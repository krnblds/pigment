extends RefCounted
## The tree kit (tools/trees -> assets/trees, copied to res://assets/trees by tools/trees/sync_godot.py).
##
## town_loader.gd hands every layout mesh whose key is a kit variant (tree_<species>_<shape>[_<look>])
## to this class instead of drawing the exported glb: each variant gets three LOD meshes (LOD0 cards,
## LOD1 fewer / bigger cards, LOD2 crossed-quad impostor) with the tree shaders. The loader instances
## them as MultiMeshes (LOD0 / LOD1 in streamed 64 m cells, impostors per 256 m region) and the
## shaders pick each instance's LOD from its own distance to the camera (tree_common.gdshaderinc),
## with a dithered cross-fade. Colliders are trunk capsules.

const DIR := "res://assets/trees/"
const SH_LEAF := preload("res://scripts/tree_leaves.gdshader")
const SH_BARK := preload("res://scripts/tree_bark.gdshader")
const SH_IMP := preload("res://scripts/tree_impostor.gdshader")
const FADE := 6.0

var index := {}
var ok := false
var wind := Vector4(0.8, 0.6, 0.5, 1.0)     ## dir x, dir z, strength, wetness
var _mats := {}
var _tex := {}
var _meshes := {}


func _init() -> void:
	var p := DIR + "index.json"
	if not FileAccess.file_exists(p):
		return
	var d = JSON.parse_string(FileAccess.get_file_as_string(p))
	if d is Dictionary and d.has("variants"):
		index = d
		ok = true
	var w := Vector2(wind.x, wind.y).normalized()
	wind.x = w.x
	wind.y = w.y
	RenderingServer.global_shader_parameter_set("tree_wind", wind)


func has(key: String) -> bool:
	return ok and index.variants.has(key)


## LOD bands [[begin, end] x 3] in metres for a variant.
func bands(key: String) -> Array:
	var l: Dictionary = index.variants[key].lod_m
	return [[0.0, float(l.lod1)], [float(l.lod1), float(l.lod2)], [float(l.lod2), float(l.far)]]


func lod_count(key: String) -> int:
	return int(index.variants[key].get("lods", 3))


## Called every frame by the loader: the LOD camera (also for shadow passes) and the wind.
func update(cam: Vector3) -> void:
	RenderingServer.global_shader_parameter_set("tree_cam", cam)


func set_wet(v: float) -> void:
	wind.w = v
	RenderingServer.global_shader_parameter_set("tree_wind", wind)


func set_wind(strength: float) -> void:
	wind.z = strength
	RenderingServer.global_shader_parameter_set("tree_wind", wind)


func _t(path: String) -> Texture2D:
	if not _tex.has(path):
		_tex[path] = load(DIR + path) if ResourceLoader.exists(DIR + path) else null
	return _tex[path]


func _material(kind: String, arg: String, band: Array) -> ShaderMaterial:
	var mk := "%s|%s|%d|%d" % [kind, arg, int(band[0]), int(band[1])]
	if _mats.has(mk):
		return _mats[mk]
	var m := ShaderMaterial.new()
	match kind:
		"leaf":
			m.shader = SH_LEAF
			m.set_shader_parameter("albedo_tex", _t("textures/leaves_albedo.png"))
			m.set_shader_parameter("normal_tex", _t("textures/leaves_normal.jpg"))
			m.set_shader_parameter("mask_tex", _t("textures/leaves_mask.jpg"))
		"bark":
			m.shader = SH_BARK
			m.set_shader_parameter("albedo_tex", _t("textures/bark_%s_albedo.jpg" % arg))
			m.set_shader_parameter("normal_tex", _t("textures/bark_%s_normal.jpg" % arg))
			m.set_shader_parameter("rough_tex", _t("textures/bark_%s_rough.jpg" % arg))
		"imp":
			m.shader = SH_IMP
			m.set_shader_parameter("albedo_tex", _t("impostors/%s_albedo.png" % arg))
			m.set_shader_parameter("normal_tex", _t("impostors/%s_normal.png" % arg))
	m.set_shader_parameter("lod_range", Vector2(band[0], band[1]))
	m.set_shader_parameter("lod_fade", FADE)
	m.resource_name = "Tree_" + mk
	_mats[mk] = m
	return m


## The LOD mesh of a variant with the tree materials (null if its glb is missing).
func mesh(key: String, lod: int) -> Mesh:
	var mk := "%s|%d" % [key, lod]
	if _meshes.has(mk):
		return _meshes[mk]
	var v: Dictionary = index.variants[key]
	var f: String = DIR + String(v.files["lod%d" % lod])
	var m: Mesh = null
	if ResourceLoader.exists(f):
		var ps = load(f)
		if ps is PackedScene:
			var inst: Node = ps.instantiate()
			var mi := _first_mesh(inst)
			if mi:
				m = mi.mesh
			inst.free()
	if m:
		var band: Array = bands(key)[lod]
		for i in m.get_surface_count():
			var sm := m.surface_get_material(i)
			var nm := sm.resource_name if sm else ""
			if nm.begins_with("TreeGrate"):
				var g := StandardMaterial3D.new()
				g.albedo_color = Color(0.06, 0.05, 0.045)
				g.metallic = 0.8
				g.roughness = 0.5
				g.resource_name = "TreeGrate"
				m.surface_set_material(i, g)
			elif nm.begins_with("TreeLeaves"):
				m.surface_set_material(i, _material("leaf", "", band))
			elif nm.begins_with("TreeImpostor") or lod == 2:
				m.surface_set_material(i, _material("imp", key, band))
			else:
				m.surface_set_material(i, _material("bark", String(v.bark), band))
	_meshes[mk] = m
	return m


func _first_mesh(n: Node) -> MeshInstance3D:
	if n is MeshInstance3D:
		return n
	for c in n.get_children():
		var r := _first_mesh(c)
		if r:
			return r
	return null


## Trunk capsule of an instance: [height, Transform3D (orthonormal, centred), radius], or [] (shrubs).
func collider(key: String, t: Transform3D) -> Array:
	var c: Dictionary = index.variants[key].get("collider", {})
	if c.get("type", "") != "capsule":
		return []
	var sc := t.basis.get_scale()
	var h: float = float(c.height) * sc.y
	var r: float = float(c.radius) * maxf(sc.x, sc.z)
	return [maxf(h, r * 2.0 + 0.1), Transform3D(Basis(), t.origin + Vector3.UP * h * 0.5), r]
