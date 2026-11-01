extends RigidBody3D
## Hero car: a RigidBody3D with its own vehicle model (replaces VehicleBody3D), built from the car
## contract (car.glb + car.json, see docs/agents/car/NOTES.md) and the physics data in
## data/vehicles/ (scripts/vehicle/vehicle_params.gd).  Tuning guide: docs/agents/physics/NOTES.md.
##
##   glTF Y-up, the car faces +Z (+X is its left), origin on the ground under the body centre;
##   nodes Body, Wheel_FL/FR/RL/RR (hubs), Caliper_XX, Collider (convex hull), Headlight_*, Taillight_*.
##
## Model (120 Hz physics tick, 6 drivetrain / tyre sub-steps per tick):
##   * wheels: a swept "wheel profile" probe per wheel -- 4 rays across the tyre's circle along its
##     direction of travel; the hub height that keeps the round tyre on the highest point is the
##     contact, so a 15 cm kerb lifts the wheel smoothly before the hub reaches it (rays straight down
##     at the hub drop the tyre into the kerb face).  Faces taller than `max_step` are walls: the body
##     collider handles those.
##   * per-wheel springs (rates from ride frequencies), digressive dampers, bump stops, anti-roll bars;
##     load transfer comes out of the suspension.
##   * tyres: magic-formula combined slip (normalised slip vector -> friction ellipse), load
##     sensitivity, slip ratio / slip angle from the contact patch velocity through relaxation lengths
##     (stable to a standstill: parks on hills), surface grip from the collider (asphalt, paving, kerb,
##     concrete, metal, grass; wet when it rains).
##   * drivetrain: engine torque curve, idle governor, rev limiter, engine braking, auto clutch,
##     5-speed box (automatic by default, M toggles manual), final drive, open / limited-slip diff.
##   * brakes with bias and ABS, handbrake on the rear wheels; traction control, a light stability
##     control, speed-sensitive steering with self-aligning.
##   * body: a convex collider raised above the wheel line (only the tyres touch kerbs), chamfered at
##     the overhangs; aero drag; rolling resistance.

signal impact(strength: float)
signal bump(strength: float)

const Params := preload("res://scripts/vehicle/vehicle_params.gd")
const VehicleFx := preload("res://scripts/vehicle/vehicle_fx.gd")

const SUBSTEPS := 4
const PROBE_ALL: Array[float] = [0.0, 0.88, 0.55, -0.6]
const PROBE_FWD: Array[float] = [0.0, 0.88, 0.55]
const G := 9.81

## Grip by surface: [dry mu, wet mu, rolling resistance]
const SURFACES := {
	"asphalt": [1.0, 0.72, 0.012], "concrete": [0.95, 0.68, 0.012], "paving": [0.86, 0.62, 0.014],
	"curb": [0.86, 0.6, 0.014], "metal": [0.6, 0.42, 0.012], "grass": [0.62, 0.46, 0.05],
	"other": [0.9, 0.65, 0.014],
}

var input_throttle := 0.0                ## 0..1 (a negative value brakes: the autopilot / old API)
var input_brake := 0.0                   ## 0..1
var input_steer := 0.0                   ## -1..1, + = left
var input_handbrake := false
var autopilot := false
var town: Node                           ## for surface lookup (layout categories); optional
var wet := 1.0                           ## 0 dry .. 1 wet (main: rain on = wet)
var steer_override := NAN                ## tests / autopilot: front steer angle (rad) to aim for

var abs_on := true
var tc_on := true
var esc_on := true
var steer_assist := true
var manual := false                      ## manual gearbox (E / Q shift)

var spec := {}
var P := {}                              ## vehicle physics parameters (vehicle_params.gd)
var wheels: Array = []                   ## Wheel
var front_wheels: Array = []
var rear_wheels: Array = []
var headlights: Array[SpotLight3D] = []
var tail_lights: Array[OmniLight3D] = []
var brake_materials: Array[BaseMaterial3D] = []
var calipers := []                       ## [caliper holder, its wheel]
var bar_lights: Array[OmniLight3D] = []
var lightbar_on := false
var braking := false
var reversing := false
var fx: Node3D

# drivetrain state
var gear := 1                            ## -1 R, 0 N, 1.. forward
var rpm := 850.0
var engine_w := 89.0                     ## rad/s
var clutch := 0.0                        ## 0..1 engagement
var throttle_out := 0.0                  ## after the assists (HUD, audio)
var engine_load := 0.0                   ## 0..1 (audio)
var tc_active := 0.0
var abs_active := 0.0
var esc_active := 0.0
var steer_angle := 0.0                   ## front axle steer angle (rad)
var speed_kmh := 0.0

var _steer_in := 0.0
var _thr := 0.0
var _brk := 0.0
var _tc := 1.0
var _shift_t := 0.0
var _shift_to := 1
var _since_shift := 1.0
var _rev_hold := 0.0
var _fwd_hold := 0.0
var _flip_time := 0.0
var _last_vel := Vector3.ZERO
var _bar_t := 0.0
var _since_place := 0.0
var _ray := PhysicsRayQueryParameters3D.new()
var _surf_cache := {}
var _drive: Array = []                   ## driven wheels [left, right]
var _ratios: Array = []
var _final := 4.0
var _electric := false
var _limiter_cut := false
var _snap_pending := false


## After a teleport (spawn, reset: those put the origin ~0.9 m up): set the car down on the ground
## under it instead of dropping it (the collision there is streamed in by now).
func _snap_to_ground() -> void:
	_snap_pending = false
	var xf := global_transform
	var q := PhysicsRayQueryParameters3D.create(xf.origin + Vector3.UP * 1.5, xf.origin + Vector3.DOWN * 3.0, 1, [get_rid()])
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	if hit and xf.origin.y - hit.position.y > 0.05 and hit.normal.y > 0.7:
		xf.origin.y = hit.position.y + 0.02
		global_transform = xf
		PhysicsServer3D.body_set_state(get_rid(), PhysicsServer3D.BODY_STATE_TRANSFORM, xf)
		reset_physics_interpolation()


class Wheel:
	var name := ""
	var front := false
	var left := false
	var driven := false
	var steers := false
	var rest := Vector3.ZERO             ## hub at the modelled ride height (car space)
	var r := 0.33
	var half_w := 0.1
	var k := 30000.0
	var c_bump := 1500.0
	var c_reb := 2500.0
	var bump := 0.1
	var droop := 0.12
	var static_load := 3000.0
	var roll_centre := 0.1
	# tyre
	var mu := 1.0
	var kp := 0.11
	var ap := 0.13
	var bx := 1.0
	var cx := 1.6
	var by := 1.0
	var cy := 1.4
	var lsens := 0.12
	var nref := 3000.0
	var lx := 0.22
	var ly := 0.42
	# nodes
	var pivot: Node3D
	var spin: Node3D
	# state
	var x := 0.0                         ## suspension position (+ = bump) from the probe
	var xs := 0.0                        ## clamped to the travel
	var xs_prev := 0.0
	var contact := false
	var cpoint := Vector3.ZERO
	var cnormal := Vector3.UP
	var push := Vector3.UP               ## direction of the suspension force (tilted on an edge)
	var load := 0.0
	var surface := "asphalt"
	var mu_surf := 1.0
	var rr := 0.012
	var collider_id := 0
	var omega := 0.0
	var kappa := 0.0
	var beta := 0.0
	var fx := 0.0
	var fy := 0.0
	var vx := 0.0
	var vy := 0.0
	var fwd := Vector3.FORWARD
	var lat := Vector3.LEFT
	var slip_vel := 0.0                  ## contact patch sliding speed (m/s): skids, smoke, squeal
	var slip_ratio := 0.0
	var slip_angle := 0.0
	var steer := 0.0
	var angle := 0.0
	var brake_t := 0.0                   ## brake torque this sub-step
	var brake_base := 0.0                ## pedal torque (ABS modulates it)
	var brake_extra := 0.0               ## handbrake + stability control (not modulated)
	var abs_live := false
	var abs_p := 1.0
	var t_ext := 0.0                     ## sub-step: torque on the wheel from the road + brakes
	var held := false                    ## the brake holds it still
	var ref_point := Vector3.ZERO        ## last ground contact (world): what counts as a kerb vs a wall
	var ref_valid := false
	var air_t := 0.0

	func is_in_contact() -> bool:
		return contact


func setup(glb_path: String, json_path: String, vehicle_id := "") -> void:
	if FileAccess.file_exists(json_path):
		spec = JSON.parse_string(FileAccess.get_file_as_string(json_path))
	if vehicle_id == "" and not spec.has("id") and glb_path.get_file().get_basename() == "car":
		vehicle_id = "tsubame"           # the legacy single-livery export of the Tsubame
	P = Params.build(spec, vehicle_id)
	mass = float(P.mass)
	var radius := float(P.wheel_radius)
	var model: Node3D = load(glb_path).instantiate()
	var collider := _find(model, "Collider") as MeshInstance3D
	var visual := Node3D.new()
	visual.name = "Visual"
	add_child(visual)
	for n in _all_nodes(model):
		if n is MeshInstance3D and not _under(n, model, ["Wheel_", "Caliper_", "Collider"]):
			visual.add_child(_copy_mesh(n, _model_xf(n, model)))
	_build_collider(collider, model)
	# wheels: a pivot at the hub (steer + suspension), a spin node under it with the meshes
	var sus: Dictionary = P.suspension
	var drive := String(P.get("drive", "RWD"))
	for wn: String in ["Wheel_FL", "Wheel_FR", "Wheel_RL", "Wheel_RR"]:
		var src := _find(model, wn) as Node3D
		var wp: Array = P.wheels[wn]
		var hub_xf := Transform3D(Basis(), Vector3(float(wp[0]), float(wp[1]), float(wp[2])))
		if src:
			hub_xf = _model_xf(src, model)
		var w := Wheel.new()
		w.name = wn
		w.front = wn[6] == "F"
		w.left = wn.ends_with("L")
		w.steers = w.front
		w.driven = (drive == "FWD" and w.front) or (drive != "FWD" and not w.front) or drive == "AWD"
		w.rest = hub_xf.origin
		w.r = radius
		w.half_w = float(P.wheel_width) * 0.5
		var ax := "front" if w.front else "rear"
		w.k = float(sus["k_" + ax])
		w.c_bump = float(sus["c_bump_" + ax])
		w.c_reb = float(sus["c_rebound_" + ax])
		w.bump = float(sus.bump)
		w.droop = float(sus["droop_" + ax])
		w.static_load = float(sus["static_" + ax])
		w.roll_centre = float(sus["roll_centre_" + ax])
		var ty: Dictionary = P.tyres[ax]
		w.mu = float(ty.mu)
		w.kp = float(ty.peak_slip_ratio)
		w.ap = float(ty.peak_slip_angle)
		w.cx = float(ty.shape_long)
		w.cy = float(ty.shape_lat)
		w.bx = tan(PI / (2.0 * w.cx))        # puts the magic-formula peak at a normalised slip of 1
		w.by = tan(PI / (2.0 * w.cy))
		w.lsens = float(ty.load_sensitivity)
		w.nref = float(ty.load_ref)
		w.lx = float(ty.relax_long)
		w.ly = float(ty.relax_lat)
		w.pivot = Node3D.new()
		w.pivot.name = wn
		w.pivot.position = w.rest
		add_child(w.pivot)
		w.spin = Node3D.new()
		w.spin.name = "Spin"
		w.pivot.add_child(w.spin)
		if src:
			# meshes keep their rotation relative to the hub (right-hand wheels are turned 180 deg)
			var inv := hub_xf.affine_inverse()
			for n in _all_nodes(src):
				if n is MeshInstance3D:
					var mx := inv * _model_xf(n, model)
					w.spin.add_child(_copy_mesh(n, Transform3D(hub_xf.basis, Vector3.ZERO) * mx))
		var cal := _find(model, "Caliper_" + wn.substr(6)) as Node3D
		if cal:
			var holder := Node3D.new()
			holder.name = String(cal.name)
			var cxf := _model_xf(cal, model)
			var cinv := cxf.affine_inverse()
			for n in _all_nodes(cal):
				if n is MeshInstance3D:
					holder.add_child(_copy_mesh(n, Transform3D(cxf.basis, Vector3.ZERO) * (cinv * _model_xf(n, model))))
			holder.position = w.rest
			add_child(holder)
			calipers.append([holder, w])
		wheels.append(w)
		(front_wheels if w.front else rear_wheels).append(w)
	_drive = (front_wheels if drive == "FWD" else rear_wheels).duplicate()
	if not _drive[0].left:
		_drive.reverse()
	for w in wheels:
		w.driven = w in _drive
	_setup_lights(model)
	model.free()
	# mass properties: the centre of mass and inertia from car.json (no arcade lowering)
	center_of_mass_mode = RigidBody3D.CENTER_OF_MASS_MODE_CUSTOM
	var com: Array = P.center_of_mass
	center_of_mass = Vector3(float(com[0]), float(com[1]), float(com[2]))
	var ine: Array = P.inertia
	inertia = Vector3(float(ine[0]), float(ine[1]), float(ine[2]))
	angular_damp = 0.0
	linear_damp = 0.0
	angular_damp_mode = RigidBody3D.DAMP_MODE_REPLACE
	linear_damp_mode = RigidBody3D.DAMP_MODE_REPLACE
	can_sleep = false
	contact_monitor = true
	max_contacts_reported = 4
	continuous_cd = true
	var pm := PhysicsMaterial.new()
	pm.friction = float(P.body.friction)
	pm.bounce = float(P.body.bounce)
	physics_material_override = pm
	# drivetrain
	var gb: Dictionary = P.gearbox
	_ratios = gb.ratios
	_final = float(gb.final_drive)
	_electric = bool(gb.get("electric", false))
	var assists: Dictionary = P.assists
	abs_on = bool(assists.get("abs", true)) and bool(P.brakes.get("abs", true))
	tc_on = bool(assists.get("tc", true))
	esc_on = bool(assists.get("esc", true))
	steer_assist = bool(assists.get("steer_assist", true))
	engine_w = float(P.engine.idle_rpm) * TAU / 60.0
	_ray.collision_mask = 1
	_ray.hit_back_faces = false
	_ray.exclude = [get_rid()]
	fx = VehicleFx.new()
	fx.name = "Fx"
	fx.car = self
	add_child(fx)


## The convex hull from the glb, with its underside lifted to `clearance` (and chamfered up towards
## the bumpers) so the body sits above the wheel line: only the tyres meet kerbs.  The original hull
## reaches down to 9 cm, under a 15 cm kerb: the car beached itself on the kerb top with a wheel
## hanging (the old "stuck on curbs").
func _build_collider(collider: MeshInstance3D, model: Node3D) -> void:
	var body: Dictionary = P.body
	var clear := float(body.clearance)
	var approach := float(body.approach)
	var zf := float(P.wheels.Wheel_FL[2])
	var zr := float(P.wheels.Wheel_RL[2])
	var r := float(P.wheel_radius)
	var pts := PackedVector3Array()
	if collider and collider.mesh:
		var xf := _model_xf(collider, model)
		for s in collider.mesh.get_surface_count():
			for v in collider.mesh.surface_get_arrays(s)[Mesh.ARRAY_VERTEX]:
				pts.append(xf * v)
	else:
		var d: Dictionary = P.dimensions
		var hl := float(d.length) * 0.5
		var hw := float(d.width) * 0.5
		var h := float(d.height)
		for sx in [-1.0, 1.0]:
			for sz in [-1.0, 1.0]:
				pts.append(Vector3(sx * hw, 0.0, sz * hl))
				pts.append(Vector3(sx * hw * 0.85, h, sz * (hl - 0.9)))
				pts.append(Vector3(sx * hw, h * 0.6, sz * hl))
	var out := PackedVector3Array()
	for q in pts:
		# overhang beyond the axle + 0.6 r: the floor rises at the approach / departure angle
		var over := maxf(0.0, maxf(q.z - (zf + r * 0.6), (zr - r * 0.6) - q.z))
		var floor_y := clear + over * tan(approach)
		out.append(Vector3(q.x, maxf(q.y, floor_y), q.z))
	var shape := ConvexPolygonShape3D.new()
	shape.points = out
	var cs := CollisionShape3D.new()
	cs.name = "Body"
	cs.shape = shape
	add_child(cs)


func _setup_lights(model: Node3D) -> void:
	# headlights: the empties' local -Z is the beam direction (same as SpotLight3D)
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


# ------------------------------------------------------------------ input
func _unhandled_input(event: InputEvent) -> void:
	if autopilot:
		return
	if event.is_action_pressed("shift_up"):
		shift(1)
	elif event.is_action_pressed("shift_down"):
		shift(-1)
	elif event.is_action_pressed("toggle_manual"):
		manual = not manual
		if not manual and gear == 0:
			gear = 1
	elif event.is_action_pressed("toggle_abs"):
		abs_on = not abs_on
	elif event.is_action_pressed("toggle_tc"):
		tc_on = not tc_on
	elif event.is_action_pressed("toggle_esc"):
		esc_on = not esc_on
	elif event.is_action_pressed("toggle_steer_assist"):
		steer_assist = not steer_assist


## Manual shift (+1 up / -1 down): 1..n, N (0), R (-1, only when nearly stopped).
func shift(d: int) -> void:
	if not manual:
		manual = true
	var to := gear + d
	if to < -1 or to > _ratios.size():
		return
	if to == -1 and absf(forward_speed()) > 1.5:
		return
	if gear == -1 and to == 0 and absf(forward_speed()) > 1.5:
		return
	_begin_shift(to)


func _begin_shift(to: int) -> void:
	_shift_to = to
	_shift_t = float(P.gearbox.shift_time) if to != 0 and gear != 0 else 0.05
	_since_shift = 0.0
	gear = 0 if _shift_t > 0.0 else to


func gear_label() -> String:
	if _shift_t > 0.0:
		return "-"
	if gear == -1:
		return "R"
	if gear == 0:
		return "N"
	return str(gear)


func _read_inputs(dt: float) -> void:
	var raw_thr := 0.0
	var raw_brk := 0.0
	var raw_steer := 0.0
	var hb := false
	if autopilot:
		raw_thr = clampf(input_throttle, 0.0, 1.0)
		raw_brk = clampf(input_brake + maxf(-input_throttle, 0.0), 0.0, 1.0)
		raw_steer = clampf(input_steer, -1.0, 1.0)
		hb = input_handbrake
	else:
		raw_thr = Input.get_action_strength("accelerate")
		raw_brk = Input.get_action_strength("brake")
		raw_steer = Input.get_action_strength("steer_left") - Input.get_action_strength("steer_right")
		hb = Input.is_action_pressed("handbrake")
		input_throttle = raw_thr
		input_brake = raw_brk
		input_steer = raw_steer
		input_handbrake = hb
	# keyboard (all-or-nothing) inputs ramp; analogue triggers pass through with a light filter
	var thr_analog := raw_thr > 0.0 and raw_thr < 0.99
	var brk_analog := raw_brk > 0.0 and raw_brk < 0.99
	_thr = move_toward(_thr, raw_thr, (12.0 if thr_analog else (3.5 if raw_thr > _thr else 7.0)) * dt)
	_brk = move_toward(_brk, raw_brk, (12.0 if brk_analog else (4.5 if raw_brk > _brk else 9.0)) * dt)
	var st: Dictionary = P.steering
	var v := absf(forward_speed())
	var analog := raw_steer != 0.0 and absf(raw_steer) < 0.99
	var rate := 9.0 if analog else lerpf(float(st.rate), float(st.rate_high_speed), clampf(v / 30.0, 0.0, 1.0))
	if not analog and (raw_steer == 0.0 or signf(raw_steer) != signf(_steer_in)):
		rate = maxf(rate, float(st.return_rate))
	_steer_in = move_toward(_steer_in, raw_steer, rate * dt)
	input_handbrake = hb


# ------------------------------------------------------------------ physics tick
func _physics_process(delta: float) -> void:
	if freeze:
		return
	if _snap_pending:
		_snap_to_ground()
	var _t0 := Time.get_ticks_usec()
	_physics_tick(delta)
	prof_us = prof_us * 0.99 + float(Time.get_ticks_usec() - _t0) * 0.01


var prof_us := 0.0                       ## running average cost of a physics tick (µs), for benches


func _physics_tick(delta: float) -> void:
	_read_inputs(delta)
	var xf := global_transform
	var basis := xf.basis
	var up := basis.y
	var fwd_car := basis.z
	var com_w := xf * center_of_mass
	var lv := linear_velocity
	var av := angular_velocity
	var vfwd := lv.dot(fwd_car)
	_com_rel = com_w - xf.origin
	_acc_f = Vector3.ZERO
	_acc_t = Vector3.ZERO
	var speed := lv.length()
	speed_kmh = speed * 3.6
	# --- controls: which pedal does what (automatic: brake at a stop selects reverse)
	var thr := _thr
	var brk := _brk
	_auto_reverse(delta, vfwd)
	if gear == -1 and not manual:
		var t := thr
		thr = brk
		brk = t
	reversing = gear == -1
	# auto hold (automatic): stopped with no pedal pressed, the brakes hold the car (no creeping off)
	if not manual and thr < 0.02 and brk < 0.02 and absf(vfwd) < 0.4:
		brk = 0.35
	# --- steering
	_steering(delta, vfwd, lv, av, com_w, basis)
	# --- wheel probes + suspension
	var space := get_world_3d().direct_space_state
	for w: Wheel in wheels:
		_probe(w, xf, up, lv, av, com_w, space, delta)
	_suspension(delta, xf, up)
	# --- tyre frames and contact patch velocities
	for w: Wheel in wheels:
		if not w.contact:
			continue
		var n := w.cnormal
		var wf := basis * Vector3(sin(w.steer), 0.0, cos(w.steer))
		var f := (wf - n * wf.dot(n)).normalized()
		w.fwd = f
		w.lat = n.cross(f)
		var vc := lv + av.cross(w.cpoint - com_w)
		w.vx = vc.dot(f)
		w.vy = vc.dot(w.lat)
	# --- gearbox, clutch, assists, brakes
	_gearbox(delta, thr)
	var thr_eff := _assists(delta, thr, brk, vfwd, av, up, basis)
	throttle_out = thr_eff
	_brakes(delta, brk, vfwd)
	braking = brk > 0.05 or input_handbrake
	# --- drivetrain + tyres, sub-stepped
	_substeps(delta, thr_eff)
	# --- apply the tyre forces at the roll-centre height above the contact
	for w: Wheel in wheels:
		if not w.contact:
			continue
		var fvec := w.fwd * w.fx + w.lat * w.fy
		_force(fvec, w.cpoint + up * w.roll_centre - xf.origin, w, "tyre")
	apply_central_force(_acc_f)
	apply_torque(_acc_t)
	# --- aero drag (and optional downforce), at the centre of mass
	var aero: Dictionary = P.aero
	var q := 0.5 * float(aero.air_density) * speed * speed
	if speed > 0.1:
		apply_central_force(-lv / speed * q * float(aero.cd) * float(aero.area))
		var dfc := float(aero.downforce)
		if dfc > 0.0:
			apply_central_force(-up * q * dfc * float(aero.area))
	# --- visuals, lights, effects
	_visuals(delta)
	# impacts (MERIDIAN ticker, camera shake)
	var dv := (lv - _last_vel).length() / maxf(delta, 1e-4)
	_since_place += delta
	if dv > 120.0 and get_contact_count() > 0 and _since_place > 1.0:
		impact.emit(dv)
	_last_vel = lv
	# stuck upside down: auto reset
	if up.y < 0.2 and speed < 3.0:
		_flip_time += delta
	else:
		_flip_time = 0.0


func _auto_reverse(dt: float, vfwd: float) -> void:
	if manual:
		return
	var slow := absf(vfwd) < 0.8
	if gear >= 1 or gear == 0:
		if slow and _brk > 0.3 and _thr < 0.05:
			_rev_hold += dt
			if _rev_hold > 0.45:
				gear = -1
				_shift_t = 0.0
				_rev_hold = 0.0
		else:
			_rev_hold = 0.0
		if gear == 0 and _shift_t <= 0.0:
			gear = 1
	elif gear == -1:
		if slow and _thr > 0.3 and _brk < 0.05:
			_fwd_hold += dt
			if _fwd_hold > 0.15:
				gear = 1
				_fwd_hold = 0.0
		else:
			_fwd_hold = 0.0


func _steering(dt: float, vfwd: float, lv: Vector3, av: Vector3, com_w: Vector3, basis: Basis) -> void:
	var st: Dictionary = P.steering
	var lock := deg_to_rad(float(st.lock_deg))
	var v := absf(vfwd)
	var wb := float(P.wheels.Wheel_FL[2]) - float(P.wheels.Wheel_RL[2])
	var lim := lock
	if steer_assist:
		# speed-sensitive: full input asks for about the front tyres' peak, not past it
		var mu := 0.0
		for w: Wheel in front_wheels:
			mu += w.mu * w.mu_surf * 0.5
		var w0: Wheel = front_wheels[0]
		lim = clampf(atan(wb * 0.92 * mu * G / maxf(v * v, 0.01)) + w0.ap * 1.25, 0.075, lock)
	else:
		lim = lerpf(lock, lock * 0.45, clampf(v / 45.0, 0.0, 1.0))
	var target := _steer_in * lim
	if autopilot and not is_nan(steer_override):
		target = clampf(steer_override, -lock, lock)
	# self-aligning: with the wheel let go the front wheels turn towards where the rear axle is going
	# (caster): counter-steer when the tail slides, ~centred in a normal corner
	if steer_assist and absf(input_steer) < 0.05 and v > 3.0 and is_nan(steer_override):
		var zr := float(P.wheels.Wheel_RL[2])
		var vf := lv + av.cross(basis * Vector3(0.0, 0.0, zr) + global_position - com_w)
		var along := vf.dot(basis.z)
		var side := vf.dot(basis.x)
		var follow := atan2(side, absf(along)) * signf(along) if absf(along) > 0.5 else 0.0
		target = clampf(follow * float(st.self_align), -lim, lim)
	steer_angle = move_toward(steer_angle, target, 6.0 * dt)
	# Ackermann
	var t := absf(float(P.wheels.Wheel_FL[0]) - float(P.wheels.Wheel_FR[0]))
	for w: Wheel in front_wheels:
		if absf(steer_angle) < 1e-4:
			w.steer = 0.0
			continue
		var R := wb / tan(absf(steer_angle))
		var inner := (steer_angle > 0.0) == w.left
		w.steer = signf(steer_angle) * atan(wb / (R + (-t * 0.5 if inner else t * 0.5)))


## Wheel profile probe: rays across the tyre's circle along its direction of travel; the hub must
## sit high enough for the round tyre to clear every point -> contact, suspension position, normal.
func _probe(w: Wheel, xf: Transform3D, up: Vector3, lv: Vector3, av: Vector3, com_w: Vector3,
		space: PhysicsDirectSpaceState3D, dt: float) -> void:
	var sus: Dictionary = P.suspension
	var r := w.r
	var top := w.bump + r + 0.03
	var length := top + w.droop + r + 0.06
	var hub := xf * w.rest
	var wfwd := xf.basis * Vector3(sin(w.steer), 0.0, cos(w.steer))
	var vh := lv + av.cross(hub - com_w)
	vh -= up * vh.dot(up)
	var dir := wfwd
	var vlen := vh.length()
	if vlen > 0.4:
		dir = vh / vlen
	elif w.omega < -0.5:
		dir = -wfwd
	var max_step := float(sus.max_step)
	var best := -INF
	var best_hit := {}
	var best_off := 0.0
	var start := hub + up * top
	# the trailing sample (rolling off an edge backwards) only matters when slow
	var x0 := NAN
	var x88 := NAN
	for d: float in (PROBE_FWD if vlen > 2.5 else PROBE_ALL):
		# ground level under the centre and the leading sample: nothing in between to find
		if d == 0.55 and not is_nan(x0) and not is_nan(x88) and absf((x88 - x0)) < 0.006:
			continue
		var o := dir * (d * r)
		var a := o.dot(wfwd)                         # along the tyre's rolling direction
		var l := (o - wfwd * a).length()            # across its width
		var reff := sqrt(maxf(r * r - a * a, 0.0)) - maxf(0.0, l - w.half_w) * 0.9
		var from := start + o
		var end := start + o - up * length
		var hit := {}
		var xr := -INF
		# a rejected hit (a wall top, an overhang) hides the ground under it: look past it, twice at most
		for _try in 3:
			_ray.from = from
			_ray.to = end
			hit = space.intersect_ray(_ray)
			if hit.is_empty():
				break
			var hp: Vector3 = hit.position
			var nrm: Vector3 = hit.normal
			# taller than a kerb above the ground the wheel was last on (not above the hub: a body lifted
			# by a crash must not let the tyre climb onto a barrier), or a steep face: the body's job
			var rise := (hp - w.ref_point).dot(up) if w.ref_valid else 0.0
			if rise > max_step or nrm.dot(up) < 0.3 or (nrm.dot(up) < 0.7 and rise > 0.12):
				from = hp - up * 0.02
				hit = {}
				continue
			xr = top - (start + o - hp).dot(up) + reff
			break
		if hit.is_empty():
			continue
		# compare like with like: the centre and leading samples' ground heights (not the tyre heights)
		if d == 0.0:
			x0 = xr - reff
		elif d == 0.88:
			x88 = xr - reff
		if xr > best + 0.002:
			best = xr
			best_hit = hit
			best_off = d
	w.xs_prev = w.xs
	if best_hit.is_empty() or best < -w.droop:
		w.air_t += dt
		if w.air_t > 0.4:
			w.ref_valid = false            # long airborne: whatever it lands on is the new ground
		w.contact = false
		w.x = -w.droop
		w.xs = -w.droop
		w.load = 0.0
		w.kappa *= 0.9
		w.beta *= 0.9
		return
	w.contact = true
	w.air_t = 0.0
	w.ref_point = best_hit.position
	w.ref_valid = true
	w.x = best
	w.xs = clampf(best, -w.droop, w.bump)
	w.cpoint = best_hit.position
	w.cnormal = best_hit.normal
	w.push = up
	if best_off != 0.0:
		# on an edge: the force on the tyre points from the edge to the hub (resists climbing a bit)
		var hub_now := hub + up * w.x
		var gn := (hub_now - w.cpoint).normalized()
		w.push = up.lerp(gn, float(sus.edge_push)).normalized()
		w.cnormal = w.cnormal.lerp(up, 0.5).normalized()
	var col: Object = best_hit.collider
	var cid := col.get_instance_id() if col else 0
	if cid != w.collider_id:
		w.collider_id = cid
		w.surface = _surface_of(col)
	var sd: Array = SURFACES.get(w.surface, SURFACES.other)
	w.mu_surf = lerpf(float(sd[0]), float(sd[1]), wet)
	w.rr = float(sd[2])


func _surface_of(col: Object) -> String:
	if col == null:
		return "other"
	var id := col.get_instance_id()
	if _surf_cache.has(id):
		return _surf_cache[id]
	var s := "other"
	if col.has_meta("surface"):
		s = String(col.get_meta("surface"))
	elif col is Node:
		var nm := String((col as Node).name)
		if nm.begins_with("Col_") and town and town.get("layout") is Dictionary and town.layout.has("meshes"):
			var info = town.layout.meshes.get(nm.substr(4))
			if info != null:
				s = surface_for(String(info.get("cat", "")), info.get("surfaces", []))
		elif nm.begins_with("Shapes"):
			s = "concrete"
	_surf_cache[id] = s
	return s


## Collider category (+ its mesh's material names) -> surface kind.
static func surface_for(cat: String, mats: Array) -> String:
	if mats.size() == 1:
		var m := String(mats[0]).to_lower()
		for key in [["asphalt", "asphalt"], ["paving", "paving"], ["trim", "curb"], ["curb", "curb"],
				["concrete", "concrete"], ["metal", "metal"], ["terrain", "grass"], ["grass", "grass"]]:
			if m.contains(key[0]):
				return key[1]
	match cat:
		"road", "junction":
			return "asphalt"
		"terrain":
			return "grass"
		"wall", "stairs", "bridge", "building", "footing":
			return "concrete"
		"rail":
			return "metal"
	return "other"


func _suspension(dt: float, xf: Transform3D, up: Vector3) -> void:
	var sus: Dictionary = P.suspension
	var knee := float(sus.damper_knee)
	var blow := float(sus.damper_blowoff)
	var bs_rate := float(sus.bump_stop_rate)
	for pair in [[wheels[0], wheels[1], float(sus.arb_front)], [wheels[2], wheels[3], float(sus.arb_rear)]]:
		var a: Wheel = pair[0]
		var b: Wheel = pair[1]
		var arb := float(pair[2]) * (a.xs - b.xs)
		for w: Wheel in [a, b]:
			if not w.contact:
				continue
			var vs := (w.xs - w.xs_prev) / dt                       # + = compressing
			var c := w.c_bump if vs > 0.0 else w.c_reb
			var av := absf(vs)
			# digressive damper: linear to the knee, then the blow-off slope
			var fd := c * minf(av, knee) + c * blow * maxf(av - knee, 0.0)
			fd *= signf(vs)
			var fs := w.static_load + w.k * w.xs
			# bump stop: progressive over the last 2 cm of travel, then the tyre itself
			var over := w.x - (w.bump - 0.02)
			if over > 0.0:
				# rubber bump stop: progressive, and lossy (it damps, so a hard landing doesn't bounce)
				fs += w.k * bs_rate * over * (1.0 + over * 25.0)
				fd += w.c_bump * 4.0 * clampf(over / 0.02, 0.0, 1.0) * vs
				if vs > 1.2:
					bump.emit(minf(vs * 0.5, 3.0))
			var f := fs + fd + (arb if w == a else -arb)
			f = clampf(f, 0.0, w.static_load * 12.0)
			w.load = f * w.push.dot(up)
			_force(w.push * f, w.cpoint - xf.origin, w, "susp")


func _gearbox(dt: float, thr: float) -> void:
	_since_shift += dt
	if _shift_t > 0.0:
		_shift_t -= dt
		if _shift_t <= 0.0:
			gear = _shift_to
			_shift_t = 0.0
	var gb: Dictionary = P.gearbox
	var eng: Dictionary = P.engine
	var idle := float(eng.idle_rpm)
	var wc := _carrier_w()
	# automatic: shift on the wheel-derived engine speed in the current gear
	if not manual and gear >= 1 and _shift_t <= 0.0 and _since_shift > 0.6 and not _electric:
		var r_now := _ratio(gear) * _final
		var rpm_w := absf(wc * r_now) * 60.0 / TAU
		var up_r: Array = gb.auto_up_rpm
		var dn_r: Array = gb.auto_down_rpm
		var t := clampf(thr, 0.0, 1.0)
		var up_at := lerpf(float(up_r[0]), float(up_r[1]), pow(t, 0.8))
		var dn_at := lerpf(float(dn_r[0]), float(dn_r[1]), t)
		if _brk > 0.2:
			dn_at = maxf(dn_at, 1900.0)          # braking: step down for engine braking / the exit
		if rpm_w > up_at and gear < _ratios.size():
			_begin_shift(gear + 1)
		elif rpm_w < dn_at and gear > 1:
			var rpm_lower := absf(wc * _ratio(gear - 1) * _final) * 60.0 / TAU
			if rpm_lower < float(eng.redline_rpm) - 600.0:
				_begin_shift(gear - 1)
	# auto clutch: engaged when rolling, slips at a launch (bites as the engine revs), opens at a stop
	var target := 0.0
	if gear != 0 and _shift_t <= 0.0:
		if _electric:
			target = 1.0
		else:
			var rpm_drive := absf(wc * _ratio(gear) * _final) * 60.0 / TAU
			# launch: the clutch slips with a capacity ~ rpm^2, so the engine settles where its torque
			# matches (~3000 rpm flat out) -- smooth against any load; it locks once the slip is small
			var k := float(P.gearbox.get("launch_k", 24.0))
			var launch_t := clampf(k * (rpm / 1000.0) * (rpm / 1000.0) / float(P.gearbox.clutch_torque), 0.0, 1.0)
			if rpm_drive > idle + 200.0 and rpm_drive > rpm - 350.0:
				target = 1.0
			else:
				target = launch_t
				if rpm < idle + 80.0 and _thr < 0.05:
					target = 0.0
				if input_handbrake:
					target = 0.0
	# after a shift the clutch comes back in over ~0.25 s (no shock through the tyres)
	var rate_in := 4.0 if _since_shift < 0.5 else (2.5 if gear == 1 or gear == -1 else 8.0)
	clutch = move_toward(clutch, target, (rate_in if target > clutch else 20.0) * dt)


func _ratio(g: int) -> float:
	if g >= 1:
		return float(_ratios[mini(g, _ratios.size()) - 1])
	if g == -1:
		return -float(P.gearbox.reverse) if not _electric else -float(_ratios[0])
	return 0.0


func _carrier_w() -> float:
	var a: Wheel = _drive[0]
	var b: Wheel = _drive[1]
	return (a.omega + b.omega) * 0.5


var _curve_lut := PackedFloat32Array()   ## torque per 50 rpm


func _torque_curve(r: float) -> float:
	if _curve_lut.is_empty():
		for i in 241:
			_curve_lut.append(_torque_curve_raw(i * 50.0))
	var f := clampf(r / 50.0, 0.0, 239.999)
	var i := int(f)
	return lerpf(_curve_lut[i], _curve_lut[i + 1], f - i)


func _torque_curve_raw(r: float) -> float:
	var c: Array = P.engine.torque_curve
	if r <= float(c[0][0]):
		return float(c[0][1])
	for i in range(1, c.size()):
		if r <= float(c[i][0]):
			var a: Array = c[i - 1]
			var b: Array = c[i]
			return lerpf(float(a[1]), float(b[1]), (r - float(a[0])) / (float(b[0]) - float(a[0])))
	return float(c[c.size() - 1][1])


func _assists(dt: float, thr: float, brk: float, vfwd: float, av: Vector3, up: Vector3, basis: Basis) -> float:
	var eng: Dictionary = P.engine
	var t := thr
	# speed limiter (fuel cut)
	var lim := float(eng.get("speed_limiter_kmh", 0.0))
	if lim > 0.0 and gear >= 1:
		t *= clampf((lim / 3.6 - absf(vfwd)) / 0.4, 0.0, 1.0)
	for w: Wheel in wheels:
		w.brake_extra = 0.0
	# traction control: cut the throttle while a driven wheel spins past its peak slip; at low speed
	# it brakes the spinning wheel instead (works like a locking diff) and keeps some throttle, so a
	# car with one wheel light (half on a kerb, against a wall) still pulls away
	var spin := 0.0
	var slow := clampf(1.0 - absf(vfwd) / 8.0, 0.0, 1.0)
	for w: Wheel in _drive:
		if w.contact and gear != 0:
			var sr := (w.omega * w.r - w.vx) / maxf(absf(w.vx), 3.0) * signf(_ratio(gear))
			spin = maxf(spin, sr / w.kp)
			if tc_on and slow > 0.0 and sr / w.kp > 1.5:
				w.brake_extra += clampf((sr / w.kp - 1.5) * 250.0, 0.0, 900.0) * slow
	var floor_t := lerpf(0.08, 0.45, slow)
	if tc_on and spin > 1.35 and t > 0.05:
		_tc = maxf(floor_t, _tc - 5.0 * dt * (spin - 1.2))
	else:
		_tc = minf(1.0, _tc + 4.0 * dt)
	tc_active = 1.0 - _tc if tc_on else 0.0
	t *= _tc if tc_on else 1.0
	# stability control: brake the outer front wheel when the car yaws past the bicycle-model rate
	esc_active = 0.0
	if esc_on and not input_handbrake and absf(vfwd) > 6.0 and gear >= 1:
		var wb := float(P.wheels.Wheel_FL[2]) - float(P.wheels.Wheel_RL[2])
		var r_meas := av.dot(up)
		var vch := 24.0
		var r_des := vfwd * steer_angle / (wb * (1.0 + (vfwd / vch) * (vfwd / vch)))
		var mu := 0.0
		for w: Wheel in wheels:
			mu += w.mu * w.mu_surf * 0.25
		var r_max := mu * G / absf(vfwd)
		r_des = clampf(r_des, -r_max, r_max)
		var excess := 0.0
		if signf(r_meas) != signf(r_des) and absf(r_des) > 0.02:
			excess = absf(r_meas) + 0.0
		else:
			excess = absf(r_meas) - absf(r_des)
		excess -= 0.07
		if excess > 0.0:
			esc_active = clampf(excess * 4.0, 0.0, 1.0)
			# yaw left (+) -> brake the right front, and the other way round
			var outer: Wheel = front_wheels[1] if r_meas > 0.0 else front_wheels[0]
			outer.brake_extra += clampf(excess * 3000.0, 0.0, 1400.0)
			t *= clampf(1.0 - excess * 2.5, 0.25, 1.0)
	return t


func _brakes(dt: float, brk: float, vfwd: float) -> void:
	var br: Dictionary = P.brakes
	var tmax := float(br.max_torque)
	var bias := float(br.bias_front)
	abs_active = 0.0
	for w: Wheel in wheels:
		var share := bias * 0.5 if w.front else (1.0 - bias) * 0.5
		w.brake_base = brk * tmax * share
		# ABS works per sub-step (_substeps) on the wheel's slip; not with the handbrake on that wheel
		w.abs_live = abs_on and brk > 0.05 and absf(w.vx) > 1.5 and w.contact and not (input_handbrake and not w.front)
		if not w.abs_live:
			w.abs_p = 1.0
		elif w.abs_p < 0.97:
			abs_active = 1.0
		if input_handbrake and not w.front:
			w.brake_extra += float(br.handbrake_nm)


## Tyre forces + wheel spin + clutch / gearbox / differential, sub-stepped (the slip dynamics are
## stiff); the body sees the average tyre force over the tick.
func _substeps(dt: float, thr_eff: float) -> void:
	var h := dt / SUBSTEPS
	var eng: Dictionary = P.engine
	var gb: Dictionary = P.gearbox
	var tyres: Dictionary = P.tyres
	var iw := float(tyres.wheel_inertia)
	var ie := float(eng.inertia)
	var idle_w := float(eng.idle_rpm) * TAU / 60.0
	var lim_w := float(eng.limiter_rpm) * TAU / 60.0
	var fr0 := float(eng.friction_nm)
	var fr1 := float(eng.friction_per_krpm)
	var eff := float(eng.efficiency)
	var cap := clutch * float(gb.clutch_torque) * (2.5 if _electric else 1.0)
	var c_cl := float(gb.clutch_damping)
	var gr := _ratio(gear) * _final
	var diff: Dictionary = P.differential
	var lsd := String(diff.get("type", "open")) == "lsd"
	var pre_nm := float(diff.get("preload_nm", 0.0)) if lsd else 4.0
	var lock := float(diff.get("lock_ratio", 0.0)) if lsd else 0.0
	var a: Wheel = _drive[0]
	var b: Wheel = _drive[1]
	for w: Wheel in wheels:
		w.fx = 0.0
		w.fy = 0.0
		w.slip_vel = 0.0
	var thr_e := thr_eff
	var t_cl := 0.0
	for _i in SUBSTEPS:
		# engine torque: the curve x throttle, friction / pumping off throttle, idle governor, limiter
		var e_rpm := engine_w * 60.0 / TAU
		if not _electric:
			if e_rpm > float(eng.limiter_rpm):
				_limiter_cut = true
			elif e_rpm < float(eng.limiter_rpm) - 180.0:
				_limiter_cut = false
			var gov := clampf((float(eng.idle_rpm) + 60.0 - e_rpm) / 300.0, 0.0, 1.0) * 0.6
			thr_e = maxf(thr_eff, gov)
			if _shift_t > 0.0:
				# upshift: lift; downshift: blip towards the lower gear's revs
				var wc0 := _carrier_w()
				var want := absf(wc0 * _ratio(_shift_to) * _final)
				thr_e = 0.7 if (_shift_to < gear or gear == 0) and engine_w < want else 0.0
			if _limiter_cut:
				thr_e = 0.0
		var te := thr_e * _torque_curve(e_rpm) * eff - (1.0 - thr_e) * (fr0 + fr1 * e_rpm / 1000.0) * signf(engine_w)
		# tyre forces from the slip states, per wheel; wheel torques
		for w: Wheel in wheels:
			w.t_ext = 0.0
			if not w.contact:
				continue
			var vxa := absf(w.vx)
			var sv := w.omega * w.r - w.vx
			w.kappa = clampf((w.kappa + h * sv / w.lx) / (1.0 + h * vxa / w.lx), -1.5, 1.5)
			w.beta = clampf((w.beta + h * w.vy / w.ly) / (1.0 + h * vxa / w.ly), -1.5, 1.5)
			# load: impacts (kerbs, landings) spike it for a tick; the tyre saturates well before that
			var n := clampf(w.load, 0.0, w.nref * 3.5)
			var mu := w.mu * w.mu_surf * clampf(1.0 - w.lsens * (n / w.nref - 1.0), 0.6, 1.25)
			var sx := w.kappa / w.kp
			var sy := w.beta / w.ap
			var s := sqrt(sx * sx + sy * sy)
			var fx := 0.0
			var fy := 0.0
			if s > 1e-6:
				var fxm := mu * n * sin(w.cx * atan(w.bx * s))
				var fym := mu * n * sin(w.cy * atan(w.by * s))
				fx = fxm * sx / s
				fy = -fym * sy / s
			# low-speed damping of the slip springs (they have no |v| term to damp them near a stop):
			# sliding friction on the patch velocity, acting on both the body and the wheel
			var lo := clampf(1.0 - vxa / 3.0, 0.0, 1.0)
			var fdx := 0.0
			if lo > 0.0:
				fy -= lo * 3.2 * n * w.vy
				fdx = lo * (3.0 if w.held else 1.0) * n * sv
			var fmax := mu * n * 1.02
			var fl := sqrt((fx + fdx) * (fx + fdx) + fy * fy)
			var sc := fmax / fl if fl > fmax and fl > 1e-6 else 1.0
			w.fx += (fx + fdx) * sc / SUBSTEPS
			w.fy += fy * sc / SUBSTEPS
			w.slip_vel += sqrt(sv * sv + w.vy * w.vy) / SUBSTEPS
			# rolling resistance as a torque that can't reverse the wheel
			w.t_ext = -(fx + (0.0 if w.held else fdx)) * sc * w.r - signf(w.omega) * minf(w.rr * n * w.r, absf(w.omega) * iw / h)
		# brakes: Coulomb friction that holds a stopped wheel (the engine side adds its inertia).
		# ABS: a slip controller per wheel that holds the brake slip just under the tyre's peak
		for w: Wheel in wheels:
			w.held = false
			if w.abs_live:
				var vxa := maxf(absf(w.vx), 0.5)
				var sr := (w.omega * w.r - w.vx) / vxa * signf(w.vx)
				var e := (sr + w.kp * 0.85) / w.kp
				w.abs_p = clampf(w.abs_p + h * (40.0 if e < 0.0 else 12.0) * e, 0.05, 1.0)
			w.brake_t = w.brake_base * w.abs_p + w.brake_extra
			if w.brake_t > 0.0:
				var ieff := iw + (ie * gr * gr * 0.5 if (w.driven and clutch > 0.95) else 0.0)
				var wf := w.omega + h * w.t_ext / ieff
				if absf(wf) <= h * w.brake_t / ieff:
					# stops within this sub-step: the brake holds it (static friction)
					w.t_ext = -w.omega * ieff / h
					w.held = true
				else:
					w.t_ext -= signf(wf) * w.brake_t
		# undriven wheels
		for w: Wheel in wheels:
			if not w.driven:
				w.omega += h * w.t_ext / iw
		# driven axle: carrier (sum) mode with the engine through the clutch, implicit; diff mode
		var wc := (a.omega + b.omega) * 0.5
		var wd := (a.omega - b.omega) * 0.5
		var ic := 2.0 * iw
		var tc := a.t_ext + b.t_ext
		if gr != 0.0 and cap > 0.0:
			var s0 := engine_w - gr * wc
			var s1 := (s0 + h * (te / ie - gr * tc / ic)) / (1.0 + h * c_cl * (1.0 / ie + gr * gr / ic))
			t_cl = clampf(c_cl * s1, -cap, cap)
		else:
			t_cl = 0.0
		engine_w += h * (te - t_cl) / ie
		if not _electric:
			engine_w = maxf(engine_w, idle_w * 0.5)
		else:
			engine_w = maxf(engine_w, -lim_w)
		wc += h * (tc + gr * t_cl) / ic
		# limited slip: friction lock between the halves (preload + a share of the input torque)
		var td := a.t_ext - b.t_ext
		var id := 2.0 * iw
		var t_req := id * wd / h + td
		var lcap := pre_nm + lock * absf(gr * t_cl)
		var t_lock := clampf(t_req, -lcap, lcap)
		wd += h * (td - t_lock) / id
		a.omega = wc + wd
		b.omega = wc - wd
	rpm = engine_w * 60.0 / TAU
	engine_load = clampf(absf(t_cl) / maxf(float(eng.peak_torque), 1.0), 0.0, 1.0) if gr != 0.0 else thr_e * 0.3
	for w: Wheel in wheels:
		if w.contact:
			w.slip_ratio = w.kappa
			w.slip_angle = atan(w.beta)


func _visuals(delta: float) -> void:
	for w: Wheel in wheels:
		w.angle = fmod(w.angle + w.omega * delta, TAU)
		w.pivot.transform = Transform3D(Basis(Vector3.UP, w.steer), w.rest + Vector3.UP * w.xs)
		w.spin.transform = Transform3D(Basis(Vector3.RIGHT, w.angle), Vector3.ZERO)
	for c in calipers:
		var w: Wheel = c[1]
		var hd: Node3D = c[0]
		hd.transform = Transform3D(Basis(Vector3.UP, w.steer), w.rest + Vector3.UP * w.xs)
	var be := 3.2 if braking else (1.6 if reversing else 0.6)
	for l in tail_lights:
		l.light_energy = lerpf(l.light_energy, be, 0.3)
	for m in brake_materials:
		m.emission_energy_multiplier = 18.0 if braking else 5.0
	if lightbar_on:
		_bar_t += delta
		var phase := int(_bar_t * 6.0) % 4
		bar_lights[0].light_energy = 4.0 if phase < 2 else 0.0
		bar_lights[1].light_energy = 0.0 if phase < 2 else 4.0
	if fx:
		fx.physics_update(delta)


var _nan_reported := false


## apply_force, refusing non-finite values (and saying where they came from, once).
var _acc_f := Vector3.ZERO
var _acc_t := Vector3.ZERO
var _com_rel := Vector3.ZERO               ## centre of mass - body origin (global orientation)


## Accumulates a force at `at` (relative to the body origin, global orientation); one
## apply_central_force + apply_torque per tick instead of 8 apply_force calls.
func _force(f: Vector3, at: Vector3, w: Wheel, what: String) -> void:
	if f.is_finite() and at.is_finite():
		_acc_f += f
		_acc_t += (at - _com_rel).cross(f)
		return
	if not _nan_reported:
		_nan_reported = true
		push_warning("car: non-finite %s force %s at %s on %s: x=%s load=%s omega=%s kappa=%s beta=%s vx=%s vy=%s push=%s n=%s fwd=%s" % [
			what, f, at, w.name, w.x, w.load, w.omega, w.kappa, w.beta, w.vx, w.vy, w.push, w.cnormal, w.fwd])
	for q: Wheel in wheels:
		if not (is_finite(q.omega) and is_finite(q.kappa) and is_finite(q.beta)):
			q.omega = 0.0
			q.kappa = 0.0
			q.beta = 0.0
	if not is_finite(engine_w):
		engine_w = float(P.engine.idle_rpm) * TAU / 60.0


func needs_reset() -> bool:
	return _flip_time > 2.0


func place(xf: Transform3D) -> void:
	global_transform = xf
	linear_velocity = Vector3.ZERO
	angular_velocity = Vector3.ZERO
	_last_vel = Vector3.ZERO
	_flip_time = 0.0
	_since_place = 0.0
	_steer_in = 0.0
	steer_angle = 0.0
	for w: Wheel in wheels:
		w.omega = 0.0
		w.kappa = 0.0
		w.beta = 0.0
		w.x = 0.0
		w.xs = 0.0
		w.xs_prev = 0.0
		w.abs_p = 1.0
		w.steer = 0.0
		w.ref_valid = false
	gear = 1
	_shift_t = 0.0
	engine_w = float(P.engine.idle_rpm) * TAU / 60.0
	if fx:
		fx.reset_marks()
	PhysicsServer3D.body_set_state(get_rid(), PhysicsServer3D.BODY_STATE_TRANSFORM, xf)
	reset_physics_interpolation()
	_snap_pending = true


## Tests / teleports at speed: wheels rolling at v, a sensible gear, engine at the matching revs.
func prime_speed(v: float) -> void:
	for w: Wheel in wheels:
		w.omega = v / w.r
		w.kappa = 0.0
		w.beta = 0.0
	if _electric:
		gear = 1
	else:
		gear = 1
		for g in range(1, _ratios.size() + 1):
			gear = g
			var r := absf(v / float(P.wheel_radius) * _ratio(g) * _final) * 60.0 / TAU
			if r < float(P.gearbox.auto_up_rpm[1]) * 0.75:
				break
	engine_w = maxf(absf(v / float(P.wheel_radius) * _ratio(gear) * _final), float(P.engine.idle_rpm) * TAU / 60.0)
	clutch = 1.0
	_since_shift = 0.0


## For the HUD / tests: how hard the tyres are working.
func max_slip() -> float:
	var m := 0.0
	for w: Wheel in wheels:
		if w.contact:
			m = maxf(m, w.slip_vel)
	return m
