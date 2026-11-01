//! Image fills end to end: MCP-style args -> compositor -> exported maps,
//! project round trip, and the normal-map frame convention.

use super::automation::Session;
use super::*;
use serde_json::json;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn material(s: &mut Session) -> export::MaterialImages {
    s.app.commit_doc_changes();
    s.app.ensure_composited(&s.rs);
    io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts)
}

/// Fraction of texels whose colour is brick-red (r clearly above g and b).
fn reddish(m: &export::MaterialImages) -> f32 {
    let n = m.color.chunks_exact(4).filter(|p| p[0] as i32 > p[1] as i32 + 25 && p[0] as i32 > p[2] as i32 + 25).count();
    n as f32 / (m.size * m.size) as f32
}

#[test]
fn image_fill_args_composite_and_persist() {
    let Ok(mut s) = Session::new() else { return };
    let r = root();
    s.new_project(&json!({ "mesh": r.join("assets/ammo_box.glb"), "resolution": 512, "material": "White plastic" })).unwrap();
    let before = material(&mut s);
    assert!(reddish(&before) < 0.01);

    // relative tile set: found through the mesh folder's parents (the repo root)
    let out = s.add_layer(&json!({ "name": "Bricks", "image": { "tile_set": "assets/tiles/brick", "projection": "triplanar", "tile_size": 0.5, "rotation": 10 } })).unwrap();
    let layer = out["layers"].as_array().unwrap().iter().find(|l| l["name"] == "Bricks").unwrap().clone();
    assert_eq!(layer["image"]["projection"], "triplanar", "{layer}");
    assert_eq!(layer["image"]["images"]["normal"], "assets/tiles/brick/normal.png");
    assert!(layer["channels"].as_array().unwrap().iter().any(|c| c == "normal"), "normal channel enabled by the image");
    let m = material(&mut s);
    assert!(reddish(&m) > 0.3, "bricks cover the box ({})", reddish(&m));
    let bent = m.normal.chunks_exact(4).filter(|p| (p[0] as i32 - 128).abs() > 12 || (p[1] as i32 - 128).abs() > 12).count();
    assert!(bent > 2000, "brick relief shows in the normal map ({bent})");

    // UV projection with tiling, then the tint darkens it
    s.update_layer(&json!({ "layer": "Bricks", "image": { "projection": "uv", "tiling": [4, 4] } })).unwrap();
    assert!(reddish(&material(&mut s)) > 0.3);
    s.update_layer(&json!({ "layer": "Bricks", "image": { "tint": [0.0, 0.0, 0.0] } })).unwrap();
    let dark = material(&mut s);
    assert!(dark.color.chunks_exact(4).filter(|p| p[0] < 10).count() as u32 > dark.size * dark.size / 2);

    // errors: missing image, paint layer, unknown projection
    assert!(s.update_layer(&json!({ "layer": "Bricks", "image": { "base_color": "assets/tiles/nope.png" } })).is_err());
    assert!(s.update_layer(&json!({ "layer": "Paint", "image": "assets/tiles/brick" })).is_err());
    assert!(s.update_layer(&json!({ "layer": "Bricks", "image": { "projection": "cube" } })).is_err());
    assert!(s.library()["tile_sets"].to_string().contains("brick") || !Path::new("assets/tiles").exists());

    // save + reopen keeps the image fill; null removes it
    s.update_layer(&json!({ "layer": "Bricks", "image": { "tint": [1.0, 1.0, 1.0] } })).unwrap();
    let dir = std::env::temp_dir().join(format!("pigment-imgfill-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    // a saved project lives elsewhere: give it an absolute path so it reloads
    let abs = r.join("assets/tiles/brick");
    s.update_layer(&json!({ "layer": "Bricks", "image": abs.to_string_lossy() })).unwrap();
    s.save_project(&json!({ "path": dir.join("b.pigment") })).unwrap();
    s.open_project(&json!({ "path": dir.join("b.pigment") })).unwrap();
    let l = s.app.doc.layers.iter().find(|l| l.name == "Bricks").unwrap();
    assert_eq!(l.image.as_ref().unwrap().projection, Projection::Uv);
    assert!(reddish(&material(&mut s)) > 0.3, "image fill survives save/open");
    s.update_layer(&json!({ "layer": "Bricks", "image": null })).unwrap();
    assert!(reddish(&material(&mut s)) < 0.01);
    std::fs::remove_dir_all(dir).ok();
}

/// A normal map and the height map it was made from must bend the final
/// normals the same way, in both projections: checks the image frame ->
/// texel tangent frame conversion (UV rotation, triplanar planes).
#[test]
fn image_normals_agree_with_image_height() {
    let Ok(mut s) = Session::new() else { return };
    let r = root();
    s.new_project(&json!({ "mesh": r.join("assets/ammo_box.glb"), "resolution": 512, "material": "White plastic" })).unwrap();
    let set = r.join("assets/tiles/corrugated_metal");
    let h = set.join("height.png").to_string_lossy().to_string();
    let n = set.join("normal.png").to_string_lossy().to_string();
    for proj in [json!({ "projection": "uv", "tiling": 3, "rotation": 30 }), json!({ "projection": "triplanar", "tile_size": 0.4, "rotation": 30 })] {
        let mut a = proj.clone();
        a["height"] = json!(h);
        a["height_scale"] = json!(0.3);
        s.add_layer(&json!({ "name": "H", "image": a })).unwrap();
        let from_height = material(&mut s);
        s.delete_layer(&json!({ "layer": "H" })).unwrap();
        let mut b = proj.clone();
        b["normal"] = json!(n);
        s.add_layer(&json!({ "name": "N", "image": b })).unwrap();
        let from_normal = material(&mut s);
        s.delete_layer(&json!({ "layer": "N" })).unwrap();
        for k in 0..2 {
            let (mut dot, mut na, mut nb) = (0.0f64, 0.0f64, 0.0f64);
            for (p, q) in from_height.normal.chunks_exact(4).zip(from_normal.normal.chunks_exact(4)) {
                let (x, y) = (p[k] as f64 - 128.0, q[k] as f64 - 128.0);
                dot += x * y;
                na += x * x;
                nb += y * y;
            }
            let corr = dot / (na.sqrt() * nb.sqrt() + 1e-9);
            assert!(corr > 0.5, "{proj}: normal {} from the normal map vs from height correlate {corr:.2}", ["x", "y"][k]);
        }
    }
}
