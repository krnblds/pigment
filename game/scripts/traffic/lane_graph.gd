extends RefCounted
## Lane graph for traffic: directed lanes on roads + connector lanes through junctions.
##
## Built from either
##   * the town layout (res://assets/town/town_layout.json: "roads" centre lines + "road_info"
##     topology from tools/godot/export_town.py; inferred from the junction positions if absent), or
##   * the world lane format ("world-lanes/1", see docs/agents/traffic/NOTES.md), which the world
##     workstream's world.json carries.
## Everything is in Godot space (y up, metres).  Lanes are polylines with cumulative lengths; a car
## is (lane, s).  Connectors are lanes too (junction >= 0), so following a route is just lane -> next.
##
## Precomputed navigation data:
##   lane.next / prev            successor / predecessor lanes
##   lane.left / right           same-direction neighbour lanes (lane changes)
##   lane.group                  lanes of one road + direction (a connector may start in any of them)
##   connector.conflicts         connectors of the same junction whose paths cross or merge
##   connector.rank              priority (major road, then straight > kerb-side turn > crossing turn)
##   junction.approaches         incoming lane groups, used by the signal controller
##   grid                        spatial hash of lane samples (nearest-lane queries)
##   dist_to_exit                metres to the nearest dead end (despawn sink) per lane, by Dijkstra

const TURN_STRAIGHT := 0
const TURN_KERB := 1        ## the short turn (left when driving on the left)
const TURN_FAR := 2         ## the turn across oncoming traffic
const TURN_UTURN := 3
const TURN_NAMES := ["straight", "kerb", "far", "uturn"]
const CELL := 16.0

class Lane:
	var id := 0
	var name := ""
	var pts := PackedVector3Array()
	var cum := PackedFloat32Array()
	var length := 0.0
	var road := -1             ## road index (road lanes)
	var junction := -1         ## junction index (connectors)
	var start_junction := -1
	var end_junction := -1
	var approach := -1         ## approach index in end_junction (road lanes)
	var group := -1            ## lane group (road + direction)
	var kerb_index := 0        ## 0 = kerb-most lane of its group
	var turn := 0              ## connectors
	var rank := 0              ## connectors: priority
	var src := -1              ## connectors: source lane
	var dst := -1              ## connectors: exit lane
	var next := PackedInt32Array()
	var prev := PackedInt32Array()
	var left := -1             ## neighbour lane, same direction, on the travel-left side
	var right := -1
	var conflicts := PackedInt32Array()
	var speed := 13.9          ## m/s
	var width := 3.5
	var dist_to_exit := INF

	func pos_at(s: float) -> Vector3:
		var i := seg_at(s, 0)
		var a := cum[i]
		var b := cum[i + 1]
		return pts[i].lerp(pts[i + 1], clampf((s - a) / maxf(b - a, 1e-4), 0.0, 1.0))

	## Segment index containing s, searching forward from a hint (cars advance monotonically).
	func seg_at(s: float, hint: int) -> int:
		var n := pts.size() - 1
		var i := clampi(hint, 0, n - 1)
		if s < cum[i]:
			i = 0
		while i < n - 1 and cum[i + 1] < s:
			i += 1
		return i

	func dir_at_seg(i: int) -> Vector3:
		return (pts[i + 1] - pts[i]).normalized()

class Junction:
	var id := 0
	var name := ""
	var pos := Vector3.ZERO
	var control := "signal"    ## signal | yield | stop | none
	var approaches: Array = [] ## [{road, lanes: PackedInt32Array, dir (into the junction), major}]
	var connectors := PackedInt32Array()
	var signals: Array = []    ## explicit signal heads [{pos, facing, approach}] (world format)
	var phases: Array = []     ## explicit phases [{approaches: [i...], green, amber}]
	var radius := 12.0

var lanes: Array[Lane] = []
var junctions: Array[Junction] = []
var roads: Array = []          ## [{name, pts, half_width, parking: [sides], lanes: [ids]}]
var groups: Array = []         ## lane groups: PackedInt32Array of lane ids, kerb-most first
var drive_side := "left"
var source := ""
var lane_key := {}             ## "road id#lane index" -> lane id (world connections)
var grid := {}                 ## Vector2i -> PackedInt32Array of (lane id << 12 | sample index)


# ================================================================== queries
func lane_count() -> int:
	return lanes.size()


func road_lanes() -> Array:
	return lanes.filter(func(l): return l.junction < 0)


func kerb_sign() -> float:
	## +1: kerb is to the travel-left (drive on the left)
	return 1.0 if drive_side == "left" else -1.0


## Nearest lane sample to p: [lane id, s, distance] (lane id -1 if none in range).
func nearest(p: Vector3, max_dist := 24.0, only_roads := false, dir := Vector3.ZERO) -> Array:
	var c := Vector2i(floori(p.x / CELL), floori(p.z / CELL))
	var best := [-1, 0.0, INF]
	var r := int(ceil(max_dist / CELL))
	for dx in range(-r, r + 1):
		for dz in range(-r, r + 1):
			var k := Vector2i(c.x + dx, c.y + dz)
			if not grid.has(k):
				continue
			for code in grid[k]:
				var li: int = code >> 12
				var si: int = code & 4095
				var l: Lane = lanes[li]
				if only_roads and l.junction >= 0:
					continue
				var a := l.pts[si]
				var b := l.pts[mini(si + 1, l.pts.size() - 1)]
				var ab := b - a
				if dir != Vector3.ZERO and ab.dot(dir) <= 0.0:
					continue
				var t := clampf((p - a).dot(ab) / maxf(ab.length_squared(), 1e-6), 0.0, 1.0)
				var q := a + ab * t
				var d := Vector2(p.x - q.x, p.z - q.z).length() + absf(p.y - q.y) * 0.3
				if d < best[2]:
					best = [li, l.cum[si] + ab.length() * t, d]
	if best[2] > max_dist:
		best[0] = -1
	return best


## Shortest route (lane ids, start excluded) from lane a to lane b, Dijkstra on lane lengths.
func route(a: int, b: int, max_nodes := 4000) -> PackedInt32Array:
	var dist := {a: 0.0}
	var prev := {}
	var open := [[0.0, a]]
	var seen := 0
	while not open.is_empty() and seen < max_nodes:
		var bi := 0
		for i in open.size():
			if open[i][0] < open[bi][0]:
				bi = i
		var cur: Array = open[bi]
		open.remove_at(bi)
		var u: int = cur[1]
		if u == b:
			break
		if cur[0] > dist.get(u, INF):
			continue
		seen += 1
		for v in lanes[u].next:
			var nd: float = cur[0] + lanes[v].length
			if nd < dist.get(v, INF):
				dist[v] = nd
				prev[v] = u
				open.append([nd, v])
	var out := PackedInt32Array()
	if not dist.has(b) or a == b:
		return out
	var x := b
	while x != a:
		out.insert(0, x)
		x = prev[x]
	return out


# ================================================================== building blocks
func _add_lane(pts: PackedVector3Array, name := "") -> Lane:
	var l := Lane.new()
	l.id = lanes.size()
	l.name = name
	l.pts = pts
	_finish_lane(l)
	lanes.append(l)
	return l


static func _finish_lane(l: Lane) -> void:
	l.cum.resize(l.pts.size())
	var acc := 0.0
	l.cum[0] = 0.0
	for i in range(1, l.pts.size()):
		acc += l.pts[i].distance_to(l.pts[i - 1])
		l.cum[i] = acc
	l.length = acc


static func resample(pts: PackedVector3Array, step: float) -> PackedVector3Array:
	var out := PackedVector3Array()
	if pts.size() < 2:
		return pts
	out.append(pts[0])
	for i in range(1, pts.size()):
		var a := pts[i - 1]
		var b := pts[i]
		var n := int(ceil(a.distance_to(b) / step))
		for k in range(1, n + 1):
			out.append(a.lerp(b, float(k) / n))
	return out


## Offset a centre line sideways (+ = to the right of the point order), y kept.
static func offset_line(pts: PackedVector3Array, off: float) -> PackedVector3Array:
	var out := PackedVector3Array()
	out.resize(pts.size())
	for i in pts.size():
		var a := pts[maxi(0, i - 1)]
		var b := pts[mini(pts.size() - 1, i + 1)]
		var t := Vector3(b.x - a.x, 0.0, b.z - a.z).normalized()
		var right := t.cross(Vector3.UP)
		out[i] = pts[i] + right * off
	return out


static func reversed(pts: PackedVector3Array) -> PackedVector3Array:
	var out := PackedVector3Array()
	out.resize(pts.size())
	for i in pts.size():
		out[i] = pts[pts.size() - 1 - i]
	return out


func _junction_by_name(n) -> int:
	if n == null:
		return -1
	for j in junctions:
		if j.name == str(n):
			return j.id
	return -1


## Cut the part of a lane line that lies inside junction discs (world data may run to the centre).
func _trim_to_junctions(pts: PackedVector3Array, ja: int, jb: int) -> PackedVector3Array:
	var a := 0
	var b := pts.size() - 1
	if ja >= 0:
		var J := junctions[ja]
		while a < b - 1 and Vector2(pts[a].x - J.pos.x, pts[a].z - J.pos.z).length() < J.radius:
			a += 1
	if jb >= 0:
		var J := junctions[jb]
		while b > a + 1 and Vector2(pts[b].x - J.pos.x, pts[b].z - J.pos.z).length() < J.radius:
			b -= 1
	return pts.slice(a, b + 1)


## Road with explicit lanes: lane_defs = [{offset (+ right of point order), width, dir (+1/-1), speed}]
func add_road(name: String, centre: PackedVector3Array, lane_defs: Array, ja: int, jb: int, half_width: float, parking: Array = []) -> void:
	var road_i := roads.size()
	var rd := {"name": name, "pts": centre, "half_width": half_width, "parking": parking, "lanes": [],
		"start_junction": ja, "end_junction": jb}
	roads.append(rd)
	var by_dir := {1: [], -1: []}
	for d in lane_defs:
		var dir := int(d.dir)
		var line := offset_line(centre, float(d.offset))
		if dir < 0:
			line = reversed(line)
		var sj := ja if dir > 0 else jb
		var ej := jb if dir > 0 else ja
		line = _trim_to_junctions(resample(line, 3.0), sj, ej)
		if line.size() < 2:
			continue
		var l := _add_lane(line, "%s:%s%d" % [name, "f" if dir > 0 else "b", by_dir[dir].size()])
		l.road = road_i
		l.start_junction = sj
		l.end_junction = ej
		l.width = float(d.get("width", 3.5))
		l.speed = float(d.get("speed", 13.9))
		# kerb distance: drive on the left -> kerb side is the travel-left, i.e. the most negative
		# "right" offset in travel frame.  Travel-frame right offset = offset * dir.
		by_dir[dir].append([l.id, float(d.offset) * dir])
		rd.lanes.append(l.id)
		if d.has("index"):
			lane_key["%s#%d" % [name, int(d.index)]] = l.id
	for dir in by_dir:
		var arr: Array = by_dir[dir]
		if arr.is_empty():
			continue
		# kerb-most first: drive on the left -> most negative travel-right offset first
		arr.sort_custom(func(x, y): return x[1] * kerb_sign() < y[1] * kerb_sign())
		var g := PackedInt32Array()
		for e in arr:
			g.append(e[0])
		var gi := groups.size()
		groups.append(g)
		for k in g.size():
			var l: Lane = lanes[g[k]]
			l.group = gi
			l.kerb_index = k
			# travel-left / travel-right neighbours
			for k2 in g.size():
				if k2 == k:
					continue
				var o: Lane = lanes[g[k2]]
				var rel: float = arr[k2][1] - arr[k][1]      # + : o is to the travel-right
				if absf(rel) < l.width * 1.6:
					if rel > 0.0:
						l.right = o.id
					else:
						l.left = o.id


# ================================================================== importers
## Town layout (export_town.py).  One lane each way, drive on the left, offset 1.9 m.
func build_from_town(layout: Dictionary, clip: AABB = AABB()) -> void:
	source = "town_layout"
	drive_side = String(layout.get("drive_side", "left"))
	for jd in layout.get("junctions", []):
		var J := Junction.new()
		J.id = junctions.size()
		J.name = String(jd.name)
		J.pos = Vector3(jd.pos[0], jd.pos[1], jd.pos[2])
		var arm_len: Array = jd.get("arm_len", [])
		J.radius = (arm_len.min() - 0.5) if not arm_len.is_empty() else 12.0
		J.control = "yield" if String(jd.get("kind", "")) == "T" else "signal"
		junctions.append(J)
	var info: Array = layout.get("road_info", [])
	var polys: Array = layout.get("roads", [])
	for ri in polys.size():
		var pts := PackedVector3Array()
		for q in polys[ri]:
			pts.append(Vector3(q[0], q[1], q[2]))
		var hw := 4.0
		var dy := 0.2
		var ja := -1
		var jb := -1
		if ri < info.size():
			var inf: Dictionary = info[ri]
			hw = float(inf.get("half_width", 4.0))
			dy = float(inf.get("surface_dy", 0.2))
			if inf.get("from") != null:
				ja = _junction_by_name(inf.from.junction)
			if inf.get("to") != null:
				jb = _junction_by_name(inf.to.junction)
		else:
			ja = _nearest_junction(pts[0], 30.0)
			jb = _nearest_junction(pts[pts.size() - 1], 30.0)
		for i in pts.size():
			pts[i].y += dy
		if clip.size != Vector3.ZERO:
			pts = _clip_line(pts, clip)
			if pts.size() < 3:
				continue
			if ja >= 0 and pts[0].distance_to(junctions[ja].pos) > 40.0:
				ja = -1
			if jb >= 0 and pts[pts.size() - 1].distance_to(junctions[jb].pos) > 40.0:
				jb = -1
		var off := hw * 0.48            # lane centre ~1.9 m from the crown on an 8 m road
		var lw := hw - 0.4              # gutter excluded
		# drive on the left: the forward lane is left of the point order (offset < 0)
		var s := -1.0 if drive_side == "left" else 1.0
		add_road("R%d" % ri, pts, [{"offset": s * off, "width": lw, "dir": 1}, {"offset": -s * off, "width": lw, "dir": -1}],
				ja, jb, hw, ["left", "right"])
	_finish()


func _nearest_junction(p: Vector3, max_d: float) -> int:
	var best := -1
	var bd := max_d
	for J in junctions:
		var d := J.pos.distance_to(p)
		if d < bd:
			bd = d
			best = J.id
	return best


## Longest stretch inside the clip box (same rule as town_loader._clipped_roads).
static func _clip_line(pts: PackedVector3Array, box: AABB) -> PackedVector3Array:
	var best := PackedVector3Array()
	var cur := PackedVector3Array()
	for q in pts:
		if q.x > box.position.x and q.x < box.end.x and q.z > box.position.z and q.z < box.end.z:
			cur.append(q)
		else:
			if cur.size() > best.size():
				best = cur
			cur = PackedVector3Array()
	if cur.size() > best.size():
		best = cur
	return best


## World data: the world workstream's world.json ("pigment-world/1", Blender coordinates) or the
## same structure in Godot coordinates.  See docs/agents/traffic/NOTES.md for the fields used:
##   roads[]:     id, points [[x,y,z]] (road surface), lanes [{offset (+ = LEFT of the point order),
##                dir (+1 along the points / -1), width, kind: drive|parking}], start/end {node|junction},
##                speed_kmh (or speed_limit m/s), half_width
##   junctions[]: id, pos, kind (X/T/L/transition/plaza/end...), signalised | control, arms[{length,
##                half_width, road}], connections [{from {road, lane}, to {road, lane}, turn, points?}]
##   signals[]:   junction, controls {road, end}, pos, facing, phase (A/B/...)
## A "traffic" dict at the top level is read instead when present (a lanes-only file).
func build_from_world(w: Dictionary) -> void:
	if w.has("traffic") and w.traffic is Dictionary:
		w = w.traffic
	source = String(w.get("format", "world"))
	var side := String(w.get("drive_side", w.get("traffic", "left")))
	drive_side = "right" if side.begins_with("right") else "left"
	var coords := String(w.get("coords", "godot")).to_lower()
	var blender: bool = coords.begins_with("blender") or String(w.get("up", "y")) == "z"
	var conv := func(a: Array) -> Vector3:
		var z: float = a[2] if a.size() > 2 else 0.0
		return Vector3(a[0], z, -a[1]) if blender else Vector3(a[0], a[1], z)
	var conv_dir := func(a: Array) -> Vector3:
		# 2D directions are (x, y) in Blender space, (x, z) in Godot space
		if a.size() == 2:
			return Vector3(a[0], 0.0, -a[1]) if blender else Vector3(a[0], 0.0, a[1])
		return Vector3(a[0], a[2], -a[1]) if blender else Vector3(a[0], a[1], a[2])
	var default_speed := float(w.get("speed_limit", 13.9))
	# junctions (every node: transitions and dead ends too, so road ends can refer to them)
	for jd in w.get("junctions", []):
		var J := Junction.new()
		J.id = junctions.size()
		J.name = String(jd.get("id", jd.get("name", "J%d" % J.id)))
		J.pos = conv.call(jd.pos)
		var kind := String(jd.get("kind", "X"))
		var ctl := String(jd.get("control", ""))
		if ctl == "":
			if jd.get("signalised", false):
				ctl = "signal"
			elif kind in ["transition", "L", "end", "dead_end"]:
				ctl = "none"
			else:
				ctl = "yield"
		J.control = ctl
		var arms: Array = jd.get("arms", [])
		var r := float(jd.get("radius", 0.0))
		if r <= 0.0 and not arms.is_empty():
			r = arms.map(func(x): return float(x.get("length", 10.0))).min() * 0.6
		J.radius = r
		J.phases = jd.get("phases", [])
		if jd.has("priority_roads"):
			J.set_meta("priority_roads", jd.priority_roads)
		elif arms.size() >= 3:
			# the widest arms are the major road at unsignalled junctions
			var hw: Array = arms.map(func(x): return float(x.get("half_width", 0.0)))
			if hw.max() > hw.min() + 0.5:
				J.set_meta("priority_roads", arms.filter(func(x): return float(x.get("half_width", 0.0)) >= hw.max() - 0.01).map(func(x): return String(x.road)))
		J.set_meta("connections", jd.get("connections", []))
		for sd in jd.get("signals", []):
			J.signals.append(_signal_entry(sd, conv, conv_dir))
		junctions.append(J)
	for sd in w.get("signals", []):
		var j := _junction_by_name(sd.get("junction"))
		if j >= 0:
			junctions[j].signals.append(_signal_entry(sd, conv, conv_dir))
	# phases from the signals' phase letters
	for J in junctions:
		if J.phases.is_empty() and not J.signals.is_empty():
			var by := {}
			for sg in J.signals:
				if sg.phase != "" and sg.road != "":
					if not by.has(sg.phase):
						by[sg.phase] = []
					by[sg.phase].append(sg.road)
			var keys := by.keys()
			keys.sort()
			for k in keys:
				J.phases.append({"roads": by[k]})
	for rd in w.get("roads", []):
		var pts := PackedVector3Array()
		for q in rd.get("points", rd.get("centerline", [])):
			pts.append(conv.call(q))
		if pts.size() < 2:
			continue
		var ja := _junction_ref(rd.get("start", rd.get("from")))
		var jb := _junction_ref(rd.get("end", rd.get("to")))
		var speed := default_speed
		if rd.has("speed_limit"):
			speed = float(rd.speed_limit)
		elif rd.has("speed_kmh"):
			speed = float(rd.speed_kmh) / 3.6
		var lw := float(rd.get("lane_width", 3.5))
		var defs := []
		var parking := []
		if rd.has("lanes") and rd.lanes is Array:
			for li in rd.lanes.size():
				var ld: Dictionary = rd.lanes[li]
				var dv = ld.get("dir", 1)
				var dir := 1
				if dv is String:
					dir = -1 if String(dv).begins_with("b") or dv == "-1" else 1
				else:
					dir = -1 if float(dv) < 0.0 else 1
				var roff := -float(ld.get("offset", 0.0))       # internal: + = right of the point order
				var lkind := String(ld.get("kind", "drive"))
				if lkind == "parking":
					parking.append({"roff": roff, "dir": dir, "width": float(ld.get("width", 2.0))})
				elif lkind == "drive":
					defs.append({"offset": roff, "width": float(ld.get("width", lw)), "dir": dir, "speed": float(ld.get("speed", speed)),
						"index": int(ld.get("id", li))})
		else:
			var nf := int(rd.get("lanes_forward", 1))
			var nb := int(rd.get("lanes_backward", 0 if rd.get("one_way", rd.get("oneway", false)) else 1))
			var med := float(rd.get("median", 0.0)) * 0.5
			# drive on the left: forward lanes are left of the point order (internal offset < 0)
			var sg := -1.0 if drive_side == "left" else 1.0
			if nb == 0:
				for k in nf:
					defs.append({"offset": (k - (nf - 1) * 0.5) * lw, "width": lw, "dir": 1, "speed": speed})
			else:
				for k in nf:
					defs.append({"offset": sg * (med + lw * (k + 0.5)), "width": lw, "dir": 1, "speed": speed})
				for k in nb:
					defs.append({"offset": -sg * (med + lw * (k + 0.5)), "width": lw, "dir": -1, "speed": speed})
			for side_name in rd.get("parking", []):
				parking.append(side_name)
		var hw := float(rd.get("half_width", float(rd.get("width", 0.0)) * 0.5))
		if hw <= 0.0:
			for d in defs:
				hw = maxf(hw, absf(float(d.offset)) + float(d.width) * 0.5)
		add_road(String(rd.get("id", "R%d" % roads.size())), pts, defs, ja, jb, hw, parking)
	# connections: per junction (world.json) and / or top level
	var conns := []
	for J in junctions:
		for c in J.get_meta("connections", []):
			conns.append([J.id, c])
	for c in w.get("connections", []):
		conns.append([-1, c])
	_finish(conns, conv)


func _junction_ref(r) -> int:
	if r == null:
		return -1
	if r is Dictionary:
		return _junction_by_name(r.get("junction", r.get("node")))
	return _junction_by_name(r)


func _signal_entry(sd: Dictionary, conv: Callable, conv_dir: Callable) -> Dictionary:
	var road := ""
	var ctl = sd.get("controls", {})
	if ctl is Dictionary:
		road = String(ctl.get("road", ""))
	road = String(sd.get("road", road))
	var f: Vector3 = conv_dir.call(sd.get("facing", [0, 1]))
	return {"id": String(sd.get("id", "")), "pos": conv.call(sd.pos), "facing": f.normalized(),
		"road": road, "phase": String(sd.get("phase", "")), "mast": float(sd.get("mast", 0.0)),
		"approach": int(sd.approach) if sd.has("approach") else -1}


# ================================================================== junction topology
func _finish(explicit_connections: Array = [], conv = null) -> void:
	_build_approaches()
	if explicit_connections.is_empty():
		_build_connectors()
	else:
		_build_explicit_connectors(explicit_connections, conv)
	_build_conflicts()
	_build_grid()
	_build_exit_distances()


func _build_approaches() -> void:
	for J in junctions:
		J.approaches.clear()
	for gi in groups.size():
		var g: PackedInt32Array = groups[gi]
		var l: Lane = lanes[g[0]]
		if l.end_junction < 0:
			continue
		var J := junctions[l.end_junction]
		var d := Vector3.ZERO
		for li in g:
			d += lanes[li].dir_at_seg(lanes[li].pts.size() - 2)
		d.y = 0.0
		J.approaches.append({"road": l.road, "group": gi, "lanes": g, "dir": d.normalized(), "major": false})
		for li in g:
			lanes[li].approach = J.approaches.size() - 1
	# major road at yield junctions: the pair of approaches closest to opposite (or priority_roads)
	for J in junctions:
		var pr = J.get_meta("priority_roads") if J.has_meta("priority_roads") else null
		if pr is Array:
			for a in J.approaches:
				a["major"] = pr.has(roads[a.road].name)
			continue
		var best := 2.0
		var pair := [-1, -1]
		for i in J.approaches.size():
			for k in range(i + 1, J.approaches.size()):
				var dd: float = J.approaches[i].dir.dot(J.approaches[k].dir)
				if dd < best:
					best = dd
					pair = [i, k]
		if best < -0.7:
			J.approaches[pair[0]]["major"] = true
			J.approaches[pair[1]]["major"] = true


static func _turn_of(din: Vector3, dout: Vector3) -> int:
	var a := Vector3(din.x, 0, din.z).normalized().signed_angle_to(Vector3(dout.x, 0, dout.z).normalized(), Vector3.UP)
	if absf(a) < deg_to_rad(32.0):
		return TURN_STRAIGHT
	if absf(a) > deg_to_rad(150.0):
		return TURN_UTURN
	return 1 if a > 0.0 else 2   # + = counter-clockwise from above = left turn


func _kerb_turn(t: int) -> int:
	## turn code -> TURN_KERB / TURN_FAR for the drive side (left turn is kerb-side when driving on the left)
	if t == TURN_STRAIGHT or t == TURN_UTURN:
		return t
	var is_left := t == 1
	return TURN_KERB if is_left == (drive_side == "left") else TURN_FAR


func _out_groups(J: Junction) -> Array:
	var out := []
	for gi in groups.size():
		var l: Lane = lanes[groups[gi][0]]
		if l.start_junction == J.id:
			out.append(gi)
	return out


func _build_connectors() -> void:
	for J in junctions:
		var outs := _out_groups(J)
		for ai in J.approaches.size():
			var ap: Dictionary = J.approaches[ai]
			var gin: PackedInt32Array = ap.lanes
			for go in outs:
				var gout: PackedInt32Array = groups[go]
				var lo0: Lane = lanes[gout[0]]
				if lo0.road == ap.road and outs.size() > 1:
					continue           # no U-turns unless it is the only way out
				var din: Vector3 = ap.dir
				var dout := lo0.dir_at_seg(0)
				var turn := _kerb_turn(_turn_of(din, dout))
				if lo0.road == ap.road:
					turn = TURN_UTURN
				var n := gin.size()
				var m := gout.size()
				var pairs := []
				match turn:
					TURN_KERB:
						pairs.append([0, 0])
					TURN_FAR, TURN_UTURN:
						pairs.append([n - 1, m - 1])
					_:
						for k in n:
							pairs.append([k, mini(k, m - 1)])
				for p in pairs:
					_add_connector(J, ap, gin[p[0]], gout[p[1]], turn)


## conns: [[junction id or -1, {from: {road, lane} | "R:f0", to: ..., turn?, points?}]]
func _build_explicit_connectors(conns: Array, conv) -> void:
	for e in conns:
		var c: Dictionary = e[1]
		var a = _lane_ref(c.get("from"))
		var b = _lane_ref(c.get("to"))
		if a == null or b == null:
			continue          # parking lanes, roads clipped away...
		var la: Lane = lanes[a]
		var lb: Lane = lanes[b]
		var j: int = la.end_junction if la.end_junction >= 0 else int(e[0])
		if j < 0 or la.approach < 0:
			continue
		var J := junctions[j]
		var ap: Dictionary = J.approaches[la.approach]
		var turn := _kerb_turn(_turn_of(ap.dir, lb.dir_at_seg(0)))
		var tn := String(c.get("turn", ""))
		if tn != "":
			turn = {"straight": TURN_STRAIGHT, "left": _kerb_turn(1), "right": _kerb_turn(2), "uturn": TURN_UTURN}.get(tn, turn)
		var pts := PackedVector3Array()
		if c.has("points") and conv != null:
			for q in c.points:
				pts.append(conv.call(q))
		_add_connector(J, ap, a, b, turn, pts)


## Lane reference: {road, lane: index into the road's lanes array} or the internal name "R12:f0".
func _lane_ref(r):
	if r is Dictionary:
		return lane_key.get("%s#%d" % [String(r.get("road", "")), int(r.get("lane", 0))])
	for l in lanes:
		if l.name == String(r):
			return l.id
	return null


func _add_connector(J: Junction, ap: Dictionary, a: int, b: int, turn: int, given := PackedVector3Array()) -> void:
	var la: Lane = lanes[a]
	var lb: Lane = lanes[b]
	var p0 := la.pts[la.pts.size() - 1]
	var p3 := lb.pts[0]
	var d0 := la.dir_at_seg(la.pts.size() - 2)
	var d1 := lb.dir_at_seg(0)
	var dist := p0.distance_to(p3)
	var pts := PackedVector3Array()
	if dist < 0.6:
		# continuation (transition node): a short straight link
		pts.append(p0)
		pts.append(p0.lerp(p3, 0.5) + d0 * 0.3)
		pts.append(p3 + d1 * 0.05)
	elif given.size() >= 2:
		# the world's own connector curve, joined to our (trimmed / resampled) lane ends
		pts.append(p0)
		for q in given:
			if q.distance_to(p0) > 0.8 and q.distance_to(p3) > 0.8:
				pts.append(q)
		pts.append(p3)
		pts = resample(pts, 1.5)
	else:
		var k := dist * (0.42 if turn == TURN_STRAIGHT else 0.55)
		var c1 := p0 + d0 * k
		var c2 := p3 - d1 * k
		var n := maxi(4, int(ceil(dist / 1.5)))
		for i in n + 1:
			var t := float(i) / n
			var u := 1.0 - t
			var q := p0 * (u * u * u) + c1 * (3.0 * u * u * t) + c2 * (3.0 * u * t * t) + p3 * (t * t * t)
			q.y = lerpf(p0.y, p3.y, t * t * (3.0 - 2.0 * t))
			pts.append(q)
	var c := _add_lane(pts, "%s:%s>%s" % [J.name, la.name, lb.name])
	c.junction = J.id
	c.turn = turn
	c.src = a
	c.dst = b
	c.width = la.width
	c.speed = minf(la.speed, 7.5 if turn != TURN_STRAIGHT else la.speed * 0.85)
	c.rank = (10 if ap.major else 0) + [3, 2, 1, 0][turn]
	la.next.append(c.id)
	c.prev.append(a)
	c.next.append(b)
	lb.prev.append(c.id)
	J.connectors.append(c.id)


## Two connectors conflict when their paths come closer than ~a car width (crossing or merging),
## unless they leave from the same lane (those cars queue on that lane anyway).
func _build_conflicts() -> void:
	for J in junctions:
		var cs := J.connectors
		for i in cs.size():
			for k in range(i + 1, cs.size()):
				var a: Lane = lanes[cs[i]]
				var b: Lane = lanes[cs[k]]
				if a.src == b.src:
					continue
				var hit := a.dst == b.dst
				if not hit:
					hit = _paths_close(a.pts, b.pts, 3.0)
				if hit:
					a.conflicts.append(b.id)
					b.conflicts.append(a.id)


static func _paths_close(p: PackedVector3Array, q: PackedVector3Array, d: float) -> bool:
	var d2 := d * d
	for i in p.size():
		for k in q.size():
			var dx := p[i].x - q[k].x
			var dz := p[i].z - q[k].z
			if dx * dx + dz * dz < d2:
				return true
	return false


func _build_grid() -> void:
	grid.clear()
	for l in lanes:
		for i in l.pts.size():
			var k := Vector2i(floori(l.pts[i].x / CELL), floori(l.pts[i].z / CELL))
			if not grid.has(k):
				grid[k] = PackedInt32Array()
			grid[k].append((l.id << 12) | mini(i, 4095))


## Distance to the nearest dead end (lanes without successors), reverse Dijkstra.
func _build_exit_distances() -> void:
	var open := []
	for l in lanes:
		l.dist_to_exit = INF
		if l.next.is_empty():
			l.dist_to_exit = l.length
			open.append(l.id)
	while not open.is_empty():
		var u: int = open.pop_back()
		for p in lanes[u].prev:
			var nd: float = lanes[u].dist_to_exit + lanes[p].length
			if nd < lanes[p].dist_to_exit - 0.01:
				lanes[p].dist_to_exit = nd
				open.append(p)


## Raise / lower lane samples onto the real road surface (call once the town collision exists).
func snap_to_ground(space: PhysicsDirectSpaceState3D, mask := 1, exclude: Array = []) -> int:
	var moved := 0
	var q := PhysicsRayQueryParameters3D.new()
	q.collision_mask = mask
	var ex: Array[RID] = []
	ex.assign(exclude)
	q.exclude = ex
	for l in lanes:
		for i in l.pts.size():
			var p := l.pts[i]
			q.from = p + Vector3.UP * 2.0
			q.to = p - Vector3.UP * 2.5
			var hit := space.intersect_ray(q)
			if hit and absf(hit.position.y - p.y) < 1.2:
				l.pts[i].y = hit.position.y
				moved += 1
		_finish_lane(l)
	return moved


func summary() -> Dictionary:
	var n_road := 0
	var n_conn := 0
	var total := 0.0
	var conflicts := 0
	var turns := [0, 0, 0, 0]
	var multi := 0
	for l in lanes:
		if l.junction >= 0:
			n_conn += 1
			conflicts += l.conflicts.size()
			turns[l.turn] += 1
		else:
			n_road += 1
			total += l.length
			if l.left >= 0 or l.right >= 0:
				multi += 1
	return {"source": source, "drive_side": drive_side, "roads": roads.size(), "junctions": junctions.size(),
		"road_lanes": n_road, "connectors": n_conn, "lane_km": snappedf(total / 1000.0, 0.01),
		"turns": {"straight": turns[0], "kerb": turns[1], "far": turns[2], "uturn": turns[3]},
		"conflict_pairs": conflicts / 2, "multi_lane_lanes": multi,
		"dead_ends": lanes.filter(func(l): return l.next.is_empty()).size()}


## Debug / doc dump of the graph (lane ids, names, lengths, next, conflicts).
func to_dict() -> Dictionary:
	var ls := []
	for l in lanes:
		ls.append({"id": l.id, "name": l.name, "len": snappedf(l.length, 0.1), "junction": l.junction, "turn": TURN_NAMES[l.turn] if l.junction >= 0 else null,
			"next": Array(l.next), "left": l.left, "right": l.right, "conflicts": Array(l.conflicts)})
	return {"summary": summary(), "lanes": ls}
