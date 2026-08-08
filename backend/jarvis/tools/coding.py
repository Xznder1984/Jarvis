"""Coding-mode orchestration helpers.

Coding mode lets JARVIS run commands (terminal), capture output, run tests, and
ask the user for feedback. Commands are executed locally via subprocess; the
backend keeps a small working directory per session.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger("jarvis.tools.coding")


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


class CodingTool:
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd or tempfile.mkdtemp(prefix="jarvis-code-")

    def run(self, command: str, timeout: int = 120) -> RunResult:
        """Run a shell command in the coding workspace and capture output."""
        logger.info("coding run: %s", command)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return RunResult(-1, "", f"Command timed out after {timeout}s")
        except OSError as exc:
            return RunResult(-1, "", str(exc))
        return RunResult(proc.returncode, proc.stdout, proc.stderr)

    def list_workspace(self) -> list[str]:
        try:
            return sorted(os.listdir(self.cwd))
        except OSError:
            return []
