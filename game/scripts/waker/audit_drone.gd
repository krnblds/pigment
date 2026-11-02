extends Node3D
## Hoshikawa audit drone: the light consequence of a low MERIDIAN score. Flies in, hangs over the Waker
## with a searchlight and keeps line of sight; 10 s of exposure inside 30 m files a flag (fine + score),
## losing it for 45 s (outrun it in the car, break line of sight under cover) closes the audit.

signal finished(flagged: bool)

var target: Node3D
var exposure := 0.0
var life := 45.0
var done := false
var light: SpotLight3D
var _blink := 0.0
var _beacon: OmniLight3D
var _ray := PhysicsRayQueryParameters3D.new()
var _speed := 16.0
var _rotors: Array[MeshInstance3D] = []


func _ready() -> void:
	name = "AuditDrone"
	var dark := StandardMaterial3D.new()
	dark.albedo_color = Color(0.05, 0.055, 0.065)
	dark.metallic = 0.7
	dark.roughness = 0.35
	var core := MeshInstance3D.new()
	var b := BoxMesh.new()
	b.size = Vector3(0.7, 0.18, 0.7)
	core.mesh = b
	core.material_override = dark
	add_child(core)
	for i in 4:
		var arm := MeshInstance3D.new()
		var am := BoxMesh.new()
		am.size = Vector3(0.9, 0.05, 0.08)
		arm.mesh = am
		arm.material_override = dark
		arm.rotation.y = PI * 0.25 + i * PI * 0.5
		add_child(arm)
		var r := MeshInstance3D.new()
		var cm := CylinderMesh.new()
		cm.top_radius = 0.28
		cm.bottom_radius = 0.28
		cm.height = 0.02
		r.mesh = cm
		var rm := StandardMaterial3D.new()
		rm.albedo_color = Color(0.3, 0.32, 0.35, 0.4)
		rm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		r.material_override = rm
		r.position = Vector3(cos(PI * 0.25 + i * PI * 0.5), 0.08, -sin(PI * 0.25 + i * PI * 0.5)) * 0.55
		r.position.y = 0.08
		add_child(r)
		_rotors.append(r)
	light = SpotLight3D.new()
	light.light_color = Color(0.85, 0.95, 1.0)
	light.light_energy = 6.0
	light.spot_range = 40.0
	light.spot_angle = 16.0
	light.shadow_enabled = false
	light.rotation.x = -PI * 0.5
	add_child(light)
	_beacon = OmniLight3D.new()
	_beacon.omni_range = 6.0
	_beacon.light_energy = 0.0
	add_child(_beacon)


func _physics_process(dt: float) -> void:
	if done or target == null:
		return
	life -= dt
	var tp := target.global_position
	var hover := tp + Vector3.UP * 9.0 + (global_position - tp).normalized().slide(Vector3.UP) * 5.0
	var to := hover - global_position
	global_position += to.normalized() * minf(to.length(), _speed * dt)
	light.look_at_from_position(global_position, tp + Vector3.UP, Vector3.FORWARD)
	for r in _rotors:
		r.rotate_y(dt * 40.0)
	_blink += dt
	_beacon.light_color = Color(1.0, 0.15, 0.2) if fmod(_blink, 0.6) < 0.3 else Color(0.2, 0.4, 1.0)
	_beacon.light_energy = 2.0
	var d := global_position.distance_to(tp)
	var sees := false
	if d < 30.0:
		_ray.from = global_position + Vector3.DOWN * 0.3
		_ray.to = tp + Vector3.UP * 1.0
		_ray.collision_mask = 1
		sees = get_world_3d().direct_space_state.intersect_ray(_ray).is_empty()
	if sees:
		exposure += dt
	if exposure >= 10.0:
		done = true
		finished.emit(true)
	elif life <= 0.0:
		done = true
		finished.emit(false)
