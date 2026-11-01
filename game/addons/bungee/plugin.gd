@tool
extends EditorPlugin

var _export_plugin: EditorExportPlugin

func _enter_tree() -> void:
	_ensure_default_input_actions()
	_export_plugin = preload("res://addons/bungee/export_open_content.gd").new()
	add_export_plugin(_export_plugin)

func _exit_tree() -> void:
	if _export_plugin != null:
		remove_export_plugin(_export_plugin)
		_export_plugin = null

func _ensure_default_input_actions() -> void:
	var changed := false
	changed = _add_action_if_missing(&"gastrigger", [_joy_axis(JOY_AXIS_TRIGGER_RIGHT, 1.0), _key(KEY_W)]) or changed
	changed = _add_action_if_missing(&"braketrigger", [_joy_axis(JOY_AXIS_TRIGGER_LEFT, 1.0), _key(KEY_S)]) or changed
	changed = _add_action_if_missing(&"handbraketrigger", [_joy_button(JOY_BUTTON_A), _key(KEY_SPACE)]) or changed
	changed = _add_action_if_missing(&"shiftuptrigger", [_joy_button(JOY_BUTTON_RIGHT_SHOULDER), _key(KEY_E)]) or changed
	changed = _add_action_if_missing(&"shiftdowntrigger", [_joy_button(JOY_BUTTON_LEFT_SHOULDER), _key(KEY_Q)]) or changed
	if changed:
		ProjectSettings.save()
		InputMap.load_from_project_settings()
		print("Bungee Engine Audio: fehlende Input-Actions wurden zum Projekt hinzugefügt.")

func _add_action_if_missing(action: StringName, events: Array[InputEvent]) -> bool:
	var setting := "input/%s" % action
	if ProjectSettings.has_setting(setting):
		return false
	ProjectSettings.set_setting(setting, {"deadzone": 0.2, "events": events})
	return true

func _key(code: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.device = -1
	event.physical_keycode = code
	return event

func _joy_button(button: JoyButton) -> InputEventJoypadButton:
	var event := InputEventJoypadButton.new()
	event.device = -1
	event.button_index = button
	return event

func _joy_axis(axis: JoyAxis, value: float) -> InputEventJoypadMotion:
	var event := InputEventJoypadMotion.new()
	event.device = -1
	event.axis = axis
	event.axis_value = value
	return event
