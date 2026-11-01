extends RefCounted
## Traffic vehicle models from a fleet index (see docs/agents/traffic/NOTES.md, "Vehicle index").
##
## Looks for, in order:
##   res://assets/vehicles/index.json          the fleet workstream's index ("vehicle-index" v1), copied in
##                                              with its vehicles by tools/godot/sync_vehicles.py
##   res://assets/traffic/standin/index.json   stand-in fleet made from the hero car (make_traffic_standins.py)
## Each vehicle becomes a template: per LOD the body meshes (+ spinning wheel pivots when the LOD has
## Wheel_* nodes), the convex collider, lamp positions and size.
##
## Variants:
##   * fleet: KHR_materials_variants on Body.  Godot ignores the extension, so the variant materials come
##     from the fleet's import extension (meta "gltf_variants" on the meshes, vehicle_variants.gd) when it
##     is registered, otherwise from a one-time runtime glTF parse of each LOD file (materials are named
##     "<id>_<variant>" there).  Variant "kind" police -> used by the security patrols only.
##   * stand-in: an albedo "tint", an "albedo" texture or a "material" override per variant.
## Materials are shared by all cars of a variant; glass is see-through only on a close-up LOD.

const INDEX_PATHS := ["res://assets/vehicles/index.json", "res://assets/traffic/standin/index.json"]
const POLICE_KINDS := ["police", "security"]

var models: Array = []           ## [Model]
var source := ""
var head_mat: StandardMaterial3D
var tail_mat: StandardMaterial3D
var brake_mat: StandardMaterial3D
var bar_mats := {}               ## "red_on", "red_off", "blue_on", "blue_off"
var load_ms := 0
var variant_paths := {"import_extension": 0, "runtime_gltf": 0, "tint_or_default": 0}


class Model:
	var name := ""
	var klass := "car"
	var weight := 1.0
	var lightbar := false
	var lods: Array = []         ## [{max, file, parts: [[mesh, xf, mats, variant table]], wheels: [{hub, parts}]}]
	var variants: Array = []     ## [{name, kind, weight, police, mats: [per LOD {source material: material}]}]
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
	var default_variant := ""

	func has_police() -> bool:
		return variants.any(func(v): return v.police)

	func has_civil() -> bool:
		return variants.any(func(v): return not v.police)


func load_index() -> bool:
	var t0 := Time.get_ticks_msec()
	_make_light_mats()
	for p in INDEX_PATHS:
		if FileAccess.file_exists(p):
			var d = JSON.parse_string(FileAccess.get_file_as_string(p))
			if d is Dictionary and _load(d, p.get_base_dir()):
				source = p
				load_ms = Time.get_ticks_msec() - t0
				return true
	# last resort: the hero car itself
	var d := {"vehicles": [{"name": "hero", "class": "sedan", "spawn_weight": 1.0, "spec": "res://assets/car/car.json",
		"lods": [{"file": "res://assets/car/car.glb", "max_distance": 600.0}], "variants": [{"name": "default"}, {"name": "security", "kind": "police"}]}]}
	source = "hero car"
	return _load(d, "res://assets/car")


func _load(d: Dictionary, base: String) -> bool:
	for vd in d.get("vehicles", d.get("models", [])):
		var m := _load_model(vd, base)
		if m:
			models.append(m)
	return not models.is_empty()


func _res(path: String, base: String) -> String:
	if path.begins_with("res://") or path.begins_with("user://") or path.is_absolute_path():
		return path
	return base.path_join(path).simplify_path()


func _load_model(vd: Dictionary, base: String) -> Model:
	var m := Model.new()
	m.name = String(vd.get("id", vd.get("name", "vehicle")))
	var dir := base
	if vd.has("dir"):
		dir = _res(String(vd.dir), base)
	m.klass = String(vd.get("class", "car"))
	m.weight = float(vd.get("spawn_weight", vd.get("weight", 1.0)))
	var files = vd.get("lods", vd.get("files", vd.get("lod", [])))
	var spec := {}
	var sp := String(vd.get("spec", vd.get("json", "")))
	if sp == "" and files is Dictionary and files.has("json"):
		sp = String(files.json)
	if sp != "" and FileAccess.file_exists(_res(sp, dir)):
		spec = JSON.parse_string(FileAccess.get_file_as_string(_res(sp, dir)))
	m.mass = float(spec.get("mass_kg", vd.get("mass_kg", 1250.0)))
	m.wheel_radius = float(spec.get("wheel_radius", 0.33))
	var dims: Dictionary = spec.get("dimensions", vd.get("dimensions", {}))
	# LOD list: [{file, max_distance}] (stand-in) or {"lod0": f, "lod1": f, "lod2": f, "json": f} with
	# "lod_distances_m": {"lod0": 0, "lod1": 25, "lod2": 70} = where each LOD starts (fleet)
	var lod_list := []
	if files is Dictionary:
		var keys: Array = files.keys().filter(func(k): return String(k).begins_with("lod"))
		keys.sort()
		var starts: Dictionary = vd.get("lod_distances_m", {})
		var dflt := [0.0, 22.0, 60.0, 160.0]
		for i in keys.size():
			var end := 600.0
			if i < keys.size() - 1:
				end = float(starts.get(keys[i + 1], dflt[mini(i + 1, 3)]))
			lod_list.append({"file": files[keys[i]], "max_distance": end})
	elif files is Array:
		lod_list = files
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
		_take_lod(m, root, float(e.get("max_distance", 600.0)), f)
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
	var vs: Array = vd.get("variants", spec.get("variants", []))
	if vs.is_empty():
		vs = [{"name": "default"}]
	var patrol_model := bool(vd.get("patrol", m.klass in POLICE_KINDS))
	m.default_variant = String(vd.get("default_variant", spec.get("default_variant", String(vs[0].get("name", "")))))
	for v in vs:
		var vv: Dictionary = v.duplicate()
		vv["police"] = patrol_model or String(v.get("kind", "civilian")) in POLICE_KINDS
		m.variants.append(_variant(m, vv, dir))
	m.lightbar = bool(vd.get("lightbar", m.has_police()))
	return m


func _take_lod(m: Model, root: Node3D, max_d: float, file: String) -> void:
	var lod := {"max": max_d, "file": file, "parts": [], "wheels": []}
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
					parts.append([c.mesh, inv * _xf(c, root), _mats(c), c.get_meta("gltf_variants", {})])
			lod.wheels.append({"hub": hub, "parts": parts})
	for n in all:
		if n is MeshInstance3D and not _under(n, root, "Wheel_") and not _under(n, root, "Collider") and not _under(n, root, "Caliper_"):
			lod.parts.append([n.mesh, _xf(n, root), _mats(n), n.get_meta("gltf_variants", {})])
	if not lod.parts.is_empty():
		m.lods.append(lod)


func _mats(mi: MeshInstance3D) -> Array:
	var out := []
	for s in mi.mesh.get_surface_count():
		out.append(mi.get_active_material(s))
	return out


var _gltf_mats := {}            ## file -> {material name: Material} (runtime parse, fleet variants)


## Variant materials of a glb by name, parsed at runtime (when the import extension was not registered).
func _file_materials(file: String) -> Dictionary:
	if _gltf_mats.has(file):
		return _gltf_mats[file]
	var out := {}
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	var src := ProjectSettings.globalize_path(file)
	if doc.append_from_file(src, st) == OK:
		var done := {}
		for mat in st.get_materials():
			out[String(mat.resource_name)] = mat
			if mat is BaseMaterial3D:
				_compress_textures(mat, done)
	_gltf_mats[file] = out
	return out


## Runtime-parsed glTF textures are uncompressed RGBA: compress them (S3TC + mipmaps) to keep VRAM sane.
static func _compress_textures(mat: BaseMaterial3D, done: Dictionary) -> void:
	for prop in ["albedo_texture", "normal_texture", "roughness_texture", "metallic_texture", "emission_texture", "ao_texture",
			"clearcoat_texture"]:
		var tex = mat.get(prop)
		if not (tex is Texture2D):
			continue
		var key: int = tex.get_instance_id()
		if done.has(key):
			mat.set(prop, done[key])
			continue
		var img: Image = tex.get_image()
		if img == null or img.is_compressed():
			done[key] = tex
			continue
		img.generate_mipmaps()
		img.compress(Image.COMPRESS_S3TC, Image.COMPRESS_SOURCE_NORMAL if prop == "normal_texture" else Image.COMPRESS_SOURCE_GENERIC)
		var it := ImageTexture.create_from_image(img)
		done[key] = it
		mat.set(prop, it)


## Per variant and LOD: a material for every surface (shared by all cars of the variant).
func _variant(m: Model, v: Dictionary, dir: String) -> Dictionary:
	var out := {"name": String(v.get("name", "default")), "kind": String(v.get("kind", "civilian")), "police": v.police,
		"weight": float(v.get("weight", 1.0)), "mats": []}
	var tint = v.get("tint", null)
	var override_mat: Material = null
	if v.has("material") and String(v.material).begins_with("res://") and ResourceLoader.exists(String(v.material)):
		override_mat = load(String(v.material))
	var mat_name := String(v.get("material", "%s_%s" % [m.name, out.name]))
	var default_name := "%s_%s" % [m.name, m.default_variant]     # the body material each LOD file carries
	var albedo_tex: Texture2D = null
	if v.has("albedo") and ResourceLoader.exists(_res(String(v.albedo), dir)):
		albedo_tex = load(_res(String(v.albedo), dir))
	var cache := {}
	for li in m.lods.size():
		# glass stays see-through (depth pre-pass) only on a close-up LOD; further LODs are opaque
		# (dark glossy panes, like the town's windows): one draw per surface instead of two
		var far: bool = (li == m.lods.size() - 1 and m.lods.size() > 1) or m.lods[li].max > 30.0
		var lod: Dictionary = m.lods[li]
		var per := {}
		for group in [lod.parts] + lod.wheels.map(func(w): return w.parts):
			for p in group:
				var table: Dictionary = p[3]
				for si in p[2].size():
					var src: Material = p[2][si]
					if src == null or per.has(src):
						continue
					var base_mat: Material = src
					var sname := String(src.resource_name)
					# fleet variant: the extension's table, or the "<id>_<variant>" material of this file
					if table.has(out.name) and si < table[out.name].size() and table[out.name][si] != null:
						base_mat = table[out.name][si]
						variant_paths.import_extension += 1
					elif table.is_empty() and sname == default_name and sname != mat_name and v.has("index"):
						var fm := _file_materials(lod.file)
						if fm.has(mat_name):
							base_mat = fm[mat_name]
							variant_paths.runtime_gltf += 1
					else:
						variant_paths.tint_or_default += 1
					var key := [base_mat, far, out.name]
					if cache.has(key):
						per[src] = cache[key]
						continue
					var mat: Material = base_mat
					var low := sname.to_lower()
					var is_body := low.contains("body") or low.contains("paint") or sname == default_name
					if base_mat is BaseMaterial3D:
						var bm: BaseMaterial3D = base_mat.duplicate()
						if is_body and override_mat:
							mat = override_mat
						else:
							if is_body and tint is Array:
								bm.albedo_color = Color(tint[0], tint[1], tint[2])
							if is_body and albedo_tex:
								bm.albedo_texture = albedo_tex
							if bm.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
								bm.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED if far else BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS
							if far:
								bm.clearcoat_enabled = false
							mat = bm
					cache[key] = mat
					per[src] = mat
		out.mats.append(per)
	return out


func pick(rng: RandomNumberGenerator, patrol := false) -> Model:
	var pool := models.filter(func(x): return x.has_police() if patrol else (x.has_civil() and x.weight > 0.0))
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


static func pick_variant(m: Model, rng: RandomNumberGenerator, patrol := false) -> int:
	var idx := []
	for i in m.variants.size():
		if m.variants[i].police == patrol:
			idx.append(i)
	if idx.is_empty():
		idx = range(m.variants.size())
	var tot := 0.0
	for i in idx:
		tot += m.variants[i].weight
	var r := rng.randf() * tot
	for i in idx:
		r -= m.variants[i].weight
		if r <= 0.0:
			return i
	return idx[0]


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


## Small quads at the lamp positions facing +Z (front) or -Z (rear).
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


static func bar_mesh(_m: Model, _side: float) -> Mesh:
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
