# Builds a lathed porcelain vase with a gilded lip and foot for Pigment.
#
#   blender -b --factory-startup --python assets/blender/vase.py -- assets/vase.glb
#
# Material test: long smooth curves with no hard edges (glaze, crackle,
# Porcelain / Marble white), a hollow neck you can see into (AO falls off
# inside), and two thin Gold bands as their own texture set. Two materials:
# Ceramic, Gold.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import cyl, export, lathe, spline, torus  # noqa: E402

# outer profile bottom -> lip, then back down the inside (wall 6 mm)
outer = [(0.0, 0.012), (0.055, 0.012), (0.062, 0.016), (0.075, 0.03), (0.105, 0.08), (0.125, 0.14),
         (0.128, 0.18), (0.118, 0.23), (0.09, 0.28), (0.058, 0.32), (0.045, 0.35), (0.044, 0.38),
         (0.05, 0.405), (0.062, 0.42)]
inner = [(0.056, 0.42), (0.044, 0.405), (0.038, 0.38), (0.039, 0.35), (0.052, 0.32), (0.084, 0.28),
         (0.112, 0.23), (0.122, 0.18), (0.119, 0.14), (0.099, 0.08), (0.06, 0.035), (0.0, 0.03)]
lathe("body", outer[:1] + spline(outer[1:], 5) + spline(inner[:-1], 5) + inner[-1:], segs=72, mat="Ceramic", smooth_angle=50)

# gilded foot ring and lip bead
cyl("foot", 0.064, 0.012, (0, 0, 0.006), bevel=0.003, segments=3, verts=72, mat="Gold")
torus("lip", 0.059, 0.0035, (0, 0, 0.42), maj=72, mi=10, mat="Gold")
torus("shoulder_band", 0.098, 0.0022, (0, 0, 0.267), maj=72, mi=8, mat="Gold")

export("Vase")
