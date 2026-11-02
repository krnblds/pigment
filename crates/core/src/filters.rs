//! Filters (adjustment layers) and anchor points.
//!
//! A filter changes pixels that already exist: levels, HSL, blur, warp,
//! grow / shrink... Filters sit in ordered stacks with enable toggles in three
//! places:
//!
//! - `Mask::filters`: run on the layer's evaluated mask (painted pixels x
//!   generator x parts x invert), e.g. blur, grow, fill holes, warp.
//! - `Layer::filters`: run on the composited stack right after the layer,
//!   inside the layer's mask (the whole surface when it has none).
//! - A filter layer (`LayerKind::Filter`): filters the stack below it, gated
//!   by its own mask and opacity (an adjustment layer).
//!
//! Spatial filters work in texture space. Every neighbourhood tap reads
//! through the jump-flood padding map, so taps that leave a UV island take
//! the island's nearest texel instead of the background and seams don't
//! break (the same scheme as the curvature blur).
//!
//! **Anchors** (`Layer::anchor`): the composited stack right after an anchor
//! layer (or at the end of an anchor folder) is kept: height, the layer's
//! mask (coverage) and colour luminance. Generators of layers above read it
//! through `Generator::input` (instead of only the mesh bakes), e.g. edge
//! wear on painted scratches or dirt that gathers in painted dents, and the
//! `anchor` generator uses an anchor channel directly as a mask.
//!
//! Everything here has serde defaults, so projects without filters or
//! anchors load and save unchanged.

use crate::Channel;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FilterKind {
    /// Input black / white / gamma and output black / white, per RGB channel and master.
    Levels,
    /// Hue shift, saturation and lightness.
    Hsl,
    /// Colour balance: RGB offsets for shadows, midtones and highlights.
    ColorBalance,
    /// 1 - x (height: -h).
    Invert,
    /// Clamp values into [min, max].
    Clamp,
    /// Gaussian blur (separable, seam-aware).
    Blur,
    /// Blur along one texture-space direction (motion blur).
    DirectionalBlur,
    /// Unsharp mask.
    Sharpen,
    /// Displace the image by world-space noise (wobbly edges, organic breakup).
    Warp,
    /// Smear the image along the slope of a noise (or the stack's height) field.
    SlopeBlur,
    /// Sobel edge strength.
    EdgeDetect,
    /// Turn the stack's height into normal detail (with a strength), optionally flattening it.
    HeightToNormal,
    /// Close small holes in a mask (grow, then shrink).
    FillHoles,
    /// Dilate a mask.
    Grow,
    /// Erode a mask.
    Shrink,
    /// "MatFinish" noise: world-space value noise added to colour / roughness / height / mask.
    NoiseOverlay,
}

/// Where a filter stack is applied (MCP `target`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FilterTarget {
    /// The layer's composited result (inside its mask); for a filter layer, the stack below.
    Layer,
    /// The layer's evaluated mask.
    Mask,
}

impl FilterKind {
    pub const ALL: [FilterKind; 16] = [
        FilterKind::Levels,
        FilterKind::Hsl,
        FilterKind::ColorBalance,
        FilterKind::Invert,
        FilterKind::Clamp,
        FilterKind::Blur,
        FilterKind::DirectionalBlur,
        FilterKind::Sharpen,
        FilterKind::Warp,
        FilterKind::SlopeBlur,
        FilterKind::EdgeDetect,
        FilterKind::HeightToNormal,
        FilterKind::FillHoles,
        FilterKind::Grow,
        FilterKind::Shrink,
        FilterKind::NoiseOverlay,
    ];
    pub fn id(self) -> &'static str {
        match self {
            FilterKind::Levels => "levels",
            FilterKind::Hsl => "hsl",
            FilterKind::ColorBalance => "color_balance",
            FilterKind::Invert => "invert",
            FilterKind::Clamp => "clamp",
            FilterKind::Blur => "blur",
            FilterKind::DirectionalBlur => "directional_blur",
            FilterKind::Sharpen => "sharpen",
            FilterKind::Warp => "warp",
            FilterKind::SlopeBlur => "slope_blur",
            FilterKind::EdgeDetect => "edge_detect",
            FilterKind::HeightToNormal => "height_to_normal",
            FilterKind::FillHoles => "fill_holes",
            FilterKind::Grow => "grow",
            FilterKind::Shrink => "shrink",
            FilterKind::NoiseOverlay => "noise_overlay",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            FilterKind::Levels => "Levels",
            FilterKind::Hsl => "Hue / saturation / lightness",
            FilterKind::ColorBalance => "Colour balance",
            FilterKind::Invert => "Invert",
            FilterKind::Clamp => "Clamp",
            FilterKind::Blur => "Blur",
            FilterKind::DirectionalBlur => "Directional blur",
            FilterKind::Sharpen => "Sharpen",
            FilterKind::Warp => "Warp",
            FilterKind::SlopeBlur => "Slope blur",
            FilterKind::EdgeDetect => "Edge detect",
            FilterKind::HeightToNormal => "Height to normal",
            FilterKind::FillHoles => "Fill holes",
            FilterKind::Grow => "Grow",
            FilterKind::Shrink => "Shrink",
            FilterKind::NoiseOverlay => "Noise overlay (MatFinish)",
        }
    }
    pub fn blurb(self) -> &'static str {
        match self {
            FilterKind::Levels => "Remap values: input black / white / gamma, then output black / white.",
            FilterKind::Hsl => "Shift the hue, change saturation and lightness of the colour.",
            FilterKind::ColorBalance => "Push shadows, midtones and highlights towards a colour.",
            FilterKind::Invert => "Flip values: 1 - x (height turns into -height).",
            FilterKind::Clamp => "Keep values between a minimum and a maximum.",
            FilterKind::Blur => "Soften with a seam-aware gaussian blur.",
            FilterKind::DirectionalBlur => "Smear along one direction (texture space).",
            FilterKind::Sharpen => "Exaggerate local detail (unsharp mask).",
            FilterKind::Warp => "Push pixels around with world-space noise: wobbly, organic edges.",
            FilterKind::SlopeBlur => "Smear down the slopes of a noise field (or the painted height): eroded, dripping edges.",
            FilterKind::EdgeDetect => "Keep only the edges (outline of shapes).",
            FilterKind::HeightToNormal => "Bake the stack's height into normal detail, with a strength.",
            FilterKind::FillHoles => "Close small holes and gaps in a mask.",
            FilterKind::Grow => "Expand the white areas of a mask.",
            FilterKind::Shrink => "Shrink the white areas of a mask.",
            FilterKind::NoiseOverlay => "Add fine world-space noise to colour, roughness, height or a mask.",
        }
    }
    pub fn from_id(s: &str) -> Option<FilterKind> {
        let s = s.to_ascii_lowercase().replace([' ', '-'], "_");
        Self::ALL.into_iter().find(|k| k.id() == s).or(match s.as_str() {
            "hue_saturation" | "hue" | "hsv" => Some(FilterKind::Hsl),
            "colour_balance" | "balance" => Some(FilterKind::ColorBalance),
            "gaussian_blur" => Some(FilterKind::Blur),
            "motion_blur" | "dir_blur" => Some(FilterKind::DirectionalBlur),
            "dilate" | "expand" => Some(FilterKind::Grow),
            "erode" | "contract" => Some(FilterKind::Shrink),
            "close" | "fill" => Some(FilterKind::FillHoles),
            "edges" | "edge" => Some(FilterKind::EdgeDetect),
            "matfinish" | "noise" | "mat_finish" => Some(FilterKind::NoiseOverlay),
            "height_normal" | "normal_from_height" => Some(FilterKind::HeightToNormal),
            _ => None,
        })
    }
    /// GPU id shared with `filter.wgsl` (0 = none).
    pub fn gpu_id(self) -> u32 {
        self as u32 + 1
    }
    /// Can run on a mask.
    pub fn on_mask(self) -> bool {
        !matches!(self, FilterKind::Hsl | FilterKind::ColorBalance | FilterKind::HeightToNormal)
    }
    /// Can run on the composited channels (layer result / filter layer).
    pub fn on_layer(self) -> bool {
        !matches!(self, FilterKind::FillHoles | FilterKind::Grow | FilterKind::Shrink)
    }
    /// Reads neighbouring texels (needs margins in partial composites).
    pub fn is_spatial(self) -> bool {
        matches!(
            self,
            FilterKind::Blur
                | FilterKind::DirectionalBlur
                | FilterKind::Sharpen
                | FilterKind::Warp
                | FilterKind::SlopeBlur
                | FilterKind::EdgeDetect
                | FilterKind::HeightToNormal
                | FilterKind::FillHoles
                | FilterKind::Grow
                | FilterKind::Shrink
        )
    }
    /// Number of GPU passes (separable filters take two, fill holes four).
    pub fn passes(self) -> u32 {
        match self {
            FilterKind::Blur | FilterKind::Grow | FilterKind::Shrink => 2,
            FilterKind::FillHoles => 4,
            _ => 1,
        }
    }
    /// Channels a layer filter changes when none are listed.
    pub fn default_channels(self) -> &'static [Channel] {
        use Channel::*;
        match self {
            FilterKind::Hsl | FilterKind::ColorBalance => &[BaseColor],
            FilterKind::Levels | FilterKind::Invert | FilterKind::Clamp => &[BaseColor],
            FilterKind::HeightToNormal => &[Height, Normal],
            FilterKind::NoiseOverlay => &[BaseColor, Roughness],
            FilterKind::EdgeDetect => &[BaseColor],
            _ => &[BaseColor, Roughness, Metallic, Height, Emissive],
        }
    }
}

fn yes() -> bool {
    true
}

/// Levels per channel: [r, g, b, master].
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Levels {
    pub in_black: [f32; 4],
    pub in_white: [f32; 4],
    pub gamma: [f32; 4],
    pub out_black: [f32; 4],
    pub out_white: [f32; 4],
}

impl Default for Levels {
    fn default() -> Self {
        Levels { in_black: [0.0; 4], in_white: [1.0; 4], gamma: [1.0; 4], out_black: [0.0; 4], out_white: [1.0; 4] }
    }
}

impl Levels {
    pub fn is_identity(&self) -> bool {
        *self == Levels::default()
    }
}

/// Filter parameters. Each kind reads the fields it needs (see the docs of
/// each field); the rest keep their defaults and are not written to disk.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct FilterParams {
    /// Blur / sharpen / grow / shrink / fill holes / edge detect radius, warp
    /// and slope blur distance: texels at 2048 (scaled with the resolution).
    pub radius: f32,
    /// Strength: sharpen amount, warp / slope blur / noise / height-to-normal strength, edge gain.
    pub amount: f32,
    /// Directional blur angle, degrees (0 = along +u).
    pub angle: f32,
    /// Noise frequency per metre (warp, slope blur, noise overlay).
    pub scale: f32,
    pub seed: u32,
    #[serde(skip_serializing_if = "Levels::is_identity")]
    pub levels: Levels,
    /// HSL: hue shift in degrees, saturation and lightness offsets (-1..1).
    pub hue: f32,
    pub saturation: f32,
    pub lightness: f32,
    /// Colour balance offsets (-1..1 per RGB channel).
    pub shadows: [f32; 3],
    pub midtones: [f32; 3],
    pub highlights: [f32; 3],
    /// Clamp range.
    pub min: f32,
    pub max: f32,
    /// Slope blur: follow the stack's height instead of noise. Height to normal: keep the height.
    pub use_height: bool,
}

impl Default for FilterParams {
    fn default() -> Self {
        FilterParams {
            radius: 4.0,
            amount: 0.5,
            angle: 0.0,
            scale: 4.0,
            seed: 1,
            levels: Levels::default(),
            hue: 0.0,
            saturation: 0.0,
            lightness: 0.0,
            shadows: [0.0; 3],
            midtones: [0.0; 3],
            highlights: [0.0; 3],
            min: 0.0,
            max: 1.0,
            use_height: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Filter {
    pub kind: FilterKind,
    #[serde(default = "yes")]
    pub enabled: bool,
    #[serde(default)]
    pub params: FilterParams,
    /// Layer filters: channels to change (empty = the kind's defaults).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub channels: Vec<Channel>,
}

impl Filter {
    pub fn new(kind: FilterKind) -> Self {
        let mut params = FilterParams::default();
        match kind {
            FilterKind::Blur => params.radius = 6.0,
            FilterKind::DirectionalBlur => params.radius = 12.0,
            FilterKind::Sharpen => (params.radius, params.amount) = (2.0, 1.0),
            FilterKind::Warp => (params.radius, params.scale) = (8.0, 6.0),
            FilterKind::SlopeBlur => (params.radius, params.scale) = (16.0, 4.0),
            FilterKind::EdgeDetect => (params.radius, params.amount) = (1.5, 4.0),
            FilterKind::HeightToNormal => (params.amount, params.use_height) = (1.0, true),
            FilterKind::FillHoles => params.radius = 6.0,
            FilterKind::Grow | FilterKind::Shrink => params.radius = 4.0,
            FilterKind::NoiseOverlay => (params.amount, params.scale) = (0.15, 40.0),
            _ => {}
        }
        Filter { kind, enabled: true, params, channels: Vec::new() }
    }
    /// Channels this layer filter changes.
    pub fn channel_list(&self) -> Vec<Channel> {
        if self.channels.is_empty() {
            self.kind.default_channels().to_vec()
        } else {
            self.channels.clone()
        }
    }
    /// GPU channel bits: 1 colour, 2 roughness, 4 metallic, 8 height, 16 normal, 32 emission.
    pub fn channel_bits(&self) -> u32 {
        self.channel_list()
            .iter()
            .map(|c| match c {
                Channel::BaseColor => 1,
                Channel::Roughness => 2,
                Channel::Metallic => 4,
                Channel::Height => 8,
                Channel::Normal => 16,
                Channel::Emissive => 32,
                _ => 0,
            })
            .fold(0, |a, b| a | b)
    }
    /// How far (texels at resolution `res`) this filter reads from a texel.
    pub fn reach(&self, res: u32) -> u32 {
        if !self.enabled || !self.kind.is_spatial() {
            return 0;
        }
        let r = self.params.radius.abs() * res as f32 / 2048.0;
        let per_pass = match self.kind {
            FilterKind::Sharpen | FilterKind::EdgeDetect => r.max(1.0),
            FilterKind::HeightToNormal => 1.0,
            FilterKind::Warp | FilterKind::SlopeBlur => r * self.params.amount.abs().max(1.0),
            _ => r,
        };
        (per_pass.ceil() as u32 + 1) * self.kind.passes()
    }
}

/// Total reach of a filter stack.
pub fn stack_reach(filters: &[Filter], res: u32) -> u32 {
    filters.iter().map(|f| f.reach(res)).sum()
}

/// True if any filter of the stack is on.
pub fn any_enabled(filters: &[Filter]) -> bool {
    filters.iter().any(|f| f.enabled)
}

/// Which composited channel of an anchor a generator reads.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnchorChannel {
    /// Composited height (painted dents, scratches, stacked fills).
    Height,
    /// The anchor layer's mask x coverage x opacity.
    Mask,
    /// Luminance of the composited base colour.
    Color,
}

impl AnchorChannel {
    pub const ALL: [AnchorChannel; 3] = [AnchorChannel::Height, AnchorChannel::Mask, AnchorChannel::Color];
    pub fn id(self) -> &'static str {
        match self {
            AnchorChannel::Height => "height",
            AnchorChannel::Mask => "mask",
            AnchorChannel::Color => "color",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            AnchorChannel::Height => "Anchor height",
            AnchorChannel::Mask => "Anchor mask",
            AnchorChannel::Color => "Anchor colour",
        }
    }
    pub fn from_id(s: &str) -> Option<AnchorChannel> {
        match s.to_ascii_lowercase().as_str() {
            "height" => Some(AnchorChannel::Height),
            "mask" | "coverage" | "alpha" => Some(AnchorChannel::Mask),
            "color" | "colour" | "luminance" | "base_color" => Some(AnchorChannel::Color),
            _ => None,
        }
    }
    /// 1-based GPU mode (0 = bake).
    pub fn gpu_mode(self) -> u32 {
        self as u32 + 1
    }
}

/// A generator's input: the mesh bakes (default, `None` on the generator) or
/// an anchor's channel. The anchor's relief (value minus its local average
/// over `radius` texels at 2048) is added to the curvature the generator sees,
/// times `strength`: raised rims count as convex edges, dents as cavities.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct GenInput {
    /// Anchor name (`Layer::anchor`).
    pub anchor: String,
    pub channel: AnchorChannel,
    #[serde(default = "default_input_strength")]
    pub strength: f32,
    #[serde(default = "default_input_radius")]
    pub radius: f32,
}

fn default_input_strength() -> f32 {
    4.0
}
fn default_input_radius() -> f32 {
    6.0
}

impl GenInput {
    pub fn new(anchor: &str, channel: AnchorChannel) -> Self {
        GenInput { anchor: anchor.to_string(), channel, strength: default_input_strength(), radius: default_input_radius() }
    }
    /// Texels the relief lookup reads around a texel at resolution `res`.
    pub fn reach(&self, res: u32) -> u32 {
        (self.radius.abs() * res as f32 / 2048.0).ceil() as u32 + 1
    }
}

impl crate::Document {
    /// The layer that is anchor `name` (case-insensitive).
    pub fn anchor_layer(&self, name: &str) -> Option<usize> {
        let n = name.to_ascii_lowercase();
        self.layers.iter().position(|l| l.anchor.as_ref().is_some_and(|a| a.to_ascii_lowercase() == n))
    }
    /// Names of every anchor, bottom to top.
    pub fn anchor_names(&self) -> Vec<String> {
        self.layers.iter().filter_map(|l| l.anchor.clone()).collect()
    }
    /// Anchors that layer `i` can read: anchors composited before it (below
    /// it in the plan, and not inside... an anchor folder can't be read by its own children).
    pub fn anchors_below(&self, i: usize) -> Vec<String> {
        let plan = self.composite_plan();
        let id = self.layers[i].id;
        let ancestors = self.ancestors(id);
        let mut out = Vec::new();
        for st in plan {
            let k = match st {
                crate::folders::Step::Layer(k) => k,
                crate::folders::Step::End(k) => k,
                crate::folders::Step::Begin(_) => continue,
            };
            if k == i {
                break;
            }
            if let Some(a) = &self.layers[k].anchor {
                if !ancestors.contains(&self.layers[k].id) {
                    out.push(a.clone());
                }
            }
        }
        out
    }
    /// A new stand-alone filter layer.
    pub fn new_filter_layer(&mut self, name: &str, filters: Vec<Filter>) -> crate::Layer {
        let mut l = self.new_fill_layer(name);
        l.kind = crate::LayerKind::Filter {};
        l.filters = filters;
        l
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::*;

    #[test]
    fn filter_kinds_round_trip_and_targets() {
        for k in FilterKind::ALL {
            assert_eq!(FilterKind::from_id(k.id()), Some(k));
            assert!(k.on_mask() || k.on_layer());
        }
        assert_eq!(FilterKind::from_id("dilate"), Some(FilterKind::Grow));
        assert!(!FilterKind::Hsl.on_mask());
        assert!(!FilterKind::Grow.on_layer());
        assert_eq!(FilterKind::Blur.passes(), 2);
    }

    #[test]
    fn reach_scales_with_resolution_and_skips_disabled() {
        let mut f = Filter::new(FilterKind::Blur);
        f.params.radius = 8.0;
        assert_eq!(f.reach(2048), 18);
        assert_eq!(f.reach(4096), 34);
        f.enabled = false;
        assert_eq!(f.reach(4096), 0);
        assert_eq!(Filter::new(FilterKind::Levels).reach(4096), 0);
    }

    #[test]
    fn old_projects_load_without_filters_or_anchors() {
        let d = Document::demo();
        let json = serde_json::to_string(&d).unwrap();
        assert!(!json.contains("filters") && !json.contains("anchor") && !json.contains("\"input\""));
        let back: Document = serde_json::from_str(&json).unwrap();
        assert_eq!(back, d);
    }

    #[test]
    fn filters_and_anchors_round_trip() {
        let mut d = Document::demo();
        d.layers[0].anchor = Some("Base".into());
        let mut lv = Filter::new(FilterKind::Levels);
        lv.params.levels.gamma[3] = 2.0;
        d.layers[1].filters.push(lv);
        d.layers[1].mask.as_mut().unwrap().filters.push(Filter::new(FilterKind::Grow));
        d.layers[2].mask.as_mut().unwrap().generator.as_mut().unwrap().input = Some(GenInput::new("Base", AnchorChannel::Height));
        let f = d.new_filter_layer("Blur all", vec![Filter::new(FilterKind::Blur)]);
        d.layers.push(f);
        let json = serde_json::to_string(&d).unwrap();
        let back: Document = serde_json::from_str(&json).unwrap();
        assert_eq!(back, d);
        assert_eq!(back.anchor_layer("base"), Some(0));
        assert_eq!(back.anchors_below(2), vec!["Base".to_string()]);
        assert!(back.anchors_below(0).is_empty());
    }
}
