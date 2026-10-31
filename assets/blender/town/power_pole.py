# Town kit: concrete power pole (~9 m) with crossbars, insulators and a transformer.
#
#   blender -b --factory-startup --python assets/blender/town/power_pole.py -- assets/town/power_pole.glb
#
# Tapered pole, two crossbars along X (wires run along the street) with
# diagonal braces, pin insulators (each one lathed piece), a transformer drum
# on a bracket, a cable riser and climbing step bolts. Pole at the origin.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

lathe("pole", [(0.17, 0.0), (0.11, 9.0), (0.09, 9.08), (0.0, 9.1)], (0, 0, 0), segs=20, bevel=0.0)
lathe("pole_footing", [(0.26, 0.0), (0.26, 0.3), (0.2, 0.36), (0.0, 0.37)], (0, 0, 0), segs=20, bevel=0.01)

INS = [(0.035, 0.0), (0.035, 0.04), (0.09, 0.05), (0.09, 0.07), (0.04, 0.08), (0.04, 0.12), (0.08, 0.13), (0.08, 0.15),
       (0.035, 0.16), (0.035, 0.2), (0.0, 0.22)]
for z, L, xs in ((8.6, 2.6, (-1.15, -0.4, 0.4, 1.15)), (7.8, 1.9, (-0.8, 0.8))):
    box("crossbar", (L, 0.14, 0.12), (0, -0.2, z), bevel=0.01)
    for s in (-1, 1):
        rod("crossbar_brace", (0, -0.15, z - 0.75), (s * L * 0.32, -0.2, z - 0.07), 0.025, verts=8)
    for x in xs:
        lathe("insulator", INS, (x, -0.2, z + 0.062), segs=14)
# transformer drum on a bracket, with bushings and a cable riser
box("transformer_bracket", (0.12, 0.42, 0.7), (0, -0.33, 6.3), bevel=0.01)
lathe("transformer", [(0.32, 0.0), (0.32, 0.95), (0.28, 1.0), (0.0, 1.02)], (0, -0.86, 5.85), segs=24, bevel=0.01)
for x in (-0.12, 0.12):
    lathe("bushing", INS, (x, -0.86, 6.87), segs=12)
cyl("riser", 0.035, 5.8, (0.16, 0.08, 3.0), bevel=0.0, verts=10)
# climbing step bolts, alternating sides
for k in range(8):
    z = 2.4 + k * 0.45
    s = 1 if k % 2 == 0 else -1
    r = 0.165 - 0.06 * z / 9.0
    rod("step_bolt", (s * (r - 0.03), 0, z), (s * (r + 0.2), 0, z), 0.014, verts=8)

export("PowerPole", centre_xy=False, view=(-1.0, -1.3, 0.45), close=[("close", (0, -0.4, 8.0), 1.6, (-0.9, -1.3, 0.5))])
