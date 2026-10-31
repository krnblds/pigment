# Town kit: a 14 x 14 m crossroad matching street_segment (8 m road, 0.25 m
# curbs, sidewalks to the tile edge, same heights).
#
#   blender -b --factory-startup --python assets/blender/town/crossroad.py -- assets/town/crossroad.glb
#
# Plus-shaped asphalt slab, four corner sidewalks with rounded curbs (1.5 m
# radius at the road edge), a zebra crossing on each arm (every stripe is
# its own thin part), a manhole and four gutter drain grates. Each arm's road
# edge meets a street_segment end exactly.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

H = 7.0  # half tile
RW = 4.0
CB = 0.25
R = 1.5  # curb radius at the road edge
ROAD, WALK = 0.20, 0.35
G = 0.003
SEG = 12


def arc(r, t0, t1):
    c = (RW + R, RW + R)
    return [(c[0] + r * math.cos(math.radians(t0 + (t1 - t0) * k / SEG)), c[1] + r * math.sin(math.radians(t0 + (t1 - t0) * k / SEG))) for k in range(SEG + 1)]


def rot(pts, k):
    a = k * math.pi / 2
    ca, sa = round(math.cos(a)), round(math.sin(a))
    return [(x * ca - y * sa, x * sa + y * ca) for x, y in pts]


# road: plus shape with rounded inner corners
unit = [(H, -(RW - G)), (H, RW - G)] + arc(R + G, 270, 180)
road = []
for k in range(4):
    road += rot(unit, k)
prism("road", road, 0.0, ROAD, bevel=0.01, angle=40)

# corner curbs and sidewalks (quadrant +X+Y, rotated to the others)
curb = [(RW, H)] + arc(R, 180, 270) + [(H, RW), (H, RW + CB)] + arc(R - CB, 270, 180) + [(RW + CB, H)]
walk = [(RW + CB + G, H)] + arc(R - CB - G, 180, 270) + [(H, RW + CB + G), (H, H)]
for k in range(4):
    prism("curb", rot(curb, k), 0.0, WALK, bevel=0.03, segments=3, angle=40)
    prism("sidewalk", rot(walk, k), 0.0, WALK, bevel=0.01, angle=40)

# zebra crossings: stripes run with the traffic, one crossing per arm
for k in range(4):
    for j in range(7):
        x, y = rot([(5.55, -3.0 + j * 1.0)], k)[0]
        box("zebra", (2.3, 0.5, 0.007) if k % 2 == 0 else (0.5, 2.3, 0.007), (x, y, ROAD + 0.0025), bevel=0.0)

# drain grates in the gutters just before the crossings, and a manhole
for k in range(4):
    x, y = rot([(RW + R + 0.2, -(RW - 0.22))], k)[0]
    g = raw_box((0.9, 0.42, 0.04))
    g.name = "drain_grate"
    cut(g, [cutter((0.05, 0.3, 0.2), (-0.36 + i * 0.08, 0, 0)) for i in range(10)])
    g.location = (x, y, ROAD - 0.012)
    g.rotation_euler = (0, 0, k * math.pi / 2)
    finish(g, 0.004)
cyl("manhole", 0.36, 0.04, (0.8, -0.6, ROAD - 0.012), bevel=0.006, verts=32)

export("Crossroad", view=(-0.8, -1.1, 1.1), close=[("close", (5.0, 5.0, 0.3), 2.5, (-0.7, -1.2, 0.9))])
