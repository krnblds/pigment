extends Node3D
## Debris pool: every loose rigid piece (car panels, knocked props, fallen poles, bag / box chunks).
##
##   spawn(nodes, shapes, xf, mass, opts)  -> RigidBody3D   (nodes are re-parented into the body)
##   release(rb)                            back to the pool
##
## Budget (docs/agents/damage/NOTES.md): at most MAX_AWAKE simulated bodies; beyond that the oldest
## awake ones far from the player are frozen (static, still solid). Bodies past FREEZE_FAR freeze,
## past DESPAWN_FAR they go (their prop stays destroyed: destructibles.gd keeps that state), and the
## oldest go first when there are more than MAX_BODIES. `life` (s) ends small stuff (glass, cans)
## once it is out of sight. Pinned bodies (panels still hanging on a hinge) are never frozen.
##
## Layers: debris is on layer 4 (bit value 8) and collides with the world (1), cars (2, the hero is
## on 1) and other debris (8). Wheel rays (mask 1) roll over it without seeing it.

const LAYER := 8
const MAX_AWAKE := 60
const MAX_BODIES := 140
const FREEZE_FAR := 70.0
const DESPAWN_FAR := 170.0
const CHECK_EVERY := 0.25

var focus: Node3D                ## the player's car
var audio: Node                  ## damage_audio.gd (debris lands silently: bounce clatter was too much)
var bodies: Array = []           ## entries {rb, t, life, kind, pinned, on_free}
var stats := {"spawned": 0, "released": 0, "frozen_budget": 0, "max_awake": 0, "max_bodies": 0}
var _pool: Array[RigidBody3D] = []
var _t := 0.0
var _by_rb := {}


func _physics_process(delta: float) -> void:
	_t -= delta
	for e in bodies:
		e.t += delta
	if _t > 0.0:
		return
	_t = CHECK_EVERY
	var t0 := Time.get_ticks_usec()
	housekeeping()
	if get_parent() and get_parent().has_method("prof_add"):
		get_parent().prof_add("debris", Time.get_ticks_usec() - t0)


## Budget pass (also called by the tests).
func housekeeping() -> void:
	var fp: Vector3 = focus.global_position if is_instance_valid(focus) else Vector3.ZERO
	var cam := get_viewport().get_camera_3d() if is_inside_tree() else null
	var cp: Vector3 = cam.global_position if cam else fp
	var awake := []
	var drop := []
	for e in bodies:
		var rb: RigidBody3D = e.rb
		if not is_instance_valid(rb):
			drop.append(e)
			continue
		var d := rb.global_position.distance_to(fp)
		if e.pinned:
			continue
		if d > DESPAWN_FAR:
			drop.append(e)
			continue
		if e.life > 0.0 and e.t > e.life and (rb.global_position.distance_to(cp) > 25.0 or e.t > e.life * 3.0):
			drop.append(e)
			continue
		if not rb.freeze:
			if d > FREEZE_FAR and (rb.sleeping or e.t > 8.0):
				_freeze(rb)
			elif not rb.sleeping:
				awake.append(e)
		elif d < FREEZE_FAR * 0.6 and rb.get_meta("budget_frozen", false):
			rb.set_meta("budget_frozen", false)
			rb.freeze = false
	# too many awake: freeze the oldest, farthest first
	if awake.size() > MAX_AWAKE:
		awake.sort_custom(func(a, b): return a.rb.global_position.distance_squared_to(fp) > b.rb.global_position.distance_squared_to(fp))
		for i in awake.size() - MAX_AWAKE:
			_freeze(awake[i].rb)
			awake[i].rb.set_meta("budget_frozen", true)
			stats.frozen_budget += 1
	for e in drop:
		_release_entry(e)
	# too many in total: the oldest unpinned go
	if bodies.size() > MAX_BODIES:
		var old := bodies.filter(func(e): return not e.pinned)
		old.sort_custom(func(a, b): return a.t > b.t)
		for i in mini(old.size(), bodies.size() - MAX_BODIES):
			_release_entry(old[i])
	stats.max_awake = maxi(stats.max_awake, mini(awake.size(), MAX_AWAKE))
	stats.max_bodies = maxi(stats.max_bodies, bodies.size())


func awake_count() -> int:
	var n := 0
	for e in bodies:
		if is_instance_valid(e.rb) and not e.rb.freeze and not e.rb.sleeping:
			n += 1
	return n


func _freeze(rb: RigidBody3D) -> void:
	rb.freeze_mode = RigidBody3D.FREEZE_MODE_STATIC
	rb.freeze = true


## A rigid body made of `nodes` (re-parented, keeping their global transforms) and `shapes`
## ([[Shape3D, Transform3D local]]), at `xf`. opts: vel, angvel, life (s, 0 = until far), kind
## (material for sounds: metal / plastic / glass / wood / cardboard / bag / concrete), pinned,
## on_free (Callable(rb)), name, ccd.
func spawn(nodes: Array, shapes: Array, xf: Transform3D, mass: float, opts := {}) -> RigidBody3D:
	var rb: RigidBody3D = _pool.pop_back() if not _pool.is_empty() else _new_body()
	rb.name = String(opts.get("name", "Debris"))
	rb.mass = maxf(mass, 0.2)
	rb.freeze = false
	rb.sleeping = false
	rb.continuous_cd = bool(opts.get("ccd", false))
	rb.set_meta("budget_frozen", false)
	if rb.get_parent() == null:
		add_child(rb)
	rb.global_transform = xf
	for s in shapes:
		var cs := CollisionShape3D.new()
		cs.shape = s[0]
		cs.transform = s[1]
		rb.add_child(cs)
	for n in nodes:
		var nd: Node3D = n
		var g := nd.global_transform
		if nd.get_parent():
			nd.get_parent().remove_child(nd)
		rb.add_child(nd)
		nd.global_transform = g
	rb.linear_velocity = opts.get("vel", Vector3.ZERO)
	rb.angular_velocity = opts.get("angvel", Vector3.ZERO)
	rb.reset_physics_interpolation()
	var e := {"rb": rb, "t": 0.0, "life": float(opts.get("life", 0.0)), "kind": String(opts.get("kind", "metal")),
		"pinned": bool(opts.get("pinned", false)), "on_free": opts.get("on_free", Callable())}
	bodies.append(e)
	_by_rb[rb] = e
	stats.spawned += 1
	return rb


func set_pinned(rb: RigidBody3D, pinned: bool, life := -1.0) -> void:
	var e: Dictionary = _by_rb.get(rb, {})
	if e.is_empty():
		return
	e.pinned = pinned
	e.t = 0.0
	if life >= 0.0:
		e.life = life


func release(rb: RigidBody3D) -> void:
	var e: Dictionary = _by_rb.get(rb, {})
	if not e.is_empty():
		_release_entry(e)


func clear_all() -> void:
	for e in bodies.duplicate():
		_release_entry(e)


func _release_entry(e: Dictionary) -> void:
	bodies.erase(e)
	var rb: RigidBody3D = e.rb
	_by_rb.erase(rb)
	if not is_instance_valid(rb):
		return
	var cb: Callable = e.on_free
	if cb.is_valid():
		cb.call(rb)
	for c in rb.get_children():
		rb.remove_child(c)
		c.queue_free()
	for x in rb.get_collision_exceptions():
		rb.remove_collision_exception_with(x)
	rb.freeze = true
	rb.linear_velocity = Vector3.ZERO
	rb.angular_velocity = Vector3.ZERO
	if rb.get_parent():
		rb.get_parent().remove_child(rb)      # out of the physics world while pooled
	_pool.append(rb)
	stats.released += 1


func _new_body() -> RigidBody3D:
	var rb := RigidBody3D.new()
	rb.collision_layer = LAYER
	rb.collision_mask = 1 | 2 | LAYER
	rb.can_sleep = true
	rb.linear_damp = 0.05
	rb.angular_damp = 0.3
	var pm := PhysicsMaterial.new()
	pm.friction = 0.7
	pm.bounce = 0.1
	rb.physics_material_override = pm
	return rb
