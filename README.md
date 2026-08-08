# JARVIS — personal desktop AI assistant

A hybrid desktop assistant inspired by the architecture of
[ethanplusai/jarvis](https://github.com/ethanplusai/jarvis) (WebSocket voice loop,
action-tag dispatch, reactive orb) — built with our own original stack:

- **Shell / GUI**: Tauri v2 (Rust) + React + TypeScript
- **Orchestration**: local Python + FastAPI service
- **Voice-first**: clap-to-wake, wake phrase, voice-in / voice-out

## Features

- **Clap or wake-word activation** — always-on mic listener (Rust/cpal) detects
  claps and wakes JARVIS; responds aloud ("Ready at any moment, sir." — both
  phrase and honorific configurable).
- **Multi-provider LLM routing** with credit monitoring and automatic failover:
  NVIDIA NIM, Groq, Cerebras, OpenCode Zen, Ollama Cloud, and local Ollama as
  the last-resort fallback. Priority order editable in Settings.
- **TTS with fallback** — Fish Audio primary, automatic local software TTS
  (macOS `say`) so JARVIS never goes silent.
- **Local STT** — faster-whisper, no paid API needed.
- **Capabilities** — web search, open apps/files, screen capture & vision,
  image/video understanding, code execution in Coding Mode.
- **Coding Mode** — auto-entered for coding tasks; runs commands/tests, asks for
  feedback, and switches back to Normal Mode automatically.
- **Power saving (opt-in, off by default)** — idle-timeout sleep/shutdown via
  `pmset` / `osascript` on macOS.
- **Polished GUI** — reactive presence orb, Settings panel (masked keys,
  priority reorder, clap sensitivity), activity log, status bar, first-run
  Terms & Conditions gate.

## Architecture

```
┌─────────────────────────── Tauri shell (Rust) ──────────────────────────┐
│  window │ tray │ always-on audio (clap/wake) │ platform actions         │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │ WebSocket (JSON, ws://127.0.0.1:8765)
┌──────────────────────────────▼─────────────────────────────────────────┐
│  FastAPI backend (Python) — LLM routing/credits, STT, TTS, vision,     │
│  web search, mode state machine, activity log                          │
└────────────────────────────────────────────────────────────────────────┘
```

The full message contract and module map live in [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start (macOS, Intel)

```sh
curl -fsSL https://raw.githubusercontent.com/Xznder1984/Jarvis/main/install.sh | sh
```

Or manually — see [SETUP.md](SETUP.md). At minimum:

1. `cp .env.example .env` and add at least one LLM key (or run local Ollama).
2. `python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt`
3. `cd frontend && npm install && npm run build`
4. `cd src-tauri && cargo build`
5. Grant **Microphone** permission (and **Screen Recording** for screen vision).
6. Run the backend (`uvicorn jarvis.main:app`) then the app.

## Providers

See [PROVIDERS.md](PROVIDERS.md) for how each LLM/TTS provider's key and credit
check works, and which use real usage endpoints vs. rolling local estimates.

## Security

- API keys live in `.env` (gitignored) or an encrypted local store written by
  Settings — never plain-text-logged.
- A pre-commit hook (`scripts/pre-commit`) blocks commits that match likely
  API-key patterns. Install with `git config core.hooksPath scripts`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Credits

Architectural inspiration: [ethanplusai/jarvis](https://github.com/ethanplusai/jarvis)
(voice loop, action-tag dispatch, WebSocket backend, reactive orb, SQLite memory).
Code is original.
