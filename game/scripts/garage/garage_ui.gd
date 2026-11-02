extends CanvasLayer
## Garage menu in the HUD's style (dark glass panels, cyan type, magenta highlight): customisation rows
## with < > buttons on the left, the vehicle's specs (stock -> tuned) on the right, a key hint at the bottom.
## Keys and buttons both go through garage.gd (step / leave), so tests drive the same code.

const CYAN := Color(0.35, 0.95, 1.0)
const MAGENTA := Color(1.0, 0.25, 0.65)
const DIM := Color(0.6, 0.72, 0.82)
const PANEL := Color(0.02, 0.03, 0.06, 0.8)

var ctrl: Node                  ## garage.gd
var sel := 0
var _root: Control
var _rows: Array = []           ## [{key, bg, value, panel}]
var _title: Label
var _sub: Label
var _spec_name: Label
var _spec_sub: Label
var _spec_grid: GridContainer
var _plate: LineEdit
var _picker: ColorPickerButton
var _glow_picker: ColorPickerButton


func _ready() -> void:
	layer = 20
	process_mode = Node.PROCESS_MODE_ALWAYS
	_root = Control.new()
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)
	_build()
	visible = false


func show_menu(on: bool) -> void:
	visible = on
	if not on and _plate and _plate.has_focus():
		_plate.release_focus()


func selected_key() -> String:
	return String(_rows[sel].key) if sel < _rows.size() else ""


func move(d: int) -> void:
	sel = posmod(sel + d, _rows.size())
	_highlight()


func edit_plate() -> void:
	for i in _rows.size():
		if _rows[i].key == "plate":
			sel = i
	_highlight()
	_plate.grab_focus()
	_plate.select_all()


# ------------------------------------------------------------------ build
func _label(parent: Node, t: String, size: int, c: Color) -> Label:
	var l := Label.new()
	l.text = t
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", c)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	l.add_theme_constant_override("outline_size", 3)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(l)
	return l


func _panel(pos: Vector2, size: Vector2, anchor: int) -> Panel:
	var p := Panel.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = PANEL
	sb.border_color = Color(CYAN, 0.55)
	sb.border_width_top = 2
	sb.border_width_left = 1
	sb.border_width_right = 1
	sb.border_width_bottom = 1
	sb.corner_detail = 1
	p.add_theme_stylebox_override("panel", sb)
	p.set_anchors_preset(anchor)
	p.position = pos
	p.size = size
	_root.add_child(p)
	return p


func _button(parent: Node, t: String, cb: Callable, w := 40) -> Button:
	var b := Button.new()
	b.text = t
	b.focus_mode = Control.FOCUS_NONE
	b.custom_minimum_size = Vector2(w, 34)
	b.add_theme_font_size_override("font_size", 20)
	for st in ["normal", "hover", "pressed"]:
		var sb := StyleBoxFlat.new()
		sb.bg_color = Color(0.05, 0.08, 0.14, 0.9) if st == "normal" else (Color(MAGENTA, 0.45) if st == "pressed" else Color(CYAN, 0.25))
		sb.border_color = Color(CYAN, 0.6)
		sb.border_width_bottom = 1
		sb.border_width_top = 1
		sb.border_width_left = 1
		sb.border_width_right = 1
		b.add_theme_stylebox_override(st, sb)
	b.add_theme_color_override("font_color", CYAN)
	b.add_theme_color_override("font_hover_color", Color.WHITE)
	b.pressed.connect(cb)
	parent.add_child(b)
	return b


func _build() -> void:
	# title bar (like the MERIDIAN bar of the HUD)
	var bar := ColorRect.new()
	bar.color = Color(0.02, 0.03, 0.06, 0.78)
	bar.set_anchors_preset(Control.PRESET_TOP_WIDE)
	bar.offset_bottom = 52
	bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(bar)
	var line := ColorRect.new()
	line.color = Color(MAGENTA, 0.7)
	line.set_anchors_preset(Control.PRESET_TOP_WIDE)
	line.offset_top = 52
	line.offset_bottom = 54
	_root.add_child(line)
	_title = _label(bar, "GARAGE //", 26, MAGENTA)
	_title.position = Vector2(20, 10)
	_sub = _label(bar, "", 22, DIM)
	_sub.position = Vector2(520, 13)
	# customisation rows
	var left := _panel(Vector2(24, 76), Vector2(600, 790), Control.PRESET_TOP_LEFT)
	var vb := VBoxContainer.new()
	vb.position = Vector2(14, 12)
	vb.size = Vector2(572, 880)
	vb.add_theme_constant_override("separation", 3)
	left.add_child(vb)
	for i in ctrl.ROWS.size():
		var key: String = ctrl.ROWS[i][0]
		var row := PanelContainer.new()
		var sb := StyleBoxFlat.new()
		sb.bg_color = Color(0, 0, 0, 0)
		sb.content_margin_left = 8
		sb.content_margin_right = 6
		row.add_theme_stylebox_override("panel", sb)
		row.mouse_filter = Control.MOUSE_FILTER_STOP
		row.gui_input.connect(_row_input.bind(i))
		vb.add_child(row)
		var hb := HBoxContainer.new()
		hb.add_theme_constant_override("separation", 6)
		row.add_child(hb)
		var name_l := _label(hb, ctrl.ROWS[i][1], 19, DIM)
		name_l.custom_minimum_size = Vector2(170, 0)
		_button(hb, "◀", func(): sel = i; _highlight(); ctrl.step(key, -1))
		var val: Control
		if key == "plate":
			_plate = LineEdit.new()
			_plate.max_length = 10
			_plate.custom_minimum_size = Vector2(250, 34)
			_plate.add_theme_font_size_override("font_size", 20)
			_plate.add_theme_color_override("font_color", Color(1.0, 0.95, 0.7))
			_plate.text_submitted.connect(func(t): ctrl.set_value("plate", t); _plate.release_focus())
			_plate.focus_exited.connect(func(): if ctrl.inside: ctrl.set_value("plate", _plate.text))
			hb.add_child(_plate)
			val = _plate
		else:
			var l := _label(hb, "", 20, Color.WHITE)
			l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			l.custom_minimum_size = Vector2(250, 0)
			l.clip_text = true
			val = l
		_button(hb, "▶", func(): sel = i; _highlight(); ctrl.step(key, 1))
		if key == "paint":
			_picker = ColorPickerButton.new()
			_picker.custom_minimum_size = Vector2(40, 34)
			_picker.focus_mode = Control.FOCUS_NONE
			_picker.edit_alpha = false
			_picker.color_changed.connect(func(c): ctrl.set_value("paint_color", c))
			hb.add_child(_picker)
		elif key == "underglow":
			_glow_picker = ColorPickerButton.new()
			_glow_picker.custom_minimum_size = Vector2(40, 34)
			_glow_picker.focus_mode = Control.FOCUS_NONE
			_glow_picker.edit_alpha = false
			_glow_picker.color_changed.connect(func(c): ctrl.set_value("underglow_color", c))
			hb.add_child(_glow_picker)
		_rows.append({"key": key, "bg": sb, "value": val, "name": name_l})
	var sp := Control.new()
	sp.custom_minimum_size = Vector2(0, 12)
	vb.add_child(sp)
	var hb2 := HBoxContainer.new()
	hb2.add_theme_constant_override("separation", 12)
	vb.add_child(hb2)
	var drive := _button(hb2, "DRIVE OUT   [ENTER]", func(): ctrl.leave(true), 280)
	drive.add_theme_color_override("font_color", MAGENTA)
	_button(hb2, "LEAVE   [ESC]", func(): ctrl.leave(false), 270)
	# specs
	var right := _panel(Vector2(-520, 76), Vector2(496, 560), Control.PRESET_TOP_RIGHT)
	_spec_name = _label(right, "", 30, CYAN)
	_spec_name.position = Vector2(18, 12)
	_spec_name.size = Vector2(460, 40)
	_spec_name.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_spec_sub = _label(right, "", 19, MAGENTA)
	_spec_sub.position = Vector2(18, 92)
	_spec_sub.size = Vector2(460, 50)
	_spec_sub.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_spec_grid = GridContainer.new()
	_spec_grid.columns = 2
	_spec_grid.position = Vector2(18, 150)
	_spec_grid.size = Vector2(460, 420)
	_spec_grid.add_theme_constant_override("h_separation", 18)
	_spec_grid.add_theme_constant_override("v_separation", 6)
	right.add_child(_spec_grid)
	# key hint
	var hint := _label(_root, "W/S  select     A/D  change     TAB  vehicle     [ ]  livery     drag / Q E  orbit     wheel / Z X  zoom     SPACE  turntable     P  plate     ENTER  drive out     ESC  leave", 17, DIM)
	hint.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.offset_top = -40
	hint.offset_bottom = -12
	_highlight()


func _row_input(e: InputEvent, i: int) -> void:
	if e is InputEventMouseButton and e.pressed and e.button_index == MOUSE_BUTTON_LEFT:
		sel = i
		_highlight()


func _highlight() -> void:
	for i in _rows.size():
		var on := i == sel
		_rows[i].bg.bg_color = Color(MAGENTA, 0.22) if on else Color(0, 0, 0, 0)
		_rows[i].bg.border_color = MAGENTA
		_rows[i].bg.border_width_left = 4 if on else 0
		_rows[i].name.add_theme_color_override("font_color", Color.WHITE if on else DIM)


func refresh(v: Dictionary, cfg: Dictionary, stock: Dictionary, tuned: Dictionary) -> void:
	_title.text = "GARAGE  //  " + (String(ctrl.current.data.name) if ctrl.current else "SHOWROOM")
	_sub.text = "%s   —   %s" % [String(v.name), String(v.get("class", "")).to_upper()]
	for r in _rows:
		if r.key == "plate":
			if not _plate.has_focus():
				_plate.text = String(cfg.plate)
		else:
			r.value.text = ctrl.value_text(r.key)
	if _picker:
		_picker.color = Color(cfg.paint.color[0], cfg.paint.color[1], cfg.paint.color[2])
	if _glow_picker:
		_glow_picker.color = Color(cfg.underglow.color[0], cfg.underglow.color[1], cfg.underglow.color[2])
	var parts := String(v.name).split(",", true, 1)
	_spec_name.text = parts[0]
	var vi: int = ctrl.Fleet.variant_index(v, String(cfg.variant))
	_spec_sub.text = "%s%s\nLIVERY: %s" % [String(v.get("class", "")).to_upper(), (" — " + parts[1].strip_edges().to_upper()) if parts.size() > 1 else "",
		String(v.variants[vi].label).to_upper()]
	for c in _spec_grid.get_children():
		_spec_grid.remove_child(c)
		c.queue_free()
	var rows := [
		["MASS", "%d kg" % int(stock.mass), ""],
		["DIMENSIONS", "%.2f × %.2f × %.2f m" % [stock.length, stock.width, stock.height], ""],
		["WHEELBASE", "%.2f m" % stock.wheelbase, ""],
		["DRIVE", "%s   %s" % [stock.drive, "single-speed EV" if stock.electric else "%d-speed auto" % stock.gears], ""],
		["POWER", "%d kW  (%d hp)" % [int(stock.power_kw), int(stock.power_kw * 1.341)], "%d kW" % int(tuned.power_kw)],
		["TORQUE", "%d Nm @ %d" % [int(stock.torque), int(stock.torque_rpm)], "%d Nm" % int(tuned.torque)],
		["TOP SPEED", "%d km/h%s" % [int(stock.top_kmh), " (limited)" if stock.limited else ""], "%d km/h" % int(tuned.top_kmh)],
		["BRAKING", "%.2f g" % stock.brake_g, "%.2f g" % tuned.brake_g],
		["TYRE GRIP", "μ %.2f" % stock.grip, "μ %.2f" % tuned.grip],
		["TYRES", "%d mm  r %.2f m" % [int(stock.wheel_width * 1000.0), stock.wheel_radius], ""],
	]
	for r in rows:
		_label(_spec_grid, r[0], 18, DIM)
		var t: String = r[1]
		var l := _label(_spec_grid, t, 19, Color.WHITE)
		if r[2] != "" and r[2] != t.get_slice(" ", 0) + " " + t.get_slice(" ", 1) and _differs(r[1], r[2]):
			l.text = t + "   →  " + r[2]
			l.add_theme_color_override("font_color", MAGENTA.lerp(Color.WHITE, 0.25))


func _differs(a: String, b: String) -> bool:
	return a.get_slice(" ", 0) != b.get_slice(" ", 0) or (a.begins_with("μ") and a.get_slice(" ", 1) != b.get_slice(" ", 1))
