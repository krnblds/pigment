// Specular prefiltering of an equirectangular environment.
// Mip m of the output holds the environment convolved with a GGX lobe of
// roughness m / (mips - 1): the "prefiltered radiance" half of the split-sum
// approximation. Uses filtered importance sampling (sampling source mips by
// the sample's solid angle) so 64 samples per texel come out noise-free.

@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var samp: sampler;
struct Pre { roughness: f32, src_width: f32, src_mips: f32, _a: f32 };
@group(0) @binding(2) var<uniform> pre: Pre;

fn dir_from_uv(uv: vec2<f32>) -> vec3<f32> {
    let phi = uv.x * 2.0 * PI - PI;
    let theta = uv.y * PI;
    return vec3<f32>(sin(theta) * sin(phi), cos(theta), -sin(theta) * cos(phi));
}

fn uv_from_dir(d: vec3<f32>) -> vec2<f32> {
    let phi = atan2(d.x, -d.z);
    let theta = acos(clamp(d.y, -1.0, 1.0));
    return vec2<f32>((phi + PI) / (2.0 * PI), theta / PI);
}

fn hammersley(i: u32, n: u32) -> vec2<f32> {
    return vec2<f32>(f32(i) / f32(n), f32(reverseBits(i)) * 2.3283064e-10);
}

@fragment
fn fs_prefilter(f: FullOut) -> @location(0) vec4<f32> {
    let n = dir_from_uv(f.uv);
    if (pre.roughness <= 0.0) {
        return vec4<f32>(textureSampleLevel(src, samp, f.uv, 0.0).rgb, 1.0);
    }
    let up = select(vec3<f32>(0.0, 1.0, 0.0), vec3<f32>(1.0, 0.0, 0.0), abs(n.y) > 0.999);
    let tx = normalize(cross(up, n));
    let ty = cross(n, tx);
    let a = pre.roughness * pre.roughness;
    let count = 64u;
    // solid angle of one source texel (equirect, averaged)
    let omega_p = 4.0 * PI / (pre.src_width * pre.src_width * 0.5);
    var sum = vec3<f32>(0.0);
    var w = 0.0;
    for (var i = 0u; i < count; i++) {
        let xi = hammersley(i, count);
        let phi = 2.0 * PI * xi.x;
        let ct = sqrt((1.0 - xi.y) / (1.0 + (a * a - 1.0) * xi.y));
        let st = sqrt(1.0 - ct * ct);
        let h = normalize(tx * (st * cos(phi)) + ty * (st * sin(phi)) + n * ct);
        let l = 2.0 * dot(n, h) * h - n;
        let nl = dot(n, l);
        if (nl > 0.0) {
            // pdf for N = V: D(h) / 4
            let nh = max(dot(n, h), 0.0);
            let d = a * a / (PI * pow(nh * nh * (a * a - 1.0) + 1.0, 2.0));
            let pdf = d / 4.0 + 1e-4;
            let omega_s = 1.0 / (f32(count) * pdf);
            let lod = clamp(0.5 * log2(omega_s / omega_p) + 1.0, 0.0, pre.src_mips - 1.0);
            sum += textureSampleLevel(src, samp, uv_from_dir(l), lod).rgb * nl;
            w += nl;
        }
    }
    return vec4<f32>(sum / max(w, 1e-4), 1.0);
}
