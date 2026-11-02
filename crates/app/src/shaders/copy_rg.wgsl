// High-to-low bake results into the mesh bakes: AO and curvature from the
// high mesh replace bakes.r / bakes.g (the pipeline's write mask keeps the
// drip and rain-exposure bakes in b / a).
@group(0) @binding(0) var src: texture_2d<f32>;  // r = AO, g = curvature

@fragment
fn fs_copy_rg(f: FullOut) -> @location(0) vec4<f32> {
    let v = textureLoad(src, vec2<i32>(f.pos.xy), 0);
    return vec4<f32>(v.r, v.g, 0.0, 1.0);
}
