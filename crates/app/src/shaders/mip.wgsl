// ---------- Mip generation: 2x2 box downsample ----------
@group(0) @binding(0) var mip_src: texture_2d<f32>;
@group(0) @binding(1) var mip_samp: sampler;

@fragment
fn fs_mip(f: FullOut) -> @location(0) vec4<f32> {
    // sampling at the centre of the 2x2 block with bilinear = box filter
    return textureSampleLevel(mip_src, mip_samp, f.uv, 0.0);
}
