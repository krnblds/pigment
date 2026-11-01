// Viewport post-processing: mip-chain bloom and ACES tone mapping.
//
// The viewport renders into an HDR target. Alpha marks how a pixel is meant
// to be displayed: 1 = scene-referred radiance (tone-mapped here, may bloom),
// 0 = already display-referred (channel/debug views, the plain gradient
// background), passed through untouched.
//
// Bloom (Jimenez 2014, "Next generation post processing in Call of Duty"):
//   fs_down_first  full-res HDR -> bloom mip 0: 13-tap filter with a Karis
//                  average (no fireflies) and a soft-knee threshold
//   fs_down        bloom mip i-1 -> mip i: the same 13-tap filter
//   fs_up          mip i+1 -> mip i: 3x3 tent, blended with the hardware blend
//                  constant (= radius): mip_i = mix(mip_i, up(mip_i+1), radius)
//   fs_composite   HDR + intensity * bloom, then tone map

struct Post {
    bloom: vec4<f32>,  // x threshold, y knee, z intensity, w radius
    flags: vec4<f32>,  // x bloom on (0/1)
};

@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var samp: sampler;
@group(0) @binding(2) var<uniform> post: Post;
@group(0) @binding(3) var bloom_tex: texture_2d<f32>;

// ACES filmic, Hill's fit (sRGB -> ACES AP1 -> RRT/ODT -> sRGB).
fn aces(c: vec3<f32>) -> vec3<f32> {
    let i = mat3x3<f32>(
        vec3<f32>(0.59719, 0.07600, 0.02840),
        vec3<f32>(0.35458, 0.90834, 0.13383),
        vec3<f32>(0.04823, 0.01566, 0.83777));
    let o = mat3x3<f32>(
        vec3<f32>(1.60475, -0.10208, -0.00327),
        vec3<f32>(-0.53108, 1.10813, -0.07276),
        vec3<f32>(-0.07367, -0.00605, 1.07602));
    let v = i * c;
    let a = v * (v + 0.0245786) - 0.000090537;
    let b = v * (0.983729 * v + 0.4329510) + 0.238081;
    return clamp(o * (a / b), vec3<f32>(0.0), vec3<f32>(1.0));
}

fn luma(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
}

// Only scene-referred pixels (alpha 1) feed the bloom.
fn tap(uv: vec2<f32>) -> vec3<f32> {
    let c = textureSampleLevel(src, samp, uv, 0.0);
    return max(c.rgb, vec3<f32>(0.0)) * clamp(c.a, 0.0, 1.0);
}

fn karis(a: vec3<f32>, b: vec3<f32>, c: vec3<f32>, d: vec3<f32>) -> vec4<f32> {
    let m = (a + b + c + d) * 0.25;
    let w = 1.0 / (1.0 + luma(m));
    return vec4<f32>(m * w, w);
}

fn down13(uv: vec2<f32>, first: bool) -> vec3<f32> {
    let t = 1.0 / vec2<f32>(textureDimensions(src));
    let a = tap(uv + t * vec2<f32>(-2.0, -2.0));
    let b = tap(uv + t * vec2<f32>(0.0, -2.0));
    let c = tap(uv + t * vec2<f32>(2.0, -2.0));
    let d = tap(uv + t * vec2<f32>(-2.0, 0.0));
    let e = tap(uv);
    let f = tap(uv + t * vec2<f32>(2.0, 0.0));
    let g = tap(uv + t * vec2<f32>(-2.0, 2.0));
    let h = tap(uv + t * vec2<f32>(0.0, 2.0));
    let i = tap(uv + t * vec2<f32>(2.0, 2.0));
    let j = tap(uv + t * vec2<f32>(-1.0, -1.0));
    let k = tap(uv + t * vec2<f32>(1.0, -1.0));
    let l = tap(uv + t * vec2<f32>(-1.0, 1.0));
    let m = tap(uv + t * vec2<f32>(1.0, 1.0));
    if (first) {
        // Karis average per 2x2 group: a single very bright texel can't
        // dominate, which keeps the bloom from flickering as the camera moves.
        let s = karis(j, k, l, m) * 0.5
            + karis(a, b, d, e) * 0.125 + karis(b, c, e, f) * 0.125
            + karis(d, e, g, h) * 0.125 + karis(e, f, h, i) * 0.125;
        return s.rgb / max(s.a, 1e-5);
    }
    return e * 0.125 + (a + c + g + i) * 0.03125 + (b + d + f + h) * 0.0625 + (j + k + l + m) * 0.125;
}

// Soft-knee threshold on the brightest channel.
fn threshold(c: vec3<f32>) -> vec3<f32> {
    let br = max(c.r, max(c.g, c.b));
    let knee = max(post.bloom.y, 1e-4);
    var rq = clamp(br - post.bloom.x + knee, 0.0, 2.0 * knee);
    rq = rq * rq / (4.0 * knee);
    return c * (max(rq, br - post.bloom.x) / max(br, 1e-5));
}

@fragment
fn fs_down_first(f: FullOut) -> @location(0) vec4<f32> {
    return vec4<f32>(min(threshold(down13(f.uv, true)), vec3<f32>(6.0e4)), 1.0);
}

@fragment
fn fs_down(f: FullOut) -> @location(0) vec4<f32> {
    return vec4<f32>(down13(f.uv, false), 1.0);
}

fn up9(tex: texture_2d<f32>, uv: vec2<f32>) -> vec3<f32> {
    let t = 1.0 / vec2<f32>(textureDimensions(tex));
    var s = textureSampleLevel(tex, samp, uv, 0.0).rgb * 4.0;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(0.0, -1.0), 0.0).rgb * 2.0;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(-1.0, 0.0), 0.0).rgb * 2.0;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(1.0, 0.0), 0.0).rgb * 2.0;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(0.0, 1.0), 0.0).rgb * 2.0;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(-1.0, -1.0), 0.0).rgb;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(1.0, -1.0), 0.0).rgb;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(-1.0, 1.0), 0.0).rgb;
    s += textureSampleLevel(tex, samp, uv + t * vec2<f32>(1.0, 1.0), 0.0).rgb;
    return s / 16.0;
}

@fragment
fn fs_up(f: FullOut) -> @location(0) vec4<f32> {
    return vec4<f32>(up9(src, f.uv), 1.0);
}

@fragment
fn fs_composite(f: FullOut) -> @location(0) vec4<f32> {
    let h = textureLoad(src, vec2<i32>(f.pos.xy), 0);
    var b = vec3<f32>(0.0);
    if (post.flags.x > 0.5) {
        b = up9(bloom_tex, f.uv) * post.bloom.z;
    }
    let a = clamp(h.a, 0.0, 1.0);
    let c = max(h.rgb, vec3<f32>(0.0));
    let ldr = mix(min(c, vec3<f32>(1.0)), aces(c + b), a) + (1.0 - a) * aces(b);
    return vec4<f32>(min(ldr, vec3<f32>(1.0)), 1.0);
}
