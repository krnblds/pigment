extends RefCounted
## Pigment foliage in Godot: builds the cards exported by Pigment's
## `export_foliage` / `send_to_blender` (<name>_foliage_instances.json plus
## the atlas maps next to it) as one MultiMeshInstance3D per cell.
##
## Each group in the JSON has the cell's UV rect (v down, as Godot), its card
## mesh (quad / cross / star), its mount and a flat list of 12 floats per
## instance: basis columns x, y, z and the origin, for a unit card spanning
## x -0.5..0.5, y 0..1 (z = card normal x card width). Pigment, glTF and Godot
## share axes (Y up, metres), so the cards line up with the painted mesh.
##
## Material: foliage_card.gdshader (alpha scissor, two-sided, BACKLIGHT from the
## Translucency map, wind sway).
##
##   var FoliageLoader := preload("res://scripts/foliage_loader.gd")
##   add_child(FoliageLoader.build("C:/exports/building_a/building_a_foliage_instances.json"))

const CardShader := preload("res://scripts/foliage_card.gdshader")
const MOUNTS := {"upright": 0, "flat": 1, "wall": 2, "hanging": 3}


static func load_texture(path: String) -> Texture2D:
	if path == "" or not FileAccess.file_exists(path):
		return null
	var img := Image.load_from_file(path)
	if img == null:
		return null
	img.generate_mipmaps()
	return ImageTexture.create_from_image(img)


## Unit card for one atlas cell: quads in the card's local frame.
static func card_mesh(uv: Array, kind: String) -> ArrayMesh:
	var quads := 1
	if kind == "cross":
		quads = 2
	elif kind == "star":
		quads = 3
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var u0: float = uv[0]
	var v0: float = uv[1]
	var u1: float = uv[2]
	var v1: float = uv[3]
	for q in quads:
		var a := PI * float(q) / float(quads)
		var side := Vector3(cos(a), 0.0, sin(a))       # local x for q = 0; the z column carries the width
		var n := side.cross(Vector3.UP).normalized()
		var corners := [Vector2(-0.5, 0.0), Vector2(0.5, 0.0), Vector2(0.5, 1.0), Vector2(-0.5, 0.0), Vector2(0.5, 1.0), Vector2(-0.5, 1.0)]
		for c in corners:
			st.set_normal(n)
			st.set_uv(Vector2(lerpf(u0, u1, c.x + 0.5), lerpf(v1, v0, c.y)))
			st.add_vertex(side * c.x + Vector3(0.0, c.y, 0.0))
	st.generate_tangents()
	return st.commit()


## Build every group of an instances JSON. `wind` < 0 keeps the exported value.
static func build(json_path: String, wind := -1.0) -> Node3D:
	var root := Node3D.new()
	root.name = "PigmentFoliage"
	var f := FileAccess.open(json_path, FileAccess.READ)
	if f == null:
		push_error("foliage: can't read %s" % json_path)
		return root
	var j = JSON.parse_string(f.get_as_text())
	if typeof(j) != TYPE_DICTIONARY:
		push_error("foliage: bad JSON in %s" % json_path)
		return root
	var dir := json_path.get_base_dir()
	var maps: Dictionary = j.get("maps", {})
	var tex := func(role: String) -> Texture2D:
		return load_texture(dir.path_join(String(maps.get(role, "")))) if maps.has(role) else null
	var albedo: Texture2D = tex.call("base_color_alpha")
	var normal: Texture2D = tex.call("normal")
	var rough: Texture2D = tex.call("roughness")
	var trans: Texture2D = tex.call("translucency")
	var w: float = wind if wind >= 0.0 else float(j.get("wind", 0.0))
	var cards := 0
	for g in j.get("groups", []):
		var xf: Array = g.get("transforms", [])
		var n := xf.size() / 12
		if n == 0:
			continue
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = card_mesh(g.get("uv", [0, 0, 1, 1]), String(g.get("mesh", "quad")))
		mm.instance_count = n
		for i in n:
			var k := i * 12
			var b := Basis(Vector3(xf[k], xf[k + 1], xf[k + 2]), Vector3(xf[k + 3], xf[k + 4], xf[k + 5]), Vector3(xf[k + 6], xf[k + 7], xf[k + 8]))
			mm.set_instance_transform(i, Transform3D(b, Vector3(xf[k + 9], xf[k + 10], xf[k + 11])))
		var mat := ShaderMaterial.new()
		mat.shader = CardShader
		mat.set_shader_parameter("albedo_alpha", albedo)
		if normal:
			mat.set_shader_parameter("normal_map", normal)
		if rough:
			mat.set_shader_parameter("roughness_map", rough)
		if trans:
			mat.set_shader_parameter("translucency", trans)
		mat.set_shader_parameter("wind", w)
		mat.set_shader_parameter("mount", int(MOUNTS.get(String(g.get("mount", "upright")), 0)))
		var mmi := MultiMeshInstance3D.new()
		mmi.name = String(g.get("cell", "cards"))
		mmi.multimesh = mm
		mmi.material_override = mat
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
		root.add_child(mmi)
		cards += n
	print("foliage: %d cards in %d groups from %s" % [cards, root.get_child_count(), json_path.get_file()])
	return root
