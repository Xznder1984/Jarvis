"""TTSRouter: Fish Audio first, local fallback so JARVIS never goes silent.

On Fish Audio failure (401/402/429/quota or network error) we warn, then fall
back to local software TTS. Returns provider name with the audio so the shell
can surface which one spoke.
"""
from __future__ import annotations

import logging
from typing import Callable

from jarvis.providers.base import ProviderError
from jarvis.tts.fish_audio import FishAudioTTS, encode_audio
from jarvis.tts.local import LocalTTS

logger = logging.getLogger("jarvis.tts.router")


class TTSRouter:
    def __init__(self, config, on_notify: Callable[[str, str], None] | None = None) -> None:
        self._config = config
        self._on_notify = on_notify
        self.fish = FishAudioTTS(
            api_key=config.get("FISH_AUDIO_API_KEY", "") or None,
            reference_id=config.get("FISH_AUDIO_REFERENCE_ID", "") or None,
            model=config.get("FISH_AUDIO_MODEL", "fishaudio/fish-speech-1.5"),
        )
        self.local = LocalTTS(
            voice=config.get("LOCAL_TTS_VOICE", "Samantha"),
            rate=config.get_int("LOCAL_TTS_RATE", 185),
        )

    def synthesize(self, text: str) -> tuple[str, str]:
        """Returns (provider, base64-wav)."""
        if self.fish.available():
            try:
                audio = self.fish.synthesize(text)
                return "fish", encode_audio(audio)
            except ProviderError as exc:
                self._notify("warn", f"Fish Audio unavailable ({exc.code or 'error'}), using local TTS.")
                logger.warning("Fish Audio failed: %s", exc)

        audio = self.local.synthesize(text)
        return "local", encode_audio(audio)

    def _notify(self, level: str, message: str) -> None:
        if self._on_notify:
            self._on_notify(level, message)
