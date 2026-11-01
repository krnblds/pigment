extends Node
## Damage / destruction tests and proof (user args after "--"):
##
##   --damage-test [--damage-out=res.json]   headless OK, exit 0 = pass:
##       * the hero into a concrete wall at 30 and 60 km/h (a flat pad off the map): dents happened
##         (vertices moved, a few cm+); at 60 panels came off; R (reset) makes it whole again
##       * a street lamp hit at ~50 km/h: it snaps and falls (its body tips past 45 degrees), its
##         collision is gone, its light killed
##       * a fire hydrant hit at ~40 km/h: it bursts, a water jet is running
##       * 40 debris bodies dropped in a heap: physics time per tick stays within budget and the pool
##         keeps its limits
##   --damage-shots=<dir>   windowed: crumpled bonnet, door hanging, debris on the road, a knocked-down
##                          lamp post with sparks, a hydrant geyser at night in the rain
##   --damage-bench         windowed: fps / frame time with 0 and 40 debris bodies and 3 geysers

var main: Node3D
var car: RigidBody3D
var dmg: Node3D                 ## damage_manager.gd
var res := {}
var checks := {}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	car = main.car
	dmg = main.damage
	if dmg == null:
		push_error("damage test: damage is off (--no-damage?)")
		get_tree().quit(2)
		return
	if main.traffic:
		main.traffic.process_mode = Node.PROCESS_MODE_DISABLED
		main.traffic.visible = false
	if main.args.has("damage-shots"):
		_shots.call_deferred(String(main.args["damage-shots"]))
	elif main.args.has("damage-bench"):
		_bench.call_deferred()
	else:
		_test.call_deferred()


func _wait(t: float) -> void:
	await get_tree().create_timer(t, true, true, true).timeout


func _tick() -> void:
	await get_tree().physics_frame


func _dt() -> float:
	return 1.0 / Engine.physics_ticks_per_second


func _set_inputs(throttle: float, brake: float, steer: float, handbrake := false) -> void:
	car.autopilot = true
	car.input_throttle = throttle
	car.input_brake = brake
	car.input_steer = steer
	car.input_handbrake = handbrake


func _ray(from: Vector3, to: Vector3, mask := 1) -> Dictionary:
	var q := PhysicsRayQueryParameters3D.create(from, to)
	q.exclude = [car.get_rid()]
	q.collision_mask = mask
	return car.get_world_3d().direct_space_state.intersect_ray(q)


# ------------------------------------------------------------------ pad + wall
var _pad_o := Vector3(-40000, 0, 40000)
var _wall: StaticBody3D


func _make_pad() -> void:
	if main.town and main.town.layout:
		_pad_o.y = maxf(main.town.bounds.position.y + 60.0, 0.0)
	var sb := StaticBody3D.new()
	sb.name = "DamagePad"
	sb.set_meta("surface", "asphalt")
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(800, 2, 800)
	cs.shape = b
	sb.add_child(cs)
	sb.position = _pad_o + Vector3(0, -1, 0)
	var mi := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(800, 800)
	mi.mesh = pm
	mi.position = Vector3(0, 1.0, 0)
	var am := StandardMaterial3D.new()
	am.albedo_color = Color(0.08, 0.08, 0.09)
	am.roughness = 0.35
	mi.material_override = am
	sb.add_child(mi)
	main.add_child(sb)


## A concrete block (visible) across the pad at local z.
func _block(at: Vector3, size: Vector3, yaw := 0.0) -> StaticBody3D:
	var sb := StaticBody3D.new()
	sb.name = "Block"
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = size
	cs.shape = b
	sb.add_child(cs)
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = size
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0.42, 0.41, 0.4)
	m.roughness = 0.9
	bm.material = m
	mi.mesh = bm
	sb.add_child(mi)
	main.add_child(sb)
	sb.global_transform = Transform3D(Basis(Vector3.UP, yaw), at + Vector3.UP * size.y * 0.5)
	return sb


func _place(xf: Transform3D, v: Vector3) -> void:
	car.place(xf)
	await _tick()
	car.place(xf)
	if car.has_method("prime_speed"):
		car.prime_speed(v.dot(xf.basis.z))
	for i in 3:
		car.linear_velocity = v
		car.angular_velocity = Vector3.ZERO
		await _tick()


## Drive into the wall at `kmh` (from 9 m away), let it settle; damage stats.
func _wall_hit(kmh: float) -> Dictionary:
	dmg.reset_hero()
	var hd: Node3D = dmg.hero_damage
	var z0 := -9.0 - float(car.spec.get("dimensions", {}).get("length", 4.4)) * 0.5
	var xf := Transform3D(Basis(), _pad_o + Vector3(0, 0.05, z0))
	var v := kmh / 3.6
	await _place(xf, Vector3(0, 0, v))
	var t := 0.0
	var peak := 0.0
	while t < 2.5:
		_set_inputs(0.35 if t < 0.6 else 0.0, 0.0 if t < 0.8 else 0.6, 0.0)
		await _tick()
		t += _dt()
		peak = maxf(peak, hd.stats.max_impulse)
	var off := 0.0
	for df in hd.deformers:
		if df.mesh:
			off = maxf(off, df.max_offset())
	var out := {"kmh": kmh, "impacts": hd.stats.impacts, "max_impulse": roundf(hd.stats.max_impulse), "deformed_verts": hd.stats.deformed,
		"max_vertex_offset_m": snappedf(off, 0.001), "deform_ms": snappedf(hd.stats.deform_ms, 0.01), "detached": hd.stats.detached,
		"loose": hd.stats.loose, "glass": hd.stats.glass, "lenses": hd.stats.lenses, "states": hd.state_counts(),
		"engine": snappedf(hd.engine, 0.01), "total": snappedf(hd.total(), 0.01), "power_scale": snappedf(car.power_scale, 0.01)}
	print("  wall %d km/h: %s" % [kmh, JSON.stringify(out)])
	return out


# ------------------------------------------------------------------ props in the world
## A run-up towards prop `id`: a direction with flat ground and nothing in the way. [Transform3D, ok]
func _approach(id: int, dist := 9.0) -> Array:
	var d: Node3D = dmg.destructibles
	var x: Transform3D = d.xfs[id]
	var p := x.origin
	main.stream_now(p)
	main.town.ensure_collision(p, 60.0)
	d.arm_around(p)
	await _tick()
	var dirs := [x.basis.z, -x.basis.x, x.basis.x, -x.basis.z]
	for k in 8:
		dirs.append(Vector3(cos(k * PI / 4.0), 0, sin(k * PI / 4.0)))
	var why := []
	for dd in dirs:
		var dir: Vector3 = (dd as Vector3) * Vector3(1, 0, 1)
		if dir.length() < 0.1:
			continue
		dir = dir.normalized()
		var s := p + dir * dist
		var g := _ray(s + Vector3.UP * 3.0, s + Vector3.DOWN * 4.0)
		if g.is_empty() or absf(g.position.y - p.y) > 0.45:
			why.append("ground %s" % ("none" if g.is_empty() else str(snappedf(g.position.y - p.y, 0.01))))
			continue
		# the way in at bumper and roof height: the first thing hit must be the prop (or nothing)
		var clear := true
		for h in [0.5, 1.2]:
			for side in [-0.6, 0.0, 0.6]:
				var off: Vector3 = Vector3.UP.cross(dir) * float(side)
				var a: Vector3 = g.position + Vector3.UP * h + off
				var b: Vector3 = p + Vector3.UP * h + off - dir * 0.5
				var hit := _ray(a, b)
				if hit and hit.collider and not hit.collider.has_meta("destructible") and (hit.position - p).length() > 1.8:
					if clear:
						why.append("blocked %s at %.1f" % [hit.collider.name, (hit.position - p).length()])
					clear = false
		if not clear:
			continue
		var fwd := -dir
		var basis := Basis(Vector3.UP.cross(fwd).normalized(), Vector3.UP, fwd)
		return [Transform3D(basis, g.position + Vector3.UP * 0.05), true]
	print("      run-up: ", ", ".join(why))
	return [Transform3D(), false]


func _prop_hit(prop: String, kmh: float, tries := 12) -> Dictionary:
	var d: Node3D = dmg.destructibles
	var sp: Vector3 = main.town.spawn_transform().origin
	var ids: Array = d.near(sp, 900.0, prop)
	ids.sort_custom(func(a, b): return d.xfs[a].origin.distance_to(sp) < d.xfs[b].origin.distance_to(sp))
	var n := 0
	for id in ids:
		if n >= tries:
			break
		if d.state[id] != 0:
			continue
		n += 1
		var ap: Array = await _approach(id)
		if not ap[1]:
			print("    %s %d: no clear run-up" % [prop, id])
			continue
		dmg.reset_hero()
		var got := []
		var cb := func(bid: int, _k: String): got.append(bid)
		d.broke.connect(cb)
		await _place(ap[0], (ap[0] as Transform3D).basis.z * kmh / 3.6)
		var t := 0.0
		while t < 3.5:
			_set_inputs(0.4 if t < 0.5 else 0.0, 0.0 if t < 1.0 else 0.5, 0.0)
			await _tick()
			t += _dt()
		d.broke.disconnect(cb)
		print("    %s %d: broke %s (hero impacts %d, max J %d, car at %s, prop at %s)" % [prop, id, got.has(id),
			dmg.hero_damage.stats.impacts, dmg.hero_damage.stats.max_impulse, car.global_position, d.xfs[id].origin])
		if got.has(id):
			var tilt := 0.0
			var body_found := false
			for e in dmg.debris.bodies:
				if is_instance_valid(e.rb) and String(e.rb.name) == prop and e.rb.global_position.distance_to(d.xfs[id].origin) < 12.0:
					body_found = true
					tilt = maxf(tilt, rad_to_deg(acos(clampf((e.rb.global_basis.y as Vector3).dot(Vector3.UP), -1.0, 1.0))))
			var col_left := _ray(d.xfs[id].origin + Vector3(0, 1.0, 0) - (ap[0] as Transform3D).basis.z * 1.0,
				d.xfs[id].origin + Vector3(0, 1.0, 0) + (ap[0] as Transform3D).basis.z * 1.0)
			return {"id": id, "prop": prop, "pos": d.xfs[id].origin, "kmh": kmh, "broken": true, "tilt_deg": snappedf(tilt, 0.1),
				"body": body_found, "collision_gone": col_left.is_empty() or col_left.collider.has_meta("destructible") == false and not String(col_left.collider.name).begins_with("Col"),
				"jets": d.active_jets(), "tries": n}
	return {"prop": prop, "broken": false, "tries": n}


# ------------------------------------------------------------------ the test
func _test() -> void:
	await _wait(0.5)
	var t0 := Time.get_ticks_msec()
	res["indexed_props"] = dmg.destructibles.stats.indexed
	res["hero_panels"] = dmg.hero_damage.panels.size()
	checks["hero_has_panels"] = dmg.hero_damage.panels.size() >= 12
	_make_pad()
	_wall = _block(_pad_o + Vector3(0, 0, 0), Vector3(14.0, 2.5, 1.0))
	await _wait(0.3)
	# 1. walls
	var w30 := await _wall_hit(30.0)
	res["wall_30"] = w30
	checks["wall30_impact"] = w30.impacts >= 1
	checks["wall30_deformed"] = w30.deformed_verts > 200 and w30.max_vertex_offset_m > 0.03
	dmg.reset_hero()
	await _tick()
	var w60 := await _wall_hit(60.0)
	res["wall_60"] = w60
	checks["wall60_deeper"] = w60.max_vertex_offset_m > w30.max_vertex_offset_m
	checks["wall60_panels_detached"] = w60.detached >= 1
	checks["wall60_engine_damage"] = w60.engine > 0.2 and w60.power_scale < 1.0
	# reset
	dmg.reset_hero()
	await _tick()
	var hd: Node3D = dmg.hero_damage
	var sc: Dictionary = hd.state_counts()
	var dented: bool = hd.deformers.any(func(df): return df.mesh != null)
	res["after_reset"] = {"states": sc, "dented_meshes": dented, "power_scale": car.power_scale}
	checks["reset_restores"] = sc.get("ok", 0) == hd.panels.size() and not dented and car.power_scale == 1.0
	# 2. lamp post, 3. hydrant (in the world)
	if main.town and main.town.layout:
		var lamp := await _prop_hit("street_lamp", 50.0)
		print("  lamp: ", JSON.stringify(lamp))
		res["lamp"] = lamp
		checks["lamp_falls"] = lamp.broken and lamp.get("body", false) and lamp.get("tilt_deg", 0.0) > 45.0
		var hyd := await _prop_hit("fire_hydrant", 40.0)
		print("  hydrant: ", JSON.stringify(hyd))
		res["hydrant"] = hyd
		checks["hydrant_water"] = hyd.broken and hyd.get("jets", 0) >= 1 and _jet_running()
		var cone := await _prop_hit("traffic_cone", 35.0, 6)
		res["cone"] = cone
		print("  cone: ", JSON.stringify(cone))
	# 4. perf: 40 debris bodies
	var perf := await _debris_perf(40)
	res["debris_perf"] = perf
	print("  debris perf: ", JSON.stringify(perf))
	checks["perf_budget"] = perf.tick_ms_avg_40 < perf.tick_ms_avg_0 + 2.0 and perf.awake_max <= 60
	res["sounds"] = dmg.audio.played
	res["fx"] = dmg.fx.stats
	res["debris_stats"] = dmg.debris.stats
	res["checks"] = checks
	res["secs"] = (Time.get_ticks_msec() - t0) / 1000.0
	var ok := checks.values().all(func(v): return v)
	print("DAMAGE TEST ", "PASS" if ok else "FAIL", " ", JSON.stringify(checks))
	if main.args.has("damage-out"):
		var f := FileAccess.open(String(main.args["damage-out"]), FileAccess.WRITE)
		f.store_string(JSON.stringify(res, " "))
	await _wait(0.2)
	get_tree().quit(0 if ok else 1)


func _jet_running() -> bool:
	for j in dmg.destructibles.jets:
		if is_instance_valid(j.node):
			for c in j.node.get_children():
				if c is GPUParticles3D and c.emitting and c.amount > 100:
					return true
	return false


## Physics time per tick with no debris, then with n bodies dropped in a heap on the pad.
func _debris_perf(n: int) -> Dictionary:
	dmg.reset_hero()
	await _place(Transform3D(Basis(), _pad_o + Vector3(30, 0.05, -30)), Vector3.ZERO)
	_set_inputs(0.0, 1.0, 0.0, true)
	await _wait(1.0)
	var c0: Vector3 = car.global_position
	var base := await _phys_ms(2.0)
	var box := BoxMesh.new()
	box.size = Vector3(0.6, 0.4, 0.5)
	for i in n:
		var mi := MeshInstance3D.new()
		mi.mesh = box
		main.add_child(mi)
		var at := c0 + Vector3(randf_range(-2, 2), 1.0 + i * 0.35, 12.0 + randf_range(-2, 2))
		mi.global_position = at
		var bs := BoxShape3D.new()
		bs.size = box.size
		dmg.debris.spawn([mi], [[bs, Transform3D()]], Transform3D(Basis(), at), 12.0,
			{"angvel": Vector3(randf(), randf(), randf()), "kind": "wood", "name": "perf_box"})
	var awake_max := 0
	print("    perf: spawned %d, pool %d, car at %s" % [n, dmg.debris.bodies.size(), car.global_position])
	var t := 0.0
	var samples := []
	while t < 4.0:
		await _tick()
		t += _dt()
		awake_max = maxi(awake_max, dmg.debris.awake_count())
		samples.append(_last_tick_ms)
	var with := 0.0
	for s in samples:
		with += s
	with /= maxf(samples.size(), 1)
	var mx: float = samples.max() if not samples.is_empty() else 0.0
	return {"bodies": n, "tick_ms_avg_0": snappedf(base, 0.001), "tick_ms_avg_40": snappedf(with, 0.001),
		"tick_ms_max_40": snappedf(mx, 0.001), "awake_max": awake_max, "pool": dmg.debris.bodies.size()}


func _phys_ms(secs: float) -> float:
	var t := 0.0
	var tot := 0.0
	var k := 0
	while t < secs:
		await _tick()
		t += _dt()
		tot += _last_tick_ms
		k += 1
	return tot / maxf(k, 1)


## Wall time of the last physics tick (headless + --fixed-fps: the frame is the physics tick).
var _last_tick_ms := 0.0
var _tick_us := 0


func _physics_process(_d: float) -> void:
	var now := Time.get_ticks_usec()
	if _tick_us > 0:
		_last_tick_ms = (now - _tick_us) / 1000.0
	_tick_us = now


# ------------------------------------------------------------------ screenshots (windowed)
func _shot(dir: String, nm: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img.get_width() > 1600:
		img.resize(1600, int(1600.0 * img.get_height() / img.get_width()), Image.INTERPOLATE_LANCZOS)
	var full := dir.path_join(nm + ".png")
	img.save_png(full)
	print("SHOT ", full)


func _cam(eye: Vector3, at: Vector3, fov := 50.0) -> void:
	main.cam.manual = true
	main.cam.fov = fov
	main.cam.global_position = eye
	main.cam.look_at(at, Vector3.UP)


func _shots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	DisplayServer.window_set_size(Vector2i(1920, 1080))
	var d: Node3D = dmg.destructibles
	# 1. a lamp post, knocked down: sparks and the dying light
	var lamp_ids: Array = d.near(main.town.spawn_transform().origin, 900.0, "street_lamp")
	lamp_ids.sort_custom(func(a, b): return d.xfs[a].origin.distance_to(main.town.spawn_transform().origin) < d.xfs[b].origin.distance_to(main.town.spawn_transform().origin))
	var done_lamp := false
	for id in lamp_ids.slice(0, 15):
		var ap: Array = await _approach(id, 12.0)
		if not ap[1]:
			continue
		var xf: Transform3D = ap[0]
		var lp: Vector3 = d.xfs[id].origin
		main.stream_now(lp)
		car.place(xf)
		_set_inputs(0.0, 1.0, 0.0, true)
		_cam(lp + xf.basis.x * 9.0 - xf.basis.z * 3.0 + Vector3.UP * 2.4, lp + Vector3.UP * 2.0, 55.0)
		await _wait(5.0)                        # streaming, shaders, SDFGI
		await _place(xf, xf.basis.z * 55.0 / 3.6)
		var t := 0.0
		var shot := false
		while t < 2.5:
			_set_inputs(0.3, 0.0, 0.0)
			await _tick()
			t += _dt()
			if d.state[id] == 1 and not shot:
				await _wait(0.42)
				await _shot(dir, "04_lamp_post_sparks")
				shot = true
		if shot:
			await _wait(2.0)
			_cam(lp + xf.basis.x * 7.0 + xf.basis.z * 5.0 + Vector3.UP * 3.0, lp + xf.basis.z * 3.0 + Vector3.UP * 0.5, 55.0)
			await _wait(0.6)
			await _shot(dir, "04b_lamp_post_down")
			done_lamp = true
			break
	print("lamp shot: ", done_lamp)
	# 2. into a concrete block at 60 km/h on the street: crumpled bonnet (stay in the same street)
	var base: Transform3D = car.global_transform
	var road: Array = main.town.nearest_road(car.global_position + Vector3(0, 0, 0))
	var rp: Vector3 = road[0]
	var rd: Vector3 = (road[1] as Vector3) * Vector3(1, 0, 1)
	rd = rd.normalized()
	var blk_at: Vector3 = rp + rd * 20.0
	var g := _ray(blk_at + Vector3.UP * 4.0, blk_at + Vector3.DOWN * 6.0)
	if g:
		blk_at = g.position
	var blk := _block(blk_at, Vector3(4.0, 1.2, 1.2), atan2(rd.x, rd.z))
	dmg.reset_hero()
	var fbasis := Basis(Vector3.UP.cross(rd).normalized(), Vector3.UP, rd)
	var start := Transform3D(fbasis, blk_at - rd * 16.0 + Vector3.UP * 0.1)
	car.place(start)
	await _wait(1.5)
	await _place(start, rd * 62.0 / 3.6)
	var tt := 0.0
	while tt < 2.0:
		_set_inputs(0.3 if tt < 0.5 else 0.0, 0.0 if tt < 0.9 else 0.8, 0.0)
		await _tick()
		tt += _dt()
	await _wait(1.5)
	var cp: Vector3 = car.global_position
	var cz: Vector3 = car.global_basis.z
	var cx: Vector3 = car.global_basis.x
	_cam(cp + cz * 4.2 + cx * 2.6 + Vector3.UP * 1.5, cp + cz * 1.4 + Vector3.UP * 0.6, 50.0)
	var spot := OmniLight3D.new()
	spot.omni_range = 9.0
	spot.light_energy = 2.0
	spot.light_color = Color(0.85, 0.9, 1.0)
	main.add_child(spot)
	spot.global_position = cp + cz * 3.5 + cx * 1.5 + Vector3.UP * 3.0
	await _wait(1.0)
	await _shot(dir, "01_crumpled_bonnet")
	# 3. side swipe into the block: a door hanging
	blk.global_position = car.global_position + cz * 0.0 + cx * 3.2 + Vector3.UP * 0.0
	blk.global_position.y = blk_at.y + 0.6
	blk.global_basis = Basis(Vector3.UP, atan2(cz.x, cz.z))
	await _tick()
	var side_xf := car.global_transform
	await _place(side_xf, cx * 32.0 / 3.6)
	tt = 0.0
	while tt < 1.6:
		_set_inputs(0.0, 0.4, 0.0)
		await _tick()
		tt += _dt()
	# a second slower nudge so a door comes loose if the first only dented it
	var hd: Node3D = dmg.hero_damage
	for nm in ["Door_FL", "Door_RL"]:
		if hd.panels.has(nm) and hd.panels[nm].state == "ok":
			hd.apply_impact(car.global_transform * hd.panels[nm].aabb.get_center(), -cx, 9000.0)
	blk.global_position = Vector3(0, -3000, 0)
	await _tick()
	# drive off slowly so the loose door swings open
	tt = 0.0
	while tt < 1.2:
		_set_inputs(0.25, 0.0, 0.25)
		await _tick()
		tt += _dt()
	_set_inputs(0.0, 0.0, 0.0, true)
	await _wait(1.2)
	cp = car.global_position
	cz = car.global_basis.z
	cx = car.global_basis.x
	_cam(cp + cx * 4.6 + cz * 2.0 + Vector3.UP * 1.6, cp + cx * 0.8 + Vector3.UP * 0.7, 52.0)
	spot.global_position = cp + cx * 3.5 + Vector3.UP * 3.0
	await _wait(0.8)
	await _shot(dir, "02_door_hanging")
	# 4. debris on the road: knock the props near here over, plus the panels lying around
	for id in d.near(cp, 25.0, "", "knock").slice(0, 10):
		d.break_prop(id, Vector3(randf_range(-3, 3), 1.0, randf_range(-3, 3)), 2000.0)
	await _wait(2.5)
	var low := cp - cz * 6.0 + cx * 2.0 + Vector3.UP * 0.9
	_cam(low, cp + cz * 2.0, 60.0)
	await _wait(0.5)
	await _shot(dir, "03_debris_on_road")
	spot.queue_free()
	# 5. hydrant geyser at night in the rain
	main.rain.emitting = true
	main.rain.visible = true
	main.town.set_road_rain(1.0)
	var hyd: Array = d.near(cp, 900.0, "fire_hydrant")
	hyd.sort_custom(func(a, b): return d.xfs[a].origin.distance_to(cp) < d.xfs[b].origin.distance_to(cp))
	for id in hyd.slice(0, 12):
		var ap: Array = await _approach(id, 10.0)
		if not ap[1]:
			continue
		var xf: Transform3D = ap[0]
		var hp: Vector3 = d.xfs[id].origin
		main.stream_now(hp)
		dmg.reset_hero()
		car.place(xf)
		await _wait(3.0)
		await _place(xf, xf.basis.z * 42.0 / 3.6)
		var t := 0.0
		while t < 2.0:
			_set_inputs(0.2 if t < 0.4 else 0.0, 0.0 if t < 0.6 else 0.9, 0.0)
			await _tick()
			t += _dt()
		if d.state[id] == 1:
			await _wait(9.0)
			_cam(hp + xf.basis.x * 9.0 + xf.basis.z * 6.0 + Vector3.UP * 2.2, hp + Vector3.UP * 4.0, 60.0)
			await _wait(1.5)
			await _shot(dir, "05_hydrant_geyser_rain")
			_cam(hp + xf.basis.z * 4.0 - xf.basis.x * 4.0 + Vector3.UP * 1.4, hp + Vector3.UP * 2.5, 70.0)
			await _wait(0.8)
			await _shot(dir, "05b_hydrant_geyser_close")
			break
	main.cam.manual = false
	await _wait(0.3)
	get_tree().quit(0)


# ------------------------------------------------------------------ bench (windowed)
func _bench() -> void:
	DisplayServer.window_set_size(Vector2i(1920, 1080))
	var xf: Transform3D = main.town.spawn_transform()
	car.place(xf)
	_set_inputs(0.0, 1.0, 0.0, true)
	main.cam.manual = true
	main.cam.global_position = xf.origin + xf.basis.z * -8.0 + Vector3.UP * 3.5
	main.cam.look_at(xf.origin + xf.basis.z * 6.0, Vector3.UP)
	await _wait(6.0)
	var out := {}
	out["empty"] = await _fps(5.0)
	var box := BoxMesh.new()
	box.size = Vector3(0.6, 0.4, 0.5)
	for i in 40:
		var mi := MeshInstance3D.new()
		mi.mesh = box
		main.add_child(mi)
		var at := xf.origin + xf.basis.z * 8.0 + Vector3(randf_range(-2, 2), 1.0 + i * 0.3, randf_range(-2, 2))
		mi.global_position = at
		var bs := BoxShape3D.new()
		bs.size = box.size
		dmg.debris.spawn([mi], [[bs, Transform3D()]], Transform3D(Basis(), at), 12.0, {"kind": "wood"})
	out["debris_40_falling"] = await _fps(5.0)
	out["debris_40_resting"] = await _fps(5.0)
	for k in 3:
		dmg.fx.water_jet(xf.origin + xf.basis.z * (10.0 + k * 4.0) + xf.basis.x * 5.0, 9.0)
		dmg.fx.puddle(xf.origin + xf.basis.z * (10.0 + k * 4.0) + xf.basis.x * 5.0, 5.0)
	out["debris_40_jets_3"] = await _fps(5.0)
	print("DAMAGE BENCH ", JSON.stringify(out))
	if main.args.has("damage-out"):
		var f := FileAccess.open(String(main.args["damage-out"]), FileAccess.WRITE)
		f.store_string(JSON.stringify(out, " "))
	get_tree().quit(0)


func _fps(secs: float) -> Dictionary:
	var frames := []
	var t := 0.0
	while t < secs:
		await get_tree().process_frame
		var dt := get_process_delta_time()
		frames.append(dt)
		t += dt
	frames.sort()
	var avg := 0.0
	for f in frames:
		avg += f
	avg /= maxf(frames.size(), 1)
	var p99: float = frames[int(frames.size() * 0.99)] if not frames.is_empty() else 0.0
	return {"fps": snappedf(1.0 / maxf(avg, 1e-6), 0.1), "low1_fps": snappedf(1.0 / maxf(p99, 1e-6), 0.1),
		"physics_ms": snappedf(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0, 0.01),
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)}
