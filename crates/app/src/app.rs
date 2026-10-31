//! Top-level application: UI layout, input handling, and wiring between the
//! core model and the renderer.

use crate::render::viewport::{ViewMode, Viewport};
use eframe::egui;
use glam::Vec2;
use pigment_core::{Mesh, OrbitCamera};
use std::path::{Path, PathBuf};
use std::time::Instant;

pub struct PigmentApp {
    viewport: Viewport,
    camera: OrbitCamera,
    mesh: Mesh,
    view_mode: ViewMode,
    status: Option<(String, bool)>, // (message, is_error)
    frame_times: Vec<f32>,
    last_frame: Instant,
}

impl PigmentApp {
    pub fn new(cc: &eframe::CreationContext<'_>, startup_mesh: Option<PathBuf>) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let rs = cc.wgpu_render_state.as_ref().ok_or("Pigment needs the wgpu renderer")?;
        let info = rs.adapter.get_info();
        log::info!("GPU: {} ({:?})", info.name, info.backend);
        cc.egui_ctx.set_visuals(egui::Visuals::dark());

        let mut app = Self {
            viewport: Viewport::new(&rs.device),
            camera: OrbitCamera::default(),
            mesh: Mesh::default(),
            view_mode: ViewMode::UvChecker,
            status: None,
            frame_times: Vec::new(),
            last_frame: Instant::now(),
        };
        app.set_mesh(rs, Mesh::torus(1.0, 0.38, 128, 48));
        if let Some(p) = startup_mesh {
            app.open_mesh(rs, &p);
        }
        Ok(app)
    }

    fn set_mesh(&mut self, rs: &eframe::egui_wgpu::RenderState, mesh: Mesh) {
        self.viewport.set_mesh(&rs.device, &mesh);
        let (c, r) = mesh.bounding_sphere();
        self.camera.frame(c, r);
        self.mesh = mesh;
    }

    fn open_mesh(&mut self, rs: &eframe::egui_wgpu::RenderState, path: &Path) {
        let t0 = Instant::now();
        match Mesh::load(path) {
            Ok(mesh) => {
                let msg = format!(
                    "Loaded {} — {} triangles in {:.0} ms{}",
                    mesh.name,
                    mesh.triangle_count(),
                    t0.elapsed().as_secs_f64() * 1000.0,
                    if mesh.has_uvs { "" } else { ". Warning: no UVs, so it can't be painted" }
                );
                log::info!("{msg}");
                self.status = Some((msg, !mesh.has_uvs));
                self.set_mesh(rs, mesh);
            }
            Err(e) => {
                log::error!("{e:#}");
                self.status = Some((format!("Couldn't open that file: {e:#}"), true));
            }
        }
    }

    fn handle_viewport_input(&mut self, ui: &egui::Ui, response: &egui::Response) {
        let (alt, delta, scroll, pinch) = ui.input(|i| (i.modifiers.alt, i.pointer.delta(), i.smooth_scroll_delta(), i.zoom_delta()));
        let d = Vec2::new(delta.x, delta.y);
        let height = response.rect.height() * ui.ctx().pixels_per_point();
        let ppp = ui.ctx().pixels_per_point();

        // Substance-style: Alt+LMB orbit, Alt+MMB pan, Alt+RMB zoom.
        // Plain LMB orbits too for now; it becomes the paint button in M3.
        if response.dragged_by(egui::PointerButton::Primary) {
            self.camera.orbit(d);
        }
        if response.dragged_by(egui::PointerButton::Middle) {
            self.camera.pan(d * ppp, height);
        }
        if response.dragged_by(egui::PointerButton::Secondary) {
            if alt {
                self.camera.zoom((d.x - d.y) * 0.02);
            } else {
                self.camera.orbit(d);
            }
        }
        if response.hovered() {
            if scroll.y != 0.0 {
                self.camera.zoom(scroll.y / 50.0);
            }
            if pinch != 1.0 {
                self.camera.zoom(pinch.ln() / 0.105);
            }
        }
        let typing = ui.ctx().egui_wants_keyboard_input();
        if response.double_clicked() || (!typing && ui.input(|i| i.key_pressed(egui::Key::F))) {
            let (c, r) = self.mesh.bounding_sphere();
            self.camera.frame(c, r);
        }
    }

    fn side_panel(&mut self, ui: &mut egui::Ui) {
        ui.heading("Mesh");
        egui::Grid::new("mesh_info").num_columns(2).show(ui, |ui| {
            ui.label("Name");
            ui.label(&self.mesh.name);
            ui.end_row();
            ui.label("Triangles");
            ui.label(format_count(self.mesh.triangle_count()));
            ui.end_row();
            ui.label("Vertices");
            ui.label(format_count(self.mesh.vertices.len()));
            ui.end_row();
            ui.label("UVs");
            if self.mesh.has_uvs {
                ui.label("yes");
            } else {
                ui.colored_label(egui::Color32::from_rgb(240, 120, 90), "missing");
            }
            ui.end_row();
        });
        ui.add_space(12.0);
        ui.heading("View");
        for m in ViewMode::ALL {
            ui.radio_value(&mut self.view_mode, m, m.label());
        }
        ui.add_space(12.0);
        ui.heading("Controls");
        ui.label("Drag: orbit\nMiddle-drag: pan\nWheel / Alt+right-drag: zoom\nF or double-click: frame mesh\nDrop an .obj / .gltf / .glb file to open it");
    }
}

impl eframe::App for PigmentApp {
    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        let Some(rs) = frame.wgpu_render_state().cloned() else { return };

        let now = Instant::now();
        self.frame_times.push((now - self.last_frame).as_secs_f32());
        self.last_frame = now;
        if self.frame_times.len() > 60 {
            self.frame_times.remove(0);
        }

        let dropped: Vec<PathBuf> = ui.input(|i| i.raw.dropped_files.iter().map(|f| f.path().to_path_buf()).filter(|p| !p.as_os_str().is_empty()).collect());
        if let Some(p) = dropped.first() {
            self.open_mesh(&rs, p);
        }

        egui::Panel::top("menu").show(ui, |ui| {
            egui::MenuBar::new().ui(ui, |ui| {
                ui.menu_button("File", |ui| {
                    if ui.button("Open mesh…").clicked() {
                        if let Some(p) = rfd::FileDialog::new()
                            .add_filter("Meshes", &["obj", "gltf", "glb"])
                            .pick_file()
                        {
                            self.open_mesh(&rs, &p);
                        }
                    }
                    if ui.button("Load test torus").clicked() {
                        self.set_mesh(&rs, Mesh::torus(1.0, 0.38, 128, 48));
                        self.status = None;
                    }
                });
                ui.menu_button("View", |ui| {
                    if ui.button("Frame mesh (F)").clicked() {
                        let (c, r) = self.mesh.bounding_sphere();
                        self.camera.frame(c, r);
                    }
                });
            });
        });

        egui::Panel::bottom("status").show(ui, |ui| {
            ui.horizontal(|ui| {
                let avg = self.frame_times.iter().sum::<f32>() / self.frame_times.len().max(1) as f32;
                ui.label(format!("{:.0} fps ({:.1} ms)", 1.0 / avg.max(1e-6), avg * 1000.0));
                if let Some((msg, err)) = &self.status {
                    ui.separator();
                    if *err {
                        ui.colored_label(egui::Color32::from_rgb(240, 160, 90), msg);
                    } else {
                        ui.label(msg);
                    }
                }
            });
        });

        egui::Panel::left("tools").resizable(true).default_size(240.0).show(ui, |ui| self.side_panel(ui));

        egui::CentralPanel::default().frame(egui::Frame::NONE).show(ui, |ui| {
            let rect = ui.available_rect_before_wrap();
            let response = ui.allocate_rect(rect, egui::Sense::click_and_drag());
            self.handle_viewport_input(ui, &response);
            let ppp = ui.ctx().pixels_per_point();
            let size = [(rect.width() * ppp).round() as u32, (rect.height() * ppp).round() as u32];
            if let Some(tex) = self.viewport.render(&rs, size, &self.camera, self.view_mode) {
                let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
                ui.painter().image(tex, rect, uv, egui::Color32::WHITE);
            }
        });

        // Keep the fps counter live; the viewport becomes continuously animated in later milestones anyway.
        ui.ctx().request_repaint();
    }
}

fn format_count(n: usize) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    out
}

#[cfg(test)]
mod tests {
    #[test]
    fn counts_are_grouped() {
        assert_eq!(super::format_count(0), "0");
        assert_eq!(super::format_count(999), "999");
        assert_eq!(super::format_count(100000), "100,000");
        assert_eq!(super::format_count(1234567), "1,234,567");
    }
}
