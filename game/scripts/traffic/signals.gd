extends Node3D
## Traffic signal controllers for the signalled junctions of a lane graph, and their light heads.
##
## Phases: approaches that face each other (within ~45 deg of opposite) share a phase, every other
## approach gets its own; or the explicit "phases" of the world format ({roads: [...], green, amber}).
## Cycle per phase: green -> amber -> all-red -> next phase.  Junctions start at random offsets.
## Actuated: after min_green a green gaps out early when no car is approaching on it while cars
## wait on red (demand comes from the traffic manager through demand_fn(junction, approach)).
##
## Heads: the props workstream's traffic lights when present (res://assets/props/traffic_light_pole.glb,
## traffic_light_mast.glb: a mast over approaches with 2+ lanes), otherwise a simple pole + three-lamp
## head.  The prop's front (lenses) is its +Z; the mast arm is +X (over the road when driving on the left).
## Lamp nodes are found by name, case-insensitive: a name ending in Red / Amber|Yellow|Orange / Green
## ("Lamp_A_Red", "Lamp_C_Green"); names that only contain the colour are used if none end in it.
## Each lit lamp gets its emission switched; one small OmniLight per head tints the wet road.
## Props the world already placed can be driven instead: attach_instance(signal id, node).

const GREEN := 0
const AMBER := 1
const RED := 2
const POLE_PATHS := ["res://assets/props/traffic_light_pole.glb", "res://assets/props/traffic_light/traffic_light_pole.glb",
	"res://assets/props/traffic_light.glb"]
const MAST_PATHS := ["res://assets/props/traffic_light_mast.glb", "res://assets/props/traffic_light/traffic_light_mast.glb"]

var graph
var ctl: Array = []             ## per junction: Dictionary (or null when unsignalled)
var green_time := 14.0
var min_green := 6.0
var demand_fn := Callable()          ## (junction id, approach) -> cars waiting / approaching
var amber_time := 3.0
var all_red_time := 2.0
var stats := {"phase_changes": 0, "greens": 0}
var prop_scene: PackedScene          ## pole
var mast_scene: PackedScene
var prop_path := ""
var by_id := {}                      ## signal id -> head
var _mats := {}


func setup(g, rng: RandomNumberGenerator) -> void:
	graph = g
	for p in POLE_PATHS:
		if ResourceLoader.exists(p):
			prop_scene = load(p)
			prop_path = p
			break
	for p in MAST_PATHS:
		if ResourceLoader.exists(p):
			mast_scene = load(p)
			break
	if mast_scene == null:
		mast_scene = prop_scene
	_make_mats()
	for J in graph.junctions:
		if J.control != "signal" or J.approaches.size() < 2:
			ctl.append(null)
			continue
		var phases := _phases(J)
		var c := {"phases": phases, "phase": rng.randi() % phases.size(), "state": GREEN,
			"t": rng.randf() * green_time, "app": PackedInt32Array(), "heads": [], "hold": {}, "seen": {}}
		c.app.resize(J.approaches.size())
		ctl.append(c)
		_apply(J.id)
		_build_heads(J, c)


func _phases(J) -> Array:
	var out := []
	if not J.phases.is_empty():
		var used := {}
		for ph in J.phases:
			var aps := []
			for ai in J.approaches.size():
				if ph.get("roads", []).has(graph.roads[J.approaches[ai].road].name) or ph.get("approaches", []).has(ai):
					aps.append(ai)
					used[ai] = true
			if not aps.is_empty():
				out.append({"aps": aps, "green": float(ph.get("green", green_time)), "amber": float(ph.get("amber", amber_time))})
		for ai in J.approaches.size():
			if not used.has(ai):
				out.append({"aps": [ai], "green": green_time, "amber": amber_time})
		return out
	var taken := {}
	for ai in J.approaches.size():
		if taken.has(ai):
			continue
		var aps := [ai]
		taken[ai] = true
		for bi in range(ai + 1, J.approaches.size()):
			if not taken.has(bi) and J.approaches[ai].dir.dot(J.approaches[bi].dir) < -0.7:
				aps.append(bi)
				taken[bi] = true
				break
		out.append({"aps": aps, "green": green_time if aps.size() > 1 else green_time * 0.8, "amber": amber_time})
	return out


func _gap_out(j: int, c: Dictionary, ph: Dictionary) -> bool:
	if not demand_fn.is_valid():
		return false
	for ai in ph.aps:
		if demand_fn.call(j, ai) > 0:
			return false
	for ai in c.app.size():
		if not ph.aps.has(ai) and demand_fn.call(j, ai) > 0:
			return true
	return false


func state(j: int, approach: int) -> int:
	if j < 0 or j >= ctl.size() or ctl[j] == null or approach < 0:
		return GREEN
	return ctl[j].app[approach]


func is_signalled(j: int) -> bool:
	return j >= 0 and j < ctl.size() and ctl[j] != null


## Keep an approach red for t seconds (screenshots / tests).
func hold_red(j: int, approach: int, t: float) -> void:
	if is_signalled(j):
		ctl[j].hold[approach] = t
		_apply(j)


func step(dt: float) -> void:
	for j in ctl.size():
		var c = ctl[j]
		if c == null:
			continue
		for a in c.hold.keys():
			c.hold[a] -= dt
			if c.hold[a] <= 0.0:
				c.hold.erase(a)
		c.t += dt
		var ph: Dictionary = c.phases[c.phase]
		var changed := false
		match c.state:
			GREEN:
				if c.t >= ph.green or (c.t >= min_green and _gap_out(j, c, ph)):
					c.state = AMBER
					c.t = 0.0
					changed = true
			AMBER:
				if c.t >= ph.amber:
					c.state = RED
					c.t = 0.0
					changed = true
			RED:
				if c.t >= all_red_time:
					c.phase = (c.phase + 1) % c.phases.size()
					c.state = GREEN
					c.t = 0.0
					changed = true
					stats.greens += 1
		if changed or not c.hold.is_empty():
			if changed:
				stats.phase_changes += 1
			_apply(j)


func _apply(j: int) -> void:
	var c: Dictionary = ctl[j]
	var ph: Dictionary = c.phases[c.phase]
	for ai in c.app.size():
		var st := RED
		if ph.aps.has(ai):
			st = GREEN if c.state == GREEN else (AMBER if c.state == AMBER else RED)
		if c.hold.has(ai):
			st = RED
		if c.app[ai] != st or not c.seen.has(ai):
			c.app[ai] = st
			var seen: Dictionary = c.seen.get(ai, {})
			seen[st] = true
			c.seen[ai] = seen
			for h in c.heads:
				if h.approach == ai:
					_show(h, st)


## Every approach of every signalled junction has shown green, amber and red.
func all_cycled() -> bool:
	for c in ctl:
		if c == null:
			continue
		for ai in c.app.size():
			var seen: Dictionary = c.seen.get(ai, {})
			if not (seen.has(GREEN) and seen.has(RED)):
				return false
	return true


# ------------------------------------------------------------------ heads
func _make_mats() -> void:
	var cols := {"red": Color(1.0, 0.06, 0.03), "amber": Color(1.0, 0.55, 0.0), "green": Color(0.1, 1.0, 0.45)}
	for k in cols:
		for on in [true, false]:
			var m := StandardMaterial3D.new()
			m.albedo_color = cols[k] * (0.05 if on else 0.08)
			m.emission_enabled = true
			m.emission = cols[k]
			m.emission_energy_multiplier = 12.0 if on else 0.08
			m.roughness = 0.2
			_mats["%s_%s" % [k, "on" if on else "off"]] = m
	var body := StandardMaterial3D.new()
	body.albedo_color = Color(0.05, 0.05, 0.055)
	body.roughness = 0.55
	body.metallic = 0.6
	_mats["body"] = body


func _build_heads(J, c: Dictionary) -> void:
	var places := []      # [pos, facing, approach, mast, id]
	if not J.signals.is_empty():
		for sd in J.signals:
			var ai := _approach_of(J, sd)
			places.append([sd.pos, sd.facing, ai, sd.mast > 3.0, sd.id])
	else:
		for ai in J.approaches.size():
			var ap: Dictionary = J.approaches[ai]
			var kerb_lane = graph.lanes[ap.lanes[0]]
			var p: Vector3 = kerb_lane.pts[kerb_lane.pts.size() - 1]
			var d: Vector3 = ap.dir
			var left := Vector3.UP.cross(d).normalized()
			var side: float = graph.kerb_sign()
			p += left * side * (kerb_lane.width * 0.5 + 1.7) - d * 0.5
			places.append([p, -d, ai, ap.lanes.size() > 1, ""])
	for pl in places:
		var h := _make_head(pl[0], pl[1], pl[3])
		h["approach"] = pl[2]
		c.heads.append(h)
		if pl[4] != "":
			by_id[pl[4]] = h
		_show(h, c.app[pl[2]] if pl[2] >= 0 else RED)


## Drive the lamps of a traffic light the world placed itself (instead of the one spawned here).
func attach_instance(signal_id: String, node: Node3D) -> bool:
	if not by_id.has(signal_id):
		return false
	var h: Dictionary = by_id[signal_id]
	var lamps := _find_lamps(node)
	if lamps.red.is_empty():
		return false
	h.root.queue_free()
	h.root = node
	h.lamps = lamps
	h.mats = {}
	var ol: OmniLight3D = h.light
	if ol:
		ol.reparent(node, false)
	return true


func _approach_of(J, sd: Dictionary) -> int:
	if sd.get("approach", -1) >= 0:
		return int(sd.approach)
	if sd.get("road", "") != "":
		for ai in J.approaches.size():
			if graph.roads[J.approaches[ai].road].name == String(sd.road):
				return ai
	# nearest approach end
	var best := 0
	var bd := INF
	for ai in J.approaches.size():
		var l = graph.lanes[J.approaches[ai].lanes[0]]
		var d: float = l.pts[l.pts.size() - 1].distance_to(sd.pos)
		if d < bd:
			bd = d
			best = ai
	return best


## facing: the direction the lamps shine (towards the approaching cars)
func _make_head(p: Vector3, facing: Vector3, mast := false) -> Dictionary:
	var root := Node3D.new()
	root.name = "SignalHead"
	add_child(root)
	var z := facing.normalized()
	var x := Vector3.UP.cross(z).normalized()
	root.global_transform = Transform3D(Basis(x, Vector3.UP, z), p)
	var h := {"root": root, "lamps": {"red": [], "amber": [], "green": []}, "light": null, "mats": {}}
	var scene: PackedScene = mast_scene if mast else prop_scene
	if scene:
		var inst: Node3D = scene.instantiate()
		root.add_child(inst)
		h.lamps = _find_lamps(inst)
		if h.lamps.red.is_empty():
			inst.queue_free()
	if h.lamps.red.is_empty():
		_simple_head(root, h)
	var ol := OmniLight3D.new()
	ol.position = Vector3(0, 3.0, 0.5)
	ol.omni_range = 7.0
	ol.light_energy = 1.2
	ol.light_volumetric_fog_energy = 1.5
	ol.distance_fade_enabled = true
	ol.distance_fade_begin = 70.0
	ol.distance_fade_length = 20.0
	root.add_child(ol)
	h.light = ol
	return h


func _simple_head(root: Node3D, h: Dictionary) -> void:
	var pole := MeshInstance3D.new()
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.06
	cyl.bottom_radius = 0.08
	cyl.height = 3.6
	pole.mesh = cyl
	pole.position = Vector3(0, 1.8, 0)
	pole.material_override = _mats.body
	root.add_child(pole)
	var box := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = Vector3(0.36, 1.05, 0.26)
	box.mesh = bm
	box.position = Vector3(0, 3.05, 0.1)
	box.material_override = _mats.body
	root.add_child(box)
	var keys := ["red", "amber", "green"]
	for i in 3:
		var lamp := MeshInstance3D.new()
		var sm := SphereMesh.new()
		sm.radius = 0.1
		sm.height = 0.12
		sm.radial_segments = 12
		sm.rings = 6
		lamp.mesh = sm
		lamp.position = Vector3(0, 3.38 - i * 0.32, 0.23)
		lamp.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		root.add_child(lamp)
		h.lamps[keys[i]].append(lamp)
		# visor
		var vis := MeshInstance3D.new()
		var vm := BoxMesh.new()
		vm.size = Vector3(0.28, 0.02, 0.16)
		vis.mesh = vm
		vis.position = Vector3(0, 3.38 - i * 0.32 + 0.13, 0.3)
		vis.material_override = _mats.body
		root.add_child(vis)
	for c in root.get_children():
		if c is GeometryInstance3D:
			c.visibility_range_end = 220.0


func _show(h: Dictionary, st: int) -> void:
	var on: String = ["green", "amber", "red"][st]
	for k in ["red", "amber", "green"]:
		for mi in h.lamps[k]:
			if prop_scene and not h.mats.has(mi):
				_prop_mats(h, mi, k)
			if h.mats.has(mi):
				var arr: Array = h.mats[mi]
				for si in arr.size():
					var m: BaseMaterial3D = arr[si]
					m.emission_energy_multiplier = 12.0 if k == on else 0.05
			else:
				mi.material_override = _mats["%s_%s" % [k, "on" if k == on else "off"]]
	if h.light:
		h.light.light_color = {"green": Color(0.1, 1.0, 0.45), "amber": Color(1.0, 0.55, 0.0), "red": Color(1.0, 0.06, 0.03)}[on]


## Prop lamps keep their own look; only the emission is driven (per-head material copies).
func _prop_mats(h: Dictionary, mi: MeshInstance3D, key: String) -> void:
	var arr := []
	for si in mi.mesh.get_surface_count():
		var m = mi.get_active_material(si)
		var bm: BaseMaterial3D = m.duplicate() if m is BaseMaterial3D else StandardMaterial3D.new()
		bm.emission_enabled = true
		if bm.emission.get_luminance() < 0.05:
			bm.emission = _mats["%s_on" % key].emission
		mi.set_surface_override_material(si, bm)
		arr.append(bm)
	h.mats[mi] = arr


func _find_lamps(root: Node) -> Dictionary:
	var out := {"red": [], "amber": [], "green": []}
	var keys := {"red": ["red"], "amber": ["amber", "yellow", "orange"], "green": ["green"]}
	for strict in [true, false]:
		for n in _all(root):
			var nm := String(n.name).to_lower()
			if nm.begins_with("ped"):
				continue
			for k in keys:
				for word in keys[k]:
					if (nm.ends_with(word) if strict else nm.contains(word)):
						for mi in _all(n):
							if mi is MeshInstance3D and not out[k].has(mi):
								out[k].append(mi)
		if not out.red.is_empty():
			break
	return out


static func _all(n: Node) -> Array:
	var out := [n]
	for c in n.get_children():
		out.append_array(_all(c))
	return out
