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


## The shared impostor: a unit mesh (3 crossed vertical quads at azimuth 0 / 60 / 120 deg of the bake,
## and a top quad) with the atlas material; instances carry their variant in INSTANCE_CUSTOM.
var _imp_mesh: ArrayMesh


func impostor_mesh() -> ArrayMesh:
	if _imp_mesh:
		return _imp_mesh
	var v := PackedVector3Array()
	var n := PackedVector3Array()
	var uv := PackedVector2Array()
	var uv2 := PackedVector2Array()
	var idx := PackedInt32Array()
	for k in 4:
		var b := v.size()
		var corners := [[-1, 0, 0, 0], [1, 0, 1, 0], [1, 1, 1, 1], [-1, 1, 0, 1]]
		for c in corners:
			if k < 3:
				var a := deg_to_rad(60.0 * k)
				var right := Vector3(cos(a), 0.0, -sin(a))      # Blender (cos a, sin a, 0) in Godot space
				v.append(right * c[0] * 0.5 + Vector3.UP * c[1])
				n.append(Vector3(sin(a), 0.0, cos(a)))
			else:
				v.append(Vector3(c[0] * 0.5, 0.0, -(c[1] * 2.0 - 1.0) * 0.5))
				n.append(Vector3.UP)
			uv.append(Vector2(c[2], c[3]))
			uv2.append(Vector2(k, 2.0))
		idx.append_array([b, b + 2, b + 1, b, b + 3, b + 2])
	var arr := []
	arr.resize(Mesh.ARRAY_MAX)
	arr[Mesh.ARRAY_VERTEX] = v
	arr[Mesh.ARRAY_NORMAL] = n
	arr[Mesh.ARRAY_TEX_UV] = uv
	arr[Mesh.ARRAY_TEX_UV2] = uv2
	arr[Mesh.ARRAY_INDEX] = idx
	_imp_mesh = ArrayMesh.new()
	_imp_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
	var m := ShaderMaterial.new()
	m.shader = SH_IMP
	m.set_shader_parameter("albedo_tex", _t("impostors/atlas_albedo.png"))
	m.set_shader_parameter("normal_tex", _t("impostors/atlas_normal.png"))
	m.set_shader_parameter("lod_fade", FADE)
	_imp_mesh.surface_set_material(0, m)
	# instances are scaled in the shader: a generous AABB keeps culling correct
	_imp_mesh.custom_aabb = AABB(Vector3(-20, -2, -20), Vector3(40, 40, 40))
	return _imp_mesh


func has_impostor(key: String) -> bool:
	return index.variants[key].has("impostor")


## [instance transform (moved to the crown centre), INSTANCE_CUSTOM] for the shared impostor.
func impostor_instance(key: String, t: Transform3D) -> Array:
	var v: Dictionary = index.variants[key]
	var im: Dictionary = v.impostor
	var l: Dictionary = v.lod_m
	var c := Color(float(im.cell) * 1000.0 + float(l.lod2), float(im.size_v), float(im.size_t),
		floorf(float(l.far) / 10.0) * 1000.0 + float(im.height))
	var off := Vector3(float(im.center[0]), 0.0, -float(im.center[1]))
	return [Transform3D(t.basis, t * off), c]


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
