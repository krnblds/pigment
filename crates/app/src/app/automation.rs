//! Headless automation: drive Pigment with commands instead of a mouse.
//! Used by the `pigment-mcp` server (one JSON object per tool call) and by tests.
//!
//! Every command runs through the same code paths as the UI (document edits,
//! undo history, strokes, bake, composite, save, export).

use super::*;
use crate::render::viewport::ViewMode;
use serde_json::{json, Value};

type Res<T> = Result<T, String>;

/// A GPU device without a window.
pub fn headless_render_state() -> Option<RenderState> {
    use eframe::egui_wgpu::wgpu;
    let instance = wgpu::Instance::default();
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        ..Default::default()
    }))
    .ok()?;
    let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor::default())).ok()?;
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

pub struct Session {
    pub rs: RenderState,
    pub app: PigmentApp,
    size: [u32; 2],
}

/// A rendered preview.
pub struct Image {
    pub png: Vec<u8>,
    pub path: PathBuf,
}

fn f(v: &Value, k: &str) -> Option<f32> {
    v.get(k).and_then(Value::as_f64).map(|x| x as f32)
}
fn s<'a>(v: &'a Value, k: &str) -> Option<&'a str> {
    v.get(k).and_then(Value::as_str)
}
fn req<'a>(v: &'a Value, k: &str) -> Res<&'a str> {
    s(v, k).ok_or_else(|| format!("missing string argument `{k}`"))
}

fn view_mode(name: &str) -> Res<ViewMode> {
    let n = name.to_ascii_lowercase();
    ViewMode::ALL
        .into_iter()
        .find(|m| m.label().to_ascii_lowercase().starts_with(&n) || format!("{m:?}").to_ascii_lowercase() == n)
        .ok_or_else(|| format!("`view` = \"{name}\": unknown view (one of: {})", ViewMode::ALL.iter().map(|m| m.label().to_ascii_lowercase()).collect::<Vec<_>>().join(", ")))
}

fn channel(name: &str) -> Res<Channel> {
    let n = name.to_ascii_lowercase().replace([' ', '-'], "_");
    Channel::ALL.into_iter().find(|c| c.file_stem() == n || c.label().to_ascii_lowercase().replace(' ', "_") == n).ok_or_else(|| format!("unknown channel `{name}` (one of: {})", Channel::ALL.map(|c| c.file_stem()).join(", ")))
}

fn blend_mode(name: &str) -> Res<BlendMode> {
    let n = name.to_ascii_lowercase();
    [
        BlendMode::Normal,
        BlendMode::Multiply,
        BlendMode::Screen,
        BlendMode::Overlay,
        BlendMode::Add,
        BlendMode::Subtract,
        BlendMode::Darken,
        BlendMode::Lighten,
        BlendMode::Replace,
        BlendMode::NormalCombine,
    ]
    .into_iter()
    .find(|m| m.label().to_ascii_lowercase().starts_with(&n) || format!("{m:?}").to_ascii_lowercase() == n)
    .ok_or_else(|| format!("unknown blend mode `{name}` (normal, multiply, screen, overlay, add, subtract, darken, lighten, replace, combine)"))
}

fn unknown_material(arg: &str, name: &str) -> String {
    let names: Vec<&str> = material_presets().into_iter().map(|(n, _)| n).collect();
    format!("`{arg}` = \"{name}\": unknown material preset (names are case-sensitive; one of: {})", names.join(", "))
}

fn unknown_smart_material(name: &str) -> String {
    format!("`name` / `smart_material` = \"{name}\": unknown smart material (one of: {})", smart_material_names().join(", "))
}

fn unknown_generator(arg: &str, k: &str) -> String {
    format!("`{arg}` = \"{k}\": unknown generator (one of: {})", GeneratorKind::ALL.iter().map(|g| g.id()).collect::<Vec<_>>().join(", "))
}

impl Session {
    pub fn new() -> Res<Session> {
        let rs = headless_render_state().ok_or("no GPU adapter available")?;
        let app = PigmentApp::create(&rs, None);
        Ok(Session { rs, app, size: [1280, 960] })
    }

    fn status(&self) -> Res<String> {
        match &self.app.status {
            Some((m, true)) => Err(m.clone()),
            Some((m, false)) => Ok(m.clone()),
            None => Ok(String::new()),
        }
    }

    fn settle(&mut self) {
        self.app.commit_doc_changes();
        self.app.ensure_composited(&self.rs);
    }

    // ------------------------------------------------------------------ projects

    pub fn new_project(&mut self, a: &Value) -> Res<Value> {
        let mesh = PathBuf::from(req(a, "mesh")?);
        self.app.status = None;
        if let Some(r) = a.get("resolution").and_then(Value::as_u64) {
            if !RESOLUTIONS.contains(&(r as u32)) {
                return Err(format!("resolution must be one of {RESOLUTIONS:?}"));
            }
            self.app.doc.resolution = r as u32;
        }
        self.app.open_mesh_as_new(&self.rs, &mesh);
        self.status()?;
        // start from an empty stack, then optionally a smart material and a paint layer on top
        self.app.doc.layers.clear();
        if let Some(name) = s(a, "smart_material") {
            let layers = self.app.doc.smart_material(name).ok_or_else(|| unknown_smart_material(name))?;
            self.app.doc.layers.extend(layers);
        } else {
            let base = self.app.doc.fill_with("Base", s(a, "material").unwrap_or("White plastic"), None);
            self.app.doc.layers.push(base);
        }
        let paint = self.app.doc.new_paint_layer("Paint");
        self.app.doc.layers.push(paint);
        self.app.committed = self.app.doc.clone();
        let _ = self.app.history.clear();
        self.app.select(self.app.doc.layers.last().map(|l| l.id), false);
        self.settle();
        Ok(json!({ "mesh": self.app.mesh.name, "triangles": self.app.mesh.triangle_count(), "layers": self.layers() }))
    }

    pub fn open_project(&mut self, a: &Value) -> Res<Value> {
        self.app.status = None;
        self.app.open_project(&self.rs, Path::new(req(a, "path")?));
        self.status()?;
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    pub fn save_project(&mut self, a: &Value) -> Res<Value> {
        self.settle();
        let dir = match s(a, "path") {
            Some(p) => PathBuf::from(p),
            None => self.app.project_dir.clone().ok_or("no project folder yet: pass `path` (e.g. C:/work/crate.pigment)")?,
        };
        self.app.status = None;
        self.app.save_to(&self.rs, dir.clone());
        Ok(json!({ "saved": dir, "status": self.status()? }))
    }

    // ------------------------------------------------------------------ library + layers

    pub fn library(&self) -> Value {
        json!({
            "materials": material_presets().into_iter().map(|(n, v)| json!({
                "name": n, "base_color": v.base_color, "roughness": v.roughness, "metallic": v.metallic, "height": v.height,
                "emissive": v.emissive, "emissive_strength": v.emissive_strength
            })).collect::<Vec<_>>(),
            "smart_materials": smart_material_names(),
            "generators": GeneratorKind::ALL.iter().map(|k| json!({ "id": k.id(), "label": k.label(), "uses_bakes": k.uses_bakes() })).collect::<Vec<_>>(),
            "blend_modes": ["normal", "multiply", "screen", "overlay", "add", "subtract", "darken", "lighten", "replace", "combine"],
            "export_presets": export::presets().iter().map(|p| json!({ "id": p.id, "label": p.label })).collect::<Vec<_>>(),
            "views": ViewMode::ALL.iter().map(|m| m.label()).collect::<Vec<_>>(),
        })
    }

    pub fn layers(&self) -> Value {
        Value::Array(
            self.app
                .doc
                .layers
                .iter()
                .enumerate()
                .map(|(i, l)| {
                    let mut o = json!({
                        "index": i,
                        "name": l.name,
                        "kind": if l.is_paint() { "paint" } else { "fill" },
                        "visible": l.visible,
                        "opacity": l.opacity,
                        "channels": Channel::ALL.iter().filter(|c| l.channels.get(**c).enabled).map(|c| c.file_stem()).collect::<Vec<_>>(),
                    });
                    if let LayerKind::Fill { values } = &l.kind {
                        o["material"] = json!(material_presets().into_iter().find(|(_, v)| v == values).map(|(n, _)| n).unwrap_or("custom"));
                    }
                    if let Some(m) = &l.mask {
                        o["mask"] = json!({
                            "generator": m.generator.as_ref().map(|g| json!({
                                "kind": g.kind.id(), "amount": g.amount, "softness": g.softness, "scale": g.noise_scale,
                                "breakup": g.noise_amount, "seed": g.seed, "ao_influence": g.ao_influence, "curvature_weight": g.curvature_weight
                            })),
                            "effects": m.effects.iter().map(|e| json!({ "generator": e.generator.kind.id(), "op": format!("{:?}", e.op).to_lowercase(), "amount": e.generator.amount, "scale": e.generator.noise_scale })).collect::<Vec<_>>(),
                            "parts": m.parts,
                            "invert": m.invert,
                        });
                    }
                    o
                })
                .collect(),
        )
    }

    fn find_layer(&self, r: &Value) -> Res<usize> {
        match r {
            Value::Number(n) => {
                let i = n.as_u64().ok_or("`layer` index must be >= 0")? as usize;
                let len = self.app.doc.layers.len();
                (i < len).then_some(i).ok_or_else(|| format!("`layer` = {i}: no such layer (indices 0..{}, 0 = bottom)", len.saturating_sub(1)))
            }
            Value::String(name) => {
                let n = name.to_ascii_lowercase();
                // last match = the topmost layer with that name
                self.app.doc.layers.iter().rposition(|l| l.name.to_ascii_lowercase() == n).ok_or_else(|| {
                    let names: Vec<&str> = self.app.doc.layers.iter().map(|l| l.name.as_str()).collect();
                    format!("`layer` = \"{name}\": no layer with that name (layers bottom to top: {})", names.join(", "))
                })
            }
            _ => Err("`layer` must be a name or an index (0 = bottom)".into()),
        }
    }

    /// Apply the optional layer fields of `a` to layer `i`.
    fn configure(&mut self, i: usize, a: &Value) -> Res<()> {
        let rs = &self.rs;
        let app = &mut self.app;
        if let Some(n) = s(a, "name") {
            app.doc.layers[i].name = n.to_string();
        }
        if let Some(o) = f(a, "opacity") {
            app.doc.layers[i].opacity = o.clamp(0.0, 1.0);
        }
        if let Some(v) = a.get("visible").and_then(Value::as_bool) {
            app.doc.layers[i].visible = v;
        }
        if let Some(name) = s(a, "material") {
            if !material_presets().iter().any(|(n, _)| *n == name) {
                return Err(unknown_material("material", name));
            }
            let values = material_preset(name);
            let l = &mut app.doc.layers[i];
            let LayerKind::Fill { values: v } = &mut l.kind else { return Err("`material` applies to fill layers".into()) };
            *v = values.clone();
            if values.height.abs() > 1e-3 {
                l.channels.height.enabled = true;
            }
            l.channels.emissive.enabled = values.emissive_strength > 0.0;
        }
        if let Some(vals) = a.get("values") {
            let l = &mut app.doc.layers[i];
            let LayerKind::Fill { values: v } = &mut l.kind else { return Err("`values` apply to fill layers".into()) };
            let mut height_set = false;
            if let Some(c) = vals.get("base_color").and_then(Value::as_array) {
                for (k, x) in c.iter().take(3).enumerate() {
                    v.base_color[k] = x.as_f64().unwrap_or(0.0).clamp(0.0, 1.0) as f32;
                }
            }
            if let Some(x) = f(vals, "roughness") {
                v.roughness = x.clamp(0.0, 1.0);
            }
            if let Some(x) = f(vals, "metallic") {
                v.metallic = x.clamp(0.0, 1.0);
            }
            if let Some(x) = f(vals, "height") {
                v.height = x.clamp(-1.0, 1.0);
                height_set = true;
            }
            if let Some(c) = vals.get("emissive").and_then(Value::as_array) {
                for (k, x) in c.iter().take(3).enumerate() {
                    v.emissive[k] = x.as_f64().unwrap_or(0.0).clamp(0.0, 1.0) as f32;
                }
            }
            if let Some(x) = f(vals, "emissive_strength") {
                v.emissive_strength = x.max(0.0);
            }
            let glows = v.emissive_strength > 0.0;
            l.channels.emissive.enabled = glows;
            if height_set {
                l.channels.height.enabled = true;
            }
        }
        if let Some(chs) = a.get("channels").and_then(Value::as_object) {
            for (k, on) in chs {
                let c = channel(k)?;
                app.doc.layers[i].channels.get_mut(c).enabled = on.as_bool().unwrap_or(true);
            }
        }
        if let Some(bl) = a.get("blend").and_then(Value::as_object) {
            for (k, m) in bl {
                let c = channel(k)?;
                app.doc.layers[i].channels.get_mut(c).blend = blend_mode(m.as_str().unwrap_or("normal"))?;
            }
        }
        match a.get("mask") {
            None => {}
            Some(Value::Null) => app.doc.layers[i].mask = None,
            Some(Value::String(c)) => {
                let white = match c.as_str() {
                    "white" => true,
                    "black" => false,
                    _ => return Err("mask must be \"white\", \"black\", null or {generator: ...}".into()),
                };
                let res = app.doc.mint();
                app.ts.new_mask(&rs.device, &rs.queue, res, white);
                app.doc.layers[i].mask = Some(Mask::new(res));
            }
            Some(m) => {
                let kind = match s(m, "generator") {
                    Some(k) => Some(GeneratorKind::from_id(k).ok_or_else(|| unknown_generator("mask.generator", k))?),
                    None => None,
                };
                if app.doc.layers[i].mask.is_none() {
                    let res = app.doc.mint();
                    app.ts.new_mask(&rs.device, &rs.queue, res, true);
                    app.doc.layers[i].mask = Some(Mask::new(res));
                }
                let mask = app.doc.layers[i].mask.as_mut().unwrap();
                if let Some(k) = kind {
                    if mask.generator.as_ref().map(|g| g.kind) != Some(k) {
                        mask.generator = Some(Generator::new(k));
                    }
                }
                if let Some(inv) = m.get("invert").and_then(Value::as_bool) {
                    mask.invert = inv;
                }
                if let Some(ps) = m.get("parts") {
                    let n = app.parts.info.len();
                    let ps = ps.as_array().ok_or("`mask.parts` must be an array of part ids (see list_parts)")?;
                    let mut ids = Vec::with_capacity(ps.len());
                    for (k, p) in ps.iter().enumerate() {
                        let id = p.as_u64().ok_or_else(|| format!("`mask.parts[{k}]` must be a part id (integer >= 0), got {p}"))?;
                        if id as usize >= n {
                            return Err(format!("`mask.parts[{k}]` = {id}: no such part (the mesh has {n} parts, ids 0..{})", n.saturating_sub(1)));
                        }
                        if id >= MAX_SELECTABLE_PARTS as u64 {
                            return Err(format!("`mask.parts[{k}]` = {id}: part masks support ids below {MAX_SELECTABLE_PARTS}"));
                        }
                        ids.push(id as u32);
                    }
                    ids.sort_unstable();
                    ids.dedup();
                    mask.parts = ids;
                }
                if let Some(effs) = m.get("effects").and_then(Value::as_array) {
                    if effs.len() > MAX_MASK_EFFECTS {
                        return Err(format!("at most {MAX_MASK_EFFECTS} extra effects"));
                    }
                    mask.effects.clear();
                    for e in effs {
                        let k = s(e, "generator").ok_or("each effect needs `generator`")?;
                        let mut g = Generator::new(GeneratorKind::from_id(k).ok_or_else(|| unknown_generator("mask.effects[].generator", k))?);
                        apply_generator_fields(&mut g, e);
                        let op = match s(e, "op") {
                            Some(o) => MaskOp::from_id(o).ok_or_else(|| format!("unknown op `{o}` (multiply, add, subtract, max, min)"))?,
                            None => MaskOp::Multiply,
                        };
                        mask.effects.push(MaskEffect { generator: g, op });
                    }
                }
                if let Some(g) = mask.generator.as_mut() {
                    apply_generator_fields(g, m);
                }
            }
        }
        Ok(())
    }

    /// Connected pieces of the mesh, for part masks.
    pub fn list_parts(&self) -> Value {
        Value::Array(
            self.app
                .parts
                .info
                .iter()
                .enumerate()
                .map(|(i, p)| {
                    let c: Vec<f32> = (0..3).map(|k| (p.min[k] + p.max[k]) * 0.5).collect();
                    let sz: Vec<f32> = (0..3).map(|k| p.max[k] - p.min[k]).collect();
                    json!({ "id": i, "triangles": p.triangles, "center": c, "size": sz })
                })
                .collect(),
        )
    }

    /// Which parts are under viewport points (0..1) for a camera view.
    pub fn pick_parts(&mut self, a: &Value) -> Res<Value> {
        match (a.get("points"), a.get("shape")) {
            (Some(_), Some(_)) => return Err("pick_parts takes either `points` (viewport picking) or `shape` (a shape query), not both".into()),
            (None, Some(shape)) => return self.pick_parts_by_shape(shape),
            (None, None) => return Err("pick_parts needs `points` ([[x, y], ...] in 0..1 for a camera view) or `shape` (e.g. {\"max_thickness\": 0.02, \"min_area\": 1.0})".into()),
            _ => {}
        }
        self.set_camera(a);
        let px = Vec2::new(self.size[0] as f32, self.size[1] as f32);
        let pts = a.get("points").and_then(Value::as_array).ok_or("`points` must be an array of [x, y] in 0..1")?;
        let mut out = Vec::new();
        for (i, p) in pts.iter().enumerate() {
            let xy = p.as_array().filter(|p| p.len() == 2 && p.iter().all(Value::is_number)).ok_or_else(|| format!("`points[{i}]` must be [x, y] (numbers in 0..1), got {p}"))?;
            let v = Vec2::new(xy[0].as_f64().unwrap_or(0.0) as f32, xy[1].as_f64().unwrap_or(0.0) as f32);
            out.push(self.app.part_at(v * px, px).map(Value::from).unwrap_or(Value::Null));
        }
        Ok(json!({ "parts": out }))
    }

    pub fn add_smart_material(&mut self, a: &Value) -> Res<Value> {
        let name = req(a, "name")?;
        let layers = self.app.doc.smart_material(name).ok_or_else(|| unknown_smart_material(name))?;
        // insert below the topmost paint layer so painting stays on top
        let at = self.app.doc.layers.iter().rposition(|l| l.is_paint()).unwrap_or(self.app.doc.layers.len());
        for (k, l) in layers.into_iter().enumerate() {
            self.app.doc.layers.insert(at + k, l);
        }
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    pub fn add_layer(&mut self, a: &Value) -> Res<Value> {
        let kind = s(a, "kind").unwrap_or("fill");
        let name = s(a, "name").unwrap_or(if kind == "paint" { "Paint" } else { "Fill" }).to_string();
        let l = match kind {
            "paint" => self.app.doc.new_paint_layer(&name),
            "fill" => self.app.doc.fill_with(&name, s(a, "material").unwrap_or("White plastic"), None),
            _ => return Err("`kind` must be \"fill\" or \"paint\"".into()),
        };
        let at = match a.get("index").and_then(Value::as_u64) {
            Some(i) => (i as usize).min(self.app.doc.layers.len()),
            None if kind == "paint" => self.app.doc.layers.len(),
            None => self.app.doc.layers.iter().rposition(|l| l.is_paint()).unwrap_or(self.app.doc.layers.len()),
        };
        self.app.doc.layers.insert(at, l);
        let mut cfg = a.clone();
        if let Some(o) = cfg.as_object_mut() {
            o.remove("name");
        }
        if let Err(e) = self.configure(at, &cfg) {
            self.app.doc.layers.remove(at);
            return Err(e);
        }
        self.settle();
        Ok(json!({ "added": at, "layers": self.layers() }))
    }

    pub fn update_layer(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer` (a layer name or index, 0 = bottom; see list_layers)")?)?;
        self.configure(i, a)?;
        if let Some(to) = a.get("move_to").and_then(Value::as_u64) {
            let l = self.app.doc.layers.remove(i);
            let to = (to as usize).min(self.app.doc.layers.len());
            self.app.doc.layers.insert(to, l);
        }
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    pub fn delete_layer(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer` (a layer name or index, 0 = bottom; see list_layers)")?)?;
        self.app.doc.layers.remove(i);
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    pub fn undo(&mut self, redo: bool) -> Res<Value> {
        self.app.undo(&self.rs, redo);
        self.settle();
        Ok(json!({ "status": self.status()?, "layers": self.layers() }))
    }

    pub fn bake(&mut self, a: &Value) -> Res<Value> {
        let b = &mut self.app.doc.bake;
        if let Some(n) = a.get("ao_samples").and_then(Value::as_u64) {
            b.ao_samples = (n as u32).clamp(8, 1024);
        }
        if let Some(x) = f(a, "ao_distance") {
            b.ao_distance = x;
        }
        if let Some(x) = f(a, "curvature_radius") {
            b.curvature_radius = x;
        }
        if let Some(x) = f(a, "curvature_strength") {
            b.curvature_strength = x;
        }
        self.app.bake(&self.rs);
        self.settle();
        Ok(json!({ "status": self.status()? }))
    }

    // ------------------------------------------------------------------ camera, painting, output

    fn set_camera(&mut self, a: &Value) {
        let (c, r) = self.app.mesh.bounding_sphere();
        let cam = &mut self.app.camera;
        cam.frame(c, r);
        cam.yaw = f(a, "yaw").map(|d| d.to_radians()).unwrap_or(35f32.to_radians());
        cam.pitch = f(a, "pitch").map(|d| d.to_radians()).unwrap_or(20f32.to_radians());
        cam.distance *= f(a, "zoom").map(|z| 1.0 / z.max(0.05)).unwrap_or(1.0);
        if let Some(w) = a.get("width").and_then(Value::as_u64) {
            self.size[0] = (w as u32).clamp(64, 4096);
        }
        if let Some(h) = a.get("height").and_then(Value::as_u64) {
            self.size[1] = (h as u32).clamp(64, 4096);
        }
    }

    /// Point the camera straight at a part's outward-facing broad face (its
    /// thinnest axis, on the side away from the model's centre) and return the
    /// viewport rect (0..1) covering it, shrunk to the image's aspect for
    /// `fit = "contain"` or stretched for `"fill"`.
    fn aim_at_part(&mut self, part: u32, image: &Path, fit: &str, margin: f32) -> Res<Vec<f32>> {
        let info = *self.app.parts.info.get(part as usize).ok_or_else(|| format!("no part {part}"))?;
        let (lo, hi) = (glam::Vec3::from(info.min), glam::Vec3::from(info.max));
        let c = (lo + hi) * 0.5;
        let size = hi - lo;
        let axis = if size.x <= size.y && size.x <= size.z { 0 } else if size.y <= size.z { 1 } else { 2 };
        let (mc, _) = self.app.mesh.bounding_sphere();
        let outward = if c[axis] >= mc[axis] { 1.0 } else { -1.0 };
        let cam = &mut self.app.camera;
        cam.target = c;
        // OrbitCamera: eye = target + (sin yaw cos p, sin p, cos yaw cos p) * d
        (cam.yaw, cam.pitch) = match (axis, outward > 0.0) {
            (0, true) => (std::f32::consts::FRAC_PI_2, 0.0),
            (0, false) => (-std::f32::consts::FRAC_PI_2, 0.0),
            (2, true) => (0.0, 0.0),
            (2, false) => (std::f32::consts::PI, 0.0),
            (_, true) => (0.0, 1.5),
            (_, false) => (0.0, -1.5),
        };
        let extent = size.length().max(0.05);
        cam.distance = extent / (cam.fov_y * 0.5).tan() * 0.75;
        self.size = [1024, 1024];
        let vp = cam.view_proj(1.0);
        let (mut x0, mut y0, mut x1, mut y1) = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
        for k in 0..8 {
            let p = glam::Vec3::new(if k & 1 == 0 { lo.x } else { hi.x }, if k & 2 == 0 { lo.y } else { hi.y }, if k & 4 == 0 { lo.z } else { hi.z });
            let q = vp.project_point3(p);
            let (u, v) = (q.x * 0.5 + 0.5, 0.5 - q.y * 0.5);
            x0 = x0.min(u);
            y0 = y0.min(v);
            x1 = x1.max(u);
            y1 = y1.max(v);
        }
        let (w, h) = ((x1 - x0) * (1.0 - 2.0 * margin), (y1 - y0) * (1.0 - 2.0 * margin));
        let (cx, cy) = ((x0 + x1) * 0.5, (y0 + y1) * 0.5);
        let (mut w, mut h) = (w, h);
        if fit == "contain" {
            if let Ok((iw, ih)) = image::image_dimensions(image) {
                let ar = iw as f32 / ih as f32;
                if w / h > ar {
                    w = h * ar;
                } else {
                    h = w / ar;
                }
            }
        }
        Ok(vec![cx - w * 0.5, cy - h * 0.5, cx + w * 0.5, cy + h * 0.5])
    }

    fn draw(&mut self) {
        self.app.viewport.ensure_targets(&self.rs.device, self.size);
        self.app.viewport.draw(&self.rs.device, &self.rs.queue, &self.app.camera, &self.app.view, self.app.mesh_gpu.as_ref(), &self.app.env, &self.app.ts);
    }

    /// Paint one stroke. `points` are viewport positions in 0..1 (x right, y down)
    /// for a camera given by yaw / pitch / zoom (degrees; same as `render`).
    pub fn paint_stroke(&mut self, a: &Value) -> Res<Value> {
        let pts: Vec<Vec2> = a
            .get("points")
            .and_then(Value::as_array)
            .ok_or("missing `points`: [[x, y], ...] in 0..1")?
            .iter()
            .filter_map(|p| {
                let p = p.as_array()?;
                Some(Vec2::new(p.first()?.as_f64()? as f32, p.get(1)?.as_f64()? as f32))
            })
            .collect();
        if pts.is_empty() {
            return Err("`points` is empty".into());
        }
        self.set_camera(a);
        // target layer: given, else the topmost paint layer (created if missing)
        let i = match a.get("layer") {
            Some(r) => self.find_layer(r)?,
            None => match self.app.doc.layers.iter().rposition(|l| l.is_paint()) {
                Some(i) => i,
                None => {
                    let l = self.app.doc.new_paint_layer("Paint");
                    self.app.doc.layers.push(l);
                    self.app.doc.layers.len() - 1
                }
            },
        };
        let id = self.app.doc.layers[i].id;
        let on_mask = a.get("mask").and_then(Value::as_bool).unwrap_or(false);
        self.app.select(Some(id), on_mask);
        self.settle();
        let b = &mut self.app.brush;
        if let Some(name) = s(a, "material") {
            if !material_presets().iter().any(|(n, _)| *n == name) {
                return Err(unknown_material("material", name));
            }
            b.values = material_preset(name);
            b.channels = [true, true, true, b.values.height.abs() > 1e-3, false, b.values.emissive_strength > 0.0];
        }
        if let Some(chs) = a.get("channels").and_then(Value::as_array) {
            b.channels = [false; 6];
            for c in chs.iter().filter_map(Value::as_str) {
                b.channels[channel(c)?.index()] = true;
            }
        }
        if let Some(h) = f(a, "height") {
            b.values.height = h;
            b.channels[3] = true;
        }
        b.size = f(a, "size").unwrap_or(40.0);
        b.opacity = f(a, "opacity").unwrap_or(1.0);
        b.hardness = f(a, "hardness").unwrap_or(0.6);
        b.spacing = 0.1;
        b.erase = a.get("erase").and_then(Value::as_bool).unwrap_or(false);
        b.mask_white = s(a, "mask_value").unwrap_or("white") != "black";
        self.app.ppp = 1.0;
        self.draw();
        let px = Vec2::new(self.size[0] as f32, self.size[1] as f32);
        let to_px = |p: Vec2| p * px;
        self.app.begin_stroke(&self.rs, to_px(pts[0]), px);
        if self.app.stroke.is_none() {
            return Err(self.status().err().unwrap_or_else(|| "couldn't start the stroke".into()));
        }
        let spacing = (self.app.brush.size * self.app.brush.spacing).max(1.0);
        for p in &pts[1..] {
            let stamps = self.app.stroke.as_mut().map(|st| st.sampler.move_to(to_px(*p), spacing)).unwrap_or_default();
            self.app.apply_stamps(&self.rs, stamps);
        }
        self.app.end_stroke(&self.rs);
        self.settle();
        Ok(json!({ "painted_on": self.app.doc.layers[i].name, "mask": on_mask }))
    }

    /// Project an image (decal) onto the model from a camera view, over a
    /// viewport rectangle `rect` = [x0, y0, x1, y1] in 0..1.
    pub fn project_decal(&mut self, a: &Value) -> Res<Value> {
        let image = PathBuf::from(req(a, "image")?);
        let rect: Vec<f32> = match a.get("part").and_then(Value::as_u64) {
            // aim at a mesh part's outward face and fit the image to it
            Some(part) => self.aim_at_part(part as u32, &image, s(a, "fit").unwrap_or("contain"), f(a, "margin").unwrap_or(0.05))?,
            None => {
                let r: Vec<f32> = a.get("rect").and_then(Value::as_array).ok_or("missing `rect` ([x0, y0, x1, y1] in 0..1) or `part`")?.iter().filter_map(|v| v.as_f64().map(|x| x as f32)).collect();
                if r.len() != 4 {
                    return Err("`rect` needs 4 numbers".into());
                }
                self.set_camera(a);
                r
            }
        };
        let i = match a.get("layer") {
            Some(r) => self.find_layer(r)?,
            None => match self.app.doc.layers.iter().rposition(|l| l.is_paint()) {
                Some(i) => i,
                None => {
                    let l = self.app.doc.new_paint_layer("Decals");
                    self.app.doc.layers.push(l);
                    self.app.doc.layers.len() - 1
                }
            },
        };
        let id = self.app.doc.layers[i].id;
        self.app.select(Some(id), a.get("mask").and_then(Value::as_bool).unwrap_or(false));
        self.settle();
        let b = &mut self.app.brush;
        b.values = match s(a, "material") {
            Some(m) if !material_presets().iter().any(|(n, _)| *n == m) => return Err(unknown_material("material", m)),
            Some(m) => material_preset(m),
            None => MaterialValues { base_color: [1.0; 3], roughness: 0.4, ..Default::default() },
        };
        if let Some(t) = a.get("tint").and_then(Value::as_array) {
            for (k, x) in t.iter().take(3).enumerate() {
                b.values.base_color[k] = x.as_f64().unwrap_or(1.0) as f32;
            }
        }
        b.channels = [true, true, true, false, false, false];
        if let Some(e) = f(a, "emissive_strength") {
            b.values.emissive = b.values.base_color;
            b.values.emissive_strength = e;
            b.channels[5] = e > 0.0;
        }
        if let Some(h) = f(a, "height") {
            b.values.height = h;
            b.channels[3] = true;
        }
        if let Some(chs) = a.get("channels").and_then(Value::as_array) {
            b.channels = [false; 6];
            for c in chs.iter().filter_map(Value::as_str) {
                b.channels[channel(c)?.index()] = true;
            }
        }
        b.opacity = f(a, "opacity").unwrap_or(1.0);
        b.erase = false;
        b.mask_white = s(a, "mask_value").unwrap_or("white") != "black";
        self.draw();
        let px = Vec2::new(self.size[0] as f32, self.size[1] as f32);
        let r = [rect[0] * px.x, rect[1] * px.y, rect[2] * px.x, rect[3] * px.y];
        let lum = a.get("alpha_from_luminance").and_then(Value::as_bool).unwrap_or(false);
        self.app.project_decal(&self.rs, &image, r, px, lum)?;
        self.settle();
        Ok(json!({ "decal": image, "on": self.app.doc.layers[i].name }))
    }

    pub fn render(&mut self, a: &Value) -> Res<Image> {
        self.settle();
        self.set_camera(a);
        if let Some(v) = s(a, "view") {
            self.app.view.mode = view_mode(v)?;
        } else {
            self.app.view.mode = ViewMode::Material;
        }
        if let Some(x) = f(a, "exposure") {
            self.app.view.exposure = x;
        }
        if let Some(bg) = a.get("background").and_then(Value::as_bool) {
            self.app.view.show_env = bg;
        }
        self.draw();
        let rgba = crate::render::gpu::readback(&self.rs.device, &self.rs.queue, self.app.viewport.color().ok_or("no viewport")?);
        let mut png = Vec::new();
        image::codecs::png::PngEncoder::new(&mut png)
            .write_image(&rgba, self.size[0], self.size[1], image::ExtendedColorType::Rgba8)
            .map_err(|e| e.to_string())?;
        let path = match s(a, "path") {
            Some(p) => PathBuf::from(p),
            None => std::env::temp_dir().join("pigment-mcp").join(format!("render-{}.png", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0))),
        };
        if let Some(d) = path.parent() {
            std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        std::fs::write(&path, &png).map_err(|e| e.to_string())?;
        Ok(Image { png, path })
    }

    pub fn export_textures(&mut self, a: &Value) -> Res<Value> {
        self.settle();
        let dir = PathBuf::from(req(a, "dir")?);
        let preset = s(a, "preset").unwrap_or("separate");
        if export::preset(preset).is_none() {
            return Err(format!("unknown preset `{preset}`: unreal, unity, godot, separate"));
        }
        let compression = match a.get("compression") {
            None => export::Compression::default(),
            Some(c) => c.as_str().and_then(export::Compression::from_id).ok_or_else(|| {
                format!("`compression` = {c}: expected one of {}", export::Compression::ALL.map(|c| c.id()).join(", "))
            })?,
        };
        self.app.doc.export_preset = preset.to_string();
        self.app.export_dir = Some(dir.clone());
        self.app.export_name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        self.app.export_compression = compression;
        self.app.status = None;
        self.app.export(&self.rs);
        let msg = self.status()?;
        let [wait_ms, read_ms, encode_ms, total_ms] = self.app.last_export_ms.map(|x| (x * 10.0).round() / 10.0);
        let scale = self.app.last_emissive_scale;
        let files: Vec<String> = export::preset(preset)
            .unwrap()
            .outputs
            .iter()
            .map(|o| dir.join(format!("{}_{}.png", self.app.export_name, o.suffix)).to_string_lossy().to_string())
            .collect();
        Ok(json!({ "status": msg, "files": files, "emissive_scale": scale, "compression": compression.id(),
                   "timing_ms": { "gpu_finish": wait_ms, "read_back": read_ms, "encode": encode_ms, "total": total_ms } }))
    }
}

// ---------------------------------------------------------------------- part queries, project info

use pigment_core::partquery::{PartQuery, Range, Shape, SortKey, AXES};

/// Keys of a part shape query (list_parts filters, pick_parts `shape`).
pub const PART_QUERY_KEYS: [&str; 17] = [
    "min_triangles", "max_triangles", "min_thickness", "max_thickness", "min_width", "max_width", "min_length", "max_length",
    "min_area", "max_area", "min_volume", "max_volume", "facing", "inside", "ids", "min_size", "max_size",
];
/// Paging / output keys shared by list_parts and pick_parts `shape`.
pub const PART_LIST_KEYS: [&str; 5] = ["sort", "order", "limit", "offset", "ids_only"];

fn num(a: &Value, k: &str, path: &str) -> Res<Option<f32>> {
    match a.get(k) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => v.as_f64().map(|x| Some(x as f32)).ok_or_else(|| format!("`{path}{k}` must be a number, got {v}")),
    }
}

fn range(a: &Value, what: &str, path: &str) -> Res<Range> {
    Ok(Range { min: num(a, &format!("min_{what}"), path)?, max: num(a, &format!("max_{what}"), path)? })
}

/// Parse a part shape query. `path` prefixes argument names in errors ("shape.").
pub fn part_query(a: &Value, path: &str) -> Res<PartQuery> {
    let mut q = PartQuery {
        triangles: range(a, "triangles", path)?,
        thickness: range(a, "thickness", path)?,
        width: range(a, "width", path)?,
        length: range(a, "length", path)?,
        area: range(a, "area", path)?,
        volume: range(a, "volume", path)?,
        ..Default::default()
    };
    // min_size / max_size: the longest side (alias of min_length / max_length)
    let size = range(a, "size", path)?;
    q.length.min = q.length.min.or(size.min);
    q.length.max = q.length.max.or(size.max);
    if let Some(v) = a.get("facing") {
        let f = v.as_str().map(|s| s.to_ascii_lowercase());
        q.facing = Some(AXES.iter().position(|x| Some(*x) == f.as_deref()).ok_or_else(|| format!("`{path}facing` must be \"x\", \"y\" or \"z\" (the axis of the part's thinnest side), got {v}"))?);
    }
    if let Some(v) = a.get("inside") {
        let bad = || format!("`{path}inside` must be [[x0, y0, z0], [x1, y1, z1]] (null = unbounded), got {v}");
        let corners = v.as_array().filter(|c| c.len() == 2).ok_or_else(bad)?;
        let mut out = [[f32::NEG_INFINITY; 3], [f32::INFINITY; 3]];
        for (c, corner) in corners.iter().enumerate() {
            let xs = corner.as_array().filter(|x| x.len() == 3).ok_or_else(bad)?;
            for (k, x) in xs.iter().enumerate() {
                if !x.is_null() {
                    out[c][k] = x.as_f64().ok_or_else(bad)? as f32;
                }
            }
        }
        q.inside = Some((out[0], out[1]));
    }
    if let Some(v) = a.get("ids") {
        let ids = v.as_array().ok_or_else(|| format!("`{path}ids` must be an array of part ids"))?;
        q.ids = Some(ids.iter().enumerate().map(|(i, x)| x.as_u64().map(|x| x as u32).ok_or_else(|| format!("`{path}ids[{i}]` must be a part id, got {x}"))).collect::<Res<_>>()?);
    }
    Ok(q)
}

fn r3(x: f32) -> f64 {
    (x as f64 * 1000.0).round() / 1000.0
}

impl Session {
    /// `list_parts` with optional shape filters, sorting and paging. With no
    /// arguments it returns the plain array of every part (as before).
    pub fn list_parts_query(&self, a: &Value) -> Res<Value> {
        let has_any = a.as_object().is_some_and(|o| !o.is_empty());
        if !has_any {
            return Ok(self.list_parts());
        }
        self.query_parts(a, "")
    }

    fn query_parts(&self, a: &Value, path: &str) -> Res<Value> {
        let q = part_query(a, path)?;
        let sort = match a.get("sort") {
            None => SortKey::Id,
            Some(v) => v.as_str().and_then(SortKey::from_id).ok_or_else(|| {
                format!("`{path}sort` = {v}: expected one of {}", SortKey::ALL.iter().map(|(n, _)| *n).collect::<Vec<_>>().join(", "))
            })?,
        };
        // biggest first unless asked otherwise (except for ids)
        let descending = match a.get("order").map(|v| (v, v.as_str())) {
            None => sort != SortKey::Id,
            Some((_, Some("desc"))) => true,
            Some((_, Some("asc"))) => false,
            Some((v, _)) => return Err(format!("`{path}order` must be \"asc\" or \"desc\", got {v}")),
        };
        let int = |k: &str| -> Res<Option<usize>> {
            match a.get(k) {
                None => Ok(None),
                Some(v) => v.as_u64().map(|x| Some(x as usize)).ok_or_else(|| format!("`{path}{k}` must be an integer >= 0, got {v}")),
            }
        };
        let (limit, offset) = (int("limit")?, int("offset")?.unwrap_or(0));
        let ids_only = a.get("ids_only").and_then(Value::as_bool).unwrap_or(false);
        let info = &self.app.parts.info;
        let hits = q.run(info, sort, descending);
        let page: Vec<usize> = hits.iter().copied().skip(offset).take(limit.unwrap_or(usize::MAX)).collect();
        let parts: Vec<Value> = page
            .iter()
            .map(|&i| {
                if ids_only {
                    return json!(i);
                }
                let p = &info[i];
                let s = Shape::of(p);
                json!({
                    "id": i, "triangles": p.triangles,
                    "center": s.center.map(r3), "size": s.size.map(r3),
                    "thickness": r3(s.thickness), "area": r3(s.area), "facing": AXES[s.facing],
                })
            })
            .collect();
        Ok(json!({ "total_parts": info.len(), "matched": hits.len(), "returned": parts.len(), "offset": offset, "parts": parts }))
    }

    /// `pick_parts` by shape: `shape` holds a part query (see list_parts).
    pub fn pick_parts_by_shape(&self, shape: &Value) -> Res<Value> {
        if !shape.is_object() {
            return Err(format!("`shape` must be an object of filters, e.g. {{\"max_thickness\": 0.02, \"min_area\": 1.0}}, got {shape}"));
        }
        if let Some(k) = shape.as_object().unwrap().keys().find(|k| !PART_QUERY_KEYS.contains(&k.as_str()) && !PART_LIST_KEYS.contains(&k.as_str())) {
            return Err(format!("unknown argument `shape.{k}`; accepted: {}, {}", PART_QUERY_KEYS.join(", "), PART_LIST_KEYS.join(", ")));
        }
        let mut s = shape.clone();
        s["ids_only"] = json!(true);
        let r = self.query_parts(&s, "shape.")?;
        Ok(json!({ "parts": r["parts"], "count": r["matched"] }))
    }

    /// One-call overview of the session: mesh, resolution, parts, layers,
    /// bake status, project folder and the last export.
    pub fn project_info(&self) -> Value {
        let app = &self.app;
        let m = &app.mesh;
        let (mut lo, mut hi) = ([f32::MAX; 3], [f32::MIN; 3]);
        for v in &m.vertices {
            for k in 0..3 {
                lo[k] = lo[k].min(v.position[k]);
                hi[k] = hi[k].max(v.position[k]);
            }
        }
        let loaded = !m.vertices.is_empty();
        let part_layers: Vec<Value> = app
            .doc
            .layers
            .iter()
            .filter_map(|l| l.mask.as_ref().filter(|mk| !mk.parts.is_empty()).map(|mk| json!({ "layer": l.name, "parts": mk.parts.len(), "max_id": mk.parts.iter().max() })))
            .collect();
        json!({
            "mesh": if loaded { json!({
                "name": m.name, "source": app.mesh_source, "triangles": m.triangle_count(), "vertices": m.vertices.len(), "has_uvs": m.has_uvs,
                "bounds": { "min": lo.map(r3), "max": hi.map(r3) }, "size": ([0, 1, 2].map(|k| r3(hi[k] - lo[k]))),
            }) } else { Value::Null },
            "resolution": app.doc.resolution,
            "parts": { "count": app.parts.info.len(), "max_selectable": MAX_SELECTABLE_PARTS, "masked_layers": part_layers },
            "layers": {
                "count": app.doc.layers.len(),
                "visible": app.doc.layers.iter().filter(|l| l.visible).count(),
                "paint": app.doc.layers.iter().filter(|l| l.is_paint()).count(),
                "masked": app.doc.layers.iter().filter(|l| l.mask.is_some()).count(),
                "names": app.doc.layers.iter().map(|l| l.name.clone()).collect::<Vec<_>>(),
            },
            "bake": { "baked": app.ts.baked, "settings": serde_json::to_value(&app.doc.bake).unwrap_or(Value::Null) },
            "project_dir": app.project_dir,
            "modified": app.modified,
            "undo_steps": app.history.len(),
            "export": { "preset": app.doc.export_preset, "name": app.export_name, "dir": app.export_dir, "compression": app.export_compression.id(),
                        "last_timing_ms": { "gpu_finish": r3(app.last_export_ms[0] as f32), "read_back": r3(app.last_export_ms[1] as f32), "encode": r3(app.last_export_ms[2] as f32), "total": r3(app.last_export_ms[3] as f32) } },
            "gpu_memory_mb": (app.ts.vram_bytes() as f64 / (1024.0 * 1024.0)).round(),
        })
    }
}

use image::ImageEncoder;

fn apply_generator_fields(g: &mut Generator, m: &Value) {
    if let Some(x) = f(m, "amount") {
        g.amount = x;
    }
    if let Some(x) = f(m, "softness") {
        g.softness = x;
    }
    if let Some(x) = f(m, "scale") {
        g.noise_scale = x;
    }
    if let Some(x) = f(m, "breakup") {
        g.noise_amount = x;
    }
    if let Some(x) = m.get("seed").and_then(Value::as_u64) {
        g.seed = x as u32;
    }
    if let Some(x) = f(m, "ao_influence") {
        g.ao_influence = x;
    }
    if let Some(x) = f(m, "curvature_weight") {
        g.curvature_weight = x;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scripted_session_builds_a_material_and_exports() {
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mesh = root.join("assets/ammo_box.glb");
        let r = s.new_project(&json!({ "mesh": mesh, "resolution": 512, "smart_material": "Hazard stripes" })).unwrap();
        assert!(r["layers"].as_array().unwrap().len() >= 5, "{r}");
        s.add_layer(&json!({ "kind": "fill", "name": "Seams", "material": "Panel seam", "mask": { "generator": "panel_lines", "scale": 4.0 } })).unwrap();
        s.update_layer(&json!({ "layer": "Seams", "opacity": 0.8 })).unwrap();
        assert!(s.update_layer(&json!({ "layer": "Nope" })).is_err());
        let p = s.paint_stroke(&json!({ "points": [[0.3, 0.5], [0.7, 0.45]], "material": "Neon pink plastic", "size": 30 })).unwrap();
        assert_eq!(p["painted_on"], "Paint");
        let img = s.render(&json!({ "yaw": 30, "pitch": 20, "width": 320, "height": 240 })).unwrap();
        assert!(img.png.len() > 1000 && img.path.exists());
        let out = std::env::temp_dir().join(format!("pigment-auto-{}", std::process::id()));
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Box" })).unwrap();
        for f in e["files"].as_array().unwrap() {
            assert!(Path::new(f.as_str().unwrap()).exists(), "{f}");
        }
        s.undo(false).unwrap();
        let saved = s.save_project(&json!({ "path": out.join("box.pigment") })).unwrap();
        assert!(out.join("box.pigment/project.json").exists(), "{saved}");
        std::fs::remove_dir_all(out).ok();
    }

    #[test]
    fn neon_glows_in_material_export_and_brush() {
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/neon_tubes.glb"), "resolution": 512, "material": "Neon pink" })).unwrap();
        let out = std::env::temp_dir().join(format!("pigment-neon-{}", std::process::id()));
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Tube" })).unwrap();
        assert!((e["emissive_scale"].as_f64().unwrap() - 6.0).abs() < 0.5, "{e}");
        let em = image::open(out.join("Tube_Emissive.png")).unwrap().to_rgb8();
        let px = em.get_pixel(256, 256).0;
        assert!(px[0] > 200 && px[1] < 140 && px[2] > 120, "emissive texel {px:?}");
        // brush paints emission on a plain material
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Matte black" })).unwrap();
        s.paint_stroke(&json!({ "points": [[0.3, 0.5], [0.7, 0.5]], "material": "Neon cyan", "size": 60 })).unwrap();
        let img = s.render(&json!({ "view": "emission", "width": 320, "height": 240, "path": std::env::temp_dir().join("pig/emis_view.png") })).unwrap();
        let rgba = image::load_from_memory(&img.png).unwrap().to_rgba8();
        // bright neon: the core blows out towards white, the rim is cyan
        let cyan = rgba.pixels().filter(|p| p.0[2] > 180 && p.0[1] > 180).count();
        assert!(cyan > 100, "{cyan} glowing pixels");
        // decal: a neon sign image projected onto the box, glowing pink
        s.add_layer(&json!({ "kind": "paint", "name": "Signs" })).unwrap();
        let d = s.project_decal(&json!({ "image": root.join("assets/decals/neon_open.png"), "rect": [0.25, 0.3, 0.75, 0.6], "tint": [1.0, 0.2, 0.7], "emissive_strength": 5.0 })).unwrap();
        assert_eq!(d["on"], "Signs");
        let img = s.render(&json!({ "view": "emission", "width": 320, "height": 240, "path": std::env::temp_dir().join("pig/decal_view.png") })).unwrap();
        let rgba = image::load_from_memory(&img.png).unwrap().to_rgba8();
        let pink = rgba.pixels().filter(|p| p.0[0] > 180 && p.0[2] > 120 && p.0[1] < 200).count();
        assert!(pink > 200, "{pink} pink decal pixels");
        s.undo(false).unwrap();
        let img = s.render(&json!({ "view": "emission", "width": 320, "height": 240 })).unwrap();
        let rgba = image::load_from_memory(&img.png).unwrap().to_rgba8();
        let pink_after = rgba.pixels().filter(|p| p.0[0] > 180 && p.0[2] > 120 && p.0[1] < 200).count();
        assert!(pink_after < pink / 10, "undo left the decal ({pink_after})");
        std::fs::remove_dir_all(out).ok();
    }

    /// Regression: sliver triangles (from the vending machine's vent cut-outs)
    /// used to smear corner curvature across the flat side panel.
    #[test]
    fn flat_panels_stay_flat_next_to_sliver_triangles() {
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/vending_machine.glb"), "resolution": 1024 })).unwrap();
        let img = s.render(&json!({ "yaw": 90, "pitch": 0, "width": 640, "height": 640, "view": "curvature" })).unwrap();
        let g = image::load_from_memory(&img.png).unwrap().to_luma8();
        // the flat area between the two vents
        let mut worst = 0i32;
        for y in (240..440).step_by(4) {
            for x in (260..380).step_by(4) {
                worst = worst.max((g.get_pixel(x, y).0[0] as i32 - 128).abs());
            }
        }
        assert!(worst < 20, "flat side panel reads as curved (max deviation {worst}/255)");
    }

    #[test]
    fn part_masks_limit_a_layer_to_the_picked_pieces() {
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Matte black" })).unwrap();
        let parts = s.list_parts();
        assert!(parts.as_array().unwrap().len() > 5, "ammo box should have several pieces");
        // the piece under the middle of the front view (the body)
        let picked = s.pick_parts(&json!({ "points": [[0.5, 0.55]], "yaw": 0, "pitch": 5 })).unwrap();
        let body = picked["parts"][0].as_u64().expect("something under the centre");
        let glow = |s: &mut Session| -> usize {
            let img = s.render(&json!({ "view": "emission", "yaw": 0, "pitch": 5, "width": 320, "height": 320 })).unwrap();
            image::load_from_memory(&img.png).unwrap().to_luma8().pixels().filter(|p| p.0[0] > 100).count()
        };
        s.add_layer(&json!({ "name": "Glow", "material": "Neon green", "mask": { "parts": [body] } })).unwrap();
        let only_body = glow(&mut s);
        s.update_layer(&json!({ "layer": "Glow", "mask": { "parts": [] } })).unwrap();
        let everything = glow(&mut s);
        assert!(only_body > 1000, "selected part glows ({only_body})");
        assert!(everything > only_body + 1000, "whole model glows more than one part ({everything} vs {only_body})");
        let layers = s.layers();
        assert!(layers.to_string().contains("\"parts\":[]"));
    }

    #[test]
    fn part_queries_project_info_and_named_errors() {
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512 })).unwrap();
        let all = s.list_parts_query(&json!({})).unwrap();
        let n = all.as_array().unwrap().len();
        // filtered + sorted + paged
        let big = s.list_parts_query(&json!({ "sort": "area", "limit": 3 })).unwrap();
        assert_eq!(big["total_parts"], n);
        assert_eq!(big["returned"], 3);
        let areas: Vec<f64> = big["parts"].as_array().unwrap().iter().map(|p| p["area"].as_f64().unwrap()).collect();
        assert!(areas.windows(2).all(|w| w[0] >= w[1]), "biggest first: {areas:?}");
        let biggest = big["parts"][0]["id"].as_u64().unwrap();
        let small = s.list_parts_query(&json!({ "max_size": 0.05, "ids_only": true })).unwrap();
        assert!(!small["parts"].as_array().unwrap().iter().any(|p| p.as_u64() == Some(biggest)));
        let m = small["matched"].as_u64().unwrap() as usize;
        let rest = s.list_parts_query(&json!({ "min_size": 0.05000001, "ids_only": true })).unwrap();
        assert_eq!(m + rest["matched"].as_u64().unwrap() as usize, n, "size filters split the parts");
        // pick by shape = the same query
        let p = s.pick_parts(&json!({ "shape": { "sort": "area", "limit": 1 } })).unwrap();
        assert_eq!(p["parts"][0].as_u64(), Some(biggest));
        assert_eq!(p["count"].as_u64(), Some(n as u64));
        assert!(s.pick_parts(&json!({})).unwrap_err().contains("`points`"));
        assert!(s.pick_parts(&json!({ "shape": { "facing": "w" } })).unwrap_err().contains("`shape.facing`"));
        assert!(s.list_parts_query(&json!({ "sort": "colour" })).unwrap_err().contains("`sort`"));
        // bad part ids name the argument
        let e = s.add_layer(&json!({ "name": "X", "mask": { "parts": [0, n + 5] } })).unwrap_err();
        assert!(e.contains(&format!("`mask.parts[1]` = {}", n + 5)) && e.contains(&format!("the mesh has {n} parts")), "{e}");
        assert!(s.layers().as_array().unwrap().iter().all(|l| l["name"] != "X"), "failed add_layer leaves no layer");
        let e = s.update_layer(&json!({ "layer": "Nope" })).unwrap_err();
        assert!(e.contains("`layer` = \"Nope\"") && e.contains("Paint"), "{e}");
        let e = s.add_layer(&json!({ "material": "steel" })).unwrap_err();
        assert!(e.contains("`material` = \"steel\"") && e.contains("Steel"), "{e}");
        // project info
        s.add_layer(&json!({ "name": "Glow", "material": "Neon green", "mask": { "parts": [biggest] } })).unwrap();
        let info = s.project_info();
        assert_eq!(info["resolution"], 512);
        assert_eq!(info["parts"]["count"], n);
        assert_eq!(info["parts"]["masked_layers"][0]["layer"], "Glow");
        assert_eq!(info["mesh"]["triangles"].as_u64().unwrap() as usize, s.app.mesh.triangle_count());
        assert_eq!(info["layers"]["count"].as_u64().unwrap() as usize, s.app.doc.layers.len());
        assert!(info["bake"]["baked"].as_bool().unwrap(), "{info}");
    }
}
