pub mod bake;
pub mod env;
pub mod gpu;
pub mod io;
pub mod paint;
pub mod texset;
pub mod tile_images;
pub mod viewport;

use eframe::egui_wgpu::wgpu;
use pigment_core::Mesh;
use wgpu::util::DeviceExt;

/// A mesh's vertex and index buffers, plus each vertex's part id.
pub struct MeshGpu {
    pub vertices: wgpu::Buffer,
    pub indices: wgpu::Buffer,
    pub index_count: u32,
    pub parts: wgpu::Buffer,
    pub part_count: u32,
    pub bounds: ([f32; 3], [f32; 3]),
}

impl MeshGpu {
    pub fn new(device: &wgpu::Device, mesh: &Mesh) -> Self {
        let vertices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("mesh vertices"),
            contents: bytemuck::cast_slice(&mesh.vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let indices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("mesh indices"),
            contents: bytemuck::cast_slice(&mesh.indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        let p = mesh.parts();
        let parts = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("mesh parts"),
            contents: bytemuck::cast_slice(&p.vertex_part),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let (lo, hi) = mesh.bounds();
        Self { vertices, indices, index_count: mesh.indices.len() as u32, parts, part_count: p.info.len() as u32, bounds: (lo.into(), hi.into()) }
    }
}
