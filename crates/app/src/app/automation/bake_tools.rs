//! MCP: high-to-low baking and ID maps (`bake` with `high_mesh` / `maps`).

use super::*;
use pigment_core::hibake::{BakeMap, HighBake};

impl Session {
    /// `bake {high_mesh, cage, maps, ...}`: bake the high mesh onto this
    /// project's mesh, write the maps, apply AO / curvature, the baked normal
    /// layer and the ID map.
    pub(super) fn bake_high(&mut self, a: &Value) -> Res<Value> {
        let high_path = s(a, "high_mesh");
        let maps: Vec<BakeMap> = match a.get("maps").and_then(Value::as_array) {
            Some(list) => {
                let mut v = Vec::new();
                for (k, m) in list.iter().enumerate() {
                    let id = m.as_str().ok_or_else(|| format!("`maps[{k}]` must be a map name"))?;
                    v.push(BakeMap::from_id(id).ok_or_else(|| format!("`maps[{k}]` = \"{id}\": unknown map (one of: {})", BakeMap::ALL.iter().map(|m| m.id()).collect::<Vec<_>>().join(", ")))?);
                }
                v.dedup();
                v
            }
            None if high_path.is_some() => vec![BakeMap::Normal, BakeMap::Ao, BakeMap::Curvature, BakeMap::Height, BakeMap::ColorId],
            None => vec![BakeMap::MaterialId],
        };
        if maps.is_empty() {
            return Err("`maps` is empty".into());
        }
        let high = match high_path {
            Some(p) => Some(Mesh::load(Path::new(p)).map_err(|e| format!("`high_mesh` {p}: {e:#}"))?),
            None => {
                if maps.iter().any(|m| m.needs_high()) {
                    return Err(format!("maps {:?} need `high_mesh` (only material_id bakes from the project mesh alone)", maps.iter().filter(|m| m.needs_high()).map(|m| m.id()).collect::<Vec<_>>()));
                }
                None
            }
        };
        let mut hb = HighBake::new(high_path.unwrap_or(""), maps);
        hb.cage = match a.get("cage") {
            None | Some(Value::Null) => None,
            Some(Value::String(x)) if x == "auto" => None,
            Some(v) => Some(v.as_f64().filter(|x| *x > 0.0).ok_or("`cage` must be a distance in metres (> 0) or \"auto\"")? as f32),
        };
        hb.id_from_vertex_colors = match s(a, "id_source").unwrap_or("material") {
            "material" | "materials" => false,
            "vertex_color" | "vertex_colors" => true,
            x => return Err(format!("`id_source` = \"{x}\": material or vertex_color")),
        };
        if let Some(n) = a.get("ao_samples").and_then(Value::as_u64) {
            hb.ao_samples = (n as u32).clamp(4, 512);
        }
        if let Some(x) = f(a, "ao_distance") {
            hb.ao_distance = x.max(0.001);
        }
        if let Some(d) = s(a, "dir") {
            hb.dir = d.to_string();
        }
        if !self.app.ts.baked {
            self.app.bake(&self.rs);
        }
        let normal_layer = a.get("normal_layer").and_then(Value::as_bool).unwrap_or(true);
        let r = self.app.bake_high(&self.rs, high.as_ref(), hb, normal_layer)?;
        self.settle();
        Ok(json!({
            "maps": r.files.iter().map(|(m, p)| (m.id().to_string(), json!(p))).collect::<serde_json::Map<String, Value>>(),
            "cage": r.cage,
            "hit_rate": r.hit_rate,
            "ms": r.ms.round(),
            "id_map": self.app.doc.id_map,
            "layers": self.layers(),
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::super::gpu_lock;
    use super::*;

    /// The generated bevelled box (low) and its sculpted high version on disk.
    pub(crate) fn pair_on_disk(tag: &str) -> (PathBuf, PathBuf) {
        let dir = std::env::temp_dir().join(format!("pigment-hibake-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let (low, high) = pigment_core::hibake::test_pair();
        let (lp, hp) = (dir.join("box_low.obj"), dir.join("box_high.obj"));
        low.write_obj(&lp).unwrap();
        high.write_obj(&hp).unwrap();
        (lp, hp)
    }

    #[test]
    fn high_to_low_bake_and_id_masks_over_mcp() {
        let _g = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let (lp, hp) = pair_on_disk("mcp");
        s.new_project(&json!({ "mesh": lp, "resolution": 512, "material": "Gunmetal" })).unwrap();
        // the reloaded high mesh keeps its three materials
        let high = Mesh::load(&hp).unwrap();
        assert_eq!(high.material_count(), 3, "materials survive the OBJ round trip: {:?}", high.material_names);
        assert!(s.bake(&json!({ "maps": ["normal"] })).unwrap_err().contains("high_mesh"));
        let shot = |s: &mut Session, view: &str| image::load_from_memory(&s.render(&json!({ "yaw": 20, "pitch": 25, "width": 256, "height": 256, "view": view })).unwrap().png).unwrap().to_rgb8();
        let flat_normals = shot(&mut s, "normal");
        let r = s.bake(&json!({ "high_mesh": hp, "maps": ["normal", "ao", "curvature", "height", "color_id", "material_id", "thickness", "position", "normal_object"] })).unwrap();
        assert!(r["hit_rate"].as_f64().unwrap() > 0.95, "{r}");
        for m in ["normal", "ao", "curvature", "height", "color_id", "material_id", "thickness", "position", "normal_object"] {
            let p = r["maps"][m].as_str().unwrap();
            assert!(Path::new(p).is_file(), "{m} written to {p}");
        }
        assert!(s.app.doc.layers.iter().any(|l| l.name == crate::app::hibake_app::BAKED_NORMAL_LAYER));
        assert!(s.app.doc.id_map.as_deref().is_some_and(|p| p.contains("color_id")));
        // the dents and grooves now bend the normals
        let baked = shot(&mut s, "normal");
        let diff = flat_normals.pixels().zip(baked.pixels()).filter(|(a, b)| (0..3).any(|k| (a.0[k] as i32 - b.0[k] as i32).abs() > 12)).count();
        assert!(diff > 500, "baked normal detail shows ({diff} pixels changed)");
        // ID mask: paint the lid (material 1) red
        let lid = pigment_core::hibake::id_color(1);
        s.add_layer(&json!({ "name": "Lid paint", "values": { "base_color": [1.0, 0.0, 0.0] }, "mask": { "id_color": { "color": lid, "tolerance": 0.05 } } })).unwrap();
        let m = {
            s.app.commit_doc_changes();
            s.app.ensure_composited(&s.rs);
            crate::render::io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts)
        };
        let n = m.size as usize;
        let red = |u0: f32, u1: f32, v0: f32, v1: f32| {
            (0..n * n)
                .filter(|i| {
                    let (u, v) = ((i % n) as f32 / n as f32, (i / n) as f32 / n as f32);
                    let p = &m.color[i * 4..];
                    u >= u0 && u < u1 && v >= v0 && v < v1 && p[0] > 180 && p[1] < 60
                })
                .count()
        };
        // top face is atlas cell 2 (u 2/3..1, v 0..0.5); the front (cell 4) has no lid
        let top = red(2.0 / 3.0, 1.0, 0.0, 0.5);
        let front = red(1.0 / 3.0, 2.0 / 3.0, 0.5, 1.0);
        assert!(top > 2000 && front == 0, "the ID mask picks the lid only (top {top}, front {front})");
        assert!(s.update_layer(&json!({ "layer": "Lid paint", "mask": { "id_color": { "color": [1, 2] } } })).is_err());
        // save + reopen keeps the bake, the ID map and the mask
        let dir = lp.parent().unwrap().join("proj.pigment");
        s.save_project(&json!({ "path": dir })).unwrap();
        s.open_project(&json!({ "path": dir })).unwrap();
        assert!(s.app.doc.bake.high.is_some() && s.app.doc.id_map.is_some());
        assert!(s.app.doc.layers.iter().any(|l| l.mask.as_ref().is_some_and(|m| m.id_color.is_some())));
        // material ID from the project mesh alone (one material here)
        let r = s.bake(&json!({ "maps": ["material_id"] })).unwrap();
        assert!(r["maps"]["material_id"].as_str().is_some());
    }
}
