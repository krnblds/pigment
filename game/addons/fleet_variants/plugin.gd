@tool
extends EditorPlugin
## Registers res://addons/fleet_variants/vehicle_variants.gd (the fleet workstream's glTF extension,
## copied in by tools/godot/sync_vehicles.py) for imports.  Does nothing when it is not there.

const EXT := "res://addons/fleet_variants/vehicle_variants.gd"
var _ext: GLTFDocumentExtension


func _enter_tree() -> void:
	if ResourceLoader.exists(EXT):
		var s = load(EXT)
		if s:
			_ext = s.new()
			GLTFDocument.register_gltf_document_extension(_ext)


func _exit_tree() -> void:
	if _ext:
		GLTFDocument.unregister_gltf_document_extension(_ext)
		_ext = null
