extends RefCounted
## Traffic vehicle models from a fleet index (vehicle-index/1, see docs/agents/traffic/NOTES.md).
##
## Looks for, in order:
##   res://assets/vehicles/index.json          the fleet workstream (copied in by tools/godot/sync_vehicles.py)
##   res://assets/traffic/standin/index.json   stand-in fleet made from the hero car (make_traffic_standins.py)
## Each model becomes a template: per LOD the body meshes (+ wheel pivots when the LOD has Wheel_* nodes),
## the convex collider, lamp positions and size.  Variants are material swaps (an albedo tint or a
## material/texture override per variant); materials are shared between all cars of a variant.

const INDEX_PATHS := ["res://assets/vehicles/index.json", "res://assets/traffic/standin/index.json"]

var models: Array = []           ## [Model]
var source := ""
var head_mat: StandardMaterial3D
var tail_mat: StandardMaterial3D
var brake_mat: StandardMaterial3D
var bar_mats := {}               ## "red_on", "red_off", "blue_on", "blue_off"


class Model:
	var name := ""
	var klass := "car"
	var weight := 1.0
	var patrol := false
	var lightbar := false
	var lods: Array = []         ## [{max: float, parts: [[mesh, xf, materials: Array]], wheels: [{hub: Transform3D, parts: [[mesh, xf, mats]]}]}]
	var variants: Array = []     ## [{name, weight, mats: {lod index: {surface key: Material}}}]
	var shape: Shape3D
	var shape_xf := Transform3D()
	var length := 4.4
	var width := 1.85
	var height := 1.4
	var wheel_radius := 0.33
	var head_pos: Array = []     ## Vector3 (model space)
	var tail_pos: Array = []
	var bar_y := 1.5
	var head_mesh: Mesh
	var tail_mesh: Mesh
	var mass := 1250.0


func load_index() -> bool:
	_make_light_mats()
	for p in INDEX_PATHS:
		if FileAccess.file_exists(p):
			var d = JSON.parse_string(FileAccess.get_file_as_string(p))
			if d is Dictionary and _load(d, p.get_base_dir()):
				source = p
				return true
	# last resort: the hero car itself
	var d := {"vehicles": [{"name": "hero", "class": "sedan", "spawn_weight": 1.0, "spec": "res://assets/car/car.json",
		"lods": [{"file": "res://assets/car/car.glb", "max_distance": 600.0}], "variants": [{"name": "default"}]}]}
	source = "hero car"
	return _load(d, "res://assets/car")


func _load(d: Dictionary, base: String) -> bool:
	for vd in d.get("vehicles", d.get("models", [])):
		var m := _load_model(vd, base)
		if m:
			models.append(m)
	return not models.is_empty()


func _res(path: String, base: String) -> String:
	if path.begins_with("res://") or path.begins_with("user://"):
		return path
	return base.path_join(path)


func _load_model(vd: Dictionary, base: String) -> Model:
	var m := Model.new()
	m.name = String(vd.get("name", "vehicle"))
	var dir := base
	if vd.has("dir"):
		dir = _res(String(vd.dir), base)
	m.klass = String(vd.get("class", "car"))
	m.weight = float(vd.get("spawn_weight", vd.get("weight", 1.0)))
	m.patrol = bool(vd.get("patrol", m.klass in ["security", "police"]))
	m.lightbar = bool(vd.get("lightbar", m.patrol))
	var spec := {}
	var sp := String(vd.get("spec", vd.get("json", "")))
	if sp != "" and FileAccess.file_exists(_res(sp, dir)):
		spec = JSON.parse_string(FileAccess.get_file_as_string(_res(sp, dir)))
	m.mass = float(spec.get("mass_kg", vd.get("mass_kg", 1250.0)))
	m.wheel_radius = float(spec.get("wheel_radius", 0.33))
	var dims: Dictionary = spec.get("dimensions", vd.get("dimensions", {}))
	# LOD list: [{file, max_distance}] or {"lod0": file, "lod1": file, "lod2": file}
	var lod_list := []
	var ld = vd.get("lods", vd.get("files", vd.get("lod", [])))
	if ld is Dictionary:
		var keys: Array = ld.keys()
		keys.sort()
		var dmax := [16.0, 45.0, 140.0, 600.0]
		for i in keys.size():
			lod_list.append({"file": ld[keys[i]], "max_distance": dmax[mini(i, 3)] if i < keys.size() - 1 else 600.0})
	elif ld is Array:
		lod_list = ld
	elif vd.has("file"):
		lod_list = [{"file": vd.file, "max_distance": 600.0}]
	var ok := false
	for e in lod_list:
		var f := _res(String(e.get("file", "")), dir)
		if not ResourceLoader.exists(f):
			push_warning("traffic: missing LOD %s" % f)
			continue
		var scene: PackedScene = load(f)
		if scene == null:
			continue
		var root: Node3D = scene.instantiate()
		_take_lod(m, root, float(e.get("max_distance", 600.0)))
		root.free()
		ok = true
	if not ok:
		return null
	m.lods.sort_custom(func(a, b): return a.max < b.max)
	m.length = float(dims.get("length", m.length))
	m.width = float(dims.get("width_overfenders", dims.get("width", m.width)))
	m.height = float(dims.get("height_roof", dims.get("height", m.height)))
	m.bar_y = float(dims.get("height_lightbar", m.height + 0.1)) + 0.06
	if m.head_pos.is_empty():
		m.head_pos = [Vector3(0.6, 0.6, m.length * 0.49), Vector3(-0.6, 0.6, m.length * 0.49)]
	if m.tail_pos.is_empty():
		m.tail_pos = [Vector3(0.7, 0.75, -m.length * 0.49), Vector3(-0.7, 0.75, -m.length * 0.49)]
	m.head_mesh = _lamp_mesh(m.head_pos, 1.0, Vector2(0.26, 0.11))
	m.tail_mesh = _lamp_mesh(m.tail_pos, -1.0, Vector2(0.3, 0.09))
	if m.shape == null:
		var b := BoxShape3D.new()
		b.size = Vector3(m.width, m.height * 0.8, m.length)
		m.shape = b
		m.shape_xf = Transform3D(Basis(), Vector3(0, m.height * 0.45, 0))
	# variants
	var vs: Array = vd.get("variants", [])
	if vs.is_empty():
		vs = [{"name": "default"}]
	for v in vs:
		m.variants.append(_variant(m, v, dir))
	return m


func _take_lod(m: Model, root: Node3D, max_d: float) -> void:
	var lod := {"max": max_d, "parts": [], "wheels": []}
	var all := _all(root)
	for n in all:
		var nm := String(n.name)
		if n is MeshInstance3D and nm.begins_with("Collider"):
			if m.shape == null:
				m.shape = (n as MeshInstance3D).mesh.create_convex_shape(true, true)
				m.shape_xf = _xf(n, root)
			continue
		if nm.begins_with("Headlight") and m.head_pos.size() < 2 and n is Node3D:
			m.head_pos.append(_xf(n, root).origin + Vector3(0, 0, 0.03))
		elif (nm.begins_with("Taillight") or nm.begins_with("Brakelight")) and m.tail_pos.size() < 2 and n is Node3D:
			m.tail_pos.append(_xf(n, root).origin - Vector3(0, 0, 0.03))
	for n in all:
		if not (n is Node3D):
			continue
		var nm := String(n.name)
		if nm.begins_with("Wheel_") and not _under(n.get_parent(), root, "Wheel_"):
			var hub := _xf(n, root)
			var inv := hub.affine_inverse()
			var parts := []
			for c in _all(n):
				if c is MeshInstance3D:
					parts.append([c.mesh, inv * _xf(c, root), _mats(c)])
			lod.wheels.append({"hub": hub, "parts": parts})
	for n in all:
		if n is MeshInstance3D and not _under(n, root, "Wheel_") and not _under(n, root, "Collider") and not _under(n, root, "Caliper_"):
			lod.parts.append([n.mesh, _xf(n, root), _mats(n)])
	if not lod.parts.is_empty():
		m.lods.append(lod)


func _mats(mi: MeshInstance3D) -> Array:
	var out := []
	for s in mi.mesh.get_surface_count():
		out.append(mi.get_active_material(s))
	return out


## Per variant and LOD: a material for every surface (shared by all cars of the variant).
## Body materials (name contains "body" / "paint", or the first surface) get the tint; alpha-blended
## glass gets a depth pre-pass up close and turns opaque on the last LOD.
func _variant(m: Model, v: Dictionary, dir: String) -> Dictionary:
	var out := {"name": String(v.get("name", "default")), "weight": float(v.get("weight", 1.0)), "mats": []}
	var tint = v.get("tint", v.get("paint", null))
	var override_mat: Material = null
	if v.has("material") and ResourceLoader.exists(_res(String(v.material), dir)):
		override_mat = load(_res(String(v.material), dir))
	var albedo_tex: Texture2D = null
	if v.has("albedo") and ResourceLoader.exists(_res(String(v.albedo), dir)):
		albedo_tex = load(_res(String(v.albedo), dir))
	var cache := {}
	for li in m.lods.size():
		# glass stays see-through (depth pre-pass) only on a close-up LOD; further LODs are opaque
		# (dark glossy panes, like the town's windows): one draw per surface instead of two
		var last: bool = (li == m.lods.size() - 1 and m.lods.size() > 1) or m.lods[li].max > 20.0
		var lod: Dictionary = m.lods[li]
		var per := {}
		for group in [lod.parts] + lod.wheels.map(func(w): return w.parts):
			for p in group:
				for si in p[2].size():
					var src: Material = p[2][si]
					if src == null or per.has(src):
						continue
					var key := [src, last]
					if cache.has(key):
						per[src] = cache[key]
						continue
					var mat: Material = src
					var is_body := src is BaseMaterial3D and (String(src.resource_name).to_lower().contains("body") or String(src.resource_name).to_lower().contains("paint"))
					if src is BaseMaterial3D:
						var bm: BaseMaterial3D = src.duplicate()
						if is_body and override_mat:
							mat = override_mat
						else:
							if is_body and tint is Array:
								bm.albedo_color = Color(tint[0], tint[1], tint[2])
							if is_body and albedo_tex:
								bm.albedo_texture = albedo_tex
							if bm.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
								bm.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED if last else BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS
							if last:
								bm.clearcoat_enabled = false
							mat = bm
					cache[key] = mat
					per[src] = mat
		out.mats.append(per)
	return out


func pick(rng: RandomNumberGenerator, patrol := false) -> Model:
	var pool := models.filter(func(x): return x.patrol == patrol and (patrol or x.weight > 0.0))
	if pool.is_empty():
		pool = models
	var tot := 0.0
	for x in pool:
		tot += maxf(x.weight, 0.01)
	var r := rng.randf() * tot
	for x in pool:
		r -= maxf(x.weight, 0.01)
		if r <= 0.0:
			return x
	return pool[0]


static func pick_variant(m: Model, rng: RandomNumberGenerator) -> int:
	var tot := 0.0
	for v in m.variants:
		tot += v.weight
	var r := rng.randf() * tot
	for i in m.variants.size():
		r -= m.variants[i].weight
		if r <= 0.0:
			return i
	return 0


# ------------------------------------------------------------------ lamps
func _make_light_mats() -> void:
	head_mat = _emissive(Color(1.0, 0.94, 0.82), 9.0)
	tail_mat = _emissive(Color(1.0, 0.05, 0.03), 2.2)
	brake_mat = _emissive(Color(1.0, 0.04, 0.02), 9.0)
	bar_mats = {"red_on": _emissive(Color(1, 0.05, 0.08), 14.0), "red_off": _emissive(Color(0.3, 0.02, 0.03), 0.4),
		"blue_on": _emissive(Color(0.1, 0.3, 1.0), 14.0), "blue_off": _emissive(Color(0.03, 0.06, 0.3), 0.4)}


static func _emissive(c: Color, e: float) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0, 0, 0)
	m.emission_enabled = true
	m.emission = c
	m.emission_energy_multiplier = e
	m.roughness = 0.4
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.disable_receive_shadows = true
	return m


## Small rounded quads at the lamp positions facing +Z (front) or -Z (rear).
static func _lamp_mesh(pos: Array, facing: float, size: Vector2) -> Mesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for p in pos:
		var c: Vector3 = p
		var hx := size.x * 0.5
		var hy := size.y * 0.5
		var q := [Vector3(-hx, -hy, 0), Vector3(hx, -hy, 0), Vector3(hx, hy, 0), Vector3(-hx, hy, 0)]
		for i in [0, 1, 2, 0, 2, 3]:
			st.set_normal(Vector3(0, 0, facing))
			st.add_vertex(c + q[i])
	return st.commit()


static func bar_mesh(m: Model, side: float) -> Mesh:
	var bm := BoxMesh.new()
	bm.size = Vector3(0.42, 0.09, 0.22)
	return bm


# ------------------------------------------------------------------ helpers
static func _all(n: Node) -> Array:
	var out := [n]
	for c in n.get_children():
		out.append_array(_all(c))
	return out


static func _under(n: Node, root: Node, prefix: String) -> bool:
	var cur := n
	while cur and cur != root:
		if String(cur.name).begins_with(prefix):
			return true
		cur = cur.get_parent()
	return false


static func _xf(n: Node3D, root: Node3D) -> Transform3D:
	var t := Transform3D()
	var cur: Node = n
	while cur and cur != root:
		t = (cur as Node3D).transform * t
		cur = cur.get_parent()
	return t
