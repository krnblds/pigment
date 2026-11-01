@icon("res://addons/bungee/assets/icons/bungee_engine_audio_node.svg")
class_name BungeeEngineAudio
extends Node3D
## Motor-Soundbank und gemeinsamer AudioStreamGenerator-Mix.
## Fahrzeugphysik: bungee_vehicle_simulator.gd. Bedienoberflaeche: bungee_simulator_ui.gd.

enum LiveInputMode { AUTO_SIMULATOR, EXTERNAL }
enum ReverbPreset { TUNNEL, GARAGE, OUTDOOR, UNDERPASS }
enum CabinPreset { STREET_CAR, RACE_CAR, RACE_COCKPIT }

@export_category("00 Control - Simulator or Custom Vehicle System")

@export_group("Input Source")
## Automatisch liest einen BungeeVehicleSimulator als direktes Kind.
## Extern verwendet die folgenden Werte beziehungsweise die öffentliche API.
@export_enum("Automatic Simulator", "External / Custom Vehicle Logic") var live_input_mode: int = LiveInputMode.AUTO_SIMULATOR

@export_group("Engine - Always Required")
## Hauptschalter des Motors. Ohne diesen Schalter bleiben bewusst alle Motorquellen stumm.
@export var engine_running: bool = false:
	set(value):
		if engine_running == value:
			return
		engine_running = value
		if is_node_ready():
			_set_engine_running(value)
## Gewünschte Motordrehzahl: 0 = Anfang der Soundbank, 1 = Ende der Soundbank.
## Dieser Wert treibt den eigentlichen ACC-/DCC-Motorsound an.
@export_range(0.0, 1.0, 0.001) var rpm_position: float = 0.0

@export_group("External Live Values")
## Erkennt Last automatisch: RPM steigt = ACC/Boost, RPM fällt = DCC/BOV.
@export var automatic_load_from_rpm: bool = true
## Löst die anhand der höchsten RPM aufgebaute Backfire-Ladung beim Abfall aus.
@export var automatic_backfire_trigger: bool = true
@export_range(0.0, 1.0, 0.001) var handbrake: float = 0.0
@export_range(0.0, 1.0, 0.001) var wheelspin: float = 0.0
## Momentane Sound-Trigger. Beim Aktivieren springen sie selbst auf AUS zurück.
@export var trigger_gear_up: bool = false:
	set(value):
		trigger_gear_up = false
		if value and is_node_ready():
			trigger_shift_up_sound()
@export var trigger_gear_down: bool = false:
	set(value):
		trigger_gear_down = false
		if value and is_node_ready():
			trigger_shift_down_sound()
@export var trigger_bov: bool = false:
	set(value):
		trigger_bov = false
		if value and is_node_ready():
			trigger_bov_sound()
@export var trigger_backfire: bool = false:
	set(value):
		trigger_backfire = false
		if value and is_node_ready():
			trigger_backfire_sound()

# Erweiterte Kompatibilitätswerte für die API; absichtlich nicht im einfachen Inspector.
var throttle: float = 0.0
var speed_kmh: float = 0.0
var max_speed_kmh: float = 250.0
var current_gear: int = 1
var number_of_gears: int = 6
var is_shifting: bool = false
var is_reversing: bool = false
var downshift_wheel_lock: bool = false

@export_group("External Forced Induction")
@export var turbo_enabled: bool = false
## AN berechnet den Sound-Ladedruck automatisch aus echter Audio-RPM und Gas.
@export var automatic_turbo_boost: bool = true
@export_range(0.0, 1.0, 0.001) var turbo_boost: float = 0.0
@export_range(0.0, 0.9, 0.01) var automatic_turbo_spool_start_rpm: float = 0.25
@export_range(0.1, 10.0, 0.1) var automatic_turbo_spool_up_speed: float = 1.8
@export_range(0.1, 10.0, 0.1) var automatic_turbo_spool_down_speed: float = 3.5
@export var supercharger_enabled: bool = false

@export_group("External Limiter Cut")
## Optionales Klangsignal für einen Begrenzer des eigenen Fahrzeugsystems.
@export var external_limiter_cut_active: bool = false
@export_range(1.0, 20.0, 0.5) var artificial_rpm_limiter_cut_strength: float = 6.0

# Kompatible Quellfelder für dieselbe interne Verarbeitung wie beim Simulator.
var _artificial_limiter_cut_active: bool:
	get: return external_limiter_cut_active
var _pending_gear: int:
	get: return current_gear

@export_category("01 Engine Playback")

@export_group("Sound Bank - Select Vehicle")
@export_dir var soundbank_path: String = "res://addons/bungee/sounds/Vehicles":
	set(value):
		# Alte Szenen und eigene Presets behalten ihren gueltigen Fahrzeugpfad.
		var clean_path := value.trim_suffix("/")
		soundbank_path = "res://addons/bungee/sounds/Vehicles" if clean_path in [
			"res://assets/GinNFS", "res://assets/GinNFS/Vehicles",
			"res://assets/sounds", "res://assets/sounds/Vehicles",
			"res://addons/bungee/sounds"
		] else value
		if is_node_ready():
			_scan_soundbank()
			_reload_sound()
## Gemeinsame Zusatzsounds, getrennt von den Fahrzeug-Soundbanks.
@export_dir var effects_path: String = "res://addons/bungee/sounds/Effects":
	set(value):
		var clean_path := value.trim_suffix("/")
		effects_path = "res://addons/bungee/sounds/Effects" if clean_path in [
			"res://assets/GinNFS/Effects", "res://assets/sounds/Effects"
		] else value
		if is_node_ready():
			_reload_sound()
@export var car_index: int = 0:
	set(value):
		car_index = value
		if is_node_ready():
			_reload_sound()

@export_group("RPM Tracking and Base Pitch")
## Exponentielle Zielverfolgung mit Reserve fuer Bungees Grain-Nachlauf.
## Gleicher Wert für beide Richtungen, keine zusätzliche Glättung.
## Nur Klang-Nachlauf; Simulator-Struggle und Limiter verwenden feste Referenz 20.
@export_range(0.1, 100.0, 0.1) var distance_strength: float = 10.0
## Innerhalb dieses normalisierten RPM-Abstands wird die Zielannaeherung gebremst.
@export_range(0.0, 0.25, 0.005) var follow_target_brake_distance: float = 0.08
## 0 = aus, 1 = am Ziel maximal langsam. Grosse Distanzen bleiben unveraendert.
@export_range(0.0, 1.0, 0.01) var follow_target_brake_strength: float = 0.9
## 1 = Originaltonhöhe. ACC/DCC-Pitch ist unabhängig von der RPM-Verfolgung.
## Echte Idle-/Limiter-Loops werden mit derselben Tonhöhe schneller/langsamer gelesen.
@export_range(0.5, 2.0, 0.01) var engine_pitch: float = 1.0:
	set(value):
		if is_finite(value):
			engine_pitch = clampf(value, 0.5, 2.0)

@export_group("ACC-DCC Crossfade")
## Überblendzeit in Millisekunden für beide Richtungen. 4 ms = bisheriger Klang.
## 0 ms schaltet hart um und kann wieder Knackser verursachen.
@export_range(0.0, 250.0, 0.5, "suffix:ms") var acc_dcc_transition_ms: float = 4.0

@export_group("Stationary Audio RPM - Phaser Protection")
## Verhindert den metallischen Freeze-/Phaserklang, wenn Bungee unter Last nur
## extrem langsam durch die Motoraufnahme fährt oder genau darauf stehen bleibt.
## Die sichtbare RPM und die Distanz werden dabei nicht verändert.
@export var stationary_grain_protection: bool = true
@export_range(0.0, 1.0, 0.005) var stationary_min_scan_speed: float = 0.2
@export_subgroup("Pitch Motion - Frequency and Strength")
## Schwingungen pro Sekunde; veraendert das Tempo, nicht die Staerke der Bewegung.
@export_range(0.1, 20.0, 0.1, "suffix:Hz") var stationary_motion_frequency_hz: float = 2.0
## Staerke der Pitchbewegung: 0 = aus, 0.04 = +/-4 Prozent Tonhoehe.
## Der bisherige Eigenschaftsname bleibt fuer gespeicherte Szenen erhalten.
@export_range(0.0, 0.15, 0.001) var stationary_pitch_motion: float = 0.04

@export_category("02 Engine State and Loops")

@export_group("Start and Stop")
@export_range(0.0, 2.0, 0.01) var engine_start_volume: float = 1.0
@export_range(0.5, 2.0, 0.01) var engine_start_pitch: float = 1.0
@export_range(0.0, 1.0, 0.01) var engine_start_rpm_kick: float = 0.6
@export_range(0.0, 2.0, 0.01) var engine_kill_volume: float = 1.0
@export_range(0.5, 2.0, 0.01) var engine_kill_pitch: float = 1.0

@export_group("Idle WAV")
@export var idle_enabled: bool = true
## Bei RPM 0 nur Idle; bis zu dieser Audio-RPM vollständig zu ACC/DCC wechseln.
@export_range(0.01, 0.25, 0.005) var idle_fade_end: float = 0.08
@export_range(0.0, 2.0, 0.01) var idle_volume: float = 1.0

@export_group("Redline - Limiter WAV")
@export var limiter_enabled: bool = true
## Ab dieser Audio-RPM einblenden; bei RPM 1 nur die Limiter-WAV.
@export_range(0.75, 0.99, 0.005) var limiter_fade_start: float = 0.94
@export_range(0.0, 2.0, 0.01) var limiter_volume: float = 1.0

@export_group("RPM Limiter - Cut Sound")
## Beim künstlichen RPM-Cut kurz die DCC-Stimme verwenden; der Rücklauf nutzt ACC.
@export var limiter_cut_uses_dcc: bool = true
## Zusätzliche Tonhöhenabsenkung während des Rücksprungs. 1 = unverändert.
const LIMITER_CUT_PITCH: float = 0.5
## Führt den Rücksprung in wenigen Millisekunden aus, ohne eine klickende Samplekante.
@export var limiter_cut_instant: bool = true

@export_category("03 Tone and Audio Output")

@export_group("Directional Tone - Rise and Fall")
## Resonanter Tiefpass wie zuvor, ohne Klarheitskurve oder Sättigung.
@export var direction_tone_enabled: bool = true
@export_range(1000.0, 20000.0, 100.0) var tone_cutoff_rise_hz: float = 19500.0
@export_range(1000.0, 20000.0, 100.0) var tone_cutoff_fall_hz: float = 14000.0
@export_range(0.0, 1.0, 0.01) var tone_resonance_rise: float = 0.12
@export_range(0.0, 1.0, 0.01) var tone_resonance_fall: float = 0.05

@export_group("Treble Enhancement")
@export var highs_enabled: bool = true
## Breite Höhenanhebung, keine Bassabsenkung und keine Sättigung.
@export_range(0.0, 6.0, 0.5) var highs_gain_db: float = 3.0
@export_range(1000.0, 10000.0, 100.0) var highs_start_hz: float = 3500.0

@export_group("Output - Spatial Mode and Engine Level")
## 2D ist der sichere Addon-Standard und funktioniert auch in Test-/UI-Szenen
## ohne Camera3D. Für räumlichen Fahrzeugklang im Spiel gezielt aktivieren.
@export var use_3d_audio: bool = false:
	set(value):
		use_3d_audio = value
		if is_node_ready():
			_reload_sound()
@export_range(0.0, 2.0, 0.01) var acceleration_volume: float = 1.0
## Pegelreserve VOR den Filtern. Kein Kompressor oder automatischer Pegelausgleich.
@export_range(-18.0, 0.0, 0.5) var output_headroom_db: float = -6.0

@export_group("Environment Reverb - Tunnel and Spaces")
## Schaltet den internen Raumklang frei. Amount kann im Spiel weich 0..1 fahren.
@export var reverb_enabled: bool = true
@export_enum("Tunnel", "Garage", "Outdoor", "Underpass") var reverb_preset: int = ReverbPreset.TUNNEL:
	set(value):
		reverb_preset = clampi(value, ReverbPreset.TUNNEL, ReverbPreset.UNDERPASS)
		if is_node_ready():
			_apply_reverb_preset()
## 0 = trocken, 1 = volle Stärke des gewählten Raum-Presets.
@export_range(0.0, 1.0, 0.001) var reverb_amount: float = 0.0
## Geschwindigkeit der weichen Ein-/Ausblendung pro Sekunde.
@export_range(0.1, 20.0, 0.1) var reverb_fade_speed: float = 4.0

@export_group("Cabin Sound - Driver Perspective")
## Simuliert die Dämmung zwischen Motorraum und Fahrer. Amount 0 bleibt Außenklang.
@export var cabin_enabled: bool = false
@export_enum("Street Car", "Race Car", "Race Car Cockpit") var cabin_preset: int = CabinPreset.STREET_CAR
## 0 = Außenklang, 1 = voller Innenraumklang des gewählten Presets.
@export_range(0.0, 1.0, 0.001) var cabin_amount: float = 0.0
## Geschwindigkeit der weichen Innen-/Außen-Überblendung pro Sekunde.
@export_range(0.1, 20.0, 0.1) var cabin_fade_speed: float = 5.0

@export_group("Audio Hard Limiter - Clipping Protection, No RPM Effect")
## Gemeinsamer Bus-Schutz für den kompletten Engine-Mix.
@export var hard_limiter_enabled: bool = true
@export_range(-24.0, 0.0, 0.5) var hard_limiter_pre_gain_db: float = -6.0
@export_range(-12.0, 0.0, 0.5) var hard_limiter_ceiling_db: float = -2.0
@export_range(1.0, 200.0, 1.0, "suffix:ms") var hard_limiter_release_ms: float = 80.0

@export_category("04 Transmission and Tires")

@export_group("Transmission Whine - Speed and Load")
@export var transmission_enabled: bool = true
@export var transmission_index: int = 0:
	set(value):
		transmission_index = maxi(value, 0)
		if is_node_ready():
			_scan_transmission_bank()
			_reload_transmission_only()
## Maximaler Whine-Pegel bei Endgeschwindigkeit und voller Getriebelast.
@export_range(0.0, 2.0, 0.01) var transmission_max_speed_volume: float = 0.4
## Grundmultiplikator für die gesamte Whine-Tonhöhe.
@export_range(0.5, 2.0, 0.01) var transmission_pitch: float = 1.0
## Dynamischer Pitch bei niedriger und maximaler Fahrzeuggeschwindigkeit.
@export_range(0.1, 2.0, 0.01) var transmission_pitch_low_speed: float = 0.55
@export_range(0.5, 4.0, 0.01) var transmission_pitch_high_speed: float = 2.0
## Restlautstärke ohne Last; unter Gas wird bis zum vollen Pegel überblendet.
@export_range(0.0, 1.0, 0.01) var transmission_coast_amount: float = 0.35

@export_group("Gear Shifts - Individual WAV Sounds")
@export var shift_up_sound_index: int = 0:
	set(value):
		shift_up_sound_index = maxi(value, 0)
		if is_node_ready():
			_scan_shift_sound_banks()
@export_range(0.0, 2.0, 0.01) var shift_up_sound_volume: float = 1.0
@export_range(0.5, 2.0, 0.01) var shift_up_sound_pitch: float = 1.0
@export var shift_down_sound_index: int = 0:
	set(value):
		shift_down_sound_index = maxi(value, 0)
		if is_node_ready():
			_scan_shift_sound_banks()
@export_range(0.0, 2.0, 0.01) var shift_down_sound_volume: float = 1.0
@export_range(0.5, 2.0, 0.01) var shift_down_sound_pitch: float = 1.0

@export_group("Tires - Skid Sound")
@export var skid_enabled: bool = true
@export var skid_index: int = 0:
	set(value):
		skid_index = maxi(value, 0)
		if is_node_ready():
			_scan_skid_bank()
			_reload_skid_only()
@export_range(0.0, 2.0, 0.01) var skid_volume: float = 0.8
@export_range(0.25, 2.0, 0.01) var skid_pitch_low_speed: float = 0.75
@export_range(0.5, 3.0, 0.01) var skid_pitch_high_speed: float = 1.45

@export_category("05 Forced Induction")

@export_group("Supercharger Sound")
@export var supercharger_index: int = 0:
	set(value):
		supercharger_index = maxi(value, 0)
		if is_node_ready():
			_scan_supercharger_bank()
			_reload_supercharger_only()
@export_range(0.0, 2.0, 0.01) var supercharger_volume: float = 0.35
@export_range(0.1, 2.0, 0.01) var supercharger_pitch_idle: float = 0.55
@export_range(0.5, 4.0, 0.01) var supercharger_pitch_redline: float = 2.2
@export_range(0.0, 1.0, 0.01) var supercharger_coast_amount: float = 0.25

@export_group("Turbo Sound")
@export var turbo_index: int = 0:
	set(value):
		turbo_index = maxi(value, 0)
		if is_node_ready():
			_scan_turbo_banks()
			_reload_turbo_playback()
@export_range(0.0, 2.0, 0.01) var turbo_volume: float = 0.45
@export_range(0.5, 3.0, 0.01) var turbo_pitch: float = 1.0

@export_group("Blow-Off Valve - BOV Sound")
@export var bov_index: int = 0:
	set(value):
		bov_index = maxi(value, 0)
		if is_node_ready():
			_scan_turbo_banks()
@export_range(0.0, 2.0, 0.01) var bov_volume: float = 0.7

@export_category("06 Backfire")

@export_group("Backfire - Sound and Variations")
@export var backfire_enabled: bool = true:
	set(value):
		backfire_enabled = value
		if not value and is_node_ready():
			_stop_backfire_burst()
			_backfire_release_armed = false
			_backfire_peak_load = 0.0
			_backfire_load_energy = 0.0
			_backfire_coast_shift_pending = 0.0
@export var backfire_index: int = 0:
	set(value):
		backfire_index = maxi(value, 0)
		if is_node_ready():
			_scan_backfire_bank()
@export var backfire_random_variations: bool = true
@export_range(0.0, 2.0, 0.01) var backfire_volume: float = 0.8
@export_range(0.0, 1.0, 0.01) var backfire_strength: float = 0.65
@export_range(0.5, 2.0, 0.01) var backfire_pitch: float = 1.0

@export_group("Backfire - Trigger and Duration")
@export_range(0.0, 1.0, 0.01) var backfire_min_audio_rpm: float = 0.3
@export_range(0.0, 1.0, 0.01) var backfire_max_audio_rpm: float = 1.0
@export_range(0.0, 1.0, 0.01) var backfire_min_load: float = 0.35
@export_range(0.02, 1.0, 0.01, "suffix:s") var backfire_cooldown: float = 0.16
@export_range(0.1, 5.0, 0.1, "suffix:s") var backfire_burst_duration: float = 1.5
@export_range(0.2, 5.0, 0.1, "suffix:s") var backfire_full_load_build_time: float = 2.0
@export_range(0.05, 0.6, 0.01, "suffix:s") var backfire_bang_interval: float = 0.18

@export_group("Backfire - RPM and Pitch Impulses")
@export var backfire_rpm_kick_enabled: bool = false
@export_range(0.0, 0.2, 0.005) var backfire_rpm_kick_amount: float = 0.08
## Kurzer reiner Klangimpuls; verändert weder rpm_position noch ACC/DCC-Richtung.
@export_range(0.0, 0.08, 0.001) var backfire_pitch_kick: float = 0.018

# Laufzeitwerte; die bekannten Namen bleiben für externe Leser erhalten.
var node_accel: BungeeEngineNode
var player_accel = null
var handle_accel: AudioStreamGeneratorPlayback
var acceleration_sound: AudioStreamWAV
var len_accel: float = 0.0
var node_dcc: BungeeEngineNode
var deceleration_sound: AudioStreamWAV
var len_dcc: float = 0.0
var node_transmission: BungeeEngineNode
var transmission_sound: AudioStreamWAV
var len_transmission: float = 0.0
var _last_audio_target_rpm: float = 0.0
var _use_dcc: bool = false
var _dcc_mix: float = 0.0
var _tone_falling: bool = false
var _tone_bus: StringName
var _tone_effect: AudioEffectLowPassFilter
var _highs_effect: AudioEffectHighShelfFilter
var _cabin_effect: AudioEffectLowPassFilter
var _cabin_character_effect: AudioEffectHighShelfFilter
var _reverb_effect: AudioEffectReverb
var _reverb_mix: float = 0.0
var _cabin_mix: float = 0.0
var _hard_limiter_effect: AudioEffectHardLimiter
var _output_sample_rate: int = 44100
## Optionaler Simulator-Impuls, getrennt von RPM und dem exportierten Grund-Pitch.
## Kein Einfluss auf Richtungserkennung, Idle-/Limiter-Bereiche oder DCC-Auswahl.
var simulator_pitch_modulation: float = 1.0:
	set(value):
		if is_finite(value):
			simulator_pitch_modulation = clampf(value, 0.9, 1.1)
var _idle_playback: AudioStreamPlayback
var _limiter_playback: AudioStreamPlayback
var _idle_mix: float = 0.0
var _limiter_mix: float = 0.0
var rpm_follow_distance_seconds: float = 0.0
var rpm_follow_distance_normalized: float = 0.0
var _car_folders: Array[String] = []
var _transmission_files: Array[String] = []
var transmission_name: String = "Keine"
var _shift_up_sound_files: Array[String] = []
var _shift_down_sound_files: Array[String] = []
var shift_up_sound_name: String = "Keine"
var shift_down_sound_name: String = "Keine"
var _shift_sound_playback: AudioStreamPlayback
var _shift_sound_playback_gain: float = 1.0
var _shift_sound_playback_pitch: float = 1.0
var _skid_files: Array[String] = []
var skid_name: String = "Keine"
var _skid_playback: AudioStreamPlayback
var _skid_target: float = 0.0
var _skid_mix: float = 0.0
var _supercharger_files: Array[String] = []
var supercharger_name: String = "Keine"
var _supercharger_playback: AudioStreamPlayback
var _turbo_files: Array[String] = []
var _bov_files: Array[String] = []
var turbo_name: String = "Keine"
var bov_name: String = "Keine"
var _turbo_playback: AudioStreamPlayback
var _bov_playback: AudioStreamPlayback
var _turbo_boost: float = 0.0
var _last_turbo_throttle: float = 0.0
var _last_transmission_shifting: bool = false
var _simulator_supercharger_enabled: bool = false
var _simulator_turbo_enabled: bool = false
var _simulator_limiter_cut_active: bool = false
var _simulator_limiter_cut_strength: float = 1.0
var _limiter_cut_pitch_factor: float = 1.0
var _stationary_grain_phase: float = 0.0
var _stationary_grain_mix: float = 0.0
var _backfire_files: Array[String] = []
var backfire_name: String = "Keine"
var _backfire_playback: AudioStreamPlayback
var _backfire_playback_gain: float = 0.0
var _backfire_playback_pitch: float = 1.0
var _backfire_voices: Array[Dictionary] = []
var _backfire_cooldown_timer: float = 0.0
var _backfire_pitch_offset: float = 0.0
var _backfire_burst_remaining: float = 0.0
var _backfire_next_bang_timer: float = 0.0
var _backfire_bangs_remaining: int = -1
var _backfire_burst_load: float = 0.0
var _backfire_burst_rpm: float = 0.0
var _backfire_load_energy: float = 0.0
var _backfire_rpm_kick_offset: float = 0.0
var _backfire_coast_shift_pending: float = 0.0
var _backfire_coast_shift_rise_seen: bool = false
var _backfire_coast_shift_start_rpm: float = 0.0
var _last_backfire_audio_rpm: float = 0.0
var _engine_start_path: String = ""
var _engine_kill_path: String = ""
var _engine_state_playback: AudioStreamPlayback
var _engine_state_playback_pitch: float = 1.0
var _engine_state_playback_gain: float = 1.0
var _motor_mix: float = 1.0
var _motor_mix_target: float = 1.0
var _engine_start_rpm_offset: float = 0.0
var _engine_start_waiting: bool = false
var backfire_trigger_count: int = 0
var backfire_bang_count: int = 0
var bov_trigger_count: int = 0
var _backfire_release_armed: bool = false
var _backfire_peak_load: float = 0.0
var _transmission_throttle: float = 0.0
var _transmission_speed_normalized: float = 0.0
var _transmission_is_reversing: bool = false
var _transmission_gear: int = 1
var _last_transmission_gear: int = 1
var _transmission_gear_count: int = 1
var _transmission_is_shifting: bool = false
var _transmission_handbrake: float = 0.0
var _simulator_source: Node
var _external_last_rpm_command: float = 0.0
var _external_peak_rpm: float = 0.0
var _external_backfire_charge: float = 0.0
var _external_backfire_release_energy: float = 0.0
var _external_backfire_release_active: bool = false
var _last_external_manual_turbo_boost: float = 0.0
var _external_manual_turbo_peak: float = 0.0
var _external_manual_bov_releasing: bool = false
var _last_bov_release_boost: float = 0.0
const EXTERNAL_BACKFIRE_MIN_RPM: float = 0.30

## 24x bei einer 5-s-Bank entspricht 4.8 normalisierten Banklängen pro Sekunde.
## Das Limit skaliert mit der WAV-Länge, bleibt aber bei 64x hart abgesichert.
const REFERENCE_BANK_LENGTH: float = 5.0
const REFERENCE_MAX_PLAYBACK_SPEED: float = 24.0
const HARD_MAX_PLAYBACK_SPEED: float = 64.0
const BUFFER_LENGTH: float = 0.12
const SWITCH_FADE_SECONDS: float = 0.004
const EFFECT_AUDIO_FOLLOW: float = 20.0

#region Lebenszyklus und Audio-RPM-Steuerung
func _ready() -> void:
	_setup_tone()
	_use_exported_open_sound_folders()
	_scan_soundbank()
	_reload_sound()
	if live_input_mode == LiveInputMode.EXTERNAL:
		_simulator_source = self
	_external_last_rpm_command = clampf(rpm_position, 0.0, 1.0)
	_external_peak_rpm = _external_last_rpm_command
	_last_external_manual_turbo_boost = clampf(turbo_boost, 0.0, 1.0)
	_external_manual_turbo_peak = _last_external_manual_turbo_boost

func _use_exported_open_sound_folders() -> void:
	if OS.has_feature("editor"):
		return
	var open_sound_root := OS.get_executable_path().get_base_dir().path_join("assets/sounds")
	var vehicles := open_sound_root.path_join("Vehicles")
	var effects := open_sound_root.path_join("Effects")
	if DirAccess.dir_exists_absolute(vehicles):
		soundbank_path = vehicles
	if DirAccess.dir_exists_absolute(effects):
		effects_path = effects

func _exit_tree() -> void:
	_destroy_audio()
	var bus_index := AudioServer.get_bus_index(_tone_bus)
	if bus_index > 0:
		AudioServer.remove_bus(bus_index)
	_tone_effect = null
	_highs_effect = null
	_cabin_effect = null
	_cabin_character_effect = null
	_reverb_effect = null
	_hard_limiter_effect = null

func _physics_process(delta: float) -> void:
	if not is_instance_valid(node_accel) or handle_accel == null:
		return
	if live_input_mode == LiveInputMode.EXTERNAL and automatic_load_from_rpm:
		var rpm_command := clampf(rpm_position, 0.0, 1.0)
		var command_delta := rpm_command - _external_last_rpm_command
		if command_delta > 0.0001:
			# Neue Last beendet nur noch kommende Pops; ein bereits gestarteter
			# einzelner WAV-Knall darf natürlich ausklingen.
			_external_backfire_release_active = false
			_external_backfire_release_energy = 0.0
			_backfire_burst_remaining = 0.0
			if throttle <= 0.05:
				_external_peak_rpm = rpm_command
			else:
				_external_peak_rpm = maxf(_external_peak_rpm, rpm_command)
			throttle = 1.0
			# Schnelles Ziehen des Reglers baut genauso Last auf wie langsames
			# Hochdrehen. Nur reale Physics-Zeit wäre hier praktisch unhörbar.
		elif command_delta < -0.0001:
			throttle = 0.0
			if backfire_enabled and automatic_backfire_trigger and _external_backfire_charge > 0.01:
				_trigger_external_backfire_charge(_external_backfire_charge, maxf(_external_peak_rpm, rpm_command))
			if automatic_backfire_trigger:
				_external_backfire_charge = 0.0
		# Die Ladung entspricht der höchsten erreichten RPM, nicht der Haltedauer:
		# 0.1 RPM kann niemals zu einer vollen Salve werden, 1.0 RPM dagegen schon.
		if backfire_enabled and automatic_backfire_trigger and throttle > 0.5:
			_external_backfire_charge = maxf(_external_backfire_charge, rpm_command)
		elif not backfire_enabled or not automatic_backfire_trigger:
			_external_backfire_charge = 0.0
		_external_last_rpm_command = rpm_command
	_update_transmission_inputs(delta)
	_backfire_cooldown_timer = maxf(0.0, _backfire_cooldown_timer - delta)
	_update_backfire_burst(delta)
	_backfire_pitch_offset = move_toward(_backfire_pitch_offset, 0.0, delta * 0.35)
	_backfire_rpm_kick_offset = move_toward(_backfire_rpm_kick_offset, 0.0, delta * 0.25)
	_engine_start_rpm_offset = move_toward(_engine_start_rpm_offset, 0.0, delta * 1.5)
	rpm_position = clampf(rpm_position, 0.0, 1.0)
	var audio_target_rpm := clampf(rpm_position + _backfire_rpm_kick_offset + _engine_start_rpm_offset, 0.0, 1.0)
	# ACC/DCC folgt ausschließlich der befohlenen RPM-Zielrichtung. Die Bewegung
	# des nachlaufenden Bungee-Cursors bestimmt, welche Aufnahme gerade wirklich
	# aufholen muss. Eine Totzone verhindert das frühere +/- Flattern um null.
	var current_seconds := node_accel.get_playback_position()
	var direction_distance := audio_target_rpm - current_seconds / maxf(len_accel, 0.001)
	const DIRECTION_DISTANCE_DEADZONE := 0.00035
	# Bei Gas bleibt ACC stabil. Ohne Gas zählt die tatsächliche Reststrecke:
	# Downshift-Ziel oberhalb des Audiocursors = ACC, Ausrollen darunter = DCC.
	# Innerhalb der Totzone bleibt die letzte Stimme stehen und kann nicht wobbeln.
	if limiter_cut_uses_dcc and _simulator_limiter_cut_active and direction_distance < -DIRECTION_DISTANCE_DEADZONE:
		_use_dcc = is_instance_valid(node_dcc)
		_tone_falling = true
	elif live_input_mode == LiveInputMode.EXTERNAL:
		# Bei einer eigenen Fahrzeuglogik ist das gelieferte Gaspedal eindeutig:
		# Gas = ACC, kein Gas = DCC. Dadurch wirkt der Regler auch bei konstanter RPM.
		_use_dcc = throttle <= 0.05 and is_instance_valid(node_dcc)
		_tone_falling = _use_dcc
	elif is_instance_valid(_simulator_source) and not _transmission_is_shifting and _transmission_throttle > 0.1:
		_use_dcc = false
		_tone_falling = false
	elif direction_distance > DIRECTION_DISTANCE_DEADZONE:
		_use_dcc = false
		_tone_falling = false
	elif direction_distance < -DIRECTION_DISTANCE_DEADZONE:
		_use_dcc = is_instance_valid(node_dcc)
		_tone_falling = true
	_last_audio_target_rpm = audio_target_rpm
	_update_tone(delta)
	var target_seconds := audio_target_rpm * len_accel
	rpm_follow_distance_seconds = target_seconds - current_seconds
	rpm_follow_distance_normalized = rpm_follow_distance_seconds / len_accel
	# Der tiefe Pitch färbt ausschließlich den harten Abwärts-Cut. Er darf nicht
	# während des anschließenden Limiter-Pushs aktiv bleiben, sonst wirkt der
	# Rücksprung bei sehr kleinen Werten breit und langsam.
	var limiter_is_cutting_down := _simulator_limiter_cut_active and rpm_follow_distance_seconds < -0.0001
	var limiter_pitch_target := LIMITER_CUT_PITCH if limiter_is_cutting_down else 1.0
	var limiter_pitch_speed := 300.0 if limiter_is_cutting_down else 500.0
	_limiter_cut_pitch_factor = move_toward(_limiter_cut_pitch_factor, limiter_pitch_target, delta * limiter_pitch_speed)
	var accel_speed_limit := _get_length_scaled_speed_limit(len_accel)
	# Regler arbeitet ausdrücklich im normalisierten 0..1-RPM-Raum. Für Bungee
	# wird das Ergebnis danach in reale WAV-Sekunden zurückübersetzt.
	var limiter_cut_multiplier := _simulator_limiter_cut_strength if _simulator_limiter_cut_active and rpm_follow_distance_normalized < 0.0 else 1.0
	var follow_strength := _stable_follow_rate(_get_effective_audio_follow(), delta, node_accel.pitch)
	var target_brake := _get_follow_target_brake(absf(rpm_follow_distance_normalized))
	var accel_speed := rpm_follow_distance_normalized * follow_strength * target_brake * limiter_cut_multiplier * len_accel
	# Den letzten Rest wirklich abspielen, statt den Limiter vorzeitig auszulösen.
	# Kein Seek: Nur am angeforderten Dateiende eine kleine Mindestgeschwindigkeit.
	if audio_target_rpm >= 1.0 and rpm_follow_distance_normalized > 0.0 and rpm_follow_distance_normalized <= 0.0015:
		accel_speed = maxf(accel_speed, len_accel * 0.03)
	# Bungee klingt bei einer nur noch winzigen Cursor-Geschwindigkeit unter Last
	# schnell wie ein festgehaltener Grain. Bis unmittelbar ans Ziel halten wir
	# deshalb eine kleine Mindestbewegung, ohne das Ziel zu überschießen.
	var stationary_load := stationary_grain_protection and _transmission_throttle > 0.1 \
		and not _transmission_is_shifting and not _simulator_limiter_cut_active
	if stationary_load and target_brake >= 0.999 and absf(rpm_follow_distance_seconds) > 0.0001 \
		and absf(accel_speed) < stationary_min_scan_speed:
		var exact_remaining_speed := absf(rpm_follow_distance_seconds) / maxf(delta, 1.0 / 240.0)
		var protected_speed := minf(stationary_min_scan_speed, exact_remaining_speed)
		accel_speed = signf(rpm_follow_distance_seconds) * protected_speed
	# Am vollständig erreichten Ziel bleibt der Cursor korrekt stehen. Eine sehr
	# kleine interne Pitchbewegung hält nur die Granularphase lebendig; RPM, Dist,
	# ACC/DCC-Richtung und Schaltlogik bleiben vollkommen unberührt.
	# Nicht erst bei mathematisch exakt null aktivieren: Gerade das sehr langsame
	# Kriechen im letzten Gang erzeugt den hörbaren Phaser. 20 ms WAV-Abstand sind
	# klein genug, um echte RPM-Bewegungen und Schaltvorgänge sicher auszuschließen.
	var stationary_target := stationary_load and absf(rpm_follow_distance_seconds) <= 0.02 \
		and absf(accel_speed) <= maxf(stationary_min_scan_speed, 0.01)
	_stationary_grain_mix = move_toward(_stationary_grain_mix, 1.0 if stationary_target else 0.0, delta * 5.0)
	if _stationary_grain_mix > 0.0:
		_stationary_grain_phase = fmod(_stationary_grain_phase + delta * clampf(stationary_motion_frequency_hz, 0.1, 20.0), 1.0)
	if _simulator_limiter_cut_active and rpm_follow_distance_seconds < 0.0:
		# Die Cut-Stärke darf den Audio-Cursor niemals unter die eingestellte
		# Rücksprungposition schießen. So beginnt der anschließende, vom Wheelspin
		# normalisierte Hochlauf immer exakt am selben Punkt.
		if limiter_cut_instant:
			# 12 ms sind hart genug für einen echten Cut, erhalten aber eine stetige
			# Wellenform und vermeiden das Knacken eines Sample-Positionssprungs.
			# Bungee koppelt bei Pitch != 1 die effektive Cursorbewegung an den Pitch.
			# Gegenkompensation hält die Cut-Dauer bei jedem Bass-Pitch identisch.
			var effective_cut_pitch := maxf(_limiter_cut_pitch_factor, 0.125)
			accel_speed = (rpm_follow_distance_seconds / 0.012) / effective_cut_pitch
		else:
			var exact_cut_speed := rpm_follow_distance_seconds / maxf(delta, 1.0 / 240.0)
			accel_speed = maxf(accel_speed, exact_cut_speed)
	node_accel.speed = clampf(
		accel_speed,
		-accel_speed_limit,
		accel_speed_limit
	)
	# Keine Änderung der Generatorrate: Pitch und RPM-Verfolgung bleiben getrennt.
	player_accel.volume_linear = maxf(acceleration_volume, 0.0) * db_to_linear(output_headroom_db)
	if is_instance_valid(node_dcc):
		# DCC ist zeitlich umgekehrt aufgenommen. Beide Stimmen laufen auch
		# stumm weiter, damit der direkte Wechsel keinen Neustart benötigt.
		var dcc_distance := (1.0 - audio_target_rpm) * len_dcc - node_dcc.get_playback_position()
		var dcc_distance_normalized := dcc_distance / len_dcc
		var dcc_target_brake := _get_follow_target_brake(absf(dcc_distance_normalized))
		var dcc_speed := dcc_distance_normalized * follow_strength * dcc_target_brake * limiter_cut_multiplier * len_dcc
		if _simulator_limiter_cut_active and dcc_distance > 0.0:
			if limiter_cut_instant:
				var effective_dcc_cut_pitch := maxf(_limiter_cut_pitch_factor, 0.125)
				dcc_speed = (dcc_distance / 0.012) / effective_dcc_cut_pitch
			else:
				var exact_dcc_cut_speed := dcc_distance / maxf(delta, 1.0 / 240.0)
				dcc_speed = minf(dcc_speed, exact_dcc_cut_speed)
		var dcc_speed_limit := _get_length_scaled_speed_limit(len_dcc)
		node_dcc.speed = clampf(dcc_speed, -dcc_speed_limit, dcc_speed_limit)
	if is_instance_valid(node_transmission):
		# Die WAV folgt der Getriebe-/Fahrzeuggeschwindigkeit, nicht der Motor-RPM.
		var transmission_target := _transmission_speed_normalized * len_transmission
		var transmission_distance := transmission_target - node_transmission.get_playback_position()
		var transmission_dist_normalized := transmission_distance / len_transmission
		var transmission_speed := transmission_dist_normalized * _stable_follow_rate(distance_strength, delta, node_transmission.pitch) * len_transmission
		var transmission_limit := _get_length_scaled_speed_limit(len_transmission)
		node_transmission.speed = clampf(transmission_speed, -transmission_limit, transmission_limit)
	_fill_output_buffer()

## Kompakte Laufzeit-API für ein eigenes Fahrzeugsystem. RPM bleibt wie bisher
## normalisiert (0..1), Geschwindigkeit wird real in km/h übergeben.
func update_live_inputs(
	new_rpm_position: float,
	new_throttle: float,
	new_speed_kmh: float,
	new_current_gear: int = 1,
	new_is_shifting: bool = false
) -> void:
	live_input_mode = LiveInputMode.EXTERNAL
	automatic_load_from_rpm = false
	rpm_position = clampf(new_rpm_position, 0.0, 1.0)
	throttle = clampf(new_throttle, 0.0, 1.0)
	speed_kmh = maxf(new_speed_kmh, 0.0)
	current_gear = clampi(new_current_gear, 1, maxi(number_of_gears, 1))
	is_shifting = new_is_shifting
	_simulator_source = self

## Einfachste externe Steuerung: Nur km/h und Gas liefern. Die Audio-RPM wird
## automatisch aus speed_kmh / max_speed_kmh berechnet.
func update_vehicle_inputs(
	new_speed_kmh: float,
	new_throttle: float,
	new_current_gear: int = 1,
	new_is_shifting: bool = false
) -> void:
	live_input_mode = LiveInputMode.EXTERNAL
	automatic_load_from_rpm = false
	speed_kmh = maxf(new_speed_kmh, 0.0)
	throttle = clampf(new_throttle, 0.0, 1.0)
	current_gear = clampi(new_current_gear, 1, maxi(number_of_gears, 1))
	is_shifting = new_is_shifting
	_simulator_source = self

## Klare Laufzeitbefehle fuer eigene Fahrzeugsysteme und Start-/Stop-Schalter.
func start_engine() -> void:
	engine_running = true

func stop_engine() -> void:
	engine_running = false

## Aufladung kann automatisch aus Audio-RPM/Gas oder mit eigenem Ladedruck laufen.
func update_forced_induction(turbo_on: bool, boost: float = 0.0, supercharger_on: bool = false, auto_boost: bool = true) -> void:
	turbo_enabled = turbo_on
	automatic_turbo_boost = auto_boost
	if not auto_boost:
		turbo_boost = clampf(boost, 0.0, 1.0)
	supercharger_enabled = supercharger_on

## Direkte Ereignisse für Systeme, die ihre Gangzahl nicht an den Node binden.
func trigger_shift_up_sound() -> void:
	_trigger_shift_sound(true)

func trigger_shift_down_sound() -> void:
	_trigger_shift_sound(false)

func trigger_bov_sound(boost: float = -1.0) -> void:
	_trigger_bov(turbo_boost if boost < 0.0 else clampf(boost, 0.0, 1.0))

func trigger_backfire_sound(load_strength: float = 1.0) -> void:
	if not backfire_enabled:
		return
	var audio_rpm := clampf(rpm_position, 0.0, 1.0) if live_input_mode == LiveInputMode.EXTERNAL else (node_accel.get_playback_position() / maxf(len_accel, 0.001) if is_instance_valid(node_accel) else rpm_position)
	var strength := clampf(load_strength, 0.0, 1.0)
	_trigger_backfire(maxf(strength, 0.5), audio_rpm, true)
	_external_backfire_charge = 0.0

func _get_max_speed_kmh() -> float:
	return maxf(max_speed_kmh, 1.0)

func _get_reverse_max_speed_kmh() -> float:
	return maxf(max_speed_kmh, 1.0)

func _stable_follow_rate(strength: float, delta: float, pitch: float = 1.0) -> float:
	# Ein proportionaler Regler mit 100 * dt ueberschiesst bereits bei 60 Hz.
	# Bungee verarbeitet zusaetzlich gepufferte Grains: die Reaktion kommt spaeter
	# als der neue Speed-Befehl. Exponentielle Annaeherung inkl. Grain-Reserve
	# verhindert das selbst erzeugte +/- Pendeln bei festem RPM-Ziel.
	# Tiefer Pitch verlaengert den Grain-Nachlauf und braucht mehr Reserve.
	var response_window := maxf(delta, 1.0 / 240.0) + 0.025 / clampf(pitch, 0.125, 1.0)
	return (1.0 - exp(-maxf(strength, 0.0) * response_window)) / response_window

func _get_follow_target_brake(distance_normalized: float) -> float:
	# Limiter und Struggle besitzen bereits ihre eigene feste Reaktionsrate. Die
	# allgemeine Zielbremsung darf diese Effekte nicht nochmals verlaengern.
	if _uses_fixed_effect_audio_follow():
		return 1.0
	var brake_distance := maxf(follow_target_brake_distance, 0.0)
	var brake_strength := clampf(follow_target_brake_strength, 0.0, 1.0)
	if brake_distance <= 0.0 or brake_strength <= 0.0:
		return 1.0
	var approach := smoothstep(0.0, brake_distance, maxf(distance_normalized, 0.0))
	return lerpf(1.0 - brake_strength, 1.0, approach)

func _get_effective_audio_follow() -> float:
	if _uses_fixed_effect_audio_follow():
		return EFFECT_AUDIO_FOLLOW
	return distance_strength

func _uses_fixed_effect_audio_follow() -> bool:
	return is_instance_valid(_simulator_source) and _simulator_source.has_method("uses_fixed_effect_audio_follow") \
		and bool(_simulator_source.call("uses_fixed_effect_audio_follow"))

func get_audio_rpm_normalized() -> float:
	if not is_instance_valid(node_accel) or acceleration_sound == null or len_accel <= 0.0:
		return clampf(rpm_position, 0.0, 1.0)
	var position := node_accel.get_playback_position()
	# C++ begrenzt auf den letzten Sampleframe, nicht auf die Zeit dahinter.
	# Halber Sampleframe Toleranz gleicht nur Float-Rundung aus.
	var last_frame_seconds := len_accel - 1.0 / acceleration_sound.mix_rate
	if position >= last_frame_seconds - 0.5 / acceleration_sound.mix_rate:
		return 1.0
	return clampf(position / len_accel, 0.0, 1.0)

func _get_length_scaled_speed_limit(bank_length: float) -> float:
	var normalized_limit := REFERENCE_MAX_PLAYBACK_SPEED / REFERENCE_BANK_LENGTH
	return minf(HARD_MAX_PLAYBACK_SPEED, maxf(bank_length, 0.001) * normalized_limit)

#endregion

#region Audio-Mix - Stimmen und Generator
func _render_output_frames(frame_count: int) -> PackedVector2Array:
	# Beide Synthesestimmen liefern dieselbe Anzahl Frames auf derselben Uhr.
	# Einstellbarer Stimmenübergang, keine zusätzliche RPM-Glättung.
	# Kein zweiter Generator, kein Neustart und kein Seek beim Umschalten.
	var stationary_pitch := 1.0 + sin(_stationary_grain_phase * TAU) * stationary_pitch_motion * _stationary_grain_mix
	var engine_pitch_factor := engine_pitch * simulator_pitch_modulation * _limiter_cut_pitch_factor * (1.0 + _backfire_pitch_offset) * stationary_pitch
	node_accel.pitch = engine_pitch_factor
	if is_instance_valid(node_dcc):
		node_dcc.pitch = engine_pitch_factor
	var begin_rpm := node_accel.get_playback_position() / len_accel
	var acc := node_accel.render_audio_frames(frame_count)
	var end_rpm := node_accel.get_playback_position() / len_accel
	if not is_instance_valid(node_dcc):
		_dcc_mix = 0.0
		var acc_mix := _mix_transmission_frames(_mix_loop_frames(acc, begin_rpm, end_rpm), begin_rpm, end_rpm)
		acc_mix = _mix_skid_frames(acc_mix)
		return _mix_shift_sound_frames(_mix_engine_state_frames(_mix_backfire_frames(_mix_turbo_frames(_mix_supercharger_frames(acc_mix, begin_rpm, end_rpm), begin_rpm, end_rpm))))
	var dcc := node_dcc.render_audio_frames(frame_count)
	if acc.size() != frame_count or dcc.size() != frame_count:
		push_error("Engine: unvollständiger Audioblock; Wiedergabe gestoppt.")
		player_accel.stop()
		set_physics_process(false)
		return PackedVector2Array()
	var engine_mix := _mix_transmission_frames(_mix_loop_frames(_mix_voice_frames(acc, dcc), begin_rpm, end_rpm), begin_rpm, end_rpm)
	engine_mix = _mix_skid_frames(engine_mix)
	return _mix_shift_sound_frames(_mix_engine_state_frames(_mix_backfire_frames(_mix_turbo_frames(_mix_supercharger_frames(engine_mix, begin_rpm, end_rpm), begin_rpm, end_rpm))))

func _mix_shift_sound_frames(engine_frames: PackedVector2Array) -> PackedVector2Array:
	if engine_frames.is_empty() or _shift_sound_playback == null:
		return engine_frames
	var result := engine_frames.duplicate()
	var shot := _shift_sound_playback.mix_audio(_shift_sound_playback_pitch, result.size())
	for i in range(mini(result.size(), shot.size())):
		result[i] += shot[i] * _shift_sound_playback_gain
	if shot.size() < result.size():
		_shift_sound_playback.stop()
		_shift_sound_playback = null
	return result

func _mix_engine_state_frames(engine_frames: PackedVector2Array) -> PackedVector2Array:
	if engine_frames.is_empty():
		return engine_frames
	var result := engine_frames.duplicate()
	var state_frames := _engine_state_playback.mix_audio(_engine_state_playback_pitch, result.size()) if _engine_state_playback != null else PackedVector2Array()
	# Kein Fade: Starter/Kill und Motorzustand wechseln bewusst direkt.
	_motor_mix = _motor_mix_target
	for i in range(result.size()):
		result[i] *= _motor_mix
		if i < state_frames.size():
			result[i] += state_frames[i] * _engine_state_playback_gain
	if _engine_state_playback != null and state_frames.size() < result.size():
		_engine_state_playback.stop()
		_engine_state_playback = null
		if _engine_start_waiting and engine_running:
			_begin_engine_after_start()
	return result

func _mix_backfire_frames(engine_frames: PackedVector2Array) -> PackedVector2Array:
	if engine_frames.is_empty() or _backfire_voices.is_empty() or backfire_volume <= 0.0:
		return engine_frames
	var result := engine_frames.duplicate()
	for voice_index in range(_backfire_voices.size() - 1, -1, -1):
		var voice: Dictionary = _backfire_voices[voice_index]
		var playback: AudioStreamPlayback = voice["playback"]
		var shot := playback.mix_audio(float(voice["pitch"]), engine_frames.size())
		for i in range(mini(result.size(), shot.size())):
			result[i] += shot[i] * backfire_volume * float(voice["gain"])
		if shot.size() < result.size():
			playback.stop()
			_backfire_voices.remove_at(voice_index)
			if playback == _backfire_playback:
				_backfire_playback = null
	return result

func _mix_turbo_frames(engine: PackedVector2Array, begin_rpm: float, end_rpm: float) -> PackedVector2Array:
	if engine.is_empty():
		return engine
	var result := engine.duplicate()
	var audio_rpm := clampf((begin_rpm + end_rpm) * 0.5, 0.0, 1.0)
	if _simulator_turbo_enabled and turbo_volume > 0.0 and _turbo_playback != null:
		var spool_pitch := turbo_pitch * lerpf(0.65, 1.8, audio_rpm)
		var turbo := _turbo_playback.mix_audio(spool_pitch, result.size())
		if turbo.size() == result.size():
			for i in range(result.size()):
				result[i] += turbo[i] * turbo_volume * clampf(_turbo_boost, 0.0, 1.0)
	if _simulator_turbo_enabled and bov_volume > 0.0 and _bov_playback != null:
		var bov := _bov_playback.mix_audio(1.0, result.size())
		for i in range(mini(result.size(), bov.size())):
			result[i] += bov[i] * bov_volume
		if bov.size() < result.size():
			_bov_playback.stop()
			_bov_playback = null
	return result

func _mix_supercharger_frames(engine: PackedVector2Array, begin_rpm: float, end_rpm: float) -> PackedVector2Array:
	if not _simulator_supercharger_enabled or supercharger_volume <= 0.0 or engine.is_empty() or _supercharger_playback == null:
		return engine
	var audio_rpm := clampf((begin_rpm + end_rpm) * 0.5, 0.0, 1.0)
	var pitch := lerpf(supercharger_pitch_idle, supercharger_pitch_redline, audio_rpm) * simulator_pitch_modulation
	var supercharger := _supercharger_playback.mix_audio(pitch, engine.size())
	if supercharger.size() != engine.size():
		push_warning("Engine: Supercharger-WAV lieferte zu wenig Frames; Spur bleibt aus.")
		_supercharger_playback.stop()
		_supercharger_playback = null
		return engine
	var load_throttle := 0.0 if _transmission_is_shifting else clampf(_transmission_throttle, 0.0, 1.0)
	var load_level := lerpf(supercharger_coast_amount, 1.0, load_throttle)
	var rpm_level := smoothstep(0.01, 0.15, audio_rpm)
	var result := engine.duplicate()
	for i in range(result.size()):
		result[i] += supercharger[i] * supercharger_volume * load_level * rpm_level
	return result

func _mix_transmission_frames(engine: PackedVector2Array, begin_rpm: float, end_rpm: float) -> PackedVector2Array:
	# In R gehört der Getriebewhine zum Fahrzustand und läuft deshalb auch dann,
	# wenn der normale Vorwärts-Transmission-Schalter deaktiviert wurde.
	if (not transmission_enabled and not _transmission_is_reversing) or transmission_max_speed_volume <= 0.0 or engine.is_empty() or not is_instance_valid(node_transmission):
		return engine
	# Nicht die sofortige Zielgeschwindigkeit verwenden: Pitch und Lautstärke
	# folgen dem tatsächlich von Bungee erreichten Transmission-Cursor. Dadurch
	# kann der Whine dem restlichen Audio nicht künstlich vorauseilen.
	var transmission_audio_speed := clampf(node_transmission.get_playback_position() / maxf(len_transmission, 0.001), 0.0, 1.0)
	var speed_pitch := lerpf(transmission_pitch_low_speed, transmission_pitch_high_speed, transmission_audio_speed)
	node_transmission.pitch = transmission_pitch * speed_pitch * simulator_pitch_modulation
	var transmission := node_transmission.render_audio_frames(engine.size())
	if transmission.size() != engine.size():
		push_warning("Engine: Transmission-WAV lieferte zu wenig Frames; Motorsound übernimmt.")
		return engine
	var result := engine.duplicate()
	var drivetrain_throttle := 0.0 if _transmission_handbrake > 0.02 else clampf(_transmission_throttle, 0.0, 1.0)
	var load_level := 0.0 if _transmission_is_shifting else lerpf(transmission_coast_amount, 1.0, drivetrain_throttle)
	# Schon bei mittlerem Tempo hörbar; den Maximalpegel aber erst bei Vmax erreichen.
	var speed_level := smoothstep(0.005, 0.03, transmission_audio_speed) * lerpf(0.25, 1.0, sqrt(transmission_audio_speed))
	for i in range(result.size()):
		result[i] += transmission[i] * transmission_max_speed_volume * load_level * speed_level
	return result

func _mix_skid_frames(engine: PackedVector2Array) -> PackedVector2Array:
	if engine.is_empty():
		return engine
	# Schnelles Ansprechen, aber kurzes weiches Auslaufen gegen Knackser.
	var fade_step := 1.0 / maxf(0.06 * float(_output_sample_rate), 1.0)
	var result := engine.duplicate()
	var speed_pitch := lerpf(skid_pitch_low_speed, skid_pitch_high_speed, _transmission_speed_normalized)
	var skid := _skid_playback.mix_audio(speed_pitch, result.size()) if skid_enabled and _skid_playback != null else PackedVector2Array()
	for i in range(result.size()):
		_skid_mix = move_toward(_skid_mix, _skid_target if skid_enabled and _skid_playback != null else 0.0, fade_step)
		if i < skid.size():
			result[i] += skid[i] * skid_volume * _skid_mix
	return result

func _update_transmission_inputs(delta: float) -> void:
	if live_input_mode == LiveInputMode.EXTERNAL:
		_simulator_source = self
		# Im einfachen externen Modus darf ausschließlich der neue RPM-Charge-
		# Trigger Backfire steuern. Alte Simulator-Last darf nichts doppelt auslösen.
		_backfire_release_armed = false
		_backfire_peak_load = 0.0
		_simulator_turbo_enabled = turbo_enabled
		_simulator_supercharger_enabled = supercharger_enabled
		_update_external_turbo_boost(delta)
	elif _simulator_source == self:
		_simulator_source = null
	if not is_instance_valid(_simulator_source):
		for child in get_children():
			var has_gear := false
			var has_throttle := false
			var has_speed := false
			var has_shift := false
			for property in child.get_property_list():
				has_gear = has_gear or property.name == "current_gear"
				has_throttle = has_throttle or property.name == "throttle"
				has_speed = has_speed or property.name == "speed_kmh"
				has_shift = has_shift or property.name == "is_shifting"
			if has_gear and has_throttle and has_speed and has_shift:
				_simulator_source = child
				break
	if is_instance_valid(_simulator_source):
		var new_throttle := clampf(float(_simulator_source.get("throttle")), 0.0, 1.0)
		var new_gear := maxi(1, int(_simulator_source.get("current_gear")))
		var gear_went_down := new_gear < _last_transmission_gear
		var gear_went_up := new_gear > _last_transmission_gear
		if gear_went_up:
			_trigger_shift_sound(true)
		elif gear_went_down:
			_trigger_shift_sound(false)
		_transmission_gear = new_gear
		_transmission_gear_count = maxi(1, int(_simulator_source.get("number_of_gears")))
		var new_shifting := bool(_simulator_source.get("is_shifting"))
		_transmission_is_reversing = bool(_simulator_source.get("is_reversing"))
		_transmission_handbrake = clampf(float(_simulator_source.get("handbrake")), 0.0, 1.0)
		_simulator_supercharger_enabled = bool(_simulator_source.get("supercharger_enabled"))
		_simulator_turbo_enabled = bool(_simulator_source.get("turbo_enabled"))
		_simulator_limiter_cut_active = bool(_simulator_source.get("_artificial_limiter_cut_active"))
		_simulator_limiter_cut_strength = maxf(float(_simulator_source.get("artificial_rpm_limiter_cut_strength")), 1.0)
		_turbo_boost = clampf(float(_simulator_source.get("turbo_boost")), 0.0, 1.0)
		# Der einfache externe Modus wird bewusst vollständig von der direkten
		# RPM-Position gesteuert. Er darf nicht auf den Bungee-Cursor warten.
		# Beim Loslassen zählt extern die zuvor erreichte Spitzen-RPM. Würde hier
		# bereits die neue niedrige Reglerposition gelten, blockiert Min RPM jeden
		# vollständigen Lupfer bis 0.
		var audio_rpm := maxf(clampf(rpm_position, 0.0, 1.0), _external_peak_rpm) if live_input_mode == LiveInputMode.EXTERNAL else (node_accel.get_playback_position() / maxf(len_accel, 0.001) if is_instance_valid(node_accel) else 0.0)
		var backfire_rpm_from := minf(backfire_min_audio_rpm, backfire_max_audio_rpm)
		var backfire_rpm_to := maxf(backfire_min_audio_rpm, backfire_max_audio_rpm)
		var audio_rpm_can_charge_backfire := audio_rpm >= backfire_rpm_from and audio_rpm <= backfire_rpm_to
		# Sobald nach dem Shift wieder Gas angenommen wird, ist Overrun vorbei.
		if new_throttle > 0.1 and not new_shifting and (_backfire_burst_remaining > 0.0 or not _backfire_voices.is_empty()):
			_stop_backfire_burst()
		# Restenergie nur unter echter Last aufbauen. Kurzes Antippen sammelt fast
		# nichts. Der Vorrat beginnt erst IM eingestellten Audio-RPM-Fenster.
		if live_input_mode != LiveInputMode.EXTERNAL and backfire_enabled and new_throttle >= backfire_min_load and not new_shifting and audio_rpm_can_charge_backfire:
			var rpm_load := lerpf(0.25, 1.0, clampf(audio_rpm, 0.0, 1.0))
			_backfire_load_energy = minf(_backfire_load_energy + delta * new_throttle * rpm_load, maxf(backfire_full_load_build_time, 0.2))
		var bov_release := (_last_turbo_throttle > 0.2 and new_throttle < 0.1) or (not _last_transmission_shifting and new_shifting)
		if bov_release and _turbo_boost > 0.03:
			_trigger_bov(_turbo_boost)
		# Eine Lastphase merken, bis das Gas wirklich losgelassen wurde. So geht
		# Backfire auch bei geglaetteten Eingaben (1.0 -> 0.3 -> 0.1 -> 0.0)
		# nicht verloren, nur weil der letzte einzelne Frame schon wenig Last hatte.
		if live_input_mode != LiveInputMode.EXTERNAL and backfire_enabled and new_throttle >= backfire_min_load and not new_shifting and audio_rpm_can_charge_backfire:
			_backfire_release_armed = true
			_backfire_peak_load = maxf(_backfire_peak_load, new_throttle)
		var throttle_released := _backfire_release_armed and new_throttle <= 0.1
		# Beim Schalten nur gelegentlich knallen, abhängig von der einfachen Stärke.
		var loaded_shift_started := _backfire_release_armed and not _last_transmission_shifting and new_shifting and randf() < lerpf(0.15, 0.65, backfire_strength)
		# Handschalter können die Audio-RPM schon VOR dem Einlegen anheben.
		# Deshalb den Downshift ab seinem Beginn beobachten, nicht erst danach.
		var coast_downshift_started := live_input_mode != LiveInputMode.EXTERNAL and not _last_transmission_shifting and new_shifting and int(_simulator_source.get("_pending_gear")) < new_gear
		var direct_downshift := gear_went_down and not _last_transmission_shifting and not coast_downshift_started
		if live_input_mode != LiveInputMode.EXTERNAL and backfire_enabled and engine_running and (coast_downshift_started or direct_downshift) and new_throttle <= 0.1 and backfire_strength > 0.0:
			# Nur einmal pro Gangwechsel würfeln, niemals jeden Audio-Frame.
			_backfire_coast_shift_pending = 1.0 if randf() < lerpf(0.25, 0.85, clampf(backfire_strength, 0.0, 1.0)) else 0.0
			_backfire_coast_shift_start_rpm = _last_backfire_audio_rpm
			_backfire_coast_shift_rise_seen = false
		var backfire_release := throttle_released or loaded_shift_started
		if backfire_release:
			_trigger_backfire(maxf(_backfire_peak_load, _last_turbo_throttle), audio_rpm)
			if live_input_mode == LiveInputMode.EXTERNAL:
				_external_peak_rpm = clampf(rpm_position, 0.0, 1.0)
			_backfire_release_armed = false
			_backfire_peak_load = 0.0
			# Die Lastphase ist mit dem Lupfer verbraucht, auch wenn sie ausserhalb
			# des eingestellten Audio-RPM-Fensters lag.
			_backfire_load_energy = 0.0
		if not backfire_enabled or not engine_running or new_throttle > 0.1:
			_backfire_coast_shift_pending = 0.0
			_backfire_coast_shift_rise_seen = false
		if _backfire_coast_shift_pending > 0.0:
			_backfire_coast_shift_pending = maxf(0.0, _backfire_coast_shift_pending - delta)
			_backfire_coast_shift_rise_seen = _backfire_coast_shift_rise_seen or audio_rpm > _backfire_coast_shift_start_rpm + 0.0001
			# Einen erkannten RPM-Anstieg behalten, bis der Cooldown wirklich frei ist.
			# Vorher wurde die Vormerkung auch bei einem abgelehnten Trigger gelöscht.
			if _backfire_coast_shift_pending > 0.0 and _backfire_coast_shift_rise_seen and audio_rpm_can_charge_backfire and _backfire_cooldown_timer <= 0.0 and not _backfire_files.is_empty() and backfire_strength > 0.0:
				_backfire_load_energy = maxf(_backfire_load_energy, 0.12 * backfire_strength)
				_trigger_backfire(lerpf(0.45, 0.8, backfire_strength), audio_rpm)
				_backfire_coast_shift_pending = 0.0
		_last_backfire_audio_rpm = audio_rpm
		_transmission_throttle = new_throttle
		_transmission_is_shifting = new_shifting
		_last_turbo_throttle = new_throttle
		_last_transmission_shifting = new_shifting
		_last_transmission_gear = new_gear
		var max_speed := float(_simulator_source.call("_get_max_speed_kmh")) if _simulator_source.has_method("_get_max_speed_kmh") else 1.0
		var simulator_speed := maxf(float(_simulator_source.get("speed_kmh")), 0.0)
		var transmission_speed_limit := max_speed
		if _transmission_is_reversing and _simulator_source.has_method("_get_reverse_max_speed_kmh"):
			transmission_speed_limit = float(_simulator_source.call("_get_reverse_max_speed_kmh"))
		_transmission_speed_normalized = clampf(simulator_speed / maxf(transmission_speed_limit, 1.0), 0.0, 1.0)
		var speed_presence := smoothstep(2.0, 18.0, simulator_speed)
		var raw_wheelspin := clampf(float(_simulator_source.get("wheelspin")), 0.0, 1.0)
		var skid_gear := maxi(int(_simulator_source.get("current_gear")), 1)
		var skid_gears := maxi(int(_simulator_source.get("number_of_gears")), 1)
		var skid_gear_progress := float(skid_gear - 1) / float(maxi(skid_gears - 1, 1))
		# In Gang 1/2 ist kleiner Schlupf deutlich hörbar. In hohen Gängen muss
		# echter starker Schlupf vorliegen; winzige Traktionskorrekturen dürfen dort
		# keinen dauerhaften Reifensound auslösen.
		var audible_slip_start := lerpf(0.04, 0.30, skid_gear_progress)
		var wheelspin_skid := smoothstep(audible_slip_start, minf(audible_slip_start + 0.28, 1.0), raw_wheelspin)
		var handbrake_skid := _transmission_handbrake * speed_presence
		var wheel_lock_skid := speed_presence if bool(_simulator_source.get("downshift_wheel_lock")) else 0.0
		# Normales Bremsen ist kein Radblock-Signal und löst deshalb keinen Skid aus.
		_skid_target = clampf(maxf(wheelspin_skid, maxf(handbrake_skid, wheel_lock_skid)), 0.0, 1.0)
	else:
		# Kein heimlicher RPM-Fallback: Ohne Fahrzeuggeschwindigkeit steht das
		# Getriebe, auch wenn rpm_position manuell oder beim freien Rev steigt.
		_transmission_throttle = 0.0
		_transmission_speed_normalized = 0.0
		_transmission_is_reversing = false
		_skid_target = 0.0
		_transmission_gear = 1
		_last_transmission_gear = 1
		_transmission_gear_count = 1
		_simulator_limiter_cut_active = false
		_simulator_limiter_cut_strength = 1.0
		_transmission_is_shifting = false
		_transmission_handbrake = 0.0
		_turbo_boost = 0.0
		_last_turbo_throttle = 0.0
		_last_transmission_shifting = false
		_backfire_release_armed = false
		_backfire_peak_load = 0.0
		_backfire_load_energy = 0.0
		_simulator_supercharger_enabled = false
		_simulator_turbo_enabled = false

func _update_external_turbo_boost(delta: float) -> void:
	if not turbo_enabled:
		turbo_boost = move_toward(turbo_boost, 0.0, delta * automatic_turbo_spool_down_speed)
		_last_external_manual_turbo_boost = turbo_boost
		_external_manual_turbo_peak = 0.0
		_external_manual_bov_releasing = false
		return
	if not automatic_turbo_boost:
		turbo_boost = clampf(turbo_boost, 0.0, 1.0)
		var boost_delta := turbo_boost - _last_external_manual_turbo_boost
		if boost_delta > 0.005:
			# Nach einer abgeschlossenen Entladung beginnt ein vollständig neuer
			# Ladezyklus. Der alte hohe Peak darf nicht übernommen werden.
			if _external_manual_bov_releasing or _last_external_manual_turbo_boost <= 0.005:
				_external_manual_turbo_peak = turbo_boost
			else:
				_external_manual_turbo_peak = maxf(_external_manual_turbo_peak, turbo_boost)
			_external_manual_bov_releasing = false
		elif boost_delta < -0.005 and not _external_manual_bov_releasing and _external_manual_turbo_peak > 0.03:
			# Einmal aus dem gesamten gespeicherten Spitzendruck entladen. Weitere
			# Schritte bis 0 dürfen die laufende BOV-WAV nicht neu starten.
			_trigger_bov(_external_manual_turbo_peak)
			_external_manual_bov_releasing = true
		_last_external_manual_turbo_boost = turbo_boost
		return
	# Extern ist rpm_position die einzige zentrale Sound-Eingabe.
	var audio_rpm := clampf(rpm_position, 0.0, 1.0)
	var rpm_boost := smoothstep(clampf(automatic_turbo_spool_start_rpm, 0.0, 0.9), 1.0, clampf(audio_rpm, 0.0, 1.0))
	var target := rpm_boost * clampf(throttle, 0.0, 1.0)
	var speed := automatic_turbo_spool_up_speed if target > turbo_boost else automatic_turbo_spool_down_speed
	turbo_boost = move_toward(turbo_boost, target, delta * maxf(speed, 0.1))
	_last_external_manual_turbo_boost = turbo_boost
	_external_manual_turbo_peak = turbo_boost
	_external_manual_bov_releasing = false

func _mix_loop_frames(engine: PackedVector2Array, begin_rpm: float, end_rpm: float) -> PackedVector2Array:
	if _idle_playback == null and _limiter_playback == null:
		return engine
	var count := engine.size()
	if count == 0:
		return engine
	# Direkte WAV-Decoder, keine weiteren Player oder Generatoren. Godot
	# resampelt auf die AudioServer-Rate, die auch unser Generator verwendet.
	# Loops laufen stumm weiter und starten beim Einblenden nicht neu.
	var pitch_factor := engine_pitch * simulator_pitch_modulation * (1.0 + _backfire_pitch_offset)
	var idle := _idle_playback.mix_audio(pitch_factor, count) if _idle_playback != null else PackedVector2Array()
	var limiter := _limiter_playback.mix_audio(pitch_factor, count) if _limiter_playback != null else PackedVector2Array()
	var has_idle := idle.size() == count
	var has_limiter := limiter.size() == count
	if _idle_playback != null and not has_idle:
		push_warning("Engine: Idle-Loop lieferte zu wenig Frames; ACC/DCC übernimmt.")
		_idle_playback.stop()
		_idle_playback = null
	if _limiter_playback != null and not has_limiter:
		push_warning("Engine: Limiter-Loop lieferte zu wenig Frames; ACC/DCC übernimmt.")
		_limiter_playback.stop()
		_limiter_playback = null
	var step := 1.0 / maxf(1.0, SWITCH_FADE_SECONDS * _output_sample_rate)
	var result := engine.duplicate()
	for i in range(count):
		var audio_rpm := lerpf(begin_rpm, end_rpm, float(i + 1) / count)
		var idle_target := 1.0 - smoothstep(0.0, idle_fade_end, audio_rpm) if has_idle and idle_enabled else 0.0
		var limiter_target := smoothstep(limiter_fade_start, 1.0, audio_rpm) if has_limiter and limiter_enabled else 0.0
		_idle_mix = move_toward(_idle_mix, idle_target, step)
		_limiter_mix = move_toward(_limiter_mix, limiter_target, step)
		# Komplementäre Gewichte vermeiden eine zusätzliche Pegelspitze.
		var idle_weight := _idle_mix if has_idle else 0.0
		var limiter_weight := _limiter_mix if has_limiter else 0.0
		var base_weight := maxf(0.0, 1.0 - idle_weight - limiter_weight)
		result[i] = engine[i] * base_weight
		if has_idle:
			result[i] += idle[i] * idle_weight * idle_volume
		if has_limiter:
			result[i] += limiter[i] * limiter_weight * limiter_volume
	return result

func _mix_voice_frames(acc: PackedVector2Array, dcc: PackedVector2Array) -> PackedVector2Array:
	var target_mix := 1.0 if _use_dcc else 0.0
	# Der Limiter-Cut selbst ist deutlich kürzer als ein normaler ACC/DCC-Fade.
	# Deshalb muss DCC beim tatsächlichen Abwärtssprung sofort vollständig greifen;
	# sonst endet der Cut, bevor die DCC-Stimme überhaupt hörbar geworden ist.
	if limiter_cut_uses_dcc and _simulator_limiter_cut_active and _use_dcc:
		_dcc_mix = 1.0
		return dcc
	if acc_dcc_transition_ms <= 0.0:
		_dcc_mix = target_mix
		return dcc if _use_dcc else acc
	if _dcc_mix == target_mix:
		return dcc if _use_dcc else acc
	# Oben im Drehzahlband unterscheiden sich ACC und die rückwärts laufende DCC
	# klanglich am stärksten. Dort bekommt derselbe Regler etwas mehr reale Zeit,
	# statt bei 60 ms subjektiv wie ein harter Klangsprung zu wirken.
	var live_rpm := node_accel.get_playback_position() / maxf(len_accel, 0.001)
	var high_rpm_time_scale := lerpf(1.0, 1.75, smoothstep(0.55, 1.0, live_rpm))
	var fade_frames := maxi(1, ceili(acc_dcc_transition_ms * high_rpm_time_scale * 0.001 * _output_sample_rate))
	var step := 1.0 / float(fade_frames)
	var mixed := acc.duplicate()
	for i in range(mixed.size()):
		# Zustand bleibt über Blockgrenzen erhalten. Auch bei erneutem
		# Richtungswechsel mitten im Fade geht es ohne Gewichtssprung weiter.
		_dcc_mix = move_toward(_dcc_mix, target_mix, step)
		# Equal-Power statt linearer Lautstärkeüberblendung: In der Mitte fällt
		# nicht mehr plötzlich Klangenergie weg, was besonders bei hoher RPM wie
		# ein harter ACC->DCC-Schnitt klang.
		var fade_angle := _dcc_mix * PI * 0.5
		mixed[i] = acc[i] * cos(fade_angle) + dcc[i] * sin(fade_angle)
	return mixed

func _fill_output_buffer() -> void:
	var frames_needed := mini(handle_accel.get_frames_available(), 65536)
	if frames_needed <= 0:
		return
	var output := _render_output_frames(frames_needed)
	if not output.is_empty():
		handle_accel.push_buffer(output)

#endregion

#region Soundbank und WAV-Auswahl
func _scan_soundbank() -> void:
	_car_folders.clear()
	var directory := DirAccess.open(soundbank_path)
	if directory == null:
		return
	for folder in directory.get_directories():
		# Globale Zusatzsound-Ordner dürfen nicht als Fahrzeug erscheinen.
		if not folder.begins_with(".") and folder.to_lower() not in ["whine", "skid", "supercharger", "turbo", "bov", "backfire", "enginestate", "shiftup", "shiftdown"]:
			_car_folders.append(soundbank_path.path_join(folder))
	_car_folders.sort()

func _find_bank_sound(kind: String = "acc") -> AudioStreamWAV:
	if _car_folders.is_empty():
		return null
	var selected_index := clampi(car_index, 0, _car_folders.size() - 1)
	var folder := _car_folders[selected_index]
	var directory := DirAccess.open(folder)
	if directory == null:
		return null
	var files := directory.get_files()
	files.sort()
	for file_name in files:
		var lower_name := file_name.to_lower()
		var matches := lower_name.contains("acc") or lower_name.contains("_acl") or lower_name.begins_with("acl")
		if kind == "dcc":
			matches = lower_name.contains("dcc") or lower_name.contains("dcl") or lower_name.contains("decel") or lower_name.begins_with("dec")
		elif kind == "idle":
			matches = lower_name.contains("idle") or lower_name.ends_with("_idl.wav")
		elif kind == "limiter":
			matches = lower_name.contains("limit") or lower_name.contains("redline")
		elif kind == "transmission":
			matches = lower_name.contains("transmission") or lower_name.contains("gear_whine") or lower_name.contains("gearwhine") or lower_name.begins_with("whine")
		if lower_name.ends_with(".wav") and matches:
			return _load_wav(folder.path_join(file_name))
	return null

func _scan_transmission_bank() -> void:
	_transmission_files.clear()
	transmission_name = "Keine"
	var root_directory := DirAccess.open(effects_path)
	if root_directory == null:
		return
	var whine_folder := ""
	for folder_name in root_directory.get_directories():
		if folder_name.to_lower() == "whine":
			whine_folder = effects_path.path_join(folder_name)
			break
	if whine_folder.is_empty():
		return
	var whine_directory := DirAccess.open(whine_folder)
	if whine_directory == null:
		return
	var files := whine_directory.get_files()
	files.sort()
	for file_name in files:
		if file_name.to_lower().ends_with(".wav"):
			_transmission_files.append(whine_folder.path_join(file_name))
	if not _transmission_files.is_empty():
		var active_index := clampi(transmission_index, 0, _transmission_files.size() - 1)
		transmission_name = _transmission_files[active_index].get_file().get_basename()

func _reload_transmission_only() -> void:
	if is_instance_valid(node_transmission):
		node_transmission.free()
	node_transmission = null
	transmission_sound = null
	len_transmission = 0.0
	if _transmission_files.is_empty():
		transmission_name = "Keine"
		return
	var active_index := clampi(transmission_index, 0, _transmission_files.size() - 1)
	var selected_path := _transmission_files[active_index]
	transmission_name = selected_path.get_file().get_basename()
	transmission_sound = _load_wav(selected_path)
	if transmission_sound != null and is_instance_valid(node_accel):
		_load_transmission()

func _scan_skid_bank() -> void:
	_skid_files.clear()
	skid_name = "Keine"
	var root_directory := DirAccess.open(effects_path)
	if root_directory == null:
		return
	var skid_folder := ""
	for folder_name in root_directory.get_directories():
		if folder_name.to_lower() == "skid":
			skid_folder = effects_path.path_join(folder_name)
			break
	if skid_folder.is_empty():
		return
	var directory := DirAccess.open(skid_folder)
	if directory == null:
		return
	var files := directory.get_files()
	files.sort()
	for file_name in files:
		if file_name.to_lower().ends_with(".wav"):
			_skid_files.append(skid_folder.path_join(file_name))
	if not _skid_files.is_empty():
		var active_index := clampi(skid_index, 0, _skid_files.size() - 1)
		skid_name = _skid_files[active_index].get_file().get_basename()

func _reload_skid_only() -> void:
	if _skid_playback != null:
		_skid_playback.stop()
	_skid_playback = null
	_skid_mix = 0.0
	if _skid_files.is_empty():
		skid_name = "Keine"
		return
	var active_index := clampi(skid_index, 0, _skid_files.size() - 1)
	var selected_path := _skid_files[active_index]
	skid_name = selected_path.get_file().get_basename()
	var source := _load_wav(selected_path)
	_skid_playback = _create_wav_loop(source)

func _scan_supercharger_bank() -> void:
	_supercharger_files.clear()
	supercharger_name = "Keine"
	var root_directory := DirAccess.open(effects_path)
	if root_directory == null:
		return
	var supercharger_folder := ""
	for folder_name in root_directory.get_directories():
		if folder_name.to_lower() == "supercharger":
			supercharger_folder = effects_path.path_join(folder_name)
			break
	if supercharger_folder.is_empty():
		return
	var directory := DirAccess.open(supercharger_folder)
	if directory == null:
		return
	var files := directory.get_files()
	files.sort()
	for file_name in files:
		if file_name.to_lower().ends_with(".wav"):
			_supercharger_files.append(supercharger_folder.path_join(file_name))
	if not _supercharger_files.is_empty():
		var active_index := clampi(supercharger_index, 0, _supercharger_files.size() - 1)
		supercharger_name = _supercharger_files[active_index].get_file().get_basename()

func _reload_supercharger_only() -> void:
	if _supercharger_playback != null:
		_supercharger_playback.stop()
	_supercharger_playback = null
	if _supercharger_files.is_empty():
		supercharger_name = "Keine"
		return
	var active_index := clampi(supercharger_index, 0, _supercharger_files.size() - 1)
	var selected_path := _supercharger_files[active_index]
	supercharger_name = selected_path.get_file().get_basename()
	_supercharger_playback = _create_wav_loop(_load_wav(selected_path))

func _scan_turbo_banks() -> void:
	_turbo_files = _scan_global_wav_folder("Turbo")
	_bov_files = _scan_global_wav_folder("BOV")
	turbo_name = _selected_file_name(_turbo_files, turbo_index)
	bov_name = _selected_file_name(_bov_files, bov_index)

func _scan_backfire_bank() -> void:
	_backfire_files = _scan_global_wav_folder("Backfire")
	backfire_name = _selected_file_name(_backfire_files, backfire_index)

func _scan_engine_state_bank() -> void:
	_engine_start_path = ""
	_engine_kill_path = ""
	for path in _scan_global_wav_folder("EngineState"):
		var base_name := path.get_file().get_basename().to_lower()
		if _engine_start_path.is_empty() and base_name.contains("start"):
			_engine_start_path = path
		elif _engine_kill_path.is_empty() and (base_name.contains("kill") or base_name.contains("stop")):
			_engine_kill_path = path

func _scan_shift_sound_banks() -> void:
	_shift_up_sound_files = _scan_global_wav_folder("ShiftUp")
	_shift_down_sound_files = _scan_global_wav_folder("ShiftDown")
	shift_up_sound_name = _selected_file_name(_shift_up_sound_files, shift_up_sound_index)
	shift_down_sound_name = _selected_file_name(_shift_down_sound_files, shift_down_sound_index)

#endregion

#region Gangwechsel und Motor-Start-Stop
func _trigger_shift_sound(up: bool) -> void:
	var files := _shift_up_sound_files if up else _shift_down_sound_files
	if files.is_empty():
		return
	var index := shift_up_sound_index if up else shift_down_sound_index
	var wav := _load_wav(files[clampi(index, 0, files.size() - 1)])
	if wav == null:
		return
	if _shift_sound_playback != null:
		_shift_sound_playback.stop()
	var one_shot := wav.duplicate() as AudioStreamWAV
	one_shot.loop_mode = AudioStreamWAV.LOOP_DISABLED
	_shift_sound_playback = one_shot.instantiate_playback()
	_shift_sound_playback_gain = shift_up_sound_volume if up else shift_down_sound_volume
	_shift_sound_playback_pitch = shift_up_sound_pitch if up else shift_down_sound_pitch
	_shift_sound_playback.start(0.0)

func _set_engine_running(running: bool) -> void:
	_engine_start_waiting = false
	if running:
		# Zuerst bleibt Idle/ACC vollständig stumm, während nur der Starter läuft.
		_motor_mix_target = 0.0
		_play_engine_state_sound(_engine_start_path, engine_start_pitch, engine_start_volume)
		if _engine_state_playback != null:
			_engine_start_waiting = true
		else:
			_begin_engine_after_start()
	else:
		_motor_mix_target = 0.0
		_engine_start_rpm_offset = 0.0
		_stop_backfire_burst()
		_play_engine_state_sound(_engine_kill_path, engine_kill_pitch, engine_kill_volume)

func _begin_engine_after_start() -> void:
	_engine_start_waiting = false
	# Direkt nach dem Starter übernimmt der Motor ohne Fade. Der Simulator führt
	# dazu ein echtes kurzes freies Hochdrehen mit Rise/Hold/Fall aus.
	_motor_mix_target = 1.0
	_motor_mix = 1.0
	if not is_instance_valid(_simulator_source):
		for child in get_children():
			if child.has_method("trigger_engine_start_rev"):
				_simulator_source = child
				break
	if is_instance_valid(_simulator_source) and _simulator_source.has_method("trigger_engine_start_rev"):
		_simulator_source.call("trigger_engine_start_rev", engine_start_rpm_kick)
	else:
		_engine_start_rpm_offset = maxf(_engine_start_rpm_offset, engine_start_rpm_kick)

func _play_engine_state_sound(path: String, pitch: float, gain: float) -> void:
	if _engine_state_playback != null:
		_engine_state_playback.stop()
		_engine_state_playback = null
	if path.is_empty() or gain <= 0.0:
		return
	var wav := _load_wav(path)
	if wav == null:
		return
	var one_shot := wav.duplicate() as AudioStreamWAV
	one_shot.loop_mode = AudioStreamWAV.LOOP_DISABLED
	_engine_state_playback = one_shot.instantiate_playback()
	_engine_state_playback_pitch = clampf(pitch, 0.5, 2.0)
	_engine_state_playback_gain = maxf(gain, 0.0)
	_engine_state_playback.start(0.0)

#endregion

#region Gemeinsame WAV-Hilfsfunktionen
func _scan_global_wav_folder(folder_wanted: String) -> Array[String]:
	var result: Array[String] = []
	var root_directory := DirAccess.open(effects_path)
	if root_directory == null:
		return result
	var selected_folder := ""
	for folder_name in root_directory.get_directories():
		if folder_name.to_lower() == folder_wanted.to_lower():
			selected_folder = effects_path.path_join(folder_name)
			break
	if selected_folder.is_empty():
		return result
	var directory := DirAccess.open(selected_folder)
	if directory == null:
		return result
	var files := directory.get_files()
	files.sort()
	for file_name in files:
		if file_name.to_lower().ends_with(".wav"):
			result.append(selected_folder.path_join(file_name))
	return result

func _selected_file_name(files: Array[String], index: int) -> String:
	if files.is_empty():
		return "Keine"
	return files[clampi(index, 0, files.size() - 1)].get_file().get_basename()


func _load_wav(path: String) -> AudioStreamWAV:
	if path.is_empty():
		return null
	if path.begins_with("res://") or path.begins_with("user://"):
		return load(path) as AudioStreamWAV
	return AudioStreamWAV.load_from_file(path)

func _reload_turbo_playback() -> void:
	if _turbo_playback != null:
		_turbo_playback.stop()
	_turbo_playback = null
	if not _turbo_files.is_empty():
		var path := _turbo_files[clampi(turbo_index, 0, _turbo_files.size() - 1)]
		turbo_name = path.get_file().get_basename()
		_turbo_playback = _create_wav_loop(_load_wav(path))

#endregion

#region BOV und Backfire
func _trigger_bov(boost: float) -> void:
	if not _simulator_turbo_enabled or _bov_files.is_empty():
		return
	var path := _bov_files[clampi(bov_index, 0, _bov_files.size() - 1)]
	var wav := _load_wav(path)
	if wav == null:
		return
	var one_shot := wav.duplicate() as AudioStreamWAV
	one_shot.loop_mode = AudioStreamWAV.LOOP_DISABLED
	_bov_playback = one_shot.instantiate_playback()
	# Wenig Druck startet weit hinten und spielt nur den kurzen Entladungsrest.
	_last_bov_release_boost = clampf(boost, 0.0, 1.0)
	var start_normalized := 1.0 - _last_bov_release_boost
	_bov_playback.start(start_normalized * maxf(one_shot.get_length() - 0.001, 0.0))
	bov_trigger_count += 1

func _trigger_backfire(previous_load: float, audio_rpm: float, force_full_burst: bool = false, bypass_automatic_rules: bool = false) -> void:
	if not backfire_enabled:
		return
	var rpm_from := minf(backfire_min_audio_rpm, backfire_max_audio_rpm)
	var rpm_to := maxf(backfire_min_audio_rpm, backfire_max_audio_rpm)
	# audio_rpm ist die wirkliche Wiedergabeposition des Motor-Audios, nicht
	# nur die angeforderte Simulator-RPM.
	if _backfire_files.is_empty():
		return
	# Ein direkter Trigger ist ein ausdrücklicher Nutzerbefehl und darf nicht am
	# automatischen RPM-Fenster oder dessen Cooldown hängen bleiben.
	if not force_full_burst and not bypass_automatic_rules and (_backfire_cooldown_timer > 0.0 or audio_rpm < rpm_from or audio_rpm > rpm_to):
		return
	var stored_load := 1.0 if force_full_burst else clampf(_backfire_load_energy / 1.5, 0.0, 1.0)
	# Ein Tip erzeugt hoechstens einen kurzen Pop. Erst aufgebaute Last streckt
	# die Salve bis zur eingestellten Maximaldauer.
	var simple_interval := lerpf(0.32, 0.11, backfire_strength)
	_backfire_burst_remaining = lerpf(minf(simple_interval * 0.6, 0.1), lerpf(0.5, 2.0, backfire_strength), pow(stored_load, 0.75))
	_backfire_bangs_remaining = -1
	_backfire_next_bang_timer = 0.0
	_backfire_burst_load = clampf(previous_load, 0.0, 1.0)
	_backfire_burst_rpm = audio_rpm
	_backfire_load_energy = 0.0
	_play_backfire_bang()
	_backfire_next_bang_timer = randf_range(simple_interval * 0.7, simple_interval * 1.3)
	_backfire_cooldown_timer = maxf(backfire_cooldown, 0.02)
	backfire_trigger_count += 1

func _trigger_external_backfire_charge(charge: float, audio_rpm: float) -> void:
	if not backfire_enabled or backfire_strength <= 0.0 or _backfire_files.is_empty():
		return
	var normalized_charge := clampf(charge, 0.0, 1.0)
	if normalized_charge < EXTERNAL_BACKFIRE_MIN_RPM:
		return
	# Strength ist im einfachen Modus in erster Linie die Häufigkeit pro
	# Lastabwurf: 0.2 = ungefähr 20 % Chance, 1.0 = immer.
	if randf() > clampf(backfire_strength, 0.0, 1.0):
		return
	# Kein fester Bang-Zähler: Oberhalb 30 % RPM entsteht ein Energievorrat,
	# den jeder zufällige Pop unterschiedlich stark verbraucht.
	var charged_range := smoothstep(EXTERNAL_BACKFIRE_MIN_RPM, 1.0, normalized_charge)
	_external_backfire_release_energy = lerpf(0.10, 1.0, charged_range) * lerpf(0.35, 1.0, backfire_strength)
	_external_backfire_release_active = true
	_backfire_bangs_remaining = -1
	_backfire_burst_remaining = lerpf(0.20, 1.8, charged_range) * lerpf(0.45, 1.0, backfire_strength)
	# Der erste Pop kommt nicht mechanisch exakt beim Loslassen.
	_backfire_next_bang_timer = randf_range(0.025, lerpf(0.22, 0.07, charged_range))
	_backfire_burst_load = lerpf(0.55, 1.0, charged_range)
	_backfire_burst_rpm = clampf(audio_rpm, 0.0, 1.0)
	backfire_trigger_count += 1

func _update_backfire_burst(delta: float) -> void:
	if _external_backfire_release_active:
		_backfire_burst_remaining = maxf(0.0, _backfire_burst_remaining - delta)
		_backfire_next_bang_timer -= delta
		if _backfire_burst_remaining <= 0.0 or _external_backfire_release_energy <= 0.01:
			_external_backfire_release_active = false
			_external_backfire_release_energy = 0.0
			# Nicht in die alte zeitbasierte Simulator-Schleife weiterfallen.
			_backfire_burst_remaining = 0.0
			return
		if _backfire_next_bang_timer <= 0.0:
			_play_backfire_bang()
			_external_backfire_release_energy = maxf(0.0, _external_backfire_release_energy - randf_range(0.12, 0.30))
			# Wechsel aus kurzen Pop-Gruppen und deutlich längeren Lücken.
			var long_pause := randf() < 0.28
			_backfire_next_bang_timer = randf_range(0.22, 0.55) if long_pause else randf_range(0.07, 0.24)
		return
	if _backfire_burst_remaining <= 0.0 or _backfire_bangs_remaining == 0:
		return
	_backfire_burst_remaining = maxf(0.0, _backfire_burst_remaining - delta)
	_backfire_next_bang_timer -= delta
	if _backfire_burst_remaining > 0.0 and _backfire_next_bang_timer <= 0.0:
		_play_backfire_bang()
		if _backfire_bangs_remaining > 0:
			_backfire_bangs_remaining -= 1
		var simple_interval := lerpf(0.32, 0.11, backfire_strength)
		_backfire_next_bang_timer = randf_range(simple_interval * 0.7, simple_interval * 1.3)

func _stop_backfire_burst() -> void:
	_backfire_burst_remaining = 0.0
	_backfire_next_bang_timer = 0.0
	_backfire_bangs_remaining = -1
	_external_backfire_release_active = false
	_external_backfire_release_energy = 0.0
	for voice in _backfire_voices:
		var playback: AudioStreamPlayback = voice.get("playback")
		if playback != null:
			playback.stop()
	_backfire_voices.clear()
	_backfire_playback = null
	_backfire_rpm_kick_offset = 0.0

func _play_backfire_bang() -> void:
	var selected_index := randi_range(0, _backfire_files.size() - 1) if backfire_random_variations else clampi(backfire_index, 0, _backfire_files.size() - 1)
	var path := _backfire_files[selected_index]
	var wav := _load_wav(path)
	if wav == null:
		return
	var one_shot := wav.duplicate() as AudioStreamWAV
	one_shot.loop_mode = AudioStreamWAV.LOOP_DISABLED
	_backfire_playback = one_shot.instantiate_playback()
	_backfire_playback.start(0.0)
	var rpm_from := minf(backfire_min_audio_rpm, backfire_max_audio_rpm)
	var rpm_to := maxf(backfire_min_audio_rpm, backfire_max_audio_rpm)
	var rpm_strength := inverse_lerp(rpm_from, maxf(rpm_to, rpm_from + 0.001), clampf(_backfire_burst_rpm, rpm_from, rpm_to))
	_backfire_playback_gain = clampf(_backfire_burst_load * lerpf(0.55, 1.0, rpm_strength) * randf_range(0.8, 1.0), 0.0, 1.0)
	_backfire_playback_pitch = backfire_pitch * randf_range(0.96, 1.04)
	_backfire_voices.append({"playback": _backfire_playback, "gain": _backfire_playback_gain, "pitch": _backfire_playback_pitch})
	backfire_bang_count += 1
	_backfire_pitch_offset = maxf(_backfire_pitch_offset, backfire_pitch_kick * _backfire_playback_gain)
	if backfire_rpm_kick_enabled:
		# Genug Abstand und Haltezeit, damit Bungee der angehobenen Audio-RPM
		# tatsächlich folgen kann. Das betrifft nur den Klang, nie Fahrzeugtempo.
		_backfire_rpm_kick_offset = maxf(_backfire_rpm_kick_offset, backfire_rpm_kick_amount * lerpf(0.7, 1.0, _backfire_playback_gain))

#endregion

#region Audioaufbau und Laden
func _reload_sound() -> void:
	_destroy_audio()
	set_physics_process(true)
	_output_sample_rate = int(AudioServer.get_mix_rate())
	_last_audio_target_rpm = clampf(rpm_position, 0.0, 1.0)
	_use_dcc = false
	_dcc_mix = 0.0
	_limiter_cut_pitch_factor = 1.0
	_tone_falling = false
	_update_tone(0.0)
	acceleration_sound = _find_bank_sound()
	deceleration_sound = _find_bank_sound("dcc")
	_scan_transmission_bank()
	if not _transmission_files.is_empty():
		var active_transmission_index := clampi(transmission_index, 0, _transmission_files.size() - 1)
		transmission_sound = _load_wav(_transmission_files[active_transmission_index])
	_scan_skid_bank()
	_reload_skid_only()
	_scan_supercharger_bank()
	_scan_turbo_banks()
	_scan_backfire_bank()
	_scan_engine_state_bank()
	_scan_shift_sound_banks()
	if acceleration_sound == null:
		push_warning("Engine-Hörtest: Soundbank/Fahrzeugordner mit ACC-WAV wählen.")
		return
	if acceleration_sound.format != AudioStreamWAV.FORMAT_8_BITS and acceleration_sound.format != AudioStreamWAV.FORMAT_16_BITS:
		push_error("Engine-Hörtest: WAV-Importkompression ausschalten (PCM benötigt).")
		return
	len_accel = acceleration_sound.get_length()
	if len_accel <= 0.0 or acceleration_sound.mix_rate <= 0:
		len_accel = 0.0
		return

	if use_3d_audio:
		var spatial_player := AudioStreamPlayer3D.new()
		spatial_player.attenuation_model = AudioStreamPlayer3D.ATTENUATION_DISABLED
		player_accel = spatial_player
	else:
		player_accel = AudioStreamPlayer.new()
	player_accel.name = "Engine_ACC_DCC_Output"
	# Eigener Laufzeitbus: keine vorhandenen EngineEQ-/Turbo-Effekte verändern.
	player_accel.bus = _tone_bus
	player_accel.volume_linear = maxf(acceleration_volume, 0.0) * db_to_linear(output_headroom_db)
	add_child(player_accel)

	var generator := AudioStreamGenerator.new()
	generator.mix_rate = _output_sample_rate
	# Erprobte Reserve gegen Puffer-Aussetzer bleibt erhalten.
	generator.buffer_length = BUFFER_LENGTH
	player_accel.stream = generator
	node_accel = BungeeEngineNode.new()
	add_child(node_accel)
	node_accel.load_sound(acceleration_sound, _output_sample_rate)
	node_accel.pitch = engine_pitch
	node_accel.speed = 0.0
	node_accel.set_playback_position(clampf(rpm_position, 0.0, 1.0) * len_accel)
	if deceleration_sound != null:
		_load_dcc()
	else:
		print("Engine-Hörtest: kein DCC in der Soundbank gefunden; ACC bleibt in beiden Richtungen aktiv.")
	if transmission_sound != null:
		_load_transmission()
	_idle_playback = _create_wav_loop(_find_bank_sound("idle"))
	_limiter_playback = _create_wav_loop(_find_bank_sound("limiter"))
	_reload_supercharger_only()
	_reload_turbo_playback()
	player_accel.play()
	handle_accel = player_accel.get_stream_playback() as AudioStreamGeneratorPlayback
	_motor_mix = 1.0 if engine_running else 0.0
	_motor_mix_target = _motor_mix
	_fill_output_buffer()
	_last_audio_target_rpm = clampf(rpm_position, 0.0, 1.0)

func _create_wav_loop(source: AudioStreamWAV) -> AudioStreamPlayback:
	if source == null or source.mix_rate <= 0 or source.get_length() <= 0.0:
		return null
	# Import-Ressource nicht verändern. Gültige Loop-Marker übernehmen,
	# ansonsten die gesamte WAV vorwärts loopen, ohne Pitch-Veränderung.
	var loop := source.duplicate() as AudioStreamWAV
	var frames := int(round(source.get_length() * source.mix_rate))
	if frames < 2:
		return null
	if loop.loop_mode == AudioStreamWAV.LOOP_DISABLED or loop.loop_begin < 0 or loop.loop_end <= loop.loop_begin or loop.loop_end > frames:
		loop.loop_begin = 0
		loop.loop_end = frames
	loop.loop_mode = AudioStreamWAV.LOOP_FORWARD
	var playback := loop.instantiate_playback()
	playback.start(float(loop.loop_begin) / loop.mix_rate)
	return playback

func _load_dcc() -> void:
	if deceleration_sound.format != AudioStreamWAV.FORMAT_8_BITS and deceleration_sound.format != AudioStreamWAV.FORMAT_16_BITS:
		push_warning("Engine-Hörtest: DCC braucht PCM ohne Importkompression; verwende ACC.")
		return
	len_dcc = deceleration_sound.get_length()
	if len_dcc <= 0.0 or deceleration_sound.mix_rate <= 0:
		return
	node_dcc = BungeeEngineNode.new()
	add_child(node_dcc)
	node_dcc.load_sound(deceleration_sound, _output_sample_rate)
	node_dcc.pitch = engine_pitch
	node_dcc.speed = 0.0
	node_dcc.set_playback_position((1.0 - clampf(rpm_position, 0.0, 1.0)) * len_dcc)

func _load_transmission() -> void:
	if transmission_sound.format != AudioStreamWAV.FORMAT_8_BITS and transmission_sound.format != AudioStreamWAV.FORMAT_16_BITS:
		push_warning("Engine: Transmission-WAV braucht PCM ohne Importkompression; Spur bleibt aus.")
		return
	len_transmission = transmission_sound.get_length()
	if len_transmission <= 0.0 or transmission_sound.mix_rate <= 0:
		len_transmission = 0.0
		return
	node_transmission = BungeeEngineNode.new()
	add_child(node_transmission)
	node_transmission.load_sound(transmission_sound, _output_sample_rate)
	node_transmission.pitch = transmission_pitch
	node_transmission.speed = 0.0
	node_transmission.set_playback_position(clampf(rpm_position, 0.0, 1.0) * len_transmission)

#endregion

#region Filter und Audio-Bus
func _setup_tone() -> void:
	_tone_bus = StringName("EngineTone_%s" % get_instance_id())
	AudioServer.add_bus()
	var bus_index := AudioServer.bus_count - 1
	AudioServer.set_bus_name(bus_index, _tone_bus)
	# Der interne Bus mit Richtungsklang und Hard-Limiter bleibt pro Fahrzeug
	# erhalten. Existiert ein vom Nutzer angelegter Sammelbus "EngineTone",
	# geht unser fertiges Signal zuerst dorthin und danach über dessen normales
	# Routing weiter (standardmäßig Master).
	var output_bus: StringName = &"EngineTone" if AudioServer.get_bus_index(&"EngineTone") >= 0 else &"Master"
	AudioServer.set_bus_send(bus_index, output_bus)
	_tone_effect = AudioEffectLowPassFilter.new()
	AudioServer.add_bus_effect(bus_index, _tone_effect)
	_highs_effect = AudioEffectHighShelfFilter.new()
	_highs_effect.resonance = 0.5
	AudioServer.add_bus_effect(bus_index, _highs_effect)
	_cabin_effect = AudioEffectLowPassFilter.new()
	_cabin_effect.cutoff_hz = minf(20000.0, AudioServer.get_mix_rate() * 0.45)
	_cabin_effect.resonance = 0.08
	AudioServer.add_bus_effect(bus_index, _cabin_effect)
	_cabin_character_effect = AudioEffectHighShelfFilter.new()
	_cabin_character_effect.cutoff_hz = 1450.0
	_cabin_character_effect.resonance = 0.82
	_cabin_character_effect.gain = 1.0
	AudioServer.add_bus_effect(bus_index, _cabin_character_effect)
	_reverb_effect = AudioEffectReverb.new()
	AudioServer.add_bus_effect(bus_index, _reverb_effect)
	_apply_reverb_preset()
	_hard_limiter_effect = AudioEffectHardLimiter.new()
	_hard_limiter_effect.pre_gain_db = hard_limiter_pre_gain_db
	_hard_limiter_effect.ceiling_db = hard_limiter_ceiling_db
	_hard_limiter_effect.release = hard_limiter_release_ms * 0.001
	AudioServer.add_bus_effect(bus_index, _hard_limiter_effect)
	_update_tone(0.0)

func _update_tone(delta: float) -> void:
	if _tone_effect == null:
		return
	var cutoff := tone_cutoff_fall_hz if _tone_falling else tone_cutoff_rise_hz
	var resonance := tone_resonance_fall if _tone_falling else tone_resonance_rise
	# Nur Filterparameter kurz glätten, nicht RPM oder ACC/DCC-Lautstärken.
	var weight := 1.0 if delta <= 0.0 else 1.0 - exp(-24.0 * delta)
	cutoff = minf(cutoff, AudioServer.get_mix_rate() * 0.49)
	_tone_effect.cutoff_hz = lerpf(_tone_effect.cutoff_hz, cutoff, weight)
	_tone_effect.resonance = lerpf(_tone_effect.resonance, resonance, weight)
	_highs_effect.cutoff_hz = lerpf(_highs_effect.cutoff_hz, minf(highs_start_hz, AudioServer.get_mix_rate() * 0.45), weight)
	_highs_effect.gain = lerpf(_highs_effect.gain, db_to_linear(highs_gain_db), weight)
	if _cabin_effect != null:
		var cabin_target_mix := clampf(cabin_amount, 0.0, 1.0) if cabin_enabled else 0.0
		_cabin_mix = cabin_target_mix if delta <= 0.0 else move_toward(_cabin_mix, cabin_target_mix, delta * maxf(cabin_fade_speed, 0.1))
		var cabin_cutoff := 4800.0
		if cabin_preset == CabinPreset.RACE_CAR:
			cabin_cutoff = 11500.0
		elif cabin_preset == CabinPreset.RACE_COCKPIT:
			cabin_cutoff = 10200.0
		var open_cutoff := minf(20000.0, AudioServer.get_mix_rate() * 0.45)
		# Logarithmisch blenden, damit der Innenraum über den gesamten 0..1-Regler
		# hörbar und ohne plötzlichen Frequenzsprung dichter wird.
		var target_cabin_cutoff := exp(lerpf(log(open_cutoff), log(cabin_cutoff), _cabin_mix))
		_cabin_effect.cutoff_hz = lerpf(_cabin_effect.cutoff_hz, target_cabin_cutoff, weight)
		var cabin_resonance := 0.06
		if cabin_preset == CabinPreset.RACE_CAR:
			cabin_resonance = 0.12
		elif cabin_preset == CabinPreset.RACE_COCKPIT:
			cabin_resonance = 0.34
		_cabin_effect.resonance = lerpf(_cabin_effect.resonance, cabin_resonance, weight)
		if _cabin_character_effect != null:
			var metallic_mix := _cabin_mix if cabin_preset == CabinPreset.RACE_COCKPIT else 0.0
			_cabin_character_effect.gain = lerpf(_cabin_character_effect.gain, lerpf(1.0, db_to_linear(7.0), metallic_mix), weight)
	if _reverb_effect != null:
		var reverb_target := clampf(reverb_amount, 0.0, 1.0) if reverb_enabled else 0.0
		_reverb_mix = reverb_target if delta <= 0.0 else move_toward(_reverb_mix, reverb_target, delta * maxf(reverb_fade_speed, 0.1))
		# Dry bleibt unverändert; nur der reflektierte Anteil wird zugemischt.
		_reverb_effect.dry = 1.0
		_reverb_effect.wet = _reverb_mix * 0.55
	if _hard_limiter_effect != null:
		_hard_limiter_effect.pre_gain_db = hard_limiter_pre_gain_db
		_hard_limiter_effect.ceiling_db = hard_limiter_ceiling_db
		_hard_limiter_effect.release = hard_limiter_release_ms * 0.001
	var bus_index := AudioServer.get_bus_index(_tone_bus)
	if bus_index > 0:
		AudioServer.set_bus_effect_enabled(bus_index, 0, direction_tone_enabled)
		AudioServer.set_bus_effect_enabled(bus_index, 1, highs_enabled)
		AudioServer.set_bus_effect_enabled(bus_index, 2, _cabin_mix > 0.0001)
		AudioServer.set_bus_effect_enabled(bus_index, 3, _cabin_mix > 0.0001 and cabin_preset == CabinPreset.RACE_COCKPIT)
		AudioServer.set_bus_effect_enabled(bus_index, 4, _reverb_mix > 0.0001)
		AudioServer.set_bus_effect_enabled(bus_index, 5, hard_limiter_enabled)

func _apply_reverb_preset() -> void:
	if _reverb_effect == null:
		return
	match reverb_preset:
		ReverbPreset.GARAGE:
			_reverb_effect.room_size = 0.45
			_reverb_effect.damping = 0.58
			_reverb_effect.spread = 0.68
			_reverb_effect.hipass = 0.22
			_reverb_effect.predelay_msec = 18.0
			_reverb_effect.predelay_feedback = 0.18
		ReverbPreset.OUTDOOR:
			# Offene Umgebung: nur eine kurze, schwache Boden-/Umgebungsreflexion,
			# kein langer Hallraum wie bei der früheren Hallen-Abstimmung.
			_reverb_effect.room_size = 0.18
			_reverb_effect.damping = 0.72
			_reverb_effect.spread = 0.90
			_reverb_effect.hipass = 0.50
			_reverb_effect.predelay_msec = 8.0
			_reverb_effect.predelay_feedback = 0.04
		ReverbPreset.UNDERPASS:
			_reverb_effect.room_size = 0.62
			_reverb_effect.damping = 0.34
			_reverb_effect.spread = 0.55
			_reverb_effect.hipass = 0.32
			_reverb_effect.predelay_msec = 28.0
			_reverb_effect.predelay_feedback = 0.24
		_:
			_reverb_effect.room_size = 0.82
			_reverb_effect.damping = 0.36
			_reverb_effect.spread = 0.78
			_reverb_effect.hipass = 0.18
			_reverb_effect.predelay_msec = 42.0
			_reverb_effect.predelay_feedback = 0.35

#endregion

#region Freigabe und Status
func _destroy_audio() -> void:
	if _shift_sound_playback != null:
		_shift_sound_playback.stop()
	_shift_sound_playback = null
	if _engine_state_playback != null:
		_engine_state_playback.stop()
	_engine_state_playback = null
	_engine_start_rpm_offset = 0.0
	_engine_start_waiting = false
	for voice in _backfire_voices:
		var playback: AudioStreamPlayback = voice.get("playback")
		if playback != null:
			playback.stop()
	_backfire_voices.clear()
	_backfire_playback = null
	_backfire_pitch_offset = 0.0
	_backfire_cooldown_timer = 0.0
	_backfire_burst_remaining = 0.0
	_backfire_next_bang_timer = 0.0
	_backfire_load_energy = 0.0
	_backfire_rpm_kick_offset = 0.0
	_backfire_coast_shift_pending = 0.0
	_last_backfire_audio_rpm = 0.0
	if _turbo_playback != null:
		_turbo_playback.stop()
	if _bov_playback != null:
		_bov_playback.stop()
	_turbo_playback = null
	_bov_playback = null
	_turbo_boost = 0.0
	if _supercharger_playback != null:
		_supercharger_playback.stop()
	_supercharger_playback = null
	if _skid_playback != null:
		_skid_playback.stop()
	_skid_playback = null
	_skid_target = 0.0
	_skid_mix = 0.0
	if _idle_playback != null:
		_idle_playback.stop()
	if _limiter_playback != null:
		_limiter_playback.stop()
	_idle_playback = null
	_limiter_playback = null
	_idle_mix = 0.0
	_limiter_mix = 0.0
	if is_instance_valid(node_dcc):
		node_dcc.free()
	node_dcc = null
	len_dcc = 0.0
	if is_instance_valid(node_transmission):
		node_transmission.free()
	node_transmission = null
	transmission_sound = null
	len_transmission = 0.0
	if is_instance_valid(player_accel):
		player_accel.stop()
	handle_accel = null
	if is_instance_valid(node_accel):
		node_accel.free()
	if is_instance_valid(player_accel):
		player_accel.free()
	node_accel = null
	player_accel = null
	len_accel = 0.0
	rpm_follow_distance_seconds = 0.0
	rpm_follow_distance_normalized = 0.0


func has_idle_wav() -> bool:
	return _idle_playback != null
#endregion
