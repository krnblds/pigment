extends CanvasLayer
## Speed, gear, a MERIDIAN citizen-score ticker (story flavour), controls hint and an FPS line.

var car: RigidBody3D
var score := 612
var _speed_label: Label
var _unit_label: Label
var _gear_label: Label
var _score_label: Label
var _delta_label: Label
var _ticker: Label
var _ticker_clip: Control
var _fps_label: Label
var _hint: Label
var _ticker_x := 0.0
var _delta_t := 0.0
var _hint_t := 10.0
var _speed_t := 0.0
var _clean_t := 0.0
var show_fps := true

const CYAN := Color(0.35, 0.95, 1.0)
const MAGENTA := Color(1.0, 0.25, 0.65)
const AMBER := Color(1.0, 0.7, 0.3)

const FEED := [
	"CITIZEN 7F-2201 SATO R. ... 488 (-12 LOITERING, KABUKI ROW)",
	"CITIZEN 3A-0912 MIKA ... STATUS: MISSING ... DREAMLINK LEASE OVERDUE",
	"NOCTIS SLEEP CREDIT: 8 HRS = 40 PTS. REST IS A RESOURCE.",
	"CITIZEN 1C-7730 AIKO ... 0 ... RECORD SEALED BY HOSHIKAWA DYNAMICS",
	"CURFEW 02:00 - 05:00 IN SECTORS 4, 7, 9. COMPLIANCE IS OBSERVED.",
	"CITIZEN 9D-4410 REN ... 702 (+30 INFORMANT BONUS)",
	"UNPLUG ACTIVITY DETECTED: HILL DISTRICT. REPORT TAMPERED SIGNAGE.",
	"MEMORY PAWN RATES UPDATED. CHILDHOOD: 1,200 CR. FIRST LOVE: 3,400 CR.",
	"YOUR SCORE IS YOUR FUTURE. MERIDIAN IS ALWAYS LISTENING.",
]


func _ready() -> void:
	layer = 10
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(root)
	# speed block (bottom right)
	_speed_label = _label(root, "0", 96, CYAN)
	_speed_label.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_speed_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_speed_label.position = Vector2(-330, -170)
	_speed_label.size = Vector2(240, 110)
	_unit_label = _label(root, "KM/H", 22, Color(0.6, 0.8, 0.9))
	_unit_label.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_unit_label.position = Vector2(-84, -98)
	_gear_label = _label(root, "D", 34, MAGENTA)
	_gear_label.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_gear_label.position = Vector2(-84, -150)
	# MERIDIAN bar (top)
	var bar := ColorRect.new()
	bar.color = Color(0.02, 0.03, 0.06, 0.72)
	bar.set_anchors_preset(Control.PRESET_TOP_WIDE)
	bar.size = Vector2(0, 44)
	bar.offset_bottom = 44
	bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(bar)
	var line := ColorRect.new()
	line.color = Color(CYAN, 0.6)
	line.set_anchors_preset(Control.PRESET_TOP_WIDE)
	line.offset_top = 44
	line.offset_bottom = 46
	root.add_child(line)
	var tag := _label(bar, "MERIDIAN //", 22, CYAN)
	tag.position = Vector2(16, 8)
	_score_label = _label(bar, "CITIZEN 4C-1187 (YOU)  SCORE 612", 22, Color(0.92, 0.95, 1.0))
	_score_label.position = Vector2(160, 8)
	_delta_label = _label(bar, "", 22, AMBER)
	_delta_label.position = Vector2(560, 8)
	_ticker_clip = Control.new()
	_ticker_clip.clip_contents = true
	_ticker_clip.set_anchors_preset(Control.PRESET_TOP_WIDE)
	_ticker_clip.offset_left = 900
	_ticker_clip.offset_bottom = 44
	_ticker_clip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bar.add_child(_ticker_clip)
	_ticker = _label(_ticker_clip, "   ///   ".join(FEED), 20, Color(0.7, 0.85, 0.95))
	_ticker.position = Vector2(0, 10)
	_ticker_x = 0.0
	# controls hint (bottom left)
	_hint = _label(root, "W/S or RT/LT  drive / brake-reverse     A/D or stick  steer     SPACE / A  handbrake\nR / Y  reset to road     C / RB  camera     L / X  light bar     F  rain     G  GI     F3  stats     ESC  quit", 18, Color(0.75, 0.85, 0.95))
	_hint.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	_hint.position = Vector2(24, -80)
	_fps_label = _label(root, "", 16, Color(0.6, 0.7, 0.8))
	_fps_label.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_fps_label.position = Vector2(-420, 56)
	_fps_label.size = Vector2(400, 60)
	_fps_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT


func _label(parent: Node, text: String, size: int, col: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", col)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	l.add_theme_constant_override("outline_size", 4)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(l)
	return l


func adjust(points: int, reason: String) -> void:
	score = clampi(score + points, 0, 999)
	_delta_label.text = ("%+d %s" % [points, reason])
	_delta_label.add_theme_color_override("font_color", MAGENTA if points < 0 else CYAN)
	_delta_t = 3.0


func on_impact(strength: float) -> void:
	if _delta_t < 2.0:
		adjust(-int(clampf(strength / 20.0, 3.0, 40.0)), "PROPERTY DAMAGE")


func _process(delta: float) -> void:
	if car:
		var kmh := absf(car.forward_speed()) * 3.6
		_speed_label.text = "%d" % int(round(kmh))
		_gear_label.text = "R" if car.reversing else ("P" if kmh < 0.5 else "D")
		# flavour: MERIDIAN watches your driving
		if kmh > 110.0:
			_speed_t += delta
			if _speed_t > 2.5:
				_speed_t = 0.0
				adjust(-4, "RECKLESS MOBILITY")
		else:
			_speed_t = 0.0
		if kmh > 15.0 and kmh < 70.0:
			_clean_t += delta
			if _clean_t > 12.0:
				_clean_t = 0.0
				adjust(1, "COMPLIANT TRANSIT")
	_score_label.text = "CITIZEN 4C-1187 (YOU)  SCORE %d" % score
	_delta_t -= delta
	if _delta_t <= 0.0:
		_delta_label.text = ""
	_ticker_x -= delta * 90.0
	var w := _ticker.get_minimum_size().x
	if _ticker_x < -w:
		_ticker_x = _ticker_clip.size.x
	_ticker.position.x = _ticker_x
	_hint_t -= delta
	_hint.modulate.a = clampf(_hint_t / 2.0, 0.0, 1.0) if _hint_t < 2.0 else 1.0
	_fps_label.visible = show_fps
	if show_fps:
		_fps_label.text = "%d fps   %d draws   %.1f M prims" % [
			Engine.get_frames_per_second(),
			RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
			RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME) / 1.0e6]


func show_hint() -> void:
	_hint_t = 10.0
