"""Vision package — image and video understanding.

Images go to a vision-capable LLM provider. Video is processed by extracting
frames (ffmpeg) and asking a vision-capable model to summarize the sequence.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from typing import Any

import httpx

from jarvis.providers.base import ProviderError

logger = logging.getLogger("jarvis.vision")

_VISION_MODEL_ENV = "VISION_MODEL"


def _vision_credentials() -> tuple[str, str, str]:
    """Returns (api_key, base_url, model) for a vision-capable provider.

    Prefers OpenAI-compatible Cerebras/NVIDIA/Groq; falls back to env vars.
    """
    import os

    # Allow explicit override.
    api_key = os.environ.get("VISION_API_KEY", "")
    base_url = os.environ.get("VISION_BASE_URL", "")
    model = os.environ.get(_VISION_MODEL_ENV, "")

    if api_key and base_url:
        return api_key, base_url, model or "gpt-4o"

    # Auto-pick first available key among known OpenAI-compatible providers.
    for env_key, url, default_model in (
        ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1", "llama-3.2-90b-vision-preview"),
        ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
        ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.2-90b-vision-preview"),
        ("OPENCODE_ZEN_API_KEY", "https://opencode.ai/api/v1", "gpt-4o"),
    ):
        key = os.environ.get(env_key, "")
        if key:
            return key, url, model or default_model

    raise ProviderError("No vision-capable provider configured", retryable=False, code="missing_key")


class Vision:
    def __init__(self, router=None) -> None:
        self._router = router

    def describe_image(self, image_bytes: bytes, prompt: str = "Describe what you see in this image.") -> str:
        """Send an image to a vision-capable model and return a description."""
        api_key, base_url, model = _vision_credentials()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ]
        return self._chat_vision(api_key, base_url, model, messages)

    def describe_video(self, video_path: str, prompt: str = "Summarize what happens in this video.") -> str:
        """Extract frames with ffmpeg and ask a vision model to summarize."""
        frames = _extract_frames(video_path)
        if not frames:
            return "Could not extract frames from the video."

        api_key, base_url, model = _vision_credentials()
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
        ]
        for frame_path in frames[:8]:
            with open(frame_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        messages = [{"role": "user", "content": content}]
        return self._chat_vision(api_key, base_url, model, messages)

    def _chat_vision(self, api_key: str, base_url: str, model: str, messages: list[dict]) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 800},
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Vision: network error: {exc}", retryable=True) from exc
        if resp.status_code != 200:
            raise ProviderError(f"Vision: HTTP {resp.status_code}: {resp.text[:200]}", retryable=True)
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return "No vision response."


def _extract_frames(video_path: str, count: int = 8) -> list[str]:
    """Extract up to `count` evenly-spaced JPEG frames using ffmpeg."""
    if not os.path.exists(video_path):
        logger.warning("Video file not found: %s", video_path)
        return []
    tmpdir = tempfile.mkdtemp(prefix="jarvis-frames-")
    pattern = os.path.join(tmpdir, "frame_%03d.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vf", f"thumbnail={max(1, 8)}", "-frames:v", str(count), pattern],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Frame extraction failed: %s", exc)
        return []
    frames = sorted(os.listdir(tmpdir))
    return [os.path.join(tmpdir, f) for f in frames if f.startswith("frame_")][:count]
