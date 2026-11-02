extends Node
## Pedestrian tests and proof (user args after "--"):
##
##   --npc-test [--npc-out=res.json]   headless OK, exit 0 = pass:
##       spawn      every walker placed, citizens with skeletons near the camera, the crowd beyond
##       pavement   20 s of walking: nobody on the carriageway except on crossings / mid-dodge / thrown,
##                  everybody moved at a walking pace
##       crossing   walkers crossed; at signalled junctions only while the cars had red; a walker sent to
##                  a signalled crossing waits on green and goes on red
##       dodge      the player's car at 60 km/h at a walker in the road: they jump aside
##       ragdoll    a real hit at ~45 km/h: thrown (physical bones), down, back on their feet within 12 s
##       cap        9 walkers hit at once: at most max_ragdolls (6) ragdolls, the rest stagger
##       perf       NPC cost per frame (AI + motion + animation + crowd + hit tests) < 1.5 ms
##   --npc-shots=<dir>   windowed: rainy street with people, a ragdoll mid-fall, a close-up, a crossing
##   --npc-bench         windowed: fps with and without the pedestrians

const Sidewalks := preload("res://scripts/npc/sidewalks.gd")

var main: Node3D
var npc: Node3D
var car: RigidBody3D
var res := {}
var ok := {}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	npc = main.npc
	car = main.car
	if npc == null:
		push_error("npc test: no pedestrians (citizens not built? --no-npc?)")
		get_tree().quit(2)
		return
	if main.args.has("npc-shots"):
		_shots.call_deferred(String(main.args["npc-shots"]))
	elif main.args.has("npc-bench"):
		_bench.call_deferred()
	else:
		_test.call_deferred()


func _wait(t: float) -> void:
	for i in maxi(1, int(t * Engine.physics_ticks_per_second)):
		await get_tree().physics_frame


func _frames(n: int) -> void:
	for i in n:
		await get_tree().process_frame


func _ready_npc() -> bool:
	for i in 600:
		if npc.ready_ok:
			return true
		await get_tree().process_frame
	return false


func _park_car() -> void:
	# keep the player's car still and out of the way (but where the camera is)
	car.autopilot = true
	car.input_throttle = 0.0
	car.input_brake = 1.0
	car.input_steer = 0.0
	car.linear_velocity = Vector3.ZERO


## A near walker standing on a walk edge, closest to p.
func _near_agent(p: Vector3, exclude := []):
	var best = null
	var bd := INF
	for a in npc.agents:
		if a in exclude or a.state == npc.DOWN or a.node == null:
			continue
		var d: float = a.pos.distance_to(p)
		if d < bd:
			bd = d
			best = a
	return best


func _test() -> void:
	var t_start := Time.get_ticks_msec()
	if not await _ready_npc():
		_fail("setup", "sidewalk network never finished")
		return
	_park_car()
	await _wait(3.0)
	# ---- spawn
	var near: int = npc.agents.filter(func(a): return a.node != null).size()
	res.spawn = {"agents": npc.agents.size(), "near_nodes": near, "network": npc.net.stats}
	ok.spawn = npc.agents.size() == npc.max_agents and near >= mini(12, npc.max_agents)
	# ---- pavement + walking
	var start := {}
	for a in npc.agents:
		start[a] = a.pos
	var bad := 0
	var samples := 0
	var worst := []
	var G = main.traffic.graph if main.traffic else null
	for k in 40:
		await _wait(0.5)
		for a in npc.agents:
			if a.state in [npc.DOWN, npc.DODGE, npc.STAGGER] or a.dist > 120.0:
				continue
			var e = npc.net.edges[a.edge]
			if e.kind == Sidewalks.CROSSING:
				continue
			samples += 1
			var off := absf(a.lat) > 1.35
			var on_road := false
			if G:
				var hit: Array = G.nearest(a.pos, 2.2, true)
				on_road = hit[0] >= 0 and G.lanes[hit[0]].junction < 0
			if off or on_road:
				bad += 1
				if worst.size() < 5:
					worst.append({"pos": a.pos, "edge": a.edge, "kind": e.kind, "lat": a.lat, "on_road": on_road})
	var vs := 0.0
	var walkers := 0
	for a in npc.agents:
		if a.state == npc.WALK:
			vs += a.v
			walkers += 1
	res.pavement = {"samples": samples, "off_pavement": bad, "examples": worst, "mean_walk_speed": snappedf(vs / maxf(1, walkers), 0.01)}
	ok.pavement = samples > 200 and float(bad) / samples < 0.005 and vs / maxf(1, walkers) > 0.8
	# ---- crossing at a signalled junction
	res.crossing = await _crossing_test()
	ok.crossing = res.crossing.get("ok", false) and npc.stats.red_violations == 0 and npc.stats.crossings > 0
	# ---- dodge
	res.dodge = await _dodge_test()
	ok.dodge = res.dodge.get("ok", false)
	# ---- ragdoll + get-up
	for attempt in 3:              # a parked car or a lamp post can be in the way: try another walker
		res.ragdoll = await _ragdoll_test()
		res.ragdoll["attempt"] = attempt + 1
		if res.ragdoll.get("ok", false):
			break
	ok.ragdoll = res.ragdoll.get("ok", false)
	# ---- cap
	res.cap = await _cap_test()
	ok.cap = res.cap.get("ok", false)
	# ---- perf (walking, nobody down)
	_park_car()
	await _wait(2.0)
	npc.reset_prof()
	var f0 := Engine.get_process_frames()
	await _wait(8.0)
	var sm: Dictionary = npc.summary()
	var us: Dictionary = sm.us_per_frame
	var per_frame: int = us.total + us.phys
	res.perf = {"us_per_frame": us, "total_us": per_frame, "frames": Engine.get_process_frames() - f0, "near": sm.near,
		"agents": sm.agents, "fps_headless": Engine.get_frames_per_second()}
	ok.perf = per_frame < 1500
	res.stats = npc.summary()
	res.ok = ok
	res.secs = (Time.get_ticks_msec() - t_start) / 1000.0
	var pass_all := ok.values().all(func(v): return v)
	print("npc test: ", JSON.stringify(res, "  "))
	print("npc test: %s %s" % ["PASS" if pass_all else "FAIL", JSON.stringify(ok)])
	if main.args.has("npc-out"):
		var f := FileAccess.open(String(main.args["npc-out"]), FileAccess.WRITE)
		f.store_string(JSON.stringify(res, "  "))
	get_tree().quit(0 if pass_all else 1)


func _fail(what: String, why: String) -> void:
	print("npc test: FAIL %s: %s" % [what, why])
	get_tree().quit(1)


## A walker sent to a signalled crossing: waits while the cars have green, crosses when they get red.
func _crossing_test() -> Dictionary:
	if main.traffic == null:
		return {"ok": npc.stats.crossings > 0, "note": "no traffic: unsignalled only"}
	var cpos: Vector3 = npc._center()
	var best = null
	var bd := INF
	for e in npc.net.edges:
		if e.kind != Sidewalks.CROSSING or npc.crossing_signal(e) < 0:
			continue
		var d: float = e.pts[0].distance_to(cpos)
		if d < bd:
			bd = d
			best = e
	if best == null:
		return {"ok": npc.stats.crossings > 0, "note": "no signalled crossing"}
	# move the camera (and so the near set) there: park the car next to the crossing
	var a = npc.agents[0]
	npc._detach_node(a)
	# the walk edge leading to node best.a
	var lead := -1
	for id in npc.net.adj[best.a]:
		if npc.net.edges[id].kind == Sidewalks.WALK:
			lead = id
	if lead < 0:
		return {"ok": false, "note": "no lead edge"}
	var le = npc.net.edges[lead]
	var dir := 1 if le.b == best.a else -1
	var s0: float = le.length - 1.5 if dir > 0 else 1.5
	# arrive while the cars have green: the walker has to wait for their red
	for k in 600:
		if npc.crossing_signal(best) == 0:
			break
		await _wait(0.1)
	npc._set_on(a, lead, s0, dir)
	a.force_next = best.id
	a.no_dodge = true
	a.shaken = 100.0          # no stops on the way
	var log := []
	var waited_on_green := false
	var crossed_on := -1
	var entered := false
	for k in 900:             # up to 90 s (signal cycles)
		await _wait(0.1)
		var sig: int = npc.crossing_signal(best)
		if a.state == npc.WAIT_CROSS and sig != 2:
			waited_on_green = true
		if a.edge == best.id and a.state == npc.WALK and not entered:
			entered = true
			crossed_on = sig
		if entered and a.edge != best.id:
			break
		if a.edge != lead and a.edge != best.id:
			break
	a.no_dodge = false
	a.shaken = 0.0
	return {"ok": entered and crossed_on == 2 and waited_on_green, "waited_on_green": waited_on_green, "entered": entered, "signal_when_entered": crossed_on,
		"junction": best.junction, "all_crossings": npc.stats.crossings, "signalled": npc.stats.signalled_crossings,
		"red_violations": npc.stats.red_violations}


## Put a walker on the road, the car 26 m away at 60 km/h aimed at them.
func _dodge_test() -> Dictionary:
	_park_car()
	await _wait(0.5)
	var a = _near_agent(car.global_position)
	if a == null:
		return {"ok": false, "note": "no near walker"}
	var fwd := -car.global_basis.z if false else car.global_basis.z
	var target: Vector3 = car.global_position + fwd * 26.0
	_hold(a, target)
	await _wait(0.3)
	var d0: int = npc.stats.dodges + npc.stats.flinches
	car.input_brake = 0.0
	car.linear_velocity = fwd * 16.7
	var dodged := false
	var hit := false
	for k in 240:
		await get_tree().physics_frame
		car.linear_velocity = fwd * 16.7 + Vector3(0, car.linear_velocity.y, 0)
		if a.state == npc.DODGE:
			dodged = true
		if a.state == npc.DOWN:
			hit = true
	_park_car()
	await _wait(2.0)
	_release(a)
	return {"ok": dodged and npc.stats.dodges + npc.stats.flinches > d0, "dodged": dodged, "hit_anyway": hit}


## Pin a walker at p (standing in the road, facing across).
func _hold(a, p: Vector3) -> void:
	if a.state == npc.POI_STAY or a.state == npc.POI_GO:
		npc._leave_poi(a)
	a.state = npc.POI_STAY
	a.timer = 1000.0
	a.poi = {"face": (car.global_position - p).normalized(), "s": a.s, "lat": a.lat, "kind": "hold", "pos": p}
	a.v = 0.0
	a.displace = p - a.base
	a.displace.y = 0.0
	a.gy_ok = false


func _release(a) -> void:
	if a.state == npc.POI_STAY:
		npc._leave_poi(a)


func _ragdoll_test() -> Dictionary:
	_park_car()
	await _wait(0.5)
	var a = _near_agent(car.global_position)
	if a == null:
		return {"ok": false, "note": "no near walker"}
	var fwd: Vector3 = car.global_basis.z
	_hold(a, car.global_position + fwd * 9.0)
	a.no_dodge = true
	await _wait(0.4)
	var h0: int = npc.stats.hits
	car.input_brake = 0.0
	var p0: Vector3 = a.pos
	var went_down := false
	var max_disp := 0.0
	var bones := 0
	for k in 120:
		await get_tree().physics_frame
		if k % 15 == 0 and main.args.has("npc-debug"):
			print("ragdoll test k=%d car %s v %s agent %s state %d local %s" % [k, car.global_position, car.linear_velocity, a.pos, a.state, car.global_transform.affine_inverse() * (a.pos + Vector3.UP * 0.9)])
		if not went_down:
			car.linear_velocity = fwd * 12.5 + Vector3(0, car.linear_velocity.y, 0)
		if a.state == npc.DOWN:
			if not went_down:
				_park_car()
			went_down = true
			if a.node and a.node.rag and a.node.rag.sim:
				bones = a.node.rag.bones.size()
	var stood := false
	var t_down := 0.0
	for k in 140:
		await _wait(0.1)
		if a.state == npc.DOWN:
			t_down += 0.1
			max_disp = maxf(max_disp, a.pos.distance_to(p0))
		elif went_down:
			stood = true
			break
	a.no_dodge = false
	return {"ok": went_down and stood and bones >= 10 and max_disp > 0.8, "hit": npc.stats.hits > h0, "down": went_down,
		"physical_bones": bones, "thrown_m": snappedf(max_disp, 0.01), "down_s": snappedf(t_down, 0.1), "stood_up": stood,
		"getups": npc.stats.getups}


func _cap_test() -> Dictionary:
	_park_car()
	await _wait(1.0)
	var picked := []
	for i in 9:
		var a = _near_agent(car.global_position + Vector3(0, 0, 0), picked)
		if a == null:
			break
		picked.append(a)
	if picked.size() < 7:
		return {"ok": false, "note": "only %d near walkers" % picked.size()}
	var r0: int = npc.stats.ragdolls
	var s0: int = npc.stats.staggers
	for a in picked:
		npc.hit(a, Vector3(300, 250, 0), a.pos + Vector3.UP, null)
	await _wait(0.5)
	var now: int = npc._ragdolls.size()
	var rags: int = npc.stats.ragdolls - r0
	var stag: int = npc.stats.staggers - s0
	await _wait(12.0)
	var still: int = npc._ragdolls.size()
	return {"ok": now <= npc.max_ragdolls and rags <= npc.max_ragdolls and stag >= picked.size() - npc.max_ragdolls and still == 0,
		"hit": picked.size(), "ragdolls": rags, "staggers": stag, "ragdolls_at_once": now, "after_12s": still}


# ------------------------------------------------------------------ proof shots (windowed)
func _shot(dir: String, name: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img:
		img.save_png(dir.path_join(name + ".png"))
		print("npc shot: ", dir.path_join(name + ".png"))


func _cam_at(from: Vector3, to: Vector3, fov := 55.0) -> Camera3D:
	var c := Camera3D.new()
	c.fov = fov
	c.near = 0.05
	c.far = 1500.0
	main.add_child(c)
	c.global_position = from
	c.look_at(to, Vector3.UP)
	c.current = true
	return c


func _hide_ui(n: Node) -> void:
	for c in n.get_children():
		if c is CanvasLayer:
			c.visible = false
		_hide_ui(c)


func _shots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	if not await _ready_npc():
		get_tree().quit(1)
		return
	_park_car()
	_hide_ui(main)
	await _wait(6.0)
	# 0. the chase view: the street from behind the car
	await _shot(dir, "npc_chase_view")
	# 1. the busiest sidewalk near the car, eye height, looking along it
	var best = null
	var bn := 0
	for e in npc.net.edges:
		if e.kind != Sidewalks.WALK or e.pts[0].distance_to(car.global_position) > 90.0:
			continue
		var n := 0
		for a in npc.agents:
			if a.edge == e.id:
				n += 1
		if n > bn:
			bn = n
			best = e
	if best:
		var s: float = best.length * 0.15
		var p: Vector3 = best.pos_at(s)
		var d: Vector3 = best.dir_at(s)
		var c := _cam_at(p + Vector3.UP * 1.65 - Vector3(-d.z, 0, d.x) * 0.3, p + d * 20.0 + Vector3.UP * 1.2, 60.0)
		await _wait(3.0)
		await _shot(dir, "npc_street")
		c.queue_free()
	# 2. close-up of a walker (umbrella if any)
	var a = null
	for x in npc.agents:
		if x.node and x.state == npc.WALK and x.umbrella != "":
			a = x
			break
	if a == null:
		a = _near_agent(car.global_position)
	if a:
		for k in 30:
			var f := Vector3(sin(a.yaw), 0, cos(a.yaw))
			var c := _cam_at(a.pos + f * 2.6 + Vector3.UP * 1.55 + Vector3(f.z, 0, -f.x) * 0.6, a.pos + Vector3.UP * 1.2, 40.0)
			await get_tree().process_frame
			if k < 29:
				c.queue_free()
			else:
				await _shot(dir, "npc_closeup")
				c.queue_free()
	# 3. a ragdoll mid-fall
	a = _near_agent(car.global_position)
	if a:
		var fwd: Vector3 = car.global_basis.z
		_hold(a, car.global_position + fwd * 7.0)
		a.no_dodge = true
		await _wait(0.3)
		var side := Vector3(fwd.z, 0, -fwd.x)
		var c := _cam_at(car.global_position + fwd * 6.0 + side * 6.5 + Vector3.UP * 1.6, car.global_position + fwd * 7.0 + Vector3.UP * 0.8, 50.0)
		car.input_brake = 0.0
		for k in 300:
			await get_tree().physics_frame
			if a.state != npc.DOWN:
				car.linear_velocity = fwd * 11.0 + Vector3(0, car.linear_velocity.y, 0)
			else:
				break
		_park_car()
		await _wait(0.28)
		c.look_at(a.pos, Vector3.UP)
		await _shot(dir, "npc_ragdoll")
		await _wait(0.5)
		await _shot(dir, "npc_ragdoll_2")
		c.queue_free()
		a.no_dodge = false
	# 4. a crossing from above
	var cr = null
	var cd := INF
	for e in npc.net.edges:
		if e.kind == Sidewalks.CROSSING:
			var d: float = e.pts[1].distance_to(car.global_position)
			if d < cd:
				cd = d
				cr = e
	# prefer a crossing with someone on it (wait for one near the car)
	for k in 400:
		var found = null
		for x in npc.agents:
			if x.node and x.state == npc.WALK and npc.net.edges[x.edge].kind == Sidewalks.CROSSING and x.dist < 45.0:
				found = npc.net.edges[x.edge]
		if found:
			cr = found
			break
		await _wait(0.1)
	if cr:
		var m: Vector3 = (cr.pts[1] + cr.pts[2]) * 0.5
		var c := _cam_at(m + Vector3(7, 5, 7), m, 55.0)
		await _wait(0.6)
		await _shot(dir, "npc_crossing")
		c.queue_free()
	print("npc shots: ", JSON.stringify(npc.summary()))
	get_tree().quit(0)


func _bench() -> void:
	if not await _ready_npc():
		get_tree().quit(1)
		return
	_park_car()
	await _wait(4.0)
	var out := {}
	for mode in ["npc", "no_npc", "npc_again"]:
		var on: bool = mode != "no_npc"
		npc.visible = on
		npc.process_mode = Node.PROCESS_MODE_INHERIT if on else Node.PROCESS_MODE_DISABLED
		await _wait(2.0)
		npc.reset_prof()
		var t0 := Time.get_ticks_usec()
		var f0 := Engine.get_process_frames()
		await _wait(8.0)
		var fr := Engine.get_process_frames() - f0
		var secs := (Time.get_ticks_usec() - t0) / 1e6
		out[mode] = {"fps": snappedf(fr / secs, 0.1), "ms_per_frame": snappedf(secs * 1000.0 / maxf(fr, 1), 0.01),
			"npc_us": npc.summary().us_per_frame if on else {}}
	print("npc bench: ", JSON.stringify(out))
	if main.args.has("npc-out"):
		var f := FileAccess.open(String(main.args["npc-out"]), FileAccess.WRITE)
		f.store_string(JSON.stringify(out, "  "))
	get_tree().quit(0)
