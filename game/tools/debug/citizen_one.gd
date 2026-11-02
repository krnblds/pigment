extends SceneTree
## Debug: one citizen big, rest pose (tree off) and walking.  -- <out_dir> <id>
const CitizenLib := preload("res://scripts/npc/character/citizen_library.gd")
func _initialize() -> void:
	_run.call_deferred()
func _shot(p: String) -> void:
	for f in 4:
		await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png(p)
func _run() -> void:
	var a := OS.get_cmdline_user_args()
	var out: String = a[0]
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
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.fov = 30
	cam.position = Vector3(0, 1.0, 5.0)
	var x := -1.2
	for id in a.slice(1):
		var c = CitizenLib.spawn(id, {"ragdoll": false})
		root.add_child(c)
		c.position.x = x
		x += 1.2
		c.tree.active = false
		c.skel.reset_bone_poses()
	await _shot(out.path_join("one_rest.png"))
	for c in root.get_children():
		if c.has_method("set_speed"):
			c.tree.active = true
			c.set_speed(0.0)
	for f in 30:
		await process_frame
	await _shot(out.path_join("one_idle.png"))
	quit()
