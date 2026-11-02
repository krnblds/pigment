//! The window, built from the design system (`design/`) and dockable panels
//! (`dock.rs`, `panels/`):
//!
//! ```text
//! ┌ top bar: logo · menus · [Simple|Advanced] ········ undo redo · ⌘K · ? · Send to Blender · Export ┐
//! ├ tool options (brush size / strength, decal size / wear ...)                                     ┤
//! ├ tool ┬ dock: viewport + panels in tabs and splits, user-arranged, per mode ──────────────────────┤
//! │ rail │                                                                                         │
//! ├ status: message · progress ················································· texture size ┤
//! ```

use super::design::{self as ds, font, icon, size, space, Btn, IconBtn, Icon, RichTip, ToastKind};
use super::dock::{self, DockLayout, PanelId};
use super::jobs::{self, Job};
use super::prefs::{Mode, Prefs};
use super::*;
use egui::{pos2, vec2, Align2, Rect, Stroke};

/// The active tool, derived from the brush / decal / pick state.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tool {
    Paint,
    Erase,
    Fill,
    Decal,
    Pick,
    /// Paint foliage cards onto the model (V).
    Foliage,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DecalMode {
    /// Click: stick the image flat on the surface under the cursor, sized in metres.
    Stamp,
    /// Drag a box: project the image from the camera.
    Box,
    /// Click a part: fit the image to that part's face.
    Part,
    /// Scatter many over the model with wear.
    Scatter,
}

pub struct DecalSettings {
    pub mode: DecalMode,
    pub image: Option<PathBuf>,
    pub size: f32,
    pub rotation: f32,
    pub opacity: f32,
    pub wear: f32,
    pub fade: f32,
    pub grunge: bool,
    pub count: u32,
    pub size_range: (f32, f32),
    pub seed: u64,
    pub walls_only: bool,
}

impl Default for DecalSettings {
    fn default() -> Self {
        DecalSettings { mode: DecalMode::Stamp, image: None, size: 0.3, rotation: 0.0, opacity: 1.0, wear: 0.0, fade: 0.0, grunge: false, count: 8, size_range: (0.2, 0.4), seed: 1, walls_only: false }
    }
}

/// A library entry: a smart material, a single material preset or a saved file.
#[derive(Clone, Debug, PartialEq)]
pub enum LibItem {
    Smart(String),
    Preset(String),
    File(PathBuf),
}

impl LibItem {
    pub fn name(&self) -> String {
        match self {
            LibItem::Smart(n) | LibItem::Preset(n) => n.clone(),
            LibItem::File(p) => p.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default(),
        }
    }
}

#[derive(Default)]
pub struct NewProjectDialog {
    pub open: bool,
    pub kind: usize,
    pub size_m: [f32; 2],
    pub strips: u32,
    pub cells: u32,
    pub resolution: u32,
}

pub struct UiState {
    pub prefs: Prefs,
    pub welcome: bool,
    pub toasts: ds::Toasts,
    pub jobs: Vec<Job>,
    pub palette: ds::Palette2State,
    pub cheatsheet: bool,
    pub gallery: Option<ds::gallery::GalleryState>,
    pub async_bake: bool,
    pub last_autosave: Instant,
    pub last_export: Option<PathBuf>,
    pub panels: Option<super::panels::Panels>,
    pub fill_tool: bool,
    pub decal: DecalSettings,
    pub lib_current: Option<LibItem>,
    pub wear: f32,
    pub wear_bases: std::collections::HashMap<LayerId, f32>,
    pub locked: HashSet<LayerId>,
    pub new_project: NewProjectDialog,
    pub settings: bool,
    pub save_layout: Option<String>,
    pub export_target: &'static str,
    pub thumbs: Option<super::panels::library::Thumbs>,
    pub prefs_dirty_at: Option<Instant>,
    pub hover_part: Option<(egui::Pos2, Option<(glam::Vec3, glam::Vec3)>)>,
    pub viewport_rect: Rect,
    pub dock_rects: Vec<(PanelId, Rect)>,
    pub pending_theme: bool,
    pub pending_sample: Option<usize>,
    /// Directory listings, refreshed every few seconds instead of every frame.
    pub fs_cache: std::collections::HashMap<String, (Instant, Vec<PathBuf>)>,
    pub image_thumbs: super::panels::library::ImageThumbs,
}

impl UiState {
    pub fn new(prefs: Prefs) -> UiState {
        let export_target = jobs::target(&prefs.export_target).id;
        UiState {
            prefs,
            welcome: false,
            toasts: Default::default(),
            jobs: vec![],
            palette: Default::default(),
            cheatsheet: false,
            gallery: None,
            async_bake: false,
            last_autosave: Instant::now(),
            last_export: None,
            panels: Some(super::panels::Panels::new()),
            fill_tool: false,
            decal: Default::default(),
            lib_current: None,
            wear: 0.5,
            wear_bases: Default::default(),
            locked: Default::default(),
            new_project: NewProjectDialog { size_m: [2.0, 2.0], strips: 4, cells: 6, resolution: 2048, ..Default::default() },
            settings: false,
            save_layout: None,
            export_target,
            thumbs: None,
            prefs_dirty_at: None,
            hover_part: None,
            viewport_rect: Rect::NOTHING,
            dock_rects: vec![],
            pending_theme: false,
            pending_sample: None,
            fs_cache: Default::default(),
            image_thumbs: Default::default(),
        }
    }
}

// ------------------------------------------------------------------ frame

impl eframe::App for PigmentApp {
    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        let Some(rs) = frame.wgpu_render_state().cloned() else { return };
        self.ppp = ui.ctx().pixels_per_point();
        if let Some(g) = &mut self.ui.gallery {
            let p = ds::pal(ui);
            let mut light = ds::theme(ui.ctx()).kind == ds::ThemeKind::Light;
            egui::CentralPanel::default().frame(ds::panel_frame(&p).inner_margin(egui::Margin::same(space::XXL as i8))).show(ui, |ui| {
                if ds::toggle(ui, &mut light, "Light theme").changed() {
                    ds::apply(ui.ctx(), if light { ds::ThemeKind::Light } else { ds::ThemeKind::Dark });
                }
                ds::gallery::show(ui, g);
            });
            return;
        }

        let now = Instant::now();
        self.frame_times.push((now - self.last_frame).as_secs_f32());
        self.last_frame = now;
        if self.frame_times.len() > 60 {
            self.frame_times.remove(0);
        }

        let dropped: Vec<PathBuf> = ui.input(|i| i.raw.dropped_files.iter().filter_map(|f| { let p = f.path(); (!p.as_os_str().is_empty()).then(|| p.to_path_buf()) }).collect());
        if let Some(p) = dropped.first() {
            self.open_path(&rs, p);
        }

        self.anchors.clear();
        self.poll_jobs(&rs);
        self.shortcuts(ui, &rs);
        if std::mem::take(&mut self.dump_requested) {
            self.debug_dump(&rs, &std::env::temp_dir().join("pig").join("dump"));
        }
        let p = ds::pal(ui);

        egui::Panel::top("top bar").frame(ds::bar_frame(&p).stroke(Stroke::NONE)).show(ui, |ui| self.top_bar(ui, &rs));
        egui::Panel::bottom("status").frame(ds::bar_frame(&p).stroke(Stroke::NONE)).show(ui, |ui| self.status_bar(ui));
        if self.ui.welcome {
            egui::CentralPanel::default().frame(egui::Frame::new().fill(p.bg)).show(ui, |ui| self.welcome_screen(ui, &rs));
        } else {
            egui::Panel::top("tool options").frame(ds::bar_frame(&p).fill(p.surface_raised).stroke(Stroke::NONE)).show(ui, |ui| self.tool_options(ui, &rs));
            egui::Panel::left("tool rail").exact_size(size::TOOL + space::LG * 2.0).resizable(false).frame(egui::Frame::new().fill(p.surface).inner_margin(egui::Margin::same(space::SM as i8))).show(ui, |ui| self.tool_rail(ui));
            egui::CentralPanel::default().frame(egui::Frame::new().fill(p.bg).inner_margin(egui::Margin::same(space::XS as i8))).show(ui, |ui| {
                let mut layout = std::mem::take(self.ui.prefs.layout_mut());
                let before = layout.clone();
                let mut panels = self.ui.panels.take().unwrap_or_default();
                self.ui.dock_rects.clear();
                let out = dock::show(ui, &mut layout, |ui, id| panels.show(id, self, ui, &rs));
                self.ui.panels = Some(panels);
                self.ui.dock_rects.extend(out.rects);
                if layout != before {
                    self.prefs_changed();
                }
                *self.ui.prefs.layout_mut() = layout;
            });
        }

        self.dialogs(ui.ctx(), &rs);
        self.command_palette(ui.ctx(), &rs);
        if self.ui.cheatsheet {
            self.cheatsheet(ui.ctx());
        }
        self.tour_update();
        if let Some(v) = self.anchors.get("viewport").copied() {
            self.tour_ui(ui.ctx(), v);
        }
        self.drop_overlay(ui.ctx());
        let screen = ui.ctx().content_rect();
        let anchor = Rect::from_min_max(screen.min, pos2(screen.right(), screen.bottom() - size::CONTROL_H - space::LG));
        self.ui.toasts.show(ui.ctx(), anchor);

        // Record finished edits (not mid-drag, so a slider drag is one undo step).
        let busy = ui.input(|i| i.pointer.any_down()) || self.stroke.is_some();
        if !busy {
            self.commit_doc_changes();
        }
        self.remember_window(ui.ctx());
        ui.ctx().request_repaint();
    }

    fn on_exit(&mut self) {
        self.ui.prefs.save().ok();
        if !self.modified {
            self.discard_recovery();
        }
    }
}

impl PigmentApp {
    /// A cached directory listing (`list` runs at most every 3 s per key).
    pub(super) fn cached_list(&mut self, key: &str, list: impl FnOnce() -> Vec<PathBuf>) -> Vec<PathBuf> {
        match self.ui.fs_cache.get(key) {
            Some((t, v)) if t.elapsed().as_secs_f32() < 3.0 => v.clone(),
            _ => {
                let v = list();
                self.ui.fs_cache.insert(key.to_string(), (Instant::now(), v.clone()));
                v
            }
        }
    }

    fn prefs_changed(&mut self) {
        self.ui.prefs_dirty_at.get_or_insert(Instant::now());
    }

    fn remember_window(&mut self, ctx: &egui::Context) {
        let z = ctx.zoom_factor();
        if (z - self.ui.prefs.ui_scale).abs() > 1e-3 {
            self.ui.prefs.ui_scale = z;
            self.prefs_changed();
        }
        if let Some(r) = ctx.input(|i| i.viewport().inner_rect) {
            let s = [r.width() * z, r.height() * z];
            if self.ui.prefs.window.is_none_or(|w| (w[0] - s[0]).abs() > 1.0 || (w[1] - s[1]).abs() > 1.0) {
                self.ui.prefs.window = Some(s);
                self.prefs_changed();
            }
        }
        if self.ui.prefs_dirty_at.is_some_and(|t| t.elapsed().as_secs_f32() > 2.0) {
            self.ui.prefs_dirty_at = None;
            if let Err(e) = self.ui.prefs.save() {
                log::warn!("couldn't save preferences: {e}");
            }
        }
    }

    fn load_env(&mut self, rs: &RenderState, p: &Path) {
        match Environment::load(&rs.device, &rs.queue, p) {
            Ok(e) => {
                self.set_status(format!("Lighting: {}", e.name), false);
                self.env = e;
            }
            Err(e) => self.notify_error("Couldn't load that HDRI", &format!("{e:#}")),
        }
    }

    pub(super) fn notify_error(&mut self, what: &str, e: &str) {
        let msg = jobs::friendly_error(what, e);
        self.ui.toasts.push(ToastKind::Error, what, msg.trim_start_matches(what).trim_start_matches(": ").to_string());
        self.set_status(msg, true);
    }

    /// Open a dropped / chosen file: a model, a project, an HDRI or a smart material.
    pub(super) fn open_path(&mut self, rs: &RenderState, p: &Path) {
        let ext = p.extension().map(|e| e.to_string_lossy().to_ascii_lowercase()).unwrap_or_default();
        match ext.as_str() {
            "hdr" | "exr" => self.load_env(rs, p),
            "pigsmart" => match self.apply_smart(p, &[], None) {
                Ok(id) => {
                    self.select(Some(id), false);
                    self.ui.toasts.push(ToastKind::Success, "Smart material applied", p.display().to_string());
                }
                Err(e) => self.notify_error("Couldn't apply the smart material", &e),
            },
            "png" | "jpg" | "jpeg" => {
                self.ui.decal.image = Some(p.to_path_buf());
                self.set_tool(Tool::Decal);
                self.ui.welcome = false;
                self.ui.toasts.push(ToastKind::Info, "Decal ready", "Click the model to stick it on. Esc stops.");
            }
            "obj" | "gltf" | "glb" | "pigment" | "json" | "" => self.request(rs, Self::pending_for_path(p)),
            _ => self.notify_error("Can't open that file", &format!("{} is a .{ext} file (unsupported format)", p.display())),
        }
    }

    /// `run_pending` plus the bookkeeping a person sees: recent files, toasts.
    pub(super) fn run_pending_ui(&mut self, rs: &RenderState, p: Pending) {
        let path = match &p {
            Pending::NewFromMesh(x) | Pending::OpenProject(x) => Some(x.clone()),
            _ => None,
        };
        self.status = None;
        self.run_pending(rs, p);
        if let Some((msg, true)) = self.status.clone() {
            let (what, e) = msg.split_once(": ").unwrap_or(("Couldn't open the model", &msg));
            self.notify_error(what, e);
            return;
        }
        self.ui.welcome = false;
        self.ui.wear_bases.clear();
        self.ui.wear = 0.5;
        self.ui.locked.clear();
        if let Some(x) = path {
            self.ui.prefs.add_recent(&x);
            self.prefs_changed();
        }
        self.discard_recovery();
    }

    // ------------------------------------------------------------ tools

    pub(super) fn tool(&self) -> Tool {
        if self.part_pick {
            Tool::Pick
        } else if self.foliage.active {
            Tool::Foliage
        } else if self.decal_tool.is_some() {
            Tool::Decal
        } else if self.ui.fill_tool {
            Tool::Fill
        } else if self.brush.erase {
            Tool::Erase
        } else {
            Tool::Paint
        }
    }

    pub(super) fn set_tool(&mut self, t: Tool) {
        self.part_pick = t == Tool::Pick;
        self.ui.fill_tool = t == Tool::Fill;
        self.brush.erase = t == Tool::Erase;
        self.decal_tool = None;
        self.foliage.active = t == Tool::Foliage;
        if t == Tool::Foliage {
            self.ui.prefs.layout_mut().open(PanelId::FoliageBrush);
        }
        if t == Tool::Decal {
            if self.ui.decal.image.is_none() {
                self.ui.decal.image = super::panels::decals::decal_images().into_iter().next();
            }
            match self.ui.decal.image.clone() {
                Some(img) => self.decal_tool = Some((img, None)),
                None => {
                    self.ui.toasts.push(ToastKind::Info, "Choose a decal image", "Open the Decals panel and browse for a PNG.");
                }
            }
            self.ui.prefs.layout_mut().open(PanelId::Decals);
        }
        if t == Tool::Fill {
            self.ui.prefs.layout_mut().focus(PanelId::Library);
        }
    }

    fn tool_rail(&mut self, ui: &mut egui::Ui) {
        let simple = self.ui.prefs.mode == Mode::Simple;
        let cur = self.tool();
        ui.vertical_centered(|ui| {
            ui.spacing_mut().item_spacing.y = space::XS;
            let tools: &[(Tool, Icon, &str, &str, &str)] = &[
                (Tool::Paint, Icon::Brush, "Paint", "Paint the brush material onto the model. Left-drag.", "B"),
                (Tool::Erase, Icon::Eraser, "Erase", "Erase paint, or paint a mask black.", "E"),
                (Tool::Fill, Icon::Bucket, "Fill part", "Click a part of the model to fill it with the chosen material.", "G"),
                (Tool::Decal, Icon::Stamp, "Decal", "Stick an image (sign, label, graffiti) onto the model.", "D"),
                (Tool::Pick, Icon::Target, "Parts", "Click parts to limit the selected layer to them.", "P"),
                (Tool::Foliage, Icon::Leaf, "Foliage", "Paint moss, grass, weeds, ivy or leaves onto the model as cards. Shift erases.", "V"),
            ];
            for (t, ic, label, tip, key) in tools {
                if simple && *t == Tool::Pick {
                    continue;
                }
                let r = ds::tool_button(ui, *ic, label, tip, key, cur == *t);
                if *t == Tool::Fill {
                    self.anchors.insert("fill_tool", r.rect);
                }
                if *t == Tool::Decal {
                    self.anchors.insert("decal_tool", r.rect);
                }
                if r.clicked() {
                    self.set_tool(*t);
                }
            }
            ui.add_space(space::LG);
            ui.separator();
            if ui.add(IconBtn::new(Icon::Frame, "Frame the model (or the selected parts)").shortcut("F").size(size::TOOL)).clicked() {
                self.frame_selected();
            }
            let mv = self.view.mode == ViewMode::Material;
            if ui.add(IconBtn::new(Icon::Image, "Material / base colour view").shortcut("M").selected(!mv).size(size::TOOL)).clicked() {
                self.view.mode = if mv { ViewMode::BaseColor } else { ViewMode::Material };
            }
        });
    }

    /// Frame the selected layer's parts if it has a part mask, else the whole model.
    pub(super) fn frame_selected(&mut self) {
        let parts = self.selected.and_then(|id| self.doc.layer(id)).and_then(|l| l.mask.as_ref()).map(|m| m.parts.clone()).unwrap_or_default();
        let boxes: Vec<_> = parts.iter().filter_map(|p| self.parts.info.get(*p as usize)).collect();
        if boxes.is_empty() {
            let (c, r) = self.mesh.bounding_sphere();
            self.camera.frame(c, r);
            return;
        }
        let lo = boxes.iter().fold(glam::Vec3::splat(f32::MAX), |a, b| a.min(glam::Vec3::from(b.min)));
        let hi = boxes.iter().fold(glam::Vec3::splat(f32::MIN), |a, b| a.max(glam::Vec3::from(b.max)));
        self.camera.frame((lo + hi) * 0.5, ((hi - lo).length() * 0.5).max(0.01));
    }

    fn tool_options(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let simple = self.ui.prefs.mode == Mode::Simple;
        let p = ds::pal(ui);
        ui.horizontal(|ui| {
            ui.set_min_height(size::CONTROL_H);
            let tool = self.tool();
            let (ic, name) = match tool {
                Tool::Paint => (Icon::Brush, "Paint"),
                Tool::Erase => (Icon::Eraser, "Erase"),
                Tool::Fill => (Icon::Bucket, "Fill part"),
                Tool::Decal => (Icon::Stamp, "Decal"),
                Tool::Pick => (Icon::Target, "Pick parts"),
                Tool::Foliage => (Icon::Leaf, "Foliage"),
            };
            ic.show(ui, icon::MD, p.accent);
            ui.label(ds::strong(name, font::BODY));
            ui.separator();
            let compact = |ui: &mut egui::Ui, label: &str, v: &mut f32, r: std::ops::RangeInclusive<f32>, unit: ds::Unit, log: bool, tip: &str| {
                ui.scope(|ui| {
                    ui.set_width(205.0);
                    ds::slider_row_ex(ui, label, v, r, unit, log, Some(tip));
                });
            };
            match tool {
                Tool::Paint | Tool::Erase => {
                    compact(ui, "Size", &mut self.brush.size, 2.0..=800.0, ds::Unit::Suffix(" px", 0), true, "Brush diameter on screen. [ and ] change it.");
                    compact(ui, "Strength", &mut self.brush.opacity, 0.0..=1.0, ds::Unit::Percent, false, "How much each stroke covers.");
                    if !simple {
                        compact(ui, "Hardness", &mut self.brush.hardness, 0.0..=1.0, ds::Unit::Percent, false, "Soft edge (0) to crisp edge (100%).");
                        compact(ui, "Spacing", &mut self.brush.spacing, 0.02..=1.0, ds::Unit::Percent, false, "Distance between dabs, as a share of the size.");
                    }
                }
                Tool::Fill => {
                    let name = self.ui.lib_current.as_ref().map(|i| i.name()).unwrap_or_else(|| "nothing yet".into());
                    ui.label(ds::text(format!("Click a part of the model to fill it with {name}."), font::SMALL).color(p.text_secondary));
                    if self.ui.lib_current.is_none() {
                        ui.label(ds::text("Pick a material in the Materials panel first.", font::SMALL).color(p.warn));
                    }
                }
                Tool::Decal => {
                    let d = &mut self.ui.decal;
                    ds::segmented(
                        ui,
                        &mut d.mode,
                        &[(DecalMode::Stamp, Some(Icon::Stamp), "Stamp"), (DecalMode::Box, Some(Icon::Frame), "Box"), (DecalMode::Part, Some(Icon::Parts), "Fit to part"), (DecalMode::Scatter, Some(Icon::Scatter), "Scatter")],
                    );
                    if d.mode != DecalMode::Box {
                        compact(ui, "Size", &mut d.size, 0.02..=4.0, ds::Unit::Suffix(" m", 2), true, "Width of the decal in metres; height follows the image.");
                    }
                    compact(ui, "Wear", &mut d.wear, 0.0..=1.0, ds::Unit::Percent, false, "Tear the decal with noise, leaving a rim of bare paper.");
                    compact(ui, "Fade", &mut d.fade, 0.0..=1.0, ds::Unit::Percent, false, "Sun-bleach and wear it through in patches.");
                }
                Tool::Pick => {
                    ui.label(ds::text("Click parts to add them to (or remove them from) the selected layer's mask.", font::SMALL).color(p.text_secondary));
                }
                Tool::Foliage => {
                    let b = &mut self.foliage.brush;
                    compact(ui, "Radius", &mut b.radius, 0.02..=3.0, ds::Unit::Suffix(" m", 2), true, "Brush radius on the surface, metres.");
                    compact(ui, "Density", &mut b.density, 1.0..=400.0, ds::Unit::Suffix(" /m²", 0), true, "Cards per square metre.");
                    ds::toggle(ui, &mut b.erase, "Erase");
                    ui.label(ds::text(b.cells.join(", "), font::SMALL).color(p.text_secondary));
                }
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if matches!(tool, Tool::Paint | Tool::Erase | Tool::Decal) {
                    self.paint_target_chip(ui, rs);
                }
            });
        });
    }

    /// What the brush will paint on, and the mask colour swap when on a mask.
    fn paint_target_chip(&mut self, ui: &mut egui::Ui, _rs: &RenderState) {
        let p = ds::pal(ui);
        let layer = self.selected.and_then(|id| self.doc.layer(id)).map(|l| (l.name.clone(), l.is_paint(), l.mask.is_some(), l.id));
        let locked = layer.as_ref().is_some_and(|l| self.ui.locked.contains(&l.3));
        match (layer, self.paint_target()) {
            (Some((name, ..)), _) if locked => {
                ui.label(ds::text(format!("{name} is locked"), font::SMALL).color(p.warn));
                Icon::Lock.show(ui, icon::SM, p.warn);
            }
            (Some((name, ..)), Ok(Target::Mask(_))) => {
                ds::segmented(ui, &mut self.brush.mask_white, &[(false, None, "Black: hide"), (true, None, "White: reveal")]);
                ui.label(ds::text(format!("Painting the mask of {name}"), font::SMALL).color(p.accent)).rich_tip("Painting a mask", "White shows the layer, black hides it. X swaps.");
            }
            (Some((name, ..)), Ok(Target::Layer(_))) => {
                ui.label(ds::text(format!("Painting on {name}"), font::SMALL).color(p.text_secondary));
            }
            (Some((name, false, false, _)), _) => {
                ui.label(ds::text(format!("Painting {name} gives it a mask"), font::SMALL).color(p.text_muted));
            }
            (_, Err(e)) => {
                ui.label(ds::text(e, font::SMALL).color(p.warn));
            }
            _ => {}
        }
    }

    // ------------------------------------------------------------ bars

    fn top_bar(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        egui::MenuBar::new().ui(ui, |ui| {
            ui.set_min_height(size::CONTROL_H + space::XS);
            ds::logo(ui, icon::LG);
            ui.label(ds::strong("Pigment", font::TITLE));
            ui.add_space(space::SM);
            let file = ui.menu_button("File", |ui| self.file_menu(ui, rs));
            self.anchors.insert("file_menu", file.response.rect);
            ui.menu_button("Edit", |ui| {
                let ul = self.history.undo_label().map(|s| format!("Undo: {s}")).unwrap_or_else(|| "Undo".into());
                if ui.add_enabled(self.history.can_undo() || self.doc != self.committed, egui::Button::new(ul).shortcut_text("Ctrl+Z")).clicked() {
                    self.undo(rs, false);
                }
                let rl = self.history.redo_label().map(|s| format!("Redo: {s}")).unwrap_or_else(|| "Redo".into());
                if ui.add_enabled(self.history.can_redo(), egui::Button::new(rl).shortcut_text("Ctrl+Y")).clicked() {
                    self.undo(rs, true);
                }
                if ui.button("Undo history panel").clicked() {
                    self.ui.prefs.layout_mut().open(PanelId::History);
                    ui.close();
                }
                ui.separator();
                if ui.add(egui::Button::new("Command palette…").shortcut_text("Ctrl+K")).clicked() {
                    self.ui.palette.open = true;
                    ui.close();
                }
                if ui.button("Settings…").clicked() {
                    self.ui.settings = true;
                    ui.close();
                }
            });
            ui.menu_button("View", |ui| {
                if ui.add(egui::Button::new("Frame model / selection").shortcut_text("F")).clicked() {
                    self.frame_selected();
                }
                ui.separator();
                for m in ViewMode::ALL {
                    ui.radio_value(&mut self.view.mode, m, m.label());
                }
            });
            ui.menu_button("Window", |ui| self.window_menu(ui));
            ui.menu_button("Help", |ui| {
                if ui.button("Learn in 2 minutes (guided tour)").clicked() {
                    self.start_tour(rs);
                    ui.close();
                }
                if ui.add(egui::Button::new("Keyboard shortcuts").shortcut_text("?")).clicked() {
                    self.ui.cheatsheet = true;
                    ui.close();
                }
                if ui.button("Welcome screen").clicked() {
                    self.ui.welcome = true;
                    ui.close();
                }
                if ui.button("Design gallery (restart with --design-gallery)").clicked() {
                    self.ui.toasts.push(ToastKind::Info, "Design gallery", "Run `pigment --design-gallery` to see every component.");
                    ui.close();
                }
            });
            ui.add_space(space::LG);
            let mut mode = self.ui.prefs.mode;
            let seg = ui.scope(|ui| ds::segmented(ui, &mut mode, &[(Mode::Simple, Some(Icon::Sparkle), "Simple"), (Mode::Advanced, Some(Icon::Sliders), "Advanced")]));
            self.anchors.insert("mode_toggle", seg.response.rect);
            if seg.inner {
                self.set_mode(mode);
            }
            let name = self.project_dir.as_ref().and_then(|d| d.file_stem()).map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| self.export_name.clone());
            ui.add_space(space::LG);
            ui.label(ds::text(name, font::SMALL).color(p.text_secondary));
            if self.modified {
                ds::badge(ui, "unsaved", p.warn).on_hover_text("Ctrl+S saves. Pigment also keeps a recovery copy every few minutes.");
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let exp = ui.add(Btn::primary("Export").icon(Icon::Export).shortcut("Ctrl+E"));
                self.anchors.insert("export_button", exp.rect);
                if exp.clicked() {
                    self.show_export = true;
                }
                if ui.add(Btn::secondary("Send to Blender").icon(Icon::Send)).rich_tip("Send to Blender", "Exports the maps, the mesh and a material.json the Pigment Bridge add-on links into a Blender material.").clicked() {
                    self.send_to_blender(rs);
                }
                ui.add_space(space::SM);
                if ui.add(IconBtn::new(Icon::Help, "Keyboard shortcuts").shortcut("?")).clicked() {
                    self.ui.cheatsheet = !self.ui.cheatsheet;
                }
                if ui.add(IconBtn::new(Icon::Command, "Command palette: find any action").shortcut("Ctrl+K")).clicked() {
                    self.ui.palette.open = true;
                }
                let redo = ui.add(IconBtn::new(Icon::Redo, self.history.redo_label().map(|l| format!("Redo: {l}")).unwrap_or("Redo".into())).shortcut("Ctrl+Y").enabled(self.history.can_redo()));
                if redo.clicked() {
                    self.undo(rs, true);
                }
                let undo = ui.add(IconBtn::new(Icon::Undo, self.history.undo_label().map(|l| format!("Undo: {l}")).unwrap_or("Undo".into())).shortcut("Ctrl+Z").enabled(self.history.can_undo() || self.doc != self.committed));
                self.anchors.insert("edit_menu", undo.rect.union(redo.rect));
                if undo.clicked() {
                    self.undo(rs, false);
                }
            });
        });
    }

    fn file_menu(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        if ui.add(egui::Button::new("New project…").shortcut_text("Ctrl+N")).clicked() {
            self.ui.new_project.open = true;
            ui.close();
        }
        if ui.add(egui::Button::new("Open model…").shortcut_text("Ctrl+Shift+O")).clicked() {
            self.open_model_dialog(rs);
            ui.close();
        }
        if ui.add(egui::Button::new("Open project…").shortcut_text("Ctrl+O")).clicked() {
            self.open_dialog(rs);
            ui.close();
        }
        ui.menu_button("Open recent", |ui| {
            let recent = self.ui.prefs.recent.clone();
            if recent.is_empty() {
                ui.label("Nothing yet");
            }
            for r in recent {
                if ui.button(r.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()).on_hover_text(r.display().to_string()).clicked() {
                    self.request(rs, Self::pending_for_path(&r));
                    ui.close();
                }
            }
        });
        ui.separator();
        if ui.add(egui::Button::new("Save").shortcut_text("Ctrl+S")).clicked() {
            self.save(rs, false);
            ui.close();
        }
        if ui.add(egui::Button::new("Save as…").shortcut_text("Ctrl+Shift+S")).clicked() {
            self.save(rs, true);
            ui.close();
        }
        ui.separator();
        if ui.add(egui::Button::new("Export textures…").shortcut_text("Ctrl+E")).clicked() {
            self.show_export = true;
            ui.close();
        }
        if ui.button("Send to Blender").clicked() {
            self.send_to_blender(rs);
            ui.close();
        }
        ui.separator();
        if ui.button("Welcome screen").clicked() {
            self.ui.welcome = true;
            ui.close();
        }
    }

    fn window_menu(&mut self, ui: &mut egui::Ui) {
        ui.label(ds::caption(ui, "Panels"));
        for id in PanelId::ALL {
            let open = self.ui.prefs.layout().contains(id);
            if ui.add_enabled(id.closable() || !open, egui::Button::selectable(open, id.title())).clicked() {
                let l = self.ui.prefs.layout_mut();
                if open {
                    l.remove(id);
                } else {
                    l.open(id);
                }
                self.prefs_changed();
            }
        }
        ui.separator();
        ui.label(ds::caption(ui, "Layouts"));
        for name in dock::PRESETS {
            if ui.button(name).clicked() {
                *self.ui.prefs.layout_mut() = DockLayout::preset(name).unwrap();
                self.prefs_changed();
                ui.close();
            }
        }
        let custom = self.ui.prefs.custom_layouts.clone();
        if !custom.is_empty() {
            ui.separator();
            for (name, l) in custom {
                ui.horizontal(|ui| {
                    if ui.button(&name).clicked() {
                        *self.ui.prefs.layout_mut() = l.clone();
                        self.prefs_changed();
                        ui.close();
                    }
                    if ui.add(IconBtn::new(Icon::Trash, "Delete this layout").size(size::CONTROL_H_SM)).clicked() {
                        self.ui.prefs.custom_layouts.retain(|(n, _)| *n != name);
                        self.prefs_changed();
                    }
                });
            }
        }
        ui.separator();
        if ui.button("Save current layout as…").clicked() {
            self.ui.save_layout = Some(format!("My layout {}", self.ui.prefs.custom_layouts.len() + 1));
            ui.close();
        }
        if ui.button("Reset layout").clicked() {
            *self.ui.prefs.layout_mut() = match self.ui.prefs.mode {
                Mode::Simple => DockLayout::beginner(),
                Mode::Advanced => DockLayout::texturing(),
            };
            self.prefs_changed();
            ui.close();
        }
    }

    pub(super) fn set_mode(&mut self, m: Mode) {
        if self.ui.prefs.mode == m {
            return;
        }
        self.ui.prefs.mode = m;
        if m == Mode::Simple && self.part_pick {
            self.set_tool(Tool::Paint);
        }
        self.prefs_changed();
        let msg = match m {
            Mode::Simple => "Simple mode: pick a material, set how worn, export.",
            Mode::Advanced => "Advanced mode: the full layer stack, masks, generators and channels.",
        };
        self.set_status(msg, false);
    }

    fn status_bar(&mut self, ui: &mut egui::Ui) {
        let p = ds::pal(ui);
        ui.horizontal(|ui| {
            if let Some(j) = self.ui.jobs.iter().find(|j| j.toast != 0) {
                let title = self.ui.toasts.list.iter().find(|t| t.id == j.toast).map(|t| t.title.clone()).unwrap_or_default();
                ds::progress(ui, None, &title);
                ui.separator();
            }
            if let Some((msg, err)) = &self.status {
                let (ic, c) = if *err { (Icon::Warning, p.warn) } else { (Icon::Info, p.text_muted) };
                ic.show(ui, icon::SM, c);
                ui.add(egui::Label::new(ds::text(msg, font::SMALL).color(if *err { p.warn } else { p.text_secondary })).truncate());
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(ds::mono(format!("{0}×{0}", self.ts.res)).color(p.text_muted)).on_hover_text("Texture size (change it in Texture set & bake)");
                if self.ui.prefs.mode == Mode::Advanced {
                    let avg = self.frame_times.iter().sum::<f32>() / self.frame_times.len().max(1) as f32;
                    let stats = format!("{:.0} fps · {} tris · {} layers · {:.0} MB", 1.0 / avg.max(1e-6), format_count(self.mesh.triangle_count()), self.doc.layers.len(), self.ts.vram_bytes() as f64 / 1048576.0);
                    ui.label(ds::mono(stats).color(p.text_muted));
                }
            });
        });
    }

    // ------------------------------------------------------------ shortcuts & commands

    fn shortcuts(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        use egui::{Key, KeyboardShortcut as K, Modifiers as M};
        let c = |i: &mut egui::InputState, m: M, k: Key| i.consume_shortcut(&K::new(m, k));
        let (redo2, redo, undo, save_as, save, open_model, open, export, export2, palette, newp, tab) = ui.input_mut(|i| {
            (
                c(i, M::COMMAND | M::SHIFT, Key::Z),
                c(i, M::COMMAND, Key::Y),
                c(i, M::COMMAND, Key::Z),
                c(i, M::COMMAND | M::SHIFT, Key::S),
                c(i, M::COMMAND, Key::S),
                c(i, M::COMMAND | M::SHIFT, Key::O),
                c(i, M::COMMAND, Key::O),
                c(i, M::COMMAND, Key::E),
                c(i, M::COMMAND | M::SHIFT, Key::E),
                c(i, M::COMMAND, Key::K),
                c(i, M::COMMAND, Key::N),
                c(i, M::COMMAND, Key::Tab),
            )
        });
        if redo || redo2 {
            self.undo(rs, true);
        } else if undo {
            self.undo(rs, false);
        }
        if save_as {
            self.save(rs, true);
        } else if save {
            self.save(rs, false);
        }
        if open_model {
            self.open_model_dialog(rs);
        } else if open {
            self.open_dialog(rs);
        }
        if export || export2 {
            self.show_export = true;
        }
        if palette {
            self.ui.palette.open = !self.ui.palette.open;
        }
        if newp {
            self.ui.new_project.open = true;
        }
        if tab {
            let m = if self.ui.prefs.mode == Mode::Simple { Mode::Advanced } else { Mode::Simple };
            self.set_mode(m);
        }
        if ui.ctx().egui_wants_keyboard_input() || self.ui.palette.open {
            return;
        }
        let keys = ui.input(|i| {
            let k = |key| i.key_pressed(key) && !i.modifiers.command;
            [
                k(Key::OpenBracket),
                k(Key::CloseBracket),
                k(Key::B),
                k(Key::E),
                k(Key::X),
                k(Key::M),
                k(Key::F),
                i.key_pressed(Key::Escape),
                i.key_pressed(Key::F12),
                k(Key::G),
                k(Key::D),
                k(Key::P),
                i.key_pressed(Key::Questionmark) || (i.key_pressed(Key::Slash) && i.modifiers.shift) || i.key_pressed(Key::F1),
            ]
        });
        let [smaller, bigger, b, e, x, m, f, esc, f12, g, d, pk, help] = keys;
        if smaller {
            self.brush.size = (self.brush.size / 1.15).max(2.0);
        }
        if bigger {
            self.brush.size = (self.brush.size * 1.15).min(800.0);
        }
        if b {
            self.set_tool(Tool::Paint);
        }
        if e {
            self.set_tool(if self.tool() == Tool::Erase { Tool::Paint } else { Tool::Erase });
        }
        if g {
            self.set_tool(Tool::Fill);
        }
        if d {
            self.set_tool(Tool::Decal);
        }
        if pk && self.ui.prefs.mode == Mode::Advanced {
            self.set_tool(Tool::Pick);
        }
        if ui.input(|i| i.key_pressed(Key::V) && !i.modifiers.command) {
            self.set_tool(Tool::Foliage);
        }
        if x {
            self.brush.mask_white = !self.brush.mask_white;
        }
        if m {
            self.view.mode = if self.view.mode == ViewMode::Material { ViewMode::BaseColor } else { ViewMode::Material };
        }
        if f {
            self.frame_selected();
        }
        if help {
            self.ui.cheatsheet = !self.ui.cheatsheet;
        }
        if esc {
            if self.ui.cheatsheet {
                self.ui.cheatsheet = false;
            } else if self.tool() != Tool::Paint {
                self.set_tool(Tool::Paint);
            }
        }
        if f12 {
            self.dump_requested = true;
        }
    }

    fn open_dialog(&mut self, rs: &RenderState) {
        if let Some(p) = rfd::FileDialog::new().set_title("Open project folder (.pigment)").pick_folder() {
            self.request(rs, Pending::OpenProject(p));
        }
    }

    pub(super) fn open_model_dialog(&mut self, rs: &RenderState) {
        if let Some(p) = rfd::FileDialog::new().set_title("Open a model to paint").add_filter("3D models", &["obj", "gltf", "glb"]).pick_file() {
            self.request(rs, Pending::NewFromMesh(p));
        }
    }

    /// Every action, for the command palette.
    fn commands(&self) -> Vec<ds::Command> {
        let cmd = |id: &str, title: &str, group: &'static str, shortcut: Option<&'static str>, icon: Icon| ds::Command { id: id.into(), title: title.into(), group, shortcut, icon };
        let mut v = vec![
            cmd("new", "New project…", "File", Some("Ctrl+N"), Icon::New),
            cmd("open_model", "Open model…", "File", Some("Ctrl+Shift+O"), Icon::Open),
            cmd("open", "Open project…", "File", Some("Ctrl+O"), Icon::Open),
            cmd("save", "Save", "File", Some("Ctrl+S"), Icon::Save),
            cmd("save_as", "Save as…", "File", Some("Ctrl+Shift+S"), Icon::Save),
            cmd("export", "Export textures…", "File", Some("Ctrl+E"), Icon::Export),
            cmd("blender", "Send to Blender", "File", None, Icon::Send),
            cmd("welcome", "Welcome screen", "File", None, Icon::Sparkle),
            cmd("torus", "New project: test torus", "File", None, Icon::Cube),
            cmd("undo", "Undo", "Edit", Some("Ctrl+Z"), Icon::Undo),
            cmd("redo", "Redo", "Edit", Some("Ctrl+Y"), Icon::Redo),
            cmd("simple", "Switch to Simple mode", "Mode", Some("Ctrl+Tab"), Icon::Sparkle),
            cmd("advanced", "Switch to Advanced mode", "Mode", Some("Ctrl+Tab"), Icon::Sliders),
            cmd("theme", "Toggle light / dark theme", "View", None, Icon::Sun),
            cmd("frame", "Frame model / selection", "View", Some("F"), Icon::Frame),
            cmd("tool_paint", "Paint tool", "Tools", Some("B"), Icon::Brush),
            cmd("tool_erase", "Eraser", "Tools", Some("E"), Icon::Eraser),
            cmd("tool_fill", "Fill a part", "Tools", Some("G"), Icon::Bucket),
            cmd("tool_decal", "Decal tool", "Tools", Some("D"), Icon::Stamp),
            cmd("tool_foliage", "Foliage brush", "Tools", Some("V"), Icon::Leaf),
            cmd("tool_pick", "Pick parts", "Tools", Some("P"), Icon::Target),
            cmd("add_paint", "Add paint layer", "Layers", None, Icon::PaintLayer),
            cmd("add_fill", "Add fill layer", "Layers", None, Icon::FillLayer),
            cmd("add_folder", "Add folder", "Layers", None, Icon::Folder),
            cmd("rebake", "Re-bake AO + curvature", "Texture set", None, Icon::Tile),
            cmd("shortcuts", "Keyboard shortcuts", "Help", Some("?"), Icon::Keyboard),
            cmd("tour", "Learn in 2 minutes (guided tour)", "Help", None, Icon::Play),
            cmd("reset_layout", "Reset layout", "Window", None, Icon::Window),
            cmd("settings", "Settings…", "Edit", None, Icon::Gear),
        ];
        for l in dock::PRESETS {
            v.push(ds::Command { id: format!("layout:{l}"), title: format!("Layout: {l}"), group: "Window", shortcut: None, icon: Icon::Window });
        }
        for p in PanelId::ALL {
            v.push(ds::Command { id: format!("panel:{p:?}"), title: format!("Show {} panel", p.title()), group: "Window", shortcut: None, icon: p.icon() });
        }
        for n in smart_material_names() {
            v.push(ds::Command { id: format!("smart:{n}"), title: format!("Apply {n}"), group: "Materials", shortcut: None, icon: Icon::Sparkle });
        }
        for (id, label) in pigment_core::envmath::PRESETS.iter().chain(pigment_core::envmath::SKIES.iter()) {
            v.push(ds::Command { id: format!("light:{id}"), title: format!("Lighting: {label}"), group: "Lighting", shortcut: None, icon: Icon::Sun });
        }
        v
    }

    pub(super) fn run_command(&mut self, rs: &RenderState, id: &str) {
        match id {
            "new" => self.ui.new_project.open = true,
            "open_model" => self.open_model_dialog(rs),
            "open" => self.open_dialog(rs),
            "save" => self.save(rs, false),
            "save_as" => self.save(rs, true),
            "export" => self.show_export = true,
            "blender" => self.send_to_blender(rs),
            "welcome" => self.ui.welcome = true,
            "torus" => self.request(rs, Pending::NewTorus),
            "undo" => self.undo(rs, false),
            "redo" => self.undo(rs, true),
            "simple" => self.set_mode(Mode::Simple),
            "advanced" => self.set_mode(Mode::Advanced),
            "theme" => {
                self.ui.prefs.theme = if self.ui.prefs.theme == ds::ThemeKind::Dark { ds::ThemeKind::Light } else { ds::ThemeKind::Dark };
                self.ui.pending_theme = true;
                self.prefs_changed();
            }
            "frame" => self.frame_selected(),
            "tool_paint" => self.set_tool(Tool::Paint),
            "tool_erase" => self.set_tool(Tool::Erase),
            "tool_fill" => self.set_tool(Tool::Fill),
            "tool_decal" => self.set_tool(Tool::Decal),
            "tool_foliage" => self.set_tool(Tool::Foliage),
            "tool_pick" => {
                self.set_mode(Mode::Advanced);
                self.set_tool(Tool::Pick);
            }
            "add_paint" => {
                let l = self.doc.new_paint_layer(&format!("Paint {}", self.doc.layers.len() + 1));
                self.insert_layer(l);
            }
            "add_fill" => {
                let l = self.doc.new_fill_layer(&format!("Fill {}", self.doc.layers.len() + 1));
                self.insert_layer(l);
            }
            "add_folder" => self.add_folder(),
            "rebake" => self.bake(rs),
            "shortcuts" => self.ui.cheatsheet = true,
            "tour" => self.start_tour(rs),
            "settings" => self.ui.settings = true,
            "reset_layout" => {
                *self.ui.prefs.layout_mut() = if self.ui.prefs.mode == Mode::Simple { DockLayout::beginner() } else { DockLayout::texturing() };
                self.prefs_changed();
            }
            other => {
                if let Some(l) = other.strip_prefix("layout:").and_then(DockLayout::preset) {
                    *self.ui.prefs.layout_mut() = l;
                    self.prefs_changed();
                } else if let Some(p) = other.strip_prefix("panel:").and_then(|n| PanelId::ALL.into_iter().find(|p| format!("{p:?}") == n)) {
                    self.ui.prefs.layout_mut().open(p);
                    self.prefs_changed();
                } else if let Some(n) = other.strip_prefix("smart:") {
                    self.apply_library(rs, &LibItem::Smart(n.to_string()), None);
                } else if let Some(l) = other.strip_prefix("light:") {
                    self.set_lighting(rs, l);
                }
            }
        }
    }

    fn command_palette(&mut self, ctx: &egui::Context, rs: &RenderState) {
        if std::mem::take(&mut self.ui.pending_theme) {
            ds::apply(ctx, self.ui.prefs.theme);
        }
        if !self.ui.palette.open {
            return;
        }
        let cmds = self.commands();
        if let Some(id) = ds::command_palette(ctx, &mut self.ui.palette, &cmds) {
            self.run_command(rs, &id);
        }
    }

    pub(super) fn set_lighting(&mut self, rs: &RenderState, id: &str) {
        if self.env.source == id {
            return;
        }
        match Environment::lighting(&rs.device, &rs.queue, id) {
            Ok(e) => self.env = e,
            Err(e) => self.notify_error("Couldn't load that lighting", &format!("{e:#}")),
        }
    }

    fn cheatsheet(&mut self, ctx: &egui::Context) {
        let groups: [(&str, &[(&str, &str)]); 4] = [
            ("Viewport", &[("Right-drag / Alt+left-drag", "Orbit"), ("Middle-drag", "Pan"), ("Wheel", "Zoom (towards the cursor)"), ("F", "Frame model or selected parts"), ("M", "Material / base colour view")]),
            ("Tools", &[("B", "Paint"), ("E", "Eraser"), ("G", "Fill a part"), ("D", "Decal"), ("P", "Pick parts (Advanced)"), ("[  ]", "Brush size"), ("X", "Swap mask black / white"), ("Esc", "Back to the brush")]),
            ("Project", &[("Ctrl+N", "New project"), ("Ctrl+O", "Open project"), ("Ctrl+Shift+O", "Open model"), ("Ctrl+S", "Save"), ("Ctrl+E", "Export"), ("Ctrl+Z / Ctrl+Y", "Undo / redo")]),
            ("Interface", &[("Ctrl+K", "Command palette"), ("Ctrl+Tab", "Simple / Advanced"), ("?", "This sheet"), ("Ctrl + / Ctrl -", "Interface size")]),
        ];
        let (_, dismissed) = ds::modal(ctx, "cheatsheet", "Keyboard shortcuts", 680.0, |ui| {
            ui.columns(2, |cols| {
                for (k, (title, rows)) in groups.iter().enumerate() {
                    let ui = &mut cols[k % 2];
                    ds::section(ui, title);
                    for (keys, what) in rows.iter() {
                        ui.horizontal(|ui| {
                            ui.scope(|ui| {
                                ui.set_width(150.0);
                                ds::kbd(ui, keys);
                            });
                            ui.label(ds::text(*what, font::SMALL));
                        });
                    }
                }
            });
            ui.add_space(space::MD);
            if ui.add(Btn::secondary("Close")).clicked() {
                self.ui.cheatsheet = false;
            }
        });
        if dismissed {
            self.ui.cheatsheet = false;
        }
    }

    /// Big drop target while files are dragged over the window.
    fn drop_overlay(&mut self, ctx: &egui::Context) {
        let hovering = ctx.input(|i| !i.raw.hovered_files.is_empty());
        if !hovering {
            return;
        }
        let p = ds::theme(ctx).p;
        let screen = ctx.content_rect();
        let painter = ctx.layer_painter(egui::LayerId::new(egui::Order::Foreground, egui::Id::NULL.with("drop overlay")));
        painter.rect_filled(screen, egui::CornerRadius::ZERO, p.scrim);
        let r = screen.shrink(space::XXXL * 2.0);
        painter.rect(r, egui::CornerRadius::same(ds::radius::XL), p.accent.gamma_multiply(0.12), Stroke::new(2.0, p.accent), egui::StrokeKind::Inside);
        Icon::Open.paint(&painter, Rect::from_center_size(r.center() - vec2(0.0, 40.0), vec2(icon::XL, icon::XL)), p.accent);
        painter.text(r.center() + vec2(0.0, 10.0), Align2::CENTER_CENTER, "Drop to open", ds::fonts::semibold(font::DISPLAY), p.text);
        painter.text(r.center() + vec2(0.0, 44.0), Align2::CENTER_CENTER, "Models (OBJ, glTF, GLB), .pigment projects, HDRIs, smart materials or a PNG to use as a decal", ds::fonts::regular(font::BODY), p.text_secondary);
    }

    // ------------------------------------------------------------ viewport

    pub(super) fn viewport_ui(&mut self, ui: &mut egui::Ui, rs: &RenderState) {
        let rect = ui.available_rect_before_wrap();
        let response = ui.allocate_rect(rect, egui::Sense::click_and_drag());
        self.anchors.insert("viewport", rect);
        self.ui.viewport_rect = rect;
        let ppp = self.ppp;
        let viewport_px = Vec2::new((rect.width() * ppp).round(), (rect.height() * ppp).round());
        let to_px = |p: egui::Pos2| Vec2::new((p.x - rect.min.x) * ppp, (p.y - rect.min.y) * ppp);

        let (alt, delta, scroll, pinch, pressed, down, released, latest) = ui.input(|i| {
            (i.modifiers.alt, i.pointer.delta(), i.smooth_scroll_delta(), i.zoom_delta(), i.pointer.primary_pressed(), i.pointer.primary_down(), i.pointer.primary_released(), i.pointer.latest_pos())
        });
        self.hover = response.hover_pos();
        let d = Vec2::new(delta.x, delta.y);
        let tool = self.tool();
        let click = pressed && response.hovered() && !alt;
        let locked = self.selected.is_some_and(|id| self.ui.locked.contains(&id));

        match tool {
            Tool::Pick if click => {
                if let Some(p) = latest {
                    match self.part_at(to_px(p), viewport_px) {
                        Some(part) => match self.toggle_part(rs, part) {
                            Ok(msg) => self.set_status(msg, false),
                            Err(e) => self.set_status(e, true),
                        },
                        None => self.set_status("Nothing under the cursor", false),
                    }
                }
            }
            Tool::Fill if click => {
                if let Some(p) = latest {
                    match (self.part_at(to_px(p), viewport_px), self.ui.lib_current.clone()) {
                        (Some(part), Some(item)) => self.apply_library(rs, &item, Some(part)),
                        (Some(_), None) => {
                            self.ui.toasts.push(ToastKind::Info, "Choose a material first", "Click a material in the Materials panel, then click a part.");
                            self.ui.prefs.layout_mut().open(PanelId::Library);
                        }
                        (None, _) => self.set_status("Click on the model to fill one of its parts", false),
                    }
                }
            }
            Tool::Decal => self.decal_input(ui, rs, &response, rect, viewport_px, click, released),
            Tool::Foliage => {
                let hit = self.hover.and_then(|h| self.surface_at(to_px(h), viewport_px)).map(|h| (h.0, h.1));
                let shift = ui.input(|i| i.modifiers.shift);
                self.foliage_input(hit, down && !alt && response.hovered() || (down && self.foliage.last_dab.is_some()), shift);
            }
            _ => {}
        }

        // painting (brush tools first: stencil transform, clone source, path, line)
        let paints = matches!(tool, Tool::Paint | Tool::Erase);
        self.read_pen(ui);
        // decal layers: the viewport edits their decal objects instead of painting
        let gizmo = paints && self.stroke.is_none() && self.decal_gizmo_input(ui, &response, rect, viewport_px, latest, click, alt);
        let consumed = gizmo || (paints && self.stroke.is_none() && self.brush_tool_input(ui, rs, &response, rect, viewport_px, latest, click, alt));
        if paints {
            self.brush_overlay(ui, rect);
            self.decal_overlay(ui, rect);
        }
        if paints && click && !consumed && self.stroke.is_none() {
            if locked {
                self.ui.toasts.push(ToastKind::Warn, "This layer is locked", "Unlock it in the Layers panel to paint on it.");
            } else if let Some(p) = latest {
                self.begin_stroke(rs, to_px(p), viewport_px);
            }
        } else if (down || released) && self.stroke.is_some() {
            if let Some(p) = latest {
                self.stroke_to(rs, to_px(p), self.brush.pressure);
            }
        }
        if (released || !down) && self.stroke.is_some() {
            self.end_stroke(rs);
        }

        // camera: Alt+LMB / RMB orbit, MMB pan, wheel zooms towards the cursor
        if alt && response.dragged_by(egui::PointerButton::Primary) {
            self.camera.orbit(d);
        }
        if response.dragged_by(egui::PointerButton::Middle) {
            self.camera.pan(d * ppp, viewport_px.y);
        }
        if response.dragged_by(egui::PointerButton::Secondary) {
            if alt {
                self.camera.zoom((d.x - d.y) * 0.02);
            } else {
                self.camera.orbit(d);
            }
        }
        // (Ctrl+wheel scales the selected decal on a decal layer instead)
        if response.hovered() && !(gizmo && self.decal_sel.is_some() && pinch != 1.0) {
            let steps = if scroll.y != 0.0 { scroll.y / 50.0 } else if pinch != 1.0 { pinch.ln() / 0.105 } else { 0.0 };
            if steps != 0.0 {
                self.zoom_towards(steps, self.hover.map(to_px), viewport_px);
            }
        }

        // foliage wind preview: animate while any visible foliage sways
        if self.doc.layers.iter().any(|l| l.visible && l.foliage().is_some_and(|f| f.wind > 0.0 && !f.instances.is_empty())) {
            let t0 = *self.foliage.t0.get_or_insert_with(Instant::now);
            self.viewport.foliage.time = t0.elapsed().as_secs_f32();
            ui.ctx().request_repaint();
        }
        self.ensure_composited(rs);
        let size = [viewport_px.x as u32, viewport_px.y as u32];
        // every texture set (the active one first)
        self.composite_parked(rs);
        let mut sets = vec![(self.mesh_gpu.as_ref(), &self.ts)];
        if let Some(m) = &self.multi {
            sets.extend(m.parked.iter().map(|s| (s.mesh_gpu.as_ref(), &s.ts)));
        }
        if let Some(tex) = self.viewport.render_sets(rs, size, &self.camera, &self.view, &sets, &self.env) {
            let uv = Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0));
            ui.painter().image(tex, rect, uv, ds::IMAGE_TINT);
        }
        self.cursor_overlay(ui, rect, alt, tool);
        self.viewport_overlays(ui, rect, rs);
    }

    /// Zoom, keeping the point under the cursor roughly where it is.
    fn zoom_towards(&mut self, steps: f32, cursor: Option<Vec2>, viewport_px: Vec2) {
        let before = self.camera.distance;
        self.camera.zoom(steps);
        let Some(c) = cursor else { return };
        let moved = before - self.camera.distance;
        if moved.abs() < 1e-6 {
            return;
        }
        let ndc = Vec2::new(c.x / viewport_px.x * 2.0 - 1.0, 1.0 - c.y / viewport_px.y * 2.0);
        let (right, up) = self.camera.basis();
        let aspect = viewport_px.x / viewport_px.y.max(1.0);
        let t = (self.camera.fov_y * 0.5).tan();
        let shift = right * (ndc.x * t * aspect) + up * (ndc.y * t);
        self.camera.target += shift * moved;
    }

    fn cursor_overlay(&mut self, ui: &mut egui::Ui, rect: Rect, alt: bool, tool: Tool) {
        let Some(h) = self.hover.filter(|_| !alt) else { return };
        let p = ds::pal(ui);
        let painter = ui.painter().with_clip_rect(rect);
        match tool {
            Tool::Paint | Tool::Erase => {
                let r = self.brush.size * 0.5;
                let on_mask = matches!(self.paint_target(), Ok(Target::Mask(_))) || self.selected.and_then(|id| self.doc.layer(id)).is_some_and(|l| !l.is_paint());
                let col = if self.brush.erase { p.info } else { p.text };
                painter.circle_stroke(h, r + 1.0, Stroke::new(1.0, p.shadow));
                painter.circle_stroke(h, r, Stroke::new(1.5, col));
                painter.circle_stroke(h, r * self.brush.hardness.max(0.02), Stroke::new(1.0, col.gamma_multiply(0.35)));
                let dot = if on_mask {
                    if self.brush.mask_white != self.brush.erase { p.text } else { p.bg }
                } else {
                    ds::srgb(self.brush.values.base_color)
                };
                let dp = h + vec2(r * 0.72, -r * 0.72);
                painter.circle_filled(dp, 5.5, dot);
                painter.circle_stroke(dp, 5.5, Stroke::new(1.0, p.border_strong));
                ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
            }
            Tool::Fill | Tool::Pick => {
                let ic = if tool == Tool::Fill { Icon::Bucket } else { Icon::Target };
                painter.circle_filled(h + vec2(14.0, 14.0), 12.0, p.glass);
                ic.paint(&painter, Rect::from_center_size(h + vec2(14.0, 14.0), vec2(icon::SM, icon::SM)), p.accent);
                ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
            }
            Tool::Decal => ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair),
            Tool::Foliage => {
                // the brush radius in metres, as a ring at the cursor's depth
                let r = match self.foliage.hover {
                    Some((pt, _)) => {
                        let (right, _) = self.camera.basis();
                        let size = rect.size();
                        let vp = self.camera.view_proj(size.x / size.y.max(1.0));
                        let a = vp.project_point3(pt);
                        let b = vp.project_point3(pt + right * self.foliage.brush.radius);
                        ((b.x - a.x) * size.x * 0.5).abs().max(4.0)
                    }
                    None => 12.0,
                };
                let col = if self.foliage.brush.erase { p.info } else { p.success };
                painter.circle_stroke(h, r + 1.0, Stroke::new(1.0, p.shadow));
                painter.circle_stroke(h, r, Stroke::new(1.5, col));
                Icon::Leaf.paint(&painter, Rect::from_center_size(h + vec2(r * 0.72, -r * 0.72), vec2(icon::SM, icon::SM)), col);
                ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
            }
        }
    }

    fn viewport_overlays(&mut self, ui: &mut egui::Ui, rect: Rect, rs: &RenderState) {
        let p = ds::pal(ui);
        let glass = ds::glass_frame(&p);
        let simple = self.ui.prefs.mode == Mode::Simple;
        // view-mode chips, top left
        let chips = Rect::from_min_size(rect.left_top() + vec2(space::MD, space::MD), vec2((rect.width() - 240.0).max(120.0), size::CONTROL_H + space::XS));
        ui.scope_builder(egui::UiBuilder::new().max_rect(chips), |ui| {
            glass.show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.spacing_mut().item_spacing.x = space::XXS;
                    let all: &[(ViewMode, &str)] = &[
                        (ViewMode::Material, "Material"),
                        (ViewMode::BaseColor, "Color"),
                        (ViewMode::Roughness, "Rough"),
                        (ViewMode::Metallic, "Metal"),
                        (ViewMode::Height, "Height"),
                        (ViewMode::Normal, "Normal"),
                        (ViewMode::Ao, "AO"),
                        (ViewMode::Curvature, "Curvature"),
                        (ViewMode::Emissive, "Glow"),
                        (ViewMode::Opacity, "Alpha"),
                        (ViewMode::Coat, "Coat"),
                        (ViewMode::UvChecker, "UVs"),
                    ];
                    for (m, short) in all.iter().take(if simple { 3 } else { all.len() }) {
                        let on = self.view.mode == *m;
                        if ui.add(Btn::ghost(*short).small().selected(on)).on_hover_text(m.label()).clicked() {
                            self.view.mode = *m;
                        }
                    }
                });
            });
        });
        // lighting, top right
        let light = Rect::from_min_size(pos2(rect.right() - 220.0, rect.top() + space::MD), vec2(212.0, size::CONTROL_H + space::XS));
        ui.scope_builder(egui::UiBuilder::new().max_rect(light).layout(egui::Layout::right_to_left(egui::Align::Min)), |ui| {
            glass.show(ui, |ui| {
                ui.menu_button(ds::text(format!("Lighting: {}", self.env.name), font::SMALL), |ui| {
                    ui.set_min_width(260.0);
                    super::panels::misc::lighting_controls(self, ui, rs);
                });
            });
        });
        // axis gizmo, bottom right
        let g = pos2(rect.right() - 44.0, rect.bottom() - 44.0);
        let painter = ui.painter().with_clip_rect(rect);
        painter.circle_filled(g, 30.0, p.glass);
        let view = self.camera.view();
        let mut axes: Vec<(glam::Vec3, egui::Color32, &str)> = vec![(glam::Vec3::X, p.danger, "X"), (glam::Vec3::Y, p.success, "Y"), (glam::Vec3::Z, p.info, "Z")];
        axes.sort_by(|a, b| view.transform_vector3(a.0).z.total_cmp(&view.transform_vector3(b.0).z));
        for (a, c, l) in axes {
            let v = view.transform_vector3(a);
            let tip = g + vec2(v.x, -v.y) * 22.0;
            painter.line_segment([g, tip], Stroke::new(2.0, c));
            painter.circle_filled(tip, 7.0, c);
            painter.text(tip, Align2::CENTER_CENTER, l, ds::fonts::semibold(font::CAPTION), p.on_accent);
        }
        // empty-state hint for the current tool, bottom left
        let hint = match self.tool() {
            Tool::Paint => "Left-drag to paint · Right-drag to orbit · Wheel to zoom · F to frame",
            Tool::Erase => "Left-drag to erase · E switches back to the brush",
            Tool::Fill => "Click a part of the model to fill it",
            Tool::Pick => "Click parts to add / remove them from the layer's mask",
            Tool::Foliage => "Left-drag to paint foliage cards · Shift-drag erases · pick cards in the Foliage library",
            Tool::Decal => match self.ui.decal.mode {
                DecalMode::Stamp => "Click the model to stick the decal there",
                DecalMode::Box => "Drag a box over the model to project the decal",
                DecalMode::Part => "Click a part to fit the decal to it",
                DecalMode::Scatter => "Press Scatter in the Decals panel",
            },
        };
        let gal = painter.layout_no_wrap(hint.to_string(), ds::fonts::regular(font::SMALL), p.text_secondary);
        let hr = Rect::from_min_size(rect.left_bottom() + vec2(space::MD, -space::MD - gal.size().y - space::MD), gal.size() + vec2(space::LG * 2.0, space::MD));
        painter.rect_filled(hr, egui::CornerRadius::same(ds::radius::PILL), p.glass);
        painter.galley(hr.min + vec2(space::LG, space::XS), gal, p.text_secondary);
    }
}
