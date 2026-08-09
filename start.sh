#!/usr/bin/env bash
#
# JARVIS launcher — starts the Python backend and the Tauri GUI.
#
#   ./start.sh                 backend (if not running) + cargo tauri dev
#   ./start.sh --binary        backend + run the existing debug binary (fast, no rebuild)
#   ./start.sh --release       backend + open the built .app bundle
#   ./start.sh --backend-only  just the backend (for running the GUI separately)
#   ./start.sh --no-backend    GUI only (assumes the backend is already running)
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

STARTED_BACKEND=0; BACKEND_PID=""; STARTED_VITE=0; VITE_PID=""; CLEANED=0
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
