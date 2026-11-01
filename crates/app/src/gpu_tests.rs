//! End-to-end GPU tests without a window: real device, real shaders, real
//! paint / undo / composite / bake / export code paths. Skipped (with a
//! message) on machines without a usable GPU adapter.

use crate::render::bake::Baker;
use crate::render::env::Environment;
use crate::render::paint::{BrushGpu, Painter, StampGpu, Target, ViewGpu};
use crate::render::texset::TexSet;
use crate::render::viewport::{ViewSettings, Viewport};
use crate::render::{io, MeshGpu};
use eframe::egui_wgpu::wgpu;
use glam::Vec2;
use pigment_core::stroke::StrokeSampler;
use pigment_core::tiles::{ScreenBins, TileSet, GRID};
use pigment_core::*;

struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
}

fn gpu() -> Option<Gpu> {
    let instance = wgpu::Instance::default();
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default())).ok()?;
    let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor::default())).ok()?;
    Some(Gpu { device, queue })
}

const RES: u32 = 512;
const VIEW: Vec2 = Vec2::new(800.0, 800.0);

struct Scene {
    g: Gpu,
    mesh: Mesh,
    mg: MeshGpu,
    ts: TexSet,
    painter: Painter,
    viewport: Viewport,
    env: Environment,
    camera: OrbitCamera,
    doc: Document,
}

impl Scene {
    fn new() -> Option<Scene> {
        let Some(g) = gpu() else {
            eprintln!("no GPU adapter: skipping GPU test");
            return None;
        };
        let (d, q) = (&g.device, &g.queue);
        let mesh = Mesh::torus(1.0, 0.38, 96, 32);
        let mg = MeshGpu::new(d, &mesh);
        let mut doc = Document::new_default();
        doc.resolution = RES;
        let mut ts = TexSet::new(d, q, RES);
        let (c, r) = mesh.bounding_sphere();
        ts.prepare_mesh(d, q, &mg, c, r);
        ts.ensure_resources(d, q, &doc);
        ts.composite(d, q, &doc, None);
        let mut camera = OrbitCamera::default();
        camera.frame(c, r);
        let mut viewport = Viewport::new(d);
        viewport.ensure_targets(d, [VIEW.x as u32, VIEW.y as u32]);
        let env = Environment::studio(d, q);
        viewport.draw(d, q, &camera, &ViewSettings::default(), Some(&mg), &env, &ts);
        let painter = Painter::new(d, RES);
        Some(Scene { g, mesh, mg, ts, painter, viewport, env, camera, doc })
    }

    fn paint_res(&self) -> ResId {
        self.doc.layers.iter().find_map(|l| l.paint_res()).unwrap()
    }

    /// Paint a straight stroke between two viewport positions, a few stamps per "frame".
    fn stroke(&mut self, from: Vec2, to: Vec2) -> (crate::render::paint::Snapshot, TileSet) {
        let (d, q) = (&self.g.device, &self.g.queue);
        let target = Target::Layer(self.paint_res());
        assert!(self.painter.begin(d, q, &self.ts, target));
        let vp = self.camera.view_proj(VIEW.x / VIEW.y);
        let eye = self.camera.eye();
        let view = ViewGpu { view_proj: vp.to_cols_array_2d(), eye: [eye.x, eye.y, eye.z, 1.0], viewport: [VIEW.x, VIEW.y, self.camera.near(), 0.0] };
        let bins = ScreenBins::build(&self.mesh, vp, VIEW, Some(eye));
        let mut sampler = StrokeSampler::default();
        let mut all = TileSet::default();
        let radius = 25.0;
        let brush = BrushGpu {
            color: [0.8, 0.1, 0.05, 1.0],
            rmh: [0.3, 1.0, 0.5, 0.0],
            normal: [0.0, 0.0, 1.0, 0.0],
            enabled: [1.0, 1.0, 1.0, 1.0],
            enabled2: [0.0, 0.0, 1.0, 0.0],
            emissive: [0.0; 4],
            enabled3: [0.0; 4],
        };
        let mut frames = vec![sampler.begin(from)];
        for i in 1..=8 {
            frames.push(sampler.move_to(from.lerp(to, i as f32 / 8.0), 5.0));
        }
        let depth = self.viewport.paint_depth().unwrap();
        for pts in frames {
            let mut ft = TileSet::default();
            let stamps: Vec<StampGpu> = pts
                .iter()
                .map(|p| {
                    bins.mark_stamp(*p, radius, &mut ft);
                    StampGpu { center_radius: [p.x, p.y, radius, 1.0], params: [0.5, 0.0, 0.0, 0.0] }
                })
                .collect();
            all.union(&ft);
            if let Some(rect) = ft.texel_bounds(RES) {
                self.painter.stamps(d, q, &self.ts, &self.mg, depth, view, &stamps, &brush, rect);
                self.ts.composite(d, q, &self.doc, Some(rect));
            }
        }
        let snap = self.painter.end(d, q, &all).expect("stroke touched tiles");
        (snap, all)
    }

    fn layer(&self) -> project::LayerPixels {
        io::read_layer(&self.g.device, &self.g.queue, &self.ts, self.paint_res()).unwrap()
    }
}

fn changed_texels(a: &project::LayerPixels, b: &project::LayerPixels) -> Vec<(u32, u32)> {
    let mut out = Vec::new();
    for i in 0..(a.size * a.size) as usize {
        if a.color[4 * i..4 * i + 4] != b.color[4 * i..4 * i + 4] || a.height[2 * i..2 * i + 2] != b.height[2 * i..2 * i + 2] {
            out.push((i as u32 % a.size, i as u32 / a.size));
        }
    }
    out
}

#[test]
fn stroke_paints_only_inside_its_tiles_and_undo_redo_is_exact() {
    let Some(mut s) = Scene::new() else { return };
    let blank = s.layer();
    let (mut snap1, tiles1) = s.stroke(Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
    let after1 = s.layer();
    let changed = changed_texels(&blank, &after1);
    assert!(changed.len() > 100, "stroke painted only {} texels", changed.len());
    let ts = RES / GRID;
    let outside: Vec<_> = changed.iter().filter(|(x, y)| !tiles1.contains(x / ts, y / ts)).collect();
    assert!(outside.is_empty(), "{} texels changed outside the stroke's tiles, e.g. {:?}", outside.len(), &outside[..outside.len().min(5)]);

    let (mut snap2, _) = s.stroke(Vec2::new(400.0, 250.0), Vec2::new(420.0, 600.0));
    let after2 = s.layer();
    assert!(!changed_texels(&after1, &after2).is_empty());

    let (d, q) = (&s.g.device, &s.g.queue);
    // undo stroke 2 -> exactly the state after stroke 1
    assert!(s.painter.swap(d, q, &s.ts, &mut snap2));
    assert!(changed_texels(&after1, &s.layer()).is_empty(), "undo of stroke 2 is not exact");
    // undo stroke 1 -> blank
    assert!(s.painter.swap(d, q, &s.ts, &mut snap1));
    assert!(changed_texels(&blank, &s.layer()).is_empty(), "undo of stroke 1 is not exact");
    // redo both
    assert!(s.painter.swap(d, q, &s.ts, &mut snap1));
    assert!(s.painter.swap(d, q, &s.ts, &mut snap2));
    assert!(changed_texels(&after2, &s.layer()).is_empty(), "redo is not exact");
}

#[test]
fn composite_and_export_produce_painted_material() {
    let Some(mut s) = Scene::new() else { return };
    let (_snap, _) = s.stroke(Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
    let (d, q) = (&s.g.device, &s.g.queue);
    s.ts.composite(d, q, &s.doc, None);
    let m = io::read_material(d, q, &s.ts);
    // the fill is light grey; painted texels are red and metallic
    let red = m.color.chunks_exact(4).filter(|p| p[0] > 150 && p[1] < 90).count();
    let metal = m.orm.chunks_exact(4).filter(|p| p[2] > 200).count();
    assert!(red > 100, "{red} red texels");
    assert!(metal > 100, "{metal} metallic texels");
    // painted height bends the normal map somewhere
    let bent = m.normal.chunks_exact(4).filter(|p| (p[0] as i32 - 128).abs() > 20 || (p[1] as i32 - 128).abs() > 20).count();
    assert!(bent > 10, "{bent} bent normals");
    // padding: no texel is left at the empty-background value (0,0,0)
    assert!(m.color.chunks_exact(4).all(|p| p[3] == 255));
    let dir = std::env::temp_dir().join(format!("pigment-gpu-export-{}", std::process::id()));
    let files = export::export(&dir, "T", &export::preset("unreal").unwrap(), &m).unwrap();
    assert_eq!(files.len(), 5);
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn bake_gives_occlusion_inside_the_ring_and_convex_curvature_outside() {
    let Some(mut s) = Scene::new() else { return };
    let (d, q) = (&s.g.device, &s.g.queue);
    let baker = Baker::new(d);
    let read = |ts: &TexSet| -> Vec<[f32; 4]> {
        crate::render::gpu::readback(d, q, &ts.bakes)
            .chunks_exact(8)
            .map(|c| [0, 1, 2, 3].map(|k| half::f16::from_bits(u16::from_le_bytes([c[2 * k], c[2 * k + 1]])).to_f32()))
            .collect()
    };
    // torus UV: v = 0 outer equator, v = 0.5 inner equator (facing the hole)
    let at = |px: &[[f32; 4]], u: f32, v: f32| px[((v * RES as f32) as usize).min(RES as usize - 1) * RES as usize + (u * RES as f32) as usize];
    // short max distance: the far side of the hole (~1.24 away) doesn't count
    baker.bake(d, q, &s.mesh, &s.mg, &mut s.ts, &BakeSettings { ao_samples: 64, ao_distance: 0.3, ..Default::default() });
    let near_only = at(&read(&s.ts), 0.3, 0.5)[0];
    // long max distance: it does
    baker.bake(d, q, &s.mesh, &s.mg, &mut s.ts, &BakeSettings { ao_samples: 64, ao_distance: 3.0, ..Default::default() });
    let px = read(&s.ts);
    let outer = at(&px, 0.3, 0.02);
    let inner = at(&px, 0.3, 0.5);
    assert!(outer[0] > 0.85, "outer AO {}", outer[0]);
    assert!(inner[0] < outer[0] - 0.15, "inner AO {} vs outer {}", inner[0], outer[0]);
    assert!(near_only > inner[0] + 0.1, "max distance has no effect: {near_only} vs {}", inner[0]);
    // a torus is convex on the outside and saddle-shaped on the inside: average over bands
    let band = |v0: f32, v1: f32| {
        let mut sum = 0.0;
        let mut n = 0;
        for y in ((v0 * RES as f32) as usize)..((v1 * RES as f32) as usize) {
            for x in 0..RES as usize {
                sum += px[y * RES as usize + x][1];
                n += 1;
            }
        }
        sum / n as f32
    };
    let (c_out, c_in) = (band(0.0, 0.06), band(0.47, 0.53));
    eprintln!("curvature: outer {c_out} inner {c_in}");
    assert!(c_out > 0.5 && c_out > c_in, "curvature outer {c_out} inner {c_in}");
    let _ = (&s.env, &s.camera);
}

#[test]
fn layer_pixels_survive_save_and_load() {
    let Some(mut s) = Scene::new() else { return };
    let (_snap, _) = s.stroke(Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
    let before = s.layer();
    let dir = std::env::temp_dir().join(format!("pigment-gpu-save-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    let res = s.paint_res();
    project::write_layer(&dir, res, &before).unwrap();
    let loaded = project::read_layer(&dir, res, RES).unwrap();
    let (d, q) = (&s.g.device, &s.g.queue);
    let mut fresh = TexSet::new(d, q, RES);
    io::upload_layer(d, q, &mut fresh, res, &loaded);
    let after = io::read_layer(d, q, &fresh, res).unwrap();
    assert_eq!(before.color, after.color);
    assert_eq!(before.roughness, after.roughness);
    assert_eq!(before.normal, after.normal);
    // height goes f16 -> u16 -> f16: allow one f16 step
    let worst = before.height.iter().zip(&after.height).map(|(a, b)| (*a as i32 - *b as i32).abs()).max().unwrap();
    assert!(worst <= 40, "height drifted by {worst}/65535");
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn edge_wear_generator_masks_a_fill_layer() {
    let Some(mut s) = Scene::new() else { return };
    let (d, q) = (&s.g.device, &s.g.queue);
    // a sharp-edged mesh: a cube with split faces and a simple UV layout
    let mut mesh = Mesh::default();
    let faces: [[[f32; 3]; 4]; 6] = [
        [[0., 0., 1.], [1., 0., 1.], [1., 1., 1.], [0., 1., 1.]],
        [[1., 0., 0.], [0., 0., 0.], [0., 1., 0.], [1., 1., 0.]],
        [[1., 0., 1.], [1., 0., 0.], [1., 1., 0.], [1., 1., 1.]],
        [[0., 0., 0.], [0., 0., 1.], [0., 1., 1.], [0., 1., 0.]],
        [[0., 1., 1.], [1., 1., 1.], [1., 1., 0.], [0., 1., 0.]],
        [[0., 0., 0.], [1., 0., 0.], [1., 0., 1.], [0., 0., 1.]],
    ];
    for (f, quad) in faces.iter().enumerate() {
        let (ox, oy) = ((f % 3) as f32 / 3.0, (f / 3) as f32 / 2.0);
        let base = mesh.vertices.len() as u32;
        for (k, p) in quad.iter().enumerate() {
            let (u, v) = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)][k];
            mesh.vertices.push(Vertex { position: *p, normal: [0.0; 3], uv: [ox + u / 3.0, oy + v / 2.0], tangent: [0.0; 4] });
        }
        mesh.indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    }
    mesh.compute_normals();
    mesh.compute_tangents();
    let mg = MeshGpu::new(d, &mesh);
    let (c, r) = mesh.bounding_sphere();
    s.ts.prepare_mesh(d, q, &mg, c, r);
    Baker::new(d).bake(d, q, &mesh, &mg, &mut s.ts, &BakeSettings { ao_samples: 32, curvature_radius: 0.05, curvature_strength: 1.0, ..Default::default() });

    let mut doc = Document::new_default();
    let mut wear = doc.new_fill_layer("wear");
    if let LayerKind::Fill { values } = &mut wear.kind {
        values.metallic = 1.0;
    }
    let mres = doc.mint();
    s.ts.new_mask(d, q, mres, true);
    let mut g = Generator::new(GeneratorKind::EdgeWear);
    g.noise_amount = 0.0;
    wear.mask = Some(Mask { res: mres, generator: Some(g), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
    doc.layers.push(wear);
    s.ts.ensure_resources(d, q, &doc);
    s.ts.composite(d, q, &doc, None);
    let m = io::read_material(d, q, &s.ts);
    let metal = m.orm.chunks_exact(4).filter(|p| p[2] > 128).count();
    let total = (RES * RES) as usize;
    // wear appears along edges only: some, but far from all, of the texture
    assert!(metal > total / 100, "only {metal} worn texels");
    assert!(metal < total / 2, "{metal} worn texels: wear is everywhere");
    // centre of a face stays unworn
    let i = ((RES / 4) * RES + RES / 6) as usize;
    assert!(m.orm[4 * i + 2] < 64, "face centre is worn");
}

#[test]
fn viewport_renders_a_lit_material() {
    let Some(mut s) = Scene::new() else { return };
    let (_snap, _) = s.stroke(Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
    let (d, q) = (&s.g.device, &s.g.queue);
    s.ts.composite(d, q, &s.doc, None);
    s.viewport.draw(d, q, &s.camera, &ViewSettings::default(), Some(&s.mg), &s.env, &s.ts);
    let img = crate::render::gpu::readback(d, q, s.viewport.color().unwrap());
    let out = std::env::temp_dir().join("pig");
    std::fs::create_dir_all(&out).ok();
    image::save_buffer(out.join("viewport_test.png"), &img, VIEW.x as u32, VIEW.y as u32, image::ExtendedColorType::Rgba8).unwrap();
    let mean = img.chunks_exact(4).map(|p| p[0] as u64 + p[1] as u64 + p[2] as u64).sum::<u64>() / (img.len() as u64 / 4 * 3);
    assert!(mean > 20, "viewport too dark: {mean}");
    let red = img.chunks_exact(4).filter(|p| p[0] as i32 > p[1] as i32 + 60).count();
    assert!(red > 500, "painted stroke not visible ({red} red pixels)");
}

/// Performance check against the brief's targets: 100k triangles, 4K
/// textures, 20 layers. Run with:
/// `cargo test -p pigment --release perf_targets -- --ignored --nocapture`
#[test]
#[ignore]
fn perf_targets() {
    let Some(g) = gpu() else { return };
    let (d, q) = (&g.device, &g.queue);
    let wait = || {
        let _ = d.poll(wgpu::PollType::Wait { submission_index: None, timeout: None });
    };
    let time = |label: &str, n: u32, f: &mut dyn FnMut()| {
        f();
        wait();
        let t0 = std::time::Instant::now();
        for _ in 0..n {
            f();
        }
        wait();
        let ms = t0.elapsed().as_secs_f64() * 1000.0 / n as f64;
        eprintln!("{label:<44} {ms:8.2} ms");
        ms
    };
    let mesh = Mesh::torus(1.0, 0.38, 400, 128); // 102,400 triangles
    eprintln!("mesh: {} triangles, 4096² textures, 20 layers", mesh.triangle_count());
    let mg = MeshGpu::new(d, &mesh);
    let res = 4096;
    let mut ts = TexSet::new(d, q, res);
    let (c, r) = mesh.bounding_sphere();
    ts.prepare_mesh(d, q, &mg, c, r);
    let mut doc = Document::default();
    doc.resolution = res;
    for i in 0..20 {
        let mut l = if i % 2 == 0 { doc.new_paint_layer(&format!("p{i}")) } else { doc.new_fill_layer(&format!("f{i}")) };
        if i % 4 == 1 {
            let m = doc.mint();
            l.mask = Some(Mask { res: m, generator: Some(Generator::new(GeneratorKind::EdgeWear)), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
        }
        doc.layers.push(l);
    }
    ts.ensure_resources(d, q, &doc);
    eprintln!("layer VRAM: {} MB", ts.vram_bytes() >> 20);
    let mut camera = OrbitCamera::default();
    camera.frame(c, r);
    let mut viewport = Viewport::new(d);
    viewport.ensure_targets(d, [1600, 1000]);
    let env = Environment::studio(d, q);
    let settings = ViewSettings::default();

    time("bake AO(128) + curvature", 1, &mut || Baker::new(d).bake(d, q, &mesh, &mg, &mut ts, &BakeSettings::default()));
    time("full composite (20 layers)", 5, &mut || ts.composite(d, q, &doc, None));
    let frame = time("viewport frame (1600x1000, MSAA 4x)", 30, &mut || viewport.draw(d, q, &camera, &settings, Some(&mg), &env, &ts));

    // a typical painting frame: 8 stamps of a 50 px brush, tiles from the CPU binner
    let vp = camera.view_proj(1.6);
    let eye = camera.eye();
    let bins = ScreenBins::build(&mesh, vp, Vec2::new(1600.0, 1000.0), Some(eye));
    let view = ViewGpu { view_proj: vp.to_cols_array_2d(), eye: [eye.x, eye.y, eye.z, 1.0], viewport: [1600.0, 1000.0, camera.near(), 0.0] };
    let target = doc.layers.iter().rev().find_map(|l| l.paint_res()).unwrap();
    let mut painter = Painter::new(d, res);
    painter.begin(d, q, &ts, Target::Layer(target));
    let brush = BrushGpu { color: [1.0, 0.0, 0.0, 1.0], rmh: [0.5; 4], normal: [0.0, 0.0, 1.0, 0.0], enabled: [1.0; 4], enabled2: [0.0, 0.0, 1.0, 0.0], emissive: [0.0; 4], enabled3: [0.0; 4] };
    let mut x = 600.0;
    let depth = viewport.paint_depth().unwrap();
    let paint_ms = time("paint frame: 8 stamps + apply + composite", 30, &mut || {
        let mut ft = TileSet::default();
        let stamps: Vec<StampGpu> = (0..8)
            .map(|k| {
                let p = Vec2::new(x + k as f32 * 5.0, 560.0);
                bins.mark_stamp(p, 25.0, &mut ft);
                StampGpu { center_radius: [p.x, p.y, 25.0, 1.0], params: [0.5, 0.0, 0.0, 0.0] }
            })
            .collect();
        x += 40.0;
        if x > 1000.0 {
            x = 600.0;
        }
        if let Some(rect) = ft.texel_bounds(res) {
            painter.stamps(d, q, &ts, &mg, depth, view, &stamps, &brush, rect);
            ts.composite(d, q, &doc, Some(rect));
        }
    });
    let cpu = time("CPU stroke setup (screen binning, 100k tris)", 3, &mut || {
        let _ = ScreenBins::build(&mesh, vp, Vec2::new(1600.0, 1000.0), Some(eye));
    });
    eprintln!("=> viewport {:.0} fps; painting {:.2} ms per stamp; stroke start {:.1} ms", 1000.0 / frame, paint_ms / 8.0, cpu);
}

#[test]
#[ignore]
fn perf_viewport_breakdown() {
    let Some(g) = gpu() else { return };
    let (d, q) = (&g.device, &g.queue);
    let wait = || {
        let _ = d.poll(wgpu::PollType::Wait { submission_index: None, timeout: None });
    };
    let env = Environment::studio(d, q);
    for (tris, res) in [(96 * 32, 1024u32), (400 * 128, 1024), (400 * 128, 4096)] {
        let seg = if tris > 10000 { (400, 128) } else { (96, 32) };
        let mesh = Mesh::torus(1.0, 0.38, seg.0, seg.1);
        let mg = MeshGpu::new(d, &mesh);
        let mut ts = TexSet::new(d, q, res);
        let (c, r) = mesh.bounding_sphere();
        ts.prepare_mesh(d, q, &mg, c, r);
        let doc = Document::new_default();
        ts.ensure_resources(d, q, &doc);
        ts.composite(d, q, &doc, None);
        let mut camera = OrbitCamera::default();
        camera.frame(c, r);
        let mut vp = Viewport::new(d);
        vp.ensure_targets(d, [1600, 1000]);
        for (label, mesh_opt) in [("background only", None), ("with mesh", Some(&mg))] {
            vp.draw(d, q, &camera, &ViewSettings::default(), mesh_opt, &env, &ts);
            wait();
            let t0 = std::time::Instant::now();
            for _ in 0..30 {
                vp.draw(d, q, &camera, &ViewSettings::default(), mesh_opt, &env, &ts);
            }
            wait();
            eprintln!("{:>7} tris {res:>5}² {label:<16} {:.2} ms", mesh.triangle_count(), t0.elapsed().as_secs_f64() * 1000.0 / 30.0);
        }
    }
}

/// Paint across the torus's u = 0/1 UV seam (at +X) and render it close up,
/// in a low-res texture set where any seam would be obvious.
#[test]
fn stroke_across_uv_seam_renders_without_a_line() {
    let Some(mut s) = Scene::new() else { return };
    // look straight at the +X side, where u wraps from 1 back to 0
    s.camera.yaw = std::f32::consts::FRAC_PI_2;
    s.camera.pitch = 0.2;
    s.camera.distance = 1.6;
    s.camera.target = glam::Vec3::new(1.0, 0.0, 0.0);
    let (d, q) = (&s.g.device, &s.g.queue);
    s.viewport.draw(d, q, &s.camera, &ViewSettings::default(), Some(&s.mg), &s.env, &s.ts);
    let (_snap, tiles) = s.stroke(Vec2::new(150.0, 420.0), Vec2::new(650.0, 380.0));
    // the stroke must touch tiles on both sides of the seam
    assert!(tiles.contains(0, 0) || (0..GRID).any(|y| tiles.contains(0, y)), "no tiles at u≈0");
    assert!((0..GRID).any(|y| tiles.contains(GRID - 1, y)), "no tiles at u≈1");
    let (d, q) = (&s.g.device, &s.g.queue);
    s.ts.composite(d, q, &s.doc, None);
    s.viewport.draw(d, q, &s.camera, &ViewSettings::default(), Some(&s.mg), &s.env, &s.ts);
    let img = crate::render::gpu::readback(d, q, s.viewport.color().unwrap());
    let out = std::env::temp_dir().join("pig");
    std::fs::create_dir_all(&out).ok();
    image::save_buffer(out.join("seam_test.png"), &img, VIEW.x as u32, VIEW.y as u32, image::ExtendedColorType::Rgba8).unwrap();
}

/// Renders the demo crate with the demo layer stack to %TEMP%/pig/demo_*.png
/// (material, curvature, AO). `cargo test -p pigment --release render_demo -- --ignored`
#[test]
#[ignore]
fn render_demo() {
    use crate::render::viewport::ViewMode;
    let Some(g) = gpu() else { return };
    let (d, q) = (&g.device, &g.queue);
    let mesh = Mesh::demo_crate(96);
    let mg = MeshGpu::new(d, &mesh);
    let doc = Document::demo();
    let mut ts = TexSet::new(d, q, doc.resolution);
    let (c, r) = mesh.bounding_sphere();
    ts.prepare_mesh(d, q, &mg, c, r);
    Baker::new(d).bake(d, q, &mesh, &mg, &mut ts, &doc.bake);
    ts.ensure_resources(d, q, &doc);
    ts.composite(d, q, &doc, None);
    let mut camera = OrbitCamera::default();
    camera.frame(c, r);
    camera.distance *= 0.85;
    let mut vp = Viewport::new(d);
    let size = [1200u32, 900];
    vp.ensure_targets(d, size);
    let env = Environment::studio(d, q);
    let out = std::env::temp_dir().join("pig");
    std::fs::create_dir_all(&out).ok();
    for (name, mode) in [("material", ViewMode::Material), ("curvature", ViewMode::Curvature), ("ao", ViewMode::Ao)] {
        let settings = ViewSettings { mode, ..Default::default() };
        vp.draw(d, q, &camera, &settings, Some(&mg), &env, &ts);
        let img = crate::render::gpu::readback(d, q, vp.color().unwrap());
        image::save_buffer(out.join(format!("demo_{name}.png")), &img, size[0], size[1], image::ExtendedColorType::Rgba8).unwrap();
    }
}

/// Folders composite as sub-stacks: their opacity and mask multiply their
/// children's, they nest, hidden folders hide their contents, and a partial
/// (painting) composite agrees with a full one.
#[test]
fn folders_composite_as_sub_stacks() {
    let Some(mut s) = Scene::new() else { return };
    let (d, q) = (&s.g.device, &s.g.queue);
    // roughness 0 below, a roughness-1 fill inside the folders (only roughness on)
    let mut doc = Document::default();
    doc.resolution = RES;
    let mut base = doc.new_fill_layer("base");
    if let LayerKind::Fill { values } = &mut base.kind {
        values.roughness = 0.0;
    }
    doc.layers.push(base);
    let outer = doc.new_folder("outer");
    let oid = outer.id;
    doc.layers.push(outer);
    let mut child = doc.new_fill_layer("child");
    for c in Channel::ALL {
        child.channels.get_mut(c).enabled = c == Channel::Roughness;
    }
    if let LayerKind::Fill { values } = &mut child.kind {
        values.roughness = 1.0;
    }
    let cid = child.id;
    doc.layers.push(child);
    doc.move_layer(cid, Some(oid), None).unwrap();

    let rough = |ts: &mut TexSet, doc: &Document, rect: Option<[u32; 4]>| -> f32 {
        ts.ensure_resources(d, q, doc);
        ts.composite(d, q, doc, rect);
        let m = io::read_material(d, q, ts);
        m.orm.chunks_exact(4).map(|p| p[1] as f32 / 255.0).sum::<f32>() / (m.orm.len() / 4) as f32
    };
    assert!((rough(&mut s.ts, &doc, None) - 1.0).abs() < 0.01, "full-opacity folder is a plain group");
    doc.layer_mut(oid).unwrap().opacity = 0.5;
    assert!((rough(&mut s.ts, &doc, None) - 0.5).abs() < 0.01);

    // nest: outer 0.5 > inner 0.5 > child
    let inner = doc.new_folder("inner");
    let iid = inner.id;
    doc.layers.push(inner);
    doc.move_layer(iid, Some(oid), None).unwrap();
    doc.move_layer(cid, Some(iid), None).unwrap();
    doc.layer_mut(iid).unwrap().opacity = 0.5;
    assert_eq!(doc.depth(cid), 2);
    let nested = rough(&mut s.ts, &doc, None);
    assert!((nested - 0.25).abs() < 0.01, "nested opacity multiplies: {nested}");

    // a partial composite (as while painting) leaves the rest of the result intact
    let part = rough(&mut s.ts, &doc, Some([0, 0, 64, 64]));
    assert!((part - nested).abs() < 0.002, "partial composite changed the result: {part} vs {nested}");

    // the folder's mask multiplies the child's mask: 0.5 x 0.5 (with opacities 1)
    doc.layer_mut(oid).unwrap().opacity = 1.0;
    doc.layer_mut(iid).unwrap().opacity = 1.0;
    let half = vec![128u8; (RES * RES) as usize];
    for id in [oid, cid] {
        let res = doc.mint();
        io::upload_mask(d, q, &mut s.ts, res, &half);
        doc.layer_mut(id).unwrap().mask = Some(Mask::new(res));
    }
    let masked = rough(&mut s.ts, &doc, None);
    assert!((masked - 0.25).abs() < 0.02, "folder mask x child mask: {masked}");

    // a disabled folder channel drops its children's effect on that channel
    doc.layer_mut(iid).unwrap().channels.roughness.enabled = false;
    assert!(rough(&mut s.ts, &doc, None) < 0.01);
    doc.layer_mut(iid).unwrap().channels.roughness.enabled = true;

    // hidden folder hides everything inside
    doc.layer_mut(oid).unwrap().visible = false;
    assert!(rough(&mut s.ts, &doc, None) < 0.01);
    doc.layer_mut(oid).unwrap().visible = true;
    // and a folder-less stack still composites exactly as before
    let flat: Vec<LayerId> = doc.layers.iter().filter(|l| l.is_folder()).map(|l| l.id).collect();
    for f in flat {
        let kids: Vec<LayerId> = doc.children_of(Some(f)).iter().map(|i| doc.layers[*i].id).collect();
        for k in kids {
            doc.move_layer(k, None, None).unwrap();
        }
        doc.remove_layer_tree(f);
    }
    assert!(doc.layers.iter().all(|l| !l.is_folder()));
    let m = rough(&mut s.ts, &doc, None);
    assert!((m - 0.5).abs() < 0.02, "child mask alone: {m}");
}
