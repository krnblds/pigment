//! Pigment -> DCC bridge: the `material.json` sidecar written next to exported
//! textures, and mesh export (glTF binary with tangents, or OBJ).
//!
//! The sidecar tells a consumer (the Blender add-on in
//! `tools/blender_addon/pigment_bridge`) exactly what is in the folder: which
//! file carries which material channel in which colour channel, the colour
//! space of each file, the normal-map convention, the emissive scale, the
//! texture resolution, and where the Pigment project and mesh live.
//!
//! ```json
//! { "format": "pigment-material", "version": 1,
//!   "materials": { "<name>": { "maps": [{ "file": "<name>_BaseColor.png", "sources": ["red","green","blue"], ... }], ... } } }
//! ```
//!
//! One folder can hold several exports (different base names); each export
//! updates only its own entry.

use crate::export::{MaterialImages, PixelFormat, Preset, Source};
use crate::mesh::Mesh;
use anyhow::{bail, Context, Result};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};

pub const SIDECAR: &str = "material.json";
pub const SIDECAR_FORMAT: &str = "pigment-material";
pub const SIDECAR_VERSION: u32 = 1;

/// Stable lowercase name of a channel source, as used in the sidecar.
pub fn source_name(s: Source) -> &'static str {
    match s {
        Source::Red => "red",
        Source::Green => "green",
        Source::Blue => "blue",
        Source::Roughness => "roughness",
        Source::Smoothness => "smoothness",
        Source::Metallic => "metallic",
        Source::Ao => "ao",
        Source::Height => "height",
        Source::NormalX => "normal_x",
        Source::NormalY => "normal_y",
        Source::NormalYFlipped => "normal_y_flipped",
        Source::NormalZ => "normal_z",
        Source::EmissiveR => "emissive_r",
        Source::EmissiveG => "emissive_g",
        Source::EmissiveB => "emissive_b",
        Source::Opacity => "opacity",
        Source::Transmission => "transmission",
        Source::Coat => "coat",
        Source::CoatRoughness => "coat_roughness",
        Source::Flake => "flake",
        Source::One => "one",
    }
}

fn format_name(f: PixelFormat) -> &'static str {
    match f {
        PixelFormat::L8 => "l8",
        PixelFormat::L16 => "l16",
        PixelFormat::Rgb8 => "rgb8",
        PixelFormat::Rgba8 => "rgba8",
    }
}

/// Material channel a source belongs to (`base_color`, `normal`, ...).
fn channel_of(s: Source) -> Option<&'static str> {
    Some(match s {
        Source::Red | Source::Green | Source::Blue => "base_color",
        Source::Roughness | Source::Smoothness => "roughness",
        Source::Metallic => "metallic",
        Source::Ao => "ao",
        Source::Height => "height",
        Source::NormalX | Source::NormalY | Source::NormalYFlipped | Source::NormalZ => "normal",
        Source::EmissiveR | Source::EmissiveG | Source::EmissiveB => "emissive",
        Source::Opacity => "opacity",
        Source::Transmission => "transmission",
        Source::Coat => "coat",
        Source::CoatRoughness => "coat_roughness",
        Source::Flake => "flake",
        Source::One => return None,
    })
}

/// True if any texel of the exported emissive map is lit.
pub fn has_emission(m: &MaterialImages) -> bool {
    m.emissive.chunks_exact(4).any(|p| p[0] > 0 || p[1] > 0 || p[2] > 0)
}

/// Where the export came from, for the sidecar.
#[derive(Clone, Debug, Default)]
pub struct SidecarExtra {
    /// The `.pigment` project folder, if the document has been saved.
    pub project: Option<PathBuf>,
    /// The mesh the project was made from.
    pub source_mesh: Option<PathBuf>,
    /// An exported copy of the painted mesh (see [`export_mesh`]).
    pub mesh: Option<PathBuf>,
}

fn path_str(dir: &Path, p: &Path) -> String {
    // inside the export folder: store relative so the folder can move
    match p.strip_prefix(dir) {
        Ok(rel) => rel.to_string_lossy().replace('\\', "/"),
        Err(_) => std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf()).to_string_lossy().replace('\\', "/"),
    }
}

/// The sidecar entry describing one export of `preset` named `base`.
pub fn sidecar_entry(dir: &Path, base: &str, preset: &Preset, m: &MaterialImages, extra: &SidecarExtra) -> Value {
    let mut channels: Vec<&str> = Vec::new();
    let emits = has_emission(m);
    // only the maps `export::export` actually writes: a solid material has no
    // Opacity / Transmission files and an RGB (not RGBA) base colour
    let maps: Vec<Value> = preset
        .outputs
        .iter()
        .filter_map(|o| crate::export::effective_output(o, m))
        .map(|o| {
            let srgb = o.sources.iter().any(|s| matches!(s, Source::Red | Source::Green | Source::Blue | Source::EmissiveR | Source::EmissiveG | Source::EmissiveB));
            for c in o.sources.iter().filter_map(|s| channel_of(*s)) {
                if !channels.contains(&c) && (c != "emissive" || emits) {
                    channels.push(c);
                }
            }
            json!({
                "file": format!("{base}_{}.png", o.suffix),
                "suffix": o.suffix,
                "format": format_name(o.format),
                "colorspace": if srgb { "srgb" } else { "non-color" },
                "sources": o.sources.iter().map(|s| source_name(*s)).collect::<Vec<_>>(),
            })
        })
        .collect();
    let directx = preset.outputs.iter().any(|o| o.sources.contains(&Source::NormalYFlipped));
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    json!({
        "name": base,
        "preset": preset.id,
        "resolution": m.size,
        "channels": channels,
        "normal_convention": if directx { "directx" } else { "opengl" },
        "normal_space": "tangent",
        "emissive_scale": m.emissive_scale,
        "has_emission": emits,
        "height": { "neutral": 0.5, "min": -1.0, "max": 1.0 },
        "uv": "glTF (origin top-left); first UV set",
        "maps": maps,
        "project": extra.project.as_deref().map(|p| path_str(dir, p)),
        "source_mesh": extra.source_mesh.as_deref().map(|p| path_str(dir, p)),
        "mesh": extra.mesh.as_deref().map(|p| path_str(dir, p)),
        "exported_at": now,
        "pigment_version": env!("CARGO_PKG_VERSION"),
    })
}

/// Read `dir/material.json` (empty document if missing or unreadable).
pub fn read_sidecar(dir: &Path) -> Value {
    std::fs::read_to_string(dir.join(SIDECAR))
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .filter(|v| v.get("materials").is_some_and(Value::is_object))
        .unwrap_or_else(|| json!({ "format": SIDECAR_FORMAT, "version": SIDECAR_VERSION, "materials": {} }))
}

/// Merge `patch` into the entry for `base` and write the sidecar atomically.
/// `null` values in `patch` keep what was already there (so a texture export
/// does not forget a previously exported mesh).
pub fn update_sidecar(dir: &Path, base: &str, patch: &Value) -> Result<PathBuf> {
    std::fs::create_dir_all(dir)?;
    let mut doc = read_sidecar(dir);
    doc["format"] = json!(SIDECAR_FORMAT);
    doc["version"] = json!(SIDECAR_VERSION);
    let mats = doc["materials"].as_object_mut().expect("materials is an object");
    let entry = mats.entry(base.to_string()).or_insert_with(|| Value::Object(Map::new()));
    if !entry.is_object() {
        *entry = Value::Object(Map::new());
    }
    if let (Some(e), Some(p)) = (entry.as_object_mut(), patch.as_object()) {
        for (k, v) in p {
            if !v.is_null() || !e.contains_key(k) {
                e.insert(k.clone(), v.clone());
            }
        }
    }
    let path = dir.join(SIDECAR);
    let tmp = dir.join(format!("{SIDECAR}.tmp"));
    let mut text = serde_json::to_string_pretty(&doc)?;
    text.push('\n');
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, &path).with_context(|| format!("writing {}", path.display()))?;
    Ok(path)
}

/// Write (or update) the sidecar for a texture export.
pub fn write_sidecar(dir: &Path, base: &str, preset: &Preset, m: &MaterialImages, extra: &SidecarExtra) -> Result<PathBuf> {
    update_sidecar(dir, base, &sidecar_entry(dir, base, preset, m, extra))
}

// ------------------------------------------------------------------ mesh export

/// Write the mesh by extension: `.glb` (positions, normals, UVs, tangents,
/// indices) or `.obj` (no tangents: OBJ has no slot for them).
pub fn export_mesh(mesh: &Mesh, path: &Path) -> Result<()> {
    if let Some(d) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        std::fs::create_dir_all(d)?;
    }
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "glb" => write_glb(mesh, path),
        "obj" => mesh.write_obj(path),
        other => bail!("unsupported mesh export format '.{other}' (use .glb or .obj)"),
    }
}

/// glTF 2.0 binary, Y-up, metres: one mesh; one primitive per material (named
/// as in the source, so a consumer can match texture sets to its material
/// slots), or a single primitive without a material when the mesh has none.
/// UVs are written as-is (Pigment already uses glTF's top-left origin) and the
/// tangents are Pigment's own (w = bitangent sign, glTF convention), so a
/// consumer that reads TANGENT gets the exact frame the normal map was baked in.
pub fn write_glb(mesh: &Mesh, path: &Path) -> Result<()> {
    if mesh.vertices.is_empty() || mesh.indices.is_empty() {
        bail!("mesh is empty");
    }
    let n = mesh.vertices.len();
    let (mut lo, mut hi) = ([f32::MAX; 3], [f32::MIN; 3]);
    for v in &mesh.vertices {
        for k in 0..3 {
            lo[k] = lo[k].min(v.position[k]);
            hi[k] = hi[k].max(v.position[k]);
        }
    }
    // binary chunk: positions | normals | uvs | tangents | indices
    let mut bin: Vec<u8> = Vec::with_capacity(n * 48 + mesh.indices.len() * 4);
    let mut views = Vec::new();
    let mut push = |bin: &mut Vec<u8>, bytes: &[u8], target: u32| {
        let off = bin.len();
        bin.extend_from_slice(bytes);
        while bin.len() % 4 != 0 {
            bin.push(0);
        }
        views.push(json!({ "buffer": 0, "byteOffset": off, "byteLength": bytes.len(), "target": target }));
    };
    const ARRAY: u32 = 34962;
    const ELEMENT: u32 = 34963;
    let pos: Vec<[f32; 3]> = mesh.vertices.iter().map(|v| v.position).collect();
    let nrm: Vec<[f32; 3]> = mesh.vertices.iter().map(|v| v.normal).collect();
    let uv: Vec<[f32; 2]> = mesh.vertices.iter().map(|v| v.uv).collect();
    let tan: Vec<[f32; 4]> = mesh.vertices.iter().map(|v| v.tangent).collect();
    push(&mut bin, bytemuck::cast_slice(&pos), ARRAY);
    push(&mut bin, bytemuck::cast_slice(&nrm), ARRAY);
    push(&mut bin, bytemuck::cast_slice(&uv), ARRAY);
    push(&mut bin, bytemuck::cast_slice(&tan), ARRAY);
    const F32: u32 = 5126;
    const U32: u32 = 5125;
    let mut accessors = vec![
        json!({ "bufferView": 0, "componentType": F32, "count": n, "type": "VEC3", "min": lo, "max": hi }),
        json!({ "bufferView": 1, "componentType": F32, "count": n, "type": "VEC3" }),
        json!({ "bufferView": 2, "componentType": F32, "count": n, "type": "VEC2" }),
        json!({ "bufferView": 3, "componentType": F32, "count": n, "type": "VEC4" }),
    ];
    // one index buffer per material, all sharing the vertex attributes
    let with_materials = !mesh.tri_material.is_empty() || mesh.material_names.len() > 1;
    let groups: Vec<(Option<usize>, Vec<u32>)> = if with_materials {
        (0..mesh.material_count())
            .map(|k| {
                let idx = mesh.indices.chunks_exact(3).enumerate().filter(|(t, _)| mesh.material_of(*t) as usize == k).flat_map(|(_, tri)| tri.iter().copied()).collect();
                (Some(k), idx)
            })
            .filter(|(_, idx): &(Option<usize>, Vec<u32>)| !idx.is_empty())
            .collect()
    } else {
        vec![(None, mesh.indices.clone())]
    };
    let mut primitives = Vec::new();
    for (i, (mat, idx)) in groups.iter().enumerate() {
        push(&mut bin, bytemuck::cast_slice(idx), ELEMENT);
        // views 0..4 are the vertex attributes, then one per index buffer
        accessors.push(json!({ "bufferView": 4 + i, "componentType": U32, "count": idx.len(), "type": "SCALAR" }));
        let mut p = json!({ "attributes": { "POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2, "TANGENT": 3 }, "indices": accessors.len() - 1, "mode": 4 });
        if let Some(k) = mat {
            p["material"] = json!(k);
        }
        primitives.push(p);
    }
    let name = if mesh.name.is_empty() { "mesh" } else { mesh.name.as_str() };
    let mut gltf = json!({
        "asset": { "version": "2.0", "generator": format!("Pigment {}", env!("CARGO_PKG_VERSION")) },
        "scene": 0,
        "scenes": [{ "nodes": [0] }],
        "nodes": [{ "name": name, "mesh": 0 }],
        "meshes": [{ "name": name, "primitives": primitives }],
        "buffers": [{ "byteLength": bin.len() }],
        "bufferViews": views,
        "accessors": accessors,
    });
    if with_materials {
        gltf["materials"] = json!((0..mesh.material_count() as u32).map(|k| json!({ "name": mesh.material_name(k) })).collect::<Vec<_>>());
    }
    let mut js = serde_json::to_vec(&gltf)?;
    while js.len() % 4 != 0 {
        js.push(b' ');
    }
    let total = 12 + 8 + js.len() + 8 + bin.len();
    let mut out = Vec::with_capacity(total);
    out.extend_from_slice(b"glTF");
    out.extend_from_slice(&2u32.to_le_bytes());
    out.extend_from_slice(&(total as u32).to_le_bytes());
    out.extend_from_slice(&(js.len() as u32).to_le_bytes());
    out.extend_from_slice(b"JSON");
    out.extend_from_slice(&js);
    out.extend_from_slice(&(bin.len() as u32).to_le_bytes());
    out.extend_from_slice(b"BIN\0");
    out.extend_from_slice(&bin);
    std::fs::write(path, out).with_context(|| format!("writing {}", path.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::export::preset;

    fn tiny(emit: bool) -> MaterialImages {
        let e = if emit { 200 } else { 0 };
        MaterialImages {
            size: 2,
            color: vec![255; 16],
            orm: vec![255; 16],
            normal: vec![128; 16],
            height: vec![32768; 4],
            emissive: vec![e, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255],
            emissive_scale: 3.5,
            coat: vec![],
        }
    }

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pigment-bridge-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        d
    }

    /// Opacity / Transmission maps are listed exactly when the export writes
    /// them, and the base colour's alpha is opacity only when it isn't solid.
    #[test]
    fn sidecar_lists_opacity_and_transmission_only_when_written() {
        let dir = tmp("glass");
        let mut solid = tiny(false);
        solid.orm.chunks_exact_mut(4).for_each(|p| p[3] = 0); // no transmission
        let mut glass = tiny(false);
        glass.color.chunks_exact_mut(4).for_each(|p| p[3] = 77);
        glass.orm.chunks_exact_mut(4).for_each(|p| p[3] = 255);
        let suffixes = |e: &Value| e["maps"].as_array().unwrap().iter().map(|m| m["suffix"].as_str().unwrap().to_string()).collect::<Vec<_>>();
        let sep = preset("separate").unwrap();
        let e = sidecar_entry(&dir, "Solid", &sep, &solid, &SidecarExtra::default());
        assert!(!suffixes(&e).iter().any(|s| s == "Opacity" || s == "Transmission"), "{e}");
        assert!(!e["channels"].as_array().unwrap().contains(&json!("opacity")));
        let e = sidecar_entry(&dir, "Glass", &sep, &glass, &SidecarExtra::default());
        let op = e["maps"].as_array().unwrap().iter().find(|m| m["suffix"] == "Opacity").expect("opacity map");
        assert_eq!(op["sources"], json!(["opacity"]));
        assert_eq!(op["colorspace"], "non-color");
        let tr = e["maps"].as_array().unwrap().iter().find(|m| m["suffix"] == "Transmission").expect("transmission map");
        assert_eq!(tr["sources"], json!(["transmission"]));
        let ch = e["channels"].as_array().unwrap();
        assert!(ch.contains(&json!("opacity")) && ch.contains(&json!("transmission")));
        // unreal: RGBA base colour with opacity in alpha, RGB when solid
        let ue = preset("unreal").unwrap();
        let bc = |e: &Value| e["maps"].as_array().unwrap().iter().find(|m| m["suffix"] == "BaseColor").unwrap().clone();
        assert_eq!(bc(&sidecar_entry(&dir, "G", &ue, &glass, &SidecarExtra::default()))["sources"], json!(["red", "green", "blue", "opacity"]));
        assert_eq!(bc(&sidecar_entry(&dir, "S", &ue, &solid, &SidecarExtra::default()))["sources"], json!(["red", "green", "blue"]));
    }

    /// Coat / CoatRoughness / Flake maps are listed only when written.
    #[test]
    fn sidecar_lists_coat_maps_only_when_coated() {
        let dir = tmp("coat");
        let sep = preset("separate").unwrap();
        let suffixes = |e: &Value| e["maps"].as_array().unwrap().iter().map(|m| m["suffix"].as_str().unwrap().to_string()).collect::<Vec<_>>();
        let e = sidecar_entry(&dir, "Plain", &sep, &tiny(false), &SidecarExtra::default());
        assert!(!suffixes(&e).iter().any(|s| s.starts_with("Coat") || s == "Flake"), "{e}");
        let mut car = tiny(false);
        car.coat = [255u8, 10, 128, 255].repeat(4);
        let e = sidecar_entry(&dir, "Car", &sep, &car, &SidecarExtra::default());
        let sx = suffixes(&e);
        assert!(sx.contains(&"Coat".into()) && sx.contains(&"CoatRoughness".into()) && sx.contains(&"Flake".into()), "{e}");
        let cr = e["maps"].as_array().unwrap().iter().find(|m| m["suffix"] == "CoatRoughness").unwrap();
        assert_eq!(cr["sources"], json!(["coat_roughness"]));
        assert_eq!(cr["colorspace"], "non-color");
        let ch = e["channels"].as_array().unwrap();
        assert!(ch.contains(&json!("coat")) && ch.contains(&json!("coat_roughness")) && ch.contains(&json!("flake")));
    }

    #[test]
    fn sidecar_describes_maps_and_merges_entries() {
        let dir = tmp("sidecar");
        // an absolute path on any platform, outside the export folder
        let project = std::env::temp_dir().join("work").join("crate.pigment");
        let extra = SidecarExtra { project: Some(project.clone()), ..Default::default() };
        write_sidecar(&dir, "Crate", &preset("separate").unwrap(), &tiny(true), &extra).unwrap();
        write_sidecar(&dir, "Lid", &preset("unreal").unwrap(), &tiny(false), &SidecarExtra::default()).unwrap();
        let doc = read_sidecar(&dir);
        assert_eq!(doc["format"], SIDECAR_FORMAT);
        let c = &doc["materials"]["Crate"];
        assert_eq!(c["resolution"], 2);
        assert_eq!(c["normal_convention"], "opengl");
        assert!((c["emissive_scale"].as_f64().unwrap() - 3.5).abs() < 1e-6);
        assert_eq!(c["has_emission"], true);
        assert!(c["channels"].as_array().unwrap().contains(&json!("emissive")));
        assert_eq!(c["project"], project.to_string_lossy().replace(std::path::MAIN_SEPARATOR, "/"));
        let bc = c["maps"].as_array().unwrap().iter().find(|m| m["suffix"] == "BaseColor").unwrap();
        assert_eq!(bc["file"], "Crate_BaseColor.png");
        assert_eq!(bc["colorspace"], "srgb");
        let l = &doc["materials"]["Lid"];
        assert_eq!(l["normal_convention"], "directx");
        assert_eq!(l["has_emission"], false);
        assert!(!l["channels"].as_array().unwrap().contains(&json!("emissive")));
        let orm = l["maps"].as_array().unwrap().iter().find(|m| m["suffix"] == "OcclusionRoughnessMetallic").unwrap();
        assert_eq!(orm["sources"], json!(["ao", "roughness", "metallic"]));
        assert_eq!(orm["colorspace"], "non-color");
        // a later update without a mesh keeps the mesh recorded earlier
        update_sidecar(&dir, "Crate", &json!({ "mesh": "Crate.glb" })).unwrap();
        write_sidecar(&dir, "Crate", &preset("separate").unwrap(), &tiny(true), &extra).unwrap();
        assert_eq!(read_sidecar(&dir)["materials"]["Crate"]["mesh"], "Crate.glb");
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn glb_round_trips_through_the_loader_with_tangents() {
        let dir = tmp("glb");
        let mut m = Mesh::demo_crate(2);
        m.name = "crate".into();
        let p = dir.join("crate.glb");
        export_mesh(&m, &p).unwrap();
        let back = Mesh::load(&p).unwrap();
        assert_eq!(back.indices, m.indices);
        assert_eq!(back.vertices.len(), m.vertices.len());
        for (a, b) in m.vertices.iter().zip(&back.vertices) {
            assert_eq!(a.position, b.position);
            assert_eq!(a.uv, b.uv);
            for k in 0..3 {
                assert!((a.normal[k] - b.normal[k]).abs() < 1e-5);
            }
        }
        // the TANGENT accessor holds exactly Pigment's tangents
        let (doc, buffers, _) = gltf::import(&p).unwrap();
        let prim = doc.meshes().next().unwrap().primitives().next().unwrap();
        let tans: Vec<[f32; 4]> = prim.reader(|b| Some(&buffers[b.index()])).read_tangents().unwrap().collect();
        assert_eq!(tans, m.vertices.iter().map(|v| v.tangent).collect::<Vec<_>>());
        export_mesh(&m, &dir.join("crate.obj")).unwrap();
        assert_eq!(Mesh::load(&dir.join("crate.obj")).unwrap().triangle_count(), m.triangle_count());
        assert!(export_mesh(&m, &dir.join("crate.fbx")).is_err());
        std::fs::remove_dir_all(dir).ok();
    }

    /// A mesh with materials comes back with the same material per triangle
    /// and the same names (one primitive each).
    #[test]
    fn glb_keeps_materials() {
        let dir = tmp("glb-mats");
        let mut m = Mesh::demo_crate(2);
        let n = m.triangle_count();
        m.tri_material = (0..n as u32).map(|t| u32::from(t % 3 == 0) + u32::from(t % 5 == 0)).collect();
        m.material_names = vec!["wood".into(), "iron".into(), "brass".into()];
        let p = dir.join("crate.glb");
        export_mesh(&m, &p).unwrap();
        let back = Mesh::load(&p).unwrap();
        assert_eq!(back.material_names, m.material_names);
        assert_eq!(back.triangle_count(), n);
        // triangles are grouped by material: compare the multiset of (material, corners)
        let key = |mesh: &Mesh| {
            let mut v: Vec<(u32, [[i64; 3]; 3])> = (0..mesh.triangle_count())
                .map(|t| (mesh.material_of(t), [0, 1, 2].map(|k| mesh.vertices[mesh.indices[t * 3 + k] as usize].position.map(|x| (x * 1e5).round() as i64))))
                .collect();
            v.sort();
            v
        };
        assert_eq!(key(&back), key(&m));
        std::fs::remove_dir_all(dir).ok();
    }
}
