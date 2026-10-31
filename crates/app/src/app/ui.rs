//! The egui layout: menus, tool panel, layer stack, properties, viewport input.

use super::*;
use egui::{Color32, RichText};

const ACCENT: Color32 = Color32::from_rgb(232, 140, 70);

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

        self.shortcuts(ui, &rs);
        if std::mem::take(&mut self.dump_requested) {
            self.debug_dump(&rs, &std::env::temp_dir().join("pig").join("dump"));
        }

        egui::Panel::top("menu").show(ui, |ui| self.menu_bar(ui, &rs));
        egui::Panel::bottom("status").show(ui, |ui| self.status_bar(ui));
        egui::Panel::left("tools").resizable(true).default_size(270.0).show(ui, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| self.tools_panel(ui, &rs));
        });
        egui::Panel::right("layers").resizable(true).default_size(310.0).show(ui, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| self.layers_panel(ui, &rs));
        });
        egui::CentralPanel::default().frame(egui::Frame::NONE).show(ui, |ui| self.viewport_ui(ui, &rs));

        self.dialogs(ui.ctx(), &rs);

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
            if i.key_pressed(Key::E) {
                self.brush.erase = !self.brush.erase;
            }
            if i.key_pressed(Key::X) {
                self.brush.mask_white = !self.brush.mask_white;
            }
            if i.key_pressed(Key::M) {
                self.view.mode = if self.view.mode == ViewMode::Material { ViewMode::BaseColor } else { ViewMode::Material };
            }
            if i.key_pressed(Key::F12) {
                self.dump_requested = true;
            }
            if i.key_pressed(Key::F) {
                let (c, r) = self.mesh.bounding_sphere();
                self.camera.frame(c, r);
            }
        });
    }

    fn open_dialog(&mut self, rs: &RenderState) {
        if let Some(p) = rfd::FileDialog::new().set_title("Open project folder (.pigment)").pick_folder() {
            self.request(rs, Pending::OpenProject(p));
        }
    }

    fn menu_bar(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        egui::MenuBar::new().ui(ui, |ui| {
            ui.menu_button("File", |ui| {
                if ui.button("New project from mesh…").clicked() {
                    if let Some(p) = rfd::FileDialog::new().add_filter("Meshes", &["obj", "gltf", "glb"]).pick_file() {
                        self.request(rs, Pending::NewFromMesh(p));
                    }
                }
                if ui.button("New project (test torus)").clicked() {
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
            ui.menu_button("Edit", |ui| {
                let ul = self.history.undo_label().map(|s| format!("Undo {s}")).unwrap_or_else(|| "Undo".into());
                if ui.add_enabled(self.history.can_undo() || self.doc != self.committed, egui::Button::new(ul).shortcut_text("Ctrl+Z")).clicked() {
                    self.undo(rs, false);
                }
                let rl = self.history.redo_label().map(|s| format!("Redo {s}")).unwrap_or_else(|| "Redo".into());
                if ui.add_enabled(self.history.can_redo(), egui::Button::new(rl).shortcut_text("Ctrl+Y")).clicked() {
                    self.undo(rs, true);
                }
            });
            ui.menu_button("View", |ui| {
                if ui.add(egui::Button::new("Frame mesh").shortcut_text("F")).clicked() {
                    let (c, r) = self.mesh.bounding_sphere();
                    self.camera.frame(c, r);
                }
                ui.separator();
                for m in ViewMode::ALL {
                    ui.radio_value(&mut self.view.mode, m, m.label());
                }
            });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let name = self.project_dir.as_ref().and_then(|d| d.file_name()).map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "Untitled".into());
                ui.label(RichText::new(format!("{name}{}", if self.modified { " •" } else { "" })).strong());
            });
        });
    }

    fn status_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let avg = self.frame_times.iter().sum::<f32>() / self.frame_times.len().max(1) as f32;
            ui.label(format!("{:.0} fps", 1.0 / avg.max(1e-6)));
            ui.separator();
            ui.label(format!("{} tris", format_count(self.mesh.triangle_count())));
            ui.separator();
            ui.label(format!("{}² · {} layers · {:.0} MB layer VRAM", self.ts.res, self.doc.layers.len(), self.ts.vram_bytes() as f64 / 1048576.0));
            if self.last_stamp_ms > 0.0 {
                ui.separator();
                ui.label(format!("{:.2} ms/stamp", self.last_stamp_ms));
            }
            if let Some((msg, err)) = &self.status {
                ui.separator();
                if *err {
                    ui.colored_label(Color32::from_rgb(240, 150, 90), msg);
                } else {
                    ui.label(msg);
                }
            }
        });
    }

    // ------------------------------------------------------------ left panel

    fn tools_panel(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        ui.heading("Brush");
        let target = match self.paint_target() {
            Ok(Target::Layer(_)) => RichText::new("Painting on the layer").color(ACCENT),
            Ok(Target::Mask(_)) => RichText::new("Painting on the mask").color(ACCENT),
            Err(e) => RichText::new(e).color(Color32::GRAY),
        };
        ui.label(target);
        egui::Grid::new("brush").num_columns(2).show(ui, |ui| {
            ui.label("Size");
            ui.add(egui::Slider::new(&mut self.brush.size, 2.0..=800.0).logarithmic(true).suffix(" px"));
            ui.end_row();
            ui.label("Opacity");
            ui.add(egui::Slider::new(&mut self.brush.opacity, 0.0..=1.0));
            ui.end_row();
            ui.label("Hardness");
            ui.add(egui::Slider::new(&mut self.brush.hardness, 0.0..=1.0));
            ui.end_row();
            ui.label("Spacing");
            ui.add(egui::Slider::new(&mut self.brush.spacing, 0.02..=1.0).custom_formatter(|v, _| format!("{:.0}%", v * 100.0)));
            ui.end_row();
        });
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.brush.erase, false, "Paint");
            ui.selectable_value(&mut self.brush.erase, true, "Erase (E)");
        });
        if matches!(self.paint_target(), Ok(Target::Mask(_))) {
            ui.horizontal(|ui| {
                ui.label("Mask colour (X)");
                ui.selectable_value(&mut self.brush.mask_white, true, "White: show");
                ui.selectable_value(&mut self.brush.mask_white, false, "Black: hide");
            });
        } else {
            ui.add_space(4.0);
            ui.label(RichText::new("Channels the brush paints").small());
            let b = &mut self.brush;
            egui::Grid::new("brush channels").num_columns(2).show(ui, |ui| {
                ui.checkbox(&mut b.channels[0], "Base color");
                srgb_edit(ui, &mut b.values.base_color);
                ui.end_row();
                ui.checkbox(&mut b.channels[1], "Roughness");
                ui.add(egui::Slider::new(&mut b.values.roughness, 0.0..=1.0));
                ui.end_row();
                ui.checkbox(&mut b.channels[2], "Metallic");
                ui.add(egui::Slider::new(&mut b.values.metallic, 0.0..=1.0));
                ui.end_row();
                ui.checkbox(&mut b.channels[3], "Height");
                ui.add(egui::Slider::new(&mut b.values.height, -1.0..=1.0));
                ui.end_row();
                ui.checkbox(&mut b.channels[4], "Normal");
                tilt_edit(ui, &mut b.values.normal);
                ui.end_row();
            });
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new("Presets:").small());
                let presets: [(&str, [f32; 3], f32, f32); 5] = [
                    ("Iron", [0.56, 0.57, 0.58], 0.35, 1.0),
                    ("Gold", [1.0, 0.77, 0.34], 0.25, 1.0),
                    ("Rust", [0.45, 0.2, 0.09], 0.85, 0.0),
                    ("Paint", [0.75, 0.2, 0.12], 0.4, 0.0),
                    ("Rubber", [0.05, 0.05, 0.05], 0.9, 0.0),
                ];
                for (name, c, r, m) in presets {
                    if ui.small_button(name).clicked() {
                        b.values.base_color = c;
                        b.values.roughness = r;
                        b.values.metallic = m;
                        b.channels[0] = true;
                        b.channels[1] = true;
                        b.channels[2] = true;
                    }
                }
            });
        }

        ui.add_space(10.0);
        ui.separator();
        ui.heading("Display");
        egui::ComboBox::from_id_salt("viewmode").selected_text(self.view.mode.label()).show_ui(ui, |ui| {
            for m in ViewMode::ALL {
                ui.selectable_value(&mut self.view.mode, m, m.label());
            }
        });
        egui::Grid::new("display").num_columns(2).show(ui, |ui| {
            ui.label("Exposure");
            ui.add(egui::Slider::new(&mut self.view.exposure, -4.0..=4.0).suffix(" EV"));
            ui.end_row();
            ui.label("Rotate light");
            ui.add(egui::Slider::new(&mut self.view.env_rotation, -std::f32::consts::PI..=std::f32::consts::PI));
            ui.end_row();
        });
        ui.checkbox(&mut self.view.show_env, "Show environment behind the model");
        ui.horizontal(|ui| {
            ui.label(format!("HDRI: {}", self.env.name));
            if ui.small_button("Load .hdr/.exr…").clicked() {
                if let Some(p) = rfd::FileDialog::new().add_filter("HDR images", &["hdr", "exr"]).pick_file() {
                    self.load_env(rs, &p);
                }
            }
            if ui.small_button("Studio").clicked() {
                self.env = Environment::studio(&rs.device, &rs.queue);
            }
        });

        ui.add_space(10.0);
        ui.separator();
        ui.heading("Texture set");
        let mut res = self.doc.resolution;
        egui::ComboBox::from_id_salt("res").selected_text(format!("{res} × {res}")).show_ui(ui, |ui| {
            for r in RESOLUTIONS {
                ui.selectable_value(&mut res, r, format!("{r} × {r}"));
            }
        });
        if res != self.doc.resolution {
            self.change_resolution(rs, res);
        }
        ui.label(RichText::new("Changing size resamples all layers and clears undo.").small().color(Color32::GRAY));

        ui.add_space(6.0);
        ui.label(RichText::new("Bake mesh maps").strong());
        egui::Grid::new("bake").num_columns(2).show(ui, |ui| {
            ui.label("AO quality");
            egui::ComboBox::from_id_salt("ao").selected_text(format!("{} directions", self.doc.bake.ao_samples)).show_ui(ui, |ui| {
                for n in [32, 64, 128, 256, 512] {
                    ui.selectable_value(&mut self.doc.bake.ao_samples, n, format!("{n} directions"));
                }
            });
            ui.end_row();
            ui.label("Edge width");
            ui.add(egui::Slider::new(&mut self.doc.bake.curvature_radius, 0.001..=0.05).logarithmic(true));
            ui.end_row();
            ui.label("Edge strength");
            ui.add(egui::Slider::new(&mut self.doc.bake.curvature_strength, 0.1..=4.0));
            ui.end_row();
        });
        if ui.button("Bake AO + curvature").clicked() {
            self.bake(rs);
        }
    }

    // ------------------------------------------------------------ right panel

    fn layers_panel(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        ui.heading("Layers");
        ui.horizontal_wrapped(|ui| {
            if ui.button("+ Paint").on_hover_text("New paint layer above the selection").clicked() {
                let l = self.doc.new_paint_layer(&format!("Paint {}", self.doc.layers.len() + 1));
                self.insert_layer(l);
            }
            if ui.button("+ Fill").on_hover_text("New fill layer (a flat material, shaped by its mask)").clicked() {
                let l = self.doc.new_fill_layer(&format!("Fill {}", self.doc.layers.len() + 1));
                self.insert_layer(l);
            }
            if ui.button("+ Edge wear").on_hover_text("Bare-metal fill masked by the edge wear generator").clicked() {
                let mut l = self.doc.new_fill_layer("Edge wear");
                if let LayerKind::Fill { values } = &mut l.kind {
                    *values = MaterialValues { base_color: [0.62, 0.62, 0.62], roughness: 0.3, metallic: 1.0, height: 0.0, normal: [0.0, 0.0] };
                }
                l.channels.height.enabled = false;
                l.channels.normal.enabled = false;
                let res = self.doc.mint();
                self.ts.new_mask(&rs.device, &rs.queue, res, true);
                l.mask = Some(Mask { res, generator: Some(Generator::new(GeneratorKind::EdgeWear)), invert: false, enabled: true });
                self.insert_layer(l);
            }
            if ui.button("+ Dirt").on_hover_text("Grime fill masked by the dirt generator").clicked() {
                let mut l = self.doc.new_fill_layer("Dirt");
                if let LayerKind::Fill { values } = &mut l.kind {
                    *values = MaterialValues { base_color: [0.16, 0.12, 0.08], roughness: 0.9, metallic: 0.0, height: 0.0, normal: [0.0, 0.0] };
                }
                l.channels.metallic.enabled = false;
                l.channels.height.enabled = false;
                l.channels.normal.enabled = false;
                let res = self.doc.mint();
                self.ts.new_mask(&rs.device, &rs.queue, res, true);
                let mut g = Generator::new(GeneratorKind::Dirt);
                g.amount = 0.35;
                l.mask = Some(Mask { res, generator: Some(g), invert: false, enabled: true });
                self.insert_layer(l);
            }
        });
        ui.horizontal(|ui| {
            let sel = self.selected.and_then(|id| self.doc.index_of(id));
            if ui.add_enabled(sel.is_some(), egui::Button::new("Duplicate")).clicked() {
                self.duplicate_selected(rs);
            }
            if ui.add_enabled(sel.is_some(), egui::Button::new("Delete")).clicked() {
                if let Some(i) = sel {
                    self.doc.layers.remove(i);
                    self.selected = self.doc.layers.get(i.min(self.doc.layers.len().saturating_sub(1))).map(|l| l.id);
                }
            }
            if ui.add_enabled(sel.is_some_and(|i| i + 1 < self.doc.layers.len()), egui::Button::new("Up")).on_hover_text("Move up").clicked() {
                let i = sel.unwrap();
                self.doc.layers.swap(i, i + 1);
            }
            if ui.add_enabled(sel.is_some_and(|i| i > 0), egui::Button::new("Down")).on_hover_text("Move down").clicked() {
                let i = sel.unwrap();
                self.doc.layers.swap(i, i - 1);
            }
        });
        ui.add_space(4.0);

        // top of the stack first, like every layer UI
        let n = self.doc.layers.len();
        for i in (0..n).rev() {
            let id = self.doc.layers[i].id;
            let selected = self.selected == Some(id);
            let frame = egui::Frame::group(ui.style()).fill(if selected { Color32::from_rgb(58, 46, 38) } else { Color32::from_gray(32) });
            frame.show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.horizontal(|ui| {
                    let l = &mut self.doc.layers[i];
                    ui.checkbox(&mut l.visible, "").on_hover_text("Show / hide");
                    let kind = if l.is_paint() { "paint" } else { "fill" };
                    ui.label(RichText::new(kind).small().color(Color32::GRAY));
                    let text = RichText::new(&l.name);
                    let text = if selected { text.color(ACCENT).strong() } else { text };
                    if ui.selectable_label(selected && !self.paint_mask, text).clicked() {
                        self.selected = Some(id);
                        self.paint_mask = !l.is_paint();
                    }
                    if let Some(m) = &l.mask {
                        let label = match &m.generator {
                            Some(g) => format!("mask: {}", g.kind.label().to_lowercase()),
                            None => "mask".to_string(),
                        };
                        if ui.selectable_label(selected && self.paint_mask, RichText::new(label).small()).on_hover_text("Select the mask to paint on it").clicked() {
                            self.selected = Some(id);
                            self.paint_mask = true;
                        }
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new(format!("{:.0}%", l.opacity * 100.0)).small().color(Color32::GRAY));
                    });
                });
            });
        }

        ui.add_space(10.0);
        ui.separator();
        self.properties(ui, rs);

        ui.add_space(10.0);
        ui.separator();
        egui::CollapsingHeader::new("History").default_open(false).show(ui, |ui| {
            let (labels, applied) = self.history.history();
            if labels.is_empty() {
                ui.label(RichText::new("Nothing yet").color(Color32::GRAY));
            }
            for (i, l) in labels.iter().enumerate().rev().take(40) {
                let t = RichText::new(*l);
                ui.label(if i < applied { t } else { t.color(Color32::DARK_GRAY).italics() });
            }
        });
    }

    fn insert_layer(&mut self, l: Layer) {
        let at = self.selected.and_then(|id| self.doc.index_of(id)).map(|i| i + 1).unwrap_or(self.doc.layers.len());
        self.selected = Some(l.id);
        self.paint_mask = !l.is_paint();
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
            ui.label("Select a layer to edit it.");
            return;
        };
        ui.heading("Properties");
        let id = self.doc.layers[i].id;
        // rename
        let mut name = match &self.renaming {
            Some((rid, n)) if *rid == id => n.clone(),
            _ => self.doc.layers[i].name.clone(),
        };
        let r = ui.add(egui::TextEdit::singleline(&mut name).desired_width(f32::INFINITY));
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

        let mut add_mask: Option<bool> = None;
        let mut add_gen: Option<GeneratorKind> = None;
        {
            let l = &mut self.doc.layers[i];
            ui.horizontal(|ui| {
                ui.label("Opacity");
                ui.add(egui::Slider::new(&mut l.opacity, 0.0..=1.0));
            });

            if let LayerKind::Fill { values } = &mut l.kind {
                ui.label(RichText::new("Fill material").strong());
                egui::Grid::new("fill").num_columns(2).show(ui, |ui| {
                    ui.label("Base color");
                    srgb_edit(ui, &mut values.base_color);
                    ui.end_row();
                    ui.label("Roughness");
                    ui.add(egui::Slider::new(&mut values.roughness, 0.0..=1.0));
                    ui.end_row();
                    ui.label("Metallic");
                    ui.add(egui::Slider::new(&mut values.metallic, 0.0..=1.0));
                    ui.end_row();
                    ui.label("Height");
                    ui.add(egui::Slider::new(&mut values.height, -1.0..=1.0));
                    ui.end_row();
                    ui.label("Normal tilt");
                    tilt_edit(ui, &mut values.normal);
                    ui.end_row();
                });
            }

            egui::CollapsingHeader::new("Channels & blending").default_open(true).show(ui, |ui| {
                egui::Grid::new("channels").num_columns(3).striped(true).show(ui, |ui| {
                    for c in Channel::ALL {
                        let s = l.channels.get_mut(c);
                        ui.checkbox(&mut s.enabled, c.label());
                        egui::ComboBox::from_id_salt(("blend", c.index())).width(110.0).selected_text(s.blend.label()).show_ui(ui, |ui| {
                            for m in c.blend_modes() {
                                ui.selectable_value(&mut s.blend, *m, m.label());
                            }
                        });
                        ui.add(egui::DragValue::new(&mut s.opacity).range(0.0..=1.0).speed(0.01).custom_formatter(|v, _| format!("{:.0}%", v * 100.0)));
                        ui.end_row();
                    }
                });
            });

            ui.add_space(4.0);
            ui.label(RichText::new("Mask").strong());
            match &mut l.mask {
                None => {
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("Add white mask").clicked() {
                            add_mask = Some(true);
                        }
                        if ui.button("Add black mask").clicked() {
                            add_mask = Some(false);
                        }
                        if ui.button("Edge wear").clicked() {
                            add_gen = Some(GeneratorKind::EdgeWear);
                        }
                        if ui.button("Dirt").clicked() {
                            add_gen = Some(GeneratorKind::Dirt);
                        }
                    });
                }
                Some(m) => {
                    ui.horizontal(|ui| {
                        ui.checkbox(&mut m.enabled, "Enabled");
                        ui.checkbox(&mut m.invert, "Invert");
                    });
                    ui.horizontal(|ui| {
                        ui.selectable_value(&mut self.paint_mask, false, "Paint layer").on_hover_text("Brush paints the layer's channels");
                        ui.selectable_value(&mut self.paint_mask, true, "Paint mask").on_hover_text("Brush paints the mask (white shows, black hides)");
                    });
                    let mut kind = m.generator.as_ref().map(|g| g.kind);
                    egui::ComboBox::from_id_salt("gen").selected_text(kind.map(|k| k.label()).unwrap_or("No generator")).show_ui(ui, |ui| {
                        ui.selectable_value(&mut kind, None, "No generator");
                        ui.selectable_value(&mut kind, Some(GeneratorKind::EdgeWear), "Edge wear");
                        ui.selectable_value(&mut kind, Some(GeneratorKind::Dirt), "Dirt");
                    });
                    if kind != m.generator.as_ref().map(|g| g.kind) {
                        m.generator = kind.map(Generator::new);
                    }
                    if let Some(g) = &mut m.generator {
                        if !self.ts.baked {
                            ui.colored_label(Color32::from_rgb(240, 150, 90), "Bake mesh maps first (left panel)");
                        }
                        egui::Grid::new("generator").num_columns(2).show(ui, |ui| {
                            ui.label("Amount");
                            ui.add(egui::Slider::new(&mut g.amount, 0.0..=1.0));
                            ui.end_row();
                            ui.label("Softness");
                            ui.add(egui::Slider::new(&mut g.softness, 0.0..=0.5));
                            ui.end_row();
                            ui.label("Noise scale");
                            ui.add(egui::Slider::new(&mut g.noise_scale, 0.5..=64.0).logarithmic(true));
                            ui.end_row();
                            ui.label("Noise amount");
                            ui.add(egui::Slider::new(&mut g.noise_amount, 0.0..=1.5));
                            ui.end_row();
                            ui.label("Seed");
                            ui.add(egui::DragValue::new(&mut g.seed).range(0..=999));
                            ui.end_row();
                        });
                        ui.label(RichText::new("The painted mask multiplies the generator: paint black to protect areas.").small().color(Color32::GRAY));
                    }
                    if ui.button("Remove mask").clicked() {
                        l.mask = None;
                        self.paint_mask = false;
                    }
                }
            }
        }
        if add_mask.is_some() || add_gen.is_some() {
            let white = add_mask.unwrap_or(true);
            let res = self.doc.mint();
            self.ts.new_mask(&rs.device, &rs.queue, res, white);
            self.doc.layers[i].mask = Some(Mask { res, generator: add_gen.map(Generator::new), invert: false, enabled: true });
            self.paint_mask = add_gen.is_none();
        }
    }

    // ------------------------------------------------------------ viewport

    fn viewport_ui(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let rect = ui.available_rect_before_wrap();
        let response = ui.allocate_rect(rect, egui::Sense::click_and_drag());
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
        let height = viewport_px.y;
        if alt && response.dragged_by(egui::PointerButton::Primary) {
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

        self.ensure_composited(rs);
        let size = [viewport_px.x as u32, viewport_px.y as u32];
        if let Some(tex) = self.viewport.render(rs, size, &self.camera, &self.view, self.mesh_gpu.as_ref(), &self.env, &self.ts) {
            let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
            ui.painter().image(tex, rect, uv, Color32::WHITE);
        }

        // brush cursor
        if let Some(h) = self.hover.filter(|_| !alt) {
            let r = self.brush.size * 0.5;
            let col = if self.brush.erase { Color32::from_rgb(120, 190, 255) } else { Color32::from_white_alpha(220) };
            ui.painter().circle_stroke(h, r, egui::Stroke::new(1.5, col));
            ui.painter().circle_stroke(h, r * self.brush.hardness.max(0.02), egui::Stroke::new(1.0, Color32::from_white_alpha(70)));
            if !self.brush.erase && self.brush.channels[0] && !self.paint_mask {
                let c = self.brush.values.base_color.map(|v| (v * 255.0) as u8);
                ui.painter().circle_filled(h + egui::vec2(r * 0.72, -r * 0.72), 5.0, Color32::from_rgb(c[0], c[1], c[2]));
            }
            ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
        }

        // hint overlay
        let hint = "Left-drag: paint · Alt/right-drag: orbit · Middle-drag: pan · Wheel: zoom · [ ]: brush size · E: eraser · F: frame";
        ui.painter().text(rect.left_bottom() + egui::vec2(10.0, -10.0), egui::Align2::LEFT_BOTTOM, hint, egui::FontId::proportional(12.0), Color32::from_white_alpha(120));
        if self.mesh_gpu.is_none() {
            ui.painter().text(rect.center(), egui::Align2::CENTER_CENTER, "Drop a mesh here", egui::FontId::proportional(20.0), Color32::GRAY);
        }
    }

    // ------------------------------------------------------------ windows

    fn dialogs(&mut self, ctx: &egui::Context, rs: &RenderState) {
        if let Some(p) = self.pending.clone() {
            egui::Window::new("Unsaved changes")
                .collapsible(false)
                .resizable(false)
                .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
                .show(ctx, |ui| {
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
                egui::Grid::new("export").num_columns(2).show(ui, |ui| {
                    ui.label("Preset");
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
                        let shown = self.export_dir.as_ref().map(|d| d.display().to_string()).unwrap_or_else(|| "(choose)".into());
                        ui.label(shown);
                        if ui.button("Choose…").clicked() {
                            if let Some(d) = rfd::FileDialog::new().pick_folder() {
                                self.export_dir = Some(d);
                            }
                        }
                    });
                    ui.end_row();
                    ui.label("Size");
                    ui.label(format!("{0} × {0}", self.ts.res));
                    ui.end_row();
                });
                ui.add_space(4.0);
                ui.label(RichText::new("Files:").small());
                for o in &current.outputs {
                    ui.label(RichText::new(format!("  {}_{}.png", self.export_name, o.suffix)).small().monospace());
                }
                ui.add_space(4.0);
                if ui.add_enabled(self.export_dir.is_some() && !self.export_name.trim().is_empty(), egui::Button::new("Export")).clicked() {
                    self.export(rs);
                }
            });
            self.show_export = open;
        }
    }
}
