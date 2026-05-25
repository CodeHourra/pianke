mod backend;

use backend::{find_pianke_root, find_pianke_root_from_resource, Backend};
use std::sync::Arc;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct AppState {
    backend: Arc<Backend>,
}

fn resolve_root(app: &tauri::App) -> Result<std::path::PathBuf, String> {
    if let Some(root) = find_pianke_root_from_resource(
        app.path()
            .resolve("pianke/app.py", tauri::path::BaseDirectory::Resource),
    ) {
        return Ok(root);
    }
    find_pianke_root()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let root = resolve_root(app)?;
            let backend = Arc::new(Backend::start_at(root)?);
            let url = backend.base_url();

            app.manage(AppState {
                backend: backend.clone(),
            });

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse().unwrap()))
                .title("片刻")
                .inner_size(1280.0, 800.0)
                .min_inner_size(960.0, 640.0)
                .center()
                .build()?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::Exit) {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    state.backend.stop();
                }
            }
        });
}
