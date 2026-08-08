//! Always-on microphone capture (cpal) with clap detection.
//!
//! Two responsibilities:
//! 1. Continuously listen and detect 2+ consecutive claps within a window.
//! 2. When listening (woken), stream 16 kHz mono PCM to the backend.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use base64::Engine;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::WsState;

/// Settings for clap detection (configurable via the Settings UI).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ClapSettings {
    pub clap_count: usize,
    pub window_ms: u64,
    pub sensitivity: f32,
}

impl Default for ClapSettings {
    fn default() -> Self {
        Self {
            clap_count: 2,
            window_ms: 1200,
            sensitivity: 0.35,
        }
    }
}

static LISTENING: AtomicBool = AtomicBool::new(false);
static CAPTURE_ON: AtomicBool = AtomicBool::new(false);

/// Shared state to coordinate between the capture thread and commands.
pub struct AudioState {
    pub settings: Mutex<ClapSettings>,
    pub last_clap_times: Mutex<Vec<std::time::Instant>>,
}

impl Default for AudioState {
    fn default() -> Self {
        Self {
            settings: Mutex::new(ClapSettings::default()),
            last_clap_times: Mutex::new(Vec::new()),
        }
    }
}

/// A ring of recent peak values used by the clap detector.
struct PeakRing {
    buf: Vec<f32>,
    idx: usize,
}

impl PeakRing {
    fn new(n: usize) -> Self {
        Self { buf: vec![0.0; n], idx: 0 }
    }
    fn push(&mut self, v: f32) {
        self.buf[self.idx] = v;
        self.idx = (self.idx + 1) % self.buf.len();
    }
    fn mean(&self) -> f32 {
        self.buf.iter().sum::<f32>() / self.buf.len() as f32
    }
}

/// Start the always-on capture. Call once at app startup.
#[tauri::command]
pub fn start_listening(app: AppHandle) -> Result<(), String> {
    if CAPTURE_ON.swap(true, Ordering::SeqCst) {
        return Ok(()); // already running
    }

    let handle = app.clone();
    std::thread::spawn(move || {
        let _ = run_capture(handle);
    });
    Ok(())
}

/// Stop the always-on capture (stream stops).
#[tauri::command]
pub fn stop_listening(_app: AppHandle) -> Result<(), String> {
    CAPTURE_ON.store(false, Ordering::SeqCst);
    LISTENING.store(false, Ordering::SeqCst);
    Ok(())
}

#[tauri::command]
pub fn set_clap_settings(state: State<'_, AudioState>, settings: ClapSettings) -> Result<(), String> {
    *state.settings.lock().map_err(|e| e.to_string())? = settings;
    Ok(())
}

fn run_capture(app: AppHandle) -> Result<(), String> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or("No default input device")?;
    let config = device
        .default_input_config()
        .map_err(|e| format!("default config: {e}"))?;

    let stream = device
        .build_input_stream(
            &config.into(),
            move |data: &[f32], _| {
                if !CAPTURE_ON.load(Ordering::SeqCst) {
                    return;
                }
                if let Some(state) = app.try_state::<AudioState>() {
                    process_audio(&app, &state, data);
                }
            },
            |err| log::error!("audio stream error: {err}"),
            None,
        )
        .map_err(|e| format!("build stream: {e}"))?;

    stream.play().map_err(|e| format!("play: {e}"))?;

    // Keep the thread alive until stopped.
    while CAPTURE_ON.load(Ordering::SeqCst) {
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
    let _ = stream.pause();
    Ok(())
}

fn process_audio(app: &AppHandle, state: &AudioState, samples: &[f32]) {
    // 1) Clap detection: look at short-window peak energy.
    if !LISTENING.load(Ordering::SeqCst) {
        let mut ring = PeakRing::new(160);
        for &s in samples {
            let a = s.abs();
            ring.push(a);
        }
        let mean = ring.mean();
        let settings = state.settings.lock().map(|g| g.clone()).unwrap_or_default();
        let threshold = settings.sensitivity;
        if mean > threshold {
            // Clap-like transient.
            let now = std::time::Instant::now();
            if let Ok(mut times) = state.last_clap_times.lock() {
                times.push(now);
                times.retain(|t| now.duration_since(*t).as_millis() as u64 <= settings.window_ms);
                if times.len() >= settings.clap_count {
                    times.clear();
                    // Wake!
                    if !LISTENING.swap(true, Ordering::SeqCst) {
                        let _ = app.emit("wake_detected", "clap");
                        let _ = send_ws(app, "wake_detected", &serde_json::json!({"method": "clap"}));
                    }
                }
            }
        }
    } else {
        // 2) Stream audio to backend for STT.
        let _ = send_ws(app, "audio_chunk", &serde_json::json!({
            "data": pcm_to_b64(samples),
            "sample_rate": 16000,
            "channels": 1
        }));
    }
}

fn pcm_to_b64(samples: &[f32]) -> String {
    let mut pcm: Vec<u8> = Vec::with_capacity(samples.len() * 2);
    for &s in samples {
        let v = (s.clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
        pcm.extend_from_slice(&v.to_le_bytes());
    }
    base64::engine::general_purpose::STANDARD.encode(pcm)
}

fn send_ws(app: &AppHandle, msg_type: &str, payload: &serde_json::Value) -> Result<(), String> {
    let state = app.state::<WsState>();
    let guard = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(client) = guard.as_ref() {
        client.send(msg_type, payload);
    }
    Ok(())
}

/// Emit a "wake_detected" style message (used when the wake phrase is heard —
/// placeholder for future wake-word integration).
#[allow(dead_code)]
pub fn force_wake(app: &AppHandle) {
    LISTENING.store(true, Ordering::SeqCst);
    let _ = send_ws(app, "wake_detected", &serde_json::json!({"method": "wake_word"}));
}
