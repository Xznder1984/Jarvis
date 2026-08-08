//! Platform abstraction for OS-level actions.
//!
//! macOS (Intel) is the primary target. Every action lives behind a
//! platform-neutral function here so a Windows backend can be added later
//! without touching callers. On macOS we shell out to `open`, `pmset`,
//! `osascript`, and `screencapture` — no privileged APIs required.

use std::process::Command;

#[cfg(target_os = "macos")]
mod imp {
    use super::*;

    pub fn open_app(app: &str) -> Result<String, String> {
        let out = Command::new("open")
            .arg("-a")
            .arg(app)
            .output()
            .map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok(format!("Opened app '{}'", app))
        } else {
            Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
        }
    }

    pub fn open_path(path: &str) -> Result<String, String> {
        let out = Command::new("open")
            .arg(path)
            .output()
            .map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok(format!("Opened '{}'", path))
        } else {
            Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
        }
    }

    pub fn sleep_now() -> Result<String, String> {
        let out = Command::new("pmset")
            .args(["sleepnow"])
            .output()
            .map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok("Sleeping".into())
        } else {
            Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
        }
    }

    pub fn shutdown() -> Result<String, String> {
        let out = Command::new("osascript")
            .args(["-e", r#"tell app "System Events" to shut down"#])
            .output()
            .map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok("Shutting down".into())
        } else {
            Err(String::from_utf8_lossy(&out.stderr).trim().to_string())
        }
    }

    /// Capture the screen to a temp PNG and return its base64. Requires
    /// Screen Recording permission; on failure returns an error string.
    pub fn screen_capture() -> Result<String, String> {
        let path = std::env::temp_dir().join(format!("jarvis-screen-{}.png", std::process::id()));
        let out = Command::new("screencapture")
            .args(["-x", path.to_str().unwrap_or("/tmp/jarvis.png")])
            .output()
            .map_err(|e| e.to_string())?;
        if !out.status.success() {
            return Err("Screen capture failed (Screen Recording permission?)".into());
        }
        let bytes = std::fs::read(&path).map_err(|e| e.to_string())?;
        let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);
        let _ = std::fs::remove_file(&path);
        Ok(b64)
    }
}

#[cfg(not(target_os = "macos"))]
mod imp {
    use super::*;

    pub fn open_app(app: &str) -> Result<String, String> {
        let out = Command::new("cmd")
            .args(["/C", &format!("start {}", app)])
            .output()
            .map_err(|e| e.to_string())?;
        Ok(format!("Opened app '{}' (status {})", app, out.status))
    }

    pub fn open_path(path: &str) -> Result<String, String> {
        let out = Command::new("cmd")
            .args(["/C", &format!("start \"\" \"{}\"", path)])
            .output()
            .map_err(|e| e.to_string())?;
        Ok(format!("Opened '{}' (status {})", path, out.status))
    }

    pub fn sleep_now() -> Result<String, String> {
        Ok("Sleep not implemented on this platform yet".into())
    }

    pub fn shutdown() -> Result<String, String> {
        Ok("Shutdown not implemented on this platform yet".into())
    }

    pub fn screen_capture() -> Result<String, String> {
        Err("Screen capture not implemented on this platform yet".into())
    }
}

pub use imp::*;

use base64::Engine;

use tauri::{AppHandle, Emitter};

/// Request an OS action. Called from the backend via `action_request`
/// messages routed through the WebSocket client.
pub async fn dispatch(app: &AppHandle, action: &str, args: &serde_json::Value) -> Result<String, String> {
    match action {
        "open_app" => {
            let app_name = args.get("app").and_then(|v| v.as_str()).unwrap_or("");
            if app_name.is_empty() {
                return Err("open_app requires 'app'".into());
            }
            open_app(app_name)
        }
        "open_path" => {
            let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
            if path.is_empty() {
                return Err("open_path requires 'path'".into());
            }
            open_path(path)
        }
        "sleep" => sleep_now(),
        "shutdown" => shutdown(),
        "screen_capture" => {
            let b64 = screen_capture()?;
            let _ = app.emit("screen_capture", b64);
            Ok("Screen captured and sent to the frontend".into())
        }
        other => Err(format!("Unknown action '{}'", other)),
    }
}

/// Tauri commands (invoked from the frontend).
#[tauri::command]
pub fn action_open_app(app: String) -> Result<String, String> {
    open_app(&app)
}

#[tauri::command]
pub fn action_open_path(path: String) -> Result<String, String> {
    open_path(&path)
}

#[tauri::command]
pub fn action_sleep() -> Result<String, String> {
    sleep_now()
}

#[tauri::command]
pub fn action_shutdown() -> Result<String, String> {
    shutdown()
}

#[tauri::command]
pub fn action_screen_capture() -> Result<String, String> {
    screen_capture()
}
