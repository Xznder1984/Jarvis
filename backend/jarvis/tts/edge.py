"""Edge TTS adapter — free online neural voice via Microsoft Edge's endpoint.

Used as the middle fallback between Fish Audio (needs credits) and the local
macOS `say`. Crisp, non-robotic British male by default (Ryan) which reads
closer to JARVIS than any built-in OS voice. Requires network; on failure the
router treats it like Fish and falls back to local synthesis.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import subprocess
import tempfile

from jarvis.providers.base import ProviderError

logger = logging.getLogger("jarvis.tts.edge")

#: k = "rate", "pitch" accept values like "+10%", "-30Hz" (SSML-style).
_JARVIS_VOICE = "en-GB-RyanNeural"

#: launchd/LaunchAgents run with a minimal PATH that often hides Homebrew's
#: /usr/local/bin, so resolve ffmpeg explicitly instead of trusting $PATH.
_FFMPEG_CANDIDATES = (
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/bin/ffmpeg",
)


def _find_ffmpeg() -> str | None:
    hit = shutil.which("ffmpeg")
    if hit:
        return hit
    for candidate in _FFMPEG_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class EdgeTTS:
    def __init__(
        self,
        voice: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> None:
        self.voice = voice or os.environ.get("EDGE_TTS_VOICE", _JARVIS_VOICE)
        self.rate = rate or os.environ.get("EDGE_TTS_RATE", "+0%")
        self.pitch = pitch or os.environ.get("EDGE_TTS_PITCH", "-8Hz")

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return _find_ffmpeg() is not None or self._has_ffmpeg_py()

    def _has_ffmpeg_py(self) -> bool:
        try:
            import ffmpeg  # noqa: F401

            return True
        except ImportError:
            return False

    def synthesize(self, text: str) -> bytes:
        """Return WAV bytes (24 kHz mono 16-bit) via Edge + ffmpeg."""
        try:
            import edge_tts  # noqa: F401
        except ImportError as exc:
            raise ProviderError("Edge TTS: package not installed", retryable=False, code="missing_pkg") from exc

        try:
            mp3 = asyncio.run(_edge_to_mp3(text, self.voice, self.rate, self.pitch))
        except Exception as exc:
            raise ProviderError(f"Edge TTS: request failed: {exc}", retryable=True) from exc

        if not mp3:
            raise ProviderError("Edge TTS: empty audio", retryable=True)
        return _mp3_to_wav(mp3)


async def _edge_to_mp3(text: str, voice: str, rate: str, pitch: str) -> bytes:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume="+0%")
    buf = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def _mp3_to_wav(mp3: bytes) -> bytes:
    """Convert Edge's MP3 into a 24 kHz mono PCM WAV via ffmpeg."""
    env = os.environ.copy()
    # Forking ffmpeg while faster-whisper's OpenMP threads are active is
    # hazardous (OMP Warning #191, possible stalls); skip OpenMP re-init in
    # the child to keep the fork cheap and safe.
    env.setdefault("KMP_INIT_AT_FORK", "FALSE")
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        with tempfile.TemporaryDirectory() as tmp:
            src = f"{tmp}/in.mp3"
            dst = f"{tmp}/out.wav"
            open(src, "wb").write(mp3)
            proc = subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", src, "-ar", "24000",
                 "-ac", "1", "-sample_fmt", "s16", dst],
                capture_output=True, timeout=60, env=env,
            )
            if proc.returncode == 0 and os.path.exists(dst):
                return open(dst, "rb").read()
            logger.warning("ffmpeg conversion failed: %s", proc.stderr.decode(errors="replace")[:200])

    # Last resort: minimal silent WAV so the contract still holds.
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 4000)
    return buf.getvalue()