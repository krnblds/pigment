// Brush painting.
//
// 1. Stamp pass: the mesh is rasterised *into the texture* (position = UV).
//    Each fragment is one texel of the layer and knows its world position.
//    It projects itself with the viewport camera, checks it is visible
//    (viewport depth) and facing the camera, and takes the max brush falloff
//    over this frame's stamps. Max-blending into the stroke mask means
//    overlapping stamps of one stroke don't build up: opacity is per stroke.
// 2. Apply pass: layer = composite(before-stroke copy, brush values, mask).

struct View {
    view_proj: mat4x4<f32>,
    eye: vec4<f32>,
    viewport: vec4<f32>,     // width, height, near, stamp count
};
@group(0) @binding(0) var<uniform> view: View;
@group(0) @binding(1) var depth: texture_depth_2d;
struct Stamp {
    center_radius: vec4<f32>, // x, y (px), radius (px), opacity
    params: vec4<f32>,        // hardness, angle (radians), tip (0 = round falloff, k = tip layer k - 1), flow
};
@group(0) @binding(2) var<storage, read> stamps: array<Stamp>;
// Brush tips: grayscale stamps (white = paint), one per array layer.
@group(0) @binding(3) var tips: texture_2d_array<f32>;
@group(0) @binding(4) var tip_samp: sampler;
// Brush engine extras (pigment_core::brush): symmetry transforms (object
// space; a texel at p is painted when sym[k] * p is under the brush), flow
// mode and a screen-space stencil.
struct Fx {
    sym: array<mat4x4<f32>, 16>,
    info: vec4<f32>,      // symmetry count, flow mode (1 = dabs add up), stencil on, stencil opacity
    stencil: vec4<f32>,   // centre x, y (px), cos, sin (rotation)
    stencil2: vec4<f32>,  // half size x, y (px), invert (1/0)
};
@group(0) @binding(5) var<uniform> fx: Fx;
@group(0) @binding(6) var stencil_tex: texture_2d<f32>;

struct StampOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
};

@vertex
fn vs_stamp(v: MeshIn) -> StampOut {
    var o: StampOut;
    o.pos = uv_to_clip(v.uv);
    o.world = v.position;
    o.normal = v.normal;
    return o;
}

// One dab's coverage at screen pixel px: round falloff, or a tip image
// rotated by the dab's angle.
fn dab(px: vec2<f32>, s: Stamp) -> f32 {
    let r = max(s.center_radius.z, 0.5);
    let d = px - s.center_radius.xy;
    if (s.params.z < 0.5) {
        return falloff(length(d) / r, s.params.x);
    }
    let c = cos(s.params.y);
    let sn = sin(s.params.y);
    let q = vec2<f32>(c * d.x + sn * d.y, -sn * d.x + c * d.y) / r;
    if (any(abs(q) > vec2<f32>(1.0))) { return 0.0; }
    return textureSampleLevel(tips, tip_samp, q * 0.5 + 0.5, i32(s.params.z - 0.5), 0.0).r;
}

// Stencil value at screen pixel px (1 without a stencil).
fn stencil_at(px: vec2<f32>) -> f32 {
    if (fx.info.z < 0.5) { return 1.0; }
    let d = px - fx.stencil.xy;
    let q = vec2<f32>(fx.stencil.z * d.x + fx.stencil.w * d.y, -fx.stencil.w * d.x + fx.stencil.z * d.y) / max(fx.stencil2.xy, vec2<f32>(1.0));
    var v = 0.0;
    if (all(abs(q) <= vec2<f32>(1.0))) {
        let t = textureSampleLevel(stencil_tex, tip_samp, q * 0.5 + 0.5, 0.0);
        v = dot(t.rgb, vec3<f32>(0.299, 0.587, 0.114)) * t.a;
    }
    if (fx.stencil2.z > 0.5) { v = 1.0 - v; }
    return mix(1.0, v, fx.info.w);
}

// Brush coverage of world point w (normal n), seen by the camera: 0 when
// off screen, hidden or edge-on.
fn coverage(w: vec3<f32>, n: vec3<f32>) -> f32 {
    let clip = view.view_proj * vec4<f32>(w, 1.0);
    if (clip.w <= 0.0) { return 0.0; }
    let ndc = clip.xyz / clip.w;
    let px = vec2<f32>((ndc.x * 0.5 + 0.5) * view.viewport.x, (0.5 - ndc.y * 0.5) * view.viewport.y);
    if (px.x < 0.0 || px.y < 0.0 || px.x >= view.viewport.x || px.y >= view.viewport.y) { return 0.0; }

    // Brush coverage first (cheap), visibility only if something is under the brush.
    var f = 0.0;
    let count = u32(view.viewport.w);
    let additive = fx.info.y > 0.5;
    for (var k = 0u; k < count; k++) {
        let s = stamps[k];
        let v = dab(px, s) * s.center_radius.w;
        if (additive) { f += v * s.params.w; } else { f = max(f, v); }
    }
    if (f <= 0.0) { return 0.0; }

    // Occlusion: compare linear depths (reverse-Z: depth = near / view_z).
    let scene = textureLoad(depth, vec2<i32>(px), 0);
    let near = view.viewport.z;
    let z_frag = near / max(ndc.z, 1e-9);
    let z_scene = near / max(scene, 1e-9);
    if (z_frag > z_scene * 1.004 + near * 2.0) { return 0.0; }

    // Fade out on surfaces seen edge-on so strokes don't smear along silhouettes.
    let facing = dot(normalize(n), normalize(view.eye.xyz - w));
    return f * smoothstep(0.0, 0.25, facing) * stencil_at(px);
}

@fragment
fn fs_stamp(i: StampOut) -> @location(0) vec4<f32> {
    var f = 0.0;
    let ns = max(u32(fx.info.x), 1u);
    for (var k = 0u; k < ns; k++) {
        var m = fx.sym[k];
        if (fx.info.x < 0.5) { m = mat4x4<f32>(vec4<f32>(1.0, 0.0, 0.0, 0.0), vec4<f32>(0.0, 1.0, 0.0, 0.0), vec4<f32>(0.0, 0.0, 1.0, 0.0), vec4<f32>(0.0, 0.0, 0.0, 1.0)); }
        let w = (m * vec4<f32>(i.world, 1.0)).xyz;
        let n = (m * vec4<f32>(i.normal, 0.0)).xyz;
        f = max(f, coverage(w, n));
    }
    if (f <= 0.0) { discard; }
    return vec4<f32>(f, 0.0, 0.0, 1.0);
}


// ---------- decals ----------
// Same projection and visibility as the brush, but coverage and colour come
// from an image laid over a screen rectangle: a sticker shot from the camera.
@group(1) @binding(0) var decal: texture_2d<f32>;
@group(1) @binding(1) var decal_samp: sampler;
struct Decal {
    rect: vec4<f32>,     // x0, y0, x1, y1 in viewport pixels
    params: vec4<f32>,   // opacity, mip level, alpha from luminance (0/1)
};
@group(1) @binding(2) var<uniform> dp: Decal;

struct DecalOut {
    @location(0) mask: vec4<f32>,
    @location(1) color: vec4<f32>,
};

@fragment
fn fs_decal(i: StampOut) -> DecalOut {
    let clip = view.view_proj * vec4<f32>(i.world, 1.0);
    if (clip.w <= 0.0) { discard; }
    let ndc = clip.xyz / clip.w;
    let px = vec2<f32>((ndc.x * 0.5 + 0.5) * view.viewport.x, (0.5 - ndc.y * 0.5) * view.viewport.y);
    let uv = (px - dp.rect.xy) / max(dp.rect.zw - dp.rect.xy, vec2<f32>(1.0));
    if (any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0))) { discard; }
    if (px.x < 0.0 || px.y < 0.0 || px.x >= view.viewport.x || px.y >= view.viewport.y) { discard; }
    let scene = textureLoad(depth, vec2<i32>(px), 0);
    let near = view.viewport.z;
    if (near / max(ndc.z, 1e-9) > (near / max(scene, 1e-9)) * 1.004 + near * 2.0) { discard; }
    let facing = dot(normalize(i.normal), normalize(view.eye.xyz - i.world));
    let c = textureSampleLevel(decal, decal_samp, uv, dp.params.y);
    var a = c.a;
    if (dp.params.z > 0.5) { a = a * dot(c.rgb, vec3<f32>(0.299, 0.587, 0.114)); }
    let cov = a * dp.params.x * smoothstep(0.0, 0.25, facing);
    if (cov <= 0.002) { discard; }
    var o: DecalOut;
    o.mask = vec4<f32>(cov, 0.0, 0.0, 1.0);
    o.color = vec4<f32>(c.rgb, 1.0);
    return o;
}
