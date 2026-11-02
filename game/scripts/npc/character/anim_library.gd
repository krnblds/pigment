extends RefCounted
## The citizens' animation library: Quaternius Universal Animation Library 1 + 2 (CC0), retargeted on
## import onto Godot's SkeletonProfileHumanoid (bonemap_ue.tres), renamed to the game's clip names,
## cleaned (no root / scale tracks, positions on the hips only) and saved as two libraries:
##   res://assets/npc/anim/library.res        all bones (near citizens, the player)
##   res://assets/npc/anim/library_lite.res   no finger tracks (mid-distance citizens: ~60 % fewer tracks)
## Extra clips dropped into res://assets/npc/anim/extra/ by tools/npc/convert_extra_anims.py
## (library_extra.res) are merged in at load time; the game runs without them.
##
## Every track targets "%GeneralSkeleton:<ProfileBone>", so the library plays on any humanoid imported
## with a SkeletonProfileHumanoid bone map (unique skeleton name "GeneralSkeleton").
##
##   AnimLib.get_library(lite := false) -> AnimationLibrary    (cached)
##   AnimLib.build_and_save() -> bool                           (tools: build_anim_library.gd)

const DIR := "res://assets/npc/anim/"
const SOURCES := {"ual1": "res://assets/npc/anim/ual1.glb", "ual2": "res://assets/npc/anim/ual2.glb"}

## game clip name -> [source, clip in the source]
const CLIPS := {
	"idle": ["ual1", "Idle"], "idle_talk": ["ual1", "Idle_Talking"], "idle_fold": ["ual2", "Idle_FoldArms"],
	"idle_phone": ["ual2", "Idle_TalkingPhone"], "idle_rail": ["ual2", "Idle_Rail"], "idle_lantern": ["ual2", "Idle_Lantern"],
	"no": ["ual2", "Idle_No"], "yes": ["ual2", "Yes"], "consume": ["ual2", "Consume"],
	"walk": ["ual1", "Walk"], "walk_formal": ["ual1", "Walk_Formal"], "walk_carry": ["ual2", "Walk_Carry"],
	"jog": ["ual1", "Jog_Fwd"], "sprint": ["ual1", "Sprint"],
	"sit_enter": ["ual1", "Sitting_Enter"], "sit_idle": ["ual1", "Sitting_Idle"], "sit_talk": ["ual1", "Sitting_Talking"],
	"sit_exit": ["ual1", "Sitting_Exit"],
	"flinch": ["ual1", "Hit_Chest"], "flinch_head": ["ual1", "Hit_Head"], "knockback": ["ual2", "Hit_Knockback"],
	"roll": ["ual1", "Roll"], "jump_start": ["ual1", "Jump_Start"], "jump": ["ual1", "Jump"], "jump_land": ["ual1", "Jump_Land"],
	"dodge_jump": ["ual2", "NinjaJump_Start"], "dodge_land": ["ual2", "NinjaJump_Land"],
	"getup_back": ["ual2", "LayToIdle"], "kneel": ["ual1", "Fixing_Kneeling"], "crouch": ["ual1", "Crouch_Idle"],
	"interact": ["ual1", "Interact"], "pickup": ["ual1", "PickUp_Table"], "push": ["ual1", "Push"],
	"zombie_idle": ["ual2", "Zombie_Idle"], "zombie_walk": ["ual2", "Zombie_Walk_Fwd"], "death": ["ual1", "Death01"],
	"dance": ["ual1", "Dance"], "tpose": ["ual1", "A_TPose"],
}
## locomotion speeds of the clips at the mannequin's size (from the root-motion versions), m/s
const SPEED := {"walk": 0.975, "walk_formal": 0.975, "walk_carry": 0.65, "jog": 5.36, "sprint": 8.25, "zombie_walk": 1.05}
const MANNEQUIN_HIPS := 0.917      ## hips height the speeds above belong to

static var _cache := {}


static func get_library(lite := false) -> AnimationLibrary:
	var key := "lite" if lite else "full"
	if _cache.has(key):
		return _cache[key]
	var lib: AnimationLibrary = null
	var p := DIR + ("library_lite.res" if lite else "library.res")
	if ResourceLoader.exists(p):
		lib = load(p)
	if lib == null:
		var both := build()          # no saved library yet: build it from the sources (slower start-up)
		if both.is_empty():
			return null
		lib = both[key]
	_merge_extra(lib, lite)
	_cache[key] = lib
	return lib


static func has_assets() -> bool:
	return ResourceLoader.exists(DIR + "library.res") or (ResourceLoader.exists(SOURCES.ual1) and ResourceLoader.exists(SOURCES.ual2))


## Extra (user supplied, e.g. Mixamo) clips: "extra_<name>" from anim/extra/library_extra.res.
static func _merge_extra(lib: AnimationLibrary, lite: bool) -> void:
	var p := DIR + "extra/library_extra.res"
	if not ResourceLoader.exists(p):
		return
	var ex: AnimationLibrary = load(p)
	if ex == null:
		return
	for n in ex.get_animation_list():
		if not lib.has_animation(n):
			var a: Animation = ex.get_animation(n)
			lib.add_animation(n, _lite(a.duplicate(true)) if lite else a)


static func extra_clips() -> PackedStringArray:
	var p := DIR + "extra/library_extra.res"
	if not ResourceLoader.exists(p):
		return PackedStringArray()
	var ex: AnimationLibrary = load(p)
	return PackedStringArray(ex.get_animation_list()) if ex else PackedStringArray()


static func build() -> Dictionary:
	var src := {}
	for k in SOURCES:
		if not ResourceLoader.exists(SOURCES[k]):
			push_warning("npc: animation source missing: %s (tools/npc/build_all.py)" % SOURCES[k])
			return {}
		var scn: Node = (load(SOURCES[k]) as PackedScene).instantiate()
		var ap: AnimationPlayer = scn.find_child("AnimationPlayer", true, false)
		src[k] = ap.get_animation_library("")
		scn.free()
	var full := AnimationLibrary.new()
	var lite := AnimationLibrary.new()
	for name in CLIPS:
		var s: Array = CLIPS[name]
		var lib: AnimationLibrary = src[s[0]]
		if not lib.has_animation(s[1]):
			push_warning("npc: clip %s not in %s" % [s[1], s[0]])
			continue
		var a: Animation = clean(lib.get_animation(s[1]).duplicate(true))
		if name.begins_with("idle") or name in ["walk", "walk_formal", "walk_carry", "jog", "sprint", "sit_idle", "sit_talk",
				"zombie_idle", "zombie_walk", "crouch", "dance", "consume"]:
			a.loop_mode = Animation.LOOP_LINEAR
		else:
			a.loop_mode = Animation.LOOP_NONE
		full.add_animation(name, a)
	if full.has_animation("idle"):
		full.add_animation("look_around", look_around(full.get_animation("idle")))
	if full.has_animation("kneel"):
		# face-down get-up: the end of the kneeling clip (on one knee -> standing); the ragdoll blends into it
		full.add_animation("getup_front", sub_clip(full.get_animation("kneel"), 3.6, 5.2))
	for name in full.get_animation_list():
		lite.add_animation(name, _lite(full.get_animation(name).duplicate(true)))
	return {"full": full, "lite": lite}


static func build_and_save() -> bool:
	var both := build()
	if both.is_empty():
		return false
	DirAccess.make_dir_recursive_absolute(DIR)
	var e1 := ResourceSaver.save(both.full, DIR + "library.res", ResourceSaver.FLAG_COMPRESS)
	var e2 := ResourceSaver.save(both.lite, DIR + "library_lite.res", ResourceSaver.FLAG_COMPRESS)
	print("npc: animation library %d clips -> %slibrary.res (+ lite)" % [both.full.get_animation_list().size(), DIR])
	return e1 == OK and e2 == OK


## Keep rotations everywhere, the position on the hips only; drop scales, the root and unmapped bones.
static func clean(a: Animation) -> Animation:
	var prof := SkeletonProfileHumanoid.new()
	var keep := {}
	for i in prof.bone_size:
		keep[String(prof.get_bone_name(i))] = true
	for t in range(a.get_track_count() - 1, -1, -1):
		var path := String(a.track_get_path(t))
		var bone := path.get_slice(":", 1)
		var typ := a.track_get_type(t)
		var ok := keep.has(bone) and bone != "Root"
		if typ == Animation.TYPE_SCALE_3D:
			ok = false
		elif typ == Animation.TYPE_POSITION_3D and bone != "Hips":
			ok = false
		elif typ != Animation.TYPE_ROTATION_3D and typ != Animation.TYPE_POSITION_3D:
			ok = false
		if not ok:
			a.remove_track(t)
	return a


static func _lite(a: Animation) -> Animation:
	for t in range(a.get_track_count() - 1, -1, -1):
		var bone := String(a.track_get_path(t)).get_slice(":", 1)
		for f in ["Thumb", "Index", "Middle", "Ring", "Little", "Toes"]:
			if bone.contains(f):
				a.remove_track(t)
				break
	return a


## [t0, t1] of a clip as a new, non-looping clip starting at 0.
static func sub_clip(a: Animation, t0: float, t1: float) -> Animation:
	var out := Animation.new()
	out.length = t1 - t0
	out.loop_mode = Animation.LOOP_NONE
	var fps := 30.0
	for t in a.get_track_count():
		var typ := a.track_get_type(t)
		var nt := out.add_track(typ)
		out.track_set_path(nt, a.track_get_path(t))
		for k in int((t1 - t0) * fps) + 1:
			var tm := minf(t0 + k / fps, t1)
			if typ == Animation.TYPE_ROTATION_3D:
				out.rotation_track_insert_key(nt, tm - t0, a.rotation_track_interpolate(t, tm))
			elif typ == Animation.TYPE_POSITION_3D:
				out.position_track_insert_key(nt, tm - t0, a.position_track_interpolate(t, tm))
	return out


## Idle with the head and neck turning left, right and back again: the "look around" idle.
static func look_around(idle: Animation) -> Animation:
	var L := idle.length * 2.0
	var out := Animation.new()
	out.length = L
	out.loop_mode = Animation.LOOP_LINEAR
	var fps := 15.0
	for t in idle.get_track_count():
		var path := idle.track_get_path(t)
		var bone := String(path).get_slice(":", 1)
		var typ := idle.track_get_type(t)
		var nt := out.add_track(typ)
		out.track_set_path(nt, path)
		var n := int(L * fps)
		for k in n + 1:
			var tm := float(k) / fps
			var ts := fmod(tm, idle.length)
			if typ == Animation.TYPE_ROTATION_3D:
				var q: Quaternion = idle.rotation_track_interpolate(t, ts)
				var w := 0.0
				if bone == "Head":
					w = 0.6
				elif bone == "Neck":
					w = 0.4
				elif bone == "UpperChest" or bone == "Chest":
					w = 0.12
				if w > 0.0:
					# look left at 1/4, right at 3/4, back to the front in between
					var yaw := sin(tm / L * TAU) * deg_to_rad(65.0) * w
					q = q * Quaternion(Vector3.UP, yaw)
				out.rotation_track_insert_key(nt, tm, q)
			elif typ == Animation.TYPE_POSITION_3D:
				out.position_track_insert_key(nt, tm, idle.position_track_interpolate(t, ts))
	return out
