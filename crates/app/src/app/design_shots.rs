//! Screenshot walk-through of every screen, for design reviews and the
//! before / after images in `docs/agents/design/`. Ignored: run by hand.
//!
//! `PIGMENT_SHOTS=<dir> cargo test -p pigment --release design_shots -- --ignored`
//! (default directory: `<temp>/pigment-design-shots`).

use super::dock::{DockLayout, Node, PanelId};
use super::harness::Harness;
use super::prefs::Mode;
use super::ui::{LibItem, Tool};
use super::*;

fn out_dir() -> PathBuf {
    std::env::var("PIGMENT_SHOTS").map(PathBuf::from).unwrap_or_else(|_| std::env::temp_dir().join("pigment-design-shots"))
}

fn settle(h: &mut Harness) {
    h.run(4);
    h.app.wait_jobs(&h.rs.clone());
    h.run(2);
}

fn thumbs_done(h: &mut Harness) {
    for _ in 0..200 {
        h.step();
        if h.app.ui.thumbs.as_ref().is_some_and(|t| t.pending() == 0) {
            break;
        }
    }
    h.run(2);
}

fn shot(h: &mut Harness, name: &str) -> image::RgbaImage {
    h.run(20);
    h.save_png(&out_dir().join(format!("{name}.png")))
}

/// Save the part of the last frame inside `r` (points), with a margin.
fn crop(h: &Harness, img: &image::RgbaImage, r: egui::Rect, name: &str) {
    let s = h.ppp;
    let r = r.expand(4.0);
    let x = (r.left().max(0.0) * s) as u32;
    let y = (r.top().max(0.0) * s) as u32;
    let w = ((r.width() * s) as u32).min(img.width() - x);
    let hh = ((r.height() * s) as u32).min(img.height() - y);
    let sub = image::imageops::crop_imm(img, x, y, w, hh).to_image();
    sub.save(out_dir().join(format!("{name}.png"))).unwrap();
}

fn side(p: PanelId) -> DockLayout {
    DockLayout { root: Node::Split { vertical: false, ratio: 0.66, a: Box::new(Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(Node::Leaf { tabs: vec![p], active: 0 }) }, floating: vec![] }
}

fn panel_rect(h: &Harness, p: PanelId) -> Option<egui::Rect> {
    // the content rect is the biggest one registered for the panel (tabs are small)
    h.app.ui.dock_rects.iter().filter(|(id, _)| *id == p).map(|(_, r)| *r).max_by(|a, b| a.area().total_cmp(&b.area()))
}

#[test]
#[ignore]
fn design_shots() {
    let Some(mut h) = Harness::new([1440.0, 900.0], 1.0) else { return };
    std::fs::create_dir_all(out_dir()).unwrap();
    let rs = h.rs.clone();
    // welcome
    h.app.ui.welcome = true;
    settle(&mut h);
    shot(&mut h, "welcome");
    // simple mode on the crate sample with a smart material
    h.app.ui.welcome = false;
    h.app.open_sample(&rs, &super::welcome::SAMPLES[0]);
    settle(&mut h);
    thumbs_done(&mut h);
    h.app.apply_library(&rs, &LibItem::Smart("Rusty steel".into()), None);
    h.app.set_wear(0.6);
    settle(&mut h);
    thumbs_done(&mut h);
    let v = h.app.anchors.get("viewport").copied().unwrap_or(egui::Rect::from_min_size(egui::pos2(300.0, 300.0), egui::vec2(10.0, 10.0)));
    h.hover(v.center() + egui::vec2(-80.0, 20.0));
    shot(&mut h, "simple");
    // advanced mode, Texturing layout, a generated mask selected
    h.app.set_mode(Mode::Advanced);
    *h.app.ui.prefs.layout_mut() = DockLayout::texturing();
    let i = h.app.doc.layers.iter().position(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())).unwrap();
    let id = h.app.doc.layers[i].id;
    h.app.select(Some(id), false);
    thumbs_done(&mut h);
    h.hover(v.center() + egui::vec2(-80.0, 20.0));
    let img = shot(&mut h, "advanced");
    if let Some(r) = panel_rect(&h, PanelId::Layers) {
        crop(&h, &img, r.union(r.translate(egui::vec2(0.0, -24.0))), "layers");
    }
    // every panel next to the viewport
    for p in PanelId::ALL.into_iter().filter(|p| *p != PanelId::Viewport) {
        if matches!(p, PanelId::Mask | PanelId::Properties | PanelId::Channels) {
            h.app.select(Some(id), p == PanelId::Mask);
        }
        *h.app.ui.prefs.layout_mut() = side(p);
        h.run(4);
        let img = shot(&mut h, &format!("panel_{p:?}"));
        if let Some(r) = panel_rect(&h, p) {
            crop(&h, &img, r.union(r.translate(egui::vec2(0.0, -24.0))), &format!("crop_{p:?}"));
        }
    }
    *h.app.ui.prefs.layout_mut() = DockLayout::texturing();
    h.app.select(Some(id), false);
    // decal tool
    h.app.set_tool(Tool::Decal);
    settle(&mut h);
    shot(&mut h, "tool_decal");
    h.app.set_tool(Tool::Paint);
    // right-click on a layer row
    h.run(3);
    if let Some(r) = h.app.ui.dock_rects.iter().filter(|(p, r)| *p == PanelId::Layers && r.height() < 60.0).map(|(_, r)| *r).nth(1) {
        h.right_click(r.center());
        shot(&mut h, "layer_context_menu");
        h.key(egui::Key::Escape, egui::Modifiers::NONE);
    }
    // dialogs and overlays
    h.app.show_export = true;
    shot(&mut h, "export_dialog");
    h.app.show_export = false;
    h.run(3);
    h.app.ui.settings = true;
    shot(&mut h, "settings");
    h.app.ui.settings = false;
    h.run(3);
    h.app.ui.new_project.open = true;
    shot(&mut h, "new_project");
    h.app.ui.new_project.open = false;
    h.run(3);
    h.key(egui::Key::K, egui::Modifiers::COMMAND);
    shot(&mut h, "palette_empty");
    h.type_text("rus");
    shot(&mut h, "palette");
    h.key(egui::Key::Escape, egui::Modifiers::NONE);
    h.app.ui.cheatsheet = true;
    shot(&mut h, "shortcuts");
    h.app.ui.cheatsheet = false;
    h.run(3);
    h.app.ui.toasts.push(super::design::ToastKind::Success, "Exported 5 maps", "Saved to Documents/Pigment Exports/Crate");
    h.app.ui.toasts.push(super::design::ToastKind::Error, "Couldn't open model", "car.fbx: only OBJ and glTF/GLB are supported.");
    shot(&mut h, "toasts");
    // light theme
    h.app.ui.prefs.theme = super::design::ThemeKind::Light;
    super::design::apply(&h.ctx, super::design::ThemeKind::Light);
    shot(&mut h, "advanced_light");
}
