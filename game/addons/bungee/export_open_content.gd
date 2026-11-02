@tool
extends EditorExportPlugin

var _export_directory: String = ""

func _get_name() -> String:
	return "BungeeOpenContent"

func _export_begin(_features: PackedStringArray, _is_debug: bool, path: String, _flags: int) -> void:
	_export_directory = path.get_base_dir()

func _export_end() -> void:
	if _export_directory.is_empty():
		return
	_copy_open_files(
		ProjectSettings.globalize_path("res://addons/bungee/sounds"),
		_export_directory.path_join("assets/sounds"),
		["wav"]
	)
	_copy_open_files(
		ProjectSettings.globalize_path("res://addons/bungee/presets/vehicles"),
		_export_directory.path_join("vehicle_presets"),
		["json"]
	)
	DirAccess.make_dir_recursive_absolute(_export_directory.path_join("vehicle_presets/custom"))

func _copy_open_files(source: String, destination: String, extensions: Array[String]) -> void:
	var directory := DirAccess.open(source)
	if directory == null:
		push_warning("Bungee export: Ordner fehlt: %s" % source)
		return
	DirAccess.make_dir_recursive_absolute(destination)
	for file_name in directory.get_files():
		if file_name.get_extension().to_lower() in extensions:
			var error := DirAccess.copy_absolute(source.path_join(file_name), destination.path_join(file_name))
			if error != OK:
				push_error("Bungee export: Datei konnte nicht kopiert werden: %s" % file_name)
	for folder_name in directory.get_directories():
		if not folder_name.begins_with("."):
			_copy_open_files(source.path_join(folder_name), destination.path_join(folder_name), extensions)
