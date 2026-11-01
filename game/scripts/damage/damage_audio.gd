extends Node3D
## Damage / destruction sounds: a bank of named sounds with variations, played through a pool of
## 3D players; loops (scrape, water hiss) are handed out as their own players.
##
## Sound-pack hook: a purchased pack goes in res://assets/audio/damage_pack/ with the same base names
## (wav, ogg or mp3; variations as <name>_1, <name>_2, ...). Any name found there replaces the generated
## one (tools/audio/make_damage_sounds.py writes res://assets/audio/damage/). The names:
##
##   metal_crunch_light   metal_crunch_heavy   metal_scrape (loop)   glass_shatter   plastic_clatter
##   wood_knock   cardboard_thud   bag_thump   water_burst   water_hiss (loop)   pole_clang
##   electric_fizz   can_rattle
##
## Missing sounds are skipped silently (the game runs without any of them).

const DIRS := ["res://assets/audio/damage_pack/", "res://assets/audio/damage/"]
const NAMES := ["metal_crunch_light", "metal_crunch_heavy", "metal_scrape", "glass_shatter", "plastic_clatter",
	"wood_knock", "cardboard_thud", "bag_thump", "water_burst", "water_hiss", "pole_clang", "electric_fizz", "can_rattle"]
const LOOPS := ["metal_scrape", "water_hiss"]
const EXTS := ["wav", "ogg", "mp3"]
const VOICES := 14

var bank := {}                 ## name -> [AudioStream]
var source := {}               ## name -> "pack" | "generated"
var played := {}               ## name -> count (tests)
var _voices: Array[AudioStreamPlayer3D] = []
var _vi := 0
var _last := {}                ## name -> msec (no machine-gunning the same sound)


func _ready() -> void:
	for nm in NAMES:
		for d in DIRS:
			var list := _find(d, nm)
			if not list.is_empty():
				bank[nm] = list
				source[nm] = "pack" if d.contains("damage_pack") else "generated"
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
		p.name = "Voice%d" % i
		p.unit_size = 6.0
		p.max_distance = 90.0
		p.attenuation_filter_cutoff_hz = 6000.0
		p.attenuation_filter_db = -12.0
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


## One-shot at `pos`. `strength` 0..1 maps to loudness (and a little pitch: big hits are lower).
func play(nm: String, pos: Vector3, strength := 1.0, pitch := 1.0) -> void:
	played[nm] = int(played.get(nm, 0)) + 1
	var list: Array = bank.get(nm, [])
	if list.is_empty():
		return
	var now := Time.get_ticks_msec()
	if now - int(_last.get(nm, -1000)) < 45:
		return
	_last[nm] = now
	var p := _voices[_vi]
	_vi = (_vi + 1) % _voices.size()
	p.stop()
	p.stream = list[randi() % list.size()]
	p.global_position = pos
	var s := clampf(strength, 0.0, 1.0)
	p.volume_db = lerpf(-16.0, 3.0, sqrt(s))
	p.pitch_scale = pitch * randf_range(0.93, 1.07) * lerpf(1.08, 0.9, s)
	p.play()


## Crash sound by impulse (N s): light dents to heavy crunches, plus glass when it broke.
func crash(pos: Vector3, impulse: float) -> void:
	var s := clampf(impulse / 20000.0, 0.0, 1.0)
	play("metal_crunch_heavy" if impulse > 9000.0 else "metal_crunch_light", pos, maxf(s, 0.25))


## A looping player parented to `parent` (scrapes follow the car; the hydrant's hiss stays put).
func loop(nm: String, parent: Node3D, db := -6.0) -> AudioStreamPlayer3D:
	var list: Array = bank.get(nm, [])
	var p := AudioStreamPlayer3D.new()
	p.name = "Loop_" + nm
	p.unit_size = 8.0
	p.max_distance = 120.0
	p.volume_db = db
	if not list.is_empty():
		p.stream = list[0]
	parent.add_child(p)
	if p.stream:
		p.play()
	played[nm] = int(played.get(nm, 0)) + 1
	return p
