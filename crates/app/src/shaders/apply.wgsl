// ---------- apply ----------
@group(0) @binding(0) var stroke_mask: texture_2d<f32>;
@group(0) @binding(1) var b_color: texture_2d<f32>;
@group(0) @binding(2) var b_rough: texture_2d<f32>;
@group(0) @binding(3) var b_metal: texture_2d<f32>;
@group(0) @binding(4) var b_height: texture_2d<f32>;
@group(0) @binding(5) var b_normal: texture_2d<f32>;
@group(0) @binding(6) var b_emissive: texture_2d<f32>;
struct Brush {
    color: vec4<f32>,       // linear rgb
    rmh: vec4<f32>,         // roughness, metallic, height
    normal: vec4<f32>,      // unit tangent normal
    enabled: vec4<f32>,     // color, rough, metal, height (1/0)
    enabled2: vec4<f32>,    // normal, erase(1/0), mask value
    emissive: vec4<f32>,    // linear rgb x strength
    enabled3: vec4<f32>,    // emissive, decal mode (1/0)
    extra: vec4<f32>,       // opacity value, transmission value, opacity on, transmission on
    coat: vec4<f32>,        // clearcoat, coat roughness, flake values
    coat_on: vec4<f32>,     // clearcoat, coat roughness, flake on
};
@group(0) @binding(7) var<uniform> brush: Brush;
@group(0) @binding(8) var decal_col: texture_2d<f32>;   // decal colour per texel (decal mode)
@group(0) @binding(9) var b_opacity: texture_2d<f32>;
@group(0) @binding(10) var b_transmission: texture_2d<f32>;
@group(0) @binding(11) var b_coat: texture_2d<f32>;
@group(0) @binding(12) var b_coat_rough: texture_2d<f32>;
@group(0) @binding(13) var b_flake: texture_2d<f32>;

struct LayerOut {
    @location(0) color: vec4<f32>,
    @location(1) rough: vec4<f32>,
    @location(2) metal: vec4<f32>,
    @location(3) height: vec4<f32>,
    @location(4) normal: vec4<f32>,
    @location(5) emissive: vec4<f32>,
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
    // decal mode: colour (and emission) come from the image, tinted by the brush
    var paint_col = brush.color;
    var emit = brush.emissive.rgb;
    if (brush.enabled3.y > 0.5) {
        let d = textureLoad(decal_col, t, 0).rgb;
        paint_col = vec4<f32>(d * brush.color.rgb, 1.0);
        emit = d * brush.emissive.rgb;
    }
    o.color = apply1(brush.enabled.x, bc, bc.a, paint_col, m);
    let r = apply1(brush.enabled.y, vec4<f32>(br.r), br.g, vec4<f32>(brush.rmh.x), m);
    o.rough = vec4<f32>(r.x, r.w, 0.0, 1.0);
    let mm = apply1(brush.enabled.z, vec4<f32>(bm.r), bm.g, vec4<f32>(brush.rmh.y), m);
    o.metal = vec4<f32>(mm.x, mm.w, 0.0, 1.0);
    let h = apply1(brush.enabled.w, vec4<f32>(bh.r), bh.g, vec4<f32>(brush.rmh.z), m);
    o.height = vec4<f32>(h.x, h.w, 0.0, 1.0);
    o.normal = apply1(brush.enabled2.x, bn, bn.a, vec4<f32>(brush.normal.xyz * 0.5 + 0.5, 1.0), m);
    let be = textureLoad(b_emissive, t, 0);
    o.emissive = apply1(brush.enabled3.x, be, be.a, vec4<f32>(emit, 1.0), m);
    return o;
}

// Opacity and transmission: a second pass (the main one is at the
// colour-attachment byte limit). Value + coverage, like roughness.
struct ExtraOut {
    @location(0) opacity: vec4<f32>,
    @location(1) transmission: vec4<f32>,
    @location(2) coat: vec4<f32>,
    @location(3) coat_rough: vec4<f32>,
    @location(4) flake: vec4<f32>,
};

@fragment
fn fs_apply_extra(f: FullOut) -> ExtraOut {
    let t = vec2<i32>(f.pos.xy);
    let m = textureLoad(stroke_mask, t, 0).r;
    let bo = textureLoad(b_opacity, t, 0);
    let bt = textureLoad(b_transmission, t, 0);
    var o: ExtraOut;
    let a = apply1(brush.extra.z, vec4<f32>(bo.r), bo.g, vec4<f32>(brush.extra.x), m);
    o.opacity = vec4<f32>(a.x, a.w, 0.0, 1.0);
    let tr = apply1(brush.extra.w, vec4<f32>(bt.r), bt.g, vec4<f32>(brush.extra.y), m);
    o.transmission = vec4<f32>(tr.x, tr.w, 0.0, 1.0);
    let bcw = textureLoad(b_coat, t, 0);
    let bcr = textureLoad(b_coat_rough, t, 0);
    let bfk = textureLoad(b_flake, t, 0);
    let cw = apply1(brush.coat_on.x, vec4<f32>(bcw.r), bcw.g, vec4<f32>(brush.coat.x), m);
    o.coat = vec4<f32>(cw.x, cw.w, 0.0, 1.0);
    let cr = apply1(brush.coat_on.y, vec4<f32>(bcr.r), bcr.g, vec4<f32>(brush.coat.y), m);
    o.coat_rough = vec4<f32>(cr.x, cr.w, 0.0, 1.0);
    let fk = apply1(brush.coat_on.z, vec4<f32>(bfk.r), bfk.g, vec4<f32>(brush.coat.z), m);
    o.flake = vec4<f32>(fk.x, fk.w, 0.0, 1.0);
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
