shader_type spatial;
// Far proxy for a detailed building (town_loader.gd "heavy" policy): a unit box scaled to the
// building's bounds by the MultiMesh transform. Dark wet facade with a hashed grid of lit windows,
// so the skyline keeps its glow beyond the detail range. INSTANCE_CUSTOM.xy = per-building seed.

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
		EMISSION = c * lit * window_energy * (0.6 + 0.4 * hash(cell.yx + seed));
	}
}
