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
    SAY,
    STATE_UPDATE,
    TRANSCRIPT,
    build,
)
from jarvis.conversation import Conversation
from jarvis.modes import ModeState
from jarvis.router import ProviderRouter
from jarvis.stt.whisper import WhisperSTT
from jarvis.tools.coding import CodingTool
from jarvis.tools.system import SystemActions, parse_open_command
from jarvis.tools.web import WebSearch
from jarvis.tts.router import TTSRouter
from jarvis.vision.vision import Vision

logger = logging.getLogger("jarvis.assistant")

SYSTEM_PROMPT = (
    "You are JARVIS, a personal desktop assistant inspired by the fictional J.A.R.V.I.S. "
    "Keep responses concise and conversational; you are spoken aloud, so favor short, "
    "natural sentences over long lists. Address the user with the honorific '{honorific}' "
    "when natural. Available actions you may request by emitting JSON in your reply: "
    '{{"action": "open_app", "app": "Safari"}}, {{"action": "open_path", "path": "..."}}, '
    '{{"action": "sleep"}}, {{"action": "shutdown"}}, {{"action": "screen_capture"}}. '
    "If the user asks a coding question, you may also suggest a shell command wrapped in "
    "```shell ...``` blocks."
)

ACTION_JSON = "```json"
CODING_FENCE = "```shell"


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
        self.config.save_settings({**self.config.settings, "TERMS_ACCEPTED": True})

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

    # -------------------------------------------------------------- main turn
    async def handle_wake(self, payload: dict[str, Any]) -> None:
        method = payload.get("method", "clap")
        await self._emit(ACTIVITY, {"level": "info", "message": f"Wake detected ({method})"})
        await self.set_state("listening")
        self._listening = True
        self.reset_buffer()
        await self.speak(self.response_phrase.format(honorific=self.honorific))

    async def handle_session_end(self, payload: dict[str, Any]) -> None:
        self._listening = False
        await self.set_state("idle")
        self.reset_buffer()

    async def handle_final_utterance(self, wav_bytes: bytes) -> None:
        """Process a complete spoken turn: STT -> tools -> LLM -> TTS."""
        await self.set_state("thinking")
        try:
            text = await asyncio.to_thread(self.stt.transcribe_wav, wav_bytes)
        except Exception as exc:  # noqa: BLE001
            activity.error(f"STT failed: {exc}")
            await self.speak("Sorry, I could not understand that.")
            await self.set_state("idle")
            return

        text = text.strip()
        await self._emit(TRANSCRIPT, {"text": text, "partial": False})
        if not text:
            await self.speak("I didn't catch that. Could you repeat it?")
            await self.set_state("idle")
            return

        # Sleep/goodbye commands end the session.
        if _is_sleep_command(text):
            await self.speak("Goodnight.")
            await self._emit(SESSION_END, {"reason": "explicit"})
            return

        # Classify mode (coding vs normal).
        self.modes.classify(text)

        # Check for direct tool intents.
        reply_text = await self._run_tool_intent(text)
        if not reply_text:
            reply_text = await self._llm_reply(text)

        await self.speak(reply_text)
        await self.set_state(self.modes.mode == "coding" and "listening" or "idle")

    async def _run_tool_intent(self, text: str) -> str | None:
        """Handle explicit capabilities before calling the LLM."""
        lowered = text.lower()

        if "what's on my screen" in lowered or "what is on my screen" in lowered:
            self.actions.screen_capture()
            return "Let me look at your screen."

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
                    return reply
                return "I couldn't find anything on that."

        app = parse_open_command(text)
        if app:
            await self._emit(ACTIVITY, {"level": "info", "message": f"Opening app: {app}"})
            self.actions.open_app(app)
            return f"Opening {app}."

        return None

    async def _llm_reply(self, text: str) -> str:
        self.conversation.add("user", text)
        system = SYSTEM_PROMPT.format(honorific=self.honorific)
        try:
            reply, provider = self.router.chat([{"role": "system", "content": system}] + self.conversation.messages())
        except Exception as exc:  # noqa: BLE001
            activity.error(f"LLM failed: {exc}")
            return "Sorry, I hit a problem reaching the language model."
        self.conversation.add("assistant", reply)

        # Execute requested actions embedded as ```json blocks.
        await self._execute_embedded_actions(reply)
        # Strip fences from the spoken text.
        return _strip_fences(reply)


async def _execute_embedded_actions(reply: str) -> None:
    """Extract and dispatch ```json {"action": ...} blocks from an LLM reply."""
    for block in re.findall(r"```json\s*(\{.*?\})\s*```", reply, re.DOTALL):
        try:
            import json

            action = json.loads(block)
        except json.JSONDecodeError:
            continue
        name = action.get("action")
        if name:
            logger.info("LLM requested action: %s", name)


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
