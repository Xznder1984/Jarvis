"""JARVIS assistant core: ties STT, LLM routing, TTS, tools, and modes together.

This is backend-side orchestration. The Rust shell streams audio chunks and
sends wake/end events; the backend produces state updates, transcripts, spoken
audio, and activity entries. All outbound communication goes through an
injected `send` callable so it stays transport-agnostic (WebSocket in prod,
memory in tests).
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import wave
from typing import Any, Awaitable, Callable

from jarvis.activity import activity
from jarvis.config import Config
from jarvis.contract import (
    ACTION_REQUEST,
    ACTIVITY,
    MODE_UPDATE,
    PROVIDER_UPDATE,
    RESUME_LISTENING,
    SAY,
    SESSION_END,
    STATE_UPDATE,
    TRANSCRIPT,
    build,
)
from jarvis.conversation import Conversation
from jarvis.modes import ModeState
from jarvis.router import ProviderRouter
from jarvis.stt.whisper import WhisperSTT
from jarvis.tools.coding import CodingTool
from jarvis.tools.files import FileManager
from jarvis.tools.schedule import Scheduler
from jarvis.tools.system import SystemActions, parse_open_command
from jarvis.tools.web import WebSearch
from jarvis.tts.router import TTSRouter
from jarvis.vision.vision import Vision

logger = logging.getLogger("jarvis.assistant")

SYSTEM_PROMPT = (
    "You are JARVIS, a personal desktop assistant inspired by the fictional J.A.R.V.I.S. "
    "Keep responses concise and conversational; you are spoken aloud, so favor short, "
    "natural sentences over long lists. Address the user with the honorific '{honorific}' "
    "when natural. You can perform real actions on the user's machine. When the user asks "
    "you to do something, you may emit a JSON action block in your reply like: "
    '```json {{"action": "open_app", "args": {{"app": "Safari"}}}}``` '
    'Available actions: "open_app" (args: app), "open_path" (args: path), "sleep", '
    '"shutdown", "screen_capture", "system_info". File actions: "list_dir" (args: path), '
    '"read_file" (args: path), "write_file" (args: path, content), "delete_file" (args: path), '
    '"move_file" (args: src, dst), "search_files" (args: path, pattern), "create_dir" (args: path). '
    'Schedule actions: "set_reminder" (args: time, message), "set_timer" (args: duration, message), '
    '"list_reminders" (args: none), "cancel_reminder" (args: id). Web: "web_search" (args: query). '
    "Only use these actions when the user clearly asks for them. After completing any action, "
    "ask the user if they want you to stay in the background, such as 'Do you want me to stay "
    "in the background, {honorific}?'"
)

ACTION_JSON = "```json"
CODING_FENCE = "```shell"

# Time to wait after asking "stay in the background?" before going idle.
STAY_ASK_DELAY_S = 8.0


class Assistant:
    def __init__(
        self,
        config: Config | None = None,
        *,
        send: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config or Config()
        self.send = send or (lambda _: asyncio.sleep(0))

        # Components
        self.conversation = Conversation()
        self.router = ProviderRouter(
            self.config,
            on_notify=lambda level, msg: activity.add(level, msg),
            on_provider_update=self._on_provider_update,
        )
        self.tts = TTSRouter(self.config, on_notify=lambda level, msg: activity.add(level, msg))
        self.stt = WhisperSTT(
            model_size=self.config.get("STT_MODEL", "base"),
            device=self.config.get("STT_DEVICE", "cpu"),
        )
        self.vision = Vision()
        self.web = WebSearch()
        self.coding = CodingTool()
        self.files = FileManager()
        self.scheduler = Scheduler(on_remind=self._on_remind)
        self.actions = SystemActions(request_action=self._request_action)
        self.modes = ModeState(on_change=self._on_mode_change)

        # Wake/T&C state
        self.terms_accepted = bool(self.config.get_bool("TERMS_ACCEPTED", False))
        self.wake_phrase = str(self.config.get("WAKE_PHRASE", "jarvis"))
        self.honorific = str(self.config.get("HONORIFIC", "sir"))
        self.response_phrase = str(self.config.get("WAKE_RESPONSE", "Ready at any moment, {honorific}."))
        self._buffer = bytearray()
        self._buffer_rate = 16000
        self._listening = False
        self._idle_task: asyncio.Task | None = None
        self._idle_armed = False
        self._stay_ask_task: asyncio.Task | None = None
        self._pending_waiting = False
        self._awaiting_tts = False

    @property
    def buffer(self) -> bytearray:
        return self._buffer

    @property
    def buffer_rate(self) -> int:
        return self._buffer_rate

    # ------------------------------------------------------------- outbound
    async def _emit(self, msg_type: str, payload: dict[str, Any]) -> None:
        await self.send(build(msg_type, payload))

    async def set_state(self, state: str, **meta: Any) -> None:
        await self._emit(STATE_UPDATE, {"state": state, "meta": meta})

    async def speak(self, text: str) -> None:
        provider, audio_b64 = await asyncio.to_thread(self.tts.synthesize, text)
        await self._emit(SAY, {"text": text, "audio": audio_b64, "provider": provider})

    async def _on_remind(self, message: str) -> None:
        """Fired when a reminder/timer goes off."""
        activity.info(f"Reminder: {message}")
        await self.speak(f"Reminder, {self.honorific}: {message}")

    async def _on_provider_update(self, name: str, state: str, remaining: float | None) -> None:
        await self._emit(PROVIDER_UPDATE, {"provider": name, "state": state, "credit_estimate": remaining})

    async def _on_mode_change(self, mode: str) -> None:
        await self._emit(MODE_UPDATE, {"mode": mode})

    def _request_action(self, action: str, args: dict[str, Any]) -> Any:
        # Synchronous bridge: schedule the async emit.
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit(ACTION_REQUEST, {"action": action, "args": args}))
        except RuntimeError:
            logger.warning("No running loop; action %s dropped", action)
        return {"requested": action}

    # --------------------------------------------------------------- events
    def set_terms_accepted(self) -> None:
        self.terms_accepted = True
        self.config.update({"TERMS_ACCEPTED": True})

    def on_audio_chunk(self, payload: dict[str, Any]) -> None:
        """Buffer streaming PCM from the shell for endpoint STT."""
        try:
            data = base64.b64decode(payload.get("data", ""))
        except (ValueError, TypeError):
            return
        self._buffer.extend(data)
        if payload.get("sample_rate"):
            self._buffer_rate = int(payload["sample_rate"])

    def reset_buffer(self) -> None:
        self._buffer.clear()

    # ------------------------------------------------------ idle / power-save
    def _cancel_idle_timer(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        self._idle_armed = False

    def _cancel_stay_ask(self) -> None:
        if self._stay_ask_task is not None:
            self._stay_ask_task.cancel()
            self._stay_ask_task = None

    def _arm_idle_timer(self) -> None:
        """After a session ends, optionally sleep/shut down after the idle timeout."""
        self._cancel_idle_timer()
        timeout_ms = self.config.get_int("IDLE_TIMEOUT_MS", 0)
        action = str(self.config.get("IDLE_ACTION", "off"))
        if timeout_ms <= 0 or action not in ("sleep", "shutdown"):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._idle_armed = True
        self._idle_task = loop.create_task(self._idle_tick(timeout_ms, action))

    async def _idle_tick(self, timeout_ms: int, action: str) -> None:
        try:
            await asyncio.sleep(timeout_ms / 1000.0)
        except asyncio.CancelledError:
            return
        if not self._idle_armed or self._listening:
            return
        activity.info(f"Idle timeout reached; triggering {action}")
        logger.info("Idle timeout (%d ms) -> %s", timeout_ms, action)
        if action == "sleep":
            self.actions.sleep()
        elif action == "shutdown":
            self.actions.shutdown()

    # -------------------------------------------------------------- main turn
    async def handle_wake(self, payload: dict[str, Any]) -> None:
        method = payload.get("method", "clap")
        self._cancel_idle_timer()
        self._cancel_stay_ask()
        self._pending_waiting = False
        await self._emit(ACTIVITY, {"level": "info", "message": f"Wake detected ({method})"})
        await self.set_state("listening")
        self._listening = True
        self.reset_buffer()

        # PTT (push-to-talk) method: skip the wake phrase — user is already talking.
        if method == "ptt":
            return
        await self.speak(self.response_phrase.format(honorific=self.honorific))

    async def handle_session_end(self, payload: dict[str, Any]) -> None:
        self._cancel_stay_ask()
        self._pending_waiting = False
        self._awaiting_tts = False
        self._listening = False
        await self.set_state("idle")
        self.reset_buffer()
        self._arm_idle_timer()

    async def handle_final_utterance(self, wav_bytes: bytes) -> None:
        """Process a complete spoken turn: STT -> tools -> LLM -> TTS."""
        self._cancel_stay_ask()
        await self.set_state("thinking")
        try:
            text = await asyncio.to_thread(self.stt.transcribe_wav, wav_bytes)
        except Exception as exc:  # noqa: BLE001
            activity.error(f"STT failed: {exc}")
            await self.speak("Sorry, I could not understand that.")
            await self._go_idle()
            return

        text = text.strip()
        await self._emit(TRANSCRIPT, {"text": text, "partial": False})
        if not text:
            await self.speak("I didn't catch that. Could you repeat it?")
            await self._go_idle()
            return

        # We were waiting for an answer to "stay in the background?"
        if self._pending_waiting:
            self._pending_waiting = False
            self._cancel_stay_ask()
            if _is_stay_yes(text):
                await self.speak(f"Very good, {self.honorific}.")
                await self._converse_ready()
                return
            if _is_stay_no(text) or _is_sleep_command(text):
                await self.speak("Very well. Going idle.")
                await self._emit(SESSION_END, {"reason": "user declined"})
                return
            # Anything else: treat as a fresh command and continue processing.

        # Sleep/goodbye commands end the session.
        if _is_sleep_command(text):
            await self.speak("Goodnight.")
            await self._emit(SESSION_END, {"reason": "explicit"})
            return

        # Classify mode (coding vs normal).
        self.modes.classify(text)

        # Check for direct tool intents.
        reply_text, did_action = await self._run_tool_intent(text)
        if reply_text is None:
            reply_text, did_action = await self._llm_reply(text)

        await self.speak(reply_text)

        if did_action:
            # Completed a task — ask the user whether to stay in the background.
            self._pending_waiting = True
            self._awaiting_tts = True
            await self.set_state("listening")
        elif self.modes.mode == "coding":
            # Coding mode stays in an active loop.
            self._awaiting_tts = True
            await self.set_state("listening")
        elif self._conversation_enabled():
            # Continuous conversation: re-arm listening once TTS playback ends.
            self._awaiting_tts = True
            await self.set_state("listening")
        else:
            await self._go_idle()

    def _conversation_enabled(self) -> bool:
        return bool(self.config.get_bool("CONVERSATION_MODE", True))

    async def handle_tts_finished(self) -> None:
        """Audio playback completed — safe to re-arm voice capture (no echo)."""
        if not self._awaiting_tts:
            return
        self._awaiting_tts = False
        if self._pending_waiting:
            # Just asked "stay in the background?" — time the answer window now.
            self._arm_stay_ask_window()
        self._listening = True
        await self._emit(RESUME_LISTENING, {})
        await self.set_state("listening")

    async def _converse_ready(self) -> None:
        """Stay in the conversation loop after a chat reply."""
        self._awaiting_tts = True
        self._cancel_idle_timer()
        await self.set_state("listening")

    async def _go_idle(self) -> None:
        self._listening = False
        self._awaiting_tts = False
        await self.set_state("idle")
        self._arm_idle_timer()

    def _arm_stay_ask_window(self) -> None:
        """Start the countdown to go idle if the user doesn't answer the
        stay-in-background question."""
        self._cancel_stay_ask()

        async def _wait_and_idle():
            try:
                await asyncio.sleep(STAY_ASK_DELAY_S)
            except asyncio.CancelledError:
                return
            if self._pending_waiting:
                self._pending_waiting = False
                self._awaiting_tts = False
                await self.speak("Very well. Going idle.")
                await self._go_idle()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._stay_ask_task = loop.create_task(_wait_and_idle())

    # -------------------------------------------------------------- tools
    async def _run_tool_intent(self, text: str) -> tuple[str | None, bool]:
        """Handle explicit capabilities before calling the LLM. Returns (reply, did_action)."""
        lowered = text.lower()

        # File operations (direct phrasing)
        file_handled = await self._file_intent(text, lowered)
        if file_handled is not None:
            return file_handled, True

        # Schedule operations
        sched_handled = await self._schedule_intent(text, lowered)
        if sched_handled is not None:
            return sched_handled, True

        if "what's on my screen" in lowered or "what is on my screen" in lowered:
            self.actions.screen_capture()
            return "Let me look at your screen.", True

        if "search the web" in lowered or "look up" in lowered or "search for" in lowered:
            query = text
            for phrase in ("search the web for", "look up", "search for"):
                if phrase in lowered:
                    query = text.split(phrase, 1)[1].strip(" .?!")
            if query and query != text:
                await self._emit(ACTIVITY, {"level": "info", "message": f"Searching web: {query}"})
                await self.set_state("thinking")
                try:
                    results = await asyncio.to_thread(self.web.search, query)
                except Exception as exc:  # noqa: BLE001
                    activity.error(f"Web search failed: {exc}")
                    results = ""
                if results:
                    prompt = (
                        f"The user asked: {text}\n\nWeb search results:\n{results}\n\n"
                        f"Summarize the most relevant answer concisely, addressing the user as {self.honorific}."
                    )
                    reply, _ = self.router.chat([{"role": "user", "content": prompt}])
                    return reply, True
                return "I couldn't find anything on that.", True

        app = parse_open_command(text)
        if app:
            await self._emit(ACTIVITY, {"level": "info", "message": f"Opening app: {app}"})
            self.actions.open_app(app)
            return f"Opening {app}.", True

        return None, False

    async def _file_intent(self, text: str, lowered: str) -> str | None:
        """Handle direct file commands. Returns reply or None if not a file command."""
        # "list files in X" / "what's in X"
        m = re.match(r"(?:list|show|what'?s in|what is in)\s+(?:the\s+)?(?:files?\s+in\s+)?['\"]?([^'\"]+)", lowered)
        if m and ("file" in lowered or "folder" in lowered or "dir" in lowered or "show" in lowered or "list" in lowered):
            path = m.group(1).strip().strip(".")
            listing = self.files.list_dir(path)
            return f"Here's what's in {path}:\n{listing}" if listing and "not found" not in listing and "not a directory" not in listing \
                else f"{listing}"

        # "read file X"
        m = re.match(r"(?:read|show me|open)\s+(?:the\s+)?file\s+['\"]?([^'\"]+)", lowered)
        if m and "read" in lowered:
            path = m.group(1).strip().strip(".")
            return self.files.read_file(path)

        # "create new file X" / "write to file X"
        m = re.match(r"(?:create|make|write)\s+(?:a|the|new)?\s*file\s+['\"]?([^'\"]+)", lowered)
        if m and any(w in lowered for w in ("create", "make", "write")):
            path = m.group(1).strip().strip(".")
            return self.files.create_dir(path) if path.endswith("/") else self.files.write_file(path, "")

        return None

    async def _schedule_intent(self, text: str, lowered: str) -> str | None:
        """Handle direct schedule commands. Returns reply or None if not a schedule command."""
        # "set a reminder ..."
        m = re.match(r"(?:set|create|make)\s+(?:a|an)?\s*reminder\s+(?:for\s+)?(.+)", lowered)
        if m and "reminder" in lowered:
            spec = m.group(1).strip()
            # Try to extract time and message
            time_part, message = self._parse_reminder_spec(spec)
            return self.scheduler.set_reminder(time_part, message or "You have a reminder!")

        # "set a timer for 5 minutes"
        m = re.match(r"(?:set|start|make)\s+(?:a)?\s*timer\s+(?:for\s+)?(.+)", lowered)
        if m and "timer" in lowered:
            duration = m.group(1).strip()
            # Trim natural language ("5 minutes" -> "5m", "one hour" -> "1h")
            normalized = _normalize_duration(duration)
            return self.scheduler.set_timer(normalized, "Timer's up!")

        # "list reminders" / "show reminders"
        if "list reminder" in lowered or "show reminder" in lowered or "what reminder" in lowered:
            return self.scheduler.list_reminders()

        # "cancel reminder [id]"
        m = re.match(r"(?:cancel|delete|remove)\s+(?:the\s+)?reminder\s+([a-z0-9]+)", lowered)
        if m and "reminder" in lowered:
            return self.scheduler.cancel_reminder(m.group(1))

        return None

    @staticmethod
    def _parse_reminder_spec(spec: str) -> tuple[str, str]:
        """Split 'reminder at 3pm to call mom' into (time, message)."""
        # "at 3pm to X" / "at 3pm X"
        m = re.match(r"(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)\s*(?:to\s+)?(.*)", spec, re.IGNORECASE)
        if m:
            time_part = m.group(1).strip()
            message = m.group(2).strip() or "A scheduled event."
            return time_part, message
        # "in 30 minutes to X"
        m = re.match(r"in\s+(.+?)\s+(?:to\s+)?(.*)", spec, re.IGNORECASE)
        if m:
            return _normalize_duration(m.group(1)), m.group(2).strip() or "A scheduled event."
        # Relative time at start: "30 minutes X"
        m = re.match(r"(\d+\s*(?:minutes|minute|mins|hours|hour|hrs|seconds|secs))\s+(?:to\s+)?(.*)", spec, re.IGNORECASE)
        if m:
            return _normalize_duration(m.group(1)), m.group(2).strip() or "A scheduled event."
        return spec, "A scheduled event."

    async def _llm_reply(self, text: str) -> tuple[str, bool]:
        self.conversation.add("user", text)
        system = SYSTEM_PROMPT.format(honorific=self.honorific)
        try:
            reply, provider = self.router.chat([{"role": "system", "content": system}] + self.conversation.messages())
        except Exception as exc:  # noqa: BLE001
            activity.error(f"LLM failed: {exc}")
            return "Sorry, I hit a problem reaching the language model.", False
        self.conversation.add("assistant", reply)

        # Execute requested actions embedded as ```json blocks.
        did_action = await self._execute_embedded_actions(reply)
        # Strip fences from the spoken text.
        return _strip_fences(reply), did_action

    async def _execute_embedded_actions(self, reply: str) -> bool:
        """Extract and dispatch ```json {"action": ...} blocks from an LLM reply."""
        import json

        handled_any = False
        for block in re.findall(r"```json\s*(\{.*?\})\s*```", reply, re.DOTALL):
            try:
                action = json.loads(block)
            except json.JSONDecodeError:
                logger.warning("Dropping unparsable action block")
                continue
            name = action.get("action")
            if not name:
                continue
            args = action.get("args") or action.get("params") or {}
            handler = _ACTION_DISPATCH.get(name)
            if handler is None:
                logger.warning("LLM requested unknown action '%s'", name)
                continue
            logger.info("LLM requested action: %s", name)
            activity.info(f"Executing action: {name}")
            try:
                result = handler(self, args)
                logger.info("Action '%s' result: %s", name, result)
                handled_any = True
            except Exception as exc:  # noqa: BLE001
                activity.error(f"Action '{name}' failed: {exc}")
        return handled_any


def _action_open_app(a: Assistant, args: dict[str, Any]) -> Any:
    return a.actions.open_app(str(args.get("app", "")))


def _action_open_path(a: Assistant, args: dict[str, Any]) -> Any:
    return a.actions.open_path(str(args.get("path", "")))


def _action_sleep(a: Assistant, _args: dict[str, Any]) -> Any:
    return a.actions.sleep()


def _action_shutdown(a: Assistant, _args: dict[str, Any]) -> Any:
    return a.actions.shutdown()


def _action_screen_capture(a: Assistant, _args: dict[str, Any]) -> Any:
    return a.actions.screen_capture()


def _action_system_info(a: Assistant, _args: dict[str, Any]) -> Any:
    return a.actions.system_info()


def _action_list_dir(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.list_dir(str(args.get("path", ".")))


def _action_read_file(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.read_file(str(args.get("path", "")))


def _action_write_file(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.write_file(str(args.get("path", "")), str(args.get("content", "")))


def _action_delete_file(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.delete_file(str(args.get("path", "")))


def _action_move_file(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.move_file(str(args.get("src", "")), str(args.get("dst", "")))


def _action_search_files(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.search_files(str(args.get("path", ".")), str(args.get("pattern", "*")))


def _action_create_dir(a: Assistant, args: dict[str, Any]) -> Any:
    return a.files.create_dir(str(args.get("path", "")))


def _action_set_reminder(a: Assistant, args: dict[str, Any]) -> Any:
    return a.scheduler.set_reminder(str(args.get("time", "")), str(args.get("message", "")))


def _action_set_timer(a: Assistant, args: dict[str, Any]) -> Any:
    return a.scheduler.set_timer(str(args.get("duration", "")), str(args.get("message", "")))


def _action_list_reminders(a: Assistant, _args: dict[str, Any]) -> Any:
    return a.scheduler.list_reminders()


def _action_cancel_reminder(a: Assistant, args: dict[str, Any]) -> Any:
    return a.scheduler.cancel_reminder(str(args.get("id", "")))


def _action_web_search(a: Assistant, args: dict[str, Any]) -> Any:
    from jarvis.providers.base import ProviderError

    query = str(args.get("query", ""))
    if not query:
        return "No query provided."
    try:
        return a.web.search(query)
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"


_ACTION_DISPATCH = {
    "open_app": _action_open_app,
    "open_path": _action_open_path,
    "sleep": _action_sleep,
    "shutdown": _action_shutdown,
    "screen_capture": _action_screen_capture,
    "system_info": _action_system_info,
    "list_dir": _action_list_dir,
    "read_file": _action_read_file,
    "write_file": _action_write_file,
    "delete_file": _action_delete_file,
    "move_file": _action_move_file,
    "search_files": _action_search_files,
    "create_dir": _action_create_dir,
    "set_reminder": _action_set_reminder,
    "set_timer": _action_set_timer,
    "list_reminders": _action_list_reminders,
    "cancel_reminder": _action_cancel_reminder,
    "web_search": _action_web_search,
}


def _normalize_duration(s: str) -> str:
    """Convert natural language durations to compact form ('5 minutes' -> '5m')."""
    s = s.strip().lower()
    units = {
        "hour": "h", "hours": "h", "hrs": "h", "hr": "h", "h": "h",
        "minute": "m", "minutes": "m", "min": "m", "mins": "m", "m": "m",
        "second": "s", "seconds": "s", "sec": "s", "secs": "s", "s": "s",
    }
    # Match "5 minutes", "two hours", "1h30m"
    m = re.match(r"^(\d+)\s*(minutes?|mins?|hours?|hrs?|seconds?|secs?|h|m|s)$", s)
    if m:
        num, unit = m.group(1), m.group(2)
        return f"{num}{units[unit]}"
    # Multi-unit: "1h30m"
    if re.match(r"^\d+h\d+m$", s):
        return s
    return s


def _is_stay_yes(text: str) -> bool:
    t = text.lower().strip().rstrip(".,!?")
    return t in {
        "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "stay", "why not",
        "go ahead", "affirmative", "please do", "yes please", "y", "ya",
    } or t.startswith(("yes", "yeah", "yep", "sure ", "okay", "ok "))


def _is_stay_no(text: str) -> bool:
    t = text.lower().strip().rstrip(".,!?")
    return t in {
        "no", "nope", "no thanks", "not now", "not needed", "no need",
        "go away", "negative", "n", "nah",
    } or t.startswith("no")


def _is_sleep_command(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered in {
        "goodbye",
        "good night",
        "go to sleep",
        "sleep",
        "shut up",
        "exit",
        "quit",
        "see you later",
        "you can sleep now",
    } or lowered.startswith("goodbye")


def _strip_fences(reply: str) -> str:
    """Remove markdown code fences so only natural speech is spoken."""
    lines = []
    in_fence = False
    for line in reply.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines).strip()


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container for the STT pipeline."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()