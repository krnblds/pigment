# Town kit: street lamp (~6 m), pole base at the origin, arm reaching out over -Y.
#
#   blender -b --factory-startup --python assets/blender/town/street_lamp.py -- assets/town/street_lamp.glb
#
# Base plate with anchor bolts, a tapered pole with a base collar and an access
# hatch, an angled arm, the lamp head and its glass lens (head and lens are
# separate parts). The pole stays at the origin (not the bbox centre) so it can
# be dropped onto a sidewalk.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

box("base_plate", (0.42, 0.42, 0.04), (0, 0, 0.02), bevel=0.008)
for sx in (-1, 1):
    for sy in (-1, 1):
        cyl("anchor_bolt", 0.018, 0.06, (sx * 0.15, sy * 0.15, 0.05), bevel=0.003, verts=10)
lathe("collar", [(0.15, 0.04), (0.15, 0.5), (0.11, 0.56), (0.0, 0.57)], (0, 0, 0.0), segs=20, bevel=0.008)
lathe("pole", [(0.095, 0.0), (0.06, 5.0), (0.0, 5.0)], (0, 0, 0.55), segs=20)
box("access_hatch", (0.1, 0.03, 0.22), (0, -0.108, 0.85), bevel=0.006)
# arm: short vertical stub, then angled up and out over -Y
ax, ay, az = 0.0, -1.7, 6.05
rod("arm", (0, 0.0, 5.35), (ax, ay, az), 0.045, bevel=0.0, verts=12)
rod("arm_brace", (0, -0.03, 4.75), (0, -0.85, 5.67), 0.025, verts=10)
# lamp head (slightly tilted with the arm) and its lens underneath
tilt = math.radians(8)
box("lamp_head", (0.34, 0.75, 0.13), (0, ay - 0.25, az + 0.02), bevel=0.02, segments=3, rot=(tilt, 0, 0))
box("lamp_lens", (0.26, 0.62, 0.02), (0, ay - 0.25, az - 0.05), bevel=0.004, rot=(tilt, 0, 0))

export("StreetLamp", centre_xy=False, view=(-1.0, -1.2, 0.6), close=[("close", (0, -1.8, 5.9), 0.8, (-1.0, -0.6, -0.35))])
