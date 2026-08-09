//! Always-on microphone capture (cpal) with clap detection and VAD streaming.
//!
//! Two responsibilities:
//! 1. Continuously listen and detect 2+ consecutive claps within a window,
//!    using a persistent adaptive noise floor (so ambient noise doesn't wake it).
//! 2. After a wake, stream PCM to the backend for STT. Streaming is voice
//!    activity gated: audio is discarded during a grace window (so the wake
//!    response isn't transcribed back), then streamed only while the RMS is
//!    above a floor. The turn ends when silence persists for `silence_ms`, the
//!    hard cap `max_utterance_ms` is reached, or the user says goodbye.
//!
//! Chunks carry the *device* sample rate; the backend resamples to 16 kHz for
//! Whisper.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Instant;

use base64::Engine;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::WsState;

/// Settings for wake + streaming (configurable via the Settings UI / backend).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ClapSettings {
    pub clap_count: usize,
    pub window_ms: u64,
    pub sensitivity: f32,
    /// Discard mic audio for this long after a wake (wake-response echo).
    pub grace_ms: u64,
    /// Silence (ms) after which a spoken turn is considered finished.
    pub silence_ms: u64,
    /// Hard cap (ms) on a single spoken turn.
    pub max_utterance_ms: u64,
    /// Drop back to clap mode if no speech starts within this long (ms).
    pub wake_timeout_ms: u64,
    /// RMS floor (0..1) below which audio is treated as silence.
    pub vad_floor: f32,
}

impl Default for ClapSettings {
    fn default() -> Self {
        Self {
            clap_count: 2,
            window_ms: 1200,
            sensitivity: 0.35,
            grace_ms: 2200,
            silence_ms: 900,
            max_utterance_ms: 15_000,
            wake_timeout_ms: 15_000,
            vad_floor: 0.008,
        }
    }
}

static LISTENING: AtomicBool = AtomicBool::new(false);
static CAPTURE_ON: AtomicBool = AtomicBool::new(false);

/// Per-session capture state, owned by the cpal callback thread.
#[derive(Debug, Clone, Copy)]
pub struct CaptureState {
    /// Adaptive noise floor for clap detection (slow attack / decay).
    pub noise_floor: f32,
    /// Wake response grace: don't stream until this instant.
    pub grace_until: Option<Instant>,
    /// If no speech starts by this instant, drop back to clap mode.
    pub wake_deadline: Option<Instant>,
    /// True once the user has actually spoken after waking.
    pub utterance_started: bool,
    pub utterance_start: Option<Instant>,
    pub last_voice: Option<Instant>,
}

impl Default for CaptureState {
    fn default() -> Self {
        Self {
            noise_floor: 0.001,
            grace_until: None,
            wake_deadline: None,
            utterance_started: false,
            utterance_start: None,
            last_voice: None,
        }
    }
}

/// Shared state to coordinate between the capture thread and commands.
pub struct AudioState {
    pub settings: Mutex<ClapSettings>,
    pub last_clap_times: Mutex<Vec<Instant>>,
    pub capture: Mutex<CaptureState>,
}

impl Default for AudioState {
    fn default() -> Self {
        Self {
            settings: Mutex::new(ClapSettings::default()),
            last_clap_times: Mutex::new(Vec::new()),
            capture: Mutex::new(CaptureState::default()),
        }
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
pub fn stop_listening(app: AppHandle) -> Result<(), String> {
    CAPTURE_ON.store(false, Ordering::SeqCst);
    reset_capture(&app);
    Ok(())
}

/// Called when the backend ends the session (e.g. the user said goodbye).
pub fn stop_listening_soft(app: &AppHandle) {
    if LISTENING.swap(false, Ordering::SeqCst) {
        log::info!("session ended; returning to clap mode");
    }
    reset_capture(app);
}

fn reset_capture(app: &AppHandle) {
    if let Some(state) = app.try_state::<AudioState>() {
        if let Ok(mut cap) = state.capture.lock() {
            *cap = CaptureState::default();
        }
        if let Ok(mut times) = state.last_clap_times.lock() {
            times.clear();
        }
    }
    let _ = app.emit("presence", "idle");
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
    let device_config = device
        .default_input_config()
        .map_err(|e| format!("default config: {e}"))?;
    let rate = device_config.sample_rate().0;
    log::info!("microphone: {} Hz, {} ch", rate, device_config.channels());

    let stream = device
        .build_input_stream(
            &device_config.into(),
            move |data: &[f32], _| {
                if !CAPTURE_ON.load(Ordering::SeqCst) {
                    return;
                }
                if let Some(state) = app.try_state::<AudioState>() {
                    process_audio(&app, &state, data, rate);
                }
            },
            |err| log::error!("audio stream error: {err}"),
            None,
        )
        .map_err(|e| format!("build stream: {e}"))?;

    stream.play().map_err(|e| format!("play: {e}"))?;
    log::info!("audio capture started");

    // Keep the thread alive until stopped.
    while CAPTURE_ON.load(Ordering::SeqCst) {
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
    let _ = stream.pause();
    log::info!("audio capture stopped");
    Ok(())
}

fn rms(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return 0.0;
    }
    let sum = samples.iter().map(|s| s * s).sum::<f32>();
    (sum / samples.len() as f32).sqrt()
}

fn process_audio(app: &AppHandle, state: &AudioState, samples: &[f32], sample_rate: u32) {
    let level = rms(samples);
    let settings = state.settings.lock().map(|g| g.clone()).unwrap_or_default();

    if !LISTENING.load(Ordering::SeqCst) {
        detect_clap(app, state, level, &settings);
        return;
    }
    stream_utterance(app, state, level, samples, sample_rate, &settings);
}

fn detect_clap(app: &AppHandle, state: &AudioState, level: f32, settings: &ClapSettings) {
    let Ok(mut cap) = state.capture.lock() else { return };
    let floor = cap.noise_floor;

    // Adaptive floor: slow attack up, slower decay down.
    if level > floor {
        cap.noise_floor = floor + (level - floor) * 0.02;
    } else {
        cap.noise_floor = floor * 0.999;
    }

    // Relative threshold on top of the floor, plus an absolute minimum.
    let threshold = (floor * (2.0 + settings.sensitivity.clamp(0.0, 1.0) * 4.0)).max(0.02);
    if level <= threshold {
        return;
    }

    let now = Instant::now();
    if let Ok(mut times) = state.last_clap_times.lock() {
        times.push(now);
        times.retain(|t| now.duration_since(*t).as_millis() as u64 <= settings.window_ms);
        if times.len() >= settings.clap_count.max(1) {
            times.clear();
            wake(app, state, settings);
        }
    }
}

fn wake(app: &AppHandle, state: &AudioState, settings: &ClapSettings) {
    if !LISTENING.swap(true, Ordering::SeqCst) {
        log::info!("wake detected (clap x{})", settings.clap_count.max(1));
        let now = Instant::now();
        if let Ok(mut cap) = state.capture.lock() {
            cap.grace_until = Some(now + std::time::Duration::from_millis(settings.grace_ms));
            cap.wake_deadline =
                Some(now + std::time::Duration::from_millis(settings.grace_ms + settings.wake_timeout_ms));
            cap.utterance_started = false;
            cap.utterance_start = None;
            cap.last_voice = None;
        }
        let _ = app.emit("wake_detected", "clap");
        let _ = send_ws(app, "wake_detected", &serde_json::json!({"method": "clap"}));
    }
}

fn stream_utterance(
    app: &AppHandle,
    state: &AudioState,
    level: f32,
    samples: &[f32],
    sample_rate: u32,
    settings: &ClapSettings,
) {
    let now = Instant::now();
    let mut finished = false;

    {
        let Ok(mut cap) = state.capture.lock() else { return };

        if !cap.utterance_started {
            // Grace window: discard the wake-response echo.
            if let Some(grace) = cap.grace_until {
                if now < grace {
                    return;
                }
                cap.grace_until = None;
            }
            // Wake timeout: no speech by the deadline -> drop back to clap mode.
            if let Some(deadline) = cap.wake_deadline {
                if now >= deadline {
                    finished = true;
                }
            }
            if !finished && level > settings.vad_floor {
                cap.utterance_started = true;
                cap.utterance_start = Some(now);
                cap.last_voice = Some(now);
                log::debug!("voice started; streaming utterance");
            }
        } else {
            if level > settings.vad_floor {
                cap.last_voice = Some(now);
            }
            let silence_ms = cap
                .last_voice
                .map(|lv| now.duration_since(lv).as_millis() as u64)
                .unwrap_or(0);
            let dur_ms = cap
                .utterance_start
                .map(|us| now.duration_since(us).as_millis() as u64)
                .unwrap_or(0);
            if silence_ms > settings.silence_ms || dur_ms > settings.max_utterance_ms {
                finished = true;
            }
        }
    }

    // Stream the current chunk if we're actively capturing voice.
    if LISTENING.load(Ordering::SeqCst) && !finished {
        let streaming = state
            .capture
            .lock()
            .map(|c| c.utterance_started)
            .unwrap_or(false);
        if streaming {
            let _ = send_ws(
                app,
                "audio_chunk",
                &serde_json::json!({
                    "data": pcm_to_b64(samples),
                    "sample_rate": sample_rate,
                    "channels": 1
                }),
            );
        }
    }

    if finished {
        end_utterance(app);
    }
}

fn end_utterance(app: &AppHandle) {
    if !LISTENING.swap(false, Ordering::SeqCst) {
        return;
    }
    log::info!("utterance ended; sending to backend");
    let _ = send_ws(app, "utterance_end", &serde_json::json!({}));
    reset_capture(app);
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
    if let Some(state) = app.try_state::<AudioState>() {
        let settings = state.settings.lock().map(|g| g.clone()).unwrap_or_default();
        wake(app, &state, &settings);
    }
}
