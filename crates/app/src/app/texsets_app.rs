//! Several texture sets in one project (`pigment_core::texsets`).
//!
//! The active set lives in the app's usual fields (`doc`, `ts`, `mesh`,
//! history...), so every tool works on it unchanged; the other sets are
//! parked in `MultiSets`. Switching swaps them. The viewport draws every set,
//! painted strokes are replayed onto the other sets they touch (same screen
//! dabs, each set's own layer of the same name), saving writes each set to
//! its own folder, export names files `<name>_<set>_<map>.<udim>.png`.

use super::*;
use pigment_core::texsets::{self, SetSpec};

/// One parked texture set.
pub(crate) struct SetSlot {
    pub(super) doc: Document,
    pub(super) committed: Document,
    pub(super) composited: Option<Document>,
    pub(super) history: UndoStack<Edit>,
    pub(super) selected: Option<LayerId>,
    pub(super) paint_mask: bool,
    pub(super) ts: TexSet,
    pub(super) mesh: Mesh,
    pub(super) mesh_gpu: Option<MeshGpu>,
    pub(super) parts: pigment_core::mesh::Parts,
    pub(super) wrap_mesh: Option<Mesh>,
}

impl SetSlot {
    pub(crate) fn name(&self) -> String {
        set_name(&self.doc)
    }
}

/// The project's texture sets besides the active one.
pub(crate) struct MultiSets {
    pub(crate) parked: Vec<SetSlot>,
    /// Set names in project order.
    pub(crate) order: Vec<String>,
    /// The whole mesh (with UDIM moves applied).
    pub(crate) full: Mesh,
    /// Parts of the whole mesh (part masks use its ids in every set).
    pub(crate) part_count: usize,
}

pub(crate) fn set_name(doc: &Document) -> String {
    doc.texture_set.as_ref().map(|s| s.name.clone()).unwrap_or_else(|| "main".into())
}

/// The mesh a document paints: UDIM moves applied, then its set's part.
pub(crate) fn prepare_set_mesh(mesh: Mesh, doc: &Document) -> (Mesh, Mesh) {
    let mut full = mesh;
    texsets::apply_moves(&mut full, &doc.udim_moves);
    let sub = match &doc.texture_set {
        Some(spec) => texsets::submesh(&full, spec).0,
        None => full.clone(),
    };
    (sub, full)
}

impl PigmentApp {
    fn swap_slot(&mut self, s: &mut SetSlot) {
        std::mem::swap(&mut self.doc, &mut s.doc);
        std::mem::swap(&mut self.committed, &mut s.committed);
        std::mem::swap(&mut self.composited, &mut s.composited);
        std::mem::swap(&mut self.history, &mut s.history);
        std::mem::swap(&mut self.selected, &mut s.selected);
        std::mem::swap(&mut self.paint_mask, &mut s.paint_mask);
        std::mem::swap(&mut self.ts, &mut s.ts);
        std::mem::swap(&mut self.mesh, &mut s.mesh);
        std::mem::swap(&mut self.mesh_gpu, &mut s.mesh_gpu);
        std::mem::swap(&mut self.parts, &mut s.parts);
        std::mem::swap(&mut self.wrap_mesh, &mut s.wrap_mesh);
    }

    /// Move the active set's state out into a slot (the app is left with an
    /// empty placeholder until another set is swapped in).
    fn take_slot(&mut self, rs: &RenderState) -> SetSlot {
        let mut s = SetSlot {
            doc: Document::default(),
            committed: Document::default(),
            composited: None,
            history: UndoStack::default(),
            selected: None,
            paint_mask: false,
            ts: TexSet::new(&rs.device, &rs.queue, 8),
            mesh: Mesh::default(),
            mesh_gpu: None,
            parts: Default::default(),
            wrap_mesh: None,
        };
        self.swap_slot(&mut s);
        s
    }

    /// Names of every texture set, in project order.
    pub fn set_names(&self) -> Vec<String> {
        match &self.multi {
            Some(m) => m.order.clone(),
            None => vec![set_name(&self.doc)],
        }
    }

    pub fn active_set_name(&self) -> String {
        set_name(&self.doc)
    }

    /// Several texture sets?
    pub fn has_sets(&self) -> bool {
        self.multi.is_some()
    }

    /// Make texture set `name` the active one.
    pub fn activate_set(&mut self, rs: &RenderState, name: &str) -> Result<(), String> {
        if self.active_set_name() == name {
            return Ok(());
        }
        let Some(idx) = self.multi.as_ref().and_then(|m| m.parked.iter().position(|s| s.name() == name)) else {
            return Err(format!("no texture set `{name}` (sets: {})", self.set_names().join(", ")));
        };
        if self.stroke.is_some() {
            self.end_stroke(rs);
        }
        self.commit_doc_changes();
        let mut slot = self.multi.as_mut().unwrap().parked.remove(idx);
        self.swap_slot(&mut slot);
        self.multi.as_mut().unwrap().parked.push(slot);
        self.painter.resize(&rs.device, self.ts.res);
        self.ts.tiles.bases = self.image_bases();
        Ok(())
    }

    /// Split the (single-set) project into texture sets `specs`, each with
    /// a copy of the current stack, at `res[k]` (or the current resolution).
    pub fn split_sets(&mut self, rs: &RenderState, specs: Vec<SetSpec>, res: &[Option<u32>]) -> Result<Vec<String>, String> {
        if self.multi.is_some() {
            return Err("the project already has texture sets".into());
        }
        let full = self.mesh.clone();
        let base = self.doc.clone();
        let (c, r) = full.bounding_sphere();
        let (lo, hi) = full.bounds();
        let mut slots = Vec::new();
        let mut names = Vec::new();
        let source = self.mesh_source.clone();
        let project = self.project_dir.clone();
        for (k, spec) in specs.into_iter().enumerate() {
            let (sub, _) = texsets::submesh(&full, &spec);
            if sub.triangle_count() == 0 {
                continue;
            }
            if names.contains(&spec.name) {
                return Err(format!("two texture sets are called `{}`", spec.name));
            }
            let mut d = base.clone();
            d.resolution = res.get(k).copied().flatten().unwrap_or(base.resolution);
            names.push(spec.name.clone());
            d.texture_set = Some(spec);
            self.reset_state(rs, d);
            self.ts.ensure_resources(&rs.device, &rs.queue, &self.doc);
            self.load_mesh_gpu(rs, sub);
            self.ts.set_frame(c, r, lo, hi);
            let async_bake = std::mem::replace(&mut self.ui.async_bake, false);
            self.bake(rs);
            self.ui.async_bake = async_bake;
            slots.push(self.take_slot(rs));
        }
        if slots.is_empty() {
            return Err("no texture set has any triangles".into());
        }
        let mut first = slots.remove(0);
        self.swap_slot(&mut first);
        let part_count = full.parts().info.len();
        self.multi = Some(Box::new(MultiSets { parked: slots, order: names.clone(), full: full.clone(), part_count }));
        self.painter.resize(&rs.device, self.ts.res);
        self.camera.frame(c, r);
        self.mesh_source = source;
        self.project_dir = project;
        Ok(names)
    }

    /// Composite every parked set that is out of date (the viewport draws them).
    pub(crate) fn composite_parked(&mut self, rs: &RenderState) {
        let Some(m) = self.multi.as_mut() else { return };
        for s in &mut m.parked {
            s.ts.ensure_resources(&rs.device, &rs.queue, &s.doc);
            if s.composited.as_ref() != Some(&s.doc) {
                s.ts.composite(&rs.device, &rs.queue, &s.doc, None);
                s.composited = Some(s.doc.clone());
            }
        }
    }

    /// Replay a finished paint stroke's dabs on every other set that has a
    /// paint layer (or mask) with the target layer's name: one stroke paints
    /// seamlessly across texture sets and UDIM tiles.
    pub(crate) fn replay_on_other_sets(&mut self, rs: &RenderState, log: &StrokeLog) {
        if self.multi.is_none() || log.dabs.is_empty() {
            return;
        }
        let Some(layer) = self.selected.and_then(|id| self.doc.layer(id)).map(|l| l.name.clone()) else { return };
        let on_mask = self.paint_mask;
        let home = self.active_set_name();
        for name in self.set_names() {
            if name == home || self.activate_set(rs, &name).is_err() {
                continue;
            }
            let Some(i) = self.doc.layers.iter().rposition(|l| l.name == layer) else { continue };
            let l = &self.doc.layers[i];
            let target = match (on_mask, l.paint_res(), l.mask.as_ref()) {
                (true, _, Some(m)) => Target::Mask(m.res),
                (false, Some(r), _) => Target::Layer(r),
                _ => continue,
            };
            self.ensure_composited(rs);
            let (Some(depth), Some(mg)) = (self.viewport.paint_depth(), self.mesh_gpu.as_ref()) else { continue };
            if !self.painter.begin(&rs.device, &rs.queue, &self.ts, target) {
                continue;
            }
            self.painter.set_fx(&rs.queue, &log.fx);
            let bins = ScreenBins::build(&self.mesh, log.view_proj, log.viewport_px, Some(log.eye));
            let mut tiles = TileSet::default();
            for st in &log.stamps {
                bins.mark_stamp(Vec2::new(st.center_radius[0], st.center_radius[1]), st.center_radius[2] * log.reach, &mut tiles);
            }
            if let Some(rect) = tiles.texel_bounds(self.ts.res) {
                self.painter.stamps(&rs.device, &rs.queue, &self.ts, mg, depth, log.view, &log.stamps, &log.brush, rect);
            }
            self.painter.set_fx(&rs.queue, &FxGpu::default());
            if let Some(snap) = self.painter.end(&rs.device, &rs.queue, &tiles) {
                self.ts.unsaved.insert(target.res());
                self.push_history(format!("Paint on {layer} (from {home})"), Edit::Stroke(snap));
            }
            self.composited = None;
        }
        let _ = self.activate_set(rs, &home);
    }

    /// Save every set: the first in `dir`, the others in `dir/sets/<name>`.
    pub(crate) fn save_sets(&mut self, rs: &RenderState, dir: PathBuf) {
        let names = self.set_names();
        let home = self.active_set_name();
        let mut failed = None;
        for (k, name) in names.iter().enumerate() {
            if let Err(e) = self.activate_set(rs, name) {
                failed = Some(e);
                break;
            }
            let sub = if k == 0 { dir.clone() } else { dir.join("sets").join(name) };
            self.doc.extra_sets = if k == 0 { names[1..].iter().map(|n| format!("sets/{n}")).collect() } else { Vec::new() };
            self.save_to(rs, sub);
            if self.status.as_ref().is_some_and(|s| s.1) {
                return;
            }
        }
        let _ = self.activate_set(rs, &home);
        self.project_dir = Some(dir.clone());
        match failed {
            Some(e) => self.set_status(e, true),
            None => self.set_status(format!("Saved {} ({} texture sets)", dir.display(), names.len()), false),
        }
    }

    /// Open a project with texture sets: every extra set, then the main one.
    pub(crate) fn open_sets(&mut self, rs: &RenderState, dir: &Path, extra: &[String]) {
        let mut slots = Vec::new();
        let mut names = Vec::new();
        for e in extra {
            self.open_project_one(rs, &dir.join(e));
            if self.status.as_ref().is_some_and(|s| s.1) {
                return;
            }
            names.push(self.active_set_name());
            slots.push(self.take_slot(rs));
        }
        self.open_project_one(rs, dir);
        if self.status.as_ref().is_some_and(|s| s.1) {
            return;
        }
        names.insert(0, self.active_set_name());
        let full = self.mesh_source.as_ref().and_then(|p| Mesh::load(p).ok()).map(|m| prepare_set_mesh(m, &self.doc).1).unwrap_or_else(|| self.mesh.clone());
        let (c, r) = full.bounding_sphere();
        let (lo, hi) = full.bounds();
        self.ts.set_frame(c, r, lo, hi);
        for s in &mut slots {
            s.ts.set_frame(c, r, lo, hi);
            s.composited = None;
        }
        self.composited = None;
        self.camera.frame(c, r);
        let part_count = full.parts().info.len();
        self.multi = Some(Box::new(MultiSets { parked: slots, order: names, full, part_count }));
        self.project_dir = Some(dir.to_path_buf());
    }

    /// Export every set: `<name>_<set>_<map>.<udim>.png`. Returns the files.
    pub(crate) fn export_sets(&mut self, rs: &RenderState, dir: &Path, name: &str) -> Result<Vec<PathBuf>, String> {
        let home = self.active_set_name();
        let mut files = Vec::new();
        for set in self.set_names() {
            self.activate_set(rs, &set)?;
            let tile = self.doc.texture_set.as_ref().map(|s| s.tile()).unwrap_or(1001);
            let prefix = format!("{name}_{}", texsets::sanitize(&set));
            self.export_name = prefix.clone();
            self.export_dir = Some(dir.to_path_buf());
            self.status = None;
            self.export(rs);
            if let Some((e, true)) = &self.status {
                return Err(e.clone());
            }
            let preset = export::preset(&self.doc.export_preset).ok_or("unknown export preset")?;
            for o in &preset.outputs {
                let from = dir.join(format!("{prefix}_{}.png", o.suffix));
                if from.exists() {
                    let to = dir.join(texsets::export_file(name, &texsets::sanitize(&set), o.suffix, tile));
                    std::fs::rename(&from, &to).map_err(|e| format!("renaming {}: {e}", from.display()))?;
                    files.push(to);
                }
            }
        }
        self.activate_set(rs, &home)?;
        self.export_name = name.to_string();
        Ok(files)
    }
}

/// What a stroke painted, for replaying it on other texture sets.
#[derive(Clone)]
pub(crate) struct StrokeLog {
    pub(crate) dabs: Vec<pigment_core::brush::Dab>,
    pub(crate) stamps: Vec<StampGpu>,
    pub(crate) brush: BrushGpu,
    pub(crate) fx: FxGpu,
    pub(crate) view: ViewGpu,
    pub(crate) view_proj: glam::Mat4,
    pub(crate) viewport_px: Vec2,
    pub(crate) eye: Vec3,
    pub(crate) reach: f32,
}
