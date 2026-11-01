@icon("res://addons/bungee/assets/icons/bungee_vehicle_simulator_node.svg")
class_name BungeeVehicleSimulator
extends Node3D
## Einfacher Arcade-Fahrprüfstand als direktes Kind des Engine-Sound-Nodes.
## RPM-Steuerung plus separater Wobble-Impuls; Grund-Pitch und Lautstärken bleiben beim Motor.

signal gear_changed(previous_gear: int, new_gear: int)

enum TransmissionType { HANDSCHALTER, AUTOMATIK, DSG_SEQUENZIELL }


@export_category("01 Vehicle and Engine")

@export_group("Engine - Power and RPM")
## Motorleistung und Fahrzeugmasse bestimmen gemeinsam den Vortrieb.
@export_range(1.0, 2000.0, 1.0, "suffix:PS") var horsepower: float = 300.0
@export_range(100.0, 5000.0, 10.0, "suffix:kg") var vehicle_mass_kg: float = 1500.0
@export_range(1000.0, 20000.0, 100.0, "suffix:RPM") var max_rpm: float = 8000.0
@export_range(500.0, 2000.0, 50.0, "suffix:RPM") var idle_rpm: float = 900.0

@export_group("Engine Character - Power Curve")
## 0 = deutlich unruhige Serien-/Verschleißkurve, 1 = glatt abgestimmter Motor.
@export_range(0.0, 1.0, 0.01) var engine_smoothness: float = 0.65
## Verändert den Charakter der Unebenheiten, ohne zusätzliche Kurvenpflege.
@export_range(1, 99, 1) var engine_character: int = 1

@export_group("Struggle - Load and Coast")
## Gemeinsames hörbares Kämpfen bei Wheelspin oder hoher Last in zu hohem Gang.
@export var engine_struggle_enabled: bool = true
@export_range(0.0, 1.0, 0.01) var engine_struggle_strength: float = 0.05
## Reaktion auf flache oder lokal einbrechende Nm-Bereiche der Motorkurve.
@export_range(0.0, 1.0, 0.01) var engine_struggle_curve_sensitivity: float = 0.55
## Kurvenabhängiges Kämpfen beim Herunterdrehen ohne Gas.
@export_range(0.0, 1.0, 0.01) var coast_curve_struggle_strength: float = 0.22

@export_group("Idle - Simulation without Idle WAV")
## Wird ausschließlich verwendet, wenn im Motorsound keine Idle-WAV existiert.
@export var artificial_idle_enabled: bool = true
@export_range(0.0, 500.0, 5.0, "suffix:RPM") var artificial_idle_pulse_rpm: float = 140.0
@export_range(0.5, 8.0, 0.1, "suffix:Hz") var artificial_idle_pulse_speed: float = 2.2

@export_group("RPM Limiter - Push and Cut")
## Audio-gesteuerter Arcade-Begrenzer: Trigger erreicht -> harter RPM-Rücksprung.
@export var artificial_rpm_limiter_enabled: bool = true
# Legacy-Feld für alte Presets/Szenen. Der echte Trigger wird immer automatisch
# direkt aus max_rpm gebildet, damit jedes Fahrzeug wirklich bis ans Ende dreht.
var artificial_rpm_limiter_trigger_rpm: float = 8000.0
# Legacy-Zielposition alter Presets; verwendet wird jetzt die Rücksprungweite.
var artificial_rpm_limiter_drop_rpm: float = 7950.0
## Rücksprungweite unter Max-RPM, z.B. 200 bei 8000 RPM ergibt 7800 RPM.
@export_range(5.0, 5000.0, 5.0, "suffix:RPM") var artificial_rpm_limiter_drop_amount_rpm: float = 5.0
## Verstärkt nur den hörbaren Rücksprung; 1 = normale Audio-Follow-Stärke.
@export_range(1.0, 20.0, 0.5) var artificial_rpm_limiter_cut_strength: float = 6.0

@export_category("02 Transmission and Driving Behavior")

@export_group("Transmission - Shifting")
@export_enum("Manual", "Automatic", "DSG / Sequential") var transmission_type: int = TransmissionType.AUTOMATIK
@export var automatic_gears: bool = true
@export var automatic_perfect_shift: bool = false
@export_range(1, 10, 1) var number_of_gears: int = 5
## Anteil der RPM nach dem Hochschalten: 0.68 bedeutet z.B. 0.94 -> 0.64.
@export_range(0.5, 0.9, 0.01) var gear_rpm_drop: float = 0.68
@export_range(0.5, 0.99, 0.01) var upshift_rpm: float = 0.94
@export_range(0.1, 0.8, 0.01) var downshift_rpm: float = 0.35
## Kurze Vortriebspause. Das RPM-Ziel springt beim Einlegen des Gangs direkt.
@export_range(0.04, 0.5, 0.01) var shift_time: float = 0.12
## Nur die Rückschaltung ist nach einem Upshift zusätzlich gesperrt.
@export_range(0.0, 3.0, 0.05) var downshift_lock_time: float = 0.8
## Arcade-Motorbremse bei einem manuell zu tief gewählten Gang.
@export_range(20.0, 250.0, 5.0, "suffix:km/h/s") var downshift_wheel_lock_strength: float = 120.0
## Zeit, in der Last und Traktion nach gelöstem Radblock wieder greifen.
@export_range(0.05, 1.5, 0.05, "suffix:s") var downshift_grip_recovery_time: float = 0.45

@export_group("Top Speed - Automatic or Manual")
## AUS nutzt Max Speed direkt; AN berechnet eine Arcade-Vmax aus PS, RPM und Gangzahl.
@export var automatic_max_speed: bool = false
@export_range(20.0, 500.0, 1.0) var max_speed_kmh: float = 240.0

@export_group("Braking and Coasting")
@export_range(0.0, 80.0, 1.0) var coast_deceleration: float = 10.0
@export_range(1.0, 200.0, 1.0) var brake_strength: float = 70.0
## Geschwindigkeitsverlust bei entkoppeltem Motor/Handbremse; Gas erzeugt keinen Vortrieb.
@export_range(0.0, 30.0, 0.5) var handbrake_deceleration: float = 4.0

@export_group("Launch and Clutch Engagement")
## Anfahr-Drehzahl bei Vollgas, normalisiert wie die Audio-RPM (0 bis 1).
@export_range(0.0, 1.0, 0.01) var launch_rpm: float = 0.45
@export_range(0.05, 1.0, 0.01) var launch_rise_time: float = 0.25
## Zeit zum sanften Einkuppeln auf die geschwindigkeitsabhängige Drehzahl.
@export_range(0.1, 2.0, 0.01) var launch_settle_time: float = 0.65

@export_group("Free Revving - Handbrake")
## Handbremse entkoppelt den Motor. Gas lässt ihn ohne Vortrieb hochdrehen.
@export_range(0.5, 10.0, 0.1) var handbrake_rev_speed: float = 3.5
@export_range(0.2, 6.0, 0.1) var free_rev_fall_speed: float = 1.5

@export_category("03 Race Launch and Driving Assists")

@export_group("Traction Control - Manage Wheelspin")
@export var traction_control_enabled: bool = true
## 1.0 regelt vollständig bis zur Haftungsgrenze, kleinere Werte erlauben Restschlupf.
@export_range(0.0, 1.0, 0.01) var traction_control_strength: float = 0.94

@export_group("Launch Control - Hold RPM")
@export var launch_control_enabled: bool = false
@export_range(1000.0, 20000.0, 100.0, "suffix:RPM") var launch_control_rpm: float = 4500.0
@export_range(0.0, 1500.0, 25.0, "suffix:RPM") var launch_control_rpm_jump: float = 300.0
@export_range(1.0, 20.0, 0.5, "suffix:Hz") var launch_control_jump_speed: float = 8.0

@export_group("Race Launch - Rating and Wheelspin")
@export var race_launch_enabled: bool = true
@export_range(500.0, 20000.0, 50.0, "suffix:RPM") var race_launch_perfect_from_rpm: float = 5500.0
@export_range(500.0, 20000.0, 50.0, "suffix:RPM") var race_launch_perfect_to_rpm: float = 7500.0
## Bis zu diesem Tempo wird der schlechte Start weich von vollem Wheelspin ausgeblendet.
@export_range(5.0, 100.0, 1.0, "suffix:km/h") var race_launch_wheelspin_end_speed_kmh: float = 30.0
## Zeitlicher Bonus gilt nur für gute/perfekte Starts; Wheelspin endet per km/h.
@export_range(0.2, 2.0, 0.05, "suffix:s") var race_launch_bonus_duration: float = 0.8

@export_group("Difficulty - Launch and Shifting")
## Breites perfektes Fenster in den unteren Gängen, danach zunehmend präziser.
## Hohe Leistung pro Tonne erhält automatisch etwas Reaktionszeitausgleich.
@export var progressive_shift_difficulty: bool = true
@export_range(0.0, 1.0, 0.05) var shift_difficulty: float = 0.65
## Direkter Multiplikator für free_rev_fall_speed bei gehaltener Handbremse:
## 0 = sehr leicht/langsamer Fall, 1 = schwer/originaler Fahrzeugwert.
@export_range(0.0, 1.0, 0.05) var free_rev_fall_difficulty: float = 1.0

@export_category("04 Forced Induction and Sound Impulses")

@export_group("Supercharger Power")
@export var supercharger_enabled: bool = false
## Zusätzliche mechanische Kompressorleistung; wirkt auf Vortrieb, Dyno und Auto-Vmax.
@export_range(0.0, 1000.0, 1.0, "suffix:PS") var supercharger_power_ps: float = 100.0

@export_group("Turbo - Power and Boost Build-Up")
@export var turbo_enabled: bool = false
@export_range(0.0, 1500.0, 1.0, "suffix:PS") var turbo_power_ps: float = 150.0
## Unterhalb dieser normalisierten RPM baut der Turbo kaum Druck auf.
@export_range(0.0, 0.8, 0.01) var turbo_spool_start_rpm: float = 0.25
## Ladedruck-Reststrecke fuer volle Aufbaugeschwindigkeit; alter Name fuer Presets.
@export_range(0.001, 0.2, 0.001) var turbo_full_boost_audio_dist: float = 0.02
@export_range(0.1, 5.0, 0.05) var turbo_spool_up_speed: float = 1.2
@export_range(0.1, 8.0, 0.05) var turbo_spool_down_speed: float = 3.0

@export_group("Throttle and Shift Wobble - Pitch Only")
@export var wobble_enabled: bool = true:
	set(value):
		wobble_enabled = value
		if not value:
			_reset_wobble()
## Kurzer Tonhöhenimpuls, ohne Änderung der RPM oder ACC/DCC-Richtung.
@export_range(0.0, 0.35, 0.001) var wobble_strength: float = 0.025
@export_range(0.1, 1.0, 0.01) var wobble_duration: float = 0.35

@export_category("05 System and Display")

@export_group("Simulator Activation")
@export var simulator_enabled: bool = true:
	set(value):
		simulator_enabled = value
		if not value:
			_cancel_shift()
			_reset_wobble()
			_launch_elapsed = -1.0
			_launch_armed = true
			launch_control_active = false
			_launch_control_was_active = false
			_launch_control_phase = 0.0
		if is_instance_valid(_debug_ui):
			_debug_ui.sync_controls()

@export_group("Interface - Visibility and Design")
@export var debug_ui_enabled: bool = true:
	set(value):
		debug_ui_enabled = value
		if is_instance_valid(_debug_ui):
			_debug_ui.visible = value
@export var debug_values_enabled: bool = true:
	set(value):
		debug_values_enabled = value
		if is_instance_valid(_debug_ui):
			_debug_ui.sync_controls()
@export var power_graph_enabled: bool = true:
	set(value):
		power_graph_enabled = value
		if is_instance_valid(_debug_ui):
			_debug_ui.sync_controls()
			_debug_ui.fit_to_screen.call_deferred()
@export_enum("Dark", "NFS ProStreet", "NFS Most Wanted 2005", "Street Racing Red", "Retro Dyno") var ui_style: int = 0:
	set(value):
		ui_style = clampi(value, 0, 4)
		if is_instance_valid(_debug_ui) and _debug_ui.has_method("rebuild_ui"):
			_debug_ui.rebuild_ui()
@export_enum("German", "English") var ui_language: int = 1:
	set(value):
		ui_language = clampi(value, 0, 1)
		if is_instance_valid(_debug_ui) and _debug_ui.has_method("rebuild_ui"):
			_debug_ui.rebuild_ui()

@export_group("Dyno Scaling")
## Skaliert RPM, PS und Nm aus den aktuellen Motordaten und lässt oben Luft.
@export var automatic_dyno_scale: bool = true
@export_range(0.0, 0.5, 0.01, "suffix:%") var dyno_scale_headroom: float = 0.15
@export_range(6000.0, 20000.0, 500.0, "suffix:RPM") var dyno_max_rpm: float = 12000.0
@export_range(100.0, 3000.0, 50.0, "suffix:PS") var dyno_max_power_ps: float = 1000.0
@export_range(100.0, 3000.0, 50.0, "suffix:Nm") var dyno_max_torque_nm: float = 1000.0

# Messwerte, keine Sound-Einstellungen.
var throttle: float = 0.0
var brake: float = 0.0
var handbrake: float = 0.0
var speed_kmh: float = 0.0
var rpm_normalized: float = 0.0
## Physikalische Motor-RPM; Audio-Follow, Struggle und Audio-Cuts schreiben nie hierher.
var physics_rpm: float = 0.0
var _physics_launch_remaining: float = 0.0
var _physics_launch_peak: float = 0.0
var _physics_launch_armed: bool = true
var visual_rpm: float = 0.0
var current_gear: int = 1
var is_reversing: bool = false
var is_shifting: bool = false
var wobble: float = 0.0
var acceleration_time_0_100: float = -1.0
var acceleration_time_100_200: float = -1.0
var traction: float = 1.0
var wheelspin: float = 0.0
var traction_control_active: bool = false
var _tc_phase: float = 0.0
var _tc_recovery: float = 0.0
var _tc_pulse: float = 0.0
var downshift_wheel_lock: bool = false
var supercharger_boost: float = 0.0
var turbo_boost: float = 0.0
var launch_control_active: bool = false
var race_launch_staging: bool = false
var race_launch_status: String = "BEREIT"
var race_launch_effect_active: bool = false
var engine_power_available: bool = true
var vehicle_presets: Array[Dictionary] = []
var selected_vehicle_preset: int = 0
var _vehicle_preset_defaults: Dictionary = {}
var speed: float:
	get: return speed_kmh
var rpm: float:
	get: return rpm_normalized
var currentgear: int:
	get: return current_gear

var _engine_sound_system: Node
var _parent_properties: Dictionary = {}
var _pending_gear: int = 1
var _gear_changed: bool = false
var _shift_timer: float = 0.0
var _shift_duration: float = 0.12
var _shift_start_rpm: float = 0.0
var _manual_shift_requested: bool = false
var _downshift_grip_recovery: float = 1.0
var _downshift_lock_target_speed: float = 0.0
var _downshift_lock_timer: float = 0.0
var _artificial_limiter_cut_active: bool = false
var _gear_hold_timer: float = 0.0
var _was_free_reving: bool = false
var _last_step_speed_kmh: float = 0.0
var _sudden_speed_loss: bool = false
var _acceleration_run_time: float = -1.0
var _time_at_100: float = -1.0
var _launch_armed: bool = true
var _launch_elapsed: float = -1.0
var _launch_start_rpm: float = 0.0
var _launch_peak_rpm: float = 0.0
var _launch_control_phase: float = 0.0
var _launch_control_was_active: bool = false
var _launch_control_release_timer: float = 0.0
var _race_launch_effect_timer: float = 0.0
var _race_launch_power_factor: float = 1.0
var _race_launch_traction_factor: float = 1.0
var _race_launch_spin_hold_rpm: float = 0.0
var _race_launch_spin_severity: float = 1.0
var _engine_struggle_phase: float = 0.0
var _audio_struggle_active: bool = false
var _engine_start_rev_elapsed: float = -1.0
var _engine_start_rev_begin: float = 0.0
var _engine_start_rev_peak: float = 0.6
var _debug_ui: CanvasLayer
var _wobble_velocity: float = 0.0
var _gas_wobble_armed: bool = true
var _wobble_waiting_for_audio_rise: bool = false
var _last_audio_rpm_dist: float = 0.0
var _post_shift_rpm_floor: float = 0.0
var _post_shift_audio_floor: float = 0.0
var _ui_elapsed: float = 0.0
var _reverse_to_forward_active: bool = false
var _reverse_launch_wheelspin_timer: float = 0.0
var _artificial_idle_phase: float = 0.0

const INPUT_EPSILON: float = 0.02
const MIN_GEAR_HOLD: float = 0.22
const WOBBLE_HZ: float = 8.0
const HP_TO_WATTS: float = 735.5
const DRIVETRAIN_EFFICIENCY: float = 0.78
## Rund 1 g: automatische Arcade-Grenze für Reifenhaftung/Wheelie beim Start.
const TRACTION_LIMIT_KMH_S: float = 36.0
const VEHICLE_PRESET_PATH: String = "res://addons/bungee/presets/vehicles"
const PROJECT_CUSTOM_PRESET_PATH: String = "res://addons/bungee/presets/custom"
const LEGACY_CUSTOM_PRESET_PATH: String = "user://vehicle_presets"
const VEHICLE_PRESET_PROPERTIES: Array[String] = [
	"horsepower", "vehicle_mass_kg", "max_rpm", "idle_rpm", "artificial_idle_enabled",
	"artificial_idle_pulse_rpm", "artificial_idle_pulse_speed", "max_speed_kmh",
	"automatic_max_speed", "number_of_gears", "gear_rpm_drop", "upshift_rpm",
	"downshift_rpm", "engine_smoothness", "engine_character", "coast_deceleration",
	"brake_strength", "turbo_enabled", "turbo_power_ps", "turbo_spool_start_rpm",
	"supercharger_enabled", "supercharger_power_ps", "engine_struggle_enabled",
	"engine_struggle_strength", "engine_struggle_curve_sensitivity", "shift_time", "downshift_lock_time",
	"downshift_grip_recovery_time", "launch_rpm", "launch_rise_time", "launch_settle_time",
	"handbrake_rev_speed", "free_rev_fall_speed", "wobble_enabled", "wobble_strength",
	"wobble_duration", "coast_curve_struggle_strength", "turbo_full_boost_audio_dist", "turbo_spool_up_speed",
	"turbo_spool_down_speed", "launch_control_enabled", "launch_control_rpm",
	"launch_control_rpm_jump", "launch_control_jump_speed", "race_launch_enabled",
	"race_launch_perfect_from_rpm", "race_launch_perfect_to_rpm",
	"race_launch_wheelspin_end_speed_kmh", "race_launch_bonus_duration",
	"artificial_rpm_limiter_enabled", "artificial_rpm_limiter_trigger_rpm",
	"artificial_rpm_limiter_drop_rpm", "artificial_rpm_limiter_cut_strength",
	"artificial_rpm_limiter_drop_amount_rpm",
	"automatic_perfect_shift", "transmission_type", "traction_control_enabled",
	"traction_control_strength"
]
const ENGINE_SOUND_PRESET_PROPERTIES: Array[String] = [
	"acc_dcc_transition_ms", "distance_strength", "engine_pitch", "idle_fade_end",
	"idle_volume", "limiter_fade_start", "limiter_volume", "direction_tone_enabled",
	"tone_cutoff_rise_hz", "tone_cutoff_fall_hz", "tone_resonance_rise",
	"tone_resonance_fall", "highs_enabled", "highs_gain_db", "highs_start_hz",
	"transmission_enabled", "transmission_max_speed_volume", "transmission_pitch",
	"transmission_pitch_low_speed", "transmission_pitch_high_speed",
	"transmission_coast_amount", "shift_up_sound_volume", "shift_up_sound_pitch",
	"shift_down_sound_volume", "shift_down_sound_pitch", "supercharger_volume",
	"supercharger_pitch_idle", "supercharger_pitch_redline", "supercharger_coast_amount",
	"turbo_volume", "turbo_pitch", "bov_volume", "backfire_enabled", "backfire_volume",
	"backfire_strength", "backfire_pitch", "backfire_min_load", "backfire_cooldown",
	"backfire_burst_duration", "backfire_bang_interval", "backfire_pitch_kick"
]

#region Initialisierung und Presets
func _ready() -> void:
	_engine_sound_system = get_parent()
	if is_instance_valid(_engine_sound_system):
		for property in _engine_sound_system.get_property_list():
			_parent_properties[property.name] = true
		# Neue RPM vor dem Audio-Physics-Tick bereitstellen.
		process_physics_priority = _engine_sound_system.process_physics_priority - 1
	if not _parent_properties.has("rpm_position"):
		push_error("Engine Simulator: direkt unter den Engine-Sound-Node hängen (rpm_position fehlt).")
		simulator_enabled = false
	_capture_vehicle_preset_defaults()
	_load_vehicle_presets()
	# Beim Start direkt mit einem definierten Fahrzeug beginnen. Dadurch sind
	# Simulation und UI sofort auf dem ersten Preset statt auf Inspector-Werten.
	if not vehicle_presets.is_empty():
		apply_vehicle_preset(0)
	_bind_optional_ui()
	_update_debug_ui()

func _exit_tree() -> void:
	_reset_wobble()

func _load_vehicle_presets() -> void:
	vehicle_presets.clear()
	_append_vehicle_presets(_built_in_vehicle_preset_path(), false)
	_append_vehicle_presets(_project_custom_preset_path(), true)
	# Im Editor bleiben frühere user://-Presets zur Migration erreichbar.
	if OS.has_feature("editor"):
		_append_vehicle_presets(LEGACY_CUSTOM_PRESET_PATH, true)
	selected_vehicle_preset = clampi(selected_vehicle_preset, 0, maxi(vehicle_presets.size() - 1, 0))

func _built_in_vehicle_preset_path() -> String:
	if not OS.has_feature("editor"):
		return OS.get_executable_path().get_base_dir().path_join("vehicle_presets")
	return VEHICLE_PRESET_PATH

func _project_custom_preset_path() -> String:
	if not OS.has_feature("editor"):
		return OS.get_executable_path().get_base_dir().path_join("vehicle_presets/custom")
	return ProjectSettings.globalize_path(PROJECT_CUSTOM_PRESET_PATH)

func _custom_preset_write_folder() -> String:
	var project_folder := _project_custom_preset_path()
	if DirAccess.make_dir_recursive_absolute(project_folder) == OK:
		return project_folder
	return ""

func _append_vehicle_presets(folder: String, custom: bool) -> void:
	var directory := DirAccess.open(folder)
	if directory == null:
		return
	var files := PackedStringArray(directory.get_files())
	files.sort()
	for file_name in files:
		if file_name.get_extension().to_lower() != "json":
			continue
		var file := FileAccess.open(folder.path_join(file_name), FileAccess.READ)
		if file == null:
			continue
		var parsed = JSON.parse_string(file.get_as_text())
		if not parsed is Dictionary or not parsed.has("presets") or not parsed.presets is Array:
			push_warning("Engine Simulator: ungültiges Preset: %s" % file_name)
			continue
		var category := str(parsed.get("category", file_name.get_basename()))
		for entry in parsed.presets:
			if entry is Dictionary and entry.has("name") and entry.get("settings", {}) is Dictionary:
				var sound_settings: Dictionary = parsed.get("sound_defaults", {}).duplicate(true)
				var sound_overrides: Dictionary = entry.get("sound", {})
				for sound_property in sound_overrides:
					sound_settings[sound_property] = sound_overrides[sound_property]
				vehicle_presets.append({"name": str(entry.name), "category": category, "settings": entry.settings, "sound": sound_settings, "custom": custom, "file": folder.path_join(file_name)})

func _preset_snapshot(node: Node, excluded: Array[String]) -> Dictionary:
	var snapshot := {}
	if not is_instance_valid(node):
		return snapshot
	for property in node.get_script().get_script_property_list():
		if property.usage & PROPERTY_USAGE_EDITOR and property.usage & PROPERTY_USAGE_STORAGE and property.name not in excluded:
			var value = node.get(property.name)
			if typeof(value) in [TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING]:
				snapshot[property.name] = value
	return snapshot

func _custom_vehicle_snapshot() -> Dictionary:
	return _preset_snapshot(self, ["simulator_enabled", "debug_ui_enabled", "debug_values_enabled", "power_graph_enabled", "ui_style", "ui_language", "automatic_dyno_scale", "dyno_scale_headroom", "dyno_max_rpm", "dyno_max_power_ps", "dyno_max_torque_nm"])

func _custom_sound_snapshot() -> Dictionary:
	return _preset_snapshot(_engine_sound_system, [
		"engine_running", "rpm_position", "live_input_mode", "automatic_load_from_rpm", "automatic_backfire_trigger", "trigger_gear_up", "trigger_gear_down", "trigger_bov", "trigger_backfire", "throttle", "speed_kmh",
		"max_speed_kmh", "current_gear", "number_of_gears", "is_shifting", "is_reversing",
		"handbrake", "wheelspin", "downshift_wheel_lock", "turbo_enabled",
		"automatic_turbo_boost", "turbo_boost", "automatic_turbo_spool_start_rpm",
		"automatic_turbo_spool_up_speed", "automatic_turbo_spool_down_speed",
		"supercharger_enabled", "external_limiter_cut_active",
		"artificial_rpm_limiter_cut_strength",
		# Umgebung gehört zur Strecke/Szene und niemals zum Fahrzeug-Preset.
		"reverb_enabled", "reverb_preset", "reverb_amount", "reverb_fade_speed",
		"cabin_enabled", "cabin_preset", "cabin_amount", "cabin_fade_speed"
	])

func save_vehicle_preset(preset_name: String) -> Dictionary:
	var clean_name := preset_name.strip_edges().substr(0, 80)
	if clean_name.is_empty():
		return {"ok": false, "error": "name"}
	var save_folder := _custom_preset_write_folder()
	if save_folder.is_empty():
		return {"ok": false, "error": "Preset-Ordner konnte nicht angelegt werden"}
	# Dateiname kommt nicht aus Benutzereingaben; vorhandene Presets nie ersetzen.
	var path := save_folder.path_join("custom_%d_%d.json" % [int(Time.get_unix_time_from_system()), Time.get_ticks_usec()])
	while FileAccess.file_exists(path):
		path = path.get_basename() + "_copy.json"
	var data := {"category": "Eigene Presets", "presets": [{"name": clean_name, "settings": _custom_vehicle_snapshot(), "sound": _custom_sound_snapshot()}]}
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return {"ok": false, "error": error_string(FileAccess.get_open_error())}
	file.store_string(JSON.stringify(data, "\t"))
	file.flush()
	var error := file.get_error()
	file.close()
	if error != OK:
		return {"ok": false, "error": error_string(error)}
	_load_vehicle_presets()
	for index in range(vehicle_presets.size()):
		if vehicle_presets[index].get("file", "") == path:
			selected_vehicle_preset = index
			break
	return {"ok": true, "path": path}

func _capture_vehicle_preset_defaults() -> void:
	# Szene-/Inspector-Grundwerte einmal sichern. Ein später geladenes Preset darf
	# niemals fehlende Angaben vom zuvor ausgewählten Fahrzeug erben.
	_vehicle_preset_defaults.clear()
	for property_name in VEHICLE_PRESET_PROPERTIES:
		_vehicle_preset_defaults[property_name] = get(property_name)

func apply_vehicle_preset(index: int = -1) -> bool:
	if vehicle_presets.is_empty():
		return false
	selected_vehicle_preset = clampi(selected_vehicle_preset if index < 0 else index, 0, vehicle_presets.size() - 1)
	var settings: Dictionary = vehicle_presets[selected_vehicle_preset].settings
	# Zuerst auf eine definierte Basis zurücksetzen, danach Preset-Werte anwenden.
	# Damit wird z.B. aus einem F1 -> Kleinwagen kein Kleinwagen mit F1-Rev-Speed.
	for property_name in VEHICLE_PRESET_PROPERTIES:
		if _vehicle_preset_defaults.has(property_name):
			set(property_name, _vehicle_preset_defaults[property_name])
	for property_name in VEHICLE_PRESET_PROPERTIES:
		if settings.has(property_name):
			set(property_name, settings[property_name])
	# Fehlende freie Hochdrehwerte automatisch nach Leistungsgewicht abstimmen.
	# Diese Werte betreffen nur den entkoppelten Motor, nicht die Beschleunigung.
	var preset_power_per_ton := _get_peak_horsepower() * 1000.0 / maxf(vehicle_mass_kg, 1.0)
	var rev_performance := smoothstep(55.0, 700.0, preset_power_per_ton)
	if not settings.has("handbrake_rev_speed"):
		handbrake_rev_speed = lerpf(1.7, 8.0, rev_performance)
	if not settings.has("free_rev_fall_speed"):
		free_rev_fall_speed = lerpf(0.72, 4.4, rev_performance)
	# Sehr kleine alte Presetwerte verschwinden klanglich unter dem weicheren
	# ACC/DCC-Crossfade. Presets erhalten eine hörbare, weiterhin dezente Basis;
	# der Benutzer kann sie anschließend im UI frei weiter absenken.
	if settings.has("wobble_strength"):
		wobble_strength = maxf(wobble_strength, 0.022)
	# Jedes Fahrzeug besitzt auch ohne Limiter-WAV eine echte Redline. Presets
	# ohne eigene Abstimmung erhalten automatisch einen kurzen RPM-Rücksprung.
	if not settings.has("artificial_rpm_limiter_enabled"):
		artificial_rpm_limiter_enabled = true
	if not settings.has("artificial_rpm_limiter_trigger_rpm"):
		artificial_rpm_limiter_trigger_rpm = snappedf(max_rpm * 0.985, 5.0)
	if not settings.has("artificial_rpm_limiter_drop_rpm"):
		artificial_rpm_limiter_drop_rpm = snappedf(max_rpm * 0.94, 5.0)
	if not settings.has("artificial_rpm_limiter_cut_strength"):
		artificial_rpm_limiter_cut_strength = 8.0
	# Zustände, die in älteren Presets fehlen, dürfen nicht vom zuvor geladenen
	# Fahrzeug übernommen werden. Der Rennstart ist grundsätzlich verfügbar;
	# Launch-Control dagegen nur, wenn das Preset sie ausdrücklich aktiviert.
	if not settings.has("race_launch_enabled"):
		race_launch_enabled = true
	if not settings.has("launch_control_enabled"):
		launch_control_enabled = false
	if not settings.has("launch_control_rpm"):
		launch_control_rpm = snappedf(max_rpm * 0.76, 50.0)
	# Presets ohne eigenes Rennstartfenster erhalten ein zur Motor-RPM passendes
	# Fenster. So bleiben keine Werte des zuvor geladenen Fahrzeugs hängen.
	if not settings.has("race_launch_perfect_from_rpm"):
		race_launch_perfect_from_rpm = snappedf(max_rpm * 0.65, 50.0)
	if not settings.has("race_launch_perfect_to_rpm"):
		race_launch_perfect_to_rpm = snappedf(max_rpm * 0.88, 50.0)
	# Der eigentliche Motorklang (Filter, Höhen, Resonanz und Engine-Pitch) bleibt
	# beim gewählten Motorsound. Fahrzeug-Presets dürfen aber ihre Zusatzquellen
	# passend aktivieren und abstimmen: Getriebe, Turbo/BOV, Kompressor, Shift und
	# Backfire. Soundbank und Datei-Indizes werden dabei niemals gewechselt.
	var preset_sound: Dictionary = vehicle_presets[selected_vehicle_preset].get("sound", {})
	var applied_sound_properties: Array[String] = [
		"acc_dcc_transition_ms", "distance_strength",
		"transmission_enabled", "transmission_max_speed_volume", "transmission_pitch",
		"transmission_pitch_low_speed", "transmission_pitch_high_speed", "transmission_coast_amount",
		"shift_up_sound_volume", "shift_up_sound_pitch", "shift_down_sound_volume", "shift_down_sound_pitch",
		"supercharger_volume", "supercharger_pitch_idle", "supercharger_pitch_redline", "supercharger_coast_amount",
		"turbo_volume", "turbo_pitch", "bov_volume",
		"backfire_enabled", "backfire_volume", "backfire_strength", "backfire_pitch",
		"backfire_min_load", "backfire_cooldown", "backfire_burst_duration",
		"backfire_bang_interval", "backfire_pitch_kick"
	]
	for sound_property in applied_sound_properties:
		if preset_sound.has(sound_property) and _parent_properties.has(sound_property):
			_engine_sound_system.set(sound_property, preset_sound[sound_property])
	# Nur eigene Snapshots stellen auch Klang, Dateiauswahl und Fahrhilfen wieder
	# her. Mitgelieferte Fahrzeugtypen behalten ihr bisheriges Verhalten.
	if vehicle_presets[selected_vehicle_preset].get("custom", false):
		for property_name in _custom_vehicle_snapshot():
			if settings.has(property_name):
				set(property_name, settings[property_name])
		for property_name in _custom_sound_snapshot():
			if preset_sound.has(property_name) and _engine_sound_system.get(property_name) != preset_sound[property_name]:
				_engine_sound_system.set(property_name, preset_sound[property_name])
	number_of_gears = clampi(number_of_gears, 1, 10)
	max_rpm = maxf(max_rpm, idle_rpm + 100.0)
	reset_simulation()
	if is_instance_valid(_debug_ui):
		_debug_ui.sync_controls()
		if _debug_ui.has_method("rebuild_ui"):
			_debug_ui.rebuild_ui()
	return true

#endregion

#region Eingaben und Simulationsablauf
func _physics_process(delta: float) -> void:
	if delta <= 0.0:
		return
	if simulator_enabled and _parent_properties.has("rpm_position"):
		advance_simulation(delta, _action_strength("gastrigger"), _action_strength("braketrigger"), _action_strength("handbraketrigger"))
		# Semi-Automatik: Manuelle Trigger bleiben auch bei aktiver Gangautomatik
		# jederzeit erlaubt. Alte Action-Namen funktionieren als Fallback weiter.
		if _any_action_just_pressed([&"shiftuptrigger", &"shiftup", &"shift_up"]):
			shift_up()
		if _any_action_just_pressed([&"shiftdowntrigger", &"shiftdown", &"shift_down"]):
			shift_down()
		# Wobble separat übertragen, nie in die Audio-RPM einrechnen.
		_engine_sound_system.set("rpm_position", rpm_normalized)
		_send_wobble()
	var shown_rpm := _get_audio_rpm()
	# Keine zweite Glaettung: Dyno und Limiter lesen denselben Audiocursor.
	visual_rpm = shown_rpm
	_ui_elapsed += delta
	if _ui_elapsed >= 0.05:
		_ui_elapsed = 0.0
		_update_debug_ui()

func _action_strength(action: StringName) -> float:
	return Input.get_action_strength(action) if InputMap.has_action(action) else 0.0

func _is_engine_running() -> bool:
	if is_instance_valid(_engine_sound_system) and _parent_properties.has("engine_running"):
		return bool(_engine_sound_system.get("engine_running"))
	return true

func _any_action_just_pressed(actions: Array[StringName]) -> bool:
	for action in actions:
		if InputMap.has_action(action) and Input.is_action_just_pressed(action):
			return true
	return false

func advance_simulation(delta: float, gas: float, braking: float, parking_brake: float) -> void:
	# Deterministischer, unabhängig vom Input-System testbarer Simulationsschritt.
	if not simulator_enabled or delta <= 0.0 or not is_finite(delta):
		return
	var previous_handbrake := handbrake
	throttle = clampf(gas, 0.0, 1.0) if is_finite(gas) else 0.0
	brake = clampf(braking, 0.0, 1.0) if is_finite(braking) else 0.0
	handbrake = clampf(parking_brake, 0.0, 1.0) if is_finite(parking_brake) else 0.0
	var forward_trigger := throttle
	var reverse_trigger := brake
	# Bei Stillstand wird gehaltene Bremse zum Arcade-Rückwärtsgas. Während R
	# aktiv ist, treibt derselbe Trigger rückwärts, statt weiter zu bremsen.
	if not is_reversing and speed_kmh <= 0.5 and reverse_trigger > 0.20 and forward_trigger <= INPUT_EPSILON:
		is_reversing = true
		current_gear = 1
		_cancel_shift()
	if is_reversing:
		if forward_trigger <= INPUT_EPSILON and reverse_trigger <= INPUT_EPSILON:
			# Arcade-Automatik: Werden beide Trigger losgelassen, fällt R zurück auf
			# Gang 1. Eine vorhandene Rückwärtsbewegung wird vorher sauber abgebaut.
			is_reversing = false
			current_gear = 1
			_reverse_to_forward_active = speed_kmh > 0.2
			throttle = 0.0
			brake = 0.0
		elif forward_trigger >= 0.95:
			# Vollgas vorwärts aus R: Gang 1 sofort einlegen und erst die bestehende
			# Rückwärtsbewegung über einen hör-/sichtbaren Wheelspin abbauen.
			is_reversing = false
			current_gear = 1
			_reverse_to_forward_active = speed_kmh > 0.2
			_reverse_launch_wheelspin_timer = 0.65
			throttle = forward_trigger
			brake = 0.0
		else:
			throttle = reverse_trigger
			brake = 0.0
	_reverse_launch_wheelspin_timer = maxf(0.0, _reverse_launch_wheelspin_timer - delta)
	# Erkennt auch einen von der Fahrzeugphysik gesetzten Geschwindigkeitssprung (z.B. Wandkontakt).
	var speed_before_step := speed_kmh
	_sudden_speed_loss = _last_step_speed_kmh - speed_kmh > 5.0
	number_of_gears = clampi(number_of_gears, 1, 10)
	current_gear = clampi(current_gear, 1, number_of_gears)
	# Unter Schrittgeschwindigkeit wird nicht Gang für Gang heruntergeschaltet.
	# Die Automatik legt direkt den ersten Gang ein.
	if automatic_gears and not is_reversing and speed_kmh < 10.0 and current_gear != 1 and not is_shifting:
		current_gear = 1
		_pending_gear = 1
	if _pending_gear > number_of_gears:
		_cancel_shift()
	_downshift_lock_timer = maxf(0.0, _downshift_lock_timer - delta)
	_gear_hold_timer = maxf(0.0, _gear_hold_timer - delta)
	_launch_control_release_timer = maxf(0.0, _launch_control_release_timer - delta)
	if handbrake > INPUT_EPSILON and is_shifting:
		_cancel_shift()
	engine_power_available = _is_engine_running()
	_update_race_launch(delta, previous_handbrake)
	_update_physics_rpm(delta)
	launch_control_active = engine_power_available and launch_control_enabled and handbrake > INPUT_EPSILON and throttle >= 0.8 and speed_kmh <= 5.0 and current_gear == 1 and not is_shifting
	if _launch_control_was_active and not launch_control_active:
		# Handbremse gelöst: Die bereits anliegende Launch-RPM kontrolliert an die
		# Räder übergeben. Während dieser kurzen Einkuppelphase bleibt Gang 1 drin;
		# starke Autos schalten dadurch nicht wegen Wheelspin sofort alle Gänge hoch.
		_launch_start_rpm = rpm_normalized
		_launch_peak_rpm = rpm_normalized
		_launch_elapsed = maxf(launch_rise_time, 0.01)
		_launch_control_release_timer = maxf(launch_settle_time + 0.35, 0.35)
		_launch_armed = false
		_was_free_reving = false
	if launch_control_active and not _launch_control_was_active:
		_launch_control_phase = 0.0
	_launch_control_was_active = launch_control_active
	_update_supercharger()
	_update_turbo(delta)
	# Vor der Bewegung prüfen, damit der Start auch bei hoher Beschleunigung greift.
	if speed_kmh <= 0.5 and throttle <= INPUT_EPSILON:
		_launch_armed = true
	if engine_power_available and _launch_armed and not launch_control_active and speed_kmh <= 0.5 and current_gear == 1 and not is_shifting and throttle > INPUT_EPSILON and brake <= INPUT_EPSILON and handbrake <= INPUT_EPSILON:
		_launch_armed = false
		_launch_elapsed = 0.0
		_launch_start_rpm = rpm_normalized
		_launch_peak_rpm = maxf(rpm_normalized, clampf(launch_rpm, 0.0, 0.9) * throttle)
	if race_launch_effect_active and race_launch_status == "DURCHDREHEN":
		# Wheelspin ersetzt den normalen Anfahrablauf vollständig. Sonst würde der
		# eingefrorene Standard-Launch nach dem Schlupf weiterlaufen und die RPM
		# plötzlich auf einen alten Wert (teilweise 0) zurückziehen.
		_launch_elapsed = -1.0
		_launch_control_release_timer = 0.0
		_launch_armed = false
	_update_speed(delta)
	_update_acceleration_times(delta, speed_before_step)
	var shift_was_active := is_shifting
	_update_shift(delta)
	_update_rpm(delta)
	_apply_artificial_idle(delta)
	_apply_artificial_rpm_limiter()
	_update_wobble_input(shift_was_active)
	_update_automatic_gears()
	_update_wobble(delta)
	_last_step_speed_kmh = speed_kmh

func _update_physics_rpm(delta: float) -> void:
	if not engine_power_available:
		physics_rpm = 0.0
		_physics_launch_remaining = 0.0
		_physics_launch_armed = true
		return
	var wheel_target := _wheel_rpm(current_gear)
	if throttle <= INPUT_EPSILON and speed_kmh < 0.5:
		_physics_launch_armed = true
	if handbrake > INPUT_EPSILON:
		_physics_launch_armed = true
		_physics_launch_remaining = 0.0
		var target := maxf(wheel_target, throttle)
		if launch_control_enabled and throttle >= 0.8 and speed_kmh <= 5.0:
			target = normalized_from_actual_rpm(launch_control_rpm)
		var rate := handbrake_rev_speed if target > physics_rpm else free_rev_fall_speed
		if target < physics_rpm:
			var window := _get_effective_race_launch_window()
			var actual := calculate_actual_rpm(physics_rpm)
			if actual >= window.x - maxf((max_rpm - idle_rpm) * 0.10, 250.0) and actual <= window.y:
				rate *= _get_free_rev_fall_difficulty_factor()
		physics_rpm = move_toward(physics_rpm, target, maxf(rate, 0.01) * delta)
		return
	if _physics_launch_armed and speed_kmh <= 0.5 and throttle > INPUT_EPSILON and brake <= INPUT_EPSILON and current_gear == 1:
		_physics_launch_armed = false
		_physics_launch_peak = maxf(physics_rpm, launch_rpm * throttle)
		_physics_launch_remaining = maxf(launch_rise_time + launch_settle_time, 0.01)
	if is_shifting or brake > INPUT_EPSILON or current_gear != 1 or throttle <= INPUT_EPSILON:
		_physics_launch_remaining = 0.0
	physics_rpm = wheel_target
	if _physics_launch_remaining > 0.0:
		_physics_launch_remaining = maxf(0.0, _physics_launch_remaining - delta)
		var coupling := _physics_launch_remaining / maxf(launch_rise_time + launch_settle_time, 0.01)
		physics_rpm = maxf(wheel_target, lerpf(wheel_target, _physics_launch_peak, coupling))
	# Schlupf darf die physikalische Drehzahl anheben, aber nicht mit einem
	# Audio-/Free-Rev-Regler. Die Resttraktion stammt aus dem vorigen Physikschritt.
	if not is_shifting and not downshift_wheel_lock and throttle > INPUT_EPSILON:
		physics_rpm = maxf(physics_rpm, lerpf(wheel_target, throttle, clampf(wheelspin, 0.0, 1.0)))
	physics_rpm = clampf(physics_rpm, 0.0, 1.0)

#endregion

#region Zeitmessung, Rennstart und Schwierigkeit
func _update_acceleration_times(delta: float, speed_before: float) -> void:
	if is_reversing or _reverse_to_forward_active:
		return
	# Neuer Lauf wird erst beim tatsächlichen Losrollen gestartet.
	if _acceleration_run_time < 0.0:
		if speed_before <= 0.1 and speed_kmh > 0.1:
			_acceleration_run_time = 0.0
			acceleration_time_0_100 = -1.0
			acceleration_time_100_200 = -1.0
			_time_at_100 = -1.0
		else:
			return
	var time_before := _acceleration_run_time
	_acceleration_run_time += delta
	var speed_change := speed_kmh - speed_before
	if acceleration_time_0_100 < 0.0 and speed_before < 100.0 and speed_kmh >= 100.0:
		var fraction := clampf((100.0 - speed_before) / maxf(speed_change, 0.0001), 0.0, 1.0)
		_time_at_100 = time_before + delta * fraction
		acceleration_time_0_100 = _time_at_100
	if acceleration_time_100_200 < 0.0 and _time_at_100 >= 0.0 and speed_before < 200.0 and speed_kmh >= 200.0:
		var fraction := clampf((200.0 - speed_before) / maxf(speed_change, 0.0001), 0.0, 1.0)
		acceleration_time_100_200 = time_before + delta * fraction - _time_at_100
	# Nach dem Ausrollen ist der nächste Start automatisch ein neuer Messlauf.
	if speed_kmh <= 0.1 and throttle <= INPUT_EPSILON:
		_acceleration_run_time = -1.0
		_time_at_100 = -1.0
		acceleration_time_0_100 = -1.0
		acceleration_time_100_200 = -1.0

func _format_acceleration_time(value: float, threshold: float) -> String:
	if value >= 0.0:
		return "%.2f s" % value
	if _acceleration_run_time >= 0.0 and speed_kmh < threshold:
		return "läuft ..."
	return "--"

func _classify_race_launch(actual_rpm: float) -> String:
	var window := _get_effective_race_launch_window()
	var perfect_from := window.x
	var perfect_to := window.y
	# Exakt dieselbe untere blaue Grenze wie die Dyno-Leiste. Darunter ist nicht
	# mehr automatisch "GUT", sondern ein eigener zu niedriger/boggender Start.
	var good_tolerance := maxf((max_rpm - idle_rpm) * 0.10, 250.0)
	var good_from := maxf(idle_rpm, perfect_from - good_tolerance)
	if actual_rpm >= perfect_from and actual_rpm <= perfect_to:
		return "PERFEKT"
	if actual_rpm >= good_from and actual_rpm < perfect_from:
		return "GUT"
	return "ZU_WENIG" if actual_rpm < good_from else "DURCHDREHEN"

func _get_effective_race_launch_window() -> Vector2:
	if progressive_shift_difficulty:
		# Ein gemeinsamer Schwierigkeitsregler für Start und Schalten. Die Mitte
		# liegt relativ im nutzbaren RPM-Bereich und passt damit automatisch zu
		# jedem Motor; 0 ist breit/leicht, 1 deutlich schmaler/schwer.
		var usable_rpm := maxf(max_rpm - idle_rpm, 100.0)
		var center_rpm := idle_rpm + usable_rpm * 0.76
		var window_width := usable_rpm * lerpf(0.30, 0.08, clampf(shift_difficulty, 0.0, 1.0))
		var automatic_from := clampf(center_rpm - window_width * 0.5, idle_rpm, max_rpm)
		var automatic_to := clampf(center_rpm + window_width * 0.5, automatic_from, max_rpm)
		return Vector2(automatic_from, automatic_to)
	var perfect_from := clampf(minf(race_launch_perfect_from_rpm, race_launch_perfect_to_rpm), idle_rpm, max_rpm)
	var perfect_to := clampf(maxf(race_launch_perfect_from_rpm, race_launch_perfect_to_rpm), perfect_from, max_rpm)
	# Ein vollständig außerhalb liegendes oder zusammengequetschtes Fenster kann
	# bei kleineren Motoren nie getroffen werden. Dann relativ zur Redline retten.
	var minimum_width := maxf((max_rpm - idle_rpm) * 0.08, 100.0)
	if perfect_from >= max_rpm * 0.96 or perfect_to - perfect_from < minimum_width:
		perfect_from = lerpf(idle_rpm, max_rpm, 0.62)
		perfect_to = lerpf(idle_rpm, max_rpm, 0.86)
	return Vector2(perfect_from, perfect_to)

func _get_free_rev_fall_difficulty_factor() -> float:
	# Linear war die Hilfe bei mittleren Werten kaum wahrnehmbar. Die kubische
	# Kurve behaelt klare Endpunkte: 0 = maximale Hilfe, 1 = keine Hilfe.
	return pow(clampf(free_rev_fall_difficulty, 0.0, 1.0), 3.0)

func _race_launch_spin_factor() -> float:
	# Schwache Autos drehen ebenfalls kurz durch, erreichen aber wesentlich früher
	# wieder Grip. Starke Fahrzeuge nutzen bis zur vollen eingestellten Strecke.
	var effective_end_speed := race_launch_wheelspin_end_speed_kmh * lerpf(0.35, 1.0, clampf(_race_launch_spin_severity, 0.0, 1.0))
	return clampf(1.0 - speed_kmh / maxf(effective_end_speed, 1.0), 0.0, 1.0)

func _update_race_launch(delta: float, previous_handbrake: float) -> void:
	# Ein schlechter Start endet geschwindigkeitsabhängig statt nach einer starren
	# Zeit: Gas halten lässt den Schlupf bis zur eingestellten km/h-Grenze ausfaden.
	if _race_launch_effect_timer > 0.0 and race_launch_status == "DURCHDREHEN":
		if throttle <= INPUT_EPSILON or _race_launch_spin_factor() <= 0.0:
			_race_launch_effect_timer = 0.0
	else:
		_race_launch_effect_timer = maxf(0.0, _race_launch_effect_timer - delta)
	race_launch_effect_active = _race_launch_effect_timer > 0.0
	if not race_launch_effect_active:
		_race_launch_power_factor = 1.0
		_race_launch_traction_factor = 1.0
	var was_staging := race_launch_staging
	race_launch_staging = race_launch_enabled and engine_power_available and current_gear == 1 and speed_kmh < 5.0 and handbrake > INPUT_EPSILON and not is_shifting
	if race_launch_staging:
		var actual_audio_rpm := calculate_actual_rpm(physics_rpm)
		# Die Startbewertung folgt der Motorphysik; Audio-Cuts sperren sie nicht.
		var judged_rpm := actual_audio_rpm
		race_launch_status = _classify_race_launch(judged_rpm)
		return
	var released := previous_handbrake > INPUT_EPSILON and handbrake <= INPUT_EPSILON
	if race_launch_enabled and engine_power_available and released and was_staging and current_gear == 1 and speed_kmh < 5.0 and throttle > INPUT_EPSILON:
		# Entscheidend ist ausschließlich der Moment, in dem die Handbremse gelöst
		# wird. Liegt die physikalische Drehzahl beim Loslassen im grünen
		# Fenster, ist es für jedes Fahrzeug wieder ein perfekter Start.
		var release_rpm := calculate_actual_rpm(physics_rpm)
		race_launch_status = _classify_race_launch(release_rpm)
		var perfect_to := _get_effective_race_launch_window().y
		var rpm_excess := clampf(inverse_lerp(perfect_to, maxf(max_rpm, perfect_to + 1.0), release_rpm), 0.0, 1.0)
		var power_per_ton := _get_peak_horsepower() * 1000.0 / maxf(vehicle_mass_kg, 1.0)
		var power_severity := smoothstep(45.0, 500.0, power_per_ton)
		# Selbst ein schwaches Auto kann bei zu hoher RPM kurz Schlupf haben.
		_race_launch_spin_severity = clampf(0.12 + power_severity * 0.58 + rpm_excess * 0.30, 0.12, 1.0)
		_race_launch_spin_hold_rpm = normalized_from_actual_rpm(release_rpm)
		_engine_struggle_phase = 0.0
		# Wheelspin benutzt den Timer nur als Aktiv-Markierung und endet allein
		# über Gas oder km/h. Gute/perfekte Starts behalten einen kurzen Bonus.
		_race_launch_effect_timer = 1.0 if race_launch_status == "DURCHDREHEN" else maxf(race_launch_bonus_duration, 0.2)
		race_launch_effect_active = true
		match race_launch_status:
			"PERFEKT":
				_race_launch_power_factor = 1.12
				# Ein perfekter Start dosiert bei extremem Leistungsgewicht vor allem
				# die Traktion. F1/Drag erhalten deshalb mehr Grip-Hilfe als ein
				# normaler Kleinwagen, statt trotz Grün noch Gang 1–2 durchzudrehen.
				var perfect_power_per_ton := _get_peak_horsepower() * 1000.0 / maxf(vehicle_mass_kg, 1.0)
				_race_launch_traction_factor = lerpf(1.25, 1.75, smoothstep(220.0, 900.0, perfect_power_per_ton))
			"GUT":
				# Ein guter Start ist wirklich ein kleiner Bonus und keine versteckte
				# Leistungsstrafe. Perfekt bleibt deutlich stärker spürbar.
				_race_launch_power_factor = 1.03
				_race_launch_traction_factor = 1.05
			"ZU_WENIG":
				# Zu niedrige Start-RPM lässt den Motor kurz einbrechen/boggen.
				_race_launch_power_factor = 0.82
				_race_launch_traction_factor = 1.0
			"DURCHDREHEN":
				_race_launch_power_factor = 1.0
				_race_launch_traction_factor = lerpf(0.88, 0.45, _race_launch_spin_severity)
	elif not race_launch_effect_active:
		race_launch_status = "BEREIT"

#endregion

#region Vortrieb, Bremsen und Traktionskontrolle
func _update_speed(delta: float) -> void:
	var safe_gear_speed := _downshift_lock_target_speed if downshift_wheel_lock else _get_gear_limited_speed(current_gear) * 0.92
	if downshift_wheel_lock and speed_kmh <= safe_gear_speed + 0.05:
		# Radblock nach passendem Tempo und physikalischer Motordrehzahl freigeben;
		# ein langsamer Audiocursor darf das Fahrzeug nicht weiter abbremsen.
		var gear_audio_target := _wheel_rpm(current_gear)
		var actual_audio_rpm := physics_rpm
		if actual_audio_rpm < 0.98 and absf(actual_audio_rpm - gear_audio_target) <= 0.05:
			downshift_wheel_lock = false
			_downshift_grip_recovery = 0.0
			_downshift_lock_target_speed = 0.0
	if not downshift_wheel_lock and not is_reversing:
		_downshift_grip_recovery = move_toward(_downshift_grip_recovery, 1.0, delta / maxf(downshift_grip_recovery_time, 0.01))
	var drive := throttle * _downshift_grip_recovery if engine_power_available and not is_shifting and not downshift_wheel_lock and handbrake <= INPUT_EPSILON else 0.0
	var effective_max_speed := _get_max_speed_kmh()
	var speed_fraction := clampf(speed_kmh / effective_max_speed, 0.0, 1.0)
	# Leistung wird über P/(m*v) in Beschleunigung übersetzt. Die interne Kennlinie
	# ersetzt die editierbare Torque Curve und reagiert automatisch auf Gang/RPM.
	var speed_mps := maxf(speed_kmh / 3.6, 8.0)
	var engine_output := _automatic_engine_output(physics_rpm)
	var launch_assist := _launch_control_release_timer > 0.0 and current_gear == 1
	if launch_assist:
		var launch_normalized := normalized_from_actual_rpm(clampf(launch_control_rpm, idle_rpm, max_rpm))
		engine_output = maxf(engine_output, _automatic_engine_output(launch_normalized))
	var demanded_acceleration := _get_effective_horsepower() * HP_TO_WATTS * DRIVETRAIN_EFFICIENCY * engine_output * _race_launch_power_factor / (maxf(vehicle_mass_kg, 1.0) * speed_mps) * 3.6
	# Die Übersetzung reduziert zuerst die angeforderte Radkraft. Erst danach wird
	# geprüft, ob diese Kraft die Reifenhaftung überschreitet. So bleiben 800 PS
	# auch im vierten Gang stärker als ein schwacher Motor.
	var launch_gear_factor := pow(clampf(gear_rpm_drop, 0.5, 0.9), current_gear - 1) if _physics_launch_remaining > 0.0 else 1.0
	var geared_acceleration := demanded_acceleration * launch_gear_factor
	# Automatischer Wheelspin: Überschüssiger Vortrieb erhöht RPM/Klang, nicht Tempo.
	# Mit Tempo und höheren Gängen wird die übertragbare Leistung stabiler
	# (Reifengeschwindigkeit, Übersetzung und bei Rennwagen aerodynamischer Grip).
	# Dadurch darf ein F1 am Start/noch im zweiten Gang schlupfen, aber nicht bei
	# jedem weiteren Hochschalten dauerhaft die Reifen quietschen lassen.
	var gear_progress := float(current_gear - 1) / float(maxi(number_of_gears - 1, 1))
	var speed_grip := lerpf(1.0, 2.65, pow(speed_fraction, 1.15))
	var gear_grip := lerpf(1.0, 1.35, gear_progress)
	var traction_limit := TRACTION_LIMIT_KMH_S * speed_grip * gear_grip
	var tc_strength := clampf(traction_control_strength, 0.0, 1.0) if traction_control_enabled else 0.0
	if tc_strength <= 0.0 or drive <= INPUT_EPSILON:
		_tc_recovery = 0.0
	# TC kann verlorene Start-Haftung zurückgewinnen, aber niemals über normalen
	# Grip hinaus erhöhen. Die separate Perfekt-Start-Hilfe bleibt erhalten.
	var launch_grip := _race_launch_traction_factor
	if race_launch_effect_active and race_launch_status == "DURCHDREHEN":
		launch_grip = lerpf(launch_grip, 1.0, _tc_recovery)
	traction_limit *= launch_grip
	if launch_assist:
		traction_limit *= 1.15
	# Analoges Gas muss VOR der Haftungsprüfung in die Radkraft eingehen. Zuvor
	# wurde selbst bei 10 % Triggerweg die volle F1-Leistung gegen die Reifen
	# geprüft und erst das fertige Wheelspin-Signal nachträglich leiser skaliert.
	var requested_acceleration := geared_acceleration * drive
	var raw_slip := clampf(1.0 - traction_limit / maxf(requested_acceleration, 0.001), 0.0, 1.0) if drive > INPUT_EPSILON else 0.0
	var launch_spin := _race_launch_spin_factor() if race_launch_effect_active and race_launch_status == "DURCHDREHEN" else 0.0
	# Auch der absichtlich schlechte Start muss VOR der TC in denselben Schlupf
	# eingehen. Sonst würde er die Regelung direkt danach wieder überschreiben.
	raw_slip = maxf(raw_slip, lerpf(0.18, 0.75, _race_launch_spin_severity) * launch_spin * drive)
	# Der reine Leistungsüberschuss konnte bei extremen Rennwagen den normalen
	# raw_slip dauerhaft hoch halten, obwohl der geschwindigkeitsabhängige
	# Launch-Wheelspin bereits ausgeblendet war. Derselbe km/h-Bereich begrenzt
	# deshalb auch den gesamten Startschlupf. Höhere Gänge reduzieren ihn früher.
	var wheelspin_end_speed := maxf(race_launch_wheelspin_end_speed_kmh, 5.0)
	var wheelspin_speed_envelope := 1.0 - smoothstep(wheelspin_end_speed * 0.15, wheelspin_end_speed, speed_kmh)
	var wheelspin_gear_envelope := lerpf(1.0, 0.18, smoothstep(0.0, 0.35, gear_progress))
	raw_slip = minf(raw_slip, wheelspin_speed_envelope * wheelspin_gear_envelope)
	traction_control_active = tc_strength > 0.0 and drive > INPUT_EPSILON and raw_slip > 0.025 and not downshift_wheel_lock and handbrake <= INPUT_EPSILON
	if traction_control_active:
		_tc_phase = fmod(_tc_phase + delta * 8.0, 1.0)
		_tc_pulse = 0.5 - 0.5 * cos(_tc_phase * TAU)
		_tc_recovery = move_toward(_tc_recovery, tc_strength, delta * 3.0 * tc_strength)
		var control := _tc_recovery * lerpf(0.88, 1.0, _tc_pulse)
		# Sanfte 8-Hz-Schnitte um die Haftungsgrenze, kein dauerhaftes Gas-Aus.
		var controlled_request := minf(requested_acceleration, traction_limit * lerpf(1.0, 0.92, _tc_pulse))
		requested_acceleration = lerpf(requested_acceleration, controlled_request, control)
		wheelspin = raw_slip * (1.0 - control)
	else:
		_tc_phase = 0.0
		_tc_pulse = 0.0
		_tc_recovery = move_toward(_tc_recovery, 0.0, delta * 4.0)
		wheelspin = raw_slip
	traction = 1.0 - wheelspin
	if _reverse_launch_wheelspin_timer > 0.0 and throttle >= 0.95:
		# Richtungswechsel unter Vollgas garantiert kurz Schlupf, unabhängig von
		# Leistung oder aktiver Traktionskontrolle.
		wheelspin = maxf(wheelspin, 0.78)
		traction = minf(traction, 0.22)
	var aero_reserve := clampf(1.0 - 0.55 * calculate_air_resistance() * speed_fraction * speed_fraction, 0.2, 1.0)
	var available_acceleration := minf(requested_acceleration, traction_limit) * aero_reserve
	# Ohne TC vernichtet überschüssiger Schlupf tatsächlich Vortrieb. Die Anzeige
	# und das Reifengeräusch verwenden denselben verbleibenden Wheelspin-Wert.
	available_acceleration *= lerpf(1.0, 0.55, wheelspin)
	if race_launch_effect_active and race_launch_status == "DURCHDREHEN":
		# Beim Burnout wird die Motorleistung hauptsächlich in Raddrehzahl und
		# Reifenschlupf umgesetzt. Nur ein kleiner Rest beschleunigt das Fahrzeug.
		available_acceleration *= lerpf(0.18, 1.0, 1.0 - launch_spin * (1.0 - _tc_recovery))
	# Handbremse entkoppelt hier den Antrieb wie ein neutraler Gang und bremst nur leicht.
	var change: float
	if _reverse_to_forward_active:
		var powered_direction_change := throttle >= 0.95
		traction = 0.18 if powered_direction_change else 1.0
		wheelspin = 0.82 if powered_direction_change else 0.0
		# Ohne Gegen-Gas ganz normal ausrollen wie in Gang 1. Nur ein bewusster
		# Vollgas-Richtungswechsel baut die Rückwärtsbewegung hart ab.
		change = -maxf(brake_strength * 0.75, 55.0) if powered_direction_change else -coast_deceleration
		if speed_kmh <= 0.5:
			_reverse_to_forward_active = false
	elif downshift_wheel_lock:
		# Zu tiefer manueller Gang: Antriebsräder blockieren/schleifen und bauen
		# Geschwindigkeit ab, bis Radtempo und maximal erlaubte Gang-RPM passen.
		traction = 0.0
		# Radblock ist negativer Schlupf, kein Wheelspin unter Motorleistung.
		wheelspin = 0.0
		# Bis zur ganggerechten Geschwindigkeit hart blockieren. Danach Tempo
		# nur halten/ausrollen lassen, bis die nachlaufende Audio-RPM aufgeholt hat.
		change = -maxf(downshift_wheel_lock_strength, brake_strength) if speed_kmh > safe_gear_speed else -brake_strength * brake
	elif handbrake > INPUT_EPSILON:
		traction = 1.0
		wheelspin = 0.0
		change = -handbrake_deceleration * handbrake - brake_strength * brake
	else:
		# `available_acceleration` enthält die analoge Gasstellung bereits.
		change = available_acceleration - coast_deceleration * (1.0 - drive)
		change -= brake_strength * brake
	var speed_ceiling := effective_max_speed
	if is_reversing:
		speed_ceiling = minf(speed_ceiling, _get_reverse_max_speed_kmh())
	if not downshift_wheel_lock and not is_reversing:
		# Im festen manuellen Gang endet der Vortrieb an dessen Übersetzung.
		# Der Limiter hält RPM und Fahrzeugtempo dort, bis hochgeschaltet wird.
		speed_ceiling = minf(speed_ceiling, _get_gear_limited_speed(current_gear))
	speed_kmh = clampf(speed_kmh + change * delta, 0.0, speed_ceiling)
	if _reverse_to_forward_active and speed_kmh <= 0.5:
		speed_kmh = 0.0
		_reverse_to_forward_active = false

#endregion

#region Motorkurve, Aufladung und Dyno
func _automatic_engine_output(normalized_rpm: float) -> float:
	# Aus fester Drehmomentform entsteht eine echte Leistungskurve P = M * RPM.
	var value := clampf(normalized_rpm, 0.0, 1.0)
	var actual_ratio := calculate_actual_rpm(value) / maxf(max_rpm, 1.0)
	return clampf(actual_ratio * _automatic_torque_shape(value) / 0.86, 0.0, 1.0)

func _update_supercharger() -> void:
	# Mechanisch gekoppelt an die Physik, niemals an die Audiopuffer-Position.
	supercharger_boost = _get_supercharger_factor(physics_rpm) if engine_power_available and supercharger_enabled else 0.0

func _get_supercharger_factor(normalized_audio_rpm: float) -> float:
	return smoothstep(0.0, 1.0, clampf(normalized_audio_rpm, 0.0, 1.0))

func _update_turbo(delta: float) -> void:
	if not engine_power_available or not turbo_enabled:
		turbo_boost = move_toward(turbo_boost, 0.0, maxf(turbo_spool_down_speed, 0.1) * delta)
		return
	var rpm_spool := smoothstep(clampf(turbo_spool_start_rpm, 0.0, 0.95), 1.0, physics_rpm)
	var effective_gas := 0.0 if is_shifting else throttle
	# Zieldruck und Aufbau folgen nur Gas, Physik-RPM und Spool-Einstellung.
	var target := clampf(effective_gas * rpm_spool, 0.0, 1.0)
	# Kleine negative Dist-Schwankungen entstehen auch beim Einregeln nahe Vmax.
	# Solange Gas und RPM anliegen, darf das den Boost nicht zyklisch wegwerfen.
	# Echte Gaswegnahme und Shift setzen target bereits zuverlässig auf null.
	var pressure_gap := clampf((target - turbo_boost) / maxf(turbo_full_boost_audio_dist, 0.001), 0.0, 1.0)
	var rise_rate := turbo_spool_up_speed * lerpf(0.35, 1.0, pressure_gap)
	var rate := rise_rate if target > turbo_boost else turbo_spool_down_speed
	turbo_boost = move_toward(turbo_boost, target, maxf(rate, 0.1) * delta)

func calculate_actual_rpm(normalized_rpm: float) -> float:
	return lerpf(clampf(idle_rpm, 0.0, maxf(max_rpm, 1.0)), maxf(max_rpm, 1.0), clampf(normalized_rpm, 0.0, 1.0))

func normalized_from_actual_rpm(actual_rpm: float) -> float:
	return clampf((actual_rpm - idle_rpm) / maxf(max_rpm - idle_rpm, 1.0), 0.0, 1.0)

func _automatic_torque_shape(normalized_rpm: float) -> float:
	# Universelle Arcade-Kennlinie: Drehmoment steigt sanft und fällt vor Redline.
	var value := clampf(normalized_rpm, 0.0, 1.0)
	var rise := lerpf(0.52, 1.0, smoothstep(0.08, 0.62, value))
	var redline_fall := lerpf(1.0, 0.82, smoothstep(0.86, 1.0, value))
	var base := rise * redline_fall
	var roughness := (1.0 - clampf(engine_smoothness, 0.0, 1.0)) * 0.18
	var phase := float(engine_character) * 1.731
	var uneven := sin(value * TAU * 2.7 + phase) * 0.55 + sin(value * TAU * 6.2 + phase * 0.37) * 0.30 + sin(value * TAU * 11.0 + phase * 0.71) * 0.15
	# An den Rändern abschwächen, damit Start und Redline stabil bleiben.
	var envelope := sin(clampf(value, 0.0, 1.0) * PI)
	return clampf(base * (1.0 + uneven * roughness * envelope), 0.05, 1.1)

func _get_nm_curve_struggle(normalized_rpm: float) -> float:
	# Liest die lokale Steigung der tatsächlich verwendeten Nm-Kurve. Positive
	# Steigung bleibt ruhig; Plateau und Einbruch liefern zunehmend Struggle.
	# Motorglätte ist der direkte Gegenspieler: bei 100 % darf selbst an der
	# natürlichen Drehmomentspitze kein künstliches Kämpfen mehr entstehen.
	var rpm := clampf(normalized_rpm, 0.0, 1.0)
	var curve_step := 0.025
	var torque_now := _automatic_torque_shape(rpm)
	var torque_ahead := _automatic_torque_shape(minf(rpm + curve_step, 1.0))
	var torque_gain := torque_ahead - torque_now
	var sensitivity := clampf(engine_struggle_curve_sensitivity, 0.0, 1.0)
	var plateau_threshold := lerpf(-0.004, 0.014, sensitivity)
	var raw_curve_struggle := clampf((plateau_threshold - torque_gain) / 0.035, 0.0, 1.0)
	var roughness_factor := 1.0 - clampf(engine_smoothness, 0.0, 1.0)
	return raw_curve_struggle * roughness_factor

func _get_load_struggle_rpm_fade(normalized_audio_rpm: float) -> float:
	return 1.0 - smoothstep(0.55, 1.0, clampf(normalized_audio_rpm, 0.0, 1.0))

func _get_load_struggle_gear_factor(normalized_audio_rpm: float) -> float:
	var gear_progress := clampf(float(current_gear - 1) / float(maxi(number_of_gears - 1, 1)), 0.0, 1.0)
	# Untertourig bleibt der bisherige Lastfaktor erhalten. Ab 20 % Audio-RPM
	# weich zur Gang-Beruhigung wechseln; ab 50 % gilt diese vollstaendig.
	var low_rpm_load := lerpf(0.55, 1.0, gear_progress)
	var settled_gear_load := lerpf(1.0, 0.35, gear_progress)
	return lerpf(low_rpm_load, settled_gear_load, smoothstep(0.2, 0.5, normalized_audio_rpm))

func calculate_power_ps(normalized_rpm: float) -> float:
	return _get_effective_horsepower_for_rpm(normalized_rpm) * _automatic_engine_output(normalized_rpm)

func calculate_torque_nm(normalized_rpm: float) -> float:
	var omega_at_max := maxf(max_rpm, 1.0) * TAU / 60.0
	var peak_torque_scale := _get_effective_horsepower_for_rpm(normalized_rpm) * HP_TO_WATTS / (omega_at_max * 0.86)
	return peak_torque_scale * _automatic_torque_shape(normalized_rpm)

func get_dyno_display_scales() -> Vector3:
	## x = RPM, y = PS, z = Nm. Die Skala benutzt immer das vollständig
	## aufgebaute Turbo-/Supercharger-Potenzial. Live-Boost darf sie nie bewegen.
	if not automatic_dyno_scale:
		return Vector3(maxf(dyno_max_rpm, 1.0), maxf(dyno_max_power_ps, 1.0), maxf(dyno_max_torque_nm, 1.0))
	var peak_ps := 0.0
	var peak_nm := 0.0
	var configured_peak_horsepower := _get_peak_horsepower()
	var omega_at_max := maxf(max_rpm, 1.0) * TAU / 60.0
	var configured_peak_torque := configured_peak_horsepower * HP_TO_WATTS / (omega_at_max * 0.86)
	for index in range(65):
		var normalized := float(index) / 64.0
		peak_ps = maxf(peak_ps, configured_peak_horsepower * _automatic_engine_output(normalized))
		peak_nm = maxf(peak_nm, configured_peak_torque * _automatic_torque_shape(normalized))
	var air := 1.0 + clampf(dyno_scale_headroom, 0.0, 0.5)
	var rpm_scale := _round_dyno_scale(max_rpm * air, 1000.0, 2000.0)
	var ps_target := peak_ps * air
	var nm_target := peak_nm * air
	return Vector3(
		rpm_scale,
		_round_dyno_scale(ps_target, _nice_dyno_step(ps_target), 100.0),
		_round_dyno_scale(nm_target, _nice_dyno_step(nm_target), 100.0)
	)

func _nice_dyno_step(value: float) -> float:
	if value <= 250.0:
		return 50.0
	if value <= 750.0:
		return 100.0
	if value <= 1500.0:
		return 200.0
	return 500.0

func _round_dyno_scale(value: float, step_value: float, minimum: float) -> float:
	var safe_step := maxf(step_value, 1.0)
	return maxf(minimum, ceil(value / safe_step) * safe_step)

func _get_dyno_visual_rpm() -> float:
	# Fahrleistung und Timing beziehen sich auf dieselbe physikalische Drehzahl.
	# Der nachlaufende Audiocursor bleibt separat in der Debug-Anzeige sichtbar.
	return clampf(physics_rpm if simulator_enabled else visual_rpm, 0.0, 1.0)

#endregion

#region Vmax und Getriebeuebersetzung
func calculate_vmax() -> float:
	# Bewusst eine kalibrierte Arcade-Formel, keine physikalische Aero-Simulation.
	# Vmax darf nicht vom momentan schwankenden Boost abhängen, sonst entsteht
	# eine Rückkopplung aus Boost -> Vmax -> RPM/Dist -> Boost. Hier zählt die
	# stabile konfigurierbare Spitzenleistung; nur der Vortrieb nutzt Live-Boost.
	var effective_ps := maxf(_get_peak_horsepower(), 1.0) * (10000.0 + maxf(max_rpm, 0.0) * 0.15) / (1234.0 * PI)
	var exponent := 1.06 / PI
	# Masse wirkt absichtlich nur schwach auf Vmax: stark auf Beschleunigung, aber
	# ohne separates Aero-Modell nur als Arcade-Ersatz für sehr leichte Fahrzeuge.
	var mass_factor := 1.0 / calculate_air_resistance()
	var vmax := (23.0 + float(clampi(number_of_gears, 1, 10))) * pow(effective_ps, exponent) * mass_factor
	return clampf(snappedf(vmax, 1.0), 20.0, 500.0)

func _get_effective_horsepower() -> float:
	return _get_effective_horsepower_for_rpm(physics_rpm)

func _get_effective_horsepower_for_rpm(_normalized_audio_rpm: float) -> float:
	var result := maxf(horsepower, 0.0)
	if supercharger_enabled:
		# Dyno und Live-Werte zeigen nur den momentan durch die Physik-RPM
		# aufgebauten Kompressoranteil, nicht vorab das Redline-Potenzial.
		result += maxf(supercharger_power_ps, 0.0) * clampf(supercharger_boost, 0.0, 1.0)
	if turbo_enabled:
		result += maxf(turbo_power_ps, 0.0) * clampf(turbo_boost, 0.0, 1.0)
	return result

func _get_peak_horsepower() -> float:
	var result := maxf(horsepower, 0.0)
	if supercharger_enabled:
		result += maxf(supercharger_power_ps, 0.0)
	if turbo_enabled:
		result += maxf(turbo_power_ps, 0.0)
	return result

func calculate_air_resistance() -> float:
	# Arcade-Näherung: 1500 kg = 1.0, leicht = kompakter, schwer = größer.
	# Der kleine Exponent verhindert extreme Ergebnisse bei Motorrädern/LKWs.
	return clampf(pow(maxf(vehicle_mass_kg, 1.0) / 1500.0, 0.11), 0.7, 1.35)

func _get_max_speed_kmh() -> float:
	return calculate_vmax() if automatic_max_speed else maxf(max_speed_kmh, 1.0)

func _wheel_rpm(gear: int) -> float:
	return clampf(speed_kmh / _get_gear_max_speed(gear), 0.0, 1.0)

func _get_gear_max_speed(gear: int) -> float:
	# Geometrische Staffelung ergibt in jedem Gang denselben einstellbaren RPM-Abfall.
	var index := clampi(gear, 1, number_of_gears)
	return maxf(1.0, _get_max_speed_kmh() * pow(clampf(gear_rpm_drop, 0.5, 0.9), number_of_gears - index))

func _get_reverse_max_speed_kmh() -> float:
	# R verwendet dieselbe Arcade-Übersetzung und Endgeschwindigkeit wie Gang 1.
	return _get_gear_max_speed(1)

func _get_gear_limited_speed(gear: int) -> float:
	var rpm_limit := _get_artificial_limiter_trigger_normalized() if artificial_rpm_limiter_enabled else 1.0
	return _get_gear_max_speed(gear) * rpm_limit

#endregion

#region Idle, RPM-Begrenzer und Schaltfenster
func _get_artificial_limiter_trigger_normalized() -> float:
	return normalized_from_actual_rpm(_get_artificial_limiter_trigger_rpm())

func _get_artificial_limiter_trigger_rpm() -> float:
	return maxf(idle_rpm, max_rpm)

func _get_artificial_limiter_drop_normalized() -> float:
	var trigger_rpm := _get_artificial_limiter_trigger_rpm()
	var drop_amount := clampf(artificial_rpm_limiter_drop_amount_rpm, 5.0, 5000.0)
	var automatic_drop_rpm := maxf(idle_rpm, trigger_rpm - drop_amount)
	return normalized_from_actual_rpm(minf(automatic_drop_rpm, trigger_rpm))

func _apply_artificial_idle(delta: float) -> void:
	var has_real_idle := false
	if is_instance_valid(_engine_sound_system) and _engine_sound_system.has_method("has_idle_wav"):
		has_real_idle = bool(_engine_sound_system.call("has_idle_wav"))
	var idle_active := artificial_idle_enabled and not has_real_idle and engine_power_available \
		and speed_kmh <= 0.5 and throttle <= INPUT_EPSILON and not is_shifting \
		and not is_reversing and not _reverse_to_forward_active and _engine_start_rev_elapsed < 0.0
	if not idle_active:
		_artificial_idle_phase = 0.0
		return
	# Weicher 0..1-Puls oberhalb der echten Idle-RPM. Keine negative Position und
	# kein Seek: ACC/DCC folgt wie beim Limiter ausschließlich über seine Distanz.
	_artificial_idle_phase = fmod(_artificial_idle_phase + delta * maxf(artificial_idle_pulse_speed, 0.1), 1.0)
	var pulse := 0.5 - 0.5 * cos(_artificial_idle_phase * TAU)
	var pulse_range := clampf(artificial_idle_pulse_rpm / maxf(max_rpm - idle_rpm, 1.0), 0.0, 0.25)
	rpm_normalized = maxf(rpm_normalized, pulse * pulse_range)

func get_effective_upshift_rpm() -> float:
	var threshold := _calculate_perfect_upshift_rpm() if automatic_perfect_shift else clampf(upshift_rpm, 0.5, 0.99)
	if automatic_gears:
		# Straßenautos schalten unter Volllast merklich vor dem Begrenzer;
		# leichte/starke Rennfahrzeuge dürfen die Leistung weiter ausdrehen.
		var power_per_ton := _get_peak_horsepower() * 1000.0 / maxf(vehicle_mass_kg, 1.0)
		var vehicle_performance := smoothstep(70.0, 650.0, power_per_ton)
		var road_shift_cap := lerpf(0.84, 0.975, vehicle_performance)
		threshold = minf(threshold, road_shift_cap)
	if artificial_rpm_limiter_enabled:
		threshold = minf(threshold, maxf(_get_artificial_limiter_trigger_normalized() - 0.01, 0.0))
	return threshold

func get_perfect_shift_window_width() -> float:
	# Dieses Fenster betrifft ausschließlich UI/Ampel und die Bewertung. Leistung,
	# Beschleunigung und der echte automatische Schaltpunkt bleiben unverändert.
	if not progressive_shift_difficulty:
		return 0.05
	# Gleiche RPM-Fensterbreite in allen Gängen. Spätere Gänge werden bereits durch
	# ihren langsameren RPM-Anstieg natürlicherweise leichter zu treffen.
	var window := lerpf(0.14, 0.05, clampf(shift_difficulty, 0.0, 1.0))
	# Starke Fahrzeuge durchlaufen dieselbe RPM-Zone in viel weniger Zeit. Ein
	# kleiner Bonus hilft vor allem auf leichten Stufen; bei 1 bleibt es schwer.
	var power_per_ton := _get_peak_horsepower() * 1000.0 / maxf(vehicle_mass_kg, 1.0)
	var power_assist := smoothstep(280.0, 900.0, power_per_ton) * 0.02
	window += power_assist * lerpf(1.0, 0.25, clampf(shift_difficulty, 0.0, 1.0))
	return clampf(window, 0.05, 0.16)

func _apply_artificial_rpm_limiter() -> void:
	# Rückwärts darf der Bungee-Cursor niemals dauerhaft am letzten Sample stehen.
	# Deshalb läuft in R immer der kleine automatische Redline-Zyklus, selbst wenn
	# der frei konfigurierbare Vorwärts-Limiter deaktiviert wurde.
	var limiter_should_run := artificial_rpm_limiter_enabled or is_reversing
	if not limiter_should_run:
		_artificial_limiter_cut_active = false
		return
	# Handbremse gehalten + Gas gelöst bedeutet bewusstes freies RPM-Abfallen.
	# Der harte Limiter-Rücksprung darf die kurz zuvor berechnete Fallhilfe nicht
	# überschreiben; ab jetzt steuert ausschließlich free_rev_fall_speed den Weg.
	if not is_reversing and handbrake > INPUT_EPSILON and throttle <= INPUT_EPSILON:
		_artificial_limiter_cut_active = false
		return
	# Ein Gangwechsel senkt die Ziel-RPM bereits selbst. Würde der künstliche
	# Limiter gleichzeitig aktiv bleiben, vervielfacht seine Cut-Stärke genau den
	# negativen Shift-Dist und erzeugt einen zweiten, wobbelnden RPM-Abfall.
	if is_shifting:
		_artificial_limiter_cut_active = false
		return
	if traction_control_active and _tc_recovery > 0.05:
		# TC fängt die Drehzahl bereits weich ein. Kein zweiter harter RPM-Cut.
		_artificial_limiter_cut_active = false
		return
	var trigger := _get_artificial_limiter_trigger_normalized()
	var drop_position := minf(_get_artificial_limiter_drop_normalized(), trigger)
	var audio_rpm := _get_audio_rpm()
	if _artificial_limiter_cut_active:
		# Ziel bleibt hart unten, bis der echte hörbare Cursor den Rücksprung
		# ausgeführt hat. Erst dann darf er wieder zum Trigger hochlaufen.
		rpm_normalized = drop_position
		if audio_rpm <= drop_position + 0.00005:
			_artificial_limiter_cut_active = false
	# Der Audiotreiber meldet 1.0 erst am letzten Sampleframe. Kein pauschales
	# vorzeitiges Ausloesen mehr; der letzte Rest wird im Audio-Treiber durchfahren.
	elif audio_rpm >= trigger:
		# Nicht die vorauslaufende Fahrzeug-RPM, sondern die tatsächliche
		# Audio-RPM löst den hörbaren Push aus: z.B. 0.98 -> sofort 0.80.
		_artificial_limiter_cut_active = true
		rpm_normalized = drop_position

func uses_fixed_effect_audio_follow() -> bool:
	if not simulator_enabled or not engine_power_available:
		return false
	if _audio_struggle_active:
		return true
	if not (artificial_rpm_limiter_enabled or is_reversing) or is_shifting:
		return false
	# Beide Haelften des Limiters gleich behandeln, nicht nur den Abwaerts-Cut.
	# Einschliesslich Wheelspin-Hochlauf bleibt die bewusste Ziel-RPM-Rampe erhalten.
	return _artificial_limiter_cut_active or rpm_normalized >= _get_artificial_limiter_drop_normalized() \
		or (race_launch_effect_active and race_launch_status == "DURCHDREHEN")

func get_effective_downshift_rpm() -> float:
	if not automatic_perfect_shift:
		return clampf(downshift_rpm, 0.1, 0.8)
	# Nach einem perfekten Upshift landet der Motor ungefähr bei
	# upshift * gear_rpm_drop. Der Abstand verhindert Gang-Pingpong und lässt
	# beim Ausrollen rechtzeitig in den stärkeren unteren Gang wechseln.
	return clampf(get_effective_upshift_rpm() * clampf(gear_rpm_drop, 0.5, 0.9) - 0.05, 0.15, 0.8)

func _calculate_perfect_upshift_rpm() -> float:
	var drop := clampf(gear_rpm_drop, 0.5, 0.9)
	var peak_rpm := 0.65
	var peak_power := -1.0
	# Erst den letzten relevanten Leistungsberg bestimmen; kleine Unebenheiten
	# einer ungetunten Kurve dürfen keinen viel zu frühen Shift auslösen.
	for sample in range(66, 100):
		var rpm_value := float(sample) / 100.0
		var power := _automatic_engine_output(rpm_value)
		if power >= peak_power:
			peak_power = power
			peak_rpm = rpm_value
	# Ab dem Peak lohnt der Wechsel, sobald der neue Gang nach dem RPM-Abfall
	# mehr Leistung bereitstellt als weiteres Ausdrehen im aktuellen Gang.
	var calculated := 0.985
	for sample in range(int(ceil(peak_rpm * 1000.0)), 986):
		var rpm_value := float(sample) / 1000.0
		var current_power := _automatic_engine_output(rpm_value)
		var next_gear_power := _automatic_engine_output(rpm_value * drop)
		if next_gear_power >= current_power:
			calculated = clampf(rpm_value, 0.7, 0.985)
			break
	# Eine Limiter-WAV ist Klanggestaltung und darf den physikalischen
	# Schaltpunkt nicht mehr verschieben.
	return calculated

#endregion

#region Motor-RPM und Struggle
func _update_rpm(delta: float) -> void:
	_audio_struggle_active = false
	if not engine_power_available:
		_launch_elapsed = -1.0
		_engine_start_rev_elapsed = -1.0
		_was_free_reving = false
		rpm_normalized = 0.0
		return
	if _engine_start_rev_elapsed >= 0.0:
		_engine_start_rev_elapsed += delta
		var rise_time := 0.18
		var hold_time := 0.12
		var fall_time := 0.55
		var rolling_target := _wheel_rpm(current_gear)
		if _engine_start_rev_elapsed < rise_time:
			var blend := smoothstep(0.0, rise_time, _engine_start_rev_elapsed)
			rpm_normalized = lerpf(_engine_start_rev_begin, _engine_start_rev_peak, blend)
		elif _engine_start_rev_elapsed < rise_time + hold_time:
			rpm_normalized = _engine_start_rev_peak
		else:
			var fall_elapsed := _engine_start_rev_elapsed - rise_time - hold_time
			var blend := smoothstep(0.0, fall_time, fall_elapsed)
			rpm_normalized = lerpf(_engine_start_rev_peak, rolling_target, blend)
			if fall_elapsed >= fall_time:
				_engine_start_rev_elapsed = -1.0
				rpm_normalized = rolling_target
		_was_free_reving = true
		return
	if _launch_elapsed >= 0.0 and (handbrake > INPUT_EPSILON or brake > INPUT_EPSILON or throttle <= INPUT_EPSILON or is_shifting or current_gear != 1):
		_launch_elapsed = -1.0
		_was_free_reving = true
	if handbrake > INPUT_EPSILON:
		if launch_control_active:
			var base := normalized_from_actual_rpm(clampf(launch_control_rpm, idle_rpm, max_rpm))
			var jump := clampf(launch_control_rpm_jump / maxf(max_rpm - idle_rpm, 1.0), 0.0, 0.3)
			# Erst sauber zur Launch-Drehzahl hochlaufen, dann am Begrenzer zwischen
			# oberer und unterer Grenze springen.
			if rpm_normalized < base - jump:
				rpm_normalized = move_toward(rpm_normalized, base - jump, maxf(handbrake_rev_speed, 0.01) * delta)
			else:
				_launch_control_phase = fmod(_launch_control_phase + delta * maxf(launch_control_jump_speed, 1.0), 1.0)
				var limiter_side := 1.0 if _launch_control_phase < 0.5 else -1.0
				rpm_normalized = clampf(base + jump * limiter_side, 0.0, 1.0)
			_was_free_reving = true
			return
		# Entkoppelt, aber nicht künstlich auf null: Ohne Gas folgt der Motor weich
		# der rollenden Fahrzeug-RPM; Gas darf ihn frei darüber hochdrehen.
		var rolling_rpm := _wheel_rpm(current_gear)
		var target := maxf(rolling_rpm, throttle)
		var rate := handbrake_rev_speed if target > rpm_normalized else free_rev_fall_speed
		# Bewusst simpel: Nur beim freien Abfallen wird der Fahrzeugwert direkt mit
		# der eigenen Schwierigkeit multipliziert – aber ausschließlich innerhalb
		# der sichtbaren blauen GUT- und grünen PERFEKT-Startbereiche.
		if target < rpm_normalized:
			var actual_free_rpm := calculate_actual_rpm(rpm_normalized)
			var launch_window := _get_effective_race_launch_window()
			var good_tolerance := maxf((max_rpm - idle_rpm) * 0.10, 250.0)
			var good_zone_begin := maxf(idle_rpm, launch_window.x - good_tolerance)
			if actual_free_rpm >= good_zone_begin and actual_free_rpm <= launch_window.y:
				rate *= _get_free_rev_fall_difficulty_factor()
		rpm_normalized = move_toward(rpm_normalized, target, maxf(rate, 0.01) * delta)
		_was_free_reving = true
		return
	if is_shifting:
		if transmission_type == TransmissionType.HANDSCHALTER and not _gear_changed:
			# Gas weg + Kupplung getrennt: Die Motor-RPM fällt bereits während der
			# Schaltbewegung zum Niveau des nächsten Gangs. Damit wird die Audio-Dist
			# wirklich negativ und DCC kann weich übernehmen.
			var total_progress := clampf(1.0 - _shift_timer / maxf(_shift_duration, 0.001), 0.0, 1.0)
			var clutch_phase := clampf(total_progress / maxf(_get_shift_engage_fraction(), 0.01), 0.0, 1.0)
			var next_gear_rpm := _wheel_rpm(_pending_gear)
			rpm_normalized = lerpf(_shift_start_rpm, next_gear_rpm, smoothstep(0.0, 1.0, clutch_phase))
		else:
			# Automatik/DSG halten den Cut zunächst kurz und setzen den vorbereiteten
			# Gang dann direkt. Wobble bleibt ausschließlich eine Tonhöhenmodulation.
			rpm_normalized = _wheel_rpm(current_gear) if _gear_changed else _shift_start_rpm
		return
	# Rückwärts verwendet exakt dieselbe Übersetzung wie Gang 1. Am Ende dieser
	# fahrzeugspezifischen Geschwindigkeit liegt Redline an und der Limiter greift.
	var target: float
	if is_reversing:
		target = clampf(speed_kmh / maxf(_get_reverse_max_speed_kmh(), 1.0), 0.0, 1.0)
	else:
		target = _wheel_rpm(current_gear)
	if downshift_wheel_lock:
		# Die Ziel-RPM folgt ausschließlich dem blockierten Radtempo. Die echte
		# Audio-RPM darf nun kontrolliert von Bungee zu diesem Wert aufholen.
		rpm_normalized = target
		_was_free_reving = false
		return
	if traction_control_active and _tc_recovery > 0.05:
		# Nur verbleibender Schlupf hebt RPM über das Radtempo. So darf der alte
		# Start-Limiter nicht trotz eingefangenem Wheelspin weiter Redline erzwingen.
		# TC übernimmt hier die Kupplungs-/Anfahr-RPM; keine eingefrorene
		# Anfahrphase zurücklassen, die anschließend Automatikschaltungen sperrt.
		_launch_elapsed = -1.0
		var controlled_rpm := maxf(target, lerpf(target, throttle, wheelspin))
		var tc_rpm_rate := free_rev_fall_speed if controlled_rpm < rpm_normalized else handbrake_rev_speed
		rpm_normalized = move_toward(rpm_normalized, controlled_rpm, maxf(tc_rpm_rate, 0.01) * delta)
		_was_free_reving = true
		return
	if race_launch_effect_active and race_launch_status == "DURCHDREHEN" and artificial_rpm_limiter_enabled and throttle > INPUT_EPSILON:
		# Beim schlechten Start darf die Motor-/Audio-RPM nicht an der langsamen
		# Fahrzeuggeschwindigkeit kleben. Die Räder drehen Richtung Redline durch,
		# während _update_speed() wegen des Schlupfs nur wenig Tempo aufbaut.
		var spin_fade := _race_launch_spin_factor()
		# Mit künstlichem Begrenzer exakt zu dessen Trigger, sonst bis ans Ende
		# der Audio-RPM. Dadurch hört man anschließend auch den Limiter arbeiten.
		var limiter_target := _get_artificial_limiter_trigger_normalized() if artificial_rpm_limiter_enabled else 1.0
		# Mit abnehmendem Wheelspin wandert auch das RPM-Ziel vom Limiter zurück
		# zur echten Gang-/Rad-RPM. Zuvor blieb nur der Hochlauf langsamer, das Ziel
		# selbst aber oben – dadurch hing die RPM bis zum letzten Moment am Limit.
		var spin_target := maxf(target, lerpf(target, limiter_target, spin_fade))
		# Nicht eine beliebige Motor-Rate skalieren, sondern exakt den Limiter-Push:
		# Rücksprung -> Trigger ist die normierte Strecke. Bei vollem Wheelspin dauert
		# sie etwa 0,10 s, bei 50 % Push 0,20 s und bei 10 % ungefähr 1,0 s.
		var limiter_drop := _get_artificial_limiter_drop_normalized()
		var limiter_push_distance := maxf(limiter_target - limiter_drop, 0.01)
		var full_limiter_push_rate := limiter_push_distance / 0.10
		var normalized_limiter_push := clampf(spin_fade, 0.0, 1.0)
		var spin_rate: float
		if spin_target < rpm_normalized:
			# Nicht hart herunterreißen: Während die Reifen Grip finden, koppelt die
			# Motordrehzahl zunehmend und sichtbar weich an das Radtempo zurück.
			spin_rate = free_rev_fall_speed * lerpf(0.06, 0.22, 1.0 - normalized_limiter_push)
		else:
			spin_rate = full_limiter_push_rate * normalized_limiter_push
		rpm_normalized = move_toward(rpm_normalized, spin_target, maxf(spin_rate, 0.001) * delta)
		_was_free_reving = true
		return
	if race_launch_effect_active and race_launch_status == "DURCHDREHEN" and throttle > INPUT_EPSILON:
		_audio_struggle_active = engine_struggle_enabled and engine_struggle_strength > 0.0
		# Ohne künstlichen Limiter hängt der Motor während des Schlupfs hoch in der
		# Drehzahl, bekommt aber kurze ungleichmäßige Einbrüche. Das simuliert das
		# NFS-artige Kämpfen der Reifen, statt eines glatten freien Hochdrehens.
		var spin_fade := _race_launch_spin_factor()
		_engine_struggle_phase = fmod(_engine_struggle_phase + delta * lerpf(4.0, 9.0, spin_fade), 1.0)
		var pulse := pow(maxf(sin(_engine_struggle_phase * TAU), 0.0), 4.0)
		var held_rpm := maxf(_race_launch_spin_hold_rpm, target)
		var coupled_target := lerpf(target, held_rpm, spin_fade)
		var struggle_amount := engine_struggle_strength if engine_struggle_enabled else 0.0
		var struggle_target := maxf(target, coupled_target - struggle_amount * spin_fade * pulse)
		var struggle_rate := handbrake_rev_speed * (0.65 if struggle_target < rpm_normalized else 1.15)
		rpm_normalized = move_toward(rpm_normalized, struggle_target, maxf(struggle_rate, 0.01) * delta)
		_was_free_reving = true
		return
	if _launch_elapsed >= 0.0:
		_launch_elapsed += delta
		var rise := maxf(launch_rise_time, 0.01)
		var settle := maxf(launch_settle_time, 0.01)
		if _launch_elapsed < rise:
			var blend := smoothstep(0.0, rise, _launch_elapsed)
			rpm_normalized = maxf(target, lerpf(_launch_start_rpm, _launch_peak_rpm, blend))
		else:
			var blend := smoothstep(0.0, settle, _launch_elapsed - rise)
			rpm_normalized = lerpf(maxf(target, _launch_peak_rpm), target, blend)
		if _launch_elapsed >= rise + settle:
			_launch_elapsed = -1.0
			_was_free_reving = false
		return
	if engine_struggle_enabled and current_gear > 1 and throttle > 0.45 and brake <= INPUT_EPSILON and handbrake <= INPUT_EPSILON:
		# Keine Rueckkopplung vom selbst modulierten Audiocursor auf die Lastkurve.
		var audio_rpm := physics_rpm
		# Nicht mehr pauschal unterhalb einer festen RPM-Grenze kämpfen. Wir lesen
		# stattdessen die echte Nm-Kurve ein kleines Stück voraus: steigt sie weiter,
		# bleibt der Motor ruhig; bei Plateau oder Einbruch wird der Struggle hörbar.
		var curve_struggle := _get_nm_curve_struggle(audio_rpm)
		var throttle_load := smoothstep(0.45, 1.0, throttle)
		var gear_load := _get_load_struggle_gear_factor(audio_rpm)
		# Vor einem möglichen Hochschalten muss der Lastpuls auslaufen. Andernfalls
		# trifft sein RPM-Rückgang genau auf Shift-Cut/Gangwechsel und erzeugt das
		# starke Zwischen-Wabbeln. Im letzten Gang gibt es keinen solchen Schutz.
		var pre_shift_fade := 1.0
		if current_gear < number_of_gears:
			var upshift_point := float(get_effective_upshift_rpm())
			# Nicht erst unmittelbar vor dem Mittelpunkt abschalten. Das dynamische
			# Schwierigkeitsfenster kann deutlich breiter sein; der Struggle muss schon
			# am Beginn von Blau vollständig verschwunden sein.
			var perfect_window := get_perfect_shift_window_width()
			var good_window := maxf(0.14, perfect_window + 0.06)
			var good_zone_begin := upshift_point - good_window
			pre_shift_fade = 1.0 - smoothstep(good_zone_begin - 0.025, good_zone_begin, audio_rpm)
		# Nur Last-Struggle: ab 55 % der echten Audio-RPM allmaehlich ruhiger
		# ausdrehen, an Redline kein Lastpuls mehr (auch im letzten Gang).
		# Nm-Ausloesung und der Schutz vor dem Schaltfenster bleiben erhalten.
		var rpm_load_fade := _get_load_struggle_rpm_fade(audio_rpm)
		var struggle_intensity := clampf(curve_struggle * throttle_load * gear_load * pre_shift_fade * rpm_load_fade, 0.0, 1.0)
		if struggle_intensity > 0.01:
			_audio_struggle_active = true
			_engine_struggle_phase = fmod(_engine_struggle_phase + delta * lerpf(4.0, 7.0, struggle_intensity), 1.0)
			var load_pulse := pow(maxf(sin(_engine_struggle_phase * TAU), 0.0), 4.0)
			var load_target := clampf(target - engine_struggle_strength * struggle_intensity * load_pulse, 0.0, 1.0)
			var load_rate := handbrake_rev_speed * (0.55 if load_target < rpm_normalized else 1.0)
			rpm_normalized = move_toward(rpm_normalized, load_target, maxf(load_rate, 0.01) * delta)
			_was_free_reving = true
			return
	# Dasselbe echte Lastsystem im Schubbetrieb: Beim Herunterdrehen modulieren
	# Plateau/Einbruch der Nm-Kurve nun die RPM und damit direkt Dist + DCC. Es ist
	# bewusst schwächer als unter Gas und niemals während Bremse/Handbremse/Shift.
	if engine_struggle_enabled and coast_curve_struggle_strength > 0.0 and throttle < 0.15 and speed_kmh > 5.0 and brake <= INPUT_EPSILON and handbrake <= INPUT_EPSILON and target < rpm_normalized - 0.0005:
		var coast_curve := _get_nm_curve_struggle(physics_rpm)
		if coast_curve > 0.01:
			_audio_struggle_active = true
			_engine_struggle_phase = fmod(_engine_struggle_phase + delta * lerpf(2.5, 5.0, coast_curve), 1.0)
			var coast_pulse := pow(maxf(sin(_engine_struggle_phase * TAU), 0.0), 3.0)
			var coast_amount := engine_struggle_strength * coast_curve_struggle_strength * coast_curve
			var coast_target := clampf(target - coast_amount * coast_pulse, 0.0, 1.0)
			var coast_rate := maxf(free_rev_fall_speed * lerpf(0.65, 1.15, coast_pulse), 0.01)
			rpm_normalized = move_toward(rpm_normalized, coast_target, coast_rate * delta)
			_was_free_reving = true
			return
	if wheelspin > 0.01 and throttle > INPUT_EPSILON:
		# Durchdrehende Räder entkoppeln Motor- und Fahrzeug-RPM teilweise.
		# Je mehr Schlupf, desto stärker zieht Gas die RPM Richtung Redline.
		var slip_target := maxf(target, lerpf(target, throttle, clampf(wheelspin, 0.0, 1.0)))
		var slip_rate := lerpf(free_rev_fall_speed, handbrake_rev_speed, clampf(wheelspin, 0.0, 1.0))
		rpm_normalized = move_toward(rpm_normalized, slip_target, maxf(slip_rate, 0.01) * delta)
		_was_free_reving = true
		return
	if _was_free_reving:
		var rate := handbrake_rev_speed if target > rpm_normalized else free_rev_fall_speed
		rpm_normalized = move_toward(rpm_normalized, target, maxf(rate, 0.01) * delta)
		if is_equal_approx(rpm_normalized, target):
			_was_free_reving = false
	else:
		rpm_normalized = target

#endregion

#region Gangwahl und Schaltablauf
func _update_automatic_gears() -> void:
	# Wie in NFS: Solange die normale Bremse gehalten wird, bleibt der aktuelle
	# Gang drin. Bremsen darf keinen automatischen Downshift erzwingen.
	if not engine_power_available or not automatic_gears or is_reversing or _reverse_to_forward_active or is_shifting or downshift_wheel_lock or _physics_launch_remaining > 0.0 or (race_launch_effect_active and race_launch_status == "DURCHDREHEN") or handbrake > INPUT_EPSILON or brake > INPUT_EPSILON:
		return
	if _gear_hold_timer > 0.0 and not _sudden_speed_loss:
		return
	var up_threshold := get_effective_upshift_rpm()
	var down_threshold := get_effective_downshift_rpm()
	if throttle > INPUT_EPSILON and brake <= INPUT_EPSILON and physics_rpm >= up_threshold and current_gear < number_of_gears:
		_request_gear(current_gear + 1)
	elif current_gear > 1 and (_downshift_lock_timer <= 0.0 or _sudden_speed_loss):
		var wheel_rpm := _wheel_rpm(current_gear)
		if wheel_rpm <= down_threshold or _sudden_speed_loss:
			var best_gear := _find_best_gear_for_speed(up_threshold - 0.06)
			if best_gear < current_gear:
				_request_gear(best_gear)

func _find_best_gear_for_speed(max_allowed_rpm: float) -> int:
	# Niedrigsten Gang wählen, der bei der aktuellen Geschwindigkeit nicht überdreht.
	for gear in range(1, current_gear):
		if speed_kmh / _get_gear_max_speed(gear) <= max_allowed_rpm:
			return gear
	return current_gear

func shift_up() -> void:
	_request_gear(current_gear + 1, true)

func shift_down() -> void:
	_request_gear(current_gear - 1, true)

func _get_effective_shift_duration() -> float:
	var base := maxf(shift_time, 0.001)
	match transmission_type:
		TransmissionType.HANDSCHALTER:
			return maxf(base * 1.25, 0.12)
		TransmissionType.DSG_SEQUENZIELL:
			return maxf(base * 0.55, 0.035)
		_:
			return base

func _get_shift_engage_fraction() -> float:
	match transmission_type:
		TransmissionType.HANDSCHALTER:
			return 0.62 # Kupplung trennt, dann wird der neue Gang eingelegt.
		TransmissionType.DSG_SEQUENZIELL:
			return 0.28 # Nächster Gang ist bereits vorgewählt.
		_:
			return 0.48

func _get_shift_wobble_factor() -> float:
	match transmission_type:
		TransmissionType.HANDSCHALTER:
			return 1.15
		TransmissionType.DSG_SEQUENZIELL:
			return 0.55
		_:
			return 0.85

func _request_gear(new_gear: int, manual_request: bool = false) -> void:
	if not simulator_enabled or is_shifting or handbrake > INPUT_EPSILON:
		return
	new_gear = clampi(new_gear, 1, number_of_gears)
	if new_gear == current_gear:
		return
	# Die Automatik wählt weiterhin keinen Gang, der sofort überdrehen würde.
	# Ein bewusster manueller Downshift bleibt in der Semi-Automatik erlaubt;
	# _wheel_rpm() begrenzt die Audio-RPM dabei sicher auf den Limiterbereich.
	if not manual_request and new_gear < current_gear and speed_kmh > _get_gear_limited_speed(new_gear):
		return
	_pending_gear = new_gear
	_manual_shift_requested = manual_request
	_shift_duration = _get_effective_shift_duration()
	_shift_timer = _shift_duration
	_shift_start_rpm = rpm_normalized
	_gear_changed = false
	# Ein alter Gasimpuls darf nicht in den Schaltvorgang hineinragen.
	_reset_wobble()
	# Ebenso darf ein gerade begonnener Redline-Cut nicht in den Shift hineinragen.
	_artificial_limiter_cut_active = false
	_wobble_waiting_for_audio_rise = false
	is_shifting = true

func _update_shift(delta: float) -> void:
	if not is_shifting:
		return
	_shift_timer = maxf(0.0, _shift_timer - delta)
	var progress := 1.0 - _shift_timer / _shift_duration
	if not _gear_changed and progress >= _get_shift_engage_fraction():
		var previous := current_gear
		current_gear = _pending_gear
		_gear_changed = true
		_was_free_reving = false
		rpm_normalized = _wheel_rpm(current_gear)
		if _manual_shift_requested and current_gear < previous and speed_kmh > _get_gear_limited_speed(current_gear):
			downshift_wheel_lock = true
			_downshift_grip_recovery = 0.0
			# Unterhalb des Limiters festes Fangtempo, damit die Audio-RPM ein
			# stabiles Ziel erhält und die Blockierung sicher wieder lösen kann.
			_downshift_lock_target_speed = _get_gear_limited_speed(current_gear) * 0.92
		if current_gear > previous:
			_downshift_lock_timer = maxf(downshift_lock_time, 0.0)
		gear_changed.emit(previous, current_gear)
	if _shift_timer <= 0.0:
		is_shifting = false
		_post_shift_rpm_floor = rpm_normalized
		_post_shift_audio_floor = _get_audio_rpm()
		# Nach einem manuellen Eingriff nicht sofort von der Automatik wieder
		# zurückschalten. Die vorhandene Sperrzeit dient als Semi-Auto-Haltezeit.
		_gear_hold_timer = maxf(MIN_GEAR_HOLD, downshift_lock_time) if _manual_shift_requested else MIN_GEAR_HOLD
		_manual_shift_requested = false

#endregion

#region Wobble-Ausloesung
func _update_wobble_input(shift_was_active: bool) -> void:
	if is_shifting:
		# Shift-Timer läuft: Gas/Last und Wobble bleiben vollständig aus.
		_update_gas_wobble(0.0)
		return
	if shift_was_active:
		# Timer ist vorbei, aber noch NICHT wobblen. Ab jetzt entscheidet nur der
		# echte Audio-RPM-Abstand aus bungee_engine_audio.gd über die Last-Rückkehr.
		_wobble_waiting_for_audio_rise = true
		_last_audio_rpm_dist = _get_audio_rpm_dist()
		_update_gas_wobble(0.0)
		return
	if _wobble_waiting_for_audio_rise:
		_update_post_shift_audio_wobble(_get_audio_rpm_dist())
		return
	if brake > INPUT_EPSILON:
		return
	_update_gas_wobble(throttle)

func _update_post_shift_audio_wobble(audio_dist: float) -> void:
	if brake > INPUT_EPSILON or throttle <= 0.9:
		_last_audio_rpm_dist = audio_dist
		_update_gas_wobble(0.0)
		return
	# Eindeutiger Ganganschluss: Ziel UND tatsächlich hörbare Audio-RPM müssen nach
	# Shift-Ende steigen. Der alte Dist-Vergleich konnte bei schnellem Follow nie
	# freigeben, weil der Abstand beim Aufholen naturgemäß bereits wieder schrumpft.
	var target_is_rising := rpm_normalized > _post_shift_rpm_floor + 0.00015
	var audio_is_recovering := _get_audio_rpm() > _post_shift_audio_floor + 0.0001
	if target_is_rising and audio_is_recovering:
		_wobble_waiting_for_audio_rise = false
		_update_gas_wobble(throttle)
	else:
		_update_gas_wobble(0.0)
	_last_audio_rpm_dist = audio_dist

func _update_gas_wobble(effective_throttle: float) -> void:
	if effective_throttle < 0.5:
		_gas_wobble_armed = true
	elif _gas_wobble_armed and effective_throttle > 0.9:
		_gas_wobble_armed = false
		_trigger_wobble(maxf(effective_throttle, 0.35) * _get_shift_wobble_factor())

#endregion

#region Reset und Motorstart
func _cancel_shift() -> void:
	is_shifting = false
	_manual_shift_requested = false
	_pending_gear = current_gear
	_shift_timer = 0.0
	_gear_changed = false
	_wobble_waiting_for_audio_rise = false
	_post_shift_rpm_floor = rpm_normalized

func reset_simulation() -> void:
	_audio_struggle_active = false
	physics_rpm = 0.0
	_physics_launch_remaining = 0.0
	_physics_launch_peak = 0.0
	_physics_launch_armed = true
	_cancel_shift()
	_reset_wobble()
	speed_kmh = 0.0
	rpm_normalized = 0.0
	visual_rpm = 0.0
	current_gear = 1
	is_reversing = false
	_reverse_to_forward_active = false
	_reverse_launch_wheelspin_timer = 0.0
	_pending_gear = 1
	throttle = 0.0
	brake = 0.0
	handbrake = 0.0
	_downshift_lock_timer = 0.0
	_gear_hold_timer = 0.0
	_was_free_reving = false
	_last_step_speed_kmh = 0.0
	_sudden_speed_loss = false
	downshift_wheel_lock = false
	_downshift_grip_recovery = 1.0
	_downshift_lock_target_speed = 0.0
	_artificial_limiter_cut_active = false
	_wobble_waiting_for_audio_rise = false
	_last_audio_rpm_dist = 0.0
	_post_shift_rpm_floor = 0.0
	_post_shift_audio_floor = 0.0
	_acceleration_run_time = -1.0
	_time_at_100 = -1.0
	acceleration_time_0_100 = -1.0
	acceleration_time_100_200 = -1.0
	traction = 1.0
	wheelspin = 0.0
	traction_control_active = false
	_tc_phase = 0.0
	_tc_recovery = 0.0
	_tc_pulse = 0.0
	supercharger_boost = 0.0
	turbo_boost = 0.0
	_launch_elapsed = -1.0
	_launch_armed = true
	launch_control_active = false
	race_launch_staging = false
	race_launch_status = "BEREIT"
	race_launch_effect_active = false
	_race_launch_effect_timer = 0.0
	_race_launch_power_factor = 1.0
	_race_launch_traction_factor = 1.0
	_race_launch_spin_hold_rpm = 0.0
	_race_launch_spin_severity = 1.0
	_engine_struggle_phase = 0.0
	_launch_control_was_active = false
	_launch_control_phase = 0.0
	_launch_control_release_timer = 0.0
	_engine_start_rev_elapsed = -1.0
	# AUS bedeutet keine automatischen RPM-Schreibzugriffe auf den Sound-Node.
	if simulator_enabled and is_instance_valid(_engine_sound_system) and _parent_properties.has("rpm_position"):
		_engine_sound_system.set("rpm_position", 0.0)
	_update_debug_ui()

func trigger_engine_start_rev(peak_rpm: float) -> void:
	if not simulator_enabled:
		return
	_engine_start_rev_elapsed = 0.0
	_engine_start_rev_begin = rpm_normalized
	_engine_start_rev_peak = clampf(peak_rpm, 0.0, 1.0)
	_was_free_reving = true

#endregion

#region Pitch-Wobble und Audio-Rueckmeldung
func _trigger_wobble(amount: float) -> void:
	if not wobble_enabled or wobble_strength <= 0.0:
		return
	# Geschwindigkeitsimpuls erhält den aktuellen Wert auch bei Retriggern.
	var impulse := TAU * WOBBLE_HZ * wobble_strength
	_wobble_velocity = clampf(_wobble_velocity + impulse * amount, -2.0 * impulse, 2.0 * impulse)

func _update_wobble(delta: float) -> void:
	if not wobble_enabled or wobble_strength <= 0.0:
		_reset_wobble()
		return
	# Analytisch gedämpfte Schwingung: unabhängig vom Physics-Takt.
	var omega := TAU * WOBBLE_HZ
	var damping := 4.0 / maxf(wobble_duration, 0.01)
	var decay := exp(-damping * delta)
	var cosine := cos(omega * delta)
	var sine := sin(omega * delta)
	var position := wobble
	var q := _wobble_velocity + damping * position
	wobble = decay * (position * cosine + q / omega * sine)
	_wobble_velocity = decay * (_wobble_velocity * cosine - (omega * position + damping * q / omega) * sine)
	wobble = clampf(wobble, -wobble_strength, wobble_strength)
	if absf(wobble) < 0.00001 and absf(_wobble_velocity) < 0.0001:
		wobble = 0.0
		_wobble_velocity = 0.0

func _send_wobble() -> void:
	if is_instance_valid(_engine_sound_system) and _parent_properties.has("simulator_pitch_modulation"):
		_engine_sound_system.set("simulator_pitch_modulation", 1.0 + wobble)

func _reset_wobble() -> void:
	wobble = 0.0
	_wobble_velocity = 0.0
	_gas_wobble_armed = true
	_send_wobble()

func _get_audio_rpm() -> float:
	if is_instance_valid(_engine_sound_system) and _parent_properties.has("node_accel"):
		var voice = _engine_sound_system.get("node_accel")
		var length := float(_engine_sound_system.get("len_accel"))
		if is_instance_valid(voice) and length > 0.0:
			if _engine_sound_system.has_method("get_audio_rpm_normalized"):
				return float(_engine_sound_system.get_audio_rpm_normalized())
			return clampf(voice.get_playback_position() / length, 0.0, 1.0)
	return rpm_normalized

func _get_audio_rpm_dist() -> float:
	if is_instance_valid(_engine_sound_system) and _parent_properties.has("rpm_follow_distance_normalized"):
		return float(_engine_sound_system.get("rpm_follow_distance_normalized"))
	return 0.0

#endregion

#region UI-Anbindung
func _bind_optional_ui() -> void:
	_debug_ui = null
	for child in get_children():
		if child is BungeeSimulatorUI:
			_debug_ui = child
			_debug_ui.setup(self, _engine_sound_system, _parent_properties)
			break

func _fit_debug_ui(viewport_override: Vector2 = Vector2.ZERO) -> void:
	if is_instance_valid(_debug_ui):
		_debug_ui.fit_to_screen(viewport_override)

func _update_debug_ui() -> void:
	if is_instance_valid(_debug_ui):
		_debug_ui.refresh()

#endregion
