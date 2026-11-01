"""Build a "town block" test mesh with ~600 parts from the town kit: three
buildings side by side in one mesh, each building's UVs squeezed into its
own quadrant of the 0..1 square. Used to prove part masks past the old
256-part limit on real content (see docs/agents/scale-mcp/NOTES.md).

    blender -b --factory-startup --python tools/make_town_block.py

Writes assets/town/generated/town_block.glb (git-ignored; regenerate).
"""
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "town" / "generated" / "town_block.glb"
# building, x offset (m), UV quadrant origin
BUILDINGS = [("building_a", -13.0, (0.0, 0.5)), ("building_b", 0.0, (0.5, 0.5)), ("building_c", 13.0, (0.0, 0.0))]

bpy.ops.wm.read_factory_settings(use_empty=True)
pieces = []
for name, dx, (ou, ov) in BUILDINGS:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT / "assets" / "town" / f"{name}.glb"))
    meshes = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
    for o in meshes:
        # bake transforms so joining keeps the geometry where it was
        o.data = o.data.copy()
        o.data.transform(o.matrix_world)
        o.matrix_world.identity()
        o.location.x += dx
        uv = o.data.uv_layers.active
        uv.name = "UVMap"
        for d in uv.data:
            d.uv = (ou + d.uv[0] * 0.5, ov + d.uv[1] * 0.5)
        o.data.materials.clear()
        pieces.append(o)
    print(name, len(meshes), "mesh objects")

bpy.ops.object.select_all(action="DESELECT")
for o in pieces:
    o.select_set(True)
bpy.context.view_layer.objects.active = pieces[0]
bpy.ops.object.join()
block = bpy.context.view_layer.objects.active
block.name = "TownBlock"
for o in list(bpy.data.objects):
    if o is not block:
        bpy.data.objects.remove(o)
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(OUT), export_format="GLB", use_selection=False, export_materials="NONE")
print("wrote", OUT, len(block.data.polygons), "faces")
