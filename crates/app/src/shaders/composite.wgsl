// Layer compositing (one pass per visible layer, bottom to top) and the
// finalize pass that turns the composited stack into the material textures.
//
// Accumulation set (all Rgba16Float):
//   acc_color.rgb  linear base colour
//   acc_rmh        roughness, metallic, height
//   acc_normal.xyz tangent-space detail normal (painted / filled normals)
//   acc_emissive   linear HDR emission

// ---- group 0: mesh-derived data shared by every layer ----
@group(0) @binding(0) var bakes: texture_2d<f32>;      // r = AO, g = curvature (0.5 neutral)
@group(0) @binding(1) var position: texture_2d<f32>;   // world position, w = coverage
@group(0) @binding(2) var nearest: texture_2d<u32>;    // jump-flood nearest covered texel
struct Shared {
    center_radius: vec4<f32>,   // bounding sphere for noise space
    res: vec4<f32>,             // x = resolution, y = height-to-normal strength
};
@group(0) @binding(3) var<uniform> sh: Shared;
@group(0) @binding(4) var wnormal: texture_2d<f32>;    // world normal

// ---- group 1: accumulation input ----
@group(1) @binding(0) var acc_color: texture_2d<f32>;
@group(1) @binding(1) var acc_rmh: texture_2d<f32>;
@group(1) @binding(2) var acc_normal: texture_2d<f32>;
@group(1) @binding(3) var acc_emissive: texture_2d<f32>;

// ---- group 2: the layer ----
@group(2) @binding(0) var l_color: texture_2d<f32>;    // srgb view: rgb linear, a coverage
@group(2) @binding(1) var l_rough: texture_2d<f32>;    // r value, g coverage
@group(2) @binding(2) var l_metal: texture_2d<f32>;
@group(2) @binding(3) var l_height: texture_2d<f32>;   // r value (-1..1), g coverage
@group(2) @binding(4) var l_normal: texture_2d<f32>;   // rgb encoded normal, a coverage
@group(2) @binding(5) var l_emissive: texture_2d<f32>;  // linear HDR rgb, a coverage (channel order)
@group(2) @binding(6) var l_mask: texture_2d<f32>;
struct LayerParams {
    flags: vec4<u32>,       // kind (0 paint, 1 fill), has mask, generator id, invert
    blend: vec4<u32>,       // color, rough, metal, height
    blend2: vec4<u32>,      // normal
    opacity: vec4<f32>,     // color, rough, metal, height (layer x channel x enabled)
    opacity2: vec4<f32>,    // normal
    fill_color: vec4<f32>,  // linear
    fill_rmh: vec4<f32>,
    fill_normal: vec4<f32>,
    gen: vec4<f32>,         // amount, softness, noise scale, noise amount
    gen2: vec4<f32>,        // seed, AO influence, curvature weight
    fill_emissive: vec4<f32>, // linear rgb x strength
};
@group(2) @binding(7) var<uniform> lp: LayerParams;

struct Acc {
    @location(0) color: vec4<f32>,
    @location(1) rmh: vec4<f32>,
    @location(2) normal: vec4<f32>,
    @location(3) emissive: vec4<f32>,
};

// Ridged fbm: 1 at the noise's zero crossings, falling off around them.
fn ridged(p: vec3<f32>) -> f32 {
    return 1.0 - abs(fbm(p) * 2.0 - 1.0);
}

fn generator(t: vec2<i32>) -> f32 {
    let bk = textureLoad(bakes, t, 0);
    let ao = bk.r;
    let curv = bk.g;
    let pw = textureLoad(position, t, 0).xyz;                 // world, metres
    let p = (pw - sh.center_radius.xyz) / max(sh.center_radius.w, 1e-6);  // object-relative
    let seed = vec3<f32>(lp.gen2.x * 7.31, lp.gen2.x * 3.17, lp.gen2.x * 5.53);
    let s = lp.gen.z;
    let n = fbm(p * s + seed);
    let threshold = 1.0 - lp.gen.x;
    let soft = max(lp.gen.y, 0.003);
    let occl = 1.0 - ao;
    var v = 0.0;
    switch lp.flags.z {
        case 1u: {
            // edge wear: convex curvature, broken up by noise, kept out of occluded areas
            let convex = clamp((curv - 0.5) * 2.0, 0.0, 1.0);
            v = convex * lp.gen2.z + (n - 0.5) * lp.gen.w - occl * lp.gen2.y;
        }
        case 2u: {
            // dirt: occluded and concave areas
            let cavity = clamp((0.5 - curv) * 2.0, 0.0, 1.0);
            v = max(occl * lp.gen2.y, cavity * lp.gen2.z) + (n - 0.5) * lp.gen.w;
        }
        case 3u: {
            // grunge: two octaves of blotches, in world space
            v = fbm(pw * s + seed) * 0.65 + fbm(pw * s * 4.3 + seed.zxy) * 0.35 + occl * lp.gen2.y;
        }
        case 4u: {
            // streaks: noise stretched along world up, more under overhangs
            let q = vec3<f32>(pw.x * s, pw.y * s * 0.07, pw.z * s);
            v = fbm(q + seed) * 0.8 + fbm(q * 3.0 + seed.yzx) * 0.2 + occl * lp.gen2.y;
        }
        case 5u: {
            // hazard stripes: diagonal triangle wave in world space (amount = stripe width)
            let d = (pw.x + pw.y + pw.z) * s;
            v = abs(fract(d) - 0.5) * 2.0 + (fbm(pw * 8.0 + seed) - 0.5) * lp.gen.w * 0.3;
        }
        case 6u: {
            // spots: domain-warped blobs
            let w = pw * s + vec3<f32>(fbm(pw * s * 0.7 + seed), fbm(pw * s * 0.7 + seed.yzx), fbm(pw * s * 0.7 + seed.zxy)) * 2.0;
            v = smoothstep(0.35, 0.75, fbm(w + seed * 1.3)) + occl * lp.gen2.y;
        }
        case 7u: {
            // scratches: sharp ridges of strongly stretched noise, two directions
            let a = ridged(vec3<f32>(pw.x * s, pw.y * s * 9.0, pw.z * s) + seed);
            let b = ridged(vec3<f32>(pw.x * s * 9.0, pw.y * s, pw.z * s * 9.0) + seed.zyx);
            v = pow(max(a, b), 10.0) * smoothstep(0.35, 0.6, fbm(pw * s * 0.5 + seed));
        }
        case 8u: {
            // panel lines: distance to a world grid, measured on the two axes
            // that lie in the surface (the axis along the normal is skipped)
            let nrm = abs(normalize(textureLoad(wnormal, t, 0).xyz));
            let g = fract(pw * s);
            let dist = min(g, vec3<f32>(1.0) - g);
            var dmin = 1.0;
            if (nrm.x < 0.75) { dmin = min(dmin, dist.x); }
            if (nrm.y < 0.75) { dmin = min(dmin, dist.y); }
            if (nrm.z < 0.75) { dmin = min(dmin, dist.z); }
            v = 1.0 - dmin * 2.0;
        }
        default: {}
    }
    if (lp.flags.z >= 3u && lp.flags.z != 5u) {
        v += (n - 0.5) * lp.gen.w;
    }
    return smoothstep(threshold - soft, threshold + soft, v);
}

@fragment
fn fs_layer(f: FullOut) -> Acc {
    let t = vec2<i32>(f.pos.xy);
    let dc = textureLoad(acc_color, t, 0);
    let dr = textureLoad(acc_rmh, t, 0);
    let dn = textureLoad(acc_normal, t, 0).xyz;
    let de = textureLoad(acc_emissive, t, 0).rgb;

    var e = vec4<f32>(lp.fill_emissive.rgb, 1.0);
    var c = vec4<f32>(lp.fill_color.rgb, 1.0);
    var r = vec2<f32>(lp.fill_rmh.x, 1.0);
    var m = vec2<f32>(lp.fill_rmh.y, 1.0);
    var h = vec2<f32>(lp.fill_rmh.z, 1.0);
    var n = vec4<f32>(lp.fill_normal.xyz, 1.0);
    if (lp.flags.x == 0u) {
        c = textureLoad(l_color, t, 0);
        r = textureLoad(l_rough, t, 0).rg;
        m = textureLoad(l_metal, t, 0).rg;
        h = textureLoad(l_height, t, 0).rg;
        let ln = textureLoad(l_normal, t, 0);
        n = vec4<f32>(normalize(ln.xyz * 2.0 - 1.0 + vec3<f32>(0.0, 0.0, 1e-4)), ln.a);
        e = textureLoad(l_emissive, t, 0);
    }

    var mask = 1.0;
    if (lp.flags.y == 1u) {
        mask = textureLoad(l_mask, t, 0).r;
        if (lp.flags.z != 0u) { mask *= generator(t); }
        if (lp.flags.w == 1u) { mask = 1.0 - mask; }
    }

    // Replace ignores the layer's own coverage.
    let cov = vec4<f32>(
        select(c.a, 1.0, lp.blend.x == 8u),
        select(r.y, 1.0, lp.blend.y == 8u),
        select(m.y, 1.0, lp.blend.z == 8u),
        select(h.y, 1.0, lp.blend.w == 8u));
    let a = cov * lp.opacity * mask;
    let an = n.a * lp.opacity2.x * mask;
    let ae = select(e.a, 1.0, lp.blend2.y == 8u) * lp.opacity2.y * mask;

    var o: Acc;
    o.color = vec4<f32>(max(blend_rgb(lp.blend.x, dc.rgb, c.rgb, a.x), vec3<f32>(0.0)), 1.0);
    o.rmh = vec4<f32>(
        clamp(blend_scalar(lp.blend.y, dr.x, r.x, a.y), 0.0, 1.0),
        clamp(blend_scalar(lp.blend.z, dr.y, m.x, a.z), 0.0, 1.0),
        // height is HDR (stacked dents can pass -1); clamped only on export
        clamp(blend_scalar(lp.blend.w, dr.z, h.x, a.w), -8.0, 8.0),
        1.0);
    o.normal = vec4<f32>(blend_normal(lp.blend2.x, dn, n.xyz, an), 1.0);
    o.emissive = vec4<f32>(max(blend_rgb(lp.blend2.y, de, e.rgb, ae), vec3<f32>(0.0)), 1.0);
    return o;
}

// Defaults under the bottom layer.
@fragment
fn fs_clear(f: FullOut) -> Acc {
    var o: Acc;
    o.color = vec4<f32>(srgb_to_linear(vec3<f32>(0.5)), 1.0);
    o.rmh = vec4<f32>(0.5, 0.0, 0.0, 1.0);
    o.normal = vec4<f32>(0.0, 0.0, 1.0, 1.0);
    o.emissive = vec4<f32>(0.0, 0.0, 0.0, 1.0);
    return o;
}

// ---------- finalize ----------
// Reads the composited stack through the jump-flood map: texels outside every
// UV island take the value of the nearest island texel (seam padding, so
// bilinear filtering and mips never pull in background). Height is turned
// into a normal with central differences whose neighbours are also looked up
// through the padding map, then combined with painted normal detail (RNM).

struct Material {
    @location(0) color: vec4<f32>,   // srgb target
    @location(1) orm: vec4<f32>,     // ao, roughness, metallic, coverage
    @location(2) normal: vec4<f32>,  // encoded tangent-space normal
    @location(3) height: vec4<f32>,  // r = height
};

fn src_texel(t: vec2<i32>) -> vec2<i32> {
    let s = textureLoad(nearest, t, 0).xy;
    if (s.x == 65535u) { return t; }
    return vec2<i32>(s);
}

fn height_at(t: vec2<i32>) -> f32 {
    let size = i32(sh.res.x);
    let c = clamp(t, vec2<i32>(0), vec2<i32>(size - 1));
    return textureLoad(acc_rmh, src_texel(c), 0).z;
}

// Is texel t inside a UV island (rather than padding)?
fn covered(t: vec2<i32>) -> bool {
    let size = i32(sh.res.x);
    if (any(t < vec2<i32>(0)) || any(t >= vec2<i32>(size))) { return false; }
    let s = textureLoad(nearest, t, 0).xy;
    return s.x != 65535u && all(vec2<i32>(s) == t);
}

// Height slope along `d`, central where both neighbours are on the island,
// one-sided at island borders. Using padded values across a border would
// read as a flat slope and draw a visible line along every UV seam.
fn slope(s: vec2<i32>, d: vec2<i32>) -> f32 {
    let p = covered(s + d);
    let m = covered(s - d);
    let h = height_at(s);
    if (p && m) { return height_at(s + d) - height_at(s - d); }
    if (p) { return 2.0 * (height_at(s + d) - h); }
    if (m) { return 2.0 * (h - height_at(s - d)); }
    return 0.0;
}

@fragment
fn fs_finalize(f: FullOut) -> Material {
    let t = vec2<i32>(f.pos.xy);
    let s = src_texel(t);
    let c = textureLoad(acc_color, s, 0);
    let rmh = textureLoad(acc_rmh, s, 0);
    let detail = textureLoad(acc_normal, s, 0).xyz;
    let ao = textureLoad(bakes, s, 0).r;

    // central differences in texel space; texel rows go down (+v)
    let k = sh.res.y;
    let hx = slope(s, vec2<i32>(1, 0));
    let hy = slope(s, vec2<i32>(0, 1));
    // OpenGL convention: +y points up the image, i.e. towards -v
    let hn = normalize(vec3<f32>(-hx * k, hy * k, 1.0));
    let nrm = rnm(hn, detail);

    var o: Material;
    o.color = vec4<f32>(c.rgb, 1.0);
    o.orm = vec4<f32>(ao, rmh.x, rmh.y, 1.0);
    o.normal = vec4<f32>(nrm * 0.5 + 0.5, 1.0);
    o.height = vec4<f32>(rmh.z, 0.0, 0.0, 1.0);
    return o;
}

// Emission, seam padded like the rest of the material.
@fragment
fn fs_finalize_emissive(f: FullOut) -> @location(0) vec4<f32> {
    let s = src_texel(vec2<i32>(f.pos.xy));
    return vec4<f32>(textureLoad(acc_emissive, s, 0).rgb, 1.0);
}
