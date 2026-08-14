"""Central logging configuration for the JARVIS backend.

Writes to both the console and a rotating file under ~/.jarvis/logs/. All
records pass through a redaction formatter so API keys and bearer tokens never
reach the log file, the console, or the GUI.

Settings:
    JARVIS_LOG_LEVEL      (default INFO)
    JARVIS_LOG_DIR        (default ~/.jarvis/logs)
    JARVIS_LOG_MAX_BYTES  (default 5 MiB per file)
    JARVIS_LOG_BACKUPS    (default 3 rotated files)
"""
from __future__ import annotations

import logging
import logging.handlers
import re
import threading
from pathlib import Path

from jarvis.config import Config

# Redaction patterns for secrets that must never be persisted to disk.
# Each is (regex, replacement). Replacement preserves the key's prefix/suffix
# so logs stay greppable without leaking the payload.
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[\"']?([^\s\"',}]+)"), r"\1=<redacted>"),
    (re.compile(r"sk-[A-Za-z0-9]{12,}"), "sk-***"),
    (re.compile(r"csk-[A-Za-z0-9]{12,}"), "csk-***"),
    (re.compile(r"ghp_[A-Za-z0-9]{24,}"), "ghp_***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    (re.compile(r"(?i)x-subscription-token:\s*\S+"), "X-Subscription-Token: <redacted>"),
]


def redact(message: str) -> str:
    """Mask secrets in a single log line."""
    out = str(message)
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


class RedactingFormatter(logging.Formatter):
    """Formatter that applies `redact()` to every record before formatting."""

    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact(record.getMessage())
        record.args = ()
        return super().format(record)


_logger_cache: dict[str, logging.Logger] = {}
_setup_lock = threading.Lock()


def setup_logging(config: Config | None = None) -> str:
    """Configure the 'jarvis' logger tree. Idempotent; returns the log dir."""
    with _setup_lock:
        config = config or Config()
        log_dir = Path(config.get("JARVIS_LOG_DIR", Path.home() / ".jarvis" / "logs")).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)

        level = config.log_level.upper()
        log_path = log_dir / "jarvis-backend.log"

        root = logging.getLogger("jarvis")
        if root.handlers:
            return str(log_dir)  # already configured (e.g. reload in tests)

        root.setLevel(level)
        root.propagate = False

        fmt = RedactingFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")

        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=config.get_int("JARVIS_LOG_MAX_BYTES", 5 * 1024 * 1024),
                backupCount=config.get_int("JARVIS_LOG_BACKUPS", 3),
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except OSError:
            # Never crash the backend because logging failed.
            root.warning("Could not open log file at %s; console only", log_path)

        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        return str(log_dir)


def get_logger(name: str) -> logging.Logger:
    """Return a cached module logger under the 'jarvis' tree."""
    if name not in _logger_cache:
        _logger_cache[name] = logging.getLogger(f"jarvis.{name}")
    return _logger_cache[name]


def set_log_level(level: str) -> None:
    """Change the backend log level at runtime."""
    numeric = getattr(logging, str(level).upper(), None)
    if not isinstance(numeric, int):
        raise ValueError(f"invalid log level: {level}")
    logging.getLogger("jarvis").setLevel(numeric)


def current_log_level() -> str:
    return logging.getLevelName(logging.getLogger("jarvis").level)
