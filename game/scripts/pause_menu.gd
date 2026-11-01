extends CanvasLayer
## Pause menu (ESC / Start): RESUME, GARAGE / SHOWROOM, QUIT.  Pauses the tree while open.

const CYAN := Color(0.35, 0.95, 1.0)
const MAGENTA := Color(1.0, 0.25, 0.65)

var main: Node
var _items: Array = []          ## [[label, Callable]]
var _buttons: Array = []
var _sel := 0


func _ready() -> void:
	layer = 80
	process_mode = Node.PROCESS_MODE_ALWAYS
	visible = false
	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.02, 0.6)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(dim)
	var panel := Panel.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.02, 0.03, 0.06, 0.88)
	sb.border_color = Color(CYAN, 0.6)
	sb.border_width_top = 2
	sb.border_width_bottom = 1
	sb.border_width_left = 1
	sb.border_width_right = 1
	panel.add_theme_stylebox_override("panel", sb)
	panel.set_anchors_preset(Control.PRESET_CENTER)
	panel.position = Vector2(-220, -170)
	panel.size = Vector2(440, 340)
	add_child(panel)
	var title := Label.new()
	title.text = "PAUSED  //  MERIDIAN"
	title.add_theme_font_size_override("font_size", 26)
	title.add_theme_color_override("font_color", MAGENTA)
	title.position = Vector2(24, 18)
	panel.add_child(title)
	_items = [["RESUME", resume], ["GARAGE  /  SHOWROOM    [V]", _garage], ["QUIT", func(): get_tree().quit()]]
	for i in _items.size():
		var b := Button.new()
		b.text = _items[i][0]
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(24, 80 + i * 76)
		b.size = Vector2(392, 58)
		b.add_theme_font_size_override("font_size", 22)
		b.add_theme_color_override("font_color", CYAN)
		for st in ["normal", "hover", "pressed"]:
			var s := StyleBoxFlat.new()
			s.bg_color = Color(0.05, 0.08, 0.14, 0.9) if st == "normal" else Color(MAGENTA, 0.35)
			s.border_color = Color(CYAN, 0.5)
			s.border_width_bottom = 1
			s.border_width_top = 1
			s.border_width_left = 1
			s.border_width_right = 1
			b.add_theme_stylebox_override(st, s)
		b.pressed.connect(_items[i][1])
		b.mouse_entered.connect(func(): _sel = i; _highlight())
		panel.add_child(b)
		_buttons.append(b)
	_highlight()


func toggle() -> void:
	if visible:
		resume()
	else:
		visible = true
		_sel = 0
		_highlight()
		get_tree().paused = true


func resume() -> void:
	visible = false
	get_tree().paused = false


func _garage() -> void:
	resume()
	var g = main.get_node_or_null("Garage") if main else null
	if g:
		g.open(null)


func _highlight() -> void:
	for i in _buttons.size():
		_buttons[i].add_theme_color_override("font_color", Color.WHITE if i == _sel else CYAN)
		_buttons[i].modulate = Color(1.3, 1.1, 1.25) if i == _sel else Color.WHITE


func _unhandled_input(event: InputEvent) -> void:
	if not visible:
		return
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_UP, KEY_W:
				_sel = posmod(_sel - 1, _items.size())
				_highlight()
			KEY_DOWN, KEY_S:
				_sel = posmod(_sel + 1, _items.size())
				_highlight()
			KEY_ENTER, KEY_KP_ENTER, KEY_SPACE:
				_items[_sel][1].call()
			KEY_ESCAPE:
				resume()
			KEY_V:
				_garage()
		get_viewport().set_input_as_handled()
	elif event is InputEventJoypadButton and event.pressed:
		if event.button_index == JOY_BUTTON_START or event.button_index == JOY_BUTTON_B:
			resume()
		elif event.button_index == JOY_BUTTON_A:
			_items[_sel][1].call()
		elif event.button_index == JOY_BUTTON_DPAD_UP:
			_sel = posmod(_sel - 1, _items.size())
			_highlight()
		elif event.button_index == JOY_BUTTON_DPAD_DOWN:
			_sel = posmod(_sel + 1, _items.size())
			_highlight()
		get_viewport().set_input_as_handled()
