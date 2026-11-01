//! One icon set, drawn as vectors on an 18 x 18 grid with a 1.6 pt stroke
//! (scaled with the icon), round joins, 2 pt padding. Every tool and action
//! has one; `Icon::ALL` lists them for the gallery.

use eframe::egui;
use egui::{pos2, vec2, Color32, Painter, Pos2, Rect, Shape, Stroke};
use std::f32::consts::{FRAC_PI_2, PI, TAU};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
pub enum Icon {
    Brush,
    Eraser,
    Bucket,
    Stamp,
    Target,
    Undo,
    Redo,
    Export,
    Send,
    Save,
    Open,
    New,
    Plus,
    Minus,
    Close,
    Check,
    Eye,
    EyeOff,
    Lock,
    Unlock,
    Grip,
    Folder,
    Layers,
    PaintLayer,
    FillLayer,
    Mask,
    Wand,
    Search,
    Gear,
    Help,
    Keyboard,
    Command,
    History,
    Sun,
    Moon,
    Glow,
    Frame,
    Orbit,
    Grid,
    ChevronRight,
    ChevronDown,
    More,
    Trash,
    Duplicate,
    Warning,
    Info,
    Error,
    Success,
    Dice,
    Image,
    Cube,
    Parts,
    Rain,
    Palette,
    Sliders,
    Tile,
    Trim,
    Atlas,
    Window,
    Sparkle,
    Play,
    Scatter,
    Leaf,
}

impl Icon {
    pub const ALL: [Icon; 63] = [
        Icon::Brush,
        Icon::Eraser,
        Icon::Bucket,
        Icon::Stamp,
        Icon::Target,
        Icon::Undo,
        Icon::Redo,
        Icon::Export,
        Icon::Send,
        Icon::Save,
        Icon::Open,
        Icon::New,
        Icon::Plus,
        Icon::Minus,
        Icon::Close,
        Icon::Check,
        Icon::Eye,
        Icon::EyeOff,
        Icon::Lock,
        Icon::Unlock,
        Icon::Grip,
        Icon::Folder,
        Icon::Layers,
        Icon::PaintLayer,
        Icon::FillLayer,
        Icon::Mask,
        Icon::Wand,
        Icon::Search,
        Icon::Gear,
        Icon::Help,
        Icon::Keyboard,
        Icon::Command,
        Icon::History,
        Icon::Sun,
        Icon::Moon,
        Icon::Glow,
        Icon::Frame,
        Icon::Orbit,
        Icon::Grid,
        Icon::ChevronRight,
        Icon::ChevronDown,
        Icon::More,
        Icon::Trash,
        Icon::Duplicate,
        Icon::Warning,
        Icon::Info,
        Icon::Error,
        Icon::Success,
        Icon::Dice,
        Icon::Image,
        Icon::Cube,
        Icon::Parts,
        Icon::Rain,
        Icon::Palette,
        Icon::Sliders,
        Icon::Tile,
        Icon::Trim,
        Icon::Atlas,
        Icon::Window,
        Icon::Sparkle,
        Icon::Play,
        Icon::Scatter,
        Icon::Leaf,
    ];

    pub fn name(self) -> String {
        format!("{self:?}")
    }

    /// Paint the icon centred in `rect` (a square of the icon size).
    pub fn paint(self, painter: &Painter, rect: Rect, color: Color32) {
        let pen = Pen { p: painter, o: rect.min, k: rect.width().min(rect.height()) / 18.0, c: color };
        pen.draw(self);
    }

    /// Allocate an icon-sized spot and paint it.
    pub fn show(self, ui: &mut egui::Ui, size: f32, color: Color32) -> egui::Response {
        let (r, resp) = ui.allocate_exact_size(vec2(size, size), egui::Sense::hover());
        self.paint(ui.painter(), r, color);
        resp
    }
}

struct Pen<'a> {
    p: &'a Painter,
    o: Pos2,
    k: f32,
    c: Color32,
}

impl Pen<'_> {
    fn at(&self, x: f32, y: f32) -> Pos2 {
        self.o + vec2(x, y) * self.k
    }
    fn stroke(&self) -> Stroke {
        Stroke::new(super::icon::STROKE * self.k.max(0.6), self.c)
    }
    fn line(&self, a: (f32, f32), b: (f32, f32)) {
        self.p.line_segment([self.at(a.0, a.1), self.at(b.0, b.1)], self.stroke());
    }
    fn poly(&self, pts: &[(f32, f32)], closed: bool) {
        let pts: Vec<Pos2> = pts.iter().map(|p| self.at(p.0, p.1)).collect();
        if closed {
            self.p.add(Shape::closed_line(pts, self.stroke()));
        } else {
            self.p.add(Shape::line(pts, self.stroke()));
        }
    }
    fn fill(&self, pts: &[(f32, f32)]) {
        let pts: Vec<Pos2> = pts.iter().map(|p| self.at(p.0, p.1)).collect();
        self.p.add(Shape::convex_polygon(pts, self.c, Stroke::NONE));
    }
    fn circle(&self, c: (f32, f32), r: f32) {
        self.p.circle_stroke(self.at(c.0, c.1), r * self.k, self.stroke());
    }
    fn dot(&self, c: (f32, f32), r: f32) {
        self.p.circle_filled(self.at(c.0, c.1), r * self.k, self.c);
    }
    fn rect(&self, a: (f32, f32), b: (f32, f32), r: f32) {
        let rr = Rect::from_min_max(self.at(a.0, a.1), self.at(b.0, b.1));
        self.p.rect_stroke(rr, egui::CornerRadius::same((r * self.k) as u8), self.stroke(), egui::StrokeKind::Middle);
    }
    fn fill_rect(&self, a: (f32, f32), b: (f32, f32), r: f32) {
        let rr = Rect::from_min_max(self.at(a.0, a.1), self.at(b.0, b.1));
        self.p.rect_filled(rr, egui::CornerRadius::same((r * self.k) as u8), self.c);
    }
    /// Arc from angle a0 to a1 (radians, 0 = +x, clockwise on screen).
    fn arc(&self, c: (f32, f32), r: f32, a0: f32, a1: f32) {
        let n = (((a1 - a0).abs() / TAU) * 32.0).ceil().max(4.0) as usize;
        let pts: Vec<(f32, f32)> = (0..=n).map(|i| a0 + (a1 - a0) * i as f32 / n as f32).map(|a| (c.0 + r * a.cos(), c.1 + r * a.sin())).collect();
        self.poly(&pts, false);
    }
    fn arrow_head(&self, tip: (f32, f32), dir: (f32, f32), s: f32) {
        let l = (dir.0 * dir.0 + dir.1 * dir.1).sqrt().max(1e-4);
        let (dx, dy) = (dir.0 / l, dir.1 / l);
        let (nx, ny) = (-dy, dx);
        self.poly(&[(tip.0 - dx * s + nx * s, tip.1 - dy * s + ny * s), tip, (tip.0 - dx * s - nx * s, tip.1 - dy * s - ny * s)], false);
    }

    fn draw(&self, icon: Icon) {
        use Icon::*;
        match icon {
            Brush => {
                self.poly(&[(15.5, 2.5), (8.5, 9.5), (10.5, 11.5), (15.5, 2.5)], true);
                self.poly(&[(8.0, 10.5), (5.5, 11.0), (4.0, 13.0), (3.0, 15.5), (6.0, 15.0), (8.0, 13.5), (9.0, 12.0)], true);
            }
            Eraser => {
                self.poly(&[(10.5, 3.0), (15.5, 8.0), (9.0, 14.5), (5.5, 14.5), (2.5, 11.5), (10.5, 3.0)], true);
                self.line((6.0, 7.5), (11.0, 12.5));
                self.line((9.0, 15.0), (15.5, 15.0));
            }
            Bucket => {
                self.poly(&[(3.0, 8.0), (8.5, 2.5), (14.0, 8.0), (8.5, 13.5)], true);
                self.line((3.0, 8.0), (14.0, 8.0));
                self.poly(&[(15.0, 10.5), (16.2, 13.0), (15.0, 14.6), (13.8, 13.0), (15.0, 10.5)], true);
            }
            Stamp => {
                self.rect((3.0, 3.0), (15.0, 15.0), 2.5);
                self.poly(&[(15.0, 10.0), (10.0, 15.0)], false);
                self.poly(&[(10.0, 15.0), (10.0, 11.5), (11.5, 10.0), (15.0, 10.0)], false);
                self.circle((7.0, 7.0), 1.5);
            }
            Target => {
                self.poly(&[(4.0, 3.0), (4.0, 13.5), (7.0, 10.8), (9.2, 15.0), (11.0, 14.0), (8.8, 9.9), (12.8, 9.6), (4.0, 3.0)], true);
            }
            Undo => {
                self.arc((10.0, 10.5), 5.0, -PI * 0.95, PI * 0.55);
                self.arrow_head((5.0, 10.0), (-0.1, 1.0), 2.6);
            }
            Redo => {
                self.arc((8.0, 10.5), 5.0, PI * 0.45, PI * 1.95);
                self.arrow_head((13.0, 10.0), (0.1, 1.0), 2.6);
            }
            Export => {
                self.poly(&[(6.0, 7.0), (3.5, 7.0), (3.5, 15.0), (14.5, 15.0), (14.5, 7.0), (12.0, 7.0)], false);
                self.line((9.0, 11.0), (9.0, 2.5));
                self.arrow_head((9.0, 2.5), (0.0, -1.0), 2.8);
            }
            Send => {
                self.poly(&[(2.5, 8.5), (15.5, 3.0), (11.0, 15.5), (8.5, 10.0), (2.5, 8.5)], true);
                self.line((8.5, 10.0), (15.5, 3.0));
            }
            Save => {
                self.poly(&[(3.0, 3.0), (12.5, 3.0), (15.0, 5.5), (15.0, 15.0), (3.0, 15.0), (3.0, 3.0)], true);
                self.rect((6.0, 3.0), (11.5, 6.5), 0.5);
                self.rect((5.5, 10.0), (12.5, 15.0), 0.5);
            }
            Open => {
                self.poly(&[(2.5, 14.5), (2.5, 4.0), (7.0, 4.0), (8.5, 5.5), (14.0, 5.5), (14.0, 8.0)], false);
                self.poly(&[(2.5, 14.5), (5.0, 8.0), (16.0, 8.0), (13.5, 14.5), (2.5, 14.5)], true);
            }
            New => {
                self.poly(&[(4.0, 2.5), (10.5, 2.5), (14.0, 6.0), (14.0, 15.5), (4.0, 15.5), (4.0, 2.5)], true);
                self.line((9.0, 7.5), (9.0, 12.5));
                self.line((6.5, 10.0), (11.5, 10.0));
            }
            Plus => {
                self.line((9.0, 3.5), (9.0, 14.5));
                self.line((3.5, 9.0), (14.5, 9.0));
            }
            Minus => self.line((3.5, 9.0), (14.5, 9.0)),
            Close => {
                self.line((4.5, 4.5), (13.5, 13.5));
                self.line((13.5, 4.5), (4.5, 13.5));
            }
            Check => self.poly(&[(3.5, 9.5), (7.5, 13.5), (14.5, 4.5)], false),
            Eye => {
                self.arc((9.0, 15.0), 9.0, -PI * 0.82, -PI * 0.18);
                self.arc((9.0, 3.0), 9.0, PI * 0.18, PI * 0.82);
                self.circle((9.0, 9.0), 2.4);
            }
            EyeOff => {
                self.arc((9.0, 15.0), 9.0, -PI * 0.82, -PI * 0.18);
                self.arc((9.0, 3.0), 9.0, PI * 0.18, PI * 0.82);
                self.line((3.5, 14.5), (14.5, 3.5));
            }
            Lock => {
                self.rect((4.0, 8.0), (14.0, 15.5), 1.5);
                self.arc((9.0, 8.0), 3.2, PI, TAU);
                self.dot((9.0, 11.8), 1.0);
            }
            Unlock => {
                self.rect((4.0, 8.0), (14.0, 15.5), 1.5);
                self.arc((9.0, 6.0), 3.2, PI, TAU - 0.3);
                self.line((5.8, 6.0), (5.8, 8.0));
                self.dot((9.0, 11.8), 1.0);
            }
            Grip => {
                for y in [5.0, 9.0, 13.0] {
                    self.dot((6.8, y), 1.15);
                    self.dot((11.2, y), 1.15);
                }
            }
            Folder => self.poly(&[(2.5, 14.5), (2.5, 4.0), (7.0, 4.0), (8.5, 5.8), (15.5, 5.8), (15.5, 14.5), (2.5, 14.5)], true),
            Layers => {
                self.poly(&[(9.0, 2.5), (16.0, 6.5), (9.0, 10.5), (2.0, 6.5), (9.0, 2.5)], true);
                self.poly(&[(2.0, 9.5), (9.0, 13.5), (16.0, 9.5)], false);
                self.poly(&[(2.0, 12.5), (9.0, 16.0), (16.0, 12.5)], false);
            }
            PaintLayer => {
                self.rect((2.5, 2.5), (15.5, 15.5), 2.5);
                self.poly(&[(5.0, 12.5), (7.5, 8.0), (9.5, 11.0), (13.0, 5.5)], false);
            }
            FillLayer => {
                self.rect((2.5, 2.5), (15.5, 15.5), 2.5);
                self.fill_rect((5.0, 9.0), (13.0, 13.0), 1.0);
            }
            Mask => {
                self.rect((2.5, 2.5), (15.5, 15.5), 2.5);
                self.p.circle_filled(self.at(9.0, 9.0), 4.0 * self.k, self.c);
            }
            Wand => {
                self.line((3.0, 15.0), (11.5, 6.5));
                self.line((13.0, 2.0), (13.0, 5.0));
                self.line((11.5, 3.5), (14.5, 3.5));
                self.line((15.5, 7.5), (15.5, 9.5));
                self.line((14.5, 8.5), (16.5, 8.5));
                self.dot((8.5, 3.5), 0.9);
            }
            Search => {
                self.circle((7.8, 7.8), 4.8);
                self.line((11.3, 11.3), (15.5, 15.5));
            }
            Gear => {
                self.circle((9.0, 9.0), 2.3);
                for i in 0..8 {
                    let a = i as f32 * TAU / 8.0;
                    self.line((9.0 + 4.6 * a.cos(), 9.0 + 4.6 * a.sin()), (9.0 + 6.6 * a.cos(), 9.0 + 6.6 * a.sin()));
                }
                self.circle((9.0, 9.0), 4.6);
            }
            Help => {
                self.circle((9.0, 9.0), 7.0);
                self.arc((9.0, 7.2), 2.3, PI * 1.05, PI * 2.35);
                self.line((9.0, 9.6), (9.0, 10.6));
                self.dot((9.0, 13.0), 1.0);
            }
            Keyboard => {
                self.rect((1.5, 4.5), (16.5, 13.5), 2.0);
                for x in [4.5, 7.5, 10.5, 13.5] {
                    self.dot((x, 7.5), 0.8);
                }
                self.line((5.5, 10.6), (12.5, 10.6));
            }
            Command => {
                self.rect((2.5, 4.0), (15.5, 14.0), 2.0);
                self.poly(&[(5.0, 7.0), (7.5, 9.0), (5.0, 11.0)], false);
                self.line((9.0, 11.0), (12.5, 11.0));
            }
            History => {
                self.arc((9.0, 9.0), 6.5, -PI * 0.9, PI * 1.0);
                self.arrow_head((2.6, 7.2), (-0.3, 1.0), 2.2);
                self.poly(&[(9.0, 5.5), (9.0, 9.0), (11.5, 10.5)], false);
            }
            Sun => {
                self.circle((9.0, 9.0), 3.2);
                for i in 0..8 {
                    let a = i as f32 * TAU / 8.0;
                    self.line((9.0 + 5.2 * a.cos(), 9.0 + 5.2 * a.sin()), (9.0 + 7.0 * a.cos(), 9.0 + 7.0 * a.sin()));
                }
            }
            Moon => {
                self.arc((9.0, 9.0), 6.5, -PI * 0.15, PI * 1.35);
                self.arc((12.5, 6.0), 5.0, PI * 0.42, PI * 1.12);
            }
            Glow => {
                self.dot((9.0, 9.0), 2.6);
                self.circle((9.0, 9.0), 5.0);
                for i in 0..4 {
                    let a = i as f32 * FRAC_PI_2 + PI / 4.0;
                    self.line((9.0 + 6.5 * a.cos(), 9.0 + 6.5 * a.sin()), (9.0 + 7.8 * a.cos(), 9.0 + 7.8 * a.sin()));
                }
            }
            Frame => {
                self.poly(&[(2.5, 6.5), (2.5, 2.5), (6.5, 2.5)], false);
                self.poly(&[(11.5, 2.5), (15.5, 2.5), (15.5, 6.5)], false);
                self.poly(&[(15.5, 11.5), (15.5, 15.5), (11.5, 15.5)], false);
                self.poly(&[(6.5, 15.5), (2.5, 15.5), (2.5, 11.5)], false);
                self.circle((9.0, 9.0), 2.5);
            }
            Orbit => {
                self.circle((9.0, 9.0), 2.5);
                self.arc((9.0, 9.0), 6.8, -PI * 0.8, PI * 0.6);
                self.arrow_head((5.1, 14.5), (-1.0, -0.6), 2.2);
            }
            Grid => {
                self.rect((2.5, 2.5), (7.8, 7.8), 1.5);
                self.rect((10.2, 2.5), (15.5, 7.8), 1.5);
                self.rect((2.5, 10.2), (7.8, 15.5), 1.5);
                self.rect((10.2, 10.2), (15.5, 15.5), 1.5);
            }
            ChevronRight => self.poly(&[(7.0, 4.0), (12.0, 9.0), (7.0, 14.0)], false),
            ChevronDown => self.poly(&[(4.0, 7.0), (9.0, 12.0), (14.0, 7.0)], false),
            More => {
                for x in [4.0, 9.0, 14.0] {
                    self.dot((x, 9.0), 1.4);
                }
            }
            Trash => {
                self.line((2.5, 4.5), (15.5, 4.5));
                self.poly(&[(7.0, 4.5), (7.0, 2.5), (11.0, 2.5), (11.0, 4.5)], false);
                self.poly(&[(4.0, 4.5), (5.0, 15.5), (13.0, 15.5), (14.0, 4.5)], false);
                self.line((7.5, 7.5), (7.5, 12.5));
                self.line((10.5, 7.5), (10.5, 12.5));
            }
            Duplicate => {
                self.rect((6.0, 6.0), (15.5, 15.5), 2.0);
                self.poly(&[(12.0, 4.0), (12.0, 2.5), (2.5, 2.5), (2.5, 12.0), (4.0, 12.0)], false);
            }
            Warning => {
                self.poly(&[(9.0, 2.5), (16.0, 15.0), (2.0, 15.0), (9.0, 2.5)], true);
                self.line((9.0, 7.0), (9.0, 10.5));
                self.dot((9.0, 12.8), 1.0);
            }
            Info => {
                self.circle((9.0, 9.0), 7.0);
                self.line((9.0, 8.0), (9.0, 12.8));
                self.dot((9.0, 5.4), 1.0);
            }
            Error => {
                self.circle((9.0, 9.0), 7.0);
                self.line((6.3, 6.3), (11.7, 11.7));
                self.line((11.7, 6.3), (6.3, 11.7));
            }
            Success => {
                self.circle((9.0, 9.0), 7.0);
                self.poly(&[(5.8, 9.3), (8.2, 11.6), (12.4, 6.6)], false);
            }
            Dice => {
                self.rect((2.5, 2.5), (15.5, 15.5), 3.0);
                for (x, y) in [(6.0, 6.0), (12.0, 12.0), (9.0, 9.0), (12.0, 6.0), (6.0, 12.0)] {
                    self.dot((x, y), 1.1);
                }
            }
            Image => {
                self.rect((2.5, 3.5), (15.5, 14.5), 2.0);
                self.poly(&[(2.5, 12.5), (7.0, 8.5), (10.5, 11.5), (12.5, 9.5), (15.5, 12.0)], false);
                self.circle((11.8, 6.8), 1.3);
            }
            Cube => {
                self.poly(&[(9.0, 2.0), (15.5, 5.5), (15.5, 12.5), (9.0, 16.0), (2.5, 12.5), (2.5, 5.5), (9.0, 2.0)], true);
                self.poly(&[(2.5, 5.5), (9.0, 9.0), (15.5, 5.5)], false);
                self.line((9.0, 9.0), (9.0, 16.0));
            }
            Parts => {
                self.poly(&[(9.0, 2.0), (15.5, 5.5), (9.0, 9.0), (2.5, 5.5), (9.0, 2.0)], true);
                self.fill(&[(2.5, 8.0), (8.0, 11.0), (8.0, 16.0), (2.5, 13.0)]);
                self.poly(&[(10.0, 11.0), (15.5, 8.0), (15.5, 13.0), (10.0, 16.0), (10.0, 11.0)], true);
            }
            Rain => {
                self.arc((7.0, 8.0), 3.5, PI, TAU * 0.93);
                self.arc((11.5, 7.5), 3.8, PI * 1.2, TAU * 1.05);
                self.line((3.5, 11.0), (15.0, 11.0));
                self.arc((3.5, 8.0), 3.0, FRAC_PI_2, PI * 1.3);
                self.line((6.0, 13.0), (5.0, 16.0));
                self.line((9.5, 13.0), (8.5, 16.0));
                self.line((13.0, 13.0), (12.0, 16.0));
            }
            Palette => {
                self.arc((9.0, 9.0), 7.0, PI * 0.35, PI * 2.1);
                self.poly(&[(13.0, 14.7), (11.0, 12.5), (12.5, 11.0), (15.6, 11.2)], false);
                self.dot((6.0, 7.0), 1.1);
                self.dot((9.5, 5.2), 1.1);
                self.dot((12.5, 7.5), 1.1);
                self.dot((5.5, 11.0), 1.1);
            }
            Sliders => {
                for (y, x) in [(4.5, 11.5), (9.0, 6.0), (13.5, 12.5)] {
                    self.line((2.5, y), (15.5, y));
                    self.p.circle_filled(self.at(x, y), 2.0 * self.k, self.c);
                }
            }
            Tile => {
                self.rect((2.5, 2.5), (15.5, 15.5), 1.0);
                self.line((9.0, 2.5), (9.0, 15.5));
                self.line((2.5, 9.0), (15.5, 9.0));
                self.dot((5.7, 5.7), 1.0);
                self.dot((12.3, 12.3), 1.0);
            }
            Trim => {
                self.rect((2.5, 2.5), (15.5, 15.5), 1.0);
                self.line((2.5, 6.0), (15.5, 6.0));
                self.line((2.5, 8.5), (15.5, 8.5));
                self.line((2.5, 12.5), (15.5, 12.5));
            }
            Atlas => {
                self.rect((2.5, 2.5), (9.5, 9.5), 1.0);
                self.rect((11.0, 2.5), (15.5, 7.0), 1.0);
                self.rect((11.0, 8.5), (15.5, 15.5), 1.0);
                self.rect((2.5, 11.0), (9.5, 15.5), 1.0);
            }
            Window => {
                self.rect((2.0, 3.0), (16.0, 15.0), 2.0);
                self.line((2.0, 6.5), (16.0, 6.5));
                self.line((7.5, 6.5), (7.5, 15.0));
            }
            Sparkle => {
                self.fill(&[(9.0, 2.0), (10.6, 7.4), (16.0, 9.0), (10.6, 10.6), (9.0, 16.0), (7.4, 10.6), (2.0, 9.0), (7.4, 7.4)]);
            }
            Play => self.fill(&[(5.0, 3.0), (15.0, 9.0), (5.0, 15.0)]),
            Scatter => {
                self.rect((2.5, 3.0), (7.5, 7.0), 1.0);
                self.rect((10.5, 2.0), (15.5, 6.0), 1.0);
                self.rect((6.0, 10.0), (11.0, 14.0), 1.0);
                self.dot((14.0, 12.0), 1.1);
                self.dot((3.5, 13.5), 1.1);
            }
            Leaf => {
                // a leaf blade with its midrib and stalk
                self.poly(&[(3.5, 14.5), (4.0, 9.0), (7.0, 5.0), (11.5, 3.0), (15.0, 3.0), (14.8, 7.0), (12.5, 11.5), (8.5, 14.0), (3.5, 14.5)], true);
                self.line((2.5, 15.5), (12.5, 5.5));
                self.line((8.0, 10.0), (8.2, 6.5));
                self.line((10.0, 8.0), (12.8, 8.2));
            }
        }
    }
}

/// A spinner (progress of unknown length) in `rect`.
pub fn spinner(painter: &Painter, rect: Rect, color: Color32, time: f64) {
    let c = rect.center();
    let r = rect.width().min(rect.height()) * 0.4;
    let start = (time * 4.0) as f32;
    let n = 24;
    let pts: Vec<Pos2> = (0..=n).map(|i| start + 4.4 * i as f32 / n as f32).map(|a| pos2(c.x + r * a.cos(), c.y + r * a.sin())).collect();
    painter.add(Shape::line(pts, Stroke::new((r * 0.28).max(1.5), color)));
}
