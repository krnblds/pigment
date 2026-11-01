extends Node3D
## The garage interior: a cyberpunk lightbox.  A dark seamless cyclorama sweep at the back (floor curving
## into the wall), a glossy reflective floor (SSR + a box-projected reflection probe), neon strips with real
## magenta / cyan lights, a soft-shadowed softbox key over a turntable lift, tool walls along the sides and
## the roller door you drove in through.  Built in code (no .tscn); restyled per garage (accent colours,
## name).  Lives far outside the city (ORIGIN) with its own Environment while the player is inside.

const ORIGIN := Vector3(6000.0, 800.0, 6000.0)
const HALF_X := 11.0           ## side walls
const BACK_Z := -11.0          ## back wall (cove)
const FRONT_Z := 13.0          ## roller door wall
const HEIGHT := 7.6
const COVE_R := 3.6
const TABLE_R := 3.1
const TABLE_Y := 0.14          ## car floor on the turntable

var env: Environment
var turntable: Node3D
var spin := true
var spin_speed := 0.16         ## rad/s
var _accent_mats: Array = []   ## materials tinted by the garage accent
var _accent2_mats: Array = []
var _accent_lights: Array = []
var _accent2_lights: Array = []
var _name_label: Label3D
var _sub_label: Label3D
var probe: ReflectionProbe


func _ready() -> void:
	global_position = ORIGIN
	_build_env()
	_build_room()
	_build_lights()
	_build_turntable()
	_build_tool_walls()
	_build_door()
	style(Color(1.0, 0.16, 0.62), Color(0.2, 0.9, 1.0), "GARAGE", "")


func _process(delta: float) -> void:
	if spin and turntable:
		turntable.rotate_y(spin_speed * delta)


## Where the car stands (world transform), following the turntable.
func car_transform() -> Transform3D:
	return turntable.global_transform * Transform3D(Basis(), Vector3(0, TABLE_Y, 0))


func style(accent: Color, accent2: Color, title: String, sub: String) -> void:
	for m in _accent_mats:
		m.albedo_color = accent
		m.emission = accent
	for m in _accent2_mats:
		m.albedo_color = accent2
		m.emission = accent2
	for l in _accent_lights:
		l.light_color = accent
	for l in _accent2_lights:
		l.light_color = accent2
	if _name_label:
		_name_label.text = title
		_name_label.modulate = Color(accent.r * 3.0, accent.g * 3.0, accent.b * 3.0)
		_name_label.outline_modulate = Color(accent, 0.35)
		_sub_label.text = sub
		_sub_label.modulate = Color(accent2.r * 1.6, accent2.g * 1.6, accent2.b * 1.6)


# ------------------------------------------------------------------ environment
func _build_env() -> void:
	env = Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.0, 0.0, 0.0)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.05, 0.045, 0.07)
	env.ambient_light_energy = 0.35
	env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_exposure = 1.1
	env.glow_enabled = true
	env.glow_normalized = false
	env.glow_intensity = 0.55
	env.glow_strength = 0.9
	env.glow_bloom = 0.02
	env.glow_hdr_threshold = 1.0
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SCREEN
	for i in range(1, 8):
		env.set("glow_levels/%d" % i, [0.0, 0.4, 0.7, 0.6, 0.35, 0.15, 0.0][i - 1])
	env.ssr_enabled = true
	env.ssr_max_steps = 128
	env.ssr_fade_in = 0.1
	env.ssr_fade_out = 1.6
	env.ssr_depth_tolerance = 0.25
	env.ssao_enabled = true
	env.ssao_radius = 1.0
	env.ssao_intensity = 1.8
	env.ssil_enabled = true
	env.ssil_radius = 4.0
	env.ssil_intensity = 1.2
	env.sdfgi_enabled = false
	env.fog_enabled = false
	env.volumetric_fog_enabled = true
	env.volumetric_fog_density = 0.012
	env.volumetric_fog_albedo = Color(0.85, 0.85, 0.95)
	env.volumetric_fog_anisotropy = 0.55
	env.volumetric_fog_length = 40.0
	env.volumetric_fog_ambient_inject = 0.0
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.08
	env.adjustment_saturation = 1.1


# ------------------------------------------------------------------ materials
static func _mat(c: Color, rough: float, metal := 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.roughness = rough
	m.metallic = metal
	return m


func _neon(c: Color, energy: float, group := 0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = c
	m.emission_enabled = true
	m.emission = c
	m.emission_energy_multiplier = energy
	if group == 1:
		_accent_mats.append(m)
	elif group == 2:
		_accent2_mats.append(m)
	return m


func _box(size: Vector3, pos: Vector3, mat: Material, parent: Node = self, rot := Vector3.ZERO) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = size
	mi.mesh = bm
	mi.position = pos
	mi.rotation = rot
	mi.material_override = mat
	parent.add_child(mi)
	return mi


func _stripes_tex(n: int, a: Color, b: Color, vertical := false) -> ImageTexture:
	var img := Image.create(64, 64, true, Image.FORMAT_RGBA8)
	for y in 64:
		for x in 64:
			var e := ((x if vertical else y) * n) % 64
			img.set_pixel(x, y, a if e > 6 else b)
	img.generate_mipmaps()
	return ImageTexture.create_from_image(img)


func _pegboard_tex() -> ImageTexture:
	var img := Image.create(64, 64, true, Image.FORMAT_RGBA8)
	img.fill(Color(0.07, 0.075, 0.085))
	for cy in [16, 48]:
		for cx in [16, 48]:
			for y in range(cy - 3, cy + 4):
				for x in range(cx - 3, cx + 4):
					if Vector2(x - cx, y - cy).length() < 3.2:
						img.set_pixel(x, y, Color(0.005, 0.005, 0.008))
	img.generate_mipmaps()
	return ImageTexture.create_from_image(img)


# ------------------------------------------------------------------ room
func _build_room() -> void:
	var floor_mat := _mat(Color(0.018, 0.018, 0.022), 0.07, 0.0)
	floor_mat.clearcoat_enabled = true
	floor_mat.clearcoat = 1.0
	floor_mat.clearcoat_roughness = 0.02
	var wall_mat := _mat(Color(0.03, 0.03, 0.036), 0.75)
	# floor + cyclorama sweep (one mesh: floor, cove, back wall)
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var prof: Array = []        # [Vector2(z, y), Vector2 normal(z, y)]
	prof.append([Vector2(FRONT_Z, 0.0), Vector2(0, 1)])
	prof.append([Vector2(BACK_Z + COVE_R, 0.0), Vector2(0, 1)])
	var segs := 16
	for i in range(1, segs + 1):
		var a := PI * 0.5 * float(i) / segs            # 0 -> 90 deg
		var c := Vector2(BACK_Z + COVE_R, COVE_R)
		var p := c + Vector2(-sin(a), -cos(a)) * COVE_R
		prof.append([p, (c - p).normalized()])
	prof.append([Vector2(BACK_Z, HEIGHT), Vector2(1, 0)])
	for i in prof.size() - 1:
		var a: Array = prof[i]
		var b: Array = prof[i + 1]
		var x0 := -HALF_X
		var x1 := HALF_X
		var v := [Vector3(x0, a[0].y, a[0].x), Vector3(x1, a[0].y, a[0].x), Vector3(x1, b[0].y, b[0].x), Vector3(x0, b[0].y, b[0].x)]
		var nr := [Vector3(0, a[1].y, a[1].x), Vector3(0, a[1].y, a[1].x), Vector3(0, b[1].y, b[1].x), Vector3(0, b[1].y, b[1].x)]
		for k in [0, 2, 1, 0, 3, 2]:
			st.set_normal(nr[k])
			st.set_uv(Vector2(v[k].x, v[k].z) * 0.25)
			st.add_vertex(v[k])
	var sweep := MeshInstance3D.new()
	sweep.name = "Sweep"
	sweep.mesh = st.commit()
	sweep.material_override = floor_mat
	add_child(sweep)
	# side walls, ceiling, front wall (around the roller door)
	for sx in [-1.0, 1.0]:
		_box(Vector3(0.2, HEIGHT, FRONT_Z - BACK_Z), Vector3(sx * (HALF_X + 0.1), HEIGHT * 0.5, (FRONT_Z + BACK_Z) * 0.5), wall_mat)
	_box(Vector3(HALF_X * 2.0 + 0.4, 0.2, FRONT_Z - BACK_Z + 0.4), Vector3(0, HEIGHT + 0.1, (FRONT_Z + BACK_Z) * 0.5), _mat(Color(0.01, 0.01, 0.012), 0.9))
	_box(Vector3(HALF_X * 2.0, HEIGHT, 0.2), Vector3(0, HEIGHT * 0.5, FRONT_Z + 0.1), wall_mat)
	# floor runway lines from the door to the turntable, hazard edge at the door
	var line := _neon(Color(0.2, 0.9, 1.0), 2.5, 2)
	for sx in [-1.0, 1.0]:
		_box(Vector3(0.06, 0.006, 7.5), Vector3(sx * 2.4, 0.004, 8.4), line)
	for i in 6:
		_box(Vector3(0.5, 0.006, 0.06), Vector3(0, 0.004, 5.4 + i * 1.2), line)
	# neon: cove top edge, back wall verticals, ceiling light bars (they reflect in the paint)
	var mag := _neon(Color(1.0, 0.16, 0.62), 5.0, 1)
	var cyan := _neon(Color(0.2, 0.9, 1.0), 5.0, 2)
	_box(Vector3(HALF_X * 2.0 - 0.6, 0.08, 0.08), Vector3(0, HEIGHT - 0.35, BACK_Z + 0.1), mag)
	_box(Vector3(HALF_X * 2.0 - 0.6, 0.05, 0.05), Vector3(0, 0.03, BACK_Z + COVE_R + 0.05), cyan)
	for sx in [-1.0, 1.0]:
		_box(Vector3(0.07, HEIGHT - COVE_R - 0.6, 0.07), Vector3(sx * (HALF_X - 0.9), COVE_R + (HEIGHT - COVE_R - 0.6) * 0.5, BACK_Z + 0.08), cyan if sx < 0 else mag)
		# floor-to-wall corner strips along the side walls
		_box(Vector3(0.05, 0.05, FRONT_Z - BACK_Z - COVE_R - 1.0), Vector3(sx * (HALF_X - 0.05), 0.03, (FRONT_Z + BACK_Z + COVE_R) * 0.5), mag if sx < 0 else cyan)
	var ceil := _neon(Color(0.85, 0.92, 1.0), 3.2)
	for i in 3:
		_box(Vector3(0.12, 0.04, 9.0), Vector3((i - 1) * 2.6, HEIGHT - 0.05, 0.0), ceil)
	# neon name on the back wall
	_name_label = Label3D.new()
	_name_label.name = "Name"
	_name_label.font_size = 220
	_name_label.pixel_size = 0.0065
	_name_label.outline_size = 36
	_name_label.shaded = false
	_name_label.double_sided = false
	_name_label.position = Vector3(0, 5.7, BACK_Z + 0.06)
	_name_label.fixed_size = false
	add_child(_name_label)
	_sub_label = Label3D.new()
	_sub_label.name = "Sub"
	_sub_label.font_size = 64
	_sub_label.pixel_size = 0.0065
	_sub_label.outline_size = 8
	_sub_label.shaded = false
	_sub_label.position = Vector3(0, 4.75, BACK_Z + 0.06)
	add_child(_sub_label)
	probe = ReflectionProbe.new()
	probe.name = "Probe"
	probe.size = Vector3(HALF_X * 2.0, HEIGHT, FRONT_Z - BACK_Z)
	probe.position = Vector3(0, HEIGHT * 0.5, (FRONT_Z + BACK_Z) * 0.5)
	probe.origin_offset = Vector3(0, -HEIGHT * 0.5 + 1.2, -(FRONT_Z + BACK_Z) * 0.5)
	probe.box_projection = true
	probe.interior = true
	probe.update_mode = ReflectionProbe.UPDATE_ONCE
	probe.intensity = 1.0
	probe.ambient_mode = ReflectionProbe.AMBIENT_COLOR
	probe.ambient_color = Color(0.02, 0.02, 0.03)
	add_child(probe)


func _build_lights() -> void:
	# softbox key: a glowing panel over the turntable with a soft-shadowed spot under it
	var panel := _neon(Color(0.9, 0.93, 1.0), 2.2)
	_box(Vector3(5.0, 0.04, 3.0), Vector3(0, HEIGHT - 0.6, 0), panel)
	_box(Vector3(5.2, 0.02, 3.2), Vector3(0, HEIGHT - 0.57, 0), _mat(Color(0.02, 0.02, 0.02), 0.6))
	var key := SpotLight3D.new()
	key.name = "Key"
	key.position = Vector3(0, HEIGHT - 0.7, 0)
	key.rotation = Vector3(-PI * 0.5, 0, 0)
	key.light_color = Color(0.92, 0.95, 1.0)
	key.light_energy = 9.0
	key.spot_range = 12.0
	key.spot_angle = 58.0
	key.spot_angle_attenuation = 1.4
	key.shadow_enabled = true
	key.light_size = 2.4                    # PCSS: soft contact shadows under the car
	key.shadow_blur = 1.5
	key.light_volumetric_fog_energy = 0.4
	add_child(key)
	# accent fills: magenta left / cyan right, low and wide, and a rim from behind
	for sx in [-1.0, 1.0]:
		var o := OmniLight3D.new()
		o.position = Vector3(sx * 6.5, 2.2, -4.5)
		o.light_energy = 4.0
		o.omni_range = 11.0
		o.omni_attenuation = 1.2
		o.light_volumetric_fog_energy = 0.8
		o.shadow_enabled = true
		o.light_size = 0.8
		add_child(o)
		(_accent_lights if sx < 0 else _accent2_lights).append(o)
		var f := OmniLight3D.new()
		f.position = Vector3(sx * 5.0, 1.6, 6.5)
		f.light_energy = 1.6
		f.omni_range = 9.0
		add_child(f)
		(_accent2_lights if sx < 0 else _accent_lights).append(f)
	var rim := SpotLight3D.new()
	rim.position = Vector3(0, 5.5, BACK_Z + 2.5)
	rim.look_at_from_position(rim.position, Vector3(0, 0.6, 0.5))
	rim.light_energy = 6.0
	rim.spot_range = 16.0
	rim.spot_angle = 35.0
	rim.light_volumetric_fog_energy = 1.4
	add_child(rim)
	_accent_lights.append(rim)
	# cyclorama wash: uplights at the cove make the sweep glow from dark floor to colour
	for i in 5:
		var u := SpotLight3D.new()
		var x := (i - 2) * 4.2
		u.position = Vector3(x, 0.2, BACK_Z + COVE_R + 0.6)
		u.look_at_from_position(u.position, Vector3(x, 4.5, BACK_Z))
		u.light_energy = 5.0
		u.spot_range = 9.0
		u.spot_angle = 42.0
		u.light_volumetric_fog_energy = 0.0
		add_child(u)
		(_accent_lights if i % 2 == 0 else _accent2_lights).append(u)


func _build_turntable() -> void:
	var base := _mat(Color(0.04, 0.04, 0.05), 0.35, 0.7)
	var plinth := MeshInstance3D.new()
	var pc := CylinderMesh.new()
	pc.top_radius = TABLE_R + 0.25
	pc.bottom_radius = TABLE_R + 0.35
	pc.height = 0.08
	pc.radial_segments = 96
	plinth.mesh = pc
	plinth.position = Vector3(0, 0.04, 0)
	plinth.material_override = base
	add_child(plinth)
	var ring := MeshInstance3D.new()
	var tm := TorusMesh.new()
	tm.inner_radius = TABLE_R + 0.06
	tm.outer_radius = TABLE_R + 0.14
	tm.rings = 96
	ring.mesh = tm
	ring.position = Vector3(0, 0.085, 0)
	ring.scale = Vector3(1, 0.4, 1)
	ring.material_override = _neon(Color(0.2, 0.9, 1.0), 4.0, 2)
	add_child(ring)
	turntable = Node3D.new()
	turntable.name = "Turntable"
	add_child(turntable)
	var top := MeshInstance3D.new()
	var tc := CylinderMesh.new()
	tc.top_radius = TABLE_R
	tc.bottom_radius = TABLE_R
	tc.height = 0.06
	tc.radial_segments = 96
	top.mesh = tc
	top.position = Vector3(0, TABLE_Y - 0.03, 0)
	var tmat := _mat(Color(0.06, 0.062, 0.07), 0.18, 0.85)
	top.material_override = tmat
	turntable.add_child(top)
	# tick marks so the rotation reads
	var tick := _neon(Color(1.0, 0.16, 0.62), 2.0, 1)
	for i in 24:
		var a := TAU * i / 24.0
		var t := _box(Vector3(0.04, 0.005, 0.22), Vector3(sin(a) * (TABLE_R - 0.16), TABLE_Y + 0.001, cos(a) * (TABLE_R - 0.16)), tick, turntable)
		t.rotation.y = a
	# lift posts (it is a garage): four hydraulic columns at the turntable corners
	var post := _mat(Color(0.75, 0.55, 0.05), 0.4, 0.6)
	for sx in [-1.0, 1.0]:
		for sz in [-1.0, 1.0]:
			var p := Vector3(sx * (TABLE_R + 0.9), 0, sz * (TABLE_R + 0.2))
			_box(Vector3(0.32, 2.6, 0.32), p + Vector3(0, 1.3, 0), post)
			_box(Vector3(0.5, 0.06, 0.5), p + Vector3(0, 0.03, 0), _mat(Color(0.02, 0.02, 0.02), 0.5, 0.5))
			_box(Vector3(0.06, 2.2, 0.02), p + Vector3(0, 1.3, 0.17 * sz), _neon(Color(1.0, 0.16, 0.62), 3.0, 1))


func _build_tool_walls() -> void:
	var peg := StandardMaterial3D.new()
	peg.albedo_texture = _pegboard_tex()
	peg.uv1_scale = Vector3(40, 12, 1)
	peg.roughness = 0.8
	var steel := _mat(Color(0.55, 0.57, 0.6), 0.3, 0.9)
	var red := _mat(Color(0.5, 0.02, 0.03), 0.3, 0.2)
	red.clearcoat_enabled = true
	var dark := _mat(Color(0.015, 0.015, 0.018), 0.5)
	var rubber := _mat(Color(0.012, 0.012, 0.012), 0.85)
	var rng := RandomNumberGenerator.new()
	rng.seed = 2077
	for sx in [-1.0, 1.0]:
		var wx: float = sx * (HALF_X - 0.03)
		# pegboard with tools
		_box(Vector3(0.04, 2.6, 8.5), Vector3(wx, 2.6, 0.5), peg)
		for i in 26:
			var z := rng.randf_range(-3.4, 4.4)
			var y := rng.randf_range(1.6, 3.6)
			var kind := rng.randi() % 3
			if kind == 0:          # wrench / screwdriver
				_box(Vector3(0.03, rng.randf_range(0.25, 0.45), 0.035), Vector3(wx - sx * 0.04, y, z), steel, self, Vector3(rng.randf_range(-0.2, 0.2), 0, 0))
			elif kind == 1:        # hammer
				_box(Vector3(0.03, 0.32, 0.03), Vector3(wx - sx * 0.04, y, z), red)
				_box(Vector3(0.04, 0.06, 0.14), Vector3(wx - sx * 0.04, y + 0.16, z), steel)
			else:                  # tape / sockets
				var c := MeshInstance3D.new()
				var cm := CylinderMesh.new()
				cm.top_radius = rng.randf_range(0.04, 0.08)
				cm.bottom_radius = cm.top_radius
				cm.height = 0.05
				c.mesh = cm
				c.rotation = Vector3(0, 0, PI * 0.5)
				c.position = Vector3(wx - sx * 0.05, y, z)
				c.material_override = steel
				add_child(c)
		# neon frame around the board
		var nm := _neon(Color(1.0, 0.16, 0.62) if sx < 0 else Color(0.2, 0.9, 1.0), 3.5, 1 if sx < 0 else 2)
		_box(Vector3(0.04, 0.04, 8.6), Vector3(wx - sx * 0.03, 3.92, 0.5), nm)
		_box(Vector3(0.04, 0.04, 8.6), Vector3(wx - sx * 0.03, 1.28, 0.5), nm)
		# tool chest
		var cz := -5.6
		_box(Vector3(0.75, 1.05, 1.9), Vector3(wx - sx * 0.4, 0.53, cz), red)
		for d in 6:
			_box(Vector3(0.01, 0.01, 1.7), Vector3(wx - sx * 0.78, 0.2 + d * 0.15, cz), steel)
		_box(Vector3(0.8, 0.04, 1.95), Vector3(wx - sx * 0.4, 1.07, cz), dark)
		# tyre stack
		for t in 4:
			var ty := MeshInstance3D.new()
			var tm := TorusMesh.new()
			tm.inner_radius = 0.22
			tm.outer_radius = 0.36
			ty.mesh = tm
			ty.scale = Vector3(1, 0.62, 1)
			ty.position = Vector3(wx - sx * 0.55, 0.12 + t * 0.235, 6.6)
			ty.material_override = rubber
			add_child(ty)
		# workbench + lamp
		_box(Vector3(0.8, 0.06, 2.6), Vector3(wx - sx * 0.42, 0.95, 8.6), _mat(Color(0.12, 0.1, 0.08), 0.7))
		for lz in [7.45, 9.75]:
			_box(Vector3(0.06, 0.92, 0.06), Vector3(wx - sx * 0.75, 0.46, lz), dark)
		var lamp := OmniLight3D.new()
		lamp.position = Vector3(wx - sx * 0.5, 1.6, 8.6)
		lamp.light_color = Color(1.0, 0.75, 0.45)
		lamp.light_energy = 1.2
		lamp.omni_range = 3.5
		add_child(lamp)
		_box(Vector3(0.18, 0.05, 0.4), Vector3(wx - sx * 0.5, 1.68, 8.6), _neon(Color(1.0, 0.8, 0.55), 3.0))


func _build_door() -> void:
	var slats := StandardMaterial3D.new()
	slats.albedo_texture = _stripes_tex(4, Color(0.11, 0.115, 0.125), Color(0.03, 0.03, 0.035))
	slats.uv1_scale = Vector3(1, 6, 1)
	slats.metallic = 0.7
	slats.roughness = 0.45
	_box(Vector3(6.4, 4.6, 0.06), Vector3(0, 2.3, FRONT_Z - 0.04), slats)
	var hz := StandardMaterial3D.new()
	hz.albedo_texture = _stripes_tex(6, Color(0.9, 0.7, 0.05), Color(0.02, 0.02, 0.02), true)
	hz.uv1_scale = Vector3(4, 1, 1)
	hz.roughness = 0.6
	for sx in [-1.0, 1.0]:
		_box(Vector3(0.22, 4.8, 0.12), Vector3(sx * 3.3, 2.4, FRONT_Z - 0.08), hz)
	_box(Vector3(6.8, 0.1, 0.1), Vector3(0, 4.78, FRONT_Z - 0.1), _neon(Color(1.0, 0.16, 0.62), 4.0, 1))
