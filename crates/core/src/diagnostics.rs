//! CPU-only inspection and exported asset validation. These checks decode files;
//! they do not claim to have imported the material in an external game engine.
use crate::{bridge, project, Mesh};
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::path::{Component, Path, PathBuf};

pub fn local_path(root: &Path, name: &str) -> Result<PathBuf> {
    let path = Path::new(name);
    if name.is_empty()
        || path
            .components()
            .any(|c| !matches!(c, Component::Normal(_) | Component::CurDir))
    {
        bail!("expected a relative asset path inside the project: {name}");
    }
    Ok(root.join(path))
}

pub fn inspect(path: &Path) -> Result<Value> {
    if path.is_dir()
        || path.extension().is_some_and(|e| e == "pigment")
        || path.file_name().is_some_and(|n| n == project::MANIFEST)
    {
        let root = if path.file_name().is_some_and(|n| n == project::MANIFEST) {
            path.parent().unwrap()
        } else {
            path
        };
        let mut pending = vec![root.to_path_buf()];
        let mut visited = std::collections::HashSet::new();
        let mut sets = Vec::new();
        while let Some(dir) = pending.pop() {
            let doc = project::load_manifest(&dir)?;
            if !visited.insert(dir.canonicalize()?) {
                bail!("cyclic or duplicate texture set {}", dir.display());
            }
            if doc.resolution == 0 || !doc.resolution.is_power_of_two() {
                bail!("invalid resolution {}", doc.resolution);
            }
            let mesh = Mesh::load(&local_path(&dir, &doc.mesh)?)?;
            if mesh.triangle_count() == 0 || !mesh.has_uvs {
                bail!("mesh needs triangles and UVs: {}", doc.mesh);
            }
            let mut ids = std::collections::HashSet::new();
            for layer in &doc.layers {
                if !ids.insert(layer.id) {
                    bail!("duplicate layer id {}", layer.id);
                }
                if let Some(res) = layer.paint_res() {
                    let pixels = project::layer_dir(&dir, res);
                    if pixels.exists() {
                        check_images(&pixels, doc.resolution)?;
                    }
                }
                if let Some(mask) = &layer.mask {
                    let p = project::mask_path(&dir, mask.res);
                    if p.exists() {
                        check_image(&p, doc.resolution)?;
                    }
                }
                if let Some(fill) = &layer.image {
                    let bases = dir.ancestors().map(Path::to_path_buf).collect::<Vec<_>>();
                    for channel in crate::image_fill::ImageChannel::ALL {
                        if let Some(name) = fill.images.get(channel) {
                            let p = crate::image_fill::resolve_path(name, &bases)
                                .with_context(|| format!("missing image fill {name}"))?;
                            image::open(&p).with_context(|| format!("decoding {}", p.display()))?;
                        }
                    }
                }
            }
            if let Some(id) = &doc.id_map {
                check_image(&local_path(&dir, id)?, doc.resolution)?;
            }
            for extra in &doc.extra_sets {
                pending.push(local_path(&dir, extra)?);
            }
            sets.push(json!({"path":dir,"resolution":doc.resolution,"layers":doc.layers.len(),"triangles":mesh.triangle_count(),"mesh":doc.mesh}));
        }
        Ok(json!({"kind":"project","ok":true,"sets":sets}))
    } else {
        let mesh = Mesh::load(path)?;
        Ok(
            json!({"kind":"mesh","path":path,"triangles":mesh.triangle_count(),"has_uvs":mesh.has_uvs,"bounds":mesh.bounds()}),
        )
    }
}

fn check_image(path: &Path, size: u32) -> Result<()> {
    let image = image::open(path).with_context(|| format!("decoding {}", path.display()))?;
    if image.width() != size || image.height() != size {
        bail!(
            "{}: expected {size}x{size}, got {}x{}",
            path.display(),
            image.width(),
            image.height()
        );
    }
    Ok(())
}
fn check_images(dir: &Path, size: u32) -> Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let p = entry?.path();
        if p.extension().is_some_and(|e| e == "png") {
            check_image(&p, size)?;
        }
    }
    Ok(())
}

pub fn verify_export(dir: &Path, target: Option<&str>) -> Result<Value> {
    let sidecar: Value = serde_json::from_slice(&std::fs::read(dir.join(bridge::SIDECAR))?)?;
    if sidecar["format"] != bridge::SIDECAR_FORMAT || sidecar["version"] != bridge::SIDECAR_VERSION
    {
        bail!("unsupported material sidecar format/version");
    }
    let materials = sidecar["materials"]
        .as_object()
        .context("missing materials")?;
    if materials.is_empty() {
        bail!("export has no materials");
    }
    let mut checked = Vec::new();
    for (name, mat) in materials {
        let preset = mat["preset"].as_str().context("missing material preset")?;
        if let Some(target) = target {
            let expected = if target == "blender" {
                "separate"
            } else {
                target
            };
            if preset != expected {
                bail!("{name}: preset {preset} does not match target {target}");
            }
        }
        let size = mat["resolution"]
            .as_u64()
            .filter(|s| *s > 0 && *s <= u32::MAX as u64)
            .context("invalid material resolution")? as u32;
        let maps = mat["maps"].as_array().context("missing material maps")?;
        if maps.is_empty() {
            bail!("{name}: no maps");
        }
        if let Some(definition) = crate::export::preset(preset) {
            for output in definition.outputs {
                let optional = output.sources.len() == 1
                    && matches!(
                        output.sources[0],
                        crate::export::Source::Opacity
                            | crate::export::Source::Transmission
                            | crate::export::Source::Coat
                            | crate::export::Source::CoatRoughness
                            | crate::export::Source::Flake
                    );
                let map = maps.iter().find(|m| m["suffix"] == output.suffix);
                if let Some(map) = map {
                    let expected: Vec<_> = output
                        .sources
                        .iter()
                        .copied()
                        .map(bridge::source_name)
                        .collect();
                    let opaque_rgb = expected.len() == 4
                        && expected.last() == Some(&"opacity")
                        && map["sources"] == json!(&expected[..3]);
                    if map["sources"] != json!(expected) && !opaque_rgb {
                        bail!("{name}: wrong channel packing for {}", output.suffix);
                    }
                } else if !optional {
                    bail!("{name}: missing required map {}", output.suffix);
                }
            }
        }
        if !matches!(
            mat["normal_convention"].as_str(),
            Some("opengl" | "directx")
        ) {
            bail!("{name}: invalid normal convention");
        }
        for map in maps {
            let path = local_path(dir, map["file"].as_str().context("map needs file")?)?;
            check_image(&path, size)?;
            let color = image::open(&path)?.color();
            let format = match color {
                image::ColorType::L8 => "l8",
                image::ColorType::L16 => "l16",
                image::ColorType::Rgb8 => "rgb8",
                image::ColorType::Rgba8 => "rgba8",
                _ => "unsupported",
            };
            if map["format"] != format {
                bail!("{}: pixel format differs from sidecar", path.display());
            }
            let sources = map["sources"]
                .as_array()
                .context("map needs channel sources")?;
            if sources.len() != color.channel_count() as usize {
                bail!("{}: channel count differs from sidecar", path.display());
            }
            let srgb = sources.iter().any(|s| {
                matches!(
                    s.as_str(),
                    Some("red" | "green" | "blue" | "emissive_r" | "emissive_g" | "emissive_b")
                )
            });
            let expected_space = if srgb { "srgb" } else { "non-color" };
            if map["colorspace"] != expected_space {
                bail!("incorrect colorspace for {}", path.display());
            }
            if sources.iter().any(|s| s == "normal_y") && mat["normal_convention"] != "opengl" {
                bail!("{name}: inconsistent normal convention");
            }
            if sources.iter().any(|s| s == "normal_y_flipped")
                && mat["normal_convention"] != "directx"
            {
                bail!("{name}: inconsistent normal convention");
            }
            checked.push(path);
        }
        if let Some(mesh) = mat["mesh"].as_str() {
            let path = if Path::new(mesh).is_absolute() {
                PathBuf::from(mesh)
            } else {
                local_path(dir, mesh)?
            };
            let mesh = Mesh::load(&path)
                .with_context(|| format!("loading exported mesh {}", path.display()))?;
            if mesh.triangle_count() == 0 || !mesh.has_uvs {
                bail!("exported mesh has no triangles or UVs");
            }
            checked.push(path);
        }
    }
    Ok(
        json!({"ok":true,"materials":materials.len(),"files":checked,"target":target,"engine_import_tested":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_missing_textures_and_incorrect_dimensions() {
        let dir = std::env::temp_dir().join(format!("pigment-verify-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let m = crate::export::MaterialImages {
            size: 2,
            color: vec![128; 16],
            orm: vec![128; 16],
            normal: vec![128; 16],
            height: vec![32768; 4],
            emissive: vec![0; 16],
            emissive_scale: 1.0,
            coat: Vec::new(),
        };
        let preset = crate::export::preset("separate").unwrap();
        bridge::write_sidecar(&dir, "A", &preset, &m, &Default::default()).unwrap();
        assert!(verify_export(&dir, None).is_err());
        crate::export::export(&dir, "A", &preset, &m).unwrap();
        assert!(verify_export(&dir, Some("blender")).is_ok());
        assert!(verify_export(&dir, Some("unreal")).is_err());
        image::RgbImage::new(1, 1)
            .save(dir.join("A_BaseColor.png"))
            .unwrap();
        assert!(verify_export(&dir, None).is_err());
        for preset in crate::export::presets() {
            let sub = dir.join(preset.id);
            crate::export::export(&sub, "Glass", &preset, &m).unwrap();
            bridge::write_sidecar(&sub, "Glass", &preset, &m, &Default::default()).unwrap();
            verify_export(&sub, Some(preset.id)).unwrap();
        }
        std::fs::remove_dir_all(dir).unwrap();
    }
}
