"""TTS router tests: silent/placeholder WAVs must NOT be accepted as real audio.

Regression guard for the Edge TTS ffmpeg fallback that previously emitted an
all-zero placeholder WAV which slipped past the old size-only check and played
as silence in the GUI.
"""
from __future__ import annotations

import io
import wave

from jarvis.tts.router import _is_real_audio


def _wav(audio_bytes: bytes, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio_bytes)
    return buf.getvalue()


def test_empty_placeholder_rejected():
    """The ffmpeg-less silent fallback (all zeros) must be rejected."""
    silent = _wav(b"\x00\x00" * 4000)
    assert silent[:4] == b"RIFF"
    assert len(silent) > 4096
    assert _is_real_audio(silent) is False


def test_short_garbage_rejected():
    assert _is_real_audio(b"") is False
    assert _is_real_audio(b"RIFF" + b"\x00" * 100) is False


def test_nonzero_pcm_accepted():
    """Real speech audio (non-zero samples) always passes."""
    pcm = (b"\x00\x00" * 2000) + b"\x64\x00" + b"\x00\x00" * 200
    assert len(_wav(pcm)) > 4096
    assert _is_real_audio(_wav(pcm)) is True


def test_non_16bit_wav_rejected():
    """8-bit WAVs aren't what the pipeline produces; don't trust them."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(24000)
        w.writeframes(b"\x00" * 4000 + b"\x01")
    assert _is_real_audio(buf.getvalue()) is False