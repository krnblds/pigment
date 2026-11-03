//! The ground generators and fill options (docs/agents/ground/NOTES.md) end
//! to end through the MCP Session: seamless tiles, rounded per-instance
//! heights, per-instance jitter, height blend, MCP args.

use super::automation::Session;
use super::*;
use serde_json::{json, Value};

fn material(s: &mut Session) -> export::MaterialImages {
    s.app.commit_doc_changes();
    s.app.ensure_composited(&s.rs);
    io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts)
}

fn tile(s: &mut Session, size: f32, offset: [f32; 2], res: u32) {
    s.new_project(&json!({ "tile": { "size_m": [size, size], "offset_m": offset }, "resolution": res, "material": "Concrete" })).unwrap();
    s.delete_layer(&json!({ "layer": "Paint" })).unwrap();
    s.update_layer(&json!({ "layer": "Base", "values": { "base_color": [0.2, 0.2, 0.2], "height": 0.0, "roughness": 0.9 } })).unwrap();
}

/// Every ground generator plus the fill options, in one stack.
fn ground_stack(s: &mut Session) {
    for l in [
        json!({ "name": "Rock", "values": { "base_color": [0.4, 0.38, 0.35], "height": 0.6 }, "height_profile": true, "jitter": 0.2,
                "mask": { "generator": "rock", "scale": 1.1, "strata": 0.6, "cracks": 0.8, "bands": 1.7, "streaks": 0.5, "warp": 0.6 } }),
        json!({ "name": "Plates", "values": { "base_color": [0.5, 0.45, 0.4], "height": 0.3 }, "opacity": 0.5, "height_profile": true,
                "mask": { "generator": "cobbles", "scale": 2.3, "edge_width": 0.03, "warp": 0.3, "edge_noise": 0.5 } }),
        json!({ "name": "Sand", "values": { "base_color": [0.7, 0.6, 0.4], "height": 0.25 }, "height_blend": { "mode": "above", "contrast": 0.05 },
                "mask": { "generator": "ripples", "scale": 3.3, "angle": 25, "defects": 0.5, "irregularity": 0.6 } }),
        json!({ "name": "Pebbles", "values": { "base_color": [0.6, 0.6, 0.62], "height": 0.7 }, "height_profile": true, "jitter": { "value": 0.3, "hue": 0.05 },
                "mask": { "generator": "pebbles", "scale": 4.3, "density": 0.6, "size": 0.4, "per_cell": 2 } }),
        json!({ "name": "Leaves", "values": { "base_color": [0.5, 0.3, 0.1], "height": 0.4 }, "height_profile": true,
                "mask": { "generator": "leaves", "scale": 3.1, "density": 0.4, "size": 0.35, "elongation": 1.8 } }),
        json!({ "name": "Grass", "values": { "base_color": [0.2, 0.4, 0.1], "height": 0.5 }, "height_profile": true, "opacity": 0.8,
                "mask": { "generator": "grass", "scale": 37.0, "density": 0.5, "length": 0.12, "lean": 0.6 } }),
        json!({ "name": "Moss", "values": { "base_color": [0.1, 0.3, 0.05] }, "channels": { "height": false }, "height_blend": { "mode": "tops", "offset": 0.5 } }),
    ] {
        s.add_layer(&l).unwrap();
    }
}

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

/// Mean |difference| across the left/right and top/bottom seams vs. between
/// interior neighbours.
fn seams(img: &[u8], size: usize, ch: usize) -> [f64; 4] {
    let px = |x: usize, y: usize, c: usize| img[(y * size + x) * 4 + c] as f64;
    let (mut sx, mut ix, mut sy, mut iy) = (0.0, 0.0, 0.0, 0.0);
    for i in 0..size {
        for c in 0..ch {
            sx += (px(0, i, c) - px(size - 1, i, c)).abs();
            sy += (px(i, 0, c) - px(i, size - 1, c)).abs();
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

#[test]
fn ground_generators_tile_seamlessly() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    tile(&mut s, 3.0, [0.0, 0.0], 512);
    ground_stack(&mut s);
    let a = material(&mut s);
    let n = a.size as usize;
    // scrolled by part of the period = the same maps, rolled
    tile(&mut s, 3.0, [1.5, -0.75], 512);
    ground_stack(&mut s);
    let b = material(&mut s);
    let (dx, dy) = (n / 2, n - n / 4);
    let dc = rolled_diff(&b.color, &a.color, n, 3, dx, dy);
    let dn = rolled_diff(&b.normal, &a.normal, n, 3, dx, dy);
    let dr = rolled_diff(&b.orm, &a.orm, n, 3, dx, dy);
    assert!(dc < 1.0 && dn < 1.5 && dr < 1.0, "scrolled tile = rolled maps (colour {dc:.3}, normal {dn:.3}, orm {dr:.3})");
    let not_rolled = rolled_diff(&b.color, &a.color, n, 3, 0, 0);
    assert!(not_rolled > 5.0 * dc.max(0.2), "scrolling changes the unrolled maps ({not_rolled:.3})");
    for (name, img) in [("colour", &a.color), ("normal", &a.normal), ("roughness", &a.orm)] {
        let [sx, ix, sy, iy] = seams(img, n, 3);
        assert!(sx < ix * 1.6 + 0.6 && sy < iy * 1.6 + 0.6, "{name}: seam x {sx:.2} vs interior {ix:.2}, seam y {sy:.2} vs {iy:.2}");
    }
}

/// Fraction of covered texels (height above `floor`) whose height lies
/// strictly between 20 % and 80 % of the maximum: rounded shapes have many,
/// flat plateaus almost none.
fn rounded_fraction(h: &[u16], floor: f64) -> f64 {
    let v: Vec<f64> = h.iter().map(|x| (*x as f64 - 32768.0) / 32767.0).collect();
    let max = v.iter().cloned().fold(0.0, f64::max);
    let covered: Vec<f64> = v.into_iter().filter(|x| *x > floor).collect();
    covered.iter().filter(|x| **x > 0.2 * max && **x < 0.8 * max).count() as f64 / covered.len().max(1) as f64
}

#[test]
fn scatter_instances_are_rounded_and_jittered() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    tile(&mut s, 2.0, [0.0, 0.0], 512);
    let pebbles = json!({ "generator": "pebbles", "scale": 6.0, "density": 0.7, "size": 0.45 });
    s.add_layer(&json!({ "name": "P", "values": { "base_color": [0.6, 0.6, 0.6], "height": 0.8 }, "mask": pebbles })).unwrap();
    let flat = material(&mut s);
    s.update_layer(&json!({ "layer": "P", "height_profile": true, "jitter": { "value": 0.4 } })).unwrap();
    let round = material(&mut s);
    let (rf, rr) = (rounded_fraction(&flat.height, 0.01), rounded_fraction(&round.height, 0.01));
    assert!(rr > 0.3 && rf < 0.12, "domes: {rr:.2} of the stones' texels are on their slopes (flat plateau: {rf:.2})");
    // per-instance tone: the stones' brightness spreads out with jitter
    let spread = |m: &export::MaterialImages| {
        let g: Vec<f64> = m.color.chunks(4).filter(|p| p[0] > 80).map(|p| p[0] as f64).collect();
        let mean = g.iter().sum::<f64>() / g.len().max(1) as f64;
        (g.iter().map(|x| (x - mean) * (x - mean)).sum::<f64>() / g.len().max(1) as f64).sqrt()
    };
    let (sf, sj) = (spread(&flat), spread(&round));
    assert!(sj > sf * 3.0 + 4.0, "jitter varies the stones' tone (std {sj:.1} vs {sf:.1})");
    // shapes: leaves, twigs and shells cover something, and each differently
    let mut cover = vec![];
    for v in ["leaf", "twig", "shell", "flake"] {
        s.update_layer(&json!({ "layer": "P", "jitter": null, "mask": { "generator": "scatter", "variant": v, "elongation": if v == "twig" { 8.0 } else { 1.6 }, "size": if v == "twig" { 0.08 } else { 0.4 } } })).unwrap();
        let m = material(&mut s);
        let c = m.color.chunks(4).filter(|p| p[0] > 80).count() as f64 / (m.size * m.size) as f64;
        assert!(c > 0.01 && c < 0.95, "{v}: covers {c:.3}");
        cover.push(c);
    }
    assert!(cover.windows(2).all(|w| (w[0] - w[1]).abs() > 1e-3), "shapes differ: {cover:?}");
}

#[test]
fn height_blend_fills_the_lows_and_caps_the_tops() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    tile(&mut s, 2.0, [0.0, 0.0], 512);
    s.add_layer(&json!({ "name": "Stones", "values": { "base_color": [0.5, 0.5, 0.5], "height": 0.8 }, "height_profile": true,
                         "mask": { "generator": "pebbles", "scale": 5.0, "density": 0.6, "size": 0.45 } })).unwrap();
    let before = material(&mut s);
    // red sand settles up to height 0.3 between the stones; green moss caps what rises above 0.6
    s.add_layer(&json!({ "name": "Sand", "values": { "base_color": [1.0, 0.0, 0.0], "height": 0.3 }, "height_blend": { "mode": "lows", "contrast": 0.02 } })).unwrap();
    s.add_layer(&json!({ "name": "Moss", "values": { "base_color": [0.0, 1.0, 0.0] }, "channels": { "height": false }, "height_blend": { "mode": "tops", "offset": 0.6, "contrast": 0.02 } })).unwrap();
    let after = material(&mut s);
    let h = |m: &export::MaterialImages, i: usize| (m.height[i] as f64 - 32768.0) / 32767.0;
    let (mut low_red, mut low_n, mut top_red, mut top_green, mut top_n, mut mid_green, mut mid_n) = (0, 0, 0, 0, 0, 0, 0);
    for i in 0..(after.size * after.size) as usize {
        let (r, g) = (after.color[i * 4] > 150, after.color[i * 4 + 1] > 150);
        let h0 = h(&before, i);
        if h0 < 0.15 {
            low_n += 1;
            low_red += r as u32;
        } else if h0 > 0.7 {
            top_n += 1;
            top_red += r as u32;
            top_green += g as u32;
        } else if h0 > 0.35 && h0 < 0.55 {
            mid_n += 1;
            mid_green += g as u32;
        }
    }
    let f = |a: u32, n: u32| a as f64 / n.max(1) as f64;
    assert!(low_n > 1000 && top_n > 1000 && mid_n > 1000, "{low_n} {top_n} {mid_n}");
    assert!(f(low_red, low_n) > 0.97, "sand fills the gaps: {:.3}", f(low_red, low_n));
    assert!(f(top_red, top_n) < 0.01, "stone tops stay clear of sand: {:.3}", f(top_red, top_n));
    assert!(f(top_green, top_n) > 0.97, "moss on the tops: {:.3}", f(top_green, top_n));
    assert!(f(mid_green, mid_n) < 0.03, "no moss on the flanks: {:.3}", f(mid_green, mid_n));
    // the sand raised the gaps to its level
    let raised = (0..(after.size * after.size) as usize).filter(|&i| h(&before, i) < 0.05).map(|i| h(&after, i)).sum::<f64>() / low_n as f64;
    assert!((raised - 0.3).abs() < 0.06, "gaps filled to the sand level: {raised:.3}");
}

#[test]
fn ground_mcp_args() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    tile(&mut s, 2.0, [0.0, 0.0], 512);
    s.add_layer(&json!({ "name": "Setts", "mask": { "generator": "cobbles", "edge_width": 0.03, "randomness": 0.4, "stretch": 1.5 }, "jitter": 0.25, "height_profile": true,
                         "height_blend": "below" })).unwrap();
    let layers = s.layers();
    let l = layers.as_array().unwrap().iter().find(|l| l["name"] == "Setts").unwrap();
    let g = &l["mask"]["generator"];
    assert_eq!(g["kind"], "cells");
    assert_eq!(g["variant_name"], "plates");
    assert!((g["curvature_weight"].as_f64().unwrap() - 0.03).abs() < 1e-6 && (g["ao_influence"].as_f64().unwrap() - 0.4).abs() < 1e-6);
    assert!((g["extra"][0].as_f64().unwrap() - 1.5).abs() < 1e-6);
    assert_eq!(l["height_blend"]["mode"], "below");
    assert!((l["jitter"]["value"].as_f64().unwrap() - 0.25).abs() < 1e-6);
    assert_eq!(l["height_profile"], true);
    // named variants per generator, aliases, numeric variants
    s.update_layer(&json!({ "layer": "Setts", "mask": { "generator": "scatter", "variant": "leaf", "density": 0.3 } })).unwrap();
    let g = s.layers()[1]["mask"]["generator"].clone();
    assert_eq!((g["kind"].as_str(), g["variant_name"].as_str()), (Some("scatter"), Some("leaf")));
    assert!((g["amount"].as_f64().unwrap() - 0.3).abs() < 1e-6);
    s.update_layer(&json!({ "layer": "Setts", "mask": { "generator": "grass", "lean": 0.9, "length": 0.1 } })).unwrap();
    assert_eq!(s.layers()[1]["mask"]["generator"]["kind"], "blades");
    let e = s.update_layer(&json!({ "layer": "Setts", "mask": { "generator": "cells", "variant": "bricks" } })).unwrap_err();
    assert!(e.contains("cells takes one of: dome, f2, edges, value, plates"), "{e}");
    let e = s.update_layer(&json!({ "layer": "Setts", "height_blend": "sideways" })).unwrap_err();
    assert!(e.contains("above"), "{e}");
    s.update_layer(&json!({ "layer": "Setts", "height_blend": null, "jitter": null, "height_profile": false })).unwrap();
    let l = s.layers()[1].clone();
    assert!(l.get("height_blend").is_none() && l.get("jitter").is_none() && l.get("height_profile").is_none(), "{l}");
    // fill layers only
    s.add_layer(&json!({ "kind": "paint", "name": "P" })).unwrap();
    assert!(s.update_layer(&json!({ "layer": "P", "jitter": 0.2 })).is_err());
    // library lists the variants and aliases
    let lib = s.library();
    let gens = lib["generators"].as_array().unwrap();
    let rip = gens.iter().find(|g| g["id"] == "ripples").unwrap();
    assert_eq!(rip["variants"], json!(["height", "crests"]));
    assert!(lib["ground_aliases"].as_array().unwrap().iter().any(|a| a["alias"] == "cobbles"));
    // projects keep it all
    let dir = std::env::temp_dir().join(format!("pigment-ground-{}", std::process::id()));
    s.update_layer(&json!({ "layer": "Setts", "height_blend": { "mode": "above", "offset": 0.1 }, "jitter": { "hue": 0.03 } })).unwrap();
    s.save_project(&json!({ "path": dir.join("g.pigment") })).unwrap();
    s.open_project(&json!({ "path": dir.join("g.pigment") })).unwrap();
    let l: Value = s.layers()[1].clone();
    assert_eq!(l["height_blend"]["mode"], "above");
    assert!((l["jitter"]["hue"].as_f64().unwrap() - 0.03).abs() < 1e-6);
    let _ = std::fs::remove_dir_all(dir);
}

/// A wood floor: plank faces, latewood, pores and dark joints, all reading one planks layout.
fn planks_stack(s: &mut Session, layout: &str, joint: f32) {
    let g = json!({ "generator": "planks", "variant": layout, "scale": 7.0, "length_ratio": 4, "joint_width": joint, "knots": 0.4, "seed": 3 });
    let with = |out: &str| {
        let mut m = g.clone();
        m["output"] = json!(out);
        m
    };
    for l in [
        json!({ "name": "Oak", "values": { "base_color": [0.9, 0.9, 0.9], "height": 0.4 }, "height_profile": true, "jitter": { "value": 0.2 }, "mask": with("surface") }),
        json!({ "name": "Latewood", "values": { "base_color": [0.6, 0.6, 0.6] }, "channels": { "height": false }, "mask": with("latewood") }),
        json!({ "name": "Pores", "values": { "base_color": [0.5, 0.5, 0.5], "height": -0.2 }, "opacity": 0.5, "mask": with("pores") }),
        json!({ "name": "Joints", "values": { "base_color": [0.0, 0.0, 0.0], "height": -0.5 }, "mask": with("joints") }),
    ] {
        s.add_layer(&l).unwrap();
    }
}

#[test]
fn planks_tile_seamlessly_in_every_layout() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    for layout in pigment_core::ground::PLANK_LAYOUTS {
        tile(&mut s, 2.0, [0.0, 0.0], 512);
        planks_stack(&mut s, layout, 0.004);
        let a = material(&mut s);
        let n = a.size as usize;
        for (name, img) in [("colour", &a.color), ("normal", &a.normal)] {
            let [sx, ix, sy, iy] = seams(img, n, 3);
            assert!(sx < ix * 1.6 + 0.6 && sy < iy * 1.6 + 0.6, "{layout} {name}: seam x {sx:.2} vs interior {ix:.2}, seam y {sy:.2} vs {iy:.2}");
        }
        // the joints are a thin network, not blotches: about joint / width of the floor
        let dark = a.color.chunks(4).filter(|p| p[0] < 128).count() as f64 / (n * n) as f64;
        assert!((0.01..0.12).contains(&dark), "{layout}: joints cover {:.1} % of the floor", dark * 100.0);
    }
}

#[test]
fn planks_layers_share_their_layout() {
    let _gpu = super::automation::gpu_lock();
    let Ok(mut s) = Session::new() else { return };
    tile(&mut s, 2.0, [0.0, 0.0], 512);
    planks_stack(&mut s, "boards", 0.002);
    s.update_layer(&json!({ "layer": "Oak", "mask": { "generator": "planks", "variant": "herringbone", "scale": 12.0, "rings_per_cm": 5.0 } })).unwrap();
    let gens: Vec<_> = s.app.doc.layers.iter().filter_map(|l| l.mask.as_ref()?.generator.clone().map(|g| (l.name.clone(), g))).collect();
    for (name, g) in &gens {
        assert_eq!((g.variant, g.noise_scale, g.extra[0]), (1, 12.0, 5.0), "{name} follows the edited layout");
    }
    let outputs: Vec<f32> = gens.iter().map(|(_, g)| g.extra[3]).collect();
    assert_eq!(outputs, vec![0.0, 2.0, 3.0, 1.0], "each layer keeps its own output");
}
