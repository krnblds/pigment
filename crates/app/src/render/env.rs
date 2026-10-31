//! HDRI environment on the GPU: source upload + mips, GGX-prefiltered mip
//! chain, BRDF LUT, and SH9 irradiance (from `pigment_core::envmath`).

use super::gpu::{self, Tex};
use eframe::egui_wgpu::wgpu;
use glam::Vec3;
use pigment_core::envmath::{self, EnvImage};
use std::path::Path;

const ENV_WIDTH: u32 = 1024;
pub const ENV_MIPS: u32 = 7;

pub struct Environment {
    pub prefiltered: Tex,
    pub brdf_lut: Tex,
    pub sh: [Vec3; 9],
    pub sampler: wgpu::Sampler,
    pub name: String,
}

fn to_f16(v: f32) -> u16 {
    half::f16::from_f32(v).to_bits()
}

impl Environment {
    pub fn studio(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        Self::from_image(device, queue, &EnvImage::studio(ENV_WIDTH), "Studio")
    }

    pub fn load(device: &wgpu::Device, queue: &wgpu::Queue, path: &Path) -> anyhow::Result<Self> {
        let img = image::open(path)?.to_rgb32f();
        let img = image::imageops::resize(&img, ENV_WIDTH, ENV_WIDTH / 2, image::imageops::FilterType::Triangle);
        let env = EnvImage::from_rgb32f(img.width(), img.height(), img.as_raw());
        let name = path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        Ok(Self::from_image(device, queue, &env, &name))
    }

    pub fn from_image(device: &wgpu::Device, queue: &wgpu::Queue, env: &EnvImage, name: &str) -> Self {
        let fmt = wgpu::TextureFormat::Rgba16Float;
        let src_mips = gpu::mip_count(env.width);
        let src = Tex::new(device, "env source", env.width, env.height, fmt, gpu::rw_usage(), src_mips);
        // Clamp extreme values (sun disks) so prefiltering doesn't produce fireflies.
        let data: Vec<u16> = env.data.iter().flat_map(|c| [to_f16(c[0].min(2000.0)), to_f16(c[1].min(2000.0)), to_f16(c[2].min(2000.0)), to_f16(1.0)]).collect();
        gpu::upload(queue, &src, bytemuck::cast_slice(&data));

        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("env"),
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::ClampToEdge,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::MipmapFilterMode::Linear,
            ..Default::default()
        });
        let mut enc = device.create_command_encoder(&Default::default());
        let mips = MipGen::new(device);
        mips.generate(device, &mut enc, &src, None);

        let prefiltered = Tex::new(device, "env prefiltered", ENV_WIDTH, ENV_WIDTH / 2, fmt, gpu::rw_usage(), ENV_MIPS);
        let module = gpu::shader(device, "env.wgsl", &[include_str!("../shaders/common.wgsl"), include_str!("../shaders/env.wgsl")].concat());
        let bgl = gpu::bgl(
            device,
            "prefilter",
            &[gpu::ftex(0), gpu::sampler_entry(1, wgpu::SamplerBindingType::Filtering), gpu::uniform_entry(2, false)],
        );
        let layout = gpu::layout(device, "prefilter", &[&bgl]);
        let pipe = gpu::fullscreen(device, "prefilter", &module, "fs_prefilter", &layout, &[gpu::target(fmt, None)]);
        for level in 0..ENV_MIPS {
            let rough = level as f32 / (ENV_MIPS - 1) as f32;
            let params = [rough, env.width as f32, src_mips as f32, 0.0];
            let ubuf = wgpu::util::DeviceExt::create_buffer_init(
                device,
                &wgpu::util::BufferInitDescriptor { label: None, contents: bytemuck::cast_slice(&params), usage: wgpu::BufferUsages::UNIFORM },
            );
            let bg = gpu::bind_group(
                device,
                "prefilter",
                &bgl,
                &[wgpu::BindingResource::TextureView(&src.view), wgpu::BindingResource::Sampler(&sampler), ubuf.as_entire_binding()],
            );
            let view = prefiltered.mip_view(level);
            let mut pass = gpu::pass(&mut enc, "prefilter", &[&view], Some(wgpu::Color::BLACK));
            pass.set_pipeline(&pipe);
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..3, 0..1);
        }
        queue.submit([enc.finish()]);

        let lut_size = 64;
        let lut = envmath::brdf_lut(lut_size, 128);
        let brdf_lut = Tex::new(device, "brdf lut", lut_size, lut_size, wgpu::TextureFormat::Rgba16Float, gpu::rw_usage(), 1);
        let lut_data: Vec<u16> = lut.iter().flat_map(|[a, b]| [to_f16(*a), to_f16(*b), 0, 0]).collect();
        gpu::upload(queue, &brdf_lut, bytemuck::cast_slice(&lut_data));

        Self { prefiltered, brdf_lut, sh: env.irradiance_sh9(), sampler, name: name.to_string() }
    }
}

/// Box-filter mip generation for any filterable colour format.
pub struct MipGen {
    module: wgpu::ShaderModule,
    bgl: wgpu::BindGroupLayout,
    layout: wgpu::PipelineLayout,
    sampler: wgpu::Sampler,
    pipes: std::cell::RefCell<std::collections::HashMap<wgpu::TextureFormat, wgpu::RenderPipeline>>,
}

impl MipGen {
    pub fn new(device: &wgpu::Device) -> Self {
        let module = gpu::shader(device, "mip.wgsl", &[include_str!("../shaders/common.wgsl"), include_str!("../shaders/mip.wgsl")].concat());
        let bgl = gpu::bgl(device, "mip", &[gpu::ftex(0), gpu::sampler_entry(1, wgpu::SamplerBindingType::Filtering)]);
        let layout = gpu::layout(device, "mip", &[&bgl]);
        let sampler = gpu::linear_sampler(device, 1);
        Self { module, bgl, layout, sampler, pipes: Default::default() }
    }

    /// Resample `src` into mip 0 of `dst` (bilinear), e.g. on resolution change.
    pub fn blit(&self, device: &wgpu::Device, enc: &mut wgpu::CommandEncoder, src: &wgpu::TextureView, dst: &Tex) {
        let mut pipes = self.pipes.borrow_mut();
        let pipe = pipes
            .entry(dst.format)
            .or_insert_with(|| gpu::fullscreen(device, "mip", &self.module, "fs_mip", &self.layout, &[gpu::target(dst.format, None)]));
        let bg = gpu::bind_group(device, "blit", &self.bgl, &[wgpu::BindingResource::TextureView(src), wgpu::BindingResource::Sampler(&self.sampler)]);
        let view = dst.mip_view(0);
        let mut pass = gpu::pass(enc, "blit", &[&view], None);
        pass.set_pipeline(pipe);
        pass.set_bind_group(0, &bg, &[]);
        pass.draw(0..3, 0..1);
    }

    /// Regenerate mips 1.. of `t`. With `rect` (texels of mip 0), only that
    /// region (rounded out) is refreshed on every level.
    pub fn generate(&self, device: &wgpu::Device, enc: &mut wgpu::CommandEncoder, t: &Tex, rect: Option<[u32; 4]>) {
        let mut pipes = self.pipes.borrow_mut();
        let pipe = pipes
            .entry(t.format)
            .or_insert_with(|| gpu::fullscreen(device, "mip", &self.module, "fs_mip", &self.layout, &[gpu::target(t.format, None)]));
        for level in 1..t.mips {
            let src = t.mip_view(level - 1);
            let dst = t.mip_view(level);
            let bg = gpu::bind_group(device, "mip", &self.bgl, &[wgpu::BindingResource::TextureView(&src), wgpu::BindingResource::Sampler(&self.sampler)]);
            let mut pass = gpu::pass(enc, "mip", &[&dst], None);
            pass.set_pipeline(pipe);
            pass.set_bind_group(0, &bg, &[]);
            let (w, h) = ((t.size >> level).max(1), (t.height >> level).max(1));
            if let Some([x, y, rw, rh]) = rect {
                let x0 = (x >> level).min(w - 1);
                let y0 = (y >> level).min(h - 1);
                let x1 = ((x + rw).div_ceil(1 << level)).clamp(x0 + 1, w);
                let y1 = ((y + rh).div_ceil(1 << level)).clamp(y0 + 1, h);
                pass.set_scissor_rect(x0, y0, x1 - x0, y1 - y0);
            }
            pass.draw(0..3, 0..1);
        }
    }
}
