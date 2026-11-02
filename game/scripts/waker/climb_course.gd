extends Node3D
## The climber's scaffold run: physical scaffolding (StaticBody boxes on layer 1, steel-pipe dressing)
## sized for the on-foot controller: a 90 cm crate to vault, scaffold stairs (18 cm steps), a 1.6 m gap
## to jump, a 1.5 m ledge to mantle, more stairs, and a top deck 5 m up where the climber gets cornered.
## `nodes` is the climber's route: [{pos, move}] in world space (move: run | vault | jump | climb).
##
## place(origin, dir) tries the spot and a few turns / offsets until the footprint is free of the city.

var nodes: Array = []
var length := 33.0
var _mat_plank: StandardMaterial3D
var _mat_pipe: StandardMaterial3D
var _mat_crate: StandardMaterial3D
var _mat_glow: StandardMaterial3D

const PIECES := [
	# [size, centre (local: x along the run, y up, z across)]
	[Vector3(0.6, 0.9, 1.6), Vector3(4.3, 0.45, 0)],                 # crate to vault
	[Vector3(3.4, 1.8, 2.4), Vector3(12.3, 0.9, 0)],                 # deck A (1.8 m)
	[Vector3(3.4, 1.8, 2.4), Vector3(17.3, 0.9, 0)],                 # deck B after the 1.6 m gap
	[Vector3(4.0, 3.3, 2.4), Vector3(21.0, 1.65, 0)],                # deck C (ledge 1.5 m above B)
	[Vector3(6.0, 5.1, 2.4), Vector3(29.0, 2.55, 0)],                # top deck D (5.1 m)
]


func _ready() -> void:
	_mat_plank = _m(Color(0.22, 0.2, 0.17), 0.0, 0.85)
	_mat_pipe = _m(Color(0.5, 0.52, 0.55), 0.9, 0.35)
	_mat_crate = _m(Color(0.25, 0.3, 0.33), 0.2, 0.7)
	_mat_glow = _m(Color(1.0, 0.55, 0.15), 0.0, 0.5)
	_mat_glow.emission_enabled = true
	_mat_glow.emission = Color(1.0, 0.55, 0.15)
	_mat_glow.emission_energy_multiplier = 2.5


func _m(c: Color, metal: float, rough: float) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.metallic = metal
	m.roughness = rough
	return m


## Footprint free of world collision at (origin, dir)?
static func footprint_free(space: PhysicsDirectSpaceState3D, origin: Vector3, dir: Vector3) -> bool:
	var q := PhysicsShapeQueryParameters3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(33.0, 5.4, 3.0)
	q.shape = b
	q.collision_mask = 1 | 2
	var x := dir.normalized()
	var z := x.cross(Vector3.UP).normalized()
	q.transform = Transform3D(Basis(x, Vector3.UP, z), origin + x * 16.5 + Vector3.UP * 3.0)
	return space.intersect_shape(q, 1).is_empty()


func build(origin: Vector3, dir: Vector3) -> void:
	var x := Vector3(dir.x, 0, dir.z).normalized()
	var z := x.cross(Vector3.UP).normalized()
	global_transform = Transform3D(Basis(x, Vector3.UP, z), origin)
	for p in PIECES:
		_deck(p[0], p[1], p == PIECES[0])
	_stairs(Vector3(7.6, 0, 0), 10, 0.18, 0.3, 1.6)             # ground -> 1.8
	_stairs(Vector3(23.0, 3.3, 0), 10, 0.18, 0.3, 1.6)          # 3.3 -> 5.1
	# rails on the top deck (visual) and warning lamps
	for i in 7:
		_pipe(Vector3(26.0 + i, 5.1 + 0.5, 1.15), 1.0, false)
		_pipe(Vector3(26.0 + i, 5.1 + 0.5, -1.15), 1.0, false)
	_rail(Vector3(29.0, 6.1, 1.15), 6.0)
	_rail(Vector3(29.0, 6.1, -1.15), 6.0)
	for lp in [Vector3(12.3, 1.85, 1.1), Vector3(21.0, 3.35, 1.1), Vector3(31.8, 5.15, 0.0)]:
		var mi := MeshInstance3D.new()
		var s := SphereMesh.new()
		s.radius = 0.06
		s.height = 0.12
		mi.mesh = s
		mi.material_override = _mat_glow
		mi.position = lp
		add_child(mi)
	var l := OmniLight3D.new()
	l.light_color = Color(1.0, 0.6, 0.25)
	l.light_energy = 1.2
	l.omni_range = 9.0
	l.position = Vector3(21.0, 5.0, 0)
	add_child(l)
	var route := [[Vector3(0.5, 0, 0), "run"], [Vector3(3.4, 0, 0), "run"], [Vector3(5.4, 0, 0), "vault"], [Vector3(7.3, 0, 0), "run"],
		[Vector3(10.8, 1.8, 0), "run"], [Vector3(13.7, 1.8, 0), "run"], [Vector3(16.2, 1.8, 0), "jump"], [Vector3(18.6, 1.8, 0), "run"],
		[Vector3(19.7, 3.3, 0), "climb"], [Vector3(22.7, 3.3, 0), "run"], [Vector3(26.3, 5.1, 0), "run"], [Vector3(31.2, 5.1, 0), "run"]]
	nodes.clear()
	for r in route:
		nodes.append({"pos": global_transform * (r[0] as Vector3), "move": r[1]})


func _deck(size: Vector3, c: Vector3, crate: bool) -> void:
	var b := StaticBody3D.new()
	b.collision_layer = 1
	b.set_meta("surface", "metal" if not crate else "wood")
	var cs := CollisionShape3D.new()
	var bs := BoxShape3D.new()
	bs.size = size
	cs.shape = bs
	b.add_child(cs)
	b.position = c
	add_child(b)
	if crate:
		var mi := MeshInstance3D.new()
		var bm := BoxMesh.new()
		bm.size = size
		mi.mesh = bm
		mi.material_override = _mat_crate
		b.add_child(mi)
		return
	# a plank deck on a frame of pipes, open underneath
	var top := MeshInstance3D.new()
	var tm := BoxMesh.new()
	tm.size = Vector3(size.x, 0.08, size.z)
	top.mesh = tm
	top.material_override = _mat_plank
	top.position.y = size.y * 0.5 - 0.04
	b.add_child(top)
	for sx in [-0.5, 0.5]:
		for sz in [-0.5, 0.5]:
			_pipe(c + Vector3(size.x * sx * 0.96, -size.y * 0.5, size.z * sz * 0.92), size.y, true)
	for lv in range(1, int(size.y / 1.2) + 1):
		var y := c.y - size.y * 0.5 + lv * 1.2
		if y > c.y + size.y * 0.5 - 0.1:
			break
		_rail(Vector3(c.x, y, size.z * 0.46), size.x)
		_rail(Vector3(c.x, y, -size.z * 0.46), size.x)


func _pipe(base: Vector3, h: float, from_base: bool) -> void:
	var mi := MeshInstance3D.new()
	var cm := CylinderMesh.new()
	cm.top_radius = 0.03
	cm.bottom_radius = 0.03
	cm.height = h
	cm.radial_segments = 6
	cm.rings = 1
	mi.mesh = cm
	mi.material_override = _mat_pipe
	mi.position = base + Vector3.UP * (h * 0.5 if from_base else 0.0)
	add_child(mi)


func _rail(c: Vector3, len_: float) -> void:
	var mi := MeshInstance3D.new()
	var cm := CylinderMesh.new()
	cm.top_radius = 0.025
	cm.bottom_radius = 0.025
	cm.height = len_
	cm.radial_segments = 6
	cm.rings = 1
	mi.mesh = cm
	mi.material_override = _mat_pipe
	mi.position = c
	mi.rotation.z = PI * 0.5
	add_child(mi)


func _stairs(start: Vector3, n: int, rise: float, run: float, width: float) -> void:
	for i in n:
		var h := rise * (i + 1)
		var b := StaticBody3D.new()
		b.collision_layer = 1
		b.set_meta("surface", "metal")
		var cs := CollisionShape3D.new()
		var bs := BoxShape3D.new()
		bs.size = Vector3(run, h, width)
		cs.shape = bs
		b.add_child(cs)
		b.position = start + Vector3(run * (i + 0.5), h * 0.5, 0)
		var mi := MeshInstance3D.new()
		var tm := BoxMesh.new()
		tm.size = Vector3(run, 0.05, width)
		mi.mesh = tm
		mi.material_override = _mat_pipe if i % 2 == 0 else _mat_plank
		mi.position.y = h * 0.5 - 0.025
		b.add_child(mi)
		add_child(b)
	_rail(start + Vector3(run * n * 0.5, rise * n * 0.5 + 0.9, width * 0.5), run * n * 1.15)
