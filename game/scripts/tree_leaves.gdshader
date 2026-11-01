shader_type spatial;
// Tree kit leaf / needle / blossom cards: alpha scissor, two-sided with the crown's bent normals
// (no back-face flip), translucency (BACKLIGHT: leaves glow when a street lamp is behind them),
// crown occlusion from COLOR.a, rain wetness, wind sway, per-instance LOD (tree_common).
render_mode cull_disabled, depth_draw_opaque, diffuse_burley, specular_schlick_ggx;

#include "res://scripts/tree_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D mask_tex : hint_default_white, filter_linear_mipmap, repeat_disable;
uniform vec3 tint : source_color = vec3(1.0);
uniform float translucency = 0.9;
uniform float alpha_cut = 0.42;
uniform float occlusion = 0.7;

varying float v_ao;

void vertex() {
	if (!tree_lod(MODEL_MATRIX)) {
		VERTEX = vec3(0.0);
	} else {
		VERTEX += tree_wind_offset(VERTEX, NORMAL, COLOR, UV2, MODEL_MATRIX, TIME);
	}
	v_ao = COLOR.a;
}

void fragment() {
	if (tree_dither_discard(FRAGCOORD.xy)) {
		discard;
	}
	vec4 a = texture(albedo_tex, UV);
	// keep coverage in the small mips (alpha-tested foliage thins out at distance otherwise)
	float lod = textureQueryLod(albedo_tex, UV).y;
	ALPHA = clamp(a.a * (1.0 + max(lod - 1.0, 0.0) * 0.22), 0.0, 1.0);
	ALPHA_SCISSOR_THRESHOLD = alpha_cut;
	float wet = tree_wind.w;
	ALBEDO = a.rgb * tint * mix(1.0 - occlusion, 1.0, v_ao) * mix(1.0, 0.8, wet);
	vec3 m = texture(mask_tex, UV).rgb;
	ROUGHNESS = mix(m.r, m.r * 0.45, wet);
	SPECULAR = 0.4;
	NORMAL_MAP = texture(normal_tex, UV).rgb;
	NORMAL_MAP_DEPTH = 0.9;
	// cards carry the crown's outward normal on both sides: undo the engine's back-face flip
	if (!FRONT_FACING) {
		NORMAL = -NORMAL;
	}
	BACKLIGHT = ALBEDO * m.g * translucency;
	AO = mix(0.5, 1.0, v_ao);
	AO_LIGHT_AFFECT = 0.4;
}
