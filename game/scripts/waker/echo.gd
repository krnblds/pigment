extends Node3D
## Memory echo: translucent cyan replays of the memory a sleeper is living, around where they were found.
## Ghost figures are the same humanoid adapter (player_body.gd, look "ghost": additive fresnel scanline
## shader) walking / standing / reaching; ghost props are primitives in the same material. The echo
## fades in from 60 m and tells the Waker which memory has them (the archetype).
##
##   echo.build(archetype, anchor, dir)   then the manager calls echo.tick(dt, player_pos)

const PlayerBody := preload("res://scripts/player/player_body.gd")

var archetype := ""
var ghosts: Array = []                 ## {body, from, to, t, speed, mode}
var strength := 0.0
var hum: AudioStreamPlayer3D
var _mat: ShaderMaterial
var _props: Array[MeshInstance3D] = []


func build(kind: String, anchor: Vector3, dir: Vector3) -> void:
	archetype = kind
	var x := Vector3(dir.x, 0, dir.z).normalized()
	if x.length() < 0.1:
		x = Vector3.RIGHT
	var z := x.cross(Vector3.UP).normalized()
	global_transform = Transform3D(Basis(x, Vector3.UP, z), anchor)
	_mat = PlayerBody.ghost_material().duplicate()
	match kind:
		"parent":
			for i in 3:
				_box(Vector3(2.2, 0.08, 1.2), Vector3(-4 + i * 4, 2.3, 3.5))               # stall awnings
				_box(Vector3(0.06, 2.3, 0.06), Vector3(-5 + i * 4, 1.15, 3.0))
				_box(Vector3(1.8, 0.9, 0.9), Vector3(-4 + i * 4, 0.45, 3.6))                # counters
			for i in 8:
				_sphere(0.18, Vector3(-6 + i * 1.6, 3.0 + 0.2 * sin(i), 2.6))             # lanterns
			for i in 3:
				_ghost(Vector3(-5 + i * 3.5, 0, 1.5), Vector3(5 - i * 3.5, 0, 1.0), 1.2, "walk")
			_ghost(Vector3(0, 0, -0.5), Vector3(9, 0, -2.0), 2.6, "run", 0.62)              # the child, always leaving
		"soldier":
			for i in 6:
				_box(Vector3(1.1, 0.35, 0.55), Vector3(-3 + i * 1.1, 0.18, 2.5))           # sandbag rows
				_box(Vector3(1.1, 0.35, 0.55), Vector3(-2.5 + i * 1.1, 0.53, 2.5))
			_box(Vector3(5.0, 0.1, 0.1), Vector3(4.0, 1.0, -2.0))                            # checkpoint boom
			_box(Vector3(0.3, 1.2, 0.3), Vector3(1.5, 0.6, -2.0))
			_box(Vector3(0.4, 0.3, 0.25), Vector3(-2.0, 0.85, 2.5))                         # the dead radio
			_ghost(Vector3(-1.5, 0, 3.2), Vector3.INF, 0.0, "aim")
			_ghost(Vector3(2.0, 0, 3.2), Vector3.INF, 0.0, "aim")
			_ghost(Vector3(-6, 0, -1.0), Vector3(6, 0, -1.0), 1.4, "walk")
		"climber":
			for i in 5:
				_box(Vector3(0.05, 9.0, 0.05), Vector3(-2 + i * 1.5, 4.5, -4.0))             # old scaffold uprights
			for h in [2.0, 4.0, 6.0, 8.0]:
				_box(Vector3(6.5, 0.05, 0.05), Vector3(1.0, h, -4.0))
			_ghost(Vector3(1.0, 8.0, -4.0), Vector3.INF, 0.0, "idle")
		"courier":
			for i in 4:
				_box(Vector3(0.5, 0.35, 0.4), Vector3(-1.0 + (i % 2) * 0.55, 0.18 + (i / 2) * 0.36, 2.5))   # parcels
			_box(Vector3(1.8, 1.2, 4.0), Vector3(3.5, 0.9, 3.0))                                           # van outline
			_ghost(Vector3(-2.5, 0, 2.5), Vector3.INF, 0.0, "reach")
			_ghost(Vector3(0, 0, -2.0), Vector3(14, 0, -2.0), 6.0, "run")
		"swarm":
			_box(Vector3(18.0, 0.06, 0.25), Vector3(0, 0.03, 3.0))                           # platform edge
			_box(Vector3(16.0, 2.8, 2.8), Vector3(0, 1.6, 5.2))                              # the train
			for i in 4:
				_ghost(Vector3(-6 + i * 3.2, 0, 1.5), Vector3.INF, 0.0, "idle")
	set_strength(0.0)


func _prop(mesh: Mesh, pos: Vector3) -> void:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = _mat
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	mi.position = pos
	add_child(mi)
	_props.append(mi)


func _box(size: Vector3, pos: Vector3) -> void:
	var b := BoxMesh.new()
	b.size = size
	_prop(b, pos)


func _sphere(r: float, pos: Vector3) -> void:
	var s := SphereMesh.new()
	s.radius = r
	s.height = r * 2.0
	s.radial_segments = 10
	s.rings = 5
	_prop(s, pos)


func _ghost(from: Vector3, to: Vector3, speed: float, mode: String, scale_ := 1.0) -> void:
	var b := PlayerBody.new()
	b.look = "ghost"
	add_child(b)
	b.position = from
	b.scale = Vector3.ONE * scale_
	if to != Vector3.INF:
		var d := to - from
		b.rotation.y = atan2(d.x, d.z)
	ghosts.append({"body": b, "from": from, "to": to, "t": randf(), "speed": speed, "mode": mode})


func set_strength(s: float) -> void:
	strength = s
	visible = s > 0.01
	if _mat:
		_mat.set_shader_parameter("strength", s)
	for g in ghosts:
		for mi in g.body.mesh_instances:
			if mi.material_override != _mat:
				mi.material_override = _mat


func tick(dt: float, viewer: Vector3) -> void:
	var d := viewer.distance_to(global_position)
	var want := clampf((60.0 - d) / 25.0, 0.0, 1.0)
	set_strength(move_toward(strength, want, dt * 0.8))
	if not visible:
		return
	for g in ghosts:
		var b: Node3D = g.body
		match String(g.mode):
			"walk", "run":
				var len_: float = (g.to - g.from).length()
				g.t = fmod(float(g.t) + dt * float(g.speed) / maxf(len_, 0.1), 1.0)
				b.position = (g.from as Vector3).lerp(g.to, g.t)
				b.set_locomotion(float(g.speed), 0.0, 0.0)
			"aim":
				b.set_armed(true)
				b.set_aim(1.0, 0.0, 0.0)
				b.set_locomotion(0.0, 0.6, 0.0)
			"reach":
				b.set_locomotion(0.0, 0.0, 0.0)
				if randf() < dt * 0.25:
					b.play("interact")
			_:
				b.set_locomotion(0.0, 0.0, 0.0)
