extends Node3D
## One drive-in garage in the city (data/garages.json entry): a box building on a foundation behind the
## sidewalk, an open lit bay behind a half-rolled roller door, an Area3D trigger inside the bay, a neon
## "GARAGE" sign on the facade plus a blade sign at the corner (read along the road), lamps over the
## apron and a bobbing chevron marker.  Local frame: +Z faces the road (the door), y = 0 is the floor.

signal entered(garage: Node3D)

var data: Dictionary = {}
var trigger: Area3D
var marker: Node3D
var size := Vector3(14.0, 7.5, 16.0)
const DOOR_W := 6.0
const DOOR_H := 4.6
const BAY := 7.0               ## bay depth behind the door
var _t := 0.0
var _armed := true             ## re-armed once the car has left the trigger


func setup(d: Dictionary) -> void:
	data = d
	name = "Garage_" + String(d.id)
	var s: Array = d.get("size", [14.0, 7.5, 16.0])
	size = Vector3(s[0], s[1], s[2])
	position = Vector3(d.pos[0], d.pos[1], d.pos[2])
	rotation = Vector3(0, float(d.yaw), 0)
	_build()


func accent() -> Color:
	var a: Array = data.get("accent", [1.0, 0.2, 0.6])
	return Color(a[0], a[1], a[2])


func accent2() -> Color:
	var a: Array = data.get("accent2", [0.2, 0.9, 1.0])
	return Color(a[0], a[1], a[2])


## Where a car leaves: on the apron outside the door, facing the road (world transform).
func exit_transform() -> Transform3D:
	var fwd := global_basis.z
	var p := global_transform * Vector3(0, 0.9, size.z * 0.5 + 2.6)
	return Transform3D(Basis(Vector3.UP.cross(fwd).normalized(), Vector3.UP, fwd), p)


## A spot on the road in front of the door, facing it (tests / teleports).
func approach_transform(dist := 14.0) -> Transform3D:
	var back := -global_basis.z
	var p := global_transform * Vector3(0, 0.9, size.z * 0.5 + dist)
	return Transform3D(Basis(Vector3.UP.cross(back).normalized(), Vector3.UP, back), p)


func door_position() -> Vector3:
	return global_transform * Vector3(0, 1.0, size.z * 0.5)


func _process(delta: float) -> void:
	_t += delta
	if marker and marker.visible:
		marker.position.y = DOOR_H + 2.9 + sin(_t * 2.2) * 0.18
		marker.rotation.y = _t * 0.9


func _player() -> Node:
	return get_meta("player") if has_meta("player") else null


func _on_body_entered(b: Node) -> void:
	if _armed and b == _player():
		_armed = false
		entered.emit(self)


func _on_body_exited(b: Node) -> void:
	if b == _player():
		_armed = true


func rearm_later(sec := 2.0) -> void:
	_armed = false
	await get_tree().create_timer(sec).timeout
	var p = _player()
	if p == null or not is_instance_valid(p) or not trigger.overlaps_body(p):
		_armed = true


# ------------------------------------------------------------------ building
func _mat(c: Color, rough: float, metal := 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.roughness = rough
	m.metallic = metal
	return m


func _neon(c: Color, energy: float) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = c
	m.emission_enabled = true
	m.emission = c
	m.emission_energy_multiplier = energy
	return m


func _box(parent: Node, sz: Vector3, pos: Vector3, mat: Material, collide := false) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = sz
	mi.mesh = bm
	mi.position = pos
	mi.material_override = mat
	parent.add_child(mi)
	if collide:
		var cs := CollisionShape3D.new()
		var sh := BoxShape3D.new()
		sh.size = sz
		cs.shape = sh
		cs.position = pos
		_body.add_child(cs)
	return mi


var _body: StaticBody3D


func _build() -> void:
	var hx := size.x * 0.5
	var hz := size.z * 0.5
	var h := size.y
	var style := String(data.get("style", "mod"))
	var wall := _mat(Color(0.075, 0.072, 0.08), 0.85)
	if style == "chop":
		wall = _mat(Color(0.13, 0.075, 0.05), 0.9, 0.2)
	elif style == "dealer":
		wall = _mat(Color(0.03, 0.035, 0.045), 0.25, 0.6)
	var trim := _mat(Color(0.02, 0.02, 0.022), 0.4, 0.5)
	_body = StaticBody3D.new()
	_body.name = "Body"
	_body.collision_layer = 1
	add_child(_body)
	# foundation (covers the lot down into the terrain) + floor, walls, roof
	_box(self, Vector3(size.x + 0.6, 6.0, size.z + 0.6), Vector3(0, -3.0, 0), _mat(Color(0.16, 0.16, 0.17), 0.95), true)
	_box(self, Vector3(size.x, h, 0.4), Vector3(0, h * 0.5, -hz + 0.2), wall, true)
	for sx in [-1.0, 1.0]:
		_box(self, Vector3(0.4, h, size.z), Vector3(sx * (hx - 0.2), h * 0.5, 0), wall, true)
		var pw := hx - DOOR_W * 0.5
		_box(self, Vector3(pw, h, 0.4), Vector3(sx * (DOOR_W * 0.5 + pw * 0.5), h * 0.5, hz - 0.2), wall, true)
	_box(self, Vector3(DOOR_W, h - DOOR_H, 0.4), Vector3(0, DOOR_H + (h - DOOR_H) * 0.5, hz - 0.2), wall, true)
	_box(self, Vector3(size.x + 0.4, 0.3, size.z + 0.4), Vector3(0, h + 0.15, 0), trim, true)
	# apron over the gap to the sidewalk
	var road_gap := 1.6
	_box(self, Vector3(DOOR_W + 1.0, 0.3, road_gap), Vector3(0, -0.15, hz + road_gap * 0.5), _mat(Color(0.2, 0.2, 0.21), 0.9), true)
	# the bay: a glowing back panel, side strips, a light (seen from the street through the door)
	var bz := hz - BAY
	_box(self, Vector3(size.x - 0.8, h, 0.3), Vector3(0, h * 0.5, bz - 0.15), wall, true)
	var glow := _neon(accent(), 1.6)
	_box(self, Vector3(DOOR_W + 1.2, DOOR_H - 0.6, 0.04), Vector3(0, DOOR_H * 0.5 + 0.2, bz + 0.02), glow)
	for i in 5:
		_box(self, Vector3(DOOR_W + 1.0, 0.05, 0.05), Vector3(0, 0.6 + i * 0.75, bz + 0.06), _neon(accent2(), 3.0))
	var floor_line := _neon(accent2(), 2.5)
	for sx in [-1.0, 1.0]:
		_box(self, Vector3(0.08, 0.01, BAY - 0.4), Vector3(sx * 2.3, 0.01, bz + BAY * 0.5), floor_line)
	_box(self, Vector3(size.x - 0.9, 0.02, BAY), Vector3(0, 0.0, bz + BAY * 0.5), _mat(Color(0.02, 0.02, 0.025), 0.12))
	var bay_light := OmniLight3D.new()
	bay_light.position = Vector3(0, 3.2, bz + BAY * 0.5)
	bay_light.light_color = accent()
	bay_light.light_energy = 3.0
	bay_light.omni_range = 9.0
	add_child(bay_light)
	# roller door: drum + half-lowered slats, LED frame, hazard posts
	var drum := MeshInstance3D.new()
	var dm := CylinderMesh.new()
	dm.top_radius = 0.38
	dm.bottom_radius = 0.38
	dm.height = DOOR_W + 0.4
	drum.mesh = dm
	drum.rotation = Vector3(0, 0, PI * 0.5)
	drum.position = Vector3(0, DOOR_H + 0.15, hz + 0.25)
	drum.material_override = trim
	add_child(drum)
	var slats := StandardMaterial3D.new()
	var img := Image.create(8, 64, true, Image.FORMAT_RGBA8)
	for y in 64:
		for x in 8:
			img.set_pixel(x, y, Color(0.16, 0.165, 0.18) if y % 16 > 2 else Color(0.03, 0.03, 0.035))
	img.generate_mipmaps()
	slats.albedo_texture = ImageTexture.create_from_image(img)
	slats.uv1_scale = Vector3(1, 3, 1)
	slats.metallic = 0.6
	slats.roughness = 0.4
	_box(self, Vector3(DOOR_W - 0.1, 0.75, 0.05), Vector3(0, DOOR_H - 0.37, hz - 0.05), slats)
	var led := _neon(accent(), 5.0)
	for sx in [-1.0, 1.0]:
		_box(self, Vector3(0.08, DOOR_H, 0.08), Vector3(sx * (DOOR_W * 0.5 + 0.05), DOOR_H * 0.5, hz + 0.04), led)
	_box(self, Vector3(DOOR_W + 0.2, 0.08, 0.08), Vector3(0, DOOR_H + 0.62, hz + 0.04), led)
	for sx in [-1.0, 1.0]:
		var sl := SpotLight3D.new()
		sl.position = Vector3(sx * (DOOR_W * 0.5 + 0.8), DOOR_H + 0.9, hz + 0.6)
		sl.rotation = Vector3(-PI * 0.42, 0, 0)
		sl.light_color = Color(0.95, 0.95, 1.0).lerp(accent2(), 0.3)
		sl.light_energy = 6.0
		sl.spot_range = 10.0
		sl.spot_angle = 38.0
		sl.light_volumetric_fog_energy = 1.5
		add_child(sl)
		_box(self, Vector3(0.3, 0.12, 0.3), sl.position + Vector3(0, 0.06, 0), _neon(Color(0.95, 0.97, 1.0), 4.0))
	# facade sign: GARAGE in neon over the door + the shop name
	var panel := _mat(Color(0.01, 0.01, 0.012), 0.5)
	_box(self, Vector3(size.x - 1.0, 2.0, 0.12), Vector3(0, h - 1.15, hz + 0.08), panel)
	_box(self, Vector3(size.x - 0.9, 0.05, 0.05), Vector3(0, h - 0.12, hz + 0.16), _neon(accent2(), 4.0))
	_box(self, Vector3(size.x - 0.9, 0.05, 0.05), Vector3(0, h - 2.18, hz + 0.16), _neon(accent2(), 4.0))
	var sign := _label(String(data.get("sign", "GARAGE")), 240, 0.0062, accent(), 4.0)
	sign.position = Vector3(0, h - 1.05, hz + 0.16)
	add_child(sign)
	var sub := _label(String(data.get("name", "")), 72, 0.0062, accent2(), 2.2)
	sub.position = Vector3(0, h - 1.85, hz + 0.16)
	add_child(sub)
	var sign_light := OmniLight3D.new()
	sign_light.position = Vector3(0, h - 1.1, hz + 1.5)
	sign_light.light_color = accent()
	sign_light.light_energy = 2.5
	sign_light.omni_range = 9.0
	add_child(sign_light)
	# blade sign at the street corner: vertical GARAGE, readable along the road both ways
	var blade := Node3D.new()
	blade.name = "Blade"
	blade.position = Vector3(hx - 0.3, h + 0.2, hz + 0.9)
	add_child(blade)
	_box(blade, Vector3(0.22, 6.2, 1.3), Vector3(0, 0, 0), panel)
	_box(blade, Vector3(0.26, 6.3, 0.05), Vector3(0, 0, 0.66), _neon(accent(), 5.0))
	_box(blade, Vector3(0.26, 6.3, 0.05), Vector3(0, 0, -0.66), _neon(accent(), 5.0))
	for sx in [-1.0, 1.0]:
		var bl := _label("G\nA\nR\nA\nG\nE", 150, 0.0065, accent2(), 4.5)
		bl.line_spacing = -20.0
		bl.position = Vector3(sx * 0.12, 0, 0)
		bl.rotation = Vector3(0, sx * PI * 0.5, 0)
		blade.add_child(bl)
	var blade_light := OmniLight3D.new()
	blade_light.position = Vector3(0, 0, 0)
	blade_light.light_color = accent2()
	blade_light.light_energy = 2.0
	blade_light.omni_range = 8.0
	blade.add_child(blade_light)
	# roof edge neon
	_box(self, Vector3(size.x + 0.4, 0.06, 0.06), Vector3(0, h + 0.32, hz + 0.2), _neon(accent(), 4.0))
	if style == "chop":
		# hazard posts guarding the bay
		var hzm := StandardMaterial3D.new()
		var im := Image.create(8, 32, true, Image.FORMAT_RGBA8)
		for y in 32:
			for x in 8:
				im.set_pixel(x, y, Color(0.95, 0.7, 0.05) if (y / 6) % 2 == 0 else Color(0.02, 0.02, 0.02))
		im.generate_mipmaps()
		hzm.albedo_texture = ImageTexture.create_from_image(im)
		for sx in [-1.0, 1.0]:
			_box(self, Vector3(0.3, 1.1, 0.3), Vector3(sx * (DOOR_W * 0.5 + 0.45), 0.55, hz + 0.45), hzm, true)
	# marker: a chevron over the door, shown when the player is near
	marker = Node3D.new()
	marker.name = "Marker"
	marker.position = Vector3(0, DOOR_H + 2.9, hz + 1.2)
	add_child(marker)
	var mm := _neon(accent2(), 6.0)
	for sx in [-1.0, 1.0]:
		var arm := _box(marker, Vector3(0.12, 0.7, 0.12), Vector3(sx * 0.22, 0.2, 0), mm)
		arm.rotation = Vector3(0, 0, sx * 0.75)
	# trigger inside the bay
	trigger = Area3D.new()
	trigger.name = "Trigger"
	trigger.collision_layer = 0
	trigger.collision_mask = 1
	trigger.monitorable = false
	var cs := CollisionShape3D.new()
	var bs := BoxShape3D.new()
	bs.size = Vector3(DOOR_W - 1.0, 3.0, 3.2)
	cs.shape = bs
	cs.position = Vector3(0, 1.5, hz - 2.6)
	trigger.add_child(cs)
	add_child(trigger)
	trigger.body_entered.connect(_on_body_entered)
	trigger.body_exited.connect(_on_body_exited)


func _label(t: String, size_px: int, px: float, c: Color, energy: float) -> Label3D:
	var l := Label3D.new()
	l.text = t
	l.font_size = size_px
	l.pixel_size = px
	l.outline_size = int(size_px * 0.12)
	l.shaded = false
	l.double_sided = false
	l.modulate = Color(c.r * energy, c.g * energy, c.b * energy)
	l.outline_modulate = Color(c, 0.3)
	return l
