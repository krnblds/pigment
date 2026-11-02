// Citizens: one 1024 atlas per character (tools/npc/compose_atlas.py).
//   albedo: rgb + alpha (hair / brows cut-out)
//   mask:   R roughness, G rain response, B emission (1 = glowing trims)
// Per instance: trim glow strength.  Included by citizen.gdshader (opaque) and
// citizen_cutout.gdshader (hair / brows, alpha scissor, two-sided).

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D mask_tex : hint_default_black, filter_linear_mipmap, repeat_disable;
uniform float wet : hint_range(0.0, 1.0) = 1.0;        // the rain (manager sets it on every material)
uniform vec3 trim_color : source_color = vec3(0.1, 0.85, 1.0);
instance uniform float trim_glow : hint_range(0.0, 4.0) = 1.0;

void fragment() {
	vec4 a = texture(albedo_tex, UV);
#ifdef CUTOUT
	if (a.a < 0.45) { discard; }
#endif
	vec3 m = texture(mask_tex, UV).rgb;
	float w = wet * m.g;
	// wet cloth / skin: darker and glossier
	ALBEDO = a.rgb * mix(1.0, 0.62, w);
	ROUGHNESS = mix(m.r, m.r * 0.35 + 0.05, w);
	SPECULAR = 0.5 + 0.2 * w;
	NORMAL_MAP = texture(normal_tex, UV).rgb;
	NORMAL_MAP_DEPTH = 1.0 - 0.4 * w;
	float trim = smoothstep(0.8, 0.95, m.b);
	EMISSION = a.rgb * trim * trim_glow * 3.0;
}
