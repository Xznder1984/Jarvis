"""Fish Audio TTS adapter.

Primary TTS provider. Returns a WAV (PCM 16-bit) that the Rust shell plays.
Set FISH_AUDIO_API_KEY in .env or Settings.
"""
from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

import httpx

from jarvis.providers.base import ProviderError

logger = logging.getLogger("jarvis.tts.fish")

_BASE_URL = "https://api.fish.audio"

# JARVIS (MCU) voice from the reference "djbaril/jarvis" project — used as the
# default when no reference id is configured.
_JARVIS_REFERENCE_ID = "612b878b113047d9a770c069c8b4fdfe"


class FishAudioTTS:
    def __init__(self, api_key: str | None = None, reference_id: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FISH_AUDIO_API_KEY", "")
        self.reference_id = (
            reference_id
            or os.environ.get("FISH_AUDIO_REFERENCE_ID", "")
            or _JARVIS_REFERENCE_ID
        )
        self.model = model or os.environ.get("FISH_AUDIO_MODEL", "fishaudio/fish-speech-1.5")

    def available(self) -> bool:
        return bool(self.api_key)

    def synthesize(self, text: str) -> bytes:
        """Synthesize text to WAV bytes."""
        if not self.api_key:
            raise ProviderError("Fish Audio: no API key configured", retryable=False, code="missing_key")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload: dict[str, Any] = {"text": text, "model": self.model, "format": "wav"}
        if self.reference_id:
            payload["reference_id"] = self.reference_id
        try:
            resp = httpx.post(f"{_BASE_URL}/v1/tts", headers=headers, json=payload, timeout=60.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Fish Audio: network error: {exc}", retryable=True) from exc

        if resp.status_code in (401, 402, 403):
            raise ProviderError(
                f"Fish Audio: auth/payment error ({resp.status_code})", retryable=False, code="quota"
            )
        if resp.status_code != 200:
            raise ProviderError(f"Fish Audio: HTTP {resp.status_code}: {resp.text[:200]}", retryable=True)

        content = resp.content
        # API may return raw WAV bytes directly; if not, wrap.
        if not content.startswith(b"RIFF"):
            content = _wrap_wav(content)
        return content


def _wrap_wav(audio_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Best-effort: wrap raw PCM into a RIFF/WAV container if needed."""
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio_bytes)
    return buf.getvalue()


def encode_audio(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")
