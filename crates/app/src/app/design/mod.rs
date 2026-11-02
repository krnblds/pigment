//! Pigment's design system: tokens (colour roles, spacing, radii, elevation,
//! type, icon sizes, motion, density), the embedded fonts, a vector icon set
//! and a component library built on egui. Every screen is built from these;
//! raw colours and magic sizes outside this module are rejected by
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
///
/// The dark theme is a near-black, low-chroma neutral (a hint of cool) so the
/// model and its materials are the brightest, most colourful thing on screen.
/// The orange accent marks only the selection, the active tool and the
/// primary action.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Palette {
    /// Behind everything (viewport surround, window background, gaps between panels).
    pub bg: Color32,
    /// Panels and bars.
    pub surface: Color32,
    /// Rows, cards and tabs on a panel.
    pub surface_raised: Color32,
    /// Hovered rows, pressed secondary buttons.
    pub surface_hover: Color32,
    /// Text fields, drag fields, tracks.
    pub well: Color32,
    /// The value part of a drag field (neutral, not the accent).
    pub field_fill: Color32,
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
        bg: rgb(22, 22, 24),
        surface: rgb(30, 31, 33),
        surface_raised: rgb(38, 39, 42),
        surface_hover: rgb(48, 49, 53),
        well: rgb(21, 22, 24),
        field_fill: rgb(56, 59, 66),
        overlay: rgb(36, 37, 40),
        glass: Color32::from_rgba_premultiplied(16, 16, 18, 214),
        border: rgb(46, 47, 50),
        border_strong: rgb(60, 62, 67),
        text: rgb(228, 229, 232),
        text_secondary: rgb(168, 171, 177),
        text_muted: rgb(128, 132, 140),
        text_disabled: rgb(84, 87, 93),
        accent: rgb(240, 138, 60),
        accent_hover: rgb(255, 160, 88),
        accent_pressed: rgb(214, 116, 42),
        accent_subtle: rgb(58, 42, 30),
        on_accent: rgb(26, 16, 6),
        success: rgb(76, 195, 138),
        warn: rgb(242, 179, 61),
        danger: rgb(240, 96, 90),
        info: rgb(96, 170, 240),
        focus: rgb(125, 183, 255),
        selection: rgb(84, 58, 36),
        scrim: Color32::from_rgba_premultiplied(0, 0, 0, 140),
        shadow: Color32::from_rgba_premultiplied(0, 0, 0, 90),
    };

    pub const LIGHT: Palette = Palette {
        bg: rgb(214, 216, 220),
        surface: rgb(236, 237, 240),
        surface_raised: rgb(247, 248, 250),
        surface_hover: rgb(224, 226, 230),
        well: rgb(250, 250, 251),
        field_fill: rgb(204, 210, 220),
        overlay: rgb(250, 250, 251),
        glass: Color32::from_rgba_premultiplied(236, 238, 241, 214),
        border: rgb(208, 211, 216),
        border_strong: rgb(176, 181, 189),
        text: rgb(22, 24, 28),
        text_secondary: rgb(62, 67, 75),
        text_muted: rgb(96, 103, 113),
        text_disabled: rgb(160, 166, 175),
        accent: rgb(210, 98, 22),
        accent_hover: rgb(230, 114, 34),
        accent_pressed: rgb(184, 84, 16),
        accent_subtle: rgb(250, 224, 202),
        on_accent: rgb(255, 255, 255),
        success: rgb(26, 140, 86),
        warn: rgb(176, 112, 0),
        danger: rgb(200, 52, 46),
        info: rgb(28, 112, 200),
        focus: rgb(36, 112, 220),
        selection: rgb(248, 214, 186),
        scrim: Color32::from_rgba_premultiplied(10, 12, 16, 90),
        shadow: Color32::from_rgba_premultiplied(0, 0, 0, 36),
    };
}

// ------------------------------------------------------------------ scales

/// Spacing scale (points). Layouts use these steps only; compact layouts
/// live on 4 / 6 / 8.
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

/// Corner radii: flat, 2–4 pt. `PILL` is only for switches and dots.
pub mod radius {
    pub const SM: u8 = 2;
    pub const MD: u8 = 3;
    pub const LG: u8 = 4;
    pub const XL: u8 = 4;
    pub const PILL: u8 = 255;
}

/// Elevation: 0 = flat, 1 = a hairline lift, 2 = menus / popovers / toasts,
/// 3 = dialogs. Shadows are short and soft: hierarchy comes from hairlines
/// and fills.
pub fn elevation(level: u8, p: &Palette) -> Shadow {
    match level {
        0 => Shadow::NONE,
        1 => Shadow { offset: [0, 1], blur: 2, spread: 0, color: p.shadow.gamma_multiply(0.5) },
        2 => Shadow { offset: [0, 2], blur: 8, spread: 0, color: p.shadow },
        _ => Shadow { offset: [0, 6], blur: 20, spread: 0, color: p.shadow },
    }
}

/// Type scale (points) on Inter, values in JetBrains Mono.
pub mod font {
    pub const CAPTION: f32 = 11.0;
    pub const SMALL: f32 = 12.0;
    pub const BODY: f32 = 12.5;
    pub const TITLE: f32 = 13.5;
    pub const HEADING: f32 = 15.0;
    pub const DISPLAY: f32 = 24.0;
    pub const MONO: f32 = 11.5;
    /// Extra letter spacing for upper-case captions.
    pub const CAPTION_TRACKING: f32 = 0.6;
}

/// Icon sizes (points) and the stroke width at the 18 pt design grid.
pub mod icon {
    pub const SM: f32 = 13.0;
    pub const MD: f32 = 16.0;
    pub const LG: f32 = 22.0;
    pub const XL: f32 = 32.0;
    pub const STROKE: f32 = 1.6;
}

/// Control sizes at the compact density (`metrics` gives the live values).
pub mod size {
    /// Buttons, text fields, property rows.
    pub const CONTROL_H: f32 = 22.0;
    pub const CONTROL_H_SM: f32 = 18.0;
    /// Drag fields (inline numeric sliders).
    pub const FIELD_H: f32 = 20.0;
    /// Icon-only buttons.
    pub const ICON_BTN: f32 = 22.0;
    /// Tool rail buttons.
    pub const TOOL: f32 = 32.0;
    pub const ROW_H: f32 = 28.0;
    pub const THUMB: f32 = 20.0;
    pub const TILE: f32 = 80.0;
    pub const TAB_H: f32 = 24.0;
    pub const STATUS_H: f32 = 22.0;
    pub const SPLITTER: f32 = 3.0;
    pub const SLIDER_W: f32 = 120.0;
    /// Label column of property rows.
    pub const LABEL_W: f32 = 84.0;
    pub const SIDEBAR: f32 = 280.0;
    pub const DIALOG_W: f32 = 500.0;
}

/// Motion: durations (seconds) and easing.
pub mod motion {
    pub const FAST: f32 = 0.08;
    pub const NORMAL: f32 = 0.12;
    pub const SLOW: f32 = 0.24;
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

// ------------------------------------------------------------------ density

/// How dense the interface is: Compact (Blender-like rows, the default) or
/// Comfortable (the roomier spacing of earlier versions).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default, serde::Serialize, serde::Deserialize)]
pub enum Density {
    #[default]
    Compact,
    Comfortable,
}

/// Live component sizes for a density.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Metrics {
    pub density: Density,
    pub control_h: f32,
    pub control_h_sm: f32,
    pub field_h: f32,
    pub icon_btn: f32,
    pub tool: f32,
    /// Tool rail buttons show a label under the icon.
    pub tool_labels: bool,
    pub row_h: f32,
    pub thumb: f32,
    pub tab_h: f32,
    pub status_h: f32,
    pub label_w: f32,
    /// Panel content padding.
    pub pad: f32,
    /// Gap between items in a row (x) and between rows (y).
    pub gap: egui::Vec2,
}

impl Metrics {
    pub fn of(d: Density) -> Metrics {
        match d {
            Density::Compact => Metrics {
                density: d,
                control_h: size::CONTROL_H,
                control_h_sm: size::CONTROL_H_SM,
                field_h: size::FIELD_H,
                icon_btn: size::ICON_BTN,
                tool: size::TOOL,
                tool_labels: false,
                row_h: size::ROW_H,
                thumb: size::THUMB,
                tab_h: size::TAB_H,
                status_h: size::STATUS_H,
                label_w: size::LABEL_W,
                pad: space::MD,
                gap: egui::vec2(space::SM, space::XS),
            },
            Density::Comfortable => Metrics {
                density: d,
                control_h: 28.0,
                control_h_sm: 22.0,
                field_h: 24.0,
                icon_btn: 28.0,
                tool: 36.0,
                tool_labels: true,
                row_h: 44.0,
                thumb: 32.0,
                tab_h: 30.0,
                status_h: 28.0,
                label_w: 96.0,
                pad: space::LG,
                gap: egui::vec2(space::MD, space::SM),
            },
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
    pub m: Metrics,
}

impl Theme {
    pub fn new(kind: ThemeKind) -> Theme {
        Theme::with(kind, Density::Compact)
    }
    pub fn with(kind: ThemeKind, density: Density) -> Theme {
        Theme { kind, p: if kind == ThemeKind::Dark { Palette::DARK } else { Palette::LIGHT }, m: Metrics::of(density) }
    }
}

fn theme_id() -> egui::Id {
    egui::Id::NULL.with("pigment.design.theme")
}

/// The theme in effect (dark and compact until `apply` says otherwise).
pub fn theme(ctx: &egui::Context) -> Theme {
    ctx.data(|d| d.get_temp::<Theme>(theme_id())).unwrap_or(Theme::new(ThemeKind::Dark))
}

/// Shorthand: the palette in effect for this `Ui`.
pub fn pal(ui: &egui::Ui) -> Palette {
    theme(ui.ctx()).p
}

/// Shorthand: the component sizes in effect for this `Ui`.
pub fn metrics(ui: &egui::Ui) -> Metrics {
    theme(ui.ctx()).m
}

/// Fonts, theme, density and UI scale from the user's preferences.
pub fn install(ctx: &egui::Context, prefs: &crate::app::prefs::Prefs) {
    fonts::install(ctx);
    apply_with(ctx, prefs.theme, prefs.density);
    load_sections(ctx, &prefs.sections);
    ctx.set_zoom_factor(prefs.ui_scale.clamp(0.75, 2.0));
}

/// Switch the theme, keeping the density.
pub fn apply(ctx: &egui::Context, kind: ThemeKind) {
    apply_with(ctx, kind, theme(ctx).m.density);
}

/// Switch the density, keeping the theme.
pub fn set_density(ctx: &egui::Context, d: Density) {
    apply_with(ctx, theme(ctx).kind, d);
}

/// Switch theme and density: egui's visuals and spacing derive from them.
pub fn apply_with(ctx: &egui::Context, kind: ThemeKind, density: Density) {
    let t = Theme::with(kind, density);
    ctx.data_mut(|d| d.insert_temp(theme_id(), t));
    let (p, m) = (t.p, t.m);
    let compact = density == Density::Compact;
    let mut v = if kind == ThemeKind::Dark { egui::Visuals::dark() } else { egui::Visuals::light() };
    v.panel_fill = p.surface;
    v.window_fill = p.overlay;
    v.window_stroke = Stroke::new(1.0, p.border_strong);
    v.window_shadow = elevation(3, &p);
    v.popup_shadow = elevation(2, &p);
    v.window_corner_radius = CornerRadius::same(radius::LG);
    v.menu_corner_radius = CornerRadius::same(radius::LG);
    v.extreme_bg_color = p.well;
    v.faint_bg_color = p.surface_raised;
    v.code_bg_color = p.well;
    v.override_text_color = None;
    v.hyperlink_color = p.accent;
    v.warn_fg_color = p.warn;
    v.error_fg_color = p.danger;
    v.selection.bg_fill = p.selection;
    v.selection.stroke = Stroke::new(1.0, p.accent);
    v.text_cursor.stroke = Stroke::new(1.5, p.accent);
    v.slider_trailing_fill = false;
    v.handle_shape = egui::style::HandleShape::Rect { aspect_ratio: 0.5 };
    v.collapsing_header_frame = false;
    v.indent_has_left_vline = true;
    let w = &mut v.widgets;
    for (state, bg, fg, stroke) in [
        (&mut w.noninteractive, p.surface, p.text_secondary, p.border),
        (&mut w.inactive, p.surface_raised, p.text, p.border),
        (&mut w.hovered, p.surface_hover, p.text, p.border_strong),
        (&mut w.active, p.surface_hover, p.text, p.border_strong),
        (&mut w.open, p.surface_hover, p.text, p.border_strong),
    ] {
        state.bg_fill = bg;
        state.weak_bg_fill = bg;
        state.fg_stroke = Stroke::new(1.0, fg);
        state.bg_stroke = Stroke::new(1.0, stroke);
        state.corner_radius = CornerRadius::same(radius::MD);
        state.expansion = 0.0;
    }
    // text fields and combo boxes sit in a dark well with a hairline
    w.inactive.bg_fill = p.well;
    w.inactive.bg_stroke = Stroke::new(1.0, p.border);
    w.inactive.weak_bg_fill = p.surface_raised;
    ctx.set_visuals_of(egui::Theme::Dark, v.clone());
    ctx.set_visuals_of(egui::Theme::Light, v);
    ctx.set_theme(if kind == ThemeKind::Dark { egui::Theme::Dark } else { egui::Theme::Light });
    ctx.all_styles_mut(|s| {
        s.spacing.item_spacing = m.gap;
        s.spacing.button_padding = egui::vec2(if compact { space::SM } else { space::MD + 2.0 }, space::XXS);
        s.spacing.slider_width = size::SLIDER_W;
        s.spacing.slider_rail_height = space::XS;
        s.spacing.interact_size = egui::vec2(32.0, m.field_h);
        s.spacing.icon_width = if compact { 12.0 } else { 14.0 };
        s.spacing.icon_width_inner = if compact { 6.0 } else { 8.0 };
        s.spacing.icon_spacing = space::XS;
        s.spacing.menu_margin = Margin::same(space::XS as i8);
        s.spacing.window_margin = Margin::same(m.pad as i8);
        s.spacing.indent = space::LG;
        s.spacing.combo_width = 120.0;
        s.spacing.text_edit_width = 160.0;
        s.spacing.scroll = egui::style::ScrollStyle { bar_width: 6.0, floating: true, handle_min_length: 16.0, ..egui::style::ScrollStyle::floating() };
        s.interaction.tooltip_delay = 0.35;
        s.animation_time = motion::NORMAL;
        s.text_styles = fonts::text_styles();
    });
}

/// Panel frames.
pub fn panel_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.surface).inner_margin(Margin::same(space::MD as i8))
}

/// The top bar and the status bar: flat surface, tight padding.
pub fn bar_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.surface).inner_margin(Margin::symmetric(space::MD as i8, space::XS as i8)).stroke(Stroke::new(1.0, p.border))
}

/// The tool options bar under the top bar.
pub fn toolbar_frame(p: &Palette) -> egui::Frame {
    egui::Frame::new().fill(p.surface).inner_margin(Margin::symmetric(space::MD as i8, space::XXS as i8))
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
            for bg in [p.surface, p.surface_raised, p.surface_hover, p.overlay, p.bg, p.well] {
                assert!(contrast(p.text, bg) >= 7.0, "primary text {:?} on {:?}", p.text, bg);
                assert!(contrast(p.text_secondary, bg) >= 4.5, "secondary on {:?}: {}", bg, contrast(p.text_secondary, bg));
                assert!(contrast(p.text_muted, bg) >= 3.0, "muted on {:?}: {}", bg, contrast(p.text_muted, bg));
            }
            // values are drawn over the drag field's fill
            assert!(contrast(p.text, p.field_fill) >= 4.5, "value text on field fill: {}", contrast(p.text, p.field_fill));
            assert!(contrast(p.text_secondary, p.field_fill) >= 3.0, "label on field fill: {}", contrast(p.text_secondary, p.field_fill));
            // selected rows
            assert!(contrast(p.text, p.accent_subtle) >= 7.0, "text on selected row");
            assert!(contrast(p.accent, p.accent_subtle) >= 3.0, "accent icon on selected row: {}", contrast(p.accent, p.accent_subtle));
            assert!(contrast(p.on_accent, p.accent) >= 3.0, "on-accent {}", contrast(p.on_accent, p.accent));
        }
    }

    /// The dark chrome stays low-chroma and darker than the model: no surface
    /// is saturated, and the panel greys sit in the Blender-dark range.
    #[test]
    fn dark_chrome_is_neutral_and_dark() {
        let p = Palette::DARK;
        let chroma = |c: Color32| c.r().max(c.g()).max(c.b()) - c.r().min(c.g()).min(c.b());
        for c in [p.bg, p.surface, p.surface_raised, p.surface_hover, p.well, p.overlay, p.border, p.border_strong, p.field_fill] {
            assert!(chroma(c) <= 10, "{c:?} is too colourful for chrome");
        }
        for (c, max) in [(p.bg, 26), (p.surface, 36), (p.surface_raised, 44), (p.border, 52)] {
            assert!(c.r().max(c.g()).max(c.b()) <= max, "{c:?} brighter than {max}");
        }
        assert!(p.bg.r() < p.surface.r() && p.surface.r() < p.surface_raised.r() && p.surface_raised.r() < p.surface_hover.r(), "surfaces step up");
    }

    /// Compact is denser than Comfortable everywhere it matters.
    #[test]
    fn compact_density_is_denser() {
        let (c, f) = (Metrics::of(Density::Compact), Metrics::of(Density::Comfortable));
        assert!(c.row_h < f.row_h && c.control_h < f.control_h && c.tab_h < f.tab_h && c.pad < f.pad && c.field_h < f.field_h);
        assert!((20.0..=22.0).contains(&c.field_h) && c.control_h <= 22.0, "Blender-density rows");
        assert!(radius::LG <= 4 && radius::XL <= 4, "flat corners");
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
            // raw egui sliders: use `DragField` / `slider_row` (inline value, Ctrl snaps)
            "egui::Slider::new",
            // raw collapsing headers: use `collapsible` (remembered state, house style)
            "egui::CollapsingHeader::new",
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
