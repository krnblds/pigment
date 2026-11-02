extends Node3D
## Combat world: weapon data, hitscan / melee / thrown resolution, and every pooled effect (tracers,
## muzzle flashes, impact decals, sparks, shell casings, EMP charges) plus the weapon sound bank.
## One instance (Combat.world); characters fire through their weapon_user.gd.
##
## Targets: any node with `take_hit(hit: Dictionary)` on the collider or up to 3 parents. hit keys:
##   amount (hp), stun (0..1), pos, normal, dir, source (Node), weapon (id), lethal (bool), emp (bool)
## Props: shooting a street prop near the hit uses the damage workstream's destructibles additively
## (glass on vending machines / kiosks / bus stops shatters, lamps can be shot out).
##
## Layers: characters are on 16 (player + sleepers); shots test world (1), traffic (2), characters (16).

const WeaponAudio := preload("res://scripts/weapons/weapon_audio.gd")
const DATA_DIR := "res://data/weapons/"
const SHOT_MASK := 1 | 2 | 16
const CHAR_LAYER := 16

static var world: Node3D
static var defs := {}                  ## id -> Dictionary (data/weapons/*.json)

var main: Node
var audio: Node3D
var stats := {"shots": 0, "hits": 0, "headshots": 0, "tracers": 0, "decals": 0, "casings": 0, "emp": 0, "props": 0}
var prof_us := 0.0                     ## running average of this node's per-frame cost (µs)
var noise_events: Array = []           ## [pos, radius, time] gunshots etc. for hearing (AI reads)
var hit_listeners: Array[Callable] = []  ## called with (hit, target) on every confirmed hit (HUD markers)

const N_TRACERS := 32
const N_FLASH := 6
const N_DECALS := 96
const N_CASINGS := 64
const N_SPARKS := 10
const N_EMP := 4

var _tracers: Array = []               ## {mi, t, life}
var _ti := 0
var _flashes: Array = []               ## {node, light, t}
var _fi := 0
var _decals: Array[Decal] = []
var _di := 0
var _decal_tex := {}
var _casing_mm: MultiMesh
var _casings: Array = []               ## {p, v, r, w, t, floor}
var _ci := 0
var _sparks: Array[GPUParticles3D] = []
var _si := 0
var _emps: Array = []                  ## {node, p, v, t, fuse, live, def, source, ring, light}
var _ray := PhysicsRayQueryParameters3D.new()


static func load_defs() -> Dictionary:
	if not defs.is_empty():
		return defs
	var d := DirAccess.open(DATA_DIR)
	if d == null:
		return defs
	for f in d.get_files():
		if f.ends_with(".json"):
			var w = JSON.parse_string(FileAccess.get_file_as_string(DATA_DIR + f))
			if w is Dictionary:
				defs[String(w.id)] = w
	return defs


func _ready() -> void:
	world = self
	name = "Combat"
	load_defs()
	audio = WeaponAudio.new()
	add_child(audio)
	_build_tracers()
	_build_flashes()
	_build_decals()
	_build_casings()
	_build_sparks()
	_build_emps()


func _exit_tree() -> void:
	if world == self:
		world = null


# ================================================================== resolution
## Hitscan from `from` towards `dir` (already spread). Returns the hit dictionary (empty: miss).
func hitscan(from: Vector3, dir: Vector3, w: Dictionary, source: Node, exclude: Array) -> Dictionary:
	var rng := float(w.get("range", 100.0))
	_ray.from = from
	_ray.to = from + dir * rng
	_ray.collision_mask = SHOT_MASK
	_ray.exclude = exclude
	_ray.collide_with_areas = false
	var hit := get_world_3d().direct_space_state.intersect_ray(_ray)
	stats.shots += 1
	var end: Vector3 = hit.position if hit else _ray.to
	tracer(from, end, String(w.get("tracer", "bullet")))
	if not hit:
		return {}
	var target := _target_of(hit.collider)
	var h := {"amount": float(w.get("damage", 10.0)), "stun": float(w.get("stun", 0.0)), "pos": hit.position,
		"normal": hit.normal, "dir": dir, "source": source, "weapon": String(w.id), "lethal": bool(w.get("lethal", true)),
		"headshot_mult": float(w.get("headshot", 1.0))}
	if source and "damage_scale" in source:
		h.amount *= float(source.damage_scale)
	if target:
		target.take_hit(h)
		stats.hits += 1
		if h.get("headshot", false):
			stats.headshots += 1
		for cb in hit_listeners:
			cb.call(h, target)
		audio.play("body_hit" if String(w.get("tracer", "")) != "arc" else "taser_hit", hit.position, 0.8)
	else:
		impact(hit.position, hit.normal, hit.collider, String(w.get("tracer", "bullet")) == "arc")
	return h


## Melee cone in front of `source`.
func melee(from: Vector3, fwd: Vector3, w: Dictionary, source: Node) -> int:
	var n := 0
	var cosc := cos(deg_to_rad(float(w.get("cone_deg", 50.0))))
	for c in get_tree().get_nodes_in_group("combatant"):
		if c == source or not (c is Node3D) or not c.has_method("take_hit"):
			continue
		var to: Vector3 = (c.global_position + Vector3.UP * 1.1) - from
		if to.length() > float(w.get("range", 2.2)) + 0.3:
			continue
		var tf := to
		tf.y = 0.0
		if tf.length() > 0.2 and tf.normalized().dot(Vector3(fwd.x, 0, fwd.z).normalized()) < cosc:
			continue
		var h := {"amount": float(w.get("damage", 5.0)), "stun": float(w.get("stun", 0.5)), "pos": from + to,
			"normal": -to.normalized(), "dir": to.normalized(), "source": source, "weapon": String(w.id),
			"lethal": bool(w.get("lethal", false)), "melee": true}
		c.take_hit(h)
		stats.hits += 1
		for cb in hit_listeners:
			cb.call(h, c)
		n += 1
	audio.play(String(w.sounds.get("hit" if n > 0 else "fire", "baton_swing")), from + fwd, 0.9)
	if n > 0:
		spark(from + fwd * 1.0, -fwd, true)
	return n


func _target_of(col: Object) -> Node:
	var n := col as Node
	for i in 4:
		if n == null:
			return null
		if n.has_method("take_hit"):
			return n
		n = n.get_parent()
	return null


## Bullet impact on the world: decal, sparks / chips, sound; street props react through the damage API.
func impact(pos: Vector3, normal: Vector3, col: Object, taser := false) -> void:
	var surf := _surface(col)
	if taser:
		spark(pos, normal, true)
		audio.play("taser_hit", pos, 0.5)
		return
	decal(pos, normal, surf)
	if surf == "metal":
		spark(pos, normal, false)
		audio.play("impact_metal", pos, 0.8, randf_range(0.9, 1.15))
		if randf() < 0.3:
			audio.play("ricochet", pos, 0.6, randf_range(0.85, 1.2))
	else:
		_fx_burst("chips" if surf != "glass" else "glass", pos, normal, 0.35)
		audio.play("impact_concrete", pos, 0.7, randf_range(0.9, 1.15))
	_props(pos, col)


func _surface(col: Object) -> String:
	if col is RigidBody3D or col is VehicleBody3D:
		return "metal"
	if col is Node and (col as Node).has_meta("surface"):
		return String(col.get_meta("surface"))
	if main and main.car and main.car.has_method("_surface_of"):
		var s := String(main.car._surface_of(col))
		if s in ["metal"]:
			return "metal"
	return "concrete"


## Additive hook into scripts/damage/destructibles.gd: glass and lamps near the hit.
func _props(pos: Vector3, _col: Object) -> void:
	if main == null or not ("damage" in main) or main.damage == null:
		return
	var de = main.damage.get("destructibles")
	if de == null:
		return
	for id in de.near(pos, 1.6):
		var nm := String(de.names[id])
		var d: Dictionary = de.defs.get(nm, {})
		if not d.get("glass", []).is_empty() and de.state[id] == 0:
			de.shatter_glass(id)
			stats.props += 1
			return
		if nm.contains("lamp") or String(d.get("kind", "")) == "lamp":
			if de.state[id] == 0 and randf() < 0.35:
				de.break_prop(id, Vector3.DOWN, 1.0)
				stats.props += 1
				return


# ================================================================== tracers / flashes
func _build_tracers() -> void:
	var box := BoxMesh.new()
	box.size = Vector3(0.018, 0.018, 1.0)
	for i in N_TRACERS:
		var mi := MeshInstance3D.new()
		mi.mesh = box
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		var m := StandardMaterial3D.new()
		m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
		m.albedo_color = Color(2.0, 1.6, 0.9)
		mi.material_override = m
		mi.visible = false
		add_child(mi)
		_tracers.append({"mi": mi, "t": 0.0, "life": 0.06, "mat": m})


func tracer(a: Vector3, b: Vector3, kind := "bullet") -> void:
	var len_ := a.distance_to(b)
	if len_ < 0.3:
		return
	var e: Dictionary = _tracers[_ti]
	_ti = (_ti + 1) % _tracers.size()
	var mi: MeshInstance3D = e.mi
	var arc := kind == "arc"
	# a streak a few metres long, travelling from the muzzle
	var streak := len_ if arc else minf(len_, 6.0)
	var mid := a.lerp(b, 0.5) if arc else a.lerp(b, clampf(0.35, 0.0, 1.0))
	mi.global_transform = Transform3D(Basis.looking_at((b - a).normalized(), Vector3.UP if absf((b - a).normalized().y) < 0.98 else Vector3.RIGHT), mid)
	mi.scale = Vector3(2.2 if arc else 1.0, 2.2 if arc else 1.0, streak)
	(e.mat as StandardMaterial3D).albedo_color = Color(0.5, 1.8, 2.4) if arc else Color(2.0, 1.6, 0.9)
	e.t = 0.0
	e.life = 0.12 if arc else 0.05
	e.a = a
	e.b = b
	e.arc = arc
	mi.visible = true
	stats.tracers += 1


func _build_flashes() -> void:
	var q := QuadMesh.new()
	q.size = Vector2(0.32, 0.32)
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	m.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
	m.albedo_texture = _star_texture()
	m.albedo_color = Color(2.2, 1.5, 0.7)
	m.disable_receive_shadows = true
	q.material = m
	for i in N_FLASH:
		var n := Node3D.new()
		var mi := MeshInstance3D.new()
		mi.mesh = q
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		n.add_child(mi)
		var l := OmniLight3D.new()
		l.light_color = Color(1.0, 0.75, 0.4)
		l.omni_range = 5.0
		l.light_energy = 0.0
		l.shadow_enabled = false
		n.add_child(l)
		n.visible = false
		add_child(n)
		_flashes.append({"node": n, "light": l, "mi": mi, "t": 1.0})


func muzzle_flash(pos: Vector3, dir: Vector3, cyan := false) -> void:
	var e: Dictionary = _flashes[_fi]
	_fi = (_fi + 1) % _flashes.size()
	var n: Node3D = e.node
	n.global_position = pos + dir * 0.05
	n.visible = true
	(e.light as OmniLight3D).light_color = Color(0.4, 0.9, 1.0) if cyan else Color(1.0, 0.72, 0.38)
	(e.light as OmniLight3D).light_energy = 3.5
	(e.mi as MeshInstance3D).scale = Vector3.ONE * randf_range(0.8, 1.3)
	(e.mi as MeshInstance3D).rotation.z = randf() * TAU
	e.t = 0.0


func _star_texture() -> Texture2D:
	var s := 64
	var img := Image.create(s, s, false, Image.FORMAT_RGBA8)
	for y in s:
		for x in s:
			var p := Vector2(x - s / 2.0 + 0.5, y - s / 2.0 + 0.5) / (s / 2.0)
			var r := p.length()
			var ang := atan2(p.y, p.x)
			var star := pow(absf(cos(ang * 3.0)), 8.0) * (1.0 - r)
			var core := clampf(1.0 - r * 2.2, 0.0, 1.0)
			var v := clampf(core + star * 0.9, 0.0, 1.0)
			img.set_pixel(x, y, Color(1, 1, 1, v))
	return ImageTexture.create_from_image(img)


# ================================================================== decals
func _build_decals() -> void:
	for k in ["concrete", "metal", "glass"]:
		_decal_tex[k] = _hole_texture(k)
	for i in N_DECALS:
		var d := Decal.new()
		d.size = Vector3(0.14, 0.1, 0.14)
		d.visible = false
		d.cull_mask = 1
		d.distance_fade_enabled = true
		d.distance_fade_begin = 40.0
		d.distance_fade_length = 15.0
		d.upper_fade = 0.2
		d.lower_fade = 0.2
		add_child(d)
		_decals.append(d)


func decal(pos: Vector3, normal: Vector3, surf: String) -> void:
	var d := _decals[_di]
	_di = (_di + 1) % _decals.size()
	var up := normal.normalized()
	var side := up.cross(Vector3.UP if absf(up.y) < 0.95 else Vector3.RIGHT).normalized()
	var fwd := side.cross(up)
	d.global_transform = Transform3D(Basis(side, up, fwd).rotated(up, randf() * TAU), pos)
	d.texture_albedo = _decal_tex.get(surf, _decal_tex.concrete)
	var s := randf_range(0.1, 0.16) * (1.6 if surf == "glass" else 1.0)
	d.size = Vector3(s, 0.12, s)
	d.visible = true
	stats.decals += 1


func _hole_texture(kind: String) -> Texture2D:
	var s := 64
	var img := Image.create(s, s, true, Image.FORMAT_RGBA8)
	var rnd := RandomNumberGenerator.new()
	rnd.seed = kind.hash()
	var spikes := PackedFloat32Array()
	for i in 24:
		spikes.append(rnd.randf())
	for y in s:
		for x in s:
			var p := Vector2(x - s / 2.0 + 0.5, y - s / 2.0 + 0.5) / (s / 2.0)
			var r := p.length()
			var a := (atan2(p.y, p.x) + PI) / TAU
			var sp := spikes[int(a * 24.0) % 24]
			var c := Color(0, 0, 0, 0)
			match kind:
				"metal":
					var hole := 1.0 - smoothstep(0.12, 0.2, r)
					var ring := (1.0 - smoothstep(0.2, 0.45 + sp * 0.2, r)) * 0.8
					c = Color(0.05, 0.05, 0.05, hole) if hole > 0.5 else Color(0.75, 0.72, 0.68, ring)
				"glass":
					var hole := 1.0 - smoothstep(0.06, 0.12, r)
					var crack := pow(absf(cos(a * TAU * 6.0 + sp)), 40.0) * (1.0 - r) * 0.9
					var ring := (1.0 - smoothstep(0.12, 0.3, r)) * 0.6
					c = Color(0.85, 0.9, 1.0, clampf(hole + crack + ring, 0.0, 1.0))
					if hole > 0.5:
						c = Color(0.02, 0.02, 0.03, hole)
				_:
					var hole := 1.0 - smoothstep(0.1, 0.2, r)
					var chip := (1.0 - smoothstep(0.18, 0.55 + sp * 0.35, r)) * 0.75
					c = Color(0.03, 0.03, 0.03, hole) if hole > 0.5 else Color(0.18, 0.17, 0.16, chip)
			img.set_pixel(x, y, c)
	img.generate_mipmaps()
	return ImageTexture.create_from_image(img)


# ================================================================== casings (one MultiMesh)
func _build_casings() -> void:
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.0055
	cyl.bottom_radius = 0.0055
	cyl.height = 0.022
	cyl.radial_segments = 6
	cyl.rings = 1
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(0.85, 0.62, 0.28)
	m.metallic = 1.0
	m.roughness = 0.3
	cyl.material = m
	_casing_mm = MultiMesh.new()
	_casing_mm.transform_format = MultiMesh.TRANSFORM_3D
	_casing_mm.mesh = cyl
	_casing_mm.instance_count = N_CASINGS
	_casing_mm.visible_instance_count = N_CASINGS
	var mmi := MultiMeshInstance3D.new()
	mmi.name = "Casings"
	mmi.multimesh = _casing_mm
	mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	mmi.custom_aabb = AABB(Vector3(-1e5, -1e4, -1e5), Vector3(2e5, 2e4, 2e5))
	add_child(mmi)
	for i in N_CASINGS:
		_casings.append({"p": Vector3(0, -1e4, 0), "v": Vector3.ZERO, "r": Basis(), "w": Vector3.ZERO, "t": 99.0, "floor": -1e4, "rest": true})
		_casing_mm.set_instance_transform(i, Transform3D(Basis().scaled(Vector3.ZERO), Vector3(0, -1e4, 0)))


func eject_casing(pos: Vector3, right: Vector3) -> void:
	var e: Dictionary = _casings[_ci]
	_ci = (_ci + 1) % _casings.size()
	e.p = pos
	e.v = right * randf_range(1.6, 2.4) + Vector3.UP * randf_range(1.4, 2.2) + Vector3(randf() - 0.5, 0, randf() - 0.5) * 0.4
	e.w = Vector3(randf() - 0.5, randf() - 0.5, randf() - 0.5) * 30.0
	e.r = Basis()
	e.t = 0.0
	e.rest = false
	e.placed = false
	_ray.from = pos + Vector3.UP * 0.2
	_ray.to = pos + Vector3.DOWN * 4.0
	_ray.collision_mask = 1
	_ray.exclude = []
	var h := get_world_3d().direct_space_state.intersect_ray(_ray)
	e.floor = h.position.y + 0.006 if h else pos.y - 1.5
	e.bounced = false
	stats.casings += 1


func _tick_casings(dt: float) -> void:
	for i in _casings.size():
		var e: Dictionary = _casings[i]
		if e.t > 6.0:
			continue
		e.t += dt
		if e.rest and e.t < 5.5 and e.get("placed", false):
			continue
		if not e.rest:
			e.v.y -= 9.81 * dt
			e.p += e.v * dt
			if e.w.length() > 0.01:
				e.r = (e.r * Basis(e.w.normalized(), e.w.length() * dt)).orthonormalized()
			if e.p.y < e.floor:
				e.p.y = e.floor
				if not e.bounced and e.v.y < -1.0:
					e.bounced = true
					e.v = Vector3(e.v.x * 0.4, -e.v.y * 0.3, e.v.z * 0.4)
					e.w *= 0.5
					if i % 3 == 0:
						audio.play("casing_tink", e.p, 0.4, randf_range(0.9, 1.3))
				else:
					e.rest = true
					e.r = Basis(Vector3.FORWARD, PI * 0.5).rotated(Vector3.UP, randf() * TAU)
		var sc := 1.0 if e.t < 5.5 else clampf((6.0 - e.t) * 2.0, 0.0, 1.0)
		e.placed = e.rest
		_casing_mm.set_instance_transform(i, Transform3D(e.r.scaled(Vector3.ONE * sc), e.p))


# ================================================================== sparks
func _build_sparks() -> void:
	for i in N_SPARKS:
		var p := GPUParticles3D.new()
		p.one_shot = true
		p.emitting = false
		p.amount = 14
		p.lifetime = 0.35
		p.explosiveness = 1.0
		p.local_coords = false
		p.visibility_aabb = AABB(Vector3(-4, -4, -4), Vector3(8, 8, 8))
		var pm := ParticleProcessMaterial.new()
		pm.direction = Vector3(0, 1, 0)
		pm.spread = 55.0
		pm.initial_velocity_min = 3.0
		pm.initial_velocity_max = 8.0
		pm.gravity = Vector3(0, -12, 0)
		pm.scale_min = 0.6
		pm.scale_max = 1.2
		p.process_material = pm
		var q := QuadMesh.new()
		q.size = Vector2(0.012, 0.09)
		var m := StandardMaterial3D.new()
		m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
		m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
		m.vertex_color_use_as_albedo = true
		m.albedo_color = Color(2.5, 1.7, 0.8)
		q.material = m
		p.draw_pass_1 = q
		p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(p)
		_sparks.append(p)


func spark(pos: Vector3, normal: Vector3, cyan: bool) -> void:
	var p := _sparks[_si]
	_si = (_si + 1) % _sparks.size()
	var d := normal.normalized() if normal.length() > 0.01 else Vector3.UP
	var up := Vector3.UP if absf(d.y) < 0.95 else Vector3.FORWARD
	var x := up.cross(d).normalized()
	p.global_transform = Transform3D(Basis(x, d, x.cross(d)), pos)
	((p.draw_pass_1 as QuadMesh).material as StandardMaterial3D).albedo_color = Color(0.6, 1.8, 2.6) if cyan else Color(2.5, 1.7, 0.8)
	p.restart()
	p.emitting = true


func _fx_burst(kind: String, pos: Vector3, n: Vector3, s: float) -> void:
	var fx = main.damage.get("fx") if main and "damage" in main and main.damage else null
	if fx and fx.has_method("burst"):
		fx.burst(kind, pos, n, s)
	else:
		spark(pos, n, false)


# ================================================================== EMP charges
func _build_emps() -> void:
	for i in N_EMP:
		var n := Node3D.new()
		var mi := MeshInstance3D.new()
		var s := SphereMesh.new()
		s.radius = 0.06
		s.height = 0.12
		s.radial_segments = 8
		s.rings = 4
		var m := StandardMaterial3D.new()
		m.albedo_color = Color(0.08, 0.09, 0.1)
		m.emission_enabled = true
		m.emission = Color(0.3, 0.9, 1.0)
		m.emission_energy_multiplier = 2.0
		s.material = m
		mi.mesh = s
		n.add_child(mi)
		var ring := MeshInstance3D.new()
		var sp := SphereMesh.new()
		sp.radius = 1.0
		sp.height = 2.0
		sp.radial_segments = 24
		sp.rings = 12
		var rm := StandardMaterial3D.new()
		rm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		rm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		rm.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
		rm.cull_mode = BaseMaterial3D.CULL_DISABLED
		rm.albedo_color = Color(0.3, 0.85, 1.0, 0.35)
		rm.disable_receive_shadows = true
		sp.material = rm
		ring.mesh = sp
		ring.visible = false
		ring.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		ring.top_level = true
		n.add_child(ring)
		var l := OmniLight3D.new()
		l.light_color = Color(0.4, 0.85, 1.0)
		l.omni_range = 9.0
		l.light_energy = 0.0
		n.add_child(l)
		n.visible = false
		add_child(n)
		_emps.append({"node": n, "ring": ring, "rmat": rm, "light": l, "live": false, "t": 0.0, "p": Vector3.ZERO, "v": Vector3.ZERO, "blast": -1.0})


func throw_emp(from: Vector3, vel: Vector3, w: Dictionary, source: Node) -> void:
	for e in _emps:
		if not e.live and e.blast < 0.0:
			e.live = true
			e.p = from
			e.v = vel
			e.t = 0.0
			e.def = w
			e.source = source
			e.node.visible = true
			e.node.global_position = from
			audio.play(String(w.sounds.get("fire", "emp_throw")), from, 0.6)
			return


func _tick_emps(dt: float) -> void:
	for e in _emps:
		if e.live:
			e.t += dt
			var np: Vector3 = e.p + e.v * dt
			e.v.y -= 9.81 * dt
			_ray.from = e.p
			_ray.to = np
			_ray.collision_mask = 1 | 2
			_ray.exclude = []
			var h := get_world_3d().direct_space_state.intersect_ray(_ray)
			if h:
				var n: Vector3 = h.normal
				e.v = (e.v - 2.0 * e.v.dot(n) * n) * 0.35
				np = h.position + n * 0.07
			e.p = np
			e.node.global_position = np
			if int(e.t * 6.0) != int((e.t - dt) * 6.0):
				audio.play(String(e.def.sounds.get("arm", "emp_arm")), np, 0.3, 1.0 + e.t * 0.3)
			if e.t >= float(e.def.get("fuse", 1.4)):
				_detonate(e)
		elif e.blast >= 0.0:
			e.blast += dt
			var k: float = e.blast / 0.6
			var r: float = float(e.def.get("radius", 7.0)) * clampf(k * 1.3, 0.0, 1.0)
			e.ring.global_position = e.p
			e.ring.scale = Vector3.ONE * maxf(r, 0.01)
			e.rmat.albedo_color = Color(0.3, 0.85, 1.0, 0.35 * (1.0 - k))
			e.light.light_energy = 6.0 * (1.0 - k)
			if k >= 1.0:
				e.blast = -1.0
				e.ring.visible = false
				e.node.visible = false
				e.light.light_energy = 0.0


func _detonate(e: Dictionary) -> void:
	e.live = false
	e.blast = 0.0
	e.ring.visible = true
	stats.emp += 1
	var w: Dictionary = e.def
	var rad := float(w.get("radius", 7.0))
	audio.play(String(w.sounds.get("blast", "emp_blast")), e.p, 1.0)
	noise(e.p, 30.0)
	for c in get_tree().get_nodes_in_group("combatant"):
		if c is Node3D and c.has_method("take_hit") and (c as Node3D).global_position.distance_to(e.p) < rad:
			var h := {"amount": 0.0, "stun": float(w.get("stun", 1.0)), "pos": (c as Node3D).global_position + Vector3.UP,
				"normal": Vector3.UP, "dir": ((c as Node3D).global_position - e.p).normalized(), "source": e.source,
				"weapon": "emp", "lethal": false, "emp": true}
			c.take_hit(h)
			for cb in hit_listeners:
				cb.call(h, c)
	# stall cars in the radius (the courier's getaway): car.gd power_scale back after a few seconds
	for c in get_tree().get_nodes_in_group("emp_car"):
		if c is RigidBody3D and (c as Node3D).global_position.distance_to(e.p) < rad + 2.0 and "power_scale" in c:
			c.set_meta("emp_until", Time.get_ticks_msec() + int(float(w.get("stall_cars", 5.0)) * 1000.0))
	spark(e.p, Vector3.UP, true)


# ================================================================== hearing
func noise(pos: Vector3, radius: float) -> void:
	noise_events.append([pos, radius, Time.get_ticks_msec()])
	if noise_events.size() > 16:
		noise_events.pop_front()


## The loudest recent noise `p` can hear (null if none within its radius in the last `ms`).
func heard(p: Vector3, ms := 1500):
	var now := Time.get_ticks_msec()
	for i in range(noise_events.size() - 1, -1, -1):
		var n: Array = noise_events[i]
		if now - int(n[2]) > ms:
			break
		if p.distance_to(n[0]) < float(n[1]):
			return n[0]
	return null


# ================================================================== per frame
func _process(dt: float) -> void:
	var t0 := Time.get_ticks_usec()
	for e in _tracers:
		if e.mi.visible:
			e.t += dt
			if e.t >= e.life:
				e.mi.visible = false
			elif not e.get("arc", false):
				# the streak flies down the line
				var a: Vector3 = e.a
				var b: Vector3 = e.b
				var k := clampf(e.t / e.life, 0.0, 1.0)
				e.mi.global_position = a.lerp(b, clampf(0.25 + k * 0.7, 0.0, 1.0))
	for e in _flashes:
		if e.t < 1.0:
			e.t += dt
			if e.t > 0.05:
				e.node.visible = false
				e.light.light_energy = 0.0
				e.t = 1.0
			else:
				e.light.light_energy = 3.5 * (1.0 - e.t / 0.05)
	_tick_casings(dt)
	_tick_emps(dt)
	prof_us = lerpf(prof_us, float(Time.get_ticks_usec() - t0), 0.05)
