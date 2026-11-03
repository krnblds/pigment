# Builds a 16 x 16 m patch of terrain for Pigment terrain painting.
#
#   blender -b --factory-startup --python assets/blender/terrain.py -- assets/terrain.glb
#
# Material test at landscape scale: rolling ground rising to a bank at the
# back (+y), a hollow that holds a puddle (Puddles), a shallow worn trench
# winding across for a path (painted in Pigment with paint_stroke), and four
# boulders half buried in the bank. Two materials: Ground (a planar top-down
# UV over the whole patch, one texture set at 4096 = 4 mm a texel; soil,
# grass blades, gravel, leaves, foliage cards) and Rock (the boulders,
# smart-projected; Rock strata, Moss, lichen).
#
# The ground sits around z = 0; heights are in metres.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from kit import export, fbm, finish, rock  # noqa: E402
from mathutils import Vector  # noqa: E402

SIZE = 16.0
N = 160  # quads per side: 10 cm


def path_y(x):
    """Centre line of the path: it wanders across the patch, left to right."""
    return -1.2 + 1.6 * math.sin(x * 0.38 + 0.6) + 0.4 * math.sin(x * 1.1)


def height(x, y):
    p = Vector((x, y, 0))
    h = 0.3 * fbm(p * 0.12, 3) + 0.06 * fbm(p * 0.7, 3)
    # the bank: rises towards the back, its foot wandering
    foot = 2.5 + 0.8 * fbm(Vector((x * 0.25, 0, 3)), 2)
    t = min(max((y - foot) / 4.5, 0.0), 1.0)
    h += 2.0 * t * t * (3 - 2 * t) * (0.8 + 0.25 * fbm(p * 0.3 + Vector((5, 0, 0)), 2))
    # a hollow that holds water
    h -= 0.32 * math.exp(-((x - 3.2) ** 2 + (y + 4.6) ** 2) / 2.2)
    # the worn path: a shallow trench, flatter in its bed
    d = abs(y - path_y(x))
    h -= 0.07 * math.exp(-(d / 0.55) ** 2)
    return h


me = bpy.data.meshes.new("ground")
verts, faces = [], []
for j in range(N + 1):
    for i in range(N + 1):
        x = -SIZE / 2 + SIZE * i / N
        y = -SIZE / 2 + SIZE * j / N
        verts.append((x, y, height(x, y)))
for j in range(N):
    for i in range(N):
        a = j * (N + 1) + i
        faces.append((a, a + 1, a + N + 2, a + N + 1))
me.from_pydata(verts, [], faces)
ground = bpy.data.objects.new("ground", me)
bpy.context.collection.objects.link(ground)
bpy.context.view_layer.objects.active = ground
ground.select_set(True)
bpy.ops.object.shade_smooth()
ground.select_set(False)
finish(ground, 0, mat="Ground")

# boulders half buried in the bank and one by the path
for k, (x, y, r, sq) in enumerate([(-4.2, 4.3, 1.1, 0.75), (-2.6, 5.1, 0.7, 0.8), (1.4, 5.6, 0.9, 0.7), (5.3, 3.9, 1.2, 0.65), (-6.0, -2.4, 0.45, 0.7)]):
    rock("boulder", r, (x, y, height(x, y) + r * sq * 0.1), scale=(1.2, 1.0, sq), seed=20 + k, sub=5 if r > 0.6 else 4, mat="Rock",
         flat_base=False, chips=26, strata=0.025, grain=0.012)

export("Terrain", ground=False, planar={"Ground": (0.0, 0.0, SIZE / 2)}, max_tris=160000)
