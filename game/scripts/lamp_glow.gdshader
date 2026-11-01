shader_type spatial;
// Far street lamps (town_loader.gd _lamp_glows): a soft additive halo, camera facing, sized to stay a few
// pixels wide far away. Fades in where the lamp's real OmniLight fades out (fade_in, metres), out far away.
render_mode blend_add, unshaded, depth_draw_never, cull_disabled, fog_disabled;

uniform vec2 fade_in = vec2(45.0, 60.0);
uniform float fade_out = 700.0;
uniform float energy = 1.2;

varying float vis;

void vertex() {
	vec3 centre = (MODELVIEW_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
	float d = length(centre);
	float size = 2.2 + d * 0.012;                     // ~3 m near the fade, grows so it never vanishes
	vis = smoothstep(fade_in.x, fade_in.y, d) * (1.0 - smoothstep(fade_out * 0.6, fade_out, d));
	vec3 v = centre + vec3(VERTEX.xy * size, 0.0);
	POSITION = PROJECTION_MATRIX * vec4(v, 1.0);
}

void fragment() {
	vec2 p = UV * 2.0 - 1.0;
	float r2 = dot(p, p);
	float core = exp(-r2 * 18.0);
	float halo = exp(-r2 * 4.0) * 0.35;
	float a = (core + halo) * max(1.0 - r2, 0.0) * vis;
	ALBEDO = COLOR.rgb * energy * a;     // unshaded + additive: albedo is the output
	if (a < 0.002) {
		discard;
	}
}
