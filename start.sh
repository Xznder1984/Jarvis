#!/usr/bin/env bash
#
# JARVIS launcher — starts the Python backend and the Tauri GUI.
#
#   ./start.sh                 backend (if not running) + cargo tauri dev
#   ./start.sh --binary        backend + run the existing debug binary (fast, no rebuild)
#   ./start.sh --release       backend + open the built .app bundle
#   ./start.sh --backend-only  just the backend (for running the GUI separately)
#   ./start.sh --no-backend    GUI only (assumes the backend is already running)
#   ./start.sh --remote        backend + public URL via ngrok/tunnelmole (use from anywhere)
#
# The backend it starts is shut down automatically when this script exits.

set -euo pipefail

# ---------------------------------------------------------------- setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[jarvis]${NC} $*"; }
warn() { echo -e "${YELLOW}[jarvis]${NC} $*"; }
die()  { echo -e "${RED}[jarvis]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------- args
MODE="dev"
case "${1:-dev}" in
  dev)          MODE="dev" ;;
  --binary)     MODE="binary" ;;
  --release)    MODE="release" ;;
  --backend-only) MODE="backend-only" ;;
  --no-backend) MODE="no-backend" ;;
  --remote)     MODE="remote" ;;
  --help|-h)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *) die "Unknown option: $1 (try --help)" ;;
esac

# ---------------------------------------------------------------- config
WS_HOST="$(grep -E '^JARVIS_WS_HOST=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
WS_PORT="$(grep -E '^JARVIS_WS_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
WS_HOST="${WS_HOST:-127.0.0.1}"
WS_PORT="${WS_PORT:-8765}"
HEALTH_URL="http://$WS_HOST:$WS_PORT/api/health"

[ -x backend/.venv/bin/uvicorn ] || die "Backend venv missing. Run ./install.sh first."

# ---------------------------------------------------------------- helpers
backend_running() { curl -fsS "$HEALTH_URL" >/dev/null 2>&1; }

start_vite() {
  info "Starting Vite dev server on http://localhost:1420 ..."
  nohup npm run dev --prefix frontend >/tmp/jarvis-vite.log 2>&1 &
  VITE_PID=$!
  STARTED_VITE=1
  local tries=0
  until curl -fsS -o /dev/null http://localhost:1420/ || [ "$tries" -ge 20 ]; do
    tries=$((tries + 1)); sleep 0.5
  done
  curl -fsS -o /dev/null http://localhost:1420/ || warn "Vite not answering yet — see /tmp/jarvis-vite.log"
  info "Vite is up"
}

start_backend() {
  info "Starting backend on ws://$WS_HOST:$WS_PORT ..."
  LOG_DIR="${JARVIS_LOG_DIR:-$HOME/.jarvis/logs}"
  mkdir -p "$LOG_DIR"
  nohup backend/.venv/bin/uvicorn jarvis.main:app \
    --app-dir backend \
    --host "$WS_HOST" --port "$WS_PORT" \
    >>"$LOG_DIR/start.log" 2>&1 &
  BACKEND_PID=$!
  STARTED_BACKEND=1
  local tries=0
  until backend_running || [ "$tries" -ge 15 ]; do
    tries=$((tries + 1)); sleep 0.5
  done
  backend_running || { kill "$BACKEND_PID" 2>/dev/null || true; die "Backend failed to start — see $LOG_DIR/start.log"; }
  info "Backend is up ($HEALTH_URL)"
}

STARTED_BACKEND=0; BACKEND_PID=""; STARTED_VITE=0; VITE_PID=""; STARTED_NGROK=0; NGROK_PID=""; CLEANED=0
cleanup() {
  [ "$CLEANED" = "1" ] && return
  CLEANED=1
  if [ "$STARTED_BACKEND" = "1" ] && [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    info "Stopping backend (pid $BACKEND_PID)..."
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ "$STARTED_VITE" = "1" ] && [ -n "$VITE_PID" ] && kill -0 "$VITE_PID" 2>/dev/null; then
    info "Stopping Vite (pid $VITE_PID)..."
    kill "$VITE_PID" 2>/dev/null || true
  fi
  if [ "$STARTED_NGROK" = "1" ] && [ -n "$NGROK_PID" ] && kill -0 "$NGROK_PID" 2>/dev/null; then
    info "Stopping tunnel (pid $NGROK_PID)..."
    kill "$NGROK_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [ "$MODE" != "no-backend" ]; then
  if backend_running; then
    info "Backend already running at $HEALTH_URL (leaving it alone)"
  else
    start_backend
  fi
fi

[ "$MODE" = "backend-only" ] && {
  info "Backend-only. Ctrl-C to stop."
  wait
  exit 0
}

# ---------------------------------------------------------------- GUI
case "$MODE" in
  remote)
    # Build the frontend if the backend isn't already serving a dist, so the
    # tunnel exposes both the UI and the WebSocket from one URL.
    if [ ! -f frontend/dist/index.html ]; then
      info "frontend/dist missing — building..."
      ( cd frontend && npm run build ) || die "Frontend build failed"
    fi
    info "Public URL mode — backend serves UI at http://$WS_HOST:$WS_PORT"
    if command -v cloudflared >/dev/null 2>&1; then
      info "Starting Cloudflare quick tunnel for http://$WS_HOST:$WS_PORT ..."
      nohup cloudflared tunnel --url "http://$WS_HOST:$WS_PORT" --no-autoupdate >/tmp/jarvis-cfd.log 2>&1 &
      NGROK_PID=$!
      STARTED_NGROK=1
      local_tries=0
      URL=""
      while [ -z "$URL" ] && [ "$local_tries" -lt 30 ]; do
        local_tries=$((local_tries + 1)); sleep 1
        URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/jarvis-cfd.log | head -1 || true)"
      done
      if [ -n "$URL" ]; then
        info "🌍 Jarvis is live — share this URL: $URL"
      else
        warn "cloudflared started but no URL yet — see /tmp/jarvis-cfd.log"
      fi
    elif command -v tmole >/dev/null 2>&1 || command -v tunnelmole >/dev/null 2>&1; then
      TM="${TUNNELMOLE_BIN:-$(command -v tmole || command -v tunnelmole)}"
      info "Starting tunnelmole tunnel for http://$WS_HOST:$WS_PORT ..."
      nohup "$TM" "$WS_PORT" >/tmp/jarvis-tmole.log 2>&1 &
      NGROK_PID=$!
      STARTED_NGROK=1
      sleep 8
      URL="$(grep -oE 'https://[a-z0-9-]+\.tunnelmole[a-z.-]*' /tmp/jarvis-tmole.log | head -1 || true)"
      if [ -n "$URL" ]; then
        info "🌍 Jarvis is live — share this URL: $URL"
      else
        warn "tunnelmole started but no URL detected yet — see /tmp/jarvis-tmole.log"
      fi
    elif command -v ngrok >/dev/null 2>&1; then
      info "Starting ngrok tunnel for http://$WS_HOST:$WS_PORT ..."
      nohup ngrok http "$WS_HOST:$WS_PORT" --log=stdout >/tmp/jarvis-ngrok.log 2>&1 &
      NGROK_PID=$!
      STARTED_NGROK=1
      local_tries=0
      URL=""
      while [ -z "$URL" ] && [ "$local_tries" -lt 20 ]; do
        local_tries=$((local_tries + 1)); sleep 0.75
        URL="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["tunnels"][0]["public_url"] if d["tunnels"] else "")' 2>/dev/null || true)"
      done
      if [ -n "$URL" ]; then
        info "🌍 Jarvis is live — share this URL: $URL"
      else
        warn "ngrok started but no public URL yet — see /tmp/jarvis-ngrok.log"
      fi
    elif command -v tmole >/dev/null 2>&1 || command -v tunnelmole >/dev/null 2>&1; then
      TM="${TUNNELMOLE_BIN:-$(command -v tmole || command -v tunnelmole)}"
      info "Starting tunnelmole tunnel for http://$WS_HOST:$WS_PORT ..."
      nohup "$TM" "$WS_PORT" >/tmp/jarvis-tmole.log 2>&1 &
      NGROK_PID=$!
      STARTED_NGROK=1
      sleep 8
      URL="$(grep -oE 'https://[a-z0-9.-]+\.tunnelmole[a-z.-]*' /tmp/jarvis-tmole.log | head -1 || true)"
      if [ -n "$URL" ]; then
        info "🌍 Jarvis is live — share this URL: $URL"
      else
        warn "tunnelmole started but no URL detected yet — see /tmp/jarvis-tmole.log"
      fi
    else
      warn "Neither ngrok nor tunnelmole found. Install one:"
      warn "  brew install ngrok   # or: npm i -g tunnelmole"
    fi
    info "Public URL mode is running. Press Ctrl-C to stop and exit."
    if [ -n "$BACKEND_PID" ]; then
      while kill -0 "$BACKEND_PID" 2>/dev/null; do sleep 2; done
    else
      while true; do sleep 3600; done
    fi
    ;;
  binary)
    BIN="src-tauri/target/debug/jarvis"
    [ -x "$BIN" ] || die "No debug binary ($BIN). Run: cd src-tauri && cargo build"
    start_vite
    info "Launching existing binary $BIN"
    "$BIN"
    ;;
  release)
    BUNDLE="$(ls -d src-tauri/target/*/release/bundle/macos/*.app 2>/dev/null | head -1 || true)"
    [ -n "$BUNDLE" ] || die "No .app bundle found. Run: cd src-tauri && cargo tauri build"
    info "Opening $BUNDLE"
    open "$BUNDLE"
    info "GUI launched; this script stays alive to keep the backend running."
    info "Press Ctrl-C to stop the backend and exit."
    if [ -n "$BACKEND_PID" ]; then
      while kill -0 "$BACKEND_PID" 2>/dev/null; do sleep 2; done
    else
      while true; do sleep 3600; done
    fi
    ;;
  *)
    if cargo tauri --version >/dev/null 2>&1; then
      info "Launching dev GUI (cargo tauri dev)..."
      ( cd src-tauri && cargo tauri dev )
    else
      warn "cargo tauri CLI not found; falling back to npx tauri dev from frontend/."
      info "To install the CLI: cargo install tauri-cli"
      ( cd frontend && npx --yes tauri dev )
    fi
    ;;
esac
