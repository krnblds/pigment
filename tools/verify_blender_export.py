"""Import a Pigment export in a fresh Blender process; no user scene is changed.

Invoked by `pigment verify-export DIR --blender /path/to/blender`.
"""
import importlib.util
import json
from pathlib import Path
import sys

import bpy

folder, bridge_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
spec = importlib.util.spec_from_file_location("pigment_bridge_verify", bridge_path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
sidecar = json.loads((folder / "material.json").read_text())
loaded_meshes = set()
for name, entry in sidecar["materials"].items():
    material_spec = bridge.discover(str(folder), name)
    material = bridge.build_material(material_spec)
    assert material.use_nodes and len(material.node_tree.links), f"{name}: empty material graph"
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            assert node.image and node.image.size[0] > 0, f"{name}: image failed to load"
    mesh = entry.get("mesh")
    if mesh:
        mesh = Path(mesh)
        if not mesh.is_absolute():
            mesh = folder / mesh
        if mesh in loaded_meshes:
            continue
        loaded_meshes.add(mesh)
        before = set(bpy.data.objects)
        if mesh.suffix.lower() in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=str(mesh))
        elif mesh.suffix.lower() == ".obj":
            bpy.ops.wm.obj_import(filepath=str(mesh))
        else:
            raise ValueError(f"Unsupported mesh: {mesh}")
        objects = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
        assert objects, f"{mesh}: imported no mesh objects"
        for obj in objects:
            assert obj.data.uv_layers and obj.data.polygons, f"{mesh}: missing UVs or faces"
            obj.data.materials.append(material)
print("PIGMENT_IMPORT_OK")
