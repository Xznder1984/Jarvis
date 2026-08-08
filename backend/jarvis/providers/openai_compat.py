"""Shared OpenAI-compatible HTTP adapter.

NVIDIA NIM, Groq, Cerebras, OpenCode Zen and Ollama (incl. Cloud) all expose
OpenAI-compatible `/chat/completions` endpoints, so one client class serves all
of them. Each provider module only supplies endpoint + defaults.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from jarvis.providers.base import CreditStatus, LLMProvider, ProviderError, ProviderResult


class OpenAICompatibleProvider(LLMProvider):
    """Provider speaking the OpenAI chat-completions protocol."""

    base_url: str = ""
    #: Env var name holding the key, e.g. "GROQ_API_KEY".
    env_key: str = ""
    has_credit_endpoint: bool = False

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        if api_key is None:
            api_key = os.environ.get(self.env_key, "")
        super().__init__(api_key=api_key, model=model or os.environ.get(self.env_key.replace("_API_KEY", "_MODEL"), ""))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
        if not self.api_key:
            raise ProviderError(f"{self.label}: no API key configured", retryable=False, code="missing_key")
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            **{k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens", "stream", "top_p")},
        }
        try:
            resp = httpx.post(url, headers=self._headers(), json=body, timeout=90.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label}: network error: {exc}", retryable=True) from exc

        if resp.status_code == 401:
            raise ProviderError(f"{self.label}: invalid API key (401)", retryable=False, code="auth")
        if resp.status_code == 429:
            raise ProviderError(f"{self.label}: rate limited / out of quota (429)", retryable=True, code="quota")
        if resp.status_code != 200:
            raise ProviderError(
                f"{self.label}: HTTP {resp.status_code}: {resp.text[:300]}", retryable=True
            )

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.label}: malformed response", retryable=True) from exc

        usage = data.get("usage") or {}
        return ProviderResult(
            text=text,
            provider=self.name,
            model=self.model,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
            },
        )

    def check_credit(self) -> CreditStatus:
        """No programmatic endpoint: return local-estimate placeholder.

        Providers without a usage endpoint are tracked via rolling token
        estimates in the router. This method exists to keep the interface
        uniform; see PROVIDERS.md.
        """
        return CreditStatus(remaining=None, has_endpoint=False, detail="no usage endpoint; local estimate")

    def available(self) -> bool:
        return bool(self.api_key)
