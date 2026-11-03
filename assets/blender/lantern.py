# Builds a hexagonal candle lantern for Pigment.
#
#   blender -b --factory-startup --python assets/blender/lantern.py -- assets/lantern.glb
#
# Material test: six glass panes as their own texture set (Clear / Smoked /
# Frosted glass: transmission and opacity, soot Gradient rising inside,
# grime in the pane corners), a wax candle (Bone / Porcelain, soot on the
# rim) and its flame for emissive + bloom (Warm bulb, Neon amber), and a pressed-tin frame (Copper patina,
# Weathered galvanized, Hammered copper: verdigris in the cavities under the
# roof, wear on the handle ring). Four materials: Metal, Glass, Wax, Flame.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import box, cyl, export, lathe, sphere, torus  # noqa: E402

RP = 0.085  # circumradius of the hexagon at the posts
Z0, Z1 = 0.035, 0.27  # glass from .. to

# base and roof: hexagonal lathes (segs=6), corners on the posts
lathe("base", [(0.0, 0.0), (0.1, 0.0), (0.1, 0.012), (0.094, 0.018), (0.094, 0.028), (0.09, Z0), (0.0, Z0)], segs=6, mat="Metal")
lathe("roof", [(0.0, Z1), (0.096, Z1), (0.104, Z1 + 0.008), (0.1, Z1 + 0.014), (0.06, Z1 + 0.06),
               (0.024, Z1 + 0.08), (0.024, Z1 + 0.09), (0.0, Z1 + 0.09)], segs=6, mat="Metal")
# vented chimney cap and finial
cyl("chimney", 0.018, 0.03, (0, 0, Z1 + 0.105), bevel=0.002, verts=24, mat="Metal")
sphere("finial", 0.012, (0, 0, Z1 + 0.13), segs=16, rings=8, mat="Metal")
torus("handle", 0.045, 0.0045, (0, 0, Z1 + 0.175), rot=(math.pi / 2, 0, 0), maj=40, mi=8, mat="Metal")

for k in range(6):
    a = math.pi / 3 * k
    # corner posts
    box("post", (0.008, 0.008, Z1 - Z0 + 0.004), (RP * math.cos(a), RP * math.sin(a), (Z0 + Z1) / 2), bevel=0.0015, segments=2, rot=(0, 0, a), mat="Metal")
    # pane between post k and k+1: on the apothem, width = side length
    am = a + math.pi / 6
    ap = RP * math.cos(math.pi / 6) - 0.002
    box("pane", (0.003, RP - 0.006, Z1 - Z0 - 0.004), (ap * math.cos(am), ap * math.sin(am), (Z0 + Z1) / 2), bevel=0, rot=(0, 0, am), mat="Glass")
    # thin horizontal rails holding the panes
    for z in (Z0 + 0.004, Z1 - 0.004):
        box("rail", (0.006, RP, 0.006), ((ap + 0.002) * math.cos(am), (ap + 0.002) * math.sin(am), z), bevel=0.001, segments=1, rot=(0, 0, am), mat="Metal")

# candle on a drip tray, with a flame
cyl("tray", 0.04, 0.006, (0, 0, Z0 + 0.003), bevel=0.0015, verts=32, mat="Metal")
lathe("candle", [(0.0, Z0 + 0.006), (0.024, Z0 + 0.006), (0.024, Z0 + 0.09), (0.021, Z0 + 0.094), (0.004, Z0 + 0.092), (0.0, Z0 + 0.088)], segs=32, mat="Wax")
cyl("wick", 0.0012, 0.01, (0, 0, Z0 + 0.095), bevel=0, verts=8, mat="Metal")
sphere("flame", 0.008, (0, 0, Z0 + 0.112), scale=(1, 1, 2.2), segs=16, rings=10, mat="Flame")

export("Lantern")
