//! The quick-start guide: one step at a time, a glowing outline around the
//! thing to use, and automatic progress when the user has done it.

use super::*;
use egui::{Color32, CornerRadius, RichText, Stroke};

const ACCENT: Color32 = Color32::from_rgb(236, 142, 64);

pub struct Step {
    pub title: &'static str,
    pub body: &'static str,
    /// UI anchor to outline (registered by the panels each frame).
    pub anchor: &'static str,
    pub show_me: Option<&'static str>,
}

pub const STEPS: [Step; 6] = [
    Step {
        title: "Look around",
        body: "Hold the RIGHT mouse button on the crate and drag to spin it. Scroll the wheel to zoom.",
        anchor: "viewport",
        show_me: None,
    },
    Step {
        title: "Paint on it",
        body: "Pick a colour from the presets on the left, then hold the LEFT mouse button on the crate and drag.",
        anchor: "presets",
        show_me: Some("Pick orange paint for me"),
    },
    Step {
        title: "Undo",
        body: "Made a mess? Press Ctrl+Z to undo (Ctrl+Y redoes).",
        anchor: "edit_menu",
        show_me: None,
    },
    Step {
        title: "Change the worn edges",
        body: "The bare metal on the edges comes from the \"Edge wear\" layer. Drag its Amount slider to wear the paint more or less.",
        anchor: "generator",
        show_me: Some("Open the Edge wear settings"),
    },
    Step {
        title: "Protect an area",
        body: "With the Edge wear mask selected, the brush paints black: paint over some worn edges to make the paint whole again.",
        anchor: "viewport",
        show_me: Some("Set it up for me"),
    },
    Step {
        title: "Use it in your game",
        body: "File → Export textures saves PNGs ready for Unreal, Unity or Godot.",
        anchor: "file_menu",
        show_me: Some("Open export"),
    },
];

#[derive(Default)]
pub struct Tour {
    pub open: bool,
    pub step: usize,
    /// Counters and values when the current step began.
    start: Snapshot,
}

#[derive(Default, Clone, PartialEq)]
struct Snapshot {
    yaw: f32,
    pitch: f32,
    distance: f32,
    strokes: u32,
    mask_strokes: u32,
    undos: u32,
    wear_amount: Option<f32>,
}

fn marker() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA").or_else(|| std::env::var_os("XDG_CONFIG_HOME")).map(PathBuf::from).or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("pigment").join("quick_start_done"))
}

impl PigmentApp {
    fn tour_snapshot(&self) -> Snapshot {
        Snapshot {
            yaw: self.camera.yaw,
            pitch: self.camera.pitch,
            distance: self.camera.distance,
            strokes: self.counters.strokes,
            mask_strokes: self.counters.mask_strokes,
            undos: self.counters.undos,
            wear_amount: self.edge_wear_layer().and_then(|i| self.doc.layers[i].mask.as_ref()?.generator.as_ref().map(|g| g.amount)),
        }
    }

    pub(super) fn edge_wear_layer(&self) -> Option<usize> {
        self.doc.layers.iter().position(|l| l.mask.as_ref().and_then(|m| m.generator.as_ref()).is_some_and(|g| g.kind == GeneratorKind::EdgeWear))
    }

    pub(super) fn tour_start(&mut self, force: bool) {
        if !force && marker().is_some_and(|m| m.exists()) {
            return;
        }
        self.tour.open = true;
        self.tour.step = 0;
        self.tour.start = self.tour_snapshot();
    }

    fn tour_go(&mut self, step: usize) {
        self.tour.step = step;
        self.tour.start = self.tour_snapshot();
    }

    /// Has the user done what the current step asks?
    pub(super) fn tour_step_done(&self) -> bool {
        let s = &self.tour.start;
        let now = self.tour_snapshot();
        match self.tour.step {
            0 => (now.yaw - s.yaw).abs() + (now.pitch - s.pitch).abs() > 0.3 || (now.distance - s.distance).abs() > s.distance * 0.15,
            1 => now.strokes > s.strokes,
            2 => now.undos > s.undos,
            3 => now.wear_amount.is_some() && now.wear_amount != s.wear_amount,
            4 => now.mask_strokes > s.mask_strokes,
            5 => self.show_export,
            _ => false,
        }
    }

    /// Advance when done (call once per frame, outside a stroke).
    pub(super) fn tour_update(&mut self) {
        if self.tour.open && self.tour.step < STEPS.len() && self.stroke.is_none() && self.tour_step_done() {
            let next = self.tour.step + 1;
            self.tour_go(next);
        }
    }

    pub(super) fn tour_show_me(&mut self) {
        match self.tour.step {
            1 => {
                let top = self.doc.layers.iter().rev().find(|l| l.is_paint()).map(|l| l.id);
                self.select(top, false);
                self.brush.values = material_preset("Orange paint");
                self.brush.channels = [true, true, true, false, false, false];
                self.brush.erase = false;
            }
            3 | 4 => {
                if let Some(i) = self.edge_wear_layer() {
                    let id = self.doc.layers[i].id;
                    self.select(Some(id), true);
                    if self.tour.step == 4 {
                        self.brush.mask_white = false;
                        self.brush.erase = false;
                        self.brush.size = self.brush.size.max(60.0);
                    }
                }
            }
            5 => self.show_export = true,
            _ => {}
        }
    }

    pub(super) fn tour_ui(&mut self, ctx: &egui::Context, viewport: egui::Rect) {
        if !self.tour.open {
            return;
        }
        // glowing outline around the thing to use
        if let Some(step) = STEPS.get(self.tour.step) {
            // the generator settings only exist once the Edge wear layer is selected: point at its row until then
            let anchor = self.anchors.get(step.anchor).or_else(|| if step.anchor == "generator" { self.anchors.get("edge_wear_row") } else { None });
            if let Some(r) = anchor {
                let t = ctx.input(|i| i.time) as f32;
                let a = (150.0 + 100.0 * (t * 4.0).sin()) as u8;
                let painter = ctx.layer_painter(egui::LayerId::new(egui::Order::Foreground, egui::Id::unique("tour glow")));
                let r = if step.anchor == "viewport" { r.shrink(6.0) } else { r.expand(4.0) };
                painter.rect_stroke(r, CornerRadius::same(8), Stroke::new(3.0, Color32::from_rgba_unmultiplied(236, 142, 64, a)), egui::StrokeKind::Outside);
            }
        }
        let width = 330.0;
        let pos = egui::pos2(viewport.right() - width - 16.0, viewport.bottom() - 16.0);
        let mut close = false;
        let mut finish = false;
        egui::Area::new(egui::Id::unique("quick start"))
            .fixed_pos(pos)
            .pivot(egui::Align2::LEFT_BOTTOM)
            .order(egui::Order::Foreground)
            .show(ctx, |ui| {
                egui::Frame::new()
                    .fill(Color32::from_rgb(34, 35, 39))
                    .stroke(Stroke::new(1.0, ACCENT))
                    .corner_radius(CornerRadius::same(10))
                    .inner_margin(egui::Margin::same(14))
                    .shadow(egui::Shadow { offset: [0, 4], blur: 16, spread: 0, color: Color32::from_black_alpha(120) })
                    .show(ui, |ui| {
                        ui.set_width(width - 28.0);
                        match STEPS.get(self.tour.step) {
                            Some(step) => {
                                ui.horizontal(|ui| {
                                    ui.label(RichText::new(format!("QUICK START  ·  {} of {}", self.tour.step + 1, STEPS.len())).size(11.0).color(ACCENT).strong());
                                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                        if ui.small_button("Close").clicked() {
                                            close = true;
                                        }
                                    });
                                });
                                // progress dots
                                ui.horizontal(|ui| {
                                    for k in 0..STEPS.len() {
                                        let (r, _) = ui.allocate_exact_size(egui::vec2(10.0, 10.0), egui::Sense::hover());
                                        let c = if k < self.tour.step { ACCENT } else if k == self.tour.step { Color32::WHITE } else { Color32::from_gray(70) };
                                        ui.painter().circle_filled(r.center(), 4.0, c);
                                    }
                                });
                                ui.add_space(4.0);
                                ui.label(RichText::new(step.title).size(18.0).strong());
                                ui.label(RichText::new(step.body).size(14.0));
                                ui.add_space(6.0);
                                ui.horizontal(|ui| {
                                    if let Some(label) = step.show_me {
                                        if ui.add(egui::Button::new(RichText::new(label).strong()).fill(Color32::from_rgb(92, 58, 32))).clicked() {
                                            self.tour_show_me();
                                        }
                                    }
                                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                        if ui.small_button("Skip").clicked() {
                                            let next = self.tour.step + 1;
                                            self.tour_go(next);
                                        }
                                        if self.tour.step > 0 && ui.small_button("Back").clicked() {
                                            let prev = self.tour.step - 1;
                                            self.tour_go(prev);
                                        }
                                    });
                                });
                            }
                            None => {
                                ui.label(RichText::new("You're all set!").size(18.0).strong());
                                ui.label("That's the whole loop: paint, layer, wear, export.");
                                ui.add_space(4.0);
                                ui.label(RichText::new("Try next:").strong());
                                ui.label("• + Add layer → Rust, for rust in the crevices");
                                ui.label("• File → New project from mesh… to paint your own model");
                                ui.label("• Help → Quick start guide brings this back");
                                ui.add_space(6.0);
                                if ui.button(RichText::new("Done").strong()).clicked() {
                                    finish = true;
                                }
                            }
                        }
                    });
            });
        if close || finish {
            self.tour.open = false;
            if let Some(m) = marker() {
                let _ = std::fs::create_dir_all(m.parent().unwrap());
                let _ = std::fs::write(m, "1");
            }
        }
    }
}
