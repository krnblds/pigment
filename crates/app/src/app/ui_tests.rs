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
    let lib = h.app.ui.dock_rects.iter().filter(|(p, _)| *p == PanelId::Library).map(|(_, r)| *r).max_by(|a, b| a.width().total_cmp(&b.width())).expect("library visible");
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

/// Layer lock and the weathering level are saved in the project.
#[test]
fn lock_and_weathering_survive_save_and_open() {
    let Some(mut h) = harness() else { return };
    let rs = h.rs.clone();
    settle(&mut h);
    h.app.apply_library(&rs, &LibItem::Smart("Rusty steel".into()), None);
    h.app.set_wear(0.8);
    let worn = gen_amounts(&h);
    let id = h.app.doc.layers.iter().find(|l| l.is_paint()).unwrap().id;
    h.app.doc.layer_mut(id).unwrap().locked = true;
    h.app.commit_doc_changes();
    let dir = std::env::temp_dir().join(format!("pigment-ui-lock-{}.pigment", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    h.app.save_to(&rs, dir.clone());
    h.app.run_pending(&rs, Pending::NewTorus);
    h.app.request(&rs, Pending::OpenProject(dir.clone()));
    settle(&mut h);
    assert!((h.app.wear() - 0.8).abs() < 1e-4, "weathering {}", h.app.wear());
    assert_eq!(gen_amounts(&h), worn);
    assert!(h.app.doc.layers.iter().any(|l| l.is_paint() && l.locked), "lock saved");
    // "as authored" survives too: 50% gives back the material's own amounts
    h.app.set_wear(0.5);
    let authored = gen_amounts(&h);
    assert!(authored.iter().zip(&worn).all(|(a, w)| a <= w) && authored != worn, "{authored:?} vs {worn:?}");
    let _ = std::fs::remove_dir_all(&dir);
}

/// Variants defined in the panel export from the UI, one folder each, and
/// leave the project as it was.
#[test]
fn variants_panel_defines_and_exports() {
    let Some(mut h) = harness() else { return };
    let rs = h.rs.clone();
    settle(&mut h);
    h.app.apply_library(&rs, &LibItem::Smart("Rusty steel".into()), None);
    let i = h.app.doc.layers.iter().position(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())).unwrap();
    h.app.doc.layers[i].variant.group = "grime".into();
    h.app.set_mode(super::prefs::Mode::Advanced);
    h.app.ui.prefs.layout_mut().open(PanelId::Variants);
    settle(&mut h);
    // two variants, the second hides the group
    for _ in 0..2 {
        h.app.doc.variants.defs.push(pigment_core::variants::VariantDef { name: format!("v{}", h.app.doc.variants.defs.len()), ..Default::default() });
    }
    h.app.doc.variants.defs[1].disable.push("grime".into());
    h.app.doc.variants.defs[1].seed = 7;
    h.run(4);
    assert!(h.app.check_variants().is_ok());
    let out = std::env::temp_dir().join(format!("pigment-ui-variants-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&out);
    h.app.ui.prefs.export_dir = Some(out.clone());
    h.app.export_name = "Crate".into();
    let doc = h.app.doc.clone();
    // the panel draws the button (it may be scrolled out of a short dock); run its action
    anchor(&h, "export_variants");
    h.app.run_export_variants(&rs);
    settle(&mut h);
    for v in ["v0", "v1"] {
        let d = out.join("Crate/variants").join(format!("Crate__{v}"));
        assert!(d.join("variant.json").is_file(), "{d:?}: {:?}", h.app.status);
        assert!(d.join("preview.png").is_file());
    }
    let side: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(out.join("Crate/variants/Crate__v1/variant.json")).unwrap()).unwrap();
    assert!(side["hidden_layers"].as_array().unwrap().iter().any(|n| n == h.app.doc.layers[i].name.as_str()), "{side}");
    assert_eq!(h.app.doc.layers, doc.layers, "the project is unchanged");
    // preview: one undo step that shows the variant, Ctrl+Z goes back
    let v = h.app.doc.variants.defs[1].clone();
    h.app.preview_variant(&v).unwrap();
    assert!(!h.app.doc.layers[i].visible && h.app.doc.variants.seed == 7);
    h.app.undo(&rs, false);
    assert!(h.app.doc.layers[i].visible);
    // a bad name is reported, not exported
    h.app.doc.variants.defs[0].name = "v1".into();
    assert!(h.app.check_variants().unwrap_err().contains("duplicate"));
    let _ = std::fs::remove_dir_all(&out);
}

/// View > Save image renders the viewport at 2x without moving the camera.
#[test]
fn save_render_and_turntable() {
    let Some(mut h) = harness() else { return };
    let rs = h.rs.clone();
    settle(&mut h);
    let out = std::env::temp_dir().join(format!("pigment-ui-render-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&out);
    h.app.ui.prefs.export_dir = Some(out.clone());
    h.app.export_name = "Crate".into();
    h.app.camera.yaw = 1.1;
    let (cam, size) = (h.app.camera.clone(), h.app.viewport.size());
    h.key(egui::Key::R, egui::Modifiers::COMMAND | egui::Modifiers::SHIFT);
    h.run(2);
    let png = out.join("Crate/renders/Crate_001.png");
    let img = image::open(&png).unwrap_or_else(|e| panic!("{png:?}: {e} {:?}", h.app.status));
    assert_eq!([img.width(), img.height()], [size[0] * 2, size[1] * 2]);
    assert_eq!(h.app.camera, cam, "camera put back");
    h.app.run_render(&rs, true);
    assert!(out.join("Crate/renders/Crate_turntable_001.png").is_file());
    let _ = std::fs::remove_dir_all(&out);
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

/// A three-quarter view of the whole model, `zoom` > 1 closer.
fn hero_camera(h: &mut Harness, yaw_deg: f32, pitch_deg: f32, zoom: f32) {
    let (c, r) = h.app.full_mesh().bounding_sphere();
    h.app.camera.frame(c, r);
    h.app.camera.yaw = yaw_deg.to_radians();
    h.app.camera.pitch = pitch_deg.to_radians();
    h.app.camera.distance /= zoom;
}

/// Screenshots for docs/agents/ui and docs/design. Ignored: run by hand.
/// Staged on the samples a new user sees: the vending machine for Simple
/// mode and decals, the finished town building for the layer stack, both on
/// the dark lightbox (glossy floor, reflection, contact shadow).
#[test]
#[ignore]
fn ui_screenshots() {
    let Some(mut h) = harness() else { return };
    let rs = h.rs.clone();
    let out = docs().join("agents/ui");
    let shot = |h: &mut Harness, name: &str| {
        h.run(30);
        h.save_png(&out.join(format!("{name}.png")));
    };
    // welcome (first run: no recent files, so the "how it works" steps show)
    h.app.ui.welcome = true;
    settle(&mut h);
    shot(&mut h, "welcome");
    // simple mode on the vending machine with a smart material
    h.click(anchor(&h, "sample_vending").center());
    settle(&mut h);
    thumbs_done(&mut h);
    h.app.apply_library(&rs, &LibItem::Smart("Worn red paint metal".into()), None);
    h.app.set_wear(0.7);
    h.app.set_lighting(&rs, "lightbox_dark");
    hero_camera(&mut h, 32.0, 14.0, 1.05);
    settle(&mut h);
    thumbs_done(&mut h);
    h.hover(anchor(&h, "viewport").center() + egui::vec2(40.0, -60.0));
    shot(&mut h, "simple_mode");
    // material library close-up: compact layout with the library in a wide column
    h.app.ui.prefs.layout_simple = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.45, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Library, PanelId::Look], active: 0 }) }, floating: vec![] };
    thumbs_done(&mut h);
    shot(&mut h, "material_library");
    h.app.ui.prefs.layout_simple = DockLayout::beginner();
    // decal tool: a torn poster stamped on the side, the ghost of the next one under the cursor
    let img = super::panels::decals::asset_dir("decals").unwrap().join("story/poster_missing.png");
    let img = if img.exists() { img } else { super::panels::decals::asset_dir("decals").unwrap().join("hazard_triangle.png") };
    h.app.ui.decal.image = Some(img);
    h.app.ui.decal.size = 0.32;
    h.app.ui.decal.wear = 0.35;
    h.app.set_tool(Tool::Decal);
    settle(&mut h);
    let v = anchor(&h, "viewport");
    h.click(v.center() + egui::vec2(-50.0, 10.0));
    h.hover(v.center() + egui::vec2(70.0, -30.0));
    shot(&mut h, "decal_tool");
    h.app.set_tool(Tool::Paint);
    // advanced mode on the finished town building: folders, generators, glowing windows
    let building = super::welcome::SAMPLES.iter().position(|s| s.id == "building").unwrap();
    let has_building = super::welcome::sample_project(&super::welcome::SAMPLES[building]).is_some();
    if has_building {
        h.app.open_sample(&rs, &super::welcome::SAMPLES[building]);
        settle(&mut h);
        h.app.set_lighting(&rs, "lightbox_dark");
        h.app.view.bloom.enabled = true;
        hero_camera(&mut h, 38.0, 8.0, 0.95);
        // a few real steps for the History panel
        h.app.set_wear(0.62);
        h.app.commit_doc_changes();
        h.app.doc.variants.seed = 11;
        h.app.commit_doc_changes();
    }
    h.app.set_mode(Mode::Advanced);
    let i = h.app.doc.layers.iter().rposition(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())).unwrap();
    let id = h.app.doc.layers[i].id;
    h.app.select(Some(id), true);
    settle(&mut h);
    thumbs_done(&mut h);
    shot(&mut h, "advanced_mode");
    // variants: the building's stored looks, ready to export, in a tall column
    let advanced = h.app.ui.prefs.layout().clone();
    *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.66, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Variants, PanelId::Layers], active: 0 }) }, floating: vec![] };
    h.app.select(Some(id), false);
    shot(&mut h, "variants");
    *h.app.ui.prefs.layout_mut() = advanced;
    // a second layout (Painting) for the docking docs
    *h.app.ui.prefs.layout_mut() = DockLayout::painting();
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
    h.type_text("vari");
    shot(&mut h, "command_palette");
    h.key(egui::Key::Escape, egui::Modifiers::NONE);
    h.app.ui.cheatsheet = true;
    shot(&mut h, "shortcuts");
    h.app.ui.cheatsheet = false;
    // light theme on the bright lightbox
    h.app.ui.prefs.theme = super::design::ThemeKind::Light;
    super::design::apply(&h.ctx, super::design::ThemeKind::Light);
    h.app.set_lighting(&rs, "lightbox");
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
        h.app.camera.distance *= 0.95;
        // on the dark lightbox: a glossy floor with the model's reflection and contact shadow
        h.app.set_lighting(&rs, "lightbox_dark");
        h.app.view.show_env = true;
        h.app.view.stage = true;
        let [w, ht] = [960, 720];
        h.app.viewport.ensure_targets(&rs.device, [w, ht]);
        h.app.viewport.draw(&rs.device, &rs.queue, &h.app.camera, &h.app.view, h.app.mesh_gpu.as_ref(), &h.app.env, &h.app.ts);
        let px = crate::render::gpu::readback(&rs.device, &rs.queue, h.app.viewport.color().unwrap());
        image::save_buffer(out.join(format!("{}.png", s.id)), &px, w, ht, image::ExtendedColorType::Rgba8).unwrap();
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

/// Filters and anchors in the Properties and Mask panels: a filter layer's
/// stack, a mask filter and the anchor toggle; clicking a filter's switch
/// turns it off (and the composite follows).
#[test]
fn filter_stacks_and_anchor_in_panels() {
    use pigment_core::filters::{Filter, FilterKind};
    // tall, so the mask panel's filter section is on screen
    let Some(mut h) = Harness::new([1440.0, 2400.0], 1.0) else { return };
    settle(&mut h);
    let layout = |p: PanelId| DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.5, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![p], active: 0 }) }, floating: vec![] };
    super::panels::filters::add_filter_layer(&mut h.app);
    let id = h.app.doc.layers.iter().find(|l| matches!(l.kind, LayerKind::Filter {})).unwrap().id;
    h.app.select(Some(id), true);
    *h.app.ui.prefs.layout_mut() = layout(PanelId::Properties);
    h.run(4);
    let r = anchor(&h, "layer_filter_0");
    h.click(r.center());
    h.run(3);
    let l = h.app.doc.layer(id).unwrap();
    assert!(!l.filters[0].enabled, "clicking the switch disables the filter");
    // mask filters in the Mask panel
    let i = h.app.edge_wear_layer().unwrap();
    let wid = h.app.doc.layers[i].id;
    h.app.doc.layers[i].mask.as_mut().unwrap().filters.push(Filter::new(FilterKind::Blur));
    h.app.doc.layers[i].anchor = Some("Wear".into());
    h.app.select(Some(wid), true);
    *h.app.ui.prefs.layout_mut() = layout(PanelId::Mask);
    h.run(4);
    let r = anchor(&h, "mask_filter_0");
    h.click(r.center());
    h.run(3);
    assert!(!h.app.doc.layers[i].mask.as_ref().unwrap().filters[0].enabled);
    *h.app.ui.prefs.layout_mut() = layout(PanelId::Properties);
    h.run(4);
}

/// Brush engine in the viewport: pen pressure from touch force, Shift-click
/// line from the last stroke's end, the path tool (click points, Enter), and
/// the Brush panel with clone / stencil / symmetry sections.
#[test]
fn brush_engine_pen_line_and_path() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let paint = h.app.doc.layers.iter().rposition(|l| l.is_paint()).unwrap();
    let id = h.app.doc.layers[paint].id;
    h.app.select(Some(id), false);
    h.app.set_tool(Tool::Paint);
    h.run(3);
    let vp = anchor(&h, "viewport");
    let a = vp.center() + egui::vec2(-40.0, 0.0);
    let b = vp.center() + egui::vec2(40.0, 20.0);
    // pen pressure
    h.hover(a);
    h.push_event(egui::Event::Touch { device_id: egui::TouchDeviceId(1), id: egui::TouchId(1), phase: egui::TouchPhase::Move, pos: a, force: Some(0.3) });
    h.step();
    assert!((h.app.brush.pressure - 0.3).abs() < 1e-4, "pen force read: {}", h.app.brush.pressure);
    h.push_event(egui::Event::Touch { device_id: egui::TouchDeviceId(1), id: egui::TouchId(1), phase: egui::TouchPhase::End, pos: a, force: Some(0.0) });
    h.step();
    assert_eq!(h.app.brush.pressure, 1.0, "lifting the pen resets pressure");
    // a click paints, Shift-click paints a line from there
    let n0 = h.app.counters.strokes;
    h.click(a);
    assert_eq!(h.app.counters.strokes, n0 + 1);
    assert!(h.app.brush.last_end.is_some());
    h.click_with(b, egui::Modifiers::SHIFT);
    assert_eq!(h.app.counters.strokes, n0 + 2, "Shift-click paints a straight line");
    // path tool: clicks add points, Enter paints once
    h.app.brush.path_mode = true;
    for p in [a, b, vp.center() + egui::vec2(0.0, -50.0)] {
        h.click(p);
    }
    assert_eq!(h.app.brush.path.len(), 3);
    assert_eq!(h.app.counters.strokes, n0 + 2, "clicks only add path points");
    h.key(egui::Key::Enter, Default::default());
    assert_eq!(h.app.counters.strokes, n0 + 3, "Enter paints the path");
    assert!(h.app.brush.path.is_empty());
    h.app.brush.path_mode = false;
    // the Brush panel with the engine sections open
    h.app.brush.tool = super::BrushTool::Clone;
    h.app.brush.symmetry.x = true;
    *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.5, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Brush], active: 0 }) }, floating: vec![] };
    h.run(4);
    assert!(h.app.brush.tips.len() >= 10, "the tip library loads ({} tips)", h.app.brush.tips.len());
}

/// High-to-low bake and ID masks in the panels: bake the generated pair, then
/// the Texture set & bake panel shows the high bake, and the Mask panel offers
/// the ID map's colours.
#[test]
fn high_bake_and_id_mask_panels() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let (low, high) = pigment_core::hibake::test_pair();
    let rs = h.rs.clone();
    h.app.new_project(&rs, low, None, Document::new_default());
    let hb = pigment_core::hibake::HighBake::new("generated", vec![pigment_core::hibake::BakeMap::Normal, pigment_core::hibake::BakeMap::ColorId]);
    h.app.bake_high(&rs, Some(&high), hb, true).unwrap();
    let path = pigment_core::image_fill::resolve_path(h.app.doc.id_map.as_ref().unwrap(), &h.app.image_bases()).unwrap();
    assert_eq!(super::panels::hibake::id_palette(&path).len(), 3, "three materials, three ID colours");
    let layout = |p: PanelId| DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.5, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![p], active: 0 }) }, floating: vec![] };
    *h.app.ui.prefs.layout_mut() = layout(PanelId::TextureSet);
    h.run(4);
    let i = h.app.doc.layers.len() - 1;
    let res = h.app.doc.mint();
    h.app.ts.new_mask(&rs.device, &rs.queue, res, true);
    h.app.doc.layers[i].mask = Some(Mask::new(res));
    let id = h.app.doc.layers[i].id;
    h.app.select(Some(id), true);
    *h.app.ui.prefs.layout_mut() = layout(PanelId::Mask);
    h.run(4);
}

/// Texture sets in the UI: split a two-material box, the Layers panel shows
/// the switcher, switching changes the stack, and the viewport draws both
/// sets (the parked one too).
#[test]
fn texture_set_switcher_and_viewport() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let mut mesh = pigment_core::hibake::rounded_box(glam::Vec3::new(0.5, 0.35, 0.4), 0.06, 8, None, Some(&|p: glam::Vec3| if p.y > 0.33 { 1 } else { 0 }));
    mesh.material_names = vec!["body".into(), "lid".into()];
    let rs = h.rs.clone();
    h.app.new_project(&rs, mesh, None, Document::new_default());
    let specs = pigment_core::texsets::sets_by_material(&h.app.mesh);
    assert_eq!(h.app.split_sets(&rs, specs, &[]).unwrap(), vec!["body".to_string(), "lid".to_string()]);
    *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.6, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Layers, PanelId::TextureSet], active: 0 }) }, floating: vec![] };
    h.run(4);
    let before = h.render();
    // paint the lid set's base red: the viewport (showing the body set active) changes
    h.app.activate_set(&rs, "lid").unwrap();
    if let LayerKind::Fill { values } = &mut h.app.doc.layers[0].kind {
        values.base_color = [1.0, 0.0, 0.0];
    }
    h.app.activate_set(&rs, "body").unwrap();
    h.run(4);
    let after = h.render();
    let reds = |img: &image::RgbaImage| img.pixels().filter(|p| p.0[0] > 150 && p.0[1] < 70 && p.0[2] < 70).count();
    assert!(reds(&after) > reds(&before) + 100, "the parked lid set is drawn ({} -> {})", reds(&before), reds(&after));
    assert_eq!(h.app.active_set_name(), "body");
}

/// Export templates in the Export panel: the picker and the editor on a copy
/// of a built-in render; a copy saved with the project is found by id.
#[test]
fn export_template_editor() {
    let Some(mut h) = Harness::new([1440.0, 1800.0], 1.0) else { return };
    settle(&mut h);
    super::panels::templates::edit_copy_for_tests(&h.app, "unity_hdrp");
    *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.45, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Export], active: 0 }) }, floating: vec![] };
    h.run(6);
    let mut t = h.app.find_template("unity_hdrp").unwrap();
    t.id = "hdrp_custom".into();
    t.outputs[1].channels[2] = "const:0".into();
    h.app.save_template(t, super::templates_app::TemplateScope::Project).unwrap();
    assert_eq!(h.app.find_template("hdrp_custom").unwrap().outputs[1].channels[2], "const:0");
    assert!(h.app.save_template(h.app.find_template("unreal").unwrap(), super::templates_app::TemplateScope::Builtin).is_err());
    if std::env::var("PIGMENT_SHOTS").is_ok() {
        h.save_png(&docs().join("agents/parity/templates_ui.png"));
    }
}

/// Decal objects in the viewport: on a decal layer, a click selects the
/// decal under the cursor, a drag slides it over the surface, Ctrl+wheel
/// scales it; the Properties panel lists it.
#[test]
fn decal_gizmo_select_drag_scale() {
    let Some(mut h) = harness() else { return };
    settle(&mut h);
    let rs = h.rs.clone();
    h.app.new_project(&rs, Mesh::tile_grid(1), None, Document::new_default());
    let mut l = h.app.doc.new_paint_layer("Decals");
    l.decals = Some(Default::default());
    let lid = l.id;
    h.app.doc.layers.push(l);
    let img = super::panels::decals::asset_dir("decals").unwrap().join("hazard_triangle.png");
    let i = h.app.doc.layers.len() - 1;
    h.app.doc.layers[i].decals.as_mut().unwrap().add(pigment_core::decal_layer::DecalObject {
        id: 0,
        name: "tri".into(),
        group: String::new(),
        image: img.to_string_lossy().into_owned(),
        center: [0.0, 0.0, 0.0],
        normal: [0.0, 0.0, 1.0],
        size: [0.6, 0.6],
        rotation: 0.0,
        depth: 0.1,
        projection: Default::default(),
        wear: Default::default(),
        values: pigment_core::decal_layer::white_decal(),
        channels: pigment_core::decal_layer::default_channels(),
        enabled: true,
    });
    h.app.select(Some(lid), false);
    h.app.set_tool(Tool::Paint);
    h.app.camera.yaw = 0.0;
    h.app.camera.pitch = 0.0;
    *h.app.ui.prefs.layout_mut() = DockLayout { root: super::dock::Node::Split { vertical: false, ratio: 0.6, a: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Viewport], active: 0 }), b: Box::new(super::dock::Node::Leaf { tabs: vec![PanelId::Properties], active: 0 }) }, floating: vec![] };
    h.run(4);
    let vp = anchor(&h, "viewport");
    h.click(vp.center());
    assert_eq!(h.app.decal_sel, Some(0), "the click selects the decal under the cursor");
    let strokes = h.app.counters.strokes;
    h.drag(vp.center(), vp.center() + egui::vec2(60.0, 0.0), 6);
    h.run(2);
    let o = &h.app.doc.layers[i].decals.as_ref().unwrap().objects[0];
    assert!(o.center[0] > 0.05, "dragging slides it along the surface: {:?}", o.center);
    assert_eq!(h.app.counters.strokes, strokes, "no paint stroke on a decal layer");
    let w0 = o.size[0];
    h.hover(vp.center() + egui::vec2(60.0, 0.0));
    h.push_event(egui::Event::ModifiersChanged(egui::Modifiers::CTRL));
    h.push_event(egui::Event::MouseWheel { unit: egui::MouseWheelUnit::Point, delta: egui::vec2(0.0, 120.0), modifiers: egui::Modifiers::CTRL, phase: egui::TouchPhase::Move, source: egui::MouseWheelSource::Wheel });
    h.run(4);
    h.push_event(egui::Event::ModifiersChanged(Default::default()));
    h.run(2);
    let w1 = h.app.doc.layers[i].decals.as_ref().unwrap().objects[0].size[0];
    assert!(w1 > w0 * 1.02, "Ctrl+wheel scales ({w0} -> {w1})");
}
