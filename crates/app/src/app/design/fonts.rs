//! Embedded fonts (SIL Open Font License 1.1, see `crates/app/assets/fonts`):
//! Inter for the interface, JetBrains Mono for values. egui's default fonts
//! stay behind them as fallbacks for symbols Inter's Latin subset lacks.

use eframe::egui;
use egui::{FontData, FontFamily, FontId, TextStyle};
use std::collections::BTreeMap;
use std::sync::Arc;

pub const SEMIBOLD: &str = "Inter SemiBold";
pub const BOLD: &str = "Inter Bold";

pub fn install(ctx: &egui::Context) {
    let mut defs = egui::FontDefinitions::default();
    let add = |defs: &mut egui::FontDefinitions, name: &str, bytes: &'static [u8]| {
        defs.font_data.insert(name.to_string(), Arc::new(FontData::from_static(bytes)));
    };
    add(&mut defs, "Inter", include_bytes!("../../../assets/fonts/Inter-Regular.ttf"));
    add(&mut defs, SEMIBOLD, include_bytes!("../../../assets/fonts/Inter-SemiBold.ttf"));
    add(&mut defs, BOLD, include_bytes!("../../../assets/fonts/Inter-Bold.ttf"));
    add(&mut defs, "JetBrains Mono", include_bytes!("../../../assets/fonts/JetBrainsMono-Regular.ttf"));
    let fallback_prop = defs.families.get(&FontFamily::Proportional).cloned().unwrap_or_default();
    let fallback_mono = defs.families.get(&FontFamily::Monospace).cloned().unwrap_or_default();
    let with = |first: &str, rest: &[String]| std::iter::once(first.to_string()).chain(rest.iter().cloned()).collect::<Vec<_>>();
    defs.families.insert(FontFamily::Proportional, with("Inter", &fallback_prop));
    defs.families.insert(FontFamily::Monospace, with("JetBrains Mono", &fallback_mono));
    defs.families.insert(FontFamily::Name(SEMIBOLD.into()), with(SEMIBOLD, &fallback_prop));
    defs.families.insert(FontFamily::Name(BOLD.into()), with(BOLD, &fallback_prop));
    ctx.set_fonts(defs);
}

pub fn semibold(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name(SEMIBOLD.into()))
}

pub fn bold(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name(BOLD.into()))
}

pub fn regular(size: f32) -> FontId {
    FontId::proportional(size)
}

pub fn mono(size: f32) -> FontId {
    FontId::monospace(size)
}

pub fn text_styles() -> BTreeMap<TextStyle, FontId> {
    use super::font::*;
    [
        (TextStyle::Small, regular(SMALL)),
        (TextStyle::Body, regular(BODY)),
        (TextStyle::Button, regular(BODY)),
        (TextStyle::Heading, semibold(HEADING)),
        (TextStyle::Monospace, mono(MONO)),
    ]
    .into()
}
