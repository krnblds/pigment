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
    // rain exposure: near-vertical directions, weighted towards straight up,
    // counted whichever way the surface faces (a wall gets rain from its side)
    let rain_w = max(l.y - 0.35, 0.0);
    if (c <= 0.0 && rain_w <= 0.0) { discard; }
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
    var sky = 0.0;
    for (var k = 0; k < 4; k++) {
        let o = vec2<f32>(f32(k & 1), f32(k >> 1));
        let q = clamp(vec2<i32>(base + o), vec2<i32>(0), vec2<i32>(dims) - 1);
        let d = textureLoad(shadow, q, 0);
        let gap = (clip.z - d) * light.range.x;
        let occluded = clip.z > d + 1e-5 && gap < light.range.y;
        let w = mix(1.0 - fr.x, fr.x, o.x) * mix(1.0 - fr.y, fr.y, o.y);
        vis += select(1.0, 0.0, occluded) * w;
        // rain is stopped by any occluder, however far
        sky += select(1.0, 0.0, clip.z > d + 1e-5) * w;
    }
    let ca = max(c, 0.0);
    return vec4<f32>(vis * ca, ca, sky * rain_w, rain_w);
}

// ---------- drip map ----------
// How far below the nearest protrusion (sill, AC unit, ledge, eave) each wall
// texel is. The mesh is cut into horizontal slices; for each slice an
// orthographic depth map looks straight up from the slice top (`dir.x`), so
// it holds the lowest surface above it within `range.x` metres. Texels in
// the band [top - step, top) (`dir.y` = step) look up the column just outside
// their wall (pushed out by `dir.z` along the horizontal normal): anything
// found there sticks out of the wall above them. Output: 1 / (1 + gap metres),
// 0 = nothing above.
@fragment
fn fs_drip(f: FullOut) -> @location(0) vec4<f32> {
    let t = vec2<i32>(f.pos.xy);
    let p = textureLoad(position, t, 0);
    if (p.w < 0.5) { discard; }
    let top = light.dir.x;
    if (p.y >= top || p.y < top - light.dir.y) { discard; }
    let n = normalize(textureLoad(wnormal, t, 0).xyz);
    let nh = vec2<f32>(n.x, n.z);
    if (abs(n.y) > 0.75 || length(nh) < 1e-3) { return vec4<f32>(0.0); }
    let o = normalize(nh) * light.dir.z;
    let q = vec3<f32>(p.x + o.x, top, p.z + o.y);
    let clip = light.view_proj * vec4<f32>(q, 1.0);
    let uv = vec2<f32>(clip.x * 0.5 + 0.5, 0.5 - clip.y * 0.5);
    let dims = vec2<i32>(textureDimensions(shadow));
    let c = vec2<i32>(uv * vec2<f32>(dims));
    // nearest surface over a 2x2 footprint
    var d = 1.0;
    for (var k = 0; k < 4; k++) {
        let qq = clamp(c + vec2<i32>(k & 1, k >> 1) - vec2<i32>(1), vec2<i32>(0), dims - 1);
        d = min(d, textureLoad(shadow, qq, 0));
    }
    if (d >= 0.9999) { return vec4<f32>(0.0); }
    let gap = max(top + d * light.range.x - p.y, 0.0);
    return vec4<f32>(1.0 / (1.0 + gap), 0.0, 0.0, 1.0);
}

