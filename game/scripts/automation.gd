extends Node
## Automated runs (see main.gd header): --autoshot=<dir>, --bench=<seconds>, --drive-test.

var main: Node3D
var _ap := false
var _frames: PackedFloat32Array = []
var _draws: PackedFloat32Array = []
var _prims: PackedFloat32Array = []
var _measure := false
var _cpu_ms: PackedFloat32Array = []
var _gpu_ms: PackedFloat32Array = []
var _scr_ms: PackedFloat32Array = []
var _phys_ms: PackedFloat32Array = []
var _objs: PackedFloat32Array = []


static func _mean(a: PackedFloat32Array) -> float:
	var s := 0.0
	for v in a:
		s += v
	return s / maxf(1, a.size())


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var a: Dictionary = main.args
	if a.has("drive-test"):
		_drive_test.call_deferred()
	elif a.has("autoshot"):
		_autoshot.call_deferred(String(a.autoshot))
	elif a.has("bench-spots"):
		_bench_spots.call_deferred(String(a["bench-spots"]))
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
		_objs.append(RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_OBJECTS_IN_FRAME))
		var vp := get_viewport().get_viewport_rid()
		_cpu_ms.append(RenderingServer.viewport_get_measured_render_time_cpu(vp) + RenderingServer.get_frame_setup_time_cpu())
		_gpu_ms.append(RenderingServer.viewport_get_measured_render_time_gpu(vp))
		_scr_ms.append(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0)
		_phys_ms.append(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0)


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
	_cpu_ms.clear()
	_gpu_ms.clear()
	_objs.clear()
	_scr_ms.clear()
	_phys_ms.clear()
	var vp := get_viewport().get_viewport_rid()
	RenderingServer.viewport_set_measure_render_time(vp, true)
	_measure = true
	await _wait(t)
	_measure = false
	RenderingServer.viewport_set_measure_render_time(vp, false)
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
		"sdfgi": main.env.sdfgi_enabled,
		# where the frame goes (averages): render-thread CPU, GPU, scripts (_process), physics tick
		"render_cpu_ms": snappedf(_mean(_cpu_ms), 0.01), "gpu_ms": snappedf(_mean(_gpu_ms), 0.01),
		"process_ms": snappedf(_mean(_scr_ms), 0.01), "physics_ms": snappedf(_mean(_phys_ms), 0.01),
		"objects": int(_mean(_objs))}
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


# ------------------------------------------------------------------ fixed camera spots (open world)
## --bench-spots=<dir> [--spot-secs=5]: downtown avenue, the arch bridge looking at the city,
## the summit lookout looking at the skyline, then the autopilot drive. Saves one PNG per spot
## and spots.json (fps, draw calls, primitives, VRAM, CPU/GPU ms, load time) into <dir>.
func _bench_spots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	_video_setup()
	var secs := float(main.args.get("spot-secs", "5"))
	var out := {"gpu": RenderingServer.get_video_adapter_name(), "load": main.town.stats.duplicate(),
		"startup_ms": Time.get_ticks_msec()}       # engine start to the end of main._ready()
	var w = null
	var wp := "res://assets/world/world.json"
	if FileAccess.file_exists(wp):
		w = JSON.parse_string(FileAccess.get_file_as_string(wp))
	await _wait(5.0)
	var cam = main.cam
	cam.manual = true
	if w != null:
		for spot in _spots(w):
			cam.fov = float(spot.get("fov", 62.0))
			cam.global_position = spot.eye
			cam.look_at(spot.at, Vector3.UP)
			if main.has_method("stream_now"):
				main.stream_now(spot.eye)
			await _wait(4.0)                                   # stream in, fog / GI settle
			out[spot.name] = await _measure_for(secs)
			await _shot(dir, "spot_" + spot.name)
	cam.manual = false
	cam.snap()
	main.ap_speed = 17.0
	_drive(true)
	await _wait(2.0)
	out["drive"] = await _measure_for(float(main.args.get("drive-secs", "20")))
	var f := FileAccess.open(dir.path_join("spots.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(out, "  "))
	f.close()
	print("SPOTS ", JSON.stringify(out))
	_quit()


static func _g(p: Array) -> Vector3:          # world.json (Blender) -> Godot
	return Vector3(p[0], p[2], -p[1])


static func _spots(w: Dictionary) -> Array:
	var dc := Vector2(-120, -150)
	for d in w.get("districts", []):
		if d.name == "downtown" and d.center != null:
			dc = Vector2(d.center[0], d.center[1])
	var city := Vector3(dc.x, 40.0, -dc.y)
	var spots := []
	# downtown avenue: the avenue sample nearest the downtown centre, looking along it
	var best := INF
	var av := {}
	for r in w.roads:
		if r["class"] != "avenue":
			continue
		var pts: Array = r.points
		for i in range(1, pts.size() - 1):
			var d := Vector2(pts[i][0], pts[i][1]).distance_to(dc)
			if d < best:
				best = d
				av = {"p": _g(pts[i]), "t": (_g(pts[i + 1]) - _g(pts[i - 1])).normalized()}
	if av:
		var t: Vector3 = av.t
		var side := Vector3.UP.cross(t).normalized()
		var eye: Vector3 = av.p + Vector3.UP * 2.2 + side * 3.0
		spots.append({"name": "avenue", "eye": eye, "at": eye + t * 60.0 + Vector3.UP * 4.0})
	# bridge: the arch (or the first) bridge, deck point nearest its middle, looking at downtown
	var br = null
	for b in w.get("bridges", []):
		if b.type == "arch":
			br = b
	if br == null and w.get("bridges", []).size() > 0:
		br = w.bridges[0]
	if br != null and br.get("arches", []).size() > 0:
		var a: Array = br.arches[0]
		var m: Array = a[a.size() / 2]
		var bd := INF
		var deck := Vector3.ZERO
		for r in w.roads:
			var dk: Array = r.get("deck", [])
			for i in dk.size():
				if dk[i]:
					var d := Vector2(r.points[i][0], r.points[i][1]).distance_to(Vector2(m[0], m[1]))
					if d < bd:
						bd = d
						deck = _g(r.points[i])
		var eye := deck + Vector3.UP * 4.0
		spots.append({"name": "bridge", "eye": eye, "at": city})
	# mountain lookout: the summit plaza, looking at the skyline
	for j in w.junctions:
		if j.kind == "plaza":
			var eye := _g(j.pos) + Vector3.UP * 3.0
			spots.append({"name": "lookout", "eye": eye, "at": city, "fov": 40.0})
			break
	return spots


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
	if main.args.has("spot") and FileAccess.file_exists("res://assets/world/world.json"):
		for spot in _spots(JSON.parse_string(FileAccess.get_file_as_string("res://assets/world/world.json"))):
			if spot.name == main.args.spot:
				main.cam.manual = true
				main.cam.fov = float(spot.get("fov", 62.0))
				main.cam.global_position = spot.eye
				main.cam.look_at(spot.at, Vector3.UP)
				if main.has_method("stream_now"):
					main.stream_now(spot.eye)
				await _wait(4.0)
	var env: Environment = main.env
	var moon: DirectionalLight3D = main.get_node("Moon")
	var vis: Node3D = main.town.get_node("Visuals")
	var res := {}
	res["base"] = await _measure_for(3.0)
	if main.traffic:
		main.traffic.visible = false
		res["traffic_hidden"] = await _measure_for(3.0)
		main.traffic.process_mode = Node.PROCESS_MODE_DISABLED
		res["traffic_hidden_paused"] = await _measure_for(3.0)
		main.traffic.process_mode = Node.PROCESS_MODE_INHERIT
		main.traffic.visible = true
	var lights: Node3D = main.town.get_node_or_null("Lights")
	if lights:
		lights.visible = false
		res["town_lights_hidden"] = await _measure_for(3.0)
		lights.visible = true
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
	env.sdfgi_enabled = false
	res["+no_sdfgi"] = await _measure_for(3.0)
	vis.visible = false
	res["+no_visuals"] = await _measure_for(3.0)
	print("MATRIX ", JSON.stringify(res, "  "))
	_quit()
