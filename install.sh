#!/usr/bin/env bash
#
# JARVIS installer — macOS (Intel / x86_64) only.
#
#   curl -fsSL https://raw.githubusercontent.com/Xznder1984/Jarvis/main/install.sh | sh
#
# Assumptions: macOS on Intel (x86_64). Prints a warning and exits if run on
# Apple Silicon (aarch64) since native deps may not have prebuilt wheels.

set -euo pipefail

JARVIS_REPO="${JARVIS_REPO:-https://github.com/Xznder1984/Jarvis.git}"
JARVIS_DIR="${JARVIS_DIR:-$HOME/Jarvis}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[jarvis]${NC} $*"; }
warn()  { echo -e "${YELLOW}[jarvis]${NC} $*"; }
die()   { echo -e "${RED}[jarvis]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------- platform
ARCH="$(uname -m)"
OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
  die "This installer targets macOS. Your OS is '$OS'. See installers/windows/ for Windows."
fi
if [ "$ARCH" != "x86_64" ]; then
  die "This installer targets Intel macOS (x86_64). Detected '$ARCH' (Apple Silicon). Build from source instead."
fi
info "Platform: macOS on Intel (x86_64)"

# ---------------------------------------------------------------- helpers
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    warn "Missing '$1' — installing via Homebrew (requires sudo for brew?)."
    if [ "$1" = "brew" ]; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
      brew install "$1"
    fi
  fi
}

# ---------------------------------------------------------------- prerequisites
info "Checking prerequisites..."
xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools missing. Run: xcode-select --install"
require_cmd brew
require_cmd git
require_cmd node
require_cmd npm
require_cmd ffmpeg

if ! command -v rustup >/dev/null 2>&1; then
  info "Installing Rust via rustup..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # shellcheck disable=SC1090
  . "$HOME/.cargo/env"
fi

PY="$(command -v python3.12 || command -v python3 || true)"
[ -n "$PY" ] || die "Python 3 not found."

# ---------------------------------------------------------------- repo
if [ -d "$JARVIS_DIR/.git" ]; then
  info "Updating existing repo at $JARVIS_DIR"
  git -C "$JARVIS_DIR" pull --ff-only
else
  info "Cloning repo into $JARVIS_DIR"
  git clone "$JARVIS_REPO" "$JARVIS_DIR"
fi
cd "$JARVIS_DIR"

# ---------------------------------------------------------------- env
if [ ! -f .env ]; then
  cp .env.example .env
  warn "Created .env — add at least one LLM API key (or run local Ollama)."
fi

# ---------------------------------------------------------------- backend
info "Setting up Python backend (venv)..."
"$PY" -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip >/dev/null
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/pip install pytest pillow >/dev/null

# ---------------------------------------------------------------- frontend
info "Installing frontend deps + building..."
( cd frontend && npm install && npm run build )

# ---------------------------------------------------------------- rust
info "Building Tauri app for x86_64-apple-darwin (this may take a while)..."
rustup target add x86_64-apple-darwin
( cd src-tauri && cargo tauri build --target x86_64-apple-darwin )

BUNDLE="src-tauri/target/x86_64-apple-darwin/release/bundle/macos"
if [ -d "$BUNDLE" ]; then
  info "Done! App bundle: $JARVIS_DIR/$BUNDLE"
  info "Launch it, grant Microphone (and optionally Screen Recording), then speak."
else
  warn "Build finished but no .app bundle found — check the build output above."
fi

info "Reminder: start the backend with:"
info "  cd $JARVIS_DIR/backend && .venv/bin/uvicorn jarvis.main:app --host 127.0.0.1 --port 8765"
echo
echo "Setup docs: https://github.com/Xznder1984/Jarvis/blob/main/SETUP.md"
