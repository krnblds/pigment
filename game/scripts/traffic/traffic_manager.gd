extends Node3D
## Living traffic: lane graph + signals + pooled AI vehicles, parked cars and security patrols.
##
## Moving cars are kinematic lane followers (cheap) and only get collision near the player; when
## the player (or a loose car) hits one it becomes a real rigid body, comes to rest, then blends back
## onto its lane.  AI per car: IDM car-following (car ahead, red light / stop line, player and
## wrecks in its path), junction entry with conflicts, priorities and "don't block the box",
## lane changes (route + overtaking slow cars), brake / head lights, horn.
##
## Spawning keeps `target` cars active in a ring around the player, out of view; the count adapts
## to the frame rate (between min_count and max_count) unless `fixed_count` is set (bench / tests).

const LaneGraph := preload("res://scripts/traffic/lane_graph.gd")
const Signals := preload("res://scripts/traffic/signals.gd")
const VehicleLib := preload("res://scripts/traffic/vehicle_library.gd")
const TrafficCar := preload("res://scripts/traffic/traffic_car.gd")
const Pedestrians := preload("res://scripts/traffic/pedestrians.gd")

const WORLD_PATHS := ["res://assets/world/world.json", "res://assets/world/world_lanes.json"]

# --- tuning
var max_count := 80
var min_count := 24
var target := 60
var fixed_count := false
var world_spawn = null           ## world.json spawn point (Godot space), if any
var ignore_player := false       ## tests: the player is parked out of the way
var patrol_count := 2
var parked_per_100m := 2.6
var ring_min := 45.0
var ring_max := 260.0
var near_radius := 55.0          ## collision on within this distance of the player
var spot_lights := 6             ## real headlight spots on the nearest cars
var ai_div := 4                  ## full AI every Nth physics tick per car (30 Hz at 120 Hz)
# IDM
const A_MAX := 1.8
const B_COMF := 2.6
const S0 := 2.6
const T_HEAD := 1.25
const LOOK := 90.0

var main: Node3D                 ## main.gd (car, cam, town, args)
var graph
var signals
var lib
var peds
var rng := RandomNumberGenerator.new()
var cars: Array = []             ## moving pool (civilians)
var patrols: Array = []          ## security cruisers
var parked: Array = []
var active: Array = []           ## moving cars currently on the road (civilians + patrols)
var occ := {}                    ## lane id -> Array of cars, sorted by s
var reserved := {}               ## connector id -> Array of cars
var obstacles: Array = []        ## [pos, vel, half_len, kind] player + loose cars
var ready_ok := false
var night := true
var stats := {"spawned": 0, "despawned": 0, "dead_end": 0, "lane_changes": 0, "junctions": 0, "honks": 0,
	"knocked": 0, "recovered": 0, "ai_collisions": 0, "max_stall": 0.0, "distance_km": 0.0, "car_seconds": 0.0}
var collision_log: Array = []    ## the first AI-AI overlaps (tests)
var _tick := 0
var _slow_t := 0.0
var _road_lanes: Array = []
var _road_cum := PackedFloat32Array()
var _spots: Array = []
var _tails: Array = []
var _horns: Array = []
var _horn_stream: AudioStreamWAV
var _fps_acc := 0.0
var _fps_n := 0
var _patrol_t := 20.0
var _overlap := {}
var _hero_rid := RID()


func setup(m: Node3D, opts := {}) -> bool:
	main = m
	rng.seed = int(opts.get("seed", 7))
	max_count = int(opts.get("max", max_count))
	if opts.has("count"):
		target = int(opts.count)
		fixed_count = true
	target = mini(target, max_count)
	graph = LaneGraph.new()
	var wpath := String(opts.get("world", ""))
	if wpath == "" and not opts.get("town_only", false):
		for p in WORLD_PATHS:
			if FileAccess.file_exists(p):
				wpath = p
				break
	if wpath != "" and FileAccess.file_exists(wpath):
		var w = JSON.parse_string(FileAccess.get_file_as_string(wpath))
		if w is Dictionary:
			graph.build_from_world(w)
			var sp = w.get("spawn")
			if sp is Dictionary and sp.has("pos"):
				var q: Array = sp.pos
				world_spawn = Vector3(q[0], q[2], -q[1]) if String(w.get("up", "y")) == "z" else Vector3(q[0], q[1], q[2])
	elif main.town and main.town.layout:
		var b: AABB = main.town.bounds
		var clip := AABB(b.position + Vector3(6, -1000, 6), b.size - Vector3(12, -2000, 12))
		graph.build_from_town(main.town.layout, clip)
	if graph.lanes.is_empty():
		push_warning("traffic: no lanes")
		return false
	print("traffic: lane graph ", JSON.stringify(graph.summary()))
	for l in graph.lanes:
		if l.junction < 0 and l.length > 20.0:
			_road_lanes.append(l)
	var acc := 0.0
	for l in _road_lanes:
		acc += l.length
		_road_cum.append(acc)
	# small maps: at most ~38 moving cars per lane-km by default (the town has 1.4 km of lanes)
	if not fixed_count:
		max_count = mini(max_count, maxi(min_count, int(acc / 1000.0 * 38.0)))
		target = mini(target, max_count)
	lib = VehicleLib.new()
	lib.load_index()
	print("traffic: %d vehicle models from %s in %d ms (%s), variant materials %s" % [lib.models.size(), lib.source, lib.load_ms,
		", ".join(lib.models.map(func(x): return "%s %d LODs %d variants" % [x.name, x.lods.size(), x.variants.size()])), JSON.stringify(lib.variant_paths)])
	signals = Signals.new()
	signals.name = "Signals"
	add_child(signals)
	signals.setup(graph, rng)
	signals.demand_fn = _demand
	_make_horn()
	for i in max_count:
		var c = _new_car(lib.pick(rng, false), i)
		cars.append(c)
	for i in patrol_count:
		var c = _new_car(lib.pick(rng, true), max_count + i)
		c.patrol = true
		patrols.append(c)
	for i in spot_lights:
		var sl := SpotLight3D.new()
		sl.light_color = Color(1.0, 0.94, 0.82)
		sl.light_energy = 6.0
		sl.spot_range = 38.0
		sl.spot_angle = 30.0
		sl.spot_angle_attenuation = 0.8
		sl.light_volumetric_fog_energy = 0.5
		sl.visible = false
		add_child(sl)
		_spots.append(sl)
		var tl := OmniLight3D.new()
		tl.light_color = Color(1.0, 0.05, 0.03)
		tl.omni_range = 4.5
		tl.light_energy = 0.8
		tl.visible = false
		add_child(tl)
		_tails.append(tl)
	if main.car:
		main.car.collision_mask |= 2
		_hero_rid = main.car.get_rid()
	_late_setup.call_deferred(opts)
	return true


func _late_setup(opts: Dictionary) -> void:
	# lanes onto the real road surface once the town's collision is in the physics space
	await get_tree().physics_frame
	await get_tree().physics_frame
	if main.town and main.town.layout:
		var n: int = graph.snap_to_ground(get_world_3d().direct_space_state, 1, [_hero_rid])
		print("traffic: %d lane samples snapped to the road surface" % n)
	signals.ground_heads(get_world_3d().direct_space_state, [_hero_rid])
	if not opts.get("no_parked", false):
		_spawn_parked()
	if opts.get("peds", true) and Pedestrians:
		peds = Pedestrians.new()
		peds.name = "Pedestrians"
		add_child(peds)
		peds.setup(self, int(opts.get("peds_count", 40)))
	_fill(true)
	ready_ok = true


func _new_car(model, i: int):
	var c := TrafficCar.new()
	c.name = "Traffic%d" % i
	add_child(c)
	c.build(model, lib, i)
	return c


# ================================================================== spawning
func _player_pos() -> Vector3:
	var pf = main.get("player_focus")         # on foot (scripts/waker/): traffic lives round the Waker
	if pf and is_instance_valid(pf):
		return pf.global_position
	return main.car.global_position if main.car else Vector3.ZERO


func _cam() -> Camera3D:
	return get_viewport().get_camera_3d()


func _in_view(p: Vector3, dist: float) -> bool:
	var cam := _cam()
	if cam == null:
		return false
	if cam.global_position.distance_to(p) > 170.0:
		return false
	return cam.is_position_in_frustum(p + Vector3.UP)


func _random_road_spot() -> Array:
	var r := rng.randf() * _road_cum[_road_cum.size() - 1]
	var lo := 0
	var hi := _road_cum.size() - 1
	while lo < hi:
		var mid := (lo + hi) >> 1
		if _road_cum[mid] < r:
			lo = mid + 1
		else:
			hi = mid
	var l = _road_lanes[lo]
	return [l, rng.randf_range(4.0, l.length - 8.0)]


## A random road-lane spot in the ring [rmin, rmax] around p (spatial grid; big worlds).
func _spot_near(p: Vector3, rmin: float, rmax: float) -> Array:
	for k in 6:
		var a := rng.randf() * TAU
		var r := sqrt(rng.randf_range(rmin * rmin, rmax * rmax))
		var q := p + Vector3(cos(a) * r, 0.0, sin(a) * r)
		var hit: Array = graph.nearest(q, 20.0, true)
		if hit[0] >= 0:
			var l = graph.lanes[hit[0]]
			if l.length > 20.0:
				return [l, clampf(hit[1], 4.0, l.length - 8.0)]
	return []


func _lane_free(l, s: float, gap: float) -> bool:
	for c in occ.get(l.id, []):
		if absf(c.s - s) < gap:
			return false
	for nb in [l.left, l.right]:
		if nb >= 0:
			for c in occ.get(nb, []):
				if absf(c.s - s) < gap * 0.6:
					return false
	return true


func _fill(initial: bool) -> void:
	var want := target - active.filter(func(c): return not c.patrol).size()
	var tries := want * 6 if initial else 10
	var pp := _player_pos()
	var big := _road_cum[_road_cum.size() - 1] > 8000.0      # lanes far beyond the ring: sample near the player
	while want > 0 and tries > 0:
		tries -= 1
		var spot := _spot_near(pp, 25.0 if initial else ring_min, ring_max) if big else _random_road_spot()
		if spot.is_empty():
			continue
		var l = spot[0]
		var s: float = spot[1]
		var p: Vector3 = l.pos_at(s)
		var d := p.distance_to(pp)
		if d < (25.0 if initial else ring_min) or d > ring_max:
			continue
		if not initial and _in_view(p, d):
			continue
		if not _lane_free(l, s, 16.0):
			continue
		var c = _free_car()
		if c == null:
			break
		_place(c, l, s)
		want -= 1


func _free_car():
	var free := cars.filter(func(c): return c.mode == TrafficCar.OFF)
	if free.is_empty():
		return null
	return free[rng.randi() % free.size()]


func _place(c, l, s: float) -> void:
	c.lane = l.id
	c.s = s
	c.seg = l.seg_at(s, 0)
	c.drive_factor = rng.randf_range(0.82, 1.12) * (1.12 if c.patrol else 1.0)
	c.v = l.speed * c.drive_factor * 0.8
	c.acc = 0.0
	c.lat = 0.0
	c.lc_t = 1.0
	c.yaw_off = 0.0
	c.lc_cool = rng.randf_range(2.0, 6.0)
	c.wait_t = 0.0
	c.stall_t = 0.0
	c.honk_cool = rng.randf_range(0.0, 5.0)
	c.cleared = false
	c.reserved = -1
	c.stopped_at_line = false
	c.progress = 0.0
	c.last_progress = 0.0
	c.spawn_t = 0.0
	c.mode = TrafficCar.KINEMATIC
	c.set_variant(VehicleLib.pick_variant(c.model, rng, c.patrol))
	c.set_braking(false, lib)
	c.activate()
	_enter_lane(c)
	_pose(c, 0.0)
	var cam := _cam()
	c.update_lods(c.global_position.distance_to(cam.global_position if cam else _player_pos()))
	c.reset_physics_interpolation()
	active.append(c)
	_occ_add(c)
	stats.spawned += 1
	c.show_bar(c.patrol)
	if c.patrol:
		c.set_lightbar(rng.randf() < 0.6, lib)


func _despawn(c) -> void:
	_unreserve(c)
	c.deactivate()
	active.erase(c)
	stats.despawned += 1


# ================================================================== lanes / routes
func _enter_lane(c) -> void:
	var l = graph.lanes[c.lane]
	c.cleared = false
	c.stopped_at_line = false
	c.wait_t = 0.0
	if l.junction >= 0:
		c.nxt = l.next[0] if not l.next.is_empty() else -1
		c.plan = -1
		_unreserve(c)
		stats.junctions += 1
	else:
		c.plan = _choose_connector(c, l, true)
		c.nxt = c.plan if c.plan >= 0 and graph.lanes[c.plan].src == l.id else -1
		if c.plan < 0 and not l.next.is_empty():
			c.nxt = l.next[0]


## Pick the connector to take at the end of lane l: any connector leaving l's lane group (a lane
## change gets the car to its source lane), weighted straight > kerb turn > far turn > U-turn.
## Patrols drift towards the player.
func _choose_connector(c, l, whole_group: bool) -> int:
	var cand := []
	var lanes_from: Array = graph.groups[l.group] if whole_group and l.group >= 0 else [l.id]
	for li in lanes_from:
		for k in graph.lanes[li].next:
			cand.append(k)
	if cand.is_empty():
		return -1
	var w := []
	var tot := 0.0
	var pp := _player_pos()
	for k in cand:
		var cl = graph.lanes[k]
		var x: float = [0.55, 0.25, 0.2, 0.02][cl.turn]
		if cl.src != l.id:
			x *= 0.6
		# avoid heading into dead ends when there is a choice
		var ex = graph.lanes[cl.dst]
		if ex.next.is_empty() and ex.length < 60.0:
			x *= 0.3
		if c.patrol:
			var tip: Vector3 = ex.pts[mini(ex.pts.size() - 1, 10)]
			x *= 1.0 + 2.0 * maxf(0.0, (tip - cl.pts[0]).normalized().dot((pp - cl.pts[0]).normalized()))
		w.append(x)
		tot += x
	var r := rng.randf() * tot
	for i in cand.size():
		r -= w[i]
		if r <= 0.0:
			return cand[i]
	return cand[0]


## Cars within 45 m of the stop line of a junction approach (actuated signals).
func _demand(j: int, ai: int) -> int:
	var n := 0
	for li in graph.junctions[j].approaches[ai].lanes:
		var l = graph.lanes[li]
		for c in occ.get(li, []):
			if l.length - c.s < 45.0:
				n += 1
	return n


func _unreserve(c) -> void:
	if c.reserved >= 0:
		var arr: Array = reserved.get(c.reserved, [])
		arr.erase(c)
		c.reserved = -1


func _occ_add(c) -> void:
	if not occ.has(c.lane):
		occ[c.lane] = []
	occ[c.lane].append(c)


func _rebuild_occ() -> void:
	occ.clear()
	for c in active:
		if c.mode == TrafficCar.KINEMATIC or c.mode == TrafficCar.RECOVER:
			_occ_add(c)
			if c.lc_t < 0.6 and c.lc_from >= 0:
				if not occ.has(c.lc_from):
					occ[c.lc_from] = []
				occ[c.lc_from].append(c)
	for k in occ:
		occ[k].sort_custom(func(a, b): return a.s < b.s)


# ================================================================== per tick
var prof := {"ticks": 0, "total_us": 0, "think_us": 0, "advance_us": 0, "occ_us": 0, "house_us": 0}


func _physics_process(dt: float) -> void:
	if not ready_ok:
		return
	var t0 := Time.get_ticks_usec()
	_physics_inner(dt)
	prof.ticks += 1
	prof.total_us += Time.get_ticks_usec() - t0


func _physics_inner(dt: float) -> void:
	_tick += 1
	signals.step(dt)
	var ta := Time.get_ticks_usec()
	if _tick % 2 == 0:
		_rebuild_occ()
		_collect_obstacles()
	prof.occ_us += Time.get_ticks_usec() - ta
	_check_hero_contacts()
	for c in active.duplicate():
		match c.mode:
			TrafficCar.KINEMATIC:
				if (c.idx + _tick) % ai_div == 0:
					var tb := Time.get_ticks_usec()
					_think(c, dt * ai_div)
					prof.think_us += Time.get_ticks_usec() - tb
				var tc := Time.get_ticks_usec()
				_advance(c, dt)
				prof.advance_us += Time.get_ticks_usec() - tc
			TrafficCar.DYNAMIC:
				_dynamic_step(c, dt)
			TrafficCar.RECOVER:
				_recover_step(c, dt)
		if c.patrol and c.mode != TrafficCar.OFF:
			c.flash(dt, lib)
	for p in parked:
		if p.mode == TrafficCar.DYNAMIC:
			_parked_dynamic(p, dt)
	if _tick % 30 == 0:
		var td := Time.get_ticks_usec()
		_housekeeping()
		prof.house_us += Time.get_ticks_usec() - td
	if _tick % 15 == 7:
		_count_overlaps()


func _process(delta: float) -> void:
	if not ready_ok:
		return
	_fps_acc += delta
	_fps_n += 1


func _housekeeping() -> void:
	var pp := _player_pos()
	var cam := _cam()
	var cp: Vector3 = cam.global_position if cam else pp
	for c in active.duplicate():
		var p: Vector3 = c.global_position
		var d := p.distance_to(pp)
		c.far = p.distance_to(cp) > 110.0
		c.update_lods(p.distance_to(cp))
		c.set_collision(d < near_radius or c.mode != TrafficCar.KINEMATIC)
		if c.mode == TrafficCar.KINEMATIC and d > ring_max + 30.0 and not _in_view(p, d):
			_despawn(c)
		elif c.stall_t > 90.0 and not _in_view(p, d) and d > 40.0:
			_despawn(c)   # last resort against gridlock; counted by the tests via max_stall
	for p in parked:
		p.set_collision(p.global_position.distance_to(pp) < near_radius * 1.5 or p.mode == TrafficCar.DYNAMIC)
		p.update_lods(p.global_position.distance_to(cp))
	_fill(false)
	_patrol_logic(0.25)
	_assign_lights()
	_adapt_count()


func _adapt_count() -> void:
	if fixed_count or _fps_n < 10:
		return
	var fps := _fps_n / maxf(_fps_acc, 1e-3)
	if _fps_acc < 2.0:
		return
	_fps_acc = 0.0
	_fps_n = 0
	if fps < 72.0 and target > min_count:
		target = maxi(min_count, target - 4)
	elif fps > 110.0 and target < max_count:
		target = mini(max_count, target + 2)


# ------------------------------------------------------------------ kinematic motion
func _advance(c, dt: float) -> void:
	c.v = maxf(0.0, c.v + c.acc * dt)
	c.s += c.v * dt
	c.progress += c.v * dt
	stats.distance_km += c.v * dt * 0.001
	stats.car_seconds += dt
	c.spawn_t += dt
	var l = graph.lanes[c.lane]
	while c.s > l.length:
		var n: int = c.nxt
		if n < 0:
			stats.dead_end += 1
			_despawn(c)
			return
		c.s -= l.length
		var old: Array = occ.get(c.lane, [])
		old.erase(c)
		c.lane = n
		c.seg = 0
		l = graph.lanes[n]
		if not occ.has(n):
			occ[n] = []
		occ[n].insert(0, c)
		_enter_lane(c)
	if c.lc_t < 1.0:
		c.lc_t = minf(1.0, c.lc_t + dt / c.lc_dur)
	if not c.far or (_tick + c.idx) % 3 == 0:
		_pose(c, dt if not c.far else dt * 3.0)


func _pose(c, dt: float) -> void:
	var l = graph.lanes[c.lane]
	c.seg = l.seg_at(c.s, c.seg)
	var p: Vector3 = _lane_point(l, c.s, c.seg)
	# heading from the axles: chord across the wheelbase (bicycle-like turn-in on bends)
	var hb := 1.35
	var front := _point_ahead(c, l, hb)
	var back: Vector3 = l.pos_at(maxf(0.0, c.s - hb)) if c.s > hb else p - (front - p)
	var fwd := front - back
	if fwd.length_squared() < 1e-6:
		fwd = l.dir_at_seg(c.seg)
	fwd = fwd.normalized()
	# lane change: smoothstep lateral offset and the yaw that goes with it
	var lat := 0.0
	if c.lc_t < 1.0:
		var t: float = c.lc_t
		var sm := t * t * (3.0 - 2.0 * t)
		lat = c.lat0 * (1.0 - sm)
		var dlat_ds: float = -c.lat0 * 6.0 * t * (1.0 - t) / maxf(c.lc_dur * maxf(c.v, 2.0), 1.0)
		fwd = fwd.rotated(Vector3.UP, -atan(dlat_ds))
	c.lat = lat
	var right := fwd.cross(Vector3.UP).normalized()
	p += right * lat
	var x := Vector3.UP.cross(fwd).normalized()
	var y := fwd.cross(x).normalized()
	c.global_transform = Transform3D(Basis(x, y, fwd), p)
	if dt > 0.0 and c.lod_nodes.size() > 0:
		c.spin_wheels(dt)


func _lane_point(l, s: float, seg: int) -> Vector3:
	var a: float = l.cum[seg]
	var b: float = l.cum[seg + 1]
	return l.pts[seg].lerp(l.pts[seg + 1], clampf((s - a) / maxf(b - a, 1e-4), 0.0, 1.0))


## Point ds metres ahead of the car along its route (into the next lane if needed).
func _point_ahead(c, l, ds: float) -> Vector3:
	var s2: float = c.s + ds
	if s2 <= l.length or c.nxt < 0:
		return l.pos_at(minf(s2, l.length))
	var n = graph.lanes[c.nxt]
	return n.pos_at(minf(s2 - l.length, n.length))


# ------------------------------------------------------------------ AI
func _think(c, dt: float) -> void:
	var l = graph.lanes[c.lane]
	c.lc_cool -= dt
	c.honk_cool -= dt
	var v0: float = l.speed * c.drive_factor
	# 1. leader on the route
	var lead := _leader(c, l)
	var gap: float = lead[0]
	var lv: float = lead[1]
	if c.lc_t < 0.7 and c.lc_from >= 0:
		for o in occ.get(c.lc_from, []):
			if o != c and o.s > c.s - 1.0:
				var g2: float = o.s - c.s - c.half_len - o.half_len
				if g2 < gap:
					gap = g2
					lv = o.v
				break
	var reason := "leader" if gap < 60.0 else ""
	# 2. player / loose cars in the path
	var ob := _obstacle_ahead(c, l)
	var by_player := false
	if ob[0] < gap:
		gap = ob[0]
		lv = ob[1]
		by_player = ob[2]
		reason = "player" if by_player else "wreck"
	# 3. junction ahead: signals, priorities, space behind the junction
	if l.junction < 0 and l.end_junction >= 0 and not c.cleared:
		var to_line: float = l.length - c.s - c.half_len - 0.8
		var look: float = maxf(45.0, c.v * c.v / (2.0 * B_COMF) + 20.0)
		if to_line < look:
			var ok := _may_enter(c, l, to_line)
			if not ok:
				if to_line < gap:
					gap = maxf(to_line, 0.0)
					lv = 0.0
					reason = c.wait_reason
				if c.v < 0.5:
					c.wait_t += dt
			elif to_line < maxf(6.0, c.v * 1.6) and c.nxt >= 0 and graph.lanes[c.nxt].junction >= 0:
				c.cleared = true
				if c.nxt >= 0 and graph.lanes[c.nxt].junction >= 0:
					c.reserved = c.nxt
					if not reserved.has(c.nxt):
						reserved[c.nxt] = []
					reserved[c.nxt].append(c)
	# 4. IDM
	var dv: float = c.v - lv
	var s_star: float = S0 + maxf(0.0, c.v * T_HEAD + c.v * dv / (2.0 * sqrt(A_MAX * B_COMF)))
	var free_term := 1.0 - pow(c.v / maxf(v0, 0.5), 4.0)
	var inter := (s_star / maxf(gap, 0.1)) ** 2 if gap < 200.0 else 0.0
	c.acc = clampf(A_MAX * (free_term - inter), -8.0, A_MAX)
	if gap < 0.3:
		c.acc = minf(c.acc, -c.v / maxf(dt, 0.05))
	c.leader_gap = gap
	# 5. lane changes
	if c.lc_t >= 1.0 and l.junction < 0 and not c.cleared and (l.left >= 0 or l.right >= 0):
		_lane_change_logic(c, l, lead, v0)
	# 6. lights, horn, stall bookkeeping
	c.set_braking(c.acc < -0.6 or c.v < 0.4, lib)
	if by_player and c.v < 1.0 and gap < 10.0:
		c.blocked_by_player_t += dt
	else:
		c.blocked_by_player_t = 0.0
	# drivers mind their own business: only a long hold-up by the player gets the odd honk
	if c.honk_cool <= 0.0 and c.blocked_by_player_t > 8.0:
		c.honk_cool = rng.randf_range(25.0, 45.0)
		if rng.randf() < 0.3:
			_honk(c)
	if c.v < 0.3:
		c.stall_t += dt
	else:
		c.stall_t = 0.0
	c.wait_reason = reason
	stats.max_stall = maxf(stats.max_stall, c.stall_t)


## [gap (bumper to bumper), leader speed] along the lane and the next two lanes.
func _leader(c, l) -> Array:
	var arr: Array = occ.get(l.id, [])
	var best := INF
	var bv := 0.0
	for o in arr:
		if o != c and o.s > c.s:
			best = o.s - c.s - c.half_len - o.half_len
			bv = o.v
			break
	if best < INF:
		return [best, bv]
	var dist: float = l.length - c.s
	var ln: int = c.nxt
	var hops := 0
	while ln >= 0 and dist < LOOK and hops < 3:
		var nl = graph.lanes[ln]
		var a2: Array = occ.get(ln, [])
		if not a2.is_empty():
			var o = a2[0]
			return [dist + o.s - c.half_len - o.half_len, o.v]
		# cars merging into the exit lane from other connectors also count (they are on conflicting connectors)
		dist += nl.length
		ln = nl.next[0] if nl.junction >= 0 and not nl.next.is_empty() else -1
		hops += 1
	return [INF, 0.0]


func _collect_obstacles() -> void:
	obstacles.clear()
	if main.car and not ignore_player:
		obstacles.append([main.car.global_position, main.car.linear_velocity, 2.25, true, main.car, 0.95])
	for c in active:
		if c.mode == TrafficCar.DYNAMIC or c.mode == TrafficCar.RECOVER:
			obstacles.append([c.global_position, c.linear_velocity if c.mode == TrafficCar.DYNAMIC else Vector3.ZERO, c.half_len, false, c, c.half_w])
	for p in parked:
		if p.mode == TrafficCar.DYNAMIC:
			obstacles.append([p.global_position, p.linear_velocity, p.half_len, false, p, p.half_w])
	if peds:
		peds.add_obstacles(obstacles)
	# the Waker on foot (scripts/waker/): cars stop for them; sleepers and a courier's car too
	var pf = main.get("player_focus")
	if pf and is_instance_valid(pf) and not ignore_player:
		obstacles.append([pf.global_position, pf.velocity, 0.35, true, pf, 0.35])
	for s in get_tree().get_nodes_in_group("sleeper"):
		if s.visible and s.global_position.distance_squared_to(_player_pos()) < 90000.0:
			obstacles.append([s.global_position, s.velocity, 0.35, false, s, 0.35])


## [gap, speed along my heading, is player] for the nearest obstacle on my path.
func _obstacle_ahead(c, l) -> Array:
	var best := [INF, 0.0, false]
	var p: Vector3 = c.global_position
	var fwd: Vector3 = c.global_basis.z
	for ob in obstacles:
		if ob[4] == c:
			continue
		var rel: Vector3 = ob[0] - p
		var along := rel.dot(fwd)
		if along < 0.0 or along > 45.0:
			continue
		var q := _point_ahead(c, l, along)
		var lat := Vector2(ob[0].x - q.x, ob[0].z - q.z).length()
		var lim: float = c.half_w + float(ob[5]) + 0.35
		if lat > lim or absf(ob[0].y - q.y) > 3.0:
			continue
		var gap: float = along - c.half_len - ob[2]
		if gap < best[0]:
			best = [gap, maxf(0.0, (ob[1] as Vector3).dot(fwd)), ob[3]]
	return best


## May this car enter the junction at the end of lane l?  Sets c.wait_reason when not.
func _may_enter(c, l, to_line: float) -> bool:
	var conn: int = c.nxt
	if conn < 0 or graph.lanes[conn].junction < 0:
		if c.plan >= 0 and graph.lanes[c.plan].src != l.id:
			c.wait_reason = "lane"     # still has to change lanes for its turn
			return to_line > 12.0
		return true
	var cl = graph.lanes[conn]
	var J = graph.junctions[cl.junction]
	var st: int = signals.state(J.id, l.approach)
	if st == Signals.RED:
		c.wait_reason = "signal"
		return false
	if st == Signals.AMBER and to_line > c.v * c.v / (2.0 * 3.2) + 1.0:
		c.wait_reason = "signal"
		return false
	if J.control == "stop" and not c.stopped_at_line:
		if c.v < 0.6 and to_line < 3.5:
			c.stopped_at_line = true
		else:
			c.wait_reason = "stop"
			return false
	# exit lane must have room (don't block the box)
	var ex: Array = occ.get(cl.dst, [])
	if not ex.is_empty() and ex[0].s < ex[0].half_len + c.half_len + 4.0 and ex[0].v < 3.0:
		c.wait_reason = "box"
		return false
	var patient: bool = c.wait_t > 9.0
	# conflicting connectors in use / reserved
	for k in cl.conflicts:
		for o in occ.get(k, []):
			if not patient or o.global_position.distance_to(c.global_position) < 18.0 or o.v > 1.0:
				c.wait_reason = "junction"
				return false
		for o in reserved.get(k, []):
			if o != c:
				c.wait_reason = "junction"
				return false
	# yield to higher-priority traffic arriving soon on conflicting connectors
	if not patient:
		for k in cl.conflicts:
			var kl = graph.lanes[k]
			if kl.rank <= cl.rank:
				continue
			var sl = graph.lanes[kl.src]
			if signals.state(J.id, sl.approach) == Signals.RED:
				continue
			for o in occ.get(kl.src, []):
				if o.nxt != k:
					continue
				var d: float = sl.length - o.s
				if d < 40.0 and d / maxf(o.v, 1.5) < 4.0:
					c.wait_reason = "yield"
					return false
	return true


func _lane_change_logic(c, l, lead: Array, v0: float) -> void:
	if c.lc_cool > 0.0 or c.s < 6.0 or l.length - c.s < 18.0:
		# too late for the planned lane: take a turn from this lane instead
		if c.plan >= 0 and graph.lanes[c.plan].src != l.id and l.length - c.s < 18.0:
			c.plan = _choose_connector(c, l, false)
			c.nxt = c.plan
			c.cleared = false
			_unreserve(c)
		return
	var want := 0     # -1 left, +1 right
	var mandatory := false
	if c.plan >= 0:
		var src: int = graph.lanes[c.plan].src
		if src != l.id:
			var tgt = graph.lanes[src]
			want = -1 if tgt.kerb_index < l.kerb_index else 1
			# kerb index grows away from the kerb; kerb side is travel-left when driving on the left
			if graph.drive_side != "left":
				want = -want
			mandatory = true
	if want == 0 and lead[0] < 30.0 and lead[1] < v0 * 0.7:
		want = -1 if rng.randf() < 0.5 else 1
	if want == 0:
		return
	var target: int = l.left if want < 0 else l.right
	if target < 0:
		target = l.right if want < 0 else l.left
		if mandatory or target < 0:
			return
	var tl = graph.lanes[target]
	var s_t: float = clampf(c.s * tl.length / maxf(l.length, 1.0), 0.0, tl.length - 1.0)
	# gaps in the target lane
	var ahead := INF
	var av := 0.0
	var behind := INF
	var bv := 0.0
	for o in occ.get(target, []):
		var d: float = o.s - s_t
		if d >= 0.0 and d < ahead:
			ahead = d - c.half_len - o.half_len
			av = o.v
		elif d < 0.0 and -d < behind:
			behind = -d - c.half_len - o.half_len
			bv = o.v
	var safe: bool = ahead > 5.0 + maxf(0.0, c.v - av) * 1.6 and behind > 5.0 + maxf(0.0, bv - c.v) * 2.0
	if not safe:
		return
	if not mandatory and ahead < lead[0] + 12.0:
		return     # no real gain
	# go: the car switches lane now and slides across the offset
	var p_old: Vector3 = c.global_position
	c.lc_from = c.lane
	c.cleared = false
	_unreserve(c)
	c.lane = target
	c.s = s_t
	c.seg = tl.seg_at(s_t, 0)
	var q: Vector3 = tl.pos_at(s_t)
	var fwd: Vector3 = tl.dir_at_seg(c.seg)
	var right: Vector3 = fwd.cross(Vector3.UP).normalized()
	c.lat0 = (p_old - q).dot(right)
	c.lc_t = 0.0
	c.lc_dur = clampf(2.2 + absf(c.lat0) * 0.25, 2.2, 4.0)
	c.lc_cool = rng.randf_range(5.0, 10.0)
	_occ_add(c)
	occ[target].sort_custom(func(a, b): return a.s < b.s)
	if not mandatory:
		c.plan = _choose_connector(c, tl, false)
	c.nxt = c.plan if c.plan >= 0 and graph.lanes[c.plan].src == tl.id else (tl.next[0] if not tl.next.is_empty() else -1)
	stats.lane_changes += 1


# ------------------------------------------------------------------ physics hand-off
var _hero_prev_vel := Vector3.ZERO


## The hero car must never hit a frozen (infinite-mass) traffic car: that stops it dead. Cars the
## hero is about to touch become real rigid bodies a moment *before* contact, so the crash is
## between two masses. If contact still happens first (very fast, or spawned in the way), the hero's
## pre-contact speed is restored and shared as an inelastic crash.
func _check_hero_contacts() -> void:
	var hero = main.car
	if hero == null:
		return
	var hv: Vector3 = hero.linear_velocity
	var hp: Vector3 = hero.global_position
	var speed := hv.length()
	# 1) predictive: wake anything inside the reach of the next ~0.25 s
	if speed > 1.0:
		var reach := 3.2 + speed * 0.25
		for c in active:
			if c.mode != TrafficCar.KINEMATIC and c.mode != TrafficCar.PARKED and c.mode != TrafficCar.RECOVER:
				continue
			var d: Vector3 = c.global_position - hp
			d.y = 0.0
			var dist := d.length()
			if dist > reach + c.half_len:
				continue
			var cv: Vector3 = c.global_basis.z * c.v if c.mode == TrafficCar.KINEMATIC else Vector3.ZERO
			var closing := (hv - cv).dot(d / maxf(dist, 0.01))
			if closing > 0.5 or dist < c.half_len + 2.6:
				_knock(c)
	# 2) contact already happened with a frozen car: undo the dead stop, share momentum
	if hero.get_contact_count() > 0:
		for b in hero.get_colliding_bodies():
			if b is TrafficCar and (b.mode == TrafficCar.KINEMATIC or b.mode == TrafficCar.PARKED or b.mode == TrafficCar.RECOVER):
				_knock(b)
				var m1: float = hero.mass
				var m2: float = b.mass
				var v_common: Vector3 = (_hero_prev_vel * m1 + b.linear_velocity * m2) / (m1 + m2)
				hero.linear_velocity = v_common.lerp(_hero_prev_vel, 0.25)
				b.linear_velocity = v_common + (_hero_prev_vel - v_common) * 0.35
	_hero_prev_vel = hero.linear_velocity


func _knock(c) -> void:
	_unreserve(c)
	var vel: Vector3 = c.global_basis.z * c.v if c.mode == TrafficCar.KINEMATIC else Vector3.ZERO
	var was_parked: bool = c.mode == TrafficCar.PARKED
	c.mode = TrafficCar.DYNAMIC
	c.set_collision(true)
	c.freeze = false
	c.linear_velocity = vel
	c.contact_monitor = true
	c.max_contacts_reported = 4
	c.dyn_t = 0.0
	c.rest_t = 0.0
	c.v = 0.0
	c.set_braking(true, lib)
	if not was_parked:
		stats.knocked += 1
		if c.honk_cool <= 0.0 and rng.randf() < 0.35:      # rammed: sometimes a honk, not always
			c.honk_cool = 20.0
			_honk(c)


func _dynamic_step(c, dt: float) -> void:
	c.dyn_t += dt
	# chain reactions: a loose car knocks the kinematic cars it hits loose too
	if c.get_contact_count() > 0 and c.linear_velocity.length() > 2.0:
		for b in c.get_colliding_bodies():
			if b is TrafficCar and b.mode == TrafficCar.KINEMATIC:
				_knock(b)
	if c.linear_velocity.length() < 0.7 and c.angular_velocity.length() < 0.6:
		c.rest_t += dt
	else:
		c.rest_t = 0.0
	if c.dyn_t > 3.0 and c.rest_t > 1.2:
		_begin_recover(c)
	elif c.dyn_t > 20.0:
		_begin_recover(c)


func _begin_recover(c) -> void:
	var p: Vector3 = c.global_position
	if main.car and main.car.global_position.distance_to(p) < 5.5 and c.dyn_t < 20.0:
		return     # still being pushed around by the player
	var upright: bool = c.global_basis.y.y > 0.7
	# the nearest lane going the way the car now faces (or any lane if it was spun round)
	var hit: Array = graph.nearest(p, 8.0, true, c.global_basis.z)
	if hit[0] < 0:
		hit = graph.nearest(p, 8.0, true)
	if hit[0] < 0 or not upright:
		if not _in_view(p, p.distance_to(_player_pos())) or c.dyn_t > 25.0:
			_despawn(c)
		return
	var l = graph.lanes[hit[0]]
	var seg: int = l.seg_at(hit[1], 0)
	c.mode = TrafficCar.RECOVER
	c.freeze = true
	c.contact_monitor = false
	c.lane = l.id
	c.s = clampf(hit[1], 0.0, l.length - 0.5)
	c.seg = seg
	c.v = 0.0
	c.acc = 0.0
	c.lc_t = 1.0
	c.rec_from = c.global_transform
	_enter_lane(c)
	_pose(c, 0.0)
	var cam := _cam()
	c.update_lods(c.global_position.distance_to(cam.global_position if cam else _player_pos()))
	c.rec_to = c.global_transform
	c.global_transform = c.rec_from
	c.rec_t = 0.0


func _recover_step(c, dt: float) -> void:
	c.rec_t += dt / 1.4
	var t := minf(c.rec_t, 1.0)
	var sm := t * t * (3.0 - 2.0 * t)
	var a: Transform3D = c.rec_from
	var b: Transform3D = c.rec_to
	c.global_transform = Transform3D(a.basis.orthonormalized().slerp(b.basis.orthonormalized(), sm), a.origin.lerp(b.origin, sm) + Vector3.UP * sin(t * PI) * 0.15)
	if t >= 1.0:
		c.mode = TrafficCar.KINEMATIC
		stats.recovered += 1


func _parked_dynamic(p, dt: float) -> void:
	p.dyn_t += dt
	if p.linear_velocity.length() < 0.4 and p.angular_velocity.length() < 0.4:
		p.rest_t += dt
	else:
		p.rest_t = 0.0
	if p.dyn_t > 2.0 and p.rest_t > 1.5:
		p.freeze_mode = RigidBody3D.FREEZE_MODE_STATIC
		p.freeze = true
		p.mode = TrafficCar.PARKED
		p.set_braking(false, lib)


# ------------------------------------------------------------------ AI collision accounting (tests)
func _count_overlaps() -> void:
	var list := active.filter(func(c): return c.mode == TrafficCar.KINEMATIC)
	var now := {}
	for i in list.size():
		var a = list[i]
		for k in range(i + 1, list.size()):
			var b = list[k]
			if absf(a.global_position.x - b.global_position.x) > 6.0 or absf(a.global_position.z - b.global_position.z) > 6.0:
				continue
			if _obb_overlap(a, b):
				var key := "%d_%d" % [a.idx, b.idx]
				now[key] = true
				if not _overlap.has(key):
					stats.ai_collisions += 1
					if collision_log.size() < 10:
						collision_log.append({"a": graph.lanes[a.lane].name, "b": graph.lanes[b.lane].name, "sa": snappedf(a.s, 0.1), "sb": snappedf(b.s, 0.1),
							"va": snappedf(a.v, 0.1), "vb": snappedf(b.v, 0.1), "lc": [snappedf(a.lc_t, 0.01), snappedf(b.lc_t, 0.01)],
							"pos": [snappedf(a.global_position.x, 0.1), snappedf(a.global_position.z, 0.1)]})
	_overlap = now


static func _obb_overlap(a, b) -> bool:
	# 2D separating axis test of the two footprints (shrunk 8 %)
	var pa := Vector2(a.global_position.x, a.global_position.z)
	var pb := Vector2(b.global_position.x, b.global_position.z)
	var fa := Vector2(a.global_basis.z.x, a.global_basis.z.z).normalized()
	var fb := Vector2(b.global_basis.z.x, b.global_basis.z.z).normalized()
	var ea := Vector2(a.half_len, a.half_w) * 0.92
	var eb := Vector2(b.half_len, b.half_w) * 0.92
	for ax in [fa, fa.orthogonal(), fb, fb.orthogonal()]:
		var ra := ea.x * absf(fa.dot(ax)) + ea.y * absf(fa.orthogonal().dot(ax))
		var rb := eb.x * absf(fb.dot(ax)) + eb.y * absf(fb.orthogonal().dot(ax))
		if absf((pb - pa).dot(ax)) > ra + rb:
			return false
	return true


# ------------------------------------------------------------------ parked cars
func _spawn_parked() -> void:
	var space := get_world_3d().direct_space_state
	var box := BoxShape3D.new()
	var qp := PhysicsShapeQueryParameters3D.new()
	qp.shape = box
	qp.collision_mask = 1
	var ray := PhysicsRayQueryParameters3D.new()
	ray.collision_mask = 1
	ray.exclude = [_hero_rid]
	qp.exclude = [_hero_rid]
	var placed := 0
	var models: Array = lib.models.filter(func(x): return x.has_civil())
	if models.is_empty():
		return
	var limit := int(maxf(10.0, parked_per_100m * _road_cum[_road_cum.size() - 1] / 200.0))
	limit = mini(limit, 70)
	for rd in graph.roads:
		var pts: PackedVector3Array = rd.pts
		if pts.size() < 4 or rd.parking.is_empty():
			continue
		var tmp := LaneGraph.Lane.new()
		tmp.pts = LaneGraph.resample(pts, 1.0)
		LaneGraph._finish_lane(tmp)
		for side in rd.parking:
			# "left" / "right": the kerb side (town sidewalk); {roff, dir}: a parking lane of the world
			var lane_park: bool = side is Dictionary
			var sgn := 1.0
			if lane_park:
				sgn = signf(side.roff) if side.roff != 0.0 else 1.0
			else:
				sgn = -1.0 if String(side) == "left" else 1.0
			var s := rng.randf_range(10.0, 30.0)
			while s < tmp.length - 14.0 and placed < limit:
				var m = models[rng.randi() % models.size()]
				var seg := tmp.seg_at(s, 0)
				var p := tmp.pos_at(s)
				var d := tmp.dir_at_seg(seg)
				d.y = 0.0
				d = d.normalized()
				var right := d.cross(Vector3.UP)
				# on the town's sidewalk (kerb + 1.2 m), or on the road edge for a world parking lane
				var off: float = absf(side.roff) if lane_park else rd.half_width + (1.35 if graph.source == "town_layout" else -1.1)
				var c: Vector3 = p + right * sgn * off
				s += rng.randf_range(7.0, 34.0)
				if _near_junction(c, 9.0):
					continue
				if main.town and main.town.has_method("ensure_collision"):
					main.town.ensure_collision(c)      # the world streams its collision
				# ground: flat under the whole footprint
				var hs := []
				for o in [Vector2(0, 0), Vector2(1, 1), Vector2(1, -1), Vector2(-1, 1), Vector2(-1, -1)]:
					var q: Vector3 = c + d * o.x * m.length * 0.45 + right * o.y * m.width * 0.45
					ray.from = q + Vector3.UP * 2.5
					ray.to = q - Vector3.UP * 3.0
					var h := space.intersect_ray(ray)
					if h.is_empty():
						break
					hs.append(h.position.y)
				if hs.size() < 5 or hs.max() - hs.min() > 0.18:
					continue
				var y: float = hs[0]
				var flip := rng.randf() < 0.5
				var fz := (d if (sgn < 0.0) == (graph.drive_side == "left") else -d) * (-1.0 if flip and rng.randf() < 0.2 else 1.0)
				if lane_park:
					fz = d * float(side.dir)
				var xf := Transform3D(Basis(Vector3.UP.cross(fz).normalized(), Vector3.UP, fz), Vector3(c.x, y + 0.02, c.z))
				box.size = Vector3(m.width + 0.3, 1.2, m.length + 0.4)
				qp.transform = Transform3D(xf.basis, xf.origin + Vector3.UP * 0.95)
				if not space.intersect_shape(qp, 1).is_empty():
					continue
				if _parked_clash(xf.origin, m.length):
					continue
				var car := TrafficCar.new()
				car.name = "Parked%d" % placed
				add_child(car)
				car.build(m, lib, 1000 + placed)
				car.set_variant(VehicleLib.pick_variant(m, rng))
				car.show_bar(false)
				car.mode = TrafficCar.PARKED
				car.freeze_mode = RigidBody3D.FREEZE_MODE_STATIC
				car.activate()
				car.global_transform = xf
				car.reset_physics_interpolation()
				car.head.visible = false
				car.tail.material_override = lib.tail_mat
				car.tail.visible = rng.randf() < 0.15
				parked.append(car)
				placed += 1
	print("traffic: %d parked cars" % placed)


func _near_junction(p: Vector3, extra: float) -> bool:
	for J in graph.junctions:
		if Vector2(p.x - J.pos.x, p.z - J.pos.z).length() < J.radius + extra:
			return true
	return false


func _parked_clash(p: Vector3, len: float) -> bool:
	for o in parked:
		if o.global_position.distance_to(p) < len + 1.0:
			return true
	return false


# ------------------------------------------------------------------ patrols
func _patrol_logic(dt: float) -> void:
	_patrol_t -= dt * 2.0     # called every 0.25 s
	var pp := _player_pos()
	for c in patrols:
		if c.mode != TrafficCar.OFF and c.lane >= 0 and c.global_position.distance_to(pp) > ring_max:
			_despawn(c)
	if _patrol_t > 0.0:
		return
	_patrol_t = rng.randf_range(25.0, 45.0)
	var free := patrols.filter(func(c): return c.mode == TrafficCar.OFF)
	if free.is_empty():
		return
	# appear out of view 70-170 m away on a lane heading towards the player
	for i in 30:
		var spot := _random_road_spot()
		var l = spot[0]
		var s: float = spot[1]
		var p: Vector3 = l.pos_at(s)
		var d := p.distance_to(pp)
		if d < 70.0 or d > 170.0 or _in_view(p, d) or not _lane_free(l, s, 20.0):
			continue
		if l.dir_at_seg(l.seg_at(s, 0)).dot((pp - p).normalized()) < 0.3:
			continue
		_place(free[0], l, s)
		return


## Force a patrol at a lane spot (screenshots).
func spawn_patrol_at(l, s: float, lightbar := true):
	var free := patrols.filter(func(c): return c.mode == TrafficCar.OFF)
	if free.is_empty():
		_despawn(patrols[0])
		free = [patrols[0]]
	_place(free[0], l, s)
	free[0].set_lightbar(lightbar, lib)
	return free[0]


# ------------------------------------------------------------------ lights / horn
func _assign_lights() -> void:
	var cam := _cam()
	if cam == null:
		return
	var cp := cam.global_position
	var near_list := active.filter(func(c): return c.global_position.distance_to(cp) < 70.0)
	near_list.sort_custom(func(a, b): return a.global_position.distance_squared_to(cp) < b.global_position.distance_squared_to(cp))
	for i in _spots.size():
		var sl: SpotLight3D = _spots[i]
		var tl: OmniLight3D = _tails[i]
		if i < near_list.size() and night:
			var c = near_list[i]
			if sl.get_parent() != c:
				sl.get_parent().remove_child(sl)
				c.add_child(sl)
				tl.get_parent().remove_child(tl)
				c.add_child(tl)
			var hp: Vector3 = (c.model.head_pos[0] + c.model.head_pos[1]) * 0.5
			sl.transform = Transform3D(Basis(Vector3.UP, PI) * Basis(Vector3.RIGHT, deg_to_rad(-5.0)), hp + Vector3(0, 0, 0.1))
			var tp: Vector3 = (c.model.tail_pos[0] + c.model.tail_pos[1]) * 0.5
			tl.position = tp + Vector3(0, 0, -0.3)
			tl.light_energy = 2.2 if c.braking else 0.7
			sl.visible = true
			tl.visible = true
		else:
			sl.visible = false
			tl.visible = false
	for c in active:
		c.head.visible = night


func _make_horn() -> void:
	var rate := 22050
	var n := int(rate * 0.42)
	var data := PackedByteArray()
	data.resize(n * 2)
	for i in n:
		var t := float(i) / rate
		var env := minf(1.0, t / 0.02) * minf(1.0, (0.42 - t) / 0.06)
		var x := 0.0
		for f in [415.0, 520.0]:
			x += signf(sin(TAU * f * t)) * 0.25 + sin(TAU * f * 2.0 * t) * 0.08
		data.encode_s16(i * 2, int(clampf(x * env, -1.0, 1.0) * 20000.0))
	_horn_stream = AudioStreamWAV.new()
	_horn_stream.format = AudioStreamWAV.FORMAT_16_BITS
	_horn_stream.mix_rate = rate
	_horn_stream.data = data
	for i in 3:
		var a := AudioStreamPlayer3D.new()
		a.stream = _horn_stream
		a.unit_size = 12.0
		a.max_distance = 120.0
		a.volume_db = -4.0
		add_child(a)
		_horns.append(a)


func _honk(c) -> void:
	stats.honks += 1
	for a in _horns:
		if not a.playing:
			a.global_position = c.global_position + Vector3.UP
			a.pitch_scale = rng.randf_range(0.9, 1.12)
			a.play()
			return


# ------------------------------------------------------------------ queries (hero autopilot, tests)
## Speed the hero autopilot may drive at so it does not run into traffic ahead.
func hero_safe_speed(car: Node3D) -> float:
	var p := car.global_position
	var fwd := car.global_basis.z
	var best := INF
	for c in active:
		var rel: Vector3 = c.global_position - p
		var along := rel.dot(fwd)
		if along < 0.0 or along > 40.0:
			continue
		if absf(rel.dot(car.global_basis.x)) > 2.4:
			continue
		best = minf(best, along - 4.6)
	for c in parked:
		var rel: Vector3 = c.global_position - p
		var along := rel.dot(fwd)
		if along > 0.0 and along < 25.0 and absf(rel.dot(car.global_basis.x)) < 2.0:
			best = minf(best, along - 4.6)
	if best == INF:
		return INF
	return sqrt(2.0 * 3.5 * maxf(0.0, best - 2.0))


func active_count() -> int:
	return active.size()


func summary() -> Dictionary:
	var by_mode := {}
	for c in active:
		by_mode[c.mode] = by_mode.get(c.mode, 0) + 1
	var d := stats.duplicate()
	d["active"] = active.size()
	d["target"] = target
	d["parked"] = parked.size()
	d["patrols_active"] = patrols.filter(func(c): return c.mode != TrafficCar.OFF).size()
	d["signal_phase_changes"] = signals.stats.phase_changes
	d["peds"] = peds.count() if peds else 0
	var n: float = maxf(1.0, prof.ticks)
	d["us_per_tick"] = {"total": int(prof.total_us / n), "think": int(prof.think_us / n), "advance": int(prof.advance_us / n),
		"occ": int(prof.occ_us / n), "house": int(prof.house_us / n)}
	return d
