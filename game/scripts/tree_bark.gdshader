shader_type spatial;
// Tree kit bark: Pigment bark tile (tiling UVs from the generator), wet darkening, wind sway
// matching the leaves, per-instance LOD (tree_common).
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

#include "res://scripts/tree_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic;
uniform sampler2D rough_tex : hint_default_white, filter_linear_mipmap;
uniform vec3 tint : source_color = vec3(1.0);

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
	float wet = tree_wind.w;
	ALBEDO = texture(albedo_tex, UV).rgb * tint * mix(1.0, 0.62, wet) * v_ao;
	float r = texture(rough_tex, UV).r;
	ROUGHNESS = mix(r, r * 0.4, wet);
	SPECULAR = mix(0.35, 0.6, wet);
	NORMAL_MAP = texture(normal_tex, UV).rgb;
	NORMAL_MAP_DEPTH = 1.2;
}
