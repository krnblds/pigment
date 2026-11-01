//! Brush strokes on the GPU, plus tile snapshots for undo.
//!
//! Per stroke:
//! 1. `begin`: clear the stroke mask, copy the target's textures to a
//!    "before" scratch set.
//! 2. `stamps` (per frame): max-blend this frame's stamps into the stroke mask
//!    (see stamp.wgsl), then re-derive the target from before + mask inside
//!    the frame's dirty rectangle (apply.wgsl).
//! 3. `end`: copy the dirty tiles of the "before" set into a compact atlas:
//!    that atlas is the undo record. Undo/redo swap atlas and live tiles.

use super::gpu::{self, Tex};
use super::texset::{TexSet, LAYER_FORMATS, MASK_FORMAT};
use super::MeshGpu;
use eframe::egui_wgpu::wgpu;
use pigment_core::tiles::{TileSet, GRID};
use pigment_core::ResId;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Target {
    Layer(ResId),
    Mask(ResId),
}

impl Target {
    pub fn res(self) -> ResId {
        match self {
            Target::Layer(r) | Target::Mask(r) => r,
        }
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct StampGpu {
    pub center_radius: [f32; 4], // x, y, radius (px), opacity
    pub params: [f32; 4],        // hardness
}

#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct ViewGpu {
    pub view_proj: [[f32; 4]; 4],
    pub eye: [f32; 4],
    pub viewport: [f32; 4], // width, height, near, stamp count
}

#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct BrushGpu {
    pub color: [f32; 4],
    pub rmh: [f32; 4],
    pub normal: [f32; 4],
    pub enabled: [f32; 4],
    pub enabled2: [f32; 4], // normal, erase, mask value
    pub emissive: [f32; 4], // linear rgb x strength
    pub enabled3: [f32; 4], // emissive
}

/// Pixels of the dirty tiles of one target, packed into atlases.
pub struct Snapshot {
    pub target: Target,
    tiles: Vec<(u32, u32)>,
    atlas: Vec<Tex>,
    cols: u32,
}

impl Snapshot {
    pub fn bytes(&self) -> u64 {
        self.atlas.iter().map(|t| t.bytes()).sum()
    }
}

const MAX_STAMPS: usize = 256;

#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct DecalGpu {
    pub rect: [f32; 4],   // x0, y0, x1, y1 in viewport pixels
    pub params: [f32; 4], // opacity, mip level, alpha from luminance
}

/// Uniforms of `decal_box.wgsl` (a world-space decal, see pigment_core::decal).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, bytemuck::Pod, bytemuck::Zeroable)]
pub struct BoxDecalGpu {
    pub center: [f32; 4], // xyz, half depth
    pub right: [f32; 4],  // unit xyz, half width
    pub up: [f32; 4],     // unit xyz, half height
    pub normal: [f32; 4], // unit xyz, opacity
    pub params: [f32; 4], // alpha from luminance, min facing
    pub wear: [f32; 4],   // tear, fade, noise scale, seed
    pub wear2: [f32; 4],  // style (0 noise / 1 grunge), paper rim
}

pub struct Painter {
    res: u32,
    stamp_pipe: wgpu::RenderPipeline,
    stamp_bgl: wgpu::BindGroupLayout,
    apply_pipe: wgpu::RenderPipeline,
    apply_mask_pipe: wgpu::RenderPipeline,
    apply_bgl: wgpu::BindGroupLayout,
    view_buf: wgpu::Buffer,
    stamp_buf: wgpu::Buffer,
    brush_buf: wgpu::Buffer,
    stroke_mask: Tex,
    /// Per-texel colour written by a decal projection.
    decal_color: Tex,
    decal_pipe: wgpu::RenderPipeline,
    decal_bgl: wgpu::BindGroupLayout,
    decal_buf: wgpu::Buffer,
    decal_sampler: wgpu::Sampler,
    before: [Tex; 6],
    before_mask: Tex,
    active: Option<Target>,
    box_pipe: wgpu::RenderPipeline,
    box_bgl: wgpu::BindGroupLayout,
    box_buf: wgpu::Buffer,
}

impl Painter {
    pub fn new(device: &wgpu::Device, res: u32) -> Self {
        let common = include_str!("../shaders/common.wgsl");
        let sm = gpu::shader(device, "stamp.wgsl", &[common, include_str!("../shaders/stamp.wgsl")].concat());
        let am = gpu::shader(device, "apply.wgsl", &[common, include_str!("../shaders/apply.wgsl")].concat());
        let stamp_bgl = gpu::bgl(device, "stamp", &[gpu::uniform_entry(0, false), gpu::dtex(1), gpu::storage_entry(2)]);
        let apply_bgl = gpu::bgl(
            device,
            "apply",
            &[gpu::ntex(0), gpu::ntex(1), gpu::ntex(2), gpu::ntex(3), gpu::ntex(4), gpu::ntex(5), gpu::ntex(6), gpu::uniform_entry(7, false), gpu::ntex(8)],
        );
        let attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32x4];
        let mesh_layout = [Some(wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<pigment_core::Vertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &attrs,
        })];
        let stamp_layout = gpu::layout(device, "stamp", &[&stamp_bgl]);
        let stamp_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "stamp",
                module: &sm,
                vs: "vs_stamp",
                fs: Some("fs_stamp"),
                layout: &stamp_layout,
                buffers: &mesh_layout,
                targets: &[gpu::target(wgpu::TextureFormat::R16Float, Some(gpu::MAX_BLEND))],
                depth: None,
                samples: 1,
                cull: None,
            },
        );
        let decal_bgl = gpu::bgl(device, "decal", &[gpu::ftex(0), gpu::sampler_entry(1, wgpu::SamplerBindingType::Filtering), gpu::uniform_entry(2, false)]);
        let decal_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "decal",
                module: &sm,
                vs: "vs_stamp",
                fs: Some("fs_decal"),
                layout: &gpu::layout(device, "decal", &[&stamp_bgl, &decal_bgl]),
                buffers: &mesh_layout,
                targets: &[gpu::target(wgpu::TextureFormat::R16Float, Some(gpu::MAX_BLEND)), gpu::target(wgpu::TextureFormat::Rgba16Float, None)],
                depth: None,
                samples: 1,
                cull: None,
            },
        );
        let decal_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("decal"),
            size: std::mem::size_of::<DecalGpu>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let decal_sampler = gpu::linear_sampler(device, 8);
        let bm = gpu::shader(device, "decal_box.wgsl", &[common, include_str!("../shaders/decal_box.wgsl")].concat());
        let box_bgl = gpu::bgl(device, "box decal", &[gpu::ftex(0), gpu::sampler_entry(1, wgpu::SamplerBindingType::Filtering), gpu::uniform_entry(2, false)]);
        let box_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "box decal",
                module: &bm,
                vs: "vs_box",
                fs: Some("fs_box"),
                layout: &gpu::layout(device, "box decal", &[&box_bgl]),
                buffers: &mesh_layout,
                targets: &[gpu::target(wgpu::TextureFormat::R16Float, Some(gpu::MAX_BLEND)), gpu::target(wgpu::TextureFormat::Rgba16Float, None)],
                depth: None,
                samples: 1,
                cull: None,
            },
        );
        let box_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("box decal"),
            size: std::mem::size_of::<BoxDecalGpu>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let apply_layout = gpu::layout(device, "apply", &[&apply_bgl]);
        let layer_targets: Vec<_> = LAYER_FORMATS.iter().map(|f| gpu::target(*f, None)).collect();
        let apply_pipe = gpu::fullscreen(device, "apply", &am, "fs_apply", &apply_layout, &layer_targets);
        let apply_mask_pipe = gpu::fullscreen(device, "apply mask", &am, "fs_apply_mask", &apply_layout, &[gpu::target(MASK_FORMAT, None)]);
        let ubuf = |label, size| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(label),
                size,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            })
        };
        let view_buf = ubuf("paint view", std::mem::size_of::<ViewGpu>() as u64);
        let brush_buf = ubuf("brush", std::mem::size_of::<BrushGpu>() as u64);
        let stamp_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stamps"),
            size: (MAX_STAMPS * std::mem::size_of::<StampGpu>()) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let (stroke_mask, before, before_mask) = Self::scratch(device, res);
        let decal_color = Tex::target(device, "decal colour", res, wgpu::TextureFormat::Rgba16Float);
        Self {
            res,
            stamp_pipe,
            stamp_bgl,
            apply_pipe,
            apply_mask_pipe,
            apply_bgl,
            view_buf,
            stamp_buf,
            brush_buf,
            stroke_mask,
            decal_color,
            decal_pipe,
            decal_bgl,
            decal_buf,
            decal_sampler,
            before,
            before_mask,
            active: None,
            box_pipe,
            box_bgl,
            box_buf,
        }
    }

    fn scratch(device: &wgpu::Device, res: u32) -> (Tex, [Tex; 6], Tex) {
        (
            Tex::target(device, "stroke mask", res, wgpu::TextureFormat::R16Float),
            [0, 1, 2, 3, 4, 5].map(|i| Tex::target(device, "before", res, LAYER_FORMATS[i])),
            Tex::target(device, "before mask", res, MASK_FORMAT),
        )
    }

    pub fn resize(&mut self, device: &wgpu::Device, res: u32) {
        if res != self.res {
            self.res = res;
            (self.stroke_mask, self.before, self.before_mask) = Self::scratch(device, res);
            self.decal_color = Tex::target(device, "decal colour", res, wgpu::TextureFormat::Rgba16Float);
        }
    }

    fn target_textures<'a>(ts: &'a TexSet, target: Target) -> Option<Vec<&'a Tex>> {
        match target {
            Target::Layer(r) => ts.layers.get(&r).map(|l| l.ch.iter().collect()),
            Target::Mask(r) => ts.masks.get(&r).map(|m| vec![m]),
        }
    }

    pub fn begin(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet, target: Target) -> bool {
        let Some(live) = Self::target_textures(ts, target) else { return false };
        let mut enc = device.create_command_encoder(&Default::default());
        drop(gpu::pass(&mut enc, "stroke mask clear", &[&self.stroke_mask.view, &self.decal_color.view], Some(wgpu::Color::TRANSPARENT)));
        let scratch: Vec<&Tex> = match target {
            Target::Layer(_) => self.before.iter().collect(),
            Target::Mask(_) => vec![&self.before_mask],
        };
        for (l, s) in live.iter().zip(scratch) {
            gpu::copy_tex(&mut enc, &l.tex, [0, 0], &s.tex, [0, 0], [self.res, self.res]);
        }
        queue.submit([enc.finish()]);
        self.active = Some(target);
        true
    }

    /// Stamp a batch and re-apply the target inside `rect` (texels).
    #[allow(clippy::too_many_arguments)]
    pub fn stamps(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ts: &TexSet,
        mesh: &MeshGpu,
        depth: &wgpu::TextureView,
        view: ViewGpu,
        stamps: &[StampGpu],
        brush: &BrushGpu,
        rect: [u32; 4],
    ) {
        let Some(target) = self.active else { return };
        let Some(live) = Self::target_textures(ts, target) else { return };
        queue.write_buffer(&self.brush_buf, 0, bytemuck::bytes_of(brush));
        let stamp_bg = gpu::bind_group(
            device,
            "stamp",
            &self.stamp_bgl,
            &[self.view_buf.as_entire_binding(), wgpu::BindingResource::TextureView(depth), self.stamp_buf.as_entire_binding()],
        );
        for chunk in stamps.chunks(MAX_STAMPS) {
            let mut v = view;
            v.viewport[3] = chunk.len() as f32;
            queue.write_buffer(&self.view_buf, 0, bytemuck::bytes_of(&v));
            queue.write_buffer(&self.stamp_buf, 0, bytemuck::cast_slice(chunk));
            let mut enc = device.create_command_encoder(&Default::default());
            {
                let mut pass = gpu::pass(&mut enc, "stamp", &[&self.stroke_mask.view], None);
                pass.set_pipeline(&self.stamp_pipe);
                pass.set_bind_group(0, &stamp_bg, &[]);
                pass.set_vertex_buffer(0, mesh.vertices.slice(..));
                pass.set_index_buffer(mesh.indices.slice(..), wgpu::IndexFormat::Uint32);
                pass.draw_indexed(0..mesh.index_count, 0, 0..1);
            }
            queue.submit([enc.finish()]);
        }
        self.apply(device, queue, target, &live, rect);
    }

    /// Project an image onto the target from the camera (`view`), over the
    /// viewport rectangle in `decal.rect`, then re-apply inside `rect` (texels).
    /// `brush.enabled3[1]` must be 1 so the apply pass takes colour from the image.
    #[allow(clippy::too_many_arguments)]
    pub fn decal(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ts: &TexSet,
        mesh: &MeshGpu,
        depth: &wgpu::TextureView,
        view: ViewGpu,
        image: &Tex,
        decal: DecalGpu,
        brush: &BrushGpu,
        rect: [u32; 4],
    ) {
        let Some(target) = self.active else { return };
        let Some(live) = Self::target_textures(ts, target) else { return };
        queue.write_buffer(&self.brush_buf, 0, bytemuck::bytes_of(brush));
        queue.write_buffer(&self.view_buf, 0, bytemuck::bytes_of(&view));
        queue.write_buffer(&self.decal_buf, 0, bytemuck::bytes_of(&decal));
        let stamp_bg = gpu::bind_group(
            device,
            "stamp",
            &self.stamp_bgl,
            &[self.view_buf.as_entire_binding(), wgpu::BindingResource::TextureView(depth), self.stamp_buf.as_entire_binding()],
        );
        let decal_bg = gpu::bind_group(
            device,
            "decal",
            &self.decal_bgl,
            &[wgpu::BindingResource::TextureView(&image.view), wgpu::BindingResource::Sampler(&self.decal_sampler), self.decal_buf.as_entire_binding()],
        );
        let mut enc = device.create_command_encoder(&Default::default());
        {
            let mut pass = gpu::pass(&mut enc, "decal", &[&self.stroke_mask.view, &self.decal_color.view], None);
            pass.set_pipeline(&self.decal_pipe);
            pass.set_bind_group(0, &stamp_bg, &[]);
            pass.set_bind_group(1, &decal_bg, &[]);
            pass.set_vertex_buffer(0, mesh.vertices.slice(..));
            pass.set_index_buffer(mesh.indices.slice(..), wgpu::IndexFormat::Uint32);
            pass.draw_indexed(0..mesh.index_count, 0, 0..1);
        }
        queue.submit([enc.finish()]);
        self.apply(device, queue, target, &live, rect);
    }

    /// Project an image as a world-space box decal (no camera), then
    /// re-apply inside `rect` (texels). `brush.enabled3[1]` must be 1.
    #[allow(clippy::too_many_arguments)]
    pub fn box_decal(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet, mesh: &MeshGpu, image: &Tex, decal: &BoxDecalGpu, brush: &BrushGpu, rect: [u32; 4]) {
        let Some(target) = self.active else { return };
        let Some(live) = Self::target_textures(ts, target) else { return };
        queue.write_buffer(&self.brush_buf, 0, bytemuck::bytes_of(brush));
        queue.write_buffer(&self.box_buf, 0, bytemuck::bytes_of(decal));
        let bg = gpu::bind_group(
            device,
            "box decal",
            &self.box_bgl,
            &[wgpu::BindingResource::TextureView(&image.view), wgpu::BindingResource::Sampler(&self.decal_sampler), self.box_buf.as_entire_binding()],
        );
        let mut enc = device.create_command_encoder(&Default::default());
        {
            let mut pass = gpu::pass(&mut enc, "box decal", &[&self.stroke_mask.view, &self.decal_color.view], None);
            pass.set_pipeline(&self.box_pipe);
            pass.set_bind_group(0, &bg, &[]);
            pass.set_vertex_buffer(0, mesh.vertices.slice(..));
            pass.set_index_buffer(mesh.indices.slice(..), wgpu::IndexFormat::Uint32);
            pass.draw_indexed(0..mesh.index_count, 0, 0..1);
        }
        queue.submit([enc.finish()]);
        self.apply(device, queue, target, &live, rect);
    }

    fn apply(&self, device: &wgpu::Device, queue: &wgpu::Queue, target: Target, live: &[&Tex], rect: [u32; 4]) {
        let mut enc = device.create_command_encoder(&Default::default());
        let (pipe, before): (&wgpu::RenderPipeline, Vec<&Tex>) = match target {
            Target::Layer(_) => (&self.apply_pipe, self.before.iter().collect()),
            // mask apply reads the before-mask in slot 1; other slots are unused fillers
            Target::Mask(_) => (&self.apply_mask_pipe, vec![&self.before_mask, &self.before[1], &self.before[2], &self.before[3], &self.before[4], &self.before[5]]),
        };
        let mut res = vec![tv(&self.stroke_mask)];
        res.extend(before.iter().map(|t| tv(t)));
        res.push(self.brush_buf.as_entire_binding());
        res.push(tv(&self.decal_color));
        let bg = gpu::bind_group(device, "apply", &self.apply_bgl, &res);
        {
            let views: Vec<&wgpu::TextureView> = live.iter().map(|t| &t.view).collect();
            let mut pass = gpu::pass(&mut enc, "apply", &views, None);
            let [x, y, w, h] = rect;
            pass.set_scissor_rect(x, y, w.min(self.res - x), h.min(self.res - y));
            pass.set_pipeline(pipe);
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..3, 0..1);
        }
        queue.submit([enc.finish()]);
    }

    /// Finish the stroke: returns the undo snapshot of the touched tiles.
    pub fn end(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, tiles: &TileSet) -> Option<Snapshot> {
        let target = self.active.take()?;
        if tiles.is_empty() {
            return None;
        }
        let scratch: Vec<&Tex> = match target {
            Target::Layer(_) => self.before.iter().collect(),
            Target::Mask(_) => vec![&self.before_mask],
        };
        let tiles: Vec<(u32, u32)> = tiles.iter().collect();
        let (atlas, cols) = alloc_atlas(device, &scratch, tiles.len() as u32, self.res);
        let mut enc = device.create_command_encoder(&Default::default());
        copy_tiles(&mut enc, &scratch, &atlas, &tiles, cols, self.res, true);
        queue.submit([enc.finish()]);
        Some(Snapshot { target, tiles, atlas, cols })
    }

    /// Exchange the snapshot's pixels with the live texture: undo and redo
    /// are the same operation.
    pub fn swap(&self, device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet, snap: &mut Snapshot) -> bool {
        let Some(live) = Self::target_textures(ts, snap.target) else { return false };
        let (tmp, _) = alloc_atlas(device, &live, snap.tiles.len() as u32, self.res);
        let mut enc = device.create_command_encoder(&Default::default());
        copy_tiles(&mut enc, &live, &tmp, &snap.tiles, snap.cols, self.res, true);
        copy_tiles(&mut enc, &live, &snap.atlas, &snap.tiles, snap.cols, self.res, false);
        queue.submit([enc.finish()]);
        snap.atlas = tmp;
        true
    }
}

fn tv(t: &Tex) -> wgpu::BindingResource<'_> {
    wgpu::BindingResource::TextureView(&t.view)
}

fn alloc_atlas(device: &wgpu::Device, like: &[&Tex], n: u32, res: u32) -> (Vec<Tex>, u32) {
    let ts = res / GRID;
    let cols = (n as f32).sqrt().ceil().max(1.0) as u32;
    let rows = n.div_ceil(cols).max(1);
    let atlas = like
        .iter()
        .map(|t| {
            Tex::new(
                device,
                "undo tiles",
                cols * ts,
                rows * ts,
                t.format,
                wgpu::TextureUsages::COPY_SRC | wgpu::TextureUsages::COPY_DST | wgpu::TextureUsages::TEXTURE_BINDING,
                1,
            )
        })
        .collect();
    (atlas, cols)
}

/// Copy tiles between full textures and atlases. `to_atlas` picks the direction.
fn copy_tiles<T: std::borrow::Borrow<Tex>>(enc: &mut wgpu::CommandEncoder, full: &[&Tex], atlas: &[T], tiles: &[(u32, u32)], cols: u32, res: u32, to_atlas: bool) {
    let ts = res / GRID;
    for (f, a) in full.iter().zip(atlas) {
        let a = a.borrow();
        for (i, (tx, ty)) in tiles.iter().enumerate() {
            let i = i as u32;
            let full_xy = [tx * ts, ty * ts];
            let atlas_xy = [(i % cols) * ts, (i / cols) * ts];
            if to_atlas {
                gpu::copy_tex(enc, &f.tex, full_xy, &a.tex, atlas_xy, [ts, ts]);
            } else {
                gpu::copy_tex(enc, &a.tex, atlas_xy, &f.tex, full_xy, [ts, ts]);
            }
        }
    }
}
