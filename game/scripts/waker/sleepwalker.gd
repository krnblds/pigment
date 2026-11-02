extends CharacterBody3D
## A Sleepwalker: a citizen awake and walking the city inside someone else's leased memory. Behaviour
## comes from the memory archetype (stories.gd ARCHETYPES):
##
##   parent   searches a small area calling a name; startles (calm drops, flees) at sprinting, a drawn
##            weapon, gunfire or the siren close by; wakeable once calm again
##   soldier  combat brain: patrol -> alert -> cover / flank / charge / hunt, fires at the Waker; stun
##            (taser, baton, EMP) puts them down for a few seconds, which is the window to wake them
##   climber  runs the scaffold course (climb_course.gd) ahead of you; cornered at the top it calms
##   courier  drives the memory's route (courier_driver.gd); once the car is boxed in or stalled it gets
##            out dazed and can be woken
##   swarm    walks with the others sharing the memory; agitation is shared (case.shared)
##
## Common: perception (sight cone + line of sight, hearing gunshots through combat.gd), calm 0..1,
## stun, hit reactions, health / armour with a headshot multiplier (limb-agnostic otherwise), death.
## Death uses the NPC workstream's ragdoll when it exists (see _death_hook) and the death clip otherwise.
## Layer 16 like the player; dormant (no physics) until the Waker is near enough for collision.

const PlayerBody := preload("res://scripts/player/player_body.gd")
const WeaponUser := preload("res://scripts/weapons/weapon_user.gd")
const Stories := preload("res://scripts/waker/stories.gd")
const NPC_RAGDOLL := "res://scripts/npc/character/ragdoll.gd"

signal died(s: Node)
signal woken(s: Node)

var archetype := "parent"
var case                                   ## case dictionary owner: case_manager.gd
var manager: Node
var shared: Dictionary = {}                ## swarm: {"calm": x, "members": [...]} shared by the group
var body: Node3D
var weapons: Node3D
var state := "idle"
var hp := 100.0
var armour := 0.0
var calm := 0.8
var stun_acc := 0.0
var stunned_t := 0.0
var stagger_t := 0.0
var awake := false
var dead := false
var dormant := true
var home := Vector3.ZERO
var route: Array = []                      ## parent / swarm waypoints, climber course nodes
var route_i := 0
var damage_scale := 0.45                   ## sleepers hit softer than the numbers on paper
var lethal_taken := 0.0
var nonlethal_only := true
var seen_player := false
var last_known := Vector3.INF
var stats := {"shots": 0, "hits_taken": 0, "cover_moves": 0, "flanks": 0, "charges": 0, "flees": 0, "states": {}}
var speech: Label3D

var _t := 0.0
var _think := 0.0
var _say_t := 3.0
var _cover := Vector3.INF
var _cover_t := 0.0
var _burst := 0
var _burst_t := 0.0
var _sight_t := 0.0
var _lost_t := 0.0
var _flee_from := Vector3.ZERO
var _seg_t := 0.0
var _seg_from := Vector3.ZERO
var _yaw := 0.0
var _wander_t := 0.0
var _move_speed := 0.0
var _ray := PhysicsRayQueryParameters3D.new()
var _avoid := 0.0
var _crouch := 0.0


func _ready() -> void:
	add_to_group("combatant")
	add_to_group("sleeper")
	collision_layer = 16
	collision_mask = 1 | 2 | 8
	floor_max_angle = deg_to_rad(50.0)
	floor_snap_length = 0.4
	var cs := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.3
	cap.height = 1.76
	cs.shape = cap
	cs.position.y = 0.88
	add_child(cs)
	body = PlayerBody.new()
	body.look = String(Stories.ARCHETYPES.get(archetype, {}).get("look", "civilian"))
	add_child(body)
	speech = Label3D.new()
	speech.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	speech.font_size = 34
	speech.pixel_size = 0.004
	speech.modulate = Color(0.55, 0.95, 1.0, 0.0)
	speech.outline_size = 8
	speech.position.y = 2.25
	speech.no_depth_test = false
	speech.visibility_range_end = 30.0
	add_child(speech)
	match archetype:
		"soldier":
			hp = 110.0
			armour = 30.0
			calm = 0.15
			weapons = WeaponUser.new()
			weapons.character = self
			weapons.body = body
			weapons.ai = true
			weapons.accuracy = 3.2
			weapons.infinite_reserve = true
			weapons.exclude = [get_rid()]
			add_child(weapons)
			weapons.give("service_pistol")
			weapons.select("service_pistol")
			state = "patrol"
		"climber":
			calm = 0.3
			state = "wait"
		"courier":
			calm = 0.2
			state = "driving"
		"swarm":
			calm = 0.7
			state = "walk"
		_:
			calm = 0.75
			state = "search"
	home = global_position
	_yaw = rotation.y
	set_dormant(true)


func set_dormant(on: bool) -> void:
	dormant = on
	set_physics_process(not on)
	if body:
		body.process_mode = Node.PROCESS_MODE_DISABLED if on else Node.PROCESS_MODE_INHERIT


func head_position() -> Vector3:
	return body.head_position() if body else global_position + Vector3.UP * 1.65


func forward() -> Vector3:
	return global_basis.z


func wakeable() -> bool:
	return not dead and not awake and state not in ["driving", "flee", "climb"] and (stunned_t > 0.0 or calm >= 0.6)


## Is the Waker inside the sleeper's focus cone (in front, within reach)? Stunned: any side.
func focus_ok(p: Vector3) -> bool:
	var to := p - global_position
	to.y = 0.0
	if to.length() > 3.6:
		return false
	if stunned_t > 0.0:
		return true
	return forward().dot(to.normalized()) > cos(deg_to_rad(65.0))


func say(text: String, seconds := 3.5) -> void:
	speech.text = text
	speech.set_meta("t", seconds)


func _state(s: String) -> void:
	if s == state:
		return
	state = s
	_t = 0.0
	stats.states[s] = int(stats.states.get(s, 0)) + 1


func calm_value() -> float:
	return float(shared.calm) if not shared.is_empty() else calm


func _set_calm(v: float) -> void:
	v = clampf(v, 0.0, 1.0)
	if not shared.is_empty():
		shared.calm = v
	calm = v


## Something upsetting happened near the sleeper: calm drops (shared across a swarm).
func agitate(amount: float, from := Vector3.INF) -> void:
	if dead or awake:
		return
	_set_calm(calm_value() - amount)
	if from != Vector3.INF:
		_flee_from = from


# ================================================================== damage
func take_hit(h: Dictionary) -> void:
	if dead:
		return
	var amt := float(h.get("amount", 0.0)) * (0.0 if awake else 1.0)
	var pos: Vector3 = h.get("pos", global_position)
	if not h.get("emp", false) and not h.get("melee", false) and pos.y > head_position().y - 0.16:
		h.headshot = true
		amt *= float(h.get("headshot_mult", 1.0))
	if bool(h.get("lethal", true)) and amt > 0.0:
		nonlethal_only = false
		lethal_taken += amt
		if armour > 0.0:
			var soak := minf(armour, amt * 0.5)
			armour -= soak
			amt -= soak
	hp -= amt
	stats.hits_taken += 1
	if manager and manager.has_method("on_sleeper_hit"):
		manager.on_sleeper_hit(self, h)
	if hp <= 0.0:
		h.killed = true
		_die(h)
		return
	var st := float(h.get("stun", 0.0))
	if st > 0.0:
		stun_acc += st
		if stun_acc >= 0.99:
			stun_acc = 0.0
			stunned_t = 7.0 if h.get("emp", false) else 6.0
			_set_calm(1.0)
			_state("stunned")
			body.play("hit")
			say("...", 2.0)
	else:
		stagger_t = 0.35
		body.play("hit")
	if archetype != "soldier":
		agitate(0.5, (h.get("source") as Node3D).global_position if h.get("source") is Node3D else Vector3.INF)
	else:
		last_known = (h.get("source") as Node3D).global_position if h.get("source") is Node3D else last_known
		seen_player = true


func _die(h: Dictionary) -> void:
	dead = true
	_state("dead")
	velocity = Vector3.ZERO
	collision_layer = 0
	if weapons:
		weapons.trigger(false)
		weapons.holster()
	_death_hook(h)
	speech.text = ""
	died.emit(self)


## NPC ragdoll API when the NPC workstream is merged (scripts/npc/character/ragdoll.gd with
## static func ragdoll(body: Node3D, skeleton: Skeleton3D, impulse: Vector3) -> bool), else the clip.
func _death_hook(h: Dictionary) -> void:
	if ResourceLoader.exists(NPC_RAGDOLL):
		var R = load(NPC_RAGDOLL)
		if R and R.has_method("ragdoll"):
			var imp: Vector3 = h.get("dir", Vector3.ZERO) * 4.0
			if R.ragdoll(self, body.skeleton, imp):
				return
	body.set_dead(true)


func wake() -> void:
	if awake or dead:
		return
	awake = true
	stunned_t = 0.0
	_state("awake")
	velocity = Vector3.ZERO
	if weapons:
		weapons.trigger(false)
		weapons.holster()
	body.set_look("civilian")
	body.set_aim(0.0, 0.0, 0.0)
	body.set_armed(false)
	say("...where... where am I?", 5.0)
	remove_from_group("combatant")
	woken.emit(self)


# ================================================================== per tick
func _physics_process(dt: float) -> void:
	if dormant:
		return
	_t += dt
	stunned_t = maxf(0.0, stunned_t - dt)
	stagger_t = maxf(0.0, stagger_t - dt)
	var player: Node3D = manager.waker.player if manager else null
	var pp: Vector3 = player.global_position if player else Vector3.INF
	if not dead and not awake:
		_perceive(player, dt)
	if dead:
		velocity.x = 0.0
		velocity.z = 0.0
	elif awake:
		_awake(dt, pp)
	elif state == "stunned" or stunned_t > 0.0:
		if state != "stunned":
			_state("stunned")
		_halt(dt)
		if stunned_t <= 0.0:
			_set_calm(0.15 if archetype == "soldier" else 0.4)
			_state("patrol" if archetype == "soldier" else ("search" if archetype == "parent" else _resume_state()))
	elif stagger_t > 0.0:
		_halt(dt)
	else:
		match archetype:
			"soldier":
				_soldier(dt, player)
			"climber":
				_climber(dt, pp)
			"courier":
				_courier(dt, pp)
			"swarm":
				_swarm(dt, pp)
			_:
				_parent(dt, pp)
	if state != "climb":
		if not is_on_floor():
			velocity.y -= 14.0 * dt
		else:
			velocity.y = minf(velocity.y, 0.0)
		move_and_slide()
	_animate(dt, pp)
	_speech(dt)


func _resume_state() -> String:
	match archetype:
		"climber":
			return "wait"
		"courier":
			return "dazed"
		"swarm":
			return "walk"
	return "search"


func _perceive(player: Node3D, dt: float) -> void:
	if player == null:
		return
	var p: Node = player
	var on_foot: bool = p.on_foot()
	var src: Vector3 = player.global_position if on_foot else (manager.waker.main.car.global_position if manager.waker.main.car else player.global_position)
	var d := global_position.distance_to(src)
	# sight
	var sees := false
	if d < 38.0:
		var to := src - global_position
		to.y = 0.0
		if to.length() < 2.0 or forward().dot(to.normalized()) > cos(deg_to_rad(75.0)):
			_ray.from = head_position()
			_ray.to = src + Vector3.UP * 1.4
			_ray.collision_mask = 1
			_ray.exclude = [get_rid()]
			var h := get_world_3d().direct_space_state.intersect_ray(_ray)
			sees = not h or (h.position as Vector3).distance_to(_ray.to) < 1.0
	if sees:
		_sight_t += dt
		last_known = src
		if _sight_t > 0.25:
			seen_player = true
	else:
		_sight_t = 0.0
	# hearing: gunshots / EMP within their radius
	var c = manager.waker.combat if manager else null
	if c:
		var n = c.heard(global_position, 600)
		if n != null:
			if archetype == "soldier":
				last_known = n
				seen_player = true
			else:
				agitate(dt * 1.2, n)
	# calm: a running, armed Waker or the siren up close is upsetting; a quiet one is not
	if archetype != "soldier" and on_foot and d < 12.0:
		var bad := 0.0
		if p.sprinting:
			bad += 0.35
		if p.weapon_drawn():
			bad += 0.25 if d < 8.0 else 0.1
		if p.aiming:
			bad += 0.3
		if bad > 0.0:
			agitate(bad * dt, src)
		elif p.speed() < 2.5:
			_set_calm(calm_value() + dt * 0.12)
	elif archetype != "soldier":
		_set_calm(calm_value() + dt * 0.05)
	if manager and manager.waker.main.car and manager.waker.siren and archetype != "soldier":
		if manager.waker.main.car.global_position.distance_to(global_position) < 25.0:
			agitate(dt * 0.4, manager.waker.main.car.global_position)
	calm = calm_value()


# ================================================================== movement
func _halt(dt: float) -> void:
	velocity.x = move_toward(velocity.x, 0.0, 12.0 * dt)
	velocity.z = move_toward(velocity.z, 0.0, 12.0 * dt)
	_move_speed = 0.0


func _go(target: Vector3, spd: float, dt: float, face := true) -> float:
	var to := target - global_position
	to.y = 0.0
	var d := to.length()
	if d < 0.15:
		_halt(dt)
		return d
	var dir := to / d
	# feelers: steer round what's in front
	_avoid = maxf(0.0, _avoid - dt)
	if is_on_wall() and _avoid <= 0.0:
		_avoid = 0.6
		set_meta("side", 1.0 if randf() < 0.5 else -1.0)
	if _avoid > 0.0:
		dir = dir.rotated(Vector3.UP, float(get_meta("side", 1.0)) * 1.1)
	var v := dir * minf(spd, d * 3.0)
	velocity.x = move_toward(velocity.x, v.x, 20.0 * dt)
	velocity.z = move_toward(velocity.z, v.z, 20.0 * dt)
	_move_speed = Vector2(velocity.x, velocity.z).length()
	if face:
		_face(dir, dt)
	return d


func _face(dir: Vector3, dt: float, rate := 8.0) -> void:
	if dir.length() < 0.01:
		return
	_yaw = lerp_angle(_yaw, atan2(dir.x, dir.z), 1.0 - exp(-dt * rate))
	rotation = Vector3(0, _yaw, 0)


func _ground(p: Vector3) -> Vector3:
	_ray.from = p + Vector3.UP * 3.0
	_ray.to = p + Vector3.DOWN * 6.0
	_ray.collision_mask = 1
	_ray.exclude = [get_rid()]
	var h := get_world_3d().direct_space_state.intersect_ray(_ray)
	return h.position if h else p


# ================================================================== parent
func _parent(dt: float, pp: Vector3) -> void:
	var c := calm_value()
	if state == "flee" or c < 0.12:
		if state != "flee":
			_state("flee")
			stats.flees += 1
			say(["No... no, stay away!", "Hana!"][randi() % 2], 2.5)
		var away := global_position - _flee_from
		away.y = 0.0
		if away.length() < 0.1:
			away = forward()
		_go(global_position + away.normalized() * 6.0, 4.2, dt)
		if _t > 4.0 and c > 0.3:
			home = global_position
			_state("search")
		return
	var near := pp != Vector3.INF and pp.distance_to(global_position) < 6.0
	if near and c >= 0.5:
		if state != "notice":
			_state("notice")
			say("Have you... have you seen her?", 3.0)
		_halt(dt)
		_face(pp - global_position, dt, 3.0)
		return
	if state == "notice":
		_state("search")
	_wander(dt, 18.0, 1.3)


func _wander(dt: float, radius: float, spd: float) -> void:
	_wander_t -= dt
	if route.is_empty() or _wander_t <= 0.0 or global_position.distance_to(route[0]) < 0.8:
		var a := randf() * TAU
		var r := randf_range(3.0, radius)
		route = [_ground(home + Vector3(cos(a) * r, 0, sin(a) * r))]
		_wander_t = randf_range(5.0, 9.0)
	if _wander_t > 7.5:
		_halt(dt)          # pause and look around
	else:
		_go(route[0], spd, dt)


# ================================================================== soldier (combat brain)
func _soldier(dt: float, player: Node3D) -> void:
	_think -= dt
	var p: Node = player
	var target: Vector3 = last_known
	var visible_now := _sight_t > 0.25
	var tpos: Vector3 = player.global_position if player else Vector3.INF
	var dist := global_position.distance_to(tpos) if tpos != Vector3.INF else INF
	if weapons:
		weapons.update(dt, (tpos + Vector3.UP * 1.25) if visible_now else global_position + forward() * 10.0 + Vector3.UP * 1.3, visible_now)
	match state:
		"patrol":
			_crouch = 0.0
			if route.is_empty():
				route = [home + Vector3(6, 0, 0), home + Vector3(6, 0, 6), home + Vector3(-4, 0, 4), home]
			if _go(route[route_i % route.size()], 1.4, dt) < 0.8:
				route_i += 1
			if seen_player:
				_state("alert")
				say(Stories.ARCHETYPES.soldier.lines[0], 2.5)
		"alert":
			_halt(dt)
			if target != Vector3.INF:
				_face(target - global_position, dt, 10.0)
			if _t > 0.5:
				_state("cover")
		"cover":
			if _think <= 0.0 or _cover == Vector3.INF:
				_think = 1.5
				var cv := _find_cover(target if target != Vector3.INF else global_position + forward() * 10.0)
				if cv != Vector3.INF and cv.distance_to(_cover) > 1.0:
					_cover = cv
					stats.cover_moves += 1
				elif cv == Vector3.INF and _cover == Vector3.INF and _t > 1.0:
					_state("flank")          # nothing to hide behind: work round the side
					stats.flanks += 1
					return
			if _cover != Vector3.INF and global_position.distance_to(_cover) > 0.6:
				_go(_cover, 4.0, dt, not visible_now)
				_crouch = 0.0
			else:
				_halt(dt)
				_cover_t += dt
				# peek and shoot, duck
				var peek := fmod(_cover_t, 3.0) < 1.8
				_crouch = 0.0 if peek else 1.0
			if visible_now:
				_face(tpos - global_position, dt, 10.0)
				_shoot(dt, p)
			if dist < 5.5 and visible_now:
				_state("charge")
				stats.charges += 1
				say("Get down!", 1.5)
			elif _t > 9.0 and (not visible_now or _cover_t > 8.0):
				_state("flank")
				stats.flanks += 1
				_cover_t = 0.0
			elif not visible_now and _t > 4.0 and _sight_t == 0.0 and _lost_t > 3.0:
				_state("hunt")
			_lost_t = 0.0 if visible_now else _lost_t + dt
		"flank":
			_crouch = 0.0
			if target == Vector3.INF:
				_state("hunt")
				return
			var side := (global_position - target)
			side.y = 0.0
			var fl := target + side.normalized().rotated(Vector3.UP, 1.3 * (1.0 if int(stats.flanks) % 2 == 0 else -1.0)) * clampf(side.length(), 6.0, 12.0)
			var d := _go(fl, 4.5, dt, not visible_now)
			if visible_now:
				_face(tpos - global_position, dt, 10.0)
				_shoot(dt, p)
			if d < 1.0 or _t > 6.0:
				_cover = Vector3.INF
				_state("cover")
		"charge":
			_crouch = 0.0
			_go(tpos, 5.0, dt)
			if dist < 1.8 and _t > 0.3:
				body.play("punch")
				if p.has_method("take_hit") and _burst_t <= 0.0:
					p.take_hit({"amount": 14.0 * damage_scale * 2.0, "stun": 0.25, "pos": tpos + Vector3.UP, "dir": (tpos - global_position).normalized(), "source": self, "lethal": true})
					_burst_t = 1.1
			_burst_t -= dt
			if _t > 3.0 or dist > 9.0:
				_cover = Vector3.INF
				_state("cover")
		"hunt":
			_crouch = 0.0
			if target == Vector3.INF or _go(target, 3.0, dt) < 1.2 or _t > 10.0:
				_state("patrol")
				seen_player = false
				route_i = 0
			if visible_now:
				_state("cover")


func _shoot(dt: float, p: Node) -> void:
	if weapons == null or p == null or not p.has_method("take_hit"):
		return
	if p.get("state") == "dead":
		weapons.trigger(false)
		return
	_burst_t -= dt
	if _burst_t <= 0.0:
		_burst = 3
		_burst_t = randf_range(0.9, 1.6)
	if _burst > 0 and fmod(_burst_t, 0.28) < dt * 1.5:
		weapons.trigger(true)
		weapons.trigger(false)
		_burst -= 1
		stats.shots += 1


## A spot near by with something solid between it and the threat at chest height.
func _find_cover(threat: Vector3) -> Vector3:
	var space := get_world_3d().direct_space_state
	var best := Vector3.INF
	var bd := INF
	_ray.collision_mask = 1
	_ray.exclude = [get_rid()]
	for r in [3.0, 6.0, 9.0]:
		for i in 10:
			var a: float = TAU * i / 10.0
			var c: Vector3 = global_position + Vector3(cos(a), 0, sin(a)) * r
			_ray.from = c + Vector3.UP * 2.5
			_ray.to = c + Vector3.DOWN * 3.0
			var g := space.intersect_ray(_ray)
			if not g:
				continue
			c = g.position
			if absf(c.y - global_position.y) > 1.2:
				continue
			_ray.from = c + Vector3.UP * 0.9
			_ray.to = threat + Vector3.UP * 1.3
			var h := space.intersect_ray(_ray)
			if h and (h.position as Vector3).distance_to(c) < 2.2:
				var score: float = c.distance_to(global_position) - c.distance_to(threat) * 0.15
				if score < bd:
					bd = score
					best = c
	return best


# ================================================================== climber
func _climber(dt: float, pp: Vector3) -> void:
	if route.is_empty():
		_wander(dt, 6.0, 1.2)
		return
	var near := pp != Vector3.INF and pp.distance_to(global_position) < 7.0
	match state:
		"wait":
			_halt(dt)
			if pp != Vector3.INF:
				_face(pp - global_position, dt, 4.0)
			if route_i >= route.size() - 1:
				_state("cornered")
				say("The view's better at the top.", 3.0)
			elif near or (pp != Vector3.INF and pp.distance_to(global_position) < 11.0 and calm_value() < 0.3):
				_state("climb")
				_seg_t = 0.0
				_seg_from = global_position
				if randf() < 0.5:
					say(Stories.ARCHETYPES.climber.lines[randi() % 4], 2.0)
		"climb":
			# kinematic run along the course: segment by segment, arcs for jumps / vaults / climbs
			var n: Dictionary = route[route_i + 1]
			var to: Vector3 = n.pos
			var kind := String(n.get("move", "run"))
			var spd := 5.6 if kind == "run" else 4.0
			var seg_len := maxf(_seg_from.distance_to(to), 0.1)
			_seg_t += dt * spd / seg_len
			var k := clampf(_seg_t, 0.0, 1.0)
			var p := _seg_from.lerp(to, k)
			if kind in ["jump", "vault", "climb"]:
				p.y += sin(k * PI) * (0.9 if kind == "jump" else 0.5) + (to.y - _seg_from.y) * (k * k - k) * 0.0
				if kind == "climb":
					p.y = lerpf(_seg_from.y, to.y, smoothstep(0.0, 0.6, k))
			global_position = p
			velocity = (to - _seg_from).normalized() * spd
			_move_speed = spd
			_face(to - _seg_from, dt, 12.0)
			if k >= 1.0:
				route_i += 1
				_seg_from = to
				_seg_t = 0.0
				velocity = Vector3.ZERO
				var still_near := pp != Vector3.INF and pp.distance_to(global_position) < 8.0
				if route_i >= route.size() - 1 or not still_near:
					_state("wait")
		"cornered":
			_halt(dt)
			if pp != Vector3.INF:
				_face(pp - global_position, dt, 3.0)
			_set_calm(calm_value() + dt * 0.08)


# ================================================================== courier
func _courier(dt: float, _pp: Vector3) -> void:  # _pp used below
	if state == "driving":
		return          # courier_driver.gd moves the car and carries us
	if state == "dazed" or state == "search":
		_set_calm(maxf(calm_value(), 0.65))
		if _pp_near(_pp, 5.0):
			_halt(dt)
			_face(_pp - global_position, dt, 3.0)
		else:
			_wander(dt, 5.0, 0.9)


func _pp_near(pp: Vector3, r: float) -> bool:
	return pp != Vector3.INF and pp.distance_to(global_position) < r


# ================================================================== swarm
func _swarm(dt: float, pp: Vector3) -> void:
	var c := calm_value()
	if c < 0.15:
		if state != "flee":
			_state("flee")
			stats.flees += 1
		var away := global_position - _flee_from
		away.y = 0.0
		_go(global_position + (away.normalized() if away.length() > 0.1 else forward()) * 5.0, 3.8, dt)
		if _t > 3.5:
			_state("walk")
		return
	if pp != Vector3.INF and pp.distance_to(global_position) < 4.5 and c >= 0.5:
		_halt(dt)
		_face(pp - global_position, dt, 3.0)
		return
	if route.is_empty():
		_wander(dt, 8.0, 1.0)
		return
	if _go(route[route_i % route.size()], 1.1, dt) < 1.0:
		route_i += 1


# ================================================================== awake / animation
func _awake(dt: float, pp: Vector3) -> void:
	_halt(dt)
	if pp != Vector3.INF and pp.distance_to(global_position) < 8.0:
		_face(pp - global_position, dt, 3.0)


func _animate(dt: float, _pp: Vector3) -> void:
	var hv := Vector3(velocity.x, 0, velocity.z)
	var along := hv.dot(forward())
	var crouch := 1.0 if state == "stunned" else _crouch
	body.set_locomotion(along, crouch, 0.0 if is_on_floor() or state == "climb" else 1.0)
	if weapons:
		var armed: bool = state in ["alert", "cover", "flank", "charge", "hunt"] and not weapons.is_holstered()
		body.set_armed(armed)
		var pitch := 0.0
		if armed and last_known != Vector3.INF:
			var to := last_known + Vector3.UP * 1.2 - head_position()
			pitch = atan2(to.y, Vector2(to.x, to.z).length())
		body.set_aim(1.0 if armed and _sight_t > 0.25 else 0.0, 0.0, clampf(pitch, -0.8, 0.8))


func _speech(dt: float) -> void:
	var t := float(speech.get_meta("t", 0.0)) - dt
	speech.set_meta("t", t)
	speech.modulate.a = clampf(t, 0.0, 1.0) * 0.9
	if dead or awake:
		return
	_say_t -= dt
	if _say_t <= 0.0 and state in ["search", "walk", "patrol", "wait", "dazed", "cornered"]:
		_say_t = randf_range(6.0, 11.0)
		var lines: Array = Stories.ARCHETYPES.get(archetype, {}).get("lines", [])
		if not lines.is_empty():
			say(lines[randi() % lines.size()], 3.5)
