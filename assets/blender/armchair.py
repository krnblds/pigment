# Builds a tufted leather club armchair on a wooden frame for Pigment.
#
#   blender -b --factory-startup --python assets/blender/armchair.py -- assets/armchair.glb
#
# Material test: soft upholstery with big rounded bevels (Pebbled leather,
# Velvet, Linen: wear on the cushion edges and arm fronts, creases in the
# tufting dimples), turned wooden legs and a front apron (Oak / Varnished
# walnut grain on curved and flat wood), and brass nail-heads and leg
# ferrules (small metal parts in their own texture set). Three materials:
# Leather, Wood, Brass.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from kit import box, cone, cut, cyl, export, sphere  # noqa: E402

W, D = 0.86, 0.84  # outer width, depth
SEAT = 0.44  # seat cushion top

# --- upholstered body: base, arms, back ---
box("base", (W, D, 0.22), (0, 0, 0.24), bevel=0.04, segments=6, mat="Leather")
for s in (-1, 1):
    # rolled arms: a box with a fat bevel, and a cylinder roll on top
    box("arm", (0.15, D, 0.34), (s * (W / 2 - 0.075), 0, 0.47), bevel=0.05, segments=6, mat="Leather")
    cyl("arm_roll", 0.085, D - 0.02, (s * (W / 2 - 0.075), 0.01, 0.64), rot=(math.pi / 2, 0, 0), bevel=0.03, segments=5, verts=40, mat="Leather")

back = box("back", (W - 0.02, 0.2, 0.52), (0, D / 2 - 0.1, 0.62), bevel=0.06, segments=7, rot=(math.radians(-8), 0, 0), mat="Leather")

# tufting: dimples cut into the inside face of the back, a button in each
ang = math.radians(-8)
tufts = []
for row, z in enumerate((0.5, 0.64, 0.78)):
    xs = (-0.24, -0.08, 0.08, 0.24) if row % 2 == 0 else (-0.16, 0.0, 0.16)
    for x in xs:
        # point on the tilted front face of the back
        y = D / 2 - 0.2 + (z - 0.62) * math.tan(-ang) + 0.003
        tufts.append((x, y, z))
cutters = []
for p in tufts:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.028, location=(p[0], p[1] - 0.012, p[2]))
    c = bpy.context.active_object
    c.scale = (1, 0.7, 1)
    cutters.append(c)
cut(back, cutters, lip_bevel=0.006)
for p in tufts:
    sphere("button", 0.011, (p[0], p[1] + 0.006, p[2]), scale=(1, 0.55, 1), segs=16, rings=8, mat="Leather")

# loose seat cushion with a piped front edge
box("seat_cushion", (W - 0.32, D - 0.24, 0.1), (0, -0.09, SEAT - 0.05), bevel=0.035, segments=6, mat="Leather")
cyl("piping", 0.007, W - 0.36, (0, -0.09 - (D - 0.24) / 2 + 0.01, SEAT - 0.012), rot=(0, math.pi / 2, 0), bevel=0, verts=10, mat="Leather")

# --- wood: apron rail under the front and turned legs ---
box("apron", (W - 0.04, 0.03, 0.07), (0, -D / 2 - 0.005, 0.15), bevel=0.006, segments=3, mat="Wood")
for sx in (-1, 1):
    for sy in (-1, 1):
        x, y = sx * (W / 2 - 0.07), sy * (D / 2 - 0.07)
        cone("leg", 0.022, 0.032, 0.11, (x, y, 0.075), bevel=0.004, verts=24, mat="Wood")
        cyl("leg_collar", 0.036, 0.02, (x, y, 0.13), bevel=0.004, verts=24, mat="Wood")
        # brass ferrule on the foot
        cyl("ferrule", 0.024, 0.03, (x, y, 0.015), bevel=0.003, verts=24, mat="Brass")

# --- brass nail-heads along the front of each arm ---
for s in (-1, 1):
    x0 = s * (W / 2 - 0.075)
    for k in range(13):
        a = math.pi * k / 12
        # an arc over the arm front: up the outside, over the roll, down the inside
        x = x0 + 0.05 * math.cos(a) * s
        z = 0.47 + 0.12 * math.sin(a) if k not in (0, 12) else 0.47
        sphere("nail", 0.0065, (x, -D / 2 - 0.002, z), scale=(1, 0.6, 1), segs=12, rings=6, mat="Brass")
    for z in (0.33, 0.38, 0.43):
        for xs in (-0.05, 0.05):
            sphere("nail", 0.0065, (x0 + xs, -D / 2 - 0.002, z), scale=(1, 0.6, 1), segs=12, rings=6, mat="Brass")

export("Armchair")
