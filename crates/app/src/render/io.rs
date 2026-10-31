//! Moving pixels between the GPU and the CPU formats used by project files
//! and export, plus resolution changes.

use super::gpu::{self, Tex};
use super::texset::{LayerTex, TexSet, MASK_FORMAT};
use eframe::egui_wgpu::wgpu;
use half::f16;
use pigment_core::export::MaterialImages;
use pigment_core::project::LayerPixels;
use pigment_core::ResId;

fn f16_bytes_to_f32(b: &[u8]) -> impl Iterator<Item = f32> + '_ {
    b.chunks_exact(2).map(|c| f16::from_bits(u16::from_le_bytes([c[0], c[1]])).to_f32())
}

fn unorm16(v: f32) -> u16 {
    (v.clamp(0.0, 1.0) * 65535.0).round() as u16
}

pub fn read_layer(device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet, res: ResId) -> Option<LayerPixels> {
    let l = ts.layers.get(&res)?;
    let rb = |i: usize| gpu::readback(device, queue, &l.ch[i]);
    let h = rb(3);
    let height: Vec<u16> = f16_bytes_to_f32(&h)
        .enumerate()
        .map(|(i, v)| if i % 2 == 0 { unorm16(v * 0.5 + 0.5) } else { unorm16(v) })
        .collect();
    Some(LayerPixels { size: ts.res, color: rb(0), roughness: rb(1), metallic: rb(2), height, normal: rb(4) })
}

pub fn upload_layer(device: &wgpu::Device, queue: &wgpu::Queue, ts: &mut TexSet, res: ResId, px: &LayerPixels) {
    let l = LayerTex::new(device, ts.res);
    gpu::upload(queue, &l.ch[0], &px.color);
    gpu::upload(queue, &l.ch[1], &px.roughness);
    gpu::upload(queue, &l.ch[2], &px.metallic);
    let h: Vec<u16> = px
        .height
        .iter()
        .enumerate()
        .map(|(i, &v)| {
            let x = v as f32 / 65535.0;
            f16::from_f32(if i % 2 == 0 { x * 2.0 - 1.0 } else { x }).to_bits()
        })
        .collect();
    gpu::upload(queue, &l.ch[3], bytemuck::cast_slice(&h));
    gpu::upload(queue, &l.ch[4], &px.normal);
    ts.layers.insert(res, l);
}

pub fn read_mask(device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet, res: ResId) -> Option<Vec<u8>> {
    ts.masks.get(&res).map(|m| gpu::readback(device, queue, m))
}

pub fn upload_mask(device: &wgpu::Device, queue: &wgpu::Queue, ts: &mut TexSet, res: ResId, px: &[u8]) {
    let t = Tex::target(device, "mask", ts.res, MASK_FORMAT);
    gpu::upload(queue, &t, px);
    ts.masks.insert(res, t);
}

/// The final, seam-padded material, for export.
pub fn read_material(device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet) -> MaterialImages {
    let h = gpu::readback(device, queue, &ts.material[3]);
    MaterialImages {
        size: ts.res,
        color: gpu::readback(device, queue, &ts.material[0]),
        orm: gpu::readback(device, queue, &ts.material[1]),
        normal: gpu::readback(device, queue, &ts.material[2]),
        height: f16_bytes_to_f32(&h).map(|v| unorm16(v * 0.5 + 0.5)).collect(),
    }
}

/// Move all layer and mask pixels into `dst` (a fresh TexSet at a new
/// resolution), resampling bilinearly.
pub fn resample_into(device: &wgpu::Device, queue: &wgpu::Queue, src: &TexSet, dst: &mut TexSet) {
    let mut enc = device.create_command_encoder(&Default::default());
    for (res, l) in &src.layers {
        let nl = LayerTex::new(device, dst.res);
        for (s, d) in l.ch.iter().zip(&nl.ch) {
            dst.mip_gen().blit(device, &mut enc, &s.view, d);
        }
        dst.layers.insert(*res, nl);
        dst.unsaved.insert(*res);
    }
    for (res, m) in &src.masks {
        let nm = Tex::target(device, "mask", dst.res, MASK_FORMAT);
        dst.mip_gen().blit(device, &mut enc, &m.view, &nm);
        dst.masks.insert(*res, nm);
        dst.unsaved.insert(*res);
    }
    queue.submit([enc.finish()]);
}
