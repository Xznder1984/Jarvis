"""Cerebras provider adapter."""
from __future__ import annotations

from jarvis.providers.openai_compat import OpenAICompatibleProvider


class CerebrasProvider(OpenAICompatibleProvider):
    name = "cerebras"
    label = "Cerebras"
    base_url = "https://api.cerebras.ai/v1"
    env_key = "CEREBRAS_API_KEY"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(api_key, model or "llama-3.3-70b-versatile")
