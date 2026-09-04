"""Schedule and reminders tool — set reminders, timers, list and cancel.

Reminders persist in ~/.jarvis/reminders.json. Timers are in-memory
(asyncio tasks) that fire once and are removed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger("jarvis.tools.schedule")

_REMINDERS_FILE = Path.home() / ".jarvis" / "reminders.json"


class Scheduler:
    def __init__(
        self,
        on_remind: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._on_remind = on_remind
        self._timers: dict[str, asyncio.Task] = {}

    # ── persistence ──────────────────────────────────────────────────
    def _load(self) -> list[dict[str, Any]]:
        if _REMINDERS_FILE.exists():
            try:
                return json.loads(_REMINDERS_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save(self, reminders: list[dict[str, Any]]) -> None:
        try:
            _REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _REMINDERS_FILE.write_text(json.dumps(reminders, indent=2))
        except OSError:
            logger.warning("Could not save reminders")

    # ── public API ───────────────────────────────────────────────────
    def set_reminder(self, time_str: str, message: str) -> str:
        """Set a reminder. time_str can be:
        - ISO format: '2025-12-25T09:00'
        - Relative: '30m', '2h', '1h30m'
        """
        try:
            target = self._parse_time(time_str)
        except ValueError as e:
            return f"Could not parse time: {e}"

        rid = str(uuid.uuid4())[:8]
        reminder = {
            "id": rid,
            "time": target.isoformat(),
            "message": message,
            "created": datetime.now().isoformat(),
        }
        reminders = self._load()
        reminders.append(reminder)
        self._save(reminders)

        # Schedule in-memory timer
        delay = (target - datetime.now()).total_seconds()
        if delay > 0:
            self._schedule_timer(rid, delay, message)

        return f"Reminder set for {target.strftime('%I:%M %p')}: {message}"

    def set_timer(self, duration_str: str, message: str = "") -> str:
        """Set a countdown timer. duration_str: '30s', '5m', '2h', '90' (seconds)."""
        seconds = self._parse_duration(duration_str)
        if seconds <= 0:
            return "Duration must be positive."
        if not message:
            message = "Timer's up!"
        rid = str(uuid.uuid4())[:8]
        self._schedule_timer(rid, seconds, message)
        mins, secs = divmod(int(seconds), 60)
        hrs, mins = divmod(mins, 60)
        human = f"{hrs}h {mins}m {secs}s" if hrs else (f"{mins}m {secs}s" if mins else f"{secs}s")
        return f"Timer set for {human}: {message}"

    def list_reminders(self) -> str:
        """List all pending reminders."""
        reminders = self._load()
        now = datetime.now()
        pending = []
        for r in reminders:
            try:
                t = datetime.fromisoformat(r["time"])
                if t > now:
                    pending.append(r)
            except (ValueError, KeyError):
                pending.append(r)
        # Clean expired
        self._save(pending)

        if not pending and not self._timers:
            return "No pending reminders or timers."
        lines = []
        for r in pending:
            try:
                t = datetime.fromisoformat(r["time"])
                delta = t - now
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m, s = divmod(rem, 60)
                when = f"in {h}h {m}m" if h else f"in {m}m {s}s"
            except (ValueError, KeyError):
                when = "unknown"
            lines.append(f"[{r['id']}] {when} — {r['message']}")
        if self._timers:
            lines.append(f"  + {len(self._timers)} active countdown timer(s)")
        return "\n".join(lines)

    def cancel_reminder(self, rid: str) -> str:
        """Cancel a reminder or timer by ID."""
        # Try in-memory timers first
        if rid in self._timers:
            task = self._timers[rid]
            if task is not None:
                task.cancel()
            del self._timers[rid]
            return f"Timer {rid} cancelled."

        # Try persisted reminders
        reminders = self._load()
        found = False
        for r in reminders:
            if r.get("id") == rid:
                reminders.remove(r)
                found = True
                break
        if found:
            self._save(reminders)
            return f"Reminder {rid} cancelled."
        return f"No reminder or timer with ID: {rid}"

    # ── internal ─────────────────────────────────────────────────────
    def _schedule_timer(self, rid: str, delay_seconds: float, message: str) -> None:
        async def _fire():
            try:
                await asyncio.sleep(delay_seconds)
            except asyncio.CancelledError:
                return

            async def _fire_callback():
                self._timers.pop(rid, None)
                logger.info("Timer %s fired: %s", rid, message)
                if self._on_remind:
                    try:
                        await self._on_remind(message)
                    except Exception:  # noqa: BLE001
                        logger.warning("Reminder callback failed", exc_info=True)

            await _fire_callback()

        coro = _fire()
        try:
            task = asyncio.create_task(coro)
            self._timers[rid] = task
        except RuntimeError:
            # No running event loop (e.g. called from a sync context). Spawn a
            # dedicated thread loop for this one-shot timer.
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
            self._timers[rid] = None  # tracked but not cancellable

    def _parse_time(self, s: str) -> datetime:
        s = s.strip()
        # Try ISO format first
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
        # Relative: 30m, 2h, 1h30m
        delta = self._parse_duration(s)
        return datetime.now() + timedelta(seconds=delta)

    def _parse_duration(self, s: str) -> float:
        s = s.strip().lower()
        if not s:
            raise ValueError("Empty duration")
        # Pure number = seconds
        if s.isdigit():
            return float(s)
        total = 0.0
        current = ""
        for ch in s:
            if ch.isdigit() or ch == ".":
                current += ch
            elif ch == "h":
                total += float(current or 0) * 3600
                current = ""
            elif ch == "m":
                total += float(current or 0) * 60
                current = ""
            elif ch == "s":
                total += float(current or 0)
                current = ""
            else:
                raise ValueError(f"Unknown duration character: {ch}")
        # If trailing number without unit, treat as seconds
        if current:
            total += float(current)
        if total <= 0:
            raise ValueError("Duration must be positive")
        return total

    def resume_persisted(self) -> int:
        """On startup, re-schedule any persisted reminders that haven't expired."""
        reminders = self._load()
        now = datetime.now()
        active = []
        count = 0
        for r in reminders:
            try:
                t = datetime.fromisoformat(r["time"])
                delay = (t - now).total_seconds()
                if delay > 0:
                    active.append(r)
                    self._schedule_timer(r["id"], delay, r.get("message", "Reminder!"))
                    count += 1
            except (ValueError, KeyError):
                pass
        self._save(active)
        return count
