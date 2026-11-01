extends Node3D
## Feedback for the hero car: skid marks (one MultiMesh ring buffer of quads on the ground: one draw
## call), tyre smoke (a GPUParticles3D per wheel, emitting only while it slides), and generated audio
## (no samples): an engine loop pitched by rpm with on / off-load layers, an intake hiss, and a tyre
## squeal loop whose volume and pitch follow the sliding speed.

var car: RigidBody3D
const MARKS := 2400
const MARK_STEP := 0.28

var _mm: MultiMesh
var _mmi: MultiMeshInstance3D
var _next := 0
var _count := 0
var _last := []                 ## per wheel: last mark point (or null) and its intensity
var _smoke: Array[GPUParticles3D] = []
var _smoke_t: Array[float] = []
var _eng_on: AudioStreamPlayer
var _eng_off: AudioStreamPlayer
var _intake: AudioStreamPlayer
var _squeal: AudioStreamPlayer
var _wet_scrub: AudioStreamPlayer
var _audio := true
## Bungee Engine Audio (game/addons/bungee, MIT): recorded ACC/DCC/idle/limiter engine loops driven by
## our RPM. Windows only (native library); elsewhere the generated engine loops below are used.
var _bungee: Node = null
var _last_gear := 1
const ENGINE_BASE_RPM := 1500.0         ## the engine loops are made at this rpm (4 cylinders: 50 Hz firing)


func _ready() -> void:
	top_level = true
	global_transform = Transform3D()
	physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	_build_marks()
	for i in car.wheels.size():
		_last.append([null, 0.0])
		_smoke.append(_build_smoke())
		_smoke_t.append(0.0)
		_smoke[i].visible = false
	_audio = DisplayServer.get_name() != "headless"
	if _audio:
		_build_audio()


# ------------------------------------------------------------------ skid marks
func _build_marks() -> void:
	_mm = MultiMesh.new()
	_mm.transform_format = MultiMesh.TRANSFORM_3D
	_mm.use_colors = true
	var pm := PlaneMesh.new()
	pm.size = Vector2(1, 1)
	_mm.mesh = pm
	_mm.instance_count = MARKS
	_mm.visible_instance_count = 0
	var m := StandardMaterial3D.new()
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.vertex_color_use_as_albedo = true
	m.albedo_color = Color(1, 1, 1, 1)
	m.roughness = 0.75
	m.metallic_specular = 0.2
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.render_priority = 1
	pm.material = m
	_mmi = MultiMeshInstance3D.new()
	_mmi.name = "SkidMarks"
	_mmi.multimesh = _mm
	_mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_mmi.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	add_child(_mmi)


func reset_marks() -> void:
	for l in _last:
		l[0] = null


func _add_mark(a: Vector3, b: Vector3, n: Vector3, width: float, alpha: float) -> void:
	var d := b - a
	var len := d.length()
	if len < 0.01:
		return
	var z := d / len
	var x := n.cross(z).normalized()
	var y := z.cross(x)
	var xf := Transform3D(Basis(x * width, y, z * (len + 0.04)), (a + b) * 0.5 + n * 0.018)
	_mm.set_instance_transform(_next, xf)
	_mm.set_instance_color(_next, Color(0.02, 0.02, 0.022, alpha))
	_next = (_next + 1) % MARKS
	_count = mini(_count + 1, MARKS)
	_mm.visible_instance_count = _count


# ------------------------------------------------------------------ smoke
func _build_smoke() -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.amount = 64
	p.lifetime = 2.4
	p.local_coords = false
	p.emitting = false
	p.visibility_aabb = AABB(Vector3(-12, -2, -12), Vector3(24, 10, 24))
	p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	p.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	var pm := ParticleProcessMaterial.new()
	pm.direction = Vector3(0, 1, 0)
	pm.spread = 55.0
	pm.initial_velocity_min = 0.4
	pm.initial_velocity_max = 1.6
	pm.gravity = Vector3(0, 0.35, 0)
	pm.damping_min = 0.6
	pm.damping_max = 1.2
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	pm.emission_sphere_radius = 0.25
	pm.angle_min = -180.0
	pm.angle_max = 180.0
	pm.angular_velocity_min = -40.0
	pm.angular_velocity_max = 40.0
	var sc := Curve.new()
	sc.add_point(Vector2(0.0, 0.35))
	sc.add_point(Vector2(1.0, 1.0))
	var sct := CurveTexture.new()
	sct.curve = sc
	pm.scale_min = 1.6
	pm.scale_max = 2.6
	pm.scale_curve = sct
	var grad := Gradient.new()
	grad.set_color(0, Color(0.85, 0.85, 0.88, 0.55))
	grad.add_point(0.25, Color(0.8, 0.8, 0.84, 0.45))
	grad.set_color(grad.get_point_count() - 1, Color(0.7, 0.7, 0.74, 0.0))
	var gt := GradientTexture1D.new()
	gt.gradient = grad
	pm.color_ramp = gt
	p.process_material = pm
	var q := QuadMesh.new()
	q.size = Vector2(1, 1)
	var m := StandardMaterial3D.new()
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.vertex_color_use_as_albedo = true
	m.albedo_texture = _puff_texture()
	m.roughness = 1.0
	m.emission_enabled = true
	m.emission = Color(0.06, 0.06, 0.07)
	m.proximity_fade_enabled = true
	m.proximity_fade_distance = 0.6
	m.disable_receive_shadows = true
	q.material = m
	p.draw_pass_1 = q
	add_child(p)
	return p


static var _puff: Texture2D


static func _puff_texture() -> Texture2D:
	if _puff:
		return _puff
	var g := Gradient.new()
	g.set_color(0, Color(1, 1, 1, 1))
	g.set_color(1, Color(1, 1, 1, 0))
	g.add_point(0.45, Color(1, 1, 1, 0.55))
	var t := GradientTexture2D.new()
	t.gradient = g
	t.fill = GradientTexture2D.FILL_RADIAL
	t.fill_from = Vector2(0.5, 0.5)
	t.fill_to = Vector2(1.0, 0.5)
	t.width = 64
	t.height = 64
	_puff = t
	return t


# ------------------------------------------------------------------ audio (generated)
func _build_audio() -> void:
	_bungee = _make_bungee()
	_eng_on = _player(_engine_loop(true), -6.0)
	_eng_off = _player(_engine_loop(false), -9.0)
	_intake = _player(_noise_loop(), -30.0)
	# recorded-quality loops from tools/audio/make_tyre_sounds.py; the old synth is the fallback
	_squeal = _player(_loop_file("res://assets/audio/tyre_squeal.wav", _squeal_loop()), -60.0)
	_wet_scrub = _player(_loop_file("res://assets/audio/tyre_wet.wav", _noise_loop()), -60.0)


func _make_bungee() -> Node:
	var path := "res://addons/bungee/bungee_engine_audio.gd"
	# the native granular player (GDExtension, Windows) must be loaded, otherwise keep the generated engine
	if not ClassDB.class_exists("BungeeEngineNode") or not ResourceLoader.exists(path):
		return null
	var scr = load(path)
	if scr == null:
		return null
	var b: Node = scr.new()
	b.name = "BungeeEngine"
	b.set("live_input_mode", 1)              # External / custom vehicle logic
	b.set("use_3d_audio", false)
	b.set("reverb_enabled", false)
	b.set("output_headroom_db", -8.0)
	b.set("engine_running", true)
	car.add_child(b)
	return b


static func _loop_file(path: String, fallback: AudioStream) -> AudioStream:
	if not ResourceLoader.exists(path):
		return fallback
	var w = load(path)
	if w is AudioStreamWAV:
		w.loop_mode = AudioStreamWAV.LOOP_FORWARD
		w.loop_begin = 0
		w.loop_end = int(w.get_length() * w.mix_rate)
		return w
	return fallback


func _player(stream: AudioStream, db: float) -> AudioStreamPlayer:
	var p := AudioStreamPlayer.new()
	p.stream = stream
	p.volume_db = db
	p.autoplay = true
	add_child(p)
	return p


static func _wav(data: PackedFloat32Array, rate: int) -> AudioStreamWAV:
	var bytes := PackedByteArray()
	bytes.resize(data.size() * 2)
	for i in data.size():
		bytes.encode_s16(i * 2, int(clampf(data[i], -1.0, 1.0) * 32000.0))
	var w := AudioStreamWAV.new()
	w.format = AudioStreamWAV.FORMAT_16_BITS
	w.mix_rate = rate
	w.stereo = false
	w.data = bytes
	w.loop_mode = AudioStreamWAV.LOOP_FORWARD
	w.loop_begin = 0
	w.loop_end = data.size()
	return w


## One second of a 4-cylinder at ENGINE_BASE_RPM: firing pulses (50 Hz) as decaying bursts, crank
## orders as harmonics; on-load is rougher and brighter.  Whole cycles, so it loops seamlessly.
static func _engine_loop(on_load: bool) -> AudioStreamWAV:
	var rate := 22050
	var f0 := ENGINE_BASE_RPM / 60.0 * 2.0
	var data := PackedFloat32Array()
	data.resize(rate)
	var rng := RandomNumberGenerator.new()
	rng.seed = 11 if on_load else 12
	var orders := [[0.5, 0.35], [1.0, 1.0], [2.0, 0.55], [3.0, 0.3], [4.0, 0.22], [6.0, 0.12]] if on_load \
		else [[0.5, 0.25], [1.0, 1.0], [2.0, 0.3], [3.0, 0.1]]
	var ph := []
	for o in orders:
		ph.append(rng.randf() * TAU)
	var lp := 0.0
	var jitter := []
	for k in int(f0) + 1:
		jitter.append(rng.randf_range(0.85, 1.15))
	for i in rate:
		var t := float(i) / rate
		var s := 0.0
		for k in orders.size():
			s += float(orders[k][1]) * sin(TAU * f0 * float(orders[k][0]) * t + float(ph[k]))
		# combustion pulse: noise burst decaying after each firing
		var cyc := t * f0
		var fi := int(cyc)
		var frac := cyc - fi
		var pulse := exp(-frac * (7.0 if on_load else 10.0)) * float(jitter[fi % jitter.size()])
		var nz := rng.randf_range(-1.0, 1.0)
		lp += (nz - lp) * (0.35 if on_load else 0.15)
		s = s * 0.32 + lp * pulse * (0.55 if on_load else 0.25)
		data[i] = s * 0.55
	return _wav(data, rate)


static func _noise_loop() -> AudioStreamWAV:
	var rate := 22050
	var data := PackedFloat32Array()
	data.resize(rate)
	var rng := RandomNumberGenerator.new()
	rng.seed = 3
	var a := 0.0
	var b := 0.0
	for i in rate:
		a += (rng.randf_range(-1.0, 1.0) - a) * 0.25
		b += (a - b) * 0.5
		data[i] = (a - b) * 1.6
	return _wav(data, rate)


## Tyre squeal: a cluster of detuned partials around 1 kHz with slow wobble, plus filtered noise.
static func _squeal_loop() -> AudioStreamWAV:
	var rate := 22050
	var data := PackedFloat32Array()
	data.resize(rate)
	var rng := RandomNumberGenerator.new()
	rng.seed = 5
	var lp := 0.0
	var hp := 0.0
	for i in rate:
		var t := float(i) / rate
		var wob := sin(TAU * 3.0 * t) * 0.6 + sin(TAU * 7.0 * t) * 0.3
		var s := sin(TAU * (940.0 * t) + wob) * 0.5 + sin(TAU * 1180.0 * t + wob * 1.3) * 0.32 \
			+ sin(TAU * 1460.0 * t + wob * 0.7) * 0.18
		var n := rng.randf_range(-1.0, 1.0)
		lp += (n - lp) * 0.45
		hp += (lp - hp) * 0.08
		data[i] = (s * 0.6 + (lp - hp) * 0.5) * (0.75 + 0.25 * sin(TAU * 2.0 * t))
	return _wav(data, rate)


# ------------------------------------------------------------------ per tick (from car.gd)
func physics_update(delta: float) -> void:
	var total_slide := 0.0
	for i in car.wheels.size():
		var w = car.wheels[i]
		var sl: float = w.slip_vel if w.contact else 0.0
		# skid marks from ~2 m/s sliding (locked brakes, wheelspin, drifting)
		var k := clampf((sl - 2.0) / 5.0, 0.0, 1.0) * clampf(w.load / maxf(w.static_load * 0.4, 1.0), 0.0, 1.0)
		total_slide = maxf(total_slide, clampf((sl - 1.2) / 5.0, 0.0, 1.0) * (1.0 if w.contact else 0.0))
		var last: Array = _last[i]
		if w.contact and k > 0.05:
			var p: Vector3 = w.cpoint
			if last[0] == null:
				last[0] = p
				last[1] = k
			elif (p - last[0]).length() > MARK_STEP:
				var surf_k := 0.55 if car.wet > 0.5 else 0.85     # marks are fainter on a wet road
				_add_mark(last[0], p, w.cnormal, w.half_w * 1.7, minf(last[1], k) * surf_k)
				last[0] = p
				last[1] = k
		else:
			last[0] = null
		# smoke: hard sliding on dry-ish tarmac (wet roads spray a little)
		var sm: GPUParticles3D = _smoke[i]
		var sk := clampf((sl - 4.0) / 6.0, 0.0, 1.0) * (1.0 if w.contact else 0.0)
		if w.surface == "grass":
			sk *= 0.3
		sk *= lerpf(1.0, 0.55, car.wet)
		if sk > 0.05:
			sm.global_position = w.cpoint + Vector3.UP * 0.15
			sm.amount_ratio = clampf(sk, 0.15, 1.0)
			if not sm.emitting:
				sm.emitting = true
				sm.visible = true
			_smoke_t[i] = sm.lifetime + 0.2
		else:
			if sm.emitting:
				sm.emitting = false
			# once the last puff is gone the system stops drawing / simulating
			_smoke_t[i] -= delta
			if sm.visible and _smoke_t[i] <= 0.0:
				sm.visible = false
	_slide = total_slide


var _slide := 0.0
var _audio_t := 0.0


## Audio parameters at ~30 Hz from _process (setting player properties every physics tick is not free).
func _process(delta: float) -> void:
	_audio_t -= delta
	if _audio and _audio_t <= 0.0:
		_audio_t = 0.033
		_update_audio(delta, _slide)


func _update_audio(_delta: float, slide: float) -> void:
	if _bungee:
		var eng: Dictionary = car.P.engine
		var idle := float(eng.idle_rpm)
		var lim := float(eng.limiter_rpm)
		_bungee.set("rpm_position", clampf((car.rpm - idle) / maxf(lim - idle, 1.0), 0.0, 1.0))
		_bungee.set("throttle", clampf(car.throttle_out, 0.0, 1.0))
		_bungee.set("speed_kmh", car.speed_kmh)
		_bungee.set("wheelspin", clampf(slide, 0.0, 1.0))
		if car.gear != _last_gear and car.gear >= 1 and _last_gear >= 1:
			_bungee.set("trigger_gear_up" if car.gear > _last_gear else "trigger_gear_down", true)
		_last_gear = car.gear
		for p in [_eng_on, _eng_off, _intake]:
			p.stream_paused = true
	else:
		_engine_synth()
	_tyres(slide)


func _engine_synth() -> void:
	var rpm: float = maxf(car.rpm, 500.0)
	var pitch := rpm / ENGINE_BASE_RPM
	var load: float = clampf(car.throttle_out * 0.7 + car.engine_load * 0.6, 0.0, 1.0)
	_eng_on.pitch_scale = clampf(pitch, 0.3, 6.0)
	_eng_off.pitch_scale = clampf(pitch, 0.3, 6.0)
	var loud := clampf((rpm - 600.0) / 6500.0, 0.0, 1.0)
	_eng_on.volume_db = linear_to_db(maxf(0.02, load * (0.55 + loud * 0.45))) - 4.0
	_eng_off.volume_db = linear_to_db(maxf(0.02, (1.0 - load) * (0.45 + loud * 0.4))) - 6.0
	_intake.pitch_scale = clampf(0.6 + rpm / 7000.0, 0.5, 1.8)
	_intake.volume_db = linear_to_db(maxf(0.001, car.throttle_out * loud * 0.5)) - 12.0


func _tyres(slide: float) -> void:
	# dry: rubber squeals once it really slides (eased in); wet: no squeal, water swish instead
	var s := clampf(slide, 0.0, 1.0)
	var dry := 1.0 - clampf(car.wet, 0.0, 1.0)
	var sq := smoothstep(0.12, 0.7, s) * dry
	_squeal.volume_db = linear_to_db(maxf(0.0005, sq)) - 10.0
	_squeal.pitch_scale = 0.94 + sq * 0.12
	_squeal.stream_paused = sq < 0.01            # silent loops don't need mixing
	var sw := smoothstep(0.05, 0.6, s) * (1.0 - dry)
	_wet_scrub.volume_db = linear_to_db(maxf(0.0005, sw)) - 12.0
	_wet_scrub.pitch_scale = 0.9 + s * 0.25
	_wet_scrub.stream_paused = sw < 0.01
	_intake.stream_paused = _bungee != null or car.throttle_out < 0.02
