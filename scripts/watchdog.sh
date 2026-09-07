#!/bin/bash
# JARVIS app watchdog — relaunch JARVIS.app if it isn't running.
#
# The backend runs under a launchd KeepAlive agent, so it heals itself; the GUI
# app does not. This watchdog keeps the assistant always available.
#
# Pause auto-relaunch:  touch ~/.jarvis/app.paused   (remove the file to resume)
# Disable entirely:     launchctl bootout gui/$(id -u)/dev.xznder.jarvis-app-watchdog
set -u

# 1) Paused? Nothing to do.
if [[ -f "$HOME/.jarvis/app.paused" ]]; then
    exit 0
fi

# 2) Already running? Nothing to do.
if pgrep -f "JARVIS.app/Contents/MacOS/jarvis" >/dev/null 2>&1; then
    exit 0
fi

# 3) Find the newest release bundle (covers target/release and per-triple dirs).
APP=$(ls -td "$HOME/Jarvis/src-tauri"/target/release/bundle/macos/JARVIS.app \
          "$HOME/Jarvis/src-tauri"/target/*/release/bundle/macos/JARVIS.app 2>/dev/null | head -1)
if [[ -z "$APP" || ! -d "$APP" ]]; then
    exit 0
fi

# 4) Relaunch detached via LaunchServices so it outlives this script.
open "$APP"

# Log the relaunch so the health story is auditable.
printf '%s watchdog relaunched %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$APP" >> "$HOME/.jarvis/logs/watchdog.log"