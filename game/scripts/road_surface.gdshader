shader_type spatial;
// The open-world road surfaces (asphalt, paving, concrete), matching the Blender
// material in tools/town_roads.py surface_material(): Pigment's seamless tiles in
// metres (mesh UVs are metres along / across the road), a second rotated sample
// blended by world noise so the tile never visibly repeats, a macro tone and
// roughness drift over tens of metres, and rain: damp darkening plus puddles in
// the low spots of the height map.
render_mode cull_back;

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rough_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D height_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float tile_m = 4.0;            // metres per tile
uniform bool world_box = false;        // concrete: world-space projection instead of UVs
uniform bool anti_tile = true;
uniform float macro = 0.22;            // tone variation
uniform float wet = 1.0;               // how much this surface collects water (0 = never)
uniform float rain = 1.0;              // set by the game: 1 raining, 0 dry
uniform float normal_strength = 1.0;

varying vec3 wpos;
varying vec3 wnrm;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p) {
	vec2 i = floor(p), f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
	float s = 0.0, a = 0.5;
	for (int i = 0; i < 4; i++) { s += vnoise(p) * a; p = p * 2.03 + 17.1; a *= 0.5; }
	return s / 0.9375;
}

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	wnrm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	vec2 uv1;
	if (world_box) {
		vec3 a = abs(wnrm);
		uv1 = (a.y > max(a.x, a.z) ? wpos.xz : (a.x > a.z ? wpos.zy : wpos.xy)) / tile_m;
	} else {
		uv1 = UV / tile_m;
	}
	vec3 col = texture(albedo_tex, uv1).rgb;
	float rough = texture(rough_tex, uv1).r;
	float h = texture(height_tex, uv1).r;
	vec3 nm = texture(normal_tex, uv1).rgb;
	if (anti_tile && !world_box) {
		float c = cos(0.6458), s = sin(0.6458);   // 37 degrees
		vec2 uv2 = mat2(vec2(c, s), vec2(-s, c)) * uv1 + vec2(0.31, 0.57);
		float k = smoothstep(0.42, 0.58, fbm(wpos.xz * 0.07));
		// the second sample is rotated, so its normal is turned back into the first's frame
		vec3 n2 = texture(normal_tex, uv2).rgb * 2.0 - 1.0;
		n2.xy = mat2(vec2(c, -s), vec2(s, c)) * n2.xy;
		col = mix(col, texture(albedo_tex, uv2).rgb, k);
		rough = mix(rough, texture(rough_tex, uv2).r, k);
		h = mix(h, texture(height_tex, uv2).r, k);
		nm = mix(nm, n2 * 0.5 + 0.5, k);
	}
	// macro tone / roughness drift
	float mv = fbm(wpos.xz * 0.045 + 3.0);
	col *= mix(1.0 - macro, 1.0 + macro, mv);
	rough = clamp(rough + (mv - 0.5) * 0.25, 0.0, 1.0);
	// rain: damp everywhere it can get wet, standing water in the low spots
	float w = wet * rain;
	float pud = 0.0;
	if (w > 0.0) {
		float field = fbm(wpos.xz * 0.11 + 7.0) * 0.75 + (1.0 - h) * 0.45;
		pud = smoothstep(0.55, 0.63, field) * w;
		float damp = w * 0.8;
		col = mix(col, vec3(0.0), damp * 0.35);
		col = mix(col, col * vec3(0.45, 0.45, 0.47), pud);
		rough = mix(rough, 0.25, damp * 0.4);
		rough = mix(rough, 0.03, pud);
	}
	ALBEDO = col;
	ROUGHNESS = rough;
	METALLIC = 0.0;
	SPECULAR = 0.5;
	NORMAL_MAP = mix(nm, vec3(0.5, 0.5, 1.0), pud);   // standing water is flat
	NORMAL_MAP_DEPTH = normal_strength;
}
