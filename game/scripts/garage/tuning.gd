extends RefCounted
## Garage customisation of the player car: a plain Dictionary ("cfg", saved to user://garage.json) and the
## code that puts it on a car built by car.gd -- without changing car.gd:
##   livery    fleet_variants material swap (fleet.gd)
##   paint     car_paint.gdshader replaces the body material: same Pigment textures, the texels matching the
##             livery's paint colour are recoloured (decals / wear / trim stay); finish stock|pearl|chrome|matte
##   tint      window tint (the see-through part of the body atlas)
##   underglow coloured lights + emissive strips under the sills
##   rims      wheel meshes from another fleet vehicle (scaled to this car's tyre size) + rim colour
##   stance    ride height (the hubs move up in the body: the car sits lower) and camber (visual, a touch of grip)
##   kit       front lip, rear wing, roof light bar (extra meshes sized from the body)
##   perf      engine / brakes / tyres / suspension tiers scale the physics params from data/vehicles
##   plate     plate text (Label3D on a plate at both ends)
## Physics changes are applied relative to the values the car was built with (meta "tune_base"), so
## applying again never compounds.

const Fleet := preload("res://scripts/garage/fleet.gd")
const PaintShader := preload("res://scripts/garage/car_paint.gdshader")
const F := Fleet.TuningFactors
const SAVE := "user://garage.json"

const PALETTE := [
	["NEON MAGENTA", Color(1.0, 0.1, 0.55)], ["CYBER CYAN", Color(0.05, 0.85, 1.0)], ["ACID LIME", Color(0.6, 1.0, 0.1)],
	["SUNSET ORANGE", Color(1.0, 0.42, 0.05)], ["BLOOD RED", Color(0.75, 0.02, 0.05)], ["ULTRAVIOLET", Color(0.42, 0.1, 1.0)],
	["MIDNIGHT BLUE", Color(0.03, 0.06, 0.25)], ["GOLD", Color(1.0, 0.72, 0.2)], ["PEARL WHITE", Color(0.92, 0.92, 0.9)],
	["GUNMETAL", Color(0.16, 0.17, 0.19)], ["JET BLACK", Color(0.012, 0.012, 0.014)], ["TOXIC YELLOW", Color(1.0, 0.92, 0.0)],
]
const FINISHES := ["stock", "pearl", "chrome", "matte"]
const TINTS := [0.0, 0.35, 0.6, 0.85]
const DROPS := [0.0, 0.02, 0.04, 0.06]
const CAMBERS := [0.0, 1.5, 3.0, 4.5]


static func default_cfg(vehicle_id := "") -> Dictionary:
	var c := Fleet.catalogue()
	var v: Dictionary = Fleet.find(vehicle_id) if vehicle_id != "" else {}
	if v.is_empty():
		v = c[0]
		for x in c:
			if x.get("player", false):
				v = x
				break
	return {
		"vehicle": v.id, "variant": "cab" if v.variants.any(func(x): return x.name == "cab") else v.default_variant,
		"paint": {"on": false, "color": _arr(PALETTE[0][1]), "finish": "stock"},
		"tint": 0.0,
		"underglow": {"on": false, "color": _arr(PALETTE[1][1])},
		"rims": {"style": "stock", "color": null},
		"stance": {"drop": 0.0, "camber": 0.0},
		"kit": {"lip": false, "wing": false, "lightbar": false},
		"perf": {"engine": 0, "brakes": 0, "tyres": 0, "suspension": 0},
		"plate": "4C-1187",
	}


static func _arr(c: Color) -> Array:
	return [snappedf(c.r, 0.001), snappedf(c.g, 0.001), snappedf(c.b, 0.001)]


static func col(a) -> Color:
	return Color(float(a[0]), float(a[1]), float(a[2])) if a is Array and a.size() >= 3 else Color.WHITE


## cfg with every key present (old / partial saves), values clamped to what exists.
static func normalized(cfg: Dictionary) -> Dictionary:
	var d := default_cfg(String(cfg.get("vehicle", "")))
	var out: Dictionary = preload("res://scripts/vehicle/vehicle_params.gd").merge(d, cfg)
	var v := Fleet.find(String(out.vehicle))
	if v.is_empty():
		out = d
		v = Fleet.find(String(out.vehicle))
	if v.variants.filter(func(x): return x.name == String(out.variant)).is_empty():
		out.variant = v.default_variant
	for k in ["engine", "brakes", "tyres", "suspension"]:
		out.perf[k] = clampi(int(out.perf.get(k, 0)), 0, 3)
	out.plate = String(out.plate).substr(0, 10).to_upper()
	return out


static func save(cfg: Dictionary, path := SAVE) -> bool:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return false
	f.store_string(JSON.stringify(cfg, " "))
	f.close()
	return true


static func load_cfg(path := SAVE) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(path))
	return normalized(d) if d is Dictionary else {}


# ------------------------------------------------------------------ apply
## Everything except the vehicle itself (that is a rebuild: garage.gd).
static func apply(car: Node, cfg: Dictionary) -> void:
	var v := Fleet.find(String(cfg.vehicle))
	Fleet.apply_variant(car, v, String(cfg.variant))
	apply_paint(car, v, cfg)
	apply_rims(car, cfg)
	apply_underglow(car, cfg)
	apply_kit(car, cfg)
	apply_plate(car, cfg)
	apply_physics(car, cfg)
	car.set_meta("garage_cfg", cfg.duplicate(true))


static func _body_meshes(car: Node) -> Array:
	var out := []
	var vis := car.get_node_or_null("Visual")
	if vis == null:
		return out
	for mi in vis.find_children("*", "MeshInstance3D", true, false):
		out.append(mi)
	return out


## The car_paint material for a base StandardMaterial3D (cached per base material and mode).
static func paint_material(base: BaseMaterial3D, mask_mode: int) -> ShaderMaterial:
	var sm := ShaderMaterial.new()
	sm.shader = PaintShader if mask_mode == 0 else _opaque_shader()
	sm.resource_name = String(base.resource_name) + "_paint"
	sm.set_shader_parameter("albedo", base.albedo_color)
	sm.set_shader_parameter("texture_albedo", base.albedo_texture)
	sm.set_shader_parameter("metallic", base.metallic)
	sm.set_shader_parameter("texture_metallic", base.metallic_texture)
	sm.set_shader_parameter("metallic_channel", _channel(base.metallic_texture_channel))
	sm.set_shader_parameter("roughness", base.roughness)
	sm.set_shader_parameter("texture_roughness", base.roughness_texture)
	sm.set_shader_parameter("roughness_channel", _channel(base.roughness_texture_channel))
	sm.set_shader_parameter("specular", base.metallic_specular)
	sm.set_shader_parameter("use_normal", base.normal_enabled and base.normal_texture != null)
	sm.set_shader_parameter("texture_normal", base.normal_texture)
	sm.set_shader_parameter("normal_scale", base.normal_scale)
	sm.set_shader_parameter("use_emission", base.emission_enabled)
	sm.set_shader_parameter("texture_emission", base.emission_texture)
	sm.set_shader_parameter("emission", base.emission)
	sm.set_shader_parameter("emission_energy", base.emission_energy_multiplier)
	sm.set_shader_parameter("emission_multiply", base.emission_operator == BaseMaterial3D.EMISSION_OP_MULTIPLY)
	sm.set_shader_parameter("use_alpha", base.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED)
	sm.set_shader_parameter("uv1_scale", base.uv1_scale)
	sm.set_shader_parameter("uv1_offset", base.uv1_offset)
	sm.set_shader_parameter("mask_mode", mask_mode)
	sm.set_meta("base", base)
	return sm


static var _opaque: Shader


## The same shader without alpha (wheels: stay in the opaque pass).
static func _opaque_shader() -> Shader:
	if _opaque == null:
		_opaque = Shader.new()
		_opaque.code = PaintShader.code.replace("depth_prepass_alpha, ", "").replace("ALPHA = alpha;", "")
	return _opaque


static func _channel(c: int) -> Vector4:
	match c:
		0: return Vector4(1, 0, 0, 0)
		1: return Vector4(0, 1, 0, 0)
		2: return Vector4(0, 0, 1, 0)
		3: return Vector4(0, 0, 0, 1)
	return Vector4(0.333, 0.333, 0.333, 0)


## Body paint, finish and window tint.  Untouched (stock everything) = the livery material itself.
static func apply_paint(car: Node, v: Dictionary, cfg: Dictionary) -> void:
	var p: Dictionary = cfg.paint
	var fin := FINISHES.find(String(p.get("finish", "stock")))
	var stock := not bool(p.get("on", false)) and fin <= 0 and float(cfg.tint) <= 0.0
	var ref := Color(0.5, 0.5, 0.5)
	if not stock:
		ref = _paint_ref(car, v, String(cfg.variant))
	for mi: MeshInstance3D in _body_meshes(car):
		for s in mi.mesh.get_surface_count():
			var lm: Material = Fleet.livery_material(mi, s)
			if lm == null:
				lm = mi.get_active_material(s)
				if lm is ShaderMaterial and lm.has_meta("base"):
					lm = lm.get_meta("base")
			if not (lm is BaseMaterial3D):
				continue
			var low := String(lm.resource_name).to_lower()
			if not (low.contains("body") or low.contains("paint") or low.begins_with(String(v.id) + "_")):
				continue
			if stock:
				var m: Material = lm
				if lm.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
					m = lm.duplicate()
					m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS
				mi.set_surface_override_material(s, m)
				continue
			var sm := paint_material(lm, 0)
			sm.set_shader_parameter("paint_on", bool(p.get("on", false)))
			sm.set_shader_parameter("paint_color", col(p.color))
			sm.set_shader_parameter("paint_ref", ref)
			sm.set_shader_parameter("finish", maxi(fin, 0))
			sm.set_shader_parameter("window_tint", float(cfg.tint))
			mi.set_surface_override_material(s, sm)


static var _refs := {}


## The livery's paint colour: the albedo under the outer panels of the body (roof, bonnet, boot lid and
## the door skins, picked from the mesh by position and normal), most common colour wins -- so stripes,
## decals, glass, trim and the interior parts of the atlas don't count.  Grey when the texture can't be
## read (headless).
static func _paint_ref(car: Node, v: Dictionary, variant: String) -> Color:
	var key := "%s/%s" % [v.id, variant]
	if _refs.has(key):
		return _refs[key]
	var out := Color(0.5, 0.5, 0.5)
	var t: Dictionary = Fleet.variant_table(v.glb, v.id, v.default_variant)
	var mat: BaseMaterial3D = null
	if t.has(variant) and t[variant].has("Body"):
		mat = t[variant]["Body"][0] as BaseMaterial3D
	var img: Image = mat.albedo_texture.get_image() if mat and mat.albedo_texture else null
	var body: MeshInstance3D = null
	for mi in _body_meshes(car):
		if String(mi.name) == "Body":
			body = mi
	if img and not img.is_empty() and body:
		img = img.duplicate()
		if img.is_compressed():
			img.decompress()
		img.convert(Image.FORMAT_RGBA8)
		img.resize(512, 512, Image.INTERPOLATE_BILINEAR)
		var box := _body_box(car)
		var hw := box.size.x * 0.5
		var hist := {}
		var sums := {}
		var shell_top := {}
		var shell_side := {}
		var mesh := body.mesh
		for si in mesh.get_surface_count():
			var arr := mesh.surface_get_arrays(si)
			if arr.is_empty() or arr[Mesh.ARRAY_TEX_UV] == null or arr[Mesh.ARRAY_NORMAL] == null:
				continue
			var vs: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			var uvs: PackedVector2Array = arr[Mesh.ARRAY_TEX_UV]
			var ns: PackedVector3Array = arr[Mesh.ARRAY_NORMAL]
			var idx: PackedInt32Array = arr[Mesh.ARRAY_INDEX] if arr[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
			var ntri := idx.size() / 3 if idx.size() else vs.size() / 3
			for ti in ntri:
				var i0 := idx[ti * 3] if idx.size() else ti * 3
				var i1 := idx[ti * 3 + 1] if idx.size() else ti * 3 + 1
				var i2 := idx[ti * 3 + 2] if idx.size() else ti * 3 + 2
				var a: Vector3 = body.transform * vs[i0]
				var b: Vector3 = body.transform * vs[i1]
				var c: Vector3 = body.transform * vs[i2]
				var cr := (b - a).cross(c - a)
				var area := cr.length() * 0.5
				if area < 1e-5:
					continue
				var n: Vector3 = (body.transform.basis * (ns[i0] + ns[i1] + ns[i2])).normalized()
				var p := (a + b + c) / 3.0
				# the outer shell only: per 8 cm cell the highest up-facing / outermost side-facing triangle
				if n.y > 0.7:
					var key2 := Vector2i(int(floorf(p.x / 0.08)), int(floorf(p.z / 0.08)))
					if not shell_top.has(key2) or shell_top[key2][0] < p.y:
						shell_top[key2] = [p.y, (uvs[i0] + uvs[i1] + uvs[i2]) / 3.0, area]
				elif absf(n.x) > 0.8 and signf(n.x) == signf(p.x) and p.y > box.position.y + box.size.y * 0.2:
					var key3 := Vector3i(int(signf(p.x)), int(floorf(p.y / 0.08)), int(floorf(p.z / 0.08)))
					if not shell_side.has(key3) or absf(shell_side[key3][0]) < absf(p.x):
						shell_side[key3] = [p.x, (uvs[i0] + uvs[i1] + uvs[i2]) / 3.0, area]
		for pair in [["t", shell_top], ["s", shell_side]]:
			for key4 in pair[1]:
				var e: Array = pair[1][key4]
				var uv: Vector2 = e[1]
				var px := img.get_pixel(clampi(int(fposmod(uv.x, 1.0) * 512.0), 0, 511), clampi(int(fposmod(uv.y, 1.0) * 512.0), 0, 511))
				if px.a < 0.97:
					continue
				var k := Vector3i(int(px.r * 7.99), int(px.g * 7.99), int(px.b * 7.99))
				if not hist.has(k):
					hist[k] = {"t": 0.0, "s": 0.0}
				hist[k][pair[0]] += 1.0
				sums[k] = sums.get(k, Vector3.ZERO) + Vector3(px.r, px.g, px.b)
		# a colour on both the roof / bonnet and the doors is the paint (a black roof or bonnet is not)
		var tt := 0.0
		var ts := 0.0
		for k in hist:
			tt += hist[k].t
			ts += hist[k].s
		var best := -1.0
		for k in hist:
			var ft: float = hist[k].t / maxf(tt, 1e-6)
			var fs: float = hist[k].s / maxf(ts, 1e-6)
			var score := minf(ft, fs) * 2.0 + maxf(ft, fs)
			if score > best:
				best = score
				var c: Vector3 = sums[k] / float(hist[k].t + hist[k].s)
				out = Color(c.x, c.y, c.z)
	_refs[key] = out
	return out


# ------------------------------------------------------------------ wheels
## Rim style (another fleet vehicle's wheel meshes, scaled to this tyre) and rim colour.
static func apply_rims(car: Node, cfg: Dictionary) -> void:
	if not ("wheels" in car) or car.wheels.is_empty():
		return
	var style := String(cfg.rims.get("style", "stock"))
	var own := String(cfg.vehicle)
	var donor_id := own if style == "stock" or Fleet.find(style).is_empty() else style
	var cur := String(car.get_meta("rim_style", own))
	if cur != donor_id:
		_swap_wheels(car, Fleet.find(own), Fleet.find(donor_id))
		car.set_meta("rim_style", donor_id)
	var rc = cfg.rims.get("color", null)
	for w in car.wheels:
		for mi in w.spin.find_children("*", "MeshInstance3D", true, false):
			for s in mi.mesh.get_surface_count():
				var base: Material = mi.get_meta("rim_base_%d" % s) if mi.has_meta("rim_base_%d" % s) else null
				if base == null:
					base = mi.get_active_material(s)
					mi.set_meta("rim_base_%d" % s, base)
				if rc == null or not (base is BaseMaterial3D):
					mi.set_surface_override_material(s, null if base == mi.mesh.surface_get_material(s) else base)
				else:
					var sm := paint_material(base, 1)
					sm.set_shader_parameter("paint_on", true)
					sm.set_shader_parameter("paint_color", col(rc))
					sm.set_shader_parameter("finish", 2 if col(rc).get_luminance() > 0.6 else 0)
					mi.set_surface_override_material(s, sm)
	_apply_camber(car, float(cfg.stance.get("camber", 0.0)))


static func _swap_wheels(car: Node, own: Dictionary, donor: Dictionary) -> void:
	var dspec := Fleet.read_json(donor.json)
	var dr := float(dspec.get("wheel_radius", 0.33))
	var dw := float(dspec.get("wheel_width", 0.2))
	var r := float(car.P.wheel_radius)
	var ww := float(car.P.wheel_width)
	var model: Node3D = load(donor.glb).instantiate()
	for w in car.wheels:
		var src := model.find_child(w.name, true, false) as Node3D
		if src == null:
			continue
		for c in w.spin.get_children():
			w.spin.remove_child(c)
			c.queue_free()
		var hub_xf := _model_xf(src, model)
		var inv := hub_xf.affine_inverse()
		var sc := Basis.from_scale(Vector3(ww / maxf(dw, 0.05), r / maxf(dr, 0.05), r / maxf(dr, 0.05)))
		for n in [src] + src.find_children("*", "MeshInstance3D", true, false):
			if not (n is MeshInstance3D):
				continue
			var mi := MeshInstance3D.new()
			mi.name = n.name
			mi.mesh = n.mesh
			for s in n.mesh.get_surface_count():
				var m: Material = n.get_active_material(s)
				if m != n.mesh.surface_get_material(s):
					mi.set_surface_override_material(s, m)
			mi.transform = Transform3D(sc, Vector3.ZERO) * Transform3D(hub_xf.basis, Vector3.ZERO) * (inv * _model_xf(n, model))
			w.spin.add_child(mi)
	model.free()


static func _model_xf(n: Node3D, model: Node3D) -> Transform3D:
	var t := Transform3D()
	var cur: Node = n
	while cur and cur != model:
		t = (cur as Node3D).transform * t
		cur = cur.get_parent()
	return t


## Camber: a node between each wheel's steering pivot and its spinning meshes (car.gd drives both).
static func _apply_camber(car: Node, deg: float) -> void:
	for w in car.wheels:
		var cam := w.pivot.get_node_or_null("Camber") as Node3D
		if cam == null:
			cam = Node3D.new()
			cam.name = "Camber"
			w.pivot.add_child(cam)
			w.spin.reparent(cam, false)
		cam.rotation = Vector3(0, 0, deg_to_rad(deg) * (1.0 if w.left else -1.0))


# ------------------------------------------------------------------ underglow, kit, plate
static func _body_box(car: Node) -> AABB:
	if car.has_meta("body_box"):
		return car.get_meta("body_box")
	var box := AABB()
	var first := true
	for mi: MeshInstance3D in _body_meshes(car):
		var b: AABB = mi.transform * mi.get_aabb()
		box = b if first else box.merge(b)
		first = false
	if first:
		var d: Dictionary = car.spec.get("dimensions", {}) if "spec" in car else {}
		var l := float(d.get("length", 4.4))
		box = AABB(Vector3(-0.9, 0.15, -l * 0.5), Vector3(1.8, float(d.get("height_roof", 1.4)) - 0.15, l))
	car.set_meta("body_box", box)
	return box


## Heights of the body surface (car space) sampled from its vertices: roof / rear deck / front bumper.
static func _profile(car: Node) -> Dictionary:
	if car.has_meta("body_profile"):
		return car.get_meta("body_profile")
	var box := _body_box(car)
	var deck := box.position.y + box.size.y * 0.62
	var nose_low := box.position.y + 0.12
	var roof := box.end.y
	var hw := box.size.x * 0.5
	var verts := 0
	var deck_y := -INF
	var nose_y := INF
	var roof_y := -INF
	for mi: MeshInstance3D in _body_meshes(car):
		var mesh := mi.mesh
		if mesh == null:
			continue
		for s in mesh.get_surface_count():
			var arr := mesh.surface_get_arrays(s)
			if arr.is_empty() or arr[Mesh.ARRAY_VERTEX] == null:
				continue
			var vs: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			for i in range(0, vs.size(), 3):
				var p: Vector3 = mi.transform * vs[i]
				verts += 1
				if absf(p.x) < hw * 0.45:
					if p.z < box.position.z + 0.45:
						deck_y = maxf(deck_y, p.y)
					if p.z > box.end.z - 0.35:
						nose_y = minf(nose_y, p.y)
					if absf(p.z - box.get_center().z) < 0.5:
						roof_y = maxf(roof_y, p.y)
	var out := {"deck": deck_y if deck_y > -INF else deck, "nose": nose_y if nose_y < INF else nose_low,
		"roof": roof_y if roof_y > -INF else roof, "box": box, "verts": verts}
	car.set_meta("body_profile", out)
	return out


static func _neon_mat(c: Color, energy := 4.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = c
	m.emission_enabled = true
	m.emission = c
	m.emission_energy_multiplier = energy
	return m


static func _carbon_mat() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0.02, 0.02, 0.025)
	m.metallic = 0.3
	m.roughness = 0.22
	m.clearcoat_enabled = true
	m.clearcoat = 1.0
	m.clearcoat_roughness = 0.05
	return m


static func _box(parent: Node, nm: String, size: Vector3, xf: Transform3D, mat: Material) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.name = nm
	var bm := BoxMesh.new()
	bm.size = size
	mi.mesh = bm
	mi.transform = xf
	mi.material_override = mat
	parent.add_child(mi)
	return mi


static func _group(car: Node, nm: String) -> Node3D:
	var g := car.get_node_or_null(nm) as Node3D
	if g:
		for c in g.get_children():
			g.remove_child(c)
			c.queue_free()
	else:
		g = Node3D.new()
		g.name = nm
		car.add_child(g)
	return g


static func apply_underglow(car: Node, cfg: Dictionary) -> void:
	var g := _group(car, "Underglow")
	var u: Dictionary = cfg.underglow
	g.visible = bool(u.get("on", false))
	if not g.visible:
		return
	var c := col(u.color)
	var box := _body_box(car)
	var hw := box.size.x * 0.5 - 0.12
	var y := box.position.y + 0.04
	var len := box.size.z * 0.62
	var m := _neon_mat(c, 6.0)
	for sx in [-1.0, 1.0]:
		_box(g, "Strip", Vector3(0.025, 0.02, len), Transform3D(Basis(), Vector3(sx * hw, y, box.get_center().z)), m)
	for sz in [-1.0, 1.0]:
		_box(g, "StripX", Vector3(hw * 1.5, 0.02, 0.025), Transform3D(Basis(), Vector3(0, y, box.get_center().z + sz * len * 0.5)), m)
	for i in 3:
		var l := OmniLight3D.new()
		l.name = "Glow%d" % i
		l.light_color = c
		l.light_energy = 1.1
		l.omni_range = 2.8
		l.omni_attenuation = 1.4
		l.light_volumetric_fog_energy = 0.0
		l.position = Vector3(0, maxf(y - 0.02, 0.08), box.get_center().z + (float(i) - 1.0) * len * 0.42)
		g.add_child(l)


class KitBar extends Node3D:
	var car: Node
	var lens: Array = []

	func _process(_d: float) -> void:
		if car == null or not ("bar_lights" in car) or car.bar_lights.size() < 2:
			return
		for i in mini(2, lens.size()):
			var e: float = car.bar_lights[i].light_energy
			lens[i].material_override.emission_energy_multiplier = 0.4 + e * 2.0


static func apply_kit(car: Node, cfg: Dictionary) -> void:
	var g := _group(car, "Kit")
	var k: Dictionary = cfg.kit
	var pr := _profile(car)
	var box: AABB = pr.box
	var w := box.size.x
	var carbon := _carbon_mat()
	if bool(k.get("lip", false)):
		var lip := Node3D.new()
		lip.name = "Lip"
		g.add_child(lip)
		var y: float = maxf(float(pr.nose) - 0.01, box.position.y + 0.02)
		_box(lip, "Blade", Vector3(w * 0.86, 0.025, 0.2), Transform3D(Basis(), Vector3(0, y, box.end.z - 0.12)), carbon)
		for sx in [-1.0, 1.0]:
			_box(lip, "Canard", Vector3(0.02, 0.07, 0.16), Transform3D(Basis(), Vector3(sx * w * 0.43, y + 0.03, box.end.z - 0.1)), carbon)
	if bool(k.get("wing", false)):
		var wing := Node3D.new()
		wing.name = "Wing"
		g.add_child(wing)
		var deck: float = float(pr.deck)
		var z := box.position.z + 0.2
		var top := deck + 0.28
		for sx in [-1.0, 1.0]:
			_box(wing, "Strut", Vector3(0.03, 0.3, 0.1), Transform3D(Basis(Vector3.RIGHT, -0.15), Vector3(sx * w * 0.3, deck + 0.13, z + 0.02)), carbon)
			_box(wing, "Endplate", Vector3(0.012, 0.16, 0.34), Transform3D(Basis(), Vector3(sx * w * 0.46, top + 0.02, z - 0.02)), carbon)
		_box(wing, "Blade", Vector3(w * 0.92, 0.03, 0.3), Transform3D(Basis(Vector3.RIGHT, 0.12), Vector3(0, top, z - 0.02)), carbon)
		_box(wing, "Edge", Vector3(w * 0.9, 0.008, 0.012), Transform3D(Basis(), Vector3(0, top + 0.02, z - 0.17)),
			_neon_mat(col(cfg.underglow.color) if bool(cfg.underglow.get("on", false)) else Color(1.0, 0.15, 0.5), 5.0))
	if bool(k.get("lightbar", false)):
		var bar := KitBar.new()
		bar.name = "LightBar"
		bar.car = car
		g.add_child(bar)
		var y: float = float(pr.roof) + 0.02
		var z := box.get_center().z - 0.05
		_box(bar, "Base", Vector3(1.05, 0.06, 0.26), Transform3D(Basis(), Vector3(0, y + 0.03, z)), carbon)
		var red := _neon_mat(Color(1.0, 0.05, 0.08), 0.6)
		var blue := _neon_mat(Color(0.1, 0.3, 1.0), 0.6)
		bar.lens.append(_box(bar, "LensR", Vector3(0.45, 0.07, 0.2), Transform3D(Basis(), Vector3(0.25, y + 0.09, z)), red))
		bar.lens.append(_box(bar, "LensB", Vector3(0.45, 0.07, 0.2), Transform3D(Basis(), Vector3(-0.25, y + 0.09, z)), blue))


static func apply_plate(car: Node, cfg: Dictionary) -> void:
	var g := _group(car, "Plates")
	var box := _body_box(car)
	var txt := String(cfg.get("plate", "")).to_upper()
	if txt == "":
		return
	var plate_mat := StandardMaterial3D.new()
	plate_mat.albedo_color = Color(0.92, 0.9, 0.72)
	plate_mat.roughness = 0.4
	plate_mat.emission_enabled = true
	plate_mat.emission = Color(0.92, 0.9, 0.72)
	plate_mat.emission_energy_multiplier = 0.15
	for front in [true, false]:
		var z := box.end.z + 0.004 if front else box.position.z - 0.004
		var y := box.position.y + (0.3 if front else 0.42)
		var holder := Node3D.new()
		holder.name = "Front" if front else "Rear"
		holder.transform = Transform3D(Basis() if front else Basis(Vector3.UP, PI), Vector3(0, y, z))
		g.add_child(holder)
		_box(holder, "Plate", Vector3(0.44, 0.115, 0.008), Transform3D(), plate_mat)
		var l := Label3D.new()
		l.name = "Text"
		l.text = txt
		l.font_size = 56
		l.pixel_size = 0.0016
		l.outline_size = 0
		l.modulate = Color(0.05, 0.08, 0.1)
		l.position = Vector3(0, -0.004, 0.006)
		l.double_sided = false
		holder.add_child(l)


# ------------------------------------------------------------------ physics
static func _base(car: Node) -> Dictionary:
	if car.has_meta("tune_base"):
		return car.get_meta("tune_base")
	var P: Dictionary = car.P
	var ws := []
	for w in car.wheels:
		ws.append({"mu": w.mu, "k": w.k, "cb": w.c_bump, "cr": w.c_reb, "rest": w.rest})
	var b := {"curve": (P.engine.torque_curve as Array).duplicate(true), "peak": float(P.engine.peak_torque),
		"brake": float(P.brakes.max_torque), "arb_f": float(P.suspension.arb_front), "arb_r": float(P.suspension.arb_rear),
		"wheels": ws}
	car.set_meta("tune_base", b)
	return b


static func apply_physics(car: Node, cfg: Dictionary) -> void:
	if not ("P" in car) or car.P.is_empty():
		return
	var b := _base(car)
	var pf: Dictionary = cfg.perf
	var fe: float = F.ENGINE[int(pf.engine)]
	var fb: float = F.BRAKES[int(pf.brakes)]
	var ft: float = F.TYRES[int(pf.tyres)]
	var fs: float = F.SUSPENSION[int(pf.suspension)]
	var camber := float(cfg.stance.get("camber", 0.0))
	var drop := float(cfg.stance.get("drop", 0.0))
	var P: Dictionary = car.P
	P.engine["torque_curve"] = (b.curve as Array).map(func(pt): return [pt[0], float(pt[1]) * fe])
	P.engine["peak_torque"] = float(b.peak) * fe
	if "_curve_lut" in car:
		car._curve_lut = PackedFloat32Array()      # car.gd rebuilds its torque table lazily
	P.brakes["max_torque"] = float(b.brake) * fb
	P.suspension["arb_front"] = float(b.arb_f) * fs
	P.suspension["arb_rear"] = float(b.arb_r) * fs
	# negative camber: a little more cornering grip (and it looks the part)
	var fc := 1.0 + clampf(camber, 0.0, 5.0) * 0.008
	for i in car.wheels.size():
		var w = car.wheels[i]
		var wb: Dictionary = b.wheels[i]
		w.mu = float(wb.mu) * ft * fc
		w.k = float(wb.k) * fs
		w.c_bump = float(wb.cb) * sqrt(fs)
		w.c_reb = float(wb.cr) * sqrt(fs)
		w.rest = (wb.rest as Vector3) + Vector3.UP * drop     # hubs higher in the body: the car sits lower
		w.pivot.position = w.rest
	if "calipers" in car:
		for c in car.calipers:
			c[0].position = c[1].rest
	car.set_meta("tune_factors", {"engine": fe, "brakes": fb, "tyres": ft * fc, "suspension": fs, "drop": drop})
