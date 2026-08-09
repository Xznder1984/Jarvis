"""Unified log broker: aggregates log records from every layer.

Backend, Rust shell, and the frontend all publish log entries here. The broker
keeps a ring buffer (surfaced via REST/WS for the GUI log panel) and broadcasts
each entry to connected WebSocket subscribers as a `log` envelope.

Sources: "backend" (Python logging), "shell" (Rust), "frontend" (browser).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Awaitable, Callable

from jarvis.logging_setup import redact

logger = logging.getLogger("jarvis.logs")

Subscriber = Callable[[dict[str, Any]], Awaitable[None]]

_VALID_LEVELS = {"debug", "info", "warn", "error"}


def _normalize_level(level: str) -> str:
    if level in _VALID_LEVELS:
        return level
    if level.lower() == "warning":
        return "warn"
    return "info"


class LogBroker:
    def __init__(self, maxlen: int = 1000) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._subscribers: set[Subscriber] = set()

    # ------------------------------------------------------------- publish
    def publish(self, level: str, message: str, source: str = "backend", **extra: Any) -> dict[str, Any]:
        level = _normalize_level(level)
        entry: dict[str, Any] = {
            "level": level,
            "message": redact(message),
            "source": source,
            "ts": time.time(),
            **extra,
        }
        with self._lock:
            self._items.appendleft(entry)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                asyncio_create_task(subscriber, entry)
            except Exception:  # noqa: BLE001
                pass
        return entry

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)[:limit]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    # --------------------------------------------------------- subscribers
    def subscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)


def asyncio_create_task(coro: Callable[[], Awaitable[None]], entry: dict[str, Any]) -> None:
    """Schedule an async subscriber without blocking the calling thread.

    The subscriber callables are async (WS sends). We must be careful: publish()
    may be called from sync threads, so we bridge through the running loop when
    possible and swallow otherwise.
    """
    try:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(coro(entry))
        else:
            # Called from a non-async thread; skip broadcast for that entry.
            pass
    except Exception:  # noqa: BLE001
        pass


class LogBridgeHandler(logging.Handler):
    """Python logging handler that mirrors every backend record into the broker."""

    def __init__(self, broker: LogBroker, min_level: int = logging.INFO) -> None:
        super().__init__(level=min_level)
        self._broker = broker

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = record.levelname.lower()
            if level == "warning":
                level = "warn"
            self._broker.publish(level, record.getMessage(), source="backend")
        except Exception:  # noqa: BLE001
            pass


broker = LogBroker()
