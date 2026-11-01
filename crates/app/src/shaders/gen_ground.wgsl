// Natural-ground generators (ids 15..19), appended after gen_weather.wgsl:
//   15 cells     Voronoi: F1 domes, F2, F2 - F1 edges, a value per cell, bevelled plates
//   16 scatter   bombing: pebbles, flakes, leaves, twigs / needles, shells (rounded heights)
//   17 rock      domain-warped ridged rock, strata ledges, block-joint cracks, downhill streaks
//   18 blades    a dense grass-blade field: clumps, random lean, tips
//   19 ripples   wind ripples with curving, splitting and fading crests
//
// Every pattern lives on the in-surface plane of wx_surface (floors: x, z;
// walls: horizontal, y), in metres. In tile mode each frequency is snapped
// per axis so a whole number of cells fits the tile period and cell ids
// wrap, so the patterns are periodic and the tiles stay seamless.
//
// Slots: gp = amount, softness, scale, breakup; gp2 = seed, ao_influence
// slot, curvature_weight slot, variant; gp3 = Generator::extra.
//
// Besides the mask, each generator leaves two side channels for fs_layer
// (captured from the main generator in `generator()`):
//   g_prof  the raw height profile, 0..1 (a dome per pebble, a blade's rise)
//   g_inst  a random value per instance (cell, stone, blade, rock block)

var<private> g_prof: f32 = -1.0;
var<private> g_inst: f32 = 0.5;
var<private> l_prof: f32 = 1.0;
var<private> l_inst: f32 = 0.5;

struct GnFrame {
    p: vec2<f32>,    // in-surface position, metres
    tp: vec2<f32>,   // tile period along p (metres; 0 = no wrap)
    face: f32,
};

fn gn_frame(t: vec2<i32>) -> GnFrame {
    let pw = textureLoad(position, t, 0).xyz;
    let n = normalize(textureLoad(wnormal, t, 0).xyz + vec3<f32>(0.0, 1e-5, 0.0));
    let sf = wx_surface(pw, n);
    var o: GnFrame;
    o.p = sf.xy;
    o.tp = tile_plane_period(n);
    o.face = sf.z;
    return o;
}

// A frequency (per metre, per axis) snapped to whole cycles per tile period.
fn gn_k(f: vec2<f32>, tp: vec2<f32>) -> vec2<f32> {
    var k = abs(f);
    if (tp.x > 0.0) { k.x = max(round(k.x * tp.x), 1.0) / tp.x; }
    if (tp.y > 0.0) { k.y = max(round(k.y * tp.y), 1.0) / tp.y; }
    return k;
}
// Same, but keeps the sign and allows 0 (wave vectors).
fn gn_kv(f: vec2<f32>, tp: vec2<f32>) -> vec2<f32> {
    var k = f;
    if (tp.x > 0.0) { k.x = round(f.x * tp.x) / tp.x; }
    if (tp.y > 0.0) { k.y = round(f.y * tp.y) / tp.y; }
    return k;
}
// Lattice period in cells for a snapped frequency (0 = no wrap).
fn gn_per(k: vec2<f32>, tp: vec2<f32>) -> vec2<f32> {
    return round(k * tp);
}
fn gn_wrap(c: vec2<f32>, per: vec2<f32>) -> vec2<f32> {
    let m = c - per * floor(c / max(per, vec2<f32>(1.0)));
    return select(c, m, per > vec2<f32>(0.5));
}
fn gn_h(c: vec2<f32>, salt: f32) -> f32 {
    return wx_hash2(c, salt);
}
fn gn_h2(c: vec2<f32>, salt: f32) -> vec2<f32> {
    return vec2<f32>(wx_hash2(c, salt), wx_hash2(c + vec2<f32>(19.17, 47.3), salt + 0.61));
}

// Periodic 2D gradient noise, ~0..1.
fn gn_grad(c: vec2<f32>, per: vec2<f32>, salt: f32) -> vec2<f32> {
    let a = gn_h(gn_wrap(c, per), salt) * 6.2831853;
    return vec2<f32>(cos(a), sin(a));
}
fn gn_noise(p: vec2<f32>, per: vec2<f32>, salt: f32) -> f32 {
    let i = floor(p);
    let f = p - i;
    let u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    let a = dot(gn_grad(i, per, salt), f);
    let b = dot(gn_grad(i + vec2<f32>(1.0, 0.0), per, salt), f - vec2<f32>(1.0, 0.0));
    let c = dot(gn_grad(i + vec2<f32>(0.0, 1.0), per, salt), f - vec2<f32>(0.0, 1.0));
    let d = dot(gn_grad(i + vec2<f32>(1.0, 1.0), per, salt), f - vec2<f32>(1.0, 1.0));
    return clamp(mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 0.9 + 0.5, 0.0, 1.0);
}
// fbm at ~f features per metre, periodic over the tile.
fn gn_fbm(p: vec2<f32>, f: vec2<f32>, tp: vec2<f32>, oct: i32, salt: f32) -> f32 {
    var s = 0.0;
    var amp = 0.5;
    var norm = 0.0;
    var fr = f;
    for (var i = 0; i < oct; i++) {
        let k = gn_k(fr, tp);
        s += gn_noise(p * k, gn_per(k, tp), salt + f32(i) * 13.7) * amp;
        norm += amp;
        amp *= 0.5;
        fr *= 2.03;
    }
    return s / max(norm, 1e-6);
}
// Ridged multifractal: sharp crests, each octave weighted by the one below.
fn gn_ridged(p: vec2<f32>, f: vec2<f32>, tp: vec2<f32>, oct: i32, salt: f32) -> f32 {
    var s = 0.0;
    var amp = 0.5;
    var norm = 0.0;
    var w = 1.0;
    var fr = f;
    for (var i = 0; i < oct; i++) {
        let k = gn_k(fr, tp);
        var r = 1.0 - abs(gn_noise(p * k, gn_per(k, tp), salt + f32(i) * 7.9) * 2.0 - 1.0);
        r = r * r * w;
        w = clamp(r * 1.6, 0.0, 1.0);
        s += r * amp;
        norm += amp;
        amp *= 0.5;
        fr *= 2.03;
    }
    return s / max(norm, 1e-6);
}

// ---------------------------------------------------------------- Voronoi

struct GnVor {
    f1: f32,          // metres to the nearest point
    f2: f32,          // metres to the second nearest
    edge: f32,        // metres to the nearest cell border (exact bisector distance)
    id: vec2<f32>,    // wrapped cell id of the nearest point
};

// p in metres, k cells per metre (per axis, snapped), per = wrap period in cells.
fn gn_voronoi(p: vec2<f32>, k: vec2<f32>, per: vec2<f32>, rnd: f32, salt: f32) -> GnVor {
    let q = p * k;
    let ci = floor(q);
    let inv = 1.0 / k;
    var best = 1e9;
    var second = 1e9;
    var mr = vec2<f32>(0.0);
    var mc = ci;
    for (var j = -1; j <= 1; j++) {
        for (var i = -1; i <= 1; i++) {
            let c = ci + vec2<f32>(f32(i), f32(j));
            let pt = c + 0.5 + (gn_h2(gn_wrap(c, per), salt) - 0.5) * rnd;
            let r = (pt - q) * inv;
            let d = dot(r, r);
            if (d < best) {
                second = best;
                best = d;
                mr = r;
                mc = c;
            } else if (d < second) {
                second = d;
            }
        }
    }
    var ed = 1e9;
    for (var j = -2; j <= 2; j++) {
        for (var i = -2; i <= 2; i++) {
            let c = mc + vec2<f32>(f32(i), f32(j));
            let pt = c + 0.5 + (gn_h2(gn_wrap(c, per), salt) - 0.5) * rnd;
            let r = (pt - q) * inv;
            let dd = r - mr;
            if (dot(dd, dd) > 1e-12) {
                ed = min(ed, dot(0.5 * (mr + r), normalize(dd)));
            }
        }
    }
    var o: GnVor;
    o.f1 = sqrt(best);
    o.f2 = sqrt(second);
    o.edge = max(ed, 0.0);
    o.id = gn_wrap(mc, per);
    return o;
}

// cells: scale = cells per metre, ao slot = point randomness (0 grid .. 1),
// curvature slot = edge / bevel width (m), breakup = domain warp (cells),
// extra = (stretch along x, height variation per cell, edge noise).
// variant: 0 dome (1 - F1), 1 F2, 2 edges (1 on the borders), 3 value per
// cell, 4 plates (flat tops, rounded bevel to the borders).
fn gn_cells(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>, gp3: vec4<f32>) -> f32 {
    let fr = gn_frame(t);
    let salt = gp2.x * 1.37 + fr.face * 17.0;
    let s = max(gp.z, 0.01);
    let stretch = select(1.0, gp3.x, gp3.x > 0.0);
    let k = gn_k(vec2<f32>(s * stretch, s), fr.tp);
    let per = gn_per(k, fr.tp);
    let cell = 1.0 / s;
    var p = fr.p;
    // broad warp (breakup) bends the cell walls, fine noise roughens them
    if (gp.w > 0.0) {
        let w = vec2<f32>(gn_fbm(fr.p, vec2<f32>(s * 0.6), fr.tp, 3, salt + 1.0), gn_fbm(fr.p, vec2<f32>(s * 0.6), fr.tp, 3, salt + 2.0)) - 0.5;
        p += w * gp.w * cell * 1.5;
    }
    if (gp3.z > 0.0) {
        let w = vec2<f32>(gn_fbm(fr.p, vec2<f32>(s * 7.0), fr.tp, 3, salt + 3.0), gn_fbm(fr.p, vec2<f32>(s * 7.0), fr.tp, 3, salt + 4.0)) - 0.5;
        p += w * gp3.z * cell * 0.25;
    }
    let v = gn_voronoi(p, k, per, clamp(gp2.y, 0.0, 1.0), salt);
    let r = gn_h(v.id, salt + 7.0);
    g_inst = r;
    let ew = max(gp2.z, 1e-4);
    let hv = 1.0 - clamp(gp3.y, 0.0, 1.0) * gn_h(v.id, salt + 9.0);
    var o = 0.0;
    switch u32(gp2.w + 0.5) {
        case 1u: { o = clamp(v.f2 / (cell * 1.2), 0.0, 1.0); }
        case 2u: { o = 1.0 - smoothstep(0.0, ew, v.edge); }
        case 3u: { o = r; }
        case 4u: {
            let x = clamp(v.edge / ew, 0.0, 1.0);
            o = sqrt(max(1.0 - (1.0 - x) * (1.0 - x), 0.0)) * hv;
        }
        default: {
            let x = clamp(v.f1 / (cell * 0.75), 0.0, 1.0);
            o = (1.0 - x * x) * hv;
        }
    }
    g_prof = o;
    return wx_threshold(o, gp);
}

// ---------------------------------------------------------------- scatter

fn gn_outline(x: vec2<f32>, irr: f32, ph: f32) -> f32 {
    let a = atan2(x.y, x.x);
    let w = 0.5 * sin(2.0 * a + ph * 6.2831853) + 0.3 * sin(3.0 * a + ph * 17.0) + 0.2 * sin(5.0 * a + ph * 29.0);
    return 1.0 + irr * 0.4 * w;
}

// Height (0 outside, 0..1 inside) of one instance in its local frame `l`
// (cells; x along the long axis), radius r (cells), elongation e.
fn gn_shape(shape: u32, l: vec2<f32>, r: f32, e: f32, irr: f32, ph: f32) -> f32 {
    switch shape {
        case 1u: {
            // flake / flat stone: a plate with a rounded rim, tilted a little
            let x = l / vec2<f32>(r * e, r);
            let rr = dot(x, x) * gn_outline(x, irr, ph);
            if (rr >= 1.0) { return 0.0; }
            return clamp((0.38 + 0.12 * x.x * (ph - 0.5) * 2.0) * pow(1.0 - rr * rr, 0.35), 0.0, 1.0);
        }
        case 2u: {
            // leaf: pointed oval, curled edges, a midrib groove, veins, a stalk
            let len = r * e;
            let s = l.x / len;
            if (s < -1.0) {
                if (s > -1.3 && abs(l.y) < r * 0.07) { return 0.22; }
                return 0.0;
            }
            if (s >= 1.0) { return 0.0; }
            let serr = 1.0 + irr * 0.12 * sin(s * 23.0 + ph * 40.0);
            let hw = r * pow(max(1.0 - s * s, 0.0), 0.62) * (1.0 - 0.22 * s) * serr;
            let v = abs(l.y) / max(hw, 1e-5);
            if (v >= 1.0) { return 0.0; }
            let rib = 1.0 - smoothstep(0.0, 0.1, v);
            let vein = 1.0 - abs(fract(s * 3.5 + v * 1.8) * 2.0 - 1.0);
            return clamp(0.3 + 0.28 * v * v - 0.05 * rib + 0.04 * smoothstep(0.75, 1.0, vein) + 0.1 * (1.0 - s * s), 0.0, 1.0);
        }
        case 3u: {
            // twig / needle: a thin bent capsule with a round profile and bark bumps
            let len = r * e;
            let bend = (ph - 0.5) * 1.2;
            let y = l.y - bend * (l.x / len) * (l.x / len) * r * 1.5;
            let taper = 1.0 - 0.35 * clamp((l.x / len + 1.0) * 0.5, 0.0, 1.0);
            let rr = r * taper;
            let ax = clamp(l.x, -len + rr, len - rr);
            let d = length(vec2<f32>(l.x - ax, y)) / rr;
            if (d >= 1.0) { return 0.0; }
            return sqrt(1.0 - d * d) * (0.88 + 0.12 * sin(l.x / r * 2.7 + ph * 31.0));
        }
        case 4u: {
            // shell: a ribbed fan from its hinge
            let x = l / r;
            let h0 = x - vec2<f32>(-0.85, 0.0);
            let rad = length(h0);
            let a = atan2(h0.y, h0.x);
            let edge = 1.7 * (1.0 - 0.05 * abs(sin(a * 9.0)));
            if (abs(a) > 1.1 || rad > edge) { return 0.0; }
            let u = rad / edge;
            let dome = sqrt(max(1.0 - u * u, 0.0)) * (1.0 - pow(abs(a) / 1.1, 6.0));
            return clamp(0.55 * dome * (0.82 + 0.18 * cos(a * 18.0)) + 0.05, 0.0, 1.0);
        }
        case 5u: {
            // clover: three heart-shaped leaflets round a centre, a pale chevron on each
            let x = l / r;
            let rad = length(x);
            let a = atan2(x.y, x.x) + ph * 6.2831853;
            let lobe = abs(cos(1.5 * a));
            let notch = 1.0 - 0.28 * pow(max(cos(3.0 * a), 0.0), 24.0);
            let edge = (0.2 + 0.8 * pow(lobe, 0.6)) * notch;
            if (rad >= edge) { return 0.0; }
            let u = rad / edge;
            return clamp(0.42 + 0.18 * u * u - 0.06 * (1.0 - smoothstep(0.0, 0.08, abs(sin(1.5 * a)) * rad)), 0.0, 1.0);
        }
        case 6u: {
            // chip: an angular rock fragment, a convex polygon with a faceted top
            let x = l / vec2<f32>(r * e, r);
            var m = 0.0;
            for (var i = 0; i < 6; i++) {
                let fi = f32(i);
                let a = (fi + 0.5 * fract(ph * 7.3 + fi * 0.37)) * 1.0471976;
                let dist = 0.72 + 0.28 * fract(ph * 13.1 + fi * 0.61) - irr * 0.15 * fract(ph * 5.7 + fi * 0.29);
                m = max(m, dot(x, vec2<f32>(cos(a), sin(a))) / dist);
            }
            if (m >= 1.0) { return 0.0; }
            // a bevelled rim, then a top broken into tilted facets along a ridge
            let bevel = smoothstep(0.0, 0.28 + 0.25 * fract(ph * 3.1), 1.0 - m);
            let d1 = vec2<f32>(cos(ph * 9.0), sin(ph * 9.0));
            let d2 = vec2<f32>(-d1.y, d1.x);
            let top = 0.82 + 0.2 * dot(x, d1) * (fract(ph * 5.3) - 0.5) * 2.0 - 0.16 * abs(dot(x, d2) + 0.25 * (fract(ph * 2.7) - 0.5));
            return clamp(bevel * top, 0.0, 1.0);
        }
        default: {
            // pebble: an ellipsoid dome with an irregular outline
            let x = l / vec2<f32>(r * e, r);
            let rr = dot(x, x) * gn_outline(x, irr, ph);
            if (rr >= 1.0) { return 0.0; }
            return sqrt(1.0 - rr);
        }
    }
}

// scatter: amount = density (chance per slot), scale = cells per metre,
// breakup = size variation, ao slot = elongation, curvature slot = radius
// (fraction of a cell), extra = (instances per cell, alignment to x,
// outline irregularity, height variation). variant = shape: 0 pebble,
// 1 flake, 2 leaf, 3 twig / needle, 4 shell, 5 clover, 6 chip (angular). The mask is the covered area;
// g_prof the topmost instance's height.
fn gn_scatter(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>, gp3: vec4<f32>) -> f32 {
    let fr = gn_frame(t);
    let k = gn_k(vec2<f32>(max(gp.z, 0.01)), fr.tp);
    let per = gn_per(k, fr.tp);
    let q = fr.p * k;
    let ci = floor(q);
    let e = max(gp2.y, 1.0);
    let rad = max(gp2.z, 0.02);
    let shape = u32(gp2.w + 0.5);
    let reach = rad * e * select(1.25, 1.6, shape == 2u || shape == 4u || shape == 5u);
    let nr = i32(clamp(ceil(reach), 1.0, 3.0));
    let layers = i32(clamp(select(1.0, gp3.x, gp3.x > 0.0), 1.0, 8.0));
    let align = clamp(gp3.y, 0.0, 1.0);
    var best = 0.0;
    var inst = 0.5;
    for (var j = -nr; j <= nr; j++) {
        for (var i = -nr; i <= nr; i++) {
            let c = ci + vec2<f32>(f32(i), f32(j));
            let cw = gn_wrap(c, per);
            for (var s = 0; s < layers; s++) {
                let salt = gp2.x * 1.37 + f32(s) * 31.1;
                if (gn_h(cw, salt) > gp.x) { continue; }
                let ctr = c + gn_h2(cw, salt + 3.3);
                let r1 = gn_h2(cw, salt + 7.7);
                let r2 = gn_h2(cw, salt + 11.9);
                let size = rad * (1.0 - clamp(gp.w, 0.0, 1.0) * r1.x * 0.8);
                let ang = mix(r1.y * 6.2831853, (r1.y - 0.5) * 0.5, align);
                let d = q - ctr;
                if (dot(d, d) > (size * e * 1.7) * (size * e * 1.7) + 0.01) { continue; }
                let ca = cos(ang);
                let sa = sin(ang);
                let l = vec2<f32>(ca * d.x + sa * d.y, -sa * d.x + ca * d.y);
                let sh = gn_shape(shape, l, size, e, gp3.z, r2.y);
                if (sh <= 0.0) { continue; }
                let hgt = sh * (1.0 - clamp(gp3.w, 0.0, 1.0) * r2.x * 0.7);
                if (hgt > best) {
                    best = hgt;
                    inst = gn_h(cw, salt + 23.1);
                }
            }
        }
    }
    g_prof = best;
    g_inst = inst;
    return smoothstep(0.0, max(gp.y, 0.003), best);
}

// ---------------------------------------------------------------- rock

// rock: scale = rock features per metre, breakup = domain warp, ao slot =
// strata strength, curvature slot = crack strength, extra = (strata bands
// per metre along the surface's v / up axis, downhill streaks, crack cells
// per metre). variant: 0 height, 1 cracks, 2 ledges (up-facing shelves of
// the strata, where lichen and debris settle), 3 streaks (the downhill
// stain field). g_inst = the rock block.
fn gn_rock(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>, gp3: vec4<f32>) -> f32 {
    let fr = gn_frame(t);
    let salt = gp2.x * 1.91 + fr.face * 17.0;
    let s = max(gp.z, 0.01);
    let wq = vec2<f32>(gn_fbm(fr.p, vec2<f32>(s * 0.5), fr.tp, 3, salt), gn_fbm(fr.p, vec2<f32>(s * 0.5), fr.tp, 3, salt + 5.3)) - 0.5;
    let p = fr.p + wq * gp.w / s;
    let ridge = gn_ridged(p, vec2<f32>(s), fr.tp, 6, salt + 2.0);
    // strata: bands along v, bent by the warp, each protruding by its own amount
    let bands = select(1.6, gp3.x, gp3.x > 0.0);
    let kb = gn_k(vec2<f32>(1.0, bands), fr.tp).y;
    let bper = select(0.0, round(kb * fr.tp.y), fr.tp.y > 0.0);
    let b = p.y * kb + (gn_fbm(fr.p, vec2<f32>(s * 0.35), fr.tp, 2, salt + 8.0) - 0.5) * 2.2 + (gn_fbm(fr.p, vec2<f32>(s * 1.3, s * 0.6), fr.tp, 3, salt + 6.0) - 0.5) * 0.9;
    let bi = floor(b);
    let bf = b - bi;
    let bid = select(bi, bi - bper * floor(bi / max(bper, 1.0)), bper > 0.5);
    let br = gn_h(vec2<f32>(bid, 3.0), salt + 11.0);
    let slab = smoothstep(0.0, 0.14, bf) * smoothstep(1.0, 0.82, bf);
    let strata = mix(0.35, 1.0, br) * mix(0.55, 1.0, slab);
    // block joints: Voronoi borders, roughened
    let kc = gn_k(vec2<f32>(select(1.2, gp3.z, gp3.z > 0.0) * vec2<f32>(1.0, 0.75)), fr.tp);
    let pc = p + (vec2<f32>(gn_fbm(fr.p, vec2<f32>(s * 6.0), fr.tp, 3, salt + 13.0), gn_fbm(fr.p, vec2<f32>(s * 6.0), fr.tp, 3, salt + 14.0)) - 0.5) * 0.04;
    let v = gn_voronoi(pc, kc, gn_per(kc, fr.tp), 0.85, salt + 15.0);
    let cw = 0.006 + 0.012 * gn_fbm(fr.p, vec2<f32>(s * 3.0), fr.tp, 2, salt + 16.0);
    let crack = 1.0 - smoothstep(0.0, cw, v.edge);
    let block = gn_h(v.id, salt + 17.0);
    // downhill streaks: noise stretched along v (water and debris run down)
    let streak = gn_fbm(p, vec2<f32>(s * 5.0, s * 0.35), fr.tp, 3, salt + 19.0);
    let st = clamp(gp2.y, 0.0, 1.0);
    var h = mix(ridge, strata * (0.75 + 0.25 * ridge), st);
    h = h * (0.9 + 0.2 * block) + (streak - 0.5) * gp3.y * 0.35;
    h -= crack * clamp(gp2.z, 0.0, 2.0) * 0.45;
    h = clamp(h, 0.0, 1.0);
    g_inst = fract(block + br * 0.37);
    var o = h;
    switch u32(gp2.w + 0.5) {
        case 1u: { o = crack; }
        case 2u: { o = smoothstep(0.7, 0.95, bf) * mix(0.4, 1.0, br) * (1.0 - crack) * st; }
        case 3u: { o = streak; }
        default: {}
    }
    g_prof = o;
    return wx_threshold(o, gp);
}

// ---------------------------------------------------------------- grass blades

// blades: amount = density, scale = blades per metre (per axis), breakup =
// clumping, ao slot = lean (0 upright .. 1 lying flat), curvature slot =
// blade length (m), extra = (blade half width at the root (m), swirl: how
// much neighbouring blades lean the same way, level: where the tips / clumps
// mask starts, else 1 - amount). variant: 0 height (mask =
// covered), 1 tips (0 at the root .. 1 at the tip), 2 clumps (the clump
// density field). g_inst = the blade.
fn gn_blades(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>, gp3: vec4<f32>) -> f32 {
    let fr = gn_frame(t);
    let salt = gp2.x * 2.17 + fr.face * 17.0;
    let k = gn_k(vec2<f32>(max(gp.z, 1.0)), fr.tp);
    let per = gn_per(k, fr.tp);
    let q = fr.p * k;
    let ci = floor(q);
    let len = max(gp2.z, 0.003);
    let lean = clamp(gp2.y, 0.0, 1.0);
    let wid = select(0.0035, gp3.x, gp3.x > 0.0);
    let swirl = clamp(gp3.y, 0.0, 1.0);
    let reach = len * mix(0.3, 1.0, lean) * 1.25 + wid;
    let nr = i32(clamp(ceil(reach * max(k.x, k.y)), 1.0, 4.0));
    let clump = gn_fbm(fr.p, vec2<f32>(1.0 / max(len * 2.5, 0.01)), fr.tp, 3, salt + 3.0);
    let dens = gp.x * mix(1.0, smoothstep(0.32, 0.62, clump), clamp(gp.w, 0.0, 1.0));
    let flow = gn_fbm(fr.p, vec2<f32>(1.0 / max(len * 5.0, 0.02)), fr.tp, 2, salt + 9.0) * 12.566;
    var best = 0.0;
    var tip = 0.0;
    var inst = 0.5;
    for (var j = -nr; j <= nr; j++) {
        for (var i = -nr; i <= nr; i++) {
            let c = ci + vec2<f32>(f32(i), f32(j));
            let cw = gn_wrap(c, per);
            if (gn_h(cw, salt) > dens) { continue; }
            let root = (c + gn_h2(cw, salt + 3.1)) / k;
            let r1 = gn_h2(cw, salt + 5.7);
            let r2 = gn_h2(cw, salt + 8.3);
            let ang = mix(r1.x * 6.2831853, flow + (r1.x - 0.5) * 2.2, swirl);
            let dir = vec2<f32>(cos(ang), sin(ang));
            let L = len * (0.55 + 0.6 * r1.y) * mix(0.75, 1.15, clump);
            let proj = L * mix(0.3, 1.0, lean * (0.45 + 0.55 * r2.x));
            let d = fr.p - root;
            let along = dot(d, dir);
            if (along < -wid || along > proj) { continue; }
            let tt = clamp(along / proj, 0.0, 1.0);
            let bend = (r2.y - 0.5) * 0.5;
            let across = dot(d, vec2<f32>(-dir.y, dir.x)) - bend * tt * tt * proj;
            let w = wid * pow(1.0 - tt, 0.55) * (0.7 + 0.6 * r2.y) + 1e-5;
            if (abs(across) >= w) { continue; }
            let xs = abs(across) / w;
            let h = (0.2 + 0.8 * tt) * (0.55 + 0.45 * r1.y) * (0.8 + 0.2 * sqrt(1.0 - xs * xs)) * (1.0 - 0.06 * (1.0 - smoothstep(0.0, 0.2, xs)));
            if (h > best) {
                best = h;
                tip = tt;
                inst = gn_h(cw, salt + 13.0);
            }
        }
    }
    g_inst = inst;
    // tips / clumps: amount is the blade density, so the mask starts at `level` (extra[2]) when set
    let thr = select(1.0 - gp.x, gp3.z, gp3.z > 0.0);
    let soft = max(gp.y, 0.003);
    switch u32(gp2.w + 0.5) {
        case 1u: {
            g_prof = tip * step(1e-4, best);
            return smoothstep(thr - soft, thr + soft, g_prof);
        }
        case 2u: {
            g_prof = clump;
            return smoothstep(thr - soft, thr + soft, clump);
        }
        default: {}
    }
    g_prof = best;
    return smoothstep(0.0, max(gp.y, 0.003), best);
}

// ---------------------------------------------------------------- ripples

// ripples: scale = ripples per metre, breakup = irregularity (curving
// crests), ao slot = asymmetry (gentle windward, steep lee side), curvature
// slot = defects (crests that split, end and fade), extra = (crest
// direction in degrees from the surface's x axis, crest sharpness).
// variant: 0 height, 1 crests.
fn gn_ripples(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>, gp3: vec4<f32>) -> f32 {
    let fr = gn_frame(t);
    let salt = gp2.x * 2.53 + fr.face * 17.0;
    let f = max(gp.z, 0.05);
    let ang = gp3.x * 0.017453293;
    // the wave runs across the crests; snapped so whole waves fit the tile
    let kv = gn_kv(vec2<f32>(-sin(ang), cos(ang)) * f, fr.tp);
    let kv2 = gn_kv(vec2<f32>(-sin(ang + 0.5), cos(ang + 0.5)) * f * 1.9, fr.tp);
    let irr = clamp(gp.w, 0.0, 2.0);
    let defects = clamp(gp2.z, 0.0, 1.0);
    let w1 = gn_fbm(fr.p, vec2<f32>(f * 0.12), fr.tp, 3, salt) - 0.5;
    let w2 = gn_fbm(fr.p, vec2<f32>(f * 0.5), fr.tp, 2, salt + 4.0) - 0.5;
    var ph = dot(fr.p, kv) + (w1 * 3.5 + w2 * 0.9) * irr;
    // dislocations: half a wavelength of extra phase switched in over a
    // short distance makes crests fork (Y junctions) and end
    let dn = gn_fbm(fr.p, vec2<f32>(f * 0.3), fr.tp, 2, salt + 8.0);
    ph += 0.5 * smoothstep(0.47, 0.53, dn) * defects + 0.5 * smoothstep(0.6, 0.66, gn_fbm(fr.p, vec2<f32>(f * 0.22), fr.tp, 2, salt + 9.0)) * defects;
    let x = fract(ph);
    let a = 0.5 + 0.38 * clamp(gp2.y, 0.0, 1.0);
    var h = select((1.0 - x) / (1.0 - a), x / a, x < a);
    h = h * h * (3.0 - 2.0 * h);
    h = pow(h, mix(1.0, 0.55, clamp(gp3.y, 0.0, 1.0)));
    let amp = mix(1.0, 0.35 + 0.65 * smoothstep(0.25, 0.7, gn_fbm(fr.p, vec2<f32>(f * 0.18), fr.tp, 2, salt + 12.0)), defects);
    let fine = sin((dot(fr.p, kv2) + w2 * 0.6) * 6.2831853) * 0.5 + 0.5;
    let v = clamp(h * amp * 0.88 + fine * 0.12 * (1.0 - h * 0.5), 0.0, 1.0);
    g_inst = clamp(w1 + 0.5, 0.0, 1.0);
    var o = v;
    if (u32(gp2.w + 0.5) == 1u) {
        o = smoothstep(0.78, 0.96, h) * amp;
    }
    g_prof = o;
    return wx_threshold(o, gp);
}

fn gen_ground(t: vec2<i32>, kind: u32, gp: vec4<f32>, gp2: vec4<f32>, gp3: vec4<f32>) -> f32 {
    switch kind {
        case 15u: { return gn_cells(t, gp, gp2, gp3); }
        case 16u: { return gn_scatter(t, gp, gp2, gp3); }
        case 17u: { return gn_rock(t, gp, gp2, gp3); }
        case 18u: { return gn_blades(t, gp, gp2, gp3); }
        case 19u: { return gn_ripples(t, gp, gp2, gp3); }
        default: { return 0.0; }
    }
}

// Per-instance colour variation: brightness, hue (rotation about the grey
// axis), saturation; `id` is the generator's instance random.
fn gn_jitter_rgb(c: vec3<f32>, id: f32, j: vec4<f32>) -> vec3<f32> {
    let r1 = id;
    let r2 = fract(id * 97.31 + 0.17);
    let r3 = fract(id * 53.71 + 0.43);
    var o = c * (1.0 + (r1 - 0.5) * 2.0 * j.x);
    let a = (r2 - 0.5) * 2.0 * j.y * 6.2831853;
    let ax = vec3<f32>(0.57735027);
    o = o * cos(a) + cross(ax, o) * sin(a) + ax * dot(ax, o) * (1.0 - cos(a));
    let l = dot(o, vec3<f32>(0.2126, 0.7152, 0.0722));
    o = mix(vec3<f32>(l), o, 1.0 + (r3 - 0.5) * 2.0 * j.z);
    return max(o, vec3<f32>(0.0));
}
