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
    /// Light the surface gives off: neon, screens, LEDs. HDR (colour x strength).
    Emissive,
    /// Coverage / alpha: 1 = solid, 0 = cut away (fences, grilles, holes).
    Opacity,
    /// Glass: 0 = opaque surface, 1 = fully transmissive (refracting) surface.
    Transmission,
}

impl Channel {
    pub const ALL: [Channel; 8] = [
        Channel::BaseColor,
        Channel::Roughness,
        Channel::Metallic,
        Channel::Height,
        Channel::Normal,
        Channel::Emissive,
        Channel::Opacity,
        Channel::Transmission,
    ];
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
            Channel::Emissive => "Emission",
            Channel::Opacity => "Opacity",
            Channel::Transmission => "Transmission",
        }
    }
    pub fn file_stem(self) -> &'static str {
        match self {
            Channel::BaseColor => "base_color",
            Channel::Roughness => "roughness",
            Channel::Metallic => "metallic",
            Channel::Height => "height",
            Channel::Normal => "normal",
            Channel::Emissive => "emissive",
            Channel::Opacity => "opacity",
            Channel::Transmission => "transmission",
        }
    }
    /// Blend modes that make sense for this channel.
    pub fn blend_modes(self) -> &'static [BlendMode] {
        use BlendMode::*;
        match self {
            Channel::Normal => &[Normal, NormalCombine],
            Channel::Emissive => &[Normal, Add, Screen, Lighten, Multiply, Replace],
            Channel::Height => &[Normal, Add, Subtract, Multiply, Darken, Lighten, Replace],
            _ => &[Normal, Multiply, Screen, Overlay, Add, Subtract, Darken, Lighten, Replace],
        }
    }
    pub fn default_blend(self) -> BlendMode {
        match self {
            Channel::Normal => BlendMode::NormalCombine,
            // Height layers stack (Substance's default is Linear Dodge / Add):
            // a dent painted over a chip goes deeper, and a fill with height 0
            // doesn't wipe height painted below it.
            Channel::Height => BlendMode::Add,
            _ => BlendMode::Normal,
        }
    }
}

/// One value per channel, serialised with readable keys.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(bound(deserialize = "T: Deserialize<'de> + Default"))]
pub struct Channels<T> {
    pub base_color: T,
    pub roughness: T,
    pub metallic: T,
    pub height: T,
    pub normal: T,
    /// Added in format 1 later: older projects load it as default (off).
    #[serde(default)]
    pub emissive: T,
    /// Added later still: older projects load these as default (off).
    #[serde(default)]
    pub opacity: T,
    #[serde(default)]
    pub transmission: T,
}

impl<T> Channels<T> {
    pub fn from_fn(mut f: impl FnMut(Channel) -> T) -> Self {
        Channels {
            base_color: f(Channel::BaseColor),
            roughness: f(Channel::Roughness),
            metallic: f(Channel::Metallic),
            height: f(Channel::Height),
            normal: f(Channel::Normal),
            emissive: f(Channel::Emissive),
            opacity: f(Channel::Opacity),
            transmission: f(Channel::Transmission),
        }
    }
    pub fn get(&self, c: Channel) -> &T {
        match c {
            Channel::BaseColor => &self.base_color,
            Channel::Roughness => &self.roughness,
            Channel::Metallic => &self.metallic,
            Channel::Height => &self.height,
            Channel::Normal => &self.normal,
            Channel::Emissive => &self.emissive,
            Channel::Opacity => &self.opacity,
            Channel::Transmission => &self.transmission,
        }
    }
    pub fn get_mut(&mut self, c: Channel) -> &mut T {
        match c {
            Channel::BaseColor => &mut self.base_color,
            Channel::Roughness => &mut self.roughness,
            Channel::Metallic => &mut self.metallic,
            Channel::Height => &mut self.height,
            Channel::Normal => &mut self.normal,
            Channel::Emissive => &mut self.emissive,
            Channel::Opacity => &mut self.opacity,
            Channel::Transmission => &mut self.transmission,
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

impl Default for ChannelSettings {
    fn default() -> Self {
        Self { enabled: false, blend: BlendMode::Normal, opacity: 1.0 }
    }
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
    /// Emitted light colour (sRGB) and strength (0 = none, 1 = as bright as
    /// white paint under the studio light, neon ~4-8).
    #[serde(default)]
    pub emissive: [f32; 3],
    #[serde(default)]
    pub emissive_strength: f32,
    /// Alpha: 1 = solid, 0 = a hole (cut-out).
    #[serde(default = "one")]
    pub opacity: f32,
    /// 0 = opaque, 1 = clear glass (light passes through and refracts).
    #[serde(default)]
    pub transmission: f32,
}

impl Default for MaterialValues {
    fn default() -> Self {
        Self {
            base_color: [0.8, 0.8, 0.8],
            roughness: 0.5,
            metallic: 0.0,
            height: 0.0,
            normal: [0.0, 0.0],
            emissive: [0.0; 3],
            emissive_strength: 0.0,
            opacity: 1.0,
            transmission: 0.0,
        }
    }
}

impl MaterialValues {
    /// (see-through, transmissive): whether a fill of these values needs its
    /// opacity / transmission channels on.
    pub fn is_see_through(&self) -> (bool, bool) {
        (self.opacity < 1.0 - 1e-3, self.transmission > 1e-3)
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
    /// Blotchy multi-scale noise: discolouration, roughness breakup.
    Grunge,
    /// Vertical rain / leak streaks (world up), heavier under overhangs.
    Streaks,
    /// Diagonal hazard stripes in world space.
    Stripes,
    /// Domain-warped blobs: rust spots, paint splotches.
    Spots,
    /// Thin ridged lines: scratches and scuffs.
    Scratches,
    /// Grid of panel seams on every face (pair with negative height).
    PanelLines,
    /// Rises from the bottom of the model: grime, splash and rust near the ground.
    Gradient,
}

impl GeneratorKind {
    pub const ALL: [GeneratorKind; 9] = [
        GeneratorKind::EdgeWear,
        GeneratorKind::Dirt,
        GeneratorKind::Grunge,
        GeneratorKind::Streaks,
        GeneratorKind::Stripes,
        GeneratorKind::Spots,
        GeneratorKind::Scratches,
        GeneratorKind::PanelLines,
        GeneratorKind::Gradient,
    ];
    pub fn label(self) -> &'static str {
        match self {
            GeneratorKind::EdgeWear => "Edge wear",
            GeneratorKind::Dirt => "Dirt",
            GeneratorKind::Grunge => "Grunge",
            GeneratorKind::Streaks => "Streaks",
            GeneratorKind::Stripes => "Hazard stripes",
            GeneratorKind::Spots => "Spots",
            GeneratorKind::Scratches => "Scratches",
            GeneratorKind::PanelLines => "Panel lines",
            GeneratorKind::Gradient => "Ground gradient",
        }
    }
    pub fn id(self) -> &'static str {
        match self {
            GeneratorKind::EdgeWear => "edge_wear",
            GeneratorKind::Dirt => "dirt",
            GeneratorKind::Grunge => "grunge",
            GeneratorKind::Streaks => "streaks",
            GeneratorKind::Stripes => "stripes",
            GeneratorKind::Spots => "spots",
            GeneratorKind::Scratches => "scratches",
            GeneratorKind::PanelLines => "panel_lines",
            GeneratorKind::Gradient => "gradient",
        }
    }
    pub fn from_id(s: &str) -> Option<GeneratorKind> {
        let s = s.to_ascii_lowercase().replace([' ', '-'], "_");
        Self::ALL.into_iter().find(|k| k.id() == s || k.label().to_ascii_lowercase().replace(' ', "_") == s)
    }
    /// Uses the curvature / AO bakes (vs. a pure world-space pattern).
    pub fn uses_bakes(self) -> bool {
        matches!(self, GeneratorKind::EdgeWear | GeneratorKind::Dirt | GeneratorKind::Streaks | GeneratorKind::Grunge | GeneratorKind::Spots)
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
    /// How strongly occluded areas count: keeps edge wear out of cavities,
    /// drives dirt into them.
    #[serde(default = "half")]
    pub ao_influence: f32,
    /// How strongly curvature counts (0 = noise/AO only).
    #[serde(default = "one")]
    pub curvature_weight: f32,
}

fn half() -> f32 {
    0.5
}
fn one() -> f32 {
    1.0
}

impl Generator {
    pub fn new(kind: GeneratorKind) -> Self {
        // (amount, softness, scale, breakup, AO influence). Pattern generators
        // (grunge and later) use `noise_scale` as features per metre.
        let (amount, softness, noise_scale, noise_amount, ao_influence) = match kind {
            GeneratorKind::EdgeWear => (0.5, 0.15, 8.0, 0.5, 0.5),
            GeneratorKind::Dirt => (0.5, 0.15, 8.0, 0.5, 1.0),
            GeneratorKind::Grunge => (0.45, 0.12, 4.0, 0.0, 0.2),
            GeneratorKind::Streaks => (0.4, 0.1, 6.0, 0.2, 0.4),
            GeneratorKind::Stripes => (0.5, 0.01, 3.0, 0.0, 0.0),
            GeneratorKind::Spots => (0.3, 0.06, 4.0, 0.2, 0.3),
            GeneratorKind::Scratches => (0.2, 0.03, 5.0, 0.0, 0.0),
            GeneratorKind::PanelLines => (0.06, 0.01, 2.5, 0.0, 0.0),
            GeneratorKind::Gradient => (0.2, 0.15, 6.0, 0.25, 0.0),
        };
        Self { kind, amount, softness, noise_scale, noise_amount, seed: 1, ao_influence, curvature_weight: 1.0 }
    }
    pub fn gpu_id(&self) -> u32 {
        match self.kind {
            GeneratorKind::EdgeWear => 1,
            GeneratorKind::Dirt => 2,
            GeneratorKind::Grunge => 3,
            GeneratorKind::Streaks => 4,
            GeneratorKind::Stripes => 5,
            GeneratorKind::Spots => 6,
            GeneratorKind::Scratches => 7,
            GeneratorKind::PanelLines => 8,
            GeneratorKind::Gradient => 9,
        }
    }
    pub fn with(mut self, amount: f32, noise_scale: f32) -> Self {
        self.amount = amount;
        self.noise_scale = noise_scale;
        self
    }
}

/// How an extra mask effect combines with the effects before it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MaskOp {
    Multiply,
    Add,
    Subtract,
    Max,
    Min,
}

impl MaskOp {
    pub const ALL: [MaskOp; 5] = [MaskOp::Multiply, MaskOp::Add, MaskOp::Subtract, MaskOp::Max, MaskOp::Min];
    pub fn label(self) -> &'static str {
        match self {
            MaskOp::Multiply => "Multiply (both)",
            MaskOp::Add => "Add (either)",
            MaskOp::Subtract => "Subtract",
            MaskOp::Max => "Max",
            MaskOp::Min => "Min",
        }
    }
    pub fn gpu_id(self) -> u32 {
        self as u32
    }
    pub fn from_id(s: &str) -> Option<MaskOp> {
        Self::ALL.into_iter().find(|o| format!("{o:?}").eq_ignore_ascii_case(s))
    }
}

/// An extra generator in a mask, combined with the result so far.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct MaskEffect {
    pub generator: Generator,
    pub op: MaskOp,
}

/// Most mask effects after the main generator (GPU parameter budget).
pub const MAX_MASK_EFFECTS: usize = 2;
/// Parts with ids below this can be selected in masks.
pub const MAX_SELECTABLE_PARTS: u32 = 256;

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
    /// Only these mesh parts (empty = the whole model). Non-destructive
    /// "polygon fill": survives resolution changes and stays editable.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub parts: Vec<u32>,
    /// Further generators combined after `generator` (at most MAX_MASK_EFFECTS).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub effects: Vec<MaskEffect>,
}

impl Mask {
    pub fn new(res: ResId) -> Self {
        Mask { res, generator: None, invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() }
    }
    pub fn with_generator(res: ResId, g: Generator) -> Self {
        Mask { generator: Some(g), ..Mask::new(res) }
    }
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
    /// Occluders farther than this (fraction of the bounding radius) don't
    /// darken AO, so big interiors don't go black (Substance: max occluder distance).
    #[serde(default = "ao_distance")]
    pub ao_distance: f32,
}

fn ao_distance() -> f32 {
    0.3
}

impl Default for BakeSettings {
    fn default() -> Self {
        Self { ao_samples: 128, curvature_radius: 0.05, curvature_strength: 1.0, ao_distance: ao_distance() }
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

/// Paint colours offered as "Worn <paint> metal" smart materials.
pub const SMART_PAINTS: [&str; 7] = ["Olive drab", "Teal paint", "Orange paint", "Red paint", "Hazard yellow", "Matte black", "Violet paint"];
/// Plastics offered as "Scuffed <plastic>" smart materials.
pub const SMART_PLASTICS: [&str; 4] = ["Neon pink plastic", "Cyan plastic", "White plastic", "Black rubber"];

/// Every smart material name, for menus and the MCP server.
pub fn smart_material_names() -> Vec<String> {
    let mut v: Vec<String> = SMART_PAINTS.iter().map(|p| format!("Worn {} metal", p.to_ascii_lowercase())).collect();
    v.extend(["Rusty steel", "Hazard stripes", "Grimy concrete", "Tech panels", "Grimy chrome"].map(String::from));
    v.extend(SMART_PLASTICS.iter().map(|p| format!("Scuffed {}", p.to_ascii_lowercase())));
    v
}

/// Ready-made materials for the brush and for fill layers.
pub fn material_presets() -> Vec<(&'static str, MaterialValues)> {
    let m = |c: [f32; 3], r: f32, mt: f32, h: f32| MaterialValues { base_color: c, roughness: r, metallic: mt, height: h, ..Default::default() };
    let neon = |c: [f32; 3], strength: f32| MaterialValues { base_color: c, roughness: 0.2, emissive: c, emissive_strength: strength, ..Default::default() };
    vec![
        ("Steel", m([0.56, 0.57, 0.58], 0.3, 1.0, 0.0)),
        ("Dark iron", m([0.33, 0.33, 0.34], 0.55, 1.0, 0.0)),
        ("Aluminium", m([0.91, 0.92, 0.92], 0.35, 1.0, 0.0)),
        ("Gold", m([1.0, 0.77, 0.34], 0.22, 1.0, 0.0)),
        ("Copper", m([0.95, 0.64, 0.54], 0.3, 1.0, 0.0)),
        ("Teal paint", m([0.1, 0.32, 0.35], 0.45, 0.0, 0.0)),
        ("Orange paint", m([0.86, 0.36, 0.08], 0.4, 0.0, 0.0)),
        ("Olive drab", m([0.29, 0.31, 0.18], 0.6, 0.0, 0.0)),
        ("Hazard yellow", m([0.93, 0.72, 0.05], 0.45, 0.0, 0.0)),
        ("Matte black", m([0.03, 0.03, 0.035], 0.75, 0.0, 0.0)),
        ("Gunmetal", m([0.22, 0.23, 0.25], 0.4, 1.0, 0.0)),
        ("Chrome", m([0.95, 0.95, 0.96], 0.05, 1.0, 0.0)),
        ("Brushed steel", m([0.62, 0.63, 0.64], 0.42, 1.0, 0.0)),
        ("Neon pink plastic", m([1.0, 0.1, 0.55], 0.3, 0.0, 0.0)),
        ("Cyan plastic", m([0.0, 0.75, 0.85], 0.3, 0.0, 0.0)),
        ("Violet paint", m([0.38, 0.12, 0.62], 0.45, 0.0, 0.0)),
        ("Carbon black", m([0.06, 0.06, 0.07], 0.35, 0.0, 0.0)),
        ("Asphalt", m([0.09, 0.09, 0.09], 0.8, 0.0, 0.0)),
        ("Wet concrete", m([0.32, 0.32, 0.33], 0.25, 0.0, 0.0)),
        ("Verdigris", m([0.32, 0.6, 0.5], 0.8, 0.0, 0.05)),
        ("Oxidized iron", m([0.2, 0.1, 0.06], 0.9, 0.3, 0.1)),
        ("Panel seam", m([0.05, 0.05, 0.05], 0.6, 0.5, -0.5)),
        ("Neon pink", neon([1.0, 0.12, 0.6], 6.0)),
        ("Neon cyan", neon([0.05, 0.9, 1.0], 6.0)),
        ("Neon amber", neon([1.0, 0.55, 0.08], 6.0)),
        ("Neon green", neon([0.3, 1.0, 0.25], 6.0)),
        ("Neon violet", neon([0.6, 0.2, 1.0], 6.0)),
        ("LED white", neon([0.95, 0.97, 1.0], 4.0)),
        ("Screen blue", MaterialValues { base_color: [0.02, 0.04, 0.08], roughness: 0.1, emissive: [0.25, 0.55, 1.0], emissive_strength: 2.0, ..Default::default() }),
        ("Red paint", m([0.62, 0.07, 0.05], 0.4, 0.0, 0.0)),
        ("White plastic", m([0.85, 0.85, 0.83], 0.35, 0.0, 0.0)),
        ("Black rubber", m([0.04, 0.04, 0.04], 0.9, 0.0, 0.0)),
        ("Rust", m([0.42, 0.18, 0.08], 0.85, 0.15, 0.15)),
        ("Grime", m([0.13, 0.1, 0.07], 0.95, 0.0, 0.0)),
        ("Concrete", m([0.55, 0.54, 0.52], 0.9, 0.0, 0.0)),
        ("Chip (dent)", m([0.56, 0.57, 0.58], 0.3, 1.0, -0.6)),
        ("Clear glass", MaterialValues { base_color: [0.92, 0.95, 0.96], roughness: 0.03, opacity: 0.35, transmission: 1.0, ..Default::default() }),
        ("Tinted glass", MaterialValues { base_color: [0.35, 0.45, 0.5], roughness: 0.05, opacity: 0.6, transmission: 1.0, ..Default::default() }),
        ("Frosted glass", MaterialValues { base_color: [0.85, 0.88, 0.9], roughness: 0.35, opacity: 0.7, transmission: 1.0, ..Default::default() }),
        ("Cut-out", MaterialValues { opacity: 0.0, ..Default::default() }),
    ]
}

pub fn material_preset(name: &str) -> MaterialValues {
    material_presets().into_iter().find(|(n, _)| *n == name).map(|(_, v)| v).unwrap_or_default()
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

    /// The demo stack: teal painted metal worn to bare steel on edges, with
    /// grime in the creases, and an empty paint layer on top.
    pub fn demo() -> Self {
        let mut d = Document::default();
        for l in d.worn_paint_layers("Teal paint") {
            d.layers.push(l);
        }
        let paint = d.new_paint_layer("Paint");
        d.layers.push(paint);
        d
    }

    /// Smart material: paint (any preset) worn to bare steel on edges, with
    /// recessed chips, plus grime in crevices. Three layers, bottom to top.
    pub fn worn_paint_layers(&mut self, paint: &str) -> Vec<Layer> {
        let mut base = self.new_fill_layer(&paint);
        base.kind = LayerKind::Fill { values: material_preset(paint) };

        let mut wear = self.new_fill_layer("Edge wear");
        let mut steel = material_preset("Steel");
        steel.height = -0.35;
        wear.kind = LayerKind::Fill { values: steel };
        wear.channels.normal.enabled = false;
        let res = self.mint();
        let mut g = Generator::new(GeneratorKind::EdgeWear);
        g.amount = 0.62;
        g.softness = 0.04;
        g.noise_scale = 22.0;
        g.noise_amount = 0.9;
        wear.mask = Some(Mask { res, generator: Some(g), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });

        let mut dirt = self.new_fill_layer("Dirt");
        dirt.kind = LayerKind::Fill { values: material_preset("Grime") };
        dirt.channels.metallic.enabled = false;
        dirt.channels.height.enabled = false;
        dirt.channels.normal.enabled = false;
        dirt.opacity = 0.85;
        let res = self.mint();
        let mut g = Generator::new(GeneratorKind::Dirt);
        g.amount = 0.55;
        g.softness = 0.2;
        g.noise_scale = 5.0;
        g.noise_amount = 0.7;
        dirt.mask = Some(Mask { res, generator: Some(g), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
        vec![base, wear, dirt]
    }

    /// A fill layer from a preset, optionally masked by a generator. Height
    /// only participates when the preset has some.
    pub fn fill_with(&mut self, name: &str, preset: &str, generator: Option<Generator>) -> Layer {
        let mut l = self.new_fill_layer(name);
        let values = material_preset(preset);
        l.channels.height.enabled = values.height.abs() > 1e-3;
        l.channels.normal.enabled = false;
        l.channels.emissive.enabled = values.emissive_strength > 0.0;
        (l.channels.opacity.enabled, l.channels.transmission.enabled) = values.is_see_through();
        l.kind = LayerKind::Fill { values };
        if let Some(g) = generator {
            let res = self.mint();
            l.mask = Some(Mask { res, generator: Some(g), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
        }
        l
    }

    /// Multi-layer smart materials, bottom to top. `None` for an unknown name.
    pub fn smart_material(&mut self, name: &str) -> Option<Vec<Layer>> {
        use GeneratorKind::*;
        if let Some(paint) = name.strip_prefix("Worn ").and_then(|p| p.strip_suffix(" metal")) {
            let preset = SMART_PAINTS.iter().find(|p| p.to_ascii_lowercase() == paint.to_ascii_lowercase())?;
            return Some(self.worn_paint_layers(preset));
        }
        let g = Generator::new;
        let only = |l: &mut Layer, keep: &[Channel]| {
            for c in Channel::ALL {
                l.channels.get_mut(c).enabled = keep.contains(&c);
            }
        };
        Some(match name {
            "Rusty steel" => {
                let base = self.fill_with("Dark iron", "Dark iron", None);
                let mut grunge = self.fill_with("Grunge", "Oxidized iron", Some(g(Grunge).with(0.4, 7.0)));
                grunge.opacity = 0.6;
                let rust = self.fill_with("Rust spots", "Rust", Some(g(Spots).with(0.3, 9.0)));
                let mut cav = g(Dirt);
                cav.amount = 0.55;
                let rust2 = self.fill_with("Rust in crevices", "Rust", Some(cav));
                let streaks = self.fill_with("Rust streaks", "Oxidized iron", Some(g(Streaks).with(0.3, 12.0)));
                vec![base, grunge, rust, rust2, streaks]
            }
            "Hazard stripes" => {
                let base = self.fill_with("Hazard yellow", "Hazard yellow", None);
                let stripes = self.fill_with("Black stripes", "Matte black", Some(g(Stripes)));
                let mut wear = self.worn_paint_layers("Hazard yellow");
                let dirt = wear.pop().unwrap();
                let edge = wear.pop().unwrap();
                vec![base, stripes, edge, dirt]
            }
            "Grimy concrete" => {
                let base = self.fill_with("Concrete", "Concrete", None);
                let mut blotch = self.fill_with("Damp patches", "Wet concrete", Some(g(Grunge).with(0.5, 2.0)));
                only(&mut blotch, &[Channel::BaseColor, Channel::Roughness]);
                let leaks = self.fill_with("Leaks", "Grime", Some(g(Streaks).with(0.45, 5.0)));
                let mut dirt = g(Dirt);
                dirt.amount = 0.6;
                let grime = self.fill_with("Grime", "Grime", Some(dirt));
                vec![base, blotch, leaks, grime]
            }
            "Tech panels" => {
                let base = self.fill_with("Gunmetal", "Gunmetal", None);
                let mut rough = self.fill_with("Roughness breakup", "Dark iron", Some(g(Grunge).with(0.5, 6.0)));
                only(&mut rough, &[Channel::Roughness]);
                let seams = self.fill_with("Panel seams", "Panel seam", Some(g(PanelLines)));
                let mut scratches = self.fill_with("Scratches", "Brushed steel", Some(g(Scratches).with(0.1, 6.0)));
                scratches.opacity = 0.4;
                let mut wear = g(EdgeWear);
                wear.amount = 0.55;
                wear.noise_scale = 22.0;
                wear.noise_amount = 0.8;
                wear.softness = 0.05;
                let edges = self.fill_with("Edge wear", "Brushed steel", Some(wear));
                let mut dirt = g(Dirt);
                dirt.amount = 0.5;
                let grime = self.fill_with("Grime", "Grime", Some(dirt));
                vec![base, rough, seams, scratches, edges, grime]
            }
            "Grimy chrome" => {
                let base = self.fill_with("Chrome", "Chrome", None);
                let mut smudge = self.fill_with("Smudges", "Brushed steel", Some(g(Grunge).with(0.5, 8.0)));
                only(&mut smudge, &[Channel::Roughness]);
                let mut dirt = g(Dirt);
                dirt.amount = 0.5;
                let grime = self.fill_with("Grime", "Grime", Some(dirt));
                vec![base, smudge, grime]
            }
            other => {
                let color = other.strip_prefix("Scuffed ")?;
                let preset = SMART_PLASTICS.iter().find(|p| p.to_ascii_lowercase() == color.to_ascii_lowercase())?;
                let base = self.fill_with(preset, preset, None);
                let scratches = self.fill_with("Scuffs", "White plastic", Some(g(Scratches).with(0.25, 7.0)));
                let mut dirt = g(Dirt);
                dirt.amount = 0.45;
                let grime = self.fill_with("Grime", "Grime", Some(dirt));
                vec![base, scratches, grime]
            }
        })
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
        let mut channels = Self::channels_default();
        channels.emissive.enabled = false; // a fill without emission must not black out glow below it
        channels.opacity.enabled = false; // nor make glass / cut-outs below it solid
        channels.transmission.enabled = false;
        Layer {
            id,
            name: name.into(),
            visible: true,
            opacity: 1.0,
            kind: LayerKind::Fill { values: MaterialValues::default() },
            channels,
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
    fn demo_stack_is_complete() {
        let d = Document::demo();
        assert_eq!(d.layers.len(), 4);
        assert_eq!(d.layers.iter().filter(|l| l.mask.as_ref().is_some_and(|m| m.generator.is_some())).count(), 2);
        assert!(d.layers.last().unwrap().is_paint());
        assert_eq!(d.resources().len(), 3);
        assert!(material_presets().len() >= 10);
    }

    #[test]
    fn every_smart_material_builds() {
        for name in smart_material_names() {
            let mut d = Document::default();
            let layers = d.smart_material(&name).unwrap_or_else(|| panic!("{name} didn't build"));
            assert!(layers.len() >= 2, "{name}");
            // every layer id and resource id unique
            let mut ids: Vec<u64> = layers.iter().map(|l| l.id).collect();
            ids.extend(layers.iter().filter_map(|l| l.mask.as_ref().map(|m| m.res)));
            let n = ids.len();
            ids.sort();
            ids.dedup();
            assert_eq!(ids.len(), n, "{name}");
        }
        assert!(Document::default().smart_material("Nope").is_none());
    }

    #[test]
    fn generator_kinds_round_trip_by_id() {
        for k in GeneratorKind::ALL {
            assert_eq!(GeneratorKind::from_id(k.id()), Some(k));
            assert_eq!(GeneratorKind::from_id(k.label()), Some(k));
        }
    }

    #[test]
    fn emission_is_off_on_plain_fills_and_old_projects_load() {
        let mut d = Document::default();
        assert!(!d.new_fill_layer("f").channels.emissive.enabled);
        assert!(d.new_paint_layer("p").channels.emissive.enabled);
        assert!(d.fill_with("n", "Neon pink", None).channels.emissive.enabled);
        // a document saved before the emissive channel existed
        let mut v = serde_json::to_value(Document::new_default()).unwrap();
        for l in v["layers"].as_array_mut().unwrap() {
            l["channels"].as_object_mut().unwrap().remove("emissive");
            if let Some(vals) = l["kind"].get_mut("values") {
                vals.as_object_mut().unwrap().remove("emissive");
                vals.as_object_mut().unwrap().remove("emissive_strength");
            }
        }
        let old: Document = serde_json::from_value(v).unwrap();
        assert!(!old.layers[0].channels.emissive.enabled);
    }

    #[test]
    fn opacity_and_transmission_are_off_on_plain_fills_and_old_projects_load() {
        let mut d = Document::default();
        let f = d.new_fill_layer("f");
        assert!(!f.channels.opacity.enabled && !f.channels.transmission.enabled);
        let p = d.new_paint_layer("p");
        assert!(p.channels.opacity.enabled && p.channels.transmission.enabled);
        let g = d.fill_with("g", "Clear glass", None);
        assert!(g.channels.opacity.enabled && g.channels.transmission.enabled);
        let c = d.fill_with("c", "Cut-out", None);
        assert!(c.channels.opacity.enabled && !c.channels.transmission.enabled);
        assert!(Channel::ALL.iter().enumerate().all(|(i, c)| c.index() == i));
        // a document saved before these channels existed
        let mut v = serde_json::to_value(Document::new_default()).unwrap();
        for l in v["layers"].as_array_mut().unwrap() {
            l["channels"].as_object_mut().unwrap().remove("opacity");
            l["channels"].as_object_mut().unwrap().remove("transmission");
            if let Some(vals) = l["kind"].get_mut("values") {
                vals.as_object_mut().unwrap().remove("opacity");
                vals.as_object_mut().unwrap().remove("transmission");
            }
        }
        let old: Document = serde_json::from_value(v).unwrap();
        assert!(!old.layers[0].channels.opacity.enabled);
        let LayerKind::Fill { values } = &old.layers[0].kind else { panic!() };
        assert_eq!((values.opacity, values.transmission), (1.0, 0.0));
    }

    #[test]
    fn height_stacks_by_default() {
        // Substance's default: a dent painted over a chip goes deeper
        assert_eq!(Channel::Height.default_blend(), BlendMode::Add);
        let mut d = Document::default();
        let l = d.new_fill_layer("f");
        assert_eq!(l.channels.height.blend, BlendMode::Add);
        let chip = crate::blend::blend_scalar(BlendMode::Add, 0.0, -0.35, 1.0);
        let dent = crate::blend::blend_scalar(BlendMode::Add, chip, -0.3, 1.0);
        assert!(dent < chip);
    }

    #[test]
    fn old_projects_get_new_generator_fields() {
        let json = r#"{"kind":"edge_wear","amount":0.5,"softness":0.1,"noise_scale":8.0,"noise_amount":0.5,"seed":1}"#;
        let g: Generator = serde_json::from_str(json).unwrap();
        assert_eq!((g.ao_influence, g.curvature_weight), (0.5, 1.0));
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
        d.layers[1].mask = Some(Mask { res: 99, generator: Some(Generator::new(GeneratorKind::EdgeWear)), invert: false, enabled: true, parts: Vec::new(), effects: Vec::new() });
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
