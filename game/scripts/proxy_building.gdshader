shader_type spatial;
// Far proxy for a detailed building (town_loader.gd "heavy" policy): a unit box scaled to the
// building's bounds by the MultiMesh transform. Dark wet facade with a hashed grid of lit windows,
// so the skyline keeps its glow beyond the detail range. INSTANCE_CUSTOM.xy = per-building seed.
// Lit windows show a room from the interior atlas (interior_common.gdshaderinc) through the cheap
// path: one parallax plane half-way into the room, read at a coarse mip.

#include "res://scripts/interior_common.gdshaderinc"

uniform vec3 facade : source_color = vec3(0.045, 0.043, 0.05);
uniform vec2 window_size = vec2(2.2, 3.3);         // m: bay width, storey height
uniform float lit_fraction = 0.2;
uniform float window_energy = 3.5;
uniform vec3 warm : source_color = vec3(1.0, 0.62, 0.32);
uniform vec3 cool : source_color = vec3(0.45, 0.8, 1.0);
uniform vec3 neon : source_color = vec3(1.0, 0.25, 0.75);

varying vec3 local_m;      // box-local position in metres
varying vec3 local_n;
varying flat vec2 seed;
varying vec3 scale_m;

float hash(vec2 p) {
	p = fract(p * vec2(123.34, 456.21));
	p += dot(p, p + 45.32);
	return fract(p.x * p.y);
}

void vertex() {
	vec3 scale = vec3(length(MODEL_MATRIX[0].xyz), length(MODEL_MATRIX[1].xyz), length(MODEL_MATRIX[2].xyz));
	local_m = (VERTEX + 0.5) * scale;
	local_n = NORMAL;
	seed = INSTANCE_CUSTOM.xy;
	scale_m = scale;
}

void fragment() {
	ALBEDO = facade;
	ROUGHNESS = 0.55;
	SPECULAR = 0.5;
	if (abs(local_n.y) < 0.5) {
		float u = abs(local_n.x) > 0.5 ? local_m.z : local_m.x;
		vec2 g = vec2(u, local_m.y - 0.6) / window_size;
		vec2 cell = floor(g);
		vec2 f = fract(g);
		float h = hash(cell + seed * 97.0 + local_n.xz * 13.0);
		float pane = step(0.18, f.x) * step(f.x, 0.82) * step(0.22, f.y) * step(f.y, 0.78);
		float lit = step(1.0 - lit_fraction, h) * pane * step(1.0, cell.y);
		vec3 c = h > 0.97 ? neon : (h > 0.88 ? cool : warm);
		float k = window_energy * (0.6 + 0.4 * hash(cell.yx + seed));
		vec3 e = c * lit * k;
		if (interior_count > 0 && lit > 0.5) {
			// view ray in box-local metres -> the pane's tangent space (box faces are axis aligned)
			vec3 dir_w = normalize((INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz - CAMERA_POSITION_WORLD);
			vec3 dl = normalize(inverse(mat3(MODEL_MATRIX)) * dir_w * scale_m);
			vec3 n = normalize(local_n);
			vec3 right = normalize(cross(vec3(0.0, 1.0, 0.0), n));
			vec3 v = vec3(dot(dl, right), dl.y, dot(dl, n));
			int room = pick_room(fract(h * 53.1), 0, c);
			vec4 d = interior_dims[room];
			vec2 p = (f - 0.5) * vec2(0.64, 0.56) * window_size;
			float flip = abs(local_n.x) > 0.5 ? sign(local_n.x) : -sign(local_n.z);
			p.x *= flip;
			// one plane half-way into the room
			vec2 q = p + v.xy * (0.5 * d.z / max(-v.z, 0.15));
			float s = d.w / (d.w + 0.5 * d.z);
			vec2 uv = clamp(vec2(0.5 + q.x * s / d.x, 0.5 - q.y * s / d.y), vec2(0.01), vec2(0.99));
			vec3 room_col = textureLod(interior_rooms, vec3(uv, float(room * 2)), 4.0).rgb;
			e = mix(c * k, room_col * mix(vec3(1.0), c, interior_tint) * k * 1.6, 0.75) * lit;
		}
		EMISSION = e;
	}
}
