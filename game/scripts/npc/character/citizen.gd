extends Node3D
## One character from the citizen catalogue: the imported MPFB model (skeleton renamed to
## SkeletonProfileHumanoid bones, "%GeneralSkeleton"), LOD0/LOD1 skinned meshes with the atlas shader,
## the shared AnimationTree setup (citizen_anim.gd), an optional umbrella, the sleepwalker look and the
## ragdoll + get-up component (ragdoll.gd).  Make them with citizen_library.gd: CitizenLib.spawn(id).
##
##   set_speed(v)                     ground speed in m/s (drives idle / walk / jog / sprint and their rates)
##   set_idle(kind)                   idle / idle_talk / idle_fold / idle_phone / look_around / idle_rail / sit_idle / consume
##   play_action(clip) -> bool        any library clip once (flinch, roll, dodge_jump, yes, no, interact, extra_* ...)
##   set_activity(clip, amount)       a looping clip blended over everything (sit_idle, idle_phone, extra_smoking ...)
##   set_umbrella(kind)               "clear" / "black" / "neon" / "" (none)
##   set_sleepwalker(on)              faint cyan glow at the temples and eyes, slack posture, slower idle
##   ragdoll(impulse, at)             throw them (Jolt physical bones); signal stood_up when back on their feet
##   is_down() -> bool                ragdolling or getting up
##   anim_auto = false + advance(dt)  drive the animation yourself (the crowd does: staggered / reduced rates)

signal fell
signal stood_up

const CitizenAnim := preload("res://scripts/npc/character/citizen_anim.gd")
const AnimLib := preload("res://scripts/npc/character/anim_library.gd")
const Ragdoll := preload("res://scripts/npc/character/ragdoll.gd")
const LIB_PATH := "res://scripts/npc/character/citizen_library.gd"

var citizen_id := ""
var info := {}
var model: Node3D
var skel: Skeleton3D
var lod0: MeshInstance3D
var lod1: MeshInstance3D
var tree: AnimationTree
var rag: Node
var umbrella: Node3D
var umbrella_kind := ""
var sleepwalker := false
var hips_h := 0.9
var speed := 0.0
var anim_auto := true:
	set(v):
		anim_auto = v
		if tree:
			tree.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_IDLE if v else AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
var _hand := -1
static var _umb_mesh := {}


func setup(id: String, inf: Dictionary, opts := {}) -> void:
	var Lib = load(LIB_PATH)
	citizen_id = id
	info = inf
	name = id
	hips_h = float(inf.get("hips", 0.9))
	model = Lib.scene(id).instantiate()
	model.name = "Model"
	add_child(model)
	skel = model.find_child("GeneralSkeleton", true, false)
	lod0 = model.find_child("LOD0", true, false)
	lod1 = model.find_child("LOD1", true, false)
	var l2 = model.find_child("LOD2", true, false)
	if l2:
		l2.get_parent().remove_child(l2)
		l2.free()
	var mats: Array = Lib.materials(id)
	for mi in [lod0, lod1]:
		if mi == null:
			continue
		for s in mi.mesh.get_surface_count():
			var src: Material = mi.mesh.surface_get_material(s)
			var cut := src != null and String(src.resource_name).contains("cutout")
			mi.set_surface_override_material(s, mats[1] if cut else mats[0])
	if lod0 and lod1:
		lod0.visibility_range_end = 16.0
		lod0.visibility_range_end_margin = 1.0
		lod1.visibility_range_begin = 16.0
		lod1.visibility_range_begin_margin = 1.0
		lod1.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	if not opts.get("shadows", true):
		for mi in [lod0, lod1]:
			if mi:
				mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var lib := AnimLib.get_library(bool(opts.get("lite", false)))
	tree = CitizenAnim.make(lib)
	model.add_child(tree)
	tree.root_node = NodePath("..")
	tree.active = true
	anim_auto = bool(opts.get("anim_auto", true))
	_hand = skel.find_bone("RightHand") if skel else -1
	if opts.get("ragdoll", true):
		rag = Ragdoll.new()
		rag.name = "RagdollCtl"
		add_child(rag)
		rag.setup(skel, tree, self, hips_h)
		rag.fell.connect(func(): fell.emit())
		rag.stood_up.connect(func(): stood_up.emit())
	var u = opts.get("umbrella", inf.get("umbrella"))
	if u != null and String(u) != "":
		set_umbrella(String(u))
	set_idle(String(inf.get("idle", "idle")).to_lower())


func skeleton() -> Skeleton3D:
	return skel


func anim_tree() -> AnimationTree:
	return tree


func set_speed(v: float) -> void:
	speed = v
	CitizenAnim.set_speed(tree, v, hips_h)


func set_idle(kind: String) -> void:
	CitizenAnim.set_idle(tree, kind)


func play_action(clip: String, fade_in := 0.12) -> bool:
	return CitizenAnim.play_action(tree, clip, fade_in)


func action_playing() -> bool:
	return CitizenAnim.action_active(tree)


func set_activity(clip: String, amount := 1.0) -> void:
	CitizenAnim.set_activity(tree, clip, amount)


func set_sleepwalker(on: bool) -> void:
	sleepwalker = on
	for mi in [lod0, lod1]:
		if mi:
			mi.set_instance_shader_parameter("sleepwalker", 1.0 if on else 0.0)
	CitizenAnim.set_sleepwalker(tree, 1.0 if on else 0.0)


func set_trim_glow(v: float) -> void:
	for mi in [lod0, lod1]:
		if mi:
			mi.set_instance_shader_parameter("trim_glow", v)


func is_down() -> bool:
	return rag != null and rag.active()


func ragdoll(impulse: Vector3, at: Vector3, exclude: PhysicsBody3D = null) -> void:
	if rag == null:
		return
	if exclude:
		rag.exclude(exclude)
	if umbrella:
		umbrella.visible = false
	rag.ragdoll(impulse, at)


func advance(dt: float) -> void:
	if tree and not anim_auto:
		tree.advance(dt)
	_place_umbrella()


func _process(_dt: float) -> void:
	if anim_auto:
		_place_umbrella()


func set_lod_distances(near_end: float) -> void:
	if lod0 and lod1:
		lod0.visibility_range_end = near_end
		lod1.visibility_range_begin = near_end


# ------------------------------------------------------------------ umbrella
func set_umbrella(kind: String) -> void:
	umbrella_kind = kind
	if kind == "":
		if umbrella:
			umbrella.queue_free()
			umbrella = null
		CitizenAnim.set_umbrella(tree, 0.0)
		return
	if umbrella == null:
		umbrella = Node3D.new()
		umbrella.name = "Umbrella"
		add_child(umbrella)
		var mi := MeshInstance3D.new()
		umbrella.add_child(mi)
	var m: Array = umbrella_mesh(kind)
	var mi: MeshInstance3D = umbrella.get_child(0)
	mi.mesh = m[0]
	mi.material_override = m[1]
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF if kind == "clear" else GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	CitizenAnim.set_umbrella(tree, 1.0)


func _place_umbrella() -> void:
	if umbrella == null or _hand < 0:
		return
	umbrella.visible = not is_down()
	if umbrella.visible:
		var hp := skel.global_transform * skel.get_bone_global_pose(_hand).origin
		umbrella.global_transform = Transform3D(global_basis.orthonormalized(), hp)


## [mesh, material]: shaft + 8-rib canopy (radius 0.5 m), the hand at the origin.
static func umbrella_mesh(kind: String) -> Array:
	if _umb_mesh.has(kind):
		return _umb_mesh[kind]
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var ribs := 8
	var top := Vector3(0, 0.86, 0)
	var r := 0.52
	var rim_y := 0.66
	for i in ribs:
		var a0 := TAU * i / ribs
		var a1 := TAU * (i + 1) / ribs
		var p0 := Vector3(cos(a0) * r, rim_y, sin(a0) * r)
		var p1 := Vector3(cos(a1) * r, rim_y, sin(a1) * r)
		var mid := (p0 + p1) * 0.5 * 0.93 + Vector3(0, 0.03, 0)       # scalloped panels
		for tri in [[top, p0, mid], [top, mid, p1]]:
			var n: Vector3 = (tri[1] - tri[0]).cross(tri[2] - tri[0]).normalized()
			if n.y < 0:
				n = -n
				tri = [tri[0], tri[2], tri[1]]
			for p in tri:
				st.set_normal(n)
				st.set_uv(Vector2(0.5, 1.0 if p == top else 0.0))
				st.add_vertex(p)
	# shaft (thin box) from the hand to the top, and the hook below the hand
	var w := 0.012
	for seg in [[Vector3(0, -0.12, 0), top + Vector3(0, 0.06, 0)]]:
		var a: Vector3 = seg[0]
		var b: Vector3 = seg[1]
		var corners := [Vector3(-w, 0, -w), Vector3(w, 0, -w), Vector3(w, 0, w), Vector3(-w, 0, w)]
		for k in 4:
			var c0: Vector3 = corners[k]
			var c1: Vector3 = corners[(k + 1) % 4]
			var n := (c0 + c1).normalized()
			for p in [a + c0, b + c0, b + c1, a + c0, b + c1, a + c1]:
				st.set_normal(n)
				st.set_uv(Vector2(0.5, 0.5))
				st.add_vertex(p)
	var mesh := st.commit()
	var m := StandardMaterial3D.new()
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	match kind:
		"clear":
			m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			m.albedo_color = Color(0.75, 0.85, 0.95, 0.28)
			m.roughness = 0.05
			m.metallic_specular = 0.9
		"neon":
			m.albedo_color = Color(0.03, 0.03, 0.04)
			m.roughness = 0.25
			m.emission_enabled = true
			var g := Gradient.new()
			g.set_color(0, Color(0, 0, 0))
			g.set_color(1, Color(0.1, 0.9, 1.0) if randf() < 0.5 else Color(1.0, 0.15, 0.65))
			g.set_offset(0, 0.8)
			var gt := GradientTexture2D.new()
			gt.gradient = g
			gt.fill_from = Vector2(0, 1)
			gt.fill_to = Vector2(0, 0)
			gt.width = 4
			gt.height = 32
			m.emission_texture = gt
			m.emission_energy_multiplier = 2.5
		_:
			m.albedo_color = Color(0.02, 0.02, 0.025)
			m.roughness = 0.3
	_umb_mesh[kind] = [mesh, m]
	return _umb_mesh[kind]
