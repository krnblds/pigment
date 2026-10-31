//! Texture export: channel packing presets for game engines, and PNG output.
//!
//! The renderer reads the final material back into a [`MaterialImages`]; each
//! preset then describes which output files to write and which material
//! channel goes into each of their colour channels.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};

/// Final material pixels, row-major, `size × size`.
pub struct MaterialImages {
    pub size: u32,
    /// RGBA8, sRGB-encoded colour.
    pub color: Vec<u8>,
    /// RGBA8: R = ambient occlusion, G = roughness, B = metallic.
    pub orm: Vec<u8>,
    /// RGBA8 tangent-space normal, OpenGL convention (+Y up), encoded n*0.5+0.5.
    pub normal: Vec<u8>,
    /// 16-bit height, 32768 = neutral.
    pub height: Vec<u16>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    Red,
    Green,
    Blue,
    Roughness,
    Smoothness,
    Metallic,
    Ao,
    Height,
    NormalX,
    /// OpenGL convention (Unity, Godot, Blender).
    NormalY,
    /// DirectX convention (Unreal): green flipped.
    NormalYFlipped,
    NormalZ,
    One,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PixelFormat {
    L8,
    L16,
    Rgb8,
    Rgba8,
}

impl PixelFormat {
    fn channels(self) -> usize {
        match self {
            PixelFormat::L8 | PixelFormat::L16 => 1,
            PixelFormat::Rgb8 => 3,
            PixelFormat::Rgba8 => 4,
        }
    }
}

#[derive(Clone, Debug)]
pub struct OutputMap {
    pub suffix: &'static str,
    pub format: PixelFormat,
    pub sources: Vec<Source>,
}

#[derive(Clone, Debug)]
pub struct Preset {
    pub id: &'static str,
    pub label: &'static str,
    pub outputs: Vec<OutputMap>,
}

pub fn presets() -> Vec<Preset> {
    use PixelFormat::*;
    use Source::*;
    let o = |suffix, format, sources: &[Source]| OutputMap { suffix, format, sources: sources.to_vec() };
    vec![
        Preset {
            id: "unreal",
            label: "Unreal Engine (packed ORM, DirectX normal)",
            outputs: vec![
                o("BaseColor", Rgb8, &[Red, Green, Blue]),
                o("Normal", Rgb8, &[NormalX, NormalYFlipped, NormalZ]),
                o("OcclusionRoughnessMetallic", Rgb8, &[Ao, Roughness, Metallic]),
                o("Height", L16, &[Height]),
            ],
        },
        Preset {
            id: "unity",
            label: "Unity (URP / Built-in metallic)",
            outputs: vec![
                o("Albedo", Rgb8, &[Red, Green, Blue]),
                o("Normal", Rgb8, &[NormalX, NormalY, NormalZ]),
                o("MetallicSmoothness", Rgba8, &[Metallic, Metallic, Metallic, Smoothness]),
                o("Occlusion", L8, &[Ao]),
                o("Height", L16, &[Height]),
            ],
        },
        Preset {
            id: "godot",
            label: "Godot (ORM material)",
            outputs: vec![
                o("albedo", Rgb8, &[Red, Green, Blue]),
                o("normal", Rgb8, &[NormalX, NormalY, NormalZ]),
                o("orm", Rgb8, &[Ao, Roughness, Metallic]),
                o("height", L16, &[Height]),
            ],
        },
        Preset {
            id: "separate",
            label: "Separate maps (glTF / generic)",
            outputs: vec![
                o("BaseColor", Rgb8, &[Red, Green, Blue]),
                o("Roughness", L8, &[Roughness]),
                o("Metallic", L8, &[Metallic]),
                o("AO", L8, &[Ao]),
                o("Normal_OpenGL", Rgb8, &[NormalX, NormalY, NormalZ]),
                o("Height", L16, &[Height]),
            ],
        },
    ]
}

pub fn preset(id: &str) -> Option<Preset> {
    presets().into_iter().find(|p| p.id == id)
}

/// Value of `src` at pixel `i`, as 16-bit (0..65535).
fn sample(m: &MaterialImages, src: Source, i: usize) -> u16 {
    let b = |v: u8| v as u16 * 257;
    match src {
        Source::Red => b(m.color[4 * i]),
        Source::Green => b(m.color[4 * i + 1]),
        Source::Blue => b(m.color[4 * i + 2]),
        Source::Ao => b(m.orm[4 * i]),
        Source::Roughness => b(m.orm[4 * i + 1]),
        Source::Smoothness => b(255 - m.orm[4 * i + 1]),
        Source::Metallic => b(m.orm[4 * i + 2]),
        Source::NormalX => b(m.normal[4 * i]),
        Source::NormalY => b(m.normal[4 * i + 1]),
        Source::NormalYFlipped => b(255 - m.normal[4 * i + 1]),
        Source::NormalZ => b(m.normal[4 * i + 2]),
        Source::Height => m.height[i],
        Source::One => 65535,
    }
}

pub enum Packed {
    Bytes(Vec<u8>),
    Words(Vec<u16>),
}

pub fn pack(out: &OutputMap, m: &MaterialImages) -> Packed {
    let n = (m.size * m.size) as usize;
    let ch = out.format.channels();
    assert_eq!(out.sources.len(), ch, "{}: wrong number of sources", out.suffix);
    match out.format {
        PixelFormat::L16 => Packed::Words((0..n).map(|i| sample(m, out.sources[0], i)).collect()),
        _ => {
            let mut v = Vec::with_capacity(n * ch);
            for i in 0..n {
                for s in &out.sources {
                    v.push((sample(m, *s, i) >> 8) as u8);
                }
            }
            Packed::Bytes(v)
        }
    }
}

pub fn write_packed(path: &Path, size: u32, format: PixelFormat, data: &Packed) -> Result<()> {
    use image::ExtendedColorType as C;
    let (bytes, color): (Vec<u8>, C) = match (format, data) {
        (PixelFormat::L16, Packed::Words(w)) => (bytemuck::cast_slice(w).to_vec(), C::L16),
        (PixelFormat::L8, Packed::Bytes(b)) => (b.clone(), C::L8),
        (PixelFormat::Rgb8, Packed::Bytes(b)) => (b.clone(), C::Rgb8),
        (PixelFormat::Rgba8, Packed::Bytes(b)) => (b.clone(), C::Rgba8),
        _ => anyhow::bail!("format/data mismatch"),
    };
    // PNG wants 16-bit samples big-endian; image's encoder takes native-endian u16 bytes.
    image::save_buffer(path, &bytes, size, size, color).with_context(|| format!("writing {}", path.display()))
}

/// Write every output of `preset` into `dir` as `<base>_<suffix>.png`.
pub fn export(dir: &Path, base: &str, preset: &Preset, m: &MaterialImages) -> Result<Vec<PathBuf>> {
    std::fs::create_dir_all(dir)?;
    let mut written = Vec::new();
    for out in &preset.outputs {
        let path = dir.join(format!("{base}_{}.png", out.suffix));
        write_packed(&path, m.size, out.format, &pack(out, m))?;
        written.push(path);
    }
    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tiny() -> MaterialImages {
        // 2x2; pixel 0 is distinctive
        MaterialImages {
            size: 2,
            color: vec![10, 20, 30, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255],
            orm: vec![200, 100, 50, 255, 255, 128, 0, 255, 255, 128, 0, 255, 255, 128, 0, 255],
            normal: vec![128, 200, 255, 255, 128, 128, 255, 255, 128, 128, 255, 255, 128, 128, 255, 255],
            height: vec![40000, 32768, 32768, 32768],
        }
    }

    #[test]
    fn unreal_orm_packing_and_dx_normal() {
        let p = preset("unreal").unwrap();
        let m = tiny();
        let orm = p.outputs.iter().find(|o| o.suffix == "OcclusionRoughnessMetallic").unwrap();
        let Packed::Bytes(b) = pack(orm, &m) else { panic!() };
        assert_eq!(&b[0..3], &[200, 100, 50]);
        let nrm = p.outputs.iter().find(|o| o.suffix == "Normal").unwrap();
        let Packed::Bytes(n) = pack(nrm, &m) else { panic!() };
        assert_eq!(&n[0..3], &[128, 255 - 200, 255]);
    }

    #[test]
    fn unity_smoothness_is_inverted_roughness_in_alpha() {
        let p = preset("unity").unwrap();
        let ms = p.outputs.iter().find(|o| o.suffix == "MetallicSmoothness").unwrap();
        let Packed::Bytes(b) = pack(ms, &tiny()) else { panic!() };
        assert_eq!(&b[0..4], &[50, 50, 50, 255 - 100]);
        let nrm = p.outputs.iter().find(|o| o.suffix == "Normal").unwrap();
        let Packed::Bytes(n) = pack(nrm, &tiny()) else { panic!() };
        assert_eq!(n[1], 200); // OpenGL: green unchanged
    }

    #[test]
    fn height_is_16_bit() {
        let p = preset("godot").unwrap();
        let h = p.outputs.iter().find(|o| o.suffix == "height").unwrap();
        let Packed::Words(w) = pack(h, &tiny()) else { panic!() };
        assert_eq!(w[0], 40000);
    }

    #[test]
    fn export_writes_readable_pngs() {
        let dir = std::env::temp_dir().join(format!("pigment-export-{}", std::process::id()));
        let files = export(&dir, "Crate", &preset("unreal").unwrap(), &tiny()).unwrap();
        assert_eq!(files.len(), 4);
        let img = image::open(dir.join("Crate_OcclusionRoughnessMetallic.png")).unwrap().to_rgb8();
        assert_eq!(img.get_pixel(0, 0).0, [200, 100, 50]);
        let h = image::open(dir.join("Crate_Height.png")).unwrap().to_luma16();
        assert_eq!(h.get_pixel(0, 0).0, [40000]);
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn every_preset_is_well_formed() {
        for p in presets() {
            for o in &p.outputs {
                assert_eq!(o.sources.len(), o.format.channels(), "{} {}", p.id, o.suffix);
            }
        }
    }
}
