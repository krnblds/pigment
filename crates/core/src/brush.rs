//! Brush engine dynamics (GPU-free): turns pointer input (position, pen
//! pressure, tilt) into dabs with size, angle, opacity and flow, with
//! spacing, jitter, pressure curves, angle-follows-stroke and lazy mouse.
//! Also: symmetry transforms (mirror X/Y/Z planes and radial copies in object
//! space), UV lookup under a ray (clone / smudge), and polyline resampling.
//!
//! The renderer stamps each dab (see `stamp.wgsl`): a round falloff or a
//! grayscale tip image, rotated by the dab's angle, optionally through a
//! screen-space stencil.

use glam::{Mat4, Vec2, Vec3};
use serde::{Deserialize, Serialize};

/// A pressure response: value = min + (1 - min) * pressure^gamma.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct PressureCurve {
    pub enabled: bool,
    /// Value at zero pressure (0..1).
    pub min: f32,
    /// > 1: needs more pressure; < 1: responds early.
    pub gamma: f32,
}

impl PressureCurve {
    pub const fn on() -> Self {
        PressureCurve { enabled: true, min: 0.1, gamma: 1.0 }
    }
    pub const fn off() -> Self {
        PressureCurve { enabled: false, min: 0.1, gamma: 1.0 }
    }
    pub fn eval(&self, pressure: f32) -> f32 {
        if !self.enabled {
            return 1.0;
        }
        let p = pressure.clamp(0.0, 1.0).powf(self.gamma.max(0.05));
        self.min.clamp(0.0, 1.0) + (1.0 - self.min.clamp(0.0, 1.0)) * p
    }
}

/// Random variation per dab (0 = none).
#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Jitter {
    /// Size: dab diameter varies by up to this fraction (0..1).
    pub size: f32,
    /// Angle: up to this many degrees either way.
    pub angle: f32,
    /// Position: scattered up to this fraction of the diameter.
    pub position: f32,
    /// Flow: dab strength varies by up to this fraction.
    pub flow: f32,
}

impl Jitter {
    pub fn is_zero(&self) -> bool {
        *self == Jitter::default()
    }
}

/// Stroke behaviour of a brush.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct BrushDynamics {
    /// Distance between dabs as a fraction of the diameter.
    pub spacing: f32,
    /// Per-dab strength. 1 = classic (a stroke never exceeds its opacity,
    /// overlapping dabs don't build up); < 1 = dabs build up towards the
    /// stroke opacity.
    pub flow: f32,
    /// Dab angle in degrees (tips; also the stencil-free round brush ignores it).
    pub angle: f32,
    /// The dab angle follows the stroke direction (plus `angle`).
    pub follow_angle: bool,
    pub jitter: Jitter,
    /// Pen pressure -> size, flow, opacity.
    pub pressure_size: PressureCurve,
    pub pressure_flow: PressureCurve,
    pub pressure_opacity: PressureCurve,
    /// Lazy mouse: the brush trails the pointer by this many pixels (smooth lines).
    pub lazy: f32,
    pub seed: u32,
}

impl Default for BrushDynamics {
    fn default() -> Self {
        BrushDynamics {
            spacing: 0.1,
            flow: 1.0,
            angle: 0.0,
            follow_angle: false,
            jitter: Jitter::default(),
            pressure_size: PressureCurve::on(),
            pressure_flow: PressureCurve::off(),
            pressure_opacity: PressureCurve::off(),
            lazy: 0.0,
            seed: 1,
        }
    }
}

/// One pointer sample.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct InputPoint {
    pub pos: Vec2,
    /// 0..1 (mouse: 1).
    pub pressure: f32,
    /// Pen tilt (x, y), -1..1 (0 = upright / unknown).
    pub tilt: Vec2,
}

impl InputPoint {
    pub fn mouse(pos: Vec2) -> Self {
        InputPoint { pos, pressure: 1.0, tilt: Vec2::ZERO }
    }
}

/// One stamp of the brush.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Dab {
    pub pos: Vec2,
    /// Multiplies the brush radius.
    pub size: f32,
    /// Radians.
    pub angle: f32,
    /// Multiplies the stroke opacity (pressure).
    pub opacity: f32,
    /// Per-dab strength (flow x pressure x jitter).
    pub flow: f32,
    pub pressure: f32,
}

/// Small deterministic RNG (xorshift), so strokes replay identically.
#[derive(Clone, Debug)]
pub struct Rng(u32);

impl Rng {
    pub fn new(seed: u32) -> Self {
        Rng(seed.wrapping_mul(747796405).wrapping_add(2891336453) | 1)
    }
    pub fn next(&mut self) -> f32 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.0 = x;
        (x >> 8) as f32 / (1u32 << 24) as f32
    }
    /// -1..1
    pub fn signed(&mut self) -> f32 {
        self.next() * 2.0 - 1.0
    }
}

/// Stateful dab generator for one stroke.
pub struct DabGenerator {
    pub dyn_: BrushDynamics,
    /// Brush diameter in pixels at full pressure.
    pub diameter: f32,
    last: Option<InputPoint>,
    /// Lazy mouse: where the brush is (trails the pointer).
    lazy_pos: Option<Vec2>,
    carry: f32,
    dir: Vec2,
    rng: Rng,
}

impl DabGenerator {
    pub fn new(dyn_: BrushDynamics, diameter: f32) -> Self {
        let rng = Rng::new(dyn_.seed);
        DabGenerator { dyn_, diameter, last: None, lazy_pos: None, carry: 0.0, dir: Vec2::X, rng }
    }

    fn dab(&mut self, pos: Vec2, pressure: f32) -> Dab {
        let d = &self.dyn_;
        let j = d.jitter;
        let mut size = d.pressure_size.eval(pressure);
        if j.size > 0.0 {
            size *= 1.0 - j.size.clamp(0.0, 1.0) * self.rng.next();
        }
        let mut angle = d.angle.to_radians();
        if d.follow_angle {
            angle += self.dir.y.atan2(self.dir.x);
        }
        if j.angle > 0.0 {
            angle += j.angle.to_radians() * self.rng.signed();
        }
        let mut p = pos;
        if j.position > 0.0 {
            let a = self.rng.next() * std::f32::consts::TAU;
            p += Vec2::new(a.cos(), a.sin()) * self.rng.next().sqrt() * j.position * self.diameter;
        }
        let mut flow = d.flow.clamp(0.0, 1.0) * d.pressure_flow.eval(pressure);
        if j.flow > 0.0 {
            flow *= 1.0 - j.flow.clamp(0.0, 1.0) * self.rng.next();
        }
        Dab { pos: p, size: size.max(0.01), angle, opacity: d.pressure_opacity.eval(pressure), flow, pressure }
    }

    fn spacing_at(&self, pressure: f32) -> f32 {
        (self.diameter * self.dyn_.pressure_size.eval(pressure) * self.dyn_.spacing.max(0.01)).max(0.5)
    }

    /// Start a stroke: always one dab at the press position.
    pub fn begin(&mut self, p: InputPoint) -> Vec<Dab> {
        self.last = Some(p);
        self.lazy_pos = Some(p.pos);
        self.carry = 0.0;
        vec![self.dab(p.pos, p.pressure)]
    }

    /// Continue to `p`: dabs every `spacing` along the path, pressure
    /// interpolated between samples.
    pub fn move_to(&mut self, p: InputPoint) -> Vec<Dab> {
        let Some(prev) = self.last else { return self.begin(p) };
        // lazy mouse: the brush only moves once the pointer is `lazy` px away
        let mut target = p;
        if self.dyn_.lazy > 0.0 {
            let at = self.lazy_pos.unwrap_or(prev.pos);
            let d = p.pos - at;
            let len = d.length();
            if len <= self.dyn_.lazy {
                return Vec::new();
            }
            target.pos = at + d / len * (len - self.dyn_.lazy);
            self.lazy_pos = Some(target.pos);
        }
        let mut out = Vec::new();
        let mut from = prev.pos;
        let total = (target.pos - prev.pos).length();
        if total > 1e-6 {
            self.dir = (target.pos - prev.pos) / total;
        }
        let mut travelled = 0.0;
        loop {
            let seg = target.pos - from;
            let len = seg.length();
            if len < 1e-6 {
                break;
            }
            let t = if total > 1e-6 { travelled / total } else { 1.0 };
            let pressure = prev.pressure + (target.pressure - prev.pressure) * t;
            let spacing = self.spacing_at(pressure);
            if self.carry + len < spacing {
                break;
            }
            let step = spacing - self.carry;
            let stamp = from + seg / len * step;
            travelled += step;
            let pr = prev.pressure + (target.pressure - prev.pressure) * (travelled / total.max(1e-6)).min(1.0);
            out.push(self.dab(stamp, pr));
            from = stamp;
            self.carry = 0.0;
        }
        self.carry += (target.pos - from).length();
        self.last = Some(target);
        out
    }

    pub fn end(&mut self) {
        self.last = None;
        self.lazy_pos = None;
        self.carry = 0.0;
    }
}

/// Points along a polyline (straight line tool, path tool), every `step` px.
pub fn polyline(points: &[Vec2], step: f32) -> Vec<Vec2> {
    let mut out = Vec::new();
    let Some(&first) = points.first() else { return out };
    out.push(first);
    for w in points.windows(2) {
        let (a, b) = (w[0], w[1]);
        let n = ((b - a).length() / step.max(0.5)).ceil().max(1.0) as usize;
        for k in 1..=n {
            out.push(a.lerp(b, k as f32 / n as f32));
        }
    }
    out
}

/// Symmetry painting: mirror planes through `center` (object space) and/or
/// radial copies around an axis.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Symmetry {
    /// Mirror across the plane x = center.x (and y, z).
    pub x: bool,
    pub y: bool,
    pub z: bool,
    /// Radial copies around `axis` (0 or 1 = none).
    pub radial: u32,
    /// Radial axis: 0 x, 1 y, 2 z.
    pub axis: u32,
    /// Centre (None = the mesh bounds centre).
    pub center: Option<[f32; 3]>,
}

/// Most symmetry copies (GPU budget).
pub const MAX_SYMMETRY: usize = 16;

impl Symmetry {
    pub fn is_off(&self) -> bool {
        !self.x && !self.y && !self.z && self.radial <= 1
    }
    /// Every transform of the symmetry group (identity first), at most
    /// MAX_SYMMETRY. A texel at p is painted when T(p) is under the brush.
    pub fn transforms(&self, mesh_center: Vec3) -> Vec<Mat4> {
        let c = self.center.map(Vec3::from).unwrap_or(mesh_center);
        let to = Mat4::from_translation(c);
        let from = Mat4::from_translation(-c);
        let mut mirrors = vec![Mat4::IDENTITY];
        for (on, s) in [(self.x, Vec3::new(-1.0, 1.0, 1.0)), (self.y, Vec3::new(1.0, -1.0, 1.0)), (self.z, Vec3::new(1.0, 1.0, -1.0))] {
            if on {
                let m = Mat4::from_scale(s);
                let more: Vec<Mat4> = mirrors.iter().map(|x| m * *x).collect();
                mirrors.extend(more);
            }
        }
        let n = self.radial.max(1);
        let mut out = Vec::new();
        for k in 0..n {
            let a = std::f32::consts::TAU * k as f32 / n as f32;
            let r = match self.axis {
                0 => Mat4::from_rotation_x(a),
                2 => Mat4::from_rotation_z(a),
                _ => Mat4::from_rotation_y(a),
            };
            for m in &mirrors {
                out.push(to * r * *m * from);
                if out.len() == MAX_SYMMETRY {
                    return out;
                }
            }
        }
        out
    }
}

/// The UV under a ray (nearest hit), for clone sources and smudge directions.
pub fn uv_at(mesh: &crate::Mesh, origin: Vec3, dir: Vec3) -> Option<Vec2> {
    let (t, _) = mesh.raycast(origin, dir)?;
    let idx = &mesh.indices[t * 3..t * 3 + 3];
    let v = idx.iter().map(|&i| &mesh.vertices[i as usize]).collect::<Vec<_>>();
    let [a, b, c] = [0, 1, 2].map(|k| Vec3::from(v[k].position));
    let (e1, e2) = (b - a, c - a);
    let p = dir.cross(e2);
    let det = e1.dot(p);
    if det.abs() < 1e-12 {
        return None;
    }
    let s = origin - a;
    let u = s.dot(p) * det.recip();
    let w = dir.dot(s.cross(e1)) * det.recip();
    let [ua, ub, uc] = [0, 1, 2].map(|k| Vec2::from(v[k].uv));
    Some(ua * (1.0 - u - w) + ub * u + uc * w)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spacing_follows_pressure_and_size_curve() {
        let mut g = DabGenerator::new(BrushDynamics { spacing: 0.25, ..Default::default() }, 40.0);
        let mut dabs = g.begin(InputPoint { pos: Vec2::ZERO, pressure: 1.0, tilt: Vec2::ZERO });
        dabs.extend(g.move_to(InputPoint { pos: Vec2::new(100.0, 0.0), pressure: 1.0, tilt: Vec2::ZERO }));
        assert_eq!(dabs.len(), 11, "10 px spacing at full pressure");
        let mut g = DabGenerator::new(BrushDynamics { spacing: 0.25, ..Default::default() }, 40.0);
        let mut light = g.begin(InputPoint { pos: Vec2::ZERO, pressure: 0.2, tilt: Vec2::ZERO });
        light.extend(g.move_to(InputPoint { pos: Vec2::new(100.0, 0.0), pressure: 0.2, tilt: Vec2::ZERO }));
        assert!(light.len() > 25, "light pressure = smaller dabs, closer together: {}", light.len());
        assert!(light.iter().all(|d| d.size < 0.4));
        // pressure ramps along a stroke
        let mut g = DabGenerator::new(BrushDynamics::default(), 40.0);
        g.begin(InputPoint { pos: Vec2::ZERO, pressure: 0.0, tilt: Vec2::ZERO });
        let ramp = g.move_to(InputPoint { pos: Vec2::new(200.0, 0.0), pressure: 1.0, tilt: Vec2::ZERO });
        assert!(ramp.windows(2).all(|w| w[1].size >= w[0].size - 1e-4));
    }

    #[test]
    fn jitter_is_seeded_and_bounded() {
        let dy = BrushDynamics { jitter: Jitter { size: 0.5, angle: 30.0, position: 0.5, flow: 0.5 }, ..Default::default() };
        let run = || {
            let mut g = DabGenerator::new(dy.clone(), 20.0);
            let mut d = g.begin(InputPoint::mouse(Vec2::ZERO));
            d.extend(g.move_to(InputPoint::mouse(Vec2::new(100.0, 0.0))));
            d
        };
        let (a, b) = (run(), run());
        assert_eq!(a, b, "same seed, same stroke");
        for d in &a {
            assert!(d.size >= 0.5 - 1e-4 && d.size <= 1.0);
            assert!(d.angle.abs() <= 30f32.to_radians() + 1e-4);
            assert!(d.pos.y.abs() <= 10.0 + 1e-3);
            assert!(d.flow >= 0.5 - 1e-4);
        }
        assert!(a.iter().any(|d| d.pos.y.abs() > 1.0), "positions scatter");
    }

    #[test]
    fn angle_follows_the_stroke_and_lazy_mouse_trails() {
        let mut g = DabGenerator::new(BrushDynamics { follow_angle: true, ..Default::default() }, 20.0);
        g.begin(InputPoint::mouse(Vec2::ZERO));
        let d = g.move_to(InputPoint::mouse(Vec2::new(0.0, 50.0)));
        assert!((d[0].angle - std::f32::consts::FRAC_PI_2).abs() < 1e-4);
        let mut g = DabGenerator::new(BrushDynamics { lazy: 30.0, ..Default::default() }, 20.0);
        g.begin(InputPoint::mouse(Vec2::ZERO));
        assert!(g.move_to(InputPoint::mouse(Vec2::new(20.0, 0.0))).is_empty(), "inside the lazy radius");
        let d = g.move_to(InputPoint::mouse(Vec2::new(100.0, 0.0)));
        assert!(d.last().unwrap().pos.x <= 70.0 + 1e-3, "trails by 30 px");
    }

    #[test]
    fn symmetry_group() {
        let s = Symmetry { x: true, ..Default::default() };
        let t = s.transforms(Vec3::new(1.0, 0.0, 0.0));
        assert_eq!(t.len(), 2);
        assert!((t[1].transform_point3(Vec3::new(3.0, 1.0, 2.0)) - Vec3::new(-1.0, 1.0, 2.0)).length() < 1e-5);
        assert_eq!(Symmetry { x: true, y: true, z: true, ..Default::default() }.transforms(Vec3::ZERO).len(), 8);
        let r = Symmetry { radial: 4, axis: 1, ..Default::default() }.transforms(Vec3::ZERO);
        assert_eq!(r.len(), 4);
        assert!((r[1].transform_point3(Vec3::X) - Vec3::new(0.0, 0.0, -1.0)).length() < 1e-5);
        assert_eq!(Symmetry { x: true, radial: 12, ..Default::default() }.transforms(Vec3::ZERO).len(), MAX_SYMMETRY);
        assert!(Symmetry::default().is_off());
    }

    #[test]
    fn polyline_and_pressure_curves() {
        let p = polyline(&[Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)], 5.0);
        assert_eq!(p.len(), 5);
        assert_eq!(*p.last().unwrap(), Vec2::new(10.0, 10.0));
        let c = PressureCurve { enabled: true, min: 0.2, gamma: 2.0 };
        assert!((c.eval(0.0) - 0.2).abs() < 1e-6 && (c.eval(1.0) - 1.0).abs() < 1e-6);
        assert!(c.eval(0.5) < 0.6);
        assert_eq!(PressureCurve::off().eval(0.0), 1.0);
    }

    #[test]
    fn uv_under_a_ray() {
        let m = crate::Mesh::tile_grid(1);
        let uv = uv_at(&m, Vec3::new(0.0, 0.0, 5.0), Vec3::new(0.0, 0.0, -1.0)).unwrap();
        assert!((uv - Vec2::splat(0.5)).length() < 1e-4, "{uv:?}");
    }
}
