extends RefCounted
## Soft-body-ish denting of one vehicle mesh on the CPU, only when it is hit.
##
## On its first dent the MeshInstance3D gets its own ArrayMesh copy (traffic cars share their meshes).
## A dent pushes the vertices within `radius` of the impact point along the impact direction and
## buckles them across it, with creases rather than a smooth bowl:
##     w      = smoothstep(1, 0.3, r / radius)                (a crushed plateau, then a falloff)
##     crease = (1 - |noise(p * 4 m^-1 + panel phase)|)^2      (ridged noise: sharp fold lines)
##     offset = dir * depth * w * (0.6 + 0.8 crease)          (push: a frontal hit shortens the nose)
##            + buckle * depth * w * 0.32 * (1.3 crease - 0.35) (folds across the push; for a frontal or
##                                                               side hit "buckle" is up: the bonnet
##                                                               buckles upward, wings and doors fold)
##            + dir * depth * w * 0.04 * noise(p * 23 m^-1)   (fine per-vertex crumple)
## Every panel is its own mesh with its own noise phase, so folds break at the shut lines.
## Normals follow the field's gradient (n' = n - grad(f) (dir . n) - grad(g) (buckle . n)), so the
## creases catch the light. Stable: one dent moves a vertex at most 1.4 x depth, a vertex never ends up
## more than MAX_OFFSET from its rest position, and dents accumulate.
## Vertices are found through a 25 cm grid (built on a worker thread; shared by every instance of the
## same mesh), so a dent costs ~ the vertices it touches, not the whole mesh. Vertices at the same
## position move identically, so split normals / UV seams stay closed.

const CELL := 0.25
const MAX_OFFSET := 0.55
const FREQ := 4.0

static var _grids := {}          ## source mesh instance id -> [per surface Dictionary Vector3i -> Array of vertex ids]
static var _noise: FastNoiseLite

var mi: MeshInstance3D
var orig_mesh: Mesh
var mesh: ArrayMesh
var arrays: Array = []
var orig_pos: Array = []
var orig_nrm: Array = []
var mats: Array = []
var dents := 0
var _task := -1
var _key := 0
var _phase := Vector3.ZERO      ## per panel: folds don't run across shut lines


func _init(m: MeshInstance3D) -> void:
	mi = m
	orig_mesh = m.mesh
	_key = orig_mesh.get_instance_id() if orig_mesh else 0
	var hsh := hash(String(m.name))
	_phase = Vector3(float(hsh & 255), float((hsh >> 8) & 255), float((hsh >> 16) & 255)) * 0.731
	if _noise == null:
		_noise = FastNoiseLite.new()
		_noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
		_noise.seed = 4242
		_noise.frequency = 1.0
		_noise.fractal_type = FastNoiseLite.FRACTAL_NONE


func _fetch() -> void:
	if not arrays.is_empty() or orig_mesh == null:
		return
	for s in orig_mesh.get_surface_count():
		var a := orig_mesh.surface_get_arrays(s)
		arrays.append(a)
		orig_pos.append((a[Mesh.ARRAY_VERTEX] as PackedVector3Array).duplicate())
		orig_nrm.append((a[Mesh.ARRAY_NORMAL] as PackedVector3Array).duplicate() if a[Mesh.ARRAY_NORMAL] != null else PackedVector3Array())
		mats.append(orig_mesh.surface_get_material(s))


## Read the arrays now and build the grid on a worker thread (the hero does this at load).
func prepare_async() -> void:
	_fetch()
	if _grids.has(_key) or _task >= 0 or arrays.is_empty():
		return
	var pos := orig_pos.duplicate()
	_task = WorkerThreadPool.add_task(_build_grid.bind(pos), false, "dent grid")


func _build_grid(pos: Array) -> void:
	var out := []
	for s in pos.size():
		var verts: PackedVector3Array = pos[s]
		var g := {}
		for i in verts.size():
			var k := Vector3i((verts[i] / CELL).floor())
			var arr = g.get(k)
			if arr == null:
				g[k] = [i]                   # Array: a reference (a PackedInt32Array in a dict is copied on append)
			else:
				(arr as Array).append(i)
		out.append(g)
	_grids[_key] = out


func _grid() -> Array:
	if _task >= 0:
		WorkerThreadPool.wait_for_task_completion(_task)
		_task = -1
	if not _grids.has(_key):
		_build_grid(orig_pos)
	return _grids[_key]


## (push along dir, buckle across it) at p.
func _fg(p: Vector3, c: Vector3, radius: float, depth: float) -> Vector2:
	var r := p.distance_to(c) / radius
	if r >= 1.0:
		return Vector2.ZERO
	var w := smoothstep(1.0, 0.3, r)
	var cr := 1.0 - absf(_noise.get_noise_3dv(p * FREQ + _phase))
	cr *= cr
	return Vector2(depth * w * (0.6 + 0.8 * cr), depth * w * 0.32 * (1.3 * cr - 0.35))


## Dent around `pl` (car space point), pushing along `dl` (car space unit vector). Returns the number of
## vertices moved.
func dent(car_xf: Transform3D, pl: Vector3, dl: Vector3, radius: float, depth: float) -> int:
	if orig_mesh == null:
		return 0
	var to_mesh := mi.global_transform.affine_inverse() * car_xf
	var c := to_mesh * pl
	var d := (to_mesh.basis * dl).normalized()
	var up := to_mesh.basis * Vector3.UP
	var b := up - d * up.dot(d)
	if b.length() < 0.2:
		b = (to_mesh.basis * Vector3.FORWARD).slide(d)
	b = b.normalized()
	if not orig_mesh.get_aabb().grow(radius).has_point(c):
		return 0
	_fetch()
	var grid := _grid()
	var moved := 0
	var h := 0.02
	var reach := radius + MAX_OFFSET           # rest positions in the grid; a dented vertex may have moved
	var k0 := Vector3i(((c - Vector3.ONE * reach) / CELL).floor())
	var k1 := Vector3i(((c + Vector3.ONE * reach) / CELL).floor())
	for s in arrays.size():
		var a: Array = arrays[s]
		var verts: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
		var norms: PackedVector3Array = a[Mesh.ARRAY_NORMAL] if a[Mesh.ARRAY_NORMAL] != null else PackedVector3Array()
		var p0: PackedVector3Array = orig_pos[s]
		var g: Dictionary = grid[s]
		var touched := false
		for x in range(k0.x, k1.x + 1):
			for y in range(k0.y, k1.y + 1):
				for z in range(k0.z, k1.z + 1):
					var cell = g.get(Vector3i(x, y, z))
					if cell == null:
						continue
					for i in (cell as Array):
						# the grid holds rest positions; a dented vertex may have moved up to MAX_OFFSET
						var p := verts[i]
						var fg := _fg(p, c, radius, depth)
						if fg.x <= 0.0:
							continue
						var step := d * fg.x + b * fg.y + d * (fg.x * 0.04 * _noise.get_noise_3dv(p * 23.0 + _phase))
						if step.length() > depth * 1.4:
							step = step.normalized() * depth * 1.4
						var np := p + step
						var off := np - p0[i]
						if off.length() > MAX_OFFSET:
							np = p0[i] + off.normalized() * MAX_OFFSET
						verts[i] = np
						if not norms.is_empty():
							var gx := (_fg(p + Vector3(h, 0, 0), c, radius, depth) - fg) / h
							var gy := (_fg(p + Vector3(0, h, 0), c, radius, depth) - fg) / h
							var gz := (_fg(p + Vector3(0, 0, h), c, radius, depth) - fg) / h
							var n := norms[i]
							var nn := n - Vector3(gx.x, gy.x, gz.x) * d.dot(n) * 0.5 - Vector3(gx.y, gy.y, gz.y) * b.dot(n) * 0.5
							if nn.length_squared() > 1e-8:
								norms[i] = nn.normalized()
						moved += 1
						touched = true
		if touched:
			a[Mesh.ARRAY_VERTEX] = verts
			if not norms.is_empty():
				a[Mesh.ARRAY_NORMAL] = norms
	if moved > 0:
		_upload()
		dents += 1
	return moved


func _upload() -> void:
	if mesh == null:
		mesh = ArrayMesh.new()
		mesh.resource_name = orig_mesh.resource_name + "_dented"
	mesh.clear_surfaces()
	for s in arrays.size():
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays[s])
		mesh.surface_set_material(s, mats[s])
	if mi.mesh != mesh:
		mi.mesh = mesh


## Back to the undamaged shared mesh (keeps the arrays for the next crash).
func restore() -> void:
	if mesh == null:
		return
	for s in arrays.size():
		arrays[s][Mesh.ARRAY_VERTEX] = (orig_pos[s] as PackedVector3Array).duplicate()
		if not (orig_nrm[s] as PackedVector3Array).is_empty():
			arrays[s][Mesh.ARRAY_NORMAL] = (orig_nrm[s] as PackedVector3Array).duplicate()
	mi.mesh = orig_mesh
	mesh = null
	dents = 0


## Largest vertex offset from rest (tests).
func max_offset() -> float:
	var m := 0.0
	for s in arrays.size():
		var v: PackedVector3Array = arrays[s][Mesh.ARRAY_VERTEX]
		var p0: PackedVector3Array = orig_pos[s]
		for i in range(0, v.size(), 3):
			m = maxf(m, v[i].distance_to(p0[i]))
	return m
