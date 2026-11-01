//! Work that must not freeze the window: bakes (tracked on the GPU queue),
//! exports and autosaves (pixels are read back on the main thread, then
//! encoded and written on a worker thread). Each job shows a progress toast
//! that turns into a result toast.

use super::design::ToastKind;
use super::*;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};

pub enum JobKind {
    Bake { done: Arc<AtomicBool>, t0: Instant },
    Thread { rx: mpsc::Receiver<Result<(String, String), String>>, what: &'static str, then: Option<PathBuf> },
}

pub struct Job {
    pub toast: u64,
    pub kind: JobKind,
}

/// Where a one-click export goes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ExportTarget {
    pub id: &'static str,
    pub label: &'static str,
    pub preset: &'static str,
    pub blurb: &'static str,
    /// Also write the mesh (glTF) and the material sidecar for the Blender add-on.
    pub with_mesh: bool,
}

pub const TARGETS: [ExportTarget; 5] = [
    ExportTarget { id: "blender", label: "Blender", preset: "separate", blurb: "Maps + mesh + material.json for the Pigment Bridge add-on", with_mesh: true },
    ExportTarget { id: "unreal", label: "Unreal", preset: "unreal", blurb: "Packed ORM, DirectX normal", with_mesh: false },
    ExportTarget { id: "unity", label: "Unity", preset: "unity", blurb: "URP / Built-in metallic-smoothness", with_mesh: false },
    ExportTarget { id: "godot", label: "Godot", preset: "godot", blurb: "StandardMaterial3D maps", with_mesh: false },
    ExportTarget { id: "gltf", label: "glTF / other", preset: "separate", blurb: "One PNG per channel", with_mesh: false },
];

pub fn target(id: &str) -> ExportTarget {
    TARGETS.iter().copied().find(|t| t.id == id).unwrap_or(TARGETS[0])
}

/// `~/Documents/Pigment Exports`.
pub fn default_export_root() -> PathBuf {
    let home = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(PathBuf::from).unwrap_or_else(std::env::temp_dir);
    let docs = home.join("Documents");
    (if docs.is_dir() { docs } else { home }).join("Pigment Exports")
}

impl PigmentApp {
    pub(super) fn start_bake_job(&mut self, rs: &RenderState) {
        let done = Arc::new(AtomicBool::new(false));
        let d2 = done.clone();
        rs.queue.on_submitted_work_done(move || d2.store(true, Ordering::Release));
        rs.queue.submit([]);
        let toast = self.ui.toasts.push(ToastKind::Progress, "Baking mesh maps", "Ambient occlusion and curvature drive edge wear and dirt.");
        self.ui.jobs.push(Job { toast, kind: JobKind::Bake { done, t0: Instant::now() } });
    }

    pub(super) fn busy_with(&self, what: &str) -> bool {
        self.ui.jobs.iter().any(|j| matches!(&j.kind, JobKind::Thread { what: w, .. } if *w == what))
    }

    /// Export for `target` into `dir/<name>_*.png` without blocking the window.
    pub(super) fn export_async(&mut self, rs: &RenderState, t: ExportTarget, dir: PathBuf) {
        let Some(preset) = export::preset(t.preset) else { return };
        if self.busy_with("export") {
            self.ui.toasts.push(ToastKind::Info, "An export is already running", "");
            return;
        }
        self.ensure_composited(rs);
        let m = io::read_material(&rs.device, &rs.queue, &self.ts);
        self.last_emissive_scale = m.emissive_scale;
        let name = self.export_name.trim().to_string();
        let name = if name.is_empty() { "Asset".to_string() } else { name };
        let sidecar = pigment_core::bridge::SidecarExtra { project: self.project_dir.clone(), source_mesh: self.mesh_source.clone(), mesh: None };
        let opts = export::ExportOptions { compression: self.export_compression, ..Default::default() };
        let mesh = t.with_mesh.then(|| self.mesh.clone());
        let tile = self.doc.tile.clone();
        let res = self.doc.resolution;
        let (tx, rx) = mpsc::channel();
        let d2 = dir.clone();
        let label = t.label;
        std::thread::spawn(move || {
            let t0 = Instant::now();
            let r = (|| -> anyhow::Result<usize> {
                let files = export::export_with(&d2, &name, &preset, &m, opts)?;
                pigment_core::bridge::write_sidecar(&d2, &name, &preset, &m, &sidecar)?;
                if let Some(spec) = tile {
                    std::fs::write(d2.join(format!("{name}_layout.json")), serde_json::to_string_pretty(&spec.layout_json(&name, res))?)?;
                }
                if let Some(mesh) = mesh {
                    let file = format!("{name}.glb");
                    pigment_core::bridge::export_mesh(&mesh, &d2.join(&file))?;
                    pigment_core::bridge::update_sidecar(&d2, &name, &serde_json::json!({ "mesh": file }))?;
                }
                Ok(files.len())
            })();
            let _ = tx.send(match r {
                Ok(n) => Ok((format!("Exported for {label}"), format!("{n} maps{} in {:.1} s to {}", if label == "Blender" { " + mesh" } else { "" }, t0.elapsed().as_secs_f32(), d2.display()))),
                Err(e) => Err(friendly_error("Export failed", &format!("{e:#}"))),
            });
        });
        let toast = self.ui.toasts.push(ToastKind::Progress, format!("Exporting for {}", t.label), format!("{0}x{0} maps to {1}", self.ts.res, dir.display()));
        self.ui.jobs.push(Job { toast, kind: JobKind::Thread { rx, what: "export", then: Some(dir) } });
    }

    /// Write a recovery copy of the open project without touching it.
    pub(super) fn autosave(&mut self, rs: &RenderState) {
        let Some(dir) = self.ui.prefs.autosave_dir() else { return };
        if self.busy_with("autosave") || self.stroke.is_some() {
            return;
        }
        self.ui.last_autosave = Instant::now();
        let (d, q) = (&rs.device, &rs.queue);
        let mut layers = vec![];
        let mut masks = vec![];
        for l in &self.doc.layers {
            if let Some(r) = l.paint_res() {
                if let Some(px) = io::read_layer(d, q, &self.ts, r) {
                    layers.push((r, px));
                }
            }
            if let Some(m) = &l.mask {
                if let Some(px) = io::read_mask(d, q, &self.ts, m.res) {
                    masks.push((m.res, px));
                }
            }
        }
        let mut doc = self.doc.clone();
        let source = self.mesh_source.clone().filter(|p| p.exists());
        let mesh = if source.is_none() { Some(self.mesh.clone()) } else { None };
        let res = self.ts.res;
        let meta = serde_json::json!({ "project": self.project_dir, "name": self.export_name, "saved": std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) });
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let tmp = dir.with_extension("tmp");
            let r = (|| -> anyhow::Result<()> {
                let _ = std::fs::remove_dir_all(&tmp);
                std::fs::create_dir_all(&tmp)?;
                doc.mesh = match (&source, &mesh) {
                    (Some(src), _) => project::copy_mesh(&tmp, src)?,
                    (None, Some(m)) => {
                        std::fs::create_dir_all(tmp.join("mesh"))?;
                        m.write_obj(&tmp.join("mesh/mesh.obj"))?;
                        "mesh/mesh.obj".into()
                    }
                    _ => anyhow::bail!("no mesh"),
                };
                for (r, px) in &layers {
                    project::write_layer(&tmp, *r, px)?;
                }
                for (r, px) in &masks {
                    project::write_mask(&tmp, *r, res, px)?;
                }
                project::save_manifest(&tmp, &doc)?;
                std::fs::write(tmp.join("recovery.json"), serde_json::to_string_pretty(&meta)?)?;
                let _ = std::fs::remove_dir_all(&dir);
                std::fs::rename(&tmp, &dir)?;
                Ok(())
            })();
            let _ = tx.send(r.map(|_| (String::new(), String::new())).map_err(|e| format!("Autosave failed: {e:#}")));
        });
        let toast = 0;
        self.ui.jobs.push(Job { toast, kind: JobKind::Thread { rx, what: "autosave", then: None } });
    }

    /// The recovery copy left by a session that didn't close cleanly.
    pub(super) fn recovery(&self) -> Option<(PathBuf, String)> {
        let dir = self.ui.prefs.autosave_dir()?;
        let meta: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(dir.join("recovery.json")).ok()?).ok()?;
        let name = meta["name"].as_str().unwrap_or("Untitled").to_string();
        dir.join(project::MANIFEST).exists().then_some((dir, name))
    }

    pub(super) fn discard_recovery(&mut self) {
        if let Some(d) = self.ui.prefs.autosave_dir() {
            let _ = std::fs::remove_dir_all(d);
        }
    }

    pub(super) fn recover(&mut self, rs: &RenderState) {
        let Some((dir, name)) = self.recovery() else { return };
        let meta: serde_json::Value = std::fs::read_to_string(dir.join("recovery.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
        self.open_project(rs, &dir);
        if self.status.as_ref().is_some_and(|(_, e)| *e) {
            return;
        }
        // it belongs to the original project (or none): saving asks where
        self.project_dir = meta["project"].as_str().map(PathBuf::from);
        self.mesh_source = None;
        self.export_name = name.clone();
        self.modified = true;
        self.ui.toasts.push(ToastKind::Success, "Recovered your work", format!("{name}: save it to keep it."));
    }

    /// Per-frame: finish jobs, autosave when it's time.
    pub(super) fn poll_jobs(&mut self, rs: &RenderState) {
        let mut done = vec![];
        for (k, j) in self.ui.jobs.iter().enumerate() {
            match &j.kind {
                JobKind::Bake { done: flag, t0 } => {
                    if flag.load(Ordering::Acquire) {
                        done.push((k, Ok((format!("Baked in {:.1} s", t0.elapsed().as_secs_f32()), "Edge wear and dirt now follow the model's shape.".to_string())), None));
                    }
                }
                JobKind::Thread { rx, then, .. } => match rx.try_recv() {
                    Ok(r) => done.push((k, r, then.clone())),
                    Err(mpsc::TryRecvError::Disconnected) => done.push((k, Err("The worker stopped unexpectedly".into()), None)),
                    Err(mpsc::TryRecvError::Empty) => {}
                },
            }
        }
        if !self.ui.jobs.is_empty() {
            let _ = rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Poll);
        }
        for (k, r, then) in done.into_iter().rev() {
            let j = self.ui.jobs.remove(k);
            match r {
                Ok((title, body)) if !title.is_empty() => {
                    self.ui.toasts.finish(j.toast, ToastKind::Success, title.clone(), body);
                    self.set_status(title, false);
                    if let Some(dir) = then {
                        self.ui.last_export = Some(dir);
                    }
                }
                Ok(_) => {}
                Err(e) => {
                    self.ui.toasts.finish(j.toast, ToastKind::Error, "Something went wrong", e.clone());
                    self.set_status(e, true);
                }
            }
        }
        let every = self.ui.prefs.autosave_minutes;
        if every > 0.0 && self.modified && self.ui.last_autosave.elapsed().as_secs_f32() > every * 60.0 {
            self.autosave(rs);
        }
    }

    /// Block until every job is done (tests, exit).
    pub(super) fn wait_jobs(&mut self, rs: &RenderState) {
        let t0 = Instant::now();
        while !self.ui.jobs.is_empty() && t0.elapsed().as_secs() < 120 {
            let _ = rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: Some(std::time::Duration::from_millis(50)) });
            self.poll_jobs(rs);
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
}

/// Turn an error chain into something a person can act on.
pub fn friendly_error(what: &str, e: &str) -> String {
    let lower = e.to_lowercase();
    let advice = if lower.contains("access is denied") || lower.contains("permission denied") {
        " Pigment isn't allowed to write there: choose another folder."
    } else if lower.contains("no space") {
        " The disk is full."
    } else if lower.contains("cannot find the path") || lower.contains("no such file") {
        " The folder or file doesn't exist any more."
    } else if lower.contains("uv") {
        " The model needs UVs: unwrap it in Blender (U > Smart UV Project) and export again."
    } else if lower.contains("unsupported") || lower.contains("format") {
        " Pigment opens OBJ, glTF (.gltf) and GLB models."
    } else {
        ""
    };
    format!("{what}: {e}.{advice}")
}
