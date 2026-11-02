//! Headless UI tests: the real frame function driven by scripted input
//! through `harness::Harness` (no window, no OS input), plus the docs
//! screenshots (`cargo test -p pigment --release ui_screenshots -- --ignored`).

use super::design::DropZone;
use super::dock::{DockLayout, PanelId};
use super::harness::Harness;
use super::prefs::Mode;
use super::ui::{LibItem, Tool};
use super::*;

fn harness() -> Option<Harness> {
    let h = Harness::new([1440.0, 900.0], 1.0);
    if h.is_none() {
        eprintln!("no GPU adapter: skipping");
    }
    h
}

fn settle(h: &mut Harness) {
    h.run(4);
    h.app.wait_jobs(&h.rs.clone());
    h.run(2);
}

/// Wait for every queued thumbnail (they render a couple per frame).
fn thumbs_done(h: &mut Harness) {
    for _ in 0..200 {
        h.step();
        if h.app.ui.thumbs.as_ref().is_some_and(|t| t.pending() == 0) {
            break;
        }
    }
    h.run(2);
}

fn anchor(h: &Harness, name: &str) -> egui::Rect {
    *h.app.anchors.get(name).unwrap_or_else(|| panic!("no anchor `{name}`; have {:?}", h.app.anchors.keys().collect::<Vec<_>>()))
}

/// The beginner path: welcome → sample → smart material → weathering → export.
#[test]
fn welcome_sample_material_export() {
    let Some(mut h) = harness() else { return };
    h.app.ui.welcome = true;
    settle(&mut h);
    assert!(h.app.ui.welcome);
    // 1: the crate sample
    h.click(anchor(&h, "sample_crate").center());
    settle(&mut h);
    assert!(!h.app.ui.welcome, "sample click closes the welcome screen");
    assert_eq!(h.app.ui.prefs.mode, Mode::Simple);
    assert!(h.app.ui.prefs.layout().contains(PanelId::Library), "simple layout shows the library");
    // 2: click "Rusty" in the library
    h.run(2);
    let lib = h.app.ui.dock_rects.iter().find(|(p, _)| *p == PanelId::Library).map(|(_, r)| *r).expect("library visible");
    assert!(lib.width() > 100.0);
    h.app.apply_library(&h.rs.clone(), &LibItem::Smart("Rusty steel".into()), None);
    settle(&mut h);
    let top_level: Vec<String> = h.app.doc.layers.iter().filter(|l| l.parent.is_none()).map(|l| l.name.clone()).collect();
    assert!(top_level.iter().any(|n| n == "Rusty"), "{top_level:?}");
    assert!(!top_level.iter().any(|n| n == "Teal paint" || n == "Edge wear"), "simple mode replaces the old material: {top_level:?}");
    assert!(h.history_can_undo());
    // 3: more wear: generator amounts follow the slider
    let before: Vec<f32> = gen_amounts(&h);
    h.app.set_wear(0.9);
    let after: Vec<f32> = gen_amounts(&h);
    assert!(after.iter().zip(&before).all(|(a, b)| a >= b) && after != before, "{before:?} -> {after:?}");
    // 4: export for Blender, without blocking the window
    let out = std::env::temp_dir().join(format!("pigment-ui-export-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&out);
    h.app.ui.prefs.export_dir = Some(out.clone());
    h.app.export_name = "Crate".into();
    h.key(egui::Key::E, egui::Modifiers::COMMAND);
    h.run(20);
    assert!(h.app.show_export, "Ctrl+E opens export");
    h.click(anchor(&h, "export_go").center());
    assert!(!h.app.ui.jobs.is_empty() || out.join("Crate").exists(), "export started");
    settle(&mut h);
    let dir = out.join("Crate");
    for f in ["Crate_BaseColor.png", "Crate_Roughness.png", "Crate.glb", "material.json"] {
        assert!(dir.join(f).exists(), "missing {f}: {:?} {:?}", std::fs::read_dir(&dir).map(|d| d.flatten().map(|e| e.file_name()).collect::<Vec<_>>()), h.app.status);
    }
    assert!(!h.app.show_export, "dialog closes after export");
    let _ = std::fs::remove_dir_all(&out);
}

fn gen_amounts(h: &Harness) -> Vec<f32> {
    h.app.doc.layers.iter().filter_map(|l| l.mask.as_ref()?.generator.as_ref()).filter(|g| super::panels::library::WEATHER.contains(&g.kind)).map(|g| g.amount).collect()
}

impl Harness {
    fn history_can_undo(&mut self) -> bool {
        self.app.commit_doc_changes();
        self.app.history.can_undo()
    }
}

/// A material can go on one part with the Fill tool, and it replaces the
/// previous fill of that part.
#[test]
fn fill_part_tool_targets_one_part() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    h.app.ui.lib_current = Some(LibItem::Preset("Gold".into()));
    h.app.set_tool(Tool::Fill);
    settle(&mut h);
    let v = anchor(&h, "viewport");
    h.click(v.center());
    settle(&mut h);
    let filled: Vec<&Layer> = h.app.doc.layers.iter().filter(|l| l.parent.is_none() && l.mask.as_ref().is_some_and(|m| m.parts.len() == 1)).collect();
    assert_eq!(filled.len(), 1, "one part folder: {:?}", h.app.doc.layers.iter().map(|l| &l.name).collect::<Vec<_>>());
    h.app.ui.lib_current = Some(LibItem::Preset("Copper".into()));
    h.click(v.center());
    settle(&mut h);
    let filled: Vec<String> = h.app.doc.layers.iter().filter(|l| l.parent.is_none() && l.mask.as_ref().is_some_and(|m| m.parts.len() == 1)).map(|l| l.name.clone()).collect();
    assert_eq!(filled, vec!["Copper".to_string()], "same part refilled");
}

/// Dragging a layer by its handle onto a folder puts it inside; onto the
/// top edge of a row moves it above.
#[test]
fn folder_drag_and_drop() {
    let Some(mut h) = harness() else { return };
    h.app.ui.prefs.mode = Mode::Advanced;
    *h.app.ui.prefs.layout_mut() = DockLayout::texturing();
    settle(&mut h);
    // a folder above the paint layer
    h.app.select(h.app.doc.layers.last().map(|l| l.id), false);
    h.app.add_folder();
    settle(&mut h);
    let folder = h.app.doc.layers.iter().find(|l| l.is_folder()).unwrap().id;
    let dirt = h.app.doc.layers.iter().find(|l| l.name == "Dirt").unwrap().id;
    let row = |h: &Harness, id: LayerId| {
        let name = h.app.doc.layer(id).unwrap().name.clone();
        // rows are pushed to dock_rects in panel order (top of the stack first)
        let visible: Vec<LayerId> = h.app.doc.layers.iter().rev().filter(|l| !h.app.doc.is_hidden_in_panel(l.id)).map(|l| l.id).collect();
        let k = visible.iter().position(|x| *x == id).unwrap();
        let rows: Vec<egui::Rect> = h.app.ui.dock_rects.iter().filter(|(p, r)| *p == PanelId::Layers && r.height() < 60.0).map(|(_, r)| *r).collect();
        assert!(rows.len() >= visible.len(), "{name}: {} rows for {} layers", rows.len(), visible.len());
        rows[k]
    };
    let from = row(&h, dirt);
    let to = row(&h, folder);
    let handle = egui::pos2(from.left() + 10.0, from.center().y);
    h.drag(handle, to.center(), 6);
    settle(&mut h);
    assert_eq!(h.app.doc.layer(dirt).unwrap().parent, Some(folder), "dropped into the folder: {:?}", h.app.status);
    // the pure move logic, above / below / into
    let mut d = h.app.doc.clone();
    let edge = d.layers.iter().find(|l| l.name == "Edge wear").unwrap().id;
    super::panels::layers::drop_layer(&mut d, edge, folder, DropZone::Above).unwrap();
    let ie = d.index_of(edge).unwrap();
    let iff = d.index_of(folder).unwrap();
    assert!(ie > iff && d.layer(edge).unwrap().parent.is_none(), "above the folder in the stack");
    super::panels::layers::drop_layer(&mut d, folder, dirt, DropZone::Into).unwrap_err();
    super::panels::layers::drop_layer(&mut d, edge, dirt, DropZone::Below).unwrap();
    assert_eq!(d.layer(edge).unwrap().parent, Some(folder), "below a child = into its folder");
}

/// Decal tool: stamp on the surface under the cursor, one undo step;
/// scatter places several in one step.
#[test]
fn decal_tool_stamp_and_scatter() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let img = super::panels::decals::asset_dir("decals").unwrap().join("hazard_triangle.png");
    h.app.ui.decal.image = Some(img.clone());
    h.app.ui.decal.size = 0.5;
    h.key(egui::Key::D, egui::Modifiers::NONE);
    settle(&mut h);
    assert_eq!(h.app.tool(), Tool::Decal);
    assert!(h.app.ui.prefs.layout().contains(PanelId::Decals), "D opens the decals panel");
    let paint = h.app.doc.layers.iter().rev().find(|l| l.is_paint()).unwrap().paint_res().unwrap();
    let before = io::read_layer(&h.rs.device, &h.rs.queue, &h.app.ts, paint).unwrap();
    let v = anchor(&h, "viewport");
    h.click(v.center());
    settle(&mut h);
    let after = io::read_layer(&h.rs.device, &h.rs.queue, &h.app.ts, paint).unwrap();
    assert_ne!(before.color, after.color, "stamp painted: {:?}", h.app.status);
    assert!(h.app.history.undo_label().is_some_and(|l| l.contains("hazard_triangle")), "{:?}", h.app.history.undo_label());
    // scatter: one undo step
    h.app.ui.decal.mode = super::ui::DecalMode::Scatter;
    h.app.ui.decal.count = 5;
    h.app.ui.decal.size_range = (0.1, 0.2);
    h.app.ui.decal.walls_only = false;
    h.app.scatter_decals_ui(&h.rs.clone(), &[img]);
    assert!(h.app.history.undo_label().is_some_and(|l| l.starts_with("Scatter")), "{:?} {:?}", h.app.history.undo_label(), h.app.status);
    h.key(egui::Key::Z, egui::Modifiers::COMMAND);
    assert!(h.app.history.undo_label().is_some_and(|l| l.contains("hazard_triangle")), "one undo removes the whole scatter");
    h.key(egui::Key::Escape, egui::Modifiers::NONE);
    assert_eq!(h.app.tool(), Tool::Paint);
}

/// Simple / Advanced: each mode keeps its own layout; Ctrl+Tab switches.
#[test]
fn simple_advanced_toggle() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    assert_eq!(h.app.ui.prefs.mode, Mode::Simple);
    assert!(!h.app.ui.prefs.layout().contains(PanelId::Layers), "simple hides the layer stack");
    h.click(anchor(&h, "mode_toggle").right_center() - egui::vec2(30.0, 0.0));
    h.run(2);
    assert_eq!(h.app.ui.prefs.mode, Mode::Advanced);
    assert!(h.app.ui.prefs.layout().contains(PanelId::Layers));
    assert!(h.app.ui.dock_rects.iter().any(|(p, _)| *p == PanelId::Layers));
    // customise the advanced layout; it survives a round trip through Simple
    h.app.ui.prefs.layout_mut().remove(PanelId::Variants);
    h.key(egui::Key::Tab, egui::Modifiers::COMMAND);
    assert_eq!(h.app.ui.prefs.mode, Mode::Simple);
    h.key(egui::Key::Tab, egui::Modifiers::COMMAND);
    assert_eq!(h.app.ui.prefs.mode, Mode::Advanced);
    assert!(!h.app.ui.prefs.layout().contains(PanelId::Variants), "custom layout kept");
    // Pick parts is an Advanced tool
    h.key(egui::Key::P, egui::Modifiers::NONE);
    assert_eq!(h.app.tool(), Tool::Pick);
}

/// Every panel renders on its own (as a floating window) without panicking.
#[test]
fn every_panel_renders_in_isolation() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let registered = h.app.ui.panels.as_ref().unwrap().ids();
    assert_eq!(registered, PanelId::ALL.to_vec(), "every panel id has a widget");
    for p in PanelId::ALL {
        let mut l = DockLayout { root: super::dock::Node::Leaf { tabs: vec![p], active: 0 }, floating: vec![] };
        l.repair();
        *h.app.ui.prefs.layout_mut() = l;
        h.run(3);
        let drawn = h.app.ui.dock_rects.iter().any(|(id, r)| *id == p && r.width() > 50.0 && r.height() > 50.0);
        assert!(drawn, "{p:?} not drawn: {:?}", h.app.ui.dock_rects);
    }
    // and with a selection that has a mask + generator (Mask, Properties, Channels)
    let i = h.app.edge_wear_layer().unwrap();
    let id = h.app.doc.layers[i].id;
    h.app.select(Some(id), true);
    for p in [PanelId::Mask, PanelId::Properties, PanelId::Channels, PanelId::Variants, PanelId::Parts] {
        *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.6, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![p], active: 0 }) }, floating: vec![] };
        h.run(3);
    }
}

/// Command palette: Ctrl+K, type, Enter runs the best match.
#[test]
fn command_palette_runs_commands() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    h.key(egui::Key::K, egui::Modifiers::COMMAND);
    assert!(h.app.ui.palette.open);
    h.type_text("advanced mode");
    h.key(egui::Key::Enter, egui::Modifiers::NONE);
    assert!(!h.app.ui.palette.open);
    assert_eq!(h.app.ui.prefs.mode, Mode::Advanced);
    // ? opens the shortcut sheet
    h.key(egui::Key::Questionmark, egui::Modifiers::SHIFT);
    assert!(h.app.ui.cheatsheet);
}

/// Undo history panel: clicking an earlier step undoes back to it.
#[test]
fn history_panel_jumps() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    for k in 0..3 {
        let l = h.app.doc.new_fill_layer(&format!("F{k}"));
        h.app.insert_layer(l);
        h.app.commit_doc_changes();
    }
    let n = h.app.doc.layers.len();
    h.app.history_jump(&h.rs.clone(), 1);
    assert_eq!(h.app.doc.layers.len(), n - 2);
    h.app.history_jump(&h.rs.clone(), 3);
    assert_eq!(h.app.doc.layers.len(), n);
}

/// Autosave writes a recovery copy that the welcome screen can restore.
#[test]
fn autosave_and_recover() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let l = h.app.doc.new_fill_layer("Only in autosave");
    h.app.insert_layer(l);
    h.app.commit_doc_changes();
    let rs = h.rs.clone();
    h.app.autosave(&rs);
    h.app.wait_jobs(&rs);
    assert!(h.app.recovery().is_some(), "recovery copy written");
    h.app.run_pending(&rs, Pending::NewTorus);
    assert!(!h.app.doc.layers.iter().any(|l| l.name == "Only in autosave"));
    h.app.recover(&rs);
    assert!(h.app.doc.layers.iter().any(|l| l.name == "Only in autosave"), "{:?}", h.app.status);
    assert!(h.app.modified);
}

/// Thumbnails render asynchronously (a few per frame) and are cached on disk.
#[test]
fn library_thumbnails_render_and_cache() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    thumbs_done(&mut h);
    let t = h.app.ui.thumbs.as_ref().expect("library panel created the thumbnail renderer");
    assert!(t.rendered > 10, "rendered {}", t.rendered);
    let dir = h.app.ui.prefs.thumb_dir().unwrap();
    let n = std::fs::read_dir(&dir).map(|d| d.count()).unwrap_or(0);
    assert!(n >= t.rendered, "{n} cached files");
}

// ------------------------------------------------------------------ screenshots

fn docs() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../docs")
}

/// Screenshots for docs/agents/ui and docs/design. Ignored: run by hand.
#[test]
#[ignore]
fn ui_screenshots() {
    let Some(mut h) = harness() else { return };
    let out = docs().join("agents/ui");
    let shot = |h: &mut Harness, name: &str| {
        h.run(30);
        h.save_png(&out.join(format!("{name}.png")));
    };
    // welcome
    h.app.ui.welcome = true;
    settle(&mut h);
    shot(&mut h, "welcome");
    // simple mode on a sample with a smart material
    h.click(anchor(&h, "sample_crate").center());
    settle(&mut h);
    thumbs_done(&mut h);
    h.app.apply_library(&h.rs.clone(), &LibItem::Smart("Rusty steel".into()), None);
    h.app.set_wear(0.6);
    settle(&mut h);
    thumbs_done(&mut h);
    shot(&mut h, "simple_mode");
    // material library close-up: compact layout with the library in a wide column
    h.app.ui.prefs.layout_simple = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.45, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Library, PanelId::Look], active: 0 }) }, floating: vec![] };
    thumbs_done(&mut h);
    shot(&mut h, "material_library");
    h.app.ui.prefs.layout_simple = DockLayout::beginner();
    // decal tool
    let img = super::panels::decals::asset_dir("decals").unwrap().join("story/poster_missing.png");
    let img = if img.exists() { img } else { super::panels::decals::asset_dir("decals").unwrap().join("hazard_triangle.png") };
    h.app.ui.decal.image = Some(img);
    h.app.ui.decal.size = 0.45;
    h.app.ui.decal.wear = 0.35;
    h.app.set_tool(Tool::Decal);
    settle(&mut h);
    let v = anchor(&h, "viewport");
    h.click(v.center() + egui::vec2(-60.0, 30.0));
    h.hover(v.center() + egui::vec2(90.0, -40.0));
    shot(&mut h, "decal_tool");
    h.app.set_tool(Tool::Paint);
    // advanced mode
    h.app.set_mode(Mode::Advanced);
    let i = h.app.doc.layers.iter().position(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())).unwrap();
    let id = h.app.doc.layers[i].id;
    h.app.select(Some(id), true);
    thumbs_done(&mut h);
    shot(&mut h, "advanced_mode");
    // a second layout (Painting) for the docking docs
    *h.app.ui.prefs.layout_mut() = DockLayout::painting();
    h.app.select(Some(id), false);
    shot(&mut h, "layout_painting");
    *h.app.ui.prefs.layout_mut() = DockLayout::compact();
    shot(&mut h, "layout_compact");
    *h.app.ui.prefs.layout_mut() = DockLayout::texturing();
    // export dialog
    h.app.show_export = true;
    shot(&mut h, "export_dialog");
    h.app.show_export = false;
    // command palette and shortcut sheet
    h.key(egui::Key::K, egui::Modifiers::COMMAND);
    h.type_text("rus");
    shot(&mut h, "command_palette");
    h.key(egui::Key::Escape, egui::Modifiers::NONE);
    h.app.ui.cheatsheet = true;
    shot(&mut h, "shortcuts");
    h.app.ui.cheatsheet = false;
    // light theme
    h.app.ui.prefs.theme = super::design::ThemeKind::Light;
    super::design::apply(&h.ctx, super::design::ThemeKind::Light);
    shot(&mut h, "advanced_mode_light");
}

/// The design gallery in dark and light, for docs/design.
#[test]
#[ignore]
fn design_gallery_screenshots() {
    let Some(mut h) = Harness::new([1440.0, 1500.0], 1.0) else { return };
    h.app.ui.gallery = Some(Default::default());
    h.run(40);
    h.save_png(&docs().join("design/gallery.png"));
    super::design::apply(&h.ctx, super::design::ThemeKind::Light);
    h.run(40);
    h.save_png(&docs().join("design/gallery_light.png"));
}

/// The app icon in the top bar and on the welcome screen, dark and light
/// (docs/branding/*). `cargo test -p pigment branding_screenshots -- --ignored`
#[test]
#[ignore]
fn branding_screenshots() {
    let Some(mut h) = Harness::new([1280.0, 640.0], 2.0) else { return };
    let out = docs().join("branding");
    std::fs::create_dir_all(&out).unwrap();
    for (theme, name) in [(super::design::ThemeKind::Dark, "dark"), (super::design::ThemeKind::Light, "light")] {
        super::design::apply(&h.ctx, theme);
        h.app.ui.welcome = true;
        h.run(40);
        let img = h.save_png(&out.join(format!("welcome_{name}.png")));
        // the left of the top bar: logo, name and the first menus
        let bar = image::imageops::crop_imm(&img, 0, 0, 900, 80).to_image();
        bar.save(out.join(format!("top_bar_{name}.png"))).unwrap();
    }
}

/// Preview images for the welcome screen's samples (assets/samples/*.png).
#[test]
#[ignore]
fn sample_previews() {
    let Some(mut h) = harness() else { return };
    let out = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/samples");
    std::fs::create_dir_all(&out).unwrap();
    let rs = h.rs.clone();
    for s in super::welcome::SAMPLES.iter().filter(|s| s.mesh.is_none() || super::welcome::sample_mesh(s).is_some()) {
        h.app.open_sample(&rs, s);
        eprintln!("{}: {:?} {}", s.id, h.app.status, h.app.mesh.name);
        h.app.wait_jobs(&rs);
        h.app.ensure_composited(&rs);
        let (c, r) = h.app.mesh.bounding_sphere();
        h.app.camera.frame(c, r);
        h.app.camera.yaw = 0.7;
        h.app.camera.pitch = 0.3;
        h.app.camera.distance *= 0.82;
        h.app.view.show_env = false;
        h.app.viewport.ensure_targets(&rs.device, [480, 360]);
        h.app.viewport.draw(&rs.device, &rs.queue, &h.app.camera, &h.app.view, h.app.mesh_gpu.as_ref(), &h.app.env, &h.app.ts);
        let px = crate::render::gpu::readback(&rs.device, &rs.queue, h.app.viewport.color().unwrap());
        image::save_buffer(out.join(format!("{}.png", s.id)), &px, 480, 360, image::ExtendedColorType::Rgba8).unwrap();
    }
}

/// HiDPI: the window renders at 2x and the brush ring is sized in points.
#[test]
fn hidpi_renders_at_scale() {
    let Some(mut h) = Harness::new([900.0, 600.0], 2.0) else { return };
    settle(&mut h);
    let img = h.render();
    assert_eq!((img.width(), img.height()), (1800, 1200));
    assert_eq!(h.app.brush_radius_px(), h.app.brush.size * 0.5 * 2.0, "brush radius follows pixels per point");
    // the UI scale preference is a zoom factor on top
    h.ctx.set_zoom_factor(1.25);
    h.run(3);
    assert!((h.app.ui.prefs.ui_scale - 1.25).abs() < 1e-3, "zoom remembered: {}", h.app.ui.prefs.ui_scale);
}

/// Frame times of the whole window (UI + viewport + compositing) while
/// painting on a 4K texture set. `cargo test -p pigment --release ui_frame_timing -- --ignored --nocapture`
#[test]
#[ignore]
fn ui_frame_timing() {
    let Some(mut h) = harness() else { return };
    let rs = h.rs.clone();
    h.app.change_resolution(&rs, 4096);
    for (mode, layout) in [(Mode::Simple, DockLayout::beginner()), (Mode::Advanced, DockLayout::texturing())] {
        h.app.ui.prefs.mode = mode;
        *h.app.ui.prefs.layout_mut() = layout;
        settle(&mut h);
        thumbs_done(&mut h);
        let wait = |h: &Harness| {
            let _ = h.rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: None });
        };
        let mut idle = vec![];
        for _ in 0..60 {
            let t = Instant::now();
            h.step();
            wait(&h);
            idle.push(t.elapsed().as_secs_f64() * 1000.0);
        }
        let v = anchor(&h, "viewport");
        let (a, b) = (v.center() - egui::vec2(200.0, 50.0), v.center() + egui::vec2(200.0, 60.0));
        let mut paint = vec![];
        h.drag(a, a, 1);
        h.hover(a);
        h.step();
        h.events_push_press(a);
        for i in 0..120 {
            let p = a + (b - a) * (i as f32 / 119.0);
            h.hover(p);
            let t = Instant::now();
            h.step();
            wait(&h);
            paint.push(t.elapsed().as_secs_f64() * 1000.0);
        }
        h.events_push_release(b);
        h.run(2);
        let stats = |v: &mut Vec<f64>| {
            v.sort_by(|a, b| a.total_cmp(b));
            (v.iter().sum::<f64>() / v.len() as f64, v[v.len() * 95 / 100])
        };
        let (im, ip) = stats(&mut idle);
        let (pm, pp) = stats(&mut paint);
        eprintln!("{mode:?} 4096: idle frame {im:.2} ms (p95 {ip:.2}), painting frame {pm:.2} ms (p95 {pp:.2}), {} strokes", h.app.counters.strokes);
    }
}

/// README hero shot: Advanced mode on a finished town building under the night sky.
/// `cargo test -p pigment --release readme_hero -- --ignored`
#[test]
#[ignore]
fn readme_hero() {
    let Some(mut h) = Harness::new([1600.0, 900.0], 1.0) else { return };
    let rs = h.rs.clone();
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let project = std::env::var("PIGMENT_HERO_PROJECT").map(PathBuf::from).unwrap_or_else(|_| root.join("scenes/town/projects/building_b.pigment"));
    h.app.ui.welcome = false;
    h.app.run_pending_ui(&rs, Pending::OpenProject(project));
    h.app.set_mode(Mode::Advanced);
    *h.app.ui.prefs.layout_mut() = DockLayout::texturing();
    settle(&mut h);
    thumbs_done(&mut h);                       // material swatches render under studio light first
    let env = |k: &str, d: f32| std::env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d);
    let light = std::env::var("PIGMENT_HERO_LIGHT").unwrap_or_else(|_| "night_rain".into());
    h.app.set_lighting(&rs, &light);
    settle(&mut h);
    let (c, r) = h.app.mesh.bounding_sphere();
    h.app.camera.frame(c, r);
    h.app.camera.yaw = env("PIGMENT_HERO_YAW", 0.55);
    h.app.camera.pitch = env("PIGMENT_HERO_PITCH", 0.12);
    h.app.camera.distance *= env("PIGMENT_HERO_ZOOM", 0.78);
    if let Some(i) = h.app.doc.layers.iter().position(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())) {
        let id = h.app.doc.layers[i].id;
        h.app.select(Some(id), false);
    }
    thumbs_done(&mut h);
    h.run(40);
    let out = std::env::var("PIGMENT_HERO_OUT").map(PathBuf::from).unwrap_or_else(|_| docs().join("readme/pigment_ui.png"));
    std::fs::create_dir_all(out.parent().unwrap()).unwrap();
    h.save_png(&out);
}

/// Foliage brush: V picks the tool and opens its panel, a drag paints cards
/// onto a foliage layer as one undo step, erase removes them, and the
/// quick "Add moss" action works from the panel API.
#[test]
fn foliage_brush_paints_erases_and_quick_plants() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    h.key(egui::Key::V, egui::Modifiers::NONE);
    settle(&mut h);
    assert_eq!(h.app.tool(), Tool::Foliage);
    assert!(h.app.ui.prefs.layout().contains(PanelId::FoliageBrush), "V opens the foliage brush panel");
    h.app.foliage.brush.cells = vec!["grass".into(), "weed".into()];
    h.app.foliage.brush.radius = 0.15;
    h.app.foliage.brush.density = 200.0;
    let v = anchor(&h, "viewport");
    let undo_before = h.app.history.history().1;
    h.drag(v.center() - egui::vec2(60.0, 0.0), v.center() + egui::vec2(60.0, 0.0), 12);
    settle(&mut h);
    let count = |h: &Harness| h.app.doc.layers.iter().filter_map(|l| l.foliage()).map(|f| f.instances.len()).sum::<usize>();
    let n = count(&h);
    assert!(n > 10, "the drag painted cards: {n} ({:?})", h.app.status);
    assert!(h.app.viewport.foliage.card_count() as usize >= n);
    assert_eq!(h.app.history.history().1, undo_before + 1, "one stroke = one undo step");
    // erase with the same stroke
    h.app.foliage.brush.erase = true;
    h.app.foliage.brush.radius = 0.4;
    h.drag(v.center() - egui::vec2(60.0, 0.0), v.center() + egui::vec2(60.0, 0.0), 12);
    settle(&mut h);
    assert!(count(&h) < n / 4, "erased: {} of {n} left", count(&h));
    h.key(egui::Key::Z, egui::Modifiers::COMMAND);
    settle(&mut h);
    assert_eq!(count(&h), n, "undo brings the erased cards back");
    // one-click moss (Simple mode's Plants buttons call this)
    h.app.foliage.brush.erase = false;
    let added = h.app.quick_foliage(&h.rs.clone(), "moss").unwrap();
    assert!(added > 20, "{added}");
    assert!(h.app.history.undo_label().is_some_and(|l| l.contains("Moss")), "{:?}", h.app.history.undo_label());
    // the panels draw with a foliage layer selected
    for p in [PanelId::FoliageLibrary, PanelId::FoliageBrush, PanelId::FoliageCells] {
        *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.6, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![p], active: 0 }) }, floating: vec![] };
        h.run(3);
        assert!(h.app.ui.dock_rects.iter().any(|(id, r)| *id == p && r.width() > 50.0), "{p:?}");
    }
    h.key(egui::Key::Escape, egui::Modifiers::NONE);
}

/// Docs screenshots of the foliage UI (`docs/agents/foliage/`). Opens the
/// project given by PIGMENT_FOLIAGE_PROJECT (the proof's building_a) if set.
/// `cargo test -p pigment --release foliage_screenshots -- --ignored`
#[test]
#[ignore]
fn foliage_screenshots() {
    let Some(mut h) = harness() else { return };
    let out = docs().join("agents/foliage");
    std::fs::create_dir_all(&out).unwrap();
    let shot = |h: &mut Harness, name: &str| {
        h.run(30);
        h.save_png(&out.join(format!("{name}.png")));
    };
    h.app.ui.welcome = false;
    settle(&mut h);
    if let Ok(p) = std::env::var("PIGMENT_FOLIAGE_PROJECT") {
        h.app.run_pending_ui(&h.rs.clone(), Pending::OpenProject(PathBuf::from(p)));
    } else {
        let mesh = docs().join("../assets/town/building_a.glb");
        h.app.run_pending_ui(&h.rs.clone(), Pending::NewFromMesh(mesh));
        h.app.quick_foliage(&h.rs.clone(), "moss").unwrap();
        h.app.quick_foliage(&h.rs.clone(), "ivy").unwrap();
        h.app.quick_foliage(&h.rs.clone(), "grass").unwrap();
    }
    settle(&mut h);
    h.app.set_mode(Mode::Advanced);
    h.app.set_tool(Tool::Foliage);
    h.app.ui.prefs.layout_mut().open(PanelId::FoliageLibrary);
    // close-up of the ivy wall
    let (c, _) = h.app.mesh.bounding_sphere();
    h.app.camera.target = glam::Vec3::new(c.x + 3.0, 2.6, c.z + 0.5);
    h.app.camera.distance = 9.0;
    h.app.camera.yaw = 70f32.to_radians();
    h.app.camera.pitch = 8f32.to_radians();
    settle(&mut h);
    let v = anchor(&h, "viewport");
    h.hover(v.center() + egui::vec2(40.0, 60.0));
    shot(&mut h, "ui_foliage_brush");
    // the whole building in Simple mode with the Plants buttons
    h.app.set_tool(Tool::Paint);
    h.app.set_mode(Mode::Simple);
    h.app.ui.prefs.layout_simple = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.7, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Look, PanelId::Library], active: 0 }) }, floating: vec![] };
    let (c, r) = h.app.mesh.bounding_sphere();
    h.app.camera.frame(c, r);
    h.app.camera.yaw = 55f32.to_radians();
    h.app.camera.pitch = 12f32.to_radians();
    shot(&mut h, "ui_simple_plants");
}
