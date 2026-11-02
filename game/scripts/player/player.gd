extends CharacterBody3D
## The Waker on foot: third-person controller (walk / jog / sprint, crouch, jump, vault and mantle low
## obstacles, slopes, step-up for stairs), aiming and firing through weapon_user.gd, health / armour,
## hit reactions, death and respawn, and getting in and out of cars.
##
## Faces +Z (global_basis.z = forward, like the cars and the character model). Collision layer 16
## (characters), mask 1 | 2 | 8 (world, traffic, debris). Input comes from the actions waker.gd
## registers; tests drive it through `bot` (a Dictionary of fake inputs) instead.

const PlayerBody := preload("res://scripts/player/player_body.gd")
const WeaponUser := preload("res://scripts/weapons/weapon_user.gd")

signal damaged(from_dir: Vector3, amount: float)
signal died
signal respawned
signal entered_car(car: Node)
signal exited_car(car: Node)

const WALK := 1.7
const JOG := 4.2
const SPRINT := 6.8
const CROUCH := 1.9
const AIM_WALK := 2.4
const ACCEL := 16.0
const AIR_ACCEL := 3.0
const GRAVITY := 14.0
const JUMP_V := 5.0
const STEP := 0.42
const RADIUS := 0.32
const HEIGHT := 1.78
const MAX_HEALTH := 100.0
const MAX_ARMOUR := 60.0

var waker: Node                         ## waker.gd (main, camera, stations)
var cam: Camera3D                       ## ots_camera.gd
var body: Node3D                        ## player_body.gd
var weapons: Node3D                     ## weapon_user.gd
var state := "car"                      ## foot | car | vault | enter | exit | dead
var car: RigidBody3D                    ## the car we're in (state car)
var health := MAX_HEALTH
var armour := MAX_ARMOUR
var aiming := false
var crouching := false
var sprinting := false
var walking := false
var stunned := 0.0
var bot := {}                           ## tests: {"move": Vector2, "sprint", "jump", "aim", "fire", "crouch", "walk"}
var input_enabled := true
var aim_point := Vector3.ZERO
var prof_us := 0.0                      ## running average of the controller + animation driving cost (µs)
var stats := {"jumps": 0, "vaults": 0, "mantles": 0, "steps": 0, "enters": 0, "exits": 0, "deaths": 0, "hits_taken": 0}

var _shape: CollisionShape3D
var _capsule := CapsuleShape3D.new()
var _yaw := 0.0
var _anim_t := 0.0
var _t := 0.0
var _from := Vector3.ZERO
var _mid := Vector3.ZERO
var _to := Vector3.ZERO
var _dur := 0.5
var _since_hit := 99.0
var _fire_face := 0.0
var _jump_buf := 0.0
var _coyote := 0.0
var _dead_t := 0.0
var _air := 0.0
var _crouch_s := 0.0
var _enter_car: RigidBody3D
var _ray := PhysicsRayQueryParameters3D.new()
var _shape_q := PhysicsShapeQueryParameters3D.new()


func _ready() -> void:
	name = "Player"
	add_to_group("combatant")
	add_to_group("player")
	collision_layer = 16
	collision_mask = 1 | 2 | 8
	floor_max_angle = deg_to_rad(48.0)
	floor_snap_length = 0.45
	floor_constant_speed = true
	floor_block_on_wall = true
	safe_margin = 0.02
	_capsule.radius = RADIUS
	_capsule.height = HEIGHT
	_shape = CollisionShape3D.new()
	_shape.shape = _capsule
	_shape.position.y = HEIGHT * 0.5
	add_child(_shape)
	body = PlayerBody.new()
	body.name = "Body"
	body.look = "waker"
	add_child(body)
	weapons = WeaponUser.new()
	weapons.name = "Weapons"
	weapons.character = self
	weapons.body = body
	weapons.exclude = [get_rid()]
	add_child(weapons)
	for id in ["stun_baton", "taser", "service_pistol", "emp"]:
		weapons.give(id)
	_shape_q.shape = _capsule
	_shape_q.collision_mask = 1 | 2
	_shape_q.exclude = [get_rid()]
	_set_present(false)


# ================================================================== queries (waking / HUD)
func on_foot() -> bool:
	return state in ["foot", "vault"]


func weapon_drawn() -> bool:
	return not weapons.is_holstered()


func speed() -> float:
	return Vector2(velocity.x, velocity.z).length()


func forward() -> Vector3:
	return global_basis.z


func head_position() -> Vector3:
	return global_position + Vector3.UP * (1.62 - 0.5 * _crouch_s)


# ================================================================== input
func _in(name_: String) -> bool:
	if not bot.is_empty():
		return bool(bot.get(name_, false))
	if not input_enabled:
		return false
	return InputMap.has_action(name_) and Input.is_action_pressed(name_)


func _move_input() -> Vector2:
	if not bot.is_empty():
		return bot.get("move", Vector2.ZERO)
	if not input_enabled:
		return Vector2.ZERO
	return Input.get_vector("foot_left", "foot_right", "foot_back", "foot_fwd")


func handle_input(event: InputEvent) -> bool:
	if not on_foot() or not input_enabled:
		return false
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		cam.look(event.relative)
		return true
	if event.is_action_pressed("jump"):
		_jump_buf = 0.15
		return true
	if event.is_action_pressed("crouch"):
		crouching = not crouching
		return true
	if event.is_action_pressed("reload_weapon"):
		weapons.reload()
		return true
	if event.is_action_pressed("holster"):
		if weapons.is_holstered():
			weapons.select(weapons.last_weapon)
		else:
			weapons.holster()
		return true
	if event.is_action_pressed("shoulder_swap"):
		cam.cycle()
		return true
	if event.is_action_pressed("weapon_next"):
		weapons.cycle(1)
		return true
	if event.is_action_pressed("weapon_prev"):
		weapons.cycle(-1)
		return true
	if event.is_action_pressed("quick_emp") and weapons.inventory.has("emp"):
		var prev: String = weapons.current
		weapons.select("emp")
		weapons.trigger(true)
		weapons.trigger(false)
		if prev != "" and prev != "emp":
			get_tree().create_timer(0.5).timeout.connect(func(): if weapons.current == "emp": weapons.select(prev))
		return true
	for i in 6:
		if event.is_action_pressed("weapon_%d" % (i + 1)):
			for id in weapons.inventory:
				if int(weapons.defs()[id].get("slot", 0)) == i + 1:
					weapons.select(id)
			return true
	return false


# ================================================================== physics
func _physics_process(dt: float) -> void:
	var t0 := Time.get_ticks_usec()
	_physics_inner(dt)
	prof_us = lerpf(prof_us, float(Time.get_ticks_usec() - t0), 0.05)


func _physics_inner(dt: float) -> void:
	_since_hit += dt
	_fire_face = maxf(0.0, _fire_face - dt)
	stunned = maxf(0.0, stunned - dt)
	match state:
		"foot":
			_foot(dt)
		"vault":
			_vault_tick(dt)
		"enter":
			_enter_tick(dt)
		"exit":
			_exit_tick(dt)
		"dead":
			_dead_t += dt
			velocity.x = 0.0
			velocity.z = 0.0
			velocity.y -= GRAVITY * dt
			move_and_slide()
			if _dead_t > 3.5:
				respawn()
		"car":
			if car and is_instance_valid(car):
				global_position = car.global_position
	# armour does not regenerate; health creeps back to 60 % after a while out of fire
	if state != "dead" and _since_hit > 6.0 and health < MAX_HEALTH * 0.6:
		health = minf(MAX_HEALTH * 0.6, health + dt * 6.0)


func _foot(dt: float) -> void:
	var mv := _move_input()
	aiming = _in("aim") and stunned <= 0.0
	walking = _in("walk")
	sprinting = _in("sprint") and mv.y > 0.3 and not aiming and not crouching and stunned <= 0.0
	if sprinting and crouching:
		crouching = false
	if _in("jump") and not bot.is_empty():
		_jump_buf = 0.15
	if bot.get("crouch", null) != null:
		crouching = bool(bot.crouch)
	if bot.has("yaw") and cam:
		cam.yaw = float(bot.yaw)
	var yaw: float = cam.yaw if cam else _yaw
	var fwd := Vector3(-sin(yaw), 0, -cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	var wish := (fwd * mv.y + right * mv.x)
	if wish.length() > 1.0:
		wish = wish.normalized()
	var top := JOG
	if sprinting:
		top = SPRINT
	elif crouching:
		top = CROUCH
	elif aiming:
		top = AIM_WALK
	elif walking:
		top = WALK
	if stunned > 0.0:
		top *= 0.35
	var hv := Vector3(velocity.x, 0, velocity.z)
	var target := wish * top
	var acc := ACCEL if is_on_floor() else AIR_ACCEL
	hv = hv.move_toward(target, acc * dt * 2.2)
	velocity.x = hv.x
	velocity.z = hv.z
	# vertical
	_jump_buf = maxf(0.0, _jump_buf - dt)
	_coyote = 0.12 if is_on_floor() else maxf(0.0, _coyote - dt)
	if is_on_floor():
		velocity.y = minf(velocity.y, 0.0)
	else:
		velocity.y -= GRAVITY * dt
	if _jump_buf > 0.0 and _coyote > 0.0 and stunned <= 0.0:
		_jump_buf = 0.0
		if not _try_vault(hv.normalized() if hv.length() > 0.5 else forward()):
			velocity.y = JUMP_V
			_coyote = 0.0
			crouching = false
			stats.jumps += 1
			if state == "foot":
				floor_snap_length = 0.0
	if velocity.y <= 0.0:
		floor_snap_length = 0.45
	var pre := global_position
	var pre_v := velocity
	move_and_slide()
	# step up stairs / kerbs the capsule stops at
	if is_on_floor() and is_on_wall() and hv.length() > 0.5:
		_try_step(pre, pre_v * dt)
	# facing: towards the aim while aiming or just after firing, else towards travel
	var face_yaw := _yaw
	if aiming or _fire_face > 0.0 or (weapons.current != "" and _in("fire")):
		face_yaw = atan2(fwd.x, fwd.z)
	elif hv.length() > 0.4:
		face_yaw = atan2(hv.x, hv.z)
	_yaw = lerp_angle(_yaw, face_yaw, 1.0 - exp(-dt * (16.0 if aiming else 10.0)))
	rotation = Vector3(0, _yaw, 0)
	_crouch_s = move_toward(_crouch_s, 1.0 if crouching else 0.0, dt * 5.0)
	_air = move_toward(_air, 0.0 if is_on_floor() else 1.0, dt * 6.0)
	# weapons
	var ap := {"point": global_position + forward() * 20.0 + Vector3.UP * 1.4}
	if bot.has("aim_at"):
		ap.point = bot.aim_at
	elif cam and cam.current:
		ap = cam.aim_point(250.0, [get_rid()])
	aim_point = ap.point
	var firing := _in("fire") and stunned <= 0.0
	if firing and weapons.is_holstered():
		weapons.select(weapons.last_weapon)
	weapons.trigger(firing)
	if firing:
		_fire_face = 0.6
	weapons.update(dt, aim_point, aiming or firing)
	if cam:
		cam.aiming = aiming
		cam.crouch = _crouch_s


func _try_step(pre: Vector3, motion: Vector3) -> void:
	var m := Vector3(motion.x, 0, motion.z)
	if m.length() < 0.001:
		return
	var probe := m.normalized() * (RADIUS + 0.05)
	var xf := Transform3D(Basis(), pre)
	if test_move(xf, Vector3.UP * STEP):
		return
	var up := xf.translated(Vector3.UP * STEP)
	if test_move(up, probe):
		return
	var fw := up.translated(probe)
	var col := KinematicCollision3D.new()
	if test_move(fw, Vector3.DOWN * (STEP + 0.05), col) and col.get_normal().y > 0.7:
		var h := (fw.origin + col.get_travel()).y - pre.y
		if h > 0.03:
			var to := pre + m.normalized() * maxf(m.length(), 0.06) + Vector3.UP * (h + 0.01)
			if not test_move(Transform3D(Basis(), to), Vector3.UP * 0.01):
				global_position = to
				stats.steps += 1


## Vault over / mantle onto a low obstacle in front. True when it started.
func _try_vault(dir: Vector3) -> bool:
	var space := get_world_3d().direct_space_state
	dir.y = 0.0
	dir = dir.normalized()
	var feet := global_position
	_ray.collision_mask = 1 | 2
	_ray.exclude = [get_rid()]
	_ray.from = feet + Vector3.UP * 0.4
	_ray.to = _ray.from + dir * 1.1
	var h := space.intersect_ray(_ray)
	if not h:
		return false
	var wall: Vector3 = h.position
	# top of the obstacle
	_ray.from = wall + dir * 0.3 + Vector3.UP * 2.3
	_ray.to = wall + dir * 0.3 + Vector3.UP * 0.2
	var t := space.intersect_ray(_ray)
	if not t:
		return false
	var top_y: float = t.position.y
	var hgt := top_y - feet.y
	if hgt < 0.45 or hgt > 2.05:
		return false
	# headroom on top
	_shape_q.transform = Transform3D(Basis(), Vector3(wall.x, top_y + 0.05 + HEIGHT * 0.5, wall.z) + dir * 0.35)
	_capsule.height = HEIGHT * 0.9
	var blocked := not space.intersect_shape(_shape_q, 1).is_empty()
	_capsule.height = HEIGHT
	if blocked:
		return false
	# beyond: ground lower than the top -> vault over, otherwise mantle onto it
	_ray.from = wall + dir * 1.3 + Vector3.UP * (hgt + 0.4)
	_ray.to = wall + dir * 1.3 + Vector3.DOWN * 1.5
	var b := space.intersect_ray(_ray)
	var over := hgt <= 1.4 and b and float(b.position.y) < top_y - 0.35
	_from = feet
	if over:
		_to = Vector3(b.position.x, b.position.y + 0.02, b.position.z)
		_mid = Vector3(wall.x, top_y + 0.35, wall.z) + dir * 0.2
		_dur = 0.55
		stats.vaults += 1
	else:
		_to = Vector3(wall.x, top_y + 0.03, wall.z) + dir * 0.45
		_mid = Vector3(feet.x, top_y + 0.45, feet.z) + dir * 0.15
		_dur = 0.45 + hgt * 0.2
		stats.mantles += 1
	_t = 0.0
	state = "vault"
	velocity = Vector3.ZERO
	body.play("interact")
	return true


func _vault_tick(dt: float) -> void:
	_t += dt / _dur
	var k := clampf(_t, 0.0, 1.0)
	var a := _from.lerp(_mid, k)
	var b := _mid.lerp(_to, k)
	global_position = a.lerp(b, k)
	if _t >= 1.0:
		state = "foot"
		velocity = (_to - _mid).normalized() * 2.5
		velocity.y = 0.0
	weapons.update(dt, aim_point, false)


# ================================================================== animation
func _process(dt: float) -> void:
	if body == null or not visible:
		return
	var hv := Vector3(velocity.x, 0, velocity.z)
	var fwd := forward()
	var along := hv.dot(fwd)
	var hip := 0.0
	if (aiming or _fire_face > 0.0) and hv.length() > 0.4:
		var ang := fwd.signed_angle_to(hv.normalized(), Vector3.UP)
		if absf(ang) > PI * 0.5:
			ang = wrapf(ang - PI, -PI, PI)   # backwards: legs point back, clips run in reverse
		hip = clampf(ang, -1.2, 1.2)
		along = hv.length() * signf(hv.dot(fwd) if absf(hv.dot(fwd)) > 0.1 else 1.0)
	body.set_locomotion(along, _crouch_s, _air if state == "foot" else 0.0)
	var armed: bool = not weapons.is_holstered() and String(weapons.def().get("hold", "")) != "baton"
	body.set_armed(armed and (aiming or _fire_face > 0.0 or weapons.current in ["service_pistol", "taser", "smg", "shotgun"]))
	var pitch := 0.0
	var yaw_off := 0.0
	if cam and (aiming or _fire_face > 0.0):
		var to := aim_point - head_position()
		pitch = atan2(to.y, Vector2(to.x, to.z).length())
		yaw_off = fwd.signed_angle_to(Vector3(to.x, 0, to.z).normalized(), Vector3.UP) if Vector2(to.x, to.z).length() > 0.3 else 0.0
	body.set_aim(1.0 if (aiming or _fire_face > 0.0) and armed else 0.0, clampf(yaw_off, -0.8, 0.8), clampf(pitch, -1.0, 1.0), hip)


# ================================================================== damage
func take_hit(h: Dictionary) -> void:
	if state == "dead" or state == "car" or h.get("source") == self:
		return
	var amt := float(h.get("amount", 0.0))
	if armour > 0.0:
		var soak := minf(armour, amt * 0.65)
		armour -= soak
		amt -= soak
	health -= amt
	stats.hits_taken += 1
	_since_hit = 0.0
	if float(h.get("stun", 0.0)) > 0.0:
		stunned = maxf(stunned, float(h.stun) * 1.2)
	var d: Vector3 = h.get("dir", Vector3.ZERO)
	damaged.emit(-d, float(h.get("amount", 0.0)))
	if cam and cam.has_method("shake"):
		cam.shake(clampf(float(h.get("amount", 0.0)) / 40.0, 0.15, 0.6))
	if health <= 0.0:
		die()
	elif randf() < 0.5:
		body.play("hit")


func die() -> void:
	if state == "dead":
		return
	health = 0.0
	state = "dead"
	_dead_t = 0.0
	stats.deaths += 1
	weapons.trigger(false)
	body.set_dead(true)
	died.emit()


## Back on your feet next to the car (if it's within reach) or at the nearest Hoshikawa station.
func respawn() -> void:
	var p := global_position
	var at: Vector3
	var c: RigidBody3D = waker.main.car if waker and waker.main else null
	var st: Vector3 = waker.nearest_station(p) if waker and waker.has_method("nearest_station") else Vector3.INF
	if c and (st == Vector3.INF or c.global_position.distance_to(p) < 400.0 or c.global_position.distance_to(p) < st.distance_to(p)):
		at = exit_spot(c)
	else:
		at = st
	health = MAX_HEALTH
	armour = MAX_ARMOUR
	stunned = 0.0
	body.set_dead(false)
	place(at, _yaw)
	state = "foot"
	respawned.emit()


func place(p: Vector3, yaw := 0.0) -> void:
	global_position = p
	velocity = Vector3.ZERO
	_yaw = yaw
	rotation = Vector3(0, yaw, 0)
	reset_physics_interpolation()
	if cam:
		cam.yaw = yaw + PI
		cam.snap()


# ================================================================== cars
func _set_present(on: bool) -> void:
	visible = on
	_shape.disabled = not on
	set_physics_process(true)
	collision_layer = 16 if on else 0
	if not on:
		weapons.trigger(false)
		weapons.holster()


func door_point(c: Node3D, side := -1.0) -> Vector3:
	# the driver sits on the right (left-hand traffic): -X in car space (+X is its left)
	return c.global_transform * Vector3(side * 1.25, 0.0, 0.25)


## A free spot next to the car for getting out (driver's door, the other side, behind, in front).
func exit_spot(c: Node3D) -> Vector3:
	var space := get_world_3d().direct_space_state
	for off in [Vector3(-1.35, 0, 0.25), Vector3(1.35, 0, 0.25), Vector3(0, 0, -3.0), Vector3(0, 0, 3.0), Vector3(-2.2, 0, 0.0), Vector3(2.2, 0, 0)]:
		var p: Vector3 = c.global_transform * off
		_ray.collision_mask = 1
		_ray.exclude = [c.get_rid()]
		_ray.from = p + Vector3.UP * 2.0
		_ray.to = p + Vector3.DOWN * 3.0
		var g := space.intersect_ray(_ray)
		if g:
			p.y = g.position.y + 0.03
		_shape_q.transform = Transform3D(Basis(), p + Vector3.UP * (HEIGHT * 0.5 + 0.05))
		_shape_q.exclude = [get_rid(), c.get_rid()]
		if space.intersect_shape(_shape_q, 1).is_empty():
			_shape_q.exclude = [get_rid()]
			return p
	_shape_q.exclude = [get_rid()]
	return c.global_position + Vector3.UP * 2.2


func can_enter(c: Node3D) -> bool:
	if c == null or not on_foot():
		return false
	var dp := door_point(c)
	var dp2 := door_point(c, 1.0)
	return minf(global_position.distance_to(dp), global_position.distance_to(dp2)) < 2.4 or global_position.distance_to(c.global_position) < 3.0


## Start getting into `c` (walks to the door, opens it, sits in).
func enter(c: RigidBody3D) -> void:
	_enter_car = c
	state = "enter"
	_t = 0.0
	_from = global_position
	var a := door_point(c)
	var b := door_point(c, 1.0)
	_to = a if global_position.distance_to(a) <= global_position.distance_to(b) else b
	_dur = clampf(_from.distance_to(_to) / 3.5, 0.15, 0.6)
	weapons.holster()
	velocity = Vector3.ZERO


func _enter_tick(dt: float) -> void:
	_t += dt
	var c := _enter_car
	if c == null or not is_instance_valid(c):
		state = "foot"
		return
	var k := clampf(_t / _dur, 0.0, 1.0)
	global_position = _from.lerp(_to, k)
	var look := c.global_position - global_position
	look.y = 0.0
	if look.length() > 0.1:
		_yaw = lerp_angle(_yaw, atan2(look.x, look.z), 1.0 - exp(-dt * 12.0))
		rotation.y = _yaw
	body.set_locomotion(2.0 if k < 1.0 else 0.0, 0.0, 0.0)
	if _t > _dur and _anim_t == 0.0:
		_anim_t = 0.01
		body.play("interact")
	if _anim_t > 0.0:
		_anim_t += dt
	if _anim_t > 0.35:
		_anim_t = 0.0
		state = "car"
		car = c
		_set_present(false)
		stats.enters += 1
		entered_car.emit(c)


## Get out of the car we're in. False when it's moving too fast.
func exit_car(force := false) -> bool:
	if state != "car" or car == null:
		return false
	if not force and absf(car.linear_velocity.length()) > 4.5:
		return false
	var c := car
	var p := exit_spot(c)
	_set_present(true)
	_from = p
	global_position = p
	velocity = Vector3.ZERO
	var out := p - c.global_position
	out.y = 0.0
	_yaw = atan2(out.x, out.z) if out.length() > 0.1 else c.rotation.y
	rotation = Vector3(0, _yaw, 0)
	reset_physics_interpolation()
	state = "exit"
	_t = 0.0
	body.play("interact")
	car = null
	stats.exits += 1
	exited_car.emit(c)
	return true


func _exit_tick(dt: float) -> void:
	_t += dt
	velocity.y -= GRAVITY * dt
	velocity.x = 0.0
	velocity.z = 0.0
	move_and_slide()
	body.set_locomotion(0.0, 0.0, 0.0)
	if _t > 0.35:
		state = "foot"
