//! The component library. Every control has the same states: rest, hover,
//! pressed (active), focused (keyboard focus ring), selected and disabled,
//! all drawn from the palette and the density metrics in `design::theme`.

use super::*;
use egui::text::{CCursor, CCursorRange, LayoutJob, TextFormat, TextWrapping};
use egui::{pos2, vec2, Align2, Color32, CornerRadius, FontId, Rect, Response, RichText, Sense, Stroke, StrokeKind, Ui, Widget};
use std::collections::BTreeMap;
use std::sync::Arc;

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

/// Small upper-case label with letter spacing (section headers).
pub fn caption(ui: &Ui, s: impl Into<String>) -> RichText {
    RichText::new(s.into().to_uppercase()).font(fonts::semibold(font::CAPTION - 0.5)).color(pal(ui).text_muted).extra_letter_spacing(font::CAPTION_TRACKING)
}

pub fn mono(s: impl Into<String>) -> RichText {
    RichText::new(s).font(fonts::mono(font::MONO))
}

/// A wrapped muted paragraph.
pub fn hint(ui: &mut Ui, s: impl Into<String>) -> Response {
    let t = muted(ui, s);
    ui.add(egui::Label::new(t).wrap())
}

/// One line of text, cut with an ellipsis at `max_w`.
pub fn elided(painter: &egui::Painter, s: &str, font: FontId, color: Color32, max_w: f32) -> Arc<egui::Galley> {
    let mut job = LayoutJob::single_section(s.to_string(), TextFormat { font_id: font, color, ..Default::default() });
    job.wrap = TextWrapping { max_width: max_w.max(1.0), max_rows: 1, break_anywhere: true, overflow_character: Some('…') };
    painter.layout_job(job)
}

/// Section header: caption text.
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
        ui.painter().rect_stroke(rect.expand(1.0), cr(r.saturating_add(1)), Stroke::new(1.5, pal(ui).focus), StrokeKind::Outside);
    }
}

// ------------------------------------------------------------------ collapsible sections

#[derive(Clone, Default)]
struct SectionStore {
    open: BTreeMap<String, bool>,
    dirty: bool,
}

fn section_store_id() -> egui::Id {
    egui::Id::NULL.with("pigment.design.sections")
}

/// Seed the open / closed state of collapsible sections (from the preferences).
pub fn load_sections(ctx: &egui::Context, open: &BTreeMap<String, bool>) {
    ctx.data_mut(|d| d.insert_temp(section_store_id(), SectionStore { open: open.clone(), dirty: false }));
}

/// The section states if the user changed one since the last call.
pub fn take_changed_sections(ctx: &egui::Context) -> Option<BTreeMap<String, bool>> {
    ctx.data_mut(|d| {
        let s = d.get_temp_mut_or_default::<SectionStore>(section_store_id());
        std::mem::take(&mut s.dirty).then(|| s.open.clone())
    })
}

/// Is the section `key` open (`None` if the user never touched it)?
pub fn section_open(ctx: &egui::Context, key: &str) -> Option<bool> {
    ctx.data(|d| d.get_temp::<SectionStore>(section_store_id()).and_then(|s| s.open.get(key).copied()))
}

pub fn set_section_open(ctx: &egui::Context, key: &str, open: bool) {
    ctx.data_mut(|d| {
        let s = d.get_temp_mut_or_default::<SectionStore>(section_store_id());
        if s.open.get(key) != Some(&open) {
            s.open.insert(key.to_string(), open);
            s.dirty = true;
        }
    });
}

/// A collapsible section: small chevron + caption. Its open state is kept
/// under `key` and remembered between sessions (see `load_sections`).
/// Returns the closure's value when open.
pub fn collapsible<R>(ui: &mut Ui, key: &str, title: &str, default_open: bool, add: impl FnOnce(&mut Ui) -> R) -> Option<R> {
    let p = pal(ui);
    let m = metrics(ui);
    let open = section_open(ui.ctx(), key).unwrap_or(default_open);
    ui.add_space(space::XXS);
    let (rect, resp) = ui.allocate_exact_size(vec2(ui.available_width(), m.control_h_sm + 2.0), Sense::click());
    let hov = resp.hovered();
    if hov {
        ui.painter().rect_filled(rect, cr(radius::SM), p.surface_hover.gamma_multiply(0.6));
    }
    let fg = if hov { p.text } else { p.text_secondary };
    let ir = Rect::from_center_size(pos2(rect.left() + space::XS + 5.0, rect.center().y), vec2(10.0, 10.0));
    (if open { Icon::ChevronDown } else { Icon::ChevronRight }).paint(ui.painter(), ir, if hov { p.text } else { p.text_muted });
    let mut job = LayoutJob::single_section(title.to_uppercase(), TextFormat { font_id: fonts::semibold(font::CAPTION - 0.5), color: if hov { p.text_secondary } else { p.text_muted }, extra_letter_spacing: font::CAPTION_TRACKING, ..Default::default() });
    job.wrap.max_width = f32::INFINITY;
    let g2 = ui.painter().layout_job(job);
    ui.painter().galley(pos2(ir.right() + space::SM, rect.center().y - g2.size().y / 2.0), g2, fg);
    focus_ring(ui, &resp, rect, radius::SM);
    if resp.clicked() {
        set_section_open(ui.ctx(), key, !open);
    }
    if open {
        ui.add_space(space::XXS);
        let r = add(ui);
        ui.add_space(space::XS);
        Some(r)
    } else {
        None
    }
}

// ------------------------------------------------------------------ hover hints (status bar)

/// A mouse button for the status-bar hints.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MouseBtn {
    Left,
    Right,
    Middle,
    Wheel,
}

/// One status-bar hint: optional keys, optional mouse button, what it does.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Hint {
    pub keys: &'static str,
    pub mouse: Option<MouseBtn>,
    pub action: &'static str,
}

pub const fn hint_mouse(mouse: MouseBtn, action: &'static str) -> Hint {
    Hint { keys: "", mouse: Some(mouse), action }
}

pub const fn hint_key(keys: &'static str, action: &'static str) -> Hint {
    Hint { keys, mouse: None, action }
}

pub const fn hint_mod(keys: &'static str, mouse: MouseBtn, action: &'static str) -> Hint {
    Hint { keys, mouse: Some(mouse), action }
}

/// What the hovered control does with the mouse and keys; the status bar
/// shows it instead of the tool's hints.
pub const DRAG_FIELD_HINTS: &[Hint] = &[hint_mouse(MouseBtn::Left, "Drag to change"), hint_key("Shift", "Fine"), hint_key("Ctrl", "Snap"), hint_key("Double-click", "Type a value")];

#[derive(Clone)]
struct HoverHints {
    pass: u64,
    hints: &'static [Hint],
}

/// Called by a hovered control: the status bar shows `hints` next frame.
pub fn set_hover_hints(ctx: &egui::Context, hints: &'static [Hint]) {
    let pass = ctx.cumulative_pass_nr();
    ctx.data_mut(|d| d.insert_temp(egui::Id::NULL.with("pigment.hover.hints"), HoverHints { pass, hints }));
}

/// The hints a control set during the previous frame, if any.
pub fn hover_hints(ctx: &egui::Context) -> Option<&'static [Hint]> {
    let now = ctx.cumulative_pass_nr();
    ctx.data(|d| d.get_temp::<HoverHints>(egui::Id::NULL.with("pigment.hover.hints"))).filter(|h| now <= h.pass + 1).map(|h| h.hints)
}

/// A tiny mouse with the pressed button (or the wheel) highlighted.
pub fn paint_mouse(painter: &egui::Painter, rect: Rect, which: MouseBtn, fg: Color32, hi: Color32) {
    let body = Rect::from_center_size(rect.center(), vec2(rect.height() * 0.66, rect.height()));
    let r = (body.width() * 0.5) as u8;
    let top = Rect::from_min_max(body.min, pos2(body.max.x, body.top() + body.height() * 0.45));
    match which {
        MouseBtn::Left => {
            let q = Rect::from_min_max(top.min, pos2(top.center().x, top.max.y));
            painter.rect_filled(q, CornerRadius { nw: r, ne: 0, sw: 0, se: 0 }, hi);
        }
        MouseBtn::Right => {
            let q = Rect::from_min_max(pos2(top.center().x, top.min.y), top.max);
            painter.rect_filled(q, CornerRadius { nw: 0, ne: r, sw: 0, se: 0 }, hi);
        }
        MouseBtn::Middle | MouseBtn::Wheel => {
            let w = Rect::from_center_size(pos2(top.center().x, top.center().y + 1.0), vec2(2.5, top.height() * 0.62));
            painter.rect_filled(w, cr(1), hi);
        }
    }
    painter.rect_stroke(body, CornerRadius::same(r), Stroke::new(1.0, fg), StrokeKind::Inside);
    if which != MouseBtn::Wheel {
        painter.vline(body.center().x, top.y_range().shrink(1.0), Stroke::new(1.0, fg));
    }
    painter.hline(body.x_range().shrink(1.0), top.bottom(), Stroke::new(1.0, fg));
}

/// A row of status-bar hints: `[keys] (mouse) action`.
pub fn hint_row(ui: &mut Ui, hints: &[Hint]) {
    let p = pal(ui);
    ui.horizontal(|ui| {
        ui.spacing_mut().item_spacing.x = space::XS;
        for (k, h) in hints.iter().enumerate() {
            if k > 0 {
                ui.add_space(space::MD);
            }
            if !h.keys.is_empty() {
                kbd(ui, h.keys);
            }
            if let Some(mb) = h.mouse {
                let (r, _) = ui.allocate_exact_size(vec2(10.0, 14.0), Sense::hover());
                paint_mouse(ui.painter(), r, mb, p.text_muted, p.text_secondary);
            }
            ui.label(text(h.action, font::SMALL).color(p.text_secondary));
        }
    });
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
        let m = metrics(ui);
        let (h, fs, pad, isz) = match self.size {
            BtnSize::Sm => (m.control_h_sm, font::SMALL, space::SM, icon::SM - 1.0),
            BtnSize::Md => (m.control_h, font::BODY, space::MD, icon::SM),
            BtnSize::Lg => (m.control_h + space::SM, font::TITLE, space::LG, icon::MD),
        };
        let fid = if self.kind == BtnKind::Primary { fonts::semibold(fs) } else { fonts::regular(fs) };
        let galley = ui.painter().layout_no_wrap(self.label.clone(), fid, Color32::PLACEHOLDER);
        let sc = self.shortcut.as_ref().map(|s| ui.painter().layout_no_wrap(s.clone(), fonts::mono(font::CAPTION - 0.5), Color32::PLACEHOLDER));
        let gap = space::SM;
        let mut w = pad * 2.0 + galley.size().x;
        if self.icon.is_some() {
            w += isz + if self.label.is_empty() { 0.0 } else { gap };
        }
        if let Some(sc) = &sc {
            w += sc.size().x + space::MD;
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
                    if self.selected { p.accent_subtle } else if down { p.surface_hover } else if hov { p.surface_hover } else { p.surface_raised },
                    p.text,
                    if self.selected { p.accent.gamma_multiply(0.7) } else if hov { p.border_strong } else { p.border },
                ),
                BtnKind::Ghost => (
                    if self.selected { p.accent_subtle } else if down || hov { p.surface_hover } else { Color32::TRANSPARENT },
                    if self.selected { p.accent } else if hov { p.text } else { p.text_secondary },
                    Color32::TRANSPARENT,
                ),
                BtnKind::Danger => (if down { p.danger.gamma_multiply(0.8) } else if hov { p.danger } else { p.danger.gamma_multiply(0.14) }, if hov || down { p.on_accent } else { p.danger }, p.danger.gamma_multiply(0.45)),
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
    size: Option<f32>,
    tint: Option<Color32>,
}

impl IconBtn {
    pub fn new(icon: Icon, tip: impl Into<String>) -> IconBtn {
        IconBtn { icon, tip: tip.into(), shortcut: None, selected: false, enabled: true, size: None, tint: None }
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
        self.size = Some(s);
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
        let sz = self.size.unwrap_or(metrics(ui).icon_btn);
        let (rect, resp) = ui.allocate_exact_size(vec2(sz, sz), if self.enabled { Sense::click() } else { Sense::hover() });
        let hov = resp.hovered() && self.enabled;
        let bg = if self.selected { p.accent_subtle } else if hov || resp.is_pointer_button_down_on() { p.surface_hover } else { Color32::TRANSPARENT };
        ui.painter().rect_filled(rect, cr(radius::MD), bg);
        let fg = if !self.enabled {
            p.text_disabled
        } else if self.selected {
            p.accent
        } else {
            self.tint.unwrap_or(if hov { p.text } else { p.text_secondary })
        };
        let isz = (sz * 0.62).clamp(icon::SM - 1.0, icon::LG);
        self.icon.paint(ui.painter(), Rect::from_center_size(rect.center(), vec2(isz, isz)), fg);
        focus_ring(ui, &resp, rect, radius::MD);
        let (tip, sc) = (self.tip, self.shortcut);
        if tip.is_empty() {
            return resp;
        }
        resp.on_hover_ui(|ui| tooltip_body(ui, &tip, None, sc.as_deref()))
    }
}

/// A tool button for the tool rail: an icon (with its label under it in the
/// Comfortable density), the active tool filled and marked with an accent bar.
pub fn tool_button(ui: &mut Ui, icon: Icon, label: &str, tip: &str, shortcut: &str, selected: bool) -> Response {
    let p = pal(ui);
    let m = metrics(ui);
    let (w, h) = if m.tool_labels { (m.tool + space::LG, m.tool + space::LG + 2.0) } else { (m.tool, m.tool) };
    let (rect, resp) = ui.allocate_exact_size(vec2(w, h), Sense::click());
    let hov = resp.hovered();
    let bg = if selected { p.accent_subtle } else if hov { p.surface_hover } else { Color32::TRANSPARENT };
    ui.painter().rect_filled(rect, cr(radius::LG), bg);
    if selected {
        let bar = Rect::from_min_size(pos2(rect.left() - space::XS + 1.0, rect.top() + space::SM), vec2(2.0, rect.height() - space::SM * 2.0));
        ui.painter().rect_filled(bar, cr(1), p.accent);
    }
    let fg = if selected { p.accent } else if hov { p.text } else { p.text_secondary };
    if m.tool_labels {
        let ir = Rect::from_center_size(pos2(rect.center().x, rect.top() + space::SM + icon::MD / 2.0 + 2.0), vec2(icon::MD + 2.0, icon::MD + 2.0));
        icon.paint(ui.painter(), ir, fg);
        ui.painter().text(pos2(rect.center().x, rect.bottom() - space::SM), Align2::CENTER_BOTTOM, label, fonts::regular(font::CAPTION), fg);
    } else {
        icon.paint(ui.painter(), Rect::from_center_size(rect.center(), vec2(icon::MD + 1.0, icon::MD + 1.0)), fg);
        // the shortcut letter in the corner, so the keyboard way is visible
        if !shortcut.is_empty() && shortcut.len() == 1 {
            ui.painter().text(rect.right_bottom() - vec2(3.0, 1.0), Align2::RIGHT_BOTTOM, shortcut, fonts::mono(9.0), if selected { p.accent.gamma_multiply(0.8) } else { p.text_disabled });
        }
    }
    focus_ring(ui, &resp, rect, radius::LG);
    resp.on_hover_ui(|ui| tooltip_body(ui, label, Some(tip), Some(shortcut).filter(|s| !s.is_empty())))
}

/// Key cap.
pub fn kbd(ui: &mut Ui, keys: &str) -> Response {
    let p = pal(ui);
    let g = ui.painter().layout_no_wrap(keys.to_string(), fonts::mono(font::CAPTION - 0.5), p.text_secondary);
    let (rect, resp) = ui.allocate_exact_size(g.size() + vec2(space::SM + 2.0, space::XXS + 1.0), Sense::hover());
    ui.painter().rect(rect, cr(radius::SM), p.surface_raised, Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
    ui.painter().galley(rect.center() - g.size() / 2.0, g, p.text_secondary);
    resp
}

/// Rich tooltip: a title, optional body and shortcut.
pub fn tooltip_body(ui: &mut Ui, title: &str, body: Option<&str>, shortcut: Option<&str>) {
    ui.set_max_width(260.0);
    ui.horizontal(|ui| {
        ui.label(strong(title, font::SMALL));
        if let Some(s) = shortcut {
            ui.add_space(space::XS);
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

// ------------------------------------------------------------------ menus

/// A menu / context-menu entry: icon column, label, shortcut on the right.
/// Same height and look in every menu.
pub struct MenuItem {
    label: String,
    icon: Option<Icon>,
    shortcut: Option<String>,
    enabled: bool,
    danger: bool,
    checked: Option<bool>,
}

impl MenuItem {
    pub fn new(label: impl Into<String>) -> MenuItem {
        MenuItem { label: label.into(), icon: None, shortcut: None, enabled: true, danger: false, checked: None }
    }
    pub fn icon(mut self, i: Icon) -> MenuItem {
        self.icon = Some(i);
        self
    }
    pub fn shortcut(mut self, s: impl Into<String>) -> MenuItem {
        self.shortcut = Some(s.into());
        self
    }
    pub fn enabled(mut self, on: bool) -> MenuItem {
        self.enabled = on;
        self
    }
    pub fn danger(mut self) -> MenuItem {
        self.danger = true;
        self
    }
    /// Show a check mark (on) or an empty check column (off).
    pub fn checked(mut self, on: bool) -> MenuItem {
        self.checked = Some(on);
        self
    }
}

impl Widget for MenuItem {
    fn ui(self, ui: &mut Ui) -> Response {
        let p = pal(ui);
        let m = metrics(ui);
        let g = ui.painter().layout_no_wrap(self.label.clone(), fonts::regular(font::BODY), p.text);
        let sc = self.shortcut.as_ref().map(|s| ui.painter().layout_no_wrap(s.clone(), fonts::mono(font::CAPTION - 0.5), p.text_muted));
        let w = (icon::SM + space::MD * 2.0 + g.size().x + sc.as_ref().map_or(0.0, |s| s.size().x + space::XL) + space::MD).max(150.0);
        let (rect, resp) = ui.allocate_at_least(vec2(w, m.control_h), if self.enabled { Sense::click() } else { Sense::hover() });
        let hov = resp.hovered() && self.enabled;
        if hov {
            ui.painter().rect_filled(rect, cr(radius::MD), if self.danger { p.danger.gamma_multiply(0.18) } else { p.surface_hover });
        }
        let fg = if !self.enabled {
            p.text_disabled
        } else if self.danger && hov {
            p.danger
        } else {
            p.text
        };
        let ir = Rect::from_center_size(pos2(rect.left() + space::SM + icon::SM / 2.0, rect.center().y), vec2(icon::SM, icon::SM));
        match (self.checked, self.icon) {
            (Some(true), _) => Icon::Check.paint(ui.painter(), ir, if self.enabled { p.accent } else { p.text_disabled }),
            (_, Some(i)) => i.paint(ui.painter(), ir, if self.enabled { if self.danger { p.danger } else { p.text_secondary } } else { p.text_disabled }),
            _ => {}
        }
        ui.painter().galley(pos2(ir.right() + space::MD, rect.center().y - g.size().y / 2.0), g, fg);
        if let Some(sc) = sc {
            ui.painter().galley(pos2(rect.right() - space::SM - sc.size().x, rect.center().y - sc.size().y / 2.0), sc, if self.enabled { p.text_muted } else { p.text_disabled });
        }
        resp
    }
}

// ------------------------------------------------------------------ toggles

/// A switch with a label.
pub fn toggle(ui: &mut Ui, on: &mut bool, label: &str) -> Response {
    let p = pal(ui);
    let m = metrics(ui);
    let g = ui.painter().layout_no_wrap(label.to_string(), fonts::regular(font::BODY), p.text);
    let sw = vec2(24.0, 13.0);
    let (rect, mut resp) = ui.allocate_exact_size(vec2(sw.x + space::SM + g.size().x, m.control_h_sm + 2.0), Sense::click());
    if resp.clicked() {
        *on = !*on;
        resp.mark_changed();
    }
    let t = ui.ctx().animate_bool_with_time(resp.id, *on, motion::FAST);
    let track = Rect::from_min_size(pos2(rect.left(), rect.center().y - sw.y / 2.0), sw);
    let bg = if *on { p.accent } else if resp.hovered() { p.border_strong } else { p.surface_hover };
    ui.painter().rect_filled(track, cr(radius::PILL), bg);
    let x = egui::lerp(track.left() + sw.y / 2.0..=track.right() - sw.y / 2.0, motion::ease_out(t));
    ui.painter().circle_filled(pos2(x, track.center().y), sw.y / 2.0 - 2.0, if *on { p.on_accent } else { p.text_secondary });
    ui.painter().galley(pos2(track.right() + space::SM, rect.center().y - g.size().y / 2.0), g, if resp.hovered() { p.text } else { p.text_secondary });
    focus_ring(ui, &resp, track, radius::PILL);
    resp
}

/// Segmented control: one of several options. Returns true when changed.
pub fn segmented<T: PartialEq + Copy>(ui: &mut Ui, value: &mut T, options: &[(T, Option<Icon>, &str)]) -> bool {
    let p = pal(ui);
    let m = metrics(ui);
    let mut changed = false;
    let frame = egui::Frame::new().fill(p.well).corner_radius(cr(radius::MD)).inner_margin(egui::Margin::same(1)).stroke(Stroke::new(1.0, p.border));
    frame.show(ui, |ui| {
        ui.spacing_mut().item_spacing = vec2(1.0, 1.0);
        ui.horizontal_wrapped(|ui| {
            for (v, ic, label) in options {
                let on = *value == *v;
                let g = ui.painter().layout_no_wrap(label.to_string(), fonts::regular(font::SMALL), p.text);
                let w = g.size().x + space::MD * 2.0 + ic.map_or(0.0, |_| icon::SM + space::XS);
                let w = if label.is_empty() { m.control_h_sm + space::XS } else { w };
                let (rect, resp) = ui.allocate_exact_size(vec2(w, m.control_h_sm), Sense::click());
                let bg = if on { p.surface_hover } else if resp.hovered() { p.surface_raised } else { Color32::TRANSPARENT };
                ui.painter().rect_filled(rect, cr(radius::SM), bg);
                let fg = if on { p.text } else if resp.hovered() { p.text_secondary } else { p.text_muted };
                let mut x = rect.center().x - (w - space::MD * 2.0) / 2.0;
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
    let m = metrics(ui);
    let mut changed = false;
    ui.horizontal(|ui| {
        ui.spacing_mut().item_spacing.x = space::XXS;
        for (v, label) in options {
            let on = *value == *v;
            let g = ui.painter().layout_no_wrap(label.to_string(), if on { fonts::semibold(font::SMALL) } else { fonts::regular(font::SMALL) }, p.text);
            let (rect, resp) = ui.allocate_exact_size(vec2(g.size().x + space::MD * 2.0, m.tab_h - 2.0), Sense::click());
            if resp.hovered() && !on {
                ui.painter().rect_filled(rect.shrink2(vec2(0.0, 2.0)), cr(radius::MD), p.surface_hover);
            }
            let fg = if on { p.text } else if resp.hovered() { p.text } else { p.text_secondary };
            ui.painter().galley(pos2(rect.left() + space::MD, rect.center().y - g.size().y / 2.0), g, fg);
            if on {
                ui.painter().rect_filled(Rect::from_min_max(pos2(rect.left() + space::XS, rect.bottom() - 2.0), pos2(rect.right() - space::XS, rect.bottom())), cr(1), p.accent);
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

// ------------------------------------------------------------------ drag fields

/// How a value is shown.
#[derive(Clone, Copy)]
pub enum Unit {
    Plain(usize),
    Percent,
    Suffix(&'static str, usize),
}

impl Unit {
    pub fn format(self, v: f32) -> String {
        match self {
            Unit::Percent => format!("{:.0}%", v * 100.0),
            Unit::Plain(d) => format!("{v:.d$}"),
            Unit::Suffix(s, d) => format!("{v:.d$}{s}"),
        }
    }
    /// The number to put in the text box when typing (no unit).
    fn edit_text(self, v: f32) -> String {
        match self {
            Unit::Percent => format!("{:.0}", v * 100.0),
            Unit::Plain(d) | Unit::Suffix(_, d) => format!("{v:.d$}"),
        }
    }
    /// Parse typed text; accepts the unit, `%`, and simple `a+b`, `a-b`, `a*b`, `a/b`.
    pub fn parse(self, s: &str) -> Option<f32> {
        let mut t = s.trim().to_string();
        if let Unit::Suffix(suf, _) = self {
            t = t.trim_end_matches(suf.trim()).trim().to_string();
        }
        t = t.trim_end_matches('%').trim().to_string();
        let x = eval_simple(&t)?;
        Some(match self {
            Unit::Percent => x / 100.0,
            _ => x,
        } as f32)
    }
    fn decimals(self) -> usize {
        match self {
            Unit::Percent => 2,
            Unit::Plain(d) | Unit::Suffix(_, d) => d,
        }
    }
}

/// `12`, `-3.5`, `40+5`, `2*3`, `10/4`: one binary operator at most.
fn eval_simple(s: &str) -> Option<f64> {
    let s = s.replace(',', ".");
    if let Ok(v) = s.parse::<f64>() {
        return Some(v);
    }
    for op in ['+', '*', '/', '-'] {
        if let Some(k) = s.char_indices().skip(1).filter(|(_, c)| *c == op).map(|(i, _)| i).last() {
            let (a, b) = (s[..k].trim().parse::<f64>().ok()?, s[k + 1..].trim().parse::<f64>().ok()?);
            return Some(match op {
                '+' => a + b,
                '-' => a - b,
                '*' => a * b,
                _ if b != 0.0 => a / b,
                _ => return None,
            });
        }
    }
    None
}

/// A "nice" step near `x`: 1, 2, 2.5 or 5 times a power of ten.
pub fn nice_step(x: f32) -> f32 {
    if !(x.is_finite() && x > 0.0) {
        return 1.0;
    }
    let e = 10f32.powf(x.log10().floor());
    let f = x / e;
    let n = if f < 1.5 {
        1.0
    } else if f < 2.25 {
        2.0
    } else if f < 3.5 {
        2.5
    } else if f < 7.5 {
        5.0
    } else {
        10.0
    };
    n * e
}

#[derive(Clone, Default)]
struct FieldState {
    editing: Option<String>,
    fresh: bool,
    drag_t: f32,
}

/// Blender-style inline numeric field: the value sits inside a bar that fills
/// to show where it is in its range. Drag to scrub (Shift: fine, Ctrl: snap
/// to round steps), double-click (or Enter when focused) to type, the arrow
/// ends nudge, Left / Right keys nudge when focused.
pub struct DragField<'a> {
    v: &'a mut f32,
    range: std::ops::RangeInclusive<f32>,
    unit: Unit,
    log: bool,
    label: Option<String>,
    width: Option<f32>,
}

impl<'a> DragField<'a> {
    pub fn new(v: &'a mut f32, range: std::ops::RangeInclusive<f32>) -> DragField<'a> {
        DragField { v, range, unit: Unit::Plain(2), log: false, label: None, width: None }
    }
    pub fn unit(mut self, u: Unit) -> Self {
        self.unit = u;
        self
    }
    pub fn percent(self) -> Self {
        self.unit(Unit::Percent)
    }
    pub fn decimals(mut self, d: usize) -> Self {
        self.unit = match self.unit {
            Unit::Suffix(s, _) => Unit::Suffix(s, d),
            _ => Unit::Plain(d),
        };
        self
    }
    pub fn suffix(mut self, s: &'static str) -> Self {
        self.unit = Unit::Suffix(s, self.unit.decimals());
        self
    }
    pub fn logarithmic(mut self, on: bool) -> Self {
        self.log = on;
        self
    }
    /// A label drawn inside the field, left of the value (toolbars).
    pub fn label(mut self, s: impl Into<String>) -> Self {
        self.label = Some(s.into());
        self
    }
    pub fn width(mut self, w: f32) -> Self {
        self.width = Some(w);
        self
    }
}

fn field_norm(v: f32, lo: f32, hi: f32, log: bool) -> f32 {
    if hi <= lo {
        return 0.0;
    }
    if log && lo > 0.0 {
        ((v.max(lo) / lo).ln() / (hi / lo).ln()).clamp(0.0, 1.0)
    } else {
        ((v - lo) / (hi - lo)).clamp(0.0, 1.0)
    }
}

fn field_denorm(t: f32, lo: f32, hi: f32, log: bool) -> f32 {
    let t = t.clamp(0.0, 1.0);
    if log && lo > 0.0 {
        lo * (hi / lo).powf(t)
    } else {
        lo + (hi - lo) * t
    }
}

impl Widget for DragField<'_> {
    fn ui(self, ui: &mut Ui) -> Response {
        let p = pal(ui);
        let m = metrics(ui);
        let (lo, hi) = (*self.range.start(), *self.range.end());
        let w = self.width.unwrap_or_else(|| ui.available_width()).max(40.0);
        let (rect, mut resp) = ui.allocate_exact_size(vec2(w, m.field_h), Sense::click_and_drag());
        let id = resp.id;
        let mut st: FieldState = ui.data(|d| d.get_temp(id)).unwrap_or_default();
        let span = hi - lo;
        let snap = |v: f32| -> f32 {
            let step = match self.unit {
                Unit::Percent => 0.05,
                _ => nice_step(span / 20.0),
            };
            (v / step).round() * step
        };
        let nudge_step = match self.unit {
            Unit::Percent => 0.01,
            Unit::Plain(d) | Unit::Suffix(_, d) => nice_step(span / 100.0).max(10f32.powi(-(d as i32))),
        };
        let before = *self.v;
        // ---- typing
        if st.editing.is_none() && (resp.double_clicked() || (resp.has_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)))) {
            st.editing = Some(self.unit.edit_text(*self.v));
            st.fresh = true;
        }
        if let Some(mut buf) = st.editing.take() {
            let eid = id.with("edit");
            let mut child = ui.new_child(egui::UiBuilder::new().max_rect(rect).layout(egui::Layout::left_to_right(egui::Align::Center)));
            ui.painter().rect(rect, cr(radius::MD), p.well, Stroke::new(1.0, p.focus), StrokeKind::Inside);
            let te = egui::TextEdit::singleline(&mut buf).id(eid).frame(egui::Frame::NONE).font(fonts::mono(font::MONO)).align(Align2::CENTER_CENTER).desired_width(rect.width() - space::MD).margin(egui::Margin::symmetric(space::XS as i8, 0));
            let r = child.add(te);
            if st.fresh {
                r.request_focus();
                if let Some(mut s) = egui::TextEdit::load_state(ui.ctx(), eid) {
                    s.cursor.set_char_range(Some(CCursorRange::two(CCursor::new(0), CCursor::new(buf.chars().count()))));
                    s.store(ui.ctx(), eid);
                }
                st.fresh = false;
                st.editing = Some(buf);
            } else if r.lost_focus() {
                let esc = ui.input(|i| i.key_pressed(egui::Key::Escape));
                if !esc {
                    if let Some(x) = self.unit.parse(&buf) {
                        *self.v = x.clamp(lo.min(hi), hi.max(lo));
                    }
                }
                resp.request_focus();
            } else {
                st.editing = Some(buf);
            }
            ui.data_mut(|d| d.insert_temp(id, st));
            if *self.v != before {
                resp.mark_changed();
            }
            return resp;
        }
        // ---- dragging
        let shift = ui.input(|i| i.modifiers.shift);
        let ctrl = ui.input(|i| i.modifiers.command || i.modifiers.ctrl);
        if resp.drag_started() {
            st.drag_t = field_norm(*self.v, lo, hi, self.log);
        }
        if resp.dragged() {
            let dx = resp.drag_delta().x;
            if dx != 0.0 {
                st.drag_t = (st.drag_t + dx / rect.width() * if shift { 0.1 } else { 1.0 }).clamp(0.0, 1.0);
                let mut v = field_denorm(st.drag_t, lo, hi, self.log);
                if ctrl {
                    v = snap(v);
                }
                *self.v = v.clamp(lo, hi);
            }
            ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
        }
        // ---- nudging: the arrow ends, and Left / Right when focused
        let edge = space::MD + 2.0;
        let hov = resp.hovered() || resp.dragged();
        if resp.clicked() && !resp.dragged() {
            if let Some(pt) = resp.interact_pointer_pos() {
                if pt.x < rect.left() + edge {
                    *self.v = (*self.v - nudge_step).clamp(lo, hi);
                } else if pt.x > rect.right() - edge {
                    *self.v = (*self.v + nudge_step).clamp(lo, hi);
                }
            }
            resp.request_focus();
        }
        if resp.has_focus() {
            let (l, r) = ui.input(|i| (i.key_pressed(egui::Key::ArrowLeft), i.key_pressed(egui::Key::ArrowRight)));
            let k = if shift { 0.1 } else if ctrl { 10.0 } else { 1.0 };
            if l {
                *self.v = (*self.v - nudge_step * k).clamp(lo, hi);
            }
            if r {
                *self.v = (*self.v + nudge_step * k).clamp(lo, hi);
            }
        }
        if resp.hovered() {
            set_hover_hints(ui.ctx(), DRAG_FIELD_HINTS);
            if !resp.dragged() {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
            }
        }
        ui.data_mut(|d| d.insert_temp(id, st));
        if *self.v != before {
            resp.mark_changed();
        }
        // ---- paint
        if ui.is_rect_visible(rect) {
            let bg = if hov { p.surface_raised } else { p.well };
            ui.painter().rect_filled(rect, cr(radius::MD), bg);
            let t = field_norm(*self.v, lo, hi, self.log);
            let c = if resp.dragged() { p.border_strong.lerp_to_gamma(p.field_fill, 0.4) } else if hov { p.field_fill.lerp_to_gamma(p.border_strong, 0.25) } else { p.field_fill };
            if lo < 0.0 && hi > 0.0 && !self.log {
                // signed: fill from zero towards the value
                let z = field_norm(0.0, lo, hi, false);
                let (a, b) = (z.min(t), z.max(t));
                let fill = Rect::from_min_max(pos2(rect.left() + rect.width() * a, rect.top()), pos2(rect.left() + rect.width() * b, rect.bottom()));
                ui.painter().rect_filled(fill, CornerRadius::ZERO, c);
                let zx = rect.left() + rect.width() * z;
                ui.painter().vline(zx, rect.top()..=rect.top() + space::XS, Stroke::new(1.0, p.text_muted));
                ui.painter().vline(zx, rect.bottom() - space::XS..=rect.bottom(), Stroke::new(1.0, p.text_muted));
            } else if t > 0.0 {
                let fill = Rect::from_min_max(rect.min, pos2(rect.left() + rect.width() * t, rect.bottom()));
                ui.painter().rect_filled(fill, CornerRadius { nw: radius::MD, sw: radius::MD, ne: if t > 0.99 { radius::MD } else { 0 }, se: if t > 0.99 { radius::MD } else { 0 } }, c);
            }
            ui.painter().rect_stroke(rect, cr(radius::MD), Stroke::new(1.0, if resp.has_focus() { p.focus } else if hov { p.border_strong } else { p.border }), StrokeKind::Inside);
            let value = self.unit.format(*self.v);
            let vg = ui.painter().layout_no_wrap(value, fonts::mono(font::MONO), p.text);
            let pad = if hov { edge } else { space::SM };
            match &self.label {
                Some(l) => {
                    let lg = elided(ui.painter(), l, fonts::regular(font::SMALL), p.text_secondary, rect.width() - vg.size().x - pad * 2.0 - space::XS);
                    ui.painter().galley(pos2(rect.left() + pad, rect.center().y - lg.size().y / 2.0), lg, p.text_secondary);
                    ui.painter().galley(pos2(rect.right() - pad - vg.size().x, rect.center().y - vg.size().y / 2.0), vg, p.text);
                }
                None => {
                    ui.painter().galley(rect.center() - vg.size() / 2.0, vg, p.text);
                }
            }
            if hov && !resp.dragged() {
                let a = Rect::from_center_size(pos2(rect.left() + edge / 2.0 + 1.0, rect.center().y), vec2(8.0, 8.0));
                let b = Rect::from_center_size(pos2(rect.right() - edge / 2.0 - 1.0, rect.center().y), vec2(8.0, 8.0));
                Icon::ChevronLeft.paint(ui.painter(), a, p.text_muted);
                Icon::ChevronRight.paint(ui.painter(), b, p.text_muted);
            }
        }
        resp
    }
}

/// Property row: label in the left column, a drag field in the right.
/// Returns the field's response (changed when the value changed).
pub fn slider_row(ui: &mut Ui, label: &str, v: &mut f32, range: std::ops::RangeInclusive<f32>, unit: Unit) -> Response {
    slider_row_ex(ui, label, v, range, unit, false, None)
}

pub fn slider_row_ex(ui: &mut Ui, label: &str, v: &mut f32, range: std::ops::RangeInclusive<f32>, unit: Unit, log: bool, tip: Option<&str>) -> Response {
    let p = pal(ui);
    let m = metrics(ui);
    ui.horizontal(|ui| {
        let lw = (ui.available_width() * 0.4).clamp(48.0, m.label_w);
        let (lr, lresp) = ui.allocate_exact_size(vec2(lw, m.field_h), Sense::hover());
        let g = elided(ui.painter(), label, fonts::regular(font::SMALL), p.text_secondary, lw - space::XS);
        ui.painter().galley(pos2(lr.left(), lr.center().y - g.size().y / 2.0), g, p.text_secondary);
        let r = ui.add(DragField::new(v, range).unit(unit).logarithmic(log));
        match tip {
            Some(t) => {
                lresp.on_hover_ui(|ui| tooltip_body(ui, label, Some(t), None));
                r.on_hover_ui(|ui| tooltip_body(ui, label, Some(t), None))
            }
            None => r,
        }
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
        ui.painter().rect_stroke(rect.expand(1.5), cr(radius::MD), Stroke::new(1.5, if selected { p.accent } else { p.text_muted }), StrokeKind::Outside);
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

/// A flat group on a panel: a slightly raised fill and a hairline.
pub fn card<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> R {
    let p = pal(ui);
    let m = metrics(ui);
    egui::Frame::new()
        .fill(p.surface_raised)
        .stroke(Stroke::new(1.0, p.border))
        .corner_radius(cr(radius::LG))
        .inner_margin(egui::Margin::same(m.pad as i8))
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            add(ui)
        })
        .inner
}

/// A card that can be selected (accent border) and clicked.
pub fn card_selectable<R>(ui: &mut Ui, selected: bool, add: impl FnOnce(&mut Ui) -> R) -> (Response, R) {
    let p = pal(ui);
    let m = metrics(ui);
    let out = egui::Frame::new()
        .fill(if selected { p.accent_subtle } else { p.surface_raised })
        .stroke(Stroke::new(1.0, if selected { p.accent } else { p.border }))
        .corner_radius(cr(radius::LG))
        .inner_margin(egui::Margin::same(m.pad as i8))
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
    egui::Frame::new().fill(p.overlay).stroke(Stroke::new(1.0, p.border_strong)).corner_radius(cr(radius::LG)).shadow(elevation(2, p)).inner_margin(egui::Margin::same(space::MD as i8))
}

/// Translucent HUD chip frame over the viewport.
pub fn glass_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.glass).corner_radius(cr(radius::LG)).inner_margin(egui::Margin::same(space::XXS as i8)).stroke(Stroke::new(1.0, p.border))
}

/// Empty state: icon, title, explanation, optional action. Returns true if
/// the action was clicked.
pub fn empty_state(ui: &mut Ui, icon: Icon, title: &str, body: &str, action: Option<&str>) -> bool {
    let p = pal(ui);
    let mut clicked = false;
    ui.vertical_centered(|ui| {
        ui.add_space(space::LG);
        let (r, _) = ui.allocate_exact_size(vec2(icon::XL, icon::XL), Sense::hover());
        ui.painter().rect_filled(r, cr(radius::LG), p.surface_raised);
        icon.paint(ui.painter(), r.shrink(space::SM + 1.0), p.text_muted);
        ui.add_space(space::SM);
        ui.label(strong(title, font::BODY));
        ui.add(egui::Label::new(muted(ui, body)).wrap());
        if let Some(a) = action {
            ui.add_space(space::XS);
            clicked = ui.add(Btn::secondary(a).small()).clicked();
        }
        ui.add_space(space::LG);
    });
    clicked
}

/// Progress: a bar for known fractions, a spinner otherwise.
pub fn progress(ui: &mut Ui, frac: Option<f32>, label: &str) {
    let p = pal(ui);
    ui.horizontal(|ui| {
        match frac {
            Some(f) => {
                let (rect, _) = ui.allocate_exact_size(vec2(100.0, 4.0), Sense::hover());
                ui.painter().rect_filled(rect, cr(radius::SM), p.well);
                let mut fill = rect;
                fill.set_width(rect.width() * f.clamp(0.0, 1.0));
                ui.painter().rect_filled(fill, cr(radius::SM), p.accent);
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

/// Search field with an icon and a clear button. Esc clears it while focused.
pub fn search_field(ui: &mut Ui, query: &mut String, hint_text: &str) -> Response {
    let p = pal(ui);
    let m = metrics(ui);
    egui::Frame::new()
        .fill(p.well)
        .stroke(Stroke::new(1.0, p.border))
        .corner_radius(cr(radius::MD))
        .inner_margin(egui::Margin { left: space::SM as i8, right: space::XXS as i8, top: 0, bottom: 0 })
        .show(ui, |ui| {
            let h = m.control_h - 2.0;
            ui.allocate_ui_with_layout(vec2(ui.available_width(), h), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                ui.set_min_height(h);
                ui.spacing_mut().item_spacing.x = space::XS;
                Icon::Search.show(ui, icon::SM - 1.0, p.text_muted);
                let w = ui.available_width() - if query.is_empty() { 0.0 } else { m.control_h_sm + space::XS };
                let mut r = ui.add(egui::TextEdit::singleline(query).hint_text(hint_text).frame(egui::Frame::NONE).font(fonts::regular(font::BODY)).desired_width(w).margin(egui::Margin::ZERO));
                if r.has_focus() && !query.is_empty() && ui.input(|i| i.key_pressed(egui::Key::Escape)) {
                    query.clear();
                    r.mark_changed();
                }
                if !query.is_empty() && ui.add(IconBtn::new(Icon::Close, "Clear").size(m.control_h_sm)).clicked() {
                    query.clear();
                    r.mark_changed();
                }
                r
            })
            .inner
        })
        .inner
}

/// Property inspector: label column + control column.
pub fn prop_grid<R>(ui: &mut Ui, id: &str, add: impl FnOnce(&mut Ui) -> R) -> R {
    let m = metrics(ui);
    ui.spacing_mut().slider_width = (ui.available_width() - m.label_w - space::MD - 56.0).clamp(60.0, 220.0);
    egui::Grid::new(id).num_columns(2).spacing([space::MD, m.gap.y]).min_col_width(m.label_w).min_row_height(m.field_h).show(ui, add).inner
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
    asset_tile_ex(ui, w, w - space::XXS * 2.0, thumb, fallback, title, subtitle, selected)
}

/// `asset_tile` with a thumbnail `img_h` points tall (wide previews), the image cropped to fit.
#[allow(clippy::too_many_arguments)]
pub fn asset_tile_ex(ui: &mut Ui, w: f32, img_h: f32, thumb: Option<egui::TextureId>, fallback: impl FnOnce(&egui::Painter, Rect), title: &str, subtitle: &str, selected: bool) -> Response {
    let p = pal(ui);
    let h = img_h + space::XXS * 2.0 + 30.0;
    let (rect, resp) = ui.allocate_exact_size(vec2(w, h), Sense::click());
    if !ui.is_rect_visible(rect) {
        return resp;
    }
    let hov = resp.hovered();
    let bg = if selected { p.accent_subtle } else if hov { p.surface_hover } else { p.surface_raised };
    ui.painter().rect_filled(rect, cr(radius::LG), bg);
    let img = Rect::from_min_size(rect.min + vec2(space::XXS, space::XXS), vec2(w - space::XXS * 2.0, img_h));
    match thumb {
        Some(t) => {
            let a = img.height() / img.width();
            let uv = if a < 1.0 { Rect::from_min_max(pos2(0.0, 0.5 - a / 2.0), pos2(1.0, 0.5 + a / 2.0)) } else { Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)) };
            ui.painter().image(t, img, uv, Color32::WHITE);
        }
        None => fallback(ui.painter(), img),
    }
    let tr = Rect::from_min_max(pos2(rect.left() + space::XS + 1.0, img.bottom() + space::XS), pos2(rect.right() - space::XS, rect.bottom()));
    let title_g = ui.painter().layout(title.to_string(), fonts::regular(font::SMALL), p.text, tr.width());
    let rows = title_g.rows.len();
    let th = title_g.size().y;
    ui.painter().with_clip_rect(tr).galley(tr.min, title_g, p.text);
    if rows < 2 && !subtitle.is_empty() {
        let sg = elided(ui.painter(), subtitle, fonts::regular(font::CAPTION - 0.5), p.text_muted, tr.width());
        ui.painter().with_clip_rect(tr).galley(tr.min + vec2(0.0, th), sg, p.text_muted);
    }
    let stroke = if selected { Stroke::new(1.5, p.accent) } else if hov { Stroke::new(1.0, p.border_strong) } else { Stroke::new(1.0, p.border) };
    ui.painter().rect_stroke(rect, cr(radius::LG), stroke, StrokeKind::Inside);
    focus_ring(ui, &resp, rect, radius::LG);
    resp
}

/// A small label chip.
pub fn badge(ui: &mut Ui, label: &str, color: Color32) -> Response {
    let g = ui.painter().layout_no_wrap(label.to_string(), fonts::semibold(font::CAPTION - 0.5), color);
    let (rect, resp) = ui.allocate_exact_size(g.size() + vec2(space::MD, space::XXS), Sense::hover());
    ui.painter().rect_filled(rect, cr(radius::SM), color.gamma_multiply(0.16));
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
    /// Where the name is drawn (for inline renaming).
    pub name_rect: Rect,
    pub handle: Option<Response>,
    pub context: Option<Response>,
}

impl Default for LayerRowResponse {
    fn default() -> Self {
        LayerRowResponse { clicked: false, double_clicked: false, toggle_visible: false, toggle_lock: false, toggle_collapse: false, mask_clicked: false, rect: Rect::NOTHING, name_rect: Rect::NOTHING, handle: None, context: None }
    }
}

/// The layer row: drag handle, (folder arrow), visibility, thumbnail, name +
/// what it is, opacity, lock, mask thumbnail. The handle is a drag source
/// for `payload`. Compact density puts the name and kind on one line.
pub fn layer_row<P: Send + Sync + 'static>(ui: &mut Ui, row: &LayerRow, payload: P) -> LayerRowResponse {
    let p = pal(ui);
    let m = metrics(ui);
    let compact = m.density == Density::Compact;
    let mut out = LayerRowResponse::default();
    let w = ui.available_width();
    let (rect, resp) = ui.allocate_exact_size(vec2(w, m.row_h), Sense::click());
    out.rect = rect;
    if !ui.is_rect_visible(rect) {
        return out;
    }
    let hov = resp.hovered();
    let bg = if row.selected { p.accent_subtle } else if hov { p.surface_hover } else { p.surface_raised };
    ui.painter().rect_filled(rect, cr(radius::MD), bg);
    if row.selected {
        ui.painter().rect_filled(Rect::from_min_size(rect.min, vec2(2.0, rect.height())), CornerRadius { nw: radius::MD, sw: radius::MD, ne: 0, se: 0 }, p.accent);
    }
    let mut x = rect.left() + space::XXS;
    let cy = rect.center().y;
    let small = |x: f32, s: f32| Rect::from_center_size(pos2(x + s / 2.0, cy), vec2(s, s));
    let isz = if compact { icon::SM - 1.0 } else { icon::SM };
    // drag handle
    let hw = if compact { 12.0 } else { 16.0 };
    let hr = Rect::from_min_size(pos2(x, rect.top()), vec2(hw, rect.height()));
    let hresp = ui.interact(hr, row.id.with("handle"), Sense::drag());
    if hresp.drag_started() {
        hresp.dnd_set_drag_payload(payload);
    }
    let hc = if hresp.hovered() || hresp.dragged() { p.text } else if hov { p.text_muted } else { p.text_disabled };
    Icon::Grip.paint(ui.painter(), small(x, hw), hc);
    if hresp.hovered() {
        ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
    }
    out.handle = Some(hresp.on_hover_text("Drag to reorder or drop into a folder"));
    x += hw;
    // nesting guides
    let indent = if compact { 12.0 } else { 14.0 };
    for k in 0..row.depth {
        let gx = x + indent * 0.5 + indent * k as f32;
        ui.painter().vline(gx, rect.y_range().shrink(space::XXS), Stroke::new(1.0, p.border_strong));
    }
    x += indent * row.depth as f32;
    // folder arrow
    if let Some(collapsed) = row.folder {
        let r = small(x, isz - 2.0);
        let a = ui.interact(r.expand(3.0), row.id.with("fold"), Sense::click());
        (if collapsed { Icon::ChevronRight } else { Icon::ChevronDown }).paint(ui.painter(), r, if a.hovered() { p.text } else { p.text_secondary });
        if a.on_hover_text(if collapsed { "Expand folder" } else { "Collapse folder" }).clicked() {
            out.toggle_collapse = true;
        }
    }
    x += isz;
    // visibility
    let vr = small(x, isz);
    let v = ui.interact(vr.expand(3.0), row.id.with("vis"), Sense::click());
    (if row.visible { Icon::Eye } else { Icon::EyeOff }).paint(ui.painter(), vr, if v.hovered() { p.text } else if row.visible { p.text_secondary } else { p.text_disabled });
    if v.on_hover_text(if row.visible { "Hide layer" } else { "Show layer" }).clicked() {
        out.toggle_visible = true;
    }
    x += isz + space::SM;
    // thumbnail
    let tr = small(x, m.thumb);
    (row.thumb)(ui.painter(), tr);
    ui.painter().rect_stroke(tr, cr(radius::SM), Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
    x += m.thumb + space::SM;
    // trailing: mask thumb, lock, opacity
    let mut right = rect.right() - space::XS;
    if let Some((generated, active)) = row.mask {
        let ms = m.thumb;
        let mr = Rect::from_center_size(pos2(right - ms / 2.0, cy), vec2(ms, ms));
        let mk = ui.interact(mr, row.id.with("mask"), Sense::click());
        ui.painter().rect_filled(mr, cr(radius::SM), p.well);
        ui.painter().rect_filled(Rect::from_min_max(mr.center_top(), mr.right_bottom()), CornerRadius { ne: radius::SM, se: radius::SM, nw: 0, sw: 0 }, p.text_secondary);
        if generated {
            Icon::Sparkle.paint(ui.painter(), Rect::from_center_size(mr.center(), vec2(ms * 0.5, ms * 0.5)), p.accent);
        }
        ui.painter().rect_stroke(mr, cr(radius::SM), Stroke::new(if active { 1.5 } else { 1.0 }, if active { p.accent } else if mk.hovered() { p.text_muted } else { p.border_strong }), StrokeKind::Outside);
        if mk.on_hover_ui(|ui| tooltip_body(ui, "Mask", Some("Where this layer shows. Click to select the mask and paint on it (white reveals, black hides)."), None)).clicked() {
            out.mask_clicked = true;
        }
        right -= ms + space::SM;
    }
    let lr = Rect::from_center_size(pos2(right - isz / 2.0, cy), vec2(isz, isz));
    let l = ui.interact(lr.expand(3.0), row.id.with("lock"), Sense::click());
    if row.locked || l.hovered() || hov {
        (if row.locked { Icon::Lock } else { Icon::Unlock }).paint(ui.painter(), lr, if row.locked { p.warn } else if l.hovered() { p.text } else { p.text_disabled });
    }
    if l.on_hover_text(if row.locked { "Unlock: allow painting" } else { "Lock: protect from painting and edits" }).clicked() {
        out.toggle_lock = true;
    }
    right -= isz + space::SM;
    if row.opacity < 0.999 {
        let t = format!("{:.0}%", row.opacity * 100.0);
        let g = ui.painter().layout_no_wrap(t, fonts::mono(font::CAPTION - 0.5), p.text_muted);
        right -= g.size().x;
        ui.painter().galley(pos2(right, cy - g.size().y / 2.0), g, p.text_muted);
        right -= space::SM;
    }
    // name and subtitle
    let name_c = if row.shown { p.text } else { p.text_muted };
    let name_font = if row.selected { fonts::semibold(font::BODY) } else { fonts::regular(font::BODY) };
    let avail = (right - x).max(10.0);
    out.name_rect = Rect::from_min_max(pos2(x - space::XS, rect.top() + space::XXS), pos2(right, rect.bottom() - space::XXS));
    let mut cut;
    if compact {
        let ng = elided(ui.painter(), row.name, name_font, name_c, avail);
        cut = ng.elided;
        let nw = ng.size().x;
        ui.painter().galley(pos2(x, cy - ng.size().y / 2.0), ng, name_c);
        let rest = avail - nw - space::SM;
        if rest > 24.0 && !row.subtitle.is_empty() {
            let sg = elided(ui.painter(), row.subtitle, fonts::regular(font::CAPTION - 0.5), p.text_muted, rest);
            cut |= sg.elided;
            ui.painter().galley(pos2(x + nw + space::SM, cy - sg.size().y / 2.0 + 0.5), sg, p.text_muted);
        } else {
            cut |= !row.subtitle.is_empty();
        }
    } else {
        let ng = elided(ui.painter(), row.name, name_font, name_c, avail);
        cut = ng.elided;
        ui.painter().galley(pos2(x, cy - 1.0 - ng.size().y), ng, name_c);
        let sg = elided(ui.painter(), row.subtitle, fonts::regular(font::CAPTION), p.text_muted, avail);
        ui.painter().galley(pos2(x, cy + 2.0), sg, p.text_muted);
    }
    out.clicked = resp.clicked();
    out.double_clicked = resp.double_clicked();
    // the full name and kind when they're cut short
    out.context = Some(if cut { resp.on_hover_text(format!("{} · {}", row.name, row.subtitle)) } else { resp });
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
            ui.painter().hline(rect.x_range(), rect.top() - 1.0, Stroke::new(2.0, p.accent));
            ui.painter().circle_filled(pos2(rect.left() + 2.0, rect.top() - 1.0), 3.0, p.accent);
        }
        DropZone::Below => {
            ui.painter().hline(rect.x_range(), rect.bottom() + 1.0, Stroke::new(2.0, p.accent));
            ui.painter().circle_filled(pos2(rect.left() + 2.0, rect.bottom() + 1.0), 3.0, p.accent);
        }
        DropZone::Into => {
            ui.painter().rect(rect, cr(radius::MD), p.accent.gamma_multiply(0.12), Stroke::new(1.5, p.accent), StrokeKind::Inside);
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
        // hovering a toast keeps it on screen
        let hovered: Option<u64> = self.list.iter().find(|t| ctx.data(|d| d.get_temp::<bool>(egui::Id::NULL.with(("toast hover", t.id)))).unwrap_or(false)).map(|t| t.id);
        for t in &mut self.list {
            if Some(t.id) == hovered && !t.sticky {
                t.born = t.born.max(now - life(t) + 1.0);
            }
        }
        self.list.retain(|t| t.sticky || now - t.born < life(t));
        let mut y = anchor.bottom() - space::MD;
        let mut close = None;
        for t in self.list.iter().rev() {
            let age = (now - t.born) as f32;
            let fade = if t.sticky { 1.0 } else { ((life(t) as f32 - age) / motion::SLOW).clamp(0.0, 1.0) };
            let slide = (1.0 - motion::ease_out(age / motion::NORMAL)) * space::MD;
            let area = egui::Area::new(egui::Id::NULL.with(("toast", t.id))).order(egui::Order::Foreground).pivot(Align2::RIGHT_BOTTOM).fixed_pos(pos2(anchor.right() - space::MD, y + slide)).interactable(true);
            let r = area.show(ctx, |ui| {
                ui.set_opacity(fade);
                let (ic, c) = match t.kind {
                    ToastKind::Info => (Icon::Info, p.info),
                    ToastKind::Success => (Icon::Success, p.success),
                    ToastKind::Warn => (Icon::Warning, p.warn),
                    ToastKind::Error => (Icon::Error, p.danger),
                    ToastKind::Progress => (Icon::History, p.accent),
                };
                let fr = overlay_frame(&p).inner_margin(egui::Margin { left: space::MD as i8, right: space::XS as i8, top: space::SM as i8, bottom: space::SM as i8 }).show(ui, |ui| {
                    ui.set_width(268.0);
                    ui.spacing_mut().item_spacing = vec2(space::SM, space::XXS);
                    ui.horizontal(|ui| {
                        ui.vertical(|ui| {
                            ui.add_space(1.0);
                            if t.kind == ToastKind::Progress {
                                let (r, _) = ui.allocate_exact_size(vec2(icon::SM, icon::SM), Sense::hover());
                                icons::spinner(ui.painter(), r, c, now);
                            } else {
                                ic.show(ui, icon::SM, c);
                            }
                        });
                        ui.vertical(|ui| {
                            ui.horizontal(|ui| {
                                ui.label(strong(&t.title, font::SMALL));
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Min), |ui| {
                                    if !t.sticky && ui.add(IconBtn::new(Icon::Close, "Dismiss").size(16.0)).clicked() {
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
                // a thin status-coloured edge on the left
                let er = fr.response.rect;
                ui.painter().rect_filled(Rect::from_min_size(er.min + vec2(0.0, space::XS), vec2(2.0, er.height() - space::MD)), cr(1), c);
            });
            let hov = r.response.contains_pointer();
            ctx.data_mut(|d| d.insert_temp(egui::Id::NULL.with(("toast hover", t.id)), hov));
            y -= r.response.rect.height() + space::SM;
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

/// A centred dialog over a scrim, with a close button. Returns the closure's
/// result and whether the user dismissed it (Esc, the x, or a click outside).
pub fn modal<R>(ctx: &egui::Context, id: &str, title: &str, width: f32, add: impl FnOnce(&mut Ui) -> R) -> (R, bool) {
    let p = theme(ctx).p;
    let mut closed = false;
    let m = egui::Modal::new(egui::Id::NULL.with(("modal", id)))
        .backdrop_color(p.scrim)
        .frame(egui::Frame::new().fill(p.overlay).stroke(Stroke::new(1.0, p.border_strong)).corner_radius(cr(radius::XL)).shadow(elevation(3, &p)).inner_margin(egui::Margin::same(space::XL as i8)));
    let r = m.show(ctx, |ui| {
        ui.set_width(width);
        ui.horizontal(|ui| {
            ui.label(strong(title, font::HEADING));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.add(IconBtn::new(Icon::Close, "Close").shortcut("Esc")).clicked() {
                    closed = true;
                }
            });
        });
        ui.add_space(space::SM);
        add(ui)
    });
    let dismissed = r.should_close() || closed;
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

fn is_word_start(t: &[char], i: usize) -> bool {
    i == 0 || !t[i - 1].is_alphanumeric() || (t[i].is_uppercase() && t[i - 1].is_lowercase())
}

/// One query word against `t`: the best placement where every run of
/// matched letters starts a word (or the whole word is a substring).
fn fuzzy_word(q: &[char], t: &[char], tl: &[char]) -> Option<(i32, Vec<usize>)> {
    if q.is_empty() {
        return Some((0, vec![]));
    }
    let mut best: Option<(i32, Vec<usize>)> = None;
    // 1) contiguous substring
    for s in 0..tl.len() {
        if tl[s..].starts_with(q) {
            let ws = is_word_start(t, s);
            let score = q.len() as i32 * 16 + if ws { 40 } else { 0 } + if s == 0 { 30 } else { 0 } - (s as i32).min(20);
            if best.as_ref().is_none_or(|b| score > b.0) {
                best = Some((score, (s..s + q.len()).collect()));
            }
        }
    }
    // 2) runs that each start a word ("adv mo" -> Advanced mode, "ec" -> Edge Crack)
    let mut qi = 0;
    let mut idx = vec![];
    let mut i = 0;
    while i < tl.len() && qi < q.len() {
        if is_word_start(t, i) && tl[i] == q[qi] {
            while i < tl.len() && qi < q.len() && tl[i] == q[qi] {
                idx.push(i);
                qi += 1;
                i += 1;
            }
        } else {
            i += 1;
        }
    }
    if qi == q.len() {
        let runs = 1 + idx.windows(2).filter(|w| w[1] != w[0] + 1).count() as i32;
        let score = q.len() as i32 * 14 + 30 - runs * 6 + if idx[0] == 0 { 20 } else { 0 };
        if best.as_ref().is_none_or(|b| score > b.0) {
            best = Some((score, idx));
        }
    }
    best
}

/// Fuzzy match: every word of `query` must match `text` as a substring or as
/// word-initial runs. Returns a score (higher is better) and the matched
/// character positions, for highlighting.
pub fn fuzzy_match(query: &str, text: &str) -> Option<(i32, Vec<usize>)> {
    let t: Vec<char> = text.chars().collect();
    let tl: Vec<char> = text.to_lowercase().chars().collect();
    if tl.len() != t.len() {
        return None;
    }
    let mut score = 0;
    let mut all = vec![];
    for w in query.split_whitespace() {
        let q: Vec<char> = w.to_lowercase().chars().collect();
        let (s, idx) = fuzzy_word(&q, &t, &tl)?;
        score += s;
        all.extend(idx);
    }
    all.sort_unstable();
    all.dedup();
    Some((score - t.len() as i32 / 8, all))
}

/// Fuzzy match score (higher is better), None if no match.
pub fn fuzzy_score(query: &str, text: &str) -> Option<i32> {
    fuzzy_match(query, text).map(|m| m.0)
}

#[derive(Default)]
pub struct Palette2State {
    pub open: bool,
    pub query: String,
    pub cursor: usize,
    /// Recently run command ids, newest first (shown first on an empty query).
    pub recent: Vec<String>,
}

impl Palette2State {
    pub fn remember(&mut self, id: &str) {
        self.recent.retain(|r| r != id);
        self.recent.insert(0, id.to_string());
        self.recent.truncate(8);
    }
}

/// Rank the commands for a query: matches by score; an empty query lists
/// recent commands first, then everything in its original order.
pub fn rank_commands<'c>(query: &str, recent: &[String], commands: &'c [Command]) -> Vec<(&'c Command, Vec<usize>, bool)> {
    if query.trim().is_empty() {
        let mut v: Vec<(&Command, Vec<usize>, bool)> = recent.iter().filter_map(|r| commands.iter().find(|c| &c.id == r)).map(|c| (c, vec![], true)).collect();
        v.extend(commands.iter().filter(|c| !recent.contains(&c.id)).map(|c| (c, vec![], false)));
        return v;
    }
    let mut ranked: Vec<(i32, &Command, Vec<usize>)> = commands
        .iter()
        .filter_map(|c| {
            let title = fuzzy_match(query, &c.title);
            let with_group = fuzzy_match(query, &format!("{} {}", c.title, c.group)).map(|(s, i)| (s - 12, i.into_iter().filter(|k| *k < c.title.chars().count()).collect()));
            let (mut s, idx) = match (title, with_group) {
                (Some(a), Some(b)) => if a.0 >= b.0 { a } else { b },
                (a, b) => a.or(b)?,
            };
            if let Some(k) = recent.iter().position(|r| *r == c.id) {
                s += 12 - k as i32;
            }
            Some((s, c, idx))
        })
        .collect();
    ranked.sort_by(|a, b| b.0.cmp(&a.0));
    ranked.into_iter().map(|(_, c, i)| (c, i, false)).collect()
}

fn highlighted(title: &str, idx: &[usize], base: Color32, hi: Color32, font: FontId) -> LayoutJob {
    let mut job = LayoutJob::default();
    for (k, ch) in title.chars().enumerate() {
        let on = idx.contains(&k);
        job.append(&ch.to_string(), 0.0, TextFormat { font_id: if on { fonts::semibold(font.size) } else { font.clone() }, color: if on { hi } else { base }, ..Default::default() });
    }
    job
}

/// The command palette (Ctrl+K): fuzzy search over every action, matched
/// letters highlighted, recent commands first. Arrows / Tab move, Enter runs,
/// Esc closes. Returns the chosen command id.
pub fn command_palette(ctx: &egui::Context, st: &mut Palette2State, commands: &[Command]) -> Option<String> {
    if !st.open {
        return None;
    }
    let p = theme(ctx).p;
    let m = theme(ctx).m;
    let ranked = rank_commands(&st.query, &st.recent, commands);
    let (up, down, enter, esc, pgup, pgdn) = ctx.input(|i| {
        (
            i.key_pressed(egui::Key::ArrowUp) || (i.key_pressed(egui::Key::Tab) && i.modifiers.shift),
            i.key_pressed(egui::Key::ArrowDown) || (i.key_pressed(egui::Key::Tab) && !i.modifiers.shift),
            i.key_pressed(egui::Key::Enter),
            i.key_pressed(egui::Key::Escape),
            i.key_pressed(egui::Key::PageUp),
            i.key_pressed(egui::Key::PageDown),
        )
    });
    let n = ranked.len();
    let moved = up || down || pgup || pgdn;
    if down {
        st.cursor = if st.cursor + 1 >= n { 0 } else { st.cursor + 1 };
    }
    if up {
        st.cursor = if st.cursor == 0 { n.saturating_sub(1) } else { st.cursor - 1 };
    }
    if pgdn {
        st.cursor = (st.cursor + 8).min(n.saturating_sub(1));
    }
    if pgup {
        st.cursor = st.cursor.saturating_sub(8);
    }
    st.cursor = st.cursor.min(n.saturating_sub(1));
    let mut chosen = None;
    if esc {
        st.open = false;
        st.query.clear();
        st.cursor = 0;
        return None;
    }
    if enter {
        chosen = ranked.get(st.cursor).map(|(c, _, _)| c.id.clone());
    }
    let screen = ctx.content_rect();
    let mut close = false;
    let area = egui::Area::new(egui::Id::NULL.with("command palette")).order(egui::Order::Foreground).fixed_pos(pos2(screen.center().x, screen.top() + 72.0)).pivot(Align2::CENTER_TOP).show(ctx, |ui| {
        overlay_frame(&p).shadow(elevation(3, &p)).inner_margin(egui::Margin::same(space::SM as i8)).show(ui, |ui| {
            ui.set_width(560.0);
            ui.spacing_mut().item_spacing.y = 0.0;
            let r = search_field(ui, &mut st.query, "Search commands, panels, materials, lighting…");
            r.request_focus();
            if r.changed() {
                st.cursor = 0;
            }
            ui.add_space(space::XS);
            if ranked.is_empty() {
                ui.add_space(space::MD);
                ui.label(muted(ui, format!("Nothing matches \u{201c}{}\u{201d}. Try fewer letters, or a panel or material name.", st.query.trim())));
                ui.add_space(space::MD);
            }
            let row_h = m.control_h + 2.0;
            egui::ScrollArea::vertical().max_height(row_h * 12.0).auto_shrink([false, true]).show(ui, |ui| {
                let mut last_section: Option<&str> = None;
                for (k, (c, idx, recent)) in ranked.iter().enumerate() {
                    let section = if st.query.trim().is_empty() { if *recent { "Recent" } else { c.group } } else { "" };
                    if !section.is_empty() && last_section != Some(section) {
                        ui.add_space(space::XS);
                        ui.label(caption(ui, section));
                        ui.add_space(space::XXS);
                        last_section = Some(section);
                    }
                    let on = k == st.cursor;
                    let (rect, resp) = ui.allocate_exact_size(vec2(ui.available_width(), row_h), Sense::click());
                    if on && moved {
                        ui.scroll_to_rect(rect, None);
                    }
                    if on || resp.hovered() {
                        ui.painter().rect_filled(rect, cr(radius::MD), if on { p.surface_hover } else { p.surface_raised });
                    }
                    if on {
                        ui.painter().rect_filled(Rect::from_min_size(rect.min + vec2(0.0, 4.0), vec2(2.0, rect.height() - 8.0)), cr(1), p.accent);
                    }
                    c.icon.paint(ui.painter(), Rect::from_center_size(pos2(rect.left() + space::MD + icon::SM / 2.0, rect.center().y), vec2(icon::SM, icon::SM)), if on { p.accent } else { p.text_muted });
                    let job = highlighted(&c.title, idx, p.text, p.accent, fonts::regular(font::BODY));
                    let g = ui.painter().layout_job(job);
                    ui.painter().galley(pos2(rect.left() + space::MD * 2.0 + icon::SM, rect.center().y - g.size().y / 2.0), g, p.text);
                    let mut rx = rect.right() - space::SM;
                    if let Some(s) = c.shortcut {
                        let g = ui.painter().layout_no_wrap(s.to_string(), fonts::mono(font::CAPTION - 0.5), p.text_secondary);
                        let kr = Rect::from_min_size(pos2(rx - g.size().x - space::SM, rect.center().y - g.size().y / 2.0 - 1.5), g.size() + vec2(space::SM, 3.0));
                        ui.painter().rect(kr, cr(radius::SM), p.surface_raised, Stroke::new(1.0, p.border_strong), StrokeKind::Inside);
                        ui.painter().galley(kr.min + vec2(space::XS - 1.0, 1.5), g, p.text_secondary);
                        rx = kr.left() - space::MD;
                    }
                    if !st.query.trim().is_empty() || *recent {
                        ui.painter().text(pos2(rx, rect.center().y), Align2::RIGHT_CENTER, c.group, fonts::regular(font::CAPTION), p.text_muted);
                    }
                    if resp.clicked() {
                        chosen = Some(c.id.clone());
                    }
                }
            });
            ui.add_space(space::XS);
            ui.painter().hline(ui.min_rect().x_range(), ui.cursor().top(), Stroke::new(1.0, p.border));
            ui.add_space(space::XS);
            ui.horizontal(|ui| {
                ui.spacing_mut().item_spacing.x = space::XS;
                for (k, a) in [("↑↓", "move"), ("Enter", "run"), ("Esc", "close")] {
                    kbd(ui, k);
                    ui.label(text(a, font::CAPTION).color(p.text_muted));
                    ui.add_space(space::SM);
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(text(format!("{n} commands"), font::CAPTION).color(p.text_muted));
                });
            });
        });
    });
    // a click outside closes it
    if ctx.input(|i| i.pointer.any_pressed()) && !area.response.contains_pointer() && ctx.pointer_latest_pos().is_some_and(|pt| !area.response.rect.contains(pt)) {
        close = true;
    }
    if let Some(id) = &chosen {
        st.remember(id);
    }
    if chosen.is_some() || close {
        st.open = false;
        st.query.clear();
        st.cursor = 0;
    }
    chosen
}

/// A font id for custom painting at a type-scale size.
pub fn font_id(size: f32) -> FontId {
    fonts::regular(size)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fuzzy_prefers_word_starts_and_rejects_scatter() {
        // scattered letters across words don't match
        assert!(fuzzy_match("rus", "Re-bake AO + curvature").is_none());
        // word-start runs and substrings do
        assert!(fuzzy_match("adv mode", "Switch to Advanced mode").is_some());
        assert!(fuzzy_match("ec", "Edge crack").is_some());
        let a = fuzzy_score("rus", "Apply Rusty steel").unwrap();
        let b = fuzzy_score("rus", "Foliage brush").unwrap();
        assert!(a > b, "word start {a} beats mid-word {b}");
        let (_, idx) = fuzzy_match("exp tex", "Export textures…").unwrap();
        assert_eq!(idx, vec![0, 1, 2, 7, 8, 9]);
        assert!(fuzzy_score("", "anything").is_some());
    }

    #[test]
    fn ranking_puts_recent_first_and_best_match_first() {
        let c = |id: &str, title: &str, group: &'static str| Command { id: id.into(), title: title.into(), group, shortcut: None, icon: Icon::Sparkle };
        let cmds = vec![c("export", "Export textures…", "File"), c("rebake", "Re-bake AO + curvature", "Texture set"), c("rusty", "Apply Rusty steel", "Materials"), c("lay", "Show Layers panel", "Window")];
        let r = rank_commands("rus", &[], &cmds);
        assert_eq!(r[0].0.id, "rusty");
        assert!(!r.iter().any(|x| x.0.id == "rebake"));
        let r = rank_commands("", &["lay".to_string()], &cmds);
        assert_eq!(r[0].0.id, "lay");
        assert!(r[0].2, "flagged recent");
        assert_eq!(r.len(), cmds.len());
        // the group name matches too ("window layers")
        assert_eq!(rank_commands("window lay", &[], &cmds)[0].0.id, "lay");
    }

    #[test]
    fn units_format_and_parse() {
        assert_eq!(Unit::Percent.format(0.62), "62%");
        assert_eq!(Unit::Percent.parse("45"), Some(0.45));
        assert_eq!(Unit::Percent.parse("45 %"), Some(0.45));
        assert_eq!(Unit::Suffix(" px", 0).format(60.0), "60 px");
        assert_eq!(Unit::Suffix(" px", 0).parse("80px"), Some(80.0));
        assert_eq!(Unit::Suffix(" m", 2).parse("0.5+0.25"), Some(0.75));
        assert_eq!(Unit::Plain(2).parse("2*3"), Some(6.0));
        assert_eq!(Unit::Plain(2).parse("-3"), Some(-3.0));
        assert_eq!(Unit::Plain(2).parse("abc"), None);
        assert_eq!(nice_step(39.9), 50.0);
        assert!((nice_step(0.05) - 0.05).abs() < 1e-6);
        assert_eq!(nice_step(18.0), 20.0);
        // log mapping round-trips
        let t = field_norm(60.0, 2.0, 800.0, true);
        assert!((field_denorm(t, 2.0, 800.0, true) - 60.0).abs() < 0.01);
    }
}
