extends Control
## HUD tachometer: rpm arc with the redline, needle, gear, gearbox mode, assist lamps (lit while an
## assist works, dim while armed, red when switched off) and the road state (WET / DRY).

var car: RigidBody3D
var max_rpm := 8000.0
var redline := 6800.0
var _rpm := 0.0
var _font: Font

const CYAN := Color(0.35, 0.95, 1.0)
const MAGENTA := Color(1.0, 0.25, 0.65)
const DIM := Color(0.45, 0.6, 0.7, 0.55)
const A0 := deg_to_rad(140.0)
const A1 := deg_to_rad(400.0)


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_font = ThemeDB.fallback_font
	if car and "P" in car and car.P.has("engine"):
		redline = float(car.P.engine.get("redline_rpm", 6800.0))
		max_rpm = ceilf((float(car.P.engine.get("limiter_rpm", 7000.0)) + 600.0) / 1000.0) * 1000.0


var _redraw_t := 0.0


func _process(delta: float) -> void:
	if car == null or not ("rpm" in car):
		return
	_rpm = lerpf(_rpm, float(car.rpm), 1.0 - exp(-delta * 18.0))
	_redraw_t -= delta
	if _redraw_t <= 0.0:              # 40 Hz is plenty for a gauge
		_redraw_t = 0.025
		queue_redraw()


func _ang(r: float) -> float:
	return lerpf(A0, A1, clampf(r / max_rpm, 0.0, 1.0))


func _draw() -> void:
	if car == null or not ("rpm" in car):
		return
	var c := size * 0.5
	var R := minf(size.x, size.y) * 0.5 - 6.0
	draw_circle(c, R + 4.0, Color(0.02, 0.03, 0.06, 0.62))
	draw_arc(c, R - 6.0, A0, A1, 64, Color(0.3, 0.45, 0.55, 0.5), 3.0, true)
	draw_arc(c, R - 6.0, _ang(redline), A1, 24, MAGENTA, 6.0, true)
	# lit arc up to the current revs
	var col := MAGENTA if _rpm > redline else CYAN
	draw_arc(c, R - 6.0, A0, _ang(_rpm), 64, Color(col, 0.85), 6.0, true)
	for k in int(max_rpm / 1000.0) + 1:
		var a := _ang(k * 1000.0)
		var d := Vector2(cos(a), sin(a))
		draw_line(c + d * (R - 16.0), c + d * (R - 2.0), Color(0.8, 0.9, 1.0, 0.8), 2.0, true)
		if k % 2 == 1:
			continue                   # numbers on the even thousands: fewer draw calls
		var txt := str(k)
		var ts := _font.get_string_size(txt, HORIZONTAL_ALIGNMENT_CENTER, -1, 16)
		draw_string(_font, c + d * (R - 30.0) + Vector2(-ts.x * 0.5, 6.0), txt, HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color(0.8, 0.9, 1.0, 0.85))
	# needle
	var na := _ang(_rpm)
	var nd := Vector2(cos(na), sin(na))
	draw_line(c - nd * 10.0, c + nd * (R - 12.0), Color(1.0, 0.55, 0.3), 3.0, true)
	draw_circle(c, 6.0, Color(1.0, 0.55, 0.3))
	# gear and mode
	var g: String = car.gear_label() if car.has_method("gear_label") else "D"
	var gs := _font.get_string_size(g, HORIZONTAL_ALIGNMENT_CENTER, -1, 54)
	draw_string(_font, c + Vector2(-gs.x * 0.5, R * 0.62), g, HORIZONTAL_ALIGNMENT_LEFT, -1, 54, MAGENTA)
	var mode := "AUTO"
	var ms := _font.get_string_size(mode, HORIZONTAL_ALIGNMENT_CENTER, -1, 14)
	draw_string(_font, c + Vector2(-ms.x * 0.5, R * 0.62 + 20.0), mode, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, DIM)
	var kmh := absf(car.linear_velocity.dot(car.global_basis.z)) * 3.6
	var sp := "%d" % int(round(kmh))
	var ss := _font.get_string_size(sp, HORIZONTAL_ALIGNMENT_CENTER, -1, 40)
	draw_string(_font, c + Vector2(-ss.x * 0.5, -R * 0.2), sp, HORIZONTAL_ALIGNMENT_LEFT, -1, 40, CYAN)
	var rt := "KM/H   %d RPM" % int(round(_rpm / 50.0) * 50.0)
	var rs := _font.get_string_size(rt, HORIZONTAL_ALIGNMENT_CENTER, -1, 13)
	draw_string(_font, c + Vector2(-rs.x * 0.5, -R * 0.2 + 18.0), rt, HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color(0.8, 0.9, 1.0, 0.8))
	# assist lamps
	var lamps := [["ABS", car.get("abs_on"), car.get("abs_active")], ["TC", car.get("tc_on"), car.get("tc_active")],
		["ESC", car.get("esc_on"), car.get("esc_active")]]
	var x := -54.0
	for l in lamps:
		var on: bool = l[1] if l[1] != null else false
		var act: float = l[2] if l[2] != null else 0.0
		var lc := Color(1.0, 0.75, 0.2) if act > 0.05 else (DIM if on else Color(1.0, 0.25, 0.25, 0.9))
		var t: String = l[0] if on else l[0] + " OFF"
		var fs := 13 if on else 11
		var w := _font.get_string_size(t, HORIZONTAL_ALIGNMENT_CENTER, -1, fs).x
		draw_string(_font, c + Vector2(x - w * 0.5, R * 0.12), t, HORIZONTAL_ALIGNMENT_LEFT, -1, fs, lc)
		x += 54.0
	var wet: float = car.get("wet") if car.get("wet") != null else 0.0
	var road := "WET" if wet > 0.5 else "DRY"
	var ws := _font.get_string_size(road, HORIZONTAL_ALIGNMENT_CENTER, -1, 12)
	draw_string(_font, c + Vector2(-ws.x * 0.5, R * 0.27), road, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(0.5, 0.75, 1.0, 0.7) if wet > 0.5 else DIM)
