//! Pigment — paint PBR textures directly onto 3D meshes.

use pigment_engine::app;

fn main() -> eframe::Result {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn,wgpu_hal=error,pigment=info")).init();
    let startup_mesh = std::env::args_os().nth(1).map(std::path::PathBuf::from);

    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_title("Pigment")
            .with_inner_size([1440.0, 900.0])
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
        Box::new(move |cc| Ok(Box::new(app::PigmentApp::new(cc, startup_mesh)?))),
    )
}
