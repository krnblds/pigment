extends Node
## Live link for the city build (tools/city, `python -m tools.city watch`): hot-swaps rebuilt assets
## into the running game without a restart. Autoload; idle unless the game runs with `-- --live`.
##
## The build appends events to res://assets/.live/events.jsonl (one JSON object per line, each with a
## "seq"); this node tails the file, applies each event in place and appends an acknowledgement
## {"seq", "ok", "ms", "type", ...} to acks.jsonl. A heartbeat in .live/alive tells the build it is here.
## Files are read straight from disk (Image.load_from_file, GLTFDocument), so a swap does not wait for
## Godot's importer; the build re-imports afterwards for the next normal start.
##
## Events:
##   texture  {map, folder}     packed Pigment texture set -> every material using that folder
##   image    {map, image}      an image material's texture (road tiles, billboards ...)
##   material {map, folder}     emissive scale / opacity re-read from the layout json
##   mesh     {map, key}        a mesh glb -> MultiMesh cells (live and not yet streamed), single meshes,
##                              and the merged region meshes that contain it (re-merged)
##   layout   {map, keys}       many meshes at once
##   camera   {pos, look, fov}  park a camera (proof shots); {"type": "camera", "off": true} gives it back
##   screenshot {path, frames}  save the viewport after `frames` frames (default 8)
##   ping
## Collision and far proxies are not rebuilt by a swap (they come from the same bounds; a restart rebuilds them).

const DIR := "res://assets/.live/"
const POLL := 0.1

var enabled := false
var _events_path := ""
var _acks_path := ""
var _offset := 0
var _t := 0.0
var _beat := 0.0
var _busy := false
var _cam: Camera3D
var _prev_cam: Camera3D
var stats := {"events": 0, "textures": 0, "meshes": 0, "merged": 0}


func _ready() -> void:
	enabled = "--live" in OS.get_cmdline_user_args()
	set_process(enabled)
	if not enabled:
		return
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(DIR))
	_events_path = ProjectSettings.globalize_path(DIR + "events.jsonl")
	_acks_path = ProjectSettings.globalize_path(DIR + "acks.jsonl")
	# only events sent from now on: older ones were for an earlier session
	if FileAccess.file_exists(_events_path):
		var f := FileAccess.open(_events_path, FileAccess.READ)
		_offset = f.get_length()
	_heartbeat()
	print("live_link: listening on %s" % _events_path)


func _heartbeat() -> void:
	var f := FileAccess.open(ProjectSettings.globalize_path(DIR + "alive"), FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"pid": OS.get_process_id(), "t": Time.get_unix_time_from_system(), "stats": stats}))


func _process(delta: float) -> void:
	_beat += delta
	if _beat > 1.0:
		_beat = 0.0
		_heartbeat()
	_t += delta
	if _t < POLL or _busy:
		return
	_t = 0.0
	if not FileAccess.file_exists(_events_path):
		return
	var f := FileAccess.open(_events_path, FileAccess.READ)
	if f == null or f.get_length() <= _offset:
		return
	f.seek(_offset)
	var text := f.get_buffer(f.get_length() - _offset).get_string_from_utf8()
	var last_nl := text.rfind("\n")
	if last_nl < 0:
		return
	_offset += text.substr(0, last_nl + 1).to_utf8_buffer().size()
	var events := []
	for line in text.substr(0, last_nl).split("\n", false):
		var e = JSON.parse_string(line)
		if e is Dictionary:
			events.append(e)
	if not events.is_empty():
		_run(events)


func _run(events: Array) -> void:
	_busy = true
	for e in events:
		var t0 := Time.get_ticks_usec()
		var ack := {"seq": e.get("seq", -1), "type": e.get("type", "?"), "ok": true}
		var r = await _apply(e)
		if r is Dictionary:
			ack.merge(r, true)
		ack["ms"] = (Time.get_ticks_usec() - t0) / 1000.0
		stats.events += 1
		_ack(ack)
		print("live_link: %s" % JSON.stringify(ack))
	_busy = false


func _ack(a: Dictionary) -> void:
	var f: FileAccess
	if FileAccess.file_exists(_acks_path):
		f = FileAccess.open(_acks_path, FileAccess.READ_WRITE)
		f.seek_end()
	else:
		f = FileAccess.open(_acks_path, FileAccess.WRITE)
	if f:
		f.store_line(JSON.stringify(a))


func _town() -> Node:
	var s := get_tree().current_scene
	if s == null:
		return null
	var t = s.get("town")
	return t if t is Node and t.get("layout") is Dictionary and not t.layout.is_empty() else null


func _apply(e: Dictionary):
	match String(e.get("type", "")):
		"ping":
			return {"ok": true, "town": _town() != null}
		"camera":
			return _camera(e)
		"screenshot":
			return await _screenshot(e)
	var town := _town()
	if town == null:
		return {"ok": false, "error": "no town loaded"}
	if e.has("map") and town.dir != "res://assets/%s/" % e.map:
		return {"ok": true, "skipped": "other map"}
	match String(e.type):
		"texture":
			return _texture(town, String(e.folder))
		"image":
			return _image(town, String(e.image))
		"material":
			return _material(town, String(e.folder))
		"mesh":
			return _meshes(town, [String(e.key)])
		"layout":
			return _meshes(town, e.get("keys", []))
	return {"ok": false, "error": "unknown event"}


# ------------------------------------------------------------------ textures
func _load_tex(res_path: String, mipmaps := true) -> Texture2D:
	var abs := ProjectSettings.globalize_path(res_path)
	if not FileAccess.file_exists(abs):
		return null
	var img := Image.load_from_file(abs)
	if img == null or img.is_empty():
		return null
	if mipmaps:
		img.generate_mipmaps()
	return ImageTexture.create_from_image(img)


func _layout_file(town: Node) -> Dictionary:
	var p: String = town.dir + "%s_layout.json" % String(town.dir).trim_suffix("/").get_file()
	var d = JSON.parse_string(FileAccess.get_file_as_string(p))
	return d if d is Dictionary else {}


func _texture(town: Node, folder: String) -> Dictionary:
	var base: String = town.dir + "textures/" + folder + "/"
	var tex := {}
	for nm in ["albedo", "orm", "normal", "emission"]:
		var t := _load_tex(base + nm + ".png")
		tex[nm] = t
		town._tex_cache[base + nm + ".png"] = t
	var n := 0
	for mname in town._mat_cache:
		var d: Dictionary = town.layout.materials.get(mname, {})
		if d.get("type", "") != "pigment" or d.get("folder", "") != folder:
			continue
		var m = town._mat_cache[mname]
		if m is ShaderMaterial:      # interior-mapped building (town_loader._interior_material)
			for k in ["albedo", "orm", "normal", "emission"]:
				if tex[k]:
					m.set_shader_parameter(k + "_tex", tex[k])
			m.set_shader_parameter("use_emission", tex.emission != null)
			n += 1
			continue
		if not (m is ORMMaterial3D):
			continue
		if tex.albedo:
			m.albedo_texture = tex.albedo
		if tex.orm:
			m.orm_texture = tex.orm
		if tex.normal:
			m.normal_enabled = true
			m.normal_texture = tex.normal
		if tex.emission:
			m.emission_enabled = true
			m.emission_texture = tex.emission
		else:
			m.emission_enabled = false
		n += 1
	stats.textures += 1
	_material(town, folder)
	return {"ok": true, "materials": n, "folder": folder}


func _image(town: Node, image: String) -> Dictionary:
	var t := _load_tex(town.dir + image)
	if t == null:
		return {"ok": false, "error": "cannot read " + image}
	town._tex_cache[town.dir + image] = t
	var n := 0
	for mname in town._mat_cache:
		var d: Dictionary = town.layout.materials.get(mname, {})
		if d.get("type", "") == "image" and d.get("image", "") == image:
			var m = town._mat_cache[mname]
			if m is ShaderMaterial:  # interior-mapped tower facade
				m.set_shader_parameter("albedo_tex", t)
				n += 1
				continue
			m.albedo_texture = t
			if m.emission_enabled:
				m.emission_texture = t
			n += 1
	return {"ok": true, "materials": n, "image": image}


func _material(town: Node, folder: String) -> Dictionary:
	var lay := _layout_file(town)
	var n := 0
	for mname in lay.get("materials", {}):
		var d: Dictionary = lay.materials[mname]
		if d.get("type", "") != "pigment" or d.get("folder", "") != folder:
			continue
		town.layout.materials[mname] = d
		if town._mat_cache.has(mname):
			var m = town._mat_cache[mname]
			if m is ShaderMaterial:  # interior-mapped building
				m.set_shader_parameter("emission_energy", float(d.get("emissive_scale", 1.0)) * 1.3)
				m.set_shader_parameter("alpha_scissor", 0.15 if d.get("opacity", false) else 0.0)
				n += 1
				continue
			m.emission_energy_multiplier = float(d.get("emissive_scale", 1.0)) * 1.3
			if d.get("opacity", false):
				m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
				m.alpha_scissor_threshold = 0.15
			else:
				m.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED
			n += 1
	return {"ok": true, "materials": n}


# ------------------------------------------------------------------ meshes
func _read_glb_mesh(path: String) -> ArrayMesh:
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(ProjectSettings.globalize_path(path), st) != OK or st.meshes.is_empty():
		return null
	var im: ImporterMesh = st.meshes[0].mesh
	return im.get_mesh()


## A copy of `src` (fresh geometry) wearing `old`'s materials, matched by surface index or name.
func _dress_like(src: ArrayMesh, old: Mesh) -> ArrayMesh:
	var out := ArrayMesh.new()
	var by_name := {}
	if old:
		for i in old.get_surface_count():
			var m := old.surface_get_material(i)
			if m:
				by_name[m.resource_name] = m
	for i in src.get_surface_count():
		out.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, src.surface_get_arrays(i))
		var nm := ""
		var sm := src.surface_get_material(i)
		if sm:
			nm = sm.resource_name
		var mat: Material = null
		if old and i < old.get_surface_count() and old.get_surface_count() == src.get_surface_count():
			mat = old.surface_get_material(i)
		if mat == null:
			mat = by_name.get(nm, null)
		out.surface_set_material(i, mat)
	return out


func _meshes(town: Node, keys: Array) -> Dictionary:
	var lay_meshes: Dictionary = town.layout.meshes
	var fresh := {}
	for k in keys:
		if lay_meshes.has(k):
			var m := _read_glb_mesh(town.dir + lay_meshes[k].file)
			if m:
				fresh[k] = m
	if fresh.is_empty():
		return {"ok": false, "error": "no readable glb for %s" % str(keys)}
	# meshes drawn as themselves: every user of an old mesh made from these keys
	var replace := {}            # old Mesh -> new ArrayMesh
	var olds := {}
	for k in fresh:
		var old = town._mesh_cache.get(k, null)
		if old:
			olds[old] = k
	var users := []
	_collect(town._visuals, users)
	var n := 0
	for gi in users:
		var mesh: Mesh = gi.multimesh.mesh if gi is MultiMeshInstance3D else gi.mesh
		var k = _key_of(gi.name, fresh, olds, mesh)
		if k == null:
			continue
		if not replace.has(mesh):
			replace[mesh] = _dress_like(fresh[k], mesh)
		if gi is MultiMeshInstance3D:
			gi.multimesh.mesh = replace[mesh]
		else:
			gi.mesh = replace[mesh]
		n += 1
	# cells that are not streamed in yet
	for ck in town._cells:
		for e in town._cells[ck].entries:
			if replace.has(e.mesh):
				e.mesh = replace[e.mesh]
			elif olds.has(e.mesh):
				replace[e.mesh] = _dress_like(fresh[olds[e.mesh]], e.mesh)
				e.mesh = replace[e.mesh]
	for k in fresh:
		var old = town._mesh_cache.get(k, null)
		if old and replace.has(old):
			town._mesh_cache[k] = replace[old]
	stats.meshes += fresh.size()
	var merged := _remerge(town, fresh.keys())
	return {"ok": true, "keys": fresh.size(), "instances": n, "merged_regions": merged}


func _collect(n: Node, out: Array) -> void:
	for c in n.get_children():
		if c is MultiMeshInstance3D or c is MeshInstance3D:
			out.append(c)
		_collect(c, out)


func _key_of(node_name: String, fresh: Dictionary, olds: Dictionary, mesh: Mesh):
	if mesh and olds.has(mesh):
		return olds[mesh]
	# dressed copies (other material remaps) are not cached: match the names town_loader gives its nodes:
	# "<key>" (single), "<key>_r<x>_<y>" (region), "<key>_<x>_<y>" (cell)
	for k in fresh:
		if node_name == k:
			return k
		var re := RegEx.new()
		re.compile("^" + k + "_(r)?-?[0-9]+_-?[0-9]+$")
		if re.search(node_name):
			return k
	return null


## Rebuild the merged region meshes ("merge" policy) that contain any of `keys`, exactly as
## town_loader._build_groups does, and swap them in.
func _remerge(town: Node, keys: Array) -> int:
	var want := {}
	for k in keys:
		want[k] = true
	var jobs := {}
	var hit := {}
	var groups: Array = town._group_instances()
	for g in groups:
		var info: Dictionary = town.layout.meshes[g.mesh]
		if town._policy(info, g.xf.size()) != "merge":
			continue
		var cat: String = info.get("cat", "other")
		var vis_end: float = town.VIS_END.get(cat, 0.0)
		var shadows: bool = town.CAST_SHADOWS.get(cat, true)
		var a: Array = info.aabb
		var local_c := (Vector3(a[0][0], a[0][1], a[0][2]) + Vector3(a[1][0], a[1][1], a[1][2])) * 0.5
		for x in g.xf:
			var t: Transform3D = x
			var rk: Vector2i = town._key(t * local_c, town.REGION)
			var jk := "%d,%d,%d,%d" % [rk.x, rk.y, int(vis_end), int(shadows)]
			if not jobs.has(jk):
				jobs[jk] = {"key": rk, "vis": vis_end, "shadows": shadows, "parts": [], "groups": []}
			jobs[jk].parts.append([g.mesh, t, g.remap])
			if want.has(g.mesh):
				hit[jk] = true
	if hit.is_empty():
		return 0
	var akeys := {}
	for jk in hit:
		for p in jobs[jk].parts:
			akeys[p[0]] = true
	town._load_arrays(akeys)
	var root: Node = town._visuals.get_node_or_null("Merged")
	var n := 0
	for jk in hit:
		var job: Dictionary = jobs[jk]
		var parts := []
		for p in job.parts:
			parts.append([p[0], p[1], town._surface_materials(p[0], p[2])])
		var mesh: ArrayMesh = town._merge_job({"key": job.key, "vis": job.vis, "shadows": job.shadows, "parts": parts})
		if mesh == null:
			continue
		for s in mesh.get_surface_count():
			mesh.surface_set_material(s, town.material(mesh.surface_get_name(s)))
		var nm := "merged_%d_%d_%d" % [job.key.x, job.key.y, int(job.vis)]
		var mi: MeshInstance3D = root.get_node_or_null(nm) if root else null
		if mi:
			mi.mesh = mesh
			n += 1
	town._arrays_cache.clear()
	town._arrays_mats.clear()
	stats.merged += n
	return n


# ------------------------------------------------------------------ proof helpers
func _camera(e: Dictionary) -> Dictionary:
	var vp := get_viewport()
	if e.get("off", false):
		if _cam:
			_cam.current = false
		if _prev_cam:
			_prev_cam.current = true
		return {"ok": true}
	if _cam == null:
		_cam = Camera3D.new()
		_cam.name = "LiveCam"
		_cam.far = 3500.0
		_cam.near = 0.1
		get_tree().current_scene.add_child(_cam)
	_prev_cam = vp.get_camera_3d() if vp.get_camera_3d() != _cam else _prev_cam
	var p: Array = e.pos
	var l: Array = e.look
	_cam.global_position = Vector3(p[0], p[1], p[2])
	_cam.look_at(Vector3(l[0], l[1], l[2]), Vector3.UP)
	_cam.fov = float(e.get("fov", 60.0))
	_cam.current = true
	var town := _town()
	if town and town.has_method("stream_now"):
		town.stream_now(_cam.global_position)
	return {"ok": true}


func _screenshot(e: Dictionary) -> Dictionary:
	for i in int(e.get("frames", 8)):
		await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var path := String(e.path)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var err := img.save_png(path)
	return {"ok": err == OK, "path": path, "size": [img.get_width(), img.get_height()]}
