extends Node3D
## Weapon, Waker-kit and case sounds: a bank of named sounds with variations through a pool of 3D voices.
##
## Sound-pack hook: drop better sounds into res://assets/audio/weapons_pack/ with the same base names
## (wav / ogg / mp3; variations as <name>_1, <name>_2, ...). Any name found there replaces the generated
## one (tools/audio/make_weapon_sounds.py writes res://assets/audio/weapons/). Names:
##
##   pistol_shot  smg_shot  shotgun_shot  taser_zap  taser_hit  baton_swing  baton_hit  dry_fire
##   reload_mag  reload_shell  reload_cell  casing_tink  impact_concrete  impact_metal  ricochet
##   body_hit  emp_throw  emp_arm  emp_blast  siren (loop)  scan_pulse  wake_sync (loop)  wake_chime
##   echo_hum (loop)  dispatch_beep  audit_drone (loop)
##
## Missing sounds are skipped silently.

const DIRS := ["res://assets/audio/weapons_pack/", "res://assets/audio/weapons/"]
const NAMES := ["pistol_shot", "smg_shot", "shotgun_shot", "taser_zap", "taser_hit", "baton_swing", "baton_hit",
	"dry_fire", "reload_mag", "reload_shell", "reload_cell", "casing_tink", "impact_concrete", "impact_metal",
	"ricochet", "body_hit", "emp_throw", "emp_arm", "emp_blast", "siren", "scan_pulse", "wake_sync", "wake_chime",
	"echo_hum", "dispatch_beep", "audit_drone"]
const LOOPS := ["siren", "wake_sync", "echo_hum", "audit_drone"]
const EXTS := ["wav", "ogg", "mp3"]
const VOICES := 16

var bank := {}
var source := {}
var played := {}
var _voices: Array[AudioStreamPlayer3D] = []
var _vi := 0
var _last := {}


func _ready() -> void:
	name = "WeaponAudio"
	for nm in NAMES:
		for d in DIRS:
			var list := _find(d, nm)
			if not list.is_empty():
				bank[nm] = list
				source[nm] = "pack" if d.contains("_pack") else "generated"
				break
	for nm in LOOPS:
		for s in bank.get(nm, []):
			if s is AudioStreamWAV:
				s.loop_mode = AudioStreamWAV.LOOP_FORWARD
				s.loop_begin = 0
				s.loop_end = int(s.get_length() * s.mix_rate)
			elif "loop" in s:
				s.loop = true
	for i in VOICES:
		var p := AudioStreamPlayer3D.new()
		p.unit_size = 10.0
		p.max_distance = 160.0
		p.attenuation_filter_cutoff_hz = 8000.0
		p.attenuation_filter_db = -10.0
		add_child(p)
		_voices.append(p)


func _find(d: String, nm: String) -> Array:
	var out := []
	for ext in EXTS:
		var p := "%s%s.%s" % [d, nm, ext]
		if ResourceLoader.exists(p):
			out.append(load(p))
		for i in range(1, 9):
			var q := "%s%s_%d.%s" % [d, nm, i, ext]
			if ResourceLoader.exists(q):
				out.append(load(q))
	return out


func play(nm: String, pos: Vector3, strength := 1.0, pitch := 1.0) -> void:
	played[nm] = int(played.get(nm, 0)) + 1
	var list: Array = bank.get(nm, [])
	if list.is_empty():
		return
	var now := Time.get_ticks_msec()
	if now - int(_last.get(nm, -1000)) < 30:
		return
	_last[nm] = now
	var p := _voices[_vi]
	_vi = (_vi + 1) % _voices.size()
	p.stop()
	p.stream = list[randi() % list.size()]
	p.global_position = pos
	p.volume_db = lerpf(-18.0, 2.0, sqrt(clampf(strength, 0.0, 1.0)))
	p.pitch_scale = pitch * randf_range(0.95, 1.05)
	p.play()


## A looping player parented to `parent` (siren on the cruiser, the sync hum on the sleeper).
func loop(nm: String, parent: Node3D, db := -6.0) -> AudioStreamPlayer3D:
	var p := AudioStreamPlayer3D.new()
	p.name = "Loop_" + nm
	p.unit_size = 10.0
	p.max_distance = 200.0
	p.volume_db = db
	var list: Array = bank.get(nm, [])
	if not list.is_empty():
		p.stream = list[0]
	parent.add_child(p)
	played[nm] = int(played.get(nm, 0)) + 1
	return p
