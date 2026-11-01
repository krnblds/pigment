extends Node3D
## Builds the town / open world from res://assets/<map>/<map>_layout.json (tools/godot/export_town.py,
## tools/world/world_export.py) and streams it around the player.
##
## Every (mesh, material set) group gets one of these treatments (see _policy and docs/agents/perf/NOTES.md):
##   "cell"    MultiMesh per CELL m cell with a visibility range; the cells are streamed in and out
##             around the camera (props, signs, lamps, poles)
##   "heavy"   detailed buildings: streamed MultiMesh cells like "cell", plus a far proxy (one box per
##             building, lit-window shader) per REGION. The proxy is the cells' visibility parent (HLOD):
##             a region shows either its detailed buildings or its proxy boxes
##   "region"  repeated small meshes (containers, footings, trees): one MultiMesh per REGION, no range
##   "merge"   unique / rare small meshes (roads, junctions, decals, towers, sea walls): merged per
##             REGION and material into one mesh on worker threads
##   "single"  terrain chunks, bridges, water: a MeshInstance3D each (auto LOD from the import)
## Collision is streamed around the car: box / cylinder shapes in one StaticBody per REGION, trimesh
## bodies per mesh, and HeightMapShape3D terrain chunks from heightfield.f32 when the world has one.
## Lights are streamed too: an OmniLight3D exists only while it is inside its own fade distance.

const DIR := "res://assets/town/"
var dir := DIR                 ## res://assets/<map>/ (town or world)
const CELL := 64.0             ## near-detail cells
const REGION := 256.0          ## merged geometry / proxies / collision cells

## visibility range end (m) per category, 0 = always
const VIS_END := {"sign": 220.0, "decal": 150.0, "lamp": 260.0, "pole": 260.0, "rail": 170.0,
		"wire": 200.0, "footing": 260.0, "other": 150.0,
		"bridge_detail": 700.0, "bridge_near": 450.0}
## categories drawn only beyond a distance (far LOD stand-ins: bridge stays as flat ribbons)
const VIS_BEGIN := {"bridge_far": 450.0}
const CAST_SHADOWS := {"building": true, "footing": true, "wall": true, "stairs": true, "lamp": true,
		"pole": true, "sign": true, "terrain": true, "road": false, "decal": false, "wire": false, "rail": true,
		"other": true, "water": false, "bridge_wash": false, "bridge_far": false}
const HEAVY_TRIS := 3000       ## buildings above this get far proxies
const PROXY_NEAR := 330.0      ## a region switches from detailed buildings to proxies this far from its centre
const MERGE_TRIS := 3000       ## meshes up to this size may be merged / region-instanced
const MERGE_MAX_INST := 6      ## ... merged when used at most this often, region MultiMesh otherwise
const COL_RADIUS := 300.0      ## collision exists within this distance of the car (covers the traffic ring)
const TELEPORT := 30.0         ## a focus jump this big in one tick streams its collision in at once
const LIGHT_MARGIN := 15.0     ## lights are created this far beyond their fade-out distance
const STREAM_BUDGET_USEC := 2500
const STREAM_EVERY := 0.2

var layout: Dictionary = {}
var road_points := PackedVector3Array()   ## road centre samples
var road_dirs := PackedVector3Array()     ## unit tangents at the samples
var lamp_lights: Array = []               ## street lamps that currently exist (main.gd shadows the nearest)
var stats := {"multimesh": 0, "mesh_instances": 0, "shapes": 0, "lights": 0}
var collision_focus: Node3D               ## the car (collision streams around it); camera if null
var streaming := true

var _mesh_cache := {}
var _dressed := {}             ## mesh key -> remap json of its in-place dressing
var _mat_cache := {}
var _tex_cache := {}
var _wet := 1.0
var _headless := false
var _visuals: Node3D
var _lights_root: Node3D
var _col_root: Node3D

# streaming state
var _cells := {}               ## Vector3i(x, y, 0 = CELL cell | 1 = REGION) -> {"center": Vector2, "r": float, "entries": Array}
var _cell_nodes := {}          ## Vector2i -> Array[Node]
var _proxies := {}             ## Vector2i region -> MultiMeshInstance3D
var _col_items: Array = []     ## {rect: Rect2, node, kind, ...}
var _lights: Array = []        ## light dicts
var _light_grid := {}          ## Vector2i(CELL) -> Array[int]
var _light_nodes := {}         ## int -> Light3D
var _queue: Array = []         ## pending Callables (stream-in work)
var _stream_t := 0.0
var _arrays_cache := {}        ## mesh key -> Array of surface arrays (merging, collision)
var _arrays_mats := {}         ## mesh key -> material name per surface
var _hf: PackedFloat32Array
var _hf_meta := {}
var _proxy_mat: ShaderMaterial


func load_town(wet := 1.0, map := "town") -> bool:
	_wet = wet
	_headless = DisplayServer.get_name() == "headless"
	process_priority = 100        # stream after the camera has moved this frame
	process_physics_priority = -100   # teleport check before the car / traffic scripts
	dir = "res://assets/%s/" % map
	var path := dir + "%s_layout.json" % map
	if not FileAccess.file_exists(path):
		push_warning("town layout missing: %s (run tools/godot/export_town.py)" % path)
		return false
	var t0 := Time.get_ticks_msec()
	layout = JSON.parse_string(FileAccess.get_file_as_string(path))
	if layout.is_empty():
		return false
	_visuals = Node3D.new()
	_visuals.name = "Visuals"
	add_child(_visuals)
	_col_root = Node3D.new()
	_col_root.name = "Collision"
	add_child(_col_root)
	_lights_root = Node3D.new()
	_lights_root.name = "Lights"
	add_child(_lights_root)
	_load_heightfield(map)
	var groups := _group_instances()
	for g in groups:
		g["pol"] = _policy(layout.meshes[g.mesh], g.xf.size())
	# scenes only for what is drawn as itself; merged / collision meshes come as arrays (_load_arrays)
	_preload_meshes(groups.filter(func(g): return g.pol != "merge" and not _headless))
	stats["mesh_load_ms"] = Time.get_ticks_msec() - t0
	_build_groups(groups)
	_index_lights()
	_build_roads()
	stream_now(spawn_transform().origin)
	stats["load_ms"] = Time.get_ticks_msec() - t0
	print("town: %d multimesh, %d mesh instances, %d collision shapes (%d streamed items), %d lights (%d live) in %d ms %s" % [
			stats.multimesh, stats.mesh_instances, stats.shapes, _col_items.size(), _lights.size(), _light_nodes.size(),
			stats.load_ms, JSON.stringify(stats)])
	return true


# ------------------------------------------------------------------ transforms
static func xf_from(a: Array) -> Transform3D:
	var b := Basis(Vector3(a[0], a[1], a[2]), Vector3(a[3], a[4], a[5]), Vector3(a[6], a[7], a[8]))
	return Transform3D(b, Vector3(a[9], a[10], a[11]))


static func _key(p: Vector3, size: float) -> Vector2i:
	return Vector2i(floori(p.x / size), floori(p.z / size))


static func _center(k: Vector2i, size: float) -> Vector2:
	return Vector2((k.x + 0.5) * size, (k.y + 0.5) * size)


# ------------------------------------------------------------------ meshes
func _preload_meshes(groups: Array) -> void:
	# all glbs at once on the loader's threads
	var files := {}
	for g in groups:
		files[dir + layout.meshes[g.mesh].file] = true
	for f in files:
		ResourceLoader.load_threaded_request(f, "", true)
	for g in groups:
		_source_mesh(g.mesh)


func _source_mesh(key: String) -> Mesh:
	if _mesh_cache.has(key):
		return _mesh_cache[key]
	var info: Dictionary = layout.meshes[key]
	var mesh: Mesh = null
	var f: String = dir + info.file
	var ps = null
	if ResourceLoader.load_threaded_get_status(f) != ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
		ps = ResourceLoader.load_threaded_get(f)
	else:
		ps = load(f)
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


## Material names per surface after the remap.
func _surface_materials(key: String, remap: Dictionary) -> Array:
	var names: Array = layout.meshes[key].surfaces
	var out := []
	if _arrays_mats.has(key) and not _mesh_cache.has(key):
		for nm in _arrays_mats[key]:
			out.append(remap.get(nm, nm))
		return out
	var src := _source_mesh(key)
	if src == null:
		return out
	for i in src.get_surface_count():
		var nm := ""
		var m := src.surface_get_material(i)
		if m:
			nm = m.resource_name
		if nm == "" and i < names.size():
			nm = names[i]
		out.append(remap.get(nm, nm))
	return out


## The mesh with the final material on every surface. The first dressing of a mesh is done in place
## (no copy: duplicating an ArrayMesh is a GPU read-back plus a second upload); other remaps copy it.
func _dressed_mesh(key: String, remap: Dictionary) -> Mesh:
	var src := _source_mesh(key)
	if src == null:
		return null
	var rk := JSON.stringify(remap)
	var mats := _surface_materials(key, remap)
	var mesh: Mesh = src
	if _dressed.has(key) and _dressed[key] != rk:
		mesh = src.duplicate()
	else:
		_dressed[key] = rk
	for i in mesh.get_surface_count():
		mesh.surface_set_material(i, material(mats[i]))
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


## Road surfaces rebuilt from the full Pigment map set (tools/godot/pack_textures.py road_maps) with
## scripts/road_surface.gdshader: tile size in metres, how much water the surface collects ("wet", as in
## tools/town_roads.py), how much of it a rain film covers, tone variation, world projection.
const ROAD_SURFACES := {
	"RoadAsphalt": {"tile": "asphalt", "tile_m": 4.0, "wet": 1.0, "film": 0.85, "macro": 0.25, "anti": true, "box": false, "normal": 1.0},
	"RoadPaving": {"tile": "paving", "tile_m": 2.0, "wet": 0.6, "film": 0.55, "macro": 0.18, "anti": false, "box": false, "normal": 1.0},
	"RoadConcrete": {"tile": "concrete", "tile_m": 2.0, "wet": 0.0, "film": 0.0, "macro": 0.2, "anti": false, "box": true, "normal": 0.8},
	# the curb / gutter trim sheet: its UVs address the strips, U wraps every 2 m
	"RoadTrim": {"tile": "trim", "tile_m": 1.0, "wet": 0.8, "film": 0.6, "macro": 0.15, "anti": false, "box": false, "normal": 1.0, "metal": true},
}
const ROAD_SHADER := preload("res://scripts/road_surface.gdshader")
const ROAD_DECAL_SHADER := preload("res://scripts/road_decal.gdshader")
var road_materials: Array[ShaderMaterial] = []


## Rain on / off for every road surface (puddles, film, ripples).
func set_road_rain(v: float) -> void:
	_wet = v
	for m in road_materials:
		m.set_shader_parameter("rain", v)


func _road_tex(tile: String, map: String) -> Texture2D:
	return _tex(dir + "images/roads/%s_%s.png" % [tile, map])


func _road_material(nm: String) -> Material:
	if ROAD_SURFACES.has(nm):
		var r: Dictionary = ROAD_SURFACES[nm]
		var albedo := _road_tex(r.tile, "BaseColor")
		if albedo == null:
			return null
		var m := ShaderMaterial.new()
		m.shader = ROAD_SHADER
		m.set_shader_parameter("albedo_tex", albedo)
		m.set_shader_parameter("rough_tex", _road_tex(r.tile, "Roughness"))
		m.set_shader_parameter("normal_tex", _road_tex(r.tile, "Normal_OpenGL"))
		m.set_shader_parameter("height_tex", _road_tex(r.tile, "Height"))
		if r.get("metal", false):
			var met := _road_tex(r.tile, "Metallic")
			if met:
				m.set_shader_parameter("metal_tex", met)
				m.set_shader_parameter("use_metal", true)
		m.set_shader_parameter("tile_m", r.tile_m)
		m.set_shader_parameter("wet", r.wet)
		m.set_shader_parameter("film", r.film)
		m.set_shader_parameter("macro", r.macro)
		m.set_shader_parameter("anti_tile", r.anti)
		m.set_shader_parameter("world_box", r.box)
		m.set_shader_parameter("normal_strength", r.normal)
		m.set_shader_parameter("rain", _wet)
		road_materials.append(m)
		return m
	if nm == "RoadDecals":
		# painted markings, cracks, patches, manholes: cut out by alpha, no shadows of their own
		var albedo := _road_tex("atlas", "BaseColorAlpha")
		if albedo == null:
			return null
		var d := ShaderMaterial.new()
		d.shader = ROAD_DECAL_SHADER
		d.set_shader_parameter("albedo_tex", albedo)
		d.set_shader_parameter("rough_tex", _road_tex("atlas", "Roughness"))
		d.set_shader_parameter("normal_tex", _road_tex("atlas", "Normal_OpenGL"))
		d.set_shader_parameter("height_tex", _road_tex("atlas", "Height"))
		d.set_shader_parameter("metal_tex", _road_tex("atlas", "Metallic"))
		d.set_shader_parameter("rain", _wet)
		d.render_priority = 1
		road_materials.append(d)
		return d
	return null


func material(nm: String) -> Material:
	if _mat_cache.has(nm):
		return _mat_cache[nm]
	if nm.begins_with("Road") and nm != "RoadMetal":
		var rm := _road_material(nm)
		if rm:
			rm.resource_name = nm
			_mat_cache[nm] = rm
			return rm
	var d: Dictionary = layout.materials.get(nm, {})
	var m: BaseMaterial3D
	match d.get("type", "flat"):
		"pigment":
			m = _pigment_material(d)
		"image":
			m = StandardMaterial3D.new()
			m.albedo_texture = _tex(dir + d.image)
			# only images that really carry alpha (decal atlases) blend. The export flags every image
			# "alpha", which made roads, terrain and facades transparent (no depth pre-pass, no SSR / SSAO)
			if m.albedo_texture == null or m.albedo_texture.has_alpha():
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
	var base: String = dir + "textures/" + d.folder + "/"
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


## Far proxies: dark facade, a hashed grid of lit windows (per-instance seed in INSTANCE_CUSTOM).
func _proxy_material() -> ShaderMaterial:
	if _proxy_mat:
		return _proxy_mat
	_proxy_mat = ShaderMaterial.new()
	_proxy_mat.shader = load("res://scripts/proxy_building.gdshader")
	return _proxy_mat


# ------------------------------------------------------------------ instances
func _group_instances() -> Array:
	var groups := {}
	for inst in layout.instances:
		if not layout.meshes.has(inst.mesh):
			continue
		var remap: Dictionary = inst.get("remap", {})
		var gk: String = inst.mesh + "|" + JSON.stringify(remap)
		if not groups.has(gk):
			groups[gk] = {"mesh": inst.mesh, "remap": remap, "xf": []}
		groups[gk].xf.append(xf_from(inst.xf))
	return groups.values()


func _policy(info: Dictionary, n: int) -> String:
	var cat: String = info.get("cat", "other")
	var tris: int = int(info.get("tris", 0))
	if cat in ["terrain", "water", "bridge", "wire", "bridge_detail", "bridge_near", "bridge_far", "bridge_wash"]:
		return "single"
	if cat == "building" and tris > HEAVY_TRIS:
		return "heavy"
	if cat in ["road", "decal", "wall", "rail", "stairs"] and n == 1:
		return "merge"
	if tris <= MERGE_TRIS and cat not in ["other", "sign", "lamp", "pole"]:
		return "merge" if n <= MERGE_MAX_INST else "region"
	return "cell"


func _dress(gi: GeometryInstance3D, vis_end: float, shadows: bool) -> void:
	gi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if shadows else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	if vis_end > 0.0:
		gi.visibility_range_end = vis_end
		gi.visibility_range_end_margin = 10.0


static func _mm_buffer(xfs: Array) -> PackedFloat32Array:
	var buf := PackedFloat32Array()
	buf.resize(xfs.size() * 12)
	var o := 0
	for x in xfs:
		var t: Transform3D = x
		var b := t.basis
		buf[o] = b.x.x
		buf[o + 1] = b.y.x
		buf[o + 2] = b.z.x
		buf[o + 3] = t.origin.x
		buf[o + 4] = b.x.y
		buf[o + 5] = b.y.y
		buf[o + 6] = b.z.y
		buf[o + 7] = t.origin.y
		buf[o + 8] = b.x.z
		buf[o + 9] = b.y.z
		buf[o + 10] = b.z.z
		buf[o + 11] = t.origin.z
		o += 12
	return buf


func _new_mmi(nm: String, mesh: Mesh, buf: PackedFloat32Array, n: int) -> MultiMeshInstance3D:
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = n
	mm.buffer = buf
	var mmi := MultiMeshInstance3D.new()
	mmi.name = nm
	mmi.multimesh = mm
	return mmi


func _build_groups(groups: Array) -> void:
	var merge_jobs := {}       # "rx,ry,vis,shadow" -> {"key", "vis", "shadows", "parts": [[mesh key, xf, mats]]}
	var visual_keys := {}      # meshes drawn as themselves
	var proxies := {}          # region -> Array of Transform3D (unit box -> building bounds)
	# arrays (no GPU round trip) for every mesh that is merged or becomes collision
	var akeys := {}
	for g in groups:
		var col: String = layout.meshes[g.mesh].get("col", "none")
		if (g.pol == "merge" and not _headless) or col == "trimesh":
			akeys[g.mesh] = true
	_load_arrays(akeys)
	for g in groups:
		var info: Dictionary = layout.meshes[g.mesh]
		var cat: String = info.get("cat", "other")
		var vis_end: float = VIS_END.get(cat, 0.0)
		var shadows: bool = CAST_SHADOWS.get(cat, true)
		var xfs: Array = g.xf
		var pol: String = g.pol
		_index_collision(g.mesh, info, xfs)
		if _headless:
			continue
		if pol == "merge" and not _arrays_cache.has(g.mesh) or pol != "merge" and _source_mesh(g.mesh) == null:
			continue
		var a: Array = info.aabb
		var lo := Vector3(a[0][0], a[0][1], a[0][2])
		var hi := Vector3(a[1][0], a[1][1], a[1][2])
		var local_c := (lo + hi) * 0.5
		if pol != "merge":
			visual_keys[g.mesh] = true
		match pol:
			"single":
				var mesh := _dressed_mesh(g.mesh, g.remap)
				for x in xfs:
					var mi := MeshInstance3D.new()
					mi.name = g.mesh
					mi.mesh = mesh
					mi.transform = x
					_dress(mi, vis_end, shadows)
					if VIS_BEGIN.has(cat):
						mi.visibility_range_begin = VIS_BEGIN[cat]
						mi.visibility_range_begin_margin = 10.0
					_visuals.add_child(mi)
					stats.mesh_instances += 1
			"region":
				var mesh := _dressed_mesh(g.mesh, g.remap)
				var by := {}
				for x in xfs:
					var t: Transform3D = x
					var k := _key(t * local_c, REGION)
					if not by.has(k):
						by[k] = []
					by[k].append(t)
				for k in by:
					var mmi := _new_mmi("%s_r%d_%d" % [g.mesh, k.x, k.y], mesh, _mm_buffer(by[k]), by[k].size())
					_dress(mmi, vis_end, shadows)
					_visuals.add_child(mmi)
					stats.multimesh += 1
			"merge":
				var mats := _surface_materials(g.mesh, g.remap)
				for m in mats:
					material(m)
				for x in xfs:
					var t: Transform3D = x
					var k := _key(t * local_c, REGION)
					var jk := "%d,%d,%d,%d" % [k.x, k.y, int(vis_end), int(shadows)]
					if not merge_jobs.has(jk):
						merge_jobs[jk] = {"key": k, "vis": vis_end, "shadows": shadows, "parts": []}
					merge_jobs[jk].parts.append([g.mesh, t, mats])
			_:   # "heavy", "cell"
				var mesh := _dressed_mesh(g.mesh, g.remap)
				var by := {}
				for x in xfs:
					var t: Transform3D = x
					var k := _key(t * local_c, CELL)
					if not by.has(k):
						by[k] = []
					by[k].append(t)
					if pol == "heavy":
						var rk := _key(t * local_c, REGION)
						if not proxies.has(rk):
							proxies[rk] = []
						var size := (hi - lo).max(Vector3.ONE * 0.5)
						proxies[rk].append(t * Transform3D(Basis.from_scale(size), local_c))
				for k in by:
					var e := {"name": "%s_%d_%d" % [g.mesh, k.x, k.y], "mesh": mesh, "buf": _mm_buffer(by[k]),
						"n": by[k].size(), "vis": vis_end, "shadows": shadows, "region": null}
					# streaming unit: the cell itself, or for detailed buildings the whole region, which
					# shows them while its centre is within PROXY_NEAR (the proxy is their visibility parent)
					var uk := Vector3i(k.x, k.y, 0)
					var center := _center(k, CELL)
					var r := vis_end + CELL * 0.75 if vis_end > 0.0 else 1.0e9
					if pol == "heavy":
						e.region = _key(Vector3(center.x, 0.0, center.y), REGION)     # a cell lies in one region
						e.vis = 0.0
						uk = Vector3i(e.region.x, e.region.y, 1)
						center = _center(e.region, REGION)
						r = PROXY_NEAR + 60.0
					if not _cells.has(uk):
						_cells[uk] = {"center": center, "r": 0.0, "entries": []}
					_cells[uk].entries.append(e)
					_cells[uk].r = maxf(_cells[uk].r, r)
	_build_proxies(proxies)
	_prepare_collision()
	_run_merges(merge_jobs.values())
	_arrays_cache.clear()
	_arrays_mats.clear()


func _build_proxies(proxies: Dictionary) -> void:
	if proxies.is_empty():
		return
	var box := BoxMesh.new()
	box.size = Vector3.ONE
	box.material = _proxy_material()
	var root := Node3D.new()
	root.name = "Proxies"
	_visuals.add_child(root)
	for k in proxies:
		var list: Array = proxies[k]
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.use_custom_data = true
		mm.mesh = box
		mm.instance_count = list.size()
		for i in list.size():
			var t: Transform3D = list[i]
			mm.set_instance_transform(i, t)
			var h := hash(Vector2i(roundi(t.origin.x * 10.0), roundi(t.origin.z * 10.0)))
			mm.set_instance_custom_data(i, Color(float(h & 1023) / 1023.0, float((h >> 10) & 1023) / 1023.0, 0, 0))
		var mmi := MultiMeshInstance3D.new()
		mmi.name = "proxy_%d_%d" % [k.x, k.y]
		mmi.multimesh = mm
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		mmi.visibility_range_begin = PROXY_NEAR
		mmi.visibility_range_begin_margin = 10.0
		root.add_child(mmi)
		_proxies[k] = mmi
		stats.multimesh += 1


# ------------------------------------------------------------------ merging (worker threads)
func _run_merges(jobs: Array) -> void:
	if jobs.is_empty():
		return
	var t0 := Time.get_ticks_msec()
	var results := []
	results.resize(jobs.size())
	var task := WorkerThreadPool.add_group_task(func(i: int): results[i] = _merge_job(jobs[i]), jobs.size(), -1, true, "merge")
	WorkerThreadPool.wait_for_group_task_completion(task)
	var root := Node3D.new()
	root.name = "Merged"
	_visuals.add_child(root)
	for i in jobs.size():
		var j: Dictionary = jobs[i]
		var mesh: ArrayMesh = results[i]
		if mesh == null:
			continue
		for s in mesh.get_surface_count():
			mesh.surface_set_material(s, material(mesh.surface_get_name(s)))
		var mi := MeshInstance3D.new()
		mi.name = "merged_%d_%d_%d" % [j.key.x, j.key.y, int(j.vis)]
		mi.mesh = mesh
		var vis: float = j.vis
		_dress(mi, vis + REGION * 0.71 if vis > 0.0 else 0.0, j.shadows)
		root.add_child(mi)
		stats.mesh_instances += 1
	stats["merge_ms"] = Time.get_ticks_msec() - t0


## parts: [mesh key, Transform3D, material names] -> one ArrayMesh, a surface per material
## (named after it; the materials are set on the main thread)
func _merge_job(job: Dictionary) -> ArrayMesh:
	var by_mat := {}
	for p in job.parts:
		var surfs: Array = _arrays_cache[p[0]]
		var mats: Array = p[2]
		for i in surfs.size():
			var nm: String = mats[i] if i < mats.size() else ""
			if not by_mat.has(nm):
				by_mat[nm] = []
			by_mat[nm].append([surfs[i], p[1]])
	var mesh := ArrayMesh.new()
	var merged := {}
	for nm in by_mat:
		var arrays := _merge_arrays(by_mat[nm])
		if not arrays.is_empty():
			merged[nm] = arrays
	if merged.has("RoadAsphalt") and merged.has("RoadTrim"):
		_wet_bias(merged["RoadAsphalt"], merged["RoadTrim"])
	for nm in merged:
		var arrays: Array = merged[nm]
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
		mesh.surface_set_name(mesh.get_surface_count() - 1, nm)
	return mesh if mesh.get_surface_count() > 0 else null


## The Blender roads carry a "wet_bias" attribute (tools/town_roads.py: gutters and the asphalt next to
## them collect water). Exports from tools/godot/export_town.py keep it as vertex colour (R = 1 - wet_bias);
## for older exports it is rebuilt here: the gutter strip of the trim sheet (UV.v 0.25..0.475, Blender's
## "Gutter" cell flipped) gets 0.36 at its road edge .. 0.6 at the curb, the asphalt 0.8 at the gutter
## fading to 0 over 1.2 m, as SectionBuilder.side() / build_run() write it.
const GUTTER_V := Vector2(0.25, 0.475)


static func _wet_bias(asphalt: Array, trim: Array) -> void:
	if asphalt[Mesh.ARRAY_COLOR] != null and trim[Mesh.ARRAY_COLOR] != null:
		var ca: PackedColorArray = asphalt[Mesh.ARRAY_COLOR]
		var dry := true
		for c in ca:
			if c.r < 0.999:
				dry = false
				break
		if not dry:
			return              # exported with the attribute
	var tv: PackedVector3Array = trim[Mesh.ARRAY_VERTEX]
	var tuv: PackedVector2Array = trim[Mesh.ARRAY_TEX_UV] if trim[Mesh.ARRAY_TEX_UV] != null else PackedVector2Array()
	if tuv.size() != tv.size():
		return
	var tc := PackedColorArray()
	tc.resize(tv.size())
	var grid := {}           # 1.5 m cells -> gutter road-edge points (x, z)
	for i in tv.size():
		var v := tuv[i].y
		var w := 0.0
		if v >= GUTTER_V.x - 0.002 and v <= GUTTER_V.y + 0.002:
			var t := clampf((GUTTER_V.y - v) / (GUTTER_V.y - GUTTER_V.x), 0.0, 1.0)
			w = lerpf(0.36, 0.6, t)
			if t < 0.05:
				var p := tv[i]
				var k := Vector2i(floori(p.x / 1.5), floori(p.z / 1.5))
				if not grid.has(k):
					grid[k] = PackedVector3Array()
				grid[k].append(p)
		tc[i] = Color(1.0 - w, 1.0, 1.0, 1.0)
	trim[Mesh.ARRAY_COLOR] = tc
	var av: PackedVector3Array = asphalt[Mesh.ARRAY_VERTEX]
	var ac := PackedColorArray()
	ac.resize(av.size())
	for i in av.size():
		var p := av[i]
		var k := Vector2i(floori(p.x / 1.5), floori(p.z / 1.5))
		var best := 4.0
		for dz in range(-1, 2):
			for dx in range(-1, 2):
				var pts = grid.get(k + Vector2i(dx, dz))
				if pts == null:
					continue
				for q in pts:
					if absf(q.y - p.y) < 0.3:
						best = minf(best, Vector2(q.x - p.x, q.z - p.z).length_squared())
		var d := sqrt(best)
		var w := 0.8 * (1.0 - smoothstep(0.0, 1.2, d))
		ac[i] = Color(1.0 - w, 1.0, 1.0, 1.0)
	asphalt[Mesh.ARRAY_COLOR] = ac


static func _merge_arrays(parts: Array) -> Array:
	var has_n := false
	var has_t := false
	var has_uv := false
	var has_uv2 := false
	var has_c := false
	for p in parts:
		var a: Array = p[0]
		has_n = has_n or a[Mesh.ARRAY_NORMAL] != null
		has_t = has_t or a[Mesh.ARRAY_TANGENT] != null
		has_uv = has_uv or a[Mesh.ARRAY_TEX_UV] != null
		has_uv2 = has_uv2 or a[Mesh.ARRAY_TEX_UV2] != null
		has_c = has_c or a[Mesh.ARRAY_COLOR] != null
	var V := PackedVector3Array()
	var N := PackedVector3Array()
	var T := PackedFloat32Array()
	var UV := PackedVector2Array()
	var UV2 := PackedVector2Array()
	var C := PackedColorArray()
	var I := PackedInt32Array()
	for p in parts:
		var a: Array = p[0]
		var xf: Transform3D = p[1]
		var v: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
		var nv := v.size()
		if nv == 0:
			continue
		var base := V.size()
		var ident := xf.basis.is_equal_approx(Basis.IDENTITY)
		V.append_array(v if ident and xf.origin == Vector3.ZERO else xf * v)
		var rot := Transform3D(xf.basis, Vector3.ZERO)
		if has_n:
			if a[Mesh.ARRAY_NORMAL] != null:
				var nn: PackedVector3Array = a[Mesh.ARRAY_NORMAL]
				N.append_array(nn if ident else rot * nn)
			else:
				var f := PackedVector3Array()
				f.resize(nv)
				f.fill(Vector3.UP)
				N.append_array(f)
		if has_t:
			var t := PackedFloat32Array()
			if a[Mesh.ARRAY_TANGENT] != null:
				t = a[Mesh.ARRAY_TANGENT]
			if t.size() != nv * 4:
				t = PackedFloat32Array()
				t.resize(nv * 4)
				for k in nv:
					t[k * 4] = 1.0
					t[k * 4 + 3] = 1.0
			elif not ident:
				t = t.duplicate()
				for k in nv:
					var tv := xf.basis * Vector3(t[k * 4], t[k * 4 + 1], t[k * 4 + 2])
					t[k * 4] = tv.x
					t[k * 4 + 1] = tv.y
					t[k * 4 + 2] = tv.z
			T.append_array(t)
		if has_uv:
			var u := PackedVector2Array()
			if a[Mesh.ARRAY_TEX_UV] != null:
				u = a[Mesh.ARRAY_TEX_UV]
			else:
				u.resize(nv)
			UV.append_array(u)
		if has_uv2:
			var u2 := PackedVector2Array()
			if a[Mesh.ARRAY_TEX_UV2] != null:
				u2 = a[Mesh.ARRAY_TEX_UV2]
			else:
				u2.resize(nv)
			UV2.append_array(u2)
		if has_c:
			var c := PackedColorArray()
			if a[Mesh.ARRAY_COLOR] != null:
				c = a[Mesh.ARRAY_COLOR]
			else:
				c.resize(nv)
				c.fill(Color.WHITE)
			C.append_array(c)
		var start := I.size()
		if a[Mesh.ARRAY_INDEX] == null:
			I.resize(start + nv)
			for k in nv:
				I[start + k] = base + k
		else:
			I.append_array(a[Mesh.ARRAY_INDEX])
			if base != 0:
				for k in range(start, I.size()):
					I[k] += base
		if xf.basis.determinant() < 0.0:      # mirrored: keep the winding
			for k in range(start, I.size(), 3):
				var s := I[k + 1]
				I[k + 1] = I[k + 2]
				I[k + 2] = s
	if V.is_empty():
		return []
	var out := []
	out.resize(Mesh.ARRAY_MAX)
	out[Mesh.ARRAY_VERTEX] = V
	if has_n:
		out[Mesh.ARRAY_NORMAL] = N
	if has_t:
		out[Mesh.ARRAY_TANGENT] = T
	if has_uv:
		out[Mesh.ARRAY_TEX_UV] = UV
	if has_uv2:
		out[Mesh.ARRAY_TEX_UV2] = UV2
	if has_c:
		out[Mesh.ARRAY_COLOR] = C
	out[Mesh.ARRAY_INDEX] = I
	return out


# ------------------------------------------------------------------ collision (streamed around the car)
## Collision lives in COL_CELL cells: one StaticBody3D per cell holds its boxes / cylinders, another its
## triangle soup (every trimesh mesh's triangles, cut up by centroid, so no Jolt mesh shape is bigger
## than a cell: a whole 1.6 km viaduct took ~40 ms to build on the main thread). Terrain chunks use
## HeightMapShape3D from heightfield.f32 when the world has one. Faces and heights are prepared on
## worker threads at load; streaming only creates the shapes.
const COL_CELL := 64.0

var _col_cells := {}           ## Vector2i -> item {"kind": "cell", "shapes": [], "faces": PackedVector3Array}
var _trimesh_parts: Array = [] ## [mesh key, Transform3D]


func _load_heightfield(map: String) -> void:
	var wp := dir + "world.json"
	if map == "town" or not FileAccess.file_exists(wp):
		return
	var w = JSON.parse_string(FileAccess.get_file_as_string(wp))
	if w == null or not w.has("terrain"):
		return
	var t: Dictionary = w.terrain
	var hp: String = dir + String(t.get("heightfield", "heightfield.f32"))
	if not FileAccess.file_exists(hp):
		return
	var n := int(t.n)
	var bytes := FileAccess.get_file_as_bytes(hp)
	if bytes.size() != n * n * 4:
		return
	_hf = bytes.to_float32_array()
	_hf_meta = {"n": n, "cell": float(t.cell_m), "ox": float(t.origin[0]), "oy": float(t.origin[1]),
		"chunk_cells": int(t.get("chunk_cells", 128)), "chunks": {}}
	for c in t.get("chunks", []):
		_hf_meta.chunks["Terrain_" + String(c.id)] = c


func _col_cell(k: Vector2i) -> Dictionary:
	if not _col_cells.has(k):
		var c := _center(k, COL_CELL)
		# slack: shapes and triangles near the edge reach over it
		var item := {"kind": "cell", "shapes": [], "faces": {}, "rep": {}, "node": null,
			"rect": Rect2(c.x - COL_CELL * 0.5 - 20.0, c.y - COL_CELL * 0.5 - 20.0, COL_CELL + 40.0, COL_CELL + 40.0)}
		_col_cells[k] = item
		_col_items.append(item)
	return _col_cells[k]


func _index_collision(key: String, info: Dictionary, xfs: Array) -> void:
	var col: String = info.get("col", "none")
	if col == "none":
		return
	var aabb: Array = info.aabb
	var lo := Vector3(aabb[0][0], aabb[0][1], aabb[0][2])
	var hi := Vector3(aabb[1][0], aabb[1][1], aabb[1][2])
	for x in xfs:
		var t: Transform3D = x
		match col:
			"box":
				var sc := t.basis.get_scale()
				var ct := Transform3D(t.basis.orthonormalized(), t * ((lo + hi) * 0.5))
				_col_cell(_key(ct.origin, COL_CELL)).shapes.append(["box", ((hi - lo) * sc).abs().max(Vector3.ONE * 0.05), ct])
			"cyl":
				var h := maxf(0.5, hi.y - lo.y)
				_col_cell(_key(t.origin, COL_CELL)).shapes.append(["cyl", h, Transform3D(Basis(), t.origin + Vector3.UP * h * 0.5)])
			"trimesh":
				if _hf_meta.has("chunks") and _hf_meta.chunks.has(key) and t.basis.is_equal_approx(Basis.IDENTITY) \
						and t.origin.is_zero_approx():
					var wb: AABB = t * AABB(lo, hi - lo)
					_col_items.append({"kind": "height", "key": key, "node": null, "data": null,
						"rect": Rect2(wb.position.x, wb.position.z, wb.size.x, wb.size.z)})
				else:
					_trimesh_parts.append([key, t])


## Surface arrays + material names of the meshes that are merged or become collision. The glbs are
## parsed directly on worker threads (GLTFDocument: ~0.4 ms a file, no GPU); where the source glb is
## not there (an exported build has only the imported scenes) the imported mesh is read back instead.
func _load_arrays(keys: Dictionary) -> void:
	var t0 := Time.get_ticks_msec()
	var list: Array = keys.keys()
	var res := []
	res.resize(list.size())
	var task := WorkerThreadPool.add_group_task(func(i: int): res[i] = _gltf_arrays(dir + layout.meshes[list[i]].file),
			list.size(), -1, true, "glb arrays")
	WorkerThreadPool.wait_for_group_task_completion(task)
	var fallback := 0
	for i in list.size():
		var k: String = list[i]
		var r = res[i]
		if r == null:
			fallback += 1
			var m := _source_mesh(k)
			r = {"arrays": [], "mats": []}
			if m:
				for si in m.get_surface_count():
					r.arrays.append(m.surface_get_arrays(si))
					var mat := m.surface_get_material(si)
					r.mats.append(mat.resource_name if mat else "")
		var names: Array = layout.meshes[k].surfaces
		for si in r.mats.size():
			if r.mats[si] == "" and si < names.size():
				r.mats[si] = names[si]
		_arrays_cache[k] = r.arrays
		_arrays_mats[k] = r.mats
	stats["arrays_ms"] = Time.get_ticks_msec() - t0
	stats["arrays_readback"] = fallback


static func _gltf_arrays(path: String):
	if not FileAccess.file_exists(path):
		return null
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(ProjectSettings.globalize_path(path), st) != OK or st.meshes.is_empty():
		return null
	var m: ImporterMesh = st.meshes[0].mesh
	var out := {"arrays": [], "mats": []}
	for i in m.get_surface_count():
		out.arrays.append(m.get_surface_arrays(i))
		var mat := m.get_surface_material(i)
		out.mats.append(mat.resource_name if mat else m.get_surface_name(i))
	return out


## Worker threads: triangle soups per collision cell, heights per terrain chunk.
func _prepare_collision() -> void:
	var t0 := Time.get_ticks_msec()
	var results := []
	results.resize(_trimesh_parts.size())
	var task := WorkerThreadPool.add_group_task(func(i: int): results[i] = _faces_job(_trimesh_parts[i]),
			_trimesh_parts.size(), -1, true, "collision faces")
	var heights: Array = _col_items.filter(func(it): return it.kind == "height")
	var htask := WorkerThreadPool.add_group_task(func(i: int): heights[i].data = _height_data(heights[i].key),
			heights.size(), -1, true, "heights")
	WorkerThreadPool.wait_for_group_task_completion(task)
	WorkerThreadPool.wait_for_group_task_completion(htask)
	for i in results.size():
		var key: String = _trimesh_parts[i][0]
		var cat: String = layout.meshes[key].get("cat", "other")
		for k3 in results[i]:
			var it := _col_cell(Vector2i(k3.x, k3.y))
			# road meshes are split by surface material (asphalt / kerb / paving / concrete / metal), so
			# the car's tyres can tell them apart: the body keeps the "Col_<mesh>" name, plus a meta
			var grp: String = cat if k3.z == 0 else cat + "/" + SURF_KINDS[k3.z]
			if not it.faces.has(grp):
				it.faces[grp] = PackedVector3Array()
				it.rep[grp] = key
			it.faces[grp].append_array(results[i][k3])
	_trimesh_parts.clear()
	stats["collision_prep_ms"] = Time.get_ticks_msec() - t0


const SURF_KINDS := ["", "asphalt", "curb", "paving", "concrete", "metal"]


## Material name -> index in SURF_KINDS (0: don't split).
static func surface_kind(mat: String) -> int:
	var m := mat.to_lower()
	if m.contains("asphalt"):
		return 1
	if m.contains("trim") or m.contains("curb"):
		return 2
	if m.contains("paving"):
		return 3
	if m.contains("concrete"):
		return 4
	if m.contains("metal"):
		return 5
	return 0


## One trimesh instance -> {Vector3i(cell x, cell y, surface kind): PackedVector3Array of triangle corners}
## (surface kind only for roads, see SURF_KINDS; 0 otherwise)
func _faces_job(part: Array) -> Dictionary:
	var out := {}
	var xf: Transform3D = part[1]
	var split: bool = layout.meshes[part[0]].get("cat", "") == "road"
	var mats: Array = _arrays_mats.get(part[0], [])
	var si := -1
	for a in _arrays_cache.get(part[0], []):
		si += 1
		var sk := surface_kind(String(mats[si])) if split and si < mats.size() else 0
		var v: PackedVector3Array = xf * PackedVector3Array(a[Mesh.ARRAY_VERTEX])
		var has_idx: bool = a[Mesh.ARRAY_INDEX] != null
		var idx := PackedInt32Array()
		if has_idx:
			idx = a[Mesh.ARRAY_INDEX]
		var n: int = idx.size() if has_idx else v.size()
		for t in range(0, n - 2, 3):
			var p0: Vector3
			var p1: Vector3
			var p2: Vector3
			if has_idx:
				p0 = v[idx[t]]
				p1 = v[idx[t + 1]]
				p2 = v[idx[t + 2]]
			else:
				p0 = v[t]
				p1 = v[t + 1]
				p2 = v[t + 2]
			var k2 := _key((p0 + p1 + p2) / 3.0, COL_CELL)
			var k := Vector3i(k2.x, k2.y, sk)
			if not out.has(k):
				out[k] = PackedVector3Array()
			out[k].append(p0)        # in place on the stored array (a local copy would be COW-copied)
			out[k].append(p1)
			out[k].append(p2)
	return out


## Heights of a terrain chunk for HeightMapShape3D (Blender (x, y, z) -> Godot (x, z, -y): rows flip).
func _height_data(key: String) -> PackedFloat32Array:
	var c: Dictionary = _hf_meta.chunks[key]
	var n: int = _hf_meta.n
	var cc: int = _hf_meta.chunk_cells
	var cell: float = _hf_meta.cell
	var w := cc + 1
	var ix0 := int(c.ix) * cc
	var iy0 := int(c.iy) * cc
	var data := PackedFloat32Array()
	data.resize(w * w)
	for zi in w:
		var row := (iy0 + (w - 1 - zi)) * n + ix0      # Godot +z is Blender -y
		for xi in w:
			data[zi * w + xi] = _hf[row + xi] / cell
	return data


func _make_collision(item: Dictionary) -> Node:
	var t0 := Time.get_ticks_usec()
	var node := Node3D.new()
	match item.kind:
		"cell":
			node.name = "ColCell"
			if not item.shapes.is_empty():
				var sb := StaticBody3D.new()
				sb.name = "Shapes"
				for s in item.shapes:
					var cs := CollisionShape3D.new()
					if s[0] == "box":
						var b := BoxShape3D.new()
						b.size = s[1]
						cs.shape = b
					else:
						var c := CylinderShape3D.new()
						c.radius = 0.22
						c.height = s[1]
						cs.shape = c
					cs.transform = s[2]
					sb.add_child(cs)
				node.add_child(sb)
			for cat in item.faces:
				# a body per category, named "Col_<a mesh of it>" like the per-mesh bodies were (ray hits
				# tell road from the rest by it); own bodies: Jolt compounds of mesh shapes run out of
				# sub-shape ID bits
				var sb := StaticBody3D.new()
				sb.name = "Col_" + String(item.rep[cat])
				if String(cat).contains("/"):
					sb.set_meta("surface", String(cat).get_slice("/", 1))
				var shape := ConcavePolygonShape3D.new()
				shape.set_faces(item.faces[cat])
				var cs := CollisionShape3D.new()
				cs.shape = shape
				sb.add_child(cs)
				if String(cat).contains("/"):
					# surface bodies of one road mesh share its "Col_<mesh>" name: each gets its own
					# parent so the name stays unique (siblings with one name would be renamed)
					var holder := Node3D.new()
					holder.name = "S_" + String(cat).replace("/", "_")
					holder.add_child(sb)
					node.add_child(holder)
				else:
					node.add_child(sb)
		"height":
			node.name = "Height_" + item.key
			var sb := StaticBody3D.new()
			sb.name = "Col_" + item.key
			sb.add_child(_height_shape(item))
			node.add_child(sb)
	_col_root.add_child(node)
	var us := Time.get_ticks_usec() - t0
	if us > 6000:
		print("stream: collision %s %s %d us (%d shapes)" % [item.kind, item.get("key", ""), us, item.get("shapes", []).size()])
	return node


## Shape space is centred, 1 unit per sample, so the node is scaled by the cell size.
func _height_shape(item: Dictionary) -> CollisionShape3D:
	var c: Dictionary = _hf_meta.chunks[item.key]
	var cc: int = _hf_meta.chunk_cells
	var cell: float = _hf_meta.cell
	var w := cc + 1
	var hs := HeightMapShape3D.new()
	hs.map_width = w
	hs.map_depth = w
	hs.map_data = item.data if item.data != null else _height_data(item.key)
	var cs := CollisionShape3D.new()
	cs.shape = hs
	var ox: float = _hf_meta.ox + int(c.ix) * cc * cell
	var oy: float = _hf_meta.oy + int(c.iy) * cc * cell
	cs.transform = Transform3D(Basis.from_scale(Vector3.ONE * cell), Vector3(ox + cc * cell * 0.5, 0.0, -(oy + cc * cell * 0.5)))
	return cs


static func _rect_dist(r: Rect2, p: Vector2) -> float:
	var dx := maxf(maxf(r.position.x - p.x, 0.0), p.x - r.end.x)
	var dy := maxf(maxf(r.position.y - p.y, 0.0), p.y - r.end.y)
	return sqrt(dx * dx + dy * dy)


func _stream_collision(p: Vector2, sync: bool) -> void:
	var n := 0
	for item in _col_items:
		var d := _rect_dist(item.rect, p)
		if item.node == null and d < COL_RADIUS:
			if sync:
				item.node = _make_collision(item)
			elif not item.get("queued", false):
				item.queued = true
				_queue.append(func():
					item.queued = false
					if item.node == null:
						item.node = _make_collision(item))
		elif item.node != null and d > COL_RADIUS + 80.0:
			item.node.queue_free()
			item.node = null
		if item.node != null:
			n += item.get("shapes", []).size()
			n += 1 if item.kind == "height" else item.faces.size()
	stats.shapes = n


# ------------------------------------------------------------------ visual streaming
func _make_entry(k: Vector3i, e: Dictionary) -> void:
	var mmi := _new_mmi(e.name, e.mesh, e.buf, e.n)
	_dress(mmi, e.vis, e.shadows)
	_visuals.add_child(mmi)
	if e.region != null and _proxies.has(e.region):
		mmi.visibility_parent = mmi.get_path_to(_proxies[e.region])
	_cell_nodes[k].append(mmi)


## A unit streams in one MultiMesh per queue item, so a frame never builds a whole region.
func _stream_cells(p: Vector2, sync: bool) -> void:
	var n := 0
	for k in _cells:
		var c: Dictionary = _cells[k]
		var d: float = c.center.distance_to(p)
		var has: bool = _cell_nodes.has(k)
		if not has and d < c.r:
			_cell_nodes[k] = []
			c.gen = int(c.get("gen", 0)) + 1
			var gen: int = c.gen
			for e in c.entries:
				if sync:
					_make_entry(k, e)
				else:
					_queue.append(func():
						if _cell_nodes.has(k) and c.gen == gen:
							_make_entry(k, e))
		elif has and d > c.r + 60.0:
			for nd in _cell_nodes[k]:
				nd.queue_free()
			_cell_nodes.erase(k)
		if _cell_nodes.has(k):
			n += _cell_nodes[k].size()
	stats["cells_live"] = n


# ------------------------------------------------------------------ lights (streamed)
## The world export names its lights Light_<what>; the town uses LampLight / AlleyLight.
const LIGHT_KINDS := {"Light_lamp": "LampLight", "Light_alley": "AlleyLight", "Light_mast": "MastLight"}
## [fade begin, fade length] (m) per light kind. Street lamps are real lights only within ~60 m (their
## pools on the road); beyond that a glow sprite (_lamp_glows) stands in for the lamp in the rain.
const LIGHT_FADE := {"LampLight": [45.0, 15.0], "MastLight": [70.0, 30.0], "": [35.0, 15.0]}
const GLOW_SHADER := preload("res://scripts/lamp_glow.gdshader")


static func _light_fade(kind: String) -> Array:
	return LIGHT_FADE.get(kind, LIGHT_FADE[""])


func _index_lights() -> void:
	if _headless:
		return
	for d in layout.lights:
		d["kind"] = LIGHT_KINDS.get(String(d.get("kind", "")), d.get("kind", ""))
		var i := _lights.size()
		var p := Vector3(d.pos[0], d.pos[1], d.pos[2])
		var kind: String = d.get("kind", "")
		var f := _light_fade(kind)
		_lights.append({"d": d, "p": p, "r": f[0] + f[1] + LIGHT_MARGIN})
		var k := _key(p, CELL)
		if not _light_grid.has(k):
			_light_grid[k] = []
		_light_grid[k].append(i)
	stats.lights = _lights.size()
	_lamp_glows()


## Every street lamp as a camera-facing glow sprite (one MultiMesh, additive, no lighting): it fades in
## where the lamp's OmniLight fades out, so a street keeps its row of lamp halos to the horizon.
func _lamp_glows() -> void:
	var lamps := []
	for l in _lights:
		if l.d.get("kind", "") == "LampLight":
			lamps.append(l)
	if lamps.is_empty():
		return
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	var q := QuadMesh.new()
	q.size = Vector2(1, 1)
	mm.mesh = q
	mm.instance_count = lamps.size()
	var f: Array = _light_fade("LampLight")
	for i in lamps.size():
		var c: Array = lamps[i].d.color
		mm.set_instance_transform(i, Transform3D(Basis(), lamps[i].p))
		mm.set_instance_color(i, Color(c[0], c[1], c[2]))
	var mat := ShaderMaterial.new()
	mat.shader = GLOW_SHADER
	mat.set_shader_parameter("fade_in", Vector2(f[0], f[0] + f[1]))
	var mmi := MultiMeshInstance3D.new()
	mmi.name = "LampGlows"
	mmi.multimesh = mm
	mmi.material_override = mat
	mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	mmi.custom_aabb = AABB(Vector3(-1e5, -1e3, -1e5), Vector3(2e5, 2e3, 2e5))
	_lights_root.add_child(mmi)


func _make_light(i: int) -> Light3D:
	var d: Dictionary = _lights[i].d
	var c: Array = d.color
	var col := Color(c[0], c[1], c[2])
	var p: Vector3 = _lights[i].p
	var kind: String = d.get("kind", "")
	var l: Light3D
	var typ: String = d.get("type", "POINT")
	if typ == "AREA" or typ == "SPOT":
		var s := SpotLight3D.new()
		s.spot_range = 12.0
		s.spot_angle = 60.0
		s.light_energy = 4.0
		l = s
		_lights_root.add_child(l)
		var dr := Vector3(d.dir[0], d.dir[1], d.dir[2])
		l.global_position = p
		if dr.length() > 0.01:
			l.look_at(p + dr, Vector3.UP if absf(dr.normalized().y) < 0.99 else Vector3.RIGHT)
	else:
		var o := OmniLight3D.new()
		match kind:
			"LampLight":
				o.omni_range = 20.0
				o.light_energy = 3.2
				o.light_volumetric_fog_energy = 2.0
				o.light_size = 0.15
				o.omni_shadow_mode = OmniLight3D.SHADOW_DUAL_PARABOLOID
				lamp_lights.append(o)
			"MastLight":
				# port flood masts: big, high, few
				o.omni_range = 38.0
				o.light_energy = 4.0
				o.light_volumetric_fog_energy = 1.5
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
		_lights_root.add_child(l)
	l.light_color = col
	l.shadow_enabled = false
	l.distance_fade_enabled = true
	var fd := _light_fade(kind)
	l.distance_fade_begin = fd[0]
	l.distance_fade_length = fd[1]
	l.distance_fade_shadow = 40.0
	return l


func _stream_lights(p: Vector3) -> void:
	if _lights.is_empty():
		return
	var want := {}
	var reach := 100.0 + LIGHT_MARGIN + CELL
	var k0 := _key(p - Vector3(reach, 0, reach), CELL)
	var k1 := _key(p + Vector3(reach, 0, reach), CELL)
	for x in range(k0.x, k1.x + 1):
		for z in range(k0.y, k1.y + 1):
			for i in _light_grid.get(Vector2i(x, z), []):
				if _lights[i].p.distance_to(p) < _lights[i].r:
					want[i] = true
	for i in _light_nodes.keys():
		if not want.has(i) and _lights[i].p.distance_to(p) > _lights[i].r + 20.0:
			var l: Light3D = _light_nodes[i]
			lamp_lights.erase(l)
			l.queue_free()
			_light_nodes.erase(i)
	for i in want:
		if not _light_nodes.has(i):
			_light_nodes[i] = _make_light(i)
	stats["lights_live"] = _light_nodes.size()


# ------------------------------------------------------------------ streaming driver
## Synchronously stream everything needed around `p` (load, teleports).
func stream_now(p: Vector3) -> void:
	if not streaming:
		return
	_queue.clear()
	for k in _cell_nodes.keys():          # half-built units: rebuild them completely
		if _cell_nodes[k].size() < _cells[k].entries.size():
			for nd in _cell_nodes[k]:
				nd.queue_free()
			_cell_nodes.erase(k)
	for it in _col_items:
		it.erase("queued")
	_stream_cells(Vector2(p.x, p.z), true)
	_stream_lights(p)
	var cp: Vector3 = collision_focus.global_position if is_instance_valid(collision_focus) else p
	_stream_collision(Vector2(cp.x, cp.z), true)


## Collision around `p` right now, wherever the car is (the traffic places parked cars by ray casts
## all over the map). Cells made this way stay until the streamer drops them.
func ensure_collision(p: Vector3, radius := 20.0) -> void:
	var p2 := Vector2(p.x, p.z)
	for item in _col_items:
		if item.node == null and _rect_dist(item.rect, p2) < radius:
			item.node = _make_collision(item)


var _last_focus := Vector3.INF


## Teleports (reset, automation placing the car anywhere): collision must be there before the next
## physics step, so a big jump of the focus streams it in synchronously.
func _check_teleport() -> void:
	if not is_instance_valid(collision_focus):
		return
	var fp := collision_focus.global_position
	if _last_focus != Vector3.INF and fp.distance_to(_last_focus) > TELEPORT:
		_stream_collision(Vector2(fp.x, fp.z), true)
	_last_focus = fp


func _physics_process(_dt: float) -> void:
	if streaming and not layout.is_empty():
		_check_teleport()


func _process(delta: float) -> void:
	if not streaming or layout.is_empty():
		return
	_check_teleport()
	_stream_t -= delta
	if _stream_t <= 0.0:
		_stream_t = STREAM_EVERY
		var cam := get_viewport().get_camera_3d()
		var cp: Vector3 = cam.global_position if cam else Vector3.ZERO
		_stream_cells(Vector2(cp.x, cp.z), false)
		_stream_lights(cp)
		var fp: Vector3 = collision_focus.global_position if is_instance_valid(collision_focus) else cp
		_stream_collision(Vector2(fp.x, fp.z), false)
	var t0 := Time.get_ticks_usec()
	while not _queue.is_empty() and Time.get_ticks_usec() - t0 < STREAM_BUDGET_USEC:
		var f: Callable = _queue.pop_front()
		var t1 := Time.get_ticks_usec()
		f.call()
		if OS.is_stdout_verbose() or Time.get_ticks_usec() - t1 > 6000:
			print("stream: slow item %d us" % (Time.get_ticks_usec() - t1))


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
