"""Configuration loading for the JARVIS backend.

Secrets (API keys, voice reference ids) are strictly DEVICE-LOCAL: they live in
`~/.jarvis/` (settings.json and, optionally, `~/.jarvis/.env`) and are never
written into the repo. The repo `.env` is reserved for shared non-secret
defaults. Precedence: process env > device `~/.jarvis/.env` > repo `.env` >
settings store > default.
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

# The only `.env` file UI saves may write: device-local, never the repo.
_DEVICE_ENV_FILE = _HOME_DIR / ".env"


def _repo_env_files() -> list[Path]:
    return [_REPO_ROOT / ".env", _BACKEND_DIR / ".env"]


def load_env() -> None:
    # Shared repo defaults first (first definition wins); the device-local
    # `~/.jarvis/.env` then overrides any overlap so secrets stay per-device.
    for p in _repo_env_files():
        if p.exists():
            load_dotenv(p)
    if _DEVICE_ENV_FILE.exists():
        load_dotenv(_DEVICE_ENV_FILE, override=True)


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


# Keys the Settings UI owns that should also land in .env.
_ENV_PERSISTED_KEYS = {
    "NVIDIA_API_KEY",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENCODE_ZEN_API_KEY",
    "OLLAMA_CLOUD_API_KEY",
    "FISH_AUDIO_API_KEY",
    "FISH_AUDIO_REFERENCE_ID",
}


def save_env_updates(updates: dict[str, Any]) -> Path:
    """Merge UI-saved API keys into the device-local `~/.jarvis/.env`.

    Secrets are written to the home directory so they never land in a repo
    folder that could be copied, zipped, or synced to another machine.
    Existing lines are updated in place; new keys are appended.
    """
    env_path = _DEVICE_ENV_FILE
    payload = {k: v for k, v in updates.items() if k in _ENV_PERSISTED_KEYS and v not in (None, "")}
    if not payload:
        return env_path

    text = env_path.read_text() if env_path.exists() else ""
    lines = text.splitlines()
    written: dict[str, str] = {}

    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in payload:
            out.append(f"{key}={payload[key]}")
            written[key] = payload[key]
        else:
            out.append(line)
    for key, value in payload.items():
        if key not in written:
            out.append(f"{key}={value}")

    _HOME_DIR.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(out) + ("\n" if out else ""))
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    return env_path


class Config:
    """Unified view over .env + settings store.

    Priority: explicit env var (process) > .env file > settings store > default.
    """

    def __init__(self) -> None:
        load_env()
        self._settings = load_settings()

    def _lookup(self, key: str, default: Any = None) -> Any:
        # Empty-string env values (e.g. repo .env placeholders) are treated as
        # unset so a real device-local value or settings-store value can win.
        env = os.environ.get(key)
        if env not in (None, ""):
            return env
        store = self._settings.get(key)
        if store not in (None, ""):
            return store
        return default

    def update(self, updates: dict[str, Any]) -> None:
        """Apply UI settings: merge into the settings store and mirror to env.

        Values arrive as strings from the GUI; primitives that the settings
        store expects as JSON (e.g. PROVIDER_PRIORITY) are normalized here.
        """
        merged = {**self._settings}
        for key, value in updates.items():
            if value is None:
                continue
            if key == "PROVIDER_PRIORITY":
                merged[key] = self._coerce_priority(value)
            elif isinstance(value, str) and value.strip().startswith(("true", "false", "[")):
                merged[key] = value.strip()
            else:
                merged[key] = value
        self._settings = merged
        save_settings(merged)
        # Persist API keys into the repo .env so they survive across installs.
        save_env_updates(updates)
        # Mirror into the process env so `.env`-only lookups see them too.
        for key, value in merged.items():
            if isinstance(value, (str, int, float, bool)):
                os.environ[key] = str(value)

    @staticmethod
    def _coerce_priority(value: Any) -> list[str] | None:
        """Accept a list or a JSON-encoded string and return a clean list."""
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        return None

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

    def masked_settings(self) -> dict[str, Any]:
        """Settings safe to send to the GUI: API key values replaced with flags."""
        out: dict[str, Any] = {}
        for key, value in self._settings.items():
            if key.endswith("_API_KEY") and value:
                out[key] = True
            else:
                out[key] = value
        # Always include known defaults even if unset.
        out.setdefault("STT_MODEL", "base")
        out.setdefault("LOCAL_TTS_VOICE", "Daniel")
        out.setdefault("LOCAL_TTS_RATE", 170)
        out.setdefault("WAKE_PHRASE", self.get("WAKE_PHRASE", "jarvis"))
        out.setdefault("HONORIFIC", self.get("HONORIFIC", "sir"))
        out.setdefault("IDLE_TIMEOUT_MS", self.get("IDLE_TIMEOUT_MS", 0))
        out.setdefault("IDLE_ACTION", self.get("IDLE_ACTION", "off"))
        return out
