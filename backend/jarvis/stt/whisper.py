"""Local speech-to-text via faster-whisper (free, offline, CPU-friendly).

Chosen over paid STT APIs so voice input never depends on a billable service.
Documented in PROVIDERS.md. Models: tiny/base/small/medium; larger = better
accuracy but slower on Intel CPUs.
"""
from __future__ import annotations

import io
import logging
import wave

import numpy as np

logger = logging.getLogger("jarvis.stt.whisper")


class WhisperSTT:
    """Lazy-loaded faster-whisper wrapper."""

    def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
        self._model_size = model_size
        self._device = device
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '%s' (device=%s)...", self._model_size, self._device)
            self._model = WhisperModel(self._model_size, device=self._device)
        return self._model

    def transcribe_pcm(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe raw 16-bit PCM mono audio."""
        model = self._load()
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(audio, beam_size=1, vad_filter=True)
        return "".join(seg.text for seg in segments).strip()

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        """Transcribe a WAV file's audio."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        return self.transcribe_pcm(frames, rate)
