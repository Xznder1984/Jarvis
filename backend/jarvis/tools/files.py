"""File management tool — read, write, list, search, delete, move, create directories.

All operations are restricted to the user's home directory for safety.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("jarvis.tools.files")

_HOME = Path.home()
_MAX_READ_CHARS = 8000


class FileManager:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else _HOME

    def _safe(self, path: str) -> Path:
        """Resolve and enforce the base directory boundary."""
        base = self._base.expanduser().resolve()
        try:
            p = (base / path).resolve()
            p.relative_to(base)
        except ValueError:
            raise ValueError(f"Path escapes base directory: {path}")
        return p

    def list_dir(self, path: str = ".") -> str:
        """List directory contents."""
        try:
            p = self._safe(path)
        except ValueError as e:
            return str(e)
        if not p.exists():
            return f"Directory not found: {path}"
        if not p.is_dir():
            return f"Not a directory: {path}"
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return f"Permission denied: {path}"
        lines = []
        for entry in entries[:100]:
            prefix = "DIR " if entry.is_dir() else "    "
            try:
                size = entry.stat().st_size if entry.is_file() else 0
                size_str = self._human_size(size) if entry.is_file() else ""
            except OSError:
                size_str = ""
            lines.append(f"{prefix} {entry.name} {size_str}")
        if len(entries) > 100:
            lines.append(f"  ... and {len(entries) - 100} more")
        return "\n".join(lines) if lines else "Empty directory."

    def read_file(self, path: str) -> str:
        """Read file contents (first _MAX_READ_CHARS characters)."""
        try:
            p = self._safe(path)
        except ValueError as e:
            return str(e)
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        try:
            text = p.read_text(errors="replace")[:_MAX_READ_CHARS]
        except PermissionError:
            return f"Permission denied: {path}"
        except OSError as e:
            return f"Error reading file: {e}"
        if len(text) >= _MAX_READ_CHARS:
            text += f"\n\n[truncated at {_MAX_READ_CHARS} chars]"
        return text

    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a file."""
        try:
            p = self._safe(path)
        except ValueError as e:
            return str(e)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"Wrote {len(content)} chars to {path}"
        except PermissionError:
            return f"Permission denied: {path}"
        except OSError as e:
            return f"Error writing file: {e}"

    def search_files(self, path: str = ".", pattern: str = "*") -> str:
        """Glob search for files matching a pattern."""
        try:
            base = self._safe(path)
        except ValueError as e:
            return str(e)
        if not base.is_dir():
            return f"Not a directory: {path}"
        matches = sorted(base.glob(pattern))
        if not matches:
            return f"No files matching '{pattern}' in {path}"
        lines = []
        for m in matches[:50]:
            rel = m.relative_to(base)
            prefix = "DIR " if m.is_dir() else "    "
            lines.append(f"{prefix} {rel}")
        if len(matches) > 50:
            lines.append(f"  ... and {len(matches) - 50} more")
        return "\n".join(lines)

    def delete_file(self, path: str) -> str:
        """Delete a file or empty directory."""
        try:
            p = self._safe(path)
        except ValueError as e:
            return str(e)
        if not p.exists():
            return f"Not found: {path}"
        try:
            if p.is_dir():
                p.rmdir()
                return f"Deleted directory: {path}"
            p.unlink()
            return f"Deleted file: {path}"
        except PermissionError:
            return f"Permission denied: {path}"
        except OSError as e:
            return f"Error deleting: {e}"

    def move_file(self, src: str, dst: str) -> str:
        """Move or rename a file/directory."""
        try:
            src_p = self._safe(src)
            dst_p = self._safe(dst)
        except ValueError as e:
            return str(e)
        if not src_p.exists():
            return f"Source not found: {src}"
        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_p), str(dst_p))
            return f"Moved {src} to {dst}"
        except PermissionError:
            return f"Permission denied"
        except OSError as e:
            return f"Error moving: {e}"

    def create_dir(self, path: str) -> str:
        """Create a directory (and parents)."""
        try:
            p = self._safe(path)
        except ValueError as e:
            return str(e)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return f"Created directory: {path}"
        except PermissionError:
            return f"Permission denied: {path}"
        except OSError as e:
            return f"Error creating directory: {e}"

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
