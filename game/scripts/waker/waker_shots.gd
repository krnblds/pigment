extends RefCounted
## --waker-shots=<dir>: windowed proof screenshots on the real streets at night in the rain.
##   waker_exit.png      getting out of the Hoshikawa cruiser (light bar on), the camera handing over
##   waker_aim.png       on foot, aiming the service pistol down a wet street
##   waker_dispatch.png  in the cruiser: MERIDIAN dispatch panel, signal area marker, Resonance scan
##   waker_echo.png      a memory echo: the parent's market search replayed in cyan ghosts
##   waker_firefight.png a soldier sleeper in cover firing, the Waker answering with the taser
## Also writes perf.json (frame time with and without combat).

var ct
var t
var dir := ""


func run(case_tests) -> void:
	ct = case_tests
	t = ct.t
	dir = ct.shots_dir
	DirAccess.make_dir_recursive_absolute(dir)
	var main = t.main
	var cm = ct.cm
	var town = main.town
	var sp: Transform3D = town.spawn_transform() if town and town.layout else Transform3D(Basis(), Vector3(0, 1, 0))
	main.car.place(sp)
	main.stream_now(sp.origin)
	if t.player.state != "car":
		t.player.state = "car"
		t.player.car = main.car
		t.player._set_present(false)
		t.waker._on_entered(main.car)
	t.player.armour = 1.0e6
	await _settle(3.0)
	# 1. dispatch HUD in the cruiser (a case 200 m off, scanning)
	var fwd: Vector3 = main.car.global_basis.z
	cm.dispatch("parent", _road_ahead(sp.origin, fwd, 220.0))
	cm.bot = {"scan": true}
	main.car.toggle_lightbar()
	await _settle(2.5)
	await _shot("waker_dispatch.png")
	cm.bot = {}
	# 2. getting out (mid hand-over)
	t.waker.toggle_car()
	await _frames(14)
	await _shot("waker_exit.png")
	await _settle(1.5)
	main.car.toggle_lightbar()
	# 3. aiming down the street
	t.player.weapons.select("service_pistol")
	var p: Vector3 = t.player.global_position
	var ahead: Vector3 = p + fwd * 30.0 + Vector3.UP * 1.3
	t.player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": ahead, "yaw": t.face(fwd)}
	t.waker.ots.yaw = t.face(fwd)
	t.waker.ots.pitch = -0.04
	await _settle(1.5)
	await _shot("waker_aim.png")
	# 4. the memory echo around the sleeper
	var home: Vector3 = cm.active.home
	t.player.bot = {}
	t.player.weapons.holster()
	main.stream_now(home)
	var look_from: Vector3 = home - fwd * 9.0
	t.player.place(_ground(look_from), t.face(fwd))
	t.waker.ots.yaw = t.face(home - look_from)
	t.waker.ots.pitch = -0.08
	await _settle(4.0)
	await _shot("waker_echo.png")
	# 5. firefight: soldier sleeper 14 m away
	var f0 := Time.get_ticks_usec()
	var fr0 := Engine.get_frames_drawn()
	await _settle(2.0)
	var calm_ms := float(Time.get_ticks_usec() - f0) / 1000.0 / maxf(1.0, Engine.get_frames_drawn() - fr0)
	var at: Vector3 = t.player.global_position + fwd * 14.0
	cm.dispatch("soldier", at)
	await _settle(1.5)
	var s: Node3D = cm.active.sleepers[0]
	t.waker.combat.noise(t.player.global_position, 60.0)
	t.player.weapons.select("taser")
	t.waker.ots.yaw = t.face(at - t.player.global_position)
	await _settle(2.5)
	var cost := 0.0
	var n := 0
	f0 = Time.get_ticks_usec()
	fr0 = Engine.get_frames_drawn()
	for i in 180:
		var aimp: Vector3 = s.global_position + Vector3.UP * 1.1
		t.player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aimp, "fire": i % 40 == 0, "yaw": t.face(aimp - t.player.global_position)}
		await t.get_tree().process_frame
		cost += t.waker.combat_cost_us()
		n += 1
		if i == 150:
			await _shot("waker_firefight.png")
	var fight_ms := float(Time.get_ticks_usec() - f0) / 1000.0 / maxf(1.0, Engine.get_frames_drawn() - fr0)
	t.player.bot = {}
	var perf := {"frame_ms_walking": calm_ms, "frame_ms_firefight": fight_ms, "waker_combat_us_per_frame": cost / n,
		"fps_firefight": 1000.0 / maxf(fight_ms, 0.01), "breakdown": t.waker.cost_breakdown()}
	var f := FileAccess.open(dir.path_join("perf.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(perf, "  "))
	t.notes.append("shots perf: %s" % JSON.stringify(perf))
	t.check(true, "screenshots written to " + dir)


func _road_ahead(from: Vector3, fwd: Vector3, d: float) -> Vector3:
	var town = t.main.town
	if town and town.layout:
		var r: Array = town.nearest_road(from + fwd * d)
		return (r[0] as Vector3) + Vector3.UP.cross(r[1]).normalized() * 5.0
	return from + fwd * d


func _ground(p: Vector3) -> Vector3:
	t.main.town.ensure_collision(p, 25.0)
	var q := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 30.0, p + Vector3.DOWN * 30.0, 1)
	var h: Dictionary = t.main.get_world_3d().direct_space_state.intersect_ray(q)
	return (h.position as Vector3) + Vector3.UP * 0.05 if h else p


func _frames(n: int) -> void:
	for i in n:
		await t.get_tree().process_frame


func _settle(s: float) -> void:
	var end := Time.get_ticks_msec() + int(s * 1000.0)
	while Time.get_ticks_msec() < end:
		await t.get_tree().process_frame


func _shot(name_: String) -> void:
	await RenderingServer.frame_post_draw
	var img: Image = t.get_viewport().get_texture().get_image()
	img.resize(1600, 900, Image.INTERPOLATE_LANCZOS)
	img.save_png(dir.path_join(name_))
	print("shot ", name_)
