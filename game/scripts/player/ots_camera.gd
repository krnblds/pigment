extends Camera3D
## Over-the-shoulder camera for the on-foot Waker: mouse yaw / pitch, shoulder offset (X swaps), a sphere
## cast from the head to the camera so walls pull it in, zoomed aim-down mode (RMB), recoil kicks, shake.
## Duck-types the chase camera's API used elsewhere (shake / snap / cycle / target), so main.cam can
## point at it while on foot (rain and lamp shadows follow the camera).

var target: Node3D                      ## the player (CharacterBody3D)
var manual := false                     ## tests / shots place the camera themselves
var yaw := 0.0                          ## world yaw of the view (rad)
var pitch := -0.12                      ## + = looking up
var shoulder := 1.0                     ## +1 right shoulder, -1 left
var aiming := false
var crouch := 0.0
var sensitivity := 0.0032
var aim_sensitivity := 0.0018
var pad_speed := 2.6

const DIST := 2.9
const DIST_AIM := 1.25
const SIDE := 0.55
const SIDE_AIM := 0.62
const HEIGHT := 1.62
const FOV := 72.0
const FOV_AIM := 48.0
const RADIUS := 0.22

var _side := SIDE
var _dist := DIST
var _shoulder_s := 1.0
var _shake := 0.0
var _shake_t := 0.0
var _kick := Vector2.ZERO               ## recoil (pitch, yaw) that recovers
var _blend := 0.0                       ## transition from another camera (0 = done)
var _blend_from := Transform3D()
var _blend_len := 0.5
var _frac := 1.0
var _shape := SphereShape3D.new()
var _q := PhysicsShapeQueryParameters3D.new()


func _ready() -> void:
	_shape.radius = RADIUS
	_q.shape = _shape
	_q.collision_mask = 1 | 2


func shake(amount: float) -> void:
	_shake = clampf(maxf(_shake, amount), 0.0, 1.0)


func snap() -> void:
	_blend = 0.0


func cycle() -> void:
	shoulder = -shoulder


func kick(pitch_rad: float, yaw_rad: float) -> void:
	_kick += Vector2(pitch_rad, yaw_rad)


## Start a smooth hand-over from another camera's transform.
func blend_from(xf: Transform3D, seconds := 0.5) -> void:
	_blend_from = xf
	_blend_len = seconds
	_blend = 1.0


func look(rel: Vector2) -> void:
	var s := aim_sensitivity if aiming else sensitivity
	yaw = wrapf(yaw - rel.x * s, -PI, PI)
	pitch = clampf(pitch - rel.y * s, -1.2, 1.1)


func forward_flat() -> Vector3:
	return Vector3(-sin(yaw), 0.0, -cos(yaw))


func _physics_process(_delta: float) -> void:
	if manual or target == null or not is_inside_tree():
		return
	var pivot := _pivot()
	var want := pivot + _offset(1.0)
	_q.exclude = [target.get_rid()]
	_q.transform = Transform3D(Basis(), pivot)
	_q.motion = want - pivot
	var r := get_world_3d().direct_space_state.cast_motion(_q)
	_frac = clampf(r[0], 0.05, 1.0) if r.size() > 0 else 1.0


func _pivot() -> Vector3:
	var p := target.get_global_transform_interpolated().origin if target.is_inside_tree() else target.global_position
	return p + Vector3.UP * (HEIGHT - 0.55 * crouch)


func _offset(frac: float) -> Vector3:
	var b := Basis.from_euler(Vector3(pitch + _kick.x, yaw + _kick.y, 0.0))
	return (b.z * _dist + b.x * _side * _shoulder_s) * frac


func _process(delta: float) -> void:
	_shake = maxf(0.0, _shake - delta * 2.5)
	_shake_t += delta
	h_offset = (sin(_shake_t * 47.0) + sin(_shake_t * 71.0) * 0.5) * _shake * 0.06
	v_offset = (sin(_shake_t * 59.0 + 1.3) + sin(_shake_t * 83.0) * 0.5) * _shake * 0.05
	_kick = _kick.lerp(Vector2.ZERO, 1.0 - exp(-delta * 9.0))
	if manual or target == null:
		return
	if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED or Input.get_connected_joypads().size() > 0:
		var stick := Vector2(Input.get_joy_axis(0, JOY_AXIS_RIGHT_X), Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y))
		if stick.length() > 0.15:
			yaw = wrapf(yaw - stick.x * pad_speed * delta * (0.55 if aiming else 1.0), -PI, PI)
			pitch = clampf(pitch - stick.y * pad_speed * 0.7 * delta, -1.2, 1.1)
	var k := 1.0 - exp(-delta * 12.0)
	_dist = lerpf(_dist, DIST_AIM if aiming else DIST, k)
	_side = lerpf(_side, SIDE_AIM if aiming else SIDE, k)
	_shoulder_s = lerpf(_shoulder_s, shoulder, 1.0 - exp(-delta * 8.0))
	fov = lerpf(fov, FOV_AIM if aiming else FOV, 1.0 - exp(-delta * 10.0))
	var pivot := _pivot()
	var b := Basis.from_euler(Vector3(pitch + _kick.x, yaw + _kick.y, 0.0))
	var xf := Transform3D(b, pivot + _offset(_frac))
	if _blend > 0.0:
		_blend = maxf(0.0, _blend - delta / _blend_len)
		var t := smoothstep(0.0, 1.0, 1.0 - _blend)
		xf = Transform3D(_blend_from.basis.slerp(xf.basis, t), _blend_from.origin.lerp(xf.origin, t))
		fov = lerpf(68.0, fov, t)
	global_transform = xf


## The point under the crosshair (ray from the camera through the screen centre, past the player).
func aim_point(max_dist := 300.0, exclude: Array = []) -> Dictionary:
	var from := global_position
	var dir := -global_basis.z
	# start the ray at the player's depth so nothing between the camera and the player is hit
	if target:
		from += dir * maxf(0.0, (target.global_position - from).dot(dir) - 0.2)
	var q := PhysicsRayQueryParameters3D.create(from, from + dir * max_dist, 1 | 2 | 16)
	q.exclude = exclude
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	if hit:
		return {"point": hit.position, "hit": true, "collider": hit.collider}
	return {"point": from + dir * max_dist, "hit": false, "collider": null}
