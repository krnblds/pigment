//! Image-based lighting math done on the CPU: equirectangular direction
//! mapping, 9-coefficient spherical harmonics for diffuse irradiance, the
//! split-sum BRDF lookup table, and a procedural studio environment so the
//! app looks right with no HDRI on disk.
//!
//! Direction convention (mirrored in `env.wgsl` / `viewport.wgsl`):
//! u = 0..1 wraps around +Y; v = 0 at the zenith (+Y), v = 1 at the nadir.

use glam::{Vec2, Vec3};
use std::f32::consts::PI;

pub struct EnvImage {
    pub width: u32,
    pub height: u32,
    /// Linear RGB radiance, row-major.
    pub data: Vec<[f32; 3]>,
}

pub fn dir_from_uv(uv: Vec2) -> Vec3 {
    let phi = uv.x * 2.0 * PI - PI;
    let theta = uv.y * PI;
    Vec3::new(theta.sin() * phi.sin(), theta.cos(), -theta.sin() * phi.cos())
}

pub fn uv_from_dir(d: Vec3) -> Vec2 {
    let phi = d.x.atan2(-d.z);
    let theta = d.y.clamp(-1.0, 1.0).acos();
    Vec2::new((phi + PI) / (2.0 * PI), theta / PI)
}

impl EnvImage {
    /// A neutral photo-studio: dim floor, soft grey walls, three softboxes.
    /// Bright, broad light sources read well on both rough and glossy materials.
    pub fn studio(width: u32) -> EnvImage {
        let height = width / 2;
        let boxes = [
            // direction, angular half-size (u, v), intensity, tint
            (Vec3::new(-0.6, 0.6, 0.55).normalize(), Vec2::new(0.35, 0.22), 9.0, Vec3::new(1.0, 0.97, 0.92)),
            (Vec3::new(0.75, 0.35, -0.2).normalize(), Vec2::new(0.18, 0.3), 5.0, Vec3::new(0.9, 0.95, 1.0)),
            (Vec3::new(0.1, 0.9, -0.5).normalize(), Vec2::new(0.4, 0.4), 3.0, Vec3::ONE),
        ];
        let mut data = Vec::with_capacity((width * height) as usize);
        for y in 0..height {
            for x in 0..width {
                let uv = Vec2::new((x as f32 + 0.5) / width as f32, (y as f32 + 0.5) / height as f32);
                let d = dir_from_uv(uv);
                // walls/floor gradient
                let t = d.y * 0.5 + 0.5;
                let floor = Vec3::new(0.16, 0.15, 0.14);
                let wall = Vec3::new(0.32, 0.32, 0.33);
                let ceil = Vec3::new(0.55, 0.56, 0.6);
                let mut c = if d.y < 0.0 { floor.lerp(wall, (t * 2.0).powf(3.0)) } else { wall.lerp(ceil, (t - 0.5) * 2.0) };
                for (dir, half, intensity, tint) in boxes {
                    // local frame around the box direction
                    let right = dir.cross(Vec3::Y).normalize_or(Vec3::X);
                    let up = right.cross(dir);
                    let along = d.dot(dir);
                    if along <= 0.0 {
                        continue;
                    }
                    let p = Vec2::new(d.dot(right), d.dot(up)) / along;
                    let q = (p.abs() / half).max_element();
                    // soft-edged rectangle
                    let k = (1.0 - ((q - 0.85) / 0.3).clamp(0.0, 1.0)).powf(2.0);
                    c += tint * intensity * k;
                }
                data.push(c.into());
            }
        }
        EnvImage { width, height, data }
    }

    /// Built-in lighting by name: `studio`, `night` (night city) or `overcast`.
    pub fn preset(name: &str, width: u32) -> Option<EnvImage> {
        match preset_id(name)? {
            "studio" => Some(Self::studio(width)),
            "night" => Some(Self::night_city(width)),
            "overcast" => Some(Self::overcast(width)),
            _ => None,
        }
    }

    /// A rainy cyberpunk street at night: a dark blue sky with a magenta and
    /// sodium light-pollution glow at the horizon, a skyline of lit windows,
    /// wet dark ground, a cyan and a magenta neon rim light behind the model
    /// (camera-default view) and a dim sodium street lamp as a key light.
    pub fn night_city(width: u32) -> EnvImage {
        let height = width / 2;
        // direction, angular half-size (u, v), intensity, tint
        let lights = [
            (Vec3::new(-0.8, 0.2, -0.45).normalize(), Vec2::new(0.1, 0.6), 8.0, Vec3::new(0.15, 0.75, 1.0)),
            (Vec3::new(0.82, 0.25, -0.4).normalize(), Vec2::new(0.1, 0.6), 8.0, Vec3::new(1.0, 0.12, 0.62)),
            (Vec3::new(0.4, 0.7, 0.6).normalize(), Vec2::new(0.16, 0.16), 24.0, Vec3::new(1.0, 0.62, 0.3)),
        ];
        let mut data = Vec::with_capacity((width * height) as usize);
        for y in 0..height {
            for x in 0..width {
                let uv = Vec2::new((x as f32 + 0.5) / width as f32, (y as f32 + 0.5) / height as f32);
                let d = dir_from_uv(uv);
                let zenith = Vec3::new(0.012, 0.022, 0.07);
                let glow = Vec3::new(0.09, 0.045, 0.1);
                let mut c = if d.y >= 0.0 {
                    let mut sky = zenith.lerp(glow, (1.0 - d.y).powf(6.0));
                    // skyline: blocky building silhouettes with lit windows
                    let col = (uv.x * 96.0).floor();
                    let top = 0.03 + 0.17 * hash(col, 3.0).powf(1.6);
                    if d.y < top {
                        sky = Vec3::new(0.006, 0.006, 0.012);
                        let wy = (d.y * 140.0).floor();
                        let wx = (uv.x * 96.0 * 6.0).floor();
                        let lit = hash(wx, wy);
                        if lit > 0.78 && (d.y * 140.0).fract() > 0.35 && (uv.x * 576.0).fract() > 0.3 {
                            let warm = Vec3::new(1.0, 0.7, 0.4);
                            let cool = Vec3::new(0.4, 0.8, 1.0);
                            let pink = Vec3::new(1.0, 0.3, 0.7);
                            let tint = if lit > 0.95 { pink } else if lit > 0.88 { cool } else { warm };
                            sky += tint * 0.6;
                        }
                    }
                    sky
                } else {
                    // wet asphalt: dark, picks up a little of the horizon glow
                    Vec3::new(0.01, 0.012, 0.022).lerp(glow * 0.35, (1.0 + d.y).powf(10.0))
                };
                for (dir, half, intensity, tint) in lights {
                    c += tint * intensity * soft_rect(d, dir, half);
                }
                data.push(c.into());
            }
        }
        EnvImage { width, height, data }
    }

    /// A uniformly overcast day (CIE overcast sky: the zenith is three times
    /// brighter than the horizon) over a mid-grey ground. Soft, shadowless,
    /// neutral: good for judging albedo and roughness.
    pub fn overcast(width: u32) -> EnvImage {
        let height = width / 2;
        let mut data = Vec::with_capacity((width * height) as usize);
        let sky = Vec3::new(0.95, 0.98, 1.04) * 1.6;
        let ground = Vec3::new(0.2, 0.19, 0.18);
        for y in 0..height {
            for x in 0..width {
                let uv = Vec2::new((x as f32 + 0.5) / width as f32, (y as f32 + 0.5) / height as f32);
                let d = dir_from_uv(uv);
                let horizon = sky / 3.0;
                let c = if d.y >= 0.0 { sky * (1.0 + 2.0 * d.y) / 3.0 } else { ground.lerp(horizon, (1.0 + d.y).powf(24.0)) };
                data.push(c.into());
            }
        }
        EnvImage { width, height, data }
    }

    /// Write as a Radiance .hdr (e.g. to light a Blender world identically).
    pub fn write_hdr(&self, path: &std::path::Path) -> anyhow::Result<()> {
        let px: Vec<image::Rgb<f32>> = self.data.iter().map(|c| image::Rgb(*c)).collect();
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let f = std::io::BufWriter::new(std::fs::File::create(path)?);
        image::codecs::hdr::HdrEncoder::new(f).encode(&px, self.width as usize, self.height as usize)?;
        Ok(())
    }

    pub fn from_rgb32f(width: u32, height: u32, rgb: &[f32]) -> EnvImage {
        let data = rgb.chunks_exact(3).map(|c| [c[0].max(0.0), c[1].max(0.0), c[2].max(0.0)]).collect();
        EnvImage { width, height, data }
    }

    /// 9 SH coefficients of irradiance / pi, i.e. ready to multiply by albedo.
    pub fn irradiance_sh9(&self) -> [Vec3; 9] {
        let mut l = [Vec3::ZERO; 9];
        // coarse stride is plenty: SH9 is extremely low frequency
        let step = (self.width / 256).max(1);
        let mut wsum = 0.0;
        for y in (0..self.height).step_by(step as usize) {
            let v = (y as f32 + 0.5) / self.height as f32;
            let sin_t = (v * PI).sin();
            for x in (0..self.width).step_by(step as usize) {
                let u = (x as f32 + 0.5) / self.width as f32;
                let d = dir_from_uv(Vec2::new(u, v));
                let c = Vec3::from(self.data[(y * self.width + x) as usize]);
                let w = sin_t; // solid angle of an equirect texel ∝ sin(theta)
                wsum += w;
                let b = sh_basis(d);
                for i in 0..9 {
                    l[i] += c * b[i] * w;
                }
            }
        }
        let norm = 4.0 * PI / wsum;
        // convolve with the clamped cosine lobe (Ramamoorthi & Hanrahan), divide by pi
        let a = [PI, 2.0 * PI / 3.0, 2.0 * PI / 3.0, 2.0 * PI / 3.0, PI / 4.0, PI / 4.0, PI / 4.0, PI / 4.0, PI / 4.0];
        let mut out = [Vec3::ZERO; 9];
        for i in 0..9 {
            out[i] = l[i] * norm * a[i] / PI;
        }
        out
    }
}

/// Built-in lighting presets: (id, display name).
pub const PRESETS: [(&str, &str); 3] = [("studio", "Studio"), ("night", "Night city"), ("overcast", "Overcast")];

/// Canonical preset id for a user-facing name (`night city`, `Night`, `night_city` → `night`).
pub fn preset_id(name: &str) -> Option<&'static str> {
    let n = name.trim().to_ascii_lowercase().replace([' ', '-', '_'], "");
    PRESETS.iter().find(|(id, label)| n == *id || n == label.to_ascii_lowercase().replace(' ', "")).map(|(id, _)| *id)
}

/// Soft-edged rectangular light around `dir` (angular half-size `half`), 0..1.
fn soft_rect(d: Vec3, dir: Vec3, half: Vec2) -> f32 {
    let along = d.dot(dir);
    if along <= 0.0 {
        return 0.0;
    }
    let right = dir.cross(Vec3::Y).normalize_or(Vec3::X);
    let up = right.cross(dir);
    let p = Vec2::new(d.dot(right), d.dot(up)) / along;
    let q = (p.abs() / half).max_element();
    (1.0 - ((q - 0.85) / 0.3).clamp(0.0, 1.0)).powf(2.0)
}

fn hash(x: f32, y: f32) -> f32 {
    ((x * 12.9898 + y * 78.233).sin() * 43_758.547).fract().abs()
}

pub fn sh_basis(d: Vec3) -> [f32; 9] {
    [
        0.282095,
        0.488603 * d.y,
        0.488603 * d.z,
        0.488603 * d.x,
        1.092548 * d.x * d.y,
        1.092548 * d.y * d.z,
        0.315392 * (3.0 * d.z * d.z - 1.0),
        1.092548 * d.x * d.z,
        0.546274 * (d.x * d.x - d.y * d.y),
    ]
}

pub fn eval_sh9(sh: &[Vec3; 9], n: Vec3) -> Vec3 {
    let b = sh_basis(n);
    (0..9).fold(Vec3::ZERO, |acc, i| acc + sh[i] * b[i])
}

fn hammersley(i: u32, n: u32) -> Vec2 {
    Vec2::new(i as f32 / n as f32, i.reverse_bits() as f32 * 2.328_306_4e-10)
}

fn importance_ggx(xi: Vec2, roughness: f32) -> Vec3 {
    let a = roughness * roughness;
    let phi = 2.0 * PI * xi.x;
    let cos_t = ((1.0 - xi.y) / (1.0 + (a * a - 1.0) * xi.y)).sqrt();
    let sin_t = (1.0 - cos_t * cos_t).sqrt();
    Vec3::new(sin_t * phi.cos(), sin_t * phi.sin(), cos_t)
}

/// Split-sum environment BRDF (Karis 2013): (scale, bias) to F0, indexed by
/// (N·V, roughness). Returned row-major, `size × size`, row = roughness.
pub fn brdf_lut(size: u32, samples: u32) -> Vec<[f32; 2]> {
    let mut out = Vec::with_capacity((size * size) as usize);
    for y in 0..size {
        let rough = (y as f32 + 0.5) / size as f32;
        for x in 0..size {
            let nv = ((x as f32 + 0.5) / size as f32).max(1e-3);
            let v = Vec3::new((1.0 - nv * nv).sqrt(), 0.0, nv);
            let (mut a, mut b) = (0.0, 0.0);
            let k = rough * rough / 2.0;
            let g1 = |c: f32| c / (c * (1.0 - k) + k);
            for i in 0..samples {
                let h = importance_ggx(hammersley(i, samples), rough);
                let l = 2.0 * v.dot(h) * h - v;
                let nl = l.z.max(0.0);
                let nh = h.z.max(0.0);
                let vh = v.dot(h).max(0.0);
                if nl > 0.0 {
                    let g = g1(nv) * g1(nl);
                    let gv = g * vh / (nh * nv).max(1e-6);
                    let fc = (1.0 - vh).powi(5);
                    a += (1.0 - fc) * gv;
                    b += fc * gv;
                }
            }
            out.push([a / samples as f32, b / samples as f32]);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uv_dir_round_trip() {
        for (u, v) in [(0.1, 0.2), (0.5, 0.5), (0.9, 0.7), (0.3, 0.95)] {
            let uv = Vec2::new(u, v);
            let back = uv_from_dir(dir_from_uv(uv));
            assert!((back - uv).length() < 1e-4, "{uv} -> {back}");
        }
        assert!((dir_from_uv(Vec2::new(0.5, 0.0)) - Vec3::Y).length() < 1e-5);
    }

    #[test]
    fn constant_environment_gives_constant_irradiance() {
        let env = EnvImage { width: 64, height: 32, data: vec![[1.0, 0.5, 0.25]; 64 * 32] };
        let sh = env.irradiance_sh9();
        for n in [Vec3::X, Vec3::Y, -Vec3::Z, Vec3::new(1.0, 1.0, 1.0).normalize()] {
            // white furnace: a uniform environment of radiance L gives diffuse radiance L
            let e = eval_sh9(&sh, n);
            assert!((e - Vec3::new(1.0, 0.5, 0.25)).length() < 0.03, "{n} -> {e}");
        }
    }

    #[test]
    fn sky_lights_the_top_more_than_the_bottom() {
        let env = EnvImage::studio(128);
        let sh = env.irradiance_sh9();
        assert!(eval_sh9(&sh, Vec3::Y).x > eval_sh9(&sh, -Vec3::Y).x);
    }

    #[test]
    fn lighting_presets_resolve_and_differ() {
        assert_eq!(preset_id("Night city"), Some("night"));
        assert_eq!(preset_id("night_city"), Some("night"));
        assert_eq!(preset_id("OVERCAST"), Some("overcast"));
        assert_eq!(preset_id("disco"), None);
        let mean = |e: &EnvImage| e.data.iter().map(|c| Vec3::from(*c)).sum::<Vec3>() / e.data.len() as f32;
        let night = EnvImage::preset("night", 256).unwrap();
        let overcast = EnvImage::preset("overcast", 256).unwrap();
        let (mn, mo) = (mean(&night), mean(&overcast));
        // night is darker on average (mostly sky; a few bright lamps); overcast is near-neutral
        assert!(mn.length() < 0.5 * mo.length(), "{mn} vs {mo}");
        let dark = night.data.iter().filter(|c| Vec3::from(**c).max_element() < 0.12).count();
        assert!(dark > night.data.len() * 3 / 4, "night sky should be mostly dark ({dark})");
        assert!((mo.x - mo.z).abs() < 0.15 * mo.z, "{mo}");
        // night has strongly coloured rim lights: some texels are bright cyan, some magenta
        assert!(night.data.iter().any(|c| c[2] > 5.0 && c[0] < 2.0));
        assert!(night.data.iter().any(|c| c[0] > 5.0 && c[1] < 2.0));
        // overcast: brighter overhead than at the horizon
        let sh = overcast.irradiance_sh9();
        assert!(eval_sh9(&sh, Vec3::Y).y > eval_sh9(&sh, Vec3::X).y);
    }

    #[test]
    fn environment_round_trips_through_hdr() {
        let env = EnvImage::night_city(64);
        let p = std::env::temp_dir().join(format!("pigment-env-{}.hdr", std::process::id()));
        env.write_hdr(&p).unwrap();
        let back = image::open(&p).unwrap().to_rgb32f();
        assert_eq!((back.width(), back.height()), (64, 32));
        let a = Vec3::from(env.data[100]);
        let r = &back.as_raw()[300..303];
        let b = Vec3::new(r[0], r[1], r[2]);
        assert!((a - b).length() <= 0.02 * a.length() + 1e-3, "{a} vs {b}");
        std::fs::remove_file(p).ok();
    }

    #[test]
    fn brdf_lut_is_energy_bounded() {
        let lut = brdf_lut(16, 64);
        for [a, b] in &lut {
            assert!(*a >= 0.0 && *b >= 0.0 && a + b <= 1.05, "{a} {b}");
        }
        // smooth surface viewed head-on reflects ~F0: scale ≈ 1, bias ≈ 0
        let [a, b] = lut[15];
        assert!(a > 0.9 && b < 0.05, "{a} {b}");
    }
}
