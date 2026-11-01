//! Image fills: a fill layer whose channels come from tiling textures
//! instead of flat values (brick, concrete, paving...).
//!
//! The images are referenced by path (not copied into the project). Relative
//! paths are looked up from the project folder and each of its parents, then
//! from the working directory, so a project inside a repo can refer to
//! `assets/tiles/brick/base_color.png`.
//!
//! Projection:
//! * `uv`: the image repeats `tiling` times across the 0..1 UV square.
//! * `triplanar`: the image is projected along the three world axes and
//!   blended by the surface normal; one repeat covers `tile_size` metres, so
//!   it ignores UVs entirely (no stretching, no visible UV seams).
//!
//! Channel conventions:
//! * base colour: sRGB, multiplied by `tint`;
//! * roughness: grey, remapped into `roughness_range`;
//! * height: grey, 0.5 = neutral, `height = (v - 0.5) * height_scale`;
//! * normal: tangent-space, OpenGL convention (+Y up the image).

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Projection {
    #[default]
    Uv,
    Triplanar,
}

impl Projection {
    pub fn label(self) -> &'static str {
        match self {
            Projection::Uv => "UV",
            Projection::Triplanar => "Triplanar (world)",
        }
    }
    pub fn from_id(s: &str) -> Option<Projection> {
        match s.to_ascii_lowercase().as_str() {
            "uv" => Some(Projection::Uv),
            "triplanar" | "world" => Some(Projection::Triplanar),
            _ => None,
        }
    }
}

/// The channels an image fill can drive.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ImageChannel {
    BaseColor,
    Roughness,
    Height,
    Normal,
}

impl ImageChannel {
    pub const ALL: [ImageChannel; 4] = [ImageChannel::BaseColor, ImageChannel::Roughness, ImageChannel::Height, ImageChannel::Normal];
    pub fn id(self) -> &'static str {
        match self {
            ImageChannel::BaseColor => "base_color",
            ImageChannel::Roughness => "roughness",
            ImageChannel::Height => "height",
            ImageChannel::Normal => "normal",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            ImageChannel::BaseColor => "Base color",
            ImageChannel::Roughness => "Roughness",
            ImageChannel::Height => "Height",
            ImageChannel::Normal => "Normal",
        }
    }
    /// The layer channel this image feeds.
    pub fn channel(self) -> crate::Channel {
        match self {
            ImageChannel::BaseColor => crate::Channel::BaseColor,
            ImageChannel::Roughness => crate::Channel::Roughness,
            ImageChannel::Height => crate::Channel::Height,
            ImageChannel::Normal => crate::Channel::Normal,
        }
    }
    /// Base colour is sRGB; everything else is linear data.
    pub fn is_color(self) -> bool {
        self == ImageChannel::BaseColor
    }
    /// File names recognised in a tile set folder (without extension).
    fn stems(self) -> &'static [&'static str] {
        match self {
            ImageChannel::BaseColor => &["base_color", "basecolor", "albedo", "color", "diffuse"],
            ImageChannel::Roughness => &["roughness", "rough"],
            ImageChannel::Height => &["height", "displacement", "disp"],
            ImageChannel::Normal => &["normal", "normal_opengl", "normal_gl"],
        }
    }
}

/// One image per channel; `None` keeps the layer's flat value for that channel.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct ChannelImages {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_color: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub roughness: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub height: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub normal: Option<String>,
}

impl ChannelImages {
    pub fn get(&self, c: ImageChannel) -> Option<&String> {
        match c {
            ImageChannel::BaseColor => self.base_color.as_ref(),
            ImageChannel::Roughness => self.roughness.as_ref(),
            ImageChannel::Height => self.height.as_ref(),
            ImageChannel::Normal => self.normal.as_ref(),
        }
    }
    pub fn get_mut(&mut self, c: ImageChannel) -> &mut Option<String> {
        match c {
            ImageChannel::BaseColor => &mut self.base_color,
            ImageChannel::Roughness => &mut self.roughness,
            ImageChannel::Height => &mut self.height,
            ImageChannel::Normal => &mut self.normal,
        }
    }
    /// Every (channel, path) that is set.
    pub fn iter(&self) -> impl Iterator<Item = (ImageChannel, &String)> {
        ImageChannel::ALL.into_iter().filter_map(|c| self.get(c).map(|p| (c, p)))
    }
    pub fn is_empty(&self) -> bool {
        self.iter().next().is_none()
    }
}

/// Tiling textures for a fill layer's channels, and how they are projected.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ImageFill {
    #[serde(default)]
    pub images: ChannelImages,
    #[serde(default)]
    pub projection: Projection,
    /// UV projection: repeats across the 0..1 UV square (u, v).
    #[serde(default = "one2")]
    pub tiling: [f32; 2],
    /// Shift, in tiles (both projections).
    #[serde(default)]
    pub offset: [f32; 2],
    /// Degrees, counter-clockwise (both projections).
    #[serde(default)]
    pub rotation: f32,
    /// Triplanar: metres covered by one repeat of the image.
    #[serde(default = "one")]
    pub tile_size: f32,
    /// Triplanar: how sharply the three projections hand over at corners
    /// (1 = soft, 8+ = nearly hard edges).
    #[serde(default = "four")]
    pub blend_sharpness: f32,
    /// Multiplies the base colour image (sRGB 0..1).
    #[serde(default = "white")]
    pub tint: [f32; 3],
    /// Roughness image 0..1 is remapped to this range.
    #[serde(default = "unit_range")]
    pub roughness_range: [f32; 2],
    /// height = (image - 0.5) * height_scale.
    #[serde(default = "one")]
    pub height_scale: f32,
    /// Scales the normal map's tilt (0 = flat).
    #[serde(default = "one")]
    pub normal_strength: f32,
}

fn one() -> f32 {
    1.0
}
fn four() -> f32 {
    4.0
}
fn one2() -> [f32; 2] {
    [1.0, 1.0]
}
fn white() -> [f32; 3] {
    [1.0; 3]
}
fn unit_range() -> [f32; 2] {
    [0.0, 1.0]
}

impl Default for ImageFill {
    fn default() -> Self {
        Self {
            images: ChannelImages::default(),
            projection: Projection::Uv,
            tiling: one2(),
            offset: [0.0; 2],
            rotation: 0.0,
            tile_size: 1.0,
            blend_sharpness: four(),
            tint: white(),
            roughness_range: unit_range(),
            height_scale: 1.0,
            normal_strength: 1.0,
        }
    }
}

impl ImageFill {
    /// Fill every channel from a tile set folder (`base_color.png`,
    /// `roughness.png`, `height.png`, `normal.png`; common aliases accepted).
    /// `dir` is stored as given (relative stays relative); `bases` are where
    /// relative folders are looked up. Errors if the folder has none of them.
    pub fn from_tile_set(dir: &str, bases: &[PathBuf]) -> Result<ChannelImages, String> {
        let found = resolve_path(dir, bases).ok_or_else(|| format!("tile set folder `{dir}` not found"))?;
        if !found.is_dir() {
            return Err(format!("`{dir}` is not a folder"));
        }
        let mut images = ChannelImages::default();
        for c in ImageChannel::ALL {
            'stems: for stem in c.stems() {
                for ext in ["png", "jpg", "jpeg", "exr", "hdr"] {
                    if found.join(format!("{stem}.{ext}")).is_file() {
                        let p = Path::new(dir).join(format!("{stem}.{ext}"));
                        let mut text = p.to_string_lossy().to_string();
                        if !p.is_absolute() {
                            text = text.replace('\\', "/"); // portable relative paths in project files
                        }
                        *images.get_mut(c) = Some(text);
                        break 'stems;
                    }
                }
            }
        }
        if images.is_empty() {
            return Err(format!("`{dir}` has no base_color/roughness/height/normal images"));
        }
        Ok(images)
    }

    /// Paths that can't be found from `bases`.
    pub fn missing(&self, bases: &[PathBuf]) -> Vec<String> {
        self.images.iter().filter(|(_, p)| resolve_path(p, bases).is_none()).map(|(_, p)| p.clone()).collect()
    }
}

/// Find a file or folder: absolute paths as they are; relative ones under
/// each base and each base's parents, then the working directory.
pub fn resolve_path(path: &str, bases: &[PathBuf]) -> Option<PathBuf> {
    let p = Path::new(path);
    if p.is_absolute() {
        return p.exists().then(|| p.to_path_buf());
    }
    for b in bases {
        for dir in b.ancestors() {
            let c = dir.join(p);
            if c.exists() {
                return Some(c);
            }
        }
    }
    p.exists().then(|| p.to_path_buf())
}

/// Tile set folders (any sub-folder with at least one channel image) in `root`.
pub fn list_tile_sets(root: &Path) -> Vec<String> {
    let mut out: Vec<String> = std::fs::read_dir(root)
        .into_iter()
        .flatten()
        .flatten()
        .filter(|e| e.path().is_dir())
        .filter(|e| ImageFill::from_tile_set(&e.path().to_string_lossy(), &[]).is_ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();
    out.sort();
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_fill_in_for_missing_fields() {
        let f: ImageFill = serde_json::from_str(r#"{"images":{"base_color":"a.png"},"projection":"triplanar"}"#).unwrap();
        assert_eq!(f.projection, Projection::Triplanar);
        assert_eq!(f.tiling, [1.0, 1.0]);
        assert_eq!(f.tint, [1.0; 3]);
        assert_eq!(f.roughness_range, [0.0, 1.0]);
        assert_eq!(f.images.base_color.as_deref(), Some("a.png"));
        assert!(f.images.normal.is_none());
        let back: ImageFill = serde_json::from_str(&serde_json::to_string(&f).unwrap()).unwrap();
        assert_eq!(f, back);
        // unset channels are not written
        assert!(!serde_json::to_string(&f.images).unwrap().contains("normal"));
    }

    #[test]
    fn tile_sets_resolve_from_project_parents() {
        let root = std::env::temp_dir().join(format!("pigment-tiles-{}", std::process::id()));
        let set = root.join("assets/tiles/brick");
        std::fs::create_dir_all(&set).unwrap();
        for f in ["base_color.png", "roughness.png", "normal.png"] {
            std::fs::write(set.join(f), b"x").unwrap();
        }
        let project = root.join("scenes/town/projects/a.pigment");
        std::fs::create_dir_all(&project).unwrap();
        let imgs = ImageFill::from_tile_set("assets/tiles/brick/", &[project.clone()]).unwrap();
        assert_eq!(imgs.base_color.as_deref(), Some("assets/tiles/brick/base_color.png"));
        assert_eq!(imgs.normal.as_deref(), Some("assets/tiles/brick/normal.png"));
        assert!(imgs.height.is_none());
        let fill = ImageFill { images: imgs, ..Default::default() };
        assert!(fill.missing(&[project.clone()]).is_empty());
        assert_eq!(fill.missing(&[]).len(), 3, "not found without the project base");
        assert!(ImageFill::from_tile_set("assets/tiles/nope", &[project]).is_err());
        assert_eq!(list_tile_sets(&root.join("assets/tiles")), vec!["brick".to_string()]);
        std::fs::remove_dir_all(root).ok();
    }

    #[test]
    fn old_projects_load_and_image_fills_round_trip() {
        // a project saved before image fills: no `image` key on any layer
        let d = crate::Document::new_default();
        let json = serde_json::to_string(&d).unwrap();
        assert!(!json.contains("\"image\""));
        let old: crate::Document = serde_json::from_str(&json).unwrap();
        assert!(old.layers.iter().all(|l| l.image.is_none()));
        let mut d = old;
        d.layers[0].image = Some(ImageFill {
            images: ChannelImages { base_color: Some("assets/tiles/brick/base_color.png".into()), ..Default::default() },
            projection: Projection::Triplanar,
            tile_size: 2.0,
            rotation: 30.0,
            ..Default::default()
        });
        let back: crate::Document = serde_json::from_str(&serde_json::to_string_pretty(&d).unwrap()).unwrap();
        assert_eq!(back, d);
    }

    #[test]
    fn projection_ids() {
        assert_eq!(Projection::from_id("TRIPLANAR"), Some(Projection::Triplanar));
        assert_eq!(Projection::from_id("uv"), Some(Projection::Uv));
        assert_eq!(Projection::from_id("box"), None);
    }
}
