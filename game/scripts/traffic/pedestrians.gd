extends Node3D
## Pedestrian silhouettes on the sidewalks: capsule bodies, heads, swinging legs and a glowing
## LED collar, drawn with a handful of MultiMeshes (one draw call per part for all of them).
## Paths are the road centre lines offset to the sidewalk, sampled every 2 m onto the ground and cut
## where the ground jumps (stairs, walls) or near junctions; walkers turn round at path ends.
## Walkers far from the player are moved to a path spot 30-90 m away, out of view.

var mgr                          ## traffic manager
var paths: Array = []            ## [PackedVector3Array]
var peds: Array = []             ## [{path, i, t, dir, speed, phase, pos, fwd, col, h}]
var rng := RandomNumberGenerator.new()
var _mm := {}                    ## part -> MultiMesh
var _relocate_t := 0.0

const PARTS := ["body", "head", "leg_l", "leg_r", "collar"]


func setup(m, n: int) -> void:
	mgr = m
	rng.seed = 99
	_build_paths()
	if paths.is_empty():
		return
	_build_meshes(n)
	var pp: Vector3 = mgr._player_pos()
	for i in n:
		var p := {"path": 0, "i": 0, "t": 0.0, "dir": 1, "speed": rng.randf_range(1.0, 1.6), "phase": rng.randf() * TAU,
			"pos": Vector3.ZERO, "fwd": Vector3.FORWARD, "h": rng.randf_range(0.92, 1.08),
			"col": Color.from_hsv(rng.randf(), 0.25, rng.randf_range(0.05, 0.16)),
			"glow": Color.from_hsv([0.52, 0.85, 0.95, 0.12][rng.randi() % 4], 0.9, 1.0)}
		_put_random(p, pp, 5.0, 90.0, false)
		peds.append(p)
	for i in n:
		_mm.collar.set_instance_color(i, peds[i].glow)
		_mm.body.set_instance_color(i, peds[i].col)
	print("traffic: %d pedestrians on %d sidewalk paths" % [n, paths.size()])


func count() -> int:
	return peds.size()


func add_obstacles(_list: Array) -> void:
	pass       # walkers stay on the sidewalks; cars never need to stop for them


func _build_paths() -> void:
	var space: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var ray := PhysicsRayQueryParameters3D.new()
	ray.collision_mask = 1
	ray.exclude = [mgr._hero_rid]
	var G = mgr.graph
	for rd in G.roads:
		if rd.parking.is_empty() and G.source != "town_layout":
			continue
		for sgn in [-1.0, 1.0]:
			var off: float = rd.half_width + (2.6 if G.source == "town_layout" else 2.0)
			var line: PackedVector3Array = G.offset_line(G.resample(rd.pts, 2.0), off * sgn)
			var cur := PackedVector3Array()
			for q in line:
				var ok := true
				for J in G.junctions:
					if Vector2(q.x - J.pos.x, q.z - J.pos.z).length() < J.radius + 2.0:
						ok = false
				var y := q.y
				if ok:
					ray.from = q + Vector3.UP * 2.5
					ray.to = q - Vector3.UP * 3.0
					var h := space.intersect_ray(ray)
					if h.is_empty():
						ok = false
					else:
						y = h.position.y
						if not cur.is_empty() and absf(y - cur[cur.size() - 1].y) > 0.35:
							ok = false
				if ok:
					cur.append(Vector3(q.x, y, q.z))
				else:
					if cur.size() > 6:
						paths.append(cur)
					cur = PackedVector3Array()
			if cur.size() > 6:
				paths.append(cur)


func _build_meshes(n: int) -> void:
	var dark := StandardMaterial3D.new()
	dark.vertex_color_use_as_albedo = true
	dark.roughness = 0.7
	var skin := StandardMaterial3D.new()
	skin.albedo_color = Color(0.25, 0.2, 0.18)
	skin.roughness = 0.6
	var glow := ShaderMaterial.new()
	var sh := Shader.new()
	sh.code = "shader_type spatial;\nrender_mode unshaded;\nvoid fragment() { ALBEDO = COLOR.rgb * 3.5; }\n"
	glow.shader = sh
	var shapes := {}
	var body := CapsuleMesh.new()
	body.radius = 0.2
	body.height = 0.85
	shapes.body = [body, dark]
	var head := SphereMesh.new()
	head.radius = 0.11
	head.height = 0.24
	head.radial_segments = 10
	head.rings = 5
	shapes.head = [head, skin]
	var leg := CapsuleMesh.new()
	leg.radius = 0.075
	leg.height = 0.85
	leg.radial_segments = 6
	leg.rings = 2
	shapes.leg_l = [leg, dark]
	shapes.leg_r = [leg, dark]
	var collar := TorusMesh.new()
	collar.inner_radius = 0.1
	collar.outer_radius = 0.135
	collar.rings = 12
	collar.ring_segments = 4
	shapes.collar = [collar, glow]
	for k in PARTS:
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.use_colors = k in ["body", "collar", "leg_l", "leg_r"]
		mm.mesh = shapes[k][0]
		mm.instance_count = n
		var mmi := MultiMeshInstance3D.new()
		mmi.multimesh = mm
		mmi.material_override = shapes[k][1]
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF if k == "collar" else GeometryInstance3D.SHADOW_CASTING_SETTING_ON
		mmi.name = "Peds_" + k
		add_child(mmi)
		_mm[k] = mm
	for i in n:
		_mm.leg_l.set_instance_color(i, Color(0.04, 0.04, 0.05))
		_mm.leg_r.set_instance_color(i, Color(0.04, 0.04, 0.05))


func _put_random(p: Dictionary, around: Vector3, rmin: float, rmax: float, hidden: bool) -> bool:
	for k in 25:
		var pidx := rng.randi() % paths.size()
		var path: PackedVector3Array = paths[pidx]
		var i := rng.randi() % (path.size() - 1)
		var d := path[i].distance_to(around)
		if d < rmin or d > rmax:
			continue
		if hidden and mgr._in_view(path[i], d):
			continue
		p.path = pidx
		p.i = i
		p.t = rng.randf()
		p.dir = 1 if rng.randf() < 0.5 else -1
		return true
	return false


func _physics_process(dt: float) -> void:
	if peds.is_empty():
		return
	var pp: Vector3 = mgr._player_pos()
	_relocate_t -= dt
	var relocate := _relocate_t <= 0.0
	if relocate:
		_relocate_t = 0.5
	for idx in peds.size():
		var p: Dictionary = peds[idx]
		var path: PackedVector3Array = paths[p.path]
		var a: Vector3 = path[p.i]
		var b: Vector3 = path[p.i + 1]
		var seg := maxf(a.distance_to(b), 0.01)
		p.t += p.dir * p.speed * dt / seg
		if p.t > 1.0:
			p.t -= 1.0
			p.i += 1
			if p.i >= path.size() - 1:
				p.i = path.size() - 2
				p.t = 1.0
				p.dir = -1
		elif p.t < 0.0:
			p.t += 1.0
			p.i -= 1
			if p.i < 0:
				p.i = 0
				p.t = 0.0
				p.dir = 1
		a = path[p.i]
		b = path[p.i + 1]
		var pos := a.lerp(b, p.t)
		var fwd: Vector3 = (b - a) * p.dir
		fwd.y = 0.0
		fwd = fwd.normalized() if fwd.length_squared() > 1e-6 else Vector3.FORWARD
		p.pos = pos
		p.fwd = fwd
		p.phase += dt * p.speed * 5.2
		if relocate and pos.distance_to(pp) > 110.0:
			_put_random(p, pp, 30.0, 90.0, true)
		_write(idx, p)


func _write(i: int, p: Dictionary) -> void:
	var z: Vector3 = p.fwd
	var x := Vector3.UP.cross(z).normalized()
	var h: float = p.h
	var bob := absf(sin(p.phase)) * 0.04
	var sway := sin(p.phase) * 0.05
	var base := Basis(x, Vector3.UP, z)
	var o: Vector3 = p.pos
	_mm.body.set_instance_transform(i, Transform3D(base * Basis(Vector3.BACK, sway) * Basis.from_scale(Vector3(1.0, h, 0.8)), o + Vector3.UP * (1.18 * h + bob)))
	_mm.head.set_instance_transform(i, Transform3D(base, o + Vector3.UP * (1.72 * h + bob)))
	_mm.collar.set_instance_transform(i, Transform3D(base, o + Vector3.UP * (1.58 * h + bob)))
	var sw := sin(p.phase) * 0.45
	for side in [-1.0, 1.0]:
		var hip: Vector3 = o + Vector3.UP * (0.86 * h + bob) + x * side * 0.1
		var rot := base * Basis(Vector3.RIGHT, sw * side)
		var leg := Transform3D(rot, hip) * Transform3D(Basis(), Vector3(0, -0.4 * h, 0))
		(_mm.leg_l if side < 0.0 else _mm.leg_r).set_instance_transform(i, leg)
