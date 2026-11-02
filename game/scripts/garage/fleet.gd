extends RefCounted
## The fleet as the garage sees it: every vehicle of res://assets/vehicles/index.json (the same index the
## traffic loads, copied in by tools/godot/sync_vehicles.py) with its liveries (KHR_materials_variants,
## see addons/fleet_variants) and its specs from the physics data (data/vehicles/ + classes.json via
## vehicle_params.gd).  Falls back to the hero car alone (assets/car) when the fleet is not synced.

const Params := preload("res://scripts/vehicle/vehicle_params.gd")
const INDEX := "res://assets/vehicles/index.json"
const DIR := "res://assets/vehicles/"

static var _catalogue: Array = []
static var _tables := {}          ## glb path -> {variant: {mesh name: [material per surface]}}
static var _gltf_mats := {}       ## glb path -> {material name: Material} (runtime parse fallback)


## [{id, name, class, glb, json, lod2, variants: [{name, label, kind}], default_variant, dimensions, mass_kg,
##   wheelbase}]
static func catalogue() -> Array:
	if not _catalogue.is_empty():
		return _catalogue
	if FileAccess.file_exists(INDEX):
		var d = JSON.parse_string(FileAccess.get_file_as_string(INDEX))
		if d is Dictionary:
			for v in d.get("vehicles", []):
				var files: Dictionary = v.get("files", {})
				var glb := DIR + String(files.get("lod0", "%s/%s.glb" % [v.id, v.id]))
				if not ResourceLoader.exists(glb):
					continue
				var vs: Array = []
				for vv in v.get("variants", []):
					vs.append({"name": String(vv.get("name", "")), "label": String(vv.get("label", vv.get("name", ""))),
						"kind": String(vv.get("kind", "civilian"))})
				_catalogue.append({"id": String(v.id), "name": String(v.get("name", v.id)), "class": String(v.get("class", "car")),
					"glb": glb, "json": DIR + String(files.get("json", "%s/%s.json" % [v.id, v.id])),
					"lod2": DIR + String(files.get("lod2", "")) if files.has("lod2") else "",
					"variants": vs, "default_variant": String(v.get("default_variant", vs[0].name if vs.size() else "")),
					"dimensions": v.get("dimensions", {}), "mass_kg": float(v.get("mass_kg", 1300.0)),
					"wheelbase": float(v.get("wheelbase", 2.6)), "player": bool(v.get("player", false))})
	if _catalogue.is_empty():
		_catalogue.append({"id": "tsubame", "name": "Kanzaki Tsubame-4", "class": "sedan", "glb": "res://assets/car/car.glb",
			"json": "res://assets/car/car.json", "lod2": "", "variants": [{"name": "default", "label": "stock", "kind": "civilian"}],
			"default_variant": "default", "dimensions": {}, "mass_kg": 1280.0, "wheelbase": 2.65, "player": true})
	return _catalogue


static func find(id: String) -> Dictionary:
	for v in catalogue():
		if v.id == id:
			return v
	return {}


static func index_of(id: String) -> int:
	var c := catalogue()
	for i in c.size():
		if c[i].id == id:
			return i
	return 0


static func variant_index(v: Dictionary, name: String) -> int:
	for i in v.variants.size():
		if v.variants[i].name == name:
			return i
	return 0


static func read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(path))
	return d if d is Dictionary else {}


# ------------------------------------------------------------------ liveries
## {variant: {mesh node name: [material per surface]}} of a glb: the import extension's meta
## ("gltf_variants", vehicle_variants.gd) or, without it, the "<id>_<variant>" materials of a runtime parse.
static func variant_table(glb: String, id: String, default_variant: String) -> Dictionary:
	if _tables.has(glb):
		return _tables[glb]
	var out := {}
	var scene: PackedScene = load(glb)
	if scene:
		var root := scene.instantiate()
		var stack: Array = [root]
		var defaults := {}          # mesh name -> [material per surface] (fallback mapping)
		while stack.size():
			var n: Node = stack.pop_back()
			stack.append_array(n.get_children())
			if not (n is MeshInstance3D):
				continue
			var mi := n as MeshInstance3D
			if mi.has_meta("gltf_variants"):
				var t: Dictionary = mi.get_meta("gltf_variants")
				for vn in t:
					if not out.has(vn):
						out[vn] = {}
					out[vn][String(mi.name)] = t[vn]
			else:
				var mats := []
				for s in mi.mesh.get_surface_count():
					mats.append(mi.get_active_material(s))
				defaults[String(mi.name)] = mats
		if out.is_empty():
			# runtime fallback: swap the "<id>_<default>" material for "<id>_<variant>"
			var fm := _file_materials(glb)
			var dname := "%s_%s" % [id, default_variant]
			for mname in fm:
				if not String(mname).begins_with(id + "_"):
					continue
				var vn := String(mname).substr(id.length() + 1)
				for mesh_name in defaults:
					var mats: Array = defaults[mesh_name]
					var row := []
					var any := false
					for m in mats:
						if m and String(m.resource_name) == dname:
							row.append(fm[mname])
							any = true
						else:
							row.append(null)
					if any:
						if not out.has(vn):
							out[vn] = {}
						out[vn][mesh_name] = row
		root.free()
	_tables[glb] = out
	return out


static func _file_materials(glb: String) -> Dictionary:
	if _gltf_mats.has(glb):
		return _gltf_mats[glb]
	var out := {}
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(ProjectSettings.globalize_path(glb), st) == OK:
		for m in st.get_materials():
			out[String(m.resource_name)] = m
	_gltf_mats[glb] = out
	return out


## Show `variant` on a car built from the vehicle's glb (car.gd copies the mesh nodes by name).
## Alpha-blended materials get the depth pre-pass the car uses.  Returns how many surfaces changed.
static func apply_variant(car: Node, v: Dictionary, variant: String) -> int:
	var table: Dictionary = variant_table(v.glb, v.id, v.default_variant)
	if not table.has(variant):
		return 0
	var per: Dictionary = table[variant]
	var n := 0
	for mi in car.find_children("*", "MeshInstance3D", true, false):
		if not per.has(String(mi.name)):
			continue
		var mats: Array = per[String(mi.name)]
		for s in mini(mats.size(), mi.mesh.get_surface_count()):
			var m: Material = mats[s]
			if m == null:
				continue
			if m is BaseMaterial3D and m.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
				m = m.duplicate()
				m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS
			mi.set_surface_override_material(s, m)
			mi.set_meta("livery_mat_%d" % s, mats[s])
			n += 1
	car.set_meta("livery", variant)
	return n


## The material a mesh shows for the livery (before paint), for tests.
static func livery_material(mi: MeshInstance3D, s: int) -> Material:
	return mi.get_meta("livery_mat_%d" % s) if mi.has_meta("livery_mat_%d" % s) else null


# ------------------------------------------------------------------ specs
## Real (not "easy") physics numbers for the spec panel; `tune` scales like tuning.gd does.
static func specs(v: Dictionary, perf := {}) -> Dictionary:
	var spec := read_json(v.json)
	var was: bool = Params.easy
	Params.easy = false
	var P: Dictionary = Params.build(spec, v.id)
	Params.easy = was
	var tf: float = TuningFactors.ENGINE[int(perf.get("engine", 0))]
	var best_p := 0.0
	var best_p_rpm := 0.0
	var best_t := 0.0
	var best_t_rpm := 0.0
	for pt in P.engine.torque_curve:
		var rpm := float(pt[0])
		var t := float(pt[1]) * tf
		if t > best_t:
			best_t = t
			best_t_rpm = rpm
		var p := t * rpm * TAU / 60.0
		if p > best_p and rpm <= float(P.engine.limiter_rpm):
			best_p = p
			best_p_rpm = rpm
	var r := float(P.wheel_radius)
	var ratios: Array = P.gearbox.ratios
	var gear_v := float(P.engine.redline_rpm) * TAU / 60.0 / (float(ratios[-1]) * float(P.gearbox.final_drive)) * r
	# drag-limited speed: power at the wheels = aero drag + rolling resistance
	var area := float(P.aero.area)
	var cd := float(P.aero.cd)
	var rho := float(P.aero.air_density)
	var crr := float(P.tyres.rolling_resistance)
	var pw := best_p * float(P.engine.get("efficiency", 0.9))
	var vd := 10.0
	for i in 60:
		var need := 0.5 * rho * cd * area * vd * vd * vd + crr * float(P.mass) * 9.81 * vd
		vd *= pow(pw / maxf(need, 1.0), 0.33)
	var top := minf(gear_v, vd)
	var lim := float(P.engine.get("speed_limiter_kmh", 0))
	if lim > 0.0:
		top = minf(top, lim / 3.6)
	var dims: Dictionary = v.get("dimensions", {})
	return {
		"mass": float(P.mass), "drive": String(P.get("drive", "RWD")), "gears": ratios.size(),
		"electric": bool(P.gearbox.get("electric", false)),
		"power_kw": best_p / 1000.0, "power_rpm": best_p_rpm, "torque": best_t, "torque_rpm": best_t_rpm,
		"top_kmh": top * 3.6, "limited": lim > 0.0 and lim / 3.6 <= minf(gear_v, vd) + 0.1,
		"length": float(dims.get("length", P.dimensions.length)), "width": float(dims.get("width_body", dims.get("width", P.dimensions.width))),
		"height": float(dims.get("height_roof", dims.get("height", P.dimensions.height))),
		"wheelbase": float(P.wheels.Wheel_FL[2]) - float(P.wheels.Wheel_RL[2]),
		"brake_g": float(P.brakes.max_decel_g) * TuningFactors.BRAKES[int(perf.get("brakes", 0))],
		"grip": float(P.tyres.front.mu) * TuningFactors.TYRES[int(perf.get("tyres", 0))],
		"wheel_radius": r, "wheel_width": float(P.wheel_width),
	}


class TuningFactors:
	const ENGINE := [1.0, 1.12, 1.25, 1.4]
	const BRAKES := [1.0, 1.12, 1.25, 1.4]
	const TYRES := [1.0, 1.05, 1.1, 1.16]
	const SUSPENSION := [1.0, 1.12, 1.25, 1.4]
	const NAMES := ["STOCK", "STREET", "SPORT", "RACE"]
