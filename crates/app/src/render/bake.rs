//! Mesh map baking: ambient occlusion (many-directions shadow mapping) and
//! curvature (mesh dihedral angles rasterised into texture space). Results go
//! into `TexSet::bakes` (r = AO, g = curvature), padded across seams.

use super::gpu::{self, Tex};
use super::texset::{TexSet, BAKES};
use super::MeshGpu;
use eframe::egui_wgpu::wgpu;
use glam::Vec3;
use pigment_core::{curvature, BakeSettings, Mesh};
use wgpu::util::DeviceExt;

const SHADOW_SIZE: u32 = 2048;

pub struct Baker {
    depth_pipe: wgpu::RenderPipeline,
    accum_pipe: wgpu::RenderPipeline,
    light_bgl: wgpu::BindGroupLayout,
    accum_bgl: wgpu::BindGroupLayout,
    curv_pipe: wgpu::RenderPipeline,
    curv_bgl: wgpu::BindGroupLayout,
    resolve_pipe: wgpu::RenderPipeline,
    resolve_bgl: wgpu::BindGroupLayout,
    blur_pipe: wgpu::RenderPipeline,
    blur_bgl: wgpu::BindGroupLayout,
    cmp_sampler: wgpu::Sampler,
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct LightGpu {
    view_proj: [[f32; 4]; 4],
    dir: [f32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct CurvVertex {
    uv: [f32; 2],
    bary: [f32; 3],
    heights: [f32; 3],
    convexity: [f32; 3],
    vcurv: f32,
}

/// Evenly spread directions over the sphere (Fibonacci lattice).
pub fn sphere_directions(n: u32) -> Vec<Vec3> {
    let golden = std::f32::consts::PI * (3.0 - 5f32.sqrt());
    (0..n)
        .map(|i| {
            let y = 1.0 - 2.0 * (i as f32 + 0.5) / n as f32;
            let r = (1.0 - y * y).sqrt();
            let phi = golden * i as f32;
            Vec3::new(r * phi.cos(), y, r * phi.sin())
        })
        .collect()
}

impl Baker {
    pub fn new(device: &wgpu::Device) -> Self {
        let common = include_str!("../shaders/common.wgsl");
        let ao = gpu::shader(device, "bake_ao.wgsl", &[common, include_str!("../shaders/bake_ao.wgsl")].concat());
        let cv = gpu::shader(device, "bake_curv.wgsl", &[common, include_str!("../shaders/bake_curv.wgsl")].concat());
        let rs = gpu::shader(device, "bake_resolve.wgsl", &[common, include_str!("../shaders/bake_resolve.wgsl")].concat());

        let light_bgl = gpu::bgl(device, "light", &[gpu::uniform_entry(0, false)]);
        let accum_bgl = gpu::bgl(
            device,
            "ao accum",
            &[gpu::uniform_entry(0, false), gpu::dtex(1), gpu::sampler_entry(2, wgpu::SamplerBindingType::Comparison), gpu::ntex(3), gpu::ntex(4)],
        );
        let attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32x4];
        let mesh_layout = [Some(wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<pigment_core::Vertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &attrs,
        })];
        let depth_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "ao depth",
                module: &ao,
                vs: "vs_ao_depth",
                fs: None,
                layout: &gpu::layout(device, "ao depth", &[&light_bgl]),
                buffers: &mesh_layout,
                targets: &[],
                depth: Some(wgpu::DepthStencilState {
                    format: wgpu::TextureFormat::Depth32Float,
                    depth_write_enabled: Some(true),
                    depth_compare: Some(wgpu::CompareFunction::Less),
                    stencil: Default::default(),
                    bias: wgpu::DepthBiasState { constant: 2, slope_scale: 2.0, clamp: 0.0 },
                }),
                samples: 1,
                cull: None,
            },
        );
        let accum_pipe = gpu::fullscreen(
            device,
            "ao accum",
            &ao,
            "fs_ao_accum",
            &gpu::layout(device, "ao accum", &[&accum_bgl]),
            &[gpu::target(wgpu::TextureFormat::Rgba16Float, Some(gpu::ADD_BLEND))],
        );

        let curv_bgl = gpu::bgl(device, "curv", &[gpu::uniform_entry(0, false)]);
        let curv_attrs = wgpu::vertex_attr_array![0 => Float32x2, 1 => Float32x3, 2 => Float32x3, 3 => Float32x3, 4 => Float32];
        let curv_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "curvature",
                module: &cv,
                vs: "vs_curv",
                fs: Some("fs_curv"),
                layout: &gpu::layout(device, "curv", &[&curv_bgl]),
                buffers: &[Some(wgpu::VertexBufferLayout {
                    array_stride: std::mem::size_of::<CurvVertex>() as u64,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &curv_attrs,
                })],
                targets: &[gpu::target(wgpu::TextureFormat::R16Float, None)],
                depth: None,
                samples: 1,
                cull: None,
            },
        );
        let resolve_bgl = gpu::bgl(device, "bake resolve", &[gpu::ntex(0), gpu::ntex(1), gpu::utex(2)]);
        let resolve_pipe = gpu::fullscreen(
            device,
            "bake resolve",
            &rs,
            "fs_resolve",
            &gpu::layout(device, "bake resolve", &[&resolve_bgl]),
            &[gpu::target(BAKES, None)],
        );
        let bm = gpu::shader(device, "bake_blur.wgsl", &[common, include_str!("../shaders/bake_blur.wgsl")].concat());
        let blur_bgl = gpu::bgl(device, "curv blur", &[gpu::ntex(0), gpu::utex(1), gpu::uniform_entry(2, false)]);
        let blur_pipe = gpu::fullscreen(
            device,
            "curv blur",
            &bm,
            "fs_blur",
            &gpu::layout(device, "curv blur", &[&blur_bgl]),
            &[gpu::target(wgpu::TextureFormat::R16Float, None)],
        );
        let cmp_sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("shadow"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            compare: Some(wgpu::CompareFunction::LessEqual),
            ..Default::default()
        });
        Self { depth_pipe, accum_pipe, light_bgl, accum_bgl, curv_pipe, curv_bgl, resolve_pipe, resolve_bgl, blur_pipe, blur_bgl, cmp_sampler }
    }

    pub fn bake(&self, device: &wgpu::Device, queue: &wgpu::Queue, mesh: &Mesh, mg: &MeshGpu, ts: &mut TexSet, s: &BakeSettings) {
        let res = ts.res;
        let (center, radius) = mesh.bounding_sphere();
        let radius = radius.max(1e-4);

        // ---- ambient occlusion ----
        let acc = Tex::target(device, "ao accum", res, wgpu::TextureFormat::Rgba16Float);
        let shadow = Tex::new(
            device,
            "ao shadow",
            SHADOW_SIZE,
            SHADOW_SIZE,
            wgpu::TextureFormat::Depth32Float,
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            1,
        );
        {
            let mut enc = device.create_command_encoder(&Default::default());
            drop(gpu::pass(&mut enc, "ao clear", &[&acc.view], Some(wgpu::Color::TRANSPARENT)));
            queue.submit([enc.finish()]);
        }
        let dirs = sphere_directions(s.ao_samples.max(8));
        for batch in dirs.chunks(32) {
            let mut enc = device.create_command_encoder(&Default::default());
            for d in batch {
                let up = if d.y.abs() > 0.99 { Vec3::X } else { Vec3::Y };
                let eye = center + *d * radius * 2.0;
                let view = glam::camera::rh::view::look_at_mat4(eye, center, up);
                let proj = glam::camera::rh::proj::directx::orthographic(-radius, radius, -radius, radius, radius * 0.5, radius * 3.5);
                let light = LightGpu { view_proj: (proj * view).to_cols_array_2d(), dir: [d.x, d.y, d.z, radius * 0.003] };
                let buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("light"),
                    contents: bytemuck::bytes_of(&light),
                    usage: wgpu::BufferUsages::UNIFORM,
                });
                {
                    let lbg = gpu::bind_group(device, "light", &self.light_bgl, &[buf.as_entire_binding()]);
                    let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some("ao depth"),
                        color_attachments: &[],
                        depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                            view: &shadow.view,
                            depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(1.0), store: wgpu::StoreOp::Store }),
                            stencil_ops: None,
                        }),
                        timestamp_writes: None,
                        occlusion_query_set: None,
                        multiview_mask: None,
                    });
                    pass.set_pipeline(&self.depth_pipe);
                    pass.set_bind_group(0, &lbg, &[]);
                    pass.set_vertex_buffer(0, mg.vertices.slice(..));
                    pass.set_index_buffer(mg.indices.slice(..), wgpu::IndexFormat::Uint32);
                    pass.draw_indexed(0..mg.index_count, 0, 0..1);
                }
                let abg = gpu::bind_group(
                    device,
                    "ao accum",
                    &self.accum_bgl,
                    &[
                        buf.as_entire_binding(),
                        wgpu::BindingResource::TextureView(&shadow.view),
                        wgpu::BindingResource::Sampler(&self.cmp_sampler),
                        wgpu::BindingResource::TextureView(&ts.position.view),
                        wgpu::BindingResource::TextureView(&ts.wnormal.view),
                    ],
                );
                let mut pass = gpu::pass(&mut enc, "ao accum", &[&acc.view], None);
                pass.set_pipeline(&self.accum_pipe);
                pass.set_bind_group(0, &abg, &[]);
                pass.draw(0..3, 0..1);
            }
            queue.submit([enc.finish()]);
        }

        // ---- curvature ----
        let cd = curvature::compute(mesh);
        let mut verts = Vec::with_capacity(mesh.indices.len());
        for (t, tri) in mesh.indices.chunks_exact(3).enumerate() {
            for k in 0..3 {
                let mut bary = [0.0; 3];
                bary[k] = 1.0;
                verts.push(CurvVertex {
                    uv: mesh.vertices[tri[k] as usize].uv,
                    bary,
                    heights: cd.heights[t],
                    convexity: cd.edge_convexity[t],
                    vcurv: cd.vertex[tri[k] as usize],
                });
            }
        }
        let curv = Tex::target(device, "curvature", res, wgpu::TextureFormat::R16Float);
        let vbuf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("curvature verts"),
            contents: bytemuck::cast_slice(&verts),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let params = [s.curvature_radius * radius, s.curvature_strength, 0.0, 0.0];
        let pbuf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("curv params"),
            contents: bytemuck::cast_slice(&params),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let mut enc = device.create_command_encoder(&Default::default());
        {
            let bg = gpu::bind_group(device, "curv", &self.curv_bgl, &[pbuf.as_entire_binding()]);
            let mut pass = gpu::pass(&mut enc, "curvature", &[&curv.view], Some(wgpu::Color { r: 0.5, g: 0.0, b: 0.0, a: 1.0 }));
            pass.set_pipeline(&self.curv_pipe);
            pass.set_bind_group(0, &bg, &[]);
            pass.set_vertex_buffer(0, vbuf.slice(..));
            pass.draw(0..verts.len() as u32, 0..1);
        }
        // ---- blur (horizontal then vertical), a few texels per 512 ----
        let tmp = Tex::target(device, "curvature blur", res, wgpu::TextureFormat::R16Float);
        let radius = (res / 256).max(2) as i32;
        for (src, dst, dir) in [(&curv, &tmp, [1i32, 0]), (&tmp, &curv, [0, 1])] {
            let p = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("blur params"),
                contents: bytemuck::cast_slice(&[dir[0], dir[1], radius, res as i32]),
                usage: wgpu::BufferUsages::UNIFORM,
            });
            let bg = gpu::bind_group(
                device,
                "curv blur",
                &self.blur_bgl,
                &[wgpu::BindingResource::TextureView(&src.view), wgpu::BindingResource::TextureView(&ts.nearest.view), p.as_entire_binding()],
            );
            let mut pass = gpu::pass(&mut enc, "curv blur", &[&dst.view], None);
            pass.set_pipeline(&self.blur_pipe);
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..3, 0..1);
        }
        // ---- resolve into the bakes texture (seam padded) ----
        {
            let bg = gpu::bind_group(
                device,
                "bake resolve",
                &self.resolve_bgl,
                &[
                    wgpu::BindingResource::TextureView(&acc.view),
                    wgpu::BindingResource::TextureView(&curv.view),
                    wgpu::BindingResource::TextureView(&ts.nearest.view),
                ],
            );
            let mut pass = gpu::pass(&mut enc, "bake resolve", &[&ts.bakes.view], None);
            pass.set_pipeline(&self.resolve_pipe);
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..3, 0..1);
        }
        queue.submit([enc.finish()]);
        ts.baked = true;
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn sphere_directions_are_unit_and_balanced() {
        let d = super::sphere_directions(256);
        assert!(d.iter().all(|v| (v.length() - 1.0).abs() < 1e-4));
        let mean = d.iter().copied().sum::<glam::Vec3>() / 256.0;
        assert!(mean.length() < 0.01);
    }
}
