extends SceneTree
## Headless tool (tools/npc/sync_godot.py runs it after the import):
##   godot --headless --path game -s res://scripts/npc/character/build_anim_library.gd
## Builds res://assets/npc/anim/library.res + library_lite.res (scripts/npc/character/anim_library.gd).

const AnimLib := preload("res://scripts/npc/character/anim_library.gd")


func _initialize() -> void:
	var ok := AnimLib.build_and_save()
	quit(0 if ok else 1)
