// Layer folders: blends a folder's sub-stack onto the stack below it.
// Appended to common.wgsl + composite.wgsl (reuses its bindings, generators
// and part selection).
//
//   group 1 (acc_*)   C: the stack below with the folder's children on top
//   group 2 (lp)      the folder's own params and mask
//   group 3 (base_*)  B: the stack below the folder
//
// out = blend(B, C, folder opacity x channel opacity x folder mask). With the
// Normal mode this is mix(B, C, a): the folder's opacity and mask multiply
// every child's. Height and normal always mix (C already contains B, so
// Add / Combine would count the stack below twice).

@group(3) @binding(0) var base_color: texture_2d<f32>;
@group(3) @binding(1) var base_rmh: texture_2d<f32>;
@group(3) @binding(2) var base_normal: texture_2d<f32>;
@group(3) @binding(3) var base_emissive: texture_2d<f32>;

fn folder_mask(t: vec2<i32>) -> f32 {
    var mask = 1.0;
    if (lp.flags.y == 1u) {
        mask = textureLoad(l_mask, t, 0).r;
        if (lp.flags.z != 0u) { mask *= generator(t); }
        if (lp.misc.x == 1u) {
            mask *= part_selected(src_texel(t));
        }
        if (lp.flags.w == 1u) { mask = 1.0 - mask; }
    }
    return mask;
}

@fragment
fn fs_folder(f: FullOut) -> Acc {
    let t = vec2<i32>(f.pos.xy);
    let bc4 = textureLoad(base_color, t, 0);   // a = opacity
    let br4 = textureLoad(base_rmh, t, 0);     // w = transmission
    let bc = bc4.rgb;
    let br = br4.xyz;
    let bn4 = textureLoad(base_normal, t, 0);    // packed normal xy, coat, flake
    let bn = acc_n(bn4);
    let be4 = textureLoad(base_emissive, t, 0);  // w = coat roughness
    let be = be4.rgb;
    let cc4 = textureLoad(acc_color, t, 0);
    let cr4 = textureLoad(acc_rmh, t, 0);
    let cc = cc4.rgb;
    let cr = cr4.xyz;
    let cn4 = textureLoad(acc_normal, t, 0);
    let cn = acc_n(cn4);
    let ce4 = textureLoad(acc_emissive, t, 0);
    let ce = ce4.rgb;

    let mask = folder_mask(t);
    let a = lp.opacity * mask;
    let an = clamp(lp.opacity2.x * mask, 0.0, 1.0);
    let ae = lp.opacity2.y * mask;
    let ao = lp.opacity2.z * mask;
    let at = lp.opacity2.w * mask;
    let acw = lp.coat_opacity.x * mask;
    let acr = lp.coat_opacity.y * mask;
    let afk = lp.coat_opacity.z * mask;

    var o: Acc;
    o.color = vec4<f32>(max(blend_rgb(lp.blend.x, bc, cc, a.x), vec3<f32>(0.0)), clamp(blend_scalar(lp.blend2.z, bc4.a, cc4.a, ao), 0.0, 1.0));
    o.rmh = vec4<f32>(
        clamp(blend_scalar(lp.blend.y, br.x, cr.x, a.y), 0.0, 1.0),
        clamp(blend_scalar(lp.blend.z, br.y, cr.y, a.z), 0.0, 1.0),
        clamp(blend_scalar(lp.blend.w, br.z, cr.z, a.w), -8.0, 8.0),
        clamp(blend_scalar(lp.blend2.w, br4.w, cr4.w, at), 0.0, 1.0));
    o.normal = pack_n(normalize(mix(bn, cn, an) + vec3<f32>(0.0, 0.0, 1e-5)),
        clamp(blend_scalar(lp.coat_blend.x, bn4.z, cn4.z, acw), 0.0, 1.0),
        clamp(blend_scalar(lp.coat_blend.z, bn4.w, cn4.w, afk), 0.0, 1.0));
    o.emissive = vec4<f32>(max(blend_rgb(lp.blend2.y, be, ce, ae), vec3<f32>(0.0)),
        clamp(blend_scalar(lp.coat_blend.y, be4.w, ce4.w, acr), 0.0, 1.0));
    return o;
}
