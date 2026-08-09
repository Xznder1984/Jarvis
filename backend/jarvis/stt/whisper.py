"""Local speech-to-text via faster-whisper (free, offline, CPU-friendly).

Chosen over paid STT APIs so voice input never depends on a billable service.
Documented in PROVIDERS.md. Models: tiny/base/small/medium; larger = better
accuracy but slower on Intel CPUs.

faster-whisper assumes 16 kHz input, but the shell captures at the device's
native rate (typically 44.1/48 kHz). We resample to 16 kHz with a cheap linear
interpolation before transcription.
"""
from __future__ import annotations

import io
import logging
import wave

import numpy as np

logger = logging.getLogger("jarvis.stt.whisper")

WHISPER_RATE = 16000


def resample_to_16k(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample a mono float array to 16 kHz using linear interpolation.

    Returns a copy; the input is left untouched. Correct for speech use.
    """
    if sample_rate == WHISPER_RATE or len(samples) < 2:
        return samples
    target_len = int(round(len(samples) * WHISPER_RATE / sample_rate))
    if target_len < 1:
        return samples
    src_idx = np.arange(len(samples))
    dst_idx = np.linspace(0, len(samples) - 1, target_len)
    return np.interp(dst_idx, src_idx, samples).astype(np.float32)


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

    def transcribe_pcm(self, pcm_bytes: bytes, sample_rate: int = WHISPER_RATE) -> str:
        """Transcribe raw 16-bit PCM mono audio (resampled to 16 kHz)."""
        model = self._load()
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != WHISPER_RATE:
            audio = resample_to_16k(audio, sample_rate)
        segments, _ = model.transcribe(audio, beam_size=1, vad_filter=True)
        return "".join(seg.text for seg in segments).strip()

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        """Transcribe a WAV file's audio."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        return self.transcribe_pcm(frames, rate)
