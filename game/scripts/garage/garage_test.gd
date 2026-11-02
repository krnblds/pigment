extends Node
## --showroom-test (headless OK; add --fixed-fps 120):
##   1. opens the garage (showroom shortcut), cycles every fleet vehicle and every livery: the car is rebuilt
##      with that vehicle's physics, the Body material is the livery's (fleet_variants swap)
##   2. applies every customisation category and asserts its effect (paint / finish / tint shader params,
##      underglow lights, rim meshes + colour, ride height + camber, kit parts, perf factors on the physics
##      params, plate text), then that the save file round-trips and a car built from it matches
##   3. drives out and drives every vehicle (with the custom kit on the last) a few metres in the city
##   4. drive-in: puts the car on the road in front of each garage and drives it through the door: the
##      trigger must open the garage; leaving puts the car outside the door facing the road
## Prints SHOWROOMTEST {...} and PASS / FAIL; exit code 0 = pass.
## --showroom-shot=<dir>: garage exterior from the road, interior wide + customised close-ups, the menu.

const Fleet := preload("res://scripts/garage/fleet.gd")
const Tuning := preload("res://scripts/garage/tuning.gd")

var main: Node3D
var g: Node                     ## garage.gd
var fails: Array = []
var res := {}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	g = main.garage
	g.save_path = String(main.args.get("garage-save", "user://garage_test.json"))
	if main.args.has("showroom-shot"):
		_shots.call_deferred(String(main.args["showroom-shot"]))
	else:
		_run.call_deferred()


func _wait(t: float) -> void:
	await get_tree().create_timer(t, true, false, true).timeout


func _frames(n: int) -> void:
	for i in n:
		await get_tree().process_frame


func _check(name: String, ok: bool, info = null) -> bool:
	if not ok:
		fails.append(name + ("" if info == null else " " + str(info)))
		printerr("SHOWROOMTEST fail: ", name, " ", "" if info == null else str(info))
	return ok


func _body(car: Node) -> MeshInstance3D:
	var vis := car.get_node_or_null("Visual")
	if vis == null:
		return null
	for mi in vis.find_children("*", "MeshInstance3D", true, false):
		if String(mi.name) == "Body":
			return mi
	return null


func _open() -> void:
	g.open(null)
	while not g.inside or g.busy:
		await get_tree().process_frame


func _leave(keep: bool) -> void:
	g.leave(keep)
	while g.inside or g.busy:
		await get_tree().process_frame


func _drive(sec: float, steer_to = null) -> float:
	var car: RigidBody3D = main.car
	var p0 := car.global_position
	car.autopilot = true
	var t := 0.0
	while t < sec:
		car.input_throttle = 0.7
		car.input_brake = 0.0
		car.input_handbrake = false
		if steer_to != null:
			var to: Vector3 = steer_to - car.global_position
			to.y = 0.0
			var ang := car.global_basis.z.signed_angle_to(to.normalized(), Vector3.UP)
			car.input_steer = clampf(ang * 2.5, -1.0, 1.0)
		else:
			car.input_steer = 0.0
		await get_tree().physics_frame
		t += 1.0 / Engine.physics_ticks_per_second
		if steer_to != null and g.inside:
			break
	car.input_throttle = 0.0
	car.input_brake = 1.0
	for i in 30:
		await get_tree().physics_frame
	car.input_brake = 0.0
	car.autopilot = false
	return car.global_position.distance_to(p0)


func _run() -> void:
	var t0 := Time.get_ticks_msec()
	await _frames(10)
	var cat := Fleet.catalogue()
	res["vehicles"] = cat.size()
	res["garages"] = g.garages.size()
	_check("fleet_found", cat.size() >= 1, cat.size())
	if main.map_name == "world":
		_check("three_garages", g.garages.size() == 3, g.garages.size())
	await _open()
	_check("opened", g.inside and g.interior != null and get_viewport().get_camera_3d() == g.cam)
	# ---------------------------------------------------------------- 1. vehicles x liveries
	var liveries := 0
	var per := {}
	for vi in cat.size():
		var v: Dictionary = cat[vi]
		var c := Tuning.default_cfg(v.id)
		g.set_value("cfg", c)
		await _frames(2)
		var car: RigidBody3D = main.car
		var ok := _check("built_" + v.id, car != null and car.wheels.size() == 4 and String(car.P.get("id", "")) == v.id,
			car.P.get("id", "") if car else null)
		_check("parked_on_turntable_" + v.id, car.freeze and car.global_position.distance_to(g.interior.car_transform().origin) < 0.05)
		var swapped := 0
		for var_i in v.variants.size():
			var vn: String = v.variants[var_i].name
			g.cfg.variant = vn
			Tuning.apply(car, g.cfg)
			var body := _body(car)
			var want: Material = null
			var table: Dictionary = Fleet.variant_table(v.glb, v.id, v.default_variant)
			if table.has(vn) and table[vn].has("Body"):
				want = table[vn]["Body"][0]
			var got: Material = body.get_active_material(0) if body else null
			var same: bool = got != null and want != null and (got == want or (got is BaseMaterial3D and want is BaseMaterial3D
				and got.albedo_texture == want.albedo_texture and got.resource_name == want.resource_name))
			if _check("livery_%s_%s" % [v.id, vn], same and String(car.get_meta("livery", "")) == vn,
					[got.resource_name if got else null, want.resource_name if want else null]):
				swapped += 1
			liveries += 1
		per[v.id] = {"variants": v.variants.size(), "swapped": swapped, "mass": car.mass if ok else 0.0}
	res["liveries"] = liveries
	res["per_vehicle"] = per
	# ---------------------------------------------------------------- 2. customisation
	var vid: String = "tsubame" if not Fleet.find("tsubame").is_empty() else cat[0].id
	g.set_value("cfg", Tuning.default_cfg(vid))
	await _frames(2)
	var car: RigidBody3D = main.car
	var base_peak := float(car.P.engine.peak_torque)
	var base_brake := float(car.P.brakes.max_torque)
	var base_mu := float(car.wheels[0].mu)
	var base_k := float(car.wheels[0].k)
	var base_rest_y := float(car.wheels[0].rest.y)
	var base_rim_mesh: Mesh = car.wheels[0].spin.get_child(0).mesh if car.wheels[0].spin.get_child_count() else null
	# paint, finish, tint
	g.set_value("paint_color", Color(1.0, 0.1, 0.55))
	g.step("finish", 1)                      # pearl
	g.step("finish", 1)                      # chrome
	g.step("tint", 1)
	g.step("tint", 1)
	var body := _body(car)
	var pm: Material = body.get_active_material(0) if body else null
	var cats := {}
	cats["paint"] = _check("paint_shader", pm is ShaderMaterial and bool(pm.get_shader_parameter("paint_on"))
		and Color(pm.get_shader_parameter("paint_color")).is_equal_approx(Color(1.0, 0.1, 0.55)), pm)
	cats["finish"] = _check("finish_chrome", pm is ShaderMaterial and int(pm.get_shader_parameter("finish")) == 2 and String(g.cfg.paint.finish) == "chrome")
	cats["tint"] = _check("window_tint", pm is ShaderMaterial and is_equal_approx(float(pm.get_shader_parameter("window_tint")), 0.6))
	_check("paint_keeps_livery_textures", pm is ShaderMaterial and pm.get_shader_parameter("texture_albedo") != null
		and pm.get_shader_parameter("texture_albedo") == (pm.get_meta("base") as BaseMaterial3D).albedo_texture)
	# underglow
	g.step("underglow", 1)
	var ug := car.get_node_or_null("Underglow")
	var lights := ug.find_children("*", "OmniLight3D", true, false) if ug else []
	cats["underglow"] = _check("underglow", ug != null and ug.visible and lights.size() >= 2
		and (lights[0] as OmniLight3D).light_color.is_equal_approx(Tuning.col(g.cfg.underglow.color)))
	# rims: style from another vehicle + colour
	g.step("rims", 1)
	await _frames(1)
	var rim_mesh: Mesh = car.wheels[0].spin.get_child(0).mesh if car.wheels[0].spin.get_child_count() else null
	var donor := String(g.cfg.rims.style)
	cats["rims"] = _check("rim_style", donor != "stock" and rim_mesh != null and rim_mesh != base_rim_mesh, [donor, rim_mesh])
	g.step("rim_color", 1)
	var rmi: MeshInstance3D = car.wheels[0].spin.get_child(0) if car.wheels[0].spin.get_child_count() else null
	var rm: Material = rmi.get_active_material(0) if rmi else null
	cats["rim_color"] = _check("rim_color", rm is ShaderMaterial and int(rm.get_shader_parameter("mask_mode")) == 1 and bool(rm.get_shader_parameter("paint_on")))
	# stance
	g.step("drop", 1)
	g.step("drop", 1)
	g.step("camber", 1)
	g.step("camber", 1)
	var camber_node := car.wheels[0].pivot.get_node_or_null("Camber") as Node3D
	cats["stance"] = _check("ride_height", is_equal_approx(float(car.wheels[0].rest.y), base_rest_y + 0.04), [car.wheels[0].rest.y, base_rest_y]) \
		and _check("camber", camber_node != null and absf(rad_to_deg(absf(camber_node.rotation.z)) - 3.0) < 0.01 and car.wheels[0].spin.get_parent() == camber_node)
	# kit
	for k in ["lip", "wing", "lightbar"]:
		g.step(k, 1)
	var kit := car.get_node_or_null("Kit")
	cats["kit"] = _check("kit_parts", kit != null and kit.get_node_or_null("Lip") != null and kit.get_node_or_null("Wing") != null
		and kit.get_node_or_null("LightBar") != null)
	# performance
	for k in ["engine", "brakes", "tyres", "suspension"]:
		g.step(k, 1)
		g.step(k, 1)
		g.step(k, 1)
	var F := Fleet.TuningFactors
	var fc := 1.0 + 3.0 * 0.008
	cats["perf"] = _check("perf_engine", is_equal_approx(float(car.P.engine.peak_torque), base_peak * F.ENGINE[3]), [car.P.engine.peak_torque, base_peak]) \
		and _check("perf_brakes", is_equal_approx(float(car.P.brakes.max_torque), base_brake * F.BRAKES[3])) \
		and _check("perf_tyres", absf(float(car.wheels[0].mu) - base_mu * F.TYRES[3] * fc) < 1e-4, [car.wheels[0].mu, base_mu]) \
		and _check("perf_suspension", is_equal_approx(float(car.wheels[0].k), base_k * F.SUSPENSION[3])) \
		and _check("perf_lut_reset", car._curve_lut.is_empty())
	# applying twice must not compound
	Tuning.apply(car, g.cfg)
	_check("perf_idempotent", is_equal_approx(float(car.P.engine.peak_torque), base_peak * F.ENGINE[3]))
	# plate
	g.set_value("plate", "unplug-77")
	var plates := car.get_node_or_null("Plates")
	var lbl := plates.find_children("*", "Label3D", true, false) if plates else []
	cats["plate"] = _check("plate", lbl.size() == 2 and (lbl[0] as Label3D).text == "UNPLUG-77")
	# save round trip + launch path
	g.leave(true)
	while g.inside or g.busy:
		await get_tree().process_frame
	var loaded := Tuning.load_cfg(g.save_path)
	cats["save"] = _check("save_roundtrip", JSON.stringify(loaded) == JSON.stringify(Tuning.normalized(g.cfg)), [loaded, g.cfg])
	var c2: RigidBody3D = g.build_car(loaded)
	Tuning.apply(c2, loaded)
	var b2 := _body(c2)
	var pm2: Material = b2.get_active_material(0) if b2 else null
	_check("saved_car_rebuilds", is_equal_approx(float(c2.P.engine.peak_torque), float(main.car.P.engine.peak_torque))
		and pm2 is ShaderMaterial and int(pm2.get_shader_parameter("finish")) == 2 and c2.get_node_or_null("Kit/Wing") != null)
	c2.queue_free()
	res["categories"] = cats
	# ---------------------------------------------------------------- 3. drive every vehicle a few metres
	var drives := {}
	for vi in cat.size():
		var v: Dictionary = cat[vi]
		await _open()
		var c: Dictionary = Tuning.default_cfg(v.id) if vi < cat.size() - 1 else g.cfg.duplicate(true)
		c.vehicle = v.id
		c.variant = v.variants[v.variants.size() - 1].name
		g.set_value("cfg", c)
		await _frames(2)
		await _leave(true)
		await _wait(0.4)
		_check("unparked_" + v.id, not main.car.freeze and main.car.collision_layer != 0)
		var d := await _drive(2.5)
		drives[v.id] = snappedf(d, 0.01)
		_check("drive_" + v.id, d > 3.0, d)
	res["drive_m"] = drives
	# ---------------------------------------------------------------- 4. drive into each garage
	var ins := {}
	for gar in g.garages:
		var xf: Transform3D = gar.approach_transform(16.0)
		main.stream_now(xf.origin)
		main.town.ensure_collision(xf.origin, 40.0)
		await _frames(3)
		main.car.place(xf)
		main.cam.snap()
		await _wait(0.5)
		var target: Vector3 = gar.global_transform * Vector3(0, 0.5, gar.size.z * 0.5 - 3.0)
		# this checks the garage trigger, not traffic: keep passing cars out of the approach
		if main.traffic and main.traffic.has_method("clear_around"):
			main.traffic.clear_around(xf.origin.lerp(target, 0.5), 30.0)
		if main.npc and main.npc.has_method("clear_around"):
			main.npc.clear_around(xf.origin.lerp(target, 0.5), 25.0)
		var d := await _drive(9.0, target)
		var t_in := 0.0
		while (g.busy or not g.inside) and t_in < 3.0:
			await get_tree().process_frame
			t_in += get_process_delta_time()
		var entered: bool = g.inside and g.current == gar
		if not entered:
			var car: RigidBody3D = main.car
			var q := PhysicsRayQueryParameters3D.create(car.global_position + Vector3.UP * 0.6, car.global_position + Vector3.UP * 0.6 + car.global_basis.z * 4.0)
			q.exclude = [car.get_rid()]
			var hit := car.get_world_3d().direct_space_state.intersect_ray(q)
			print("garage test: stopped short of %s; ahead: %s" % [gar.data.id, (str(hit.collider.name) + " " + str(hit.collider.get_parent().name)) if hit else "nothing"])
		_check("drive_in_" + String(gar.data.id), entered, d)
		if entered:
			await _leave(true)
			await _wait(0.3)
			var fwd: Vector3 = main.car.global_basis.z
			var outside: bool = not gar.trigger.overlaps_body(main.car)
			var facing: bool = fwd.dot(gar.global_basis.z) > 0.9
			_check("exit_facing_road_" + String(gar.data.id), outside and facing, [outside, fwd.dot(gar.global_basis.z)])
			# and it can drive off onto the road
			var dd := await _drive(2.0)
			_check("exit_drive_" + String(gar.data.id), dd > 2.0, dd)
		ins[gar.data.id] = entered
	res["drive_in"] = ins
	res["ms"] = Time.get_ticks_msec() - t0
	res["pass"] = fails.is_empty()
	res["fails"] = fails
	print("SHOWROOMTEST ", JSON.stringify(res))
	print("SHOWROOMTEST %s: %d vehicles, %d liveries, %d categories, %d drives, %d garage entries, %d failures" % [
		"PASS" if fails.is_empty() else "FAIL", cat.size(), liveries, cats.size(), drives.size(),
		ins.values().count(true), fails.size()])
	DirAccess.remove_absolute(ProjectSettings.globalize_path(g.save_path))
	await _wait(0.2)
	get_tree().quit(0 if fails.is_empty() else 1)


# ------------------------------------------------------------------ screenshots
func _snap(dir: String, name: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img.get_width() > 1600:          # docs PNGs stay under ~1.5 MB
		img.resize(1600, int(1600.0 * img.get_height() / img.get_width()), Image.INTERPOLATE_LANCZOS)
	img.save_png(dir.path_join(name))
	print("showroom shot: ", dir.path_join(name))


func _shots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	var only := String(main.args.get("shots", "ext,wide,custom1,custom2,menu")).split(",")
	await _frames(20)
	main.hud.visible = false
	if "ext" in only and g.garages.size():
		var gar: Node3D = g.garages[int(main.args.get("shot-garage", "0"))]
		# from the road, across the street, looking at the door and sign
		var door: Vector3 = gar.door_position()
		var road_dir: Vector3 = Vector3(gar.data.road_dir[0], 0, gar.data.road_dir[2])
		var out: Vector3 = gar.global_basis.z
		var eye := door + out * 19.0 + road_dir * 7.0 + Vector3.UP * 1.6
		main.stream_now(eye)
		main.car.place(gar.approach_transform(9.0) * Transform3D(Basis(Vector3.UP, PI * 0.5), Vector3(-1.5, 0, 0)))
		var cam := Camera3D.new()
		cam.fov = 62.0
		cam.far = 2000.0
		main.add_child(cam)
		cam.global_position = eye
		cam.look_at(door + Vector3.UP * 2.6, Vector3.UP)
		cam.current = true
		g.set_process(true)
		await _wait(3.0)
		await _snap(dir, "showroom_exterior.png")
		main.cam.current = true
		cam.queue_free()
	var c := Tuning.default_cfg("hayate" if not Fleet.find("hayate").is_empty() else "")
	await _open()
	g.ui.visible = false
	if "wide" in only:
		c.variant = "purple" if c.vehicle == "hayate" else c.variant
		g.set_value("cfg", c)
		g.interior.spin = false
		g.interior.turntable.rotation.y = -0.5
		g.yaw = 0.3
		g.pitch = 0.16
		g.dist = 11.0
		await _wait(2.0)
		await _snap(dir, "showroom_wide.png")
	if "custom1" in only:
		var c1 := c.duplicate(true)
		c1.paint = {"on": true, "color": Tuning._arr(Color(0.05, 0.85, 1.0)), "finish": "pearl"}
		c1.underglow = {"on": true, "color": Tuning._arr(Color(1.0, 0.1, 0.55))}
		c1.kit = {"lip": true, "wing": true, "lightbar": false}
		c1.stance = {"drop": 0.04, "camber": 3.0}
		c1.rims = {"style": "kago" if not Fleet.find("kago").is_empty() else "stock", "color": Tuning._arr(Color(1.0, 0.72, 0.2))}
		c1.tint = 0.85
		c1.plate = "UNPLUG-77"
		g.set_value("cfg", c1)
		g.interior.turntable.rotation.y = 0.0
		g.yaw = 0.95
		g.pitch = 0.1
		g.dist = 6.8
		await _wait(1.5)
		await _snap(dir, "showroom_custom.png")
	if "custom2" in only:
		var c2 := Tuning.default_cfg("mame" if not Fleet.find("mame").is_empty() else "")
		c2.variant = "tsuru" if c2.vehicle == "mame" else c2.variant
		c2.underglow = {"on": true, "color": Tuning._arr(Color(0.6, 1.0, 0.1))}
		c2.kit = {"lip": false, "wing": false, "lightbar": false}
		g.set_value("cfg", c2)
		g.yaw = -2.4
		g.pitch = 0.22
		g.dist = 7.0
		await _wait(1.5)
		await _snap(dir, "showroom_livery.png")
	if "menu" in only:
		g.ui.visible = true
		var c3 := Tuning.default_cfg("tsubame" if not Fleet.find("tsubame").is_empty() else "")
		c3.variant = "pearl" if c3.vehicle == "tsubame" else c3.variant
		c3.paint = {"on": true, "color": Tuning._arr(Color(0.42, 0.1, 1.0)), "finish": "pearl"}
		c3.underglow = {"on": true, "color": Tuning._arr(Color(0.05, 0.85, 1.0))}
		c3.perf = {"engine": 2, "brakes": 1, "tyres": 2, "suspension": 1}
		c3.kit = {"lip": true, "wing": false, "lightbar": true}
		g.set_value("cfg", c3)
		g.ui.sel = 2
		g.ui._highlight()
		g.yaw = 0.35
		g.pitch = 0.14
		g.dist = 8.6
		await _wait(1.5)
		await _snap(dir, "showroom_menu.png")
	get_tree().quit(0)
