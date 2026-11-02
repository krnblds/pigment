extends Node3D
## A character's weapons: inventory and ammo, fire / reload timing, spread bloom, recoil, the weapon model
## in the hand. Used by the player (player.gd) and armed sleepwalkers (waker/sleepwalker.gd).
##
##   user.update(dt, aim_point, aiming)  every frame;  user.trigger(pressed);  user.reload()
##   user.select(id) / user.holster()   user.spread_deg() for the crosshair

const Combat := preload("res://scripts/weapons/combat.gd")
const WeaponModels := preload("res://scripts/weapons/weapon_models.gd")

signal fired(id: String)
signal reloaded(id: String)
signal changed(id: String)

var character: Node3D                    ## the body shooting (excluded from its own shots)
var body: Node3D                         ## player_body.gd adapter (hand position, animations)
var inventory: Array = []                ## weapon ids, slot order
var ammo := {}                           ## id -> {"mag": n, "reserve": n}
var current := ""                        ## "" = holstered
var last_weapon := "taser"
var ai := false                          ## AI shooter: wider spread
var accuracy := 1.0                      ## AI: spread multiplier
var infinite_reserve := false
var exclude: Array = []

var _cool := 0.0
var _reload_t := 0.0
var _bloom := 0.0
var _held := false
var _aim_point := Vector3.ZERO
var _aiming := false
var _model: Node3D
var _models := {}
var _throw_pending := -1.0
var _buffer := 0.0


func defs() -> Dictionary:
	return Combat.load_defs()


func give(id: String, full := true) -> void:
	var d: Dictionary = defs().get(id, {})
	if d.is_empty():
		return
	if not inventory.has(id):
		inventory.append(id)
		inventory.sort_custom(func(a, b): return int(defs()[a].get("slot", 9)) < int(defs()[b].get("slot", 9)))
	if full or not ammo.has(id):
		ammo[id] = {"mag": int(d.get("mag", 0)), "reserve": int(d.get("reserve", 0))}


func def() -> Dictionary:
	return defs().get(current, {})


func is_holstered() -> bool:
	return current == ""


func reloading() -> bool:
	return _reload_t > 0.0


func select(id: String) -> void:
	if id == current or (id != "" and not inventory.has(id)):
		return
	current = id
	if id != "":
		last_weapon = id
	_reload_t = 0.0
	_cool = 0.25
	_bloom = 0.0
	_show_model()
	changed.emit(id)


func holster() -> void:
	select("")


func cycle(dir: int) -> void:
	if inventory.is_empty():
		return
	var i := inventory.find(current)
	if i < 0:
		i = inventory.find(last_weapon)
	select(inventory[posmod(i + dir, inventory.size())])


func trigger(pressed: bool) -> void:
	if pressed and not _held:
		_buffer = 0.2                    # a press just before the weapon is ready still fires
		_try_fire()
	_held = pressed


func reload() -> void:
	var d := def()
	if d.is_empty() or int(d.get("mag", 0)) <= 0 or _reload_t > 0.0:
		return
	var a: Dictionary = ammo[current]
	if a.mag >= int(d.mag) or (a.reserve <= 0 and not infinite_reserve):
		return
	_reload_t = float(d.get("reload", 1.5))
	if body and body.has_method("play"):
		body.play("reload")
	if Combat.world:
		Combat.world.audio.play(String(d.sounds.get("reload", "reload_mag")), global_position, 0.6)


func spread_deg() -> float:
	var d := def()
	if d.is_empty():
		return 0.0
	var base := float(d.get("spread_aim" if _aiming else "spread_hip", 1.0))
	return (base + _bloom) * (accuracy if ai else 1.0)


func muzzle_position() -> Vector3:
	if _model and _model.has_node("Muzzle"):
		return (_model.get_node("Muzzle") as Node3D).global_position
	if body and body.has_method("hand_position"):
		return body.hand_position()
	return global_position + Vector3.UP * 1.4


func update(dt: float, aim_point: Vector3, aiming: bool) -> void:
	_aim_point = aim_point
	_aiming = aiming
	_cool = maxf(0.0, _cool - dt)
	var d := def()
	_bloom = maxf(0.0, _bloom - dt * 6.0)
	if _reload_t > 0.0:
		_reload_t -= dt
		if _reload_t <= 0.0 and not d.is_empty():
			var a: Dictionary = ammo[current]
			var need := int(d.mag) - int(a.mag)
			var take := need if infinite_reserve else mini(need, int(a.reserve))
			a.mag += take
			if not infinite_reserve:
				a.reserve -= take
			reloaded.emit(current)
	if _buffer > 0.0:
		_buffer -= dt
		if _cool <= 0.0 and _reload_t <= 0.0:
			_try_fire()
	elif _held and not d.is_empty() and bool(d.get("auto", false)):
		_try_fire()
	if _throw_pending >= 0.0:
		_throw_pending -= dt
		if _throw_pending < 0.0:
			_do_throw()
	_pose_model()


func _try_fire() -> void:
	var d := def()
	if d.is_empty() or _cool > 0.0 or _reload_t > 0.0 or Combat.world == null:
		return
	var kind := String(d.get("kind", "hitscan"))
	var a: Dictionary = ammo.get(current, {"mag": 0, "reserve": 0})
	if int(d.get("mag", 0)) > 0 and a.mag <= 0:
		Combat.world.audio.play(String(d.sounds.get("dry", "dry_fire")), global_position, 0.4)
		_cool = 0.25
		if a.reserve > 0 or infinite_reserve:
			reload()
		return
	_cool = 1.0 / float(d.get("rate", 4.0))
	_buffer = 0.0
	if int(d.get("mag", 0)) > 0:
		a.mag -= 1
	match kind:
		"melee":
			if body:
				body.play("melee")
			var fwd := (_aim_point - character.global_position)
			fwd.y = 0.0
			if fwd.length() < 0.1:
				fwd = character.global_basis.z
			Combat.world.melee(character.global_position + Vector3.UP * 1.2, fwd.normalized(), d, character)
			Combat.world.noise(character.global_position, 6.0)
		"thrown":
			if body:
				body.play("punch")
			_throw_pending = 0.22
			_cool = maxf(_cool, 0.8)
		_:
			_shoot(d)
	fired.emit(current)


func _shoot(d: Dictionary) -> void:
	var from := muzzle_position()
	var to := _aim_point
	var dir := (to - from).normalized() if to.distance_to(from) > 0.5 else -character.global_basis.z
	var spread := deg_to_rad(spread_deg())
	var basis := Basis.looking_at(dir, Vector3.UP if absf(dir.y) < 0.98 else Vector3.RIGHT)
	for i in int(d.get("pellets", 1)):
		var r := sqrt(randf()) * spread
		var a := randf() * TAU
		var sd := (basis * Vector3(cos(a) * sin(r), sin(a) * sin(r), -cos(r))).normalized()
		Combat.world.hitscan(from, sd, d, character, exclude)
	var cyan := String(d.get("tracer", "")) == "arc"
	Combat.world.muzzle_flash(from, dir, cyan)
	Combat.world.audio.play(String(d.sounds.get("fire", "pistol_shot")), from, 1.0 if not cyan else 0.6)
	Combat.world.noise(from, 12.0 if cyan else 55.0)
	if bool(d.get("casing", false)):
		Combat.world.eject_casing(from - dir * 0.12, basis.x)
	_bloom = minf(_bloom + float(d.get("bloom", 0.5)), float(d.get("bloom_max", 4.0)))
	if body:
		body.play("shoot")


func _do_throw() -> void:
	var d: Dictionary = defs().get("emp", {})
	if d.is_empty() or Combat.world == null:
		return
	var from: Vector3 = (body.hand_position() if body else character.global_position + Vector3.UP * 1.5) + Vector3.UP * 0.1
	var to := _aim_point
	var dir: Vector3 = (to - from)
	var flat := Vector3(dir.x, 0, dir.z)
	var dist := clampf(flat.length(), 3.0, 22.0)
	var spd := float(d.get("throw_speed", 15.0))
	# lob: aim a little above the target, speed scales with distance
	var v := flat.normalized() * minf(spd, 4.0 + dist * 0.9) + Vector3.UP * (2.5 + dist * 0.18 + clampf(dir.y, -2.0, 6.0) * 0.5)
	Combat.world.throw_emp(from, v, d, character)


# ------------------------------------------------------------------ model in the hand
func _show_model() -> void:
	for k in _models:
		_models[k].visible = false
	_model = null
	if current == "" or body == null:
		return
	if not _models.has(current):
		var m := WeaponModels.build(current)
		m.top_level = true
		add_child(m)
		_models[current] = m
	_model = _models[current]
	_model.visible = true


func _pose_model() -> void:
	if _model == null or body == null or not _model.visible:
		return
	var hand: Vector3 = body.hand_position()
	var fwd := (_aim_point - hand)
	if fwd.length() < 0.3 or not _aiming:
		fwd = character.global_basis.z if fwd.length() < 0.3 else fwd
	fwd = fwd.normalized()
	if not _aiming and String(def().get("hold", "pistol")) != "baton":
		# lowered: pointing ahead and a little down
		var f := character.global_basis.z
		fwd = (f - Vector3.UP * 0.5).normalized()
	if String(def().get("hold", "")) == "baton" and not _aiming:
		fwd = (character.global_basis.z * 0.3 + Vector3.UP * -0.95).normalized()
	var up := Vector3.UP if absf(fwd.y) < 0.98 else character.global_basis.z
	_model.global_transform = Transform3D(Basis.looking_at(fwd, up), hand)
