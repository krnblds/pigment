//! Project folders: `<name>.pigment/`.
//!
//! ```text
//! project.json                 document (pretty JSON, stable ids)
//! mesh/<file>                  copy of the source mesh
//! layers/<res>/<channel>.png   paint layer pixels; a channel nobody painted has no file
//! masks/<res>.png              mask pixels
//! ```
//!
//! Everything is lossless PNG or text, so the folder diffs and commits
//! cleanly. Pixel files are only rewritten for resources marked dirty, and
//! files for resources no longer referenced are removed on save.

use crate::document::{Document, ResId, FORMAT_VERSION};
use anyhow::{bail, Context, Result};
use image::ExtendedColorType as C;
use std::path::{Path, PathBuf};

pub const MANIFEST: &str = "project.json";
pub const EXTENSION: &str = "pigment";

/// CPU copy of a paint layer's pixels, `size × size`, two values per texel
/// for scalar channels (value, coverage).
#[derive(Clone, Debug, PartialEq)]
pub struct LayerPixels {
    pub size: u32,
    /// RGBA8: sRGB colour + coverage.
    pub color: Vec<u8>,
    /// RG8: value + coverage.
    pub roughness: Vec<u8>,
    pub metallic: Vec<u8>,
    /// RG16: height mapped -1..1 -> 0..65535, + coverage.
    pub height: Vec<u16>,
    /// RGBA8: encoded tangent normal + coverage.
    pub normal: Vec<u8>,
    /// RGBA16: linear emission / 16 (so 0..16 fits), + coverage.
    pub emissive: Vec<u16>,
    /// RG8: opacity (alpha) + coverage.
    pub opacity: Vec<u8>,
    /// RG8: transmission + coverage.
    pub transmission: Vec<u8>,
    /// RG8: clearcoat weight + coverage.
    pub coat: Vec<u8>,
    /// RG8: clearcoat roughness + coverage.
    pub coat_roughness: Vec<u8>,
    /// RG8: metallic flake + coverage.
    pub flake: Vec<u8>,
}

impl LayerPixels {
    pub fn empty(size: u32) -> Self {
        let n = (size * size) as usize;
        // height value slots hold the neutral code (32768 = 0.0) so an empty layer
        // round-trips exactly through the GPU's float format
        let height = (0..n).flat_map(|_| [32768u16, 0]).collect();
        Self { size, color: vec![0; n * 4], roughness: vec![0; n * 2], metallic: vec![0; n * 2], height, normal: vec![0; n * 4], emissive: vec![0; n * 4], opacity: vec![0; n * 2], transmission: vec![0; n * 2], coat: vec![0; n * 2], coat_roughness: vec![0; n * 2], flake: vec![0; n * 2] }
    }
}

pub fn save_manifest(dir: &Path, doc: &Document) -> Result<()> {
    std::fs::create_dir_all(dir)?;
    let mut json = serde_json::to_string_pretty(doc)?;
    json.push('\n');
    let path = dir.join(MANIFEST);
    // Write-then-rename so a crash mid-save never leaves a truncated manifest.
    let tmp = dir.join(format!("{MANIFEST}.tmp"));
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, &path).with_context(|| format!("writing {}", path.display()))?;
    Ok(())
}

pub fn load_manifest(dir: &Path) -> Result<Document> {
    let path = dir.join(MANIFEST);
    let text = std::fs::read_to_string(&path).with_context(|| format!("reading {}", path.display()))?;
    let doc: Document = serde_json::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
    if doc.format > FORMAT_VERSION {
        bail!("this project was saved by a newer Pigment (format {}), please update", doc.format);
    }
    // Future format migrations go here.
    Ok(doc)
}

pub fn layer_dir(dir: &Path, res: ResId) -> PathBuf {
    dir.join("layers").join(res.to_string())
}

pub fn mask_path(dir: &Path, res: ResId) -> PathBuf {
    dir.join("masks").join(format!("{res}.png"))
}

fn any_coverage_rg8(v: &[u8]) -> bool {
    v.chunks_exact(2).any(|p| p[1] != 0)
}

fn pixel_count(size: u32) -> Result<usize> {
    if size == 0 {
        bail!("pixel dimensions must be nonzero");
    }
    (size as usize).checked_mul(size as usize).context("pixel dimensions overflow")
}

fn validate_channel(name: &str, actual: usize, pixels: usize, components: usize) -> Result<()> {
    let expected = pixels.checked_mul(components).context("channel dimensions overflow")?;
    if actual != expected {
        bail!("{name}: expected {expected} samples, got {actual}");
    }
    Ok(())
}

/// Encode completely before replacing an existing pixel file.
fn save_png(path: &Path, bytes: &[u8], size: u32, color: C) -> Result<()> {
    let tmp = path.with_extension("png.tmp");
    let result: Result<()> = (|| {
        image::save_buffer_with_format(&tmp, bytes, size, size, color, image::ImageFormat::Png)?;
        std::fs::rename(&tmp, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    result.with_context(|| format!("writing {}", path.display()))
}

pub fn write_layer(dir: &Path, res: ResId, px: &LayerPixels) -> Result<()> {
    // Validate every channel before writing or deleting any saved pixels.
    let n = pixel_count(px.size)?;
    for (name, actual, components) in [
        ("base_color", px.color.len(), 4),
        ("roughness", px.roughness.len(), 2),
        ("metallic", px.metallic.len(), 2),
        ("height", px.height.len(), 2),
        ("normal", px.normal.len(), 4),
        ("emissive", px.emissive.len(), 4),
        ("opacity", px.opacity.len(), 2),
        ("transmission", px.transmission.len(), 2),
        ("coat", px.coat.len(), 2),
        ("coat_roughness", px.coat_roughness.len(), 2),
        ("flake", px.flake.len(), 2),
    ] {
        validate_channel(name, actual, n, components)?;
    }

    let d = layer_dir(dir, res);
    std::fs::create_dir_all(&d)?;
    let s = px.size;
    let put = |name: &str, used: bool, bytes: &[u8], color: C| -> Result<()> {
        let path = d.join(name);
        if used {
            save_png(&path, bytes, s, color)?;
        } else if path.exists() {
            std::fs::remove_file(&path)?;
        }
        Ok(())
    };
    // the channel PNGs encode in parallel (4K layers save several times faster)
    std::thread::scope(|sc| {
        let jobs = [
            sc.spawn(|| put("base_color.png", px.color.chunks_exact(4).any(|p| p[3] != 0), &px.color, C::Rgba8)),
            sc.spawn(|| put("roughness.png", any_coverage_rg8(&px.roughness), &px.roughness, C::La8)),
            sc.spawn(|| put("metallic.png", any_coverage_rg8(&px.metallic), &px.metallic, C::La8)),
            sc.spawn(|| put("height.png", px.height.chunks_exact(2).any(|p| p[1] != 0), bytemuck::cast_slice(&px.height), C::La16)),
            sc.spawn(|| put("normal.png", px.normal.chunks_exact(4).any(|p| p[3] != 0), &px.normal, C::Rgba8)),
            sc.spawn(|| put("emissive.png", px.emissive.chunks_exact(4).any(|p| p[3] != 0), bytemuck::cast_slice(&px.emissive), C::Rgba16)),
            sc.spawn(|| put("opacity.png", any_coverage_rg8(&px.opacity), &px.opacity, C::La8)),
            sc.spawn(|| put("transmission.png", any_coverage_rg8(&px.transmission), &px.transmission, C::La8)),
            sc.spawn(|| put("coat.png", any_coverage_rg8(&px.coat), &px.coat, C::La8)),
            sc.spawn(|| put("coat_roughness.png", any_coverage_rg8(&px.coat_roughness), &px.coat_roughness, C::La8)),
            sc.spawn(|| put("flake.png", any_coverage_rg8(&px.flake), &px.flake, C::La8)),
        ];
        jobs.into_iter().try_for_each(|j| j.join().unwrap_or_else(|_| Err(anyhow::anyhow!("layer save thread panicked"))))
    })
}

fn open_resized(path: &Path, size: u32) -> Result<Option<image::DynamicImage>> {
    if !path.exists() {
        return Ok(None);
    }
    let img = image::open(path).with_context(|| format!("reading {}", path.display()))?;
    Ok(Some(if img.width() != size || img.height() != size {
        img.resize_exact(size, size, image::imageops::FilterType::Triangle)
    } else {
        img
    }))
}

/// Read a layer; missing channel files are empty (fully transparent).
/// Images of a different size are resampled to `size`.
pub fn read_layer(dir: &Path, res: ResId, size: u32) -> Result<LayerPixels> {
    let d = layer_dir(dir, res);
    let mut px = LayerPixels::empty(size);
    if let Some(i) = open_resized(&d.join("base_color.png"), size)? {
        px.color = i.to_rgba8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("roughness.png"), size)? {
        px.roughness = i.to_luma_alpha8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("metallic.png"), size)? {
        px.metallic = i.to_luma_alpha8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("height.png"), size)? {
        px.height = i.to_luma_alpha16().into_raw();
    }
    if let Some(i) = open_resized(&d.join("normal.png"), size)? {
        px.normal = i.to_rgba8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("emissive.png"), size)? {
        px.emissive = i.to_rgba16().into_raw();
    }
    if let Some(i) = open_resized(&d.join("opacity.png"), size)? {
        px.opacity = i.to_luma_alpha8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("transmission.png"), size)? {
        px.transmission = i.to_luma_alpha8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("coat.png"), size)? {
        px.coat = i.to_luma_alpha8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("coat_roughness.png"), size)? {
        px.coat_roughness = i.to_luma_alpha8().into_raw();
    }
    if let Some(i) = open_resized(&d.join("flake.png"), size)? {
        px.flake = i.to_luma_alpha8().into_raw();
    }
    Ok(px)
}

pub fn write_mask(dir: &Path, res: ResId, size: u32, px: &[u8]) -> Result<()> {
    validate_channel("mask", px.len(), pixel_count(size)?, 1)?;
    let path = mask_path(dir, res);
    std::fs::create_dir_all(path.parent().unwrap())?;
    save_png(&path, px, size, C::L8)
}

pub fn read_mask(dir: &Path, res: ResId, size: u32) -> Result<Option<Vec<u8>>> {
    Ok(open_resized(&mask_path(dir, res), size)?.map(|i| i.to_luma8().into_raw()))
}

/// Delete pixel files of resources the document no longer uses.
pub fn prune(dir: &Path, doc: &Document) -> Result<()> {
    let live: std::collections::HashSet<String> = doc.resources().iter().map(|r| r.to_string()).collect();
    if let Ok(rd) = std::fs::read_dir(dir.join("layers")) {
        for e in rd.flatten() {
            if !live.contains(&e.file_name().to_string_lossy().to_string()) {
                std::fs::remove_dir_all(e.path())?;
            }
        }
    }
    if let Ok(rd) = std::fs::read_dir(dir.join("masks")) {
        for e in rd.flatten() {
            let p = e.path();
            let stem = p.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
            if !live.contains(&stem) {
                std::fs::remove_file(p)?;
            }
        }
    }
    Ok(())
}

/// Copy a mesh (and, for `.gltf`, its relative buffer/image files) into
/// `<dir>/mesh/`. Returns the path relative to the project folder.
pub fn copy_mesh(dir: &Path, src: &Path) -> Result<String> {
    let mesh_dir = dir.join("mesh");
    std::fs::create_dir_all(&mesh_dir)?;
    let name = src.file_name().context("mesh path has no file name")?;
    let dst = mesh_dir.join(name);
    if src.canonicalize().ok() != dst.canonicalize().ok() {
        std::fs::copy(src, &dst).with_context(|| format!("copying {}", src.display()))?;
        // OBJ materials (texture sets, ID bakes): the .mtl files it names
        if src.extension().is_some_and(|e| e.eq_ignore_ascii_case("obj")) {
            let src_dir = src.parent().unwrap_or(Path::new("."));
            for line in std::fs::read_to_string(src).unwrap_or_default().lines().filter(|l| l.starts_with("mtllib ")) {
                let mtl = line[7..].trim();
                let from = src_dir.join(mtl);
                if from.is_file() {
                    std::fs::copy(&from, mesh_dir.join(mtl)).with_context(|| format!("copying {}", from.display()))?;
                }
            }
        }
        if src.extension().is_some_and(|e| e.eq_ignore_ascii_case("gltf")) {
            let json: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(src)?)?;
            let src_dir = src.parent().unwrap_or(Path::new("."));
            for key in ["buffers", "images"] {
                for item in json.get(key).and_then(|v| v.as_array()).into_iter().flatten() {
                    if let Some(uri) = item.get("uri").and_then(|u| u.as_str()) {
                        if !uri.starts_with("data:") && !uri.contains("://") {
                            let from = src_dir.join(uri);
                            let to = mesh_dir.join(uri);
                            if let Some(p) = to.parent() {
                                std::fs::create_dir_all(p)?;
                            }
                            std::fs::copy(&from, &to).with_context(|| format!("copying {}", from.display()))?;
                        }
                    }
                }
            }
        }
    }
    Ok(format!("mesh/{}", name.to_string_lossy()))
}

/// The project folder's `.gitignore`, written on first save.
pub fn write_gitignore(dir: &Path) -> Result<()> {
    let p = dir.join(".gitignore");
    if !p.exists() {
        std::fs::write(p, "# Pigment project: everything here is source, except temp files.\n*.tmp\n")?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::document::{Document, Mask};

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pigment-proj-{}-{name}", std::process::id()));
        std::fs::remove_dir_all(&d).ok();
        d
    }

    #[test]
    fn manifest_round_trip() {
        let dir = tmp("manifest");
        let mut doc = Document::new_default();
        doc.mesh = "mesh/x.obj".into();
        save_manifest(&dir, &doc).unwrap();
        assert_eq!(load_manifest(&dir).unwrap(), doc);
        // stable output: saving twice gives identical bytes
        let a = std::fs::read(dir.join(MANIFEST)).unwrap();
        save_manifest(&dir, &doc).unwrap();
        assert_eq!(a, std::fs::read(dir.join(MANIFEST)).unwrap());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn newer_format_is_rejected() {
        let dir = tmp("newer");
        let mut doc = Document::new_default();
        doc.format = FORMAT_VERSION + 1;
        save_manifest(&dir, &doc).unwrap();
        assert!(load_manifest(&dir).is_err());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn layer_pixels_round_trip_and_skip_empty_channels() {
        let dir = tmp("layer");
        let mut px = LayerPixels::empty(4);
        px.color[0..4].copy_from_slice(&[255, 10, 20, 200]);
        px.height[0] = 50000;
        px.height[1] = 65535;
        assert_eq!(LayerPixels::empty(1).height, vec![32768, 0]);
        write_layer(&dir, 7, &px).unwrap();
        assert!(layer_dir(&dir, 7).join("base_color.png").exists());
        assert!(layer_dir(&dir, 7).join("height.png").exists());
        assert!(!layer_dir(&dir, 7).join("roughness.png").exists());
        assert_eq!(read_layer(&dir, 7, 4).unwrap(), px);
        // resampled when the project resolution changed
        assert_eq!(read_layer(&dir, 7, 8).unwrap().size, 8);
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn invalid_layer_preserves_all_saved_channels() {
        let dir = tmp("invalid-layer");
        let mut original = LayerPixels::empty(2);
        original.color.fill(255);
        original.flake.fill(128);
        write_layer(&dir, 1, &original).unwrap();
        let mut invalid = LayerPixels::empty(2);
        // An empty color channel would delete saved paint if validation were late.
        invalid.flake.pop();
        assert!(write_layer(&dir, 1, &invalid).unwrap_err().to_string().contains("flake"));
        assert_eq!(read_layer(&dir, 1, 2).unwrap(), original);
        assert!(write_layer(&dir, 1, &LayerPixels::empty(0)).is_err());
        assert_eq!(read_layer(&dir, 1, 2).unwrap(), original);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn invalid_mask_preserves_saved_pixels_and_valid_save_replaces_them() {
        let dir = tmp("invalid-mask");
        write_mask(&dir, 1, 2, &[1, 2, 3, 4]).unwrap();
        for pixels in [&[9, 9, 9][..], &[9, 9, 9, 9, 9][..]] {
            assert!(write_mask(&dir, 1, 2, pixels).is_err());
            assert_eq!(read_mask(&dir, 1, 2).unwrap().unwrap(), [1, 2, 3, 4]);
        }
        assert!(write_mask(&dir, 1, 0, &[]).is_err());
        write_mask(&dir, 1, 2, &[4, 3, 2, 1]).unwrap();
        assert_eq!(read_mask(&dir, 1, 2).unwrap().unwrap(), [4, 3, 2, 1]);
        assert!(!mask_path(&dir, 1).with_extension("png.tmp").exists());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn masks_round_trip_and_prune() {
        let dir = tmp("mask");
        let mut doc = Document::new_default();
        let res = doc.mint();
        doc.layers[1].mask = Some(Mask { res, generator: None, invert: false, enabled: true, parts: Vec::new(), effects: Vec::new(), filters: Vec::new(), id_color: None });
        let px: Vec<u8> = (0..16).map(|i| i * 16).collect();
        write_mask(&dir, res, 4, &px).unwrap();
        write_mask(&dir, 999, 4, &px).unwrap();
        write_layer(&dir, 998, &LayerPixels::empty(4)).unwrap();
        assert_eq!(read_mask(&dir, res, 4).unwrap().unwrap(), px);
        prune(&dir, &doc).unwrap();
        assert!(mask_path(&dir, res).exists());
        assert!(!mask_path(&dir, 999).exists());
        assert!(!layer_dir(&dir, 998).exists());
        std::fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn gltf_copy_brings_its_buffers() {
        let src = tmp("gltf-src");
        std::fs::create_dir_all(&src).unwrap();
        std::fs::write(src.join("a.gltf"), r#"{"buffers":[{"uri":"a.bin","byteLength":1}]}"#).unwrap();
        std::fs::write(src.join("a.bin"), [0u8]).unwrap();
        let dir = tmp("gltf-dst");
        assert_eq!(copy_mesh(&dir, &src.join("a.gltf")).unwrap(), "mesh/a.gltf");
        assert!(dir.join("mesh/a.bin").exists());
        std::fs::remove_dir_all(src).ok();
        std::fs::remove_dir_all(dir).ok();
    }
}
