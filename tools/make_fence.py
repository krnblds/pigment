"""Build the town kit's chain-link fence segment (assets/town/fence.glb).

A 3 m x 2 m wire-mesh panel (one quad: the wire pattern is a Pigment
cut-out, not geometry), two posts, a top rail and a bottom rail. Origin at
the bottom centre, panel in the XZ plane (Blender), facing -Y.

    blender -b --factory-startup --python tools/make_fence.py
"""
import math
import os

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "town", "fence.glb")
W, H = 3.0, 2.0

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

parts = []
# the mesh panel: a single quad between the posts
bpy.ops.mesh.primitive_plane_add(size=1)
p = bpy.context.active_object
p.scale = (W - 0.06, H - 0.08, 1)
p.rotation_euler = (math.radians(90), 0, 0)
p.location = (0, 0, 0.04 + (H - 0.08) / 2)
parts.append(p)
# posts
for x in (-W / 2, W / 2):
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.03, depth=H + 0.1, location=(x, 0, (H + 0.1) / 2))
    parts.append(bpy.context.active_object)
# rails
for z in (H, 0.04):
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.018, depth=W, location=(0, 0, z), rotation=(0, math.radians(90), 0))
    parts.append(bpy.context.active_object)

for o in parts:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
bpy.ops.object.join()
fence = bpy.context.active_object
fence.name = "fence"
# origin at the bottom centre (the joined object kept the panel's origin)
bpy.context.scene.cursor.location = (0, 0, 0)
bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01, scale_to_bounds=True)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.shade_flat()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.export_scene.gltf(filepath=os.path.abspath(OUT), export_format="GLB", use_selection=True, export_materials="NONE")
print("WROTE", os.path.abspath(OUT))
