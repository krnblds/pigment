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
    /// RGBA8, sRGB-encoded colour; A = opacity (255 = solid).
    pub color: Vec<u8>,
    /// RGBA8: R = ambient occlusion, G = roughness, B = metallic, A = transmission.
    pub orm: Vec<u8>,
    /// RGBA8 tangent-space normal, OpenGL convention (+Y up), encoded n*0.5+0.5.
    pub normal: Vec<u8>,
    /// 16-bit height, 32768 = neutral.
    pub height: Vec<u16>,
    /// RGBA8, sRGB-encoded emission, normalised so the brightest texel is 1.
    pub emissive: Vec<u8>,
    /// Multiply the emissive map by this in the engine to get the painted brightness.
    pub emissive_scale: f32,
    /// RGBA8: R = clearcoat weight, G = coat roughness, B = metallic flake.
    /// Empty = no coat anywhere (coat 0, coat roughness 0.03, flake 0).
    pub coat: Vec<u8>,
}

/// Coat roughness of an uncoated material (0.03 as 8-bit).
pub const NEUTRAL_COAT_ROUGHNESS: u8 = 8;

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
    EmissiveR,
    EmissiveG,
    EmissiveB,
    One,
    /// Alpha: 255 = solid, 0 = cut away.
    Opacity,
    /// 0 = opaque, 255 = clear glass.
    Transmission,
    /// Clearcoat weight: 0 = none.
    Coat,
    /// Clearcoat roughness (only meaningful where there is a coat).
    CoatRoughness,
    /// Metallic flake amount under the coat.
    Flake,
}

impl Source {
    /// Value of a fully solid, non-transmissive material, for sources that
    /// may be left out of an export when they carry no information.
    fn neutral(self) -> Option<u16> {
        match self {
            Source::Opacity => Some(65535),
            Source::Transmission => Some(0),
            Source::Coat | Source::Flake => Some(0),
            Source::CoatRoughness => Some(NEUTRAL_COAT_ROUGHNESS as u16 * 257),
            _ => None,
        }
    }
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
                o("BaseColor", Rgba8, &[Red, Green, Blue, Opacity]),
                o("Normal", Rgb8, &[NormalX, NormalYFlipped, NormalZ]),
                o("OcclusionRoughnessMetallic", Rgb8, &[Ao, Roughness, Metallic]),
                o("Height", L16, &[Height]),
                o("Emissive", Rgb8, &[EmissiveR, EmissiveG, EmissiveB]),
            ],
        },
        Preset {
            id: "unity",
            label: "Unity (URP / Built-in metallic)",
            outputs: vec![
                o("Albedo", Rgba8, &[Red, Green, Blue, Opacity]),
                o("Normal", Rgb8, &[NormalX, NormalY, NormalZ]),
                o("MetallicSmoothness", Rgba8, &[Metallic, Metallic, Metallic, Smoothness]),
                o("Occlusion", L8, &[Ao]),
                o("Height", L16, &[Height]),
                o("Emission", Rgb8, &[EmissiveR, EmissiveG, EmissiveB]),
            ],
        },
        Preset {
            id: "godot",
            label: "Godot (ORM material)",
            outputs: vec![
                o("albedo", Rgba8, &[Red, Green, Blue, Opacity]),
                o("normal", Rgb8, &[NormalX, NormalY, NormalZ]),
                o("orm", Rgb8, &[Ao, Roughness, Metallic]),
                o("height", L16, &[Height]),
                o("emission", Rgb8, &[EmissiveR, EmissiveG, EmissiveB]),
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
                o("Emissive", Rgb8, &[EmissiveR, EmissiveG, EmissiveB]),
                o("Opacity", L8, &[Opacity]),
                o("Transmission", L8, &[Transmission]),
                o("Coat", L8, &[Coat]),
                o("CoatRoughness", L8, &[CoatRoughness]),
                o("Flake", L8, &[Flake]),
            ],
        },
    ]
}

pub fn preset(id: &str) -> Option<Preset> {
    presets().into_iter().find(|p| p.id == id)
}

/// PNG compression effort for export.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Compression {
    /// No deflate compression: fastest to write, biggest files.
    None,
    /// Fast deflate without per-row filter search (Up filter): quick, slightly bigger files.
    Fastest,
    /// Fast deflate with adaptive filtering (the previous default).
    #[default]
    Fast,
    /// Balanced zlib compression.
    Balanced,
    /// Smallest files, slowest.
    Best,
}

impl Compression {
    pub const ALL: [Compression; 5] = [Compression::None, Compression::Fastest, Compression::Fast, Compression::Balanced, Compression::Best];
    pub fn id(self) -> &'static str {
        match self {
            Compression::None => "none",
            Compression::Fastest => "fastest",
            Compression::Fast => "fast",
            Compression::Balanced => "balanced",
            Compression::Best => "best",
        }
    }
    pub fn from_id(id: &str) -> Option<Compression> {
        let id = id.to_ascii_lowercase();
        Self::ALL.into_iter().find(|c| c.id() == id || (id == "default" && *c == Compression::Fast))
    }
    fn image_settings(self) -> (image::codecs::png::CompressionType, image::codecs::png::FilterType) {
        use image::codecs::png::{CompressionType as C, FilterType as F};
        match self {
            Compression::None => (C::Uncompressed, F::NoFilter),
            Compression::Fastest => (C::Fast, F::Up),
            Compression::Fast => (C::Fast, F::Adaptive),
            Compression::Balanced => (C::Default, F::Adaptive),
            Compression::Best => (C::Best, F::Adaptive),
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ExportOptions {
    pub compression: Compression,
    /// Encode the maps on parallel threads (default true).
    pub serial: bool,
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
        Source::EmissiveR => b(m.emissive[4 * i]),
        Source::EmissiveG => b(m.emissive[4 * i + 1]),
        Source::EmissiveB => b(m.emissive[4 * i + 2]),
        Source::One => 65535,
        Source::Opacity => b(m.color[4 * i + 3]),
        Source::Transmission => b(m.orm[4 * i + 3]),
        Source::Coat => b(coat_at(m, 0, i)),
        Source::CoatRoughness => b(coat_at(m, 1, i)),
        Source::Flake => b(coat_at(m, 2, i)),
    }
}

/// Coat / coat roughness / flake (k = 0, 1, 2) at pixel i; an empty coat
/// buffer is an uncoated material.
fn coat_at(m: &MaterialImages, k: usize, i: usize) -> u8 {
    if m.coat.is_empty() {
        return [0, NEUTRAL_COAT_ROUGHNESS, 0][k];
    }
    m.coat[4 * i + k]
}

pub enum Packed {
    Bytes(Vec<u8>),
    Words(Vec<u16>),
}

/// Where an 8-bit source lives: an RGBA8 buffer + channel (optionally
/// inverted), the 16-bit height, or a constant.
enum Plane<'a> {
    Rgba8(&'a [u8], usize, bool),
    Height(&'a [u16]),
    One,
    /// A constant byte (an absent coat buffer).
    Const(u8),
}

fn plane(m: &MaterialImages, src: Source) -> Plane<'_> {
    use Source::*;
    match src {
        Red => Plane::Rgba8(&m.color, 0, false),
        Green => Plane::Rgba8(&m.color, 1, false),
        Blue => Plane::Rgba8(&m.color, 2, false),
        Ao => Plane::Rgba8(&m.orm, 0, false),
        Roughness => Plane::Rgba8(&m.orm, 1, false),
        Smoothness => Plane::Rgba8(&m.orm, 1, true),
        Metallic => Plane::Rgba8(&m.orm, 2, false),
        NormalX => Plane::Rgba8(&m.normal, 0, false),
        NormalY => Plane::Rgba8(&m.normal, 1, false),
        NormalYFlipped => Plane::Rgba8(&m.normal, 1, true),
        NormalZ => Plane::Rgba8(&m.normal, 2, false),
        Height => Plane::Height(&m.height),
        EmissiveR => Plane::Rgba8(&m.emissive, 0, false),
        EmissiveG => Plane::Rgba8(&m.emissive, 1, false),
        EmissiveB => Plane::Rgba8(&m.emissive, 2, false),
        Opacity => Plane::Rgba8(&m.color, 3, false),
        Transmission => Plane::Rgba8(&m.orm, 3, false),
        Coat | CoatRoughness | Flake => {
            let k = match src {
                Coat => 0,
                CoatRoughness => 1,
                _ => 2,
            };
            if m.coat.is_empty() {
                Plane::Const([0, NEUTRAL_COAT_ROUGHNESS, 0][k])
            } else {
                Plane::Rgba8(&m.coat, k, false)
            }
        }
        One => Plane::One,
    }
}

/// Pack one output map. Works plane by plane (a strided copy per output
/// channel) instead of matching on the source per pixel; same result as
/// [`sample`] >> 8 for 8-bit outputs.
pub fn pack(out: &OutputMap, m: &MaterialImages) -> Packed {
    let n = (m.size * m.size) as usize;
    let ch = out.format.channels();
    assert_eq!(out.sources.len(), ch, "{}: wrong number of sources", out.suffix);
    match out.format {
        PixelFormat::L16 => match out.sources[0] {
            Source::Height => Packed::Words(m.height[..n].to_vec()),
            s => Packed::Words((0..n).map(|i| sample(m, s, i)).collect()),
        },
        _ => {
            let mut v = vec![0u8; n * ch];
            for (k, s) in out.sources.iter().enumerate() {
                let dst = v[k..].iter_mut().step_by(ch);
                match plane(m, *s) {
                    Plane::Rgba8(buf, off, false) => dst.zip(buf[off..].iter().step_by(4)).for_each(|(d, s)| *d = *s),
                    Plane::Rgba8(buf, off, true) => dst.zip(buf[off..].iter().step_by(4)).for_each(|(d, s)| *d = 255 - *s),
                    Plane::Height(h) => dst.zip(h.iter()).for_each(|(d, s)| *d = (*s >> 8) as u8),
                    Plane::One => dst.for_each(|d| *d = 255),
                    Plane::Const(c) => dst.for_each(|d| *d = c),
                }
            }
            Packed::Bytes(v)
        }
    }
}

pub fn write_packed(path: &Path, size: u32, format: PixelFormat, data: &Packed) -> Result<()> {
    write_packed_with(path, size, format, data, Compression::default())
}

pub fn write_packed_with(path: &Path, size: u32, format: PixelFormat, data: &Packed, compression: Compression) -> Result<()> {
    use image::ExtendedColorType as C;
    use image::ImageEncoder;
    // image's PNG encoder takes native-endian u16 bytes for 16-bit (it swaps to big-endian)
    let (bytes, color): (&[u8], C) = match (format, data) {
        (PixelFormat::L16, Packed::Words(w)) => (bytemuck::cast_slice(w), C::L16),
        (PixelFormat::L8, Packed::Bytes(b)) => (b, C::L8),
        (PixelFormat::Rgb8, Packed::Bytes(b)) => (b, C::Rgb8),
        (PixelFormat::Rgba8, Packed::Bytes(b)) => (b, C::Rgba8),
        _ => anyhow::bail!("format/data mismatch"),
    };
    let file = std::fs::File::create(path).with_context(|| format!("creating {}", path.display()))?;
    let w = std::io::BufWriter::with_capacity(1 << 20, file);
    let (c, f) = compression.image_settings();
    image::codecs::png::PngEncoder::new_with_quality(w, c, f)
        .write_image(bytes, size, size, color)
        .with_context(|| format!("writing {}", path.display()))
}

/// Does `src` hold its neutral value (solid / not transmissive) everywhere?
fn is_neutral(m: &MaterialImages, src: Source) -> bool {
    // coat roughness carries no information where there is no coat
    if src == Source::CoatRoughness && is_neutral(m, Source::Coat) {
        return true;
    }
    match src.neutral() {
        Some(v) => (0..(m.size * m.size) as usize).all(|i| sample(m, src, i) == v),
        None => false,
    }
}

/// The output as actually written for this material: an alpha channel that
/// is solid everywhere is dropped (RGBA -> RGB), and a single-channel map of
/// a neutral opacity / transmission is skipped entirely (`None`).
pub fn effective_output(out: &OutputMap, m: &MaterialImages) -> Option<OutputMap> {
    let last = *out.sources.last()?;
    if !is_neutral(m, last) {
        return Some(out.clone());
    }
    match out.format {
        PixelFormat::Rgba8 => Some(OutputMap { suffix: out.suffix, format: PixelFormat::Rgb8, sources: out.sources[..3].to_vec() }),
        PixelFormat::L8 | PixelFormat::L16 => None,
        PixelFormat::Rgb8 => Some(out.clone()),
    }
}

/// Write every output of `preset` into `dir` as `<base>_<suffix>.png`.
/// Opacity / transmission maps of a solid material are not written (and a
/// stale one from an earlier export is removed).
pub fn export(dir: &Path, base: &str, preset: &Preset, m: &MaterialImages) -> Result<Vec<PathBuf>> {
    export_with(dir, base, preset, m, ExportOptions::default())
}

/// [`export`] with options: maps are packed and PNG-encoded on parallel
/// threads (one per output map) unless `opts.serial`.
pub fn export_with(dir: &Path, base: &str, preset: &Preset, m: &MaterialImages, opts: ExportOptions) -> Result<Vec<PathBuf>> {
    std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
    // Ok(None): an opacity / transmission map a solid material doesn't need
    let job = |out: &OutputMap| -> Result<Option<PathBuf>> {
        let path = dir.join(format!("{base}_{}.png", out.suffix));
        let Some(out) = effective_output(out, m) else {
            if path.exists() {
                std::fs::remove_file(&path)?;
            }
            return Ok(None);
        };
        write_packed_with(&path, m.size, out.format, &pack(&out, m), opts.compression)?;
        Ok(Some(path))
    };
    if opts.serial {
        return preset.outputs.iter().map(job).filter_map(Result::transpose).collect();
    }
    std::thread::scope(|s| {
        let handles: Vec<_> = preset.outputs.iter().map(|out| s.spawn(move || job(out))).collect();
        handles.into_iter().map(|h| h.join().unwrap_or_else(|_| Err(anyhow::anyhow!("export thread panicked")))).filter_map(Result::transpose).collect()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tiny() -> MaterialImages {
        // 2x2; pixel 0 is distinctive
        MaterialImages {
            size: 2,
            color: vec![10, 20, 30, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255],
            orm: vec![200, 100, 50, 0, 255, 128, 0, 0, 255, 128, 0, 0, 255, 128, 0, 0], // A = transmission
            normal: vec![128, 200, 255, 255, 128, 128, 255, 255, 128, 128, 255, 255, 128, 128, 255, 255],
            height: vec![40000, 32768, 32768, 32768],
            emissive: vec![255, 0, 128, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255],
            emissive_scale: 6.0,
            coat: vec![],
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
        assert_eq!(files.len(), 5);
        let em = image::open(dir.join("Crate_Emissive.png")).unwrap().to_rgb8();
        assert_eq!(em.get_pixel(0, 0).0, [255, 0, 128]);
        let img = image::open(dir.join("Crate_OcclusionRoughnessMetallic.png")).unwrap().to_rgb8();
        assert_eq!(img.get_pixel(0, 0).0, [200, 100, 50]);
        let h = image::open(dir.join("Crate_Height.png")).unwrap().to_luma16();
        assert_eq!(h.get_pixel(0, 0).0, [40000]);
        std::fs::remove_dir_all(dir).ok();
    }

    /// A larger material with varied, non-trivial pixels.
    fn noisy(size: u32) -> MaterialImages {
        let n = (size * size) as usize;
        let mut x = 12345u32;
        let mut r = move || {
            x ^= x << 13;
            x ^= x >> 17;
            x ^= x << 5;
            x
        };
        let mut b = |k: usize| (0..k).map(|_| (r() >> 24) as u8).collect::<Vec<u8>>();
        let (color, orm, normal, emissive, coat) = (b(4 * n), b(4 * n), b(4 * n), b(4 * n), b(4 * n));
        let height = (0..n).map(|i| (i as u32).wrapping_mul(2654435761) as u16).collect();
        MaterialImages { size, color, orm, normal, height, emissive, emissive_scale: 1.0, coat }
    }

    #[test]
    fn plane_packing_matches_per_pixel_sampling() {
        let m = noisy(16);
        for p in presets() {
            for o in &p.outputs {
                let n = 16 * 16;
                match pack(o, &m) {
                    Packed::Bytes(b) => {
                        let mr = &m;
                        let want: Vec<u8> = (0..n).flat_map(|i| o.sources.iter().map(move |s| (sample(mr, *s, i) >> 8) as u8).collect::<Vec<_>>()).collect();
                        assert_eq!(b, want, "{} {}", p.id, o.suffix);
                    }
                    Packed::Words(w) => assert_eq!(w, (0..n).map(|i| sample(&m, o.sources[0], i)).collect::<Vec<_>>()),
                }
            }
        }
    }

    #[test]
    fn every_compression_level_round_trips_in_parallel_export() {
        let m = noisy(64);
        let p = preset("separate").unwrap();
        for c in Compression::ALL {
            assert_eq!(Compression::from_id(c.id()), Some(c));
            let dir = std::env::temp_dir().join(format!("pigment-export-{}-{}", std::process::id(), c.id()));
            let files = export_with(&dir, "N", &p, &m, ExportOptions { compression: c, serial: false }).unwrap();
            assert_eq!(files.len(), p.outputs.len());
            let base = image::open(dir.join("N_BaseColor.png")).unwrap().to_rgb8();
            assert_eq!(base.get_pixel(5, 3).0, [m.color[4 * (3 * 64 + 5)], m.color[4 * (3 * 64 + 5) + 1], m.color[4 * (3 * 64 + 5) + 2]], "{c:?}");
            let h = image::open(dir.join("N_Height.png")).unwrap().to_luma16();
            assert_eq!(h.get_pixel(7, 9).0[0], m.height[9 * 64 + 7], "{c:?}");
            let r = image::open(dir.join("N_Roughness.png")).unwrap().to_luma8();
            assert_eq!(r.get_pixel(1, 2).0[0], m.orm[4 * (2 * 64 + 1) + 1], "{c:?}");
            std::fs::remove_dir_all(dir).ok();
        }
        assert_eq!(Compression::from_id("default"), Some(Compression::Fast));
        assert_eq!(Compression::from_id("zip"), None);
    }

    #[test]
    fn coat_maps_are_written_only_when_coated() {
        let dir = std::env::temp_dir().join(format!("pigment-export-coat-{}", std::process::id()));
        let sep = preset("separate").unwrap();
        // uncoated (empty buffer): no coat maps
        let files = export(&dir, "Plain", &sep, &tiny()).unwrap();
        assert!(!files.iter().any(|f| f.to_string_lossy().contains("Coat") || f.to_string_lossy().contains("Flake")), "{files:?}");
        // uncoated but explicit buffer: same
        let mut m = tiny();
        m.coat = [0u8, NEUTRAL_COAT_ROUGHNESS, 0, 255].repeat(4);
        assert!(!export(&dir, "Plain", &sep, &m).unwrap().iter().any(|f| f.to_string_lossy().contains("Coat")));
        // coated pixel 0: coat 255, coat roughness 20, flake 0 -> Coat + CoatRoughness, no Flake
        m.coat[0] = 255;
        m.coat[1] = 20;
        let files = export(&dir, "Car", &sep, &m).unwrap();
        assert!(files.iter().any(|f| f.ends_with("Car_Coat.png")) && files.iter().any(|f| f.ends_with("Car_CoatRoughness.png")));
        assert!(!files.iter().any(|f| f.ends_with("Car_Flake.png")));
        assert_eq!(image::open(dir.join("Car_Coat.png")).unwrap().to_luma8().get_pixel(0, 0).0, [255]);
        assert_eq!(image::open(dir.join("Car_CoatRoughness.png")).unwrap().to_luma8().get_pixel(0, 0).0, [20]);
        m.coat[2] = 200;
        export(&dir, "Car", &sep, &m).unwrap();
        assert_eq!(image::open(dir.join("Car_Flake.png")).unwrap().to_luma8().get_pixel(0, 0).0, [200]);
        // re-exporting uncoated removes the stale maps
        export(&dir, "Car", &sep, &tiny()).unwrap();
        assert!(!dir.join("Car_Coat.png").exists() && !dir.join("Car_CoatRoughness.png").exists() && !dir.join("Car_Flake.png").exists());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn opacity_goes_to_base_color_alpha_and_separate_maps_only_when_used() {
        let dir = std::env::temp_dir().join(format!("pigment-export-alpha-{}", std::process::id()));
        // solid: RGB base colour, no opacity / transmission maps
        let files = export(&dir, "Solid", &preset("separate").unwrap(), &tiny()).unwrap();
        assert!(!files.iter().any(|f| f.to_string_lossy().contains("Opacity")));
        let files = export(&dir, "Solid", &preset("unreal").unwrap(), &tiny()).unwrap();
        assert_eq!(files.len(), 5);
        assert_eq!(image::open(dir.join("Solid_BaseColor.png")).unwrap().color(), image::ColorType::Rgb8);
        // glass: alpha 64, transmission 255 on pixel 0
        let mut m = tiny();
        m.color[3] = 64;
        m.orm[3] = 255;
        export(&dir, "Glass", &preset("unreal").unwrap(), &m).unwrap();
        let bc = image::open(dir.join("Glass_BaseColor.png")).unwrap().to_rgba8();
        assert_eq!(bc.get_pixel(0, 0).0, [10, 20, 30, 64]);
        assert_eq!(bc.get_pixel(1, 0).0[3], 255);
        let files = export(&dir, "Glass", &preset("separate").unwrap(), &m).unwrap();
        assert!(files.iter().any(|f| f.ends_with("Glass_Opacity.png")));
        assert_eq!(image::open(dir.join("Glass_Opacity.png")).unwrap().to_luma8().get_pixel(0, 0).0, [64]);
        assert_eq!(image::open(dir.join("Glass_Transmission.png")).unwrap().to_luma8().get_pixel(0, 0).0, [255]);
        // re-exporting as solid removes the stale maps
        export(&dir, "Glass", &preset("separate").unwrap(), &tiny()).unwrap();
        assert!(!dir.join("Glass_Opacity.png").exists());
        assert!(!dir.join("Glass_Transmission.png").exists());
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
