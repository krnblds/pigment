//! Pigment — paint PBR textures directly onto 3D meshes.
//!
//! `pigment [model or project]` opens it; `pigment --design-gallery` shows
//! every design-system component in every state.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")] // no console window for the release .exe

use pigment_engine::app;

fn main() -> eframe::Result {
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
            .with_drag_and_drop(true),
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
