//! MCP: foliage. Foliage atlas projects (`new_project.foliage_atlas`,
//! `add_foliage_cell`, `update_foliage_cell`), bark on seamless tiles
//! (`add_bark`), and foliage layers on models (`paint_foliage`,
//! `scatter_foliage`, `grow_ivy`, `export_foliage`).

use super::*;
use crate::app::foliage::{FoliageBrush, MaskImage, MaskSource};
use glam::Vec3;
use pigment_core::decal::SurfaceTri;
use pigment_core::foliage::{self as fol, CardMesh, FoliageCell, LeafSpec, Mount};
use pigment_core::foliage_set::{IvyOpts, PlaceOpts, ScatterOpts, SurfaceFilter};

/// Leaf spec keys accepted on a cell (everything in `LeafSpec`).
pub const LEAF_KEYS: [&str; 39] = [
    "shape", "arrangement", "count", "aspect", "lobes", "lobe_depth", "spread", "serration", "teeth", "venation", "veins", "vein_angle", "color", "tip_color",
    "tip_amount", "vein_color", "hue_jitter", "value_jitter", "autumn", "autumn_jitter", "autumn_color", "dry_edges", "dry_color", "holes", "bites",
    "translucency", "translucency_color", "roughness", "stem_color", "stem_width", "bend", "wave", "leaf_size", "stamens", "seed",
    // cell-level keys handled next to the spec
    "name", "preset", "size_m", "mount",
];

fn vec3(v: &Value) -> Option<Vec3> {
    let a = v.as_array()?;
    Some(Vec3::new(a.first()?.as_f64()? as f32, a.get(1)?.as_f64()? as f32, a.get(2)?.as_f64()? as f32))
}

fn pair(v: &Value, what: &str) -> Res<(f32, f32)> {
    if let Some(x) = v.as_f64() {
        return Ok((x as f32, x as f32));
    }
    match v.as_array().map(|a| a.iter().filter_map(Value::as_f64).map(|x| x as f32).collect::<Vec<_>>()).as_deref() {
        Some([a, b]) => Ok((*a, *b)),
        _ => Err(format!("`{what}` must be a number or [min, max], got {v}")),
    }
}

/// Apply the spec fields of `a` on top of `spec` (serde does the typing).
fn apply_spec(spec: &LeafSpec, a: &Value, path: &str) -> Res<LeafSpec> {
    let mut j = serde_json::to_value(spec).unwrap();
    if let Some(o) = a.as_object() {
        for (k, v) in o {
            if LEAF_KEYS[..35].contains(&k.as_str()) {
                if k == "shape" && v.as_str().is_some_and(|s| fol::LeafShape::from_id(s).is_none()) {
                    return Err(format!("`{path}shape` = {v}: one of {}", fol::LeafShape::ALL.map(|s| s.id()).join(", ")));
                }
                if k == "arrangement" && v.as_str().is_some_and(|s| fol::Arrangement::from_id(s).is_none()) {
                    return Err(format!("`{path}arrangement` = {v}: one of {}", fol::Arrangement::ALL.map(|s| s.id()).join(", ")));
                }
                // accept aliases (maple -> palmate, pinnate -> compound)
                let v = match k.as_str() {
                    "shape" => json!(fol::LeafShape::from_id(v.as_str().unwrap_or("")).map(|s| s.id()).unwrap_or("ovate")),
                    "arrangement" => json!(fol::Arrangement::from_id(v.as_str().unwrap_or("")).map(|s| s.id()).unwrap_or("single")),
                    _ => v.clone(),
                };
                j[k] = v;
            }
        }
    }
    serde_json::from_value(j).map_err(|e| format!("`{path}`: {e}"))
}

/// A foliage cell from `{name, preset, size_m, mount, mesh, ...leaf params}`.
fn parse_cell(c: &Value, i: usize, base: Option<&FoliageCell>) -> Res<FoliageCell> {
    let path = format!("cells[{i}].");
    let name = s(c, "name").map(String::from).or_else(|| base.map(|b| b.name.clone())).or_else(|| s(c, "preset").map(String::from)).unwrap_or_else(|| format!("cell{i}"));
    let mut cell = match (s(c, "preset"), base) {
        (Some(p), _) => FoliageCell::from_preset(&name, p).ok_or_else(|| format!("`{path}preset` = \"{p}\": unknown (one of: {})", fol::PRESETS.join(", ")))?,
        (None, Some(b)) => b.clone(),
        (None, None) => FoliageCell { name: name.clone(), size_m: [0.2, 0.2], spec: LeafSpec::default(), mount: Mount::Upright, mesh: CardMesh::Quad, preset: String::new() },
    };
    cell.name = name;
    if let Some(v) = c.get("size_m") {
        let (w, h) = pair(v, &format!("{path}size_m"))?;
        if !(w > 0.0 && h > 0.0) {
            return Err(format!("`{path}size_m` must be > 0"));
        }
        cell.size_m = [w, h];
    }
    if let Some(m) = s(c, "mount") {
        cell.mount = Mount::from_id(m).ok_or_else(|| format!("`{path}mount` = \"{m}\": one of upright, flat, wall, hanging"))?;
    }
    if let Some(m) = s(c, "mesh") {
        cell.mesh = CardMesh::from_id(m).ok_or_else(|| format!("`{path}mesh` = \"{m}\": one of quad, cross, star"))?;
    }
    cell.spec = apply_spec(&cell.spec, c, &path)?;
    Ok(cell)
}

fn cell_json(c: &FoliageCell) -> Value {
    json!({ "name": c.name, "preset": c.preset, "size_m": c.size_m, "mount": c.mount.id(), "mesh": c.mesh.id(), "shape": c.spec.shape.id(), "arrangement": c.spec.arrangement.id() })
}

/// `cells` as names or {cell, weight}.
fn cell_list(a: &Value, default: &[&str]) -> Res<Vec<(String, f32)>> {
    match a.get("cells") {
        None => Ok(default.iter().map(|c| (c.to_string(), 1.0)).collect()),
        Some(Value::String(c)) => Ok(vec![(c.clone(), 1.0)]),
        Some(Value::Array(v)) if !v.is_empty() => v
            .iter()
            .enumerate()
            .map(|(k, c)| match c {
                Value::String(n) => Ok((n.clone(), 1.0)),
                Value::Object(_) => Ok((s(c, "cell").ok_or_else(|| format!("`cells[{k}].cell` is required"))?.to_string(), f(c, "weight").unwrap_or(1.0))),
                _ => Err(format!("`cells[{k}]` must be a cell name or {{cell, weight}}")),
            })
            .collect(),
        Some(v) => Err(format!("`cells` must be a non-empty array of cell names, got {v}")),
    }
}

impl Session {
    // ------------------------------------------------------------ foliage atlas projects

    /// `new_project` with `foliage_atlas`: a decal-atlas sheet whose cells are
    /// drawn by the leaf generators into a generated paint layer.
    pub(super) fn new_foliage_atlas(&mut self, a: &Value) -> Res<Value> {
        let fa = &a["foliage_atlas"];
        let list = fa.get("cells").and_then(Value::as_array).filter(|c| !c.is_empty()).ok_or("`foliage_atlas.cells` must be a non-empty array of {name, preset, size_m, ...}")?;
        let cells: Vec<FoliageCell> = list.iter().enumerate().map(|(i, c)| parse_cell(c, i, None)).collect::<Res<_>>()?;
        let mut names = std::collections::HashSet::new();
        for c in &cells {
            if !names.insert(c.name.clone()) {
                return Err(format!("`foliage_atlas.cells`: two cells are named `{}`", c.name));
            }
        }
        self.build_foliage_atlas(cells, fa, a.get("resolution").and_then(Value::as_u64).map(|r| r as u32))
    }

    fn build_foliage_atlas(&mut self, cells: Vec<FoliageCell>, fa: &Value, resolution: Option<u32>) -> Res<Value> {
        let tile = json!({
            "cells": cells.iter().map(|c| json!({ "name": c.name, "size_m": c.size_m })).collect::<Vec<_>>(),
            "padding_px": fa.get("padding_px").and_then(Value::as_u64).unwrap_or(16),
            "name": s(fa, "name").unwrap_or("FoliageAtlas"),
            "folders": fa.get("folders").and_then(Value::as_bool).unwrap_or(true),
        });
        let mut args = json!({ "tile": tile });
        if let Some(r) = resolution {
            args["resolution"] = json!(r);
        }
        self.new_sheet_project(&args)?;
        let mut gen = self.app.doc.new_paint_layer("Leaves (generated)");
        gen.generated = Some(Generated::FoliageCells { cells: cells.clone() });
        // above the transparent base, below the cell folders
        self.app.doc.layers.insert(1, gen);
        self.app.committed = self.app.doc.clone();
        let _ = self.app.history.clear();
        self.settle();
        Ok(json!({
            "atlas": self.app.doc.tile.as_ref().map(|t| t.layout_json(&self.app.export_name, self.app.doc.resolution)),
            "cells": cells.iter().map(cell_json).collect::<Vec<_>>(),
            "layers": self.layers(),
            "hint": "add grime / colour layers inside each cell's folder; export_textures writes BaseColorAlpha, Translucency, Thickness and <name>_foliage.json (use it as a foliage layer's `atlas`)",
        }))
    }

    fn atlas_cells(&self) -> Res<(usize, Vec<FoliageCell>)> {
        self.app
            .doc
            .layers
            .iter()
            .enumerate()
            .find_map(|(i, l)| match &l.generated {
                Some(Generated::FoliageCells { cells }) => Some((i, cells.clone())),
                _ => None,
            })
            .ok_or_else(|| "this is not a foliage atlas project (start one with new_project {foliage_atlas: {cells: [...]}})".to_string())
    }

    /// Repack the atlas with a new cell list: keeps fills / folders (cell
    /// folders keep their part index), redraws the generated cells. Painted
    /// pixels can't follow a repack and are cleared.
    fn rebuild_atlas(&mut self, cells: Vec<FoliageCell>) -> Res<Vec<String>> {
        let old = self.app.doc.tile.clone().ok_or("no sheet")?;
        let list: Vec<(String, [f32; 2])> = cells.iter().map(|c| (c.name.clone(), c.size_m)).collect();
        let pad = (old.cells.iter().map(|c| c.uv[0]).fold(1.0f32, f32::min) * self.app.doc.resolution as f32).round().max(1.0) as u32;
        let spec = pigment_core::tile::TileSpec::atlas(&list, self.app.doc.resolution, pad)?;
        let mut doc = self.app.doc.clone();
        doc.tile = Some(spec.clone());
        let mut warnings = vec![];
        for l in &mut doc.layers {
            if let Some(Generated::FoliageCells { cells: c }) = &mut l.generated {
                *c = cells.clone();
            } else if l.is_paint() {
                warnings.push(format!("paint layer `{}` was cleared (its pixels can't follow the repacked cells)", l.name));
            }
        }
        // a folder for each new cell
        for (i, c) in cells.iter().enumerate().skip(old.cells.len()) {
            let mut f = doc.new_folder(&c.name);
            let res = doc.mint();
            f.mask = Some(Mask { parts: vec![i as u32], ..Mask::new(res) });
            doc.layers.push(f);
        }
        let mesh = spec.mesh();
        let name = self.app.export_name.clone();
        self.app.new_project(&self.rs, mesh, None, doc.clone());
        // new_project resets the doc's resolution to the session's; masks need pixels
        for l in &self.app.doc.layers {
            if let Some(m) = &l.mask {
                if !self.app.ts.masks.contains_key(&m.res) {
                    self.app.ts.new_mask(&self.rs.device, &self.rs.queue, m.res, true);
                }
            }
        }
        self.app.export_name = name;
        self.app.foliage.generated.clear();
        self.app.committed = self.app.doc.clone();
        let _ = self.app.history.clear();
        self.settle();
        Ok(warnings)
    }

    pub fn add_foliage_cell(&mut self, a: &Value) -> Res<Value> {
        let (_, mut cells) = self.atlas_cells()?;
        let c = parse_cell(a, cells.len(), None)?;
        if cells.iter().any(|x| x.name == c.name) {
            return Err(format!("a cell named `{}` already exists (use update_foliage_cell)", c.name));
        }
        cells.push(c.clone());
        let warnings = self.rebuild_atlas(cells)?;
        Ok(json!({ "added": cell_json(&c), "atlas": self.app.doc.tile.as_ref().map(|t| t.layout_json(&self.app.export_name, self.app.doc.resolution)), "warnings": warnings }))
    }

    pub fn update_foliage_cell(&mut self, a: &Value) -> Res<Value> {
        let (li, mut cells) = self.atlas_cells()?;
        let k = match a.get("cell") {
            Some(Value::Number(n)) => n.as_u64().map(|n| n as usize).filter(|n| *n < cells.len()).ok_or_else(|| format!("`cell` = {n}: no such cell (0..{})", cells.len() - 1))?,
            Some(Value::String(n)) => cells.iter().position(|c| c.name.eq_ignore_ascii_case(n)).ok_or_else(|| format!("`cell` = \"{n}\": no such cell (cells: {})", cells.iter().map(|c| c.name.as_str()).collect::<Vec<_>>().join(", ")))?,
            _ => return Err("`cell` (name or index) is required".into()),
        };
        let mut upd = a.clone();
        if let Some(o) = upd.as_object_mut() {
            o.remove("cell");
            if o.get("rename").is_some() {
                let r = o.remove("rename").unwrap();
                o.insert("name".into(), r);
            }
        }
        let before = cells[k].clone();
        let c = parse_cell(&upd, k, Some(&before))?;
        let resized = c.size_m != before.size_m;
        cells[k] = c.clone();
        if resized {
            let warnings = self.rebuild_atlas(cells)?;
            return Ok(json!({ "cell": cell_json(&c), "repacked": true, "warnings": warnings }));
        }
        if let Some(Generated::FoliageCells { cells: g }) = &mut self.app.doc.layers[li].generated {
            *g = cells;
        }
        self.settle();
        Ok(json!({ "cell": cell_json(&c), "spec": c.spec }))
    }

    /// Bark on a seamless tile: a generated paint layer above the base.
    pub fn add_bark(&mut self, a: &Value) -> Res<Value> {
        if self.app.doc.tile.as_ref().is_none_or(|t| t.kind != pigment_core::tile::SheetKind::Tile) {
            return Err("add_bark needs a seamless tile project: new_project {tile: {size_m: [1, 2]}}".into());
        }
        let style = s(a, "style").unwrap_or("fissured");
        let mut spec = crate::app::foliage::bark_spec(style).ok_or_else(|| format!("`style` = \"{style}\": one of fissured, plated, lenticels (cherry), peeling"))?;
        let mut j = serde_json::to_value(&spec).unwrap();
        for k in ["scale", "stretch", "depth", "roughness_variation", "color", "crack_color", "accent_color", "roughness", "lichen", "seed"] {
            if let Some(v) = a.get(k) {
                j[k] = v.clone();
            }
        }
        spec = serde_json::from_value(j).map_err(|e| format!("add_bark: {e}"))?;
        let name = s(a, "name").unwrap_or("Bark (generated)").to_string();
        let existing = self.app.doc.layers.iter().position(|l| l.name == name && matches!(l.generated, Some(Generated::Bark { .. })));
        match existing {
            Some(i) => self.app.doc.layers[i].generated = Some(Generated::Bark { bark: spec.clone() }),
            None => {
                let mut l = self.app.doc.new_paint_layer(&name);
                l.generated = Some(Generated::Bark { bark: spec.clone() });
                let at = 1.min(self.app.doc.layers.len());
                self.app.doc.layers.insert(at, l);
            }
        }
        self.settle();
        Ok(json!({ "layer": name, "bark": spec, "layers": self.layers() }))
    }

    // ------------------------------------------------------------ foliage layers

    fn foliage_target(&mut self, a: &Value) -> Res<usize> {
        let name = match a.get("layer") {
            None => None,
            Some(Value::String(n)) => Some(n.clone()),
            Some(v @ Value::Number(_)) => {
                let i = self.find_layer(v)?;
                if !self.app.doc.layers[i].is_foliage() {
                    return Err(format!("`layer` = {v} is not a foliage layer"));
                }
                Some(self.app.doc.layers[i].name.clone())
            }
            Some(v) => return Err(format!("`layer` must be a name or index, got {v}")),
        };
        let i = self.app.foliage_layer(name.as_deref(), true)?;
        if let Some(at) = s(a, "atlas") {
            let at = if at == "builtin" { at.to_string() } else { at.replace('\\', "/") };
            self.app.foliage_atlas(&at)?;
            let lname = self.app.doc.layers[i].name.clone();
            let set = self.app.doc.layers[i].foliage_mut().unwrap();
            if set.atlas != at && !set.instances.is_empty() {
                return Err(format!("layer `{lname}` already uses atlas `{}`; use another `layer` for cards from `{at}`", set.atlas));
            }
            if set.atlas != at {
                set.cells.clear();
            }
            set.atlas = at;
        }
        if let Some(w) = f(a, "wind") {
            self.app.doc.layers[i].foliage_mut().unwrap().wind = w.clamp(0.0, 1.0);
        }
        Ok(i)
    }

    fn filter_from(&self, a: &Value, default_facing: &str) -> Res<SurfaceFilter> {
        let facing = s(a, "facing").unwrap_or(default_facing);
        let mut up = SurfaceFilter::facing(facing).ok_or_else(|| format!("`facing` = \"{facing}\": one of up, walls, down, any"))?;
        if let Some(x) = f(a, "min_up") {
            up.0 = x;
        }
        if let Some(x) = f(a, "max_up") {
            up.1 = x;
        }
        let parts = match a.get("parts") {
            Some(Value::Array(p)) => Some(p.iter().map(|x| x.as_u64().map(|x| x as u32).ok_or("`parts` are part ids")).collect::<Result<Vec<_>, _>>()?),
            _ => None,
        };
        let region = match a.get("region") {
            Some(r) => Some((vec3(&r["min"]).ok_or("`region.min` = [x, y, z]")?, vec3(&r["max"]).ok_or("`region.max` = [x, y, z]")?)),
            None => None,
        };
        Ok(SurfaceFilter { parts, region, up })
    }

    /// Mask / AO acceptance for scatter and the brush, as owned data.
    fn acceptance(&mut self, a: &Value) -> Res<impl Fn(&SurfaceTri, Vec3, Vec3) -> f32 + use<>> {
        let mask: Option<MaskImage> = match a.get("mask") {
            None | Some(Value::Null) => None,
            Some(v @ (Value::String(_) | Value::Number(_))) => {
                let i = self.find_layer(v)?;
                let id = self.app.doc.layers[i].id;
                if self.app.doc.layers[i].mask.is_none() {
                    return Err(format!("`mask`: layer `{}` has no mask", self.app.doc.layers[i].name));
                }
                Some(self.app.mask_image(&self.rs, &MaskSource::Layer(id))?)
            }
            Some(m) => {
                let k = s(m, "generator").ok_or("`mask` object needs `generator` (or give a layer name)")?;
                let mut g = Generator::new(GeneratorKind::from_id(k).ok_or_else(|| unknown_generator("mask.generator", k))?);
                apply_generator_fields(&mut g, m);
                let res = self.app.doc.next_id + 1_000_000;
                self.app.ts.new_mask(&self.rs.device, &self.rs.queue, res, true);
                let mut mk = Mask::with_generator(res, g);
                mk.invert = m.get("invert").and_then(Value::as_bool).unwrap_or(false);
                if let Some(p) = m.get("parts").and_then(Value::as_array) {
                    mk.parts = p.iter().filter_map(Value::as_u64).map(|x| x as u32).collect();
                }
                let img = self.app.mask_image(&self.rs, &MaskSource::Mask(Box::new(mk)))?;
                self.app.ts.masks.remove(&res);
                Some(img)
            }
        };
        let thr = f(a, "mask_threshold").unwrap_or(0.5);
        let ao_range = match a.get("ao") {
            Some(v) => Some(pair(v, "ao")?),
            None => None,
        };
        let ao = ao_range.map(|_| self.app.ao_image(&self.rs));
        let uvs: Vec<[f32; 2]> = self.app.mesh.vertices.iter().map(|v| v.uv).collect();
        let idx = self.app.mesh.indices.clone();
        Ok(move |st: &SurfaceTri, bary: Vec3, _p: Vec3| {
            let t = &idx[st.tri * 3..st.tri * 3 + 3];
            let uv = [0, 1, 2].iter().fold([0.0f32; 2], |acc, &k| {
                let u = uvs[t[k] as usize];
                [acc[0] + u[0] * bary[k], acc[1] + u[1] * bary[k]]
            });
            let mut p = 1.0f32;
            if let Some(m) = &mask {
                let v = m.at(uv);
                p *= ((v - (thr - 0.15)) / 0.3).clamp(0.0, 1.0);
            }
            if let (Some(img), Some((lo, hi))) = (&ao, ao_range) {
                let v = img.at(uv);
                p *= if v >= lo && v <= hi { 1.0 } else { 0.0 };
            }
            p
        })
    }

    fn place_opts(a: &Value, defaults: (f32, f32)) -> Res<PlaceOpts> {
        let mut o = PlaceOpts::default();
        if let Some(v) = a.get("scale") {
            o.scale = pair(v, "scale")?;
        } else {
            o.scale = defaults;
        }
        if let Some(x) = f(a, "align") {
            o.align = x.clamp(0.0, 1.0);
        }
        if let Some(x) = f(a, "rotation_jitter") {
            o.rotation_jitter = x;
        }
        if let Some(m) = s(a, "mount") {
            o.mount = Some(Mount::from_id(m).ok_or_else(|| format!("`mount` = \"{m}\": one of upright, flat, wall, hanging"))?);
        }
        Ok(o)
    }

    fn summary(&self, i: usize) -> Value {
        let l = &self.app.doc.layers[i];
        let set = l.foliage().unwrap();
        let counts: serde_json::Map<String, Value> = set.cells.iter().zip(set.counts()).map(|(c, n)| (c.clone(), json!(n))).collect();
        json!({ "layer": l.name, "atlas": set.atlas, "cards": set.instances.len(), "by_cell": counts })
    }

    pub fn scatter_foliage(&mut self, a: &Value) -> Res<Value> {
        let i = self.foliage_target(a)?;
        let names = cell_list(a, &["grass"])?;
        let (cells, defs) = self.app.foliage_cells(i, &names)?;
        let filter = self.filter_from(a, "up")?;
        let count = match (a.get("count").and_then(Value::as_u64), f(a, "density")) {
            (Some(c), _) => c as usize,
            (None, Some(d)) => (pigment_core::foliage_set::surface_area(&self.app.mesh, &self.app.parts, &filter) * d).round() as usize,
            (None, None) => 200,
        };
        if count > 200_000 {
            return Err(format!("{count} cards is too many (max 200000): lower `count` / `density`"));
        }
        let accept = self.acceptance(a)?;
        let place = Self::place_opts(a, (0.8, 1.2))?;
        let min_spacing = f(a, "min_spacing").unwrap_or(0.0).max(0.0);
        let o = ScatterOpts { cells, defs: &defs, count, seed: a.get("seed").and_then(Value::as_u64).unwrap_or(1), filter, min_spacing, place };
        let existing = self.app.doc.layers[i].foliage().unwrap().instances.clone();
        let got = pigment_core::foliage_set::scatter(&self.app.mesh, &self.app.parts, &o, &existing, &accept);
        let n = got.len();
        self.app.doc.layers[i].foliage_mut().unwrap().instances.extend(got);
        self.settle();
        let mut r = self.summary(i);
        r["placed"] = json!(n);
        r["requested"] = json!(count);
        Ok(r)
    }

    /// Surface points from `world_points` ([[x,y,z], ...], snapped to the
    /// surface) or a camera stroke (`points` in 0..1 + camera args).
    fn stroke_hits(&mut self, a: &Value, spacing_m: f32) -> Res<Vec<(Vec3, Vec3)>> {
        let mut hits = vec![];
        if let Some(wp) = a.get("world_points").and_then(Value::as_array) {
            let grid = pigment_core::foliage_set::TriGrid::new(&self.app.mesh, &self.app.parts, &SurfaceFilter::default(), 0.25);
            for (k, p) in wp.iter().enumerate() {
                let p = vec3(p).ok_or_else(|| format!("`world_points[{k}]` must be [x, y, z]"))?;
                let (q, n) = grid.closest(p, 1.0).ok_or_else(|| format!("`world_points[{k}]` = {p} is not within 1 m of the surface"))?;
                hits.push((q, n));
            }
        } else {
            let pts: Vec<Vec2> = a
                .get("points")
                .and_then(Value::as_array)
                .ok_or("give `points` ([[x, y], ...] in 0..1 for a camera view) or `world_points` ([[x, y, z], ...])")?
                .iter()
                .filter_map(|p| Some(Vec2::new(p.get(0)?.as_f64()? as f32, p.get(1)?.as_f64()? as f32)))
                .collect();
            self.set_camera(a);
            let px = Vec2::new(self.size[0] as f32, self.size[1] as f32);
            let mut raw: Vec<(Vec3, Vec3)> = vec![];
            // resample the stroke in screen space, then keep hits spaced in metres
            for w in pts.windows(2).chain(if pts.len() == 1 { Some(&pts[..1]) } else { None }) {
                let (p0, p1) = (w[0] * px, w.get(1).copied().unwrap_or(w[0]) * px);
                let steps = ((p1 - p0).length() / 3.0).ceil().max(1.0) as usize;
                for k in 0..=steps {
                    if let Some((p, n, _)) = self.app.surface_at(p0.lerp(p1, k as f32 / steps as f32), px) {
                        raw.push((p, n));
                    }
                }
            }
            for h in raw {
                if hits.last().is_none_or(|l: &(Vec3, Vec3)| l.0.distance(h.0) >= spacing_m) {
                    hits.push(h);
                }
            }
        }
        if hits.is_empty() {
            return Err("the stroke missed the model (render the same view to check the points)".into());
        }
        Ok(hits)
    }

    pub fn paint_foliage(&mut self, a: &Value) -> Res<Value> {
        let i = self.foliage_target(a)?;
        let erase = a.get("erase").and_then(Value::as_bool).unwrap_or(false);
        let names = match (a.get("cells"), erase) {
            (None, true) => vec![],
            _ => cell_list(a, &["grass"])?,
        };
        let radius = f(a, "radius").unwrap_or(0.3).max(0.01);
        let b = FoliageBrush {
            cells: names.into_iter().map(|c| c.0).collect(),
            radius,
            density: f(a, "density").unwrap_or(40.0).max(0.01),
            scale: Self::place_opts(a, (0.8, 1.2))?.scale,
            align: f(a, "align").unwrap_or(0.6),
            facing: s(a, "facing").unwrap_or("any").into(),
            erase,
            seed: a.get("seed").and_then(Value::as_u64).unwrap_or(1),
        };
        let filter = self.filter_from(a, "any")?;
        let hits = self.stroke_hits(a, radius * 0.6)?;
        let accept = self.acceptance(a)?;
        let n = self.app.foliage_paint(i, &hits, &b, &accept, filter)?;
        self.settle();
        let mut r = self.summary(i);
        r[if erase { "removed" } else { "added" }] = json!(n);
        r["dabs"] = json!(hits.len());
        Ok(r)
    }

    pub fn grow_ivy(&mut self, a: &Value) -> Res<Value> {
        let i = self.foliage_target(a)?;
        let mut starts = vec![];
        if let Some(st) = a.get("start").and_then(Value::as_array) {
            for (k, p) in st.iter().enumerate() {
                let p = vec3(p).ok_or_else(|| format!("`start[{k}]` must be [x, y, z]"))?;
                starts.push((p, Vec3::ZERO));
            }
        } else {
            starts = self.stroke_hits(a, 0.3)?;
        }
        if starts.is_empty() {
            return Err("grow_ivy needs `start` ([[x, y, z], ...] world points) or a camera stroke `points`".into());
        }
        let d = IvyOpts::default();
        let o = IvyOpts {
            length: f(a, "length").unwrap_or(d.length).clamp(0.05, 50.0),
            step: f(a, "step").unwrap_or(d.step).clamp(0.005, 0.5),
            branching: f(a, "branching").unwrap_or(d.branching).max(0.0),
            max_strands: a.get("max_strands").and_then(Value::as_u64).map(|x| x as usize).unwrap_or(d.max_strands),
            up_bias: f(a, "up_bias").unwrap_or(d.up_bias),
            wander: f(a, "wander").unwrap_or(d.wander),
            leaf_spacing: f(a, "leaf_spacing").unwrap_or(d.leaf_spacing).max(0.005),
            leaf_scale: match a.get("leaf_scale") {
                Some(v) => pair(v, "leaf_scale")?,
                None => d.leaf_scale,
            },
            stem_width: f(a, "stem_width").unwrap_or(d.stem_width),
            seed: a.get("seed").and_then(Value::as_u64).unwrap_or(1),
        };
        let leaf = s(a, "leaf").unwrap_or("ivy_leaf").to_string();
        let stem = match a.get("stem") {
            Some(Value::Null) => None,
            Some(Value::String(x)) => Some(x.clone()),
            _ => Some("ivy_stem".to_string()),
        };
        let filter = self.filter_from(a, "any")?;
        let r = self.app.foliage_ivy(i, &starts, &leaf, stem.as_deref(), &o, &filter)?;
        self.settle();
        let mut out = self.summary(i);
        out["strands"] = json!(r.strands);
        out["stem_length_m"] = json!((r.length * 100.0).round() / 100.0);
        out["added"] = json!(r.instances.len());
        let top = r.instances.iter().map(|x| x.p[1]).fold(f32::MIN, f32::max);
        out["highest_y"] = json!(top);
        Ok(out)
    }

    pub fn export_foliage(&mut self, a: &Value) -> Res<Value> {
        self.settle();
        let dir = PathBuf::from(req(a, "dir")?);
        let name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        let only = match a.get("layer") {
            Some(v) => {
                let i = self.find_layer(v)?;
                if !self.app.doc.layers[i].is_foliage() {
                    return Err(format!("`layer` = {v} is not a foliage layer"));
                }
                Some(self.app.doc.layers[i].id)
            }
            None => None,
        };
        let (files, sets) = self.app.export_foliage_to(&dir, &name, only)?;
        Ok(json!({ "files": files, "sets": sets, "sidecar": dir.join(pigment_core::bridge::SIDECAR),
                   "godot": "load <name>_foliage_instances.json: one MultiMesh per group (transforms = Transform3D basis x, y, z + origin, unit card quad x -0.5..0.5, y 0..1), see game/scripts/foliage_loader.gd",
                   "blender": "import <name>_foliage.glb; the Pigment Bridge add-on / tools/blender_pigment.py apply_foliage_material wires BaseColorAlpha (alpha clip), Normal, Translucency" }))
    }

    /// Foliage summary for `list_library`.
    pub fn foliage_library(&self) -> Value {
        let builtin: Vec<String> = fol::builtin_cells().into_iter().map(|c| c.name).collect();
        json!({
            "presets": fol::PRESETS,
            "shapes": fol::LeafShape::ALL.map(|s| s.id()),
            "arrangements": fol::Arrangement::ALL.map(|s| s.id()),
            "mounts": Mount::ALL.map(|m| m.id()),
            "card_meshes": CardMesh::ALL.map(|m| m.id()),
            "builtin_cells": builtin,
            "bark_styles": fol::BarkStyle::ALL.map(|b| b.id()),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn session() -> Option<Session> {
        Session::new().ok()
    }

    /// Mean colour (rgb) and coverage of the opaque texels of atlas cell `cell`.
    fn cell_stats(s: &mut Session, cell: usize) -> [f32; 4] {
        s.settle();
        let m = crate::render::io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts);
        let uv = s.app.doc.tile.as_ref().unwrap().cells[cell].uv;
        let r = pigment_core::foliage::cell_rect(uv, m.size);
        let (mut acc, mut n) = ([0.0f32; 3], 0.0f32);
        for y in r[1]..r[3] {
            for x in r[0]..r[2] {
                let k = ((y * m.size + x) * 4) as usize;
                if m.color[k + 3] > 200 {
                    for c in 0..3 {
                        acc[c] += m.color[k + c] as f32;
                    }
                    n += 1.0;
                }
            }
        }
        let area = ((r[2] - r[0]) * (r[3] - r[1])) as f32;
        [acc[0] / n.max(1.0), acc[1] / n.max(1.0), acc[2] / n.max(1.0), n / area]
    }

    #[test]
    fn foliage_atlas_cells_generate_update_undo_and_export() {
        let _gpu = gpu_lock();
        let Some(mut s) = session() else { return };
        let r = s
            .new_project(&json!({ "resolution": 512, "foliage_atlas": { "name": "T", "cells": [
                { "name": "maple", "preset": "maple_leaf", "size_m": 0.1 },
                { "name": "grass", "preset": "grass" },
                { "name": "custom", "shape": "lanceolate", "arrangement": "twig", "count": 5, "serration": 0.6, "size_m": [0.2, 0.3] } ] } }))
            .unwrap();
        assert_eq!(r["cells"].as_array().unwrap().len(), 3);
        let out = std::env::temp_dir().join(format!("pigment-foliage-atlas-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&out);
        let green = cell_stats(&mut s, 0);
        assert!(green[1] > green[0] && green[3] > 0.1 && green[3] < 0.95, "maple is a green leaf shape: {green:?}");
        // autumn turns that cell red; undo brings it back
        s.update_foliage_cell(&json!({ "cell": "maple", "autumn": 1.0, "autumn_jitter": 0.0 })).unwrap();
        let red = cell_stats(&mut s, 0);
        assert!(red[0] > red[1] * 1.3, "autumn maple: {red:?}");
        s.undo(false).unwrap();
        let back = cell_stats(&mut s, 0);
        assert!((back[0] - green[0]).abs() < 2.0 && (back[1] - green[1]).abs() < 2.0, "undo restores the cell: {back:?} vs {green:?}");
        assert!(s.update_foliage_cell(&json!({ "cell": "nope", "autumn": 1.0 })).is_err());
        assert!(s.update_foliage_cell(&json!({ "cell": 0, "shape": "triangle" })).is_err());
        // export: translucency, thickness, godot backlight and the atlas json
        let r = s.export_textures(&json!({ "dir": out, "preset": "godot", "name": "T" })).unwrap();
        for f in ["T_BaseColorAlpha.png", "T_Translucency.png", "T_Thickness.png", "T_backlight.png", "T_foliage.json"] {
            assert!(out.join(f).exists(), "{f}: {r}");
        }
        let meta: Value = serde_json::from_str(&std::fs::read_to_string(out.join("T_foliage.json")).unwrap()).unwrap();
        assert_eq!(meta["cells"][2]["name"], "custom");
        // add a cell: repacked, the new cell gets drawn
        s.add_foliage_cell(&json!({ "name": "ivy", "preset": "ivy_leaf" })).unwrap();
        assert_eq!(s.app.doc.tile.as_ref().unwrap().cells.len(), 4);
        assert!(cell_stats(&mut s, 3)[3] > 0.1);
        // save + reopen keeps the generated pixels without redrawing
        let proj = out.join("t.pigment");
        s.save_project(&json!({ "path": proj })).unwrap();
        s.open_project(&json!({ "path": proj })).unwrap();
        assert_eq!(s.app.foliage.generated.len(), 1);
        assert!(cell_stats(&mut s, 3)[3] > 0.1);
        // bark needs a tile project
        assert!(s.add_bark(&json!({ "style": "plated" })).is_err());
        s.new_project(&json!({ "resolution": 512, "tile": { "size_m": [1, 1] } })).unwrap();
        s.add_bark(&json!({ "style": "plated", "seed": 3 })).unwrap();
        s.settle();
        let m = crate::render::io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts);
        let spread = m.height.iter().map(|v| *v as i64).max().unwrap() - m.height.iter().map(|v| *v as i64).min().unwrap();
        assert!(spread > 4000, "bark has relief: {spread}");
        let _ = std::fs::remove_dir_all(&out);
    }

    #[test]
    fn foliage_layers_scatter_paint_ivy_undo_save_and_export() {
        let _gpu = gpu_lock();
        let Some(mut s) = session() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/town/building_a.glb"), "resolution": 512 })).unwrap();
        // grass only on up-facing surfaces
        let r = s.scatter_foliage(&json!({ "cells": ["grass"], "count": 200, "facing": "up", "seed": 1 })).unwrap();
        assert_eq!(r["placed"], 200, "{r}");
        let li = s.app.doc.layers.iter().position(|l| l.is_foliage()).unwrap();
        assert!(s.app.doc.layers[li].foliage().unwrap().instances.iter().all(|i| i.y[1] > 0.0), "grass stands up");
        // a layer's generator mask limits where moss goes
        s.add_layer(&json!({ "name": "Moss", "values": { "base_color": [0.2, 0.3, 0.1] }, "mask": { "generator": "moss", "amount": 0.3 } })).unwrap();
        let mossy = s.scatter_foliage(&json!({ "cells": ["moss"], "count": 100, "facing": "any", "mask": "Moss", "seed": 2, "layer": "Mossy" })).unwrap();
        assert!(mossy["placed"].as_u64().unwrap() > 20, "{mossy}");
        let mi = s.app.doc.layers.iter().position(|l| l.name == "Mossy").unwrap();
        let ups: Vec<f32> = s.app.doc.layers[mi].foliage().unwrap().instances.iter().map(|i| i.y[1] / i.y[0].hypot(i.y[1]).hypot(i.y[2])).collect();
        // the moss generator grows on ledges: masked moss stands mostly upright
        assert!(ups.iter().filter(|u| **u > 0.5).count() as f32 > ups.len() as f32 * 0.8, "{ups:?}");
        // inline generator mask + AO crevices
        s.scatter_foliage(&json!({ "cells": ["weed"], "count": 30, "mask": { "generator": "moss", "amount": 0.4 }, "ao": [0, 0.9], "seed": 5, "layer": "Weeds" })).unwrap();
        // a camera brush stroke, then erase it; each is one undo step
        let li = s.app.doc.layers.iter().position(|l| l.is_foliage() && l.name == "Foliage").unwrap();
        let before = s.app.doc.layers[li].foliage().unwrap().instances.len();
        let p = s.paint_foliage(&json!({ "points": [[0.4, 0.5], [0.6, 0.5]], "yaw": 90, "pitch": 5, "zoom": 2, "cells": ["ivy_leaf"], "radius": 0.5, "density": 30, "layer": "Foliage" })).unwrap();
        let added = p["added"].as_u64().unwrap() as usize;
        assert!(added > 10, "{p}");
        assert_eq!(s.app.doc.layers[li].foliage().unwrap().instances.len(), before + added);
        s.undo(false).unwrap();
        assert_eq!(s.app.doc.layers[li].foliage().unwrap().instances.len(), before);
        s.undo(true).unwrap();
        let e = s.paint_foliage(&json!({ "points": [[0.4, 0.5], [0.6, 0.5]], "yaw": 90, "pitch": 5, "zoom": 2, "erase": true, "radius": 0.6, "cells": ["ivy_leaf"], "layer": "Foliage" })).unwrap();
        assert!(e["removed"].as_u64().unwrap() as usize >= added * 9 / 10, "{e}");
        // ivy climbs the +X wall
        let ivy = s.grow_ivy(&json!({ "start": [[4.4, 0.2, 0.5]], "length": 3, "seed": 2, "layer": "Ivy" })).unwrap();
        assert!(ivy["highest_y"].as_f64().unwrap() > 1.5, "{ivy}");
        assert!(ivy["strands"].as_u64().unwrap() > 1);
        // the viewport draws the cards
        s.settle();
        assert!(s.app.viewport.foliage.card_count() > 300);
        // save / reopen keeps the layers
        let out = std::env::temp_dir().join(format!("pigment-foliage-layers-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&out);
        let n_all: usize = s.app.doc.layers.iter().filter_map(|l| l.foliage()).map(|f| f.instances.len()).sum();
        s.save_project(&json!({ "path": out.join("b.pigment") })).unwrap();
        s.open_project(&json!({ "path": out.join("b.pigment") })).unwrap();
        let n_back: usize = s.app.doc.layers.iter().filter_map(|l| l.foliage()).map(|f| f.instances.len()).sum();
        assert_eq!(n_all, n_back);
        // export: glb + instances + maps + sidecar
        let x = s.export_foliage(&json!({ "dir": out.join("exp"), "name": "b" })).unwrap();
        for f in ["b_foliage.glb", "b_foliage_instances.json", "b_foliage_BaseColorAlpha.png", "b_foliage_Translucency.png", "material.json"] {
            assert!(out.join("exp").join(f).exists(), "{f}: {x}");
        }
        let inst: Value = serde_json::from_str(&std::fs::read_to_string(out.join("exp/b_foliage_instances.json")).unwrap()).unwrap();
        let total: u64 = inst["groups"].as_array().unwrap().iter().map(|g| g["count"].as_u64().unwrap()).sum();
        assert_eq!(total as usize, n_back);
        let glb = pigment_core::Mesh::load(&out.join("exp/b_foliage.glb")).unwrap();
        assert!(glb.triangle_count() >= n_back * 2);
        let side: Value = serde_json::from_str(&std::fs::read_to_string(out.join("exp/material.json")).unwrap()).unwrap();
        assert_eq!(side["materials"]["b_foliage"]["kind"], "foliage");
        // bad args name the problem
        assert!(s.scatter_foliage(&json!({ "cells": ["nope"] })).unwrap_err().contains("nope"));
        assert!(s.scatter_foliage(&json!({ "facing": "sideways" })).is_err());
        let _ = std::fs::remove_dir_all(&out);
    }
}
