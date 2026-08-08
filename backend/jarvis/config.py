"""Configuration loading for the JARVIS backend.

Supports both a gitignored local settings store (written by the Settings UI
and mirrored by the Tauri shell) and a plain `.env` file for power users.
The `.env` file takes precedence for any key it defines.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Backend runs from the repo's backend/ dir or from repo root; search both.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_HOME_DIR = Path.home() / ".jarvis"
_SETTINGS_FILE = _HOME_DIR / "settings.json"


def _candidate_env_files() -> list[Path]:
    return [
        _REPO_ROOT / ".env",
        _BACKEND_DIR / ".env",
        _HOME_DIR / ".env",
    ]


def load_env() -> None:
    for p in _candidate_env_files():
        if p.exists():
            load_dotenv(p)


def load_settings() -> dict[str, Any]:
    """Load the local settings store (encrypted-lite: permissions locked)."""
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(settings: dict[str, Any]) -> None:
    _HOME_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
    # Tighten permissions so the file is user-only readable.
    os.chmod(_SETTINGS_FILE, 0o600)


class Config:
    """Unified view over .env + settings store.

    Priority: explicit env var (process) > .env file > settings store > default.
    """

    def __init__(self) -> None:
        load_env()
        self._settings = load_settings()

    def _lookup(self, key: str, default: Any = None) -> Any:
        if key in os.environ:
            return os.environ.get(key)
        if key in self._settings:
            return self._settings[key]
        return default

    def get(self, key: str, default: Any = None) -> Any:
        return self._lookup(key, default)

    def get_float(self, key: str, default: float) -> float:
        try:
            return float(self._lookup(key, default))
        except (TypeError, ValueError):
            return default

    def get_int(self, key: str, default: int) -> int:
        try:
            return int(self._lookup(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool) -> bool:
        raw = self._lookup(key, default)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    # --- Convenience accessors used across the backend ---
    @property
    def ws_host(self) -> str:
        return str(self.get("JARVIS_WS_HOST", "127.0.0.1"))

    @property
    def ws_port(self) -> int:
        return self.get_int("JARVIS_WS_PORT", 8765)

    @property
    def log_level(self) -> str:
        return str(self.get("JARVIS_LOG_LEVEL", "INFO"))

    @property
    def credit_low_threshold(self) -> float:
        return self.get_float("CREDIT_LOW_THRESHOLD", 0.10)

    @property
    def api_keys(self) -> dict[str, str]:
        keys = {}
        for name in (
            "NVIDIA_API_KEY",
            "GROQ_API_KEY",
            "CEREBRAS_API_KEY",
            "OPENCODE_ZEN_API_KEY",
            "OLLAMA_CLOUD_API_KEY",
        ):
            value = self.get(name, "")
            if value:
                keys[name] = value
        return keys

    @property
    def settings_store_path(self) -> Path:
        return _SETTINGS_FILE

    @property
    def settings(self) -> dict[str, Any]:
        return self._settings
