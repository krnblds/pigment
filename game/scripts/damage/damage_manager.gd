extends Node3D
## Damage and destruction for the whole game (docs/agents/damage/NOTES.md). main.gd creates one:
##
##   fx            damage_fx.gd        pooled particles, geysers, smoke, puddles
##   audio         damage_audio.gd     crash / glass / water / clang sounds (sound-pack hook)
##   debris        debris.gd           every loose rigid piece, with the body budget
##   destructibles destructibles.gd    the street props
##   hero_damage   vehicle_damage.gd   on the player's car (R resets it), and on traffic cars while they
##                                     are physics bodies near the player (cheap: only nearby ones deform)
##   a small damage indicator on the HUD (damage_hud.gd)
##
## --no-damage turns it all off.

const Fx := preload("res://scripts/damage/damage_fx.gd")
const Audio := preload("res://scripts/damage/damage_audio.gd")
const Debris := preload("res://scripts/damage/debris.gd")
const Destructibles := preload("res://scripts/damage/destructibles.gd")
const VehicleDamage := preload("res://scripts/damage/vehicle_damage.gd")
const DamageHud := preload("res://scripts/damage/damage_hud.gd")

const TRAFFIC_R := 70.0           ## traffic cars get damage within this of the hero
const TRAFFIC_MAX := 10           ## ... at most this many at once

var main: Node
var hero: RigidBody3D
var fx: Node3D
var audio: Node3D
var debris: Node3D
var destructibles: Node3D
var hero_damage: Node3D
var hud: Control
var _traffic_t := 0.0
var _tracked: Array = []          ## traffic cars carrying a damage node


func setup(m: Node) -> void:
	main = m
	name = "Damage"
	hero = m.car
	fx = Fx.new()
	fx.name = "Fx"
	add_child(fx)
	audio = Audio.new()
	audio.name = "Audio"
	add_child(audio)
	debris = Debris.new()
	debris.name = "Debris"
	debris.focus = hero
	debris.audio = audio
	add_child(debris)
	# debris collides with the hero (its body, not its wheel rays)
	hero.collision_mask |= Debris.LAYER
	hero_damage = attach(hero, true)
	destructibles = Destructibles.new()
	add_child(destructibles)
	destructibles.setup(self, m.town if m.town and m.town.layout else null)
	if hero_damage:
		hero_damage.hit.connect(func(p: Vector3, j: float): destructibles.on_car_hit(p, j, hero))
	if m.hud:
		hud = DamageHud.new()
		hud.damage = hero_damage
		m.hud.add_child(hud)
	print("damage: %d destructible props indexed, hero panels %d" % [destructibles.stats.indexed, hero_damage.panels.size() if hero_damage else 0])


## Damage on a vehicle body: the hero (car.gd: meshes under Visual) or a traffic car (LOD0 meshes).
func attach(b: RigidBody3D, is_hero := false) -> Node3D:
	if b.has_node("Damage"):
		return b.get_node("Damage")
	if not is_inside_tree() or get_tree().is_queued_for_deletion():
		return null
	var d := VehicleDamage.new()
	var meshes := {}
	var root: Node3D = null
	var sp := {}
	if is_hero:
		root = b.get_node_or_null("Visual")
		sp = b.spec
		if root:
			for c in root.get_children():
				if c is MeshInstance3D:
					meshes[String(c.name)] = c
	else:
		root = b
		sp = {"damage": b.model.damage, "wheel_positions": b.model.wheel_positions, "class": b.model.klass}
		if b.lod_nodes.is_empty():
			return null
		for mi in b.lod_nodes[0].meshes:
			if mi is MeshInstance3D and mi.get_parent() == b:
				meshes[String(mi.name)] = mi
	if root == null or sp.get("damage", {}).is_empty():
		return null
	d.setup(self, b, root, meshes, sp, is_hero)
	b.add_child(d)
	if not is_hero:
		_pin_lod0(b, d)
	return d


## A damaged traffic car keeps its LOD0 (its dents and missing panels live there) until it is reset;
## the reparented panel meshes leave the LOD bookkeeping, their pivots join it.
func _pin_lod0(b: RigidBody3D, d: Node3D) -> void:
	var e: Dictionary = b.lod_nodes[0]
	if not e.has("orig_end"):
		e["orig_end"] = e.end
		e["orig_top"] = (e.top as Array).duplicate()
	e.end = 1.0e6
	var top: Array = []
	for n in e.top:
		if is_instance_valid(n) and n.get_parent() == b:
			top.append(n)
	for nm in d.panels:
		var pv: Node3D = d.panels[nm].pivot
		if pv and pv.get_parent() == b:
			top.append(pv)
	e.top = top
	for mi in e.meshes:
		if mi is MeshInstance3D:
			mi.visibility_range_end = 0.0
	for li in range(1, b.lod_nodes.size()):
		for mi in b.lod_nodes[li].meshes:
			if mi is MeshInstance3D:
				mi.set_meta("dmg_hidden", true)
				mi.visible = false


## Cars that can hit props this tick: the hero and loose (physics) traffic near it.
func hitters() -> Array:
	var out := [hero]
	var tr = main.traffic if main and "traffic" in main else null
	if tr:
		for c in tr.active:
			if c.mode == 1 and c.global_position.distance_to(hero.global_position) < TRAFFIC_R:   # DYNAMIC
				out.append(c)
	return out


## The hero hit something that doesn't register hits itself (a lane-following or parked traffic car):
## give that car the mirrored impulse.
func forward_impact(other: Object, pos: Vector3, dir: Vector3, j: float) -> void:
	if not (other is RigidBody3D) or other == hero or not ("model" in other):
		return
	if other.mode == 1:          # a loose car registers its own hits
		return
	var d := _traffic_damage(other)
	if d:
		d.apply_impact(pos, dir, j)


func _traffic_damage(c: RigidBody3D) -> Node3D:
	if c.has_node("Damage"):
		return c.get_node("Damage")
	if _tracked.size() >= TRAFFIC_MAX:
		# drop the farthest undamaged one
		_tracked.sort_custom(func(a, b): return a.global_position.distance_to(hero.global_position) < b.global_position.distance_to(hero.global_position))
		var last = _tracked.back()
		if is_instance_valid(last) and last.global_position.distance_to(hero.global_position) > c.global_position.distance_to(hero.global_position):
			release_traffic(last)
		else:
			return null
	var d := attach(c, false)
	if d:
		_tracked.append(c)
	return d


## --damage-prof: script time per physics tick of the damage parts, printed every 5 s.
var prof := {}
var _prof_on := OS.get_cmdline_user_args().has("--damage-prof")
var _prof_t := 0.0
var _prof_ticks := 0


func prof_add(key: String, us: int) -> void:
	prof[key] = int(prof.get(key, 0)) + us


func _process(delta: float) -> void:
	if not _prof_on:
		return
	_prof_t += delta
	if _prof_t > 5.0:
		var out := {}
		for k in prof:
			out[k] = snappedf(float(prof[k]) / maxf(_prof_ticks, 1), 0.1)
		print("damage prof us/tick ", JSON.stringify(out), " debris ", debris.bodies.size(), " awake ", debris.awake_count(),
			" armed ", destructibles.armed.size(), " broken ", destructibles.stats.broken)
		prof.clear()
		_prof_t = 0.0
		_prof_ticks = 0


func _physics_process(delta: float) -> void:
	_prof_ticks += 1
	_traffic_t -= delta
	if _traffic_t > 0.0:
		return
	_traffic_t = 0.25
	var tr = main.traffic if main and "traffic" in main else null
	if tr == null:
		return
	for c in tr.active:
		if c.mode == 1 and c.global_position.distance_to(hero.global_position) < TRAFFIC_R:
			_traffic_damage(c)
	for c in _tracked.duplicate():
		if not is_instance_valid(c) or not c.visible or c.mode == 4:      # OFF: despawned, back in the pool
			release_traffic(c)


## A pooled traffic car leaves: its damage goes (undamaged when it respawns).
func release_traffic(c) -> void:
	_tracked.erase(c)
	if not is_instance_valid(c) or not c.has_node("Damage"):
		return
	var d: Node3D = c.get_node("Damage")
	d.reset()
	# panels back to plain children of the car, LOD bookkeeping as it was
	for nm in d.panels:
		var p: Dictionary = d.panels[nm]
		var mi: MeshInstance3D = p.mi
		var g := mi.global_transform
		if mi.get_parent():
			mi.get_parent().remove_child(mi)
		c.add_child(mi)
		mi.global_transform = g
	for nm in d.order:
		if d.panels.has(nm) and is_instance_valid(d.panels[nm].pivot):
			d.panels[nm].pivot.queue_free()
	var e: Dictionary = c.lod_nodes[0]
	if e.has("orig_end"):
		e.end = e.orig_end
		e.top = e.orig_top
		e.erase("orig_end")
		e.erase("orig_top")
		for mi in e.meshes:
			if mi is MeshInstance3D:
				mi.visibility_range_end = e.end
	for li in range(1, c.lod_nodes.size()):
		for mi in c.lod_nodes[li].meshes:
			if mi is MeshInstance3D and mi.get_meta("dmg_hidden", false):
				mi.visible = true
				mi.remove_meta("dmg_hidden")
	c.remove_child(d)
	d.queue_free()


## R: the hero is whole again.
func reset_hero() -> void:
	if hero_damage:
		hero_damage.reset()
