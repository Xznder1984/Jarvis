"""Minimal conversation/memory context window persisted to disk."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.conversation")

_MEMORY_FILE = Path.home() / ".jarvis" / "memory.json"


class Conversation:
    def __init__(self, max_turns: int = 20, memory_file: Path | None = None) -> None:
        self._max_turns = max_turns
        self._file = memory_file or _MEMORY_FILE
        self._lock = threading.Lock()
        self._turns: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self._file.exists():
            try:
                return json.loads(self._file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._turns[-200:], indent=2))
            os.chmod(self._file, 0o600)
        except OSError:
            logger.warning("Could not persist conversation memory")

    def add(self, role: str, content: str) -> None:
        with self._lock:
            self._turns.append({"role": role, "content": content})
            if len(self._turns) > self._max_turns:
                self._turns = self._turns[-self._max_turns:]
            self._save()

    def messages(self) -> list[dict[str, str]]:
        with self._lock:
            return [{"role": t["role"], "content": t["content"]} for t in self._turns]

    def clear(self) -> None:
        with self._lock:
            self._turns = []
            self._save()
