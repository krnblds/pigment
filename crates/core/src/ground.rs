//! Natural-ground building blocks (see docs/agents/ground/NOTES.md):
//!
//! * five generators that make real structure instead of noise blobs:
//!   `cells` (Voronoi: F1 domes, F2, F2 - F1 edges / plates, a random value per
//!   cell), `scatter` (bombing: pebbles, flakes, leaves, twigs / needles,
//!   shells with a rounded height profile each), `rock` (domain-warped ridged
//!   rock with strata ledges, block-joint cracks and downhill streaks),
//!   `blades` (a dense grass-blade field with clumps, lean and tips) and
//!   `ripples` (wind ripples with bifurcations, not stripes). They live in
//!   `GeneratorKind` like every other generator and are tile-periodic in
//!   tile mode (`gen_ground.wgsl`).
//! * three fill-layer options:
//!   - `height_profile`: the fill's height follows the generator's shape (a
//!     dome per pebble, the blade's rise to its tip, the ripple profile)
//!     instead of a flat plateau under the mask;
//!   - `height_blend`: the layer only shows where its height level is above
//!     the stack's height (sand settling between pebbles, water in the lows)
//!     or below it (moss on the tops), with a contrast;
//!   - `jitter`: per-instance colour / roughness variation driven by the
//!     generator's instance id (each pebble, cell, blade gets its own tone).
//!
//! All of them are serde-defaulted, so older projects load unchanged.

use serde::{Deserialize, Serialize};

/// Which side of the stack's height a height-blended layer shows on.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HeightBlendMode {
    /// Shows where the layer's level is above the stack: fills the lows
    /// (sand between pebbles, water and mud in ruts).
    #[default]
    Above,
    /// Shows where the stack rises above the layer's level: the tops
    /// (moss and lichen on stones, dust on ridges).
    Below,
}

impl HeightBlendMode {
    pub const ALL: [HeightBlendMode; 2] = [HeightBlendMode::Above, HeightBlendMode::Below];
    pub fn id(self) -> &'static str {
        match self {
            HeightBlendMode::Above => "above",
            HeightBlendMode::Below => "below",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            HeightBlendMode::Above => "Fill the lows",
            HeightBlendMode::Below => "On the tops",
        }
    }
    pub fn from_id(s: &str) -> Option<HeightBlendMode> {
        match s.to_ascii_lowercase().as_str() {
            "above" | "lows" | "fill" | "fill_lows" | "low" => Some(HeightBlendMode::Above),
            "below" | "tops" | "top" | "peaks" | "high" => Some(HeightBlendMode::Below),
            _ => None,
        }
    }
    pub fn gpu_id(self) -> f32 {
        match self {
            HeightBlendMode::Above => 1.0,
            HeightBlendMode::Below => 2.0,
        }
    }
}

/// Blend a fill layer by height: it covers texels where its level
/// (`offset`, plus the layer's own height when its height channel is on)
/// is above (or below) the height composited so far.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct HeightBlend {
    #[serde(default)]
    pub mode: HeightBlendMode,
    /// Width of the transition in height units (0 = a hard line).
    #[serde(default = "contrast")]
    pub contrast: f32,
    /// Added to the layer's level (height units, -1..1 like fill heights).
    #[serde(default)]
    pub offset: f32,
}

fn contrast() -> f32 {
    0.05
}

impl Default for HeightBlend {
    fn default() -> Self {
        Self { mode: HeightBlendMode::Above, contrast: contrast(), offset: 0.0 }
    }
}

/// Per-instance variation of a fill, keyed by the mask generator's instance
/// id (a pebble, a Voronoi cell, a grass blade, a rock block). Each amount is
/// the +/- range: value 0.2 = brightness x 0.8 .. 1.2.
#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct InstanceJitter {
    #[serde(default)]
    pub value: f32,
    /// Hue rotation range in turns (0.05 = +/- 18 degrees).
    #[serde(default)]
    pub hue: f32,
    #[serde(default)]
    pub saturation: f32,
    #[serde(default)]
    pub roughness: f32,
}

impl InstanceJitter {
    pub fn is_zero(&self) -> bool {
        self.value == 0.0 && self.hue == 0.0 && self.saturation == 0.0 && self.roughness == 0.0
    }
}

/// Variant (output / shape) names of the ground generators.
pub const CELL_VARIANTS: [&str; 5] = ["dome", "f2", "edges", "value", "plates"];
pub const SCATTER_VARIANTS: [&str; 5] = ["pebble", "flake", "leaf", "twig", "shell"];
pub const ROCK_VARIANTS: [&str; 3] = ["height", "cracks", "ledges"];
pub const BLADE_VARIANTS: [&str; 3] = ["height", "tips", "clumps"];
pub const RIPPLE_VARIANTS: [&str; 2] = ["height", "crests"];

/// Aliases accepted as `generator` that also pick a variant:
/// (alias, generator id, variant).
pub const GROUND_ALIASES: [(&str, &str, &str); 22] = [
    ("voronoi", "cells", "dome"),
    ("cellular", "cells", "dome"),
    ("worley", "cells", "dome"),
    ("cell_edges", "cells", "edges"),
    ("cobbles", "cells", "plates"),
    ("flagstones", "cells", "plates"),
    ("cracked_mud", "cells", "plates"),
    ("mud_cracks", "cells", "plates"),
    ("bombing", "scatter", "pebble"),
    ("pebbles", "scatter", "pebble"),
    ("gravel", "scatter", "pebble"),
    ("stones", "scatter", "pebble"),
    ("leaves", "scatter", "leaf"),
    ("twigs", "scatter", "twig"),
    ("needles", "scatter", "twig"),
    ("shells", "scatter", "shell"),
    ("strata", "rock", "height"),
    ("eroded_rock", "rock", "height"),
    ("grass", "blades", "height"),
    ("turf", "blades", "height"),
    ("sand_ripples", "ripples", "height"),
    ("waves", "ripples", "height"),
];

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Document, GeneratorKind};

    #[test]
    fn ground_options_default_and_round_trip() {
        let mut d = Document::default();
        let mut l = d.new_fill_layer("Sand");
        let plain = serde_json::to_value(&l).unwrap();
        for k in ["height_blend", "jitter", "height_profile"] {
            assert!(plain.get(k).is_none(), "{k} is skipped when unset: {plain}");
        }
        l.height_blend = Some(HeightBlend { mode: HeightBlendMode::Below, contrast: 0.1, offset: 0.2 });
        l.jitter = Some(InstanceJitter { value: 0.2, hue: 0.02, saturation: 0.1, roughness: 0.15 });
        l.height_profile = true;
        let back: crate::Layer = serde_json::from_value(serde_json::to_value(&l).unwrap()).unwrap();
        assert_eq!(back, l);
        // partial objects fill in defaults
        let hb: HeightBlend = serde_json::from_str("{}").unwrap();
        assert_eq!(hb, HeightBlend::default());
        assert_eq!(HeightBlendMode::from_id("tops"), Some(HeightBlendMode::Below));
        assert_eq!(HeightBlendMode::from_id("lows"), Some(HeightBlendMode::Above));
    }

    #[test]
    fn ground_aliases_name_real_generators_and_variants() {
        for (alias, id, v) in GROUND_ALIASES {
            let k = GeneratorKind::from_id(alias).unwrap_or_else(|| panic!("{alias}"));
            assert_eq!(k.id(), id, "{alias}");
            assert!(k.variant_names().contains(&v), "{alias}: {v}");
            assert_eq!(k.alias_variant(alias), k.variant_names().iter().position(|x| *x == v).map(|i| i as u32));
        }
    }
}
