extends RefCounted
## The citizen catalogue (res://assets/npc/index.json, written by tools/npc/sync_godot.py) and the
## spawner other systems use:
##
##   const CitizenLib := preload("res://scripts/npc/character/citizen_library.gd")
##   CitizenLib.available() -> bool                 citizens built + imported?
##   CitizenLib.ids(include_players := false) -> PackedStringArray
##   CitizenLib.info(id) -> Dictionary              manifest entry (sex, height, archetype, umbrella, ...)
##   CitizenLib.spawn(id_or_seed, opts := {}) -> Citizen (scripts/npc/character/citizen.gd), not yet in the tree
##        id_or_seed: "citizen_07" / "waker_f", or an int seed (picks a non-player citizen)
##        opts: {"lite": bool (no finger tracks), "umbrella": "clear"/"black"/"neon"/"" (override),
##               "ragdoll": true (default), "shadows": true}
##   CitizenLib.crowd_mesh(id) -> Mesh              the LOD2 mesh (static, ~360 tris, sway colours)
##   CitizenLib.materials(id) -> [opaque, cutout]   shared ShaderMaterials (atlas)
##   CitizenLib.set_wet(w)                          rain response of every citizen material

const INDEX := "res://assets/npc/index.json"
const Citizen := preload("res://scripts/npc/character/citizen.gd")
const SHADER := preload("res://scripts/npc/character/citizen.gdshader")
const SHADER_CUT := preload("res://scripts/npc/character/citizen_cutout.gdshader")

static var _index := {}
static var _list: Array = []
static var _scenes := {}
static var _mats := {}
static var _crowd := {}
static var _wet := 1.0


static func available() -> bool:
	_load()
	return not _list.is_empty()


static func _load() -> void:
	if not _index.is_empty() or not FileAccess.file_exists(INDEX):
		return
	var d = JSON.parse_string(FileAccess.get_file_as_string(INDEX))
	if not d is Dictionary:
		return
	for c in d.get("citizens", []):
		if ResourceLoader.exists(c.glb):
			_index[c.id] = c
			_list.append(c)


static func ids(include_players := false) -> PackedStringArray:
	_load()
	var out := PackedStringArray()
	for c in _list:
		if include_players or not c.get("player", false):
			out.append(c.id)
	return out


static func info(id: String) -> Dictionary:
	_load()
	return _index.get(id, {})


static func pick(seed_value: int) -> String:
	var l := ids(false)
	if l.is_empty():
		return ""
	return l[posmod(seed_value * 2654435761, l.size())]


static func scene(id: String) -> PackedScene:
	if not _scenes.has(id):
		_scenes[id] = load(info(id).glb)
	return _scenes[id]


static func materials(id: String) -> Array:
	if _mats.has(id):
		return _mats[id]
	var c := info(id)
	var out := []
	for sh in [SHADER, SHADER_CUT]:
		var m := ShaderMaterial.new()
		m.shader = sh
		m.set_shader_parameter("albedo_tex", load(c.albedo))
		m.set_shader_parameter("normal_tex", load(c.normal))
		m.set_shader_parameter("mask_tex", load(c.mask))
		m.set_shader_parameter("wet", _wet)
		out.append(m)
	_mats[id] = out
	return out


static func set_wet(w: float) -> void:
	_wet = w
	for k in _mats:
		for m in _mats[k]:
			m.set_shader_parameter("wet", w)
	for k in _crowd:
		_crowd[k][1].set_shader_parameter("wet", w)


## LOD2 mesh + its crowd material ([mesh, material]): far citizens drawn with MultiMeshes.
static func crowd(id: String) -> Array:
	if _crowd.has(id):
		return _crowd[id]
	var root: Node = scene(id).instantiate()
	var mi: MeshInstance3D = root.find_child("LOD2", true, false)
	var mesh: Mesh = mi.mesh if mi else null
	root.free()
	var c := info(id)
	var m := ShaderMaterial.new()
	m.shader = preload("res://scripts/npc/crowd.gdshader")
	m.set_shader_parameter("albedo_tex", load(c.albedo))
	m.set_shader_parameter("mask_tex", load(c.mask))
	m.set_shader_parameter("hip_y", float(c.get("hips", 0.9)))
	m.set_shader_parameter("shoulder_y", float(c.get("shoulder", 1.4)))
	m.set_shader_parameter("wet", _wet)
	_crowd[id] = [mesh, m]
	return _crowd[id]


static func crowd_mesh(id: String) -> Mesh:
	return crowd(id)[0]


static func spawn(id_or_seed, opts := {}) -> Node3D:
	_load()
	var id := String(id_or_seed) if id_or_seed is String else pick(int(id_or_seed))
	if not _index.has(id):
		push_warning("npc: no citizen %s" % id)
		return null
	var c = Citizen.new()
	c.setup(id, info(id), opts)
	return c
