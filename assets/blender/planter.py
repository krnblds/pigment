# Builds a terracotta planter on a saucer, filled with soil and pebbles, for Pigment.
#
#   blender -b --factory-startup --python assets/blender/planter.py -- assets/planter.glb
#
# Material test: porous fired clay (Terracotta, Clay: efflorescence and water
# stains rising from the saucer with the Gradient generator, moss in the rim
# crease), a lumpy up-facing soil surface (Scatter pebbles / twigs, Cells,
# Puddles; a target for scatter_foliage), and a handful of loose stones.
# Three materials: Terracotta, Soil, Stone.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import displace, export, lathe, rock, spline  # noqa: E402

# pot: tapered wall with a rolled rim band, 9 mm wall, drainage foot ring
outer = [(0.0, 0.02), (0.11, 0.02), (0.115, 0.012), (0.125, 0.012), (0.13, 0.025), (0.165, 0.27),
         (0.172, 0.275), (0.19, 0.28), (0.195, 0.29), (0.195, 0.335), (0.19, 0.345), (0.178, 0.35)]
inner = [(0.17, 0.35), (0.168, 0.34), (0.168, 0.285), (0.156, 0.27), (0.12, 0.04), (0.0, 0.04)]
lathe("pot", outer[:4] + spline(outer[3:8], 3)[1:] + outer[8:] + inner, segs=72, mat="Terracotta", smooth_angle=35)

# saucer
saucer = [(0.0, 0.0), (0.17, 0.0), (0.2, 0.004), (0.215, 0.03), (0.21, 0.034), (0.2, 0.034),
          (0.19, 0.012), (0.0, 0.012)]
lathe("saucer", saucer, segs=72, mat="Terracotta", smooth_angle=35)

# soil: a lumpy disc 3 cm below the rim, its edge tucked under the inner wall
soil = lathe("soil", [(0.0, 0.318), (0.06, 0.318), (0.12, 0.316), (0.166, 0.312), (0.172, 0.29)], segs=72, mat="Soil", smooth_angle=80)
displace(soil, 0.012, 14.0, seed=2, mask=lambda co: 1.0 if co.z > 0.305 and (co.x * co.x + co.y * co.y) < 0.155 ** 2 else 0.0)

# loose stones on the soil and one fallen in the saucer
for i, (x, y, r, sz) in enumerate([(0.05, 0.04, 0.022, 0.6), (-0.07, 0.02, 0.016, 0.7), (0.0, -0.08, 0.019, 0.5),
                                   (-0.03, 0.09, 0.012, 0.8), (0.09, -0.05, 0.014, 0.6)]):
    rock("pebble", r, (x, y, 0.322), scale=(1.0, 0.8, sz), seed=i + 1, sub=3, rough=0.2, mat="Stone")
rock("pebble", 0.015, (0.18, 0.06, 0.018), scale=(1.0, 0.85, 0.6), seed=9, sub=3, rough=0.2, mat="Stone")

export("Planter")
