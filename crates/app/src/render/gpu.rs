//! Small wgpu helpers shared by the render modules.

use eframe::egui_wgpu::wgpu;

pub struct Tex {
    pub tex: wgpu::Texture,
    pub view: wgpu::TextureView,
    pub size: u32,
    pub height: u32,
    pub format: wgpu::TextureFormat,
    pub mips: u32,
}

impl Tex {
    pub fn new(
        device: &wgpu::Device,
        label: &str,
        w: u32,
        h: u32,
        format: wgpu::TextureFormat,
        usage: wgpu::TextureUsages,
        mips: u32,
    ) -> Self {
        let tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
            mip_level_count: mips,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage,
            view_formats: &[],
        });
        let view = tex.create_view(&Default::default());
        Self { tex, view, size: w, height: h, format, mips }
    }

    /// Multisampled attachment (not sampled, no mips).
    pub fn new_ms(device: &wgpu::Device, label: &str, size: [u32; 2], format: wgpu::TextureFormat, usage: wgpu::TextureUsages, samples: u32) -> Self {
        let tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d { width: size[0], height: size[1], depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: samples,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage,
            view_formats: &[],
        });
        let view = tex.create_view(&Default::default());
        Self { tex, view, size: size[0], height: size[1], format, mips: 1 }
    }

    /// Render target + sampled + copyable: what almost every texture here needs.
    pub fn target(device: &wgpu::Device, label: &str, size: u32, format: wgpu::TextureFormat) -> Self {
        Self::new(device, label, size, size, format, rw_usage(), 1)
    }

    pub fn mip_view(&self, level: u32) -> wgpu::TextureView {
        self.tex.create_view(&wgpu::TextureViewDescriptor {
            base_mip_level: level,
            mip_level_count: Some(1),
            ..Default::default()
        })
    }

    pub fn bytes(&self) -> u64 {
        let bpp = self.format.block_copy_size(None).unwrap_or(4) as u64;
        let base = self.size as u64 * self.height as u64 * bpp;
        if self.mips > 1 { base * 4 / 3 } else { base }
    }
}

pub fn rw_usage() -> wgpu::TextureUsages {
    wgpu::TextureUsages::RENDER_ATTACHMENT
        | wgpu::TextureUsages::TEXTURE_BINDING
        | wgpu::TextureUsages::COPY_SRC
        | wgpu::TextureUsages::COPY_DST
}

pub fn mip_count(size: u32) -> u32 {
    32 - size.max(1).leading_zeros()
}

// ---- bind group layout entries ----

pub fn tex_entry(binding: u32, sample: wgpu::TextureSampleType) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
        ty: wgpu::BindingType::Texture {
            sample_type: sample,
            view_dimension: wgpu::TextureViewDimension::D2,
            multisampled: false,
        },
        count: None,
    }
}

pub fn ftex(binding: u32) -> wgpu::BindGroupLayoutEntry {
    tex_entry(binding, wgpu::TextureSampleType::Float { filterable: true })
}
/// Non-filterable float (Rgba32Float etc.), read with textureLoad.
pub fn ntex(binding: u32) -> wgpu::BindGroupLayoutEntry {
    tex_entry(binding, wgpu::TextureSampleType::Float { filterable: false })
}
pub fn utex(binding: u32) -> wgpu::BindGroupLayoutEntry {
    tex_entry(binding, wgpu::TextureSampleType::Uint)
}
pub fn dtex(binding: u32) -> wgpu::BindGroupLayoutEntry {
    tex_entry(binding, wgpu::TextureSampleType::Depth)
}

pub fn uniform_entry(binding: u32, dynamic: bool) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
        ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Uniform, has_dynamic_offset: dynamic, min_binding_size: None },
        count: None,
    }
}

pub fn storage_entry(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Storage { read_only: true },
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

pub fn sampler_entry(binding: u32, kind: wgpu::SamplerBindingType) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry { binding, visibility: wgpu::ShaderStages::VERTEX_FRAGMENT, ty: wgpu::BindingType::Sampler(kind), count: None }
}

pub fn bgl(device: &wgpu::Device, label: &str, entries: &[wgpu::BindGroupLayoutEntry]) -> wgpu::BindGroupLayout {
    device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor { label: Some(label), entries })
}

/// Bind group from a list of resources, bound at 0, 1, 2, ...
pub fn bind_group(device: &wgpu::Device, label: &str, layout: &wgpu::BindGroupLayout, res: &[wgpu::BindingResource]) -> wgpu::BindGroup {
    let entries: Vec<wgpu::BindGroupEntry> =
        res.iter().enumerate().map(|(i, r)| wgpu::BindGroupEntry { binding: i as u32, resource: r.clone() }).collect();
    device.create_bind_group(&wgpu::BindGroupDescriptor { label: Some(label), layout, entries: &entries })
}

pub fn layout(device: &wgpu::Device, label: &str, groups: &[&wgpu::BindGroupLayout]) -> wgpu::PipelineLayout {
    let g: Vec<Option<&wgpu::BindGroupLayout>> = groups.iter().map(|g| Some(*g)).collect();
    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor { label: Some(label), bind_group_layouts: &g, immediate_size: 0 })
}

pub fn shader(device: &wgpu::Device, label: &str, src: &str) -> wgpu::ShaderModule {
    device.create_shader_module(wgpu::ShaderModuleDescriptor { label: Some(label), source: wgpu::ShaderSource::Wgsl(src.into()) })
}

pub fn target(format: wgpu::TextureFormat, blend: Option<wgpu::BlendState>) -> Option<wgpu::ColorTargetState> {
    Some(wgpu::ColorTargetState { format, blend, write_mask: wgpu::ColorWrites::ALL })
}

pub const MAX_BLEND: wgpu::BlendState = wgpu::BlendState {
    color: wgpu::BlendComponent { src_factor: wgpu::BlendFactor::One, dst_factor: wgpu::BlendFactor::One, operation: wgpu::BlendOperation::Max },
    alpha: wgpu::BlendComponent { src_factor: wgpu::BlendFactor::One, dst_factor: wgpu::BlendFactor::One, operation: wgpu::BlendOperation::Max },
};

pub const ADD_BLEND: wgpu::BlendState = wgpu::BlendState {
    color: wgpu::BlendComponent { src_factor: wgpu::BlendFactor::One, dst_factor: wgpu::BlendFactor::One, operation: wgpu::BlendOperation::Add },
    alpha: wgpu::BlendComponent { src_factor: wgpu::BlendFactor::One, dst_factor: wgpu::BlendFactor::One, operation: wgpu::BlendOperation::Add },
};

pub struct PipeDesc<'a> {
    pub label: &'a str,
    pub module: &'a wgpu::ShaderModule,
    pub vs: &'a str,
    pub fs: Option<&'a str>,
    pub layout: &'a wgpu::PipelineLayout,
    pub buffers: &'a [Option<wgpu::VertexBufferLayout<'a>>],
    pub targets: &'a [Option<wgpu::ColorTargetState>],
    pub depth: Option<wgpu::DepthStencilState>,
    pub samples: u32,
    pub cull: Option<wgpu::Face>,
}

pub fn pipeline(device: &wgpu::Device, d: PipeDesc) -> wgpu::RenderPipeline {
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(d.label),
        layout: Some(d.layout),
        vertex: wgpu::VertexState { module: d.module, entry_point: Some(d.vs), compilation_options: Default::default(), buffers: d.buffers },
        primitive: wgpu::PrimitiveState { cull_mode: d.cull, ..Default::default() },
        depth_stencil: d.depth,
        multisample: wgpu::MultisampleState { count: d.samples, mask: !0, alpha_to_coverage_enabled: false },
        fragment: d.fs.map(|fs| wgpu::FragmentState {
            module: d.module,
            entry_point: Some(fs),
            compilation_options: Default::default(),
            targets: d.targets,
        }),
        multiview_mask: None,
        cache: None,
    })
}

/// A fullscreen-triangle pipeline (vertex entry `vs_full` from common.wgsl).
pub fn fullscreen(
    device: &wgpu::Device,
    label: &str,
    module: &wgpu::ShaderModule,
    fs: &str,
    layout: &wgpu::PipelineLayout,
    targets: &[Option<wgpu::ColorTargetState>],
) -> wgpu::RenderPipeline {
    pipeline(device, PipeDesc { label, module, vs: "vs_full", fs: Some(fs), layout, buffers: &[], targets, depth: None, samples: 1, cull: None })
}

/// Begin a render pass that writes `views` (load or clear).
pub fn pass<'a>(enc: &'a mut wgpu::CommandEncoder, label: &str, views: &[&wgpu::TextureView], clear: Option<wgpu::Color>) -> wgpu::RenderPass<'a> {
    let atts: Vec<Option<wgpu::RenderPassColorAttachment>> = views
        .iter()
        .map(|v| {
            Some(wgpu::RenderPassColorAttachment {
                view: v,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: clear.map_or(wgpu::LoadOp::Load, wgpu::LoadOp::Clear),
                    store: wgpu::StoreOp::Store,
                },
            })
        })
        .collect();
    enc.begin_render_pass(&wgpu::RenderPassDescriptor {
        label: Some(label),
        color_attachments: &atts,
        depth_stencil_attachment: None,
        timestamp_writes: None,
        occlusion_query_set: None,
        multiview_mask: None,
    })
}

pub fn linear_sampler(device: &wgpu::Device, aniso: u16) -> wgpu::Sampler {
    device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("linear"),
        address_mode_u: wgpu::AddressMode::ClampToEdge,
        address_mode_v: wgpu::AddressMode::ClampToEdge,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        mipmap_filter: wgpu::MipmapFilterMode::Linear,
        anisotropy_clamp: aniso,
        ..Default::default()
    })
}

pub fn copy_tex(enc: &mut wgpu::CommandEncoder, src: &wgpu::Texture, src_xy: [u32; 2], dst: &wgpu::Texture, dst_xy: [u32; 2], size: [u32; 2]) {
    enc.copy_texture_to_texture(
        wgpu::TexelCopyTextureInfo { texture: src, mip_level: 0, origin: wgpu::Origin3d { x: src_xy[0], y: src_xy[1], z: 0 }, aspect: wgpu::TextureAspect::All },
        wgpu::TexelCopyTextureInfo { texture: dst, mip_level: 0, origin: wgpu::Origin3d { x: dst_xy[0], y: dst_xy[1], z: 0 }, aspect: wgpu::TextureAspect::All },
        wgpu::Extent3d { width: size[0], height: size[1], depth_or_array_layers: 1 },
    );
}

/// Upload tightly packed pixels into mip 0.
pub fn upload(queue: &wgpu::Queue, t: &Tex, data: &[u8]) {
    let bpp = t.format.block_copy_size(None).unwrap();
    queue.write_texture(
        wgpu::TexelCopyTextureInfo { texture: &t.tex, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
        data,
        wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(t.size * bpp), rows_per_image: Some(t.height) },
        wgpu::Extent3d { width: t.size, height: t.height, depth_or_array_layers: 1 },
    );
}

/// Blocking read of mip 0 into tightly packed bytes.
/// Read several textures (mip 0) back at once: every copy goes into one
/// command buffer, one submit, one wait, instead of a GPU round trip each.
pub fn readback_many(device: &wgpu::Device, queue: &wgpu::Queue, texs: &[&Tex]) -> Vec<Vec<u8>> {
    let mut enc = device.create_command_encoder(&Default::default());
    let jobs: Vec<(wgpu::Buffer, u32, u32, u32)> = texs
        .iter()
        .map(|t| {
            let bpp = t.format.block_copy_size(None).unwrap();
            let row = t.size * bpp;
            let padded = row.div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
            let buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("readback"),
                size: padded as u64 * t.height as u64,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });
            enc.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo { texture: &t.tex, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
                wgpu::TexelCopyBufferInfo {
                    buffer: &buf,
                    layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(padded), rows_per_image: Some(t.height) },
                },
                wgpu::Extent3d { width: t.size, height: t.height, depth_or_array_layers: 1 },
            );
            (buf, row, padded, t.height)
        })
        .collect();
    queue.submit([enc.finish()]);
    for (buf, ..) in &jobs {
        buf.map_async(wgpu::MapMode::Read, .., |r| {
            if let Err(e) = r {
                log::error!("readback map failed: {e}");
            }
        });
    }
    let _ = device.poll(wgpu::PollType::Wait { submission_index: None, timeout: None });
    jobs.into_iter()
        .map(|(buf, row, padded, h)| {
            let mapped = buf.get_mapped_range(..).expect("readback mapping");
            let out = if row == padded {
                mapped.to_vec()
            } else {
                let mut out = Vec::with_capacity((row * h) as usize);
                for y in 0..h as usize {
                    let start = y * padded as usize;
                    out.extend_from_slice(&mapped[start..start + row as usize]);
                }
                out
            };
            drop(mapped);
            buf.unmap();
            out
        })
        .collect()
}

pub fn readback(device: &wgpu::Device, queue: &wgpu::Queue, t: &Tex) -> Vec<u8> {
    let bpp = t.format.block_copy_size(None).unwrap();
    let row = t.size * bpp;
    let padded = row.div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    let buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("readback"),
        size: padded as u64 * t.height as u64,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut enc = device.create_command_encoder(&Default::default());
    enc.copy_texture_to_buffer(
        wgpu::TexelCopyTextureInfo { texture: &t.tex, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
        wgpu::TexelCopyBufferInfo {
            buffer: &buf,
            layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(padded), rows_per_image: Some(t.height) },
        },
        wgpu::Extent3d { width: t.size, height: t.height, depth_or_array_layers: 1 },
    );
    queue.submit([enc.finish()]);
    buf.map_async(wgpu::MapMode::Read, .., |r| {
        if let Err(e) = r {
            log::error!("readback map failed: {e}");
        }
    });
    let _ = device.poll(wgpu::PollType::Wait { submission_index: None, timeout: None });
    let mapped = buf.get_mapped_range(..).expect("readback mapping");
    let mut out = Vec::with_capacity((row * t.height) as usize);
    for y in 0..t.height as usize {
        let start = y * padded as usize;
        out.extend_from_slice(&mapped[start..start + row as usize]);
    }
    drop(mapped);
    buf.unmap();
    out
}

/// Sampled textures the layer compositor binds per shader stage (shared mesh
/// data + accumulation + one layer's channels and mask). wgpu's default limit
/// is 16; every desktop GPU allows far more.
pub const SAMPLED_TEXTURES_NEEDED: u32 = 18;

/// Limits Pigment asks for: wgpu's defaults, plus room for 8K viewports and
/// the compositor's texture count (capped to what the adapter supports).
pub fn required_limits(adapter: &wgpu::Adapter) -> wgpu::Limits {
    let have = adapter.limits();
    wgpu::Limits {
        max_texture_dimension_2d: 8192u32.min(have.max_texture_dimension_2d),
        max_sampled_textures_per_shader_stage: 32u32.min(have.max_sampled_textures_per_shader_stage),
        ..wgpu::Limits::default()
    }
}

/// Device descriptor for every device Pigment creates (app, headless, tests).
pub fn device_descriptor(adapter: &wgpu::Adapter) -> wgpu::DeviceDescriptor<'static> {
    wgpu::DeviceDescriptor { label: Some("pigment"), required_limits: required_limits(adapter), ..Default::default() }
}
