extends Node
## Headless tests for the Waker layer (exit code 0 = pass) and the windowed proof shots.
##
##   --onfoot-test    walk / jog / sprint speeds, jump height, 25 deg slope up, 60 deg slope blocked, stairs,
##                    vault over a low wall, mantle onto a block, camera pulled in by a wall, out of and
##                    back into the car (it stays parked meanwhile)
##   --weapons-test   pistol body / head damage, reload, taser stun, baton, EMP radius stun, shotgun pellets,
##                    500 shots through the pools (no node growth), per-shot and per-frame cost
##   --waker-test     see case_tests.gd
##   --waker-shots=<dir>   windowed proof screenshots (see case_tests.gd)
##
## Everything runs on a test yard built 300 m above the spawn (StaticBody boxes on layer 1), so the town's
## streaming and traffic can't interfere.

var main: Node3D
var waker: Node3D
var player: CharacterBody3D
var fails: Array = []
var notes: Array = []
var yard := Vector3.ZERO
var _yard_node: Node3D


func _ready() -> void:
	name = "WakerTests"
	await get_tree().process_frame
	await get_tree().process_frame
	waker = main.waker
	player = waker.player
	if main.traffic:
		main.traffic.set("ignore_player", true)
	var ok := true
	if main.args.has("onfoot-test"):
		await _onfoot()
	elif main.args.has("weapons-test"):
		await _weapons()
	else:
		var ct := preload("res://scripts/waker/case_tests.gd").new()
		ct.t = self
		add_child(ct)
		await ct.run()
	ok = fails.is_empty()
	for n in notes:
		print("  ", n)
	if ok:
		print("WAKER TEST: PASS")
	else:
		for f in fails:
			print("  FAIL: ", f)
		print("WAKER TEST: FAIL (%d)" % fails.size())
	get_tree().quit(0 if ok else 1)


func check(cond: bool, what: String) -> void:
	if cond:
		notes.append("ok   " + what)
	else:
		fails.append(what)


func frames(n: int) -> void:
	for i in n:
		await get_tree().physics_frame


func seconds(s: float) -> void:
	await frames(int(s * Engine.physics_ticks_per_second))


func face(dir: Vector3) -> float:
	return atan2(-dir.x, -dir.z)


# ================================================================== yard
func box(size: Vector3, pos: Vector3, rot := Vector3.ZERO, col := Color(0.3, 0.32, 0.36)) -> StaticBody3D:
	var b := StaticBody3D.new()
	b.collision_layer = 1
	var cs := CollisionShape3D.new()
	var bs := BoxShape3D.new()
	bs.size = size
	cs.shape = bs
	b.add_child(cs)
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = size
	mi.mesh = bm
	var m := StandardMaterial3D.new()
	m.albedo_color = col
	m.roughness = 0.6
	mi.material_override = m
	b.add_child(mi)
	_yard_node.add_child(b)
	b.global_position = yard + pos
	b.rotation = rot
	return b


func build_yard() -> void:
	if _yard_node:
		return
	yard = main.car.global_position + Vector3(0, 300, 0)
	_yard_node = Node3D.new()
	_yard_node.name = "TestYard"
	add_child(_yard_node)
	box(Vector3(120, 1, 120), Vector3(0, -0.5, 0))
	# slopes along +X at z = 10 (25 deg) and z = 16 (60 deg)
	for s in [[25.0, 10.0], [60.0, 16.0]]:
		var a := deg_to_rad(s[0])
		var L := 8.0
		box(Vector3(L, 0.4, 3.0), Vector3(10 + cos(a) * L * 0.5, sin(a) * L * 0.5 - 0.2 * cos(a), s[1]), Vector3(0, 0, a))
	# stairs along +X at z = -10: 8 steps of 18 cm, 30 cm deep, then a landing
	for i in 8:
		box(Vector3(0.3, 0.18 * (i + 1), 3.0), Vector3(10.15 + i * 0.3, 0.09 * (i + 1), -10))
	box(Vector3(4.0, 1.44, 3.0), Vector3(14.4 + 0.0, 0.72, -10))
	# low wall to vault (90 cm) at x = -10, a 1.6 m block to mantle at x = -10, z = 10
	box(Vector3(0.3, 0.9, 4.0), Vector3(-10, 0.45, 0))
	box(Vector3(3.0, 1.6, 3.0), Vector3(-12, 0.8, 12))
	# a wall for the camera test at z = -30
	box(Vector3(12, 6, 0.4), Vector3(0, 3, -30))
	await frames(4)


func put_car(local: Vector3) -> void:
	var c: RigidBody3D = main.car
	c.place(Transform3D(Basis(), yard + local + Vector3.UP * 0.9))
	await frames(30)


func foot_at(local: Vector3, yaw := 0.0) -> void:
	if player.state == "car":
		player.exit_car(true)
	player.state = "foot"
	player.place(yard + local, yaw)
	player.bot = {"move": Vector2.ZERO}
	await frames(10)


func run_bot(move: Vector2, yaw_dir: Vector3, secs: float, extra := {}) -> void:
	var b := {"move": move, "yaw": face(yaw_dir)}
	b.merge(extra, true)
	player.bot = b
	await seconds(secs)
	player.bot = {"move": Vector2.ZERO, "yaw": face(yaw_dir)}


func hspeed() -> float:
	return Vector2(player.velocity.x, player.velocity.z).length()


# ================================================================== on foot
func _onfoot() -> void:
	await build_yard()
	await put_car(Vector3(0, 0, 30))
	# out of the car
	check(player.state == "car", "starts in the car")
	waker.toggle_car()
	await seconds(0.6)
	check(player.on_foot(), "F gets out (state %s)" % player.state)
	check(main.cam == waker.ots and waker.ots.current, "shoulder camera takes over")
	check(main.car.autopilot and main.car.input_handbrake, "car parked (brakes + handbrake)")
	await seconds(1.0)
	check(main.car.linear_velocity.length() < 0.3, "parked car stays put (%.2f m/s)" % main.car.linear_velocity.length())
	var car_pos: Vector3 = main.car.global_position
	# speeds on the flat
	await foot_at(Vector3(-30, 0.05, -10))
	for s in [["walk", {"walk": true}, player.WALK], ["jog", {}, player.JOG], ["sprint", {"sprint": true}, player.SPRINT]]:
		await foot_at(Vector3(-30, 0.05, -14))
		await run_bot(Vector2(0, 1), Vector3.RIGHT, 1.2, s[1])
		player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.RIGHT)}
		player.bot.merge(s[1], true)
		await frames(2)
		var v := hspeed()
		check(absf(v - float(s[2])) < 0.35, "%s speed %.2f m/s (want %.1f)" % [s[0], v, s[2]])
	player.bot = {}
	# jump height
	await foot_at(Vector3(-30, 0.05, 20))
	var y0 := player.global_position.y
	var top := y0
	player.bot = {"move": Vector2.ZERO, "jump": true}
	await frames(2)
	player.bot = {"move": Vector2.ZERO}
	for i in 120:
		await get_tree().physics_frame
		top = maxf(top, player.global_position.y)
	check(top - y0 > 0.75 and top - y0 < 1.3, "jump height %.2f m" % (top - y0))
	check(player.is_on_floor(), "lands again")
	# 25 deg slope: walks up
	await foot_at(Vector3(7, 0.05, 10))
	await run_bot(Vector2(0, 1), Vector3.RIGHT, 2.2)
	var up25 := player.global_position.y - yard.y
	check(up25 > 2.0, "walks up a 25 deg slope (rose %.2f m)" % up25)
	# 60 deg slope: can't
	await foot_at(Vector3(7, 0.05, 16))
	await run_bot(Vector2(0, 1), Vector3.RIGHT, 2.0)
	var up60 := player.global_position.y - yard.y
	check(up60 < 0.6, "60 deg slope blocks (rose %.2f m)" % up60)
	# stairs
	await foot_at(Vector3(8, 0.05, -10))
	var steps0: int = player.stats.steps
	await run_bot(Vector2(0, 1), Vector3.RIGHT, 1.6)
	var upst := player.global_position.y - yard.y
	check(upst > 1.35, "climbs stairs to the landing (%.2f m, %d steps)" % [upst, player.stats.steps - steps0])
	# vault the low wall (x = -10) going -X
	await foot_at(Vector3(-8.2, 0.05, 0))
	var v0: int = player.stats.vaults
	player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.LEFT)}
	await seconds(0.25)
	player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.LEFT), "jump": true}
	await frames(3)
	player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.LEFT)}
	await seconds(1.0)
	player.bot = {"move": Vector2.ZERO}
	check(player.stats.vaults > v0 and player.global_position.x < yard.x - 10.3, "vaults the 90 cm wall (x %.2f)" % (player.global_position.x - yard.x))
	# mantle onto the 1.6 m block (x -13.5..-10.5, z 10.5..13.5) going +Z
	await foot_at(Vector3(-12, 0.05, 9.3))
	var m0: int = player.stats.mantles
	player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.BACK)}
	await seconds(0.2)
	player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.BACK), "jump": true}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "yaw": face(Vector3.BACK)}
	await seconds(1.0)
	check(player.stats.mantles > m0 and player.global_position.y - yard.y > 1.5, "mantles onto the 1.6 m block (y %.2f)" % (player.global_position.y - yard.y))
	# camera collision: back to the wall at z = -30, camera would be behind it
	await foot_at(Vector3(0, 0.05, -28.9))
	player.bot = {"move": Vector2.ZERO, "yaw": face(Vector3.BACK)}
	await seconds(0.6)
	var cp: Vector3 = waker.ots.global_position
	check(cp.z - yard.z > -29.8, "camera stays in front of the wall (cam z %.2f, wall face -29.8)" % (cp.z - yard.z))
	# back into the car
	await foot_at(car_pos - yard + Vector3(-2.0, 0.05, 0.0))
	check(main.car.global_position.distance_to(car_pos) < 0.3, "car where we left it")
	waker.toggle_car()
	await seconds(1.2)
	check(player.state == "car", "F gets back in (state %s)" % player.state)
	check(main.cam == waker.chase and waker.chase.current, "chase camera back")
	check(not main.car.autopilot, "car drivable again")
	player.bot = {"move": Vector2(0, 1), "yaw": face(Vector3.RIGHT)}
	await seconds(1.0)
	main.car.place(Transform3D(Basis(), yard + Vector3(30, 0.9, 30)))
	waker.toggle_car()
	await seconds(0.8)
	player.bot = {"move": Vector2(0.3, 1), "yaw": face(Vector3.RIGHT)}
	await seconds(3.0)
	notes.append("on-foot cost: %s (headless, jogging)" % waker.cost_breakdown())


# ================================================================== weapons
class Dummy extends StaticBody3D:
	var hits: Array = []
	var hp := 100.0
	var stun := 0.0
	func _init() -> void:
		collision_layer = 16
		add_to_group("combatant")
		var cs := CollisionShape3D.new()
		var c := CapsuleShape3D.new()
		c.radius = 0.3
		c.height = 1.8
		cs.shape = c
		cs.position.y = 0.9
		add_child(cs)
	func head_position() -> Vector3:
		return global_position + Vector3.UP * 1.62
	func take_hit(h: Dictionary) -> void:
		var amt := float(h.get("amount", 0.0))
		var pos: Vector3 = h.get("pos", global_position)
		if pos.y > global_position.y + 1.45 and not h.get("melee", false) and not h.get("emp", false):
			h.headshot = true
			amt *= float(h.get("headshot_mult", 1.0))
		hp -= amt
		stun = maxf(stun, float(h.get("stun", 0.0)))
		h.dealt = amt
		hits.append(h)


func dummy(local: Vector3) -> Dummy:
	var d := Dummy.new()
	_yard_node.add_child(d)
	d.global_position = yard + local
	return d


func _weapons() -> void:
	await build_yard()
	await put_car(Vector3(30, 0, 30))
	await foot_at(Vector3(0, 0.05, 0), 0.0)
	var w = player.weapons
	var cw = waker.combat
	for id in ["smg", "shotgun"]:
		w.give(id)
	var d := dummy(Vector3(0, 0, 8))
	# pistol: body then head (aim exactly; spread off for the check)
	w.select("service_pistol")
	await frames(40)
	var aim_body: Vector3 = d.global_position + Vector3.UP * 1.0
	var aim_head: Vector3 = d.global_position + Vector3.UP * 1.62
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_body, "yaw": face(Vector3.BACK)}
	await frames(60)
	w._bloom = 0.0
	var mag0: int = w.ammo.service_pistol.mag
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_body, "fire": true, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_head, "yaw": face(Vector3.BACK)}
	await frames(40)
	check(d.hits.size() >= 1 and absf(float(d.hits[0].dealt) - 24.0) < 0.1, "pistol body shot 24 hp (%s)" % [d.hits[0].dealt if d.hits.size() > 0 else "miss"])
	check(w.ammo.service_pistol.mag == mag0 - 1, "one round used")
	var n0 := d.hits.size()
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_head, "fire": true, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_head, "yaw": face(Vector3.BACK)}
	await frames(10)
	var hs: Dictionary = d.hits[-1] if d.hits.size() > n0 else {}
	check(hs.get("headshot", false) and absf(float(hs.get("dealt", 0.0)) - 60.0) < 0.1, "headshot x2.5 = 60 hp (%s)" % [hs.get("dealt", "miss")])
	# reload
	w.ammo.service_pistol.mag = 2
	var res0: int = w.ammo.service_pistol.reserve
	w.reload()
	check(w.reloading(), "reload starts")
	await seconds(1.6)
	check(w.ammo.service_pistol.mag == 15 and w.ammo.service_pistol.reserve == res0 - 13, "reload fills the magazine from the reserve (%d / %d)" % [w.ammo.service_pistol.mag, w.ammo.service_pistol.reserve])
	# empty magazine: dry click, auto reload
	w.ammo.service_pistol.mag = 0
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_body, "fire": true, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_body, "yaw": face(Vector3.BACK)}
	check(w.reloading(), "empty trigger pull reloads")
	await seconds(1.6)
	# taser: stun, no lethal damage
	var t := dummy(Vector3(-3, 0, 9))
	w.select("taser")
	await frames(40)
	var aim_t: Vector3 = t.global_position + Vector3.UP * 1.0
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_t, "yaw": face(Vector3.BACK)}
	await frames(30)
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_t, "fire": true, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_t, "yaw": face(Vector3.BACK)}
	await frames(10)
	check(t.stun >= 1.0 and t.hits.size() == 1 and not bool(t.hits[0].lethal), "taser dart stuns (stun %.1f)" % t.stun)
	# baton: melee cone
	var bd := dummy(Vector3(0, 0, 1.5))
	w.select("stun_baton")
	await frames(30)
	player.bot = {"move": Vector2.ZERO, "fire": true, "aim_at": bd.global_position + Vector3.UP, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "yaw": face(Vector3.BACK)}
	await frames(10)
	check(bd.hits.size() == 1 and bd.stun > 0.4, "baton hit stuns (%d hits)" % bd.hits.size())
	bd.queue_free()
	await frames(2)
	# shotgun pellets
	var sg := dummy(Vector3(3, 0, 6))
	w.select("shotgun")
	await frames(40)
	var aim_s: Vector3 = sg.global_position + Vector3.UP * 1.0
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_s, "yaw": face(Vector3.BACK)}
	await frames(30)
	var shots0: int = cw.stats.shots
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_s, "fire": true, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "yaw": face(Vector3.BACK)}
	await frames(5)
	check(cw.stats.shots - shots0 == 8 and sg.hits.size() >= 3, "shotgun: 8 pellets, %d hit at 6 m" % sg.hits.size())
	# EMP: two dummies in the radius, one outside
	var e1 := dummy(Vector3(-6, 0, 14))
	var e2 := dummy(Vector3(-4, 0, 16))
	var e3 := dummy(Vector3(-6, 0, 26))
	w.select("emp")
	await frames(30)
	player.bot = {"move": Vector2.ZERO, "aim_at": yard + Vector3(-5, 0, 14.5), "fire": true, "yaw": face(Vector3.BACK)}
	await frames(3)
	player.bot = {"move": Vector2.ZERO, "yaw": face(Vector3.BACK)}
	await seconds(2.4)
	check(cw.stats.emp == 1, "EMP detonates after its fuse")
	check(e1.stun >= 1.0 and e2.stun >= 1.0 and e3.stun == 0.0, "EMP stuns inside 7.5 m only (%.1f %.1f %.1f)" % [e1.stun, e2.stun, e3.stun])
	check(w.ammo.emp.mag == 0 or w.ammo.emp.reserve < 3, "EMP charge used")
	# pools: 500 shots, no node growth
	w.select("smg")
	w.infinite_reserve = true
	await frames(30)
	var nodes0: int = cw.get_child_count()
	var obj0 := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	var t0 := Time.get_ticks_usec()
	var from: Vector3 = player.global_position + Vector3.UP * 1.4
	for i in 500:
		cw.hitscan(from, (Vector3(randf_range(-0.3, 0.3), randf_range(-0.2, 0.05), 1.0)).normalized(), w.defs().smg, player, [player.get_rid()])
		cw.muzzle_flash(from, Vector3.BACK)
		cw.eject_casing(from, Vector3.RIGHT)
	var per_shot := float(Time.get_ticks_usec() - t0) / 500.0
	await frames(10)
	var vis := 0
	for e in cw._tracers:
		if e.mi.visible:
			vis += 1
	check(cw.get_child_count() == nodes0, "pools: no new nodes after 500 shots (%d)" % cw.get_child_count())
	check(Performance.get_monitor(Performance.OBJECT_NODE_COUNT) - obj0 < 5, "scene node count flat (%+d)" % int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT) - obj0))
	check(vis <= cw.N_TRACERS, "tracers capped at the pool (%d live)" % vis)
	notes.append("hitscan + flash + casing: %.1f us per shot" % per_shot)
	# sustained fire cost: SMG auto for 3 s
	player.bot = {"move": Vector2.ZERO, "aim": true, "aim_at": aim_body, "fire": true, "yaw": face(Vector3.BACK)}
	var acc := 0.0
	var n := 0
	for i in 360:
		await get_tree().physics_frame
		acc += waker.combat_cost_us()
		n += 1
	player.bot = {"move": Vector2.ZERO}
	var avg := acc / n
	notes.append("sustained SMG fire: waker+combat %.1f us/frame (headless)" % avg)
	check(avg < 1500.0, "combat under 1.5 ms/frame (%.2f ms)" % (avg / 1000.0))
	check(cw.audio.played.get("smg_shot", 0) > 10 and cw.audio.bank.has("smg_shot"), "weapon sounds load and play")
