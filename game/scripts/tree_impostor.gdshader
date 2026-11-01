shader_type spatial;
// Tree kit LOD2: 3 crossed vertical quads + a horizontal one, textures baked from LOD0 in Cycles
// (albedo x crown occlusion, object-space normals). Quads fade out when seen edge-on.
render_mode cull_disabled, depth_draw_opaque, diffuse_burley, specular_schlick_ggx;

#include "res://scripts/tree_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_disable;
uniform sampler2D normal_tex : hint_default_white, filter_linear_mipmap, repeat_disable;
uniform vec3 tint : source_color = vec3(1.0);
uniform float translucency = 0.35;

varying float v_facing;

void vertex() {
	if (!tree_lod(MODEL_MATRIX)) {
		VERTEX = vec3(0.0);
	} else {
		VERTEX += tree_wind_offset(VERTEX, vec3(0.0), vec4(0.0), UV2, MODEL_MATRIX, TIME);
	}
	vec3 wn = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
	vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_facing = abs(dot(wn, normalize(tree_cam - wp)));
}

void fragment() {
	if (tree_dither_discard(FRAGCOORD.xy)) {
		discard;
	}
	vec4 a = texture(albedo_tex, UV);
	// quads seen edge-on dissolve (the others cover the crown)
	float edge = smoothstep(0.08, 0.35, v_facing);
	ALPHA = a.a * edge * 1.15;
	ALPHA_SCISSOR_THRESHOLD = 0.45;
	float wet = tree_wind.w;
	ALBEDO = a.rgb * tint * mix(1.0, 0.82, wet);
	// baked object-space normal (Blender z up) -> Godot (x, z, -y) -> view space
	vec3 nb = texture(normal_tex, UV).rgb * 2.0 - 1.0;
	vec3 no = normalize(vec3(nb.x, nb.z, -nb.y));
	NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(no, 0.0)).xyz);
	ROUGHNESS = mix(0.75, 0.45, wet);
	SPECULAR = 0.3;
	BACKLIGHT = ALBEDO * translucency;
}
