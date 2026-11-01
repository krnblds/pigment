shader_type spatial;
// The open-world road surfaces (asphalt, paving, concrete, the curb / gutter trim sheet), matching the
// Blender material in tools/town_roads.py surface_material() / trim_material(): Pigment's seamless tiles
// in metres (mesh UVs are metres along / across the road; the trim sheet's UVs address its strips), a
// second rotated sample blended by world noise so the tile never visibly repeats, a macro tone and
// roughness drift over tens of metres, and the wet-surface model:
//   damp     Blender's damp mask (broad noise + wet_bias + the height map's low spots) plus, while it
//            rains, a water film over the whole surface: darker (porous), glossy where the film covers
//            the texture, the aggregate's high points poke through and stay rougher
//   puddles  standing water in the low spots: darker still, mirror-smooth, flat normal, rain ripples
// wet_bias (gutters, profile sag points) comes in as vertex colour: COLOR.r = 1 - wet_bias, so meshes
// without colours are dry (tools/godot/export_town.py writes it; town_loader.gd derives it otherwise).
render_mode cull_back;

#include "res://scripts/road_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rough_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D height_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D metal_tex : hint_default_black, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool use_metal = false;        // trim sheet: drain grates are metal
uniform float tile_m = 4.0;            // metres per tile (1 = use the UVs as they are)
uniform bool world_box = false;        // concrete: world-space projection instead of UVs
uniform bool anti_tile = true;
uniform float macro = 0.22;            // tone variation
uniform float wet = 1.0;               // how much this surface collects water (0 = never)
uniform float film = 0.75;             // how much of it a rain film covers (0..1) while it rains
uniform float rain = 1.0;              // set by the game: 1 raining, 0 dry
uniform float normal_strength = 1.0;
uniform float ripple_strength = 1.0;

varying vec3 wpos;
varying vec3 wnrm;

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
	float metal = use_metal ? texture(metal_tex, uv1).r : 0.0;
	if (anti_tile && !world_box) {
		float c = cos(0.6458), s = sin(0.6458);   // 37 degrees
		vec2 uv2 = mat2(vec2(c, s), vec2(-s, c)) * uv1 + vec2(0.31, 0.57);
		float k = smoothstep(0.42, 0.58, rd_fbm(wpos.xz * 0.07, 2));
		if (k > 0.0) {
			// the second sample is rotated, so its normal is turned back into the first's frame
			vec3 n2 = texture(normal_tex, uv2).rgb * 2.0 - 1.0;
			n2.xy = mat2(vec2(c, -s), vec2(s, c)) * n2.xy;
			col = mix(col, texture(albedo_tex, uv2).rgb, k);
			rough = mix(rough, texture(rough_tex, uv2).r, k);
			h = mix(h, texture(height_tex, uv2).r, k);
			nm = mix(nm, n2 * 0.5 + 0.5, k);
		}
	}
	// macro tone / roughness drift
	float mv = rd_fbm(wpos.xz * 0.045 + 3.0, 3);
	col *= mix(1.0 - macro, 1.0 + macro, mv);
	rough = clamp(rough + (mv - 0.5) * 0.25, 0.0, 1.0);
	float nstr = normal_strength;
	vec2 ripple = vec2(0.0);
	float w = wet * rain;
	if (w > 0.0) {
		float wet_bias = 1.0 - COLOR.r;
		vec2 pd = rd_wetness(wpos.xz, h, wet_bias, wet);
		float pud = pd.x * rain;
		// damp: Blender's mask, plus the rain film over everything that can get wet
		float damp = max(pd.y, film) * rain;
		// the film fills the texture's pores: the aggregate's high points poke through it
		float tips = smoothstep(0.6, 0.85, h) * (1.0 - pud);
		col *= mix(1.0, 0.6, damp);                              // porous surfaces darken when wet
		col *= mix(1.0, 0.5, pud);
		float film_rough = mix(0.05, 0.3, tips);
		rough = mix(rough, min(rough, film_rough), damp);
		rough = mix(rough, 0.02, pud);
		metal *= 1.0 - pud;
		nstr *= mix(1.0, 0.55, damp) * (1.0 - pud);             // water evens the surface out
		if (pud > 0.01 && ripple_strength > 0.0) {
			ripple = rd_ripples(wpos.xz, TIME) * pud * ripple_strength;
		}
	}
	ALBEDO = col;
	ROUGHNESS = rough;
	METALLIC = metal;
	SPECULAR = 0.5;
	// normal map scaled by hand (NORMAL_MAP_DEPTH can't go to 0 per pixel), ripples on top
	vec3 n = nm * 2.0 - 1.0;
	n.xy = n.xy * nstr + ripple;
	NORMAL_MAP = normalize(n) * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 1.0;
}
