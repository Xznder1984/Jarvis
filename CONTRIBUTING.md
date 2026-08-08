# Contributing to JARVIS

Thanks for wanting to help! JARVIS is a hybrid Tauri (Rust) + FastAPI (Python)
personal assistant. This guide keeps the two halves consistent and — critically —
keeps your secrets out of git.

## Ground rules

1. **Never commit secrets.** No `.env`, no raw API keys, no recorded voice
   samples, no dev screenshots. `.gitignore` covers these; the pre-commit hook
   (below) is a second line of defense.
2. **One concern per commit.** Logical, reviewable chunks. No giant diffs.
3. **Platform abstraction.** OS-specific code (launch app, sleep, shutdown,
   capture) lives behind the platform module — don't scatter `#[cfg(target_os)]`
   through business logic.
4. **Contract first.** Any change to the Rust↔Python message envelope must be
   mirrored on both sides and updated in `ARCHITECTURE.md`.
5. **Voice-first.** The core loop is voice-in, voice-out. New features must not
   assume a text chat box exists.

## Project layout

```
backend/     Python FastAPI service (LLM routing, TTS, STT, vision, tools)
src-tauri/   Rust shell (window, tray, audio capture, platform actions)
frontend/    React + TypeScript GUI
scripts/     dev helpers + pre-commit secret check
install.sh   macOS (Intel) curl installer
```

## Getting started

1. `cp .env.example .env` and fill in at least one provider key (or run a local
   Ollama server).
2. Backend: `python3 -m venv backend/.venv && source backend/.venv/bin/activate && pip install -r backend/requirements.txt`.
3. Frontend: `cd frontend && npm install`.
4. Rust: `cd src-tauri && cargo build` (needs Xcode Command Line Tools on macOS).
5. Run: see `SETUP.md`.

## Running checks

```sh
# Python (from backend/)
ruff check jarvis/        # lint
pytest                   # tests

# Rust
cargo fmt --check && cargo clippy -- -D warnings

# Frontend
npm run lint && npm run typecheck
```

## Testing

- Backend unit tests live alongside modules (`jarvis/tests/`). Keep provider
  adapters testable with injected HTTP clients; never hit live APIs in tests.
- **No real API keys or personal data in tests.** Use fixtures only with mock
  values. Anything that needs a real key is an integration test you run locally
  with your own `.env`, never committed.

## The pre-commit hook

`scripts/pre-commit` greps staged files for likely API-key patterns and aborts
the commit if it finds any. Install it:

```sh
ln -s ../../scripts/pre-commit .git/hooks/pre-commit   # from repo root
# or run: git config core.hooksPath scripts
```

`core.hooksPath scripts` installs `scripts/pre-commit` automatically (make sure
it's executable: `chmod +x scripts/pre-commit`).

## Pull requests

- Open PRs against `main` from a feature branch (`git checkout -b feat/...`).
- Mention what changed in the message contract, if anything.
- Test on your platform; note clearly if you couldn't (e.g. Windows-specific
  changes tested only on macOS).

## License

MIT — see `LICENSE`. By contributing you agree to license your contribution
under the same terms.
