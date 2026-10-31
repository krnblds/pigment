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
    params: vec4<f32>,        // hardness
};
@group(0) @binding(2) var<storage, read> stamps: array<Stamp>;

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

@fragment
fn fs_stamp(i: StampOut) -> @location(0) vec4<f32> {
    let clip = view.view_proj * vec4<f32>(i.world, 1.0);
    if (clip.w <= 0.0) { discard; }
    let ndc = clip.xyz / clip.w;
    let px = vec2<f32>((ndc.x * 0.5 + 0.5) * view.viewport.x, (0.5 - ndc.y * 0.5) * view.viewport.y);
    if (px.x < 0.0 || px.y < 0.0 || px.x >= view.viewport.x || px.y >= view.viewport.y) { discard; }

    // Brush coverage first (cheap), visibility only if something is under the brush.
    var f = 0.0;
    let count = u32(view.viewport.w);
    for (var k = 0u; k < count; k++) {
        let s = stamps[k];
        let d = length(px - s.center_radius.xy) / max(s.center_radius.z, 0.5);
        f = max(f, falloff(d, s.params.x) * s.center_radius.w);
    }
    if (f <= 0.0) { discard; }

    // Occlusion: compare linear depths (reverse-Z: depth = near / view_z).
    let scene = textureLoad(depth, vec2<i32>(px), 0);
    let near = view.viewport.z;
    let z_frag = near / max(ndc.z, 1e-9);
    let z_scene = near / max(scene, 1e-9);
    if (z_frag > z_scene * 1.004 + near * 2.0) { discard; }

    // Fade out on surfaces seen edge-on so strokes don't smear along silhouettes.
    let n = normalize(i.normal);
    let facing = dot(n, normalize(view.eye.xyz - i.world));
    f *= smoothstep(0.0, 0.25, facing);
    return vec4<f32>(f, 0.0, 0.0, 1.0);
}

