// Tree kit (tools/trees): wind sway and per-instance LOD, shared by tree_leaves / tree_bark /
// tree_impostor. Vertex attributes (see assets/trees/index.json "attributes"):
//   COLOR.r branch flex, COLOR.g phase, COLOR.b leaf flutter, COLOR.a crown occlusion
//   UV2.x height / tree height, UV2.y 0 bark, 1 leaf card, 2 impostor
// Globals (project.godot [shader_globals], set by tree_kit.gd every frame):
//   tree_cam   the camera position (the main view's, also in shadow passes: the LOD is picked
//              once, from the player's camera)
//   tree_wind  xy: wind direction (world x, z), z: strength 0..1, w: wetness 0..1

global uniform vec3 tree_cam;
global uniform vec4 tree_wind;

// LOD band of this mesh: drawn while lod_range.x <= distance < lod_range.y, dithered over lod_fade.
uniform vec2 lod_range = vec2(0.0, 100000.0);
uniform float lod_fade = 6.0;

varying float v_fade_in;
varying float v_fade_out;

float tree_hash(vec2 p) {
	return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// Returns false when this instance is outside the LOD band (the caller collapses the vertex).
bool tree_lod(mat4 model) {
	vec3 o = model[3].xyz;
	float d = distance(o.xz, tree_cam.xz) + abs(o.y - tree_cam.y) * 0.25;
	float h = lod_fade * 0.5;
	v_fade_in = lod_range.x <= 0.0 ? 1.0 : clamp((d - (lod_range.x - h)) / lod_fade, 0.0, 1.0);
	v_fade_out = clamp(((lod_range.y + h) - d) / lod_fade, 0.0, 1.0);
	return v_fade_in > 0.0 && v_fade_out > 0.0;
}

// Dithered cross-fade between neighbouring LODs: the two bands keep complementary pixels.
bool tree_dither_discard(vec2 frag) {
	float r = tree_hash(floor(frag));
	return r >= v_fade_out || r < 1.0 - v_fade_in;
}

// Wind: a gusting main bend by height, branch sway, leaf flutter. Local (model) space.
vec3 tree_wind_offset(vec3 v, vec3 n, vec4 col, vec2 uv2, mat4 model, float t) {
	vec3 o = model[3].xyz;
	float ph = dot(o.xz, vec2(0.071, 0.113)) + col.g * 6.2832;
	vec2 wd = tree_wind.xy;
	// gust field drifting across the city
	float g = 0.55 + 0.45 * sin(t * 0.41 + dot(o.xz, wd) * 0.021) * sin(t * 0.17 + o.x * 0.013 + o.z * 0.009);
	float s = tree_wind.z * (0.45 + 0.55 * g);
	mat3 inv = transpose(mat3(model));
	vec3 wl = normalize(inv * vec3(wd.x, 0.0, wd.y));
	float h = clamp(uv2.x, 0.0, 1.0);
	float y = max(v.y, 0.0);
	// main bend: grows with height^2, slow oscillation around a leaning mean
	float bend = h * y * 0.022 * s * (1.0 + 0.4 * sin(t * 1.1 + ph));
	vec3 off = wl * bend;
	off.y -= bend * bend / max(y, 1.0) * 0.5;
	// branches: flex weight, faster, partly vertical
	float b = col.r * s * 0.09 * sin(t * 2.3 + ph * 1.7 + v.y * 0.15);
	off += (wl * 0.6 + vec3(0.0, 0.5, 0.0)) * b;
	// leaves: flutter along the card normal, high frequency
	off += n * col.b * s * 0.045 * sin(t * 8.5 + ph * 5.0 + v.x * 3.0 + v.z * 2.0);
	return off;
}
