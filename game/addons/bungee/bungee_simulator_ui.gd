class_name BungeeSimulatorUI
extends CanvasLayer
## Optionale Laufzeit-Oberfläche als Kind eines BungeeVehicleSimulator.

const UI_VERSION: String = "2.0"

var simulator: Node
var engine: Node
var parent_properties: Dictionary
var debug_label: Label
var settings_panel: PanelContainer
var settings_scroll: ScrollContainer
var debug_panel: PanelContainer
var ui_root: GridContainer
var debug_scroll: ScrollContainer
var debug_column: VBoxContainer
var power_graph_row: GridContainer
var dyno_graph: Control
var acceleration_display: Control
var enable_button: CheckButton
var graph_button: CheckButton
var debug_values_button: CheckButton
var automatic_vmax_button: CheckButton
var automatic_gears_button: CheckButton
var automatic_dyno_scale_button: CheckButton
var dyno_rpm_input: SpinBox
var dyno_power_input: SpinBox
var dyno_torque_input: SpinBox
var manual_rpm_slider: HSlider
var manual_rpm_label: Label
var fps_label: Label
var car_name_label: Label
var previous_car_button: Button
var next_car_button: Button
var horsepower_input: SpinBox
var mass_input: SpinBox
var max_rpm_input: SpinBox
var idle_rpm_input: SpinBox
var max_speed_input: SpinBox
var gear_count_input: SpinBox
var smoothness_input: SpinBox
var character_input: SpinBox
var engine_start_stop_button: Button
var style_selector: OptionButton
var language_selector: OptionButton
var vehicle_preset_selector: OptionButton
var preset_name_input: LineEdit
var preset_save_status: Label
var _last_engine_button_running: int = -1
var _ui_rebuild_queued: bool = false
var _limiter_flash_until_msec: int = 0
var sound_name_labels: Dictionary = {}

func _ready() -> void:
	# Parent-_ready laedt zuerst Presets und bindet diese UI. Der Deferred-Fallback
	# greift nur, falls die Node spaeter zur laufenden Szene hinzugefuegt wird.
	call_deferred("_auto_setup_from_parent")

func _auto_setup_from_parent() -> void:
	if simulator != null:
		return
	var owner_simulator := get_parent()
	if not owner_simulator is BungeeVehicleSimulator:
		push_error("BungeeSimulatorUI muss ein direktes Kind von BungeeVehicleSimulator sein.")
		visible = false
		return
	var sound_engine := owner_simulator.get_parent()
	var properties := {}
	if is_instance_valid(sound_engine):
		for property in sound_engine.get_property_list():
			properties[property.name] = true
	setup(owner_simulator, sound_engine, properties)

func _unhandled_input(event: InputEvent) -> void:
	release_focus_from_world_click(event)

#region Design und Sprache
func _palette() -> Dictionary:
	var index := clampi(int(simulator.ui_style) if is_instance_valid(simulator) else 0, 0, 4)
	return [
		{"panel": Color("202020"), "panel_deep": Color("171717"), "control_bg": Color("171717"), "border": Color("505050"), "grid": Color("333333"), "grid_minor": Color("292929"), "power": Color("64b5d8"), "torque": Color("d89b64"), "accent": Color("79d98c"), "vehicle": Color("64b5d8"), "sound": Color("e3a45f"), "extra": Color("b692e6"), "text": Color("eeeeee"), "control_text": Color("eeeeee"), "muted": Color("aaaaaa"), "radius": 8},
		{"panel": Color("c7c7c7"), "panel_deep": Color("070707"), "control_bg": Color("bdbdbd"), "border": Color("111111"), "grid": Color("3e3e3e"), "grid_minor": Color("252525"), "power": Color("efff00"), "torque": Color("b8d968"), "accent": Color("efff00"), "vehicle": Color("101010"), "sound": Color("101010"), "extra": Color("101010"), "text": Color("101010"), "control_text": Color("101010"), "muted": Color("565656"), "radius": 0},
		{"panel": Color("171814"), "panel_deep": Color("050605"), "control_bg": Color("050605"), "border": Color("d9dbcd"), "grid": Color("383a30"), "grid_minor": Color("25271f"), "power": Color("bde85d"), "torque": Color("efb66b"), "accent": Color("c3ef61"), "vehicle": Color("f2f2ed"), "sound": Color("efb66b"), "extra": Color("bde85d"), "text": Color("f1f1eb"), "control_text": Color("f1f1eb"), "muted": Color("aaa994"), "radius": 1},
		{"panel": Color("292b2c"), "panel_deep": Color("0d0f10"), "control_bg": Color("0d0f10"), "border": Color("deded8"), "grid": Color("4c4e4f"), "grid_minor": Color("303233"), "power": Color("f1f0e9"), "torque": Color("ef5035"), "accent": Color("ef5938"), "vehicle": Color("f1f0e9"), "sound": Color("ef5938"), "extra": Color("52a6cc"), "text": Color("f2f1eb"), "control_text": Color("f2f1eb"), "muted": Color("aeb1b1"), "radius": 0},
		{"panel": Color("172119"), "panel_deep": Color("09130c"), "control_bg": Color("09130c"), "border": Color("4f8b5d"), "grid": Color("24502f"), "grid_minor": Color("183820"), "power": Color("67ff7e"), "torque": Color("ffd166"), "accent": Color("a6ffb2"), "vehicle": Color("67ff7e"), "sound": Color("ffd166"), "extra": Color("71cfff"), "text": Color("e8f5e9"), "control_text": Color("e8f5e9"), "muted": Color("91ad96"), "radius": 4},
	][index]

func _t(source: String) -> String:
	if not is_instance_valid(simulator) or simulator.ui_language == 0:
		return source
	var exact := {
		"STEHENDE AUDIO-RPM · PHASERSCHUTZ": "STATIONARY AUDIO RPM · PHASER PROTECTION",
		"LEERLAUF · SIMULATION OHNE WAV": "IDLE · SIMULATION WITHOUT WAV",
		"RPM-BEGRENZER · RÜCKSPRUNG-KLANG": "RPM LIMITER · CUT SOUND",
		"GAS- UND SCHALTWOBBLE · NUR PITCH": "THROTTLE / SHIFT WOBBLE · PITCH ONLY",
		"Stillstand-Phaserschutz": "Stationary phaser protection",
		"Phaserschutz Mindestbewegung": "Phaser protection minimum scan speed",
		"Phaserschutz Klangbewegung": "Phaser protection pitch motion",
		"Phaserschutz Frequenz (Hz)": "Phaser protection frequency (Hz)",
		"Phaserschutz Stärke": "Phaser protection strength",
		"Druckdifferenz fuer vollen Aufbau": "Pressure gap for full spool rate",
		"FAHRZEUG & STEUERUNG": "VEHICLE & CONTROLS", "FAHRZEUG & MOTOR": "VEHICLE & ENGINE",
		"SOUND & KLANG": "SOUND & TONE", "ZUSATZSYSTEME": "AUXILIARY SYSTEMS", "ANZEIGE": "DISPLAY",
		"★ WICHTIGE MOTOR-EINSTELLUNGEN": "★ IMPORTANT ENGINE SETTINGS",
		"RPM-BEGRENZER · FAHRPHYSIK": "RPM LIMITER · VEHICLE PHYSICS",
		"ACC / DCC MOTOR-WIEDERGABE · SOUND": "ACC / DCC ENGINE PLAYBACK · SOUND",
		"AUDIO-PEGEL / CLIPPING-SCHUTZ": "AUDIO LEVEL / CLIPPING PROTECTION",
		"IDLE & LIMITER-WAV · NUR SOUND": "IDLE & LIMITER WAV · SOUND ONLY",
		"KLANGFILTER · NUR SOUND": "TONE FILTER · SOUND ONLY", "START / STOP · SOUND": "START / STOP · SOUND",
		"UMGEBUNGS-REVERB · TUNNEL / RÄUME": "ENVIRONMENT REVERB · TUNNEL / ROOMS",
		"Reverb aktiv": "Reverb enabled", "Reverb Preset": "Reverb preset",
		"Reverb Stärke (0–1)": "Reverb amount (0–1)", "Reverb Ein-/Ausblendung": "Reverb fade speed",
		"INNENRAUMKLANG · FAHRERPERSPEKTIVE": "CABIN SOUND · DRIVER PERSPECTIVE",
		"Innenraumklang aktiv": "Cabin sound enabled", "Innenraum Preset": "Cabin preset",
		"Innenraum Stärke (0–1)": "Cabin amount (0–1)", "Innen-/Außen-Übergang": "Cabin transition speed",
		"MOTORCHARAKTER / TUNING": "ENGINE CHARACTER / TUNING", "FAHRWIDERSTAND / BREMSEN": "DRAG / BRAKES",
		"ANFAHREN / FREIES HOCHDREHEN": "LAUNCH / FREE REV", "SCHALTWOBBLE": "SHIFT WOBBLE",
		"RENNSTART / PERFECT LAUNCH": "RACE START / PERFECT LAUNCH", "GETRIEBE": "TRANSMISSION",
		"SUPERCHARGER · LEISTUNG + SOUND": "SUPERCHARGER · POWER + SOUND",
		"TURBO / BOV · LEISTUNG + SOUND": "TURBO / BOV · POWER + SOUND",
		"BACKFIRE SOUND": "BACKFIRE SOUND", "ANZEIGE / DYNO-SKALA · NUR UI": "DISPLAY / DYNO SCALE · UI ONLY",
		"STEUERUNGSHILFE": "CONTROL HELP", "Simulator aktiv": "Simulator enabled", "Dyno anzeigen": "Show dyno",
		"Debug-Zahlen anzeigen": "Show debug values", "Vmax automatisch": "Automatic top speed",
		"Dyno-Skala automatisch": "Automatic dyno scale",
		"Gangautomatik": "Automatic transmission", "Automatisch perfekter Schaltpunkt": "Automatic perfect shift",
		"Perfect-Launch-System": "Perfect launch system", "RPM-Push aktiv": "RPM push enabled",
		"Motor läuft": "Engine running", "Richtungsklang": "Directional tone", "Audio Hard-Limiter": "Audio hard limiter",
		"Limiter-WAV verwenden": "Use limiter WAV", "RPM-Kick bei Backfire": "RPM kick on backfire",
		"Zufällige Variationen": "Random variations", "Wobble aktiv": "Wobble enabled",
		"Motor-Struggle aktiv": "Engine struggle enabled",
		"Interface Style": "Interface style", "Deutsch": "German", "English": "English",
		"Gang -": "Gear -", "Gang +": "Gear +", "Keine Soundbank": "No soundbank",
		"Nicht belegt": "Not assigned", "Automatik": "Automatic", "Manuell": "Manual",
		"Gas": "Throttle", "Bremse": "Brake", "Handbremse": "Handbrake", "Gang hoch": "Shift up", "Gang runter": "Shift down",
	}
	if exact.has(source):
		return exact[source]
	var result := source
	var replacements := [
		["Perfekter Start", "Perfect start"], ["Gut/Perfekt Bonusdauer", "Good/perfect bonus duration"],
		["Wheelspin ausblenden bis", "Fade wheelspin until"], ["Wheelspin RPM-Stocken", "Wheelspin RPM struggle"],
		["Zurückspringen auf", "Drop back to"], ["Auslösen bei", "Trigger at"], ["Cut Stärke", "Cut strength"],
		["Motorleistung", "Engine power"], ["Fahrzeugmasse", "Vehicle mass"], ["Manuelle Vmax", "Manual top speed"],
		["Motorglätte / Tuning", "Engine smoothness / tuning"], ["Motorcharakter", "Engine character"],
		["Motor-Struggle Stärke", "Engine struggle strength"], ["Untertourige Grenze", "Low-RPM threshold"],
		["Schalt-Struggle Stärke", "Shift struggle strength"], ["Schalt-Struggle Dauer", "Shift struggle duration"],
		["Normale Bremse", "Brake strength"], ["Handbremse / Entkoppelt", "Handbrake / disengaged"],
		["Ausrollen ohne Gas", "Coasting without throttle"],
		["Anfahr-RPM", "Launch RPM"],
		["Freies Hochdrehen Stärke", "Free rev strength"], ["Freies RPM Abfallen", "Free RPM fall"],
		["Sprunggeschwindigkeit", "Jump speed"], ["RPM-Sprung", "RPM jump"],
		["Wobble Stärke", "Wobble strength"], ["Wobble Dauer", "Wobble duration"],
		["Ganganzahl", "Gear count"], ["RPM nach Hochschalten", "RPM after upshift"],
		["Manueller Hochschaltpunkt", "Manual upshift point"], ["Manueller Runterschaltpunkt", "Manual downshift point"],
		["Schaltzeit", "Shift time"], ["Downshift-Sperre", "Downshift lock"], ["Traktion wieder aufbauen", "Traction recovery"],
		["Motor Gesamtlautstärke", "Engine master volume"], ["Ausgabe Headroom", "Output headroom"],
		["Übergang", "transition"], ["Stärke", "strength"], ["Höhen ab", "Treble from"], ["Höhen Gain", "Treble gain"],
		["Höhen", "Treble"], ["Idle Übergang Ende", "Idle transition end"], ["einblenden ab Audio-Position", "fade in from audio position"],
		["Start-Aufheulen RPM", "Start rev RPM"], ["Extra Leistung", "Additional power"], ["Leistung", "Power"],
		["Max Salvendauer", "Max burst duration"], ["Volllast Aufbauzeit", "Full-load build time"],
		["Mindestlast", "Minimum load"], ["Bang Abstand", "Bang interval"], ["Anzeige Max", "Display max"],
		["hohe Geschwindigkeit", "high speed"], ["niedrige Geschwindigkeit", "low speed"],
	]
	for pair in replacements:
		result = result.replace(pair[0], pair[1])
	return result

#endregion

#region UI-Lebenszyklus
func rebuild_ui() -> void:
	if _ui_rebuild_queued:
		return
	_ui_rebuild_queued = true
	_perform_ui_rebuild.call_deferred()

func _perform_ui_rebuild() -> void:
	_ui_rebuild_queued = false
	if is_instance_valid(ui_root):
		remove_child(ui_root)
		ui_root.queue_free()
	_build()
	fit_to_screen.call_deferred()

func apply_ui_style() -> void:
	if not is_instance_valid(ui_root):
		return
	var colors := _palette()
	var theme := Theme.new()
	var control_hover_color: Color = colors.control_text if simulator.ui_style == 1 else colors.accent
	theme.set_color("font_color", "Label", colors.text)
	theme.set_color("font_color", "CheckButton", colors.text)
	theme.set_color("font_hover_color", "CheckButton", control_hover_color)
	for control_type in ["Button", "OptionButton", "LineEdit", "SpinBox"]:
		theme.set_color("font_color", control_type, colors.control_text)
		theme.set_color("font_hover_color", control_type, control_hover_color)
		theme.set_color("font_pressed_color", control_type, control_hover_color)
	var control_box := StyleBoxFlat.new()
	control_box.bg_color = colors.control_bg
	control_box.border_color = Color(colors.border.r, colors.border.g, colors.border.b, 0.7)
	control_box.set_border_width_all(1)
	control_box.set_corner_radius_all(int(colors.radius))
	control_box.content_margin_left = 8
	control_box.content_margin_right = 8
	control_box.content_margin_top = 5
	control_box.content_margin_bottom = 5
	for control_type in ["Button", "OptionButton", "LineEdit"]:
		theme.set_stylebox("normal", control_type, control_box)
		var hover_box := control_box.duplicate()
		hover_box.bg_color = colors.panel
		hover_box.border_color = colors.accent
		theme.set_stylebox("hover", control_type, hover_box)
		var pressed_box := control_box.duplicate()
		pressed_box.bg_color = Color(colors.accent.r, colors.accent.g, colors.accent.b, 0.22)
		pressed_box.border_color = colors.accent
		theme.set_stylebox("pressed", control_type, pressed_box)
	ui_root.theme = theme
	if is_instance_valid(settings_panel): settings_panel.add_theme_stylebox_override("panel", _style())
	if is_instance_valid(debug_panel): debug_panel.add_theme_stylebox_override("panel", _style())
	if is_instance_valid(style_selector): style_selector.select(clampi(simulator.ui_style, 0, 4))
	if is_instance_valid(dyno_graph): dyno_graph.queue_redraw()
	if is_instance_valid(acceleration_display): acceleration_display.queue_redraw()

func setup(owner_simulator: Node, sound_engine: Node, properties: Dictionary) -> void:
	simulator = owner_simulator
	engine = sound_engine
	parent_properties = properties
	layer = 100
	if is_instance_valid(ui_root):
		rebuild_ui()
		refresh()
		return
	_build()
	visible = simulator.debug_ui_enabled
	if not get_viewport().size_changed.is_connected(fit_to_screen):
		get_viewport().size_changed.connect(fit_to_screen)
	fit_to_screen.call_deferred()
	refresh()

#endregion

#region Darstellung und wiederverwendbare Controls
func _style() -> StyleBoxFlat:
	var colors := _palette()
	var box := StyleBoxFlat.new()
	box.bg_color = colors.panel
	box.border_color = colors.border
	box.set_border_width_all(2)
	box.set_corner_radius_all(int(colors.radius))
	box.content_margin_left = 16
	box.content_margin_right = 16
	box.content_margin_top = 12
	box.content_margin_bottom = 12
	box.shadow_color = Color(0, 0, 0, 0.35)
	box.shadow_size = 6
	return box

func _badge_style() -> StyleBoxFlat:
	var colors := _palette()
	var box := StyleBoxFlat.new()
	box.bg_color = colors.panel_deep
	box.border_color = colors.border
	box.set_border_width_all(1)
	box.set_corner_radius_all(int(colors.radius))
	box.content_margin_left = 9
	box.content_margin_right = 9
	box.content_margin_top = 3
	box.content_margin_bottom = 3
	return box

func _styled_accent(original: Color) -> Color:
	var colors := _palette()
	if original.is_equal_approx(Color("64b5d8")): return colors.vehicle
	if original.is_equal_approx(Color("e3a45f")): return colors.sound
	if original.is_equal_approx(Color("b692e6")): return colors.extra
	return colors.accent if original.a > 0.01 else original

func _draw_engine_start_button() -> void:
	if not is_instance_valid(engine_start_stop_button):
		return
	var running := is_instance_valid(engine) and parent_properties.has("engine_running") and bool(engine.get("engine_running"))
	var center := engine_start_stop_button.size * 0.5
	var hovered := engine_start_stop_button.is_hovered()
	var pressed := engine_start_stop_button.button_pressed
	var glow := Color("43b9ff") if running else Color("ffb34f")
	if hovered:
		glow = glow.lightened(0.2)
	# Gleicher Aufbau wie die Shift-Lampen: schwarzer Außenrand, Metallfassung,
	# schwarzer Innenring und eine zurückgesetzte leuchtende Fläche.
	engine_start_stop_button.draw_circle(center, 47.0, Color("050607"))
	engine_start_stop_button.draw_circle(center, 42.0, Color("4b5054"))
	engine_start_stop_button.draw_circle(center, 38.0, Color("0a0c0e"))
	engine_start_stop_button.draw_circle(center, 32.0, Color(glow.r, glow.g, glow.b, 0.22 if not pressed else 0.38))
	engine_start_stop_button.draw_circle(center, 27.0 if not pressed else 25.0, Color("14191d") if not pressed else Color("0c1013"))
	engine_start_stop_button.draw_arc(center, 30.0, 0.0, TAU, 64, glow, 2.5 if not hovered else 4.0, true)
	var font := ThemeDB.fallback_font
	engine_start_stop_button.draw_string(font, Vector2(0, center.y - 3), "ENGINE", HORIZONTAL_ALIGNMENT_CENTER, engine_start_stop_button.size.x, 10, Color("c9d0d4"))
	engine_start_stop_button.draw_string(font, Vector2(0, center.y + 14), "STOP" if running else "START", HORIZONTAL_ALIGNMENT_CENTER, engine_start_stop_button.size.x, 12, glow)

func _check(text: String, state: bool, callback: Callable) -> CheckButton:
	var button := CheckButton.new()
	button.text = _t(text)
	button.focus_mode = Control.FOCUS_NONE
	button.set_pressed_no_signal(state)
	button.toggled.connect(callback)
	return button

func _section_title(parent: VBoxContainer, text: String, color: Color) -> void:
	color = _styled_accent(color)
	var title := Label.new()
	title.text = _t(text)
	title.add_theme_font_size_override("font_size", 13)
	title.add_theme_color_override("font_color", color)
	title.add_theme_constant_override("outline_size", 3)
	title.add_theme_color_override("font_outline_color", Color("101010"))
	parent.add_child(title)
	parent.add_child(HSeparator.new())

func _input_help_line(caption: String, action: StringName) -> String:
	if not InputMap.has_action(action):
		return "%s: %s" % [_t(caption), _t("Nicht belegt")]
	var bindings := PackedStringArray()
	for event in InputMap.action_get_events(action):
		if event is InputEventKey:
			var key_text := event.as_text().replace(" (Physical)", "")
			bindings.append(key_text)
		elif event is InputEventJoypadMotion:
			var axis_names := {4: "LT", 5: "RT"}
			bindings.append(axis_names.get(event.axis, "Controller Achse %d" % event.axis))
		elif event is InputEventJoypadButton:
			var button_names := {0: "A", 1: "B", 2: "X", 3: "Y", 7: "L3", 8: "R3", 9: "LB", 10: "RB"}
			bindings.append(button_names.get(event.button_index, "Controller Button %d" % event.button_index))
	return "%s: %s" % [_t(caption), _t("Nicht belegt") if bindings.is_empty() else " / ".join(bindings)]

func _number(parent: VBoxContainer, text: String, minimum: float, maximum: float, step_value: float, value: float, callback: Callable) -> SpinBox:
	var label := Label.new()
	label.text = _t(text)
	label.add_theme_color_override("font_color", _palette().text)
	parent.add_child(label)
	var input := SpinBox.new()
	input.min_value = minimum
	input.max_value = maximum
	input.step = step_value
	input.value = value
	input.custom_minimum_size = Vector2(0, 28)
	input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	input.value_changed.connect(callback)
	parent.add_child(input)
	return input

func _subgroup(parent: VBoxContainer, title: String, opened: bool = false, accent: Color = Color.TRANSPARENT) -> VBoxContainer:
	accent = _styled_accent(accent)
	var header := Button.new()
	header.focus_mode = Control.FOCUS_NONE
	header.alignment = HORIZONTAL_ALIGNMENT_LEFT
	header.toggle_mode = true
	header.set_pressed_no_signal(opened)
	if accent.a > 0.01:
		header.add_theme_color_override("font_color", accent)
		header.add_theme_color_override("font_hover_color", accent.lightened(0.18))
		var highlighted := StyleBoxFlat.new()
		highlighted.bg_color = Color(accent.r, accent.g, accent.b, 0.12)
		highlighted.border_color = Color(accent.r, accent.g, accent.b, 0.55)
		highlighted.set_border_width_all(1)
		highlighted.set_corner_radius_all(int(_palette().radius))
		highlighted.content_margin_left = 10
		highlighted.content_margin_right = 8
		highlighted.content_margin_top = 7
		highlighted.content_margin_bottom = 7
		header.add_theme_stylebox_override("normal", highlighted)
		header.add_theme_stylebox_override("pressed", highlighted)
	parent.add_child(header)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 5)
	content.visible = opened
	parent.add_child(content)
	var update_header := func(active: bool):
		content.visible = active
		header.text = ("▼ " if active else "▶ ") + _t(title)
		_fit_after_group_change.call_deferred()
	header.toggled.connect(update_header)
	update_header.call(opened)
	return content

func _audio_subgroup(parent: VBoxContainer, opened: bool = false) -> VBoxContainer:
	# Verschachtelte Audio-Einstellungen bewusst eingerückt und eingefasst, damit
	# die nächste Hauptgruppe optisch nicht zum offenen Sound Setup gehört.
	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 14)
	margin.add_theme_constant_override("margin_right", 4)
	parent.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 4)
	margin.add_child(column)
	var header := Button.new()
	header.focus_mode = Control.FOCUS_NONE
	header.alignment = HORIZONTAL_ALIGNMENT_LEFT
	header.toggle_mode = true
	header.set_pressed_no_signal(opened)
	var colors := _palette()
	header.add_theme_color_override("font_color", colors.sound)
	column.add_child(header)
	var panel := PanelContainer.new()
	var panel_style := StyleBoxFlat.new()
	panel_style.bg_color = colors.panel_deep
	panel_style.border_color = Color(colors.sound.r, colors.sound.g, colors.sound.b, 0.55)
	panel_style.set_border_width_all(1)
	panel_style.set_corner_radius_all(int(colors.radius))
	panel_style.content_margin_left = 10
	panel_style.content_margin_right = 10
	panel_style.content_margin_top = 8
	panel_style.content_margin_bottom = 8
	panel.add_theme_stylebox_override("panel", panel_style)
	panel.visible = opened
	column.add_child(panel)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 5)
	panel.add_child(content)
	var update_header := func(active: bool):
		panel.visible = active
		header.text = ("▼  " if active else "▶  ") + "AUDIO · SOUND SETUP"
		_fit_after_group_change.call_deferred()
	header.toggled.connect(update_header)
	update_header.call(opened)
	return content

func _fit_after_group_change() -> void:
	fit_to_screen(Vector2.ZERO, true)

func _engine_check(parent: VBoxContainer, text: String, property: StringName) -> CheckButton:
	var state := bool(engine.get(property)) if is_instance_valid(engine) and parent_properties.has(property) else false
	var button := _check(text, state, func(value):
		if is_instance_valid(engine) and parent_properties.has(property): engine.set(property, value)
	)
	parent.add_child(button)
	return button

func _sound_selector(parent: VBoxContainer, title: String, index_property: StringName, files_property: StringName, name_property: StringName) -> void:
	var caption := Label.new(); caption.text = title; caption.add_theme_color_override("font_color", Color("cccccc")); parent.add_child(caption)
	var row := HBoxContainer.new(); parent.add_child(row)
	var previous := Button.new(); previous.text = "◀"; previous.focus_mode = Control.FOCUS_NONE
	var label := Label.new(); label.size_flags_horizontal = Control.SIZE_EXPAND_FILL; label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER; label.clip_text = true
	var next := Button.new(); next.text = "▶"; next.focus_mode = Control.FOCUS_NONE
	row.add_child(previous); row.add_child(label); row.add_child(next)
	sound_name_labels[index_property] = {"label": label, "previous": previous, "next": next, "files": files_property, "name": name_property}
	previous.pressed.connect(_change_sound.bind(index_property, files_property, -1))
	next.pressed.connect(_change_sound.bind(index_property, files_property, 1))

func _change_sound(index_property: StringName, files_property: StringName, direction: int) -> void:
	if not is_instance_valid(engine) or not parent_properties.has(index_property) or not parent_properties.has(files_property): return
	var files: Array = engine.get(files_property)
	if files.is_empty(): return
	engine.set(index_property, posmod(int(engine.get(index_property)) + direction, files.size()))
	refresh()

#endregion

#region Aufbau - Fahrzeug, Sound, Extras und Anzeige
func _build() -> void:
	ui_root = GridContainer.new()
	ui_root.position = Vector2(16, 16)
	ui_root.columns = 2
	ui_root.add_theme_constant_override("h_separation", 10)
	ui_root.add_theme_constant_override("v_separation", 10)
	add_child(ui_root)
	settings_panel = PanelContainer.new()
	settings_panel.custom_minimum_size = Vector2(440, 760)
	settings_panel.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	settings_panel.add_theme_stylebox_override("panel", _style())
	settings_panel.gui_input.connect(_clear_focus_on_click)
	ui_root.add_child(settings_panel)
	settings_scroll = ScrollContainer.new()
	settings_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	settings_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	settings_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	settings_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	settings_panel.add_child(settings_scroll)
	var settings := VBoxContainer.new()
	settings.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	settings.add_theme_constant_override("separation", 6)
	settings_scroll.add_child(settings)
	var header := HBoxContainer.new()
	header.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	settings.add_child(header)
	var title := Label.new()
	title.text = _t("FAHRZEUG & STEUERUNG")
	title.add_theme_font_size_override("font_size", 16)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title)
	var fps_box := PanelContainer.new()
	fps_box.custom_minimum_size = Vector2(82, 26)
	fps_box.add_theme_stylebox_override("panel", _badge_style())
	header.add_child(fps_box)
	fps_label = Label.new()
	fps_label.text = "FPS: --"
	fps_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	fps_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	fps_label.add_theme_font_size_override("font_size", 13)
	fps_label.add_theme_color_override("font_color", Color("79d98c"))
	fps_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	fps_box.add_child(fps_label)
	enable_button = _check("Simulator aktiv", simulator.simulator_enabled, func(v): simulator.simulator_enabled = v)
	graph_button = _check("Dyno anzeigen", simulator.power_graph_enabled, func(v): simulator.power_graph_enabled = v)
	debug_values_button = _check("Debug-Zahlen anzeigen", simulator.debug_values_enabled, func(v): simulator.debug_values_enabled = v)
	automatic_vmax_button = _check("Vmax automatisch", simulator.automatic_max_speed, func(v): simulator.automatic_max_speed = v; sync_controls())
	var car_row := HBoxContainer.new()
	settings.add_child(car_row)
	previous_car_button = Button.new(); previous_car_button.text = "◀"; previous_car_button.focus_mode = Control.FOCUS_NONE
	next_car_button = Button.new(); next_car_button.text = "▶"; next_car_button.focus_mode = Control.FOCUS_NONE
	previous_car_button.pressed.connect(_change_car.bind(-1)); next_car_button.pressed.connect(_change_car.bind(1))
	car_name_label = Label.new(); car_name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL; car_name_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER; car_name_label.clip_text = true; car_name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	car_row.add_child(previous_car_button); car_row.add_child(car_name_label); car_row.add_child(next_car_button)
	var preset_group := _subgroup(settings, "FAHRZEUG-PRESET", true, Color("64b5d8"))
	var preset_caption := Label.new(); preset_caption.text = "Fahrzeug-Preset" if simulator.ui_language == 0 else "Vehicle preset"; preset_group.add_child(preset_caption)
	vehicle_preset_selector = OptionButton.new()
	vehicle_preset_selector.focus_mode = Control.FOCUS_NONE
	for preset in simulator.vehicle_presets:
		vehicle_preset_selector.add_item("%s · %s" % [preset.category, preset.name])
	vehicle_preset_selector.select(clampi(simulator.selected_vehicle_preset, 0, maxi(vehicle_preset_selector.item_count - 1, 0)))
	vehicle_preset_selector.item_selected.connect(func(index): simulator.selected_vehicle_preset = index)
	preset_group.add_child(vehicle_preset_selector)
	var load_preset_button := Button.new(); load_preset_button.text = "PRESET LADEN" if simulator.ui_language == 0 else "LOAD PRESET"; load_preset_button.focus_mode = Control.FOCUS_NONE; load_preset_button.disabled = simulator.vehicle_presets.is_empty(); load_preset_button.pressed.connect(func(): simulator.apply_vehicle_preset(simulator.selected_vehicle_preset)); preset_group.add_child(load_preset_button)
	preset_name_input = LineEdit.new()
	preset_name_input.placeholder_text = "Name fuer eigenes Preset" if simulator.ui_language == 0 else "Custom preset name"
	preset_name_input.max_length = 80
	preset_name_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	preset_group.add_child(preset_name_input)
	var save_preset_button := Button.new()
	save_preset_button.text = "ALS EIGENES PRESET SPEICHERN" if simulator.ui_language == 0 else "SAVE AS CUSTOM PRESET"
	save_preset_button.focus_mode = Control.FOCUS_NONE
	save_preset_button.pressed.connect(_save_current_preset)
	preset_group.add_child(save_preset_button)
	preset_save_status = Label.new()
	preset_save_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	preset_group.add_child(preset_save_status)
	settings.add_child(HSeparator.new())
	var category_legend := HBoxContainer.new(); category_legend.add_theme_constant_override("separation", 10); settings.add_child(category_legend)
	var colors := _palette()
	var motor_badge := Label.new(); motor_badge.text = "● " + ("FAHRZEUG" if simulator.ui_language == 0 else "VEHICLE"); motor_badge.add_theme_font_size_override("font_size", 10); motor_badge.add_theme_color_override("font_color", colors.vehicle); category_legend.add_child(motor_badge)
	var sound_badge := Label.new(); sound_badge.text = "● SOUND"; sound_badge.add_theme_font_size_override("font_size", 10); sound_badge.add_theme_color_override("font_color", colors.sound); category_legend.add_child(sound_badge)
	var extra_badge := Label.new(); extra_badge.text = "● EXTRAS"; extra_badge.add_theme_font_size_override("font_size", 10); extra_badge.add_theme_color_override("font_color", colors.extra); category_legend.add_child(extra_badge)
	# Feste Kategorie-Reihenfolge: Fahrzeug -> Sound -> Extras -> reine Anzeige.
	# Die einzelnen Gruppen können im Build-Code unabhängig davon befüllt werden.
	var vehicle_section := VBoxContainer.new(); vehicle_section.add_theme_constant_override("separation", 5); settings.add_child(vehicle_section)
	var sound_section := VBoxContainer.new(); sound_section.add_theme_constant_override("separation", 5); settings.add_child(sound_section)
	var extras_section := VBoxContainer.new(); extras_section.add_theme_constant_override("separation", 5); settings.add_child(extras_section)
	var display_section := VBoxContainer.new(); display_section.add_theme_constant_override("separation", 5); settings.add_child(display_section)
	_section_title(vehicle_section, "FAHRZEUG & MOTOR", Color("64b5d8"))
	_section_title(sound_section, "SOUND & KLANG", Color("e3a45f"))
	_section_title(extras_section, "ZUSATZSYSTEME", Color("b692e6"))
	_section_title(display_section, "ANZEIGE", Color("92989d"))
	var primary_motor := _subgroup(vehicle_section, "★ WICHTIGE MOTOR-EINSTELLUNGEN", false, Color("64b5d8"))
	horsepower_input = _number(primary_motor, "Motorleistung (PS)", 1, 2000, 1, simulator.horsepower, func(v): simulator.horsepower = v)
	mass_input = _number(primary_motor, "Fahrzeugmasse (kg)", 100, 5000, 10, simulator.vehicle_mass_kg, func(v): simulator.vehicle_mass_kg = v)
	max_rpm_input = _number(primary_motor, "Max RPM", 1000, 20000, 5, simulator.max_rpm, func(v): simulator.max_rpm = v)
	idle_rpm_input = _number(primary_motor, "Idle RPM", 500, 2000, 5, simulator.idle_rpm, func(v): simulator.idle_rpm = v)
	var idle_simulation := _subgroup(vehicle_section, "LEERLAUF · SIMULATION OHNE WAV", false, Color("64b5d8"))
	var artificial_idle_switch := _check("Künstliches Idle ohne WAV", simulator.artificial_idle_enabled, func(v): simulator.artificial_idle_enabled = v); idle_simulation.add_child(artificial_idle_switch)
	_number(idle_simulation, "Idle Puls (RPM)", 0, 500, 5, simulator.artificial_idle_pulse_rpm, func(v): simulator.artificial_idle_pulse_rpm = v)
	_number(idle_simulation, "Idle Puls Geschwindigkeit (Hz)", 0.5, 8, 0.1, simulator.artificial_idle_pulse_speed, func(v): simulator.artificial_idle_pulse_speed = v)
	var rpm_limiter := _subgroup(vehicle_section, "RPM-BEGRENZER · FAHRPHYSIK", false, Color("64b5d8"))
	var artificial_limiter := _check("RPM-Push aktiv", simulator.artificial_rpm_limiter_enabled, func(v): simulator.artificial_rpm_limiter_enabled = v); rpm_limiter.add_child(artificial_limiter)
	var limiter_trigger_info := Label.new()
	limiter_trigger_info.text = "Automatischer Trigger: Max RPM − 0"
	rpm_limiter.add_child(limiter_trigger_info)
	_number(rpm_limiter, "Rücksprungweite (RPM)", 5, 5000, 5, simulator.artificial_rpm_limiter_drop_amount_rpm, func(v): simulator.artificial_rpm_limiter_drop_amount_rpm = v)
	_number(rpm_limiter, "Cut Stärke", 1, 20, 0.5, simulator.artificial_rpm_limiter_cut_strength, func(v): simulator.artificial_rpm_limiter_cut_strength = v)
	var motor_sound := _subgroup(sound_section, "ACC / DCC MOTOR-WIEDERGABE · SOUND", true, Color("e3a45f"))
	_engine_check(motor_sound, "3D Audio", &"use_3d_audio")
	_number(motor_sound, "Motor Gesamtlautstärke", 0, 2, 0.01, _sound_value("acceleration_volume", 1.0), func(v): engine.set("acceleration_volume", v))
	_number(motor_sound, "ACC / DCC Übergang (ms)", 0, 250, 0.5, _sound_value("acc_dcc_transition_ms", 4.0), func(v): engine.set("acc_dcc_transition_ms", v))
	var follow_control := _number(motor_sound, "Audio Follow Stärke", 0.1, 100, 0.1, _sound_value("distance_strength", 10.0), func(v): engine.set("distance_strength", v))
	follow_control.tooltip_text = "Nur Audio-Nachlauf, keine Fahrleistung. Struggle und Limiter nutzen feste Referenz 20." if simulator.ui_language == 0 else "Audio response only, no vehicle power change. Struggle and limiter use a fixed reference of 20."
	_number(motor_sound, "Zielbremsung Bereich (RPM 0–1)", 0, 0.25, 0.005, _sound_value("follow_target_brake_distance", 0.08), func(v): engine.set("follow_target_brake_distance", v))
	_number(motor_sound, "Zielbremsung Stärke", 0, 1, 0.01, _sound_value("follow_target_brake_strength", 0.9), func(v): engine.set("follow_target_brake_strength", v))
	_number(motor_sound, "Motor Pitch", 0.5, 2, 0.01, _sound_value("engine_pitch", 1.0), func(v): engine.set("engine_pitch", v))
	var stationary_settings := _subgroup(motor_sound, "STEHENDE AUDIO-RPM · PHASERSCHUTZ", false, Color("e3a45f"))
	_engine_check(stationary_settings, "Stillstand-Phaserschutz", &"stationary_grain_protection")
	_number(stationary_settings, "Phaserschutz Mindestbewegung", 0, 1, 0.005, _sound_value("stationary_min_scan_speed", 0.2), func(v): engine.set("stationary_min_scan_speed", v))
	_number(stationary_settings, "Phaserschutz Frequenz (Hz)", 0.1, 20, 0.1, _sound_value("stationary_motion_frequency_hz", 2.0), func(v): engine.set("stationary_motion_frequency_hz", v))
	_number(stationary_settings, "Phaserschutz Stärke", 0, 0.15, 0.001, _sound_value("stationary_pitch_motion", 0.04), func(v): engine.set("stationary_pitch_motion", v))
	var engine_bus := _subgroup(sound_section, "AUDIO-PEGEL / CLIPPING-SCHUTZ", false, Color("e3a45f"))
	var bus_hint := Label.new(); bus_hint.text = "Nur Audio-Lautstärke – keine Wirkung auf RPM" if simulator.ui_language == 0 else "Audio volume only – does not affect RPM"; bus_hint.add_theme_color_override("font_color", _palette().sound.darkened(0.18)); engine_bus.add_child(bus_hint)
	_number(engine_bus, "Ausgabe Headroom (dB)", -18, 0, 0.5, _sound_value("output_headroom_db", -6.0), func(v): engine.set("output_headroom_db", v))
	_engine_check(engine_bus, "Audio Hard-Limiter", &"hard_limiter_enabled")
	_number(engine_bus, "Pre Gain (dB)", -24, 0, 0.5, _sound_value("hard_limiter_pre_gain_db", -6.0), func(v): engine.set("hard_limiter_pre_gain_db", v))
	_number(engine_bus, "Ceiling (dB)", -12, 0, 0.5, _sound_value("hard_limiter_ceiling_db", -2.0), func(v): engine.set("hard_limiter_ceiling_db", v))
	_number(engine_bus, "Release (ms)", 1, 200, 1, _sound_value("hard_limiter_release_ms", 80.0), func(v): engine.set("hard_limiter_release_ms", v))
	var loops := _subgroup(sound_section, "IDLE & LIMITER-WAV · NUR SOUND", false, Color("e3a45f"))
	_engine_check(loops, "Idle Sound", &"idle_enabled")
	_number(loops, "Idle Übergang Ende", 0.01, 0.25, 0.005, _sound_value("idle_fade_end", 0.08), func(v): engine.set("idle_fade_end", v))
	_number(loops, "Idle Volume", 0, 2, 0.01, _sound_value("idle_volume", 1.0), func(v): engine.set("idle_volume", v))
	_engine_check(loops, "Limiter-WAV verwenden", &"limiter_enabled")
	_number(loops, "Limiter-WAV einblenden ab Audio-Position", 0.75, 0.99, 0.005, _sound_value("limiter_fade_start", 0.94), func(v): engine.set("limiter_fade_start", v))
	_number(loops, "Limiter-WAV Volume", 0, 2, 0.01, _sound_value("limiter_volume", 1.0), func(v): engine.set("limiter_volume", v))
	var limiter_audio := _subgroup(sound_section, "RPM-BEGRENZER · RÜCKSPRUNG-KLANG", false, Color("e3a45f"))
	_engine_check(limiter_audio, "Limiter-Rücksprung nutzt DCC", &"limiter_cut_uses_dcc")
	_engine_check(limiter_audio, "Limiter Fast Cut (klickfrei)", &"limiter_cut_instant")
	var engine_tone := _subgroup(sound_section, "KLANGFILTER · NUR SOUND", false, Color("e3a45f"))
	_engine_check(engine_tone, "Richtungsklang", &"direction_tone_enabled")
	_number(engine_tone, "Rise Cutoff (Hz)", 1000, 20000, 100, _sound_value("tone_cutoff_rise_hz", 19500.0), func(v): engine.set("tone_cutoff_rise_hz", v))
	_number(engine_tone, "Fall Cutoff (Hz)", 1000, 20000, 100, _sound_value("tone_cutoff_fall_hz", 14000.0), func(v): engine.set("tone_cutoff_fall_hz", v))
	_number(engine_tone, "Rise Resonance", 0, 1, 0.01, _sound_value("tone_resonance_rise", 0.12), func(v): engine.set("tone_resonance_rise", v))
	_number(engine_tone, "Fall Resonance", 0, 1, 0.01, _sound_value("tone_resonance_fall", 0.05), func(v): engine.set("tone_resonance_fall", v))
	_engine_check(engine_tone, "Höhen", &"highs_enabled")
	_number(engine_tone, "Höhen Gain (dB)", 0, 6, 0.5, _sound_value("highs_gain_db", 3.0), func(v): engine.set("highs_gain_db", v))
	_number(engine_tone, "Höhen ab (Hz)", 1000, 10000, 100, _sound_value("highs_start_hz", 3500.0), func(v): engine.set("highs_start_hz", v))
	var environment_reverb := _subgroup(sound_section, "UMGEBUNGS-REVERB · TUNNEL / RÄUME", false, Color("e3a45f"))
	_engine_check(environment_reverb, "Reverb aktiv", &"reverb_enabled")
	var reverb_preset_caption := Label.new()
	reverb_preset_caption.text = _t("Reverb Preset")
	environment_reverb.add_child(reverb_preset_caption)
	var reverb_preset_selector := OptionButton.new()
	reverb_preset_selector.focus_mode = Control.FOCUS_NONE
	for preset_name in (["Tunnel", "Garage", "Draußen", "Unterführung"] if simulator.ui_language == 0 else ["Tunnel", "Garage", "Outdoor", "Underpass"]):
		reverb_preset_selector.add_item(preset_name)
	reverb_preset_selector.select(clampi(int(_sound_value("reverb_preset", 0.0)), 0, 3))
	reverb_preset_selector.item_selected.connect(func(index):
		if is_instance_valid(engine) and parent_properties.has("reverb_preset"):
			engine.set("reverb_preset", index)
	)
	environment_reverb.add_child(reverb_preset_selector)
	_number(environment_reverb, "Reverb Stärke (0–1)", 0, 1, 0.01, _sound_value("reverb_amount", 0.0), func(v): engine.set("reverb_amount", v))
	_number(environment_reverb, "Reverb Ein-/Ausblendung", 0.1, 20, 0.1, _sound_value("reverb_fade_speed", 4.0), func(v): engine.set("reverb_fade_speed", v))
	var reverb_hint := Label.new()
	reverb_hint.text = "0 = trocken · 1 = voller Raumklang" if simulator.ui_language == 0 else "0 = dry · 1 = full room sound"
	reverb_hint.add_theme_color_override("font_color", _palette().sound.darkened(0.18))
	environment_reverb.add_child(reverb_hint)
	var cabin_sound := _subgroup(sound_section, "INNENRAUMKLANG · FAHRERPERSPEKTIVE", false, Color("e3a45f"))
	_engine_check(cabin_sound, "Innenraumklang aktiv", &"cabin_enabled")
	var cabin_preset_caption := Label.new()
	cabin_preset_caption.text = _t("Innenraum Preset")
	cabin_sound.add_child(cabin_preset_caption)
	var cabin_preset_selector := OptionButton.new()
	cabin_preset_selector.focus_mode = Control.FOCUS_NONE
	for preset_name in (["Straßenauto · weich / gedämmt", "Rennauto · direkt / mechanisch", "Rennwagen-Cockpit · spitz / blechern"] if simulator.ui_language == 0 else ["Street car · soft / insulated", "Race car · direct / mechanical", "Race cockpit · sharp / metallic"]):
		cabin_preset_selector.add_item(preset_name)
	cabin_preset_selector.select(clampi(int(_sound_value("cabin_preset", 0.0)), 0, 2))
	cabin_preset_selector.item_selected.connect(func(index):
		if is_instance_valid(engine) and parent_properties.has("cabin_preset"):
			engine.set("cabin_preset", index)
	)
	cabin_sound.add_child(cabin_preset_selector)
	_number(cabin_sound, "Innenraum Stärke (0–1)", 0, 1, 0.01, _sound_value("cabin_amount", 0.0), func(v): engine.set("cabin_amount", v))
	_number(cabin_sound, "Innen-/Außen-Übergang", 0.1, 20, 0.1, _sound_value("cabin_fade_speed", 5.0), func(v): engine.set("cabin_fade_speed", v))
	var cabin_hint := Label.new()
	cabin_hint.text = "0 = außen · 1 = vollständig im Fahrzeug" if simulator.ui_language == 0 else "0 = outside · 1 = fully inside the vehicle"
	cabin_hint.add_theme_color_override("font_color", _palette().sound.darkened(0.18))
	cabin_sound.add_child(cabin_hint)
	var engine_state := _subgroup(sound_section, "START / STOP · SOUND", false, Color("e3a45f"))
	_engine_check(engine_state, "Motor läuft", &"engine_running")
	var engine_state_hint := Label.new(); engine_state_hint.text = "EngineState/start.wav + kill.wav"; engine_state_hint.add_theme_color_override("font_color", Color("888888")); engine_state.add_child(engine_state_hint)
	_number(engine_state, "Start Volume", 0, 2, 0.01, _sound_value("engine_start_volume", 1.0), func(v): engine.set("engine_start_volume", v))
	_number(engine_state, "Start Pitch", 0.5, 2, 0.01, _sound_value("engine_start_pitch", 1.0), func(v): engine.set("engine_start_pitch", v))
	_number(engine_state, "Start-Aufheulen RPM (%)", 0, 100, 1, _sound_value("engine_start_rpm_kick") * 100, func(v): engine.set("engine_start_rpm_kick", v / 100.0))
	_number(engine_state, "Kill Volume", 0, 2, 0.01, _sound_value("engine_kill_volume", 1.0), func(v): engine.set("engine_kill_volume", v))
	_number(engine_state, "Kill Pitch", 0.5, 2, 0.01, _sound_value("engine_kill_pitch", 1.0), func(v): engine.set("engine_kill_pitch", v))
	var car_power := _subgroup(vehicle_section, "MOTORCHARAKTER / TUNING", false, Color("64b5d8"))
	smoothness_input = _number(car_power, "Motorglätte / Tuning (%)", 0, 100, 1, simulator.engine_smoothness * 100, func(v): simulator.engine_smoothness = v / 100.0)
	character_input = _number(car_power, "Motorcharakter", 1, 99, 1, simulator.engine_character, func(v): simulator.engine_character = int(v))
	var struggle_settings := _subgroup(car_power, "STRUGGLE · NM-KURVE / DCC", false, Color("9a72d8"))
	var struggle_switch := _check("Motor-Struggle aktiv", simulator.engine_struggle_enabled, func(v): simulator.engine_struggle_enabled = v); struggle_settings.add_child(struggle_switch)
	_number(struggle_settings, "Motor-Struggle Stärke", 0, 1, 0.01, simulator.engine_struggle_strength, func(v): simulator.engine_struggle_strength = v)
	_number(struggle_settings, "Nm-Kurven Empfindlichkeit", 0, 1, 0.01, simulator.engine_struggle_curve_sensitivity, func(v): simulator.engine_struggle_curve_sensitivity = v)
	_number(struggle_settings, "DCC / Schubbetrieb Stärke", 0, 1, 0.01, simulator.coast_curve_struggle_strength, func(v): simulator.coast_curve_struggle_strength = v)
	var traction_control := _subgroup(vehicle_section, "TRAKTIONSKONTROLLE", false, Color("64b5d8"))
	var traction_control_switch := _check("Traktionskontrolle aktiv", simulator.traction_control_enabled, func(v): simulator.traction_control_enabled = v); traction_control.add_child(traction_control_switch)
	_number(traction_control, "TC Eingriff Stärke (%)", 0, 100, 1, simulator.traction_control_strength * 100, func(v): simulator.traction_control_strength = v / 100.0)
	var braking := _subgroup(vehicle_section, "FAHRWIDERSTAND / BREMSEN", false, Color("64b5d8"))
	_number(braking, "Ausrollen ohne Gas", 0, 80, 1, simulator.coast_deceleration, func(v): simulator.coast_deceleration = v)
	_number(braking, "Normale Bremse", 1, 200, 1, simulator.brake_strength, func(v): simulator.brake_strength = v)
	_number(braking, "Handbremse / Entkoppelt", 0, 30, 0.5, simulator.handbrake_deceleration, func(v): simulator.handbrake_deceleration = v)
	_number(braking, "Downshift Radblock-Bremse", 20, 250, 5, simulator.downshift_wheel_lock_strength, func(v): simulator.downshift_wheel_lock_strength = v)
	var driving_rpm := _subgroup(vehicle_section, "ANFAHREN / FREIES HOCHDREHEN", false, Color("64b5d8"))
	_number(driving_rpm, "Anfahr-RPM (0–1)", 0, 1.0, 0.01, simulator.launch_rpm, func(v): simulator.launch_rpm = v)
	_number(driving_rpm, "Freies Hochdrehen Stärke", 0.5, 10, 0.1, simulator.handbrake_rev_speed, func(v): simulator.handbrake_rev_speed = v)
	_number(driving_rpm, "Freies RPM Abfallen", 0.2, 6, 0.1, simulator.free_rev_fall_speed, func(v): simulator.free_rev_fall_speed = v)
	var wobble_settings := _subgroup(sound_section, "GAS- UND SCHALTWOBBLE · NUR PITCH", false, Color("e3a45f"))
	var wobble_switch := _check("Wobble aktiv", simulator.wobble_enabled, func(v): simulator.wobble_enabled = v); wobble_settings.add_child(wobble_switch)
	_number(wobble_settings, "Wobble Stärke", 0, 0.35, 0.001, simulator.wobble_strength, func(v): simulator.wobble_strength = v)
	_number(wobble_settings, "Wobble Dauer (s)", 0.1, 1, 0.01, simulator.wobble_duration, func(v): simulator.wobble_duration = v)
	var difficulty := _subgroup(vehicle_section, "SCHWIERIGKEIT / FAHRHILFEN", false, Color("9b72d0"))
	var difficulty_switch := _check("Schwierigkeit für Start & Schalten", simulator.progressive_shift_difficulty, func(v): simulator.progressive_shift_difficulty = v); difficulty.add_child(difficulty_switch)
	_number(difficulty, "Perfekt-Timing Schwierigkeit", 0, 1, 0.05, simulator.shift_difficulty, func(v): simulator.shift_difficulty = v)
	var fall_difficulty := _number(difficulty, "Start-Abfall Schwierigkeit (0 leicht / 1 schwer)", 0, 1, 0.05, simulator.free_rev_fall_difficulty, func(v): simulator.free_rev_fall_difficulty = v)
	fall_difficulty.tooltip_text = "Wirkt nur beim freien RPM-Abfall innerhalb der blauen und grünen Startzone."
	var difficulty_hint := Label.new(); difficulty_hint.text = "Nur in Blau + Grün: RPM-Abfall = Fahrzeug-Abfallstärke × Abfall-Schwierigkeit\nAußerhalb bleibt der Fahrzeugwert normal. 0 = leicht, 1 = schwer/original."; difficulty_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART; difficulty.add_child(difficulty_hint)
	var launch_control := _subgroup(vehicle_section, "LAUNCH CONTROL", false, Color("64b5d8"))
	var launch_control_switch := _check("Launch Control", simulator.launch_control_enabled, func(v): simulator.launch_control_enabled = v); launch_control.add_child(launch_control_switch)
	_number(launch_control, "Launch RPM", simulator.idle_rpm, simulator.max_rpm, 100, simulator.launch_control_rpm, func(v): simulator.launch_control_rpm = v)
	_number(launch_control, "RPM-Sprung", 0, 1500, 25, simulator.launch_control_rpm_jump, func(v): simulator.launch_control_rpm_jump = v)
	_number(launch_control, "Sprunggeschwindigkeit (Hz)", 1, 20, 0.5, simulator.launch_control_jump_speed, func(v): simulator.launch_control_jump_speed = v)
	var race_launch := _subgroup(vehicle_section, "RENNSTART / PERFECT LAUNCH", false, Color("64b5d8"))
	var race_launch_switch := _check("Perfect-Launch-System", simulator.race_launch_enabled, func(v): simulator.race_launch_enabled = v); race_launch.add_child(race_launch_switch)
	var automatic_launch_hint := Label.new(); automatic_launch_hint.text = "Perfektes RPM-Fenster wird automatisch über die Timing-Schwierigkeit berechnet."; automatic_launch_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART; race_launch.add_child(automatic_launch_hint)
	_number(race_launch, "Wheelspin ausblenden bis (km/h)", 5, 100, 1, simulator.race_launch_wheelspin_end_speed_kmh, func(v): simulator.race_launch_wheelspin_end_speed_kmh = v)
	_number(race_launch, "Start-Effekt Dauer (s)", 0.2, 2, 0.05, simulator.race_launch_bonus_duration, func(v): simulator.race_launch_bonus_duration = v)
	var transmission := _subgroup(vehicle_section, "GETRIEBE", false, Color("64b5d8"))
	var transmission_type_caption := Label.new(); transmission_type_caption.text = "Getriebetyp" if simulator.ui_language == 0 else "Transmission type"; transmission.add_child(transmission_type_caption)
	var transmission_type_selector := OptionButton.new()
	transmission_type_selector.focus_mode = Control.FOCUS_NONE
	for type_name in (["Handschalter", "Automatik", "DSG / Sequenziell"] if simulator.ui_language == 0 else ["Manual", "Automatic", "DSG / Sequential"]):
		transmission_type_selector.add_item(type_name)
	transmission_type_selector.select(clampi(simulator.transmission_type, 0, 2))
	transmission_type_selector.item_selected.connect(func(index): simulator.transmission_type = index)
	transmission.add_child(transmission_type_selector)
	transmission.add_child(automatic_vmax_button)
	max_speed_input = _number(transmission, "Manuelle Vmax (km/h)", 20, 500, 1, simulator.max_speed_kmh, func(v): simulator.max_speed_kmh = v)
	automatic_gears_button = _check("Gangautomatik", simulator.automatic_gears, func(v): simulator.automatic_gears = v); transmission.add_child(automatic_gears_button)
	var perfect_shift_button := _check("Automatisch perfekter Schaltpunkt", simulator.automatic_perfect_shift, func(v): simulator.automatic_perfect_shift = v); transmission.add_child(perfect_shift_button)
	gear_count_input = _number(transmission, "Ganganzahl", 1, 10, 1, simulator.number_of_gears, func(v): simulator.number_of_gears = int(v))
	_number(transmission, "RPM nach Hochschalten (%)", 50, 90, 1, simulator.gear_rpm_drop * 100, func(v): simulator.gear_rpm_drop = v / 100.0)
	_number(transmission, "Manueller Hochschaltpunkt (%)", 50, 99, 1, simulator.upshift_rpm * 100, func(v): simulator.upshift_rpm = v / 100.0)
	_number(transmission, "Manueller Runterschaltpunkt (%)", 10, 80, 1, simulator.downshift_rpm * 100, func(v): simulator.downshift_rpm = v / 100.0)
	_number(transmission, "Schaltzeit (s)", 0.04, 0.5, 0.01, simulator.shift_time, func(v): simulator.shift_time = v)
	_number(transmission, "Downshift-Sperre (s)", 0, 3, 0.05, simulator.downshift_lock_time, func(v): simulator.downshift_lock_time = v)
	_number(transmission, "Traktion wieder aufbauen (s)", 0.05, 1.5, 0.05, simulator.downshift_grip_recovery_time, func(v): simulator.downshift_grip_recovery_time = v)
	var transmission_sound := _audio_subgroup(transmission, false)
	_engine_check(transmission_sound, "Transmission Sound", &"transmission_enabled")
	_sound_selector(transmission_sound, "Whine Sound", &"transmission_index", &"_transmission_files", &"transmission_name")
	_number(transmission_sound, "Max Volume bei Vmax", 0, 2, 0.01, _sound_value("transmission_max_speed_volume"), func(v): engine.set("transmission_max_speed_volume", v))
	_number(transmission_sound, "Whine Grund-Pitch", 0.5, 2, 0.01, _sound_value("transmission_pitch", 1.0), func(v): engine.set("transmission_pitch", v))
	_number(transmission_sound, "Pitch niedrige Geschwindigkeit", 0.1, 2, 0.01, _sound_value("transmission_pitch_low_speed", 0.55), func(v): engine.set("transmission_pitch_low_speed", v))
	_number(transmission_sound, "Pitch hohe Geschwindigkeit", 0.5, 4, 0.01, _sound_value("transmission_pitch_high_speed", 2.0), func(v): engine.set("transmission_pitch_high_speed", v))
	_number(transmission_sound, "Coast Amount (%)", 0, 100, 1, _sound_value("transmission_coast_amount") * 100, func(v): engine.set("transmission_coast_amount", v / 100.0))
	_sound_selector(transmission_sound, "Shift Up Sound", &"shift_up_sound_index", &"_shift_up_sound_files", &"shift_up_sound_name")
	_number(transmission_sound, "Shift Up Volume", 0, 2, 0.01, _sound_value("shift_up_sound_volume", 1.0), func(v): engine.set("shift_up_sound_volume", v))
	_number(transmission_sound, "Shift Up Pitch", 0.5, 2, 0.01, _sound_value("shift_up_sound_pitch", 1.0), func(v): engine.set("shift_up_sound_pitch", v))
	_sound_selector(transmission_sound, "Shift Down Sound", &"shift_down_sound_index", &"_shift_down_sound_files", &"shift_down_sound_name")
	_number(transmission_sound, "Shift Down Volume", 0, 2, 0.01, _sound_value("shift_down_sound_volume", 1.0), func(v): engine.set("shift_down_sound_volume", v))
	_number(transmission_sound, "Shift Down Pitch", 0.5, 2, 0.01, _sound_value("shift_down_sound_pitch", 1.0), func(v): engine.set("shift_down_sound_pitch", v))
	var skid_sound := _subgroup(sound_section, "REIFEN / SKID SOUND", false, Color("e3a45f"))
	_engine_check(skid_sound, "Skid Sound", &"skid_enabled")
	_sound_selector(skid_sound, "Reifen Sound", &"skid_index", &"_skid_files", &"skid_name")
	_number(skid_sound, "Skid Volume", 0, 2, 0.01, _sound_value("skid_volume", 0.8), func(v): engine.set("skid_volume", v))
	_number(skid_sound, "Pitch niedrige Geschwindigkeit", 0.25, 2, 0.01, _sound_value("skid_pitch_low_speed", 0.75), func(v): engine.set("skid_pitch_low_speed", v))
	_number(skid_sound, "Pitch hohe Geschwindigkeit", 0.5, 3, 0.01, _sound_value("skid_pitch_high_speed", 1.45), func(v): engine.set("skid_pitch_high_speed", v))
	var supercharger := _subgroup(extras_section, "SUPERCHARGER · LEISTUNG + SOUND", false, Color("b692e6"))
	var super_sim := _check("Supercharger Leistung", simulator.supercharger_enabled, func(v): simulator.supercharger_enabled = v); supercharger.add_child(super_sim)
	_number(supercharger, "Extra Leistung (PS)", 0, 1000, 1, simulator.supercharger_power_ps, func(v): simulator.supercharger_power_ps = v)
	var supercharger_sound := _audio_subgroup(supercharger, false)
	_sound_selector(supercharger_sound, "Supercharger Sound", &"supercharger_index", &"_supercharger_files", &"supercharger_name")
	_number(supercharger_sound, "Sound Volume", 0, 2, 0.01, _sound_value("supercharger_volume"), func(v): engine.set("supercharger_volume", v))
	_number(supercharger_sound, "Pitch Idle", 0.1, 2, 0.01, _sound_value("supercharger_pitch_idle", 0.55), func(v): engine.set("supercharger_pitch_idle", v))
	_number(supercharger_sound, "Pitch Redline", 0.5, 4, 0.01, _sound_value("supercharger_pitch_redline", 2.2), func(v): engine.set("supercharger_pitch_redline", v))
	_number(supercharger_sound, "Coast Amount (%)", 0, 100, 1, _sound_value("supercharger_coast_amount", 0.25) * 100, func(v): engine.set("supercharger_coast_amount", v / 100.0))
	var turbo := _subgroup(extras_section, "TURBO / BOV · LEISTUNG + SOUND", false, Color("b692e6"))
	var turbo_sim := _check("Turbo Leistung", simulator.turbo_enabled, func(v): simulator.turbo_enabled = v); turbo.add_child(turbo_sim)
	_number(turbo, "Extra Leistung (PS)", 0, 1500, 1, simulator.turbo_power_ps, func(v): simulator.turbo_power_ps = v)
	_number(turbo, "Spool Start RPM (%)", 0, 80, 1, simulator.turbo_spool_start_rpm * 100, func(v): simulator.turbo_spool_start_rpm = v / 100.0)
	_number(turbo, "Druckdifferenz fuer vollen Aufbau", 0.001, 0.2, 0.001, simulator.turbo_full_boost_audio_dist, func(v): simulator.turbo_full_boost_audio_dist = v)
	_number(turbo, "Spool Aufbau", 0.1, 5, 0.05, simulator.turbo_spool_up_speed, func(v): simulator.turbo_spool_up_speed = v)
	_number(turbo, "Spool Abbau", 0.1, 8, 0.05, simulator.turbo_spool_down_speed, func(v): simulator.turbo_spool_down_speed = v)
	var turbo_sound := _audio_subgroup(turbo, false)
	_sound_selector(turbo_sound, "Turbo Spool Sound", &"turbo_index", &"_turbo_files", &"turbo_name")
	_number(turbo_sound, "Turbo Volume", 0, 2, 0.01, _sound_value("turbo_volume"), func(v): engine.set("turbo_volume", v))
	_number(turbo_sound, "Turbo Pitch", 0.5, 3, 0.01, _sound_value("turbo_pitch", 1.0), func(v): engine.set("turbo_pitch", v))
	_sound_selector(turbo_sound, "BOV Sound", &"bov_index", &"_bov_files", &"bov_name")
	_number(turbo_sound, "BOV Volume", 0, 2, 0.01, _sound_value("bov_volume"), func(v): engine.set("bov_volume", v))
	var backfire := _subgroup(sound_section, "BACKFIRE SOUND", false, Color("e3a45f"))
	_engine_check(backfire, "Backfire", &"backfire_enabled")
	_engine_check(backfire, "Zufällige Variationen", &"backfire_random_variations")
	_sound_selector(backfire, "Backfire Sound", &"backfire_index", &"_backfire_files", &"backfire_name")
	_number(backfire, "Backfire Volume", 0, 2, 0.01, _sound_value("backfire_volume"), func(v): engine.set("backfire_volume", v))
	_number(backfire, "Backfire Stärke (%)", 0, 100, 1, _sound_value("backfire_strength") * 100, func(v): engine.set("backfire_strength", v / 100.0))
	_number(backfire, "Backfire Pitch", 0.5, 2, 0.01, _sound_value("backfire_pitch", 1.0), func(v): engine.set("backfire_pitch", v))
	_engine_check(backfire, "RPM-Kick bei Backfire", &"backfire_rpm_kick_enabled")
	_number(backfire, "RPM-Kick Stärke (%)", 0, 20, 0.5, _sound_value("backfire_rpm_kick_amount") * 100, func(v): engine.set("backfire_rpm_kick_amount", v / 100.0))
	_number(backfire, "Backfire ab Audio-RPM", 0, simulator.max_rpm, 100, _sound_value("backfire_min_audio_rpm") * simulator.max_rpm, func(v): engine.set("backfire_min_audio_rpm", v / maxf(simulator.max_rpm, 1.0)))
	_number(backfire, "Backfire bis Audio-RPM", 0, simulator.max_rpm, 100, _sound_value("backfire_max_audio_rpm") * simulator.max_rpm, func(v): engine.set("backfire_max_audio_rpm", v / maxf(simulator.max_rpm, 1.0)))
	_number(backfire, "Mindestlast (%)", 0, 100, 1, _sound_value("backfire_min_load", 0.35) * 100, func(v): engine.set("backfire_min_load", v / 100.0))
	_number(backfire, "Cooldown (s)", 0.02, 1, 0.01, _sound_value("backfire_cooldown", 0.16), func(v): engine.set("backfire_cooldown", v))
	_number(backfire, "Max Salvendauer (s)", 0.1, 5, 0.1, _sound_value("backfire_burst_duration", 1.5), func(v): engine.set("backfire_burst_duration", v))
	_number(backfire, "Volllast Aufbauzeit (s)", 0.2, 5, 0.1, _sound_value("backfire_full_load_build_time", 2.0), func(v): engine.set("backfire_full_load_build_time", v))
	_number(backfire, "Bang Abstand (s)", 0.05, 0.6, 0.01, _sound_value("backfire_bang_interval", 0.18), func(v): engine.set("backfire_bang_interval", v))
	_number(backfire, "Klang Pitch-Kick", 0, 0.08, 0.001, _sound_value("backfire_pitch_kick", 0.018), func(v): engine.set("backfire_pitch_kick", v))
	var dyno_settings := _subgroup(display_section, "ANZEIGE / DYNO-SKALA · NUR UI", false, Color("92989d"))
	var style_caption := Label.new(); style_caption.text = "Interface Style"; dyno_settings.add_child(style_caption)
	style_selector = OptionButton.new()
	style_selector.focus_mode = Control.FOCUS_NONE
	for style_name in ["Dark", "NFS ProStreet", "NFS Most Wanted 2005", "Street Racing Red", "Retro Dyno"]:
		style_selector.add_item(style_name)
	style_selector.select(clampi(simulator.ui_style, 0, 4))
	style_selector.item_selected.connect(func(index): simulator.ui_style = index; apply_ui_style())
	dyno_settings.add_child(style_selector)
	var language_caption := Label.new(); language_caption.text = "Sprache" if simulator.ui_language == 0 else "Language"; dyno_settings.add_child(language_caption)
	language_selector = OptionButton.new()
	language_selector.focus_mode = Control.FOCUS_NONE
	language_selector.add_item("Deutsch")
	language_selector.add_item("English")
	language_selector.select(clampi(simulator.ui_language, 0, 1))
	language_selector.item_selected.connect(func(index): simulator.ui_language = index)
	dyno_settings.add_child(language_selector)
	automatic_dyno_scale_button = _check("Dyno-Skala automatisch", simulator.automatic_dyno_scale, func(v): simulator.automatic_dyno_scale = v; sync_controls())
	dyno_settings.add_child(automatic_dyno_scale_button)
	_number(dyno_settings, "Dyno Luft nach oben (%)", 0, 50, 1, simulator.dyno_scale_headroom * 100.0, func(v): simulator.dyno_scale_headroom = v / 100.0)
	dyno_rpm_input = _number(dyno_settings, "Anzeige Max RPM", 2000, 30000, 500, simulator.dyno_max_rpm, func(v): simulator.dyno_max_rpm = v)
	dyno_power_input = _number(dyno_settings, "Anzeige Max PS", 100, 5000, 50, simulator.dyno_max_power_ps, func(v): simulator.dyno_max_power_ps = v)
	dyno_torque_input = _number(dyno_settings, "Anzeige Max Nm", 100, 5000, 50, simulator.dyno_max_torque_nm, func(v): simulator.dyno_max_torque_nm = v)
	var simulator_display := _subgroup(display_section, "SIMULATOR / DYNO / DEBUG", false, Color("92989d"))
	simulator_display.add_child(enable_button)
	simulator_display.add_child(graph_button)
	simulator_display.add_child(debug_values_button)
	settings.add_child(HSeparator.new())
	manual_rpm_label = Label.new(); settings.add_child(manual_rpm_label)
	manual_rpm_slider = HSlider.new(); manual_rpm_slider.max_value = 1; manual_rpm_slider.step = 0.001; manual_rpm_slider.custom_minimum_size = Vector2(0, 24); manual_rpm_slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL; manual_rpm_slider.focus_mode = Control.FOCUS_NONE
	manual_rpm_slider.value_changed.connect(_set_manual_rpm); settings.add_child(manual_rpm_slider)
	var buttons := HBoxContainer.new(); settings.add_child(buttons)
	for caption in ["Gang -", "Gang +", "Reset"]:
		var button := Button.new(); button.text = _t(caption); button.focus_mode = Control.FOCUS_NONE; buttons.add_child(button)
		if caption == "Gang -": button.pressed.connect(simulator.shift_down)
		elif caption == "Gang +": button.pressed.connect(simulator.shift_up)
		else: button.pressed.connect(simulator.reset_simulation)
	var controls_help := _subgroup(settings, "STEUERUNGSHILFE", false)
	var controls_label := Label.new()
	controls_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	controls_label.add_theme_color_override("font_color", Color("bcbcbc"))
	controls_label.text = "\n".join([
		_input_help_line("Gas", &"gastrigger"),
		_input_help_line("Bremse", &"braketrigger"),
		_input_help_line("Handbremse", &"handbraketrigger"),
		_input_help_line("Gang hoch", &"shiftuptrigger"),
		_input_help_line("Gang runter", &"shiftdowntrigger"),
	])
	controls_help.add_child(controls_label)
	debug_panel = PanelContainer.new(); debug_panel.custom_minimum_size = Vector2(620, 760); debug_panel.size_flags_vertical = Control.SIZE_SHRINK_BEGIN; debug_panel.add_theme_stylebox_override("panel", _style()); debug_panel.gui_input.connect(_clear_focus_on_click); ui_root.add_child(debug_panel)
	debug_scroll = ScrollContainer.new(); debug_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL; debug_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL; debug_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_SHOW_NEVER; debug_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_SHOW_NEVER; debug_panel.add_child(debug_scroll)
	debug_column = VBoxContainer.new(); debug_column.custom_minimum_size = Vector2(584, 0); debug_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL; debug_column.size_flags_vertical = Control.SIZE_EXPAND_FILL; debug_column.add_theme_constant_override("separation", 8); debug_scroll.add_child(debug_column)
	debug_label = Label.new(); debug_label.custom_minimum_size = Vector2(584, 190); debug_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL; debug_label.size_flags_vertical = Control.SIZE_SHRINK_END; debug_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART; debug_label.add_theme_font_size_override("font_size", 16); debug_label.mouse_filter = Control.MOUSE_FILTER_IGNORE; debug_column.add_child(debug_label)
	power_graph_row = GridContainer.new(); power_graph_row.columns = 1; power_graph_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL; power_graph_row.size_flags_vertical = Control.SIZE_EXPAND_FILL; power_graph_row.visible = simulator.power_graph_enabled; debug_column.add_child(power_graph_row)
	dyno_graph = Control.new(); dyno_graph.custom_minimum_size = Vector2(584, 440); dyno_graph.size_flags_horizontal = Control.SIZE_EXPAND_FILL; dyno_graph.size_flags_vertical = Control.SIZE_EXPAND_FILL; dyno_graph.mouse_filter = Control.MOUSE_FILTER_IGNORE; dyno_graph.draw.connect(_draw_dyno); power_graph_row.add_child(dyno_graph)
	acceleration_display = Control.new(); acceleration_display.custom_minimum_size = Vector2(584, 58); acceleration_display.size_flags_horizontal = Control.SIZE_EXPAND_FILL; acceleration_display.mouse_filter = Control.MOUSE_FILTER_IGNORE; acceleration_display.draw.connect(_draw_acceleration_display); power_graph_row.add_child(acceleration_display)
	# Dyno oben; der Startknopf wird separat als feste Panel-Ebene gebaut.
	debug_column.move_child(power_graph_row, 0)
	# Eigene Overlay-Ebene: bleibt fest unten rechts im Panel und wird niemals
	# vom Dyno-/Debug-Inhalt oder dessen deaktiviertem Scrollbereich abgeschnitten.
	var ignition_overlay := MarginContainer.new()
	ignition_overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ignition_overlay.add_theme_constant_override("margin_right", 18)
	ignition_overlay.add_theme_constant_override("margin_bottom", 18)
	debug_panel.add_child(ignition_overlay)
	var ignition_column := VBoxContainer.new(); ignition_column.mouse_filter = Control.MOUSE_FILTER_IGNORE; ignition_overlay.add_child(ignition_column)
	var vertical_spacer := Control.new(); vertical_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL; vertical_spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE; ignition_column.add_child(vertical_spacer)
	var engine_button_row := HBoxContainer.new(); engine_button_row.mouse_filter = Control.MOUSE_FILTER_IGNORE; ignition_column.add_child(engine_button_row)
	var button_spacer := Control.new(); button_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL; button_spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE; engine_button_row.add_child(button_spacer)
	engine_start_stop_button = Button.new()
	engine_start_stop_button.custom_minimum_size = Vector2(100, 100)
	engine_start_stop_button.focus_mode = Control.FOCUS_NONE
	engine_start_stop_button.flat = true
	engine_start_stop_button.pressed.connect(_toggle_engine_running)
	engine_start_stop_button.draw.connect(_draw_engine_start_button)
	engine_start_stop_button.mouse_entered.connect(engine_start_stop_button.queue_redraw)
	engine_start_stop_button.mouse_exited.connect(engine_start_stop_button.queue_redraw)
	engine_start_stop_button.button_down.connect(engine_start_stop_button.queue_redraw)
	engine_start_stop_button.button_up.connect(engine_start_stop_button.queue_redraw)
	engine_button_row.add_child(engine_start_stop_button)
	_update_engine_start_button(true)
	_constrain_settings_width(settings_scroll)
	apply_ui_style()

#endregion

#region Bedienung und Live-Synchronisierung
func _save_current_preset() -> void:
	var result: Dictionary = simulator.save_vehicle_preset(preset_name_input.text)
	if not result.ok:
		preset_save_status.text = ("Bitte einen Namen eingeben." if simulator.ui_language == 0 else "Please enter a name.") if result.error == "name" else (("Speichern fehlgeschlagen: " if simulator.ui_language == 0 else "Save failed: ") + str(result.error))
		return
	preset_name_input.release_focus()
	vehicle_preset_selector.clear()
	for preset in simulator.vehicle_presets:
		vehicle_preset_selector.add_item("%s · %s" % [preset.category, preset.name])
	vehicle_preset_selector.select(simulator.selected_vehicle_preset)
	preset_save_status.text = "Gespeichert unter Eigene Presets." if simulator.ui_language == 0 else "Saved under Eigene Presets (custom presets)."
	preset_save_status.tooltip_text = ProjectSettings.globalize_path(result.path)

func _sound_value(property: StringName, fallback: float = 0.0) -> float:
	return float(engine.get(property)) if is_instance_valid(engine) and parent_properties.has(property) else fallback

func _folders() -> PackedStringArray:
	return PackedStringArray(engine.get("_car_folders")) if is_instance_valid(engine) and parent_properties.has("_car_folders") else PackedStringArray()

func _change_car(direction: int) -> void:
	var folders := _folders()
	if folders.size() > 1:
		engine.set("car_index", posmod(int(_sound_value("car_index")) + direction, folders.size()))
		refresh()

func _set_manual_rpm(value: float) -> void:
	if not simulator.simulator_enabled and is_instance_valid(engine) and parent_properties.has("rpm_position"):
		engine.set("rpm_position", clampf(value, 0, 1)); refresh()

func _toggle_engine_running() -> void:
	if not is_instance_valid(engine) or not parent_properties.has("engine_running"):
		return
	engine.set("engine_running", not bool(engine.get("engine_running")))
	_update_engine_start_button(true)

func _update_engine_start_button(force: bool = false) -> void:
	if not is_instance_valid(engine_start_stop_button):
		return
	var available := is_instance_valid(engine) and parent_properties.has("engine_running")
	var running := bool(engine.get("engine_running")) if available else false
	var state := 1 if running else 0
	if not force and state == _last_engine_button_running:
		return
	_last_engine_button_running = state
	engine_start_stop_button.disabled = not available
	engine_start_stop_button.text = ""
	engine_start_stop_button.queue_redraw()

func sync_controls() -> void:
	if not is_instance_valid(horsepower_input): return
	horsepower_input.set_value_no_signal(simulator.horsepower); mass_input.set_value_no_signal(simulator.vehicle_mass_kg); max_rpm_input.set_value_no_signal(simulator.max_rpm); idle_rpm_input.set_value_no_signal(simulator.idle_rpm)
	max_speed_input.set_value_no_signal(simulator.max_speed_kmh); max_speed_input.editable = not simulator.automatic_max_speed; max_speed_input.modulate.a = 0.45 if simulator.automatic_max_speed else 1.0
	gear_count_input.set_value_no_signal(simulator.number_of_gears); smoothness_input.set_value_no_signal(simulator.engine_smoothness * 100); character_input.set_value_no_signal(simulator.engine_character)
	enable_button.set_pressed_no_signal(simulator.simulator_enabled); graph_button.set_pressed_no_signal(simulator.power_graph_enabled); debug_values_button.set_pressed_no_signal(simulator.debug_values_enabled); automatic_vmax_button.set_pressed_no_signal(simulator.automatic_max_speed); automatic_gears_button.set_pressed_no_signal(simulator.automatic_gears)
	if is_instance_valid(automatic_dyno_scale_button): automatic_dyno_scale_button.set_pressed_no_signal(simulator.automatic_dyno_scale)
	for dyno_input in [dyno_rpm_input, dyno_power_input, dyno_torque_input]:
		if is_instance_valid(dyno_input):
			dyno_input.editable = not simulator.automatic_dyno_scale
			dyno_input.modulate.a = 0.45 if simulator.automatic_dyno_scale else 1.0
	if is_instance_valid(vehicle_preset_selector) and vehicle_preset_selector.item_count > 0: vehicle_preset_selector.select(clampi(simulator.selected_vehicle_preset, 0, vehicle_preset_selector.item_count - 1))
	power_graph_row.visible = simulator.power_graph_enabled
	# Platz bleibt statisch reserviert; nur die Schrift wird ein-/ausgeblendet.
	debug_label.visible = true
	debug_label.modulate.a = 1.0 if simulator.debug_values_enabled else 0.0
	manual_rpm_slider.editable = not simulator.simulator_enabled and parent_properties.has("rpm_position")
	var target := _sound_value("rpm_position", simulator.rpm_normalized); manual_rpm_slider.set_value_no_signal(target); manual_rpm_label.text = ("Manuelle RPM: %.3f%s" if simulator.ui_language == 0 else "Manual RPM: %.3f%s") % [target, ("  (Simulator ausschalten)" if simulator.ui_language == 0 else "  (disable simulator)") if simulator.simulator_enabled else ""]
	var folders := _folders(); previous_car_button.disabled = folders.size() < 2; next_car_button.disabled = folders.size() < 2
	car_name_label.text = _t("Keine Soundbank") if folders.is_empty() else folders[clampi(int(_sound_value("car_index")), 0, folders.size() - 1)].get_file()
	_update_engine_start_button()
	for index_property in sound_name_labels:
		var data: Dictionary = sound_name_labels[index_property]
		var files: Array = engine.get(data.files) if is_instance_valid(engine) and parent_properties.has(data.files) else []
		var display_name := str(engine.get(data.name)) if is_instance_valid(engine) and parent_properties.has(data.name) else "Keine"
		data.label.text = display_name
		data.previous.disabled = files.size() < 2
		data.next.disabled = files.size() < 2

func refresh() -> void:
	if not is_instance_valid(debug_label): return
	sync_controls()
	if is_instance_valid(fps_label):
		fps_label.text = "FPS: %d" % int(round(Engine.get_frames_per_second()))
	if simulator.power_graph_enabled:
		dyno_graph.queue_redraw()
		acceleration_display.queue_redraw()
	var mode := "Perfect Launch: %s" % simulator.race_launch_status if simulator.race_launch_staging or simulator.race_launch_effect_active else ("Radblock / Motorbremse" if simulator.downshift_wheel_lock else ("Launch Control" if simulator.launch_control_active else ("Schalten" if simulator.is_shifting else ("Freies Hochdrehen" if simulator.handbrake > 0.02 else "Fahren"))))
	debug_label.text = "Bungee Motor-Prüfstand | %s\n%s | %s\nTempo: %.1f / %.0f km/h%s   Gang: %d/%d\nMotor: %.0f PS   Gesamt: %.0f PS   Masse: %.0f kg   Max: %.0f RPM\nLeistung (Physik): %.0f PS   Drehmoment: %.0f Nm   Aero: %.2f\nSC: %.0f %%   Turbo: %.0f %%   Traktion: %.0f %%   Wheelspin: %.0f %%\n0–100: %s   100–200: %s\nRPM Ziel: %.3f   Audio: %.3f   Visual: %.3f\nDist: %+.4f (%+.3f s)\nGas: %.2f  Bremse: %.2f  Handbremse: %.2f\nDCC: %.2f  Idle: %.2f  Limit: %.2f\nWobble: %+.2f %%" % ["AN" if simulator.simulator_enabled else "AUS", mode, "Automatik" if simulator.automatic_gears else "Manuell", simulator.speed_kmh, simulator._get_max_speed_kmh(), " (Auto)" if simulator.automatic_max_speed else "", simulator.current_gear, simulator.number_of_gears, simulator.horsepower, simulator._get_effective_horsepower(), simulator.vehicle_mass_kg, simulator.max_rpm, simulator.calculate_power_ps(simulator._get_dyno_visual_rpm()), simulator.calculate_torque_nm(simulator._get_dyno_visual_rpm()), simulator.calculate_air_resistance(), simulator.supercharger_boost * 100, simulator.turbo_boost * 100, simulator.traction * 100, simulator.wheelspin * 100, simulator._format_acceleration_time(simulator.acceleration_time_0_100, 100), simulator._format_acceleration_time(simulator.acceleration_time_100_200, 200), _sound_value("rpm_position", simulator.rpm_normalized), simulator._get_audio_rpm(), simulator.visual_rpm, _sound_value("rpm_follow_distance_normalized"), _sound_value("rpm_follow_distance_seconds"), simulator.throttle, simulator.brake, simulator.handbrake, _sound_value("_dcc_mix"), _sound_value("_idle_mix"), _sound_value("_limiter_mix"), simulator.wobble * 100]
	debug_label.text += ("\nRPM Physik: %.0f | Audio: %.0f" if simulator.ui_language == 0 else "\nPhysics RPM: %.0f | Audio: %.0f") % [simulator.calculate_actual_rpm(simulator.physics_rpm), simulator.calculate_actual_rpm(simulator._get_audio_rpm())]
	if simulator.ui_language == 1:
		var debug_replacements := [["Motor-Prüfstand", "Engine Dyno"], ["Radblock / Motorbremse", "Wheel lock / engine braking"], ["Schalten", "Shifting"], ["Freies Hochdrehen", "Free rev"], ["Fahren", "Driving"], ["PERFEKT", "PERFECT"], ["DURCHDREHEN", "WHEELSPIN"], ["BEREIT", "READY"], ["GUT", "GOOD"], ["Tempo", "Speed"], ["Gang", "Gear"], ["Motor", "Engine"], ["Gesamt", "Total"], ["Masse", "Mass"], ["Leistung", "Power"], ["Drehmoment", "Torque"], ["Traktion", "Traction"], ["Ziel", "Target"], ["Gas", "Throttle"], ["Bremse", "Brake"], ["Handbremse", "Handbrake"], ["Automatik", "Automatic"], ["Manuell", "Manual"], ["läuft ...", "running ..."], ["AN", "ON"], ["AUS", "OFF"]]
		for pair in debug_replacements:
			debug_label.text = debug_label.text.replace(pair[0], pair[1])

#endregion

#region Layout und Fokus
func _constrain_settings_width(node: Node) -> void:
	# Lange Presetnamen/Untergruppen duerfen nicht den gesamten Scroll-Inhalt
	# breiter ziehen als das Panel. Nur Text kuerzen, nicht Schalter/Pfeile.
	if node is OptionButton:
		node.fit_to_longest_item = false
		node.clip_text = true
		node.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	elif node is Button and (node is CheckButton or node.text.length() > 3):
		node.clip_text = true
		node.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		node.tooltip_text = node.text
	elif node is Label and not node.clip_text and node.text.length() > 25:
		node.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	for child in node.get_children():
		_constrain_settings_width(child)

func fit_to_screen(viewport_override: Vector2 = Vector2.ZERO, allow_scale_up: bool = true) -> void:
	var view := viewport_override if viewport_override.x > 0 else get_viewport().get_visible_rect().size
	var available := Vector2(maxf(view.x - 32, 240), maxf(view.y - 32, 180))
	ui_root.columns = 2 if available.x >= 1070 else 1
	var fixed_height := 760.0
	var scale_value := minf(1.0, available.y / fixed_height)
	if ui_root.columns == 2:
		# Breite nach der Höhenskalierung zurückrechnen, damit das sichtbare Panel
		# trotzdem bis fast an den rechten Fensterrand reicht.
		var unscaled_width := available.x / maxf(scale_value, 0.1)
		var right_width := maxf(620.0, unscaled_width - 450.0)
		settings_panel.custom_minimum_size = Vector2(440, fixed_height)
		debug_panel.custom_minimum_size = Vector2(right_width, fixed_height)
		debug_column.custom_minimum_size.x = right_width - 36.0
		debug_label.custom_minimum_size.x = right_width - 36.0
		dyno_graph.custom_minimum_size.x = right_width - 36.0
		acceleration_display.custom_minimum_size.x = right_width - 36.0
	else:
		settings_panel.custom_minimum_size.x = 620.0
		debug_panel.custom_minimum_size.x = 620.0
	ui_root.size = ui_root.get_combined_minimum_size()
	ui_root.scale = Vector2.ONE * maxf(scale_value, 0.1)

func _clear_focus_on_click(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed: get_viewport().gui_release_focus()

func release_focus_from_world_click(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed: get_viewport().gui_release_focus()

#endregion

#region Dyno - Kurven, Messwerte und Schaltanzeigen
func _draw_dyno() -> void:
	var graph := dyno_graph
	var size := graph.size
	var colors := _palette()
	graph.draw_rect(Rect2(Vector2.ZERO, size), colors.panel_deep, true)
	graph.draw_rect(Rect2(Vector2(0.5, 0.5), size - Vector2.ONE), colors.border, false, 1.0)
	var left := 34.0
	var right := 34.0
	var top := 50.0
	# Unter der RPM-Achse bleibt ein fester Bereich für die Rennstart-Zonen.
	var bottom := 52.0
	var area := Vector2(size.x - left - right, size.y - top - bottom)
	var dyno_scales: Vector3 = simulator.get_dyno_display_scales()
	var rpm_max := maxf(dyno_scales.x, 1.0)
	var ps_max := maxf(dyno_scales.y, 1.0)
	var nm_max := maxf(dyno_scales.z, 1.0)
	var font := ThemeDB.fallback_font
	# Raster und beide farbigen Y-Skalen.
	for division in range(6):
		var fraction := float(division) / 5.0
		var y := top + area.y * fraction
		graph.draw_line(Vector2(left, y), Vector2(left + area.x, y), colors.grid, 1.0)
		graph.draw_string(font, Vector2(1.0, y + 3.0), "%.0f" % (ps_max * (1.0 - fraction)), HORIZONTAL_ALIGNMENT_RIGHT, 29.0, 8, colors.power)
		graph.draw_string(font, Vector2(size.x - 31.0, y + 3.0), "%.0f" % (nm_max * (1.0 - fraction)), HORIZONTAL_ALIGNMENT_LEFT, 30.0, 8, colors.torque)
	# Feste RPM-Achse mit sechs Abschnitten.
	for division in range(7):
		var fraction := float(division) / 6.0
		var x := left + area.x * fraction
		graph.draw_line(Vector2(x, top), Vector2(x, top + area.y), colors.grid_minor, 1.0)
		graph.draw_string(font, Vector2(x - 18.0, top + area.y + 13.0), "%.0fk" % (rpm_max * fraction / 1000.0), HORIZONTAL_ALIGNMENT_CENTER, 36.0, 9, Color("aaaaaa"))
	# Die eingefasste RPM-Leiste beginnt als Rennstart-Hilfe und wird nach dem
	# Anfahren automatisch zur Schalthilfe für den jeweils nächsten Gang.
	var launch_guide: bool = bool(simulator.race_launch_staging) or (simulator.speed_kmh < 5.0 and simulator.current_gear == 1)
	var last_gear_guide: bool = not launch_guide and simulator.current_gear >= simulator.number_of_gears
	var guide_caption := "START"
	var good_from_rpm: float
	var perfect_from_rpm: float
	var perfect_to_rpm: float
	if launch_guide:
		var launch_window: Vector2 = simulator._get_effective_race_launch_window()
		var launch_tolerance := maxf((simulator.max_rpm - simulator.idle_rpm) * 0.10, 250.0)
		good_from_rpm = maxf(float(simulator.idle_rpm), launch_window.x - launch_tolerance)
		perfect_from_rpm = clampf(launch_window.x, 0.0, rpm_max)
		perfect_to_rpm = clampf(launch_window.y, perfect_from_rpm, rpm_max)
	else:
		guide_caption = "GANG %d > %d" % [simulator.current_gear, mini(simulator.current_gear + 1, simulator.number_of_gears)]
		# Der perfekte Schaltpunkt ist die obere Kante des grünen Fensters. Damit
		# bleibt rechts immer ein klar sichtbarer roter Zu-spät-Bereich erhalten.
		var shift_center := float(simulator.get_effective_upshift_rpm())
		var perfect_window := float(simulator.get_perfect_shift_window_width())
		var good_window := maxf(0.14, perfect_window + 0.06)
		good_from_rpm = float(simulator.calculate_actual_rpm(clampf(shift_center - good_window, 0.0, 1.0)))
		perfect_from_rpm = float(simulator.calculate_actual_rpm(clampf(shift_center - perfect_window, 0.0, 1.0)))
		perfect_to_rpm = float(simulator.calculate_actual_rpm(shift_center))
		good_from_rpm = clampf(good_from_rpm, 0.0, rpm_max)
		perfect_from_rpm = clampf(perfect_from_rpm, good_from_rpm, rpm_max)
		perfect_to_rpm = clampf(perfect_to_rpm, perfect_from_rpm, rpm_max)
	var bar := Rect2(left, size.y - 22.0, area.x, 16.0)
	graph.draw_rect(bar, Color("090b0e"), true)
	if last_gear_guide:
		graph.draw_rect(bar, Color("ffd447").darkened(0.68), true)
		graph.draw_line(Vector2(bar.position.x, bar.position.y + 1.0), Vector2(bar.end.x, bar.position.y + 1.0), Color("ffd447"), 3.0)
		graph.draw_string(font, Vector2(bar.position.x + 2.0, bar.position.y + 12.0), "LETZTER GANG", HORIZONTAL_ALIGNMENT_CENTER, bar.size.x - 4.0, 8, Color("fff1a6"))
	else:
		var zone_starts := [good_from_rpm, perfect_from_rpm, perfect_to_rpm]
		var zone_ends := [perfect_from_rpm, perfect_to_rpm, minf(float(simulator.max_rpm), rpm_max)]
		var zone_colors := [Color("3f9cff"), Color("42df72"), Color("ef4b4b")]
		var zone_names := ["GUT", "PERFEKT", "SPIN" if launch_guide else "ZU SPÄT"]
		for zone_index in range(3):
			var zone_x := left + area.x * clampf(float(zone_starts[zone_index]) / rpm_max, 0.0, 1.0)
			var zone_end_x := left + area.x * clampf(float(zone_ends[zone_index]) / rpm_max, 0.0, 1.0)
			var zone_width := maxf(zone_end_x - zone_x, 1.0)
			var zone_rect := Rect2(zone_x, bar.position.y, zone_width, bar.size.y)
			graph.draw_rect(zone_rect, zone_colors[zone_index].darkened(0.58), true)
			graph.draw_line(Vector2(zone_x, bar.position.y + 1.0), Vector2(zone_end_x, bar.position.y + 1.0), zone_colors[zone_index], 3.0)
			if zone_width >= 38.0:
				graph.draw_string(font, Vector2(zone_x + 2.0, bar.position.y + 12.0), zone_names[zone_index], HORIZONTAL_ALIGNMENT_CENTER, zone_width - 4.0, 8, Color("eeeeee"))
		# Die beiden entscheidenden Grenzen als echte RPM-Zahlen über der Box.
		var from_x := left + area.x * perfect_from_rpm / rpm_max
		var to_x := left + area.x * perfect_to_rpm / rpm_max
		graph.draw_line(Vector2(from_x, bar.position.y - 2.0), Vector2(from_x, bar.end.y), Color("42df72"), 1.0)
		graph.draw_line(Vector2(to_x, bar.position.y - 2.0), Vector2(to_x, bar.end.y), Color("ef4b4b"), 1.0)
		graph.draw_string(font, Vector2(from_x - 28.0, bar.position.y - 3.0), "%.0f" % perfect_from_rpm, HORIZONTAL_ALIGNMENT_CENTER, 56.0, 8, Color("42df72"))
		graph.draw_string(font, Vector2(to_x - 28.0, bar.position.y - 3.0), "%.0f" % perfect_to_rpm, HORIZONTAL_ALIGNMENT_CENTER, 56.0, 8, Color("ef4b4b"))
	# Modusbezeichnung sitzt im noch dunklen linken Teil und bleibt immer sichtbar.
	if not last_gear_guide:
		graph.draw_string(font, Vector2(bar.position.x + 4.0, bar.position.y + 12.0), guide_caption, HORIZONTAL_ALIGNMENT_LEFT, maxf(good_from_rpm / rpm_max * area.x - 8.0, 70.0), 8, Color("d8d8d8"))
	graph.draw_rect(bar, colors.border, false, 1.0)
	var ps_points := PackedVector2Array()
	var nm_points := PackedVector2Array()
	var visible_rpm := minf(float(simulator.max_rpm), rpm_max)
	# Beide Kurven besitzen einen festen Ursprung bei 0 RPM / 0 Ausgabe.
	# Änderungen an PS oder Drehmoment wachsen dadurch aus demselben Startpunkt,
	# statt die komplette linke Kurvenkante mit nach oben zu verschieben.
	ps_points.append(Vector2(left, top + area.y))
	nm_points.append(Vector2(left, top + area.y))
	# Drehmoment liegt am Idle bereits deutlich an. Zusätzliche Punkte formen den
	# grafischen Anstieg dorthin weich, statt eine harte Diagonale zu zeichnen.
	var idle_graph_rpm := minf(float(simulator.idle_rpm), visible_rpm)
	var idle_torque := float(simulator.calculate_torque_nm(0.0))
	for start_index in range(1, 13):
		var start_fraction := float(start_index) / 12.0
		var start_rpm := idle_graph_rpm * start_fraction
		var smooth_start := smoothstep(0.0, 1.0, start_fraction)
		var start_x := left + area.x * start_rpm / rpm_max
		var start_y := top + area.y * (1.0 - clampf(idle_torque * smooth_start / nm_max, 0.0, 1.0))
		nm_points.append(Vector2(start_x, start_y))
	for index in range(97):
		var shown_rpm := lerpf(minf(float(simulator.idle_rpm), visible_rpm), visible_rpm, float(index) / 96.0)
		var normalized := float(simulator.normalized_from_actual_rpm(shown_rpm))
		var x := left + area.x * shown_rpm / rpm_max
		ps_points.append(Vector2(x, top + area.y * (1.0 - clampf(float(simulator.calculate_power_ps(normalized)) / ps_max, 0.0, 1.0))))
		nm_points.append(Vector2(x, top + area.y * (1.0 - clampf(float(simulator.calculate_torque_nm(normalized)) / nm_max, 0.0, 1.0))))
	graph.draw_polyline(ps_points, colors.power, 2.0, true)
	graph.draw_polyline(nm_points, colors.torque, 2.0, true)
	var current := float(simulator._get_dyno_visual_rpm())
	var actual_current_rpm := float(simulator.calculate_actual_rpm(current))
	# Zwei reine Anzeigezeiger: echte Motor-RPM und nachlaufender Audiocursor.
	var physics_marker_rpm := float(simulator.calculate_actual_rpm(simulator.physics_rpm))
	var physics_marker_x := left + area.x * clampf(physics_marker_rpm / rpm_max, 0.0, 1.0)
	var marker_rpm := clampf(float(simulator._get_audio_rpm()), 0.0, 1.0)
	var actual_marker_rpm := float(simulator.calculate_actual_rpm(marker_rpm))
	var marker_x := left + area.x * clampf(actual_marker_rpm / rpm_max, 0.0, 1.0)
	# Die Physik-Linie zeigt die echte Start-/Schaltzone; Audio bleibt gestrichelt.
	var marker_color := Color("888888")
	if last_gear_guide:
		marker_color = Color("ffd447")
	elif physics_marker_rpm >= perfect_to_rpm:
		marker_color = Color("ef4b4b")
	elif physics_marker_rpm >= perfect_from_rpm:
		marker_color = Color("42df72")
	elif physics_marker_rpm >= good_from_rpm:
		marker_color = Color("3f9cff")
	graph.draw_line(Vector2(physics_marker_x, top), Vector2(physics_marker_x, top + area.y), marker_color, 3.0)
	# Schmalere Striche bleiben auch bei deckungsgleichen Zeigern unterscheidbar.
	graph.draw_dashed_line(Vector2(marker_x, top), Vector2(marker_x, top + area.y), colors.text, 1.5, 5.0)
	graph.draw_circle(Vector2(marker_x, top + area.y * (1.0 - clampf(float(simulator.calculate_power_ps(marker_rpm)) / ps_max, 0.0, 1.0))), 3.5, colors.power)
	graph.draw_circle(Vector2(marker_x, top + area.y * (1.0 - clampf(float(simulator.calculate_torque_nm(marker_rpm)) / nm_max, 0.0, 1.0))), 3.5, colors.torque)
	graph.draw_string(font, Vector2(8.0, 16.0), "DYNO", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, colors.text)
	graph.draw_line(Vector2(72.0, 11.0), Vector2(91.0, 11.0), marker_color, 3.0)
	graph.draw_string(font, Vector2(97.0, 15.0), "Physik-RPM" if simulator.ui_language == 0 else "Physics RPM", HORIZONTAL_ALIGNMENT_LEFT, 83.0, 10, colors.text)
	graph.draw_dashed_line(Vector2(187.0, 11.0), Vector2(210.0, 11.0), colors.text, 1.5, 5.0)
	graph.draw_string(font, Vector2(216.0, 15.0), "Audio-RPM" if simulator.ui_language == 0 else "Audio RPM", HORIZONTAL_ALIGNMENT_LEFT, 80.0, 10, colors.text)
	# Fest eingebettete TC-Leuchte: grau = aus, blau = bereit, gelb = regelt.
	var tc_box := Rect2(size.x - 160.0, 2.0, 38.0, 16.0)
	var tc_color := Color("555555")
	if simulator.traction_control_enabled:
		tc_color = Color("ffd447") if simulator.traction_control_active else Color("3f9cff")
	graph.draw_rect(tc_box, colors.panel, true)
	graph.draw_rect(tc_box, tc_color.darkened(0.35), false, 1.0)
	graph.draw_string(font, Vector2(tc_box.position.x + 4.0, 14.0), "TC", HORIZONTAL_ALIGNMENT_CENTER, 30.0, 10, tc_color)
	graph.draw_string(font, Vector2(size.x - 112.0, 16.0), "VERSION %s" % UI_VERSION, HORIZONTAL_ALIGNMENT_RIGHT, 102.0, 10, colors.muted)
	# Feste Live-Spalten: wechselnde Stellenzahlen verschieben keine Nachbarwerte.
	var live_boxes := [Rect2(8, 22, 112, 24), Rect2(128, 22, 90, 24), Rect2(226, 22, 100, 24), Rect2(334, 22, 116, 24)]
	for box in live_boxes:
		graph.draw_rect(box, colors.panel, true)
		graph.draw_rect(box, colors.border.darkened(0.25), false, 1.0)
	graph.draw_string(font, Vector2(14.0, 39.0), "RPM", HORIZONTAL_ALIGNMENT_LEFT, 30.0, 12, colors.muted)
	graph.draw_string(font, Vector2(43.0, 39.0), "%.0f" % actual_current_rpm, HORIZONTAL_ALIGNMENT_RIGHT, 69.0, 13, colors.text)
	graph.draw_string(font, Vector2(134.0, 39.0), "PS", HORIZONTAL_ALIGNMENT_LEFT, 22.0, 12, colors.power)
	graph.draw_string(font, Vector2(157.0, 39.0), "%.0f" % simulator.calculate_power_ps(current), HORIZONTAL_ALIGNMENT_RIGHT, 53.0, 13, colors.text)
	graph.draw_string(font, Vector2(232.0, 39.0), "Nm", HORIZONTAL_ALIGNMENT_LEFT, 27.0, 12, colors.torque)
	graph.draw_string(font, Vector2(260.0, 39.0), "%.0f" % simulator.calculate_torque_nm(current), HORIZONTAL_ALIGNMENT_RIGHT, 58.0, 13, colors.text)
	graph.draw_string(font, Vector2(340.0, 39.0), "km/h", HORIZONTAL_ALIGNMENT_LEFT, 37.0, 12, colors.muted)
	graph.draw_string(font, Vector2(379.0, 39.0), "%.1f" % simulator.speed_kmh, HORIZONTAL_ALIGNMENT_RIGHT, 63.0, 13, colors.text)
	# Fester aktueller Gang direkt neben der NFS-Drag-Schaltampel.
	var gear_box := Rect2(458.0, 22.0, 48.0, 24.0)
	graph.draw_rect(gear_box, colors.panel, true)
	graph.draw_rect(gear_box, colors.border.darkened(0.25), false, 1.0)
	graph.draw_string(font, Vector2(463.0, 39.0), "G", HORIZONTAL_ALIGNMENT_LEFT, 12.0, 10, colors.muted)
	var live_gear_text := "R" if simulator.is_reversing else "%d" % int(simulator.current_gear)
	graph.draw_string(font, Vector2(476.0, 40.0), live_gear_text, HORIZONTAL_ALIGNMENT_CENTER, 25.0, 15, colors.text)
	# NFS-Drag-artige Schaltampel, mit fester Mindestbreite rechts daneben.
	var shift_box := Rect2(514.0, 22.0, maxf(size.x - 522.0, 98.0), 24.0)
	graph.draw_rect(shift_box, colors.panel, true)
	graph.draw_rect(shift_box, colors.border.darkened(0.25), false, 1.0)
	var launch_display := bool(simulator.race_launch_staging) or bool(simulator.race_launch_effect_active)
	var launch_caption := {
		"ZU_WENIG": "L RPM NIEDRIG",
		"GUT": "L GUT",
		"PERFEKT": "L PERFEKT",
		"DURCHDREHEN": "L SPIN",
	}.get(str(simulator.race_launch_status), "L BEREIT")
	var box_caption: String = launch_caption if launch_display else "SHIFT"
	graph.draw_string(font, Vector2(519.0, 39.0), box_caption, HORIZONTAL_ALIGNMENT_LEFT, 38.0, 7 if launch_display else 9, colors.muted)
	# Anzeige und Startbewertung verwenden dieselbe Physik-Drehzahl.
	# Kein Audio-Nachlauf darf den Spieler in eine andere Timing-Zone fuehren.
	var shift_rpm := float(simulator.physics_rpm)
	var perfect_rpm := float(simulator.get_effective_upshift_rpm())
	var perfect_shift_window := float(simulator.get_perfect_shift_window_width())
	# Keine nachblendende Limiter-WAV als Logik verwenden: Ihr Mix kann nach dem
	# eigentlichen Ereignis noch aktiv sein und die rote Lampe festhalten.
	var limiter_active := shift_rpm >= float(simulator._get_artificial_limiter_trigger_normalized())
	var shift_state := 0
	if simulator.race_launch_staging:
		# Während die Handbremse gehalten wird, ist die Ampel eine Live-Anzeige.
		# Die spätere Startwertung verwendet ebenfalls die physikalische RPM;
		# ein alter Limiterkontakt darf die rote Lampe nicht festhalten.
		var live_launch_rpm := float(simulator.calculate_actual_rpm(shift_rpm))
		var live_launch_window: Vector2 = simulator._get_effective_race_launch_window()
		var limiter_trigger := float(simulator._get_artificial_limiter_trigger_normalized())
		var limiter_hit_now := shift_rpm >= limiter_trigger
		if limiter_hit_now:
			# Die Drehzahl kann den Trigger zwischen zwei UI-Zeichenframes treffen.
			# Ein sehr kurzer Merker macht jeden echten Cut sichtbar, ohne den alten
			# DURCHDREHEN-Status dauerhaft als rote Lampe darzustellen.
			_limiter_flash_until_msec = Time.get_ticks_msec() + 90
		if Time.get_ticks_msec() < _limiter_flash_until_msec:
			shift_state = 3
		elif live_launch_rpm >= live_launch_window.x and live_launch_rpm <= live_launch_window.y:
			shift_state = 2
		elif live_launch_rpm >= live_launch_window.x - maxf((simulator.max_rpm - simulator.idle_rpm) * 0.10, 250.0):
			shift_state = 1
	else:
		_limiter_flash_until_msec = 0
	if not simulator.race_launch_staging and simulator.race_launch_effect_active:
		match str(simulator.race_launch_status):
			"ZU_WENIG": shift_state = 0
			"GUT": shift_state = 1
			"PERFEKT": shift_state = 2
			"DURCHDREHEN": shift_state = 3
	elif not simulator.race_launch_staging and simulator.engine_power_available and simulator.throttle > 0.1 and not simulator.is_shifting:
		if limiter_active or shift_rpm >= perfect_rpm:
			shift_state = 3 # rot: überdreht
		elif shift_rpm >= perfect_rpm - perfect_shift_window:
			shift_state = 2 # grün: perfekt
		elif shift_rpm >= perfect_rpm - maxf(0.14, perfect_shift_window + 0.06):
			shift_state = 1 # blau: jetzt schalten ist okay
	var light_right := shift_box.end.x - 12.0
	var light_positions := [light_right - 48.0, light_right - 24.0, light_right]
	var active_colors := [Color("3f9cff"), Color("42df72"), Color("ef4b4b")]
	var is_last_gear := int(simulator.current_gear) >= int(simulator.number_of_gears)
	var last_gear_blink := int(Time.get_ticks_msec() / 280) % 2 == 0
	var launch_zone_blink := int(Time.get_ticks_msec() / 180) % 2 == 0
	var overrev_blink := int(Time.get_ticks_msec() / 110) % 2 == 0
	for light_index in range(3):
		var active := shift_state == light_index + 1
		var light_color: Color
		if simulator.race_launch_staging and shift_state > 0:
			# Nur beim stehenden Rennstart zeigen alle drei Lampen gemeinsam die
			# aktuelle Zone: 3x blau, 3x grün oder 3x rot. Der rote Zustand wird
			# bereits durch die echten kurzen Limiter-Flashs ein-/ausgeschaltet.
			var launch_color: Color = active_colors[shift_state - 1]
			var launch_blink_on := true if shift_state == 3 else launch_zone_blink
			light_color = launch_color if launch_blink_on else launch_color.darkened(0.72)
		elif shift_state == 3 and light_index == 2:
			light_color = Color("ef4b4b") if overrev_blink else Color("541b1b")
		elif is_last_gear and not launch_display:
			light_color = Color("ffd447") if last_gear_blink else Color("594a19")
		else:
			light_color = active_colors[light_index] if active else active_colors[light_index].darkened(0.72)
		graph.draw_circle(Vector2(light_positions[light_index], 34.0), 6.0, Color("090909"))
		graph.draw_circle(Vector2(light_positions[light_index], 34.0), 4.5, light_color)

#endregion

#region Beschleunigungszeiten
func _draw_acceleration_display() -> void:
	var graph := acceleration_display
	var size := graph.size
	var colors := _palette()
	graph.draw_rect(Rect2(Vector2.ZERO, size), colors.panel_deep, true)
	graph.draw_rect(Rect2(Vector2(0.5, 0.5), size - Vector2.ONE), colors.border, false, 1.0)
	var gap := 8.0
	var box_width := (size.x - gap - 16.0) * 0.5
	var first := Rect2(8.0, 7.0, box_width, size.y - 14.0)
	var second := Rect2(first.end.x + gap, 7.0, box_width, size.y - 14.0)
	for box in [first, second]:
		graph.draw_rect(box, colors.panel, true)
		graph.draw_rect(box, colors.border.darkened(0.25), false, 1.0)
	var font := ThemeDB.fallback_font
	graph.draw_string(font, Vector2(first.position.x + 10.0, 25.0), "0–100 km/h", HORIZONTAL_ALIGNMENT_LEFT, 105.0, 12, colors.muted)
	graph.draw_string(font, Vector2(first.position.x + 118.0, 28.0), simulator._format_acceleration_time(simulator.acceleration_time_0_100, 100.0), HORIZONTAL_ALIGNMENT_RIGHT, box_width - 128.0, 16, colors.text)
	graph.draw_string(font, Vector2(second.position.x + 10.0, 25.0), "100–200 km/h", HORIZONTAL_ALIGNMENT_LEFT, 120.0, 12, colors.muted)
	graph.draw_string(font, Vector2(second.position.x + 133.0, 28.0), simulator._format_acceleration_time(simulator.acceleration_time_100_200, 200.0), HORIZONTAL_ALIGNMENT_RIGHT, box_width - 143.0, 16, colors.text)
#endregion
