//! GPU copies of the tiling images used by image fills, loaded on demand
//! from disk (with a full CPU-built mip chain) and kept until the texture set
//! is dropped.
//!
//! Formats: base colour Rgba8UnormSrgb (sampling returns linear), roughness
//! and normal Rgba8Unorm, height Rgba16Float (16-bit PNGs keep their depth).

use super::gpu::{self, Tex};
use eframe::egui_wgpu::wgpu;
use pigment_core::blend::{linear_to_srgb, srgb_to_linear};
use pigment_core::image_fill::resolve_path;
use pigment_core::{Document, ImageChannel, LayerKind};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Largest image side kept on the GPU (bigger sources are downscaled).
const MAX_SIDE: u32 = 4096;

pub struct TileImages {
    /// (path as written in the document, channel) -> texture; `None` = failed to load.
    map: HashMap<(String, u8), Option<Tex>>,
    /// Where relative paths are looked up (the project folder).
    pub bases: Vec<PathBuf>,
    pub sampler: wgpu::Sampler,
}

fn key(path: &str, c: ImageChannel) -> (String, u8) {
    (path.to_string(), c as u8)
}

fn format_for(c: ImageChannel) -> wgpu::TextureFormat {
    match c {
        ImageChannel::BaseColor => wgpu::TextureFormat::Rgba8UnormSrgb,
        ImageChannel::Height => wgpu::TextureFormat::Rgba16Float,
        _ => wgpu::TextureFormat::Rgba8Unorm,
    }
}

impl TileImages {
    pub fn new(device: &wgpu::Device) -> Self {
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("tile images"),
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::Repeat,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::MipmapFilterMode::Linear,
            anisotropy_clamp: 8,
            ..Default::default()
        });
        Self { map: HashMap::new(), bases: Vec::new(), sampler }
    }

    pub fn get(&self, path: &str, c: ImageChannel) -> Option<&Tex> {
        self.map.get(&key(path, c)).and_then(Option::as_ref)
    }

    /// Load every image the document's fill layers use and the GPU lacks.
    pub fn ensure(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, doc: &Document) {
        for l in &doc.layers {
            let (LayerKind::Fill { .. }, Some(fill)) = (&l.kind, &l.image) else { continue };
            for (c, p) in fill.images.iter() {
                let k = key(p, c);
                if self.map.contains_key(&k) {
                    continue;
                }
                let tex = match resolve_path(p, &self.bases) {
                    Some(path) => match load(device, queue, &path, c) {
                        Ok(t) => Some(t),
                        Err(e) => {
                            log::warn!("image fill: can't load {}: {e:#}", path.display());
                            None
                        }
                    },
                    None => {
                        log::warn!("image fill: `{p}` not found");
                        None
                    }
                };
                self.map.insert(k, tex);
            }
        }
    }

    /// Forget images that failed, so they are retried (after the user fixed a path).
    pub fn retry_missing(&mut self) {
        self.map.retain(|_, t| t.is_some());
    }

    pub fn bytes(&self) -> u64 {
        self.map.values().flatten().map(|t| t.bytes()).sum()
    }
}

/// Decode an image and upload it with a full mip chain.
pub fn load(device: &wgpu::Device, queue: &wgpu::Queue, path: &Path, c: ImageChannel) -> anyhow::Result<Tex> {
    let mut img = image::open(path)?.to_rgba32f();
    let (w, h) = img.dimensions();
    if w.max(h) > MAX_SIDE {
        let k = MAX_SIDE as f32 / w.max(h) as f32;
        img = image::imageops::resize(&img, ((w as f32 * k) as u32).max(1), ((h as f32 * k) as u32).max(1), image::imageops::FilterType::Triangle);
    }
    // filter colour in linear light
    if c.is_color() {
        for p in img.pixels_mut() {
            for v in &mut p.0[..3] {
                *v = srgb_to_linear(*v);
            }
        }
    }
    let (w, h) = img.dimensions();
    let format = format_for(c);
    let mips = gpu::mip_count(w.max(h));
    let tex = Tex::new(device, "tile image", w, h, format, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST, mips);
    let mut level = img;
    for m in 0..mips {
        let (lw, lh) = ((w >> m).max(1), (h >> m).max(1));
        if m > 0 {
            level = image::imageops::resize(&level, lw, lh, image::imageops::FilterType::Triangle);
        }
        let data = encode(&level, c);
        let bpp = format.block_copy_size(None).unwrap();
        queue.write_texture(
            wgpu::TexelCopyTextureInfo { texture: &tex.tex, mip_level: m, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
            &data,
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(lw * bpp), rows_per_image: Some(lh) },
            wgpu::Extent3d { width: lw, height: lh, depth_or_array_layers: 1 },
        );
    }
    Ok(tex)
}

fn encode(img: &image::Rgba32FImage, c: ImageChannel) -> Vec<u8> {
    let q = |v: f32| (v.clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
    match c {
        ImageChannel::BaseColor => img.pixels().flat_map(|p| [q(linear_to_srgb(p.0[0])), q(linear_to_srgb(p.0[1])), q(linear_to_srgb(p.0[2])), q(p.0[3])]).collect(),
        ImageChannel::Height => img.pixels().flat_map(|p| p.0.map(|v| half::f16::from_f32(v).to_bits())).flat_map(u16::to_le_bytes).collect(),
        _ => img.pixels().flat_map(|p| p.0.map(q)).collect(),
    }
}
