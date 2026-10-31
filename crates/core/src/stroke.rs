//! Brush stroke resampling: turns an irregular stream of pointer positions
//! into evenly spaced stamps, so a stroke's density doesn't depend on how fast
//! the mouse moved or on the frame rate.

use glam::Vec2;

#[derive(Default)]
pub struct StrokeSampler {
    last: Option<Vec2>,
    /// Distance travelled since the last stamp.
    carry: f32,
}

impl StrokeSampler {
    /// Start a stroke: always stamps at the press position.
    pub fn begin(&mut self, p: Vec2) -> Vec<Vec2> {
        self.last = Some(p);
        self.carry = 0.0;
        vec![p]
    }

    /// Continue to `p`, emitting a stamp every `spacing` pixels along the path.
    pub fn move_to(&mut self, p: Vec2, spacing: f32) -> Vec<Vec2> {
        let spacing = spacing.max(0.5);
        let Some(mut from) = self.last else { return self.begin(p) };
        let mut out = Vec::new();
        let mut seg = p - from;
        let mut len = seg.length();
        while len > 1e-6 && self.carry + len >= spacing {
            let step = spacing - self.carry;
            let stamp = from + seg / len * step;
            out.push(stamp);
            from = stamp;
            seg = p - from;
            len = seg.length();
            self.carry = 0.0;
        }
        self.carry += len;
        self.last = Some(p);
        out
    }

    pub fn end(&mut self) {
        self.last = None;
        self.carry = 0.0;
    }

    pub fn active(&self) -> bool {
        self.last.is_some()
    }
}

/// Brush falloff for a normalised distance `d` (0 at centre, 1 at rim).
/// `hardness` 1 = hard disc, 0 = smooth bell. Mirrored in `paint.wgsl`.
pub fn falloff(d: f32, hardness: f32) -> f32 {
    if d >= 1.0 {
        return 0.0;
    }
    let h = hardness.clamp(0.0, 0.999);
    let t = ((d - h) / (1.0 - h)).clamp(0.0, 1.0);
    1.0 - t * t * (3.0 - 2.0 * t)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evenly_spaced_regardless_of_event_chunking() {
        let mut a = StrokeSampler::default();
        let mut stamps = a.begin(Vec2::ZERO);
        stamps.extend(a.move_to(Vec2::new(100.0, 0.0), 10.0));
        assert_eq!(stamps.len(), 11);

        let mut b = StrokeSampler::default();
        let mut s2 = b.begin(Vec2::ZERO);
        for x in [3.0, 4.0, 17.5, 18.0, 55.0, 99.0, 100.0] {
            s2.extend(b.move_to(Vec2::new(x, 0.0), 10.0));
        }
        assert_eq!(s2.len(), 11);
        for (i, s) in s2.iter().enumerate() {
            assert!((s.x - i as f32 * 10.0).abs() < 1e-3, "{s:?}");
        }
    }

    #[test]
    fn spacing_follows_corners() {
        let mut s = StrokeSampler::default();
        s.begin(Vec2::ZERO);
        s.move_to(Vec2::new(5.0, 0.0), 10.0);
        let out = s.move_to(Vec2::new(5.0, 5.0), 10.0);
        assert_eq!(out.len(), 1);
        assert!((out[0] - Vec2::new(5.0, 5.0)).length() < 1e-4);
    }

    #[test]
    fn tiny_spacing_is_clamped() {
        let mut s = StrokeSampler::default();
        s.begin(Vec2::ZERO);
        assert_eq!(s.move_to(Vec2::new(10.0, 0.0), 0.0).len(), 20);
    }

    #[test]
    fn falloff_shape() {
        assert_eq!(falloff(0.0, 0.0), 1.0);
        assert_eq!(falloff(1.0, 0.5), 0.0);
        assert_eq!(falloff(0.4, 0.5), 1.0);
        assert!(falloff(0.75, 0.5) > 0.0 && falloff(0.75, 0.5) < 1.0);
        let mut prev = 1.0;
        for i in 0..=100 {
            let f = falloff(i as f32 / 100.0, 0.3);
            assert!(f <= prev + 1e-6);
            prev = f;
        }
    }
}
