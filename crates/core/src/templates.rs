//! Custom export templates: outputs -> file name pattern -> per-channel
//! sources, with bit depth (8 / 16-bit PNG, 8-bit TGA, f16 / f32 EXR),
//! colour space and padding. The built-in templates cover the old presets
//! plus ORM, Unreal packed, Unity HDRP mask map, Godot ORM, glTF and an
//! Arnold aiStandardSurface set. Users save their own as JSON, either in the
//! user prefs (`export_templates.json`) or alongside the project
//! (`Document::export_templates`).
//!
//! Channel sources are strings:
//! `base_color.r|g|b`, `opacity` (also `base_color.a`), `roughness`,
//! `smoothness`, `metallic`, `ao`, `height`, `normal.x|y|z` (OpenGL),
//! `normal_dx.x|y|z` (DirectX, green flipped), `emissive.r|g|b`,
//! `transmission`, `coat`, `coat_roughness`, `flake`, `const:<value>`,
//! with a `1-` prefix to invert. In float (EXR) outputs, `height` and
//! `emissive` keep their HDR range (raw height, linear emission x strength).

use crate::export::MaterialImages;
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FileFormat {
    Png,
    Tga,
    Exr,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BitDepth {
    U8,
    U16,
    F16,
    F32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ColorSpace {
    /// Base colour and emission as painted (sRGB-encoded); data maps are linear anyway.
    #[default]
    Srgb,
    /// Base colour and emission converted to linear.
    Linear,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Padding {
    /// Seam padding: texels outside the UV islands repeat the nearest island texel.
    #[default]
    Dilate,
    /// Outside the UV islands: zero (and alpha 0).
    None,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TemplateOutput {
    /// File name without extension; tokens `{name}`, `{set}`, `{udim}`.
    pub pattern: String,
    /// 1 (grey), 3 (RGB) or 4 (RGBA) channel sources.
    pub channels: Vec<String>,
    pub format: FileFormat,
    pub bit_depth: BitDepth,
    #[serde(default)]
    pub color_space: ColorSpace,
    #[serde(default)]
    pub padding: Padding,
    /// Skip the file when every channel is neutral (opacity / transmission / coat of a material without any).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub skip_if_neutral: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportTemplate {
    pub id: String,
    #[serde(default)]
    pub label: String,
    pub outputs: Vec<TemplateOutput>,
}

/// Where a channel's value comes from.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Src {
    BaseColor(usize),
    Opacity,
    Roughness,
    Smoothness,
    Metallic,
    Ao,
    Height,
    Normal(usize),
    NormalDx(usize),
    Emissive(usize),
    Transmission,
    Coat,
    CoatRoughness,
    Flake,
    Const(f32),
}

/// A parsed channel source.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Chan {
    pub src: Src,
    pub invert: bool,
}

fn comp(s: &str) -> Option<usize> {
    match s {
        "r" | "x" => Some(0),
        "g" | "y" => Some(1),
        "b" | "z" => Some(2),
        "a" | "w" => Some(3),
        _ => None,
    }
}

/// Parse a channel source string (see the module docs).
pub fn parse_chan(s: &str) -> Result<Chan, String> {
    let t = s.trim().to_ascii_lowercase();
    let (invert, t) = match t.strip_prefix("1-") {
        Some(rest) => (true, rest.trim().to_string()),
        None => (false, t),
    };
    if let Some(v) = t.strip_prefix("const:") {
        let v: f32 = v.trim().parse().map_err(|_| format!("`{s}`: const needs a number, e.g. const:0.5"))?;
        return Ok(Chan { src: Src::Const(v), invert });
    }
    let (map, c) = match t.split_once('.') {
        Some((m, c)) => (m.to_string(), Some(comp(c).ok_or_else(|| format!("`{s}`: component must be r, g, b or a (x, y, z)"))?)),
        None => (t.clone(), None),
    };
    let need = |c: Option<usize>, max: usize| -> Result<usize, String> {
        match c {
            Some(c) if c < max => Ok(c),
            Some(_) => Err(format!("`{s}`: component out of range")),
            None => Err(format!("`{s}`: say which component, e.g. {map}.r")),
        }
    };
    let src = match map.as_str() {
        "base_color" | "basecolor" | "albedo" | "color" => match c {
            Some(3) => Src::Opacity,
            c => Src::BaseColor(need(c, 3)?),
        },
        "opacity" | "alpha" => Src::Opacity,
        "roughness" => Src::Roughness,
        "smoothness" | "gloss" | "glossiness" => Src::Smoothness,
        "metallic" | "metalness" => Src::Metallic,
        "ao" | "occlusion" | "ambient_occlusion" => Src::Ao,
        "height" | "displacement" => Src::Height,
        "normal" | "normal_gl" | "normal_opengl" => Src::Normal(need(c, 3)?),
        "normal_dx" | "normal_directx" => Src::NormalDx(need(c, 3)?),
        "emissive" | "emission" => Src::Emissive(need(c, 3)?),
        "transmission" => Src::Transmission,
        "coat" | "clearcoat" => Src::Coat,
        "coat_roughness" => Src::CoatRoughness,
        "flake" => Src::Flake,
        _ => return Err(format!("`{s}`: unknown source (base_color.r/g/b, opacity, roughness, smoothness, metallic, ao, height, normal.x/y/z, normal_dx.x/y/z, emissive.r/g/b, transmission, coat, coat_roughness, flake, const:<v>; prefix 1- to invert)")),
    };
    Ok(Chan { src, invert })
}

impl TemplateOutput {
    fn new(pattern: &str, channels: &[&str], format: FileFormat, bit_depth: BitDepth) -> Self {
        TemplateOutput { pattern: pattern.into(), channels: channels.iter().map(|c| c.to_string()).collect(), format, bit_depth, color_space: ColorSpace::Srgb, padding: Padding::Dilate, skip_if_neutral: false }
    }
    fn linear(mut self) -> Self {
        self.color_space = ColorSpace::Linear;
        self
    }
    fn optional(mut self) -> Self {
        self.skip_if_neutral = true;
        self
    }
    pub fn extension(&self) -> &'static str {
        match self.format {
            FileFormat::Png => "png",
            FileFormat::Tga => "tga",
            FileFormat::Exr => "exr",
        }
    }
    pub fn is_float(&self) -> bool {
        matches!(self.bit_depth, BitDepth::F16 | BitDepth::F32)
    }
    /// The file name for these token values.
    pub fn file_name(&self, name: &str, set: &str, udim: u32) -> String {
        format!("{}.{}", self.pattern.replace("{name}", name).replace("{set}", set).replace("{udim}", &udim.to_string()), self.extension())
    }
    pub fn validate(&self) -> Result<Vec<Chan>, String> {
        if self.pattern.trim().is_empty() {
            return Err("an output needs a file name `pattern`".into());
        }
        if self.pattern.contains(['/', '\\', ':']) {
            return Err(format!("`{}`: the pattern is a file name, not a path", self.pattern));
        }
        let ok = match self.format {
            FileFormat::Png => matches!(self.bit_depth, BitDepth::U8 | BitDepth::U16),
            FileFormat::Tga => self.bit_depth == BitDepth::U8,
            FileFormat::Exr => matches!(self.bit_depth, BitDepth::F16 | BitDepth::F32),
        };
        if !ok {
            return Err(format!("`{}`: {:?} can't store {:?} (PNG: u8 / u16, TGA: u8, EXR: f16 / f32)", self.pattern, self.format, self.bit_depth));
        }
        if ![1, 3, 4].contains(&self.channels.len()) {
            return Err(format!("`{}`: give 1 (grey), 3 (RGB) or 4 (RGBA) channels, got {}", self.pattern, self.channels.len()));
        }
        self.channels.iter().map(|c| parse_chan(c)).collect()
    }
}

impl ExportTemplate {
    pub fn validate(&self) -> Result<(), String> {
        if self.id.trim().is_empty() {
            return Err("a template needs an `id`".into());
        }
        if self.outputs.is_empty() {
            return Err(format!("template `{}` has no outputs", self.id));
        }
        let mut names = std::collections::HashSet::new();
        for o in &self.outputs {
            o.validate()?;
            if !names.insert(o.file_name("x", "s", 1001)) {
                return Err(format!("template `{}`: two outputs write `{}`", self.id, o.pattern));
            }
        }
        Ok(())
    }
    /// Does any output need the float (HDR) planes or the coverage mask?
    pub fn needs_hdr(&self) -> bool {
        self.outputs.iter().any(|o| o.is_float() || o.padding == Padding::None)
    }
}

/// Built-in templates: the old presets (same files) and engine-specific packs.
pub fn builtin() -> Vec<ExportTemplate> {
    use BitDepth::*;
    use FileFormat::*;
    let t = |id: &str, label: &str, outputs: Vec<TemplateOutput>| ExportTemplate { id: id.into(), label: label.into(), outputs };
    let o = TemplateOutput::new;
    vec![
        t("unreal", "Unreal Engine (packed ORM, DirectX normal)", vec![
            o("{name}_BaseColor", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_Normal", &["normal_dx.x", "normal_dx.y", "normal_dx.z"], Png, U8),
            o("{name}_OcclusionRoughnessMetallic", &["ao", "roughness", "metallic"], Png, U8),
            o("{name}_Height", &["height"], Png, U16),
            o("{name}_Emissive", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
        ]),
        t("unity", "Unity (URP / Built-in metallic)", vec![
            o("{name}_Albedo", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_Normal", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_MetallicSmoothness", &["metallic", "metallic", "metallic", "smoothness"], Png, U8),
            o("{name}_Occlusion", &["ao"], Png, U8),
            o("{name}_Height", &["height"], Png, U16),
            o("{name}_Emission", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
        ]),
        t("godot", "Godot (ORM material)", vec![
            o("{name}_albedo", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_normal", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_orm", &["ao", "roughness", "metallic"], Png, U8),
            o("{name}_height", &["height"], Png, U16),
            o("{name}_emission", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
        ]),
        t("separate", "Separate maps (glTF / generic)", vec![
            o("{name}_BaseColor", &["base_color.r", "base_color.g", "base_color.b"], Png, U8),
            o("{name}_Roughness", &["roughness"], Png, U8),
            o("{name}_Metallic", &["metallic"], Png, U8),
            o("{name}_AO", &["ao"], Png, U8),
            o("{name}_Normal_OpenGL", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_Height", &["height"], Png, U16),
            o("{name}_Emissive", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
            o("{name}_Opacity", &["opacity"], Png, U8).optional(),
            o("{name}_Transmission", &["transmission"], Png, U8).optional(),
            o("{name}_Coat", &["coat"], Png, U8).optional(),
            o("{name}_CoatRoughness", &["coat_roughness"], Png, U8).optional(),
            o("{name}_Flake", &["flake"], Png, U8).optional(),
        ]),
        t("orm", "ORM packed (occlusion, roughness, metallic) + OpenGL normal", vec![
            o("{name}_BaseColor", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_ORM", &["ao", "roughness", "metallic"], Png, U8),
            o("{name}_Normal", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_Emissive", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
        ]),
        t("unreal_packed", "Unreal packed (BaseColor + opacity, ORM + height in alpha, DirectX normal)", vec![
            o("T_{name}_BC", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("T_{name}_ORMH", &["ao", "roughness", "metallic", "height"], Png, U8),
            o("T_{name}_N", &["normal_dx.x", "normal_dx.y", "normal_dx.z"], Png, U8),
            o("T_{name}_E", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
        ]),
        t("unity_hdrp", "Unity HDRP (Lit: Mask Map = metallic, AO, detail mask, smoothness)", vec![
            o("{name}_BaseMap", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_MaskMap", &["metallic", "ao", "const:1", "smoothness"], Png, U8),
            o("{name}_Normal", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_Height", &["height"], Png, U16),
            o("{name}_Emissive", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
        ]),
        t("godot_orm", "Godot 4 ORMMaterial3D (albedo, ORM, normal, emission, height)", vec![
            o("{name}_albedo", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_orm", &["ao", "roughness", "metallic"], Png, U8),
            o("{name}_normal", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_emission", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
            o("{name}_height", &["height"], Png, U16),
        ]),
        t("gltf", "glTF 2.0 (baseColor, occlusionRoughnessMetallic, normal, emissive)", vec![
            o("{name}_baseColor", &["base_color.r", "base_color.g", "base_color.b", "opacity"], Png, U8),
            o("{name}_occlusionRoughnessMetallic", &["ao", "roughness", "metallic"], Png, U8),
            o("{name}_normal", &["normal.x", "normal.y", "normal.z"], Png, U8),
            o("{name}_emissive", &["emissive.r", "emissive.g", "emissive.b"], Png, U8),
            o("{name}_transmission", &["transmission"], Png, U8).optional(),
            o("{name}_clearcoat", &["coat", "coat_roughness", "flake"], Png, U8).optional(),
        ]),
        t("arnold", "Arnold aiStandardSurface (linear EXR: HDR emission and height, f16 data maps)", vec![
            o("{name}_baseColor", &["base_color.r", "base_color.g", "base_color.b"], Exr, F16).linear(),
            o("{name}_specularRoughness", &["roughness"], Exr, F16),
            o("{name}_metalness", &["metallic"], Exr, F16),
            o("{name}_normal", &["normal.x", "normal.y", "normal.z"], Exr, F16),
            o("{name}_height", &["height"], Exr, F32),
            o("{name}_emission", &["emissive.r", "emissive.g", "emissive.b"], Exr, F16).linear(),
            o("{name}_opacity", &["opacity"], Exr, F16).optional(),
            o("{name}_transmission", &["transmission"], Exr, F16).optional(),
            o("{name}_coat", &["coat"], Exr, F16).optional(),
        ]),
    ]
}

/// User templates file (in the prefs folder).
pub const USER_FILE: &str = "export_templates.json";

pub fn load_user(dir: &Path) -> Vec<ExportTemplate> {
    std::fs::read_to_string(dir.join(USER_FILE)).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default()
}

pub fn save_user(dir: &Path, list: &[ExportTemplate]) -> Result<()> {
    std::fs::create_dir_all(dir)?;
    std::fs::write(dir.join(USER_FILE), serde_json::to_string_pretty(list)?)?;
    Ok(())
}

/// Float planes for EXR outputs and the island coverage for `padding: none`.
pub struct HdrPlanes {
    /// Raw composited height (HDR, 0 = neutral).
    pub height: Vec<f32>,
    /// Linear emission x strength, RGB.
    pub emissive: Vec<f32>,
    /// 1 inside a UV island, 0 in the padding.
    pub coverage: Vec<u8>,
}

fn srgb_to_linear(v: f32) -> f32 {
    crate::blend::srgb_to_linear(v)
}

/// One channel's value at texel `i` (0..1 for integer outputs; HDR height /
/// emission in float outputs when `hdr` is given).
pub fn value(m: &MaterialImages, hdr: Option<&HdrPlanes>, c: Chan, i: usize, linear: bool, float: bool) -> f32 {
    let b = |v: u8| v as f32 / 255.0;
    let coat = |k: usize| if m.coat.is_empty() { [0.0, crate::export::NEUTRAL_COAT_ROUGHNESS as f32 / 255.0, 0.0][k] } else { b(m.coat[4 * i + k]) };
    let v = match c.src {
        Src::BaseColor(k) => {
            let v = b(m.color[4 * i + k]);
            if linear {
                srgb_to_linear(v)
            } else {
                v
            }
        }
        Src::Opacity => b(m.color[4 * i + 3]),
        Src::Roughness => b(m.orm[4 * i + 1]),
        Src::Smoothness => 1.0 - b(m.orm[4 * i + 1]),
        Src::Metallic => b(m.orm[4 * i + 2]),
        Src::Ao => b(m.orm[4 * i]),
        Src::Transmission => b(m.orm[4 * i + 3]),
        Src::Height => match (float, hdr) {
            (true, Some(h)) => h.height[i],
            _ => m.height[i] as f32 / 65535.0,
        },
        Src::Normal(k) => b(m.normal[4 * i + k]),
        Src::NormalDx(k) => {
            let v = b(m.normal[4 * i + k]);
            if k == 1 {
                1.0 - v
            } else {
                v
            }
        }
        Src::Emissive(k) => match (float, hdr) {
            // linear HDR; sRGB-encoded only if asked (values above 1 kept)
            (true, Some(h)) => {
                let v = h.emissive[3 * i + k];
                if linear || v > 1.0 {
                    v
                } else {
                    crate::blend::linear_to_srgb(v.max(0.0))
                }
            }
            _ => {
                let v = b(m.emissive[4 * i + k]);
                if linear {
                    srgb_to_linear(v)
                } else {
                    v
                }
            }
        },
        Src::Coat => coat(0),
        Src::CoatRoughness => coat(1),
        Src::Flake => coat(2),
        Src::Const(v) => v,
    };
    if c.invert {
        if matches!(c.src, Src::Height) && float {
            -v
        } else {
            1.0 - v
        }
    } else {
        v
    }
}

/// Is every channel neutral (the optional maps of a material without them)?
fn all_neutral(m: &MaterialImages, chans: &[Chan]) -> bool {
    let n = (m.size * m.size) as usize;
    chans.iter().all(|c| {
        let neutral = match c.src {
            Src::Opacity => 1.0,
            Src::Transmission | Src::Coat | Src::Flake => 0.0,
            Src::CoatRoughness => crate::export::NEUTRAL_COAT_ROUGHNESS as f32 / 255.0,
            _ => return false,
        };
        (0..n).all(|i| (value(m, None, *c, i, false, false) - neutral).abs() < 1e-6)
    })
}

/// Write one output; Ok(None) when skipped (neutral optional map).
pub fn write_output(dir: &Path, file: &str, o: &TemplateOutput, m: &MaterialImages, hdr: Option<&HdrPlanes>, compression: crate::export::Compression) -> Result<Option<PathBuf>> {
    let chans = o.validate().map_err(anyhow::Error::msg)?;
    let path = dir.join(file);
    if o.skip_if_neutral && all_neutral(m, &chans) {
        if path.exists() {
            std::fs::remove_file(&path)?;
        }
        return Ok(None);
    }
    let n = (m.size * m.size) as usize;
    let ch = chans.len();
    let linear = o.color_space == ColorSpace::Linear;
    let float = o.is_float();
    let covered = |i: usize| o.padding == Padding::Dilate || hdr.is_none_or(|h| h.coverage.get(i).copied().unwrap_or(1) != 0);
    let mut px = vec![0f32; n * ch];
    for i in 0..n {
        if !covered(i) {
            continue; // padding none: zero, alpha 0
        }
        for (k, c) in chans.iter().enumerate() {
            px[i * ch + k] = value(m, hdr, *c, i, linear, float);
        }
    }
    let size = m.size;
    match (o.format, o.bit_depth) {
        (FileFormat::Png, BitDepth::U8) | (FileFormat::Tga, BitDepth::U8) => {
            let bytes: Vec<u8> = px.iter().map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8).collect();
            let color = match ch {
                1 => image::ExtendedColorType::L8,
                3 => image::ExtendedColorType::Rgb8,
                _ => image::ExtendedColorType::Rgba8,
            };
            write_ldr(&path, size, &bytes, color, o.format, compression)?;
        }
        (FileFormat::Png, BitDepth::U16) => {
            let words: Vec<u16> = px.iter().map(|v| (v.clamp(0.0, 1.0) * 65535.0).round() as u16).collect();
            let color = match ch {
                1 => image::ExtendedColorType::L16,
                3 => image::ExtendedColorType::Rgb16,
                _ => image::ExtendedColorType::Rgba16,
            };
            write_ldr(&path, size, bytemuck::cast_slice(&words), color, FileFormat::Png, compression)?;
        }
        (FileFormat::Exr, d) => write_exr(&path, size, &px, ch, d == BitDepth::F16)?,
        (f, d) => bail!("{f:?} can't store {d:?}"),
    }
    Ok(Some(path))
}

fn write_ldr(path: &Path, size: u32, bytes: &[u8], color: image::ExtendedColorType, format: FileFormat, compression: crate::export::Compression) -> Result<()> {
    use image::ImageEncoder;
    let file = std::fs::File::create(path).with_context(|| format!("creating {}", path.display()))?;
    let w = std::io::BufWriter::with_capacity(1 << 20, file);
    match format {
        FileFormat::Tga => image::codecs::tga::TgaEncoder::new(w).write_image(bytes, size, size, color),
        _ => {
            let (c, f) = crate::export::png_settings(compression);
            image::codecs::png::PngEncoder::new_with_quality(w, c, f).write_image(bytes, size, size, color)
        }
    }
    .with_context(|| format!("writing {}", path.display()))
}

/// EXR via the `exr` crate: Y, RGB or RGBA channels, f16 or f32.
fn write_exr(path: &Path, size: u32, px: &[f32], ch: usize, half_float: bool) -> Result<()> {
    use exr::prelude::*;
    let names: &[&str] = match ch {
        1 => &["Y"],
        3 => &["R", "G", "B"],
        _ => &["R", "G", "B", "A"],
    };
    let n = (size * size) as usize;
    let list: Vec<AnyChannel<FlatSamples>> = names
        .iter()
        .enumerate()
        .map(|(k, name)| {
            let plane: Vec<f32> = (0..n).map(|i| px[i * ch + k]).collect();
            let samples = if half_float { FlatSamples::F16(plane.into_iter().map(half::f16::from_f32).collect()) } else { FlatSamples::F32(plane) };
            AnyChannel::new(*name, samples)
        })
        .collect();
    let channels = AnyChannels::sort(list.into_iter().collect());
    let layer = Layer::new((size as usize, size as usize), LayerAttributes::default(), Encoding::SMALL_LOSSLESS, channels);
    let image = Image::from_layer(layer);
    image.write().to_file(path).map_err(|e| anyhow::anyhow!("writing {}: {e}", path.display()))
}

/// Write every output of `t` into `dir`, in parallel. `name` / `set` / `udim` fill the pattern tokens.
pub fn export(dir: &Path, t: &ExportTemplate, m: &MaterialImages, hdr: Option<&HdrPlanes>, name: &str, set: &str, udim: u32, compression: crate::export::Compression) -> Result<Vec<PathBuf>> {
    t.validate().map_err(anyhow::Error::msg)?;
    std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
    std::thread::scope(|s| {
        let hs: Vec<_> = t.outputs.iter().map(|o| s.spawn(move || write_output(dir, &o.file_name(name, set, udim), o, m, hdr, compression))).collect();
        hs.into_iter().map(|h| h.join().unwrap_or_else(|_| Err(anyhow::anyhow!("export thread panicked")))).filter_map(Result::transpose).collect()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tiny() -> MaterialImages {
        let n = 4usize;
        MaterialImages {
            size: 2,
            color: [[255, 128, 0, 255]; 4].concat(),
            orm: [[200, 64, 255, 0]; 4].concat(),
            normal: [[128, 200, 255, 255]; 4].concat(),
            height: vec![32768; n],
            emissive: [[255, 0, 0, 255]; 4].concat(),
            emissive_scale: 5.0,
            coat: Vec::new(),
        }
    }

    /// Demo helper: dump EXR files to raw f32 (`<file>.raw`: u32 width,
    /// height, channels, then interleaved f32). Files from PIGMENT_EXR_DUMP
    /// (separated by `;`). `cargo test -p pigment-core --release exr_dump -- --ignored`
    #[test]
    #[ignore]
    fn exr_dump() {
        let Ok(list) = std::env::var("PIGMENT_EXR_DUMP") else { return };
        for f in list.split(';').filter(|f| !f.is_empty()) {
            let img = exr::prelude::read_first_flat_layer_from_file(f).unwrap();
            let size = img.layer_data.size;
            let chans = &img.layer_data.channel_data.list;
            let planes: Vec<Vec<f32>> = chans.iter().map(|c| c.sample_data.values_as_f32().collect()).collect();
            let mut out: Vec<u8> = Vec::new();
            for v in [size.0 as u32, size.1 as u32, chans.len() as u32] {
                out.extend_from_slice(&v.to_le_bytes());
            }
            for i in 0..size.0 * size.1 {
                for p in &planes {
                    out.extend_from_slice(&p[i].to_le_bytes());
                }
            }
            std::fs::write(format!("{f}.raw"), out).unwrap();
        }
    }

    #[test]
    fn channel_strings_parse() {
        assert_eq!(parse_chan("base_color.g").unwrap().src, Src::BaseColor(1));
        assert_eq!(parse_chan("base_color.a").unwrap().src, Src::Opacity);
        assert!(parse_chan("1-roughness").unwrap().invert);
        assert_eq!(parse_chan("const:0.25").unwrap().src, Src::Const(0.25));
        assert_eq!(parse_chan("normal_dx.y").unwrap().src, Src::NormalDx(1));
        assert!(parse_chan("normal").unwrap_err().contains("component"));
        assert!(parse_chan("sparkle").unwrap_err().contains("unknown"));
    }

    #[test]
    fn builtins_are_valid_and_keep_the_old_presets() {
        for t in builtin() {
            t.validate().unwrap_or_else(|e| panic!("{}: {e}", t.id));
        }
        // the old presets' files, by suffix
        for p in crate::export::presets() {
            let t = builtin().into_iter().find(|t| t.id == p.id).unwrap();
            for (o, n) in p.outputs.iter().zip(&t.outputs) {
                assert_eq!(n.file_name("X", "", 1001), format!("X_{}.png", o.suffix));
            }
        }
        for id in ["orm", "unreal_packed", "unity_hdrp", "godot_orm", "gltf", "arnold"] {
            assert!(builtin().iter().any(|t| t.id == id), "{id}");
        }
    }

    #[test]
    fn validation_names_the_problem() {
        let mut o = TemplateOutput::new("{name}_x", &["roughness"], FileFormat::Tga, BitDepth::U16);
        assert!(o.validate().unwrap_err().contains("TGA"));
        o.format = FileFormat::Png;
        o.channels = vec!["roughness".into(), "metallic".into()];
        assert!(o.validate().unwrap_err().contains("1 (grey)"));
        let t = ExportTemplate { id: "d".into(), label: String::new(), outputs: vec![TemplateOutput::new("{name}", &["ao"], FileFormat::Png, BitDepth::U8); 2] };
        assert!(t.validate().unwrap_err().contains("two outputs"));
    }

    #[test]
    fn writes_png_tga_and_hdr_exr() {
        let m = tiny();
        let hdr = HdrPlanes { height: vec![2.5; 4], emissive: [[4.0f32, 0.5, 0.0]; 4].concat(), coverage: vec![1, 1, 1, 0] };
        let dir = std::env::temp_dir().join(format!("pigment-templates-{}", std::process::id()));
        let t = ExportTemplate {
            id: "test".into(),
            label: String::new(),
            outputs: vec![
                TemplateOutput::new("{name}_{set}_ORM.{udim}", &["ao", "roughness", "metallic"], FileFormat::Png, BitDepth::U8),
                TemplateOutput::new("{name}_rough16", &["1-roughness"], FileFormat::Png, BitDepth::U16),
                TemplateOutput::new("{name}_bc", &["base_color.r", "base_color.g", "base_color.b", "opacity"], FileFormat::Tga, BitDepth::U8),
                TemplateOutput { padding: Padding::None, ..TemplateOutput::new("{name}_height", &["height"], FileFormat::Exr, BitDepth::F32) },
                TemplateOutput::new("{name}_emit", &["emissive.r", "emissive.g", "emissive.b"], FileFormat::Exr, BitDepth::F16).linear(),
                TemplateOutput::new("{name}_transmission", &["transmission"], FileFormat::Png, BitDepth::U8).optional(),
            ],
        };
        let files = export(&dir, &t, &m, Some(&hdr), "box", "lid", 1002, Default::default()).unwrap();
        assert_eq!(files.len(), 5, "the neutral transmission map is skipped: {files:?}");
        let orm = image::open(dir.join("box_lid_ORM.1002.png")).unwrap().to_rgb8();
        assert_eq!(orm.get_pixel(0, 0).0, [200, 64, 255]);
        let r16 = image::open(dir.join("box_rough16.png")).unwrap().to_luma16();
        assert_eq!(r16.get_pixel(0, 0).0[0], ((1.0 - 64.0 / 255.0) * 65535.0f32).round() as u16);
        let tga = image::open(dir.join("box_bc.tga")).unwrap().to_rgba8();
        assert_eq!(tga.get_pixel(1, 1).0, [255, 128, 0, 255]);
        // EXR keeps the HDR range; padding none zeroes the uncovered texel
        let img = exr::prelude::read_first_flat_layer_from_file(dir.join("box_height.exr")).unwrap();
        let ch = &img.layer_data.channel_data.list[0];
        assert_eq!(ch.name.to_string(), "Y");
        let y: Vec<f32> = ch.sample_data.values_as_f32().collect();
        assert!((y[0] - 2.5).abs() < 1e-5 && y[3] == 0.0, "HDR height kept, padding none zeroes uncovered texels: {y:?}");
        let e = image::open(dir.join("box_emit.exr")).unwrap().to_rgb32f();
        assert!((e.get_pixel(0, 0).0[0] - 4.0).abs() < 0.01, "HDR emission above 1: {:?}", e.get_pixel(0, 0));
        std::fs::remove_dir_all(dir).ok();
    }
}
