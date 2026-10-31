//! Geometric curvature for the curvature bake.
//!
//! Texture-space curvature (differentiating a baked normal map) breaks down
//! exactly where wear matters most: hard edges, which are almost always UV
//! seams. Instead we measure curvature on the mesh itself:
//!
//! * **Edge convexity**: positions are welded (so UV and normal splits don't
//!   hide adjacency), and every edge shared by two triangles gets the signed
//!   dihedral angle between them, positive = convex.
//! * **Vertex curvature**: the mean convexity of a vertex's edges, for smooth,
//!   dense meshes where individual edges are nearly flat.
//!
//! The baker rasterises each triangle in UV space, and for each texel adds the
//! edge convexity faded by the texel's distance to that edge (from barycentrics
//! and triangle heights), plus the interpolated vertex curvature. The result
//! is crisp wear lines on hard-surface models without any seams.

use crate::mesh::Mesh;
use glam::Vec3;
use std::collections::HashMap;

pub struct CurvatureData {
    /// Per triangle, convexity of the edge opposite each corner, in -1..1
    /// (dihedral angle / pi, signed).
    pub edge_convexity: Vec<[f32; 3]>,
    /// Per triangle, the distance from each corner to its opposite edge.
    pub heights: Vec<[f32; 3]>,
    /// Per (unwelded) vertex, mean convexity of adjacent edges.
    pub vertex: Vec<f32>,
}

/// Map each vertex to a welded id by quantised position.
pub fn weld(mesh: &Mesh) -> Vec<u32> {
    let (_, r) = mesh.bounding_sphere();
    let q = 1e5 / r.max(1e-6);
    let mut map: HashMap<[i64; 3], u32> = HashMap::new();
    mesh.vertices
        .iter()
        .map(|v| {
            let key = v.position.map(|c| (c * q).round() as i64);
            let n = map.len() as u32;
            *map.entry(key).or_insert(n)
        })
        .collect()
}

pub fn compute(mesh: &Mesh) -> CurvatureData {
    let welded = weld(mesh);
    let tris = mesh.indices.len() / 3;
    let pos = |i: u32| Vec3::from(mesh.vertices[i as usize].position);
    let mut face_n = Vec::with_capacity(tris);
    let mut centroid = Vec::with_capacity(tris);
    let mut heights = Vec::with_capacity(tris);
    for t in mesh.indices.chunks_exact(3) {
        let (a, b, c) = (pos(t[0]), pos(t[1]), pos(t[2]));
        let cr = (b - a).cross(c - a);
        let area2 = cr.length();
        face_n.push(cr.normalize_or_zero());
        centroid.push((a + b + c) / 3.0);
        let p = [a, b, c];
        heights.push([0, 1, 2].map(|k| {
            let len = (p[(k + 2) % 3] - p[(k + 1) % 3]).length();
            if len > 1e-12 { area2 / len } else { 0.0 }
        }));
    }

    // edge (welded, sorted) -> (triangle, local edge index)
    let mut edges: HashMap<(u32, u32), Vec<(usize, usize)>> = HashMap::new();
    for (t, tri) in mesh.indices.chunks_exact(3).enumerate() {
        for k in 0..3 {
            let a = welded[tri[(k + 1) % 3] as usize];
            let b = welded[tri[(k + 2) % 3] as usize];
            if a != b {
                edges.entry((a.min(b), a.max(b))).or_default().push((t, k));
            }
        }
    }

    let mut edge_convexity = vec![[0.0f32; 3]; tris];
    let welded_count = welded.iter().copied().max().map_or(0, |m| m as usize + 1);
    let mut vsum = vec![0.0f32; welded_count];
    let mut vcnt = vec![0u32; welded_count];
    for ((a, b), users) in &edges {
        if users.len() != 2 {
            continue; // open border or non-manifold: no meaningful dihedral
        }
        let (ta, ka) = users[0];
        let (tb, kb) = users[1];
        let (na, nb) = (face_n[ta], face_n[tb]);
        // atan2 stays accurate near 0, where acos(dot) amplifies rounding error
        let angle = na.cross(nb).length().atan2(na.dot(nb)) / std::f32::consts::PI;
        let convex = (centroid[tb] - centroid[ta]).dot(na) <= 0.0;
        let v = if convex { angle } else { -angle };
        edge_convexity[ta][ka] = v;
        edge_convexity[tb][kb] = v;
        for w in [*a, *b] {
            vsum[w as usize] += v;
            vcnt[w as usize] += 1;
        }
    }
    let vertex = welded.iter().map(|&w| if vcnt[w as usize] > 0 { vsum[w as usize] / vcnt[w as usize] as f32 } else { 0.0 }).collect();
    CurvatureData { edge_convexity, heights, vertex }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::Vertex;

    fn v(p: [f32; 3]) -> Vertex {
        Vertex { position: p, ..Default::default() }
    }

    /// A cube with every face's vertices split (like a hard-edged, UV-unwrapped asset).
    fn split_cube() -> Mesh {
        let faces: [[[f32; 3]; 4]; 6] = [
            [[0., 0., 1.], [1., 0., 1.], [1., 1., 1.], [0., 1., 1.]],
            [[1., 0., 0.], [0., 0., 0.], [0., 1., 0.], [1., 1., 0.]],
            [[1., 0., 1.], [1., 0., 0.], [1., 1., 0.], [1., 1., 1.]],
            [[0., 0., 0.], [0., 0., 1.], [0., 1., 1.], [0., 1., 0.]],
            [[0., 1., 1.], [1., 1., 1.], [1., 1., 0.], [0., 1., 0.]],
            [[0., 0., 0.], [1., 0., 0.], [1., 0., 1.], [0., 0., 1.]],
        ];
        let mut m = Mesh::default();
        for f in faces {
            let base = m.vertices.len() as u32;
            m.vertices.extend(f.iter().map(|p| v(*p)));
            m.indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        }
        m
    }

    #[test]
    fn welding_merges_split_corners() {
        let m = split_cube();
        let w = weld(&m);
        assert_eq!(w.iter().copied().max().unwrap() + 1, 8);
    }

    #[test]
    fn cube_edges_are_convex_right_angles_and_diagonals_flat() {
        let m = split_cube();
        let c = compute(&m);
        let mut convex = 0;
        let mut flat = 0;
        for e in c.edge_convexity.iter().flatten() {
            if (e - 0.5).abs() < 1e-4 {
                convex += 1;
            } else if e.abs() < 1e-4 {
                flat += 1;
            } else {
                panic!("unexpected convexity {e}");
            }
        }
        // 12 cube edges, each seen from 2 triangles; 6 face diagonals, each from 2 triangles
        assert_eq!(convex, 24);
        assert_eq!(flat, 12);
        assert!(c.vertex.iter().all(|&x| x > 0.0));
    }

    #[test]
    fn valley_fold_is_concave() {
        // two quads folded upward along x = 0 (a V shape opening toward +y)
        let mut m = Mesh::default();
        m.vertices = vec![
            v([0., 0., 0.]), v([0., 0., 1.]), v([1., 1., 1.]), v([1., 1., 0.]),
            v([-1., 1., 0.]), v([-1., 1., 1.]),
        ];
        // normals point up (+y-ish) on both sides
        m.indices = vec![0, 1, 2, 0, 2, 3, 0, 4, 5, 0, 5, 1];
        let c = compute(&m);
        let fold: Vec<f32> = c.edge_convexity.iter().flatten().copied().filter(|e| e.abs() > 1e-4).collect();
        assert!(!fold.is_empty());
        assert!(fold.iter().all(|&e| e < 0.0), "{fold:?}");
    }

    #[test]
    fn heights_of_right_triangle() {
        let mut m = Mesh::default();
        m.vertices = vec![v([0., 0., 0.]), v([2., 0., 0.]), v([0., 2., 0.])];
        m.indices = vec![0, 1, 2];
        let c = compute(&m);
        let h = c.heights[0];
        assert!((h[0] - 2f32.sqrt()).abs() < 1e-5); // corner 0 to hypotenuse
        assert!((h[1] - 2.0).abs() < 1e-5);
        assert!((h[2] - 2.0).abs() < 1e-5);
    }
}
