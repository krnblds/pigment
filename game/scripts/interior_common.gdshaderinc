// Interior mapping ("parallax windows"), shared by interior_window.gdshader (kit buildings and
// tower facades) and proxy_building.gdshader (far boxes). See docs/agents/interiors/NOTES.md.
//
// Rooms are Pigment `pack_interiors` atlases: a Texture2DArray, two layers per room (lit, off),
// in the *pre-projected* format. A room is a box W x H (metres) at the window plane and D deep;
// its image is what a pinhole camera E metres in front of the window sees, so a room-space point
// q (x right, y up from the front rectangle's centre, z <= 0 into the room) is at
//     s = E / (E - q.z),  uv = (0.5 + q.x * s / W,  0.5 - q.y * s / H)
// and alpha holds the depth of the surface seen there (0 window plane .. 1 back wall). The view
// ray is marched through the box against that depth, so furniture has real parallax, then the
// colour is read where the ray first passes behind the stored surface.

uniform sampler2DArray interior_rooms : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform vec4 interior_dims[32];          // per room: W, H, D, E (metres)
uniform int interior_count = 0;          // rooms in the atlas (0 = no interiors)
uniform float interior_cell = 512.0;     // layer size in pixels (mip selection)
// room pick lists (atlas room indices): ground floor shops, then upper floors by light colour
uniform int rooms_ground[8];
uniform int n_ground = 0;
uniform int rooms_warm[8];
uniform int n_warm = 0;
uniform int rooms_cool[8];
uniform int n_cool = 0;
uniform int rooms_screen[8];
uniform int n_screen = 0;
uniform float interior_lit_energy = 2.4;  // lit room brightness (emission)
uniform float interior_off_energy = 0.22; // unlit room (city glow)
uniform float interior_tint = 0.35;       // how much the pane's lit colour tints its room

float ihash13(vec3 p) {
	p = fract(p * 0.1031);
	p += dot(p, p.zyx + 31.32);
	return fract((p.x + p.y) * p.z);
}

int pick_room(float h, int ground_floor, vec3 lit_col) {
	// Meridian-blue panes show screen rooms, fluorescent ones cool rooms, the rest warm rooms
	int k = 0;
	if (ground_floor == 1 && n_ground > 0) {
		k = rooms_ground[int(h * float(n_ground)) % n_ground];
	} else if (lit_col.b > lit_col.r * 1.25 && n_screen > 0) {
		k = rooms_screen[int(h * float(n_screen)) % n_screen];
	} else if (lit_col.b > lit_col.r * 0.82 && n_cool > 0) {
		k = rooms_cool[int(h * float(n_cool)) % n_cool];
	} else if (n_warm > 0) {
		k = rooms_warm[int(h * float(n_warm)) % n_warm];
	}
	return clamp(k, 0, max(interior_count - 1, 0));
}

vec2 room_uv(vec3 q, vec4 d) {
	float s = d.w / (d.w - q.z);
	return vec2(0.5 + q.x * s / d.x, 0.5 - q.y * s / d.y);
}

// p: point on the window plane in room space (metres), v: view ray in room space (v.z < 0).
// Returns the room colour (linear) for `layer`; `steps` = 0 reads the empty box only.
vec3 interior_trace(float layer, vec4 d, vec2 p, vec3 v, float lod, int steps) {
	vec3 o = vec3(p, 0.0);
	v.z = min(v.z, -1e-4);
	vec3 inv = 1.0 / v;
	float tx = ((v.x > 0.0 ? 0.5 : -0.5) * d.x - o.x) * inv.x;
	float ty = ((v.y > 0.0 ? 0.5 : -0.5) * d.y - o.y) * inv.y;
	float tz = (-d.z - o.z) * inv.z;
	float tmax = max(min(min(tx, ty), tz), 0.0);
	vec2 uv = room_uv(o + v * tmax, d);
	if (steps > 0) {
		float t0 = 0.0;
		float f0 = -1.0;     // (ray depth - stored depth) at t0: < 0 in front of the stored surface
		for (int i = 1; i <= steps; i++) {
			float t = tmax * float(i) / float(steps);
			vec3 q = o + v * t;
			vec2 u = room_uv(q, d);
			float f = -q.z - textureLod(interior_rooms, vec3(u, layer), lod).a * d.z;
			if (f >= 0.0) {
				// secant step between the last two samples
				float tt = mix(t0, t, clamp(f0 / (f0 - f), 0.0, 1.0));
				uv = room_uv(o + v * tt, d);
				break;
			}
			t0 = t;
			f0 = f;
		}
	}
	return textureLod(interior_rooms, vec3(clamp(uv, vec2(0.002), vec2(0.998)), layer), lod).rgb;
}

// Curtains / blinds just behind the glass (z = -0.06), seen with parallax. Returns coverage and
// a fold shade. kind: 0 none, 1 blinds lowered to `amount`, 2 curtains drawn to `amount`.
vec2 window_dressing(int kind, float amount, vec2 p, vec3 v, vec2 half_size) {
	if (kind == 0) {
		return vec2(0.0);
	}
	vec2 q = p + v.xy * (0.06 / max(-v.z, 1e-3));
	vec2 n = q / half_size;          // -1..1 over the pane
	if (kind == 1) {
		float lowered = step(1.0 - 2.0 * amount, n.y);
		float slat = smoothstep(0.15, 0.35, fract(q.y * 18.0)) * 0.6 + 0.4;
		return vec2(lowered * 0.92, slat);
	}
	float side = step(1.0 - amount, abs(n.x));
	float fold = 0.65 + 0.35 * sin(q.x * 42.0);
	return vec2(side, fold);
}
