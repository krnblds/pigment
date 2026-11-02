extends CanvasLayer
## Waker HUD, in the main HUD's style (cyan / magenta / amber on dark glass, outlined labels):
## crosshair that opens with the spread, hit markers, damage direction wedges, ammo and weapon, health /
## armour, the MERIDIAN dispatch panel with radio chatter, the case marker with distance, the Resonance
## scan gauge, the wake sync ring, UNPLUG trust / credits next to the MERIDIAN score, the report-or-keep
## choice, memory vignettes, prompts and toasts. Everything is drawn by one Control (_draw) plus a few
## labels; nothing allocates per frame.

const CYAN := Color(0.35, 0.95, 1.0)
const MAGENTA := Color(1.0, 0.25, 0.65)
const AMBER := Color(1.0, 0.7, 0.3)
const DIM := Color(0.7, 0.85, 0.95)

var waker: Node
var prof_us := 0.0
var _root: Control
var _canvas: Control
var _ammo: Label
var _wname: Label
var _prompt: Label
var _toast: Label
var _dispatch: Label
var _radio: Label
var _scores: Label
var _choice: Label
var _vignette: Label
var _marker: Label
var _scan: Label
var _toast_t := 0.0
var _hit_t := 0.0
var _hit_col := Color.WHITE
var _dmg: Array = []                   ## [world_dir, t]
var _vig_t := 0.0
var _font: Font
var _main_hud_hidden := false


func _ready() -> void:
	layer = 11
	_root = Control.new()
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)
	_canvas = Control.new()
	_canvas.set_anchors_preset(Control.PRESET_FULL_RECT)
	_canvas.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_canvas.draw.connect(_draw_canvas)
	_root.add_child(_canvas)
	_font = ThemeDB.fallback_font
	_ammo = _label("", 44, CYAN, Control.PRESET_BOTTOM_RIGHT, Vector2(-330, -150), Vector2(300, 60), HORIZONTAL_ALIGNMENT_RIGHT)
	_wname = _label("", 18, DIM, Control.PRESET_BOTTOM_RIGHT, Vector2(-430, -88), Vector2(400, 30), HORIZONTAL_ALIGNMENT_RIGHT)
	_prompt = _label("", 22, Color(0.95, 0.97, 1.0), Control.PRESET_CENTER, Vector2(-400, 90), Vector2(800, 40), HORIZONTAL_ALIGNMENT_CENTER)
	_toast = _label("", 22, AMBER, Control.PRESET_CENTER_TOP, Vector2(-500, 262), Vector2(1000, 40), HORIZONTAL_ALIGNMENT_CENTER)
	# top right, under the MERIDIAN bar and the stats line (the damage HUD owns the top left)
	_dispatch = _label("", 18, Color(0.92, 0.95, 1.0), Control.PRESET_TOP_RIGHT, Vector2(-600, 92), Vector2(576, 140))
	_radio = _label("", 16, DIM, Control.PRESET_TOP_RIGHT, Vector2(-680, 246), Vector2(656, 120), HORIZONTAL_ALIGNMENT_RIGHT)
	_scores = _label("", 18, DIM, Control.PRESET_TOP_LEFT, Vector2(560, 52), Vector2(500, 30))
	_choice = _label("", 22, Color(0.95, 0.97, 1.0), Control.PRESET_CENTER_BOTTOM, Vector2(-520, -330), Vector2(1040, 200), HORIZONTAL_ALIGNMENT_CENTER)
	_vignette = _label("", 22, Color(0.85, 0.95, 1.0), Control.PRESET_CENTER, Vector2(-520, -260), Vector2(1040, 220), HORIZONTAL_ALIGNMENT_CENTER)
	_vignette.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_radio.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_choice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_marker = _label("", 16, CYAN, Control.PRESET_TOP_LEFT, Vector2.ZERO, Vector2(200, 40), HORIZONTAL_ALIGNMENT_CENTER)
	_scan = _label("", 18, CYAN, Control.PRESET_CENTER_BOTTOM, Vector2(-200, -250), Vector2(400, 30), HORIZONTAL_ALIGNMENT_CENTER)
	if waker:
		waker.combat.hit_listeners.append(_on_hit)
		waker.player.damaged.connect(_on_damaged)


func _label(text: String, size: int, col: Color, preset: int, pos: Vector2, sz: Vector2, align := HORIZONTAL_ALIGNMENT_LEFT) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", col)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	l.add_theme_constant_override("outline_size", 4)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	l.set_anchors_preset(preset)
	l.position = pos
	l.size = sz
	l.horizontal_alignment = align
	_root.add_child(l)
	return l


func toast(text: String, seconds := 2.5) -> void:
	_toast.text = text
	_toast_t = seconds


func vignette(text: String, seconds := 9.0) -> void:
	_vignette.text = text
	_vig_t = seconds


func modal() -> bool:
	var c = waker.cases if waker else null
	return c != null and bool(c.get("choice_pending"))


func handle_input(_e: InputEvent) -> bool:
	return false


func _on_hit(h: Dictionary, target: Node) -> void:
	if waker == null or h.get("source") != waker.player:
		return
	_hit_t = 0.18
	_hit_col = CYAN if not bool(h.get("lethal", true)) else (MAGENTA if h.get("killed", false) else Color.WHITE)
	if h.get("headshot", false):
		_hit_col = AMBER


func _on_damaged(from_dir: Vector3, _amount: float) -> void:
	_dmg.append([from_dir, 1.4])
	if _dmg.size() > 6:
		_dmg.pop_front()


# ================================================================== per frame
func _process(dt: float) -> void:
	var t0 := Time.get_ticks_usec()
	if waker == null:
		return
	var p = waker.player
	var on_foot: bool = p.on_foot() or p.state in ["dead", "enter", "exit"]
	_main_hud(not on_foot)
	_hit_t = maxf(0.0, _hit_t - dt)
	for d in _dmg:
		d[1] -= dt
	while not _dmg.is_empty() and _dmg[0][1] <= 0.0:
		_dmg.pop_front()
	_toast_t -= dt
	_toast.visible = _toast_t > 0.0
	_toast.modulate.a = clampf(_toast_t * 2.0, 0.0, 1.0)
	_vig_t -= dt
	_vignette.visible = _vig_t > 0.0
	_vignette.modulate.a = clampf(minf(_vig_t, 9.0 - _vig_t) * 1.5, 0.0, 1.0)
	# weapon / ammo
	var w: Dictionary = p.weapons.def()
	_ammo.visible = on_foot and not w.is_empty()
	_wname.visible = _ammo.visible
	if _ammo.visible:
		var a: Dictionary = p.weapons.ammo.get(p.weapons.current, {"mag": 0, "reserve": 0})
		if int(w.get("mag", 0)) > 0:
			_ammo.text = "%d / %d" % [a.mag, a.reserve]
			_ammo.add_theme_color_override("font_color", MAGENTA if a.mag == 0 else CYAN)
		else:
			_ammo.text = "∞"
		_wname.text = ("%s%s" % [String(w.name), "   RELOADING" if p.weapons.reloading() else ""]) + ("" if bool(w.get("lethal", true)) else "   NON-LETHAL")
	_case_text()
	_prompt.text = _prompt_text()
	_canvas.queue_redraw()
	prof_us = lerpf(prof_us, float(Time.get_ticks_usec() - t0), 0.05)


func _main_hud(driving: bool) -> void:
	var mh = waker.main.hud
	if mh == null or _main_hud_hidden == not driving:
		return
	_main_hud_hidden = not driving
	for k in ["_speed_label", "_unit_label", "_gear_label"]:
		var n = mh.get(k)
		if n:
			n.visible = driving
	for n in mh.find_children("*", "", true, false):
		if n.get_script() == preload("res://scripts/vehicle/tacho.gd"):
			n.visible = driving


func _prompt_text() -> String:
	var p = waker.player
	var c = waker.cases
	if c and c.has_method("prompt"):
		var s: String = c.prompt()
		if s != "":
			return s
	if p.state == "dead":
		return "SIGNAL LOST ... RESTORING"
	if p.on_foot():
		var car: Node3D = waker.nearest_enterable()
		if car and p.can_enter(car):
			return "F   GET IN"
	return ""


func _case_text() -> void:
	var c = waker.cases
	if c == null:
		_dispatch.text = ""
		_radio.text = ""
		_scores.text = ""
		_choice.visible = false
		_scan.visible = false
		return
	_dispatch.text = c.dispatch_text()
	var lines: PackedStringArray = []
	for r in c.radio:
		lines.append(String(r[0]))
	_radio.text = "\n".join(lines)
	_scores.text = "UNPLUG TRUST %d    CR %s" % [int(c.unplug), _thousands(int(c.credits))]
	_choice.visible = bool(c.choice_pending)
	if _choice.visible:
		_choice.text = c.choice_text()
	_scan.visible = bool(c.scan_active)
	if _scan.visible:
		_scan.text = "RESONANCE  %d%%" % int(round(float(c.scan_strength) * 100.0))


func _thousands(n: int) -> String:
	var s := str(absi(n))
	var out := ""
	while s.length() > 3:
		out = "," + s.right(3) + out
		s = s.left(s.length() - 3)
	return ("-" if n < 0 else "") + s + out


# ================================================================== drawing
func _draw_canvas() -> void:
	if waker == null:
		return
	var vp := _canvas.get_viewport_rect().size
	var ctr := vp * 0.5
	var p = waker.player
	var cam: Camera3D = get_viewport().get_camera_3d()
	if p.on_foot():
		_crosshair(ctr, p)
		_bars(vp, p)
	# hit marker
	if _hit_t > 0.0:
		var a := _hit_t / 0.18
		var col := Color(_hit_col, a)
		for s in [Vector2(1, 1), Vector2(-1, 1), Vector2(1, -1), Vector2(-1, -1)]:
			_canvas.draw_line(ctr + s * 7.0, ctr + s * 15.0, col, 2.5, true)
	# damage wedges: around the centre, towards where it came from
	if cam and not _dmg.is_empty():
		var cf := -cam.global_basis.z
		cf.y = 0.0
		for d in _dmg:
			var dir: Vector3 = d[0]
			dir.y = 0.0
			if dir.length() < 0.01 or cf.length() < 0.01:
				continue
			var ang := cf.normalized().signed_angle_to(dir.normalized(), Vector3.UP)
			var sa := -PI * 0.5 - ang
			_canvas.draw_arc(ctr, 150.0, sa - 0.28, sa + 0.28, 16, Color(MAGENTA, clampf(float(d[1]), 0.0, 1.0) * 0.85), 7.0, true)
	var c = waker.cases
	if c and cam:
		_case_marker(cam, vp, c)
		if c.scan_active:
			_scan_gauge(cam, vp, c)
		_sync_ring(cam, c)
	if c and c.choice_pending:
		_canvas.draw_rect(Rect2(vp.x * 0.5 - 540, vp.y - 345, 1080, 220), Color(0.02, 0.03, 0.06, 0.82))
		_canvas.draw_rect(Rect2(vp.x * 0.5 - 540, vp.y - 345, 1080, 2), Color(CYAN, 0.7))
	if _vig_t > 0.0:
		var a := clampf(minf(_vig_t, 9.0 - _vig_t) * 1.5, 0.0, 1.0)
		_canvas.draw_rect(Rect2(vp.x * 0.5 - 540, vp.y * 0.5 - 270, 1080, 240), Color(0.02, 0.03, 0.06, 0.75 * a))
		_canvas.draw_rect(Rect2(vp.x * 0.5 - 540, vp.y * 0.5 - 270, 4, 240), Color(MAGENTA, 0.8 * a))


func _crosshair(ctr: Vector2, p) -> void:
	var w: Dictionary = p.weapons.def()
	if w.is_empty():
		_canvas.draw_circle(ctr, 1.6, Color(1, 1, 1, 0.5))
		return
	var col := Color(CYAN if not bool(w.get("lethal", true)) else Color(0.95, 0.97, 1.0), 0.9)
	var kind := String(w.get("kind", "hitscan"))
	if kind == "melee":
		_canvas.draw_arc(ctr, 14.0, -2.4, -0.74, 18, col, 2.0, true)
		return
	if kind == "thrown":
		_canvas.draw_arc(ctr, 10.0, 0, TAU, 24, col, 1.5, true)
		_canvas.draw_circle(ctr, 2.0, col)
		return
	var cam: Camera3D = get_viewport().get_camera_3d()
	var fovr := deg_to_rad(cam.fov if cam else 70.0)
	var px: float = tan(deg_to_rad(p.weapons.spread_deg())) / tan(fovr * 0.5) * _canvas.get_viewport_rect().size.y * 0.5
	var gap := clampf(px, 4.0, 160.0)
	for d in [Vector2.RIGHT, Vector2.LEFT, Vector2.UP, Vector2.DOWN]:
		_canvas.draw_line(ctr + d * gap, ctr + d * (gap + 9.0), Color(0, 0, 0, 0.5), 4.0)
		_canvas.draw_line(ctr + d * gap, ctr + d * (gap + 9.0), col, 2.0)
	_canvas.draw_circle(ctr, 1.5, col)


func _bars(vp: Vector2, p) -> void:
	var x := 28.0
	var y := vp.y - 70.0
	var w := 300.0
	_canvas.draw_rect(Rect2(x - 2, y - 2, w + 4, 34), Color(0.02, 0.03, 0.06, 0.6))
	_canvas.draw_rect(Rect2(x, y, w * clampf(p.health / p.MAX_HEALTH, 0.0, 1.0), 14), Color(MAGENTA if p.health < 35.0 else Color(0.92, 0.95, 1.0), 0.9))
	_canvas.draw_rect(Rect2(x, y + 18, w * clampf(p.armour / p.MAX_ARMOUR, 0.0, 1.0), 10), Color(CYAN, 0.85))
	_canvas.draw_string(_font, Vector2(x, y - 8), "WAKER  //  VITALS", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color(DIM, 0.8))


func _case_marker(cam: Camera3D, vp: Vector2, c) -> void:
	var tp = c.marker_position()
	if tp == null:
		_marker.visible = false
		return
	var wp: Vector3 = tp
	var d := cam.global_position.distance_to(wp)
	var behind := cam.is_position_behind(wp)
	var sp := cam.unproject_position(wp)
	if behind:
		sp = vp - sp
		sp.y = vp.y - 40.0
	var m := 40.0
	var clamped := Vector2(clampf(sp.x, m, vp.x - m), clampf(sp.y, m + 60.0, vp.y - m))
	var col: Color = MAGENTA if c.marker_is_sleeper() else CYAN
	var pts := PackedVector2Array([clamped + Vector2(0, -11), clamped + Vector2(9, 0), clamped + Vector2(0, 11), clamped + Vector2(-9, 0), clamped + Vector2(0, -11)])
	_canvas.draw_polyline(pts, Color(0, 0, 0, 0.6), 5.0)
	_canvas.draw_polyline(pts, col, 2.5)
	if not c.marker_is_sleeper():
		var r: float = c.area_radius_px(cam, vp)
		if r > 20.0 and not behind and clamped == sp:
			_canvas.draw_arc(clamped, r, 0, TAU, 48, Color(col, 0.25), 1.5, true)
	_marker.visible = true
	_marker.text = "%s\n%d m" % [c.marker_label(), int(d)]
	_marker.position = clamped + Vector2(-100, 14)
	_marker.add_theme_color_override("font_color", col)


func _scan_gauge(cam: Camera3D, vp: Vector2, c) -> void:
	var ctr := Vector2(vp.x * 0.5, vp.y - 170.0)
	var s := float(c.scan_strength)
	var pulse := fmod(float(c.scan_pulse_t), 1.0)
	_canvas.draw_arc(ctr, 52.0, 0, TAU, 48, Color(CYAN, 0.25), 2.0, true)
	_canvas.draw_arc(ctr, 52.0 + pulse * 30.0, 0, TAU, 48, Color(CYAN, (1.0 - pulse) * 0.5), 2.0, true)
	var dir: Vector3 = c.scan_dir
	var cf := -cam.global_basis.z
	cf.y = 0.0
	if dir.length() > 0.01 and cf.length() > 0.01:
		var ang := cf.normalized().signed_angle_to(dir.normalized(), Vector3.UP)
		var spread := lerpf(1.2, 0.12, s)                # a weak signal is a wide, soft lobe
		var a := -PI * 0.5 - ang
		_canvas.draw_arc(ctr, 46.0, a - spread, a + spread, 24, Color(MAGENTA, 0.35 + 0.6 * s), 8.0, true)
	_canvas.draw_rect(Rect2(ctr.x - 60, ctr.y + 62, 120 * s, 5), Color(CYAN, 0.9))
	_canvas.draw_rect(Rect2(ctr.x - 60, ctr.y + 62, 120, 5), Color(CYAN, 0.2))


func _sync_ring(cam: Camera3D, c) -> void:
	var s = c.sync_target()
	if s == null:
		return
	var hp: Vector3 = s.head_position() + Vector3.UP * 0.35
	if cam.is_position_behind(hp):
		return
	var sp := cam.unproject_position(hp)
	var k := float(c.sync)
	var calm := float(s.calm)
	_canvas.draw_arc(sp, 26.0, 0, TAU, 40, Color(0, 0, 0, 0.45), 6.0, true)
	if k > 0.0:
		_canvas.draw_arc(sp, 26.0, -PI * 0.5, -PI * 0.5 + TAU * k, 40, CYAN, 4.0, true)
	# calm: the inner ring (magenta when agitated)
	_canvas.draw_arc(sp, 18.0, -PI * 0.5, -PI * 0.5 + TAU * calm, 32, Color(CYAN, 0.5).lerp(Color(MAGENTA, 0.8), 1.0 - calm), 2.0, true)
