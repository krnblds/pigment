//! GPU side of a document: per-layer pixel textures, the layer compositor,
//! seam padding (jump flood), and the final material textures the viewport
//! samples and the exporter reads back.

use super::env::MipGen;
use super::gpu::{self, Tex};
use super::MeshGpu;
use eframe::egui_wgpu::wgpu;
use glam::{Vec2, Vec3};
use pigment_core::blend::{normal_from_tilt, srgb_to_linear};
use pigment_core::{Channel, Document, Layer, LayerKind, ResId};
use std::collections::{HashMap, HashSet};
use wgpu::util::DeviceExt;

/// Paint layer channel formats, indexed by `Channel`.
pub const LAYER_FORMATS: [wgpu::TextureFormat; 6] = [
    wgpu::TextureFormat::Rgba8UnormSrgb, // base colour + coverage
    wgpu::TextureFormat::Rg8Unorm,       // roughness + coverage
    wgpu::TextureFormat::Rg8Unorm,       // metallic + coverage
    wgpu::TextureFormat::Rg16Float,      // height (-1..1) + coverage
    wgpu::TextureFormat::Rgba8Unorm,     // encoded normal + coverage
    wgpu::TextureFormat::Rgba16Float,    // emission (linear HDR) + coverage
];
pub const EMISSIVE: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
pub const MASK_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::R8Unorm;
const ACC: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
pub const MATERIAL_FORMATS: [wgpu::TextureFormat; 4] = [
    wgpu::TextureFormat::Rgba8UnormSrgb, // colour
    wgpu::TextureFormat::Rgba8Unorm,     // ao, roughness, metallic
    wgpu::TextureFormat::Rgba8Unorm,     // normal
    wgpu::TextureFormat::R16Float,       // height
];
const POSITION: wgpu::TextureFormat = wgpu::TextureFormat::Rgba32Float;
const WNORMAL: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
const NEAREST: wgpu::TextureFormat = wgpu::TextureFormat::Rg16Uint;
pub const BAKES: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
const LAYER_UNIFORM_STRIDE: u64 = 512;
const PARTS: wgpu::TextureFormat = wgpu::TextureFormat::R16Uint;

pub struct LayerTex {
    pub ch: [Tex; 6],
}

impl LayerTex {
    pub fn new(device: &wgpu::Device, res: u32) -> Self {
        Self { ch: Channel::ALL.map(|c| Tex::target(device, c.file_stem(), res, LAYER_FORMATS[c.index()])) }
    }
    pub fn bytes(&self) -> u64 {
        self.ch.iter().map(|t| t.bytes()).sum()
    }
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct LayerParams {
    flags: [u32; 4],
    blend: [u32; 4],
    blend2: [u32; 4],
    opacity: [f32; 4],
    opacity2: [f32; 4],
    fill_color: [f32; 4],
    fill_rmh: [f32; 4],
    fill_normal: [f32; 4],
    gp: [f32; 4],
    gp2: [f32; 4],
    fill_emissive: [f32; 4],
    /// extra mask effects: kind b, op b, kind c, op c
    eff: [u32; 4],
    gb: [f32; 4],
    gb2: [f32; 4],
    gc: [f32; 4],
    gc2: [f32; 4],
    /// x = part selection on, y = first word of this layer's bitset in the
    /// part-selection storage buffer, z = its length in words
    misc: [u32; 4],
}

fn layer_params(l: &Layer) -> LayerParams {
    let ch = |c: Channel| {
        let s = l.channels.get(c);
        (if s.enabled { s.opacity * l.opacity } else { 0.0 }, s.blend.gpu_id())
    };
    let (oc, bc) = ch(Channel::BaseColor);
    let (or, br) = ch(Channel::Roughness);
    let (om, bm) = ch(Channel::Metallic);
    let (oh, bh) = ch(Channel::Height);
    let (on, bn) = ch(Channel::Normal);
    let (oe, be) = ch(Channel::Emissive);
    let mut p = LayerParams {
        flags: [0, 0, 0, 0],
        blend: [bc, br, bm, bh],
        blend2: [bn, be, 0, 0],
        opacity: [oc, or, om, oh],
        opacity2: [on, oe, 0.0, 0.0],
        fill_color: [0.0; 4],
        fill_rmh: [0.0; 4],
        fill_normal: [0.0, 0.0, 1.0, 0.0],
        gp: [0.0; 4],
        gp2: [0.0; 4],
        fill_emissive: [0.0; 4],
        eff: [0; 4],
        gb: [0.0; 4],
        gb2: [0.0; 4],
        gc: [0.0; 4],
        gc2: [0.0; 4],
        misc: [0; 4],
    };
    if let LayerKind::Fill { values } = &l.kind {
        p.flags[0] = 1;
        let c = values.base_color.map(srgb_to_linear);
        p.fill_color = [c[0], c[1], c[2], 1.0];
        p.fill_rmh = [values.roughness, values.metallic, values.height, 0.0];
        let n = normal_from_tilt(Vec2::from(values.normal));
        p.fill_normal = [n.x, n.y, n.z, 0.0];
        let e = values.emissive.map(srgb_to_linear);
        let k = values.emissive_strength.max(0.0);
        p.fill_emissive = [e[0] * k, e[1] * k, e[2] * k, 1.0];
    }
    if let Some(m) = l.mask.as_ref().filter(|m| m.enabled) {
        p.flags[1] = 1;
        p.flags[3] = m.invert as u32;
        if let Some(g) = &m.generator {
            p.flags[2] = g.gpu_id();
            p.gp = [g.amount, g.softness, g.noise_scale, g.noise_amount];
            p.gp2 = [g.seed as f32, g.ao_influence, g.curvature_weight, 0.0];
            for (k, e) in m.effects.iter().take(pigment_core::MAX_MASK_EFFECTS).enumerate() {
                let g = &e.generator;
                let a = [g.amount, g.softness, g.noise_scale, g.noise_amount];
                let b = [g.seed as f32, g.ao_influence, g.curvature_weight, 0.0];
                p.eff[2 * k] = g.gpu_id();
                p.eff[2 * k + 1] = e.op.gpu_id();
                if k == 0 {
                    (p.gb, p.gb2) = (a, b);
                } else {
                    (p.gc, p.gc2) = (a, b);
                }
            }
        }
        if !m.parts.is_empty() {
            // misc.y / misc.z (where the bitset lives) are filled in by `composite`
            p.misc[0] = 1;
        }
    }
    p
}

/// Bitset of selected part ids (bit k of word k/32 = part k), just long
/// enough for the highest id. Ids at or above MAX_SELECTABLE_PARTS are
/// dropped (they can't be told apart in the R16 part-id map).
pub fn part_bitset(parts: &[u32]) -> Vec<u32> {
    let ids = || parts.iter().copied().filter(|&id| id < pigment_core::MAX_SELECTABLE_PARTS);
    let Some(top) = ids().max() else { return Vec::new() };
    let mut words = vec![0u32; (top / 32 + 1) as usize];
    for id in ids() {
        words[(id / 32) as usize] |= 1 << (id % 32);
    }
    words
}

struct AccSet {
    t: [Tex; 4],
    bg: wgpu::BindGroup,
}

pub struct TexSet {
    pub res: u32,
    pub layers: HashMap<ResId, LayerTex>,
    pub masks: HashMap<ResId, Tex>,
    /// Resources changed since the last save.
    pub unsaved: HashSet<ResId>,
    acc: [AccSet; 3], // ping, pong, final
    pub material: [Tex; 4],
    /// Final emission (linear HDR), mipmapped like the material.
    pub emissive: Tex,
    pub position: Tex,
    pub wnormal: Tex,
    pub nearest: Tex,
    /// Mesh part id + 1 per texel (0 = no surface).
    pub parts: Tex,
    bounds: [[f32; 4]; 2],
    pub bakes: Tex,
    pub baked: bool,
    dummy_layer: LayerTex,
    dummy_mask: Tex,
    shared_buf: wgpu::Buffer,
    shared_bg: wgpu::BindGroup,
    layer_buf: wgpu::Buffer,
    layer_buf_slots: u64,
    /// Part-selection bitsets of all visible layers (storage, u32 words).
    part_buf: wgpu::Buffer,
    part_buf_words: u64,
    p: Pipes,
    mipgen: MipGen,
    center_radius: [f32; 4],
}

struct Pipes {
    shared_bgl: wgpu::BindGroupLayout,
    acc_bgl: wgpu::BindGroupLayout,
    layer_bgl: wgpu::BindGroupLayout,
    jfa_bgl: wgpu::BindGroupLayout,
    clear: wgpu::RenderPipeline,
    layer: wgpu::RenderPipeline,
    finalize: wgpu::RenderPipeline,
    finalize_emissive: wgpu::RenderPipeline,
    uv: wgpu::RenderPipeline,
    jfa_init: wgpu::RenderPipeline,
    jfa_step: wgpu::RenderPipeline,
}

impl Pipes {
    fn new(device: &wgpu::Device) -> Self {
        let common = include_str!("../shaders/common.wgsl");
        let comp = gpu::shader(device, "composite.wgsl", &[common, include_str!("../shaders/composite.wgsl")].concat());
        let ts = gpu::shader(device, "texspace.wgsl", &[common, include_str!("../shaders/texspace.wgsl")].concat());
        let shared_bgl = gpu::bgl(device, "shared", &[gpu::ntex(0), gpu::ntex(1), gpu::utex(2), gpu::uniform_entry(3, false), gpu::ntex(4), gpu::utex(5)]);
        let acc_bgl = gpu::bgl(device, "acc", &[gpu::ntex(0), gpu::ntex(1), gpu::ntex(2), gpu::ntex(3)]);
        let layer_bgl = gpu::bgl(
            device,
            "layer",
            &[gpu::ntex(0), gpu::ntex(1), gpu::ntex(2), gpu::ntex(3), gpu::ntex(4), gpu::ntex(5), gpu::ntex(6), gpu::uniform_entry(7, true), gpu::storage_entry(8)],
        );
        let full_layout = gpu::layout(device, "composite", &[&shared_bgl, &acc_bgl, &layer_bgl]);
        let fin_layout = gpu::layout(device, "finalize", &[&shared_bgl, &acc_bgl]);
        let empty_layout = gpu::layout(device, "empty", &[]);
        let acc_targets = [gpu::target(ACC, None), gpu::target(ACC, None), gpu::target(ACC, None), gpu::target(ACC, None)];
        let mat_targets: Vec<_> = MATERIAL_FORMATS.iter().map(|f| gpu::target(*f, None)).collect();
        let jfa_bgl = gpu::bgl(device, "jfa", &[gpu::utex(0), gpu::ntex(1), gpu::uniform_entry(2, false)]);
        let jfa_layout = gpu::layout(device, "jfa", &[&jfa_bgl]);
        let attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32x4];
        let mesh_layout = [Some(wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<pigment_core::Vertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &attrs,
        })];
        Self {
            clear: gpu::fullscreen(device, "acc clear", &comp, "fs_clear", &empty_layout, &acc_targets),
            layer: gpu::fullscreen(device, "composite layer", &comp, "fs_layer", &full_layout, &acc_targets),
            finalize: gpu::fullscreen(device, "finalize", &comp, "fs_finalize", &fin_layout, &mat_targets),
            finalize_emissive: gpu::fullscreen(device, "finalize emissive", &comp, "fs_finalize_emissive", &fin_layout, &[gpu::target(EMISSIVE, None)]),
            uv: gpu::pipeline(
                device,
                gpu::PipeDesc {
                    label: "uv raster",
                    module: &ts,
                    vs: "vs_uv",
                    fs: Some("fs_uv"),
                    layout: &empty_layout,
                    buffers: &[
                        mesh_layout[0].clone(),
                        Some(wgpu::VertexBufferLayout { array_stride: 4, step_mode: wgpu::VertexStepMode::Vertex, attributes: &wgpu::vertex_attr_array![4 => Uint32] }),
                    ],
                    targets: &[gpu::target(POSITION, None), gpu::target(WNORMAL, None), gpu::target(PARTS, None)],
                    depth: None,
                    samples: 1,
                    cull: None,
                },
            ),
            jfa_init: gpu::fullscreen(device, "jfa init", &ts, "fs_jfa_init", &jfa_layout, &[gpu::target(NEAREST, None)]),
            jfa_step: gpu::fullscreen(device, "jfa step", &ts, "fs_jfa_step", &jfa_layout, &[gpu::target(NEAREST, None)]),
            shared_bgl,
            acc_bgl,
            layer_bgl,
            jfa_bgl,
        }
    }
}

fn part_buffer(device: &wgpu::Device, words: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("part selection bits"),
        size: words * 4,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

fn acc_views(s: &AccSet) -> [&wgpu::TextureView; 4] {
    [&s.t[0].view, &s.t[1].view, &s.t[2].view, &s.t[3].view]
}

fn acc_set(device: &wgpu::Device, p: &Pipes, res: u32, name: &str) -> AccSet {
    let t = [0, 1, 2, 3].map(|i| Tex::target(device, &format!("{name} {i}"), res, ACC));
    let bg = gpu::bind_group(
        device,
        name,
        &p.acc_bgl,
        &[
            wgpu::BindingResource::TextureView(&t[0].view),
            wgpu::BindingResource::TextureView(&t[1].view),
            wgpu::BindingResource::TextureView(&t[2].view),
            wgpu::BindingResource::TextureView(&t[3].view),
        ],
    );
    AccSet { t, bg }
}

impl TexSet {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue, res: u32) -> Self {
        let p = Pipes::new(device);
        let mip = gpu::mip_count(res);
        let material = [0, 1, 2, 3].map(|i| Tex::new(device, "material", res, res, MATERIAL_FORMATS[i], gpu::rw_usage(), mip));
        let emissive = Tex::new(device, "material emissive", res, res, EMISSIVE, gpu::rw_usage(), mip);
        let position = Tex::target(device, "position map", res, POSITION);
        let wnormal = Tex::target(device, "world normal map", res, WNORMAL);
        let nearest = Tex::target(device, "nearest map", res, NEAREST);
        let parts = Tex::target(device, "part ids", res, PARTS);
        let bakes = Tex::target(device, "bakes", res, BAKES);
        let shared_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("composite shared"),
            size: 64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let shared_bg = gpu::bind_group(
            device,
            "shared",
            &p.shared_bgl,
            &[
                wgpu::BindingResource::TextureView(&bakes.view),
                wgpu::BindingResource::TextureView(&position.view),
                wgpu::BindingResource::TextureView(&nearest.view),
                shared_buf.as_entire_binding(),
                wgpu::BindingResource::TextureView(&wnormal.view),
                wgpu::BindingResource::TextureView(&parts.view),
            ],
        );
        let acc = [acc_set(device, &p, res, "acc ping"), acc_set(device, &p, res, "acc pong"), acc_set(device, &p, res, "acc final")];
        let dummy_layer = LayerTex::new(device, 1);
        let dummy_mask = Tex::target(device, "dummy mask", 1, MASK_FORMAT);
        let layer_buf_slots = 64;
        let layer_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("layer params"),
            size: LAYER_UNIFORM_STRIDE * layer_buf_slots,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let part_buf_words = 256;
        let part_buf = part_buffer(device, part_buf_words);
        let s = Self {
            res,
            layers: HashMap::new(),
            masks: HashMap::new(),
            unsaved: HashSet::new(),
            acc,
            material,
            emissive,
            position,
            wnormal,
            nearest,
            parts,
            bounds: [[0.0; 4]; 2],
            bakes,
            baked: false,
            dummy_layer,
            dummy_mask,
            shared_buf,
            shared_bg,
            layer_buf,
            layer_buf_slots,
            part_buf,
            part_buf_words,
            p,
            mipgen: MipGen::new(device),
            center_radius: [0.0, 0.0, 0.0, 1.0],
        };
        // neutral bakes until the first real bake: AO 1, curvature 0.5
        let mut enc = device.create_command_encoder(&Default::default());
        drop(gpu::pass(&mut enc, "bakes clear", &[&s.bakes.view], Some(wgpu::Color { r: 1.0, g: 0.5, b: 0.0, a: 1.0 })));
        queue.submit([enc.finish()]);
        s
    }

    pub fn mip_gen(&self) -> &MipGen {
        &self.mipgen
    }

    /// Create pixel storage for any paint layers / masks the document has but
    /// the GPU doesn't (new layers start transparent, new masks with `fill`).
    pub fn ensure_resources(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, doc: &Document) {
        let mut enc = device.create_command_encoder(&Default::default());
        for l in &doc.layers {
            if let Some(r) = l.paint_res() {
                if !self.layers.contains_key(&r) {
                    let lt = LayerTex::new(device, self.res);
                    for t in &lt.ch {
                        drop(gpu::pass(&mut enc, "layer clear", &[&t.view], Some(wgpu::Color::TRANSPARENT)));
                    }
                    self.layers.insert(r, lt);
                    self.unsaved.insert(r);
                }
            }
            if let Some(m) = &l.mask {
                if !self.masks.contains_key(&m.res) {
                    let t = Tex::target(device, "mask", self.res, MASK_FORMAT);
                    drop(gpu::pass(&mut enc, "mask clear", &[&t.view], Some(wgpu::Color::WHITE)));
                    self.masks.insert(m.res, t);
                    self.unsaved.insert(m.res);
                }
            }
        }
        queue.submit([enc.finish()]);
    }

    /// Create a mask filled with white (1.0) or black (0.0).
    pub fn new_mask(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, res: ResId, white: bool) {
        let t = Tex::target(device, "mask", self.res, MASK_FORMAT);
        let mut enc = device.create_command_encoder(&Default::default());
        let c = if white { wgpu::Color::WHITE } else { wgpu::Color::BLACK };
        drop(gpu::pass(&mut enc, "mask clear", &[&t.view], Some(c)));
        queue.submit([enc.finish()]);
        self.masks.insert(res, t);
        self.unsaved.insert(res);
    }

    /// Copy a paint layer's pixels into a new resource id (layer duplicate).
    pub fn duplicate_layer(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, from: ResId, to: ResId) {
        let Some(src) = self.layers.get(&from) else { return };
        let dst = LayerTex::new(device, self.res);
        let mut enc = device.create_command_encoder(&Default::default());
        for (s, d) in src.ch.iter().zip(&dst.ch) {
            gpu::copy_tex(&mut enc, &s.tex, [0, 0], &d.tex, [0, 0], [self.res, self.res]);
        }
        queue.submit([enc.finish()]);
        self.layers.insert(to, dst);
        self.unsaved.insert(to);
    }

    pub fn duplicate_mask(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, from: ResId, to: ResId) {
        let Some(src) = self.masks.get(&from) else { return };
        let dst = Tex::target(device, "mask", self.res, MASK_FORMAT);
        let mut enc = device.create_command_encoder(&Default::default());
        gpu::copy_tex(&mut enc, &src.tex, [0, 0], &dst.tex, [0, 0], [self.res, self.res]);
        queue.submit([enc.finish()]);
        self.masks.insert(to, dst);
        self.unsaved.insert(to);
    }

    /// Free pixel storage nobody references any more.
    pub fn retain(&mut self, live: &HashSet<ResId>) {
        self.layers.retain(|r, _| live.contains(r));
        self.masks.retain(|r, _| live.contains(r));
    }

    pub fn vram_bytes(&self) -> u64 {
        self.layers.values().map(|l| l.bytes()).sum::<u64>() + self.masks.values().map(|m| m.bytes()).sum::<u64>()
    }

    /// Rasterise the mesh into texture space (position + normal per texel) and
    /// build the seam-padding map. Runs once per mesh / resolution.
    pub fn prepare_mesh(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, mesh: &MeshGpu, center: Vec3, radius: f32) {
        self.center_radius = [center.x, center.y, center.z, radius];
        let (lo, hi) = mesh.bounds;
        self.bounds = [[lo[0], lo[1], lo[2], 0.0], [hi[0], hi[1], hi[2], 0.0]];
        let mut enc = device.create_command_encoder(&Default::default());
        {
            let mut pass = gpu::pass(&mut enc, "uv raster", &[&self.position.view, &self.wnormal.view, &self.parts.view], Some(wgpu::Color::TRANSPARENT));
            pass.set_pipeline(&self.p.uv);
            pass.set_vertex_buffer(0, mesh.vertices.slice(..));
            pass.set_vertex_buffer(1, mesh.parts.slice(..));
            pass.set_index_buffer(mesh.indices.slice(..), wgpu::IndexFormat::Uint32);
            pass.draw_indexed(0..mesh.index_count, 0, 0..1);
        }
        // Jump flood: init, then steps res/2 .. 1, plus one extra step of 1 (JFA+1).
        let tmp = Tex::target(device, "jfa tmp", self.res, NEAREST);
        let mut steps = vec![];
        let mut k = self.res / 2;
        while k >= 1 {
            steps.push(k);
            k /= 2;
        }
        steps.push(1);
        let bufs: Vec<wgpu::Buffer> = std::iter::once(0)
            .chain(steps.iter().copied())
            .map(|s| {
                device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("jfa params"),
                    contents: bytemuck::cast_slice(&[s as i32, self.res as i32, 0, 0]),
                    usage: wgpu::BufferUsages::UNIFORM,
                })
            })
            .collect();
        // ping-pong so the last write lands in self.nearest
        let n = steps.len() + 1;
        let mut targets: Vec<(&Tex, &Tex)> = Vec::new(); // (src, dst)
        for i in 0..n {
            let dst_is_final = (n - 1 - i) % 2 == 0;
            let (src, dst) = if dst_is_final { (&tmp, &self.nearest) } else { (&self.nearest, &tmp) };
            targets.push((src, dst));
        }
        for (i, (src, dst)) in targets.iter().enumerate() {
            let bg = gpu::bind_group(
                device,
                "jfa",
                &self.p.jfa_bgl,
                &[
                    wgpu::BindingResource::TextureView(&src.view),
                    wgpu::BindingResource::TextureView(&self.position.view),
                    bufs[i].as_entire_binding(),
                ],
            );
            let mut pass = gpu::pass(&mut enc, "jfa", &[&dst.view], None);
            pass.set_pipeline(if i == 0 { &self.p.jfa_init } else { &self.p.jfa_step });
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..3, 0..1);
        }
        queue.submit([enc.finish()]);
    }

    /// Composite the visible layers and refresh the material textures.
    /// `rect` (texels) limits the work to a region, used while painting.
    pub fn composite(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, doc: &Document, rect: Option<[u32; 4]>) {
        let res = self.res;
        let shared = [self.center_radius, [res as f32, res as f32 / 256.0, 0.0, 0.0], self.bounds[0], self.bounds[1]];
        queue.write_buffer(&self.shared_buf, 0, bytemuck::cast_slice(&shared));

        let visible: Vec<&Layer> = doc.layers.iter().filter(|l| l.visible).collect();
        if visible.len() as u64 > self.layer_buf_slots {
            self.layer_buf_slots = (visible.len() as u64).next_power_of_two();
            self.layer_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("layer params"),
                size: LAYER_UNIFORM_STRIDE * self.layer_buf_slots,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
        }
        let mut params = vec![0u8; (LAYER_UNIFORM_STRIDE as usize) * visible.len().max(1)];
        // word 0 stays zero so the buffer is never empty
        let mut part_words: Vec<u32> = vec![0];
        for (i, l) in visible.iter().enumerate() {
            let mut p = layer_params(l);
            // a mask flagged in the doc but without pixels yet acts as "no mask"
            if l.mask.as_ref().is_some_and(|m| !self.masks.contains_key(&m.res)) {
                p.flags[1] = 0;
            }
            if p.misc[0] != 0 {
                let bits = part_bitset(&l.mask.as_ref().map(|m| m.parts.as_slice()).unwrap_or(&[]));
                p.misc[1] = part_words.len() as u32;
                p.misc[2] = bits.len() as u32;
                part_words.extend_from_slice(&bits);
            }
            let o = i * LAYER_UNIFORM_STRIDE as usize;
            params[o..o + std::mem::size_of::<LayerParams>()].copy_from_slice(bytemuck::bytes_of(&p));
        }
        queue.write_buffer(&self.layer_buf, 0, &params);
        if part_words.len() as u64 > self.part_buf_words {
            self.part_buf_words = (part_words.len() as u64).next_power_of_two();
            self.part_buf = part_buffer(device, self.part_buf_words);
        }
        queue.write_buffer(&self.part_buf, 0, bytemuck::cast_slice(&part_words));

        let layer_bgs: Vec<wgpu::BindGroup> = visible
            .iter()
            .map(|l| {
                let lt = l.paint_res().and_then(|r| self.layers.get(&r)).unwrap_or(&self.dummy_layer);
                let mask = l.mask.as_ref().and_then(|m| self.masks.get(&m.res)).unwrap_or(&self.dummy_mask);
                let mut res: Vec<wgpu::BindingResource> = lt.ch.iter().map(|t| wgpu::BindingResource::TextureView(&t.view)).collect();
                res.push(wgpu::BindingResource::TextureView(&mask.view));
                res.push(wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                    buffer: &self.layer_buf,
                    offset: 0,
                    size: wgpu::BufferSize::new(std::mem::size_of::<LayerParams>() as u64),
                }));
                res.push(self.part_buf.as_entire_binding());
                gpu::bind_group(device, "layer", &self.p.layer_bgl, &res)
            })
            .collect();

        let scissor = |pass: &mut wgpu::RenderPass, r: Option<[u32; 4]>| {
            if let Some([x, y, w, h]) = r {
                pass.set_scissor_rect(x, y, w, h);
            }
        };
        let mut enc = device.create_command_encoder(&Default::default());
        // defaults into ping (or straight into final if there are no layers)
        let first = if visible.is_empty() { 2 } else { 0 };
        {
            let mut pass = gpu::pass(&mut enc, "acc clear", &acc_views(&self.acc[first]), None);
            scissor(&mut pass, rect);
            pass.set_pipeline(&self.p.clear);
            pass.draw(0..3, 0..1);
        }
        let mut src = 0usize;
        for (i, bg) in layer_bgs.iter().enumerate() {
            let dst = if i + 1 == visible.len() { 2 } else { 1 - src };
            let mut pass = gpu::pass(&mut enc, "composite", &acc_views(&self.acc[dst]), None);
            scissor(&mut pass, rect);
            pass.set_pipeline(&self.p.layer);
            pass.set_bind_group(0, &self.shared_bg, &[]);
            pass.set_bind_group(1, &self.acc[src].bg, &[]);
            pass.set_bind_group(2, bg, &[(i as u64 * LAYER_UNIFORM_STRIDE) as u32]);
            pass.draw(0..3, 0..1);
            src = dst;
        }
        // finalize, with a margin for the height-to-normal neighbourhood
        let frect = rect.map(|[x, y, w, h]| {
            let x0 = x.saturating_sub(2);
            let y0 = y.saturating_sub(2);
            [x0, y0, (x + w + 2).min(res) - x0, (y + h + 2).min(res) - y0]
        });
        {
            let mip0: Vec<wgpu::TextureView> = self.material.iter().map(|t| t.mip_view(0)).collect();
            let mut pass = gpu::pass(&mut enc, "finalize", &[&mip0[0], &mip0[1], &mip0[2], &mip0[3]], None);
            scissor(&mut pass, frect);
            pass.set_pipeline(&self.p.finalize);
            pass.set_bind_group(0, &self.shared_bg, &[]);
            pass.set_bind_group(1, &self.acc[2].bg, &[]);
            pass.draw(0..3, 0..1);
        }
        {
            // separate pass: the main finalize is at the 32-byte-per-pixel attachment limit
            let e0 = self.emissive.mip_view(0);
            let mut pass = gpu::pass(&mut enc, "finalize emissive", &[&e0], None);
            scissor(&mut pass, frect);
            pass.set_pipeline(&self.p.finalize_emissive);
            pass.set_bind_group(0, &self.shared_bg, &[]);
            pass.set_bind_group(1, &self.acc[2].bg, &[]);
            pass.draw(0..3, 0..1);
        }
        for t in self.material.iter().chain(std::iter::once(&self.emissive)) {
            self.mipgen.generate(device, &mut enc, t, frect);
        }
        queue.submit([enc.finish()]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn part_bitset_covers_ids_far_past_the_old_256_limit() {
        assert!(part_bitset(&[]).is_empty());
        let b = part_bitset(&[0, 31, 32, 300, 4095]);
        assert_eq!(b.len(), 4095 / 32 + 1);
        assert_eq!(b[0], 1 | 1 << 31);
        assert_eq!(b[1], 1);
        assert_eq!(b[300 / 32], 1 << (300 % 32));
        assert_eq!(b[127], 1 << 31);
        assert_eq!(b.iter().map(|w| w.count_ones()).sum::<u32>(), 5);
        // ids the R16 part map can't tell apart are dropped
        assert!(part_bitset(&[pigment_core::MAX_SELECTABLE_PARTS]).is_empty());
    }
}
