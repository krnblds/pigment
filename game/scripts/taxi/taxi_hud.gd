extends CanvasLayer
## Taxi HUD: the job panel (top centre), the meter, what the passenger says (subtitle), and a result
## card after each ride.  Same look as the main HUD (cyan / magenta on dark glass).

const Data := preload("res://scripts/taxi/taxi_data.gd")
const CYAN := Color(0.35, 0.95, 1.0)
const AMBER := Color(1.0, 0.75, 0.25)
const MAGENTA := Color(1.0, 0.25, 0.7)
const DIM := Color(0.62, 0.74, 0.84)

var taxi: Node
var _panel: PanelContainer
var _status: Label
var _detail: Label
var _meter: Label
var _mood: Label
var _comfort: ProgressBar
var _totals: Label
var _say: Label
var _say_t := 0.0
var _card: PanelContainer
var _card_text: Label
var _card_t := 0.0


func _ready() -> void:
	layer = 11
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(root)
	_panel = _glass(root)
	_pin(_panel, 0.5, 0.0, Vector2(-310, 58), Vector2(620, 0))
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 2)
	_panel.add_child(v)
	var top := HBoxContainer.new()
	v.add_child(top)
	_status = _label(top, "", 24, AMBER)
	_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_meter = _label(top, "", 24, CYAN)
	_detail = _label(v, "", 17, DIM)
	var row := HBoxContainer.new()
	v.add_child(row)
	_mood = _label(row, "", 15, MAGENTA)
	_mood.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_comfort = ProgressBar.new()
	_comfort.custom_minimum_size = Vector2(160, 10)
	_comfort.show_percentage = false
	_comfort.max_value = 1.0
	var bg := StyleBoxFlat.new()
	bg.bg_color = Color(0, 0, 0, 0.5)
	var fg := StyleBoxFlat.new()
	fg.bg_color = CYAN
	_comfort.add_theme_stylebox_override("background", bg)
	_comfort.add_theme_stylebox_override("fill", fg)
	_comfort.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(_comfort)
	_totals = _label(v, "", 14, DIM)
	# what the passenger says
	_say = _label(root, "", 22, Color(1, 1, 1))
	_say.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_pin(_say, 0.5, 1.0, Vector2(-520, -230), Vector2(1040, 40))
	# ride result
	_card = _glass(root)
	_pin(_card, 0.5, 0.5, Vector2(-200, -170), Vector2(400, 0))
	_card_text = _label(_card, "", 20, CYAN)
	_card.visible = false


## Anchor a control at (ax, ay) of the screen with its top-left at `off` and a minimum size.
func _pin(c: Control, ax: float, ay: float, off: Vector2, min_size: Vector2) -> void:
	c.anchor_left = ax
	c.anchor_right = ax
	c.anchor_top = ay
	c.anchor_bottom = ay
	c.offset_left = off.x
	c.offset_top = off.y
	c.offset_right = off.x + min_size.x
	c.offset_bottom = off.y + maxf(min_size.y, 1.0)
	c.custom_minimum_size = min_size
	c.grow_horizontal = Control.GROW_DIRECTION_END
	c.grow_vertical = Control.GROW_DIRECTION_END


func _glass(parent: Control) -> PanelContainer:
	var p := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.02, 0.03, 0.06, 0.72)
	sb.border_color = Color(CYAN, 0.35)
	sb.set_border_width_all(1)
	sb.set_content_margin_all(12)
	p.add_theme_stylebox_override("panel", sb)
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(p)
	return p


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


func say(text: String) -> void:
	_say.text = ("“%s”" % text) if text != "" else ""
	_say_t = 5.0 if text != "" else 0.0


func show_result(r: Dictionary) -> void:
	var stars := int(round(float(r.stars)))
	_card_text.text = "FARE COMPLETE  //  %s\n\n%s   %.1f\n\nFare   %s\nTip    %s\nTotal  %s\n\n%s   ETA %s" % [
		String(r.dest).to_upper(), "★".repeat(stars) + "☆".repeat(5 - stars), float(r.stars),
		_money(int(r.fare)), _money(int(r.tip)), _money(int(r.total)), _clock(float(r.time)), _clock(float(r.eta))]
	_card.visible = true
	_card_t = 5.0


func _money(v: int) -> String:
	var s := str(absi(v))
	var out := ""
	while s.length() > 3:
		out = "," + s.substr(s.length() - 3) + out
		s = s.substr(0, s.length() - 3)
	return Data.CURRENCY + s + out


func _clock(t: float) -> String:
	return "%d:%02d" % [int(t) / 60, int(t) % 60]


func _process(dt: float) -> void:
	_say_t -= dt
	if _say_t <= 0.0:
		_say.text = ""
	_card_t -= dt
	_card.visible = _card_t > 0.0
	if taxi == null:
		return
	var st: int = taxi.state
	_comfort.visible = st == taxi.RIDING
	match st:
		taxi.WAITING:
			_status.text = "FOR HIRE"
			_detail.text = "Waiting for a fare...   [N] skip"
			_meter.text = ""
			_mood.text = ""
		taxi.TO_PICKUP:
			_status.text = "PICK UP  //  %s" % taxi.district_name(taxi.pickup_pos).to_upper()
			_detail.text = "Someone is hailing, %dm.  Follow the amber line, stop beside them.   [N] skip" % int(taxi.remaining_m())
			_meter.text = ""
			_mood.text = ""
		taxi.BOARDING:
			_status.text = "PASSENGER GETTING IN"
			_detail.text = "Hold still..."
		taxi.RIDING:
			_status.text = "TO  %s" % String(taxi.dest_name).to_upper()
			var eta: float = taxi.route_m / Data.CRUISE_MS + Data.ETA_SLACK_S - taxi.ride_t
			_detail.text = "%s left   ETA %s%s" % [_dist(taxi.remaining_m()), "-" if eta < 0.0 else "", _clock(absf(eta))]
			var fare := Data.FLAG_FARE + int(round(taxi.route_m / 1000.0 * Data.PER_KM)) + int(round(taxi.wait_t / 60.0 * Data.WAIT_PER_MIN))
			_meter.text = _money(fare)
			_mood.text = "PASSENGER: %s" % String(Data.MOODS[taxi.pax.mood].label)
			_comfort.value = clampf(1.0 - taxi.discomfort / 3.0, 0.0, 1.0)
			_comfort.get_theme_stylebox("fill").bg_color = CYAN.lerp(MAGENTA, 1.0 - _comfort.value)
		taxi.ALIGHTING:
			_status.text = "THANK YOU"
			_detail.text = ""
	var s: Dictionary = taxi.stats
	_totals.text = "Shift: %d fares   %s earned   rating %.1f★" % [int(s.fares), _money(int(s.earned)), taxi.average_stars()]


func _dist(m: float) -> String:
	return "%.1f km" % (m / 1000.0) if m >= 1000.0 else "%d m" % int(m)
