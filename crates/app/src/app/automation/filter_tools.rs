//! MCP: filters (layer result, mask, filter layers) and anchor points
//! (`pigment_core::filters`): add_filter, update_filter, remove_filter,
//! set_anchor, plus the `filters` / `anchor` / mask `input` / mask `filters`
//! fields of add_layer and update_layer.

use super::*;
use pigment_core::filters::{AnchorChannel, Filter, FilterKind, FilterTarget, GenInput};

fn target(a: &Value) -> Res<FilterTarget> {
    match s(a, "target") {
        None | Some("layer") => Ok(FilterTarget::Layer),
        Some("mask") => Ok(FilterTarget::Mask),
        Some(t) => Err(format!("`target` = \"{t}\": must be \"layer\" (the layer's result; for a filter layer the stack below) or \"mask\"")),
    }
}

/// A number or [r, g, b] / [r, g, b, master] for levels (a number sets the master).
fn levels4(v: &Value, k: &str, into: &mut [f32; 4]) -> Res<()> {
    let Some(x) = v.get(k) else { return Ok(()) };
    if let Some(n) = x.as_f64() {
        into[3] = n as f32;
        return Ok(());
    }
    let a: Vec<f32> = x.as_array().map(|a| a.iter().filter_map(Value::as_f64).map(|v| v as f32).collect()).unwrap_or_default();
    match a.len() {
        3 | 4 => {
            into[..a.len()].copy_from_slice(&a);
            Ok(())
        }
        _ => Err(format!("`levels.{k}` must be a number (master) or [r, g, b] / [r, g, b, master], got {x}")),
    }
}

fn rgb(v: &Value, k: &str) -> Res<Option<[f32; 3]>> {
    let Some(x) = v.get(k) else { return Ok(None) };
    let a: Vec<f32> = x.as_array().map(|a| a.iter().filter_map(Value::as_f64).map(|v| v as f32).collect()).unwrap_or_default();
    if a.len() != 3 {
        return Err(format!("`{k}` must be [r, g, b] offsets (-1..1), got {x}"));
    }
    Ok(Some([a[0], a[1], a[2]]))
}

/// Apply filter fields of `a` to `f` (kind changes reset the parameters).
pub(super) fn apply_filter_fields(f: &mut Filter, a: &Value, tgt: FilterTarget) -> Res<()> {
    if let Some(k) = s(a, "kind") {
        let kind = FilterKind::from_id(k).ok_or_else(|| format!("`kind` = \"{k}\": unknown filter (one of: {})", FilterKind::ALL.iter().map(|k| k.id()).collect::<Vec<_>>().join(", ")))?;
        if kind != f.kind {
            *f = Filter::new(kind);
        }
    }
    let ok = match tgt {
        FilterTarget::Mask => f.kind.on_mask(),
        FilterTarget::Layer => f.kind.on_layer(),
    };
    if !ok {
        return Err(format!("filter `{}` can't run on a {}", f.kind.id(), if tgt == FilterTarget::Mask { "mask (colour-only filter)" } else { "layer (mask-only filter: use target \"mask\")" }));
    }
    if let Some(e) = a.get("enabled").and_then(Value::as_bool) {
        f.enabled = e;
    }
    let p = &mut f.params;
    for (k, v) in [("radius", &mut p.radius), ("amount", &mut p.amount), ("angle", &mut p.angle), ("scale", &mut p.scale), ("hue", &mut p.hue), ("saturation", &mut p.saturation), ("lightness", &mut p.lightness), ("min", &mut p.min), ("max", &mut p.max)] {
        if let Some(x) = f32_arg(a, k) {
            *v = x;
        }
    }
    if let Some(x) = f32_arg(a, "strength") {
        p.amount = x;
    }
    if p.radius < 0.0 || p.radius > 512.0 {
        return Err(format!("`radius` = {}: must be 0..512 (texels at 2048)", p.radius));
    }
    if let Some(x) = a.get("seed").and_then(Value::as_u64) {
        p.seed = x as u32;
    }
    if let Some(x) = a.get("use_height").and_then(Value::as_bool) {
        p.use_height = x;
    }
    if let Some(lv) = a.get("levels") {
        levels4(lv, "in_black", &mut p.levels.in_black)?;
        levels4(lv, "in_white", &mut p.levels.in_white)?;
        levels4(lv, "gamma", &mut p.levels.gamma)?;
        levels4(lv, "out_black", &mut p.levels.out_black)?;
        levels4(lv, "out_white", &mut p.levels.out_white)?;
    }
    if let Some(c) = rgb(a, "shadows")? {
        p.shadows = c;
    }
    if let Some(c) = rgb(a, "midtones")? {
        p.midtones = c;
    }
    if let Some(c) = rgb(a, "highlights")? {
        p.highlights = c;
    }
    if let Some(chs) = a.get("channels").and_then(Value::as_array) {
        f.channels.clear();
        for c in chs {
            f.channels.push(channel(c.as_str().unwrap_or(""))?);
        }
    }
    Ok(())
}

fn f32_arg(a: &Value, k: &str) -> Option<f32> {
    a.get(k).and_then(Value::as_f64).map(|x| x as f32)
}

fn filter_json(f: &Filter) -> Value {
    let mut v = serde_json::to_value(f).unwrap_or(Value::Null);
    v["kind"] = json!(f.kind.id());
    v["channels"] = json!(f.channel_list().iter().map(|c| c.file_stem()).collect::<Vec<_>>());
    v
}

/// List of filters for list_layers / tool results.
pub(super) fn filters_json(fs: &[Filter]) -> Value {
    Value::Array(fs.iter().map(filter_json).collect())
}

/// Parse a generator `input` ({anchor, channel, strength, radius} | null).
pub(super) fn gen_input(doc: &Document, i: usize, v: &Value) -> Res<Option<GenInput>> {
    if v.is_null() {
        return Ok(None);
    }
    let name = s(v, "anchor").ok_or("`mask.input` needs `anchor` (an anchor name; see set_anchor)")?;
    let below = doc.anchors_below(i);
    let Some(name) = below.iter().find(|a| a.eq_ignore_ascii_case(name)) else {
        let all = doc.anchor_names();
        return Err(if all.iter().any(|a| a.eq_ignore_ascii_case(name)) {
            format!("`mask.input.anchor` = \"{name}\": that anchor is not below this layer (anchors are read by layers above them)")
        } else {
            format!("`mask.input.anchor` = \"{name}\": no such anchor (anchors: {})", if all.is_empty() { "none; set one with set_anchor".to_string() } else { all.join(", ") })
        });
    };
    let ch = s(v, "channel").unwrap_or("height");
    let channel = AnchorChannel::from_id(ch).ok_or_else(|| format!("`mask.input.channel` = \"{ch}\": one of height, mask, color"))?;
    let mut g = GenInput::new(name, channel);
    if let Some(x) = f32_arg(v, "strength") {
        g.strength = x;
    }
    if let Some(x) = f32_arg(v, "radius") {
        g.radius = x.clamp(1.0, 256.0);
    }
    Ok(Some(g))
}

/// add_layer / update_layer: `filters`, `anchor`, `mask.input`, `mask.filters`.
pub(super) fn configure_filters(app: &mut PigmentApp, i: usize, a: &Value) -> Res<()> {
    if let Some(list) = a.get("filters") {
        let arr = list.as_array().ok_or("`filters` must be an array of filters ([] removes them)")?;
        let mut out = Vec::new();
        for (k, f) in arr.iter().enumerate() {
            let kind = s(f, "kind").ok_or_else(|| format!("`filters[{k}]` needs `kind`"))?;
            let mut x = Filter::new(FilterKind::from_id(kind).ok_or_else(|| format!("`filters[{k}].kind` = \"{kind}\": unknown filter"))?);
            apply_filter_fields(&mut x, f, FilterTarget::Layer).map_err(|e| format!("`filters[{k}]`: {e}"))?;
            out.push(x);
        }
        app.doc.layers[i].filters = out;
    }
    match a.get("anchor") {
        None => {}
        Some(Value::Null) => app.doc.layers[i].anchor = None,
        Some(Value::String(n)) => set_anchor_name(&mut app.doc, i, n)?,
        Some(_) => return Err("`anchor` is a name or null".into()),
    }
    if let Some(m) = a.get("mask").filter(|m| m.is_object()) {
        match m.get("id_color") {
            None => {}
            Some(Value::Null) => {
                if let Some(mk) = app.doc.layers[i].mask.as_mut() {
                    mk.id_color = None;
                }
            }
            Some(v) => {
                let c = v.get("color").and_then(Value::as_array).filter(|c| c.len() == 3).ok_or("`mask.id_color.color` must be [r, g, b] (sRGB 0..1, as in the ID map)")?;
                let color = [0, 1, 2].map(|k| c[k].as_f64().unwrap_or(0.0) as f32);
                let tolerance = f32_arg(v, "tolerance").unwrap_or(0.1).max(0.0);
                if app.doc.id_map.is_none() {
                    return Err("`mask.id_color` needs an ID map: bake one first (bake maps [\"color_id\"] or [\"material_id\"])".into());
                }
                app.doc.layers[i].mask.as_mut().ok_or("`mask.id_color` needs a mask")?.id_color = Some(pigment_core::IdPick { color, tolerance });
            }
        }
        if let Some(v) = m.get("input") {
            let inp = gen_input(&app.doc, i, v)?;
            let g = app.doc.layers[i].mask.as_mut().and_then(|m| m.generator.as_mut()).ok_or("`mask.input` needs a mask generator")?;
            g.input = inp;
        }
        if let Some(list) = m.get("filters") {
            let arr = list.as_array().ok_or("`mask.filters` must be an array")?;
            let mut out = Vec::new();
            for (k, f) in arr.iter().enumerate() {
                let kind = s(f, "kind").ok_or_else(|| format!("`mask.filters[{k}]` needs `kind`"))?;
                let mut x = Filter::new(FilterKind::from_id(kind).ok_or_else(|| format!("`mask.filters[{k}].kind` = \"{kind}\": unknown filter"))?);
                apply_filter_fields(&mut x, f, FilterTarget::Mask).map_err(|e| format!("`mask.filters[{k}]`: {e}"))?;
                out.push(x);
            }
            app.doc.layers[i].mask.as_mut().ok_or("`mask.filters` needs a mask")?.filters = out;
        }
    }
    if app.doc.layers[i].mask.as_ref().and_then(|m| m.generator.as_ref()).is_some_and(|g| g.kind == GeneratorKind::Anchor && g.input.is_none()) {
        return Err("the `anchor` generator needs `mask.input` ({anchor, channel})".into());
    }
    Ok(())
}

fn set_anchor_name(doc: &mut Document, i: usize, n: &str) -> Res<()> {
    let n = n.trim();
    if n.is_empty() {
        return Err("`anchor` name must not be empty (null removes the anchor)".into());
    }
    if let Some(j) = doc.anchor_layer(n) {
        if j != i {
            return Err(format!("anchor \"{n}\" is already on layer `{}`", doc.layers[j].name));
        }
    }
    doc.layers[i].anchor = Some(n.to_string());
    Ok(())
}

impl Session {
    fn filter_list(&mut self, i: usize, t: FilterTarget) -> Res<&mut Vec<Filter>> {
        let l = &mut self.app.doc.layers[i];
        match t {
            FilterTarget::Layer => {
                if l.is_foliage() {
                    return Err("foliage layers have no texture filters".into());
                }
                Ok(&mut l.filters)
            }
            FilterTarget::Mask => Ok(&mut l.mask.as_mut().ok_or_else(|| format!("`{}` has no mask: give it one first (update_layer mask)", l.name))?.filters),
        }
    }

    fn filter_result(&self, i: usize, t: FilterTarget) -> Value {
        let l = &self.app.doc.layers[i];
        let fs = match t {
            FilterTarget::Layer => &l.filters,
            FilterTarget::Mask => l.mask.as_ref().map(|m| &m.filters).unwrap_or(&l.filters),
        };
        json!({ "layer": l.name, "target": if t == FilterTarget::Mask { "mask" } else { "layer" }, "filters": filters_json(fs) })
    }

    /// add_filter: append (or insert at `index`) a filter to a layer's result or mask.
    pub fn add_filter(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer`")?)?;
        let t = target(a)?;
        let kind = req(a, "kind")?;
        let mut f = Filter::new(FilterKind::from_id(kind).ok_or_else(|| format!("`kind` = \"{kind}\": unknown filter (one of: {})", FilterKind::ALL.iter().map(|k| k.id()).collect::<Vec<_>>().join(", ")))?);
        apply_filter_fields(&mut f, a, t)?;
        let list = self.filter_list(i, t)?;
        let at = a.get("index").and_then(Value::as_u64).map(|x| (x as usize).min(list.len())).unwrap_or(list.len());
        list.insert(at, f);
        self.settle();
        Ok(self.filter_result(i, t))
    }

    /// update_filter: change, toggle or move filter `index`.
    pub fn update_filter(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer`")?)?;
        let t = target(a)?;
        let k = a.get("index").and_then(Value::as_u64).ok_or("missing `index` (0 = first filter, runs first)")? as usize;
        let list = self.filter_list(i, t)?;
        let n = list.len();
        let f = list.get_mut(k).ok_or_else(|| format!("`index` = {k}: the stack has {n} filter(s)"))?;
        apply_filter_fields(f, a, t)?;
        if let Some(to) = a.get("move_to").and_then(Value::as_u64) {
            let f = list.remove(k);
            let to = (to as usize).min(list.len());
            list.insert(to, f);
        }
        self.settle();
        Ok(self.filter_result(i, t))
    }

    /// remove_filter: drop filter `index`.
    pub fn remove_filter(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer`")?)?;
        let t = target(a)?;
        let k = a.get("index").and_then(Value::as_u64).ok_or("missing `index`")? as usize;
        let list = self.filter_list(i, t)?;
        if k >= list.len() {
            return Err(format!("`index` = {k}: the stack has {} filter(s)", list.len()));
        }
        list.remove(k);
        self.settle();
        Ok(self.filter_result(i, t))
    }

    /// set_anchor: make a layer (or folder) an anchor point, or clear it.
    pub fn set_anchor(&mut self, a: &Value) -> Res<Value> {
        let i = self.find_layer(a.get("layer").ok_or("missing `layer`")?)?;
        match a.get("anchor") {
            None => {
                let n = self.app.doc.layers[i].name.clone();
                set_anchor_name(&mut self.app.doc, i, &n)?
            }
            Some(Value::Null) => self.app.doc.layers[i].anchor = None,
            Some(Value::String(n)) => set_anchor_name(&mut self.app.doc, i, n)?,
            Some(_) => return Err("`anchor` is a name or null".into()),
        }
        self.settle();
        Ok(json!({ "layer": self.app.doc.layers[i].name, "anchor": self.app.doc.layers[i].anchor, "anchors": self.app.doc.anchor_names() }))
    }
}

#[cfg(test)]
mod tests {
    use super::super::gpu_lock;
    use std::path::Path;
    use super::*;

    /// add_filter / update_filter / remove_filter / set_anchor / mask.input
    /// over the session API, with renders changing, save + reopen and undo.
    #[test]
    fn filters_and_anchors_over_mcp() {
        let _gpu = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Olive drab" })).unwrap();
        let shot = |s: &mut Session| image::load_from_memory(&s.render(&json!({ "width": 200, "height": 200 })).unwrap().png).unwrap().to_rgb8();
        let mean = |img: &image::RgbImage| img.pixels().map(|p| p.0[0] as f64 + p.0[1] as f64 + p.0[2] as f64).sum::<f64>() / img.len() as f64;
        let before = shot(&mut s);
        // a filter layer: HSL lightness up
        s.add_layer(&json!({ "kind": "filter", "name": "Grade", "filters": [{ "kind": "hsl", "lightness": 0.5 }] })).unwrap();
        let lighter = shot(&mut s);
        assert!(mean(&lighter) > mean(&before) + 5.0, "HSL lightness brightens");
        let r = s.update_filter(&json!({ "layer": "Grade", "index": 0, "enabled": false })).unwrap();
        assert_eq!(r["filters"][0]["enabled"], false);
        let off = shot(&mut s);
        assert!((mean(&off) - mean(&before)).abs() < 1.0, "disabled filter = no change");
        s.add_filter(&json!({ "layer": "Grade", "kind": "levels", "levels": { "out_white": 0.5 } })).unwrap();
        assert!(mean(&shot(&mut s)) < mean(&before) - 5.0, "levels darken");
        // errors name the problem
        assert!(s.add_filter(&json!({ "layer": "Grade", "kind": "grow" })).unwrap_err().contains("mask"));
        assert!(s.add_filter(&json!({ "layer": "Grade", "kind": "nope" })).unwrap_err().contains("unknown filter"));
        s.remove_filter(&json!({ "layer": "Grade", "index": 1 })).unwrap();
        // anchors + generator input + mask filters
        s.set_anchor(&json!({ "layer": "Base" })).unwrap();
        s.add_layer(&json!({ "name": "Wear", "material": "Steel", "mask": { "generator": "edge_wear", "input": { "anchor": "Base", "channel": "height" }, "filters": [{ "kind": "blur", "radius": 3 }] } })).unwrap();
        let l = s.list_layers(&json!({}));
        let wear = l.as_array().unwrap().iter().find(|x| x["name"] == "Wear").unwrap().clone();
        assert_eq!(wear["mask"]["input"]["anchor"], "Base");
        assert_eq!(wear["mask"]["filters"][0]["kind"], "blur");
        assert!(s.update_layer(&json!({ "layer": "Base", "mask": { "generator": "dirt", "input": { "anchor": "Base" } } })).unwrap_err().contains("not below"));
        assert!(s.update_layer(&json!({ "layer": "Wear", "mask": { "input": { "anchor": "Nope" } } })).unwrap_err().contains("no such anchor"));
        // save, reopen: same stack
        let dir = std::env::temp_dir().join(format!("pigment-filters-{}", std::process::id()));
        s.save_project(&json!({ "path": dir.join("t.pigment") })).unwrap();
        let a = shot(&mut s);
        s.open_project(&json!({ "path": dir.join("t.pigment") })).unwrap();
        let b = shot(&mut s);
        assert!((mean(&a) - mean(&b)).abs() < 0.5, "reopened project renders the same");
        assert_eq!(s.app.doc.layers.iter().filter(|l| l.anchor.is_some()).count(), 1);
        // undo removes the anchor's reader again
        s.set_anchor(&json!({ "layer": "Base", "anchor": null })).unwrap();
        s.undo(false).unwrap();
        assert_eq!(s.app.doc.anchor_names(), vec!["Base".to_string()]);
        std::fs::remove_dir_all(dir).ok();
    }
}
