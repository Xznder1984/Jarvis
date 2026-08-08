# JARVIS Architecture

JARVIS is a **hybrid** desktop assistant:

- **Shell / GUI**: Tauri v2 + Rust + React + TypeScript — window management, system
  tray, always-on audio capture (clap + wake-word detection), OS-level actions,
  and rendering the GUI.
- **Orchestration**: a local Python + FastAPI service (`backend/`) that owns LLM
  provider routing + credit monitoring, conversation/memory, speech-to-text,
  TTS (Fish Audio + fallback), vision, web search, and coding-mode orchestration.

The two halves talk over a local WebSocket at `ws://127.0.0.1:8765` (configurable
via `JARVIS_WS_PORT`). They are independently developed and tested against the
message contract below.

## Topology

```
┌────────────────────────────── macOS / Intel (x86_64) ─────────────────────────────┐
│                                                                                    │
│  ┌─────────────────────────── Tauri shell (Rust) ──────────────────────────────┐   │
│  │  system tray │ window mgmt │ always-on audio capture (clap/wake)           │   │
│  │  platform actions (open app, sleep, shutdown, screen capture)              │   │
│  └───────────────┬────────────────────────────────────────────┬──────────────┘   │
│                  │ WebSocket (JSON)                           │                   │
│                  ▼                                            ▼ Tauri IPC          │
│  ┌────────────────────────── FastAPI backend (Python) ──────────────┐  ┌─────────┐│
│  │  ProviderRouter → nvidia/groq/ollama/ollama_cloud/opencode_zen/  │  │ React   ││
│  │  cerebras │ TTSRouter (Fish Audio → local) │ STT (whisper)       │  │ GUI     ││
│  │  vision │ web search │ mode state machine │ activity log         │  │ (orb,   ││
│  └──────────────────────────────────────────────────────────────────┘  │  settings││
│                                                                        └─────────┘│
└────────────────────────────────────────────────────────────────────────────────────┘
```

## Message contract

All messages are JSON objects with a stable envelope. Both sides must treat
**unknown fields as ignored** and **unknown `type` values as logged, not fatal**,
so forward/backward compatibility is preserved.

```jsonc
{
  "type": "<message_type>",      // string, required
  "id": "6c8f…",                 // string, optional correlation id
  "ts": 1712345678.123,          // float, unix seconds, optional
  "payload": { }                 // object, type-specific
}
```

### Rust → Python

| `type` | `payload` | Purpose |
|---|---|---|
| `audio_chunk` | `{ data: "<base64 pcm16>", sample_rate: 16000, channels: 1 }` | Streaming mic audio while in conversation mode. |
| `wake_detected` | `{ method: "clap" \| "wake_word", meta: {} }` | Tells backend to enter listening mode. |
| `session_end` | `{ reason: "timeout" \| "explicit" \| "idle" }` | Ends the current conversation turn. |
| `system_action_result` | `{ action: "open_app", ok: bool, detail: "..." }` | Result of an OS action the backend requested. |
| `terms_accepted` | `{ accepted: true, ts: 1712345678 }` | First-run T&C gate result (Rust persists acceptance). |

### Python → Rust

| `type` | `payload` | Purpose |
|---|---|---|
| `state_update` | `{ state: "idle" \| "listening" \| "thinking" \| "speaking", meta: {} }` | Drives the GUI presence indicator. |
| `transcript` | `{ text: "…", partial: bool }` | Live STT text for the activity log/debug console. |
| `say` | `{ text: "…", audio: "<base64 wav>", provider: "fish" \| "local" }` | Speak aloud; Rust plays the audio. |
| `activity` | `{ level: "info" \| "warn" \| "error", message: "…" }` | Append to the in-app activity/log panel. |
| `provider_update` | `{ provider: "groq", state: "active" \| "low" \| "exhausted", credit_estimate: 0.42 }` | Status-bar provider/credit indicator. |
| `mode_update` | `{ mode: "normal" \| "coding" }` | Mode state machine change. |
| `action_request` | `{ action: "open_app" \| "sleep" \| "shutdown" \| "screen_capture", args: {} }` | Asks Rust to perform an OS action. |

## Module map

```
backend/
  jarvis/main.py            FastAPI app + /ws WebSocket endpoint + lifespan
  jarvis/config.py          Load .env + settings store
  jarvis/contract.py        Message envelope builders/parsers, type constants
  jarvis/router.py          ProviderRouter (credit monitoring + failover)
  jarvis/modes.py           Mode state machine (normal / coding)
  jarvis/activity.py        In-memory ring buffer activity log
  jarvis/conversation.py    Simple conversation/memory context window
  jarvis/providers/base.py  LLMProvider abstract interface
  jarvis/providers/nvidia.py, groq.py, ollama.py, ollama_cloud.py,
        opencode_zen.py, cerebras.py
  jarvis/stt/whisper.py     faster-whisper wrapper (local, free)
  jarvis/tts/router.py      TTSRouter (credit monitor + failover)
  jarvis/tts/fish_audio.py  Fish Audio adapter
  jarvis/tts/local.py       macOS `say` fallback + wav generation
  jarvis/vision/            image/video frame understanding via vision-capable LLM
  jarvis/tools/web.py       Web search + summarization
  jarvis/tools/coding.py    Coding-mode orchestration helpers

src-tauri/
  src/main.rs               Tauri entrypoint, tray, setup
  src/audio/mod.rs          Always-on capture via cpal
  src/audio/clap.rs         Clap detection DSP
  src/audio/wake.rs         Wake word handling + conversation loop
  src/ws.rs                 WebSocket client to backend, reconnection
  src/platform/mod.rs       Platform abstraction
  src/platform/macos.rs     macOS: open -a, pmset sleepnow, osascript, screencapture
  src/platform/windows.rs   Placeholder for future Windows backend
  src/commands.rs           Tauri commands bridging GUI ↔ backend

frontend/
  src/main.tsx, App.tsx     React bootstrap
  src/components/Orb.tsx    Presence indicator (canvas, reactive)
  src/components/Settings.tsx, TermsGate.tsx, ActivityLog.tsx, StatusBar.tsx
```

## Provider credit-check strategy

Per provider (details in `PROVIDERS.md`):

- Providers with a **programmatic usage endpoint** query it directly.
- Providers **without one** use a rolling local estimate: track prompt/completion
  token counts against the known free-tier monthly budget, persisted in a
  gitignored local store. Estimates are marked as such in the GUI.
- Local **Ollama** is treated as infinite (no credits).

## Threading / lifecycle

- Rust owns the mic. On clap/wake it starts streaming `audio_chunk` frames to
  Python; Python runs STT → LLM → TTS and replies with `say` frames.
- Rust reconnects the WebSocket with exponential backoff if the backend drops.
- Backend is launched by Rust on startup (if not already running) via
  `src-tauri/src/commands.rs` spawn of the venv `uvicorn` process; see `SETUP.md`.

## Conventions

- JSON only, UTF-8, no binary frames on the WS (audio is base64 in JSON).
- Message size: audio chunks are small (≈ 3200 bytes PCM per 100 ms) — fine.
- Both sides log unknown message types at debug level and continue.
