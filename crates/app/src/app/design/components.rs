//! The component library. Every control has the same states: rest, hover,
//! pressed (active), focused (keyboard focus ring), selected and disabled,
//! all drawn from the palette in `design::theme`.

use super::*;
use egui::{pos2, vec2, Align2, Color32, CornerRadius, FontId, Rect, Response, RichText, Sense, Stroke, StrokeKind, Ui, Widget};

fn cr(r: u8) -> CornerRadius {
    CornerRadius::same(r)
}

/// Text in the UI font at a type-scale size.
pub fn text(s: impl Into<String>, size: f32) -> RichText {
    RichText::new(s).font(fonts::regular(size))
}

pub fn strong(s: impl Into<String>, size: f32) -> RichText {
    RichText::new(s).font(fonts::semibold(size))
}

pub fn muted(ui: &Ui, s: impl Into<String>) -> RichText {
    RichText::new(s).font(fonts::regular(font::SMALL)).color(pal(ui).text_muted)
}

pub fn caption(ui: &Ui, s: impl Into<String>) -> RichText {
    RichText::new(s.into().to_uppercase()).font(fonts::semibold(font::CAPTION)).color(pal(ui).text_muted)
}

pub fn mono(s: impl Into<String>) -> RichText {
    RichText::new(s).font(fonts::mono(font::MONO))
}

/// A wrapped muted paragraph.
pub fn hint(ui: &mut Ui, s: impl Into<String>) -> Response {
    let t = muted(ui, s);
    ui.add(egui::Label::new(t).wrap())
}

/// Section header: caption text, optional trailing content.
pub fn section(ui: &mut Ui, title: &str) {
    ui.add_space(space::SM);
    ui.label(caption(ui, title));
    ui.add_space(space::XXS);
}

pub fn section_with<R>(ui: &mut Ui, title: &str, trailing: impl FnOnce(&mut Ui) -> R) -> R {
    ui.add_space(space::SM);
    ui.horizontal(|ui| {
        ui.label(caption(ui, title));
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), trailing).inner
    })
    .inner
}

fn focus_ring(ui: &Ui, resp: &Response, rect: Rect, r: u8) {
    if resp.has_focus() {
        ui.painter().rect_stroke(rect.expand(2.0), cr(r.saturating_add(2)), Stroke::new(2.0, pal(ui).focus), StrokeKind::Outside);
    }
}

// ------------------------------------------------------------------ buttons

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BtnKind {
    Primary,
    Secondary,
    Ghost,
    Danger,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BtnSize {
    Sm,
    Md,
    Lg,
}

/// A button: primary (one per screen), secondary, ghost or danger, with an
/// optional leading icon and trailing shortcut hint.
pub struct Btn {
    kind: BtnKind,
    size: BtnSize,
    label: String,
    icon: Option<Icon>,
    shortcut: Option<String>,
    selected: bool,
    enabled: bool,
    min_width: f32,
    fill_width: bool,
}

impl Btn {
    pub fn new(kind: BtnKind, label: impl Into<String>) -> Btn {
        Btn { kind, size: BtnSize::Md, label: label.into(), icon: None, shortcut: None, selected: false, enabled: true, min_width: 0.0, fill_width: false }
    }
    pub fn primary(label: impl Into<String>) -> Btn {
        Btn::new(BtnKind::Primary, label)
    }
    pub fn secondary(label: impl Into<String>) -> Btn {
        Btn::new(BtnKind::Secondary, label)
    }
    pub fn ghost(label: impl Into<String>) -> Btn {
        Btn::new(BtnKind::Ghost, label)
    }
    pub fn danger(label: impl Into<String>) -> Btn {
        Btn::new(BtnKind::Danger, label)
    }
    pub fn icon(mut self, i: Icon) -> Btn {
        self.icon = Some(i);
        self
    }
    pub fn shortcut(mut self, s: impl Into<String>) -> Btn {
        self.shortcut = Some(s.into());
        self
    }
    pub fn size(mut self, s: BtnSize) -> Btn {
        self.size = s;
        self
    }
    pub fn small(self) -> Btn {
        self.size(BtnSize::Sm)
    }
    pub fn large(self) -> Btn {
        self.size(BtnSize::Lg)
    }
    pub fn selected(mut self, on: bool) -> Btn {
        self.selected = on;
        self
    }
    pub fn enabled(mut self, on: bool) -> Btn {
        self.enabled = on;
        self
    }
    pub fn min_width(mut self, w: f32) -> Btn {
        self.min_width = w;
        self
    }
    pub fn fill(mut self) -> Btn {
        self.fill_width = true;
        self
    }
}

impl Widget for Btn {
    fn ui(self, ui: &mut Ui) -> Response {
        let p = pal(ui);
        let (h, fs, pad, isz) = match self.size {
            BtnSize::Sm => (size::CONTROL_H_SM, font::SMALL, space::MD, icon::SM),
            BtnSize::Md => (size::CONTROL_H, font::BODY, space::LG, icon::SM + 1.0),
            BtnSize::Lg => (size::TOOL + 4.0, font::TITLE, space::XL, icon::MD),
        };
        let fid = if self.kind == BtnKind::Primary { fonts::semibold(fs) } else { fonts::regular(fs) };
        let galley = ui.painter().layout_no_wrap(self.label.clone(), fid, Color32::PLACEHOLDER);
        let sc = self.shortcut.as_ref().map(|s| ui.painter().layout_no_wrap(s.clone(), fonts::regular(font::CAPTION), Color32::PLACEHOLDER));
        let gap = space::SM;
        let mut w = pad * 2.0 + galley.size().x;
        if self.icon.is_some() {
            w += isz + if self.label.is_empty() { 0.0 } else { gap };
        }
        if let Some(sc) = &sc {
            w += sc.size().x + space::LG;
        }
        if self.label.is_empty() && self.icon.is_some() {
            w = h;
        }
        let w = if self.fill_width { ui.available_width() } else { w.max(self.min_width) };
        let sense = if self.enabled { Sense::click() } else { Sense::hover() };
        let (rect, resp) = ui.allocate_exact_size(vec2(w, h), sense);
        if ui.is_rect_visible(rect) {
            let (hov, down) = (resp.hovered() && self.enabled, resp.is_pointer_button_down_on() && self.enabled);
            let (bg, fg, border) = match self.kind {
                BtnKind::Primary => (if down { p.accent_pressed } else if hov { p.accent_hover } else { p.accent }, p.on_accent, Color32::TRANSPARENT),
                BtnKind::Secondary => (
                    if down || self.selected { p.accent_subtle } else if hov { p.surface_hover } else { p.surface_raised },
                    p.text,
                    if self.selected { p.accent } else { p.border },
                ),
                BtnKind::Ghost => (
                    if down || self.selected { p.accent_subtle } else if hov { p.surface_hover } else { Color32::TRANSPARENT },
                    if self.selected { p.accent } else { p.text_secondary },
                    Color32::TRANSPARENT,
                ),
                BtnKind::Danger => (if down { p.danger.gamma_multiply(0.8) } else if hov { p.danger } else { p.danger.gamma_multiply(0.18) }, if hov || down { p.on_accent } else { p.danger }, p.danger.gamma_multiply(0.5)),
            };
            let (bg, fg) = if self.enabled { (bg, fg) } else { (bg.gamma_multiply(0.5), p.text_disabled) };
            ui.painter().rect(rect, cr(radius::MD), bg, Stroke::new(1.0, border), StrokeKind::Inside);
            let content_w = if self.label.is_empty() { isz } else { galley.size().x + self.icon.map_or(0.0, |_| isz + gap) };
            let mut x = if self.label.is_empty() || self.fill_width || self.min_width > 0.0 { rect.center().x - content_w / 2.0 } else { rect.left() + pad };
            if sc.is_some() && !self.fill_width {
                x = rect.left() + pad;
            }
            if let Some(i) = self.icon {
                let ir = Rect::from_center_size(pos2(x + isz / 2.0, rect.center().y), vec2(isz, isz));
                i.paint(ui.painter(), ir, fg);
                x += isz + gap;
            }
            ui.painter().galley(pos2(x, rect.center().y - galley.size().y / 2.0), galley, fg);
            if let Some(sc) = sc {
                let c = if self.kind == BtnKind::Primary { fg.gamma_multiply(0.7) } else { p.text_muted };
                ui.painter().galley(pos2(rect.right() - pad - sc.size().x, rect.center().y - sc.size().y / 2.0), sc, c);
            }
            focus_ring(ui, &resp, rect, radius::MD);
        }
        resp
    }
}

/// A square icon-only button with a tooltip (and the shortcut in it).
pub struct IconBtn {
    icon: Icon,
    tip: String,
    shortcut: Option<String>,
    selected: bool,
    enabled: bool,
    size: f32,
    tint: Option<Color32>,
}

impl IconBtn {
    pub fn new(icon: Icon, tip: impl Into<String>) -> IconBtn {
        IconBtn { icon, tip: tip.into(), shortcut: None, selected: false, enabled: true, size: size::CONTROL_H, tint: None }
    }
    pub fn shortcut(mut self, s: impl Into<String>) -> IconBtn {
        self.shortcut = Some(s.into());
        self
    }
    pub fn selected(mut self, on: bool) -> IconBtn {
        self.selected = on;
        self
    }
    pub fn enabled(mut self, on: bool) -> IconBtn {
        self.enabled = on;
        self
    }
    pub fn size(mut self, s: f32) -> IconBtn {
        self.size = s;
        self
    }
    pub fn tint(mut self, c: Color32) -> IconBtn {
        self.tint = Some(c);
        self
    }
}

impl Widget for IconBtn {
    fn ui(self, ui: &mut Ui) -> Response {
        let p = pal(ui);
        let (rect, resp) = ui.allocate_exact_size(vec2(self.size, self.size), if self.enabled { Sense::click() } else { Sense::hover() });
        let hov = resp.hovered() && self.enabled;
        let bg = if self.selected || resp.is_pointer_button_down_on() { p.accent_subtle } else if hov { p.surface_hover } else { Color32::TRANSPARENT };
        ui.painter().rect_filled(rect, cr(radius::MD), bg);
        let fg = if !self.enabled {
            p.text_disabled
        } else if self.selected {
            p.accent
        } else {
            self.tint.unwrap_or(if hov { p.text } else { p.text_secondary })
        };
        let isz = (self.size * 0.6).min(icon::LG);
        self.icon.paint(ui.painter(), Rect::from_center_size(rect.center(), vec2(isz, isz)), fg);
        focus_ring(ui, &resp, rect, radius::MD);
        let (tip, sc) = (self.tip, self.shortcut);
        if tip.is_empty() {
            return resp;
        }
        resp.on_hover_ui(|ui| tooltip_body(ui, &tip, None, sc.as_deref()))
    }
}

/// A tool button for the tool rail: big icon, label under it, shortcut in the tooltip.
pub fn tool_button(ui: &mut Ui, icon: Icon, label: &str, tip: &str, shortcut: &str, selected: bool) -> Response {
    let p = pal(ui);
    let w = size::TOOL + space::LG;
    let (rect, resp) = ui.allocate_exact_size(vec2(w, size::TOOL + space::LG + 2.0), Sense::click());
    let hov = resp.hovered();
    let bg = if selected { p.accent_subtle } else if hov { p.surface_hover } else { Color32::TRANSPARENT };
    ui.painter().rect_filled(rect, cr(radius::LG), bg);
    if selected {
        let bar = Rect::from_min_size(pos2(rect.left(), rect.top() + space::MD), vec2(3.0, rect.height() - space::MD * 2.0));
        ui.painter().rect_filled(bar, cr(radius::SM), p.accent);
    }
    let fg = if selected { p.accent } else if hov { p.text } else { p.text_secondary };
    let ir = Rect::from_center_size(pos2(rect.center().x, rect.top() + space::SM + icon::MD / 2.0 + 2.0), vec2(icon::MD + 2.0, icon::MD + 2.0));
    icon.paint(ui.painter(), ir, fg);
    ui.painter().text(pos2(rect.center().x, rect.bottom() - space::SM), Align2::CENTER_BOTTOM, label, fonts::regular(font::CAPTION), fg);
    focus_ring(ui, &resp, rect, radius::LG);
    resp.on_hover_ui(|ui| tooltip_body(ui, label, Some(tip), Some(shortcut).filter(|s| !s.is_empty())))
}

/// Key cap.
pub fn kbd(ui: &mut Ui, keys: &str) -> Response {
    let p = pal(ui);
    let g = ui.painter().layout_no_wrap(keys.to_string(), fonts::mono(font::SMALL), p.text_secondary);
    let (rect, resp) = ui.allocate_exact_size(g.size() + vec2(space::MD * 1.5, space::XS * 1.5), Sense::hover());
    ui.painter().rect(rect, cr(radius::SM), p.well, Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
    ui.painter().galley(rect.center() - g.size() / 2.0, g, p.text_secondary);
    resp
}

/// Rich tooltip: a title, optional body and shortcut.
pub fn tooltip_body(ui: &mut Ui, title: &str, body: Option<&str>, shortcut: Option<&str>) {
    ui.set_max_width(280.0);
    ui.horizontal(|ui| {
        ui.label(strong(title, font::BODY));
        if let Some(s) = shortcut {
            ui.add_space(space::SM);
            kbd(ui, s);
        }
    });
    if let Some(b) = body {
        hint(ui, b);
    }
}

pub trait RichTip {
    fn rich_tip(self, title: &str, body: &str) -> Self;
}

impl RichTip for Response {
    fn rich_tip(self, title: &str, body: &str) -> Response {
        self.on_hover_ui(|ui| tooltip_body(ui, title, Some(body), None))
    }
}

// ------------------------------------------------------------------ toggles

/// A switch with a label.
pub fn toggle(ui: &mut Ui, on: &mut bool, label: &str) -> Response {
    let p = pal(ui);
    let g = ui.painter().layout_no_wrap(label.to_string(), fonts::regular(font::BODY), p.text);
    let sw = vec2(30.0, 17.0);
    let (rect, mut resp) = ui.allocate_exact_size(vec2(sw.x + space::MD + g.size().x, size::CONTROL_H_SM), Sense::click());
    if resp.clicked() {
        *on = !*on;
        resp.mark_changed();
    }
    let t = ui.ctx().animate_bool_with_time(resp.id, *on, motion::FAST);
    let track = Rect::from_min_size(pos2(rect.left(), rect.center().y - sw.y / 2.0), sw);
    let bg = if *on { p.accent } else if resp.hovered() { p.border_strong } else { p.border };
    ui.painter().rect_filled(track, cr(radius::PILL), bg);
    let x = egui::lerp(track.left() + sw.y / 2.0..=track.right() - sw.y / 2.0, motion::ease_out(t));
    ui.painter().circle_filled(pos2(x, track.center().y), sw.y / 2.0 - 2.5, if *on { p.on_accent } else { p.text_secondary });
    ui.painter().galley(pos2(track.right() + space::MD, rect.center().y - g.size().y / 2.0), g, p.text);
    focus_ring(ui, &resp, track, radius::PILL);
    resp
}

/// Segmented control: one of several options. Returns true when changed.
pub fn segmented<T: PartialEq + Copy>(ui: &mut Ui, value: &mut T, options: &[(T, Option<Icon>, &str)]) -> bool {
    let p = pal(ui);
    let mut changed = false;
    let frame = egui::Frame::new().fill(p.well).corner_radius(cr(radius::MD)).inner_margin(egui::Margin::same(2)).stroke(Stroke::new(1.0, p.border));
    frame.show(ui, |ui| {
        ui.spacing_mut().item_spacing = vec2(space::XXS, space::XXS);
        ui.horizontal_wrapped(|ui| {
            for (v, ic, label) in options {
                let on = *value == *v;
                let g = ui.painter().layout_no_wrap(label.to_string(), if on { fonts::semibold(font::SMALL) } else { fonts::regular(font::SMALL) }, p.text);
                let w = g.size().x + space::LG * 2.0 + ic.map_or(0.0, |_| icon::SM + space::XS);
                let w = if label.is_empty() { size::CONTROL_H_SM + space::XS } else { w };
                let (rect, resp) = ui.allocate_exact_size(vec2(w, size::CONTROL_H_SM), Sense::click());
                let bg = if on { p.surface_hover } else if resp.hovered() { p.surface_raised } else { Color32::TRANSPARENT };
                ui.painter().rect_filled(rect, cr(radius::SM), bg);
                let fg = if on { p.text } else { p.text_muted };
                let mut x = rect.center().x - (w - space::LG * 2.0) / 2.0;
                if label.is_empty() {
                    x = rect.center().x - icon::SM / 2.0;
                }
                if let Some(i) = ic {
                    i.paint(ui.painter(), Rect::from_min_size(pos2(x, rect.center().y - icon::SM / 2.0), vec2(icon::SM, icon::SM)), if on { p.accent } else { fg });
                    x += icon::SM + space::XS;
                }
                ui.painter().galley(pos2(x, rect.center().y - g.size().y / 2.0), g, fg);
                if resp.clicked() && !on {
                    *value = *v;
                    changed = true;
                }
            }
        });
    });
    changed
}

/// Underlined tabs. Returns true when changed.
pub fn tabs<T: PartialEq + Copy>(ui: &mut Ui, value: &mut T, options: &[(T, &str)]) -> bool {
    let p = pal(ui);
    let mut changed = false;
    ui.horizontal(|ui| {
        ui.spacing_mut().item_spacing.x = space::LG;
        for (v, label) in options {
            let on = *value == *v;
            let g = ui.painter().layout_no_wrap(label.to_string(), if on { fonts::semibold(font::BODY) } else { fonts::regular(font::BODY) }, p.text);
            let (rect, resp) = ui.allocate_exact_size(vec2(g.size().x, size::TAB_H - 2.0), Sense::click());
            let fg = if on { p.text } else if resp.hovered() { p.text_secondary } else { p.text_muted };
            ui.painter().galley(pos2(rect.left(), rect.center().y - g.size().y / 2.0), g, fg);
            if on {
                ui.painter().rect_filled(Rect::from_min_max(pos2(rect.left(), rect.bottom() - 2.0), rect.right_bottom()), cr(1), p.accent);
            }
            if resp.clicked() && !on {
                *value = *v;
                changed = true;
            }
        }
    });
    let r = ui.min_rect();
    ui.painter().hline(r.x_range(), r.bottom(), Stroke::new(1.0, p.border));
    changed
}

// ------------------------------------------------------------------ sliders

/// How a slider shows its value.
#[derive(Clone, Copy)]
pub enum Unit {
    Plain(usize),
    Percent,
    Suffix(&'static str, usize),
}

/// Labelled slider with an editable value field. Returns the slider response
/// (changed when either part changed).
pub fn slider_row(ui: &mut Ui, label: &str, v: &mut f32, range: std::ops::RangeInclusive<f32>, unit: Unit) -> Response {
    slider_row_ex(ui, label, v, range, unit, false, None)
}

pub fn slider_row_ex(ui: &mut Ui, label: &str, v: &mut f32, range: std::ops::RangeInclusive<f32>, unit: Unit, log: bool, tip: Option<&str>) -> Response {
    let p = pal(ui);
    ui.horizontal(|ui| {
        let lw = (ui.available_width() * 0.32).clamp(48.0, 96.0);
        let (lr, lresp) = ui.allocate_exact_size(vec2(lw, size::CONTROL_H_SM), Sense::hover());
        ui.painter().text(pos2(lr.left(), lr.center().y), Align2::LEFT_CENTER, label, fonts::regular(font::SMALL), p.text_secondary);
        if let Some(t) = tip {
            lresp.on_hover_ui(|ui| tooltip_body(ui, label, Some(t), None));
        }
        let field_w = 58.0;
        let sw = (ui.available_width() - field_w - ui.spacing().item_spacing.x * 2.0 - space::XS).max(40.0);
        ui.spacing_mut().slider_width = sw;
        let mut r = ui.add(egui::Slider::new(v, range.clone()).show_value(false).logarithmic(log));
        let dv = match unit {
            Unit::Percent => egui::DragValue::new(v).range(range).speed(0.005).custom_formatter(|x, _| format!("{:.0}%", x * 100.0)).custom_parser(|s| s.trim_end_matches('%').trim().parse::<f64>().ok().map(|x| x / 100.0)),
            Unit::Plain(d) => egui::DragValue::new(v).range(range).speed(0.01).fixed_decimals(d),
            Unit::Suffix(s, d) => egui::DragValue::new(v).range(range).speed(0.01).fixed_decimals(d).suffix(s),
        };
        let r2 = ui.add_sized([field_w, size::CONTROL_H_SM], dv);
        if r2.changed() {
            r.mark_changed();
        }
        r
    })
    .inner
}

// ------------------------------------------------------------------ swatches

/// A material-ish swatch: colour, sheen for metal, highlight for gloss,
/// glow ring for emission, checker for see-through.
pub fn paint_material_swatch(painter: &egui::Painter, rect: Rect, base: [f32; 3], rough: f32, metal: f32, emissive: f32, opacity: f32, r: u8) {
    let c = srgb(base);
    if opacity < 0.99 {
        let n = 4;
        let s = rect.width() / n as f32;
        for i in 0..n {
            for j in 0..n {
                let cell = Rect::from_min_size(rect.min + vec2(i as f32 * s, j as f32 * s), vec2(s, s));
                painter.rect_filled(cell, CornerRadius::ZERO, if (i + j) % 2 == 0 { Color32::from_gray(200) } else { Color32::from_gray(130) });
            }
        }
        painter.rect_filled(rect, cr(r), c.gamma_multiply(opacity.max(0.25)));
    } else {
        painter.rect_filled(rect, cr(r), c);
    }
    if metal > 0.5 {
        let a = rect.left_top() + vec2(rect.width() * 0.15, 0.0);
        let shine = Color32::from_white_alpha(((1.0 - rough) * 120.0) as u8 + 30);
        painter.with_clip_rect(rect).line_segment([a, a + vec2(rect.width() * 0.5, rect.height())], Stroke::new(rect.width() * 0.18, shine));
    } else if rough < 0.45 {
        painter.circle_filled(rect.left_top() + vec2(rect.width() * 0.3, rect.height() * 0.3), rect.width() * 0.12, Color32::from_white_alpha(90));
    }
    if emissive > 0.0 {
        painter.rect_stroke(rect.shrink(1.5), cr(r), Stroke::new(2.0, c.gamma_multiply(1.4)), StrokeKind::Inside);
    }
    painter.rect_stroke(rect, cr(r), Stroke::new(1.0, Color32::from_black_alpha(110)), StrokeKind::Inside);
}

/// A clickable colour swatch.
pub fn swatch(ui: &mut Ui, color: Color32, sz: f32, selected: bool) -> Response {
    let p = pal(ui);
    let (rect, resp) = ui.allocate_exact_size(vec2(sz, sz), Sense::click());
    ui.painter().rect_filled(rect, cr(radius::SM), color);
    ui.painter().rect_stroke(rect, cr(radius::SM), Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
    if selected || resp.hovered() {
        ui.painter().rect_stroke(rect.expand(2.0), cr(radius::MD), Stroke::new(1.5, if selected { p.accent } else { p.text_muted }), StrokeKind::Outside);
    }
    focus_ring(ui, &resp, rect, radius::SM);
    resp
}

/// Colour picker button for an sRGB 0..1 colour.
pub fn color_picker(ui: &mut Ui, c: &mut [f32; 3]) -> Response {
    let mut b = c.map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8);
    let r = ui.color_edit_button_srgb(&mut b);
    if r.changed() {
        *c = b.map(|v| v as f32 / 255.0);
    }
    r
}

// ------------------------------------------------------------------ surfaces

/// A card on a panel.
pub fn card<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> R {
    let p = pal(ui);
    egui::Frame::new()
        .fill(p.surface_raised)
        .corner_radius(cr(radius::LG))
        .inner_margin(egui::Margin::same(space::LG as i8))
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            add(ui)
        })
        .inner
}

/// A card that can be selected (accent border) and clicked.
pub fn card_selectable<R>(ui: &mut Ui, selected: bool, add: impl FnOnce(&mut Ui) -> R) -> (Response, R) {
    let p = pal(ui);
    let out = egui::Frame::new()
        .fill(if selected { p.accent_subtle } else { p.surface_raised })
        .stroke(Stroke::new(1.0, if selected { p.accent } else { p.border }))
        .corner_radius(cr(radius::LG))
        .inner_margin(egui::Margin::same(space::LG as i8))
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            add(ui)
        });
    let resp = out.response.interact(Sense::click());
    if resp.hovered() && !selected {
        ui.painter().rect_stroke(out.response.rect, cr(radius::LG), Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
    }
    (resp, out.inner)
}

/// A frame for floating things (popovers, toasts, the palette).
pub fn overlay_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.overlay).stroke(Stroke::new(1.0, p.border_strong)).corner_radius(cr(radius::LG)).shadow(elevation(2, p)).inner_margin(egui::Margin::same(space::LG as i8))
}

/// Translucent HUD chip frame over the viewport.
pub fn glass_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.glass).corner_radius(cr(radius::LG)).inner_margin(egui::Margin::same(space::XS as i8)).stroke(Stroke::new(1.0, p.border.gamma_multiply(0.6)))
}

/// Empty state: icon, title, explanation, optional action. Returns true if
/// the action was clicked.
pub fn empty_state(ui: &mut Ui, icon: Icon, title: &str, body: &str, action: Option<&str>) -> bool {
    let p = pal(ui);
    let mut clicked = false;
    ui.vertical_centered(|ui| {
        ui.add_space(space::XL);
        let (r, _) = ui.allocate_exact_size(vec2(icon::XL, icon::XL), Sense::hover());
        ui.painter().circle_filled(r.center(), icon::XL * 0.62, p.surface_raised);
        icon.paint(ui.painter(), r.shrink(space::SM), p.text_muted);
        ui.add_space(space::MD);
        ui.label(strong(title, font::TITLE));
        ui.add(egui::Label::new(muted(ui, body)).wrap());
        if let Some(a) = action {
            ui.add_space(space::SM);
            clicked = ui.add(Btn::secondary(a)).clicked();
        }
        ui.add_space(space::XL);
    });
    clicked
}

/// Progress: a bar for known fractions, a spinner otherwise.
pub fn progress(ui: &mut Ui, frac: Option<f32>, label: &str) {
    let p = pal(ui);
    ui.horizontal(|ui| {
        match frac {
            Some(f) => {
                let (rect, _) = ui.allocate_exact_size(vec2(120.0, 6.0), Sense::hover());
                ui.painter().rect_filled(rect, cr(radius::PILL), p.well);
                let mut fill = rect;
                fill.set_width(rect.width() * f.clamp(0.0, 1.0));
                ui.painter().rect_filled(fill, cr(radius::PILL), p.accent);
            }
            None => {
                let (rect, _) = ui.allocate_exact_size(vec2(icon::SM, icon::SM), Sense::hover());
                icons::spinner(ui.painter(), rect, p.accent, ui.input(|i| i.time));
                ui.ctx().request_repaint();
            }
        }
        ui.label(text(label, font::SMALL).color(p.text_secondary));
    });
}

/// Search field with an icon and a clear button.
pub fn search_field(ui: &mut Ui, query: &mut String, hint_text: &str) -> Response {
    let p = pal(ui);
    egui::Frame::new()
        .fill(p.well)
        .stroke(Stroke::new(1.0, p.border))
        .corner_radius(cr(radius::MD))
        .inner_margin(egui::Margin { left: space::MD as i8, right: space::XS as i8, top: space::XXS as i8, bottom: space::XXS as i8 })
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                Icon::Search.show(ui, icon::SM, p.text_muted);
                let w = ui.available_width() - if query.is_empty() { 0.0 } else { size::CONTROL_H_SM + space::XS };
                let r = ui.add(egui::TextEdit::singleline(query).hint_text(hint_text).frame(egui::Frame::NONE).desired_width(w));
                if !query.is_empty() && ui.add(IconBtn::new(Icon::Close, "Clear").size(size::CONTROL_H_SM)).clicked() {
                    query.clear();
                }
                r
            })
            .inner
        })
        .inner
}

/// Property inspector: label column + control column.
pub fn prop_grid<R>(ui: &mut Ui, id: &str, add: impl FnOnce(&mut Ui) -> R) -> R {
    ui.spacing_mut().slider_width = (ui.available_width() - 80.0 - space::LG - 64.0).clamp(60.0, 220.0);
    egui::Grid::new(id).num_columns(2).spacing([space::LG, space::SM]).min_col_width(80.0).show(ui, add).inner
}

/// A label for the property grid's first column, with an optional explanation on hover.
pub fn prop_label(ui: &mut Ui, label: &str, tip: Option<&str>) -> Response {
    let r = ui.label(text(label, font::SMALL).color(pal(ui).text_secondary));
    match tip {
        Some(t) => r.on_hover_ui(|ui| tooltip_body(ui, label, Some(t), None)),
        None => r,
    }
}

/// An asset tile: thumbnail (texture or a painter fallback), title, subtitle.
pub fn asset_tile(ui: &mut Ui, w: f32, thumb: Option<egui::TextureId>, fallback: impl FnOnce(&egui::Painter, Rect), title: &str, subtitle: &str, selected: bool) -> Response {
    asset_tile_ex(ui, w, w - space::XS * 2.0, thumb, fallback, title, subtitle, selected)
}

/// `asset_tile` with a thumbnail `img_h` points tall (wide previews), the image cropped to fit.
#[allow(clippy::too_many_arguments)]
pub fn asset_tile_ex(ui: &mut Ui, w: f32, img_h: f32, thumb: Option<egui::TextureId>, fallback: impl FnOnce(&egui::Painter, Rect), title: &str, subtitle: &str, selected: bool) -> Response {
    let p = pal(ui);
    let h = img_h + space::XS * 2.0 + 34.0;
    let (rect, resp) = ui.allocate_exact_size(vec2(w, h), Sense::click());
    if !ui.is_rect_visible(rect) {
        return resp;
    }
    let hov = resp.hovered();
    let bg = if selected { p.accent_subtle } else if hov { p.surface_hover } else { p.surface_raised };
    ui.painter().rect_filled(rect, cr(radius::LG), bg);
    let img = Rect::from_min_size(rect.min + vec2(space::XS, space::XS), vec2(w - space::XS * 2.0, img_h));
    match thumb {
        Some(t) => {
            let a = img.height() / img.width();
            let uv = if a < 1.0 { Rect::from_min_max(pos2(0.0, 0.5 - a / 2.0), pos2(1.0, 0.5 + a / 2.0)) } else { Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)) };
            ui.painter().image(t, img, uv, Color32::WHITE);
        }
        None => fallback(ui.painter(), img),
    }
    let tr = Rect::from_min_max(pos2(rect.left() + space::SM, img.bottom() + space::XS), pos2(rect.right() - space::XS, rect.bottom()));
    let title_g = ui.painter().layout(title.to_string(), fonts::semibold(font::SMALL), p.text, tr.width());
    let rows = title_g.rows.len();
    ui.painter().with_clip_rect(tr).galley(tr.min, title_g, p.text);
    if rows < 2 && !subtitle.is_empty() {
        ui.painter().with_clip_rect(tr).text(tr.min + vec2(0.0, 15.0), Align2::LEFT_TOP, subtitle, fonts::regular(font::CAPTION), p.text_muted);
    }
    let stroke = if selected { Stroke::new(1.5, p.accent) } else if hov { Stroke::new(1.0, p.border_strong) } else { Stroke::new(1.0, p.border) };
    ui.painter().rect_stroke(rect, cr(radius::LG), stroke, StrokeKind::Inside);
    focus_ring(ui, &resp, rect, radius::LG);
    resp
}

/// A small pill label.
pub fn badge(ui: &mut Ui, label: &str, color: Color32) -> Response {
    let g = ui.painter().layout_no_wrap(label.to_string(), fonts::semibold(font::CAPTION), color);
    let (rect, resp) = ui.allocate_exact_size(g.size() + vec2(space::MD * 1.5, space::XS), Sense::hover());
    ui.painter().rect_filled(rect, cr(radius::PILL), color.gamma_multiply(0.18));
    ui.painter().galley(rect.center() - g.size() / 2.0, g, color);
    resp
}

// ------------------------------------------------------------------ layer row

/// What to draw in a layer row.
pub struct LayerRow<'a> {
    pub id: egui::Id,
    pub depth: usize,
    pub name: &'a str,
    pub subtitle: &'a str,
    pub visible: bool,
    pub locked: bool,
    pub selected: bool,
    /// Effective visibility (a parent folder may hide it).
    pub shown: bool,
    pub folder: Option<bool>,
    pub mask: Option<(bool, bool)>,
    pub opacity: f32,
    pub thumb: &'a dyn Fn(&egui::Painter, Rect),
}

pub struct LayerRowResponse {
    pub clicked: bool,
    pub double_clicked: bool,
    pub toggle_visible: bool,
    pub toggle_lock: bool,
    pub toggle_collapse: bool,
    pub mask_clicked: bool,
    pub rect: Rect,
    pub handle: Option<Response>,
    pub context: Option<Response>,
}

/// The layer row: drag handle, (folder arrow), visibility, thumbnail, name +
/// what it is, lock, mask thumbnail. The handle is a drag source for `id`.
impl Default for LayerRowResponse {
    fn default() -> Self {
        LayerRowResponse { clicked: false, double_clicked: false, toggle_visible: false, toggle_lock: false, toggle_collapse: false, mask_clicked: false, rect: Rect::NOTHING, handle: None, context: None }
    }
}

pub fn layer_row<P: Send + Sync + 'static>(ui: &mut Ui, row: &LayerRow, payload: P) -> LayerRowResponse {
    let p = pal(ui);
    let mut out = LayerRowResponse::default();
    let w = ui.available_width();
    let (rect, resp) = ui.allocate_exact_size(vec2(w, size::ROW_H), Sense::click());
    out.rect = rect;
    if !ui.is_rect_visible(rect) {
        return out;
    }
    let hov = resp.hovered();
    let bg = if row.selected { p.accent_subtle } else if hov { p.surface_hover } else { p.surface_raised };
    ui.painter().rect(rect, cr(radius::MD), bg, if row.selected { Stroke::new(1.0, p.accent) } else { Stroke::NONE }, StrokeKind::Inside);
    let mut x = rect.left() + space::XS;
    let cy = rect.center().y;
    let small = |x: f32, s: f32| Rect::from_center_size(pos2(x + s / 2.0, cy), vec2(s, s));
    // drag handle
    let hr = Rect::from_min_size(pos2(x, rect.top()), vec2(16.0, rect.height()));
    let hresp = ui.interact(hr, row.id.with("handle"), Sense::drag());
    if hresp.drag_started() {
        hresp.dnd_set_drag_payload(payload);
    }
    let hc = if hresp.hovered() || hresp.dragged() { p.text } else { p.text_disabled };
    Icon::Grip.paint(ui.painter(), small(x, icon::SM), hc);
    if hresp.hovered() {
        ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
    }
    out.handle = Some(hresp);
    x += 16.0;
    // nesting guides
    for k in 0..row.depth {
        let gx = x + 6.0 + 14.0 * k as f32;
        ui.painter().vline(gx, rect.y_range().shrink(space::XS), Stroke::new(1.0, p.border_strong));
    }
    x += 14.0 * row.depth as f32;
    // folder arrow
    if let Some(collapsed) = row.folder {
        let r = small(x, icon::SM);
        let a = ui.interact(r.expand(2.0), row.id.with("fold"), Sense::click());
        (if collapsed { Icon::ChevronRight } else { Icon::ChevronDown }).paint(ui.painter(), r, if a.hovered() { p.text } else { p.text_secondary });
        if a.on_hover_text(if collapsed { "Expand folder" } else { "Collapse folder" }).clicked() {
            out.toggle_collapse = true;
        }
    }
    x += icon::SM + space::XXS;
    // visibility
    let vr = small(x, icon::SM + 2.0);
    let v = ui.interact(vr.expand(3.0), row.id.with("vis"), Sense::click());
    (if row.visible { Icon::Eye } else { Icon::EyeOff }).paint(ui.painter(), vr, if v.hovered() { p.text } else if row.visible { p.text_secondary } else { p.text_disabled });
    if v.on_hover_text(if row.visible { "Hide layer" } else { "Show layer" }).clicked() {
        out.toggle_visible = true;
    }
    x += icon::SM + 2.0 + space::SM;
    // thumbnail
    let tr = small(x, size::THUMB);
    (row.thumb)(ui.painter(), tr);
    ui.painter().rect_stroke(tr, cr(radius::SM), Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
    x += size::THUMB + space::MD;
    // trailing: mask thumb, lock, opacity
    let mut right = rect.right() - space::SM;
    if let Some((generated, active)) = row.mask {
        let mr = Rect::from_center_size(pos2(right - 13.0, cy), vec2(26.0, 26.0));
        let m = ui.interact(mr, row.id.with("mask"), Sense::click());
        ui.painter().rect_filled(mr, cr(radius::SM), p.well);
        ui.painter().rect_filled(Rect::from_min_max(mr.center_top(), mr.right_bottom()), cr(radius::SM), p.text);
        if generated {
            Icon::Sparkle.paint(ui.painter(), Rect::from_center_size(mr.center(), vec2(12.0, 12.0)), p.accent);
        }
        ui.painter().rect_stroke(mr, cr(radius::SM), Stroke::new(if active { 2.0 } else { 1.0 }, if active { p.accent } else { p.border_strong }), StrokeKind::Outside);
        if m.on_hover_ui(|ui| tooltip_body(ui, "Mask", Some("Where this layer shows. Click to select the mask and paint on it (white reveals, black hides)."), None)).clicked() {
            out.mask_clicked = true;
        }
        right -= 26.0 + space::SM;
    }
    let lr = Rect::from_center_size(pos2(right - icon::SM / 2.0, cy), vec2(icon::SM, icon::SM));
    let l = ui.interact(lr.expand(3.0), row.id.with("lock"), Sense::click());
    if row.locked || l.hovered() || hov {
        (if row.locked { Icon::Lock } else { Icon::Unlock }).paint(ui.painter(), lr, if row.locked { p.warn } else if l.hovered() { p.text } else { p.text_disabled });
    }
    if l.on_hover_text(if row.locked { "Unlock: allow painting" } else { "Lock: protect from painting and edits" }).clicked() {
        out.toggle_lock = true;
    }
    right -= icon::SM + space::SM;
    if row.opacity < 0.999 {
        let t = format!("{:.0}%", row.opacity * 100.0);
        let g = ui.painter().layout_no_wrap(t, fonts::mono(font::CAPTION), p.text_muted);
        right -= g.size().x;
        ui.painter().galley(pos2(right, cy - g.size().y / 2.0), g, p.text_muted);
        right -= space::SM;
    }
    // name and subtitle
    let nr = Rect::from_min_max(pos2(x, rect.top()), pos2(right, rect.bottom()));
    let name_c = if row.shown { p.text } else { p.text_muted };
    let painter = ui.painter().with_clip_rect(nr);
    painter.text(pos2(x, cy - 1.0), Align2::LEFT_BOTTOM, row.name, fonts::semibold(font::BODY), name_c);
    painter.text(pos2(x, cy + 2.0), Align2::LEFT_TOP, row.subtitle, fonts::regular(font::CAPTION), p.text_muted);
    out.clicked = resp.clicked();
    out.double_clicked = resp.double_clicked();
    out.context = Some(resp);
    out
}

/// Where a dragged row would land relative to `rect`: above, inside (folders) or below.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DropZone {
    Above,
    Into,
    Below,
}

pub fn drop_zone_at(rect: Rect, y: f32, folder: bool) -> DropZone {
    let t = (y - rect.top()) / rect.height().max(1.0);
    if folder {
        if t < 0.28 {
            DropZone::Above
        } else if t > 0.72 {
            DropZone::Below
        } else {
            DropZone::Into
        }
    } else if t < 0.5 {
        DropZone::Above
    } else {
        DropZone::Below
    }
}

pub fn paint_drop_hint(ui: &Ui, rect: Rect, zone: DropZone) {
    let p = pal(ui);
    match zone {
        DropZone::Above => {
            ui.painter().hline(rect.x_range(), rect.top() - 1.5, Stroke::new(2.5, p.accent));
        }
        DropZone::Below => {
            ui.painter().hline(rect.x_range(), rect.bottom() + 1.5, Stroke::new(2.5, p.accent));
        }
        DropZone::Into => {
            ui.painter().rect_stroke(rect, cr(radius::MD), Stroke::new(2.0, p.accent), StrokeKind::Inside);
        }
    }
}

// ------------------------------------------------------------------ toasts

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ToastKind {
    Info,
    Success,
    Warn,
    Error,
    Progress,
}

#[derive(Clone, Debug)]
pub struct Toast {
    pub id: u64,
    pub kind: ToastKind,
    pub title: String,
    pub body: String,
    pub born: f64,
    /// Known progress 0..1 for Progress toasts.
    pub frac: Option<f32>,
    pub sticky: bool,
}

/// Notifications in the bottom-right corner. Progress toasts stay until
/// `finish`; others fade after `motion::TOAST` seconds (errors stay longer).
#[derive(Default)]
pub struct Toasts {
    pub list: Vec<Toast>,
    next: u64,
}

impl Toasts {
    pub fn push(&mut self, kind: ToastKind, title: impl Into<String>, body: impl Into<String>) -> u64 {
        self.next += 1;
        let id = self.next;
        self.list.push(Toast { id, kind, title: title.into(), body: body.into(), born: f64::NAN, frac: None, sticky: kind == ToastKind::Progress });
        if self.list.len() > 5 {
            self.list.remove(0);
        }
        id
    }

    pub fn finish(&mut self, id: u64, kind: ToastKind, title: impl Into<String>, body: impl Into<String>) {
        if let Some(t) = self.list.iter_mut().find(|t| t.id == id) {
            t.kind = kind;
            t.title = title.into();
            t.body = body.into();
            t.sticky = false;
            t.born = f64::NAN;
        } else {
            self.push(kind, title, body);
        }
    }

    pub fn show(&mut self, ctx: &egui::Context, anchor: Rect) {
        let p = theme(ctx).p;
        let now = ctx.input(|i| i.time);
        for t in &mut self.list {
            if t.born.is_nan() {
                t.born = now;
            }
        }
        let life = |t: &Toast| if t.kind == ToastKind::Error { motion::TOAST as f64 * 2.5 } else { motion::TOAST as f64 };
        self.list.retain(|t| t.sticky || now - t.born < life(t));
        let mut y = anchor.bottom() - space::XL;
        let mut close = None;
        for t in self.list.iter().rev() {
            let age = (now - t.born) as f32;
            let fade = if t.sticky { 1.0 } else { ((life(t) as f32 - age) / motion::SLOW).clamp(0.0, 1.0) };
            let slide = (1.0 - motion::ease_out(age / motion::NORMAL)) * space::XL;
            let area = egui::Area::new(egui::Id::NULL.with(("toast", t.id))).order(egui::Order::Foreground).pivot(Align2::RIGHT_BOTTOM).fixed_pos(pos2(anchor.right() - space::XL, y + slide)).interactable(true);
            let r = area.show(ctx, |ui| {
                ui.set_opacity(fade);
                overlay_frame(&p).show(ui, |ui| {
                    ui.set_width(300.0);
                    ui.horizontal(|ui| {
                        let (ic, c) = match t.kind {
                            ToastKind::Info => (Icon::Info, p.info),
                            ToastKind::Success => (Icon::Success, p.success),
                            ToastKind::Warn => (Icon::Warning, p.warn),
                            ToastKind::Error => (Icon::Error, p.danger),
                            ToastKind::Progress => (Icon::History, p.accent),
                        };
                        if t.kind == ToastKind::Progress {
                            let (r, _) = ui.allocate_exact_size(vec2(icon::MD, icon::MD), Sense::hover());
                            icons::spinner(ui.painter(), r, c, now);
                        } else {
                            ic.show(ui, icon::MD, c);
                        }
                        ui.vertical(|ui| {
                            ui.horizontal(|ui| {
                                ui.label(strong(&t.title, font::BODY));
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Min), |ui| {
                                    if !t.sticky && ui.add(IconBtn::new(Icon::Close, "Dismiss").size(size::CONTROL_H_SM - 4.0)).clicked() {
                                        close = Some(t.id);
                                    }
                                });
                            });
                            if !t.body.is_empty() {
                                hint(ui, &t.body);
                            }
                            if let Some(f) = t.frac {
                                progress(ui, Some(f), "");
                            }
                        });
                    });
                });
            });
            y -= r.response.rect.height() + space::MD;
        }
        if let Some(id) = close {
            self.list.retain(|t| t.id != id);
        }
        if !self.list.is_empty() {
            ctx.request_repaint();
        }
    }
}

// ------------------------------------------------------------------ modal

/// A centred dialog over a scrim. Returns the closure's result and whether
/// the user dismissed it (Esc / click outside).
pub fn modal<R>(ctx: &egui::Context, id: &str, title: &str, width: f32, add: impl FnOnce(&mut Ui) -> R) -> (R, bool) {
    let p = theme(ctx).p;
    let m = egui::Modal::new(egui::Id::NULL.with(("modal", id)))
        .backdrop_color(p.scrim)
        .frame(egui::Frame::new().fill(p.overlay).stroke(Stroke::new(1.0, p.border_strong)).corner_radius(cr(radius::XL)).shadow(elevation(3, &p)).inner_margin(egui::Margin::same(space::XXL as i8)));
    let r = m.show(ctx, |ui| {
        ui.set_width(width);
        ui.horizontal(|ui| {
            ui.label(strong(title, font::HEADING));
        });
        ui.add_space(space::MD);
        add(ui)
    });
    let dismissed = r.should_close();
    (r.inner, dismissed)
}

// ------------------------------------------------------------------ command palette

/// A command for the palette.
#[derive(Clone, Debug)]
pub struct Command {
    pub id: String,
    pub title: String,
    pub group: &'static str,
    pub shortcut: Option<&'static str>,
    pub icon: Icon,
}

/// Subsequence fuzzy match score (higher is better), None if no match.
pub fn fuzzy_score(query: &str, text: &str) -> Option<i32> {
    let q: Vec<char> = query.to_lowercase().chars().filter(|c| !c.is_whitespace()).collect();
    if q.is_empty() {
        return Some(0);
    }
    let t: Vec<char> = text.to_lowercase().chars().collect();
    let mut score = 0;
    let mut qi = 0;
    let mut last: Option<usize> = None;
    for (i, c) in t.iter().enumerate() {
        if qi < q.len() && *c == q[qi] {
            score += 10;
            if last == Some(i.wrapping_sub(1)) {
                score += 15;
            }
            if i == 0 || t[i - 1] == ' ' {
                score += 20;
            }
            last = Some(i);
            qi += 1;
        }
    }
    (qi == q.len()).then_some(score - t.len() as i32 / 4)
}

#[derive(Default)]
pub struct Palette2State {
    pub open: bool,
    pub query: String,
    pub cursor: usize,
}

/// The command palette (Ctrl+K). Returns the chosen command id.
pub fn command_palette(ctx: &egui::Context, st: &mut Palette2State, commands: &[Command]) -> Option<String> {
    if !st.open {
        return None;
    }
    let p = theme(ctx).p;
    let mut ranked: Vec<(i32, &Command)> = commands.iter().filter_map(|c| fuzzy_score(&st.query, &format!("{} {}", c.title, c.group)).map(|s| (s, c))).collect();
    ranked.sort_by(|a, b| b.0.cmp(&a.0));
    ranked.truncate(12);
    let (up, down, enter, esc) = ctx.input(|i| (i.key_pressed(egui::Key::ArrowUp), i.key_pressed(egui::Key::ArrowDown), i.key_pressed(egui::Key::Enter), i.key_pressed(egui::Key::Escape)));
    if down {
        st.cursor = (st.cursor + 1).min(ranked.len().saturating_sub(1));
    }
    if up {
        st.cursor = st.cursor.saturating_sub(1);
    }
    st.cursor = st.cursor.min(ranked.len().saturating_sub(1));
    let mut chosen = None;
    if esc {
        st.open = false;
        return None;
    }
    if enter {
        chosen = ranked.get(st.cursor).map(|(_, c)| c.id.clone());
    }
    let screen = ctx.content_rect();
    egui::Area::new(egui::Id::NULL.with("command palette")).order(egui::Order::Foreground).fixed_pos(pos2(screen.center().x, screen.top() + 90.0)).pivot(Align2::CENTER_TOP).show(ctx, |ui| {
        overlay_frame(&p).shadow(elevation(3, &p)).show(ui, |ui| {
            ui.set_width(560.0);
            let r = search_field(ui, &mut st.query, "Type a command: export, rust, lighting, folder...");
            r.request_focus();
            if r.changed() {
                st.cursor = 0;
            }
            ui.add_space(space::SM);
            if ranked.is_empty() {
                ui.label(muted(ui, "No matching command"));
            }
            for (k, (_, c)) in ranked.iter().enumerate() {
                let on = k == st.cursor;
                let (rect, resp) = ui.allocate_exact_size(vec2(ui.available_width(), size::CONTROL_H + 2.0), Sense::click());
                if on || resp.hovered() {
                    ui.painter().rect_filled(rect, cr(radius::MD), if on { p.accent_subtle } else { p.surface_hover });
                }
                c.icon.paint(ui.painter(), Rect::from_center_size(pos2(rect.left() + space::LG + icon::SM / 2.0, rect.center().y), vec2(icon::SM, icon::SM)), if on { p.accent } else { p.text_secondary });
                ui.painter().text(pos2(rect.left() + space::LG * 2.0 + icon::SM, rect.center().y), Align2::LEFT_CENTER, &c.title, fonts::regular(font::BODY), p.text);
                let mut rx = rect.right() - space::LG;
                if let Some(s) = c.shortcut {
                    let g = ui.painter().layout_no_wrap(s.to_string(), fonts::mono(font::CAPTION), p.text_muted);
                    rx -= g.size().x;
                    ui.painter().galley(pos2(rx, rect.center().y - g.size().y / 2.0), g, p.text_muted);
                    rx -= space::LG;
                }
                ui.painter().text(pos2(rx, rect.center().y), Align2::RIGHT_CENTER, c.group, fonts::regular(font::CAPTION), p.text_muted);
                if resp.clicked() {
                    chosen = Some(c.id.clone());
                }
            }
        });
    });
    if chosen.is_some() {
        st.open = false;
        st.query.clear();
    }
    chosen
}

/// A font id for custom painting at a type-scale size.
pub fn font_id(size: f32) -> FontId {
    fonts::regular(size)
}
