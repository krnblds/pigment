@tool
extends GLTFDocumentExtension
## KHR_materials_variants for Godot 4 (the fleet's paint / livery variants).
##
## Godot's glTF importer parses every material of a file but only assigns each primitive's default
## one; it ignores KHR_materials_variants. This extension keeps the mappings: at import it stores,
## on every MeshInstance3D with variants, the meta "gltf_variants" = {variant name: [material per
## surface]}, and on the scene root "gltf_variant_names" = [names in file order].
##
## Register it once (an autoload or an EditorPlugin's _enter_tree):
##     GLTFDocument.register_gltf_document_extension(preload("res://.../vehicle_variants.gd").new())
## then re-import the .glb files. At runtime:
##     var car := preload("res://assets/vehicles/mame/mame.glb").instantiate()
##     VehicleVariants.set_variant(car, "tsuru")        # or set_variant_index(car, 5)
## Variant names, labels, kinds and spawn weights are in assets/vehicles/<id>/<id>.json and
## assets/vehicles/index.json.
##
## Without the extension (or for files imported before it was registered) the same switch can be
## done by hand: every variant material is in the file, named "<id>_<variant>".
class_name VehicleVariants


func _import_post(state: GLTFState, root: Node) -> Error:
	var j: Dictionary = state.json
	var ext: Dictionary = j.get("extensions", {}).get("KHR_materials_variants", {})
	if ext.is_empty():
		return OK
	var names: Array = []
	for v in ext.get("variants", []):
		names.append(String(v.get("name", "variant%d" % names.size())))
	root.set_meta("gltf_variant_names", names)
	var mats: Array = state.get_materials()
	var meshes: Array = j.get("meshes", [])
	var nodes: Array = j.get("nodes", [])
	for i in nodes.size():
		var nd: Dictionary = nodes[i]
		if not nd.has("mesh"):
			continue
		var prims: Array = meshes[int(nd["mesh"])].get("primitives", [])
		var table := {}
		var any := false
		for s in prims.size():
			var maps: Array = prims[s].get("extensions", {}).get("KHR_materials_variants", {}).get("mappings", [])
			for m in maps:
				any = true
				for vi in m.get("variants", []):
					var nm: String = names[int(vi)]
					if not table.has(nm):
						table[nm] = []
						table[nm].resize(prims.size())
					table[nm][s] = mats[int(m["material"])]
		if not any:
			continue
		var node := state.get_scene_node(i)
		if node:
			node.set_meta("gltf_variants", table)
	return OK


## Show `variant` on every mesh under `root` that has it. Returns false if no mesh knows it.
static func set_variant(root: Node, variant: String) -> bool:
	var found := false
	for n in _meshes(root):
		var table: Dictionary = n.get_meta("gltf_variants", {})
		if not table.has(variant):
			continue
		var surf: Array = table[variant]
		for s in surf.size():
			if surf[s] != null:
				n.set_surface_override_material(s, surf[s])
		found = true
	return found


static func set_variant_index(root: Node, index: int) -> bool:
	var names: Array = root.get_meta("gltf_variant_names", [])
	return index >= 0 and index < names.size() and set_variant(root, names[index])


## Pick a variant by the weights in <id>.json ("variants": [{name, weight}, ...]).
static func pick_weighted(variants: Array, rng: RandomNumberGenerator) -> String:
	var total := 0.0
	for v in variants:
		total += float(v.get("weight", 1.0))
	var r := rng.randf() * total
	for v in variants:
		r -= float(v.get("weight", 1.0))
		if r <= 0.0:
			return String(v["name"])
	return String(variants[-1]["name"]) if variants.size() else ""


static func _meshes(root: Node) -> Array:
	var out: Array = []
	var stack: Array = [root]
	while stack.size():
		var n: Node = stack.pop_back()
		if n is MeshInstance3D and n.has_meta("gltf_variants"):
			out.append(n)
		stack.append_array(n.get_children())
	return out
