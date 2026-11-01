//! Flat "sheet" projects: seamless tiles, trim sheets and decal atlases.
//!
//! All three are a flat plane in world XZ (normal +Y, y = 0) whose UVs fill
//! the texture, so generators work in true metres:
//!
//! - **tile**: one cell over the whole texture that wraps on both axes. The
//!   texture repeats seamlessly: strokes and decals that cross an edge come
//!   back in on the other side, generator noise is periodic over the tile and
//!   the height-to-normal pass wraps.
//! - **trim**: horizontal strips stacked in V (curb top, curb face, gutter...),
//!   each its own mesh part (so a part mask or the strip's folder limits a
//!   material to it), wrapping along U only.
//! - **atlas**: cells packed into the texture with padding (decals), not
//!   wrapping; each cell is a part.
//!
//! UV convention: u right, v down (texture rows), as everywhere in Pigment.
//! World: x = (u - 0.5) * width, z = (v - 0.5) * height.

use crate::mesh::{Mesh, Vertex};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SheetKind {
    #[default]
    Tile,
    Trim,
    Atlas,
}

impl SheetKind {
    pub fn id(self) -> &'static str {
        match self {
            SheetKind::Tile => "tile",
            SheetKind::Trim => "trim",
            SheetKind::Atlas => "atlas",
        }
    }
}

/// One rectangle of the sheet: a trim strip or an atlas cell.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SheetCell {
    pub name: String,
    /// u0, v0, u1, v1 (v down).
    pub uv: [f32; 4],
}

/// Stored in the document of a flat-sheet project.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TileSpec {
    /// World size of the whole sheet in metres (x, z).
    pub size_m: [f32; 2],
    /// Wrap along u (x) and v (z).
    #[serde(default = "both")]
    pub wrap: [bool; 2],
    #[serde(default)]
    pub kind: SheetKind,
    /// Strips / atlas cells; one part each, in order. Empty for a plain tile.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cells: Vec<SheetCell>,
    /// World position of the sheet's centre (x, z). Moving a seamless tile
    /// by part of its period scrolls the pattern (used to prove periodicity).
    #[serde(default, skip_serializing_if = "is_zero2")]
    pub offset_m: [f32; 2],
}

fn is_zero2(v: &[f32; 2]) -> bool {
    *v == [0.0, 0.0]
}

fn both() -> [bool; 2] {
    [true, true]
}

/// Grid quads per metre-ish: enough for tight dirty-tile tracking.
const GRID: f32 = 32.0;

impl TileSpec {
    /// A seamless tile of `w x h` metres.
    pub fn tile(w: f32, h: f32) -> TileSpec {
        TileSpec { size_m: [w, h], wrap: [true, true], kind: SheetKind::Tile, cells: vec![], offset_m: [0.0; 2] }
    }

    /// A trim sheet `width` metres wide: strips (name, height in metres)
    /// stacked from the top of the texture (v = 0) down. Wraps along U.
    pub fn trim(width: f32, strips: &[(String, f32)]) -> Result<TileSpec, String> {
        if strips.is_empty() {
            return Err("a trim sheet needs at least one strip".into());
        }
        if let Some((n, _)) = strips.iter().find(|(_, h)| !(*h > 0.0)) {
            return Err(format!("strip `{n}`: height_m must be > 0"));
        }
        let total: f32 = strips.iter().map(|s| s.1).sum();
        let mut v = 0.0;
        let cells = strips
            .iter()
            .map(|(name, h)| {
                let v0 = v / total;
                v += h;
                SheetCell { name: name.clone(), uv: [0.0, v0, 1.0, v / total] }
            })
            .collect();
        Ok(TileSpec { size_m: [width, total], wrap: [true, false], kind: SheetKind::Trim, cells, offset_m: [0.0; 2] })
    }

    /// A decal atlas: cells (name, [w, h] metres) shelf-packed into a square
    /// sheet with `pad_px` texels between cells at resolution `res`. The
    /// sheet's world size is chosen so everything fits at one texel density.
    pub fn atlas(cells: &[(String, [f32; 2])], res: u32, pad_px: u32) -> Result<TileSpec, String> {
        if cells.is_empty() {
            return Err("an atlas needs at least one cell".into());
        }
        if let Some((n, _)) = cells.iter().find(|(_, s)| !(s[0] > 0.0 && s[1] > 0.0)) {
            return Err(format!("cell `{n}`: size_m must be > 0"));
        }
        let area: f32 = cells.iter().map(|(_, s)| s[0] * s[1]).sum();
        let widest = cells.iter().map(|(_, s)| s[0].max(s[1])).fold(0.0, f32::max);
        let pad = pad_px as f32 / res as f32;
        let mut side = area.sqrt().max(widest);
        for _ in 0..400 {
            if let Some(rects) = shelf_pack(cells, side, pad) {
                let cells = cells.iter().zip(rects).map(|((n, _), uv)| SheetCell { name: n.clone(), uv }).collect();
                return Ok(TileSpec { size_m: [side, side], wrap: [false, false], kind: SheetKind::Atlas, cells, offset_m: [0.0; 2] });
            }
            side *= 1.02;
        }
        Err("couldn't pack the atlas cells".into())
    }

    /// World period on x and z (0 = that axis doesn't wrap).
    pub fn period(&self) -> [f32; 2] {
        [if self.wrap[0] { self.size_m[0] } else { 0.0 }, if self.wrap[1] { self.size_m[1] } else { 0.0 }]
    }

    fn cells_or_whole(&self) -> Vec<SheetCell> {
        if self.cells.is_empty() {
            vec![SheetCell { name: "tile".into(), uv: [0.0, 0.0, 1.0, 1.0] }]
        } else {
            self.cells.clone()
        }
    }

    pub fn world_of(&self, u: f32, v: f32) -> [f32; 3] {
        [(u - 0.5) * self.size_m[0] + self.offset_m[0], 0.0, (v - 0.5) * self.size_m[1] + self.offset_m[1]]
    }

    /// World rectangle of a cell: [x0, z0, x1, z1].
    pub fn cell_world(&self, c: &SheetCell) -> [f32; 4] {
        let a = self.world_of(c.uv[0], c.uv[1]);
        let b = self.world_of(c.uv[2], c.uv[3]);
        [a[0], a[2], b[0], b[2]]
    }

    /// The plane: one grid per cell, each its own part (neighbouring strips
    /// get different column counts so no edge is shared and they stay
    /// separate parts).
    pub fn mesh(&self) -> Mesh {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        for (k, c) in self.cells_or_whole().iter().enumerate() {
            let [u0, v0, u1, v1] = c.uv;
            let nx = ((GRID * (u1 - u0)).round() as u32).max(1) + (k as u32 % 2);
            let ny = ((GRID * (v1 - v0)).round() as u32).max(1);
            let base = vertices.len() as u32;
            for j in 0..=ny {
                for i in 0..=nx {
                    let u = u0 + (u1 - u0) * i as f32 / nx as f32;
                    let v = v0 + (v1 - v0) * j as f32 / ny as f32;
                    vertices.push(Vertex { position: self.world_of(u, v), normal: [0.0, 1.0, 0.0], uv: [u, v], tangent: [0.0; 4] });
                }
            }
            let row = nx + 1;
            for j in 0..ny {
                for i in 0..nx {
                    let a = base + j * row + i;
                    let (b, c, d) = (a + 1, a + row + 1, a + row);
                    // counter-clockwise seen from +Y
                    indices.extend_from_slice(&[a, c, b, a, d, c]);
                }
            }
        }
        let name = match self.kind {
            SheetKind::Tile => format!("Tile{}x{}m", self.size_m[0], self.size_m[1]),
            SheetKind::Trim => "TrimSheet".to_string(),
            SheetKind::Atlas => "DecalAtlas".to_string(),
        };
        let mut m = Mesh { name, vertices, indices, has_uvs: true };
        m.compute_tangents();
        m
    }

    /// The painting mesh: `mesh` plus copies shifted by one period on each
    /// wrapping axis (the original first), all with the same UVs. Strokes and
    /// decals rasterised with it land on both sides of a wrapped edge.
    pub fn wrap_mesh(&self, mesh: &Mesh) -> Mesh {
        let [px, pz] = self.period();
        let xs: Vec<f32> = if px > 0.0 { vec![0.0, -px, px] } else { vec![0.0] };
        let zs: Vec<f32> = if pz > 0.0 { vec![0.0, -pz, pz] } else { vec![0.0] };
        let mut out = Mesh { name: mesh.name.clone(), vertices: Vec::new(), indices: Vec::new(), has_uvs: mesh.has_uvs };
        for &dz in &zs {
            for &dx in &xs {
                let base = out.vertices.len() as u32;
                out.vertices.extend(mesh.vertices.iter().map(|v| {
                    let mut v = *v;
                    v.position[0] += dx;
                    v.position[2] += dz;
                    v
                }));
                out.indices.extend(mesh.indices.iter().map(|i| i + base));
            }
        }
        out
    }

    /// How many copies `wrap_mesh` makes.
    pub fn copies(&self) -> usize {
        let [px, pz] = self.period();
        (if px > 0.0 { 3 } else { 1 }) * (if pz > 0.0 { 3 } else { 1 })
    }

    /// Layout description written next to the exported maps.
    pub fn layout_json(&self, name: &str, res: u32) -> serde_json::Value {
        let cells: Vec<serde_json::Value> = self
            .cells_or_whole()
            .iter()
            .enumerate()
            .map(|(i, c)| {
                let [u0, v0, u1, v1] = c.uv;
                serde_json::json!({
                    "name": c.name, "part": i,
                    "uv": [u0, v0, u1, v1],
                    // Blender / OpenGL UVs have v up from the bottom of the image
                    "uv_gl": [u0, 1.0 - v1, u1, 1.0 - v0],
                    "px": [(u0 * res as f32).round(), (v0 * res as f32).round(), (u1 * res as f32).round(), (v1 * res as f32).round()],
                    "size_m": [(u1 - u0) * self.size_m[0], (v1 - v0) * self.size_m[1]],
                })
            })
            .collect();
        serde_json::json!({
            "name": name, "kind": self.kind.id(), "size_m": self.size_m, "wrap": { "u": self.wrap[0], "v": self.wrap[1] },
            "resolution": res, "texels_per_m": [res as f32 / self.size_m[0], res as f32 / self.size_m[1]],
            "v_down": true,
            "cells": cells,
        })
    }
}

/// Shelf packing in UV units of a square sheet `side` metres wide.
fn shelf_pack(cells: &[(String, [f32; 2])], side: f32, pad: f32) -> Option<Vec<[f32; 4]>> {
    let mut order: Vec<usize> = (0..cells.len()).collect();
    order.sort_by(|&a, &b| cells[b].1[1].total_cmp(&cells[a].1[1]).then(a.cmp(&b)));
    let mut out = vec![[0.0; 4]; cells.len()];
    let (mut x, mut y, mut shelf) = (pad, pad, 0.0f32);
    for i in order {
        let (w, h) = (cells[i].1[0] / side, cells[i].1[1] / side);
        if x + w + pad > 1.0 {
            x = pad;
            y += shelf + pad;
            shelf = 0.0;
        }
        if x + w + pad > 1.0 || y + h + pad > 1.0 {
            return None;
        }
        out[i] = [x, y, x + w, y + h];
        x += w + pad;
        shelf = shelf.max(h);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tile_plane_fills_the_uv_square_in_metres() {
        let t = TileSpec::tile(4.0, 2.0);
        let m = t.mesh();
        let (lo, hi) = m.bounds();
        assert!((lo.x + 2.0).abs() < 1e-5 && (hi.x - 2.0).abs() < 1e-5);
        assert!((lo.z + 1.0).abs() < 1e-5 && (hi.z - 1.0).abs() < 1e-5);
        assert_eq!(m.parts().info.len(), 1);
        // faces point up
        let t0 = &m.indices[0..3];
        let p = |i: u32| glam::Vec3::from(m.vertices[i as usize].position);
        assert!((p(t0[1]) - p(t0[0])).cross(p(t0[2]) - p(t0[0])).y > 0.0);
        let w = t.wrap_mesh(&m);
        assert_eq!(t.copies(), 9);
        assert_eq!(w.indices.len(), m.indices.len() * 9);
        // the original comes first
        assert_eq!(&w.vertices[..m.vertices.len()].iter().map(|v| v.position).collect::<Vec<_>>(), &m.vertices.iter().map(|v| v.position).collect::<Vec<_>>());
    }

    #[test]
    fn trim_strips_are_separate_parts_in_order() {
        let t = TileSpec::trim(2.0, &[("curb top".into(), 0.3), ("curb face".into(), 0.2), ("gutter".into(), 0.5)]).unwrap();
        assert_eq!(t.size_m, [2.0, 1.0]);
        assert_eq!(t.wrap, [true, false]);
        assert_eq!(t.copies(), 3);
        assert!((t.cells[1].uv[1] - 0.3).abs() < 1e-6 && (t.cells[1].uv[3] - 0.5).abs() < 1e-6);
        let m = t.mesh();
        let parts = m.parts();
        assert_eq!(parts.info.len(), 3);
        // part k is strip k: its z range matches the strip
        for (k, c) in t.cells.iter().enumerate() {
            let w = t.cell_world(c);
            assert!((parts.info[k].min[2] - w[1]).abs() < 1e-5 && (parts.info[k].max[2] - w[3]).abs() < 1e-5, "strip {k}");
        }
        let j = t.layout_json("road_trim", 2048);
        assert_eq!(j["cells"][2]["name"], "gutter");
        assert!((j["cells"][0]["uv_gl"][3].as_f64().unwrap() - 1.0).abs() < 1e-6);
        assert!(TileSpec::trim(1.0, &[]).is_err());
        assert!(TileSpec::trim(1.0, &[("x".into(), 0.0)]).is_err());
    }

    #[test]
    fn atlas_cells_do_not_overlap_and_keep_their_aspect() {
        let cells: Vec<(String, [f32; 2])> = (0..9).map(|i| (format!("c{i}"), [0.5 + 0.1 * i as f32, 0.4 + 0.05 * (i % 3) as f32])).collect();
        let t = TileSpec::atlas(&cells, 2048, 8).unwrap();
        assert_eq!(t.cells.len(), 9);
        let pad = 8.0 / 2048.0;
        for (i, a) in t.cells.iter().enumerate() {
            let [u0, v0, u1, v1] = a.uv;
            assert!(u0 >= pad - 1e-6 && v0 >= pad - 1e-6 && u1 <= 1.0 && v1 <= 1.0);
            let sz = [(u1 - u0) * t.size_m[0], (v1 - v0) * t.size_m[1]];
            assert!((sz[0] - cells[i].1[0]).abs() < 1e-4 && (sz[1] - cells[i].1[1]).abs() < 1e-4);
            for b in &t.cells[i + 1..] {
                let apart = a.uv[2] + pad * 0.99 <= b.uv[0] || b.uv[2] + pad * 0.99 <= a.uv[0] || a.uv[3] + pad * 0.99 <= b.uv[1] || b.uv[3] + pad * 0.99 <= a.uv[1];
                assert!(apart, "{} overlaps {}", a.name, b.name);
            }
        }
        assert_eq!(t.mesh().parts().info.len(), 9);
        assert_eq!(t.copies(), 1);
        // tightly packed: at least 45 % of the sheet is used
        let used: f32 = cells.iter().map(|c| c.1[0] * c.1[1]).sum();
        assert!(used / (t.size_m[0] * t.size_m[1]) > 0.45);
    }

    #[test]
    fn spec_round_trips_and_defaults() {
        let t = TileSpec::trim(2.0, &[("a".into(), 1.0)]).unwrap();
        let s = serde_json::to_string(&t).unwrap();
        assert_eq!(serde_json::from_str::<TileSpec>(&s).unwrap(), t);
        let d: TileSpec = serde_json::from_str(r#"{"size_m": [4, 4]}"#).unwrap();
        assert_eq!(d, TileSpec::tile(4.0, 4.0));
    }
}
