//! Modal dialogs: unsaved changes, export, new project, settings and
//! "save layout as".

use super::design::{self as ds, font, size, space, Btn, Icon};
use super::dock::DockLayout;
use super::*;

impl PigmentApp {
    pub(super) fn dialogs(&mut self, ctx: &egui::Context, rs: &RenderState) {
        if let Some(pend) = self.pending.clone() {
            let mut choice = 0;
            let (_, dismissed) = ds::modal(ctx, "unsaved", "Save your changes first?", 420.0, |ui| {
                ds::hint(ui, "This project has changes that aren't saved. If you continue without saving they're lost.");
                ui.add_space(space::LG);
                ui.horizontal(|ui| {
                    if ui.add(Btn::primary("Save").icon(Icon::Save)).clicked() {
                        choice = 1;
                    }
                    if ui.add(Btn::danger("Don't save")).clicked() {
                        choice = 2;
                    }
                    if ui.add(Btn::ghost("Cancel")).clicked() {
                        choice = 3;
                    }
                });
            });
            let sample = self.ui.pending_sample;
            let go = |app: &mut PigmentApp| match sample {
                Some(k) => {
                    app.ui.pending_sample = None;
                    app.open_sample(rs, &super::welcome::SAMPLES[k]);
                }
                None => app.run_pending_ui(rs, pend.clone()),
            };
            match choice {
                1 => {
                    self.save(rs, false);
                    self.pending = None;
                    if !self.modified {
                        go(self);
                    }
                }
                2 => {
                    self.pending = None;
                    self.modified = false;
                    go(self);
                }
                3 => {
                    self.pending = None;
                    self.ui.pending_sample = None;
                }
                _ if dismissed => {
                    self.pending = None;
                    self.ui.pending_sample = None;
                }
                _ => {}
            }
        }

        if self.show_export {
            let (exported, dismissed) = ds::modal(ctx, "export", "Export textures", size::DIALOG_W, |ui| super::panels::misc::export_body(self, ui, rs, false));
            if exported || dismissed {
                self.show_export = false;
            }
        }

        if self.ui.new_project.open {
            self.new_project_dialog(ctx, rs);
        }
        if self.ui.settings {
            self.settings_dialog(ctx);
        }
        if let Some(mut name) = self.ui.save_layout.clone() {
            let mut close = false;
            let (_, dismissed) = ds::modal(ctx, "save layout", "Save layout", 360.0, |ui| {
                ds::hint(ui, "Keeps the current panel arrangement under a name in Window > Layouts.");
                let r = ui.add(egui::TextEdit::singleline(&mut name).desired_width(f32::INFINITY));
                r.request_focus();
                ui.add_space(space::MD);
                ui.horizontal(|ui| {
                    if ui.add(Btn::primary("Save layout").enabled(!name.trim().is_empty())).clicked() || (r.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter))) {
                        let l = self.ui.prefs.layout().clone();
                        self.ui.prefs.custom_layouts.retain(|(n, _)| n != name.trim());
                        self.ui.prefs.custom_layouts.push((name.trim().to_string(), l));
                        let _ = self.ui.prefs.save();
                        close = true;
                    }
                    if ui.add(Btn::ghost("Cancel")).clicked() {
                        close = true;
                    }
                });
            });
            self.ui.save_layout = if close || dismissed { None } else { Some(name) };
        }
    }

    fn new_project_dialog(&mut self, ctx: &egui::Context, rs: &RenderState) {
        let p = ds::theme(ctx).p;
        let mut create = false;
        let (_, dismissed) = ds::modal(ctx, "new project", "New project", 600.0, |ui| {
            let kinds: [(Icon, &str, &str); 5] = [
                (Icon::Cube, "Your model", "Paint an OBJ / glTF / GLB with UVs"),
                (Icon::Sparkle, "A sample", "The crate, vending machine, building or car"),
                (Icon::Tile, "Seamless tile", "A texture that repeats in both directions"),
                (Icon::Trim, "Trim sheet", "Horizontal strips for trims, pipes and edges"),
                (Icon::Atlas, "Decal atlas", "Cells for signs, labels and stickers"),
            ];
            let np = &mut self.ui.new_project;
            egui::Grid::new("np kinds").spacing([space::SM, space::SM]).show(ui, |ui| {
                for (k, (ic, title, blurb)) in kinds.iter().enumerate() {
                    let on = np.kind == k;
                    let (r, resp) = ui.allocate_exact_size(egui::vec2(108.0, 96.0), egui::Sense::click());
                    let bg = if on { p.accent_subtle } else if resp.hovered() { p.surface_hover } else { p.surface_raised };
                    ui.painter().rect(r, egui::CornerRadius::same(ds::radius::LG), bg, egui::Stroke::new(if on { 1.5 } else { 1.0 }, if on { p.accent } else { p.border }), egui::StrokeKind::Inside);
                    ic.paint(ui.painter(), egui::Rect::from_center_size(r.center() - egui::vec2(0.0, 16.0), egui::vec2(26.0, 26.0)), if on { p.accent } else { p.text_secondary });
                    ui.painter().text(r.center() + egui::vec2(0.0, 18.0), egui::Align2::CENTER_CENTER, *title, ds::fonts::semibold(font::SMALL), p.text);
                    if resp.on_hover_text(*blurb).clicked() {
                        np.kind = k;
                    }
                }
            });
            ui.add_space(space::MD);
            ds::hint(ui, kinds[np.kind].2);
            ui.add_space(space::SM);
            match np.kind {
                0 | 1 => {}
                k => {
                    ds::prop_grid(ui, "np params", |ui| {
                        ds::prop_label(ui, if k == 4 { "Cell size" } else { "Size" }, Some("Real-world size in metres, so generators and decals scale right"));
                        ui.horizontal(|ui| {
                            ui.add(egui::DragValue::new(&mut np.size_m[0]).range(0.05..=50.0).speed(0.05).suffix(" m"));
                            ui.label("×");
                            ui.add(egui::DragValue::new(&mut np.size_m[1]).range(0.05..=50.0).speed(0.05).suffix(" m"));
                        });
                        ui.end_row();
                        if k == 3 {
                            ds::prop_label(ui, "Strips", None);
                            ui.add(egui::DragValue::new(&mut np.strips).range(1..=16));
                            ui.end_row();
                        }
                        if k == 4 {
                            ds::prop_label(ui, "Cells", None);
                            ui.add(egui::DragValue::new(&mut np.cells).range(1..=32));
                            ui.end_row();
                        }
                        ds::prop_label(ui, "Texture size", None);
                        egui::ComboBox::from_id_salt("np res").selected_text(format!("{0} × {0}", np.resolution)).show_ui(ui, |ui| {
                            for r in RESOLUTIONS {
                                ui.selectable_value(&mut np.resolution, r, format!("{r} × {r}"));
                            }
                        });
                        ui.end_row();
                    });
                }
            }
            ui.add_space(space::LG);
            ui.horizontal(|ui| {
                let label = match np.kind {
                    0 => "Choose a model…",
                    1 => "Show samples",
                    _ => "Create",
                };
                if ui.add(Btn::primary(label).icon(Icon::New)).clicked() {
                    create = true;
                }
                if ui.add(Btn::ghost("Cancel")).clicked() {
                    np.open = false;
                }
            });
        });
        if dismissed {
            self.ui.new_project.open = false;
        }
        if create {
            self.ui.new_project.open = false;
            let np = &self.ui.new_project;
            let (kind, size_m, strips, cells, res) = (np.kind, np.size_m, np.strips, np.cells, np.resolution);
            match kind {
                0 => self.open_model_dialog(rs),
                1 => self.ui.welcome = true,
                k => {
                    let count = if k == 3 { strips } else { cells };
                    if let Err(e) = self.new_sheet(rs, k - 2, size_m, count, res) {
                        self.notify_error("Couldn't create the project", &e);
                    }
                }
            }
        }
    }

    fn settings_dialog(&mut self, ctx: &egui::Context) {
        let mut close = false;
        let (_, dismissed) = ds::modal(ctx, "settings", "Settings", 460.0, |ui| {
            ds::section(ui, "Appearance");
            let mut theme = self.ui.prefs.theme;
            ui.horizontal(|ui| {
                ds::prop_label(ui, "Theme", None);
                if ds::segmented(ui, &mut theme, &[(ds::ThemeKind::Dark, Some(Icon::Moon), "Dark"), (ds::ThemeKind::Light, Some(Icon::Sun), "Light")]) {
                    self.ui.prefs.theme = theme;
                    ds::apply(ui.ctx(), theme);
                }
            });
            let mut density = self.ui.prefs.density;
            ui.horizontal(|ui| {
                ds::prop_label(ui, "Density", Some("Compact fits more on screen (Blender-like rows); Comfortable has the roomier spacing of earlier versions"));
                if ds::segmented(ui, &mut density, &[(ds::Density::Compact, None, "Compact"), (ds::Density::Comfortable, None, "Comfortable")]) {
                    self.ui.prefs.density = density;
                    ds::set_density(ui.ctx(), density);
                }
            });
            let mut scale = ui.ctx().zoom_factor();
            if ds::slider_row_ex(ui, "Interface size", &mut scale, 0.75..=2.0, ds::Unit::Percent, false, Some("Also Ctrl + and Ctrl -")).changed() {
                ui.ctx().set_zoom_factor(scale);
            }
            ds::section(ui, "Safety");
            ds::slider_row_ex(ui, "Autosave every", &mut self.ui.prefs.autosave_minutes, 0.0..=30.0, ds::Unit::Suffix(" min", 0), false, Some("A recovery copy, offered on the welcome screen after a crash. 0 = off"));
            ds::section(ui, "Start-up");
            ds::toggle(ui, &mut self.ui.prefs.show_welcome, "Show the welcome screen");
            ds::section(ui, "Layouts");
            ui.horizontal(|ui| {
                if ui.add(Btn::secondary("Reset both layouts").small()).clicked() {
                    self.ui.prefs.layout_simple = DockLayout::beginner();
                    self.ui.prefs.layout_advanced = DockLayout::texturing();
                }
                if ui.add(Btn::ghost("Clear thumbnail cache").small()).clicked() {
                    if let Some(d) = self.ui.prefs.thumb_dir() {
                        let _ = std::fs::remove_dir_all(d);
                    }
                    self.ui.thumbs = None;
                }
            });
            ui.add_space(space::LG);
            if ui.add(Btn::primary("Done")).clicked() {
                close = true;
            }
        });
        if close || dismissed {
            self.ui.settings = false;
            let _ = self.ui.prefs.save();
        }
    }
}
