// ---------- resolve: AO sum / weight + curvature, padded through the jump-flood map ----------
@group(0) @binding(0) var ao_acc: texture_2d<f32>;
@group(0) @binding(1) var curv: texture_2d<f32>;
@group(0) @binding(2) var nearest: texture_2d<u32>;

@fragment
fn fs_resolve(f: FullOut) -> @location(0) vec4<f32> {
    var t = vec2<i32>(f.pos.xy);
    let s = textureLoad(nearest, t, 0).xy;
    if (s.x != 65535u) { t = vec2<i32>(s); }
    let a = textureLoad(ao_acc, t, 0);
    let ao = select(1.0, a.x / a.y, a.y > 1e-4);
    return vec4<f32>(ao, textureLoad(curv, t, 0).r, 0.0, 1.0);
}
