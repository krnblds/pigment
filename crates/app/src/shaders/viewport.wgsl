// M1 viewport shading: clay / UV checker / normals / UV debug views.
// Real PBR + IBL replaces the lighting here in M2.

struct Globals {
    view_proj: mat4x4<f32>,
    eye: vec4<f32>,
    light_dir: vec4<f32>,   // xyz = direction *towards* the light
    params: vec4<f32>,      // x = view mode, y = checker cells across UV 0..1
};
@group(0) @binding(0) var<uniform> g: Globals;

struct VsIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) tangent: vec4<f32>,
};
struct VsOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
};

@vertex
fn vs_mesh(v: VsIn) -> VsOut {
    var o: VsOut;
    o.clip = g.view_proj * vec4<f32>(v.position, 1.0);
    o.world = v.position;
    o.normal = v.normal;
    o.uv = v.uv;
    return o;
}

fn checker(uv: vec2<f32>, cells: f32) -> vec3<f32> {
    let c = floor(uv * cells);
    let odd = (i32(c.x) + i32(c.y)) & 1;
    // tint by quadrant of UV space so flipped/rotated islands are obvious
    let tint = mix(vec3<f32>(0.85, 0.55, 0.35), vec3<f32>(0.35, 0.6, 0.85), step(0.5, uv.x));
    let base = mix(tint, tint.zyx, step(0.5, uv.y));
    return select(base * 0.9, vec3<f32>(0.9), odd == 1);
}

@fragment
fn fs_mesh(i: VsOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    var n = normalize(i.normal);
    if (!front) { n = -n; }
    let v = normalize(g.eye.xyz - i.world);
    let l = normalize(g.light_dir.xyz);
    let mode = i32(g.params.x);

    if (mode == 2) { return vec4<f32>(n * 0.5 + 0.5, 1.0); }          // normals
    if (mode == 3) { return vec4<f32>(fract(i.uv), 0.0, 1.0); }        // raw UVs

    var albedo = vec3<f32>(0.62, 0.6, 0.58);                            // clay
    if (mode == 1) { albedo = checker(i.uv, g.params.y); }

    // key light + soft hemisphere ambient + Blinn-Phong spec, with a rim term
    let ndl = max(dot(n, l), 0.0);
    let h = normalize(l + v);
    let spec = pow(max(dot(n, h), 0.0), 48.0) * 0.25;
    let sky = mix(vec3<f32>(0.18, 0.17, 0.16), vec3<f32>(0.32, 0.36, 0.42), n.y * 0.5 + 0.5);
    let rim = pow(1.0 - max(dot(n, v), 0.0), 3.0) * 0.15;
    let color = albedo * (ndl * vec3<f32>(1.0, 0.97, 0.92) + sky) + vec3<f32>(spec + rim);
    if (!front) { return vec4<f32>(color * vec3<f32>(0.6, 0.3, 0.3), 1.0); } // backfaces tinted red
    return vec4<f32>(color, 1.0);
}

// Fullscreen background gradient.
struct BgOut { @builtin(position) clip: vec4<f32>, @location(0) t: f32 };
@vertex
fn vs_bg(@builtin(vertex_index) vi: u32) -> BgOut {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u)) * 2.0 - 1.0;
    var o: BgOut;
    o.clip = vec4<f32>(p, 0.0, 1.0);
    o.t = p.y * 0.5 + 0.5;
    return o;
}
@fragment
fn fs_bg(i: BgOut) -> @location(0) vec4<f32> {
    let c = mix(vec3<f32>(0.035, 0.035, 0.04), vec3<f32>(0.11, 0.115, 0.13), i.t);
    return vec4<f32>(c, 1.0);
}
