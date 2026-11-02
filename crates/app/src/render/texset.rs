//! GPU side of a document: per-layer pixel textures, the layer compositor,
//! seam padding (jump flood), and the final material textures the viewport
//! samples and the exporter reads back.

use super::env::MipGen;
use super::gpu::{self, Tex};
use super::MeshGpu;
use eframe::egui_wgpu::wgpu;
use glam::{Vec2, Vec3};
use pigment_core::blend::{normal_from_tilt, srgb_to_linear};
use pigment_core::folders::{folder_blend, Step};
use pigment_core::{Channel, Document, ImageChannel, Layer, LayerKind, Projection, ResId};
use std::collections::{HashMap, HashSet};
use wgpu::util::DeviceExt;

/// Paint layer channel formats, indexed by `Channel`.
pub const LAYER_FORMATS: [wgpu::TextureFormat; 11] = [
    wgpu::TextureFormat::Rgba8UnormSrgb, // base colour + coverage
    wgpu::TextureFormat::Rg8Unorm,       // roughness + coverage
    wgpu::TextureFormat::Rg8Unorm,       // metallic + coverage
    wgpu::TextureFormat::Rg16Float,      // height (-1..1) + coverage
    wgpu::TextureFormat::Rgba8Unorm,     // encoded normal + coverage
    wgpu::TextureFormat::Rgba16Float,    // emission (linear HDR) + coverage
    wgpu::TextureFormat::Rg8Unorm,       // opacity + coverage
    wgpu::TextureFormat::Rg8Unorm,       // transmission + coverage
    wgpu::TextureFormat::Rg8Unorm,       // clearcoat + coverage
    wgpu::TextureFormat::Rg8Unorm,       // clearcoat roughness + coverage
    wgpu::TextureFormat::Rg8Unorm,       // metallic flake + coverage
];
/// Layer channels bound before the part-selection buffer (opacity,
/// transmission at 9, 10); the coat channels follow it (12, 13, 14).
pub const PRE_COAT_LAYER_CHANNELS: usize = 8;
/// Final clearcoat map: R = coat weight, G = coat roughness, B = flake.
pub const COAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
/// Layer channels written by the brush's main apply pass (the rest go
/// through a second pass: the main one is at the 32-byte attachment limit).
pub const MAIN_LAYER_CHANNELS: usize = 6;
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
/// Evaluated / filtered masks.
const FMASK: wgpu::TextureFormat = wgpu::TextureFormat::R16Float;
/// Anchors: height, mask, colour luminance.
pub const ANCHOR: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
const FILTER_UNIFORM_STRIDE: u64 = 256;

pub struct LayerTex {
    pub ch: [Tex; 11],
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
    /// image fill: channel bits (1 colour, 2 roughness, 4 height, 8 normal), projection (0 uv, 1 triplanar)
    img: [u32; 4],
    /// tiling u, v, offset u, v
    img_xf: [f32; 4],
    /// cos(rotation), sin(rotation), 1 / tile size (m), blend sharpness
    img_xf2: [f32; 4],
    /// linear tint rgb, height scale
    img_tint: [f32; 4],
    /// roughness range lo, hi, normal strength
    img_amt: [f32; 4],
    /// fill coat, coat roughness, flake
    coat_fill: [f32; 4],
    /// blend ids: coat, coat roughness, flake
    coat_blend: [u32; 4],
    /// layer x channel opacity: coat, coat roughness, flake
    coat_opacity: [f32; 4],
    /// ground generators: Generator::extra of the main generator, effect b, effect c
    gp3: [f32; 4],
    gb3: [f32; 4],
    gc3: [f32; 4],
    /// height blend mode (0 off, 1 above, 2 below), contrast, offset; w = height gain, > 0 when the height follows the generator profile
    ground: [f32; 4],
    /// per-instance jitter: value, hue, saturation, roughness
    jit: [f32; 4],
    /// x = 1: the mask binding holds the precomputed (filtered) mask;
    /// y = anchor input (0 bake, 1 height, 2 mask, 3 colour); z = relief
    /// radius (texels); w = relief strength. 496 of 512 bytes are now used:
    /// further per-layer data should go to a storage buffer (like part masks).
    ext: [f32; 4],
    /// ID mask: ID-map colour (sRGB 0..1) and tolerance (w < 0 = off). With
    /// this the struct is exactly 512 bytes (the uniform stride).
    idc: [f32; 4],
}

/// One filter pass (`filter.wgsl` FilterParams), 256-byte slots.
#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct FilterGpu {
    /// kind, channel bits, pass index, flags (1 gate texture, 2 mask mode, 4 last pass)
    kind: [u32; 4],
    a: [f32; 4],
    b: [f32; 4],
    c: [f32; 4],
    in_black: [f32; 4],
    in_white: [f32; 4],
    gamma: [f32; 4],
    out_black: [f32; 4],
    out_white: [f32; 4],
    shadows: [f32; 4],
    midtones: [f32; 4],
    highlights: [f32; 4],
}

fn filter_gpu(f: &pigment_core::filters::Filter, res: u32, pass: u32, mask: bool, gate: bool, gate_mul: f32) -> FilterGpu {
    let p = &f.params;
    let v3 = |x: [f32; 3]| [x[0], x[1], x[2], 0.0];
    FilterGpu {
        kind: [f.kind.gpu_id(), if mask { 1 } else { f.channel_bits() }, pass, (gate as u32) | if mask { 2 } else { 0 }],
        a: [p.radius.max(0.0) * res as f32 / 2048.0, p.amount, p.angle.to_radians(), p.scale],
        b: [p.seed as f32, p.hue / 360.0, p.saturation, p.lightness],
        c: [p.min, p.max, p.use_height as u32 as f32, gate_mul],
        in_black: p.levels.in_black,
        in_white: p.levels.in_white,
        gamma: p.levels.gamma,
        out_black: p.levels.out_black,
        out_white: p.levels.out_white,
        shadows: v3(p.shadows),
        midtones: v3(p.midtones),
        highlights: v3(p.highlights),
    }
}

fn layer_params(l: &Layer, variant_seed: u32) -> LayerParams {
    let vseed = |g: u32| pigment_core::variants::generator_seed(g, variant_seed);
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
    let (oo, bo) = ch(Channel::Opacity);
    let (ot, bt) = ch(Channel::Transmission);
    let (ocw, bcw) = ch(Channel::Coat);
    let (ocr, bcr) = ch(Channel::CoatRoughness);
    let (ofk, bfk) = ch(Channel::Flake);
    let mut p = LayerParams {
        flags: [0, 0, 0, 0],
        blend: [bc, br, bm, bh],
        blend2: [bn, be, bo, bt],
        opacity: [oc, or, om, oh],
        opacity2: [on, oe, oo, ot],
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
        img: [0; 4],
        img_xf: [0.0; 4],
        img_xf2: [0.0; 4],
        img_tint: [0.0; 4],
        img_amt: [0.0; 4],
        coat_fill: [0.0, 0.03, 0.0, 0.0],
        coat_blend: [bcw, bcr, bfk, 0],
        coat_opacity: [ocw, ocr, ofk, 0.0],
        gp3: [0.0; 4],
        gb3: [0.0; 4],
        gc3: [0.0; 4],
        ground: [0.0; 4],
        jit: [0.0; 4],
        ext: [0.0; 4],
        idc: [0.0, 0.0, 0.0, -1.0],
    };
    ground_params(l, &mut p);
    image_fill_params(l, &mut p);
    if let LayerKind::Fill { values } = &l.kind {
        p.flags[0] = 1;
        let c = values.base_color.map(srgb_to_linear);
        p.fill_color = [c[0], c[1], c[2], values.opacity.clamp(0.0, 1.0)];
        p.fill_rmh = [values.roughness, values.metallic, values.height, values.transmission.clamp(0.0, 1.0)];
        let n = normal_from_tilt(Vec2::from(values.normal));
        p.fill_normal = [n.x, n.y, n.z, 0.0];
        let e = values.emissive.map(srgb_to_linear);
        let k = values.emissive_strength.max(0.0);
        p.fill_emissive = [e[0] * k, e[1] * k, e[2] * k, 1.0];
        p.coat_fill = [values.coat.clamp(0.0, 1.0), values.coat_roughness.clamp(0.0, 1.0), values.flake.clamp(0.0, 1.0), 0.0];
    }
    if let Some(m) = l.mask.as_ref().filter(|m| m.enabled) {
        p.flags[1] = 1;
        p.flags[3] = m.invert as u32;
        if let Some(g) = &m.generator {
            p.flags[2] = g.gpu_id();
            p.gp = [g.amount, g.softness, g.noise_scale, g.noise_amount];
            p.gp2 = [vseed(g.seed) as f32, g.ao_influence, g.curvature_weight, g.variant as f32];
            p.gp3 = g.extra;
            for (k, e) in m.effects.iter().take(pigment_core::MAX_MASK_EFFECTS).enumerate() {
                let g = &e.generator;
                let a = [g.amount, g.softness, g.noise_scale, g.noise_amount];
                let b = [vseed(g.seed) as f32, g.ao_influence, g.curvature_weight, g.variant as f32];
                p.eff[2 * k] = g.gpu_id();
                p.eff[2 * k + 1] = e.op.gpu_id();
                if k == 0 {
                    (p.gb, p.gb2) = (a, b);
                    p.gb3 = g.extra;
                } else {
                    (p.gc, p.gc2) = (a, b);
                    p.gc3 = g.extra;
                }
            }
        }
        // same condition as variants::selected_parts returning Some
        if let Some(id) = &m.id_color {
            p.idc = [id.color[0], id.color[1], id.color[2], id.tolerance.max(0.0)];
        }
        if !m.parts.is_empty() || l.variant.part_subset.is_some() {
            // misc.y / misc.z (where the bitset lives) are filled in by `composite`
            p.misc[0] = 1;
        }
    }
    p
}

/// The ground options of a fill layer (`pigment_core::ground`): height
/// blend, height profile, per-instance jitter.
fn ground_params(l: &Layer, p: &mut LayerParams) {
    if !matches!(l.kind, LayerKind::Fill { .. }) {
        return;
    }
    if let Some(hb) = &l.height_blend {
        p.ground[0] = hb.mode.gpu_id();
        p.ground[1] = hb.contrast.max(0.0);
        p.ground[2] = hb.offset;
    }
    // w: |w| = height gain, sign = the height follows the generator profile
    let gain = l.height_gain.clamp(0.0, 8.0);
    p.ground[3] = if l.height_profile { gain } else { -gain };
    if let Some(j) = &l.jitter {
        p.jit = [j.value, j.hue, j.saturation, j.roughness];
    }
}

/// Params for a folder pass: the folder's mask and opacity, with blend modes
/// limited to the ones a pass-through sub-stack supports.
fn folder_params(l: &Layer, variant_seed: u32) -> LayerParams {
    let mut p = layer_params(l, variant_seed);
    let ids: Vec<u32> = Channel::ALL.iter().map(|c| folder_blend(*c, l.channels.get(*c).blend).gpu_id()).collect();
    p.blend = [ids[0], ids[1], ids[2], ids[3]];
    p.blend2 = [ids[4], ids[5], ids[6], ids[7]];
    p.coat_blend = [ids[8], ids[9], ids[10], 0];
    p
}

/// Image fill uniforms. Channel bits are set for every image the layer
/// names; `composite` clears the ones that aren't loaded.
fn image_fill_params(l: &Layer, p: &mut LayerParams) {
    let (LayerKind::Fill { .. }, Some(f)) = (&l.kind, &l.image) else { return };
    for (c, _) in f.images.iter() {
        p.img[0] |= image_bit(c);
    }
    p.img[1] = (f.projection == Projection::Triplanar) as u32;
    let (s, c) = f.rotation.to_radians().sin_cos();
    p.img_xf = [f.tiling[0], f.tiling[1], f.offset[0], f.offset[1]];
    p.img_xf2 = [c, s, 1.0 / f.tile_size.max(1e-4), f.blend_sharpness.max(0.01)];
    let t = f.tint.map(srgb_to_linear);
    p.img_tint = [t[0], t[1], t[2], f.height_scale];
    p.img_amt = [f.roughness_range[0], f.roughness_range[1], f.normal_strength, 0.0];
}

fn image_bit(c: ImageChannel) -> u32 {
    match c {
        ImageChannel::BaseColor => 1,
        ImageChannel::Roughness => 2,
        ImageChannel::Height => 4,
        ImageChannel::Normal => 8,
    }
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
    /// Accumulation sets: [0] is the final result, the rest a pool for
    /// ping-pong and for the stacks below open folders (grows on demand).
    acc: Vec<AccSet>,
    pub material: [Tex; 4],
    /// Final emission (linear HDR), mipmapped like the material.
    pub emissive: Tex,
    /// Final clearcoat (coat, coat roughness, flake), mipmapped.
    pub coat: Tex,
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
    /// Tiling images used by image fills.
    pub tiles: super::tile_images::TileImages,
    /// Flat tile projects: world wrap period along x / z in metres (0 = none).
    pub tile_period: [f32; 2],
    /// Evaluated + filtered masks of layers that need them (by layer id).
    pub mask_cache: HashMap<pigment_core::LayerId, Tex>,
    mask_scratch: Vec<Tex>,
    /// Anchor captures by lower-case anchor name.
    pub anchors: HashMap<String, Tex>,
    dummy_anchor: Tex,
    filter_buf: wgpu::Buffer,
    filter_buf_slots: u64,
    /// Colour ID map for ID masks (1 x 1 black until set).
    pub id_map: Tex,
}

struct Pipes {
    shared_bgl: wgpu::BindGroupLayout,
    acc_bgl: wgpu::BindGroupLayout,
    layer_bgl: wgpu::BindGroupLayout,
    /// A folder pass only needs the mask and params (bindings 6, 7 of the
    /// layer group), which keeps it within 16 sampled textures per stage.
    folder_bgl: wgpu::BindGroupLayout,
    jfa_bgl: wgpu::BindGroupLayout,
    clear: wgpu::RenderPipeline,
    layer: wgpu::RenderPipeline,
    folder: wgpu::RenderPipeline,
    finalize: wgpu::RenderPipeline,
    finalize_emissive: wgpu::RenderPipeline,
    finalize_coat: wgpu::RenderPipeline,
    uv: wgpu::RenderPipeline,
    jfa_init: wgpu::RenderPipeline,
    jfa_step: wgpu::RenderPipeline,
    filter_bgl: wgpu::BindGroupLayout,
    /// High-to-low AO / curvature into bakes.rg (write-masked).
    copy_rg: (wgpu::RenderPipeline, wgpu::BindGroupLayout),
    filter_acc: wgpu::RenderPipeline,
    filter_mask: wgpu::RenderPipeline,
    mask_eval: wgpu::RenderPipeline,
    anchor: wgpu::RenderPipeline,
}

impl Pipes {
    fn new(device: &wgpu::Device) -> Self {
        let common = include_str!("../shaders/common.wgsl");
        let comp = gpu::shader(device, "composite.wgsl", &[common, include_str!("../shaders/composite.wgsl"), include_str!("../shaders/gen_weather.wgsl"), include_str!("../shaders/gen_ground.wgsl")].concat());
        let ts = gpu::shader(device, "texspace.wgsl", &[common, include_str!("../shaders/texspace.wgsl")].concat());
        // binding 6: the colour ID map (ID masks)
        let shared_bgl = gpu::bgl(device, "shared", &[gpu::ntex(0), gpu::ntex(1), gpu::utex(2), gpu::uniform_entry(3, false), gpu::ntex(4), gpu::utex(5), gpu::ntex(6)]);
        let acc_bgl = gpu::bgl(device, "acc", &[gpu::ntex(0), gpu::ntex(1), gpu::ntex(2), gpu::ntex(3)]);
        let layer_bgl = gpu::bgl(
            device,
            "layer",
            // channel slots are filterable: fill layers bind image-fill textures there (sampled at binding 8)
            &[
                gpu::ftex(0),
                gpu::ftex(1),
                gpu::ftex(2),
                gpu::ftex(3),
                gpu::ftex(4),
                gpu::ftex(5),
                gpu::ntex(6),
                gpu::uniform_entry(7, true),
                gpu::sampler_entry(8, wgpu::SamplerBindingType::Filtering),
                // opacity, transmission
                gpu::ntex(9),
                gpu::ntex(10),
                // part-selection bitsets
                gpu::storage_entry(11),
                // clearcoat, coat roughness, flake
                gpu::ntex(12),
                gpu::ntex(13),
                gpu::ntex(14),
                // anchor read by the mask generator (filters.rs)
                gpu::ntex(15),
            ],
        );
        let full_layout = gpu::layout(device, "composite", &[&shared_bgl, &acc_bgl, &layer_bgl]);
        let folder_src = [common, include_str!("../shaders/composite.wgsl"), include_str!("../shaders/gen_weather.wgsl"), include_str!("../shaders/gen_ground.wgsl"), include_str!("../shaders/folder.wgsl")].concat();
        let folder_mod = gpu::shader(device, "folder.wgsl", &folder_src);
        // folder passes use the mask, params and (for part masks) the part bitsets
        let folder_bgl = gpu::bgl(device, "folder", &[gpu::ntex(6), gpu::uniform_entry(7, true), gpu::storage_entry(11), gpu::ntex(15)]);
        let folder_layout = gpu::layout(device, "folder", &[&shared_bgl, &acc_bgl, &folder_bgl, &acc_bgl]);
        let fin_layout = gpu::layout(device, "finalize", &[&shared_bgl, &acc_bgl]);
        // filters, mask evaluation and anchor capture (filter.wgsl)
        let filter_src = [common, include_str!("../shaders/composite.wgsl"), include_str!("../shaders/gen_weather.wgsl"), include_str!("../shaders/gen_ground.wgsl"), include_str!("../shaders/filter.wgsl")].concat();
        let filter_mod = gpu::shader(device, "filter.wgsl", &filter_src);
        let filter_bgl = gpu::bgl(device, "filter", &[gpu::uniform_entry(20, true), gpu::ntex(21)]);
        let filter_acc_layout = gpu::layout(device, "filter acc", &[&shared_bgl, &acc_bgl, &filter_bgl, &acc_bgl]);
        let filter_mask_layout = gpu::layout(device, "filter mask", &[&shared_bgl, &acc_bgl, &filter_bgl]);
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
            folder: gpu::fullscreen(device, "composite folder", &folder_mod, "fs_folder", &folder_layout, &acc_targets),
            finalize: gpu::fullscreen(device, "finalize", &comp, "fs_finalize", &fin_layout, &mat_targets),
            finalize_emissive: gpu::fullscreen(device, "finalize emissive", &comp, "fs_finalize_emissive", &fin_layout, &[gpu::target(EMISSIVE, None)]),
            finalize_coat: gpu::fullscreen(device, "finalize coat", &comp, "fs_finalize_coat", &fin_layout, &[gpu::target(COAT, None)]),
            filter_acc: gpu::fullscreen(device, "filter acc", &filter_mod, "fs_filter_acc", &filter_acc_layout, &acc_targets),
            filter_mask: gpu::fullscreen(device, "filter mask", &filter_mod, "fs_filter_mask", &filter_mask_layout, &[gpu::target(FMASK, None)]),
            mask_eval: gpu::fullscreen(device, "mask eval", &filter_mod, "fs_mask_eval", &full_layout, &[gpu::target(FMASK, None)]),
            anchor: gpu::fullscreen(device, "anchor capture", &filter_mod, "fs_anchor", &full_layout, &[gpu::target(ANCHOR, None)]),
            filter_bgl,
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
            copy_rg: {
                let m = gpu::shader(device, "copy_rg.wgsl", &[common, include_str!("../shaders/copy_rg.wgsl")].concat());
                let bgl = gpu::bgl(device, "copy rg", &[gpu::ntex(0)]);
                let layout = gpu::layout(device, "copy rg", &[&bgl]);
                let target = Some(wgpu::ColorTargetState { format: BAKES, blend: None, write_mask: wgpu::ColorWrites::RED | wgpu::ColorWrites::GREEN });
                (gpu::fullscreen(device, "copy rg", &m, "fs_copy_rg", &layout, &[target]), bgl)
            },
            jfa_init: gpu::fullscreen(device, "jfa init", &ts, "fs_jfa_init", &jfa_layout, &[gpu::target(NEAREST, None)]),
            jfa_step: gpu::fullscreen(device, "jfa step", &ts, "fs_jfa_step", &jfa_layout, &[gpu::target(NEAREST, None)]),
            shared_bgl,
            acc_bgl,
            layer_bgl,
            folder_bgl,
            jfa_bgl,
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn shared_bind_group(device: &wgpu::Device, p: &Pipes, bakes: &Tex, position: &Tex, nearest: &Tex, buf: &wgpu::Buffer, wnormal: &Tex, parts: &Tex, id_map: &Tex) -> wgpu::BindGroup {
    gpu::bind_group(
        device,
        "shared",
        &p.shared_bgl,
        &[
            wgpu::BindingResource::TextureView(&bakes.view),
            wgpu::BindingResource::TextureView(&position.view),
            wgpu::BindingResource::TextureView(&nearest.view),
            buf.as_entire_binding(),
            wgpu::BindingResource::TextureView(&wnormal.view),
            wgpu::BindingResource::TextureView(&parts.view),
            wgpu::BindingResource::TextureView(&id_map.view),
        ],
    )
}

fn filter_buffer(device: &wgpu::Device, slots: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("filter params"),
        size: FILTER_UNIFORM_STRIDE * slots,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
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
        let coat = Tex::new(device, "material coat", res, res, COAT, gpu::rw_usage(), mip);
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
        let id_map = Tex::new(device, "id map", 1, 1, wgpu::TextureFormat::Rgba8Unorm, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST, 1);
        let shared_bg = shared_bind_group(device, &p, &bakes, &position, &nearest, &shared_buf, &wnormal, &parts, &id_map);
        let acc = vec![acc_set(device, &p, res, "acc final"), acc_set(device, &p, res, "acc ping"), acc_set(device, &p, res, "acc pong")];
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
            coat,
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
            tiles: super::tile_images::TileImages::new(device),
            tile_period: [0.0; 2],
            mask_cache: HashMap::new(),
            mask_scratch: Vec::new(),
            anchors: HashMap::new(),
            dummy_anchor: Tex::target(device, "dummy anchor", 1, ANCHOR),
            filter_buf: filter_buffer(device, 16),
            filter_buf_slots: 16,
            id_map,
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

    /// Noise space and bounds of the whole object, for texture sets that
    /// paint part of it (generators stay continuous across sets).
    pub fn set_frame(&mut self, center: Vec3, radius: f32, lo: Vec3, hi: Vec3) {
        self.center_radius = [center.x, center.y, center.z, radius];
        self.bounds = [[lo.x, lo.y, lo.z, 0.0], [hi.x, hi.y, hi.z, 0.0]];
    }

    /// Set the colour ID map (RGBA8, `w` x `h`, row 0 = v 0); None clears it.
    pub fn set_id_map(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, img: Option<(&[u8], u32, u32)>) {
        self.id_map = match img {
            Some((data, w, h)) => {
                let t = Tex::new(device, "id map", w, h, wgpu::TextureFormat::Rgba8Unorm, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST, 1);
                gpu::upload(queue, &t, data);
                t
            }
            None => Tex::new(device, "id map", 1, 1, wgpu::TextureFormat::Rgba8Unorm, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST, 1),
        };
        self.shared_bg = shared_bind_group(device, &self.p, &self.bakes, &self.position, &self.nearest, &self.shared_buf, &self.wnormal, &self.parts, &self.id_map);
    }

    /// High-to-low AO (r) and curvature (g), `res` x `res` RG f32, into the
    /// mesh bakes (b / a keep the drip and rain bakes).
    pub fn apply_high_bakes(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, rg: &[[f32; 2]], res: u32) {
        let data: Vec<half::f16> = rg.iter().flat_map(|v| [half::f16::from_f32(v[0]), half::f16::from_f32(v[1]), half::f16::ZERO, half::f16::ONE]).collect();
        let t = Tex::new(device, "high bakes", res, res, wgpu::TextureFormat::Rgba16Float, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST, 1);
        gpu::upload(queue, &t, bytemuck::cast_slice(&data));
        let bg = gpu::bind_group(device, "copy rg", &self.p.copy_rg.1, &[wgpu::BindingResource::TextureView(&t.view)]);
        let mut enc = device.create_command_encoder(&Default::default());
        {
            let mut pass = gpu::pass(&mut enc, "high bakes", &[&self.bakes.view], None);
            pass.set_pipeline(&self.p.copy_rg.0);
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..3, 0..1);
        }
        queue.submit([enc.finish()]);
        self.baked = true;
    }

    /// Create pixel storage for any paint layers / masks the document has but
    /// the GPU doesn't (new layers start transparent, new masks with `fill`).
    pub fn ensure_resources(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, doc: &Document) {
        self.tiles.ensure(device, queue, doc);
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
            pass.draw_indexed(0..mesh.uv_index_count, 0, 0..1);
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
    ///
    /// Filters (`pigment_core::filters`) add passes: a layer whose mask has
    /// filters (or that has filters itself, or is a filter layer) gets its
    /// mask evaluated into `mask_cache` and filtered there; layer filters
    /// run on the accumulation after the layer pass; anchors are captured
    /// after their layer. Spatial filters read neighbours, so in a partial
    /// composite every pass is widened by the filters' reach (the regions
    /// shrink as filters consume it, and the final one still covers the
    /// rect plus everything the change can spread to).
    pub fn composite(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, doc: &Document, rect: Option<[u32; 4]>) {
        use pigment_core::filters::{Filter, FilterTarget};
        let res = self.res;
        let shared = [self.center_radius, [res as f32, res as f32 / 256.0, self.tile_period[0], self.tile_period[1]], self.bounds[0], self.bounds[1]];
        queue.write_buffer(&self.shared_buf, 0, bytemuck::cast_slice(&shared));

        // ---- what each step of the plan does
        struct StepInfo<'a> {
            l: &'a Layer,
            folder: bool,
            filter_layer: bool,
            /// mask evaluated (+ filtered) into mask_cache[l.id]
            cache: bool,
            mask_filters: Vec<&'a Filter>,
            acc_filters: Vec<&'a Filter>,
            anchor: Option<String>,
            /// (anchor key, GPU mode, relief radius texels, strength)
            input: Option<(String, f32, f32, f32)>,
            main_slot: usize,
            eval_slot: usize,
            anchor_slot: usize,
        }
        let plan = doc.composite_plan();
        let scale = res as f32 / 2048.0;
        let mut steps: Vec<Option<StepInfo>> = Vec::with_capacity(plan.len());
        let mut nslots = 0usize;
        for st in &plan {
            let (i, folder) = match *st {
                Step::Layer(i) => (i, false),
                Step::End(i) => (i, true),
                Step::Begin(_) => {
                    steps.push(None);
                    continue;
                }
            };
            let l = &doc.layers[i];
            let filter_layer = matches!(l.kind, LayerKind::Filter {});
            let acc_filters: Vec<&Filter> = l.filters.iter().filter(|f| f.enabled && f.kind.on_layer()).collect();
            if filter_layer && acc_filters.is_empty() {
                steps.push(None); // a filter layer with nothing on passes the stack through
                continue;
            }
            let mask = l.mask.as_ref().filter(|m| m.enabled && self.masks.contains_key(&m.res));
            let mask_filters: Vec<&Filter> = mask.map(|m| m.filters.iter().filter(|f| f.enabled && f.kind.on_mask()).collect()).unwrap_or_default();
            let cache = mask.is_some() && (!mask_filters.is_empty() || !acc_filters.is_empty());
            let input = mask
                .and_then(|m| m.generator.iter().chain(m.effects.iter().map(|e| &e.generator)).find_map(|g| g.input.as_ref()))
                .and_then(|inp| doc.anchor_layer(&inp.anchor).map(|_| (inp.anchor.to_ascii_lowercase(), inp.channel.gpu_mode() as f32, (inp.radius * scale).max(1.0), inp.strength)));
            let anchor = l.anchor.as_ref().map(|a| a.to_ascii_lowercase());
            let main_slot = nslots;
            nslots += 1;
            let eval_slot = if cache { nslots += 1; nslots - 1 } else { usize::MAX };
            let anchor_slot = if anchor.is_some() { nslots += 1; nslots - 1 } else { usize::MAX };
            steps.push(Some(StepInfo { l, folder, filter_layer, cache, mask_filters, acc_filters, anchor, input, main_slot, eval_slot, anchor_slot }));
        }

        // ---- textures the steps need: mask caches, scratch, anchors
        let live: HashSet<pigment_core::LayerId> = steps.iter().flatten().filter(|s| s.cache).map(|s| s.l.id).collect();
        self.mask_cache.retain(|id, _| live.contains(id));
        for id in &live {
            self.mask_cache.entry(*id).or_insert_with(|| Tex::target(device, "mask cache", res, FMASK));
        }
        if steps.iter().flatten().any(|s| !s.mask_filters.is_empty()) && self.mask_scratch.len() < 2 {
            self.mask_scratch = (0..2).map(|_| Tex::target(device, "mask scratch", res, FMASK)).collect();
        }
        let names: HashSet<String> = doc.layers.iter().filter_map(|l| l.anchor.as_ref().map(|a| a.to_ascii_lowercase())).collect();
        self.anchors.retain(|n, _| names.contains(n));
        {
            let mut enc = device.create_command_encoder(&Default::default());
            for n in &names {
                if !self.anchors.contains_key(n) {
                    let t = Tex::target(device, "anchor", res, ANCHOR);
                    drop(gpu::pass(&mut enc, "anchor clear", &[&t.view], Some(wgpu::Color { r: 0.0, g: 0.0, b: 0.0, a: 1.0 })));
                    self.anchors.insert(n.clone(), t);
                }
            }
            queue.submit([enc.finish()]);
        }

        // ---- layer params (main / mask eval / anchor capture slots)
        if nslots as u64 > self.layer_buf_slots {
            self.layer_buf_slots = (nslots as u64).next_power_of_two();
            self.layer_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("layer params"),
                size: LAYER_UNIFORM_STRIDE * self.layer_buf_slots,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
        }
        let mut params = vec![0u8; (LAYER_UNIFORM_STRIDE as usize) * nslots.max(1)];
        // word 0 stays zero so the buffer is never empty
        let mut part_words: Vec<u32> = vec![0];
        let mut put = |slot: usize, p: &LayerParams| {
            let o = slot * LAYER_UNIFORM_STRIDE as usize;
            params[o..o + std::mem::size_of::<LayerParams>()].copy_from_slice(bytemuck::bytes_of(p));
        };
        for s in steps.iter().flatten() {
            let l = s.l;
            let mut p = if s.folder { folder_params(l, doc.variants.seed) } else { layer_params(l, doc.variants.seed) };
            // image channels whose texture isn't loaded fall back to the flat value
            if let Some(f) = &l.image {
                for (c, path) in f.images.iter() {
                    if self.tiles.get(path, c).is_none() {
                        p.img[0] &= !image_bit(c);
                    }
                }
            }
            // part selection (with the variant's seeded subset) -> storage buffer
            if p.misc[0] != 0 {
                let bits = part_bitset(&pigment_core::variants::selected_parts(l, doc.variants.seed).unwrap_or_default());
                p.misc[1] = part_words.len() as u32;
                p.misc[2] = bits.len() as u32;
                part_words.extend_from_slice(&bits);
            }
            // a mask flagged in the doc but without pixels yet acts as "no mask"
            if l.mask.as_ref().is_some_and(|m| !self.masks.contains_key(&m.res)) {
                p.flags[1] = 0;
            }
            if let Some((_, mode, radius, strength)) = &s.input {
                p.ext[1] = *mode;
                p.ext[2] = *radius;
                p.ext[3] = *strength;
            }
            if s.cache {
                let mut e = p;
                e.ext[0] = 0.0;
                put(s.eval_slot, &e);
                p.ext[0] = 1.0;
            }
            if s.anchor.is_some() {
                let mut a = p;
                if s.folder || s.filter_layer {
                    a.flags[0] = 1; // full coverage
                }
                put(s.anchor_slot, &a);
            }
            put(s.main_slot, &p);
        }
        queue.write_buffer(&self.layer_buf, 0, &params);
        if part_words.len() as u64 > self.part_buf_words {
            self.part_buf_words = (part_words.len() as u64).next_power_of_two();
            self.part_buf = part_buffer(device, self.part_buf_words);
        }
        queue.write_buffer(&self.part_buf, 0, bytemuck::cast_slice(&part_words));

        // ---- filter params, in execution order
        let mut fparams: Vec<FilterGpu> = Vec::new();
        for s in steps.iter().flatten() {
            for f in &s.mask_filters {
                for k in 0..f.kind.passes() {
                    fparams.push(filter_gpu(f, res, k, true, false, 1.0));
                }
            }
            let gate_mul = if s.filter_layer { s.l.opacity } else { 1.0 };
            for f in &s.acc_filters {
                for k in 0..f.kind.passes() {
                    let mut g = filter_gpu(f, res, k, false, s.cache, gate_mul);
                    if k + 1 == f.kind.passes() {
                        g.kind[3] |= 4;
                    }
                    fparams.push(g);
                }
            }
        }
        if fparams.len() as u64 > self.filter_buf_slots {
            self.filter_buf_slots = (fparams.len() as u64).next_power_of_two();
            self.filter_buf = filter_buffer(device, self.filter_buf_slots);
        }
        if !fparams.is_empty() {
            let mut bytes = vec![0u8; FILTER_UNIFORM_STRIDE as usize * fparams.len()];
            for (k, f) in fparams.iter().enumerate() {
                let o = k * FILTER_UNIFORM_STRIDE as usize;
                bytes[o..o + std::mem::size_of::<FilterGpu>()].copy_from_slice(bytemuck::bytes_of(f));
            }
            queue.write_buffer(&self.filter_buf, 0, &bytes);
        }

        // ---- bind groups
        let params_res = || {
            wgpu::BindingResource::Buffer(wgpu::BufferBinding { buffer: &self.layer_buf, offset: 0, size: wgpu::BufferSize::new(std::mem::size_of::<LayerParams>() as u64) })
        };
        let raw_mask = |l: &Layer| l.mask.as_ref().and_then(|m| self.masks.get(&m.res)).unwrap_or(&self.dummy_mask);
        let input_tex = |s: &StepInfo| s.input.as_ref().and_then(|(n, ..)| self.anchors.get(n)).unwrap_or(&self.dummy_anchor);
        // a layer-type bind group (also for folders / filter layers: dummy channels)
        let layer_bg = |l: &Layer, mask: &Tex, anchor: &Tex| {
            let lt = l.paint_res().and_then(|r| self.layers.get(&r)).unwrap_or(&self.dummy_layer);
            let mut res: Vec<wgpu::BindingResource> = lt.ch[..MAIN_LAYER_CHANNELS].iter().map(|t| wgpu::BindingResource::TextureView(&t.view)).collect();
            // image fills: the tiling images take the channel slots
            if let (LayerKind::Fill { .. }, Some(f)) = (&l.kind, &l.image) {
                for (c, path) in f.images.iter() {
                    if let Some(t) = self.tiles.get(path, c) {
                        res[c.channel().index()] = wgpu::BindingResource::TextureView(&t.view);
                    }
                }
            }
            res.push(wgpu::BindingResource::TextureView(&mask.view));
            res.push(params_res());
            // image-fill sampler (binding 8), then opacity, transmission (bindings 9, 10)
            res.push(wgpu::BindingResource::Sampler(&self.tiles.sampler));
            res.extend(lt.ch[MAIN_LAYER_CHANNELS..PRE_COAT_LAYER_CHANNELS].iter().map(|t| wgpu::BindingResource::TextureView(&t.view)));
            // part-selection bitsets (binding 11)
            res.push(self.part_buf.as_entire_binding());
            // clearcoat, coat roughness, flake (bindings 12, 13, 14)
            res.extend(lt.ch[PRE_COAT_LAYER_CHANNELS..].iter().map(|t| wgpu::BindingResource::TextureView(&t.view)));
            // anchor input (binding 15)
            res.push(wgpu::BindingResource::TextureView(&anchor.view));
            gpu::bind_group(device, "layer", &self.p.layer_bgl, &res)
        };
        struct StepBgs {
            main: Option<wgpu::BindGroup>,
            eval: Option<wgpu::BindGroup>,
            anchor: Option<wgpu::BindGroup>,
            gate: Option<wgpu::BindGroup>,
        }
        let filter_bg = |gate: &Tex| {
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("filter"),
                layout: &self.p.filter_bgl,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 20,
                        resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding { buffer: &self.filter_buf, offset: 0, size: wgpu::BufferSize::new(std::mem::size_of::<FilterGpu>() as u64) }),
                    },
                    wgpu::BindGroupEntry { binding: 21, resource: wgpu::BindingResource::TextureView(&gate.view) },
                ],
            })
        };
        let bgs: Vec<Option<StepBgs>> = steps
            .iter()
            .map(|s| {
                let s = s.as_ref()?;
                let l = s.l;
                let mask = if s.cache { &self.mask_cache[&l.id] } else { raw_mask(l) };
                let anchor_in = input_tex(s);
                let main = if s.filter_layer {
                    None
                } else if s.folder {
                    Some(device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: Some("folder"),
                        layout: &self.p.folder_bgl,
                        entries: &[
                            wgpu::BindGroupEntry { binding: 6, resource: wgpu::BindingResource::TextureView(&mask.view) },
                            wgpu::BindGroupEntry { binding: 7, resource: params_res() },
                            wgpu::BindGroupEntry { binding: 11, resource: self.part_buf.as_entire_binding() },
                            wgpu::BindGroupEntry { binding: 15, resource: wgpu::BindingResource::TextureView(&anchor_in.view) },
                        ],
                    }))
                } else {
                    Some(layer_bg(l, mask, anchor_in))
                };
                let eval = s.cache.then(|| layer_bg(l, raw_mask(l), anchor_in));
                let anchor = s.anchor.as_ref().map(|_| layer_bg(l, mask, anchor_in));
                let gate = (!s.acc_filters.is_empty()).then(|| filter_bg(if s.cache { &self.mask_cache[&l.id] } else { &self.dummy_mask }));
                Some(StepBgs { main, eval, anchor, gate })
            })
            .collect();
        let mask_filter_bg = filter_bg(&self.dummy_mask);
        // mask sources as group-1 sets (binding 0 = the mask, the rest dummies)
        let mask_src_bg = |t: &Tex| {
            gpu::bind_group(
                device,
                "mask src",
                &self.p.acc_bgl,
                &[
                    wgpu::BindingResource::TextureView(&t.view),
                    wgpu::BindingResource::TextureView(&self.dummy_mask.view),
                    wgpu::BindingResource::TextureView(&self.dummy_mask.view),
                    wgpu::BindingResource::TextureView(&self.dummy_mask.view),
                ],
            )
        };
        let scratch_bgs: Vec<wgpu::BindGroup> = self.mask_scratch.iter().map(mask_src_bg).collect();

        // ---- regions (partial composites with filters widen every pass)
        let spread: u32 = steps
            .iter()
            .flatten()
            .map(|s| {
                let m: u32 = if s.cache { s.mask_filters.iter().map(|f| f.reach(res)).sum() } else { 0 };
                let a: u32 = s.acc_filters.iter().map(|f| f.reach(res)).sum();
                let i = s.input.as_ref().map(|(_, _, r, _)| r.ceil() as u32 * 2 + 1).unwrap_or(0);
                m + a + i
            })
            .sum();
        let acc_reach: u32 = steps.iter().flatten().map(|s| s.acc_filters.iter().map(|f| f.reach(res)).sum::<u32>()).sum();
        let expand = |r: Option<[u32; 4]>, m: u32| -> Option<[u32; 4]> {
            r.map(|[x, y, w, h]| {
                let x0 = x.saturating_sub(m);
                let y0 = y.saturating_sub(m);
                [x0, y0, (x + w + m).min(res) - x0, (y + h + m).min(res) - y0]
            })
        };
        let mut consumed = 0u32;
        let budget = spread + acc_reach;

        // ---- run
        let total_acc: usize = steps.iter().flatten().map(|s| if s.filter_layer { 0 } else { 1 } + s.acc_filters.iter().map(|f| f.kind.passes() as usize).sum::<usize>()).sum();
        let mut free: Vec<usize> = (1..self.acc.len()).rev().collect();
        let p = &self.p;
        let alloc = |acc: &mut Vec<AccSet>, free: &mut Vec<usize>| -> usize {
            free.pop().unwrap_or_else(|| {
                acc.push(acc_set(device, p, res, "acc pool"));
                acc.len() - 1
            })
        };
        let scissor = |pass: &mut wgpu::RenderPass, r: Option<[u32; 4]>| {
            if let Some([x, y, w, h]) = r {
                pass.set_scissor_rect(x, y, w, h);
            }
        };
        let mut enc = device.create_command_encoder(&Default::default());
        let mut done = 0usize;
        // defaults into a pool slot (or straight into final if there are no passes)
        let mut cur = if total_acc == 0 { 0 } else { alloc(&mut self.acc, &mut free) };
        {
            let mut pass = gpu::pass(&mut enc, "acc clear", &acc_views(&self.acc[cur]), None);
            scissor(&mut pass, expand(rect, budget));
            pass.set_pipeline(&p.clear);
            pass.draw(0..3, 0..1);
        }
        let mut below: Vec<usize> = Vec::new();
        let mut fslot = 0usize; // next filter param slot
        for (k, st) in plan.iter().enumerate() {
            if let Step::Begin(_) = st {
                below.push(cur);
                continue;
            }
            let (Some(s), Some(b)) = (&steps[k], &bgs[k]) else {
                // skipped (an empty filter layer); an End still needs its base popped
                continue;
            };
            let region = expand(rect, budget - consumed);
            // mask evaluation + mask filters -> mask_cache
            if s.cache {
                let target = &self.mask_cache[&s.l.id];
                let mf_reach: u32 = s.mask_filters.iter().map(|f| f.reach(res)).sum();
                let npass: u32 = s.mask_filters.iter().map(|f| f.kind.passes()).sum();
                {
                    let dst = if npass == 0 { target } else { &self.mask_scratch[0] };
                    let mut pass = gpu::pass(&mut enc, "mask eval", &[&dst.view], None);
                    scissor(&mut pass, expand(region, mf_reach));
                    pass.set_pipeline(&p.mask_eval);
                    pass.set_bind_group(0, &self.shared_bg, &[]);
                    pass.set_bind_group(1, &self.acc[cur].bg, &[]);
                    pass.set_bind_group(2, b.eval.as_ref().unwrap(), &[(s.eval_slot as u64 * LAYER_UNIFORM_STRIDE) as u32]);
                    pass.draw(0..3, 0..1);
                }
                let mut src = 0usize;
                let mut left = mf_reach;
                let mut n = 0u32;
                for f in &s.mask_filters {
                    let sub = f.reach(res) / f.kind.passes();
                    for _ in 0..f.kind.passes() {
                        n += 1;
                        left = left.saturating_sub(sub);
                        let dst = if n == npass { target } else { &self.mask_scratch[1 - src] };
                        let mut pass = gpu::pass(&mut enc, "mask filter", &[&dst.view], None);
                        scissor(&mut pass, expand(region, if n == npass { 0 } else { left }));
                        pass.set_pipeline(&p.filter_mask);
                        pass.set_bind_group(0, &self.shared_bg, &[]);
                        pass.set_bind_group(1, &scratch_bgs[src], &[]);
                        pass.set_bind_group(2, &mask_filter_bg, &[(fslot as u64 * FILTER_UNIFORM_STRIDE) as u32]);
                        pass.draw(0..3, 0..1);
                        fslot += 1;
                        src = 1 - src;
                    }
                }
            }
            let is_end = s.folder;
            let base = if is_end { below.pop() } else { None };
            // the layer / folder pass
            if let Some(main) = &b.main {
                done += 1;
                let dst = if done == total_acc { 0 } else { alloc(&mut self.acc, &mut free) };
                {
                    let mut pass = gpu::pass(&mut enc, if is_end { "composite folder" } else { "composite" }, &acc_views(&self.acc[dst]), None);
                    scissor(&mut pass, region);
                    pass.set_pipeline(if is_end { &p.folder } else { &p.layer });
                    pass.set_bind_group(0, &self.shared_bg, &[]);
                    pass.set_bind_group(1, &self.acc[cur].bg, &[]);
                    pass.set_bind_group(2, main, &[(s.main_slot as u64 * LAYER_UNIFORM_STRIDE) as u32]);
                    if let Some(bs) = base {
                        pass.set_bind_group(3, &self.acc[bs].bg, &[]);
                    }
                    pass.draw(0..3, 0..1);
                }
                for d in [Some(cur), base].into_iter().flatten() {
                    if d != 0 && !below.contains(&d) && !free.contains(&d) {
                        free.push(d);
                    }
                }
                cur = dst;
            } else if let Some(bs) = base {
                if bs != cur && bs != 0 && !below.contains(&bs) && !free.contains(&bs) {
                    free.push(bs);
                }
            }
            // layer filters / a filter layer's filters on the accumulation
            for f in &s.acc_filters {
                let x = cur;
                let mut src = x;
                let sub = f.reach(res) / f.kind.passes();
                for k2 in 0..f.kind.passes() {
                    consumed += sub;
                    done += 1;
                    let dst = if done == total_acc { 0 } else { alloc(&mut self.acc, &mut free) };
                    {
                        let mut pass = gpu::pass(&mut enc, "filter", &acc_views(&self.acc[dst]), None);
                        scissor(&mut pass, expand(rect, budget - consumed));
                        pass.set_pipeline(&p.filter_acc);
                        pass.set_bind_group(0, &self.shared_bg, &[]);
                        pass.set_bind_group(1, &self.acc[src].bg, &[]);
                        pass.set_bind_group(2, b.gate.as_ref().unwrap(), &[(fslot as u64 * FILTER_UNIFORM_STRIDE) as u32]);
                        pass.set_bind_group(3, &self.acc[x].bg, &[]);
                        pass.draw(0..3, 0..1);
                    }
                    fslot += 1;
                    // intermediate results of this filter are dropped as soon as they are read
                    if src != x && src != 0 && !free.contains(&src) {
                        free.push(src);
                    }
                    if k2 + 1 == f.kind.passes() && x != 0 && !below.contains(&x) && !free.contains(&x) {
                        free.push(x);
                    }
                    src = dst;
                }
                cur = src;
            }
            // anchor capture: the stack as it is right after this layer
            if let (Some(name), Some(abg)) = (&s.anchor, &b.anchor) {
                let t = &self.anchors[name];
                let mut pass = gpu::pass(&mut enc, "anchor", &[&t.view], None);
                scissor(&mut pass, expand(rect, budget - consumed));
                pass.set_pipeline(&p.anchor);
                pass.set_bind_group(0, &self.shared_bg, &[]);
                pass.set_bind_group(1, &self.acc[cur].bg, &[]);
                pass.set_bind_group(2, abg, &[(s.anchor_slot as u64 * LAYER_UNIFORM_STRIDE) as u32]);
                pass.draw(0..3, 0..1);
            }
        }
        let _ = FilterTarget::Layer;
        debug_assert_eq!(cur, 0);
        // finalize, with a margin for the height-to-normal neighbourhood
        let frect = expand(expand(rect, budget - consumed), 2);
        {
            let mip0: Vec<wgpu::TextureView> = self.material.iter().map(|t| t.mip_view(0)).collect();
            let mut pass = gpu::pass(&mut enc, "finalize", &[&mip0[0], &mip0[1], &mip0[2], &mip0[3]], None);
            scissor(&mut pass, frect);
            pass.set_pipeline(&self.p.finalize);
            pass.set_bind_group(0, &self.shared_bg, &[]);
            pass.set_bind_group(1, &self.acc[0].bg, &[]);
            pass.draw(0..3, 0..1);
        }
        {
            // separate pass: the main finalize is at the 32-byte-per-pixel attachment limit
            let e0 = self.emissive.mip_view(0);
            let mut pass = gpu::pass(&mut enc, "finalize emissive", &[&e0], None);
            scissor(&mut pass, frect);
            pass.set_pipeline(&self.p.finalize_emissive);
            pass.set_bind_group(0, &self.shared_bg, &[]);
            pass.set_bind_group(1, &self.acc[0].bg, &[]);
            pass.draw(0..3, 0..1);
        }
        {
            let c0 = self.coat.mip_view(0);
            let mut pass = gpu::pass(&mut enc, "finalize coat", &[&c0], None);
            scissor(&mut pass, frect);
            pass.set_pipeline(&self.p.finalize_coat);
            pass.set_bind_group(0, &self.shared_bg, &[]);
            pass.set_bind_group(1, &self.acc[0].bg, &[]);
            pass.draw(0..3, 0..1);
        }
        for t in self.material.iter().chain([&self.emissive, &self.coat]) {
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
