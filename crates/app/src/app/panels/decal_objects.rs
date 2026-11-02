//! Decal layer properties: the decal objects (select, show / hide, order,
//! delete) and the selected one's transform, projection, look and placement
//! aids (snap to the area's centre / edge, upright, fill the largest flat
//! window-free wall, a grid of copies).

use super::super::design::{self as ds, font, size, Btn, Icon, IconBtn};
use super::*;
use pigment_core::decal_layer::{self as dl, DecalProjection, RegionQuery};

pub fn decal_objects_ui(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState, i: usize) {
    if app.doc.layers[i].decals.is_none() {
        return;
    }
    ds::section(ui, "Decals");
    let mut act: Option<(u32, &'static str)> = None;
    {
        let set = app.doc.layers[i].decals.as_mut().unwrap();
        if set.objects.is_empty() {
            ds::empty_state(ui, Icon::Image, "No decals yet", "Pick an image in the Decals panel and click the model, or use place_decal over MCP. Each decal stays editable here.", None);
        }
        let n = set.objects.len();
        for (k, o) in set.objects.iter_mut().enumerate().rev() {
            let sel = app.decal_sel == Some(o.id);
            ui.horizontal(|ui| {
                let eye = if o.enabled { Icon::Eye } else { Icon::EyeOff };
                if ui.add(IconBtn::new(eye, "Show / hide").size(size::CONTROL_H_SM)).clicked() {
                    o.enabled = !o.enabled;
                }
                if ui.add(Btn::ghost(&o.name).small().selected(sel)).clicked() {
                    act = Some((o.id, "select"));
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.add(IconBtn::new(Icon::Trash, "Delete this decal").size(size::CONTROL_H_SM)).clicked() {
                        act = Some((o.id, "delete"));
                    }
                    if k + 1 < n && ui.add(IconBtn::new(Icon::ChevronDown, "Bring forward (on top)").size(size::CONTROL_H_SM)).clicked() {
                        act = Some((o.id, "up"));
                    }
                    if k > 0 && ui.add(IconBtn::new(Icon::ChevronRight, "Send backward").size(size::CONTROL_H_SM)).clicked() {
                        act = Some((o.id, "down"));
                    }
                });
            });
        }
    }
    if let Some((id, a)) = act {
        let set = app.doc.layers[i].decals.as_mut().unwrap();
        if let Some(k) = set.objects.iter().position(|o| o.id == id) {
            match a {
                "select" => app.decal_sel = Some(id),
                "delete" => {
                    set.objects.remove(k);
                }
                "up" if k + 1 < set.objects.len() => set.objects.swap(k, k + 1),
                "down" if k > 0 => set.objects.swap(k, k - 1),
                _ => {}
            }
        }
    }
    ds::hint(ui, "In the viewport: click a decal to select it, drag to slide it over the surface, Shift+drag rotates, Ctrl+wheel scales.");
    let Some(id) = app.decal_sel else { return };
    let mesh = app.mesh.clone();
    let Some(o) = app.doc.layers[i].decals.as_mut().and_then(|s| s.objects.iter_mut().find(|o| o.id == id)) else { return };
    ds::section(ui, "Selected decal");
    let mut snap: Option<bool> = None;
    let mut fill = false;
    ds::card(ui, |ui| {
        ui.horizontal(|ui| {
            ds::prop_label(ui, "Name", None);
            ui.text_edit_singleline(&mut o.name);
        });
        ds::segmented(ui, &mut o.projection, &[(DecalProjection::Box, None, "Box"), (DecalProjection::Triplanar, None, "Triplanar"), (DecalProjection::Wrap, None, "Wrap")]);
        let mut w = o.size[0];
        if ds::slider_row_ex(ui, "Width", &mut w, 0.02..=20.0, ds::Unit::Suffix(" m", 2), true, None).changed() {
            let k = w / o.size[0].max(1e-6);
            o.size = [w, o.size[1] * k];
        }
        ds::slider_row(ui, "Rotation", &mut o.rotation, -180.0..=180.0, ds::Unit::Suffix("°", 0));
        ds::slider_row_ex(ui, "Depth", &mut o.depth, 0.005..=2.0, ds::Unit::Suffix(" m", 3), true, Some("How far the projection reaches along the normal"));
        ds::slider_row(ui, "Opacity", &mut o.wear.opacity, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Torn", &mut o.wear.tear, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Faded", &mut o.wear.fade, 0.0..=1.0, ds::Unit::Percent);
        ui.horizontal_wrapped(|ui| {
            if ui.add(Btn::ghost("Upright").small()).on_hover_text("Rotation 0: the image's up is world up").clicked() {
                o.rotation = 0.0;
            }
            if ui.add(Btn::ghost("Snap to centre").small()).on_hover_text("Centre it on the flat area it sits on").clicked() {
                snap = Some(false);
            }
            if ui.add(Btn::ghost("Snap to edge").small()).on_hover_text("Push it to the nearest edge of that area").clicked() {
                snap = Some(true);
            }
            if ui.add(Btn::secondary("Fill this wall").icon(Icon::Frame).small()).on_hover_text("Fit it into the largest flat, window-free area of the wall it is on").clicked() {
                fill = true;
            }
        });
        ui.label(ds::text(format!("{} · {}", o.image, o.projection.id()), font::SMALL).color(ds::pal(ui).text_muted));
    });
    if snap.is_some() || fill {
        let regions = dl::find_regions(&mesh, &RegionQuery { margin: 0.0, max_normal_y: 1.0, ..Default::default() });
        let at = glam::Vec3::from(o.center);
        let region = if fill {
            // the biggest area on this decal's plane
            let n = glam::Vec3::from(o.normal);
            regions.iter().find(|r| r.normal.dot(n) > 0.95 && (at - r.center).dot(r.normal).abs() < 0.05).copied()
        } else {
            dl::region_at(&regions, at).copied()
        };
        match region {
            Some(r) if fill => {
                let aspect = o.size[0] / o.size[1].max(1e-6);
                let (c, s) = dl::fit_in(&r, aspect, 0.9);
                o.center = c.into();
                o.normal = r.normal.into();
                o.size = s.into();
                o.rotation = 0.0;
            }
            Some(r) => o.center = dl::snap(o, &r, snap == Some(true), 0.05).into(),
            None => app.set_status("This decal isn't on a flat area to snap to", false),
        }
    }
    let _ = rs;
}
