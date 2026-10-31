// ---------- curvature raster ----------
struct CurvIn {
    @location(0) uv: vec2<f32>,
    @location(1) bary: vec3<f32>,
    @location(2) heights: vec3<f32>,
    @location(3) convexity: vec3<f32>,
    @location(4) vcurv: f32,
};
struct CurvOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) bary: vec3<f32>,
    @location(1) @interpolate(flat) heights: vec3<f32>,
    @location(2) @interpolate(flat) convexity: vec3<f32>,
    @location(3) vcurv: f32,
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
    let k = (edge + i.vcurv * 0.5) * 2.0 * cp.strength;
    return vec4<f32>(0.5 + 0.5 * clamp(k, -1.0, 1.0), 0.0, 0.0, 1.0);
}

