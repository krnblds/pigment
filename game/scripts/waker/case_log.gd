extends CanvasLayer
## Case log (TAB, or CASE LOG in the pause menu): the night so far, scores, unlocks, every case with its
## outcome and choice, and the UNPLUG vignettes you've pieced together. Pauses the game while open.
## N requests the next case now (skips the cooldown).

const Stories := preload("res://scripts/waker/stories.gd")
const CYAN := Color(0.35, 0.95, 1.0)
const MAGENTA := Color(1.0, 0.25, 0.65)

var manager: Node
var _text: RichTextLabel
var _was_paused := false


func _ready() -> void:
	layer = 85
	process_mode = Node.PROCESS_MODE_ALWAYS
	visible = false
	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.02, 0.7)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(dim)
	var panel := Panel.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.02, 0.03, 0.06, 0.92)
	sb.border_color = Color(CYAN, 0.6)
	sb.border_width_top = 2
	sb.border_width_bottom = 1
	sb.border_width_left = 1
	sb.border_width_right = 1
	panel.add_theme_stylebox_override("panel", sb)
	panel.set_anchors_preset(Control.PRESET_CENTER)
	panel.position = Vector2(-560, -380)
	panel.size = Vector2(1120, 760)
	add_child(panel)
	_text = RichTextLabel.new()
	_text.bbcode_enabled = true
	_text.position = Vector2(28, 22)
	_text.size = Vector2(1064, 716)
	_text.add_theme_font_size_override("normal_font_size", 18)
	_text.add_theme_font_size_override("bold_font_size", 22)
	_text.add_theme_color_override("default_color", Color(0.85, 0.92, 1.0))
	panel.add_child(_text)


func open() -> void:
	_was_paused = get_tree().paused
	_text.text = build_text()
	visible = true
	get_tree().paused = true


func close() -> void:
	visible = false
	get_tree().paused = _was_paused


func build_text() -> String:
	var m = manager
	var out := "[b][color=#ff40a6]WAKER CASE LOG  //  HOSHIKAWA SECURITY[/color][/b]\n"
	out += "MERIDIAN SCORE %d     UNPLUG TRUST %d     CREDITS %d     NIGHT CLOCK %s\n" % [m.meridian(), m.unplug, m.credits, m.clock_text(m.clock)]
	var c: Dictionary = m.counts
	out += "WOKEN %d   REPORTED %d   KEPT %d   FAILED %d (KILLED %d, DAWN %d)   AUDITS %d (FLAGGED %d)\n" % [c.woken, c.reported, c.kept, c.failed, c.killed, c.dawn, c.audits, c.flags]
	out += "KIT: %s\n\n" % (", ".join(PackedStringArray(m.unlocks)) if not m.unlocks.is_empty() else "standard issue")
	out += "[color=#5af2ff]CASES[/color]\n"
	var h: Array = m.history
	for i in range(h.size() - 1, maxi(-1, h.size() - 16), -1):
		var e: Dictionary = h[i]
		var A: Dictionary = Stories.ARCHETYPES.get(String(e.archetype), {"title": "?"})
		var res := String(e.outcome).to_upper()
		if String(e.choice) != "":
			res += "  ->  " + ("REPORTED" if e.choice == "reported" else "LET THEM KEEP IT")
		out += "#%04d  %-14s %-12s %-16s %s  %s%s\n" % [int(e.no), String(A.title), String(e.district), String(e.get("citizen", "")), String(e.time), res,
			("   %+d CR" % int(e.credits)) if int(e.credits) != 0 else ""]
	if h.is_empty():
		out += "no cases yet tonight\n"
	if int(c.kept) > 0:
		out += "\n[color=#ff40a6]WHAT THE FRAGMENTS SAID[/color]\n"
		for i in mini(int(c.kept), Stories.VIGNETTES.size()):
			out += "- " + String(Stories.VIGNETTES[i]).replace("\n", " ") + "\n"
	out += "\n[color=#8899aa]TAB / ESC close     N  request the next case now[/color]"
	return out


func _unhandled_input(e: InputEvent) -> void:
	if not visible:
		return
	if e is InputEventKey and e.pressed and not e.echo:
		match e.physical_keycode:
			KEY_TAB, KEY_ESCAPE:
				close()
			KEY_N:
				manager.cooldown = 0.0
				close()
		get_viewport().set_input_as_handled()
