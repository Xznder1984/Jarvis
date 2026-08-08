# Windows installer (WIP)

The Windows build is **parked** and will be completed in a follow-up session on
the Windows desktop. This directory is a clean, documented starting point.

## Context from prior Windows sessions

- The existing history was built/tested on a Windows desktop.
- MSVC was unavailable due to C:\ space constraints, so Rust builds were routed
  through **MSYS2/MinGW** at `D:\Albarr\msys64`.
- A known unresolved issue there: a **stall during the full binary link step**.
- Tauri v2 on Windows needs the WebView2 runtime and either the MSVC or GNU
  toolchain. If MSVC is unavailable, the MinGW (`x86_64-pc-windows-gnu`) target
  is the path used previously.

## Plan (for the Windows session)

1. Verify the Rust toolchain on the Windows machine (`rustup show`, `cargo build`).
2. Confirm whether the link-stage stall still reproduces; try:
   - building with `x86_64-pc-windows-msvc` if MSVC becomes available, or
   - increasing stack/heap for `ld` and using `-j1` for the link job.
3. Generate Windows icons (`icon.ico`) and adjust `tauri.conf.json` bundle icons.
4. Windows platform actions: replace `platform` module's `not(macos)` branch
   with real implementations:
   - open apps: `start "" "app"` or `explorer.exe`
   - sleep: `rundll32 powrprof.dll,SetSuspendState 0,1,0`
   - shutdown: `shutdown /s /t 0`
   - screen capture: use a crate like `xcap` or PowerShell + .NET.
5. Create `installers/windows/install.ps1` following `install.sh`'s steps
   (repo, Python 3.12 venv, npm build, `cargo tauri build --target x86_64-pc-windows-gnu`).
6. Test microphone/clap detection and TTS fallback (Windows local TTS via
   `espeak`/PowerShell System.Speech).

## Getting started when you're on the Windows box

```powershell
git clone https://github.com/Xznder1984/Jarvis.git
cd Jarvis
Copy-Item .env.example .env   # add keys
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
cd frontend; npm install; npm run build; cd ..
cd src-tauri; cargo build --target x86_64-pc-windows-gnu; cd ..
```

Refer to [SETUP.md](../../SETUP.md) for provider and permission guidance
(Windows equivalents: microphone in Settings → Privacy → Microphone).
