//! Foliage cards: procedural leaves, twigs, needle sprays, blossoms, grass
//! tufts, ivy sprigs and moss, drawn on the CPU into the cells of a foliage
//! atlas (a decal-atlas sheet project, see `tile`).
//!
//! Nothing here is painted by hand. A cell is a [`LeafSpec`]: an outline
//! ([`LeafShape`]), an arrangement of several leaves on stems
//! ([`Arrangement`]), venation, edge serration and colour variation (hue
//! jitter, autumn, dry edges, holes and insect bites). [`render_cell`] turns
//! it into the maps a foliage shader wants: base colour + alpha (from the
//! shape), height (veins, leaf dome, stacking), roughness, a translucency
//! (back-lit / subsurface) colour and a thickness.
//!
//! Coordinates: a cell is `size_m` metres; elements are laid out in
//! arbitrary units with the stem base at the origin and "up" = +y, then fitted
//! into the cell. Leaf-local space: x across, y along the leaf (0 = base,
//! 1 = tip), in units of the leaf length.
//!
//! The same generator draws Pigment's built-in card library
//! ([`builtin_cells`]) used by the foliage brush on 3D models.

use glam::Vec2;
use serde::{Deserialize, Serialize};
use std::f32::consts::PI;

/// Leaf outline.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LeafShape {
    /// Egg-shaped, widest below the middle (cherry, pagoda-tree leaflets).
    #[default]
    Ovate,
    /// Long and narrow, tapering to a point (willow, bamboo, dandelion).
    Lanceolate,
    /// Oval, widest in the middle.
    Elliptic,
    /// Heart-shaped with a notch at the base (katsura, pothos).
    Cordate,
    /// Palm-like lobes from one point (Japanese maple).
    Palmate,
    /// Fan with a notch in the middle of the rim (ginkgo).
    Ginkgo,
    /// Three to five shallow, rounded lobes (English ivy).
    Ivy,
    /// A thin needle (pine).
    Needle,
    /// A grass blade: widest at the base, long pointed tip.
    Grass,
    /// A blossom petal: widest near the tip, notched (cherry).
    Petal,
    /// A tiny moss frond.
    Moss,
}

impl LeafShape {
    pub const ALL: [LeafShape; 11] = [
        LeafShape::Ovate,
        LeafShape::Lanceolate,
        LeafShape::Elliptic,
        LeafShape::Cordate,
        LeafShape::Palmate,
        LeafShape::Ginkgo,
        LeafShape::Ivy,
        LeafShape::Needle,
        LeafShape::Grass,
        LeafShape::Petal,
        LeafShape::Moss,
    ];
    pub fn id(self) -> &'static str {
        match self {
            LeafShape::Ovate => "ovate",
            LeafShape::Lanceolate => "lanceolate",
            LeafShape::Elliptic => "elliptic",
            LeafShape::Cordate => "cordate",
            LeafShape::Palmate => "palmate",
            LeafShape::Ginkgo => "ginkgo",
            LeafShape::Ivy => "ivy",
            LeafShape::Needle => "needle",
            LeafShape::Grass => "grass",
            LeafShape::Petal => "petal",
            LeafShape::Moss => "moss",
        }
    }
    pub fn from_id(s: &str) -> Option<LeafShape> {
        let s = s.to_ascii_lowercase();
        let s = match s.as_str() {
            "maple" => "palmate",
            "fan" => "ginkgo",
            "heart" => "cordate",
            "blade" => "grass",
            "lance" => "lanceolate",
            "oval" => "elliptic",
            other => other,
        };
        LeafShape::ALL.into_iter().find(|k| k.id() == s)
    }
    /// Lobed outlines measured from a centre (the petiole joint).
    fn is_polar(self) -> bool {
        matches!(self, LeafShape::Palmate | LeafShape::Ginkgo | LeafShape::Ivy)
    }
    /// Default width / length.
    fn default_aspect(self) -> f32 {
        match self {
            LeafShape::Ovate => 0.55,
            LeafShape::Lanceolate => 0.22,
            LeafShape::Elliptic => 0.5,
            LeafShape::Cordate => 0.8,
            LeafShape::Palmate | LeafShape::Ginkgo | LeafShape::Ivy => 1.0,
            LeafShape::Needle => 0.035,
            LeafShape::Grass => 0.07,
            LeafShape::Petal => 0.75,
            LeafShape::Moss => 0.3,
        }
    }
}

/// How the leaves of a cell are put together.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Arrangement {
    /// One leaf on a short petiole.
    #[default]
    Single,
    /// Leaves alternating along a stem (a twig, an ivy sprig).
    Twig,
    /// Pinnately compound leaves: leaflets in opposite pairs along a rachis
    /// plus a terminal leaflet (pagoda tree, ash, fern). `count` compound
    /// leaves on a twig, `lobes` = leaflet pairs.
    Compound,
    /// Blades fanning out from one base (grass, sedge).
    Tuft,
    /// Needle fascicles along a twig (`lobes` needles each, black pine: 2).
    Spray,
    /// Flowers of `lobes` petals on short stalks around a twig (blossom).
    Cluster,
    /// Leaves radiating from a centre, seen from above (weeds, plantain).
    Rosette,
    /// Many small fronds in a dome (a moss cushion seen from the side).
    Clump,
    /// Leaves dropped at random over the cell (fallen leaves, moss patch).
    Scatter,
    /// A stem hanging from the top of the cell with leaves along it.
    Trailing,
}

impl Arrangement {
    pub const ALL: [Arrangement; 10] = [
        Arrangement::Single,
        Arrangement::Twig,
        Arrangement::Compound,
        Arrangement::Tuft,
        Arrangement::Spray,
        Arrangement::Cluster,
        Arrangement::Rosette,
        Arrangement::Clump,
        Arrangement::Scatter,
        Arrangement::Trailing,
    ];
    pub fn id(self) -> &'static str {
        match self {
            Arrangement::Single => "single",
            Arrangement::Twig => "twig",
            Arrangement::Compound => "compound",
            Arrangement::Tuft => "tuft",
            Arrangement::Spray => "spray",
            Arrangement::Cluster => "cluster",
            Arrangement::Rosette => "rosette",
            Arrangement::Clump => "clump",
            Arrangement::Scatter => "scatter",
            Arrangement::Trailing => "trailing",
        }
    }
    pub fn from_id(s: &str) -> Option<Arrangement> {
        let s = s.to_ascii_lowercase();
        let s = match s.as_str() {
            "pinnate" => "compound",
            "sprig" | "branch" => "twig",
            "needles" | "fascicles" => "spray",
            "blossom" | "flowers" => "cluster",
            "fallen" | "patch" => "scatter",
            "hanging" => "trailing",
            other => other,
        };
        Arrangement::ALL.into_iter().find(|k| k.id() == s)
    }
}

/// How a card is set on a surface by the foliage brush / scatter.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mount {
    /// Standing up from the surface, base at the bottom edge of the cell
    /// (grass, weeds, moss tufts).
    #[default]
    Upright,
    /// Lying on the surface (fallen leaves, moss patches, rosettes).
    Flat,
    /// Against a wall, tilted out a little (ivy leaves).
    Wall,
    /// Hanging down from its top edge (trailing plants on balconies).
    Hanging,
}

impl Mount {
    pub const ALL: [Mount; 4] = [Mount::Upright, Mount::Flat, Mount::Wall, Mount::Hanging];
    pub fn id(self) -> &'static str {
        match self {
            Mount::Upright => "upright",
            Mount::Flat => "flat",
            Mount::Wall => "wall",
            Mount::Hanging => "hanging",
        }
    }
    pub fn from_id(s: &str) -> Option<Mount> {
        Mount::ALL.into_iter().find(|k| k.id() == s.to_ascii_lowercase())
    }
}

/// Card geometry used for each instance of a cell.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CardMesh {
    /// One quad.
    #[default]
    Quad,
    /// Two quads crossed at 90 degrees (grass tufts, weeds).
    Cross,
    /// Three quads at 60 degrees.
    Star,
}

impl CardMesh {
    pub const ALL: [CardMesh; 3] = [CardMesh::Quad, CardMesh::Cross, CardMesh::Star];
    pub fn id(self) -> &'static str {
        match self {
            CardMesh::Quad => "quad",
            CardMesh::Cross => "cross",
            CardMesh::Star => "star",
        }
    }
    pub fn from_id(s: &str) -> Option<CardMesh> {
        CardMesh::ALL.into_iter().find(|k| k.id() == s.to_ascii_lowercase())
    }
    /// Number of quads.
    pub fn quads(self) -> usize {
        match self {
            CardMesh::Quad => 1,
            CardMesh::Cross => 2,
            CardMesh::Star => 3,
        }
    }
}

/// Everything that describes one foliage cell. All fields have defaults, so
/// a spec can be given partially (MCP / JSON) on top of a preset.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct LeafSpec {
    pub shape: LeafShape,
    pub arrangement: Arrangement,
    /// Leaves (twig / tuft / rosette / scatter / clump), compound leaves
    /// (compound), fascicles (spray) or flowers (cluster).
    pub count: u32,
    /// Leaf width / length; 0 = the shape's default.
    pub aspect: f32,
    /// Lobes (palmate / ivy), leaflet pairs (compound), needles per
    /// fascicle (spray), petals (cluster).
    pub lobes: u32,
    /// 0..1: how deep the lobes are cut (palmate / ivy / ginkgo notch).
    pub lobe_depth: f32,
    /// Total angle the lobes / tuft / fascicle spread over, degrees (0 = default).
    pub spread: f32,
    /// 0..1 edge tooth depth.
    pub serration: f32,
    /// Teeth along each side (per lobe for lobed leaves).
    pub teeth: u32,
    /// 0..1 vein strength (height and colour).
    pub venation: f32,
    /// Secondary veins per side.
    pub veins: u32,
    /// Angle of the secondary veins to the midrib, degrees.
    pub vein_angle: f32,
    /// Base colour (sRGB 0..1).
    pub color: [f32; 3],
    /// Colour the leaf shades to towards its tip / rim.
    pub tip_color: [f32; 3],
    /// How strongly the leaf shades to `tip_color` (0..1).
    pub tip_amount: f32,
    pub vein_color: [f32; 3],
    /// 0..1 per-leaf hue jitter.
    pub hue_jitter: f32,
    /// 0..1 per-leaf brightness jitter.
    pub value_jitter: f32,
    /// 0..1: green -> yellow -> `autumn_color`.
    pub autumn: f32,
    /// Per-leaf +- variation of `autumn`.
    pub autumn_jitter: f32,
    /// Where full autumn ends up (maple red, ginkgo yellow).
    pub autumn_color: [f32; 3],
    /// 0..1 width of a dry brown rim.
    pub dry_edges: f32,
    pub dry_color: [f32; 3],
    /// 0..1 density of holes eaten through the blade.
    pub holes: f32,
    /// 0..1 chance per leaf of insect bites out of the edge.
    pub bites: f32,
    /// 0..1 how much light passes through (back-lit glow).
    pub translucency: f32,
    /// Colour of the light coming through; `None` = derived from the leaf colour.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub translucency_color: Option<[f32; 3]>,
    pub roughness: f32,
    pub stem_color: [f32; 3],
    /// Stem width relative to the leaf length (0 = no stem).
    pub stem_width: f32,
    /// Sideways bend of blades and needles (-1..1).
    pub bend: f32,
    /// Waviness of the main stem (0..1).
    pub wave: f32,
    /// Leaf length relative to the stem / cell (0 = default).
    pub leaf_size: f32,
    /// Blossom: draw stamens in the flower centre.
    pub stamens: bool,
    pub seed: u32,
}

impl Default for LeafSpec {
    fn default() -> Self {
        LeafSpec {
            shape: LeafShape::Ovate,
            arrangement: Arrangement::Single,
            count: 1,
            aspect: 0.0,
            lobes: 5,
            lobe_depth: 0.5,
            spread: 0.0,
            serration: 0.0,
            teeth: 12,
            venation: 0.6,
            veins: 7,
            vein_angle: 50.0,
            color: [0.22, 0.38, 0.12],
            tip_color: [0.35, 0.48, 0.14],
            tip_amount: 0.35,
            vein_color: [0.42, 0.55, 0.25],
            hue_jitter: 0.25,
            value_jitter: 0.2,
            autumn: 0.0,
            autumn_jitter: 0.2,
            autumn_color: [0.62, 0.07, 0.04],
            dry_edges: 0.0,
            dry_color: [0.36, 0.24, 0.12],
            holes: 0.0,
            bites: 0.0,
            translucency: 0.6,
            translucency_color: None,
            roughness: 0.55,
            stem_color: [0.25, 0.2, 0.12],
            stem_width: 0.02,
            bend: 0.0,
            wave: 0.2,
            leaf_size: 0.0,
            stamens: true,
            seed: 0,
        }
    }
}

/// One cell of a foliage atlas (or of the built-in card library).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FoliageCell {
    pub name: String,
    /// Card size in metres [width, height].
    pub size_m: [f32; 2],
    #[serde(default)]
    pub spec: LeafSpec,
    #[serde(default)]
    pub mount: Mount,
    #[serde(default)]
    pub mesh: CardMesh,
    /// The preset this cell started from (informational).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub preset: String,
}

/// Named starting points: (spec, card size in metres, mount, mesh).
pub fn preset(name: &str) -> Option<(LeafSpec, [f32; 2], Mount, CardMesh)> {
    let d = LeafSpec::default();
    let n = name.to_ascii_lowercase().replace(['-', ' '], "_");
    let r = match n.as_str() {
        // Styphnolobium japonicum: pinnate, 5-8 pairs of ovate leaflets, glossy dark green
        "pagoda_tree" | "pagoda" | "japanese_pagoda_tree" => (
            LeafSpec { shape: LeafShape::Ovate, arrangement: Arrangement::Compound, count: 3, lobes: 6, aspect: 0.48, venation: 0.4, veins: 5, color: [0.2, 0.34, 0.1], tip_color: [0.3, 0.44, 0.14], roughness: 0.42, stem_color: [0.3, 0.32, 0.14], seed: 11, ..d.clone() },
            [0.45, 0.55],
            Mount::Upright,
            CardMesh::Quad,
        ),
        // Acer palmatum: 7 deep pointed serrated lobes on a twig
        "maple" | "japanese_maple" => (
            LeafSpec { shape: LeafShape::Palmate, arrangement: Arrangement::Twig, count: 5, lobes: 7, lobe_depth: 0.72, spread: 285.0, serration: 0.35, teeth: 7, venation: 0.6, color: [0.28, 0.42, 0.1], tip_color: [0.45, 0.5, 0.12], autumn_color: [0.66, 0.06, 0.04], stem_color: [0.45, 0.12, 0.08], translucency: 0.75, seed: 21, ..d.clone() },
            [0.35, 0.4],
            Mount::Upright,
            CardMesh::Quad,
        ),
        "maple_leaf" => (
            LeafSpec { shape: LeafShape::Palmate, lobes: 7, lobe_depth: 0.72, spread: 285.0, serration: 0.35, teeth: 7, color: [0.28, 0.42, 0.1], tip_color: [0.45, 0.5, 0.12], autumn_color: [0.66, 0.06, 0.04], stem_color: [0.45, 0.12, 0.08], translucency: 0.75, seed: 22, ..d.clone() },
            [0.09, 0.1],
            Mount::Flat,
            CardMesh::Quad,
        ),
        "maple_autumn" => (
            LeafSpec { shape: LeafShape::Palmate, arrangement: Arrangement::Twig, count: 5, lobes: 7, lobe_depth: 0.72, spread: 285.0, serration: 0.35, teeth: 7, autumn: 0.85, autumn_jitter: 0.3, color: [0.28, 0.42, 0.1], tip_color: [0.7, 0.2, 0.05], autumn_color: [0.66, 0.06, 0.04], stem_color: [0.45, 0.12, 0.08], dry_edges: 0.25, translucency: 0.8, seed: 23, ..d.clone() },
            [0.35, 0.4],
            Mount::Upright,
            CardMesh::Quad,
        ),
        // Ginkgo biloba: fans on short shoots, fine radiating veins, golden in autumn
        "ginkgo" => (
            LeafSpec { shape: LeafShape::Ginkgo, arrangement: Arrangement::Twig, count: 6, leaf_size: 0.22, lobe_depth: 0.6, spread: 150.0, venation: 0.5, veins: 28, color: [0.36, 0.5, 0.14], tip_color: [0.45, 0.55, 0.16], autumn_color: [0.93, 0.75, 0.08], stem_color: [0.4, 0.33, 0.2], roughness: 0.5, seed: 31, ..d.clone() },
            [0.3, 0.38],
            Mount::Upright,
            CardMesh::Quad,
        ),
        "ginkgo_leaf" => (
            LeafSpec { shape: LeafShape::Ginkgo, lobe_depth: 0.6, spread: 150.0, venation: 0.5, veins: 28, color: [0.36, 0.5, 0.14], autumn: 0.9, autumn_color: [0.93, 0.75, 0.08], stem_color: [0.5, 0.42, 0.2], seed: 32, ..d.clone() },
            [0.07, 0.08],
            Mount::Flat,
            CardMesh::Quad,
        ),
        // Prunus serrulata: five notched pale pink petals, pink-red centre, stamens
        "cherry_blossom" | "sakura" => (
            LeafSpec { shape: LeafShape::Petal, arrangement: Arrangement::Cluster, count: 9, lobes: 5, aspect: 0.78, venation: 0.25, veins: 5, color: [0.98, 0.8, 0.86], tip_color: [1.0, 0.95, 0.96], tip_amount: 0.6, vein_color: [0.95, 0.68, 0.76], hue_jitter: 0.1, value_jitter: 0.08, translucency: 0.9, translucency_color: Some([1.0, 0.78, 0.84]), roughness: 0.5, stem_color: [0.35, 0.18, 0.15], seed: 41, ..d.clone() },
            [0.3, 0.3],
            Mount::Upright,
            CardMesh::Quad,
        ),
        "cherry_leaf" => (
            LeafSpec { shape: LeafShape::Ovate, arrangement: Arrangement::Twig, count: 6, aspect: 0.45, serration: 0.4, teeth: 22, venation: 0.6, veins: 9, color: [0.2, 0.36, 0.1], stem_color: [0.38, 0.16, 0.12], seed: 42, ..d.clone() },
            [0.3, 0.4],
            Mount::Upright,
            CardMesh::Quad,
        ),
        "cherry_petals" => (
            LeafSpec { shape: LeafShape::Petal, arrangement: Arrangement::Scatter, count: 14, aspect: 0.78, color: [0.98, 0.82, 0.88], tip_color: [1.0, 0.95, 0.96], tip_amount: 0.6, venation: 0.15, value_jitter: 0.1, translucency: 0.9, seed: 43, ..d.clone() },
            [0.18, 0.18],
            Mount::Flat,
            CardMesh::Quad,
        ),
        // Pinus thunbergii: stiff dark needles in pairs along a twig
        "black_pine" | "pine" | "japanese_black_pine" => (
            LeafSpec { shape: LeafShape::Needle, arrangement: Arrangement::Spray, count: 46, lobes: 2, spread: 70.0, venation: 0.0, color: [0.11, 0.21, 0.09], tip_color: [0.2, 0.3, 0.12], tip_amount: 0.4, hue_jitter: 0.1, value_jitter: 0.25, translucency: 0.35, roughness: 0.45, stem_color: [0.32, 0.22, 0.14], stem_width: 0.05, bend: 0.15, leaf_size: 0.42, seed: 51, ..d.clone() },
            [0.3, 0.45],
            Mount::Upright,
            CardMesh::Quad,
        ),
        "grass" => (
            LeafSpec { shape: LeafShape::Grass, arrangement: Arrangement::Tuft, count: 16, spread: 50.0, venation: 0.35, veins: 3, color: [0.25, 0.4, 0.12], tip_color: [0.58, 0.55, 0.25], tip_amount: 0.45, hue_jitter: 0.3, value_jitter: 0.25, translucency: 0.6, roughness: 0.6, bend: 0.35, dry_edges: 0.1, seed: 61, ..d.clone() },
            [0.3, 0.3],
            Mount::Upright,
            CardMesh::Cross,
        ),
        // Hedera: dark glossy lobed leaves with pale veins on a wandering stem
        "ivy" => (
            LeafSpec { shape: LeafShape::Ivy, arrangement: Arrangement::Twig, count: 5, leaf_size: 0.27, lobes: 5, lobe_depth: 0.38, spread: 220.0, venation: 0.8, color: [0.1, 0.22, 0.07], tip_color: [0.14, 0.26, 0.08], tip_amount: 0.2, vein_color: [0.5, 0.6, 0.38], roughness: 0.32, translucency: 0.35, stem_color: [0.3, 0.24, 0.14], wave: 0.5, seed: 71, ..d.clone() },
            [0.3, 0.4],
            Mount::Wall,
            CardMesh::Quad,
        ),
        "ivy_leaf" => (
            LeafSpec { shape: LeafShape::Ivy, lobes: 5, lobe_depth: 0.38, spread: 220.0, venation: 0.8, color: [0.1, 0.22, 0.07], vein_color: [0.5, 0.6, 0.38], roughness: 0.32, translucency: 0.35, stem_color: [0.3, 0.24, 0.14], seed: 72, ..d.clone() },
            [0.09, 0.1],
            Mount::Wall,
            CardMesh::Quad,
        ),
        "ivy_stem" => (
            LeafSpec { shape: LeafShape::Grass, arrangement: Arrangement::Single, aspect: 0.0, color: [0.3, 0.24, 0.14], stem_width: 0.0, venation: 0.0, translucency: 0.0, roughness: 0.7, seed: 73, ..d.clone() },
            [0.03, 0.2],
            Mount::Flat,
            CardMesh::Quad,
        ),
        "moss" | "moss_tuft" => (
            LeafSpec { shape: LeafShape::Moss, arrangement: Arrangement::Clump, count: 140, aspect: 0.3, venation: 0.2, color: [0.24, 0.36, 0.08], tip_color: [0.48, 0.55, 0.14], tip_amount: 0.5, hue_jitter: 0.3, value_jitter: 0.35, translucency: 0.5, roughness: 0.8, stem_width: 0.0, seed: 81, ..d.clone() },
            [0.14, 0.07],
            Mount::Upright,
            CardMesh::Cross,
        ),
        "moss_patch" => (
            LeafSpec { shape: LeafShape::Moss, arrangement: Arrangement::Scatter, count: 420, aspect: 0.35, venation: 0.1, color: [0.22, 0.34, 0.08], tip_color: [0.45, 0.52, 0.12], tip_amount: 0.5, hue_jitter: 0.3, value_jitter: 0.35, translucency: 0.4, roughness: 0.85, stem_width: 0.0, leaf_size: 0.13, seed: 82, ..d.clone() },
            [0.25, 0.25],
            Mount::Flat,
            CardMesh::Quad,
        ),
        // dandelion-like weed: deeply toothed lanceolate leaves
        "weed" | "dandelion" => (
            LeafSpec { shape: LeafShape::Lanceolate, arrangement: Arrangement::Tuft, count: 9, aspect: 0.26, serration: 0.8, teeth: 6, spread: 120.0, venation: 0.5, color: [0.2, 0.38, 0.1], hue_jitter: 0.2, bend: 0.15, translucency: 0.55, seed: 91, ..d.clone() },
            [0.22, 0.2],
            Mount::Upright,
            CardMesh::Cross,
        ),
        "weed_rosette" => (
            LeafSpec { shape: LeafShape::Lanceolate, arrangement: Arrangement::Rosette, count: 10, aspect: 0.26, serration: 0.8, teeth: 6, venation: 0.5, color: [0.2, 0.38, 0.1], hue_jitter: 0.2, seed: 92, ..d.clone() },
            [0.25, 0.25],
            Mount::Flat,
            CardMesh::Quad,
        ),
        "fern" => (
            LeafSpec { shape: LeafShape::Lanceolate, arrangement: Arrangement::Compound, count: 1, lobes: 14, aspect: 0.3, serration: 0.2, venation: 0.3, color: [0.2, 0.4, 0.1], seed: 101, ..d.clone() },
            [0.25, 0.5],
            Mount::Upright,
            CardMesh::Cross,
        ),
        "hanging_vine" | "trailing_vine" | "pothos" => (
            LeafSpec { shape: LeafShape::Cordate, arrangement: Arrangement::Trailing, count: 9, aspect: 0.75, venation: 0.5, veins: 5, color: [0.16, 0.36, 0.1], tip_color: [0.3, 0.48, 0.12], hue_jitter: 0.2, roughness: 0.35, stem_color: [0.3, 0.4, 0.15], wave: 0.6, seed: 111, ..d.clone() },
            [0.3, 0.7],
            Mount::Hanging,
            CardMesh::Quad,
        ),
        "fallen_leaves" => (
            LeafSpec { shape: LeafShape::Palmate, arrangement: Arrangement::Scatter, count: 7, lobes: 7, lobe_depth: 0.7, spread: 285.0, serration: 0.3, teeth: 7, autumn: 0.75, autumn_jitter: 0.6, dry_edges: 0.35, holes: 0.2, bites: 0.3, color: [0.3, 0.4, 0.12], autumn_color: [0.6, 0.12, 0.05], stem_color: [0.4, 0.2, 0.1], roughness: 0.7, seed: 121, ..d.clone() },
            [0.4, 0.4],
            Mount::Flat,
            CardMesh::Quad,
        ),
        "bamboo" => (
            LeafSpec { shape: LeafShape::Lanceolate, arrangement: Arrangement::Twig, count: 7, aspect: 0.17, venation: 0.4, veins: 3, color: [0.26, 0.42, 0.12], seed: 131, ..d.clone() },
            [0.3, 0.45],
            Mount::Upright,
            CardMesh::Quad,
        ),
        _ => return None,
    };
    Some(r)
}

/// Names accepted by [`preset`].
pub const PRESETS: [&str; 22] = [
    "pagoda_tree",
    "maple",
    "maple_leaf",
    "maple_autumn",
    "ginkgo",
    "ginkgo_leaf",
    "cherry_blossom",
    "cherry_leaf",
    "cherry_petals",
    "black_pine",
    "grass",
    "ivy",
    "ivy_leaf",
    "ivy_stem",
    "moss",
    "moss_patch",
    "weed",
    "weed_rosette",
    "fern",
    "hanging_vine",
    "fallen_leaves",
    "bamboo",
];

impl FoliageCell {
    /// A cell from a preset (`None` if the name is unknown).
    pub fn from_preset(name: &str, preset_name: &str) -> Option<FoliageCell> {
        let (spec, size_m, mount, mesh) = preset(preset_name)?;
        Some(FoliageCell { name: name.into(), size_m, spec, mount, mesh, preset: preset_name.into() })
    }
}

// ------------------------------------------------------------------ noise

fn hash(x: i32, y: i32, s: u32) -> f32 {
    let mut h = (x as u32).wrapping_mul(0x8da6_b343) ^ (y as u32).wrapping_mul(0xd816_3841) ^ s.wrapping_mul(0xcb1a_b31f);
    h ^= h >> 13;
    h = h.wrapping_mul(0x5bd1_e995);
    h ^= h >> 15;
    (h & 0xffffff) as f32 / 16_777_215.0
}

/// Smooth value noise in 0..1.
pub fn vnoise(p: Vec2, s: u32) -> f32 {
    let (ix, iy) = (p.x.floor() as i32, p.y.floor() as i32);
    let (fx, fy) = (p.x - p.x.floor(), p.y - p.y.floor());
    let (ux, uy) = (fx * fx * (3.0 - 2.0 * fx), fy * fy * (3.0 - 2.0 * fy));
    let a = hash(ix, iy, s);
    let b = hash(ix + 1, iy, s);
    let c = hash(ix, iy + 1, s);
    let d = hash(ix + 1, iy + 1, s);
    a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy
}

pub fn fbm(p: Vec2, s: u32, octaves: u32) -> f32 {
    let (mut v, mut amp, mut f, mut norm) = (0.0, 0.5, 1.0, 0.0);
    for o in 0..octaves {
        v += amp * vnoise(p * f, s.wrapping_add(o * 7919));
        norm += amp;
        amp *= 0.5;
        f *= 2.03;
    }
    v / norm
}

/// Deterministic per-element random numbers.
#[derive(Clone)]
struct Rand(std::cell::Cell<u64>);

impl Rand {
    fn new(seed: u64) -> Rand {
        Rand(std::cell::Cell::new(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ 0xD1B5_4A32_D192_ED03))
    }
    fn f(&self) -> f32 {
        self.0.set(self.0.get().wrapping_add(0x9E37_79B9_7F4A_7C15));
        let mut z = self.0.get();
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        ((z ^ (z >> 31)) >> 40) as f32 / (1u64 << 24) as f32
    }
    fn range(&self, lo: f32, hi: f32) -> f32 {
        lo + (hi - lo) * self.f()
    }
    fn sym(&self) -> f32 {
        self.f() * 2.0 - 1.0
    }
}

// ------------------------------------------------------------------ colour

fn rgb_to_hsv(c: [f32; 3]) -> [f32; 3] {
    let (r, g, b) = (c[0], c[1], c[2]);
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let d = max - min;
    let h = if d < 1e-6 {
        0.0
    } else if max == r {
        ((g - b) / d).rem_euclid(6.0) / 6.0
    } else if max == g {
        ((b - r) / d + 2.0) / 6.0
    } else {
        ((r - g) / d + 4.0) / 6.0
    };
    [h, if max > 0.0 { d / max } else { 0.0 }, max]
}

fn hsv_to_rgb(c: [f32; 3]) -> [f32; 3] {
    let (h, s, v) = (c[0].rem_euclid(1.0) * 6.0, c[1].clamp(0.0, 1.0), c[2].max(0.0));
    let i = h.floor();
    let f = h - i;
    let (p, q, t) = (v * (1.0 - s), v * (1.0 - s * f), v * (1.0 - s * (1.0 - f)));
    match i as i32 {
        0 => [v, t, p],
        1 => [q, v, p],
        2 => [p, v, t],
        3 => [p, q, v],
        4 => [t, p, v],
        _ => [v, p, q],
    }
}

fn mix3(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    let t = t.clamp(0.0, 1.0);
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

fn scale3(a: [f32; 3], k: f32) -> [f32; 3] {
    [a[0] * k, a[1] * k, a[2] * k]
}

fn smoothstep(e0: f32, e1: f32, x: f32) -> f32 {
    let t = ((x - e0) / (e1 - e0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// Yellow the leaf passes through on its way to the autumn colour.
const AUTUMN_MID: [f32; 3] = [0.82, 0.64, 0.12];

fn autumn_mix(base: [f32; 3], end: [f32; 3], a: f32) -> [f32; 3] {
    if a < 0.5 {
        mix3(base, AUTUMN_MID, a * 2.0)
    } else {
        mix3(AUTUMN_MID, end, (a - 0.5) * 2.0)
    }
}

// ------------------------------------------------------------------ elements

#[derive(Clone, Debug)]
struct LeafEl {
    /// Petiole joint (polar shapes: the centre) in layout units.
    base: Vec2,
    /// Unit direction base -> tip.
    dir: Vec2,
    len: f32,
    shape: LeafShape,
    aspect: f32,
    bend: f32,
    color: [f32; 3],
    tip: [f32; 3],
    /// 0..1 dryness of this leaf (scales the dry rim).
    dry: f32,
    /// Insect bites: (leaf-local centre, radius), leaf-length units.
    bites: Vec<(Vec2, f32)>,
    /// Stacking height (later leaves on top).
    z: f32,
    seed: u32,
}

#[derive(Clone, Debug)]
enum Elem {
    Leaf(LeafEl),
    Stem { a: Vec2, b: Vec2, w0: f32, w1: f32, color: [f32; 3], z: f32 },
    Dot { c: Vec2, r: f32, color: [f32; 3], z: f32 },
}

impl Elem {
    /// Conservative bounds (min, max) in layout units.
    fn bounds(&self) -> (Vec2, Vec2) {
        match self {
            Elem::Leaf(l) => {
                if l.shape.is_polar() {
                    let r = l.len * 1.05;
                    (l.base - Vec2::splat(r), l.base + Vec2::splat(r))
                } else {
                    let side = Vec2::new(-l.dir.y, l.dir.x) * l.len * (l.aspect * 0.55 + l.bend.abs() * 0.3 + 0.01);
                    let tip = l.base + l.dir * l.len * 1.02;
                    let base = l.base - l.dir * l.len * 0.02;
                    let pts = [base + side, base - side, tip + side, tip - side];
                    let lo = pts.iter().fold(Vec2::splat(f32::MAX), |a, p| a.min(*p));
                    let hi = pts.iter().fold(Vec2::splat(f32::MIN), |a, p| a.max(*p));
                    (lo, hi)
                }
            }
            Elem::Stem { a, b, w0, w1, .. } => {
                let w = w0.max(*w1);
                (a.min(*b) - Vec2::splat(w), a.max(*b) + Vec2::splat(w))
            }
            Elem::Dot { c, r, .. } => (*c - Vec2::splat(*r), *c + Vec2::splat(*r)),
        }
    }
    fn transform(&mut self, s: f32, t: Vec2) {
        match self {
            Elem::Leaf(l) => {
                l.base = l.base * s + t;
                l.len *= s;
            }
            Elem::Stem { a, b, w0, w1, .. } => {
                *a = *a * s + t;
                *b = *b * s + t;
                *w0 *= s;
                *w1 *= s;
            }
            Elem::Dot { c, r, .. } => {
                *c = *c * s + t;
                *r *= s;
            }
        }
    }
}

fn rot(v: Vec2, a: f32) -> Vec2 {
    let (s, c) = a.sin_cos();
    Vec2::new(v.x * c - v.y * s, v.x * s + v.y * c)
}

/// Direction at `deg` degrees clockwise from up.
fn dir_deg(deg: f32) -> Vec2 {
    let a = deg.to_radians();
    Vec2::new(a.sin(), a.cos())
}

struct Builder<'a> {
    spec: &'a LeafSpec,
    rng: Rand,
    out: Vec<Elem>,
    z: f32,
    leaves: u32,
}

impl<'a> Builder<'a> {
    fn aspect(&self) -> f32 {
        if self.spec.aspect > 0.0 {
            self.spec.aspect
        } else {
            self.spec.shape.default_aspect()
        }
    }

    fn leaf_color(&mut self) -> ([f32; 3], [f32; 3], f32) {
        let s = self.spec;
        let r = &self.rng;
        let a = (s.autumn + r.sym() * 0.5 * s.autumn_jitter * (s.autumn > 0.0 || s.autumn_jitter > 0.0) as u32 as f32).clamp(0.0, 1.0);
        let a = if s.autumn <= 0.0 { (a - 0.1).max(0.0) * 0.5 } else { a };
        let mut base = autumn_mix(s.color, s.autumn_color, a);
        let mut tip = autumn_mix(s.tip_color, s.autumn_color, (a * 1.15).min(1.0));
        let dh = r.sym() * s.hue_jitter * 0.06;
        let dv = 1.0 + r.sym() * s.value_jitter * 0.5;
        for c in [&mut base, &mut tip] {
            let mut h = rgb_to_hsv(*c);
            h[0] += dh;
            h[2] *= dv;
            *c = hsv_to_rgb(h);
        }
        // drier leaves as autumn goes on
        let dry = (s.dry_edges * (0.6 + 0.8 * r.f()) * (0.5 + a)).clamp(0.0, 1.0);
        (base, tip, dry)
    }

    fn push_leaf(&mut self, base: Vec2, dir: Vec2, len: f32, shape: LeafShape, aspect: f32, bend: f32) {
        let (color, tip, dry) = self.leaf_color();
        let mut bites = Vec::new();
        if self.rng.f() < self.spec.bites {
            let n = 1 + (self.rng.f() * 2.5) as usize;
            for _ in 0..n {
                let u = self.rng.range(0.25, 0.85);
                let side = if self.rng.f() < 0.5 { -1.0 } else { 1.0 };
                let r = self.rng.range(0.04, 0.09);
                let p = if shape.is_polar() {
                    let a = self.rng.range(-1.6, 1.6);
                    Vec2::new(a.sin(), a.cos()) * (0.55 + 0.4 * u)
                } else {
                    Vec2::new(side * half_width(shape, u, aspect) * 1.05, u)
                };
                bites.push((p, r));
            }
        }
        self.leaves += 1;
        self.z += 0.004;
        let seed = self.spec.seed.wrapping_mul(977).wrapping_add(self.leaves * 131);
        self.out.push(Elem::Leaf(LeafEl { base, dir: dir.normalize_or(Vec2::Y), len, shape, aspect, bend, color, tip, dry, bites, z: self.z, seed }));
    }

    fn push_stem(&mut self, a: Vec2, b: Vec2, w0: f32, w1: f32) {
        if w0 <= 0.0 && w1 <= 0.0 {
            return;
        }
        self.z += 0.002;
        self.out.push(Elem::Stem { a, b, w0, w1, color: self.spec.stem_color, z: self.z });
    }

    /// A curved stem from `a` along `dir` of length `len` as segments;
    /// returns the polyline.
    fn stem_line(&mut self, a: Vec2, dir: Vec2, len: f32, wave: f32, w0: f32, w1: f32, segs: usize) -> Vec<Vec2> {
        let phase = self.rng.f() * 6.28;
        let side = Vec2::new(-dir.y, dir.x);
        let pts: Vec<Vec2> = (0..=segs)
            .map(|i| {
                let t = i as f32 / segs as f32;
                a + dir * len * t + side * len * wave * 0.08 * ((t * PI * 1.6 + phase).sin() - phase.sin()) * t.sqrt()
            })
            .collect();
        for i in 0..segs {
            let (t0, t1) = (i as f32 / segs as f32, (i + 1) as f32 / segs as f32);
            self.push_stem(pts[i], pts[i + 1], w0 + (w1 - w0) * t0, w0 + (w1 - w0) * t1);
        }
        pts
    }

    /// One leaf of the spec's shape on a petiole from `at` going `dir`.
    fn leaf_on_petiole(&mut self, at: Vec2, dir: Vec2, len: f32) {
        let s = self.spec;
        let shape = s.shape;
        let aspect = self.aspect();
        let pet = match shape {
            LeafShape::Palmate => 0.45,
            LeafShape::Ginkgo => 0.55,
            LeafShape::Ivy => 0.5,
            LeafShape::Needle | LeafShape::Grass | LeafShape::Moss | LeafShape::Petal => 0.0,
            _ => 0.12,
        } * len;
        let sw = s.stem_width * len * 0.6;
        let joint = at + dir * pet;
        if pet > 0.0 {
            self.push_stem(at, joint, sw, sw * 0.8);
        }
        let bend = s.bend * self.rng.sym();
        self.push_leaf(joint, dir, len, shape, aspect, bend);
    }

    /// A pinnately compound leaf: rachis from `at` along `dir`.
    fn compound(&mut self, at: Vec2, dir: Vec2, len: f32) {
        let s = self.spec;
        let pairs = s.lobes.clamp(1, 30);
        let aspect = self.aspect();
        let sw = (s.stem_width * len * 0.35).max(len * 0.006);
        let pts = self.stem_line(at, dir, len, s.wave * 0.3, sw, sw * 0.6, 8);
        let leaflet = if s.leaf_size > 0.0 { s.leaf_size * len } else { len * (0.95 / (pairs as f32 + 1.0)).clamp(0.08, 0.32) * 1.7 };
        for k in 0..pairs {
            let t = 0.12 + 0.8 * (k as f32 + 0.5) / pairs as f32;
            let p = pts[((t * 8.0) as usize).min(7)].lerp(pts[((t * 8.0) as usize + 1).min(8)], (t * 8.0).fract());
            let l = leaflet * (1.0 - 0.25 * (t - 0.5).abs() * 2.0) * self.rng.range(0.9, 1.08);
            for side in [-1.0f32, 1.0] {
                let ang = side * self.rng.range(55.0, 70.0);
                let d = rot(dir, -ang.to_radians());
                self.push_leaf(p + d * l * 0.06, d, l, s.shape, aspect, s.bend * self.rng.sym());
            }
        }
        let tip = *pts.last().unwrap();
        self.push_leaf(tip, dir, leaflet * 1.05, s.shape, aspect, 0.0);
    }

    fn flower(&mut self, c: Vec2, r: f32) {
        let s = self.spec;
        let petals = s.lobes.clamp(3, 12);
        let off = self.rng.f() * 6.28;
        let aspect = self.aspect();
        for k in 0..petals {
            let a = off + k as f32 * 2.0 * PI / petals as f32 + self.rng.sym() * 0.12;
            let d = Vec2::new(a.sin(), a.cos());
            self.push_leaf(c + d * r * 0.08, d, r * self.rng.range(0.9, 1.05), LeafShape::Petal, aspect, 0.0);
        }
        // pink-red throat, then stamens
        self.z += 0.002;
        let throat = mix3(s.color, [0.75, 0.2, 0.3], 0.55);
        self.out.push(Elem::Dot { c, r: r * 0.24, color: throat, z: self.z });
        if s.stamens {
            for k in 0..14 {
                let a = k as f32 * 2.0 * PI / 14.0 + self.rng.sym() * 0.2;
                let d = Vec2::new(a.sin(), a.cos());
                let e = c + d * r * self.rng.range(0.28, 0.42);
                self.z += 0.0005;
                self.out.push(Elem::Stem { a: c, b: e, w0: r * 0.012, w1: r * 0.01, color: [0.95, 0.9, 0.85], z: self.z });
                self.out.push(Elem::Dot { c: e, r: r * 0.035, color: [0.92, 0.72, 0.2], z: self.z + 0.001 });
            }
        }
    }

    fn build(mut self) -> Vec<Elem> {
        let s = self.spec;
        let n = s.count.max(1);
        let leaf_len = |default: f32| if s.leaf_size > 0.0 { s.leaf_size } else { default };
        match s.arrangement {
            Arrangement::Single => {
                if s.shape == LeafShape::Grass && s.aspect == 0.0 && s.stem_width == 0.0 {
                    // a plain strip (e.g. the ivy stem card): one straight blade
                    self.push_leaf(Vec2::ZERO, Vec2::Y, 1.0, LeafShape::Grass, 0.12, 0.0);
                } else {
                    self.leaf_on_petiole(Vec2::ZERO, Vec2::Y, 1.0);
                }
            }
            Arrangement::Twig => {
                let sw = (s.stem_width * 1.2).max(0.004);
                let pts = self.stem_line(Vec2::ZERO, Vec2::Y, 1.0, s.wave, sw, sw * 0.45, 10);
                let l = leaf_len(match s.shape {
                    LeafShape::Palmate | LeafShape::Ivy => 0.36,
                    LeafShape::Ginkgo => 0.3,
                    LeafShape::Lanceolate => 0.45,
                    _ => 0.38,
                });
                for i in 0..n {
                    let t = if n == 1 { 0.6 } else { 0.18 + 0.72 * i as f32 / (n - 1) as f32 };
                    let k = ((t * 10.0) as usize).min(9);
                    let p = pts[k].lerp(pts[k + 1], (t * 10.0).fract());
                    let side = if i % 2 == 0 { 1.0 } else { -1.0 };
                    let ang = side * self.rng.range(35.0, 60.0) * (1.0 - 0.4 * t);
                    let d = dir_deg(ang + self.rng.sym() * 8.0);
                    let ll = l * (0.75 + 0.35 * (PI * (t * 0.8 + 0.1)).sin()) * self.rng.range(0.9, 1.1);
                    self.leaf_on_petiole(p, d, ll);
                }
                let tip = *pts.last().unwrap();
                self.leaf_on_petiole(tip, dir_deg(self.rng.sym() * 10.0), l * 0.85);
            }
            Arrangement::Compound => {
                if n == 1 {
                    self.compound(Vec2::ZERO, Vec2::Y, 1.0);
                } else {
                    let sw = (s.stem_width * 1.2).max(0.004);
                    let pts = self.stem_line(Vec2::ZERO, Vec2::Y, 0.55, s.wave, sw, sw * 0.6, 6);
                    for i in 0..n {
                        let t = if n == 1 { 1.0 } else { i as f32 / (n - 1) as f32 };
                        let p = pts[((t * 6.0) as usize).min(6)];
                        let side = if i % 2 == 0 { 1.0 } else { -1.0 };
                        let ang = if i + 1 == n { self.rng.sym() * 8.0 } else { side * self.rng.range(30.0, 50.0) };
                        self.compound(p, dir_deg(ang), 0.75 * self.rng.range(0.85, 1.05));
                    }
                }
            }
            Arrangement::Tuft => {
                let spread = if s.spread > 0.0 { s.spread } else { 50.0 };
                let aspect = self.aspect();
                for i in 0..n {
                    let f = if n == 1 { 0.0 } else { i as f32 / (n - 1) as f32 * 2.0 - 1.0 };
                    let ang = f * spread * 0.5 + self.rng.sym() * spread * 0.12;
                    let base = Vec2::new(self.rng.sym() * 0.04, 0.0);
                    let len = leaf_len(1.0) * self.rng.range(0.55, 1.0) * (1.0 - 0.3 * f.abs());
                    let bend = s.bend * (f * 0.8 + self.rng.sym() * 0.5);
                    self.push_leaf(base, dir_deg(ang), len, s.shape, aspect * self.rng.range(0.8, 1.2), bend);
                }
            }
            Arrangement::Spray => {
                let sw = (s.stem_width * 0.5).max(0.006);
                let pts = self.stem_line(Vec2::ZERO, Vec2::Y, 1.0, s.wave * 0.5, sw, sw * 0.5, 10);
                let l = leaf_len(0.4);
                let spread = if s.spread > 0.0 { s.spread } else { 70.0 };
                let per = s.lobes.clamp(1, 8);
                let aspect = self.aspect();
                for i in 0..n {
                    let t = 0.08 + 0.9 * i as f32 / n as f32;
                    let k = ((t * 10.0) as usize).min(9);
                    let p = pts[k].lerp(pts[k + 1], (t * 10.0).fract());
                    let around = self.rng.sym();
                    for j in 0..per {
                        let a = around * spread * 0.5 + (j as f32 - (per - 1) as f32 * 0.5) * 12.0 + self.rng.sym() * 10.0;
                        // needles near the tip point forward, lower ones splay out
                        let a = a * (0.55 + 0.45 * (1.0 - t)) + if around > 0.0 { 12.0 } else { -12.0 };
                        let len = l * self.rng.range(0.8, 1.05) * (0.75 + 0.25 * (1.0 - (t - 0.6).abs()));
                        self.push_leaf(p, dir_deg(a), len, s.shape, aspect, s.bend * self.rng.sym());
                    }
                }
                // terminal bud tuft
                let tip = *pts.last().unwrap();
                for j in 0..(per * 4) {
                    let a = (j as f32 / (per * 4 - 1).max(1) as f32 - 0.5) * 50.0;
                    self.push_leaf(tip, dir_deg(a), l * 0.8, s.shape, aspect, s.bend * self.rng.sym());
                }
            }
            Arrangement::Cluster => {
                let sw = (s.stem_width * 1.5).max(0.012);
                let pts = self.stem_line(Vec2::new(0.0, 0.0), dir_deg(8.0), 0.85, s.wave, sw, sw * 0.5, 8);
                let r = leaf_len(0.17);
                let mut placed: Vec<Vec2> = Vec::new();
                for i in 0..n {
                    let t = 0.35 + 0.65 * (i as f32 + 0.5) / n as f32;
                    let p = pts[((t * 8.0) as usize).min(8)];
                    let mut c = p + Vec2::new(self.rng.sym() * 0.22, self.rng.sym() * 0.12);
                    for _ in 0..6 {
                        if placed.iter().all(|q| q.distance(c) > r * 1.1) {
                            break;
                        }
                        c = p + Vec2::new(self.rng.sym() * 0.3, self.rng.sym() * 0.18);
                    }
                    placed.push(c);
                    self.push_stem(p, c, sw * 0.35, sw * 0.25);
                }
                for c in placed {
                    let rr = r * self.rng.range(0.85, 1.1);
                    self.flower(c, rr);
                }
            }
            Arrangement::Rosette => {
                let aspect = self.aspect();
                let off = self.rng.f() * 6.28;
                for i in 0..n {
                    let a = off + i as f32 * 2.0 * PI / n as f32 + self.rng.sym() * 0.2;
                    let d = Vec2::new(a.sin(), a.cos());
                    self.push_leaf(d * 0.03, d, leaf_len(1.0) * self.rng.range(0.7, 1.0), s.shape, aspect, s.bend * self.rng.sym());
                }
            }
            Arrangement::Clump => {
                let aspect = self.aspect();
                for i in 0..n {
                    let x = (i as f32 + self.rng.f()) / n as f32 * 2.0 - 1.0;
                    let h = (1.0 - x * x).max(0.0).sqrt();
                    let base = Vec2::new(x, self.rng.range(0.0, 0.15) * h);
                    let ang = x * 65.0 + self.rng.sym() * 20.0;
                    let len = leaf_len(0.2) * (0.4 + 0.8 * h) * self.rng.range(0.6, 1.2);
                    self.push_leaf(base, dir_deg(ang), len, s.shape, aspect, s.bend + self.rng.sym() * 0.3);
                }
            }
            Arrangement::Scatter => {
                let aspect = self.aspect();
                let l = leaf_len(0.32);
                for _ in 0..n {
                    let a = self.rng.f() * 6.28;
                    let r = self.rng.f().sqrt() * (1.0 - l * 0.5);
                    let c = Vec2::new(a.cos(), a.sin()) * r;
                    let d = dir_deg(self.rng.f() * 360.0);
                    if s.shape.is_polar() || s.shape == LeafShape::Ovate || s.shape == LeafShape::Cordate {
                        self.leaf_on_petiole(c - d * l * 0.4, d, l * self.rng.range(0.8, 1.1));
                    } else {
                        self.push_leaf(c - d * l * 0.5, d, l * self.rng.range(0.7, 1.1), s.shape, aspect, s.bend * self.rng.sym());
                    }
                }
            }
            Arrangement::Trailing => {
                let sw = (s.stem_width * 1.2).max(0.005);
                let pts = self.stem_line(Vec2::new(0.0, 1.0), -Vec2::Y, 1.0, s.wave, sw, sw * 0.6, 12);
                let l = leaf_len(0.2);
                for i in 0..n {
                    let t = 0.08 + 0.88 * i as f32 / n.max(2) as f32;
                    let k = ((t * 12.0) as usize).min(11);
                    let p = pts[k].lerp(pts[k + 1], (t * 12.0).fract());
                    let side = if i % 2 == 0 { 1.0 } else { -1.0 };
                    let ang = 180.0 - side * self.rng.range(40.0, 75.0);
                    self.leaf_on_petiole(p, dir_deg(ang), l * self.rng.range(0.8, 1.15) * (1.0 - 0.3 * t));
                }
            }
        }
        self.out
    }
}

// ------------------------------------------------------------------ shapes

fn profile_ab(shape: LeafShape) -> (f32, f32) {
    match shape {
        LeafShape::Ovate => (0.55, 0.9),
        LeafShape::Lanceolate => (0.6, 1.25),
        LeafShape::Elliptic => (0.8, 0.8),
        LeafShape::Cordate => (0.32, 1.0),
        LeafShape::Grass => (0.06, 0.95),
        LeafShape::Petal => (1.3, 0.35),
        LeafShape::Moss => (0.45, 1.3),
        LeafShape::Needle => (0.05, 0.5),
        _ => (0.6, 0.9),
    }
}

/// Half width of a profile-shaped leaf at `u` (0 base .. 1 tip), in leaf lengths.
fn half_width(shape: LeafShape, u: f32, aspect: f32) -> f32 {
    if !(0.0..=1.0).contains(&u) {
        return 0.0;
    }
    let (a, b) = profile_ab(shape);
    let m = a / (a + b);
    let peak = m.powf(a) * (1.0 - m).powf(b);
    0.5 * aspect * u.powf(a) * (1.0 - u).powf(b) / peak
}

/// Result of evaluating a leaf at a point.
struct LeafHit {
    /// Signed distance to the outline in leaf lengths (< 0 inside).
    sd: f32,
    /// Vein intensity 0..1 (midrib / primaries).
    main_vein: f32,
    /// Secondary vein intensity 0..1.
    vein: f32,
    /// 0 at the base .. 1 at the tip / rim.
    u: f32,
    /// 0 on the midline .. 1 at the edge.
    across: f32,
}

fn tooth(x: f32) -> f32 {
    // sawtooth with teeth leaning to the tip: slow rise, quick drop
    let f = x.rem_euclid(1.0);
    1.0 - f.powf(1.6)
}

fn line_vein(d: f32, w: f32) -> f32 {
    1.0 - smoothstep(w * 0.4, w, d)
}

fn eval_leaf(l: &LeafEl, spec: &LeafSpec, q: Vec2, px: f32) -> LeafHit {
    // px: one pixel in leaf lengths, for vein widths that stay visible
    let vw = |w: f32| w.max(px * 0.9);
    let mut hit = match l.shape {
        LeafShape::Palmate | LeafShape::Ivy => {
            let n = if l.shape == LeafShape::Ivy { spec.lobes.clamp(3, 7) } else { spec.lobes.clamp(3, 11) };
            let spread = if spec.spread > 0.0 { spec.spread } else if l.shape == LeafShape::Ivy { 220.0 } else { 280.0 }.min(340.0);
            let spread = spread.to_radians();
            let depth = spec.lobe_depth.clamp(0.0, 0.95);
            let q_pow = if l.shape == LeafShape::Ivy { 1.6 } else { 0.65 };
            let hw = spread / (n - 1) as f32 * 0.5 * 1.05;
            let theta = q.x.atan2(q.y);
            let rr = q.length();
            let mut r = 0.0f32;
            let mut main = 0.0f32;
            let mut sec = 0.0f32;
            for k in 0..n {
                let phi = spread * (k as f32 / (n - 1) as f32 - 0.5);
                let fall = if l.shape == LeafShape::Ivy { 0.35 } else { 0.42 };
                let len_k = 1.0 - fall * (phi.abs() / (spread * 0.5)).powi(2);
                let t = ((theta - phi + PI).rem_euclid(2.0 * PI) - PI).abs() / hw;
                let mut bump = 1.0 - depth * t.min(1.0).powf(q_pow) - (t - 1.0).max(0.0) * 0.9;
                if spec.serration > 0.0 && t < 1.0 {
                    bump -= spec.serration * 0.07 * tooth(rr / len_k * spec.teeth.max(1) as f32 * 0.5) * (rr / len_k).clamp(0.25, 1.0);
                }
                r = r.max(len_k * bump.max(0.0));
                let d = Vec2::new(phi.sin(), phi.cos());
                let along = q.dot(d);
                let perp = q.perp_dot(d).abs();
                if along > 0.0 && along < len_k {
                    main = main.max(line_vein(perp, vw(0.016 * (1.0 - along / len_k * 0.75))));
                    // secondaries from this primary
                    let a = spec.vein_angle.clamp(15.0, 80.0).to_radians();
                    let s_coord = along - perp / a.tan();
                    let cnt = (spec.veins.max(1) as f32 * 0.8).max(2.0);
                    let f = (s_coord / len_k * cnt).rem_euclid(1.0);
                    let g = (f.min(1.0 - f)) * len_k / cnt;
                    if t < 1.0 && s_coord > 0.03 {
                        sec = sec.max(line_vein(g, vw(0.006)));
                    }
                }
            }
            LeafHit { sd: rr - r, main_vein: main, vein: sec, u: (rr / r.max(1e-4)).min(1.0), across: (rr / r.max(1e-4)).min(1.0) }
        }
        LeafShape::Ginkgo => {
            let half = if spec.spread > 0.0 { spec.spread * 0.5 } else { 75.0 }.to_radians();
            let theta = q.x.atan2(q.y);
            let rr = q.length();
            let notch = spec.lobe_depth.clamp(0.0, 1.0) * 0.35 * (-(theta / 0.09).powi(2)).exp();
            let wave = 0.025 * (theta * 23.0 + l.seed as f32).sin() + 0.015 * (theta * 51.0).sin();
            let r = 1.0 - notch + wave - 0.12 * (theta.abs() / half).powi(4);
            let ang = (theta.abs() - half) * rr.max(0.05);
            let sd = (rr - r).max(ang).max(-q.y);
            let n = spec.veins.max(6) as f32;
            let f = (theta / half * 0.5 + 0.5) * n;
            let g = (f - f.round()).abs() / n * half * 2.0 * rr;
            let vein = line_vein(g, vw(0.004)) * smoothstep(0.05, 0.2, rr);
            LeafHit { sd, main_vein: 0.0, vein, u: (rr / r.max(1e-4)).min(1.0), across: (theta.abs() / half).min(1.0) }
        }
        _ => {
            // profile shapes, with an optional sideways bend (grass, needles)
            let u = q.y;
            let x = q.x - l.bend * 0.35 * u * u;
            let mut w = half_width(l.shape, u, l.aspect);
            if spec.serration > 0.0 && u > 0.06 && u < 0.97 {
                let depth = spec.serration * if l.shape == LeafShape::Lanceolate { 0.55 } else { 0.22 };
                w *= 1.0 - depth * tooth(u * spec.teeth.max(1) as f32);
            }
            if l.shape == LeafShape::Petal {
                // notched petal tip (cherry)
                let notch = 0.12 * (-(x / (l.aspect * 0.09)).powi(2)).exp();
                w *= if u > 1.0 - notch { 0.0 } else { 1.0 };
            }
            let mut sd = (x.abs() - w).max(-u).max(u - 1.0);
            if l.shape == LeafShape::Cordate {
                // basal sinus around the petiole
                sd = sd.max(-(Vec2::new(x, u + 0.02).length() - 0.09 * l.aspect));
            }
            let across = if w > 1e-5 { (x.abs() / w).min(1.0) } else { 1.0 };
            let main = if matches!(l.shape, LeafShape::Needle | LeafShape::Moss) { 0.0 } else { line_vein(x.abs(), vw(0.012 * l.aspect.max(0.3) * (1.0 - u * 0.7))) };
            let vein = match l.shape {
                LeafShape::Grass | LeafShape::Needle | LeafShape::Moss => {
                    // parallel veins
                    let n = spec.veins.clamp(1, 8) as f32;
                    let f = across * n;
                    line_vein((f - f.round()).abs() * w / n, vw(0.003))
                }
                _ => {
                    let a = spec.vein_angle.clamp(15.0, 80.0).to_radians();
                    let s_coord = u - x.abs() / a.tan();
                    let n = spec.veins.max(1) as f32;
                    let f = (s_coord * n).rem_euclid(1.0);
                    let g = f.min(1.0 - f) / n * a.sin();
                    if s_coord > 0.02 && across < 0.92 {
                        line_vein(g, vw(0.005))
                    } else {
                        0.0
                    }
                }
            };
            LeafHit { sd, main_vein: main, vein, u: u.clamp(0.0, 1.0), across }
        }
    };
    for (c, r) in &l.bites {
        hit.sd = hit.sd.max(r - (q - *c).length());
    }
    hit
}

// ------------------------------------------------------------------ raster

/// Maps of one cell (or a whole atlas), row-major, top row first.
#[derive(Clone, Debug)]
pub struct CellImage {
    pub w: u32,
    pub h: u32,
    /// sRGB colour (0..1).
    pub color: Vec<[f32; 3]>,
    /// Coverage (from the leaf shapes).
    pub alpha: Vec<f32>,
    /// Height -1..1 (0 = flat).
    pub height: Vec<f32>,
    pub roughness: Vec<f32>,
    /// Back-lit (translucency / subsurface) colour, sRGB 0..1.
    pub translucency: Vec<[f32; 3]>,
    /// 0 = paper thin .. 1 = thick (stems, veins).
    pub thickness: Vec<f32>,
}

impl CellImage {
    pub fn new(w: u32, h: u32) -> CellImage {
        let n = (w * h) as usize;
        CellImage { w, h, color: vec![[0.0; 3]; n], alpha: vec![0.0; n], height: vec![0.0; n], roughness: vec![0.6; n], translucency: vec![[0.0; 3]; n], thickness: vec![0.0; n] }
    }
}

fn srgb_luma(c: [f32; 3]) -> f32 {
    0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}

/// Translucent colour of a leaf colour: brighter and more saturated.
fn back_lit(c: [f32; 3]) -> [f32; 3] {
    let mut h = rgb_to_hsv(c);
    h[1] = (h[1] * 1.15).min(1.0);
    h[2] = (h[2] * 1.6 + 0.08).min(1.0);
    // light through chlorophyll leans yellow-green
    let g = hsv_to_rgb(h);
    mix3(g, [g[0] * 1.05 + 0.03, g[1] * 1.08 + 0.04, g[2] * 0.8], 0.4)
}

/// Draw a cell's leaves into a `w x h` image covering `size_m` metres.
/// `margin` keeps them off the edges (fraction of the smaller side).
pub fn render_cell(cell: &FoliageCell, w: u32, h: u32) -> CellImage {
    let mut img = CellImage::new(w, h);
    if w == 0 || h == 0 {
        return img;
    }
    let spec = &cell.spec;
    let b = Builder { spec, rng: Rand::new(spec.seed as u64 * 7 + 1), out: Vec::new(), z: 0.0, leaves: 0 };
    let mut elems = b.build();
    // fit into the cell, keeping proportions
    let (mut lo, mut hi) = (Vec2::splat(f32::MAX), Vec2::splat(f32::MIN));
    for e in &elems {
        let (a, b) = e.bounds();
        lo = lo.min(a);
        hi = hi.max(b);
    }
    let size = Vec2::new(cell.size_m[0], cell.size_m[1]);
    let margin = 0.03 * size.min_element();
    let avail = size - Vec2::splat(2.0 * margin);
    let ext = (hi - lo).max(Vec2::splat(1e-6));
    let s = (avail.x / ext.x).min(avail.y / ext.y);
    // centred horizontally; upright cards sit on the bottom edge, hanging ones on the top
    let used = ext * s;
    let x0 = -size.x * 0.5 + margin + (avail.x - used.x) * 0.5;
    let y0 = match cell.mount {
        Mount::Upright => margin * 0.3,
        Mount::Hanging => size.y - margin * 0.3 - used.y,
        _ => margin + (avail.y - used.y) * 0.5,
    };
    let t = Vec2::new(x0, y0) - lo * s;
    for e in &mut elems {
        e.transform(s, t);
    }
    let px_m = size.x / w as f32;
    let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).clamp(1, 16);
    let rows_per = (h as usize).div_ceil(threads).max(1);
    let n_rows = h as usize;
    // split the image into row bands, one thread each
    let wus = w as usize;
    let mut bands: Vec<(usize, CellImage)> = (0..n_rows).step_by(rows_per).map(|r0| (r0, CellImage::new(w, (rows_per.min(n_rows - r0)) as u32))).collect();
    std::thread::scope(|sc| {
        for (r0, band) in bands.iter_mut() {
            let elems = &elems;
            let r0 = *r0;
            sc.spawn(move || {
                let bh = band.h as usize;
                // world y of the band's rows (top row = size.y)
                let y_top = size.y - r0 as f32 * px_m;
                let y_bot = y_top - bh as f32 * px_m;
                for e in elems {
                    let (blo, bhi) = e.bounds();
                    if bhi.y < y_bot || blo.y > y_top {
                        continue;
                    }
                    let i0 = (((blo.x + size.x * 0.5) / px_m).floor() as i64 - 1).clamp(0, wus as i64) as usize;
                    let i1 = (((bhi.x + size.x * 0.5) / px_m).ceil() as i64 + 1).clamp(0, wus as i64) as usize;
                    let j0 = (((y_top - bhi.y) / px_m).floor() as i64 - 1).clamp(0, bh as i64) as usize;
                    let j1 = (((y_top - blo.y) / px_m).ceil() as i64 + 1).clamp(0, bh as i64) as usize;
                    for j in j0..j1 {
                        let y = y_top - (j as f32 + 0.5) * px_m;
                        for i in i0..i1 {
                            let x = (i as f32 + 0.5) * px_m - size.x * 0.5;
                            shade(e, spec, Vec2::new(x, y), px_m, band, j * wus + i);
                        }
                    }
                }
            });
        }
    });
    for (r0, band) in bands {
        let o = r0 * wus;
        let n = band.color.len();
        img.color[o..o + n].copy_from_slice(&band.color);
        img.alpha[o..o + n].copy_from_slice(&band.alpha);
        img.height[o..o + n].copy_from_slice(&band.height);
        img.roughness[o..o + n].copy_from_slice(&band.roughness);
        img.translucency[o..o + n].copy_from_slice(&band.translucency);
        img.thickness[o..o + n].copy_from_slice(&band.thickness);
    }
    bleed(&mut img, 24);
    img
}

/// Composite one element over pixel `k` of `img` at layout point `p`.
fn shade(e: &Elem, spec: &LeafSpec, p: Vec2, px_m: f32, img: &mut CellImage, k: usize) {
    let (cov, col, hgt, rough, trans, thick) = match e {
        Elem::Stem { a, b, w0, w1, color, z } => {
            let ab = *b - *a;
            let t = ((p - *a).dot(ab) / ab.length_squared().max(1e-12)).clamp(0.0, 1.0);
            let w = w0 + (w1 - w0) * t;
            let d = (p - (*a + ab * t)).length() - w;
            let cov = (0.5 - d / px_m).clamp(0.0, 1.0);
            if cov <= 0.0 {
                return;
            }
            let round = (1.0 - ((p - (*a + ab * t)).length() / w.max(1e-6)).powi(2)).max(0.0).sqrt();
            let c = scale3(*color, 0.75 + 0.3 * round);
            (cov, c, 0.25 + z + 0.2 * round, 0.65, [0.0; 3], 1.0)
        }
        Elem::Dot { c, r, color, z } => {
            let d = (p - *c).length() - r;
            let cov = (0.5 - d / px_m).clamp(0.0, 1.0);
            if cov <= 0.0 {
                return;
            }
            let round = (1.0 - ((p - *c).length() / r.max(1e-6)).powi(2)).max(0.0).sqrt();
            (cov, scale3(*color, 0.8 + 0.25 * round), 0.3 + z + 0.15 * round, 0.5, scale3(*color, 0.5), 0.6)
        }
        Elem::Leaf(l) => {
            let d = p - l.base;
            let side = Vec2::new(l.dir.y, -l.dir.x); // right of the leaf axis
            let q = Vec2::new(d.dot(side), d.dot(l.dir)) / l.len;
            let pxl = px_m / l.len;
            let hit = eval_leaf(l, spec, q, pxl);
            let mut cov = (0.5 - hit.sd / pxl).clamp(0.0, 1.0);
            if cov <= 0.0 {
                return;
            }
            let n1 = fbm(q * 9.0, l.seed, 3);
            let n2 = vnoise(q * 31.0, l.seed ^ 0x55);
            // holes: eaten through, with a brown rim
            let mut rim = 0.0;
            if spec.holes > 0.0 {
                let hn = fbm(q * 7.0 + Vec2::splat(l.seed as f32 * 0.37), l.seed ^ 0xA1, 3);
                let thr = 1.0 - spec.holes * 0.32;
                if hn > thr {
                    cov *= ((thr + 0.015 - hn) / 0.015).clamp(0.0, 1.0);
                    if cov <= 0.0 {
                        return;
                    }
                }
                rim = smoothstep(thr - 0.04, thr, hn);
            }
            // colour: base -> tip, veins, mottling, dry rim
            let mut c = mix3(l.color, l.tip, spec.tip_amount * smoothstep(0.25, 1.0, hit.u.max(hit.across * 0.6)));
            let ven = spec.venation.clamp(0.0, 1.0);
            c = mix3(c, spec.vein_color, ven * (hit.main_vein * 0.85 + hit.vein * 0.45));
            c = scale3(c, 0.9 + 0.2 * n1 + 0.06 * (n2 - 0.5));
            let edge = (-hit.sd).max(0.0);
            let mut dry = 0.0;
            if l.dry > 0.0 {
                let width = l.dry * 0.12 * (0.55 + 0.9 * n1);
                dry = 1.0 - smoothstep(width * 0.35, width, edge);
            }
            dry = dry.max(rim * 0.9);
            if dry > 0.0 {
                let dc = scale3(spec.dry_color, 0.8 + 0.4 * n2);
                c = mix3(c, dc, dry);
            }
            // height: dome across the blade, raised midrib, grooved secondaries
            let dome = 1.0 - hit.across * hit.across;
            let h = 0.2 + l.z + 0.12 * dome + ven * (0.12 * hit.main_vein - 0.08 * hit.vein) + 0.03 * (n2 - 0.5) - 0.06 * dry;
            let r = (spec.roughness + 0.1 * (n1 - 0.5) - 0.04 * hit.main_vein + 0.25 * dry).clamp(0.02, 1.0);
            let tl = spec.translucency.clamp(0.0, 1.0);
            let tc = match spec.translucency_color {
                Some(t) => mix3(t, back_lit(c), 0.3),
                None => back_lit(c),
            };
            let block = (1.0 - 0.55 * ven * hit.main_vein - 0.25 * ven * hit.vein) * (1.0 - 0.85 * dry);
            let trans = scale3(tc, tl * block);
            let thick = (0.15 + 0.6 * hit.main_vein + 0.2 * hit.vein + 0.6 * dry).min(1.0) * (1.0 - 0.5 * tl) + 0.1;
            (cov, c, h, r, trans, thick.min(1.0))
        }
    };
    let a = cov;
    let blend = |d: f32, s: f32| d + (s - d) * a;
    img.color[k] = mix3(img.color[k], col, a);
    img.height[k] = blend(img.height[k], hgt.min(1.0));
    img.roughness[k] = blend(img.roughness[k], rough);
    img.translucency[k] = mix3(img.translucency[k], trans, a);
    img.thickness[k] = blend(img.thickness[k], thick);
    img.alpha[k] = a + img.alpha[k] * (1.0 - a);
    let _ = srgb_luma;
}

/// Spread colours into transparent texels (so alpha-tested, mip-mapped
/// cards don't get dark fringes), `passes` texels out; what is left gets the
/// mean leaf colour.
pub fn bleed(img: &mut CellImage, passes: u32) {
    let (w, h) = (img.w as usize, img.h as usize);
    let mut known: Vec<bool> = img.alpha.iter().map(|a| *a > 0.02).collect();
    // un-premultiply partially covered edge texels (they were blended over black)
    for k in 0..w * h {
        let a = img.alpha[k];
        if a > 0.02 && a < 0.999 {
            img.color[k] = scale3(img.color[k], 1.0 / a);
            img.translucency[k] = scale3(img.translucency[k], 1.0 / a);
        }
    }
    let n = known.iter().filter(|k| **k).count().max(1) as f32;
    let mean = img.color.iter().zip(&known).filter(|(_, k)| **k).fold([0.0f32; 3], |a, (c, _)| [a[0] + c[0] / n, a[1] + c[1] / n, a[2] + c[2] / n]);
    for _ in 0..passes {
        let prev = known.clone();
        let mut any = false;
        for y in 0..h {
            for x in 0..w {
                let k = y * w + x;
                if prev[k] {
                    continue;
                }
                let (mut acc, mut cnt) = ([0.0f32; 3], 0.0);
                for (dx, dy) in [(-1i32, 0i32), (1, 0), (0, -1), (0, 1)] {
                    let (nx, ny) = (x as i32 + dx, y as i32 + dy);
                    if nx < 0 || ny < 0 || nx >= w as i32 || ny >= h as i32 {
                        continue;
                    }
                    let j = ny as usize * w + nx as usize;
                    if prev[j] {
                        let c = img.color[j];
                        acc = [acc[0] + c[0], acc[1] + c[1], acc[2] + c[2]];
                        cnt += 1.0;
                    }
                }
                if cnt > 0.0 {
                    img.color[k] = scale3(acc, 1.0 / cnt);
                    known[k] = true;
                    any = true;
                }
            }
        }
        if !any {
            break;
        }
    }
    for k in 0..w * h {
        if !known[k] {
            img.color[k] = mean;
        }
    }
}

/// Paste `cell` into `dst` with its top-left texel at (`x0`, `y0`).
pub fn blit(dst: &mut CellImage, cell: &CellImage, x0: u32, y0: u32) {
    for y in 0..cell.h.min(dst.h.saturating_sub(y0)) {
        for x in 0..cell.w.min(dst.w.saturating_sub(x0)) {
            let s = (y * cell.w + x) as usize;
            let d = ((y + y0) * dst.w + x + x0) as usize;
            dst.color[d] = cell.color[s];
            dst.alpha[d] = cell.alpha[s];
            dst.height[d] = cell.height[s];
            dst.roughness[d] = cell.roughness[s];
            dst.translucency[d] = cell.translucency[s];
            dst.thickness[d] = cell.thickness[s];
        }
    }
}

/// Texel rectangle [x0, y0, x1, y1) of a sheet cell's UV rect at `res`.
pub fn cell_rect(uv: [f32; 4], res: u32) -> [u32; 4] {
    let n = res as f32;
    [(uv[0] * n).round() as u32, (uv[1] * n).round() as u32, ((uv[2] * n).round() as u32).min(res), ((uv[3] * n).round() as u32).min(res)]
}

/// Render every cell into a `res x res` atlas laid out by `uvs` (one UV rect
/// per cell, v down).
pub fn render_atlas(cells: &[FoliageCell], uvs: &[[f32; 4]], res: u32) -> CellImage {
    let mut atlas = CellImage::new(res, res);
    for (c, uv) in cells.iter().zip(uvs) {
        let r = cell_rect(*uv, res);
        let img = render_cell(c, r[2] - r[0], r[3] - r[1]);
        blit(&mut atlas, &img, r[0], r[1]);
    }
    atlas
}

/// The built-in card library used by the foliage brush when a foliage layer
/// has no atlas of its own.
pub fn builtin_cells() -> Vec<FoliageCell> {
    let mk = |name: &str, p: &str| FoliageCell::from_preset(name, p).expect("builtin preset");
    vec![
        mk("moss", "moss"),
        mk("moss_patch", "moss_patch"),
        mk("grass", "grass"),
        mk("weed", "weed"),
        mk("ivy_leaf", "ivy_leaf"),
        mk("ivy_stem", "ivy_stem"),
        mk("ivy", "ivy"),
        mk("maple_leaf", "maple_leaf"),
        mk("ginkgo_leaf", "ginkgo_leaf"),
        mk("cherry_petals", "cherry_petals"),
        mk("fallen_leaves", "fallen_leaves"),
        mk("fern", "fern"),
        mk("hanging_vine", "hanging_vine"),
        mk("weed_rosette", "weed_rosette"),
    ]
}

/// Resolve a name against the built-in cells (also accepts a few aliases).
pub fn builtin_alias(name: &str) -> &str {
    match name {
        "leaves" | "fallen" => "fallen_leaves",
        "weeds" => "weed",
        "petals" | "sakura" => "cherry_petals",
        "vine" | "hanging" | "hanging_plant" => "hanging_vine",
        other => other,
    }
}

// ------------------------------------------------------------------ bark

/// Bark styles for seamless tile projects.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BarkStyle {
    /// Deep vertical furrows between long ridges (oak, old pine trunks).
    #[default]
    Fissured,
    /// Scaly plates separated by dark cracks (Japanese black pine).
    Plated,
    /// Smooth, glossy bark with horizontal lenticels (cherry).
    Lenticels,
    /// Papery sheets peeling off a smoother under-layer (birch, crape myrtle).
    Peeling,
}

impl BarkStyle {
    pub const ALL: [BarkStyle; 4] = [BarkStyle::Fissured, BarkStyle::Plated, BarkStyle::Lenticels, BarkStyle::Peeling];
    pub fn id(self) -> &'static str {
        match self {
            BarkStyle::Fissured => "fissured",
            BarkStyle::Plated => "plated",
            BarkStyle::Lenticels => "lenticels",
            BarkStyle::Peeling => "peeling",
        }
    }
    pub fn from_id(s: &str) -> Option<BarkStyle> {
        let s = s.to_ascii_lowercase();
        let s = match s.as_str() {
            "smooth" | "cherry" => "lenticels",
            "pine" | "scaly" => "plated",
            "oak" | "furrowed" => "fissured",
            "birch" | "paperbark" => "peeling",
            o => o,
        };
        BarkStyle::ALL.into_iter().find(|k| k.id() == s)
    }
}

/// A procedural bark (seamless over the tile it is drawn for).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct BarkSpec {
    pub style: BarkStyle,
    /// Features (ridges, plates, lenticel rows) per metre across.
    pub scale: f32,
    /// Ridge / plate elongation along the trunk (v).
    pub stretch: f32,
    /// 0..1 relief depth.
    pub depth: f32,
    /// 0..1 irregularity.
    pub roughness_variation: f32,
    /// Main bark colour (sRGB).
    pub color: [f32; 3],
    /// Colour deep in the cracks / under peeled sheets.
    pub crack_color: [f32; 3],
    /// Accent colour (lenticels, inner bark of plates, peeled patches).
    pub accent_color: [f32; 3],
    pub roughness: f32,
    /// 0..1 lichen / moss specks.
    pub lichen: f32,
    pub seed: u32,
}

impl Default for BarkSpec {
    fn default() -> Self {
        BarkSpec {
            style: BarkStyle::Fissured,
            scale: 8.0,
            stretch: 3.0,
            depth: 0.7,
            roughness_variation: 0.5,
            color: [0.33, 0.27, 0.22],
            crack_color: [0.08, 0.06, 0.05],
            accent_color: [0.45, 0.26, 0.16],
            roughness: 0.85,
            lichen: 0.0,
            seed: 0,
        }
    }
}

impl BarkSpec {
    /// Sensible colours / scales for each style.
    pub fn for_style(style: BarkStyle) -> BarkSpec {
        let d = BarkSpec::default();
        match style {
            BarkStyle::Fissured => BarkSpec { style, ..d },
            BarkStyle::Plated => BarkSpec { style, scale: 6.0, stretch: 1.6, color: [0.3, 0.27, 0.25], crack_color: [0.07, 0.05, 0.04], accent_color: [0.55, 0.3, 0.18], ..d },
            BarkStyle::Lenticels => BarkSpec { style, scale: 10.0, stretch: 1.0, depth: 0.35, color: [0.36, 0.2, 0.17], crack_color: [0.18, 0.1, 0.08], accent_color: [0.62, 0.5, 0.42], roughness: 0.45, ..d },
            BarkStyle::Peeling => BarkSpec { style, scale: 5.0, stretch: 0.6, depth: 0.45, color: [0.85, 0.82, 0.76], crack_color: [0.28, 0.22, 0.18], accent_color: [0.62, 0.42, 0.3], roughness: 0.7, ..d },
        }
    }
}

/// Periodic value noise: `period` cells on each axis wrap.
fn pnoise(p: Vec2, period: [i32; 2], s: u32) -> f32 {
    let (ix, iy) = (p.x.floor() as i32, p.y.floor() as i32);
    let (fx, fy) = (p.x - p.x.floor(), p.y - p.y.floor());
    let (ux, uy) = (fx * fx * (3.0 - 2.0 * fx), fy * fy * (3.0 - 2.0 * fy));
    let w = |x: i32, y: i32| hash(x.rem_euclid(period[0].max(1)), y.rem_euclid(period[1].max(1)), s);
    let (a, b, c, d) = (w(ix, iy), w(ix + 1, iy), w(ix, iy + 1), w(ix + 1, iy + 1));
    a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy
}

/// Periodic fbm over the unit square (`base` lattice cells per side).
fn pfbm(uv: Vec2, base: [i32; 2], s: u32, oct: u32) -> f32 {
    let (mut v, mut amp, mut norm) = (0.0, 0.5, 0.0);
    for o in 0..oct {
        let k = 1 << o;
        let per = [base[0] * k, base[1] * k];
        v += amp * pnoise(Vec2::new(uv.x * per[0] as f32, uv.y * per[1] as f32), per, s.wrapping_add(o * 101));
        norm += amp;
        amp *= 0.5;
    }
    v / norm
}

/// Periodic Worley: (F1, F2, cell id hash) with `cells` points per side.
fn pworley(uv: Vec2, cells: [i32; 2], s: u32) -> (f32, f32, f32) {
    let p = Vec2::new(uv.x * cells[0] as f32, uv.y * cells[1] as f32);
    let (ix, iy) = (p.x.floor() as i32, p.y.floor() as i32);
    let (mut f1, mut f2, mut id) = (f32::MAX, f32::MAX, 0.0);
    for dy in -1..=1 {
        for dx in -1..=1 {
            let (cx, cy) = (ix + dx, iy + dy);
            let (wx, wy) = (cx.rem_euclid(cells[0]), cy.rem_euclid(cells[1]));
            let jit = Vec2::new(hash(wx, wy, s), hash(wx, wy, s ^ 0x9e37));
            let q = Vec2::new(cx as f32, cy as f32) + jit * 0.85 + Vec2::splat(0.075);
            let d = (q - p).length();
            if d < f1 {
                f2 = f1;
                f1 = d;
                id = hash(wx, wy, s ^ 0x1234);
            } else if d < f2 {
                f2 = d;
            }
        }
    }
    (f1, f2, id)
}

/// Draw bark over a seamless tile `size_m` metres, `w x h` texels. The
/// result wraps on both axes.
pub fn render_bark(spec: &BarkSpec, size_m: [f32; 2], w: u32, h: u32) -> CellImage {
    let mut img = CellImage::new(w, h);
    let cells = |per_m: f32, stretch: f32| -> [i32; 2] { [((size_m[0] * per_m).round() as i32).max(1), ((size_m[1] * per_m / stretch.max(0.1)).round() as i32).max(1)] };
    let s = spec.seed;
    let dep = spec.depth.clamp(0.0, 1.0);
    let rv = spec.roughness_variation.clamp(0.0, 1.0);
    let rows: Vec<usize> = (0..h as usize).collect();
    let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).clamp(1, 16);
    let chunk = rows.len().div_ceil(threads).max(1);
    let results: Vec<Vec<([f32; 3], f32, f32)>> = std::thread::scope(|sc| {
        let hs: Vec<_> = rows
            .chunks(chunk)
            .map(|rs| {
                sc.spawn(move || {
                    let mut out = Vec::with_capacity(rs.len() * w as usize);
                    for &y in rs {
                        for x in 0..w as usize {
                            let uv = Vec2::new((x as f32 + 0.5) / w as f32, (y as f32 + 0.5) / h as f32);
                            out.push(bark_texel(spec, uv, &cells, s, dep, rv));
                        }
                    }
                    out
                })
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });
    for (k, (c, hgt, r)) in results.into_iter().flatten().enumerate() {
        img.color[k] = c;
        img.height[k] = hgt;
        img.roughness[k] = r;
        img.alpha[k] = 1.0;
        img.thickness[k] = 1.0;
    }
    img
}

fn bark_texel(spec: &BarkSpec, uv: Vec2, cells: &dyn Fn(f32, f32) -> [i32; 2], s: u32, dep: f32, rv: f32) -> ([f32; 3], f32, f32) {
    let n_fine = pfbm(uv, cells(spec.scale * 4.0, 1.0), s ^ 7, 4);
    let n_mid = pfbm(uv, cells(spec.scale * 0.8, spec.stretch), s ^ 3, 4);
    let (mut c, mut h, mut r);
    match spec.style {
        BarkStyle::Fissured | BarkStyle::Plated => {
            let stretch = if spec.style == BarkStyle::Fissured { spec.stretch.max(1.0) } else { spec.stretch };
            // warp the cells so plate edges wander
            let warp = Vec2::new(pfbm(uv, cells(spec.scale * 0.6, 1.0), s ^ 11, 3) - 0.5, pfbm(uv, cells(spec.scale * 0.6, 1.0), s ^ 13, 3) - 0.5);
            let cw = cells(spec.scale, stretch);
            let uvw = uv + Vec2::new(warp.x / cw[0] as f32 * 0.9, warp.y / cw[1] as f32 * 0.9);
            let (f1, f2, id) = pworley(uvw, cw, s);
            let edge = f2 - f1; // 0 on the crack
            let crack_w = if spec.style == BarkStyle::Fissured { 0.32 } else { 0.14 };
            let crack = 1.0 - smoothstep(0.0, crack_w * (0.7 + 0.6 * n_mid), edge);
            // plates: raised, slightly domed, flaky layers
            let plate = smoothstep(0.0, 0.45, edge);
            let layers = ((n_mid * 3.0 + id * 2.0).fract() - 0.5).abs() * 2.0;
            h = (plate * (0.55 + 0.25 * id) + 0.15 * layers * plate + 0.12 * (n_fine - 0.5)) * dep - crack * 0.6 * dep;
            c = mix3(spec.color, spec.accent_color, (id * 0.7 + 0.3 * layers) * if spec.style == BarkStyle::Plated { 0.6 } else { 0.25 });
            c = scale3(c, 0.75 + 0.45 * n_fine * (0.5 + rv));
            c = mix3(c, spec.crack_color, crack);
            r = spec.roughness + 0.1 * (n_fine - 0.5) * rv + crack * 0.05;
        }
        BarkStyle::Lenticels => {
            // smooth glossy skin, horizontal bands, lenticel dashes in rows
            let band = pfbm(Vec2::new(uv.x * 0.25, uv.y), cells(spec.scale * 0.3, 0.5), s ^ 21, 3);
            c = mix3(spec.color, scale3(spec.color, 0.75), band);
            let rows_n = cells(spec.scale * 2.0, 1.0);
            let row_y = uv.y * rows_n[1] as f32;
            let row = row_y.floor();
            let fy = row_y - row;
            // dashes: per row random offsets and lengths, periodic in u
            let per = (rows_n[0] / 2).max(1);
            let off = hash(row as i32, 0, s) * 3.0;
            let xx = uv.x * per as f32 + off;
            let cell = xx.floor();
            let fx = xx - cell;
            let len = 0.25 + 0.45 * hash(cell as i32 % per.max(1), row as i32, s ^ 5);
            let present = hash(cell as i32, row as i32, s ^ 9) < 0.7;
            let dash = if present { (1.0 - smoothstep(len * 0.5 - 0.05, len * 0.5, (fx - 0.5).abs())) * (1.0 - smoothstep(0.12, 0.22, (fy - 0.5).abs())) } else { 0.0 };
            c = mix3(c, spec.accent_color, dash * 0.85);
            c = mix3(c, spec.crack_color, (1.0 - smoothstep(0.0, 0.08, (fy - 0.5).abs() - 0.18)).min(1.0) * dash * 0.4);
            c = scale3(c, 0.88 + 0.24 * n_fine);
            h = (0.1 * band + 0.35 * dash + 0.05 * (n_fine - 0.5)) * dep;
            r = spec.roughness + 0.25 * dash + 0.08 * (n_fine - 0.5) * rv;
        }
        BarkStyle::Peeling => {
            let cw = cells(spec.scale, spec.stretch.max(0.2));
            let (f1, f2, id) = pworley(uv, cw, s);
            let sheet = id < 0.55; // still attached
            let edge = f2 - f1;
            let curl = smoothstep(0.0, 0.12, edge);
            if sheet {
                c = scale3(spec.color, 0.85 + 0.25 * n_fine);
                // fine horizontal striations of papery bark
                let stri = (pfbm(Vec2::new(uv.x * 0.2, uv.y), cells(spec.scale * 6.0, 0.2), s ^ 31, 2) - 0.5) * 0.3;
                c = scale3(c, 1.0 + stri);
                h = (0.55 + 0.1 * n_mid) * dep * curl + 0.25 * dep * (1.0 - curl);
                c = mix3(spec.crack_color, c, 0.35 + 0.65 * curl);
            } else {
                c = mix3(spec.accent_color, spec.crack_color, 0.3 * n_mid);
                c = scale3(c, 0.85 + 0.3 * n_fine);
                h = 0.15 * dep * n_mid;
            }
            r = spec.roughness + 0.12 * (n_fine - 0.5) * rv + if sheet { 0.0 } else { -0.15 };
        }
    }
    if spec.lichen > 0.0 {
        let l = pfbm(uv, cells(spec.scale * 2.5, 1.0), s ^ 77, 4);
        let m = smoothstep(1.0 - spec.lichen * 0.45, 1.0 - spec.lichen * 0.45 + 0.06, l);
        c = mix3(c, [0.55, 0.6, 0.45], m * 0.8);
        h += m * 0.08;
        r = r + m * 0.1;
    }
    (c, h.clamp(-1.0, 1.0), r.clamp(0.02, 1.0))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cell(p: &str) -> FoliageCell {
        FoliageCell::from_preset(p, p).unwrap()
    }

    #[test]
    fn every_preset_draws_a_shape_inside_the_cell() {
        for p in PRESETS {
            let c = cell(p);
            let (w, h) = (96, (96.0 * c.size_m[1] / c.size_m[0]).round() as u32);
            let img = render_cell(&c, w, h);
            let cov: f32 = img.alpha.iter().sum::<f32>() / (w * h) as f32;
            assert!(cov > 0.02 && cov < 0.97, "{p}: coverage {cov}");
            // nothing touches the outer border (the margin keeps cards clean)
            for x in 0..w {
                assert!(img.alpha[x as usize] < 0.5, "{p}: top border");
            }
            for y in 0..h {
                assert!(img.alpha[(y * w) as usize] < 0.5 && img.alpha[(y * w + w - 1) as usize] < 0.5, "{p}: side border");
            }
            // translucency only where there is a leaf
            let lit = img.translucency.iter().zip(&img.alpha).filter(|(t, a)| **a < 0.01 && t.iter().sum::<f32>() > 0.05).count();
            let _ = lit;
        }
    }

    #[test]
    fn shapes_have_their_character() {
        // a palmate maple leaf has deep sinuses: its convex hull is much
        // bigger than its area; an elliptic leaf fills its hull
        let fill = |spec: LeafSpec| {
            let c = FoliageCell { name: "x".into(), size_m: [0.1, 0.1], spec, mount: Mount::Flat, mesh: CardMesh::Quad, preset: String::new() };
            let img = render_cell(&c, 128, 128);
            let area: f32 = img.alpha.iter().sum();
            let (mut x0, mut x1, mut y0, mut y1) = (128, 0, 128, 0);
            for (k, a) in img.alpha.iter().enumerate() {
                if *a > 0.5 {
                    let (x, y) = (k % 128, k / 128);
                    x0 = x0.min(x);
                    x1 = x1.max(x);
                    y0 = y0.min(y);
                    y1 = y1.max(y);
                }
            }
            area / (((x1 - x0) * (y1 - y0)) as f32).max(1.0)
        };
        let maple = fill(preset("maple_leaf").unwrap().0);
        let ellipse = fill(LeafSpec { shape: LeafShape::Elliptic, stem_width: 0.0, ..Default::default() });
        assert!(maple < 0.6 * ellipse, "maple {maple} vs ellipse {ellipse}");
        // serration roughens the outline: more edge texels
        let edge = |spec: LeafSpec| {
            let c = FoliageCell { name: "x".into(), size_m: [0.1, 0.2], spec, mount: Mount::Flat, mesh: CardMesh::Quad, preset: String::new() };
            let img = render_cell(&c, 100, 200);
            let mut n = 0;
            for y in 1..200 {
                for x in 1..100 {
                    let a = img.alpha[y * 100 + x] > 0.5;
                    if a != (img.alpha[y * 100 + x - 1] > 0.5) || a != (img.alpha[(y - 1) * 100 + x] > 0.5) {
                        n += 1;
                    }
                }
            }
            n
        };
        let smooth = edge(LeafSpec { shape: LeafShape::Lanceolate, aspect: 0.35, ..Default::default() });
        let toothed = edge(LeafSpec { shape: LeafShape::Lanceolate, aspect: 0.35, serration: 1.0, teeth: 8, ..Default::default() });
        assert!(toothed > smooth, "serration {toothed} vs {smooth}");
    }

    #[test]
    fn autumn_holes_and_translucency_do_what_they_say() {
        let base = preset("maple_leaf").unwrap().0;
        let mean = |spec: LeafSpec| {
            let c = FoliageCell { name: "x".into(), size_m: [0.1, 0.1], spec, mount: Mount::Flat, mesh: CardMesh::Quad, preset: String::new() };
            let img = render_cell(&c, 96, 96);
            let (mut s, mut n, mut t) = ([0.0f32; 3], 0.0, 0.0);
            for k in 0..img.alpha.len() {
                if img.alpha[k] > 0.9 {
                    for i in 0..3 {
                        s[i] += img.color[k][i];
                    }
                    t += img.translucency[k].iter().sum::<f32>();
                    n += 1.0;
                }
            }
            ([s[0] / n, s[1] / n, s[2] / n], n, t / n)
        };
        let (green, area, tr) = mean(base.clone());
        let (red, _, _) = mean(LeafSpec { autumn: 1.0, autumn_jitter: 0.0, ..base.clone() });
        assert!(green[1] > green[0], "summer leaf is green: {green:?}");
        assert!(red[0] > red[1] * 1.5, "autumn maple is red: {red:?}");
        let (_, holed, _) = mean(LeafSpec { holes: 1.0, ..base.clone() });
        assert!(holed < area * 0.97, "holes remove area: {holed} vs {area}");
        let (_, _, opaque) = mean(LeafSpec { translucency: 0.0, ..base.clone() });
        assert!(tr > 0.2 && opaque < 0.01, "translucency {tr} vs {opaque}");
        // deterministic
        let c = cell("ginkgo");
        assert_eq!(render_cell(&c, 64, 80).alpha, render_cell(&c, 64, 80).alpha);
    }

    #[test]
    fn atlas_and_bleed() {
        let cells = vec![cell("grass"), cell("ivy_leaf")];
        let a = render_atlas(&cells, &[[0.0, 0.0, 0.5, 0.5], [0.5, 0.5, 1.0, 1.0]], 128);
        // the empty quadrants stay transparent
        assert!(a.alpha[(32 * 128 + 96) as usize] == 0.0);
        // and transparent texels inside a cell carry a leaf colour, not black
        let k = (2 * 128 + 2) as usize;
        assert!(a.alpha[k] < 0.01 && a.color[k].iter().sum::<f32>() > 0.05, "bled colour {:?}", a.color[k]);
    }

    #[test]
    fn bark_tiles_seamlessly() {
        for style in BarkStyle::ALL {
            let spec = BarkSpec::for_style(style);
            let (w, h) = (96u32, 96u32);
            let img = render_bark(&spec, [1.0, 1.0], w, h);
            // wrap differences across the edges are like interior neighbour differences
            let at = |x: u32, y: u32| img.height[(y * w + x) as usize];
            let (mut seam, mut inner) = (0.0, 0.0);
            for y in 0..h {
                seam += (at(0, y) - at(w - 1, y)).abs();
                inner += (at(w / 2, y) - at(w / 2 - 1, y)).abs();
            }
            for x in 0..w {
                seam += (at(x, 0) - at(x, h - 1)).abs();
                inner += (at(x, h / 2) - at(x, h / 2 - 1)).abs();
            }
            assert!(seam < inner * 2.0 + 0.5, "{style:?}: seam {seam} vs interior {inner}");
            let var = img.height.iter().map(|v| (v - img.height[0]).abs()).sum::<f32>();
            assert!(var > 1.0, "{style:?} has relief");
        }
        assert_eq!(BarkStyle::from_id("cherry"), Some(BarkStyle::Lenticels));
    }

    #[test]
    fn specs_round_trip_with_defaults() {
        let c = cell("pagoda_tree");
        let s = serde_json::to_string(&c).unwrap();
        assert_eq!(serde_json::from_str::<FoliageCell>(&s).unwrap(), c);
        let partial: LeafSpec = serde_json::from_str(r#"{"shape": "palmate", "lobes": 5}"#).unwrap();
        assert_eq!(partial.shape, LeafShape::Palmate);
        assert_eq!(partial.teeth, LeafSpec::default().teeth);
        assert_eq!(LeafShape::from_id("maple"), Some(LeafShape::Palmate));
        assert_eq!(Arrangement::from_id("pinnate"), Some(Arrangement::Compound));
        for p in PRESETS {
            assert!(preset(p).is_some(), "{p}");
        }
    }

    /// Contact sheet of every preset (colour over grey, translucency, height)
    /// to `target/foliage_presets.png`: `cargo test -p pigment-core dump_foliage_presets -- --ignored`.
    #[test]
    #[ignore]
    fn dump_foliage_presets() {
        let tile = 256u32;
        let n = PRESETS.len() as u32;
        let cols = 6;
        let rows = n.div_ceil(cols);
        let mut out = image::RgbImage::new(cols * tile, rows * tile * 2);
        for (i, p) in PRESETS.iter().enumerate() {
            let c = cell(p);
            let k = (tile as f32 / c.size_m[0].max(c.size_m[1])) * 0.98;
            let (w, h) = (((c.size_m[0] * k) as u32).max(8), ((c.size_m[1] * k) as u32).max(8));
            let img = render_cell(&c, w, h);
            let (ox, oy) = ((i as u32 % cols) * tile, (i as u32 / cols) * tile * 2);
            for y in 0..h {
                for x in 0..w {
                    let j = (y * w + x) as usize;
                    let a = img.alpha[j];
                    let bg = if ((x / 8) + (y / 8)) % 2 == 0 { 0.32 } else { 0.38 };
                    let col = img.color[j];
                    let px = [0, 1, 2].map(|q| ((col[q] * a + bg * (1.0 - a)) * 255.0) as u8);
                    out.put_pixel(ox + x, oy + y, image::Rgb(px));
                    let t = img.translucency[j];
                    let hh = (img.height[j] * 0.5 + 0.5) * a;
                    let px2 = [((t[0] * 0.6 + hh * 0.4) * 255.0) as u8, ((t[1] * 0.6 + hh * 0.4) * 255.0) as u8, ((t[2] * 0.6 + hh * 0.4) * 255.0) as u8];
                    out.put_pixel(ox + x, oy + tile + y, image::Rgb(px2));
                }
            }
        }
        std::fs::create_dir_all("../../target").unwrap();
        out.save("../../target/foliage_presets.png").unwrap();
        let mut bark = image::RgbImage::new(4 * 256, 512);
        for (i, st) in BarkStyle::ALL.iter().enumerate() {
            let img = render_bark(&BarkSpec::for_style(*st), [1.0, 1.0], 256, 256);
            for y in 0..256u32 {
                for x in 0..256u32 {
                    let j = (y * 256 + x) as usize;
                    bark.put_pixel(i as u32 * 256 + x, y, image::Rgb(img.color[j].map(|v| (v.clamp(0.0, 1.0) * 255.0) as u8)));
                    let h = ((img.height[j] * 0.5 + 0.5) * 255.0) as u8;
                    bark.put_pixel(i as u32 * 256 + x, 256 + y, image::Rgb([h, h, h]));
                }
            }
        }
        bark.save("../../target/bark_styles.png").unwrap();
    }
}
