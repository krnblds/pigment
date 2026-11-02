//! The Pigment mark: the app icon drawn inside the UI.
//!
//! The rasters come from `assets/branding` (see `tools/branding/make_icons.py`)
//! and are embedded, so the logo shows whatever the working directory. Small
//! sizes use the hand-simplified 32 px artwork; anything bigger uses the master.

use eframe::egui;
use egui::{Color32, Rect, Sense, TextureHandle, TextureOptions, Vec2};

/// The window and taskbar icon (also used for the design gallery window).
pub const WINDOW_ICON_PNG: &[u8] = include_bytes!("../../../../../assets/branding/png/pigment-256.png");
const SMALL_PNG: &[u8] = include_bytes!("../../../../../assets/branding/png/pigment-32.png");
const LARGE_PNG: &[u8] = include_bytes!("../../../../../assets/branding/png/pigment-128.png");

fn texture(ctx: &egui::Context, small: bool) -> Option<TextureHandle> {
    let id = egui::Id::NULL.with(("pigment_logo", small));
    if let Some(t) = ctx.data(|d| d.get_temp::<TextureHandle>(id)) {
        return Some(t);
    }
    let img = image::load_from_memory_with_format(if small { SMALL_PNG } else { LARGE_PNG }, image::ImageFormat::Png).ok()?.to_rgba8();
    let ci = egui::ColorImage::from_rgba_unmultiplied([img.width() as usize, img.height() as usize], img.as_raw());
    let opts = TextureOptions { mipmap_mode: Some(egui::TextureFilter::Linear), ..TextureOptions::LINEAR };
    let t = ctx.load_texture("pigment_logo", ci, opts);
    ctx.data_mut(|d| d.insert_temp(id, t.clone()));
    Some(t)
}

/// Paint the mark into `rect` (square; the artwork is centred in it).
pub fn paint_logo(ui: &egui::Ui, rect: Rect) {
    let px = rect.width().min(rect.height()) * ui.ctx().pixels_per_point();
    if let Some(t) = texture(ui.ctx(), px <= 40.0) {
        let uv = Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
        ui.painter().image(t.id(), rect, uv, Color32::WHITE);
    }
}

/// Allocate a `size` x `size` square and paint the mark in it.
pub fn logo(ui: &mut egui::Ui, size: f32) -> egui::Response {
    let (rect, resp) = ui.allocate_exact_size(Vec2::splat(size), Sense::hover());
    paint_logo(ui, rect);
    resp
}
