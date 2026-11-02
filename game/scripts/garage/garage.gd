extends Node
## Drive-in garages: the buildings in the city (data/garages.json, garage_exterior.gd), the interior you
## drive into (garage_interior.gd), its menu (garage_ui.gd) and the player-car customisation
## (tuning.gd, saved to user://garage.json and loaded on the next launch).
##
##   main.gd:  Garage.prepare(town, map) before load_town (lots: buildings / props there are skipped),
##             then garage.setup(main) once the car, camera, HUD and traffic exist.
##   Drive into a garage's lit bay (Area3D) -> fade -> interior.  V (or the pause menu) opens it from
##   anywhere as a showroom; leaving puts the car back where it was.
##   Inside: the car stands on the turntable; every change is applied to it live.  ENTER drives out with
##   the changes (saved), ESC leaves without them.  Swapping the vehicle rebuilds the player car at run
##   time (car.gd setup with that vehicle's glb + physics data, like --vehicle=<id>) and rewires the
##   camera, HUD, traffic and collision streaming to it.

const Fleet := preload("res://scripts/garage/fleet.gd")
const Tuning := preload("res://scripts/garage/tuning.gd")
const Interior := preload("res://scripts/garage/garage_interior.gd")
const Exterior := preload("res://scripts/garage/garage_exterior.gd")
const UI := preload("res://scripts/garage/garage_ui.gd")
const Car := preload("res://scripts/car.gd")
const DATA := "res://data/garages.json"
## Automation / tests: never load the player's saved car there.
const NO_SAVE_FLAGS := ["autoshot", "bench", "bench-spots", "bench-matrix", "drive-old", "drive-test", "curb-test",
	"physics-shots", "car-cost", "traffic-test", "traffic-shots", "bench-traffic", "road-clear-test", "foliage-demo",
	"interior-shots", "bridge-shots", "vehicle", "showroom-test", "no-garage-save"]

signal opened
signal closed

var main: Node3D
var garages: Array = []         ## garage_exterior.gd nodes
var interior: Node3D
var ui: CanvasLayer
var cam: Camera3D
var inside := false
var busy := false               ## fading / rebuilding
var current: Node3D             ## the garage driven into (null: showroom shortcut)
var cfg := {}
var entry_cfg := {}
var save_path := Tuning.SAVE
var return_xf := Transform3D()
var yaw := 0.6
var pitch := 0.2
var dist := 8.0
var _drag := false
var _fade: ColorRect
var _hint: Label
var _marker: Label
var _saved := {}                ## things switched off while inside (env, moon, rain, hud, traffic)
var _car_layers := Vector2i(1, 1)
var _shot_dir := ""


## Lot data for the map ("world" only); tells the town loader what to leave out.  Call before load_town.
static func prepare(town: Node, map_name: String) -> Array:
	if map_name != "world" or not FileAccess.file_exists(DATA):
		return []
	var d = JSON.parse_string(FileAccess.get_file_as_string(DATA))
	if not (d is Dictionary):
		return []
	var list: Array = d.get("garages", [])
	if "skip_instances" in town:
		for g in list:
			for r in g.get("remove", []):
				if not town.skip_instances.has(r[0]):
					town.skip_instances[r[0]] = []
				town.skip_instances[r[0]].append(Vector3(r[1], r[2], r[3]))
			for l in g.get("remove_lights", []):
				town.skip_lights.append(Vector3(l[0], l[1], l[2]))
	return list


func setup(m: Node3D, list: Array) -> void:
	main = m
	name = "Garage"
	process_mode = Node.PROCESS_MODE_ALWAYS
	save_path = String(main.args.get("garage-save", Tuning.SAVE))
	for d in list:
		var g := Exterior.new()
		g.setup(d)
		main.add_child(g)
		g.set_meta("player", main.car)
		g.entered.connect(_on_entered)
		garages.append(g)
	_clear_parked()
	_build_overlay()
	# the player's saved car (garage customisation) on a normal launch
	if not NO_SAVE_FLAGS.any(func(f): return main.args.has(f)):
		var saved := Tuning.load_cfg(save_path)
		if not saved.is_empty():
			var xf: Transform3D = main.car.global_transform
			install_car(build_car(saved), xf)
			Tuning.apply(main.car, saved)
			print("garage: loaded the saved car (%s, %s) from %s" % [saved.vehicle, saved.variant, save_path])
	print("garage: %d garages %s" % [garages.size(), ", ".join(garages.map(func(g): return "%s @ %s" % [g.data.id, g.global_position.snapped(Vector3.ONE * 0.1)]))])


## Parked traffic in front of a garage door would block the driveway.
func _clear_parked() -> void:
	if main.traffic == null or not ("parked" in main.traffic):
		return
	var gone := 0
	for p in main.traffic.parked.duplicate():
		for g in garages:
			var local: Vector3 = g.global_transform.affine_inverse() * p.global_position
			if absf(local.x) < 9.0 and local.z > 0.0 and local.z < g.size.z * 0.5 + 16.0:
				main.traffic.parked.erase(p)
				p.queue_free()
				gone += 1
				break
	if gone:
		print("garage: %d parked cars moved off the driveways" % gone)


func _build_overlay() -> void:
	var layer := CanvasLayer.new()
	layer.layer = 40
	layer.process_mode = Node.PROCESS_MODE_ALWAYS
	add_child(layer)
	_hint = Label.new()
	_hint.add_theme_font_size_override("font_size", 24)
	_hint.add_theme_color_override("font_color", Color(0.35, 0.95, 1.0))
	_hint.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	_hint.add_theme_constant_override("outline_size", 6)
	_hint.set_anchors_preset(Control.PRESET_CENTER_TOP)
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hint.position = Vector2(-500, 62)
	_hint.size = Vector2(1000, 40)
	_hint.visible = false
	_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(_hint)
	_marker = Label.new()
	_marker.add_theme_font_size_override("font_size", 20)
	_marker.add_theme_color_override("font_color", Color(1.0, 0.3, 0.7))
	_marker.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.9))
	_marker.add_theme_constant_override("outline_size", 6)
	_marker.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_marker.size = Vector2(240, 60)
	_marker.visible = false
	_marker.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(_marker)
	var fl := CanvasLayer.new()
	fl.layer = 90
	add_child(fl)
	_fade = ColorRect.new()
	_fade.color = Color(0, 0, 0, 0)
	_fade.set_anchors_preset(Control.PRESET_FULL_RECT)
	_fade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	fl.add_child(_fade)


func nearest() -> Array:
	var best: Node3D = null
	var bd := INF
	if main.car == null:
		return [null, INF]
	for g in garages:
		var d: float = g.door_position().distance_to(main.car.global_position)
		if d < bd:
			bd = d
			best = g
	return [best, bd]


func _process(delta: float) -> void:
	if inside:
		if interior and main.car and not busy:
			main.car.global_transform = interior.car_transform()
		_orbit(delta)
		return
	var n := nearest()
	var g: Node3D = n[0]
	var d: float = n[1]
	for x in garages:
		x.marker.visible = x == g and d < 180.0
	_hint.visible = g != null and d < 70.0 and not busy
	if _hint.visible:
		_hint.text = "◆  %s  —  %d m   drive in through the lit roller door  ◆" % [String(g.data.name), int(d)]
	_marker.visible = false
	var vc := get_viewport().get_camera_3d()
	if g and d < 400.0 and vc:
		var p: Vector3 = g.door_position() + Vector3.UP * 6.5
		if not vc.is_position_behind(p):
			var sp := vc.unproject_position(p)
			_marker.visible = true
			_marker.text = "▼ GARAGE\n%d m" % int(d)
			_marker.position = sp - Vector2(120, 50)


# ------------------------------------------------------------------ input
func _unhandled_input(event: InputEvent) -> void:
	if not inside:
		if event.is_action_pressed("garage") and not busy and not get_tree().paused:
			get_viewport().set_input_as_handled()
			open(null)
		return
	if busy:
		get_viewport().set_input_as_handled()
		return
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_LEFT:
			_drag = event.pressed
		elif event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			dist = clampf(dist * 0.92, 4.0, 14.0)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			dist = clampf(dist * 1.08, 4.0, 14.0)
		get_viewport().set_input_as_handled()
	elif event is InputEventMouseMotion and _drag:
		yaw -= event.relative.x * 0.006
		pitch = clampf(pitch + event.relative.y * 0.004, -0.05, 1.1)
		get_viewport().set_input_as_handled()
	elif event is InputEventKey and event.pressed:
		var k: int = event.physical_keycode
		var handled := true
		match k:
			KEY_ESCAPE, KEY_BACKSPACE:
				leave(false)
			KEY_ENTER, KEY_KP_ENTER:
				leave(true)
			KEY_UP, KEY_W:
				ui.move(-1)
			KEY_DOWN, KEY_S:
				ui.move(1)
			KEY_LEFT, KEY_A:
				step(ui.selected_key(), -1)
			KEY_RIGHT, KEY_D:
				step(ui.selected_key(), 1)
			KEY_PAGEUP:
				step("vehicle", -1)
			KEY_PAGEDOWN:
				step("vehicle", 1)
			KEY_TAB:
				step("vehicle", -1 if event.shift_pressed else 1)
			KEY_BRACKETLEFT:
				step("variant", -1)
			KEY_BRACKETRIGHT:
				step("variant", 1)
			KEY_SPACE:
				interior.spin = not interior.spin
			KEY_P:
				ui.edit_plate()
			KEY_F3:
				handled = false
			_:
				handled = k in [KEY_Q, KEY_E, KEY_Z, KEY_X, KEY_R, KEY_F, KEY_G, KEY_L, KEY_C, KEY_B, KEY_T, KEY_J, KEY_K, KEY_V]
		if handled:
			get_viewport().set_input_as_handled()


func _orbit(delta: float) -> void:
	if cam == null:
		return
	if not get_viewport().gui_get_focus_owner() is LineEdit:
		if Input.is_physical_key_pressed(KEY_Q):
			yaw += delta * 1.2
		if Input.is_physical_key_pressed(KEY_E):
			yaw -= delta * 1.2
		if Input.is_physical_key_pressed(KEY_Z):
			dist = clampf(dist - delta * 4.0, 4.0, 14.0)
		if Input.is_physical_key_pressed(KEY_X):
			dist = clampf(dist + delta * 4.0, 4.0, 14.0)
	var target: Vector3 = interior.global_position + Vector3(0, 0.75, 0)
	var off := Vector3(sin(yaw) * cos(pitch), sin(pitch), cos(yaw) * cos(pitch)) * dist
	cam.global_position = target + off
	cam.look_at(target, Vector3.UP)


# ------------------------------------------------------------------ enter / leave
func _on_entered(g: Node3D) -> void:
	if not inside and not busy:
		open(g)


func open(g: Node3D) -> void:
	if inside or busy:
		return
	busy = true
	get_tree().paused = false
	await _fade_to(1.0)
	current = g
	return_xf = main.car.global_transform
	if interior == null:
		interior = Interior.new()
		interior.name = "GarageInterior"
		main.add_child(interior)
		cam = Camera3D.new()
		cam.name = "GarageCamera"
		cam.fov = 50.0
		cam.near = 0.05
		cam.far = 120.0
		cam.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
		interior.add_child(cam)
		ui = UI.new()
		ui.ctrl = self
		add_child(ui)
	var d: Dictionary = g.data if g else {"name": "SHOWROOM", "sub": "HOSHIKAWA FLEET  //  SHOWROOM", "accent": [0.2, 0.85, 1.0], "accent2": [1.0, 0.18, 0.62]}
	interior.style(_c(d.get("accent", [1, 0.2, 0.6])), _c(d.get("accent2", [0.2, 0.9, 1])), String(d.get("name", "GARAGE")), String(d.get("sub", "")))
	interior.visible = true
	# world look off, garage look on
	_saved = {"env": main.world_env.environment, "rain": main.rain.visible if main.rain else false,
		"rain_emit": main.rain.emitting if main.rain else false, "hud": main.hud.visible if main.hud else true}
	main.world_env.environment = interior.env
	for n in main.get_children():
		if n is DirectionalLight3D and n.visible:
			n.visible = false
			_saved["moon_" + String(n.name)] = n
	if main.rain:
		main.rain.visible = false
		main.rain.emitting = false
	if main.hud:
		main.hud.visible = false
	if main.traffic:
		main.traffic.process_mode = Node.PROCESS_MODE_DISABLED
	cfg = Tuning.normalized(main.car.get_meta("garage_cfg", Tuning.default_cfg(_car_vehicle_id())))
	if not main.car.has_meta("garage_cfg"):
		cfg.variant = String(main.car.get_meta("livery", cfg.variant))
	entry_cfg = cfg.duplicate(true)
	_park(main.car)
	if not main.car.has_meta("garage_cfg"):
		# a car the garage did not build (the legacy hero export, --vehicle): rebuild it from the fleet glb so
		# the livery tables, wheels and body shell are the ones the customisation works on
		inside = true
		_rebuild()
		inside = false
	cam.current = true
	yaw = 0.7
	pitch = 0.18
	dist = 8.0
	_orbit(0.0)
	inside = true
	ui.show_menu(true)
	refresh()
	opened.emit()
	await _fade_to(0.0)
	busy = false


## The fleet id of the current player car (its physics id).
func _car_vehicle_id() -> String:
	if main.car and "P" in main.car and main.car.P.has("id"):
		var id := String(main.car.P.id)
		if not Fleet.find(id).is_empty():
			return id
	return ""


func leave(keep: bool) -> void:
	if not inside or busy:
		return
	busy = true
	await _fade_to(1.0)
	if keep:
		Tuning.save(cfg, save_path)
	elif JSON.stringify(cfg) != JSON.stringify(entry_cfg):
		var rebuild: bool = String(cfg.vehicle) != String(entry_cfg.vehicle)
		cfg = entry_cfg.duplicate(true)
		if rebuild:
			_rebuild()
		else:
			Tuning.apply(main.car, cfg)
	ui.show_menu(false)
	interior.visible = false
	main.world_env.environment = _saved.env
	for k in _saved:
		if String(k).begins_with("moon_"):
			_saved[k].visible = true
	if main.rain:
		main.rain.visible = _saved.rain
		main.rain.emitting = _saved.rain_emit
	if main.hud:
		main.hud.visible = _saved.hud
	if main.traffic:
		main.traffic.process_mode = Node.PROCESS_MODE_INHERIT
	var xf: Transform3D = current.exit_transform() if current else return_xf
	if not current:
		xf.origin += Vector3.UP * 0.4
	_unpark(main.car, xf)
	main.cam.current = true
	main.cam.snap()
	inside = false
	if current:
		current.rearm_later(2.5)
	closed.emit()
	await _fade_to(0.0)
	busy = false


func _park(c: RigidBody3D) -> void:
	_car_layers = Vector2i(c.collision_layer, c.collision_mask)
	c.collision_layer = 0
	c.collision_mask = 0
	c.freeze = true
	c.process_mode = Node.PROCESS_MODE_DISABLED
	c.linear_velocity = Vector3.ZERO
	c.angular_velocity = Vector3.ZERO
	c.global_transform = interior.car_transform()
	c.reset_physics_interpolation()


func _unpark(c: RigidBody3D, xf: Transform3D) -> void:
	main.stream_now(xf.origin)
	if main.town and main.town.has_method("ensure_collision"):
		main.town.ensure_collision(xf.origin, 30.0)
	c.collision_layer = _car_layers.x
	c.collision_mask = _car_layers.y
	c.process_mode = Node.PROCESS_MODE_INHERIT
	c.freeze = false
	c.place(xf)


func _fade_to(a: float) -> void:
	if _fade == null:
		return
	var tw := create_tween()
	tw.set_pause_mode(Tween.TWEEN_PAUSE_PROCESS)
	tw.tween_property(_fade, "color:a", a, 0.3)
	await tw.finished


static func _c(a) -> Color:
	return Color(a[0], a[1], a[2])


# ------------------------------------------------------------------ cars
## A player car for cfg (not installed yet): car.gd with the vehicle's glb + physics data.
func build_car(c: Dictionary) -> RigidBody3D:
	var v := Fleet.find(String(c.vehicle))
	var car := Car.new()
	car.name = "CarNew"
	main.add_child(car)
	car.setup(v.glb, v.json, v.id)
	return car


## Make `new_car` the player car at `xf` (camera, HUD, tach, traffic, collision streaming, signals).
func install_car(new_car: RigidBody3D, xf: Transform3D) -> void:
	var old: RigidBody3D = main.car
	if old == new_car:
		return
	new_car.town = main.town
	if old:
		new_car.wet = old.wet
		old.name = "CarOld"
		old.process_mode = Node.PROCESS_MODE_DISABLED
		old.queue_free()
	new_car.name = "Car"
	main.car = new_car
	if main.cam:
		main.cam.target = new_car
	if main.hud:
		main.hud.car = new_car
		for n in main.hud.find_children("*", "", true, false):
			if n.get_script() == preload("res://scripts/vehicle/tacho.gd"):
				n.car = new_car
		new_car.impact.connect(main.hud.on_impact)
	if main.cam:
		new_car.impact.connect(func(s: float): main.cam.shake(clampf(s / 400.0, 0.1, 1.0)))
		new_car.bump.connect(func(s: float): main.cam.shake(clampf(s * 0.08, 0.0, 0.3)))
	if main.town and "collision_focus" in main.town:
		main.town.collision_focus = new_car
	if main.traffic:
		new_car.collision_mask |= 2
		if "_hero_rid" in main.traffic:
			main.traffic._hero_rid = new_car.get_rid()
	if "damage" in main and main.damage and main.damage.has_method("set_hero"):
		main.damage.set_hero(new_car)
	for g in garages:
		g.set_meta("player", new_car)
	new_car.place(xf)


func _rebuild() -> void:
	var c := build_car(cfg)
	install_car(c, interior.car_transform() if inside else main.car.global_transform)
	if inside:
		_car_layers = Vector2i(c.collision_layer, c.collision_mask)
		c.collision_layer = 0
		c.collision_mask = 0
		c.freeze = true
		c.process_mode = Node.PROCESS_MODE_DISABLED
		c.global_transform = interior.car_transform()
	Tuning.apply(c, cfg)


# ------------------------------------------------------------------ menu
const ROWS := [
	["vehicle", "VEHICLE"], ["variant", "LIVERY"], ["paint", "PAINT"], ["finish", "FINISH"], ["tint", "WINDOW TINT"],
	["underglow", "UNDERGLOW"], ["rims", "RIMS"], ["rim_color", "RIM COLOUR"], ["drop", "RIDE HEIGHT"],
	["camber", "CAMBER"], ["lip", "FRONT LIP"], ["wing", "REAR WING"], ["lightbar", "LIGHT BAR"],
	["engine", "ENGINE"], ["brakes", "BRAKES"], ["tyres", "TYRES"], ["suspension", "SUSPENSION"], ["plate", "PLATE"],
]


func value_text(key: String) -> String:
	var v := Fleet.find(String(cfg.vehicle))
	match key:
		"vehicle":
			return String(v.name).get_slice(",", 0).to_upper()
		"variant":
			var vi := Fleet.variant_index(v, String(cfg.variant))
			return "%s  (%d/%d)" % [String(v.variants[vi].label).to_upper(), vi + 1, v.variants.size()]
		"paint":
			return _colour_name(cfg.paint.color) if bool(cfg.paint.on) else "LIVERY"
		"finish":
			return String(cfg.paint.finish).to_upper()
		"tint":
			return "%d%%" % int(round(float(cfg.tint) * 100.0)) if float(cfg.tint) > 0.0 else "CLEAR"
		"underglow":
			return _colour_name(cfg.underglow.color) if bool(cfg.underglow.on) else "OFF"
		"rims":
			var s := String(cfg.rims.style)
			return "STOCK" if s == "stock" else String(Fleet.find(s).get("name", s)).get_slice(" ", 1).to_upper() + " STYLE"
		"rim_color":
			return "STOCK" if cfg.rims.color == null else _colour_name(cfg.rims.color)
		"drop":
			return "STOCK" if float(cfg.stance.drop) <= 0.0 else "-%d CM" % int(round(float(cfg.stance.drop) * 100.0))
		"camber":
			return "%.1f°" % float(cfg.stance.camber)
		"lip", "wing", "lightbar":
			return "ON" if bool(cfg.kit[key]) else "OFF"
		"engine", "brakes", "tyres", "suspension":
			return Fleet.TuningFactors.NAMES[int(cfg.perf[key])]
		"plate":
			return String(cfg.plate)
	return ""


func _colour_name(a) -> String:
	var c := Tuning.col(a)
	for p in Tuning.PALETTE:
		if (p[1] as Color).is_equal_approx(c) or Tuning._arr(p[1]) == Tuning._arr(c):
			return p[0]
	return "CUSTOM #" + c.to_html(false).to_upper()


func _palette_step(a, on: bool, dir: int) -> Array:
	## -> [on, colour]: OFF / stock, then the palette
	var n := Tuning.PALETTE.size()
	var i := -1
	if on:
		for k in n:
			if Tuning._arr(Tuning.PALETTE[k][1]) == Tuning._arr(Tuning.col(a)):
				i = k
	i += dir
	if i < -1:
		i = n - 1
	if i >= n:
		i = -1
	return [i >= 0, Tuning._arr(Tuning.PALETTE[i][1]) if i >= 0 else a]


static func _cycle(arr: Array, cur, dir: int):
	var i := 0
	for k in arr.size():
		if is_equal_approx(float(arr[k]), float(cur)) if (arr[k] is float or arr[k] is int) else arr[k] == cur:
			i = k
	return arr[posmod(i + dir, arr.size())]


func step(key: String, dir: int) -> void:
	if not inside or busy or key == "":
		return
	var v := Fleet.find(String(cfg.vehicle))
	match key:
		"vehicle":
			var c := Fleet.catalogue()
			var nv: Dictionary = c[posmod(Fleet.index_of(String(cfg.vehicle)) + dir, c.size())]
			cfg.vehicle = nv.id
			cfg.variant = nv.default_variant
			_rebuild()
		"variant":
			var vi := posmod(Fleet.variant_index(v, String(cfg.variant)) + dir, v.variants.size())
			cfg.variant = v.variants[vi].name
		"paint":
			var r := _palette_step(cfg.paint.color, bool(cfg.paint.on), dir)
			cfg.paint.on = r[0]
			cfg.paint.color = r[1]
		"finish":
			cfg.paint.finish = _cycle(Tuning.FINISHES, String(cfg.paint.finish), dir)
		"tint":
			cfg.tint = _cycle(Tuning.TINTS, float(cfg.tint), dir)
		"underglow":
			var r := _palette_step(cfg.underglow.color, bool(cfg.underglow.on), dir)
			cfg.underglow.on = r[0]
			cfg.underglow.color = r[1]
		"rims":
			var styles := ["stock"] + Fleet.catalogue().map(func(x): return x.id).filter(func(x): return x != String(cfg.vehicle))
			cfg.rims.style = _cycle(styles, String(cfg.rims.style), dir)
		"rim_color":
			var r := _palette_step(cfg.rims.color if cfg.rims.color != null else [1, 1, 1], cfg.rims.color != null, dir)
			cfg.rims.color = r[1] if r[0] else null
		"drop":
			cfg.stance.drop = _cycle(Tuning.DROPS, float(cfg.stance.drop), dir)
		"camber":
			cfg.stance.camber = _cycle(Tuning.CAMBERS, float(cfg.stance.camber), dir)
		"lip", "wing", "lightbar":
			cfg.kit[key] = not bool(cfg.kit[key])
		"engine", "brakes", "tyres", "suspension":
			cfg.perf[key] = clampi(int(cfg.perf[key]) + dir, 0, 3)
		_:
			return
	if key != "vehicle":
		Tuning.apply(main.car, cfg)
	refresh()


## Direct setters (colour picker, plate field, tests).
func set_value(key: String, value) -> void:
	match key:
		"paint_color":
			cfg.paint.on = true
			cfg.paint.color = Tuning._arr(value)
		"underglow_color":
			cfg.underglow.on = true
			cfg.underglow.color = Tuning._arr(value)
		"plate":
			cfg.plate = String(value).to_upper().substr(0, 10)
		"cfg":
			var nv: bool = String(value.vehicle) != String(cfg.vehicle)
			cfg = Tuning.normalized(value)
			if nv:
				_rebuild()
				refresh()
				return
	Tuning.apply(main.car, cfg)
	refresh()


func refresh() -> void:
	if ui == null:
		return
	var v := Fleet.find(String(cfg.vehicle))
	var stock := Fleet.specs(v)
	var tuned := Fleet.specs(v, cfg.perf)
	ui.refresh(v, cfg, stock, tuned)
