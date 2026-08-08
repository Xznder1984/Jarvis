"""Local Ollama provider — no key needed, treated as infinite fallback."""
from __future__ import annotations

import os
from typing import Any

import httpx

from jarvis.providers.base import CreditStatus, LLMProvider, ProviderError, ProviderResult


class OllamaProvider(LLMProvider):
    name = "ollama"
    label = "Ollama (local)"
    is_local = True

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(api_key="", model=model or os.environ.get("OLLAMA_MODEL", "llama3.2"))
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
        url = f"{self.base_url.rstrip('/')}/api/chat"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            **{k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens", "top_p")},
        }
        try:
            resp = httpx.post(url, json=body, timeout=120.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label}: cannot reach server: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            raise ProviderError(f"{self.label}: HTTP {resp.status_code}: {resp.text[:300]}", retryable=True)

        data = resp.json()
        text = data.get("message", {}).get("content", "")
        prompt_eval = int(data.get("prompt_eval_count", 0))
        eval_count = int(data.get("eval_count", 0))
        return ProviderResult(
            text=text,
            provider=self.name,
            model=self.model,
            usage={"prompt_tokens": prompt_eval, "completion_tokens": eval_count},
        )

    def check_credit(self) -> CreditStatus:
        return CreditStatus(remaining=1.0, has_endpoint=False, detail="local; infinite credits")

    def available(self) -> bool:
        """Verify the local server is reachable (cheap HEAD)."""
        try:
            httpx.get(f"{self.base_url.rstrip('/')}/api/tags", timeout=2.0)
            return True
        except httpx.HTTPError:
            return False
