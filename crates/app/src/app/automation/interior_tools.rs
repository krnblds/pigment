//! MCP: interior mapping ("parallax windows").
//!
//! * `export_window_map`: a window map of the loaded mesh: a UV-space texture
//!   whose texels hold the pane index + 1 of the glass part under them, and
//!   a JSON of every pane's frame (centre, outward normal, right / up, size in
//!   metres, centre UV). Game and Blender shaders use it to put a room behind
//!   every pane of a building that has one material for everything.
//! * `pack_interiors`: pack rendered (or five-face) rooms into one
//!   texture-array strip in the pre-projected format, alpha = depth, with a
//!   colour grade per room and a lit / off layer each. Needs no project.

use super::*;
use glam::Vec3;
use pigment_core::interior::{pack_atlas, pane_frames, part_map, write_part_map, Faces, Grade, RoomSpec};

fn vec3_arg(a: &Value, k: &str) -> Res<Option<Vec3>> {
    match a.get(k) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => {
            let n: Vec<f32> = v.as_array().ok_or_else(|| format!("`{k}` must be [x, y, z]"))?.iter().filter_map(|x| x.as_f64().map(|x| x as f32)).collect();
            match n[..] {
                [x, y, z] => Ok(Some(Vec3::new(x, y, z))),
                _ => Err(format!("`{k}` must be [x, y, z]")),
            }
        }
    }
}

fn grade_arg(v: Option<&Value>, what: &str) -> Res<Option<Grade>> {
    match v {
        None | Some(Value::Null) => Ok(None),
        Some(v) => serde_json::from_value(v.clone()).map(Some).map_err(|e| format!("`{what}`: {e} (keys: exposure, contrast, saturation, tint [r,g,b], lift [r,g,b], vignette)")),
    }
}

/// `pack_interiors` (no GPU, no project).
pub fn pack_interiors(a: &Value) -> Res<Value> {
    let dir = PathBuf::from(req(a, "dir")?);
    let name = s(a, "name").unwrap_or("interiors");
    let cell = a.get("cell").and_then(Value::as_u64).unwrap_or(512) as u32;
    let base = s(a, "base_dir").map(PathBuf::from);
    let path = |p: &str| -> PathBuf {
        let p = PathBuf::from(p);
        match &base {
            Some(b) if p.is_relative() => b.join(p),
            _ => p,
        }
    };
    let global = grade_arg(a.get("grade"), "grade")?;
    let rooms = a.get("rooms").and_then(Value::as_array).ok_or("missing `rooms`: [{name, lit | faces, off?, depth?, size?, eye?, grade?, off_grade?, tags?}]")?;
    let mut specs = Vec::with_capacity(rooms.len());
    for (i, r) in rooms.iter().enumerate() {
        let name = s(r, "name").ok_or_else(|| format!("`rooms[{i}].name` is required"))?.to_string();
        let size = match r.get("size") {
            None => [4.0, 3.0, 4.0],
            Some(v) => {
                let n: Vec<f32> = v.as_array().map(|a| a.iter().filter_map(Value::as_f64).map(|x| x as f32).collect()).unwrap_or_default();
                match n[..] {
                    [w, h, d] => [w, h, d],
                    _ => return Err(format!("`rooms[{i}].size` must be [width, height, depth] in metres")),
                }
            }
        };
        let faces = match r.get("faces") {
            None | Some(Value::Null) => None,
            Some(f) => {
                let get = |k: &str| s(f, k).map(path).ok_or_else(|| format!("`rooms[{i}].faces.{k}` is required (back, left, right, floor, ceiling)"));
                Some(Faces { back: get("back")?, left: get("left")?, right: get("right")?, floor: get("floor")?, ceiling: get("ceiling")? })
            }
        };
        // the pack-wide grade first, then the room's own
        let own = grade_arg(r.get("grade"), &format!("rooms[{i}].grade"))?;
        let grade = match (&global, own) {
            (Some(g), Some(o)) => Grade {
                exposure: g.exposure + o.exposure,
                contrast: g.contrast * o.contrast,
                saturation: g.saturation * o.saturation,
                tint: [0, 1, 2].map(|k| g.tint[k] * o.tint[k]),
                lift: [0, 1, 2].map(|k| g.lift[k] + o.lift[k]),
                vignette: g.vignette.max(o.vignette),
            },
            (Some(g), None) => g.clone(),
            (None, Some(o)) => o,
            (None, None) => Grade::default(),
        };
        specs.push(RoomSpec {
            name,
            size,
            eye: f(r, "eye"),
            lit: s(r, "lit").map(path),
            off: s(r, "off").map(path),
            depth: s(r, "depth").map(path),
            faces,
            grade,
            off_grade: grade_arg(r.get("off_grade"), &format!("rooms[{i}].off_grade"))?,
            tags: r.get("tags").and_then(Value::as_array).map(|t| t.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default(),
        });
    }
    let t0 = std::time::Instant::now();
    let atlas = pack_atlas(&dir, name, &specs, cell).map_err(|e| format!("{e:#}"))?;
    Ok(json!({
        "image": dir.join(&atlas.image),
        "json": dir.join(format!("{name}.json")),
        "cell": atlas.cell,
        "layers": atlas.layers,
        "rooms": atlas.rooms.iter().map(|r| json!({ "name": r.name, "lit_layer": r.lit_layer, "off_layer": r.off_layer, "mean_lit": r.mean_lit })).collect::<Vec<_>>(),
        "ms": t0.elapsed().as_millis() as u64,
    }))
}

impl Session {
    /// `export_window_map`.
    pub fn export_window_map(&mut self, a: &Value) -> Res<Value> {
        if self.app.mesh.vertices.is_empty() {
            return Err("no mesh loaded: new_project first".into());
        }
        let dir = PathBuf::from(req(a, "dir")?);
        let name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        let res = a.get("resolution").and_then(Value::as_u64).map(|r| r as u32).unwrap_or(self.app.doc.resolution);
        if !(16..=8192).contains(&res) {
            return Err(format!("`resolution` must be 16..8192, got {res}"));
        }
        let ids: Vec<u32> = match a.get("parts") {
            Some(Value::Array(v)) => v.iter().map(|p| p.as_u64().map(|x| x as u32).ok_or_else(|| format!("`parts` must be part ids, got {p}"))).collect::<Res<_>>()?,
            Some(q @ Value::Object(_)) => {
                // a shape query, as in list_parts / pick_parts
                let hits = self.query_parts(q, "parts.")?;
                hits["parts"].as_array().map(|v| v.iter().filter_map(|p| p.get("id").and_then(Value::as_u64).or_else(|| p.as_u64())).map(|x| x as u32).collect()).unwrap_or_default()
            }
            _ => return Err("missing `parts`: part ids, or a shape query like {max_thickness: 0.02, min_area: 0.3}".into()),
        };
        if ids.is_empty() {
            return Err("`parts` selects no parts".into());
        }
        if let Some(bad) = ids.iter().find(|&&p| p as usize >= self.app.parts.info.len()) {
            return Err(format!("part {bad} does not exist (the mesh has {} parts)", self.app.parts.info.len()));
        }
        let (lo, hi) = self.app.mesh.bounds();
        let outward = vec3_arg(a, "outward_from")?.unwrap_or((lo + hi) * 0.5);
        let up = vec3_arg(a, "up")?.unwrap_or(Vec3::Y);
        let pad = a.get("pad").and_then(Value::as_u64).unwrap_or(4) as u32;
        let frames = pane_frames(&self.app.mesh, &self.app.parts, &ids, outward, up).map_err(|e| format!("{e:#}"))?;
        let map = part_map(&self.app.mesh, &self.app.parts, &ids, res, pad);
        let png = dir.join(format!("{name}_WindowMap.png"));
        write_part_map(&png, &map, res).map_err(|e| format!("{e:#}"))?;
        let covered = map.iter().filter(|&&v| v != 0).count();
        let doc = json!({
            "format": "pigment-window-map-v1",
            "mesh": self.app.mesh.name,
            "resolution": res,
            "image": png.file_name().map(|f| f.to_string_lossy().to_string()),
            "uv": "glTF (origin top-left, v down); texel = pane index + 1, 0 = no pane",
            "panes": frames,
        });
        let jpath = dir.join(format!("{name}_panes.json"));
        std::fs::write(&jpath, serde_json::to_string_pretty(&doc).unwrap()).map_err(|e| e.to_string())?;
        Ok(json!({ "image": png, "json": jpath, "panes": frames.len(), "resolution": res, "coverage": covered as f64 / map.len() as f64 }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn window_map_of_the_town_building_finds_its_panes() {
        let _gpu = crate::app::automation::gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/town/building_a.glb"), "resolution": 512 })).unwrap();
        let dir = std::env::temp_dir().join(format!("pigment_window_map_{}", std::process::id()));
        // thin flat parts of window size, by shape query
        let r = s.export_window_map(&json!({ "dir": dir, "name": "a", "resolution": 512, "parts": { "max_thickness": 0.015, "min_area": 1.0, "max_area": 4.0 } })).unwrap();
        let n = r["panes"].as_u64().unwrap();
        assert!(n >= 30, "{r}");
        let doc: Value = serde_json::from_str(&std::fs::read_to_string(dir.join("a_panes.json")).unwrap()).unwrap();
        let map = image::open(dir.join("a_WindowMap.png")).unwrap().to_luma8();
        assert_eq!(map.dimensions(), (512, 512));
        for p in doc["panes"].as_array().unwrap() {
            // the centre UV of every pane reads back its own index
            let uv: Vec<f64> = p["uv_center"].as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect();
            let v = map.get_pixel((uv[0] * 512.0) as u32, (uv[1] * 512.0) as u32).0[0] as u64;
            assert_eq!(v, p["index"].as_u64().unwrap() + 1, "{p}");
            // walls: horizontal normals, outward from the building's middle
            let n: Vec<f64> = p["normal"].as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect();
            let c: Vec<f64> = p["center"].as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect();
            assert!(n[1].abs() < 0.01 && n[0] * c[0] + n[2] * c[2] > 0.0, "{p}");
        }
        assert!(s.export_window_map(&json!({ "dir": dir, "parts": [99999] })).unwrap_err().contains("does not exist"));
        // and the atlas packer runs without a project
        let lit = dir.join("room.png");
        image::RgbImage::from_pixel(16, 16, image::Rgb([200, 120, 60])).save(&lit).unwrap();
        let p = pack_interiors(&json!({ "dir": dir, "cell": 16, "base_dir": dir, "rooms": [{ "name": "r", "lit": "room.png", "tags": ["apartment"] }] })).unwrap();
        assert_eq!(p["layers"], 2);
        assert!(pack_interiors(&json!({ "dir": dir, "rooms": [{ "name": "r", "lit": "room.png", "grade": { "exposre": 1 } }] })).unwrap_err().contains("grade"));
        std::fs::remove_dir_all(&dir).ok();
    }
}
