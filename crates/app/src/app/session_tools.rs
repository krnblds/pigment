//! UI entry points for tools that used to be MCP-only: a high-resolution
//! image of the viewport, turntable sheets and "Export all variants". They
//! lend the app to an automation `Session`, so the UI and `pigment-mcp` run
//! the same code.

use super::automation::Session;
use super::design::ToastKind;
use super::jobs;
use super::*;
use pigment_core::variants::{resolve, validate_defs, VariantDef};
use serde_json::{json, Value};

/// `dir/<stem>_001.<ext>`, the first number not taken yet.
fn next_free(dir: &Path, stem: &str, ext: &str) -> PathBuf {
    (1..10_000).map(|i| dir.join(format!("{stem}_{i:03}.{ext}"))).find(|p| !p.exists()).unwrap_or_else(|| dir.join(format!("{stem}.{ext}")))
}

/// A variant name `validate_defs` accepts: letters, digits, `_` and `-`.
pub fn variant_name(s: &str) -> String {
    let n: String = s.trim().chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' { c } else { '_' }).collect();
    if n.is_empty() { "variant".into() } else { n }
}

impl PigmentApp {
    fn asset_name(&self) -> String {
        let n = self.export_name.trim();
        if n.is_empty() { "Asset".into() } else { n.to_string() }
    }

    /// `<export folder>/<asset>/<sub>`: renders and variants sit next to the maps.
    pub(in crate::app) fn output_dir(&self, sub: &str) -> PathBuf {
        self.ui.prefs.export_dir.clone().unwrap_or_else(jobs::default_export_root).join(self.asset_name()).join(sub)
    }

    /// The orbit camera as `render` arguments, so a render matches the viewport.
    fn camera_args(&self) -> Value {
        let c = &self.camera;
        json!({ "yaw": c.yaw.to_degrees(), "pitch": c.pitch.to_degrees(), "target": [c.target.x, c.target.y, c.target.z], "distance": c.distance })
    }

    /// The current lighting as `preview` / `render` look arguments.
    fn look_args(&self) -> Value {
        match pigment_core::envmath::lighting_id(&self.env.source) {
            Some(id) => json!({ "lighting": id }),
            None if Path::new(&self.env.source).is_file() => json!({ "hdri": self.env.source }),
            None => json!({}),
        }
    }

    /// Run a session tool that renders, then put the user's camera and view back.
    fn lend_render<R>(&mut self, rs: &RenderState, f: impl FnOnce(&mut Session) -> R) -> R {
        let (camera, view) = (self.camera.clone(), self.view.clone());
        let r = Session::lend(self, rs, f);
        (self.camera, self.view) = (camera, view);
        r
    }

    /// Save the viewport (material view, no UI) as a PNG at `scale` times its
    /// size, longest side at most 4096 px.
    pub(in crate::app) fn save_render(&mut self, rs: &RenderState, scale: f32) -> Result<PathBuf, String> {
        let [w, h] = match self.viewport.size() {
            [w, h] if w >= 16 && h >= 16 => [w as f32, h as f32],
            _ => [1280.0, 960.0],
        };
        let k = scale.max(0.1).min(4096.0 / w.max(h));
        let dir = self.output_dir("renders");
        let path = next_free(&dir, &self.asset_name(), "png");
        let mut a = self.camera_args();
        a["width"] = json!((w * k).round() as u32);
        a["height"] = json!((h * k).round() as u32);
        a["path"] = json!(path);
        self.lend_render(rs, |s| s.render(&a)).map(|img| img.path)
    }

    /// Save a turntable contact sheet: `frames` views around the model,
    /// starting from the current angle.
    pub(in crate::app) fn save_turntable(&mut self, rs: &RenderState, frames: u32) -> Result<PathBuf, String> {
        let dir = self.output_dir("renders");
        let path = next_free(&dir, &format!("{}_turntable", self.asset_name()), "png");
        let c = &self.camera;
        let a = json!({ "frames": frames, "start_yaw": c.yaw.to_degrees(), "pitch": c.pitch.to_degrees(), "width": 512, "height": 512, "path": path });
        self.lend_render(rs, |s| s.render_turntable(&a)).map(|img| img.path)
    }

    /// `save_render` / `save_turntable` with a toast either way.
    pub(in crate::app) fn run_render(&mut self, rs: &RenderState, turntable: bool) {
        let (r, what) = if turntable { (self.save_turntable(rs, 8), "Turntable saved") } else { (self.save_render(rs, 2.0), "Image saved") };
        match r {
            Ok(path) => {
                self.ui.toasts.push(ToastKind::Success, what, path.display().to_string());
                self.ui.last_export = path.parent().map(Path::to_path_buf);
            }
            Err(e) => self.notify_error("Couldn't render the image", &e),
        }
    }

    /// Check the stored variant definitions; the first problem in words.
    pub(in crate::app) fn check_variants(&self) -> Result<(), String> {
        let defs = &self.doc.variants.defs;
        validate_defs(defs)?;
        defs.iter().try_for_each(|d| resolve(&self.doc, d).map(|_| ()))
    }

    /// Preview a variant in the viewport: its seed and which layers show. One
    /// undo step; decal swaps only show in the export.
    pub(in crate::app) fn preview_variant(&mut self, v: &VariantDef) -> Result<(), String> {
        let r = resolve(&self.doc, v)?;
        self.commit_doc_changes();
        self.doc.variants.seed = r.doc.variants.seed;
        for l in &mut self.doc.layers {
            if let Some(x) = r.doc.layer(l.id) {
                l.visible = x.visible;
            }
        }
        if self.doc != self.committed {
            let before = Box::new(std::mem::replace(&mut self.committed, self.doc.clone()));
            self.push_history(format!("Preview variant {}", v.name), Edit::Doc { before, after: Box::new(self.doc.clone()) });
        }
        Ok(())
    }

    /// Export every stored variant into `<export folder>/<asset>/variants`,
    /// one folder per variant with its maps, `variant.json` and a preview
    /// render in the current lighting. Returns the folder and the count.
    pub(in crate::app) fn export_all_variants(&mut self, rs: &RenderState) -> Result<(PathBuf, usize), String> {
        self.check_variants()?;
        if self.doc.variants.defs.is_empty() {
            return Err("Add a variant first.".into());
        }
        let dir = self.output_dir("variants");
        let mut preview = self.look_args();
        preview["width"] = json!(768);
        preview["height"] = json!(576);
        let a = json!({ "dir": dir, "preset": jobs::target(self.ui.export_target).preset, "name": self.asset_name(), "preview": preview });
        let out = self.lend_render(rs, |s| s.export_variants(&a))?;
        Ok((dir, out["variants"].as_array().map_or(0, Vec::len)))
    }
}
