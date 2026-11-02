shader_type spatial;
// Far citizens (LOD2, ~360 tris) drawn with one MultiMesh per citizen model.  The vertex colours from
// tools/npc/build_citizens.py say which vertices are the left leg (R), right leg (G) and the arms (B);
// INSTANCE_CUSTOM.x = gait phase (0-1), .y = stride (0 standing .. 1 walking), .z = sleepwalker glow.

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_disable;
uniform sampler2D mask_tex : hint_default_black, filter_linear_mipmap, repeat_disable;
uniform float hip_y = 0.9;
uniform float shoulder_y = 1.4;
uniform float wet : hint_range(0.0, 1.0) = 1.0;
varying float v_sleep;

vec2 rot(vec2 p, float a) {
	float c = cos(a);
	float s = sin(a);
	return vec2(p.x * c - p.y * s, p.x * s + p.y * c);
}

void vertex() {
	float ph = INSTANCE_CUSTOM.x * TAU;
	float amp = INSTANCE_CUSTOM.y;
	float s = sin(ph);
	float legs = COLOR.r - COLOR.g;
	float la = -s * 0.42 * amp * legs;
	vec2 yz = VERTEX.yz - vec2(hip_y, 0.0);
	VERTEX.yz = rot(yz, la * step(VERTEX.y, hip_y + 0.05)) + vec2(hip_y, 0.0);
	float side = VERTEX.x > 0.0 ? 1.0 : -1.0;
	float aa = s * 0.32 * amp * side * COLOR.b;
	vec2 ayz = VERTEX.yz - vec2(shoulder_y, 0.0);
	VERTEX.yz = rot(ayz, aa) + vec2(shoulder_y, 0.0);
	VERTEX.y += abs(cos(ph)) * 0.025 * amp;
	v_sleep = INSTANCE_CUSTOM.z;
}

void fragment() {
	vec4 a = texture(albedo_tex, UV);
	vec3 m = texture(mask_tex, UV).rgb;
	float w = wet * m.g;
	ALBEDO = a.rgb * mix(1.0, 0.62, w);
	ROUGHNESS = mix(m.r, m.r * 0.35 + 0.05, w);
	float trim = smoothstep(0.8, 0.95, m.b);
	float sleep = smoothstep(0.3, 0.45, m.b) * (1.0 - smoothstep(0.6, 0.75, m.b));
	EMISSION = a.rgb * trim * 3.0 + vec3(0.25, 0.9, 1.0) * sleep * v_sleep * 2.5;
}
