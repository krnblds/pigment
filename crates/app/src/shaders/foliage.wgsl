// Foliage cards in the viewport: instanced, alpha-tested quads sampling a
// foliage atlas (colour + alpha, and a translucency map), lit by the same
// environment as the model (SH diffuse + prefiltered specular), with light
// coming through back-lit leaves and an optional wind sway.

struct Globals {
    view_proj: mat4x4<f32>,
    inv_view_proj: mat4x4<f32>,
    eye: vec4<f32>,
    params: vec4<f32>,   // x view mode, y exposure (EV), z env rotation (rad), w env mips
    params2: vec4<f32>,
    sh: array<vec4<f32>, 9>,
};
@group(0) @binding(0) var<uniform> g: Globals;

@group(1) @binding(0) var env: texture_2d<f32>;
@group(1) @binding(1) var brdf_lut: texture_2d<f32>;
@group(1) @binding(2) var env_samp: sampler;

struct Foliage {
    // x time (s), y global wind multiplier
    params: vec4<f32>,
};
@group(2) @binding(0) var f_color: texture_2d<f32>;        // sRGB colour, a = alpha
@group(2) @binding(1) var f_trans: texture_2d<f32>;        // translucency colour (sRGB)
@group(2) @binding(2) var f_samp: sampler;
@group(2) @binding(3) var<uniform> fp: Foliage;

struct CardIn {
    @location(0) p: vec3<f32>,
    @location(1) x: vec3<f32>,
    @location(2) y: vec3<f32>,
    @location(3) uv: vec4<f32>,     // u0, v0, u1, v1 (v down)
    // x: mount (0 upright, 1 flat, 2 wall, 3 hanging), y: wind, z: phase, w: highlight
    @location(4) misc: vec4<f32>,
};

struct CardOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) up: vec3<f32>,
    @location(4) misc: vec4<f32>,
};

@vertex
fn vs_card(@builtin(vertex_index) vi: u32, c: CardIn) -> CardOut {
    // two triangles: (0,0) (1,0) (1,1) / (0,0) (1,1) (0,1)
    var corners = array<vec2<f32>, 6>(vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(1.0, 1.0), vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 1.0), vec2<f32>(0.0, 1.0));
    let k = corners[vi % 6u];
    let s = k.x - 0.5;
    let t = k.y;
    var world = c.p + c.x * s + c.y * t;
    // wind: the free end sways (tip of upright cards, bottom of hanging ones)
    let mount = i32(c.misc.x + 0.5);
    var free = t * t;
    if (mount == 3) { free = (1.0 - t) * (1.0 - t); }
    if (mount == 1) { free = 0.0; }
    let w = c.misc.y * fp.params.y;
    if (w > 0.0) {
        let time = fp.params.x;
        let ph = c.misc.z;
        let gust = sin(time * 1.7 + ph) * 0.6 + sin(time * 3.1 + ph * 1.7) * 0.25;
        let len = length(c.y);
        world += vec3<f32>(1.0, 0.0, 0.35) * gust * w * free * len * 0.18;
    }
    var o: CardOut;
    o.clip = g.view_proj * vec4<f32>(world, 1.0);
    o.world = world;
    o.normal = normalize(cross(c.x, c.y));
    o.uv = vec2<f32>(mix(c.uv.x, c.uv.z, k.x), mix(c.uv.w, c.uv.y, t));
    o.up = normalize(c.y);
    o.misc = c.misc;
    return o;
}

fn rotate_y(d: vec3<f32>, a: f32) -> vec3<f32> {
    let c = cos(a);
    let s = sin(a);
    return vec3<f32>(c * d.x + s * d.z, d.y, -s * d.x + c * d.z);
}

fn env_uv(d: vec3<f32>) -> vec2<f32> {
    let phi = atan2(d.x, -d.z);
    let theta = acos(clamp(d.y, -1.0, 1.0));
    return vec2<f32>((phi + PI) / (2.0 * PI), theta / PI);
}

fn env_rad(d: vec3<f32>, lod: f32) -> vec3<f32> {
    return textureSampleLevel(env, env_samp, env_uv(rotate_y(d, g.params.z)), lod).rgb;
}

fn sh_irr(n0: vec3<f32>) -> vec3<f32> {
    let n = rotate_y(n0, g.params.z);
    let b = array<f32, 9>(
        0.282095, 0.488603 * n.y, 0.488603 * n.z, 0.488603 * n.x,
        1.092548 * n.x * n.y, 1.092548 * n.y * n.z, 0.315392 * (3.0 * n.z * n.z - 1.0),
        1.092548 * n.x * n.z, 0.546274 * (n.x * n.x - n.y * n.y));
    var e = vec3<f32>(0.0);
    for (var i = 0; i < 9; i++) { e += g.sh[i].xyz * b[i]; }
    return max(e, vec3<f32>(0.0));
}

@fragment
fn fs_card(i: CardOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    let c4 = textureSample(f_color, f_samp, i.uv);
    if (c4.a < 0.5) { discard; }
    let albedo = c4.rgb;
    let trans = textureSample(f_trans, f_samp, i.uv).rgb;
    var n = normalize(i.normal);
    if (!front) { n = -n; }
    let mount = i32(i.misc.x + 0.5);
    // upright / hanging cards: shade like the plant's volume, not a flat sheet
    if (mount == 0 || mount == 3) { n = normalize(n * 0.35 + i.up * 0.65); }
    let mode = i32(g.params.x);
    if (mode == 1) { return vec4<f32>(albedo, 0.0); }
    if (mode == 11) { return vec4<f32>(1.0, 1.0, 1.0, 0.0); }
    let v = normalize(g.eye.xyz - i.world);
    let rough = 0.55;
    let nv = clamp(abs(dot(n, v)), 1e-4, 1.0);
    let r = reflect(-v, n);
    let spec = env_rad(normalize(mix(n, r, 0.4)), rough * (g.params.w - 1.0)) * (0.04 + 0.2 * pow(1.0 - nv, 5.0));
    let diffuse = albedo * sh_irr(n);
    // back-lit leaves: light arriving from behind the card comes through
    let back = trans * sh_irr(-n) * 0.8;
    var color = diffuse + back + spec * 0.5;
    if (i.misc.w > 0.5) { color = mix(color, vec3<f32>(0.2, 0.9, 0.4), 0.35); }
    return vec4<f32>(color * exp2(g.params.y), 1.0);
}
