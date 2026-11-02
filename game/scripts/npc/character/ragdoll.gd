extends Node
## Ragdoll + get-up for any SkeletonProfileHumanoid character (Jolt, PhysicalBoneSimulator3D).
##
##   var rd := Ragdoll.new(); rd.setup(skeleton, anim_tree, character_root, hips_height); add_child(rd)
##   rd.ragdoll(impulse, at)        throw the body: impulse (kg m/s, world) at a world point
##   signal fell / stood_up         stood_up after the get-up animation (face up: getup_back, face down: getup_front)
##   rd.active() -> bool            simulating or getting up
##   rd.exclude(body)               no collisions with this body (the car that hit them)
## Physical bones are created on the first hit and freed after the get-up, so idle citizens cost nothing.
## Collision layer 64 (only scans layer 1: the world, props, the player car unless excluded).

signal fell
signal stood_up

const LAYER := 64
const CitizenAnim := preload("res://scripts/npc/character/citizen_anim.gd")
## bone: [child bone (capsule end) or "", radius, mass, swing deg, twist deg]
const BONES := {
	"Hips": ["Spine", 0.13, 12.0, 0.0, 0.0],
	"Spine": ["UpperChest", 0.12, 9.0, 25.0, 15.0],
	"UpperChest": ["Neck", 0.13, 12.0, 20.0, 15.0],
	"Head": ["", 0.1, 5.0, 35.0, 30.0],
	"LeftUpperArm": ["LeftLowerArm", 0.05, 2.5, 80.0, 40.0], "RightUpperArm": ["RightLowerArm", 0.05, 2.5, 80.0, 40.0],
	"LeftLowerArm": ["LeftHand", 0.04, 1.8, 70.0, 10.0], "RightLowerArm": ["RightHand", 0.04, 1.8, 70.0, 10.0],
	"LeftUpperLeg": ["LeftLowerLeg", 0.075, 9.0, 60.0, 20.0], "RightUpperLeg": ["RightLowerLeg", 0.075, 9.0, 60.0, 20.0],
	"LeftLowerLeg": ["LeftFoot", 0.055, 5.0, 70.0, 8.0], "RightLowerLeg": ["RightFoot", 0.055, 5.0, 70.0, 8.0],
}

var skel: Skeleton3D
var tree: AnimationTree
var body: Node3D                ## the character root (moved to where the body lies before the get-up)
var hips_h := 0.9
var sim: PhysicalBoneSimulator3D
var bones := {}
var state := 0                  ## 0 idle, 1 falling, 2 getting up
var t := 0.0
var _still := 0.0
var _excl: Array = []
var _blend := 0.0
var _up_len := 1.5
var face_up := true
var max_time := 5.0


func setup(s: Skeleton3D, at: AnimationTree, root: Node3D, hips := 0.9) -> void:
	skel = s
	tree = at
	body = root
	hips_h = hips


func active() -> bool:
	return state != 0


func exclude(b: PhysicsBody3D) -> void:
	if b and not _excl.has(b):
		_excl.append(b)


func _build() -> void:
	sim = PhysicalBoneSimulator3D.new()
	sim.name = "Ragdoll"
	skel.add_child(sim)
	var scale := hips_h / 0.917
	for bn in BONES:
		var bi := skel.find_bone(bn)
		if bi < 0:
			continue
		var d: Array = BONES[bn]
		var pb := PhysicalBone3D.new()
		pb.name = "PB_" + bn
		pb.bone_name = bn
		pb.collision_layer = LAYER
		pb.collision_mask = 1
		pb.mass = d[2] * scale
		pb.friction = 0.9
		pb.bounce = 0.05
		pb.linear_damp = 0.15
		pb.angular_damp = 0.9
		var cs := CollisionShape3D.new()
		var length := 0.18 * scale
		var dir := Vector3.UP
		var ci := skel.find_bone(d[0]) if d[0] != "" else -1
		if ci >= 0:
			var to: Vector3 = skel.get_bone_global_rest(bi).affine_inverse() * skel.get_bone_global_rest(ci).origin
			length = maxf(0.05, to.length())
			dir = to.normalized()
		if bn.ends_with("LowerArm"):
			length += 0.08 * scale          # the hand
		elif bn.ends_with("LowerLeg"):
			length += 0.04 * scale
		var r: float = d[1] * scale
		if bn == "Head":
			var sp := SphereShape3D.new()
			sp.radius = r
			cs.shape = sp
		else:
			var cap := CapsuleShape3D.new()
			cap.radius = r
			cap.height = maxf(length + r * 0.6, 2.0 * r + 0.01)
			cs.shape = cap
		var basis := Basis(Quaternion(Vector3.UP, dir)) if dir.cross(Vector3.UP).length() > 1e-4 else (Basis() if dir.y > 0 else Basis(Vector3.RIGHT, PI))
		var off := Transform3D(basis, dir * (length * 0.5 if bn != "Head" else 0.08 * scale))
		pb.body_offset = off
		pb.joint_offset = off.affine_inverse()
		if bn == "Hips":
			pb.joint_type = PhysicalBone3D.JOINT_TYPE_NONE
		else:
			pb.joint_type = PhysicalBone3D.JOINT_TYPE_CONE
			pb.set("joint_constraints/swing_span", d[3])
			pb.set("joint_constraints/twist_span", d[4])
			pb.set("joint_constraints/bias", 0.3)
			pb.set("joint_constraints/softness", 0.8)
			pb.set("joint_constraints/relaxation", 1.0)
		pb.add_child(cs)
		sim.add_child(pb)
		bones[bn] = pb


func ragdoll(impulse: Vector3, at: Vector3) -> void:
	if state == 1:
		_kick(impulse * 0.5, at)
		return
	if sim == null:
		_build()
	for b in bones.values():
		for e in _excl:
			if is_instance_valid(e):
				b.add_collision_exception_with(e)
	sim.active = true
	sim.influence = 1.0
	sim.physical_bones_start_simulation()
	state = 1
	t = 0.0
	_still = 0.0
	CitizenAnim.stop_action(tree)
	_kick(impulse, at)
	fell.emit()


func _kick(impulse: Vector3, at: Vector3) -> void:
	var m := 0.0
	for b in bones.values():
		m += b.mass
	var v := impulse / maxf(m, 1.0)
	var best = null
	var bd := INF
	for b in bones.values():
		b.linear_velocity = v
		var d: float = b.global_position.distance_to(at)
		if d < bd:
			bd = d
			best = b
	if best:
		best.apply_impulse(impulse * 0.12, at - best.global_position)


func _physics_process(dt: float) -> void:
	if state == 1:
		t += dt
		var hb: PhysicalBone3D = bones.get("Hips")
		var sp := hb.linear_velocity.length() if hb else 0.0
		_still = _still + dt if sp < 0.35 else 0.0
		if (_still > 0.7 and t > 1.6) or t > max_time:
			_begin_getup()
	elif state == 2:
		t += dt
		_blend = maxf(0.0, _blend - dt / 0.55)
		if sim:
			sim.influence = _blend
			if _blend <= 0.0 and sim.is_simulating_physics():
				sim.physical_bones_stop_simulation()
				sim.active = false
		if t > _up_len - 0.15:
			_finish()


func _begin_getup() -> void:
	var hb: PhysicalBone3D = bones.get("Hips")
	var head: PhysicalBone3D = bones.get("Head", bones.get("UpperChest"))
	if hb == null:
		_finish()
		return
	# where and how the body lies: hips' local +Z is the character's front
	var hips_b := (hb.global_transform * hb.body_offset.affine_inverse()).basis
	face_up = hips_b.z.normalized().y > 0.0
	var axis := head.global_position - hb.global_position
	axis.y = 0.0
	axis = axis.normalized() if axis.length() > 0.05 else -body.global_basis.z
	var ground := _ground(hb.global_position)
	# getup_back starts with the head along -Z of the root, getup_front (kneel) with it along +Z
	var z := -axis if face_up else axis
	var basis := Basis.looking_at(-z, Vector3.UP)          # looking_at points -Z at the target: -(-z) => +Z = z
	var hips_local := Vector3(0, 0, -0.23) if face_up else Vector3(0, 0, -0.02)
	var k := hips_h / 0.917
	var origin := Vector3(hb.global_position.x, ground, hb.global_position.z) - basis * (hips_local * k)
	origin.y = ground
	body.global_transform = Transform3D(basis, origin)
	var clip := "getup_back" if face_up else "getup_front"
	if not tree.has_animation(clip):
		clip = "getup_back"
	_up_len = tree.get_animation(clip).length if tree.has_animation(clip) else 1.5
	CitizenAnim.play_action(tree, clip, 0.05)
	state = 2
	t = 0.0
	_blend = 1.0


func _ground(p: Vector3) -> float:
	var space := body.get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 0.5, p + Vector3.DOWN * 3.0, 1)
	q.exclude = _excl.filter(func(e): return is_instance_valid(e)).map(func(e): return e.get_rid())
	var h := space.intersect_ray(q)
	return h.position.y if not h.is_empty() else p.y - hips_h * 0.1


func _finish() -> void:
	if sim:
		sim.physical_bones_stop_simulation()
		sim.queue_free()
		sim = null
		bones.clear()
	state = 0
	stood_up.emit()
