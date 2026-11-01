//! Pigment's design system: tokens (colour roles, spacing, radii, elevation,
//! type, icon sizes, motion), the embedded fonts, a vector icon set and a
//! component library built on egui. Every screen is built from these; raw
//! colours and magic sizes outside this module are rejected by
//! `design::tests::no_raw_styles_outside_design`.
//!
//! See `docs/design/DESIGN_SYSTEM.md`.

pub mod components;
pub mod fonts;
pub mod gallery;
pub mod icons;

pub use components::*;
pub use icons::Icon;

use eframe::egui;
use egui::{Color32, CornerRadius, Margin, Shadow, Stroke};

// ------------------------------------------------------------------ colour

/// Semantic colour roles. Screens ask for a role, never a colour.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Palette {
    /// Behind everything (viewport surround, window background).
    pub bg: Color32,
    /// Panels.
    pub surface: Color32,
    /// Cards and rows on a panel.
    pub surface_raised: Color32,
    /// Hovered rows, pressed secondary buttons.
    pub surface_hover: Color32,
    /// Text fields, sliders' tracks, wells.
    pub well: Color32,
    /// Floating things: menus, popovers, toasts, dialogs.
    pub overlay: Color32,
    /// Translucent glass behind viewport HUD chips.
    pub glass: Color32,
    pub border: Color32,
    pub border_strong: Color32,
    pub text: Color32,
    pub text_secondary: Color32,
    pub text_muted: Color32,
    pub text_disabled: Color32,
    pub accent: Color32,
    pub accent_hover: Color32,
    pub accent_pressed: Color32,
    /// Tinted background for selected things.
    pub accent_subtle: Color32,
    /// Text / icons drawn on an accent fill.
    pub on_accent: Color32,
    pub success: Color32,
    pub warn: Color32,
    pub danger: Color32,
    pub info: Color32,
    pub focus: Color32,
    pub selection: Color32,
    /// Scrim behind modals.
    pub scrim: Color32,
    pub shadow: Color32,
}

const fn rgb(r: u8, g: u8, b: u8) -> Color32 {
    Color32::from_rgb(r, g, b)
}

impl Palette {
    pub const DARK: Palette = Palette {
        bg: rgb(17, 18, 21),
        surface: rgb(27, 29, 33),
        surface_raised: rgb(35, 38, 43),
        surface_hover: rgb(45, 49, 55),
        well: rgb(19, 21, 24),
        overlay: rgb(36, 39, 45),
        glass: Color32::from_rgba_premultiplied(14, 15, 17, 196),
        border: rgb(51, 55, 62),
        border_strong: rgb(72, 77, 86),
        text: rgb(236, 238, 241),
        text_secondary: rgb(186, 191, 199),
        text_muted: rgb(140, 146, 156),
        text_disabled: rgb(92, 98, 107),
        accent: rgb(240, 138, 60),
        accent_hover: rgb(255, 160, 88),
        accent_pressed: rgb(214, 116, 42),
        accent_subtle: rgb(64, 43, 28),
        on_accent: rgb(26, 16, 6),
        success: rgb(76, 195, 138),
        warn: rgb(242, 179, 61),
        danger: rgb(240, 96, 90),
        info: rgb(96, 170, 240),
        focus: rgb(125, 183, 255),
        selection: rgb(86, 56, 32),
        scrim: Color32::from_rgba_premultiplied(0, 0, 0, 150),
        shadow: Color32::from_rgba_premultiplied(0, 0, 0, 110),
    };

    pub const LIGHT: Palette = Palette {
        bg: rgb(222, 225, 230),
        surface: rgb(244, 245, 247),
        surface_raised: rgb(255, 255, 255),
        surface_hover: rgb(232, 235, 239),
        well: rgb(234, 236, 240),
        overlay: rgb(255, 255, 255),
        glass: Color32::from_rgba_premultiplied(236, 238, 241, 214),
        border: rgb(212, 216, 222),
        border_strong: rgb(178, 184, 193),
        text: rgb(22, 24, 28),
        text_secondary: rgb(62, 67, 75),
        text_muted: rgb(96, 103, 113),
        text_disabled: rgb(160, 166, 175),
        accent: rgb(210, 98, 22),
        accent_hover: rgb(230, 114, 34),
        accent_pressed: rgb(184, 84, 16),
        accent_subtle: rgb(251, 226, 205),
        on_accent: rgb(255, 255, 255),
        success: rgb(26, 140, 86),
        warn: rgb(176, 112, 0),
        danger: rgb(200, 52, 46),
        info: rgb(28, 112, 200),
        focus: rgb(36, 112, 220),
        selection: rgb(248, 214, 186),
        scrim: Color32::from_rgba_premultiplied(10, 12, 16, 90),
        shadow: Color32::from_rgba_premultiplied(0, 0, 0, 40),
    };
}

// ------------------------------------------------------------------ scales

/// Spacing scale (points). Layouts use these steps only.
pub mod space {
    pub const XXS: f32 = 2.0;
    pub const XS: f32 = 4.0;
    pub const SM: f32 = 6.0;
    pub const MD: f32 = 8.0;
    pub const LG: f32 = 12.0;
    pub const XL: f32 = 16.0;
    pub const XXL: f32 = 24.0;
    pub const XXXL: f32 = 32.0;
}

/// Corner radii.
pub mod radius {
    pub const SM: u8 = 4;
    pub const MD: u8 = 6;
    pub const LG: u8 = 10;
    pub const XL: u8 = 14;
    pub const PILL: u8 = 255;
}

/// Elevation: 0 = flat, 1 = cards on hover, 2 = menus / popovers / toasts, 3 = dialogs.
pub fn elevation(level: u8, p: &Palette) -> Shadow {
    match level {
        0 => Shadow::NONE,
        1 => Shadow { offset: [0, 1], blur: 4, spread: 0, color: p.shadow.gamma_multiply(0.6) },
        2 => Shadow { offset: [0, 4], blur: 16, spread: 0, color: p.shadow },
        _ => Shadow { offset: [0, 12], blur: 36, spread: 2, color: p.shadow },
    }
}

/// Type scale (points) on Inter, values in JetBrains Mono.
pub mod font {
    pub const CAPTION: f32 = 11.0;
    pub const SMALL: f32 = 12.0;
    pub const BODY: f32 = 13.5;
    pub const TITLE: f32 = 15.0;
    pub const HEADING: f32 = 18.0;
    pub const DISPLAY: f32 = 28.0;
    pub const MONO: f32 = 12.5;
}

/// Icon sizes (points) and the stroke width at the 18 pt design grid.
pub mod icon {
    pub const SM: f32 = 14.0;
    pub const MD: f32 = 18.0;
    pub const LG: f32 = 24.0;
    pub const XL: f32 = 40.0;
    pub const STROKE: f32 = 1.6;
}

/// Control sizes.
pub mod size {
    pub const CONTROL_H: f32 = 28.0;
    pub const CONTROL_H_SM: f32 = 22.0;
    pub const TOOL: f32 = 36.0;
    pub const ROW_H: f32 = 44.0;
    pub const THUMB: f32 = 32.0;
    pub const TILE: f32 = 92.0;
    pub const TAB_H: f32 = 30.0;
    pub const SPLITTER: f32 = 4.0;
    pub const SLIDER_W: f32 = 140.0;
    pub const SIDEBAR: f32 = 300.0;
    pub const DIALOG_W: f32 = 520.0;
}

/// Motion: durations (seconds) and easing.
pub mod motion {
    pub const FAST: f32 = 0.08;
    pub const NORMAL: f32 = 0.16;
    pub const SLOW: f32 = 0.28;
    /// Toasts stay this long before fading.
    pub const TOAST: f32 = 4.0;
    pub fn ease_out(t: f32) -> f32 {
        let t = t.clamp(0.0, 1.0);
        1.0 - (1.0 - t).powi(3)
    }
    pub fn ease_in_out(t: f32) -> f32 {
        let t = t.clamp(0.0, 1.0);
        if t < 0.5 {
            4.0 * t * t * t
        } else {
            1.0 - (-2.0 * t + 2.0).powi(3) / 2.0
        }
    }
}

// ------------------------------------------------------------------ theme

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default, serde::Serialize, serde::Deserialize)]
pub enum ThemeKind {
    #[default]
    Dark,
    Light,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Theme {
    pub kind: ThemeKind,
    pub p: Palette,
}

impl Theme {
    pub fn new(kind: ThemeKind) -> Theme {
        Theme { kind, p: if kind == ThemeKind::Dark { Palette::DARK } else { Palette::LIGHT } }
    }
}

fn theme_id() -> egui::Id {
    egui::Id::NULL.with("pigment.design.theme")
}

/// The theme in effect (dark until `apply` says otherwise).
pub fn theme(ctx: &egui::Context) -> Theme {
    ctx.data(|d| d.get_temp::<Theme>(theme_id())).unwrap_or(Theme::new(ThemeKind::Dark))
}

/// Shorthand: the palette in effect for this `Ui`.
pub fn pal(ui: &egui::Ui) -> Palette {
    theme(ui.ctx()).p
}

/// Fonts, theme and UI scale from the user's preferences.
pub fn install(ctx: &egui::Context, prefs: &crate::app::prefs::Prefs) {
    fonts::install(ctx);
    apply(ctx, prefs.theme);
    ctx.set_zoom_factor(prefs.ui_scale.clamp(0.75, 2.0));
}

/// Switch the theme: egui's visuals are derived from the palette.
pub fn apply(ctx: &egui::Context, kind: ThemeKind) {
    let t = Theme::new(kind);
    ctx.data_mut(|d| d.insert_temp(theme_id(), t));
    let p = t.p;
    let mut v = if kind == ThemeKind::Dark { egui::Visuals::dark() } else { egui::Visuals::light() };
    v.panel_fill = p.surface;
    v.window_fill = p.overlay;
    v.window_stroke = Stroke::new(1.0, p.border);
    v.window_shadow = elevation(3, &p);
    v.popup_shadow = elevation(2, &p);
    v.window_corner_radius = CornerRadius::same(radius::LG);
    v.menu_corner_radius = CornerRadius::same(radius::MD);
    v.extreme_bg_color = p.well;
    v.faint_bg_color = p.surface_raised;
    v.code_bg_color = p.well;
    v.override_text_color = None;
    v.hyperlink_color = p.accent;
    v.warn_fg_color = p.warn;
    v.error_fg_color = p.danger;
    v.selection.bg_fill = p.selection;
    v.selection.stroke = Stroke::new(1.0, p.accent);
    v.text_cursor.stroke = Stroke::new(2.0, p.accent);
    v.slider_trailing_fill = true;
    v.handle_shape = egui::style::HandleShape::Circle;
    let w = &mut v.widgets;
    for (state, bg, fg, stroke) in [
        (&mut w.noninteractive, p.surface, p.text_secondary, p.border),
        (&mut w.inactive, p.surface_raised, p.text, p.border),
        (&mut w.hovered, p.surface_hover, p.text, p.border_strong),
        (&mut w.active, p.accent_subtle, p.text, p.accent),
        (&mut w.open, p.surface_hover, p.text, p.border_strong),
    ] {
        state.bg_fill = bg;
        state.weak_bg_fill = bg;
        state.fg_stroke = Stroke::new(1.2, fg);
        state.bg_stroke = Stroke::new(1.0, stroke);
        state.corner_radius = CornerRadius::same(radius::MD);
        state.expansion = 0.0;
    }
    w.noninteractive.bg_stroke = Stroke::new(1.0, p.border);
    w.inactive.bg_stroke = Stroke::NONE;
    ctx.set_visuals_of(egui::Theme::Dark, v.clone());
    ctx.set_visuals_of(egui::Theme::Light, v);
    ctx.set_theme(if kind == ThemeKind::Dark { egui::Theme::Dark } else { egui::Theme::Light });
    ctx.all_styles_mut(|s| {
        s.spacing.item_spacing = egui::vec2(space::MD, space::SM);
        s.spacing.button_padding = egui::vec2(space::MD + 2.0, space::XS);
        s.spacing.slider_width = size::SLIDER_W;
        s.spacing.interact_size = egui::vec2(40.0, size::CONTROL_H_SM);
        s.spacing.menu_margin = Margin::same(space::SM as i8);
        s.spacing.window_margin = Margin::same(space::XL as i8);
        s.spacing.indent = space::XL;
        s.spacing.combo_width = 140.0;
        s.spacing.scroll = egui::style::ScrollStyle { bar_width: 8.0, floating: true, ..egui::style::ScrollStyle::floating() };
        s.interaction.tooltip_delay = 0.35;
        s.animation_time = motion::NORMAL;
        s.text_styles = fonts::text_styles();
    });
}

/// Panel / bar frames.
pub fn panel_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.surface).inner_margin(Margin::same(space::LG as i8))
}

pub fn bar_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.surface).inner_margin(Margin::symmetric(space::LG as i8, space::SM as i8)).stroke(Stroke::new(1.0, p.border))
}

/// Untinted image drawing (not a colour role).
pub const IMAGE_TINT: Color32 = Color32::WHITE;

/// sRGB 0..1 material colour to a display colour (data, not a design token).
pub fn srgb(c: [f32; 3]) -> Color32 {
    let b = c.map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8);
    Color32::from_rgb(b[0], b[1], b[2])
}

/// Relative luminance contrast ratio (WCAG) between two colours.
pub fn contrast(a: Color32, b: Color32) -> f32 {
    let lum = |c: Color32| {
        let f = |v: u8| {
            let s = v as f32 / 255.0;
            if s <= 0.04045 {
                s / 12.92
            } else {
                ((s + 0.055) / 1.055).powf(2.4)
            }
        };
        0.2126 * f(c.r()) + 0.7152 * f(c.g()) + 0.0722 * f(c.b())
    };
    let (x, y) = (lum(a), lum(b));
    (x.max(y) + 0.05) / (x.min(y) + 0.05)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Text roles stay readable on every surface (WCAG AA: 4.5 body, 3 large/muted).
    #[test]
    fn text_contrast_meets_wcag() {
        for p in [Palette::DARK, Palette::LIGHT] {
            for bg in [p.surface, p.surface_raised, p.overlay, p.bg] {
                assert!(contrast(p.text, bg) >= 7.0, "primary text {:?} on {:?}", p.text, bg);
                assert!(contrast(p.text_secondary, bg) >= 4.5, "secondary on {:?}", bg);
                assert!(contrast(p.text_muted, bg) >= 3.0, "muted on {:?}: {}", bg, contrast(p.text_muted, bg));
            }
            assert!(contrast(p.on_accent, p.accent) >= 3.0, "on-accent {}", contrast(p.on_accent, p.accent));
        }
    }

    /// Screens use tokens and components only: no raw colours, font sizes or
    /// spacing literals outside `design/`.
    #[test]
    fn no_raw_styles_outside_design() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src/app");
        let mut files = vec![];
        for name in ["ui.rs", "tour.rs", "welcome.rs", "dock.rs", "dialogs.rs", "folders_ui.rs"] {
            files.push(root.join(name));
        }
        for e in std::fs::read_dir(root.join("panels")).into_iter().flatten().flatten() {
            files.push(e.path());
        }
        let banned = [
            "Color32::from_rgb",
            "Color32::from_gray",
            "Color32::from_rgba",
            "Color32::from_black_alpha",
            "Color32::from_white_alpha",
            "Color32::WHITE",
            "Color32::BLACK",
            "Color32::LIGHT_GRAY",
            "Color32::DARK_GRAY",
            "add_space(0",
            "add_space(1",
            "add_space(2",
            "add_space(3",
            "add_space(4",
            "add_space(5",
            "add_space(6",
            "add_space(7",
            "add_space(8",
            "add_space(9",
            "Margin::same(1",
            "Margin::same(2",
            "Margin::same(4",
            "Margin::same(6",
            "Margin::same(8",
            "Margin::symmetric(1",
            "Margin::symmetric(2",
            "Margin::symmetric(4",
            "Margin::symmetric(6",
            "Margin::symmetric(8",
            "CornerRadius::same(1",
            "CornerRadius::same(2",
            "CornerRadius::same(3",
            "CornerRadius::same(4",
            "CornerRadius::same(5",
            "CornerRadius::same(6",
            "CornerRadius::same(8",
            ".size(1",
            ".size(2",
        ];
        let mut bad = vec![];
        for f in files.iter().filter(|f| f.exists()) {
            let src = std::fs::read_to_string(f).unwrap();
            for (n, line) in src.lines().enumerate() {
                for b in banned {
                    if line.contains(b) && !line.contains("lint: allow") {
                        bad.push(format!("{}:{}: `{b}` in `{}`", f.file_name().unwrap().to_string_lossy(), n + 1, line.trim()));
                    }
                }
            }
        }
        assert!(bad.is_empty(), "use design tokens / components instead:\n{}", bad.join("\n"));
    }
}
