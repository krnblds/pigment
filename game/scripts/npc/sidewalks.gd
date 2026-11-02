extends RefCounted
## The pedestrian network: sidewalks, corners and crossings, derived from the world layout the traffic
## uses (assets/world/world.json: roads with their half widths and "curb" sides, junction arms; Blender
## coordinates -> Godot (x, z, -y)), plus the street furniture to walk round and the places to stop at.
##
##   node   E(arm, side): where a crosswalk meets the sidewalk (2.7 m back from each junction mouth, the
##          ped signals' spot), on the sidewalk centre line (curb + 1.75 m: between the curb-side furniture
##          at +0.75 and the frontage at +2.75)
##   edge   WALK      a sidewalk along one side of a road, E(start arm) -> E(end arm)
##          CORNER    round the corner between two neighbouring arms of a junction
##          CROSSING  across an arm (T / X junctions), on the road; signalled junctions -> wait for red
## Every walk edge stores, every 2 m, which of its two walking lines (+0.5 / -0.5 m from the centre)
## is blocked by furniture (lamps, bollards, benches, vending machines ...), so walkers weave round them.
## POIs: bus stops, benches, vending machines / kiosks / stalls, shop and bar fronts (shelter in the rain).
## Fallback without world.json: the traffic lane graph's roads, straight sidewalks only.

const WALK := 0
const CORNER := 1
const CROSSING := 2
const SIDE_OFF := 1.75
const WALK_Z := 0.35            ## sidewalk above the road centre line (tools/world/placement.py WALK_Z)
const ROAD_Z := 0.2
const CROSS_BACK := 2.7         ## crosswalk distance back from the junction mouth
const CELL := 32.0
const SAMPLE := 2.0

class Edge:
	var id := 0
	var a := 0
	var b := 0
	var kind := 0
	var pts := PackedVector3Array()
	var cum := PackedFloat32Array()
	var length := 0.0
	var junction := ""          ## world junction id (corners / crossings)
	var road := ""              ## world road id (walk edges / crossings)
	var block := PackedByteArray()  ## per SAMPLE metres: bit 0 = +0.5 line blocked, bit 1 = -0.5 line blocked
	var pois: Array = []        ## [{s, pos, face, kind}]
	var district := ""
	var bside := 0.0            ## lateral sign of the buildings (lateral + = right of the edge direction)

	func pos_at(s: float, hint := 0) -> Vector3:
		var i := seg_at(s, hint)
		var a0 := cum[i]
		var a1 := cum[i + 1]
		return pts[i].lerp(pts[i + 1], clampf((s - a0) / maxf(a1 - a0, 1e-4), 0.0, 1.0))

	func seg_at(s: float, hint := 0) -> int:
		var n := pts.size() - 1
		var i := clampi(hint, 0, n - 1)
		if s < cum[i]:
			i = 0
		while i < n - 1 and cum[i + 1] < s:
			i += 1
		return i

	func dir_at(s: float, hint := 0) -> Vector3:
		var i := seg_at(s, hint)
		var d := pts[i + 1] - pts[i]
		d.y = 0.0
		return d.normalized() if d.length_squared() > 1e-8 else Vector3.FORWARD

	func blocked(s: float, line: int) -> bool:
		if block.is_empty():
			return false
		var k := clampi(int(s / SAMPLE), 0, block.size() - 1)
		return (block[k] & (1 if line > 0 else 2)) != 0

var nodes := PackedVector3Array()
var adj: Array = []             ## node -> PackedInt32Array of edge ids
var edges: Array = []           ## [Edge]
var grid := {}                  ## Vector2i -> PackedInt32Array of edge ids
var pois: Array = []            ## [{pos, face, kind, edge, s}]
var source := ""
var stats := {}


# ================================================================== build
func build_from_world(w: Dictionary) -> void:
	source = "world"
	var conv := func(a: Array) -> Vector3:
		return Vector3(float(a[0]), float(a[2]) if a.size() > 2 else 0.0, -float(a[1]))
	var roads := {}
	for r in w.get("roads", []):
		roads[String(r.id)] = r
	var walkable := func(rid: String) -> bool:
		var r = roads.get(rid)
		return r != null and String(r.get("side", "curb")) == "curb" and String(r.get("class", "street")) in ["street", "avenue"]
	var ends := {}              # "junction|arm|side" -> node id
	var n_cross := 0
	var n_corner := 0
	var jinfo := {}
	for J in w.get("junctions", []):
		var jp: Vector3 = conv.call(J.pos)
		var arms: Array = J.get("arms", [])
		if arms.is_empty():
			continue
		var sorted := arms.duplicate()
		sorted.sort_custom(func(x, y): return float(x.angle) < float(y.angle))
		var jz := float(J.get("z", J.pos[2]))
		jinfo[String(J.id)] = {"signalised": bool(J.get("signalised", false)), "kind": String(J.get("kind", "X"))}
		for a in sorted:
			if not walkable.call(String(a.road)):
				continue
			var d := Vector2(float(a.dir[0]), float(a.dir[1]))
			var nrm := Vector2(-d.y, d.x)
			for s in [1, -1]:
				var p2: Vector2 = Vector2(jp.x, -jp.z) + d * maxf(float(a.length) - CROSS_BACK, 3.0) + nrm * s * (float(a.half_width) + SIDE_OFF)
				var id := _node(Vector3(p2.x, jz + WALK_Z, -p2.y))
				ends["%s|%d|%d" % [J.id, int(a.index), s]] = id
		# corners between neighbouring walkable arms
		var m := sorted.size()
		for i in m:
			var a0 = sorted[i]
			var a1 = sorted[(i + 1) % m]
			if m == 1 or a0 == a1:
				continue
			var k0 := "%s|%d|1" % [J.id, int(a0.index)]
			var k1 := "%s|%d|-1" % [J.id, int(a1.index)]
			if not ends.has(k0) or not ends.has(k1):
				continue
			var gap := fposmod(float(a1.angle) - float(a0.angle), 360.0)
			var pts := _corner(Vector2(jp.x, -jp.z), a0, a1, gap, jz + WALK_Z, nodes[ends[k0]], nodes[ends[k1]])
			_edge(ends[k0], ends[k1], CORNER, pts, String(J.id), "")
			n_corner += 1
		# dead end: walk round the end of the road
		if m == 1:
			var a = sorted[0]
			var k0 := "%s|%d|1" % [J.id, int(a.index)]
			var k1 := "%s|%d|-1" % [J.id, int(a.index)]
			if ends.has(k0) and ends.has(k1):
				_edge(ends[k0], ends[k1], CORNER, PackedVector3Array([nodes[ends[k0]], nodes[ends[k1]]]), String(J.id), "")
		# crossings over every walkable arm of T / X junctions
		if m >= 3:
			for a in sorted:
				var k0 := "%s|%d|1" % [J.id, int(a.index)]
				var k1 := "%s|%d|-1" % [J.id, int(a.index)]
				if not ends.has(k0) or not ends.has(k1):
					continue
				var p0 := nodes[ends[k0]]
				var p1 := nodes[ends[k1]]
				var road_y := jz + ROAD_Z
				var dd := (p1 - p0)
				dd.y = 0
				var L := dd.length()
				var u := dd / maxf(L, 0.01)
				var pts := PackedVector3Array([p0, Vector3(p0.x, road_y, p0.z) + u * (SIDE_OFF - 0.1),
					Vector3(p1.x, road_y, p1.z) - u * (SIDE_OFF - 0.1), p1])
				_edge(ends[k0], ends[k1], CROSSING, pts, String(J.id), String(a.road))
				n_cross += 1
	# sidewalks along the roads
	var n_walk := 0
	for r in w.get("roads", []):
		var rid := String(r.id)
		if not walkable.call(rid):
			continue
		var st = r.get("start")
		var en = r.get("end")
		if not (st is Dictionary and en is Dictionary) or st.get("arm") == null or en.get("arm") == null:
			continue
		var line := PackedVector3Array()
		for q in r.get("points", []):
			line.append(conv.call(q))
		if line.size() < 2:
			continue
		var hw := float(r.get("half_width", 5.0))
		for s in [1, -1]:
			var ka := "%s|%d|%d" % [st.node, int(st.arm), s]
			var kb := "%s|%d|%d" % [en.node, int(en.arm), -s]
			if not ends.has(ka) or not ends.has(kb):
				continue
			var pa := nodes[ends[ka]]
			var pb := nodes[ends[kb]]
			var off := _offset(line, s * (hw + SIDE_OFF))
			var mid := PackedVector3Array([pa])
			# keep the offset samples between the two crosswalk ends (by projection on pa -> pb)
			var ab := pb - pa
			ab.y = 0
			var L2 := ab.length_squared()
			for q in off:
				var t := ((q - pa) * Vector3(1, 0, 1)).dot(ab) / maxf(L2, 1e-4)
				if t > 0.02 and t < 0.98 and Vector2(q.x - pa.x, q.z - pa.z).length() > 3.0 and Vector2(q.x - pb.x, q.z - pb.z).length() > 3.0:
					mid.append(q + Vector3.UP * WALK_Z)
			mid.append(pb)
			var e := _edge(ends[ka], ends[kb], WALK, _resample(mid, SAMPLE), "", rid)
			e.bside = -float(s)        # offset to the road's (Blender-)left = our lateral -, buildings beyond
			n_walk += 1
	_furniture(w, conv)
	_build_grid()
	stats = {"nodes": nodes.size(), "edges": edges.size(), "walk": n_walk, "corners": n_corner, "crossings": n_cross,
		"pois": pois.size(), "km": snappedf(edges.reduce(func(acc, e): return acc + e.length, 0.0) / 1000.0, 0.1)}


## Fallback (town map, or no world.json): straight sidewalks from the traffic graph's roads.
func build_from_graph(G) -> void:
	source = "lane_graph"
	for rd in G.roads:
		for s in [1.0, -1.0]:
			var line: PackedVector3Array = G.offset_line(G.resample(rd.pts, SAMPLE), (float(rd.half_width) + 2.4) * s)
			var cur := PackedVector3Array()
			for q in line:
				var near := false
				for J in G.junctions:
					if Vector2(q.x - J.pos.x, q.z - J.pos.z).length() < J.radius + 3.0:
						near = true
						break
				if near:
					if cur.size() > 6:
						_edge(_node(cur[0]), _node(cur[cur.size() - 1]), WALK, cur, "", String(rd.name))
					cur = PackedVector3Array()
				else:
					cur.append(q + Vector3.UP * 0.25)
			if cur.size() > 6:
				_edge(_node(cur[0]), _node(cur[cur.size() - 1]), WALK, cur, "", String(rd.name))
	_build_grid()
	stats = {"nodes": nodes.size(), "edges": edges.size(), "source": source}


func _node(p: Vector3) -> int:
	nodes.append(p)
	adj.append(PackedInt32Array())
	return nodes.size() - 1


func _edge(a: int, b: int, kind: int, pts: PackedVector3Array, junction: String, road: String) -> Edge:
	var e := Edge.new()
	e.id = edges.size()
	e.a = a
	e.b = b
	e.kind = kind
	e.pts = pts
	e.junction = junction
	e.road = road
	var acc := 0.0
	e.cum.append(0.0)
	for i in range(1, pts.size()):
		acc += pts[i].distance_to(pts[i - 1])
		e.cum.append(acc)
	e.length = maxf(acc, 0.01)
	edges.append(e)
	adj[a].append(e.id)
	adj[b].append(e.id)
	return e


static func _offset(line: PackedVector3Array, off: float) -> PackedVector3Array:
	# + off = left of travel in Blender's x/y (= +nrm of the arms); in Godot x/z that is (-t.z... ) see conv
	var out := PackedVector3Array()
	var n := line.size()
	for i in n:
		var a := line[maxi(i - 1, 0)]
		var b := line[mini(i + 1, n - 1)]
		var t := Vector2(b.x - a.x, -(b.z - a.z)).normalized()       # Blender (x, y) tangent
		var nb := Vector2(-t.y, t.x) * off                            # Blender left normal
		out.append(line[i] + Vector3(nb.x, 0.0, -nb.y))
	return out


static func _resample(pts: PackedVector3Array, step: float) -> PackedVector3Array:
	var out := PackedVector3Array()
	if pts.size() < 2:
		return pts
	out.append(pts[0])
	var carry := 0.0
	for i in range(1, pts.size()):
		var a := pts[i - 1]
		var b := pts[i]
		var L := a.distance_to(b)
		var t := step - carry
		while t < L:
			out.append(a.lerp(b, t / L))
			t += step
		carry = L - (t - step)
	if out[out.size() - 1].distance_to(pts[pts.size() - 1]) > 0.2:
		out.append(pts[pts.size() - 1])
	else:
		out[out.size() - 1] = pts[pts.size() - 1]
	return out


func _corner(jc: Vector2, a0, a1, gap: float, y: float, e0: Vector3, e1: Vector3) -> PackedVector3Array:
	var d0 := Vector2(float(a0.dir[0]), float(a0.dir[1]))
	var d1 := Vector2(float(a1.dir[0]), float(a1.dir[1]))
	var p0 := jc + Vector2(-d0.y, d0.x) * (float(a0.half_width) + SIDE_OFF)
	var p1 := jc - Vector2(-d1.y, d1.x) * (float(a1.half_width) + SIDE_OFF)
	var out := PackedVector3Array([e0])
	if absf(gap - 180.0) > 20.0:
		# intersection of the two sidewalk lines
		var den := d0.x * d1.y - d0.y * d1.x
		if absf(den) > 1e-4:
			var q := p1 - p0
			var t := (q.x * d1.y - q.y * d1.x) / den
			var c := p0 + d0 * t
			var lim := 2.0 * maxf(float(a0.length), float(a1.length))
			if c.distance_to(jc) < lim:
				var c3 := Vector3(c.x, y, -c.y)
				out.append_array(_resample(PackedVector3Array([e0, c3]), SAMPLE).slice(1))
				out.append_array(_resample(PackedVector3Array([c3, e1]), SAMPLE).slice(1))
				return out
	return _resample(PackedVector3Array([e0, e1]), SAMPLE)


# ------------------------------------------------------------------ furniture + places
const SOLID := {"bollard": 0.2, "street_lamp": 0.25, "parking_meter": 0.2, "bench": 0.9, "vending_machine": 0.6,
	"trash_bin": 0.35, "trash_bag_pile": 0.6, "planter": 0.6, "tree_grate": 0.7, "power_pole": 0.3, "cctv_pole": 0.25,
	"traffic_light_mast": 0.35, "ped_signal": 0.2, "data_kiosk": 0.5, "phone_kiosk": 0.6, "bus_stop": 1.7, "fire_hydrant": 0.25,
	"bicycle": 0.8, "scooter": 0.8, "street_name_sign": 0.15, "holo_pylon": 0.4, "skewer_stall": 1.3, "cardboard_boxes": 0.5,
	"tree_planter_box": 0.7, "tree_planter_azalea": 0.7, "traffic_cone": 0.2, "overhead_sign": 0.25}
const POI_KIND := {"bus_stop": "bus", "bench": "bench", "vending_machine": "vending", "data_kiosk": "kiosk", "phone_kiosk": "kiosk",
	"skewer_stall": "stall"}


func _furniture(w: Dictionary, conv: Callable) -> void:
	# a coarse grid of the walk edges' samples, to find what is on which sidewalk
	var sg := {}
	for e in edges:
		if e.kind != WALK:
			continue
		e.block.resize(maxi(1, int(e.length / SAMPLE) + 1))
		for i in e.pts.size():
			var k := Vector2i(floori(e.pts[i].x / 8.0), floori(e.pts[i].z / 8.0))
			if not sg.has(k):
				sg[k] = []
			sg[k].append([e, i])
	var n_block := 0
	for inst in w.get("instances", []):
		var asset := String(inst.get("asset", ""))
		var r := float(SOLID.get(asset, 0.0))
		if asset.begins_with("tree_") and r == 0.0:
			r = 0.6
		if r == 0.0:
			continue
		var p: Vector3 = conv.call(inst.pos)
		var k0 := Vector2i(floori(p.x / 8.0), floori(p.z / 8.0))
		var best = null
		var bd := 4.5
		var bi := 0
		for dx in [-1, 0, 1]:
			for dz in [-1, 0, 1]:
				for it in sg.get(k0 + Vector2i(dx, dz), []):
					var e: Edge = it[0]
					var q: Vector3 = e.pts[it[1]]
					var d := Vector2(q.x - p.x, q.z - p.z).length()
					if d < bd:
						bd = d
						best = e
						bi = it[1]
		if best == null:
			continue
		var e: Edge = best
		var s := e.cum[bi]
		var dir := e.dir_at(s, bi)
		var left := Vector3(-dir.z, 0, dir.x)
		var lat := (p - e.pts[bi]).dot(left)
		# which walking line (+0.5 / -0.5) does it sit on, over which samples
		for line in [1, -1]:
			if absf(lat - 0.5 * line) < r + 0.35:
				var s0 := s - r - 0.4
				var s1 := s + r + 0.4
				for k in range(maxi(0, int(s0 / SAMPLE)), mini(e.block.size(), int(s1 / SAMPLE) + 1)):
					e.block[k] |= (1 if line > 0 else 2)
				n_block += 1
		if POI_KIND.has(asset):
			var face := Vector3(-sin(float(inst.get("rot", 0.0))), 0, -cos(float(inst.get("rot", 0.0))))
			# stand on the sidewalk side of it, facing it (benches: sit facing the road)
			var spot := p + left * signf(-lat) * (0.9 if asset != "bench" else 0.0)
			var poi := {"pos": Vector3(spot.x, e.pts[bi].y, spot.z), "face": face, "kind": POI_KIND[asset], "edge": e.id, "s": s,
				"lat": clampf(lat, -1.2, 1.2), "asset": asset, "district": String(inst.get("district", ""))}
			if asset == "bench":
				poi.pos = Vector3(p.x, e.pts[bi].y, p.z)
			pois.append(poi)
			e.pois.append(poi)
	# shop / bar fronts: every ~18 m on the building side of walk edges (shelter in the rain, loiter)
	var rng := RandomNumberGenerator.new()
	rng.seed = 77
	for e in edges:
		if e.kind != WALK or e.length < 20.0:
			continue
		var s := rng.randf_range(6.0, 14.0)
		while s < e.length - 6.0:
			var i: int = e.seg_at(s)
			var dir: Vector3 = e.dir_at(s, i)
			var left := Vector3(-dir.z, 0, dir.x)
			var p: Vector3 = e.pos_at(s, i)
			# the building side is away from the road: the road is on the side of the centre line we were offset from
			var side := _building_side(e, s)
			var poi := {"pos": p + left * side * 1.15, "face": -left * side, "kind": "front", "edge": e.id, "s": s, "lat": side * 1.15,
				"asset": "", "district": ""}
			pois.append(poi)
			e.pois.append(poi)
			s += rng.randf_range(14.0, 26.0)
	for e in edges:
		e.pois.sort_custom(func(x, y): return x.s < y.s)
	stats["blocked"] = n_block


## Lateral sign (+ = right of the edge direction) of the buildings along a walk edge.
func _building_side(e: Edge, _s: float) -> float:
	return e.bside if e.bside != 0.0 else 1.0


func _build_grid() -> void:
	for e in edges:
		var seen := {}
		for p in e.pts:
			var k := Vector2i(floori(p.x / CELL), floori(p.z / CELL))
			if not seen.has(k):
				seen[k] = true
				if not grid.has(k):
					grid[k] = PackedInt32Array()
				grid[k].append(e.id)


## Edges with a sample within r of p.
func edges_near(p: Vector3, r: float) -> PackedInt32Array:
	var out := PackedInt32Array()
	var seen := {}
	var k0 := Vector2i(floori((p.x - r) / CELL), floori((p.z - r) / CELL))
	var k1 := Vector2i(floori((p.x + r) / CELL), floori((p.z + r) / CELL))
	for x in range(k0.x, k1.x + 1):
		for z in range(k0.y, k1.y + 1):
			for id in grid.get(Vector2i(x, z), PackedInt32Array()):
				if not seen.has(id):
					seen[id] = true
					out.append(id)
	return out


## [edge id, s, distance] of the closest point of any edge (kinds filter) to p within r, or [-1, 0, INF].
func nearest(p: Vector3, r := 30.0, walk_only := false) -> Array:
	var best := [-1, 0.0, INF]
	for id in edges_near(p, r):
		var e: Edge = edges[id]
		if walk_only and e.kind != WALK:
			continue
		for i in e.pts.size() - 1:
			var a := e.pts[i]
			var b := e.pts[i + 1]
			var ab := b - a
			var t := clampf((p - a).dot(ab) / maxf(ab.length_squared(), 1e-6), 0.0, 1.0)
			var q := a + ab * t
			var d := Vector2(q.x - p.x, q.z - p.z).length() + absf(q.y - p.y) * 0.3
			if d < best[2]:
				best = [id, e.cum[i] + (e.cum[i + 1] - e.cum[i]) * t, d]
	return best
