"""System-action orchestration.

The backend never performs OS actions directly — it issues `action_request`
messages to the Rust shell, which owns platform-specific execution (open app,
sleep, shutdown, screen capture). This module defines the set of available
actions and how to ask for them.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger("jarvis.tools.system")

# Recognized actions -> description for the LLM.
ACTIONS: dict[str, str] = {
    "open_app": "Launch an application (arg: app name or path)",
    "open_path": "Open a file/folder in the default app (arg: path)",
    "sleep": "Put the machine to sleep",
    "shutdown": "Shut down the machine",
    "screen_capture": "Capture the current screen and return a base64 PNG",
    "system_info": "Return basic system info (OS, hostname)",
}

_OPEN_PATTERNS = re.compile(
    r"^(?:please\s+)?(?:open|launch|start|run)\s+(?:the\s+)?app(?:lication)?\s*['\"]?([^'\"]+?)['\"]?$",
    re.IGNORECASE,
)


def parse_open_command(text: str) -> str | None:
    """Extract an app name from 'open the app X' style commands."""
    m = _OPEN_PATTERNS.search(text.strip())
    if m:
        return m.group(1).strip().strip(".")
    return None


class SystemActions:
    def __init__(self, request_action: Callable[[str, dict[str, Any]], Any] | None = None) -> None:
        self._request = request_action or (lambda action, args: logger.info("action %s %s", action, args))

    def open_app(self, app: str) -> Any:
        return self._request("open_app", {"app": app})

    def open_path(self, path: str) -> Any:
        return self._request("open_path", {"path": path})

    def sleep(self) -> Any:
        return self._request("sleep", {})

    def shutdown(self) -> Any:
        return self._request("shutdown", {})

    def screen_capture(self) -> Any:
        return self._request("screen_capture", {})
