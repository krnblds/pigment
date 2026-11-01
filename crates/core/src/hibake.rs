//! High-to-low baking (CPU, BVH ray caster) and ID maps.
//!
//! The low mesh is rasterised in UV space; every covered texel has a low
//! surface point `p`, a smooth normal `n` and a tangent frame. A ray starts
//! on the cage (`p + n * cage`) and runs inward along `-n` up to `2 * cage`,
//! so it finds high-poly detail on both sides of the low surface; the hit
//! closest to the low surface wins. From the hit:
//!
//! - **normal** (tangent space, OpenGL / +Y up, like Pigment's normal maps)
//!   and **object-space normal**;
//! - **position** (normalised to the low mesh's bounds);
//! - **height**: signed distance from the low surface along `n`, 0.5 = on it,
//!   0 / 1 = `-cage` / `+cage`;
//! - **AO** from the high mesh (cosine-weighted hemisphere rays);
//! - **curvature** from the high mesh (per-vertex mean curvature,
//!   interpolated at the hit), 0.5 = flat;
//! - **thickness** (rays into the surface; 1 = thick);
//! - **color ID**: a distinct colour per high-mesh material, or its vertex
//!   colours;
//! - **material ID** of the low mesh (no ray), the same palette.
//!
//! Everything runs on all cores (`std::thread::scope`); outputs are RGBA f32
//! with a few texels of dilation into the gutter.

use crate::Mesh;
use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BakeMap {
    Normal,
    NormalObject,
    Position,
    Thickness,
    Ao,
    Curvature,
    Height,
    ColorId,
    MaterialId,
}

impl BakeMap {
    pub const ALL: [BakeMap; 9] = [
        BakeMap::Normal,
        BakeMap::NormalObject,
        BakeMap::Position,
        BakeMap::Thickness,
        BakeMap::Ao,
        BakeMap::Curvature,
        BakeMap::Height,
        BakeMap::ColorId,
        BakeMap::MaterialId,
    ];
    pub fn id(self) -> &'static str {
        match self {
            BakeMap::Normal => "normal",
            BakeMap::NormalObject => "normal_object",
            BakeMap::Position => "position",
            BakeMap::Thickness => "thickness",
            BakeMap::Ao => "ao",
            BakeMap::Curvature => "curvature",
            BakeMap::Height => "height",
            BakeMap::ColorId => "color_id",
            BakeMap::MaterialId => "material_id",
        }
    }
    pub fn from_id(s: &str) -> Option<BakeMap> {
        let s = s.to_ascii_lowercase().replace([' ', '-'], "_");
        Self::ALL.into_iter().find(|m| m.id() == s).or(match s.as_str() {
            "tangent_normal" | "normal_tangent" => Some(BakeMap::Normal),
            "world_normal" | "object_normal" => Some(BakeMap::NormalObject),
            "occlusion" | "ambient_occlusion" => Some(BakeMap::Ao),
            "id" | "id_map" | "colour_id" => Some(BakeMap::ColorId),
            "material" | "material_ids" => Some(BakeMap::MaterialId),
            "displacement" => Some(BakeMap::Height),
            _ => None,
        })
    }
    /// Needs the high mesh (everything but the low material ID).
    pub fn needs_high(self) -> bool {
        self != BakeMap::MaterialId
    }
}

/// High-to-low bake settings (stored in the project).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct HighBake {
    /// High-poly mesh, relative to the project folder (or absolute).
    pub mesh: String,
    /// Cage distance in metres; None = automatic (from the high / low gap).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cage: Option<f32>,
    pub maps: Vec<BakeMap>,
    /// Color ID from the high mesh's vertex colours instead of its materials.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub id_from_vertex_colors: bool,
    #[serde(default = "ao_rays")]
    pub ao_samples: u32,
    /// Occluders farther than this (fraction of the bounding radius) don't count.
    #[serde(default = "ao_dist")]
    pub ao_distance: f32,
    /// Folder the baked maps were written to (relative to the project).
    #[serde(default)]
    pub dir: String,
}

fn ao_rays() -> u32 {
    48
}
fn ao_dist() -> f32 {
    0.25
}

impl HighBake {
    pub fn new(mesh: &str, maps: Vec<BakeMap>) -> Self {
        HighBake { mesh: mesh.into(), cage: None, maps, id_from_vertex_colors: false, ao_samples: ao_rays(), ao_distance: ao_dist(), dir: String::new() }
    }
}

// ------------------------------------------------------------------ BVH

#[derive(Clone, Copy)]
struct Node {
    lo: Vec3,
    hi: Vec3,
    /// Leaf: first triangle (in `order`), count > 0. Inner: left child at index + 1, right at `first`.
    first: u32,
    count: u32,
}

/// A bounding volume hierarchy over a mesh's triangles.
pub struct Bvh<'a> {
    mesh: &'a Mesh,
    nodes: Vec<Node>,
    order: Vec<u32>,
    tri: Vec<[Vec3; 3]>,
}

/// A ray hit: triangle, distance, barycentrics (of vertices 1 and 2).
#[derive(Clone, Copy, Debug)]
pub struct Hit {
    pub tri: usize,
    pub t: f32,
    pub u: f32,
    pub v: f32,
}

impl<'a> Bvh<'a> {
    pub fn new(mesh: &'a Mesh) -> Self {
        let tri: Vec<[Vec3; 3]> = mesh.indices.chunks_exact(3).map(|t| [0, 1, 2].map(|k| Vec3::from(mesh.vertices[t[k] as usize].position))).collect();
        let cent: Vec<Vec3> = tri.iter().map(|t| (t[0] + t[1] + t[2]) / 3.0).collect();
        let mut order: Vec<u32> = (0..tri.len() as u32).collect();
        let mut nodes = Vec::with_capacity(tri.len() * 2 / 3 + 1);
        Self::build(&tri, &cent, &mut order, 0, tri.len(), &mut nodes);
        Bvh { mesh, nodes, order, tri }
    }

    fn build(tri: &[[Vec3; 3]], cent: &[Vec3], order: &mut [u32], start: usize, end: usize, nodes: &mut Vec<Node>) -> usize {
        let (mut lo, mut hi) = (Vec3::splat(f32::MAX), Vec3::splat(f32::MIN));
        let (mut clo, mut chi) = (Vec3::splat(f32::MAX), Vec3::splat(f32::MIN));
        for &i in &order[start..end] {
            for p in tri[i as usize] {
                lo = lo.min(p);
                hi = hi.max(p);
            }
            clo = clo.min(cent[i as usize]);
            chi = chi.max(cent[i as usize]);
        }
        let me = nodes.len();
        nodes.push(Node { lo, hi, first: start as u32, count: (end - start) as u32 });
        if end - start <= 4 {
            return me;
        }
        let ext = chi - clo;
        let axis = if ext.x >= ext.y && ext.x >= ext.z { 0 } else if ext.y >= ext.z { 1 } else { 2 };
        let mid = (start + end) / 2;
        order[start..end].select_nth_unstable_by(mid - start, |a, b| cent[*a as usize][axis].total_cmp(&cent[*b as usize][axis]));
        Self::build(tri, cent, order, start, mid, nodes);
        let right = Self::build(tri, cent, order, mid, end, nodes);
        nodes[me].first = right as u32;
        nodes[me].count = 0;
        me
    }

    /// Nearest hit along `dir` (unit) within [tmin, tmax].
    pub fn hit(&self, o: Vec3, dir: Vec3, tmin: f32, tmax: f32) -> Option<Hit> {
        let inv = Vec3::ONE / dir;
        let mut best: Option<Hit> = None;
        let mut far = tmax;
        let mut stack = [0usize; 64];
        let mut sp = 1;
        while sp > 0 {
            sp -= 1;
            let ni = stack[sp];
            let n = self.nodes[ni];
            let t0 = (n.lo - o) * inv;
            let t1 = (n.hi - o) * inv;
            let tn = t0.min(t1).max_element();
            let tf = t0.max(t1).min_element();
            if tf < tn.max(tmin) || tn > far {
                continue;
            }
            if n.count > 0 {
                for &ti in &self.order[n.first as usize..(n.first + n.count) as usize] {
                    let [a, b, c] = self.tri[ti as usize];
                    let (e1, e2) = (b - a, c - a);
                    let pv = dir.cross(e2);
                    let det = e1.dot(pv);
                    if det.abs() < 1e-14 {
                        continue;
                    }
                    let id = 1.0 / det;
                    let s = o - a;
                    let u = s.dot(pv) * id;
                    if !(0.0..=1.0).contains(&u) {
                        continue;
                    }
                    let q = s.cross(e1);
                    let v = dir.dot(q) * id;
                    if v < 0.0 || u + v > 1.0 {
                        continue;
                    }
                    let t = e2.dot(q) * id;
                    if t >= tmin && t <= far {
                        far = t;
                        best = Some(Hit { tri: ti as usize, t, u, v });
                    }
                }
            } else if sp + 2 <= stack.len() {
                // left child right after its parent, right child at `first`
                stack[sp] = n.first as usize;
                stack[sp + 1] = ni + 1;
                sp += 2;
            }
        }
        best
    }

    /// Interpolated smooth normal at a hit.
    pub fn normal(&self, h: &Hit) -> Vec3 {
        let t = &self.mesh.indices[h.tri * 3..h.tri * 3 + 3];
        let n = |k: usize| Vec3::from(self.mesh.vertices[t[k] as usize].normal);
        (n(0) * (1.0 - h.u - h.v) + n(1) * h.u + n(2) * h.v).normalize_or_zero()
    }
    /// Geometric (face) normal of the hit triangle.
    pub fn face_normal(&self, h: &Hit) -> Vec3 {
        let [a, b, c] = self.tri[h.tri];
        (b - a).cross(c - a).normalize_or_zero()
    }
    fn interp<T: Copy + std::ops::Mul<f32, Output = T> + std::ops::Add<Output = T>>(&self, h: &Hit, f: impl Fn(usize) -> T) -> T {
        let t = &self.mesh.indices[h.tri * 3..h.tri * 3 + 3];
        f(t[0] as usize) * (1.0 - h.u - h.v) + f(t[1] as usize) * h.u + f(t[2] as usize) * h.v
    }
}

// ------------------------------------------------------------------ helpers

/// A distinct colour for ID `k` (golden-ratio hues, sRGB 0..1).
pub fn id_color(k: u32) -> [f32; 3] {
    let h = (k as f32 * 0.618_034 + 0.13).fract();
    let s = if k % 2 == 0 { 0.75 } else { 0.55 };
    let v = if (k / 2) % 2 == 0 { 0.95 } else { 0.75 };
    let i = (h * 6.0).floor();
    let f = h * 6.0 - i;
    let (p, q, t) = (v * (1.0 - s), v * (1.0 - s * f), v * (1.0 - s * (1.0 - f)));
    match i as i32 % 6 {
        0 => [v, t, p],
        1 => [q, v, p],
        2 => [p, v, t],
        3 => [p, q, v],
        4 => [t, p, v],
        _ => [v, p, q],
    }
}

/// Per-vertex mean curvature of a mesh (positive = convex), from welded
/// positions: the average over neighbours of (n_j - n_i) . (p_j - p_i) / |p_j - p_i|^2.
pub fn vertex_curvature(mesh: &Mesh) -> Vec<f32> {
    use std::collections::HashMap;
    let key = |p: [f32; 3]| [(p[0] * 1e5).round() as i64, (p[1] * 1e5).round() as i64, (p[2] * 1e5).round() as i64];
    let mut weld: HashMap<[i64; 3], usize> = HashMap::new();
    let ids: Vec<usize> = mesh.vertices.iter().map(|v| { let n = weld.len(); *weld.entry(key(v.position)).or_insert(n) }).collect();
    let n = weld.len();
    let mut pos = vec![Vec3::ZERO; n];
    let mut nrm = vec![Vec3::ZERO; n];
    for (i, v) in mesh.vertices.iter().enumerate() {
        pos[ids[i]] = Vec3::from(v.position);
        nrm[ids[i]] += Vec3::from(v.normal);
    }
    for x in &mut nrm {
        *x = x.normalize_or_zero();
    }
    let mut sum = vec![0.0f32; n];
    let mut cnt = vec![0u32; n];
    for t in mesh.indices.chunks_exact(3) {
        for (a, b) in [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])] {
            let (i, j) = (ids[a as usize], ids[b as usize]);
            let d = pos[j] - pos[i];
            let l2 = d.length_squared().max(1e-12);
            // positive where neighbours' normals open outward (convex)
            let k = (nrm[j] - nrm[i]).dot(d) / l2;
            sum[i] += k;
            sum[j] += k;
            cnt[i] += 1;
            cnt[j] += 1;
        }
    }
    let vk: Vec<f32> = (0..n).map(|i| if cnt[i] > 0 { sum[i] / cnt[i] as f32 } else { 0.0 }).collect();
    ids.iter().map(|&i| vk[i]).collect()
}

/// Cosine-weighted direction around `n` from two numbers in 0..1.
fn cosine_dir(n: Vec3, a: f32, b: f32) -> Vec3 {
    let (t, bt) = n.any_orthonormal_pair();
    let r = a.sqrt();
    let phi = std::f32::consts::TAU * b;
    (t * r * phi.cos() + bt * r * phi.sin() + n * (1.0 - a).max(0.0).sqrt()).normalize()
}

fn hammersley(i: u32, n: u32) -> (f32, f32) {
    (i as f32 / n as f32 + 0.5 / n as f32, i.reverse_bits() as f32 / 4294967296.0)
}

/// Texels of the low mesh in UV space: (triangle, barycentrics) per texel, by
/// rasterising every triangle (texel centres, top-left inclusive).
pub fn rasterize_uv(mesh: &Mesh, res: u32) -> Vec<Option<(u32, f32, f32)>> {
    let mut out: Vec<Option<(u32, f32, f32)>> = vec![None; (res * res) as usize];
    let r = res as f32;
    for (ti, t) in mesh.indices.chunks_exact(3).enumerate() {
        let uv = [0, 1, 2].map(|k| Vec2::from(mesh.vertices[t[k] as usize].uv) * r);
        // UDIM / tiling UVs wrap into the tile
        let base = (uv[0] / r).floor() * r;
        let uv = uv.map(|u| u - base);
        let lo = uv[0].min(uv[1]).min(uv[2]).floor().max(Vec2::ZERO);
        let hi = uv[0].max(uv[1]).max(uv[2]).ceil().min(Vec2::splat(r - 1.0));
        let d = (uv[1] - uv[0]).perp_dot(uv[2] - uv[0]);
        if d.abs() < 1e-12 {
            continue;
        }
        for y in lo.y as u32..=hi.y as u32 {
            for x in lo.x as u32..=hi.x as u32 {
                let p = Vec2::new(x as f32 + 0.5, y as f32 + 0.5);
                let w1 = (p - uv[0]).perp_dot(uv[2] - uv[0]) / d;
                let w2 = (uv[1] - uv[0]).perp_dot(p - uv[0]) / d;
                let w0 = 1.0 - w1 - w2;
                if w0 >= -1e-4 && w1 >= -1e-4 && w2 >= -1e-4 {
                    out[(y * res + x) as usize] = Some((ti as u32, w1, w2));
                }
            }
        }
    }
    out
}

/// One baked map: RGBA f32, row-major, `size` x `size`.
pub struct BakedMap {
    pub map: BakeMap,
    pub size: u32,
    pub rgba: Vec<f32>,
}

pub struct BakeOutput {
    pub maps: Vec<BakedMap>,
    pub cage: f32,
    /// Fraction of covered texels whose ray hit the high mesh.
    pub hit_rate: f32,
    pub texels: usize,
}

/// Automatic cage: 1.25 x the 98th percentile of the gap between the high
/// mesh's vertices and the low surface (rays along the high normals, both
/// ways), at least 0.5 % of the bounding radius.
pub fn auto_cage(low: &Mesh, high: &Mesh) -> f32 {
    let bvh = Bvh::new(low);
    let (_, radius) = low.bounding_sphere();
    let step = (high.vertices.len() / 4000).max(1);
    let mut d: Vec<f32> = Vec::new();
    for v in high.vertices.iter().step_by(step) {
        let p = Vec3::from(v.position);
        let n = Vec3::from(v.normal).normalize_or_zero();
        if n == Vec3::ZERO {
            continue;
        }
        let a = bvh.hit(p, n, 0.0, radius).map(|h| h.t);
        let b = bvh.hit(p, -n, 0.0, radius).map(|h| h.t);
        if let Some(x) = match (a, b) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (a, b) => a.or(b),
        } {
            d.push(x);
        }
    }
    if d.is_empty() {
        return radius * 0.05;
    }
    d.sort_by(f32::total_cmp);
    let p98 = d[((d.len() as f32 * 0.98) as usize).min(d.len() - 1)];
    (p98 * 1.25).max(radius * 0.005)
}

/// Bake `maps` of `high` onto `low`'s UVs at `res`.
pub fn bake(low: &Mesh, high: Option<&Mesh>, res: u32, s: &HighBake) -> BakeOutput {
    let texels = rasterize_uv(low, res);
    let (lo_b, hi_b) = low.bounds();
    let (_, radius) = low.bounding_sphere();
    let cage = match (s.cage, high) {
        (Some(c), _) => c.max(1e-5),
        (None, Some(h)) => auto_cage(low, h),
        (None, None) => radius * 0.05,
    };
    let bvh = high.map(Bvh::new);
    let curv = high.filter(|_| s.maps.contains(&BakeMap::Curvature)).map(vertex_curvature);
    let curv_scale = radius * 0.05; // curvature x this ~ -1..1 for features a few % of the size
    let n = (res * res) as usize;
    let maps: Vec<BakeMap> = s.maps.clone();
    let mut out: Vec<Vec<f32>> = maps.iter().map(|_| vec![0.0; n * 4]).collect();
    let covered: Vec<bool> = texels.iter().map(Option::is_some).collect();
    let threads = std::thread::available_parallelism().map(|x| x.get()).unwrap_or(4).min(32);
    let rows_per = (res as usize).div_ceil(threads);
    let hits = std::sync::atomic::AtomicUsize::new(0);
    let ao_n = s.ao_samples.clamp(4, 512);
    let ao_far = s.ao_distance * radius;
    std::thread::scope(|sc| {
        let mut chunks: Vec<Vec<&mut [f32]>> = (0..threads).map(|_| Vec::new()).collect();
        for buf in out.iter_mut() {
            for (k, c) in buf.chunks_mut(rows_per * res as usize * 4).enumerate() {
                chunks[k].push(c);
            }
        }
        for (k, mut bufs) in chunks.into_iter().enumerate() {
            let texels = &texels;
            let bvh = bvh.as_ref();
            let curv = curv.as_ref();
            let maps = &maps;
            let hits = &hits;
            sc.spawn(move || {
                let y0 = k * rows_per;
                let y1 = ((k + 1) * rows_per).min(res as usize);
                for y in y0..y1 {
                    for x in 0..res as usize {
                        let i = y * res as usize + x;
                        let Some((ti, w1, w2)) = texels[i] else { continue };
                        let t = &low.indices[ti as usize * 3..ti as usize * 3 + 3];
                        let v = |k: usize| &low.vertices[t[k] as usize];
                        let w0 = 1.0 - w1 - w2;
                        let p = Vec3::from(v(0).position) * w0 + Vec3::from(v(1).position) * w1 + Vec3::from(v(2).position) * w2;
                        let nl = (Vec3::from(v(0).normal) * w0 + Vec3::from(v(1).normal) * w1 + Vec3::from(v(2).normal) * w2).normalize_or_zero();
                        let tg4 = |k: usize| glam::Vec4::from(v(k).tangent);
                        let tg = tg4(0) * w0 + tg4(1) * w1 + tg4(2) * w2;
                        let tan = (tg.truncate() - nl * nl.dot(tg.truncate())).normalize_or_zero();
                        let bit = nl.cross(tan) * if tg.w < 0.0 { -1.0 } else { 1.0 };
                        // within the cage; else the nearest surface along +-n (corners
                        // where the high mesh strays past the cage), in cage coordinates
                        let hit = bvh.and_then(|b| {
                            b.hit(p + nl * cage, -nl, 0.0, cage * 2.0).or_else(|| {
                                let far = radius * 0.25;
                                let dn = b.hit(p, -nl, 0.0, far).map(|h| Hit { t: cage + h.t, ..h });
                                let up = b.hit(p, nl, 0.0, far).map(|h| Hit { t: cage - h.t, ..h });
                                match (dn, up) {
                                    (Some(a), Some(b)) => Some(if (a.t - cage).abs() <= (b.t - cage).abs() { a } else { b }),
                                    (a, b) => a.or(b),
                                }
                            })
                        });
                        if hit.is_some() {
                            hits.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        }
                        let off = (y - y0) * res as usize * 4 + x * 4;
                        for (mi, m) in maps.iter().enumerate() {
                            let px: [f32; 4] = match (m, hit.as_ref(), bvh) {
                                (BakeMap::MaterialId, ..) => {
                                    let c = id_color(low.material_of(ti as usize));
                                    [c[0], c[1], c[2], 1.0]
                                }
                                (BakeMap::Position, h, b) => {
                                    let hp = match (h, b) {
                                        (Some(h), Some(_)) => p + nl * (cage - h.t),
                                        _ => p,
                                    };
                                    let q = (hp - lo_b) / (hi_b - lo_b).max(Vec3::splat(1e-6));
                                    [q.x, q.y, q.z, 1.0]
                                }
                                (_, None, _) | (_, _, None) => match m {
                                    BakeMap::Normal => [0.5, 0.5, 1.0, 1.0],
                                    BakeMap::NormalObject => [nl.x * 0.5 + 0.5, nl.y * 0.5 + 0.5, nl.z * 0.5 + 0.5, 1.0],
                                    BakeMap::Height | BakeMap::Curvature => [0.5, 0.5, 0.5, 1.0],
                                    BakeMap::ColorId => [0.0, 0.0, 0.0, 1.0],
                                    _ => [1.0, 1.0, 1.0, 1.0],
                                },
                                (_, Some(h), Some(b)) => {
                                    let hp = p + nl * (cage - h.t);
                                    let mut nh = b.normal(h);
                                    if nh == Vec3::ZERO {
                                        nh = b.face_normal(h);
                                    }
                                    match m {
                                        BakeMap::Normal => {
                                            let tn = Vec3::new(nh.dot(tan), nh.dot(bit), nh.dot(nl)).normalize_or_zero();
                                            [tn.x * 0.5 + 0.5, tn.y * 0.5 + 0.5, tn.z * 0.5 + 0.5, 1.0]
                                        }
                                        BakeMap::NormalObject => [nh.x * 0.5 + 0.5, nh.y * 0.5 + 0.5, nh.z * 0.5 + 0.5, 1.0],
                                        BakeMap::Height => {
                                            let d = (cage - h.t) / cage;
                                            let v = (0.5 + 0.5 * d).clamp(0.0, 1.0);
                                            [v, v, v, 1.0]
                                        }
                                        BakeMap::Ao => {
                                            let o = hp + nh * cage * 0.01;
                                            let mut open = 0u32;
                                            for k in 0..ao_n {
                                                let (a, c) = hammersley(k, ao_n);
                                                let a = (a + (i as f32 * 0.618_034).fract()).fract();
                                                let dir = cosine_dir(nh, a, c);
                                                if b.hit(o, dir, 0.0, ao_far).is_none() {
                                                    open += 1;
                                                }
                                            }
                                            let v = open as f32 / ao_n as f32;
                                            [v, v, v, 1.0]
                                        }
                                        BakeMap::Thickness => {
                                            let o = hp - nh * cage * 0.01;
                                            let far = radius * 2.0;
                                            let k = 16;
                                            let mut sum = 0.0;
                                            for j in 0..k {
                                                let (a, c) = hammersley(j, k);
                                                let dir = cosine_dir(-nh, a * 0.5, c);
                                                sum += b.hit(o, dir, 0.0, far).map(|x| x.t).unwrap_or(far).min(far);
                                            }
                                            let v = (sum / k as f32 / (radius * 1.5)).clamp(0.0, 1.0);
                                            [v, v, v, 1.0]
                                        }
                                        BakeMap::Curvature => {
                                            let c = curv.map(|cv| b.interp(h, |k| cv[k])).unwrap_or(0.0);
                                            let v = (0.5 + c * curv_scale).clamp(0.0, 1.0);
                                            [v, v, v, 1.0]
                                        }
                                        BakeMap::ColorId => {
                                            let hm = high.unwrap();
                                            let c = if s.id_from_vertex_colors && !hm.colors.is_empty() {
                                                let c = b.interp(h, |k| Vec3::from(hm.colors[k]));
                                                [c.x, c.y, c.z]
                                            } else {
                                                id_color(hm.material_of(h.tri))
                                            };
                                            [c[0], c[1], c[2], 1.0]
                                        }
                                        BakeMap::MaterialId | BakeMap::Position => unreachable!(),
                                    }
                                }
                            };
                            bufs[mi][off..off + 4].copy_from_slice(&px);
                        }
                    }
                }
            });
        }
    });
    // dilate into the gutter so bilinear filtering and mips don't pull in black
    for buf in out.iter_mut() {
        dilate(buf, &covered, res, 4);
    }
    let count = covered.iter().filter(|c| **c).count();
    BakeOutput {
        maps: maps.into_iter().zip(out).map(|(map, rgba)| BakedMap { map, size: res, rgba }).collect(),
        cage,
        hit_rate: if count > 0 { hits.into_inner() as f32 / count as f32 } else { 0.0 },
        texels: count,
    }
}

/// Grow covered texels `steps` times into uncovered neighbours.
pub fn dilate(rgba: &mut [f32], covered: &[bool], res: u32, steps: u32) {
    let r = res as i32;
    let mut cov = covered.to_vec();
    for _ in 0..steps {
        let mut next = cov.clone();
        for y in 0..r {
            for x in 0..r {
                let i = (y * r + x) as usize;
                if cov[i] {
                    continue;
                }
                let mut acc = [0.0f32; 4];
                let mut n = 0.0;
                for (dx, dy) in [(-1, 0), (1, 0), (0, -1), (0, 1)] {
                    let (xx, yy) = (x + dx, y + dy);
                    if xx < 0 || yy < 0 || xx >= r || yy >= r {
                        continue;
                    }
                    let j = (yy * r + xx) as usize;
                    if cov[j] {
                        for k in 0..4 {
                            acc[k] += rgba[j * 4 + k];
                        }
                        n += 1.0;
                    }
                }
                if n > 0.0 {
                    for k in 0..4 {
                        rgba[i * 4 + k] = acc[k] / n;
                    }
                    next[i] = true;
                }
            }
        }
        cov = next;
    }
}

// ------------------------------------------------------------------ test meshes

/// A rounded box: `half` extents, edge radius `bevel`, `n` x `n` quads per
/// face, UVs in a 3 x 2 atlas (one cell per face, with a margin). Normals are
/// the analytic rounded-box normals; `displace(p, n)` moves vertices along
/// the normal (a sculpt-like high version) and `material(p)` assigns ids.
pub fn rounded_box(half: Vec3, bevel: f32, n: u32, displace: Option<&dyn Fn(Vec3, Vec3) -> f32>, material: Option<&dyn Fn(Vec3) -> u32>) -> Mesh {
    let mut m = Mesh { name: "rounded box".into(), has_uvs: true, ..Default::default() };
    let inner = (half - Vec3::splat(bevel)).max(Vec3::ZERO);
    let faces: [(Vec3, Vec3, Vec3); 6] = [
        (Vec3::X, -Vec3::Z, Vec3::Y),
        (-Vec3::X, Vec3::Z, Vec3::Y),
        (Vec3::Y, Vec3::X, -Vec3::Z),
        (-Vec3::Y, Vec3::X, Vec3::Z),
        (Vec3::Z, Vec3::X, Vec3::Y),
        (-Vec3::Z, -Vec3::X, Vec3::Y),
    ];
    let margin = 0.04;
    for (fi, (nrm, u_ax, v_ax)) in faces.iter().enumerate() {
        let cell = Vec2::new((fi % 3) as f32 / 3.0, (fi / 3) as f32 / 2.0);
        let base = m.vertices.len() as u32;
        for j in 0..=n {
            for i in 0..=n {
                let (a, b) = (i as f32 / n as f32 * 2.0 - 1.0, j as f32 / n as f32 * 2.0 - 1.0);
                // point on the cube face, then rounded
                let q = *nrm * half.dot(nrm.abs()) + *u_ax * a * half.dot(u_ax.abs()) + *v_ax * b * half.dot(v_ax.abs());
                let c = q.clamp(-inner, inner);
                let dir = (q - c).normalize_or(*nrm);
                let mut p = c + dir * bevel;
                if let Some(d) = displace {
                    p += dir * d(p, dir);
                }
                let uv = cell + Vec2::new(margin + (a * 0.5 + 0.5) * (1.0 / 3.0 - 2.0 * margin), margin + (0.5 - b * 0.5) * (0.5 - 2.0 * margin));
                m.vertices.push(crate::Vertex { position: p.into(), normal: dir.into(), uv: uv.into(), tangent: [0.0; 4] });
            }
        }
        for j in 0..n {
            for i in 0..n {
                let k = base + j * (n + 1) + i;
                m.indices.extend_from_slice(&[k, k + 1, k + n + 2, k, k + n + 2, k + n + 1]);
            }
        }
    }
    if let Some(f) = material {
        m.tri_material = m.indices.chunks_exact(3).map(|t| f(t.iter().map(|&k| Vec3::from(m.vertices[k as usize].position)).sum::<Vec3>() / 3.0)).collect();
    }
    if displace.is_some() {
        m.compute_normals_welded();
    }
    m.compute_tangents();
    m
}

/// The test pair: a bevelled box (low, 4 x 4 quads per face) and a sculpt-like
/// high version (dents, a raised ring on top, horizontal grooves; three
/// materials: body, lid, ring).
pub fn test_pair() -> (Mesh, Mesh) {
    let half = Vec3::new(0.5, 0.35, 0.4);
    let low = rounded_box(half, 0.06, 4, None, None);
    let sculpt = |p: Vec3, n: Vec3| -> f32 {
        let mut d = 0.0;
        // three round dents on the front
        for c in [Vec3::new(-0.2, 0.05, 0.4), Vec3::new(0.15, -0.1, 0.4), Vec3::new(0.25, 0.15, 0.4)] {
            let r = (p - c).length();
            d -= 0.025 * (1.0 - (r / 0.09).min(1.0)).powi(2) * n.z.max(0.0);
        }
        // a raised ring on the top
        let rr = Vec2::new(p.x, p.z).length();
        d += 0.012 * (1.0 - ((rr - 0.22).abs() / 0.03).min(1.0)) * n.y.max(0.0);
        // grooves around the sides
        let g = ((p.y * 18.0).fract() - 0.5).abs();
        d -= 0.008 * (1.0 - (g / 0.06).min(1.0)) * (1.0 - n.y.abs());
        d
    };
    let mat = |p: Vec3| -> u32 {
        if p.y > 0.33 {
            if (Vec2::new(p.x, p.z).length() - 0.22).abs() < 0.035 {
                2
            } else {
                1
            }
        } else {
            0
        }
    };
    let mut high = rounded_box(half, 0.07, 96, Some(&sculpt), Some(&mat));
    high.material_names = vec!["body".into(), "lid".into(), "ring".into()];
    high.name = "rounded box high".into();
    (low, high)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bvh_matches_brute_force() {
        let (_, high) = test_pair();
        let b = Bvh::new(&high);
        for (k, d) in [Vec3::new(0.1, -0.2, -1.0), Vec3::new(-1.0, 0.1, 0.05), Vec3::new(0.0, -1.0, 0.0)].iter().enumerate() {
            let o = -*d * 3.0 + Vec3::new(0.05 * k as f32, 0.02, 0.0);
            let dir = d.normalize();
            let a = b.hit(o, dir, 0.0, 100.0).unwrap();
            let (t, dist) = high.raycast(o, dir).unwrap();
            assert_eq!(a.tri, t);
            assert!((a.t - dist).abs() < 1e-4);
        }
    }

    #[test]
    fn high_to_low_bake_finds_the_sculpt() {
        let (low, high) = test_pair();
        let s = HighBake::new("high", BakeMap::ALL.to_vec());
        let out = bake(&low, Some(&high), 128, &s);
        assert!(out.hit_rate > 0.97, "rays hit the high mesh ({})", out.hit_rate);
        assert!(out.cage > 0.005 && out.cage < 0.1, "auto cage {}", out.cage);
        let get = |m: BakeMap| &out.maps.iter().find(|x| x.map == m).unwrap().rgba;
        let res = 128usize;
        // front face (+Z) is atlas cell 4: u 1/3..2/3, v 0.5..1; the dent centred at (-0.2, 0.05)
        let texel = |p: Vec3| -> usize {
            let a = p.x / 0.5;
            let b = p.y / 0.35;
            let m = 0.04;
            let u = 1.0 / 3.0 + m + (a * 0.5 + 0.5) * (1.0 / 3.0 - 2.0 * m);
            let v = 0.5 + m + (0.5 - b * 0.5) * (0.5 - 2.0 * m);
            ((v * res as f32) as usize) * res + (u * res as f32) as usize
        };
        let dent = texel(Vec3::new(-0.2, 0.05, 0.4));
        let flat = texel(Vec3::new(0.0, -0.25, 0.4));
        let h = get(BakeMap::Height);
        assert!(h[dent * 4] < h[flat * 4] - 0.1, "the dent is lower: {} vs {}", h[dent * 4], h[flat * 4]);
        let nrm = get(BakeMap::Normal);
        let rim = texel(Vec3::new(-0.2 + 0.06, 0.05, 0.4));
        assert!((nrm[flat * 4 + 2] - 1.0).abs() < 0.05, "flat area faces out: {:?}", &nrm[flat * 4..flat * 4 + 3]);
        assert!(nrm[rim * 4] < 0.45, "the dent's right wall tilts towards -x in tangent space: {:?}", &nrm[rim * 4..rim * 4 + 3]);
        let ao = get(BakeMap::Ao);
        assert!(ao[dent * 4] < ao[flat * 4] + 1e-3, "dent no brighter in AO ({} vs {})", ao[dent * 4], ao[flat * 4]);
        // ID: the top has the lid (and ring) colours, the front the body colour
        let id = get(BakeMap::ColorId);
        let body = id_color(0);
        assert!((id[flat * 4] - body[0]).abs() < 1e-4 && (id[flat * 4 + 1] - body[1]).abs() < 1e-4);
        let top_cell = |u: f32, v: f32| ((v * res as f32) as usize) * res + (u * res as f32) as usize;
        let lid = id_color(1);
        let t = top_cell(2.0 / 3.0 + 0.04 + 0.02, 0.04 + 0.02);
        assert!((id[t * 4] - lid[0]).abs() < 1e-4, "lid colour on the top face");
        let c = get(BakeMap::Curvature);
        assert!(c.iter().step_by(4).any(|v| *v > 0.6) && c.iter().step_by(4).any(|v| *v < 0.4), "convex and concave curvature both found");
        let th = get(BakeMap::Thickness);
        assert!(th[flat * 4] > 0.3, "the box is thick ({})", th[flat * 4]);
        // the low mesh's material ID: one material = one colour everywhere covered
        let mid = get(BakeMap::MaterialId);
        assert!((mid[flat * 4] - body[0]).abs() < 1e-4);
    }

    /// Writes the generated pair for docs/agents/parity/hibake_demo.py:
    /// `cargo test -p pigment-core --release write_test_pair -- --ignored`
    #[test]
    #[ignore]
    fn write_test_pair() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../target/pd");
        std::fs::create_dir_all(&dir).unwrap();
        let (low, high) = test_pair();
        low.write_obj(&dir.join("box_low.obj")).unwrap();
        high.write_obj(&dir.join("box_high.obj")).unwrap();
    }

    #[test]
    fn id_colors_are_distinct() {
        let c: Vec<[f32; 3]> = (0..12).map(id_color).collect();
        for i in 0..c.len() {
            for j in i + 1..c.len() {
                let d: f32 = (0..3).map(|k| (c[i][k] - c[j][k]).abs()).sum();
                assert!(d > 0.08, "{i} vs {j}: {:?} {:?}", c[i], c[j]);
            }
        }
    }
}
