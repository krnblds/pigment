extends Camera3D
## Smooth chase camera: follows the car's heading (blended with its velocity), springs in
## when a wall is between it and the car, FOV widens with speed.  C cycles chase / far / hood.

var target: VehicleBody3D
var mode := 0
var manual := false                  ## automation drives the camera directly
const MODES := [
	{"dist": 6.2, "height": 2.1, "look": 1.1, "fov": 68.0},
	{"dist": 10.5, "height": 3.6, "look": 1.3, "fov": 62.0},
	{"dist": -0.4, "height": 1.15, "look": 1.0, "fov": 78.0},   # hood
]
var _dir := Vector3.BACK
var _pos := Vector3.ZERO
var _init := false
var _ray_frac := 1.0                 ## 0..1 of the boom that is free of obstacles (physics tick)


func cycle() -> void:
	mode = (mode + 1) % MODES.size()
	_init = false


func snap() -> void:
	_init = false


func _physics_process(_delta: float) -> void:
	if manual or target == null or mode == 2:
		return
	var m: Dictionary = MODES[mode]
	var from := target.global_position + Vector3.UP * 1.2
	var to := target.global_position - _dir * (m.dist + 0.5) + Vector3.UP * m.height
	var q := PhysicsRayQueryParameters3D.create(from, to)
	q.exclude = [target.get_rid()]
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	_ray_frac = 1.0
	if hit:
		_ray_frac = clampf(from.distance_to(hit.position) / from.distance_to(to) - 0.08, 0.15, 1.0)


func _process(delta: float) -> void:
	if manual or target == null:
		return
	var m: Dictionary = MODES[mode]
	var tx := target.get_global_transform_interpolated()
	var fwd := tx.basis.z
	fwd.y = 0.0
	fwd = fwd.normalized()
	var vel := target.linear_velocity
	vel.y = 0.0
	var speed := vel.length()
	var want := fwd
	if speed > 3.0 and vel.normalized().dot(fwd) > 0.0:
		want = fwd.lerp(vel.normalized(), 0.35).normalized()
	if not _init:
		_dir = want
	_dir = _dir.slerp(want, 1.0 - exp(-delta * 4.0)).normalized()
	var car := tx.origin
	if mode == 2:
		var hood := tx * Vector3(0, m.height, 0.4)
		global_position = hood
		look_at(hood + tx.basis.z * 10.0 + Vector3.DOWN * 0.3, Vector3.UP)
		fov = m.fov + speed * 0.25
		_init = true
		return
	var from := car + Vector3.UP * 1.2
	var desired := car - _dir * m.dist + Vector3.UP * m.height
	desired = from.lerp(desired, _ray_frac)     # spring in when a wall is in the way
	if not _init:
		_pos = desired
		_init = true
	_pos = _pos.lerp(desired, 1.0 - exp(-delta * 9.0))
	global_position = _pos
	look_at(car + Vector3.UP * m.look + _dir * 2.5, Vector3.UP)
	var tf: float = m.fov + clampf(speed / 50.0, 0.0, 1.0) * 20.0
	fov = lerpf(fov, tf, 1.0 - exp(-delta * 3.0))
