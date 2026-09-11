pub mod audio;
pub mod logging;
pub mod platform;
pub mod ws;

use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::Manager;

/// Shared state: the WebSocket client to the Python backend.
pub struct WsState(pub Mutex<Option<ws::WsClient>>);

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn hide_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

#[tauri::command]
fn show_main_window_cmd(app: tauri::AppHandle) {
    show_main_window(&app);
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show JARVIS", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "Hide to tray", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit JARVIS", true, None::<&str>)?;
    // Note: ordering is reversed in the macOS context menu.
    let menu = Menu::with_items(app, &[&quit, &hide, &show])?;

    TrayIconBuilder::with_id("jarvis-tray")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main_window(app),
            "hide" => hide_main_window(app),
            "quit" => {
                // Hide (so the tray icon exits cleanly) then exit.
                hide_main_window(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                let visible = app
                    .get_webview_window("main")
                    .map(|w| w.is_visible().unwrap_or(false))
                    .unwrap_or(false);
                if visible {
                    hide_main_window(app);
                } else {
                    show_main_window(app);
                }
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    logging::init();
    logging::install_panic_hook();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(WsState(Mutex::new(None)))
        .manage(audio::AudioState::default())
        .setup(|app| {
            // Let the logger forward records to the backend over WS.
            logging::attach(app.handle());
            // Menu-bar tray: Show / Hide / Quit + left-click toggle.
            setup_tray(app)?;
            // Spawn the backend connection loop (with reconnect).
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let rt = tokio::runtime::Runtime::new().expect("tokio runtime");
                rt.block_on(ws::ws_loop(handle));
            });
            // Start the always-on mic capture so PTT, clap wake, and
            // conversation mode all have audio to work with.
            let _ = audio::start_listening(app.handle().clone());
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
            show_main_window_cmd,
            logging::get_logs,
            logging::clear_logs,
            platform::action_open_app,
            platform::action_open_path,
            platform::action_sleep,
            platform::action_shutdown,
            platform::action_screen_capture,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            log::info!("JARVIS app exiting cleanly");
        }
    });
}
