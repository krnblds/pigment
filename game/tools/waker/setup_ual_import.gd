extends SceneTree
## One-off: retarget the CC0 Quaternius Universal Animation Library mannequin to SkeletonProfileHumanoid.
## Writes assets/characters/ual/ual_bone_map.tres and points the gltf's import at it (bone map + rest
## fixer), so its animations share Godot's humanoid profile with any other retargeted character
## (e.g. the NPC workstream's MPFB officer). Run:
##   godot --headless --path game --script res://tools/waker/setup_ual_import.gd   then   godot --headless --path game --import

const SRC := "res://assets/characters/ual/AnimationLibrary_Godot_Standard.gltf"
const MAP_PATH := "res://assets/characters/ual/ual_bone_map.tres"

func _init() -> void:
	var m := {
		"Root": "root", "Hips": "DEF-hips", "Spine": "DEF-spine.001", "Chest": "DEF-spine.002",
		"UpperChest": "DEF-spine.003", "Neck": "DEF-neck", "Head": "DEF-head",
	}
	for s in ["Left", "Right"]:
		var x := ".L" if s == "Left" else ".R"
		m[s + "Shoulder"] = "DEF-shoulder" + x
		m[s + "UpperArm"] = "DEF-upper_arm" + x
		m[s + "LowerArm"] = "DEF-forearm" + x
		m[s + "Hand"] = "DEF-hand" + x
		m[s + "UpperLeg"] = "DEF-thigh" + x
		m[s + "LowerLeg"] = "DEF-shin" + x
		m[s + "Foot"] = "DEF-foot" + x
		m[s + "Toes"] = "DEF-toe" + x
		m[s + "ThumbMetacarpal"] = "DEF-thumb.01" + x
		m[s + "ThumbProximal"] = "DEF-thumb.02" + x
		m[s + "ThumbDistal"] = "DEF-thumb.03" + x
		for f in [["Index", "index"], ["Middle", "middle"], ["Ring", "ring"], ["Little", "pinky"]]:
			m[s + f[0] + "Proximal"] = "DEF-f_%s.01%s" % [f[1], x]
			m[s + f[0] + "Intermediate"] = "DEF-f_%s.02%s" % [f[1], x]
			m[s + f[0] + "Distal"] = "DEF-f_%s.03%s" % [f[1], x]
	var bm := BoneMap.new()
	bm.profile = SkeletonProfileHumanoid.new()
	for k in m:
		bm.set_skeleton_bone_name(StringName(k), StringName(m[k]))
	print("bone map: ", ResourceSaver.save(bm, MAP_PATH))
	var cf := ConfigFile.new()
	cf.load(SRC + ".import")
	cf.set_value("params", "_subresources", {
		"nodes": {"PATH:Rig/Skeleton3D": {"retarget/bone_map": load(MAP_PATH)}},
		## (the "_Loop" clips come in looping and without the suffix: Walk, Jog_Fwd, Sprint, Idle, ...)
	})
	cf.save(SRC + ".import")
	quit()
