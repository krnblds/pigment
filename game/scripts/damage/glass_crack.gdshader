shader_type spatial;
// Cracked-glass overlay (material_overlay on a damaged windscreen / rear window). The crack texture
// (tools/damage/make_glass_crack.py: a Pigment crack web + an impact star) is projected onto the
// pane in mesh space, centred on the impact point, along the pane's normal.
render_mode blend_mix, cull_disabled, depth_draw_never, specular_schlick_ggx;

uniform sampler2D crack_tex : source_color, filter_linear_mipmap, repeat_disable;
uniform vec3 center = vec3(0.0);
uniform vec3 normal = vec3(0.0, 0.0, 1.0);
uniform float size = 1.0;
uniform float rot = 0.0;

varying vec3 lp;

void vertex() {
	lp = VERTEX;
}

void fragment() {
	vec3 n = normalize(normal);
	vec3 t = normalize(cross(abs(n.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0), n));
	vec3 b = cross(n, t);
	vec3 r = lp - center;
	vec2 uv = vec2(dot(r, t), dot(r, b)) / size;
	float c = cos(rot);
	float s = sin(rot);
	uv = mat2(vec2(c, -s), vec2(s, c)) * uv + 0.5;
	float a = 0.0;
	if (uv.x > 0.0 && uv.x < 1.0 && uv.y > 0.0 && uv.y < 1.0) {
		a = texture(crack_tex, uv).a;
	}
	ALBEDO = vec3(0.9, 0.94, 1.0);
	ALPHA = a * 0.85;
	ROUGHNESS = 0.25;
	SPECULAR = 0.9;
	EMISSION = vec3(0.05, 0.06, 0.07) * a;
}
