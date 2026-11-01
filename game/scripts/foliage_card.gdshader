// Pigment foliage cards (export_foliage): alpha-scissored, two-sided, light
// through the leaves from the atlas Translucency map (BACKLIGHT), a gentle
// wind sway on the free end of upright / hanging cards.
shader_type spatial;
render_mode cull_disabled, depth_draw_opaque;

uniform sampler2D albedo_alpha : source_color, filter_linear_mipmap, repeat_disable;
uniform sampler2D normal_map : hint_normal, filter_linear_mipmap, repeat_disable;
uniform sampler2D roughness_map : hint_default_white, filter_linear_mipmap, repeat_disable;
uniform sampler2D translucency : source_color, hint_default_black, filter_linear_mipmap, repeat_disable;
uniform float alpha_scissor = 0.5;
uniform float backlight_strength = 0.9;
uniform float normal_strength = 0.6;
// 0 = still; scaled per card by how far the vertex is from the card's base
uniform float wind = 0.3;
// 0 upright, 1 flat, 2 wall, 3 hanging (per MultiMesh)
uniform int mount = 0;

void vertex() {
	float t = VERTEX.y; // 0 at the base .. 1 at the top of the unit card
	float free_end = mount == 3 ? (1.0 - t) * (1.0 - t) : (mount == 1 ? 0.0 : t * t);
	vec3 origin = MODEL_MATRIX[3].xyz;
	float ph = dot(origin, vec3(0.37, 0.11, 0.53));
	float gust = sin(TIME * 1.7 + ph) * 0.6 + sin(TIME * 3.1 + ph * 1.7) * 0.25;
	float len = length(MODEL_MATRIX[1].xyz);
	// sway in world space, converted back to the card's local frame
	vec3 w = vec3(1.0, 0.0, 0.35) * gust * wind * free_end * len * 0.18;
	VERTEX += (inverse(mat3(MODEL_MATRIX)) * w);
	// upright / hanging cards shade like the plant's volume rather than a flat sheet
	if (mount == 0 || mount == 3) {
		NORMAL = normalize(mix(NORMAL, vec3(0.0, 1.0, 0.0), 0.65));
	}
}

void fragment() {
	vec4 c = texture(albedo_alpha, UV);
	ALBEDO = c.rgb;
	ALPHA = c.a;
	ALPHA_SCISSOR_THRESHOLD = alpha_scissor;
	ROUGHNESS = texture(roughness_map, UV).r;
	SPECULAR = 0.35;
	NORMAL_MAP = texture(normal_map, UV).rgb;
	NORMAL_MAP_DEPTH = normal_strength;
	BACKLIGHT = texture(translucency, UV).rgb * backlight_strength;
}
