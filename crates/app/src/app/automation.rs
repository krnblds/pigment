//! Headless automation: drive Pigment with commands instead of a mouse.
//! Used by the `pigment-mcp` server (one JSON object per tool call) and by tests.
//!
//! Every command runs through the same code paths as the UI (document edits,
//! undo history, strokes, bake, composite, save, export).

use super::*;
use crate::render::viewport::ViewMode;
use pigment_core::variants::{resolve, validate_defs, DecalRecord, PartSubset, VariantDef};
use serde_json::{json, Value};

type Res<T> = Result<T, String>;

mod decal_tools;
mod sheet_tools;

/// A GPU device without a window.
pub fn headless_render_state() -> Option<RenderState> {
    use eframe::egui_wgpu::wgpu;
    let instance = wgpu::Instance::default();
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        ..Default::default()
    }))
    .ok()?;
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
        if a.get("tile").is_some_and(|t| !t.is_null()) {
            return self.new_sheet_project(a);
        }
        let mesh = PathBuf::from(req(a, "mesh").map_err(|_| "missing argument `mesh` (or `tile` for a flat seamless tile / trim sheet / decal atlas)".to_string())?);
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
                "emissive": v.emissive, "emissive_strength": v.emissive_strength,
                "opacity": v.opacity, "transmission": v.transmission,
                "coat": v.coat, "coat_roughness": v.coat_roughness, "flake": v.flake
            })).collect::<Vec<_>>(),
            "smart_materials": smart_material_names(),
            "generators": GeneratorKind::ALL.iter().map(|k| json!({ "id": k.id(), "label": k.label(), "uses_bakes": k.uses_bakes() })).collect::<Vec<_>>(),
            "blend_modes": ["normal", "multiply", "screen", "overlay", "add", "subtract", "darken", "lighten", "replace", "combine"],
            "export_presets": export::presets().iter().map(|p| json!({ "id": p.id, "label": p.label })).collect::<Vec<_>>(),
            "views": ViewMode::ALL.iter().map(|m| m.label()).collect::<Vec<_>>(),
            "tile_sets": pigment_core::image_fill::list_tile_sets(Path::new("assets/tiles")).iter().map(|n| format!("assets/tiles/{n}")).collect::<Vec<_>>(),
            "image_projections": ["uv", "triplanar"],
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
                    if let Some(img) = &l.image {
                        o["image"] = serde_json::to_value(img).unwrap_or(Value::Null);
                    }
                    if let Some(m) = &l.mask {
                        o["mask"] = json!({
                            "generator": m.generator.as_ref().map(|g| json!({
                                "kind": g.kind.id(), "amount": g.amount, "softness": g.softness, "scale": g.noise_scale,
                                "breakup": g.noise_amount, "seed": g.seed, "ao_influence": g.ao_influence, "curvature_weight": g.curvature_weight,
                                "variant": g.variant
                            })),
                            "effects": m.effects.iter().map(|e| json!({ "generator": e.generator.kind.id(), "op": format!("{:?}", e.op).to_lowercase(), "amount": e.generator.amount, "scale": e.generator.noise_scale })).collect::<Vec<_>>(),
                            "parts": m.parts,
                            "invert": m.invert,
                        });
                    }
                    if !l.variant.is_empty() {
                        o["variant"] = json!({
                            "group": l.variant.group,
                            "part_subset": l.variant.part_subset,
                            "decals": l.variant.decals.iter().map(|d| json!({ "name": d.name, "group": d.group, "enabled": d.enabled, "image": d.args.get("image") })).collect::<Vec<_>>(),
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
        // mask.parts_where: a part shape query, resolved to ids now
        let where_ids: Option<Vec<u32>> = match a.get("mask").and_then(|m| m.get("parts_where")) {
            Some(w) => Some(self.query_ids(w, "mask.parts_where.")?),
            None => None,
        };
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
            (l.channels.opacity.enabled, l.channels.transmission.enabled) = values.is_see_through();
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
            // opacity / transmission: on when given or not neutral
            if let Some(x) = f(vals, "opacity") {
                v.opacity = x.clamp(0.0, 1.0);
            }
            if let Some(x) = f(vals, "transmission") {
                v.transmission = x.clamp(0.0, 1.0);
            }
            let (see, trans) = v.is_see_through();
            l.channels.opacity.enabled |= see || vals.get("opacity").is_some();
            l.channels.transmission.enabled |= trans || vals.get("transmission").is_some();
            // clearcoat: on when given or coated; coat roughness rides with the coat
            if let Some(x) = f(vals, "coat") {
                v.coat = x.clamp(0.0, 1.0);
            }
            if let Some(x) = f(vals, "coat_roughness") {
                v.coat_roughness = x.clamp(0.0, 1.0);
            }
            if let Some(x) = f(vals, "flake") {
                v.flake = x.clamp(0.0, 1.0);
            }
            let (coat, flake) = v.is_coated();
            let coat_given = vals.get("coat").is_some();
            l.channels.coat.enabled |= coat || coat_given;
            l.channels.coat_roughness.enabled |= coat || coat_given || vals.get("coat_roughness").is_some();
            l.channels.flake.enabled |= flake || vals.get("flake").is_some();
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
        if let Some(img) = a.get("image") {
            configure_image(app, i, img)?;
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
                if let Some(w) = where_ids {
                    // with `parts` too: the union; alone: replaces the selection
                    if m.get("parts").is_none() {
                        mask.parts.clear();
                    }
                    mask.parts.extend(w.into_iter().filter(|&id| id < MAX_SELECTABLE_PARTS));
                    mask.parts.sort_unstable();
                    mask.parts.dedup();
                    if mask.parts.is_empty() {
                        return Err("`mask.parts_where` matched no parts (an empty selection would mean the whole model); loosen the query or check list_parts".into());
                    }
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
        match a.get("variant") {
            None => {}
            Some(Value::Null) => app.doc.layers[i].variant.group.clear(),
            Some(Value::String(g)) => app.doc.layers[i].variant.group = g.clone(),
            Some(_) => return Err("`variant` is a group name or null".into()),
        }
        match a.get("part_subset") {
            None => {}
            Some(Value::Null) => app.doc.layers[i].variant.part_subset = None,
            Some(v) => {
                let from = f(v, "from").unwrap_or(0.0);
                let to = f(v, "to").ok_or("`part_subset` needs `to` (0..1)")?;
                if !(0.0..=1.0).contains(&from) || !(from..=1.0).contains(&to) {
                    return Err("`part_subset` needs 0 <= from <= to <= 1".into());
                }
                let salt = v.get("salt").and_then(Value::as_u64).unwrap_or(0) as u32;
                if app.doc.layers[i].mask.is_none() {
                    let res = app.doc.mint();
                    app.ts.new_mask(&rs.device, &rs.queue, res, true);
                    app.doc.layers[i].mask = Some(Mask::new(res));
                }
                app.doc.layers[i].variant.part_subset = Some(PartSubset { from, to, salt });
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
        let i = self.find_layer(a.get("layer").ok_or("missing `layer` (a layer name or index, 0 = bottom; see list_layers)")?)?;
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
        let i = self.find_layer(a.get("layer").ok_or("missing `layer` (a layer name or index, 0 = bottom; see list_layers)")?)?;
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
        // close-ups: orbit a world point (`target`), optionally at a given distance
        if let Some(t) = a.get("target").and_then(Value::as_array).filter(|t| t.len() == 3) {
            cam.target = glam::Vec3::new(t[0].as_f64().unwrap_or(0.0) as f32, t[1].as_f64().unwrap_or(0.0) as f32, t[2].as_f64().unwrap_or(0.0) as f32);
        }
        if let Some(d) = f(a, "distance") {
            cam.distance = d.max(0.01);
        }
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
    fn aim_at_part(&mut self, part: u32, image: &Path, fit: &str, margin: f32, facing: Option<&str>) -> Res<Vec<f32>> {
        let info = *self.app.parts.info.get(part as usize).ok_or_else(|| format!("no part {part}"))?;
        self.aim_at_box(glam::Vec3::from(info.min), glam::Vec3::from(info.max), image, fit, margin, facing)
    }

    /// `aim_at_part` for any world-space box (e.g. an area of a big wall that
    /// is one part with the rest of the building). `facing` ("+x", "-z", ...)
    /// overrides the side the camera looks from.
    fn aim_at_box(&mut self, lo: glam::Vec3, hi: glam::Vec3, image: &Path, fit: &str, margin: f32, facing: Option<&str>) -> Res<Vec<f32>> {
        let c = (lo + hi) * 0.5;
        let size = hi - lo;
        let (mc, _) = self.app.mesh.bounding_sphere();
        let (axis, outward) = match facing {
            Some(f) => {
                let f = f.to_ascii_lowercase();
                let axis = match f.trim_start_matches(['+', '-']) {
                    "x" => 0,
                    "y" => 1,
                    "z" => 2,
                    _ => return Err(format!("facing `{f}`: use +x, -x, +y, -y, +z or -z")),
                };
                (axis, if f.starts_with('-') { -1.0 } else { 1.0 })
            }
            None => {
                let axis = if size.x <= size.y && size.x <= size.z { 0 } else if size.y <= size.z { 1 } else { 2 };
                (axis, if c[axis] >= mc[axis] { 1.0 } else { -1.0 })
            }
        };
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
            let (see, trans) = b.values.is_see_through();
            let (coat, flake) = b.values.is_coated();
            b.channels = [true, true, true, b.values.height.abs() > 1e-3, false, b.values.emissive_strength > 0.0, see, trans, coat, coat, flake];
        }
        if let Some(vals) = a.get("values") {
            apply_material_values(&mut b.values, vals);
            let (see, trans) = b.values.is_see_through();
            b.channels[6] |= see || vals.get("opacity").is_some();
            b.channels[7] |= trans || vals.get("transmission").is_some();
            let (coat, flake) = b.values.is_coated();
            b.channels[8] |= coat || vals.get("coat").is_some();
            b.channels[9] |= coat || vals.get("coat").is_some() || vals.get("coat_roughness").is_some();
            b.channels[10] |= flake || vals.get("flake").is_some();
        }
        if let Some(chs) = a.get("channels").and_then(Value::as_array) {
            b.channels = [false; 11];
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
        self.decal_impl(a, false)
    }

    /// `replay`: re-project a recorded decal during variant export (no
    /// record, no undo step, no history commit).
    fn decal_impl(&mut self, a: &Value, replay: bool) -> Res<Value> {
        // precise placement: a spot on a part's face, or a world position + normal
        if a.get("anchor").is_some() || a.get("position").is_some() {
            return self.place_decal(a, replay);
        }
        let image = PathBuf::from(req(a, "image")?);
        let (fit, margin, facing) = (s(a, "fit").unwrap_or("contain"), f(a, "margin").unwrap_or(0.05), s(a, "facing"));
        let rect: Vec<f32> = match (a.get("part").and_then(Value::as_u64), a.get("box")) {
            // aim at a mesh part's outward face and fit the image to it
            (Some(part), _) => self.aim_at_part(part as u32, &image, fit, margin, facing)?,
            // or at a world-space box: {min, max} or {center, size}
            (None, Some(b)) => {
                let v3 = |k: &str| -> Option<glam::Vec3> {
                    let a = b.get(k)?.as_array()?;
                    (a.len() == 3).then(|| glam::Vec3::new(a[0].as_f64().unwrap_or(0.0) as f32, a[1].as_f64().unwrap_or(0.0) as f32, a[2].as_f64().unwrap_or(0.0) as f32))
                };
                let (lo, hi) = match (v3("min"), v3("max"), v3("center"), v3("size")) {
                    (Some(lo), Some(hi), _, _) => (lo.min(hi), lo.max(hi)),
                    (_, _, Some(c), Some(sz)) => (c - sz.abs() * 0.5, c + sz.abs() * 0.5),
                    _ => return Err("`box` needs {min: [x,y,z], max: [x,y,z]} or {center, size}".into()),
                };
                self.aim_at_box(lo, hi, &image, fit, margin, facing)?
            }
            (None, None) => {
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
        let on_mask = a.get("mask").and_then(Value::as_bool).unwrap_or(false);
        let enabled = a.get("enabled").and_then(Value::as_bool).unwrap_or(true);
        if !replay {
            // record it on the layer, so variants can switch it or swap its image
            if !on_mask && self.app.doc.layers[i].is_paint() {
                let mut args = a.clone();
                if let Some(o) = args.as_object_mut() {
                    for k in ["layer", "name", "variant", "enabled"] {
                        o.remove(k);
                    }
                }
                let name = s(a, "name").map(String::from).unwrap_or_else(|| image.file_stem().map(|x| x.to_string_lossy().to_string()).unwrap_or_default());
                let group = s(a, "variant").unwrap_or("").to_string();
                self.app.doc.layers[i].variant.decals.push(DecalRecord { name, group, enabled, args });
            } else if !enabled || a.get("variant").is_some() {
                return Err("only decals on a paint layer (not its mask) can be tagged or disabled for variants".into());
            }
            if !enabled {
                if !image.exists() {
                    self.app.doc.layers[i].variant.decals.pop();
                    return Err(format!("no image {}", image.display()));
                }
                self.settle();
                return Ok(json!({ "decal": image, "on": self.app.doc.layers[i].name, "painted": false }));
            }
        }
        self.app.select(Some(id), on_mask);
        // no commit here: the decal record goes into the same undo step as the pixels
        self.app.ensure_composited(&self.rs);
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
        b.channels = [true, true, true, false, false, false, false, false, false, false, false];
        if let Some(e) = f(a, "emissive_strength") {
            b.values.emissive = b.values.base_color;
            b.values.emissive_strength = e;
            b.channels[5] = e > 0.0;
        }
        if let Some(h) = f(a, "height") {
            b.values.height = h;
            b.channels[3] = true;
        }
        if let Some(vals) = a.get("values") {
            apply_material_values(&mut b.values, vals);
            b.channels[6] |= vals.get("opacity").is_some();
            b.channels[7] |= vals.get("transmission").is_some();
            b.channels[8] |= vals.get("coat").is_some();
            b.channels[9] |= vals.get("coat").is_some() || vals.get("coat_roughness").is_some();
            b.channels[10] |= vals.get("flake").is_some();
        }
        if let Some(chs) = a.get("channels").and_then(Value::as_array) {
            b.channels = [false; 11];
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
        if let Err(e) = self.app.project_decal_ex(&self.rs, &image, r, px, lum, !replay) {
            if !replay && !on_mask && self.app.doc.layers[i].is_paint() {
                self.app.doc.layers[i].variant.decals.pop();
            }
            return Err(e);
        }
        if !replay {
            self.settle();
        }
        Ok(json!({ "decal": image, "on": self.app.doc.layers[i].name }))
    }

    /// Lighting and post settings shared by `render`, `render_turntable` and
    /// `render(views)`. Every setting persists for later renders until changed.
    ///   lighting: studio | night | overcast    hdri: path to .hdr / .exr
    ///   exposure (EV), env_rotation (degrees), background (bool)
    ///   bloom: true | false | {enabled, threshold, intensity, radius}
    pub fn apply_look(&mut self, a: &Value) -> Res<()> {
        let (d, q) = (&self.rs.device, &self.rs.queue);
        if let Some(p) = s(a, "hdri") {
            if self.app.env.source != p {
                self.app.env = Environment::load(d, q, Path::new(p)).map_err(|e| format!("couldn't load HDRI `{p}`: {e:#}"))?;
                self.app.env.source = p.to_string();
            }
        } else if let Some(l) = s(a, "lighting") {
            let id = pigment_core::envmath::preset_id(l).ok_or_else(|| format!("unknown lighting `{l}` (studio, night, overcast)"))?;
            if self.app.env.source != id {
                self.app.env = Environment::preset(d, q, id).ok_or("lighting preset failed")?;
            }
        }
        if let Some(x) = f(a, "exposure") {
            self.app.view.exposure = x;
        }
        if let Some(x) = f(a, "env_rotation") {
            self.app.view.env_rotation = x.to_radians();
        }
        if let Some(bg) = a.get("background").and_then(Value::as_bool) {
            self.app.view.show_env = bg;
        }
        let b = &mut self.app.view.bloom;
        match a.get("bloom") {
            Some(Value::Bool(on)) => b.enabled = *on,
            Some(o @ Value::Object(_)) => {
                b.enabled = o.get("enabled").and_then(Value::as_bool).unwrap_or(true);
                if let Some(x) = f(o, "threshold") {
                    b.threshold = x.max(0.0);
                }
                if let Some(x) = f(o, "intensity") {
                    b.intensity = x.max(0.0);
                }
                if let Some(x) = f(o, "radius") {
                    b.radius = x.clamp(0.0, 1.0);
                }
            }
            Some(Value::Null) | None => {}
            Some(other) => return Err(format!("`bloom` must be true/false or {{threshold, intensity, radius}}, got {other}")),
        }
        Ok(())
    }

    /// Draw the current camera/view and read the 8-bit image back.
    fn grab(&mut self) -> Res<Vec<u8>> {
        self.draw();
        Ok(crate::render::gpu::readback(&self.rs.device, &self.rs.queue, self.app.viewport.color().ok_or("no viewport")?))
    }

    fn save_png(rgba: &[u8], w: u32, h: u32, path: Option<&str>) -> Res<Image> {
        let mut png = Vec::new();
        image::codecs::png::PngEncoder::new(&mut png).write_image(rgba, w, h, image::ExtendedColorType::Rgba8).map_err(|e| e.to_string())?;
        let path = match path {
            Some(p) => PathBuf::from(p),
            None => std::env::temp_dir().join("pigment-mcp").join(format!("render-{}.png", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0))),
        };
        if let Some(d) = path.parent() {
            std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        std::fs::write(&path, &png).map_err(|e| e.to_string())?;
        Ok(Image { png, path })
    }

    /// Render several (label, yaw, pitch) views into one labelled contact sheet.
    fn contact_sheet(&mut self, a: &Value, views: &[(String, f32, f32)], default_cols: usize) -> Res<Image> {
        self.settle();
        self.apply_look(a)?;
        self.app.view.mode = match s(a, "view") {
            Some(v) => view_mode(v)?,
            None => ViewMode::Material,
        };
        let mut tile_args = a.clone();
        tile_args["width"] = json!(a.get("width").and_then(Value::as_u64).unwrap_or(384));
        tile_args["height"] = json!(a.get("height").and_then(Value::as_u64).unwrap_or(384));
        let mut tiles = Vec::with_capacity(views.len());
        for (label, yaw, pitch) in views {
            tile_args["yaw"] = json!(yaw);
            tile_args["pitch"] = json!(pitch);
            self.set_camera(&tile_args);
            let rgba = self.grab()?;
            tiles.push(pigment_core::sheet::Tile { rgba, w: self.size[0], h: self.size[1], label: label.clone() });
        }
        let cols = a.get("columns").and_then(Value::as_u64).map(|c| c as usize).unwrap_or(default_cols);
        let (img, w, h) = pigment_core::sheet::contact_sheet(&tiles, cols);
        Self::save_png(&img, w, h, s(a, "path"))
    }

    /// `frames` views evenly spaced around the model (from `start_yaw`, at
    /// `pitch`), as one contact-sheet PNG.
    pub fn render_turntable(&mut self, a: &Value) -> Res<Image> {
        let n = a.get("frames").and_then(Value::as_u64).unwrap_or(8).clamp(1, 36) as usize;
        let pitch = f(a, "pitch").unwrap_or(15.0);
        let start = f(a, "start_yaw").unwrap_or(0.0);
        let views: Vec<(String, f32, f32)> = (0..n)
            .map(|i| {
                let yaw = start + 360.0 * i as f32 / n as f32;
                (format!("YAW {}", yaw.rem_euclid(360.0).round()), yaw, pitch)
            })
            .collect();
        self.contact_sheet(a, &views, n.min(4))
    }

    /// Named views (front, back, left, right, top, bottom; or "all") as one
    /// contact sheet. Front looks at the model's +Z face (glTF front, Blender
    /// -Y), right from +X: the same as Blender's numpad views.
    pub fn render_views(&mut self, a: &Value) -> Res<Image> {
        let names: Vec<String> = match a.get("views") {
            Some(Value::String(x)) if x == "all" => ["front", "back", "left", "right", "top"].map(String::from).to_vec(),
            Some(Value::String(x)) => x.split(',').map(|v| v.trim().to_string()).collect(),
            Some(Value::Array(v)) => v.iter().filter_map(Value::as_str).map(String::from).collect(),
            _ => return Err("`views` must be a list like [\"front\", \"left\", \"top\"] or \"all\"".into()),
        };
        let pitch = f(a, "pitch").unwrap_or(0.0);
        let mut views = Vec::new();
        for n in &names {
            let (yaw, p) = match n.to_ascii_lowercase().as_str() {
                "front" => (0.0, pitch),
                "back" => (180.0, pitch),
                "right" => (90.0, pitch),
                "left" => (-90.0, pitch),
                "top" => (0.0, 89.0),
                "bottom" => (0.0, -89.0),
                other => return Err(format!("unknown view `{other}` (front, back, left, right, top, bottom)")),
            };
            views.push((n.to_ascii_uppercase(), yaw, p));
        }
        if views.is_empty() {
            return Err("no views given".into());
        }
        let cols = if views.len() == 5 { 3 } else { views.len().min(4) };
        self.contact_sheet(a, &views, cols)
    }

    /// Write a lighting preset as an equirectangular Radiance .hdr, e.g. to
    /// light a Blender world exactly like Pigment's viewport.
    pub fn export_lighting(&mut self, a: &Value) -> Res<Value> {
        let name = s(a, "lighting").unwrap_or("night");
        let path = PathBuf::from(req(a, "path")?);
        let width = a.get("width").and_then(Value::as_u64).unwrap_or(2048).clamp(64, 8192) as u32;
        let env = pigment_core::envmath::EnvImage::preset(name, width).ok_or_else(|| format!("unknown lighting `{name}` (studio, night, overcast)"))?;
        env.write_hdr(&path).map_err(|e| e.to_string())?;
        Ok(json!({ "lighting": pigment_core::envmath::preset_id(name), "path": path, "width": width, "height": width / 2,
                   "note": "equirectangular, +Y up. Blender: Environment Texture behind a Mapping node rotated -90 degrees about Z (tools/blender_lookdev.py does this)" }))
    }

    pub fn render(&mut self, a: &Value) -> Res<Image> {
        if a.get("views").is_some_and(|v| !v.is_null()) {
            return self.render_views(a);
        }
        self.settle();
        self.render_now(a)
    }

    /// `render` without committing pending document changes.
    fn render_now(&mut self, a: &Value) -> Res<Image> {
        self.app.ensure_composited(&self.rs);
        self.apply_look(a)?;
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
            .map(|o| dir.join(format!("{}_{}.png", self.app.export_name, o.suffix)))
            // opacity / transmission maps of a solid material aren't written
            .filter(|p| p.exists())
            .map(|p| p.to_string_lossy().to_string())
            .collect();
        let mut files = files;
        files.extend(self.export_sheet_extras(&dir)?);
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

    /// Ids matching a part query object (filters + sort/order/limit/offset).
    fn query_ids(&self, w: &Value, path: &str) -> Res<Vec<u32>> {
        if !w.is_object() {
            return Err(format!("`{}` must be an object of part filters (see list_parts), got {w}", path.trim_end_matches('.')));
        }
        let mut q = w.clone();
        q["ids_only"] = json!(true);
        let r = self.query_parts(&q, path)?;
        Ok(r["parts"].as_array().map(|a| a.iter().filter_map(|x| x.as_u64().map(|x| x as u32)).collect()).unwrap_or_default())
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

    // ------------------------------------------------------------------ variants

    /// Export one texture set per variant: `<dir>/<name>__<variant>/<name>_<map>.png`.
    /// `variants` (optional) replaces the definitions stored in the project.
    pub fn export_variants(&mut self, a: &Value) -> Res<Value> {
        self.settle();
        if let Some(v) = a.get("variants") {
            let defs: Vec<VariantDef> = serde_json::from_value(v.clone()).map_err(|e| format!("bad `variants`: {e}"))?;
            validate_defs(&defs)?;
            for d in &defs {
                resolve(&self.app.doc, d)?; // check every selector before storing anything
            }
            self.app.doc.variants.defs = defs;
            self.settle();
        }
        let mut defs = self.app.doc.variants.defs.clone();
        if defs.is_empty() {
            return Err("no variants: pass `variants` (they are stored in the project for next time)".into());
        }
        if let Some(only) = a.get("only").and_then(Value::as_array) {
            let only: Vec<&str> = only.iter().filter_map(Value::as_str).collect();
            defs.retain(|d| only.iter().any(|o| o.eq_ignore_ascii_case(&d.name)));
        }
        if a.get("dry_run").and_then(Value::as_bool).unwrap_or(false) {
            let mut out = Vec::new();
            for d in &defs {
                let r = resolve(&self.app.doc, d)?;
                out.push(json!({
                    "name": d.name,
                    "seed": d.seed,
                    "hidden_layers": r.doc.layers.iter().filter(|l| !l.visible).map(|l| l.name.clone()).collect::<Vec<_>>(),
                    "decals": r.doc.layers.iter().flat_map(|l| l.variant.decals.iter().filter(|x| x.enabled).map(|x| json!([x.name, x.args.get("image")]))).collect::<Vec<_>>(),
                    "replayed_layers": r.replay.len(),
                }));
            }
            return Ok(json!({ "dry_run": true, "variants": out }));
        }
        let dir = PathBuf::from(req(a, "dir")?);
        let preset = s(a, "preset").unwrap_or("separate").to_string();
        if export::preset(&preset).is_none() {
            return Err(format!("unknown preset `{preset}`: unreal, unity, godot, separate"));
        }
        let name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        let pattern = s(a, "folder").unwrap_or("{name}__{variant}").to_string();
        let preview = a.get("preview").cloned();

        let doc0 = self.app.doc.clone();
        let saved = (self.app.export_dir.clone(), self.app.export_name.clone());
        let mut out = Vec::new();
        let mut next_id = doc0.next_id;
        let mut result = Ok(());
        // Previews are deterministic: they start from the default look (studio,
        // bloom on, exposure 0) plus only the lighting/bloom/exposure args given
        // in `preview`, never what the last `render` left behind. The session's
        // look (environment, view settings, camera, size) is restored after.
        let saved_look = match &preview {
            Some(p) => {
                let env = self.preview_env(p)?;
                let old_env = std::mem::replace(&mut self.app.env, env);
                let old_view = self.app.view.clone();
                self.app.view = crate::render::viewport::ViewSettings { emission: old_view.emission, ..Default::default() };
                Some((old_env, old_view, self.app.camera.clone(), self.size))
            }
            None => None,
        };
        for v in &defs {
            let folder = dir.join(pattern.replace("{name}", &name).replace("{variant}", &v.name));
            let r = self.export_one(&doc0, v, &preset, &folder, &name, preview.as_ref());
            next_id = next_id.max(self.app.doc.next_id);
            // back to the authored state; free the scratch layers
            self.app.doc = doc0.clone();
            let live = self.app.live_resources();
            self.app.ts.retain(&live);
            self.app.ts.unsaved.retain(|r| live.contains(r));
            match r {
                Ok(x) => out.push(x),
                Err(e) => {
                    result = Err(e);
                    break;
                }
            }
        }
        // scratch ids are never reused
        self.app.doc.next_id = next_id;
        self.app.committed.next_id = self.app.committed.next_id.max(next_id);
        (self.app.export_dir, self.app.export_name) = saved;
        if let Some((env, view, camera, size)) = saved_look {
            self.app.env = env;
            self.app.view = view;
            self.app.camera = camera;
            self.size = size;
        }
        self.app.composited = None;
        self.app.ensure_composited(&self.rs);
        result?;
        Ok(json!({ "dir": dir, "variants": out }))
    }

    /// The environment for `export_variants` previews: `hdri`, else the
    /// `lighting` preset, else studio.
    fn preview_env(&self, p: &Value) -> Res<Environment> {
        let (d, q) = (&self.rs.device, &self.rs.queue);
        if let Some(path) = s(p, "hdri") {
            let mut env = Environment::load(d, q, Path::new(path)).map_err(|e| format!("couldn't load preview HDRI `{path}`: {e:#}"))?;
            env.source = path.to_string();
            return Ok(env);
        }
        let l = s(p, "lighting").unwrap_or("studio");
        let id = pigment_core::envmath::preset_id(l).ok_or_else(|| format!("unknown preview lighting `{l}` (studio, night, overcast)"))?;
        Environment::preset(d, q, id).ok_or_else(|| "lighting preset failed".into())
    }

    fn export_one(&mut self, doc0: &Document, v: &VariantDef, preset: &str, folder: &Path, name: &str, preview: Option<&Value>) -> Res<Value> {
        let r = resolve(doc0, v)?;
        self.app.doc = r.doc;
        self.app.doc.export_preset = preset.to_string();
        // decals changed on these layers: start them blank and replay
        for id in &r.replay {
            let res = self.app.doc.mint();
            if let Some(l) = self.app.doc.layer_mut(*id) {
                l.kind = LayerKind::Paint { res };
            }
        }
        self.app.ensure_composited(&self.rs);
        let mut painted = 0;
        for id in &r.replay {
            let i = self.app.doc.index_of(*id).ok_or("layer vanished")?;
            let recs: Vec<Value> = self.app.doc.layers[i].variant.decals.iter().filter(|d| d.enabled).map(|d| d.args.clone()).collect();
            for mut args in recs {
                args["layer"] = json!(i);
                self.decal_impl(&args, true).map_err(|e| format!("variant `{}`: {e}", v.name))?;
                painted += 1;
            }
        }
        self.app.ensure_composited(&self.rs);
        self.app.export_dir = Some(folder.to_path_buf());
        self.app.export_name = name.to_string();
        self.app.status = None;
        self.app.export(&self.rs);
        self.status().map_err(|e| format!("variant `{}`: {e}", v.name))?;
        let mut o = json!({ "name": v.name, "folder": folder, "seed": v.seed, "decals_replayed": painted, "emissive_scale": self.app.last_emissive_scale });
        // sidecar for consumers (Blender): the emission map is normalised per
        // variant, so its strength travels with it
        let shown: Vec<Value> = self.app.doc.layers.iter().filter(|l| l.visible).flat_map(|l| l.variant.decals.iter().filter(|d| d.enabled)).map(|d| json!({ "name": d.name, "group": d.group, "image": d.args.get("image") })).collect();
        let hidden: Vec<&str> = self.app.doc.layers.iter().filter(|l| !l.visible).map(|l| l.name.as_str()).collect();
        let side = json!({ "asset": name, "variant": v.name, "seed": v.seed, "preset": preset, "emissive_scale": self.app.last_emissive_scale, "decals": shown, "hidden_layers": hidden });
        std::fs::write(folder.join("variant.json"), serde_json::to_string_pretty(&side).unwrap_or_default()).map_err(|e| e.to_string())?;
        if let Some(p) = preview {
            let mut pa = p.clone();
            let path = match s(p, "dir") {
                Some(d) => Path::new(d).join(format!("{name}__{}.png", v.name)),
                None => folder.join("preview.png"),
            };
            pa["path"] = json!(path);
            let img = self.render_now(&pa)?;
            o["preview"] = json!(img.path);
        }
        Ok(o)
    }
}

use image::ImageEncoder;

fn f2(v: &Value, k: &str) -> Res<Option<[f32; 2]>> {
    match v.get(k) {
        None => Ok(None),
        Some(Value::Number(n)) => {
            let x = n.as_f64().unwrap_or(1.0) as f32;
            Ok(Some([x, x]))
        }
        Some(Value::Array(a)) if a.len() == 2 => Ok(Some([a[0].as_f64().unwrap_or(0.0) as f32, a[1].as_f64().unwrap_or(0.0) as f32])),
        Some(_) => Err(format!("`{k}` must be a number or [x, y]")),
    }
}

/// The `image` argument of add_layer / update_layer: tiling images for a fill
/// layer. A string is a tile set folder; an object edits the current settings
/// (only the given fields change); null removes the image fill.
fn configure_image(app: &mut PigmentApp, i: usize, m: &Value) -> Res<()> {
    use pigment_core::image_fill::ImageFill;
    if m.is_null() {
        app.doc.layers[i].image = None;
        return Ok(());
    }
    if app.doc.layers[i].is_paint() {
        return Err("`image` applies to fill layers".into());
    }
    let bases = app.image_bases();
    let mut fill = app.doc.layers[i].image.clone().unwrap_or_default();
    let set = match m {
        Value::String(d) => Some(d.as_str()),
        Value::Object(_) => s(m, "tile_set"),
        _ => return Err("`image` must be a tile set folder, an object or null".into()),
    };
    if let Some(dir) = set {
        fill.images = ImageFill::from_tile_set(dir, &bases)?;
    }
    if m.is_object() {
        for c in ImageChannel::ALL {
            match m.get(c.id()) {
                None => {}
                Some(Value::Null) => *fill.images.get_mut(c) = None,
                Some(Value::String(p)) => *fill.images.get_mut(c) = Some(p.clone()),
                Some(_) => return Err(format!("`image.{}` must be a path or null", c.id())),
            }
        }
        if let Some(p) = s(m, "projection") {
            fill.projection = Projection::from_id(p).ok_or_else(|| format!("unknown projection `{p}` (uv, triplanar)"))?;
        }
        if let Some(t) = f2(m, "tiling")? {
            fill.tiling = t;
        }
        if let Some(o) = f2(m, "offset")? {
            fill.offset = o;
        }
        if let Some(x) = f(m, "rotation") {
            fill.rotation = x;
        }
        if let Some(x) = f(m, "tile_size") {
            if x <= 0.0 {
                return Err("`tile_size` must be > 0 (metres per repeat)".into());
            }
            fill.tile_size = x;
        }
        if let Some(x) = f(m, "blend_sharpness").or_else(|| f(m, "sharpness")) {
            fill.blend_sharpness = x.clamp(0.1, 64.0);
        }
        if let Some(c) = m.get("tint").and_then(Value::as_array) {
            for (k, x) in c.iter().take(3).enumerate() {
                fill.tint[k] = x.as_f64().unwrap_or(1.0).max(0.0) as f32;
            }
        }
        if let Some(r) = f2(m, "roughness_range")? {
            fill.roughness_range = r.map(|x| x.clamp(0.0, 1.0));
        }
        if let Some(x) = f(m, "height_scale") {
            fill.height_scale = x;
        }
        if let Some(x) = f(m, "normal_strength") {
            fill.normal_strength = x;
        }
    }
    if fill.images.is_empty() {
        return Err("an image fill needs at least one image (tile_set, base_color, roughness, height or normal)".into());
    }
    let missing = fill.missing(&bases);
    if !missing.is_empty() {
        return Err(format!("image not found: {}", missing.join(", ")));
    }
    let l = &mut app.doc.layers[i];
    for (c, _) in fill.images.iter() {
        l.channels.get_mut(c.channel()).enabled = true;
    }
    l.image = Some(fill);
    app.ts.tiles.retry_missing();
    Ok(())
}

/// Brush material values from a JSON object (same keys as a fill's `values`).
fn apply_material_values(v: &mut MaterialValues, vals: &Value) {
    let rgb = |k: &str, out: &mut [f32; 3]| {
        if let Some(c) = vals.get(k).and_then(Value::as_array) {
            for (i, x) in c.iter().take(3).enumerate() {
                out[i] = x.as_f64().unwrap_or(0.0).clamp(0.0, 1.0) as f32;
            }
        }
    };
    rgb("base_color", &mut v.base_color);
    rgb("emissive", &mut v.emissive);
    if let Some(x) = f(vals, "roughness") {
        v.roughness = x.clamp(0.0, 1.0);
    }
    if let Some(x) = f(vals, "metallic") {
        v.metallic = x.clamp(0.0, 1.0);
    }
    if let Some(x) = f(vals, "height") {
        v.height = x.clamp(-1.0, 1.0);
    }
    if let Some(x) = f(vals, "emissive_strength") {
        v.emissive_strength = x.max(0.0);
    }
    if let Some(x) = f(vals, "opacity") {
        v.opacity = x.clamp(0.0, 1.0);
    }
    if let Some(x) = f(vals, "transmission") {
        v.transmission = x.clamp(0.0, 1.0);
    }
    if let Some(x) = f(vals, "coat") {
        v.coat = x.clamp(0.0, 1.0);
    }
    if let Some(x) = f(vals, "coat_roughness") {
        v.coat_roughness = x.clamp(0.0, 1.0);
    }
    if let Some(x) = f(vals, "flake") {
        v.flake = x.clamp(0.0, 1.0);
    }
}

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
    apply_weather_fields(g, m);
}

/// Named parameters of the weathering / pattern generators, mapped onto the
/// generic slots (see `GeneratorKind::Leaks` .. `WindowGrid`):
///   leaks:       drip_length (m)          -> curvature_weight
///   tiles:       variant bricks|square|hex, mortar -> ao_influence, aspect -> curvature_weight
///   window_grid: cell_size (m) -> scale, fill -> amount, frame -> ao_influence, aspect -> curvature_weight
fn apply_weather_fields(g: &mut Generator, m: &Value) {
    // `generator: "hex"` / "bricks" / "square" picks the tile variant too
    let named = s(m, "variant").or(s(m, "generator").filter(|k| GeneratorKind::TILE_VARIANTS.contains(k) || *k == "brick"));
    if let Some(v) = named {
        let v = if v == "brick" { "bricks" } else { v };
        if let Some(i) = GeneratorKind::TILE_VARIANTS.iter().position(|t| *t == v) {
            g.variant = i as u32;
        }
    } else if let Some(v) = m.get("variant").and_then(Value::as_u64) {
        g.variant = v.min(2) as u32;
    }
    for k in ["drip_length", "aspect"] {
        if let Some(x) = f(m, k) {
            g.curvature_weight = x;
        }
    }
    for k in ["mortar", "frame"] {
        if let Some(x) = f(m, k) {
            g.ao_influence = x;
        }
    }
    if let Some(x) = f(m, "cell_size") {
        g.noise_scale = x;
    }
    if let Some(x) = f(m, "fill") {
        g.amount = x;
    }
}

/// Session tests take turns on the shared GPU: each Session allocates a
/// texture set, and running them all at once runs a shared GPU out of memory.
#[cfg(test)]
pub(crate) fn gpu_lock() -> std::sync::MutexGuard<'static, ()> {
    static L: std::sync::Mutex<()> = std::sync::Mutex::new(());
    L.lock().unwrap_or_else(|e| e.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scripted_session_builds_a_material_and_exports() {
        let _gpu = gpu_lock();
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
    fn glass_and_cut_outs_flow_through_fill_brush_viewport_export_and_save() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Steel" })).unwrap();
        let out = std::env::temp_dir().join(format!("pigment-glass-{}", std::process::id()));
        // a solid material exports no opacity / transmission maps and an RGB base colour
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Solid" })).unwrap();
        assert!(!e["files"].to_string().contains("Opacity"), "{e}");
        // glass fill over everything
        s.add_layer(&json!({ "name": "Glass", "values": { "base_color": [0.9, 0.95, 1.0], "roughness": 0.05, "opacity": 0.3, "transmission": 1.0 } })).unwrap();
        let l = s.layers();
        let glass = l.as_array().unwrap().iter().find(|l| l["name"] == "Glass").unwrap();
        assert!(glass["channels"].to_string().contains("opacity") && glass["channels"].to_string().contains("transmission"), "{glass}");
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Glass" })).unwrap();
        let op = image::open(out.join("Glass_Opacity.png")).unwrap().to_luma8();
        let tr = image::open(out.join("Glass_Transmission.png")).unwrap().to_luma8();
        let mid = |i: &image::GrayImage| i.get_pixel(i.width() / 2, i.height() / 2).0[0];
        assert!((mid(&op) as i32 - 77).abs() <= 3, "opacity {}", mid(&op));
        assert!(mid(&tr) >= 250, "transmission {}", mid(&tr));
        // unreal: alpha rides in BaseColor
        s.export_textures(&json!({ "dir": out, "preset": "unreal", "name": "GlassUE" })).unwrap();
        let bc = image::open(out.join("GlassUE_BaseColor.png")).unwrap();
        assert_eq!(bc.color(), image::ColorType::Rgba8);
        // the viewport shows the background through the glass: the material
        // view differs from an opaque render of the same values
        let a = s.render(&json!({ "width": 160, "height": 120 })).unwrap();
        s.update_layer(&json!({ "layer": "Glass", "values": { "opacity": 1.0, "transmission": 0.0 } })).unwrap();
        let b = s.render(&json!({ "width": 160, "height": 120 })).unwrap();
        assert_ne!(a.png, b.png);
        let ov = s.render(&json!({ "view": "opacity", "width": 160, "height": 120 })).unwrap();
        assert!(ov.png.len() > 100);
        // brush: punch a hole (opacity 0) on the paint layer
        s.update_layer(&json!({ "layer": "Glass", "visible": false })).unwrap();
        let p = s.paint_stroke(&json!({ "points": [[0.4, 0.5], [0.6, 0.5]], "size": 60, "yaw": 0, "pitch": 0, "values": { "opacity": 0.0 }, "channels": ["opacity"] })).unwrap();
        assert_eq!(p["painted_on"], "Paint");
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Holes" })).unwrap();
        let holes = image::open(out.join("Holes_Opacity.png")).unwrap().to_luma8();
        assert!(holes.pixels().any(|p| p.0[0] < 10), "no hole painted");
        assert!(holes.pixels().any(|p| p.0[0] == 255));
        // save + reopen keeps the painted opacity
        s.save_project(&json!({ "path": out.join("holes.pigment") })).unwrap();
        assert!(out.join("holes.pigment/layers").read_dir().unwrap().flatten().any(|d| d.path().join("opacity.png").exists()));
        s.open_project(&json!({ "path": out.join("holes.pigment") })).unwrap();
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Reopened" })).unwrap();
        let again = image::open(out.join("Reopened_Opacity.png")).unwrap().to_luma8();
        assert_eq!(holes.as_raw(), again.as_raw());
        std::fs::remove_dir_all(out).ok();
    }

    #[test]
    fn clearcoat_and_flake_flow_through_fill_brush_folder_viewport_export_and_save() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Steel" })).unwrap();
        let out = std::env::temp_dir().join(format!("pigment-coat-{}", std::process::id()));
        // uncoated: no coat maps
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Bare" })).unwrap();
        assert!(!e["files"].to_string().contains("Coat") && !e["files"].to_string().contains("Flake"), "{e}");
        let bare = s.render(&json!({ "width": 160, "height": 120 })).unwrap();
        // candy paint fill: coat, coat roughness and flake channels on
        s.add_layer(&json!({ "name": "Paint job", "values": { "base_color": [0.5, 0.05, 0.3], "metallic": 0.6, "roughness": 0.3, "coat": 1.0, "coat_roughness": 0.1, "flake": 0.6 } })).unwrap();
        let l = s.layers();
        let pj = l.as_array().unwrap().iter().find(|l| l["name"] == "Paint job").unwrap();
        for c in ["coat", "coat_roughness", "flake"] {
            assert!(pj["channels"].as_array().unwrap().contains(&json!(c)), "{pj}");
        }
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Car" })).unwrap();
        assert!(e["files"].to_string().contains("Car_Coat.png") && e["files"].to_string().contains("Car_CoatRoughness.png") && e["files"].to_string().contains("Car_Flake.png"), "{e}");
        let mid = |n: &str| {
            let i = image::open(out.join(n)).unwrap().to_luma8();
            i.get_pixel(i.width() / 2, i.height() / 2).0[0] as i32
        };
        assert!(mid("Car_Coat.png") >= 250, "coat {}", mid("Car_Coat.png"));
        assert!((mid("Car_CoatRoughness.png") - 26).abs() <= 2, "coat roughness {}", mid("Car_CoatRoughness.png"));
        assert!((mid("Car_Flake.png") - 153).abs() <= 2, "flake {}", mid("Car_Flake.png"));
        // the normal map survives the packed accumulator: still flat-ish (z up)
        let nrm = image::open(out.join("Car_Normal_OpenGL.png")).unwrap().to_rgb8();
        let np = nrm.get_pixel(256, 256).0;
        assert!(np[2] > 240, "normal {np:?}");
        // material.json lists the coat maps
        let side: Value = serde_json::from_str(&std::fs::read_to_string(out.join("material.json")).unwrap()).unwrap();
        let ch = side["materials"]["Car"]["channels"].as_array().unwrap();
        assert!(ch.contains(&json!("coat")) && ch.contains(&json!("coat_roughness")) && ch.contains(&json!("flake")), "{side}");
        // the viewport shows the coat: renders differ, coat views work
        let coated = s.render(&json!({ "width": 160, "height": 120 })).unwrap();
        assert_ne!(bare.png, coated.png);
        for v in ["coat", "coat roughness", "flake"] {
            assert!(s.render(&json!({ "view": v, "width": 64, "height": 48 })).unwrap().png.len() > 100, "{v}");
        }
        // a dirt fill with coat 0 strips the coat (giving the key turns the channel on)
        s.add_layer(&json!({ "name": "Strip", "values": { "base_color": [0.2, 0.15, 0.1], "coat": 0.0 } })).unwrap();
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Stripped" })).unwrap();
        assert!(!out.join("Stripped_Coat.png").exists(), "coat map written for an uncoated result");
        s.delete_layer(&json!({ "layer": "Strip" })).unwrap();
        // folder at half opacity halves the coat
        s.add_layer(&json!({ "name": "Clear", "kind": "folder" })).unwrap();
        s.update_layer(&json!({ "layer": "Paint job", "parent": "Clear" })).unwrap();
        s.update_layer(&json!({ "layer": "Clear", "opacity": 0.5 })).unwrap();
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Half" })).unwrap();
        assert!((mid("Half_Coat.png") - 128).abs() <= 4, "half coat {}", mid("Half_Coat.png"));
        s.delete_layer(&json!({ "layer": "Clear" })).unwrap();
        // brush: paint a coat stroke on the paint layer
        let p = s.paint_stroke(&json!({ "points": [[0.4, 0.5], [0.6, 0.5]], "size": 60, "yaw": 0, "pitch": 0, "values": { "coat": 1.0, "coat_roughness": 0.5 }, "channels": ["coat", "coat_roughness"] })).unwrap();
        assert_eq!(p["painted_on"], "Paint");
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Brushed" })).unwrap();
        let coat = image::open(out.join("Brushed_Coat.png")).unwrap().to_luma8();
        assert!(coat.pixels().any(|p| p.0[0] > 245), "no coat painted");
        assert!(coat.pixels().any(|p| p.0[0] == 0));
        // save + reopen keeps the painted coat
        s.save_project(&json!({ "path": out.join("coat.pigment") })).unwrap();
        assert!(out.join("coat.pigment/layers").read_dir().unwrap().flatten().any(|d| d.path().join("coat.png").exists()));
        s.open_project(&json!({ "path": out.join("coat.pigment") })).unwrap();
        s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "Reopened" })).unwrap();
        let again = image::open(out.join("Reopened_Coat.png")).unwrap().to_luma8();
        assert_eq!(coat.as_raw(), again.as_raw());
        // presets
        let lib = s.library();
        assert!(lib["materials"].as_array().unwrap().iter().any(|m| m["name"] == "Candy paint" && m["flake"].as_f64().unwrap() > 0.0), "{lib}");
        std::fs::remove_dir_all(out).ok();
    }

    #[test]
    fn neon_glows_in_material_export_and_brush() {
        let _gpu = gpu_lock();
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
        let _gpu = gpu_lock();
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
        let _gpu = gpu_lock();
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
        let _gpu = gpu_lock();
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
    /// Variants: seeded part subsets, decal enable/disable and image swaps
    /// export as separate texture sets and leave the authored project intact.
    #[test]
    fn export_variants_makes_distinct_sets_and_restores_the_project() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Matte black" })).unwrap();
        let n = s.list_parts().as_array().unwrap().len() as u64;
        let all: Vec<u64> = (0..n).collect();
        s.add_layer(&json!({ "name": "Glow", "material": "Neon green", "mask": { "parts": all }, "part_subset": { "from": 0.0, "to": 0.5, "salt": 3 } })).unwrap();
        s.add_layer(&json!({ "kind": "paint", "name": "Signs" })).unwrap();
        let decal = |img: &str| root.join("assets/decals").join(img);
        s.project_decal(&json!({ "layer": "Signs", "image": decal("neon_open.png"), "rect": [0.25, 0.3, 0.75, 0.6], "tint": [1.0, 0.2, 0.7], "emissive_strength": 5.0, "variant": "shop" })).unwrap();
        s.project_decal(&json!({ "layer": "Signs", "image": decal("neon_bar.png"), "rect": [0.25, 0.3, 0.75, 0.6], "tint": [0.2, 0.9, 1.0], "emissive_strength": 5.0, "variant": "shop", "enabled": false })).unwrap();
        let layers = s.layers().to_string();
        assert!(layers.contains("\"neon_bar\"") && layers.contains("\"part_subset\""), "{layers}");
        let signs_res = s.app.doc.layers.iter().find(|l| l.name == "Signs").unwrap().paint_res().unwrap();
        let signs_px = io::read_layer(&s.rs.device, &s.rs.queue, &s.app.ts, signs_res).unwrap();
        let doc_before = s.app.doc.clone();

        // a typo is an error and stores nothing
        let bad = s.export_variants(&json!({ "dir": "x", "variants": [{ "name": "a", "enable": ["neon_baar"] }] }));
        assert!(bad.unwrap_err().contains("neon_baar"));
        assert!(s.app.doc.variants.defs.is_empty());

        let out = std::env::temp_dir().join(format!("pigment-variants-{}", std::process::id()));
        std::fs::remove_dir_all(&out).ok();
        let r = s
            .export_variants(&json!({ "dir": out, "name": "Box", "variants": [
                { "name": "open", "seed": 1 },
                { "name": "bar", "seed": 2, "disable": ["neon_open"], "enable": ["neon_bar"] },
                { "name": "swapped", "seed": 1, "swaps": { "neon_open": { "image": decal("neon_ramen.png"), "tint": [1.0, 0.5, 0.1] } } },
                { "name": "dark", "seed": 1, "disable": ["*", "Glow"] }
            ], "preview": { "width": 160, "height": 120, "dir": out.join("previews") } }))
            .unwrap();
        assert_eq!(r["variants"].as_array().unwrap().len(), 4, "{r}");
        let emis = |v: &str| image::open(out.join(format!("Box__{v}/Box_Emissive.png"))).unwrap().to_rgb8();
        for v in ["open", "bar", "swapped", "dark"] {
            assert!(out.join(format!("Box__{v}/Box_BaseColor.png")).exists(), "{v}");
            assert!(out.join(format!("previews/Box__{v}.png")).exists(), "{v}");
        }
        let lit = |img: &image::RgbImage| img.pixels().filter(|p| p.0.iter().any(|&c| c > 40)).count();
        let (open, bar, swapped, dark) = (emis("open"), emis("bar"), emis("swapped"), emis("dark"));
        assert!(lit(&open) > 1000, "open glows");
        assert_eq!(lit(&dark), 0, "everything off is dark");
        assert_ne!(open, bar, "seed + decal switch change the emission");
        assert_ne!(open, swapped, "image swap changes the emission");
        // the replay reproduces the authored decal exactly: same seed, same decal
        let again = s.export_variants(&json!({ "dir": out, "name": "Box", "only": ["open"] })).unwrap();
        assert_eq!(again["variants"][0]["decals_replayed"], 0, "untouched layer isn't replayed");
        assert_eq!(emis("open"), open);

        // the authored project is untouched, and the definitions are stored
        let mut doc_after = s.app.doc.clone();
        assert_eq!(doc_after.variants.defs.len(), 4);
        doc_after.variants.defs.clear();
        doc_after.next_id = doc_before.next_id;
        assert_eq!(doc_after, doc_before);
        assert_eq!(io::read_layer(&s.rs.device, &s.rs.queue, &s.app.ts, signs_res).unwrap(), signs_px);
        let dry = s.export_variants(&json!({ "dry_run": true })).unwrap();
        assert_eq!(dry["variants"][1]["decals"][0][0], "neon_bar", "{dry}");
        s.save_project(&json!({ "path": out.join("box.pigment") })).unwrap();
        let manifest = std::fs::read_to_string(out.join("box.pigment/project.json")).unwrap();
        assert!(manifest.contains("\"swapped\"") && manifest.contains("\"decals\""));
        std::fs::remove_dir_all(out).ok();
    }

    /// Decals aimed at a world-space box (an area of a wall that is part of a bigger piece).
    #[test]
    fn decal_on_a_world_box() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Matte black" })).unwrap();
        s.add_layer(&json!({ "kind": "paint", "name": "Signs" })).unwrap();
        let (c, r) = s.app.mesh.bounding_sphere();
        let img = root.join("assets/decals/neon_open.png");
        let glow = |s: &mut Session| -> usize {
            let im = s.render(&json!({ "view": "emission", "width": 256, "height": 256 })).unwrap();
            image::load_from_memory(&im.png).unwrap().to_luma8().pixels().filter(|p| p.0[0] > 60).count()
        };
        let e = s.project_decal(&json!({ "image": img, "box": { "center": [c.x, c.y, c.z], "size": [r, r, r] }, "facing": "up" }));
        assert!(e.unwrap_err().contains("facing"));
        s.project_decal(&json!({ "image": img, "box": { "center": [c.x, c.y, c.z], "size": [r, r, r] }, "facing": "+y", "emissive_strength": 5.0 })).unwrap();
        assert!(glow(&mut s) > 300, "decal from above landed on the top");
        assert!(s.project_decal(&json!({ "image": img, "box": { "min": [0, 0] } })).is_err());
    }

    #[test]
    fn bloom_lighting_presets_and_contact_sheets() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let tmp = std::env::temp_dir().join(format!("pigment-look-{}", std::process::id()));
        s.new_project(&json!({ "mesh": root.join("assets/neon_tubes.glb"), "resolution": 512, "material": "Neon pink" })).unwrap();
        let shot = |s: &mut Session, extra: Value| -> image::RgbaImage {
            let mut a = json!({ "yaw": 0, "pitch": 5, "width": 320, "height": 240, "background": false, "path": tmp.join("shot.png") });
            a.as_object_mut().unwrap().extend(extra.as_object().unwrap().clone());
            image::load_from_memory(&s.render(&a).unwrap().png).unwrap().to_rgba8()
        };
        // bloom spreads the neon's light into the (dark) surroundings
        let off = shot(&mut s, json!({ "lighting": "night", "bloom": false }));
        let on = shot(&mut s, json!({ "bloom": { "intensity": 0.8, "radius": 0.8 } }));
        let pinkish = |img: &image::RgbaImage| img.pixels().filter(|p| p.0[0] as i32 > p.0[1] as i32 + 25).count();
        let (p_off, p_on) = (pinkish(&off), pinkish(&on));
        assert!(p_on > p_off + p_off / 4, "bloom should add a pink halo ({p_off} -> {p_on} pixels)");
        let sum = |img: &image::RgbaImage| img.pixels().map(|p| p.0[0] as u64 + p.0[1] as u64 + p.0[2] as u64).sum::<u64>();
        assert!(sum(&on) > sum(&off));
        // channel views never bloom
        let e1 = shot(&mut s, json!({ "view": "emission" }));
        let e2 = shot(&mut s, json!({ "view": "emission", "bloom": false }));
        assert_eq!(e1.as_raw(), e2.as_raw());

        // night is much darker than studio on a non-emissive material
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Olive drab" })).unwrap();
        // (measured on the box only, not the gradient background)
        let sum = |img: &image::RgbaImage| sum(&image::imageops::crop_imm(img, 110, 95, 100, 50).to_image());
        let studio = sum(&shot(&mut s, json!({ "lighting": "studio" })));
        let night = sum(&shot(&mut s, json!({ "lighting": "night" })));
        let overcast = sum(&shot(&mut s, json!({ "lighting": "overcast" })));
        assert!(night * 2 < studio && night * 2 < overcast, "night {night}, studio {studio}, overcast {overcast}");
        assert!(s.render(&json!({ "lighting": "disco" })).is_err());
        assert!(s.render(&json!({ "hdri": tmp.join("missing.hdr") })).is_err());

        // a preset written to .hdr loads back as an HDRI
        let hdr = tmp.join("night.hdr");
        let r = s.export_lighting(&json!({ "lighting": "night", "path": hdr, "width": 256 })).unwrap();
        assert_eq!(r["height"], 128);
        let via_hdri = sum(&shot(&mut s, json!({ "hdri": hdr })));
        assert!(via_hdri * 2 < studio, "HDRI night {via_hdri} vs studio {studio}");
        assert_eq!(s.app.env.source, hdr.to_string_lossy());

        // contact sheets: turntable and named views, tile size = width x height
        let t = s.render_turntable(&json!({ "frames": 6, "width": 128, "height": 96, "columns": 3, "lighting": "studio", "path": tmp.join("turn.png") })).unwrap();
        let img = image::load_from_memory(&t.png).unwrap();
        assert_eq!((img.width(), img.height()), (3 * 128 + 16, 2 * 96 + 12));
        let v = s.render(&json!({ "views": "all", "width": 128, "height": 128, "path": tmp.join("views.png") })).unwrap();
        let img = image::load_from_memory(&v.png).unwrap();
        assert_eq!((img.width(), img.height()), (3 * 128 + 16, 2 * 128 + 12));
        assert!(v.path.exists());
        assert!(s.render(&json!({ "views": ["front", "sideways"] })).is_err());
        std::fs::remove_dir_all(tmp).ok();
    }

    /// export_variants previews ignore the look left by earlier renders (they use
    /// only the `preview` args over the defaults) and restore the session look.
    #[test]
    fn variant_previews_are_deterministic() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let r = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": r.join("assets/ammo_box.glb"), "resolution": 512, "material": "Olive drab" })).unwrap();
        s.add_layer(&json!({ "name": "Glow", "material": "Neon green", "variant": "lights" })).unwrap();
        let out = std::env::temp_dir().join(format!("pigment-preview-{}", std::process::id()));
        std::fs::remove_dir_all(&out).ok();
        let export = |s: &mut Session, sub: &str, preview: Value| -> Vec<u8> {
            let mut p = preview;
            p["dir"] = json!(out.join(sub));
            s.export_variants(&json!({ "dir": out.join("maps"), "name": "Box", "variants": [{ "name": "on", "seed": 1 }], "preview": p })).unwrap();
            image::open(out.join(sub).join("Box__on.png")).unwrap().to_rgba8().into_raw()
        };
        let base = json!({ "yaw": 30, "pitch": 15, "width": 160, "height": 120 });
        let fresh = export(&mut s, "a", base.clone());
        // a render with a very different look must not leak into the preview
        s.render(&json!({ "lighting": "night", "bloom": false, "exposure": 3.0, "env_rotation": 90, "background": false, "width": 200, "height": 100 })).unwrap();
        let after = export(&mut s, "b", base.clone());
        assert_eq!(fresh, after, "preview depends on the previous render's look");
        // ...and the session keeps its own look
        assert_eq!(s.app.env.source, "night");
        assert!(!s.app.view.bloom.enabled && s.app.view.exposure == 3.0 && !s.app.view.show_env);
        assert_eq!(s.size, [200, 100]);
        // explicit preview args still apply
        let night = export(&mut s, "c", json!({ "yaw": 30, "pitch": 15, "width": 160, "height": 120, "lighting": "night" }));
        assert_ne!(fresh, night);
        assert_eq!(s.app.env.source, "night");
        std::fs::remove_dir_all(out).ok();
    }

    #[test]
    fn part_queries_project_info_and_named_errors() {
        let _gpu = gpu_lock();
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
        // a mask can take the shape query directly
        let q = json!({ "sort": "area", "limit": 2 });
        s.add_layer(&json!({ "name": "Where", "mask": { "parts_where": q } })).unwrap();
        let picked: Vec<u64> = s.pick_parts(&json!({ "shape": q })).unwrap()["parts"].as_array().unwrap().iter().map(|x| x.as_u64().unwrap()).collect();
        let mut got: Vec<u64> = s.layers().as_array().unwrap().iter().find(|l| l["name"] == "Where").unwrap()["mask"]["parts"].as_array().unwrap().iter().map(|x| x.as_u64().unwrap()).collect();
        got.sort();
        let mut want = picked.clone();
        want.sort();
        assert_eq!(got, want);
        assert!(s.add_layer(&json!({ "mask": { "parts_where": { "min_area": 1e9 } } })).unwrap_err().contains("matched no parts"));
        s.delete_layer(&json!({ "layer": "Where" })).unwrap();
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
