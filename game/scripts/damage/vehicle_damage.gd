extends Node3D
## Damage for one vehicle (the hero, or a traffic car while it is a physics body near the player).
##
## Impacts: the body's velocity change per physics tick (contacts present) above DV_HIT starts an impact;
## the ticks of one crash are summed (impulse J = m * |dv|, the point from the contact positions, the
## direction of dv), then committed once. Contacts sliding past at speed are scrapes: sparks + a grind.
##
## What an impact does (e = J / 1000 N s; a 30 km/h wall hit is e ~ 11, 60 km/h e ~ 22):
##   * soft deformation (vehicle_deform.gd): the body and the attached door / hood / trunk / bumper
##     meshes are pushed in around the impact point (radius and depth grow with e, clamped), with a
##     crumple noise; repeated hits accumulate. CPU, only on impacts (traffic: only within DEFORM_NEAR
##     of the camera).
##   * panel health (from the car json's "damage" panels: tools/vehicles/damage_panels.py): a panel
##     loses e * K * falloff(distance to its box). Doors, hood and trunk come loose (a HingeJoint3D on
##     their hinge, swinging; the hood flaps up at speed), bumpers hang from one end, then everything
##     falls off as debris. Mirrors snap off. Side glass shatters (gone + shards); the windscreen and
##     rear window crack first (an overlay), then shatter. Lenses break and darken their lamps.
##   * zones / engine / wheels: front, rear, left, right; the engine (front hits) steams, then smokes
##     black and loses power (car.power_scale); a hit front wheel pulls the steering (car.steer_pull).
## reset() puts everything back (R).

const Deform := preload("res://scripts/damage/vehicle_deform.gd")
const CRACK_SHADER := preload("res://scripts/damage/glass_crack.gdshader")
const CRACK_TEX := "res://assets/damage/glass_crack.png"

const DV_HIT := 1.25            ## m/s in one tick (~15 g at 120 Hz): an impact
const DEFORM_NEAR := 40.0       ## traffic cars deform only this close to the camera
const K := {"door": 1.0, "hood": 1.1, "trunk": 1.0, "bumper": 1.5, "mirror": 2.6, "glass": 1.25, "lens": 2.0, "lamp": 0.0}
const LOOSE_AT := 55.0
const SCRAPE_V := 2.6

signal changed
signal hit(pos: Vector3, impulse: float)

var world: Node                 ## damage_manager.gd (fx, audio, debris)
var body: RigidBody3D
var hero := false
var spec := {}
var panels := {}                ## node name -> panel dict
var order: Array = []           ## panel names, parents first
var deformers: Array = []       ## [Deform] for Body + door / hood / trunk / bumper meshes
var deform_enabled := true
var engine := 0.0               ## 0..1
var zones := {"front": 0.0, "rear": 0.0, "left": 0.0, "right": 0.0}
var wheel_dmg := {"FL": 0.0, "FR": 0.0, "RL": 0.0, "RR": 0.0}
var lights_out := {}            ## "Headlight_L" -> true
var stats := {"impacts": 0, "max_impulse": 0.0, "detached": 0, "loose": 0, "glass": 0, "lenses": 0, "deformed": 0,
	"deform_ms": 0.0, "scrape_s": 0.0}

var _root: Node3D               ## parent of the visual meshes (car space)
var _body_mi: MeshInstance3D
var _last_v := Vector3.ZERO
var _acc := {}                  ## pending impact: {j, p, d, n, other}
var _scrape_t := 0.0
var _scrape_snd: AudioStreamPlayer3D
var _smoke: GPUParticles3D
var _smoke_pos := Vector3.ZERO
var _wheel_pos := {}
var _crack_mat: ShaderMaterial
var _dark_mats := {}
var _electric := false
var _setup_ok := false
var _debug := OS.get_cmdline_user_args().has("--damage-debug")


## meshes: node name -> MeshInstance3D (Body and the panels); root: their parent in car space.
func setup(w: Node, b: RigidBody3D, root: Node3D, meshes: Dictionary, sp: Dictionary, is_hero: bool) -> void:
	world = w
	body = b
	hero = is_hero
	spec = sp
	_root = root
	name = "Damage"
	process_physics_priority = 50          # after the car's own tick
	_electric = String(sp.get("class", "")) == "robotaxi" or bool(sp.get("electric", false))
	_body_mi = meshes.get("Body")
	for wn in ["FL", "FR", "RL", "RR"]:
		var wp: Array = sp.get("wheel_positions", {}).get("Wheel_" + wn, [0.8 if wn.ends_with("L") else -0.8, 0.33, 1.3 if wn[0] == "F" else -1.3])
		_wheel_pos[wn] = Vector3(float(wp[0]), float(wp[1]), float(wp[2]))
	var list: Array = sp.get("damage", {}).get("panels", [])
	# parents first
	var left := list.duplicate()
	var placed := {}
	var guard := 0
	while not left.is_empty() and guard < 100:
		guard += 1
		for p in left.duplicate():
			var par = p.get("parent")
			if par == null or placed.has(par) or not list.any(func(q): return q.node == par):
				order.append(String(p.node))
				placed[p.node] = true
				left.erase(p)
	for p in list:
		var mi: MeshInstance3D = meshes.get(String(p.node))
		if mi == null:
			continue
		var a: Array = p.aabb
		var lo := Vector3(a[0][0], a[0][1], a[0][2])
		var hi := Vector3(a[1][0], a[1][1], a[1][2])
		var pv: Array = p.pivot
		var d := {"node": String(p.node), "kind": String(p.kind), "parent": p.get("parent"), "mi": mi,
			"pivot_pos": Vector3(pv[0], pv[1], pv[2]), "aabb": AABB(lo, hi - lo), "mass": float(p.get("mass_kg", 5.0)),
			"axis": _v3(p.get("hinge_axis", [0, 0, 0])), "sign": float(p.get("open_sign", 0)),
			"limit": deg_to_rad(float((p.get("limits_deg", [0, 60]) as Array)[1])) if p.has("limits_deg") else 0.0,
			"lamps": p.get("lamps", []), "health": 100.0, "state": "ok", "children": [], "pivot": null,
			"rb": null, "joint": null, "home": null, "vis": mi.visible}
		panels[d.node] = d
	for nm in order:
		if not panels.has(nm):
			continue
		var d: Dictionary = panels[nm]
		var par_node: Node3D = _root
		if d.parent != null and panels.has(d.parent):
			par_node = panels[d.parent].pivot
			panels[d.parent].children.append(nm)
		var pv := Node3D.new()
		pv.name = nm + "_Pivot"
		par_node.add_child(pv)
		pv.global_transform = _root.global_transform * Transform3D(Basis(), d.pivot_pos)
		var mi: MeshInstance3D = d.mi
		var g := mi.global_transform
		mi.get_parent().remove_child(mi)
		pv.add_child(mi)
		mi.global_transform = g
		d.pivot = pv
		d.home = pv.transform
	# deformable meshes (lazy: a mesh copy is only made on its first dent)
	if _body_mi:
		deformers.append(Deform.new(_body_mi))
	for nm in order:
		if panels.has(nm) and panels[nm].kind in ["door", "hood", "trunk", "bumper"]:
			deformers.append(Deform.new(panels[nm].mi))
	if hero:
		for df in deformers:
			df.prepare_async()
	_smoke_pos = _engine_pos()
	_last_v = body.linear_velocity
	_setup_ok = true


static func _v3(a) -> Vector3:
	return Vector3(float(a[0]), float(a[1]), float(a[2])) if a is Array and a.size() >= 3 else Vector3.ZERO


func _engine_pos() -> Vector3:
	if panels.has("Hood"):
		var b: AABB = panels.Hood.aabb
		return Vector3(b.get_center().x, b.position.y + b.size.y * 0.6, b.get_center().z + b.size.z * 0.1)
	var zf: float = _wheel_pos.FL.z
	return Vector3(0, 0.95, zf + 0.25)


## 0..1 overall (HUD): the worst zone dominates.
func total() -> float:
	var mx := 0.0
	var sum := 0.0
	for k in zones:
		mx = maxf(mx, zones[k])
		sum += zones[k]
	return clampf(mx * 0.65 + sum * 0.25 * 0.35 + engine * 0.15, 0.0, 1.0)


# ------------------------------------------------------------------ physics
func _physics_process(delta: float) -> void:
	if not _setup_ok or not is_instance_valid(body):
		return
	if body.freeze:
		_last_v = body.linear_velocity
		_flush()
		return
	var v := body.linear_velocity
	var dv := v - _last_v
	_last_v = v
	var n := body.get_contact_count() if body.contact_monitor else 0
	var st := PhysicsServer3D.body_get_direct_state(body.get_rid()) if n > 0 else null
	if st and dv.length() > DV_HIT:
		var p := Vector3.ZERO
		var cnt := 0
		var other: Object = null
		for i in st.get_contact_count():
			var o := st.get_contact_collider_object(i)
			if o and world.debris and o is RigidBody3D and o.get_parent() == world.debris:
				continue
			p += st.get_contact_local_position(i)
			cnt += 1
			if other == null:
				other = o
		if cnt > 0:
			p /= cnt
			var j := body.mass * dv.length()
			if _acc.is_empty():
				_acc = {"j": 0.0, "p": Vector3.ZERO, "d": Vector3.ZERO, "w": 0.0, "n": 0, "other": other}
			_acc.j += j
			_acc.p += p * j
			_acc.d += dv
			_acc.w += j
			_acc.n += 1
			if _acc.n >= 5:
				_flush()
			return
	_flush()
	# scrapes: contacts sliding past at speed (walls, the road when on the roof or a side)
	_scrape(st, delta)
	_tick_effects(delta)


func _flush() -> void:
	if _acc.is_empty():
		return
	var a := _acc
	_acc = {}
	if a.w <= 0.0:
		return
	apply_impact(a.p / a.w, a.d.normalized(), a.j, a.other)


func _scrape(st: PhysicsDirectBodyState3D, delta: float) -> void:
	var scraping := false
	if st:
		var com := body.global_transform * body.center_of_mass
		for i in st.get_contact_count():
			var p := st.get_contact_local_position(i)
			var nrm := st.get_contact_local_normal(i)
			var vr := body.linear_velocity + body.angular_velocity.cross(p - com)
			var vt := vr - nrm * vr.dot(nrm)
			if vt.length() > SCRAPE_V:
				scraping = true
				_scrape_t -= delta
				if _scrape_t <= 0.0:
					_scrape_t = 0.045
					world.fx.burst("sparks", p, (nrm * 0.6 - vt.normalized()).normalized(), clampf(vt.length() / 12.0, 0.3, 1.6))
				stats.scrape_s += delta
				if _scrape_snd == null and world.audio:
					_scrape_snd = world.audio.loop("metal_scrape", self, -60.0)
				if _scrape_snd:
					_scrape_snd.global_position = p
					_scrape_snd.volume_db = lerpf(_scrape_snd.volume_db, lerpf(-14.0, 0.0, clampf(vt.length() / 20.0, 0.0, 1.0)), 0.3)
				break
	if not scraping and _scrape_snd:
		_scrape_snd.volume_db = lerpf(_scrape_snd.volume_db, -60.0, 0.15)


## The impact itself: `pw` world point, `dir` the direction the car was pushed, `j` impulse (N s).
func apply_impact(pw: Vector3, dir: Vector3, j: float, other: Object = null) -> void:
	var inv := body.global_transform.affine_inverse()
	var pl := inv * pw
	var dl := (body.global_basis.inverse() * dir).normalized()
	var e := j / 1000.0
	if _debug:
		print("impact %s j=%d pl=%s dl=%s" % [body.name, j, pl, dl])
	stats.impacts += 1
	stats.max_impulse = maxf(stats.max_impulse, j)
	hit.emit(pw, j)
	if world.audio:
		world.audio.crash(pw, j)
	world.fx.burst("chips", pw, -dir, clampf(e / 12.0, 0.2, 1.5))
	if e > 5.0:
		world.fx.burst("sparks", pw, -dir + Vector3.UP * 0.5, clampf(e / 15.0, 0.4, 1.6))
	if e > 9.0:
		world.fx.burst("dust", pw, Vector3.UP, clampf(e / 20.0, 0.3, 1.4))
	# soft deformation
	if deform_enabled and e > 2.5 and _may_deform():
		var radius := clampf(0.32 + 0.024 * e, 0.32, 0.95)
		var depth := clampf(0.0095 * e, 0.0, 0.21)
		var t0 := Time.get_ticks_usec()
		for df in deformers:
			if is_instance_valid(df.mi) and df.mi.is_visible_in_tree() and _attached(df.mi):
				var mv: int = df.dent(body.global_transform, pl, dl, radius, depth)
				stats.deformed += mv
				if _debug:
					print("  dent %s: %d verts" % [df.mi.name, mv])
		stats.deform_ms = maxf(stats.deform_ms, (Time.get_ticks_usec() - t0) / 1000.0)
	# zones, engine, wheels
	var hl: float = maxf(absf(_wheel_pos.FL.z), 1.5)
	var fz := clampf(pl.z / hl, -1.5, 1.5)
	var sx := clampf(pl.x / 0.85, -1.5, 1.5)
	var amt := e * 0.032
	if fz > 0.55:
		zones.front = minf(1.0, zones.front + amt * clampf(fz, 0.5, 1.2))
		if not _electric:
			engine = minf(1.0, engine + e * 0.024 * clampf(fz - 0.3, 0.0, 1.0))
	if fz < -0.55:
		zones.rear = minf(1.0, zones.rear + amt * clampf(-fz, 0.5, 1.2))
	if sx > 0.5:
		zones.left = minf(1.0, zones.left + amt * clampf(sx, 0.5, 1.2))
	if sx < -0.5:
		zones.right = minf(1.0, zones.right + amt * clampf(-sx, 0.5, 1.2))
	for wn in wheel_dmg:
		var dw: float = (_wheel_pos[wn] as Vector3).distance_to(pl)
		if dw < 0.8:
			wheel_dmg[wn] = minf(1.0, wheel_dmg[wn] + e * 0.035 * (1.0 - dw / 0.8))
	# panels
	var r := 0.55 + 0.022 * e
	for nm in order:
		if not panels.has(nm):
			continue
		var d: Dictionary = panels[nm]
		if d.state == "off" or d.state == "gone" or K.get(d.kind, 0.0) <= 0.0:
			continue
		var box: AABB = _panel_box(d)
		var dist := _box_dist(box, pl)
		if dist > r:
			continue
		var dmg: float = e * 4.5 * K[d.kind] * (1.0 - dist / r)
		if d.kind == "glass" and nm in ["Glass_Windshield", "Glass_RearWindow"]:
			dmg *= 0.75
		_damage_panel(d, dmg, pl, dl, j)
	# a big frontal / rear shock cracks the screens even away from the hit
	if e > 12.0:
		for nm in ["Glass_Windshield", "Glass_RearWindow"]:
			if panels.has(nm) and panels[nm].state == "ok" and signf(pl.z) == (1.0 if nm == "Glass_Windshield" else -1.0):
				_damage_panel(panels[nm], (e - 10.0) * 4.0, pl, dl, j)
	_apply_performance()
	# the other car: a kinematic / parked traffic car doesn't feel the hit itself
	if other and world.has_method("forward_impact"):
		world.forward_impact(other, pw, -dir, j)
	changed.emit()


func _may_deform() -> bool:
	if hero:
		return true
	var cam := get_viewport().get_camera_3d()
	return cam == null or cam.global_position.distance_to(body.global_position) < DEFORM_NEAR


## Is this mesh still on the car (not on a debris body)?
func _attached(mi: Node) -> bool:
	var n := mi.get_parent()
	while n:
		if n == body:
			return true
		if n is RigidBody3D:
			return false
		n = n.get_parent()
	return false


func _panel_box(d: Dictionary) -> AABB:
	if d.state == "ok":
		return d.aabb
	# loose: move its box with it (pivot space -> car space)
	var pv: Node3D = d.pivot
	if not is_instance_valid(pv):
		return d.aabb
	var xf := body.global_transform.affine_inverse() * pv.global_transform
	var local: AABB = d.aabb
	local.position -= d.pivot_pos
	return xf * local


static func _box_dist(b: AABB, p: Vector3) -> float:
	var q := p.clamp(b.position, b.end)
	return q.distance_to(p)


func _damage_panel(d: Dictionary, dmg: float, pl: Vector3, dl: Vector3, j: float) -> void:
	d.health -= dmg
	match d.kind:
		"door", "hood", "trunk", "bumper":
			if d.health <= 0.0:
				_detach(d, dl, j)
			elif d.health <= LOOSE_AT and d.state == "ok":
				_loosen(d, pl, dl)
		"mirror":
			if d.health <= 60.0:
				_detach(d, dl, j)
		"glass":
			var big: bool = d.node in ["Glass_Windshield", "Glass_RearWindow"]
			if big and d.state == "ok" and d.health <= 72.0:
				_crack(d, pl)
			if d.health <= (12.0 if big else 70.0) and d.state != "gone":
				_shatter(d)
		"lens":
			if d.health <= 65.0 and d.state != "gone":
				_break_lens(d)


# ------------------------------------------------------------------ panel states
func _shapes_for(d: Dictionary) -> Array:
	var b: AABB = d.aabb
	var sz := b.size.max(Vector3(0.03, 0.03, 0.03))
	var bs := BoxShape3D.new()
	bs.size = sz
	return [[bs, Transform3D(Basis(), b.get_center() - d.pivot_pos)]]


## Loose: the panel hangs on a hinge (doors, hood, trunk) or from one end (bumpers).
func _loosen(d: Dictionary, pl: Vector3, _dl: Vector3) -> void:
	var pv: Node3D = d.pivot
	var axis_local: Vector3 = d.axis
	var sign: float = d.sign
	var limit: float = d.limit
	if d.kind == "bumper":
		# hang from the end away from the hit: rotate about the car's Z at that end
		var b: AABB = d.aabb
		var keep_x := b.position.x if pl.x > b.get_center().x else b.end.x
		var new_pivot := Vector3(keep_x, b.get_center().y, b.get_center().z)
		var shift: Vector3 = new_pivot - d.pivot_pos
		pv.position += shift             # pivots sit axis-aligned in car space
		for c in pv.get_children():      # the mesh keeps its place
			if c is Node3D:
				(c as Node3D).position -= shift
		d.pivot_pos = new_pivot
		axis_local = Vector3(0, 0, 1)
		var free_dx := b.get_center().x - keep_x
		sign = -signf(free_dx) if absf(free_dx) > 0.01 else 1.0
		limit = deg_to_rad(65.0)
	if axis_local == Vector3.ZERO:
		_detach(d, Vector3.ZERO, 0.0)
		return
	d.state = "loose"
	stats.loose += 1
	var xf := pv.global_transform
	var rb: RigidBody3D = world.debris.spawn([pv], _shapes_for(d), xf, d.mass,
		{"vel": body.linear_velocity, "angvel": body.angular_velocity, "kind": "metal", "pinned": true, "name": "Panel_" + d.node,
		"on_free": _reclaim.bind(d.node)})
	pv.transform = Transform3D()      # the pivot node now sits at the body's origin
	rb.add_collision_exception_with(body)
	body.add_collision_exception_with(rb)
	var jt := HingeJoint3D.new()
	jt.name = "Hinge_" + d.node
	world.debris.add_child(jt)
	if d.kind == "door":
		# a sprung hinge sags: the axis leans out at the top, so gravity swings the door open
		axis_local = Vector3(0.24 * signf(d.pivot_pos.x), 1.0, 0.0).normalized()
	var ax_w: Vector3 = (body.global_basis * axis_local).normalized()
	var up := Vector3.UP if absf(ax_w.dot(Vector3.UP)) < 0.9 else Vector3.RIGHT
	var x := up.cross(ax_w).normalized()
	jt.global_transform = Transform3D(Basis(x, ax_w.cross(x), ax_w), xf.origin)
	jt.node_a = jt.get_path_to(body)
	jt.node_b = jt.get_path_to(rb)
	jt.set_flag(HingeJoint3D.FLAG_USE_LIMIT, true)
	var lo := minf(0.0, sign * limit)
	var hi := maxf(0.0, sign * limit)
	# the joint measures B's turn relative to A about its Z; a little slack past closed
	jt.set_param(HingeJoint3D.PARAM_LIMIT_LOWER, lo - 0.03)
	jt.set_param(HingeJoint3D.PARAM_LIMIT_UPPER, hi + 0.03)
	jt.exclude_nodes_from_collision = true
	d.rb = rb
	d.joint = jt
	# a kick open
	rb.angular_velocity = body.angular_velocity + ax_w * sign * 2.5
	if world.audio:
		world.audio.play("metal_crunch_light", xf.origin, 0.5)


## Off: falls away as debris (with whatever is mounted on it).
func _detach(d: Dictionary, dl: Vector3, j: float) -> void:
	if d.state == "off":
		return
	var was_loose: bool = d.state == "loose"
	d.state = "off"
	stats.detached += 1
	for c in d.children:
		if panels.has(c):
			panels[c].state = "off" if panels[c].state != "gone" else "gone"
	if was_loose and is_instance_valid(d.joint):
		d.joint.queue_free()
		d.joint = null
		world.debris.set_pinned(d.rb, false, 150.0)
		(d.rb as RigidBody3D).apply_central_impulse(-(body.global_basis * dl) * minf(j * 0.004, 60.0))
		return
	var pv: Node3D = d.pivot
	var xf := pv.global_transform
	var kick := body.global_basis * (-dl) * clampf(j / 2500.0, 0.5, 6.0) + Vector3.UP * randf_range(0.5, 2.0)
	var rb: RigidBody3D = world.debris.spawn([pv], _shapes_for(d), xf, d.mass,
		{"vel": body.linear_velocity * 0.85 + kick, "angvel": Vector3(randf_range(-4, 4), randf_range(-4, 4), randf_range(-4, 4)),
		"kind": "metal", "life": 150.0, "name": "Panel_" + d.node, "on_free": _reclaim.bind(d.node)})
	pv.transform = Transform3D()
	rb.add_collision_exception_with(body)
	d.rb = rb
	if world.audio:
		world.audio.play("plastic_clatter" if d.kind in ["mirror", "bumper"] else "metal_crunch_light", xf.origin, 0.7)


## The debris pool lets a fallen panel go (far away / old): its pivot comes back to the car, hidden,
## so reset() can put it on again (the pool frees what is left in the body).
func _reclaim(rb: RigidBody3D, nm: String) -> void:
	if not panels.has(nm) or not is_instance_valid(body):
		return
	var d: Dictionary = panels[nm]
	var pv: Node3D = d.pivot
	if is_instance_valid(pv) and pv.get_parent() == rb:
		rb.remove_child(pv)
		_root.add_child(pv)
		pv.visible = false
		d["hidden_pivot"] = true
	if d.rb == rb:
		d.rb = null
	if is_instance_valid(d.joint):
		d.joint.queue_free()
		d.joint = null


func _crack(d: Dictionary, pl: Vector3) -> void:
	d.state = "cracked"
	var mi: MeshInstance3D = d.mi
	var m := ShaderMaterial.new()
	m.shader = CRACK_SHADER
	if ResourceLoader.exists(CRACK_TEX):
		m.set_shader_parameter("crack_tex", load(CRACK_TEX))
	var to_mesh := mi.global_transform.affine_inverse() * body.global_transform
	m.set_shader_parameter("center", to_mesh * pl.clamp(d.aabb.position, d.aabb.end))
	var n := Vector3(0, 0.45, 1.0) if d.node == "Glass_Windshield" else Vector3(0, 0.45, -1.0)
	m.set_shader_parameter("normal", (to_mesh.basis * n).normalized())
	m.set_shader_parameter("size", maxf(d.aabb.size.x, 0.6) * randf_range(0.9, 1.3))
	m.set_shader_parameter("rot", randf() * TAU)
	mi.material_overlay = m
	if world.audio:
		world.audio.play("glass_shatter", mi.global_position, 0.25, 1.3)


func _shatter(d: Dictionary) -> void:
	d.state = "gone"
	stats.glass += 1
	var mi: MeshInstance3D = d.mi
	var c: Vector3 = body.global_transform * d.aabb.get_center()
	mi.visible = false
	world.fx.burst("glass", c, (c - body.global_position).normalized() + Vector3.UP * 0.3, 1.2)
	if world.audio:
		world.audio.play("glass_shatter", c, 0.8)


func _break_lens(d: Dictionary) -> void:
	d.state = "gone"
	stats.lenses += 1
	var mi: MeshInstance3D = d.mi
	var c: Vector3 = body.global_transform * d.aabb.get_center()
	mi.visible = false
	world.fx.burst("glass", c, (c - body.global_position).normalized(), 0.45)
	if world.audio:
		world.audio.play("plastic_clatter", c, 0.5, 1.4)
	for l in d.lamps:
		_lamp_off(String(l))


func _lamp_off(lamp: String) -> void:
	if lights_out.has(lamp):
		return
	lights_out[lamp] = true
	# the emitter meshes of that lamp go dark
	for nm in panels:
		var p: Dictionary = panels[nm]
		if p.kind == "lamp" and lamp in p.lamps:
			var mi: MeshInstance3D = p.mi
			for s in mi.mesh.get_surface_count():
				var src := mi.get_active_material(s)
				if src is BaseMaterial3D:
					if not _dark_mats.has(src):
						var dm: BaseMaterial3D = src.duplicate()
						dm.emission_enabled = false
						_dark_mats[src] = dm
					mi.set_surface_override_material(s, _dark_mats[src])
	if body.has_method("toggle_lightbar"):         # the hero's real lights
		var idx := ["Headlight_L", "Headlight_R"].find(lamp)
		if idx >= 0 and idx < body.headlights.size():
			body.headlights[idx].visible = false
		idx = ["Taillight_L", "Taillight_R"].find(lamp)
		if idx >= 0 and idx < body.tail_lights.size():
			body.tail_lights[idx].visible = false
	elif "head" in body:                           # traffic: the shared lamp quads, when both are out
		if lights_out.has("Headlight_L") and lights_out.has("Headlight_R") and body.head:
			body.head.visible = false
		if lights_out.has("Taillight_L") and lights_out.has("Taillight_R") and body.tail:
			body.tail.visible = false
	var f := Vector3(0, 0.6, 2.0) if lamp.begins_with("Head") else Vector3(0, 0.8, -2.0)
	world.fx.burst("sparks", body.global_transform * f, body.global_basis.z * (1.0 if lamp.begins_with("Head") else -1.0), 0.3)


func _apply_performance() -> void:
	if "power_scale" in body:
		body.power_scale = clampf(1.0 - engine * 0.7 - (wheel_dmg.FL + wheel_dmg.FR + wheel_dmg.RL + wheel_dmg.RR) * 0.04, 0.25, 1.0)
	if "steer_pull" in body:
		body.steer_pull = clampf((wheel_dmg.FL - wheel_dmg.FR) * 0.07, -0.07, 0.07)


# ------------------------------------------------------------------ continuous effects
func _tick_effects(_delta: float) -> void:
	# engine: steam from 0.35, black smoke from 0.7
	if engine > 0.35 and _smoke == null and world.fx and (hero or _may_deform()):
		_smoke = world.fx.engine_smoke()
		_smoke.position = _smoke_pos
		add_child(_smoke)
		_smoke.emitting = true
	if _smoke:
		var pm: ParticleProcessMaterial = _smoke.process_material
		var black := clampf((engine - 0.62) / 0.3, 0.0, 1.0)
		pm.color = Color(0.85, 0.86, 0.9).lerp(Color(0.05, 0.05, 0.055), black)
		_smoke.amount_ratio = clampf(0.3 + engine * 0.8, 0.0, 1.0)
		var sp := body.linear_velocity.length()
		pm.gravity = Vector3(0, 0.6, 0) - body.linear_velocity * 0.15 if sp > 1.0 else Vector3(0, 0.6, 0)
	# a loose hood catches the wind at speed and flaps up
	for nm in ["Hood", "Trunk"]:
		if panels.has(nm) and panels[nm].state == "loose" and is_instance_valid(panels[nm].rb):
			var d: Dictionary = panels[nm]
			var fwd := body.linear_velocity.dot(body.global_basis.z)
			if nm == "Hood" and fwd > 6.0:
				var ax_w: Vector3 = body.global_basis * (d.axis as Vector3)
				(d.rb as RigidBody3D).apply_torque(ax_w * d.sign * fwd * fwd * 0.05 * randf_range(0.6, 1.4))


# ------------------------------------------------------------------ reset
func reset() -> void:
	_acc = {}
	for nm in order:
		if not panels.has(nm):
			continue
		var d: Dictionary = panels[nm]
		if is_instance_valid(d.joint):
			d.joint.queue_free()
		d.joint = null
	# bring the pivots home (parents first), free their debris bodies
	for nm in order:
		if not panels.has(nm):
			continue
		var d: Dictionary = panels[nm]
		var pv: Node3D = d.pivot
		var par: Node3D = _root
		if d.parent != null and panels.has(d.parent):
			par = panels[d.parent].pivot
		if is_instance_valid(pv) and pv.get_parent() != par:
			var old_rb: Node = pv.get_parent()
			old_rb.remove_child(pv)
			par.add_child(pv)
			if old_rb is RigidBody3D and is_instance_valid(d.rb):
				world.debris.release(d.rb)
		d.rb = null
		if d.kind == "bumper" or d.state != "ok":
			var pvp: Array = _orig_pivot(nm)
			if not pvp.is_empty():
				var shift: Vector3 = pvp[0] - d.pivot_pos
				for c in pv.get_children():
					if c is Node3D and not String(c.name).ends_with("_Pivot"):
						(c as Node3D).position -= shift
				d.pivot_pos = pvp[0]
		pv.transform = Transform3D(Basis(), d.pivot_pos) if par == _root else Transform3D(Basis(), d.pivot_pos - panels[d.parent].pivot_pos)
		pv.visible = true
		d.erase("hidden_pivot")
		d.health = 100.0
		d.state = "ok"
		var mi: MeshInstance3D = d.mi
		mi.visible = d.vis
		mi.material_overlay = null
		if d.kind == "lamp":
			for s in mi.mesh.get_surface_count():
				mi.set_surface_override_material(s, null)
	# children of panels: their own mesh offsets are relative to the parent's pivot again
	for df in deformers:
		df.restore()
	for k in zones:
		zones[k] = 0.0
	for k in wheel_dmg:
		wheel_dmg[k] = 0.0
	engine = 0.0
	lights_out.clear()
	if body.has_method("toggle_lightbar"):
		for l in body.headlights:
			l.visible = true
		for l in body.tail_lights:
			l.visible = true
	elif "head" in body:
		if body.head:
			body.head.visible = true
		if body.tail:
			body.tail.visible = true
	if _smoke:
		_smoke.queue_free()
		_smoke = null
	_apply_performance()
	for k in stats:
		stats[k] = 0 if stats[k] is int else 0.0
	_last_v = body.linear_velocity
	changed.emit()


func _orig_pivot(nm: String) -> Array:
	for p in spec.get("damage", {}).get("panels", []):
		if String(p.node) == nm:
			return [_v3(p.pivot)]
	return []


## Detached panels' meshes and their pivots, for the tests / HUD.
func state_counts() -> Dictionary:
	var out := {"ok": 0, "loose": 0, "off": 0, "cracked": 0, "gone": 0}
	for nm in panels:
		out[panels[nm].state] = int(out.get(panels[nm].state, 0)) + 1
	return out
