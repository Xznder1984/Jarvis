"""OpenCode Zen provider adapter."""
from __future__ import annotations

from jarvis.providers.openai_compat import OpenAICompatibleProvider


class OpenCodeZenProvider(OpenAICompatibleProvider):
    name = "opencode_zen"
    label = "OpenCode Zen"
    base_url = "https://opencode.ai/zen/v1"
    env_key = "OPENCODE_ZEN_API_KEY"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(api_key, model or "mimo-v2.5-free")
