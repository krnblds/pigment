//! MCP: texture sets and UDIM tiles (`new_project.texture_sets / udim /
//! udim_tiles`, `list_texture_sets`, the `texture_set` argument of layer tools).

use super::*;
use pigment_core::texsets::{self, SetSpec, UdimMove};

/// Tools that take `texture_set` (name, index, or "*" = every set).
pub const SET_TOOLS: [&str; 15] = [
    "add_layer",
    "update_layer",
    "delete_layer",
    "list_layers",
    "add_smart_material",
    "apply_smart_material",
    "save_smart_material",
    "add_filter",
    "update_filter",
    "remove_filter",
    "set_anchor",
    "paint_stroke",
    "project_decal",
    "scatter_decals",
    "bake",
];

impl Session {
    /// The sets a `texture_set` argument names.
    pub fn texture_set_scope(&self, v: &Value) -> Res<Vec<String>> {
        let names = self.app.set_names();
        match v {
            Value::String(s) if s == "*" => Ok(names),
            Value::String(s) => names.iter().find(|n| n.eq_ignore_ascii_case(s)).map(|n| vec![n.clone()]).ok_or_else(|| format!("`texture_set` = \"{s}\": no such texture set (sets: {})", names.join(", "))),
            Value::Number(n) => {
                let i = n.as_u64().unwrap_or(u64::MAX) as usize;
                names.get(i).map(|n| vec![n.clone()]).ok_or_else(|| format!("`texture_set` = {i}: there are {} sets", names.len()))
            }
            _ => Err("`texture_set` must be a set name, an index or \"*\"".into()),
        }
    }

    pub fn active_texture_set(&self) -> String {
        self.app.active_set_name()
    }

    pub fn activate_texture_set(&mut self, name: &str) -> Res<()> {
        self.app.activate_set(&self.rs, name)?;
        self.settle();
        Ok(())
    }

    /// `list_texture_sets`.
    pub fn list_texture_sets(&self) -> Value {
        let active = self.app.active_set_name();
        let mut out = vec![self.set_json(&self.app.doc, &self.app.mesh, &active)];
        if let Some(m) = &self.app.multi {
            for s in &m.parked {
                out.push(self.set_json(&s.doc, &s.mesh, &active));
            }
            let order = &m.order;
            out.sort_by_key(|v| order.iter().position(|n| v["name"] == **n).unwrap_or(usize::MAX));
        }
        json!({ "active": active, "texture_sets": out, "udim_tiles": self.app.multi.as_ref().map(|m| texsets::mesh_tiles(&m.full).into_iter().collect::<Vec<_>>()).unwrap_or_else(|| texsets::mesh_tiles(&self.app.mesh).into_iter().collect()) })
    }

    fn set_json(&self, doc: &Document, mesh: &Mesh, active: &str) -> Value {
        let name = crate::app::texsets_app::set_name(doc);
        let spec = doc.texture_set.clone().unwrap_or_else(|| SetSpec::all("main"));
        json!({
            "name": name, "active": name == active,
            "materials": spec.materials.iter().map(|m| json!({ "id": m, "name": mesh.material_name(*m) })).collect::<Vec<_>>(),
            "udim": spec.tile(), "resolution": doc.resolution,
            "triangles": mesh.triangle_count(), "layers": doc.layers.len(),
        })
    }

    /// new_project's texture-set arguments, after the mesh is loaded.
    pub(super) fn configure_sets(&mut self, a: &Value) -> Res<Option<Value>> {
        let moves = a.get("udim_tiles").and_then(Value::as_array).cloned().unwrap_or_default();
        let sets = a.get("texture_sets").cloned();
        let udim = a.get("udim").and_then(Value::as_bool).unwrap_or(false);
        if moves.is_empty() && sets.is_none() && !udim {
            return Ok(None);
        }
        // move selections to new UDIM tiles (UVs repacked to fill each tile)
        let mut gains = Vec::new();
        if !moves.is_empty() {
            let mut mesh = self.app.mesh.clone();
            for (k, m) in moves.iter().enumerate() {
                let tile = m.get("tile").and_then(Value::as_u64).filter(|t| (1001..=1100).contains(t)).ok_or_else(|| format!("`udim_tiles[{k}].tile` must be a UDIM number 1001..1100"))? as u32;
                let sel = self.tile_selection(&mesh, m, k)?;
                if !sel.iter().any(|x| *x) {
                    return Err(format!("`udim_tiles[{k}]` selects no triangles"));
                }
                let margin = f(m, "margin").unwrap_or(0.01).clamp(0.0, 0.2);
                let gain = texsets::move_to_tile(&mut mesh, &sel, tile, margin);
                self.app.doc.udim_moves.push(UdimMove::from_selection(tile, &sel, margin));
                gains.push(json!({ "tile": tile, "triangles": sel.iter().filter(|x| **x).count(), "density_gain": gain }));
            }
            self.app.load_mesh_gpu(&self.rs, mesh);
            self.app.committed = self.app.doc.clone();
        }
        // which sets
        let specs: Vec<SetSpec> = match &sets {
            None => texsets::sets_by_tile(&self.app.mesh, "tile"),
            Some(Value::String(s)) if s == "materials" => texsets::sets_by_material(&self.app.mesh),
            Some(Value::String(s)) if s == "udim" || s == "tiles" => texsets::sets_by_tile(&self.app.mesh, "tile"),
            Some(Value::Array(list)) => {
                let mut v = Vec::new();
                for (k, e) in list.iter().enumerate() {
                    let name = texsets::sanitize(s(e, "name").ok_or_else(|| format!("`texture_sets[{k}]` needs `name`"))?);
                    let mut materials = Vec::new();
                    for m in e.get("materials").and_then(Value::as_array).into_iter().flatten() {
                        let id = match m {
                            Value::Number(n) => n.as_u64().unwrap_or(0) as u32,
                            Value::String(n) => (0..self.app.mesh.material_count() as u32).find(|i| self.app.mesh.material_name(*i).eq_ignore_ascii_case(n)).ok_or_else(|| format!("`texture_sets[{k}].materials`: no material `{n}`"))?,
                            _ => return Err(format!("`texture_sets[{k}].materials` holds material ids or names")),
                        };
                        materials.push(id);
                    }
                    let udim = e.get("udim").and_then(Value::as_u64).map(|t| t as u32);
                    v.push(SetSpec { name, materials, udim });
                }
                v
            }
            Some(other) => return Err(format!("`texture_sets` must be \"materials\", \"udim\" or a list of {{name, materials, udim, resolution}}, got {other}")),
        };
        let res: Vec<Option<u32>> = match &sets {
            Some(Value::Array(list)) => list.iter().map(|e| e.get("resolution").and_then(Value::as_u64).map(|r| r as u32)).collect(),
            _ => Vec::new(),
        };
        for r in res.iter().flatten() {
            if !RESOLUTIONS.contains(r) {
                return Err(format!("texture set resolution must be one of {RESOLUTIONS:?}"));
            }
        }
        let names = self.app.split_sets(&self.rs, specs, &res)?;
        self.settle();
        Ok(Some(json!({ "texture_sets": names, "udim_moves": gains })))
    }

    /// Triangles a `udim_tiles` entry selects: `parts`, `parts_where`, `below_y` / `above_y` (centroid, metres).
    fn tile_selection(&self, mesh: &Mesh, m: &Value, k: usize) -> Res<Vec<bool>> {
        let n = mesh.triangle_count();
        let parts: Option<Vec<u32>> = match (m.get("parts"), m.get("parts_where")) {
            (None, None) => None,
            (p, w) => {
                let mut ids: Vec<u32> = p.and_then(Value::as_array).map(|a| a.iter().filter_map(|x| x.as_u64().map(|x| x as u32)).collect()).unwrap_or_default();
                if let Some(w) = w {
                    ids.extend(self.query_ids(w, &format!("udim_tiles[{k}].parts_where."))?);
                }
                Some(ids)
            }
        };
        let below = f(m, "below_y");
        let above = f(m, "above_y");
        if parts.is_none() && below.is_none() && above.is_none() {
            return Err(format!("`udim_tiles[{k}]` needs `parts`, `parts_where`, `below_y` or `above_y`"));
        }
        let tri_part = &self.app.parts.triangle_part;
        Ok((0..n)
            .map(|t| {
                let y = (0..3).map(|c| mesh.vertices[mesh.indices[t * 3 + c] as usize].position[1]).sum::<f32>() / 3.0;
                parts.as_ref().is_none_or(|p| tri_part.get(t).is_some_and(|id| p.contains(id))) && below.is_none_or(|b| y < b) && above.is_none_or(|b| y >= b)
            })
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::super::gpu_lock;
    use super::*;

    /// Texture sets by material and by UDIM tile over MCP: per-set layers,
    /// a stroke painting across sets, save / reopen, UDIM export names.
    #[test]
    fn texture_sets_and_udims_over_mcp() {
        let _g = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let dir = std::env::temp_dir().join(format!("pigment-sets-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let (_, high) = pigment_core::hibake::test_pair();
        // a mid-poly copy of the sculpted box with its 3 materials
        let mesh = pigment_core::hibake::rounded_box(glam::Vec3::new(0.5, 0.35, 0.4), 0.06, 16, None, Some(&|p: glam::Vec3| if p.y > 0.33 { 1 } else { 0 }));
        let mut mesh = mesh;
        mesh.material_names = vec!["body".into(), "lid".into()];
        let path = dir.join("box.obj");
        mesh.write_obj(&path).unwrap();
        drop(high);
        // by material: two sets, the lid at 1024
        let r = s.new_project(&json!({ "mesh": path, "resolution": 512, "material": "Teal paint", "texture_sets": [{ "name": "body", "materials": ["body"] }, { "name": "lid", "materials": [1], "resolution": 1024 }] })).unwrap();
        assert_eq!(r["texture_sets"], json!(["body", "lid"]));
        let l = s.list_texture_sets();
        assert_eq!(l["texture_sets"].as_array().unwrap().len(), 2);
        assert_eq!(l["texture_sets"][1]["resolution"], 1024);
        // a layer only in the lid set; list_layers per set
        s_call(&mut s, "add_layer", json!({ "name": "Lid red", "material": "Red paint", "texture_set": "lid" }));
        assert!(s.app.doc.layers.iter().all(|x| x.name != "Lid red"), "the body set is unchanged");
        let lid_layers = s_call(&mut s, "list_layers", json!({ "texture_set": "lid" }));
        assert!(lid_layers.to_string().contains("Lid red"));
        // "*" adds to every set
        s_call(&mut s, "add_layer", json!({ "name": "Grime", "material": "Grime", "opacity": 0.3, "texture_set": "*" }));
        for n in s.app.set_names() {
            s.activate_texture_set(&n).unwrap();
            assert!(s.app.doc.layers.iter().any(|x| x.name == "Grime"), "{n} has the grime layer");
        }
        s.activate_texture_set("body").unwrap();
        // a stroke across the lid edge paints both sets (the "Paint" layer exists in both)
        s.paint_stroke(&json!({ "points": [[0.5, 0.15], [0.5, 0.6]], "size": 40, "values": { "base_color": [1.0, 1.0, 0.0] }, "yaw": 0, "pitch": 30, "width": 512, "height": 512 })).unwrap();
        let yellow = |s: &mut Session| {
            s.app.commit_doc_changes();
            s.app.ensure_composited(&s.rs);
            let m = crate::render::io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts);
            m.color.chunks_exact(4).filter(|p| p[0] > 180 && p[1] > 160 && p[2] < 90).count()
        };
        let body = yellow(&mut s);
        s.activate_texture_set("lid").unwrap();
        let lid = yellow(&mut s);
        assert!(body > 200 && lid > 200, "the stroke lands in both sets (body {body}, lid {lid})");
        // save, reopen: two sets, layers intact
        let proj = dir.join("box.pigment");
        s.save_project(&json!({ "path": proj })).unwrap();
        s.open_project(&json!({ "path": proj })).unwrap();
        assert_eq!(s.app.set_names(), vec!["body".to_string(), "lid".to_string()]);
        s.activate_texture_set("lid").unwrap();
        assert!(s.app.doc.layers.iter().any(|x| x.name == "Lid red"));
        assert_eq!(s.app.ts.res, 1024);
        // export: <name>_<set>_<map>.<udim>.png
        let out = dir.join("export");
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "box" })).unwrap();
        let files: Vec<String> = e["files"].as_array().unwrap().iter().map(|f| f.as_str().unwrap().replace('\\', "/")).collect();
        assert!(files.iter().any(|f| f.ends_with("box_lid_BaseColor.1001.png")), "{files:?}");
        assert!(files.iter().any(|f| f.ends_with("box_body_BaseColor.1001.png")));

        // UDIM: move the top to tile 1002 at a higher density
        let r = s.new_project(&json!({ "mesh": path, "resolution": 512, "udim_tiles": [{ "tile": 1002, "above_y": 0.2 }] })).unwrap();
        assert_eq!(r["texture_sets"], json!(["tile_1001", "tile_1002"]));
        assert!(r["udim_moves"][0]["density_gain"].as_f64().unwrap() > 1.5, "{r}");
        let e = s.export_textures(&json!({ "dir": out, "preset": "separate", "name": "udim" })).unwrap();
        let files = e["files"].to_string();
        assert!(files.contains("udim_tile_1002_BaseColor.1002.png") && files.contains("udim_tile_1001_BaseColor.1001.png"), "{files}");
        assert!(s.new_project(&json!({ "mesh": path, "udim_tiles": [{ "tile": 1002 }] })).unwrap_err().contains("needs"));
        std::fs::remove_dir_all(dir).ok();
    }

    /// Dispatch like pigment-mcp does with `texture_set`.
    fn s_call(s: &mut Session, tool: &str, a: Value) -> Value {
        let names = s.texture_set_scope(&a["texture_set"]).unwrap();
        let prev = s.active_texture_set();
        let mut a = a;
        a.as_object_mut().unwrap().remove("texture_set");
        let mut last = Value::Null;
        for n in names {
            s.activate_texture_set(&n).unwrap();
            last = match tool {
                "add_layer" => s.add_layer(&a).unwrap(),
                "list_layers" => s.list_layers(&a),
                _ => unreachable!(),
            };
        }
        s.activate_texture_set(&prev).unwrap();
        last
    }
}
