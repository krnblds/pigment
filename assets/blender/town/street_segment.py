# Town kit: a straight street segment, 20 m long (X) and 14 m wide (Y).
#
#   blender -b --factory-startup --python assets/blender/town/street_segment.py -- assets/town/street_segment.glb
#
# 8 m asphalt road (slab top at z = 0.20), a 0.25 m curb each side rising
# 0.15 m above the road, 2.75 m sidewalk slabs behind them (curb + sidewalk =
# 3 m), two manhole covers on the road, a square utility cover on a sidewalk
# and two storm drains (gutter grate + an inlet slot in the curb face). Road,
# curbs, sidewalks and every cover/grate are separate parts; neighbouring
# pieces keep a 3 mm gap so they never share vertices. Tiles along X.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

L = 20.0
RW = 4.0  # half road width
CB = 0.25  # curb width
ROAD = 0.20  # road top
WALK = ROAD + 0.15  # curb / sidewalk top
G = 0.003

box("road", (L, 2 * (RW - G), ROAD), (0, 0, ROAD / 2), bevel=0.01, angle=40)
drains = [(2.5, 1), (-6.5, -1)]
for s in (-1, 1):
    c = raw_box((L, CB, WALK), (0, s * (RW + CB / 2), WALK / 2))
    c.name = "curb"
    # inlet slots in the curb face above each storm drain
    cut(c, [cutter((0.9, 0.12, 0.07), (x, s * RW, ROAD + 0.065)) for x, ds in drains if ds == s])
    finish(c, 0.03, 3, angle=40)
    box("sidewalk", (L, 3.0 - CB - G, WALK), (0, s * (RW + CB + G + (3.0 - CB - G) / 2), WALK / 2), bevel=0.01, angle=40)

# manhole covers sit a few millimetres proud of the asphalt
for x, y in ((-4.5, -1.6), (6.0, 1.9)):
    cyl("manhole", 0.36, 0.04, (x, y, ROAD - 0.012), bevel=0.006, verts=32)
box("utility_cover", (0.6, 0.6, 0.04), (3.5, -5.6, WALK - 0.012), bevel=0.006)

# storm drain grates in the gutter, slotted
for x, s in drains:
    g = raw_box((0.9, 0.42, 0.04))
    g.name = "drain_grate"
    cut(g, [cutter((0.05, 0.3, 0.2), (-0.36 + k * 0.08, 0, 0)) for k in range(10)])
    g.location = (x, s * (RW - 0.22), ROAD - 0.012)
    finish(g, 0.004)

export("StreetSegment", view=(-0.8, -1.1, 1.0), close=[("close", (2.5, 3.5, 0.3), 1.6, (-0.6, -1.4, 0.8))])
