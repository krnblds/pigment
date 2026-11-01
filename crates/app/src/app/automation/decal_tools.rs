//! MCP decal tools: `project_decal` with a precise anchor (part + face +
//! u/v, or a world position + normal) and `scatter_decals`.

use super::super::decals::{BoxDecal, DecalLook};
use super::*;
use glam::Vec3;
use pigment_core::decal::{face_point, raycast_parts, scatter, Face, Placement, Rng, Scatter};
use pigment_core::variants::DecalRecord;

fn vec3(a: &Value, k: &str) -> Res<Option<Vec3>> {
    match a.get(k) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => {
            let n: Vec<f32> = v.as_array().ok_or_else(|| format!("`{k}` must be [x, y, z]"))?.iter().filter_map(|x| x.as_f64().map(|x| x as f32)).collect();
            if n.len() != 3 {
                return Err(format!("`{k}` must be [x, y, z]"));
            }
            Ok(Some(Vec3::new(n[0], n[1], n[2])))
        }
    }
}

/// A number or a [lo, hi] pair.
fn range(a: &Value, k: &str) -> Res<Option<(f32, f32)>> {
    match a.get(k) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) => {
            let x = n.as_f64().unwrap_or(0.0) as f32;
            Ok(Some((x, x)))
        }
        Some(Value::Array(v)) if v.len() == 2 => {
            let (lo, hi) = (v[0].as_f64().unwrap_or(0.0) as f32, v[1].as_f64().unwrap_or(0.0) as f32);
            Ok(Some((lo.min(hi), lo.max(hi))))
        }
        _ => Err(format!("`{k}` must be a number or [min, max]")),
    }
}

fn parts_arg(a: &Value, k: &str) -> Option<Vec<u32>> {
    a.get(k).and_then(Value::as_array).map(|v| v.iter().filter_map(|p| p.as_u64().map(|x| x as u32)).collect())
}

fn aspect(image: &Path) -> Res<f32> {
    let (w, h) = image::image_dimensions(image).map_err(|e| format!("couldn't read {}: {e}", image.display()))?;
    Ok(w as f32 / h.max(1) as f32)
}

/// Decal size in metres: `size` = width (height from the image aspect) or [w, h].
fn decal_size(a: &Value, image: &Path) -> Res<glam::Vec2> {
    match a.get("size") {
        Some(Value::Array(v)) if v.len() == 2 => Ok(glam::Vec2::new(v[0].as_f64().unwrap_or(0.5) as f32, v[1].as_f64().unwrap_or(0.5) as f32)),
        Some(Value::Number(n)) => {
            let w = n.as_f64().unwrap_or(0.5) as f32;
            Ok(glam::Vec2::new(w, w / aspect(image)?))
        }
        None => Ok(glam::Vec2::new(0.5, 0.5 / aspect(image)?)),
        _ => Err("`size` must be a width in metres or [width, height]".into()),
    }
}

impl Session {
    /// Weathering and opacity from the arguments.
    fn decal_look(a: &Value) -> Res<DecalLook> {
        let d = DecalLook::default();
        let grunge = match s(a, "wear_style") {
            None | Some("noise") => false,
            Some("grunge") => true,
            Some(o) => return Err(format!("`wear_style` must be \"noise\" or \"grunge\", not `{o}`")),
        };
        Ok(DecalLook {
            opacity: f(a, "opacity").unwrap_or(d.opacity),
            luminance_alpha: a.get("alpha_from_luminance").and_then(Value::as_bool).unwrap_or(false),
            tear: f(a, "wear").unwrap_or(0.0),
            fade: f(a, "fade").unwrap_or(0.0),
            wear_scale: f(a, "wear_scale").unwrap_or(d.wear_scale),
            seed: f(a, "wear_seed").unwrap_or(0.0),
            grunge,
            paper_rim: f(a, "paper_rim").unwrap_or(d.paper_rim),
            min_facing: d.min_facing,
        })
    }

    /// Target layer: `layer`, else the `Decals <overlap_order>` paint layer
    /// (created and slotted among the other `Decals N` layers so higher
    /// orders sit on top), else the top paint layer.
    fn decal_layer(&mut self, a: &Value) -> Res<usize> {
        if let Some(r) = a.get("layer") {
            return self.find_layer(r);
        }
        if let Some(order) = a.get("overlap_order").and_then(Value::as_i64) {
            let name = format!("Decals {order}");
            if let Some(i) = self.app.doc.layers.iter().position(|l| l.name == name) {
                return Ok(i);
            }
            let ranked: Vec<(usize, i64)> = self
                .app
                .doc
                .layers
                .iter()
                .enumerate()
                .filter_map(|(i, l)| l.name.strip_prefix("Decals ").and_then(|k| k.parse::<i64>().ok()).filter(|_| l.is_paint()).map(|k| (i, k)))
                .collect();
            let at = match ranked.iter().filter(|(_, k)| *k > order).map(|(i, _)| *i).min() {
                Some(i) => i,
                None => ranked.iter().filter(|(_, k)| *k < order).map(|(i, _)| i + 1).max().unwrap_or(self.app.doc.layers.len()),
            };
            let l = self.app.doc.new_paint_layer(&name);
            self.app.doc.layers.insert(at, l);
            self.settle();
            return Ok(at);
        }
        Ok(match self.app.doc.layers.iter().rposition(|l| l.is_paint()) {
            Some(i) => i,
            None => {
                let l = self.app.doc.new_paint_layer("Decals");
                self.app.doc.layers.push(l);
                self.app.doc.layers.len() - 1
            }
        })
    }

    /// Select the decal layer and set the brush values (tint, material,
    /// emission, height, channels) the decal paints with.
    fn decal_brush(&mut self, a: &Value, i: usize) -> Res<()> {
        let id = self.app.doc.layers[i].id;
        self.app.select(Some(id), a.get("mask").and_then(Value::as_bool).unwrap_or(false));
        // no commit here: decal records go into the same undo step as the pixels
        self.app.ensure_composited(&self.rs);
        let b = &mut self.app.brush;
        b.values = match s(a, "material") {
            Some(m) if !material_presets().iter().any(|(n, _)| *n == m) => return Err(unknown_material("material", m)),
            Some(m) => material_preset(m),
            None => MaterialValues { base_color: [1.0; 3], roughness: 0.55, ..Default::default() },
        };
        if let Some(t) = a.get("tint").and_then(Value::as_array) {
            for (k, x) in t.iter().take(3).enumerate() {
                b.values.base_color[k] = x.as_f64().unwrap_or(1.0) as f32;
            }
        }
        b.channels = [true, true, true, false, false, false, false, false, false, false, false];
        if let Some(e) = f(a, "emissive_strength") {
            b.values.emissive = b.values.base_color;
            b.values.emissive_strength = e;
            b.channels[5] = e > 0.0;
        }
        if let Some(h) = f(a, "height") {
            b.values.height = h;
            b.channels[3] = true;
        }
        if let Some(vals) = a.get("values") {
            apply_material_values(&mut b.values, vals);
            b.channels[6] |= vals.get("opacity").is_some();
            b.channels[7] |= vals.get("transmission").is_some();
            b.channels[8] |= vals.get("coat").is_some();
            b.channels[9] |= vals.get("coat").is_some() || vals.get("coat_roughness").is_some();
            b.channels[10] |= vals.get("flake").is_some();
        }
        if let Some(chs) = a.get("channels").and_then(Value::as_array) {
            b.channels = [false; 11];
            for c in chs.iter().filter_map(Value::as_str) {
                b.channels[channel(c)?.index()] = true;
            }
        }
        b.opacity = 1.0;
        b.erase = false;
        b.mask_white = s(a, "mask_value").unwrap_or("white") != "black";
        Ok(())
    }

    /// Where an anchored decal goes: (centre on the surface, outward normal).
    fn anchor_point(&self, a: &Value) -> Res<(Vec3, Vec3)> {
        let mesh = &self.app.mesh;
        let tri_part = &self.app.parts.triangle_part;
        if let Some(pos) = vec3(a, "position")? {
            let n = vec3(a, "normal")?.ok_or("`position` needs a `normal` (the outward direction of the surface there)")?.try_normalize().ok_or("`normal` is zero")?;
            // snap onto the surface along the normal (within 0.5 m)
            return Ok(match raycast_parts(mesh, tri_part, None, pos + n * 0.5, -n) {
                Some((_, d, hn)) if d < 1.0 => (pos + n * 0.5 - n * d, if hn.dot(n) > 0.5 { hn } else { n }),
                _ => (pos, n),
            });
        }
        let uv: Vec<f32> = a.get("anchor").and_then(Value::as_array).ok_or("missing `anchor` [u, v]")?.iter().filter_map(|x| x.as_f64().map(|x| x as f32)).collect();
        if uv.len() != 2 {
            return Err("`anchor` must be [u, v] in 0..1 across the face ((0,0) = top-left seen from outside)".into());
        }
        let part = a.get("part").and_then(Value::as_u64).map(|p| p as u32);
        let (lo, hi) = match part {
            Some(p) => {
                let info = self.app.parts.info.get(p as usize).ok_or_else(|| format!("no part {p}"))?;
                (Vec3::from(info.min), Vec3::from(info.max))
            }
            None => mesh.bounds(),
        };
        let face_name = s(a, "face").unwrap_or("auto");
        let face = Face::parse(face_name).ok_or_else(|| format!("unknown face `{face_name}` (front, back, left, right, top, bottom, auto)"))?;
        let (mc, _) = mesh.bounding_sphere();
        let n = face.normal(lo, hi, mc);
        let (pt, _) = face_point(lo, hi, n, glam::Vec2::new(uv[0], uv[1]));
        let only = part.map(|p| vec![p]);
        let reach = (hi - lo).length() + 0.1;
        match raycast_parts(mesh, tri_part, only.as_deref(), pt + n * 0.05, -n) {
            Some((_, d, hn)) if d <= reach => Ok((pt + n * 0.05 - n * d, if hn.dot(n) > 0.5 { hn } else { n })),
            _ => Err(format!("anchor {uv:?} on the {face_name} face misses the surface{} (try another face or anchor)", part.map(|p| format!(" of part {p}")).unwrap_or_default())),
        }
    }

    /// Add how many texels the smallest decal gets across, and a warning
    /// when the mesh's UVs give it too few to read.
    fn texel_report(&self, pls: &[Placement], out: &mut Value) {
        let res = self.app.ts.res as f32;
        let min = pls.iter().filter_map(|p| p.uv_size(&self.app.mesh)).map(|s| s.min_element() * res).fold(f32::MAX, f32::min);
        if min == f32::MAX {
            return;
        }
        out["texels_across"] = json!(min.round());
        if min < 96.0 {
            out["warning"] = json!(format!(
                "only ~{} texels across the decal at {}px: the mesh's UVs give this surface little texture space, so fine print will blur (use a higher resolution, larger decals or a mesh with denser UVs)",
                min.round(),
                res
            ));
        }
    }

    /// Record decals on paint layer `i` for export_variants (enable / disable
    /// by name or group, image swaps, replay). `args` are replayable
    /// `project_decal` arguments. Returns how many were pushed (to pop on error).
    fn record_decals(&mut self, i: usize, a: &Value, records: Vec<(String, Value)>) -> Res<usize> {
        let on_mask = a.get("mask").and_then(Value::as_bool).unwrap_or(false);
        let enabled = a.get("enabled").and_then(Value::as_bool).unwrap_or(true);
        if on_mask || !self.app.doc.layers[i].is_paint() {
            if !enabled || a.get("variant").is_some() {
                return Err("only decals on a paint layer (not its mask) can be tagged or disabled for variants".into());
            }
            return Ok(0);
        }
        let group = s(a, "variant").unwrap_or("").to_string();
        let n = records.len();
        for (stem, mut args) in records {
            if let Some(o) = args.as_object_mut() {
                for k in ["layer", "name", "variant", "enabled"] {
                    o.remove(k);
                }
            }
            let name = s(a, "name").map(String::from).unwrap_or(stem);
            self.app.doc.layers[i].variant.decals.push(DecalRecord { name, group: group.clone(), enabled, args });
        }
        Ok(n)
    }

    fn unrecord_decals(&mut self, i: usize, n: usize) {
        let d = &mut self.app.doc.layers[i].variant.decals;
        d.truncate(d.len().saturating_sub(n));
    }

    /// `project_decal` with `anchor` or `position`: one decal at an exact spot.
    /// `replay` (variant export): no record, no undo step.
    pub fn place_decal(&mut self, a: &Value, replay: bool) -> Res<Value> {
        let image = PathBuf::from(req(a, "image")?);
        let size = decal_size(a, &image)?;
        let (center, normal) = self.anchor_point(a)?;
        let depth = f(a, "depth").unwrap_or_else(|| Placement::default_depth(size));
        let placement = Placement::new(center, normal, size, f(a, "rotation").unwrap_or(0.0), depth);
        let look = Self::decal_look(a)?;
        let i = self.decal_layer(a)?;
        let name = image.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        let recorded = if replay { 0 } else { self.record_decals(i, a, vec![(name.clone(), a.clone())])? };
        if !replay && !a.get("enabled").and_then(Value::as_bool).unwrap_or(true) {
            // recorded for variants only
            self.settle();
            return Ok(json!({ "decal": image, "on": self.app.doc.layers[i].name, "painted": false }));
        }
        let painted = self.decal_brush(a, i).and_then(|_| self.app.project_box_decals(&self.rs, &[BoxDecal { image: image.clone(), placement, look }], format!("Decal {name}"), !replay));
        let n = match painted {
            Ok(n) => n,
            Err(e) => {
                self.unrecord_decals(i, recorded);
                return Err(e);
            }
        };
        if n == 0 {
            self.unrecord_decals(i, recorded);
            return Err("the decal touches no surface (check anchor / position and normal)".into());
        }
        if !replay {
            self.settle();
        }
        let mut out = json!({ "decal": image, "on": self.app.doc.layers[i].name, "center": center.to_array(), "normal": placement.normal.to_array(), "size": size.to_array() });
        self.texel_report(&[placement], &mut out);
        Ok(out)
    }

    /// `project_decal` arguments that reproduce one scattered decal exactly
    /// (position, normal, size, rotation, depth and its jittered wear).
    fn scatter_record(a: &Value, d: &BoxDecal) -> Value {
        let p = &d.placement;
        // rotation: angle from the unrotated frame to this one, about the normal
        let p0 = Placement::new(p.center, p.normal, p.size, 0.0, p.depth);
        let ang = p0.right.cross(p.right).dot(p.normal).atan2(p0.right.dot(p.right)).to_degrees();
        let rot = [ang, -ang].into_iter().min_by(|x, y| {
            let e = |r: f32| (Placement::new(p.center, p.normal, p.size, r, p.depth).right - p.right).length();
            e(*x).total_cmp(&e(*y))
        });
        let l = &d.look;
        let mut r = json!({
            "image": d.image, "position": p.center.to_array(), "normal": p.normal.to_array(), "size": p.size.to_array(),
            "rotation": rot.unwrap_or(0.0), "depth": p.depth,
            "wear": l.tear, "fade": l.fade, "wear_scale": l.wear_scale, "wear_seed": l.seed, "paper_rim": l.paper_rim,
            "opacity": l.opacity, "alpha_from_luminance": l.luminance_alpha,
        });
        if l.grunge {
            r["wear_style"] = json!("grunge");
        }
        for k in ["tint", "material", "emissive_strength", "values", "channels", "overlap_order"] {
            if let Some(v) = a.get(k) {
                r[k] = v.clone();
            }
        }
        r
    }

    /// Scatter images over a set of parts / a region, with height, size,
    /// rotation, spacing and facing constraints, and per-decal wear.
    pub fn scatter_decals(&mut self, a: &Value) -> Res<Value> {
        let images: Vec<PathBuf> = a.get("images").and_then(Value::as_array).ok_or("missing `images` (array of PNG paths)")?.iter().filter_map(|v| v.as_str().map(PathBuf::from)).collect();
        if images.is_empty() {
            return Err("`images` is empty".into());
        }
        let aspects = images.iter().map(|p| aspect(p)).collect::<Res<Vec<f32>>>()?;
        let mut parts = parts_arg(a, "parts");
        if let Some(m) = a.get("mask") {
            // a layer whose part mask says where decals may go
            let li = self.find_layer(m)?;
            let mp = self.app.doc.layers[li].mask.as_ref().map(|m| m.parts.clone()).unwrap_or_default();
            if mp.is_empty() {
                return Err(format!("layer `{}` has no part mask to scatter over", self.app.doc.layers[li].name));
            }
            parts = Some(match parts {
                Some(p) => p.into_iter().filter(|x| mp.contains(x)).collect(),
                None => mp,
            });
        }
        let region = match a.get("region") {
            Some(r) => Some((vec3(r, "min")?.ok_or("`region` needs `min` [x,y,z]")?, vec3(r, "max")?.ok_or("`region` needs `max` [x,y,z]")?)),
            None => None,
        };
        let size = range(a, "size")?.unwrap_or((0.4, 0.6));
        let facing = s(a, "facing").unwrap_or("horizontal");
        let max_tilt = match facing {
            "horizontal" | "walls" => Some(f(a, "max_tilt").unwrap_or(20.0)),
            "any" => None,
            o => return Err(format!("`facing` must be \"horizontal\" or \"any\", not `{o}`")),
        };
        let p = Scatter {
            count: a.get("count").and_then(Value::as_u64).unwrap_or(6).min(500) as usize,
            seed: a.get("seed").and_then(Value::as_u64).unwrap_or(0),
            parts,
            region,
            height: range(a, "height")?,
            ground: f(a, "ground").unwrap_or_else(|| self.app.mesh.bounds().0.y),
            size,
            rotation: f(a, "rotation").unwrap_or(0.0),
            rotation_jitter: f(a, "rotation_jitter").unwrap_or(6.0),
            min_spacing: f(a, "min_spacing").unwrap_or(size.1 * 0.9),
            max_tilt,
            fit: a.get("fit").and_then(Value::as_bool).unwrap_or(true),
            aspects,
            depth: f(a, "depth"),
        };
        let placed = scatter(&self.app.mesh, &self.app.parts, &p);
        if placed.is_empty() {
            return Err("no spot met the constraints (loosen height / size / spacing / facing, or check parts)".into());
        }
        // per-decal wear: the base amounts +- jitter, each with its own noise
        let base = Self::decal_look(a)?;
        let jitter = f(a, "wear_jitter").unwrap_or(0.15);
        let mut rng = Rng::new(p.seed.wrapping_mul(31).wrapping_add(17));
        let decals: Vec<BoxDecal> = placed
            .iter()
            .map(|d| {
                let mut look = base;
                if look.tear > 0.0 {
                    look.tear = (look.tear + rng.range(-jitter, jitter)).clamp(0.0, 1.0);
                }
                if look.fade > 0.0 {
                    look.fade = (look.fade + rng.range(-jitter, jitter)).clamp(0.0, 1.0);
                }
                look.seed = base.seed + rng.range(0.0, 100.0);
                BoxDecal { image: images[d.image].clone(), placement: d.placement, look }
            })
            .collect();
        let i = self.decal_layer(a)?;
        // each placed decal is recorded as a replayable anchored project_decal
        let records: Vec<(String, Value)> = decals.iter().map(|d| (d.image.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default(), Self::scatter_record(a, d))).collect();
        let recorded = self.record_decals(i, a, records)?;
        if !a.get("enabled").and_then(Value::as_bool).unwrap_or(true) {
            // recorded for variants only: they paint when a variant enables them
            self.settle();
            return Ok(json!({ "placed": 0, "recorded": recorded, "requested": p.count, "on": self.app.doc.layers[i].name, "painted": false }));
        }
        // `height` here is the placement band, not a paint height
        let mut brush_args = a.clone();
        if let Some(o) = brush_args.as_object_mut() {
            o.remove("height");
        }
        let painted = self.decal_brush(&brush_args, i).and_then(|_| self.app.project_box_decals(&self.rs, &decals, format!("Scatter {} decals", decals.len()), true));
        let n = match painted {
            Ok(n) => n,
            Err(e) => {
                self.unrecord_decals(i, recorded);
                return Err(e);
            }
        };
        self.settle();
        let list: Vec<Value> = decals
            .iter()
            .map(|d| json!({ "image": d.image, "center": d.placement.center.to_array(), "normal": d.placement.normal.to_array(), "size": d.placement.size.to_array(), "wear": d.look.tear, "fade": d.look.fade }))
            .collect();
        let mut out = json!({ "placed": n, "requested": p.count, "on": self.app.doc.layers[i].name, "decals": list });
        let pls: Vec<Placement> = decals.iter().map(|d| d.placement).collect();
        self.texel_report(&pls, &mut out);
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
    }

    /// Lit pixels in an emission close-up of the east wall's street level.
    fn glow(s: &mut Session) -> usize {
        let img = s.render(&json!({ "view": "emission", "yaw": 90, "pitch": 0, "target": [4.0, 1.75, 0.0], "distance": 9.0, "width": 320, "height": 200 })).unwrap();
        image::load_from_memory(&img.png).unwrap().to_luma8().pixels().filter(|p| p.0[0] > 60).count()
    }

    fn building(s: &mut Session) {
        s.new_project(&json!({ "mesh": root().join("assets/town/building_a.glb"), "resolution": 1024, "material": "Matte black" })).unwrap();
    }

    #[test]
    fn anchored_decal_lands_on_the_chosen_face_and_undoes() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        building(&mut s);
        // the grey environment counts too: measure against the bare wall
        let base = glow(&mut s);
        let poster = root().join("assets/decals/story/poster_unplug.png");
        // the body's right (+X) face, middle, 1.75 m up (v from the top of a 21 m face)
        let d = s
            .project_decal(&json!({ "image": poster, "part": 1, "face": "right", "anchor": [0.5, 1.0 - 1.75 / 21.0], "size": 1.0, "rotation": 10, "emissive_strength": 3.0 }))
            .unwrap();
        let c = &d["center"];
        assert!((c[0].as_f64().unwrap() - 4.0).abs() < 0.05 && (c[1].as_f64().unwrap() - 1.75).abs() < 0.05, "{d}");
        assert!(d["normal"][0].as_f64().unwrap() > 0.99, "{d}");
        assert!(d["texels_across"].as_f64().unwrap() > 5.0, "{d}");
        let lit = glow(&mut s).saturating_sub(base);
        assert!(lit > 150, "decal glows on the wall ({lit} px)");
        s.undo(false).unwrap();
        assert!(glow(&mut s).saturating_sub(base) < lit / 10, "undo removes it");
        // a world position + normal does the same; a bad face is an error, not a silent no-op
        s.project_decal(&json!({ "image": poster, "position": [4.2, 1.5, -2.0], "normal": [1, 0, 0], "size": 0.8, "emissive_strength": 3.0 })).unwrap();
        assert!(glow(&mut s).saturating_sub(base) > 100);
        assert!(s.project_decal(&json!({ "image": poster, "part": 1, "face": "nowhere", "anchor": [0.5, 0.5] })).is_err());
    }

    #[test]
    fn scatter_obeys_constraints_layers_by_overlap_order_and_undoes_in_one_step() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        building(&mut s);
        let st = root().join("assets/decals/story");
        // graffiti first, on top (order 1); the posters' layer (order 0) must still go under it
        s.project_decal(&json!({ "image": st.join("graffiti_lying.png"), "position": [4.2, 1.6, 3.0], "normal": [1, 0, 0], "size": 2.0, "overlap_order": 1, "fade": 0.3, "wear_style": "grunge" }))
            .unwrap();
        let before = glow(&mut s);
        let r = s
            .scatter_decals(&json!({
                "images": [st.join("poster_missing_aiko.png"), st.join("poster_unplug.png")],
                "count": 5, "seed": 11, "parts": [1], "region": { "min": [3.8, 0, -5.5], "max": [4.6, 5, 5.5] },
                "height": [0.5, 3.0], "size": [0.6, 0.8], "min_spacing": 1.0, "wear": 0.3, "fade": 0.2,
                "overlap_order": 0, "emissive_strength": 3.0 }))
            .unwrap();
        assert_eq!(r["placed"], 5, "{r}");
        for d in r["decals"].as_array().unwrap() {
            let (c, sz) = (&d["center"], &d["size"]);
            let (y, h) = (c[1].as_f64().unwrap(), sz[1].as_f64().unwrap());
            assert!((c[0].as_f64().unwrap() - 4.0).abs() < 0.05, "on the east wall: {d}");
            assert!(y - h / 2.0 >= 0.45 && y + h / 2.0 <= 3.05, "street level: {d}");
        }
        let layers: Vec<String> = s.app.doc.layers.iter().map(|l| l.name.clone()).collect();
        let (p0, p1) = (layers.iter().position(|n| n == "Decals 0").unwrap(), layers.iter().position(|n| n == "Decals 1").unwrap());
        assert!(p0 < p1, "posters below graffiti: {layers:?}");
        let after = glow(&mut s);
        assert!(after > before + 300, "posters glow ({before} -> {after})");
        let li = s.app.doc.layers.iter().position(|l| l.name == "Decals 0").unwrap();
        assert_eq!(s.app.doc.layers[li].variant.decals.len(), 5, "scattered decals are recorded for variants");
        // one undo removes the whole scatter and its records (the next one would remove the layer)
        s.undo(false).unwrap();
        assert!(s.app.doc.layers[li].variant.decals.is_empty(), "the records go with the pixels");
        let undone = glow(&mut s);
        assert!(undone.abs_diff(before) < 40, "one undo, all five gone ({before} vs {undone})");
        s.undo(true).unwrap();
        assert!(glow(&mut s).abs_diff(after) < 40, "redo brings them back");
        assert_eq!(s.app.doc.layers[li].variant.decals.len(), 5);
    }

    #[test]
    fn wear_tears_and_fades_the_decal() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        building(&mut s);
        let base = glow(&mut s);
        let poster = root().join("assets/decals/story/poster_missing_ren.png");
        let place = |s: &mut Session, extra: Value| {
            let mut a = json!({ "image": poster, "position": [4.2, 1.6, 0.0], "normal": [1, 0, 0], "size": 1.4, "emissive_strength": 3.0, "paper_rim": 0 });
            for (k, v) in extra.as_object().unwrap() {
                a[k] = v.clone();
            }
            s.project_decal(&a).unwrap();
            let n = glow(s).saturating_sub(base);
            s.undo(false).unwrap();
            n
        };
        let fresh = place(&mut s, json!({}));
        let torn = place(&mut s, json!({ "wear": 0.6 }));
        let grunge = place(&mut s, json!({ "wear": 0.6, "wear_style": "grunge" }));
        assert!(fresh > 500, "{fresh}");
        assert!(torn < fresh * 9 / 10 && torn > fresh / 5, "torn, not gone: {torn} of {fresh}");
        assert!(grunge < fresh * 9 / 10, "grunge tears too: {grunge} of {fresh}");
        assert_eq!(place(&mut s, json!({ "wear": 0.6 })), torn, "same seed, same tears");
        assert!(s.project_decal(&json!({ "image": poster, "position": [4.2, 1.6, 0.0], "normal": [1, 0, 0], "wear_style": "bogus" })).is_err());
    }

    /// Anchored and scattered decals are recorded for export_variants: a
    /// variant can switch them off by group, and a replayed layer (here: an
    /// swap that changes nothing visible) reproduces the authored pixels.
    #[test]
    fn anchored_and_scattered_decals_work_with_variants() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        building(&mut s);
        let st = root().join("assets/decals/story");
        let r = s
            .scatter_decals(&json!({
                "images": [st.join("poster_missing_aiko.png"), st.join("poster_unplug.png")],
                "count": 4, "seed": 5, "parts": [1], "region": { "min": [3.8, 0, -5.5], "max": [4.6, 5, 5.5] },
                "height": [0.5, 3.0], "size": [0.6, 0.8], "rotation_jitter": 8, "wear": 0.3, "fade": 0.2,
                "overlap_order": 0, "emissive_strength": 3.0, "variant": "posters" }))
            .unwrap();
        assert_eq!(r["placed"], 4, "{r}");
        let graffiti = st.join("graffiti_lying.png");
        s.project_decal(&json!({ "image": graffiti, "position": [4.2, 1.6, 3.0], "normal": [1, 0, 0], "size": 1.5, "rotation": 7, "overlap_order": 0, "emissive_strength": 3.0, "name": "lying" }))
            .unwrap();
        let li = s.app.doc.layers.iter().position(|l| l.name == "Decals 0").unwrap();
        let recs = &s.app.doc.layers[li].variant.decals;
        assert_eq!(recs.len(), 5, "4 scattered + 1 anchored recorded");
        assert_eq!(recs.iter().filter(|d| d.group == "posters").count(), 4);
        let out = std::env::temp_dir().join(format!("pigment-decal-variants-{}", std::process::id()));
        std::fs::remove_dir_all(&out).ok();
        let ex = s.export_variants(&json!({ "dir": out, "name": "A", "variants": [
            { "name": "authored" },
            { "name": "no_posters", "disable": ["posters"] },
            { "name": "replayed", "swaps": { "lying": { "image": graffiti, "tint": [1.0, 1.0, 1.0] } } }
        ] }))
        .unwrap();
        assert_eq!(ex["variants"][0]["decals_replayed"], 0, "{ex}");
        assert_eq!(ex["variants"][2]["decals_replayed"], 5, "the swap replays the whole layer: {ex}");
        let lit = |v: &str| image::open(out.join(format!("A__{v}/A_Emissive.png"))).unwrap().to_luma8().pixels().filter(|p| p.0[0] > 30).count();
        let (authored, no_posters, replayed) = (lit("authored"), lit("no_posters"), lit("replayed"));
        assert!(authored > 0 && no_posters < authored * 9 / 10, "posters off: {no_posters} of {authored}");
        let diff = authored.abs_diff(replayed);
        assert!(diff * 50 < authored, "replay reproduces the decals: {replayed} vs {authored}");
        std::fs::remove_dir_all(out).ok();
    }
}
