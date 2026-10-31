// Shared helpers, prepended to every other shader.

struct FullOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

// Fullscreen triangle. uv (0,0) = top-left, matching texture addressing.
@vertex
fn vs_full(@builtin(vertex_index) vi: u32) -> FullOut {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    var o: FullOut;
    o.pos = vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
    o.uv = vec2<f32>(p.x, 1.0 - p.y);
    return o;
}

// Mesh vertex as laid out in pigment_core::Vertex.
struct MeshIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) tangent: vec4<f32>,
};

// Place a vertex at its UV coordinate: rasterising the mesh "into the texture".
// v points down in texture space, clip-space y points up.
fn uv_to_clip(uv: vec2<f32>) -> vec4<f32> {
    return vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.0, 1.0);
}

const PI: f32 = 3.14159265359;

fn srgb_to_linear(c: vec3<f32>) -> vec3<f32> {
    let lo = c / 12.92;
    let hi = pow((c + 0.055) / 1.055, vec3<f32>(2.4));
    return select(hi, lo, c <= vec3<f32>(0.04045));
}

// --- blend modes: must match pigment_core::blend ---
// ids: 0 Normal 1 Multiply 2 Screen 3 Overlay 4 Add 5 Subtract 6 Darken 7 Lighten 8 Replace 9 NormalCombine
fn blend_f(mode: u32, d: f32, s: f32) -> f32 {
    switch mode {
        case 1u: { return d * s; }
        case 2u: { return 1.0 - (1.0 - d) * (1.0 - s); }
        case 3u: { return select(1.0 - 2.0 * (1.0 - d) * (1.0 - s), 2.0 * d * s, d < 0.5); }
        case 4u: { return d + s; }
        case 5u: { return d - s; }
        case 6u: { return min(d, s); }
        case 7u: { return max(d, s); }
        default: { return s; }
    }
}

fn blend_scalar(mode: u32, d: f32, s: f32, a: f32) -> f32 {
    return d + (blend_f(mode, d, s) - d) * clamp(a, 0.0, 1.0);
}

fn blend_rgb(mode: u32, d: vec3<f32>, s: vec3<f32>, a: f32) -> vec3<f32> {
    return vec3<f32>(blend_scalar(mode, d.x, s.x, a), blend_scalar(mode, d.y, s.y, a), blend_scalar(mode, d.z, s.z, a));
}

// Reoriented normal mapping.
fn rnm(b: vec3<f32>, d: vec3<f32>) -> vec3<f32> {
    let t = b + vec3<f32>(0.0, 0.0, 1.0);
    let u = d * vec3<f32>(-1.0, -1.0, 1.0);
    return normalize(t * dot(t, u) - u * t.z);
}

fn blend_normal(mode: u32, d: vec3<f32>, s: vec3<f32>, a: f32) -> vec3<f32> {
    var tgt = s;
    if (mode == 9u) { tgt = rnm(d, s); }
    return normalize(mix(d, tgt, clamp(a, 0.0, 1.0)));
}

// Brush falloff: must match pigment_core::stroke::falloff.
fn falloff(d: f32, hardness: f32) -> f32 {
    if (d >= 1.0) { return 0.0; }
    let h = clamp(hardness, 0.0, 0.999);
    let t = clamp((d - h) / (1.0 - h), 0.0, 1.0);
    return 1.0 - t * t * (3.0 - 2.0 * t);
}

// --- noise for generators: 3D value noise fbm, seamless because it's
// evaluated on world position, not UVs ---
fn hash3(p: vec3<f32>) -> f32 {
    var q = fract(p * 0.1031);
    q += dot(q, q.zyx + 31.32);
    return fract((q.x + q.y) * q.z);
}

fn vnoise(p: vec3<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let a = mix(mix(hash3(i), hash3(i + vec3<f32>(1.0, 0.0, 0.0)), u.x),
                mix(hash3(i + vec3<f32>(0.0, 1.0, 0.0)), hash3(i + vec3<f32>(1.0, 1.0, 0.0)), u.x), u.y);
    let b = mix(mix(hash3(i + vec3<f32>(0.0, 0.0, 1.0)), hash3(i + vec3<f32>(1.0, 0.0, 1.0)), u.x),
                mix(hash3(i + vec3<f32>(0.0, 1.0, 1.0)), hash3(i + vec3<f32>(1.0, 1.0, 1.0)), u.x), u.y);
    return mix(a, b, u.z);
}

fn fbm(p: vec3<f32>) -> f32 {
    var s = 0.0;
    var amp = 0.5;
    var q = p;
    for (var i = 0; i < 5; i++) {
        s += vnoise(q) * amp;
        q = q * 2.03 + vec3<f32>(17.1, 3.7, 9.2);
        amp *= 0.5;
    }
    return s / 0.96875;
}
