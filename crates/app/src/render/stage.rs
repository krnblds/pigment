//! Lightbox stage on the GPU (see `pigment_core::stage` and `stage.wgsl`):
//! the cove mesh, the model's occluder height maps, the contact-shadow map,
//! and the uniforms that place them. The viewport drives the passes.

use super::gpu::{self, Tex};
use eframe::egui_wgpu::wgpu;
use glam::{Mat4, Vec3};
use pigment_core::stage::{StageLayout, StageLook};
use wgpu::util::DeviceExt;

/// Occluder and shadow map resolution (texels across the shadow area).
pub const SHADOW_RES: u32 = 256;

pub struct StageGpu {
    sweep_vertices: wgpu::Buffer,
    sweep_indices: wgpu::Buffer,
    sweep_index_count: u32,
    pub floor_pipe: wgpu::RenderPipeline,
    shadow_pipe: wgpu::RenderPipeline,
    floor_bgl: wgpu::BindGroupLayout,
    empty_bg: wgpu::BindGroup,
    occ_bg: wgpu::BindGroup,
    sampler: wgpu::Sampler,
    pub occ_low: Tex,
    pub occ_high: Tex,
    pub shadow: Tex,
    /// Globals copies for the occluder (low, high) and mirror passes.
    pub low_globals: wgpu::Buffer,
    pub high_globals: wgpu::Buffer,
    pub mirror_globals: wgpu::Buffer,
    pub low_bg: wgpu::BindGroup,
    pub high_bg: wgpu::BindGroup,
    pub mirror_bg: wgpu::BindGroup,
}

/// Uniform block of the stage (Globals.stage in viewport.wgsl / stage.wgsl).
pub fn uniforms(look: &StageLook, l: &StageLayout, size: [u32; 2], mirror: bool) -> [[f32; 4]; 6] {
    let height = l.height;
    [
        [1.0, l.floor_y, l.center.x, l.center.y],
        [l.scale, l.shadow_half, height, mirror as u32 as f32],
        [look.albedo.x, look.albedo.y, look.albedo.z, look.roughness],
        [look.f0, look.reflection, look.shadow, look.reflection_fade * height],
        [1.0 / size[0].max(1) as f32, 1.0 / size[1].max(1) as f32, look.env_reflection, 0.0],
        [0.0; 4],
    ]
}

/// Orthographic view of the shadow area from below (`low`: the nearest
/// surface is the lowest one) or above, depth = height above the floor
/// (reverse-Z: 1 at the camera). Texel rows run along +z, like `shadow_uv`.
pub fn occluder_matrix(l: &StageLayout, low: bool) -> Mat4 {
    let s = l.shadow_half;
    let (fy, h) = (l.floor_y - 1e-3 * l.height, l.height);
    let depth = if low { [0.0, -1.0 / h, 0.0, 1.0 + fy / h] } else { [0.0, 1.0 / h, 0.0, -fy / h] };
    let rows = [[1.0 / s, 0.0, 0.0, -l.center.x / s], [0.0, 0.0, -1.0 / s, l.center.y / s], depth, [0.0, 0.0, 0.0, 1.0]];
    Mat4::from_cols_array_2d(&rows).transpose()
}

/// Reflection of world space in the plane y = `floor_y`.
pub fn mirror_matrix(floor_y: f32) -> Mat4 {
    Mat4::from_translation(Vec3::Y * floor_y) * Mat4::from_scale(Vec3::new(1.0, -1.0, 1.0)) * Mat4::from_translation(-Vec3::Y * floor_y)
}

impl StageGpu {
    pub fn new(
        device: &wgpu::Device,
        g_bgl: &wgpu::BindGroupLayout,
        env_bgl: &wgpu::BindGroupLayout,
        globals_size: u64,
        color: wgpu::TextureFormat,
        depth: wgpu::TextureFormat,
        samples: u32,
    ) -> Self {
        let src = [include_str!("../shaders/common.wgsl"), include_str!("../shaders/stage.wgsl")].concat();
        let module = gpu::shader(device, "stage.wgsl", &src);
        let floor_bgl = gpu::bgl(device, "stage floor", &[gpu::ftex(0), gpu::ftex(1), gpu::sampler_entry(2, wgpu::SamplerBindingType::Filtering)]);
        let empty_bgl = gpu::bgl(device, "stage empty", &[]);
        let occ_bgl = gpu::bgl(device, "stage occluders", &[gpu::dtex(0), gpu::dtex(1)]);
        let floor_layout = gpu::layout(device, "stage floor", &[g_bgl, env_bgl, &floor_bgl]);
        let shadow_layout = gpu::layout(device, "stage shadow", &[g_bgl, env_bgl, &empty_bgl, &occ_bgl]);
        let attrs = wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x2, 3 => Float32x4];
        let mesh_layout = [Some(wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<pigment_core::Vertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &attrs,
        })];
        let floor_pipe = gpu::pipeline(
            device,
            gpu::PipeDesc {
                label: "stage floor",
                module: &module,
                vs: "vs_floor",
                fs: Some("fs_floor"),
                layout: &floor_layout,
                buffers: &mesh_layout,
                targets: &[gpu::target(color, None)],
                depth: Some(wgpu::DepthStencilState {
                    format: depth,
                    depth_write_enabled: Some(true),
                    depth_compare: Some(wgpu::CompareFunction::Greater),
                    stencil: Default::default(),
                    bias: Default::default(),
                }),
                samples,
                cull: Some(wgpu::Face::Back),
            },
        );
        let shadow_fmt = wgpu::TextureFormat::Rgba16Float;
        let shadow_pipe = gpu::fullscreen(device, "stage shadow", &module, "fs_shadow", &shadow_layout, &[gpu::target(shadow_fmt, None)]);
        let (verts, idx) = pigment_core::stage::sweep_mesh(128);
        let sweep_vertices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor { label: Some("stage sweep"), contents: bytemuck::cast_slice(&verts), usage: wgpu::BufferUsages::VERTEX });
        let sweep_indices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor { label: Some("stage sweep idx"), contents: bytemuck::cast_slice(&idx), usage: wgpu::BufferUsages::INDEX });
        let att = wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_SRC;
        let occ_low = Tex::new(device, "stage occluders low", SHADOW_RES, SHADOW_RES, depth, att, 1);
        let occ_high = Tex::new(device, "stage occluders high", SHADOW_RES, SHADOW_RES, depth, att, 1);
        let shadow = Tex::new(device, "stage shadow", SHADOW_RES, SHADOW_RES, shadow_fmt, att, 1);
        let empty_bg = gpu::bind_group(device, "stage empty", &empty_bgl, &[]);
        let occ_bg = gpu::bind_group(device, "stage occluders", &occ_bgl, &[wgpu::BindingResource::TextureView(&occ_low.view), wgpu::BindingResource::TextureView(&occ_high.view)]);
        let ubuf = |label| device.create_buffer(&wgpu::BufferDescriptor { label: Some(label), size: globals_size, usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false });
        let (low_globals, high_globals, mirror_globals) = (ubuf("stage low globals"), ubuf("stage high globals"), ubuf("stage mirror globals"));
        let bg = |b: &wgpu::Buffer| gpu::bind_group(device, "stage globals", g_bgl, &[b.as_entire_binding()]);
        let (low_bg, high_bg, mirror_bg) = (bg(&low_globals), bg(&high_globals), bg(&mirror_globals));
        Self {
            sweep_vertices,
            sweep_indices,
            sweep_index_count: idx.len() as u32,
            floor_pipe,
            shadow_pipe,
            floor_bgl,
            empty_bg,
            occ_bg,
            sampler: gpu::linear_sampler(device, 1),
            occ_low,
            occ_high,
            shadow,
            low_globals,
            high_globals,
            mirror_globals,
            low_bg,
            high_bg,
            mirror_bg,
        }
    }

    /// Bind group for the floor pass (shadow map + the mirrored model).
    pub fn floor_bind_group(&self, device: &wgpu::Device, refl: &wgpu::TextureView) -> wgpu::BindGroup {
        gpu::bind_group(
            device,
            "stage floor",
            &self.floor_bgl,
            &[wgpu::BindingResource::TextureView(&self.shadow.view), wgpu::BindingResource::TextureView(refl), wgpu::BindingResource::Sampler(&self.sampler)],
        )
    }

    /// The contact-shadow pass (after the occluder maps are drawn).
    pub fn draw_shadow(&self, enc: &mut wgpu::CommandEncoder, g_bg: &wgpu::BindGroup, env_bg: &wgpu::BindGroup) {
        let mut pass = gpu::pass(enc, "stage shadow", &[&self.shadow.view], Some(wgpu::Color::WHITE));
        pass.set_pipeline(&self.shadow_pipe);
        pass.set_bind_group(0, g_bg, &[]);
        pass.set_bind_group(1, env_bg, &[]);
        pass.set_bind_group(2, &self.empty_bg, &[]);
        pass.set_bind_group(3, &self.occ_bg, &[]);
        pass.draw(0..3, 0..1);
    }

    /// Draw the cove (pipeline + group 2 set here; groups 0/1 by the caller).
    pub fn draw_floor<'a>(&'a self, pass: &mut wgpu::RenderPass<'a>, floor_bg: &'a wgpu::BindGroup) {
        pass.set_pipeline(&self.floor_pipe);
        pass.set_bind_group(2, floor_bg, &[]);
        pass.set_vertex_buffer(0, self.sweep_vertices.slice(..));
        pass.set_index_buffer(self.sweep_indices.slice(..), wgpu::IndexFormat::Uint32);
        pass.draw_indexed(0..self.sweep_index_count, 0, 0..1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::{Vec2, Vec4};

    #[test]
    fn occluder_maps_measure_height_above_the_floor() {
        let l = StageLayout::from_bounds(Vec3::new(-1.0, 0.5, -2.0), Vec3::new(1.0, 2.0, 2.0));
        let low = occluder_matrix(&l, true);
        let high = occluder_matrix(&l, false);
        // a point 0.3 above the floor at the centre
        let p = Vec4::new(0.0, 0.8, 0.0, 1.0);
        let (a, b) = (low * p, high * p);
        assert!((a.x).abs() < 1e-5 && (a.y).abs() < 1e-5);
        assert!(((1.0 - a.z) * l.height - 0.3).abs() < 0.01, "{a}");
        assert!((b.z * l.height - 0.3).abs() < 0.01, "{b}");
        // +z maps to lower rows (texel v grows with z): clip y goes down
        let q = low * Vec4::new(0.0, 0.8, 1.0, 1.0);
        assert!(q.y < 0.0);
        let uv = Vec2::new(q.x * 0.5 + 0.5, 0.5 - q.y * 0.5);
        assert!((uv - l.shadow_uv(Vec2::new(0.0, 1.0))).length() < 1e-5);
    }

    #[test]
    fn gpu_occluders_and_shadow() {
        use crate::render::{env::Environment, texset::TexSet, viewport::{ViewSettings, Viewport}, MeshGpu};
        let instance = wgpu::Instance::default();
        let Ok(adapter) = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default())) else { return };
        let (d, q) = pollster::block_on(adapter.request_device(&crate::render::gpu::device_descriptor(&adapter))).unwrap();
        let mut mesh = pigment_core::Mesh::torus(1.0, 0.38, 64, 24);
        // off-centre and above the origin, like most real assets
        for v in &mut mesh.vertices {
            v.position = (Vec3::from(v.position) + Vec3::new(0.3, 0.9, -0.4)).into();
        }
        let mg = MeshGpu::new(&d, &mesh);
        let mut doc = pigment_core::Document::new_default();
        doc.resolution = 256;
        let mut ts = TexSet::new(&d, &q, 256);
        let (c, r) = mesh.bounding_sphere();
        ts.prepare_mesh(&d, &q, &mg, c, r);
        ts.ensure_resources(&d, &q, &doc);
        ts.composite(&d, &q, &doc, None);
        let mut cam = pigment_core::OrbitCamera::default();
        cam.frame(c, r);
        let mut vp = Viewport::new(&d);
        vp.ensure_targets(&d, [256, 256]);
        let env = Environment::lighting(&d, &q, "lightbox").unwrap();
        vp.draw(&d, &q, &cam, &ViewSettings::default(), Some(&mg), &env, &ts);
        let depth = |t: &Tex| bytemuck::cast_slice::<u8, f32>(&crate::render::gpu::readback(&d, &q, t)).to_vec();
        let (lo, hi) = (depth(&vp.stage.occ_low), depth(&vp.stage.occ_high));
        let n = (SHADOW_RES * SHADOW_RES) as usize;
        let covered = |v: &[f32]| v.iter().filter(|x| **x > 0.0).count();
        // the torus (lying flat) covers a ring in the middle of the map, seen from both sides
        assert!(covered(&lo) > n / 20 && covered(&lo) < n / 2, "{}", covered(&lo));
        assert!((covered(&lo) as i64 - covered(&hi) as i64).abs() < (n / 50) as i64);
        // its hole and the corners are empty
        let mid = (SHADOW_RES / 2 * SHADOW_RES + SHADOW_RES / 2) as usize;
        assert_eq!(lo[mid], 0.0);
        assert_eq!(lo[0], 0.0);
        // the shadow: dark under the ring, lit at the map's corner
        let sh: Vec<u16> = bytemuck::cast_slice(&crate::render::gpu::readback(&d, &q, &vp.stage.shadow)).to_vec();
        let vis = |i: usize| half::f16::from_bits(sh[i * 4]).to_f32();
        let ring = lo.iter().enumerate().filter(|(_, x)| **x > 0.9).map(|(i, _)| i).next().expect("a texel at the ring's bottom");
        eprintln!("shadow under ring {} corner {} centre {}", vis(ring), vis(0), vis(mid));
        assert!(vis(ring) < 0.3, "under the ring: {}", vis(ring));
        assert!(vis(0) > 0.9, "corner: {}", vis(0));
    }

    #[test]
    fn mirror_reflects_in_the_floor() {
        let m = mirror_matrix(0.5);
        let p = m.transform_point3(Vec3::new(1.0, 1.25, -2.0));
        assert!((p - Vec3::new(1.0, -0.25, -2.0)).length() < 1e-5);
    }
}
