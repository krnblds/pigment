//! Foliage layers: instances of foliage cards (moss tufts, grass, weeds,
//! fallen leaves, ivy, hanging plants) placed on a model's surface.
//!
//! A [`FoliageSet`] is plain data stored in the document (a foliage layer),
//! so undo, save and variants work like any other edit. Each [`Instance`] is
//! an affine frame for a unit card: the card spans `p + s * x + t * y` for
//! `s` in -0.5..0.5 and `t` in 0..1, where `t = 0` is the bottom edge of the
//! atlas cell (the plant's base). Cross / star cards add quads rotated about
//! `y`.
//!
//! Placement:
//! - [`scatter`]: area-weighted random points (the decal scatter's
//!   [`SurfaceSampler`]), filtered by surface normal, region, parts and a
//!   caller-supplied acceptance (masks, AO), with spacing;
//! - [`paint_dab`]: the same, inside a sphere around a brush hit;
//! - [`grow_ivy`]: a growth walk that climbs along the surface from start
//!   points, branching, laying stem segments and leaves.
//!
//! Export: [`card_mesh`] (one mesh of every card, for glb / Blender) and
//! [`instances_json`] (per-cell transform lists for Godot MultiMesh).

use crate::decal::{Rng, SurfaceSampler, SurfaceTri};
use crate::foliage::{CardMesh, FoliageCell, Mount};
use crate::mesh::{Mesh, Parts, Vertex};
use glam::Vec3;
use serde::{Deserialize, Serialize};

/// The atlas a foliage layer draws its cards from.
pub const BUILTIN_ATLAS: &str = "builtin";

fn builtin() -> String {
    BUILTIN_ATLAS.into()
}

/// One card.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct Instance {
    /// Index into [`FoliageSet::cells`].
    pub c: u16,
    pub mesh: CardMesh,
    pub mount: Mount,
    /// Base centre of the card.
    pub p: [f32; 3],
    /// Width vector (full width).
    pub x: [f32; 3],
    /// Height vector, base -> top of the cell.
    pub y: [f32; 3],
}

impl Instance {
    pub fn pos(&self) -> Vec3 {
        Vec3::from(self.p)
    }
    /// Centre of the card.
    pub fn center(&self) -> Vec3 {
        Vec3::from(self.p) + Vec3::from(self.y) * 0.5
    }
    /// Unit card normal (x cross y).
    pub fn normal(&self) -> Vec3 {
        Vec3::from(self.x).cross(Vec3::from(self.y)).normalize_or(Vec3::Z)
    }
    /// The width vectors of each quad (one per quad of `mesh`).
    pub fn quad_x(&self) -> Vec<Vec3> {
        let x = Vec3::from(self.x);
        let axis = Vec3::from(self.y).normalize_or(Vec3::Y);
        (0..self.mesh.quads()).map(|k| rotate(x, axis, k as f32 * std::f32::consts::PI / self.mesh.quads() as f32)).collect()
    }
}

fn rotate(v: Vec3, axis: Vec3, a: f32) -> Vec3 {
    let (s, c) = a.sin_cos();
    v * c + axis.cross(v) * s + axis * axis.dot(v) * (1.0 - c)
}

/// The data of a foliage layer.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FoliageSet {
    /// Card source: `"builtin"` (Pigment's built-in library) or the path of
    /// a foliage atlas export (`<name>_foliage.json`).
    #[serde(default = "builtin")]
    pub atlas: String,
    /// Cell names used by the instances (`Instance::c` indexes this).
    #[serde(default)]
    pub cells: Vec<String>,
    /// Wind sway amount in the viewport preview (0 = still).
    #[serde(default)]
    pub wind: f32,
    #[serde(default)]
    pub instances: Vec<Instance>,
}

impl Default for FoliageSet {
    fn default() -> Self {
        FoliageSet { atlas: builtin(), cells: Vec::new(), wind: 0.0, instances: Vec::new() }
    }
}

impl FoliageSet {
    /// Index of `name` in the palette, adding it if needed.
    pub fn cell_index(&mut self, name: &str) -> u16 {
        match self.cells.iter().position(|c| c == name) {
            Some(i) => i as u16,
            None => {
                self.cells.push(name.into());
                (self.cells.len() - 1) as u16
            }
        }
    }
    /// Number of instances of each palette cell.
    pub fn counts(&self) -> Vec<usize> {
        let mut n = vec![0; self.cells.len()];
        for i in &self.instances {
            if let Some(c) = n.get_mut(i.c as usize) {
                *c += 1;
            }
        }
        n
    }
    /// Remove instances whose base lies within `radius` of any of `points`.
    /// Returns how many went.
    pub fn erase(&mut self, points: &[Vec3], radius: f32, only: Option<&[u16]>) -> usize {
        let before = self.instances.len();
        let r2 = radius * radius;
        self.instances.retain(|i| {
            let hit = points.iter().any(|q| q.distance_squared(i.pos()) <= r2 || q.distance_squared(i.center()) <= r2);
            !(hit && only.is_none_or(|o| o.contains(&i.c)))
        });
        before - self.instances.len()
    }
}

/// How cards are sized and oriented when placed.
#[derive(Clone, Debug)]
pub struct PlaceOpts {
    /// Scale range applied to the cell's size.
    pub scale: (f32, f32),
    /// Upright cards: 0 = along the surface normal, 1 = straight up.
    pub align: f32,
    /// Rotation jitter in degrees for flat / wall cards around the normal
    /// (upright cards always get a random heading).
    pub rotation_jitter: f32,
    /// Mount override (None = the cell's own).
    pub mount: Option<Mount>,
}

impl Default for PlaceOpts {
    fn default() -> Self {
        PlaceOpts { scale: (0.8, 1.2), align: 0.6, rotation_jitter: 180.0, mount: None }
    }
}

fn any_perp(n: Vec3) -> Vec3 {
    let a = if n.y.abs() < 0.9 { Vec3::Y } else { Vec3::X };
    a.cross(n).normalize()
}

/// The direction "up the surface" at a point with normal `n` (world up
/// projected into the tangent plane), or any tangent on level ground.
pub fn up_tangent(n: Vec3) -> Vec3 {
    let t = Vec3::Y - n * n.y;
    if t.length_squared() > 1e-4 {
        t.normalize()
    } else {
        any_perp(n)
    }
}

/// One card of `cell` at surface point `p` with normal `n`.
pub fn place(cell: &FoliageCell, c: u16, p: Vec3, n: Vec3, rng: &mut Rng, o: &PlaceOpts) -> Instance {
    let k = rng.range(o.scale.0, o.scale.1.max(o.scale.0));
    let (w, h) = (cell.size_m[0] * k, cell.size_m[1] * k);
    let mount = o.mount.unwrap_or(cell.mount);
    let jitter = |rng: &mut Rng, t: Vec3, axis: Vec3, deg: f32| rotate(t, axis, rng.range(-1.0, 1.0) * deg.to_radians());
    let (base, x, y) = match mount {
        Mount::Upright => {
            let u = n.lerp(Vec3::Y, o.align.clamp(0.0, 1.0)).normalize_or(n);
            let a = any_perp(u);
            let xd = rotate(a, u, rng.f32() * std::f32::consts::TAU);
            // a little lean so tufts don't stand like soldiers
            let u = rotate(u, xd, rng.range(-0.15, 0.15));
            (p - u * h * 0.04, xd * w, u * h)
        }
        Mount::Flat => {
            let yd = jitter(rng, up_tangent(n), n, o.rotation_jitter);
            let xd = yd.cross(n).normalize_or(any_perp(n));
            let lift = 0.002 + 0.004 * rng.f32();
            (p + n * lift - yd * h * 0.5, xd * w, yd * h)
        }
        Mount::Wall => {
            let yt = jitter(rng, up_tangent(n), n, o.rotation_jitter.min(70.0));
            let tilt = rng.range(0.25, 0.75);
            let yd = (yt * tilt.cos() + n * tilt.sin()).normalize();
            let xd = yd.cross(n).normalize_or(any_perp(n));
            (p + n * 0.006, xd * w, yd * h)
        }
        Mount::Hanging => {
            let side = Vec3::Y.cross(n);
            let xd = if side.length_squared() > 1e-4 { side.normalize() } else { any_perp(Vec3::Y) };
            let xd = rotate(xd, Vec3::Y, rng.range(-0.5, 0.5));
            let out = Vec3::new(n.x, 0.0, n.z).normalize_or(Vec3::ZERO) * 0.03;
            (p + out - Vec3::Y * h, xd * w, Vec3::Y * h)
        }
    };
    Instance { c, mesh: cell.mesh, mount, p: base.into(), x: x.into(), y: y.into() }
}

/// Which surfaces foliage may grow on.
#[derive(Clone, Debug)]
pub struct SurfaceFilter {
    /// Only these mesh parts (None = all).
    pub parts: Option<Vec<u32>>,
    /// World box the points must be in.
    pub region: Option<(Vec3, Vec3)>,
    /// Allowed range of the surface normal's y (1 = facing up, 0 = wall,
    /// -1 = ceiling).
    pub up: (f32, f32),
}

impl Default for SurfaceFilter {
    fn default() -> Self {
        SurfaceFilter { parts: None, region: None, up: (-1.0, 1.0) }
    }
}

impl SurfaceFilter {
    /// `facing`: up (ground, ledges, roofs), walls, down (ceilings,
    /// undersides), any.
    pub fn facing(name: &str) -> Option<(f32, f32)> {
        Some(match name {
            "up" | "ground" | "top" => (0.7, 1.0),
            "walls" | "wall" | "horizontal" => (-0.35, 0.35),
            "down" | "ceiling" | "under" => (-1.0, -0.6),
            "any" => (-1.0, 1.0),
            _ => return None,
        })
    }
    fn keep(&self, parts: &Parts, t: usize, v: &[Vec3; 3], n: Vec3) -> bool {
        if let Some(ps) = &self.parts {
            if !ps.contains(&parts.triangle_part.get(t).copied().unwrap_or(u32::MAX)) {
                return false;
            }
        }
        if n.y < self.up.0 - 1e-4 || n.y > self.up.1 + 1e-4 {
            return false;
        }
        if let Some((lo, hi)) = self.region {
            let (tmin, tmax) = (v[0].min(v[1]).min(v[2]), v[0].max(v[1]).max(v[2]));
            if tmin.cmpgt(hi).any() || tmax.cmplt(lo).any() {
                return false;
            }
        }
        true
    }
}

/// Settings for a scatter or a brush dab.
pub struct ScatterOpts<'a> {
    /// Palette indices to use and their relative weights.
    pub cells: Vec<(u16, f32)>,
    /// Cell definitions, indexed like the palette.
    pub defs: &'a [FoliageCell],
    pub count: usize,
    pub seed: u64,
    pub filter: SurfaceFilter,
    /// Minimum distance between card bases (also against existing cards).
    pub min_spacing: f32,
    pub place: PlaceOpts,
}

/// A spatial hash of points for spacing checks.
struct PointGrid {
    cell: f32,
    map: std::collections::HashMap<(i32, i32, i32), Vec<Vec3>>,
}

impl PointGrid {
    fn new(cell: f32) -> PointGrid {
        PointGrid { cell: cell.max(1e-3), map: Default::default() }
    }
    fn key(&self, p: Vec3) -> (i32, i32, i32) {
        ((p.x / self.cell).floor() as i32, (p.y / self.cell).floor() as i32, (p.z / self.cell).floor() as i32)
    }
    fn insert(&mut self, p: Vec3) {
        let k = self.key(p);
        self.map.entry(k).or_default().push(p);
    }
    fn near(&self, p: Vec3, r: f32) -> bool {
        let k = self.key(p);
        for dz in -1..=1 {
            for dy in -1..=1 {
                for dx in -1..=1 {
                    if let Some(v) = self.map.get(&(k.0 + dx, k.1 + dy, k.2 + dz)) {
                        if v.iter().any(|q| q.distance_squared(p) < r * r) {
                            return true;
                        }
                    }
                }
            }
        }
        false
    }
}

fn pick_cell(cells: &[(u16, f32)], rng: &mut Rng) -> u16 {
    let total: f32 = cells.iter().map(|c| c.1.max(0.0)).sum();
    let mut r = rng.f32() * total;
    for (c, w) in cells {
        r -= w.max(0.0);
        if r <= 0.0 {
            return *c;
        }
    }
    cells.last().map(|c| c.0).unwrap_or(0)
}

/// Scatter cards over a sampler's triangles. `accept(triangle, barycentric,
/// point, normal)` returns a 0..1 probability (masks, AO). Spacing is checked
/// against `existing` too.
fn scatter_on(sampler: &SurfaceSampler, o: &ScatterOpts, existing: &[Instance], accept: &dyn Fn(&SurfaceTri, Vec3, Vec3) -> f32, inside: &dyn Fn(Vec3) -> bool) -> Vec<Instance> {
    let mut rng = Rng::new(o.seed);
    let mut out = Vec::new();
    if sampler.tris.is_empty() || o.cells.is_empty() || o.count == 0 {
        return out;
    }
    let mut grid = PointGrid::new(o.min_spacing.max(0.02));
    if o.min_spacing > 0.0 {
        for i in existing {
            grid.insert(i.pos());
        }
    }
    let tries = o.count * 30 + 200;
    for _ in 0..tries {
        if out.len() >= o.count {
            break;
        }
        let Some((st, p, bary)) = sampler.sample(&mut rng) else { break };
        if !inside(p) {
            continue;
        }
        if let Some((lo, hi)) = o.filter.region {
            if p.cmplt(lo).any() || p.cmpgt(hi).any() {
                continue;
            }
        }
        let a = accept(st, bary, p);
        if a <= 0.0 || rng.f32() > a {
            continue;
        }
        if o.min_spacing > 0.0 && grid.near(p, o.min_spacing) {
            continue;
        }
        let c = pick_cell(&o.cells, &mut rng);
        let Some(def) = o.defs.get(c as usize) else { continue };
        let inst = place(def, c, p, st.n, &mut rng, &o.place);
        if inst.mount == Mount::Upright && Vec3::from(inst.y).y < -0.2 * Vec3::from(inst.y).length() {
            continue; // upright plants don't grow upside down
        }
        grid.insert(p);
        out.push(inst);
    }
    out
}

/// Scatter `o.count` cards over the whole (filtered) mesh.
pub fn scatter(mesh: &Mesh, parts: &Parts, o: &ScatterOpts, existing: &[Instance], accept: &dyn Fn(&SurfaceTri, Vec3, Vec3) -> f32) -> Vec<Instance> {
    let sampler = SurfaceSampler::new(mesh, |t, v, n| o.filter.keep(parts, t, v, n));
    scatter_on(&sampler, o, existing, accept, &|_| true)
}

/// Area of the filtered surface (m²), e.g. to turn a density into a count.
pub fn surface_area(mesh: &Mesh, parts: &Parts, f: &SurfaceFilter) -> f32 {
    SurfaceSampler::new(mesh, |t, v, n| f.keep(parts, t, v, n)).total
}

/// Closest point to `p` on triangle abc (Ericson, Real-Time Collision Detection 5.1.5).
pub fn closest_on_triangle(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> Vec3 {
    let (ab, ac, ap) = (b - a, c - a, p - a);
    let (d1, d2) = (ab.dot(ap), ac.dot(ap));
    if d1 <= 0.0 && d2 <= 0.0 {
        return a;
    }
    let bp = p - b;
    let (d3, d4) = (ab.dot(bp), ac.dot(bp));
    if d3 >= 0.0 && d4 <= d3 {
        return b;
    }
    let vc = d1 * d4 - d3 * d2;
    if vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0 {
        return a + ab * (d1 / (d1 - d3));
    }
    let cp = p - c;
    let (d5, d6) = (ab.dot(cp), ac.dot(cp));
    if d6 >= 0.0 && d5 <= d6 {
        return c;
    }
    let vb = d5 * d2 - d1 * d6;
    if vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0 {
        return a + ac * (d2 / (d2 - d6));
    }
    let va = d3 * d6 - d5 * d4;
    if va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0 {
        return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)));
    }
    let denom = 1.0 / (va + vb + vc);
    a + ab * (vb * denom) + ac * (vc * denom)
}

/// One brush dab: up to `count` cards within `radius` of `center` on the
/// filtered surface, spaced from each other and from `existing`.
pub fn paint_dab(mesh: &Mesh, parts: &Parts, center: Vec3, radius: f32, o: &ScatterOpts, existing: &[Instance], accept: &dyn Fn(&SurfaceTri, Vec3, Vec3) -> f32) -> Vec<Instance> {
    let r2 = radius * radius;
    let sampler = SurfaceSampler::new(mesh, |t, v, n| {
        let (lo, hi) = (v[0].min(v[1]).min(v[2]), v[0].max(v[1]).max(v[2]));
        if (center - center.clamp(lo, hi)).length_squared() > r2 {
            return false;
        }
        closest_on_triangle(center, v[0], v[1], v[2]).distance_squared(center) <= r2 && o.filter.keep(parts, t, v, n)
    });
    scatter_on(&sampler, o, existing, accept, &|p| p.distance_squared(center) <= r2)
}

/// Uniform grid of triangles for closest-point queries (ivy growth).
pub struct TriGrid {
    cell: f32,
    lo: Vec3,
    dims: [i32; 3],
    cells: std::collections::HashMap<i32, Vec<u32>>,
    tris: Vec<SurfaceTri>,
}

impl TriGrid {
    pub fn new(mesh: &Mesh, parts: &Parts, filter: &SurfaceFilter, cell: f32) -> TriGrid {
        // no normal filter: ivy may cross any surface of the allowed parts
        let f = SurfaceFilter { up: (-1.0, 1.0), ..filter.clone() };
        let s = SurfaceSampler::new(mesh, |t, v, n| f.keep(parts, t, v, n));
        let (mut lo, mut hi) = (Vec3::splat(f32::MAX), Vec3::splat(f32::MIN));
        for t in &s.tris {
            for v in t.v {
                lo = lo.min(v);
                hi = hi.max(v);
            }
        }
        let cell = cell.max(0.02);
        let dims = if s.tris.is_empty() { [1; 3] } else { ((hi - lo) / cell).ceil().as_ivec3().max(glam::IVec3::ONE).to_array() };
        let mut g = TriGrid { cell, lo, dims, cells: Default::default(), tris: s.tris };
        for (i, t) in g.tris.iter().enumerate() {
            let (a, b) = (t.v[0].min(t.v[1]).min(t.v[2]), t.v[0].max(t.v[1]).max(t.v[2]));
            let (ka, kb) = (g.coord(a), g.coord(b));
            for z in ka[2]..=kb[2] {
                for y in ka[1]..=kb[1] {
                    for x in ka[0]..=kb[0] {
                        let k = g.key([x, y, z]);
                        g.cells.entry(k).or_default().push(i as u32);
                    }
                }
            }
        }
        g
    }
    fn coord(&self, p: Vec3) -> [i32; 3] {
        let c = ((p - self.lo) / self.cell).floor().as_ivec3();
        [c.x.clamp(0, self.dims[0] - 1), c.y.clamp(0, self.dims[1] - 1), c.z.clamp(0, self.dims[2] - 1)]
    }
    fn key(&self, c: [i32; 3]) -> i32 {
        (c[2] * self.dims[1] + c[1]) * self.dims[0] + c[0]
    }
    pub fn is_empty(&self) -> bool {
        self.tris.is_empty()
    }
    /// Closest surface point within `radius`: (point, normal).
    pub fn closest(&self, p: Vec3, radius: f32) -> Option<(Vec3, Vec3)> {
        let (a, b) = (self.coord(p - Vec3::splat(radius)), self.coord(p + Vec3::splat(radius)));
        let mut best: Option<(f32, Vec3, Vec3)> = None;
        let mut seen = std::collections::HashSet::new();
        for z in a[2]..=b[2] {
            for y in a[1]..=b[1] {
                for x in a[0]..=b[0] {
                    let Some(list) = self.cells.get(&self.key([x, y, z])) else { continue };
                    for &i in list {
                        if !seen.insert(i) {
                            continue;
                        }
                        let t = &self.tris[i as usize];
                        let q = closest_on_triangle(p, t.v[0], t.v[1], t.v[2]);
                        let d = q.distance_squared(p);
                        if d <= radius * radius && best.is_none_or(|b| d < b.0) {
                            best = Some((d, q, t.n));
                        }
                    }
                }
            }
        }
        best.map(|b| (b.1, b.2))
    }
}

/// Ivy growth settings.
#[derive(Clone, Debug)]
pub struct IvyOpts {
    /// Length of the main strand from each start point, metres.
    pub length: f32,
    /// Step of the walk, metres.
    pub step: f32,
    /// Side branches per metre of strand.
    pub branching: f32,
    pub max_strands: usize,
    /// Pull towards climbing up (0..1).
    pub up_bias: f32,
    /// Random wander (0..1).
    pub wander: f32,
    /// Distance between leaves along a strand, metres.
    pub leaf_spacing: f32,
    /// Leaf card scale range.
    pub leaf_scale: (f32, f32),
    /// Stem width, metres.
    pub stem_width: f32,
    pub seed: u64,
}

impl Default for IvyOpts {
    fn default() -> Self {
        IvyOpts { length: 2.5, step: 0.04, branching: 1.2, max_strands: 48, up_bias: 0.7, wander: 0.35, leaf_spacing: 0.06, leaf_scale: (0.8, 1.25), stem_width: 0.012, seed: 1 }
    }
}

/// What a growth walk made.
#[derive(Clone, Debug, Default)]
pub struct IvyResult {
    pub instances: Vec<Instance>,
    pub strands: usize,
    /// Total stem length, metres.
    pub length: f32,
}

/// Grow ivy from `starts` (surface points + normals) along the surface.
/// `leaf` / `stem` are palette indices with their cell definitions.
pub fn grow_ivy(grid: &TriGrid, starts: &[(Vec3, Vec3)], leaf: (u16, &FoliageCell), stem: Option<(u16, &FoliageCell)>, o: &IvyOpts) -> IvyResult {
    let mut rng = Rng::new(o.seed);
    let mut res = IvyResult::default();
    if grid.is_empty() {
        return res;
    }
    let step = o.step.max(0.005);
    let search = step * 1.6;
    // (position, normal, direction, length budget)
    let mut queue: Vec<(Vec3, Vec3, Vec3, f32)> = Vec::new();
    for &(p, n) in starts {
        let Some((q, nq)) = grid.closest(p, 0.5) else { continue };
        let n = if nq.dot(n) < 0.0 && n.length_squared() > 0.0 { nq } else { nq };
        queue.push((q, n, up_tangent(n), o.length));
    }
    let place_opts = PlaceOpts { scale: o.leaf_scale, rotation_jitter: 60.0, ..Default::default() };
    while let Some((mut p, mut n, mut dir, budget)) = queue.pop() {
        if res.strands >= o.max_strands {
            break;
        }
        res.strands += 1;
        let mut walked = 0.0f32;
        let mut since_leaf = rng.f32() * o.leaf_spacing;
        let mut side = 1.0f32;
        while walked < budget {
            let up_t = up_tangent(n);
            let rnd = (Vec3::new(rng.range(-1.0, 1.0), rng.range(-1.0, 1.0), rng.range(-1.0, 1.0)) - n * 0.0).normalize_or(Vec3::X);
            let rnd = (rnd - n * rnd.dot(n)).normalize_or(up_t);
            let mut d = (dir * 0.65 + up_t * o.up_bias + rnd * o.wander).normalize_or(up_t);
            d = (d - n * d.dot(n)).normalize_or(up_t);
            // stay on the surface: step, then snap back; round convex corners
            let guess = p + d * step + n * step * 0.25;
            let hit = grid.closest(guess, search).or_else(|| grid.closest(p + d * step * 0.5 - n * step, search));
            let Some((q, nq)) = hit else { break };
            let seg = q - p;
            let len = seg.length();
            if len < step * 0.2 {
                break;
            }
            // stem
            if let Some((sc, scell)) = stem {
                let yd = seg / len;
                let xd = yd.cross((n + nq).normalize_or(n)).normalize_or(any_perp(nq));
                let lift = (n + nq).normalize_or(nq) * 0.004;
                let w = o.stem_width * (1.0 - 0.6 * (walked / budget.max(1e-3))).max(0.35);
                let _ = scell;
                res.instances.push(Instance { c: sc, mesh: CardMesh::Quad, mount: Mount::Flat, p: (p + lift - yd * len * 0.1).into(), x: (xd * w).into(), y: (yd * len * 1.2).into() });
            }
            since_leaf += len;
            while since_leaf >= o.leaf_spacing {
                since_leaf -= o.leaf_spacing;
                side = -side;
                let at = p + seg * rng.f32();
                let mut inst = place(leaf.1, leaf.0, at, nq, &mut rng, &place_opts);
                // lean the leaf out to its side of the stem
                let yd = Vec3::from(inst.y);
                let lateral = seg.cross(nq).normalize_or(Vec3::ZERO) * side;
                let ny = (yd.normalize() + lateral * 0.8).normalize_or(yd.normalize()) * yd.length();
                let nx = ny.cross(nq).normalize_or(any_perp(nq)) * Vec3::from(inst.x).length();
                inst.y = ny.into();
                inst.x = nx.into();
                res.instances.push(inst);
            }
            // branch
            if rng.f32() < o.branching * len && res.strands + queue.len() < o.max_strands {
                let a = if rng.f32() < 0.5 { -1.0 } else { 1.0 } * rng.range(0.5, 1.1);
                queue.push((q, nq, rotate(d, nq, a), (budget - walked) * rng.range(0.35, 0.65)));
            }
            walked += len;
            res.length += len;
            dir = (seg / len - nq * (seg / len).dot(nq)).normalize_or(up_tangent(nq));
            p = q;
            n = nq;
        }
    }
    res
}

/// Atlas layout of the cells a set uses: UV rect (v down) per palette entry.
pub type CellUv = [f32; 4];

/// Every card as one triangle mesh (two triangles per quad), UVs in the
/// atlas. Upright / hanging cards get normals bent towards their up axis
/// (softer, grass-like shading); flat and wall cards keep the card normal.
pub fn card_mesh(set: &FoliageSet, uvs: &[Option<CellUv>], name: &str) -> Mesh {
    let mut vertices = Vec::new();
    let mut indices = Vec::new();
    for inst in &set.instances {
        let Some(Some(uv)) = uvs.get(inst.c as usize) else { continue };
        let p = Vec3::from(inst.p);
        let y = Vec3::from(inst.y);
        let up = y.normalize_or(Vec3::Y);
        for x in inst.quad_x() {
            let cn = x.cross(y).normalize_or(Vec3::Z);
            let n = match inst.mount {
                Mount::Upright | Mount::Hanging => (cn * 0.35 + up * 0.65).normalize(),
                _ => cn,
            };
            let base = vertices.len() as u32;
            for (s, t) in [(-0.5f32, 0.0f32), (0.5, 0.0), (0.5, 1.0), (-0.5, 1.0)] {
                let pos = p + x * s + y * t;
                let u = uv[0] + (s + 0.5) * (uv[2] - uv[0]);
                let v = uv[3] - t * (uv[3] - uv[1]);
                let tan = x.normalize_or(Vec3::X);
                vertices.push(Vertex { position: pos.into(), normal: n.into(), uv: [u, v], tangent: [tan.x, tan.y, tan.z, 1.0] });
            }
            indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        }
    }
    Mesh { name: name.into(), vertices, indices, has_uvs: true }
}

/// Godot / engine friendly instance lists: per palette cell, its UV rect,
/// mesh kind and a flat list of 12 floats per instance: basis columns x, y,
/// z then the origin, for a unit card spanning x in -0.5..0.5, y in 0..1
/// (z = unit card normal x card width, so a cross card's second quad keeps
/// its width). Glb / Godot share Pigment's axes (Y up, metres).
pub fn instances_json(set: &FoliageSet, uvs: &[Option<CellUv>], defs: &[Option<&FoliageCell>]) -> serde_json::Value {
    let mut groups: Vec<serde_json::Value> = Vec::new();
    for (ci, name) in set.cells.iter().enumerate() {
        let list: Vec<&Instance> = set.instances.iter().filter(|i| i.c as usize == ci).collect();
        if list.is_empty() {
            continue;
        }
        let uv = uvs.get(ci).copied().flatten().unwrap_or([0.0, 0.0, 1.0, 1.0]);
        let def = defs.get(ci).copied().flatten();
        let mut xf: Vec<f32> = Vec::with_capacity(list.len() * 12);
        let mut mesh = def.map(|d| d.mesh).unwrap_or_default();
        for i in &list {
            mesh = i.mesh;
            let (x, y) = (Vec3::from(i.x), Vec3::from(i.y));
            let z = i.normal() * x.length();
            xf.extend_from_slice(&[x.x, x.y, x.z, y.x, y.y, y.z, z.x, z.y, z.z, i.p[0], i.p[1], i.p[2]]);
        }
        let r = |v: f32| (v * 10000.0).round() / 10000.0;
        groups.push(serde_json::json!({
            "cell": name,
            "uv": uv, "uv_gl": [uv[0], 1.0 - uv[3], uv[2], 1.0 - uv[1]],
            "mesh": mesh.id(),
            "mount": def.map(|d| d.mount.id()).unwrap_or("upright"),
            "size_m": def.map(|d| d.size_m),
            "count": list.len(),
            "transforms": xf.into_iter().map(r).collect::<Vec<_>>(),
        }));
    }
    serde_json::json!({
        "format": "pigment-foliage-instances", "version": 1,
        "axes": "Y up, metres (same as the painted mesh / glb)",
        "card": "unit quad: x -0.5..0.5, y 0..1 (y = 0 at the bottom of the cell); cross = + the same quad rotated 90 deg about y; star = 3 quads at 60 deg",
        "transform_layout": "per instance 12 floats: basis column x, column y, column z, origin (Godot Transform3D(Basis(x, y, z), origin))",
        "atlas": set.atlas,
        "instances": set.instances.len(),
        "groups": groups,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::foliage::FoliageCell;

    /// A 4 x 4 m floor at y = 0 and a 4 m wide, 3 m tall wall facing +Z at z = -2.
    fn yard() -> Mesh {
        let v = |p: [f32; 3], n: [f32; 3]| Vertex { position: p, normal: n, uv: [0.0, 0.0], tangent: [1.0, 0.0, 0.0, 1.0] };
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        // gridded so the closest-point walk has neighbours
        let n = 8;
        let quad = |vertices: &mut Vec<Vertex>, indices: &mut Vec<u32>, f: &dyn Fn(f32, f32) -> [f32; 3], nn: [f32; 3]| {
            let b = vertices.len() as u32;
            for j in 0..=n {
                for i in 0..=n {
                    vertices.push(v(f(i as f32 / n as f32, j as f32 / n as f32), nn));
                }
            }
            for j in 0..n {
                for i in 0..n {
                    let a = b + j * (n + 1) + i;
                    indices.extend_from_slice(&[a, a + 1, a + n + 2, a, a + n + 2, a + n + 1]);
                }
            }
        };
        quad(&mut vertices, &mut indices, &|u, w| [-2.0 + 4.0 * u, 0.0, -2.0 + 4.0 * w], [0.0, 1.0, 0.0]);
        quad(&mut vertices, &mut indices, &|u, w| [-2.0 + 4.0 * u, 3.0 * w, -2.0], [0.0, 0.0, 1.0]);
        Mesh { name: "yard".into(), vertices, indices, has_uvs: true }
    }

    fn defs() -> Vec<FoliageCell> {
        vec![FoliageCell::from_preset("grass", "grass").unwrap(), FoliageCell::from_preset("ivy_leaf", "ivy_leaf").unwrap(), FoliageCell::from_preset("ivy_stem", "ivy_stem").unwrap()]
    }

    #[test]
    fn scatter_respects_facing_spacing_and_mask() {
        let m = yard();
        let parts = m.parts();
        let d = defs();
        let o = ScatterOpts { cells: vec![(0, 1.0)], defs: &d, count: 60, seed: 4, filter: SurfaceFilter { up: SurfaceFilter::facing("up").unwrap(), ..Default::default() }, min_spacing: 0.2, place: PlaceOpts::default() };
        let got = scatter(&m, &parts, &o, &[], &|_, _, _| 1.0);
        assert_eq!(got.len(), 60);
        for (k, a) in got.iter().enumerate() {
            assert!(a.p[1].abs() < 0.05, "on the floor");
            assert!(Vec3::from(a.y).y > 0.0, "grass stands up");
            for b in &got[k + 1..] {
                assert!(a.pos().distance(b.pos()) > 0.18);
            }
        }
        // same seed, same result
        assert_eq!(got, scatter(&m, &parts, &o, &[], &|_, _, _| 1.0));
        // a mask that only allows x > 0
        let half = scatter(&m, &parts, &o, &[], &|_, _, p| if p.x > 0.0 { 1.0 } else { 0.0 });
        assert!(!half.is_empty() && half.iter().all(|i| i.p[0] > -0.1));
        // walls only
        let ow = ScatterOpts { filter: SurfaceFilter { up: SurfaceFilter::facing("walls").unwrap(), ..Default::default() }, cells: vec![(1, 1.0)], ..o };
        let wall = scatter(&m, &parts, &ow, &[], &|_, _, _| 1.0);
        assert!(!wall.is_empty() && wall.iter().all(|i| (i.p[2] + 2.0).abs() < 0.05));
        // spacing against existing cards: a second pass fills only gaps
        let more = scatter(&m, &parts, &ScatterOpts { seed: 9, ..ow }, &wall, &|_, _, _| 1.0);
        for a in &more {
            assert!(wall.iter().all(|b| a.pos().distance(b.pos()) > 0.18));
        }
    }

    #[test]
    fn brush_dab_stays_in_its_sphere_and_erase_removes() {
        let m = yard();
        let parts = m.parts();
        let d = defs();
        let o = ScatterOpts { cells: vec![(0, 1.0)], defs: &d, count: 40, seed: 2, filter: SurfaceFilter::default(), min_spacing: 0.05, place: PlaceOpts::default() };
        let c = Vec3::new(0.5, 0.0, 0.5);
        let got = paint_dab(&m, &parts, c, 0.3, &o, &[], &|_, _, _| 1.0);
        assert!(got.len() > 10);
        assert!(got.iter().all(|i| i.pos().distance(c) < 0.31));
        let mut set = FoliageSet { instances: got, cells: vec!["grass".into()], ..Default::default() };
        let n = set.instances.len();
        assert_eq!(set.erase(&[c], 0.5, None), n);
    }

    #[test]
    fn ivy_climbs_the_wall_and_branches() {
        let m = yard();
        let parts = m.parts();
        let grid = TriGrid::new(&m, &parts, &SurfaceFilter::default(), 0.25);
        let d = defs();
        let o = IvyOpts { length: 2.0, seed: 3, ..Default::default() };
        let r = grow_ivy(&grid, &[(Vec3::new(0.0, 0.05, -1.95), Vec3::Z)], (1, &d[1]), Some((2, &d[2])), &o);
        assert!(r.strands > 1, "branches: {}", r.strands);
        assert!(r.length > 1.5, "length {}", r.length);
        let top = r.instances.iter().map(|i| i.p[1]).fold(0.0f32, f32::max);
        assert!(top > 1.0, "climbed to {top}");
        // everything hugs the wall (or the floor it started on)
        for i in &r.instances {
            let p = i.pos();
            assert!((p.z + 2.0).abs() < 0.12 || p.y.abs() < 0.12, "off the surface: {p}");
        }
        assert!(r.instances.iter().any(|i| i.c == 1) && r.instances.iter().any(|i| i.c == 2));
    }

    #[test]
    fn exports_cards_and_instance_lists() {
        let d = defs();
        let mut set = FoliageSet::default();
        let c0 = set.cell_index("grass");
        let mut rng = Rng::new(1);
        set.instances.push(place(&d[0], c0, Vec3::ZERO, Vec3::Y, &mut rng, &PlaceOpts::default()));
        let mesh = card_mesh(&set, &[Some([0.0, 0.0, 0.5, 0.5])], "f");
        // grass is a cross card: 2 quads
        assert_eq!(mesh.indices.len(), 12);
        let j = instances_json(&set, &[Some([0.0, 0.0, 0.5, 0.5])], &[Some(&d[0])]);
        assert_eq!(j["groups"][0]["transforms"].as_array().unwrap().len(), 12);
        assert_eq!(j["groups"][0]["mesh"], "cross");
        let s = serde_json::to_string(&set).unwrap();
        assert_eq!(serde_json::from_str::<FoliageSet>(&s).unwrap(), set);
        assert_eq!(serde_json::from_str::<FoliageSet>("{}").unwrap().atlas, "builtin");
    }
}
