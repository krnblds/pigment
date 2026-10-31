//! Pigment — paint PBR textures directly onto 3D meshes.

mod app;
mod render;
#[cfg(test)]
mod shader_tests;
#[cfg(test)]
mod gpu_tests;

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
        ..Default::default()
    };
    eframe::run_native(
        "Pigment",
        options,
        Box::new(move |cc| Ok(Box::new(app::PigmentApp::new(cc, startup_mesh)?))),
    )
}
