extends RigidBody3D
## One pooled traffic vehicle.  State lives here; the TrafficManager runs the AI.
##
## Modes:
##   KINEMATIC  follows its lane (frozen kinematic body; collision only when near the player)
##   DYNAMIC    knocked loose: a real rigid body until it comes to rest
##   RECOVER    blends from where it came to rest back onto its lane, then KINEMATIC again
##   PARKED     static at the kerb (turns DYNAMIC when hit)

enum { KINEMATIC, DYNAMIC, RECOVER, PARKED, OFF }

const VehicleLib := preload("res://scripts/traffic/vehicle_library.gd")

var model                       ## VehicleLib.Model
var variant := 0
var mode := OFF:
	set(v):
		mode = v
		_update_layers()
var idx := 0                    ## pool index (AI staggering)
var patrol := false

# lane state
var lane := -1
var s := 0.0
var seg := 0
var v := 0.0
var acc := 0.0
var v0 := 12.0                  ## desired speed factor applied to lane speed
var drive_factor := 1.0
var plan := -1                  ## planned connector at the end of the current road lane
var nxt := -1                   ## next lane (connector or exit lane)
var cleared := false            ## allowed into the junction ahead
var reserved := -1              ## connector reserved (just before entering)
var stopped_at_line := false
var lat := 0.0                  ## lateral offset (+ = travel-right), decays to 0 during a lane change
var lat0 := 0.0
var lc_t := 1.0                 ## lane change progress 0..1
var lc_from := -1               ## lane it is changing out of
var lc_dur := 3.0
var yaw_off := 0.0
var lc_cool := 0.0
var wait_t := 0.0               ## time waiting at a junction (deadlock breaking)
var wait_reason := ""
var stall_t := 0.0
var honk_cool := 0.0
var blocked_by_player_t := 0.0
var braking := false
var leader_gap := INF
var half_len := 2.2
var half_w := 0.92
var near := false
var far := false                ## far from the camera: pose written every 3rd tick
var dyn_t := 0.0
var rest_t := 0.0
var rec_from := Transform3D()
var rec_to := Transform3D()
var rec_t := 0.0
var spawn_t := 0.0
var progress := 0.0             ## metres driven since spawn
var last_progress := 0.0

# visuals
var lod_nodes: Array = []       ## per LOD: {"meshes": [MeshInstance3D], "wheels": [Node3D], "srcmats": [[Material...]]}
var wheel_pivots: Array = []    ## [Node3D] spinning wheels (closest LOD with wheels)
var wheel_angle := 0.0
var head: MeshInstance3D
var tail: MeshInstance3D
var bar_red: MeshInstance3D
var bar_blue: MeshInstance3D
var bar_lights: Array = []
var lightbar_on := false
var bar_t := 0.0
var _shape: CollisionShape3D


func build(m, lib, pool_index: int) -> void:
	model = m
	idx = pool_index
	half_len = m.length * 0.5
	half_w = m.width * 0.5
	mass = m.mass
	freeze_mode = RigidBody3D.FREEZE_MODE_KINEMATIC
	freeze = true
	collision_layer = 2
	collision_mask = 1 | 2
	physics_material_override = PhysicsMaterial.new()
	physics_material_override.friction = 0.55
	physics_material_override.bounce = 0.05
	angular_damp = 1.2
	linear_damp = 0.15
	_shape = CollisionShape3D.new()
	_shape.shape = m.shape
	_shape.transform = m.shape_xf
	_shape.disabled = true
	add_child(_shape)
	var begin := 0.0
	for li in m.lods.size():
		var lod: Dictionary = m.lods[li]
		var end: float = lod.max
		var entry := {"meshes": [], "wheels": [], "srcmats": [], "top": [], "begin": begin, "end": end, "in": true}
		var last: bool = li == m.lods.size() - 1
		for p in lod.parts:
			var mi := _mesh(p[0], p[1], begin, end, last)
			add_child(mi)
			entry.top.append(mi)
			entry.meshes.append(mi)
			entry.srcmats.append(p[2])
		for w in lod.wheels:
			var piv := Node3D.new()
			piv.transform = w.hub
			add_child(piv)
			entry.top.append(piv)
			var spin := Node3D.new()
			piv.add_child(spin)
			for p in w.parts:
				var mi := _mesh(p[0], p[1], begin, end, last)
				spin.add_child(mi)
				entry.meshes.append(mi)
				entry.srcmats.append(p[2])
			entry.wheels.append(spin)
		lod_nodes.append(entry)
		begin = end
	# wheels spin on the nearest LODs that have them
	for e in lod_nodes:
		wheel_pivots.append_array(e.wheels)
	head = MeshInstance3D.new()
	head.mesh = m.head_mesh
	head.material_override = lib.head_mat
	head.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	head.visibility_range_end = 320.0
	add_child(head)
	tail = MeshInstance3D.new()
	tail.mesh = m.tail_mesh
	tail.material_override = lib.tail_mat
	tail.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	tail.visibility_range_end = 260.0
	add_child(tail)
	if m.lightbar:
		bar_red = _bar(lib, 0.24, lib.bar_mats.red_off, m)
		bar_blue = _bar(lib, -0.24, lib.bar_mats.blue_off, m)
		for i in 2:
			var ol := OmniLight3D.new()
			ol.position = Vector3(0.5 if i == 0 else -0.5, m.bar_y + 0.1, 0.0)
			ol.light_color = Color(1.0, 0.05, 0.08) if i == 0 else Color(0.1, 0.3, 1.0)
			ol.omni_range = 13.0
			ol.light_energy = 0.0
			ol.light_volumetric_fog_energy = 2.0
			ol.distance_fade_enabled = true
			ol.distance_fade_begin = 120.0
			ol.distance_fade_length = 30.0
			add_child(ol)
			bar_lights.append(ol)
	visible = false
	process_mode = Node.PROCESS_MODE_DISABLED
	_update_layers()


func _bar(lib, x: float, mat: Material, m) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = lib.bar_mesh(m, x)
	mi.position = Vector3(x, m.bar_y, -0.1)
	mi.material_override = mat
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	mi.visibility_range_end = 300.0
	add_child(mi)
	return mi


func _mesh(mesh: Mesh, xf: Transform3D, begin: float, end: float, last: bool) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.transform = xf
	mi.visibility_range_begin = begin
	mi.visibility_range_end = end
	mi.visibility_range_begin_margin = 2.0 if begin > 0.0 else 0.0
	mi.visibility_range_end_margin = 2.0
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF if last and begin > 0.0 else GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	return mi


## Apply a paint / livery variant (shared materials from the library).
func set_variant(vi: int) -> void:
	variant = vi
	var v: Dictionary = model.variants[vi]
	for li in lod_nodes.size():
		var per: Dictionary = v.mats[li]
		var e: Dictionary = lod_nodes[li]
		for k in e.meshes.size():
			var mi: MeshInstance3D = e.meshes[k]
			var src: Array = e.srcmats[k]
			for si in src.size():
				if src[si] != null and per.has(src[si]):
					mi.set_surface_override_material(si, per[src[si]])


## Keep only the LODs whose visibility range is near the camera distance in the tree (perf): every
## node in the tree is re-transformed (and physics-interpolated) each time the car moves, ~60 nodes
## per car with all LODs attached. The visibility ranges still do the exact switching.
func update_lods(cam_dist: float) -> void:
	for e in lod_nodes:
		var want: bool = cam_dist > float(e.begin) - 40.0 and cam_dist < float(e.end) + 40.0
		if want == e["in"]:
			continue
		e["in"] = want
		for n in e.top:
			if want:
				add_child(n)
			else:
				remove_child(n)


func _notification(what: int) -> void:
	if what == NOTIFICATION_PREDELETE:
		for e in lod_nodes:
			if not e.get("in", true):
				for n in e.top:
					n.free()


func set_collision(on: bool) -> void:
	if _shape.disabled == on:
		_shape.set_deferred("disabled", not on)
	near = on
	_update_layers()


## Only a loose (DYNAMIC) car needs the world's static collision (layer 1); lane followers and parked
## cars are kinematic / static, which never make contacts with it, but Jolt still paired them with the
## road and terrain. Without collision (far from the player) a car leaves all layers, so Jolt pairs it
## with nothing (~0.5 ms per physics tick less with 60 cars). The hero (mask 1 | 2) still hits near ones.
func _update_layers() -> void:
	var on := near or mode == DYNAMIC
	collision_layer = 2 if on else 0
	collision_mask = ((1 | 2) if mode == DYNAMIC else 2) if on else 0


func set_braking(b: bool, lib) -> void:
	if b != braking:
		braking = b
		tail.material_override = lib.brake_mat if b else lib.tail_mat


## The add-on light bar only on patrols (civilian variants of a police model have none).
func show_bar(on: bool) -> void:
	if bar_red:
		bar_red.visible = on
		bar_blue.visible = on


func set_lightbar(on: bool, lib) -> void:
	lightbar_on = on
	if bar_red == null:
		return
	if not on:
		bar_red.material_override = lib.bar_mats.red_off
		bar_blue.material_override = lib.bar_mats.blue_off
		for l in bar_lights:
			l.light_energy = 0.0


func flash(dt: float, lib) -> void:
	if not lightbar_on or bar_red == null:
		return
	bar_t += dt
	var phase := int(bar_t * 7.0) % 6
	var red := phase in [0, 2]
	var blue := phase in [3, 5]
	bar_red.material_override = lib.bar_mats.red_on if red else lib.bar_mats.red_off
	bar_blue.material_override = lib.bar_mats.blue_on if blue else lib.bar_mats.blue_off
	bar_lights[0].light_energy = 5.0 if red else 0.0
	bar_lights[1].light_energy = 5.0 if blue else 0.0


func spin_wheels(dt: float) -> void:
	wheel_angle = fmod(wheel_angle + v * dt / model.wheel_radius, TAU)
	var b := Basis(Vector3.RIGHT, wheel_angle)
	for w in wheel_pivots:
		w.basis = b


func activate() -> void:
	visible = true
	process_mode = Node.PROCESS_MODE_INHERIT
	freeze = true
	reset_physics_interpolation()


func deactivate() -> void:
	mode = OFF
	visible = false
	set_collision(false)
	freeze = true
	process_mode = Node.PROCESS_MODE_DISABLED
	lane = -1
	if bar_red:
		lightbar_on = false
		for l in bar_lights:
			l.light_energy = 0.0
