extends Node
## Drives the courier sleeper's car (a car.gd instance) along the memory's route: the road centre lines
## (town.road_polylines()), keeping left, slowing for bends, at a courier's hurry. The car is "boxed in"
## when it has been held nearly still for a while with the Waker's car close by, or stalled by an EMP
## (combat.gd marks cars in the blast: meta emp_until), or wrecked by ramming (big impacts). Then
## `stopped` fires and the case puts the sleeper out on foot, dazed.
##
## Collision is streamed in around the car as it goes (town.ensure_collision) so it never drives off
## the edge of the streamed world.

signal stopped(reason: String)

var car: RigidBody3D
var main: Node3D
var lines: Array = []
var speed := 14.0
var active := false
var done := false
var held := 0.0
var rams := 0
var stats := {"distance": 0.0, "replaced": 0, "max_held": 0.0}
var _line := 0
var _idx := 0
var _dir := 1
var _stuck := 0.0
var _ensure_t := 0.0
var _last := Vector3.ZERO


func setup(m: Node3D, c: RigidBody3D) -> void:
	main = m
	car = c
	lines = m.town.road_polylines() if m.town and m.town.layout else []
	car.autopilot = true
	car.add_to_group("emp_car")
	car.impact.connect(_on_impact)
	_pick_line()
	_last = car.global_position


func _pick_line() -> void:
	var best := INF
	for li in lines.size():
		var pts: PackedVector3Array = lines[li]
		for i in pts.size():
			var d := pts[i].distance_squared_to(car.global_position)
			if d < best:
				best = d
				_line = li
				_idx = i
	if lines.is_empty():
		return
	var pts: PackedVector3Array = lines[_line]
	var a := pts[maxi(0, _idx - 1)]
	var b := pts[mini(pts.size() - 1, _idx + 1)]
	_dir = 1 if (b - a).dot(car.global_basis.z) >= 0.0 else -1


func _on_impact(strength: float) -> void:
	if active and strength > 250.0:
		var pc: Node3D = main.car
		if pc and pc != car and pc.global_position.distance_to(car.global_position) < 8.0:
			rams += 1


func _physics_process(dt: float) -> void:
	if not active or done or car == null or lines.is_empty():
		return
	_ensure_t -= dt
	if _ensure_t <= 0.0 and main.town and main.town.has_method("ensure_collision"):
		_ensure_t = 0.4
		main.town.ensure_collision(car.global_position + car.linear_velocity * 0.6, 30.0)
	stats.distance += car.global_position.distance_to(_last)
	_last = car.global_position
	var stalled := Time.get_ticks_msec() < int(car.get_meta("emp_until", 0))
	var v: float = car.forward_speed()
	var pc: Node3D = main.car
	var waker_close: bool = pc != null and pc != car and pc.global_position.distance_to(car.global_position) < 12.0
	if absf(v) < 1.5 and (waker_close or stalled):
		held += dt
	else:
		held = maxf(0.0, held - dt * 0.5)
	stats.max_held = maxf(stats.max_held, held)
	if held > 2.5 or rams >= 4 or (stalled and absf(v) < 0.8 and held > 0.6):
		_stop("boxed in" if not stalled else "stalled")
		return
	if stalled:
		car.input_throttle = 0.0
		car.input_brake = 0.6
		car.input_steer = 0.0
		return
	_steer(dt, v)
	# wedged on its own: back on the road a little further on
	_stuck = _stuck + dt if absf(v) < 0.6 and not waker_close else 0.0
	if _stuck > 4.0:
		_stuck = 0.0
		var pts: PackedVector3Array = lines[_line]
		var q := pts[clampi(_idx + _dir * 3, 0, pts.size() - 1)]
		var nq := pts[clampi(_idx + _dir * 4, 0, pts.size() - 1)]
		main.town.ensure_collision(q, 30.0)
		car.place(preload("res://scripts/town_loader.gd").car_transform(q, (nq - q) if nq != q else car.global_basis.z))
		stats.replaced += 1


func _stop(reason: String) -> void:
	done = true
	active = false
	car.input_throttle = 0.0
	car.input_brake = 0.0               # parked: handbrake only (a held brake at a stop selects reverse)
	car.input_handbrake = true
	stopped.emit(reason)


func _steer(_dt: float, v: float) -> void:
	var pts: PackedVector3Array = lines[_line]
	var p := car.global_position
	while _idx + _dir >= 0 and _idx + _dir < pts.size() and pts[_idx + _dir].distance_to(p) < pts[_idx].distance_to(p) + 1.0:
		_idx += _dir
	if _idx + _dir < 0 or _idx + _dir >= pts.size():
		_next_line()
		pts = lines[_line]
	var look := 7.0 + absf(v) * 0.6
	var j := _idx
	while j + _dir >= 0 and j + _dir < pts.size() and pts[j].distance_to(p) < look:
		j += _dir
	var tdir := (pts[j] - pts[clampi(j - _dir, 0, pts.size() - 1)]).normalized()
	var target := pts[j] + Vector3.UP.cross(tdir).normalized() * 2.0
	var to := target - p
	to.y = 0.0
	var ang := car.global_basis.z.signed_angle_to(to.normalized(), Vector3.UP)
	car.input_steer = clampf(ang * 2.2, -1.0, 1.0)
	var k := clampi(j + _dir * 8, 0, pts.size() - 1)
	var bend := absf(tdir.signed_angle_to((pts[k] - pts[j]).normalized(), Vector3.UP)) if k != j else 0.0
	var want := speed * (1.0 - clampf(absf(ang) * 1.2 + bend * 0.8, 0.0, 0.65))
	car.input_throttle = clampf((want - v) * 0.35, -1.0, 1.0)
	car.input_brake = 0.0
	car.input_handbrake = false


func _next_line() -> void:
	var pts: PackedVector3Array = lines[_line]
	var end := pts[clampi(_idx, 0, pts.size() - 1)]
	var cands := []
	for li in lines.size():
		if li == _line:
			continue
		var q: PackedVector3Array = lines[li]
		if q[0].distance_to(end) < 45.0:
			cands.append([li, 0, 1])
		if q[q.size() - 1].distance_to(end) < 45.0:
			cands.append([li, q.size() - 1, -1])
	if cands.is_empty():
		_dir = -_dir
		return
	var c: Array = cands[randi() % cands.size()]
	_line = c[0]
	_idx = c[1]
	_dir = c[2]
