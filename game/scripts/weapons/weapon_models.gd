extends RefCounted
## Weapon models. Convention: grip at the origin, barrel along -Z (Godot) / +Y (Blender), a "Muzzle" node
## at the barrel end. Loads res://assets/weapons/<id>.glb (tools/weapons/make_weapons.py: Blender low-poly
## meshes textured in Pigment); without it a primitive stand-in of the same shape is built.

const DIR := "res://assets/weapons/"
const MUZZLE := {"stun_baton": Vector3(0, 0.0, -0.55), "taser": Vector3(0, 0.07, -0.2), "service_pistol": Vector3(0, 0.08, -0.2),
	"smg": Vector3(0, 0.07, -0.42), "shotgun": Vector3(0, 0.08, -0.72), "emp": Vector3(0, 0.0, 0.0)}


static func build(id: String) -> Node3D:
	var path := DIR + id + ".glb"
	var root: Node3D
	if ResourceLoader.exists(path):
		var ps = load(path)
		if ps:
			root = ps.instantiate()
	if root == null:
		root = _stand_in(id)
	root.name = "Weapon_" + id
	if not root.has_node("Muzzle"):
		var mz := Node3D.new()
		mz.name = "Muzzle"
		mz.position = MUZZLE.get(id, Vector3(0, 0.07, -0.25))
		root.add_child(mz)
	for mi in root.find_children("*", "GeometryInstance3D", true, false):
		(mi as GeometryInstance3D).cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	return root


static func _mat(c: Color, metal := 0.6, rough := 0.4, emit := 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.metallic = metal
	m.roughness = rough
	if emit > 0.0:
		m.emission_enabled = true
		m.emission = c
		m.emission_energy_multiplier = emit
	return m


static func _box(p: Node3D, size: Vector3, pos: Vector3, m: Material, rot := Vector3.ZERO) -> void:
	var mi := MeshInstance3D.new()
	var b := BoxMesh.new()
	b.size = size
	mi.mesh = b
	mi.material_override = m
	mi.position = pos
	mi.rotation = rot
	p.add_child(mi)


static func _cyl(p: Node3D, r: float, h: float, pos: Vector3, m: Material, along_z := true) -> void:
	var mi := MeshInstance3D.new()
	var c := CylinderMesh.new()
	c.top_radius = r
	c.bottom_radius = r
	c.height = h
	c.radial_segments = 10
	mi.mesh = c
	mi.material_override = m
	mi.position = pos
	if along_z:
		mi.rotation.x = PI * 0.5
	p.add_child(mi)


static func _stand_in(id: String) -> Node3D:
	var r := Node3D.new()
	var dark := _mat(Color(0.06, 0.065, 0.075), 0.7, 0.35)
	var grip := _mat(Color(0.03, 0.03, 0.035), 0.0, 0.8)
	var cyan := _mat(Color(0.3, 0.9, 1.0), 0.0, 0.3, 3.0)
	var amber := _mat(Color(1.0, 0.65, 0.2), 0.0, 0.3, 3.0)
	match id:
		"stun_baton":
			_cyl(r, 0.018, 0.2, Vector3(0, 0, 0.0), grip)
			_cyl(r, 0.014, 0.4, Vector3(0, 0, -0.3), dark)
			_cyl(r, 0.017, 0.06, Vector3(0, 0, -0.52), cyan)
		"taser":
			_box(r, Vector3(0.03, 0.1, 0.045), Vector3(0, -0.04, 0.0), grip, Vector3(0.25, 0, 0))
			_box(r, Vector3(0.038, 0.05, 0.19), Vector3(0, 0.05, -0.07), _mat(Color(0.9, 0.75, 0.1), 0.2, 0.5))
			_box(r, Vector3(0.04, 0.012, 0.03), Vector3(0, 0.05, -0.17), cyan)
		"service_pistol":
			_box(r, Vector3(0.03, 0.11, 0.045), Vector3(0, -0.045, 0.0), grip, Vector3(0.25, 0, 0))
			_box(r, Vector3(0.032, 0.04, 0.2), Vector3(0, 0.05, -0.07), dark)
			_box(r, Vector3(0.034, 0.006, 0.12), Vector3(0, 0.072, -0.07), cyan)
		"smg":
			_box(r, Vector3(0.032, 0.1, 0.045), Vector3(0, -0.04, 0.0), grip, Vector3(0.2, 0, 0))
			_box(r, Vector3(0.045, 0.07, 0.34), Vector3(0, 0.05, -0.1), dark)
			_box(r, Vector3(0.025, 0.14, 0.035), Vector3(0, -0.06, -0.12), dark)
			_cyl(r, 0.012, 0.12, Vector3(0, 0.06, -0.33), dark)
			_box(r, Vector3(0.04, 0.05, 0.16), Vector3(0, 0.06, 0.15), grip)
			_box(r, Vector3(0.046, 0.008, 0.14), Vector3(0, 0.088, -0.12), amber)
		"shotgun":
			_box(r, Vector3(0.035, 0.1, 0.045), Vector3(0, -0.04, 0.0), grip, Vector3(0.2, 0, 0))
			_box(r, Vector3(0.05, 0.07, 0.3), Vector3(0, 0.05, -0.08), dark)
			_cyl(r, 0.018, 0.5, Vector3(0, 0.07, -0.45), dark)
			_cyl(r, 0.02, 0.22, Vector3(0, 0.035, -0.36), grip)
			_box(r, Vector3(0.045, 0.07, 0.22), Vector3(0, 0.03, 0.2), grip)
		"emp":
			var mi := MeshInstance3D.new()
			var s := SphereMesh.new()
			s.radius = 0.045
			s.height = 0.09
			mi.mesh = s
			mi.material_override = dark
			r.add_child(mi)
			_cyl(r, 0.047, 0.012, Vector3.ZERO, cyan, false)
	return r
