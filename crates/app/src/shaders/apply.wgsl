// ---------- apply ----------
@group(0) @binding(0) var stroke_mask: texture_2d<f32>;
@group(0) @binding(1) var b_color: texture_2d<f32>;
@group(0) @binding(2) var b_rough: texture_2d<f32>;
@group(0) @binding(3) var b_metal: texture_2d<f32>;
@group(0) @binding(4) var b_height: texture_2d<f32>;
@group(0) @binding(5) var b_normal: texture_2d<f32>;
struct Brush {
    color: vec4<f32>,       // linear rgb
    rmh: vec4<f32>,         // roughness, metallic, height
    normal: vec4<f32>,      // unit tangent normal
    enabled: vec4<f32>,     // color, rough, metal, height (1/0)
    enabled2: vec4<f32>,    // normal, erase(1/0), mask value
};
@group(0) @binding(6) var<uniform> brush: Brush;

struct LayerOut {
    @location(0) color: vec4<f32>,
    @location(1) rough: vec4<f32>,
    @location(2) metal: vec4<f32>,
    @location(3) height: vec4<f32>,
    @location(4) normal: vec4<f32>,
};

// "Over" for straight alpha: paint value v with alpha m over (bv, ba).
fn over(bv: vec4<f32>, ba: f32, v: vec4<f32>, m: f32) -> vec4<f32> {
    let a = m + ba * (1.0 - m);
    let c = (v * m + bv * ba * (1.0 - m)) / max(a, 1e-6);
    return vec4<f32>(c.xyz, a);
}

fn apply1(enabled: f32, bv: vec4<f32>, ba: f32, v: vec4<f32>, m: f32) -> vec4<f32> {
    if (enabled < 0.5 || m <= 0.0) { return vec4<f32>(bv.xyz, ba); }
    if (brush.enabled2.y > 0.5) { return vec4<f32>(bv.xyz, ba * (1.0 - m)); } // erase
    return over(bv, ba, v, m);
}

@fragment
fn fs_apply(f: FullOut) -> LayerOut {
    let t = vec2<i32>(f.pos.xy);
    let m = textureLoad(stroke_mask, t, 0).r;
    let bc = textureLoad(b_color, t, 0);
    let br = textureLoad(b_rough, t, 0);
    let bm = textureLoad(b_metal, t, 0);
    let bh = textureLoad(b_height, t, 0);
    let bn = textureLoad(b_normal, t, 0);
    var o: LayerOut;
    o.color = apply1(brush.enabled.x, bc, bc.a, brush.color, m);
    let r = apply1(brush.enabled.y, vec4<f32>(br.r), br.g, vec4<f32>(brush.rmh.x), m);
    o.rough = vec4<f32>(r.x, r.w, 0.0, 1.0);
    let mm = apply1(brush.enabled.z, vec4<f32>(bm.r), bm.g, vec4<f32>(brush.rmh.y), m);
    o.metal = vec4<f32>(mm.x, mm.w, 0.0, 1.0);
    let h = apply1(brush.enabled.w, vec4<f32>(bh.r), bh.g, vec4<f32>(brush.rmh.z), m);
    o.height = vec4<f32>(h.x, h.w, 0.0, 1.0);
    o.normal = apply1(brush.enabled2.x, bn, bn.a, vec4<f32>(brush.normal.xyz * 0.5 + 0.5, 1.0), m);
    return o;
}

// Masks: lerp towards the brush's mask value (white paints in, black out).
@fragment
fn fs_apply_mask(f: FullOut) -> @location(0) vec4<f32> {
    let t = vec2<i32>(f.pos.xy);
    let m = textureLoad(stroke_mask, t, 0).r;
    let b = textureLoad(b_color, t, 0).r;
    return vec4<f32>(mix(b, brush.enabled2.z, m), 0.0, 0.0, 1.0);
}
