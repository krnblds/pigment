extends Node
## Automated runs (see main.gd header): --autoshot=<dir>, --bench=<seconds>, --drive-test.

var main: Node3D
var _ap := false
var _frames: PackedFloat32Array = []
var _draws: PackedFloat32Array = []
var _prims: PackedFloat32Array = []
var _measure := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var a: Dictionary = main.args
	if a.has("drive-test"):
		_drive_test.call_deferred()
	elif a.has("autoshot"):
		_autoshot.call_deferred(String(a.autoshot))
	elif a.has("bench-matrix"):
		_bench_matrix.call_deferred()
	elif a.has("bench"):
		_bench_only.call_deferred(float(a.bench))


func _physics_process(delta: float) -> void:
	if _ap:
		main.autopilot_step(delta)


var _beat := 0


func _process(delta: float) -> void:
	var now := Time.get_ticks_msec()
	if now - _beat > 2000:
		_beat = now
		print("  [%.1f s] fps %d  frame %.1f ms" % [now / 1000.0, Engine.get_frames_per_second(), delta * 1000.0])
	if _measure:
		_frames.append(delta)
		_draws.append(RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME))
		_prims.append(RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME))


func _wait(t: float) -> void:
	await get_tree().create_timer(t, true, false, true).timeout


func _drive(on: bool) -> void:
	_ap = on
	if on:
		main.autopilot_start()
	else:
		main.car.autopilot = true


func _shot(dir: String, name: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var full := dir.path_join(name + ".png")
	if img.get_width() > 1600:
		img.resize(1600, int(1600.0 * img.get_height() / img.get_width()), Image.INTERPOLATE_LANCZOS)
	img.save_png(full)
	print("SHOT ", full)


func _video_setup() -> void:
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	Engine.max_fps = 0
	if DisplayServer.window_get_size() != Vector2i(1920, 1080):
		DisplayServer.window_set_size(Vector2i(1920, 1080))


func _measure_for(t: float) -> Dictionary:
	_frames.clear()
	_draws.clear()
	_prims.clear()
	_measure = true
	await _wait(t)
	_measure = false
	var ft := Array(_frames)
	ft.sort()
	var n := ft.size()
	var total := 0.0
	for f in ft:
		total += f
	var avg_ms := total / maxf(1, n) * 1000.0
	var p99: float = ft[int(n * 0.99)] if n > 0 else 0.0
	var draws := 0.0
	for d in _draws:
		draws += d
	var prims := 0.0
	for p in _prims:
		prims += p
	var r := {"frames": n, "avg_fps": snappedf(1000.0 / maxf(avg_ms, 0.001), 0.1), "avg_ms": snappedf(avg_ms, 0.01),
		"p1_low_fps": snappedf(1.0 / maxf(p99, 1e-6), 0.1), "min_fps": snappedf(1.0 / maxf(ft[n - 1] if n else 1.0, 1e-6), 0.1),
		"draw_calls": int(draws / maxf(1, n)), "primitives_m": snappedf(prims / maxf(1, n) / 1.0e6, 0.01),
		"vram_mb": int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0),
		"resolution": "%dx%d" % [get_viewport().get_visible_rect().size.x, get_viewport().get_visible_rect().size.y],
		"sdfgi": main.env.sdfgi_enabled}
	print("BENCH ", JSON.stringify(r))
	return r


func _quit() -> void:
	await _wait(0.2)
	get_tree().quit()


# ------------------------------------------------------------------ autoshot
func _autoshot(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	_video_setup()
	var cam = main.cam
	var perf := {"gpu": RenderingServer.get_video_adapter_name(), "driver": RenderingServer.get_video_adapter_api_version()}
	perf["town"] = main.town.stats
	await _wait(6.0)                                       # shaders, SDFGI and fog settle
	await _shot(dir, "01_spawn_chase")
	main.ap_speed = 17.0
	_drive(true)
	await _wait(7.0)
	await _shot(dir, "02_driving_chase")
	cam.mode = 2
	await _wait(2.5)
	await _shot(dir, "03_hood")
	cam.mode = 1
	cam.snap()
	await _wait(2.0)
	_ap = false
	main.car.input_throttle = -1.0
	main.car.input_steer = 0.0
	await _wait(0.5)
	await _shot(dir, "04_brake_lights")
	cam.mode = 0
	cam.snap()
	_drive(true)
	await _wait(2.0)
	perf["drive_sdfgi_on"] = await _measure_for(10.0)
	main.env.sdfgi_enabled = false
	perf["drive_sdfgi_off"] = await _measure_for(6.0)
	main.env.sdfgi_enabled = true
	_ap = false
	# overview from the Cycles "overview" camera position
	cam.manual = true
	main.rain.visible = false
	cam.fov = 50.0
	cam.global_position = Vector3(-95, 48, 70)
	cam.look_at(Vector3(10, 4, -15), Vector3.UP)
	await _wait(3.0)
	await _shot(dir, "05_overview")
	perf["overview"] = await _measure_for(3.0)
	# street level, looking into the crossroads J1
	main.rain.visible = true
	var j := _junction("J1")
	var p: Vector3 = _road_point_near(j, 32.0)
	cam.fov = 55.0
	cam.global_position = p + Vector3.UP * 1.7
	cam.look_at(j + Vector3.UP * 3.0, Vector3.UP)
	await _wait(3.0)
	await _shot(dir, "06_crossroads")
	var f := FileAccess.open(dir.path_join("perf.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(perf, "  "))
	f.close()
	print("PERF ", JSON.stringify(perf))
	_quit()


func _junction(nm: String) -> Vector3:
	for jd in main.town.layout.get("junctions", []):
		if jd.name == nm:
			return Vector3(jd.pos[0], jd.pos[1], jd.pos[2])
	return Vector3.ZERO


func _road_point_near(c: Vector3, dist: float) -> Vector3:
	var best := c + Vector3(dist, 0, 0)
	var bd := INF
	for q in main.town.road_points:
		var d := absf(q.distance_to(c) - dist)
		if d < bd:
			bd = d
			best = q
	return best


# ------------------------------------------------------------------ bench
func _bench_only(seconds: float) -> void:
	_video_setup()
	await _wait(5.0)
	main.ap_speed = 17.0
	_drive(true)
	await _wait(1.0)
	await _measure_for(seconds)
	_quit()


# ------------------------------------------------------------------ physics check (headless OK)
func _drive_test() -> void:
	var car: VehicleBody3D = main.car
	var res := {}
	print("drive test: settling")
	await _wait(2.0)
	var spawn_y: float = car.global_position.y
	res["rest_speed"] = snappedf(car.linear_velocity.length(), 0.01)
	res["rest_up"] = snappedf(car.global_basis.y.y, 0.001)
	res["wheels_contact"] = car.wheels.filter(func(w): return w.is_in_contact()).size()
	# straight-line acceleration on the road
	main.ap_speed = 45.0
	_drive(true)
	var t := 0.0
	var t100 := -1.0
	var t60 := -1.0
	var start: Vector3 = car.global_position
	var vmax := 0.0
	var min_up := 1.0
	var resets := 0
	var log := []
	while t < 40.0:
		await get_tree().physics_frame
		t += 1.0 / Engine.physics_ticks_per_second
		var v: float = car.forward_speed()
		vmax = maxf(vmax, v)
		if t60 < 0.0 and v * 3.6 >= 60.0:
			t60 = t
		if t100 < 0.0 and v * 3.6 >= 100.0:
			t100 = t
		min_up = minf(min_up, car.global_basis.y.y)
		if car.needs_reset():
			resets += 1
		if int(t * 120) % 240 == 0:
			print("  t=%.0f v=%.1f km/h up=%.2f pos=%s fps=%d" % [t, v * 3.6, car.global_basis.y.y, car.global_position.snappedf(0.1), Engine.get_frames_per_second()])
		if t > 12.0:
			main.ap_speed = 22.0
	res["t_0_100"] = snappedf(t100, 0.01)
	res["t_0_60"] = snappedf(t60, 0.01)
	res["vmax_kmh"] = snappedf(vmax * 3.6, 0.1)
	res["min_up"] = snappedf(min_up, 0.01)
	res["distance"] = snappedf(car.global_position.distance_to(start), 0.1)
	res["auto_resets"] = resets
	# braking from speed
	_ap = false
	var v0: float = car.forward_speed()
	car.input_throttle = -1.0
	car.input_steer = 0.0
	var bt := 0.0
	var bd0: Vector3 = car.global_position
	while car.forward_speed() > 0.5 and bt < 10.0:
		await get_tree().physics_frame
		bt += 1.0 / Engine.physics_ticks_per_second
	res["brake_from_kmh"] = snappedf(v0 * 3.6, 0.1)
	res["brake_time"] = snappedf(bt, 0.01)
	res["brake_dist"] = snappedf(car.global_position.distance_to(bd0), 0.1)
	# reset
	car.global_position += Vector3(30, 5, 0)
	main.reset_car()
	await _wait(1.5)
	res["after_reset_up"] = snappedf(car.global_basis.y.y, 0.001)
	res["after_reset_speed"] = snappedf(car.linear_velocity.length(), 0.01)
	for l in log:
		print("  ", l)
	print("DRIVETEST ", JSON.stringify(res))
	_quit()


# ------------------------------------------------------------------ what costs what (static view)
func _bench_matrix() -> void:
	_video_setup()
	await _wait(6.0)
	var env: Environment = main.env
	var moon: DirectionalLight3D = main.get_node("Moon")
	var vis: Node3D = main.town.get_node("Visuals")
	var res := {}
	res["base"] = await _measure_for(3.0)
	moon.shadow_enabled = false
	res["no_moon_shadow"] = await _measure_for(3.0)
	main.set_process(false)
	for l in main.town.lamp_lights:
		l.shadow_enabled = false
	res["+no_lamp_shadows"] = await _measure_for(3.0)
	env.ssil_enabled = false
	res["+no_ssil"] = await _measure_for(3.0)
	env.volumetric_fog_enabled = false
	res["+no_volfog"] = await _measure_for(3.0)
	env.ssr_enabled = false
	env.ssao_enabled = false
	res["+no_ssr_ssao"] = await _measure_for(3.0)
	main.rain.visible = false
	res["+no_rain"] = await _measure_for(3.0)
	for c in vis.get_children():
		if c.name.begins_with("building"):
			c.visible = false
	res["+no_buildings"] = await _measure_for(3.0)
	print("MATRIX ", JSON.stringify(res, "  "))
	_quit()
