extends SceneTree
## Headless helper for tools/npc/convert_extra_anims.py (extra clips dropped into assets/npc/anim_extra/):
##   godot --headless --path game -s res://scripts/npc/character/build_extra_anims.gd -- bones
##       prints "NPCBONES <res path> <skeleton node path> <json bone names>" for every staged FBX
##   godot --headless --path game -s res://scripts/npc/character/build_extra_anims.gd -- build
##       retargeted FBX animations -> res://assets/npc/anim/extra/library_extra.res as "extra_<file name>"

const AnimLib := preload("res://scripts/npc/character/anim_library.gd")
const SRC := "res://assets/npc/anim/extra/src/"
const OUT := "res://assets/npc/anim/extra/library_extra.res"


func _initialize() -> void:
	var mode := "build"
	for a in OS.get_cmdline_user_args():
		mode = String(a)
	var files := []
	var d := DirAccess.open(SRC)
	if d:
		for f in d.get_files():
			if f.to_lower().ends_with(".fbx") or f.to_lower().ends_with(".glb"):
				files.append(SRC + f)
	files.sort()
	var lib := AnimationLibrary.new()
	var n := 0
	for p in files:
		var ps = load(p)
		if not ps is PackedScene:
			push_warning("npc extra: cannot load %s" % p)
			continue
		var root: Node = ps.instantiate()
		var sk: Skeleton3D = _find_skel(root)
		if mode == "bones":
			if sk:
				var names := []
				for i in sk.get_bone_count():
					names.append(sk.get_bone_name(i))
				print("NPCBONES %s %s %s" % [p, String(root.get_path_to(sk)), JSON.stringify(names)])
		else:
			var ap: AnimationPlayer = root.find_child("AnimationPlayer", true, false)
			if ap:
				var slug := p.get_file().get_basename().to_snake_case().replace(" ", "_")
				var best: Animation = null
				for ln in ap.get_animation_library_list():
					var l := ap.get_animation_library(ln)
					for an in l.get_animation_list():
						var a: Animation = l.get_animation(an)
						if an != "RESET" and (best == null or a.length > best.length):
							best = a
				if best:
					var a := AnimLib.clean(best.duplicate(true))
					var oneshot := slug.contains("death") or slug.contains("fall") or slug.contains("hit")
					a.loop_mode = Animation.LOOP_NONE if oneshot else Animation.LOOP_LINEAR
					if a.get_track_count() > 0 and String(a.track_get_path(0)).begins_with("%GeneralSkeleton"):
						lib.add_animation("extra_" + slug, a)
						n += 1
					else:
						push_warning("npc extra: %s is not retargeted (no humanoid bone map?)" % p)
		root.free()
	if mode == "build":
		DirAccess.make_dir_recursive_absolute(OUT.get_base_dir())
		ResourceSaver.save(lib, OUT, ResourceSaver.FLAG_COMPRESS)
		print("npc extra: %d clips -> %s %s" % [n, OUT, JSON.stringify(lib.get_animation_list())])
	quit(0)


func _find_skel(n: Node) -> Skeleton3D:
	if n is Skeleton3D:
		return n
	for c in n.get_children():
		var s := _find_skel(c)
		if s:
			return s
	return null
