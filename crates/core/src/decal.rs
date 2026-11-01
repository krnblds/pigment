//! World-space decals: placing an image at a chosen spot on a surface, and
//! scattering many of them under constraints. GPU-free (the projection
//! itself is `decal_box.wgsl`).
//!
//! A decal is an oriented box: a centre on the surface, the surface normal,
//! `right` / `up` axes in the surface plane and a size in metres. Every texel
//! whose world position falls inside the box (and whose normal faces the
//! decal) takes the image. Unlike the camera-projected decal it doesn't need
//! a view, so it is exact, repeatable and the same at any texture resolution.

use crate::mesh::{Mesh, Parts};
use crate::tiles::TileSet;
use glam::{Vec2, Vec3};

/// An image stuck onto the surface.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Placement {
    pub center: Vec3,
    /// Out of the surface.
    pub normal: Vec3,
    /// Image +x direction (unit).
    pub right: Vec3,
    /// Image up direction (unit; image row 0 is at +up).
    pub up: Vec3,
    /// Full width and height in metres.
    pub size: Vec2,
    /// Half thickness of the projection box (metres along the normal).
    pub depth: f32,
}

impl Placement {
    /// Upright on walls (image up = world up projected onto the surface); on
    /// floors and ceilings image up points to -Z. `rotation` is in degrees,
    /// counter-clockwise as seen from outside.
    pub fn new(center: Vec3, normal: Vec3, size: Vec2, rotation_deg: f32, depth: f32) -> Placement {
        let n = normal.try_normalize().unwrap_or(Vec3::Z);
        let world_up = if n.y.abs() < 0.9 { Vec3::Y } else { Vec3::NEG_Z };
        let up0 = (world_up - n * n.dot(world_up)).normalize();
        let right0 = up0.cross(n);
        let (s, c) = rotation_deg.to_radians().sin_cos();
        Placement { center, normal: n, right: right0 * c + up0 * s, up: up0 * c - right0 * s, size, depth: depth.max(1e-4) }
    }

    /// Default box half-depth for a decal of this size: deep enough to wrap
    /// brick relief, shallow enough not to bleed onto things in front.
    pub fn default_depth(size: Vec2) -> f32 {
        (size.min_element() * 0.25).clamp(0.02, 0.25)
    }

    /// Centre, corners and edge midpoints, used for the fit test.
    pub fn outline(&self) -> [Vec3; 9] {
        let (r, u) = (self.right * self.size.x * 0.5, self.up * self.size.y * 0.5);
        let c = self.center;
        [c, c - r - u, c + r - u, c + r + u, c - r + u, c - u, c + r, c + u, c - r]
    }

    /// Lowest and highest world Y the decal covers.
    pub fn y_range(&self) -> (f32, f32) {
        let ext = (self.right.y * self.size.x * 0.5).abs() + (self.up.y * self.size.y * 0.5).abs();
        (self.center.y - ext, self.center.y + ext)
    }

    /// Whether a world point falls inside the box.
    pub fn contains(&self, p: Vec3) -> bool {
        let d = p - self.center;
        d.dot(self.right).abs() <= self.size.x * 0.5 && d.dot(self.up).abs() <= self.size.y * 0.5 && d.dot(self.normal).abs() <= self.depth
    }

    /// Mark the texture tiles the decal can touch: for each triangle that
    /// overlaps the box, the UV footprint of the decal on that triangle's
    /// plane (UVs are affine over a triangle), clipped to the triangle's own
    /// UV box. Big wall triangles only mark the tiles under the poster.
    /// Returns how many triangles it touches.
    pub fn mark_tiles(&self, mesh: &Mesh, tiles: &mut TileSet) -> usize {
        let (bmin, bmax) = self.aabb();
        let corners: Vec<Vec3> = [(-1.0f32, -1.0f32), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
            .iter()
            .map(|&(a, b)| self.center + self.right * a * self.size.x * 0.5 + self.up * b * self.size.y * 0.5)
            .collect();
        let mut hit = 0;
        for tri in mesh.indices.chunks_exact(3) {
            let v = [0, 1, 2].map(|k| &mesh.vertices[tri[k] as usize]);
            let p = v.map(|v| Vec3::from(v.position));
            let (tmin, tmax) = (p[0].min(p[1]).min(p[2]), p[0].max(p[1]).max(p[2]));
            if tmin.cmpgt(bmax).any() || tmax.cmplt(bmin).any() {
                continue;
            }
            let n = (p[1] - p[0]).cross(p[2] - p[0]);
            let area2 = n.length();
            if area2 < 1e-12 {
                continue;
            }
            let mut n = n / area2;
            // winding can be either way: orient by the shading normals
            let sn: Vec3 = v.iter().map(|v| Vec3::from(v.normal)).sum();
            if sn.dot(n) < 0.0 {
                n = -n;
            }
            // the decal only lands on surfaces roughly facing it (the shader fades the rest)
            if n.dot(self.normal) < 0.05 {
                continue;
            }
            // the triangle's plane must pass through the box
            let dist = (self.center - p[0]).dot(n);
            let reach = self.depth + (self.size.x * self.right.dot(n).abs() + self.size.y * self.up.dot(n).abs()) * 0.5;
            if dist.abs() > reach + 1e-4 {
                continue;
            }
            let uv = v.map(|v| Vec2::from(v.uv));
            let (tuv_min, tuv_max) = (uv[0].min(uv[1]).min(uv[2]), uv[0].max(uv[1]).max(uv[2]));
            // footprint: decal corners pushed along the decal normal onto the triangle plane
            let (mut lo, mut hi) = (Vec2::splat(f32::MAX), Vec2::splat(f32::MIN));
            let denom = self.normal.dot(n);
            for c in &corners {
                let q = if denom.abs() > 0.2 { *c + self.normal * ((p[0] - *c).dot(n) / denom) } else { *c - n * (*c - p[0]).dot(n) };
                let w = barycentric(q, p[0], p[1], p[2]);
                let t = uv[0] * w.x + uv[1] * w.y + uv[2] * w.z;
                lo = lo.min(t);
                hi = hi.max(t);
            }
            let (lo, hi) = (lo.max(tuv_min), hi.min(tuv_max));
            if lo.x > hi.x || lo.y > hi.y {
                continue;
            }
            // a little slack for bilinear filtering and conservative raster
            let pad = Vec2::splat(1.0 / 1024.0);
            tiles.mark_uv_rect(lo - pad, hi + pad);
            hit += 1;
        }
        hit
    }

    /// Size of the decal in UV space (0..1 units) on the surface under its
    /// centre: times the texture resolution, how many texels it gets across.
    /// None if no triangle lies under the centre.
    pub fn uv_size(&self, mesh: &Mesh) -> Option<Vec2> {
        let mut best: Option<(f32, Vec2)> = None;
        for tri in mesh.indices.chunks_exact(3) {
            let v = [0, 1, 2].map(|k| &mesh.vertices[tri[k] as usize]);
            let p = v.map(|v| Vec3::from(v.position));
            let n = (p[1] - p[0]).cross(p[2] - p[0]).normalize_or_zero();
            let d = (self.center - p[0]).dot(n).abs();
            if d > self.depth || n.dot(self.normal).abs() < 0.3 || best.is_some_and(|(bd, _)| d >= bd) {
                continue;
            }
            if barycentric(self.center, p[0], p[1], p[2]).min_element() < -1e-4 {
                continue;
            }
            let uv = v.map(|v| Vec2::from(v.uv));
            let map = |q: Vec3| {
                let w = barycentric(q, p[0], p[1], p[2]);
                uv[0] * w.x + uv[1] * w.y + uv[2] * w.z
            };
            let (r, u) = (self.right * self.size.x * 0.5, self.up * self.size.y * 0.5);
            let size = Vec2::new(map(self.center + r).distance(map(self.center - r)), map(self.center + u).distance(map(self.center - u)));
            best = Some((d, size));
        }
        best.map(|(_, s)| s)
    }

    fn aabb(&self) -> (Vec3, Vec3) {
        let e = (self.right * self.size.x * 0.5).abs() + (self.up * self.size.y * 0.5).abs() + (self.normal * self.depth).abs();
        (self.center - e, self.center + e)
    }
}

/// Unclamped barycentric weights of `q` (projected onto the plane of a, b, c).
fn barycentric(q: Vec3, a: Vec3, b: Vec3, c: Vec3) -> Vec3 {
    let (v0, v1, v2) = (b - a, c - a, q - a);
    let (d00, d01, d11, d20, d21) = (v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1));
    let den = d00 * d11 - d01 * d01;
    if den.abs() < 1e-20 {
        return Vec3::new(1.0, 0.0, 0.0);
    }
    let v = (d11 * d20 - d01 * d21) / den;
    let w = (d00 * d21 - d01 * d20) / den;
    Vec3::new(1.0 - v - w, v, w)
}

/// Which side of a box a decal goes on. Front = +Z (glTF forward), right = +X,
/// top = +Y. `Auto` picks the box's thinnest horizontal axis (or Y for a flat
/// slab), on the side facing away from the model's centre.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Face {
    Front,
    Back,
    Left,
    Right,
    Top,
    Bottom,
    Auto,
}

impl Face {
    pub fn parse(s: &str) -> Option<Face> {
        Some(match s.to_ascii_lowercase().as_str() {
            "front" | "+z" => Face::Front,
            "back" | "-z" => Face::Back,
            "left" | "-x" => Face::Left,
            "right" | "+x" => Face::Right,
            "top" | "+y" => Face::Top,
            "bottom" | "-y" => Face::Bottom,
            "auto" => Face::Auto,
            _ => return None,
        })
    }

    /// Outward normal of this face of the box `lo..hi`.
    pub fn normal(self, lo: Vec3, hi: Vec3, outward_from: Vec3) -> Vec3 {
        match self {
            Face::Front => Vec3::Z,
            Face::Back => Vec3::NEG_Z,
            Face::Left => Vec3::NEG_X,
            Face::Right => Vec3::X,
            Face::Top => Vec3::Y,
            Face::Bottom => Vec3::NEG_Y,
            Face::Auto => {
                let size = hi - lo;
                let c = (lo + hi) * 0.5;
                let axis = if size.y < 0.2 * size.x.min(size.z) {
                    1
                } else if size.x <= size.z {
                    0
                } else {
                    2
                };
                let mut n = Vec3::ZERO;
                n[axis] = if c[axis] >= outward_from[axis] { 1.0 } else { -1.0 };
                n
            }
        }
    }
}

/// A point on a box face: `uv` across the face as seen from outside
/// ((0,0) = top-left, (1,1) = bottom-right, like image and viewport coords).
/// Returns (point on the face plane, face width and height).
pub fn face_point(lo: Vec3, hi: Vec3, n: Vec3, uv: Vec2) -> (Vec3, Vec2) {
    let c = (lo + hi) * 0.5;
    let half = (hi - lo) * 0.5;
    let frame = Placement::new(Vec3::ZERO, n, Vec2::ONE, 0.0, 1.0);
    let (w, h) = ((frame.right.abs() * half).element_sum() * 2.0, (frame.up.abs() * half).element_sum() * 2.0);
    let on_face = c + n * (n.abs() * half).element_sum();
    (on_face + frame.right * (uv.x - 0.5) * w + frame.up * (0.5 - uv.y) * h, Vec2::new(w, h))
}

/// First triangle hit by a ray, optionally only triangles of `parts`.
/// Returns (triangle, distance, geometric normal facing against `dir`).
pub fn raycast_parts(mesh: &Mesh, tri_part: &[u32], parts: Option<&[u32]>, origin: Vec3, dir: Vec3) -> Option<(usize, f32, Vec3)> {
    let mut best: Option<(usize, f32, Vec3)> = None;
    for (t, tri) in mesh.indices.chunks_exact(3).enumerate() {
        if let Some(ps) = parts {
            if !ps.contains(&tri_part.get(t).copied().unwrap_or(u32::MAX)) {
                continue;
            }
        }
        let [a, b, c] = [0, 1, 2].map(|k| Vec3::from(mesh.vertices[tri[k] as usize].position));
        let (e1, e2) = (b - a, c - a);
        let p = dir.cross(e2);
        let det = e1.dot(p);
        if det.abs() < 1e-12 {
            continue;
        }
        let inv = 1.0 / det;
        let s = origin - a;
        let u = s.dot(p) * inv;
        if !(0.0..=1.0).contains(&u) {
            continue;
        }
        let q = s.cross(e1);
        let v = dir.dot(q) * inv;
        if v < 0.0 || u + v > 1.0 {
            continue;
        }
        let d = e2.dot(q) * inv;
        if d > 1e-6 && best.is_none_or(|(_, bd, _)| d < bd) {
            let mut n = e1.cross(e2).normalize_or_zero();
            if n.dot(dir) > 0.0 {
                n = -n;
            }
            best = Some((t, d, n));
        }
    }
    best
}

/// Small deterministic RNG (splitmix64), so a seed always gives the same scatter.
#[derive(Clone, Debug)]
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Rng {
        Rng(seed ^ 0x9E37_79B9_7F4A_7C15)
    }
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// Uniform in [0, 1).
    pub fn f32(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / (1u64 << 24) as f32
    }
    pub fn range(&mut self, lo: f32, hi: f32) -> f32 {
        lo + (hi - lo) * self.f32()
    }
    pub fn below(&mut self, n: usize) -> usize {
        (self.next_u64() % n.max(1) as u64) as usize
    }
}

/// Constraints for `scatter`.
#[derive(Clone, Debug)]
pub struct Scatter {
    pub count: usize,
    pub seed: u64,
    /// Only these parts (None = whole mesh).
    pub parts: Option<Vec<u32>>,
    /// World-space box the decal centres must fall in (None = anywhere).
    pub region: Option<(Vec3, Vec3)>,
    /// The whole decal must sit between these heights above `ground` (metres).
    pub height: Option<(f32, f32)>,
    pub ground: f32,
    /// Decal width range (metres); height follows each image's aspect.
    pub size: (f32, f32),
    /// Base rotation and +- jitter (degrees).
    pub rotation: f32,
    pub rotation_jitter: f32,
    /// Minimum distance between decal centres (metres).
    pub min_spacing: f32,
    /// Surfaces must face roughly horizontally (walls): normal within this
    /// many degrees of horizontal. None = any orientation.
    pub max_tilt: Option<f32>,
    /// Reject spots where the decal would hang off the surface (over a
    /// window, a corner, an edge).
    pub fit: bool,
    /// Image aspect ratios (width / height), one per image.
    pub aspects: Vec<f32>,
    /// Half-depth of the projection box (None = per-size default).
    pub depth: Option<f32>,
}

/// One scattered decal: which image, and where.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Scattered {
    pub image: usize,
    pub placement: Placement,
}

/// Scatter decals over the mesh. Area-weighted random points on candidate
/// triangles, rejected until they meet every constraint. Images are dealt
/// in shuffled rounds so each one shows up before any repeats. May return
/// fewer than `count` if the surface can't fit them.
pub fn scatter(mesh: &Mesh, parts: &Parts, p: &Scatter) -> Vec<Scattered> {
    let mut rng = Rng::new(p.seed);
    let max_ny = p.max_tilt.map(|t| t.clamp(0.0, 90.0).to_radians().sin());
    let band = p.height.map(|(a, b)| (p.ground + a, p.ground + b));
    // candidate triangles with their cumulative area
    let mut cand: Vec<([Vec3; 3], Vec3)> = Vec::new();
    let mut cum: Vec<f32> = Vec::new();
    let mut total = 0.0;
    for (t, tri) in mesh.indices.chunks_exact(3).enumerate() {
        if let Some(ps) = &p.parts {
            if !ps.contains(&parts.triangle_part.get(t).copied().unwrap_or(u32::MAX)) {
                continue;
            }
        }
        let v = [0, 1, 2].map(|k| Vec3::from(mesh.vertices[tri[k] as usize].position));
        let cr = (v[1] - v[0]).cross(v[2] - v[0]);
        let area = cr.length() * 0.5;
        if area < 1e-8 {
            continue;
        }
        let n = cr.normalize();
        // facing comes from the shading normals (geometric winding can be either way)
        let sn: Vec3 = tri.iter().map(|&i| Vec3::from(mesh.vertices[i as usize].normal)).sum();
        let n = if sn.dot(n) < 0.0 { -n } else { n };
        if let Some(m) = max_ny {
            if n.y.abs() > m {
                continue;
            }
        }
        if let Some((lo, hi)) = band {
            let (ymin, ymax) = (v[0].y.min(v[1].y).min(v[2].y), v[0].y.max(v[1].y).max(v[2].y));
            if ymax < lo || ymin > hi {
                continue;
            }
        }
        if let Some((rlo, rhi)) = p.region {
            let (tmin, tmax) = (v[0].min(v[1]).min(v[2]), v[0].max(v[1]).max(v[2]));
            if tmin.cmpgt(rhi).any() || tmax.cmplt(rlo).any() {
                continue;
            }
        }
        total += area;
        cand.push((v, n));
        cum.push(total);
    }
    let mut out: Vec<Scattered> = Vec::new();
    if cand.is_empty() || p.count == 0 || p.aspects.is_empty() {
        return out;
    }
    let mut deck: Vec<usize> = Vec::new();
    let mut pending: Option<usize> = None;
    for _ in 0..p.count * 400 + 2000 {
        if out.len() >= p.count {
            break;
        }
        let img = match pending {
            Some(i) => i,
            None => {
                if deck.is_empty() {
                    deck = (0..p.aspects.len()).collect();
                    for i in (1..deck.len()).rev() {
                        let j = rng.below(i + 1);
                        deck.swap(i, j);
                    }
                }
                let i = deck.pop().unwrap();
                pending = Some(i);
                i
            }
        };
        // area-weighted triangle, uniform point on it
        let r = rng.f32() * total;
        let k = cum.partition_point(|&c| c < r).min(cand.len() - 1);
        let (v, n) = cand[k];
        let (mut a, mut b) = (rng.f32(), rng.f32());
        if a + b > 1.0 {
            (a, b) = (1.0 - a, 1.0 - b);
        }
        let center = v[0] + (v[1] - v[0]) * a + (v[2] - v[0]) * b;
        let w = rng.range(p.size.0, p.size.1.max(p.size.0));
        let rot = p.rotation + rng.range(-1.0, 1.0) * p.rotation_jitter;
        if let Some((rlo, rhi)) = p.region {
            if center.cmplt(rlo).any() || center.cmpgt(rhi).any() {
                continue;
            }
        }
        let size = Vec2::new(w, w / p.aspects[img].max(1e-3));
        let depth = p.depth.unwrap_or_else(|| Placement::default_depth(size));
        let pl = Placement::new(center, n, size, rot, depth);
        if let Some((lo, hi)) = band {
            let (y0, y1) = pl.y_range();
            if y0 < lo || y1 > hi {
                continue;
            }
        }
        if out.iter().any(|o| o.placement.center.distance(center) < p.min_spacing) {
            continue;
        }
        if p.fit && !fits(&cand, &pl) {
            continue;
        }
        out.push(Scattered { image: img, placement: pl });
        pending = None;
    }
    out
}

/// Every outline point of the decal lies on a candidate triangle that is
/// (nearly) coplanar with the decal's surface.
fn fits(cand: &[([Vec3; 3], Vec3)], pl: &Placement) -> bool {
    let tol = pl.depth.clamp(0.01, 0.05);
    pl.outline().iter().all(|&q| {
        cand.iter().any(|(v, n)| {
            if n.dot(pl.normal) < 0.9 {
                return false;
            }
            let d = (q - v[0]).dot(*n);
            if d.abs() > tol {
                return false;
            }
            barycentric(q - *n * d, v[0], v[1], v[2]).min_element() >= -1e-4
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::Vertex;

    /// A 4 m wide, 6 m tall wall facing +Z (z = 0), plus a floor slab in front.
    fn wall() -> Mesh {
        let v = |p: [f32; 3], n: [f32; 3], uv: [f32; 2]| Vertex { position: p, normal: n, uv, tangent: [1.0, 0.0, 0.0, 1.0] };
        let vertices = vec![
            v([-2.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0]),
            v([2.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.5, 1.0]),
            v([2.0, 6.0, 0.0], [0.0, 0.0, 1.0], [0.5, 0.0]),
            v([-2.0, 6.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0]),
            v([-2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.5, 0.0]),
            v([2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0]),
            v([2.0, 0.0, 4.0], [0.0, 1.0, 0.0], [1.0, 1.0]),
            v([-2.0, 0.0, 4.0], [0.0, 1.0, 0.0], [0.5, 1.0]),
        ];
        Mesh { name: "wall".into(), vertices, indices: vec![0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6], has_uvs: true }
    }

    #[test]
    fn placement_is_upright_and_right_handed() {
        let p = Placement::new(Vec3::ZERO, Vec3::Z, Vec2::ONE, 0.0, 0.1);
        assert!(p.up.abs_diff_eq(Vec3::Y, 1e-5) && p.right.abs_diff_eq(Vec3::X, 1e-5));
        let p = Placement::new(Vec3::ZERO, Vec3::X, Vec2::ONE, 0.0, 0.1);
        assert!(p.right.abs_diff_eq(Vec3::NEG_Z, 1e-5), "seen from +X, right is -Z: {:?}", p.right);
        let p = Placement::new(Vec3::ZERO, Vec3::Z, Vec2::ONE, 90.0, 0.1);
        assert!(p.right.abs_diff_eq(Vec3::Y, 1e-5), "90 deg turns counter-clockwise: {:?}", p.right);
        let p = Placement::new(Vec3::ZERO, Vec3::Y, Vec2::ONE, 0.0, 0.1);
        assert!(p.up.abs_diff_eq(Vec3::NEG_Z, 1e-5) && p.right.abs_diff_eq(Vec3::X, 1e-5));
        assert!(p.contains(Vec3::new(0.4, 0.05, 0.4)) && !p.contains(Vec3::new(0.6, 0.0, 0.0)));
    }

    #[test]
    fn face_points_and_anchor_raycast() {
        let m = wall();
        let parts = m.parts();
        let (lo, hi) = m.bounds();
        let (pt, size) = face_point(lo, hi, Vec3::Z, Vec2::new(0.25, 0.5));
        assert!((pt.x + 1.0).abs() < 1e-5 && (pt.y - 3.0).abs() < 1e-5 && (pt.z - 4.0).abs() < 1e-5, "{pt:?}");
        assert!((size.x - 4.0).abs() < 1e-5 && (size.y - 6.0).abs() < 1e-5);
        let (_, d, n) = raycast_parts(&m, &parts.triangle_part, None, pt + Vec3::Z * 0.01, Vec3::NEG_Z).unwrap();
        assert!((d - 4.01).abs() < 1e-3 && n.abs_diff_eq(Vec3::Z, 1e-4), "{d} {n:?}");
        assert_eq!(Face::parse("Left"), Some(Face::Left));
        assert_eq!(Face::Auto.normal(Vec3::ZERO, Vec3::new(1.0, 1.0, 0.1), Vec3::new(0.5, 0.5, -1.0)), Vec3::Z);
    }

    #[test]
    fn tiles_cover_only_the_footprint() {
        let m = wall();
        let p = Placement::new(Vec3::new(0.0, 1.5, 0.0), Vec3::Z, Vec2::new(0.5, 0.7), 0.0, 0.05);
        let mut t = TileSet::default();
        assert_eq!(p.mark_tiles(&m, &mut t), 2, "both wall triangles, not the floor");
        assert!(t.count() > 0 && t.count() < 40, "{} tiles", t.count());
        let [x, y, _, _] = t.texel_bounds(1024).unwrap();
        // centre u = 0.25, v = 1 - 1.5 / 6 = 0.75
        assert!((x as f32 / 1024.0 - 0.25).abs() < 0.1 && (y as f32 / 1024.0 - 0.75).abs() < 0.15, "{x} {y}");
        // 4 m of wall = 0.5 UV, 6 m = 1.0 UV
        let s = p.uv_size(&m).unwrap();
        assert!((s.x - 0.5 * 0.5 / 4.0).abs() < 1e-4 && (s.y - 0.7 / 6.0).abs() < 1e-4, "{s:?}");
    }

    #[test]
    fn scatter_respects_height_spacing_tilt_and_fit() {
        let m = wall();
        let parts = m.parts();
        let s = Scatter {
            count: 6,
            seed: 7,
            parts: None,
            region: None,
            height: Some((0.5, 3.0)),
            ground: 0.0,
            size: (0.4, 0.6),
            rotation: 0.0,
            rotation_jitter: 8.0,
            min_spacing: 0.7,
            max_tilt: Some(20.0),
            fit: true,
            aspects: vec![0.7, 1.0],
            depth: None,
        };
        let a = scatter(&m, &parts, &s);
        assert_eq!(a.len(), 6, "room for six on a 4 m wall");
        for d in &a {
            let (y0, y1) = d.placement.y_range();
            assert!(y0 >= 0.5 - 1e-4 && y1 <= 3.0 + 1e-4, "height band: {y0}..{y1}");
            assert!(d.placement.normal.abs_diff_eq(Vec3::Z, 1e-4), "only on the wall, never the floor");
            for q in d.placement.outline() {
                assert!(q.x.abs() <= 2.0 + 1e-4, "hangs off the wall edge: {q:?}");
            }
        }
        for (i, x) in a.iter().enumerate() {
            for y in &a[i + 1..] {
                assert!(x.placement.center.distance(y.placement.center) >= 0.7);
            }
        }
        assert!(a.iter().any(|d| d.image == 0) && a.iter().any(|d| d.image == 1), "both images dealt");
        assert_eq!(scatter(&m, &parts, &s), a, "same seed, same scatter");
        assert_ne!(scatter(&m, &parts, &Scatter { seed: 8, ..s.clone() }), a);
        // floor only (no tilt limit, region in front of the wall)
        let floor = scatter(&m, &parts, &Scatter { max_tilt: None, height: None, region: Some((Vec3::new(-3.0, -0.1, 0.5), Vec3::new(3.0, 0.1, 5.0))), ..s.clone() });
        assert!(!floor.is_empty() && floor.iter().all(|d| d.placement.normal.abs_diff_eq(Vec3::Y, 1e-4)));
    }
}
