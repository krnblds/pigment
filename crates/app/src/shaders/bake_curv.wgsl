// ---------- curvature raster ----------
struct CurvIn {
    @location(0) uv: vec2<f32>,
    @location(1) bary: vec3<f32>,
    @location(2) heights: vec3<f32>,
    @location(3) convexity: vec3<f32>,
    @location(4) vcurv: vec3<f32>,
};
struct CurvOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) bary: vec3<f32>,
    @location(1) @interpolate(flat) heights: vec3<f32>,
    @location(2) @interpolate(flat) convexity: vec3<f32>,
    @location(3) @interpolate(flat) vcurv: vec3<f32>,
};
struct CurvParams { radius: f32, strength: f32, _a: f32, _b: f32 };
@group(0) @binding(0) var<uniform> cp: CurvParams;

@vertex
fn vs_curv(v: CurvIn) -> CurvOut {
    var o: CurvOut;
    o.pos = uv_to_clip(v.uv);
    o.bary = v.bary;
    o.heights = v.heights;
    o.convexity = v.convexity;
    o.vcurv = v.vcurv;
    return o;
}

@fragment
fn fs_curv(i: CurvOut) -> @location(0) vec4<f32> {
    // distance from this texel to each triangle edge = barycentric * height
    let dist = i.bary * i.heights;
    let fade = clamp(vec3<f32>(1.0) - dist / max(cp.radius, 1e-6), vec3<f32>(0.0), vec3<f32>(1.0));
    let edge = dot(i.convexity, fade * fade);
    // hard edges: dihedral angle, faded over the edge width;
    // bevels / smooth surfaces: curvature x edge width (dimensionless)
    // Vertex curvature is faded by distance from each corner (approximated by
    // (1 - bary) x height) instead of plain interpolation: a large flat triangle
    // touching a bevel must not inherit the bevel's curvature across its whole
    // area. On dense meshes the fade is ~1 and this is ordinary interpolation.
    let dv = (vec3<f32>(1.0) - i.bary) * i.heights;
    let wv = clamp(vec3<f32>(1.0) - dv / max(cp.radius * 1.5, 1e-6), vec3<f32>(0.0), vec3<f32>(1.0));
    let vc = dot(i.vcurv * wv, i.bary);
    let k = (edge * 2.0 + vc * cp.radius) * cp.strength;
    return vec4<f32>(0.5 + 0.5 * clamp(k, -1.0, 1.0), 0.0, 0.0, 1.0);
}

