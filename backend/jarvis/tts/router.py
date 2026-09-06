"""TTSRouter: Fish Audio first, then Edge TTS, then local `say` so JARVIS
never goes silent.

On Fish Audio failure (401/402/429/quota or network error) we warn and fall
back to Edge TTS (free online neural voice); if Edge is unreachable we fall
back to local software TTS. Returns provider name with the audio so the shell
can surface which one spoke.
"""
from __future__ import annotations

import logging
from typing import Callable

from jarvis.providers.base import ProviderError
from jarvis.tts.fish_audio import FishAudioTTS, encode_audio
from jarvis.tts.edge import EdgeTTS
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
        self.edge = EdgeTTS(
            voice=config.get("EDGE_TTS_VOICE", "") or None,
            rate=config.get("EDGE_TTS_RATE", "") or None,
            pitch=config.get("EDGE_TTS_PITCH", "") or None,
        )
        self.local = LocalTTS(
            voice=config.get("LOCAL_TTS_VOICE", "Thomas"),
            rate=config.get_int("LOCAL_TTS_RATE", 185),
        )

    def synthesize(self, text: str) -> tuple[str, str]:
        """Returns (provider, base64-wav)."""
        if self.fish.available():
            try:
                audio = self.fish.synthesize(text)
                return "fish", encode_audio(audio)
            except ProviderError as exc:
                self._notify("warn", f"Fish Audio unavailable ({exc.code or 'error'}), trying Edge TTS.")
                logger.warning("Fish Audio failed: %s", exc)

        if self.edge.available():
            try:
                audio = self.edge.synthesize(text)
                if _is_real_audio(audio):
                    return "edge", encode_audio(audio)
            except ProviderError as exc:
                logger.warning("Edge TTS failed: %s", exc)

        audio = self.local.synthesize(text)
        return "local", encode_audio(audio)

    def _notify(self, level: str, message: str) -> None:
        if self._on_notify:
            self._on_notify(level, message)


def _is_real_audio(wav: bytes) -> bool:
    """Silent fallback (placeholder wav) means the converter gave up."""
    return wav[:4] == b"RIFF" and len(wav) > 4096
