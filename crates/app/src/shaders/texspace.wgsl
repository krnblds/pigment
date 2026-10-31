// Texture-space utility passes: UV rasterisation of the mesh, jump-flood
// seam padding, and mip generation.

// ---------- UV raster: world position + normal per texel ----------
struct UvOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) @interpolate(flat) part: u32,
};

@vertex
fn vs_uv(v: MeshIn, @location(4) part: u32) -> UvOut {
    var o: UvOut;
    o.pos = uv_to_clip(v.uv);
    o.world = v.position;
    o.normal = v.normal;
    o.part = part;
    return o;
}

struct UvTargets {
    @location(0) position: vec4<f32>,  // xyz world, w = 1 where the mesh covers the texel
    @location(1) normal: vec4<f32>,
    @location(2) part: vec4<u32>,      // mesh part id + 1 (0 = no surface)
};

@fragment
fn fs_uv(i: UvOut) -> UvTargets {
    var o: UvTargets;
    o.position = vec4<f32>(i.world, 1.0);
    o.normal = vec4<f32>(normalize(i.normal), 1.0);
    o.part = vec4<u32>(min(i.part + 1u, 65535u), 0u, 0u, 0u);
    return o;
}

// ---------- Jump flood: nearest covered texel for every texel ----------
// Seeds are covered texels. After log2(N) passes with halving step sizes each
// texel holds the coordinate of (approximately) the nearest seed. Padding then
// becomes a single lookup, so it costs nothing per stroke.

@group(0) @binding(0) var jfa_src: texture_2d<u32>;
@group(0) @binding(1) var coverage: texture_2d<f32>;
struct JfaParams { step: i32, size: i32, _a: i32, _b: i32 };
@group(0) @binding(2) var<uniform> jp: JfaParams;

const NONE: u32 = 65535u;

@fragment
fn fs_jfa_init(f: FullOut) -> @location(0) vec4<u32> {
    let t = vec2<i32>(f.pos.xy);
    if (textureLoad(coverage, t, 0).w > 0.5) {
        return vec4<u32>(u32(t.x), u32(t.y), 0u, 0u);
    }
    return vec4<u32>(NONE, NONE, 0u, 0u);
}

@fragment
fn fs_jfa_step(f: FullOut) -> @location(0) vec4<u32> {
    let t = vec2<i32>(f.pos.xy);
    var best = textureLoad(jfa_src, t, 0).xy;
    var best_d = 1e30;
    if (best.x != NONE) {
        let d = vec2<f32>(vec2<i32>(best)) - vec2<f32>(t);
        best_d = dot(d, d);
    }
    for (var y = -1; y <= 1; y++) {
        for (var x = -1; x <= 1; x++) {
            let q = t + vec2<i32>(x, y) * jp.step;
            if (q.x < 0 || q.y < 0 || q.x >= jp.size || q.y >= jp.size) { continue; }
            let s = textureLoad(jfa_src, q, 0).xy;
            if (s.x == NONE) { continue; }
            let d = vec2<f32>(vec2<i32>(s)) - vec2<f32>(t);
            let dd = dot(d, d);
            if (dd < best_d) { best_d = dd; best = s; }
        }
    }
    return vec4<u32>(best, 0u, 0u);
}

