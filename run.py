#!/usr/bin/env python3
"""
JARVIS launcher — run and build the app from Python.

  python run.py                run in dev mode (backend + cargo tauri dev)
  python run.py dev            same as above
  python run.py binary         run the existing debug binary (fast, no rebuild)
  python run.py build          build a release bundle (cargo tauri build)
  python run.py run            build if needed, then open the release .app
  python run.py backend        backend only (stops when you press Ctrl-C)
  python run.py --help         show this help
"""

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
BACKEND = BASE / "backend"
SRC_TUI = BASE / "src-tauri"
VENV_UVICORN = BACKEND / ".venv" / "bin" / "uvicorn"
HEALTH_URL = "http://127.0.0.1:8765/api/health"
WS_PORT = "8765"

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
NC = "\033[0m"


def info(msg):
    print(f"{GREEN}[jarvis]{NC} {msg}", flush=True)


def warn(msg):
    print(f"{YELLOW}[jarvis]{NC} {msg}", flush=True)


def die(msg):
    print(f"{RED}[jarvis]{NC} {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kwargs):
    info(" ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kwargs)


def backend_running():
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1):
            return True
    except Exception:
        return False


def tauri_cmd():
    if shutil.which("cargo") and subprocess.run(
        ["cargo", "tauri", "--version"], capture_output=True
    ).returncode == 0:
        return ["cargo", "tauri"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@tauri-apps/cli"]
    die("No Tauri CLI. Install it: cargo install tauri-cli")


def start_backend():
    if backend_running():
        info(f"Backend already running at {HEALTH_URL} (leaving it alone)")
        return None
    if not VENV_UVICORN.is_file():
        die("Backend venv missing. Run: python3 -m venv backend/.venv && "
            "backend/.venv/bin/pip install -r backend/requirements.txt")
    info(f"Starting backend on ws://127.0.0.1:{WS_PORT} ...")
    log = Path.home() / ".jarvis" / "logs" / "start.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(VENV_UVICORN), "jarvis.main:app", "--app-dir", str(BACKEND),
         "--host", "127.0.0.1", "--port", WS_PORT],
        stdout=log.open("a"), stderr=subprocess.STDOUT,
    )
    for _ in range(15):
        if backend_running():
            info(f"Backend is up ({HEALTH_URL})")
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    proc.terminate()
    die(f"Backend failed to start — see {log}")
    return None


def bundle_path():
    target = ""
    if os.uname().machine == "x86_64":
        target = "x86_64-apple-darwin"
    return SRC_TUI / "target" / target / "release" / "bundle" / "macos" / "JARVIS.app"


def needs_build(bundle):
    bin_files = [p for p in (bundle / "Contents" / "MacOS").iterdir()] if bundle.exists() else []
    if not bin_files:
        return True
    newest = max(bin_files, key=lambda p: p.stat().st_mtime)
    roots = [SRC_TUI / "src", SRC_TUI / "Cargo.toml", SRC_TUI / "Cargo.lock",
             SRC_TUI / "tauri.conf.json", BASE / "frontend" / "src"]
    for root in roots:
        if not root.exists():
            continue
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file() and p.stat().st_mtime > newest.stat().st_mtime:
                    return True
        elif root.stat().st_mtime > newest.stat().st_mtime:
            return True
    return False


def build():
    cmd = tauri_cmd()
    target = ""
    if os.uname().machine == "x86_64":
        target = "x86_64-apple-darwin"
        info("Platform: macOS on Intel (x86_64)")
    else:
        info("Platform: macOS on Apple Silicon (native build)")
    info("Building Tauri app (first build takes ~10-15 min)...")
    args = list(cmd) + ["build"]
    if target:
        args += ["--target", target]
    rc = subprocess.run(args, cwd=SRC_TUI).returncode
    if rc != 0:
        die("Build failed")
    bundle = bundle_path()
    if not bundle.exists():
        die(f"Build finished but no bundle found at {bundle}")
    info(f"Done! App bundle: {bundle}")


def open_release(bundle):
    info(f"Opening {bundle}")
    subprocess.Popen(["open", str(bundle)])


def start_vite():
    info("Starting Vite dev server on http://localhost:1420 ...")
    log = Path("/tmp/jarvis-vite.log")
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--prefix", str(BASE / "frontend")],
        stdout=log.open("a"), stderr=subprocess.STDOUT,
    )
    for _ in range(20):
        try:
            urllib.request.urlopen("http://localhost:1420/", timeout=1)
            info("Vite is up")
            return proc
        except Exception:
            time.sleep(0.5)
    warn("Vite not answering yet — see /tmp/jarvis-vite.log")
    return proc


CHILDREN = []


def cleanup(*_):
    for p in CHILDREN:
        if p and p.poll() is None:
            p.terminate()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if mode in ("--help", "-h"):
        print(__doc__)
        return

    backend = start_backend() if mode != "binary" else start_backend()
    if backend:
        CHILDREN.append(backend)

    if mode == "backend":
        info("Backend-only. Ctrl-C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    if mode in ("build",):
        cleanup()
        build()
        return

    if mode in ("run", "release"):
        bundle = bundle_path()
        if needs_build(bundle):
            warn("Bundle is stale or missing — building...")
            build()
        open_release(bundle)
        info("GUI launched; press Ctrl-C to stop the backend and exit.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    if mode == "binary":
        bin_path = SRC_TUI / "target" / "debug" / "jarvis"
        if not bin_path.is_file():
            die(f"No debug binary ({bin_path}). Run: cd src-tauri && cargo build")
        vite = start_vite()
        CHILDREN.append(vite)
        info(f"Launching existing binary {bin_path}")
        subprocess.run([str(bin_path)])
        return

    # default: dev
    cmd = tauri_cmd()
    info("Launching dev GUI (cargo tauri dev)...")
    try:
        rc = subprocess.run(list(cmd) + ["dev"], cwd=SRC_TUI).returncode
    except KeyboardInterrupt:
        rc = 0
    sys.exit(rc)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    main()
    cleanup()
