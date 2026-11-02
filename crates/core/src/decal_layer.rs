//! Non-destructive decal layers: a paint layer that owns a list of decal
//! objects (image, transform, projection, look). The app regenerates the
//! layer's pixels from the objects whenever they change, so decals can be
//! moved, rotated, scaled, re-ordered, re-imaged, hidden or deleted at any
//! time (and undo is a document change).
//!
//! Also the CPU side of placement:
//! - **projections**: `Box` (planar, the classic box decal), `Triplanar`
//!   (the image projected along the decal frame's three axes, blended by
//!   the surface normal: wraps over box corners) and `Wrap` (conform: the
//!   surface around the decal is unfolded triangle by triangle into the
//!   decal plane, a geodesic-ish parameterisation that follows curves and
//!   corners);
//! - **smart region fill**: the largest flat, hole-free (window-free)
//!   rectangle on the walls, for a poster or a grid of posters;
//! - **snapping** to a region's centre or edges, and grid / array layouts.

use crate::decal::Placement;
use crate::{Channel, MaterialValues, Mesh};
use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecalProjection {
    /// Planar box projection along the decal normal.
    #[default]
    Box,
    /// Projected along the decal frame's three axes, blended by the surface normal.
    Triplanar,
    /// Conforms to the surface: unfolded from the decal centre outwards.
    Wrap,
}

impl DecalProjection {
    pub fn from_id(s: &str) -> Option<Self> {
        match s.to_ascii_lowercase().as_str() {
            "box" | "planar" => Some(DecalProjection::Box),
            "triplanar" | "tri" => Some(DecalProjection::Triplanar),
            "wrap" | "conform" | "geodesic" => Some(DecalProjection::Wrap),
            _ => None,
        }
    }
    pub fn id(self) -> &'static str {
        match self {
            DecalProjection::Box => "box",
            DecalProjection::Triplanar => "triplanar",
            DecalProjection::Wrap => "wrap",
        }
    }
    /// GPU mode (decal_box.wgsl).
    pub fn gpu_id(self) -> u32 {
        self as u32
    }
}

/// Opacity and weathering (see `decal_box.wgsl`).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct DecalWear {
    pub opacity: f32,
    pub alpha_from_luminance: bool,
    pub tear: f32,
    pub fade: f32,
    pub wear_scale: f32,
    pub seed: f32,
    pub grunge: bool,
    pub paper_rim: f32,
}

impl Default for DecalWear {
    fn default() -> Self {
        DecalWear { opacity: 1.0, alpha_from_luminance: false, tear: 0.0, fade: 0.0, wear_scale: 5.0, seed: 0.0, grunge: false, paper_rim: 0.035 }
    }
}

/// One editable decal.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DecalObject {
    pub id: u32,
    pub name: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub group: String,
    /// Image path (relative paths resolve like image fills).
    pub image: String,
    pub center: [f32; 3],
    pub normal: [f32; 3],
    /// Width, height in metres.
    pub size: [f32; 2],
    /// Degrees, counter-clockwise seen from outside.
    #[serde(default)]
    pub rotation: f32,
    /// Box half-thickness (metres).
    pub depth: f32,
    #[serde(default)]
    pub projection: DecalProjection,
    #[serde(default)]
    pub wear: DecalWear,
    /// Material values painted where the decal is opaque (colour = image x base colour).
    #[serde(default = "white_decal")]
    pub values: MaterialValues,
    /// Channels it paints (default colour, roughness, metallic).
    #[serde(default = "default_channels")]
    pub channels: Vec<Channel>,
    #[serde(default = "yes")]
    pub enabled: bool,
}

fn yes() -> bool {
    true
}
pub fn white_decal() -> MaterialValues {
    MaterialValues { base_color: [1.0; 3], roughness: 0.55, ..Default::default() }
}
pub fn default_channels() -> Vec<Channel> {
    vec![Channel::BaseColor, Channel::Roughness, Channel::Metallic]
}

impl DecalObject {
    pub fn placement(&self) -> Placement {
        Placement::new(Vec3::from(self.center), Vec3::from(self.normal), Vec2::from(self.size), self.rotation, self.depth)
    }
}

/// The decals of a decal layer, bottom to top.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct DecalSet {
    pub objects: Vec<DecalObject>,
    #[serde(default)]
    pub next_id: u32,
}

impl DecalSet {
    pub fn add(&mut self, mut d: DecalObject) -> u32 {
        self.next_id = self.next_id.max(self.objects.iter().map(|o| o.id + 1).max().unwrap_or(0));
        d.id = self.next_id;
        self.next_id += 1;
        if d.name.is_empty() {
            d.name = format!("decal_{}", d.id);
        }
        self.objects.push(d);
        self.next_id - 1
    }
    /// By id ("12" or 12) or name (case-insensitive).
    pub fn find(&self, key: &str) -> Option<usize> {
        if let Ok(id) = key.parse::<u32>() {
            if let Some(i) = self.objects.iter().position(|o| o.id == id) {
                return Some(i);
            }
        }
        self.objects.iter().position(|o| o.name.eq_ignore_ascii_case(key))
    }
}

// ------------------------------------------------------------------ regions

/// A flat rectangle on the surface (a wall area free of windows / holes).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Region {
    pub center: Vec3,
    pub normal: Vec3,
    pub right: Vec3,
    pub up: Vec3,
    /// Width, height in metres.
    pub size: Vec2,
}

impl Region {
    pub fn area(&self) -> f32 {
        self.size.x * self.size.y
    }
}

/// Region search options.
#[derive(Clone, Debug)]
pub struct RegionQuery {
    /// Triangles to consider (None = all).
    pub triangles: Option<Vec<bool>>,
    /// Walls only: |normal.y| below this (1 = any orientation).
    pub max_normal_y: f32,
    /// World height band of the rectangle (None = any).
    pub height: Option<(f32, f32)>,
    /// Grid cell (metres).
    pub cell: f32,
    /// Margin kept free inside the rectangle (metres).
    pub margin: f32,
    /// How many planes to search (largest first).
    pub planes: usize,
}

impl Default for RegionQuery {
    fn default() -> Self {
        RegionQuery { triangles: None, max_normal_y: 0.3, height: None, cell: 0.05, margin: 0.05, planes: 16 }
    }
}

fn frame(n: Vec3) -> (Vec3, Vec3) {
    let up0 = if n.y.abs() >= 0.9 { Vec3::NEG_Z } else { Vec3::Y };
    let up = (up0 - n * n.dot(up0)).normalize();
    (up.cross(n).normalize(), up)
}

/// Largest rectangle of `true` cells (histogram method): (x, y, w, h).
fn largest_rect(grid: &[bool], w: usize, h: usize) -> Option<(usize, usize, usize, usize)> {
    let mut heights = vec![0usize; w];
    let mut best: Option<(usize, usize, usize, usize)> = None;
    let mut best_area = 0;
    for y in 0..h {
        for x in 0..w {
            heights[x] = if grid[y * w + x] { heights[x] + 1 } else { 0 };
        }
        let mut stack: Vec<usize> = Vec::new();
        for x in 0..=w {
            let cur = if x < w { heights[x] } else { 0 };
            while let Some(&top) = stack.last() {
                if heights[top] <= cur {
                    break;
                }
                stack.pop();
                let hh = heights[top];
                let left = stack.last().map(|l| l + 1).unwrap_or(0);
                let ww = x - left;
                if hh * ww > best_area {
                    best_area = hh * ww;
                    best = Some((left, y + 1 - hh, ww, hh));
                }
            }
            stack.push(x);
        }
    }
    best
}

/// The largest flat, hole-free rectangles on the mesh's walls, biggest first
/// (one per plane).
pub fn find_regions(mesh: &Mesh, q: &RegionQuery) -> Vec<Region> {
    // group triangles by plane (quantised normal and offset)
    let mut planes: HashMap<(i32, i32, i32, i32), (Vec3, f32, Vec<usize>)> = HashMap::new();
    for t in 0..mesh.triangle_count() {
        if q.triangles.as_ref().is_some_and(|s| !s.get(t).copied().unwrap_or(false)) {
            continue;
        }
        let p = [0, 1, 2].map(|k| Vec3::from(mesh.vertices[mesh.indices[t * 3 + k] as usize].position));
        let c = (p[1] - p[0]).cross(p[2] - p[0]);
        let area = c.length() * 0.5;
        if area < 1e-6 {
            continue;
        }
        let n = c / (2.0 * area);
        if n.y.abs() > q.max_normal_y {
            continue;
        }
        let d = n.dot(p[0]);
        let key = ((n.x * 20.0).round() as i32, (n.y * 20.0).round() as i32, (n.z * 20.0).round() as i32, (d / 0.02).round() as i32);
        let e = planes.entry(key).or_insert((Vec3::ZERO, 0.0, Vec::new()));
        e.0 += n * area;
        e.1 += area;
        e.2.push(t);
    }
    // deterministic: by area, ties by plane key (HashMap order varies per run)
    let mut list: Vec<((i32, i32, i32, i32), (Vec3, f32, Vec<usize>))> = planes.into_iter().collect();
    list.sort_by(|a, b| b.1 .1.total_cmp(&a.1 .1).then(a.0.cmp(&b.0)));
    let list: Vec<(Vec3, f32, Vec<usize>)> = list.into_iter().map(|x| x.1).collect();
    let mut out = Vec::new();
    for (nsum, _, tris) in list.into_iter().take(q.planes) {
        let n = nsum.normalize();
        let (right, up) = frame(n);
        let p0 = Vec3::from(mesh.vertices[mesh.indices[tris[0] * 3] as usize].position);
        let d = n.dot(p0);
        let to2 = |p: Vec3| Vec2::new(p.dot(right), p.dot(up));
        let mut lo = Vec2::splat(f32::MAX);
        let mut hi = Vec2::splat(f32::MIN);
        let tri2: Vec<[Vec2; 3]> = tris
            .iter()
            .map(|&t| {
                let v = [0, 1, 2].map(|k| to2(Vec3::from(mesh.vertices[mesh.indices[t * 3 + k] as usize].position)));
                for x in v {
                    lo = lo.min(x);
                    hi = hi.max(x);
                }
                v
            })
            .collect();
        let ext = hi - lo;
        let cell = q.cell.max(ext.max_element() / 400.0).max(1e-3);
        let (w, h) = ((ext.x / cell).ceil() as usize + 1, (ext.y / cell).ceil() as usize + 1);
        let mut grid = vec![false; w * h];
        for t in &tri2 {
            let tl = t[0].min(t[1]).min(t[2]);
            let th = t[0].max(t[1]).max(t[2]);
            let (x0, y0) = (((tl.x - lo.x) / cell).floor().max(0.0) as usize, ((tl.y - lo.y) / cell).floor().max(0.0) as usize);
            let (x1, y1) = ((((th.x - lo.x) / cell).ceil() as usize).min(w - 1), (((th.y - lo.y) / cell).ceil() as usize).min(h - 1));
            let det = (t[1] - t[0]).perp_dot(t[2] - t[0]);
            if det.abs() < 1e-12 {
                continue;
            }
            for y in y0..=y1 {
                for x in x0..=x1 {
                    let pc = lo + Vec2::new(x as f32 + 0.5, y as f32 + 0.5) * cell;
                    let a = (t[1] - t[0]).perp_dot(pc - t[0]) / det;
                    let b = (pc - t[0]).perp_dot(t[2] - t[0]) / det;
                    if a >= -1e-4 && b >= -1e-4 && a + b <= 1.0 + 1e-4 {
                        grid[y * w + x] = true;
                    }
                }
            }
        }
        // height band (world y of the cell centre, along `up`)
        if let Some((ymin, ymax)) = q.height {
            for y in 0..h {
                for x in 0..w {
                    let p2 = lo + Vec2::new(x as f32 + 0.5, y as f32 + 0.5) * cell;
                    let world = right * p2.x + up * p2.y + n * d;
                    if world.y - cell * 0.5 < ymin || world.y + cell * 0.5 > ymax {
                        grid[y * w + x] = false;
                    }
                }
            }
        }
        let Some((x, y, rw, rh)) = largest_rect(&grid, w, h) else { continue };
        let size = Vec2::new(rw as f32, rh as f32) * cell - Vec2::splat(2.0 * q.margin);
        if size.x <= 0.0 || size.y <= 0.0 {
            continue;
        }
        let c2 = lo + Vec2::new(x as f32 + rw as f32 * 0.5, y as f32 + rh as f32 * 0.5) * cell;
        out.push(Region { center: right * c2.x + up * c2.y + n * d, normal: n, right, up, size });
    }
    // ties (symmetric walls): a fixed order by position
    out.sort_by(|a, b| {
        let key = |r: &Region| (r.area() * 1e3).round();
        key(b).total_cmp(&key(a)).then(a.center.x.total_cmp(&b.center.x)).then(a.center.z.total_cmp(&b.center.z)).then(a.center.y.total_cmp(&b.center.y))
    });
    out
}

/// Fit an image of `aspect` (w / h) into a region: (centre, size).
pub fn fit_in(r: &Region, aspect: f32, fill: f32) -> (Vec3, Vec2) {
    let (w, h) = (r.size.x * fill, r.size.y * fill);
    let size = if w / h > aspect { Vec2::new(h * aspect, h) } else { Vec2::new(w, w / aspect) };
    (r.center, size)
}

/// A rows x cols grid of cells in a region, top-left first: (centre, cell size).
pub fn grid(r: &Region, rows: u32, cols: u32, gap: f32) -> Vec<(Vec3, Vec2)> {
    let (rows, cols) = (rows.max(1), cols.max(1));
    let cw = (r.size.x - gap * (cols - 1) as f32) / cols as f32;
    let ch = (r.size.y - gap * (rows - 1) as f32) / rows as f32;
    let mut out = Vec::new();
    for j in 0..rows {
        for i in 0..cols {
            let x = -r.size.x * 0.5 + cw * 0.5 + i as f32 * (cw + gap);
            let y = r.size.y * 0.5 - ch * 0.5 - j as f32 * (ch + gap);
            out.push((r.center + r.right * x + r.up * y, Vec2::new(cw, ch)));
        }
    }
    out
}

/// Snap a decal to the region it sits in: its centre, or the nearest edge
/// (keeping `margin` from it).
pub fn snap(d: &DecalObject, r: &Region, edge: bool, margin: f32) -> Vec3 {
    let c = Vec3::from(d.center);
    if !edge {
        return r.center;
    }
    let rel = c - r.center;
    let (x, y) = (rel.dot(r.right), rel.dot(r.up));
    let (hw, hh) = (r.size.x * 0.5 - d.size[0] * 0.5 - margin, r.size.y * 0.5 - d.size[1] * 0.5 - margin);
    // push to the closest of the four edges
    let dx = hw - x.abs();
    let dy = hh - y.abs();
    let (nx, ny) = if dx < dy { (x.signum() * hw, y.clamp(-hh, hh)) } else { (x.clamp(-hw, hw), y.signum() * hh) };
    r.center + r.right * nx + r.up * ny
}

/// The region containing a point (same plane, inside its rectangle), if any.
pub fn region_at(regions: &[Region], p: Vec3) -> Option<&Region> {
    regions.iter().find(|r| {
        let rel = p - r.center;
        rel.dot(r.normal).abs() < 0.05 && rel.dot(r.right).abs() <= r.size.x * 0.5 + 0.01 && rel.dot(r.up).abs() <= r.size.y * 0.5 + 0.01
    })
}

// ------------------------------------------------------------------ wrap

/// Conform projection: unfold the surface around the decal centre into the
/// decal plane, triangle by triangle across shared edges (each new vertex
/// keeps its distances to the shared edge's ends). Per mesh vertex: decal
/// plane coordinates (metres along right, up) and 1 where reached.
pub fn unfold(mesh: &Mesh, p: &Placement, reach: f32) -> Vec<[f32; 3]> {
    let nv = mesh.vertices.len();
    let mut out = vec![[0.0f32, 0.0, 0.0]; nv];
    // weld by position so UV seams don't stop the walk
    let key = |v: [f32; 3]| [(v[0] * 1e4).round() as i64, (v[1] * 1e4).round() as i64, (v[2] * 1e4).round() as i64];
    let mut weld: HashMap<[i64; 3], usize> = HashMap::new();
    let wid: Vec<usize> = mesh.vertices.iter().map(|v| { let n = weld.len(); *weld.entry(key(v.position)).or_insert(n) }).collect();
    let mut edge_tris: HashMap<(usize, usize), Vec<usize>> = HashMap::new();
    for t in 0..mesh.triangle_count() {
        for k in 0..3 {
            let (a, b) = (wid[mesh.indices[t * 3 + k] as usize], wid[mesh.indices[t * 3 + (k + 1) % 3] as usize]);
            edge_tris.entry((a.min(b), a.max(b))).or_default().push(t);
        }
    }
    let mut wpos = vec![Vec3::ZERO; weld.len()];
    for (i, v) in mesh.vertices.iter().enumerate() {
        wpos[wid[i]] = Vec3::from(v.position);
    }
    // start: the triangle under the centre
    let Some((t0, _)) = mesh.raycast(p.center + p.normal * p.depth.max(0.01), -p.normal) else { return out };
    let mut coord: Vec<Option<Vec2>> = vec![None; weld.len()];
    let tv = |t: usize| [0, 1, 2].map(|k| wid[mesh.indices[t * 3 + k] as usize]);
    for w in tv(t0) {
        let r = wpos[w] - p.center;
        coord[w] = Some(Vec2::new(r.dot(p.right), r.dot(p.up)));
    }
    let mut seen = vec![false; mesh.triangle_count()];
    seen[t0] = true;
    let mut queue = std::collections::VecDeque::from([t0]);
    while let Some(t) = queue.pop_front() {
        let v = tv(t);
        for k in 0..3 {
            let (a, b, c) = (v[k], v[(k + 1) % 3], v[(k + 2) % 3]);
            let (Some(ca), Some(cb)) = (coord[a], coord[b]) else { continue };
            // distance from the decal centre to the shared edge (long sliver
            // triangles, e.g. a pole, have every vertex far away)
            let e = cb - ca;
            let t = (-ca).dot(e) / e.length_squared().max(1e-12);
            if (ca + e * t.clamp(0.0, 1.0)).length() > reach {
                continue;
            }
            for &n in edge_tris.get(&(a.min(b), a.max(b))).into_iter().flatten() {
                if seen[n] {
                    continue;
                }
                seen[n] = true;
                let nv3 = tv(n);
                let Some(&d) = nv3.iter().find(|&&x| x != a && x != b) else { continue };
                if coord[d].is_none() {
                    // place d keeping its 3D distances to a and b, across the edge from c
                    let (pa, pb, pd) = (wpos[a], wpos[b], wpos[d]);
                    let l = (pb - pa).length().max(1e-9);
                    let (da, db) = ((pd - pa).length(), (pd - pb).length());
                    let x = (da * da - db * db + l * l) / (2.0 * l);
                    let h = (da * da - x * x).max(0.0).sqrt();
                    let e = (cb - ca).normalize_or_zero();
                    let side = coord[c].map(|cc| (cb - ca).perp_dot(cc - ca)).unwrap_or(1.0);
                    let perp = e.perp() * if side > 0.0 { -1.0 } else { 1.0 };
                    coord[d] = Some(ca + e * x + perp * h);
                }
                queue.push_back(n);
            }
        }
    }
    for (i, o) in out.iter_mut().enumerate() {
        if let Some(c) = coord[wid[i]] {
            *o = [c.x, c.y, 1.0];
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A wall 4 m x 3 m with a 1 x 1 m window hole, as a grid of quads.
    fn wall_with_window() -> Mesh {
        let mut m = Mesh { name: "wall".into(), has_uvs: true, ..Default::default() };
        let (nx, ny) = (16, 12);
        for j in 0..ny {
            for i in 0..nx {
                let (x0, y0) = (i as f32 * 0.25, j as f32 * 0.25);
                // the window: x 2.5..3.5, y 1..2
                if (2.5..3.5).contains(&(x0 + 0.1)) && (1.0..2.0).contains(&(y0 + 0.1)) {
                    continue;
                }
                let b = m.vertices.len() as u32;
                for (dx, dy) in [(0.0, 0.0), (0.25, 0.0), (0.25, 0.25), (0.0, 0.25)] {
                    m.vertices.push(crate::Vertex { position: [x0 + dx, y0 + dy, 0.0], normal: [0.0, 0.0, 1.0], uv: [(x0 + dx) / 4.0, 1.0 - (y0 + dy) / 3.0], tangent: [0.0; 4] });
                }
                m.indices.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
            }
        }
        m
    }

    #[test]
    fn the_largest_window_free_rectangle() {
        let m = wall_with_window();
        let r = find_regions(&m, &RegionQuery { margin: 0.0, ..Default::default() });
        let best = r[0];
        // the window splits the wall: the biggest free rectangle is 2.5 x 3 (left part)
        assert!((best.size.x - 2.5).abs() < 0.11 && (best.size.y - 3.0).abs() < 0.11, "{best:?}");
        assert!((best.center.x - 1.25).abs() < 0.1, "{best:?}");
        assert!(best.normal.z > 0.99);
        // with a height band (street level up to 1 m): the full 4 m strip below the window
        let low = find_regions(&m, &RegionQuery { margin: 0.0, height: Some((0.0, 1.0)), ..Default::default() });
        assert!((low[0].size.x - 4.0).abs() < 0.11 && low[0].size.y <= 1.0 + 1e-3, "{:?}", low[0]);
        // fit and grid
        let (_, s) = fit_in(&best, 2.0, 1.0);
        assert!((s.x / s.y - 2.0).abs() < 1e-4 && s.x <= best.size.x + 1e-4);
        let g = grid(&best, 2, 3, 0.1);
        assert_eq!(g.len(), 6);
        assert!(g[0].0.y > g[3].0.y, "top row first");
    }

    #[test]
    fn snapping_and_ids() {
        let m = wall_with_window();
        let r = find_regions(&m, &RegionQuery { margin: 0.0, ..Default::default() })[0];
        let mut set = DecalSet::default();
        let id = set.add(DecalObject {
            id: 0,
            name: String::new(),
            group: String::new(),
            image: "a.png".into(),
            center: [0.8, 1.4, 0.0],
            normal: [0.0, 0.0, 1.0],
            size: [0.5, 0.5],
            rotation: 0.0,
            depth: 0.05,
            projection: DecalProjection::Box,
            wear: Default::default(),
            values: white_decal(),
            channels: default_channels(),
            enabled: true,
        });
        assert_eq!(set.find(&id.to_string()), Some(0));
        assert_eq!(set.find("decal_0"), Some(0));
        let d = &set.objects[0];
        assert!((snap(d, &r, false, 0.0) - r.center).length() < 1e-5);
        let e = snap(d, &r, true, 0.0);
        // closest edge of the 2.5 x 3 region from x = 0.8 is the left one (x = 0.25 + 0)
        assert!((e.x - 0.25).abs() < 0.12, "{e:?}");
        assert!(region_at(&[r], Vec3::new(1.0, 1.0, 0.0)).is_some());
    }

    #[test]
    fn wrap_unfolds_round_a_cylinder() {
        // a capped-free cylinder, radius 0.1, 24 sides, 2 rings
        let (r, n) = (0.1f32, 24usize);
        let mut m = Mesh { name: "cyl".into(), has_uvs: true, ..Default::default() };
        for k in 0..=n {
            let a = k as f32 / n as f32 * std::f32::consts::TAU;
            for y in [0.0f32, 1.0] {
                let (s, c) = a.sin_cos();
                m.vertices.push(crate::Vertex { position: [r * s, y, r * c], normal: [s, 0.0, c], uv: [k as f32 / n as f32, 1.0 - y], tangent: [0.0; 4] });
            }
        }
        for k in 0..n as u32 {
            let b = k * 2;
            m.indices.extend_from_slice(&[b, b + 2, b + 3, b, b + 3, b + 1]);
        }
        let p = Placement::new(Vec3::new(0.0, 0.5, r), Vec3::Z, Vec2::new(0.3, 0.3), 0.0, 0.05);
        let uv = unfold(&m, &p, 1.0);
        // walking round the front, the unfolded x grows by the arc length
        for k in 0..=6usize {
            let i = k * 2;
            let arc = (k as f32 / n as f32) * std::f32::consts::TAU * r;
            assert_eq!(uv[i][2], 1.0, "vertex {k} reached");
            assert!((uv[i][0] - arc).abs() < 0.01, "vertex {k}: {:?} vs arc {arc}", uv[i]);
        }
    }

    #[test]
    fn wrap_unfolds_around_a_corner() {
        // an L: a wall in z = 0 (x 0..1) and a side wall in x = 1 (z 0..-1)
        let mut m = Mesh { name: "L".into(), has_uvs: true, ..Default::default() };
        let quad = |m: &mut Mesh, p: [[f32; 3]; 4], n: [f32; 3]| {
            let b = m.vertices.len() as u32;
            for q in p {
                m.vertices.push(crate::Vertex { position: q, normal: n, uv: [0.0, 0.0], tangent: [0.0; 4] });
            }
            m.indices.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
        };
        quad(&mut m, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]], [0.0, 0.0, 1.0]);
        quad(&mut m, [[1.0, 0.0, 0.0], [1.0, 0.0, -1.0], [1.0, 1.0, -1.0], [1.0, 1.0, 0.0]], [1.0, 0.0, 0.0]);
        let p = Placement::new(Vec3::new(0.8, 0.5, 0.0), Vec3::Z, Vec2::new(1.0, 1.0), 0.0, 0.05);
        let uv = unfold(&m, &p, 3.0);
        assert!(uv.iter().all(|c| c[2] == 1.0), "every vertex reached");
        // the far corner of the side wall (1, 0, -1) unfolds to 1.2 m right of the centre
        let i = m.vertices.iter().position(|v| v.position == [1.0, 0.0, -1.0]).unwrap();
        assert!((uv[i][0] - 1.2).abs() < 1e-4 && (uv[i][1] + 0.5).abs() < 1e-4, "{:?}", uv[i]);
    }
}
