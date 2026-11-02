//! Brush engine tools in the viewport: pen pressure, the straight line tool
//! (Shift-click), the path tool (click points, Enter paints), the clone
//! source (Alt-click) and the screen-space stencil (hold S: drag moves,
//! Shift+drag rotates, wheel scales), plus their overlays.

use super::design::{self as ds, space};
use super::*;

impl PigmentApp {
    /// Pen pressure from this frame's touch / pen events (egui `Touch.force`);
    /// a mouse keeps pressure 1.
    pub(super) fn read_pen(&mut self, ui: &egui::Ui) {
        let pen = ui.input(|i| {
            i.events.iter().rev().find_map(|e| match e {
                egui::Event::Touch { force: Some(f), phase, .. } => Some((*f, *phase)),
                _ => None,
            })
        });
        if let Some((f, phase)) = pen {
            self.brush.pressure = match phase {
                egui::TouchPhase::End | egui::TouchPhase::Cancel => 1.0,
                _ => f.clamp(0.0, 1.0),
            };
        }
    }

    /// Paint a polyline (viewport pixels) as one stroke with the current brush.
    pub(super) fn paint_polyline(&mut self, rs: &RenderState, pts: &[Vec2], viewport_px: Vec2) {
        if pts.is_empty() {
            return;
        }
        self.begin_stroke(rs, pts[0], viewport_px);
        for p in pigment_core::brush::polyline(pts, 2.0).into_iter().skip(1) {
            self.stroke_to(rs, p, self.brush.pressure);
        }
        self.end_stroke(rs);
    }

    /// Brush-tool input before painting. True = consumed (don't start a stroke).
    #[allow(clippy::too_many_arguments)]
    pub(super) fn brush_tool_input(&mut self, ui: &egui::Ui, rs: &RenderState, response: &egui::Response, rect: egui::Rect, viewport_px: Vec2, latest: Option<egui::Pos2>, click: bool, alt: bool) -> bool {
        let ppp = self.ppp;
        let to_px = |p: egui::Pos2| Vec2::new((p.x - rect.min.x) * ppp, (p.y - rect.min.y) * ppp);
        let (s_down, shift, enter, esc, scroll) = ui.input(|i| (i.key_down(egui::Key::S), i.modifiers.shift, i.key_pressed(egui::Key::Enter), i.key_pressed(egui::Key::Escape), i.smooth_scroll_delta.y));
        // stencil transform while S is held
        if s_down && self.brush.stencil.is_some() && response.hovered() {
            let d = response.drag_delta();
            if let Some(st) = self.brush.stencil.as_mut() {
                if response.dragged_by(egui::PointerButton::Primary) {
                    if shift {
                        st.rotation += d.x * 0.5;
                    } else {
                        st.center += Vec2::new(d.x / rect.width().max(1.0), d.y / rect.height().max(1.0));
                    }
                }
                if scroll != 0.0 {
                    st.scale = (st.scale * (scroll * 0.002).exp()).clamp(0.02, 8.0);
                }
            }
            return true;
        }
        // clone source: Alt-click
        if self.brush.tool == BrushTool::Clone && alt && response.clicked() {
            if let Some(p) = latest {
                match self.uv_at_px(to_px(p), viewport_px) {
                    Some(uv) => {
                        self.brush.clone_source = Some(uv);
                        self.brush.clone_offset = None;
                        self.set_status("Clone source set: paint to copy from it", false);
                    }
                    None => self.set_status("Alt-click on the model to set the clone source", false),
                }
            }
            return true;
        }
        // path tool: clicks add points, Enter paints, Esc clears
        if self.brush.path_mode {
            if click {
                if let Some(p) = latest {
                    self.brush.path.push(to_px(p));
                }
            }
            if enter && self.brush.path.len() >= 2 {
                let pts = std::mem::take(&mut self.brush.path);
                self.paint_polyline(rs, &pts, viewport_px);
            }
            if esc {
                self.brush.path.clear();
            }
            return true;
        }
        // straight line from the end of the last stroke: Shift-click
        if click && shift && self.stroke.is_none() {
            if let (Some(from), Some(p)) = (self.brush.last_end, latest) {
                self.paint_polyline(rs, &[from, to_px(p)], viewport_px);
                return true;
            }
        }
        false
    }

    /// Overlays: the stencil image, the path being drawn.
    pub(super) fn brush_overlay(&mut self, ui: &egui::Ui, rect: egui::Rect) {
        let p = ds::pal(ui);
        let painter = ui.painter_at(rect);
        if let Some(st) = self.brush.stencil.clone() {
            if self.brush.stencil_tex.as_ref().is_none_or(|(path, _)| *path != st.path) {
                if let Ok(img) = image::open(&st.path) {
                    let img = img.to_rgba8();
                    let ci = egui::ColorImage::from_rgba_unmultiplied([img.width() as usize, img.height() as usize], img.as_raw());
                    let tex = ui.ctx().load_texture("stencil", ci, egui::TextureOptions::LINEAR);
                    self.brush.stencil_tex = Some((st.path.clone(), tex));
                }
            }
            if let Some((_, tex)) = &self.brush.stencil_tex {
                let h = st.scale * rect.height() * 0.5;
                let w = h * st.size[0] as f32 / st.size[1].max(1) as f32;
                let c = rect.min + egui::vec2(st.center.x * rect.width(), st.center.y * rect.height());
                let (sn, cs) = st.rotation.to_radians().sin_cos();
                let corner = |x: f32, y: f32| c + egui::vec2(cs * x - sn * y, sn * x + cs * y);
                let tint = egui::Color32::WHITE.gamma_multiply(0.35 * st.opacity.max(0.2)); // lint: allow (image tint)
                let mut mesh = egui::Mesh::with_texture(tex.id());
                for (pos, uv) in [(corner(-w, -h), egui::pos2(0.0, 0.0)), (corner(w, -h), egui::pos2(1.0, 0.0)), (corner(w, h), egui::pos2(1.0, 1.0)), (corner(-w, h), egui::pos2(0.0, 1.0))] {
                    mesh.vertices.push(egui::epaint::Vertex { pos, uv, color: tint });
                }
                mesh.indices.extend_from_slice(&[0, 1, 2, 0, 2, 3]);
                painter.add(egui::Shape::mesh(mesh));
                let outline = [corner(-w, -h), corner(w, -h), corner(w, h), corner(-w, h), corner(-w, -h)];
                painter.add(egui::Shape::line(outline.to_vec(), egui::Stroke::new(1.0, p.accent.gamma_multiply(0.6))));
            }
        }
        if self.brush.path_mode && !self.brush.path.is_empty() {
            let pts: Vec<egui::Pos2> = self.brush.path.iter().map(|v| rect.min + egui::vec2(v.x, v.y) / self.ppp).collect();
            painter.add(egui::Shape::line(pts.clone(), egui::Stroke::new(1.5, p.accent)));
            for q in pts {
                painter.circle_filled(q, space::XS, p.accent);
            }
        }
    }
}
