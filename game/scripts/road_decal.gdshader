shader_type spatial;
// Road decal atlas (tools/town_roads.py decal_atlas_material): painted markings, cracks, patches, oil,
// skids, manholes and drains, cut out by the atlas alpha. They get wet like the asphalt under them
// (same world-space puddle mask, rain film), so a lane line through a puddle goes dark and glossy too.
render_mode blend_mix, depth_prepass_alpha, cull_back;

#include "res://scripts/road_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D rough_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D height_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D metal_tex : hint_default_black, filter_linear_mipmap_anisotropic, repeat_disable;
uniform float rain = 1.0;
uniform float film = 0.6;

varying vec3 wpos;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec4 c = texture(albedo_tex, UV);
	vec3 col = c.rgb;
	float rough = texture(rough_tex, UV).r;
	float h = texture(height_tex, UV).r;
	float metal = texture(metal_tex, UV).r;
	vec3 nm = texture(normal_tex, UV).rgb;
	float nstr = 1.0;
	if (rain > 0.0) {
		vec2 pd = rd_wetness(wpos.xz, h, 0.0, 1.0);
		float pud = pd.x * rain;
		float damp = max(pd.y, film) * rain;
		col *= mix(1.0, 0.8, damp);              // paint is not porous: it darkens less
		col *= mix(1.0, 0.55, pud);
		rough = mix(rough, min(rough, 0.2), damp);
		rough = mix(rough, 0.03, pud);
		nstr *= 1.0 - pud;
	}
	ALBEDO = col;
	ALPHA = c.a;
	ROUGHNESS = rough;
	METALLIC = metal;
	vec3 n = nm * 2.0 - 1.0;
	n.xy *= nstr;
	NORMAL_MAP = n * 0.5 + 0.5;
}
