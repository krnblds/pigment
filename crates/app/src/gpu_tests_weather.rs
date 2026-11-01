//! GPU tests for the weathering / pattern generators (leaks, puddles, moss,
//! tiles, window grid) and the drip / rain-exposure bakes they read.

use super::*;

/// A 4 m wall facing +z with a 30 cm deep sill sticking out of it, standing
/// on a ground plane: enough to tell "under the sill" from "open wall" and
/// "flat ground" from "wall". Each quad gets its own UV atlas cell.
fn facade_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    let v = |x: f32, y: f32, z: f32| [x, y, z];
    // corners counter-clockwise seen from outside
    let quads: Vec<[[f32; 3]; 4]> = vec![
        [v(0., 0., 0.), v(4., 0., 0.), v(4., 4., 0.), v(0., 4., 0.)],         // wall, +z
        [v(-1., 0., 4.), v(5., 0., 4.), v(5., 0., 0.), v(-1., 0., 0.)],       // ground, +y
        [v(1., 2.1, 0.3), v(2., 2.1, 0.3), v(2., 2.1, 0.), v(1., 2.1, 0.)],   // sill top
        [v(1., 2.0, 0.), v(2., 2.0, 0.), v(2., 2.0, 0.3), v(1., 2.0, 0.3)],   // sill bottom
        [v(1., 2.0, 0.3), v(2., 2.0, 0.3), v(2., 2.1, 0.3), v(1., 2.1, 0.3)], // sill front
        [v(1., 2.0, 0.), v(1., 2.0, 0.3), v(1., 2.1, 0.3), v(1., 2.1, 0.)],   // sill left
        [v(2., 2.0, 0.3), v(2., 2.0, 0.), v(2., 2.1, 0.), v(2., 2.1, 0.3)],   // sill right
        [v(4., 0., -0.2), v(0., 0., -0.2), v(0., 4., -0.2), v(4., 4., -0.2)], // wall back, -z
    ];
    // (u0, v0, size): wall and ground get big cells, the rest small ones
    let cells = [(0.0, 0.5, 0.5), (0.5, 0.5, 0.5), (0.0, 0.0, 0.25), (0.25, 0.0, 0.25), (0.5, 0.0, 0.25), (0.75, 0.0, 0.25), (0.0, 0.25, 0.25), (0.25, 0.25, 0.25)];
    for (quad, (ou, ov, sz)) in quads.iter().zip(cells) {
        let base = mesh.vertices.len() as u32;
        for (k, p) in quad.iter().enumerate() {
            let (u, w) = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)][k];
            mesh.vertices.push(Vertex { position: *p, normal: [0.0; 3], uv: [ou + u * sz, ov + w * sz], tangent: [0.0; 4] });
        }
        mesh.indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    }
    mesh.compute_normals();
    mesh.compute_tangents();
    mesh
}

struct Weather {
    s: Scene,
    /// world position + coverage per texel
    pos: Vec<[f32; 4]>,
    bakes: Vec<[f32; 4]>,
}

fn weather_scene() -> Option<Weather> {
    let mut s = Scene::new()?;
    let (d, q) = (&s.g.device, &s.g.queue);
    let mesh = facade_mesh();
    let mg = MeshGpu::new(d, &mesh);
    let (c, r) = mesh.bounding_sphere();
    s.ts.prepare_mesh(d, q, &mg, c, r);
    Baker::new(d).bake(d, q, &mesh, &mg, &mut s.ts, &BakeSettings { ao_samples: 64, ..Default::default() });
    let pos = crate::render::gpu::readback(d, q, &s.ts.position)
        .chunks_exact(16)
        .map(|c| [0, 1, 2, 3].map(|k| f32::from_le_bytes([c[4 * k], c[4 * k + 1], c[4 * k + 2], c[4 * k + 3]])))
        .collect();
    let bakes = crate::render::gpu::readback(d, q, &s.ts.bakes)
        .chunks_exact(8)
        .map(|c| [0, 1, 2, 3].map(|k| half::f16::from_bits(u16::from_le_bytes([c[2 * k], c[2 * k + 1]])).to_f32()))
        .collect();
    Some(Weather { s, pos, bakes })
}

impl Weather {
    /// Composite one fill layer (metallic 1) masked by `g`; mask value per texel 0..1.
    fn mask(&mut self, g: Generator) -> Vec<f32> {
        let (d, q) = (&self.s.g.device, &self.s.g.queue);
        let mut doc = Document::new_default();
        let mut l = doc.new_fill_layer("gen");
        if let LayerKind::Fill { values } = &mut l.kind {
            values.metallic = 1.0;
        }
        let mres = doc.mint();
        self.s.ts.new_mask(d, q, mres, true);
        l.mask = Some(Mask::with_generator(mres, g));
        doc.layers.push(l);
        self.s.ts.ensure_resources(d, q, &doc);
        self.s.ts.composite(d, q, &doc, None);
        io::read_material(d, q, &self.s.ts).orm.chunks_exact(4).map(|p| p[2] as f32 / 255.0).collect()
    }
    /// Mean of `vals` over covered texels whose world position passes `f`, and how many.
    fn mean(&self, vals: impl Fn(usize) -> f32, f: impl Fn([f32; 3]) -> bool) -> (f32, usize) {
        let (mut sum, mut n) = (0.0, 0);
        for (i, p) in self.pos.iter().enumerate() {
            if p[3] > 0.5 && f([p[0], p[1], p[2]]) {
                sum += vals(i);
                n += 1;
            }
        }
        (if n > 0 { sum / n as f32 } else { 0.0 }, n)
    }
}

// The wall's front face is at z = 0, its back face at z = -0.2.
fn wall(p: [f32; 3]) -> bool {
    p[2].abs() < 0.002 && p[1] > 0.02
}
fn under_sill(p: [f32; 3]) -> bool {
    wall(p) && (1.15..1.85).contains(&p[0]) && (0.9..1.95).contains(&p[1])
}
fn open_wall(p: [f32; 3]) -> bool {
    wall(p) && (2.6..3.9).contains(&p[0]) && (0.9..1.95).contains(&p[1])
}
fn ground(p: [f32; 3]) -> bool {
    p[1].abs() < 0.002 && p[2] > 0.5
}

#[test]
fn drip_and_rain_bakes_see_the_sill() {
    let Some(w) = weather_scene() else { return };
    let drip = |i: usize| w.bakes[i][2];
    let (under, n) = w.mean(drip, under_sill);
    let (open, m) = w.mean(drip, open_wall);
    eprintln!("drip: under {under} ({n}) open {open} ({m})");
    assert!(n > 100 && m > 100, "{n} / {m} texels");
    // 0.05..1.1 m below the sill: 1 / (1 + gap) ~0.48..0.95
    assert!(under > 0.45, "drip under the sill {under}");
    assert!(open < 0.01, "drip on open wall {open}");
    // open ground is rain-exposed, a wall only from its own side
    let rain = |i: usize| w.bakes[i][3];
    let (g, _) = w.mean(rain, ground);
    let (wl, _) = w.mean(rain, open_wall);
    eprintln!("rain: ground {g} wall {wl}");
    assert!(g > 0.85, "ground rain exposure {g}");
    assert!(g > wl + 0.2, "wall {wl} vs ground {g}");
}

#[test]
fn leaks_run_down_from_under_the_sill() {
    let Some(mut w) = weather_scene() else { return };
    let mut g = Generator::new(GeneratorKind::Leaks);
    g.ao_influence = 0.0;
    g.noise_amount = 0.3;
    let m = w.mask(g);
    let (under, _) = w.mean(|i| m[i], under_sill);
    let (open, _) = w.mean(|i| m[i], open_wall);
    let (gr, _) = w.mean(|i| m[i], ground);
    eprintln!("leaks: under {under} open {open} ground {gr}");
    assert!(under > 0.3, "leaks under the sill {under}");
    assert!(open < 0.02 && gr < 0.02, "leaks elsewhere: wall {open}, ground {gr}");
    // they fade with distance below the sill
    let (near, _) = w.mean(|i| m[i], |p| under_sill(p) && p[1] > 1.6);
    let (far, _) = w.mean(|i| m[i], |p| wall(p) && (1.15..1.85).contains(&p[0]) && p[1] < 0.4);
    assert!(near > far, "near {near} far {far}");
}

#[test]
fn puddles_and_moss_settle_on_up_facing_surfaces() {
    let Some(mut w) = weather_scene() else { return };
    let mut g = Generator::new(GeneratorKind::Puddles);
    g.amount = 0.5;
    let m = w.mask(g);
    let (gr, _) = w.mean(|i| m[i], ground);
    let (wl, _) = w.mean(|i| m[i], open_wall);
    eprintln!("puddles: ground {gr} wall {wl}");
    assert!(gr > 0.1 && gr < 0.95, "puddle coverage on the ground {gr}");
    assert!(wl < 0.01, "puddles on a wall {wl}");
    let m = w.mask(Generator::new(GeneratorKind::Moss));
    let (gr, _) = w.mean(|i| m[i], ground);
    let (top, _) = w.mean(|i| m[i], |p| (p[1] - 2.1).abs() < 0.002);
    let (wl, _) = w.mean(|i| m[i], open_wall);
    eprintln!("moss: ground {gr} sill top {top} wall {wl}");
    assert!(gr > wl + 0.2 && top > wl + 0.2, "moss: ground {gr} sill {top} wall {wl}");
}

#[test]
fn tiles_and_window_grid_are_regular_patterns() {
    let Some(mut w) = weather_scene() else { return };
    // bricks, all kept: brick faces with thin mortar lines
    let mut g = Generator::new(GeneratorKind::Tiles);
    g.noise_amount = 0.0;
    let m = w.mask(g.clone());
    let (b, _) = w.mean(|i| m[i], wall);
    let (mortar, _) = w.mean(|i| (m[i] < 0.1) as u8 as f32, wall);
    eprintln!("bricks: mean {b}, mortar {mortar}");
    assert!(b > 0.7 && mortar > 0.03 && mortar < 0.3, "bricks mean {b} mortar {mortar}");
    // half of the cells kept
    g.amount = 0.5;
    let m = w.mask(g.clone());
    let (half_kept, _) = w.mean(|i| m[i], wall);
    assert!((0.2..0.7).contains(&half_kept), "half the bricks: {half_kept}");
    // hexagons leave mortar too
    g.amount = 1.0;
    g.variant = 2;
    let m = w.mask(g);
    let (mortar, _) = w.mean(|i| (m[i] < 0.1) as u8 as f32, wall);
    eprintln!("hex mortar {mortar}");
    assert!(mortar > 0.03 && mortar < 0.4, "hex mortar {mortar}");

    // window grid, 1 m cells: all lit, none lit, about half lit; never on the ground
    let mut g = Generator::new(GeneratorKind::WindowGrid);
    g.noise_scale = 1.0;
    g.curvature_weight = 1.0;
    g.noise_amount = 0.0;
    g.amount = 1.0;
    let m = w.mask(g.clone());
    let (all, _) = w.mean(|i| m[i], wall);
    let (gr, _) = w.mean(|i| m[i], ground);
    g.amount = 0.0;
    let m = w.mask(g.clone());
    let (none, _) = w.mean(|i| m[i], wall);
    g.amount = 0.5;
    let m = w.mask(g);
    let (half_lit, _) = w.mean(|i| m[i], wall);
    eprintln!("windows: all {all} none {none} half {half_lit} ground {gr}");
    // a pane is (1 - 2 * 0.18) x (1 - 2 * 0.18) of its cell, ~0.41
    assert!((0.3..0.6).contains(&all), "all lit {all}");
    assert!(none < 0.01 && gr < 0.01, "none {none} ground {gr}");
    assert!(half_lit > all * 0.2 && half_lit < all * 0.8, "half lit {half_lit} of {all}");
}
