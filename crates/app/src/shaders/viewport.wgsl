// Viewport: metallic/roughness PBR lit by an HDRI (split-sum IBL + SH9
// diffuse), ACES tone mapping, plus channel/debug views.

struct Globals {
    view_proj: mat4x4<f32>,
    inv_view_proj: mat4x4<f32>,
    eye: vec4<f32>,
    params: vec4<f32>,   // x view mode, y exposure (EV), z env rotation (rad), w env mips
    params2: vec4<f32>,  // x show env background (0/1), y background blur lod, z bake ready
    sh: array<vec4<f32>, 9>,
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
@group(2) @binding(6) var m_samp: sampler;

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

// ACES filmic, Hill's fit (sRGB -> ACES AP1 -> RRT/ODT -> sRGB).
fn aces(c: vec3<f32>) -> vec3<f32> {
    let i = mat3x3<f32>(
        vec3<f32>(0.59719, 0.07600, 0.02840),
        vec3<f32>(0.35458, 0.90834, 0.13383),
        vec3<f32>(0.04823, 0.01566, 0.83777));
    let o = mat3x3<f32>(
        vec3<f32>(1.60475, -0.10208, -0.00327),
        vec3<f32>(-0.53108, 1.10813, -0.07276),
        vec3<f32>(-0.07367, -0.00605, 1.07602));
    let v = i * c;
    let a = v * (v + 0.0245786) - 0.000090537;
    let b = v * (0.983729 * v + 0.4329510) + 0.238081;
    return clamp(o * (a / b), vec3<f32>(0.0), vec3<f32>(1.0));
}

fn tonemap(c: vec3<f32>) -> vec3<f32> {
    return aces(c * exp2(g.params.y));
}

fn checker(uv: vec2<f32>) -> vec3<f32> {
    let c = floor(uv * 16.0);
    let odd = (i32(c.x) + i32(c.y)) & 1;
    let tint = mix(vec3<f32>(0.85, 0.55, 0.35), vec3<f32>(0.35, 0.6, 0.85), step(0.5, uv.x));
    let base = mix(tint, tint.zyx, step(0.5, uv.y));
    return select(base * 0.9, vec3<f32>(0.9), odd == 1);
}

@fragment
fn fs_mesh(i: VsOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    var ng = normalize(i.normal);
    if (!front) { ng = -ng; }
    let mode = i32(g.params.x);

    let albedo = textureSample(m_color, m_samp, i.uv).rgb;
    let orm = textureSample(m_orm, m_samp, i.uv);
    let tn = textureSample(m_normal, m_samp, i.uv).xyz * 2.0 - 1.0;

    // tangent frame; bitangent points up the image (OpenGL normal maps)
    let t = normalize(i.tangent.xyz - ng * dot(ng, i.tangent.xyz));
    let b = cross(ng, t) * i.tangent.w;
    let n = normalize(t * tn.x + b * tn.y + ng * tn.z);

    switch mode {
        case 1: { return vec4<f32>(albedo, 1.0); }
        case 2: { return vec4<f32>(vec3<f32>(orm.g * orm.g), 1.0); }       // roughness (shown perceptually)
        case 3: { return vec4<f32>(vec3<f32>(orm.b * orm.b), 1.0); }       // metallic
        case 4: {
            let h = textureSample(m_height, m_samp, i.uv).r * 0.5 + 0.5;
            return vec4<f32>(srgb_to_linear(vec3<f32>(h)), 1.0);
        }
        case 5: { return vec4<f32>(srgb_to_linear(tn * 0.5 + 0.5), 1.0); }   // tangent normal
        case 6: { return vec4<f32>(srgb_to_linear(vec3<f32>(textureSample(m_bakes, m_samp, i.uv).r)), 1.0); }
        case 7: { return vec4<f32>(srgb_to_linear(vec3<f32>(textureSample(m_bakes, m_samp, i.uv).g)), 1.0); }
        case 8: { return vec4<f32>(srgb_to_linear(textureSample(m_wnormal, m_samp, i.uv).xyz * 0.5 + 0.5), 1.0); }
        case 9: {
            let l = max(dot(ng, normalize(g.eye.xyz - i.world)), 0.0);
            return vec4<f32>(checker(i.uv) * (0.25 + 0.75 * l), 1.0);
        }
        default: {}
    }

    // --- metallic/roughness PBR ---
    let rough = clamp(orm.g, 0.03, 1.0);
    let metal = orm.b;
    let ao = orm.r;
    let v = normalize(g.eye.xyz - i.world);
    let nv = clamp(dot(n, v), 1e-4, 1.0);
    let f0 = mix(vec3<f32>(0.04), albedo, metal);
    // Fresnel with roughness (Lagarde) for the diffuse/specular split
    let fr = f0 + (max(vec3<f32>(1.0 - rough), f0) - f0) * pow(1.0 - nv, 5.0);
    let r = reflect(-v, n);
    let lod = rough * (g.params.w - 1.0);
    let spec_env = env_radiance(r, lod);
    let ab = textureSampleLevel(brdf_lut, env_samp, vec2<f32>(nv, rough), 0.0).rg;
    let spec = spec_env * (f0 * ab.x + ab.y);
    let diffuse = (1.0 - fr) * (1.0 - metal) * albedo * sh_irradiance(n);
    // specular occlusion approximation (Lagarde)
    let so = clamp(pow(nv + ao, exp2(-16.0 * rough - 1.0)) - 1.0 + ao, 0.0, 1.0);
    var color = diffuse * ao + spec * so;
    if (!front) { color *= vec3<f32>(0.5, 0.25, 0.25); }
    return vec4<f32>(tonemap(color), 1.0);
}

// Background: the environment itself, slightly blurred, or a plain gradient.
@fragment
fn fs_bg(f: FullOut) -> @location(0) vec4<f32> {
    let ndc = vec2<f32>(f.uv.x * 2.0 - 1.0, 1.0 - f.uv.y * 2.0);
    let p = g.inv_view_proj * vec4<f32>(ndc, 1.0, 1.0);
    let d = normalize(p.xyz / p.w - g.eye.xyz);
    if (g.params2.x > 0.5) {
        return vec4<f32>(tonemap(env_radiance(d, g.params2.y)), 1.0);
    }
    let c = mix(vec3<f32>(0.035, 0.035, 0.04), vec3<f32>(0.11, 0.115, 0.13), 1.0 - f.uv.y);
    return vec4<f32>(c, 1.0);
}
