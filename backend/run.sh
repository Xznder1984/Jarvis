#!/usr/bin/env bash
# Start the JARVIS backend with the venv from anywhere.
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/uvicorn jarvis.main:app --host "${JARVIS_WS_HOST:-127.0.0.1}" --port "${JARVIS_WS_PORT:-8765}"
