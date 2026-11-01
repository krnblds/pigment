extends Node
## Vehicle physics tests (headless OK; add --fixed-fps 120 to run faster than real time):
##   --curb-test [--curb-out=<json>] [--curb-quick]
##       drives the hero at kerbs (sidewalks), concrete (jersey) barriers and guard rails at several
##       angles and speeds, on the current map (--map=town | world). Asserts: never stuck (it can always
##       drive or reverse away), never flipped, and kerbs at >= 30 deg are climbed. Prints CURBTEST {...},
##       exit code 0 = pass.
##   --drive-test [--drive-out=<json>]
##       0-100 km/h, top speed, 100-0 braking on dry and wet, 60 m skidpad lateral g, a 120 km/h lane
##       change, a handbrake turn; plus the rest / rollover / reset checks of the old test.
##       Prints DRIVETEST {...}.
##   --physics-shots=<dir>   (opens a window, ~1 min) drift with smoke and skid marks, the tach, a kerb
##       climb: PNGs for docs/agents/physics/

var main: Node3D
var car: RigidBody3D
var _ctl := {}            ## per-tick driver: {"mode": ..., ...}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	car = main.car
	if main.args.has("curb-test"):
		_curb_test.call_deferred()
	elif main.args.has("drive-test"):
		_drive_test.call_deferred()
	elif main.args.has("physics-shots"):
		_shots.call_deferred(String(main.args["physics-shots"]))


func _wait(t: float) -> void:
	await get_tree().create_timer(t, true, true, true).timeout


func _tick() -> void:
	await get_tree().physics_frame


func _dt() -> float:
	return 1.0 / Engine.physics_ticks_per_second


func _quit(code: int) -> void:
	await _wait(0.2)
	get_tree().quit(code)


func _ray(from: Vector3, to: Vector3) -> Dictionary:
	var q := PhysicsRayQueryParameters3D.create(from, to)
	q.exclude = [car.get_rid()]
	q.collision_mask = 1
	return car.get_world_3d().direct_space_state.intersect_ray(q)


func _ground(p: Vector3, above := 3.0) -> float:
	var h := _ray(p + Vector3.UP * above, p + Vector3.DOWN * 6.0)
	return h.position.y if h else NAN


func _set_inputs(throttle: float, brake: float, steer: float, handbrake := false) -> void:
	car.autopilot = true
	if "input_brake" in car:
		car.input_throttle = throttle
		car.input_brake = brake
	else:          # the old VehicleBody3D car: one axis
		car.input_throttle = throttle - brake
	car.input_steer = steer
	car.input_handbrake = handbrake


# ================================================================== curb test
var _whys := {}
var _spacing := 15.0          ## candidate spacing along a road (the town is small: 5 m)
var _end_pad := 30.0          ## keep away from junctions
var _clear_len := 6.5         ## sidewalk past the kerb that must be free of lamps / walls (town: 4.5)


func _why(w: String) -> void:
	_whys[w] = _whys.get(w, 0) + 1


## Sites: {kind: curb | jersey | guardrail, p: kerb point (on the road surface), t: along, o: outward,
##         step: measured height of the kerb / barrier face over the road, d_edge}
func _curb_sites() -> Array:
	var want := []         # [kind, Array of candidate [p, t, o]]
	var lay: Dictionary = main.town.layout
	if main.map_name == "town" or not FileAccess.file_exists("res://assets/world/world.json"):
		_spacing = 5.0
		_end_pad = 18.0
		_clear_len = 4.5
		var roads: Array = lay.get("roads", [])
		var info: Array = lay.get("road_info", [])
		var cands := []
		for i in roads.size():
			var hw := 4.0
			if i < info.size() and info[i] != null:
				hw = float(info[i].get("half_width", 4.0))
			cands.append_array(_road_candidates(roads[i], hw, 0.0))
		want.append(["curb", cands, 4])
	else:
		var w = JSON.parse_string(FileAccess.get_file_as_string("res://assets/world/world.json"))
		var by := {"curb": [], "jersey": [], "guardrail": []}
		for r in w.roads:
			var side := String(r.get("side", "curb"))
			if not by.has(side):
				continue
			var pts := []
			var deck: Array = r.get("deck", [])
			for k in r.points.size():
				if k < deck.size() and deck[k]:
					continue        # bridges: kerbs over the void are not what we test
				var q: Array = r.points[k]
				pts.append([q[0], q[2], -q[1]])
			by[side].append_array(_road_candidates(pts, float(r.half_width), 0.0 if side == "curb" else 0.0))
		want.append(["curb", by.curb, 3])
		want.append(["jersey", by.jersey, 2])
		want.append(["guardrail", by.guardrail, 2])
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var sites := []
	for wk in want:
		var kind: String = wk[0]
		var cands: Array = wk[1]
		var n_want: int = wk[2]
		var got := 0
		var tries := 0
		var blocked := []
		# spread: shuffle deterministically, try until n_want good sites
		var order := range(cands.size())
		for i in range(order.size() - 1, 0, -1):
			var j := rng.randi_range(0, i)
			var tmp = order[i]
			order[i] = order[j]
			order[j] = tmp
		for idx in order:
			if got >= n_want or tries > 160:
				break
			tries += 1
			var c: Array = cands[idx]
			var s = _probe_site(kind, c[0], c[1], c[2], c[3])
			if s != null and not s.clear:
				blocked.append(s)
			elif s != null and sites.all(func(o): return o.p.distance_to(s.p) > (60.0 if _spacing > 10.0 else 20.0)):
				sites.append(s)
				got += 1
		# small maps (the town): lamps, poles and walls line every sidewalk -- use those sites too;
		# there "climbed" means the front axle got up the kerb (the car may then hit a lamp)
		for b in blocked:
			if got >= n_want or not main.args.has("curb-blocked"):
				break
			if sites.all(func(o): return o.p.distance_to(b.p) > 25.0):
				sites.append(b)
				got += 1
		print("curb sites: %s %d / %d (from %d candidates, %d probed) rejected: %s" % [kind, got, n_want, cands.size(), tries, _whys])
		_whys.clear()
	return sites


## Straight, gentle stretches of a road centre line: [centre point, tangent, left normal, half width]
func _road_candidates(pts: Array, hw: float, _pad: float) -> Array:
	var out := []
	var n := pts.size()
	if n < 6:
		return out
	var P: Array = []
	for q in pts:
		P.append(Vector3(q[0], q[1], q[2]))
	var cum := [0.0]
	for i in range(1, n):
		cum.append(cum[i - 1] + P[i].distance_to(P[i - 1]))
	var L: float = cum[n - 1]
	var i := 0
	while i < n:
		if cum[i] > _end_pad and cum[i] < L - _end_pad:
			# straightness over +-12 m
			var a := i
			while a > 0 and cum[i] - cum[a] < 12.0:
				a -= 1
			var b := i
			while b < n - 1 and cum[b] - cum[i] < 12.0:
				b += 1
			var t1: Vector3 = (P[i] - P[a]) * Vector3(1, 0, 1)
			var t2: Vector3 = (P[b] - P[i]) * Vector3(1, 0, 1)
			if t1.length() > 5.0 and t2.length() > 5.0 and t1.normalized().dot(t2.normalized()) > 0.998 \
					and absf(P[b].y - P[a].y) / maxf(1.0, cum[b] - cum[a]) < 0.06:
				var t: Vector3 = (P[b] - P[a]) * Vector3(1, 0, 1)
				t = t.normalized()
				var nl := Vector3.UP.cross(t).normalized()
				out.append([P[i], t, nl, hw])
				out.append([P[i], -t, -nl, hw])
		# next candidate ~15 m on
		var j := i + 1
		while j < n and cum[j] - cum[i] < _spacing:
			j += 1
		i = j
	return out


## Scan across the road edge for the kerb / barrier face; check the path beyond is clear (kerbs).
func _probe_site(kind: String, c: Vector3, t: Vector3, o: Vector3, hw: float):
	var bd: AABB = main.town.bounds
	if c.x < bd.position.x + 16.0 or c.x > bd.end.x - 16.0 or c.z < bd.position.z + 16.0 or c.z > bd.end.z - 16.0:
		_why("map edge")
		return null
	main.town.ensure_collision(c + o * hw, 30.0)
	var road_y := _ground(c + o * (hw - 1.4))
	if is_nan(road_y):
		_why("no road")
		return null
	var dbg := []
	var prev := road_y
	var d := hw - 1.4
	var edge := -1.0
	var top := road_y
	while d < hw + 1.6:
		var y := _ground(c + o * d + Vector3.UP * (road_y - c.y), 3.0)
		if is_nan(y):
			_why("no ground")
			return null
		dbg.append(snappedf(y - road_y, 0.01))
		if y - road_y > 0.06 and edge < 0.0:
			edge = d
		if edge >= 0.0:
			top = maxf(top, y)
			if d > edge + 0.6:
				break
		elif absf(y - prev) > 0.04:
			_why("bumpy " + kind)
			if main.args.has("curb-debug"):
				print("  bumpy ", kind, " ", dbg)
			return null          # bumpy road surface: not a clean site
		prev = y
		d += 0.05
	if edge < 0.0:
		# no ground step: a guard rail (posts + beam) has none -- find the beam with a horizontal ray
		if kind != "guardrail":
			_why("no step " + kind)
			if main.args.has("curb-debug"):
				print("  nostep ", kind, " ", dbg)
			return null
		var h := _ray(c + o * (hw - 1.0) + Vector3.UP * (road_y - c.y + 0.65), c + o * (hw + 2.0) + Vector3.UP * (road_y - c.y + 0.65))
		if not h:
			return null
		edge = (h.position - c).dot(o)
		top = road_y + 0.82
	var step := top - road_y
	var measured := "curb" if step < 0.3 else "barrier"
	if kind == "curb" and measured != "curb":
		_why("curb too high %.2f" % step)
		return null
	if kind != "curb" and measured == "curb":
		_why("barrier too low %.2f" % step)
		return null
	var p := c + o * edge
	p.y = road_y
	# kerbs: the sidewalk the car will climb onto must be clear (lamps, poles, buildings, walls)
	# kerbs: the sidewalk the car drives onto must be clear (lamps, poles, walls) and have nothing
	# hanging over it lower than the roof (a footing / sign box wedges any car) -- per approach angle
	var angles := []
	if kind == "curb":
		var ss := car.get_world_3d().direct_space_state
		for ang in [15.0, 30.0, 50.0, 80.0]:
			var dir := (t * cos(deg_to_rad(ang)) + o * sin(deg_to_rad(ang))).normalized()
			var q := PhysicsShapeQueryParameters3D.new()
			var box := BoxShape3D.new()
			box.size = Vector3(2.4, 1.2, _clear_len)
			q.shape = box
			var basis := Basis(Vector3.UP.cross(dir).normalized(), Vector3.UP, dir)
			q.transform = Transform3D(basis, p + dir * (_clear_len * 0.5 + 0.35) + Vector3.UP * (step + 0.75))
			q.collision_mask = 1
			q.exclude = [car.get_rid()]
			if not ss.intersect_shape(q, 1).is_empty():
				continue
			var over := false
			var side := Vector3.UP.cross(dir).normalized()
			for k in range(1, 7):
				for l in [-0.8, 0.0, 0.8]:
					var base: Vector3 = p + dir * float(k) + side * l + Vector3.UP * (step + 0.05)
					var hu := _ray(base, base + Vector3.UP * 1.4)
					if hu and hu.normal.y < -0.5 and hu.position.y - base.y > 0.25:
						over = true
			if not over:
				angles.append(ang)
		if angles.size() < 2:
			_why("blocked")
			return null
	return {"kind": kind, "p": p, "t": t, "o": o, "step": snappedf(step, 0.01), "edge": snappedf(edge - hw, 0.01),
		"clear": true, "angles": angles}


func _curb_test() -> void:
	var quick: bool = main.args.has("curb-quick")
	var angles := [15.0, 30.0, 50.0, 80.0] if not quick else [20.0, 60.0]
	var speeds := [10.0, 20.0, 30.0, 40.0] if not quick else [15.0, 35.0]
	await _wait(1.0)
	if main.traffic:
		main.traffic.process_mode = Node.PROCESS_MODE_DISABLED
		main.traffic.visible = false
	var sites := _curb_sites()
	var results := []
	var fails := []
	var t0 := Time.get_ticks_msec()
	for s in sites:
		for ang in angles:
			for v in speeds:
				if s.kind == "curb" and not (ang in s.angles):
					continue
				if main.args.has("curb-only"):
					var f: PackedStringArray = String(main.args["curb-only"]).split(":")
					if f[0] != s.kind or float(f[1]) != ang or float(f[2]) != v:
						continue
				var r: Dictionary = await _curb_case(s, ang, v)
				results.append(r)
				var line := "  %-9s %4.0f deg %3.0f km/h  climbed=%s stuck=%s flip=%s min_up=%.2f max_rise=%.2f end_kmh=%.0f %s" % [
					s.kind, ang, v, r.climbed, r.stuck, r.flipped, r.min_up, r.max_rise, r.end_kmh, r.get("note", "") + r.get("contacts", "")]
				print(line)
				if r.fail:
					fails.append(r)
	var by_kind := {}
	for r in results:
		var k: String = r.kind
		if not by_kind.has(k):
			by_kind[k] = {"cases": 0, "stuck": 0, "flipped": 0, "climbed": 0, "must_climb": 0, "climb_missed": 0}
		var b: Dictionary = by_kind[k]
		b.cases += 1
		b.stuck += int(r.stuck)
		b.flipped += int(r.flipped)
		b.climbed += int(r.climbed)
		b.must_climb += int(r.must_climb)
		b.climb_missed += int(r.must_climb and not r.climbed)
	var out := {"map": main.map_name, "sites": sites.map(func(s): return {"kind": s.kind, "p": [snappedf(s.p.x, 0.1), snappedf(s.p.y, 0.01), snappedf(s.p.z, 0.1)], "step": s.step}),
		"cases": results.size(), "fails": fails.size(), "by_kind": by_kind, "pass": fails.is_empty() and not sites.is_empty(),
		"wall_s": snappedf((Time.get_ticks_msec() - t0) / 1000.0, 0.1), "vehicle": car.get_script().resource_path}
	print("CURBTEST ", JSON.stringify(out))
	if main.args.has("curb-out"):
		out["results"] = results
		var f := FileAccess.open(String(main.args["curb-out"]), FileAccess.WRITE)
		f.store_string(JSON.stringify(out, "  "))
		f.close()
	_quit(0 if out.pass else 1)


## One run: start on the road aimed at the kerb at `ang` degrees, holding `kmh`, then the driver tries
## to carry on (throttle), and if the car has stopped, to drive away forwards then backwards.
func _curb_case(s: Dictionary, ang: float, kmh: float) -> Dictionary:
	var v := kmh / 3.6
	var a := deg_to_rad(ang)
	var dir: Vector3 = (s.t * cos(a) + s.o * sin(a)).normalized()
	# the car's nearest front corner ~ (0.9 + v * 0.7) m from the kerb line
	var half_l := 2.25
	var half_w := 0.92
	var corner := half_l * sin(a) + half_w * cos(a)
	var perp := corner + 0.6 + v * 0.7 * sin(a)
	var start: Vector3 = s.p - dir * (perp / sin(a))
	start.y = s.p.y
	main.town.ensure_collision(start, 30.0)
	var gy := _ground(start, 3.0)          # roads have grades: the start may sit higher / lower
	if not is_nan(gy):
		start.y = gy
	var basis := Basis(Vector3.UP.cross(dir).normalized(), Vector3.UP, dir)
	car.place(Transform3D(basis, start + Vector3.UP * 0.05))
	for i in 3:
		await _tick()
	car.place(Transform3D(basis, start + Vector3.UP * 0.05))
	car.linear_velocity = dir * v
	car.angular_velocity = Vector3.ZERO
	if main.args.has("curb-trace"):
		for k in 4:
			var q := start + dir * (k * 1.5) + Vector3.UP * 1.0
			var hh := _ray(q, q + Vector3.DOWN * 3.0)
			print("   ground probe ", k, " ", hh.get("position", "-"), " n=", hh.get("normal", "-"), " ", hh.collider.name if hh else "", " car y ", car.global_position.y)
	if car.has_method("prime_speed"):
		car.prime_speed(v)
	var res := {"kind": s.kind, "angle": ang, "kmh": kmh, "climbed": false, "stuck": false, "flipped": false,
		"min_up": 1.0, "max_rise": 0.0, "end_kmh": 0.0, "fail": false, "must_climb": s.kind == "curb" and ang >= 30.0}
	var y0: float = s.p.y
	var max_pen := -9.0
	var max_rear := -9.0
	var crashed := false
	var t := 0.0
	# phase A: hold the speed, steering straight, 3.5 s (or until well past the kerb)
	while t < 3.5:
		await _tick()
		t += _dt()
		var fwd := car.linear_velocity.dot(car.global_basis.z)
		# the driver holds the speed; after a crash (speed halved by a hit) they lift
		if fwd < v * 0.5 and t > 0.3:
			crashed = true
		_set_inputs(0.0 if crashed else clampf((v - fwd) * 0.6 + 0.15, 0.0, 1.0), 0.0, 0.0)
		res.min_up = minf(res.min_up, car.global_basis.y.y)
		var pen: float = (car.global_position - s.p).dot(s.o)
		max_pen = maxf(max_pen, pen)
		var rear_now: Vector3 = car.global_position - car.global_basis.z * 1.32
		max_rear = maxf(max_rear, (rear_now - s.p).dot(s.o))
		res.max_rise = maxf(res.max_rise, car.global_position.y - y0)
		if main.args.has("curb-trace") and int(t * 120.0) % 6 == 0:
			_trace(t, s, pen)
		if pen > 3.2:
			break
	# climbed: the whole car (its rear axle) is past the kerb line, onto the sidewalk
	if s.kind == "curb":
		# both axles got over the kerb line (a site with a lamp / wall close behind: the front axle)
		res.climbed = max_rear > 0.2 if s.clear else max_rear + 2.65 > 0.5
	# phase B: is it stuck?  Moving on: fine.  Stopped: try forwards, then reverse.
	var speed := car.linear_velocity.length()
	if speed < 1.0:
		var moved := false
		for attempt in [[1.0, 0.0], [0.0, 1.0]]:
			var p0: Vector3 = car.global_position
			var tt := 0.0
			# the automatic box needs to see a stop + brake held to select reverse
			while tt < 3.0:
				await _tick()
				tt += _dt()
				_set_inputs(attempt[0], attempt[1], 0.0)
				if main.args.has("curb-trace") and int(tt * 120.0) % 12 == 0:
					_trace(tt, s, (car.global_position - s.p).dot(s.o))
				res.min_up = minf(res.min_up, car.global_basis.y.y)
				if car.global_position.distance_to(p0) > 1.0:
					moved = true
					break
			if moved:
				res["note"] = "drove away " + ("forwards" if attempt[0] > 0.0 else "in reverse")
				break
		res.stuck = not moved
		if res.stuck:
			res["contacts"] = _contacts_desc(s)
			if main.args.has("curb-trace"):
				for w in car.wheels:
					var hub: Vector3 = car.global_transform * w.rest
					var from: Vector3 = hub + Vector3.UP * 0.5
					var hits := []
					for k in 4:
						var hh := _ray(from, hub + Vector3.DOWN * 1.0)
						if hh.is_empty():
							break
						hits.append([snappedf(hh.position.y - s.p.y, 0.01), snappedf(hh.normal.y, 0.01), hh.collider.name])
						from = hh.position + Vector3.DOWN * 0.02
					print("   wheel ", w.name, " hub h=", snappedf(hub.y - s.p.y, 0.01), " hits ", hits, " ref ", w.ref_valid, " ", snappedf(w.ref_point.y - s.p.y, 0.01))
	res.end_kmh = snappedf(car.linear_velocity.length() * 3.6, 0.1)
	res.flipped = res.min_up < 0.3 or car.global_basis.y.y < 0.6
	res.min_up = snappedf(res.min_up, 0.01)
	res.max_rise = snappedf(res.max_rise, 0.01)
	res.fail = res.stuck or res.flipped or (res.must_climb and not res.climbed)
	_set_inputs(0.0, 1.0, 0.0)
	return res


func _trace(t: float, s: Dictionary, pen: float) -> void:
	print("   t=%.2f pen=%.2f kmh=%.1f gear=%s rpm=%d thr=%.2f brk=%.2f up=%.2f wheels=%s %s" % [t, pen, car.linear_velocity.length() * 3.6,
		car.gear, int(car.rpm), car.input_throttle, car.input_brake, car.global_basis.y.y,
		car.wheels.map(func(w): return [int(w.contact), snappedf(w.x, 0.01), snappedf(w.omega, 0.1)]), _contacts_desc(s)])


## Where the body touches the world (car frame: x left, y up, z forward), and which wheels have ground.
func _contacts_desc(s: Dictionary) -> String:
	var st := PhysicsServer3D.body_get_direct_state(car.get_rid())
	var out := []
	for i in st.get_contact_count():
		# get_contact_local_position is in global coordinates (despite the name)
		var gp: Vector3 = st.get_contact_local_position(i)
		var lp: Vector3 = car.global_transform.affine_inverse() * gp
		var co = st.get_contact_collider_object(i)
		out.append("body(%.2f,%.2f,%.2f) n.y=%.2f h=%.2f %s" % [lp.x, lp.y, lp.z, st.get_contact_local_normal(i).y,
			gp.y - s.p.y, co.name if co is Node else ""])
	var wc := []
	if "wheels" in car:
		for w in car.wheels:
			wc.append(1 if w.is_in_contact() else 0)
	return "contacts: %s wheels %s" % [", ".join(out), wc]


# ================================================================== drive test
## A flat proving ground (asphalt, 6 x 6 km) far off the map, so the numbers don't depend on the roads.
var _pad_o := Vector3(40000, 0, 40000)


func _make_pad() -> void:
	var y := 0.0
	if main.town and main.town.layout:
		y = maxf(main.town.bounds.position.y + 60.0, 0.0)
	_pad_o.y = y
	var sb := StaticBody3D.new()
	sb.name = "ProvingGround"
	sb.set_meta("surface", "asphalt")
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(6000, 2, 6000)
	cs.shape = b
	sb.add_child(cs)
	sb.position = _pad_o + Vector3(0, -1, 0)
	main.add_child(sb)


## Car on the pad at local (x, z), heading +Z turned by yaw, rolling at v (held while it settles).
func _pad_place(x: float, z: float, yaw: float, v: float) -> void:
	var basis := Basis(Vector3.UP, yaw)
	var xf := Transform3D(basis, _pad_o + Vector3(x, 0.02, z))
	car.place(xf)
	await _tick()
	car.place(xf)
	if v > 0.0 and car.has_method("prime_speed"):
		car.prime_speed(v)
	for i in 30:
		car.linear_velocity = car.global_basis.z * v
		car.angular_velocity = Vector3.ZERO
		_set_inputs(0.0, 0.0, 0.0, v <= 0.0)
		await _tick()


func _kmh() -> float:
	return car.linear_velocity.dot(car.global_basis.z) * 3.6


func _yaw() -> float:
	var z: Vector3 = car.global_basis.z
	return atan2(z.x, z.z)


## Pure pursuit: front steer angle (rad) towards a point `look` m ahead on the line p0 + d * s,
## shifted `offset` m to the left.
func _follow_line(p0: Vector3, d: Vector3, offset: float, look: float) -> float:
	var left := Vector3.UP.cross(d).normalized()
	var p: Vector3 = car.global_position
	var along := (p - p0).dot(d)
	var target := p0 + d * (along + look) + left * offset
	var to := target - p
	to.y = 0.0
	var fwd: Vector3 = car.global_basis.z
	var alpha := fwd.signed_angle_to(to.normalized(), Vector3.UP)
	return atan(2.0 * 2.65 * sin(alpha) / maxf(to.length(), 1.0))


func _drive_test() -> void:
	var res := {}
	var checks := {}
	print("drive test: vehicle ", car.P.get("id", "?") if "P" in car else "?")
	if main.args.has("drive-debug"):
		for i in 24:
			await _wait(0.125)
			print("  t=%.2f pos=%s up=%.3f v=%s wheels=%s" % [i * 0.125, car.global_position.snappedf(0.01), car.global_basis.y.y,
				car.linear_velocity.snappedf(0.01), car.wheels.map(func(w): return [w.contact, snappedf(w.x, 0.01), int(w.load), w.surface])])
	await _wait(1.0)
	if main.traffic:
		main.traffic.process_mode = Node.PROCESS_MODE_DISABLED
		main.traffic.visible = false
	# --- on the map: rest, a 30 s autopilot drive (rollovers), reset
	await _wait(1.0)
	res["rest_speed"] = snappedf(car.linear_velocity.length(), 0.01)
	res["rest_up"] = snappedf(car.global_basis.y.y, 0.001)
	res["wheels_contact"] = car.wheels.filter(func(w): return w.is_in_contact()).size()
	main.ap_speed = 17.0
	main.autopilot_start()
	var min_up := 1.0
	var resets := 0
	var t := 0.0
	var start: Vector3 = car.global_position
	var vmax_map := 0.0
	while t < 30.0:
		await _tick()
		t += _dt()
		main.autopilot_step(_dt())
		min_up = minf(min_up, car.global_basis.y.y)
		vmax_map = maxf(vmax_map, _kmh())
		if car.needs_reset():
			resets += 1

	res["car_tick_us"] = snappedf(float(car.get("prof_us")), 0.1) if car.get("prof_us") != null else -1.0
	res["map_drive"] = {"seconds": 30, "distance": snappedf(car.global_position.distance_to(start), 0.1),
		"vmax_kmh": snappedf(vmax_map, 0.1), "min_up": snappedf(min_up, 0.01), "auto_resets": resets}
	checks["map_drive_no_rollover"] = min_up > 0.7 and resets == 0
	car.global_position += Vector3(30, 5, 0)
	main.reset_car()
	await _wait(1.5)
	res["after_reset_up"] = snappedf(car.global_basis.y.y, 0.001)
	checks["reset_upright"] = car.global_basis.y.y > 0.95
	_set_inputs(0.0, 0.0, 0.0)
	# --- proving ground
	_make_pad()
	var fwd_line := Vector3(0, 0, 1)
	for wet in [0.0, 1.0]:
		car.wet = wet
		var tag := "wet" if wet > 0.5 else "dry"
		await _pad_place(0.0, -2900.0, 0.0, 0.0)
		var r := {}
		t = 0.0
		var t60 := -1.0
		var t100 := -1.0
		var vmax := 0.0
		var last_gain_t := 0.0
		var p0: Vector3 = car.global_position
		var shifts := []
		var g_prev: int = car.gear
		var max_slip := 0.0
		var tmax := 75.0 if wet < 0.5 else 15.0
		while t < tmax:
			await _tick()
			t += _dt()
			car.steer_override = _follow_line(p0, fwd_line, 0.0, 25.0)
			_set_inputs(1.0, 0.0, 0.0)
			var k := _kmh()
			if k > vmax + 0.2:
				vmax = k
				last_gain_t = t
			if t60 < 0.0 and k >= 60.0:
				t60 = t
			if t100 < 0.0 and k >= 100.0:
				t100 = t
			if car.gear != g_prev and car.gear > 0:
				shifts.append([car.gear, snappedf(t, 0.01), snappedf(k, 0.1)])
				g_prev = car.gear
			if t < 3.0:
				max_slip = maxf(max_slip, car.max_slip())
			if main.args.has("drive-debug") and wet < 0.5 and int(t * 120.0) % 30 == 0 and t < 12.0:
				print("    t=%.2f kmh=%.1f rpm=%d gear=%d clutch=%.2f thr=%.2f slipv=%.2f kappa=%.3f tc=%.2f" % [t, k, int(car.rpm), car.gear,
					car.clutch, car.throttle_out, car.max_slip(), car.wheels[2].kappa, car.tc_active])
			if t - last_gain_t > 6.0 and t > 20.0:
				break
		r["t_0_60"] = snappedf(t60, 0.01)
		r["t_0_100"] = snappedf(t100, 0.01)
		r["vmax_kmh"] = snappedf(vmax, 0.1)
		r["shifts"] = shifts
		r["launch_max_slip_ms"] = snappedf(max_slip, 0.1)
		r["rpm_at_end"] = int(car.rpm)
		for abs_mode in [true, false]:
			car.abs_on = abs_mode
			await _pad_place(30.0, -2900.0, 0.0, 100.0 / 3.6)
			var bp: Vector3 = car.global_position
			var bt := 0.0
			var v0 := _kmh()
			while _kmh() > 0.3 and bt < 15.0:
				await _tick()
				bt += _dt()
				car.steer_override = _follow_line(bp, fwd_line, 0.0, 20.0)
				_set_inputs(0.0, 1.0, 0.0)
			var key := "brake_100_0" + ("" if abs_mode else "_no_abs")
			r[key] = {"from_kmh": snappedf(v0, 0.1), "m": snappedf((car.global_position - bp).dot(fwd_line), 0.1),
				"s": snappedf(bt, 0.01), "heading_change_deg": snappedf(rad_to_deg(absf(_yaw())), 0.1)}
		car.abs_on = true
		res[tag] = r
		print("  ", tag, " ", JSON.stringify(r))
	car.wet = 0.0
	car.steer_override = NAN
	var dry: Dictionary = res.dry
	var wetr: Dictionary = res.wet
	checks["0_100_7_to_10.5s"] = dry.t_0_100 > 7.0 and dry.t_0_100 < 10.5
	checks["vmax_168_196"] = dry.vmax_kmh > 168.0 and dry.vmax_kmh < 196.0
	checks["brake_dry_33_47m"] = dry.brake_100_0.m > 33.0 and dry.brake_100_0.m < 47.0
	checks["brake_wet_46_64m"] = wetr.brake_100_0.m > 46.0 and wetr.brake_100_0.m < 64.0
	# --- skidpad: 60 m circle (radius 30 m); speed creeps up until the car can't hold the line
	res["skidpad"] = await _skidpad(30.0)
	print("  skidpad ", JSON.stringify(res.skidpad))
	checks["skidpad_0.75_1.08g"] = res.skidpad.lat_g > 0.75 and res.skidpad.lat_g < 1.08
	# --- lane change at 120 km/h: a smooth driver, and a keyboard-style one (full-lock taps)
	res["lane_change_120"] = await _lane_change(120.0, false)
	res["lane_change_120_keyboard"] = await _lane_change(120.0, true)
	print("  lane change ", JSON.stringify(res.lane_change_120), " ", JSON.stringify(res.lane_change_120_keyboard))
	checks["lane_change_no_spin"] = res.lane_change_120.max_slip_deg < 6.0 and res.lane_change_120.final_heading_deg < 6.0 \
		and res.lane_change_120_keyboard.max_slip_deg < 10.0 and res.lane_change_120_keyboard.final_heading_deg < 15.0
	# --- handbrake turn from 50 km/h
	res["handbrake_turn"] = await _handbrake_turn(50.0)
	print("  handbrake ", JSON.stringify(res.handbrake_turn))
	checks["handbrake_turn_rotates"] = res.handbrake_turn.yaw_deg > 60.0 and res.handbrake_turn.min_up > 0.8
	# --- power oversteer: floor it in a 30 m turn, TC off vs on (informational)
	res["power_oversteer"] = {"tc_off": await _power_on(false), "tc_on": await _power_on(true)}
	car.tc_on = true
	res["checks"] = checks
	var ok := true
	for k in checks:
		ok = ok and checks[k]
	res["pass"] = ok
	print("DRIVETEST ", JSON.stringify(res))
	if main.args.has("drive-out"):
		var f := FileAccess.open(String(main.args["drive-out"]), FileAccess.WRITE)
		f.store_string(JSON.stringify(res, "  "))
		f.close()
	_quit(0 if ok else 1)


## Pure pursuit on a circle (anticlockwise seen from above: turning left), steer angle in rad.
func _circle_steer(c: Vector3, radius: float) -> float:
	var p: Vector3 = car.global_position
	var rel := p - c
	rel.y = 0.0
	var ang := atan2(rel.z, rel.x)
	# anticlockwise in the x-z plane seen from +y is decreasing atan2(z, x)
	var ahead := ang - 10.0 / radius
	var tgt := c + Vector3(cos(ahead), 0, sin(ahead)) * radius
	var to := tgt - p
	to.y = 0.0
	var alpha: float = car.global_basis.z.signed_angle_to(to.normalized(), Vector3.UP)
	return atan(2.0 * 2.65 * sin(alpha) / maxf(to.length(), 1.0)) + clampf((rel.length() - radius) * 0.02, -0.08, 0.08)


func _skidpad(radius: float) -> Dictionary:
	var c := _pad_o + Vector3(1500, 0, 0)
	var v := 9.0
	# on the circle's west point, heading +z: the centre is to the car's left (+x)... start east
	await _pad_place(1500.0 - radius, 0.0, 0.0, v)
	c = car.global_position + Vector3(radius, 0, 0)
	var t := 0.0
	var best_g := 0.0
	var win: Array = []
	var target_v := v
	var lost := 0.0
	var steer_deg := 0.0
	while t < 70.0:
		await _tick()
		t += _dt()
		var rel: Vector3 = car.global_position - c
		rel.y = 0.0
		var rr := rel.length()
		var d := _circle_steer(c, radius)
		car.steer_override = d
		steer_deg = rad_to_deg(d)
		target_v += 0.12 * _dt()
		var k := car.linear_velocity.length()
		_set_inputs(clampf((target_v - k) * 0.5 + 0.12, 0.0, 1.0), clampf((k - target_v - 1.0) * 0.3, 0.0, 0.5), 0.0)
		var lat := k * k / maxf(rr, 1.0)
		if absf(rr - radius) < 1.5:
			win.append(lat / 9.81)
			lost = 0.0
		else:
			lost += _dt()
			win.clear()
			target_v = maxf(8.0, target_v - 0.5 * _dt())
		if win.size() > 240:          # a 2 s steady window
			win.pop_front()
			var m := 0.0
			for x in win:
				m += x
			best_g = maxf(best_g, m / win.size())
		if lost > 4.0 and t > 20.0:
			break
	car.steer_override = NAN
	return {"radius_m": radius, "lat_g": snappedf(best_g, 0.001), "speed_at_limit_kmh": snappedf(sqrt(best_g * 9.81 * radius) * 3.6, 0.1),
		"steer_deg_at_end": snappedf(steer_deg, 0.1)}


func _lane_change(kmh: float, keyboard: bool) -> Dictionary:
	var v := kmh / 3.6
	await _pad_place(-1500.0, -2900.0, 0.0, v)
	var p0: Vector3 = car.global_position
	var d := Vector3(0, 0, 1)
	var t := 0.0
	var max_beta := 0.0
	var max_yaw_rate := 0.0
	var min_up := 1.0
	var lc_start := 1.0
	var lc_len := 2.6          # seconds for the 3.5 m move
	while t < 9.0:
		await _tick()
		t += _dt()
		var k: float = car.linear_velocity.dot(car.global_basis.z)
		var thr := clampf((v - k) * 0.6 + 0.3, 0.0, 1.0)
		if keyboard:
			# keyboard driver: full taps -- left 0.30 s, right 0.30 s (the catch), then let go
			var st := 0.0
			if t > lc_start and t < lc_start + 0.30:
				st = 1.0
			elif t > lc_start + 0.55 and t < lc_start + 0.85:
				st = -1.0
			car.steer_override = NAN
			_set_inputs(thr, 0.0, st)
		else:
			var u := clampf((t - lc_start) / lc_len, 0.0, 1.0)
			var off := 3.5 * u * u * (3.0 - 2.0 * u)
			car.steer_override = _follow_line(p0, d, off, maxf(12.0, k * 0.9))
			_set_inputs(thr, 0.0, 0.0)
		var vel: Vector3 = car.linear_velocity
		if vel.length() > 5.0:
			max_beta = maxf(max_beta, absf(car.global_basis.z.signed_angle_to(vel.normalized(), Vector3.UP)))
		max_yaw_rate = maxf(max_yaw_rate, absf(car.angular_velocity.y))
		min_up = minf(min_up, car.global_basis.y.y)
	var lateral := (car.global_position - p0).dot(Vector3(1, 0, 0))
	car.steer_override = NAN
	return {"kmh": kmh, "keyboard": keyboard, "max_slip_deg": snappedf(rad_to_deg(max_beta), 0.1),
		"max_yaw_rate_dps": snappedf(rad_to_deg(max_yaw_rate), 0.1), "final_heading_deg": snappedf(rad_to_deg(absf(_yaw())), 0.1),
		"lateral_m": snappedf(lateral, 0.01), "end_kmh": snappedf(_kmh(), 0.1), "min_up": snappedf(min_up, 0.01)}


func _handbrake_turn(kmh: float) -> Dictionary:
	await _pad_place(-2500.0, -2900.0, 0.0, kmh / 3.6)
	var t := 0.0
	var acc := 0.0
	var prev := _yaw()
	var min_up := 1.0
	while t < 3.5:
		await _tick()
		t += _dt()
		var hb := t < 1.1
		var st := 1.0 if t < 1.6 else 0.0
		_set_inputs(0.0 if hb else 0.2, 0.0, st, hb)
		var y := _yaw()
		acc += wrapf(y - prev, -PI, PI)
		prev = y
		min_up = minf(min_up, car.global_basis.y.y)
	_set_inputs(0.0, 1.0, 0.0)
	return {"from_kmh": kmh, "yaw_deg": snappedf(rad_to_deg(absf(acc)), 0.1), "min_up": snappedf(min_up, 0.01),
		"end_kmh": snappedf(car.linear_velocity.length() * 3.6, 0.1)}


## On a 30 m circle at ~40 km/h, floor it: how far does the tail step out?
func _power_on(tc: bool) -> Dictionary:
	car.tc_on = tc
	var radius := 30.0
	await _pad_place(-500.0 - radius, 1500.0, 0.0, 11.0)
	var c: Vector3 = car.global_position + Vector3(radius, 0, 0)
	var t := 0.0
	var max_beta := 0.0
	while t < 5.0:
		await _tick()
		t += _dt()
		car.steer_override = _circle_steer(c, radius)
		var k: float = car.linear_velocity.length()
		var thr := clampf((11.0 - k) * 0.5 + 0.1, 0.0, 1.0) if t < 2.5 else 1.0
		_set_inputs(thr, 0.0, 0.0)
		if t > 2.5:
			var vel: Vector3 = car.linear_velocity
			if vel.length() > 3.0:
				max_beta = maxf(max_beta, absf(car.global_basis.z.signed_angle_to(vel.normalized(), Vector3.UP)))
	car.steer_override = NAN
	return {"max_slip_deg": snappedf(rad_to_deg(max_beta), 0.1), "gear": car.gear}


# ================================================================== screenshots (windowed)
func _shot(dir: String, name: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img.get_width() > 1600:
		img.resize(1600, int(1600.0 * img.get_height() / img.get_width()), Image.INTERPOLATE_LANCZOS)
	var full := dir.path_join(name + ".png")
	img.save_png(full)
	print("SHOT ", full)


func _shots(dir: String) -> void:
	DirAccess.make_dir_recursive_absolute(dir)
	DisplayServer.window_set_size(Vector2i(1920, 1080))
	if main.traffic:
		main.traffic.process_mode = Node.PROCESS_MODE_DISABLED
		main.traffic.visible = false
	car.wet = 0.0                       # dry tarmac: tyre smoke (the rain makes it spray instead)
	main.rain.emitting = false
	main.rain.visible = false
	var spot := {}
	if FileAccess.file_exists("res://assets/world/world.json") and main.map_name != "town":
		var w = JSON.parse_string(FileAccess.get_file_as_string("res://assets/world/world.json"))
		for sp in preload("res://scripts/automation.gd")._spots(w):
			if sp.name == "avenue":
				spot = sp
	var p0: Vector3
	var d: Vector3
	if spot:
		var t: Vector3 = (spot.at - spot.eye) * Vector3(1, 0, 1)
		d = t.normalized()
		p0 = spot.eye - Vector3.UP * 2.2 - Vector3.UP.cross(d).normalized() * 3.0 - d * 25.0
	else:
		var xf: Transform3D = main.town.spawn_transform()
		p0 = xf.origin
		d = xf.basis.z
	main.stream_now(p0)
	main.town.ensure_collision(p0, 60.0)
	var basis := Basis(Vector3.UP.cross(d).normalized(), Vector3.UP, d)
	car.place(Transform3D(basis, p0 + Vector3.UP * 0.5))
	_set_inputs(0.0, 0.0, 0.0, true)
	await _wait(6.0)                    # shaders, SDFGI, streaming
	# 1. the tach while pulling away hard
	car.esc_on = false
	car.tc_on = false
	var t := 0.0
	while t < 2.4:
		await _tick()
		t += _dt()
		_set_inputs(1.0, 0.0, 0.0)
	await _shot(dir, "03_hud_tach_launch")
	# 2. handbrake flick into a drift, then power on with counter-steer
	t = 0.0
	while t < 1.4:
		await _tick()
		t += _dt()
		_set_inputs(1.0, 0.0, 0.0)
	var shots := [[0.55, "01_drift_smoke"], [0.95, "01b_drift_smoke"], [1.35, "01c_drift_smoke"]]
	var drift_start: Vector3 = car.global_position
	t = 0.0
	main.cam.mode = 1
	main.cam.snap()
	while t < 1.9:
		await _tick()
		t += _dt()
		if t < 0.45:
			_set_inputs(0.3, 0.0, 1.0, true)
		else:
			_set_inputs(1.0, 0.0, -0.35, false)
		if not shots.is_empty() and t >= shots[0][0]:
			await _shot(dir, shots[0][1])
			shots.pop_front()
	var drift_end: Vector3 = car.global_position
	_set_inputs(0.0, 0.0, 0.0, true)
	await _wait(2.0)
	# 3. the skid marks, from above the line the car slid along
	main.cam.manual = true
	main.cam.fov = 60.0
	var cp: Vector3 = (drift_end + drift_start) * 0.5
	var away: Vector3 = (drift_end - drift_start) * Vector3(1, 0, 1)
	var side := Vector3.UP.cross(away.normalized())
	main.cam.global_position = cp + Vector3(0, 7.0, 0) + side * 7.0
	main.cam.look_at(cp, Vector3.UP)
	await _wait(1.0)
	await _shot(dir, "02_skid_marks")
	main.cam.manual = false
	main.cam.mode = 0
	_quit(0)
