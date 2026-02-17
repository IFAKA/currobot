use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, RunEvent,
};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct BackendState(Mutex<Option<CommandChild>>);

fn spawn_backend(app: &AppHandle) -> Result<CommandChild, String> {
    let (_, child) = app
        .shell()
        .sidecar("jobbot-backend")
        .map_err(|e| e.to_string())?
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(child)
}

fn show_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn kill_backend(app: &AppHandle) {
    let child = app.state::<BackendState>().0.lock().unwrap().take();
    if let Some(c) = child {
        let _ = c.kill();
    }
}

fn toggle_autolaunch(app: &AppHandle) {
    use tauri_plugin_autostart::ManagerExt;
    let al = app.autolaunch();
    if al.is_enabled().unwrap_or(false) {
        let _ = al.disable();
    } else {
        let _ = al.enable();
    }
}

// Disables autolaunch, notifies the user, then quits cleanly.
// Called from the "Uninstall JobBot..." tray item so no dead login item remains.
fn handle_uninstall(app: &AppHandle) {
    use tauri_plugin_autostart::ManagerExt;
    use tauri_plugin_notification::NotificationExt;
    let _ = app.autolaunch().disable();
    let _ = app
        .notification()
        .builder()
        .title("JobBot")
        .body(
            "Autolaunch disabled. \
             macOS: move JobBot.app to Trash. \
             Windows: use Add/Remove Programs.",
        )
        .show();
    kill_backend(app);
    app.exit(0);
}

#[tauri::command]
fn get_autolaunch_enabled(app: AppHandle) -> bool {
    use tauri_plugin_autostart::ManagerExt;
    app.autolaunch().is_enabled().unwrap_or(false)
}

#[tauri::command]
fn set_autolaunch(app: AppHandle, enabled: bool) -> Result<(), String> {
    use tauri_plugin_autostart::ManagerExt;
    if enabled {
        app.autolaunch().enable().map_err(|e| e.to_string())
    } else {
        app.autolaunch().disable().map_err(|e| e.to_string())
    }
}

// Called from the Settings page — disables autolaunch so the user can safely
// delete the app without leaving a dead login item behind.
#[tauri::command]
fn cleanup_for_uninstall(app: AppHandle) {
    use tauri_plugin_autostart::ManagerExt;
    let _ = app.autolaunch().disable();
}

fn build_tray(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    use tauri_plugin_autostart::ManagerExt;
    let autolaunch_on = app.autolaunch().is_enabled().unwrap_or(false);

    let open = MenuItem::with_id(app, "open", "Open JobBot", true, None::<&str>)?;
    let autolaunch = MenuItem::with_id(
        app,
        "autolaunch",
        if autolaunch_on { "✓  Start on Login" } else { "Start on Login" },
        true,
        None::<&str>,
    )?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let uninstall = MenuItem::with_id(app, "uninstall", "Uninstall JobBot...", true, None::<&str>)?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &autolaunch, &sep1, &uninstall, &sep2, &quit])?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => show_window(app),
            "autolaunch" => toggle_autolaunch(app),
            "uninstall" => handle_uninstall(app),
            "quit" => {
                kill_backend(app);
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
                show_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_notification::init())
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            match spawn_backend(&handle) {
                Ok(child) => {
                    *app.state::<BackendState>().0.lock().unwrap() = Some(child);
                }
                Err(e) => {
                    eprintln!("[jobbot] backend spawn failed: {e}");
                }
            }
            build_tray(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_autolaunch_enabled,
            set_autolaunch,
            cleanup_for_uninstall,
        ])
        .on_window_event(|window, event| {
            // Closing the window hides it to tray — the app keeps running
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                window.hide().unwrap();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_backend(app);
            }
        });
}
