//! The document model: a texture set made of a layer stack.
//!
//! This is plain data. The renderer owns the pixels (keyed by [`ResId`]) and
//! mirrors this structure on the GPU. Every user edit is a change to a
//! `Document` value, which makes undo a matter of keeping old values around.

use serde::{Deserialize, Serialize};

pub type LayerId = u64;
/// Handle to a GPU pixel resource (a paint layer's channel textures or a mask).
/// A fresh id is minted whenever new pixels are created, so old ids referenced
/// by undo history keep pointing at the right pixels.
pub type ResId = u64;

pub const FORMAT_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Channel {
    BaseColor,
    Roughness,
    Metallic,
    Height,
    Normal,
}

impl Channel {
    pub const ALL: [Channel; 5] = [Channel::BaseColor, Channel::Roughness, Channel::Metallic, Channel::Height, Channel::Normal];
    pub fn index(self) -> usize {
        self as usize
    }
    pub fn label(self) -> &'static str {
        match self {
            Channel::BaseColor => "Base color",
            Channel::Roughness => "Roughness",
            Channel::Metallic => "Metallic",
            Channel::Height => "Height",
            Channel::Normal => "Normal",
        }
    }
    pub fn file_stem(self) -> &'static str {
        match self {
            Channel::BaseColor => "base_color",
            Channel::Roughness => "roughness",
            Channel::Metallic => "metallic",
            Channel::Height => "height",
            Channel::Normal => "normal",
        }
    }
    /// Blend modes that make sense for this channel.
    pub fn blend_modes(self) -> &'static [BlendMode] {
        use BlendMode::*;
        match self {
            Channel::Normal => &[Normal, NormalCombine],
            Channel::Height => &[Normal, Add, Subtract, Multiply, Darken, Lighten, Replace],
            _ => &[Normal, Multiply, Screen, Overlay, Add, Subtract, Darken, Lighten, Replace],
        }
    }
    pub fn default_blend(self) -> BlendMode {
        match self {
            Channel::Normal => BlendMode::NormalCombine,
            _ => BlendMode::Normal,
        }
    }
}

/// Five values, one per channel, serialised with readable keys.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Channels<T> {
    pub base_color: T,
    pub roughness: T,
    pub metallic: T,
    pub height: T,
    pub normal: T,
}

impl<T> Channels<T> {
    pub fn from_fn(mut f: impl FnMut(Channel) -> T) -> Self {
        Channels {
            base_color: f(Channel::BaseColor),
            roughness: f(Channel::Roughness),
            metallic: f(Channel::Metallic),
            height: f(Channel::Height),
            normal: f(Channel::Normal),
        }
    }
    pub fn get(&self, c: Channel) -> &T {
        match c {
            Channel::BaseColor => &self.base_color,
            Channel::Roughness => &self.roughness,
            Channel::Metallic => &self.metallic,
            Channel::Height => &self.height,
            Channel::Normal => &self.normal,
        }
    }
    pub fn get_mut(&mut self, c: Channel) -> &mut T {
        match c {
            Channel::BaseColor => &mut self.base_color,
            Channel::Roughness => &mut self.roughness,
            Channel::Metallic => &mut self.metallic,
            Channel::Height => &mut self.height,
            Channel::Normal => &mut self.normal,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BlendMode {
    Normal,
    Multiply,
    Screen,
    Overlay,
    Add,
    Subtract,
    Darken,
    Lighten,
    /// Like Normal but ignores the layer's own coverage (fills the whole mask).
    Replace,
    /// Reoriented normal mapping: adds the layer's normal detail on top.
    NormalCombine,
}

impl BlendMode {
    pub fn label(self) -> &'static str {
        match self {
            BlendMode::Normal => "Normal",
            BlendMode::Multiply => "Multiply",
            BlendMode::Screen => "Screen",
            BlendMode::Overlay => "Overlay",
            BlendMode::Add => "Add",
            BlendMode::Subtract => "Subtract",
            BlendMode::Darken => "Darken",
            BlendMode::Lighten => "Lighten",
            BlendMode::Replace => "Replace",
            BlendMode::NormalCombine => "Combine (detail)",
        }
    }
    /// Id shared with the WGSL compositor.
    pub fn gpu_id(self) -> u32 {
        self as u32
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ChannelSettings {
    pub enabled: bool,
    pub blend: BlendMode,
    pub opacity: f32,
}

/// Constant channel values for a fill layer (also the brush's paint values).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct MaterialValues {
    /// sRGB-encoded, 0..1, as artists pick colors.
    pub base_color: [f32; 3],
    pub roughness: f32,
    pub metallic: f32,
    /// -1..1, 0 = neutral.
    pub height: f32,
    /// Tangent-space tilt (x, y); z is derived. (0,0) = flat.
    pub normal: [f32; 2],
}

impl Default for MaterialValues {
    fn default() -> Self {
        Self { base_color: [0.8, 0.8, 0.8], roughness: 0.5, metallic: 0.0, height: 0.0, normal: [0.0, 0.0] }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum LayerKind {
    Paint { res: ResId },
    Fill { values: MaterialValues },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GeneratorKind {
    /// Wear on convex edges: curvature + noise, kept out of cavities by AO.
    EdgeWear,
    /// Grime in cavities: inverse AO + concave curvature + noise.
    Dirt,
}

impl GeneratorKind {
    pub fn label(self) -> &'static str {
        match self {
            GeneratorKind::EdgeWear => "Edge wear",
            GeneratorKind::Dirt => "Dirt",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Generator {
    pub kind: GeneratorKind,
    /// How much of the surface is covered, 0..1.
    pub amount: f32,
    /// Edge softness, 0 = hard.
    pub softness: f32,
    /// Breakup noise frequency (relative to mesh size).
    pub noise_scale: f32,
    pub noise_amount: f32,
    pub seed: u32,
}

impl Generator {
    pub fn new(kind: GeneratorKind) -> Self {
        Self { kind, amount: 0.5, softness: 0.15, noise_scale: 8.0, noise_amount: 0.5, seed: 1 }
    }
    pub fn gpu_id(&self) -> u32 {
        match self.kind {
            GeneratorKind::EdgeWear => 1,
            GeneratorKind::Dirt => 2,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Mask {
    /// Painted black/white pixels.
    pub res: ResId,
    /// Procedural mask; multiplied with the painted pixels.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub generator: Option<Generator>,
    #[serde(default)]
    pub invert: bool,
    #[serde(default = "yes")]
    pub enabled: bool,
}

fn yes() -> bool {
    true
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Layer {
    pub id: LayerId,
    pub name: String,
    pub visible: bool,
    pub opacity: f32,
    pub kind: LayerKind,
    pub channels: Channels<ChannelSettings>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mask: Option<Mask>,
}

impl Layer {
    pub fn is_paint(&self) -> bool {
        matches!(self.kind, LayerKind::Paint { .. })
    }
    pub fn paint_res(&self) -> Option<ResId> {
        match self.kind {
            LayerKind::Paint { res } => Some(res),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BakeSettings {
    /// Number of directions for ambient occlusion.
    pub ao_samples: u32,
    /// Curvature edge width as a fraction of the mesh's bounding radius.
    pub curvature_radius: f32,
    pub curvature_strength: f32,
}

impl Default for BakeSettings {
    fn default() -> Self {
        Self { ao_samples: 128, curvature_radius: 0.01, curvature_strength: 1.0 }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Document {
    pub format: u32,
    /// Texture size in pixels (square, power of two).
    pub resolution: u32,
    /// Mesh file, relative to the project folder.
    pub mesh: String,
    /// Bottom to top.
    pub layers: Vec<Layer>,
    pub bake: BakeSettings,
    #[serde(default = "default_preset")]
    pub export_preset: String,
    pub next_id: u64,
}

fn default_preset() -> String {
    "unreal".into()
}

impl Default for Document {
    fn default() -> Self {
        Self {
            format: FORMAT_VERSION,
            resolution: 2048,
            mesh: String::new(),
            layers: Vec::new(),
            bake: BakeSettings::default(),
            export_preset: default_preset(),
            next_id: 1,
        }
    }
}

pub const RESOLUTIONS: [u32; 4] = [512, 1024, 2048, 4096];

impl Document {
    /// A new document with a base fill and an empty paint layer on top.
    pub fn new_default() -> Self {
        let mut d = Document::default();
        let base = d.new_fill_layer("Base material");
        d.layers.push(base);
        let paint = d.new_paint_layer("Paint");
        d.layers.push(paint);
        d
    }

    pub fn mint(&mut self) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        id
    }

    fn channels_default() -> Channels<ChannelSettings> {
        Channels::from_fn(|c| ChannelSettings { enabled: true, blend: c.default_blend(), opacity: 1.0 })
    }

    pub fn new_paint_layer(&mut self, name: &str) -> Layer {
        let id = self.mint();
        let res = self.mint();
        Layer {
            id,
            name: name.into(),
            visible: true,
            opacity: 1.0,
            kind: LayerKind::Paint { res },
            channels: Self::channels_default(),
            mask: None,
        }
    }

    pub fn new_fill_layer(&mut self, name: &str) -> Layer {
        let id = self.mint();
        Layer {
            id,
            name: name.into(),
            visible: true,
            opacity: 1.0,
            kind: LayerKind::Fill { values: MaterialValues::default() },
            channels: Self::channels_default(),
            mask: None,
        }
    }

    pub fn layer(&self, id: LayerId) -> Option<&Layer> {
        self.layers.iter().find(|l| l.id == id)
    }
    pub fn layer_mut(&mut self, id: LayerId) -> Option<&mut Layer> {
        self.layers.iter_mut().find(|l| l.id == id)
    }
    pub fn index_of(&self, id: LayerId) -> Option<usize> {
        self.layers.iter().position(|l| l.id == id)
    }

    /// Every pixel resource this document needs.
    pub fn resources(&self) -> Vec<ResId> {
        let mut out = Vec::new();
        for l in &self.layers {
            if let Some(r) = l.paint_res() {
                out.push(r);
            }
            if let Some(m) = &l.mask {
                out.push(m.res);
            }
        }
        out
    }

    /// Short human description of what changed between two versions, for the
    /// undo history list.
    pub fn describe_change(before: &Document, after: &Document) -> String {
        if before.layers.len() < after.layers.len() {
            let new = after.layers.iter().find(|l| before.layer(l.id).is_none());
            return format!("Add layer {}", new.map(|l| l.name.as_str()).unwrap_or(""));
        }
        if before.layers.len() > after.layers.len() {
            let gone = before.layers.iter().find(|l| after.layer(l.id).is_none());
            return format!("Delete layer {}", gone.map(|l| l.name.as_str()).unwrap_or(""));
        }
        let ids_b: Vec<_> = before.layers.iter().map(|l| l.id).collect();
        let ids_a: Vec<_> = after.layers.iter().map(|l| l.id).collect();
        if ids_b != ids_a {
            return "Reorder layers".into();
        }
        for (b, a) in before.layers.iter().zip(&after.layers) {
            if b != a {
                if b.mask.is_none() && a.mask.is_some() {
                    return format!("Add mask to {}", a.name);
                }
                if b.mask.is_some() && a.mask.is_none() {
                    return format!("Remove mask from {}", a.name);
                }
                if b.name != a.name {
                    return format!("Rename {} to {}", b.name, a.name);
                }
                return format!("Edit {}", a.name);
            }
        }
        if before.resolution != after.resolution {
            return format!("Resolution {}", after.resolution);
        }
        if before.bake != after.bake {
            return "Bake settings".into();
        }
        "Edit".into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_doc_has_fill_then_paint() {
        let d = Document::new_default();
        assert_eq!(d.layers.len(), 2);
        assert!(!d.layers[0].is_paint());
        assert!(d.layers[1].is_paint());
        assert_eq!(d.resources().len(), 1);
    }

    #[test]
    fn ids_are_unique() {
        let mut d = Document::new_default();
        let a = d.new_paint_layer("a");
        let b = d.new_paint_layer("b");
        let mut all = vec![a.id, a.paint_res().unwrap(), b.id, b.paint_res().unwrap()];
        all.extend(d.layers.iter().map(|l| l.id));
        let n = all.len();
        all.sort();
        all.dedup();
        assert_eq!(all.len(), n);
    }

    #[test]
    fn json_round_trip() {
        let mut d = Document::new_default();
        d.layers[1].mask = Some(Mask { res: 99, generator: Some(Generator::new(GeneratorKind::EdgeWear)), invert: false, enabled: true });
        let s = serde_json::to_string_pretty(&d).unwrap();
        let back: Document = serde_json::from_str(&s).unwrap();
        assert_eq!(d, back);
        assert!(s.contains("\"base_color\""));
        assert!(s.contains("\"edge_wear\""));
    }

    #[test]
    fn change_descriptions() {
        let a = Document::new_default();
        let mut b = a.clone();
        let l = b.new_fill_layer("Rust");
        b.layers.push(l);
        assert_eq!(Document::describe_change(&a, &b), "Add layer Rust");
        assert_eq!(Document::describe_change(&b, &a), "Delete layer Rust");
        let mut c = a.clone();
        c.layers.swap(0, 1);
        assert_eq!(Document::describe_change(&a, &c), "Reorder layers");
        let mut e = a.clone();
        e.layers[0].opacity = 0.5;
        assert_eq!(Document::describe_change(&a, &e), "Edit Base material");
    }
}
