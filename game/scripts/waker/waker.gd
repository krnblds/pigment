extends Node3D
## The Waker layer of the game: you, a Hoshikawa Waker, on foot and at the wheel. Owns the on-foot
## player (scripts/player/), the over-the-shoulder camera, the combat world and weapons
## (scripts/weapons/), the Waker HUD, the Hoshikawa posts (respawn points) and the case loop
## (case_manager.gd: Sleepwalker cases), and hands control between the car and the player.
##
## main.gd: `waker = Waker.new(); add_child(waker); waker.setup(self)` after the HUD / garage / pause menu.
## --no-cases: no case loop (on foot, weapons and cars still work).
##
## Car <-> foot: F gets out (the car is parked: brakes on, handbrake, engine idles, it stays where you
## left it) and back in. While on foot main.cam points at the shoulder camera (rain / lamp shadows follow
## it), the town streams collision around the player, and the garage only opens from the car (opening it
## from the pause menu puts you back in first).

const Player := preload("res://scripts/player/player.gd")
const OtsCamera := preload("res://scripts/player/ots_camera.gd")
const Combat := preload("res://scripts/weapons/combat.gd")
const WakerHud := preload("res://scripts/waker/waker_hud.gd")
const CaseManager := preload("res://scripts/waker/case_manager.gd")

var main: Node3D
var player: CharacterBody3D
var ots: Camera3D
var chase: Camera3D
var combat: Node3D
var hud: CanvasLayer
var cases: Node                          ## case_manager.gd (null with --no-cases)
var stations: Array = []                 ## Hoshikawa Waker posts: [{name, pos}]
var parked: Array = []                   ## cars the player left (kept parked)
var siren: AudioStreamPlayer3D
var prof_us := 0.0
var _siren_car: Node
var _scripted := false                   ## tests / shots / benches: never grab the mouse


func setup(m: Node3D) -> void:
	main = m
	name = "Waker"
	for k in m.args:
		if String(k).ends_with("-test") or String(k).ends_with("-shots") or String(k).ends_with("-shot") or String(k).begins_with("bench") or k in ["autoshot", "foliage-demo"]:
			_scripted = true
	process_mode = Node.PROCESS_MODE_ALWAYS          # mouse mode follows pause; children pause normally
	_setup_input()
	combat = Combat.new()
	combat.main = m
	combat.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(combat)
	ots = OtsCamera.new()
	ots.name = "ShoulderCamera"
	ots.near = 0.05
	ots.far = m.cam.far if m.cam else 3000.0
	ots.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	ots.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(ots)
	chase = m.cam
	player = Player.new()
	player.waker = self
	player.cam = ots
	player.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(player)
	ots.target = player
	player.state = "car"
	player.car = m.car
	player.global_position = m.car.global_position
	player.exited_car.connect(_on_exited)
	player.entered_car.connect(_on_entered)
	_pick_stations()
	hud = WakerHud.new()
	hud.waker = self
	hud.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(hud)
	if not (m.args.has("no-cases") or _automation_only()):
		cases = CaseManager.new()
		cases.waker = self
		cases.process_mode = Node.PROCESS_MODE_PAUSABLE
		add_child(cases)
	if m.garage and m.garage.has_signal("opened"):
		m.garage.opened.connect(_on_garage_opened)


## Other workstreams' automation: keep their runs exactly as before (no case dispatches).
func _automation_only() -> bool:
	for k in ["autoshot", "bench", "bench-spots", "bench-matrix", "drive-old", "drive-test", "curb-test", "physics-shots",
			"car-cost", "traffic-test", "traffic-shots", "bench-traffic", "road-clear-test", "foliage-demo", "interior-shots",
			"bridge-shots", "damage-test", "damage-shots", "damage-bench", "showroom-test", "showroom-shot", "onfoot-test",
			"weapons-test"]:
		if main.args.has(k):
			return true
	return false


# ================================================================== input
func _setup_input() -> void:
	# F is the door now; rain moves to F4
	if InputMap.has_action("toggle_rain"):
		for e in InputMap.action_get_events("toggle_rain"):
			if e is InputEventKey and e.physical_keycode == KEY_F:
				InputMap.action_erase_event("toggle_rain", e)
		var f4 := InputEventKey.new()
		f4.physical_keycode = KEY_F4
		InputMap.action_add_event("toggle_rain", f4)
	var keys := {
		"foot_fwd": [KEY_W, KEY_UP], "foot_back": [KEY_S, KEY_DOWN], "foot_left": [KEY_A, KEY_LEFT], "foot_right": [KEY_D, KEY_RIGHT],
		"sprint": [KEY_SHIFT], "walk": [KEY_ALT], "crouch": [KEY_CTRL], "jump": [KEY_SPACE], "reload_weapon": [KEY_R],
		"holster": [KEY_H], "shoulder_swap": [KEY_X], "quick_emp": [KEY_Z], "scan": [KEY_Q], "wake": [KEY_E],
		"enter_exit": [KEY_F], "weapon_1": [KEY_1], "weapon_2": [KEY_2], "weapon_3": [KEY_3], "weapon_4": [KEY_4],
		"weapon_5": [KEY_5], "weapon_6": [KEY_6], "choice_report": [KEY_1], "choice_keep": [KEY_2], "case_log": [KEY_TAB],
	}
	var pads := {"jump": [JOY_BUTTON_A], "crouch": [JOY_BUTTON_B], "reload_weapon": [JOY_BUTTON_X], "enter_exit": [JOY_BUTTON_Y],
		"sprint": [JOY_BUTTON_LEFT_STICK], "shoulder_swap": [JOY_BUTTON_RIGHT_STICK], "weapon_next": [JOY_BUTTON_DPAD_RIGHT],
		"weapon_prev": [JOY_BUTTON_DPAD_LEFT], "wake": [JOY_BUTTON_DPAD_UP], "holster": [JOY_BUTTON_DPAD_DOWN], "scan": [JOY_BUTTON_LEFT_SHOULDER]}
	var axes := {"foot_fwd": [JOY_AXIS_LEFT_Y, -1.0], "foot_back": [JOY_AXIS_LEFT_Y, 1.0], "foot_left": [JOY_AXIS_LEFT_X, -1.0],
		"foot_right": [JOY_AXIS_LEFT_X, 1.0], "aim": [JOY_AXIS_TRIGGER_LEFT, 1.0], "fire": [JOY_AXIS_TRIGGER_RIGHT, 1.0]}
	var mouse := {"aim": MOUSE_BUTTON_RIGHT, "fire": MOUSE_BUTTON_LEFT, "weapon_next": MOUSE_BUTTON_WHEEL_DOWN, "weapon_prev": MOUSE_BUTTON_WHEEL_UP}
	var all := {}
	for k in keys: all[k] = true
	for k in pads: all[k] = true
	for k in axes: all[k] = true
	for k in mouse: all[k] = true
	for action in all:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action, 0.2)
		for k in keys.get(action, []):
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
		if mouse.has(action):
			var e := InputEventMouseButton.new()
			e.button_index = mouse[action]
			InputMap.action_add_event(action, e)


func _unhandled_input(event: InputEvent) -> void:
	if get_tree().paused or _garage_inside():
		return
	if hud and hud.handle_input(event):
		get_viewport().set_input_as_handled()
		return
	if cases and cases.handle_input(event):
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("enter_exit"):
		toggle_car()
		get_viewport().set_input_as_handled()
		return
	if player.on_foot():
		if player.handle_input(event):
			get_viewport().set_input_as_handled()
			return
		# on foot the car keys mean nothing; keep them from reaching the parked car / reset
		if event.is_action_pressed("reset") or event.is_action_pressed("garage") or event.is_action_pressed("handbrake"):
			if event.is_action_pressed("garage"):
				hud.toast("GARAGE: GET BACK IN YOUR CAR FIRST")
			get_viewport().set_input_as_handled()
		elif event is InputEventMouseButton:
			get_viewport().set_input_as_handled()


func _garage_inside() -> bool:
	return main.garage != null and bool(main.garage.get("inside"))


# ================================================================== car <-> foot
func toggle_car() -> void:
	if player.state == "car":
		if not player.exit_car():
			hud.toast("TOO FAST TO GET OUT")
	elif player.on_foot():
		var c := nearest_enterable()
		if c and player.can_enter(c):
			player.enter(c)
		elif c:
			hud.toast("TOO FAR FROM THE CAR")


func nearest_enterable() -> RigidBody3D:
	var best: RigidBody3D = null
	var bd := INF
	var cands: Array = get_tree().get_nodes_in_group("enterable_car")
	if main.car and not cands.has(main.car):
		cands.append(main.car)
	for c in cands:
		if not is_instance_valid(c) or not (c is RigidBody3D) or c.get_meta("locked", false):
			continue
		var d: float = (c as Node3D).global_position.distance_to(player.global_position)
		if d < bd:
			bd = d
			best = c
	return best


## Park a car: brakes, handbrake, no throttle (car.gd's autopilot inputs), so nobody's keys drive it.
static func park(c: RigidBody3D) -> void:
	if c == null:
		return
	c.autopilot = true
	c.input_throttle = 0.0
	c.input_brake = 0.0                  # (held brake at a stop means "reverse" to car.gd's automatic)
	c.input_steer = 0.0
	c.input_handbrake = true


func _on_exited(c: Node) -> void:
	park(c)
	if not parked.has(c):
		parked.append(c)
	if main.cam and main.cam != ots:
		chase = main.cam
	var cf: Vector3 = (c as Node3D).global_basis.z
	ots.yaw = atan2(-cf.x, -cf.z)          # look the way the car was facing
	ots.pitch = -0.15
	ots.blend_from(chase.global_transform, 0.6)
	ots.current = true
	main.cam = ots
	main.set("player_focus", player)
	if main.town and "collision_focus" in main.town:
		main.town.collision_focus = player
	_capture()


func _on_entered(c: Node) -> void:
	if c != main.car:
		switch_hero(c as RigidBody3D)
	parked.erase(c)
	c.autopilot = false
	c.input_brake = 0.0
	c.input_handbrake = false
	main.cam = chase
	chase.target = c
	chase.current = true
	if chase.has_method("snap"):
		chase.snap()
	main.set("player_focus", null)
	if main.town and "collision_focus" in main.town:
		main.town.collision_focus = c
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


## Make `c` the player's car without throwing the old one away (the garage's install_car frees it).
func switch_hero(c: RigidBody3D) -> void:
	var old: RigidBody3D = main.car
	if old == c:
		return
	main.car = c
	c.town = main.town
	if old:
		park(old)
		old.add_to_group("enterable_car")
	if chase:
		chase.target = c
	if main.hud:
		main.hud.car = c
		for n in main.hud.find_children("*", "", true, false):
			if n.get_script() == preload("res://scripts/vehicle/tacho.gd"):
				n.car = c
		if not c.impact.is_connected(main.hud.on_impact):
			c.impact.connect(main.hud.on_impact)
	if main.traffic:
		c.collision_mask |= 2
		if "_hero_rid" in main.traffic:
			main.traffic._hero_rid = c.get_rid()
	if "damage" in main and main.damage and main.damage.has_method("set_hero") and "spec" in c and not c.spec.get("damage", {}).is_empty():
		main.damage.set_hero(c)
	if main.garage:
		for g in main.garage.garages:
			g.set_meta("player", c)


func _on_garage_opened() -> void:
	# the showroom works on the car: be in it
	if player.state != "car":
		player.state = "car"
		player.car = main.car
		player._set_present(false)
		_on_entered(main.car)


func _capture() -> void:
	if DisplayServer.get_name() != "headless" and not _scripted:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


# ================================================================== stations (respawn posts)
const POST_NAMES := ["HOSHIKAWA WAKER POST 1 // HARBOUR", "WAKER POST 2 // KABUKI ROW", "WAKER POST 3 // HILL DISTRICT",
	"WAKER POST 4 // TENJIN", "WAKER POST 5 // SECTOR 9"]


func _pick_stations() -> void:
	var pts: Array = []
	if main.town and main.town.layout:
		for j in main.town.layout.get("junctions", []):
			pts.append(Vector3(j.pos[0], j.pos[1], j.pos[2]))
	if pts.is_empty():
		pts = [main.car.global_position]
	# farthest-point sampling from the spawn: posts spread over the map
	var chosen: Array = [_closest(pts, main.car.global_position)]
	while chosen.size() < mini(POST_NAMES.size(), pts.size()):
		var best := Vector3.ZERO
		var bd := -1.0
		for p in pts:
			var d := INF
			for c in chosen:
				d = minf(d, (p as Vector3).distance_to(c))
			if d > bd:
				bd = d
				best = p
		chosen.append(best)
	for i in chosen.size():
		var p: Vector3 = chosen[i]
		stations.append({"name": POST_NAMES[i], "pos": p + Vector3(4.0, 0.0, 4.0)})
		_post_marker(stations[-1])


func _closest(pts: Array, q: Vector3) -> Vector3:
	var best: Vector3 = pts[0]
	for p in pts:
		if (p as Vector3).distance_to(q) < best.distance_to(q):
			best = p
	return best


func _post_marker(s: Dictionary) -> void:
	var n := Node3D.new()
	n.name = "WakerPost"
	add_child(n)
	n.position = s.pos
	var mi := MeshInstance3D.new()
	var c := CylinderMesh.new()
	c.top_radius = 0.12
	c.bottom_radius = 0.18
	c.height = 4.0
	mi.mesh = c
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0.04, 0.05, 0.07)
	m.emission_enabled = true
	m.emission = Color(0.3, 0.9, 1.0)
	m.emission_energy_multiplier = 0.6
	mi.material_override = m
	mi.position.y = 2.0
	n.add_child(mi)
	var l := Label3D.new()
	l.text = "HOSHIKAWA\n" + String(s.name).replace("HOSHIKAWA ", "")
	l.font_size = 48
	l.pixel_size = 0.006
	l.modulate = Color(0.4, 0.95, 1.0)
	l.billboard = BaseMaterial3D.BILLBOARD_FIXED_Y
	l.position.y = 4.6
	l.visibility_range_end = 120.0
	n.add_child(l)


func nearest_station(p: Vector3) -> Vector3:
	var best := Vector3.INF
	for s in stations:
		if (s.pos as Vector3).distance_to(p) < best.distance_to(p):
			best = s.pos
	if best != Vector3.INF and main.town and main.town.has_method("ensure_collision"):
		main.town.ensure_collision(best, 30.0)
		var q := PhysicsRayQueryParameters3D.create(best + Vector3.UP * 30.0, best + Vector3.DOWN * 30.0, 1)
		var h := get_world_3d().direct_space_state.intersect_ray(q)
		if h:
			best = h.position + Vector3.UP * 0.05
	return best


# ================================================================== per frame
func _process(_dt: float) -> void:
	var t0 := Time.get_ticks_usec()
	# mouse: captured on foot while playing, free in the car, in menus and the garage
	var want_capture: bool = player.on_foot() and not get_tree().paused and not _garage_inside() and not (hud and hud.modal())
	if DisplayServer.get_name() != "headless" and not _scripted:
		if want_capture and Input.mouse_mode != Input.MOUSE_MODE_CAPTURED and DisplayServer.window_is_focused():
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		elif not want_capture and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	if get_tree().paused:
		return
	_siren_tick()
	for c in parked:
		if is_instance_valid(c) and c != player.car:
			park(c)
	prof_us = lerpf(prof_us, float(Time.get_ticks_usec() - t0), 0.05)


## The cruiser's light bar (L) runs the siren.
func _siren_tick() -> void:
	var c = main.car
	var on: bool = c != null and bool(c.get("lightbar_on")) and not (c.get("bar_lights") as Array).is_empty()
	if on and (siren == null or _siren_car != c):
		if siren:
			siren.queue_free()
		siren = combat.audio.loop("siren", c, -4.0)
		_siren_car = c
		siren.play()
	elif not on and siren:
		siren.queue_free()
		siren = null
		_siren_car = null


func cost_breakdown() -> String:
	return "waker %.0f  combat %.0f  cases %.0f  hud %.0f  player %.0f us" % [prof_us, combat.prof_us, cases.prof_us if cases else 0.0, hud.prof_us if hud else 0.0, player.prof_us]


func combat_cost_us() -> float:
	return prof_us + combat.prof_us + (cases.prof_us if cases else 0.0) + (hud.prof_us if hud else 0.0) + player.prof_us
