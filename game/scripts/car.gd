extends VehicleBody3D
## Hero car built from the car contract (car.glb + car.json):
##   glTF Y-up, car faces +Z, nodes Body, Wheel_FL/FR/RL/RR (hub centres), Collider (convex),
##   empties Headlight_L/R, Taillight_L/R; car.json: wheel_radius, track, wheelbase, mass.
## Arcade-ish but grounded: RWD, speed-sensitive steering, downforce, handbrake drift,
## anti-roll via low centre of mass and roll influence.

signal impact(strength: float)

@export var engine_power := 9000.0       ## N at the wheels at low speed (split over traction wheels)
@export var top_speed := 52.0            ## m/s (~187 km/h)
@export var reverse_power := 4500.0
@export var brake_force := 60.0
@export var handbrake_force := 90.0
@export var max_steer := 0.55            ## rad at standstill
@export var high_speed_steer := 0.12     ## rad at top speed
@export var steer_speed := 3.2           ## rad/s
@export var downforce := 2.6             ## N per (m/s)^2
@export var grip := 3.4                  ## wheel friction slip
@export var drift_grip := 1.6            ## rear friction slip with the handbrake

var input_throttle := 0.0                ## -1..1 (autopilot / tests can drive these)
var input_steer := 0.0
var input_handbrake := false
var autopilot := false

var spec := {}
var wheels: Array[VehicleWheel3D] = []
var front_wheels: Array[VehicleWheel3D] = []
var rear_wheels: Array[VehicleWheel3D] = []
var headlights: Array[SpotLight3D] = []
var tail_lights: Array[OmniLight3D] = []
var brake_materials: Array[StandardMaterial3D] = []
var braking := false
var reversing := false
var _steer := 0.0
var _flip_time := 0.0
var _last_vel := Vector3.ZERO


func setup(glb_path: String, json_path: String) -> void:
	if FileAccess.file_exists(json_path):
		spec = JSON.parse_string(FileAccess.get_file_as_string(json_path))
	mass = float(spec.get("mass", 1350.0))
	var radius := float(spec.get("wheel_radius", 0.34))
	var model: Node3D = load(glb_path).instantiate()
	var body := _find(model, "Body") as Node3D
	var collider := _find(model, "Collider") as MeshInstance3D
	# Body and anything that is not a wheel / collider / light empty is visual
	var visual := Node3D.new()
	visual.name = "Visual"
	add_child(visual)
	for n in _all_nodes(model):
		if n is MeshInstance3D and n != collider and not n.name.begins_with("Wheel_"):
			var mi := n as MeshInstance3D
			var copy := MeshInstance3D.new()
			copy.name = mi.name
			copy.mesh = mi.mesh
			copy.transform = _model_xf(mi, model)
			for s in mi.mesh.get_surface_count():
				var m := mi.get_active_material(s)
				if m is StandardMaterial3D:
					var low := String(m.resource_name).to_lower()
					if low.contains("tail") or low.contains("brake"):
						var dm := (m as StandardMaterial3D).duplicate() as StandardMaterial3D
						dm.emission_enabled = true
						copy.set_surface_override_material(s, dm)
						brake_materials.append(dm)
			visual.add_child(copy)
	if body == null:
		push_warning("car.glb has no Body node")
	# collision
	var cs := CollisionShape3D.new()
	if collider and collider.mesh:
		cs.shape = collider.mesh.create_convex_shape(true, false)
		cs.transform = _model_xf(collider, model)
	else:
		var b := BoxShape3D.new()
		b.size = Vector3(float(spec.get("width", 1.9)), 0.9, float(spec.get("length", 4.5)))
		cs.shape = b
		cs.position = Vector3(0, 0.7, 0)
	add_child(cs)
	# wheels
	var rest := 0.16
	for wn in ["Wheel_FL", "Wheel_FR", "Wheel_RL", "Wheel_RR"]:
		var src := _find(model, wn) as Node3D
		var hub := Vector3.ZERO
		var hub_basis := Basis()
		if src:
			var t := _model_xf(src, model)
			hub = t.origin
			hub_basis = t.basis
		else:
			var tr := float(spec.get("track", 1.6)) * 0.5
			var wb := float(spec.get("wheelbase", 2.7)) * 0.5
			hub = Vector3(tr if wn.ends_with("L") else -tr, radius, wb if wn[6] == "F" else -wb)
		var w := VehicleWheel3D.new()
		w.name = wn
		# the hard point sits one rest length above the hub so the modelled ride height is kept at rest
		w.position = hub + Vector3.UP * rest
		w.wheel_radius = radius
		w.wheel_rest_length = rest
		w.suspension_travel = 0.22
		w.suspension_stiffness = 55.0
		w.suspension_max_force = mass * 9.81 * 2.5
		w.damping_compression = 2.6
		w.damping_relaxation = 3.4
		w.wheel_friction_slip = grip
		w.wheel_roll_influence = 0.12
		var front := wn[6] == "F"
		w.use_as_steering = front
		w.use_as_traction = not front
		add_child(w)
		if src is MeshInstance3D:
			var wm := MeshInstance3D.new()
			wm.mesh = (src as MeshInstance3D).mesh
			wm.transform = Transform3D(hub_basis, Vector3.ZERO)
			w.add_child(wm)
		wheels.append(w)
		(front_wheels if front else rear_wheels).append(w)
	# lights
	for ln in ["Headlight_L", "Headlight_R"]:
		var e := _find(model, ln) as Node3D
		var sl := SpotLight3D.new()
		sl.position = _model_xf(e, model).origin if e else Vector3(0.7 if ln.ends_with("L") else -0.7, 0.65, 2.3)
		# SpotLight shines along its -Z: turn it to face the car's +Z, tipped 4 degrees down
		sl.basis = Basis(Vector3.UP, PI) * Basis(Vector3.RIGHT, deg_to_rad(-4.0))
		sl.light_color = Color(0.92, 0.95, 1.0)
		sl.light_energy = 9.0
		sl.spot_range = 55.0
		sl.spot_angle = 24.0
		sl.spot_angle_attenuation = 0.7
		sl.light_volumetric_fog_energy = 0.6
		sl.shadow_enabled = ln.ends_with("L")
		add_child(sl)
		headlights.append(sl)
	for ln in ["Taillight_L", "Taillight_R"]:
		var e := _find(model, ln) as Node3D
		var ol := OmniLight3D.new()
		ol.position = (_model_xf(e, model).origin if e else Vector3(0.7 if ln.ends_with("L") else -0.7, 0.7, -2.3)) + Vector3(0, 0, -0.15)
		ol.light_color = Color(1.0, 0.05, 0.04)
		ol.omni_range = 4.0
		ol.light_energy = 0.6
		add_child(ol)
		tail_lights.append(ol)
	model.free()
	center_of_mass_mode = RigidBody3D.CENTER_OF_MASS_MODE_CUSTOM
	center_of_mass = Vector3(0, 0.38, 0.05)
	angular_damp = 0.6
	linear_damp = 0.02
	contact_monitor = true
	max_contacts_reported = 4
	continuous_cd = true


func _model_xf(n: Node3D, model: Node3D) -> Transform3D:
	var t := Transform3D()
	var cur: Node = n
	while cur and cur != model:
		t = (cur as Node3D).transform * t
		cur = cur.get_parent()
	return t


func _find(root: Node, nm: String) -> Node:
	return root.find_child(nm, true, false)


func _all_nodes(n: Node) -> Array:
	var out := [n]
	for c in n.get_children():
		out.append_array(_all_nodes(c))
	return out


func forward_speed() -> float:
	return linear_velocity.dot(global_basis.z)


func _physics_process(delta: float) -> void:
	if not autopilot:
		input_throttle = Input.get_action_strength("accelerate") - Input.get_action_strength("brake")
		input_steer = Input.get_action_strength("steer_left") - Input.get_action_strength("steer_right")
		input_handbrake = Input.is_action_pressed("handbrake")
	var v := forward_speed()
	var speed := linear_velocity.length()
	var t := clampf(speed / top_speed, 0.0, 1.0)
	# engine / brake / reverse
	var ef := 0.0
	var br := 0.0
	braking = false
	reversing = false
	if input_throttle > 0.05:
		if v < -1.0:
			br = brake_force * input_throttle
			braking = true
		else:
			ef = engine_power * input_throttle * (1.0 - t * t)
	elif input_throttle < -0.05:
		if v > 1.0:
			br = brake_force * -input_throttle
			braking = true
		else:
			ef = -reverse_power * -input_throttle * (1.0 if v > -12.0 else 0.0)
			reversing = true
	else:
		br = 1.2   # engine braking / rolling resistance
	engine_force = ef
	# steering: speed sensitive, smoothed, with a little self-centring at speed
	var lim := lerpf(max_steer, high_speed_steer, sqrt(t))
	var target := input_steer * lim
	_steer = move_toward(_steer, target, steer_speed * delta)
	steering = _steer
	for w in front_wheels:
		w.brake = br * 0.6
	for w in rear_wheels:
		w.brake = br * 0.4
		w.wheel_friction_slip = grip
	if input_handbrake:
		for w in rear_wheels:
			w.brake = handbrake_force
			w.wheel_friction_slip = drift_grip
		braking = true
	# downforce keeps it planted on crests; extra yaw damping
	apply_central_force(-global_basis.y * downforce * speed * speed)
	# lights
	var be := 3.2 if braking else (1.6 if reversing else 0.6)
	for l in tail_lights:
		l.light_energy = lerpf(l.light_energy, be, 0.3)
	for m in brake_materials:
		m.emission_energy_multiplier = 18.0 if braking else 5.0
	# impacts (for the MERIDIAN ticker)
	var dv := (linear_velocity - _last_vel).length() / maxf(delta, 1e-4)
	if dv > 60.0 and get_contact_count() > 0:
		impact.emit(dv)
	_last_vel = linear_velocity
	# stuck upside down: auto reset
	if global_basis.y.y < 0.2 and speed < 3.0:
		_flip_time += delta
	else:
		_flip_time = 0.0


func needs_reset() -> bool:
	return _flip_time > 2.0


func place(xf: Transform3D) -> void:
	global_transform = xf
	linear_velocity = Vector3.ZERO
	angular_velocity = Vector3.ZERO
	_steer = 0.0
	_last_vel = Vector3.ZERO
	_flip_time = 0.0
	PhysicsServer3D.body_set_state(get_rid(), PhysicsServer3D.BODY_STATE_TRANSFORM, xf)
