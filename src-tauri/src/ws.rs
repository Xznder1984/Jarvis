//! WebSocket client connecting the Rust shell to the Python backend.
//!
//! Reconnects with exponential backoff. Outbound messages go through
//! `WsClient::send`. Inbound `action_request` messages are dispatched to the
//! platform module and their results are sent back to the backend.

use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message as WsMessage;

use crate::platform;

const WS_URL: &str = "ws://127.0.0.1:8765/ws";

/// A handle to send messages to the backend. Clonable and cheap.
#[derive(Clone)]
pub struct WsClient {
    tx: mpsc::UnboundedSender<Value>,
}

impl WsClient {
    pub fn send(&self, msg_type: &str, payload: &Value) {
        let _ = self.tx.send(serde_json::json!({
            "type": msg_type,
            "payload": payload,
        }));
    }
}

/// Runs the WS loop: connect (with backoff), forward messages, dispatch actions.
pub async fn ws_loop(app: AppHandle) {
    let mut backoff_ms = 500u64;

    loop {
        match tokio_tungstenite::connect_async(WS_URL).await {
            Ok((ws_stream, _)) => {
                backoff_ms = 500;
                log::info!("connected to backend");

                let (mut sink, read) = ws_stream.split();
                let (tx, mut rx) = mpsc::unbounded_channel::<Value>();

                {
                    let state = app.state::<crate::WsState>();
                    *state.0.lock().unwrap() = Some(WsClient { tx });
                }

                // Forward outbound queue to the socket.
                let mut reader = Box::pin(read);
                let mut outbound = Box::pin(async move {
                    while let Some(env) = rx.recv().await {
                        if sink.send(WsMessage::Text(env.to_string())).await.is_err() {
                            break;
                        }
                    }
                });

                let _ = app.emit("backend_status", true);

                // Drive both tasks; if either ends, drop the connection.
                tokio::select! {
                    _ = &mut outbound => {}
                    _ = run_inbound(&app, &mut reader) => {}
                }

                {
                    let state = app.state::<crate::WsState>();
                    *state.0.lock().unwrap() = None;
                }
                let _ = app.emit("backend_status", false);
                log::warn!("backend disconnected; retrying");
            }
            Err(e) => {
                log::warn!("backend connect failed: {e}");
            }
        }

        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
        backoff_ms = (backoff_ms * 2).min(15_000);
    }
}

async fn run_inbound(
    app: &AppHandle,
    read: &mut (impl futures_util::Stream<Item = Result<WsMessage, tokio_tungstenite::tungstenite::Error>> + Unpin),
) {
    while let Some(msg) = read.next().await {
        let Ok(msg) = msg else { break };
        if let WsMessage::Text(text) = msg {
            if let Ok(value) = serde_json::from_str::<Value>(&text) {
                handle_inbound(app, value).await;
            }
        }
    }
}

async fn handle_inbound(app: &AppHandle, env: Value) {
    let Some(msg_type) = env.get("type").and_then(|t| t.as_str()) else {
        return;
    };
    let payload = env.get("payload").cloned().unwrap_or(Value::Null);

    match msg_type {
        "action_request" => {
            let action = payload.get("action").and_then(|a| a.as_str()).unwrap_or("");
            let args = payload.get("args").cloned().unwrap_or(Value::Null);
            let result = platform::dispatch(app, action, &args).await;
            // Reply with the result so the backend logs it.
            send_to_backend(app, "system_action_result", &serde_json::json!({
                "action": action,
                "ok": result.is_ok(),
                "detail": result.unwrap_or_else(|e| e),
            }));
        }
        _ => {
            // Forward anything else to the frontend unchanged.
            let _ = app.emit(&msg_type, payload);
        }
    }
}

fn send_to_backend(app: &AppHandle, msg_type: &str, payload: &Value) {
    let state = app.state::<crate::WsState>();
    let guard = state.0.lock().unwrap();
    if let Some(client) = guard.as_ref() {
        client.send(msg_type, payload);
    }
}

/// Convenience for other modules (audio) to send WS messages.
pub fn send(app: &AppHandle, msg_type: &str, payload: &Value) {
    send_to_backend(app, msg_type, payload);
}
