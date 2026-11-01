//! Top-level application: owns the document, the GPU engine and the UI.
//!
//! Undo model: every UI edit mutates `doc` directly. At the end of a frame in
//! which no mouse button is held, `doc` is compared with `committed` (the
//! last recorded state); if they differ, one undo entry holding both versions
//! is pushed. That gives undo for every parameter for free and coalesces a
//! slider drag into a single step. Strokes record GPU tile snapshots instead.

use crate::render::bake::Baker;
use crate::render::env::Environment;
use crate::render::paint::{BrushGpu, DecalGpu, Painter, Snapshot, StampGpu, Target, ViewGpu};
use crate::render::texset::TexSet;
use crate::render::viewport::{ViewMode, ViewSettings, Viewport};
use crate::render::{io, MeshGpu};
use eframe::egui;
use eframe::egui_wgpu::RenderState;
use glam::Vec2;
use pigment_core::blend::{normal_from_tilt, srgb_to_linear};
use pigment_core::stroke::StrokeSampler;
use pigment_core::tiles::{ScreenBins, TileSet};
use pigment_core::undo::{Entry, UndoStack};
use pigment_core::*;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub mod automation;
mod folders_ui;
mod bridge;
mod tour;
#[cfg(test)]
mod image_fill_tests;
mod ui;

/// Things the quick-start guide watches for.
#[derive(Default)]
struct Counters {
    strokes: u32,
    mask_strokes: u32,
    undos: u32,
}

const UNDO_BUDGET_BYTES: u64 = 1536 << 20;

enum Edit {
    Doc { before: Box<Document>, after: Box<Document> },
    Stroke(Snapshot),
}

struct Brush {
    size: f32, // diameter in screen points
    opacity: f32,
    hardness: f32,
    spacing: f32, // fraction of diameter
    values: MaterialValues,
    channels: [bool; 8],
    erase: bool,
    mask_white: bool,
}

impl Default for Brush {
    fn default() -> Self {
        Self {
            size: 60.0,
            opacity: 1.0,
            hardness: 0.6,
            spacing: 0.1,
            values: material_preset("Orange paint"),
            channels: [true, true, true, false, false, false, false, false],
            erase: false,
            mask_white: true,
        }
    }
}

struct Stroke {
    sampler: StrokeSampler,
    bins: ScreenBins,
    tiles: TileSet,
    target: Target,
    view: ViewGpu,
}

#[derive(Clone)]
enum Pending {
    NewFromMesh(PathBuf),
    OpenProject(PathBuf),
    NewTorus,
    Demo,
}

pub struct PigmentApp {
    // GPU
    viewport: Viewport,
    env: Environment,
    ts: TexSet,
    painter: Painter,
    baker: Baker,
    mesh_gpu: Option<MeshGpu>,
    // document
    doc: Document,
    committed: Document,
    composited: Option<Document>,
    history: UndoStack<Edit>,
    selected: Option<LayerId>,
    paint_mask: bool,
    mesh: Mesh,
    mesh_source: Option<PathBuf>,
    project_dir: Option<PathBuf>,
    modified: bool,
    // view + tools
    camera: OrbitCamera,
    view: ViewSettings,
    brush: Brush,
    stroke: Option<Stroke>,
    hover: Option<egui::Pos2>,
    // ui state
    status: Option<(String, bool)>,
    frame_times: Vec<f32>,
    last_frame: Instant,
    show_export: bool,
    export_dir: Option<PathBuf>,
    export_name: String,
    pending: Option<Pending>,
    renaming: Option<(LayerId, String)>,
    last_stamp_ms: f32,
    ppp: f32,
    dump_requested: bool,
    /// Brightness multiplier of the last exported emissive map.
    last_emissive_scale: f32,
    /// PNG compression for export (MCP `export_textures.compression`).
    export_compression: export::Compression,
    /// Timing of the last export, ms: waiting for pending GPU work (the
    /// composite), reading the maps back, encode + write, total.
    last_export_ms: [f64; 4],
    /// Decal images loaded on the GPU, by path.
    decals: std::collections::HashMap<PathBuf, crate::render::gpu::Tex>,
    /// Decal tool: the image, and where the drag started.
    decal_tool: Option<(PathBuf, Option<egui::Pos2>)>,
    /// Mesh parts (connected surfaces) of the current mesh.
    parts: pigment_core::mesh::Parts,
    /// Clicking the model toggles parts in the selected layer's mask.
    part_pick: bool,
    tour: tour::Tour,
    counters: Counters,
    /// Screen rects of UI elements the guide can point at, rebuilt every frame.
    anchors: std::collections::HashMap<&'static str, egui::Rect>,
}

impl PigmentApp {
    pub fn new(cc: &eframe::CreationContext<'_>, startup: Option<PathBuf>) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let rs = cc.wgpu_render_state.as_ref().ok_or("Pigment needs the wgpu renderer")?;
        let info = rs.adapter.get_info();
        log::info!("GPU: {} ({:?})", info.name, info.backend);
        ui::apply_style(&cc.egui_ctx);
        Ok(Self::create(rs, startup))
    }

    /// Build the app on an existing GPU device (also used by headless tests).
    pub fn create(rs: &RenderState, startup: Option<PathBuf>) -> Self {
        let (d, q) = (&rs.device, &rs.queue);
        let doc = Document::new_default();
        let mut app = Self {
            viewport: Viewport::new(d),
            env: Environment::studio(d, q),
            ts: TexSet::new(d, q, doc.resolution),
            painter: Painter::new(d, doc.resolution),
            baker: Baker::new(d),
            mesh_gpu: None,
            committed: doc.clone(),
            selected: doc.layers.last().map(|l| l.id),
            doc,
            composited: None,
            history: UndoStack::default(),
            paint_mask: false,
            mesh: Mesh::default(),
            mesh_source: None,
            project_dir: None,
            modified: false,
            camera: OrbitCamera::default(),
            view: ViewSettings::default(),
            brush: Brush::default(),
            stroke: None,
            hover: None,
            status: None,
            frame_times: Vec::new(),
            last_frame: Instant::now(),
            show_export: false,
            export_dir: None,
            export_name: "Asset".into(),
            pending: None,
            renaming: None,
            last_stamp_ms: 0.0,
            ppp: 1.0,
            dump_requested: false,
            last_emissive_scale: 1.0,
            export_compression: Default::default(),
            last_export_ms: [0.0; 4],
            decals: Default::default(),
            decal_tool: None,
            parts: Default::default(),
            part_pick: false,
            tour: Default::default(),
            counters: Counters::default(),
            anchors: Default::default(),
        };
        app.new_project(rs, Mesh::demo_crate(96), None, Document::demo());
        app.export_name = "DemoCrate".into();
        if let Some(p) = startup {
            app.run_pending(rs, Self::pending_for_path(&p));
        }
        app.tour_start(false);
        if let Ok(dir) = std::env::var("PIGMENT_DEBUG_DUMP") {
            app.debug_dump(rs, Path::new(&dir));
        }
        app
    }

    fn pending_for_path(p: &Path) -> Pending {
        let is_project = p.is_dir() || p.file_name().is_some_and(|n| n == project::MANIFEST);
        if is_project {
            Pending::OpenProject(p.to_path_buf())
        } else {
            Pending::NewFromMesh(p.to_path_buf())
        }
    }

    /// Developer aid: write the environment and material textures as PNGs.
    fn debug_dump(&mut self, rs: &RenderState, dir: &Path) {
        self.ensure_composited(rs);
        let _ = std::fs::create_dir_all(dir);
        let (d, q) = (&rs.device, &rs.queue);
        let env = crate::render::gpu::readback(d, q, &self.env.prefiltered);
        let px: Vec<u8> = env
            .chunks_exact(2)
            .map(|c| half::f16::from_bits(u16::from_le_bytes([c[0], c[1]])).to_f32())
            .map(|v| (v / (1.0 + v) * 255.0) as u8)
            .collect();
        let _ = image::save_buffer(dir.join("env.png"), &px, self.env.prefiltered.size, self.env.prefiltered.height, image::ExtendedColorType::Rgba8);
        let m = io::read_material(d, q, &self.ts);
        let _ = image::save_buffer(dir.join("color.png"), &m.color, m.size, m.size, image::ExtendedColorType::Rgba8);
        let _ = image::save_buffer(dir.join("orm.png"), &m.orm, m.size, m.size, image::ExtendedColorType::Rgba8);
        let _ = image::save_buffer(dir.join("normal.png"), &m.normal, m.size, m.size, image::ExtendedColorType::Rgba8);
        for l in &self.doc.layers {
            if let Some(px) = l.paint_res().and_then(|r| io::read_layer(d, q, &self.ts, r)) {
                let _ = image::save_buffer(dir.join(format!("layer_{}_color.png", l.id)), &px.color, px.size, px.size, image::ExtendedColorType::Rgba8);
            }
        }
        log::info!("debug dump written to {}", dir.display());
    }

    /// The one place selection changes. Fill layers are always painted through
    /// their mask, so selecting one with a mask selects the mask too.
    pub(super) fn select(&mut self, id: Option<LayerId>, want_mask: bool) {
        self.selected = id;
        self.paint_mask = id.and_then(|id| self.doc.layer(id)).is_some_and(|l| l.mask.is_some() && (want_mask || !l.is_paint()));
    }

    fn set_status(&mut self, msg: impl Into<String>, err: bool) {
        let msg = msg.into();
        if err {
            log::error!("{msg}");
        } else {
            log::info!("{msg}");
        }
        self.status = Some((msg, err));
    }

    // ------------------------------------------------------------ projects

    fn load_mesh_gpu(&mut self, rs: &RenderState, mesh: Mesh) {
        let (c, r) = mesh.bounding_sphere();
        self.camera.frame(c, r);
        let mg = MeshGpu::new(&rs.device, &mesh);
        self.parts = mesh.parts();
        self.ts.prepare_mesh(&rs.device, &rs.queue, &mg, c, r);
        self.mesh_gpu = Some(mg);
        self.mesh = mesh;
    }

    fn reset_state(&mut self, rs: &RenderState, doc: Document) {
        let (d, q) = (&rs.device, &rs.queue);
        let _ = self.history.clear();
        self.ts = TexSet::new(d, q, doc.resolution);
        self.painter.resize(d, doc.resolution);
        self.committed = doc.clone();
        let sel = doc.layers.iter().rev().find(|l| l.is_paint()).or(doc.layers.last()).map(|l| l.id);
        self.doc = doc;
        self.composited = None;
        self.stroke = None;
        self.select(sel, false);
    }

    fn new_project(&mut self, rs: &RenderState, mesh: Mesh, source: Option<PathBuf>, mut doc: Document) {
        doc.resolution = self.doc.resolution;
        self.reset_state(rs, doc);
        self.ts.ensure_resources(&rs.device, &rs.queue, &self.doc);
        self.load_mesh_gpu(rs, mesh);
        self.mesh_source = source;
        self.project_dir = None;
        self.modified = false;
        self.bake(rs);
    }

    fn bake(&mut self, rs: &RenderState) {
        let Some(mg) = &self.mesh_gpu else { return };
        let t0 = Instant::now();
        self.baker.bake(&rs.device, &rs.queue, &self.mesh, mg, &mut self.ts, &self.doc.bake);
        let _ = rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: None });
        self.composited = None;
        self.set_status(format!("Baked AO + curvature ({} directions) in {:.0} ms", self.doc.bake.ao_samples, t0.elapsed().as_secs_f64() * 1000.0), false);
    }

    fn open_mesh_as_new(&mut self, rs: &RenderState, path: &Path) {
        let t0 = Instant::now();
        match Mesh::load(path) {
            Ok(mesh) => {
                if !mesh.has_uvs {
                    self.set_status(format!("{} has no UVs, so it can't be painted. Unwrap it first (e.g. in Blender).", mesh.name), true);
                    return;
                }
                let tris = mesh.triangle_count();
                let name = mesh.name.clone();
                self.export_name = name.clone();
                self.new_project(rs, mesh, Some(path.to_path_buf()), Document::new_default());
                self.set_status(format!("New project from {name}: {} triangles, loaded in {:.0} ms", format_count(tris), t0.elapsed().as_secs_f64() * 1000.0), false);
            }
            Err(e) => self.set_status(format!("Couldn't open that file: {e:#}"), true),
        }
    }

    fn open_project(&mut self, rs: &RenderState, path: &Path) {
        let dir = if path.is_dir() { path.to_path_buf() } else { path.parent().map(Path::to_path_buf).unwrap_or_default() };
        let result = (|| -> anyhow::Result<()> {
            // Read everything first: a corrupt file must not leave a half-loaded
            // project that a later Save would write over the previous one.
            let doc = project::load_manifest(&dir)?;
            let mesh = Mesh::load(&dir.join(&doc.mesh))?;
            let size = doc.resolution;
            let mut layer_px = Vec::new();
            let mut mask_px = Vec::new();
            for l in &doc.layers {
                if let Some(r) = l.paint_res() {
                    layer_px.push((r, project::read_layer(&dir, r, size)?));
                }
                if let Some(m) = &l.mask {
                    mask_px.push((m.res, project::read_mask(&dir, m.res, size)?));
                }
            }
            self.reset_state(rs, doc);
            let (d, q) = (&rs.device, &rs.queue);
            for (r, px) in &layer_px {
                io::upload_layer(d, q, &mut self.ts, *r, px);
            }
            for (r, px) in mask_px {
                match px {
                    Some(px) => io::upload_mask(d, q, &mut self.ts, r, &px),
                    None => self.ts.new_mask(d, q, r, true),
                }
            }
            self.ts.unsaved.clear();
            self.export_name = dir.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| "Asset".into());
            self.load_mesh_gpu(rs, mesh);
            self.mesh_source = Some(dir.join(&self.doc.mesh));
            self.project_dir = Some(dir.clone());
            self.modified = false;
            Ok(())
        })();
        match result {
            Ok(()) => {
                self.bake(rs);
                self.set_status(format!("Opened {}", dir.display()), false);
            }
            Err(e) => self.set_status(format!("Couldn't open project: {e:#}"), true),
        }
    }

    fn save(&mut self, rs: &RenderState, save_as: bool) {
        let dir = match (&self.project_dir, save_as) {
            (Some(d), false) => d.clone(),
            _ => {
                let Some(mut p) = rfd::FileDialog::new().set_title("Save project").set_file_name(format!("{}.{}", self.export_name, project::EXTENSION)).save_file()
                else {
                    return;
                };
                if p.extension().is_none_or(|e| e != project::EXTENSION) {
                    p.set_extension(project::EXTENSION);
                }
                p
            }
        };
        self.save_to(rs, dir);
    }

    fn save_to(&mut self, rs: &RenderState, dir: PathBuf) {
        let fresh = self.project_dir.as_deref() != Some(dir.as_path());
        let t0 = Instant::now();
        let result = (|| -> anyhow::Result<usize> {
            std::fs::create_dir_all(&dir)?;
            // the mesh lives inside the project
            let inside = self.mesh_source.as_ref().is_some_and(|m| m.starts_with(&dir));
            if fresh || !inside || self.doc.mesh.is_empty() {
                self.doc.mesh = match &self.mesh_source {
                    Some(src) if src.exists() => project::copy_mesh(&dir, src)?,
                    _ => {
                        std::fs::create_dir_all(dir.join("mesh"))?;
                        self.mesh.write_obj(&dir.join("mesh/mesh.obj"))?;
                        "mesh/mesh.obj".to_string()
                    }
                };
                self.committed.mesh = self.doc.mesh.clone();
                self.mesh_source = Some(dir.join(&self.doc.mesh));
            }
            let (d, q) = (&rs.device, &rs.queue);
            let mut written = 0;
            for l in &self.doc.layers {
                if let Some(r) = l.paint_res() {
                    if fresh || self.ts.unsaved.contains(&r) || !project::layer_dir(&dir, r).exists() {
                        if let Some(px) = io::read_layer(d, q, &self.ts, r) {
                            project::write_layer(&dir, r, &px)?;
                            written += 1;
                        }
                    }
                }
                if let Some(m) = &l.mask {
                    if fresh || self.ts.unsaved.contains(&m.res) || !project::mask_path(&dir, m.res).exists() {
                        if let Some(px) = io::read_mask(d, q, &self.ts, m.res) {
                            project::write_mask(&dir, m.res, self.ts.res, &px)?;
                            written += 1;
                        }
                    }
                }
            }
            project::prune(&dir, &self.doc)?;
            project::save_manifest(&dir, &self.doc)?;
            project::write_gitignore(&dir)?;
            Ok(written)
        })();
        match result {
            Ok(n) => {
                self.ts.unsaved.clear();
                self.project_dir = Some(dir.clone());
                self.modified = false;
                self.set_status(format!("Saved {} ({n} image files updated, {:.0} ms)", dir.display(), t0.elapsed().as_secs_f64() * 1000.0), false);
            }
            Err(e) => self.set_status(format!("Save failed: {e:#}"), true),
        }
    }

    fn export(&mut self, rs: &RenderState) {
        let Some(dir) = self.export_dir.clone() else { return };
        let Some(preset) = export::preset(&self.doc.export_preset) else { return };
        let t0 = Instant::now();
        self.ensure_composited(rs);
        // finish queued GPU work (composite) first so the timings say where time goes
        let _ = rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: None });
        let t_wait = t0.elapsed().as_secs_f64() * 1000.0;
        let m = io::read_material(&rs.device, &rs.queue, &self.ts);
        let t_read = t0.elapsed().as_secs_f64() * 1000.0;
        self.last_emissive_scale = m.emissive_scale;
        // material.json sidecar for the Blender bridge (tools/blender_addon)
        let sidecar = pigment_core::bridge::SidecarExtra { project: self.project_dir.clone(), source_mesh: self.mesh_source.clone(), mesh: None };
        let opts = export::ExportOptions { compression: self.export_compression, ..Default::default() };
        match export::export_with(&dir, &self.export_name, &preset, &m, opts).and_then(|f| pigment_core::bridge::write_sidecar(&dir, &self.export_name, &preset, &m, &sidecar).map(|_| f)) {
            Ok(files) => {
                let total = t0.elapsed().as_secs_f64() * 1000.0;
                self.last_export_ms = [t_wait, t_read - t_wait, total - t_read, total];
                self.set_status(
                    format!(
                        "Exported {} maps ({}x{}) to {} in {:.0} ms (GPU finish {:.0} ms, read back {:.0} ms, PNG encode {:.0} ms)",
                        files.len(),
                        m.size,
                        m.size,
                        dir.display(),
                        total,
                        t_wait,
                        t_read - t_wait,
                        total - t_read
                    ),
                    false,
                )
            }
            Err(e) => self.set_status(format!("Export failed: {e:#}"), true),
        }
    }

    fn change_resolution(&mut self, rs: &RenderState, res: u32) {
        if res == self.ts.res {
            return;
        }
        let (d, q) = (&rs.device, &rs.queue);
        let mut nts = TexSet::new(d, q, res);
        io::resample_into(d, q, &self.ts, &mut nts);
        self.ts = nts;
        self.painter.resize(d, res);
        self.doc.resolution = res;
        self.committed.resolution = res;
        // tile snapshots are resolution-specific; textures only history used go too
        let _ = self.history.clear();
        let live = self.live_resources();
        self.ts.retain(&live);
        if let Some(mg) = &self.mesh_gpu {
            let (c, r) = self.mesh.bounding_sphere();
            self.ts.prepare_mesh(d, q, mg, c, r);
        }
        self.modified = true;
        self.bake(rs);
        self.set_status(format!("Texture size is now {res}x{res} (undo history cleared)"), false);
    }

    fn run_pending(&mut self, rs: &RenderState, p: Pending) {
        match p {
            Pending::NewFromMesh(path) => self.open_mesh_as_new(rs, &path),
            Pending::OpenProject(path) => self.open_project(rs, &path),
            Pending::NewTorus => {
                self.new_project(rs, Mesh::torus(1.0, 0.38, 192, 64), None, Document::new_default());
                self.export_name = "Torus".into();
                self.set_status("New project with the test torus", false);
            }
            Pending::Demo => {
                self.new_project(rs, Mesh::demo_crate(96), None, Document::demo());
                self.export_name = "DemoCrate".into();
                self.set_status("Demo crate: painted metal with edge wear and dirt. Select a layer to see how it's built.", false);
            }
        }
    }

    /// Run an action that replaces the project, asking first if there are unsaved changes.
    fn request(&mut self, rs: &RenderState, p: Pending) {
        if self.modified {
            self.pending = Some(p);
        } else {
            self.run_pending(rs, p);
        }
    }

    // ------------------------------------------------------------ undo

    fn live_resources(&self) -> HashSet<ResId> {
        let mut live: HashSet<ResId> = self.doc.resources().into_iter().collect();
        live.extend(self.committed.resources());
        for e in self.history.entries() {
            match &e.data {
                Edit::Doc { before, after } => {
                    live.extend(before.resources());
                    live.extend(after.resources());
                }
                Edit::Stroke(s) => {
                    live.insert(s.target.res());
                }
            }
        }
        live
    }

    fn push_history(&mut self, label: String, e: Edit) {
        let mut dropped: Vec<Entry<Edit>> = self.history.push(label, e);
        dropped.extend(self.history.trim_to_budget(UNDO_BUDGET_BYTES, |e| match e {
            Edit::Stroke(s) => s.bytes(),
            Edit::Doc { .. } => 0,
        }));
        self.modified = true;
        if !dropped.is_empty() {
            drop(dropped);
            let live = self.live_resources();
            self.ts.retain(&live);
        }
    }

    fn commit_doc_changes(&mut self) {
        if self.doc != self.committed {
            let label = Document::describe_change(&self.committed, &self.doc);
            let before = Box::new(std::mem::replace(&mut self.committed, self.doc.clone()));
            self.push_history(label, Edit::Doc { before, after: Box::new(self.doc.clone()) });
        }
    }

    fn undo(&mut self, rs: &RenderState, redo: bool) {
        if self.stroke.is_some() {
            return;
        }
        self.commit_doc_changes();
        let entry = if redo { self.history.redo() } else { self.history.undo() };
        let Some(entry) = entry else { return };
        let label = entry.label.clone();
        match &mut entry.data {
            Edit::Doc { before, after } => {
                let mut d = if redo { (**after).clone() } else { (**before).clone() };
                // Ids are never reused: an undone layer's pixels may still exist
                // (the redo branch references them), so a re-minted id would
                // silently pick them up.
                d.next_id = d.next_id.max(self.doc.next_id).max(self.committed.next_id);
                self.doc = d.clone();
                self.committed = d;
            }
            Edit::Stroke(snap) => {
                self.painter.swap(&rs.device, &rs.queue, &self.ts, snap);
                self.ts.unsaved.insert(snap.target.res());
                self.composited = None;
            }
        }
        let sel = self.selected.filter(|id| self.doc.layer(*id).is_some()).or_else(|| self.doc.layers.last().map(|l| l.id));
        self.select(sel, self.paint_mask);
        self.modified = true;
        if !redo {
            self.counters.undos += 1;
        }
        self.set_status(format!("{} {label}", if redo { "Redo:" } else { "Undo:" }), false);
        log::info!("history: {:?}", self.history.history());
    }

    // ------------------------------------------------------------ painting

    /// Painting on a fill layer without a mask gives it a black mask first,
    /// so the brush reveals the fill where you paint (like Substance).
    fn auto_mask_for_fill(&mut self, rs: &RenderState) {
        let Some(i) = self.selected.and_then(|id| self.doc.index_of(id)) else { return };
        if self.doc.layers[i].is_paint() {
            return;
        }
        if self.doc.layers[i].mask.is_some() {
            self.paint_mask = true; // keep the UI on the tab the brush actually paints
            return;
        }
        self.commit_doc_changes();
        let res = self.doc.mint();
        if self.doc.layers[i].is_folder() {
            // a folder starts fully shown: painting hides parts of it
            self.ts.new_mask(&rs.device, &rs.queue, res, true);
            self.doc.layers[i].mask = Some(Mask::new(res));
            self.paint_mask = true;
            self.brush.mask_white = false;
            self.brush.erase = false;
            self.commit_doc_changes();
            let name = self.doc.layers[i].name.clone();
            self.set_status(format!("Added a white mask to folder {name}: painting hides it"), false);
            return;
        }
        self.ts.new_mask(&rs.device, &rs.queue, res, false);
        self.doc.layers[i].mask = Some(Mask { res, generator: None, invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
        self.paint_mask = true;
        self.brush.mask_white = true;
        self.brush.erase = false;
        self.commit_doc_changes();
        let name = self.doc.layers[i].name.clone();
        self.set_status(format!("Added a black mask to {name}: painting reveals the fill"), false);
    }

    fn paint_target(&self) -> Result<Target, &'static str> {
        let l = self.selected.and_then(|id| self.doc.layer(id)).ok_or("Select a layer to paint on")?;
        if self.paint_mask || !l.is_paint() {
            return match &l.mask {
                Some(m) => Ok(Target::Mask(m.res)),
                None if l.is_paint() => Err("This layer has no mask. Add one in the layer properties."),
                None => Err("Fill layers can't be painted directly. Add a mask to paint where the fill shows."),
            };
        }
        Ok(Target::Layer(l.paint_res().unwrap()))
    }

    fn brush_gpu(&self) -> BrushGpu {
        let b = &self.brush;
        let c = b.values.base_color.map(srgb_to_linear);
        let n = normal_from_tilt(Vec2::from(b.values.normal));
        let on = |i: usize| if b.channels[i] { 1.0 } else { 0.0 };
        let mask_value = if b.erase { if b.mask_white { 0.0 } else { 1.0 } } else if b.mask_white { 1.0 } else { 0.0 };
        BrushGpu {
            color: [c[0], c[1], c[2], 1.0],
            rmh: [b.values.roughness, b.values.metallic, b.values.height, 0.0],
            normal: [n.x, n.y, n.z, 0.0],
            enabled: [on(0), on(1), on(2), on(3)],
            enabled2: [on(4), if b.erase { 1.0 } else { 0.0 }, mask_value, 0.0],
            emissive: {
                let e = b.values.emissive.map(srgb_to_linear);
                let k = b.values.emissive_strength.max(0.0);
                [e[0] * k, e[1] * k, e[2] * k, 1.0]
            },
            enabled3: [on(5), 0.0, 0.0, 0.0],
            extra: [b.values.opacity.clamp(0.0, 1.0), b.values.transmission.clamp(0.0, 1.0), on(6), on(7)],
        }
    }

    fn begin_stroke(&mut self, rs: &RenderState, pos_px: Vec2, viewport_px: Vec2) {
        self.auto_mask_for_fill(rs);
        let target = match self.paint_target() {
            Ok(t) => t,
            Err(msg) => {
                self.set_status(msg, true);
                return;
            }
        };
        if self.viewport.paint_depth().is_none() || self.mesh_gpu.is_none() {
            return;
        }
        // make sure the stack is current before snapshotting / partial compositing
        self.ensure_composited(rs);
        if !self.painter.begin(&rs.device, &rs.queue, &self.ts, target) {
            return;
        }
        let aspect = viewport_px.x / viewport_px.y.max(1.0);
        let vp = self.camera.view_proj(aspect);
        let eye = self.camera.eye();
        let view = ViewGpu {
            view_proj: vp.to_cols_array_2d(),
            eye: [eye.x, eye.y, eye.z, 1.0],
            viewport: [viewport_px.x, viewport_px.y, self.camera.near(), 0.0],
        };
        let bins = ScreenBins::build(&self.mesh, vp, viewport_px, Some(eye));
        let mut s = Stroke { sampler: StrokeSampler::default(), bins, tiles: TileSet::default(), target, view };
        let stamps = s.sampler.begin(pos_px);
        self.stroke = Some(s);
        self.apply_stamps(rs, stamps);
    }

    fn apply_stamps(&mut self, rs: &RenderState, points: Vec<Vec2>) {
        if points.is_empty() {
            return;
        }
        let ppp_radius = self.brush_radius_px();
        let (opacity, hardness) = (self.brush.opacity, self.brush.hardness);
        let brush = self.brush_gpu();
        let Some(stroke) = self.stroke.as_mut() else { return };
        let t0 = Instant::now();
        let mut frame_tiles = TileSet::default();
        let stamps: Vec<StampGpu> = points
            .iter()
            .map(|p| {
                stroke.bins.mark_stamp(*p, ppp_radius, &mut frame_tiles);
                StampGpu { center_radius: [p.x, p.y, ppp_radius, opacity], params: [hardness, 0.0, 0.0, 0.0] }
            })
            .collect();
        stroke.tiles.union(&frame_tiles);
        let Some(rect) = frame_tiles.texel_bounds(self.ts.res) else { return };
        let view = stroke.view;
        let (Some(depth), Some(mg)) = (self.viewport.paint_depth(), self.mesh_gpu.as_ref()) else { return };
        self.painter.stamps(&rs.device, &rs.queue, &self.ts, mg, depth, view, &stamps, &brush, rect);
        self.ts.composite(&rs.device, &rs.queue, &self.doc, Some(rect));
        self.last_stamp_ms = t0.elapsed().as_secs_f32() * 1000.0 / stamps.len() as f32;
    }

    /// The mesh part under a viewport pixel, if any.
    pub(super) fn part_at(&self, px: Vec2, viewport_px: Vec2) -> Option<u32> {
        let vp = self.camera.view_proj(viewport_px.x / viewport_px.y.max(1.0));
        let ndc = Vec2::new(px.x / viewport_px.x * 2.0 - 1.0, 1.0 - px.y / viewport_px.y * 2.0);
        let near = vp.inverse().project_point3(glam::Vec3::new(ndc.x, ndc.y, 1.0));
        let eye = self.camera.eye();
        let (t, _) = self.mesh.raycast(eye, (near - eye).normalize())?;
        self.parts.triangle_part.get(t).copied()
    }

    /// Toggle a part in the selected layer's mask (adding a white mask if needed).
    pub(super) fn toggle_part(&mut self, rs: &RenderState, part: u32) -> Result<String, String> {
        if part >= MAX_SELECTABLE_PARTS {
            return Err(format!("part {part} is beyond the {MAX_SELECTABLE_PARTS} selectable parts"));
        }
        let i = self.selected.and_then(|id| self.doc.index_of(id)).ok_or("select a layer first")?;
        if self.doc.layers[i].mask.is_none() {
            let res = self.doc.mint();
            self.ts.new_mask(&rs.device, &rs.queue, res, true);
            self.doc.layers[i].mask = Some(Mask::new(res));
        }
        let m = self.doc.layers[i].mask.as_mut().unwrap();
        let added = match m.parts.iter().position(|&p| p == part) {
            Some(k) => {
                m.parts.remove(k);
                false
            }
            None => {
                m.parts.push(part);
                m.parts.sort_unstable();
                true
            }
        };
        let tris = self.parts.info.get(part as usize).map(|p| p.triangles).unwrap_or(0);
        Ok(format!("{} part {part} ({tris} triangles) - {} selected", if added { "Added" } else { "Removed" }, m.parts.len()))
    }

    fn decal_texture(&mut self, rs: &RenderState, path: &Path) -> Result<(), String> {
        if self.decals.contains_key(path) {
            return Ok(());
        }
        let img = image::open(path).map_err(|e| format!("couldn't read {}: {e}", path.display()))?.to_rgba8();
        let (w, h) = img.dimensions();
        let t = crate::render::gpu::Tex::new(
            &rs.device,
            "decal",
            w,
            h,
            eframe::egui_wgpu::wgpu::TextureFormat::Rgba8UnormSrgb,
            crate::render::gpu::rw_usage(),
            crate::render::gpu::mip_count(w.max(h)),
        );
        crate::render::gpu::upload(&rs.queue, &t, img.as_raw());
        let mut enc = rs.device.create_command_encoder(&Default::default());
        self.ts.mip_gen().generate(&rs.device, &mut enc, &t, None);
        rs.queue.submit([enc.finish()]);
        self.decals.insert(path.to_path_buf(), t);
        Ok(())
    }

    /// Project an image onto the selected layer (or its mask) from the
    /// current camera, over `rect` = [x0, y0, x1, y1] viewport pixels. Colour
    /// comes from the image tinted by the brush colour; the brush's other
    /// enabled channels (roughness, metallic, height, emission) are painted
    /// wherever the image is opaque. One undo step.
    pub(super) fn project_decal(&mut self, rs: &RenderState, image: &Path, rect: [f32; 4], viewport_px: Vec2, luminance_alpha: bool) -> Result<(), String> {
        self.project_decal_ex(rs, image, rect, viewport_px, luminance_alpha, true)
    }

    /// `project_decal`, optionally without an undo step (variant export
    /// replays decals onto scratch layers that never enter the history).
    pub(super) fn project_decal_ex(&mut self, rs: &RenderState, image: &Path, rect: [f32; 4], viewport_px: Vec2, luminance_alpha: bool, record_history: bool) -> Result<(), String> {
        if self.stroke.is_some() {
            return Err("finish the current stroke first".into());
        }
        self.decal_texture(rs, image)?;
        self.auto_mask_for_fill(rs);
        let target = self.paint_target().map_err(String::from)?;
        let (Some(depth), Some(mg)) = (self.viewport.paint_depth(), self.mesh_gpu.as_ref()) else { return Err("no viewport yet".into()) };
        let _ = (depth, mg);
        self.ensure_composited(rs);
        if !self.painter.begin(&rs.device, &rs.queue, &self.ts, target) {
            return Err("nothing to paint on".into());
        }
        let aspect = viewport_px.x / viewport_px.y.max(1.0);
        let vp = self.camera.view_proj(aspect);
        let eye = self.camera.eye();
        let view = ViewGpu { view_proj: vp.to_cols_array_2d(), eye: [eye.x, eye.y, eye.z, 1.0], viewport: [viewport_px.x, viewport_px.y, self.camera.near(), 0.0] };
        let bins = ScreenBins::build(&self.mesh, vp, viewport_px, Some(eye));
        let mut tiles = TileSet::default();
        let c = Vec2::new((rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5);
        let half = Vec2::new((rect[2] - rect[0]).abs(), (rect[3] - rect[1]).abs()) * 0.5;
        bins.mark_stamp(c, half.length(), &mut tiles);
        let tex = &self.decals[image];
        let lod = ((tex.size as f32 / (rect[2] - rect[0]).abs().max(1.0)).log2()).max(0.0);
        let mut brush = self.brush_gpu();
        brush.enabled3[1] = 1.0;
        let decal = DecalGpu { rect, params: [self.brush.opacity, lod, luminance_alpha as u32 as f32, 0.0] };
        if let Some(texels) = tiles.texel_bounds(self.ts.res) {
            let (depth, mg) = (self.viewport.paint_depth().unwrap(), self.mesh_gpu.as_ref().unwrap());
            self.painter.decal(&rs.device, &rs.queue, &self.ts, mg, depth, view, tex, decal, &brush, texels);
        }
        if let Some(snap) = self.painter.end(&rs.device, &rs.queue, &tiles).filter(|_| record_history) {
            self.ts.unsaved.insert(target.res());
            let name = image.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
            self.counters.strokes += 1;
            self.push_history(format!("Decal {name}"), Edit::Stroke(snap));
        }
        self.composited = None;
        Ok(())
    }

    fn end_stroke(&mut self, rs: &RenderState) {
        let Some(stroke) = self.stroke.take() else { return };
        if let Some(snap) = self.painter.end(&rs.device, &rs.queue, &stroke.tiles) {
            self.ts.unsaved.insert(stroke.target.res());
            let what = match stroke.target {
                Target::Layer(_) => {
                    self.counters.strokes += 1;
                    "Paint"
                }
                Target::Mask(_) => {
                    self.counters.mask_strokes += 1;
                    "Paint mask"
                }
            };
            let layer = self.selected.and_then(|id| self.doc.layer(id)).map(|l| l.name.clone()).unwrap_or_default();
            log::info!("stroke recorded: {} tiles, {:.1} MB snapshot", stroke.tiles.count(), snap.bytes() as f64 / 1048576.0);
            self.push_history(format!("{what} on {layer}"), Edit::Stroke(snap));
        }
        // full pass refreshes seam padding outside the dirty rectangles
        self.composited = None;
    }

    fn brush_radius_px(&self) -> f32 {
        self.brush.size * 0.5 * self.ppp
    }

    /// Where image fills' relative paths are looked up (each and its parents).
    pub(super) fn image_bases(&self) -> Vec<PathBuf> {
        self.project_dir.iter().cloned().chain(self.mesh_source.as_ref().and_then(|m| m.parent()).map(Path::to_path_buf)).collect()
    }

    fn ensure_composited(&mut self, rs: &RenderState) {
        self.ts.tiles.bases = self.image_bases();
        self.ts.ensure_resources(&rs.device, &rs.queue, &self.doc);
        if self.composited.as_ref() != Some(&self.doc) {
            self.ts.composite(&rs.device, &rs.queue, &self.doc, None);
            self.composited = Some(self.doc.clone());
        }
    }
}

fn format_count(n: usize) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use eframe::egui_wgpu::wgpu;

    fn headless() -> Option<RenderState> {
        let instance = wgpu::Instance::default();
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default())).ok()?;
        let (device, queue) = pollster::block_on(adapter.request_device(&crate::render::gpu::device_descriptor(&adapter))).ok()?;
        let format = wgpu::TextureFormat::Rgba8UnormSrgb;
        let renderer = eframe::egui_wgpu::Renderer::new(&device, format, Default::default());
        Some(RenderState {
            available_adapters: vec![adapter.clone()],
            adapter,
            instance,
            device,
            queue,
            target_format: format,
            renderer: std::sync::Arc::new(egui::mutex::RwLock::new(renderer)),
        })
    }

    fn draw(app: &mut PigmentApp, rs: &RenderState) {
        app.ensure_composited(rs);
        app.viewport.ensure_targets(&rs.device, [800, 800]);
        app.viewport.draw(&rs.device, &rs.queue, &app.camera, &app.view, app.mesh_gpu.as_ref(), &app.env, &app.ts);
    }

    fn paint(app: &mut PigmentApp, rs: &RenderState, from: Vec2, to: Vec2) {
        draw(app, rs);
        app.begin_stroke(rs, from, Vec2::new(800.0, 800.0));
        for i in 1..=6 {
            let pts = app.stroke.as_mut().unwrap().sampler.move_to(from.lerp(to, i as f32 / 6.0), 6.0);
            app.apply_stamps(rs, pts);
        }
        app.end_stroke(rs);
    }

    /// The whole app flow without a window: paint, edit layers, undo/redo,
    /// save, reopen, export.
    #[test]
    fn paint_edit_undo_save_reopen_export() {
        let Some(rs) = headless() else {
            eprintln!("no GPU adapter: skipping");
            return;
        };
        let mut app = PigmentApp::create(&rs, None);
        app.change_resolution(&rs, 512);
        let base_layers = app.doc.layers.len();
        let res = app.doc.layers.iter().find_map(|l| l.paint_res()).unwrap();

        paint(&mut app, &rs, Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
        assert!(app.history.can_undo(), "stroke recorded");
        let painted = io::read_layer(&rs.device, &rs.queue, &app.ts, res).unwrap();
        assert!(painted.color.chunks_exact(4).any(|p| p[3] > 0), "stroke left no pixels");

        // a layer edit, committed the way the UI does it
        let mut fill = app.doc.new_fill_layer("Rust");
        fill.opacity = 0.5;
        app.doc.layers.push(fill);
        app.commit_doc_changes();
        assert_eq!(app.history.undo_label(), Some("Add layer Rust"));
        app.undo(&rs, false);
        assert_eq!(app.doc.layers.len(), base_layers);
        app.undo(&rs, false); // the stroke
        let blank = io::read_layer(&rs.device, &rs.queue, &app.ts, res).unwrap();
        assert!(blank.color.chunks_exact(4).all(|p| p[3] == 0), "undo left pixels behind");
        app.undo(&rs, true);
        app.undo(&rs, true);
        assert_eq!(app.doc.layers.len(), base_layers + 1);
        assert_eq!(io::read_layer(&rs.device, &rs.queue, &app.ts, res).unwrap(), painted);

        // mask with a generator, painted on
        let i = app.doc.layers.len() - 1;
        let mres = app.doc.mint();
        app.ts.new_mask(&rs.device, &rs.queue, mres, true);
        app.doc.layers[i].mask = Some(Mask { res: mres, generator: Some(Generator::new(GeneratorKind::Dirt)), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
        app.selected = Some(app.doc.layers[i].id);
        app.paint_mask = true;
        app.brush.mask_white = false;
        paint(&mut app, &rs, Vec2::new(300.0, 300.0), Vec2::new(500.0, 320.0));
        app.commit_doc_changes();

        // save, reopen, compare
        let dir = std::env::temp_dir().join(format!("pigment-app-test-{}.pigment", std::process::id()));
        std::fs::remove_dir_all(&dir).ok();
        app.save_to(&rs, dir.clone());
        assert!(!app.modified, "save failed: {:?}", app.status);
        assert!(dir.join("project.json").exists());
        assert!(dir.join("mesh/mesh.obj").exists());
        assert!(app.doc.layers.iter().any(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())), "demo stack saved");
        let mask_before = io::read_mask(&rs.device, &rs.queue, &app.ts, mres).unwrap();
        let doc_before = app.doc.clone();

        let files = walk(&dir);
        assert!(files.iter().any(|f| f.ends_with("base_color.png")), "{files:?}");
        let mut app2 = PigmentApp::create(&rs, None);
        app2.open_project(&rs, &dir);
        assert_eq!(app2.doc, doc_before, "status: {:?}", app2.status);
        assert!(io::read_layer(&rs.device, &rs.queue, &app2.ts, res).unwrap() == painted, "layer pixels differ after reopen");
        assert_eq!(io::read_mask(&rs.device, &rs.queue, &app2.ts, mres).unwrap(), mask_before);
        assert!(mask_before.iter().any(|&v| v < 128), "mask stroke didn't paint black");

        // export
        let out = dir.join("export");
        app2.export_dir = Some(out.clone());
        app2.export_name = "Torus".into();
        app2.export(&rs);
        for f in ["Torus_BaseColor.png", "Torus_Normal.png", "Torus_OcclusionRoughnessMetallic.png", "Torus_Height.png"] {
            assert!(out.join(f).exists(), "missing {f}: {:?}", app2.status);
        }
        std::fs::remove_dir_all(dir).ok();
    }

    fn walk(d: &Path) -> Vec<PathBuf> {
        let mut out = Vec::new();
        for e in std::fs::read_dir(d).into_iter().flatten().flatten() {
            if e.path().is_dir() {
                out.extend(walk(&e.path()));
            } else {
                out.push(e.path());
            }
        }
        out
    }

    /// Review finding: undo rolled the id counter back, so a new layer could
    /// reuse the id of an undone duplicate and show its pixels.
    #[test]
    fn ids_are_never_reused_after_undo() {
        let Some(rs) = headless() else { return };
        let mut app = PigmentApp::create(&rs, None);
        app.change_resolution(&rs, 512);
        paint(&mut app, &rs, Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
        app.duplicate_selected(&rs);
        app.commit_doc_changes();
        let dup_res = app.doc.layer(app.selected.unwrap()).unwrap().paint_res().unwrap();
        app.undo(&rs, false);
        let l = app.doc.new_paint_layer("Fresh");
        let fresh_res = l.paint_res().unwrap();
        app.insert_layer(l);
        app.commit_doc_changes();
        assert_ne!(fresh_res, dup_res, "resource id reused");
        app.ensure_composited(&rs);
        let px = io::read_layer(&rs.device, &rs.queue, &app.ts, fresh_res).unwrap();
        assert!(px.color.chunks_exact(4).all(|p| p[3] == 0), "new layer came with old pixels");
    }

    /// Review finding: a failed open must leave the current project untouched.
    #[test]
    fn failed_open_keeps_the_current_project() {
        let Some(rs) = headless() else { return };
        let tmp = std::env::temp_dir().join(format!("pigment-badopen-{}", std::process::id()));
        std::fs::remove_dir_all(&tmp).ok();
        let mut app = PigmentApp::create(&rs, None);
        app.change_resolution(&rs, 512);
        paint(&mut app, &rs, Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
        // project B with a corrupt layer image
        let b = tmp.join("b.pigment");
        app.save_to(&rs, b.clone());
        let bad = walk(&b).into_iter().find(|f| f.ends_with("base_color.png")).unwrap();
        std::fs::write(&bad, b"not a png").unwrap();
        // project A, the one we have open
        let a = tmp.join("a.pigment");
        let l = app.doc.new_fill_layer("Only in A");
        app.insert_layer(l);
        app.commit_doc_changes();
        app.save_to(&rs, a.clone());
        let doc_a = app.doc.clone();
        app.open_project(&rs, &b);
        assert!(app.status.as_ref().is_some_and(|(_, err)| *err), "corrupt project should fail to open");
        assert_eq!(app.doc, doc_a, "document changed by a failed open");
        assert_eq!(app.project_dir.as_deref(), Some(a.as_path()));
        std::fs::remove_dir_all(&tmp).ok();
    }

    /// The quick-start guide advances as the user does each step.
    #[test]
    fn quick_start_guide_follows_the_user() {
        let Some(rs) = headless() else { return };
        let mut app = PigmentApp::create(&rs, None);
        app.change_resolution(&rs, 512);
        app.tour_start(true);
        assert_eq!(app.tour.step, 0);
        app.tour_update();
        assert_eq!(app.tour.step, 0, "advanced without doing anything");
        // 1: look around
        app.camera.orbit(Vec2::new(80.0, 0.0));
        app.tour_update();
        assert_eq!(app.tour.step, 1);
        // 2: paint
        app.tour_show_me();
        paint(&mut app, &rs, Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
        app.tour_update();
        assert_eq!(app.tour.step, 2);
        // 3: undo
        app.undo(&rs, false);
        app.tour_update();
        assert_eq!(app.tour.step, 3);
        // 4: change the edge wear amount
        app.tour_show_me();
        assert!(app.paint_mask, "show-me opens the mask");
        let i = app.edge_wear_layer().unwrap();
        app.doc.layers[i].mask.as_mut().unwrap().generator.as_mut().unwrap().amount = 0.3;
        app.tour_update();
        assert_eq!(app.tour.step, 4);
        // 5: protect an area by painting the mask black
        app.tour_show_me();
        assert!(!app.brush.mask_white);
        paint(&mut app, &rs, Vec2::new(300.0, 300.0), Vec2::new(500.0, 320.0));
        app.tour_update();
        assert_eq!(app.tour.step, 5);
        // 6: export
        app.tour_show_me();
        app.tour_update();
        assert_eq!(app.tour.step, 6, "finished");
    }

    /// Builds `examples/<name>.pigment` from a Blender-made GLB with the worn
    /// paint smart material, and renders previews to %TEMP%/pig/showcase_*.png.
    /// `PIGMENT_SHOWCASE=assets/ammo_box.glb cargo test -p pigment --release build_showcase -- --ignored`
    #[test]
    #[ignore]
    fn build_showcase() {
        let Some(rs) = headless() else { return };
        let mesh_path = std::env::var("PIGMENT_SHOWCASE").unwrap_or_else(|_| "assets/ammo_box.glb".into());
        let paint = std::env::var("PIGMENT_SHOWCASE_PAINT").unwrap_or_else(|_| "Olive drab".into());
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mesh_path = root.join(mesh_path);
        let mut app = PigmentApp::create(&rs, None);
        app.open_mesh_as_new(&rs, &mesh_path);
        assert!(app.status.as_ref().is_some_and(|(_, e)| !e), "{:?}", app.status);
        let mut doc = Document { resolution: 2048, mesh: String::new(), ..Default::default() };
        for l in doc.worn_paint_layers(&paint) {
            doc.layers.push(l);
        }
        let top = doc.new_paint_layer("Paint");
        doc.layers.push(top);
        // small hard-surface parts are all edge: soften the curvature and the wear a little
        doc.bake.curvature_strength = 0.6;
        if let Some(g) = doc.layers.iter_mut().filter_map(|l| l.mask.as_mut()?.generator.as_mut()).find(|g| g.kind == GeneratorKind::EdgeWear) {
            g.amount = 0.5;
        }
        app.doc = doc.clone();
        app.committed = doc;
        app.bake(&rs);
        app.selected = app.doc.layers.last().map(|l| l.id);
        app.ensure_composited(&rs);
        let name = mesh_path.file_stem().unwrap().to_string_lossy().to_string();
        let out = std::env::temp_dir().join("pig");
        std::fs::create_dir_all(&out).ok();
        app.viewport.ensure_targets(&rs.device, [1400, 1000]);
        let base = app.camera.clone();
        for (k, (yaw, pitch, zoom)) in [(0.65f32, 0.38f32, 0.78f32), (-2.3, 0.25, 0.85), (0.2, 0.05, 0.5)].iter().enumerate() {
            app.camera.yaw = *yaw;
            app.camera.pitch = *pitch;
            app.camera.distance = base.distance * zoom;
            app.viewport.draw(&rs.device, &rs.queue, &app.camera, &app.view, app.mesh_gpu.as_ref(), &app.env, &app.ts);
            let img = crate::render::gpu::readback(&rs.device, &rs.queue, app.viewport.color().unwrap());
            image::save_buffer(out.join(format!("showcase_{name}_{k}.png")), &img, 1400, 1000, image::ExtendedColorType::Rgba8).unwrap();
        }
        app.camera = base;
        let dir = root.join("examples").join(format!("{name}.pigment"));
        std::fs::remove_dir_all(&dir).ok();
        app.save_to(&rs, dir.clone());
        assert!(!app.modified, "{:?}", app.status);
        eprintln!("saved {}", dir.display());
    }

    /// Render the startup state through the app's own code path.
    #[test]
    #[ignore]
    fn app_startup_render() {
        let Some(rs) = headless() else { return };
        let mut app = PigmentApp::create(&rs, None);
        draw(&mut app, &rs);
        let img = crate::render::gpu::readback(&rs.device, &rs.queue, app.viewport.color().unwrap());
        let out = std::env::temp_dir().join("pig");
        image::save_buffer(out.join("app_startup.png"), &img, 800, 800, image::ExtendedColorType::Rgba8).unwrap();
        let bk = crate::render::gpu::readback(&rs.device, &rs.queue, &app.ts.bakes);
        let ao: Vec<f32> = bk.chunks_exact(8).map(|c| half::f16::from_bits(u16::from_le_bytes([c[0], c[1]])).to_f32()).collect();
        let mean = ao.iter().sum::<f32>() / ao.len() as f32;
        eprintln!("mean AO {mean}, baked {}", app.ts.baked);
    }

    #[test]
    fn counts_are_grouped() {
        assert_eq!(super::format_count(0), "0");
        assert_eq!(super::format_count(100000), "100,000");
        assert_eq!(super::format_count(1234567), "1,234,567");
    }
}
