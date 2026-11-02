//! Texture variants: many texture sets from one project.
//!
//! A project authors *everything* once (all candidate signs, posters, lit
//! window colours...). Layers and decals carry an optional variant `group`
//! tag. A [`VariantDef`] then says, relative to the authored state:
//!
//! * `seed`: drives random part subsets (lit windows) and offsets generator
//!   seeds (grime, streaks...), so every variant weathers differently;
//! * `disable` / `enable`: layers, decals or whole groups to switch off / on
//!   (applied in that order, so `disable: ["*"]` + `enable: [...]` picks a few);
//! * `swaps`: replace a decal's image (and optionally tint, emission...).
//!
//! Decals are recorded on their paint layer (image + placement), so a layer
//! whose decals change is rebuilt by replaying them. Keep decals on their own
//! paint layers: brush strokes on a replayed layer are not part of the replay.
//!
//! Everything here is pure data + functions; the app does the GPU work.

use crate::document::{Document, Layer, LayerId, LayerKind, MAX_SELECTABLE_PARTS};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

fn yes() -> bool {
    true
}

/// Variant data on a layer. Empty for most layers.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct LayerVariant {
    /// Group tag that variants can enable / disable ("" = untagged).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub group: String,
    /// Keep only a seeded random share of the mask's parts.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub part_subset: Option<PartSubset>,
    /// Decals projected onto this (paint) layer, in order.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub decals: Vec<DecalRecord>,
}

impl LayerVariant {
    pub fn is_empty(&self) -> bool {
        self.group.is_empty() && self.part_subset.is_none() && self.decals.is_empty()
    }
}

/// A seeded random share of parts: part `p` is kept when its roll
/// `part_roll(seed, salt, p)` lies in `[from, to)`. Layers sharing a salt
/// with disjoint ranges get disjoint parts (warm / cyan / pink windows).
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct PartSubset {
    pub from: f32,
    pub to: f32,
    #[serde(default)]
    pub salt: u32,
}

/// One projected decal, replayable with another image.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DecalRecord {
    pub name: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub group: String,
    /// Painted in the authored state (variants can flip it).
    #[serde(default = "yes")]
    pub enabled: bool,
    /// The `project_decal` arguments: image, part or rect + camera, tint, emission...
    pub args: Value,
}

/// One texture set to export.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VariantDef {
    pub name: String,
    #[serde(default)]
    pub seed: u32,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub enable: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub disable: Vec<String>,
    /// decal / group / layer name -> image path, or {image, tint, emissive_strength, opacity, ...}.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub swaps: BTreeMap<String, Value>,
}

/// The document's variant state: the active seed and the stored definitions.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Variants {
    /// Active variant seed (0 = the authored look).
    #[serde(default)]
    pub seed: u32,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub defs: Vec<VariantDef>,
}

impl Variants {
    pub fn is_empty(&self) -> bool {
        self.seed == 0 && self.defs.is_empty()
    }
}

/// Uniform 0..1 roll for a part, stable for a (seed, salt, part).
pub fn part_roll(seed: u32, salt: u32, part: u32) -> f32 {
    let mut x = (seed as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ (salt as u64).wrapping_mul(0xC2B2_AE3D_27D4_EB4F) ^ (part as u64 + 1).wrapping_mul(0x1656_67B1_9E37_79F9);
    // splitmix64 finaliser
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^= x >> 31;
    (x >> 40) as f32 / (1u64 << 24) as f32
}

/// Generator seed under a variant seed (unchanged for seed 0).
pub fn generator_seed(seed: u32, variant_seed: u32) -> u32 {
    seed.wrapping_add(variant_seed % 9973)
}

/// The parts a layer's mask selects under `seed`. `None` = no part
/// restriction (the whole model); `Some(empty)` = nothing.
pub fn selected_parts(l: &Layer, seed: u32) -> Option<Vec<u32>> {
    let m = l.mask.as_ref()?;
    match &l.variant.part_subset {
        None => (!m.parts.is_empty()).then(|| m.parts.clone()),
        Some(s) => {
            let candidates: Vec<u32> = if m.parts.is_empty() { (0..MAX_SELECTABLE_PARTS).collect() } else { m.parts.clone() };
            Some(
                candidates
                    .into_iter()
                    .filter(|&p| {
                        let r = part_roll(seed, s.salt, p);
                        r >= s.from && r < s.to
                    })
                    .collect(),
            )
        }
    }
}

/// A variant applied to a document.
#[derive(Clone, Debug)]
pub struct Resolved {
    pub doc: Document,
    /// Paint layers whose decals changed: clear and replay their enabled decals.
    pub replay: Vec<LayerId>,
}

fn matches(sel: &str, name: &str, group: &str) -> bool {
    if sel == "*" {
        return !group.is_empty();
    }
    sel.eq_ignore_ascii_case(name) || (!group.is_empty() && sel.eq_ignore_ascii_case(group))
}

/// Apply a swap value to a decal's arguments.
fn swap_args(args: &mut Value, v: &Value) -> Result<(), String> {
    match v {
        Value::String(img) => args["image"] = Value::String(img.clone()),
        Value::Object(o) => {
            for (k, x) in o {
                if matches!(k.as_str(), "layer" | "name" | "variant" | "enabled") {
                    return Err(format!("swap can't change `{k}`"));
                }
                args[k.as_str()] = x.clone();
            }
        }
        _ => return Err("a swap is an image path or {image, tint, emissive_strength, ...}".into()),
    }
    Ok(())
}

/// Check a set of variant definitions (unique, folder-safe names).
pub fn validate_defs(defs: &[VariantDef]) -> Result<(), String> {
    let mut seen = std::collections::HashSet::new();
    for v in defs {
        if v.name.is_empty() || !v.name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') {
            return Err(format!("variant name `{}` must be non-empty letters, digits, _ or -", v.name));
        }
        if !seen.insert(v.name.to_ascii_lowercase()) {
            return Err(format!("duplicate variant name `{}`", v.name));
        }
    }
    Ok(())
}

/// The document as variant `v` sees it. Every selector must match something,
/// so a typo fails loudly instead of silently exporting the wrong look.
pub fn resolve(doc: &Document, v: &VariantDef) -> Result<Resolved, String> {
    let mut d = doc.clone();
    d.variants.seed = v.seed;
    for (list, on) in [(&v.disable, false), (&v.enable, true)] {
        for sel in list {
            let mut hit = false;
            for l in &mut d.layers {
                if matches(sel, &l.name, &l.variant.group) {
                    l.visible = on;
                    hit = true;
                }
                for dc in &mut l.variant.decals {
                    if matches(sel, &dc.name, &dc.group) {
                        dc.enabled = on;
                        hit = true;
                    }
                }
                // decal objects (decal layers are regenerated from them)
                for o in l.decals.iter_mut().flat_map(|s| s.objects.iter_mut()) {
                    if matches(sel, &o.name, &o.group) {
                        o.enabled = on;
                        hit = true;
                    }
                }
            }
            if !hit {
                return Err(format!("variant `{}`: `{sel}` matches no layer, decal or group", v.name));
            }
        }
    }
    for (sel, val) in &v.swaps {
        let mut hit = false;
        for l in &mut d.layers {
            let whole_layer = sel.eq_ignore_ascii_case(&l.name);
            for dc in &mut l.variant.decals {
                if whole_layer || matches(sel, &dc.name, &dc.group) {
                    swap_args(&mut dc.args, val).map_err(|e| format!("variant `{}`, swap `{sel}`: {e}", v.name))?;
                    hit = true;
                }
            }
            for o in l.decals.iter_mut().flat_map(|s| s.objects.iter_mut()) {
                if whole_layer || matches(sel, &o.name, &o.group) {
                    match val {
                        serde_json::Value::String(img) => o.image = img.clone(),
                        v => {
                            if let Some(img) = v.get("image").and_then(|x| x.as_str()) {
                                o.image = img.to_string();
                            }
                            if let Some(t) = v.get("tint").and_then(|x| x.as_array()) {
                                for (k, x) in t.iter().take(3).enumerate() {
                                    o.values.base_color[k] = x.as_f64().unwrap_or(1.0) as f32;
                                }
                            }
                        }
                    }
                    hit = true;
                }
            }
        }
        if !hit {
            return Err(format!("variant `{}`: swap `{sel}` matches no decal", v.name));
        }
    }
    let replay = d
        .layers
        .iter()
        .filter(|l| matches!(l.kind, LayerKind::Paint { .. }))
        .filter(|l| {
            let before = doc.layer(l.id).map(|o| &o.variant.decals);
            before.is_some_and(|b| b.iter().zip(&l.variant.decals).any(|(a, c)| a.enabled != c.enabled || a.args != c.args))
        })
        .map(|l| l.id)
        .collect();
    Ok(Resolved { doc: d, replay })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::document::{Mask, MaterialValues};
    use serde_json::json;

    fn rec(name: &str, group: &str, image: &str, enabled: bool) -> DecalRecord {
        DecalRecord { name: name.into(), group: group.into(), enabled, args: json!({ "image": image, "part": 3 }) }
    }

    fn town_doc() -> Document {
        let mut d = Document::default();
        let mut glass = d.new_fill_layer("Lit windows");
        glass.kind = LayerKind::Fill { values: MaterialValues::default() };
        glass.mask = Some(Mask { parts: (0..40).collect(), ..Mask::new(d.mint()) });
        glass.variant.part_subset = Some(PartSubset { from: 0.0, to: 0.3, salt: 1 });
        d.layers.push(glass);
        let mut poster = d.new_fill_layer("Poster glow");
        poster.variant.group = "posters".into();
        d.layers.push(poster);
        let mut signs = d.new_paint_layer("Signs");
        signs.variant.decals = vec![rec("shop", "street", "a.png", true), rec("pawn", "street", "b.png", false), rec("eye", "corp", "eye.png", true)];
        d.layers.push(signs);
        d
    }

    #[test]
    fn rolls_are_uniform_and_seeded() {
        let n = 20000;
        let mean: f32 = (0..n).map(|p| part_roll(7, 0, p)).sum::<f32>() / n as f32;
        assert!((mean - 0.5).abs() < 0.02, "{mean}");
        assert!((0..n).all(|p| (0.0..1.0).contains(&part_roll(7, 0, p))));
        let a: Vec<bool> = (0..64).map(|p| part_roll(1, 0, p) < 0.5).collect();
        let b: Vec<bool> = (0..64).map(|p| part_roll(2, 0, p) < 0.5).collect();
        assert_ne!(a, b, "different seeds pick different parts");
        assert_eq!(part_roll(5, 2, 9), part_roll(5, 2, 9));
        assert_eq!(generator_seed(3, 0), 3);
    }

    #[test]
    fn part_subsets_follow_the_seed_and_ranges_are_disjoint() {
        let d = town_doc();
        let l = &d.layers[0];
        let a = selected_parts(l, 1).unwrap();
        let b = selected_parts(l, 2).unwrap();
        assert!(a.len() > 4 && a.len() < 25, "{a:?}");
        assert_ne!(a, b);
        assert!(a.iter().all(|p| *p < 40));
        let mut other = l.clone();
        other.variant.part_subset = Some(PartSubset { from: 0.3, to: 0.6, salt: 1 });
        let c = selected_parts(&other, 1).unwrap();
        assert!(c.iter().all(|p| !a.contains(p)), "same salt, disjoint ranges");
        // no mask -> no restriction; mask parts without a subset -> those parts
        assert_eq!(selected_parts(&d.layers[1], 1), None);
        let mut m = l.clone();
        m.variant.part_subset = None;
        assert_eq!(selected_parts(&m, 9).unwrap().len(), 40);
    }

    #[test]
    fn enable_disable_and_swaps() {
        let d = town_doc();
        let v = VariantDef {
            name: "v1".into(),
            seed: 4,
            enable: vec!["pawn".into()],
            disable: vec!["*".into()],
            swaps: [("eye".to_string(), json!({ "image": "eye2.png", "tint": [1, 0, 0] }))].into(),
        };
        let r = resolve(&d, &v).unwrap();
        assert_eq!(r.doc.variants.seed, 4);
        assert!(!r.doc.layers[1].visible, "tagged layer disabled by *");
        assert!(r.doc.layers[0].visible, "untagged layer untouched by *");
        let dc = &r.doc.layers[2].variant.decals;
        assert_eq!(dc.iter().map(|x| x.enabled).collect::<Vec<_>>(), [false, true, false]);
        assert_eq!(dc[2].args["image"], "eye2.png");
        assert_eq!(dc[2].args["part"], 3);
        assert_eq!(r.replay, vec![d.layers[2].id]);
        // nothing about decals changes -> nothing to replay
        let plain = VariantDef { name: "p".into(), seed: 9, enable: vec![], disable: vec!["posters".into()], swaps: Default::default() };
        let r = resolve(&d, &plain).unwrap();
        assert!(r.replay.is_empty() && !r.doc.layers[1].visible);
        // swapping a whole layer by name, string form
        let sw = VariantDef { name: "s".into(), seed: 0, enable: vec![], disable: vec![], swaps: [("Signs".to_string(), json!("z.png"))].into() };
        let r = resolve(&d, &sw).unwrap();
        assert!(r.doc.layers[2].variant.decals.iter().all(|x| x.args["image"] == "z.png"));
    }

    #[test]
    fn typos_fail_loudly() {
        let d = town_doc();
        let bad = VariantDef { name: "x".into(), seed: 0, enable: vec!["shpo".into()], disable: vec![], swaps: Default::default() };
        assert!(resolve(&d, &bad).unwrap_err().contains("shpo"));
        let bad = VariantDef { name: "x".into(), seed: 0, enable: vec![], disable: vec![], swaps: [("nope".to_string(), json!("a.png"))].into() };
        assert!(resolve(&d, &bad).is_err());
        let bad = VariantDef { name: "x".into(), seed: 0, enable: vec![], disable: vec![], swaps: [("shop".to_string(), json!({ "layer": 2 }))].into() };
        assert!(resolve(&d, &bad).is_err());
        let ok = VariantDef { name: "a_1".into(), seed: 0, enable: vec![], disable: vec![], swaps: Default::default() };
        assert!(validate_defs(&[ok.clone(), VariantDef { name: "A_1".into(), ..ok.clone() }]).is_err());
        assert!(validate_defs(&[VariantDef { name: "a/b".into(), ..ok.clone() }]).is_err());
        assert!(validate_defs(&[ok]).is_ok());
    }

    #[test]
    fn variant_data_round_trips_and_old_projects_load() {
        let mut d = town_doc();
        d.variants.defs.push(VariantDef { name: "a".into(), seed: 3, enable: vec!["pawn".into()], disable: vec![], swaps: Default::default() });
        let s = serde_json::to_string(&d).unwrap();
        let back: Document = serde_json::from_str(&s).unwrap();
        assert_eq!(back, d);
        // a plain document doesn't mention variants at all
        let plain = serde_json::to_value(Document::new_default()).unwrap();
        assert!(plain.get("variants").is_none());
        assert!(plain["layers"][0].get("variant").is_none());
        let old: Document = serde_json::from_value(plain).unwrap();
        assert!(old.variants.is_empty() && old.layers.iter().all(|l| l.variant.is_empty()));
    }
}
