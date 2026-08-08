"""Mode state machine: normal <-> coding.

Coding mode is triggered when the user's request looks like a coding task, or
explicitly via a voice command. It auto-returns to normal when the task wraps up
or on explicit command.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger("jarvis.modes")

_CODING_PATTERNS = re.compile(
    r"\b(code|coding|debug|debugging|fix(?: the)? (?:bug|error)|write (?:a|the)? (?:function|script|program|"
    r"app)|test(?:ing)?|compile|build|refactor|git|terminal|shell command|run (?:this|the)? (?:app|script)"
    r"|stack trace|error message|syntax)\b",
    re.IGNORECASE,
)


class ModeState:
    def __init__(self, on_change: Callable[[str], None] | None = None) -> None:
        self._mode = "normal"
        self._on_change = on_change

    @property
    def mode(self) -> str:
        return self._mode

    def set(self, mode: str) -> bool:
        mode = "coding" if mode == "coding" else "normal"
        if mode == self._mode:
            return False
        self._mode = mode
        logger.info("Mode switch -> %s", mode)
        if self._on_change:
            self._on_change(mode)
        return True

    def switch_to_coding(self) -> bool:
        return self.set("coding")

    def switch_to_normal(self) -> bool:
        return self.set("normal")

    def classify(self, text: str) -> None:
        """Auto-enter coding mode if the request looks like a coding task."""
        if self._mode == "normal" and _CODING_PATTERNS.search(text):
            self.set("coding")
