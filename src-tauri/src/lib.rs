pub mod audio;
pub mod logging;
pub mod platform;
pub mod ws;

use std::sync::Mutex;

/// Shared state: the WebSocket client to the Python backend.
pub struct WsState(pub Mutex<Option<ws::WsClient>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    logging::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(WsState(Mutex::new(None)))
        .manage(audio::AudioState::default())
        .setup(|app| {
            // Let the logger forward records to the backend over WS.
            logging::attach(app.handle());
            // Spawn the backend connection loop (with reconnect).
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let rt = tokio::runtime::Runtime::new().expect("tokio runtime");
                rt.block_on(ws::ws_loop(handle));
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                // Keep running in tray on close.
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            audio::start_listening,
            audio::stop_listening,
            audio::set_clap_settings,
            audio::push_to_talk_start,
            audio::push_to_talk_end,
            logging::get_logs,
            logging::clear_logs,
            platform::action_open_app,
            platform::action_open_path,
            platform::action_sleep,
            platform::action_shutdown,
            platform::action_screen_capture,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
