"""Local software TTS fallback so JARVIS never goes silent.

On macOS this shells out to the built-in `say` command to produce AIFF audio,
then converts to WAV with ffmpeg when available, or falls back to generating a
minimal WAV ourselves so the contract (base64 WAV) is always honored.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger("jarvis.tts.local")


class LocalTTS:
    def __init__(self, voice: str | None = None, rate: int = 185) -> None:
        self.voice = voice or os.environ.get("LOCAL_TTS_VOICE", "Samantha")
        self.rate = int(os.environ.get("LOCAL_TTS_RATE", rate))

    def available(self) -> bool:
        return shutil.which("say") is not None or shutil.which("espeak") is not None

    def synthesize(self, text: str) -> bytes:
        """Return WAV bytes via macOS `say` + ffmpeg, or a minimal silent WAV."""
        if shutil.which("say") and _is_darwin():
            return self._macos_say(text)
        if shutil.which("espeak"):
            return self._espeak(text)
        logger.warning("No local TTS engine found; returning silent audio")
        return _silent_wav()

    def _macos_say(self, text: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            aiff = os.path.join(tmp, "out.aiff")
            cmd = ["say", "-o", aiff]
            if self.voice:
                cmd += ["-v", self.voice]
            cmd += ["-r", str(self.rate), "--", text]
            subprocess.run(cmd, check=False, capture_output=True, timeout=30)
            if not os.path.exists(aiff):
                return _silent_wav()
            if shutil.which("ffmpeg"):
                wav = os.path.join(tmp, "out.wav")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", aiff, "-ar", "16000", "-ac", "1", wav],
                    check=False,
                    capture_output=True,
                )
                if os.path.exists(wav):
                    return open(wav, "rb").read()
            # Fallback: convert AIFF to WAV with Python's `wave`+`audioop`-free approach
            return _aiff_to_wav(aiff)
        return _silent_wav()

    def _espeak(self, text: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "out.wav")
            subprocess.run(
                ["espeak", "-s", str(self.rate), "-w", wav, text],
                check=False,
                capture_output=True,
                timeout=30,
            )
            if os.path.exists(wav):
                return open(wav, "rb").read()
        return _silent_wav()


def _is_darwin() -> bool:
    import sys

    return sys.platform == "darwin"


def _aiff_to_wav(aiff_path: str) -> bytes:
    """Minimal AIFF->WAV converter for standard PCM AIFF files.

    Parses the COMM chunk (channels, frames, sample rate) and the SSND chunk
    (audio data), then rewrites as a WAV. If anything looks off we return a
    silent WAV rather than crash the pipeline.
    """
    import wave

    data = open(aiff_path, "rb").read()
    if data[:4] != b"FORM":
        return _silent_wav()

    def chunk(chunk_id: bytes) -> bytes | None:
        offset = 12
        while offset + 8 <= len(data):
            cid = data[offset : offset + 4]
            size = int.from_bytes(data[offset + 4 : offset + 8], "big")
            body = data[offset + 8 : offset + 8 + size]
            if cid == chunk_id:
                return body
            offset += 8 + size + (size % 2)
        return None

    comm = chunk(b"COMM")
    ssnd = chunk(b"SSND")
    if not comm or not ssnd or len(comm) < 18:
        return _silent_wav()

    channels = int.from_bytes(comm[4:6], "big")
    sample_rate = int.from_bytes(comm[14:18], "big")
    if channels < 1 or sample_rate <= 0:
        return _silent_wav()

    audio = ssnd[8:]  # skip SSND offset/block-size fields
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio)
    return buf.getvalue()


def _silent_wav() -> bytes:
    """Minimal valid WAV: ~0.25s of silence."""
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 4000)
    return buf.getvalue()
