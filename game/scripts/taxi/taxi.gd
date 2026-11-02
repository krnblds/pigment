extends Node3D
## Taxi: someone hails you at the kerb, you pull up beside them, they get in, you drive them to their
## address along the road network (GPS ribbon on the road, a light beacon at the stop), they get out
## and pay. The fare is flag + distance + waiting time; the tip and the star rating depend on how
## punctual and how smooth the ride was, and on who's in the back (a hurried salaryman, a nervous
## passenger just off a Noctis lease, a thrill seeker...). Earnings are saved to user://taxi.json.
##
##   N            skip this fare (a new one is offered)
##   --no-taxi    no fares     --taxi-save=<path>  save file     --taxi-test  headless test (taxi_tests.gd)

signal fare_started(info: Dictionary)
signal fare_finished(result: Dictionary)

const Data := preload("res://scripts/taxi/taxi_data.gd")
const TaxiHud := preload("res://scripts/taxi/taxi_hud.gd")
const CitizenLib := preload("res://scripts/npc/character/citizen_library.gd")
const LaneGraph := preload("res://scripts/traffic/lane_graph.gd")

enum { WAITING, TO_PICKUP, BOARDING, RIDING, ALIGHTING }
const STATE_NAMES := ["waiting", "to_pickup", "boarding", "riding", "alighting"]

## World districts (world.json, Blender x / y -> Godot x / -z): name, centre, radius (ellipse x / y), rot deg
const ISLANDS := [["Minato Port", Vector2(1520, 980), Vector2(470, 360), -14.0],
	["Kagero Hills", Vector2(-1380, 1330), Vector2(520, 430), 25.0],
	["Tenjin Corporate", Vector2(1260, -1230), Vector2(290, 240), 20.0]]
const SHINKAI := [["Yoimachi", Vector2(-720, 120), 190.0], ["Downtown", Vector2(-120, 150), 420.0],
	["Midtown", Vector2(-120, 150), 900.0]]

var main: Node3D
var graph
var hud
var rng := RandomNumberGenerator.new()
var state := WAITING
var save_path := "user://taxi.json"
var stats := {"earned": 0, "fares": 0, "stars_sum": 0.0, "best_tip": 0}
var auto_next := true                       ## offer a new fare after each ride (tests turn it off)

var pax := {}                               ## id, archetype, mood
var passenger: Node3D                       ## the citizen while visible (waiting, walking to / from the car)
var pickup_pos := Vector3.ZERO              ## where they stand
var pickup_road := Vector3.ZERO             ## the kerb lane point beside them
var dest_pos := Vector3.ZERO
var dest_road := Vector3.ZERO
var dest_lane := -1
var dest_name := ""
var route_pts := PackedVector3Array()
var route_cum := PackedFloat32Array()
var route_m := 0.0                          ## at pickup: the fare distance
var ride_t := 0.0
var wait_t := 0.0
var discomfort := 0.0
var crashes := 0
var peds := 0
var last_result := {}

var _ribbon: MeshInstance3D
var _ribbon_mesh: ImmediateMesh
var _beacon: MeshInstance3D
var _prev_v := Vector3.ZERO
var _walk_t := 0.0
var _off_t := 0.0
var _ribbon_t := 0.0
var _say_t := 0.0
var _crash_cd := 0.0
var _next_t := 1.5
var _route_i := 0


func setup(m: Node3D) -> void:
	main = m
	name = "Taxi"
	rng.randomize()
	if main.args.has("taxi-save"):
		save_path = String(main.args["taxi-save"])
	if main.args.has("taxi-test") or main.args.has("taxi-shots"):
		save_path = ""
		rng.seed = 11
	_load()
	hud = TaxiHud.new()
	hud.taxi = self
	add_child(hud)
	_make_ribbon()
	_make_beacon()
	if main.car and main.car.has_signal("impact"):
		main.car.impact.connect(_on_impact)
	if main.npc and main.npc.has_signal("pedestrian_hit"):
		main.npc.pedestrian_hit.connect(_on_ped_hit)


## Re-hook a new player car (garage swap).
func set_car(c: RigidBody3D) -> void:
	if c and c.has_signal("impact") and not c.impact.is_connected(_on_impact):
		c.impact.connect(_on_impact)


func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventKey and e.pressed and not e.echo and e.physical_keycode == KEY_N:
		if state == WAITING or state == TO_PICKUP:
			skip_fare()


# ================================================================== fares
func _graph():
	if graph == null and main.traffic and main.traffic.get("graph") and main.traffic.graph.lanes.size() > 0:
		graph = main.traffic.graph
	if graph == null and main.traffic == null:
		for p in ["res://assets/world/world.json"]:
			if FileAccess.file_exists(p):
				var w = JSON.parse_string(FileAccess.get_file_as_string(p))
				if w is Dictionary:
					graph = LaneGraph.new()
					graph.build_from_world(w)
	return graph


## Offer a new fare: a citizen hailing from the kerb 120-450 m away, reachable by road.
func new_fare() -> bool:
	if _graph() == null or main.car == null or not CitizenLib.available():
		return false
	_clear_passenger()
	var car_p: Vector3 = main.car.global_position
	var from := _car_lane()
	for attempt in 80:
		var c = _random_kerb(car_p, 120.0, 450.0)
		if c.is_empty():
			continue
		if from >= 0 and _route_between(from, c.lane, 0.0, c.s).is_empty():
			continue
		var ids := CitizenLib.ids()
		var id := ids[rng.randi() % ids.size()]
		var inf := CitizenLib.info(id)
		pax = {"id": id, "archetype": String(inf.get("archetype", "")), "mood": Data.mood_for(String(inf.get("archetype", "")), rng)}
		pickup_pos = c.kerb
		pickup_road = c.road
		passenger = CitizenLib.spawn(id, {"ragdoll": false, "umbrella": "", "shadows": true})
		add_child(passenger)
		passenger.global_position = pickup_pos
		passenger.look_at(Vector3(pickup_road.x, pickup_pos.y, pickup_road.z), Vector3.UP, true)
		passenger.set_activity("idle_lantern", 1.0)         # arm up: hailing
		if main.npc and main.npc.has_method("clear_around"):
			main.npc.clear_around(pickup_pos, 3.0)
		state = TO_PICKUP
		_set_route(from, c.lane, c.s)
		_beacon_at(pickup_pos, Color(1.0, 0.72, 0.15))
		hud.say("")
		return true
	return false


func skip_fare() -> void:
	_clear_passenger()
	state = WAITING
	_next_t = 0.5


func _clear_passenger() -> void:
	if passenger and is_instance_valid(passenger):
		passenger.queue_free()
	passenger = null


## [lane, s, road point, kerb point] on a kerb-side road lane at a straight-line distance in [rmin, rmax].
func _random_kerb(from: Vector3, rmin: float, rmax: float) -> Dictionary:
	var lanes: Array = graph.lanes
	for k in 40:
		var l = lanes[rng.randi() % lanes.size()]
		if l.junction >= 0 or l.kerb_index != 0 or l.length < 40.0 or l.speed > 16.0:
			continue
		var s := rng.randf_range(15.0, l.length - 15.0)
		var p: Vector3 = l.pos_at(s)
		var d := Vector2(p.x - from.x, p.z - from.z).length()
		if d < rmin or d > rmax:
			continue
		var i: int = l.seg_at(s, 0)
		var dir: Vector3 = l.dir_at_seg(i)
		var side: Vector3 = Vector3.UP.cross(dir).normalized() * graph.kerb_sign()
		var kerb: Vector3 = p + side * (l.width * 0.5 + 1.7)
		var y = _ground(kerb)
		if y == null or absf(float(y) - p.y) > 1.5:
			continue
		kerb.y = float(y)
		return {"lane": l.id, "s": s, "road": p, "kerb": kerb}
	return {}


func _ground(p: Vector3):
	var space := get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 4.0, p + Vector3.DOWN * 8.0, 1)
	var hit := space.intersect_ray(q)
	return hit.position.y if hit else p.y


func _car_lane() -> int:
	var c: RigidBody3D = main.car
	var r: Array = graph.nearest(c.global_position, 30.0, true, c.global_basis.z)
	if r[0] < 0:
		r = graph.nearest(c.global_position, 60.0, true)
	return r[0]


# ================================================================== per frame
func _physics_process(dt: float) -> void:
	if main.car == null or _graph() == null:
		return
	var car: RigidBody3D = main.car
	var v := car.linear_velocity
	var kmh := v.length() * 3.6
	_crash_cd = maxf(0.0, _crash_cd - dt)
	match state:
		WAITING:
			if auto_next:
				_next_t -= dt
				if _next_t <= 0.0:
					_next_t = 3.0
					new_fare()
		TO_PICKUP:
			if _flat(car.global_position - pickup_pos) < Data.PICKUP_RANGE_M and kmh < Data.PICKUP_STOP_KMH:
				state = BOARDING
				_walk_t = 0.0
				passenger.set_activity("", 0.0)
				hud.say(Data.pick(Data.PICKUP_LINES[pax.mood], rng).format({"dest": "..."}))
		BOARDING:
			_walk_t += dt
			if kmh > 8.0:                                   # drove off: they step back and wait
				state = TO_PICKUP
				passenger.set_speed(0.0)
				passenger.global_position = pickup_pos
				passenger.set_activity("idle_lantern", 1.0)
			elif _walk_to(_door(), dt) or _walk_t > 4.0:
				_start_ride()
		RIDING:
			ride_t += dt
			if kmh < 1.0:
				wait_t += dt
			var a := (v - _prev_v) / maxf(dt, 1e-4)
			a.y = 0.0
			var g := a.length() / 9.81
			if g > Data.HARSH_G and g < 3.0:                # >3 g is a collision: counted by _on_impact
				var before := discomfort
				discomfort += (g - Data.HARSH_G) * dt * 2.0
				if int(before * 2.0) != int(discomfort * 2.0) and _say_t <= 0.0:
					hud.say(Data.pick(Data.COMPLAINTS[pax.mood], rng))
					_say_t = 6.0
			_say_t = maxf(0.0, _say_t - dt)
			_track_route(car.global_position, dt)
			if _flat(car.global_position - dest_road) < Data.DROP_RANGE_M and kmh < Data.PICKUP_STOP_KMH:
				_start_alight()
		ALIGHTING:
			_walk_t += dt
			if _walk_to(dest_pos, dt) or _walk_t > 3.0:
				_clear_passenger()
				state = WAITING
				_next_t = 4.0
	_prev_v = v
	if state == TO_PICKUP:
		_track_route(car.global_position, dt)
	_ribbon_t -= dt
	if _ribbon_t <= 0.0:
		_ribbon_t = 0.15
		_draw_ribbon(car.global_position)


func _flat(d: Vector3) -> float:
	return Vector2(d.x, d.z).length()


## The kerb-side rear door of the car.
func _door() -> Vector3:
	var car: RigidBody3D = main.car
	var local := car.global_transform.affine_inverse() * pickup_pos
	var side := 1.0 if local.x >= 0.0 else -1.0
	return car.global_transform * Vector3(side * 1.25, 0.0, -0.4)


## Walk the passenger towards p; true when there.
func _walk_to(p: Vector3, dt: float) -> bool:
	if passenger == null:
		return true
	var d := p - passenger.global_position
	d.y = 0.0
	if d.length() < 0.5:
		passenger.set_speed(0.0)
		return true
	var step := minf(1.5 * dt, d.length())
	var n := passenger.global_position + d.normalized() * step
	n.y = lerpf(passenger.global_position.y, p.y, 0.2)
	passenger.global_position = n
	passenger.rotation.y = atan2(d.x, d.z)
	passenger.set_speed(1.5)
	return false


func _start_ride() -> void:
	_clear_passenger()
	var car_p: Vector3 = main.car.global_position
	var from := _car_lane()
	for attempt in 80:
		var c = _random_kerb(car_p, 600.0, 2600.0)
		if c.is_empty():
			continue
		if from >= 0 and _route_between(from, c.lane, 0.0, c.s).is_empty():
			continue
		dest_lane = c.lane
		dest_road = c.road
		dest_pos = c.kerb
		dest_name = district_name(dest_road) + " %d-chome" % (1 + (c.lane * 7 + int(c.s)) % 8)
		_set_route(from, c.lane, c.s)
		route_m = route_cum[route_cum.size() - 1] if route_cum.size() > 0 else _flat(dest_road - car_p)
		ride_t = 0.0
		wait_t = 0.0
		discomfort = 0.0
		crashes = 0
		peds = 0
		state = RIDING
		_beacon_at(dest_road, Color(0.2, 0.95, 1.0))
		hud.say(Data.pick(Data.PICKUP_LINES[pax.mood], rng).format({"dest": dest_name}))
		fare_started.emit({"dest": dest_name, "route_m": route_m, "mood": pax.mood})
		return
	skip_fare()          # nowhere reachable from here: let them go


func _start_alight() -> void:
	var res: Dictionary = Data.settle(route_m, ride_t, wait_t, discomfort, crashes, peds, String(pax.mood))
	res["dest"] = dest_name
	res["mood"] = pax.mood
	res["time"] = ride_t
	last_result = res
	stats.earned += int(res.total)
	stats.fares += 1
	stats.stars_sum += float(res.stars)
	stats.best_tip = maxi(int(stats.best_tip), int(res.tip))
	_save()
	var kind := "good" if res.stars >= 4.0 else ("ok" if res.stars >= 2.5 else "bad")
	hud.say(Data.pick(Data.DROP_LINES[kind], rng))
	hud.show_result(res)
	fare_finished.emit(res)
	# they get out on the kerb side and walk to the door of their building
	passenger = CitizenLib.spawn(String(pax.id), {"ragdoll": false, "umbrella": "", "shadows": true})
	add_child(passenger)
	var car: RigidBody3D = main.car
	var local := car.global_transform.affine_inverse() * dest_pos
	passenger.global_position = car.global_transform * Vector3((1.0 if local.x >= 0.0 else -1.0) * 1.3, 0.0, -0.4)
	passenger.global_position.y = dest_pos.y
	_walk_t = 0.0
	state = ALIGHTING
	route_pts = PackedVector3Array()
	_beacon.visible = false


func _on_impact(strength: float) -> void:
	if state == RIDING and strength > 120.0 and _crash_cd <= 0.0:
		crashes += 1
		_crash_cd = 1.5
		hud.say(Data.pick(Data.CRASH_LINES, rng))


func _on_ped_hit(_pos: Vector3, _speed: float) -> void:
	if state == RIDING:
		peds += 1
		hud.say("You hit someone! Stop the car!")


func district_name(p: Vector3) -> String:
	var q := Vector2(p.x, p.z)
	for isl in ISLANDS:
		var d: Vector2 = (q - isl[1]).rotated(deg_to_rad(isl[3]))
		var e: Vector2 = isl[2]
		if (d.x / e.x) * (d.x / e.x) + (d.y / e.y) * (d.y / e.y) <= 1.15:
			return isl[0]
	for s in SHINKAI:
		if q.distance_to(s[1]) <= s[2]:
			return s[0]
	return "Old Town"


# ================================================================== route (A* on lanes)
func _set_route(from: int, to_lane: int, to_s: float) -> void:
	route_pts = PackedVector3Array()
	route_cum = PackedFloat32Array()
	_route_i = 0
	_off_t = 0.0
	if from < 0:
		return
	var car_p: Vector3 = main.car.global_position
	var lanes: PackedInt32Array = _route_between(from, to_lane, 0.0, to_s)
	if lanes.is_empty():
		return
	var start_s: float = graph.nearest(car_p, 60.0, true, main.car.global_basis.z)[1] if graph.lanes[from].junction < 0 else 0.0
	for k in lanes.size():
		var l = graph.lanes[lanes[k]]
		var s0 := start_s if k == 0 else 0.0
		var s1: float = to_s if k == lanes.size() - 1 else l.length
		_append_lane(l, s0, s1)
	var c := 0.0
	for i in route_pts.size():
		if i > 0:
			c += route_pts[i].distance_to(route_pts[i - 1])
		route_cum.append(c)


func _append_lane(l, s0: float, s1: float) -> void:
	if s1 <= s0:
		return
	route_pts.append(l.pos_at(s0))
	for i in l.pts.size():
		if l.cum[i] > s0 and l.cum[i] < s1:
			route_pts.append(l.pts[i])
	route_pts.append(l.pos_at(s1))


## Lane ids from `a` (included) to `b` (included); empty when unreachable.
func _route_between(a: int, b: int, _sa: float, _sb: float) -> PackedInt32Array:
	if a == b:
		return PackedInt32Array([a])
	var lanes: Array = graph.lanes
	var goal: Vector3 = lanes[b].pts[0]
	var g := {a: 0.0}
	var prev := {}
	var heap: Array = [[0.0, a]]           # binary min-heap on f
	var expanded := 0
	while not heap.is_empty() and expanded < 30000:
		var cur: Array = _heap_pop(heap)
		var u: int = cur[1]
		if u == b:
			var out := PackedInt32Array()
			var x := b
			while x != a:
				out.append(x)
				x = prev[x]
			out.append(a)
			out.reverse()
			return out
		expanded += 1
		var gu: float = g[u]
		for v in lanes[u].next:
			var ng: float = gu + lanes[u].length
			if ng < g.get(v, INF):
				g[v] = ng
				prev[v] = u
				var h: float = lanes[v].pts[0].distance_to(goal)
				_heap_push(heap, [ng + h, v])
	return PackedInt32Array()


func _heap_push(h: Array, item: Array) -> void:
	h.append(item)
	var i := h.size() - 1
	while i > 0:
		var p := (i - 1) >> 1
		if h[p][0] <= h[i][0]:
			break
		var t = h[p]
		h[p] = h[i]
		h[i] = t
		i = p


func _heap_pop(h: Array) -> Array:
	var top: Array = h[0]
	var last: Array = h.pop_back()
	if not h.is_empty():
		h[0] = last
		var i := 0
		var n := h.size()
		while true:
			var l := i * 2 + 1
			var r := l + 1
			var m := i
			if l < n and h[l][0] < h[m][0]:
				m = l
			if r < n and h[r][0] < h[m][0]:
				m = r
			if m == i:
				break
			var t = h[m]
			h[m] = h[i]
			h[i] = t
			i = m
	return top


## Follow progress along the route; re-route when the driver leaves it for a few seconds.
func _track_route(p: Vector3, dt: float) -> void:
	if route_pts.size() < 2:
		return
	var best := INF
	var bi := _route_i
	for i in range(maxi(0, _route_i - 5), mini(route_pts.size(), _route_i + 60)):
		var d := _flat(route_pts[i] - p)
		if d < best:
			best = d
			bi = i
	_route_i = bi
	if best > 25.0:
		_off_t += dt
		if _off_t > 2.5:
			var target_lane: int = dest_lane if state == RIDING else graph.nearest(pickup_road, 10.0, true)[0]
			var target_s: float = graph.nearest(dest_road if state == RIDING else pickup_road, 10.0, true)[1]
			_set_route(_car_lane(), target_lane, target_s)
	else:
		_off_t = 0.0


## Remaining route distance (or straight line if there is no route).
func remaining_m() -> float:
	if route_cum.size() >= 2:
		return maxf(0.0, route_cum[route_cum.size() - 1] - route_cum[mini(_route_i, route_cum.size() - 1)])
	var t := dest_road if state == RIDING else pickup_pos
	return _flat(t - main.car.global_position) if main.car else 0.0


# ================================================================== visuals
func _make_ribbon() -> void:
	_ribbon_mesh = ImmediateMesh.new()
	_ribbon = MeshInstance3D.new()
	_ribbon.name = "GpsRibbon"
	_ribbon.mesh = _ribbon_mesh
	_ribbon.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, shadows_disabled;
uniform vec3 tint : source_color = vec3(0.2, 0.9, 1.0);
void fragment() {
	// UV.x = metres along the route, UV.y = across: chevrons flowing towards the target
	float across = abs(UV.y - 0.5) * 2.0;
	float chev = fract(UV.x * 0.25 - across * 0.35 - TIME * 1.2);
	float a = smoothstep(0.0, 0.15, chev) * (1.0 - smoothstep(0.45, 0.6, chev));
	float edge = 1.0 - smoothstep(0.7, 1.0, across);
	float fade = COLOR.a;
	ALBEDO = tint * (0.25 + a * 0.9) * edge * fade;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	_ribbon.material_override = mat
	add_child(_ribbon)


func _draw_ribbon(car_p: Vector3) -> void:
	_ribbon_mesh.clear_surfaces()
	if route_pts.size() < 2 or (state != TO_PICKUP and state != RIDING):
		return
	(_ribbon.material_override as ShaderMaterial).set_shader_parameter("tint", Color(1.0, 0.72, 0.15) if state == TO_PICKUP else Color(0.2, 0.9, 1.0))
	var i0 := maxi(0, _route_i - 1)
	var start_c: float = route_cum[i0]
	_ribbon_mesh.surface_begin(Mesh.PRIMITIVE_TRIANGLE_STRIP)
	var n := 0
	for i in range(i0, route_pts.size()):
		var along: float = route_cum[i] - start_c
		if along > 420.0:
			break
		var a := route_pts[maxi(i - 1, 0)]
		var b := route_pts[mini(i + 1, route_pts.size() - 1)]
		var dir := (b - a)
		dir.y = 0.0
		if dir.length() < 1e-3:
			continue
		var side := Vector3.UP.cross(dir.normalized()) * 0.75
		var p := route_pts[i] + Vector3.UP * 0.12
		var fade := clampf(along / 6.0, 0.0, 1.0) * (1.0 - clampf((along - 340.0) / 80.0, 0.0, 1.0))
		_ribbon_mesh.surface_set_color(Color(1, 1, 1, fade))
		_ribbon_mesh.surface_set_uv(Vector2(route_cum[i], 0.0))
		_ribbon_mesh.surface_add_vertex(p - side)
		_ribbon_mesh.surface_set_color(Color(1, 1, 1, fade))
		_ribbon_mesh.surface_set_uv(Vector2(route_cum[i], 1.0))
		_ribbon_mesh.surface_add_vertex(p + side)
		n += 2
	if n < 4:
		# ImmediateMesh needs a complete primitive: close with a degenerate pair
		for k in 4 - n:
			_ribbon_mesh.surface_add_vertex(car_p)
	_ribbon_mesh.surface_end()


func _make_beacon() -> void:
	var cyl := CylinderMesh.new()
	cyl.top_radius = 1.2
	cyl.bottom_radius = 1.2
	cyl.height = 90.0
	cyl.cap_top = false
	cyl.cap_bottom = false
	cyl.radial_segments = 24
	_beacon = MeshInstance3D.new()
	_beacon.name = "Beacon"
	_beacon.mesh = cyl
	_beacon.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, shadows_disabled;
uniform vec3 tint : source_color = vec3(1.0, 0.72, 0.15);
void fragment() {
	float h = UV.y;                        // 0 top .. 1 bottom
	float rim = pow(1.0 - abs(dot(NORMAL, VIEW)), 1.5);
	float pulse = 0.75 + 0.25 * sin(TIME * 3.0 - h * 12.0);
	ALBEDO = tint * (0.15 + rim * 0.9) * pow(h, 2.2) * pulse * 1.6;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	_beacon.material_override = mat
	_beacon.visible = false
	add_child(_beacon)


func _beacon_at(p: Vector3, col: Color) -> void:
	_beacon.global_position = p + Vector3.UP * 45.0
	(_beacon.material_override as ShaderMaterial).set_shader_parameter("tint", col)
	_beacon.visible = true


# ================================================================== save
func average_stars() -> float:
	return float(stats.stars_sum) / float(stats.fares) if int(stats.fares) > 0 else 0.0


func _save() -> void:
	if save_path == "":
		return
	var f := FileAccess.open(save_path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(stats, " "))


func _load() -> void:
	if save_path == "" or not FileAccess.file_exists(save_path):
		return
	var d = JSON.parse_string(FileAccess.get_file_as_string(save_path))
	if d is Dictionary:
		for k in stats:
			if d.has(k):
				stats[k] = d[k]
