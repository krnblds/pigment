extends Node3D
## The one place that knows which character model and animations a humanoid uses (the on-foot Waker,
## the sleepwalkers, the memory-echo ghosts). Everything else talks to this adapter:
##
##   body.set_locomotion(speed, crouch, air)     speed m/s along the facing (negative = backwards)
##   body.set_aim(amount, yaw, pitch, hip_yaw)   0..1 weapon raised; rad offsets for the aim layer
##   body.set_armed(bool)                        upper body in the weapon stance
##   body.play(action)                           "shoot" "reload" "hit" "melee" "interact" "punch"
##   body.set_dead(bool)                         full-body death (holds the last frame)
##   body.hand_position() / head_position()      for weapons, hit tests, look-at
##   body.set_look(look)                         Look preset: tint, gear and glow (see LOOKS)
##
## Stand-in (until the NPC workstream lands): the CC0 Quaternius Universal Animation Library mannequin
## (assets/characters/ual/), imported with a BoneMap to SkeletonProfileHumanoid (bone names Hips,
## Spine, ... RightHand; unique skeleton node %GeneralSkeleton), so its clips drive any humanoid that is
## imported the same way. To use the NPC pipeline's MPFB officer, set MODEL (or pass `model` before
## add_child) to that scene; keep ANIMS pointing at the retargeted clip source (the UAL gltf here, or the
## NPC pipeline's library) -- see docs/agents/waker/NOTES.md "Switching the body".

const MODEL := "res://assets/characters/ual/AnimationLibrary_Godot_Standard.gltf"
const ANIMS := "res://assets/characters/ual/AnimationLibrary_Godot_Standard.gltf"
const AimModifier := preload("res://scripts/player/aim_modifier.gd")
## NPC pipeline (scripts/npc/character/): the Waker officers (waker_m / waker_f) and the 32 citizens, same
## SkeletonProfileHumanoid import; used when built (python tools/npc/build_all.py), else the UAL mannequin.
const CITIZEN_LIB := "res://scripts/npc/character/citizen_library.gd"
const WAKER_MODELS := {"male": "res://assets/npc/citizens/waker_m.glb", "female": "res://assets/npc/citizens/waker_f.glb"}

## Upper-body bones (filters of the weapon / action layers).
const UPPER := ["Chest", "UpperChest", "Neck", "Head", "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
	"RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand"]
const FINGERS := ["Thumb", "Index", "Middle", "Ring", "Little"]

## Clip names in the library (retargeted UAL names; "_Loop" is stripped on import).
const CLIP := {
	"idle": "Idle", "walk": "Walk", "jog": "Jog_Fwd", "sprint": "Sprint", "crouch_idle": "Crouch_Idle",
	"crouch_fwd": "Crouch_Fwd", "jump": "Jump", "pistol_idle": "Pistol_Idle", "aim_up": "Pistol_Aim_Up",
	"aim_mid": "Pistol_Aim_Neutral", "aim_down": "Pistol_Aim_Down", "shoot": "Pistol_Shoot", "reload": "Pistol_Reload",
	"hit": "Hit_Chest", "melee": "Sword_Attack", "punch": "Punch_Cross", "interact": "Interact", "death": "Death01",
	"talk": "Idle_Talking", "drive": "Driving", "sit": "Sitting_Idle",
}
const ACTIONS := ["shoot", "reload", "hit", "melee", "interact", "punch"]

## Looks: body tint, gear, Dreamlink glow. Gear pieces are simple primitives on bone attachments.
const LOOKS := {
	"waker": {"tint": Color(0.06, 0.07, 0.1), "trim": Color(0.35, 0.95, 1.0), "gear": ["helmet", "shoulder_lamp"]},
	"courier": {"tint": Color(0.32, 0.12, 0.06), "trim": Color(0.25, 0.9, 1.0), "gear": ["halo"]},
	"soldier": {"tint": Color(0.16, 0.18, 0.12), "trim": Color(0.25, 0.9, 1.0), "gear": ["halo", "helmet_soft"]},
	"climber": {"tint": Color(0.1, 0.1, 0.13), "trim": Color(0.25, 0.9, 1.0), "gear": ["halo", "hood"]},
	"parent": {"tint": Color(0.35, 0.33, 0.3), "trim": Color(0.25, 0.9, 1.0), "gear": ["halo", "coat"]},
	"swarm": {"tint": Color(0.22, 0.16, 0.26), "trim": Color(0.25, 0.9, 1.0), "gear": ["halo"]},
	"civilian": {"tint": Color(0.2, 0.2, 0.24), "trim": Color(1.0, 0.4, 0.7), "gear": []},
	"ghost": {"tint": Color(0.3, 0.9, 1.0), "trim": Color(0.3, 0.9, 1.0), "gear": [], "ghost": true},
}

var model: String = ""                    ## "" = by look: the Waker officer, a citizen (sleepers, ghosts), or MODEL
var citizen_id := ""                      ## the NPC citizen this body is (its atlas materials), "" for the mannequin
var skeleton: Skeleton3D
var tree: AnimationTree
var aim: SkeletonModifier3D
var mesh_instances: Array[MeshInstance3D] = []
var look := ""
var dead := false
var height := 1.83
var _root: Node3D
var _act := ""
var _bones := {}
var _gear: Array[Node3D] = []
var _armed := 0.0
var _armed_target := 0.0

static var _lib: AnimationLibrary          ## shared, built once (reversed clips added)
static var _ghost_mat: ShaderMaterial


func _ready() -> void:
	if model == "":
		model = _pick_model()
	if model.begins_with("res://assets/npc/citizens/"):
		citizen_id = model.get_file().get_basename()
	var ps = load(model) if ResourceLoader.exists(model) else null
	if ps == null:
		_fallback()
		return
	_root = ps.instantiate()
	_root.name = "Model"
	if citizen_id != "":
		load(CITIZEN_LIB).dress(_root, citizen_id)    # atlas materials, LOD ranges, no crowd LOD2
	add_child(_root)
	var sks := _root.find_children("*", "Skeleton3D", true, false)
	if sks.is_empty():
		return
	skeleton = sks[0]
	for mi in _root.find_children("*", "MeshInstance3D", true, false):
		mesh_instances.append(mi)
	for ap in _root.find_children("*", "AnimationPlayer", true, false):
		ap.queue_free()          # the tree mixes the clips itself
	for i in skeleton.get_bone_count():
		_bones[String(skeleton.get_bone_name(i))] = i
	_build_tree()
	aim = AimModifier.new()
	aim.name = "AimLayer"
	skeleton.add_child(aim)
	if look != "":
		set_look(look)


## The Waker officer for the player, a citizen for everyone else (seeded by the node), the mannequin
## when the NPC citizens aren't built.
func _pick_model() -> String:
	var Lib = load(CITIZEN_LIB) if ResourceLoader.exists(CITIZEN_LIB) else null
	if Lib == null or not Lib.available():
		return MODEL
	if look == "waker":
		return WAKER_MODELS.male if ResourceLoader.exists(WAKER_MODELS.male) else MODEL
	var id: String = Lib.pick(get_instance_id())
	return Lib.info(id).get("glb", MODEL) if id != "" else MODEL


static func library() -> AnimationLibrary:
	if _lib:
		return _lib
	_lib = AnimationLibrary.new()
	var ps = load(ANIMS) if ResourceLoader.exists(ANIMS) else null
	if ps == null:
		return _lib
	var inst: Node = ps.instantiate()
	var aps := inst.find_children("*", "AnimationPlayer", true, false)
	if not aps.is_empty():
		var ap: AnimationPlayer = aps[0]
		for n in ap.get_animation_list():
			var a: Animation = ap.get_animation(n).duplicate(true)
			_hips_positions_only(a)
			if n in ["Pistol_Aim_Up", "Pistol_Aim_Neutral", "Pistol_Aim_Down", "Pistol_Idle", "Crouch_Idle", "Crouch_Fwd",
					"Idle", "Walk", "Jog_Fwd", "Sprint", "Jump", "Driving", "Sitting_Idle", "Idle_Talking", "Sword_Idle"]:
				a.loop_mode = Animation.LOOP_LINEAR
			_lib.add_animation(n, a)
		for n in ["Walk", "Jog_Fwd", "Crouch_Fwd"]:
			if _lib.has_animation(n):
				_lib.add_animation(n + "_Back", _reversed(_lib.get_animation(n)))
	inst.free()
	return _lib


## Position tracks only on the hips: the clips then fit any body (the MPFB citizens' proportions).
static func _hips_positions_only(a: Animation) -> void:
	for t in range(a.get_track_count() - 1, -1, -1):
		if a.track_get_type(t) == Animation.TYPE_POSITION_3D and not String(a.track_get_path(t)).ends_with(":Hips"):
			a.remove_track(t)


static func _reversed(a: Animation) -> Animation:
	var r := Animation.new()
	r.length = a.length
	r.loop_mode = Animation.LOOP_LINEAR
	for t in a.get_track_count():
		var nt := r.add_track(a.track_get_type(t))
		r.track_set_path(nt, a.track_get_path(t))
		r.track_set_interpolation_type(nt, a.track_get_interpolation_type(t))
		for k in a.track_get_key_count(t):
			r.track_insert_key(nt, a.length - a.track_get_key_time(t, k), a.track_get_key_value(t, k))
	return r


func _clip(key: String) -> AnimationNodeAnimation:
	var n := AnimationNodeAnimation.new()
	n.animation = StringName(CLIP.get(key, key))
	return n


func _filter(node: AnimationNode, upper: bool) -> void:
	node.filter_enabled = true
	var names := UPPER.duplicate()
	for s in ["Left", "Right"]:
		for f in FINGERS:
			for part in ["Metacarpal", "Proximal", "Intermediate", "Distal"]:
				names.append(s + f + part)
	if not upper:
		return
	for b in names:
		node.set_filter_path(NodePath("%GeneralSkeleton:" + b), true)


func _build_tree() -> void:
	tree = AnimationTree.new()
	tree.name = "AnimationTree"
	add_child(tree)
	tree.add_animation_library("", library())
	tree.root_node = tree.get_path_to(_root)
	var bt := AnimationNodeBlendTree.new()
	# locomotion: speed along the facing (backwards clips for negative speed)
	var loco := AnimationNodeBlendSpace1D.new()
	loco.min_space = -4.5
	loco.max_space = 7.0
	loco.sync = true
	loco.add_blend_point(_clip("Jog_Fwd_Back"), -4.0, -1, &"Jog_Fwd_Back")
	loco.add_blend_point(_clip("Walk_Back"), -1.6, -1, &"Walk_Back")
	loco.add_blend_point(_clip("idle"), 0.0, -1, &"idle")
	loco.add_blend_point(_clip("walk"), 1.6, -1, &"walk")
	loco.add_blend_point(_clip("jog"), 4.0, -1, &"jog")
	loco.add_blend_point(_clip("sprint"), 6.5, -1, &"sprint")
	bt.add_node("loco", loco, Vector2(0, 0))
	var cr := AnimationNodeBlendSpace1D.new()
	cr.min_space = -2.0
	cr.max_space = 2.0
	cr.add_blend_point(_clip("Crouch_Fwd_Back"), -1.8, -1, &"Crouch_Fwd_Back")
	cr.add_blend_point(_clip("crouch_idle"), 0.0, -1, &"crouch_idle")
	cr.add_blend_point(_clip("crouch_fwd"), 1.8, -1, &"crouch_fwd")
	bt.add_node("crouch", cr, Vector2(0, 200))
	bt.add_node("crouch_mix", AnimationNodeBlend2.new(), Vector2(250, 100))
	bt.connect_node("crouch_mix", 0, "loco")
	bt.connect_node("crouch_mix", 1, "crouch")
	bt.add_node("jump", _clip("jump"), Vector2(250, 300))
	bt.add_node("air_mix", AnimationNodeBlend2.new(), Vector2(450, 100))
	bt.connect_node("air_mix", 0, "crouch_mix")
	bt.connect_node("air_mix", 1, "jump")
	# weapon stance + aim pitch (upper body only)
	var aimbs := AnimationNodeBlendSpace1D.new()
	aimbs.min_space = -1.0
	aimbs.max_space = 1.0
	aimbs.add_blend_point(_clip("aim_down"), -1.0, -1, &"aim_down")
	aimbs.add_blend_point(_clip("aim_mid"), 0.0, -1, &"aim_mid")
	aimbs.add_blend_point(_clip("aim_up"), 1.0, -1, &"aim_up")
	bt.add_node("aim_pitch", aimbs, Vector2(250, 500))
	bt.add_node("stance", _clip("pistol_idle"), Vector2(250, 650))
	bt.add_node("aim_mix", AnimationNodeBlend2.new(), Vector2(450, 550))
	bt.connect_node("aim_mix", 0, "stance")
	bt.connect_node("aim_mix", 1, "aim_pitch")
	var arms := AnimationNodeBlend2.new()
	_filter(arms, true)
	bt.add_node("arms", arms, Vector2(650, 200))
	bt.connect_node("arms", 0, "air_mix")
	bt.connect_node("arms", 1, "aim_mix")
	# one-shot actions (upper body); a transition picks the clip
	var tr := AnimationNodeTransition.new()
	for a in ACTIONS:
		tr.add_input(a)
		bt.add_node("act_" + a, _clip(a), Vector2(650, 400 + ACTIONS.find(a) * 80))
	bt.add_node("act_pick", tr, Vector2(850, 450))
	for i in ACTIONS.size():
		bt.connect_node("act_pick", i, "act_" + ACTIONS[i])
	var os := AnimationNodeOneShot.new()
	os.fadein_time = 0.08
	os.fadeout_time = 0.18
	_filter(os, true)
	bt.add_node("action", os, Vector2(1050, 250))
	bt.connect_node("action", 0, "arms")
	bt.connect_node("action", 1, "act_pick")
	# death (full body)
	var life := AnimationNodeTransition.new()
	life.add_input("alive")
	life.add_input("dead")
	life.xfade_time = 0.15
	bt.add_node("life", life, Vector2(1250, 250))
	bt.add_node("death", _clip("death"), Vector2(1050, 500))
	bt.connect_node("life", 0, "action")
	bt.connect_node("life", 1, "death")
	bt.connect_node("output", 0, "life")
	tree.tree_root = bt
	tree.active = true
	tree.set("parameters/loco/blend_position", 0.0)
	# transitions start with no state (= rest pose) until asked
	tree.set("parameters/life/transition_request", "alive")
	tree.set("parameters/act_pick/transition_request", "shoot")


# ------------------------------------------------------------------ API
func set_locomotion(speed: float, crouch: float, air: float) -> void:
	if tree == null:
		return
	tree.set("parameters/loco/blend_position", speed)
	tree.set("parameters/crouch/blend_position", clampf(speed, -1.8, 1.8))
	tree.set("parameters/crouch_mix/blend_amount", crouch)
	tree.set("parameters/air_mix/blend_amount", air)


func set_armed(on: bool) -> void:
	_armed_target = 1.0 if on else 0.0


func set_aim(amount: float, yaw: float, pitch: float, hip_yaw := 0.0) -> void:
	if tree:
		tree.set("parameters/aim_mix/blend_amount", amount)
		tree.set("parameters/aim_pitch/blend_position", clampf(pitch / 0.9, -1.0, 1.0) * amount)
	if aim:
		aim.yaw = yaw
		aim.pitch = pitch * (1.0 - 0.6 * amount)      # the aim clips carry part of the pitch
		aim.hip_yaw = hip_yaw


func play(action: String) -> void:
	if tree == null or dead or not ACTIONS.has(action):
		return
	_act = action
	tree.set("parameters/act_pick/transition_request", action)
	tree.set("parameters/action/request", AnimationNodeOneShot.ONE_SHOT_REQUEST_FIRE)


func set_dead(on: bool) -> void:
	dead = on
	if tree:
		tree.set("parameters/life/transition_request", "dead" if on else "alive")
		if on:
			tree.set("parameters/action/request", AnimationNodeOneShot.ONE_SHOT_REQUEST_ABORT)


func bone_global(bone: String) -> Vector3:
	if skeleton and _bones.has(bone):
		return skeleton.global_transform * skeleton.get_bone_global_pose(_bones[bone]).origin
	return global_position + Vector3.UP * (1.6 if bone == "Head" else 1.0)


func hand_position() -> Vector3:
	return bone_global("RightHand")


func head_position() -> Vector3:
	return bone_global("Head") + Vector3.UP * 0.08


func _process(delta: float) -> void:
	_armed = move_toward(_armed, _armed_target, delta * 5.0)
	if tree:
		tree.set("parameters/arms/blend_amount", _armed)


# ------------------------------------------------------------------ looks
func set_look(name_: String) -> void:
	look = name_
	if skeleton == null:
		return
	for g in _gear:
		g.queue_free()
	_gear.clear()
	var L: Dictionary = LOOKS.get(name_, LOOKS.civilian)
	if citizen_id != "" and not L.get("ghost", false):
		# NPC citizens / the Waker officer wear their own clothes: no tint, no gear primitives; sleepers
		# (the looks with a Dreamlink halo) get the citizens' sleepwalker glow instead
		var sleeper: bool = "halo" in L.gear
		for mi in mesh_instances:
			mi.material_override = null
			mi.set_instance_shader_parameter("sleepwalker", 1.0 if sleeper else 0.0)
		return
	if L.get("ghost", false):
		for mi in mesh_instances:
			mi.material_override = ghost_material()
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		return
	var m := StandardMaterial3D.new()
	m.albedo_color = L.tint
	m.roughness = 0.55
	m.metallic = 0.15
	m.rim_enabled = true
	m.rim = 0.25
	for mi in mesh_instances:
		mi.material_override = m
	for g in L.gear:
		_add_gear(String(g), L)


func _attach(bone: String) -> BoneAttachment3D:
	var ba := BoneAttachment3D.new()
	ba.bone_name = bone
	skeleton.add_child(ba)
	_gear.append(ba)
	return ba


func _prim(parent: Node3D, mesh: Mesh, col: Color, pos: Vector3, emit := 0.0) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	var m := StandardMaterial3D.new()
	m.albedo_color = col
	m.roughness = 0.4
	m.metallic = 0.4
	if emit > 0.0:
		m.emission_enabled = true
		m.emission = col
		m.emission_energy_multiplier = emit
		m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mi.material_override = m
	mi.position = pos
	parent.add_child(mi)
	return mi


func _add_gear(g: String, L: Dictionary) -> void:
	match g:
		"helmet", "helmet_soft":
			var ba := _attach("Head")
			var s := SphereMesh.new()
			s.radius = 0.135
			s.height = 0.25
			var h := _prim(ba, s, Color(0.05, 0.06, 0.08) if g == "helmet" else Color(0.2, 0.22, 0.15), Vector3(0, 0.1, -0.005))
			h.scale = Vector3(1.0, 0.95, 1.12)
			if g == "helmet":
				var v := BoxMesh.new()
				v.size = Vector3(0.2, 0.035, 0.02)
				_prim(ba, v, L.trim, Vector3(0, 0.09, 0.125), 3.0)
		"vest":
			var ba := _attach("Chest")
			var b := BoxMesh.new()
			b.size = Vector3(0.36, 0.34, 0.25)
			_prim(ba, b, Color(0.03, 0.035, 0.05) if look == "waker" else Color(0.18, 0.2, 0.14), Vector3(0, 0.12, 0.0))
			if look == "waker":
				var st := BoxMesh.new()
				st.size = Vector3(0.3, 0.02, 0.01)
				_prim(ba, st, L.trim, Vector3(0, 0.2, 0.13), 2.5)
		"shoulder_lamp":
			var ba := _attach("LeftShoulder")
			var b := SphereMesh.new()
			b.radius = 0.022
			b.height = 0.044
			_prim(ba, b, L.trim, Vector3(0, 0.05, 0.08), 4.0)
		"halo":
			var ba := _attach("Head")
			var t := TorusMesh.new()
			t.inner_radius = 0.16
			t.outer_radius = 0.175
			var h := _prim(ba, t, L.trim, Vector3(0, 0.12, 0), 3.5)
			h.rotation = Vector3(0.25, 0, 0)
			h.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		"pack":
			var ba := _attach("Chest")
			var b := BoxMesh.new()
			b.size = Vector3(0.3, 0.36, 0.18)
			_prim(ba, b, Color(0.7, 0.4, 0.05), Vector3(0, 0.1, -0.2))
		"hood":
			var ba := _attach("Head")
			var s := SphereMesh.new()
			s.radius = 0.15
			s.height = 0.3
			_prim(ba, s, Color(0.08, 0.08, 0.1), Vector3(0, 0.08, -0.03))
		"coat":
			var ba := _attach("Hips")
			var c := CylinderMesh.new()
			c.top_radius = 0.2
			c.bottom_radius = 0.27
			c.height = 0.55
			_prim(ba, c, Color(0.3, 0.27, 0.22), Vector3(0, -0.2, 0))


static func ghost_material() -> ShaderMaterial:
	if _ghost_mat:
		return _ghost_mat
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_back, shadows_disabled;
uniform vec4 tint : source_color = vec4(0.3, 0.9, 1.0, 1.0);
uniform float strength = 1.0;
void fragment() {
	float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 2.0);
	vec3 wp = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float scan = 0.55 + 0.45 * sin(wp.y * 60.0 - TIME * 6.0);
	float flick = 0.85 + 0.15 * sin(TIME * 23.0 + wp.x * 3.0);
	ALBEDO = tint.rgb * (0.12 + fres * 1.4) * scan * flick * strength;
}
"""
	_ghost_mat = ShaderMaterial.new()
	_ghost_mat.shader = sh
	return _ghost_mat


func _fallback() -> void:
	# no model available: a capsule stand-in so the game still runs
	var mi := MeshInstance3D.new()
	var c := CapsuleMesh.new()
	c.radius = 0.28
	c.height = 1.8
	mi.mesh = c
	mi.position.y = 0.9
	add_child(mi)
	mesh_instances.append(mi)
