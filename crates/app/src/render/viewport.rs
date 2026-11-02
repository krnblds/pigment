//! Offscreen 3D viewport: PBR shading of the composited material under the
//! environment, rendered into an HDR MSAA target, then bloomed and tone
//! mapped (`post.wgsl`) into an 8-bit image handed to egui. Also renders a
//! single-sample depth buffer the brush uses for occlusion.

use super::env::{Environment, ENV_MIPS};
use super::gpu::{self, Tex};
use super::texset::TexSet;
use super::MeshGpu;
use eframe::egui;
use eframe::egui_wgpu::{self, wgpu};
use pigment_core::OrbitCamera;

pub const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;
pub const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;
/// Scene-referred radiance before tone mapping.
pub const HDR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
const MSAA: u32 = 4;
/// Bloom mip chain depth (from half resolution down).
const MAX_BLOOM_MIPS: u32 = 6;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ViewMode {
    Material = 0,
    BaseColor = 1,
    Roughness = 2,
    Metallic = 3,
    Height = 4,
    Normal = 5,
    Ao = 6,
    Curvature = 7,
    WorldNormal = 8,
    UvChecker = 9,
    Emissive = 10,
    Opacity = 11,
    Transmission = 12,
    Coat = 13,
    CoatRoughness = 14,
    Flake = 15,
}

impl ViewMode {
    pub const ALL: [ViewMode; 16] = [
        ViewMode::Material,
        ViewMode::BaseColor,
        ViewMode::Roughness,
        ViewMode::Metallic,
        ViewMode::Height,
        ViewMode::Normal,
        ViewMode::Ao,
        ViewMode::Curvature,
        ViewMode::WorldNormal,
        ViewMode::UvChecker,
        ViewMode::Emissive,
        ViewMode::Opacity,
        ViewMode::Transmission,
        ViewMode::Coat,
        ViewMode::CoatRoughness,
        ViewMode::Flake,
    ];
    pub fn label(self) -> &'static str {
        match self {
            ViewMode::Material => "Material",
            ViewMode::BaseColor => "Base color",
            ViewMode::Roughness => "Roughness",
            ViewMode::Metallic => "Metallic",
            ViewMode::Height => "Height",
            ViewMode::Normal => "Normal",
            ViewMode::Ao => "Ambient occlusion (bake)",
            ViewMode::Curvature => "Curvature (bake)",
            ViewMode::WorldNormal => "World normal (bake)",
            ViewMode::UvChecker => "UV checker",
            ViewMode::Emissive => "Emission",
            ViewMode::Opacity => "Opacity",
            ViewMode::Transmission => "Transmission",
            ViewMode::Coat => "Coat",
            ViewMode::CoatRoughness => "Coat roughness",
            ViewMode::Flake => "Flake",
        }
    }
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Globals {
    view_proj: [[f32; 4]; 4],
    inv_view_proj: [[f32; 4]; 4],
    eye: [f32; 4],
    params: [f32; 4],
    params2: [f32; 4],
    sh: [[f32; 4]; 9],
    /// Lightbox stage block (see `render::stage::uniforms`); zero = no stage.
    stage: [[f32; 4]; 6],
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct PostParams {
    bloom: [f32; 4],
    flags: [f32; 4],
}

struct Targets {
    size: [u32; 2],
    /// HDR multisampled colour, resolved into `hdr`.
    msaa: Tex,
    hdr: Tex,
    /// Bloom mip chain at half resolution, one view per mip.
    bloom_views: Vec<wgpu::TextureView>,
    down_bgs: Vec<wgpu::BindGroup>,
    up_bgs: Vec<wgpu::BindGroup>,
    composite_bg: wgpu::BindGroup,
    /// Final tone-mapped 8-bit image.
    resolve: Tex,
    /// Raw (non-sRGB) view of `resolve` for egui, which treats texture values
    /// as already gamma-encoded. Sampling through the sRGB view would decode
    /// them first and egui would darken the image a second time.
    display: wgpu::TextureView,
    depth: Tex,
    paint_depth: Tex,
    /// Half-res model mirrored in the lightbox floor (+ its depth).
    refl: Tex,
    refl_depth: Tex,
}

#[derive(Clone)]
pub struct ViewSettings {
    pub mode: ViewMode,
    pub exposure: f32,
    pub env_rotation: f32,
    pub show_env: bool,
    /// Multiplier on painted emission in the viewport.
    pub emission: f32,
    pub bloom: BloomSettings,
    /// Show the lightbox stage (cove floor, contact shadow, reflection) when
    /// the lighting has one (`lightbox`, `lightbox_dark`).
    pub stage: bool,
}

impl Default for ViewSettings {
    fn default() -> Self {
        Self { mode: ViewMode::Material, exposure: 0.0, env_rotation: 0.0, show_env: true, emission: 1.0, bloom: BloomSettings::default(), stage: true }
    }
}

/// Glow around emissive surfaces and HDR highlights (material view only).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BloomSettings {
    pub enabled: bool,
    /// Brightness (after exposure) where blooming starts; 1.0 = display white.
    pub threshold: f32,
    /// How much of the blurred light is added back.
    pub intensity: f32,
    /// 0..1: how far the glow spreads (weight of the wider mips).
    pub radius: f32,
}

impl Default for BloomSettings {
    fn default() -> Self {
        Self { enabled: true, threshold: 0.8, intensity: 1.0, radius: 0.6 }
    }
}

pub struct Viewport {
    mesh_pipe: wgpu::RenderPipeline,
    /// See-through surfaces (opacity < 1 or glass), premultiplied-alpha
    /// blended over the opaque pass without writing depth.
    glass_pipe: wgpu::RenderPipeline,
    bg_pipe: wgpu::RenderPipeline,
    depth_pipe: wgpu::RenderPipeline,
    post_bgl: wgpu::BindGroupLayout,
    down_first_pipe: wgpu::RenderPipeline,
    down_pipe: wgpu::RenderPipeline,
    up_pipe: wgpu::RenderPipeline,
    composite_pipe: wgpu::RenderPipeline,
    post_sampler: wgpu::Sampler,
    post_buf: wgpu::Buffer,
    env_bgl: wgpu::BindGroupLayout,
    mat_bgl: wgpu::BindGroupLayout,
    globals: wgpu::Buffer,
    g_bg: wgpu::BindGroup,
    sampler: wgpu::Sampler,
    targets: Option<Targets>,
    texture_id: Option<egui::TextureId>,
    /// Foliage cards drawn after the opaque mesh (see `render/foliage.rs`).
    pub foliage: super::foliage::FoliageGpu,
    /// Lightbox stage (see `render/stage.rs`).
    pub(crate) stage: super::stage::StageGpu,
    /// The model mirrored in the stage floor (single-sample, half res).
    mirror_pipe: wgpu::RenderPipeline,
}

impl Viewport {
    pub fn new(device: &wgpu::Device) -> Self {
        let module = gpu::shader(device, "viewport.wgsl", &[include_str!("../shaders/common.wgsl"), include_str!("../shaders/viewport.wgsl")].concat());
        let g_bgl = gpu::bgl(device, "viewport globals", &[gpu::uniform_entry(0, false)]);
        let env_bgl = gpu::bgl(device, "viewport env", &[gpu::ftex(0), gpu::ftex(1), gpu::sampler_entry(2, wgpu::SamplerBindingType::Filtering)]);
        let mat_bgl = gpu::bgl(
            device,
            "viewport material",
            &[gpu::ftex(0), gpu::ftex(1), gpu::ftex(2), gpu::ftex(3), gpu::ftex(4), gpu::ftex(5), gpu::ftex(6), gpu::sampler_entry(7, wgpu::SamplerBindingType::Filtering), gpu::ftex(8)],
        );
        let layout = gpu::layout(device, "viewport", &[&g_bgl, &env_bgl, &mat_bgl]);
        let foliage = super::foliage::FoliageGpu::new(device, &g_bgl, &env_bgl, HDR_FORMAT, DEPTH_FORMAT, MSAA);
        let stage = super::stage::StageGpu::new(device, &g_bgl, &env_bgl, std::mem::size_of::<Globals>() as u64, HDR_FORMAT, DEPTH_FORMAT, MSAA);
        let depth_layout = gpu::layout(device, "viewport depth", &[&g_bgl]);
        let globals = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("viewport globals"),
            size: std::mem::size_of::<Globals>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let g_bg = gpu::bind_group(device, "viewport globals", &g_bgl, &[globals.as_entire_binding()]);
        let attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32x4];
        let mesh_layout = [Some(wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<pigment_core::Vertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &attrs,
        })];
        let depth_state = |write: bool, cmp| wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: Some(write),
            depth_compare: Some(cmp),
            stencil: Default::default(),
            bias: Default::default(),
        };
        let ct = [gpu::target(HDR_FORMAT, None)];
        let mesh_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "viewport mesh",
                module: &module,
                vs: "vs_mesh",
                fs: Some("fs_mesh"),
                layout: &layout,
                buffers: &mesh_layout,
                targets: &ct,
                depth: Some(depth_state(true, wgpu::CompareFunction::Greater)),
                samples: MSAA,
                cull: None,
            },
        );
        // premultiplied colour; alpha keeps the HDR target's display tag (see post.wgsl)
        let premultiplied = wgpu::BlendState {
            color: wgpu::BlendComponent { src_factor: wgpu::BlendFactor::One, dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha, operation: wgpu::BlendOperation::Add },
            alpha: wgpu::BlendComponent { src_factor: wgpu::BlendFactor::Zero, dst_factor: wgpu::BlendFactor::One, operation: wgpu::BlendOperation::Add },
        };
        let glass_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "viewport glass",
                module: &module,
                vs: "vs_mesh",
                fs: Some("fs_mesh_glass"),
                layout: &layout,
                buffers: &mesh_layout,
                targets: &[gpu::target(HDR_FORMAT, Some(premultiplied))],
                depth: Some(depth_state(false, wgpu::CompareFunction::Greater)),
                samples: MSAA,
                cull: None,
            },
        );
        let mirror_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "viewport mirror",
                module: &module,
                vs: "vs_mesh",
                fs: Some("fs_mesh_mirror"),
                layout: &layout,
                buffers: &mesh_layout,
                targets: &ct,
                depth: Some(depth_state(true, wgpu::CompareFunction::Greater)),
                samples: 1,
                cull: None,
            },
        );
        let bg_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "viewport background",
                module: &module,
                vs: "vs_full",
                fs: Some("fs_bg"),
                layout: &layout,
                buffers: &[],
                targets: &ct,
                depth: Some(depth_state(false, wgpu::CompareFunction::Always)),
                samples: MSAA,
                cull: None,
            },
        );
        let depth_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "paint depth",
                module: &module,
                vs: "vs_depth",
                fs: None,
                layout: &depth_layout,
                buffers: &mesh_layout,
                targets: &[],
                depth: Some(depth_state(true, wgpu::CompareFunction::Greater)),
                samples: 1,
                cull: None,
            },
        );
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("material"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::MipmapFilterMode::Linear,
            anisotropy_clamp: 16,
            ..Default::default()
        });
        // post: bloom chain + tone map
        let post_module = gpu::shader(device, "post.wgsl", &[include_str!("../shaders/common.wgsl"), include_str!("../shaders/post.wgsl")].concat());
        let post_bgl = gpu::bgl(
            device,
            "post",
            &[gpu::ftex(0), gpu::sampler_entry(1, wgpu::SamplerBindingType::Filtering), gpu::uniform_entry(2, false), gpu::ftex(3)],
        );
        let post_layout = gpu::layout(device, "post", &[&post_bgl]);
        let mix_blend = wgpu::BlendComponent { src_factor: wgpu::BlendFactor::Constant, dst_factor: wgpu::BlendFactor::OneMinusConstant, operation: wgpu::BlendOperation::Add };
        let down_first_pipe = gpu::fullscreen(device, "bloom down first", &post_module, "fs_down_first", &post_layout, &[gpu::target(HDR_FORMAT, None)]);
        let down_pipe = gpu::fullscreen(device, "bloom down", &post_module, "fs_down", &post_layout, &[gpu::target(HDR_FORMAT, None)]);
        let up_pipe = gpu::fullscreen(
            device,
            "bloom up",
            &post_module,
            "fs_up",
            &post_layout,
            &[gpu::target(HDR_FORMAT, Some(wgpu::BlendState { color: mix_blend, alpha: mix_blend }))],
        );
        let composite_pipe = gpu::fullscreen(device, "tone map", &post_module, "fs_composite", &post_layout, &[gpu::target(COLOR_FORMAT, None)]);
        let post_sampler = gpu::linear_sampler(device, 1);
        let post_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("post params"),
            size: std::mem::size_of::<PostParams>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self {
            mesh_pipe,
            glass_pipe,
            bg_pipe,
            depth_pipe,
            post_bgl,
            down_first_pipe,
            down_pipe,
            up_pipe,
            composite_pipe,
            post_sampler,
            post_buf,
            env_bgl,
            mat_bgl,
            globals,
            g_bg,
            sampler,
            targets: None,
            texture_id: None,
            foliage,
            stage,
            mirror_pipe,
        }
    }

    /// (Re)create the render targets for `size`. Returns true if they changed.
    pub fn ensure_targets(&mut self, d: &wgpu::Device, size: [u32; 2]) -> bool {
        if self.targets.as_ref().is_some_and(|t| t.size == size) {
            return false;
        }
        let att = wgpu::TextureUsages::RENDER_ATTACHMENT;
        let resolve_tex = d.create_texture(&wgpu::TextureDescriptor {
            label: Some("viewport color"),
            size: wgpu::Extent3d { width: size[0], height: size[1], depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COLOR_FORMAT,
            usage: att | wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[wgpu::TextureFormat::Rgba8Unorm],
        });
        let display = resolve_tex.create_view(&wgpu::TextureViewDescriptor { format: Some(wgpu::TextureFormat::Rgba8Unorm), ..Default::default() });
        let resolve = Tex { view: resolve_tex.create_view(&Default::default()), tex: resolve_tex, size: size[0], height: size[1], format: COLOR_FORMAT, mips: 1 };
        let hdr = Tex::new(d, "viewport hdr", size[0], size[1], HDR_FORMAT, att | wgpu::TextureUsages::TEXTURE_BINDING, 1);
        let (bw, bh) = ((size[0] / 2).max(1), (size[1] / 2).max(1));
        let bloom_mips = (1..MAX_BLOOM_MIPS).take_while(|i| (bw.min(bh) >> i) >= 4).count() as u32 + 1;
        let bloom = Tex::new(d, "bloom", bw, bh, HDR_FORMAT, att | wgpu::TextureUsages::TEXTURE_BINDING, bloom_mips);
        let bloom_views: Vec<wgpu::TextureView> = (0..bloom_mips).map(|i| bloom.mip_view(i)).collect();
        let post_bg = |src: &wgpu::TextureView, extra: &wgpu::TextureView| {
            gpu::bind_group(
                d,
                "post",
                &self.post_bgl,
                &[
                    wgpu::BindingResource::TextureView(src),
                    wgpu::BindingResource::Sampler(&self.post_sampler),
                    self.post_buf.as_entire_binding(),
                    wgpu::BindingResource::TextureView(extra),
                ],
            )
        };
        // down i reads hdr (i = 0) or mip i-1; up i reads mip i+1 into mip i
        let down_bgs = (0..bloom_mips as usize).map(|i| post_bg(if i == 0 { &hdr.view } else { &bloom_views[i - 1] }, &hdr.view)).collect();
        let up_bgs = (0..bloom_mips as usize - 1).map(|i| post_bg(&bloom_views[i + 1], &hdr.view)).collect();
        let composite_bg = post_bg(&hdr.view, &bloom_views[0]);
        self.targets = Some(Targets {
            size,
            msaa: Tex::new_ms(d, "viewport msaa", size, HDR_FORMAT, att, MSAA),
            hdr,
            bloom_views,
            down_bgs,
            up_bgs,
            composite_bg,
            resolve,
            display,
            depth: Tex::new_ms(d, "viewport depth", size, DEPTH_FORMAT, att, MSAA),
            paint_depth: Tex::new(d, "paint depth", size[0], size[1], DEPTH_FORMAT, att | wgpu::TextureUsages::TEXTURE_BINDING, 1),
            refl: Tex::new(d, "stage reflection", bw, bh, HDR_FORMAT, att | wgpu::TextureUsages::TEXTURE_BINDING, 1),
            refl_depth: Tex::new(d, "stage reflection depth", bw, bh, DEPTH_FORMAT, att, 1),
        });
        true
    }

    /// The resolved colour image of the last frame.
    #[allow(dead_code)]
    pub fn color(&self) -> Option<&Tex> {
        self.targets.as_ref().map(|t| &t.resolve)
    }

    /// Depth buffer matching the last rendered frame, for brush occlusion.
    pub fn paint_depth(&self) -> Option<&wgpu::TextureView> {
        self.targets.as_ref().map(|t| &t.paint_depth.view)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn render(
        &mut self,
        rs: &egui_wgpu::RenderState,
        size: [u32; 2],
        camera: &OrbitCamera,
        settings: &ViewSettings,
        mesh: Option<&MeshGpu>,
        env: &Environment,
        ts: &TexSet,
    ) -> Option<egui::TextureId> {
        let size = [size[0].clamp(1, 8192), size[1].clamp(1, 8192)];
        if self.ensure_targets(&rs.device, size) || self.texture_id.is_none() {
            let view = &self.targets.as_ref()?.display;
            let mut renderer = rs.renderer.write();
            match self.texture_id {
                Some(id) => renderer.update_egui_texture_from_wgpu_texture(&rs.device, view, wgpu::FilterMode::Linear, id),
                None => self.texture_id = Some(renderer.register_native_texture(&rs.device, view, wgpu::FilterMode::Linear)),
            }
        }
        self.draw(&rs.device, &rs.queue, camera, settings, mesh, env, ts);
        self.texture_id
    }

    /// Render a frame into the current targets (call `ensure_targets` first).
    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        camera: &OrbitCamera,
        settings: &ViewSettings,
        mesh: Option<&MeshGpu>,
        env: &Environment,
        ts: &TexSet,
    ) {
        let Some(size) = self.targets.as_ref().map(|t| t.size) else { return };

        let aspect = size[0] as f32 / size[1] as f32;
        let vp = camera.view_proj(aspect);
        let eye = camera.eye();
        let mut sh = [[0.0; 4]; 9];
        for (o, c) in sh.iter_mut().zip(env.sh) {
            *o = [c.x, c.y, c.z, 0.0];
        }
        // lightbox stage: only for lighting that has one, in the material view
        let stage = pigment_core::stage::look(&env.source)
            .filter(|_| settings.stage && settings.mode == ViewMode::Material)
            .zip(mesh)
            .map(|(look, m)| (look, pigment_core::stage::StageLayout::from_bounds(glam::Vec3::from(m.bounds.0), glam::Vec3::from(m.bounds.1))));
        let mut globals = Globals {
            view_proj: vp.to_cols_array_2d(),
            inv_view_proj: vp.inverse().to_cols_array_2d(),
            eye: [eye.x, eye.y, eye.z, 1.0],
            params: [settings.mode as u32 as f32, settings.exposure, settings.env_rotation, ENV_MIPS as f32],
            params2: [settings.show_env as u32 as f32, 0.0, ts.baked as u32 as f32, settings.emission],
            sh,
            stage: [[0.0; 4]; 6],
        };
        if let Some((look, layout)) = &stage {
            use super::stage::{mirror_matrix, occluder_matrix, uniforms};
            globals.stage = uniforms(look, layout, size, false);
            let mut g = globals;
            g.view_proj = occluder_matrix(layout, true).to_cols_array_2d();
            queue.write_buffer(&self.stage.low_globals, 0, bytemuck::bytes_of(&g));
            g.view_proj = occluder_matrix(layout, false).to_cols_array_2d();
            queue.write_buffer(&self.stage.high_globals, 0, bytemuck::bytes_of(&g));
            let m = mirror_matrix(layout.floor_y);
            let meye = m.transform_point3(eye);
            g.view_proj = (vp * m).to_cols_array_2d();
            g.eye = [meye.x, meye.y, meye.z, 1.0];
            g.stage = uniforms(look, layout, size, true);
            queue.write_buffer(&self.stage.mirror_globals, 0, bytemuck::bytes_of(&g));
        }
        queue.write_buffer(&self.globals, 0, bytemuck::bytes_of(&globals));
        let b = settings.bloom;
        let bloom_on = b.enabled && b.intensity > 0.0 && settings.mode == ViewMode::Material;
        let post = PostParams {
            bloom: [b.threshold.max(0.0), (b.threshold * 0.5).max(0.05), b.intensity.max(0.0), b.radius.clamp(0.0, 1.0)],
            flags: [bloom_on as u32 as f32, 0.0, 0.0, 0.0],
        };
        queue.write_buffer(&self.post_buf, 0, bytemuck::bytes_of(&post));
        self.foliage.write_params(queue);

        let env_bg = gpu::bind_group(
            device,
            "viewport env",
            &self.env_bgl,
            &[
                wgpu::BindingResource::TextureView(&env.prefiltered.view),
                wgpu::BindingResource::TextureView(&env.brdf_lut.view),
                wgpu::BindingResource::Sampler(&env.sampler),
            ],
        );
        let mat_bg = gpu::bind_group(
            device,
            "viewport material",
            &self.mat_bgl,
            &[
                wgpu::BindingResource::TextureView(&ts.material[0].view),
                wgpu::BindingResource::TextureView(&ts.material[1].view),
                wgpu::BindingResource::TextureView(&ts.material[2].view),
                wgpu::BindingResource::TextureView(&ts.material[3].view),
                wgpu::BindingResource::TextureView(&ts.bakes.view),
                wgpu::BindingResource::TextureView(&ts.wnormal.view),
                wgpu::BindingResource::TextureView(&ts.emissive.view),
                wgpu::BindingResource::Sampler(&self.sampler),
                wgpu::BindingResource::TextureView(&ts.coat.view),
            ],
        );
        let Some(t) = self.targets.as_ref() else { return };
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("viewport") });
        let floor_bg = match (&stage, mesh) {
            (Some(_), Some(m)) => {
                // the model's lowest / highest surfaces, seen from below and above
                for (view, bg) in [(&self.stage.occ_low.view, &self.stage.low_bg), (&self.stage.occ_high.view, &self.stage.high_bg)] {
                    let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some("stage occluders"),
                        color_attachments: &[],
                        depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                            view,
                            depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(0.0), store: wgpu::StoreOp::Store }),
                            stencil_ops: None,
                        }),
                        timestamp_writes: None,
                        occlusion_query_set: None,
                        multiview_mask: None,
                    });
                    pass.set_pipeline(&self.depth_pipe);
                    pass.set_bind_group(0, bg, &[]);
                    pass.set_vertex_buffer(0, m.vertices.slice(..));
                    pass.set_index_buffer(m.indices.slice(..), wgpu::IndexFormat::Uint32);
                    pass.draw_indexed(0..m.index_count, 0, 0..1);
                }
                self.stage.draw_shadow(&mut enc, &self.g_bg, &env_bg);
                // the model mirrored in the floor
                {
                    let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some("stage reflection"),
                        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                            view: &t.refl.view,
                            depth_slice: None,
                            resolve_target: None,
                            ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT), store: wgpu::StoreOp::Store },
                        })],
                        depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                            view: &t.refl_depth.view,
                            depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(0.0), store: wgpu::StoreOp::Discard }),
                            stencil_ops: None,
                        }),
                        timestamp_writes: None,
                        occlusion_query_set: None,
                        multiview_mask: None,
                    });
                    pass.set_pipeline(&self.mirror_pipe);
                    pass.set_bind_group(0, &self.stage.mirror_bg, &[]);
                    pass.set_bind_group(1, &env_bg, &[]);
                    pass.set_bind_group(2, &mat_bg, &[]);
                    pass.set_vertex_buffer(0, m.vertices.slice(..));
                    pass.set_index_buffer(m.indices.slice(..), wgpu::IndexFormat::Uint32);
                    pass.draw_indexed(0..m.index_count, 0, 0..1);
                }
                Some(self.stage.floor_bind_group(device, &t.refl.view))
            }
            _ => None,
        };
        {
            let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("viewport"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &t.msaa.view,
                    depth_slice: None,
                    resolve_target: Some(&t.hdr.view),
                    ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::BLACK), store: wgpu::StoreOp::Discard },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &t.depth.view,
                    depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(0.0), store: wgpu::StoreOp::Discard }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_bind_group(0, &self.g_bg, &[]);
            pass.set_bind_group(1, &env_bg, &[]);
            pass.set_bind_group(2, &mat_bg, &[]);
            pass.set_pipeline(&self.bg_pipe);
            pass.draw(0..3, 0..1);
            if let Some(fb) = &floor_bg {
                self.stage.draw_floor(&mut pass, fb);
                pass.set_bind_group(2, &mat_bg, &[]);
            }
            if let Some(m) = mesh {
                pass.set_pipeline(&self.mesh_pipe);
                pass.set_vertex_buffer(0, m.vertices.slice(..));
                pass.set_index_buffer(m.indices.slice(..), wgpu::IndexFormat::Uint32);
                pass.draw_indexed(0..m.index_count, 0, 0..1);
            }
            // foliage cards (alpha-tested, depth-written)
            if self.foliage.card_count() > 0 {
                self.foliage.draw(&mut pass);
                pass.set_bind_group(2, &mat_bg, &[]);
            }
            if let Some(m) = mesh {
                // then glass and cut-outs over it (depth-tested, not written)
                pass.set_pipeline(&self.glass_pipe);
                pass.set_vertex_buffer(0, m.vertices.slice(..));
                pass.set_index_buffer(m.indices.slice(..), wgpu::IndexFormat::Uint32);
                pass.draw_indexed(0..m.index_count, 0, 0..1);
            }
        }
        {
            let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("paint depth"),
                color_attachments: &[],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &t.paint_depth.view,
                    depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(0.0), store: wgpu::StoreOp::Store }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            if let Some(m) = mesh {
                pass.set_pipeline(&self.depth_pipe);
                pass.set_bind_group(0, &self.g_bg, &[]);
                pass.set_vertex_buffer(0, m.vertices.slice(..));
                pass.set_index_buffer(m.indices.slice(..), wgpu::IndexFormat::Uint32);
                pass.draw_indexed(0..m.index_count, 0, 0..1);
            }
        }
        if bloom_on {
            let n = t.bloom_views.len();
            for i in 0..n {
                let mut pass = gpu::pass(&mut enc, "bloom down", &[&t.bloom_views[i]], Some(wgpu::Color::BLACK));
                pass.set_pipeline(if i == 0 { &self.down_first_pipe } else { &self.down_pipe });
                pass.set_bind_group(0, &t.down_bgs[i], &[]);
                pass.draw(0..3, 0..1);
            }
            let r = b.radius.clamp(0.0, 1.0) as f64;
            for i in (0..n - 1).rev() {
                let mut pass = gpu::pass(&mut enc, "bloom up", &[&t.bloom_views[i]], None);
                pass.set_pipeline(&self.up_pipe);
                pass.set_blend_constant(wgpu::Color { r, g: r, b: r, a: r });
                pass.set_bind_group(0, &t.up_bgs[i], &[]);
                pass.draw(0..3, 0..1);
            }
        }
        {
            let mut pass = gpu::pass(&mut enc, "tone map", &[&t.resolve.view], None);
            pass.set_pipeline(&self.composite_pipe);
            pass.set_bind_group(0, &t.composite_bg, &[]);
            pass.draw(0..3, 0..1);
        }
        queue.submit([enc.finish()]);
    }
}
