//! Blender bridge commands for the headless session (MCP `send_to_blender`,
//! `export_mesh`, and `pigment-mcp --export-for-blender`).
//!
//! `send_to_blender` exports the texture set plus a `material.json` sidecar
//! (see `pigment_core::bridge`) and the exact painted mesh as glTF with
//! tangents, so the add-on in `tools/blender_addon/pigment_bridge` can build
//! the material and import the mesh without guessing.

use super::automation::Session;
use pigment_core::bridge;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

type Res<T> = Result<T, String>;

fn arg_str<'a>(a: &'a Value, k: &str) -> Option<&'a str> {
    a.get(k).and_then(Value::as_str)
}

impl Session {
    /// Write the loaded mesh (as painted: world transforms applied, Pigment's
    /// UVs, normals and tangents) to `.glb` or `.obj`: the whole mesh, one
    /// glTF material per source material, even with several texture sets.
    pub fn export_mesh(&mut self, a: &Value) -> Res<Value> {
        let mut path = PathBuf::from(arg_str(a, "path").ok_or("missing string argument `path`")?);
        if let Some(fmt) = arg_str(a, "format") {
            let fmt = fmt.to_ascii_lowercase();
            if path.extension().and_then(|e| e.to_str()).map(str::to_ascii_lowercase).as_deref() != Some(fmt.as_str()) {
                path.set_extension(&fmt);
            }
        } else if path.extension().is_none() {
            path.set_extension("glb");
        }
        let mesh = self.app.full_mesh();
        if mesh.indices.is_empty() {
            return Err("no mesh loaded: call new_project or open_project first".into());
        }
        bridge::export_mesh(mesh, &path).map_err(|e| format!("{e:#}"))?;
        let glb = path.extension().is_some_and(|e| e.eq_ignore_ascii_case("glb"));
        Ok(json!({
            "path": path,
            "vertices": mesh.vertices.len(),
            "triangles": mesh.triangle_count(),
            "tangents": glb,
            "up_axis": "+Y (glTF); Blender's glTF importer converts to +Z",
        }))
    }

    /// Export textures + `material.json` + the mesh into `dir`, ready for the
    /// Blender add-on (or `tools/blender_pigment.py`).
    pub fn send_to_blender(&mut self, a: &Value) -> Res<Value> {
        let dir = PathBuf::from(arg_str(a, "dir").ok_or("missing string argument `dir`")?);
        if let Some(p) = arg_str(a, "project") {
            self.save_project(&json!({ "path": p }))?;
        }
        let name = arg_str(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        let preset = arg_str(a, "preset").unwrap_or("separate");
        let tex = self.export_textures(&json!({ "dir": dir, "preset": preset, "name": name }))?;
        let mut mesh_info = Value::Null;
        if a.get("mesh").and_then(Value::as_bool).unwrap_or(true) {
            let fmt = arg_str(a, "mesh_format").unwrap_or("glb");
            let info = self.export_mesh(&json!({ "path": dir.join(format!("{name}.{fmt}")), "format": fmt }))?;
            let file = Path::new(info["path"].as_str().unwrap_or_default()).file_name().map(|f| f.to_string_lossy().to_string());
            bridge::update_sidecar(&dir, &name, &json!({ "mesh": file })).map_err(|e| format!("{e:#}"))?;
            mesh_info = info;
        }
        // foliage layers ride along: card glb, instance list, atlas maps, a foliage sidecar entry
        let mut foliage = Value::Null;
        if a.get("foliage").and_then(Value::as_bool).unwrap_or(true) && self.app.doc.layers.iter().any(|l| l.foliage().is_some_and(|f| !f.instances.is_empty())) {
            foliage = self.export_foliage(&json!({ "dir": dir, "name": name }))?;
        }
        let sidecar = bridge::read_sidecar(&dir);
        Ok(json!({
            "dir": dir,
            "name": name,
            "sidecar": dir.join(bridge::SIDECAR),
            "material": sidecar["materials"][&name],
            "files": tex["files"],
            "mesh": mesh_info,
            "status": tex["status"],
            "foliage": foliage,
            "blender": "Pigment Bridge add-on: N-panel > Pigment > Link, or apply_pigment_material(obj, dir, name) from tools/blender_pigment.py",
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn send_to_blender_writes_maps_sidecar_and_mesh() {
        let _gpu = crate::app::automation::gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/neon_tubes.glb"), "resolution": 512, "material": "Neon pink" })).unwrap();
        let out = std::env::temp_dir().join(format!("pigment-s2b-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&out);
        let proj = out.join("tubes.pigment");
        let r = s.send_to_blender(&json!({ "dir": out.join("tex"), "name": "tubes", "project": proj })).unwrap();
        let m = &r["material"];
        assert_eq!(m["name"], "tubes", "{r}");
        assert_eq!(m["resolution"], 512);
        assert_eq!(m["has_emission"], true);
        assert!(m["emissive_scale"].as_f64().unwrap() > 1.0, "{m}");
        assert_eq!(m["mesh"], "tubes.glb");
        assert!(m["project"].as_str().unwrap().ends_with("tubes.pigment"), "{m}");
        for f in r["files"].as_array().unwrap() {
            assert!(Path::new(f.as_str().unwrap()).exists(), "{f}");
        }
        // the exported mesh is the painted one
        let back = pigment_core::Mesh::load(&out.join("tex/tubes.glb")).unwrap();
        assert_eq!(back.triangle_count(), s.app.mesh.triangle_count());
        assert_eq!(back.vertices.len(), s.app.mesh.vertices.len());
        // OBJ, and an extension-less path defaults to glb
        let o = s.export_mesh(&json!({ "path": out.join("m"), "format": "obj" })).unwrap();
        assert!(out.join("m.obj").exists() && o["tangents"] == false);
        s.export_mesh(&json!({ "path": out.join("n") })).unwrap();
        assert!(out.join("n.glb").exists());
        std::fs::remove_dir_all(out).ok();
    }

    /// With texture sets: every set in the requested preset, sidecar entries
    /// that point at the files on disk and say which materials / tile they
    /// paint, the whole mesh with its materials, and render framing on the
    /// whole mesh whichever set is active.
    #[test]
    fn send_to_blender_with_texture_sets() {
        let _gpu = crate::app::automation::gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let out = std::env::temp_dir().join(format!("pigment-s2b-sets-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&out);
        std::fs::create_dir_all(&out).unwrap();
        let mut mesh = pigment_core::hibake::rounded_box(glam::Vec3::new(0.5, 0.35, 0.4), 0.06, 16, None, Some(&|p: glam::Vec3| if p.y > 0.33 { 1 } else { 0 }));
        mesh.material_names = vec!["body".into(), "lid".into()];
        let src = out.join("box.obj");
        mesh.write_obj(&src).unwrap();
        s.new_project(&json!({ "mesh": src, "resolution": 512, "material": "Teal paint", "texture_sets": [{ "name": "body", "materials": ["body"] }, { "name": "lid", "materials": ["lid"] }] })).unwrap();
        let whole = s.app.full_mesh().triangle_count();
        assert!(s.app.mesh.triangle_count() < whole, "the active set is part of the mesh");
        let r = s.send_to_blender(&json!({ "dir": out.join("tex"), "name": "box" })).unwrap();
        let doc = pigment_core::bridge::read_sidecar(&out.join("tex"));
        let mats = &doc["materials"];
        assert_eq!(mats["box"]["texture_sets"], json!(["box_body", "box_lid"]), "{doc}");
        assert_eq!(mats["box"]["mesh"], "box.glb");
        for (entry, material) in [("box_body", "body"), ("box_lid", "lid")] {
            let e = &mats[entry];
            assert_eq!(e["preset"], "separate", "{entry} uses the requested preset");
            assert_eq!(e["materials"], json!([material]));
            for m in e["maps"].as_array().unwrap() {
                let f = m["file"].as_str().unwrap();
                assert!(f.ends_with(".1001.png") && out.join("tex").join(f).exists(), "{entry}: {f}");
            }
        }
        assert!(r["files"].as_array().unwrap().len() >= 2 * 7, "{r}");
        // the whole mesh, one glTF material per source material
        let back = pigment_core::Mesh::load(&out.join("tex/box.glb")).unwrap();
        assert_eq!(back.triangle_count(), whole);
        assert_eq!(back.material_names, vec!["body".to_string(), "lid".to_string()]);
        // framing: the same camera whichever set is active
        s.set_camera(&json!({}));
        let a = (s.app.camera.target, s.app.camera.distance);
        s.activate_texture_set("lid").unwrap();
        s.set_camera(&json!({}));
        assert!((s.app.camera.target - a.0).length() < 1e-5 && (s.app.camera.distance - a.1).abs() < 1e-5);
        std::fs::remove_dir_all(out).ok();
    }
}
