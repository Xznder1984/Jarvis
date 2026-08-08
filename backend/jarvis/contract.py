"""Message envelope builders/parsers for the Rust <-> Python WebSocket contract.

See ARCHITECTURE.md for the full contract. Every message has the shape:

    {"type": str, "id": str, "ts": float, "payload": dict}

Unknown `type` values are tolerated (logged, not fatal) on both sides.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("jarvis.contract")

# --- Message type constants (Rust -> Python) ---
AUDIO_CHUNK = "audio_chunk"
WAKE_DETECTED = "wake_detected"
SESSION_END = "session_end"
SYSTEM_ACTION_RESULT = "system_action_result"
TERMS_ACCEPTED = "terms_accepted"

# --- Message type constants (Python -> Rust) ---
STATE_UPDATE = "state_update"
TRANSCRIPT = "transcript"
SAY = "say"
ACTIVITY = "activity"
PROVIDER_UPDATE = "provider_update"
MODE_UPDATE = "mode_update"
ACTION_REQUEST = "action_request"

# --- Payload types ---
MSG_TYPES: set[str] = {
    AUDIO_CHUNK,
    WAKE_DETECTED,
    SESSION_END,
    SYSTEM_ACTION_RESULT,
    TERMS_ACCEPTED,
    STATE_UPDATE,
    TRANSCRIPT,
    SAY,
    ACTIVITY,
    PROVIDER_UPDATE,
    MODE_UPDATE,
    ACTION_REQUEST,
}


def build(msg_type: str, payload: dict[str, Any], msg_id: str | None = None) -> dict[str, Any]:
    """Build a well-formed envelope."""
    if msg_type not in MSG_TYPES:
        logger.warning("Building envelope for unknown type '%s'", msg_type)
    return {
        "type": msg_type,
        "id": msg_id or uuid.uuid4().hex,
        "ts": time.time(),
        "payload": payload or {},
    }


def parse(raw: str) -> dict[str, Any]:
    """Parse a raw WS frame into an envelope dict; {} on failure."""
    import json

    try:
        env = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Dropping non-JSON WS frame (%d bytes)", len(raw))
        return {}
    if not isinstance(env, dict) or not env.get("type"):
        logger.warning("Dropping malformed envelope")
        return {}
    return env
