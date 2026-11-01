//! Foliage panels: the card library (cells of the layer's atlas, quick
//! "add moss / ivy / grass"), the foliage brush settings, and the foliage
//! cell editor for foliage atlas projects (plus bark on seamless tiles).
//! The foliage tool (V) paints cards where the cursor hits the model.

use super::super::design::{self as ds, font, space, Btn, Icon};
use super::super::foliage::{bark_spec, AtlasMeta};
use super::super::ui::Tool;
use super::*;
use pigment_core::foliage::{self as fol, Arrangement, BarkStyle, FoliageCell, LeafShape};
use pigment_core::foliage_set::SurfaceFilter;
use std::collections::HashMap;
use std::sync::Arc;

/// Per-cell thumbnails cut from an atlas, as egui textures.
#[derive(Default)]
struct CellThumbs {
    key: String,
    tex: HashMap<String, egui::TextureHandle>,
}

impl CellThumbs {
    fn get(&mut self, ctx: &egui::Context, meta: &AtlasMeta, cell: usize) -> Option<egui::TextureId> {
        if self.key != meta.key {
            self.key = meta.key.clone();
            self.tex.clear();
        }
        let name = meta.cells.get(cell)?.name.clone();
        if let Some(t) = self.tex.get(&name) {
            return Some(t.id());
        }
        let r = fol::cell_rect(meta.uvs[cell], meta.size);
        let (w, h) = ((r[2] - r[0]).max(1), (r[3] - r[1]).max(1));
        let side = w.max(h);
        // square thumbnail, cell centred on a transparent background
        let mut px = vec![0u8; (side * side * 4) as usize];
        let (ox, oy) = ((side - w) / 2, (side - h) / 2);
        for y in 0..h {
            for x in 0..w {
                let s = (((r[1] + y) * meta.size + r[0] + x) * 4) as usize;
                let d = (((oy + y) * side + ox + x) * 4) as usize;
                let a = meta.color[s + 3] as u32;
                for c in 0..3 {
                    px[d + c] = (meta.color[s + c] as u32 * a / 255) as u8;
                }
                px[d + 3] = a as u8;
            }
        }
        let img = egui::ColorImage::from_rgba_premultiplied([side as usize, side as usize], &px);
        let t = ctx.load_texture(format!("foliage cell {}/{name}", meta.key), img, egui::TextureOptions::LINEAR);
        let id = t.id();
        self.tex.insert(name, t);
        Some(id)
    }
}

impl PigmentApp {
    /// The atlas the foliage brush paints from: the selected foliage layer's,
    /// else the topmost foliage layer's, else the built-in library.
    pub(in crate::app) fn brush_atlas_key(&self) -> String {
        let sel = self.selected.and_then(|id| self.doc.layer(id)).and_then(|l| l.foliage());
        sel.or_else(|| self.doc.layers.iter().rev().find_map(|l| l.foliage())).map(|f| f.atlas.clone()).unwrap_or_else(|| pigment_core::foliage_set::BUILTIN_ATLAS.into())
    }

    /// The foliage layer the brush paints on (the selected one, else the
    /// topmost, created if there is none).
    pub(in crate::app) fn brush_layer(&mut self) -> Result<usize, String> {
        if let Some(i) = self.selected.and_then(|id| self.doc.index_of(id)).filter(|i| self.doc.layers[*i].is_foliage()) {
            return Ok(i);
        }
        let i = self.foliage_layer(None, true)?;
        let id = self.doc.layers[i].id;
        self.select(Some(id), false);
        Ok(i)
    }

    /// Foliage tool input: drag on the model to paint (Shift or the Erase
    /// toggle removes). A stroke is one undo step (the doc diff when the
    /// button goes up).
    pub(in crate::app) fn foliage_input(&mut self, hit: Option<(glam::Vec3, glam::Vec3)>, down: bool, shift: bool) {
        self.foliage.hover = hit;
        if !down {
            self.foliage.last_dab = None;
            return;
        }
        let Some((p, n)) = hit else { return };
        let b = self.foliage.brush.clone();
        if self.foliage.last_dab.is_some_and(|l: glam::Vec3| l.distance(p) < b.radius * 0.5) {
            return;
        }
        self.foliage.last_dab = Some(p);
        let i = match self.brush_layer() {
            Ok(i) => i,
            Err(e) => return self.set_status(e, true),
        };
        let mut b = b;
        b.erase |= shift;
        b.seed = b.seed.wrapping_add(self.foliage.dabs);
        self.foliage.dabs += 1;
        let up = SurfaceFilter::facing(&b.facing).unwrap_or((-1.0, 1.0));
        match self.foliage_paint(i, &[(p, n)], &b, &|_, _, _| 1.0, SurfaceFilter { up, ..Default::default() }) {
            Ok(_) => self.modified = true,
            Err(e) => self.set_status(e, true),
        }
    }
}

fn atlas_of(app: &mut PigmentApp) -> Option<Arc<AtlasMeta>> {
    let key = app.brush_atlas_key();
    app.foliage_atlas(&key).ok()
}

// ------------------------------------------------------------------ library

#[derive(Default)]
pub struct FoliageLibraryPanel {
    thumbs: CellThumbs,
}

/// One-click plants, shared by this panel and the Simple-mode Weathering panel.
pub fn quick_actions(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    ui.horizontal_wrapped(|ui| {
        for (kind, label, tip) in [
            ("moss", "Add moss", "Moss tufts and patches on ledges, sills and in crevices"),
            ("ivy", "Add ivy", "Ivy climbing the walls from the ground"),
            ("grass", "Add grass", "Grass and weeds on the ground and in cracks"),
            ("leaves", "Fallen leaves", "Autumn leaves on the ground and ledges"),
        ] {
            if ui.add(Btn::secondary(label).icon(Icon::Leaf).small()).on_hover_text(tip).clicked() {
                match app.quick_foliage(rs, kind) {
                    Ok(n) => drop(app.ui.toasts.push(super::super::design::ToastKind::Success, label, format!("{n} cards added (one undo step)"))),
                    Err(e) => app.notify_error(label, &e),
                }
            }
        }
    });
}

impl Panel for FoliageLibraryPanel {
    fn id(&self) -> PanelId {
        PanelId::FoliageLibrary
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        ds::section(ui, "Quick plants");
        quick_actions(app, ui, rs);
        ds::hint(ui, "Each adds cards to a foliage layer; they render in the viewport and export with Send to Blender.");
        let Some(meta) = atlas_of(app) else {
            ds::hint(ui, "The card atlas couldn't be loaded.");
            return;
        };
        ds::section(ui, &format!("Cards · {}", if meta.key == "builtin" { "built-in library" } else { meta.key.as_str() }));
        if app.tool() != Tool::Foliage && ui.add(Btn::primary("Use the foliage brush").icon(Icon::Leaf)).clicked() {
            app.set_tool(Tool::Foliage);
        }
        ds::hint(ui, "Click cards to choose what the brush paints (several = a random mix).");
        let w = 92.0;
        ui.horizontal_wrapped(|ui| {
            ui.spacing_mut().item_spacing = egui::vec2(space::SM, space::SM);
            for k in 0..meta.cells.len() {
                let c = &meta.cells[k];
                let on = app.foliage.brush.cells.iter().any(|n| *n == c.name);
                let t = self.thumbs.get(ui.ctx(), &meta, k);
                let sub = format!("{} · {}", c.mount.id(), c.mesh.id());
                if ds::asset_tile_ex(ui, w, w, t, |_, _| {}, &c.name, &sub, on).clicked() {
                    let brush = &mut app.foliage.brush;
                    if on && brush.cells.len() > 1 {
                        brush.cells.retain(|n| *n != c.name);
                    } else if !on {
                        if ui.input(|i| i.modifiers.shift || i.modifiers.command) {
                            brush.cells.push(c.name.clone());
                        } else {
                            brush.cells = vec![c.name.clone()];
                        }
                    }
                    app.set_tool(Tool::Foliage);
                }
            }
        });
    }
}

// ------------------------------------------------------------------ brush

pub struct FoliageBrushPanel;

impl Panel for FoliageBrushPanel {
    fn id(&self) -> PanelId {
        PanelId::FoliageBrush
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, _rs: &RenderState) {
        let active = app.tool() == Tool::Foliage;
        if !active && ui.add(Btn::primary("Use the foliage brush").icon(Icon::Leaf)).clicked() {
            app.set_tool(Tool::Foliage);
        }
        ds::section(ui, "Brush");
        let b = &mut app.foliage.brush;
        ui.label(ds::text(format!("Painting: {}", b.cells.join(", ")), font::SMALL));
        ds::slider_row_ex(ui, "Radius", &mut b.radius, 0.02..=3.0, ds::Unit::Suffix(" m", 2), true, Some("Brush radius in metres on the surface"));
        ds::slider_row_ex(ui, "Density", &mut b.density, 1.0..=400.0, ds::Unit::Suffix(" /m²", 0), true, Some("Cards per square metre; scrubbing fills gaps instead of piling up"));
        ds::slider_row(ui, "Smallest", &mut b.scale.0, 0.2..=3.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Largest", &mut b.scale.1, 0.2..=3.0, ds::Unit::Plain(2));
        b.scale.1 = b.scale.1.max(b.scale.0);
        ds::slider_row_ex(ui, "Stand up", &mut b.align, 0.0..=1.0, ds::Unit::Percent, false, Some("Upright cards: 0 = along the surface, 100% = straight up"));
        let mut f: &str = match b.facing.as_str() {
            "up" => "up",
            "walls" => "walls",
            "down" => "down",
            _ => "any",
        };
        if ds::segmented(ui, &mut f, &[("any", None, "Any surface"), ("up", None, "Up-facing"), ("walls", None, "Walls"), ("down", None, "Undersides")]) {
            b.facing = f.to_string();
        }
        ds::toggle(ui, &mut b.erase, "Erase (or hold Shift)");
        ds::section(ui, "Layer");
        let sel = app.selected.and_then(|id| app.doc.index_of(id)).filter(|i| app.doc.layers[*i].is_foliage());
        match sel {
            Some(i) => {
                let name = app.doc.layers[i].name.clone();
                let set = app.doc.layers[i].foliage_mut().unwrap();
                ui.label(ds::text(format!("{name}: {} cards", set.instances.len()), font::SMALL));
                ds::slider_row_ex(ui, "Wind", &mut set.wind, 0.0..=1.0, ds::Unit::Percent, false, Some("Sway in the viewport preview"));
                if ui.add(Btn::danger("Clear all cards").icon(Icon::Trash).small()).clicked() {
                    set.instances.clear();
                }
            }
            None => {
                ds::hint(ui, "Paints on the selected foliage layer, or a new `Foliage` layer.");
                if ui.add(Btn::secondary("New foliage layer").icon(Icon::Plus).small()).clicked() {
                    let l = app.doc.new_foliage_layer("Foliage");
                    let id = l.id;
                    app.doc.layers.push(l);
                    app.select(Some(id), false);
                }
            }
        }
    }
}

// ------------------------------------------------------------------ cell editor

pub struct FoliageCellsPanel;

fn shape_label(s: LeafShape) -> &'static str {
    s.id()
}

impl Panel for FoliageCellsPanel {
    fn id(&self) -> PanelId {
        PanelId::FoliageCells
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, _rs: &RenderState) {
        // bark on seamless tiles
        let bark_i = app.doc.layers.iter().position(|l| matches!(l.generated, Some(Generated::Bark { .. })));
        let is_tile = app.doc.tile.as_ref().is_some_and(|t| t.kind == pigment_core::tile::SheetKind::Tile);
        if is_tile {
            ds::section(ui, "Bark");
            match bark_i {
                None => {
                    ui.horizontal_wrapped(|ui| {
                        for st in BarkStyle::ALL {
                            if ui.add(Btn::secondary(st.id()).small()).clicked() {
                                let mut l = app.doc.new_paint_layer("Bark (generated)");
                                l.generated = Some(Generated::Bark { bark: bark_spec(st.id()).unwrap() });
                                let at = 1.min(app.doc.layers.len());
                                app.doc.layers.insert(at, l);
                            }
                        }
                    });
                }
                Some(i) => {
                    if let Some(Generated::Bark { bark }) = &mut app.doc.layers[i].generated {
                        let mut st = bark.style;
                        if ds::segmented(ui, &mut st, &BarkStyle::ALL.map(|s| (s, None, s.id()))) {
                            *bark = pigment_core::foliage::BarkSpec { seed: bark.seed, ..pigment_core::foliage::BarkSpec::for_style(st) };
                        }
                        ds::slider_row(ui, "Scale", &mut bark.scale, 1.0..=30.0, ds::Unit::Suffix(" /m", 1));
                        ds::slider_row(ui, "Stretch", &mut bark.stretch, 0.2..=6.0, ds::Unit::Plain(2));
                        ds::slider_row(ui, "Depth", &mut bark.depth, 0.0..=1.0, ds::Unit::Percent);
                        ds::slider_row(ui, "Lichen", &mut bark.lichen, 0.0..=1.0, ds::Unit::Percent);
                        let mut seed = bark.seed as f32;
                        if ds::slider_row(ui, "Seed", &mut seed, 0.0..=999.0, ds::Unit::Plain(0)).changed() {
                            bark.seed = seed as u32;
                        }
                        ui.horizontal(|ui| {
                            ds::color_picker(ui, &mut bark.color);
                            ds::color_picker(ui, &mut bark.crack_color);
                            ds::color_picker(ui, &mut bark.accent_color);
                        });
                    }
                }
            }
        }
        let gi = app.doc.layers.iter().position(|l| matches!(l.generated, Some(Generated::FoliageCells { .. })));
        let Some(gi) = gi else {
            if !is_tile {
                ds::empty_state(ui, Icon::Leaf, "No foliage atlas", "Start one over MCP with new_project {foliage_atlas: {cells: [...]}}: leaves, twigs, needles, blossoms, grass, ivy, drawn by generators.", None);
            }
            return;
        };
        let Some(Generated::FoliageCells { cells }) = &mut app.doc.layers[gi].generated else { return };
        if cells.is_empty() {
            return;
        }
        let k = app.foliage.edit_cell.min(cells.len() - 1);
        ds::section(ui, "Cell");
        let mut pick = k;
        ui.horizontal_wrapped(|ui| {
            for (i, c) in cells.iter().enumerate() {
                if ui.add(Btn::ghost(c.name.as_str()).small().selected(i == k)).clicked() {
                    pick = i;
                }
            }
        });
        app.foliage.edit_cell = pick;
        let c: &mut FoliageCell = &mut cells[pick];
        ui.horizontal_wrapped(|ui| {
            ui.label(ds::muted(ui, "Preset"));
            egui::ComboBox::from_id_salt("foliage preset").selected_text(if c.preset.is_empty() { "custom" } else { c.preset.as_str() }).show_ui(ui, |ui| {
                for p in fol::PRESETS {
                    if ui.selectable_label(c.preset == p, p).clicked() {
                        if let Some(n) = FoliageCell::from_preset(&c.name, p) {
                            let size = c.size_m;
                            *c = FoliageCell { size_m: size, ..n };
                        }
                    }
                }
            });
        });
        let s = &mut c.spec;
        ds::section(ui, "Shape");
        let mut shape = s.shape;
        egui::ComboBox::from_id_salt("foliage shape").selected_text(shape_label(shape)).show_ui(ui, |ui| {
            for sh in LeafShape::ALL {
                ui.selectable_value(&mut shape, sh, shape_label(sh));
            }
        });
        s.shape = shape;
        let mut arr = s.arrangement;
        egui::ComboBox::from_id_salt("foliage arrangement").selected_text(arr.id()).show_ui(ui, |ui| {
            for a in Arrangement::ALL {
                ui.selectable_value(&mut arr, a, a.id());
            }
        });
        s.arrangement = arr;
        let int = |ui: &mut egui::Ui, label: &str, v: &mut u32, max: f32| {
            let mut f = *v as f32;
            if ds::slider_row(ui, label, &mut f, 1.0..=max, ds::Unit::Plain(0)).changed() {
                *v = f.round() as u32;
            }
        };
        int(ui, "Count", &mut s.count, 300.0);
        int(ui, "Lobes / pairs", &mut s.lobes, 16.0);
        ds::slider_row(ui, "Lobe depth", &mut s.lobe_depth, 0.0..=0.95, ds::Unit::Percent);
        ds::slider_row(ui, "Aspect", &mut s.aspect, 0.0..=1.2, ds::Unit::Plain(2));
        ds::slider_row(ui, "Leaf size", &mut s.leaf_size, 0.0..=1.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Serration", &mut s.serration, 0.0..=1.0, ds::Unit::Percent);
        int(ui, "Teeth", &mut s.teeth, 40.0);
        ds::slider_row(ui, "Bend", &mut s.bend, -1.0..=1.0, ds::Unit::Plain(2));
        ds::section(ui, "Veins");
        ds::slider_row(ui, "Venation", &mut s.venation, 0.0..=1.0, ds::Unit::Percent);
        int(ui, "Veins", &mut s.veins, 40.0);
        ds::slider_row(ui, "Vein angle", &mut s.vein_angle, 15.0..=80.0, ds::Unit::Suffix("°", 0));
        ds::section(ui, "Colour");
        ui.horizontal(|ui| {
            ds::color_picker(ui, &mut s.color);
            ds::color_picker(ui, &mut s.tip_color);
            ds::color_picker(ui, &mut s.vein_color);
            ds::color_picker(ui, &mut s.autumn_color);
        });
        ds::slider_row(ui, "Hue jitter", &mut s.hue_jitter, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Autumn", &mut s.autumn, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Dry edges", &mut s.dry_edges, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Holes", &mut s.holes, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Insect bites", &mut s.bites, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Translucency", &mut s.translucency, 0.0..=1.0, ds::Unit::Percent);
        let mut seed = s.seed as f32;
        if ds::slider_row(ui, "Seed", &mut seed, 0.0..=999.0, ds::Unit::Plain(0)).changed() {
            s.seed = seed as u32;
        }
        ds::hint(ui, "Edits redraw only this cell. Card size and new cells: update_foliage_cell / add_foliage_cell (they repack the atlas).");
    }
}
