//! Triangle meshes with one UV set: import (OBJ, glTF/GLB), normal and tangent
//! generation, bounds, and a built-in test mesh.
//!
//! UV convention is glTF's: origin top-left, v pointing down, which matches
//! GPU texture addressing. OBJ UVs (origin bottom-left) are flipped on import.

use anyhow::{bail, Context, Result};
use glam::{Mat4, Vec2, Vec3, Vec4};
use std::path::Path;

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    /// xyz = tangent, w = bitangent sign.
    pub tangent: [f32; 4],
}

#[derive(Clone, Debug, Default)]
pub struct Mesh {
    pub name: String,
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    /// True if the source had texture coordinates (painting needs them).
    pub has_uvs: bool,
}

impl Mesh {
    pub fn triangle_count(&self) -> usize {
        self.indices.len() / 3
    }

    /// Load by file extension: `.obj`, `.gltf`, `.glb`.
    pub fn load(path: &Path) -> Result<Mesh> {
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase();
        let mut mesh = match ext.as_str() {
            "obj" => load_obj(path),
            "gltf" | "glb" => load_gltf(path),
            other => bail!("unsupported mesh format '.{other}' (use .obj, .gltf or .glb)"),
        }
        .with_context(|| format!("loading {}", path.display()))?;
        if mesh.indices.is_empty() {
            bail!("{} contains no triangles", path.display());
        }
        mesh.name = path.file_stem().and_then(|s| s.to_str()).unwrap_or("mesh").to_string();
        Ok(mesh)
    }

    /// Axis-aligned bounds (min, max). Zero box for an empty mesh.
    pub fn bounds(&self) -> (Vec3, Vec3) {
        if self.vertices.is_empty() {
            return (Vec3::ZERO, Vec3::ZERO);
        }
        self.vertices.iter().fold((Vec3::splat(f32::MAX), Vec3::splat(f32::MIN)), |(lo, hi), v| {
            let p = Vec3::from(v.position);
            (lo.min(p), hi.max(p))
        })
    }

    /// Bounding sphere (center of AABB, radius to farthest vertex).
    pub fn bounding_sphere(&self) -> (Vec3, f32) {
        let (lo, hi) = self.bounds();
        let c = (lo + hi) * 0.5;
        let r = self.vertices.iter().map(|v| (Vec3::from(v.position) - c).length()).fold(0.0, f32::max);
        (c, r)
    }

    /// Area-weighted smooth normals. Vertices split on UV seams stay split, so
    /// normals across a seam can differ slightly; real assets ship normals.
    pub fn compute_normals(&mut self) {
        let mut acc = vec![Vec3::ZERO; self.vertices.len()];
        for t in self.indices.chunks_exact(3) {
            let [a, b, c] = [t[0] as usize, t[1] as usize, t[2] as usize];
            let pa = Vec3::from(self.vertices[a].position);
            let n = (Vec3::from(self.vertices[b].position) - pa).cross(Vec3::from(self.vertices[c].position) - pa);
            for i in [a, b, c] {
                acc[i] += n; // unnormalised cross = area weighting
            }
        }
        for (v, n) in self.vertices.iter_mut().zip(acc) {
            v.normal = n.try_normalize().unwrap_or(Vec3::Y).into();
        }
    }

    /// Per-vertex tangents from UV derivatives (Lengyel's method), Gram-Schmidt
    /// orthogonalised against the normal. w stores handedness.
    pub fn compute_tangents(&mut self) {
        let n = self.vertices.len();
        let mut tan = vec![Vec3::ZERO; n];
        let mut bit = vec![Vec3::ZERO; n];
        for t in self.indices.chunks_exact(3) {
            let [a, b, c] = [t[0] as usize, t[1] as usize, t[2] as usize];
            let (va, vb, vc) = (self.vertices[a], self.vertices[b], self.vertices[c]);
            let e1 = Vec3::from(vb.position) - Vec3::from(va.position);
            let e2 = Vec3::from(vc.position) - Vec3::from(va.position);
            let d1 = Vec2::from(vb.uv) - Vec2::from(va.uv);
            let d2 = Vec2::from(vc.uv) - Vec2::from(va.uv);
            let det = d1.x * d2.y - d2.x * d1.y;
            if det.abs() < 1e-12 {
                continue;
            }
            let r = 1.0 / det;
            let sdir = (e1 * d2.y - e2 * d1.y) * r;
            let tdir = (e2 * d1.x - e1 * d2.x) * r;
            for i in [a, b, c] {
                tan[i] += sdir;
                bit[i] += tdir;
            }
        }
        // Vertices split only by a UV seam (same position and normal, same UV
        // handedness) must share one tangent frame, or normal-mapped shading
        // shows a line along the seam. Sum their accumulators.
        {
            let (_, r) = self.bounding_sphere();
            let q = 1e5 / r.max(1e-6);
            let mut groups: std::collections::HashMap<([i64; 3], [i32; 3], bool), Vec<usize>> = Default::default();
            for (i, v) in self.vertices.iter().enumerate() {
                let nrm = Vec3::from(v.normal);
                let right_handed = nrm.cross(tan[i]).dot(bit[i]) <= 0.0;
                let key = (v.position.map(|c| (c * q).round() as i64), v.normal.map(|c| (c * 1000.0).round() as i32), right_handed);
                groups.entry(key).or_default().push(i);
            }
            for members in groups.values().filter(|m| m.len() > 1) {
                let (t, b) = members.iter().fold((Vec3::ZERO, Vec3::ZERO), |(t, b), &i| (t + tan[i], b + bit[i]));
                for &i in members {
                    tan[i] = t;
                    bit[i] = b;
                }
            }
        }
        for i in 0..n {
            let nrm = Vec3::from(self.vertices[i].normal);
            let t = (tan[i] - nrm * nrm.dot(tan[i])).try_normalize().unwrap_or_else(|| nrm.any_orthonormal_vector());
            // Bitangent = cross(N, T) * w must point *up* the image (towards
            // decreasing v in our v-down UVs), matching OpenGL-style normal maps.
            let w = if nrm.cross(t).dot(bit[i]) > 0.0 { -1.0 } else { 1.0 };
            self.vertices[i].tangent = Vec4::from((t, w)).into();
        }
    }

    /// Smooth normals shared across split vertices (UV seams): area-weighted
    /// face normals summed per welded position.
    pub fn compute_normals_welded(&mut self) {
        let welded = crate::curvature::weld(self);
        let count = welded.iter().copied().max().map_or(0, |m| m as usize + 1);
        let mut acc = vec![Vec3::ZERO; count];
        for t in self.indices.chunks_exact(3) {
            let [a, b, c] = [t[0] as usize, t[1] as usize, t[2] as usize];
            let pa = Vec3::from(self.vertices[a].position);
            let n = (Vec3::from(self.vertices[b].position) - pa).cross(Vec3::from(self.vertices[c].position) - pa);
            for i in [a, b, c] {
                acc[welded[i] as usize] += n;
            }
        }
        for (v, w) in self.vertices.iter_mut().zip(&welded) {
            v.normal = acc[*w as usize].try_normalize().unwrap_or(Vec3::Y).into();
        }
    }

    /// Demo asset: a bevelled crate whose faces have a raised frame around a
    /// recessed panel. Convex bevels and frame rims give edge wear something to
    /// find; the creases at the bottom of each recess collect dirt. `n` = grid cells per face side.
    pub fn demo_crate(n: u32) -> Mesh {
        let ext = Vec3::new(1.0, 0.72, 0.82); // half extents
        let bevel = 0.09;
        let (margin, slope, depth) = (0.16, 0.035, 0.07);
        let inner_ext = ext - Vec3::splat(bevel);
        // (normal, u axis, v axis) with u x v = normal
        let faces = [
            (Vec3::X, -Vec3::Z, Vec3::Y),
            (-Vec3::X, Vec3::Z, Vec3::Y),
            (Vec3::Y, Vec3::X, -Vec3::Z),
            (-Vec3::Y, Vec3::X, Vec3::Z),
            (Vec3::Z, Vec3::X, Vec3::Y),
            (-Vec3::Z, -Vec3::X, Vec3::Y),
        ];
        let pad = 0.012;
        let (cw, ch) = (1.0 / 3.0, 0.5);
        let mut m = Mesh { name: "Demo crate".into(), has_uvs: true, ..Default::default() };
        for (f, (nrm, u, v)) in faces.iter().enumerate() {
            let (eu, ev) = (u.abs().dot(ext), v.abs().dot(ext));
            let en = nrm.abs().dot(ext);
            let (col, row) = ((f % 3) as f32, (f / 3) as f32);
            let base = m.vertices.len() as u32;
            for j in 0..=n {
                for i in 0..=n {
                    let a = i as f32 / n as f32 * 2.0 - 1.0;
                    let b = j as f32 / n as f32 * 2.0 - 1.0;
                    let p = *u * (a * eu) + *v * (b * ev) + *nrm * en;
                    // rounded box: clamp to the inner box, push out by the bevel radius
                    let inner = p.clamp(-inner_ext, inner_ext);
                    let dir = (p - inner).normalize_or(*nrm);
                    let mut pos = inner + dir * bevel;
                    // recessed panel inside a frame: distance to the face border, in world units
                    let d = ((1.0 - a.abs()) * eu).min((1.0 - b.abs()) * ev);
                    let t = ((d - margin) / slope).clamp(0.0, 1.0);
                    pos -= *nrm * depth * t * t * (3.0 - 2.0 * t);
                    let uv = [
                        (col + pad + (a * 0.5 + 0.5) * (1.0 - 2.0 * pad)) * cw,
                        (row + pad + (0.5 - b * 0.5) * (1.0 - 2.0 * pad)) * ch,
                    ];
                    m.vertices.push(Vertex { position: pos.into(), normal: dir.into(), uv, tangent: [0.0; 4] });
                }
            }
            let stride = n + 1;
            for j in 0..n {
                for i in 0..n {
                    let k = base + j * stride + i;
                    m.indices.extend_from_slice(&[k, k + 1, k + stride + 1, k, k + stride + 1, k + stride]);
                }
            }
        }
        m.compute_normals_welded();
        m.compute_tangents();
        m
    }

    /// A torus with a UV seam in both directions: a good default for testing
    /// seam handling. `segments` around the ring, `sides` around the tube.
    pub fn torus(major: f32, minor: f32, segments: u32, sides: u32) -> Mesh {
        let mut vertices = Vec::with_capacity(((segments + 1) * (sides + 1)) as usize);
        for i in 0..=segments {
            let u = i as f32 / segments as f32;
            let (su, cu) = (u * std::f32::consts::TAU).sin_cos();
            for j in 0..=sides {
                let v = j as f32 / sides as f32;
                let (sv, cv) = (v * std::f32::consts::TAU).sin_cos();
                let center = Vec3::new(cu * major, 0.0, su * major);
                let normal = Vec3::new(cu * cv, sv, su * cv);
                vertices.push(Vertex {
                    position: (center + normal * minor).into(),
                    normal: normal.into(),
                    uv: [u, v],
                    tangent: [0.0; 4],
                });
            }
        }
        let mut indices = Vec::with_capacity((segments * sides * 6) as usize);
        let stride = sides + 1;
        for i in 0..segments {
            for j in 0..sides {
                let a = i * stride + j;
                let b = (i + 1) * stride + j;
                indices.extend_from_slice(&[a, a + 1, b, b, a + 1, b + 1]);
            }
        }
        let mut m = Mesh { name: "Torus".into(), vertices, indices, has_uvs: true };
        m.compute_tangents();
        m
    }

    /// Write as Wavefront OBJ (positions, UVs flipped back to OBJ's bottom-left
    /// origin, normals). Used to store generated meshes in a project.
    pub fn write_obj(&self, path: &Path) -> Result<()> {
        use std::fmt::Write as _;
        let mut s = String::with_capacity(self.vertices.len() * 64);
        writeln!(s, "# written by Pigment
o {}", self.name)?;
        for v in &self.vertices {
            writeln!(s, "v {} {} {}", v.position[0], v.position[1], v.position[2])?;
        }
        for v in &self.vertices {
            writeln!(s, "vt {} {}", v.uv[0], 1.0 - v.uv[1])?;
        }
        for v in &self.vertices {
            writeln!(s, "vn {} {} {}", v.normal[0], v.normal[1], v.normal[2])?;
        }
        for t in self.indices.chunks_exact(3) {
            let [a, b, c] = [t[0] + 1, t[1] + 1, t[2] + 1];
            writeln!(s, "f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")?;
        }
        std::fs::write(path, s)?;
        Ok(())
    }

    fn finish(mut self, had_normals: bool) -> Mesh {
        if !had_normals {
            self.compute_normals();
        }
        self.compute_tangents();
        self
    }
}

fn load_obj(path: &Path) -> Result<Mesh> {
    let opts = tobj::LoadOptions { single_index: true, triangulate: true, ignore_points: true, ignore_lines: true };
    let (models, _materials) = tobj::load_obj(path, &opts)?;
    let mut mesh = Mesh { has_uvs: true, ..Default::default() };
    let mut had_normals = true;
    for m in &models {
        let src = &m.mesh;
        let base = mesh.vertices.len() as u32;
        let count = src.positions.len() / 3;
        let has_n = src.normals.len() == src.positions.len();
        let has_uv = src.texcoords.len() / 2 == count;
        had_normals &= has_n;
        mesh.has_uvs &= has_uv;
        for i in 0..count {
            let p = [src.positions[3 * i], src.positions[3 * i + 1], src.positions[3 * i + 2]];
            let n = if has_n { [src.normals[3 * i], src.normals[3 * i + 1], src.normals[3 * i + 2]] } else { [0.0; 3] };
            let uv = if has_uv { [src.texcoords[2 * i], 1.0 - src.texcoords[2 * i + 1]] } else { [0.0; 2] };
            mesh.vertices.push(Vertex { position: p, normal: n, uv, tangent: [0.0; 4] });
        }
        mesh.indices.extend(src.indices.iter().map(|i| i + base));
    }
    if mesh.vertices.is_empty() {
        mesh.has_uvs = false;
    }
    Ok(mesh.finish(had_normals))
}

fn load_gltf(path: &Path) -> Result<Mesh> {
    let (doc, buffers, _images) = gltf::import(path)?;
    let mut mesh = Mesh { has_uvs: true, ..Default::default() };
    let mut had_normals = true;
    let scene = doc.default_scene().or_else(|| doc.scenes().next());
    let mut stack: Vec<(gltf::Node, Mat4)> = match scene {
        Some(s) => s.nodes().map(|n| (n, Mat4::IDENTITY)).collect(),
        None => doc.nodes().map(|n| (n, Mat4::IDENTITY)).collect(),
    };
    while let Some((node, parent)) = stack.pop() {
        let world = parent * Mat4::from_cols_array_2d(&node.transform().matrix());
        let normal_mat = world.inverse().transpose();
        if let Some(gm) = node.mesh() {
            for prim in gm.primitives() {
                if prim.mode() != gltf::mesh::Mode::Triangles {
                    continue;
                }
                let reader = prim.reader(|b| Some(&buffers[b.index()]));
                let Some(positions) = reader.read_positions() else { continue };
                let positions: Vec<[f32; 3]> = positions.collect();
                let normals: Option<Vec<[f32; 3]>> = reader.read_normals().map(|n| n.collect());
                let uvs: Option<Vec<[f32; 2]>> = reader.read_tex_coords(0).map(|t| t.into_f32().collect());
                had_normals &= normals.is_some();
                mesh.has_uvs &= uvs.is_some();
                let base = mesh.vertices.len() as u32;
                let first_index = mesh.indices.len();
                for (i, p) in positions.iter().enumerate() {
                    let wp = world.transform_point3(Vec3::from(*p));
                    let n = normals
                        .as_ref()
                        .map(|n| normal_mat.transform_vector3(Vec3::from(n[i])).normalize_or_zero().into())
                        .unwrap_or([0.0; 3]);
                    let uv = uvs.as_ref().map(|u| u[i]).unwrap_or([0.0; 2]);
                    mesh.vertices.push(Vertex { position: wp.into(), normal: n, uv, tangent: [0.0; 4] });
                }
                match reader.read_indices() {
                    Some(idx) => mesh.indices.extend(idx.into_u32().map(|i| i + base)),
                    None => mesh.indices.extend(base..base + positions.len() as u32),
                }
                // A negative-determinant transform flips winding.
                if world.determinant() < 0.0 {
                    for tri in mesh.indices[first_index..].chunks_exact_mut(3) {
                        tri.swap(1, 2);
                    }
                }
            }
        }
        for child in node.children() {
            stack.push((child, world));
        }
    }
    if mesh.vertices.is_empty() {
        mesh.has_uvs = false;
    }
    Ok(mesh.finish(had_normals))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn temp_file(name: &str, contents: &[u8]) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("pigment-test-{}-{}", std::process::id(), name));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join(name);
        std::fs::File::create(&p).unwrap().write_all(contents).unwrap();
        p
    }

    const QUAD_OBJ: &str = "\
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
f 1/1 2/2 3/3 4/4
";

    #[test]
    fn obj_quad_is_triangulated_with_flipped_v_and_generated_normals() {
        let p = temp_file("quad.obj", QUAD_OBJ.as_bytes());
        let m = Mesh::load(&p).unwrap();
        assert_eq!(m.triangle_count(), 2);
        assert!(m.has_uvs);
        // OBJ v=0 (bottom) becomes v=1 in our top-left convention
        let v0 = m.vertices.iter().find(|v| v.position == [0.0, 0.0, 0.0]).unwrap();
        assert_eq!(v0.uv, [0.0, 1.0]);
        // CCW quad in XY plane faces +Z
        for v in &m.vertices {
            assert!((Vec3::from(v.normal) - Vec3::Z).length() < 1e-5);
        }
        // tangent follows +u (+X here); bitangent points up the image (+Y here)
        for v in &m.vertices {
            assert!((Vec3::from_slice(&v.tangent[..3]) - Vec3::X).length() < 1e-4, "{:?}", v.tangent);
            assert_eq!(v.tangent[3], 1.0);
        }
    }

    #[test]
    fn obj_without_uvs_is_flagged() {
        let p = temp_file("nouv.obj", b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
        let m = Mesh::load(&p).unwrap();
        assert!(!m.has_uvs);
    }

    #[test]
    fn unknown_extension_is_an_error() {
        let p = temp_file("x.fbx", b"");
        assert!(Mesh::load(&p).is_err());
    }

    #[test]
    fn gltf_embedded_triangle_with_node_transform() {
        // one triangle, positions + uvs in a base64 buffer, node translated +2 on X
        let pos: [f32; 9] = [0., 0., 0., 1., 0., 0., 0., 1., 0.];
        let uv: [f32; 6] = [0., 0., 1., 0., 0., 1.];
        let mut bytes: Vec<u8> = bytemuck::cast_slice(&pos).to_vec();
        bytes.extend_from_slice(bytemuck::cast_slice(&uv));
        let b64 = base64_encode(&bytes);
        let json = format!(
            r#"{{"asset":{{"version":"2.0"}},"scene":0,"scenes":[{{"nodes":[0]}}],
            "nodes":[{{"mesh":0,"translation":[2,0,0]}}],
            "meshes":[{{"primitives":[{{"attributes":{{"POSITION":0,"TEXCOORD_0":1}}}}]}}],
            "buffers":[{{"byteLength":{len},"uri":"data:application/octet-stream;base64,{b64}"}}],
            "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":36}},{{"buffer":0,"byteOffset":36,"byteLength":24}}],
            "accessors":[
              {{"bufferView":0,"componentType":5126,"count":3,"type":"VEC3","min":[0,0,0],"max":[1,1,0]}},
              {{"bufferView":1,"componentType":5126,"count":3,"type":"VEC2"}}]}}"#,
            len = bytes.len()
        );
        let p = temp_file("tri.gltf", json.as_bytes());
        let m = Mesh::load(&p).unwrap();
        assert_eq!(m.triangle_count(), 1);
        assert!(m.has_uvs);
        let (lo, hi) = m.bounds();
        assert_eq!(lo, Vec3::new(2.0, 0.0, 0.0));
        assert_eq!(hi, Vec3::new(3.0, 1.0, 0.0));
        assert!((Vec3::from(m.vertices[0].normal) - Vec3::Z).length() < 1e-5);
    }

    #[test]
    fn tangents_match_across_uv_seams() {
        let m = Mesh::torus(1.0, 0.25, 24, 12);
        // vertex (i = 0, j) and (i = segments, j) are the same point on both sides of the u seam
        for j in 0..=12usize {
            let a = m.vertices[j];
            let b = m.vertices[24 * 13 + j];
            assert!((Vec3::from(a.position) - Vec3::from(b.position)).length() < 1e-5);
            assert!((Vec4::from(a.tangent) - Vec4::from(b.tangent)).length() < 1e-5, "{:?} vs {:?}", a.tangent, b.tangent);
        }
    }

    #[test]
    fn demo_crate_is_well_formed() {
        let m = Mesh::demo_crate(24);
        assert_eq!(m.triangle_count(), 6 * 24 * 24 * 2);
        assert!(m.vertices.iter().all(|v| v.uv[0] > 0.0 && v.uv[0] < 1.0 && v.uv[1] > 0.0 && v.uv[1] < 1.0));
        // normals point outward everywhere (the shape is star-shaped around the origin)
        assert!(m.vertices.iter().all(|v| Vec3::from(v.normal).dot(Vec3::from(v.position)) > 0.0));
        // faces wind outward: area-weighted normals agree with vertex normals
        for t in m.indices.chunks_exact(3).step_by(97) {
            let p = [0, 1, 2].map(|k| Vec3::from(m.vertices[t[k] as usize].position));
            let fnrm = (p[1] - p[0]).cross(p[2] - p[0]);
            assert!(fnrm.dot(Vec3::from(m.vertices[t[0] as usize].normal)) > 0.0);
        }
        // the bevel edges are convex: curvature sees them
        let c = crate::curvature::compute(&m);
        let convex = c.vertex.iter().filter(|&&k| k > 3.0).count();
        assert!(convex > m.vertices.len() / 20, "{convex} strongly convex vertices");
    }

    #[test]
    fn torus_is_closed_and_bounded() {
        let m = Mesh::torus(1.0, 0.25, 32, 16);
        assert_eq!(m.triangle_count(), 32 * 16 * 2);
        let (c, r) = m.bounding_sphere();
        assert!(c.length() < 1e-4);
        assert!((r - 1.25).abs() < 1e-3);
        assert!(m.indices.iter().all(|&i| (i as usize) < m.vertices.len()));
    }

    #[test]
    fn obj_write_round_trip() {
        let m = Mesh::torus(1.0, 0.3, 8, 6);
        let dir = std::env::temp_dir().join(format!("pigment-objrt-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("t.obj");
        m.write_obj(&p).unwrap();
        let back = Mesh::load(&p).unwrap();
        assert_eq!(back.triangle_count(), m.triangle_count());
        // the loader may reorder vertices, so compare triangle corners
        for (ia, ib) in back.indices.iter().zip(&m.indices) {
            let (a, b) = (back.vertices[*ia as usize], m.vertices[*ib as usize]);
            assert!((Vec2::from(a.uv) - Vec2::from(b.uv)).length() < 1e-5);
            assert!((Vec3::from(a.position) - Vec3::from(b.position)).length() < 1e-5);
        }
        std::fs::remove_dir_all(dir).ok();
    }

    fn base64_encode(data: &[u8]) -> String {
        const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut s = String::new();
        for c in data.chunks(3) {
            let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
            for k in 0..4 {
                if k <= c.len() {
                    s.push(T[(n >> (18 - 6 * k) & 63) as usize] as char);
                } else {
                    s.push('=');
                }
            }
        }
        s
    }
}
