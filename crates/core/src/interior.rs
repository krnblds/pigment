//! Interior mapping ("parallax windows"): the data a runtime shader needs to
//! fake a 3D room behind every window pane.
//!
//! Two pieces, both GPU-free:
//!
//! * **Window maps** ([`pane_frames`], [`part_map`]): for a set of mesh parts
//!   (the glass panes), a texture in the mesh's UV space whose texels hold
//!   `pane index + 1` (0 = not a pane), plus one [`PaneFrame`] per pane: its
//!   centre, outward normal, right / up axes, size in metres and the UV of
//!   its centre. A shader looks the pane up from the fragment's UV, works out
//!   where on the pane it is in metres, and ray-casts into a room box behind
//!   it. Panes are seeded from their world position so neighbours differ.
//!
//! * **Interior atlases** ([`pack_atlas`]): rooms in the *pre-projected*
//!   format, stacked into one texture-array strip. A room is a box `W x H`
//!   (metres) at the window plane and `D` deep. Its image is what a pinhole
//!   camera sees from `E` metres in front of the window plane, on the room's
//!   axis, with the frustum through the edges of the front rectangle: a
//!   point `(x, y, z)` (x right, y up from the centre of the front
//!   rectangle, z <= 0 into the room) lands at
//!
//!   ```text
//!   s = E / (E - z)
//!   u = 0.5 + x * s / W,   v = 0.5 - y * s / H          (v down)
//!   ```
//!
//!   Alpha holds the depth of the surface seen, `-z / D` in 0..1, so the shader
//!   can ray-march furniture with parallax instead of only the box walls.
//!   Rooms come from rendered images (Cycles, with a depth pass) or from the
//!   classic five faces (back, left, right, floor, ceiling), which
//!   [`project_faces`] reprojects into the same format. Every room can be
//!   colour graded ([`Grade`]) and has a lit and an "off" layer.

use anyhow::{bail, Context, Result};
use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

use crate::mesh::{Mesh, Parts};

// ------------------------------------------------------------------ window maps

/// One window pane's frame, in the mesh's space (metres).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PaneFrame {
    /// Index in the map (texel value - 1).
    pub index: u32,
    /// Mesh part id.
    pub part: u32,
    pub center: [f32; 3],
    /// Outward normal (away from `outward_from`).
    pub normal: [f32; 3],
    /// Right and up as seen from outside, looking at the pane.
    pub right: [f32; 3],
    pub up: [f32; 3],
    /// Width (along `right`) and height (along `up`) in metres.
    pub size: [f32; 2],
    /// UV of the pane's centre (glTF convention: v down).
    pub uv_center: [f32; 2],
}

/// Frames of `ids` (part ids). Normals point away from `outward_from`; `up`
/// is the world up the pane's vertical axis follows (horizontal panes fall
/// back to -z).
pub fn pane_frames(mesh: &Mesh, parts: &Parts, ids: &[u32], outward_from: Vec3, up: Vec3) -> Result<Vec<PaneFrame>> {
    let mut tris: Vec<Vec<usize>> = vec![Vec::new(); parts.info.len()];
    for (t, &p) in parts.triangle_part.iter().enumerate() {
        tris[p as usize].push(t);
    }
    let mut out = Vec::with_capacity(ids.len());
    for (index, &id) in ids.iter().enumerate() {
        let Some(list) = tris.get(id as usize) else {
            bail!("part {id} does not exist (the mesh has {} parts)", parts.info.len());
        };
        let pos = |v: u32| Vec3::from(mesh.vertices[v as usize].position);
        let tri = |t: usize| [0, 1, 2].map(|k| mesh.indices[t * 3 + k]);
        // the biggest triangle's normal is the reference; every other normal is
        // folded onto its side, so a thin box's front and back agree
        let mut best = (0.0f32, Vec3::Z);
        for &t in list {
            let [a, b, c] = tri(t).map(pos);
            let n = (b - a).cross(c - a);
            if n.length() > best.0 {
                best = (n.length(), n.normalize());
            }
        }
        let mut n = Vec3::ZERO;
        for &t in list {
            let [a, b, c] = tri(t).map(pos);
            let m = (b - a).cross(c - a);
            n += if m.dot(best.1) >= 0.0 { m } else { -m };
        }
        let mut n = n.normalize_or(best.1);
        let info = &parts.info[id as usize];
        let mid = (Vec3::from(info.min) + Vec3::from(info.max)) * 0.5;
        // outward: away from the reference point, in the horizontal plane when possible
        let mut away = mid - outward_from;
        if n.y.abs() < 0.9 {
            away.y = 0.0;
        }
        if n.dot(away) < 0.0 {
            n = -n;
        }
        let mut u = up - n * up.dot(n);
        if u.length() < 1e-3 {
            u = Vec3::NEG_Z - n * Vec3::NEG_Z.dot(n);
        }
        let u = u.normalize();
        let r = u.cross(n).normalize();
        // extents in the pane's frame
        let (mut lo, mut hi) = (Vec3::splat(f32::MAX), Vec3::splat(f32::MIN));
        for &t in list {
            for v in tri(t) {
                let p = pos(v);
                let q = Vec3::new(p.dot(r), p.dot(u), p.dot(n));
                lo = lo.min(q);
                hi = hi.max(q);
            }
        }
        let c = (lo + hi) * 0.5;
        let center = r * c.x + u * c.y + n * c.z;
        // UV of the centre: least-squares affine fit uv = A (s, t) + b over the
        // front-facing triangles (the sides of a thin box have their own islands)
        let mut ata = [[0.0f64; 3]; 3];
        let mut atu = [[0.0f64; 2]; 3];
        for &t in list {
            let [a, b, cc] = tri(t).map(pos);
            let fn_ = (b - a).cross(cc - a);
            if fn_.length() < 1e-9 || fn_.normalize().dot(n).abs() < 0.9 {
                continue;
            }
            for v in tri(t) {
                let p = pos(v) - center;
                let row = [p.dot(r) as f64, p.dot(u) as f64, 1.0];
                let uv = mesh.vertices[v as usize].uv;
                for i in 0..3 {
                    for j in 0..3 {
                        ata[i][j] += row[i] * row[j];
                    }
                    atu[i][0] += row[i] * uv[0] as f64;
                    atu[i][1] += row[i] * uv[1] as f64;
                }
            }
        }
        let uv_center = match solve3(ata, atu) {
            Some(x) => [x[2][0] as f32, x[2][1] as f32],
            None => {
                // degenerate fit: the mean UV of the part
                let mut s = Vec2::ZERO;
                let mut k: f32 = 0.0;
                for &t in list {
                    for v in tri(t) {
                        s += Vec2::from(mesh.vertices[v as usize].uv);
                        k += 1.0;
                    }
                }
                (s / k.max(1.0)).into()
            }
        };
        out.push(PaneFrame {
            index: index as u32,
            part: id,
            center: center.into(),
            normal: n.into(),
            right: r.into(),
            up: u.into(),
            size: [hi.x - lo.x, hi.y - lo.y],
            uv_center,
        });
    }
    Ok(out)
}

/// Solve the 3x3 normal equations for two right-hand sides (Gauss-Jordan).
fn solve3(mut a: [[f64; 3]; 3], mut b: [[f64; 2]; 3]) -> Option<[[f64; 2]; 3]> {
    for col in 0..3 {
        let piv = (col..3).max_by(|&i, &j| a[i][col].abs().total_cmp(&a[j][col].abs()))?;
        if a[piv][col].abs() < 1e-12 {
            return None;
        }
        a.swap(col, piv);
        b.swap(col, piv);
        for row in 0..3 {
            if row != col {
                let f = a[row][col] / a[col][col];
                for k in 0..3 {
                    a[row][k] -= f * a[col][k];
                }
                for k in 0..2 {
                    b[row][k] -= f * b[col][k];
                }
            }
        }
    }
    for i in 0..3 {
        for k in 0..2 {
            b[i][k] /= a[i][i];
        }
    }
    Some(b)
}

/// The window map: `res x res` texels in UV space (row 0 = v 0), each holding
/// `index + 1` of the pane covering it, 0 elsewhere. Panes are dilated by
/// `pad` texels into the empty atlas gutter only, never over other parts, so
/// bilinear-free (nearest) lookups at pane edges still find their pane and a
/// frame next to a pane never turns into glass.
pub fn part_map(mesh: &Mesh, parts: &Parts, ids: &[u32], res: u32, pad: u32) -> Vec<u16> {
    let n = (res * res) as usize;
    let mut map = vec![0u16; n];
    let mut used = vec![false; n];
    let mut slot = vec![0u16; parts.info.len()];
    for (i, &id) in ids.iter().enumerate() {
        if let Some(s) = slot.get_mut(id as usize) {
            *s = (i + 1).min(u16::MAX as usize) as u16;
        }
    }
    for (t, tri) in mesh.indices.chunks_exact(3).enumerate() {
        let value = slot[parts.triangle_part[t] as usize];
        let uv = [0, 1, 2].map(|k| Vec2::from(mesh.vertices[tri[k] as usize].uv) * res as f32);
        raster(&uv, res, |i| {
            used[i] = true;
            if value != 0 {
                map[i] = value;
            }
        });
    }
    // grow panes into untouched texels, one ring per pass
    for _ in 0..pad {
        let prev = map.clone();
        for y in 0..res as i32 {
            for x in 0..res as i32 {
                let i = (y * res as i32 + x) as usize;
                if used[i] || prev[i] != 0 {
                    continue;
                }
                let mut v = 0;
                for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                    let (nx, ny) = (x + dx, y + dy);
                    if nx >= 0 && ny >= 0 && nx < res as i32 && ny < res as i32 {
                        let p = prev[(ny * res as i32 + nx) as usize];
                        if p != 0 {
                            v = p;
                            break;
                        }
                    }
                }
                map[i] = v;
            }
        }
    }
    map
}

/// Visit the texels whose centres lie inside a UV-space triangle (pixels),
/// plus the texels its edges cross (so thin slivers are not lost).
fn raster(p: &[Vec2; 3], res: u32, mut f: impl FnMut(usize)) {
    let lo = p[0].min(p[1]).min(p[2]);
    let hi = p[0].max(p[1]).max(p[2]);
    let x0 = (lo.x.floor() as i32).max(0);
    let y0 = (lo.y.floor() as i32).max(0);
    let x1 = (hi.x.ceil() as i32).min(res as i32 - 1);
    let y1 = (hi.y.ceil() as i32).min(res as i32 - 1);
    let area = (p[1] - p[0]).perp_dot(p[2] - p[0]);
    if area.abs() < 1e-12 {
        return;
    }
    for y in y0..=y1 {
        for x in x0..=x1 {
            let c = Vec2::new(x as f32 + 0.5, y as f32 + 0.5);
            let w0 = (p[1] - c).perp_dot(p[2] - c) / area;
            let w1 = (p[2] - c).perp_dot(p[0] - c) / area;
            let w2 = 1.0 - w0 - w1;
            // a texel centre within half a texel of an edge still counts (conservative)
            let inside = w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0;
            if inside || edge_dist(p, c) <= 0.5 {
                f((y as u32 * res + x as u32) as usize);
            }
        }
    }
}

fn edge_dist(p: &[Vec2; 3], c: Vec2) -> f32 {
    (0..3)
        .map(|k| {
            let (a, b) = (p[k], p[(k + 1) % 3]);
            let ab = b - a;
            let t = ((c - a).dot(ab) / ab.length_squared().max(1e-12)).clamp(0.0, 1.0);
            (a + ab * t - c).length()
        })
        .fold(f32::MAX, f32::min)
}

/// Write the map: 8-bit grey when it fits (<= 255 panes), else 16-bit.
pub fn write_part_map(path: &Path, map: &[u16], res: u32) -> Result<()> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    if map.iter().all(|&v| v <= 255) {
        let img = image::GrayImage::from_raw(res, res, map.iter().map(|&v| v as u8).collect()).context("map size")?;
        img.save(path)?;
    } else {
        let img = image::ImageBuffer::<image::Luma<u16>, Vec<u16>>::from_raw(res, res, map.to_vec()).context("map size")?;
        img.save(path)?;
    }
    Ok(())
}

// ------------------------------------------------------------------ interior atlases

/// Colour grade applied to a room (in linear light).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct Grade {
    /// Stops.
    pub exposure: f32,
    /// 1 = unchanged; around mid grey 0.18.
    pub contrast: f32,
    /// 1 = unchanged, 0 = grey.
    pub saturation: f32,
    /// Multiplier per channel.
    pub tint: [f32; 3],
    /// Added to the shadows (linear).
    pub lift: [f32; 3],
    /// Darken towards the corners, 0..1.
    pub vignette: f32,
}

impl Default for Grade {
    fn default() -> Self {
        Grade { exposure: 0.0, contrast: 1.0, saturation: 1.0, tint: [1.0; 3], lift: [0.0; 3], vignette: 0.0 }
    }
}

impl Grade {
    pub fn apply(&self, c: [f32; 3], u: f32, v: f32) -> [f32; 3] {
        let k = 2f32.powf(self.exposure);
        let mut c = [0, 1, 2].map(|i| c[i] * k * self.tint[i]);
        let l = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
        for x in c.iter_mut() {
            *x = l + (*x - l) * self.saturation;
        }
        for (i, x) in c.iter_mut().enumerate() {
            let y = x.max(0.0);
            // contrast in log space around mid grey keeps blacks black
            let y = if y > 0.0 { 0.18 * (y / 0.18).powf(self.contrast) } else { 0.0 };
            *x = y + self.lift[i] * (1.0 - y).max(0.0);
        }
        if self.vignette > 0.0 {
            let d = ((u - 0.5).powi(2) + (v - 0.5).powi(2)).sqrt() / 0.7071;
            let f = 1.0 - self.vignette * d.powf(2.2);
            for x in c.iter_mut() {
                *x *= f.max(0.0);
            }
        }
        c
    }
}

/// The classic five-face room: images of the back wall, side walls, floor
/// and ceiling, each looking at the face from inside the room with up = room
/// up (floor: top edge at the back wall; ceiling: top edge at the window).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Faces {
    pub back: PathBuf,
    pub left: PathBuf,
    pub right: PathBuf,
    pub floor: PathBuf,
    pub ceiling: PathBuf,
}

/// One room of an atlas.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RoomSpec {
    pub name: String,
    /// Front rectangle width / height and depth in metres.
    #[serde(default = "default_room")]
    pub size: [f32; 3],
    /// Camera distance in front of the window plane (metres) of the
    /// pre-projected image. Default: the depth.
    #[serde(default)]
    pub eye: Option<f32>,
    /// Pre-projected image, lights on.
    #[serde(default)]
    pub lit: Option<PathBuf>,
    /// Pre-projected image, lights off (screens / neon / spill only). Default:
    /// the lit image darkened to 3 %.
    #[serde(default)]
    pub off: Option<PathBuf>,
    /// Depth image (grey, 0 = window plane .. 1 = back wall).
    #[serde(default)]
    pub depth: Option<PathBuf>,
    /// Five faces instead of `lit` (reprojected; depth is analytic).
    #[serde(default)]
    pub faces: Option<Faces>,
    #[serde(default)]
    pub grade: Grade,
    /// Extra grade for the off layer (on top of `grade`).
    #[serde(default)]
    pub off_grade: Option<Grade>,
    /// Free-form tags (office, apartment, shop, ...) for the room picker.
    #[serde(default)]
    pub tags: Vec<String>,
}

fn default_room() -> [f32; 3] {
    [4.0, 3.0, 4.0]
}

/// What `pack_atlas` wrote.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct AtlasRoom {
    pub name: String,
    pub size: [f32; 3],
    pub eye: f32,
    /// Texture-array layers (cells of the vertical strip).
    pub lit_layer: u32,
    pub off_layer: u32,
    pub tags: Vec<String>,
    /// Mean linear colour of the lit layer (for far LODs).
    pub mean_lit: [f32; 3],
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Atlas {
    pub format: String,
    pub cell: u32,
    pub layers: u32,
    pub image: String,
    pub rooms: Vec<AtlasRoom>,
}

fn srgb_to_lin(x: f32) -> f32 {
    if x <= 0.04045 {
        x / 12.92
    } else {
        ((x + 0.055) / 1.055).powf(2.4)
    }
}
fn lin_to_srgb(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    if x <= 0.0031308 {
        x * 12.92
    } else {
        1.055 * x.powf(1.0 / 2.4) - 0.055
    }
}

fn load_rgb(path: &Path, cell: u32) -> Result<image::Rgb32FImage> {
    let img = image::open(path).with_context(|| format!("reading {}", path.display()))?;
    // to_rgb32f decodes sRGB bytes as-is (0..1); linearise ourselves
    let mut img = img.to_rgb32f();
    if img.width() != cell || img.height() != cell {
        img = image::imageops::resize(&img, cell, cell, image::imageops::FilterType::Lanczos3);
    }
    for p in img.pixels_mut() {
        for c in p.0.iter_mut() {
            *c = srgb_to_lin(*c);
        }
    }
    Ok(img)
}

fn load_grey(path: &Path, cell: u32) -> Result<Vec<f32>> {
    let img = image::open(path).with_context(|| format!("reading {}", path.display()))?.to_luma32f();
    let img = if img.width() != cell || img.height() != cell {
        image::imageops::resize(&img, cell, cell, image::imageops::FilterType::Triangle)
    } else {
        img
    };
    Ok(img.pixels().map(|p| p.0[0]).collect())
}

/// The room box seen through the canonical camera: for image texel (u, v)
/// the point hit on the empty box and its depth 0..1. Shared by the face
/// reprojection and by rooms without a depth image.
pub fn box_hit(size: [f32; 3], eye: f32, u: f32, v: f32) -> (Vec3, f32) {
    let [w, h, d] = size;
    let o = Vec3::new(0.0, 0.0, eye);
    // front-plane point under the texel
    let f = Vec3::new((u - 0.5) * w, (0.5 - v) * h, 0.0);
    let dir = (f - o).normalize();
    // exit of the box [-w/2, w/2] x [-h/2, h/2] x [-d, 0] from f
    let mut t = f32::MAX;
    for (k, half) in [(0usize, w * 0.5), (1, h * 0.5)] {
        let dk = dir[k];
        if dk.abs() > 1e-9 {
            let tk = ((half * dk.signum()) - f[k]) / dk;
            t = t.min(tk.max(0.0));
        }
    }
    if dir.z < -1e-9 {
        t = t.min((-d - f.z) / dir.z);
    }
    let p = f + dir * t;
    (p, (-p.z / d).clamp(0.0, 1.0))
}

/// Reproject five face images into the pre-projected format (linear RGB) plus
/// the analytic depth.
pub fn project_faces(faces: &Faces, size: [f32; 3], eye: f32, cell: u32) -> Result<(image::Rgb32FImage, Vec<f32>)> {
    let load = |p: &Path| -> Result<image::Rgb32FImage> {
        let img = image::open(p).with_context(|| format!("reading {}", p.display()))?.to_rgb32f();
        Ok(img)
    };
    let (back, left, right, floor, ceil) = (load(&faces.back)?, load(&faces.left)?, load(&faces.right)?, load(&faces.floor)?, load(&faces.ceiling)?);
    let sample = |img: &image::Rgb32FImage, s: f32, t: f32| -> [f32; 3] {
        // bilinear, s right, t down, both 0..1
        let (w, h) = (img.width() as f32, img.height() as f32);
        let x = (s.clamp(0.0, 1.0) * w - 0.5).clamp(0.0, w - 1.0);
        let y = (t.clamp(0.0, 1.0) * h - 0.5).clamp(0.0, h - 1.0);
        let (x0, y0) = (x.floor() as u32, y.floor() as u32);
        let (x1, y1) = ((x0 + 1).min(img.width() - 1), (y0 + 1).min(img.height() - 1));
        let (fx, fy) = (x - x0 as f32, y - y0 as f32);
        let g = |xx, yy| img.get_pixel(xx, yy).0.map(srgb_to_lin);
        let (a, b, c, d) = (g(x0, y0), g(x1, y0), g(x0, y1), g(x1, y1));
        [0, 1, 2].map(|k| (a[k] * (1.0 - fx) + b[k] * fx) * (1.0 - fy) + (c[k] * (1.0 - fx) + d[k] * fx) * fy)
    };
    let [w, h, d] = size;
    let mut out = image::Rgb32FImage::new(cell, cell);
    let mut depth = vec![0.0; (cell * cell) as usize];
    for y in 0..cell {
        for x in 0..cell {
            let (u, v) = ((x as f32 + 0.5) / cell as f32, (y as f32 + 0.5) / cell as f32);
            let (p, z) = box_hit(size, eye, u, v);
            // which face: the one the hit point lies on (largest normalised coordinate)
            let ex = (p.x.abs() / (w * 0.5), p.y.abs() / (h * 0.5), -p.z / d);
            let c = if ex.2 >= ex.0.max(ex.1) - 1e-4 {
                sample(&back, p.x / w + 0.5, 0.5 - p.y / h)
            } else if ex.0 >= ex.1 {
                if p.x < 0.0 {
                    // left wall seen from inside: its right edge is at the back
                    sample(&left, 1.0 - (-p.z / d), 0.5 - p.y / h)
                } else {
                    sample(&right, -p.z / d, 0.5 - p.y / h)
                }
            } else if p.y < 0.0 {
                // floor: top edge at the back wall
                sample(&floor, p.x / w + 0.5, 1.0 - (-p.z / d))
            } else {
                // ceiling: top edge at the window
                sample(&ceil, p.x / w + 0.5, -p.z / d)
            };
            out.put_pixel(x, y, image::Rgb(c));
            depth[(y * cell + x) as usize] = z;
        }
    }
    Ok((out, depth))
}

/// Pack rooms into one vertical strip of `cell x cell` RGBA8 layers (lit,
/// off per room; alpha = depth). Writes `<dir>/<name>_atlas.png` and
/// `<dir>/<name>.json` ([`Atlas`]).
pub fn pack_atlas(dir: &Path, name: &str, rooms: &[RoomSpec], cell: u32) -> Result<Atlas> {
    if rooms.is_empty() {
        bail!("no rooms to pack");
    }
    if !(16..=4096).contains(&cell) {
        bail!("cell must be 16..4096 pixels, got {cell}");
    }
    let mut seen = std::collections::HashSet::new();
    for r in rooms {
        if !seen.insert(r.name.as_str()) {
            bail!("room `{}` is listed twice", r.name);
        }
        if r.lit.is_some() == r.faces.is_some() {
            bail!("room `{}`: give exactly one of `lit` (pre-projected image) or `faces`", r.name);
        }
        if r.size.iter().any(|&x| x <= 0.0) {
            bail!("room `{}`: size must be positive [width, height, depth] in metres", r.name);
        }
    }
    let layers = rooms.len() as u32 * 2;
    let mut atlas = image::RgbaImage::new(cell, cell * layers);
    let mut out = Vec::new();
    for (i, r) in rooms.iter().enumerate() {
        let eye = r.eye.unwrap_or(r.size[2]);
        let (lit, depth) = match (&r.lit, &r.faces) {
            (Some(p), _) => {
                let img = load_rgb(p, cell)?;
                let depth = match &r.depth {
                    Some(dp) => load_grey(dp, cell)?,
                    None => (0..cell * cell).map(|k| box_hit(r.size, eye, ((k % cell) as f32 + 0.5) / cell as f32, ((k / cell) as f32 + 0.5) / cell as f32).1).collect(),
                };
                (img, depth)
            }
            (None, Some(f)) => project_faces(f, r.size, eye, cell)?,
            _ => unreachable!(),
        };
        let off = match &r.off {
            Some(p) => load_rgb(p, cell)?,
            None => {
                let mut o = lit.clone();
                for p in o.pixels_mut() {
                    for c in p.0.iter_mut() {
                        *c *= 0.03;
                    }
                }
                o
            }
        };
        let mut mean = [0.0f64; 3];
        for (layer, img, grades) in [(i as u32 * 2, &lit, vec![&r.grade]), (i as u32 * 2 + 1, &off, [Some(&r.grade), r.off_grade.as_ref()].into_iter().flatten().collect())] {
            for y in 0..cell {
                for x in 0..cell {
                    let (u, v) = ((x as f32 + 0.5) / cell as f32, (y as f32 + 0.5) / cell as f32);
                    let mut c = img.get_pixel(x, y).0;
                    for g in &grades {
                        c = g.apply(c, u, v);
                    }
                    if layer % 2 == 0 {
                        for k in 0..3 {
                            mean[k] += c[k].clamp(0.0, 1.0) as f64;
                        }
                    }
                    let a = depth[(y * cell + x) as usize].clamp(0.0, 1.0);
                    let px = [lin_to_srgb(c[0]), lin_to_srgb(c[1]), lin_to_srgb(c[2]), a].map(|x| (x * 255.0 + 0.5) as u8);
                    atlas.put_pixel(x, layer * cell + y, image::Rgba(px));
                }
            }
        }
        let n = (cell * cell) as f64;
        out.push(AtlasRoom {
            name: r.name.clone(),
            size: r.size,
            eye,
            lit_layer: i as u32 * 2,
            off_layer: i as u32 * 2 + 1,
            tags: r.tags.clone(),
            mean_lit: mean.map(|m| (m / n) as f32),
        });
    }
    std::fs::create_dir_all(dir)?;
    let image_name = format!("{name}_atlas.png");
    atlas.save(dir.join(&image_name)).with_context(|| format!("writing {}", dir.join(&image_name).display()))?;
    let a = Atlas { format: "pigment-interior-v1 (pre-projected, alpha = depth)".into(), cell, layers, image: image_name, rooms: out };
    std::fs::write(dir.join(format!("{name}.json")), serde_json::to_string_pretty(&a)?)?;
    Ok(a)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::Vertex;

    /// Two panes: a 2 x 1 m quad facing +z at z = 1 and a thin box facing -x
    /// at x = -1, plus a frame quad sharing the first pane's UV neighbourhood.
    fn panes() -> Mesh {
        let mut m = Mesh { name: "panes".into(), has_uvs: true, ..Default::default() };
        let mut quad = |ps: [[f32; 3]; 4], uvs: [[f32; 2]; 4]| {
            let b = m.vertices.len() as u32;
            for (p, uv) in ps.iter().zip(uvs) {
                m.vertices.push(Vertex { position: *p, uv, ..Default::default() });
            }
            m.indices.extend([b, b + 1, b + 2, b, b + 2, b + 3]);
        };
        // pane 0: x -1..1, y 0..1, z = 1, UV (0.1..0.5, 0.1..0.3), v down = y up
        quad([[-1.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [-1.0, 1.0, 1.0]], [[0.1, 0.3], [0.5, 0.3], [0.5, 0.1], [0.1, 0.1]]);
        // pane 1 (thin box front and back): x = -1, z -0.5..0.5, y 2..4
        quad([[-1.0, 2.0, 0.5], [-1.0, 2.0, -0.5], [-1.0, 4.0, -0.5], [-1.0, 4.0, 0.5]], [[0.6, 0.9], [0.8, 0.9], [0.8, 0.6], [0.6, 0.6]]);
        quad([[-1.01, 2.0, -0.5], [-1.01, 2.0, 0.5], [-1.01, 4.0, 0.5], [-1.01, 4.0, -0.5]], [[0.85, 0.9], [0.95, 0.9], [0.95, 0.6], [0.85, 0.6]]);
        // frame: right next to pane 0's island
        quad([[1.0, 0.0, 1.03], [1.2, 0.0, 1.03], [1.2, 1.0, 1.03], [1.0, 1.0, 1.03]], [[0.52, 0.3], [0.56, 0.3], [0.56, 0.1], [0.52, 0.1]]);
        m
    }

    #[test]
    fn pane_frames_are_outward_with_metre_sizes_and_centre_uvs() {
        let m = panes();
        let parts = m.parts();
        // pane 1's front and back are separate parts (no shared verts); take the front
        let ids = vec![parts.triangle_part[0], parts.triangle_part[2]];
        let f = pane_frames(&m, &parts, &ids, Vec3::ZERO, Vec3::Y).unwrap();
        assert_eq!(f.len(), 2);
        let a = &f[0];
        assert!((Vec3::from(a.normal) - Vec3::Z).length() < 1e-4, "{:?}", a.normal);
        assert!((Vec3::from(a.right) - Vec3::X).length() < 1e-4);
        assert!((a.size[0] - 2.0).abs() < 1e-4 && (a.size[1] - 1.0).abs() < 1e-4);
        assert!((Vec3::from(a.center) - Vec3::new(0.0, 0.5, 1.0)).length() < 1e-4);
        assert!((a.uv_center[0] - 0.3).abs() < 1e-4 && (a.uv_center[1] - 0.2).abs() < 1e-4, "{:?}", a.uv_center);
        let b = &f[1];
        assert!((Vec3::from(b.normal) - Vec3::NEG_X).length() < 1e-4, "{:?}", b.normal);
        // seen from outside (looking along +x), right is +z
        assert!((Vec3::from(b.right) - Vec3::Z).length() < 1e-4, "{:?}", b.right);
        assert!((b.size[0] - 1.0).abs() < 1e-4 && (b.size[1] - 2.0).abs() < 1e-4);
        assert!((b.uv_center[0] - 0.7).abs() < 1e-4 && (b.uv_center[1] - 0.75).abs() < 1e-4);
    }

    #[test]
    fn part_map_marks_panes_and_never_grows_over_other_parts() {
        let m = panes();
        let parts = m.parts();
        let pane0 = parts.triangle_part[0];
        let frame = parts.triangle_part[6];
        let map = part_map(&m, &parts, &[pane0], 100, 4);
        let at = |u: f32, v: f32| map[((v * 100.0) as usize) * 100 + (u * 100.0) as usize];
        assert_eq!(at(0.3, 0.2), 1);
        assert_eq!(at(0.11, 0.11), 1);
        // the frame island stays 0 even though it is within the pad
        assert_eq!(at(0.54, 0.2), 0);
        // the gutter left of the pane is dilated, far texels are not
        assert_eq!(at(0.08, 0.2), 1);
        assert_eq!(at(0.02, 0.2), 0);
        assert_eq!(at(0.7, 0.75), 0, "pane 1 was not listed");
        assert!(frame != pane0);
    }

    #[test]
    fn box_hit_follows_the_canonical_projection() {
        let size = [4.0, 3.0, 4.0];
        // the image centre sees the middle of the back wall
        let (p, z) = box_hit(size, 4.0, 0.5, 0.5);
        assert!((p - Vec3::new(0.0, 0.0, -4.0)).length() < 1e-4 && (z - 1.0).abs() < 1e-6);
        // the back wall spans E / (E + D) = half the image: u = 0.25 is its left edge
        let (p, z) = box_hit(size, 4.0, 0.25 + 1e-3, 0.5);
        assert!((p.z + 4.0).abs() < 0.05 && (z - 1.0).abs() < 0.02, "{p:?}");
        // the image edge sees the front corner of the side wall
        let (p, z) = box_hit(size, 4.0, 0.0005, 0.5);
        assert!(z < 0.01 && (p.x + 2.0).abs() < 0.01, "{p:?}");
        // forward projection of the hit lands back on the texel
        for &(u, v) in &[(0.1f32, 0.2f32), (0.7, 0.9), (0.45, 0.3)] {
            let (p, _) = box_hit(size, 4.0, u, v);
            let s = 4.0 / (4.0 - p.z);
            assert!((0.5 + p.x * s / 4.0 - u).abs() < 1e-4 && (0.5 - p.y * s / 3.0 - v).abs() < 1e-4);
        }
    }

    #[test]
    fn grade_is_identity_by_default_and_exposure_doubles() {
        let g = Grade::default();
        let c = g.apply([0.2, 0.4, 0.1], 0.3, 0.3);
        assert!(c.iter().zip([0.2, 0.4, 0.1]).all(|(a, b)| (a - b).abs() < 1e-5), "{c:?}");
        let g = Grade { exposure: 1.0, ..Default::default() };
        assert!((g.apply([0.1, 0.1, 0.1], 0.5, 0.5)[0] - 0.2).abs() < 1e-5);
        let g = Grade { saturation: 0.0, ..Default::default() };
        let c = g.apply([1.0, 0.0, 0.0], 0.5, 0.5);
        assert!((c[0] - c[1]).abs() < 1e-6);
    }

    fn solid(dir: &Path, name: &str, c: [u8; 3]) -> PathBuf {
        let p = dir.join(name);
        image::RgbImage::from_pixel(8, 8, image::Rgb(c)).save(&p).unwrap();
        p
    }

    #[test]
    fn faces_and_images_pack_into_a_strip_with_depth_in_alpha() {
        let dir = std::env::temp_dir().join(format!("pigment_interior_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let faces = Faces {
            back: solid(&dir, "b.png", [255, 0, 0]),
            left: solid(&dir, "l.png", [0, 255, 0]),
            right: solid(&dir, "r.png", [0, 0, 255]),
            floor: solid(&dir, "f.png", [255, 255, 0]),
            ceiling: solid(&dir, "c.png", [0, 255, 255]),
        };
        let rooms = vec![
            RoomSpec { name: "box".into(), size: [4.0, 3.0, 4.0], eye: None, lit: None, off: None, depth: None, faces: Some(faces), grade: Grade::default(), off_grade: None, tags: vec!["test".into()] },
            RoomSpec { name: "img".into(), size: [4.0, 3.0, 3.0], eye: Some(2.0), lit: Some(solid(&dir, "i.png", [128, 128, 128])), off: None, depth: None, faces: None, grade: Grade { exposure: 1.0, ..Default::default() }, off_grade: None, tags: vec![] },
        ];
        let a = pack_atlas(&dir, "t", &rooms, 32).unwrap();
        assert_eq!(a.layers, 4);
        assert_eq!((a.rooms[1].lit_layer, a.rooms[1].off_layer), (2, 3));
        let img = image::open(dir.join("t_atlas.png")).unwrap().to_rgba8();
        assert_eq!(img.dimensions(), (32, 128));
        // room 0: centre is back wall (red, depth 1), left edge middle is the left wall (green), bottom middle the floor
        let c = img.get_pixel(16, 16).0;
        assert!(c[0] > 250 && c[1] < 5 && c[3] == 255, "{c:?}");
        let l = img.get_pixel(1, 16).0;
        assert!(l[1] > 250 && l[0] < 5 && l[3] < 40, "{l:?}");
        let f = img.get_pixel(16, 30).0;
        assert!(f[0] > 250 && f[1] > 250 && f[2] < 5, "{f:?}");
        // off layer is the lit one at 3 %
        let o = img.get_pixel(16, 32 + 16).0;
        assert!(o[0] > 20 && o[0] < 70, "{o:?}");
        // room 1 is exposed by one stop: sRGB 128 (lin 0.216) -> lin 0.43 -> sRGB ~175
        let g = img.get_pixel(16, 64 + 16).0;
        assert!((g[0] as i32 - 175).abs() <= 2, "{g:?}");
        let json: Atlas = serde_json::from_str(&std::fs::read_to_string(dir.join("t.json")).unwrap()).unwrap();
        assert_eq!(json, a);
        // errors are explicit
        let bad = vec![RoomSpec { name: "x".into(), size: [4.0, 3.0, 4.0], eye: None, lit: None, off: None, depth: None, faces: None, grade: Grade::default(), off_grade: None, tags: vec![] }];
        assert!(pack_atlas(&dir, "t", &bad, 32).unwrap_err().to_string().contains("exactly one"));
        std::fs::remove_dir_all(&dir).ok();
    }
}
