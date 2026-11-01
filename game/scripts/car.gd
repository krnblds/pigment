extends VehicleBody3D
## Hero car built from the car contract (car.glb + car.json, see docs/agents/car/NOTES.md):
##   glTF Y-up, the car faces +Z (+X is its left), origin on the ground under the body centre;
##   nodes Body, Wheel_FL/FR/RL/RR (origins at the hubs), Caliper_XX (steer, don't spin),
##   Collider (convex hull), empties Headlight_L/R, Taillight_L/R (local -Z = beam direction).
##   car.json: wheel_radius, track, wheelbase, mass_kg, center_of_mass, suspension_suggestion.
## Arcade-ish but grounded: RWD, speed-sensitive steering, downforce, handbrake drift,
## anti-roll via a lowered centre of mass and low roll influence.

signal impact(strength: float)

@export var engine_power := 5200.0       ## engine force at low speed (VehicleBody3D.engine_force)
@export var top_speed := 52.0            ## m/s (~187 km/h)
@export var reverse_power := 3000.0
@export var brake_force := 60.0
@export var handbrake_force := 90.0
@export var max_steer := 0.55            ## rad at standstill
@export var high_speed_steer := 0.12     ## rad at top speed
@export var steer_speed := 3.2           ## rad/s
@export var downforce := 2.6             ## N per (m/s)^2
@export var grip := 3.4                  ## wheel friction slip (car.json suggestion x 1.15 when present)
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
var brake_materials: Array[BaseMaterial3D] = []
var calipers := []                       ## [caliper holder, its wheel]
var bar_lights: Array[OmniLight3D] = []
var lightbar_on := false
var braking := false
var reversing := false
var _steer := 0.0
var _flip_time := 0.0
var _last_vel := Vector3.ZERO
var _bar_t := 0.0


func setup(glb_path: String, json_path: String) -> void:
	if FileAccess.file_exists(json_path):
		spec = JSON.parse_string(FileAccess.get_file_as_string(json_path))
	mass = float(spec.get("mass_kg", spec.get("mass", 1350.0)))
	var radius := float(spec.get("wheel_radius", 0.34))
	var sus: Dictionary = spec.get("suspension_suggestion", {})
	if sus.has("friction_slip"):
		grip = float(sus.friction_slip) * 1.15          # a touch more grip than the sim value: arcade
	var model: Node3D = load(glb_path).instantiate()
	var collider := _find(model, "Collider") as MeshInstance3D
	# visuals: every mesh that is not part of a wheel, a caliper or the collider
	var visual := Node3D.new()
	visual.name = "Visual"
	add_child(visual)
	for n in _all_nodes(model):
		if n is MeshInstance3D and not _under(n, model, ["Wheel_", "Caliper_", "Collider"]):
			visual.add_child(_copy_mesh(n, _model_xf(n, model)))
	# collision: the convex hull
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
	# wheels (VehicleWheel3D at the hubs) and calipers (follow steering + suspension, no spin)
	var rest := float(sus.get("rest_length", 0.15))
	for wn: String in ["Wheel_FL", "Wheel_FR", "Wheel_RL", "Wheel_RR"]:
		var src := _find(model, wn) as Node3D
		var hub_xf := Transform3D()
		if src:
			hub_xf = _model_xf(src, model)
		else:
			var tr := float(spec.get("track", 1.6)) * 0.5
			var wb := float(spec.get("wheelbase", 2.7)) * 0.5
			hub_xf.origin = Vector3(tr if wn.ends_with("L") else -tr, radius, wb if wn[6] == "F" else -wb)
		var w := VehicleWheel3D.new()
		w.name = wn
		# the hard point sits one rest length above the hub so the modelled ride height is kept at rest
		w.position = hub_xf.origin + Vector3.UP * rest
		w.wheel_radius = radius
		w.wheel_rest_length = rest
		w.suspension_travel = float(sus.get("travel", 0.15)) + 0.06
		w.suspension_stiffness = float(sus.get("stiffness", 42.0)) * 1.3
		w.suspension_max_force = maxf(float(sus.get("max_force", 9000.0)), mass * 9.81 * 2.5)
		w.damping_compression = maxf(float(sus.get("damping_compression", 1.0)) * 2.5, 2.2)
		w.damping_relaxation = maxf(float(sus.get("damping_relaxation", 1.4)) * 2.2, 3.0)
		w.wheel_friction_slip = grip
		w.wheel_roll_influence = 0.04
		var front := wn[6] == "F"
		w.use_as_steering = front
		w.use_as_traction = not front
		add_child(w)
		if src:
			# meshes keep their rotation relative to the hub (right-hand wheels are turned 180 deg)
			var inv := hub_xf.affine_inverse()
			for n in _all_nodes(src):
				if n is MeshInstance3D:
					var mx := inv * _model_xf(n, model)
					w.add_child(_copy_mesh(n, Transform3D(hub_xf.basis, Vector3.ZERO) * mx))
		var cal := _find(model, "Caliper_" + wn.substr(6)) as Node3D
		if cal:
			var holder := Node3D.new()
			holder.name = String(cal.name)
			var cxf := _model_xf(cal, model)
			var cinv := cxf.affine_inverse()
			for n in _all_nodes(cal):
				if n is MeshInstance3D:
					holder.add_child(_copy_mesh(n, Transform3D(cxf.basis, Vector3.ZERO) * (cinv * _model_xf(n, model))))
			add_child(holder)
			calipers.append([holder, w])
		wheels.append(w)
		(front_wheels if front else rear_wheels).append(w)
	# lights: the empties' local -Z is the beam direction (same as SpotLight3D)
	for ln: String in ["Headlight_L", "Headlight_R"]:
		var e := _find(model, ln) as Node3D
		var xf := _model_xf(e, model) if e else Transform3D(Basis(), Vector3(0.7 if ln.ends_with("L") else -0.7, 0.65, 2.3))
		if (-xf.basis.z).normalized().dot(Vector3.BACK) < 0.5:      # beam must point along the car's +Z
			xf.basis = Basis(Vector3.UP, PI)
		var sl := SpotLight3D.new()
		sl.transform = Transform3D(xf.basis.orthonormalized() * Basis(Vector3.RIGHT, deg_to_rad(-4.0)), xf.origin + Vector3(0, 0, 0.05))
		sl.light_color = Color(1.0, 0.95, 0.86)
		sl.light_energy = 9.0
		sl.spot_range = 55.0
		sl.spot_angle = 24.0
		sl.spot_angle_attenuation = 0.7
		sl.light_volumetric_fog_energy = 0.6
		sl.shadow_enabled = ln.ends_with("L")
		add_child(sl)
		headlights.append(sl)
	for ln: String in ["Taillight_L", "Taillight_R"]:
		var e := _find(model, ln) as Node3D
		var ol := OmniLight3D.new()
		ol.position = (_model_xf(e, model).origin if e else Vector3(0.7 if ln.ends_with("L") else -0.7, 0.7, -2.3)) + Vector3(0, 0, -0.18)
		ol.light_color = Color(1.0, 0.05, 0.04)
		ol.omni_range = 4.0
		ol.light_energy = 0.6
		add_child(ol)
		tail_lights.append(ol)
	# roof light bar (Hoshikawa Security): red / blue flash, toggled with L
	var dims: Dictionary = spec.get("dimensions", {})
	var bar_y := float(dims.get("height_lightbar", 1.47)) + 0.08
	for i in 2:
		var bl := OmniLight3D.new()
		bl.position = Vector3(0.4 if i == 0 else -0.4, bar_y, -0.1)
		bl.light_color = Color(1.0, 0.05, 0.08) if i == 0 else Color(0.1, 0.3, 1.0)
		bl.omni_range = 14.0
		bl.light_energy = 0.0
		bl.light_volumetric_fog_energy = 2.0
		add_child(bl)
		bar_lights.append(bl)
	model.free()
	center_of_mass_mode = RigidBody3D.CENTER_OF_MASS_MODE_CUSTOM
	var com: Array = spec.get("center_of_mass", [0.0, 0.46, 0.05])
	# arcade: the centre of mass sits lower than the real one so hard cornering doesn't roll it
	center_of_mass = Vector3(float(com[0]), minf(float(com[1]), 0.48) - 0.24, float(com[2]))
	angular_damp = 0.6
	linear_damp = 0.02
	contact_monitor = true
	max_contacts_reported = 4
	continuous_cd = true


func _under(n: Node, model: Node, prefixes: Array) -> bool:
	var cur: Node = n
	while cur and cur != model:
		for p: String in prefixes:
			if String(cur.name).begins_with(p):
				return true
		cur = cur.get_parent()
	return false


## Copy of a MeshInstance3D.  Alpha-blended materials get a depth pre-pass so the opaque paint
## sorts correctly (the real body is one alpha-blended material); brake-light materials are tracked.
func _copy_mesh(mi: MeshInstance3D, xf: Transform3D) -> MeshInstance3D:
	var copy := MeshInstance3D.new()
	copy.name = mi.name
	copy.mesh = mi.mesh
	copy.transform = xf
	for s in mi.mesh.get_surface_count():
		var m := mi.get_active_material(s)
		if m is BaseMaterial3D:
			var bm := m as BaseMaterial3D
			var low := String(bm.resource_name).to_lower()
			var dm: BaseMaterial3D = null
			if bm.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
				dm = bm.duplicate()
				dm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS
			if low.contains("tail") or low.contains("brake"):
				if dm == null:
					dm = bm.duplicate()
				dm.emission_enabled = true
				brake_materials.append(dm)
			if dm:
				copy.set_surface_override_material(s, dm)
	return copy


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


func toggle_lightbar() -> void:
	lightbar_on = not lightbar_on
	if not lightbar_on:
		for l in bar_lights:
			l.light_energy = 0.0


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
	# steering: speed sensitive and smoothed
	var lim := lerpf(max_steer, high_speed_steer, sqrt(t))
	_steer = move_toward(_steer, input_steer * lim, steer_speed * delta)
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
	# downforce keeps it planted on crests
	apply_central_force(-global_basis.y * downforce * speed * speed)
	# lights
	var be := 3.2 if braking else (1.6 if reversing else 0.6)
	for l in tail_lights:
		l.light_energy = lerpf(l.light_energy, be, 0.3)
	for m in brake_materials:
		m.emission_energy_multiplier = 18.0 if braking else 5.0
	# calipers follow the wheel (suspension + steering) without spinning
	for c in calipers:
		var w: VehicleWheel3D = c[1]
		var h: Node3D = c[0]
		h.transform = Transform3D(Basis(Vector3.UP, steering if w.use_as_steering else 0.0), w.transform.origin)
	if lightbar_on:
		_bar_t += delta
		var phase := int(_bar_t * 6.0) % 4
		bar_lights[0].light_energy = 4.0 if phase < 2 else 0.0
		bar_lights[1].light_energy = 0.0 if phase < 2 else 4.0
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
