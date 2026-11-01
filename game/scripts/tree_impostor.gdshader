shader_type spatial;
// Tree kit far LOD: 3 crossed vertical quads + a horizontal one, baked from LOD0 in Cycles (albedo x
// crown occlusion, object-space normals). Every variant lives in one shared atlas, so all impostors
// of a region are ONE MultiMesh of a unit mesh; INSTANCE_CUSTOM carries the variant:
//   x = atlas cell * 1000 + LOD2 start (m), y = vertical quad side, z = top quad side,
//   w = (far distance / 10) * 1000 + tree height
// UV = (u, v up) inside the view, UV2.x = view index (0..2 vertical, 3 top). Quads fade edge-on.
render_mode cull_disabled, depth_draw_opaque, diffuse_burley, specular_schlick_ggx;

#include "res://scripts/tree_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_disable;
uniform sampler2D normal_tex : hint_default_white, filter_linear_mipmap, repeat_disable;
uniform vec3 tint : source_color = vec3(1.0);
uniform float translucency = 0.35;
uniform float cols = 4.0;
uniform float rows = 16.0;

varying float v_facing;
varying vec2 v_uv;

void vertex() {
	vec4 c = INSTANCE_CUSTOM;
	float cell = floor(c.x / 1000.0 + 0.0001);
	float begin = c.x - cell * 1000.0;
	float fk = floor(c.w / 1000.0 + 0.0001);
	float far = fk * 10.0;
	float h = c.w - fk * 1000.0;
	float k = UV2.x;
	if (k < 2.5) {
		VERTEX *= c.y;
	} else {
		VERTEX.xz *= c.z;
		VERTEX.y = 0.62 * h;
	}
	// LOD band from the instance (the material's lod_range is not used here)
	vec3 o = MODEL_MATRIX[3].xyz;
	float d = distance(o.xz, tree_cam.xz) + abs(o.y - tree_cam.y) * 0.25;
	float hf = lod_fade * 0.5;
	v_fade = vec2(clamp((d - (begin - hf)) / lod_fade, 0.0, 1.0), clamp(((far + hf) - d) / lod_fade, 0.0, 1.0));
	if (v_fade.x <= 0.0 || v_fade.y <= 0.0) {
		VERTEX = vec3(0.0);
	} else {
		VERTEX += tree_wind_offset(VERTEX, vec3(0.0), vec4(0.0), vec2(VERTEX.y / max(h, 1.0), 2.0), MODEL_MATRIX, TIME);
	}
	float col = mod(cell, cols);
	float row = floor(cell / cols + 0.0001);
	v_uv = vec2((col * 4.0 + k + UV.x) / (cols * 4.0), (row + 1.0 - UV.y) / rows);
	vec3 wn = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
	vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_facing = abs(dot(wn, normalize(tree_cam - wp)));
}

void fragment() {
	if (tree_dither_discard(FRAGCOORD.xy, v_fade)) {
		discard;
	}
	vec4 a = texture(albedo_tex, v_uv);
	// quads seen edge-on dissolve (the others cover the crown)
	float edge = smoothstep(0.08, 0.35, v_facing);
	ALPHA = a.a * edge * 1.15;
	ALPHA_SCISSOR_THRESHOLD = 0.45;
	float wet = tree_wind.w;
	ALBEDO = a.rgb * tint * mix(1.0, 0.82, wet);
	// baked object-space normal (Blender z up) -> Godot (x, z, -y) -> view space
	vec3 nb = texture(normal_tex, v_uv).rgb * 2.0 - 1.0;
	vec3 no = normalize(vec3(nb.x, nb.z, -nb.y));
	NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(no, 0.0)).xyz);
	ROUGHNESS = mix(0.75, 0.45, wet);
	SPECULAR = 0.3;
	BACKLIGHT = ALBEDO * translucency;
}
