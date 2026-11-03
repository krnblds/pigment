# Builds a cluster of three boulders and some scree for Pigment.
#
#   blender -b --factory-startup --python assets/blender/boulders.py -- assets/boulders.glb
#
# Material test, one material (Rock): fully organic surfaces with no hard
# edges and no flat faces, so every generator has to work from curvature and
# AO alone (Rock strata and cracks, Moss on the tops and in the gaps between
# the stones, Leaks and Streaks down the flanks, lichen Spots, Snow on
# up-facing slopes). Smart-projected UVs with many seams test seam bleed.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import export, rock  # noqa: E402

rock("boulder_big", 0.7, (0, 0, 0.24), scale=(1.3, 1.0, 0.85), seed=1, sub=5)
rock("boulder_mid", 0.45, (1.05, 0.45, 0.14), scale=(1.1, 0.9, 0.8), seed=2, sub=5)
rock("boulder_small", 0.3, (-0.85, -0.65, 0.08), scale=(1.0, 1.2, 0.7), seed=3, sub=4)
# scree around the foot
for i, (x, y, r) in enumerate([(0.55, -0.75, 0.09), (0.75, -0.55, 0.06), (-0.3, -0.95, 0.07), (-1.2, -0.2, 0.08),
                               (1.5, 0.0, 0.07), (1.35, 0.95, 0.1), (0.2, 0.95, 0.06), (-0.6, 0.8, 0.08),
                               (-1.0, 0.35, 0.05), (0.95, -0.15, 0.05)]):
    rock("scree", r, (x, y, r * 0.25), scale=(1.0, 0.85, 0.65), seed=10 + i, sub=3, rough=0.25)

export("Boulders")
