extends Node3D
## Particle effects for damage and destruction: pooled one-shot bursts (sparks, glass, chips, dust,
## litter, water splash) and long-running emitters (hydrant geyser, engine steam / smoke).
## Textures are generated at start-up (soft dot, streak); nothing to import.
##
##   burst(kind, pos, dir, scale)       one-shot from a round-robin pool (no allocation per hit)
##   water_jet(pos)  -> Node3D          hydrant geyser: jet + mist + splash ring (free it to stop)
##   engine_smoke()  -> GPUParticles3D  steam / black smoke, colour set by the caller
##   puddle(pos)     -> Decal           a wet patch that grows (the caller scales it)

const POOL := {"sparks": 10, "glass": 8, "chips": 6, "dust": 6, "litter": 4, "splash": 4, "cans": 3}

var stats := {"bursts": 0, "jets": 0, "smokes": 0}
var _pools := {}
var _next := {}
var _soft: Texture2D
var _streak: Texture2D
var _mats := {}


func _ready() -> void:
	_soft = _dot_texture(64, 2.2)
	_streak = _streak_texture()
	for k in POOL:
		_pools[k] = []
		_next[k] = 0
		for i in POOL[k]:
			var p := _make(k)
			p.name = "%s_%d" % [k, i]
			add_child(p)
			_pools[k].append(p)


## One-shot burst. `dir`: the main direction (surface normal / travel); `scale` 0..2 scales amount and speed.
func burst(kind: String, pos: Vector3, dir := Vector3.UP, scale := 1.0) -> void:
	if not _pools.has(kind):
		return
	var arr: Array = _pools[kind]
	var p: GPUParticles3D = arr[_next[kind]]
	_next[kind] = (_next[kind] + 1) % arr.size()
	var d := dir.normalized() if dir.length() > 0.01 else Vector3.UP
	var up := Vector3.UP if absf(d.dot(Vector3.UP)) < 0.95 else Vector3.FORWARD
	# the process material emits along +Y of the emitter
	var x := up.cross(d).normalized()
	p.global_transform = Transform3D(Basis(x, d, x.cross(d)), pos)
	p.amount_ratio = clampf(0.25 + 0.6 * scale, 0.1, 1.0)
	p.speed_scale = clampf(0.85 + 0.15 * scale, 0.8, 1.3)
	p.restart()
	p.emitting = true
	stats.bursts += 1


# ------------------------------------------------------------------ factories
func _make(kind: String) -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.one_shot = true
	p.emitting = false
	p.local_coords = false
	p.explosiveness = 0.92
	p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	p.visibility_aabb = AABB(Vector3(-12, -6, -12), Vector3(24, 18, 24))
	var pm := ParticleProcessMaterial.new()
	pm.direction = Vector3.UP
	match kind:
		"sparks":
			p.amount = 48
			p.lifetime = 0.55
			p.randomness = 0.6
			pm.spread = 70.0
			pm.initial_velocity_min = 3.0
			pm.initial_velocity_max = 11.0
			pm.gravity = Vector3(0, -9.8, 0)
			pm.damping_min = 0.5
			pm.damping_max = 2.0
			pm.particle_flag_align_y = true
			pm.scale_min = 0.6
			pm.scale_max = 1.3
			pm.color_ramp = _ramp([Color(5.0, 4.2, 2.6), Color(4.0, 1.6, 0.35), Color(1.2, 0.25, 0.05, 0.0)])
			p.draw_pass_1 = _quad(Vector2(0.018, 0.16), _mat_add(_streak, true))
		"glass":
			p.amount = 70
			p.lifetime = 1.4
			p.randomness = 0.5
			pm.spread = 75.0
			pm.initial_velocity_min = 1.5
			pm.initial_velocity_max = 5.5
			pm.gravity = Vector3(0, -9.8, 0)
			pm.angle_min = -180.0
			pm.angle_max = 180.0
			pm.angular_velocity_min = -720.0
			pm.angular_velocity_max = 720.0
			pm.scale_min = 0.4
			pm.scale_max = 1.4
			pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
			pm.emission_sphere_radius = 0.25
			pm.color_ramp = _ramp([Color(0.85, 0.95, 1.0, 0.9), Color(0.7, 0.85, 1.0, 0.8), Color(0.6, 0.8, 1.0, 0.0)])
			var gm := StandardMaterial3D.new()
			gm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			gm.vertex_color_use_as_albedo = true
			gm.metallic = 0.6
			gm.roughness = 0.05
			gm.emission_enabled = true
			gm.emission = Color(0.35, 0.45, 0.55)
			gm.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
			gm.cull_mode = BaseMaterial3D.CULL_DISABLED
			p.draw_pass_1 = _quad(Vector2(0.035, 0.03), gm)
		"chips":
			p.amount = 28
			p.lifetime = 1.6
			pm.spread = 80.0
			pm.initial_velocity_min = 1.5
			pm.initial_velocity_max = 6.0
			pm.gravity = Vector3(0, -9.8, 0)
			pm.angular_velocity_min = -540.0
			pm.angular_velocity_max = 540.0
			pm.scale_min = 0.5
			pm.scale_max = 1.6
			pm.color_ramp = _ramp([Color(0.45, 0.45, 0.48), Color(0.3, 0.3, 0.32), Color(0.25, 0.25, 0.27, 0.0)])
			var bm := BoxMesh.new()
			bm.size = Vector3(0.04, 0.012, 0.03)
			var cm := StandardMaterial3D.new()
			cm.vertex_color_use_as_albedo = true
			cm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			cm.roughness = 0.6
			cm.metallic = 0.4
			bm.material = cm
			p.draw_pass_1 = bm
		"dust":
			p.amount = 16
			p.lifetime = 2.2
			p.explosiveness = 0.8
			pm.spread = 90.0
			pm.initial_velocity_min = 0.5
			pm.initial_velocity_max = 2.0
			pm.gravity = Vector3(0, 0.15, 0)
			pm.damping_min = 1.0
			pm.damping_max = 2.0
			pm.scale_min = 0.8
			pm.scale_max = 1.6
			pm.scale_curve = _curve([Vector2(0, 0.4), Vector2(1, 1.6)])
			pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
			pm.emission_sphere_radius = 0.3
			pm.color_ramp = _ramp([Color(0.5, 0.5, 0.55, 0.0), Color(0.45, 0.45, 0.5, 0.35), Color(0.4, 0.4, 0.45, 0.0)])
			p.draw_pass_1 = _quad(Vector2(0.9, 0.9), _mat_soft(_soft))
		"litter":
			p.amount = 24
			p.lifetime = 2.4
			pm.spread = 85.0
			pm.initial_velocity_min = 1.0
			pm.initial_velocity_max = 4.0
			pm.gravity = Vector3(0, -4.0, 0)
			pm.damping_min = 0.6
			pm.damping_max = 1.5
			pm.angular_velocity_min = -360.0
			pm.angular_velocity_max = 360.0
			pm.angle_min = -180.0
			pm.angle_max = 180.0
			pm.color_ramp = _ramp([Color(0.85, 0.82, 0.7), Color(0.6, 0.65, 0.7), Color(0.5, 0.5, 0.5, 0.0)])
			var lm := StandardMaterial3D.new()
			lm.vertex_color_use_as_albedo = true
			lm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			lm.cull_mode = BaseMaterial3D.CULL_DISABLED
			lm.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
			p.draw_pass_1 = _quad(Vector2(0.09, 0.07), lm)
		"splash":
			p.amount = 60
			p.lifetime = 0.9
			pm.spread = 55.0
			pm.initial_velocity_min = 2.0
			pm.initial_velocity_max = 6.0
			pm.gravity = Vector3(0, -9.8, 0)
			pm.particle_flag_align_y = true
			pm.color_ramp = _ramp([Color(0.8, 0.9, 1.0, 0.7), Color(0.7, 0.85, 1.0, 0.0)])
			p.draw_pass_1 = _quad(Vector2(0.03, 0.12), _mat_water(_streak))
		"cans":
			p.amount = 14
			p.lifetime = 2.5
			p.explosiveness = 0.7
			pm.spread = 40.0
			pm.initial_velocity_min = 1.5
			pm.initial_velocity_max = 3.5
			pm.gravity = Vector3(0, -9.8, 0)
			pm.angular_velocity_min = -600.0
			pm.angular_velocity_max = 600.0
			pm.collision_mode = ParticleProcessMaterial.COLLISION_DISABLED
			var cyl := CylinderMesh.new()
			cyl.top_radius = 0.033
			cyl.bottom_radius = 0.033
			cyl.height = 0.12
			cyl.radial_segments = 8
			cyl.rings = 1
			var km := StandardMaterial3D.new()
			km.vertex_color_use_as_albedo = true
			km.metallic = 0.8
			km.roughness = 0.3
			cyl.material = km
			pm.color_ramp = _ramp([Color(0.9, 0.2, 0.25), Color(0.2, 0.6, 0.9), Color(0.95, 0.85, 0.2)])
			p.draw_pass_1 = cyl
	p.process_material = pm
	return p


## Hydrant geyser: a tall jet (streaks), mist (soft sprites drifting with the wind) and splashes where
## it falls back. One node; free it to stop. `height` ~ jet height in metres.
func water_jet(pos: Vector3, height := 9.0) -> Node3D:
	var root := Node3D.new()
	root.name = "WaterJet"
	add_child(root)
	root.global_position = pos
	var v0 := sqrt(2.0 * 9.8 * height)
	# jet core
	var jet := GPUParticles3D.new()
	jet.name = "Jet"
	jet.amount = 900
	jet.lifetime = v0 / 9.8 * 1.9
	jet.local_coords = false
	jet.visibility_aabb = AABB(Vector3(-6, -1, -6), Vector3(12, height + 4, 12))
	jet.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var pm := ParticleProcessMaterial.new()
	pm.direction = Vector3.UP
	pm.spread = 4.5
	pm.initial_velocity_min = v0 * 0.86
	pm.initial_velocity_max = v0 * 1.02
	pm.gravity = Vector3(0.25, -9.8, 0.1)
	pm.particle_flag_align_y = true
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	pm.emission_sphere_radius = 0.06
	pm.scale_min = 0.7
	pm.scale_max = 1.6
	pm.scale_curve = _curve([Vector2(0, 0.6), Vector2(0.5, 1.2), Vector2(1, 1.8)])
	pm.color_ramp = _ramp([Color(0.85, 0.92, 1.0, 0.75), Color(0.8, 0.9, 1.0, 0.55), Color(0.75, 0.85, 1.0, 0.0)])
	jet.process_material = pm
	jet.draw_pass_1 = _quad(Vector2(0.06, 0.45), _mat_water(_streak))
	root.add_child(jet)
	# mist: big soft sprites around the column and the top
	var mist := GPUParticles3D.new()
	mist.name = "Mist"
	mist.amount = 90
	mist.lifetime = 3.2
	mist.local_coords = false
	mist.visibility_aabb = jet.visibility_aabb
	mist.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var mm := ParticleProcessMaterial.new()
	mm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	mm.emission_box_extents = Vector3(0.6, height * 0.5, 0.6)
	mm.emission_shape_offset = Vector3(0, height * 0.55, 0)
	mm.direction = Vector3(0.3, -0.2, 0.1)
	mm.spread = 60.0
	mm.initial_velocity_min = 0.3
	mm.initial_velocity_max = 1.2
	mm.gravity = Vector3(0.4, -0.6, 0.15)
	mm.scale_min = 1.2
	mm.scale_max = 2.6
	mm.scale_curve = _curve([Vector2(0, 0.5), Vector2(1, 1.7)])
	mm.color_ramp = _ramp([Color(0.75, 0.82, 0.92, 0.0), Color(0.75, 0.82, 0.92, 0.16), Color(0.7, 0.78, 0.9, 0.0)])
	mist.process_material = mm
	mist.draw_pass_1 = _quad(Vector2(1.6, 1.6), _mat_soft(_soft))
	root.add_child(mist)
	# splashes where the column lands (a ring around the base)
	var sp := GPUParticles3D.new()
	sp.name = "Splash"
	sp.amount = 260
	sp.lifetime = 0.7
	sp.local_coords = false
	sp.visibility_aabb = AABB(Vector3(-5, -1, -5), Vector3(10, 4, 10))
	sp.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var sm := ParticleProcessMaterial.new()
	sm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_RING
	sm.emission_ring_axis = Vector3.UP
	sm.emission_ring_radius = 1.4
	sm.emission_ring_inner_radius = 0.2
	sm.emission_ring_height = 0.05
	sm.direction = Vector3.UP
	sm.spread = 50.0
	sm.initial_velocity_min = 1.2
	sm.initial_velocity_max = 3.8
	sm.gravity = Vector3(0, -9.8, 0)
	sm.particle_flag_align_y = true
	sm.color_ramp = _ramp([Color(0.85, 0.92, 1.0, 0.65), Color(0.8, 0.9, 1.0, 0.0)])
	sp.process_material = sm
	sp.draw_pass_1 = _quad(Vector2(0.03, 0.14), _mat_water(_streak))
	sp.position = Vector3(0, 0.05, 0)
	root.add_child(sp)
	stats.jets += 1
	return root


## Continuous engine steam / smoke from under the hood; the caller sets `amount_ratio` and the colour
## (process_material.color) as the engine gets worse.
func engine_smoke() -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.name = "EngineSmoke"
	p.amount = 60
	p.lifetime = 2.6
	p.local_coords = false
	p.visibility_aabb = AABB(Vector3(-8, -2, -8), Vector3(16, 10, 16))
	p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var pm := ParticleProcessMaterial.new()
	pm.direction = Vector3.UP
	pm.spread = 25.0
	pm.initial_velocity_min = 0.6
	pm.initial_velocity_max = 1.6
	pm.gravity = Vector3(0, 0.6, 0)
	pm.damping_min = 0.4
	pm.damping_max = 1.0
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	pm.emission_box_extents = Vector3(0.35, 0.05, 0.3)
	pm.scale_min = 0.6
	pm.scale_max = 1.1
	pm.scale_curve = _curve([Vector2(0, 0.35), Vector2(1, 2.2)])
	pm.angle_min = -180.0
	pm.angle_max = 180.0
	pm.color = Color(0.85, 0.85, 0.88)
	pm.color_ramp = _ramp([Color(1, 1, 1, 0.0), Color(1, 1, 1, 0.42), Color(1, 1, 1, 0.0)])
	p.process_material = pm
	p.draw_pass_1 = _quad(Vector2(0.9, 0.9), _mat_soft(_soft, false))
	stats.smokes += 1
	return p


## A wet patch on the ground: a decal that darkens and glosses whatever it lies on.
func puddle(pos: Vector3, size := 1.0) -> Decal:
	var d := Decal.new()
	d.name = "Puddle"
	d.texture_albedo = _puddle_tex("a")
	d.texture_orm = _puddle_tex("orm")
	d.albedo_mix = 0.65
	d.modulate = Color(0.55, 0.6, 0.66, 1.0)
	d.size = Vector3(size, 0.6, size)
	d.upper_fade = 0.3
	d.lower_fade = 0.3
	d.cull_mask = 0xFFFFF
	d.distance_fade_enabled = true
	d.distance_fade_begin = 90.0
	d.distance_fade_length = 20.0
	add_child(d)
	d.global_position = pos
	return d


# ------------------------------------------------------------------ materials / textures
func _quad(size: Vector2, mat: Material) -> QuadMesh:
	var q := QuadMesh.new()
	q.size = size
	q.material = mat
	return q


func _mat_add(tex: Texture2D, align: bool) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	m.vertex_color_use_as_albedo = true
	m.albedo_texture = tex
	m.billboard_mode = BaseMaterial3D.BILLBOARD_FIXED_Y if align else BaseMaterial3D.BILLBOARD_PARTICLES
	m.billboard_keep_scale = true
	m.disable_receive_shadows = true
	m.no_depth_test = false
	return m


func _mat_soft(tex: Texture2D, unshaded := false) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED if unshaded else BaseMaterial3D.SHADING_MODE_PER_PIXEL
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.vertex_color_use_as_albedo = true
	m.albedo_texture = tex
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.proximity_fade_enabled = true
	m.proximity_fade_distance = 0.6
	m.disable_receive_shadows = true
	m.roughness = 1.0
	return m


## Water: lit (street lights and neon catch it), glossy, a touch of self-light so it reads at night.
func _mat_water(tex: Texture2D) -> StandardMaterial3D:
	if _mats.has("water"):
		return _mats.water
	var m := StandardMaterial3D.new()
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.vertex_color_use_as_albedo = true
	m.albedo_texture = tex
	m.roughness = 0.08
	m.metallic_specular = 1.0
	m.emission_enabled = true
	m.emission = Color(0.12, 0.16, 0.22)
	m.billboard_mode = BaseMaterial3D.BILLBOARD_FIXED_Y
	m.billboard_keep_scale = true
	m.disable_receive_shadows = true
	_mats.water = m
	return m


func _ramp(cols: Array) -> GradientTexture1D:
	var g := Gradient.new()
	var offs := PackedFloat32Array()
	var cs := PackedColorArray()
	for i in cols.size():
		offs.append(float(i) / float(maxi(1, cols.size() - 1)))
		cs.append(cols[i])
	g.offsets = offs
	g.colors = cs
	var t := GradientTexture1D.new()
	t.gradient = g
	t.use_hdr = true
	return t


func _curve(pts: Array) -> CurveTexture:
	var c := Curve.new()
	c.max_value = 4.0
	for p in pts:
		c.add_point(p)
	var t := CurveTexture.new()
	t.curve = c
	return t


static func _dot_texture(n: int, power: float) -> ImageTexture:
	var img := Image.create(n, n, false, Image.FORMAT_RGBA8)
	for y in n:
		for x in n:
			var d := Vector2(x + 0.5 - n * 0.5, y + 0.5 - n * 0.5).length() / (n * 0.5)
			var a := pow(clampf(1.0 - d, 0.0, 1.0), power)
			img.set_pixel(x, y, Color(1, 1, 1, a))
	return ImageTexture.create_from_image(img)


static func _streak_texture() -> ImageTexture:
	var w := 16
	var h := 64
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	for y in h:
		for x in w:
			var dx := absf(x + 0.5 - w * 0.5) / (w * 0.5)
			var dy := absf(y + 0.5 - h * 0.5) / (h * 0.5)
			var a := clampf(1.0 - dx, 0.0, 1.0) * clampf(1.0 - dy * dy, 0.0, 1.0)
			img.set_pixel(x, y, Color(1, 1, 1, a * a))
	return ImageTexture.create_from_image(img)


var _ptex := {}


## Puddle maps: "a" = albedo with a ragged alpha edge, "orm" = AO 1, roughness ~0.05, metallic 0.
func _puddle_tex(kind: String) -> Texture2D:
	if _ptex.has(kind):
		return _ptex[kind]
	var n := 128
	var noise := FastNoiseLite.new()
	noise.seed = 11
	noise.frequency = 0.045
	noise.fractal_octaves = 3
	var img := Image.create(n, n, false, Image.FORMAT_RGBA8)
	for y in n:
		for x in n:
			var d := Vector2(x + 0.5 - n * 0.5, y + 0.5 - n * 0.5).length() / (n * 0.5)
			var edge := 0.78 + 0.22 * noise.get_noise_2d(x, y)
			var a := clampf((edge - d) * 6.0, 0.0, 1.0)
			if kind == "a":
				img.set_pixel(x, y, Color(0.06, 0.07, 0.08, a))
			else:
				img.set_pixel(x, y, Color(1.0, 0.04 + 0.05 * (1.0 - a), 0.0, a))
	_ptex[kind] = ImageTexture.create_from_image(img)
	return _ptex[kind]
