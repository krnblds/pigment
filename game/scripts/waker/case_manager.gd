extends Node
## Sleepwalker cases: the night shift of a Hoshikawa Waker.
##
##   dispatch   MERIDIAN pings a sleeper's Dreamlink signal: only a rough area (a circle on the HUD) and
##              a radio line. The night clock runs 22:00 -> 05:30; each case must close before dawn.
##   signal     hold Q (Resonance) for a soft directional pulse and the signal strength; drive and walk
##              to triangulate. Close in (or a strong signal) and the sleeper is located.
##   echo       near the sleeper the memory replays as cyan ghosts (echo.gd); it names the archetype.
##   behaviour  per archetype (sleepwalker.gd): search / soldier combat / climber chase / courier
##              pursuit (courier_driver.gd) / a swarm sharing one memory.
##   wake       close, inside their focus cone, walking, weapon away, while they're calm (or stunned):
##              hold E to fill the sync ring. Stun / EMP calms violent sleepers enough. Killing a sleeper
##              fails the case with heavy penalties.
##   choice     REPORT the fragment (Hoshikawa wipes it: credits + MERIDIAN) or LET THEM KEEP IT (UNPLUG
##              trust up, MERIDIAN down, a vignette of whose memories are being leased).
##   scores     MERIDIAN score is the main HUD's citizen score; UNPLUG trust and credits sit next to it.
##              They unlock kit (SMG / shotgun at high MERIDIAN; dampener / ghost band from UNPLUG), set the
##              dispatch tone and pace, and at a low MERIDIAN score Hoshikawa audits you (audit_drone.gd).
##   save       user://waker.json (--waker-save=<path>), a case log in the pause menu (TAB).
##
## Hooks: get_tree().call_group("npc_civilians", "on_incident", pos, radius) when a case is located (the
## NPC workstream's pedestrians can flee; nothing happens without them).

const Stories := preload("res://scripts/waker/stories.gd")
const Sleepwalker := preload("res://scripts/waker/sleepwalker.gd")
const Echo := preload("res://scripts/waker/echo.gd")
const ClimbCourse := preload("res://scripts/waker/climb_course.gd")
const CourierDriver := preload("res://scripts/waker/courier_driver.gd")
const AuditDrone := preload("res://scripts/waker/audit_drone.gd")
const CaseLog := preload("res://scripts/waker/case_log.gd")
const Car := preload("res://scripts/car.gd")
const TownLoader := preload("res://scripts/town_loader.gd")

const NIGHT_MIN := 450.0                 ## 22:00 -> 05:30
const NIGHT_SECONDS := 1500.0            ## real seconds per night
const ACTIVATE_R := 160.0
const VERSION := 1

var waker: Node
var save_path := "user://waker.json"
var prof_us := 0.0
var unplug := 0
var credits := 0
var case_no := 0
var history: Array = []                      ## newest last: {no, archetype, district, outcome, choice, credits, meridian, unplug, time}
var counts := {"woken": 0, "reported": 0, "kept": 0, "failed": 0, "killed": 0, "dawn": 0, "audits": 0, "flags": 0}
var unlocks: Array = []
var clock := 30.0                        ## minutes since 22:00
var cooldown := 25.0
var auto_dispatch := true                ## tests switch the loop off and dispatch by hand
var active := {}                         ## the open case (empty: none)
var radio: Array = []                    ## [[text, seconds left]]
var scan_active := false
var scan_strength := 0.0
var scan_dir := Vector3.ZERO
var scan_pulse_t := 0.0
var sync := 0.0
var choice_pending := false
var bot := {}                            ## tests: {"scan": bool, "wake": bool}
var audit: Node3D
var _audit_t := 120.0
var _sync_target: Node3D
var _scan_beep := 0.0
var _force_used := false
var _log_ui: CanvasLayer
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	name = "Cases"
	_rng.randomize()
	var a: Dictionary = waker.main.args
	if a.has("waker-save"):
		save_path = String(a["waker-save"])
	load_save()
	_apply_unlocks(true)
	_log_ui = CaseLog.new()
	_log_ui.manager = self
	add_child(_log_ui)


# ================================================================== scores
func meridian() -> int:
	var h = waker.main.hud
	return int(h.score) if h else 600


func adjust_meridian(points: int, reason: String) -> void:
	var h = waker.main.hud
	if h and h.has_method("adjust"):
		h.adjust(points, reason)
	_apply_unlocks()


func tone() -> String:
	var m := meridian()
	if m >= 680:
		return "corporate"
	if m < 480:
		return "cold"
	return "neutral"


func _apply_unlocks(quiet := false) -> void:
	var m := meridian()
	var want := []
	if m >= 640:
		want.append("smg")
	if m >= 700:
		want.append("shotgun")
	if unplug >= 25:
		want.append("dampener")
	if unplug >= 50:
		want.append("ghost_band")
	if unplug >= 75:
		want.append("unplug_livery")
	for u in want:
		if not unlocks.has(u):
			unlocks.append(u)
			if not quiet:
				waker.hud.toast("UNLOCKED: " + String({"smg": "HS-K SHRIKE SMG (MERIDIAN TRUST)", "shotgun": "MUKADE-12 SHOTGUN (MERIDIAN TRUST)",
					"dampener": "SYNC DAMPENER: FASTER WAKES (UNPLUG)", "ghost_band": "GHOST BAND: SHARPER RESONANCE (UNPLUG)",
					"unplug_livery": "UNPLUG LIVERY FOR THE GARAGE"}.get(u, u)), 4.0)
	for u in ["smg", "shotgun"]:
		if unlocks.has(u) and not waker.player.weapons.inventory.has(u):
			waker.player.weapons.give(u)


# ================================================================== input
func handle_input(e: InputEvent) -> bool:
	if choice_pending:
		if e.is_action_pressed("choice_report"):
			choose(true)
			return true
		if e.is_action_pressed("choice_keep"):
			choose(false)
			return true
	if e.is_action_pressed("case_log"):
		open_log()
		return true
	return false


func open_log() -> void:
	if _log_ui:
		_log_ui.open()


func _held(action: String, key: String) -> bool:
	if bot.has(key):
		return bool(bot[key])
	return InputMap.has_action(action) and Input.is_action_pressed(action)


# ================================================================== dispatch
func dispatch(archetype := "", at := Vector3.INF) -> Dictionary:
	if not active.is_empty():
		_close_case()
	case_no += 1
	if archetype == "":
		archetype = _pick_archetype()
	var home := at if at != Vector3.INF else _pick_location()
	var A: Dictionary = Stories.ARCHETYPES[archetype]
	var radius := 110.0 if meridian() < 650 else 80.0
	var off := Vector3(_rng.randf_range(-1, 1), 0, _rng.randf_range(-1, 1)).normalized() * _rng.randf_range(0.2, 0.6) * radius
	active = {"no": case_no, "archetype": archetype, "district": Stories.DISTRICTS[_rng.randi() % Stories.DISTRICTS.size()],
		"citizen": "%X%s-%04d %s" % [_rng.randi_range(1, 9), "ABCDEF"[_rng.randi() % 6], _rng.randi_range(1000, 9999), Stories.NAMES[_rng.randi() % Stories.NAMES.size()]],
		"home": home, "area": home + off, "radius": radius, "sleepers": [], "echo": null, "course": null, "car": null, "driver": null,
		"deadline": minf(clock + 150.0, NIGHT_MIN), "located": false, "known": false, "active": false, "woken": 0,
		"phase": "dispatched", "nonlethal": true, "pay": int(A.pay), "started": clock}
	_force_used = false
	var n := 4 if archetype == "swarm" else 1
	var shared := {"calm": 0.7} if archetype == "swarm" else {}
	for i in n:
		var s := Sleepwalker.new()
		s.archetype = archetype
		s.manager = self
		s.shared = shared
		s.name = "Sleeper_%d_%d" % [case_no, i]
		add_child(s)
		s.global_position = home + Vector3((i % 2) * 1.6 - 0.8, 0.2, (i / 2) * 1.6)
		s.home = s.global_position
		s.died.connect(_on_died)
		s.woken.connect(_on_woken)
		active.sleepers.append(s)
		if archetype == "courier":
			s.visible = false
	var ec := Echo.new()
	ec.name = "Echo_%d" % case_no
	add_child(ec)
	var road: Array = waker.main.town.nearest_road(home) if waker.main.town and waker.main.town.layout else [home, Vector3.FORWARD]
	ec.build(archetype, home, road[1])
	active.echo = ec
	var line: String = Stories.RADIO.dispatch[tone()][_rng.randi() % 2] % active.district
	_radio(line)
	waker.combat.audio.play("dispatch_beep", waker.player.global_position, 0.6)
	return active


func _pick_archetype() -> String:
	var pool := ["parent", "soldier", "climber", "courier"]
	if case_no > 3:
		pool.append("swarm")
	if meridian() < 520:
		pool.append("soldier")             # cold dispatch hands you the dangerous ones
	if unplug > 40:
		pool.append("parent")
	return pool[_rng.randi() % pool.size()]


## A road point 150-420 m from the Waker, shifted to the kerb side.
func _pick_location() -> Vector3:
	var from: Vector3 = waker.player.global_position
	var lines: Array = waker.main.town.road_polylines() if waker.main.town and waker.main.town.layout else []
	for attempt in 60:
		if lines.is_empty():
			break
		var pts: PackedVector3Array = lines[_rng.randi() % lines.size()]
		if pts.size() < 3:
			continue
		var i := _rng.randi_range(1, pts.size() - 2)
		var p := pts[i]
		var d := p.distance_to(from)
		if d < 150.0 or d > 420.0:
			continue
		var dir := (pts[i + 1] - pts[i - 1]).normalized()
		return p + Vector3.UP.cross(dir).normalized() * 5.5
	return from + Vector3(_rng.randf_range(-1, 1), 0, _rng.randf_range(-1, 1)).normalized() * 200.0


# ================================================================== activation (near enough for collision)
func _activate() -> void:
	active.active = true
	var town = waker.main.town
	var home: Vector3 = active.home
	if town and town.has_method("ensure_collision"):
		town.ensure_collision(home, 60.0)
	await get_tree().physics_frame
	await get_tree().physics_frame
	if active.is_empty():
		return
	var space: PhysicsDirectSpaceState3D = waker.get_world_3d().direct_space_state
	match String(active.archetype):
		"climber":
			_build_course(space)
		"courier":
			_spawn_courier()
	for s in active.sleepers:
		if active.archetype == "courier":
			continue
		var g := _ground(space, s.global_position)
		s.global_position = g + Vector3.UP * 0.05
		s.home = s.global_position
		if active.archetype == "swarm":
			var r: Array = waker.main.town.nearest_road(home) if town and town.layout else [home, Vector3.FORWARD]
			var d: Vector3 = (r[1] as Vector3).normalized()
			s.route = [g + d * 25.0, g - d * 5.0]
		s.set_dormant(false)


func _ground(space: PhysicsDirectSpaceState3D, p: Vector3) -> Vector3:
	var q := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 20.0, p + Vector3.DOWN * 30.0, 1)
	var h := space.intersect_ray(q)
	return h.position if h else p


func _build_course(space: PhysicsDirectSpaceState3D) -> void:
	var home: Vector3 = active.home
	var r: Array = waker.main.town.nearest_road(home) if waker.main.town and waker.main.town.layout else [home, Vector3.RIGHT]
	var road_dir: Vector3 = (r[1] as Vector3)
	road_dir.y = 0.0
	road_dir = road_dir.normalized() if road_dir.length() > 0.1 else Vector3.RIGHT
	var origin := _ground(space, home)
	var dir := road_dir
	var found := false
	for attempt in 16:
		var cand := origin + Vector3.UP.cross(road_dir) * (attempt % 4 - 1.5) * 2.0 + road_dir * (attempt / 4) * 6.0
		cand = _ground(space, cand)
		for dd in [road_dir, -road_dir]:
			if ClimbCourse.footprint_free(space, cand, dd):
				origin = cand
				dir = dd
				found = true
				break
		if found:
			break
	var c := ClimbCourse.new()
	c.name = "ClimbCourse_%d" % active.no
	add_child(c)
	c.build(origin, dir)
	active.course = c
	var s: Node3D = active.sleepers[0]
	s.global_position = c.nodes[0].pos
	s.route = c.nodes
	s.route_i = 0
	s.home = s.global_position


func _spawn_courier() -> void:
	var home: Vector3 = active.home
	var town = waker.main.town
	var r: Array = town.nearest_road(home) if town and town.layout else [home, Vector3.FORWARD]
	var vid := "hakobi"
	var glb := "res://assets/vehicles/%s/%s.glb" % [vid, vid]
	if not ResourceLoader.exists(glb):
		vid = "mame"
		glb = "res://assets/vehicles/%s/%s.glb" % [vid, vid]
	var car := Car.new()
	car.name = "CourierCar_%d" % active.no
	waker.main.add_child(car)
	if ResourceLoader.exists(glb):
		car.setup(glb, "res://assets/vehicles/%s/%s.json" % [vid, vid], vid)
	else:
		car.setup(waker.main.CAR_GLB, waker.main.CAR_JSON)
	car.town = town
	car.wet = waker.main.car.wet if waker.main.car else 1.0
	if waker.main.traffic:
		car.collision_mask |= 2
	car.place(TownLoader.car_transform(r[0], r[1]))
	car.set_meta("locked", true)            # can't be entered while the sleeper drives it
	if "damage" in waker.main and waker.main.damage and waker.main.damage.has_method("attach"):
		waker.main.damage.attach(car, true)
	var drv := CourierDriver.new()
	drv.name = "CourierDriver"
	car.add_child(drv)
	drv.setup(waker.main, car)
	drv.stopped.connect(_on_courier_stopped)
	active.car = car
	active.driver = drv
	var s: Node3D = active.sleepers[0]
	s.global_position = car.global_position
	s.set("state", "driving")


func _on_courier_stopped(reason: String) -> void:
	if active.is_empty() or active.car == null:
		return
	var car: RigidBody3D = active.car
	var s: Node3D = active.sleepers[0]
	var p: Vector3 = waker.player.exit_spot(car)
	s.global_position = p
	s.visible = true
	s.set("state", "dazed")
	s.home = p
	s.set_dormant(false)
	s.say("...the bridge was open... it was open...", 4.0)
	car.set_meta("locked", false)
	car.add_to_group("enterable_car")
	_radio("DISPATCH: Courier vehicle %s. Sleeper's out of the car, go easy." % reason)


# ================================================================== per frame
func _process(dt: float) -> void:
	var t0 := Time.get_ticks_usec()
	_clock(dt)
	for r in radio:
		r[1] -= dt
	while not radio.is_empty() and radio[0][1] <= 0.0:
		radio.pop_front()
	if active.is_empty():
		if auto_dispatch and not choice_pending:
			cooldown -= dt * (1.25 if waker.main.rain and waker.main.rain.emitting else 1.0)
			if cooldown <= 0.0:
				dispatch()
	else:
		_case_tick(dt)
	_scan(dt)
	_audit_tick(dt)
	prof_us = lerpf(prof_us, float(Time.get_ticks_usec() - t0), 0.05)


func _clock(dt: float) -> void:
	clock += dt * NIGHT_MIN / NIGHT_SECONDS
	if clock >= NIGHT_MIN:
		if not active.is_empty() and not choice_pending:
			_fail("dawn")
		_radio(Stories.RADIO.dawn[_rng.randi() % 2])
		clock = 0.0
		cooldown = 30.0
		_radio(Stories.RADIO.night[_rng.randi() % 2])
		save()


func clock_text(m: float) -> String:
	var t := int(m) + 22 * 60
	return "%02d:%02d" % [(t / 60) % 24, t % 60]


func _case_tick(dt: float) -> void:
	var p: Node3D = waker.player
	var viewer: Vector3 = p.global_position
	var home: Vector3 = active.home
	var focus := _focus_pos()
	if not active.active and viewer.distance_to(focus) < ACTIVATE_R:
		_activate()
	if active.echo:
		active.echo.tick(dt, viewer)
		if not active.known and active.echo.strength > 0.5:
			active.known = true
			active.located = true
			_radio(Stories.RADIO.located[_rng.randi() % 2] % String(Stories.ARCHETYPES[active.archetype].echo).replace("ECHO: ", ""))
			waker.hud.toast(String(Stories.ARCHETYPES[active.archetype].echo) + "  //  " + String(Stories.ARCHETYPES[active.archetype].brief), 6.0)
			get_tree().call_group("npc_civilians", "on_incident", home, 30.0)
			if active.echo.hum == null:
				active.echo.hum = waker.combat.audio.loop("echo_hum", active.echo, -10.0)
				active.echo.hum.play()
	if not active.located and viewer.distance_to(focus) < 45.0:
		active.located = true
	# the courier starts its run once you're close
	if active.driver and not active.driver.active and not active.driver.done and viewer.distance_to(active.car.global_position) < 120.0:
		active.driver.active = true
		_radio("DISPATCH: Sleeper is mobile, they're in a vehicle. Box them in.")
	if active.car and active.driver and not active.driver.done:
		var s0: Node3D = active.sleepers[0]
		s0.global_position = active.car.global_position
	if clock >= float(active.deadline) and not choice_pending:
		_fail("dawn")
		return
	_wake_tick(dt)


func _focus_pos() -> Vector3:
	if active.car and active.driver and not active.driver.done:
		return active.car.global_position
	for s in active.sleepers:
		if is_instance_valid(s) and not s.awake and not s.dead:
			return s.global_position
	return active.home


# ================================================================== resonance scan
func _scan(dt: float) -> void:
	var on := _held("scan", "scan") and not active.is_empty()
	scan_active = on
	if not on:
		_scan_beep = 0.0
		return
	scan_pulse_t += dt * 0.8
	var p: Vector3 = waker.player.global_position
	var tgt := _focus_pos()
	var d := p.distance_to(tgt)
	var s := pow(clampf(1.0 - d / 500.0, 0.0, 1.0), 1.6)
	# the signal breathes; a weak one wobbles in direction (sharper with the ghost band)
	s = clampf(s * (0.9 + 0.1 * sin(scan_pulse_t * 5.0)), 0.0, 1.0)
	scan_strength = lerpf(scan_strength, s, 1.0 - exp(-dt * 4.0))
	var wob := (1.0 - scan_strength) * (0.25 if unlocks.has("ghost_band") else 0.7)
	var dir := (tgt - p)
	dir.y = 0.0
	scan_dir = dir.normalized().rotated(Vector3.UP, sin(scan_pulse_t * 1.7) * wob)
	_scan_beep -= dt
	if _scan_beep <= 0.0:
		_scan_beep = lerpf(1.6, 0.35, scan_strength)
		waker.combat.audio.play("scan_pulse", p, 0.3 + 0.5 * scan_strength, 0.8 + 0.6 * scan_strength)
	if scan_strength > 0.85 and not active.is_empty():
		active.located = true


# ================================================================== waking
## The sleeper the sync ring is on (or the nearest one in reach).
func sync_target():
	if active.is_empty() or choice_pending:
		return null
	if _sync_target and is_instance_valid(_sync_target) and not _sync_target.awake and not _sync_target.dead:
		return _sync_target
	var p: Vector3 = waker.player.global_position
	var best = null
	var bd := INF
	for s in active.sleepers:
		if not is_instance_valid(s) or s.awake or s.dead or not s.visible:
			continue
		var d: float = s.global_position.distance_to(p)
		if d > 6.0:
			continue
		var score := d + (0.0 if wake_block(s) == "" else 10.0)     # prefer the one you can wake right now
		if score < bd:
			bd = score
			best = s
	return best


## Why the wake can't happen right now ("" = it can).
func wake_block(s: Node3D) -> String:
	var p = waker.player
	if not p.on_foot():
		return "GET OUT OF THE CAR"
	if s.global_position.distance_to(p.global_position) > 3.6:
		return "GET CLOSER"
	if p.weapon_drawn():
		return "HOLSTER YOUR WEAPON  [H]"
	if p.sprinting or p.speed() > 2.6:
		return "SLOW DOWN  [ALT WALK]"
	if not s.focus_ok(p.global_position):
		return "STAND WHERE THEY CAN SEE YOU"
	if not s.wakeable():
		return "TOO AGITATED  -  WAIT, OR STUN THEM" if s.archetype == "soldier" or s.calm_value() < 0.3 else "LET THEM SETTLE"
	return ""


func _wake_tick(dt: float) -> void:
	var s = sync_target()
	if s == null:
		sync = maxf(0.0, sync - dt)
		_sync_target = null
		return
	var block := wake_block(s)
	var holding := _held("wake", "wake")
	if holding and block == "":
		_sync_target = s
		var t := float(Stories.ARCHETYPES[active.archetype].wake_time) / (1.4 if unlocks.has("dampener") else 1.0)
		sync += dt / t
		if not s.has_meta("hum"):
			var h: AudioStreamPlayer3D = waker.combat.audio.loop("wake_sync", s, -8.0)
			h.play()
			s.set_meta("hum", h)
		if sync >= 1.0:
			sync = 0.0
			_sync_target = null
			_stop_hum(s)
			s.wake()
	else:
		sync = maxf(0.0, sync - dt * (0.6 if holding else 0.35))
		if sync <= 0.0:
			_sync_target = null
			_stop_hum(s)


func _stop_hum(s: Node) -> void:
	if s.has_meta("hum"):
		var h = s.get_meta("hum")
		if is_instance_valid(h):
			h.queue_free()
		s.remove_meta("hum")


func _on_woken(s: Node3D) -> void:
	if active.is_empty():
		return
	active.woken += 1
	counts.woken += 1
	waker.combat.audio.play("wake_chime", s.global_position, 0.8)
	for o in active.sleepers:
		if o != s and is_instance_valid(o) and not o.awake:
			o._set_calm(o.calm_value() + 0.3)     # one waking settles the others in a shared memory
	var left := 0
	for o in active.sleepers:
		if is_instance_valid(o) and not o.awake and not o.dead:
			left += 1
	if left == 0:
		_radio(Stories.RADIO.woken[_rng.randi() % 2])
		choice_pending = true
		active.phase = "choice"
		active.fragment = Stories.FRAGMENTS[active.archetype][active.no % 3]
	else:
		waker.hud.toast("%d MORE IN THE MEMORY" % left)


func on_sleeper_hit(s: Node3D, h: Dictionary) -> void:
	if active.is_empty() or h.get("source") != waker.player:
		return
	if bool(h.get("lethal", true)) and float(h.get("amount", 0.0)) > 0.0:
		active.nonlethal = false
		adjust_meridian(-4, "EXCESSIVE FORCE")
	elif s.archetype != "soldier" and not _force_used:
		_force_used = true
		adjust_meridian(-6, "UNNECESSARY FORCE")


func _on_died(_s: Node3D) -> void:
	if active.is_empty():
		return
	_fail("killed")


# ================================================================== resolution
func choice_text() -> String:
	if active.is_empty():
		return ""
	return "THE SLEEPER IS HOLDING A FRAGMENT OF THE LEASED MEMORY:\n\"%s\"\n\n[1]  REPORT  -  Hoshikawa wipes it.  +%d CR, MERIDIAN up\n[2]  LET THEM KEEP IT  -  UNPLUG trust up, MERIDIAN down" % [String(active.get("fragment", "")), _pay()]


func _pay() -> int:
	if active.is_empty():
		return 0
	var p := int(active.pay)
	if active.nonlethal:
		p += 150
	var left := float(active.deadline) - clock
	p += int(clampf(left / 150.0, 0.0, 1.0) * 120.0)
	return p


func choose(report: bool) -> void:
	if not choice_pending or active.is_empty():
		return
	choice_pending = false
	var e := _entry("woken")
	if report:
		var pay := _pay()
		credits += pay
		counts.reported += 1
		adjust_meridian(15 + (10 if active.nonlethal else 0), "FRAGMENT REPORTED")
		_radio(Stories.RADIO.reported[_rng.randi() % 2])
		e.choice = "reported"
		e.credits = pay
	else:
		counts.kept += 1
		unplug = clampi(unplug + 12, 0, 100)
		adjust_meridian(-20, "INCOMPLETE REPORT")
		_radio(Stories.RADIO.kept[_rng.randi() % 2])
		_radio(Stories.RADIO.unplug[_rng.randi() % Stories.RADIO.unplug.size()])
		var vi := mini(counts.kept - 1, Stories.VIGNETTES.size() - 1)
		waker.hud.vignette(Stories.VIGNETTES[vi])
		e.choice = "kept"
		e.vignette = vi
	e.meridian = meridian()
	e.unplug = unplug
	history.append(e)
	_apply_unlocks()
	_close_case()
	save()


func _fail(why: String) -> void:
	var e := _entry(why)
	counts.failed += 1
	match why:
		"killed":
			counts.killed += 1
			adjust_meridian(-60, "CITIZEN TERMINATED")
			credits -= 250
			unplug = clampi(unplug - 8, 0, 100)
			_radio(Stories.RADIO.failed_kill[_rng.randi() % 2])
		_:
			counts.dawn += 1
			adjust_meridian(-10, "LEASE LOST AT DAWN")
			_radio(Stories.RADIO.failed_dawn[_rng.randi() % 2])
	e.credits = -250 if why == "killed" else 0
	e.meridian = meridian()
	e.unplug = unplug
	history.append(e)
	choice_pending = false
	_close_case()
	save()


func _entry(outcome: String) -> Dictionary:
	return {"no": int(active.get("no", case_no)), "archetype": String(active.get("archetype", "")), "district": String(active.get("district", "")),
		"citizen": String(active.get("citizen", "")), "outcome": outcome, "choice": "", "credits": 0, "nonlethal": bool(active.get("nonlethal", true)),
		"time": clock_text(clock)}


func _close_case() -> void:
	if active.is_empty():
		return
	var keep: Array = []
	for s in active.sleepers:
		if is_instance_valid(s):
			_stop_hum(s)
			if s.awake or s.dead:
				keep.append(s)
			else:
				s.queue_free()
	# woken sleepers walk off and fade after a while
	for s in keep:
		get_tree().create_timer(25.0).timeout.connect(func(): if is_instance_valid(s): s.queue_free())
	if active.echo and is_instance_valid(active.echo):
		active.echo.queue_free()
	if active.course and is_instance_valid(active.course):
		var c: Node = active.course
		get_tree().create_timer(30.0).timeout.connect(func(): if is_instance_valid(c): c.queue_free())
	if active.car and is_instance_valid(active.car):
		var car: RigidBody3D = active.car
		if active.driver and is_instance_valid(active.driver):
			active.driver.queue_free()
		car.set_meta("locked", false)
		if car != waker.main.car:
			waker.park(car)
			car.add_to_group("enterable_car")
	active = {}
	sync = 0.0
	_sync_target = null
	var m := meridian()
	cooldown = 60.0 * (0.75 if m >= 700 else (1.5 if m < 500 else 1.0)) * (1.2 if unplug > 60 else 1.0)


# ================================================================== audits (low MERIDIAN)
func _audit_tick(dt: float) -> void:
	if audit:
		return
	if meridian() >= 450:
		_audit_t = 120.0
		return
	_audit_t -= dt
	if _audit_t > 0.0:
		return
	_audit_t = 240.0
	start_audit()


func start_audit() -> void:
	if audit:
		return
	counts.audits += 1
	audit = AuditDrone.new()
	audit.target = waker.player
	add_child(audit)
	var p: Vector3 = waker.player.global_position
	audit.global_position = p + Vector3(40, 25, 0).rotated(Vector3.UP, _rng.randf() * TAU)
	audit.finished.connect(_on_audit)
	_radio(Stories.RADIO.audit[_rng.randi() % 2])
	waker.combat.audio.loop("audit_drone", audit, -6.0).play()


func _on_audit(flagged: bool) -> void:
	if flagged:
		counts.flags += 1
		credits -= 150
		adjust_meridian(-10, "AUDIT FLAG")
		_radio(Stories.RADIO.audit_flag[_rng.randi() % 2])
	else:
		_radio(Stories.RADIO.audit_clear[_rng.randi() % 2])
	var a := audit
	audit = null
	if is_instance_valid(a):
		a.queue_free()
	save()


# ================================================================== HUD text
func _radio(text: String) -> void:
	radio.append([text, 9.0])
	if radio.size() > 4:
		radio.pop_front()


func dispatch_text() -> String:
	var head := "MERIDIAN DISPATCH  //  %s  //  DAWN %s" % [clock_text(clock), clock_text(NIGHT_MIN)]
	if active.is_empty():
		if choice_pending:
			return head
		return head + "\nNO OPEN CASE  -  NEXT PING IN ~%ds" % int(maxf(cooldown, 0.0))
	var A: Dictionary = Stories.ARCHETYPES[active.archetype]
	var lines := [head, "CASE %04d  SLEEPER %s" % [active.no, active.citizen]]
	lines.append("AREA: %s   %s" % [active.district, "LOCATED" if active.located else "SIGNAL ~%d m" % int(active.radius)])
	lines.append(String(A.echo) if active.known else "MEMORY: UNKNOWN  -  FIND THE ECHO")
	lines.append("CLOSE BEFORE %s   [Q] RESONANCE" % clock_text(float(active.deadline)))
	return "\n".join(lines)


func prompt() -> String:
	if choice_pending or active.is_empty():
		return ""
	var s = sync_target()
	if s == null:
		return ""
	var b := wake_block(s)
	if b == "":
		return "HOLD E   WAKE  (%d%%)" % int(sync * 100.0) if sync > 0.0 else "HOLD E   WAKE"
	return b


func marker_position():
	if active.is_empty():
		return null
	if active.located:
		return _focus_pos() + Vector3.UP * 2.2
	return active.area


func marker_is_sleeper() -> bool:
	return not active.is_empty() and bool(active.located)


func marker_label() -> String:
	return "SLEEPER" if marker_is_sleeper() else "SIGNAL AREA"


func area_radius_px(cam: Camera3D, vp: Vector2) -> float:
	if active.is_empty():
		return 0.0
	var d := cam.global_position.distance_to(active.area)
	return float(active.radius) / maxf(d, 1.0) * (vp.y * 0.5) / tan(deg_to_rad(cam.fov) * 0.5)


# ================================================================== save
func save() -> void:
	var d := {"version": VERSION, "meridian": meridian(), "unplug": unplug, "credits": credits, "case_no": case_no, "clock": clock,
		"counts": counts, "unlocks": unlocks, "log": history.slice(maxi(0, history.size() - 200))}
	var f := FileAccess.open(save_path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(d, "  "))


func load_save() -> bool:
	if not FileAccess.file_exists(save_path):
		return false
	var d = JSON.parse_string(FileAccess.get_file_as_string(save_path))
	if not (d is Dictionary):
		return false
	unplug = int(d.get("unplug", 0))
	credits = int(d.get("credits", 0))
	case_no = int(d.get("case_no", 0))
	clock = float(d.get("clock", 30.0))
	var c: Dictionary = d.get("counts", {})
	for k in c:
		counts[k] = int(c[k])
	unlocks = Array(d.get("unlocks", []))
	history = Array(d.get("log", []))
	var h = waker.main.hud
	if h and d.has("meridian"):
		h.score = int(d.meridian)
	return true
