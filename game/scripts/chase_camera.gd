extends Camera3D
## Smooth chase camera: follows the car's heading (blended with its velocity), springs in
## when a wall is between it and the car, FOV widens with speed.  C cycles chase / far / hood.
## Hold the right mouse button and drag to orbit round the car (look around from the hood cam);
## the wheel zooms.  Let go and the view eases back behind the car after a moment.

var target: RigidBody3D
var mode := 0
var manual := false                  ## automation drives the camera directly
const MODES := [
	{"dist": 6.2, "height": 2.1, "look": 1.1, "fov": 68.0},
	{"dist": 10.5, "height": 3.6, "look": 1.3, "fov": 62.0},
	{"dist": -0.4, "height": 1.3, "look": 1.0, "fov": 78.0},    # hood
]
var _dir := Vector3.BACK
var _pos := Vector3.ZERO
var _primed := false
var _ray_frac := 1.0                 ## 0..1 of the boom that is free of obstacles (physics tick)
var _shake := 0.0                    ## impact shake, decays (h / v offsets, so it never fights the follow)
var _shake_t := 0.0
var _yaw := 0.0                      ## right-drag orbit round the car (radians, 0 = behind)
var _pitch := 0.0                    ## right-drag tilt (radians, + = looking down from higher)
var _zoom := 1.0                     ## mouse wheel, scales the boom
var _orbiting := false
var _hold := 0.0                     ## seconds left before the orbit eases back behind the car
var _view_dir := Vector3.BACK        ## _dir turned by the orbit (also used by the wall ray)
const ORBIT_SENS := 0.006
const ORBIT_HOLD := 1.5


func shake(amount: float) -> void:
	_shake = clampf(maxf(_shake, amount), 0.0, 1.0)


func cycle() -> void:
	mode = (mode + 1) % MODES.size()
	_primed = false


func snap() -> void:
	_primed = false


func _unhandled_input(event: InputEvent) -> void:
	if manual or target == null or not current:
		return
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_RIGHT:
			_orbiting = mb.pressed
			_hold = ORBIT_HOLD
			get_viewport().set_input_as_handled()
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_UP:
			_zoom = clampf(_zoom * 0.9, 0.55, 2.2)
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_zoom = clampf(_zoom / 0.9, 0.55, 2.2)
	elif event is InputEventMouseMotion and _orbiting:
		var mm := event as InputEventMouseMotion
		_yaw = wrapf(_yaw - mm.relative.x * ORBIT_SENS, -PI, PI)
		_pitch = clampf(_pitch + mm.relative.y * ORBIT_SENS, -0.25, 1.25)
		_hold = ORBIT_HOLD
		get_viewport().set_input_as_handled()


func _physics_process(_delta: float) -> void:
	if manual or target == null or mode == 2:
		return
	var m: Dictionary = MODES[mode]
	var from := target.global_position + Vector3.UP * 1.2
	var to: Vector3 = target.global_position + _boom(m, _view_dir) + -_view_dir * 0.5
	var q := PhysicsRayQueryParameters3D.create(from, to)
	q.exclude = [target.get_rid()]
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	_ray_frac = 1.0
	if hit:
		_ray_frac = clampf(from.distance_to(hit.position) / from.distance_to(to) - 0.08, 0.15, 1.0)


func _process(delta: float) -> void:
	_shake = maxf(0.0, _shake - delta * 2.2)
	_shake_t += delta
	h_offset = (sin(_shake_t * 47.0) + sin(_shake_t * 71.0) * 0.5) * _shake * 0.09
	v_offset = (sin(_shake_t * 59.0 + 1.3) + sin(_shake_t * 83.0) * 0.5) * _shake * 0.07
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
	if not _primed:
		_dir = want
	_dir = _dir.lerp(want, 1.0 - exp(-delta * 4.0)).normalized()   # lerp: slerp errors on near-parallel vectors
	if not _orbiting:
		_hold -= delta
		if _hold <= 0.0:                 # ease back behind the car
			var k := 1.0 - exp(-delta * 2.5)
			_yaw = lerpf(_yaw, 0.0, k)
			_pitch = lerpf(_pitch, 0.0, k)
	_view_dir = _dir.rotated(Vector3.UP, _yaw)
	var car := tx.origin
	if mode == 2:
		var hood: Vector3 = tx * Vector3(0, float(m.height), 1.2)
		global_position = hood
		var look_dir := tx.basis.z.rotated(Vector3.UP, _yaw)
		look_at(hood + look_dir * 10.0 + Vector3.DOWN * (0.3 + _pitch * 6.0), Vector3.UP)
		fov = float(m.fov) + speed * 0.25
		_primed = true
		return
	var from := car + Vector3.UP * 1.2
	var desired: Vector3 = car + _boom(m, _view_dir)
	desired = from.lerp(desired, _ray_frac)     # spring in when a wall is in the way
	if not _primed:
		_pos = desired
		_primed = true
	_pos = _pos.lerp(desired, 1.0 - exp(-delta * 9.0))
	global_position = _pos
	# looking ahead of the car while chasing; at the car itself once orbited round
	var ahead := 2.5 * clampf(1.0 - absf(_yaw) / 0.6 - absf(_pitch) / 0.8, 0.0, 1.0)
	look_at(car + Vector3.UP * m.look + _view_dir * ahead, Vector3.UP)
	var tf: float = m.fov + clampf(speed / 50.0, 0.0, 1.0) * 20.0
	fov = lerpf(fov, tf, 1.0 - exp(-delta * 3.0))


## Camera offset from the car: behind `d` at the mode's distance and height, tilted by the orbit pitch.
func _boom(m: Dictionary, d: Vector3) -> Vector3:
	var dist := float(m.dist) * _zoom
	var h := float(m.height) * _zoom
	var r := Vector2(dist, h).rotated(_pitch)       # tilt the boom up round the car
	return -d * r.x + Vector3.UP * maxf(r.y, 0.4)
