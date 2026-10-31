//! The interface, laid out like a texture painter:
//!
//! ```text
//! ┌ menu ──────────────────────────────────────────────────────────────┐
//! ├ tool bar: [Brush|Eraser]  size  opacity  hardness  spacing  target ┤
//! ├ brush     ┬ viewport (view-mode chips · lighting)  ┬ layer stack   ┤
//! │ material  │                                       │ properties:   │
//! │ + presets │                                       │ [Layer][Mask] │
//! │ channels  │                                       │               │
//! │ texture   │                                       │               │
//! │ set/bake  │                                       │               │
//! ├ status ────────────────────────────────────────────────────────────┤
//! ```

use super::*;
use egui::{Color32, CornerRadius, RichText, Stroke};

const ACCENT: Color32 = Color32::from_rgb(236, 142, 64);
const ACCENT_DIM: Color32 = Color32::from_rgb(92, 58, 32);
const PANEL: Color32 = Color32::from_rgb(30, 31, 34);
const CARD: Color32 = Color32::from_rgb(38, 40, 44);
const CARD_HI: Color32 = Color32::from_rgb(54, 46, 40);
const MUTED: Color32 = Color32::from_rgb(140, 144, 152);
const WARN: Color32 = Color32::from_rgb(240, 160, 90);

pub fn apply_style(ctx: &egui::Context) {
    ctx.set_visuals(egui::Visuals::dark());
    ctx.all_styles_mut(|s| {
        s.spacing.item_spacing = egui::vec2(8.0, 6.0);
        s.spacing.button_padding = egui::vec2(8.0, 4.0);
        s.spacing.slider_width = 130.0;
        s.spacing.interact_size.y = 22.0;
        let v = &mut s.visuals;
        v.panel_fill = PANEL;
        v.window_fill = PANEL;
        v.extreme_bg_color = Color32::from_rgb(20, 21, 23);
        v.selection.bg_fill = ACCENT_DIM;
        v.selection.stroke = Stroke::new(1.0, ACCENT);
        v.hyperlink_color = ACCENT;
        v.window_corner_radius = CornerRadius::same(8);
        for w in [&mut v.widgets.inactive, &mut v.widgets.hovered, &mut v.widgets.active, &mut v.widgets.noninteractive, &mut v.widgets.open] {
            w.corner_radius = CornerRadius::same(5);
        }
        v.widgets.inactive.weak_bg_fill = Color32::from_rgb(48, 50, 55);
        v.widgets.inactive.bg_fill = Color32::from_rgb(48, 50, 55);
        v.widgets.hovered.weak_bg_fill = Color32::from_rgb(62, 64, 70);
        v.widgets.active.weak_bg_fill = ACCENT_DIM;
    });
}

// ------------------------------------------------------------------ widgets

fn srgb32(c: [f32; 3]) -> Color32 {
    let b = c.map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8);
    Color32::from_rgb(b[0], b[1], b[2])
}

/// A material swatch: base colour, with a sheen for metals, a highlight for
/// glossy dielectrics, and an inset mark for negative height.
fn paint_swatch(painter: &egui::Painter, rect: egui::Rect, v: &MaterialValues) {
    let r = CornerRadius::same(4);
    painter.rect_filled(rect, r, srgb32(v.base_color));
    if v.metallic > 0.5 {
        let a = rect.left_top() + egui::vec2(rect.width() * 0.15, 0.0);
        let shine = Color32::from_white_alpha(((1.0 - v.roughness) * 120.0) as u8 + 30);
        painter.with_clip_rect(rect).line_segment([a, a + egui::vec2(rect.width() * 0.5, rect.height())], Stroke::new(rect.width() * 0.18, shine));
    } else if v.roughness < 0.45 {
        painter.circle_filled(rect.left_top() + egui::vec2(rect.width() * 0.3, rect.height() * 0.3), rect.width() * 0.12, Color32::from_white_alpha(90));
    }
    if v.height < -0.1 {
        painter.rect_stroke(rect.shrink(rect.width() * 0.25), r, Stroke::new(1.5, Color32::from_black_alpha(140)), egui::StrokeKind::Inside);
    }
    painter.rect_stroke(rect, r, Stroke::new(1.0, Color32::from_black_alpha(120)), egui::StrokeKind::Inside);
}

fn swatch_button(ui: &mut egui::Ui, v: &MaterialValues, size: f32) -> egui::Response {
    let (rect, resp) = ui.allocate_exact_size(egui::vec2(size, size), egui::Sense::click());
    paint_swatch(ui.painter(), rect, v);
    if resp.hovered() {
        ui.painter().rect_stroke(rect, CornerRadius::same(4), Stroke::new(1.5, ACCENT), egui::StrokeKind::Outside);
    }
    resp
}

fn section(ui: &mut egui::Ui, title: &str) {
    ui.add_space(6.0);
    ui.label(RichText::new(title.to_uppercase()).size(11.0).color(MUTED).strong());
    ui.add_space(2.0);
}

fn card<R>(ui: &mut egui::Ui, fill: Color32, add: impl FnOnce(&mut egui::Ui) -> R) -> R {
    egui::Frame::new()
        .fill(fill)
        .corner_radius(CornerRadius::same(6))
        .inner_margin(egui::Margin::same(8))
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            add(ui)
        })
        .inner
}

fn srgb_edit(ui: &mut egui::Ui, c: &mut [f32; 3]) -> egui::Response {
    let mut b = c.map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8);
    let r = ui.color_edit_button_srgb(&mut b);
    if r.changed() {
        *c = b.map(|v| v as f32 / 255.0);
    }
    r
}

fn tilt_edit(ui: &mut egui::Ui, n: &mut [f32; 2]) {
    ui.horizontal(|ui| {
        ui.add(egui::DragValue::new(&mut n[0]).speed(0.01).range(-0.95..=0.95).prefix("x "));
        ui.add(egui::DragValue::new(&mut n[1]).speed(0.01).range(-0.95..=0.95).prefix("y "));
    });
}

/// Editable material values in a two-column grid, optionally with per-channel toggles.
fn material_grid(ui: &mut egui::Ui, id: &str, v: &mut MaterialValues, enabled: Option<&mut [bool; 5]>) {
    let mut dummy = [true; 5];
    let has_toggles = enabled.is_some();
    let en = enabled.unwrap_or(&mut dummy);
    egui::Grid::new(id).num_columns(2).spacing([10.0, 6.0]).show(ui, |ui| {
        let row = |ui: &mut egui::Ui, on: &mut bool, label: &str| {
            if has_toggles {
                ui.checkbox(on, label);
            } else {
                ui.label(label);
            }
        };
        row(ui, &mut en[0], "Base color");
        srgb_edit(ui, &mut v.base_color);
        ui.end_row();
        row(ui, &mut en[1], "Roughness");
        ui.add(egui::Slider::new(&mut v.roughness, 0.0..=1.0));
        ui.end_row();
        row(ui, &mut en[2], "Metallic");
        ui.add(egui::Slider::new(&mut v.metallic, 0.0..=1.0));
        ui.end_row();
        row(ui, &mut en[3], "Height");
        ui.add(egui::Slider::new(&mut v.height, -1.0..=1.0));
        ui.end_row();
        row(ui, &mut en[4], "Normal tilt");
        tilt_edit(ui, &mut v.normal);
        ui.end_row();
    });
}

fn preset_name(v: &MaterialValues) -> Option<&'static str> {
    material_presets().into_iter().find(|(_, p)| p == v).map(|(n, _)| n)
}

// ------------------------------------------------------------------ frame

impl eframe::App for PigmentApp {
    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        let Some(rs) = frame.wgpu_render_state().cloned() else { return };
        self.ppp = ui.ctx().pixels_per_point();

        let now = Instant::now();
        self.frame_times.push((now - self.last_frame).as_secs_f32());
        self.last_frame = now;
        if self.frame_times.len() > 60 {
            self.frame_times.remove(0);
        }

        let dropped: Vec<PathBuf> = ui.input(|i| i.raw.dropped_files.iter().map(|f| f.path().to_path_buf()).filter(|p| !p.as_os_str().is_empty()).collect());
        if let Some(p) = dropped.first() {
            if p.extension().is_some_and(|e| matches!(e.to_ascii_lowercase().to_str(), Some("hdr" | "exr"))) {
                self.load_env(&rs, p);
            } else {
                self.request(&rs, Self::pending_for_path(p));
            }
        }

        self.anchors.clear();
        self.shortcuts(ui, &rs);
        if std::mem::take(&mut self.dump_requested) {
            self.debug_dump(&rs, &std::env::temp_dir().join("pig").join("dump"));
        }

        let bar = |m: i8| egui::Frame::new().fill(PANEL).inner_margin(egui::Margin::symmetric(m, 6));
        egui::Panel::top("menu").frame(bar(8)).show(ui, |ui| self.menu_bar(ui, &rs));
        egui::Panel::top("toolbar").frame(bar(10).fill(Color32::from_rgb(36, 37, 41))).show(ui, |ui| self.toolbar(ui));
        egui::Panel::bottom("status").frame(bar(10)).show(ui, |ui| self.status_bar(ui));
        egui::Panel::left("material").resizable(true).default_size(268.0).frame(bar(10)).show(ui, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| self.material_panel(ui, &rs));
        });
        egui::Panel::right("layers").resizable(true).default_size(340.0).frame(bar(10)).show(ui, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| self.layers_panel(ui, &rs));
        });
        egui::CentralPanel::default().frame(egui::Frame::NONE).show(ui, |ui| self.viewport_ui(ui, &rs));

        self.dialogs(ui.ctx(), &rs);
        self.tour_update();
        if let Some(v) = self.anchors.get("viewport").copied() {
            self.tour_ui(ui.ctx(), v);
        }

        // Record finished edits (not mid-drag, so a slider drag is one undo step).
        let busy = ui.input(|i| i.pointer.any_down()) || self.stroke.is_some();
        if !busy {
            self.commit_doc_changes();
        }
        ui.ctx().request_repaint();
    }
}

impl PigmentApp {
    fn load_env(&mut self, rs: &RenderState, p: &Path) {
        match Environment::load(&rs.device, &rs.queue, p) {
            Ok(e) => {
                self.set_status(format!("Environment: {}", e.name), false);
                self.env = e;
            }
            Err(e) => self.set_status(format!("Couldn't load environment: {e:#}"), true),
        }
    }

    fn shortcuts(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        use egui::{Key, KeyboardShortcut as K, Modifiers as M};
        let (redo2, redo, undo, save_as, save, open, export) = ui.input_mut(|i| {
            (
                i.consume_shortcut(&K::new(M::COMMAND | M::SHIFT, Key::Z)),
                i.consume_shortcut(&K::new(M::COMMAND, Key::Y)),
                i.consume_shortcut(&K::new(M::COMMAND, Key::Z)),
                i.consume_shortcut(&K::new(M::COMMAND | M::SHIFT, Key::S)),
                i.consume_shortcut(&K::new(M::COMMAND, Key::S)),
                i.consume_shortcut(&K::new(M::COMMAND, Key::O)),
                i.consume_shortcut(&K::new(M::COMMAND | M::SHIFT, Key::E)),
            )
        });
        if redo || redo2 {
            self.undo(rs, true);
        } else if undo {
            self.undo(rs, false);
        }
        if save_as {
            self.save(rs, true);
        } else if save {
            self.save(rs, false);
        }
        if open {
            self.open_dialog(rs);
        }
        if export {
            self.show_export = true;
        }
        if ui.ctx().egui_wants_keyboard_input() {
            return;
        }
        ui.input(|i| {
            if i.key_pressed(Key::OpenBracket) {
                self.brush.size = (self.brush.size / 1.15).max(2.0);
            }
            if i.key_pressed(Key::CloseBracket) {
                self.brush.size = (self.brush.size * 1.15).min(800.0);
            }
            if i.key_pressed(Key::B) {
                self.brush.erase = false;
            }
            if i.key_pressed(Key::E) {
                self.brush.erase = !self.brush.erase;
            }
            if i.key_pressed(Key::X) {
                self.brush.mask_white = !self.brush.mask_white;
            }
            if i.key_pressed(Key::M) {
                self.view.mode = if self.view.mode == ViewMode::Material { ViewMode::BaseColor } else { ViewMode::Material };
            }
            if i.key_pressed(Key::F) {
                let (c, r) = self.mesh.bounding_sphere();
                self.camera.frame(c, r);
            }
            if i.key_pressed(Key::F12) {
                self.dump_requested = true;
            }
        });
    }

    fn open_dialog(&mut self, rs: &RenderState) {
        if let Some(p) = rfd::FileDialog::new().set_title("Open project folder (.pigment)").pick_folder() {
            self.request(rs, Pending::OpenProject(p));
        }
    }

    // ------------------------------------------------------------ bars

    fn menu_bar(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        egui::MenuBar::new().ui(ui, |ui| {
            ui.label(RichText::new("Pigment").strong().color(ACCENT));
            ui.add_space(6.0);
            let file = ui.menu_button("File", |ui| {
                if ui.button("New project from mesh…").clicked() {
                    if let Some(p) = rfd::FileDialog::new().add_filter("Meshes", &["obj", "gltf", "glb"]).pick_file() {
                        self.request(rs, Pending::NewFromMesh(p));
                    }
                }
                if ui.button("Open the demo crate").clicked() {
                    self.request(rs, Pending::Demo);
                }
                if ui.button("New project: test torus").clicked() {
                    self.request(rs, Pending::NewTorus);
                }
                ui.separator();
                if ui.add(egui::Button::new("Open project…").shortcut_text("Ctrl+O")).clicked() {
                    self.open_dialog(rs);
                }
                if ui.add(egui::Button::new("Save").shortcut_text("Ctrl+S")).clicked() {
                    self.save(rs, false);
                }
                if ui.add(egui::Button::new("Save as…").shortcut_text("Ctrl+Shift+S")).clicked() {
                    self.save(rs, true);
                }
                ui.separator();
                if ui.add(egui::Button::new("Export textures…").shortcut_text("Ctrl+Shift+E")).clicked() {
                    self.show_export = true;
                }
            });
            self.anchors.insert("file_menu", file.response.rect);
            let edit = ui.menu_button("Edit", |ui| {
                let ul = self.history.undo_label().map(|s| format!("Undo: {s}")).unwrap_or_else(|| "Undo".into());
                if ui.add_enabled(self.history.can_undo() || self.doc != self.committed, egui::Button::new(ul).shortcut_text("Ctrl+Z")).clicked() {
                    self.undo(rs, false);
                }
                let rl = self.history.redo_label().map(|s| format!("Redo: {s}")).unwrap_or_else(|| "Redo".into());
                if ui.add_enabled(self.history.can_redo(), egui::Button::new(rl).shortcut_text("Ctrl+Y")).clicked() {
                    self.undo(rs, true);
                }
                ui.separator();
                ui.menu_button("History", |ui| {
                    let (labels, applied) = self.history.history();
                    if labels.is_empty() {
                        ui.label(RichText::new("Nothing yet").color(MUTED));
                    }
                    for (i, l) in labels.iter().enumerate().rev().take(30) {
                        let t = RichText::new(*l);
                        ui.label(if i < applied { t } else { t.color(Color32::DARK_GRAY).italics() });
                    }
                });
            });
            self.anchors.insert("edit_menu", edit.response.rect);
            ui.menu_button("View", |ui| {
                if ui.add(egui::Button::new("Frame model").shortcut_text("F")).clicked() {
                    let (c, r) = self.mesh.bounding_sphere();
                    self.camera.frame(c, r);
                }
                ui.separator();
                for m in ViewMode::ALL {
                    ui.radio_value(&mut self.view.mode, m, m.label());
                }
            });
            ui.menu_button("Help", |ui| {
                if ui.button(RichText::new("Quick start guide").strong()).clicked() {
                    self.tour_start(true);
                    ui.close();
                }
                ui.separator();
                ui.label(RichText::new("Controls").strong());
                for (k, v) in [
                    ("Left-drag", "paint"),
                    ("Right-drag / Alt+left", "orbit"),
                    ("Middle-drag", "pan"),
                    ("Wheel", "zoom"),
                    ("[  ]", "brush size"),
                    ("B / E", "brush / eraser"),
                    ("X", "swap mask colour"),
                    ("F", "frame model"),
                    ("M", "material / base colour view"),
                ] {
                    ui.horizontal(|ui| {
                        ui.label(RichText::new(k).monospace().color(ACCENT));
                        ui.label(v);
                    });
                }
                ui.separator();
                ui.label("Fill layers are shaped by their mask. Paint on a fill\nlayer and it gets a black mask you paint white into.");
            });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let name = self.project_dir.as_ref().and_then(|d| d.file_name()).map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "Untitled project".into());
                ui.label(RichText::new(format!("{name}{}", if self.modified { "  •  unsaved" } else { "" })).color(MUTED));
            });
        });
    }

    fn toolbar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let tool = |ui: &mut egui::Ui, on: bool, label: &str, tip: &str| {
                let b = egui::Button::new(RichText::new(label).strong()).selected(on).min_size(egui::vec2(70.0, 26.0));
                ui.add(b).on_hover_text(tip).clicked()
            };
            if tool(ui, !self.brush.erase, "Brush", "Paint (B)") {
                self.brush.erase = false;
            }
            if tool(ui, self.brush.erase, "Eraser", "Erase (E)") {
                self.brush.erase = true;
            }
            ui.separator();
            let slider = |ui: &mut egui::Ui, label: &str, v: &mut f32, r: std::ops::RangeInclusive<f32>, log: bool, pct: bool| {
                ui.label(RichText::new(label).color(MUTED));
                let mut s = egui::Slider::new(v, r).logarithmic(log);
                if pct {
                    s = s.custom_formatter(|v, _| format!("{:.0}%", v * 100.0));
                }
                ui.add_sized([150.0, 20.0], s);
                ui.add_space(6.0);
            };
            slider(ui, "Size", &mut self.brush.size, 2.0..=800.0, true, false);
            slider(ui, "Opacity", &mut self.brush.opacity, 0.0..=1.0, false, true);
            slider(ui, "Hardness", &mut self.brush.hardness, 0.0..=1.0, false, true);
            slider(ui, "Spacing", &mut self.brush.spacing, 0.02..=1.0, false, true);

            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let layer = self.selected.and_then(|id| self.doc.layer(id)).map(|l| (l.name.clone(), l.is_paint(), l.mask.is_some()));
                match (layer, self.paint_target()) {
                    (Some((name, _, _)), Ok(Target::Mask(_))) => {
                        ui.selectable_value(&mut self.brush.mask_white, false, "Black: hide").on_hover_text("X swaps");
                        ui.selectable_value(&mut self.brush.mask_white, true, "White: reveal");
                        ui.label(RichText::new(format!("Painting the mask of {name}")).color(ACCENT).strong());
                    }
                    (Some((name, _, _)), Ok(Target::Layer(_))) => {
                        ui.label(RichText::new(format!("Painting on {name}")).color(ACCENT).strong());
                    }
                    (Some((name, false, false)), _) => {
                        ui.label(RichText::new(format!("Painting {name} gives it a mask")).color(MUTED));
                    }
                    (_, Err(e)) => {
                        ui.label(RichText::new(e).color(WARN));
                    }
                    _ => {}
                }
            });
        });
    }

    fn status_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if let Some((msg, err)) = &self.status {
                ui.label(RichText::new(msg).color(if *err { WARN } else { Color32::LIGHT_GRAY }));
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let avg = self.frame_times.iter().sum::<f32>() / self.frame_times.len().max(1) as f32;
                let stats = format!(
                    "{:.0} fps   ·   {} tris   ·   {res}² × {} layers, {:.0} MB",
                    1.0 / avg.max(1e-6),
                    format_count(self.mesh.triangle_count()),
                    self.doc.layers.len(),
                    self.ts.vram_bytes() as f64 / 1048576.0,
                    res = self.ts.res,
                );
                ui.label(RichText::new(stats).color(MUTED).size(12.0));
            });
        });
    }

    // ------------------------------------------------------------ left: brush material

    fn material_panel(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let painting_mask = matches!(self.paint_target(), Ok(Target::Mask(_)));
        section(ui, "Brush material");
        if painting_mask {
            card(ui, CARD, |ui| {
                ui.label(RichText::new("You're painting a mask.").strong());
                ui.label(RichText::new("White reveals the layer, black hides it (X swaps). Click the layer's Layer tab to paint material again.").color(MUTED));
                ui.horizontal(|ui| {
                    ui.selectable_value(&mut self.brush.mask_white, true, "White: reveal");
                    ui.selectable_value(&mut self.brush.mask_white, false, "Black: hide");
                });
            });
        }
        ui.add_enabled_ui(!painting_mask, |ui| {
            card(ui, CARD, |ui| {
                ui.horizontal(|ui| {
                    let (rect, _) = ui.allocate_exact_size(egui::vec2(54.0, 54.0), egui::Sense::hover());
                    paint_swatch(ui.painter(), rect, &self.brush.values);
                    ui.vertical(|ui| {
                        let name = preset_name(&self.brush.values).unwrap_or("Custom");
                        ui.label(RichText::new(name).strong().size(15.0));
                        let v = &self.brush.values;
                        ui.label(RichText::new(format!("rough {:.2} · metal {:.2}", v.roughness, v.metallic)).color(MUTED).size(12.0));
                        if v.height.abs() > 0.01 && self.brush.channels[3] {
                            ui.label(RichText::new(format!("height {:+.2}", v.height)).color(MUTED).size(12.0));
                        }
                    });
                });
            });
            section(ui, "Presets");
            let presets = material_presets();
            let grid = egui::Grid::new("presets").num_columns(2).spacing([6.0, 6.0]).show(ui, |ui| {
                for (k, (name, v)) in presets.iter().enumerate() {
                    let r = ui
                        .horizontal(|ui| {
                            let r = swatch_button(ui, v, 22.0);
                            let l = ui.add(egui::Label::new(RichText::new(*name).size(12.5)).sense(egui::Sense::click()).selectable(false));
                            r.union(l)
                        })
                        .inner;
                    if r.clicked() {
                        self.brush.values = v.clone();
                        self.brush.channels = [true, true, true, v.height.abs() > 0.01, false];
                        self.brush.erase = false;
                    }
                    if k % 2 == 1 {
                        ui.end_row();
                    }
                }
            });
            self.anchors.insert("presets", grid.response.rect);
            section(ui, "Channels this brush paints");
            material_grid(ui, "brush values", &mut self.brush.values, Some(&mut self.brush.channels));
        });

        ui.add_space(8.0);
        egui::CollapsingHeader::new(RichText::new("TEXTURE SET & BAKING").size(11.0).color(MUTED).strong()).default_open(false).show(ui, |ui| {
            let mut res = self.doc.resolution;
            ui.horizontal(|ui| {
                ui.label("Size");
                egui::ComboBox::from_id_salt("res").selected_text(format!("{res} × {res}")).show_ui(ui, |ui| {
                    for r in RESOLUTIONS {
                        ui.selectable_value(&mut res, r, format!("{r} × {r}"));
                    }
                });
            });
            if res != self.doc.resolution {
                self.change_resolution(rs, res);
            }
            ui.label(RichText::new("Resamples all layers; clears undo.").size(11.0).color(MUTED));
            ui.add_space(4.0);
            egui::Grid::new("bake").num_columns(2).show(ui, |ui| {
                ui.label("AO quality");
                egui::ComboBox::from_id_salt("ao").selected_text(format!("{} rays", self.doc.bake.ao_samples)).show_ui(ui, |ui| {
                    for n in [32, 64, 128, 256, 512] {
                        ui.selectable_value(&mut self.doc.bake.ao_samples, n, format!("{n} rays"));
                    }
                });
                ui.end_row();
                ui.label("Edge width");
                ui.add(egui::Slider::new(&mut self.doc.bake.curvature_radius, 0.005..=0.2).logarithmic(true));
                ui.end_row();
                ui.label("Edge strength");
                ui.add(egui::Slider::new(&mut self.doc.bake.curvature_strength, 0.1..=4.0));
                ui.end_row();
            });
            if ui.button("Re-bake AO + curvature").clicked() {
                self.bake(rs);
            }
            ui.label(RichText::new("Generators (edge wear, dirt) read these maps. Inspect them with the AO / Curvature chips on the viewport.").size(11.0).color(MUTED));
        });
    }

    // ------------------------------------------------------------ right: layers + properties

    fn layers_panel(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        ui.horizontal(|ui| {
            section(ui, "Layers");
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.menu_button(RichText::new("+ Add layer").strong(), |ui| {
                    if ui.button("Paint layer").on_hover_text("Paint material directly with the brush").clicked() {
                        let l = self.doc.new_paint_layer(&format!("Paint {}", self.doc.layers.len() + 1));
                        self.insert_layer(l);
                        ui.close();
                    }
                    if ui.button("Fill layer").on_hover_text("A flat material; paint on it to mask where it shows").clicked() {
                        let l = self.doc.new_fill_layer(&format!("Fill {}", self.doc.layers.len() + 1));
                        self.insert_layer(l);
                        ui.close();
                    }
                    ui.separator();
                    ui.label(RichText::new("Smart layers").size(11.0).color(MUTED));
                    if ui.button("Edge wear: bare metal on edges").clicked() {
                        self.add_smart(rs, "Edge wear", "Steel", GeneratorKind::EdgeWear, 0.55);
                        ui.close();
                    }
                    if ui.button("Dirt: grime in crevices").clicked() {
                        self.add_smart(rs, "Dirt", "Grime", GeneratorKind::Dirt, 0.5);
                        ui.close();
                    }
                    if ui.button("Rust: in crevices").clicked() {
                        self.add_smart(rs, "Rust", "Rust", GeneratorKind::Dirt, 0.4);
                        ui.close();
                    }
                });
            });
        });

        // top of the stack first
        let n = self.doc.layers.len();
        let mut select: Option<(LayerId, bool)> = None;
        for i in (0..n).rev() {
            let selected = self.selected == Some(self.doc.layers[i].id);
            let paint_mask = self.paint_mask;
            let l = &mut self.doc.layers[i];
            let id = l.id;
            let row = egui::Frame::new()
                .fill(if selected { CARD_HI } else { CARD })
                .stroke(if selected { Stroke::new(1.0, ACCENT) } else { Stroke::NONE })
                .corner_radius(CornerRadius::same(6))
                .inner_margin(egui::Margin::symmetric(6, 5))
                .show(ui, |ui| {
                    ui.set_width(ui.available_width());
                    ui.horizontal(|ui| {
                        // visibility
                        let (r, resp) = ui.allocate_exact_size(egui::vec2(16.0, 16.0), egui::Sense::click());
                        if l.visible {
                            ui.painter().circle_filled(r.center(), 5.0, ACCENT);
                        } else {
                            ui.painter().circle_stroke(r.center(), 5.0, Stroke::new(1.5, MUTED));
                        }
                        if resp.on_hover_text(if l.visible { "Hide" } else { "Show" }).clicked() {
                            l.visible = !l.visible;
                        }
                        // thumbnail
                        let (r, resp) = ui.allocate_exact_size(egui::vec2(30.0, 30.0), egui::Sense::click());
                        match &l.kind {
                            LayerKind::Fill { values } => paint_swatch(ui.painter(), r, values),
                            LayerKind::Paint { .. } => {
                                let p = ui.painter();
                                p.rect_filled(r, CornerRadius::same(4), Color32::from_gray(70));
                                for k in 0..3u8 {
                                    let y = r.top() + 8.0 + k as f32 * 7.0;
                                    p.line_segment([egui::pos2(r.left() + 6.0, y + 4.0), egui::pos2(r.right() - 6.0, y - 2.0)], Stroke::new(2.0, Color32::from_gray(150 + k * 30)));
                                }
                            }
                        }
                        if resp.clicked() {
                            select = Some((id, false));
                        }
                        // name + what it is
                        let sub = match (&l.kind, &l.mask) {
                            (LayerKind::Paint { .. }, None) => "Paint".to_string(),
                            (LayerKind::Paint { .. }, Some(_)) => "Paint · masked".to_string(),
                            (LayerKind::Fill { .. }, Some(m)) => match &m.generator {
                                Some(g) => format!("Fill · {} mask", g.kind.label().to_lowercase()),
                                None => "Fill · painted mask".to_string(),
                            },
                            (LayerKind::Fill { .. }, None) => "Fill · everywhere".to_string(),
                        };
                        let resp = ui
                            .vertical(|ui| {
                                let name = RichText::new(&l.name).strong().color(if l.visible { Color32::WHITE } else { MUTED });
                                ui.add(egui::Label::new(name).selectable(false));
                                ui.add(egui::Label::new(RichText::new(sub).size(11.0).color(MUTED)).selectable(false));
                            })
                            .response
                            .interact(egui::Sense::click());
                        if resp.clicked() {
                            select = Some((id, false));
                        }
                        // mask thumbnail
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if let Some(m) = &l.mask {
                                let (r, resp) = ui.allocate_exact_size(egui::vec2(26.0, 26.0), egui::Sense::click());
                                let p = ui.painter();
                                p.rect_filled(r, CornerRadius::same(3), Color32::from_gray(20));
                                p.rect_filled(egui::Rect::from_min_max(r.center_top(), r.right_bottom()), CornerRadius::same(3), Color32::from_gray(225));
                                if m.generator.is_some() {
                                    p.circle_filled(r.center(), 4.0, ACCENT);
                                }
                                let active = selected && paint_mask;
                                p.rect_stroke(r, CornerRadius::same(3), Stroke::new(if active { 2.0 } else { 1.0 }, if active { ACCENT } else { MUTED }), egui::StrokeKind::Outside);
                                if resp.on_hover_text("Select the mask to paint on it").clicked() {
                                    select = Some((id, true));
                                }
                            }
                            ui.label(RichText::new(format!("{:.0}%", l.opacity * 100.0)).size(11.0).color(MUTED));
                        });
                    });
                });
            if self.doc.layers[i].mask.as_ref().and_then(|m| m.generator.as_ref()).is_some_and(|g| g.kind == GeneratorKind::EdgeWear) {
                self.anchors.entry("edge_wear_row").or_insert(row.response.rect);
            }
            if select.is_none() && row.response.interact(egui::Sense::click()).clicked() {
                select = Some((id, false));
            }
            ui.add_space(2.0);
        }
        if let Some((id, mask)) = select {
            self.selected = Some(id);
            let (has_mask, is_paint) = self.doc.layer(id).map(|l| (l.mask.is_some(), l.is_paint())).unwrap_or((false, true));
            // fill layers are painted through their mask
            self.paint_mask = (mask || !is_paint) && has_mask;
        }

        ui.horizontal(|ui| {
            let sel = self.selected.and_then(|id| self.doc.index_of(id));
            if ui.add_enabled(sel.is_some_and(|i| i + 1 < self.doc.layers.len()), egui::Button::new("Up")).clicked() {
                let i = sel.unwrap();
                self.doc.layers.swap(i, i + 1);
            }
            if ui.add_enabled(sel.is_some_and(|i| i > 0), egui::Button::new("Down")).clicked() {
                let i = sel.unwrap();
                self.doc.layers.swap(i, i - 1);
            }
            if ui.add_enabled(sel.is_some(), egui::Button::new("Duplicate")).clicked() {
                self.duplicate_selected(rs);
            }
            if ui.add_enabled(sel.is_some(), egui::Button::new("Delete")).clicked() {
                if let Some(i) = sel {
                    self.doc.layers.remove(i);
                    self.selected = self.doc.layers.get(i.min(self.doc.layers.len().saturating_sub(1))).map(|l| l.id);
                    self.paint_mask = false;
                }
            }
        });

        ui.add_space(8.0);
        self.properties(ui, rs);
    }

    fn add_smart(&mut self, rs: &RenderState, name: &str, material: &str, kind: GeneratorKind, amount: f32) {
        let mut l = self.doc.new_fill_layer(name);
        let values = material_preset(material);
        l.channels.metallic.enabled = values.metallic > 0.0 || material == "Steel";
        l.channels.height.enabled = values.height.abs() > 0.01;
        l.channels.normal.enabled = false;
        l.kind = LayerKind::Fill { values };
        let res = self.doc.mint();
        self.ts.new_mask(&rs.device, &rs.queue, res, true);
        let mut g = Generator::new(kind);
        g.amount = amount;
        if kind == GeneratorKind::EdgeWear {
            g.noise_scale = 20.0;
            g.noise_amount = 0.8;
            g.softness = 0.05;
        }
        l.mask = Some(Mask { res, generator: Some(g), invert: false, enabled: true });
        self.insert_layer(l);
    }

    fn insert_layer(&mut self, l: Layer) {
        let at = self.selected.and_then(|id| self.doc.index_of(id)).map(|i| i + 1).unwrap_or(self.doc.layers.len());
        self.selected = Some(l.id);
        self.paint_mask = false;
        self.doc.layers.insert(at, l);
    }

    fn duplicate_selected(&mut self, rs: &RenderState) {
        let Some(i) = self.selected.and_then(|id| self.doc.index_of(id)) else { return };
        let mut l = self.doc.layers[i].clone();
        l.id = self.doc.mint();
        l.name = format!("{} copy", l.name);
        if let LayerKind::Paint { res } = &mut l.kind {
            let new = self.doc.mint();
            self.ts.duplicate_layer(&rs.device, &rs.queue, *res, new);
            *res = new;
        }
        if let Some(m) = &mut l.mask {
            let new = self.doc.mint();
            self.ts.duplicate_mask(&rs.device, &rs.queue, m.res, new);
            m.res = new;
        }
        self.selected = Some(l.id);
        self.doc.layers.insert(i + 1, l);
    }

    fn properties(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let Some(i) = self.selected.and_then(|id| self.doc.index_of(id)) else {
            ui.label(RichText::new("Select a layer to edit it.").color(MUTED));
            return;
        };
        let id = self.doc.layers[i].id;
        section(ui, "Properties");

        let mut name = match &self.renaming {
            Some((rid, n)) if *rid == id => n.clone(),
            _ => self.doc.layers[i].name.clone(),
        };
        let r = ui.add(egui::TextEdit::singleline(&mut name).desired_width(f32::INFINITY).font(egui::TextStyle::Heading));
        if r.changed() {
            self.renaming = Some((id, name.clone()));
        }
        if r.lost_focus() {
            if let Some((_, n)) = self.renaming.take() {
                if !n.trim().is_empty() {
                    self.doc.layers[i].name = n.trim().to_string();
                }
            }
        }

        // Layer / Mask tabs. The active tab is also what the brush paints.
        let has_mask = self.doc.layers[i].mask.is_some();
        ui.horizontal(|ui| {
            if ui.add(egui::Button::new("Layer").selected(!self.paint_mask).min_size(egui::vec2(90.0, 24.0))).clicked() {
                self.paint_mask = false;
            }
            let label = if has_mask { "Mask" } else { "Mask (none)" };
            if ui.add(egui::Button::new(label).selected(self.paint_mask).min_size(egui::vec2(90.0, 24.0))).clicked() {
                self.paint_mask = true;
            }
        });
        ui.add_space(4.0);
        if self.paint_mask {
            self.mask_tab(ui, rs, i);
        } else {
            self.layer_tab(ui, i);
        }
    }

    fn layer_tab(&mut self, ui: &mut egui::Ui, i: usize) {
        let l = &mut self.doc.layers[i];
        card(ui, CARD, |ui| {
            ui.horizontal(|ui| {
                ui.label("Opacity");
                ui.add(egui::Slider::new(&mut l.opacity, 0.0..=1.0).custom_formatter(|v, _| format!("{:.0}%", v * 100.0)));
            });
        });
        match &mut l.kind {
            LayerKind::Fill { values } => {
                section(ui, "Fill material");
                card(ui, CARD, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        for (name, v) in material_presets() {
                            if swatch_button(ui, &v, 20.0).on_hover_text(name).clicked() {
                                *values = v;
                            }
                        }
                    });
                    ui.add_space(4.0);
                    material_grid(ui, "fill values", values, None);
                });
            }
            LayerKind::Paint { .. } => {
                card(ui, CARD, |ui| {
                    ui.label(RichText::new("Paint layer").strong());
                    ui.label(RichText::new("Holds whatever you paint. Choose the brush material on the left.").color(MUTED));
                });
            }
        }
        section(ui, "Channels");
        card(ui, CARD, |ui| {
            ui.label(RichText::new("Which channels this layer affects and how it blends onto the layers below.").size(11.5).color(MUTED));
            egui::Grid::new("channels").num_columns(3).spacing([8.0, 6.0]).show(ui, |ui| {
                for c in Channel::ALL {
                    let s = l.channels.get_mut(c);
                    ui.checkbox(&mut s.enabled, c.label());
                    egui::ComboBox::from_id_salt(("blend", c.index())).width(120.0).selected_text(s.blend.label()).show_ui(ui, |ui| {
                        for m in c.blend_modes() {
                            ui.selectable_value(&mut s.blend, *m, m.label());
                        }
                    });
                    ui.add(egui::DragValue::new(&mut s.opacity).range(0.0..=1.0).speed(0.01).custom_formatter(|v, _| format!("{:.0}%", v * 100.0)));
                    ui.end_row();
                }
            });
        });
    }

    fn mask_tab(&mut self, ui: &mut egui::Ui, rs: &RenderState, i: usize) {
        let mut add: Option<(bool, Option<GeneratorKind>)> = None;
        let mut removed = false;
        let baked = self.ts.baked;
        let l = &mut self.doc.layers[i];
        match &mut l.mask {
            None => {
                card(ui, CARD, |ui| {
                    ui.label(RichText::new("No mask: the layer shows everywhere.").strong());
                    ui.label(RichText::new("A mask decides where this layer appears. Paint it by hand, or let a generator find edges or crevices.").color(MUTED));
                    ui.add_space(4.0);
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("Black mask (paint to reveal)").clicked() {
                            add = Some((false, None));
                        }
                        if ui.button("White mask (paint to hide)").clicked() {
                            add = Some((true, None));
                        }
                    });
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("Edge wear generator").clicked() {
                            add = Some((true, Some(GeneratorKind::EdgeWear)));
                        }
                        if ui.button("Dirt generator").clicked() {
                            add = Some((true, Some(GeneratorKind::Dirt)));
                        }
                    });
                });
            }
            Some(m) => {
                card(ui, CARD, |ui| {
                    ui.horizontal(|ui| {
                        ui.checkbox(&mut m.enabled, "Enabled");
                        ui.checkbox(&mut m.invert, "Invert");
                    });
                    ui.label(RichText::new("The brush now paints this mask: white reveals, black hides (X swaps).").size(11.5).color(MUTED));
                });
                section(ui, "Generator");
                let top = ui.cursor().min;
                card(ui, CARD, |ui| {
                    let mut kind = m.generator.as_ref().map(|g| g.kind);
                    ui.horizontal(|ui| {
                        ui.selectable_value(&mut kind, None, "None");
                        ui.selectable_value(&mut kind, Some(GeneratorKind::EdgeWear), "Edge wear");
                        ui.selectable_value(&mut kind, Some(GeneratorKind::Dirt), "Dirt");
                    });
                    if kind != m.generator.as_ref().map(|g| g.kind) {
                        m.generator = kind.map(Generator::new);
                    }
                    match &mut m.generator {
                        None => {
                            ui.label(RichText::new("Hand-painted mask only.").color(MUTED));
                        }
                        Some(g) => {
                            if !baked {
                                ui.colored_label(WARN, "Bake mesh maps first (Texture set & baking, left).");
                            }
                            let what = match g.kind {
                                GeneratorKind::EdgeWear => "Finds convex edges (curvature), breaks them up with noise, avoids occluded areas.",
                                GeneratorKind::Dirt => "Finds crevices and occluded areas (AO + concave curvature), broken up with noise.",
                            };
                            ui.label(RichText::new(what).size(11.5).color(MUTED));
                            egui::Grid::new("generator").num_columns(2).spacing([10.0, 6.0]).show(ui, |ui| {
                                ui.label("Amount");
                                ui.add(egui::Slider::new(&mut g.amount, 0.0..=1.0));
                                ui.end_row();
                                ui.label("Sharpness");
                                let mut sharp = 1.0 - g.softness / 0.5;
                                if ui.add(egui::Slider::new(&mut sharp, 0.0..=1.0)).changed() {
                                    g.softness = (1.0 - sharp) * 0.5;
                                }
                                ui.end_row();
                                ui.label("Breakup scale");
                                ui.add(egui::Slider::new(&mut g.noise_scale, 0.5..=64.0).logarithmic(true));
                                ui.end_row();
                                ui.label("Breakup amount");
                                ui.add(egui::Slider::new(&mut g.noise_amount, 0.0..=1.5));
                                ui.end_row();
                                ui.label("Seed");
                                ui.horizontal(|ui| {
                                    ui.add(egui::DragValue::new(&mut g.seed).range(0..=999));
                                    if ui.small_button("New").clicked() {
                                        g.seed = (g.seed * 7919 + 17) % 1000;
                                    }
                                });
                                ui.end_row();
                            });
                            ui.label(RichText::new("Paint black on the mask to protect areas from the generator.").size(11.5).color(MUTED));
                        }
                    }
                });
                let gen_rect = egui::Rect::from_min_max(top, egui::pos2(ui.max_rect().right(), ui.cursor().min.y));
                if gen_rect.height() > 10.0 {
                    self.anchors.insert("generator", gen_rect);
                }
                ui.add_space(4.0);
                if ui.button("Remove mask").clicked() {
                    removed = true;
                }
            }
        }
        if removed {
            self.doc.layers[i].mask = None;
            self.paint_mask = false;
        }
        if let Some((white, generator)) = add {
            let res = self.doc.mint();
            self.ts.new_mask(&rs.device, &rs.queue, res, white);
            self.doc.layers[i].mask = Some(Mask { res, generator: generator.map(Generator::new), invert: false, enabled: true });
            self.brush.mask_white = !white;
        }
    }

    // ------------------------------------------------------------ viewport

    fn viewport_ui(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let rect = ui.available_rect_before_wrap();
        let response = ui.allocate_rect(rect, egui::Sense::click_and_drag());
        self.anchors.insert("viewport", rect);
        let ppp = self.ppp;
        let viewport_px = Vec2::new((rect.width() * ppp).round(), (rect.height() * ppp).round());
        let to_px = |p: egui::Pos2| Vec2::new((p.x - rect.min.x) * ppp, (p.y - rect.min.y) * ppp);

        let (alt, delta, scroll, pinch, pressed, down, released, latest) = ui.input(|i| {
            (
                i.modifiers.alt,
                i.pointer.delta(),
                i.smooth_scroll_delta(),
                i.zoom_delta(),
                i.pointer.primary_pressed(),
                i.pointer.primary_down(),
                i.pointer.primary_released(),
                i.pointer.latest_pos(),
            )
        });
        self.hover = response.hover_pos();
        let d = Vec2::new(delta.x, delta.y);

        // painting
        if pressed && response.hovered() && !alt && self.stroke.is_none() {
            if let Some(p) = latest {
                self.begin_stroke(rs, to_px(p), viewport_px);
            }
        } else if (down || released) && self.stroke.is_some() {
            // also on release: the last moves and the release can arrive in one frame
            if let Some(p) = latest {
                let spacing = (self.brush.size * ppp * self.brush.spacing).max(1.0);
                let pts = self.stroke.as_mut().map(|s| s.sampler.move_to(to_px(p), spacing)).unwrap_or_default();
                self.apply_stamps(rs, pts);
            }
        }
        if (released || !down) && self.stroke.is_some() {
            self.end_stroke(rs);
        }

        // camera: Alt+LMB / RMB orbit, MMB pan, wheel / Alt+RMB zoom
        if alt && response.dragged_by(egui::PointerButton::Primary) {
            self.camera.orbit(d);
        }
        if response.dragged_by(egui::PointerButton::Middle) {
            self.camera.pan(d * ppp, viewport_px.y);
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

        self.ensure_composited(rs);
        let size = [viewport_px.x as u32, viewport_px.y as u32];
        if let Some(tex) = self.viewport.render(rs, size, &self.camera, &self.view, self.mesh_gpu.as_ref(), &self.env, &self.ts) {
            let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
            ui.painter().image(tex, rect, uv, Color32::WHITE);
        }

        // brush cursor: ring = size, inner ring = hardness, dot = what you paint
        if let Some(h) = self.hover.filter(|_| !alt) {
            let r = self.brush.size * 0.5;
            let on_mask = matches!(self.paint_target(), Ok(Target::Mask(_))) || self.selected.and_then(|id| self.doc.layer(id)).is_some_and(|l| !l.is_paint());
            let col = if self.brush.erase { Color32::from_rgb(120, 190, 255) } else { Color32::from_white_alpha(230) };
            let p = ui.painter();
            p.circle_stroke(h, r + 1.0, Stroke::new(1.0, Color32::from_black_alpha(160)));
            p.circle_stroke(h, r, Stroke::new(1.5, col));
            p.circle_stroke(h, r * self.brush.hardness.max(0.02), Stroke::new(1.0, Color32::from_white_alpha(70)));
            let dot = if on_mask {
                if self.brush.mask_white != self.brush.erase { Color32::WHITE } else { Color32::BLACK }
            } else {
                srgb32(self.brush.values.base_color)
            };
            let dp = h + egui::vec2(r * 0.72, -r * 0.72);
            p.circle_filled(dp, 5.5, dot);
            p.circle_stroke(dp, 5.5, Stroke::new(1.0, Color32::from_gray(120)));
            ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
        }

        self.viewport_overlays(ui, rect, rs);
    }

    fn viewport_overlays(&mut self, ui: &mut egui::Ui, rect: egui::Rect, rs: &RenderState) {
        let glass = egui::Frame::new().fill(Color32::from_black_alpha(160)).corner_radius(CornerRadius::same(6)).inner_margin(egui::Margin::same(4));
        // view-mode chips, top left
        let chips = egui::Rect::from_min_size(rect.left_top() + egui::vec2(10.0, 10.0), egui::vec2(rect.width() - 220.0, 30.0));
        ui.scope_builder(egui::UiBuilder::new().max_rect(chips), |ui| {
            glass.show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.spacing_mut().item_spacing.x = 2.0;
                    for (m, short) in [
                        (ViewMode::Material, "Material"),
                        (ViewMode::BaseColor, "Color"),
                        (ViewMode::Roughness, "Rough"),
                        (ViewMode::Metallic, "Metal"),
                        (ViewMode::Height, "Height"),
                        (ViewMode::Normal, "Normal"),
                        (ViewMode::Ao, "AO"),
                        (ViewMode::Curvature, "Curvature"),
                        (ViewMode::UvChecker, "UVs"),
                    ] {
                        ui.selectable_value(&mut self.view.mode, m, RichText::new(short).size(12.0)).on_hover_text(m.label());
                    }
                });
            });
        });
        // lighting, top right
        let light = egui::Rect::from_min_size(egui::pos2(rect.right() - 200.0, rect.top() + 10.0), egui::vec2(190.0, 30.0));
        ui.scope_builder(egui::UiBuilder::new().max_rect(light).layout(egui::Layout::right_to_left(egui::Align::Min)), |ui| {
            glass.show(ui, |ui| {
                ui.menu_button(RichText::new(format!("Lighting: {}", self.env.name)).size(12.0), |ui| {
                    ui.set_min_width(250.0);
                    egui::Grid::new("light").num_columns(2).show(ui, |ui| {
                        ui.label("Exposure");
                        ui.add(egui::Slider::new(&mut self.view.exposure, -4.0..=4.0).suffix(" EV"));
                        ui.end_row();
                        ui.label("Rotate");
                        ui.add(egui::Slider::new(&mut self.view.env_rotation, -std::f32::consts::PI..=std::f32::consts::PI));
                        ui.end_row();
                    });
                    ui.checkbox(&mut self.view.show_env, "Show environment as background");
                    ui.separator();
                    if ui.button("Load HDRI (.hdr / .exr)…").clicked() {
                        if let Some(p) = rfd::FileDialog::new().add_filter("HDR images", &["hdr", "exr"]).pick_file() {
                            self.load_env(rs, &p);
                        }
                    }
                    if ui.button("Built-in studio").clicked() {
                        self.env = Environment::studio(&rs.device, &rs.queue);
                    }
                });
            });
        });
        // controls hint, bottom left
        let hint = "Left-drag paint   ·   Right-drag orbit   ·   Middle-drag pan   ·   Wheel zoom   ·   [ ] size   ·   F frame";
        ui.painter().text(rect.left_bottom() + egui::vec2(12.0, -12.0), egui::Align2::LEFT_BOTTOM, hint, egui::FontId::proportional(12.0), Color32::from_white_alpha(140));
    }

    // ------------------------------------------------------------ windows

    fn dialogs(&mut self, ctx: &egui::Context, rs: &RenderState) {
        if let Some(p) = self.pending.clone() {
            egui::Window::new("Unsaved changes").collapsible(false).resizable(false).anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0]).show(ctx, |ui| {
                ui.label("This project has unsaved changes. What would you like to do?");
                ui.horizontal(|ui| {
                    if ui.button("Save first").clicked() {
                        self.save(rs, false);
                        self.pending = None;
                        if !self.modified {
                            self.run_pending(rs, p.clone());
                        }
                    }
                    if ui.button("Discard changes").clicked() {
                        self.pending = None;
                        self.run_pending(rs, p.clone());
                    }
                    if ui.button("Cancel").clicked() {
                        self.pending = None;
                    }
                });
            });
        }

        if self.show_export {
            let mut open = true;
            egui::Window::new("Export textures").open(&mut open).collapsible(false).resizable(false).show(ctx, |ui| {
                let presets = export::presets();
                let current = presets.iter().find(|p| p.id == self.doc.export_preset).cloned().unwrap_or_else(|| presets[0].clone());
                egui::Grid::new("export").num_columns(2).spacing([10.0, 8.0]).show(ui, |ui| {
                    ui.label("Target");
                    egui::ComboBox::from_id_salt("preset").selected_text(current.label).show_ui(ui, |ui| {
                        for p in &presets {
                            ui.selectable_value(&mut self.doc.export_preset, p.id.to_string(), p.label);
                        }
                    });
                    ui.end_row();
                    ui.label("Name");
                    ui.text_edit_singleline(&mut self.export_name);
                    ui.end_row();
                    ui.label("Folder");
                    ui.horizontal(|ui| {
                        let shown = self.export_dir.as_ref().map(|d| d.display().to_string()).unwrap_or_else(|| "(choose a folder)".into());
                        ui.label(RichText::new(shown).color(MUTED));
                        if ui.button("Choose…").clicked() {
                            if let Some(d) = rfd::FileDialog::new().pick_folder() {
                                self.export_dir = Some(d);
                            }
                        }
                    });
                    ui.end_row();
                    ui.label("Size");
                    ui.label(format!("{0} × {0} px", self.ts.res));
                    ui.end_row();
                });
                ui.add_space(4.0);
                card(ui, CARD, |ui| {
                    for o in &current.outputs {
                        ui.label(RichText::new(format!("{}_{}.png", self.export_name, o.suffix)).monospace().size(12.0));
                    }
                });
                ui.add_space(4.0);
                let ready = self.export_dir.is_some() && !self.export_name.trim().is_empty();
                if ui.add_enabled(ready, egui::Button::new(RichText::new("Export").strong()).min_size(egui::vec2(120.0, 28.0))).clicked() {
                    self.export(rs);
                }
            });
            self.show_export = open;
        }
    }
}
