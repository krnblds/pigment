//! Decal objects in the viewport: on a decal layer, click a decal to select
//! it, drag to slide it over the surface (it follows the surface normal),
//! Shift+drag rotates, Ctrl+wheel scales. The selected decal's box outline
//! and the hovered spot are drawn as a live preview.

use super::design::{self as ds, space};
use super::*;
use pigment_core::decal_layer::DecalObject;

impl PigmentApp {
    /// The selected layer, if it is a decal layer.
    pub(crate) fn decal_layer_selected(&self) -> Option<usize> {
        let i = self.selected.and_then(|id| self.doc.index_of(id))?;
        self.doc.layers[i].decals.is_some().then_some(i)
    }

    /// Decal object under a world point on decal layer `i` (topmost first).
    fn decal_at(&self, i: usize, p: glam::Vec3) -> Option<u32> {
        let set = self.doc.layers[i].decals.as_ref()?;
        set.objects.iter().rev().find(|o| o.enabled && o.placement().contains(p)).map(|o| o.id)
    }

    fn decal_mut(&mut self, i: usize, id: u32) -> Option<&mut DecalObject> {
        self.doc.layers[i].decals.as_mut()?.objects.iter_mut().find(|o| o.id == id)
    }

    /// Viewport input on a decal layer. True = consumed (no painting).
    #[allow(clippy::too_many_arguments)]
    pub(super) fn decal_gizmo_input(&mut self, ui: &egui::Ui, response: &egui::Response, rect: egui::Rect, viewport_px: Vec2, latest: Option<egui::Pos2>, click: bool, alt: bool) -> bool {
        let Some(i) = self.decal_layer_selected() else { return false };
        if self.paint_mask || alt {
            return false;
        }
        let ppp = self.ppp;
        let to_px = |p: egui::Pos2| Vec2::new((p.x - rect.min.x) * ppp, (p.y - rect.min.y) * ppp);
        // egui turns Ctrl+wheel into a zoom gesture
        let (shift, ctrl, zoom) = ui.input(|inp| (inp.modifiers.shift, inp.modifiers.ctrl || inp.modifiers.command, inp.zoom_delta()));
        // a raycast only when it is needed (a click or a drag), not every frame
        let dragging = response.dragged_by(egui::PointerButton::Primary) && !shift;
        let hit = if click || dragging { latest.and_then(|p| self.surface_at(to_px(p), viewport_px)) } else { None };
        if click {
            self.decal_sel = hit.and_then(|(p, _, _)| self.decal_at(i, p));
        }
        let Some(id) = self.decal_sel else { return click };
        if response.dragged_by(egui::PointerButton::Primary) {
            if shift {
                let d = response.drag_delta().x * 0.5;
                if let Some(o) = self.decal_mut(i, id) {
                    o.rotation += d;
                }
            } else if let Some((p, n, _)) = hit {
                if let Some(o) = self.decal_mut(i, id) {
                    o.center = p.into();
                    o.normal = n.into();
                }
            }
        }
        if ctrl && zoom != 1.0 && response.hovered() {
            let k = zoom;
            if let Some(o) = self.decal_mut(i, id) {
                o.size = [o.size[0] * k, o.size[1] * k];
            }
        }
        if response.drag_stopped() {
            self.commit_doc_changes();
        }
        true
    }

    /// Outline of the selected decal (and the others, faint) on the viewport.
    pub(super) fn decal_overlay(&self, ui: &egui::Ui, rect: egui::Rect) {
        let Some(i) = self.decal_layer_selected() else { return };
        let Some(set) = self.doc.layers[i].decals.as_ref() else { return };
        let p = ds::pal(ui);
        let painter = ui.painter_at(rect);
        let vp = self.camera.view_proj(rect.width() / rect.height().max(1.0));
        let project = |w: glam::Vec3| -> Option<egui::Pos2> {
            let c = vp * w.extend(1.0);
            (c.w > 0.0).then(|| rect.min + egui::vec2((c.x / c.w * 0.5 + 0.5) * rect.width(), (0.5 - c.y / c.w * 0.5) * rect.height()))
        };
        for o in set.objects.iter().filter(|o| o.enabled) {
            let pl = o.placement();
            let (hw, hh) = (pl.right * pl.size.x * 0.5, pl.up * pl.size.y * 0.5);
            let corners = [pl.center - hw + hh, pl.center + hw + hh, pl.center + hw - hh, pl.center - hw - hh, pl.center - hw + hh];
            let pts: Vec<egui::Pos2> = corners.iter().filter_map(|c| project(*c)).collect();
            if pts.len() == 5 {
                let sel = self.decal_sel == Some(o.id);
                let stroke = egui::Stroke::new(if sel { 2.0 } else { 1.0 }, if sel { p.accent } else { p.text_muted.gamma_multiply(0.6) });
                painter.add(egui::Shape::line(pts, stroke));
                if sel {
                    if let Some(c) = project(pl.center) {
                        painter.circle_filled(c, space::XS, p.accent);
                    }
                }
            }
        }
    }
}
