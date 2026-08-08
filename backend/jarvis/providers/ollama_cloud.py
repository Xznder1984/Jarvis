"""Ollama Cloud provider adapter (OpenAI-compatible)."""
from __future__ import annotations

import os

from jarvis.providers.openai_compat import OpenAICompatibleProvider


class OllamaCloudProvider(OpenAICompatibleProvider):
    name = "ollama_cloud"
    label = "Ollama Cloud"
    base_url = "https://ollama.com/api"
    env_key = "OLLAMA_CLOUD_API_KEY"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(api_key, model or os.environ.get("OLLAMA_CLOUD_MODEL", "llama3.2"))
