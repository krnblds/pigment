"""Headless Blender: a plain background tower for the window-grid / tiles demo.

A 10 x 30 x 10 m box with no modelled windows, a 30 cm deep ledge band at
the first floor, a cornice at the top and a few AC units on the facade, UV
unwrapped (smart project) and exported as GLB (Y up, metres).

    blender -b --factory-startup --python docs/agents/generators/make_tower.py -- out.glb
"""
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)


def box(name, x0, y0, z0, x1, y1, z1):
    # Blender is Z up: (x, y, z) here are Blender coordinates
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.object
    o.scale = (x1 - x0, y1 - y0, z1 - z0)
    o.name = name
    bpy.ops.object.transform_apply(scale=True)
    return o


parts = [
    box("tower", -5, -5, 0, 5, 5, 30),
    box("ledge", -5.3, -5.3, 4.0, 5.3, 5.3, 4.25),
    box("cornice", -5.4, -5.4, 29.6, 5.4, 5.4, 30.0),
]
# AC units on the -y facade (the glTF +z front after export), various floors
for i, (x, z) in enumerate([(-2.8, 9.1), (1.6, 12.3), (-0.4, 18.7), (2.9, 21.9), (-3.2, 25.1)]):
    parts.append(box(f"ac{i}", x - 0.41, -5.32, z - 0.28, x + 0.41, -5.0, z + 0.28))
bpy.ops.object.select_all(action="DESELECT")
for p in parts:
    p.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.004)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=False, export_yup=True)
print("wrote", out)
