extends Node3D
## Neon Hill: loads the Pigment town, the hero car, night lighting, rain, HUD.
##
## User args (after "--" on the Godot command line):
##   --autoshot=<dir>   scripted drive, saves PNGs + perf.json to <dir>, quits
##   --bench=<seconds>  autopilot drive, prints FPS / draw calls, quits
##   --drive-test       physics-only check (works with --headless), prints, quits
##   --gi               start with SDFGI on       --no-rain   start without rain
##   --no-town          skip the town (empty ground)

const TownLoader := preload("res://scripts/town_loader.gd")
const Car := preload("res://scripts/car.gd")
const ChaseCamera := preload("res://scripts/chase_camera.gd")
const Hud := preload("res://scripts/hud.gd")

const CAR_GLB := "res://assets/car/car.glb"
const CAR_JSON := "res://assets/car/car.json"

var town: Node3D
var car: VehicleBody3D
var cam: Camera3D
var hud: CanvasLayer
var env: Environment
var world_env: WorldEnvironment
var rain: GPUParticles3D
var args := {}
var _shadow_t := 0.0
const SHADOW_LAMPS := 3                 ## nearest street lamps that cast shadows
var _road_lines: Array = []
var _ap_line := 0
var _ap_idx := 0
var _ap_dir := 1
var _ap_turn := 0
var _ap_via = null        ## junction centre to pass through when changing runs
var _ap_stuck := 0.0
var ap_speed := 15.0


func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		var kv := String(a).trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "1"
	_setup_input()
	_setup_environment()
	town = TownLoader.new()
	town.name = "Town"
	add_child(town)
	if args.has("no-town") or not town.load_town(1.0):
		_fallback_ground()
	car = Car.new()
	car.name = "Car"
	add_child(car)
	car.setup(_car_path(CAR_GLB), _car_path(CAR_JSON))
	car.place(town.spawn_transform() if town.layout else Transform3D(Basis(), Vector3(0, 2, 0)))
	cam = ChaseCamera.new()
	cam.name = "ChaseCamera"
	cam.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	cam.target = car
	cam.near = 0.1
	cam.far = 900.0
	add_child(cam)
	cam.current = true
	hud = Hud.new()
	hud.car = car
	add_child(hud)
	car.impact.connect(hud.on_impact)
	_setup_rain()
	if args.has("no-rain"):
		rain.emitting = false
	if args.has("gi"):
		env.sdfgi_enabled = true
	_road_lines = town.road_polylines() if town.layout else []
	if args.has("autoshot") or args.has("bench") or args.has("drive-test"):
		var auto := preload("res://scripts/automation.gd").new()
		auto.main = self
		add_child(auto)


## The real car (assets/car from the car workstream) is copied in by tools/godot/sync_car.py;
## otherwise the placeholder generated to the same contract is used.
func _car_path(p: String) -> String:
	return p


# ------------------------------------------------------------------ input
func _setup_input() -> void:
	var keys := {
		"accelerate": [KEY_W, KEY_UP], "brake": [KEY_S, KEY_DOWN], "steer_left": [KEY_A, KEY_LEFT],
		"steer_right": [KEY_D, KEY_RIGHT], "handbrake": [KEY_SPACE], "reset": [KEY_R], "camera": [KEY_C],
		"toggle_rain": [KEY_F], "toggle_gi": [KEY_G], "toggle_stats": [KEY_F3], "quit": [KEY_ESCAPE],
	}
	var pads := {"handbrake": [JOY_BUTTON_A], "reset": [JOY_BUTTON_Y], "camera": [JOY_BUTTON_RIGHT_SHOULDER],
		"toggle_stats": [JOY_BUTTON_BACK]}
	var axes := {"accelerate": [JOY_AXIS_TRIGGER_RIGHT, 1.0], "brake": [JOY_AXIS_TRIGGER_LEFT, 1.0],
		"steer_left": [JOY_AXIS_LEFT_X, -1.0], "steer_right": [JOY_AXIS_LEFT_X, 1.0]}
	for action in keys:
		if not InputMap.has_action(action):
			InputMap.add_action(action, 0.15)
		for k in keys[action]:
			var e := InputEventKey.new()
			e.physical_keycode = k
			InputMap.action_add_event(action, e)
		for b in pads.get(action, []):
			var e := InputEventJoypadButton.new()
			e.button_index = b
			InputMap.action_add_event(action, e)
		if axes.has(action):
			var e := InputEventJoypadMotion.new()
			e.axis = axes[action][0]
			e.axis_value = axes[action][1]
			InputMap.action_add_event(action, e)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("reset"):
		reset_car()
	elif event.is_action_pressed("camera"):
		cam.cycle()
	elif event.is_action_pressed("toggle_rain"):
		rain.emitting = not rain.emitting
		rain.visible = rain.emitting
	elif event.is_action_pressed("toggle_gi"):
		env.sdfgi_enabled = not env.sdfgi_enabled
		print("SDFGI ", env.sdfgi_enabled)
	elif event.is_action_pressed("toggle_stats"):
		hud.show_fps = not hud.show_fps
	elif event.is_action_pressed("quit"):
		get_tree().quit()


func reset_car() -> void:
	if not town.layout:
		car.place(Transform3D(Basis(), Vector3(0, 2, 0)))
		return
	var r: Array = town.nearest_road(car.global_position)
	var d: Vector3 = r[1]
	if d.dot(car.global_basis.z) < 0.0:
		d = -d
	car.place(TownLoader.car_transform(r[0], d))
	cam.snap()


# ------------------------------------------------------------------ look
func _setup_environment() -> void:
	env = Environment.new()
	var sky := Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = Color(0.006, 0.008, 0.02)
	sm.sky_horizon_color = Color(0.07, 0.045, 0.09)     # city glow on the low cloud
	sm.ground_horizon_color = Color(0.05, 0.035, 0.07)
	sm.ground_bottom_color = Color(0.01, 0.01, 0.015)
	sm.sky_curve = 0.12
	sm.sun_angle_max = 1.0
	sky.sky_material = sm
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.9
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_exposure = 1.25
	env.glow_enabled = true
	env.glow_normalized = false
	env.glow_intensity = 0.7
	env.glow_strength = 1.0
	env.glow_bloom = 0.04
	env.glow_hdr_threshold = 0.9
	env.glow_hdr_scale = 2.0
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SCREEN
	for i in range(1, 8):
		env.set("glow_levels/%d" % i, [0.0, 0.6, 0.8, 1.0, 0.8, 0.5, 0.0][i - 1])
	env.ssr_enabled = true
	env.ssr_max_steps = 72
	env.ssr_fade_in = 0.1
	env.ssr_fade_out = 2.5
	env.ssr_depth_tolerance = 0.3
	env.ssao_enabled = true
	env.ssao_radius = 1.2
	env.ssao_intensity = 1.6
	# SDFGI is opt-in (G / --gi): voxelising ~14 M triangles stalls on a shared GPU; SSIL gives the
	# cheap screen-space bounce of neon and lamps instead
	env.sdfgi_enabled = false
	env.ssil_enabled = true
	env.ssil_radius = 6.0
	env.ssil_intensity = 1.4
	env.sdfgi_use_occlusion = true
	env.sdfgi_cascades = 4
	env.sdfgi_min_cell_size = 0.3
	env.sdfgi_energy = 1.2
	env.sdfgi_bounce_feedback = 0.5
	env.fog_enabled = true
	env.fog_mode = Environment.FOG_MODE_EXPONENTIAL
	env.fog_light_color = Color(0.09, 0.07, 0.13)
	env.fog_density = 0.006
	env.fog_sky_affect = 0.4
	env.fog_aerial_perspective = 0.2
	env.volumetric_fog_enabled = true
	env.volumetric_fog_density = 0.018
	env.volumetric_fog_albedo = Color(0.75, 0.78, 0.9)
	env.volumetric_fog_emission = Color(0.02, 0.015, 0.03)
	env.volumetric_fog_emission_energy = 0.4
	env.volumetric_fog_anisotropy = 0.45
	env.volumetric_fog_length = 110.0
	env.volumetric_fog_detail_spread = 1.6
	env.volumetric_fog_gi_inject = 0.6
	env.volumetric_fog_ambient_inject = 0.15
	env.volumetric_fog_sky_affect = 0.3
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.06
	env.adjustment_saturation = 1.08
	world_env = WorldEnvironment.new()
	world_env.environment = env
	add_child(world_env)
	var moon := DirectionalLight3D.new()
	moon.name = "Moon"
	moon.light_color = Color(0.55, 0.65, 1.0)
	moon.light_energy = 0.12
	moon.shadow_enabled = false            # at this energy its shadows are invisible; lamps cast instead
	moon.directional_shadow_max_distance = 90.0
	moon.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	moon.light_volumetric_fog_energy = 0.4
	moon.rotation_degrees = Vector3(-50, 35, 0)
	add_child(moon)


func _setup_rain() -> void:
	rain = GPUParticles3D.new()
	rain.name = "Rain"
	rain.amount = 9000
	rain.lifetime = 1.4
	rain.preprocess = 1.4
	rain.local_coords = false
	rain.visibility_aabb = AABB(Vector3(-40, -40, -40), Vector3(80, 60, 80))
	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	pm.emission_box_extents = Vector3(28, 1, 28)
	pm.direction = Vector3(0.08, -1, 0.03)
	pm.spread = 2.0
	pm.initial_velocity_min = 20.0
	pm.initial_velocity_max = 26.0
	pm.gravity = Vector3.ZERO
	pm.collision_mode = ParticleProcessMaterial.COLLISION_DISABLED
	rain.process_material = pm
	var q := QuadMesh.new()
	q.size = Vector2(0.014, 0.6)
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.albedo_color = Color(0.65, 0.75, 0.95, 0.22)
	m.billboard_mode = BaseMaterial3D.BILLBOARD_FIXED_Y
	m.billboard_keep_scale = true
	m.disable_receive_shadows = true
	q.material = m
	rain.draw_pass_1 = q
	rain.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(rain)


func _fallback_ground() -> void:
	var body := StaticBody3D.new()
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(400, 1, 400)
	cs.shape = b
	cs.position = Vector3(0, -0.5, 0)
	body.add_child(cs)
	var mi := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(400, 400)
	mi.mesh = pm
	body.add_child(mi)
	add_child(body)
	var l := Label3D.new()
	l.text = "Town not exported yet:\nblender -b --factory-startup --python tools/godot/export_town.py"
	l.position = Vector3(0, 3, 12)
	l.rotation_degrees = Vector3(0, 180, 0)
	l.font_size = 64
	add_child(l)


func _process(delta: float) -> void:
	if rain and cam:
		rain.global_position = cam.global_position + Vector3.UP * 14.0 + cam.global_basis.z * -8.0
	if car.needs_reset() or (town.layout and car.global_position.y < town.bounds.position.y):
		reset_car()
	# shadows on the few street lamps nearest the camera
	_shadow_t -= delta
	if _shadow_t <= 0.0 and town and cam:
		_shadow_t = 0.3
		var lamps: Array = town.lamp_lights.duplicate()
		var cp := cam.global_position
		lamps.sort_custom(func(a, b): return a.global_position.distance_squared_to(cp) < b.global_position.distance_squared_to(cp))
		for i in lamps.size():
			lamps[i].shadow_enabled = i < SHADOW_LAMPS and lamps[i].global_position.distance_to(cp) < 50.0


# ------------------------------------------------------------------ autopilot (automation + demo)
## Follow a road centre line: pick the nearest polyline, steer to a look-ahead point.
func autopilot_start() -> void:
	car.autopilot = true
	var best := INF
	for li in _road_lines.size():
		var pts: PackedVector3Array = _road_lines[li]
		for i in pts.size():
			var d := pts[i].distance_squared_to(car.global_position)
			if d < best:
				best = d
				_ap_line = li
				_ap_idx = i
	var pts: PackedVector3Array = _road_lines[_ap_line]
	var a := pts[maxi(0, _ap_idx - 1)]
	var b := pts[mini(pts.size() - 1, _ap_idx + 1)]
	_ap_dir = 1 if (b - a).dot(car.global_basis.z) >= 0.0 else -1


## At the end of a run, continue on another run that starts/ends at the same junction
## (or turn back on the same one at a free end of the map).
func _ap_next_line() -> void:
	var pts: PackedVector3Array = _road_lines[_ap_line]
	var end := pts[_ap_idx]
	var cands := []
	for li in _road_lines.size():
		if li == _ap_line:
			continue
		var q: PackedVector3Array = _road_lines[li]
		if q[0].distance_to(end) < 45.0:
			cands.append([li, 0, 1])
		if q[q.size() - 1].distance_to(end) < 45.0:
			cands.append([li, q.size() - 1, -1])
	if cands.is_empty():
		_ap_dir = -_ap_dir
		var d := pts[_ap_idx] - pts[_ap_idx + _ap_dir]
		car.place(TownLoader.car_transform(pts[_ap_idx], -d))
		return
	var c: Array = cands[_ap_turn % cands.size()]
	_ap_turn += 1
	var jbest := INF
	for jd in town.layout.get("junctions", []):
		var jp := Vector3(jd.pos[0], jd.pos[1], jd.pos[2])
		if jp.distance_to(end) < jbest:
			jbest = jp.distance_to(end)
			_ap_via = jp
	if jbest > 40.0:
		_ap_via = null
	_ap_line = c[0]
	_ap_idx = c[1]
	_ap_dir = c[2]


func autopilot_step(_delta: float) -> void:
	if _road_lines.is_empty():
		car.input_throttle = 0.5
		return
	var pts: PackedVector3Array = _road_lines[_ap_line]
	var p := car.global_position
	var fwd := car.global_basis.z
	# advance the progress index while the next sample is closer
	while _ap_idx + _ap_dir >= 0 and _ap_idx + _ap_dir < pts.size() and pts[_ap_idx + _ap_dir].distance_to(p) < pts[_ap_idx].distance_to(p) + 1.0:
		_ap_idx += _ap_dir
	var at_end := _ap_idx + _ap_dir < 0 or _ap_idx + _ap_dir >= pts.size()
	if at_end:
		_ap_next_line()
		pts = _road_lines[_ap_line]
	var look := 7.0 + car.linear_velocity.length() * 0.6
	var j := _ap_idx
	while j + _ap_dir >= 0 and j + _ap_dir < pts.size() and pts[j].distance_to(p) < look:
		j += _ap_dir
	var target := pts[j]
	if _ap_via != null:
		if (_ap_via - p).length() < 7.0:
			_ap_via = null
		else:
			target = _ap_via + (pts[_ap_idx] - _ap_via).normalized() * 3.0
	# keep left of centre (left-hand traffic, like the hill towns it is modelled on)
	var tdir := (pts[j] - pts[clampi(j - _ap_dir, 0, pts.size() - 1)]).normalized()
	target += Vector3.UP.cross(tdir).normalized() * 2.0
	var to := target - p
	to.y = 0
	var ang := fwd.signed_angle_to(to.normalized(), Vector3.UP)
	car.input_steer = clampf(ang * 2.2, -1.0, 1.0)
	# slow for the bend ahead
	var k := clampi(j + _ap_dir * 8, 0, pts.size() - 1)
	var bend := absf(tdir.signed_angle_to((pts[k] - pts[j]).normalized(), Vector3.UP)) if k != j else 0.0
	var v: float = car.forward_speed()
	var want := ap_speed * (1.0 - clampf(absf(ang) * 1.2 + bend * 0.8, 0.0, 0.6))
	car.input_throttle = clampf((want - v) * 0.35, -1.0, 1.0)
	# wedged against something: put it back on the road
	_ap_stuck = _ap_stuck + _delta if absf(v) < 0.5 and car.input_throttle > 0.3 else 0.0
	if _ap_stuck > 3.0:
		_ap_stuck = 0.0
		_ap_via = null
		var q := pts[clampi(_ap_idx + _ap_dir * 2, 0, pts.size() - 1)]
		car.place(TownLoader.car_transform(q, (q - pts[_ap_idx]) if q != pts[_ap_idx] else fwd))
		print("autopilot: unstuck at ", q)
