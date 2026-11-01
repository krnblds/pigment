//! Flat sheet projects end to end: the exported maps of a seamless tile
//! really wrap (edges, gradients, a scrolled copy of the tile), strokes and
//! decals wrap across the edges, trim / atlas layouts and their JSON.

use super::automation::Session;
use super::*;
use serde_json::{json, Value};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn material(s: &mut Session) -> export::MaterialImages {
    s.app.commit_doc_changes();
    s.app.ensure_composited(&s.rs);
    io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts)
}

/// A road-ish stack touching every kind of world-space noise the generators use.
fn stack(s: &mut Session) {
    for l in [
        json!({ "name": "Grunge", "material": "Grime", "mask": { "generator": "grunge", "amount": 0.5, "scale": 1.3 } }),
        json!({ "name": "Spots", "values": { "base_color": [0.6, 0.6, 0.6], "height": 0.4 }, "mask": { "generator": "spots", "amount": 0.35, "scale": 2.0 } }),
        json!({ "name": "Cracks", "values": { "base_color": [0.05, 0.05, 0.05], "height": -0.6 }, "mask": { "generator": "scratches", "amount": 0.45, "scale": 2.7 } }),
        json!({ "name": "Wear", "values": { "base_color": [0.4, 0.38, 0.35] }, "mask": { "generator": "edge_wear", "amount": 0.5, "scale": 3.1, "breakup": 1.0 } }),
        json!({ "name": "Puddles", "values": { "base_color": [0.02, 0.02, 0.02], "roughness": 0.05 }, "mask": { "generator": "puddles", "amount": 0.4, "scale": 0.7 } }),
        json!({ "name": "Moss", "values": { "base_color": [0.2, 0.3, 0.1] }, "opacity": 0.5, "mask": { "generator": "moss", "amount": 0.3, "scale": 1.7 } }),
        json!({ "name": "Setts", "values": { "height": 0.3 }, "opacity": 0.6, "mask": { "generator": "tiles", "variant": "bricks", "scale": 3.3, "aspect": 2.1 } }),
        json!({ "name": "Hex", "values": { "base_color": [0.5, 0.5, 0.6] }, "opacity": 0.3, "mask": { "generator": "tiles", "variant": "hex", "scale": 2.3 } }),
        json!({ "name": "Joints", "values": { "height": -0.4 }, "mask": { "generator": "panel_lines", "amount": 0.03, "scale": 0.9 } }),
    ] {
        s.add_layer(&l).unwrap();
    }
}

/// Mean absolute difference between two RGBA8 / 16-bit planes after rolling
/// `b` by (dx, dy) texels.
fn rolled_diff(a: &[u8], b: &[u8], size: usize, ch: usize, dx: usize, dy: usize) -> f64 {
    let mut sum = 0u64;
    for y in 0..size {
        for x in 0..size {
            let (xs, ys) = ((x + dx) % size, (y + dy) % size);
            for c in 0..ch {
                sum += (a[(y * size + x) * 4 + c] as i32 - b[(ys * size + xs) * 4 + c] as i32).unsigned_abs() as u64;
            }
        }
    }
    sum as f64 / (size * size * ch) as f64
}

/// Mean |difference| across the left/right seam and across interior columns
/// (and the same for rows), on channel 0..ch of an RGBA8 image.
fn seams(img: &[u8], size: usize, ch: usize) -> [f64; 4] {
    let px = |x: usize, y: usize, c: usize| img[(y * size + x) * 4 + c] as f64;
    let (mut sx, mut ix, mut sy, mut iy) = (0.0, 0.0, 0.0, 0.0);
    for i in 0..size {
        for c in 0..ch {
            sx += (px(0, i, c) - px(size - 1, i, c)).abs();
            sy += (px(i, 0, c) - px(i, size - 1, c)).abs();
            // interior: every pair of neighbouring columns / rows
            for k in 1..size {
                ix += (px(k, i, c) - px(k - 1, i, c)).abs();
                iy += (px(i, k, c) - px(i, k - 1, c)).abs();
            }
        }
    }
    let n = (size * ch) as f64;
    let m = n * (size - 1) as f64;
    [sx / n, ix / m, sy / n, iy / m]
}

/// Gradient continuity: the one-sided slope just inside each edge predicts
/// the value across the seam about as well as it does in the interior.
fn gradient_error(h: &[u16], size: usize) -> [f64; 2] {
    let v = |x: usize, y: usize| h[y * size + x] as f64;
    let (mut seam, mut inner) = (0.0, 0.0);
    for y in 0..size {
        // extrapolate x = N-2, N-1 -> 0, vs every interior x-2, x-1 -> x
        seam += (2.0 * v(size - 1, y) - v(size - 2, y) - v(0, y)).abs();
        for x in 2..size {
            inner += (2.0 * v(x - 1, y) - v(x - 2, y) - v(x, y)).abs();
        }
    }
    [seam / size as f64, inner / (size * (size - 2)) as f64]
}

#[test]
fn seamless_tile_maps_wrap() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    let out = s.new_project(&json!({ "tile": { "size_m": [3, 3] }, "resolution": 512, "material": "Asphalt" })).unwrap();
    assert_eq!(out["tile"]["kind"], "tile");
    assert_eq!(out["tile"]["wrap"]["u"], true);
    stack(&mut s);
    let a = material(&mut s);
    let n = a.size as usize;

    // 1. the tile scrolled by part of its period gives the same maps, rolled:
    //    the pattern really is periodic (noise, tiles, panel lines, puddles,
    //    and the height-to-normal pass across the edges)
    let mut s2 = s;
    s2.new_project(&json!({ "tile": { "size_m": [3, 3], "offset_m": [1.5, -0.75] }, "resolution": 512, "material": "Asphalt" })).unwrap();
    stack(&mut s2);
    let b = material(&mut s2);
    // texel x of the scrolled tile sits where texel x + N/2 of the original was (y: - N/4)
    let (dx, dy) = (n / 2, n - n / 4);
    let dc = rolled_diff(&b.color, &a.color, n, 3, dx, dy);
    let dn = rolled_diff(&b.normal, &a.normal, n, 3, dx, dy);
    let dr = rolled_diff(&b.orm, &a.orm, n, 3, dx, dy);
    assert!(dc < 1.0 && dn < 1.5 && dr < 1.0, "scrolled tile = rolled maps (colour {dc:.3}, normal {dn:.3}, orm {dr:.3})");
    // ...whereas an ordinary (non-wrapping) project changes when moved
    // (sanity check that the comparison above can fail)
    let not_rolled = rolled_diff(&b.color, &a.color, n, 3, 0, 0);
    assert!(not_rolled > 5.0 * dc.max(0.2), "scrolling changes the unrolled maps ({not_rolled:.3})");

    // 2. edge texels continue across the seam like neighbouring interior texels
    for (name, img) in [("colour", &a.color), ("normal", &a.normal), ("roughness", &a.orm)] {
        let [sx, ix, sy, iy] = seams(img, n, 3);
        assert!(sx < ix * 1.6 + 0.6 && sy < iy * 1.6 + 0.6, "{name}: seam x {sx:.2} vs interior {ix:.2}, seam y {sy:.2} vs {iy:.2}");
    }
    let [gs, gi] = gradient_error(&a.height, n);
    assert!(gs < gi * 1.6 + 30.0, "height gradient continues across the seam ({gs:.1} vs {gi:.1})");
}

#[test]
fn strokes_and_decals_wrap_across_tile_edges() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    s.new_project(&json!({ "tile": { "size_m": [2, 2] }, "resolution": 512, "material": "Concrete" })).unwrap();
    // a box decal straddling the right edge (x = +1 m) comes back in on the left
    let img = root().join("assets/decals/hazard_triangle.png");
    s.project_decal(&json!({ "image": img, "position": [1.0, 0.0, 0.0], "normal": [0, 1, 0], "size": 0.6, "tint": [1.0, 0.0, 0.0] })).unwrap();
    let m = material(&mut s);
    let n = m.size as usize;
    let red = |x0: usize, x1: usize| {
        let mut k = 0;
        for y in n / 2 - 40..n / 2 + 40 {
            for x in x0..x1 {
                let p = &m.color[(y * n + x) * 4..];
                if p[0] as i32 > p[1] as i32 + 40 {
                    k += 1;
                }
            }
        }
        k
    };
    let (left, right, middle) = (red(0, 40), red(n - 40, n), red(n / 2 - 40, n / 2 + 40));
    assert!(left > 300 && right > 300, "decal on both sides of the seam (left {left}, right {right})");
    assert_eq!(middle, 0);
    // undo takes back both halves
    s.undo(false).unwrap();
    let m = material(&mut s);
    assert!(m.color.chunks_exact(4).all(|p| (p[0] as i32) < p[1] as i32 + 40), "undo removes both halves");

    // a brush stroke from the middle out past the left edge (top view)
    s.paint_stroke(&json!({ "points": [[0.5, 0.5], [0.02, 0.5]], "size": 30, "values": { "base_color": [0.0, 0.0, 1.0] }, "yaw": 0, "pitch": 89.9, "zoom": 1.0, "width": 512, "height": 512 })).unwrap();
    let m = material(&mut s);
    let blue = |x0: usize, x1: usize| (0..n).flat_map(|y| (x0..x1).map(move |x| (x, y))).filter(|&(x, y)| { let p = &m.color[(y * n + x) * 4..]; p[2] as i32 > p[0] as i32 + 60 }).count();
    let (l, r) = (blue(0, 30), blue(n - 30, n));
    assert!(l > 50 && r > 50, "the stroke crosses the edge and continues on the other side (left {l}, right {r})");
}

#[test]
fn trim_and_atlas_layouts() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    let out = s
        .new_project(&json!({ "tile": { "size_m": 2, "strips": [{ "name": "Curb top", "height_m": 0.3 }, { "name": "Curb face", "height_m": 0.2 }, { "name": "Gutter", "height_m": 0.5 }, { "name": "Kerb paint", "height_m": 1.0 }] }, "resolution": 512 }))
        .unwrap();
    assert_eq!(out["tile"]["kind"], "trim");
    assert_eq!(out["tile"]["wrap"]["v"], false);
    let names: Vec<String> = out["layers"].as_array().unwrap().iter().map(|l| l["name"].as_str().unwrap().to_string()).collect();
    for n in ["Curb top", "Curb face", "Gutter", "Kerb paint"] {
        assert!(names.iter().any(|x| x == n), "folder per strip: {names:?}");
    }
    // a material inside the Gutter folder lands only in the gutter's V range
    s.add_layer(&json!({ "name": "Wet", "parent": "Gutter", "values": { "base_color": [1.0, 0.0, 0.0] } })).unwrap();
    let m = material(&mut s);
    let n = m.size as usize;
    let row_red = |v: f32| { let y = (v * n as f32) as usize; let p = &m.color[(y * n + n / 2) * 4..]; p[0] as i32 > p[1] as i32 + 60 };
    assert!(row_red(0.375) && !row_red(0.2) && !row_red(0.6), "gutter strip is v 0.25..0.5");
    let dir = std::env::temp_dir().join(format!("pigment-trim-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    let e = s.export_textures(&json!({ "dir": dir, "name": "trim", "preset": "separate" })).unwrap();
    assert!(e["files"].to_string().contains("trim_layout.json"));
    let j: Value = serde_json::from_str(&std::fs::read_to_string(dir.join("trim_layout.json")).unwrap()).unwrap();
    assert_eq!(j["cells"][2]["name"], "Gutter");
    assert!((j["cells"][2]["uv"][1].as_f64().unwrap() - 0.25).abs() < 1e-6);
    assert!((j["cells"][2]["uv_gl"][1].as_f64().unwrap() - 0.5).abs() < 1e-6);

    // save + reopen keeps the sheet (wrap, layout)
    s.save_project(&json!({ "path": dir.join("trim.pigment") })).unwrap();
    s.open_project(&json!({ "path": dir.join("trim.pigment") })).unwrap();
    assert_eq!(s.app.doc.tile.as_ref().map(|t| t.cells.len()), Some(4));
    assert_eq!(s.app.ts.tile_period, [2.0, 0.0]);

    // atlas: transparent outside the cells, BaseColorAlpha written
    let out = s.new_project(&json!({ "tile": { "cells": [{ "name": "Manhole", "size_m": [0.8, 0.8] }, { "name": "Arrow", "size_m": [0.6, 2.0] }, { "name": "Crack", "size_m": [1.2, 0.4] }] }, "resolution": 512 })).unwrap();
    assert_eq!(out["tile"]["cells"].as_array().unwrap().len(), 3);
    s.add_layer(&json!({ "name": "Ink", "parent": "Arrow", "values": { "base_color": [1.0, 1.0, 1.0], "opacity": 1.0 } })).unwrap();
    let m = material(&mut s);
    let cell = &out["tile"]["cells"][1]["uv"];
    let (cu, cv) = ((cell[0].as_f64().unwrap() + cell[2].as_f64().unwrap()) * 0.5, (cell[1].as_f64().unwrap() + cell[3].as_f64().unwrap()) * 0.5);
    let n = m.size as usize;
    let alpha = |u: f64, v: f64| m.color[(((v * n as f64) as usize) * n + (u * n as f64) as usize) * 4 + 3];
    assert_eq!(alpha(cu, cv), 255, "arrow cell is opaque");
    let mc = &out["tile"]["cells"][0]["uv"];
    assert_eq!(alpha((mc[0].as_f64().unwrap() + mc[2].as_f64().unwrap()) * 0.5, (mc[1].as_f64().unwrap() + mc[3].as_f64().unwrap()) * 0.5), 0, "other cells stay transparent");
    let e = s.export_textures(&json!({ "dir": dir, "name": "atlas", "preset": "separate" })).unwrap();
    assert!(e["files"].to_string().contains("atlas_BaseColorAlpha.png"));
    assert!(s.new_project(&json!({ "tile": { "strips": [], "size_m": 1 } })).is_err());
    assert!(s.new_project(&json!({ "tile": { "size_m": [2, 2], "wrap": "diagonal" } })).is_err());
    std::fs::remove_dir_all(&dir).ok();
}
