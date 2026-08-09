//! Shell-side logging: console + rotating file + WS forwarding + GUI ring.
//!
//! Every `log` record produced by the Rust shell is written to
//! `~/.jarvis/logs/jarvis-shell.log` (with size-based rollover), kept in an
//! in-memory ring for the GUI (`get_logs` command), and forwarded to the
//! backend over WebSocket as a `log` envelope when connected. The backend
//! aggregates shell/backend/frontend logs in one broker.

use std::collections::VecDeque;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use log::{LevelFilter, Log, Metadata, Record};
use serde::Serialize;

const MAX_FILE_BYTES: u64 = 5 * 1024 * 1024;

/// One log entry exposed to the GUI and forwarded over WS.
#[derive(Debug, Clone, Serialize)]
pub struct LogEntry {
    pub level: String,
    pub message: String,
    pub source: String,
    pub ts: f64,
}

struct JarvisLogger {
    file: Mutex<Option<File>>,
    ring: Mutex<VecDeque<LogEntry>>,
    max_ring: usize,
    app: OnceLock<tauri::AppHandle>,
}

static LOGGER: OnceLock<JarvisLogger> = OnceLock::new();

fn logger() -> &'static JarvisLogger {
    LOGGER.get_or_init(|| JarvisLogger {
        file: Mutex::new(None),
        ring: Mutex::new(VecDeque::new()),
        max_ring: 500,
        app: OnceLock::new(),
    })
}

fn log_dir() -> PathBuf {
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(std::env::temp_dir);
    home.join(".jarvis").join("logs")
}

fn open_file() -> Option<File> {
    let dir = log_dir();
    std::fs::create_dir_all(&dir).ok()?;
    let path = dir.join("jarvis-shell.log");
    // Roll over if the current file is too big.
    if std::fs::metadata(&path).map(|m| m.len() > MAX_FILE_BYTES).unwrap_or(false) {
        let _ = std::fs::rename(&path, dir.join("jarvis-shell.log.1"));
    }
    OpenOptions::new().create(true).append(true).open(path).ok()
}

fn now_epoch_ms() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// Best-effort masking of obvious key prefixes. The backend redacts again, so
/// this is purely defense in depth.
fn redact(msg: &str) -> String {
    let mut out = msg.to_string();
    for marker in ["sk-", "csk-", "ghp_"] {
        let mut start = 0;
        loop {
            let Some(rel) = out[start..].find(marker) else { break };
            let abs = start + rel;
            let rest = &out[abs + marker.len()..];
            let end = rest.find(|c: char| !c.is_ascii_alphanumeric()).unwrap_or(rest.len());
            if end >= 12 {
                out.replace_range(abs + marker.len()..abs + marker.len() + end, "***");
            }
            start = abs + marker.len();
        }
    }
    out
}

fn format_line(record: &Record) -> String {
    let level = record.level().to_string();
    let msg = redact(&record.args().to_string());
    format!("{:.3} {level:<5} {} {}", now_epoch_ms(), record.target(), msg)
}

impl Log for JarvisLogger {
    fn enabled(&self, metadata: &Metadata) -> bool {
        metadata.level() <= log::max_level()
    }

    fn log(&self, record: &Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let line = format_line(record);

        if let Ok(mut guard) = self.file.lock() {
            if guard.is_none() {
                *guard = open_file();
            }
            if let Some(file) = guard.as_mut() {
                let _ = writeln!(file, "{line}");
            }
        }

        if let Ok(mut ring) = self.ring.lock() {
            ring.push_back(LogEntry {
                level: record.level().to_string().to_lowercase(),
                message: line.clone(),
                source: "shell".into(),
                ts: now_epoch_ms() / 1000.0,
            });
            while ring.len() > self.max_ring {
                ring.pop_front();
            }
        }

        // Forward to the backend broker over WS if connected.
        if let Some(app) = self.app.get() {
            let payload = serde_json::json!({
                "level": record.level().to_string().to_lowercase(),
                "message": line,
                "source": "shell",
            });
            crate::ws::send(app, "log", &payload);
        }
    }

    fn flush(&self) {
        if let Ok(guard) = self.file.lock() {
            if let Some(file) = guard.as_ref() {
                let _ = file.sync_all();
            }
        }
    }
}

/// Initialize the global shell logger. Call once at startup.
pub fn init() {
    let filter = std::env::var("RUST_LOG")
        .ok()
        .and_then(|v| v.parse::<LevelFilter>().ok())
        .unwrap_or(LevelFilter::Info);
    log::set_logger(logger()).expect("logger already set");
    log::set_max_level(filter);

    if let Ok(mut guard) = logger().file.lock() {
        *guard = open_file();
    }
    log::info!("JARVIS shell logger initialized (level={filter})");
}

/// Give the logger a handle so records can be forwarded to the backend.
/// Called from `.setup()` once the app handle exists.
pub fn attach(app: &tauri::AppHandle) {
    let _ = logger().app.set(app.clone());
    log::debug!("shell logger attached to app handle");
}

/// Tauri command: return recent shell log entries for the GUI log panel.
#[tauri::command]
pub fn get_logs(limit: Option<usize>) -> Vec<LogEntry> {
    let n = limit.unwrap_or(200);
    logger().ring.lock().map(|r| r.iter().rev().take(n).cloned().collect()).unwrap_or_default()
}

/// Tauri command: wipe the in-memory ring.
#[tauri::command]
pub fn clear_logs() {
    if let Ok(mut ring) = logger().ring.lock() {
        ring.clear();
    }
}
