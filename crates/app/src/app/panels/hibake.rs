//! High-to-low bake (Texture set & bake panel) and the ID-colour mask (Mask panel).

use super::super::design::{self as ds, font, size, Btn, Icon};
use super::*;
use pigment_core::hibake::{BakeMap, HighBake};
use std::collections::HashMap;
use std::sync::Mutex;

/// The most common colours of an ID map (by path), cached.
pub(crate) fn id_palette(path: &Path) -> Vec<[u8; 3]> {
    static CACHE: Mutex<Option<HashMap<PathBuf, (std::time::SystemTime, Vec<[u8; 3]>)>>> = Mutex::new(None);
    let stamp = std::fs::metadata(path).and_then(|m| m.modified()).unwrap_or(std::time::UNIX_EPOCH);
    let mut c = CACHE.lock().unwrap_or_else(|e| e.into_inner());
    let map = c.get_or_insert_with(HashMap::new);
    if let Some((t, v)) = map.get(path) {
        if *t == stamp {
            return v.clone();
        }
    }
    let mut counts: HashMap<[u8; 3], u32> = HashMap::new();
    if let Ok(img) = image::open(path) {
        for p in img.to_rgb8().pixels().step_by(7) {
            *counts.entry(p.0).or_default() += 1;
        }
    }
    let mut v: Vec<([u8; 3], u32)> = counts.into_iter().filter(|(c, n)| *n > 20 && *c != [0, 0, 0]).collect();
    v.sort_by(|a, b| b.1.cmp(&a.1));
    let out: Vec<[u8; 3]> = v.into_iter().take(24).map(|x| x.0).collect();
    map.insert(path.to_path_buf(), (stamp, out.clone()));
    out
}

pub fn high_bake_ui(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    ds::section(ui, "High-poly bake");
    ds::card(ui, |ui| {
        let mut choose = false;
        match &app.doc.bake.high {
            None => {
                ds::hint(ui, "Bake detail from a high-poly mesh onto this model's UVs: normals, AO, curvature, height, thickness, position and a colour ID map.");
            }
            Some(hb) => {
                ui.label(ds::mono(Path::new(&hb.mesh).file_name().map(|f| f.to_string_lossy().into_owned()).unwrap_or_default()));
            }
        }
        if ui.add(Btn::secondary(if app.doc.bake.high.is_some() { "Change high mesh…" } else { "Choose high-poly mesh…" }).icon(Icon::Cube).small()).clicked() {
            choose = true;
        }
        if choose {
            if let Some(p) = rfd::FileDialog::new().set_title("High-poly mesh").add_filter("Mesh", &["obj", "gltf", "glb"]).pick_file() {
                let maps = app.doc.bake.high.as_ref().map(|h| h.maps.clone()).unwrap_or_else(|| vec![BakeMap::Normal, BakeMap::Ao, BakeMap::Curvature, BakeMap::Height, BakeMap::ColorId]);
                let mut hb = HighBake::new(&p.to_string_lossy(), maps);
                if let Some(old) = &app.doc.bake.high {
                    hb.cage = old.cage;
                }
                app.doc.bake.high = Some(hb);
            }
        }
        let Some(hb) = app.doc.bake.high.as_mut() else { return };
        let mut auto = hb.cage.is_none();
        if ds::toggle(ui, &mut auto, "Automatic cage").changed() {
            hb.cage = if auto { None } else { Some(0.02) };
        }
        if let Some(c) = hb.cage.as_mut() {
            ds::slider_row_ex(ui, "Cage", c, 0.0005..=0.5, ds::Unit::Suffix(" m", 4), true, Some("How far the high surface may be from the low one, both ways"));
        }
        ui.horizontal_wrapped(|ui| {
            for m in BakeMap::ALL {
                let mut on = hb.maps.contains(&m);
                if ui.add(Btn::ghost(m.id()).small().selected(on)).clicked() {
                    on = !on;
                    if on {
                        hb.maps.push(m);
                    } else {
                        hb.maps.retain(|x| *x != m);
                    }
                }
            }
        });
        ds::toggle(ui, &mut hb.id_from_vertex_colors, "Color ID from vertex colours");
        let hb = hb.clone();
        if ui.add(Btn::primary("Bake from high poly").icon(Icon::Tile).enabled(!hb.maps.is_empty())).clicked() {
            let high = if hb.maps.iter().any(|m| m.needs_high()) {
                match Mesh::load(Path::new(&hb.mesh)) {
                    Ok(m) => Some(m),
                    Err(e) => {
                        app.set_status(format!("High mesh: {e:#}"), true);
                        return;
                    }
                }
            } else {
                None
            };
            match app.bake_high(rs, high.as_ref(), hb, true) {
                Ok(r) => app.set_status(format!("Baked {} maps from the high mesh in {:.1} s (cage {:.4} m, {:.0}% of texels hit)", r.files.len(), r.ms / 1000.0, r.cage, r.hit_rate * 100.0), false),
                Err(e) => app.set_status(e, true),
            }
        }
        let _ = font::SMALL;
    });
}

/// Mask panel: limit the mask to one colour of the project's ID map.
pub fn id_mask_ui(app: &mut PigmentApp, ui: &mut egui::Ui, i: usize) {
    let Some(path) = app.doc.id_map.as_ref().and_then(|p| pigment_core::image_fill::resolve_path(p, &app.image_bases())) else { return };
    ds::section(ui, "ID colour");
    let palette = id_palette(&path);
    let Some(m) = app.doc.layers[i].mask.as_mut() else { return };
    ds::card(ui, |ui| {
        ds::hint(ui, "Only where the ID map has this colour (from a colour ID / material ID bake).");
        ui.horizontal_wrapped(|ui| {
            for c in &palette {
                let f = [c[0] as f32 / 255.0, c[1] as f32 / 255.0, c[2] as f32 / 255.0];
                let on = m.id_color.as_ref().is_some_and(|x| (0..3).all(|k| (x.color[k] - f[k]).abs() < 0.01));
                let (r, resp) = ui.allocate_exact_size(egui::vec2(size::CONTROL_H_SM, size::CONTROL_H_SM), egui::Sense::click());
                ds::paint_material_swatch(ui.painter(), r, f, 0.5, 0.0, 0.0, 1.0, ds::radius::SM);
                if on {
                    ui.painter().rect_stroke(r, egui::CornerRadius::same(ds::radius::SM), egui::Stroke::new(2.0, ds::pal(ui).accent), egui::StrokeKind::Outside);
                }
                if resp.on_hover_text(format!("ID {:?}", c)).clicked() {
                    m.id_color = if on { None } else { Some(pigment_core::IdPick { color: f, tolerance: 0.05 }) };
                }
            }
        });
        if let Some(id) = m.id_color.as_mut() {
            ds::slider_row(ui, "Tolerance", &mut id.tolerance, 0.0..=0.5, ds::Unit::Plain(3));
            if ui.add(Btn::ghost("Any ID").small()).clicked() {
                m.id_color = None;
            }
        }
    });
}
