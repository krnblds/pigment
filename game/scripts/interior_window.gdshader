shader_type spatial;
// Kit buildings (building_a / b / c) with interior-mapped windows.
//
// The building is one Pigment material (albedo / ORM / normal / emission). Its glass panes are
// found through a window map (Pigment `export_window_map`): a UV-space texture holding pane
// index + 1, and a pane table (centre, right, normal, size, centre UV per pane; built by
// town_loader.gd from <asset>_panes.json). On a pane the fragment's object-space position gives
// its place on the pane in metres, the view ray goes into pane tangent space, and a room from the
// interior atlas is ray-marched behind it (interior_common.gdshaderinc). The room comes from a
// hash of the pane's world position, so neighbouring windows differ; whether it is lit comes
// from the variant's own lit-window selection (Pigment's emission at the pane centre), so the
// lit-window palettes and variant seeds are kept. The glass on top keeps Pigment's dirt and
// gets a Fresnel balance against the environment / SSR reflection.

#include "res://scripts/interior_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic;
uniform sampler2D orm_tex : hint_default_white, filter_linear_mipmap_anisotropic;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic;
uniform sampler2D emission_tex : source_color, hint_default_black, filter_linear_mipmap_anisotropic;
uniform bool use_normal = true;
uniform bool use_emission = true;
uniform float emission_energy = 7.8;
uniform float roughness_mul = 0.85;
uniform float alpha_scissor = 0.15;

uniform sampler2D window_map : filter_nearest, repeat_disable;   // pane index + 1 (R8)
uniform sampler2D pane_tex : filter_nearest, repeat_disable;     // RGBAF, x = pane, y = row
uniform int pane_count = 0;
uniform float ground_floor_top = 4.2;     // object-space height (m): panes below are shops

varying vec3 obj_pos;

void vertex() {
	obj_pos = VERTEX;
}

void fragment() {
	vec4 alb = texture(albedo_tex, UV);
	vec3 orm = texture(orm_tex, UV).rgb;
	ALBEDO = alb.rgb;
	AO = orm.r;
	ROUGHNESS = orm.g * roughness_mul;
	METALLIC = orm.b;
	if (use_normal) {
		NORMAL_MAP = texture(normal_tex, UV).rgb;
	}
	vec3 em = use_emission ? texture(emission_tex, UV).rgb * emission_energy : vec3(0.0);
	float alpha = alb.a;

	if (pane_count > 0 && interior_count > 0) {
		ivec2 ws = textureSize(window_map, 0);
		ivec2 wt = clamp(ivec2(UV * vec2(ws)), ivec2(0), ws - 1);
		int idx = int(texelFetch(window_map, wt, 0).r * 255.0 + 0.5) - 1;
		if (idx >= 0 && idx < pane_count) {
			vec4 c0 = texelFetch(pane_tex, ivec2(idx, 0), 0);   // centre, width
			vec4 c1 = texelFetch(pane_tex, ivec2(idx, 1), 0);   // right, height
			vec4 c2 = texelFetch(pane_tex, ivec2(idx, 2), 0);   // outward normal
			vec4 c3 = texelFetch(pane_tex, ivec2(idx, 3), 0);   // centre uv
			vec3 right = c1.xyz;
			vec3 nrm = c2.xyz;
			vec3 up = cross(nrm, right);
			vec2 pane = vec2(c0.w, c1.w);
			vec3 rel = obj_pos - c0.xyz;
			vec2 pp = vec2(dot(rel, right), dot(rel, up));          // metres on the pane

			vec3 wpos = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
			vec3 dir_w = normalize(wpos - CAMERA_POSITION_WORLD);
			vec3 dir_o = normalize(inverse(mat3(MODEL_MATRIX)) * dir_w);
			vec3 v = vec3(dot(dir_o, right), dot(dir_o, up), dot(dir_o, nrm));

			// per-pane seeds from the pane's world position
			vec3 cw = (MODEL_MATRIX * vec4(c0.xyz, 1.0)).xyz;
			float h = ihash13(floor(cw * 4.0) + 0.37);
			float h2 = ihash13(floor(cw * 4.0).zxy + 11.1);
			float h3 = ihash13(floor(cw * 4.0).yzx + 5.7);

			// lit or not: the variant's lit-window layers (emission at the pane centre)
			vec3 lit_col = use_emission ? textureLod(emission_tex, c3.xy, 0.0).rgb : vec3(0.0);
			float lum = max(lit_col.r, max(lit_col.g, lit_col.b));
			bool lit = lum > 0.02;
			vec3 tint = lit ? lit_col / lum : vec3(1.0, 0.62, 0.32);
			int room = pick_room(h, c0.y < ground_floor_top ? 1 : 0, tint);
			vec4 d = interior_dims[room];
			// fit the room round the pane: scale up for big panes, the pane sits on a sill,
			// off-centre by a random amount
			float s = max(1.0, max(pane.x / (0.82 * d.x), pane.y / (0.8 * d.y)));
			d *= s;
			float slack = max(0.0, 0.5 * (d.x - pane.x) - 0.12);
			float sill = clamp(0.9 * s, 0.04, d.y - pane.y - 0.04);
			vec2 p = pp + vec2((h2 * 2.0 - 1.0) * slack * 0.7, -0.5 * d.y + sill + 0.5 * pane.y);

			float dist = length(wpos - CAMERA_POSITION_WORLD);
			int steps = dist < 45.0 ? 12 : (dist < 140.0 ? 5 : 0);
			float fw = max(length(dFdx(pp)), length(dFdy(pp)));
			float lod = max(log2(max(fw * interior_cell / d.x, 1e-5)), 0.0);
			float layer = float(room * 2 + (lit ? 0 : 1));
			vec3 col = interior_trace(layer, d, p, v, lod, steps);
			float energy = lit ? interior_lit_energy * (0.7 + 0.6 * h3) : interior_off_energy;
			col *= mix(vec3(1.0), tint, lit ? interior_tint : 0.0) * energy;

			// curtains and blinds (from the pane seed), backlit when the room is lit
			int kind = h3 < 0.2 ? 1 : (h3 < 0.38 ? 2 : 0);
			vec2 dress = window_dressing(kind, 0.2 + 0.55 * fract(h3 * 7.3), pp, v, 0.5 * pane);
			vec3 cloth = (kind == 1 ? vec3(0.75, 0.72, 0.65) : mix(vec3(0.5, 0.18, 0.12), vec3(0.2, 0.25, 0.4), fract(h2 * 5.1)));
			vec3 dressed = cloth * dress.y * (lit ? tint * interior_lit_energy * 0.32 : vec3(0.02));
			col = mix(col, dressed, dress.x);

			// the glass: Pigment's grime (roughness above clean glass) dulls it; Fresnel splits
			// what is seen through it from what it reflects (env / SSR via the PBR specular)
			float dirt = clamp((orm.g - 0.06) * 2.5, 0.0, 1.0);
			float ndv = clamp(dot(NORMAL, VIEW), 0.0, 1.0);
			float F = 0.04 + 0.96 * pow(1.0 - ndv, 5.0);
			ALBEDO = alb.rgb * dirt * 0.35;
			ROUGHNESS = mix(0.03, 0.4, dirt);
			METALLIC = 0.0;
			SPECULAR = 0.5;
			AO = 1.0;
			em = col * (1.0 - F) * (1.0 - 0.45 * dirt);
			alpha = 1.0;
		}
	}
	EMISSION = em;
	ALPHA = alpha;
	ALPHA_SCISSOR_THRESHOLD = alpha_scissor;
}
