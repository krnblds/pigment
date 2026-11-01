// Viewport: metallic/roughness PBR lit by an HDRI (split-sum IBL + SH9
// diffuse) into an HDR target (post.wgsl adds bloom and tone maps), plus
// channel/debug views.

struct Globals {
    view_proj: mat4x4<f32>,
    inv_view_proj: mat4x4<f32>,
    eye: vec4<f32>,
    params: vec4<f32>,   // x view mode, y exposure (EV), z env rotation (rad), w env mips
    params2: vec4<f32>,  // x show env background (0/1), y background blur lod, z bake ready, w emission scale
    sh: array<vec4<f32>, 9>,
    // lightbox stage, see stage.wgsl ([1].w = 1: mirrored reflection pass)
    stage: array<vec4<f32>, 6>,
};
@group(0) @binding(0) var<uniform> g: Globals;

@group(1) @binding(0) var env: texture_2d<f32>;
@group(1) @binding(1) var brdf_lut: texture_2d<f32>;
@group(1) @binding(2) var env_samp: sampler;

@group(2) @binding(0) var m_color: texture_2d<f32>;
@group(2) @binding(1) var m_orm: texture_2d<f32>;
@group(2) @binding(2) var m_normal: texture_2d<f32>;
@group(2) @binding(3) var m_height: texture_2d<f32>;
@group(2) @binding(4) var m_bakes: texture_2d<f32>;
@group(2) @binding(5) var m_wnormal: texture_2d<f32>;
@group(2) @binding(6) var m_emissive: texture_2d<f32>;
@group(2) @binding(7) var m_samp: sampler;
@group(2) @binding(8) var m_coat: texture_2d<f32>;   // r clearcoat, g coat roughness, b flake

// Metallic flake: each ~0.4 mm world cell tilts the base normal a random
// way, so the base specular sparkles under the coat.
fn hash33(p: vec3<f32>) -> vec3<f32> {
    var q = fract(p * vec3<f32>(0.1031, 0.1030, 0.0973));
    q += dot(q, q.yxz + 33.33);
    return fract((q.xxy + q.yxx) * q.zyx);
}

fn flake_normal(n: vec3<f32>, world: vec3<f32>, amount: f32) -> vec3<f32> {
    if (amount <= 0.0) { return n; }
    let h = hash33(floor(world * 2500.0)) * 2.0 - 1.0;
    return normalize(n + h * (0.45 * amount));
}

// Clearcoat lobe (dielectric, F0 0.04) over the base: rgb = its reflection,
// a = how much of the base it hides (coat x Fresnel).
fn coat_layer(n: vec3<f32>, ng: vec3<f32>, v: vec3<f32>, coat: f32, coat_rough: f32, ao: f32) -> vec4<f32> {
    if (coat <= 0.0) { return vec4<f32>(0.0); }
    let cr = clamp(coat_rough, 0.02, 1.0);
    let nv = clamp(dot(n, v), 1e-4, 1.0);
    let r0 = reflect(-v, n);
    let r = normalize(mix(n, r0, (1.0 - cr) * (sqrt(1.0 - cr) + cr)));
    let env_c = env_radiance(r, cr * (g.params.w - 1.0));
    let lut_uv = clamp(vec2<f32>(nv, cr), vec2<f32>(0.5 / 64.0), vec2<f32>(1.0 - 0.5 / 64.0));
    let ab = textureSampleLevel(brdf_lut, env_samp, lut_uv, 0.0).rg;
    let fc = 0.04 + (max(1.0 - cr, 0.04) - 0.04) * pow(1.0 - nv, 5.0);
    let e = fc * ab.x + ab.y;
    let horizon = clamp(1.0 + dot(r0, ng), 0.0, 1.0);
    let so = clamp(pow(nv + ao, exp2(-16.0 * cr - 1.0)) - 1.0 + ao, 0.0, 1.0);
    return vec4<f32>(env_c * e * so * horizon * coat, clamp(coat * fc, 0.0, 1.0));
}

struct VsOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) tangent: vec4<f32>,
};

@vertex
fn vs_mesh(v: MeshIn) -> VsOut {
    var o: VsOut;
    o.clip = g.view_proj * vec4<f32>(v.position, 1.0);
    o.world = v.position;
    o.normal = v.normal;
    o.uv = v.uv;
    o.tangent = v.tangent;
    return o;
}

@vertex
fn vs_depth(v: MeshIn) -> @builtin(position) vec4<f32> {
    return g.view_proj * vec4<f32>(v.position, 1.0);
}

fn rotate_y(d: vec3<f32>, a: f32) -> vec3<f32> {
    let c = cos(a);
    let s = sin(a);
    return vec3<f32>(c * d.x + s * d.z, d.y, -s * d.x + c * d.z);
}

fn uv_from_dir(d: vec3<f32>) -> vec2<f32> {
    let phi = atan2(d.x, -d.z);
    let theta = acos(clamp(d.y, -1.0, 1.0));
    return vec2<f32>((phi + PI) / (2.0 * PI), theta / PI);
}

fn env_radiance(d: vec3<f32>, lod: f32) -> vec3<f32> {
    return textureSampleLevel(env, env_samp, uv_from_dir(rotate_y(d, g.params.z)), lod).rgb;
}

fn sh_irradiance(n0: vec3<f32>) -> vec3<f32> {
    let n = rotate_y(n0, g.params.z);
    let b = array<f32, 9>(
        0.282095, 0.488603 * n.y, 0.488603 * n.z, 0.488603 * n.x,
        1.092548 * n.x * n.y, 1.092548 * n.y * n.z, 0.315392 * (3.0 * n.z * n.z - 1.0),
        1.092548 * n.x * n.z, 0.546274 * (n.x * n.x - n.y * n.y));
    var e = vec3<f32>(0.0);
    for (var i = 0; i < 9; i++) { e += g.sh[i].xyz * b[i]; }
    return max(e, vec3<f32>(0.0));
}

// Output helpers. The viewport renders into an HDR target that `post.wgsl`
// tone maps (and blooms). Alpha tells post how to treat the pixel:
// 1 = scene-referred radiance (exposure applied here), 0 = display-referred
// values (channel views), shown as they are.
fn hdr(c: vec3<f32>) -> vec4<f32> {
    return vec4<f32>(c * exp2(g.params.y), 1.0);
}

fn ldr(c: vec3<f32>) -> vec4<f32> {
    return vec4<f32>(c, 0.0);
}

fn checker(uv: vec2<f32>) -> vec3<f32> {
    let c = floor(uv * 16.0);
    let odd = (i32(c.x) + i32(c.y)) & 1;
    let tint = mix(vec3<f32>(0.85, 0.55, 0.35), vec3<f32>(0.35, 0.6, 0.85), step(0.5, uv.x));
    let base = mix(tint, tint.zyx, step(0.5, uv.y));
    return select(base * 0.9, vec3<f32>(0.9), odd == 1);
}

// Multi-bounce ambient occlusion (Jimenez et al. 2016, GTAO): light bounces
// between bright surfaces, so occlusion darkens light albedos less.
fn ao_multibounce(ao: f32, albedo: vec3<f32>) -> vec3<f32> {
    let a = 2.0404 * albedo - 0.3324;
    let b = -4.7951 * albedo + 0.6417;
    let c = 2.7552 * albedo + 0.6903;
    return max(vec3<f32>(ao), ((ao * a + b) * ao + c) * ao);
}

// A shaded texel: `c` is what the HDR target gets (alpha = scene- vs
// display-referred tag, see post.wgsl), `cover` how much of what's behind it
// the surface hides (1 = solid; < 1 = cut-out or glass).
struct Shaded {
    c: vec4<f32>,
    cover: f32,
};

fn solid(c: vec4<f32>) -> Shaded {
    return Shaded(c, 1.0);
}

// Opaque pass: solid texels only (see-through ones go to fs_mesh_glass).
@fragment
fn fs_mesh(i: VsOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    let s = shade(i, front);
    if (s.cover < 0.996) { discard; }
    return s.c;
}

// Transparent pass: premultiplied HDR colour, a = how much of what's behind
// is hidden. The pipeline keeps the target's alpha (the display tag).
@fragment
fn fs_mesh_glass(i: VsOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    let s = shade(i, front);
    if (s.cover >= 0.996) { discard; }
    return vec4<f32>(s.c.rgb, s.cover);
}

// Model mirrored in the lightbox floor (stage.wgsl): shaded as seen from the
// mirrored eye, faded with depth below the floor; premultiplied, a = coverage.
@fragment
fn fs_mesh_mirror(i: VsOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    let s = shade(i, front);
    if (s.cover < 0.5) { discard; }
    let below = max(i.world.y - g.stage[0].y, 0.0);
    let fade = exp(-below / max(g.stage[3].w, 1e-4));
    return vec4<f32>(s.c.rgb * exp2(-g.params.y) * fade, fade);
}

fn shade(i: VsOut, front_in: bool) -> Shaded {
    // the mirror pass flips the winding
    let front = front_in != (g.stage[1].w > 0.5);
    // flake cells (0.4 mm) smaller than a pixel only alias into salt noise:
    // fade them out as the pixel footprint grows past a cell
    let flake_fade = clamp(1.5 - length(fwidth(i.world)) * 2500.0, 0.0, 1.0);
    var ng = normalize(i.normal);
    if (!front) { ng = -ng; }
    let mode = i32(g.params.x);

    let albedo4 = textureSample(m_color, m_samp, i.uv);
    let albedo = albedo4.rgb;
    let orm = textureSample(m_orm, m_samp, i.uv);
    let tn = textureSample(m_normal, m_samp, i.uv).xyz * 2.0 - 1.0;

    // tangent frame; bitangent points up the image (OpenGL normal maps)
    let t = normalize(i.tangent.xyz - ng * dot(ng, i.tangent.xyz));
    let b = cross(ng, t) * i.tangent.w;
    var n = normalize(t * tn.x + b * tn.y + ng * tn.z);
    let coat4 = textureSample(m_coat, m_samp, i.uv);

    switch mode {
        case 1: { return solid(ldr(albedo)); }
        case 2: { return solid(ldr(vec3<f32>(orm.g * orm.g))); }       // roughness (shown perceptually)
        case 3: { return solid(ldr(vec3<f32>(orm.b * orm.b))); }       // metallic
        case 4: {
            let h = textureSample(m_height, m_samp, i.uv).r * 0.5 + 0.5;
            return solid(ldr(srgb_to_linear(vec3<f32>(h))));
        }
        case 5: { return solid(ldr(srgb_to_linear(tn * 0.5 + 0.5))); }   // tangent normal
        case 6: { return solid(ldr(srgb_to_linear(vec3<f32>(textureSample(m_bakes, m_samp, i.uv).r)))); }
        case 7: { return solid(ldr(srgb_to_linear(vec3<f32>(textureSample(m_bakes, m_samp, i.uv).g)))); }
        case 8: { return solid(ldr(srgb_to_linear(textureSample(m_wnormal, m_samp, i.uv).xyz * 0.5 + 0.5))); }
        case 10: { return solid(hdr(textureSample(m_emissive, m_samp, i.uv).rgb)); }
        case 11: { return solid(ldr(srgb_to_linear(vec3<f32>(albedo4.a)))); }   // opacity
        case 12: { return solid(ldr(srgb_to_linear(vec3<f32>(orm.a)))); }       // transmission
        case 13: { return solid(ldr(srgb_to_linear(vec3<f32>(coat4.r)))); }     // clearcoat
        case 14: { return solid(ldr(srgb_to_linear(vec3<f32>(coat4.g)))); }     // coat roughness
        case 15: { return solid(ldr(srgb_to_linear(vec3<f32>(coat4.b)))); }     // flake
        case 9: {
            let l = max(dot(ng, normalize(g.eye.xyz - i.world)), 0.0);
            return solid(ldr(checker(i.uv) * (0.25 + 0.75 * l)));
        }
        default: {}
    }

    // --- metallic/roughness PBR, split-sum image-based lighting ---
    let n_coat = n;
    n = flake_normal(n, i.world, coat4.b * flake_fade);
    let rough = clamp(orm.g, 0.03, 1.0);
    let metal = orm.b;
    let ao = orm.r;
    let v = normalize(g.eye.xyz - i.world);
    let nv = clamp(dot(n, v), 1e-4, 1.0);
    let f0 = mix(vec3<f32>(0.04), albedo, metal);
    let r0 = reflect(-v, n);
    // Rough lobes lean towards the normal (Lagarde & de Rousiers 2014): fetch
    // the prefiltered radiance along the lobe's dominant direction.
    let r = normalize(mix(n, r0, (1.0 - rough) * (sqrt(1.0 - rough) + rough)));
    // Mip m of the prefiltered map holds roughness m / (mips - 1).
    let spec_env = env_radiance(r, rough * (g.params.w - 1.0));
    // Clamp into the LUT's texel centres: the env sampler repeats in u.
    let lut_uv = clamp(vec2<f32>(nv, rough), vec2<f32>(0.5 / 64.0), vec2<f32>(1.0 - 0.5 / 64.0));
    let ab = textureSampleLevel(brdf_lut, env_samp, lut_uv, 0.0).rg;
    let irradiance = sh_irradiance(n);
    // Single-scattering specular with roughness-aware Fresnel, plus the energy
    // lost to multiple scattering (Fdez-Agüera 2019) so rough metals don't
    // darken; diffuse gets whatever energy the specular didn't take.
    let fr = max(vec3<f32>(1.0 - rough), f0) - f0;
    let ks = f0 + fr * pow(1.0 - nv, 5.0);
    let fss_ess = ks * ab.x + ab.y;
    let ems = 1.0 - (ab.x + ab.y);
    let f_avg = f0 + (1.0 - f0) / 21.0;
    let fms_ems = ems * fss_ess * f_avg / (1.0 - f_avg * ems);
    let kd = albedo * (1.0 - metal) * (1.0 - fss_ess - fms_ems);
    // Horizon occlusion (Jimenez 2016): normal-mapped reflections that dip
    // below the geometric surface would see the inside of the mesh.
    let horizon = clamp(1.0 + dot(r0, ng), 0.0, 1.0);
    // Specular occlusion from the baked AO (Lagarde 2014).
    let so = clamp(pow(nv + ao, exp2(-16.0 * rough - 1.0)) - 1.0 + ao, 0.0, 1.0);
    let spec = fss_ess * spec_env * so * horizon * horizon;
    let diffuse = (kd + fms_ems) * irradiance * ao_multibounce(ao, albedo);
    // Opacity scales everything (cut-outs vanish, reflections too). Glass
    // (transmission) swaps diffuse for the background showing through, so it
    // only hides what's behind by its Fresnel reflectance.
    let alpha = albedo4.a;
    let trans = orm.a;
    let fr_avg = (ks.x + ks.y + ks.z) / 3.0;
    let cover = alpha * mix(1.0, fr_avg, trans * (1.0 - metal));
    // Clearcoat: a second, dielectric lobe over everything the base reflects.
    let cl = coat_layer(n_coat, ng, v, coat4.r, coat4.g, ao);
    var color = (diffuse * (1.0 - trans) + spec) * (1.0 - cl.a) + cl.rgb + textureSample(m_emissive, m_samp, i.uv).rgb * g.params2.w;
    if (!front && cover >= 0.996) { color *= vec3<f32>(0.5, 0.25, 0.25); }
    if (cover >= 0.996) { return solid(hdr(color)); }
    return Shaded(vec4<f32>(hdr(color).rgb * alpha, 1.0), cover);
}

// Background: the environment itself, slightly blurred, or a plain gradient.
@fragment
fn fs_bg(f: FullOut) -> @location(0) vec4<f32> {
    let ndc = vec2<f32>(f.uv.x * 2.0 - 1.0, 1.0 - f.uv.y * 2.0);
    let p = g.inv_view_proj * vec4<f32>(ndc, 1.0, 1.0);
    let d = normalize(p.xyz / p.w - g.eye.xyz);
    if (g.params2.x > 0.5) {
        return hdr(env_radiance(d, g.params2.y));
    }
    let c = mix(vec3<f32>(0.035, 0.035, 0.04), vec3<f32>(0.11, 0.115, 0.13), 1.0 - f.uv.y);
    return ldr(c);
}
