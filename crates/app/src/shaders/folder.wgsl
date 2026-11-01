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
    let bc = textureLoad(base_color, t, 0).rgb;
    let br = textureLoad(base_rmh, t, 0).xyz;
    let bn = textureLoad(base_normal, t, 0).xyz;
    let be = textureLoad(base_emissive, t, 0).rgb;
    let cc = textureLoad(acc_color, t, 0).rgb;
    let cr = textureLoad(acc_rmh, t, 0).xyz;
    let cn = textureLoad(acc_normal, t, 0).xyz;
    let ce = textureLoad(acc_emissive, t, 0).rgb;

    let mask = folder_mask(t);
    let a = lp.opacity * mask;
    let an = clamp(lp.opacity2.x * mask, 0.0, 1.0);
    let ae = lp.opacity2.y * mask;

    var o: Acc;
    o.color = vec4<f32>(max(blend_rgb(lp.blend.x, bc, cc, a.x), vec3<f32>(0.0)), 1.0);
    o.rmh = vec4<f32>(
        clamp(blend_scalar(lp.blend.y, br.x, cr.x, a.y), 0.0, 1.0),
        clamp(blend_scalar(lp.blend.z, br.y, cr.y, a.z), 0.0, 1.0),
        clamp(blend_scalar(lp.blend.w, br.z, cr.z, a.w), -8.0, 8.0),
        1.0);
    o.normal = vec4<f32>(normalize(mix(bn, cn, an) + vec3<f32>(0.0, 0.0, 1e-5)), 1.0);
    o.emissive = vec4<f32>(max(blend_rgb(lp.blend2.y, be, ce, ae), vec3<f32>(0.0)), 1.0);
    return o;
}
