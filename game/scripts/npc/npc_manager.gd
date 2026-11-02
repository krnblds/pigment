extends Node3D
## Pedestrians: MPFB citizens walking the sidewalks of the open world (docs/agents/npc/NOTES.md).
##
## Agents are plain data walking a sidewalk network (sidewalks.gd: sidewalks, corners, crossings,
## furniture to weave round, bus stops / benches / vending machines / shop fronts).  Around the camera:
##   * the nearest `max_near` (40) within `near_radius` get a Citizen node (skinned LOD0 < 16 m, LOD1
##     beyond, AnimationTree advanced by us: every frame < 16 m, every 2nd < 30 m, every 4th beyond,
##     staggered), the rest out to `spawn_radius` are the LOD2 crowd (one MultiMesh per citizen model,
##     vertex-shader walk sway); agents past `despawn_radius` respawn in a ring out of view.
##   * AI ticks at 5 Hz, staggered: keep left, overtake, weave round furniture, stop at bus stops,
##     benches, vending machines and shop fronts, shelter at the fronts when it rains (umbrellas up
##     otherwise), wait for the red at signalled crossings (the cars' red) and for a gap elsewhere.
##   * the player's car: walkers dodge / jump aside when it comes at them fast, flinch when it's too late;
##     a hit throws them (Jolt ragdoll, momentum from the impact, at most `max_ragdolls` at once - more
##     hits stagger instead), they get up after a few seconds and hurry off, shaken.
##   * traffic: walkers on a crossing (and anyone lying in the road) are obstacles the traffic AI brakes
##     for (traffic_manager.ped_provider); traffic cars that hit someone throw them too.
## API for other systems: agents_near(p, r), set_sleepwalker(agent, on), hit(agent, impulse, at), count(),
## summary(); the Citizen nodes themselves are scripts/npc/character/citizen.gd.

signal pedestrian_hit(pos: Vector3, speed: float)

const Sidewalks := preload("res://scripts/npc/sidewalks.gd")
const CitizenLib := preload("res://scripts/npc/character/citizen_library.gd")
const AnimLib := preload("res://scripts/npc/character/anim_library.gd")

enum { WALK, WAIT_CROSS, POI_GO, POI_STAY, DODGE, DOWN, STAGGER }

# --- tuning
var max_agents := 100
var max_near := 40
var near_radius := 52.0
var spawn_radius := 110.0
var despawn_radius := 128.0
var max_ragdolls := 6
var max_creates_per_frame := 1
var think_hz := 5.0

class Agent:
	var id := 0
	var model := ""
	var info := {}
	var edge := -1
	var s := 0.0
	var dir := 1
	var hint := 0
	var lat := 0.0
	var lat_target := 0.0
	var speed := 1.3
	var v := 0.0
	var pos := Vector3.ZERO
	var base := Vector3.ZERO
	var yaw := 0.0
	var state := 0
	var timer := 0.0
	var node: Node3D = null
	var phase := 0.0
	var displace := Vector3.ZERO
	var dodge_v := Vector3.ZERO
	var poi = null
	var umbrella := ""
	var sleep := false
	var shaken := 0.0
	var think_t := 0.0
	var gy := 0.0
	var gy_ok := false
	var ray_t := 0.0
	var dist := 0.0
	var anim_acc := 0.0
	var last_poi_s := -100.0
	var came_from := -1
	var idle := "idle"
	var activity := ""
	var hips := 0.9
	var down_t := 0.0
	var crossings := 0
	var off_path := 0.0
	var no_dodge := false       ## tests
	var force_next := -1        ## tests: take this edge at the next node

var main: Node3D
var net = null                  ## Sidewalks
var agents: Array = []
var ready_ok := false
var models: PackedStringArray
var rng := RandomNumberGenerator.new()
var raining := true
var _pool := {}                 ## model -> [Citizen]
var _crowd := {}                ## model -> MultiMeshInstance3D
var _crowd_n := {}
var _tick := 0
var _lod_t := 0.0
var _env_t := 0.0
var _created_this_frame := 0
var _thread_task := -1
var _world: Dictionary
var _jmap := {}                 ## world junction id -> lane graph junction index
var _rmap := {}                 ## world road id -> lane graph road index
var _ragdolls: Array = []
var _cell := {}
var stats := {"spawned": 0, "respawned": 0, "crossings": 0, "waits": 0, "dodges": 0, "flinches": 0, "hits": 0, "ragdolls": 0,
	"staggers": 0, "getups": 0, "poi_stops": 0, "nodes_created": 0, "max_ragdolls_seen": 0, "off_pavement": 0, "traffic_hits": 0,
	"signalled_crossings": 0, "red_violations": 0}
var prof := {"frames": 0, "us": 0, "us_ai": 0, "us_anim": 0, "us_crowd": 0, "us_move": 0, "us_phys": 0, "us_max": 0}


## main.gd: the pedestrians, or null when the citizens aren't built (--npc=<n> sets the number of walkers).
static func create(m: Node3D):
	var n = load("res://scripts/npc/npc_manager.gd").new()
	n.name = "Pedestrians"
	m.add_child(n)
	var opts := {}
	if m.args.has("npc"):
		opts["count"] = int(m.args.npc)
	if not n.setup(m, opts):
		n.queue_free()
		return null
	return n


func setup(m: Node3D, opts := {}) -> bool:
	main = m
	rng.seed = int(opts.get("seed", 1234))
	if opts.has("count"):
		max_agents = int(opts.count)
	if not CitizenLib.available() or not AnimLib.has_assets():
		push_warning("npc: no citizens built (python tools/npc/build_all.py) - keeping the traffic silhouettes")
		return false
	models = CitizenLib.ids(false)
	if main.get("traffic") and main.traffic:
		main.traffic.ped_provider = self
	var wpath := "res://assets/world/world.json"
	if String(main.get("map_name")) == "world" and FileAccess.file_exists(wpath):
		_thread_task = WorkerThreadPool.add_task(_load_world.bind(wpath), false, "npc sidewalks")
	else:
		_graph_fallback.call_deferred()
	return true


func _load_world(path: String) -> void:
	var w = JSON.parse_string(FileAccess.get_file_as_string(path))
	if w is Dictionary:
		var n = Sidewalks.new()
		n.build_from_world(w)
		net = n
		_world = {"junctions": w.get("junctions", []).map(func(j): return {"id": j.id, "signalised": j.get("signalised", false)})}


func _graph_fallback() -> void:
	for i in 6:
		await get_tree().physics_frame
	if main.traffic and main.traffic.graph:
		var n = Sidewalks.new()
		n.build_from_graph(main.traffic.graph)
		net = n
	_finish_setup()


func _process(dt: float) -> void:
	if not ready_ok:
		if _thread_task >= 0 and WorkerThreadPool.is_task_completed(_thread_task):
			WorkerThreadPool.wait_for_task_completion(_thread_task)
			_thread_task = -1
			_finish_setup()
		return
	var t0 := Time.get_ticks_usec()
	_frame(dt)
	var us := Time.get_ticks_usec() - t0
	prof.frames += 1
	prof.us += us
	prof.us_max = maxi(prof.us_max, us)


func _finish_setup() -> void:
	if net == null or net.edges.is_empty():
		push_warning("npc: no sidewalk network")
		return
	if main.traffic and main.traffic.graph:
		var G = main.traffic.graph
		for j in G.junctions.size():
			_jmap[G.junctions[j].name] = j
		for r in G.roads.size():
			_rmap[String(G.roads[r].name)] = r
	print("npc: sidewalk network %s; %d citizen models; %d agents, %d near" % [JSON.stringify(net.stats), models.size(), max_agents, max_near])
	var c := _center()
	for i in max_agents:
		var a := Agent.new()
		a.id = i
		a.model = models[rng.randi() % models.size()]
		a.info = CitizenLib.info(a.model)
		a.hips = float(a.info.get("hips", 0.9))
		a.speed = float(a.info.get("walk_speed", 1.3)) * rng.randf_range(0.92, 1.08)
		a.umbrella = String(a.info.get("umbrella")) if a.info.get("umbrella") != null else ""
		a.idle = String(a.info.get("idle", "idle")).to_lower()
		a.think_t = rng.randf() / think_hz
		a.phase = rng.randf()
		_place_random(a, c, 4.0, spawn_radius, false)
		if rng.randf() < 0.22:
			_try_poi_now(a)
		agents.append(a)
		stats.spawned += 1
	for mdl in models:
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.use_custom_data = true
		var cr: Array = CitizenLib.crowd(mdl)
		mm.mesh = cr[0]
		mm.instance_count = max_agents
		mm.visible_instance_count = 0
		var mmi := MultiMeshInstance3D.new()
		mmi.name = "Crowd_" + mdl
		mmi.multimesh = mm
		mmi.material_override = cr[1]
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		mmi.custom_aabb = AABB(Vector3(-5000, -500, -5000), Vector3(10000, 2000, 10000))
		add_child(mmi)
		_crowd[mdl] = mmi
	ready_ok = true
	_update_env()
	_update_lod(true)


# ================================================================== frame
func _frame(dt: float) -> void:
	_tick += 1
	_created_this_frame = 0
	_env_t -= dt
	if _env_t <= 0.0:
		_env_t = 1.0
		_update_env()
	_lod_t -= dt
	if _lod_t <= 0.0:
		_lod_t = 0.25
		_update_lod(false)
	var ta := Time.get_ticks_usec()
	_build_cells()
	var car: Node3D = main.car if main and main.car else null
	var cpos := car.global_position if car else Vector3(0, -1e6, 0)
	var cvel: Vector3 = car.linear_velocity if car else Vector3.ZERO
	for a in agents:
		a.think_t -= dt
		if a.think_t <= 0.0:
			a.think_t += 1.0 / think_hz
			_think(a)
		if a.node and a.state != DOWN and cvel.length() > 5.0 and a.pos.distance_squared_to(cpos) < 1600.0:
			_danger(a, cpos, cvel, car)
	prof.us_ai += Time.get_ticks_usec() - ta
	var tm := Time.get_ticks_usec()
	for a in agents:
		# walkers without a skeleton (the far crowd) move every 3rd frame, staggered
		a.anim_acc += dt if a.node == null else 0.0
		if a.node == null and a.state != DOWN:
			if (_tick + a.id) % 3 != 0:
				continue
			_move(a, a.anim_acc)
			a.anim_acc = 0.0
		else:
			_move(a, dt)
	prof.us_move += Time.get_ticks_usec() - tm
	var tn := Time.get_ticks_usec()
	for a in agents:
		if a.node:
			_drive_node(a, dt)
	prof.us_anim += Time.get_ticks_usec() - tn
	var tc := Time.get_ticks_usec()
	_draw_crowd(dt)
	prof.us_crowd += Time.get_ticks_usec() - tc


func _center() -> Vector3:
	var cam := get_viewport().get_camera_3d()
	if cam:
		return cam.global_position
	return main.car.global_position if main and main.car else Vector3.ZERO


func _update_env() -> void:
	var r = main.get("rain")
	raining = r != null and r.emitting
	var wet: float = main.car.wet if main.car and "wet" in main.car else (1.0 if raining else 0.0)
	CitizenLib.set_wet(maxf(wet, 0.15 if raining else 0.0))
	for a in agents:
		if a.node:
			a.node.set_umbrella(a.umbrella if raining and a.umbrella != "" and a.state != DOWN else "")


# ================================================================== placement
## Somewhere on the network between rmin and rmax from c (uniform in distance: busier near the camera).
func _place_random(a: Agent, c: Vector3, rmin: float, rmax: float, hidden: bool) -> bool:
	for k in 24:
		var r := rng.randf_range(rmin, rmax)
		var ang := rng.randf() * TAU
		var q := c + Vector3(cos(ang) * r, 0.0, sin(ang) * r)
		var hit: Array = net.nearest(q, 14.0, true)
		if hit[0] < 0:
			continue
		var e = net.edges[hit[0]]
		var s: float = clampf(hit[1] + rng.randf_range(-3.0, 3.0), 0.0, e.length)
		var p: Vector3 = e.pos_at(s)
		var d := Vector2(p.x - c.x, p.z - c.z).length()
		if d < rmin * 0.8 or d > rmax * 1.05:
			continue
		if hidden and _in_view(p, d):
			continue
		_set_on(a, e.id, s, 1 if rng.randf() < 0.5 else -1)
		return true
	return false


func _in_view(p: Vector3, d: float) -> bool:
	var cam := get_viewport().get_camera_3d()
	if cam == null or d > 160.0:
		return false
	return cam.is_position_in_frustum(p + Vector3.UP)


func _set_on(a: Agent, edge: int, s: float, dir: int) -> void:
	a.edge = edge
	a.s = s
	a.dir = dir
	a.hint = 0
	a.state = WALK
	a.displace = Vector3.ZERO
	a.lat = -0.5 * dir
	a.lat_target = a.lat
	a.gy_ok = false
	a.poi = null
	var e = net.edges[edge]
	a.base = e.pos_at(s)
	a.pos = a.base
	var d: Vector3 = e.dir_at(s) * dir
	a.yaw = atan2(d.x, d.z)


# ================================================================== AI
func _think(a: Agent) -> void:
	if a.state == DOWN or a.state == DODGE or a.state == STAGGER:
		return
	var e = net.edges[a.edge]
	match a.state:
		WAIT_CROSS:
			if _may_cross(e, a):
				a.state = WALK
				_count_cross(e)
				a.crossings += 1
			return
		POI_STAY:
			return
		POI_GO:
			return
	# walking: furniture and the people ahead decide the line
	var line := -1 if a.lat_target < 0 else 1
	var keep := -a.dir                             # keep left
	var want := 0.5 * keep
	if e.kind == Sidewalks.WALK:
		var ahead := a.s + a.dir * 2.0
		if e.blocked(ahead, 1 if want > 0 else -1) or e.blocked(a.s + a.dir * 0.8, 1 if want > 0 else -1):
			want = -want
		var other = _person_ahead(a)
		if other:
			if other.dir == a.dir and other.v < a.v * 0.9:
				want = -signf(other.lat) * 0.5 if not e.blocked(ahead, -1 if other.lat > 0 else 1) else want
				a.v = minf(a.v, other.v + 0.1)
			elif other.dir != a.dir:
				want = 0.5 * keep if absf(other.lat - 0.5 * keep) > 0.4 else -0.5 * keep
		a.lat_target = want
		# stop at a place on the way
		if a.shaken <= 0.0:
			for poi in e.pois:
				var ds: float = (poi.s - a.s) * a.dir
				if ds > 0.5 and ds < 3.0 and absf(poi.s - a.last_poi_s) > 1.0:
					a.last_poi_s = poi.s
					if _wants_poi(a, poi):
						a.poi = poi
						a.state = POI_GO
						stats.poi_stops += 1
					break
	else:
		a.lat_target = clampf(want, -0.4, 0.4)
	if a.shaken > 0.0:
		a.shaken -= 1.0 / think_hz


func _wants_poi(a: Agent, poi: Dictionary) -> bool:
	var occupied := false
	for o in _neighbours(poi.pos, 1.2):
		if o != a and (o.state == POI_STAY or o.state == POI_GO):
			occupied = true
	var p := 0.0
	match String(poi.kind):
		"bus":
			p = 0.35
		"bench":
			p = 0.18 if not occupied else 0.0
		"vending":
			p = 0.1
		"kiosk", "stall":
			p = 0.08
		"front":
			p = 0.04
			if raining and a.umbrella == "":
				p = 0.45                           # shelter under the awnings
			if occupied:
				p += 0.15                          # join someone for a chat
	if a.sleep:
		p *= 0.3
	return rng.randf() < p


func _try_poi_now(a: Agent) -> void:
	var e = net.edges[a.edge]
	if e.pois.is_empty():
		return
	var poi = e.pois[rng.randi() % e.pois.size()]
	a.s = poi.s
	a.poi = poi
	_arrive_poi(a)
	a.timer = rng.randf_range(4.0, 40.0)


func _arrive_poi(a: Agent) -> void:
	var poi: Dictionary = a.poi
	a.state = POI_STAY
	a.v = 0.0
	var kind := String(poi.kind)
	var talk := false
	for o in _neighbours(poi.pos, 1.6):
		if o != a and o.state == POI_STAY:
			talk = true
	a.activity = ""
	var extras := AnimLib.extra_clips()
	match kind:
		"bus":
			a.timer = rng.randf_range(10.0, 45.0)
			a.idle = ["idle", "look_around", "idle_phone", "idle_fold"][rng.randi() % 4]
		"bench":
			a.timer = rng.randf_range(15.0, 50.0)
			a.idle = "sit_idle"
		"vending", "kiosk", "stall":
			a.timer = rng.randf_range(5.0, 14.0)
			a.idle = "consume" if rng.randf() < 0.5 else "idle"
			if a.node:
				a.node.play_action("interact")
		_:
			a.timer = rng.randf_range(8.0, 35.0) * (2.0 if raining and a.umbrella == "" else 1.0)
			a.idle = "idle_talk" if talk else ["idle_fold", "idle_phone", "look_around", "idle"][rng.randi() % 4]
			# extra clips (git-ignored drop-ins): smoking / phone / leaning outside shops and bars
			var pick := []
			for x in extras:
				var lx := String(x).to_lower()
				if lx.contains("smok") or lx.contains("lean") or lx.contains("phone") or lx.contains("argu") or lx.contains("sweep"):
					pick.append(x)
			if not pick.is_empty() and rng.randf() < 0.6:
				a.activity = pick[rng.randi() % pick.size()]
	if a.node:
		a.node.set_idle(a.idle)
		a.node.set_activity(a.activity, 1.0 if a.activity != "" else 0.0)


func _leave_poi(a: Agent) -> void:
	a.state = WALK
	a.poi = null
	a.activity = ""
	a.idle = String(a.info.get("idle", "idle")).to_lower()
	if a.node:
		a.node.set_activity("", 0.0)
		a.node.set_idle(a.idle if a.idle != "sit_idle" else "idle")
		if a.idle == "sit_idle":
			a.node.play_action("sit_exit")


func _person_ahead(a: Agent):
	var best = null
	var bd := 1.8
	var fwd := Vector3(sin(a.yaw), 0, cos(a.yaw))
	for o in _neighbours(a.pos, 2.0):
		if o == a or o.state == DOWN:
			continue
		var rel: Vector3 = o.pos - a.pos
		var along := rel.dot(fwd)
		if along > 0.2 and along < bd and absf(rel.dot(Vector3(fwd.z, 0, -fwd.x))) < 0.7:
			bd = along
			best = o
	return best


func _build_cells() -> void:
	_cell.clear()
	for a in agents:
		if a.dist > 80.0:
			continue
		var k := Vector2i(floori(a.pos.x / 3.0), floori(a.pos.z / 3.0))
		if not _cell.has(k):
			_cell[k] = []
		_cell[k].append(a)


func _neighbours(p: Vector3, r: float) -> Array:
	var out := []
	var k0 := Vector2i(floori((p.x - r) / 3.0), floori((p.z - r) / 3.0))
	var k1 := Vector2i(floori((p.x + r) / 3.0), floori((p.z + r) / 3.0))
	for x in range(k0.x, k1.x + 1):
		for z in range(k0.y, k1.y + 1):
			for o in _cell.get(Vector2i(x, z), []):
				if o.pos.distance_squared_to(p) < r * r:
					out.append(o)
	return out


## The cars' signal for the arm a crossing goes over: 0 green, 1 amber, 2 red, -1 unsignalled.
func crossing_signal(e) -> int:
	var tr = main.traffic if main else null
	if tr == null or tr.signals == null or not _jmap.has(e.junction):
		return -1
	var j: int = _jmap[e.junction]
	if not tr.signals.is_signalled(j):
		return -1
	var ri: int = _rmap.get(e.road, -1)
	var J = tr.graph.junctions[j]
	for i in J.approaches.size():
		if J.approaches[i].road == ri:
			return tr.signals.state(j, i)
	return -1


## May this walker step onto the crossing?  Signalled junctions: when the cars of that arm have red.
## Elsewhere (and always): no car close and coming.
func _may_cross(e, a: Agent) -> bool:
	var mid: Vector3 = e.pts[e.pts.size() / 2]
	var tr = main.traffic if main else null
	var sig := crossing_signal(e)
	if sig >= 0 and sig != 2:
		return false
	# gap: the player's car and traffic
	if main.car:
		var cv: Vector3 = main.car.linear_velocity
		var rel: Vector3 = mid - main.car.global_position
		if rel.length() < 8.0 or (rel.length() < 45.0 and cv.length() > 3.0 and rel.normalized().dot(cv.normalized()) > 0.5):
			return false
	if tr:
		for c in tr.active:
			var rel: Vector3 = mid - c.global_position
			var d := rel.length()
			if d < 6.0:
				return false
			if d < 30.0 and c.v > 1.5 and rel.normalized().dot(c.global_basis.z) > 0.6:
				return false
	return true


# ================================================================== motion
func _move(a: Agent, dt: float) -> void:
	match a.state:
		DOWN:
			if a.node:
				var sk: Skeleton3D = a.node.skeleton()
				var rag = a.node.rag
				if rag and rag.bones.has("Hips"):
					a.pos = rag.bones.Hips.global_position
			a.down_t += dt
			return
		POI_STAY:
			a.timer -= dt
			a.v = 0.0
			if a.timer <= 0.0:
				_leave_poi(a)
			_pose(a, dt, Vector3(a.poi.face) if a.poi else Vector3.ZERO)
			return
		WAIT_CROSS:
			a.v = move_toward(a.v, 0.0, 3.0 * dt)
			a.timer += dt
			_pose(a, dt, Vector3.ZERO)
			return
		DODGE, STAGGER:
			a.timer -= dt
			a.displace += a.dodge_v * dt
			a.dodge_v = a.dodge_v.move_toward(Vector3.ZERO, 4.5 * dt)
			a.v = move_toward(a.v, 0.0, 4.0 * dt)
			if a.timer <= 0.0:
				a.state = WALK
				a.shaken = maxf(a.shaken, 4.0)
			_pose(a, dt, Vector3.ZERO)
			return
	var e = net.edges[a.edge]
	var want := a.speed * (0.6 if a.sleep else 1.0) * (1.7 if a.shaken > 0.0 else 1.0)
	if a.state == POI_GO:
		want = minf(want, 1.0)
	if e.kind == Sidewalks.CROSSING:
		want *= 1.15
	a.v = move_toward(a.v, want, 1.6 * dt)
	a.s += a.dir * a.v * dt
	if a.state == POI_GO and a.poi:
		a.lat_target = clampf(float(a.poi.lat), -1.25, 1.25)
		if (a.poi.s - a.s) * a.dir <= 0.0:
			_arrive_poi(a)
	a.lat = move_toward(a.lat, a.lat_target, 0.7 * dt)
	if a.s > e.length or a.s < 0.0:
		_next_edge(a)
		e = net.edges[a.edge]
	# back to the path after a dodge / a fall
	if a.displace != Vector3.ZERO:
		a.displace = a.displace.move_toward(Vector3.ZERO, (0.9 + a.displace.length() * 0.25) * dt)
	_pose(a, dt, Vector3.ZERO)
	a.phase = fmod(a.phase + a.v * dt / (1.35 * a.hips / 0.917), 1.0)


func _pose(a: Agent, dt: float, face: Vector3) -> void:
	var e = net.edges[a.edge]
	a.hint = e.seg_at(clampf(a.s, 0.0, e.length), a.hint)
	var d: Vector3 = e.dir_at(clampf(a.s, 0.0, e.length), a.hint)
	var right := Vector3(-d.z, 0, d.x)
	a.base = e.pos_at(clampf(a.s, 0.0, e.length), a.hint) + right * a.lat
	var p := a.base + a.displace
	if a.gy_ok:
		p.y = a.gy
	a.pos = p
	var f := face if face != Vector3.ZERO else d * a.dir
	if a.state == DODGE or a.state == STAGGER:
		f = Vector3(sin(a.yaw), 0, cos(a.yaw))
	var y := atan2(f.x, f.z)
	a.yaw = lerp_angle(a.yaw, y, clampf(6.0 * dt, 0.0, 1.0))


func _next_edge(a: Agent) -> void:
	var e = net.edges[a.edge]
	var node: int = e.b if a.s > e.length else e.a
	var opts: PackedInt32Array = net.adj[node]
	var cand := []
	var w := []
	for id in opts:
		if id == a.edge and opts.size() > 1:
			continue
		var x = net.edges[id]
		var k := 1.0
		if x.kind == Sidewalks.CROSSING:
			k = 0.55 if e.kind != Sidewalks.CROSSING else 0.12
		cand.append(id)
		w.append(k)
	var pick: int = a.edge
	if a.force_next >= 0 and a.force_next in cand:
		pick = a.force_next
		a.force_next = -1
	elif not cand.is_empty():
		var tot: float = w.reduce(func(acc, v): return acc + v, 0.0)
		var r := rng.randf() * tot
		for i in cand.size():
			r -= w[i]
			if r <= 0.0:
				pick = cand[i]
				break
	var ne = net.edges[pick]
	var over := absf(a.s - (e.length if a.s > e.length else 0.0))
	a.came_from = a.edge
	a.edge = pick
	a.hint = 0
	if ne.a == node:
		a.dir = 1
		a.s = minf(over, ne.length)
	else:
		a.dir = -1
		a.s = maxf(ne.length - over, 0.0)
	if ne.kind == Sidewalks.CROSSING:
		a.lat_target = clampf(a.lat_target, -0.4, 0.4)
		if not _may_cross(ne, a):
			a.state = WAIT_CROSS
			a.timer = 0.0
			stats.waits += 1
		else:
			_count_cross(ne)
			a.crossings += 1


func _count_cross(e) -> void:
	stats.crossings += 1
	var sig := crossing_signal(e)
	if sig >= 0:
		stats.signalled_crossings += 1
		if sig != 2:
			stats.red_violations += 1


# ================================================================== the player's car
func _danger(a: Agent, cpos: Vector3, cvel: Vector3, car: Node3D) -> void:
	if a.state == DODGE or a.state == STAGGER or a.no_dodge:
		return
	var rel := a.pos - cpos
	rel.y = 0.0
	var v2 := Vector3(cvel.x, 0, cvel.z)
	var sp := v2.length()
	var t := rel.dot(v2) / maxf(sp * sp, 1e-3)
	if t < 0.0 or t > 1.4:
		return
	var miss := rel - v2 * t
	var half_w := 1.0
	if miss.length() > half_w + 1.1:
		return
	var away := miss.normalized() if miss.length() > 0.15 else Vector3(-v2.z, 0, v2.x).normalized() * (1.0 if rng.randf() < 0.5 else -1.0)
	if a.state == POI_STAY or a.state == POI_GO:
		_leave_poi(a)
	if t > 0.35 and a.node:
		a.state = DODGE
		a.timer = 0.9
		var push := (half_w + 1.6 - miss.length()) / 0.55
		a.dodge_v = away * clampf(push, 2.5, 6.5)
		a.yaw = atan2(-v2.x, -v2.z)               # face the car, jump sideways
		a.node.play_action("dodge_jump" if rng.randf() < 0.6 else "roll", 0.05)
		stats.dodges += 1
	elif a.node:
		a.state = STAGGER
		a.timer = 0.6
		a.dodge_v = away * 2.0
		a.node.play_action("flinch", 0.05)
		stats.flinches += 1


func _physics_process(_dt: float) -> void:
	if not ready_ok:
		return
	var t0 := Time.get_ticks_usec()
	var car: RigidBody3D = main.car if main else null
	if car:
		var cv := car.linear_velocity
		var sp := cv.length()
		if sp > 2.0:
			var inv := car.global_transform.affine_inverse()
			for a in agents:
				if a.state == DOWN or a.dist > 30.0:
					continue
				var l: Vector3 = inv * (a.pos + Vector3.UP * 0.9)
				if absf(l.x) < 1.15 and absf(l.z) < 2.55 and l.y > -1.6 and l.y < 1.4:
					hit(a, cv * 80.0 + Vector3.UP * (80.0 * (1.2 + 0.12 * sp)), a.pos + Vector3.UP * 0.9, car)
	# traffic cars (the kinematic ones barely ever reach a walker: they brake for them)
	if _tick % 4 == 0 and main.traffic:
		for c in main.traffic.active:
			if c.v < 3.0:
				continue
			var cp: Vector3 = c.global_position
			if cp.distance_squared_to(_center()) > 3600.0:
				continue
			var inv: Transform3D = c.global_transform.affine_inverse()
			for a in _neighbours(cp, 3.5):
				if a.state == DOWN:
					continue
				var l: Vector3 = inv * (a.pos + Vector3.UP * 0.9)
				if absf(l.x) < c.half_w + 0.2 and absf(l.z) < c.half_len + 0.2:
					var fwd: Vector3 = c.global_basis.z * c.v
					hit(a, fwd * 80.0 + Vector3.UP * 150.0, a.pos + Vector3.UP * 0.9, c)
					stats.traffic_hits += 1
	prof.us_phys += Time.get_ticks_usec() - t0


## Throw a walker: ragdoll (up to max_ragdolls at once) or a stagger.  impulse in kg m/s.
func hit(a: Agent, impulse: Vector3, at: Vector3, by: Node3D = null) -> void:
	if a.state == DOWN:
		return
	stats.hits += 1
	if a.node == null:
		_attach_node(a, true)
	if a.state == POI_STAY or a.state == POI_GO:
		_leave_poi(a)
	_ragdolls = _ragdolls.filter(func(x): return x.state == DOWN)
	var sp := impulse.length() / 80.0
	pedestrian_hit.emit(at, sp)
	if by == main.car:
		if main.get("damage") and main.damage and main.damage.hero_damage:
			main.damage.hero_damage.apply_impact(at, -impulse.normalized(), minf(2200.0, impulse.length() * 0.35))
		if main.get("cam") and main.cam and main.cam.has_method("shake"):
			main.cam.shake(clampf(sp / 30.0, 0.08, 0.3))
		by.apply_central_impulse(-impulse * 0.35)
	if _ragdolls.size() >= max_ragdolls or a.node == null:
		a.state = STAGGER
		a.timer = 1.2
		a.dodge_v = Vector3(impulse.x, 0, impulse.z).normalized() * 3.0
		if a.node:
			a.node.play_action("knockback", 0.05)
		stats.staggers += 1
		return
	a.state = DOWN
	a.down_t = 0.0
	a.v = 0.0
	_ragdolls.append(a)
	stats.ragdolls += 1
	stats.max_ragdolls_seen = maxi(stats.max_ragdolls_seen, _ragdolls.size())
	a.node.ragdoll(impulse, at, by as PhysicsBody3D)


func _on_stood_up(a: Agent) -> void:
	_ragdolls.erase(a)
	stats.getups += 1
	var p: Vector3 = a.node.global_position
	var near: Array = net.nearest(p, 25.0, true)
	if near[0] >= 0:
		var keep_dir := a.dir
		_set_on(a, near[0], near[1], keep_dir)
		a.displace = p - a.base
		a.displace.y = 0.0
	a.yaw = atan2(a.node.global_basis.z.x, a.node.global_basis.z.z)
	a.state = WALK
	a.v = 0.0
	a.shaken = 10.0
	a.gy_ok = false
	if a.node and raining and a.umbrella != "":
		a.node.set_umbrella(a.umbrella)


## Is the walker on the pavement (or a crossing / a place), give or take the dodge?  (tests)
func on_pavement(a: Agent) -> bool:
	if a.state == DOWN:
		return true
	var e = net.edges[a.edge]
	return e.kind != Sidewalks.CROSSING and absf(a.lat) <= 1.3 or e.kind == Sidewalks.CROSSING


# ================================================================== LOD + nodes
func _update_lod(initial: bool) -> void:
	var c := _center()
	for a in agents:
		a.dist = Vector2(a.pos.x - c.x, a.pos.z - c.z).length()
		if a.dist > despawn_radius and a.state != DOWN:
			_respawn(a, c)
	var order := agents.duplicate()
	order.sort_custom(func(x, y): return x.dist < y.dist)
	var n := 0
	for a in order:
		var want: bool = (n < max_near and a.dist < near_radius) or a.state == DOWN
		if want:
			n += 1
			if a.node == null:
				_attach_node(a, initial)
		elif a.node and a.dist > near_radius + 4.0:
			_detach_node(a)


func _respawn(a: Agent, c: Vector3) -> void:
	if OS.has_feature("debug") and stats.respawned < 6 and main.args.has("npc-debug"):
		print("npc respawn #%d dist %.1f pos %s center %s state %d edge %d s %.1f" % [stats.respawned, a.dist, a.pos, c, a.state, a.edge, a.s])
	_detach_node(a)
	if not _place_random(a, c, 40.0, spawn_radius, true):
		_place_random(a, c, 30.0, spawn_radius, false)
	a.shaken = 0.0
	a.sleep = a.sleep
	if rng.randf() < 0.2:
		_try_poi_now(a)
	stats.respawned += 1


func _attach_node(a: Agent, force := false) -> void:
	var pool: Array = _pool.get(a.model, [])
	var c: Node3D = null
	if not pool.is_empty():
		c = pool.pop_back()
	elif force or _created_this_frame < max_creates_per_frame:
		_created_this_frame += 1
		c = CitizenLib.spawn(a.model, {"anim_auto": false, "umbrella": ""})
		if c == null:
			return
		c.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
		add_child(c)
		stats.nodes_created += 1
	else:
		return
	c.visible = true
	c.process_mode = Node.PROCESS_MODE_INHERIT
	a.node = c
	if c.has_meta("agent_cb"):
		c.stood_up.disconnect(c.get_meta("agent_cb"))
	var cb := _on_stood_up.bind(a)
	c.stood_up.connect(cb)
	c.set_meta("agent_cb", cb)
	c.global_position = a.pos
	c.rotation = Vector3(0, a.yaw, 0)
	c.set_sleepwalker(a.sleep)
	c.set_umbrella(a.umbrella if raining and a.umbrella != "" else "")
	c.set_idle(a.idle if a.state == POI_STAY else String(a.info.get("idle", "idle")).to_lower())
	c.set_activity(a.activity, 1.0 if a.activity != "" else 0.0)
	c.set_speed(a.v)
	c.advance(0.5)                     # settle the blend tree
	a.anim_acc = 0.0
	a.gy_ok = false


func _detach_node(a: Agent) -> void:
	if a.node == null:
		return
	var c: Node3D = a.node
	a.node = null
	if c.is_down():
		return                          # keep it until it stands up (never pooled mid-ragdoll)
	c.visible = false
	c.process_mode = Node.PROCESS_MODE_DISABLED
	if not _pool.has(a.model):
		_pool[a.model] = []
	_pool[a.model].append(c)


func _drive_node(a: Agent, dt: float) -> void:
	var c: Node3D = a.node
	a.anim_acc += dt
	var every := 1 if a.dist < 16.0 or a.state == DOWN or a.state == DODGE else (2 if a.dist < 30.0 else 4)
	var step := (_tick + a.id) % every == 0
	if a.state != DOWN:
		# feet on the real ground near the camera (a ray every ~0.4 s, staggered)
		a.ray_t -= dt
		if a.ray_t <= 0.0 and a.dist < 45.0:
			a.ray_t = 0.4 + rng.randf() * 0.1
			var space := get_world_3d().direct_space_state
			var q := PhysicsRayQueryParameters3D.create(a.pos + Vector3.UP * 1.2, a.pos + Vector3.DOWN * 1.5, 1)
			if main.car:
				q.exclude = [main.car.get_rid()]
			var h := space.intersect_ray(q)
			if not h.is_empty():
				var gy: float = h.position.y
				a.gy = gy if not a.gy_ok else lerpf(a.gy, gy, 0.5)
				a.gy_ok = true
		if step or every == 1 or a.dist < 30.0:
			c.global_position = a.pos
			c.rotation = Vector3(0, a.yaw, 0)
		if step and absf(c.speed - a.v) > 0.03:
			c.set_speed(a.v)
	if step:
		c.advance(a.anim_acc)
		a.anim_acc = 0.0


var _bufs := {}


func _draw_crowd(_dt: float) -> void:
	if _tick % 2 != 0:
		return
	var fill := {}
	for mdl in _crowd:
		fill[mdl] = 0
		if not _bufs.has(mdl):
			var b := PackedFloat32Array()
			b.resize(max_agents * 16)
			_bufs[mdl] = b
	for a in agents:
		if a.node or a.dist > spawn_radius + 10.0:
			continue
		var i: int = fill[a.model] * 16
		fill[a.model] += 1
		var b: PackedFloat32Array = _bufs[a.model]
		var cy := cos(a.yaw)
		var sy := sin(a.yaw)
		b[i] = cy
		b[i + 1] = 0.0
		b[i + 2] = sy
		b[i + 3] = a.pos.x
		b[i + 4] = 0.0
		b[i + 5] = 1.0
		b[i + 6] = 0.0
		b[i + 7] = a.pos.y
		b[i + 8] = -sy
		b[i + 9] = 0.0
		b[i + 10] = cy
		b[i + 11] = a.pos.z
		b[i + 12] = a.phase
		b[i + 13] = clampf(a.v / 1.2, 0.0, 1.0)
		b[i + 14] = 1.0 if a.sleep else 0.0
		b[i + 15] = 0.0
		_bufs[a.model] = b
	for mdl in _crowd:
		var mm: MultiMesh = _crowd[mdl].multimesh
		var n: int = fill[mdl]
		if n == 0:
			if mm.visible_instance_count != 0:
				mm.visible_instance_count = 0
			continue
		mm.buffer = _bufs[mdl]
		mm.visible_instance_count = n


# ================================================================== API
func count() -> int:
	return agents.size()


func add_obstacles(list: Array) -> void:
	## traffic_manager._collect_obstacles: walkers on a crossing or lying in the road.
	if not ready_ok:
		return
	for a in agents:
		if a.dist > 120.0:
			continue
		if a.state == DOWN or (a.edge >= 0 and net.edges[a.edge].kind == Sidewalks.CROSSING and a.state != WAIT_CROSS) or a.displace.length() > 1.5:
			var vel: Vector3 = Vector3(sin(a.yaw), 0, cos(a.yaw)) * a.v
			list.append([a.pos, vel, 0.35, false, null, 0.45])


func agents_near(p: Vector3, r: float) -> Array:
	return agents.filter(func(a): return a.pos.distance_to(p) < r)


func set_sleepwalker(a: Agent, on: bool) -> void:
	a.sleep = on
	if a.node:
		a.node.set_sleepwalker(on)


func summary() -> Dictionary:
	var d := stats.duplicate()
	var by := {}
	for a in agents:
		by[a.state] = by.get(a.state, 0) + 1
	d["agents"] = agents.size()
	d["near"] = agents.filter(func(a): return a.node != null).size()
	d["by_state"] = by
	d["ragdolls_now"] = _ragdolls.size()
	var n: float = maxf(1.0, prof.frames)
	d["us_per_frame"] = {"total": int(prof.us / n), "ai": int(prof.us_ai / n), "move": int(prof.us_move / n), "anim": int(prof.us_anim / n),
		"crowd": int(prof.us_crowd / n), "phys": int(prof.us_phys / n), "max": prof.us_max}
	return d


func reset_prof() -> void:
	for k in prof:
		prof[k] = 0
