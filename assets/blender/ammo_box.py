# Builds a hard-surface ammo box for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/ammo_box.py -- assets/ammo_box.glb
#
# Bevelled parts (convex edges for edge wear), an overhanging lid and ribs
# (creases for dirt), handles and latches for silhouette. One UV set, no
# overlaps, everything inside 0..1, as Pigment expects.

import math
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "ammo_box.glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
parts = []


def finish(o, bevel, segments=3):
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.shade_smooth()
    if bevel > 0:
        m = o.modifiers.new("bevel", "BEVEL")
        m.width = bevel
        m.segments = segments
        m.limit_method = "ANGLE"
        m.angle_limit = math.radians(35)
        m.harden_normals = True
    o.select_set(False)
    parts.append(o)
    return o


def box(name, size, loc, bevel=0.006, segments=3):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    return finish(o, bevel, segments)


L, W, H = 0.60, 0.30, 0.26  # body
# body and lid: the lid overhangs, making a ledge all round
box("body", (L, W, H), (0, 0, H / 2), bevel=0.012, segments=4)
box("lid", (L + 0.02, W + 0.02, 0.07), (0, 0, H + 0.035), bevel=0.01, segments=4)
box("lid_panel", (L - 0.12, W - 0.09, 0.016), (0, 0, H + 0.07 + 0.008), bevel=0.005)
# vertical ribs wrapping the long sides
for x in (-0.17, 0.17):
    box("rib", (0.04, W + 0.016, H - 0.03), (x, 0, (H - 0.03) / 2 + 0.015), bevel=0.006)
# horizontal band on the body
box("band", (L + 0.012, W + 0.012, 0.035), (0, 0, 0.09), bevel=0.005)
# skids under the box
for y in (-0.105, 0.105):
    box("skid", (L + 0.03, 0.045, 0.028), (0, y, 0.014 - 0.02), bevel=0.006)
# front latches
for x in (-0.19, 0.19):
    box("latch_plate", (0.06, 0.014, 0.09), (x, -(W / 2 + 0.013), H - 0.005), bevel=0.004)
    box("latch_lever", (0.035, 0.012, 0.05), (x, -(W / 2 + 0.024), H - 0.01), bevel=0.003)
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.009, depth=0.07, location=(x, -(W / 2 + 0.016), H + 0.045), rotation=(0, math.pi / 2, 0))
    finish(bpy.context.active_object, 0.002, 2)
# ring handles on the ends, with mounting brackets
for s in (-1, 1):
    x = s * (L / 2 + 0.03)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.055, minor_radius=0.009, major_segments=40, minor_segments=12, location=(x, 0, 0.17), rotation=(0, math.pi / 2, 0))
    finish(bpy.context.active_object, 0)
    box("bracket", (0.03, 0.12, 0.035), (s * (L / 2 + 0.012), 0, 0.225), bevel=0.005)

# apply modifiers, join into one mesh
for o in parts:
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)
bpy.ops.object.select_all(action="DESELECT")
for o in parts:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
crate = bpy.context.active_object
crate.name = "AmmoBox"

# one UV set: smart project, then pack with a margin so seams can be padded
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
bpy.ops.uv.pack_islands(rotate=True, margin=0.006)
bpy.ops.object.mode_set(mode="OBJECT")

me = crate.data
print(f"AmmoBox: {len(me.vertices)} verts, {len(me.polygons)} faces, uv layers {len(me.uv_layers)}")
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_texcoords=True, export_normals=True, export_materials="NONE", export_yup=True)
print("exported", out)
