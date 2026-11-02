extends Control
## Damage indicator (HUD, top left under the MERIDIAN bar): a top-down car whose front / rear / sides
## go from cyan to amber to red, panels that are hanging or gone, the engine and a percentage.

var damage: Node                  ## vehicle_damage.gd of the hero
var _flash := 0.0

const OK := Color(0.35, 0.95, 1.0, 0.85)
const MID := Color(1.0, 0.7, 0.3, 0.9)
const BAD := Color(1.0, 0.18, 0.25, 0.95)


func _ready() -> void:
	set_anchors_preset(Control.PRESET_TOP_LEFT)
	position = Vector2(18, 58)
	size = Vector2(170, 132)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	if damage:
		damage.changed.connect(func(): _flash = 0.6)


func _process(delta: float) -> void:
	_flash = maxf(0.0, _flash - delta)
	queue_redraw()


static func _col(v: float) -> Color:
	return OK.lerp(MID, clampf(v * 2.0, 0.0, 1.0)) if v < 0.5 else MID.lerp(BAD, clampf((v - 0.5) * 2.0, 0.0, 1.0))


func _draw() -> void:
	if damage == null:
		return
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.02, 0.03, 0.06, 0.6 + _flash * 0.4))
	var font := get_theme_default_font()
	var total: float = damage.total()
	draw_string(font, Vector2(10, 22), "DAMAGE", HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color(0.7, 0.85, 0.95))
	draw_string(font, Vector2(84, 22), "%d%%" % roundi(total * 100.0), HORIZONTAL_ALIGNMENT_LEFT, -1, 18, _col(total))
	# car outline, nose up
	var c := Vector2(48, 78)
	var w := 30.0
	var h := 72.0
	var z: Dictionary = damage.zones
	var body := Rect2(c - Vector2(w, h) * 0.5, Vector2(w, h))
	draw_rect(body, Color(0.1, 0.12, 0.16, 0.9))
	draw_rect(Rect2(body.position, Vector2(w, h * 0.22)), _col(z.front))
	draw_rect(Rect2(body.position + Vector2(0, h * 0.78), Vector2(w, h * 0.22)), _col(z.rear))
	draw_rect(Rect2(body.position + Vector2(0, h * 0.22), Vector2(w * 0.2, h * 0.56)), _col(z.left))
	draw_rect(Rect2(body.position + Vector2(w * 0.8, h * 0.22), Vector2(w * 0.2, h * 0.56)), _col(z.right))
	draw_rect(body, Color(0.6, 0.8, 0.9, 0.6), false, 1.5)
	# panels hanging (amber) / gone (red)
	var px := {"Hood": Vector2(0, -0.3), "Trunk": Vector2(0, 0.33), "Bumper_F": Vector2(0, -0.5), "Bumper_R": Vector2(0, 0.5),
		"Door_FL": Vector2(-0.5, -0.05), "Door_FR": Vector2(0.5, -0.05), "Door_RL": Vector2(-0.5, 0.18), "Door_RR": Vector2(0.5, 0.18),
		"Door_SL": Vector2(-0.5, 0.1), "Door_SR": Vector2(0.5, 0.1), "Mirror_L": Vector2(-0.75, -0.12), "Mirror_R": Vector2(0.75, -0.12)}
	for nm in px:
		if not damage.panels.has(nm):
			continue
		var st: String = damage.panels[nm].state
		if st == "ok":
			continue
		var p: Vector2 = c + Vector2(px[nm].x * w, px[nm].y * h)
		draw_circle(p, 3.5, MID if st == "loose" else BAD)
	# right column: engine, glass, lights
	var x := 92.0
	var eng: float = damage.engine
	draw_string(font, Vector2(x, 52), "ENGINE", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(0.7, 0.85, 0.95))
	draw_rect(Rect2(x, 57, 66, 6), Color(0.1, 0.12, 0.16))
	draw_rect(Rect2(x, 57, 66 * (1.0 - eng), 6), _col(eng))
	var glass := 0
	var gone := 0
	for nm in damage.panels:
		var p: Dictionary = damage.panels[nm]
		if p.kind == "glass":
			glass += 1
			if p.state != "ok":
				gone += 1
	draw_string(font, Vector2(x, 80), "GLASS %d/%d" % [glass - gone, glass], HORIZONTAL_ALIGNMENT_LEFT, -1, 12, _col(float(gone) / maxf(glass, 1)))
	var lamps: int = damage.lights_out.size()
	draw_string(font, Vector2(x, 98), "LAMPS %s" % ("OK" if lamps == 0 else "-%d" % lamps), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, OK if lamps == 0 else BAD)
	var wd: Dictionary = damage.wheel_dmg
	var wmax: float = maxf(maxf(wd.FL, wd.FR), maxf(wd.RL, wd.RR))
	draw_string(font, Vector2(x, 116), "WHEELS" if wmax < 0.2 else "ALIGN!", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, _col(wmax))
