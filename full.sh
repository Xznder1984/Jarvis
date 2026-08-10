#!/usr/bin/env bash
#
# JARVIS full setup + launch — pull, install, build, and run in one command.
#
#   ./full.sh           update + install + build (if stale) + launch release .app
#   ./full.sh --force   rebuild even if the .app bundle looks up to date
#   ./full.sh --dev     launch via cargo tauri dev instead of the .app bundle
#
# Idempotent: steps that are already done (venv, node_modules, .app bundle) are
# skipped quickly. The backend it starts is shut down when you quit.

set -euo pipefail

# ---------------------------------------------------------------- setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[jarvis]${NC} $*"; }
warn() { echo -e "${YELLOW}[jarvis]${NC} $*"; }
die()  { echo -e "${RED}[jarvis]${NC} $*" >&2; exit 1; }

FORCE=0; DEV=0
case "${1:-}" in
  "")           : ;;
  --force)      FORCE=1 ;;
  --dev)        DEV=1 ;;
  --help|-h)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *) die "Unknown option: $1 (try --help)" ;;
esac

[ -d .git ] || die "Not a git repo. Clone first: git clone https://github.com/Xznder1984/Jarvis.git"

# ---------------------------------------------------------------- update
info "Updating repo..."
git pull --ff-only

if [ ! -f .env ]; then
  cp .env.example .env
  warn "Created .env — add at least one LLM API key (or run local Ollama)."
fi

# ---------------------------------------------------------------- platform
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
  TARGET=""                      # build natively
  info "Platform: macOS on Apple Silicon (native build)"
else
  TARGET="x86_64-apple-darwin"   # match install.sh's Intel target
  info "Platform: macOS on Intel (x86_64)"
fi
[ "$TARGET" = "" ] || rustup target list --installed | grep -q "$TARGET" || rustup target add "$TARGET"

# ---------------------------------------------------------------- backend venv
if [ ! -x backend/.venv/bin/uvicorn ]; then
  info "Setting up Python backend (venv)..."
  PY="$(command -v python3.12 || command -v python3 || true)"
  [ -n "$PY" ] || die "Python 3 not found."
  "$PY" -m venv backend/.venv
  backend/.venv/bin/pip install --upgrade pip >/dev/null
  backend/.venv/bin/pip install -r backend/requirements.txt
  backend/.venv/bin/pip install pytest pillow >/dev/null
else
  info "Backend venv already present — skipping"
fi

# ---------------------------------------------------------------- frontend deps
if [ ! -d frontend/node_modules ]; then
  info "Installing frontend deps..."
  ( cd frontend && npm install )
else
  info "frontend/node_modules present — skipping"
fi

# ---------------------------------------------------------------- tauri CLI
if cargo tauri --version >/dev/null 2>&1; then
  TAURI_CMD=(cargo tauri)
elif command -v npx >/dev/null 2>&1; then
  warn "cargo tauri CLI not found; using npx @tauri-apps/cli"
  TAURI_CMD=(npx --yes @tauri-apps/cli)
else
  die "No Tauri CLI. Install it: cargo install tauri-cli"
fi

# ---------------------------------------------------------------- build
BUNDLE="src-tauri/target${TARGET:+/$TARGET}/release/bundle/macos/JARVIS.app"
BUNDLE_BIN="$(ls -dt "$BUNDLE"/Contents/MacOS/* 2>/dev/null | head -1 || true)"

needs_build() {
  [ "$FORCE" = "1" ] && return 0
  [ -n "$BUNDLE_BIN" ] || return 0
  [ -n "$(find src-tauri/src src-tauri/Cargo.toml src-tauri/Cargo.lock \
               src-tauri/tauri.conf.json src-tauri/icons \
               frontend/src frontend/package.json \
               -newer "$BUNDLE_BIN" 2>/dev/null)" ]
}

if needs_build; then
  BUILD_ARGS=()
  [ -n "$TARGET" ] && BUILD_ARGS=(--target "$TARGET")
  info "Building Tauri app for ${TARGET:-host} (first build takes ~10-15 min)..."
  ( cd src-tauri && "${TAURI_CMD[@]}" build "${BUILD_ARGS[@]}" )
else
  info "Bundle is up to date — skipping rebuild ($BUNDLE)"
fi

[ -d "$BUNDLE" ] || die "Build finished but no bundle found at $BUNDLE"

# ---------------------------------------------------------------- launch
info "Launching JARVIS"
if [ "$DEV" = "1" ]; then
  exec ./start.sh
else
  exec ./start.sh --release
fi
