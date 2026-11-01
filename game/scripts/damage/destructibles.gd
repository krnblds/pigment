extends Node3D
## The destructible world: street props from the layout (town_layout.json / world_layout.json) that
## break, fall, burst or get knocked around, following game/data/damage/props.json
## (tools/props/damage_table.py; the behaviours are described there).
##
## Every prop instance of a known kind is indexed in an 8 m grid at load (no nodes). Then, around the
## player only:
##   * armed colliders: props that should stop a slow car (poles, bollards, hydrants, kiosks, the bus
##     stop, barriers) get a static body within ARM_R; the town kit's lamps / power poles already have
##     the loader's collision.
##   * hit prediction: each physics tick, every car that can hit things (the hero, loose traffic) is
##     tested against the props near it (its box grown by its travel over the next ticks). Loose things
##     turn into rigid bodies just before the car touches them, so the physics shoves them away.
##     Anchored things break when the closing impulse (car mass x closing speed) passes their threshold;
##     below it they hold (the car crashes into them). A hit the prediction missed is caught from the
##     car's impact (damage `hit` signal).
## Breaking hides the instance in the loader's MultiMesh (town_loader.hide_instance), removes its static
## collision, spawns the pieces through the debris pool, and runs the effects: sparks, a flickering
## dying lamp, a hydrant geyser with a growing puddle, glass, cans, litter.
## Persistence: broken state is kept per instance for the session. Streaming a cell out and back in
## keeps it hidden (the loader edits its stored buffers); debris far away is pooled away; the stump
## stays.

const DATA := "res://data/damage/props.json"
const GRID := 8.0
const ARM_R := 45.0
const DISARM_R := 60.0
const ARM_EVERY := 0.25
const JET_TIME := 240.0           ## a burst hydrant runs this long, then dies down
const JET_FAR := 220.0            ## beyond this the geyser stops drawing (it keeps its time)

signal broke(id: int, kind: String)

var world: Node                   ## damage_manager.gd
var town: Node
var defs := {}                    ## prop name -> def
var keys: Array = []              ## per id: mesh key
var names: Array = []             ## per id: prop name
var xfs: Array = []               ## per id: Transform3D
var state := PackedByteArray()    ## per id: 0 intact, 1 broken / moved, 2 glass broken
var grid := {}                    ## Vector2i -> Array of ids
var armed := {}                   ## id -> StaticBody3D
var jets: Array = []              ## {id, node, t, puddle, hiss, pos}
var stats := {"indexed": 0, "broken": 0, "knocked": 0, "snapped": 0, "bursts": 0, "glass": 0, "armed": 0, "by_kind": {}}
var _arm_t := 0.0
var _arm_at := Vector3.INF
var _mesh_cache := {}
var _split_cache := {}
var _glassless := {}
var _static_pool: Array[StaticBody3D] = []
var _stump_mat: StandardMaterial3D


func setup(w: Node, t: Node) -> void:
	world = w
	town = t
	name = "Destructibles"
	process_physics_priority = -20       # before the car moves this tick
	if FileAccess.file_exists(DATA):
		defs = JSON.parse_string(FileAccess.get_file_as_string(DATA)).get("props", {})
	if town == null or town.layout.is_empty():
		return
	var key_def := {}
	for k in town.layout.meshes:
		var nm := _prop_name(String(k))
		if defs.has(nm) and String(defs[nm].kind) != "none":
			key_def[k] = nm
	for inst in town.layout.instances:
		var k := String(inst.mesh)
		if not key_def.has(k):
			continue
		var id := keys.size()
		var xf: Transform3D = town.xf_from(inst.xf)
		keys.append(k)
		names.append(key_def[k])
		xfs.append(xf)
		var g := Vector2i(floori(xf.origin.x / GRID), floori(xf.origin.z / GRID))
		if grid.has(g):
			(grid[g] as Array).append(id)
		else:
			grid[g] = [id]
	state.resize(keys.size())
	stats.indexed = keys.size()
	_stump_mat = StandardMaterial3D.new()
	_stump_mat.albedo_color = Color(0.16, 0.16, 0.17)
	_stump_mat.metallic = 0.8
	_stump_mat.roughness = 0.5


static func _prop_name(key: String) -> String:
	var k := key.trim_prefix("PROP_")
	var i := k.find("__")
	return k.substr(0, i) if i >= 0 else k


func kind_of(id: int) -> String:
	return String(defs[names[id]].kind)


## Ids within `r` of p (optionally of one prop name / kind).
func near(p: Vector3, r: float, prop := "", kind := "") -> Array:
	var out := []
	var g0 := Vector2i(floori((p.x - r) / GRID), floori((p.z - r) / GRID))
	var g1 := Vector2i(floori((p.x + r) / GRID), floori((p.z + r) / GRID))
	for x in range(g0.x, g1.x + 1):
		for z in range(g0.y, g1.y + 1):
			var c = grid.get(Vector2i(x, z))
			if c == null:
				continue
			for id in (c as Array):
				if (xfs[id] as Transform3D).origin.distance_to(p) > r:
					continue
				if prop != "" and names[id] != prop:
					continue
				if kind != "" and kind_of(id) != kind:
					continue
				out.append(id)
	return out


# ------------------------------------------------------------------ per tick
func _physics_process(delta: float) -> void:
	if keys.is_empty() or world == null:
		return
	var hero: RigidBody3D = world.hero
	if not is_instance_valid(hero):
		return
	_arm_t -= delta
	if _arm_t <= 0.0 or hero.global_position.distance_to(_arm_at) > 6.0:
		_arm_t = ARM_EVERY
		arm_around(hero.global_position)
	for car in world.hitters():
		_predict(car, delta)
	_tick_jets(delta)


## Static colliders for the anchored props near `p` (and none for those far away).
func arm_around(p: Vector3) -> void:
	_arm_at = p
	var want := {}
	for id in near(p, ARM_R):
		if state[id] == 1:
			continue
		var d: Dictionary = defs[names[id]]
		if String(d.kind) in ["knock", "heavy"] or bool(d.get("loader_collision", false)):
			continue
		want[id] = true
		if not armed.has(id):
			armed[id] = _make_static(id)
	for id in armed.keys():
		if not want.has(id) and (xfs[id] as Transform3D).origin.distance_to(p) > DISARM_R or state[id] == 1:
			_free_static(armed[id])
			armed.erase(id)
	stats.armed = armed.size()


func _make_static(id: int) -> StaticBody3D:
	var sb: StaticBody3D = _static_pool.pop_back() if not _static_pool.is_empty() else StaticBody3D.new()
	sb.collision_layer = 1
	sb.collision_mask = 0
	sb.set_meta("destructible", id)
	for s in _shapes(names[id]):
		var cs := CollisionShape3D.new()
		cs.shape = s[0]
		cs.transform = s[1]
		sb.add_child(cs)
	if sb.get_parent() == null:
		add_child(sb)
	var x: Transform3D = xfs[id]
	sb.global_transform = Transform3D(x.basis.orthonormalized(), x.origin)
	return sb


func _free_static(sb: StaticBody3D) -> void:
	for c in sb.get_children():
		sb.remove_child(c)
		c.queue_free()
	sb.global_position = Vector3(0, -6000, 0)
	_static_pool.append(sb)


## [[Shape3D, local Transform3D]] from the def's collider list (prop space).
func _shapes(nm: String) -> Array:
	var out := []
	for s in defs[nm].get("collider", []):
		var c: Array = s.center
		var xf := Transform3D(Basis(), Vector3(c[0], c[1], c[2]))
		if s.type == "box":
			var b := BoxShape3D.new()
			var sz: Array = s.size
			b.size = Vector3(maxf(sz[0], 0.04), maxf(sz[1], 0.04), maxf(sz[2], 0.04))
			out.append([b, xf])
		else:
			var cy := CylinderShape3D.new()
			cy.radius = maxf(float(s.radius), 0.04)
			cy.height = maxf(float(s.height), 0.08)
			out.append([cy, xf])
	if out.is_empty():
		var b := BoxShape3D.new()
		var sz: Array = defs[nm].get("size", [0.5, 0.5, 0.5])
		b.size = Vector3(sz[0], sz[1], sz[2])
		out.append([b, Transform3D(Basis(), Vector3(0, float(sz[1]) * 0.5, 0))])
	return out


## Footprint radius and height of a prop (from its bounds).
func _extent(nm: String) -> Vector2:
	var d: Dictionary = defs[nm]
	var b = d.get("bounds")
	if b is Dictionary:
		var lo: Array = b.min
		var hi: Array = b.max
		return Vector2(maxf(maxf(absf(lo[0]), absf(hi[0])), maxf(absf(lo[2]), absf(hi[2]))), float(hi[1]))
	var sz: Array = d.get("size", [0.5, 1.0, 0.5])
	return Vector2(maxf(sz[0], sz[2]) * 0.5, float(sz[1]))


## Will `car` touch a prop within the next ticks? Then knock it loose / break it / hold.
func _predict(car: RigidBody3D, delta: float) -> void:
	var v := car.linear_velocity
	var sp := v.length()
	var dims := _car_dims(car)
	var reach := dims.length() + sp * delta * 3.0 + 1.5
	var inv := car.global_transform.affine_inverse()
	var vl := car.global_basis.inverse() * v
	var margin := 0.12
	for id in near(car.global_position, reach):
		var st := state[id]
		var nm: String = names[id]
		var d: Dictionary = defs[nm]
		var kind := String(d.kind)
		if st == 1 or (st == 2 and kind == "shelter"):
			continue
		var x: Transform3D = xfs[id]
		var ext := _extent(nm)
		# the prop's footprint centre in car space (a disc of radius ext.x), grown along the travel
		var pl := inv * x.origin
		if pl.y > dims.y + 0.3 or pl.y + ext.y < -0.3:
			continue
		var ahead := vl * delta * 3.0
		var lo := Vector3(-dims.x, 0, -dims.z) + Vector3(minf(ahead.x, 0.0), 0, minf(ahead.z, 0.0))
		var hi := Vector3(dims.x, 0, dims.z) + Vector3(maxf(ahead.x, 0.0), 0, maxf(ahead.z, 0.0))
		var r := ext.x * (0.55 if kind in ["snap", "burst"] else 0.85) + margin
		if pl.x < lo.x - r or pl.x > hi.x + r or pl.z < lo.z - r or pl.z > hi.z + r:
			continue
		# closing impulse: car mass x its speed towards the prop
		var to := x.origin - car.global_position
		to.y = 0.0
		var n := to.normalized() if to.length() > 0.01 else car.global_basis.z
		var closing := maxf(0.0, v.dot(n))
		var j := car.mass * closing
		match kind:
			"knock", "heavy":
				if closing > 0.3 or sp > 0.5:
					break_prop(id, v, j, car)
			"snap", "burst", "topple", "bend":
				if j >= float(d.get("threshold", 1e9)):
					break_prop(id, v, j, car)
				elif d.has("glass") and st == 0 and j >= float(d.get("glass_threshold", 1e9)):
					shatter_glass(id)
			"shelter":
				if j >= float(d.get("glass_threshold", 1e9)):
					shatter_glass(id)


func _car_dims(car: Node) -> Vector3:
	if "half_len" in car:
		return Vector3(car.half_w, 1.5, car.half_len)
	var dd: Dictionary = car.spec.get("dimensions", {}) if "spec" in car else {}
	return Vector3(float(dd.get("width", 1.75)) * 0.5, float(dd.get("height", 1.4)), float(dd.get("length", 4.4)) * 0.5)


## A car's impact (vehicle_damage `hit`): break an anchored prop the prediction let stand.
func on_car_hit(pos: Vector3, impulse: float, car: RigidBody3D) -> void:
	for id in near(pos, 2.2):
		if state[id] == 1:
			continue
		var d: Dictionary = defs[names[id]]
		var kind := String(d.kind)
		if kind in ["snap", "burst", "topple", "bend"] and impulse >= float(d.get("threshold", 1e9)) * 0.8:
			break_prop(id, car.linear_velocity + (xfs[id].origin - car.global_position).normalized() * 3.0, impulse, car)
		elif d.has("glass") and state[id] == 0 and impulse >= float(d.get("glass_threshold", 1e9)):
			shatter_glass(id)


# ------------------------------------------------------------------ breaking
func break_prop(id: int, vel: Vector3, j: float, car: Node = null) -> void:
	if state[id] == 1:
		return
	var nm: String = names[id]
	var d: Dictionary = defs[nm]
	var kind := String(d.kind)
	var x: Transform3D = xfs[id]
	var had_glass := state[id] == 2
	state[id] = 1
	stats.broken += 1
	stats.by_kind[kind] = int(stats.by_kind.get(kind, 0)) + 1
	if armed.has(id):
		_free_static(armed[id])
		armed.erase(id)
	if bool(d.get("loader_collision", false)) and town.has_method("remove_collision_near"):
		town.remove_collision_near(x.origin, 0.8)
	if town.has_method("hide_instance"):
		town.hide_instance(keys[id], x.origin)
	var mat := String(d.get("material", "metal"))
	var audio = world.audio
	var fx = world.fx
	var base := x.origin + Vector3.UP * 0.15
	match kind:
		"knock", "heavy":
			stats.knocked += 1
			_spawn_pieces(id, vel * 0.25, false)
			if nm == "trash_bag_pile":
				fx.burst("litter", base + Vector3.UP * 0.3, Vector3.UP + vel.normalized() * 0.5, 1.0)
			elif nm == "cardboard_boxes" or nm == "crate_stack":
				fx.burst("dust", base, Vector3.UP, 0.5)
			if audio:
				audio.play({"bag": "bag_thump", "cardboard": "cardboard_thud", "wood": "wood_knock", "concrete": "wood_knock",
					"plastic": "plastic_clatter"}.get(mat, "metal_crunch_light"), base, clampf(j / 8000.0, 0.2, 1.0))
		_:
			stats.snapped += 1
			var rb := _spawn_pieces(id, vel, true)
			if had_glass == false and d.has("glass") and kind == "topple":
				_glass_burst(id)
			fx.burst("sparks", base, Vector3.UP + vel.normalized() * 0.4, 1.2 if mat == "metal" else 0.4)
			fx.burst("chips", base, Vector3.UP, 0.8)
			_stump(id)
			if audio:
				audio.play("pole_clang" if mat == "metal" else "wood_knock", base, clampf(j / 20000.0, 0.4, 1.0))
			if d.has("head"):
				_lamp_dies(id, rb)
			if kind == "burst":
				_burst_hydrant(id)
			if d.get("spill", "") == "cans":
				fx.burst("cans", x * Vector3(0, 0.5, 0.5), x.basis.z + Vector3.UP, 1.0)
				if audio:
					audio.play("can_rattle", base, 0.8)
	broke.emit(id, kind)


## The prop as one rigid body, or several (bags, boxes in a stack). Returns the (first) body.
func _spawn_pieces(id: int, vel: Vector3, tip: bool) -> RigidBody3D:
	var nm: String = names[id]
	var d: Dictionary = defs[nm]
	var x: Transform3D = xfs[id]
	var mass := float(d.get("mass", 20.0))
	var kindmat := String(d.get("material", "metal"))
	var mesh := _mesh(keys[id])
	var lift := Transform3D(x.basis, x.origin + Vector3.UP * 0.03)
	if d.has("chunks") and mesh:
		var parts := _split(keys[id], mesh, d.chunks)
		var first: RigidBody3D = null
		for p in parts:
			var mi := MeshInstance3D.new()
			mi.mesh = p.mesh
			var box := BoxShape3D.new()
			box.size = (p.size as Vector3).max(Vector3.ONE * 0.08)
			# the body sits at the chunk centre; the mesh is offset back
			add_child(mi)
			mi.global_transform = lift
			var cxf := lift * Transform3D(Basis(), p.center)
			var rb: RigidBody3D = world.debris.spawn([mi], [[box, Transform3D()]], cxf, mass / parts.size(),
				{"vel": vel + Vector3(randf_range(-0.5, 0.5), randf_range(0.2, 1.0), randf_range(-0.5, 0.5)),
				"angvel": Vector3(randf_range(-2, 2), randf_range(-2, 2), randf_range(-2, 2)), "kind": kindmat, "name": nm})
			if first == null:
				first = rb
		return first
	var nodes := []
	if mesh:
		var mi := MeshInstance3D.new()
		mi.mesh = _glassless_mesh(keys[id], mesh, d) if state[id] == 2 or (d.has("glass") and String(d.kind) == "topple") else mesh
		add_child(mi)
		mi.global_transform = lift
		nodes.append(mi)
	var av := Vector3.ZERO
	if tip:
		var h := _extent(nm).y
		var dir := Vector3(vel.x, 0, vel.z)
		if dir.length() < 0.1:
			dir = -x.basis.z
		av = Vector3.UP.cross(dir.normalized()) * clampf(vel.length() / maxf(h * 0.6, 0.5), 0.8, 6.0)
	var rb: RigidBody3D = world.debris.spawn(nodes, _shapes(nm), lift, mass,
		{"vel": vel * (0.55 if tip else 1.0) + Vector3.UP * 0.4, "angvel": av, "kind": "pole" if tip and kindmat == "metal" else kindmat, "name": nm})
	return rb


func _mesh(key: String) -> Mesh:
	if _mesh_cache.has(key):
		return _mesh_cache[key]
	var m: Mesh = null
	if town.has_method("_source_mesh"):
		m = town._source_mesh(key)
	_mesh_cache[key] = m
	return m


## Triangles grouped by the chunk box their centroid falls in (else the nearest box).
func _split(key: String, mesh: Mesh, chunks: Array) -> Array:
	if _split_cache.has(key):
		return _split_cache[key]
	var boxes := []
	for c in chunks:
		var cc: Array = c.center
		var sz: Array = c.size
		boxes.append(AABB(Vector3(cc[0], cc[1], cc[2]) - Vector3(sz[0], sz[1], sz[2]) * 0.5, Vector3(sz[0], sz[1], sz[2])))
	var sts := []
	for b in boxes:
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		sts.append(st)
	var used := []
	used.resize(boxes.size())
	used.fill(false)
	var mat: Material = null
	for s in mesh.get_surface_count():
		var a := mesh.surface_get_arrays(s)
		mat = mesh.surface_get_material(s)
		var v: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
		var nrm: PackedVector3Array = a[Mesh.ARRAY_NORMAL]
		var uv = a[Mesh.ARRAY_TEX_UV]
		var tan = a[Mesh.ARRAY_TANGENT]
		var idx: PackedInt32Array = a[Mesh.ARRAY_INDEX] if a[Mesh.ARRAY_INDEX] != null else PackedInt32Array(range(v.size()))
		for t in range(0, idx.size(), 3):
			var cen := (v[idx[t]] + v[idx[t + 1]] + v[idx[t + 2]]) / 3.0
			var best := 0
			var bd := INF
			for bi in boxes.size():
				var q: Vector3 = cen.clamp(boxes[bi].position, boxes[bi].end)
				var dd := q.distance_squared_to(cen)
				if dd < bd:
					bd = dd
					best = bi
			used[best] = true
			var st: SurfaceTool = sts[best]
			for k in 3:
				var vi := idx[t + k]
				st.set_normal(nrm[vi])
				if uv != null:
					st.set_uv(uv[vi])
				if tan != null and (tan as PackedFloat32Array).size() >= (vi + 1) * 4:
					st.set_tangent(Plane(tan[vi * 4], tan[vi * 4 + 1], tan[vi * 4 + 2], tan[vi * 4 + 3]))
				st.add_vertex(v[vi])
	var out := []
	for bi in boxes.size():
		if not used[bi]:
			continue
		var am: ArrayMesh = sts[bi].commit()
		if mat:
			am.surface_set_material(0, mat)
		# re-centre on the chunk so the body's origin is its middle
		var c: Vector3 = boxes[bi].get_center()
		out.append({"mesh": _offset_mesh(am, -c), "center": c, "size": boxes[bi].size})
	_split_cache[key] = out
	return out


static func _offset_mesh(m: ArrayMesh, off: Vector3) -> ArrayMesh:
	var a := m.surface_get_arrays(0)
	var v: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
	for i in v.size():
		v[i] += off
	a[Mesh.ARRAY_VERTEX] = v
	var out := ArrayMesh.new()
	out.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, a)
	out.surface_set_material(0, m.surface_get_material(0))
	return out


## The prop's mesh without its glass panes (triangles inside the panes' thin boxes).
func _glassless_mesh(key: String, mesh: Mesh, d: Dictionary) -> Mesh:
	if _glassless.has(key):
		return _glassless[key]
	var boxes := []
	for g in d.get("glass", []):
		var cc: Array = g.center
		var sz: Array = g.size
		boxes.append(AABB(Vector3(cc[0], cc[1], cc[2]) - Vector3(sz[0], sz[1], sz[2]) * 0.5, Vector3(sz[0], sz[1], sz[2])).grow(0.012))
	var out := ArrayMesh.new()
	for s in mesh.get_surface_count():
		var a := mesh.surface_get_arrays(s)
		var v: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
		var idx: PackedInt32Array = a[Mesh.ARRAY_INDEX] if a[Mesh.ARRAY_INDEX] != null else PackedInt32Array(range(v.size()))
		var keep := PackedInt32Array()
		for t in range(0, idx.size(), 3):
			var cen := (v[idx[t]] + v[idx[t + 1]] + v[idx[t + 2]]) / 3.0
			if boxes.any(func(b): return (b as AABB).has_point(cen)):
				continue
			keep.append(idx[t])
			keep.append(idx[t + 1])
			keep.append(idx[t + 2])
		a[Mesh.ARRAY_INDEX] = keep
		out.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, a)
		out.surface_set_material(s, mesh.surface_get_material(s))
	_glassless[key] = out
	return out


## Shelters, kiosks, vending machines: the glass goes, the prop stays (a glassless copy replaces it).
func shatter_glass(id: int) -> void:
	if state[id] != 0:
		return
	state[id] = 2
	stats.glass += 1
	var x: Transform3D = xfs[id]
	var mesh := _mesh(keys[id])
	if mesh and town.has_method("hide_instance"):
		town.hide_instance(keys[id], x.origin)
		var mi := MeshInstance3D.new()
		mi.name = "Glassless_%d" % id
		mi.mesh = _glassless_mesh(keys[id], mesh, defs[names[id]])
		mi.visibility_range_end = 160.0
		add_child(mi)
		mi.global_transform = x
	_glass_burst(id)


func _glass_burst(id: int) -> void:
	var x: Transform3D = xfs[id]
	for g in defs[names[id]].get("glass", []):
		var cc: Array = g.center
		var sz: Array = g.size
		var c := x * Vector3(cc[0], cc[1], cc[2])
		world.fx.burst("glass", c, Vector3.UP, clampf(maxf(sz[0], sz[2]) * float(sz[1]) * 0.8, 0.4, 2.0))
	if world.audio:
		world.audio.play("glass_shatter", x.origin + Vector3.UP, 0.9)


func _stump(id: int) -> void:
	var x: Transform3D = xfs[id]
	var shapes: Array = defs[names[id]].get("collider", [])
	var r := 0.1
	for s in shapes:
		if s.type == "cylinder":
			r = float(s.radius)
			break
	var cm := CylinderMesh.new()
	cm.top_radius = r * 0.95
	cm.bottom_radius = r * 1.05
	cm.height = 0.14
	cm.radial_segments = 10
	cm.rings = 1
	cm.material = _stump_mat
	var mi := MeshInstance3D.new()
	mi.name = "Stump_%d" % id
	mi.mesh = cm
	mi.visibility_range_end = 120.0
	add_child(mi)
	mi.global_position = x.origin + Vector3.UP * 0.07


## The lamp goes dark: its streamed light is switched off for good; a light rides on the falling pole,
## flickers with sparks and fizz, and dies.
func _lamp_dies(id: int, rb: RigidBody3D) -> void:
	var x: Transform3D = xfs[id]
	var hd: Array = defs[names[id]].head
	var head_local := Vector3(hd[0], hd[1], hd[2])
	var hw := x * head_local
	var col := Color(1.0, 0.82, 0.55)
	if town.has_method("kill_lights_near"):
		var gone: Array = town.kill_lights_near(hw, 1.6)
		if not gone.is_empty():
			col = gone[0][1]
	world.fx.burst("sparks", hw, Vector3.DOWN, 1.6)
	if world.audio:
		world.audio.play("electric_fizz", hw, 0.9)
	if rb == null:
		return
	var l := OmniLight3D.new()
	l.name = "DyingLamp"
	l.light_color = col
	l.omni_range = 16.0
	l.light_energy = 3.0
	l.light_volumetric_fog_energy = 1.5
	rb.add_child(l)
	l.position = (rb.global_transform.affine_inverse() * hw)
	var tw := create_tween()
	for i in 14:
		tw.tween_property(l, "light_energy", randf_range(0.0, 3.5) * (1.0 - i / 15.0), randf_range(0.03, 0.12))
		if i % 4 == 1:
			tw.tween_callback(func():
				if is_instance_valid(l):
					world.fx.burst("sparks", l.global_position, Vector3.DOWN, 0.6))
	tw.tween_property(l, "light_energy", 0.0, 0.2)
	tw.tween_callback(func():
		if is_instance_valid(l):
			l.queue_free())


# ------------------------------------------------------------------ hydrants
func _burst_hydrant(id: int) -> void:
	stats.bursts += 1
	var x: Transform3D = xfs[id]
	var pos := x.origin + Vector3.UP * 0.25
	var jet: Node3D = world.fx.water_jet(pos, 9.0)
	var puddle: Decal = world.fx.puddle(x.origin, 1.0)
	var hiss: AudioStreamPlayer3D = null
	if world.audio:
		world.audio.play("water_burst", pos, 1.0)
		hiss = world.audio.loop("water_hiss", jet, -2.0)
	jets.append({"id": id, "node": jet, "t": 0.0, "puddle": puddle, "hiss": hiss, "pos": pos})
	# old geysers beyond a dozen dry up early
	while jets.size() > 12:
		var j0: Dictionary = jets.pop_front()
		if is_instance_valid(j0.node):
			j0.node.queue_free()


func _tick_jets(delta: float) -> void:
	var cam := get_viewport().get_camera_3d()
	var cp: Vector3 = cam.global_position if cam else world.hero.global_position
	for j in jets:
		j.t += delta
		var node: Node3D = j.node
		if not is_instance_valid(node):
			continue
		var far: bool = cp.distance_to(j.pos) > JET_FAR
		var fade := clampf(1.0 - (j.t - JET_TIME) / 20.0, 0.0, 1.0)
		node.visible = not far and fade > 0.0
		for c in node.get_children():
			if c is GPUParticles3D:
				c.emitting = not far and fade > 0.0
				c.amount_ratio = fade
		if j.hiss:
			j.hiss.volume_db = linear_to_db(maxf(fade, 0.001)) - 2.0
		var pd: Decal = j.puddle
		if is_instance_valid(pd):
			var sz := lerpf(1.0, 7.5, clampf(j.t / 70.0, 0.0, 1.0))
			pd.size = Vector3(sz, 0.6, sz)


## For tests / HUD: active geysers.
func active_jets() -> int:
	var n := 0
	for j in jets:
		if is_instance_valid(j.node) and j.t < JET_TIME + 20.0:
			n += 1
	return n
