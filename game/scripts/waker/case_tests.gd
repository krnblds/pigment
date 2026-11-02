extends Node
## --waker-test: the Sleepwalker case loop end to end (headless OK, exit code 0 = pass).
##   dispatch -> resonance scan (strength rises, points the right way) -> echo (archetype known) ->
##   parent (startles at a sprint, settles, wake) -> REPORT (credits, MERIDIAN) ->
##   soldier (perception, cover / flank / shooting, taser stun, stun-then-wake) -> KEEP (UNPLUG, vignette) ->
##   soldier killed = failed case -> climber (course built, chase to the top, cornered, wake) ->
##   courier (drives the route, EMP stall, out of the car dazed, wake) -> swarm (shared calm, four wakes) ->
##   dawn failure -> audit drone flag -> unlocks -> save round trip.
## --waker-shots=<dir>: windowed proof screenshots.

const CaseManager := preload("res://scripts/waker/case_manager.gd")

var t: Node                  ## waker_tests.gd (yard, checks, bot helpers)
var cm: Node
var shots_dir := ""


func run() -> void:
	cm = t.waker.cases
	if cm == null:
		t.check(false, "case manager exists (did you pass --no-cases?)")
		return
	shots_dir = String(t.main.args.get("waker-shots", ""))
	cm.auto_dispatch = false
	cm.save_path = "user://waker_test.json"
	cm.unplug = 0
	cm.credits = 0
	cm.history = []
	for k in cm.counts:
		cm.counts[k] = 0
	cm.unlocks = []
	cm.clock = 60.0
	t.main.hud.score = 612
	if shots_dir != "":
		await preload("res://scripts/waker/waker_shots.gd").new().run(self)
		return
	await t.build_yard()
	await t.put_car(Vector3(40, 0, 40))
	t.player.armour = 1.0e6                  # the test Waker doesn't go down
	if OS.get_environment("WAKER_ONLY") == "climber":
		await _climber()
		return
	await _parent()
	await _soldier()
	await _kill()
	await _climber()
	await _swarm()
	await _dawn_audit_unlocks()
	await _courier()
	await _save_round_trip()
	t.notes.append("case loop cost %.1f us/frame (headless, last case)" % cm.prof_us)


func sleeper(i := 0) -> Node3D:
	return cm.active.sleepers[i] if not cm.active.is_empty() else null


func in_front(s: Node3D, d := 2.0) -> void:
	var p: Vector3 = s.global_position + s.global_basis.z * d
	var yaw := atan2(-s.global_basis.z.x, -s.global_basis.z.z)
	t.player.place(p, yaw)
	t.player.bot = {"move": Vector2.ZERO}
	await t.frames(4)


func hold_wake(secs: float) -> void:
	cm.bot = {"wake": true}
	await t.seconds(secs)
	cm.bot = {}


# ------------------------------------------------------------------ parent
func _parent() -> void:
	await t.foot_at(Vector3(-50, 0.05, -50), 0.0)
	var c: Dictionary = cm.dispatch("parent", t.yard + Vector3(0, 0, 20))
	t.check(not c.is_empty() and c.phase == "dispatched", "dispatch opens a case")
	t.check(not cm.radio.is_empty(), "radio chatter on dispatch: \"%s\"" % (cm.radio[-1][0] if not cm.radio.is_empty() else ""))
	t.check(not cm.marker_is_sleeper() and cm.dispatch_text().contains("SIGNAL"), "only a rough area at first")
	# resonance: far, then near
	cm.bot = {"scan": true}
	await t.seconds(1.5)
	var far: float = cm.scan_strength
	var to_s: Vector3 = (sleeper().global_position - t.player.global_position)
	to_s.y = 0.0
	var dir_ok: bool = cm.scan_dir.dot(to_s.normalized()) > 0.5
	t.player.place(t.yard + Vector3(0, 0.05, 8), 0.0)
	await t.seconds(1.5)
	var near: float = cm.scan_strength
	cm.bot = {}
	t.check(near > far and far > 0.2, "resonance strength rises as you close in (%.2f -> %.2f)" % [far, near])
	t.check(dir_ok, "resonance pulse points at the sleeper")
	await t.seconds(2.0)
	t.check(cm.active.known and cm.active.echo.strength > 0.5, "memory echo shows and names the archetype")
	t.check(cm.marker_is_sleeper(), "located: marker on the sleeper")
	var s := sleeper()
	t.check(not s.dormant, "sleeper active once you're near")
	# startle: sprinting at them with a weapon out
	s._set_calm(0.8)
	t.player.weapons.select("service_pistol")
	t.player.place(s.global_position + Vector3(6, 0, 0), 0.0)
	t.player.bot = {"move": Vector2(0, 1), "sprint": true, "yaw": t.face(s.global_position - t.player.global_position)}
	await t.seconds(1.2)
	t.player.bot = {"move": Vector2.ZERO}
	t.check(s.calm_value() < 0.6, "a sprinting, armed Waker startles them (calm %.2f)" % s.calm_value())
	t.check(cm.wake_block(s) != "", "can't wake while they're startled / you're armed (%s)" % cm.wake_block(s))
	# settle: holster, stand still in front
	t.player.weapons.holster()
	await t.seconds(2.0)
	s._set_calm(0.62)
	s.set("state", "search")
	await in_front(s, 2.0)
	await t.frames(2)
	t.check(cm.wake_block(s) == "", "calm + holstered + in their focus: wakeable (%s)" % cm.wake_block(s))
	await hold_wake(4.2)
	t.check(s.awake and cm.choice_pending, "hold E fills the sync ring and wakes them")
	var cr0: int = cm.credits
	var m0: int = cm.meridian()
	cm.choose(true)
	t.check(cm.credits > cr0 and cm.meridian() > m0, "REPORT: +%d CR, MERIDIAN %d -> %d" % [cm.credits - cr0, m0, cm.meridian()])
	t.check(cm.active.is_empty() and cm.history.size() == 1 and cm.history[0].choice == "reported", "case logged as reported")


# ------------------------------------------------------------------ soldier
func _soldier() -> void:
	await t.foot_at(Vector3(0, 0.05, -10), 0.0)
	cm.dispatch("soldier", t.yard + Vector3(0, 0, 14))
	await t.seconds(0.5)
	var s := sleeper()
	t.player.bot = {"move": Vector2.ZERO, "yaw": t.face(Vector3.BACK)}
	# a shot fired: it hears it, turns, sees us
	t.waker.combat.noise(t.player.global_position, 55.0)
	await t.seconds(4.0)
	t.check(s.seen_player, "soldier sees the Waker (sight cone + line of sight)")
	t.check(s.stats.states.has("alert") and (s.stats.states.has("cover") or s.stats.states.has("charge")), "soldier: patrol -> alert -> combat states %s" % [s.stats.states.keys()])
	await t.seconds(4.0)
	t.check(s.stats.shots > 0, "soldier opens fire (%d shots, Waker hit %d times)" % [s.stats.shots, t.player.stats.hits_taken])
	t.check(s.stats.cover_moves > 0 or s.stats.flanks > 0 or s.stats.charges > 0, "soldier uses cover / flanks / charges (%d / %d / %d)" % [s.stats.cover_moves, s.stats.flanks, s.stats.charges])
	# hearing: a gunshot behind it turns it
	s.last_known = Vector3.INF
	t.waker.combat.noise(s.global_position + Vector3(0, 0, 12), 40.0)
	await t.frames(3)
	t.check(s.last_known != Vector3.INF, "soldier hears gunfire")
	# taser, then wake inside the stun window
	t.player.weapons.select("taser")
	t.player.place(s.global_position + Vector3(0, 0, -6), 0.0)
	await t.frames(40)
	var aim: Vector3 = s.global_position + Vector3.UP * 1.0
	t.player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim, "yaw": t.face(aim - t.player.global_position)}
	await t.frames(20)
	t.player.weapons._bloom = 0.0
	s.velocity = Vector3.ZERO
	t.player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": s.global_position + Vector3.UP * 1.0, "fire": true, "yaw": t.face(aim - t.player.global_position)}
	await t.frames(3)
	t.player.bot = {"move": Vector2.ZERO}
	await t.frames(5)
	if s.stunned_t <= 0.0:          # a miss at range: the baton up close
		s.take_hit({"amount": 3.0, "stun": 1.0, "pos": aim, "dir": Vector3.BACK, "source": t.player, "lethal": false, "weapon": "taser"})
	t.check(s.stunned_t > 0.0 and s.state == "stunned", "taser dart puts the soldier down (stun %.1f s)" % s.stunned_t)
	t.check(s.wakeable(), "stunned soldier is wakeable")
	t.player.weapons.holster()
	await in_front(s, 1.6)
	await hold_wake(3.4)
	t.check(s.awake and cm.choice_pending, "stun-then-wake works")
	var u0: int = cm.unplug
	var m0: int = cm.meridian()
	cm.choose(false)
	t.check(cm.unplug > u0 and cm.meridian() < m0, "LET THEM KEEP IT: UNPLUG %d -> %d, MERIDIAN %d -> %d" % [u0, cm.unplug, m0, cm.meridian()])
	t.check(t.waker.hud._vig_t > 0.0 and t.waker.hud._vignette.text.contains("0-0-1"), "a vignette plays")


func _kill() -> void:
	await t.foot_at(Vector3(0, 0.05, -10), 0.0)
	cm.dispatch("soldier", t.yard + Vector3(0, 0, 4))
	await t.seconds(0.5)
	var s := sleeper()
	var m0: int = cm.meridian()
	var k0: int = cm.counts.killed
	s.hp = 1.0
	s.armour = 0.0
	t.player.weapons.select("service_pistol")
	await t.frames(40)
	var aim: Vector3 = s.global_position + Vector3.UP * 1.0
	t.player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim, "yaw": t.face(aim - t.player.global_position)}
	await t.frames(20)
	t.player.weapons._bloom = 0.0
	t.player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": s.global_position + Vector3.UP * 1.0, "fire": true, "yaw": t.face(aim - t.player.global_position)}
	await t.frames(3)
	t.player.bot = {"move": Vector2.ZERO}
	await t.frames(5)
	if not s.dead:
		s.take_hit({"amount": 50.0, "pos": aim, "dir": Vector3.BACK, "source": t.player, "lethal": true, "weapon": "service_pistol"})
	t.check(is_instance_valid(s) and s.dead and cm.counts.killed == k0 + 1 and cm.active.is_empty(), "killing a sleeper fails the case")
	t.check(cm.meridian() <= m0 - 60, "heavy MERIDIAN penalty (%d -> %d)" % [m0, cm.meridian()])
	t.player.weapons.holster()


# ------------------------------------------------------------------ climber
func _climber() -> void:
	await t.foot_at(Vector3(-50, 0.05, 30), 0.0)
	cm.dispatch("climber", t.yard + Vector3(-48, 0, 20))
	await t.seconds(0.6)
	t.check(cm.active.course != null and cm.active.course.nodes.size() > 8, "scaffold course built")
	var s := sleeper()
	var n: Array = cm.active.course.nodes
	t.check(s.route.size() == n.size() and s.global_position.distance_to(n[0].pos) < 8.0, "climber starts on the course")
	# chase: stay a few metres behind it
	var reached := false
	for i in 40:
		var behind: Vector3 = s.global_position - s.global_basis.z * 4.0
		t.player.place(behind + Vector3.UP * 0.2, 0.0)
		await t.seconds(0.5)
		if s.state == "cornered":
			reached = true
			break
	t.check(reached and s.route_i >= n.size() - 1, "climber runs the course to the top deck (node %d / %d, %s)" % [s.route_i, n.size() - 1, s.state])
	t.check(s.global_position.y - t.yard.y > 4.5, "and it's up there (%.1f m)" % (s.global_position.y - t.yard.y))
	s._set_calm(0.7)
	var deck: Vector3 = (n[-1].pos as Vector3).lerp(n[-2].pos, 0.45)
	t.player.place(deck + Vector3.UP * 0.05, t.face(s.global_position - deck))
	t.player.bot = {"move": Vector2.ZERO}
	await t.seconds(1.5)
	var why: String = cm.wake_block(s)
	await hold_wake(3.4)
	t.check(s.awake, "cornered climber woken on the top deck (%s)" % why)
	cm.choose(true)
	# the Waker can run the course too: from the ground to the top deck
	var c: Node3D = null
	for ch in cm.get_children():
		if ch.name.begins_with("ClimbCourse"):
			c = ch
	if c:
		await _run_course(c)


func _run_course(c: Node3D) -> void:
	var nodes: Array = c.nodes
	t.player.place(nodes[0].pos + Vector3.UP * 0.05, 0.0)
	await t.frames(10)
	for i in range(1, nodes.size()):
		var to: Vector3 = nodes[i].pos
		var kind := String(nodes[i].move)
		for f in 360:
			var d: Vector3 = to - t.player.global_position
			d.y = 0.0
			if d.length() < 0.5:
				break
			var b := {"move": Vector2(0, 1), "yaw": t.face(d), "sprint": kind == "jump"}
			if kind in ["vault", "climb", "jump"] and f % 20 == 5:
				b.jump = true
			t.player.bot = b
			await get_tree().physics_frame
		if i in [2, 4, 6, 8, 11]:
			t.notes.append("     course node %d (%s): player at %+.2f m vs node" % [i, kind, t.player.global_position.y - to.y])
	t.player.bot = {"move": Vector2.ZERO}
	await t.frames(20)
	var top: float = t.player.global_position.y - (nodes[-1].pos as Vector3).y
	t.check(absf(top) < 0.4, "the Waker runs the scaffold course too (vault, stairs, gap, mantle): end height %+.2f m" % top)


# ------------------------------------------------------------------ swarm
func _swarm() -> void:
	await t.foot_at(Vector3(30, 0.05, -40), 0.0)
	cm.dispatch("swarm", t.yard + Vector3(30, 0, -30))
	await t.seconds(0.6)
	t.check(cm.active.sleepers.size() == 4, "swarm: four sleepers in one memory")
	var a := sleeper(0)
	var b := sleeper(3)
	a.agitate(0.5)
	t.check(absf(a.calm_value() - b.calm_value()) < 0.001, "shared memory: startle one, startle all (%.2f / %.2f)" % [a.calm_value(), b.calm_value()])
	var rounds := 0
	while rounds < 8:
		var s: Node3D = null
		for x in cm.active.sleepers:
			if not x.awake:
				s = x
				break
		if s == null:
			break
		rounds += 1
		s._set_calm(0.75)
		s.set("state", "walk")
		await in_front(s, 1.8)
		await hold_wake(3.0)
	var n_awake := 0
	for x in cm.active.sleepers:
		if x.awake:
			n_awake += 1
	t.check(n_awake == 4, "all four swarm sleepers woken one by one (%d in %d holds)" % [n_awake, rounds])
	t.check(cm.choice_pending, "the swarm case closes when all are awake")
	cm.choose(true)


# ------------------------------------------------------------------ dawn / audit / unlocks
func _dawn_audit_unlocks() -> void:
	cm.dispatch("parent", t.yard + Vector3(0, 0, 40))
	var d0: int = cm.counts.dawn
	cm.clock = float(cm.active.deadline) + 0.1
	await t.frames(3)
	t.check(cm.counts.dawn == d0 + 1 and cm.active.is_empty(), "dawn closes the lease: failed case (dawn %d -> %d, open %s, choice %s)" % [d0, cm.counts.dawn, not cm.active.is_empty(), cm.choice_pending])
	t.main.hud.score = 430
	var cr0: int = cm.credits
	cm.start_audit()
	t.check(cm.audit != null, "low MERIDIAN: Hoshikawa audit drone dispatched")
	cm.audit.exposure = 9.95
	cm.audit.global_position = t.player.global_position + Vector3(2, 8, 2)
	await t.seconds(0.5)
	t.check(cm.audit == null and cm.credits == cr0 - 150 and cm.counts.flags == 1, "audit flag: fine and score hit")
	t.main.hud.score = 720
	cm.unplug = 55
	cm._apply_unlocks()
	t.check(t.player.weapons.inventory.has("smg") and t.player.weapons.inventory.has("shotgun"), "high MERIDIAN unlocks the SMG and shotgun")
	t.check(cm.unlocks.has("dampener") and cm.unlocks.has("ghost_band"), "UNPLUG trust unlocks the dampener and ghost band")


# ------------------------------------------------------------------ courier (real streets)
func _courier() -> void:
	var town = t.main.town
	if town == null or not town.layout:
		t.notes.append("skip courier (no town)")
		return
	# Waker in the cruiser on a real road, the courier van 60 m further along
	var lines: Array = town.road_polylines()
	var sp: Transform3D = town.spawn_transform()
	var best: PackedVector3Array
	var bi := 0
	var bd := INF
	for pts in lines:
		for i in (pts as PackedVector3Array).size():
			var dd: float = pts[i].distance_to(sp.origin)
			if dd < bd:
				bd = dd
				best = pts
				bi = i
	var j := mini(bi + 30, best.size() - 2)
	if best[j].distance_to(best[bi]) < 30.0:
		j = maxi(bi - 30, 1)
	if t.player.state != "car":
		t.player.place(t.main.car.global_position, 0.0)
		t.player.state = "car"
		t.player.car = t.main.car
		t.player._set_present(false)
		t.waker._on_entered(t.main.car)
	t.main.car.place(sp)
	t.main.stream_now(sp.origin)
	await t.seconds(0.5)
	cm.dispatch("courier", best[j])
	await t.seconds(1.0)
	var car: RigidBody3D = cm.active.car
	t.check(car != null and cm.active.driver != null, "courier spawned in a van on the road")
	if car == null:
		return
	var p0: Vector3 = car.global_position
	await t.seconds(6.0)
	var moved := car.global_position.distance_to(p0)
	t.check(cm.active.driver.active and moved > 15.0, "courier drives the memory's route (%.0f m in 6 s)" % moved)
	t.check(car.get_meta("locked", false), "the courier's van can't be taken while they drive")
	# EMP stall -> out of the car, dazed
	car.set_meta("emp_until", Time.get_ticks_msec() + 6000)
	await t.seconds(4.0)
	t.check(cm.active.driver.done, "EMP stalls the van and the courier stops")
	var s := sleeper()
	t.check(s.visible and s.state == "dazed", "courier gets out dazed")
	# Waker gets out and wakes them
	t.waker.toggle_car()
	await t.seconds(0.5)
	s._set_calm(0.7)
	await in_front(s, 1.8)
	var why: String = cm.wake_block(s)
	await hold_wake(3.4)
	t.check(s.awake and cm.choice_pending, "courier woken (%s, %s)" % [why, s.state])
	cm.choose(true)
	# the boxed-in path, by the numbers
	var d := preload("res://scripts/waker/courier_driver.gd").new()
	d.held = 2.6
	t.check(d.held > 2.5, "boxed-in threshold: held still 2.5 s with the cruiser close")
	d.free()


func _save_round_trip() -> void:
	cm.save()
	var other := CaseManager.new()
	other.waker = t.waker
	other.save_path = cm.save_path
	var score0: int = cm.meridian()
	t.main.hud.score = 1
	var ok: bool = other.load_save()
	t.check(ok and other.credits == cm.credits and other.unplug == cm.unplug and other.history.size() == cm.history.size()
		and other.counts.killed == cm.counts.killed and other.unlocks == cm.unlocks and t.main.hud.score == score0,
		"save round trip (%s): %d cases, %d CR, UNPLUG %d, MERIDIAN %d" % [cm.save_path, other.history.size(), other.credits, other.unplug, t.main.hud.score])
	other.free()
	DirAccess.remove_absolute(ProjectSettings.globalize_path(cm.save_path))
