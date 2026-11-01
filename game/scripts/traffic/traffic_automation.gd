extends Node
## Traffic automation (user args after "--"):
##   --traffic-test=<seconds> [--traffic-out=<file.json>]   headless: no stuck cars, no cars off the road,
##        signals cycling, few AI-AI collisions; then the player reactions (brake for, bump).  Exit 0 = pass.
##   --traffic-shots=<dir>   windowed: busy junction, jam at a red light, chase cam, security cruiser, perf.json
##   --bench-traffic         windowed: fps with 0 / 30 / 60 / 80 moving cars while the autopilot drives

const TrafficCar := preload("res://scripts/traffic/traffic_car.gd")

var main: Node3D
var _frames: PackedFloat32Array = []
var _measure := false
var _ap := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var a: Dictionary = main.args
	if a.has("traffic-test"):
		_test.call_deferred(float(a["traffic-test"]))
	elif a.has("traffic-shots"):
		_shots.call_deferred(String(a["traffic-shots"]))
	elif a.has("bench-traffic"):
		_bench.call_deferred()


func _physics_process(delta: float) -> void:
	if _ap:
		main.autopilot_step(delta)


func _process(delta: float) -> void:
	if _measure:
		_frames.append(delta)


func _wait(t: float) -> void:
	await get_tree().create_timer(t, true, false, true).timeout


func _traffic_ready() -> void:
	while main.traffic == null or not main.traffic.ready_ok:
		await get_tree().process_frame


# ================================================================== headless test
func _test(seconds: float) -> void:
	var T = main.traffic
	if T == null:
		print("TRAFFICTEST FAIL no traffic")
		get_tree().quit(1)
		return
	await _traffic_ready()
	var car: VehicleBody3D = main.car
	# the player out of the way: frozen and not an obstacle
	var hero_layer := car.collision_layer
	car.freeze = true
	car.collision_layer = 0
	car.collision_mask = 0
	# parked above the middle of the map (the spawn ring is centred on the player)
	var park := Transform3D(Basis(), car.global_position + Vector3.UP * 25.0)
	T.ignore_player = true
	car.global_transform = park
	var res := {"seconds": seconds, "graph": T.graph.summary(), "vehicles": T.lib.source, "models": T.lib.models.size()}
	var layout: Dictionary = main.town.layout if main.town and main.town.layout else {}
	var offroad := 0
	var samples := 0
	var offroad_where := []
	var max_dev := 0.0
	var t := 0.0
	var space := main.get_world_3d().direct_space_state
	var ray := PhysicsRayQueryParameters3D.new()
	ray.collision_mask = 1
	var stuck := {}
	var counts := []
	var min_active := 1000
	while t < seconds:
		await _wait(1.0)
		t += 1.0
		car.global_transform = park
		var act := 0
		for c in T.active:
			if c.mode != TrafficCar.KINEMATIC:
				continue
			act += 1
			samples += 1
			var p: Vector3 = c.global_position
			# off-road: the ground under the car must be road / junction (town), and the car must sit
			# on a lane (any world)
			var l = T.graph.lanes[c.lane]
			var q: Vector3 = l.pos_at(c.s)
			var dev := Vector2(p.x - q.x, p.z - q.z).length() - absf(c.lat)
			max_dev = maxf(max_dev, dev)
			var bad := dev > 0.6
			if not layout.is_empty():
				ray.from = p + Vector3.UP * 1.0
				ray.to = p - Vector3.UP * 2.0
				var h := space.intersect_ray(ray)
				var cat := "none"
				if h and h.collider:
					var key := String(h.collider.name).trim_prefix("Col_")
					cat = String(layout.meshes.get(key, {}).get("cat", "other")) if String(h.collider.name).begins_with("Col_") else "prop"
				if cat != "road":
					bad = true
					if offroad_where.size() < 8:
						offroad_where.append({"lane": l.name, "s": snappedf(c.s, 0.1), "pos": [snappedf(p.x, 0.1), snappedf(p.y, 0.1), snappedf(p.z, 0.1)], "ground": cat})
			if bad:
				offroad += 1
			if c.stall_t > 75.0:
				stuck[c.idx] = {"lane": l.name, "reason": c.wait_reason, "stall": snappedf(c.stall_t, 0.1)}
		if t > 5.0:
			min_active = mini(min_active, act)
		if int(t) % 10 == 0:
			counts.append(T.summary())
			print("  t=%d active %d  %s" % [t, T.active.size(), JSON.stringify(T.summary())])
	res["traffic"] = T.summary()
	res["samples"] = samples
	res["offroad_samples"] = offroad
	res["offroad_examples"] = offroad_where
	res["max_lane_deviation_m"] = snappedf(max_dev, 0.01)
	res["stuck_cars"] = stuck.values()
	res["signals_all_cycled"] = T.signals.all_cycled()
	res["min_active_after_5s"] = min_active
	res["avg_speed_ms"] = snappedf(T.stats.distance_km * 1000.0 / maxf(T.stats.car_seconds, 1.0), 0.01)
	res["ai_collision_log"] = T.collision_log
	var checks := {
		"no_stuck_cars": stuck.is_empty(),
		"no_offroad": offroad == 0,
		"signals_cycle": T.signals.all_cycled() and T.signals.stats.phase_changes > 0,
		"few_ai_collisions": T.stats.ai_collisions <= 3,
		"traffic_flows": T.stats.junctions > 0 and min_active >= int(T.target * 0.6) and res.avg_speed_ms > 3.0,
	}
	# --- player reactions: a car brakes for the stopped player; then the player bumps a car
	car.collision_layer = hero_layer
	car.collision_mask = 1 | 2
	T.ignore_player = false
	var victim = null
	for c in T.active:
		var l = T.graph.lanes[c.lane]
		if c.mode == TrafficCar.KINEMATIC and l.junction < 0 and l.length - c.s > 70.0 and c.v > 4.0 and c.lc_t >= 1.0:
			victim = c
			break
	if victim:
		var l = T.graph.lanes[victim.lane]
		var sp: float = victim.s + 32.0
		var p: Vector3 = l.pos_at(sp)
		var d: Vector3 = l.dir_at_seg(l.seg_at(sp, 0))
		car.freeze = false
		car.place(Transform3D(Basis(Vector3.UP.cross(d).normalized(), Vector3.UP, d), p + Vector3.UP * 0.3))
		car.autopilot = true
		car.input_throttle = 0.0
		car.input_handbrake = true
		var honks0: int = T.stats.honks
		var min_gap := INF
		var stopped := false
		var tt := 0.0
		while tt < 9.0:
			await get_tree().physics_frame
			tt += 1.0 / Engine.physics_ticks_per_second
			if victim.mode != TrafficCar.KINEMATIC:
				break
			var g: float = (car.global_position - victim.global_position).length() - 4.4
			min_gap = minf(min_gap, g)
			if victim.v < 0.2:
				stopped = true
		res["player_brake"] = {"stopped": stopped, "min_gap_m": snappedf(min_gap, 0.01), "knocked": victim.mode != TrafficCar.KINEMATIC,
			"honks": T.stats.honks - honks0}
		checks["brakes_for_player"] = stopped and min_gap > 0.3 and victim.mode == TrafficCar.KINEMATIC
		# bump: reverse the player into the waiting car... simpler: launch the player at it
		var k0: int = T.stats.knocked
		var r0: int = T.stats.recovered
		car.input_handbrake = false
		var to: Vector3 = (victim.global_position - car.global_position)
		to.y = 0.0
		car.place(Transform3D(Basis(Vector3.UP.cross(to.normalized()).normalized(), Vector3.UP, to.normalized()), car.global_position + Vector3.UP * 0.1))
		await get_tree().physics_frame
		car.linear_velocity = to.normalized() * 9.0
		car.input_throttle = 0.3
		tt = 0.0
		while tt < 16.0 and T.stats.recovered == r0:
			await get_tree().physics_frame
			tt += 1.0 / Engine.physics_ticks_per_second
			if tt > 2.0:
				car.input_throttle = 0.0
				car.input_handbrake = true
		res["player_bump"] = {"knocked": T.stats.knocked - k0, "recovered": T.stats.recovered - r0, "time": snappedf(tt, 0.1)}
		checks["bumped_and_recovers"] = T.stats.knocked > k0 and T.stats.recovered > r0
	else:
		checks["brakes_for_player"] = false
	res["checks"] = checks
	var ok := true
	for k in checks:
		ok = ok and checks[k]
	res["pass"] = ok
	print("TRAFFICTEST ", JSON.stringify(res))
	if main.args.has("traffic-out"):
		var f := FileAccess.open(String(main.args["traffic-out"]), FileAccess.WRITE)
		if f:
			f.store_string(JSON.stringify(res, "  "))
			f.close()
	print("TRAFFICTEST ", "PASS" if ok else "FAIL")
	await _wait(0.2)
	get_tree().quit(0 if ok else 1)


# ================================================================== screenshots
func _video_setup() -> void:
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	Engine.max_fps = 0
	if DisplayServer.window_get_size() != Vector2i(1920, 1080):
		DisplayServer.window_set_size(Vector2i(1920, 1080))


func _shot(dir: String, nm: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img.get_width() > 1600:
		img.resize(1600, int(1600.0 * img.get_height() / img.get_width()), Image.INTERPOLATE_LANCZOS)
	var full := dir.path_join(nm + ".png")
	img.save_png(full)
	print("SHOT ", full)


func _measure_for(t: float) -> Dictionary:
	_frames.clear()
	_measure = true
	var draws := 0.0
	var n := 0
	var t0 := Time.get_ticks_msec()
	while Time.get_ticks_msec() - t0 < t * 1000.0:
		await get_tree().process_frame
		draws += RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME)
		n += 1
	_measure = false
	var ft := Array(_frames)
	ft.sort()
	var tot := 0.0
	for f in ft:
		tot += f
	var avg := tot / maxf(1, ft.size())
	var p99: float = ft[int(ft.size() * 0.99)] if ft.size() > 0 else 0.0
	var r := {"avg_fps": snappedf(1.0 / maxf(avg, 1e-6), 0.1), "avg_ms": snappedf(avg * 1000.0, 0.01),
		"p1_low_fps": snappedf(1.0 / maxf(p99, 1e-6), 0.1), "draw_calls": int(draws / maxf(1, n)),
		"active_cars": main.traffic.active.size() if main.traffic else 0,
		"resolution": "%dx%d" % [get_viewport().get_visible_rect().size.x, get_viewport().get_visible_rect().size.y]}
	print("BENCH ", JSON.stringify(r))
	return r


func _junction(nm: String):
	for J in main.traffic.graph.junctions:
		if J.name == nm:
			return J
	return main.traffic.graph.junctions[0]


## Fill the incoming lanes of a junction approach with a queue.
func _queue(J, ai: int, n: int) -> void:
	var T = main.traffic
	var ap: Dictionary = J.approaches[ai]
	for li in ap.lanes:
		var l = T.graph.lanes[li]
		var s: float = l.length - 4.0
		for k in n:
			if s < 5.0:
				break
			var c = T._free_car()
			if c == null:
				return
			T._place(c, l, s)
			c.v = 0.0
			s -= 7.5


func _populate(around: Vector3, radius: float, n: int) -> void:
	var T = main.traffic
	var tries := n * 20
	while n > 0 and tries > 0:
		tries -= 1
		var spot: Array = T._random_road_spot()
		var p: Vector3 = spot[0].pos_at(spot[1])
		if p.distance_to(around) > radius or not T._lane_free(spot[0], spot[1], 12.0):
			continue
		var c = T._free_car()
		if c == null:
			return
		T._place(c, spot[0], spot[1])
		n -= 1


func _shots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	_video_setup()
	await _traffic_ready()
	var T = main.traffic
	T.fixed_count = true
	T.target = 60
	var cam: Camera3D = main.cam
	var perf := {"gpu": RenderingServer.get_video_adapter_name(), "graph": T.graph.summary(), "vehicles": T.lib.source}
	await _wait(5.0)
	# 1. busy junction at night (J1 crossroads), from a first-floor window
	var J = _junction("J1")
	_populate(J.pos, 70.0, 14)
	cam.manual = true
	main.car.freeze = true
	main.car.global_position = J.pos + Vector3(60, 0.5, 60)    # hero out of the frame
	var ap0: Dictionary = J.approaches[0]
	var cpos: Vector3 = J.pos - ap0.dir * 24.0 + Vector3.UP.cross(ap0.dir).normalized() * 9.0 + Vector3.UP * 9.0
	cam.fov = 62.0
	cam.global_position = cpos
	cam.look_at(J.pos + Vector3.UP * 0.5 + ap0.dir * 4.0, Vector3.UP)
	await _wait(9.0)
	await _shot(dir, "01_busy_junction")
	perf["junction_view"] = await _measure_for(3.0)
	# 2. jam at a red light: hold one approach red and queue cars on it, look along the queue
	var ai := 1 if J.approaches.size() > 1 else 0
	T.signals.hold_red(J.id, ai, 60.0)
	_queue(J, ai, 7)
	var ap: Dictionary = J.approaches[ai]
	var kerb = T.graph.lanes[ap.lanes[0]]
	var end: Vector3 = kerb.pts[kerb.pts.size() - 1]
	var back: Vector3 = kerb.pos_at(maxf(0.0, kerb.length - 62.0))
	var side: Vector3 = Vector3.UP.cross(ap.dir).normalized() * -T.graph.kerb_sign()
	cam.global_position = back + side * 4.5 + Vector3.UP * 3.2
	cam.look_at(end + Vector3.UP * 1.5, Vector3.UP)
	cam.fov = 50.0
	await _wait(7.0)
	await _shot(dir, "02_red_light_jam")
	T.signals.hold_red(J.id, ai, 0.0)
	# 3. chase cam with traffic: the autopilot drives the hero, traffic around it
	cam.manual = false
	main.car.freeze = false
	main.reset_car()
	main.car.place(main.town.spawn_transform())
	cam.mode = 0
	cam.snap()
	_populate(main.car.global_position, 90.0, 12)
	main.ap_speed = 14.0
	main.autopilot_start()
	_ap = true
	await _wait(9.0)
	await _shot(dir, "03_chase_traffic")
	perf["drive_60"] = await _measure_for(8.0)
	# 4. Hoshikawa Security cruiser, light bar flashing, from the kerb
	_ap = false
	main.car.input_throttle = -1.0
	var best = null
	for l in T._road_lanes:
		if l.length > 70.0 and (best == null or l.pos_at(20.0).distance_to(main.car.global_position) > best.pos_at(20.0).distance_to(main.car.global_position)):
			if l.pos_at(20.0).distance_to(main.car.global_position) < 120.0:
				best = l
	if best == null:
		best = T._road_lanes[0]
	var pc = T.spawn_patrol_at(best, 12.0, true)
	pc.drive_factor = 0.55
	cam.manual = true
	var tt := 0.0
	while tt < 4.2:
		await get_tree().process_frame
		tt += get_process_delta_time()
		var pz: Vector3 = pc.global_basis.z
		var px: Vector3 = pc.global_basis.x
		cam.global_position = pc.global_position + pz * 7.5 + px * 3.6 + Vector3.UP * 1.25
		cam.look_at(pc.global_position + Vector3.UP * 0.8 + pz * 0.6, Vector3.UP)
		cam.fov = 55.0
	await _shot(dir, "04_security_cruiser")
	# perf: hero chase drive with 0 / 30 / 60 / 80 cars
	cam.manual = false
	main.car.place(main.town.spawn_transform())
	cam.snap()
	main.autopilot_start()
	_ap = true
	perf["matrix"] = await _count_matrix()
	var f := FileAccess.open(dir.path_join("perf.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(perf, "  "))
	f.close()
	print("PERF ", JSON.stringify(perf))
	await _wait(0.2)
	get_tree().quit()


func _count_matrix() -> Dictionary:
	var T = main.traffic
	var out := {}
	for n in [0, 30, 60, 80]:
		T.fixed_count = true
		T.target = n
		for c in T.active.duplicate():
			if T.active.filter(func(x): return not x.patrol).size() <= n:
				break
			if not c.patrol:
				T._despawn(c)
		T._fill(true)
		await _wait(3.0)
		out["cars_%d" % n] = await _measure_for(6.0)
	return out


func _bench() -> void:
	_video_setup()
	await _traffic_ready()
	await _wait(4.0)
	main.ap_speed = 15.0
	main.autopilot_start()
	_ap = true
	var r := await _count_matrix()
	print("BENCHTRAFFIC ", JSON.stringify(r))
	await _wait(0.2)
	get_tree().quit()
