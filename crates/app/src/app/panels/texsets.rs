//! Texture sets: the switcher at the top of the Layers panel and the split
//! actions in the Texture set & bake panel.

use super::super::design::{self as ds, font, Btn, Icon};
use super::*;
use pigment_core::texsets;

/// Which texture set the layer stack shows (only with several sets).
pub fn set_switcher(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    if !app.has_sets() {
        return;
    }
    let names = app.set_names();
    let active = app.active_set_name();
    let mut pick: Option<String> = None;
    ui.horizontal(|ui| {
        ds::prop_label(ui, "Texture set", Some("Each set paints part of the model (a material or a UDIM tile) with its own layers and resolution. Strokes paint across sets."));
        let label = format!("{active} · {} px · {}", app.doc.resolution, app.doc.texture_set.as_ref().map(|s| s.tile()).unwrap_or(1001));
        egui::ComboBox::from_id_salt("texture set").selected_text(label).show_ui(ui, |ui| {
            for n in &names {
                if ui.selectable_label(*n == active, n).clicked() {
                    pick = Some(n.clone());
                }
            }
        });
    });
    if let Some(n) = pick {
        if let Err(e) = app.activate_set(rs, &n) {
            app.set_status(e, true);
        }
    }
}

/// Split a single-set project by material or by UDIM tile.
pub fn split_ui(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    ds::section(ui, "Texture sets");
    ds::card(ui, |ui| {
        if app.has_sets() {
            ui.label(ds::text(format!("{} texture sets: {}", app.set_names().len(), app.set_names().join(", ")), font::SMALL));
            ds::hint(ui, "Switch sets at the top of the Layers panel. Export writes <name>_<set>_<map>.<udim>.png.");
            return;
        }
        let materials = app.mesh.material_count();
        let tiles = texsets::mesh_tiles(&app.mesh).len();
        ds::hint(ui, &format!("This model has {materials} material(s) and {tiles} UDIM tile(s). One texture set per material or tile gives each its own resolution and layers."));
        let mut by: Option<Vec<texsets::SetSpec>> = None;
        ui.horizontal_wrapped(|ui| {
            if ui.add(Btn::secondary("One set per material").icon(Icon::Layers).small().enabled(materials > 1)).clicked() {
                by = Some(texsets::sets_by_material(&app.mesh));
            }
            if ui.add(Btn::secondary("One set per UDIM tile").icon(Icon::Grid).small().enabled(tiles > 1)).clicked() {
                by = Some(texsets::sets_by_tile(&app.mesh, "tile"));
            }
        });
        if let Some(specs) = by {
            match app.split_sets(rs, specs, &[]) {
                Ok(n) => app.set_status(format!("{} texture sets: {}", n.len(), n.join(", ")), false),
                Err(e) => app.set_status(e, true),
            }
        }
    });
}
