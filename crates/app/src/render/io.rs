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
    let emissive: Vec<u16> = f16_bytes_to_f32(&rb(5))
        .enumerate()
        .map(|(i, v)| if i % 4 == 3 { unorm16(v) } else { unorm16(v / 16.0) })
        .collect();
    Some(LayerPixels { size: ts.res, color: rb(0), roughness: rb(1), metallic: rb(2), height, normal: rb(4), emissive })
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
    let e: Vec<u16> = px
        .emissive
        .iter()
        .enumerate()
        .map(|(i, &v)| {
            let x = v as f32 / 65535.0;
            f16::from_f32(if i % 4 == 3 { x } else { x * 16.0 }).to_bits()
        })
        .collect();
    gpu::upload(queue, &l.ch[5], bytemuck::cast_slice(&e));
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
/// Run `f` over `src` split into `chunk`-aligned pieces on all cores and
/// concatenate the outputs in order.
fn par_chunks<T: Sync, U: Send + Copy>(src: &[T], chunk: usize, f: impl Fn(&[T]) -> Vec<U> + Sync) -> Vec<U> {
    let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(16);
    let per = src.len().div_ceil(threads).div_ceil(chunk).max(1) * chunk;
    let parts: Vec<Vec<U>> = std::thread::scope(|s| {
        let hs: Vec<_> = src.chunks(per).map(|c| s.spawn(|| f(c))).collect();
        hs.into_iter().map(|h| h.join().expect("conversion thread")).collect()
    });
    parts.concat()
}

/// Largest finite, non-negative half in little-endian f16 bytes (0 if none).
/// For non-negative halves the bit pattern orders like the value.
fn f16_peak(b: &[u8], skip_alpha: bool) -> u16 {
    b.chunks_exact(2)
        .enumerate()
        .filter(|(i, _)| !skip_alpha || i % 4 != 3)
        .map(|(_, c)| u16::from_le_bytes([c[0], c[1]]))
        .filter(|&h| h < 0x7c00) // sign bit clear, not inf / NaN
        .max()
        .unwrap_or(0)
}

/// A 65536-entry table over every half-float bit pattern.
fn f16_lut<T>(f: impl Fn(f32) -> T) -> Vec<T> {
    (0..=u16::MAX).map(|b| f(f16::from_bits(b).to_f32())).collect()
}

/// The final, seam-padded material, for export. All five maps come back in
/// one GPU round trip; the half-float conversions are table lookups (one
/// entry per f16 bit pattern) spread over all cores.
pub fn read_material(device: &wgpu::Device, queue: &wgpu::Queue, ts: &TexSet) -> MaterialImages {
    let mut maps = gpu::readback_many(device, queue, &[&ts.material[0], &ts.material[1], &ts.material[2], &ts.material[3], &ts.emissive]).into_iter();
    let (color, orm, normal, h, e) = (maps.next().unwrap(), maps.next().unwrap(), maps.next().unwrap(), maps.next().unwrap(), maps.next().unwrap());
    // emission is HDR: normalise so the brightest texel is 1, report the scale
    let peak = f16::from_bits(par_chunks(&e, 8, |c| vec![f16_peak(c, true)]).into_iter().max().unwrap_or(0)).to_f32();
    let scale = if peak > 1.0 { peak } else { 1.0 };
    let srgb = f16_lut(|v| {
        let v = if v.is_nan() { 0.0 } else { v };
        (pigment_core::blend::linear_to_srgb((v / scale).clamp(0.0, 1.0)) * 255.0).round() as u8
    });
    let emissive = par_chunks(&e, 8, |c| {
        c.chunks_exact(8)
            .flat_map(|p| {
                let ch = |k: usize| srgb[u16::from_le_bytes([p[2 * k], p[2 * k + 1]]) as usize];
                [ch(0), ch(1), ch(2), 255]
            })
            .collect()
    });
    let hl = f16_lut(|v| unorm16(v * 0.5 + 0.5));
    let height = par_chunks(&h, 2, |c| c.chunks_exact(2).map(|p| hl[u16::from_le_bytes([p[0], p[1]]) as usize]).collect());
    MaterialImages { size: ts.res, color, orm, normal, height, emissive, emissive_scale: scale }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn half_float_tables_match_direct_conversion() {
        let vals = [0.0f32, 0.25, 1.0, 3.5, 6.0, -2.0, 0.001, 65504.0];
        let bytes: Vec<u8> = vals.iter().flat_map(|v| f16::from_f32(*v).to_bits().to_le_bytes()).collect();
        // pixels (rgba): alpha (index 3, 7) is skipped by the peak
        assert_eq!(f16::from_bits(f16_peak(&bytes, true)).to_f32(), 6.0);
        assert_eq!(f16::from_bits(f16_peak(&bytes, false)).to_f32(), 65504.0);
        assert_eq!(f16_peak(&f16::NAN.to_bits().to_le_bytes(), false), 0);
        let hl = f16_lut(|v| unorm16(v * 0.5 + 0.5));
        for v in vals {
            assert_eq!(hl[f16::from_f32(v).to_bits() as usize], unorm16(f16::from_f32(v).to_f32() * 0.5 + 0.5));
        }
        let mut x = 1u32;
        let par = par_chunks(&(0..100_003u32).collect::<Vec<_>>(), 7, |c| c.iter().map(|v| v * 2).collect());
        assert_eq!(par.len(), 100_003);
        assert!(par.iter().enumerate().all(|(i, v)| *v == 2 * i as u32));
        x += par.len() as u32;
        assert!(x > 1);
    }
}
