// Shared by road_surface.gdshader and road_decal.gdshader: the noise and the wet-surface model of
// tools/town_roads.py (_noise, _wetness), plus the game-only rain film and drop ripples.

float rd_hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
vec2 rd_hash2(vec2 p) {
	return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453);
}
float rd_vnoise(vec2 p) {
	vec2 i = floor(p), f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(rd_hash(i), rd_hash(i + vec2(1, 0)), u.x), mix(rd_hash(i + vec2(0, 1)), rd_hash(i + vec2(1, 1)), u.x), u.y);
}
float rd_fbm(vec2 p, int oct) {
	float s = 0.0, a = 0.5, n = 0.0;
	for (int i = 0; i < oct; i++) { s += rd_vnoise(p) * a; n += a; p = p * 2.03 + 17.1; a *= 0.5; }
	return s / n;
}

// Blender _wetness(): broad noise + the mesh's wet_bias (gutters) + the texture's low spots.
// Returns (puddle, damp), both 0..1. strength: the surface's "wet" (asphalt 1, paving 0.6 ...).
vec2 rd_wetness(vec2 xz, float height, float wet_bias, float strength) {
	float big = rd_fbm(xz * 0.11 + 7.0, 3);
	float fine = rd_vnoise(xz * 0.9 + 3.3);
	float v = big + wet_bias * 0.32 + (fine - 0.5) * 0.08 + (0.5 - height) * 0.9;
	float lo = 0.545 - 0.1 * (strength - 1.0);
	float pud = clamp((v - lo) / 0.05, 0.0, 1.0);
	float damp = clamp((v - (lo - 0.14)) / 0.14, 0.0, 1.0);
	return vec2(pud, damp);
}

// Rain drops on standing water: expanding rings on a jittered grid, two layers. Returns a tangent-space
// normal offset (xy) to add to a flat water normal.
vec2 rd_ripples(vec2 p, float t) {
	vec2 acc = vec2(0.0);
	for (int layer = 0; layer < 2; layer++) {
		vec2 q = p * (layer == 0 ? 2.6 : 3.7) + float(layer) * 11.3;
		vec2 cell = floor(q);
		for (int j = -1; j <= 1; j++) {
			for (int i = -1; i <= 1; i++) {
				vec2 c = cell + vec2(float(i), float(j));
				vec2 h = rd_hash2(c);
				vec2 d = q - (c + 0.15 + h * 0.7);
				float ph = fract(t * (0.9 + h.y * 0.5) + h.x);       // 0..1 life of this cell's drop
				float r = ph * 1.1;
				float dist = length(d);
				float x = (dist - r) * 14.0;
				float ring = sin(x * 3.14159) * exp(-x * x) * (1.0 - ph) * (1.0 - ph);
				acc += ring * d / max(dist, 1e-3);
			}
		}
	}
	return acc * 0.35;
}
