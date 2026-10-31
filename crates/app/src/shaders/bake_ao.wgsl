// Mesh map bakers: ambient occlusion and curvature.
//
// AO: for each of N directions over the sphere we render an orthographic
// depth map of the mesh as seen from that direction, then every texel checks
// whether its world position is visible in that map (shadow-mapping with many
// lights). Summing cosine-weighted visibility over the hemisphere around the
// texel's normal gives ambient occlusion with no ray-tracing hardware.

struct Light {
    view_proj: mat4x4<f32>,
    dir: vec4<f32>,      // xyz = direction towards the light, w = normal offset
    range: vec4<f32>,    // x = world size of the depth range, y = max occluder distance
};
@group(0) @binding(0) var<uniform> light: Light;

@vertex
fn vs_ao_depth(v: MeshIn) -> @builtin(position) vec4<f32> {
    return light.view_proj * vec4<f32>(v.position, 1.0);
}

@group(0) @binding(1) var shadow: texture_depth_2d;
@group(0) @binding(2) var shadow_samp: sampler_comparison;
@group(0) @binding(3) var position: texture_2d<f32>;
@group(0) @binding(4) var wnormal: texture_2d<f32>;

@fragment
fn fs_ao_accum(f: FullOut) -> @location(0) vec4<f32> {
    let t = vec2<i32>(f.pos.xy);
    let p = textureLoad(position, t, 0);
    if (p.w < 0.5) { discard; }
    let n = normalize(textureLoad(wnormal, t, 0).xyz);
    let l = light.dir.xyz;
    let c = dot(n, l);
    if (c <= 0.0) { discard; }
    // normal offset to avoid self-shadowing acne
    let wp = p.xyz + n * light.dir.w;
    let clip = light.view_proj * vec4<f32>(wp, 1.0);
    let uv = vec2<f32>(clip.x * 0.5 + 0.5, 0.5 - clip.y * 0.5);
    // Ortho depth 0 = nearest the light. A texel is occluded if the map holds
    // something nearer the light, but only if that occluder is within the max
    // distance (approximate: the map only stores the first hit from the light).
    // 2x2 bilinear-weighted taps, like hardware PCF.
    let dims = vec2<f32>(textureDimensions(shadow));
    let st = uv * dims - 0.5;
    let base = floor(st);
    let fr = st - base;
    var vis = 0.0;
    for (var k = 0; k < 4; k++) {
        let o = vec2<f32>(f32(k & 1), f32(k >> 1));
        let q = clamp(vec2<i32>(base + o), vec2<i32>(0), vec2<i32>(dims) - 1);
        let d = textureLoad(shadow, q, 0);
        let gap = (clip.z - d) * light.range.x;
        let occluded = clip.z > d + 1e-5 && gap < light.range.y;
        let w = mix(1.0 - fr.x, fr.x, o.x) * mix(1.0 - fr.y, fr.y, o.y);
        vis += select(1.0, 0.0, occluded) * w;
    }
    return vec4<f32>(vis * c, c, 0.0, 0.0);
}

