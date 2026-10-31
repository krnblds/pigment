//! Orbit camera (Substance-style: rotate around a target, pan in the view plane,
//! dolly toward the target). Uses an infinite reverse-Z projection: depth 1 at the
//! near plane, 0 at infinity, which keeps depth precision on big scenes.

use glam::{Mat4, Vec2, Vec3};

#[derive(Clone, Debug, PartialEq)]
pub struct OrbitCamera {
    pub target: Vec3,
    /// Rotation around world +Y, radians.
    pub yaw: f32,
    /// Elevation, radians, clamped just short of the poles.
    pub pitch: f32,
    pub distance: f32,
    /// Vertical field of view, radians.
    pub fov_y: f32,
}

impl Default for OrbitCamera {
    fn default() -> Self {
        Self { target: Vec3::ZERO, yaw: 0.6, pitch: 0.35, distance: 3.0, fov_y: 40f32.to_radians() }
    }
}

const PITCH_LIMIT: f32 = 1.55;

impl OrbitCamera {
    pub fn eye(&self) -> Vec3 {
        let (sy, cy) = self.yaw.sin_cos();
        let (sp, cp) = self.pitch.sin_cos();
        self.target + Vec3::new(sy * cp, sp, cy * cp) * self.distance
    }

    pub fn forward(&self) -> Vec3 {
        (self.target - self.eye()).normalize()
    }

    /// Camera right and up vectors in world space.
    pub fn basis(&self) -> (Vec3, Vec3) {
        let f = self.forward();
        let right = f.cross(Vec3::Y).normalize();
        let up = right.cross(f);
        (right, up)
    }

    pub fn view(&self) -> Mat4 {
        glam::camera::rh::view::look_at_mat4(self.eye(), self.target, Vec3::Y)
    }

    pub fn near(&self) -> f32 {
        (self.distance * 0.001).max(1e-4)
    }

    pub fn proj(&self, aspect: f32) -> Mat4 {
        // wgpu clip space follows the D3D convention (y up, depth 0..1).
        glam::camera::rh::proj::directx::perspective_infinite_reverse(self.fov_y, aspect.max(1e-3), self.near())
    }

    pub fn view_proj(&self, aspect: f32) -> Mat4 {
        self.proj(aspect) * self.view()
    }

    /// Rotate by a mouse delta in pixels.
    pub fn orbit(&mut self, delta_px: Vec2) {
        const SPEED: f32 = 0.008;
        self.yaw -= delta_px.x * SPEED;
        self.pitch = (self.pitch + delta_px.y * SPEED).clamp(-PITCH_LIMIT, PITCH_LIMIT);
    }

    /// Pan so the point under the cursor follows the cursor.
    pub fn pan(&mut self, delta_px: Vec2, viewport_height_px: f32) {
        let world_per_px = 2.0 * self.distance * (self.fov_y * 0.5).tan() / viewport_height_px.max(1.0);
        let (right, up) = self.basis();
        self.target += (-right * delta_px.x + up * delta_px.y) * world_per_px;
    }

    /// Exponential dolly: positive `steps` moves closer.
    pub fn zoom(&mut self, steps: f32) {
        self.distance = (self.distance * 0.9f32.powf(steps)).clamp(1e-3, 1e6);
    }

    /// Fit a bounding sphere in view, keeping the current angles.
    pub fn frame(&mut self, center: Vec3, radius: f32) {
        self.target = center;
        let r = radius.max(1e-4);
        self.distance = r / (self.fov_y * 0.5).sin() * 1.1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eye_is_distance_from_target() {
        let c = OrbitCamera { target: Vec3::new(1.0, 2.0, 3.0), distance: 5.0, ..Default::default() };
        assert!(((c.eye() - c.target).length() - 5.0).abs() < 1e-5);
    }

    #[test]
    fn pitch_is_clamped() {
        let mut c = OrbitCamera::default();
        c.orbit(Vec2::new(0.0, 1e6));
        assert!(c.pitch <= PITCH_LIMIT);
        c.orbit(Vec2::new(0.0, -1e7));
        assert!(c.pitch >= -PITCH_LIMIT);
        // basis stays finite at the clamp
        let (r, u) = c.basis();
        assert!(r.is_finite() && u.is_finite());
    }

    #[test]
    fn zoom_in_reduces_distance_and_is_reversible() {
        let mut c = OrbitCamera::default();
        let d0 = c.distance;
        c.zoom(3.0);
        assert!(c.distance < d0);
        c.zoom(-3.0);
        assert!((c.distance - d0).abs() < 1e-4);
    }

    #[test]
    fn pan_keeps_view_direction() {
        let mut c = OrbitCamera::default();
        let f0 = c.forward();
        c.pan(Vec2::new(30.0, -10.0), 600.0);
        assert!((c.forward() - f0).length() < 1e-5);
        assert!(c.target.length() > 0.0);
    }

    #[test]
    fn framed_sphere_fits_in_view() {
        let mut c = OrbitCamera::default();
        c.frame(Vec3::new(10.0, 0.0, 0.0), 2.0);
        let vp = c.view_proj(1.0);
        // the sphere's top point in view space should land inside clip space
        let (_, up) = c.basis();
        let p = vp.project_point3(c.target + up * 2.0);
        assert!(p.y.abs() < 1.0, "projected y = {}", p.y);
        // reverse-Z: visible depth in (0, 1]
        assert!(p.z > 0.0 && p.z <= 1.0);
    }
}
