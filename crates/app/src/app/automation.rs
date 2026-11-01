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
        .ok_or_else(|| format!("unknown view `{name}` (material, base color, roughness, metallic, height, normal, ambient, curvature, world, uv)"))
}

fn channel(name: &str) -> Res<Channel> {
    let n = name.to_ascii_lowercase().replace([' ', '-'], "_");
    Channel::ALL.into_iter().find(|c| c.file_stem() == n || c.label().to_ascii_lowercase().replace(' ', "_") == n).ok_or_else(|| format!("unknown channel `{name}`"))
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
    .ok_or_else(|| format!("unknown blend mode `{name}`"))
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
            let layers = self.app.doc.smart_material(name).ok_or_else(|| format!("unknown smart material `{name}`"))?;
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
                        "kind": if l.is_folder() { "folder" } else if l.is_paint() { "paint" } else { "fill" },
                        "visible": l.visible,
                        "opacity": l.opacity,
                        "channels": Channel::ALL.iter().filter(|c| l.channels.get(**c).enabled).map(|c| c.file_stem()).collect::<Vec<_>>(),
                    });
                    self.folder_fields(l, &mut o);
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

    /// Folder info for `list_layers`: id, depth, parent index, path, and for
    /// folders their child count and collapsed state.
    fn folder_fields(&self, l: &Layer, o: &mut Value) {
        let doc = &self.app.doc;
        if !doc.layers.iter().any(|x| x.is_folder() || x.parent.is_some()) {
            return; // folder-less stacks list exactly as before
        }
        o["id"] = json!(l.id);
        o["depth"] = json!(doc.depth(l.id));
        o["parent"] = json!(doc.ancestors(l.id).first().and_then(|p| doc.index_of(*p)));
        o["path"] = json!(doc.layer_path(l.id));
        if let LayerKind::Folder { collapsed } = l.kind {
            o["children"] = json!(doc.children_of(Some(l.id)).len());
            o["collapsed"] = json!(collapsed);
        }
    }

    /// The stack as a tree: top-level items bottom to top, folders with
    /// their contents nested under `layers` (same fields as the flat list).
    pub fn layer_tree(&self) -> Value {
        fn build(doc: &Document, flat: &Value, parent: Option<LayerId>) -> Value {
            Value::Array(
                doc.children_of(parent)
                    .into_iter()
                    .map(|i| {
                        let mut o = flat[i].clone();
                        if doc.layers[i].is_folder() {
                            o["layers"] = build(doc, flat, Some(doc.layers[i].id));
                        }
                        o
                    })
                    .collect(),
            )
        }
        build(&self.app.doc, &self.layers(), None)
    }

    /// `list_layers`: flat (bottom to top) or, with `tree: true`, nested.
    pub fn list_layers(&self, a: &Value) -> Value {
        if a.get("tree").and_then(Value::as_bool).unwrap_or(false) {
            self.layer_tree()
        } else {
            self.layers()
        }
    }

    /// A folder reference (name, "A/B" path or index) that must be a folder.
    fn find_folder(&self, r: &Value) -> Res<LayerId> {
        let i = self.find_layer(r)?;
        let l = &self.app.doc.layers[i];
        if !l.is_folder() {
            return Err(format!("`{}` is not a folder", l.name));
        }
        Ok(l.id)
    }

    fn find_layer(&self, r: &Value) -> Res<usize> {
        if let Value::String(path) = r {
            // "Folder/Sub/Layer" paths pick a layer inside folders
            if path.contains('/') {
                let p = path.to_ascii_lowercase();
                let doc = &self.app.doc;
                if let Some(i) = doc.layers.iter().rposition(|l| doc.layer_path(l.id).to_ascii_lowercase() == p) {
                    return Ok(i);
                }
            }
        }
        match r {
            Value::Number(n) => {
                let i = n.as_u64().ok_or("layer index must be >= 0")? as usize;
                (i < self.app.doc.layers.len()).then_some(i).ok_or_else(|| format!("no layer {i}"))
            }
            Value::String(name) => {
                let n = name.to_ascii_lowercase();
                // last match = the topmost layer with that name
                self.app.doc.layers.iter().rposition(|l| l.name.to_ascii_lowercase() == n).ok_or_else(|| format!("no layer named `{name}`"))
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
                return Err(format!("unknown material `{name}` (see list_library)"));
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
                    Some(k) => Some(GeneratorKind::from_id(k).ok_or_else(|| format!("unknown generator `{k}`"))?),
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
                if let Some(ps) = m.get("parts").and_then(Value::as_array) {
                    mask.parts = ps.iter().filter_map(|p| p.as_u64().map(|x| x as u32)).filter(|&p| p < MAX_SELECTABLE_PARTS).collect();
                    mask.parts.sort_unstable();
                    mask.parts.dedup();
                }
                if let Some(effs) = m.get("effects").and_then(Value::as_array) {
                    if effs.len() > MAX_MASK_EFFECTS {
                        return Err(format!("at most {MAX_MASK_EFFECTS} extra effects"));
                    }
                    mask.effects.clear();
                    for e in effs {
                        let k = s(e, "generator").ok_or("each effect needs `generator`")?;
                        let mut g = Generator::new(GeneratorKind::from_id(k).ok_or_else(|| format!("unknown generator `{k}`"))?);
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
        self.set_camera(a);
        let px = Vec2::new(self.size[0] as f32, self.size[1] as f32);
        let pts = a.get("points").and_then(Value::as_array).ok_or("missing `points`")?;
        let mut out = Vec::new();
        for p in pts {
            let p = p.as_array().ok_or("points are [x, y]")?;
            let v = Vec2::new(p[0].as_f64().unwrap_or(0.0) as f32, p[1].as_f64().unwrap_or(0.0) as f32);
            out.push(self.app.part_at(v * px, px).map(Value::from).unwrap_or(Value::Null));
        }
        Ok(json!({ "parts": out }))
    }

    pub fn add_smart_material(&mut self, a: &Value) -> Res<Value> {
        let name = req(a, "name")?;
        let layers = self.app.doc.smart_material(name).ok_or_else(|| format!("unknown smart material `{name}` (see list_library)"))?;
        // insert below the topmost paint layer so painting stays on top
        let at = self.app.doc.layers.iter().rposition(|l| l.is_paint()).unwrap_or(self.app.doc.layers.len());
        for (k, l) in layers.into_iter().enumerate() {
            self.app.doc.layers.insert(at + k, l);
        }
        self.app.doc.normalize_folders();
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    pub fn add_layer(&mut self, a: &Value) -> Res<Value> {
        let kind = s(a, "kind").unwrap_or("fill");
        let name = s(a, "name").unwrap_or(if kind == "paint" { "Paint" } else { "Fill" }).to_string();
        let parent = match a.get("parent") {
            None | Some(Value::Null) => None,
            Some(r) => Some(self.find_folder(r)?),
        };
        let l = match kind {
            "paint" => self.app.doc.new_paint_layer(&name),
            "fill" => self.app.doc.fill_with(&name, s(a, "material").unwrap_or("White plastic"), None),
            "folder" => self.app.doc.new_folder(if s(a, "name").is_some() { &name } else { "Folder" }),
            _ => return Err("`kind` must be \"fill\", \"paint\" or \"folder\"".into()),
        };
        if let Some(p) = parent {
            // inside a folder: `index` is the position among its children
            let id = l.id;
            self.app.doc.layers.push(l);
            let pos = a.get("index").and_then(Value::as_u64).map(|i| i as usize);
            if let Err(e) = self.app.doc.move_layer(id, Some(p), pos) {
                self.app.doc.remove_layer_tree(id);
                return Err(e);
            }
            let at = self.app.doc.index_of(id).unwrap();
            let mut cfg = a.clone();
            if let Some(o) = cfg.as_object_mut() {
                o.remove("name");
            }
            if let Err(e) = self.configure(at, &cfg) {
                self.app.doc.remove_layer_tree(id);
                return Err(e);
            }
            self.settle();
            return Ok(json!({ "added": self.app.doc.index_of(id), "path": self.app.doc.layer_path(id), "layers": self.layers() }));
        }
        let at = match a.get("index").and_then(Value::as_u64) {
            Some(i) => (i as usize).min(self.app.doc.layers.len()),
            None if kind == "paint" => self.app.doc.layers.len(),
            None => self.app.doc.layers.iter().rposition(|l| l.is_paint()).unwrap_or(self.app.doc.layers.len()),
        };
        let id = l.id;
        self.app.doc.layers.insert(at, l);
        // a flat index inside a folder's range still means "top level"
        self.app.doc.normalize_folders();
        let at = self.app.doc.index_of(id).unwrap();
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
        let i = self.find_layer(a.get("layer").ok_or("missing `layer`")?)?;
        let id = self.app.doc.layers[i].id;
        // resolve the target folder before anything changes
        let parent = match a.get("parent") {
            None => None,
            Some(Value::Null) => Some(None),
            Some(r) => Some(Some(self.find_folder(r)?)),
        };
        self.configure(i, a)?;
        if let Some(c) = a.get("collapsed").and_then(Value::as_bool) {
            match &mut self.app.doc.layers[i].kind {
                LayerKind::Folder { collapsed } => *collapsed = c,
                _ => return Err("`collapsed` applies to folders".into()),
            }
        }
        let to = a.get("move_to").and_then(Value::as_u64).map(|t| t as usize);
        match parent {
            // into / out of a folder; `move_to` is then the position among its children
            Some(p) => self.app.doc.move_layer(id, p, to)?,
            None => {
                if let Some(to) = to {
                    match self.app.doc.layers[i].parent {
                        Some(cur) => self.app.doc.move_layer(id, Some(cur), Some(to))?,
                        None => {
                            let l = self.app.doc.layers.remove(i);
                            let to = to.min(self.app.doc.layers.len());
                            self.app.doc.layers.insert(to, l);
                            self.app.doc.normalize_folders();
                        }
                    }
                }
            }
        }
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    pub fn delete_layer(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer`")?)?;
        // a folder goes with everything inside it
        let id = self.app.doc.layers[i].id;
        self.app.doc.remove_layer_tree(id);
        self.settle();
        Ok(json!({ "layers": self.layers() }))
    }

    /// Save a folder (or fill layer) as a part-agnostic `.pigsmart` file.
    pub fn save_smart_material(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer` (the folder to save)")?)?;
        let id = self.app.doc.layers[i].id;
        let mut path = PathBuf::from(req(a, "path")?);
        if path.extension().is_none() {
            path.set_extension(pigment_core::smart::SMART_EXTENSION);
        }
        let name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.doc.layers[i].name.clone());
        let sm = self.app.save_smart(id, &name, &path)?;
        Ok(json!({ "saved": path, "name": sm.name, "layers": sm.layers.len(), "warnings": sm.warnings }))
    }

    /// Instance a `.pigsmart` file at the top level below the top paint
    /// layer, or inside folder `parent`; `parts` limits it to those mesh parts.
    pub fn apply_smart_material(&mut self, a: &Value) -> Res<Value> {
        let path = PathBuf::from(req(a, "path")?);
        let parts: Vec<u32> = a.get("parts").and_then(Value::as_array).map(|ps| ps.iter().filter_map(|p| p.as_u64().map(|x| x as u32)).collect()).unwrap_or_default();
        let parent = match a.get("parent") {
            None | Some(Value::Null) => None,
            Some(r) => Some(self.find_folder(r)?),
        };
        let root = self.app.apply_smart(&path, &parts, parent)?;
        let i = self.app.doc.index_of(root).ok_or("smart material didn't land")?;
        // optional overrides on the new folder: name, opacity, visible, blend, channels
        let cfg: serde_json::Map<String, Value> =
            a.as_object().map(|o| o.iter().filter(|(k, _)| ["name", "opacity", "visible", "blend", "channels"].contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect()).unwrap_or_default();
        if let Err(e) = self.configure(i, &Value::Object(cfg)) {
            self.app.doc.remove_layer_tree(root);
            return Err(e);
        }
        self.settle();
        Ok(json!({ "applied": self.app.doc.layer_path(root), "index": self.app.doc.index_of(root), "layers": self.layers() }))
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
                return Err(format!("unknown material `{name}`"));
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
        self.app.doc.export_preset = preset.to_string();
        self.app.export_dir = Some(dir.clone());
        self.app.export_name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        self.app.status = None;
        self.app.export(&self.rs);
        let msg = self.status()?;
        let scale = self.app.last_emissive_scale;
        let files: Vec<String> = export::preset(preset)
            .unwrap()
            .outputs
            .iter()
            .map(|o| dir.join(format!("{}_{}.png", self.app.export_name, o.suffix)).to_string_lossy().to_string())
            .collect();
        Ok(json!({ "status": msg, "files": files, "emissive_scale": scale }))
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
    fn folders_and_saved_smart_materials_over_mcp() {
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let out = std::env::temp_dir().join(format!("pigment-folders-{}", std::process::id()));
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Olive drab" })).unwrap();
        // flat list keeps its old shape until a folder exists
        assert!(s.layers()[0].get("depth").is_none());
        s.add_layer(&json!({ "kind": "folder", "name": "Weathering", "opacity": 0.9 })).unwrap();
        s.add_layer(&json!({ "name": "Grime", "material": "Grime", "parent": "Weathering", "mask": { "generator": "dirt", "amount": 0.6 } })).unwrap();
        s.add_layer(&json!({ "kind": "folder", "name": "Rust", "parent": "Weathering" })).unwrap();
        s.add_layer(&json!({ "name": "Spots", "material": "Rust", "parent": "Weathering/Rust", "mask": { "generator": "spots" } })).unwrap();
        s.add_layer(&json!({ "name": "Wear", "material": "Steel", "mask": { "generator": "edge_wear" } })).unwrap();
        // move a top-level layer into a folder, then a nested one out
        s.update_layer(&json!({ "layer": "Wear", "parent": "Weathering", "move_to": 0 })).unwrap();
        assert_eq!(s.app.doc.layer_path(s.app.doc.layers[s.find_layer(&json!("Wear")).unwrap()].id), "Weathering/Wear");
        s.update_layer(&json!({ "layer": "Weathering/Rust", "collapsed": true })).unwrap();
        assert!(s.update_layer(&json!({ "layer": "Grime", "collapsed": true })).is_err());
        assert!(s.add_layer(&json!({ "name": "x", "parent": "Grime" })).is_err(), "parent must be a folder");
        let tree = s.list_layers(&json!({ "tree": true }));
        let w = tree.as_array().unwrap().iter().find(|l| l["name"] == "Weathering").expect("folder at top level");
        assert_eq!(w["kind"], "folder");
        assert_eq!(w["layers"].as_array().unwrap().len(), 3, "{w}");
        assert_eq!(w["layers"][2]["layers"][0]["path"], "Weathering/Rust/Spots");
        let flat = s.layers();
        assert!(flat.as_array().unwrap().iter().any(|l| l["depth"] == 2));

        // save the folder, reopen the project: folders persist
        let sm = out.join("weathering.pigsmart");
        let r = s.save_smart_material(&json!({ "layer": "Weathering", "path": sm })).unwrap();
        assert_eq!(r["layers"], 5, "{r}");
        s.save_project(&json!({ "path": out.join("a.pigment") })).unwrap();
        let before = s.render(&json!({ "width": 160, "height": 120 })).unwrap().png;
        s.open_project(&json!({ "path": out.join("a.pigment") })).unwrap();
        assert_eq!(s.layer_tree(), tree);
        let after = s.render(&json!({ "width": 160, "height": 120 })).unwrap().png;
        assert_eq!(before, after, "reopened project renders the same");

        // apply to another model, limited to two parts
        s.new_project(&json!({ "mesh": root.join("assets/vending_machine.glb"), "resolution": 512, "material": "Teal paint" })).unwrap();
        let a = s.apply_smart_material(&json!({ "path": sm, "parts": [0, 1], "opacity": 0.8 })).unwrap();
        assert_eq!(a["applied"], "Weathering");
        let i = s.find_layer(&json!("Weathering")).unwrap();
        let f = &s.app.doc.layers[i];
        assert_eq!(f.mask.as_ref().unwrap().parts, vec![0, 1]);
        assert!((f.opacity - 0.8).abs() < 1e-6);
        assert!(s.layers().as_array().unwrap().last().unwrap()["kind"] == "paint", "paint layer stays on top");
        // deleting the folder removes its contents
        let n = s.app.doc.layers.len();
        s.delete_layer(&json!({ "layer": "Weathering" })).unwrap();
        assert_eq!(s.app.doc.layers.len(), n - 5);
        s.undo(false).unwrap();
        assert_eq!(s.app.doc.layers.len(), n);
        std::fs::remove_dir_all(out).ok();
    }
}
