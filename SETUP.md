# Setup

JARVIS is built and tested on **macOS on Intel (x86_64)**. This guide covers
macOS; see `installers/windows/README.md` for the Windows work-in-progress.

## Prerequisites

- macOS (Intel)
- Xcode Command Line Tools: `xcode-select --install`
- [Homebrew](https://brew.sh) (recommended)
- Rust: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- Node.js 20+ and npm
- Python 3.12 (for best wheel support with faster-whisper/ctranslate2)
- ffmpeg (for video frames + TTS conversion): `brew install ffmpeg`

Check the toolchain works before continuing:

```sh
rustc --version && cargo --version && node --version && python3.12 --version && ffmpeg -version | head -1
```

## Manual install

```sh
git clone https://github.com/Xznder1984/Jarvis.git && cd Jarvis

# 1. Environment
cp .env.example .env
#   ...edit .env and add at least one LLM API key (or run a local Ollama server)

# 2. Backend (Python)
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/pip install pytest pillow   # dev extras

# 3. Frontend
cd frontend && npm install && npm run build && cd ..

# 4. Rust shell
cd src-tauri && cargo build && cd ..
```

## macOS permissions (important)

1. **Microphone** — System Settings → Privacy & Security → Microphone.
   Needed for clap detection and voice. JARVIS should prompt on first run; if it
   silently fails to hear claps, check this permission.
2. **Screen Recording** — System Settings → Privacy & Security → Screen
   Recording. Needed for "what's on my screen" / debugging with vision. Grant to
   the JARVIS binary (`src-tauri/target/debug/jarvis` in dev, or the built app).
3. **Notifications (optional)** — for activity alerts.

After changing permissions, quit and relaunch JARVIS.

## Fish Audio TTS — step by step

Fish Audio is the primary TTS voice. Setting it up:

1. Create an account at [fish.audio](https://fish.audio) and sign in.
2. Go to your **API keys** page (Settings/Developer) and generate a key.
3. Copy the key into `FISH_AUDIO_API_KEY` in `.env` (or paste it into the
   Settings panel — it is stored masked and gitignored).
4. **Pick a voice.** Fish Audio lets you use the default voice, or clone/train
   a "JARVIS-style" voice:
   - Browse the public voice library for a suitable voice, or
   - Upload ~10–60 seconds of clean audio of the voice you want (e.g. a calm,
     British-accented assistant voice) and **clone** it from the Voices page.
   - Once you have a voice, note its **reference ID** and put it in
     `FISH_AUDIO_REFERENCE_ID`. Leave it empty to use the default voice.
5. Configure `FISH_AUDIO_MODEL` (default `fishaudio/fish-speech-1.5`).
6. Restart the backend. Verify: ask JARVIS something; the activity log should
   show the provider as `fish`. If Fish Audio errors or runs out of credits,
   JARVIS automatically falls back to the local voice (`LOCAL_TTS_VOICE`,
   default `Samantha`) so it never goes silent.

## LLM provider keys

At least one is required (or a local Ollama server). Keys go in `.env` or
Settings:

- Groq: https://console.groq.com/keys → `GROQ_API_KEY`
- Cerebras: https://cloud.cerebras.ai → `CEREBRAS_API_KEY`
- NVIDIA NIM: https://build.nvidia.com → `NVIDIA_API_KEY`
- OpenCode Zen: https://opencode.ai → `OPENCODE_ZEN_API_KEY`
- Ollama Cloud: https://ollama.com → `OLLAMA_CLOUD_API_KEY`
- Local Ollama: install from https://ollama.com and run `ollama serve`
  (optionally `ollama pull llama3.2`)

See [PROVIDERS.md](PROVIDERS.md) for credit-check details.

## Running

Quickest way — one command (starts the backend if needed, then the GUI, and
stops the backend it started when you quit):

```sh
./start.sh
```

`./start.sh` options:

```sh
./start.sh               # backend (if not running) + cargo tauri dev
./start.sh --binary      # backend + existing debug binary (fast, no rebuild)
./start.sh --release     # backend + open the built .app bundle
./start.sh --backend-only  # just the backend
./start.sh --no-backend  # GUI only (backend assumed already running)
```

Or run the pieces by hand:

Terminal 1 — backend:

```sh
cd backend && .venv/bin/uvicorn jarvis.main:app --host 127.0.0.1 --port 8765
```

Terminal 2 — app (dev):

```sh
cd frontend && npm run dev   # Vite dev server
cd src-tauri && cargo tauri dev
```

Or build a release bundle:

```sh
cd src-tauri && cargo tauri build --target x86_64-apple-darwin
```

The `.app` bundle lands in `src-tauri/target/x86_64-apple-darwin/release/bundle/macos/`.

## Using JARVIS

- **Wake:** clap twice (configurable count/window/sensitivity in Settings), or
  say the wake phrase. JARVIS replies "Ready at any moment, sir."
- **Talk:** after waking, just speak. JARVIS listens until you're silent, you
  say "goodbye"/"good night", or the session times out.
- **Ask things:** "what's on my screen", "search the web for …", "open the app
  Safari", "help me debug this code".
- **Coding mode:** say "Jarvis, switch to coding mode" (or ask a coding question
  — it auto-enters). It can run commands and tests and will ask you for feedback.
- **Power saving (off by default):** enable in Settings → Power Saving. Choose
  idle timeout and whether to sleep or shut down.

## Installer

`install.sh` automates prerequisites, repo setup, venv, frontend build, and
`cargo tauri build` for `x86_64-apple-darwin`. It assumes Intel Mac and prints a
warning if run on Apple Silicon.

## Troubleshooting

- **Can't hear claps** → check Microphone permission; raise sensitivity in
  Settings; speak up / clap louder.
- **Status bar shows NO PROVIDER** → add an API key or start local Ollama.
- **"backend offline" dot red** → backend not running or wrong port; check
  `JARVIS_WS_PORT` matches on both sides.
- **Screen capture fails** → grant Screen Recording permission.
- **Python install fails** → ensure Python 3.12 (`python3.12`), not 3.14
  (ctranslate2/faster-whisper wheels).
