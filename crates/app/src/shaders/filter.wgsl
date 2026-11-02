// Filters, mask evaluation and anchor capture (pigment_core::filters).
// Appended to common.wgsl + composite.wgsl (+ gen_weather, gen_ground): it
// reuses the shared mesh data (group 0), the accumulation inputs (group 1,
// acc_*), the layer bindings (group 2) for mask evaluation, and src_texel.
//
// Filter passes:
//   group 1 (acc_*)   the image being filtered (for masks: binding 0 only)
//   group 2           fp (params, binding 20), gate (binding 21)
//   group 3 (orig_*)  the filter's input, for gating / unchanged channels
//
// Every neighbourhood tap goes through the jump-flood padding map: a tap
// that leaves a UV island reads the island's nearest texel, never the
// background, so filters don't open seams (same as the curvature blur).

struct FilterParams {
    kind: vec4<u32>,      // x kind (FilterKind::gpu_id), y channel bits, z pass index, w flags (1 gate texture, 2 mask mode, 4 last pass: gate + keep unselected channels)
    a: vec4<f32>,         // radius (texels at this resolution), amount, angle (radians), noise scale (per metre)
    b: vec4<f32>,         // seed, hue shift (turns), saturation, lightness
    c: vec4<f32>,         // clamp min, max, use height (1), gate multiplier (opacity)
    in_black: vec4<f32>,  // levels per channel: r, g, b, master
    in_white: vec4<f32>,
    gamma: vec4<f32>,
    out_black: vec4<f32>,
    out_white: vec4<f32>,
    shadows: vec4<f32>,   // colour balance rgb
    midtones: vec4<f32>,
    highlights: vec4<f32>,
};
@group(2) @binding(20) var<uniform> fp: FilterParams;
@group(2) @binding(21) var gate_tex: texture_2d<f32>;

@group(3) @binding(0) var orig_color: texture_2d<f32>;
@group(3) @binding(1) var orig_rmh: texture_2d<f32>;
@group(3) @binding(2) var orig_normal: texture_2d<f32>;
@group(3) @binding(3) var orig_emissive: texture_2d<f32>;

struct Px {
    c: vec4<f32>,  // colour rgb, opacity
    r: vec4<f32>,  // roughness, metallic, height, transmission
    n: vec4<f32>,  // packed normal xy, coat, flake
    e: vec4<f32>,  // emission rgb, coat roughness
};

fn mask_mode() -> bool { return (fp.kind.w & 2u) != 0u; }

fn px_add(a: Px, b: Px) -> Px { return Px(a.c + b.c, a.r + b.r, a.n + b.n, a.e + b.e); }
fn px_mul(a: Px, k: f32) -> Px { return Px(a.c * k, a.r * k, a.n * k, a.e * k); }
fn px_zero() -> Px { return Px(vec4<f32>(0.0), vec4<f32>(0.0), vec4<f32>(0.0), vec4<f32>(0.0)); }
fn px_max(a: Px, b: Px) -> Px { return Px(max(a.c, b.c), max(a.r, b.r), max(a.n, b.n), max(a.e, b.e)); }
fn px_min(a: Px, b: Px) -> Px { return Px(min(a.c, b.c), min(a.r, b.r), min(a.n, b.n), min(a.e, b.e)); }
fn px_abs(a: Px) -> Px { return Px(abs(a.c), abs(a.r), abs(a.n), abs(a.e)); }

// Seam-aware tap of the image being filtered.
fn tap(t: vec2<i32>) -> Px {
    let size = i32(sh.res.x);
    let s = src_texel(clamp(twrap(t), vec2<i32>(0), vec2<i32>(size - 1)));
    if (mask_mode()) {
        let m = textureLoad(acc_color, s, 0).r;
        return Px(vec4<f32>(m), vec4<f32>(0.0), vec4<f32>(0.0), vec4<f32>(0.0));
    }
    return Px(textureLoad(acc_color, s, 0), textureLoad(acc_rmh, s, 0), textureLoad(acc_normal, s, 0), textureLoad(acc_emissive, s, 0));
}

fn tapf(t: vec2<f32>) -> Px {
    return tap(vec2<i32>(round(t)));
}

// World position at a texel (through the padding map), for noise.
fn world_at(t: vec2<i32>) -> vec3<f32> {
    let size = i32(sh.res.x);
    return textureLoad(position, src_texel(clamp(t, vec2<i32>(0), vec2<i32>(size - 1))), 0).xyz;
}

fn fnoise(t: vec2<i32>, salt: f32) -> f32 {
    let seed = vec3<f32>(fp.b.x * 7.31 + salt, fp.b.x * 3.17 - salt, fp.b.x * 5.53 + salt * 0.5);
    let pw = world_at(t);
    let s = fp.a.w;
    return fbm_s(pw * s + seed, pw, vec3<f32>(s), seed);
}

// Taps along one axis: n taps each side spread over the radius.
fn tap_count(r: f32) -> i32 { return clamp(i32(ceil(r)), 1, 32); }

// Gaussian blur along `d` (one separable pass).
fn blur1(t: vec2<i32>, d: vec2<f32>, r: f32) -> Px {
    let n = tap_count(r);
    let stp = r / f32(n);
    let sigma = max(r * 0.5, 0.5);
    var sum = px_zero();
    var w = 0.0;
    for (var k = -n; k <= n; k++) {
        let x = f32(k) * stp;
        let g = exp(-x * x / (2.0 * sigma * sigma));
        sum = px_add(sum, px_mul(tapf(vec2<f32>(t) + d * x), g));
        w += g;
    }
    return px_mul(sum, 1.0 / w);
}

// Max (grow) or min (shrink) along `d`.
fn morph1(t: vec2<i32>, d: vec2<f32>, r: f32, grow: bool) -> Px {
    let n = tap_count(r);
    let stp = r / f32(n);
    var acc = tap(t);
    for (var k = -n; k <= n; k++) {
        let p = tapf(vec2<f32>(t) + d * f32(k) * stp);
        if (grow) { acc = px_max(acc, p); } else { acc = px_min(acc, p); }
    }
    return acc;
}

// Average of 8 taps on a ring of radius r.
fn ring(t: vec2<i32>, r: f32) -> Px {
    var sum = px_zero();
    for (var k = 0; k < 8; k++) {
        let a = f32(k) * 0.7853982;
        sum = px_add(sum, tapf(vec2<f32>(t) + vec2<f32>(cos(a), sin(a)) * r));
    }
    return px_mul(sum, 0.125);
}

fn levels1(v: f32, k: i32) -> f32 {
    let ib = fp.in_black[k];
    let iw = fp.in_white[k];
    let x = clamp((v - ib) / max(iw - ib, 1e-4), 0.0, 1.0);
    let g = pow(x, 1.0 / max(fp.gamma[k], 1e-3));
    return mix(fp.out_black[k], fp.out_white[k], g);
}
// Per channel k (0..2), then the master levels.
fn levels(v: f32, k: i32) -> f32 {
    return levels1(levels1(v, k), 3);
}

fn linear_to_srgb1(c: vec3<f32>) -> vec3<f32> {
    let lo = c * 12.92;
    let hi = 1.055 * pow(max(c, vec3<f32>(0.0)), vec3<f32>(1.0 / 2.4)) - 0.055;
    return select(hi, lo, c <= vec3<f32>(0.0031308));
}

fn rgb_to_hsl(c: vec3<f32>) -> vec3<f32> {
    let mx = max(max(c.r, c.g), c.b);
    let mn = min(min(c.r, c.g), c.b);
    let l = (mx + mn) * 0.5;
    let d = mx - mn;
    if (d < 1e-6) { return vec3<f32>(0.0, 0.0, l); }
    let s = d / max(1.0 - abs(2.0 * l - 1.0), 1e-6);
    var h = 0.0;
    if (mx == c.r) { h = (c.g - c.b) / d + select(0.0, 6.0, c.g < c.b); }
    else if (mx == c.g) { h = (c.b - c.r) / d + 2.0; }
    else { h = (c.r - c.g) / d + 4.0; }
    return vec3<f32>(h / 6.0, s, l);
}
fn hsl_to_rgb(h: vec3<f32>) -> vec3<f32> {
    let k = (vec3<f32>(0.0, 8.0, 4.0) + h.x * 12.0) % vec3<f32>(12.0);
    let a = h.y * min(h.z, 1.0 - h.z);
    return h.z - a * clamp(min(k - 3.0, 9.0 - k), vec3<f32>(-1.0), vec3<f32>(1.0));
}

// Point operations on one pixel.
fn point_op(kind: u32, p: Px, t: vec2<i32>) -> Px {
    var o = p;
    switch kind {
        case 1u: {
            // levels: colour per channel + master; scalars use the master;
            // height is remapped -1..1 <-> 0..1 around it
            if (mask_mode()) {
                o.c = vec4<f32>(levels(p.c.r, 0));
            } else {
                let s = clamp(linear_to_srgb1(p.c.rgb), vec3<f32>(0.0), vec3<f32>(1.0));
                o.c = vec4<f32>(srgb_to_linear(vec3<f32>(levels(s.r, 0), levels(s.g, 1), levels(s.b, 2))), p.c.a);
            }
            o.r = vec4<f32>(levels1(p.r.x, 3), levels1(p.r.y, 3), levels1(p.r.z * 0.5 + 0.5, 3) * 2.0 - 1.0, p.r.w);
            o.e = vec4<f32>(p.e.rgb * levels1(1.0, 3), p.e.w);
        }
        case 2u: {
            // hue / saturation / lightness, in sRGB
            var h = rgb_to_hsl(clamp(linear_to_srgb1(p.c.rgb), vec3<f32>(0.0), vec3<f32>(1.0)));
            h.x = fract(h.x + fp.b.y);
            h.y = clamp(h.y * (1.0 + fp.b.z), 0.0, 1.0);
            h.z = clamp(h.z + fp.b.w * select(h.z, 1.0 - h.z, fp.b.w > 0.0), 0.0, 1.0);
            o.c = vec4<f32>(srgb_to_linear(hsl_to_rgb(h)), p.c.a);
        }
        case 3u: {
            // colour balance: shadows / midtones / highlights weighted by luminance
            let s = linear_to_srgb1(p.c.rgb);
            let l = dot(s, vec3<f32>(0.2126, 0.7152, 0.0722));
            let ws = 1.0 - smoothstep(0.0, 0.5, l);
            let wh = smoothstep(0.5, 1.0, l);
            let wm = max(1.0 - ws - wh, 0.0);
            let shifted = s + (fp.shadows.rgb * ws + fp.midtones.rgb * wm + fp.highlights.rgb * wh) * 0.5;
            o.c = vec4<f32>(srgb_to_linear(clamp(shifted, vec3<f32>(0.0), vec3<f32>(1.0))), p.c.a);
        }
        case 4u: {
            // invert
            if (mask_mode()) {
                o.c = vec4<f32>(1.0 - p.c.r);
            } else {
                o.c = vec4<f32>(srgb_to_linear(1.0 - linear_to_srgb1(p.c.rgb)), p.c.a);
            }
            o.r = vec4<f32>(1.0 - p.r.x, 1.0 - p.r.y, -p.r.z, p.r.w);
            o.n = vec4<f32>(-p.n.xy, p.n.zw);
        }
        case 5u: {
            // clamp
            let lo = fp.c.x;
            let hi = fp.c.y;
            o.c = vec4<f32>(clamp(p.c.rgb, vec3<f32>(lo), vec3<f32>(hi)), p.c.a);
            o.r = vec4<f32>(clamp(p.r.x, lo, hi), clamp(p.r.y, lo, hi), clamp(p.r.z, lo * 2.0 - 1.0, hi * 2.0 - 1.0), p.r.w);
            o.e = vec4<f32>(clamp(p.e.rgb, vec3<f32>(lo), vec3<f32>(hi * 64.0)), p.e.w);
        }
        case 16u: {
            // noise overlay ("MatFinish"): world-space value noise
            let n = (fnoise(t, 0.0) - 0.5) * 2.0 * fp.a.y;
            o.c = vec4<f32>(max(p.c.rgb * (1.0 + n), vec3<f32>(0.0)), p.c.a);
            if (mask_mode()) { o.c = vec4<f32>(clamp(p.c.r + n, 0.0, 1.0)); }
            o.r = vec4<f32>(clamp(p.r.x + n, 0.0, 1.0), clamp(p.r.y + n, 0.0, 1.0), p.r.z + n * 0.5, p.r.w);
            o.e = vec4<f32>(max(p.e.rgb * (1.0 + n), vec3<f32>(0.0)), p.e.w);
        }
        default: {}
    }
    return o;
}

// The filter's result at t (one pass of it).
fn filter_px(t: vec2<i32>) -> Px {
    let kind = fp.kind.x;
    let pass_i = fp.kind.z;
    let r = max(fp.a.x, 0.0);
    let hv = select(vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0), (pass_i % 2u) == 1u);
    switch kind {
        case 6u: { return blur1(t, hv, r); }
        case 7u: { return blur1(t, vec2<f32>(cos(fp.a.z), sin(fp.a.z)), r); }
        case 8u: {
            // sharpen: x + amount * (x - local average)
            let x = tap(t);
            let avg = ring(t, max(r, 1.0));
            return px_add(x, px_mul(px_add(x, px_mul(avg, -1.0)), fp.a.y));
        }
        case 9u: {
            // warp: displace by world-space noise (radius = max distance)
            let d = vec2<f32>(fnoise(t, 0.0) - 0.5, fnoise(t, 17.3) - 0.5) * 2.0 * r * max(fp.a.y, 0.0) * 2.0;
            return tapf(vec2<f32>(t) + d);
        }
        case 10u: {
            // slope blur: walk down the slope of a noise (or the stack's height) field and average
            var g = vec2<f32>(0.0);
            if (fp.c.z > 0.5 && !mask_mode()) {
                g = vec2<f32>(tap(t + vec2<i32>(2, 0)).r.z - tap(t - vec2<i32>(2, 0)).r.z, tap(t + vec2<i32>(0, 2)).r.z - tap(t - vec2<i32>(0, 2)).r.z);
            } else {
                g = vec2<f32>(fnoise(t + vec2<i32>(2, 0), 0.0) - fnoise(t - vec2<i32>(2, 0), 0.0), fnoise(t + vec2<i32>(0, 2), 0.0) - fnoise(t - vec2<i32>(0, 2), 0.0));
            }
            let len = length(g);
            if (len < 1e-6) { return tap(t); }
            let d = -g / len;
            let dist = r * max(fp.a.y, 0.0) * 2.0;
            var sum = px_zero();
            for (var k = 0; k <= 12; k++) {
                sum = px_add(sum, tapf(vec2<f32>(t) + d * dist * f32(k) / 12.0));
            }
            return px_mul(sum, 1.0 / 13.0);
        }
        case 11u: {
            // edge detect: Sobel magnitude per component, times the gain
            let s = max(r, 1.0);
            let tl = tapf(vec2<f32>(t) + vec2<f32>(-s, -s));
            let tc = tapf(vec2<f32>(t) + vec2<f32>(0.0, -s));
            let tr = tapf(vec2<f32>(t) + vec2<f32>(s, -s));
            let ml = tapf(vec2<f32>(t) + vec2<f32>(-s, 0.0));
            let mr = tapf(vec2<f32>(t) + vec2<f32>(s, 0.0));
            let bl = tapf(vec2<f32>(t) + vec2<f32>(-s, s));
            let bc = tapf(vec2<f32>(t) + vec2<f32>(0.0, s));
            let br = tapf(vec2<f32>(t) + vec2<f32>(s, s));
            let gx = px_add(px_add(tr, px_add(px_mul(mr, 2.0), br)), px_mul(px_add(tl, px_add(px_mul(ml, 2.0), bl)), -1.0));
            let gy = px_add(px_add(bl, px_add(px_mul(bc, 2.0), br)), px_mul(px_add(tl, px_add(px_mul(tc, 2.0), tr)), -1.0));
            let m = px_mul(px_add(px_abs(gx), px_abs(gy)), fp.a.y * 0.25);
            let x = tap(t);
            return Px(vec4<f32>(min(m.c.rgb, vec3<f32>(1.0)), x.c.a), vec4<f32>(min(m.r.xy, vec2<f32>(1.0)), m.r.z, x.r.w), x.n, vec4<f32>(m.e.rgb, x.e.w));
        }
        case 12u: {
            // height to normal: the height's slope as normal detail (RNM onto the painted detail)
            var x = tap(t);
            let hx = tap(t + vec2<i32>(1, 0)).r.z - tap(t - vec2<i32>(1, 0)).r.z;
            let hy = tap(t + vec2<i32>(0, 1)).r.z - tap(t - vec2<i32>(0, 1)).r.z;
            let k = sh.res.y * fp.a.y;
            let hn = normalize(vec3<f32>(-hx * k, hy * k, 1.0));
            let n = rnm(hn, acc_n(x.n));
            x.n = vec4<f32>(pack_n(n, x.n.z, x.n.w).xy, x.n.zw);
            if (fp.c.z < 0.5) { x.r.z = 0.0; }  // converted: the height itself goes flat
            return x;
        }
        case 13u: {
            // fill holes: grow (passes 0, 1) then shrink (2, 3)
            return morph1(t, hv, r, pass_i < 2u);
        }
        case 14u: { return morph1(t, hv, r, true); }
        case 15u: { return morph1(t, hv, r, false); }
        default: {}
    }
    return point_op(kind, tap(t), t);
}

fn bitf(bit: u32) -> f32 { return select(0.0, 1.0, (fp.kind.y & bit) != 0u); }

// Which pixel components the filter may change (layer filters): colour rgb,
// roughness, metallic, height, normal xy, emission rgb. Opacity,
// transmission, coat and flake are never touched.
fn channel_mask() -> Px {
    let c = bitf(1u);
    let e = bitf(32u);
    let n = bitf(16u);
    return Px(vec4<f32>(c, c, c, 0.0), vec4<f32>(bitf(2u), bitf(4u), bitf(8u), 0.0), vec4<f32>(n, n, 0.0, 0.0), vec4<f32>(e, e, e, 0.0));
}

@fragment
fn fs_filter_acc(f: FullOut) -> Acc {
    let t = vec2<i32>(f.pos.xy);
    let x = filter_px(t);
    var o: Acc;
    // intermediate passes of separable filters pass everything through
    if ((fp.kind.w & 4u) == 0u) {
        o.color = x.c;
        o.rmh = x.r;
        o.normal = x.n;
        o.emissive = x.e;
        return o;
    }
    var g = fp.c.w;
    if ((fp.kind.w & 1u) != 0u) { g *= textureLoad(gate_tex, t, 0).r; }
    let m = channel_mask();
    let oc = textureLoad(orig_color, t, 0);
    let orr = textureLoad(orig_rmh, t, 0);
    let on = textureLoad(orig_normal, t, 0);
    let oe = textureLoad(orig_emissive, t, 0);
    o.color = mix(oc, vec4<f32>(max(x.c.rgb, vec3<f32>(0.0)), x.c.a), m.c * g);
    o.rmh = mix(orr, vec4<f32>(clamp(x.r.xy, vec2<f32>(0.0), vec2<f32>(1.0)), clamp(x.r.z, -8.0, 8.0), x.r.w), m.r * g);
    // the normal is re-packed so it stays a unit vector
    let nn = mix(on, x.n, m.n * g);
    o.normal = vec4<f32>(pack_n(acc_n(nn), on.z, on.w).xy, on.zw);
    o.emissive = mix(oe, vec4<f32>(max(x.e.rgb, vec3<f32>(0.0)), x.e.w), m.e * g);
    return o;
}

@fragment
fn fs_filter_mask(f: FullOut) -> @location(0) vec4<f32> {
    let t = vec2<i32>(f.pos.xy);
    let x = filter_px(t);
    return vec4<f32>(clamp(x.c.r, 0.0, 1.0), 0.0, 0.0, 1.0);
}

// A layer's mask, evaluated once (painted x generator x parts x invert), so
// mask filters can read its neighbourhood.
@fragment
fn fs_mask_eval(f: FullOut) -> @location(0) vec4<f32> {
    return vec4<f32>(eval_mask(vec2<i32>(f.pos.xy)), 0.0, 0.0, 1.0);
}

// Anchor capture: the stack right after the anchor layer (group 1) plus the
// anchor layer's mask x coverage x opacity.
@fragment
fn fs_anchor(f: FullOut) -> @location(0) vec4<f32> {
    let t = vec2<i32>(f.pos.xy);
    var cov = 1.0;
    if (lp.flags.x == 0u) {
        cov = max(textureLoad(l_color, t, 0).a, textureLoad(l_height, t, 0).g);
    }
    let alpha = clamp(eval_mask(t) * cov * max(lp.opacity.x, lp.opacity.w), 0.0, 1.0);
    let c = textureLoad(acc_color, t, 0).rgb;
    let lum = dot(linear_to_srgb1(max(c, vec3<f32>(0.0))), vec3<f32>(0.2126, 0.7152, 0.0722));
    return vec4<f32>(textureLoad(acc_rmh, t, 0).z, alpha, lum, 1.0);
}
