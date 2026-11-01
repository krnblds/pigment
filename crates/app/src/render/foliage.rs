//! Foliage cards in the viewport: one instanced draw per atlas, alpha-tested
//! (see `foliage.wgsl`). The app fills the batches from the visible foliage
//! layers (`app/foliage.rs`); the viewport draws them after the opaque mesh.

use super::gpu::{self, Tex};
use eframe::egui_wgpu::wgpu;
use std::collections::HashMap;
use wgpu::util::DeviceExt;

/// One quad as the GPU sees it (cross cards are several of these).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, bytemuck::Pod, bytemuck::Zeroable)]
pub struct GpuCard {
    pub p: [f32; 3],
    pub x: [f32; 3],
    pub y: [f32; 3],
    pub uv: [f32; 4],
    /// mount, wind, phase, highlight
    pub misc: [f32; 4],
}

struct AtlasGpu {
    bg: wgpu::BindGroup,
    #[allow(dead_code)]
    color: Tex,
    #[allow(dead_code)]
    trans: Tex,
}

struct Batch {
    atlas: String,
    buf: wgpu::Buffer,
    count: u32,
}

pub struct FoliageGpu {
    pipe: wgpu::RenderPipeline,
    bgl: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    params: wgpu::Buffer,
    atlases: HashMap<String, AtlasGpu>,
    batches: Vec<Batch>,
    /// Seconds, for the wind sway.
    pub time: f32,
    /// Global wind multiplier (0 = still, e.g. for renders).
    pub wind: f32,
}

/// Box-filtered mip chain of an RGBA8 image (alpha-weighted colour so
/// transparent texels don't darken the edges).
fn mips(rgba: &[u8], size: u32) -> Vec<Vec<u8>> {
    let mut out = vec![rgba.to_vec()];
    let mut s = size;
    while s > 1 {
        let prev = out.last().unwrap();
        let n = s / 2;
        let mut next = vec![0u8; (n * n * 4) as usize];
        for y in 0..n {
            for x in 0..n {
                let mut acc = [0f32; 4];
                let mut wsum = 0.0;
                for (dx, dy) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
                    let k = (((y * 2 + dy) * s + x * 2 + dx) * 4) as usize;
                    let a = prev[k + 3] as f32;
                    let w = a + 1.0;
                    for c in 0..3 {
                        acc[c] += prev[k + c] as f32 * w;
                    }
                    acc[3] += a;
                    wsum += w;
                }
                let k = ((y * n + x) * 4) as usize;
                for c in 0..3 {
                    next[k + c] = (acc[c] / wsum).round() as u8;
                }
                // keep coverage from collapsing in small mips of thin needles
                next[k + 3] = ((acc[3] / 4.0) * 1.15).min(255.0) as u8;
            }
        }
        out.push(next);
        s = n;
    }
    out
}

fn mip_tex(device: &wgpu::Device, queue: &wgpu::Queue, label: &str, rgba: &[u8], size: u32) -> Tex {
    let chain = mips(rgba, size);
    let t = Tex::new(device, label, size, size, wgpu::TextureFormat::Rgba8UnormSrgb, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST, chain.len() as u32);
    for (level, data) in chain.iter().enumerate() {
        let s = (size >> level).max(1);
        queue.write_texture(
            wgpu::TexelCopyTextureInfo { texture: &t.tex, mip_level: level as u32, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
            data,
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(s * 4), rows_per_image: Some(s) },
            wgpu::Extent3d { width: s, height: s, depth_or_array_layers: 1 },
        );
    }
    t
}

impl FoliageGpu {
    pub fn new(device: &wgpu::Device, g_bgl: &wgpu::BindGroupLayout, env_bgl: &wgpu::BindGroupLayout, color: wgpu::TextureFormat, depth: wgpu::TextureFormat, samples: u32) -> Self {
        let module = gpu::shader(device, "foliage.wgsl", &[include_str!("../shaders/common.wgsl"), include_str!("../shaders/foliage.wgsl")].concat());
        let bgl = gpu::bgl(device, "foliage atlas", &[gpu::ftex(0), gpu::ftex(1), gpu::sampler_entry(2, wgpu::SamplerBindingType::Filtering), gpu::uniform_entry(3, false)]);
        let layout = gpu::layout(device, "foliage", &[g_bgl, env_bgl, &bgl]);
        let attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x3, 3 => Float32x4, 4 => Float32x4];
        let buffers = [Some(wgpu::VertexBufferLayout { array_stride: std::mem::size_of::<GpuCard>() as u64, step_mode: wgpu::VertexStepMode::Instance, attributes: &attrs })];
        let pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "foliage cards",
                module: &module,
                vs: "vs_card",
                fs: Some("fs_card"),
                layout: &layout,
                buffers: &buffers,
                targets: &[gpu::target(color, None)],
                depth: Some(wgpu::DepthStencilState { format: depth, depth_write_enabled: Some(true), depth_compare: Some(wgpu::CompareFunction::Greater), stencil: Default::default(), bias: Default::default() }),
                samples,
                cull: None,
            },
        );
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("foliage"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::MipmapFilterMode::Linear,
            ..Default::default()
        });
        let params = device.create_buffer(&wgpu::BufferDescriptor { label: Some("foliage params"), size: 16, usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false });
        FoliageGpu { pipe, bgl, sampler, params, atlases: HashMap::new(), batches: Vec::new(), time: 0.0, wind: 1.0 }
    }

    pub fn has_atlas(&self, key: &str) -> bool {
        self.atlases.contains_key(key)
    }

    /// Upload an atlas (square RGBA8 sRGB colour + alpha, and translucency).
    pub fn upload_atlas(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, key: &str, color: &[u8], trans: &[u8], size: u32) {
        let c = mip_tex(device, queue, "foliage colour", color, size);
        let t = mip_tex(device, queue, "foliage translucency", trans, size);
        let bg = gpu::bind_group(
            device,
            "foliage atlas",
            &self.bgl,
            &[wgpu::BindingResource::TextureView(&c.view), wgpu::BindingResource::TextureView(&t.view), wgpu::BindingResource::Sampler(&self.sampler), self.params.as_entire_binding()],
        );
        self.atlases.insert(key.to_string(), AtlasGpu { bg, color: c, trans: t });
    }

    /// Replace what is drawn: one list of quads per atlas key.
    pub fn set_batches(&mut self, device: &wgpu::Device, batches: Vec<(String, Vec<GpuCard>)>) {
        self.batches = batches
            .into_iter()
            .filter(|(_, v)| !v.is_empty())
            .map(|(atlas, v)| Batch {
                atlas,
                count: v.len() as u32,
                buf: device.create_buffer_init(&wgpu::util::BufferInitDescriptor { label: Some("foliage cards"), contents: bytemuck::cast_slice(&v), usage: wgpu::BufferUsages::VERTEX }),
            })
            .collect();
    }

    pub fn card_count(&self) -> u32 {
        self.batches.iter().map(|b| b.count).sum()
    }

    pub fn write_params(&self, queue: &wgpu::Queue) {
        queue.write_buffer(&self.params, 0, bytemuck::cast_slice(&[self.time, self.wind, 0.0f32, 0.0]));
    }

    /// Draw into a pass whose groups 0 (globals) and 1 (environment) are set.
    /// Leaves group 2 bound to a foliage atlas.
    pub fn draw(&self, pass: &mut wgpu::RenderPass<'_>) {
        let mut set = false;
        for b in &self.batches {
            let Some(a) = self.atlases.get(&b.atlas) else { continue };
            if !set {
                pass.set_pipeline(&self.pipe);
                set = true;
            }
            pass.set_bind_group(2, &a.bg, &[]);
            pass.set_vertex_buffer(0, b.buf.slice(..));
            pass.draw(0..6, 0..b.count);
        }
    }
}
