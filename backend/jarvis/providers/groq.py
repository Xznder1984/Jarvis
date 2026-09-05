"""Groq provider adapter."""
from __future__ import annotations

import os

from jarvis.providers.openai_compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    label = "Groq"
    base_url = "https://api.groq.com/openai/v1"
    env_key = "GROQ_API_KEY"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(api_key, model or os.environ.get("GROQ_MODEL", "groq/compound-mini"))
