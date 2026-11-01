extends Node3D
## `--foliage-demo=<dir>`: Pigment's foliage proof in the game. Loads the
## send_to_blender folders written by tools/foliage_demo.py (<dir>/building_a,
## <dir>/street_segment: textures, mesh and foliage) into the game's night /
## rain scene, frames the ivy wall from the street, saves a screenshot
## (`--foliage-shot=<png>`, default <dir>/godot_foliage.png) and quits.
##
##   godot --path game -- --foliage-demo=C:/repo/target/foliage --no-town --no-traffic

const FoliageLoader := preload("res://scripts/foliage_loader.gd")

var main: Node3D
var dir := ""
var shot := ""
var _t := 0.0
var _done := false
var cam: Camera3D


func _ready() -> void:
	dir = String(main.args.get("foliage-demo", ""))
	shot = String(main.args.get("foliage-shot", dir.path_join("godot_foliage.png")))
	_asset("building_a", Transform3D.IDENTITY)
	# the street along the building's east (+X) wall, as in the Blender proof
	for z in [0.0, -20.0, 20.0]:
		_asset("street_segment", Transform3D(Basis(Vector3.UP, deg_to_rad(90.0)), Vector3(4.39 + 7.0, 0.0, z)))
	_lights()
	var g := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(300, 300)
	g.mesh = pm
	var gm := StandardMaterial3D.new()
	gm.albedo_color = Color(0.012, 0.012, 0.014)
	gm.roughness = 0.12
	g.material_override = gm
	g.position = Vector3(0, -0.02, 0)
	add_child(g)
	cam = Camera3D.new()
	cam.fov = 62.0
	cam.near = 0.05
	add_child(cam)
	cam.look_at_from_position(Vector3(16.5, 1.65, 10.5), Vector3(4.4, 4.6, -0.5))
	cam.current = true
	# park the car out of the way
	if main.car:
		main.car.freeze = true
		main.car.global_position = Vector3(300, 2, 300)


func _asset(name: String, xf: Transform3D) -> void:
	var folder := dir.path_join(name)
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(folder.path_join(name + ".glb"), st) != OK or st.meshes.is_empty():
		push_error("foliage demo: no %s.glb in %s" % [name, folder])
		return
	var mi := MeshInstance3D.new()
	mi.name = name
	mi.mesh = (st.meshes[0].mesh as ImporterMesh).get_mesh()
	mi.material_override = _pigment_material(folder, name)
	mi.transform = xf
	add_child(mi)
	var inst := folder.path_join(name + "_foliage_instances.json")
	if FileAccess.file_exists(inst):
		var f := FoliageLoader.build(inst)
		f.transform = xf
		add_child(f)


## The Pigment "separate" maps as a StandardMaterial3D (glass stays solid, as in the town).
func _pigment_material(folder: String, name: String) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	var t := func(s: String) -> Texture2D: return FoliageLoader.load_texture(folder.path_join("%s_%s.png" % [name, s]))
	m.albedo_texture = t.call("BaseColor")
	m.normal_enabled = true
	m.normal_texture = t.call("Normal_OpenGL")
	m.roughness_texture = t.call("Roughness")
	m.roughness_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_RED
	m.metallic = 1.0
	m.metallic_texture = t.call("Metallic")
	m.metallic_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_RED
	m.ao_enabled = true
	m.ao_texture = t.call("AO")
	var e: Texture2D = t.call("Emissive")
	if e:
		var scale := 1.0
		var f := FileAccess.open(folder.path_join("material.json"), FileAccess.READ)
		if f:
			var j = JSON.parse_string(f.get_as_text())
			if typeof(j) == TYPE_DICTIONARY:
				scale = float(j.get("materials", {}).get(name, {}).get("emissive_scale", 1.0))
		m.emission_enabled = true
		m.emission_texture = e
		m.emission_energy_multiplier = scale * 1.3
	return m


func _lights() -> void:
	# sodium lamps over the far sidewalk, neon spill from across the street
	for p in [Vector3(15.5, 6.5, 3.0), Vector3(15.5, 6.5, -9.0)]:
		var s := SpotLight3D.new()
		s.light_color = Color(1.0, 0.62, 0.32)
		s.light_energy = 14.0
		s.spot_range = 22.0
		s.spot_angle = 55.0
		s.shadow_enabled = true
		add_child(s)
		s.look_at_from_position(p, Vector3(6.0, 0.0, p.z * 0.9))
	for d in [[Vector3(19, 3.5, -2), Color(1.0, 0.18, 0.55)], [Vector3(18, 5, 8), Color(0.15, 0.75, 1.0)]]:
		var o := OmniLight3D.new()
		o.position = d[0]
		o.light_color = d[1]
		o.light_energy = 6.0
		o.omni_range = 20.0
		add_child(o)
	var low := OmniLight3D.new()
	low.position = Vector3(5.2, 1.2, -1.0)
	low.light_color = Color(1.0, 0.7, 0.4)
	low.light_energy = 1.5
	low.omni_range = 4.0
	add_child(low)


func _process(delta: float) -> void:
	if _done:
		return
	_t += delta
	# let SDFGI, SSR and the rain settle
	if _t > 4.0 and Engine.get_frames_drawn() > 120:
		_done = true
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		img.save_png(shot)
		print("foliage demo: saved ", shot)
		get_tree().quit()
