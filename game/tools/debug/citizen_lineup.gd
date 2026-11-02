extends SceneTree
## Debug: citizens walking in place in rows of 9, front-lit, from the front and a three-quarter view,
## at LOD0 and LOD1.   godot --path game --script res://tools/debug/citizen_lineup.gd -- <out_dir>
const CitizenLib := preload("res://scripts/npc/character/citizen_library.gd")

func _initialize() -> void:
	_run.call_deferred()

func _shot(path: String) -> void:
	for f in 4:
		await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png(path)

func _run() -> void:
	var out: String = OS.get_cmdline_user_args()[0] if OS.get_cmdline_user_args().size() > 0 else "user://lineup"
	DirAccess.make_dir_recursive_absolute(out)
	var root := Node3D.new()
	get_root().add_child(root)
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.25, 0.26, 0.3)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.7, 0.7, 0.75)
	root.add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-35, 20, 0)
	root.add_child(sun)
	var ids := CitizenLib.ids(true)
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.fov = 30.0
	var umb := OS.get_cmdline_user_args().size() > 1 and OS.get_cmdline_user_args()[1] == "umbrella"
	for page in range(0, ids.size(), 9):
		var cs := []
		for i in range(page, mini(page + 9, ids.size())):
			var c = CitizenLib.spawn(ids[i], {"ragdoll": false, "umbrella": "black" if umb else ""})
			root.add_child(c)
			c.position = Vector3((i - page) * 1.3, 0, 0)
			c.set_speed(1.4)
			cs.append(c)
		for f in 40:
			await process_frame
		var tag := "%02d" % (page / 9)
		cam.position = Vector3(5.2, 1.2, 15.0)
		cam.look_at(Vector3(5.2, 0.95, 0))
		await _shot(out.path_join("front_%s.png" % tag))
		cam.position = Vector3(12.0, 1.6, 9.0)
		cam.look_at(Vector3(5.2, 0.9, 0))
		await _shot(out.path_join("three_q_%s.png" % tag))
		for c in cs:
			c.set_lod_distances(0.0)
		cam.position = Vector3(5.2, 1.2, 15.0)
		cam.look_at(Vector3(5.2, 0.95, 0))
		await _shot(out.path_join("lod1_%s.png" % tag))
		for c in cs:
			c.queue_free()
	quit()
