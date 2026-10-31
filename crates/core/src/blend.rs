//! CPU reference implementation of the per-channel blend modes.
//!
//! The GPU compositor (`composite.wgsl`) implements exactly these formulas;
//! keep the two in sync. Values are linear, 0..1 for scalar channels.
//!
//! A layer contributes `src` with alpha `a` (coverage × opacities × mask):
//! `out = lerp(dst, f(dst, src), a)`.

use crate::document::BlendMode;
use glam::{Vec2, Vec3};

pub fn blend_scalar(mode: BlendMode, dst: f32, src: f32, a: f32) -> f32 {
    let f = match mode {
        BlendMode::Normal | BlendMode::Replace | BlendMode::NormalCombine => src,
        BlendMode::Multiply => dst * src,
        BlendMode::Screen => 1.0 - (1.0 - dst) * (1.0 - src),
        BlendMode::Overlay => {
            if dst < 0.5 {
                2.0 * dst * src
            } else {
                1.0 - 2.0 * (1.0 - dst) * (1.0 - src)
            }
        }
        BlendMode::Add => dst + src,
        BlendMode::Subtract => dst - src,
        BlendMode::Darken => dst.min(src),
        BlendMode::Lighten => dst.max(src),
    };
    dst + (f - dst) * a.clamp(0.0, 1.0)
}

pub fn blend_rgb(mode: BlendMode, dst: Vec3, src: Vec3, a: f32) -> Vec3 {
    Vec3::new(
        blend_scalar(mode, dst.x, src.x, a),
        blend_scalar(mode, dst.y, src.y, a),
        blend_scalar(mode, dst.z, src.z, a),
    )
}

/// Reoriented Normal Mapping (Barré-Brisebois & Hill 2012): rotates the detail
/// normal `d` so that its "up" follows the base normal `b`. Unlike averaging or
/// UDN, detail keeps its full strength on tilted bases.
pub fn rnm(b: Vec3, d: Vec3) -> Vec3 {
    let t = b + Vec3::Z;
    let u = d * Vec3::new(-1.0, -1.0, 1.0);
    (t * t.dot(u) - u * t.z).normalize()
}

/// Tangent-space normal blend. Both inputs are unit vectors with z > 0.
pub fn blend_normal(mode: BlendMode, dst: Vec3, src: Vec3, a: f32) -> Vec3 {
    let target = match mode {
        BlendMode::NormalCombine => rnm(dst, src),
        _ => src,
    };
    dst.lerp(target, a.clamp(0.0, 1.0)).normalize()
}

/// Unit tangent-space normal from a stored (x, y) tilt.
pub fn normal_from_tilt(t: Vec2) -> Vec3 {
    let t = t.clamp_length_max(0.999);
    Vec3::new(t.x, t.y, (1.0 - t.length_squared()).sqrt())
}

pub fn srgb_to_linear(c: f32) -> f32 {
    if c <= 0.04045 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

pub fn linear_to_srgb(c: f32) -> f32 {
    if c <= 0.0031308 {
        c * 12.92
    } else {
        1.055 * c.powf(1.0 / 2.4) - 0.055
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use BlendMode::*;

    fn close(a: f32, b: f32) -> bool {
        (a - b).abs() < 1e-5
    }

    #[test]
    fn zero_alpha_is_identity_for_every_mode() {
        for m in [Normal, Multiply, Screen, Overlay, Add, Subtract, Darken, Lighten, Replace] {
            assert!(close(blend_scalar(m, 0.3, 0.9, 0.0), 0.3), "{m:?}");
        }
    }

    #[test]
    fn full_alpha_formulas() {
        assert!(close(blend_scalar(Normal, 0.3, 0.9, 1.0), 0.9));
        assert!(close(blend_scalar(Multiply, 0.5, 0.5, 1.0), 0.25));
        assert!(close(blend_scalar(Screen, 0.5, 0.5, 1.0), 0.75));
        assert!(close(blend_scalar(Add, 0.25, 0.5, 1.0), 0.75));
        assert!(close(blend_scalar(Subtract, 0.75, 0.5, 1.0), 0.25));
        assert!(close(blend_scalar(Darken, 0.2, 0.7, 1.0), 0.2));
        assert!(close(blend_scalar(Lighten, 0.2, 0.7, 1.0), 0.7));
        // overlay: dark base multiplies, light base screens
        assert!(close(blend_scalar(Overlay, 0.25, 0.5, 1.0), 0.25));
        assert!(close(blend_scalar(Overlay, 0.75, 0.5, 1.0), 0.75));
    }

    #[test]
    fn half_alpha_interpolates() {
        assert!(close(blend_scalar(Normal, 0.0, 1.0, 0.5), 0.5));
        assert!(close(blend_scalar(Multiply, 1.0, 0.0, 0.5), 0.5));
    }

    #[test]
    fn alpha_is_clamped() {
        assert!(close(blend_scalar(Normal, 0.0, 1.0, 3.0), 1.0));
        assert!(close(blend_scalar(Normal, 0.0, 1.0, -1.0), 0.0));
    }

    #[test]
    fn rnm_identities() {
        let flat = Vec3::Z;
        let d = normal_from_tilt(Vec2::new(0.3, -0.2));
        // detail on a flat base is unchanged; flat detail leaves the base unchanged
        assert!((rnm(flat, d) - d).length() < 1e-5);
        assert!((rnm(d, flat) - d).length() < 1e-5);
        let r = rnm(normal_from_tilt(Vec2::new(0.5, 0.1)), d);
        assert!((r.length() - 1.0).abs() < 1e-5);
    }

    #[test]
    fn normal_blend_stays_unit() {
        let a = normal_from_tilt(Vec2::new(0.6, 0.0));
        let b = normal_from_tilt(Vec2::new(-0.6, 0.0));
        let m = blend_normal(Normal, a, b, 0.5);
        assert!((m.length() - 1.0).abs() < 1e-5);
        assert!((m - Vec3::Z).length() < 1e-5);
    }

    #[test]
    fn srgb_round_trip() {
        for i in 0..=20 {
            let x = i as f32 / 20.0;
            assert!(close(linear_to_srgb(srgb_to_linear(x)), x));
        }
        assert!(close(srgb_to_linear(0.5), 0.21404114));
    }
}
