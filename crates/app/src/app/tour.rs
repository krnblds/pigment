//! The quick-start guide ("Learn in 2 minutes"): contextual coach marks, one
//! step at a time, a glowing outline around the thing to use, and automatic
//! progress when the user has done it. It never blocks the window: it sits
//! next to what it points at and can be closed any time.

use super::design::{self as ds, font, space, Btn};
use super::*;
use egui::Stroke;

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
        body: "Pick a colour in the Brush panel (or press the button below), then hold the LEFT mouse button on the crate and drag.",
        anchor: "presets",
        show_me: Some("Pick orange paint for me"),
    },
    Step {
        title: "Undo",
        body: "Made a mess? Press Ctrl+Z, or the undo arrow at the top. Ctrl+Y redoes.",
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
        body: "Export saves PNGs for Blender, Unreal, Unity or Godot in one click.",
        anchor: "export_button",
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
                self.brush.channels = [true, true, true, false, false, false, false, false, false, false, false];
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

    /// Start the guide on the demo crate (Advanced mode shows the layers it uses).
    pub(super) fn start_tour(&mut self, rs: &RenderState) {
        self.ui.welcome = false;
        if self.edge_wear_layer().is_none() {
            self.request(rs, Pending::Demo);
        }
        self.ui.prefs.mode = super::prefs::Mode::Advanced;
        for p in [super::dock::PanelId::Layers, super::dock::PanelId::Brush, super::dock::PanelId::Mask] {
            let l = self.ui.prefs.layout_mut();
            if !l.contains(p) {
                l.open(p);
            }
        }
        self.tour_start(true);
    }

    pub(super) fn tour_ui(&mut self, ctx: &egui::Context, viewport: egui::Rect) {
        if !self.tour.open {
            return;
        }
        let p = ds::theme(ctx).p;
        let screen = ctx.content_rect();
        let mut target = viewport;
        // glowing outline around the thing to use
        if let Some(step) = STEPS.get(self.tour.step) {
            // the generator settings only exist once the Edge wear layer is selected: point at its row until then
            let anchor = self.anchors.get(step.anchor).or_else(|| if step.anchor == "generator" { self.anchors.get("edge_wear_row") } else { None });
            if let Some(r) = anchor {
                let t = ctx.input(|i| i.time) as f32;
                let a = 0.55 + 0.4 * (t * 4.0).sin();
                let painter = ctx.layer_painter(egui::LayerId::new(egui::Order::Foreground, egui::Id::NULL.with("tour glow")));
                let r = if step.anchor == "viewport" { r.shrink(space::SM) } else { r.expand(space::XS) };
                painter.rect_stroke(r, egui::CornerRadius::same(ds::radius::LG), Stroke::new(3.0, p.accent.gamma_multiply(a)), egui::StrokeKind::Outside);
                target = r;
            }
        }
        // a coach mark next to the target: below it if there's room, else in the viewport corner
        let width = 320.0;
        let below = egui::pos2(target.left().clamp(screen.left() + space::LG, screen.right() - width - space::LG), target.bottom() + space::MD);
        let pos = if step_points_at_viewport(self.tour.step) || below.y > screen.bottom() - 220.0 {
            egui::pos2(viewport.right() - width - space::XL, viewport.bottom() - space::XL - 190.0)
        } else {
            below
        };
        let mut close = false;
        let mut finish = false;
        egui::Area::new(egui::Id::NULL.with("quick start")).fixed_pos(pos).order(egui::Order::Foreground).show(ctx, |ui| {
            ds::overlay_frame(&p).stroke(Stroke::new(1.0, p.accent)).show(ui, |ui| {
                ui.set_width(width - space::LG * 2.0);
                match STEPS.get(self.tour.step) {
                    Some(step) => {
                        ui.horizontal(|ui| {
                            ui.label(ds::caption(ui, &format!("Learn in 2 minutes  ·  {} of {}", self.tour.step + 1, STEPS.len())).color(p.accent));
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                if ui.add(ds::IconBtn::new(ds::Icon::Close, "Close the guide").size(ds::size::CONTROL_H_SM)).clicked() {
                                    close = true;
                                }
                            });
                        });
                        ui.horizontal(|ui| {
                            for k in 0..STEPS.len() {
                                let (r, _) = ui.allocate_exact_size(egui::vec2(space::MD, space::MD), egui::Sense::hover());
                                let c = if k < self.tour.step { p.accent } else if k == self.tour.step { p.text } else { p.border_strong };
                                ui.painter().circle_filled(r.center(), 3.5, c);
                            }
                        });
                        ui.label(ds::strong(step.title, font::HEADING));
                        ui.add(egui::Label::new(ds::text(step.body, font::BODY)).wrap());
                        ui.add_space(space::SM);
                        ui.horizontal(|ui| {
                            if let Some(label) = step.show_me {
                                if ui.add(Btn::primary(label).small()).clicked() {
                                    self.tour_show_me();
                                }
                            }
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                if ui.add(Btn::ghost("Skip").small()).clicked() {
                                    let next = self.tour.step + 1;
                                    self.tour_go(next);
                                }
                                if self.tour.step > 0 && ui.add(Btn::ghost("Back").small()).clicked() {
                                    let prev = self.tour.step - 1;
                                    self.tour_go(prev);
                                }
                            });
                        });
                    }
                    None => {
                        ui.label(ds::strong("You're all set!", font::HEADING));
                        ui.label(ds::text("That's the whole loop: paint, layer, wear, export.", font::BODY));
                        ui.add_space(space::XS);
                        ds::hint(ui, "Try next: the Materials panel for rust, concrete or car paint; Ctrl+K to find any action; ? for shortcuts.");
                        ui.add_space(space::SM);
                        if ui.add(Btn::primary("Done").small()).clicked() {
                            finish = true;
                        }
                    }
                }
            });
        });
        if close || finish {
            self.tour.open = false;
            self.ui.prefs.tour_done = true;
            let _ = self.ui.prefs.save();
        }
    }
}

fn step_points_at_viewport(step: usize) -> bool {
    STEPS.get(step).is_some_and(|s| s.anchor == "viewport")
}
