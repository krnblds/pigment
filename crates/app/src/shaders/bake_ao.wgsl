// Mesh map bakers: ambient occlusion and curvature.
//
// AO: for each of N directions over the sphere we render an orthographic
// depth map of the mesh as seen from that direction, then every texel checks
// whether its world position is visible in that map (shadow-mapping with many
// lights). Summing cosine-weighted visibility over the hemisphere around the
// texel's normal gives ambient occlusion with no ray-tracing hardware.

struct Light {
    view_proj: mat4x4<f32>,
    dir: vec4<f32>,      // xyz = direction towards the light, w = depth bias
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
    // ortho depth 0 = nearest the light; visible if not farther than the map (LessEqual)
    let vis = textureSampleCompareLevel(shadow, shadow_samp, uv, clip.z);
    return vec4<f32>(vis * c, c, 0.0, 0.0);
}

