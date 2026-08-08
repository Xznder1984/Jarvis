"""ProviderRouter: priority-ordered LLM routing with credit monitoring + failover.

Behavior:
- Reads API keys from config (.env / settings store).
- Uses a user-reorderable priority list (default: groq, nvidia, cerebras,
  opencode_zen, ollama_cloud, then local ollama).
- Before each request, refreshes credit estimates for providers that expose a
  usage endpoint; for others uses rolling local token-based estimates persisted
  to a gitignored file.
- On low credit (< threshold) or an error (401/429/insufficient_quota), fails
  over to the next provider, logging and notifying via callbacks.
- When everything cloud/paid is exhausted, falls back to local Ollama.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from jarvis.providers.base import CreditStatus, LLMProvider, ProviderError
from jarvis.providers import (
    CerebrasProvider,
    GroqProvider,
    NvidiaProvider,
    OllamaCloudProvider,
    OllamaProvider,
    OpenCodeZenProvider,
)

logger = logging.getLogger("jarvis.router")

# Rolling local free-tier budgets (tokens per month) used when the provider has
# no usage endpoint. Values are documented in PROVIDERS.md.
FREE_TIER_BUDGETS: dict[str, int] = {
    "groq": 100_000_000,       # Groq free tier (approx, tokens/day scaled)
    "cerebras": 10_000_000,
    "nvidia": 5_000_000,
    "opencode_zen": 10_000_000,
    "ollama_cloud": 10_000_000,
}

_USAGE_FILE = Path.home() / ".jarvis" / "usage.json"


def _default_priority() -> list[str]:
    return ["groq", "nvidia", "cerebras", "opencode_zen", "ollama_cloud"]


class ProviderRouter:
    def __init__(
        self,
        config: Any,
        *,
        on_notify: Callable[[str, str], None] | None = None,
        on_provider_update: Callable[[str, str, float | None], None] | None = None,
    ) -> None:
        self._config = config
        self._on_notify = on_notify
        self._on_provider_update = on_provider_update
        self._lock = threading.Lock()
        self._usage = self._load_usage()
        self.providers: dict[str, LLMProvider] = self._build_providers()
        self.active_provider: str | None = None
        self.priority = self._load_priority()

    # ------------------------------------------------------------------ setup
    def _build_providers(self) -> dict[str, LLMProvider]:
        keys = self._config.api_keys
        env = {
            "groq": "GROQ_API_KEY",
            "nvidia": "NVIDIA_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "opencode_zen": "OPENCODE_ZEN_API_KEY",
            "ollama_cloud": "OLLAMA_CLOUD_API_KEY",
        }
        specs: list[tuple[str, type[LLMProvider]]] = [
            ("groq", GroqProvider),
            ("nvidia", NvidiaProvider),
            ("cerebras", CerebrasProvider),
            ("opencode_zen", OpenCodeZenProvider),
            ("ollama_cloud", OllamaCloudProvider),
            ("ollama", OllamaProvider),
        ]
        providers: dict[str, LLMProvider] = {}
        for name, cls in specs:
            env_name = env.get(name, f"{name.upper()}_API_KEY")
            provider = cls(api_key=keys.get(env_name, "") or None)
            providers[name] = provider
        return providers

    def _load_usage(self) -> dict[str, dict[str, Any]]:
        if _USAGE_FILE.exists():
            try:
                return json.loads(_USAGE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_usage(self) -> None:
        try:
            _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _USAGE_FILE.write_text(json.dumps(self._usage, indent=2))
            os.chmod(_USAGE_FILE, 0o600)
        except OSError:
            logger.warning("Could not persist usage store")

    def _load_priority(self) -> list[str]:
        order = self._config.get("PROVIDER_PRIORITY")
        if isinstance(order, list) and order:
            return [p for p in order if p in self.providers]
        return _default_priority()

    # ------------------------------------------------------------- interface
    def reorder(self, new_order: list[str]) -> None:
        with self._lock:
            self.priority = [p for p in new_order if p in self.providers]

    def set_provider_model(self, name: str, model: str) -> None:
        if name in self.providers:
            self.providers[name].model = model

    def provider_names(self) -> list[str]:
        return [p for p in self.priority if self.providers[p].available()]

    # ----------------------------------------------------------- credit logic
    def credit_for(self, name: str) -> CreditStatus:
        provider = self.providers.get(name)
        if provider is None:
            return CreditStatus(remaining=None)
        if provider.is_local:
            return CreditStatus(remaining=1.0, has_endpoint=False, detail="local; infinite")
        if provider.has_credit_endpoint:
            return provider.check_credit()
        return self._local_estimate(name)

    def _local_estimate(self, name: str) -> CreditStatus:
        budget = FREE_TIER_BUDGETS.get(name)
        if budget is None:
            return CreditStatus(remaining=None, detail="no budget known")
        used = self._usage.get(name, {}).get("prompt", 0) + self._usage.get(name, {}).get("completion", 0)
        remaining = max(0.0, 1.0 - used / budget)
        return CreditStatus(remaining=remaining, has_endpoint=False, detail="rolling token estimate")

    def _is_low(self, status: CreditStatus) -> bool:
        if status.remaining is None:
            return False
        return status.remaining <= self._config.credit_low_threshold

    # --------------------------------------------------------------- chat
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, str]:
        """Route a conversation. Returns (text, provider_name)."""
        with self._lock:
            order = list(self.priority) + ["ollama"]
            last_error: str | None = None

            for name in order:
                if name == "ollama":
                    provider = self.providers.get("ollama")
                    if provider is None:
                        last_error = "local Ollama not configured"
                        continue
                    if not provider.available():
                        last_error = "local Ollama server not reachable"
                        continue
                    return self._invoke(provider, messages, **kwargs)

                if name not in self.providers or not self.providers[name].available():
                    continue

                status = self.credit_for(name)
                if self._is_low(status):
                    self._notify(
                        "warn",
                        f"{self.providers[name].label} credits low "
                        f"({status.remaining:.0%}), switching.",
                    )
                    self._emit_provider_update(name, "low", status.remaining)
                    continue

                provider = self.providers[name]
                try:
                    result = self._invoke(provider, messages, **kwargs)
                    self._emit_provider_update(name, "active", status.remaining)
                    return result
                except ProviderError as exc:
                    last_error = str(exc)
                    self._notify(
                        "warn",
                        f"{provider.label} failed ({exc.code or exc}), switching providers.",
                    )
                    self._emit_provider_update(name, "exhausted", status.remaining)
                    continue

            raise ProviderError(f"All providers exhausted. Last error: {last_error}", retryable=False)

    def _invoke(self, provider: LLMProvider, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, str]:
        self._notify("info", f"Routing through {provider.label}")
        result = provider.chat(messages, **kwargs)
        if not provider.is_local:
            self._record_usage(provider.name, result.usage)
        self.active_provider = provider.name
        return result.text, provider.name

    def _record_usage(self, name: str, usage: dict[str, int]) -> None:
        entry = self._usage.setdefault(name, {"prompt": 0, "completion": 0})
        entry["prompt"] += int(usage.get("prompt_tokens", 0))
        entry["completion"] += int(usage.get("completion_tokens", 0))
        self._save_usage()

    # -------------------------------------------------------------- callbacks
    def _notify(self, level: str, message: str) -> None:
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
        if self._on_notify:
            self._on_notify(level, message)

    def _emit_provider_update(self, name: str, state: str, remaining: float | None) -> None:
        if self._on_provider_update:
            self._on_provider_update(name, state, remaining)
