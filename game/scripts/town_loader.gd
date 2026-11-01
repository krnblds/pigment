extends Node3D
## Builds the town from res://assets/town/town_layout.json (written by tools/godot/export_town.py).
##
## Every (mesh, material set) pair becomes MultiMeshInstance3D chunks (CHUNK m cells, so they
## frustum-cull and take visibility ranges) or a single MeshInstance3D when it is used once.
## Materials are built from the packed Pigment textures; collision is simplified per category.

const DIR := "res://assets/town/"
const CHUNK := 64.0

## visibility range end (m) per category, 0 = always
const VIS_END := {"sign": 170.0, "decal": 150.0, "lamp": 240.0, "pole": 240.0, "rail": 170.0,
		"wire": 200.0, "footing": 260.0}
const CAST_SHADOWS := {"building": true, "footing": true, "wall": true, "stairs": true, "lamp": true,
		"pole": true, "sign": true, "terrain": true, "road": false, "decal": false, "wire": false, "rail": true}

var layout: Dictionary = {}
var road_points := PackedVector3Array()   ## road centre samples
var road_dirs := PackedVector3Array()     ## unit tangents at the samples
var lamp_lights: Array[OmniLight3D] = []
var stats := {"multimesh": 0, "mesh_instances": 0, "shapes": 0, "lights": 0}

var _mesh_cache := {}
var _mat_cache := {}
var _tex_cache := {}
var _body: StaticBody3D
var _col_root: Node3D
var _wet := 1.0


func load_town(wet := 1.0) -> bool:
	_wet = wet
	var path := DIR + "town_layout.json"
	if not FileAccess.file_exists(path):
		push_warning("town layout missing: %s (run tools/godot/export_town.py)" % path)
		return false
	layout = JSON.parse_string(FileAccess.get_file_as_string(path))
	if layout.is_empty():
		return false
	var t0 := Time.get_ticks_msec()
	_body = StaticBody3D.new()       # primitive shapes (boxes, cylinders), added to the tree last
	_body.name = "TownCollision"
	_build_instances()
	add_child(_body)
	add_child(_col_root)
	_build_lights()
	_build_roads()
	print("town: %d multimesh, %d mesh instances, %d collision shapes, %d lights in %d ms" % [
			stats.multimesh, stats.mesh_instances, stats.shapes, stats.lights, Time.get_ticks_msec() - t0])
	return true


# ------------------------------------------------------------------ transforms
static func xf_from(a: Array) -> Transform3D:
	var b := Basis(Vector3(a[0], a[1], a[2]), Vector3(a[3], a[4], a[5]), Vector3(a[6], a[7], a[8]))
	return Transform3D(b, Vector3(a[9], a[10], a[11]))


# ------------------------------------------------------------------ meshes
func _source_mesh(key: String) -> Mesh:
	if _mesh_cache.has(key):
		return _mesh_cache[key]
	var info: Dictionary = layout.meshes[key]
	var mesh: Mesh = null
	var ps = load(DIR + info.file)
	if ps is PackedScene:
		var inst: Node = ps.instantiate()
		var mi := _find_mesh_instance(inst)
		if mi:
			mesh = mi.mesh
		inst.free()
	_mesh_cache[key] = mesh
	if mesh == null:
		push_warning("no mesh in " + info.file)
	return mesh


func _find_mesh_instance(n: Node) -> MeshInstance3D:
	if n is MeshInstance3D:
		return n
	for c in n.get_children():
		var r := _find_mesh_instance(c)
		if r:
			return r
	return null


## A copy of the mesh with the final material on every surface.
func _dressed_mesh(key: String, remap: Dictionary) -> Mesh:
	var src := _source_mesh(key)
	if src == null:
		return null
	var mesh: Mesh = src.duplicate()
	var names: Array = layout.meshes[key].surfaces
	for i in mesh.get_surface_count():
		var nm := ""
		var m := src.surface_get_material(i)
		if m:
			nm = m.resource_name
		if nm == "" and i < names.size():
			nm = names[i]
		nm = remap.get(nm, nm)
		mesh.surface_set_material(i, material(nm))
	return mesh


# ------------------------------------------------------------------ materials
func _tex(path: String) -> Texture2D:
	if _tex_cache.has(path):
		return _tex_cache[path]
	var t: Texture2D = null
	if ResourceLoader.exists(path):
		t = load(path)
	_tex_cache[path] = t
	return t


func material(nm: String) -> Material:
	if _mat_cache.has(nm):
		return _mat_cache[nm]
	var d: Dictionary = layout.materials.get(nm, {})
	var m: BaseMaterial3D
	match d.get("type", "flat"):
		"pigment":
			m = _pigment_material(d)
		"image":
			m = StandardMaterial3D.new()
			m.albedo_texture = _tex(DIR + d.image)
			m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS
			m.roughness = d.get("roughness", 0.6)
			m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
			if float(d.get("emission", 0.0)) > 0.0:
				m.emission_enabled = true
				m.emission_texture = m.albedo_texture
				m.emission_energy_multiplier = float(d.emission)
		_:
			m = _flat_material(nm, d)
	m.resource_name = nm
	_mat_cache[nm] = m
	return m


func _pigment_material(d: Dictionary) -> BaseMaterial3D:
	var base: String = DIR + "textures/" + d.folder + "/"
	var m := ORMMaterial3D.new()
	m.albedo_texture = _tex(base + "albedo.png")
	m.orm_texture = _tex(base + "orm.png")
	var n := _tex(base + "normal.png")
	if n:
		m.normal_enabled = true
		m.normal_texture = n
	var e := _tex(base + "emission.png")
	if e:
		m.emission_enabled = true
		m.emission_texture = e
		m.emission = Color.BLACK
		m.emission_energy_multiplier = float(d.get("emissive_scale", 1.0)) * 1.3
	if d.get("opacity", false):
		# glass is ~0.3 opacity and stays solid (dark reflective panes); only real holes are cut
		m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
		m.alpha_scissor_threshold = 0.15
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	var f: String = d.folder
	if f.begins_with("street") or f.begins_with("junction") or f.begins_with("road"):
		# rain-wet asphalt: darker, glossier (Pigment's puddles stay the glossiest)
		m.albedo_color = Color(0.78, 0.78, 0.8).lerp(Color.WHITE, 1.0 - _wet)
		m.roughness = lerpf(1.0, 0.42, _wet)
		m.metallic_specular = 0.6
	elif f.begins_with("building"):
		m.roughness = lerpf(1.0, 0.85, _wet)
	return m


func _flat_material(nm: String, d: Dictionary) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	var c: Array = d.get("color", [0.5, 0.5, 0.5])
	m.albedo_color = Color(c[0], c[1], c[2])
	m.roughness = float(d.get("roughness", 0.8))
	m.metallic = float(d.get("metallic", 0.0))
	# Blender-procedural materials: approximate with triplanar noise detail
	var detail := false
	match nm:
		"TownPaving":
			m.albedo_color = Color(0.105, 0.105, 0.11)
			m.roughness = lerpf(0.85, 0.5, _wet)
			detail = true
		"TownConcrete":
			m.albedo_color = Color(0.16, 0.155, 0.15)
			m.roughness = 0.85
			detail = true
		"TownRetainingWall":
			m.albedo_color = Color(0.2, 0.19, 0.175)
			m.roughness = 0.8
			detail = true
		"TownAsphaltFallback":
			m.roughness = lerpf(0.6, 0.3, _wet)
	if detail:
		m.albedo_texture = _noise_tex(false)
		m.normal_enabled = true
		m.normal_texture = _noise_tex(true)
		m.normal_scale = 0.6
		m.uv1_triplanar = true
		m.uv1_world_triplanar = true
		m.uv1_scale = Vector3.ONE * 0.35
	if d.has("emission"):
		var e: Array = d.emission
		m.emission_enabled = true
		m.emission = Color(e[0], e[1], e[2])
		m.emission_energy_multiplier = float(d.get("emission_strength", 1.0))
	return m


func _noise_tex(normal: bool) -> Texture2D:
	var key := "noise_n" if normal else "noise_c"
	if _tex_cache.has(key):
		return _tex_cache[key]
	var n := FastNoiseLite.new()
	n.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	n.frequency = 0.02
	n.fractal_octaves = 5
	var t := NoiseTexture2D.new()
	t.width = 512
	t.height = 512
	t.seamless = true
	t.noise = n
	t.generate_mipmaps = true
	if normal:
		t.as_normal_map = true
		t.bump_strength = 6.0
	else:
		var g := Gradient.new()
		g.set_color(0, Color(0.72, 0.72, 0.72))
		g.set_color(1, Color(1.15, 1.12, 1.08))
		t.color_ramp = g
	_tex_cache[key] = t
	return t


# ------------------------------------------------------------------ instances
func _build_instances() -> void:
	# group: mesh + remap -> transforms
	var groups := {}
	for inst in layout.instances:
		var remap: Dictionary = inst.get("remap", {})
		var gk: String = inst.mesh + "|" + JSON.stringify(remap)
		if not groups.has(gk):
			groups[gk] = {"mesh": inst.mesh, "remap": remap, "xf": []}
		groups[gk].xf.append(xf_from(inst.xf))
	var visuals := Node3D.new()
	visuals.name = "Visuals"
	add_child(visuals)
	var shapes_cache := {}
	_col_root = Node3D.new()
	_col_root.name = "TrimeshCollision"
	for gk in groups:
		var g: Dictionary = groups[gk]
		var info: Dictionary = layout.meshes[g.mesh]
		var mesh := _dressed_mesh(g.mesh, g.remap)
		if mesh == null:
			continue
		var cat: String = info.get("cat", "other")
		var vis_end: float = VIS_END.get(cat, 0.0)
		var shadows: bool = CAST_SHADOWS.get(cat, true)
		var xfs: Array = g.xf
		if xfs.size() == 1:
			var mi := MeshInstance3D.new()
			mi.name = g.mesh
			mi.mesh = mesh
			mi.transform = xfs[0]
			_dress(mi, vis_end, shadows)
			visuals.add_child(mi)
			stats.mesh_instances += 1
		else:
			var chunks := {}
			for x in xfs:
				var t: Transform3D = x
				var ck := Vector2i(floori(t.origin.x / CHUNK), floori(t.origin.z / CHUNK))
				if not chunks.has(ck):
					chunks[ck] = []
				chunks[ck].append(t)
			for ck in chunks:
				var list: Array = chunks[ck]
				var mm := MultiMesh.new()
				mm.transform_format = MultiMesh.TRANSFORM_3D
				mm.mesh = mesh
				mm.instance_count = list.size()
				for i in list.size():
					mm.set_instance_transform(i, list[i])
				var mmi := MultiMeshInstance3D.new()
				mmi.name = "%s_%d_%d" % [g.mesh, ck.x, ck.y]
				mmi.multimesh = mm
				_dress(mmi, vis_end, shadows)
				visuals.add_child(mmi)
				stats.multimesh += 1
		# collision
		var col: String = info.get("col", "none")
		if col == "none":
			continue
		var aabb: Array = info.aabb
		var lo := Vector3(aabb[0][0], aabb[0][1], aabb[0][2])
		var hi := Vector3(aabb[1][0], aabb[1][1], aabb[1][2])
		for x in xfs:
			var t: Transform3D = x
			match col:
				"box":
					var sc := t.basis.get_scale()
					var bs := BoxShape3D.new()
					bs.size = ((hi - lo) * sc).abs().max(Vector3.ONE * 0.05)
					var ct := Transform3D(t.basis.orthonormalized(), t * ((lo + hi) * 0.5))
					_add_shape(bs, ct)
				"cyl":
					var cs := CylinderShape3D.new()
					cs.radius = 0.22
					cs.height = maxf(0.5, hi.y - lo.y)
					_add_shape(cs, Transform3D(Basis(), t.origin + Vector3.UP * cs.height * 0.5))
				"trimesh":
					# own body each: Jolt compounds of many mesh shapes run out of sub-shape ID bits
					if not shapes_cache.has(g.mesh):
						shapes_cache[g.mesh] = _source_mesh(g.mesh).create_trimesh_shape()
					var sb := StaticBody3D.new()
					sb.name = "Col_" + g.mesh
					var cs := CollisionShape3D.new()
					cs.shape = shapes_cache[g.mesh]
					cs.transform = t
					sb.add_child(cs)
					_col_root.add_child(sb)
					stats.shapes += 1


func _dress(gi: GeometryInstance3D, vis_end: float, shadows: bool) -> void:
	gi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if shadows else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	if vis_end > 0.0:
		gi.visibility_range_end = vis_end
		gi.visibility_range_end_margin = 10.0


func _add_shape(shape: Shape3D, xf: Transform3D) -> void:
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.transform = xf
	_body.add_child(cs)
	stats.shapes += 1


# ------------------------------------------------------------------ lights
func _build_lights() -> void:
	var root := Node3D.new()
	root.name = "Lights"
	add_child(root)
	for d in layout.lights:
		var c: Array = d.color
		var col := Color(c[0], c[1], c[2])
		var p := Vector3(d.pos[0], d.pos[1], d.pos[2])
		var kind: String = d.kind
		var l: Light3D
		if d.type == "AREA" or d.type == "SPOT":
			var s := SpotLight3D.new()
			s.spot_range = 12.0
			s.spot_angle = 60.0
			s.light_energy = 4.0
			l = s
			root.add_child(l)
			var dir := Vector3(d.dir[0], d.dir[1], d.dir[2])
			l.global_position = p
			if dir.length() > 0.01:
				l.look_at(p + dir, Vector3.UP if absf(dir.normalized().y) < 0.99 else Vector3.RIGHT)
		else:
			var o := OmniLight3D.new()
			match kind:
				"LampLight":
					o.omni_range = 20.0
					o.light_energy = 3.2
					o.light_volumetric_fog_energy = 2.0
					o.light_size = 0.15
					lamp_lights.append(o)
				"AlleyLight":
					o.omni_range = 9.0
					o.light_energy = 2.2
					o.light_volumetric_fog_energy = 1.5
				_:
					o.omni_range = 7.0
					o.light_energy = 1.4
			o.omni_attenuation = 1.4
			l = o
			l.position = p
			root.add_child(l)
		l.light_color = col
		l.shadow_enabled = false
		l.distance_fade_enabled = true
		l.distance_fade_begin = 110.0 if kind == "LampLight" else 60.0
		l.distance_fade_length = 30.0
		l.distance_fade_shadow = 40.0
		stats.lights += 1


# ------------------------------------------------------------------ roads (spawn / reset)
func _build_roads() -> void:
	_compute_bounds()
	_build_edge_walls()
	for poly in _clipped_roads():
		var pts: Array = poly
		for i in pts.size():
			var p := Vector3(pts[i][0], pts[i][1], pts[i][2])
			var a: Array = pts[maxi(0, i - 1)]
			var b: Array = pts[mini(pts.size() - 1, i + 1)]
			var t := Vector3(b[0] - a[0], 0.0, b[2] - a[2]).normalized()
			road_points.append(p)
			road_dirs.append(t)


## Nearest road sample: [position, tangent]
func nearest_road(from: Vector3) -> Array:
	var best := -1
	var bd := INF
	for i in road_points.size():
		var d := road_points[i].distance_squared_to(from)
		if d < bd:
			bd = d
			best = i
	if best < 0:
		return [Vector3(0, 1, 0), Vector3.FORWARD]
	return [road_points[best], road_dirs[best]]


## Playable area: the terrain's extent (roads run on past it to the map edge).
var bounds := AABB(Vector3(-150, -50, -150), Vector3(300, 200, 300))


func _compute_bounds() -> void:
	for key in layout.meshes:
		var m: Dictionary = layout.meshes[key]
		if m.get("cat", "") == "terrain":
			var a: Array = m.aabb
			bounds = AABB(Vector3(a[0][0], a[0][1] - 30.0, a[0][2]), Vector3(a[1][0] - a[0][0], a[1][1] - a[0][1] + 200.0, a[1][2] - a[0][2]))
			return


func _inside(q: Array, margin: float) -> bool:
	return q[0] > bounds.position.x + margin and q[0] < bounds.end.x - margin 			and q[2] > bounds.position.z + margin and q[2] < bounds.end.z - margin


## Road polylines cut to the playable area (keeps the longest inside stretch of each).
func _clipped_roads() -> Array:
	var out := []
	for poly in layout.get("roads", []):
		var best := []
		var cur := []
		for q in poly:
			if _inside(q, 6.0):
				cur.append(q)
			else:
				if cur.size() > best.size():
					best = cur
				cur = []
		if cur.size() > best.size():
			best = cur
		if best.size() > 2:
			out.append(best)
	return out


## Invisible walls on the edge of the playable area.
func _build_edge_walls() -> void:
	var c := bounds.get_center()
	var sz := bounds.size
	for side in [[Vector3(sz.x * 0.5, 0, 0), Vector3(2, sz.y, sz.z)], [Vector3(-sz.x * 0.5, 0, 0), Vector3(2, sz.y, sz.z)],
			[Vector3(0, 0, sz.z * 0.5), Vector3(sz.x, sz.y, 2)], [Vector3(0, 0, -sz.z * 0.5), Vector3(sz.x, sz.y, 2)]]:
		var b := BoxShape3D.new()
		b.size = side[1]
		var sb := StaticBody3D.new()
		sb.name = "EdgeWall"
		var cs := CollisionShape3D.new()
		cs.shape = b
		sb.add_child(cs)
		sb.position = c + side[0]
		add_child(sb)


## Road polylines as arrays of Vector3 (for the autopilot).
func road_polylines() -> Array:
	var out := []
	for poly in _clipped_roads():
		var pts := PackedVector3Array()
		for q in poly:
			pts.append(Vector3(q[0], q[1], q[2]))
		out.append(pts)
	return out


func spawn_transform() -> Transform3D:
	var s = layout.get("spawn")
	if s == null:
		return Transform3D(Basis(), Vector3(0, 2, 0))
	var p := Vector3(s.pos[0], s.pos[1], s.pos[2])
	var d := Vector3(s.dir[0], 0.0, s.dir[2]).normalized()
	return car_transform(p, d)


## Car faces +Z: basis z = travel direction.
static func car_transform(p: Vector3, d: Vector3) -> Transform3D:
	var z := Vector3(d.x, 0.0, d.z).normalized()
	var x := Vector3.UP.cross(z).normalized()
	return Transform3D(Basis(x, Vector3.UP, z), p + Vector3.UP * 0.9)
