shader_type spatial;
// World tower facades (tools/world/world_meshes.py): the Pigment facade tile (8 x 8 m) in metre
// UVs, with an interior-mapped room behind every pane of its 2 m x 4 m window grid. The grid and
// pane sizes are the tile's (tools/town_textures.py FACADE_WINDOW); which panes are lit and their
// colours follow the Blender facade material (a hash of the pane's cell, ~20 % lit). Towers use
// office / server / hydroponics rooms. See interior_common.gdshaderinc.

#include "res://scripts/interior_common.gdshaderinc"

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic;
uniform float roughness = 0.5;
uniform vec2 grid = vec2(2.0, 4.0);        // bay, storey (m)
uniform vec2 pane_size = vec2(1.86, 3.4);  // curtain wall; punched windows 1.5 x 2.6
uniform float sill = 0.55;
uniform float lit_fraction = 0.2;

void fragment() {
	// metre UVs: u along the wall, glTF v = 1 - height
	vec2 m = vec2(UV.x, 1.0 - UV.y);
	ALBEDO = texture(albedo_tex, m / 8.0).rgb;
	ROUGHNESS = roughness;
	METALLIC = 0.0;
	vec2 cell = floor(m / grid);
	vec2 f = m - cell * grid - vec2(0.5 * grid.x, sill + 0.5 * pane_size.y);
	vec3 nw = normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);
	if (interior_count > 0 && all(lessThan(abs(f), 0.5 * pane_size)) && abs(nw.y) < 0.5) {
		vec3 wpos = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
		vec3 upw = vec3(0.0, 1.0, 0.0);
		vec3 right = normalize(cross(upw, nw));
		vec3 cw = wpos - right * f.x - upw * f.y;          // the pane's world centre
		float h = ihash13(floor(cw * 2.0) + 0.37);
		float h2 = ihash13(floor(cw * 2.0).zxy + 11.1);
		float h3 = ihash13(floor(cw * 2.0).yzx + 5.7);
		bool lit = h < lit_fraction;
		// the Blender facade palette: warm, soft warm, cool white, Meridian blue
		float hc = fract(h2 * 13.7);
		vec3 tint = hc < 0.55 ? vec3(1.0, 0.62, 0.3) : (hc < 0.8 ? vec3(1.0, 0.75, 0.5) : (hc < 0.94 ? vec3(0.75, 0.9, 1.0) : vec3(0.35, 0.55, 1.0)));
		vec3 dir_w = normalize(wpos - CAMERA_POSITION_WORLD);
		vec3 v = vec3(dot(dir_w, right), dot(dir_w, upw), dot(dir_w, nw));
		int room = pick_room(fract(h * 31.7), 0, tint);
		vec4 d = interior_dims[room];
		float s = max(1.0, max(pane_size.x / (0.9 * d.x), pane_size.y / (0.92 * d.y)));
		d *= s;
		float slack = max(0.0, 0.5 * (d.x - pane_size.x) - 0.05);
		float sl = clamp(0.4 * s, 0.02, d.y - pane_size.y - 0.02);
		vec2 p = f + vec2((h2 * 2.0 - 1.0) * slack * 0.6, -0.5 * d.y + sl + 0.5 * pane_size.y);
		float dist = length(wpos - CAMERA_POSITION_WORLD);
		int steps = dist < 60.0 ? 10 : (dist < 160.0 ? 4 : 0);
		float fw = max(length(dFdx(m)), length(dFdy(m)));
		float lod = max(log2(max(fw * interior_cell / d.x, 1e-5)), 0.0);
		vec3 col = interior_trace(float(room * 2 + (lit ? 0 : 1)), d, p, v, lod, steps);
		col *= mix(vec3(1.0), tint, lit ? interior_tint : 0.0) * (lit ? interior_lit_energy * (0.6 + 0.6 * h3) : interior_off_energy);
		int kind = h3 < 0.25 ? 1 : 0;      // office blinds
		vec2 dress = window_dressing(kind, 0.15 + 0.6 * fract(h3 * 7.3), f, v, 0.5 * pane_size);
		col = mix(col, vec3(0.75, 0.75, 0.72) * dress.y * (lit ? tint * interior_lit_energy * 0.3 : vec3(0.02)), dress.x);
		float ndv = clamp(dot(NORMAL, VIEW), 0.0, 1.0);
		float F = 0.04 + 0.96 * pow(1.0 - ndv, 5.0);
		ALBEDO *= 0.15;
		ROUGHNESS = 0.05;
		SPECULAR = 0.5;
		EMISSION = col * (1.0 - F);
	}
}
