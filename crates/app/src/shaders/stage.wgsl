// Lightbox stage (see pigment_core::stage and render/stage.rs): a seamless
// photo-studio cove under the model with a soft contact shadow and a soft
// planar reflection of the model.
//
// Passes (all per frame, only when the lighting has a stage):
//   1. the model's lowest / highest surface heights, rendered from below and
//      above into two small depth maps (viewport.wgsl vs_depth);
//   2. fs_shadow: per floor texel, how much of the environment's light
//      (cosine weighted, weighted by the environment's brightness, so the
//      softboxes cast the shadow) the model blocks, marched through those
//      height maps;
//   3. the model mirrored in the floor plane into a half-res target
//      (viewport.wgsl fs_mesh_mirror);
//   4. vs_floor / fs_floor: the cove itself, in the main pass.

struct Globals {
    view_proj: mat4x4<f32>,
    inv_view_proj: mat4x4<f32>,
    eye: vec4<f32>,
    params: vec4<f32>,   // x view mode, y exposure (EV), z env rotation (rad), w env mips
    params2: vec4<f32>,
    sh: array<vec4<f32>, 9>,
    // [0] active, floor y, centre x, centre z
    // [1] unit->world scale, shadow map half-size, occluder height range, mirror pass
    // [2] sweep albedo rgb, roughness
    // [3] f0, reflection strength, shadow strength, reflection fade distance
    // [4] 1 / main target width, 1 / main target height, environment reflection scale
    stage: array<vec4<f32>, 6>,
};
@group(0) @binding(0) var<uniform> g: Globals;

@group(1) @binding(0) var env: texture_2d<f32>;
@group(1) @binding(1) var brdf_lut: texture_2d<f32>;
@group(1) @binding(2) var env_samp: sampler;

// floor pass
@group(2) @binding(0) var shadow_map: texture_2d<f32>;
@group(2) @binding(1) var refl: texture_2d<f32>;
@group(2) @binding(2) var lin: sampler;

// shadow pass
@group(3) @binding(0) var occ_low: texture_depth_2d;
@group(3) @binding(1) var occ_high: texture_depth_2d;

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

fn stage_centre() -> vec2<f32> {
    return g.stage[0].zw;
}

// ---------------------------------------------------------------- shadow

// (covered, lowest, highest) model surface over world (x, z), heights above the floor.
fn occluder(xz: vec2<f32>) -> vec3<f32> {
    let half = g.stage[1].y;
    let uv = (xz - stage_centre()) / (2.0 * half) + 0.5;
    if (any(uv < vec2<f32>(0.0)) || any(uv >= vec2<f32>(1.0))) { return vec3<f32>(0.0); }
    let size = vec2<f32>(textureDimensions(occ_low));
    let px = vec2<i32>(uv * size);
    let dl = textureLoad(occ_low, px, 0);
    let dh = textureLoad(occ_high, px, 0);
    if (dl <= 0.0) { return vec3<f32>(0.0); }
    let h = g.stage[1].z;
    return vec3<f32>(1.0, (1.0 - dl) * h, dh * h);
}

fn radical_inverse(i: u32) -> f32 {
    return f32(reverseBits(i)) * 2.3283064365386963e-10;
}

// Interleaved gradient noise (Jimenez 2014): rotates the ray set per texel.
fn ign(p: vec2<f32>) -> f32 {
    return fract(52.9829189 * fract(dot(p, vec2<f32>(0.06711056, 0.00583715))));
}

const SHADOW_RAYS: u32 = 48u;
const SHADOW_STEPS: u32 = 20u;

@fragment
fn fs_shadow(f: FullOut) -> @location(0) vec4<f32> {
    let half = g.stage[1].y;
    let h = g.stage[1].z;
    let xz = stage_centre() + (f.uv - 0.5) * 2.0 * half;
    let rot = ign(f.pos.xy) * 2.0 * PI;
    var lit = 0.0;
    var total = 0.0;
    // near-field ambient occlusion (plain cosine weighting): the dark
    // contact line where the model meets the floor
    let ao_range = 0.3 * h;
    var ao = 0.0;
    for (var i = 0u; i < SHADOW_RAYS; i++) {
        // cosine-weighted hemisphere direction (Hammersley), weighted by the
        // environment's brightness that way
        let xi = vec2<f32>((f32(i) + 0.5) / f32(SHADOW_RAYS), radical_inverse(i));
        let phi = 2.0 * PI * xi.x + rot;
        let st = sqrt(xi.y);
        let d = vec3<f32>(cos(phi) * st, sqrt(1.0 - xi.y), sin(phi) * st);
        let w = dot(env_radiance(d, 2.0), vec3<f32>(0.2126, 0.7152, 0.0722)) + 1e-4;
        total += w;
        let flat_len = max(length(d.xz), 1e-4);
        let tmax = min(h / max(d.y, 1e-3), 2.0 * half / flat_len);
        var hit = 1e9;
        for (var k = 0u; k < SHADOW_STEPS; k++) {
            let t = tmax * pow((f32(k) + 0.5) / f32(SHADOW_STEPS), 1.7);
            let o = occluder(xz + d.xz * t);
            let y = d.y * t;
            if (o.x > 0.5 && y >= o.y && y <= o.z) {
                hit = t;
                break;
            }
        }
        if (hit > 1e8) { lit += w; }
        ao += smoothstep(0.0, ao_range, hit);
    }
    return vec4<f32>(lit / total, ao / f32(SHADOW_RAYS), 0.0, 1.0);
}

// ---------------------------------------------------------------- floor

struct FloorOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
};

@vertex
fn vs_floor(v: MeshIn) -> FloorOut {
    var o: FloorOut;
    let scale = g.stage[1].x;
    // a hair below the model so flat-bottomed props don't z-fight it
    let base = vec3<f32>(g.stage[0].z, g.stage[0].y - 2e-4 * scale, g.stage[0].w);
    o.world = base + v.position * scale;
    o.normal = v.normal;
    o.clip = g.view_proj * vec4<f32>(o.world, 1.0);
    return o;
}

fn contact_shadow(xz: vec2<f32>) -> f32 {
    let half = g.stage[1].y;
    let uv = (xz - stage_centre()) / (2.0 * half) + 0.5;
    let edge = min(min(uv.x, uv.y), min(1.0 - uv.x, 1.0 - uv.y));
    if (edge <= 0.0) { return 1.0; }
    let texel = 1.0 / vec2<f32>(textureDimensions(shadow_map));
    var m = textureSampleLevel(shadow_map, lin, uv, 0.0).rg * 0.4;
    m += textureSampleLevel(shadow_map, lin, uv + vec2<f32>(1.5, 0.5) * texel, 0.0).rg * 0.15;
    m += textureSampleLevel(shadow_map, lin, uv + vec2<f32>(-0.5, 1.5) * texel, 0.0).rg * 0.15;
    m += textureSampleLevel(shadow_map, lin, uv + vec2<f32>(-1.5, -0.5) * texel, 0.0).rg * 0.15;
    m += textureSampleLevel(shadow_map, lin, uv + vec2<f32>(0.5, -1.5) * texel, 0.0).rg * 0.15;
    // light blocked from the softboxes, deepened by contact occlusion
    let s = m.x * (0.25 + 0.75 * m.y * m.y);
    // fade to unshadowed at the map's border
    return mix(1.0, s, smoothstep(0.0, 0.08, edge));
}

const POISSON: array<vec2<f32>, 8> = array<vec2<f32>, 8>(
    vec2<f32>(-0.613, 0.617), vec2<f32>(0.170, -0.040), vec2<f32>(-0.299, 0.791), vec2<f32>(0.645, 0.493),
    vec2<f32>(-0.651, -0.717), vec2<f32>(0.421, 0.027), vec2<f32>(-0.817, -0.271), vec2<f32>(0.977, -0.108));

@fragment
fn fs_floor(i: FloorOut) -> @location(0) vec4<f32> {
    let n = normalize(i.normal);
    let p = i.world;
    let v = normalize(g.eye.xyz - p);
    let albedo = g.stage[2].xyz;
    // glossy floor, satin walls: a mirror-like wall would show every strip
    // light as a hard arc behind the model
    let floor_w = smoothstep(0.35, 0.95, n.y);
    let rough = clamp(mix(max(g.stage[2].w, 0.65), g.stage[2].w, floor_w), 0.03, 1.0);
    let f0 = g.stage[3].x * mix(0.5, 1.0, floor_w);
    let vis = mix(1.0, contact_shadow(p.xz), g.stage[3].z);

    let nv = clamp(dot(n, v), 1e-4, 1.0);
    let r = reflect(-v, n);
    var spec = env_radiance(r, rough * (g.params.w - 1.0)) * g.stage[4].z;
    let lut_uv = clamp(vec2<f32>(nv, rough), vec2<f32>(0.5 / 64.0), vec2<f32>(1.0 - 0.5 / 64.0));
    let ab = textureSampleLevel(brdf_lut, env_samp, lut_uv, 0.0).rg;
    let fr = f0 + (max(1.0 - rough, f0) - f0) * pow(1.0 - nv, 5.0);
    let fspec = fr * ab.x + ab.y;
    // the model hides the overhead lights from the floor beneath it
    spec *= mix(1.0, vis, 0.85);

    // planar reflection of the model on the flat part of the floor, blurred
    // more for rougher floors; premultiplied, a = how much model is there
    let flatness = smoothstep(0.995, 0.9999, n.y);
    if (flatness > 0.0 && g.stage[3].y > 0.0) {
        let suv = i.clip.xy * g.stage[4].xy;
        let radius = (0.002 + rough * 0.012) * vec2<f32>(g.stage[4].x / g.stage[4].y, 1.0);
        var m = textureSampleLevel(refl, lin, suv, 0.0) * 0.2;
        for (var k = 0; k < 8; k++) {
            m += textureSampleLevel(refl, lin, suv + POISSON[k] * radius, 0.0) * 0.1;
        }
        let k = g.stage[3].y * flatness;
        spec = mix(spec, m.rgb + spec * (1.0 - m.a), k);
    }
    let diffuse = albedo * sh_irradiance(n) * vis;
    let c = diffuse * (1.0 - fspec) + spec * fspec;
    return vec4<f32>(c * exp2(g.params.y), 1.0);
}
