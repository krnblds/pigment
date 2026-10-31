//! Dirty-tile tracking for strokes.
//!
//! The texture is split into a `GRID × GRID` grid of tiles. While a stroke is
//! painted we work out, on the CPU, which tiles each stamp can touch. Undo
//! then only snapshots those tiles, and the GPU only recomposites their
//! bounding rectangle.
//!
//! How: at stroke start the mesh's triangles are projected with the current
//! camera and binned into a coarse screen grid. A stamp looks up the bins
//! under its circle; every triangle there whose screen box overlaps the stamp
//! marks the tiles under its UV box. It is conservative (it may mark
//! occluded triangles too), which is fine: an extra tile costs a few KB.

use crate::mesh::Mesh;
use glam::{Mat4, Vec2, Vec4};

pub const GRID: u32 = 32;

#[derive(Clone, Debug, PartialEq)]
pub struct TileSet {
    bits: Vec<bool>,
}

impl Default for TileSet {
    fn default() -> Self {
        Self { bits: vec![false; (GRID * GRID) as usize] }
    }
}

impl TileSet {
    pub fn all() -> Self {
        Self { bits: vec![true; (GRID * GRID) as usize] }
    }
    pub fn mark(&mut self, x: u32, y: u32) {
        if x < GRID && y < GRID {
            self.bits[(y * GRID + x) as usize] = true;
        }
    }
    pub fn contains(&self, x: u32, y: u32) -> bool {
        self.bits[(y * GRID + x) as usize]
    }
    /// Mark every tile overlapping a UV rectangle (0..1 space).
    pub fn mark_uv_rect(&mut self, min: Vec2, max: Vec2) {
        let lo = (min.clamp(Vec2::ZERO, Vec2::ONE) * GRID as f32).floor();
        let hi = (max.clamp(Vec2::ZERO, Vec2::ONE) * GRID as f32).floor().min(Vec2::splat(GRID as f32 - 1.0));
        for y in lo.y as u32..=hi.y as u32 {
            for x in lo.x as u32..=hi.x as u32 {
                self.mark(x, y);
            }
        }
    }
    pub fn union(&mut self, other: &TileSet) {
        for (a, b) in self.bits.iter_mut().zip(&other.bits) {
            *a |= *b;
        }
    }
    pub fn count(&self) -> usize {
        self.bits.iter().filter(|b| **b).count()
    }
    pub fn is_empty(&self) -> bool {
        self.count() == 0
    }
    pub fn iter(&self) -> impl Iterator<Item = (u32, u32)> + '_ {
        (0..GRID * GRID).filter(|i| self.bits[*i as usize]).map(|i| (i % GRID, i / GRID))
    }
    /// Bounding rectangle in texels `[x, y, w, h]` for a texture of `res` pixels.
    pub fn texel_bounds(&self, res: u32) -> Option<[u32; 4]> {
        let ts = res / GRID;
        let (mut x0, mut y0, mut x1, mut y1) = (u32::MAX, u32::MAX, 0, 0);
        for (x, y) in self.iter() {
            x0 = x0.min(x);
            y0 = y0.min(y);
            x1 = x1.max(x);
            y1 = y1.max(y);
        }
        (x0 != u32::MAX).then(|| [x0 * ts, y0 * ts, (x1 - x0 + 1) * ts, (y1 - y0 + 1) * ts])
    }
}

/// Triangles binned by screen position, built once per stroke.
pub struct ScreenBins {
    cell: f32,
    cols: usize,
    rows: usize,
    bins: Vec<Vec<u32>>,
    /// Triangles crossing the camera plane: always candidates.
    always: Vec<u32>,
    screen_box: Vec<[f32; 4]>,
    uv_box: Vec<[f32; 4]>,
}

impl ScreenBins {
    pub fn build(mesh: &Mesh, view_proj: Mat4, viewport_px: Vec2) -> Self {
        const CELL: f32 = 48.0;
        let cols = ((viewport_px.x / CELL).ceil() as usize).max(1);
        let rows = ((viewport_px.y / CELL).ceil() as usize).max(1);
        let mut bins = vec![Vec::new(); cols * rows];
        let tri_count = mesh.indices.len() / 3;
        let mut screen_box = vec![[0.0; 4]; tri_count];
        let mut uv_box = vec![[0.0; 4]; tri_count];
        let mut always = Vec::new();

        let projected: Vec<Option<Vec2>> = mesh
            .vertices
            .iter()
            .map(|v| {
                let c = view_proj * Vec4::new(v.position[0], v.position[1], v.position[2], 1.0);
                (c.w > 1e-6).then(|| {
                    let ndc = c.truncate().truncate() / c.w;
                    Vec2::new((ndc.x * 0.5 + 0.5) * viewport_px.x, (0.5 - ndc.y * 0.5) * viewport_px.y)
                })
            })
            .collect();

        for (t, tri) in mesh.indices.chunks_exact(3).enumerate() {
            let uvs = [0, 1, 2].map(|k| Vec2::from(mesh.vertices[tri[k] as usize].uv));
            let ulo = uvs[0].min(uvs[1]).min(uvs[2]);
            let uhi = uvs[0].max(uvs[1]).max(uvs[2]);
            uv_box[t] = [ulo.x, ulo.y, uhi.x, uhi.y];
            let pts = [0, 1, 2].map(|k| projected[tri[k] as usize]);
            if pts.iter().any(|p| p.is_none()) {
                always.push(t as u32);
                continue;
            }
            let p = pts.map(|p| p.unwrap());
            let lo = p[0].min(p[1]).min(p[2]);
            let hi = p[0].max(p[1]).max(p[2]);
            screen_box[t] = [lo.x, lo.y, hi.x, hi.y];
            if hi.x < 0.0 || hi.y < 0.0 || lo.x > viewport_px.x || lo.y > viewport_px.y {
                continue;
            }
            let cx0 = (lo.x / CELL).floor().max(0.0) as usize;
            let cy0 = (lo.y / CELL).floor().max(0.0) as usize;
            let cx1 = ((hi.x / CELL).floor() as usize).min(cols - 1);
            let cy1 = ((hi.y / CELL).floor() as usize).min(rows - 1);
            for cy in cy0..=cy1 {
                for cx in cx0..=cx1 {
                    bins[cy * cols + cx].push(t as u32);
                }
            }
        }
        Self { cell: CELL, cols, rows, bins, always, screen_box, uv_box }
    }

    /// Mark the tiles a stamp of `radius` pixels at `center` may touch.
    pub fn mark_stamp(&self, center: Vec2, radius: f32, tiles: &mut TileSet) {
        let lo = center - Vec2::splat(radius);
        let hi = center + Vec2::splat(radius);
        let mark = |t: u32, tiles: &mut TileSet| {
            let b = self.uv_box[t as usize];
            tiles.mark_uv_rect(Vec2::new(b[0], b[1]), Vec2::new(b[2], b[3]));
        };
        for &t in &self.always {
            mark(t, tiles);
        }
        if hi.x < 0.0 || hi.y < 0.0 {
            return;
        }
        let cx0 = (lo.x / self.cell).floor().max(0.0) as usize;
        let cy0 = (lo.y / self.cell).floor().max(0.0) as usize;
        let cx1 = ((hi.x / self.cell).floor() as usize).min(self.cols - 1);
        let cy1 = ((hi.y / self.cell).floor() as usize).min(self.rows - 1);
        if cx0 >= self.cols || cy0 >= self.rows {
            return;
        }
        for cy in cy0..=cy1 {
            for cx in cx0..=cx1 {
                for &t in &self.bins[cy * self.cols + cx] {
                    let s = self.screen_box[t as usize];
                    if s[2] >= lo.x && s[0] <= hi.x && s[3] >= lo.y && s[1] <= hi.y {
                        mark(t, tiles);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::Vertex;

    /// A unit quad in the XY plane facing +Z with UVs covering 0..1.
    fn quad() -> Mesh {
        let v = |x: f32, y: f32| Vertex { position: [x, y, 0.0], normal: [0.0, 0.0, 1.0], uv: [x, 1.0 - y], tangent: [1.0, 0.0, 0.0, 1.0] };
        Mesh { name: "q".into(), vertices: vec![v(0.0, 0.0), v(1.0, 0.0), v(1.0, 1.0), v(0.0, 1.0)], indices: vec![0, 1, 2, 0, 2, 3], has_uvs: true }
    }

    #[test]
    fn uv_rect_marking_and_bounds() {
        let mut t = TileSet::default();
        t.mark_uv_rect(Vec2::new(0.0, 0.0), Vec2::new(0.1, 0.05));
        // 0.1 * 32 = 3.2 -> tiles 0..=3 in x; 0.05*32 = 1.6 -> 0..=1 in y
        assert_eq!(t.count(), 4 * 2);
        assert_eq!(t.texel_bounds(1024), Some([0, 0, 4 * 32, 2 * 32]));
        // full range clamps to the grid
        let mut all = TileSet::default();
        all.mark_uv_rect(Vec2::splat(-1.0), Vec2::splat(2.0));
        assert_eq!(all, TileSet::all());
        assert_eq!(TileSet::default().texel_bounds(1024), None);
    }

    #[test]
    fn stamp_on_quad_marks_tiles_and_miss_marks_none() {
        let m = quad();
        // orthographic-ish: map x,y in 0..1 to clip -1..1
        let vp = Mat4::from_translation(glam::Vec3::new(-1.0, -1.0, 0.0)) * Mat4::from_scale(glam::Vec3::new(2.0, 2.0, 1.0));
        let bins = ScreenBins::build(&m, vp, Vec2::new(512.0, 512.0));
        let mut hit = TileSet::default();
        bins.mark_stamp(Vec2::new(256.0, 256.0), 10.0, &mut hit);
        assert!(hit.count() > 0);
        let mut miss = TileSet::default();
        bins.mark_stamp(Vec2::new(2000.0, 2000.0), 10.0, &mut miss);
        assert!(miss.is_empty());
    }
}
