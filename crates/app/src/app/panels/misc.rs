//! Viewport, Brush, Parts, Variants, Lighting, History, Export and
//! Texture set panels.

use super::super::design::{self as ds, font, size, space, Btn, Icon, IconBtn, RichTip, ToastKind};
use super::super::jobs;
use super::*;

pub struct ViewportPanel;

impl Panel for ViewportPanel {
    fn id(&self) -> PanelId {
        PanelId::Viewport
    }
    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        app.viewport_ui(ui, rs);
    }
}

// ------------------------------------------------------------------ brush

pub struct BrushPanel;

impl Panel for BrushPanel {
    fn id(&self) -> PanelId {
        PanelId::Brush
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        let painting_mask = matches!(app.paint_target(), Ok(Target::Mask(_)));
        ds::slider_row_ex(ui, "Size", &mut app.brush.size, 2.0..=800.0, ds::Unit::Suffix(" px", 0), true, Some("[ and ] change it"));
        ds::slider_row(ui, "Strength", &mut app.brush.opacity, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Hardness", &mut app.brush.hardness, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row(ui, "Spacing", &mut app.brush.spacing, 0.02..=1.0, ds::Unit::Percent);
        super::brush::brush_engine_ui(app, ui, rs);
        if painting_mask {
            ds::card(ui, |ui| {
                ui.label(ds::strong("You're painting a mask", font::BODY));
                ds::hint(ui, "White reveals the layer, black hides it (X swaps). Pick the Layer tab in Properties to paint material again.");
                ds::segmented(ui, &mut app.brush.mask_white, &[(true, None, "White: reveal"), (false, None, "Black: hide")]);
            });
            return;
        }
        ds::section(ui, "Brush material");
        ds::card(ui, |ui| {
            ui.horizontal(|ui| {
                let (rect, _) = ui.allocate_exact_size(egui::vec2(48.0, 48.0), egui::Sense::hover());
                let v = &app.brush.values;
                ds::paint_material_swatch(ui.painter(), rect, v.base_color, v.roughness, v.metallic, v.emissive_strength, v.opacity, ds::radius::MD);
                ui.vertical(|ui| {
                    let name = material_presets().into_iter().find(|(_, x)| x == v).map(|(n, _)| n).unwrap_or("Custom");
                    ui.label(ds::strong(name, font::TITLE));
                    ui.label(ds::mono(format!("rough {:.2} · metal {:.2}", v.roughness, v.metallic)).color(p.text_muted));
                });
            });
        });
        ds::section(ui, "Presets");
        let grid = ui.horizontal_wrapped(|ui| {
            ui.spacing_mut().item_spacing = egui::vec2(space::XS, space::XS);
            for (name, v) in material_presets() {
                let (r, resp) = ui.allocate_exact_size(egui::vec2(26.0, 26.0), egui::Sense::click());
                ds::paint_material_swatch(ui.painter(), r, v.base_color, v.roughness, v.metallic, v.emissive_strength, v.opacity, ds::radius::SM);
                let on = app.brush.values == v;
                if on || resp.hovered() {
                    ui.painter().rect_stroke(r.expand(2.0), egui::CornerRadius::same(ds::radius::MD), egui::Stroke::new(1.5, if on { p.accent } else { p.text_muted }), egui::StrokeKind::Outside);
                }
                if resp.on_hover_text(name).clicked() {
                    let (see, trans) = v.is_see_through();
                    let (coat, flake) = v.is_coated();
                    app.brush.channels = [true, true, true, v.height.abs() > 0.01, false, v.emissive_strength > 0.0, see, trans, coat, coat, flake];
                    app.brush.values = v;
                    if app.brush.erase {
                        app.set_tool(super::super::ui::Tool::Paint);
                    }
                }
            }
        });
        if app.ui.prefs.mode == super::super::prefs::Mode::Advanced || app.anchors.get("presets").is_none() {
            app.anchors.entry("presets").or_insert(grid.response.rect);
        }
        ds::section(ui, "What the brush paints");
        super::layers::material_editor(ui, "brush", &mut app.brush.values, Some(&mut app.brush.channels));
    }
}

// ------------------------------------------------------------------ parts

#[derive(Default)]
pub struct PartsPanel {
    filter: String,
}

impl Panel for PartsPanel {
    fn id(&self) -> PanelId {
        PanelId::Parts
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        let n = app.parts.info.len();
        ui.label(ds::strong(format!("{n} part{}", if n == 1 { "" } else { "s" }), font::TITLE));
        ds::hint(ui, "Parts are the separate pieces of the model. Limit a layer to some of them, or fill one with a material (G).");
        let Some(i) = app.selected.and_then(|id| app.doc.index_of(id)) else {
            ds::empty_state(ui, Icon::Layers, "Select a layer", "Then tick the parts it should cover.", None);
            return;
        };
        ui.horizontal(|ui| {
            let pick = app.part_pick;
            if ui.add(Btn::secondary(if pick { "Done picking" } else { "Pick in viewport" }).icon(Icon::Target).small().selected(pick)).clicked() {
                app.set_tool(if pick { super::super::ui::Tool::Paint } else { super::super::ui::Tool::Pick });
            }
            if ui.add(Btn::ghost("Whole model").small()).clicked() {
                if let Some(m) = app.doc.layers[i].mask.as_mut() {
                    m.parts.clear();
                }
            }
            if ui.add(IconBtn::new(Icon::Frame, "Frame the chosen parts").size(size::CONTROL_H_SM)).clicked() {
                app.frame_selected();
            }
        });
        ds::search_field(ui, &mut self.filter, "Filter: part number or min triangles");
        let chosen: Vec<u32> = app.doc.layers[i].mask.as_ref().map(|m| m.parts.clone()).unwrap_or_default();
        let min_tris: u32 = self.filter.trim().parse().unwrap_or(0);
        let mut toggle = None;
        egui::Grid::new("parts").num_columns(3).spacing([space::MD, space::XXS]).striped(true).show(ui, |ui| {
            for (k, info) in app.parts.info.iter().enumerate().take(MAX_SELECTABLE_PARTS as usize) {
                if min_tris > 0 && info.triangles < min_tris && !k.to_string().starts_with(self.filter.trim()) {
                    continue;
                }
                let mut on = chosen.contains(&(k as u32));
                if ui.checkbox(&mut on, ds::mono(format!("#{k}"))).changed() {
                    toggle = Some(k as u32);
                }
                ui.label(ds::text(format!("{} tris", info.triangles), font::SMALL).color(p.text_muted));
                let s = glam::Vec3::from(info.max) - glam::Vec3::from(info.min);
                ui.label(ds::mono(format!("{:.2}×{:.2}×{:.2} m", s.x, s.y, s.z)).color(p.text_muted));
                ui.end_row();
            }
        });
        if let Some(part) = toggle {
            match app.toggle_part(rs, part) {
                Ok(m) => app.set_status(m, false),
                Err(e) => app.set_status(e, true),
            }
        }
    }
}

// ------------------------------------------------------------------ variants

pub struct VariantsPanel;

impl Panel for VariantsPanel {
    fn id(&self) -> PanelId {
        PanelId::Variants
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, _rs: &RenderState) {
        let p = ds::pal(ui);
        ds::hint(ui, "Variants are versions of the same texture set: lit / unlit windows, other posters, different dirt. Tag layers with a group, preview a seed, export them all with the MCP tool export_variants.");
        ds::section(ui, "Preview");
        let mut seed = app.doc.variants.seed as f32;
        if ds::slider_row_ex(ui, "Seed", &mut seed, 0.0..=999.0, ds::Unit::Plain(0), false, Some("Random part subsets and generator noise follow it. 0 = the authored look")).changed() {
            app.doc.variants.seed = seed.round() as u32;
        }
        ui.horizontal(|ui| {
            if ui.add(Btn::secondary("Shuffle").icon(Icon::Dice).small()).clicked() {
                app.doc.variants.seed = (app.doc.variants.seed * 7919 + 101) % 1000 + 1;
            }
            if ui.add(Btn::ghost("Authored look").small()).clicked() {
                app.doc.variants.seed = 0;
            }
        });
        if let Some(i) = app.selected.and_then(|id| app.doc.index_of(id)) {
            ds::section(ui, "Selected layer");
            let l = &mut app.doc.layers[i];
            ui.horizontal(|ui| {
                ds::prop_label(ui, "Group", Some("Variants switch every layer and decal of a group on or off"));
                ui.add(egui::TextEdit::singleline(&mut l.variant.group).desired_width(140.0).hint_text("none"));
            });
            if !l.variant.decals.is_empty() {
                ds::prop_label(ui, &format!("{} recorded decal(s)", l.variant.decals.len()), None);
                for d in &mut l.variant.decals {
                    ui.horizontal(|ui| {
                        ui.checkbox(&mut d.enabled, ds::text(&d.name, font::SMALL));
                        if !d.group.is_empty() {
                            ds::badge(ui, &d.group, p.info);
                        }
                    });
                }
            }
        }
        ds::section(ui, "Groups in this project");
        let mut groups: Vec<String> = app.doc.layers.iter().map(|l| l.variant.group.clone()).filter(|g| !g.is_empty()).collect();
        groups.sort();
        groups.dedup();
        if groups.is_empty() {
            ds::hint(ui, "None yet: type a group name on a layer above.");
        }
        ui.horizontal_wrapped(|ui| {
            for g in groups {
                ds::badge(ui, &g, p.accent);
            }
        });
        ds::section(ui, "Defined variants");
        if app.doc.variants.defs.is_empty() {
            ds::hint(ui, "None stored. Scripts define them with export_variants { variants: [...] }.");
        }
        for v in &app.doc.variants.defs {
            ds::card(ui, |ui| {
                ui.label(ds::strong(&v.name, font::BODY));
                ui.label(ds::text(format!("seed {} · enable {:?} · disable {:?}", v.seed, v.enable, v.disable), font::SMALL).color(p.text_muted));
            });
        }
    }
}

// ------------------------------------------------------------------ lighting

/// Lighting preset cards (studio, night city, overcast, the game skies).
pub fn lighting_presets(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    let p = ds::pal(ui);
    ui.horizontal_wrapped(|ui| {
        ui.spacing_mut().item_spacing = egui::vec2(space::XS, space::XS);
        for (id, label) in pigment_core::envmath::PRESETS.iter().chain(pigment_core::envmath::SKIES.iter()) {
            let found = pigment_core::envmath::PRESETS.iter().any(|(i, _)| i == id) || pigment_core::envmath::sky_path(id).is_some();
            let ic = if id.contains("night") || id.contains("moon") { Icon::Moon } else { Icon::Sun };
            let r = ui.add(Btn::ghost(*label).icon(ic).small().selected(app.env.source == *id).enabled(found));
            if r.clicked() {
                app.set_lighting(rs, id);
            }
        }
    });
    let _ = p;
}

/// Exposure, rotation, background, bloom, presets and HDRI loading.
pub fn lighting_controls(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    lighting_presets(app, ui, rs);
    ui.add_space(space::SM);
    ds::slider_row(ui, "Exposure", &mut app.view.exposure, -4.0..=4.0, ds::Unit::Suffix(" EV", 1));
    let mut deg = app.view.env_rotation.to_degrees();
    if ds::slider_row(ui, "Rotate light", &mut deg, -180.0..=180.0, ds::Unit::Suffix("°", 0)).changed() {
        app.view.env_rotation = deg.to_radians();
    }
    ds::toggle(ui, &mut app.view.show_env, "Show the environment behind the model");
    ds::toggle(ui, &mut app.view.bloom.enabled, "Bloom: glow around lights and neon");
    if app.view.bloom.enabled {
        ds::slider_row(ui, "Threshold", &mut app.view.bloom.threshold, 0.0..=4.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Intensity", &mut app.view.bloom.intensity, 0.0..=2.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Radius", &mut app.view.bloom.radius, 0.0..=1.0, ds::Unit::Plain(2));
    }
    if ui.add(Btn::ghost("Load HDRI (.hdr / .exr)…").icon(Icon::Open).small()).clicked() {
        if let Some(pth) = rfd::FileDialog::new().add_filter("HDR images", &["hdr", "exr"]).pick_file() {
            app.open_path(rs, &pth);
        }
    }
}

pub struct LightingPanel;

impl Panel for LightingPanel {
    fn id(&self) -> PanelId {
        PanelId::Lighting
    }
    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        ds::hint(ui, "Lighting only changes how the model looks here, not the exported textures.");
        lighting_controls(app, ui, rs);
    }
}

// ------------------------------------------------------------------ history

pub struct HistoryPanel;

impl Panel for HistoryPanel {
    fn id(&self) -> PanelId {
        PanelId::History
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        let (labels, applied) = app.history.history();
        let labels: Vec<String> = labels.iter().map(|s| s.to_string()).collect();
        if labels.is_empty() {
            ds::empty_state(ui, Icon::History, "No steps yet", "Every stroke and change appears here. Click a step to go back to it.", None);
            return;
        }
        let mut jump: Option<usize> = None;
        let row = |ui: &mut egui::Ui, label: &str, on: bool, future: bool| {
            let (r, resp) = ui.allocate_exact_size(egui::vec2(ui.available_width(), size::CONTROL_H), egui::Sense::click());
            let bg = if on { p.accent_subtle } else if resp.hovered() { p.surface_hover } else { egui::Color32::TRANSPARENT };
            ui.painter().rect_filled(r, egui::CornerRadius::same(ds::radius::MD), bg);
            let c = if future { p.text_disabled } else { p.text };
            ui.painter().circle_filled(egui::pos2(r.left() + space::LG, r.center().y), 3.5, if on { p.accent } else if future { p.border } else { p.text_muted });
            ui.painter().text(egui::pos2(r.left() + space::XL + space::MD, r.center().y), egui::Align2::LEFT_CENTER, label, ds::fonts::regular(font::SMALL), c);
            resp
        };
        if row(ui, "Opened", applied == 0, false).clicked() {
            jump = Some(0);
        }
        for (k, l) in labels.iter().enumerate() {
            if row(ui, l, k + 1 == applied, k >= applied).on_hover_text(if k >= applied { "Undone: click to redo up to here" } else { "Click to go back to this step" }).clicked() {
                jump = Some(k + 1);
            }
        }
        if let Some(target) = jump {
            app.history_jump(rs, target);
        }
    }
}

impl PigmentApp {
    /// Undo / redo until `applied` steps are applied.
    pub(in crate::app) fn history_jump(&mut self, rs: &RenderState, applied: usize) {
        self.commit_doc_changes();
        for _ in 0..512 {
            let (_, now) = self.history.history();
            if now > applied {
                self.undo(rs, false);
            } else if now < applied {
                self.undo(rs, true);
            } else {
                break;
            }
        }
    }
}

// ------------------------------------------------------------------ export

/// Target cards, name, folder and the Export button (dialog and panel).
pub fn export_body(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState, compact: bool) -> bool {
    let p = ds::pal(ui);
    let mut done = false;
    ds::section(ui, "Where is it going?");
    let cols = if compact { 2 } else { 5 };
    egui::Grid::new(("export targets", compact)).spacing([space::SM, space::SM]).show(ui, |ui| {
        for (k, t) in jobs::TARGETS.iter().enumerate() {
            let on = app.ui.export_target == t.id;
            let w = if compact { (ui.available_width() / 2.0 - space::SM).max(90.0) } else { 96.0 };
            let (r, resp) = ui.allocate_exact_size(egui::vec2(w, 64.0), egui::Sense::click());
            let bg = if on { p.accent_subtle } else if resp.hovered() { p.surface_hover } else { p.surface_raised };
            ui.painter().rect(r, egui::CornerRadius::same(ds::radius::LG), bg, egui::Stroke::new(if on { 1.5 } else { 1.0 }, if on { p.accent } else { p.border }), egui::StrokeKind::Inside);
            let ic = match t.id {
                "blender" => Icon::Send,
                "unreal" => Icon::Play,
                "unity" => Icon::Cube,
                "godot" => Icon::Gear,
                _ => Icon::Image,
            };
            ic.paint(ui.painter(), egui::Rect::from_center_size(r.center() - egui::vec2(0.0, 10.0), egui::vec2(20.0, 20.0)), if on { p.accent } else { p.text_secondary });
            ui.painter().text(r.center() + egui::vec2(0.0, 16.0), egui::Align2::CENTER_CENTER, t.label, ds::fonts::semibold(font::SMALL), p.text);
            if resp.on_hover_ui(|ui| ds::tooltip_body(ui, t.label, Some(t.blurb), None)).clicked() {
                app.ui.export_target = t.id;
                app.ui.prefs.export_target = t.id.to_string();
            }
            if (k + 1) % cols == 0 {
                ui.end_row();
            }
        }
    });
    let t = jobs::target(app.ui.export_target);
    ds::hint(ui, t.blurb);
    ui.add_space(space::SM);
    let dir = app.ui.prefs.export_dir.clone().unwrap_or_else(jobs::default_export_root).join(app.export_name.trim());
    ds::prop_grid(ui, ("export grid", compact).0, |ui| {
        ds::prop_label(ui, "Name", Some("File names start with it: Name_BaseColor.png ..."));
        ui.add(egui::TextEdit::singleline(&mut app.export_name).desired_width(200.0));
        ui.end_row();
        ds::prop_label(ui, "Folder", None);
        ui.horizontal(|ui| {
            ui.add(egui::Label::new(ds::text(dir.display().to_string(), font::SMALL).color(p.text_muted)).truncate());
        });
        ui.end_row();
        ds::prop_label(ui, "", None);
        if ui.add(Btn::ghost("Change folder…").icon(Icon::Open).small()).clicked() {
            if let Some(d) = rfd::FileDialog::new().pick_folder() {
                app.ui.prefs.export_dir = Some(d);
            }
        }
        ui.end_row();
        ds::prop_label(ui, "Size", Some("Change it in Texture set & bake"));
        ui.label(ds::mono(format!("{0} × {0} px", app.ts.res)));
        ui.end_row();
    });
    if !compact {
        egui::CollapsingHeader::new(ds::caption(ui, "More options")).id_salt("export more").show(ui, |ui| {
            ui.horizontal(|ui| {
                ds::prop_label(ui, "PNG compression", Some("Fast writes bigger files; best is slowest"));
                egui::ComboBox::from_id_salt("png compression").selected_text(app.export_compression.id()).show_ui(ui, |ui| {
                    for c in export::Compression::ALL {
                        ui.selectable_value(&mut app.export_compression, c, c.id());
                    }
                });
            });
            if let Some(preset) = export::preset(t.preset) {
                ds::card(ui, |ui| {
                    for o in &preset.outputs {
                        ui.label(ds::mono(format!("{}_{}.png", app.export_name, o.suffix)).color(p.text_secondary));
                    }
                    if t.with_mesh {
                        ui.label(ds::mono(format!("{}.glb  material.json", app.export_name)).color(p.text_secondary));
                    }
                });
            }
        });
    }
    ui.add_space(space::SM);
    let busy = app.busy_with("export");
    let ready = !app.export_name.trim().is_empty() && !busy;
    let label = if busy { "Exporting…".to_string() } else { format!("Export for {}", t.label) };
    let r = ui.add(Btn::primary(label).icon(Icon::Export).large().fill().enabled(ready));
    app.anchors.insert("export_go", r.rect);
    if r.clicked() {
        let _ = std::fs::create_dir_all(&dir);
        app.export_dir = Some(dir.clone());
        app.export_async(rs, t, dir);
        done = true;
    }
    if let Some(last) = app.ui.last_export.clone() {
        ui.horizontal(|ui| {
            ui.label(ds::text("Last export:", font::SMALL).color(p.text_muted));
            if ui.add(Btn::ghost("Show folder").icon(Icon::Open).small()).rich_tip("Open the folder", &last.display().to_string()).clicked() {
                open_folder(&last);
            }
        });
    }
    done
}

pub fn open_folder(p: &Path) {
    #[cfg(target_os = "windows")]
    let _ = std::process::Command::new("explorer").arg(p).spawn();
    #[cfg(target_os = "macos")]
    let _ = std::process::Command::new("open").arg(p).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let _ = std::process::Command::new("xdg-open").arg(p).spawn();
}

pub struct ExportPanel;

impl Panel for ExportPanel {
    fn id(&self) -> PanelId {
        PanelId::Export
    }
    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        export_body(app, ui, rs, true);
    }
}

impl PigmentApp {
    /// Export textures + mesh + material.json for the Blender add-on.
    pub(in crate::app) fn send_to_blender(&mut self, rs: &RenderState) {
        let t = jobs::target("blender");
        let dir = self.ui.prefs.export_dir.clone().unwrap_or_else(jobs::default_export_root).join(self.export_name.trim());
        let _ = std::fs::create_dir_all(&dir);
        self.export_async(rs, t, dir);
        self.ui.toasts.push(ToastKind::Info, "In Blender", "Pigment Bridge add-on: N panel > Pigment > Link, and pick this folder.");
    }
}

// ------------------------------------------------------------------ texture set

pub struct TextureSetPanel;

impl Panel for TextureSetPanel {
    fn id(&self) -> PanelId {
        PanelId::TextureSet
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let mut res = app.doc.resolution;
        ds::prop_grid(ui, "texture set", |ui| {
            ds::prop_label(ui, "Texture size", Some("Resamples every layer; clears undo"));
            egui::ComboBox::from_id_salt("res").selected_text(format!("{res} × {res}")).show_ui(ui, |ui| {
                for r in RESOLUTIONS {
                    ui.selectable_value(&mut res, r, format!("{r} × {r}"));
                }
            });
            ui.end_row();
            ds::prop_label(ui, "AO quality", None);
            egui::ComboBox::from_id_salt("ao").selected_text(format!("{} rays", app.doc.bake.ao_samples)).show_ui(ui, |ui| {
                for n in [32, 64, 128, 256, 512] {
                    ui.selectable_value(&mut app.doc.bake.ao_samples, n, format!("{n} rays"));
                }
            });
            ui.end_row();
        });
        if res != app.doc.resolution {
            app.change_resolution(rs, res);
        }
        ds::slider_row_ex(ui, "AO distance", &mut app.doc.bake.ao_distance, 0.02..=2.0, ds::Unit::Suffix(" m", 2), true, None);
        ds::slider_row_ex(ui, "Edge width", &mut app.doc.bake.curvature_radius, 0.005..=0.2, ds::Unit::Plain(3), true, None);
        ds::slider_row(ui, "Edge strength", &mut app.doc.bake.curvature_strength, 0.1..=4.0, ds::Unit::Plain(2));
        let baking = app.ui.jobs.iter().any(|j| matches!(j.kind, jobs::JobKind::Bake { .. }));
        if ui.add(Btn::secondary(if baking { "Baking…" } else { "Re-bake AO + curvature" }).icon(Icon::Tile).enabled(!baking)).clicked() {
            app.bake(rs);
        }
        ds::hint(ui, "Edge wear, dirt and other generators read these maps. See them with the AO / Curvature chips on the viewport (Advanced).");
        if let Some(t) = &app.doc.tile {
            ds::section(ui, "Sheet");
            ui.label(ds::text(format!("{} · {} cell(s)", t.kind.id(), t.cells.len()), font::SMALL));
        }
    }
}
