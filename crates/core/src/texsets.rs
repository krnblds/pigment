//! Texture sets and UDIM tiles.
//!
//! A project can have several **texture sets**. Each paints part of the
//! mesh: some of its materials, and / or one UDIM tile. Each set has its own
//! resolution, layer stack (a `Document`) and GPU textures. A set's sub-mesh
//! keeps only its triangles, with UVs moved into 0..1 (its tile).
//!
//! **UDIM tiles**: UVs beyond 0..1 address tile `1001 + u + 10 v`, with u and
//! v measured OpenGL-style (v up). Pigment's UVs are glTF-style (v down), so
//! v_up = 1 - v.
//!
//! Old single-set projects have no `texture_set` and load as one set: all
//! materials, tile 1001.

use crate::{Mesh, Vertex};
use glam::Vec2;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// Which part of the mesh a texture set paints.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct SetSpec {
    pub name: String,
    /// Material indices (empty = every material).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub materials: Vec<u32>,
    /// UDIM tile (1001...); None = every tile (UVs wrapped into 0..1).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub udim: Option<u32>,
}

impl SetSpec {
    pub fn all(name: &str) -> Self {
        SetSpec { name: name.into(), materials: Vec::new(), udim: None }
    }
    /// The tile this set exports as (1001 when not split by tile).
    pub fn tile(&self) -> u32 {
        self.udim.unwrap_or(1001)
    }
    pub fn covers(&self, material: u32, tile: u32) -> bool {
        (self.materials.is_empty() || self.materials.contains(&material)) && self.udim.is_none_or(|t| t == tile)
    }
}

/// UDIM tile of a UV (glTF convention, v down).
pub fn udim_of(uv: Vec2) -> u32 {
    let u = uv.x.floor().clamp(0.0, 9.0) as u32;
    let v = (1.0 - uv.y).floor().max(0.0) as u32;
    1001 + u + 10 * v
}

/// Offset that moves UVs of `tile` into 0..1 (add it).
pub fn tile_shift(tile: u32) -> Vec2 {
    let k = tile.saturating_sub(1001);
    Vec2::new(-((k % 10) as f32), (k / 10) as f32)
}

/// Tile of a triangle (its UV centroid).
pub fn tri_tile(mesh: &Mesh, t: usize) -> u32 {
    let c = (0..3).map(|k| Vec2::from(mesh.vertices[mesh.indices[t * 3 + k] as usize].uv)).sum::<Vec2>() / 3.0;
    udim_of(c)
}

/// UDIM tiles the mesh uses.
pub fn mesh_tiles(mesh: &Mesh) -> BTreeSet<u32> {
    (0..mesh.triangle_count()).map(|t| tri_tile(mesh, t)).collect()
}

/// One set per material (named after the materials), or a single set.
pub fn sets_by_material(mesh: &Mesh) -> Vec<SetSpec> {
    let n = mesh.material_count();
    if n <= 1 {
        return vec![SetSpec::all("main")];
    }
    let used: BTreeSet<u32> = (0..mesh.triangle_count()).map(|t| mesh.material_of(t)).collect();
    used.into_iter().map(|m| SetSpec { name: sanitize(&mesh.material_name(m)), materials: vec![m], udim: None }).collect()
}

/// One set per UDIM tile the mesh uses.
pub fn sets_by_tile(mesh: &Mesh, base: &str) -> Vec<SetSpec> {
    mesh_tiles(mesh).into_iter().map(|t| SetSpec { name: format!("{base}_{t}"), materials: Vec::new(), udim: Some(t) }).collect()
}

/// A safe file-name token.
pub fn sanitize(s: &str) -> String {
    let t: String = s.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
    if t.is_empty() {
        "set".into()
    } else {
        t
    }
}

/// The triangles of `spec`, with UVs moved into 0..1. Materials, names and
/// colours are carried over. Returns the sub-mesh and, per sub-mesh triangle,
/// its index in `mesh`.
pub fn submesh(mesh: &Mesh, spec: &SetSpec) -> (Mesh, Vec<u32>) {
    let mut out = Mesh { name: mesh.name.clone(), has_uvs: mesh.has_uvs, material_names: mesh.material_names.clone(), ..Default::default() };
    let mut remap = vec![u32::MAX; mesh.vertices.len()];
    let mut tri_map = Vec::new();
    let has_mat = !mesh.tri_material.is_empty();
    // keep the whole mesh's part ids (part masks name them)
    let full_parts = mesh.parts().triangle_part;
    for t in 0..mesh.triangle_count() {
        let tile = tri_tile(mesh, t);
        if !spec.covers(mesh.material_of(t), tile) {
            continue;
        }
        // UVs into this triangle's tile (UV-wrapped sets keep each triangle's own tile)
        let shift = tile_shift(tile);
        for k in 0..3 {
            let vi = mesh.indices[t * 3 + k] as usize;
            if remap[vi] == u32::MAX {
                let mut v: Vertex = mesh.vertices[vi];
                v.uv = (Vec2::from(v.uv) + shift).into();
                remap[vi] = out.vertices.len() as u32;
                out.vertices.push(v);
                if !mesh.colors.is_empty() {
                    out.colors.push(mesh.colors[vi]);
                }
            }
            out.indices.push(remap[vi]);
        }
        if has_mat {
            out.tri_material.push(mesh.material_of(t));
        }
        out.tri_part.push(full_parts[t]);
        tri_map.push(t as u32);
    }
    (out, tri_map)
}

/// Move triangles `select` to UDIM `tile`, repacking their UV islands to
/// fill it: islands (triangles connected through shared vertices) keep their
/// shape and are shelf-packed at the largest uniform scale that fits, with
/// `margin` padding. Vertices shared with triangles that stay are split.
/// Returns the texel density gain (the scale).
pub fn move_to_tile(mesh: &mut Mesh, select: &[bool], tile: u32, margin: f32) -> f32 {
    let n = mesh.triangle_count();
    let picked: Vec<usize> = (0..n).filter(|t| select.get(*t).copied().unwrap_or(false)).collect();
    if picked.is_empty() {
        return 1.0;
    }
    // islands: union-find over picked triangles sharing a vertex index
    let mut parent: Vec<usize> = (0..picked.len()).collect();
    fn find(p: &mut [usize], x: usize) -> usize {
        let mut r = x;
        while p[r] != r {
            p[r] = p[p[r]];
            r = p[r];
        }
        r
    }
    let mut owner: std::collections::HashMap<u32, usize> = std::collections::HashMap::new();
    for (k, &t) in picked.iter().enumerate() {
        for c in 0..3 {
            let vi = mesh.indices[t * 3 + c];
            match owner.get(&vi) {
                Some(&o) => {
                    let (a, b) = (find(&mut parent, o), find(&mut parent, k));
                    parent[a] = b;
                }
                None => {
                    owner.insert(vi, k);
                }
            }
        }
    }
    let mut groups: std::collections::BTreeMap<usize, Vec<usize>> = std::collections::BTreeMap::new();
    for k in 0..picked.len() {
        let r = find(&mut parent, k);
        groups.entry(r).or_default().push(picked[k]);
    }
    // island bounds in the original UVs
    let islands: Vec<(Vec<usize>, Vec2, Vec2)> = groups
        .into_values()
        .map(|tris| {
            let mut lo = Vec2::splat(f32::MAX);
            let mut hi = Vec2::splat(f32::MIN);
            for &t in &tris {
                for c in 0..3 {
                    let uv = Vec2::from(mesh.vertices[mesh.indices[t * 3 + c] as usize].uv);
                    lo = lo.min(uv);
                    hi = hi.max(uv);
                }
            }
            (tris, lo, hi)
        })
        .collect();
    let mut order: Vec<usize> = (0..islands.len()).collect();
    order.sort_by(|a, b| (islands[*b].2.y - islands[*b].1.y).total_cmp(&(islands[*a].2.y - islands[*a].1.y)));
    // shelf packing at scale s into the unit square; returns positions or None
    let pack = |s: f32| -> Option<Vec<Vec2>> {
        let mut pos = vec![Vec2::ZERO; islands.len()];
        let (mut x, mut y, mut row_h) = (margin, margin, 0.0f32);
        for &i in &order {
            let size = (islands[i].2 - islands[i].1) * s;
            if x + size.x + margin > 1.0 + 1e-6 {
                x = margin;
                y += row_h + margin;
                row_h = 0.0;
            }
            if x + size.x + margin > 1.0 + 1e-6 || y + size.y + margin > 1.0 + 1e-6 {
                return None;
            }
            pos[i] = Vec2::new(x, y);
            x += size.x + margin;
            row_h = row_h.max(size.y);
        }
        Some(pos)
    };
    let (mut lo_s, mut hi_s) = (1e-4f32, 1e4f32);
    for _ in 0..40 {
        let mid = (lo_s * hi_s).sqrt();
        if pack(mid).is_some() {
            lo_s = mid;
        } else {
            hi_s = mid;
        }
    }
    let scale = lo_s;
    let pos = pack(scale).unwrap_or_else(|| vec![Vec2::splat(margin); islands.len()]);
    // the tile's 0..1 square in Pigment's (v down) UVs
    let shift = -tile_shift(tile);
    let mut copy = vec![u32::MAX; mesh.vertices.len()];
    for (i, (tris, lo, _)) in islands.iter().enumerate() {
        for &t in tris {
            for c in 0..3 {
                let vi = mesh.indices[t * 3 + c] as usize;
                if copy[vi] == u32::MAX {
                    let mut v = mesh.vertices[vi];
                    let uv = (Vec2::from(v.uv) - *lo) * scale + pos[i];
                    v.uv = (uv + shift).into();
                    copy[vi] = mesh.vertices.len() as u32;
                    mesh.vertices.push(v);
                    if !mesh.colors.is_empty() {
                        let col = mesh.colors[vi];
                        mesh.colors.push(col);
                    }
                }
                mesh.indices[t * 3 + c] = copy[vi];
            }
        }
    }
    scale
}

/// A recorded `move_to_tile`, so a project can rebuild its UDIM layout from
/// the original mesh file (triangle ranges keep the record small).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct UdimMove {
    pub tile: u32,
    /// Inclusive triangle index ranges [first, last].
    pub triangles: Vec<[u32; 2]>,
    #[serde(default)]
    pub margin: f32,
}

impl UdimMove {
    pub fn from_selection(tile: u32, select: &[bool], margin: f32) -> Self {
        let mut triangles: Vec<[u32; 2]> = Vec::new();
        for (t, on) in select.iter().enumerate() {
            if !*on {
                continue;
            }
            match triangles.last_mut() {
                Some(r) if r[1] + 1 == t as u32 => r[1] = t as u32,
                _ => triangles.push([t as u32, t as u32]),
            }
        }
        UdimMove { tile, triangles, margin }
    }
    pub fn selection(&self, n: usize) -> Vec<bool> {
        let mut s = vec![false; n];
        for r in &self.triangles {
            for t in r[0]..=r[1].min(n.saturating_sub(1) as u32) {
                s[t as usize] = true;
            }
        }
        s
    }
}

/// Re-apply recorded tile moves to a freshly loaded mesh.
pub fn apply_moves(mesh: &mut Mesh, moves: &[UdimMove]) {
    for m in moves {
        let sel = m.selection(mesh.triangle_count());
        move_to_tile(mesh, &sel, m.tile, m.margin);
    }
}

/// Export file name: `<name>_<set>_<map>.<udim>.png`.
pub fn export_file(name: &str, set: &str, map: &str, udim: u32) -> String {
    format!("{name}_{set}_{map}.{udim}.png")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn udim_numbers() {
        assert_eq!(udim_of(Vec2::new(0.5, 0.5)), 1001);
        assert_eq!(udim_of(Vec2::new(1.5, 0.5)), 1002);
        // v down: v in -1..0 is the row above (OpenGL v 1..2)
        assert_eq!(udim_of(Vec2::new(0.5, -0.5)), 1011);
        assert_eq!(udim_of(Vec2::new(2.2, -1.5)), 1023);
        assert_eq!(tile_shift(1002), Vec2::new(-1.0, 0.0));
        assert_eq!(tile_shift(1011), Vec2::new(0.0, 1.0));
        assert_eq!(udim_of(Vec2::new(0.5, -0.5) + tile_shift(1011)), 1001);
    }

    #[test]
    fn sets_split_by_material_and_tile() {
        let (_, high) = crate::hibake::test_pair();
        let sets = sets_by_material(&high);
        assert_eq!(sets.len(), 3);
        assert_eq!(sets[1].name, "lid");
        let total: usize = sets.iter().map(|s| submesh(&high, s).0.triangle_count()).sum();
        assert_eq!(total, high.triangle_count(), "every triangle in exactly one set");
        // move the top half of a box to tile 1002: density gain and two tile sets
        let (mut low, _) = crate::hibake::test_pair();
        let sel: Vec<bool> = low.indices.chunks_exact(3).map(|t| t.iter().map(|&i| low.vertices[i as usize].position[1]).sum::<f32>() > 0.0).collect();
        let gain = move_to_tile(&mut low, &sel, 1002, 0.01);
        assert!(gain > 1.2, "island repacking gains density ({gain})");
        assert_eq!(mesh_tiles(&low).into_iter().collect::<Vec<_>>(), vec![1001, 1002]);
        let sets = sets_by_tile(&low, "box");
        assert_eq!(sets.len(), 2);
        let (sub, map) = submesh(&low, &sets[1]);
        assert_eq!(sub.triangle_count(), sel.iter().filter(|x| **x).count());
        assert_eq!(map.len(), sub.triangle_count());
        assert!(sub.vertices.iter().all(|v| (0.0..=1.0).contains(&v.uv[0]) && (0.0..=1.0).contains(&v.uv[1])), "moved into 0..1");
        assert_eq!(export_file("bld", "main", "BaseColor", 1002), "bld_main_BaseColor.1002.png");
        let rec = UdimMove::from_selection(1002, &sel, 0.01);
        assert_eq!(rec.selection(sel.len()), sel);
    }

    #[test]
    fn old_projects_have_no_set() {
        let d = crate::Document::demo();
        let json = serde_json::to_string(&d).unwrap();
        assert!(!json.contains("texture_set"));
        let back: crate::Document = serde_json::from_str(&json).unwrap();
        assert!(back.texture_set.is_none() && back.extra_sets.is_empty());
    }
}
