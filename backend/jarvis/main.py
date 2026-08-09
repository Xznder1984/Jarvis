"""JARVIS backend entrypoint: FastAPI + WebSocket server.

Runs as a local service (uvicorn) that the Tauri/Rust shell connects to over
WebSocket at ws://127.0.0.1:8765. Also serves a small REST surface used by the
Settings UI and for health checks.

Run:
    uvicorn jarvis.main:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from jarvis.activity import activity
from jarvis.assistant import Assistant
from jarvis.config import Config
from jarvis.contract import (
    AUDIO_CHUNK,
    CLAP_SETTINGS,
    LOG,
    SESSION_END,
    SETTINGS,
    SETTINGS_UPDATE,
    TERMS_ACCEPTED,
    WAKE_DETECTED,
)
from jarvis.logging_setup import current_log_level, set_log_level, setup_logging
from jarvis.logs import LogBridgeHandler, broker

logger = logging.getLogger("jarvis.main")


class AssistantHolder:
    """Holds the shared Assistant across WS connections."""

    def __init__(self) -> None:
        self.assistant: Assistant | None = None


holder = AssistantHolder()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config()
    log_dir = setup_logging(config)
    logger.info("Logging enabled (dir=%s, level=%s)", log_dir, config.log_level)

    # Mirror all Python 'jarvis' log records into the WS/GUI log broker.
    root = logging.getLogger("jarvis")
    if not any(isinstance(h, LogBridgeHandler) for h in root.handlers):
        root.addHandler(LogBridgeHandler(broker))

    holder.assistant = Assistant(config)
    activity.info("JARVIS backend ready")
    logger.info("JARVIS backend ready (ws://%s:%s)", config.ws_host, config.ws_port)
    yield
    activity.info("JARVIS backend shutting down")


app = FastAPI(title="JARVIS Backend", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ REST
class PingResponse(BaseModel):
    ok: bool
    service: str = "jarvis-backend"


class LogLevelRequest(BaseModel):
    level: str


@app.get("/api/health", response_model=PingResponse)
async def health() -> PingResponse:
    return PingResponse(ok=True)


@app.get("/api/activity")
async def get_activity(limit: int = 100) -> dict[str, Any]:
    return {"items": activity.recent(limit)}


@app.get("/api/logs")
async def get_logs(limit: int = 200, source: str | None = None) -> dict[str, Any]:
    items = broker.recent(limit)
    if source:
        items = [i for i in items if i.get("source") == source]
    return {"items": items}


@app.get("/api/logs/level")
async def logs_level() -> dict[str, str]:
    return {"level": current_log_level()}


@app.post("/api/logs/level")
async def logs_level_set(req: LogLevelRequest) -> dict[str, str]:
    try:
        set_log_level(req.level)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"level": current_log_level()}


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    if holder.assistant is None:
        return {}
    return {"settings": holder.assistant.config.masked_settings()}


class ProviderStatus(BaseModel):
    provider: str
    state: str
    credit_estimate: float | None


@app.get("/api/providers")
async def providers() -> dict[str, Any]:
    if holder.assistant is None:
        return {"providers": []}
    router = holder.assistant.router
    out = []
    for name in router.provider_names():
        status = router.credit_for(name)
        state = "active"
        if status.remaining is not None and status.remaining <= router._config.credit_low_threshold:
            state = "low"
        out.append(ProviderStatus(provider=name, state=state, credit_estimate=status.remaining))
    return {"providers": out, "active": router.active_provider}


# ------------------------------------------------------------------ WebSocket
def _dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"))


async def _broadcast_log(env: dict[str, Any]) -> None:
    """Subscriber stub: real subscription is per-connection in ws_endpoint."""


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    assistant = holder.assistant
    if assistant is None:
        await ws.close(code=1011, reason="backend not initialized")
        return

    logger.info("Shell connected")

    async def send_to_shell(env: dict[str, Any]) -> None:
        await ws.send_text(_dumps(env))

    assistant.send = send_to_shell

    async def log_subscriber(entry: dict[str, Any]) -> None:
        try:
            await ws.send_text(_dumps({"type": LOG, "payload": entry}))
        except Exception:  # noqa: BLE001
            pass

    broker.subscribe(log_subscriber)

    try:
        await _send_full_state(assistant, send_to_shell)
        while True:
            raw = await ws.receive_text()
            env = _parse(raw)
            if not env:
                continue
            msg_type = env.get("type")
            payload = env.get("payload", {}) or {}

            if msg_type == WAKE_DETECTED:
                await assistant.handle_wake(payload)

            elif msg_type == AUDIO_CHUNK:
                assistant.on_audio_chunk(payload)

            elif msg_type == "utterance_end":
                from jarvis.assistant import pcm_to_wav

                pcm = bytes(assistant.buffer)
                assistant.reset_buffer()
                if pcm:
                    wav_bytes = pcm_to_wav(pcm, assistant.buffer_rate)
                    await assistant.handle_final_utterance(wav_bytes)

            elif msg_type == SESSION_END:
                await assistant.handle_session_end(payload)

            elif msg_type == TERMS_ACCEPTED:
                assistant.set_terms_accepted()
                activity.info("Terms accepted by user")

            elif msg_type == LOG:
                broker.publish(
                    str(payload.get("level", "info")),
                    str(payload.get("message", "")),
                    source=str(payload.get("source", "shell")),
                )

            elif msg_type == SETTINGS_UPDATE:
                await _apply_settings(assistant, payload, send_to_shell)

    except WebSocketDisconnect:
        logger.info("Shell disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS loop error: %s", exc)
    finally:
        broker.unsubscribe(log_subscriber)
        assistant.send = lambda _: asyncio.sleep(0)


async def _send_full_state(assistant: Assistant, send: Any) -> None:
    """Push current state to a newly connected shell so the GUI is in sync."""
    from jarvis.contract import MODE_UPDATE, PROVIDER_UPDATE, SETTINGS, build

    await send(build(SETTINGS, {"settings": assistant.config.masked_settings()}))
    await send(build(MODE_UPDATE, {"mode": assistant.modes.mode}))
    if assistant.router.active_provider:
        await send(
            build(
                PROVIDER_UPDATE,
                {"provider": assistant.router.active_provider, "state": "active", "credit_estimate": None},
            )
        )


async def _apply_settings(assistant: Assistant, payload: dict[str, Any], send: Any) -> None:
    """Persist UI settings, apply routing/mode changes, and propagate to the shell."""
    from jarvis.contract import CLAP_SETTINGS, MODE_UPDATE, SETTINGS, build

    settings = payload.get("settings", payload) if isinstance(payload, dict) else {}
    if not isinstance(settings, dict) or not settings:
        return

    assistant.config.update(settings)

    # Apply provider priority / model changes immediately.
    assistant.router.reorder(assistant.router._load_priority())

    # Propagate clap/voice settings to the Rust shell.
    await send(
        build(
            CLAP_SETTINGS,
            {
                "clap_count": int(assistant.config.get_int("CLAP_COUNT", 2)),
                "window_ms": int(assistant.config.get_int("CLAP_WINDOW_MS", 1200)),
                "sensitivity": float(assistant.config.get_float("CLAP_SENSITIVITY", 0.5)),
                "grace_ms": int(assistant.config.get_int("CLAP_GRACE_MS", 2200)),
                "silence_ms": int(assistant.config.get_int("UTTERANCE_SILENCE_MS", 900)),
                "max_utterance_ms": int(assistant.config.get_int("UTTERANCE_MAX_MS", 15000)),
                "vad_floor": float(assistant.config.get_float("VAD_FLOOR", 0.008)),
            },
        )
    )

    # Acknowledge back to the GUI with the persisted (masked) view.
    await send(build(SETTINGS, {"settings": assistant.config.masked_settings()}))
    await send(build(MODE_UPDATE, {"mode": assistant.modes.mode}))
    activity.info("Settings updated")


def _parse(raw: str) -> dict[str, Any]:
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return env if isinstance(env, dict) else {}
