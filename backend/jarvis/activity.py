"""In-memory ring-buffer activity log surfaced to the GUI panel and logs."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger("jarvis.activity")


class ActivityLog:
    def __init__(self, maxlen: int = 500) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, level: str, message: str, **extra: Any) -> dict[str, Any]:
        entry = {
            "level": level if level in ("info", "warn", "error") else "info",
            "message": message,
            "ts": time.time(),
            **extra,
        }
        with self._lock:
            self._items.appendleft(entry)
        getattr(logger, entry["level"])(message)
        return entry

    def info(self, message: str, **extra: Any) -> dict[str, Any]:
        return self.add("info", message, **extra)

    def warn(self, message: str, **extra: Any) -> dict[str, Any]:
        return self.add("warn", message, **extra)

    def error(self, message: str, **extra: Any) -> dict[str, Any]:
        return self.add("error", message, **extra)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)[:limit]


activity = ActivityLog()
