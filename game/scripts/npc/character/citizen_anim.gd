extends RefCounted
## AnimationTree setup for any SkeletonProfileHumanoid character (citizens, the player):
##
##   idle_kind (Transition: idle / idle_talk / idle_fold / idle_phone / look_around / idle_rail / sit)
##        -> idle_ts (TimeScale)  ─┐
##   gait (BlendSpace1D walk 0 / jog 1 / sprint 2) -> gait_ts ─┴ move (Blend2 by speed)
##   zombie (Blend2 zombie_idle / zombie_walk) ── sleep (Blend2: the sleepwalker's slack posture)
##   idle_lantern ── umbrella (Blend2, right arm only: holding the umbrella up)
##   act_loop (Animation, any looping clip) ── activity (Blend2: sitting, smoking, phone ...)
##   act_shot (Animation, any one-shot clip) ── action (OneShot: flinch, dodge, get-up ...)  -> output
##
##   var tree := CitizenAnim.make(lib)               # AnimationTree, add it under the character root
##   CitizenAnim.set_speed(tree, v, hips_height)     # drives move / gait / time scales
##   CitizenAnim.set_idle(tree, "idle_phone")        # idle kinds above
##   CitizenAnim.play_action(tree, "flinch")         # any clip in the library, once
##   CitizenAnim.set_activity(tree, "sit_idle", 1.0) # any looping clip, blended in (0 = off)
##   CitizenAnim.set_umbrella(tree, on), set_sleepwalker(tree, amount)

const AnimLib := preload("res://scripts/npc/character/anim_library.gd")
const IDLES := ["idle", "idle_talk", "idle_fold", "idle_phone", "look_around", "idle_rail", "sit_idle", "consume"]
const SKEL := "%GeneralSkeleton:"
const RIGHT_ARM := ["RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand", "RightThumbMetacarpal", "RightThumbProximal",
	"RightThumbDistal", "RightIndexProximal", "RightIndexIntermediate", "RightIndexDistal", "RightMiddleProximal",
	"RightMiddleIntermediate", "RightMiddleDistal", "RightRingProximal", "RightRingIntermediate", "RightRingDistal",
	"RightLittleProximal", "RightLittleIntermediate", "RightLittleDistal"]


static func _anim(name: String) -> AnimationNodeAnimation:
	var a := AnimationNodeAnimation.new()
	a.animation = name
	return a


static func make(lib: AnimationLibrary) -> AnimationTree:
	var bt := AnimationNodeBlendTree.new()
	var tr := AnimationNodeTransition.new()
	tr.xfade_time = 0.45
	var have := lib.get_animation_list()
	var idles := []
	for n in IDLES:
		if n in have:
			idles.append(n)
	tr.input_count = idles.size()
	for i in idles.size():
		tr.set_input_name(i, idles[i])
		bt.add_node("i_" + idles[i], _anim(idles[i]), Vector2(0, i * 80))
	bt.add_node("idle_kind", tr, Vector2(250, 0))
	for i in idles.size():
		bt.connect_node("idle_kind", i, "i_" + idles[i])
	bt.add_node("idle_ts", AnimationNodeTimeScale.new(), Vector2(450, 0))
	bt.connect_node("idle_ts", 0, "idle_kind")
	var bs := AnimationNodeBlendSpace1D.new()
	bs.min_space = 0.0
	bs.max_space = 2.0
	bs.add_blend_point(_anim("walk"), 0.0, -1, &"walk")
	bs.add_blend_point(_anim("jog"), 1.0, -1, &"jog")
	bs.add_blend_point(_anim("sprint"), 2.0, -1, &"sprint")
	bt.add_node("gait", bs, Vector2(250, 500))
	bt.add_node("gait_ts", AnimationNodeTimeScale.new(), Vector2(450, 500))
	bt.connect_node("gait_ts", 0, "gait")
	bt.add_node("move", AnimationNodeBlend2.new(), Vector2(650, 200))
	bt.connect_node("move", 0, "idle_ts")
	bt.connect_node("move", 1, "gait_ts")
	# sleepwalker
	bt.add_node("z_idle", _anim("zombie_idle" if "zombie_idle" in have else "idle"), Vector2(250, 700))
	bt.add_node("z_walk", _anim("zombie_walk" if "zombie_walk" in have else "walk"), Vector2(250, 780))
	bt.add_node("zombie", AnimationNodeBlend2.new(), Vector2(450, 740))
	bt.connect_node("zombie", 0, "z_idle")
	bt.connect_node("zombie", 1, "z_walk")
	bt.add_node("z_ts", AnimationNodeTimeScale.new(), Vector2(600, 740))
	bt.connect_node("z_ts", 0, "zombie")
	bt.add_node("sleep", AnimationNodeBlend2.new(), Vector2(850, 300))
	bt.connect_node("sleep", 0, "move")
	bt.connect_node("sleep", 1, "z_ts")
	# umbrella arm
	bt.add_node("lantern", _anim("idle_lantern" if "idle_lantern" in have else "idle"), Vector2(850, 500))
	var um := AnimationNodeBlend2.new()
	um.filter_enabled = true
	for b in RIGHT_ARM:
		um.set_filter_path(NodePath(SKEL + b), true)
	bt.add_node("umbrella", um, Vector2(1050, 300))
	bt.connect_node("umbrella", 0, "sleep")
	bt.connect_node("umbrella", 1, "lantern")
	# looping activity + one-shot action
	bt.add_node("act_loop", _anim("idle"), Vector2(1050, 500))
	bt.add_node("activity", AnimationNodeBlend2.new(), Vector2(1250, 300))
	bt.connect_node("activity", 0, "umbrella")
	bt.connect_node("activity", 1, "act_loop")
	bt.add_node("act_shot", _anim("flinch"), Vector2(1250, 500))
	var os := AnimationNodeOneShot.new()
	os.fadein_time = 0.12
	os.fadeout_time = 0.25
	bt.add_node("action", os, Vector2(1450, 300))
	bt.connect_node("action", 0, "activity")
	bt.connect_node("action", 1, "act_shot")
	bt.connect_node("output", 0, "action")
	var t := AnimationTree.new()
	t.name = "AnimationTree"
	t.add_animation_library("", lib)
	t.tree_root = bt
	t.set("parameters/idle_ts/scale", 1.0)
	t.set("parameters/gait_ts/scale", 1.0)
	t.set("parameters/z_ts/scale", 1.0)
	t.set_meta("idles", idles)
	return t


## v: ground speed (m/s), hips: the character's hips height (m) - the clips' speeds scale with size.
static func set_speed(t: AnimationTree, v: float, hips: float) -> void:
	var k := hips / AnimLib.MANNEQUIN_HIPS
	var g := 0.0
	if v > 2.2:
		g = clampf((v - 2.2) / 1.3, 0.0, 1.0)
	if v > 5.0:
		g = 1.0 + clampf((v - 5.0) / 2.5, 0.0, 1.0)
	var ref := lerpf(AnimLib.SPEED.walk, AnimLib.SPEED.jog, clampf(g, 0.0, 1.0)) if g <= 1.0 else lerpf(AnimLib.SPEED.jog, AnimLib.SPEED.sprint, g - 1.0)
	t.set("parameters/move/blend_amount", clampf(v / 0.45, 0.0, 1.0))
	t.set("parameters/zombie/blend_amount", clampf(v / 0.45, 0.0, 1.0))
	t.set("parameters/gait/blend_position", g)
	t.set("parameters/gait_ts/scale", clampf(v / (ref * k), 0.55, 1.8) if v > 0.05 else 1.0)
	t.set("parameters/z_ts/scale", clampf(v / (AnimLib.SPEED.zombie_walk * k), 0.5, 1.4) if v > 0.05 else 0.8)


static func set_idle(t: AnimationTree, kind: String) -> void:
	var idles: Array = t.get_meta("idles", [])
	if kind in idles:
		t.set("parameters/idle_kind/transition_request", kind)


static func play_action(t: AnimationTree, clip: String, fade_in := 0.12) -> bool:
	if not t.has_animation(clip):
		return false
	var bt: AnimationNodeBlendTree = t.tree_root
	(bt.get_node("act_shot") as AnimationNodeAnimation).animation = clip
	(bt.get_node("action") as AnimationNodeOneShot).fadein_time = fade_in
	t.set("parameters/action/request", AnimationNodeOneShot.ONE_SHOT_REQUEST_FIRE)
	return true


static func stop_action(t: AnimationTree) -> void:
	t.set("parameters/action/request", AnimationNodeOneShot.ONE_SHOT_REQUEST_FADE_OUT)


static func action_active(t: AnimationTree) -> bool:
	return bool(t.get("parameters/action/active"))


static func set_activity(t: AnimationTree, clip: String, amount: float) -> void:
	if clip != "" and t.has_animation(clip):
		var bt: AnimationNodeBlendTree = t.tree_root
		var a := bt.get_node("act_loop") as AnimationNodeAnimation
		if a.animation != clip:
			a.animation = clip
	t.set("parameters/activity/blend_amount", amount if clip != "" else 0.0)


static func set_umbrella(t: AnimationTree, on: float) -> void:
	t.set("parameters/umbrella/blend_amount", on)


static func set_sleepwalker(t: AnimationTree, amount: float) -> void:
	t.set("parameters/sleep/blend_amount", 0.45 * amount)
	t.set("parameters/idle_ts/scale", lerpf(1.0, 0.65, amount))
