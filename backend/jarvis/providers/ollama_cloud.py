"""Ollama Cloud provider adapter (`https://ollama.com/api/chat`).

Ollama's cloud API mirrors the local `/api/chat` shape (not OpenAI's
/chat/completions), so this subclasses the local adapter pattern and adds a
Bearer token. Model list is discoverable via `GET {base}/api/tags`.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from jarvis.providers.base import CreditStatus, LLMProvider, ProviderError, ProviderResult


class OllamaCloudProvider(LLMProvider):
    name = "ollama_cloud"
    label = "Ollama Cloud"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        api_key = api_key or os.environ.get(self.env_key, "")
        super().__init__(api_key=api_key, model=model or os.environ.get("OLLAMA_CLOUD_MODEL", "deepseek-v4-flash:0731"))
        self.base_url = os.environ.get("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api")

    env_key = "OLLAMA_CLOUD_API_KEY"

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
        if not self.api_key:
            raise ProviderError(f"{self.label}: no API key configured", retryable=False, code="missing_key")
        url = f"{self.base_url.rstrip('/')}/chat"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            **{k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens", "top_p")},
        }
        try:
            resp = httpx.post(url, json=body, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=120.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.label}: cannot reach server: {exc}", retryable=True) from exc

        if resp.status_code == 401:
            raise ProviderError(f"{self.label}: invalid API key (401)", retryable=False, code="auth")
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
        return CreditStatus(remaining=None, has_endpoint=False, detail="no usage endpoint")

    def available(self) -> bool:
        return bool(self.api_key)