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
from jarvis.contract import AUDIO_CHUNK, SESSION_END, TERMS_ACCEPTED, WAKE_DETECTED

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis.main")


class AssistantHolder:
    """Holds the shared Assistant across WS connections."""

    def __init__(self) -> None:
        self.assistant: Assistant | None = None


holder = AssistantHolder()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config()
    holder.assistant = Assistant(config)
    activity.info("JARVIS backend ready")
    yield
    activity.info("JARVIS backend shutting down")


app = FastAPI(title="JARVIS Backend", version="0.1.0", lifespan=lifespan)
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


@app.get("/api/health", response_model=PingResponse)
async def health() -> PingResponse:
    return PingResponse(ok=True)


@app.get("/api/activity")
async def get_activity(limit: int = 100) -> dict[str, Any]:
    return {"items": activity.recent(limit)}


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

    try:
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

    except WebSocketDisconnect:
        logger.info("Shell disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS loop error: %s", exc)
    finally:
        assistant.send = lambda _: asyncio.sleep(0)


def _parse(raw: str) -> dict[str, Any]:
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return env if isinstance(env, dict) else {}
