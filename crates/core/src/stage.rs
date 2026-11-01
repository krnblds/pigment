//! Lightbox stage: a seamless photo-studio "infinity cove" under the model.
//!
//! The stage is a revolved sweep: a flat round floor that curves up (a
//! quarter-circle fillet) into a tall round wall, so there is no horizon line
//! from any orbit angle. It is built once in unit space (the model's
//! horizontal radius = 1) and placed/scaled on the GPU from the model bounds
//! ([`StageLayout`]). The look (sweep colour, gloss, reflection, contact
//! shadow) comes from the lighting preset ([`StageLook`]): `lightbox` is a
//! bright white cove, `lightbox_dark` a black glossy one lit by strip lights.

use crate::mesh::Vertex;
use glam::{Vec2, Vec3};

/// How a lighting preset dresses the stage.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StageLook {
    /// Linear albedo of the sweep.
    pub albedo: Vec3,
    /// GGX roughness of the sweep (gloss of the soft reflections).
    pub roughness: f32,
    /// Fresnel reflectance at normal incidence (0.04 = plain dielectric).
    pub f0: f32,
    /// Strength of the model's planar reflection in the floor (0..1).
    pub reflection: f32,
    /// How fast the reflection fades with distance below the floor, in model
    /// heights (larger = longer mirror image).
    pub reflection_fade: f32,
    /// 0..1: how dark the contact shadow can get.
    pub shadow: f32,
}

/// The stage look for a lighting id (`lightbox`, `lightbox_dark`), or None
/// for lighting without a stage.
pub fn look(lighting_id: &str) -> Option<StageLook> {
    match lighting_id {
        "lightbox" => Some(StageLook { albedo: Vec3::splat(0.78), roughness: 0.32, f0: 0.04, reflection: 0.55, reflection_fade: 0.35, shadow: 0.92 }),
        "lightbox_dark" => Some(StageLook { albedo: Vec3::new(0.011, 0.011, 0.013), roughness: 0.1, f0: 0.05, reflection: 1.0, reflection_fade: 0.7, shadow: 0.85 }),
        _ => None,
    }
}

/// Unit-space sweep profile (model horizontal radius = 1).
pub const FLOOR_RADIUS: f32 = 3.0;
pub const FILLET_RADIUS: f32 = 2.0;
pub const WALL_TOP: f32 = 7.0;

/// Where the stage sits for a model with these bounds.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StageLayout {
    /// Floor centre (x, z) under the model.
    pub center: Vec2,
    /// Floor height: the bottom of the model.
    pub floor_y: f32,
    /// Unit-space -> world scale (>= the model's horizontal radius).
    pub scale: f32,
    /// Half-size of the square contact-shadow map around `center`.
    pub shadow_half: f32,
    /// Height range covered by the occluder maps (model height + margin).
    pub height: f32,
}

impl StageLayout {
    pub fn from_bounds(min: Vec3, max: Vec3) -> StageLayout {
        let size = (max - min).max(Vec3::splat(1e-4));
        let radius = 0.5 * Vec2::new(size.x, size.z).length();
        // tall, thin models (lamp posts) still get a roomy cove
        let scale = radius.max(size.y * 0.5).max(1e-3);
        let height = size.y * 1.02 + 1e-3;
        StageLayout {
            center: Vec2::new(0.5 * (min.x + max.x), 0.5 * (min.z + max.z)),
            floor_y: min.y,
            scale,
            // soft shadows reach out about one model height past the footprint
            shadow_half: 0.5 * size.x.max(size.z) + size.y.max(radius * 0.5) * 1.1,
            height,
        }
    }

    /// Map a world (x, z) to shadow-map uv (0..1; u along +x, v along +z).
    pub fn shadow_uv(&self, xz: Vec2) -> Vec2 {
        (xz - self.center) / (2.0 * self.shadow_half) + Vec2::splat(0.5)
    }
}

/// One point of the sweep profile: radius from the axis, height, inward normal.
fn profile(rings_floor: u32, rings_fillet: u32, rings_wall: u32) -> Vec<(f32, f32, Vec2)> {
    let mut p = Vec::new();
    for i in 0..=rings_floor {
        // denser near the model, where the shadow detail is
        let t = i as f32 / rings_floor as f32;
        p.push((FLOOR_RADIUS * t.powf(1.4), 0.0, Vec2::new(0.0, 1.0)));
    }
    for i in 1..=rings_fillet {
        let a = (i as f32 / rings_fillet as f32) * std::f32::consts::FRAC_PI_2;
        // centre of the fillet at (FLOOR_RADIUS, FILLET_RADIUS)
        let (s, c) = a.sin_cos();
        p.push((FLOOR_RADIUS + FILLET_RADIUS * s, FILLET_RADIUS * (1.0 - c), Vec2::new(-s, c)));
    }
    for i in 1..=rings_wall {
        let t = i as f32 / rings_wall as f32;
        p.push((FLOOR_RADIUS + FILLET_RADIUS, FILLET_RADIUS + (WALL_TOP - FILLET_RADIUS) * t, Vec2::new(-1.0, 0.0)));
    }
    p
}

/// The revolved sweep in unit space, triangles facing inwards (front faces
/// are counter-clockwise seen from inside the cove). uv = (angle / 2pi,
/// profile distance) for anyone who wants to texture it.
pub fn sweep_mesh(segments: u32) -> (Vec<Vertex>, Vec<u32>) {
    let prof = profile(28, 24, 10);
    let segments = segments.max(8);
    let mut verts = Vec::with_capacity(prof.len() * (segments as usize + 1));
    let mut along = 0.0;
    let mut prev = (0.0f32, 0.0f32);
    for (k, &(r, y, n)) in prof.iter().enumerate() {
        if k > 0 {
            along += Vec2::new(r - prev.0, y - prev.1).length();
        }
        prev = (r, y);
        for s in 0..=segments {
            let a = s as f32 / segments as f32 * std::f32::consts::TAU;
            let (sa, ca) = a.sin_cos();
            let radial = Vec3::new(sa, 0.0, ca);
            let normal = (radial * n.x + Vec3::Y * n.y).normalize();
            let tangent = Vec3::new(ca, 0.0, -sa);
            verts.push(Vertex { position: (radial * r + Vec3::Y * y).into(), normal: normal.into(), uv: [s as f32 / segments as f32, along], tangent: [tangent.x, tangent.y, tangent.z, 1.0] });
        }
    }
    let row = segments + 1;
    let mut idx = Vec::with_capacity(prof.len() * segments as usize * 6);
    for k in 0..prof.len() as u32 - 1 {
        for s in 0..segments {
            let a = k * row + s;
            let b = a + 1;
            let c = a + row;
            let d = c + 1;
            idx.extend_from_slice(&[a, b, c, b, d, c]);
        }
    }
    // the winding must face the inward normal
    let tri_n = |i: usize| {
        let p = |j: u32| Vec3::from(verts[j as usize].position);
        let (a, b, c) = (p(idx[i]), p(idx[i + 1]), p(idx[i + 2]));
        (b - a).cross(c - a)
    };
    let probe = (row as usize) * 6 * 4; // a floor quad away from the degenerate centre
    if tri_n(probe).dot(Vec3::from(verts[idx[probe] as usize].normal)) < 0.0 {
        for t in idx.chunks_exact_mut(3) {
            t.swap(1, 2);
        }
    }
    (verts, idx)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn looks_exist_only_for_lightbox_presets() {
        let light = look("lightbox").unwrap();
        let dark = look("lightbox_dark").unwrap();
        assert!(light.albedo.x > 0.5 && dark.albedo.x < 0.05);
        assert!(dark.roughness < light.roughness, "the dark floor is the glossier one");
        assert!(look("studio").is_none() && look("night").is_none());
    }

    #[test]
    fn layout_puts_the_floor_under_the_model() {
        let l = StageLayout::from_bounds(Vec3::new(-1.0, 0.2, -2.2), Vec3::new(1.0, 1.6, 2.2));
        assert_eq!(l.floor_y, 0.2);
        assert_eq!(l.center, Vec2::ZERO);
        assert!(l.scale >= 2.2, "covers the footprint: {}", l.scale);
        assert!(l.shadow_half > 2.2);
        assert!((l.shadow_uv(Vec2::ZERO) - Vec2::splat(0.5)).length() < 1e-6);
        let edge = l.shadow_uv(Vec2::new(l.shadow_half, -l.shadow_half));
        assert!((edge - Vec2::new(1.0, 0.0)).length() < 1e-5);
    }

    #[test]
    fn sweep_is_a_closed_inward_cove() {
        let (v, idx) = sweep_mesh(64);
        assert_eq!(idx.len() % 3, 0);
        assert!(idx.iter().all(|&i| (i as usize) < v.len()));
        let top = v.iter().map(|x| x.position[1]).fold(0.0f32, f32::max);
        assert!((top - WALL_TOP).abs() < 1e-4);
        // every non-degenerate triangle faces the same way as its normals (inwards)
        let mut agree = 0;
        let mut total = 0;
        for t in idx.chunks_exact(3) {
            let p = |i: u32| Vec3::from(v[i as usize].position);
            let n = (p(t[1]) - p(t[0])).cross(p(t[2]) - p(t[0]));
            if n.length() < 1e-9 {
                continue;
            }
            total += 1;
            if n.dot(Vec3::from(v[t[0] as usize].normal)) > 0.0 {
                agree += 1;
            }
        }
        assert_eq!(agree, total);
        // floor normals point up, wall normals point at the axis
        let wall = v.iter().find(|x| x.position[1] > WALL_TOP - 0.01).unwrap();
        let n = Vec3::from(wall.normal);
        let p = Vec3::from(wall.position);
        assert!(n.dot(-Vec3::new(p.x, 0.0, p.z).normalize()) > 0.99);
    }
}
