// Night-city sky: samples a panorama baked by tools/sky/make_sky.py.
//
// The HDRs use the glTF / Pigment equirect convention: the image centre looks along
// -Z (Blender +Y, which is where town_layout.json's Godot transforms put it) and u
// grows towards +X.  The mapping is written out here instead of using
// PanoramaSkyMaterial so the orientation never depends on engine internals: the
// MERIDIAN glow and the searchlights sit over the same streets as in Blender.
shader_type sky;

uniform sampler2D panorama : filter_linear, repeat_enable, hint_default_black;
// Scales the whole sky (background, ambient and reflections alike).
uniform float energy : hint_range(0.0, 8.0) = 1.0;
// Turns the sky around the vertical axis, degrees (positive = counter-clockwise from above).
uniform float rotation_degrees = 0.0;

void sky() {
	float r = radians(rotation_degrees);
	vec3 d = EYEDIR;
	d.xz = mat2(vec2(cos(r), -sin(r)), vec2(sin(r), cos(r))) * d.xz;
	vec2 uv = vec2((atan(d.x, -d.z) + PI) / TAU, acos(clamp(d.y, -1.0, 1.0)) / PI);
	// explicit LOD 0: the atan seam would otherwise pick the smallest mip along one line
	COLOR = textureLod(panorama, uv, 0.0).rgb * energy;
}
