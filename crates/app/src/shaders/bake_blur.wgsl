// Separable gaussian blur of the curvature bake, seam-aware: taps that fall
// outside a UV island read through the jump-flood padding map.
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var nearest: texture_2d<u32>;
struct BlurParams { dir: vec2<i32>, radius: i32, size: i32 };
@group(0) @binding(2) var<uniform> bp: BlurParams;

fn tap(t: vec2<i32>) -> f32 {
    let c = clamp(t, vec2<i32>(0), vec2<i32>(bp.size - 1));
    let s = textureLoad(nearest, c, 0).xy;
    var q = c;
    if (s.x != 65535u) { q = vec2<i32>(s); }
    return textureLoad(src, q, 0).r;
}

@fragment
fn fs_blur(f: FullOut) -> @location(0) vec4<f32> {
    let t = vec2<i32>(f.pos.xy);
    let sigma = max(f32(bp.radius) * 0.5, 0.5);
    var sum = 0.0;
    var w = 0.0;
    for (var k = -bp.radius; k <= bp.radius; k++) {
        let g = exp(-f32(k * k) / (2.0 * sigma * sigma));
        sum += tap(t + bp.dir * k) * g;
        w += g;
    }
    return vec4<f32>(sum / w, 0.0, 0.0, 1.0);
}
