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
var _hitches: Array = []


static func _mean(a: PackedFloat32Array) -> float:
	var s := 0.0
	for v in a:
		s += v
	return s / maxf(1, a.size())


var _pp_first := 0
var _pp_scripts: PackedFloat32Array = []


## Physics frame split (--bench-prof): two probes, first and last in the physics process order, time
## the scripts' share of TIME_PHYSICS_PROCESS; the rest is the physics server step.
class PhysProbe extends Node:
	var auto
	var last := false
	func _physics_process(_dt: float) -> void:
		if not last:
			auto._pp_first = Time.get_ticks_usec()
		elif auto._measure:
			auto._pp_scripts.append((Time.get_ticks_usec() - auto._pp_first) / 1000.0)


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	if main.args.has("bench-prof"):
		for last in [false, true]:
			var pr := PhysProbe.new()
			pr.auto = self
			pr.last = last
			pr.process_physics_priority = 100000 if last else -100000
			add_child(pr)
	var a: Dictionary = main.args
	if a.has("drive-old"):
		_drive_test.call_deferred()
	elif a.has("autoshot"):
		_autoshot.call_deferred(String(a.autoshot))
	elif a.has("bench-spots"):
		_bench_spots.call_deferred(String(a["bench-spots"]))
	elif a.has("bench-matrix"):
		_bench_matrix.call_deferred()
	elif a.has("bench"):
		_bench_only.call_deferred(float(a.bench))
	elif a.has("interior-shots"):
		_interior_shots.call_deferred(String(a["interior-shots"]))


func _physics_process(delta: float) -> void:
	if _ap:
		main.autopilot_step(delta)


var _beat := 0


func _process(delta: float) -> void:
	var now := Time.get_ticks_msec()
	if now - _beat > 2000:
		_beat = now
		print("  [%.1f s] fps %d  frame %.1f ms" % [now / 1000.0, Engine.get_frames_per_second(), delta * 1000.0])
	if _measure or main.args.has("bench-prof"):
		if delta > 0.025 and _hitches.size() < 40 and now > 2000:
			var st: Dictionary = main.town.stats
			_hitches.append({"t": snappedf(now / 1000.0, 0.01), "ms": snappedf(delta * 1000.0, 0.1),
				"phys": snappedf(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0, 0.1),
				"q": main.town._queue.size() if "_queue" in main.town else -1, "cells": st.get("cells_live", 0),
				"lights": st.get("lights_live", 0), "shapes": st.get("shapes", 0),
				"traffic": main.traffic.active.size() if main.traffic else 0, "measuring": _measure})
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
		"objects": int(_mean(_objs)),
		"phys_active": Performance.get_monitor(Performance.PHYSICS_3D_ACTIVE_OBJECTS),
		"phys_pairs": Performance.get_monitor(Performance.PHYSICS_3D_COLLISION_PAIRS),
		"nodes": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
		"car_tick_us": snappedf(float(main.car.get("prof_us")), 0.1) if main.car.get("prof_us") != null else -1.0}
	if main.args.has("bench-prof"):
		r["hitches"] = _hitches.duplicate()
		r["physics_scripts_ms"] = snappedf(_mean(_pp_scripts), 0.01)
		_pp_scripts.clear()
	_hitches.clear()
	if main.traffic and main.args.has("bench-prof"):
		var tp: Dictionary = main.traffic.prof.duplicate()
		var per := {}
		for k in tp:
			per[k] = snappedf(float(tp[k]) / maxf(1, tp.ticks), 0.1)
		r["traffic_us_per_tick"] = per
		var cnt := {}
		for c in main.traffic.get_children():
			var nm := String(c.name).rstrip("0123456789")
			cnt[nm] = cnt.get(nm, 0) + _count_nodes(c)
		r["traffic_nodes"] = cnt
	print("BENCH ", JSON.stringify(r))
	return r


static func _count_nodes(n: Node) -> int:
	var k := 1
	for c in n.get_children():
		k += _count_nodes(c)
	return k


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
## Startup is over when 60 frames in a row took less than 25 ms (shader pipelines compiled, traffic set
## up); returns the engine time it took. The measurements start after it, so they are not startup.
func _settle(max_s := 30.0) -> int:
	var ok := 0
	var t0 := Time.get_ticks_msec()
	while ok < 60 and Time.get_ticks_msec() - t0 < max_s * 1000.0:
		await get_tree().process_frame
		ok = ok + 1 if get_process_delta_time() < 0.025 else 0
	print("settled at %.1f s" % (Time.get_ticks_msec() / 1000.0))
	return Time.get_ticks_msec()


func _bench_only(seconds: float) -> void:
	_video_setup()
	await _wait(5.0)
	await _settle()
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
	out["settled_ms"] = await _settle()      # engine start to steady frames: the load time a player sees
	var cam = main.cam
	cam.manual = true
	if main.args.has("clean"):          # comparison shots: no HUD, no rain streaks (the roads stay wet)
		main.hud.visible = false
		main.rain.visible = false
	if w != null:
		var only := String(main.args.get("spots", ""))
		var cams := []
		for spot in _spots(w):
			if only != "" and not (spot.name in only.split(",")):
				continue
			cams.append(_blender_cam(spot))
			cam.fov = float(spot.get("fov", 62.0))
			cam.global_position = spot.eye
			cam.look_at(spot.at, Vector3.UP)
			if main.has_method("stream_now"):
				main.stream_now(spot.eye)
			await _wait(4.0)                                   # stream in, fog / GI settle
			out[spot.name] = await _measure_for(secs)
			await _shot(dir, "spot_" + spot.name)
		# the same views for Cycles (tools/world/world_render.py --cams <dir>/cams.json)
		var cf := FileAccess.open(dir.path_join("cams.json"), FileAccess.WRITE)
		cf.store_string(JSON.stringify(cams, "  "))
		cf.close()
	if main.args.has("no-drive"):
		var f0 := FileAccess.open(dir.path_join("spots.json"), FileAccess.WRITE)
		f0.store_string(JSON.stringify(out, "  "))
		f0.close()
		print("SPOTS ", JSON.stringify(out))
		_quit()
		return
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


static func _b(v: Vector3) -> Array:          # Godot -> Blender
	return [snappedf(v.x, 0.001), snappedf(-v.z, 0.001), snappedf(v.y, 0.001)]


## A spot as a Blender camera: Godot's fov is vertical, so is the camera's sensor fit.
static func _blender_cam(spot: Dictionary) -> Dictionary:
	return {"name": spot.name, "loc": _b(spot.eye), "target": _b(spot.at), "fov_y": float(spot.get("fov", 62.0))}


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
	# mountain road: two points along the switchbacks, looking up the road (checks the road cut)
	for r in w.roads:
		if r["class"] != "mountain":
			continue
		var pts: Array = r.points
		for k in [0.3, 0.65]:
			var i := clampi(int(pts.size() * k), 1, pts.size() - 2)
			var p := _g(pts[i])
			var t := (_g(pts[i + 1]) - _g(pts[i - 1])).normalized()
			var eye := p + Vector3.UP * 2.4 - t * 6.0
			spots.append({"name": "mountain_road_%d" % int(k * 100), "eye": eye, "at": p + t * 40.0 + Vector3.UP * 1.0})
		break
	# mountain lookout: the summit plaza, looking at the skyline
	for j in w.junctions:
		if j.kind == "plaza":
			var eye := _g(j.pos) + Vector3.UP * 3.0
			spots.append({"name": "lookout", "eye": eye, "at": city, "fov": 40.0})
			break
	spots.append_array(_road_spots(w, dc))
	return spots


## Road-look spots (docs/agents/roadlook): street level on the avenue, a signalised junction with its
## zebra crossings, a curb / gutter / sidewalk close-up and a low view over the wet asphalt.
static func _road_spots(w: Dictionary, dc: Vector2) -> Array:
	var spots := []
	var roads := {}
	for r in w.roads:
		roads[r.id] = r
	# the four-way junction nearest downtown whose arms are all curb streets / avenues
	var best := INF
	var jn = null
	for j in w.junctions:
		if j.kind != "X":
			continue
		var ok := true
		for a in j.arms:
			var rr = roads.get(a.road)
			if rr == null or rr.get("side", "curb") != "curb":
				ok = false
		var d := Vector2(j.pos[0], j.pos[1]).distance_to(dc)
		if ok and d < best:
			best = d
			jn = j
	if jn != null:
		var c := _g(jn.pos)
		var a: Dictionary = jn.arms[0]
		var ad := Vector3(a.dir[0], 0.0, -a.dir[1]).normalized()      # outward along the arm
		var side := Vector3.UP.cross(ad).normalized()
		var eye: Vector3 = c + ad * (float(a.length) + 14.0) + side * 1.8 + Vector3.UP * 1.7
		spots.append({"name": "junction", "eye": eye, "at": c + Vector3.UP * 0.5})
		# curb close-up: standing on the arm's sidewalk edge, looking along the curb into the junction
		var hw := float(a.half_width)
		var ce: Vector3 = c + ad * (float(a.length) + 6.0) + side * (hw + 1.2) + Vector3.UP * 1.25
		spots.append({"name": "curb", "eye": ce, "at": c + ad * (float(a.length) - 4.0) + side * (hw - 0.6), "fov": 55.0})
	# wet asphalt: low over the avenue nearest downtown, looking down it at the neon
	var bst := INF
	var av := {}
	for r in w.roads:
		if r["class"] != "avenue":
			continue
		var pts: Array = r.points
		for i in range(2, pts.size() - 2):
			var d := Vector2(pts[i][0], pts[i][1]).distance_to(dc + Vector2(60, 40))
			if d < bst:
				bst = d
				av = {"p": _g(pts[i]), "t": (_g(pts[i + 1]) - _g(pts[i - 1])).normalized()}
	if av:
		var t: Vector3 = av.t
		var side := Vector3.UP.cross(t).normalized()
		var eye: Vector3 = av.p + Vector3.UP * 0.9 - side * 2.0
		spots.append({"name": "wet", "eye": eye, "at": eye + t * 40.0 - Vector3.UP * 1.6})
	return spots


# ------------------------------------------------------------------ physics check (headless OK)
func _drive_test() -> void:
	var car: RigidBody3D = main.car
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
		if main.args.has("probe-traffic"):
			# what the paused traffic still costs: its bodies / nodes, removed group by group
			var info := []
			for c in main.traffic.cars:
				if not c._shape.disabled:
					info.append([c.mode, c.freeze, c.freeze_mode, c.collision_mask, c.global_position.distance_to(main.car.global_position), c.sleeping])
			print("PROBE cars with collision: ", info)
			print("PROBE parked: ", main.traffic.parked.filter(func(pc): return not pc._shape.disabled).size(), " ", main.traffic.parked.map(func(pc): return [pc.mode, pc.freeze, pc.freeze_mode, int(pc.global_position.distance_to(main.car.global_position))]).slice(0, 6))
			for c in main.traffic.cars:
				c._shape.disabled = true
			res["traffic_paused_cars_nocol"] = await _measure_for(3.0)
			var colc := []
			for c in main.traffic.cars:
				if c.mode != 4:
					colc.append(c)
					c._shape.disabled = false
					break
			var cr: Node = main.town.get_node("Collision")
			for b in cr.get_children():
				if String(b.name).begins_with("Shapes"):
					b.process_mode = Node.PROCESS_MODE_DISABLED
			res["traffic_paused_onecar_no_shapes"] = await _measure_for(3.0)
			for b in cr.get_children():
				b.process_mode = Node.PROCESS_MODE_DISABLED
			res["traffic_paused_onecar_no_towncol"] = await _measure_for(3.0)
			for b in cr.get_children():
				b.process_mode = Node.PROCESS_MODE_INHERIT
			res["traffic_paused_onecar_towncol"] = await _measure_for(3.0)
			for c in colc:
				c._shape.disabled = true
			var hero_xf: Transform3D = main.car.global_transform
			main.car.freeze = true
			res["traffic_paused_hero_frozen"] = await _measure_for(3.0)
			main.car.freeze = false
			main.car.global_transform = hero_xf
			for pc in main.traffic.parked:
				pc._shape.disabled = true
			res["traffic_paused_parked_nocol"] = await _measure_for(3.0)
			for pc in main.traffic.parked:
				pc.visible = false
			res["traffic_paused_parked_nocol_hidden"] = await _measure_for(3.0)
			for pc in main.traffic.parked:
				pc.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
			res["traffic_paused_parked_noint"] = await _measure_for(3.0)
			var removed := []
			for grp in [["Parked"], ["Traffic"], ["Signals", "Pedestrians"]]:
				for c in main.traffic.get_children():
					if String(c.name).rstrip("0123456789") in grp:
						main.traffic.remove_child(c)
						removed.append(c)
				res["traffic_paused_minus_" + "_".join(grp)] = await _measure_for(3.0)
			for c in removed:
				main.traffic.add_child(c)
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


# ------------------------------------------------------------------ interior-mapped windows
## --interior-shots=<dir> [--no-interiors]: night views into the windows (docs/agents/interiors):
## a street-level view of a kit building's upper windows from two angles (parallax), a shop front,
## a tower close-up and the far skyline (bridge spot), each with fps. Writes shots.json.
func _interior_shots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	_video_setup()
	main.hud.visible = false
	main.rain.visible = false
	main.car.visible = false
	await _wait(5.0)
	await _settle()
	var cam = main.cam
	cam.manual = true
	var town = main.town
	var w = null
	if FileAccess.file_exists("res://assets/world/world.json"):
		w = JSON.parse_string(FileAccess.get_file_as_string("res://assets/world/world.json"))
	var origin: Vector3 = main.car.global_position
	if w != null:
		for s in _spots(w):
			if s.name == "avenue":
				origin = s.eye
	var out := {"interiors": town.interiors_enabled}
	var views := []
	for want in [["building_a", 2.5, 7.0, 15.0, 6.0, "street"], ["building_b", 0.5, 3.5, 8.0, 3.5, "shopfront"], ["building_c", 5.0, 14.0, 20.0, 9.0, "corporate"]]:
		var v := await _window_view(town, origin, want[0], want[1], want[2], want[3], want[4])
		if v.is_empty():
			print("interior shots: no clear view of ", want[0])
			continue
		v["name"] = want[5]
		views.append(v)
	for v in views:
		for k in [-1, 1]:
			var nm: String = v.name + ("_left" if k < 0 else "_right")
			cam.fov = 50.0
			cam.global_position = v.eye + v.side * float(k) * v.slide
			cam.look_at(v.at, Vector3.UP)
			main.stream_now(cam.global_position)
			await _wait(2.5)
			out[nm] = await _measure_for(2.0)
			await _shot(dir, nm)
	# a tower facade close-up
	var tv := await _tower_view(town, origin)
	if not tv.is_empty():
		cam.fov = 55.0
		cam.global_position = tv.eye
		cam.look_at(tv.at, Vector3.UP)
		main.stream_now(tv.eye)
		await _wait(3.0)
		out["tower"] = await _measure_for(2.0)
		await _shot(dir, "tower")
	if w != null:
		for s in _spots(w):
			if s.name in ["bridge", "lookout"]:
				cam.fov = float(s.get("fov", 62.0))
				cam.global_position = s.eye
				cam.look_at(s.at, Vector3.UP)
				main.stream_now(s.eye)
				await _wait(4.0)
				out["skyline_" + s.name] = await _measure_for(3.0)
				await _shot(dir, "skyline_" + s.name)
	var f := FileAccess.open(dir.path_join("shots.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(out, "  "))
	f.close()
	print("INTERIOR_SHOTS ", JSON.stringify(out))
	_quit()


## A kit building near `origin` with an unobstructed street-level view of its panes between y0 and
## y1 (object space): {eye, at, side, slide}.
func _window_view(town, origin: Vector3, asset: String, y0: float, y1: float, dist: float, slide: float) -> Dictionary:
	var jp := "res://assets/interiors/%s_panes.json" % asset
	if not FileAccess.file_exists(jp):
		return {}
	var panes: Array = JSON.parse_string(FileAccess.get_file_as_string(jp)).panes
	var cands := []
	for inst in town.layout.instances:
		if String(inst.mesh).split("__")[0] != asset:
			continue
		var xf: Transform3D = town.xf_from(inst.xf)
		var d := xf.origin.distance_to(origin)
		if d < 600.0:
			cands.append([d, xf])
	cands.sort_custom(func(a, b): return a[0] < b[0])
	var space = get_viewport().get_world_3d().direct_space_state
	for c in cands.slice(0, 40):
		var xf: Transform3D = c[1]
		# the facade with the most panes in the height band
		var faces := {}
		for p in panes:
			if p.center[1] < y0 or p.center[1] > y1:
				continue
			var key := Vector3(p.normal[0], p.normal[1], p.normal[2]).snapped(Vector3.ONE * 0.5)
			faces[key] = faces.get(key, []) + [p]
		for key in faces:
			var list: Array = faces[key]
			if list.size() < 2:
				continue
			var mid := Vector3.ZERO
			for p in list:
				mid += Vector3(p.center[0], p.center[1], p.center[2])
			mid /= float(list.size())
			var at: Vector3 = xf * mid
			var n: Vector3 = (xf.basis * key).normalized()
			var eye: Vector3 = at + n * dist
			eye.y = xf.origin.y + 1.7
			var side := Vector3.UP.cross(n).normalized()
			main.stream_now(eye)
			town.ensure_collision(eye, 40.0)
			await get_tree().physics_frame
			var ok := true
			for e in [eye, eye + side * slide, eye - side * slide]:
				var q := PhysicsRayQueryParameters3D.create(e, at - n * 0.3)
				var hit: Dictionary = space.intersect_ray(q)
				if hit and hit.position.distance_to(at) > 1.5:
					ok = false
				var down := PhysicsRayQueryParameters3D.create(e + Vector3.UP * 3.0, e - Vector3.UP * 4.0)
				var g: Dictionary = space.intersect_ray(down)
				if g.is_empty() or g.position.y > e.y - 0.5:
					ok = false
			if ok:
				return {"eye": eye, "at": at, "side": side, "slide": slide}
	return {}


func _tower_view(town, origin: Vector3) -> Dictionary:
	var cands := []
	for inst in town.layout.instances:
		var m := String(inst.mesh)
		if not m.begins_with("tower_") or not town.layout.meshes.get(m, {}).has("aabb"):
			continue
		var xf: Transform3D = town.xf_from(inst.xf)
		cands.append([xf.origin.distance_to(origin), xf, town.layout.meshes[m].aabb])
	cands.sort_custom(func(a, b): return a[0] < b[0])
	var space = get_viewport().get_world_3d().direct_space_state
	for c in cands.slice(0, 30):
		var xf: Transform3D = c[1]
		var lo := Vector3(c[2][0][0], c[2][0][1], c[2][0][2])
		var hi := Vector3(c[2][1][0], c[2][1][1], c[2][1][2])
		for ax in [Vector3.RIGHT, Vector3.LEFT, Vector3.FORWARD, Vector3.BACK]:
			var fc: Vector3 = (lo + hi) * 0.5 + ax * (hi - lo) * 0.5
			fc.y = lo.y + 14.0
			var face: Vector3 = xf * fc
			var n: Vector3 = (xf.basis * ax).normalized()
			var side := Vector3.UP.cross(n).normalized()
			var eye: Vector3 = face + n * 30.0 + side * 12.0 - Vector3.UP * 6.0
			main.stream_now(eye)
			town.ensure_collision(eye, 40.0)
			await get_tree().physics_frame
			var hit: Dictionary = space.intersect_ray(PhysicsRayQueryParameters3D.create(eye, face + n * 0.5))
			var g: Dictionary = space.intersect_ray(PhysicsRayQueryParameters3D.create(eye, eye - Vector3.UP * 30.0))
			if hit.is_empty() and not g.is_empty():
				return {"eye": eye, "at": face + Vector3.UP * 6.0}
	return {}
