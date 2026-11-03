# Builds a broken fluted marble column on a stepped plinth, with a fallen
# drum beside it, for Pigment.
#
#   blender -b --factory-startup --python assets/blender/stone_column.py -- assets/stone_column.glb
#
# Material test, one material (Stone): Marble white / Granite / Sandstone /
# Mossy stone over long concave flutes (dirt and moss in the grooves, wear on
# the arrises between them), a rough fractured top and broken drum faces
# (Rock / Cells cracks, Leaks running down from the break), crisp stepped
# plinth edges (chips), and up-facing steps for Moss and Puddles.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from kit import box, displace, export, fbm, finish, lathe  # noqa: E402
from mathutils import Vector  # noqa: E402

FLUTES = 20
SEG = FLUTES * 8


def shaft(name, r, z0, z1, rings, break_top=None, break_bottom=None, loc=(0, 0, 0), rot=None):
    """A fluted drum: radius dips in FLUTES concave grooves; optional jagged
    break planes at either end (a function z_offset(x, y))."""
    me = bpy.data.meshes.new(name)
    verts, faces = [], []
    for k in range(rings + 1):
        t = k / rings
        for i in range(SEG):
            a = 2 * math.pi * i / SEG
            f = (i % 8) / 8  # position across a flute
            depth = 0.022 * r * 6 * math.sin(math.pi * f) ** 0.6 if f > 0.12 and f < 0.88 else 0.0
            rr = r * (1 - 0.06 * t) - depth  # entasis: slight taper
            x, y = rr * math.cos(a), rr * math.sin(a)
            z = z0 + (z1 - z0) * t
            if k == rings and break_top:
                z += break_top(x, y)
            if k == 0 and break_bottom:
                z += break_bottom(x, y)
            verts.append((x, y, z))
    for k in range(rings):
        for i in range(SEG):
            j = (i + 1) % SEG
            faces.append((k * SEG + i, k * SEG + j, (k + 1) * SEG + j, (k + 1) * SEG + i))
    # caps: fans to a centre vertex (broken faces get a noisy centre)
    for k, zc, fn in ((0, z0, break_bottom), (rings, z1, break_top)):
        c = len(verts)
        verts.append((0, 0, zc + (fn(0, 0) if fn else 0)))
        for i in range(SEG):
            j = (i + 1) % SEG
            f = (k * SEG + j, k * SEG + i, c) if k == 0 else (k * SEG + i, k * SEG + j, c)
            faces.append(f)
    me.from_pydata(verts, [], faces)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    if rot:
        o.rotation_euler = rot
    o.location = loc
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=False)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(50))
    o.select_set(False)
    return finish(o, 0, mat="Stone")


def jagged(seed, tilt, amp):
    off = Vector((seed * 3.1, seed * 7.7, 0))
    return lambda x, y: tilt * x + amp * fbm(Vector((x, y, 0)) * 18 + off, 4) + amp * 0.5 * fbm(Vector((x, y, 0)) * 60 + off, 2)


R = 0.24
# stepped plinth
box("step_low", (1.0, 1.0, 0.12), (0, 0, 0.06), bevel=0.006, segments=2, mat="Stone")
box("step_high", (0.82, 0.82, 0.12), (0, 0, 0.18), bevel=0.006, segments=2, mat="Stone")
box("plinth", (0.66, 0.66, 0.1), (0, 0, 0.29), bevel=0.005, segments=2, mat="Stone")
# attic base mouldings: torus / scotia / torus as a lathe
lathe("base", [(0.0, 0.34), (0.31, 0.34), (0.315, 0.36), (0.31, 0.38), (0.29, 0.39), (0.27, 0.395),
               (0.262, 0.41), (0.27, 0.425), (0.275, 0.44), (0.27, 0.455), (0.25, 0.46), (0.0, 0.46)],
      segs=SEG, mat="Stone", smooth_angle=35)
# standing shaft, broken at an angle
shaft("shaft", R, 0.46, 1.9, 96, break_top=jagged(1, 0.35, 0.06))
# fallen drum on the low step and the ground, broken both ends
shaft("drum", R * 0.94, -0.3, 0.3, 40, break_top=jagged(2, 0.1, 0.05), break_bottom=jagged(3, -0.12, 0.05),
      loc=(0.95, -0.85, R * 0.94), rot=(math.radians(90), 0, math.radians(20)))

# chipped corners: a few chunks knocked off the lower step by displacing its corner verts
low = bpy.data.objects["step_low"]
bpy.context.view_layer.objects.active = low
for m in list(low.modifiers):
    bpy.ops.object.modifier_apply(modifier=m.name)
displace(low, 0.02, 9.0, seed=4, mask=lambda co: max(0.0, (abs(co.x) + abs(co.y) - 0.85) / 0.15))

export("StoneColumn")
