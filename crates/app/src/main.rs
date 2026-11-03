//! Pigment — paint PBR textures directly onto 3D meshes.
//!
//! `pigment [model or project]` opens it; `pigment --design-gallery` shows
//! every design-system component in every state. Agent commands
//! (`pigment tools`, `run`, `inspect`, ...) are handled by `cli::dispatch`.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")] // no console window for the release .exe

use pigment_engine::app;

/// The release .exe is a GUI-subsystem program, so run from a terminal it has no
/// stdout. Borrow the parent's console then, unless stdout is already a pipe or
/// file (agents capturing the JSON get it either way).
#[cfg(windows)]
fn attach_parent_console() {
    #[link(name = "kernel32")]
    extern "system" {
        fn GetStdHandle(which: u32) -> isize;
        fn AttachConsole(process: u32) -> i32;
    }
    const STD_OUTPUT_HANDLE: u32 = -11i32 as u32;
    const ATTACH_PARENT_PROCESS: u32 = u32::MAX;
    // SAFETY: plain Win32 calls with constant arguments
    unsafe {
        let out = GetStdHandle(STD_OUTPUT_HANDLE);
        if out == 0 || out == -1 {
            AttachConsole(ATTACH_PARENT_PROCESS);
        }
    }
}

fn main() -> eframe::Result {
    #[cfg(windows)]
    if std::env::args_os().len() > 1 {
        attach_parent_console();
    }
    if let Some(code) = pigment_engine::cli::dispatch(std::env::args().skip(1).collect()) {
        std::process::exit(code);
    }
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn,wgpu_hal=error,pigment=info")).init();
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();
    let gallery = args.iter().any(|a| a == "--design-gallery");
    let startup = args.iter().find(|a| !a.to_string_lossy().starts_with("--")).map(std::path::PathBuf::from);
    let prefs = app::prefs::Prefs::load();
    let size = prefs.window.map(|w| [w[0].clamp(800.0, 7680.0), w[1].clamp(500.0, 4320.0)]).unwrap_or([1440.0, 900.0]);

    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_title(if gallery { "Pigment design gallery" } else { "Pigment" })
            .with_inner_size(size)
            .with_min_inner_size([800.0, 500.0])
            .with_drag_and_drop(true)
            .with_app_id("pigment") // matches StartupWMClass in packaging/linux/pigment.desktop
            .with_icon(eframe::icon_data::from_png_bytes(app::design::WINDOW_ICON_PNG).expect("embedded app icon is a valid PNG")),
        renderer: eframe::Renderer::Wgpu,
        // the layer compositor needs more sampled textures than wgpu's default
        wgpu_options: eframe::egui_wgpu::WgpuConfiguration {
            wgpu_setup: eframe::egui_wgpu::WgpuSetup::CreateNew(eframe::egui_wgpu::WgpuSetupCreateNew {
                device_descriptor: std::sync::Arc::new(pigment_engine::render::gpu::device_descriptor),
                ..eframe::egui_wgpu::WgpuSetupCreateNew::without_display_handle()
            }),
            ..Default::default()
        },
        ..Default::default()
    };
    eframe::run_native(
        "Pigment",
        options,
        Box::new(move |cc| Ok(Box::new(app::PigmentApp::new(cc, startup, gallery)?))),
    )
}
