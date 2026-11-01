// Garage paint over a fleet body (or wheel) material: the Pigment textures stay (decals, wear, dirt,
// trim); only the texels that match the livery's paint colour are recoloured, keeping their shading.
// Parameters are copied from the StandardMaterial3D it replaces (scripts/garage/tuning.gd).
shader_type spatial;
render_mode blend_mix, depth_prepass_alpha, cull_back, diffuse_burley, specular_schlick_ggx;

uniform vec4 albedo : source_color = vec4(1.0);
uniform sampler2D texture_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float metallic = 0.0;
uniform sampler2D texture_metallic : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec4 metallic_channel = vec4(0.0, 0.0, 1.0, 0.0);
uniform float roughness : hint_range(0.0, 1.0) = 1.0;
uniform sampler2D texture_roughness : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec4 roughness_channel = vec4(0.0, 1.0, 0.0, 0.0);
uniform float specular = 0.5;
uniform bool use_normal = false;
uniform sampler2D texture_normal : hint_roughness_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float normal_scale = 1.0;
uniform bool use_emission = false;
uniform sampler2D texture_emission : source_color, hint_default_black, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec4 emission : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float emission_energy = 1.0;
uniform bool use_alpha = true;
uniform vec3 uv1_scale = vec3(1.0);
uniform vec3 uv1_offset = vec3(0.0);

// garage
uniform int mask_mode = 0;                    // 0 = texels near paint_ref (body), 1 = bright metal (rims)
uniform bool paint_on = false;
uniform vec3 paint_color : source_color = vec3(0.8, 0.1, 0.4);
uniform vec3 paint_ref : source_color = vec3(0.5);     // the livery's dominant paint colour
uniform float paint_tol = 0.22;
uniform int finish = 0;                       // 0 stock, 1 pearl, 2 chrome, 3 matte
uniform float window_tint : hint_range(0.0, 1.0) = 0.0;

float lum(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

void fragment() {
	vec2 uv = UV * uv1_scale.xy + uv1_offset.xy;
	vec4 a = albedo * texture(texture_albedo, uv);
	float met = metallic * dot(texture(texture_metallic, uv), metallic_channel);
	float rough = roughness * dot(texture(texture_roughness, uv), roughness_channel);
	vec3 em = vec3(0.0);
	if (use_emission) {
		em = (emission.rgb + texture(texture_emission, uv).rgb) * emission_energy;
	}
	float alpha = use_alpha ? a.a : 1.0;
	float mask = 0.0;
	if (paint_on || finish != 0) {
		float l = lum(a.rgb);
		if (mask_mode == 0) {
			float lr = max(lum(paint_ref), 0.004);
			vec3 cr = paint_ref / lr;
			vec3 cc = a.rgb / max(l, 0.004);
			float d = length(cc - cr) * 0.35 + abs(log((l + 0.004) / (lr + 0.004))) * 0.3;
			mask = 1.0 - smoothstep(paint_tol * 0.55, paint_tol, d);
			mask *= step(0.97, alpha) * (1.0 - clamp(lum(em) * 4.0, 0.0, 1.0));
		} else {
			mask = smoothstep(0.16, 0.32, l);
		}
		float shade = 1.0;
		if (mask_mode == 0) {
			shade = clamp(l / max(lum(paint_ref), 0.004), 0.25, 1.6);
		} else {
			shade = clamp(l * 1.6, 0.3, 1.4);
		}
		vec3 base = paint_on ? paint_color * shade : a.rgb;
		float r2 = rough;
		float m2 = met;
		if (finish == 1) {            // pearl: deep glossy coat with a cool sheen at grazing angles
			float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
			base = mix(base, base.gbr * 0.6 + vec3(0.35), fres * 0.55);
			r2 = min(rough, 0.1);
			m2 = 0.35;
		} else if (finish == 2) {     // chrome
			base = mix(base, vec3(1.0), 0.15);
			r2 = 0.04;
			m2 = 1.0;
		} else if (finish == 3) {     // matte
			r2 = 0.78;
			m2 = 0.0;
		}
		a.rgb = mix(a.rgb, base, mask);
		rough = mix(rough, r2, mask);
		met = mix(met, m2, mask);
		if (finish == 1 || finish == 2) {
			CLEARCOAT = mask;
			CLEARCOAT_ROUGHNESS = 0.04;
		}
	}
	if (window_tint > 0.0 && use_alpha) {
		// glass: the see-through part of the body atlas
		float glass = 1.0 - smoothstep(0.85, 0.97, alpha);
		a.rgb = mix(a.rgb, a.rgb * 0.08, glass * window_tint);
		alpha = mix(alpha, max(alpha, 0.55 + 0.43 * window_tint), glass * window_tint);
		rough = mix(rough, 0.04, glass * window_tint);
	}
	ALBEDO = a.rgb;
	METALLIC = met;
	ROUGHNESS = rough;
	SPECULAR = specular;
	if (use_normal) {
		NORMAL_MAP = texture(texture_normal, uv).rgb;
		NORMAL_MAP_DEPTH = normal_scale;
	}
	EMISSION = em;
	if (use_alpha) {
		ALPHA = alpha;
	}
}
