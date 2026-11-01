class_name CitySky
extends RefCounted
## The baked night-city skies (tools/sky/make_sky.py) for an existing Environment.
##
##   CitySky.apply(env)                     # night_rain: sky, ambient, horizon-matched fog
##   CitySky.apply(env, "dusk")             # or night_moon / predawn
##   CitySky.setup_key(moon_light, "dusk")  # the preset's key light (moon / low sun)
##
## Or instance res://sky/sky_night.tscn (WorldEnvironment + Moon) as a ready-made scene.
## The panoramas share the Blender / Pigment orientation (see city_sky.gdshader).
## If a larger bake (assets/sky --res 4k / 8k, copied here) has been imported, it is used.

const PRESETS_JSON := "res://sky/sky_presets.json"
const DEFAULT := "night_rain"

static var _meta: Dictionary = {}


static func presets() -> Dictionary:
	if _meta.is_empty():
		var f := FileAccess.open(PRESETS_JSON, FileAccess.READ)
		if f:
			_meta = JSON.parse_string(f.get_as_text())
	return _meta


static func names() -> PackedStringArray:
	return PackedStringArray(presets().keys())


## The Sky resource for `preset`, with the largest imported panorama.
static func sky(preset: String = DEFAULT) -> Sky:
	var m: Dictionary = presets().get(preset, {})
	if m.is_empty():
		push_warning("CitySky: unknown preset %s (%s)" % [preset, ", ".join(names())])
		return null
	var s: Sky = load(m["sky"])
	for res in ["8k", "4k"]:
		var p := "res://sky/%s_%s.hdr" % [preset, res]
		if ResourceLoader.exists(p):
			s = s.duplicate(true)
			(s.sky_material as ShaderMaterial).set_shader_parameter("panorama", load(p))
			break
	return s


static func _col(a: Array, k: float = 1.0) -> Color:
	return Color(a[0] * k, a[1] * k, a[2] * k)


## Put the sky on `env`: background, ambient and reflections from it, and fog that
## fades into its horizon. Leaves tonemap, glow, SSR, GI etc. alone.
static func apply(env: Environment, preset: String = DEFAULT, fog: bool = true) -> void:
	var s := sky(preset)
	if s == null:
		return
	var m: Dictionary = presets()[preset]
	env.background_mode = Environment.BG_SKY
	env.sky = s
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = m["ambient_light_energy"]
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	if fog:
		env.fog_light_color = _col(m["fog_light_color"])
		env.fog_light_energy = m["fog_light_energy"]
		env.fog_sky_affect = 0.0          # the panorama has its own horizon haze
		env.volumetric_fog_albedo = _col(m["volumetric_fog_albedo"])
		env.volumetric_fog_emission = _col(m["volumetric_fog_emission"])
		env.volumetric_fog_emission_energy = 1.0


## Point a DirectionalLight3D along the preset's key (moon, or the low sun at dusk).
static func setup_key(light: DirectionalLight3D, preset: String = DEFAULT) -> void:
	var m: Dictionary = presets().get(preset, {})
	if m.is_empty():
		return
	var k: Dictionary = m["key"]
	var r: Array = k["rotation_degrees"]
	light.rotation_degrees = Vector3(r[0], r[1], r[2])
	light.light_color = _col(k["color"])
	light.light_energy = k["energy"]
