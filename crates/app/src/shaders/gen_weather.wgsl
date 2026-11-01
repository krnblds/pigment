// Weathering and pattern generators (ids 10..14), appended to composite.wgsl.
// They read the same group 0 data as gen_eval: bakes (r AO, g curvature,
// b drip = 1 / (1 + metres to the nearest protrusion above), a rain exposure),
// world position in metres and the world normal.
//
// Parameter slots (gp / gp2 as packed by texset::layer_params):
//   gp  = amount, softness, scale, breakup
//   gp2 = seed, ao_influence slot, curvature_weight slot, variant

fn wx_hash2(c: vec2<f32>, salt: f32) -> f32 {
    return hash3(vec3<f32>(c.x * 1.31 + 0.17, c.y * 0.73 + 11.3, salt * 0.917 + 5.1));
}

// In-surface 2D coordinates measured from the mesh's min corner, and a
// facing id so opposite walls get different random cells. Floors / roofs use
// (x, z); walls use (horizontal, y) so rows stay level.
fn wx_surface(pw: vec3<f32>, n: vec3<f32>) -> vec3<f32> {
    let a = abs(n);
    // tile mode anchors patterns to the world origin, so a tile moved by part
    // of its period scrolls the pattern (it stays periodic either way)
    let q = pw - select(sh.bmin.xyz, vec3<f32>(0.0), tile_on());
    if (a.y >= a.x && a.y >= a.z) {
        return vec3<f32>(q.x, q.z, select(1.0, 0.0, n.y > 0.0));
    }
    if (a.x > a.z) {
        return vec3<f32>(q.z, q.y, select(3.0, 2.0, n.x > 0.0));
    }
    return vec3<f32>(q.x, q.y, select(5.0, 4.0, n.z > 0.0));
}


// Tile mode: the wrap period (metres) along the two in-surface axes of
// wx_surface, for floor-facing texels (the tile plane is a floor); 0 = none.
fn tile_plane_period(n: vec3<f32>) -> vec2<f32> {
    let a = abs(n);
    if (a.y >= a.x && a.y >= a.z) { return vec2<f32>(sh.res.z, sh.res.w); }
    return vec2<f32>(0.0);
}

fn wx_threshold(v: f32, gp: vec4<f32>) -> f32 {
    let threshold = 1.0 - gp.x;
    let soft = max(gp.y, 0.003);
    return smoothstep(threshold - soft, threshold + soft, v);
}

// Leaks: water collects on sills / AC units / ledges and runs off their
// front edge, staining the wall below. The drip bake knows how far below the
// nearest protrusion each wall texel is; streaks fade over the drip length
// (curvature_weight slot, metres) and are broken into vertical runs.
fn wx_leaks(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    let bk = textureLoad(bakes, t, 0);
    let pw = textureLoad(position, t, 0).xyz;
    let n = normalize(textureLoad(wnormal, t, 0).xyz + vec3<f32>(0.0, 1e-5, 0.0));
    let seed = vec3<f32>(gp2.x * 7.31, gp2.x * 3.17, gp2.x * 5.53);
    let s = max(gp.z, 0.01);
    // walls and steep faces only; water doesn't run down floors or ceilings
    let wall = 1.0 - smoothstep(0.6, 0.85, abs(n.y));
    let drip = bk.b;
    var fall = 0.0;
    if (drip > 1e-3) {
        let gap = 1.0 / drip - 1.0;
        let len = max(gp2.z, 0.05);
        fall = pow(clamp(1.0 - gap / len, 0.0, 1.0), 1.4);
    }
    // vertical runs: noise strongly stretched along world up
    let q = vec3<f32>(pw.x * s, pw.y * s * 0.05, pw.z * s) + seed;
    let sq = vec3<f32>(s, s * 0.05, s);
    let runs = fbm_s(q, pw, sq, seed) * 0.7 + fbm_s(q * vec3<f32>(3.1, 1.7, 3.1) + seed.yzx, pw, sq * vec3<f32>(3.1, 1.7, 3.1), seed * vec3<f32>(3.1, 1.7, 3.1) + seed.yzx) * 0.3;
    let streak = smoothstep(0.38, 0.62, runs);
    let broken = mix(1.0, streak * 1.5, clamp(gp.w, 0.0, 1.0));
    // damp, sheltered wall right under overhangs (AO), also streaky
    let occl = 1.0 - bk.r;
    let v = wall * (fall * broken + occl * gp2.y * streak);
    return wx_threshold(v, gp);
}

// Puddles: water stands on near-level, rain-exposed surfaces. It fills the
// low spots of a micro-relief (fbm heightfield on the ground plane, scale =
// puddles per metre, breakup = relief contrast) first, and pools in concave
// gutters (curvature_weight slot) and corners (ao_influence slot).
fn wx_puddles(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    let bk = textureLoad(bakes, t, 0);
    let pw = textureLoad(position, t, 0).xyz;
    let n = normalize(textureLoad(wnormal, t, 0).xyz + vec3<f32>(0.0, 1e-5, 0.0));
    let seed = vec3<f32>(gp2.x * 7.31, gp2.x * 3.17, gp2.x * 5.53);
    let s = max(gp.z, 0.01);
    let level = smoothstep(0.88, 0.985, n.y);
    let rain = smoothstep(0.08, 0.4, bk.a);
    let g = vec3<f32>(pw.x, 0.0, pw.z) * s;
    let relief = fbm_s(g + seed, pw, vec3<f32>(s, 0.0, s), seed) * 0.7 + fbm_s(g * 3.7 + seed.zxy, pw, vec3<f32>(s * 3.7, 0.0, s * 3.7), seed.zxy) * 0.3;
    let low = (0.5 - relief) * (1.5 + 3.0 * gp.w);
    let cavity = clamp((0.5 - bk.g) * 2.0, 0.0, 1.0);
    let occl = 1.0 - bk.r;
    let v = level * rain * (0.5 + low + cavity * gp2.z + occl * gp2.y * 0.6);
    return wx_threshold(v, gp);
}

// Moss / grime build-up: settles on up-facing ledges, grows into occluded
// crevices (ao_influence slot) and concave corners (curvature_weight slot),
// in clumps (scale = clump frequency, breakup = clump contrast).
fn wx_moss(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    let bk = textureLoad(bakes, t, 0);
    let pw = textureLoad(position, t, 0).xyz;
    let n = normalize(textureLoad(wnormal, t, 0).xyz + vec3<f32>(0.0, 1e-5, 0.0));
    let seed = vec3<f32>(gp2.x * 7.31, gp2.x * 3.17, gp2.x * 5.53);
    let s = max(gp.z, 0.01);
    let up = smoothstep(0.35, 0.85, n.y);
    let occl = 1.0 - bk.r;
    // crevices only hold enough water and debris where the surface isn't
    // sheer: full growth on floors / corners, a third of it on walls
    let holds = mix(0.35, 1.0, smoothstep(-0.2, 0.6, n.y));
    let damp = clamp(occl * gp2.y * 1.5, 0.0, 1.0) * holds;
    let cavity = clamp((0.5 - bk.g) * 2.0, 0.0, 1.0) * gp2.z * holds;
    // nothing hangs on ceilings
    let not_down = smoothstep(-0.6, -0.2, n.y);
    let base = max(up * (0.55 + 0.45 * damp), max(damp * 0.8, cavity)) * not_down;
    let clump = fbm_s(pw * s + seed, pw, vec3<f32>(s), seed) * 0.65 + fbm_s(pw * s * 3.1 + seed.yzx, pw, vec3<f32>(s * 3.1), seed.yzx) * 0.35;
    let v = base + (clump - 0.5) * gp.w * 1.6;
    return wx_threshold(v, gp);
}

// Tiles: 0 running-bond bricks, 1 square tiles, 2 hexagons. scale = rows per
// metre, curvature_weight slot = cell aspect (w/h), ao_influence slot =
// mortar width (fraction of a row), breakup = row-offset jitter + tone
// variation, amount = fraction of cells kept (1 = all; invert for mortar).
fn wx_tiles(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    let pw = textureLoad(position, t, 0).xyz;
    let n = normalize(textureLoad(wnormal, t, 0).xyz + vec3<f32>(0.0, 1e-5, 0.0));
    let sf = wx_surface(pw, n);
    let rows = max(gp.z, 0.01);
    var h = 1.0 / rows;                      // row height, metres
    let mortar = clamp(gp2.y, 0.0, 0.9) * h;
    let soft = max(gp.y, 0.002) * h;
    let jitter = clamp(gp.w, 0.0, 1.0);
    var cell = vec2<f32>(0.0);
    var edge = 0.0;                          // metres to the cell border
    if (u32(gp2.w + 0.5) == 2u) {
        // hexagons, flat-to-flat = one row
        var p = sf.xy * rows;
        let r = vec2<f32>(1.0, 1.7320508);
        // tile mode: whole hex periods across the tile (slightly anisotropic)
        let tp = tile_plane_period(n);
        var hper = vec2<f32>(0.0);
        if (tp.x > 0.0) { hper.x = max(round(tp.x * rows), 1.0); p.x = sf.x * hper.x / tp.x; }
        if (tp.y > 0.0) { hper.y = max(round(tp.y * rows / r.y), 1.0) * r.y; p.y = sf.y * hper.y / tp.y; }
        let hr = r * 0.5;
        let a = p - r * floor(p / r) - hr;
        let b = (p - hr) - r * floor((p - hr) / r) - hr;
        let gv = select(b, a, dot(a, a) < dot(b, b));
        var ctr = p - gv;
        if (hper.x > 0.0) { ctr.x = ctr.x - hper.x * floor((ctr.x + 0.25) / hper.x); }
        if (hper.y > 0.0) { ctr.y = ctr.y - hper.y * floor((ctr.y + 0.25) / hper.y); }
        cell = floor(ctr * 2.0 + 0.5);
        let hd = max(dot(abs(gv), normalize(vec2<f32>(1.0, 1.7320508))), abs(gv.x));
        edge = (0.5 - hd) * h;
    } else {
        var w = h * max(gp2.z, 0.05);
        // tile mode: whole rows (an even count for running bond) and columns per tile
        let tp = tile_plane_period(n);
        var ncol = 0.0;
        if (tp.y > 0.0) {
            var nr = max(round(tp.y / h), 1.0);
            if (u32(gp2.w + 0.5) == 0u) { nr = max(2.0, 2.0 * round(tp.y / h * 0.5)); }
            h = tp.y / nr;
        }
        if (tp.x > 0.0) { ncol = max(round(tp.x / w), 1.0); w = tp.x / ncol; }
        let row = floor(sf.y / h);
        // tile mode: row ids repeat every period (hashes, running-bond parity)
        var rowh = row;
        if (tp.y > 0.0) { let nr = round(tp.y / h); rowh = row - nr * floor(row / nr); }
        var off = 0.0;
        if (u32(gp2.w + 0.5) == 0u) {
            off = select(0.0, 0.5, (i32(rowh) & 1) == 1) + (wx_hash2(vec2<f32>(rowh, sf.z), gp2.x) - 0.5) * jitter * 0.5;
        }
        let u = sf.x / w + off;
        var col = floor(u);
        let fx = u - col;
        if (ncol > 0.0) { col = col - ncol * floor(col / ncol); }
        let fy = sf.y / h - row;
        cell = vec2<f32>(col, rowh);
        edge = min(min(fx, 1.0 - fx) * w, min(fy, 1.0 - fy) * h);
    }
    let face = smoothstep(mortar * 0.5, mortar * 0.5 + soft, edge);
    let r1 = wx_hash2(cell, gp2.x + sf.z * 17.0);
    let r2 = wx_hash2(cell + vec2<f32>(37.0, 91.0), gp2.x + sf.z * 17.0);
    let keep = select(0.0, 1.0, r1 < gp.x || gp.x >= 0.999);
    return face * keep * (1.0 - jitter * 0.4 * r2);
}

// Window grid: storey-high cells on walls (scale = cell height in metres,
// curvature_weight slot = cell aspect w/h, ao_influence slot = frame width as
// a fraction of the cell); a random `amount` of the cells is lit, breakup
// varies their brightness. Floors, roofs and ceilings get none.
fn wx_windows(t: vec2<i32>, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    let pw = textureLoad(position, t, 0).xyz;
    let n = normalize(textureLoad(wnormal, t, 0).xyz + vec3<f32>(0.0, 1e-5, 0.0));
    if (abs(n.y) > 0.5) { return 0.0; }
    let sf = wx_surface(pw, n);
    let h = max(gp.z, 0.05);
    let w = h * max(gp2.z, 0.05);
    let c = vec2<f32>(floor(sf.x / w), floor(sf.y / h));
    let f = vec2<f32>(sf.x / w, sf.y / h) - c;
    let fr = clamp(gp2.y, 0.0, 0.45);
    // sill a bit deeper than the lintel; distances in metres
    let dx = min(f.x - fr, 1.0 - fr - f.x) * w;
    let dy = min(f.y - fr * 1.2, 1.0 - fr * 0.8 - f.y) * h;
    let soft = max(gp.y, 0.002) * h;
    let pane = smoothstep(0.0, soft, min(dx, dy));
    let salt = gp2.x + sf.z * 17.0;
    let lit = select(0.0, 1.0, wx_hash2(c, salt) < gp.x);
    let bright = 1.0 - clamp(gp.w, 0.0, 1.0) * 0.7 * wx_hash2(c + vec2<f32>(13.0, 7.0), salt);
    return pane * lit * bright;
}

fn gen_weather(t: vec2<i32>, kind: u32, gp: vec4<f32>, gp2: vec4<f32>) -> f32 {
    switch kind {
        case 10u: { return wx_leaks(t, gp, gp2); }
        case 11u: { return wx_puddles(t, gp, gp2); }
        case 12u: { return wx_moss(t, gp, gp2); }
        case 13u: { return wx_tiles(t, gp, gp2); }
        case 14u: { return wx_windows(t, gp, gp2); }
        default: { return 0.0; }
    }
}
