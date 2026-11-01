// Layer compositing (one pass per visible layer, bottom to top) and the
// finalize pass that turns the composited stack into the material textures.
//
// Accumulation set (all Rgba16Float):
//   acc_color.rgb  linear base colour
//   acc_rmh        roughness, metallic, height
//   acc_normal.xyz tangent-space detail normal (painted / filled normals)
//   acc_emissive   linear HDR emission
//   acc_color.a    opacity (1 = solid)
//   acc_rmh.w      transmission (0 = opaque, 1 = glass)

// ---- group 0: mesh-derived data shared by every layer ----
@group(0) @binding(0) var bakes: texture_2d<f32>;      // r = AO, g = curvature (0.5 neutral)
@group(0) @binding(1) var position: texture_2d<f32>;   // world position, w = coverage
@group(0) @binding(2) var nearest: texture_2d<u32>;    // jump-flood nearest covered texel
struct Shared {
    center_radius: vec4<f32>,   // bounding sphere for noise space
    res: vec4<f32>,             // x = resolution, y = height-to-normal strength
    bmin: vec4<f32>,            // mesh bounds
    bmax: vec4<f32>,
};
@group(0) @binding(3) var<uniform> sh: Shared;
@group(0) @binding(4) var wnormal: texture_2d<f32>;    // world normal
@group(0) @binding(5) var parts: texture_2d<u32>;      // mesh part id + 1

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
@group(2) @binding(9) var l_opacity: texture_2d<f32>;       // r value, g coverage
@group(2) @binding(10) var l_transmission: texture_2d<f32>;  // r value, g coverage
struct LayerParams {
    flags: vec4<u32>,       // kind (0 paint, 1 fill), has mask, generator id, invert
    blend: vec4<u32>,       // color, rough, metal, height
    blend2: vec4<u32>,      // normal, emissive, opacity, transmission
    opacity: vec4<f32>,     // color, rough, metal, height (layer x channel x enabled)
    opacity2: vec4<f32>,    // normal, emissive, opacity, transmission
    fill_color: vec4<f32>,  // linear rgb, a = opacity value
    fill_rmh: vec4<f32>,    // roughness, metallic, height, transmission
    fill_normal: vec4<f32>,
    gen: vec4<f32>,         // amount, softness, noise scale, noise amount
    gen2: vec4<f32>,        // seed, AO influence, curvature weight
    fill_emissive: vec4<f32>, // linear rgb x strength
    eff: vec4<u32>,           // extra mask effects: kind b, op b, kind c, op c
    gb: vec4<f32>,
    gb2: vec4<f32>,
    gc: vec4<f32>,
    gc2: vec4<f32>,
    misc: vec4<u32>,          // x = part selection on, y = first word in part_bits, z = word count
    img: vec4<u32>,           // image fill: channel bits (1 colour, 2 rough, 4 height, 8 normal), projection (0 uv, 1 triplanar)
    img_xf: vec4<f32>,        // tiling u, v, offset u, v
    img_xf2: vec4<f32>,       // cos, sin (rotation), 1 / tile size (m), blend sharpness
    img_tint: vec4<f32>,      // linear tint rgb, height scale
    img_amt: vec4<f32>,       // roughness lo, hi, normal strength
};
@group(2) @binding(7) var<uniform> lp: LayerParams;
// Image fills bind their tiling images in the channel slots above
// (l_color, l_rough, l_height, l_normal) and sample them with this.
@group(2) @binding(8) var img_samp: sampler;
// (bindings 9, 10: l_opacity, l_transmission above)
// Selected-parts bitsets of every visible layer, packed back to back
// (layer: words misc.y .. misc.y + misc.z; bit k = part id k).
@group(2) @binding(11) var<storage, read> part_bits: array<u32>;

struct Acc {
    @location(0) color: vec4<f32>,
    @location(1) rmh: vec4<f32>,
    @location(2) normal: vec4<f32>,
    @location(3) emissive: vec4<f32>,
};


// ---------- seamless tile mode ----------
// Flat tile / trim sheet projects set sh.res.z / sh.res.w to the world period
// along x / z in metres (0 = that axis doesn't wrap). Every world-space noise
// then becomes periodic over the tile: the scale is snapped so a whole number
// of lattice cells fits the period, and the lattice hash wraps (a periodic
// hash lattice). Outside tile mode all of this is the identity, so ordinary
// projects composite exactly as before.

fn tile_len() -> vec3<f32> { return vec3<f32>(sh.res.z, 0.0, sh.res.w); }
fn tile_on() -> bool { return sh.res.z > 0.0 || sh.res.w > 0.0; }

// World -> noise scale (per axis), snapped to whole cells per period.
fn tscale(s: vec3<f32>) -> vec3<f32> {
    let l = tile_len();
    let snapped = max(round(abs(s) * l), vec3<f32>(1.0)) / max(l, vec3<f32>(1e-6)) * sign(s);
    return select(s, snapped, l > vec3<f32>(0.0) & abs(s) > vec3<f32>(0.0));
}
// Lattice period in cells for a snapped scale (0 = no wrap on that axis).
fn tper(s: vec3<f32>) -> vec3<f32> {
    return round(abs(s) * tile_len());
}

fn lwrap(i: vec3<f32>, per: vec3<f32>) -> vec3<f32> {
    let m = i - per * floor(i / max(per, vec3<f32>(1.0)));
    return select(i, m, per > vec3<f32>(0.5));
}

fn vnoise_p(p: vec3<f32>, per: vec3<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let a = mix(mix(hash3(lwrap(i, per)), hash3(lwrap(i + vec3<f32>(1.0, 0.0, 0.0), per)), u.x),
                mix(hash3(lwrap(i + vec3<f32>(0.0, 1.0, 0.0), per)), hash3(lwrap(i + vec3<f32>(1.0, 1.0, 0.0), per)), u.x), u.y);
    let b = mix(mix(hash3(lwrap(i + vec3<f32>(0.0, 0.0, 1.0), per)), hash3(lwrap(i + vec3<f32>(1.0, 0.0, 1.0), per)), u.x),
                mix(hash3(lwrap(i + vec3<f32>(0.0, 1.0, 1.0), per)), hash3(lwrap(i + vec3<f32>(1.0, 1.0, 1.0), per)), u.x), u.y);
    return mix(a, b, u.z);
}

// fbm whose input has lattice period `per` (cells; 0 = none): each octave
// multiplies the period by ~2.03, rounded so it stays whole.
fn fbm_p(p: vec3<f32>, per: vec3<f32>) -> f32 {
    if (all(per < vec3<f32>(0.5))) { return fbm(p); }
    var s = 0.0;
    var amp = 0.5;
    var q = p;
    var pr = per;
    for (var i = 0; i < 5; i++) {
        s += vnoise_p(q, pr) * amp;
        let np = max(round(pr * 2.03), vec3<f32>(1.0));
        let wrapped = pr > vec3<f32>(0.5);
        q = q * select(vec3<f32>(2.03), np / max(pr, vec3<f32>(1.0)), wrapped) + vec3<f32>(17.1, 3.7, 9.2);
        pr = select(vec3<f32>(0.0), np, wrapped);
        amp *= 0.5;
    }
    return s / 0.96875;
}

// fbm(q) where q = pw * s + c. Outside tile mode this is exactly fbm(q) (q is
// passed as written, so results are bit-identical); in tile mode it is
// periodic over the tile.
fn fbm_s(q: vec3<f32>, pw: vec3<f32>, s: vec3<f32>, c: vec3<f32>) -> f32 {
    if (!tile_on()) { return fbm(q); }
    let k = tscale(s);
    return fbm_p(pw * k + c, tper(k));
}
fn ridged_s(q: vec3<f32>, pw: vec3<f32>, s: vec3<f32>, c: vec3<f32>) -> f32 {
    return 1.0 - abs(fbm_s(q, pw, s, c) * 2.0 - 1.0);
}
// Wrap a texel coordinate around the texture on tiling axes.
fn twrap(t: vec2<i32>) -> vec2<i32> {
    let size = i32(sh.res.x);
    var o = t;
    if (sh.res.z > 0.0) { o.x = ((t.x % size) + size) % size; }
    if (sh.res.w > 0.0) { o.y = ((t.y % size) + size) % size; }
    return o;
}

// Ridged fbm: 1 at the noise's zero crossings, falling off around them.
fn ridged(p: vec3<f32>) -> f32 {
    return 1.0 - abs(fbm(p) * 2.0 - 1.0);
}

fn gen_eval(t: vec2<i32>, kind: u32, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    if (kind >= 10u) { return gen_weather(t, kind, gp, gp2); }  // gen_weather.wgsl
    let bk = textureLoad(bakes, t, 0);
    let ao = bk.r;
    let curv = bk.g;
    let pw = textureLoad(position, t, 0).xyz;                 // world, metres
    let p = (pw - sh.center_radius.xyz) / max(sh.center_radius.w, 1e-6);  // object-relative
    let seed = vec3<f32>(gp2.x * 7.31, gp2.x * 3.17, gp2.x * 5.53);
    let s = gp.z;
    let n = fbm_s(p * s + seed, pw, vec3<f32>(s / max(sh.center_radius.w, 1e-6)), seed);
    let threshold = 1.0 - gp.x;
    let soft = max(gp.y, 0.003);
    let occl = 1.0 - ao;
    var v = 0.0;
    switch kind {
        case 1u: {
            // edge wear: convex curvature, broken up by noise, kept out of occluded areas
            let convex = clamp((curv - 0.5) * 2.0, 0.0, 1.0);
            v = convex * gp2.z + (n - 0.5) * gp.w - occl * gp2.y;
        }
        case 2u: {
            // dirt: occluded and concave areas
            let cavity = clamp((0.5 - curv) * 2.0, 0.0, 1.0);
            v = max(occl * gp2.y, cavity * gp2.z) + (n - 0.5) * gp.w;
        }
        case 3u: {
            // grunge: two octaves of blotches, in world space
            v = fbm_s(pw * s + seed, pw, vec3<f32>(s), seed) * 0.65 + fbm_s(pw * s * 4.3 + seed.zxy, pw, vec3<f32>(s * 4.3), seed.zxy) * 0.35 + occl * gp2.y;
        }
        case 4u: {
            // streaks: noise stretched along world up, more under overhangs
            let q = vec3<f32>(pw.x * s, pw.y * s * 0.07, pw.z * s);
            let sq = vec3<f32>(s, s * 0.07, s);
            v = fbm_s(q + seed, pw, sq, seed) * 0.8 + fbm_s(q * 3.0 + seed.yzx, pw, sq * 3.0, seed.yzx) * 0.2 + occl * gp2.y;
        }
        case 5u: {
            // hazard stripes: diagonal triangle wave in world space (amount = stripe width)
            var d = (pw.x + pw.y + pw.z) * s;
            if (tile_on()) { d = dot(pw, tscale(vec3<f32>(s))); }
            v = abs(fract(d) - 0.5) * 2.0 + (fbm_s(pw * 8.0 + seed, pw, vec3<f32>(8.0), seed) - 0.5) * gp.w * 0.3;
        }
        case 6u: {
            // spots: domain-warped blobs
            let s7 = vec3<f32>(s * 0.7);
            let warp = vec3<f32>(fbm_s(pw * s * 0.7 + seed, pw, s7, seed), fbm_s(pw * s * 0.7 + seed.yzx, pw, s7, seed.yzx), fbm_s(pw * s * 0.7 + seed.zxy, pw, s7, seed.zxy)) * 2.0;
            if (tile_on()) {
                let k = tscale(vec3<f32>(s));
                v = smoothstep(0.35, 0.75, fbm_p(pw * k + warp + seed * 1.3, tper(k))) + occl * gp2.y;
            } else {
                let w = pw * s + warp;
                v = smoothstep(0.35, 0.75, fbm(w + seed * 1.3)) + occl * gp2.y;
            }
        }
        case 7u: {
            // scratches: sharp ridges of strongly stretched noise, two directions
            let a = ridged_s(vec3<f32>(pw.x * s, pw.y * s * 9.0, pw.z * s) + seed, pw, vec3<f32>(s, s * 9.0, s), seed);
            let b = ridged_s(vec3<f32>(pw.x * s * 9.0, pw.y * s, pw.z * s * 9.0) + seed.zyx, pw, vec3<f32>(s * 9.0, s, s * 9.0), seed.zyx);
            v = pow(max(a, b), 10.0) * smoothstep(0.35, 0.6, fbm_s(pw * s * 0.5 + seed, pw, vec3<f32>(s * 0.5), seed));
        }
        case 8u: {
            // panel lines: distance to a world grid, measured on the two axes
            // that lie in the surface (the axis along the normal is skipped)
            let nrm = abs(normalize(textureLoad(wnormal, t, 0).xyz));
            let g = fract(pw * tscale(vec3<f32>(s)));
            let dist = min(g, vec3<f32>(1.0) - g);
            var dmin = 1.0;
            if (nrm.x < 0.75) { dmin = min(dmin, dist.x); }
            if (nrm.y < 0.75) { dmin = min(dmin, dist.y); }
            if (nrm.z < 0.75) { dmin = min(dmin, dist.z); }
            v = 1.0 - dmin * 2.0;
        }
        case 9u: {
            // ground gradient: 1 at the bottom of the model, 0 at the top
            let yr = (pw.y - sh.bmin.y) / max(sh.bmax.y - sh.bmin.y, 1e-4);
            v = 1.0 - yr;
        }
        default: {}
    }
    if (kind >= 3u && kind != 5u) {
        v += (n - 0.5) * gp.w;
    }
    return smoothstep(threshold - soft, threshold + soft, v);
}

fn combine(op: u32, a: f32, b: f32) -> f32 {
    switch op {
        case 1u: { return min(a + b, 1.0); }
        case 2u: { return max(a - b, 0.0); }
        case 3u: { return max(a, b); }
        case 4u: { return min(a, b); }
        default: { return a * b; }
    }
}

// The main generator, then up to two more combined in order.
fn generator(t: vec2<i32>) -> f32 {
    var g = gen_eval(t, lp.flags.z, lp.gen, lp.gen2);
    if (lp.eff.x != 0u) { g = combine(lp.eff.y, g, gen_eval(t, lp.eff.x, lp.gb, lp.gb2)); }
    if (lp.eff.z != 0u) { g = combine(lp.eff.w, g, gen_eval(t, lp.eff.z, lp.gc, lp.gc2)); }
    return g;
}

// Is this texel on one of the selected mesh parts?
fn part_selected(t: vec2<i32>) -> f32 {
    let id = textureLoad(parts, t, 0).r;
    if (id == 0u) { return 0.0; }
    let k = id - 1u;
    let word = k / 32u;
    if (word >= lp.misc.z) { return 0.0; }
    let w = part_bits[lp.misc.y + word];
    return f32((w >> (k % 32u)) & 1u);
}

// ---------- image fills ----------
// Tiling images projected in UV space or triplanar in world space. Sampled
// with analytic gradients (texel -> image coordinates), so mips and
// anisotropic filtering work in this fullscreen texture-space pass.

struct ImgTap {
    c: vec3<f32>,   // linear colour
    r: f32,
    h: f32,
    n: vec3<f32>,   // decoded normal, image frame (+y up the image)
};

fn img_rot(v: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(lp.img_xf2.x * v.x - lp.img_xf2.y * v.y, lp.img_xf2.y * v.x + lp.img_xf2.x * v.y);
}
fn img_unrot(v: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(lp.img_xf2.x * v.x + lp.img_xf2.y * v.y, -lp.img_xf2.y * v.x + lp.img_xf2.x * v.y);
}

fn img_tap(q: vec2<f32>, gx: vec2<f32>, gy: vec2<f32>) -> ImgTap {
    var o: ImgTap;
    o.c = vec3<f32>(1.0);
    o.r = 0.5;
    o.h = 0.5;
    o.n = vec3<f32>(0.0, 0.0, 1.0);
    let bits = lp.img.x;
    if ((bits & 1u) != 0u) { o.c = textureSampleGrad(l_color, img_samp, q, gx, gy).rgb; }
    if ((bits & 2u) != 0u) { o.r = textureSampleGrad(l_rough, img_samp, q, gx, gy).r; }
    if ((bits & 4u) != 0u) { o.h = textureSampleGrad(l_height, img_samp, q, gx, gy).r; }
    if ((bits & 8u) != 0u) { o.n = textureSampleGrad(l_normal, img_samp, q, gx, gy).xyz * 2.0 - 1.0; }
    return o;
}

// World-space change of the surface position per texel step `d`.
fn pos_step(s: vec2<i32>, d: vec2<i32>) -> vec3<f32> {
    let p = covered(s + d);
    let m = covered(s - d);
    let c = textureLoad(position, s, 0).xyz;
    if (p && m) { return (textureLoad(position, s + d, 0).xyz - textureLoad(position, s - d, 0).xyz) * 0.5; }
    if (p) { return textureLoad(position, s + d, 0).xyz - c; }
    if (m) { return c - textureLoad(position, s - d, 0).xyz; }
    return vec3<f32>(0.0);
}

// An image normal (image frame) turned into a direction in the projection
// plane's (u, v-down) coordinates, before rotation.
fn img_normal_dir(n: vec3<f32>) -> vec2<f32> {
    return img_unrot(vec2<f32>(n.x, -n.y)) * lp.img_amt.z;
}

fn image_fill(t: vec2<i32>) -> ImgTap {
    let res = sh.res.x;
    if (lp.img.y == 0u) {
        // UV: repeats `tiling` times over the texture
        let uv = (vec2<f32>(t) + 0.5) / res;
        var tl = lp.img_xf.xy;
        if (sh.res.z > 0.0) { tl.x = max(round(tl.x), 1.0); }
        if (sh.res.w > 0.0) { tl.y = max(round(tl.y), 1.0); }
        let q = img_rot(uv * tl) + lp.img_xf.zw;
        var o = img_tap(q, img_rot(vec2<f32>(tl.x / res, 0.0)), img_rot(vec2<f32>(0.0, tl.y / res)));
        // texel frame: +x along +u, +y towards -v (OpenGL)
        let d = img_normal_dir(o.n);
        o.n = normalize(vec3<f32>(d.x, -d.y, max(o.n.z, 1e-3)));
        return o;
    }
    // triplanar in world space
    var o: ImgTap;
    o.c = vec3<f32>(0.0);
    o.r = 0.0;
    o.h = 0.0;
    o.n = vec3<f32>(0.0, 0.0, 1.0);
    let pw = textureLoad(position, t, 0);
    let nl = length(textureLoad(wnormal, t, 0).xyz);
    if (pw.w == 0.0 || nl < 1e-5) { return img_tap(vec2<f32>(0.0), vec2<f32>(0.0), vec2<f32>(0.0)); }
    let p = pw.xyz;
    let nrm = textureLoad(wnormal, t, 0).xyz / nl;
    let dx = pos_step(t, vec2<i32>(1, 0));
    let dy = pos_step(t, vec2<i32>(0, 1));
    var w = pow(max(abs(nrm), vec3<f32>(1e-4)), vec3<f32>(lp.img_xf2.w));
    w = w / max(w.x + w.y + w.z, 1e-6);
    let sg = select(vec3<f32>(-1.0), vec3<f32>(1.0), nrm >= vec3<f32>(0.0));
    let inv = lp.img_xf2.z;
    var pert = vec3<f32>(0.0);
    for (var i = 0; i < 3; i++) {
        var wi = w.x;
        // plane axes: ua = direction of +u, va = direction of +v (image down);
        // ua x -va = the plane's outward normal, so images are never mirrored
        var ua = vec3<f32>(0.0, 0.0, -sg.x);
        var va = vec3<f32>(0.0, -1.0, 0.0);
        if (i == 1) {
            wi = w.y;
            ua = vec3<f32>(1.0, 0.0, 0.0);
            va = vec3<f32>(0.0, 0.0, sg.y);
        } else if (i == 2) {
            wi = w.z;
            ua = vec3<f32>(sg.z, 0.0, 0.0);
            va = vec3<f32>(0.0, -1.0, 0.0);
        }
        if (wi < 0.002) { continue; }
        var invs = vec2<f32>(inv);
        if (i == 1 && tile_on()) {
            let k = tscale(vec3<f32>(inv));
            invs = vec2<f32>(k.x, k.z);
        }
        let q = img_rot(vec2<f32>(dot(p, ua), dot(p, va)) * invs) + lp.img_xf.zw;
        let gx = img_rot(vec2<f32>(dot(dx, ua), dot(dx, va)) * inv);
        let gy = img_rot(vec2<f32>(dot(dy, ua), dot(dy, va)) * inv);
        let s = img_tap(q, gx, gy);
        o.c += s.c * wi;
        o.r += s.r * wi;
        o.h += s.h * wi;
        let d = img_normal_dir(s.n);
        pert += (ua * d.x + va * d.y) * wi;
    }
    // world normal -> this texel's tangent frame (from the position map)
    let nw = normalize(nrm + pert);
    let tx = dx - nrm * dot(nrm, dx);
    let ty = -(dy - nrm * dot(nrm, dy));
    if (dot(tx, tx) < 1e-20 || dot(ty, ty) < 1e-20) { return o; }
    o.n = normalize(vec3<f32>(dot(nw, normalize(tx)), dot(nw, normalize(ty)), max(dot(nw, nrm), 1e-3)));
    return o;
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
    var op = vec2<f32>(lp.fill_color.a, 1.0);
    var tr = vec2<f32>(lp.fill_rmh.w, 1.0);
    if (lp.flags.x == 0u) {
        op = textureLoad(l_opacity, t, 0).rg;
        tr = textureLoad(l_transmission, t, 0).rg;
        c = textureLoad(l_color, t, 0);
        r = textureLoad(l_rough, t, 0).rg;
        m = textureLoad(l_metal, t, 0).rg;
        h = textureLoad(l_height, t, 0).rg;
        let ln = textureLoad(l_normal, t, 0);
        n = vec4<f32>(normalize(ln.xyz * 2.0 - 1.0 + vec3<f32>(0.0, 0.0, 1e-4)), ln.a);
        e = textureLoad(l_emissive, t, 0);
    }

    if (lp.flags.x == 1u && lp.img.x != 0u) {
        let im = image_fill(t);
        if ((lp.img.x & 1u) != 0u) { c = vec4<f32>(im.c * lp.img_tint.rgb, 1.0); }
        if ((lp.img.x & 2u) != 0u) { r.x = mix(lp.img_amt.x, lp.img_amt.y, im.r); }
        if ((lp.img.x & 4u) != 0u) { h.x = (im.h - 0.5) * lp.img_tint.w; }
        if ((lp.img.x & 8u) != 0u) { n = vec4<f32>(im.n, 1.0); }
    }

    var mask = 1.0;
    if (lp.flags.y == 1u) {
        mask = textureLoad(l_mask, t, 0).r;
        if (lp.flags.z != 0u) { mask *= generator(t); }
        if (lp.misc.x == 1u) {
            // selection is looked up at the padded source texel so seams stay clean
            mask *= part_selected(src_texel(t));
        }
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
    let ao = select(op.y, 1.0, lp.blend2.z == 8u) * lp.opacity2.z * mask;
    let at = select(tr.y, 1.0, lp.blend2.w == 8u) * lp.opacity2.w * mask;

    var o: Acc;
    o.color = vec4<f32>(max(blend_rgb(lp.blend.x, dc.rgb, c.rgb, a.x), vec3<f32>(0.0)), clamp(blend_scalar(lp.blend2.z, dc.a, op.x, ao), 0.0, 1.0));
    o.rmh = vec4<f32>(
        clamp(blend_scalar(lp.blend.y, dr.x, r.x, a.y), 0.0, 1.0),
        clamp(blend_scalar(lp.blend.z, dr.y, m.x, a.z), 0.0, 1.0),
        // height is HDR (stacked dents can pass -1); clamped only on export
        clamp(blend_scalar(lp.blend.w, dr.z, h.x, a.w), -8.0, 8.0),
        clamp(blend_scalar(lp.blend2.w, dr.w, tr.x, at), 0.0, 1.0));
    o.normal = vec4<f32>(blend_normal(lp.blend2.x, dn, n.xyz, an), 1.0);
    o.emissive = vec4<f32>(max(blend_rgb(lp.blend2.y, de, e.rgb, ae), vec3<f32>(0.0)), 1.0);
    return o;
}

// Defaults under the bottom layer.
@fragment
fn fs_clear(f: FullOut) -> Acc {
    var o: Acc;
    o.color = vec4<f32>(srgb_to_linear(vec3<f32>(0.5)), 1.0);
    o.rmh = vec4<f32>(0.5, 0.0, 0.0, 0.0);  // w: transmission
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
    @location(0) color: vec4<f32>,   // srgb target, a = opacity
    @location(1) orm: vec4<f32>,     // ao, roughness, metallic, transmission
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
    let c = clamp(twrap(t), vec2<i32>(0), vec2<i32>(size - 1));
    return textureLoad(acc_rmh, src_texel(c), 0).z;
}

// Is texel t inside a UV island (rather than padding)?
fn covered(t0: vec2<i32>) -> bool {
    let size = i32(sh.res.x);
    let t = twrap(t0);
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
    o.color = vec4<f32>(c.rgb, c.a);
    o.orm = vec4<f32>(ao, rmh.x, rmh.y, rmh.w);
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
