//! MCP: flat sheet projects (`new_project` with `tile`): seamless tiles,
//! trim sheets and decal atlases, plus their layout JSON on export.

use super::*;
use pigment_core::tile::{SheetKind, TileSpec};

fn pair(v: &Value, what: &str) -> Res<[f32; 2]> {
    if let Some(x) = v.as_f64() {
        return Ok([x as f32; 2]);
    }
    let a: Vec<f32> = v.as_array().map(|a| a.iter().filter_map(Value::as_f64).map(|x| x as f32).collect()).unwrap_or_default();
    match a[..] {
        [w, h] if w > 0.0 && h > 0.0 => Ok([w, h]),
        _ => Err(format!("`{what}` must be a positive number or [width, height] in metres, got {v}")),
    }
}

/// Parse `new_project.tile`.
pub fn tile_spec(t: &Value, res: u32) -> Res<TileSpec> {
    let strips = t.get("strips").and_then(Value::as_array);
    let cells = t.get("cells").and_then(Value::as_array);
    let mut spec = match (strips, cells) {
        (Some(_), Some(_)) => return Err("`tile`: give `strips` (trim sheet) or `cells` (decal atlas), not both".into()),
        (Some(strips), None) => {
            let width = match t.get("size_m") {
                Some(v) => pair(v, "tile.size_m")?[0],
                None => t.get("width_m").and_then(Value::as_f64).map(|x| x as f32).unwrap_or(2.0),
            };
            let list = strips
                .iter()
                .enumerate()
                .map(|(i, s)| {
                    let name = s.get("name").and_then(Value::as_str).map(String::from).unwrap_or_else(|| format!("Strip {i}"));
                    let h = s.get("height_m").and_then(Value::as_f64).ok_or_else(|| format!("`tile.strips[{i}].height_m` is required (metres)"))? as f32;
                    Ok((name, h))
                })
                .collect::<Res<Vec<_>>>()?;
            TileSpec::trim(width, &list)?
        }
        (None, Some(cells)) => {
            let list = cells
                .iter()
                .enumerate()
                .map(|(i, c)| {
                    let name = c.get("name").and_then(Value::as_str).map(String::from).unwrap_or_else(|| format!("Cell {i}"));
                    let size = pair(c.get("size_m").ok_or_else(|| format!("`tile.cells[{i}].size_m` is required"))?, &format!("tile.cells[{i}].size_m"))?;
                    Ok((name, size))
                })
                .collect::<Res<Vec<_>>>()?;
            let pad = t.get("padding_px").and_then(Value::as_u64).unwrap_or(16) as u32;
            TileSpec::atlas(&list, res, pad)?
        }
        (None, None) => {
            let size = pair(t.get("size_m").ok_or("`tile.size_m` is required for a seamless tile (metres, e.g. [4, 4])")?, "tile.size_m")?;
            TileSpec::tile(size[0], size[1])
        }
    };
    if let Some(o) = t.get("offset_m") {
        let v: Vec<f32> = o.as_array().map(|a| a.iter().filter_map(Value::as_f64).map(|x| x as f32).collect()).unwrap_or_default();
        spec.offset_m = match v[..] {
            [x, z] => [x, z],
            _ => return Err(format!("`tile.offset_m` must be [x, z] in metres, got {o}")),
        };
    }
    if let Some(w) = t.get("wrap").and_then(Value::as_str) {
        spec.wrap = match w {
            "both" => [true, true],
            "u" | "x" => [true, false],
            "v" | "y" | "z" => [false, true],
            "none" => [false, false],
            other => return Err(format!("`tile.wrap` = \"{other}\": one of both, u, v, none")),
        };
    }
    Ok(spec)
}

impl Session {
    /// `new_project` with `tile`: a flat plane sized in metres whose UVs fill
    /// the texture. Trim strips / atlas cells are mesh parts; each gets a
    /// folder masked to it (unless `folders: false`).
    pub(super) fn new_sheet_project(&mut self, a: &Value) -> Res<Value> {
        self.app.status = None;
        if let Some(r) = a.get("resolution").and_then(Value::as_u64) {
            if !RESOLUTIONS.contains(&(r as u32)) {
                return Err(format!("resolution must be one of {RESOLUTIONS:?}"));
            }
            self.app.doc.resolution = r as u32;
        }
        let t = &a["tile"];
        let spec = tile_spec(t, self.app.doc.resolution)?;
        let mesh = spec.mesh();
        let mut doc = Document::new_default();
        doc.tile = Some(spec.clone());
        self.app.export_name = t.get("name").and_then(Value::as_str).map(String::from).unwrap_or_else(|| mesh.name.clone());
        self.app.new_project(&self.rs, mesh, None, doc);
        self.status()?;
        self.app.doc.layers.clear();
        if let Some(name) = s(a, "smart_material") {
            let layers = self.app.doc.smart_material(name).ok_or_else(|| unknown_smart_material(name))?;
            self.app.doc.layers.extend(layers);
        } else {
            let base = self.app.doc.fill_with("Base", s(a, "material").unwrap_or("White plastic"), None);
            self.app.doc.layers.push(base);
        }
        let paint = self.app.doc.new_paint_layer("Paint");
        self.app.doc.layers.push(paint);
        self.app.committed = self.app.doc.clone();
        let _ = self.app.history.clear();
        self.app.select(self.app.doc.layers.last().map(|l| l.id), false);
        self.settle();
        // an atlas starts transparent: cells get content where layers paint opacity 1
        if spec.kind == SheetKind::Atlas {
            self.update_layer(&json!({ "layer": "Base", "values": { "opacity": 0.0 } }))?;
        }
        if spec.kind != SheetKind::Tile && t.get("folders").and_then(Value::as_bool).unwrap_or(true) {
            for (i, c) in spec.cells.iter().enumerate() {
                self.add_layer(&json!({ "kind": "folder", "name": c.name, "mask": { "parts": [i] } }))?;
            }
        }
        self.app.committed = self.app.doc.clone();
        let _ = self.app.history.clear();
        self.settle();
        Ok(json!({ "mesh": self.app.mesh.name, "triangles": self.app.mesh.triangle_count(), "tile": self.app.doc.tile.as_ref().map(|t| t.layout_json(&self.app.export_name, self.app.doc.resolution)), "layers": self.layers() }))
    }

    /// After an export of a sheet project: `<name>_layout.json` (strip / cell
    /// UV rects), and for atlases `<name>_BaseColorAlpha.png` (sRGB colour +
    /// opacity as alpha). Returns the extra files.
    pub(super) fn export_sheet_extras(&mut self, dir: &Path) -> Res<Vec<String>> {
        let Some(spec) = self.app.doc.tile.clone() else { return Ok(vec![]) };
        let name = self.app.export_name.clone();
        let mut files = vec![];
        let layout = dir.join(format!("{name}_layout.json"));
        let j = spec.layout_json(&name, self.app.doc.resolution);
        std::fs::write(&layout, serde_json::to_string_pretty(&j).unwrap()).map_err(|e| format!("couldn't write {}: {e}", layout.display()))?;
        files.push(layout.to_string_lossy().to_string());
        if spec.kind == SheetKind::Atlas {
            let (d, q) = (&self.rs.device, &self.rs.queue);
            let m = crate::render::io::read_material(d, q, &self.app.ts);
            let mut img = image::RgbaImage::from_raw(m.size, m.size, m.color).ok_or("bad colour buffer")?;
            // seam padding copies the nearest cell into the empty space between
            // cells; outside every cell rectangle the atlas is transparent
            let n = m.size as f32;
            let rects: Vec<[u32; 4]> = spec.cells.iter().map(|c| [(c.uv[0] * n).floor() as u32, (c.uv[1] * n).floor() as u32, (c.uv[2] * n).ceil() as u32, (c.uv[3] * n).ceil() as u32]).collect();
            for (x, y, p) in img.enumerate_pixels_mut() {
                if !rects.iter().any(|r| x >= r[0] && x < r[2] && y >= r[1] && y < r[3]) {
                    p[3] = 0;
                }
            }
            let p = dir.join(format!("{name}_BaseColorAlpha.png"));
            img.save(&p).map_err(|e| format!("couldn't write {}: {e}", p.display()))?;
            files.push(p.to_string_lossy().to_string());
        }
        Ok(files)
    }
}
