// World-space box decals (pigment_core::decal::Placement).
//
// The mesh is rasterised into the texture (position = UV), like the brush.
// Each texel knows its world position; if it falls inside the decal's box
// and faces it, it takes the image. No camera: exact size in metres, any
// spot on any face, and occluders don't matter.
//
// Wear (posters on a street wall):
//   tear: fbm noise, biased towards the edges and the bottom, eats the decal
//         away; a thin rim of bare paper is left along each tear.
//   fade: patchy sun bleaching (desaturate + lighten) and wear-through.
//   style 0 = soft noise, 1 = grunge (ridged, vertically streaked noise).

@group(0) @binding(0) var img: texture_2d<f32>;
@group(0) @binding(1) var samp: sampler;
struct BoxDecal {
    center: vec4<f32>,   // xyz, half depth (m)
    right: vec4<f32>,    // unit xyz, half width (m)
    up: vec4<f32>,       // unit xyz, half height (m)
    normal: vec4<f32>,   // unit xyz, opacity
    params: vec4<f32>,   // alpha from luminance (0/1), min facing, -, -
    wear: vec4<f32>,     // tear 0..1, fade 0..1, noise scale, seed
    wear2: vec4<f32>,    // style (0 noise / 1 grunge), paper rim width, -, -
};
@group(0) @binding(2) var<uniform> d: BoxDecal;

struct BoxOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
};

struct BoxDecalOut {
    @location(0) mask: vec4<f32>,
    @location(1) color: vec4<f32>,
};

@vertex
fn vs_box(v: MeshIn) -> BoxOut {
    var o: BoxOut;
    o.pos = uv_to_clip(v.uv);
    o.world = v.position;
    o.normal = v.normal;
    return o;
}

fn wear_noise(p: vec3<f32>, style: f32) -> f32 {
    if (style > 0.5) {
        // grunge: ridged, stretched vertically like water runs
        let q = p * vec3<f32>(1.6, 0.45, 1.0);
        let r = 1.0 - abs(fbm(q) * 2.0 - 1.0);
        return clamp(mix(fbm(p * 1.7), r, 0.6), 0.0, 1.0);
    }
    return fbm(p);
}

@fragment
fn fs_box(i: BoxOut) -> BoxDecalOut {
    let rel = i.world - d.center.xyz;
    let lx = dot(rel, d.right.xyz) / d.right.w;
    let ly = dot(rel, d.up.xyz) / d.up.w;
    let lz = dot(rel, d.normal.xyz);
    let uv = vec2<f32>(lx * 0.5 + 0.5, 0.5 - ly * 0.5);
    // texel-space derivatives pick the right mip; taken before any discard
    let gx = dpdx(uv);
    let gy = dpdy(uv);
    if (abs(lx) > 1.0 || abs(ly) > 1.0 || abs(lz) > d.center.w) { discard; }
    let facing = dot(normalize(i.normal), d.normal.xyz);
    let fw = smoothstep(d.params.y, d.params.y + 0.25, facing);

    let c = textureSampleGrad(img, samp, uv, gx, gy);
    var a = c.a;
    if (d.params.x > 0.5) { a = a * dot(c.rgb, vec3<f32>(0.299, 0.587, 0.114)); }
    var rgb = c.rgb;

    let aspect = d.right.w / max(d.up.w, 1e-5);
    let seed = d.wear.w;
    let p = vec3<f32>(uv.x * aspect, uv.y, 0.0) * d.wear.z + vec3<f32>(seed * 17.13, seed * 5.37, seed * 3.11);
    let style = d.wear2.x;

    // fade: patchy bleaching and wear-through
    if (d.wear.y > 0.0) {
        let n2 = wear_noise(p * 0.6 + vec3<f32>(11.0, 3.0, 7.0), style);
        let f = clamp(d.wear.y * (0.35 + 1.3 * n2), 0.0, 1.0);
        let lum = dot(rgb, vec3<f32>(0.2126, 0.7152, 0.0722));
        let bleached = mix(vec3<f32>(lum), rgb, 0.3) * 0.65 + vec3<f32>(0.3, 0.3, 0.28);
        rgb = mix(rgb, bleached, f * 0.85);
        a = a * (1.0 - d.wear.y * 0.5 * smoothstep(0.45, 0.8, n2));
    }

    // tear: eaten from the edges (and more from the bottom, where people pull)
    if (d.wear.x > 0.0) {
        let n = wear_noise(p, style);
        // distance to the nearest edge as a fraction of the shorter side (0..0.5)
        let ex = min(uv.x, 1.0 - uv.x) * d.right.w;
        let ey = min(uv.y, 1.0 - uv.y) * d.up.w;
        let edge = min(ex, ey) / max(min(d.right.w, d.up.w), 1e-5);
        let keep = n + smoothstep(0.0, 0.3, edge) * 0.55 - uv.y * 0.15;
        let thr = d.wear.x * 1.05;
        a = a * smoothstep(thr, thr + 0.012, keep);
        let rim = d.wear2.y;
        if (rim > 0.0) {
            // bare paper along the tear
            let paper = smoothstep(thr + rim, thr + rim * 0.6, keep);
            rgb = mix(rgb, vec3<f32>(0.62, 0.6, 0.53), paper * step(0.05, c.a));
        }
    }

    let cov = a * d.normal.w * fw;
    if (cov <= 0.002) { discard; }
    var o: BoxDecalOut;
    o.mask = vec4<f32>(cov, 0.0, 0.0, 1.0);
    o.color = vec4<f32>(rgb, 1.0);
    return o;
}
