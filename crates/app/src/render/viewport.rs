//! Offscreen 3D viewport: PBR shading of the composited material under the
//! environment, rendered into MSAA targets and handed to egui as an image.
//! Also renders a single-sample depth buffer the brush uses for occlusion.

use super::env::{Environment, ENV_MIPS};
use super::gpu::{self, Tex};
use super::texset::TexSet;
use super::MeshGpu;
use eframe::egui;
use eframe::egui_wgpu::{self, wgpu};
use pigment_core::OrbitCamera;

pub const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;
pub const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;
const MSAA: u32 = 4;

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
}

impl ViewMode {
    pub const ALL: [ViewMode; 11] = [
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
}

struct Targets {
    size: [u32; 2],
    msaa: Tex,
    resolve: Tex,
    /// Raw (non-sRGB) view of `resolve` for egui, which treats texture values
    /// as already gamma-encoded. Sampling through the sRGB view would decode
    /// them first and egui would darken the image a second time.
    display: wgpu::TextureView,
    depth: Tex,
    paint_depth: Tex,
}

pub struct ViewSettings {
    pub mode: ViewMode,
    pub exposure: f32,
    pub env_rotation: f32,
    pub show_env: bool,
    /// Multiplier on painted emission in the viewport.
    pub emission: f32,
}

impl Default for ViewSettings {
    fn default() -> Self {
        Self { mode: ViewMode::Material, exposure: 0.0, env_rotation: 0.0, show_env: true, emission: 1.0 }
    }
}

pub struct Viewport {
    mesh_pipe: wgpu::RenderPipeline,
    bg_pipe: wgpu::RenderPipeline,
    depth_pipe: wgpu::RenderPipeline,
    env_bgl: wgpu::BindGroupLayout,
    mat_bgl: wgpu::BindGroupLayout,
    globals: wgpu::Buffer,
    g_bg: wgpu::BindGroup,
    sampler: wgpu::Sampler,
    targets: Option<Targets>,
    texture_id: Option<egui::TextureId>,
}

impl Viewport {
    pub fn new(device: &wgpu::Device) -> Self {
        let module = gpu::shader(device, "viewport.wgsl", &[include_str!("../shaders/common.wgsl"), include_str!("../shaders/viewport.wgsl")].concat());
        let g_bgl = gpu::bgl(device, "viewport globals", &[gpu::uniform_entry(0, false)]);
        let env_bgl = gpu::bgl(device, "viewport env", &[gpu::ftex(0), gpu::ftex(1), gpu::sampler_entry(2, wgpu::SamplerBindingType::Filtering)]);
        let mat_bgl = gpu::bgl(
            device,
            "viewport material",
            &[gpu::ftex(0), gpu::ftex(1), gpu::ftex(2), gpu::ftex(3), gpu::ftex(4), gpu::ftex(5), gpu::ftex(6), gpu::sampler_entry(7, wgpu::SamplerBindingType::Filtering)],
        );
        let layout = gpu::layout(device, "viewport", &[&g_bgl, &env_bgl, &mat_bgl]);
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
        let ct = [gpu::target(COLOR_FORMAT, None)];
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
        Self { mesh_pipe, bg_pipe, depth_pipe, env_bgl, mat_bgl, globals, g_bg, sampler, targets: None, texture_id: None }
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
        self.targets = Some(Targets {
            size,
            msaa: Tex::new_ms(d, "viewport msaa", size, COLOR_FORMAT, att, MSAA),
            resolve,
            display,
            depth: Tex::new_ms(d, "viewport depth", size, DEPTH_FORMAT, att, MSAA),
            paint_depth: Tex::new(d, "paint depth", size[0], size[1], DEPTH_FORMAT, att | wgpu::TextureUsages::TEXTURE_BINDING, 1),
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
        let globals = Globals {
            view_proj: vp.to_cols_array_2d(),
            inv_view_proj: vp.inverse().to_cols_array_2d(),
            eye: [eye.x, eye.y, eye.z, 1.0],
            params: [settings.mode as u32 as f32, settings.exposure, settings.env_rotation, ENV_MIPS as f32],
            params2: [settings.show_env as u32 as f32, 2.5, ts.baked as u32 as f32, settings.emission],
            sh,
        };
        queue.write_buffer(&self.globals, 0, bytemuck::bytes_of(&globals));

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
            ],
        );
        let Some(t) = self.targets.as_ref() else { return };
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("viewport") });
        {
            let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("viewport"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &t.msaa.view,
                    depth_slice: None,
                    resolve_target: Some(&t.resolve.view),
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
            if let Some(m) = mesh {
                pass.set_pipeline(&self.mesh_pipe);
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
        queue.submit([enc.finish()]);
    }
}
