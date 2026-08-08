"""NVIDIA NIM provider adapter."""
from __future__ import annotations

from jarvis.providers.openai_compat import OpenAICompatibleProvider


class NvidiaProvider(OpenAICompatibleProvider):
    name = "nvidia"
    label = "NVIDIA NIM"
    base_url = "https://integrate.api.nvidia.com/v1"
    env_key = "NVIDIA_API_KEY"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(api_key, model or "meta/llama-3.3-70b-instruct")
