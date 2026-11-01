shader_type spatial;
// The open world's terrain: the nine Pigment ground sets (tools/ground_textures.py) plus the road concrete,
// packed as two texture arrays by tools/godot/pack_ground.py, blended like the Blender material
// (tools/world/ground_material.py; keep the two in step):
//   grass everywhere -> dirt (noise patches, road verges, wet hollows) -> cracked mud (dry hollows) ->
//   forest floor (forest mask) -> scree (below cliffs, 28-33 deg) -> rock (> ~37 deg, summits; triplanar) ->
//   beach sand (shore mask) -> city land: concrete, cobbles in the old town, vacant lots in port gaps.
// Each step is height-aware (the incoming set's height map moves its edge). The world masks come from
// tools/world/ground_masks.py, sampled by world position (no mesh attributes needed).
// Anti-tiling: a second sample rotated 37 deg mixed in by world noise, macro tone / roughness drift.
// Distance: full detail near, one sample per set in the middle distance, average colours far away.
// Rain: the same `rain` uniform as the roads (town_loader.set_road_rain): darker, glossier, puddles with
// drop ripples in the texture's low spots on flat ground.
render_mode cull_back;

#include "res://scripts/road_common.gdshaderinc"

uniform sampler2DArray ground_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2DArray ground_nrm : filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D masks1 : filter_linear, repeat_disable;     // urban, forest, scree, verge
uniform sampler2D masks2 : filter_linear, repeat_disable;     // lot, hollow, old town, shore
uniform vec4 mask_xf = vec4(-2048.0, -2048.0, 4098.0, 2.0);  // origin x, origin y (Blender), span (m), cell (m)
uniform float tile_m[10];
uniform vec4 avg[10];                    // linear average colour, roughness (far shading)
uniform float rain = 1.0;                // set by the game: 1 raining, 0 dry
uniform float near_end = 70.0;           // full detail (anti-tiling, triplanar) inside this
uniform float far_start = 260.0;         // textures fade to average colours from here...
uniform float far_end = 520.0;           // ...to here
uniform float normal_strength = 1.0;

const int GRASS = 0;
const int DIRT = 1;
const int CRACKED = 2;
const int FOREST = 3;
const int SCREE = 4;
const int ROCK = 5;
const int SAND = 6;
const int COBBLES = 7;
const int LOT = 8;
const int CONCRETE = 9;

varying vec3 wpos;
varying vec3 wnrm;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	wnrm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

struct Smp {
	vec3 c;     // linear colour
	float r;
	float h;
	float ao;
	vec3 p;     // world-space normal perturbation (UDN)
};

Smp tap(int k, vec2 uv) {
	vec4 a = texture(ground_albedo, vec3(uv, float(k)));
	vec4 n = texture(ground_nrm, vec3(uv, float(k)));
	Smp s;
	s.c = a.rgb;
	s.h = a.a;
	s.r = n.b;
	s.ao = n.a;
	s.p = vec3(n.r * 2.0 - 1.0, n.g * 2.0 - 1.0, 0.0);   // tangent xy (image right, image up)
	return s;
}

Smp mixs(Smp a, Smp b, float f) {
	Smp o;
	o.c = mix(a.c, b.c, f);
	o.r = mix(a.r, b.r, f);
	o.h = mix(a.h, b.h, f);
	o.ao = mix(a.ao, b.ao, f);
	o.p = mix(a.p, b.p, f);
	return o;
}

// A planar set in the ground plane: u = east, image up = north (Blender +y = Godot -z).
// detail > 0: a second sample rotated 37 deg, mixed in by the world noise k.
Smp planar(int k, float detail, float kmix) {
	vec2 uv = wpos.xz / tile_m[k];
	Smp s = tap(k, uv);
	s.p = vec3(s.p.x, 0.0, -s.p.y);
	float kk = kmix * detail;
	if (kk > 0.002) {
		float c = cos(0.6458), si = sin(0.6458);
		vec2 uv2 = mat2(vec2(c, si), vec2(-si, c)) * uv + vec2(0.31, 0.57);
		Smp t = tap(k, uv2);
		vec2 q = mat2(vec2(c, -si), vec2(si, c)) * vec2(t.p.x, -t.p.y);   // back into the first frame (x, z)
		t.p = vec3(q.x, 0.0, q.y);
		s = mixs(s, t, kk);
	}
	return s;
}

// Rock: world triplanar; the tile's v runs up cliffs. Far away: the dominant projection only.
Smp triplanar(int k, float detail) {
	vec3 w = pow(abs(wnrm), vec3(4.0));
	w /= (w.x + w.y + w.z);
	float t = tile_m[k];
	Smp o;
	o.c = vec3(0.0); o.r = 0.0; o.h = 0.0; o.ao = 0.0; o.p = vec3(0.0);
	if (detail < 0.01) {
		// one projection: the strongest axis
		if (w.y >= w.x && w.y >= w.z) { Smp s = tap(k, wpos.xz / t); s.p = vec3(s.p.x, 0.0, -s.p.y); return s; }
		if (w.x >= w.z) { Smp s = tap(k, vec2(-wpos.z, -wpos.y) / t); s.p = vec3(0.0, s.p.y, -s.p.x); return s; }
		Smp s = tap(k, vec2(wpos.x, -wpos.y) / t); s.p = vec3(s.p.x, s.p.y, 0.0); return s;
	}
	if (w.x > 0.01) {
		Smp s = tap(k, vec2(-wpos.z, -wpos.y) / t);
		s.p = vec3(0.0, s.p.y, -s.p.x);
		o = mixs(o, s, 1.0); o.c *= w.x; o.r *= w.x; o.h *= w.x; o.ao *= w.x; o.p *= w.x;
	}
	if (w.y > 0.01) {
		Smp s = tap(k, wpos.xz / t);
		s.p = vec3(s.p.x, 0.0, -s.p.y);
		o.c += s.c * w.y; o.r += s.r * w.y; o.h += s.h * w.y; o.ao += s.ao * w.y; o.p += s.p * w.y;
	}
	if (w.z > 0.01) {
		Smp s = tap(k, vec2(wpos.x, -wpos.y) / t);
		s.p = vec3(s.p.x, s.p.y, 0.0);
		o.c += s.c * w.z; o.r += s.r * w.z; o.h += s.h * w.z; o.ao += s.ao * w.z; o.p += s.p * w.z;
	}
	return o;
}

Smp flat_set(int k) {
	Smp s;
	s.c = avg[k].rgb; s.r = avg[k].a; s.h = 0.5; s.ao = 1.0; s.p = vec3(0.0);
	return s;
}

Smp get_set(int k, float detail, float kmix, float tex) {
	if (tex < 0.01) {
		return flat_set(k);
	}
	Smp s = (k == ROCK) ? triplanar(k, detail) : planar(k, detail, kmix);
	if (tex < 0.99) {
		s = mixs(flat_set(k), s, tex);
	}
	return s;
}

// The Blender material's blend(): the incoming set's height moves the edge.
float hblend(float f, float h_in, float h_base, float hk) {
	if (hk <= 0.0) return f;
	return clamp((f - 0.5) * 2.2 + 0.5 + (h_in - h_base) * hk, 0.0, 1.0);
}

float s01(float a, float b, float x) { return smoothstep(a, b, x); }
// Blender's Map Range (smoothstep) also handles from > to (a falling edge)
float sstep(float a, float b, float x) { return a < b ? smoothstep(a, b, x) : 1.0 - smoothstep(b, a, x); }

void fragment() {
	vec2 bxy = vec2(wpos.x, -wpos.z);                           // Blender ground coordinates
	vec2 muv = (bxy - mask_xf.xy + 0.5 * mask_xf.w) / mask_xf.z;
	muv.y = 1.0 - muv.y;                                        // the mask PNGs have north at the top
	vec4 m1 = texture(masks1, muv);
	vec4 m2 = texture(masks2, muv);
	float urban = m1.r, forest = m1.g, scree = m1.b, verge = m1.a;
	float lot = m2.r, hollow = m2.g, oldtown = m2.b, shore = m2.a;
	float big = rd_fbm(bxy * 0.012 + 11.0, 3);
	float mid = rd_fbm(bxy * 0.05 + 23.0, 4);
	float fine = rd_fbm(bxy * 0.25 + 5.0, 3);
	float kmix = smoothstep(0.42, 0.58, rd_fbm(bxy * 0.07, 2));
	float steep = 1.0 - wnrm.y;
	float z = wpos.y;

	float dist = length(CAMERA_POSITION_WORLD - wpos);
	float detail = 1.0 - smoothstep(near_end * 0.7, near_end, dist);
	float tex = 1.0 - smoothstep(far_start, far_end, dist);

	// the blend weights, in order (the Blender material's)
	float hol = s01(0.25, 0.5, hollow);
	float f_dirt = max(max(s01(0.62, 0.7, mid), s01(0.3, 0.6, verge + (mid - 0.5) * 0.5)), hol * sstep(0.6, 0.5, big));
	float f_crack = hol * s01(0.5, 0.6, big);
	float f_forest = s01(0.3, 0.55, forest + (mid - 0.5) * 0.35);
	float f_scree = max(s01(0.2, 0.45, scree + (mid - 0.5) * 0.3), s01(0.12, 0.17, steep + (fine - 0.5) * 0.04)) * (1.0 - forest * 0.8);
	float f_rock = max(s01(0.19, 0.24, steep + (mid - 0.5) * 0.05), s01(210.0, 250.0, z + big * 40.0));
	float f_sand = s01(0.3, 0.55, shore + (fine - 0.5) * 0.3);
	float f_city = s01(0.3, 0.6, urban);
	float f_cob = f_city * s01(0.3, 0.6, oldtown);
	float f_lot = f_city * s01(0.25, 0.5, lot + (mid - 0.5) * 0.3);
	int ks[9] = {DIRT, CRACKED, FOREST, SCREE, ROCK, SAND, CONCRETE, COBBLES, LOT};
	float fs[9] = {f_dirt, f_crack, f_forest, f_scree, f_rock, f_sand, f_city, f_cob, f_lot};
	float hk[9] = {2.0, 2.0, 2.0, 2.0, 1.2, 2.0, 0.0, 0.0, 0.0};
	// skip what a later layer covers completely (only the layers that show get sampled)
	int first = -1;
	for (int i = 8; i >= 0; i--) {
		float cover = hk[i] > 0.0 ? (fs[i] - 0.5) * 2.2 + 0.5 - hk[i] * 0.25 : fs[i];
		if (cover >= 0.999) { first = i; break; }
	}
	Smp s;
	if (first < 0) {
		s = get_set(GRASS, detail, kmix, tex);
	} else {
		s = get_set(ks[first], detail, kmix, tex);
	}
	for (int i = max(first + 1, 0); i < 9; i++) {
		float f = fs[i];
		if (f < 0.002) continue;
		Smp t = get_set(ks[i], detail, kmix, tex);
		f = hblend(f, t.h, s.h, hk[i] * tex);
		s = mixs(s, t, f);
	}

	// macro tone / roughness drift (tens of metres)
	float mv = rd_fbm(bxy * 0.03 + 3.0, 3);
	vec3 col = s.c * vec3(0.82 + mv * 0.36, 0.82 + mv * 0.36, 0.84 + mv * 0.32);
	float rough = clamp(s.r + (mv - 0.5) * 0.15, 0.0, 1.0);
	vec3 pert = s.p;

	// wet: below the waterline, a wet line on the shore, rain (damp everywhere, puddles in the lows)
	float wl = max(sstep(0.5, -0.3, z), sstep(1.4, 0.3, z) * s01(0.2, 0.5, shore));
	float lows = sstep(0.46, 0.38, s.h + (rd_fbm(bxy * 0.11 + 7.0, 3) - 0.5) * 0.25);
	float pud = lows * rain * (1.0 - s01(0.05, 0.15, steep)) * tex;
	float damp = max(wl, rain * 0.85);
	col *= mix(1.0, 0.6, damp);
	col *= mix(1.0, 0.5, pud);
	rough = mix(rough, rough * 0.55, damp);
	rough = mix(rough, 0.03, pud);
	pert *= (1.0 - max(pud, damp * 0.3)) * normal_strength;
	vec2 rip = vec2(0.0);
	if (pud > 0.01 && dist < 40.0) {
		rip = rd_ripples(bxy, TIME) * pud;
		pert += vec3(rip.x, 0.0, -rip.y);
	}
	vec3 n = normalize(wnrm + pert * 0.9);
	ALBEDO = col;
	ROUGHNESS = rough;
	SPECULAR = 0.5;
	AO = mix(1.0, s.ao, 0.8);
	NORMAL = normalize((VIEW_MATRIX * vec4(n, 0.0)).xyz);
}
