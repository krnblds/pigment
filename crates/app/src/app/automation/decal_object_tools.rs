//! MCP: non-destructive decal objects (`pigment_core::decal_layer`):
//! project_decal / scatter_decals on a decal layer create objects;
//! list_decals, update_decal, delete_decal; place_decal {region: auto | box,
//! grid} finds the largest flat window-free wall area and fills it.

use super::*;
use crate::app::decals::BoxDecal;
use pigment_core::decal::Placement;
use pigment_core::decal_layer::{self as dl, DecalObject, DecalProjection, DecalWear, Region, RegionQuery};
use pigment_core::Channel;

/// Rotation (degrees) that reproduces a placement's frame.
pub(super) fn placement_rotation(p: &Placement) -> f32 {
    let p0 = Placement::new(p.center, p.normal, p.size, 0.0, p.depth);
    p0.right.cross(p.right).dot(p.normal).atan2(p0.right.dot(p.right)).to_degrees()
}

fn projection_arg(a: &Value) -> Res<DecalProjection> {
    match s(a, "projection") {
        None => Ok(DecalProjection::Box),
        Some(p) => DecalProjection::from_id(p).ok_or_else(|| format!("`projection` = \"{p}\": box, triplanar or wrap")),
    }
}

fn decal_json(layer: &str, o: &DecalObject) -> Value {
    json!({
        "id": o.id, "name": o.name, "group": o.group, "layer": layer, "image": o.image, "enabled": o.enabled,
        "center": o.center, "normal": o.normal, "size": o.size, "rotation": o.rotation, "depth": o.depth,
        "projection": o.projection.id(), "wear": o.wear.tear, "fade": o.wear.fade, "opacity": o.wear.opacity,
        "tint": o.values.base_color, "channels": o.channels.iter().map(|c| c.file_stem()).collect::<Vec<_>>(),
    })
}

impl Session {
    pub(super) fn is_decal_layer(&self, i: usize) -> bool {
        self.app.doc.layers.get(i).is_some_and(|l| l.decals.is_some())
    }

    /// Add decals as objects to decal layer `i` (look + brush values from `a`).
    pub(super) fn add_decal_objects(&mut self, a: &Value, i: usize, decals: &[BoxDecal]) -> Res<Vec<u32>> {
        let projection = projection_arg(a)?;
        // material values / channels the decal paints (same arguments as before)
        let mut brush_args = a.clone();
        if let Some(o) = brush_args.as_object_mut() {
            o.remove("height");
        }
        self.decal_brush(&brush_args, i)?;
        let values = self.app.brush.values.clone();
        let channels: Vec<Channel> = Channel::ALL.into_iter().filter(|c| self.app.brush.channels[c.index()]).collect();
        let group = s(a, "variant").unwrap_or("").to_string();
        let enabled = a.get("enabled").and_then(Value::as_bool).unwrap_or(true);
        let mut ids = Vec::new();
        let mesh = self.app.wrap_mesh.clone().unwrap_or_else(|| self.app.mesh.clone());
        for (k, d) in decals.iter().enumerate() {
            let mut tiles = pigment_core::tiles::TileSet::default();
            let mut probe = d.placement;
            if projection != DecalProjection::Box {
                probe.size *= 3.0;
            }
            if probe.mark_tiles(&mesh, &mut tiles) == 0 {
                continue;
            }
            let stem = d.image.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
            let name = match s(a, "name") {
                Some(n) if decals.len() == 1 => n.to_string(),
                Some(n) => format!("{n}_{k}"),
                None => stem,
            };
            let l = &d.look;
            let o = DecalObject {
                id: 0,
                name,
                group: group.clone(),
                image: d.image.to_string_lossy().replace('\\', "/"),
                center: d.placement.center.into(),
                normal: d.placement.normal.into(),
                size: d.placement.size.into(),
                rotation: placement_rotation(&d.placement),
                depth: d.placement.depth,
                projection,
                wear: DecalWear { opacity: l.opacity, alpha_from_luminance: l.luminance_alpha, tear: l.tear, fade: l.fade, wear_scale: l.wear_scale, seed: l.seed, grunge: l.grunge, paper_rim: l.paper_rim },
                values: values.clone(),
                channels: channels.clone(),
                enabled,
            };
            let set = self.app.doc.layers[i].decals.get_or_insert_with(Default::default);
            ids.push(set.add(o));
        }
        if ids.is_empty() {
            return Err("the decal touches no surface (check anchor / position and normal)".into());
        }
        self.settle();
        Ok(ids)
    }

    /// Find a decal object: (layer index, object index).
    fn find_decal(&self, a: &Value) -> Res<(usize, usize)> {
        let key = match a.get("decal") {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Number(n)) => n.to_string(),
            _ => return Err("missing `decal` (an id or name, see list_decals)".into()),
        };
        let layers: Vec<usize> = match a.get("layer") {
            Some(r) => vec![self.find_layer(r)?],
            None => (0..self.app.doc.layers.len()).rev().collect(),
        };
        for i in layers {
            if let Some(k) = self.app.doc.layers[i].decals.as_ref().and_then(|s| s.find(&key)) {
                return Ok((i, k));
            }
        }
        Err(format!("no decal `{key}` (see list_decals)"))
    }

    /// `list_decals`: every decal object (or one layer's).
    pub fn list_decals(&self, a: &Value) -> Res<Value> {
        let only = match a.get("layer") {
            Some(r) => Some(self.find_layer(r)?),
            None => None,
        };
        let mut out = Vec::new();
        for (i, l) in self.app.doc.layers.iter().enumerate() {
            if only.is_some_and(|o| o != i) {
                continue;
            }
            for o in l.decals.iter().flat_map(|s| s.objects.iter()) {
                out.push(decal_json(&l.name, o));
            }
        }
        Ok(json!({ "decals": out }))
    }

    /// `update_decal`: move / rotate / scale / re-image / re-order / snap a decal.
    pub fn update_decal(&mut self, a: &Value) -> Res<Value> {
        let (i, k) = self.find_decal(a)?;
        let mesh = self.app.mesh.clone();
        let tri_part = self.app.parts.triangle_part.clone();
        let mut o = self.app.doc.layers[i].decals.as_ref().unwrap().objects[k].clone();
        if let Some(n) = vec3_arg(a, "normal")? {
            o.normal = n.try_normalize().ok_or("`normal` is zero")?.into();
        }
        if let Some(p) = vec3_arg(a, "position")? {
            // snapped onto the surface along the normal (within 0.5 m)
            let n = Vec3::from(o.normal);
            o.center = match pigment_core::decal::raycast_parts(&mesh, &tri_part, None, p + n * 0.5, -n) {
                Some((_, d, hn)) if d < 1.0 => {
                    if hn.dot(n) > 0.5 && a.get("normal").is_none() {
                        o.normal = hn.into();
                    }
                    (p + n * 0.5 - n * d).into()
                }
                _ => p.into(),
            };
        }
        if let Some(m) = a.get("move").and_then(Value::as_array) {
            let pl = o.placement();
            let d = |k: usize| m.get(k).and_then(Value::as_f64).unwrap_or(0.0) as f32;
            o.center = (pl.center + pl.right * d(0) + pl.up * d(1)).into();
        }
        match a.get("size") {
            None => {}
            Some(Value::Number(w)) => {
                let w = w.as_f64().unwrap_or(0.5) as f32;
                o.size = [w, w * o.size[1] / o.size[0].max(1e-6)];
            }
            Some(Value::Array(v)) if v.len() == 2 => o.size = [v[0].as_f64().unwrap_or(0.5) as f32, v[1].as_f64().unwrap_or(0.5) as f32],
            Some(_) => return Err("`size` is a width in metres (keeps the aspect) or [w, h]".into()),
        }
        if let Some(sc) = f(a, "scale") {
            o.size = [o.size[0] * sc, o.size[1] * sc];
        }
        if let Some(r) = f(a, "rotation") {
            o.rotation = r;
        }
        if let Some(r) = f(a, "rotate") {
            o.rotation += r;
        }
        if let Some(d) = f(a, "depth") {
            o.depth = d.max(1e-3);
        }
        if a.get("projection").is_some() {
            o.projection = projection_arg(a)?;
        }
        if let Some(img) = s(a, "image") {
            o.image = img.to_string();
        }
        if let Some(t) = a.get("tint").and_then(Value::as_array) {
            for (c, x) in t.iter().take(3).enumerate() {
                o.values.base_color[c] = x.as_f64().unwrap_or(1.0) as f32;
            }
        }
        for (key, v) in [("opacity", &mut o.wear.opacity), ("wear", &mut o.wear.tear), ("fade", &mut o.wear.fade), ("wear_scale", &mut o.wear.wear_scale), ("wear_seed", &mut o.wear.seed), ("paper_rim", &mut o.wear.paper_rim)] {
            if let Some(x) = f(a, key) {
                *v = x;
            }
        }
        if let Some(e) = a.get("enabled").and_then(Value::as_bool) {
            o.enabled = e;
        }
        if let Some(n) = s(a, "name") {
            o.name = n.to_string();
        }
        if let Some(g) = s(a, "variant") {
            o.group = g.to_string();
        }
        if let Some(al) = s(a, "align") {
            match al {
                "upright" | "horizontal" => o.rotation = 0.0,
                "vertical" => o.rotation = 90.0,
                x => return Err(format!("`align` = \"{x}\": upright or vertical")),
            }
        }
        if let Some(sn) = s(a, "snap") {
            // the flat window-free area under the decal
            let regions = dl::find_regions(&mesh, &RegionQuery { margin: 0.0, max_normal_y: 1.0, ..Default::default() });
            let r = dl::region_at(&regions, Vec3::from(o.center)).ok_or("`snap`: the decal isn't on a flat area")?;
            o.center = match sn {
                "center" | "centre" => dl::snap(&o, r, false, 0.0),
                "edge" => dl::snap(&o, r, true, f(a, "margin").unwrap_or(0.05)),
                x => return Err(format!("`snap` = \"{x}\": center or edge")),
            }
            .into();
        }
        let set = self.app.doc.layers[i].decals.as_mut().unwrap();
        set.objects[k] = o;
        if let Some(to) = a.get("move_to").and_then(Value::as_u64) {
            let x = set.objects.remove(k);
            let to = (to as usize).min(set.objects.len());
            set.objects.insert(to, x);
        }
        self.settle();
        let l = &self.app.doc.layers[i];
        let o = l.decals.as_ref().unwrap().objects.iter().find(|x| x.name == s(a, "name").unwrap_or("")).or_else(|| l.decals.as_ref().unwrap().objects.get(a.get("move_to").and_then(Value::as_u64).map(|x| x as usize).unwrap_or(k))).cloned();
        Ok(json!({ "decal": o.map(|o| decal_json(&l.name, &o)) }))
    }

    /// `delete_decal`.
    pub fn delete_decal(&mut self, a: &Value) -> Res<Value> {
        let (i, k) = self.find_decal(a)?;
        let o = self.app.doc.layers[i].decals.as_mut().unwrap().objects.remove(k);
        self.settle();
        Ok(json!({ "deleted": o.name, "id": o.id, "layer": self.app.doc.layers[i].name }))
    }

    /// `place_decal`: the largest flat, window-free area (region auto), one
    /// decal fitted in it or a grid of them.
    pub fn place_decal_region(&mut self, a: &Value) -> Res<Value> {
        let images: Vec<PathBuf> = match (a.get("image"), a.get("images")) {
            (Some(Value::String(i)), _) => vec![PathBuf::from(i)],
            (_, Some(Value::Array(v))) => v.iter().filter_map(|x| x.as_str().map(PathBuf::from)).collect(),
            _ => return Err("missing `image` (or `images` for a grid)".into()),
        };
        if images.is_empty() {
            return Err("`images` is empty".into());
        }
        let aspects = images.iter().map(|p| super::decal_tools::image_aspect(p)).collect::<Res<Vec<f32>>>()?;
        let mesh = self.app.mesh.clone();
        let mut q = RegionQuery { margin: f(a, "margin").unwrap_or(0.05), ..Default::default() };
        let mut parts = a.get("parts").and_then(Value::as_array).map(|v| v.iter().filter_map(|x| x.as_u64().map(|x| x as u32)).collect::<Vec<u32>>());
        if let Some(w) = a.get("parts_where") {
            parts.get_or_insert_with(Vec::new).extend(self.query_ids(w, "parts_where.")?);
        }
        if let Some(p) = &parts {
            let tp = &self.app.parts.triangle_part;
            q.triangles = Some((0..mesh.triangle_count()).map(|t| tp.get(t).is_some_and(|id| p.contains(id))).collect());
        }
        if let Some(h) = a.get("height").and_then(Value::as_array) {
            let g = mesh.bounds().0.y;
            let v = |k: usize| h.get(k).and_then(Value::as_f64).unwrap_or(0.0) as f32;
            q.height = Some((g + v(0), g + v(1)));
        }
        if s(a, "facing") == Some("any") {
            q.max_normal_y = 1.0;
        }
        let region: Region = match a.get("region") {
            Some(Value::String(r)) if r == "auto" => {
                let all = dl::find_regions(&mesh, &q);
                let pick = a.get("pick").and_then(Value::as_u64).unwrap_or(0) as usize;
                *all.get(pick).ok_or_else(|| if all.is_empty() { "no flat window-free area found (loosen height / parts / facing)".to_string() } else { format!("`pick` = {pick}: only {} areas found", all.len()) })?
            }
            Some(r) if r.is_object() => {
                // the largest area inside a world box
                let lo = vec3_arg(r, "min")?.ok_or("`region` needs `min` [x,y,z]")?;
                let hi = vec3_arg(r, "max")?.ok_or("`region` needs `max` [x,y,z]")?;
                let inside: Vec<bool> = (0..mesh.triangle_count())
                    .map(|t| {
                        let c = (0..3).map(|k| Vec3::from(mesh.vertices[mesh.indices[t * 3 + k] as usize].position)).sum::<Vec3>() / 3.0;
                        c.cmpge(lo).all() && c.cmple(hi).all() && q.triangles.as_ref().is_none_or(|s| s[t])
                    })
                    .collect();
                q.triangles = Some(inside);
                *dl::find_regions(&mesh, &q).first().ok_or("no flat area inside `region`")?
            }
            _ => return Err("`region` must be \"auto\" or {min, max}".into()),
        };
        let fill = f(a, "fill").unwrap_or(0.9).clamp(0.05, 1.0);
        let look = Self::decal_look(a)?;
        let mut decals = Vec::new();
        match a.get("grid") {
            Some(g) => {
                let rows = g.get("rows").and_then(Value::as_u64).unwrap_or(2) as u32;
                let cols = g.get("cols").and_then(Value::as_u64).unwrap_or(3) as u32;
                let gap = g.get("gap").and_then(Value::as_f64).unwrap_or(0.08) as f32;
                for (k, (c, cell)) in dl::grid(&region, rows, cols, gap).into_iter().enumerate() {
                    let im = k % images.len();
                    let cr = Region { center: c, size: cell, ..region };
                    let (center, size) = dl::fit_in(&cr, aspects[im], fill);
                    decals.push(BoxDecal { image: images[im].clone(), placement: Placement::new(center, region.normal, size, 0.0, Placement::default_depth(size)), look, projection: Default::default() });
                }
            }
            None => {
                let (center, size) = dl::fit_in(&region, aspects[0], fill);
                decals.push(BoxDecal { image: images[0].clone(), placement: Placement::new(center, region.normal, size, 0.0, Placement::default_depth(size)), look, projection: Default::default() });
            }
        }
        let i = self.decal_layer(a)?;
        if !self.is_decal_layer(i) {
            return Err(format!("place_decal makes decal objects: `{}` is not a decal layer (add one with add_layer kind \"decal\")", self.app.doc.layers[i].name));
        }
        let ids = self.add_decal_objects(a, i, &decals)?;
        let l = &self.app.doc.layers[i];
        let objs: Vec<Value> = l.decals.as_ref().unwrap().objects.iter().filter(|o| ids.contains(&o.id)).map(|o| decal_json(&l.name, o)).collect();
        let mut out = json!({ "region": { "center": region.center.to_array(), "normal": region.normal.to_array(), "size": region.size.to_array() }, "decals": objs, "layer": l.name });
        let pls: Vec<Placement> = decals.iter().map(|d| d.placement).collect();
        self.texel_report(&pls, &mut out);
        Ok(out)
    }
}

fn vec3_arg(a: &Value, k: &str) -> Res<Option<Vec3>> {
    match a.get(k) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Array(v)) if v.len() == 3 && v.iter().all(Value::is_number) => Ok(Some(Vec3::new(v[0].as_f64().unwrap() as f32, v[1].as_f64().unwrap() as f32, v[2].as_f64().unwrap() as f32))),
        Some(v) => Err(format!("`{k}` must be [x, y, z], got {v}")),
    }
}

#[cfg(test)]
mod tests {
    use super::super::gpu_lock;
    use super::*;

    fn root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
    }

    /// Emissive texels (decals glow so they're easy to count).
    fn glow(s: &mut Session) -> usize {
        let img = s.render(&json!({ "view": "emission", "yaw": 90, "pitch": 5, "width": 320, "height": 320, "target": [4.0, 2.0, 0.0], "distance": 9 })).unwrap();
        image::load_from_memory(&img.png).unwrap().to_luma8().pixels().filter(|p| p.0[0] > 60).count()
    }

    /// Decal objects on building_a: place, list, move, scale, re-image,
    /// re-order, hide, delete, undo; region auto and a grid; projections;
    /// project_decal / scatter_decals on a decal layer make objects.
    #[test]
    fn decal_objects_over_mcp() {
        let _g = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        s.new_project(&json!({ "mesh": root().join("assets/town/building_a.glb"), "resolution": 1024, "material": "Concrete" })).unwrap();
        s.add_layer(&json!({ "kind": "decal", "name": "Posters" })).unwrap();
        let img = root().join("assets/decals/story/poster_missing_aiko.png");
        let base = glow(&mut s);
        let r = s.project_decal(&json!({ "image": img, "layer": "Posters", "position": [4.4, 1.6, 0.0], "normal": [1, 0, 0], "size": 1.2, "emissive_strength": 3.0, "name": "aiko" })).unwrap();
        assert!(r.to_string().contains("\"aiko\""), "{r}");
        let lit = glow(&mut s);
        assert!(lit > base + 300, "the object's decal paints ({base} -> {lit})");
        let list = s.list_decals(&json!({})).unwrap();
        assert_eq!(list["decals"].as_array().unwrap().len(), 1);
        // move it along the wall: the glow moves, the amount stays
        s.update_decal(&json!({ "decal": "aiko", "move": [0.0, 1.0] })).unwrap();
        let moved = glow(&mut s);
        assert!((moved as f32 - lit as f32).abs() / (lit as f32) < 0.35, "same decal elsewhere ({lit} vs {moved})");
        s.update_decal(&json!({ "decal": "aiko", "scale": 2.0 })).unwrap();
        assert!(glow(&mut s) > moved + 200, "scaled up");
        s.update_decal(&json!({ "decal": "aiko", "enabled": false })).unwrap();
        assert!(glow(&mut s) < base + 50, "hidden");
        s.undo(false).unwrap();
        assert!(glow(&mut s) > moved + 200, "undo shows it again");
        // region auto: the largest window-free wall area, a 2 x 3 grid of posters
        let r = s.place_decal_region(&json!({ "images": [img, root().join("assets/decals/story/poster_unplug.png")], "region": "auto", "height": [0.3, 3.4], "grid": { "rows": 2, "cols": 3 }, "layer": "Posters", "emissive_strength": 2.0 })).unwrap();
        assert_eq!(r["decals"].as_array().unwrap().len(), 6, "{r}");
        let size = r["region"]["size"].as_array().unwrap().iter().map(|v| v.as_f64().unwrap()).collect::<Vec<_>>();
        assert!(size[0] > 1.0 && size[1] > 1.0, "a sizable flat area: {size:?}");
        // a decal on a decal layer from scatter, and a triplanar / wrap projection
        let r = s.scatter_decals(&json!({ "images": [img], "count": 3, "seed": 2, "layer": "Posters", "height": [0.5, 2.5], "size": [0.4, 0.5], "projection": "triplanar" })).unwrap();
        assert!(r["placed"].as_u64().unwrap() >= 1, "{r}");
        let all = s.list_decals(&json!({ "layer": "Posters" })).unwrap();
        assert!(all["decals"].as_array().unwrap().iter().any(|d| d["projection"] == "triplanar"));
        let first = all["decals"][0]["id"].clone();
        s.update_decal(&json!({ "decal": first, "projection": "wrap", "move_to": 99 })).unwrap();
        let after = s.list_decals(&json!({ "layer": "Posters" })).unwrap();
        assert_eq!(after["decals"].as_array().unwrap().last().unwrap()["projection"], "wrap", "re-ordered to the top");
        // delete, errors
        s.delete_decal(&json!({ "decal": "aiko" })).unwrap();
        assert!(s.update_decal(&json!({ "decal": "aiko", "scale": 2 })).unwrap_err().contains("no decal"));
        // save / reopen keeps the objects and regenerates the pixels
        let dir = std::env::temp_dir().join(format!("pigment-decal-obj-{}", std::process::id()));
        let n = s.list_decals(&json!({})).unwrap()["decals"].as_array().unwrap().len();
        let g1 = glow(&mut s);
        s.save_project(&json!({ "path": dir.join("d.pigment") })).unwrap();
        s.open_project(&json!({ "path": dir.join("d.pigment") })).unwrap();
        assert_eq!(s.list_decals(&json!({})).unwrap()["decals"].as_array().unwrap().len(), n);
        let g2 = glow(&mut s);
        assert!((g1 as f32 - g2 as f32).abs() / (g1.max(1) as f32) < 0.05, "reopened decals look the same ({g1} vs {g2})");
        std::fs::remove_dir_all(dir).ok();
    }
}
