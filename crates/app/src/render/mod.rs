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
    /// Indices of the mesh itself (the first ones). Flat tile projects append
    /// copies shifted by one period for strokes and decals to wrap; the UV
    /// raster (position / normal / part maps) only uses the original.
    pub uv_index_count: u32,
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
        Self { vertices, indices, index_count: mesh.indices.len() as u32, parts, part_count: p.info.len() as u32, bounds: (lo.into(), hi.into()), uv_index_count: mesh.indices.len() as u32 }
    }

    /// GPU mesh of a flat tile project: `wrap` (from `TileSpec::wrap_mesh`,
    /// `mesh` first, then its shifted copies) is drawn for painting, decals,
    /// bakes and the viewport, `mesh` alone for the UV raster.
    pub fn with_wrap(device: &wgpu::Device, mesh: &Mesh, wrap: &Mesh) -> Self {
        let mut g = Self::new(device, wrap);
        let p = mesh.parts();
        let copies = wrap.vertices.len() / mesh.vertices.len().max(1);
        let vp: Vec<u32> = (0..copies).flat_map(|_| p.vertex_part.iter().copied()).collect();
        g.parts = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("mesh parts"),
            contents: bytemuck::cast_slice(&vp),
            usage: wgpu::BufferUsages::VERTEX,
        });
        g.part_count = p.info.len() as u32;
        let (lo, hi) = mesh.bounds();
        g.bounds = (lo.into(), hi.into());
        g.uv_index_count = mesh.indices.len() as u32;
        g
    }
}
