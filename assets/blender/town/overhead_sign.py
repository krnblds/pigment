# Town kit: hanging bilingual sign box on a wall bracket.
#
#   blender -b --factory-startup --python assets/blender/town/overhead_sign.py -- assets/town/overhead_sign.glb
#
# Wall plate (its back face at y = 0, the wall plane), a bracket arm sticking
# out along -Y with a diagonal strut, two hanger rods and a sign box hanging
# perpendicular to the wall so its faces (+X and -X) read from the street.
# Each face panel is its own part (one side per language). Min z = 0 is the
# bottom of the box; mount it with the plate on a facade.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

AZ = 1.35  # arm height above the box bottom
box("wall_plate", (0.22, 0.03, 0.75), (0, -0.015, AZ - 0.2), bevel=0.006)
for z in (AZ + 0.08, AZ - 0.48):
    cyl("plate_bolt", 0.016, 0.03, (0, -0.04, z), rot=(math.pi / 2, 0, 0), bevel=0.003, verts=10)
box("arm", (0.07, 1.55, 0.09), (0, -0.03 - 0.775, AZ), bevel=0.008)
rod("strut", (0, -0.04, AZ - 0.5), (0, -0.75, AZ - 0.05), 0.02, verts=8)
box("arm_cap", (0.09, 0.03, 0.11), (0, -1.6, AZ), bevel=0.006)
# the box hangs on two rods, centred under the arm
SY, SH, ST, SL = -0.92, 0.95, 0.24, 1.15  # centre y, height, thickness (X), length (Y)
for dy in (-0.42, 0.42):
    rod("hanger", (0, SY + dy, AZ - 0.04), (0, SY + dy, SH + 0.01), 0.012, verts=8)
box("sign_box", (ST, SL, SH), (0, SY, SH / 2), bevel=0.02, segments=3)
for s in (-1, 1):
    box("sign_face", (0.012, SL - 0.1, SH - 0.1), (s * (ST / 2 + 0.008), SY, SH / 2), bevel=0.002)

export("OverheadSign", centre_xy=False, view=(-1.3, -0.9, 0.35))
