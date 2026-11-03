# Builds an iron-bound plank chest with a barrel lid for Pigment.
#
#   blender -b --factory-startup --python assets/blender/treasure_chest.py -- assets/treasure_chest.glb
#
# Material test: separate wooden boards with real gaps between them (Oak /
# Pine / Varnished wood grain running along each board, dirt packed into the
# joints, wear on the board ends) bound by wrought iron (Rusty steel, Cast
# iron, Hammered steel: rust bleeding out from rivets and down from the
# bands, Leaks onto the wood below), with corner brackets, side handles and a
# lock plate. UVs are packed without rotation so board grain stays aligned.
# Two materials: Wood, Iron.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import band, box, cut, cutter, cyl, export, sphere, torus  # noqa: E402

W, D, H = 0.72, 0.46, 0.38  # body width (x), depth (y), height to the lid hinge line
T = 0.024  # board thickness
GAP = 0.003
R = D / 2  # lid radius

# --- body boards: three per wall, the bottom a single panel ---
bh = (H - 0.02) / 3
for k in range(3):
    z = 0.02 + bh * (k + 0.5)
    for sy in (-1, 1):
        box("board_fb", (W, T, bh - GAP), (0, sy * (D / 2 - T / 2), z), bevel=0.003, segments=2, mat="Wood")
    for sx in (-1, 1):
        box("board_side", (T, D - 2 * T - 0.001, bh - GAP), (sx * (W / 2 - T / 2), 0, z), bevel=0.003, segments=2, mat="Wood")
box("bottom", (W - 0.01, D - 0.01, 0.02), (0, 0, 0.01), bevel=0.002, segments=2, mat="Wood")

# --- barrel lid: staves round the hinge axis, half-disc ends ---
N = 9
for k in range(N):
    a = math.pi * (k + 0.5) / N  # 0 = front edge, pi = back edge
    y, z = -R * math.cos(a), H + R * math.sin(a)
    sw = math.pi * R / N - GAP
    box("stave", (W - 2 * T, sw, T), (0, y * (1 - T / (2 * R)), H + (z - H) * (1 - T / (2 * R))),
        rot=(math.pi / 2 - a, 0, 0), bevel=0.003, segments=2, mat="Wood")
for sx in (-1, 1):
    end = cyl("lid_end", R, T, (sx * (W / 2 - T / 2), 0, H), rot=(0, math.pi / 2, 0), bevel=0.003, verts=48, mat="Wood")
    cut(end, [cutter((T * 2, D * 1.2, R * 1.2), (sx * (W / 2 - T / 2), 0, H - R * 0.6))], lip_bevel=0.002)

# --- iron bands: up the front, over the lid, down the back ---
BT = 0.004


def strap_path(x, out=0.0):
    yf = -D / 2 - out
    pts = [(x, yf, 0.0), (x, yf, H)]
    for k in range(1, 24):
        a = math.pi * k / 24
        pts.append((x, -(R + out) * math.cos(a), H + (R + out) * math.sin(a)))
    pts += [(x, D / 2 + out, H), (x, D / 2 + out, 0.0)]
    return pts


for x in (-W / 2 + 0.11, W / 2 - 0.11):
    band("band", strap_path(x, BT / 2), 0.05, BT, mat="Iron")
    # rivets down the front and back of each band
    for z in (0.06, 0.18, 0.3):
        for sy in (-1, 1):
            sphere("rivet", 0.007, (x, sy * (D / 2 + BT), z), scale=(1, 0.6, 1), segs=12, rings=6, mat="Iron")
# a horizontal band round the body at mid height, under the vertical ones
band("waist", [(-W / 2 - 0.0015, -D / 2 - 0.0015, 0.19), (W / 2 + 0.0015, -D / 2 - 0.0015, 0.19), (W / 2 + 0.0015, D / 2 + 0.0015, 0.19),
               (-W / 2 - 0.0015, D / 2 + 0.0015, 0.19), (-W / 2 - 0.0015, -D / 2 + 0.01, 0.19)], 0.035, 0.003, side=(0, 0, 1), mat="Iron")

# corner brackets: L plates on the vertical corners
for sx in (-1, 1):
    for sy in (-1, 1):
        box("bracket", (0.07, 0.004, 0.07), (sx * (W / 2 - 0.035), sy * (D / 2 + 0.004), H - 0.04), bevel=0.0015, segments=1, mat="Iron")
        box("bracket", (0.004, 0.07, 0.07), (sx * (W / 2 + 0.004), sy * (D / 2 - 0.035), H - 0.04), bevel=0.0015, segments=1, mat="Iron")
        box("bracket", (0.07, 0.004, 0.07), (sx * (W / 2 - 0.035), sy * (D / 2 + 0.004), 0.04), bevel=0.0015, segments=1, mat="Iron")
        box("bracket", (0.004, 0.07, 0.07), (sx * (W / 2 + 0.004), sy * (D / 2 - 0.035), 0.04), bevel=0.0015, segments=1, mat="Iron")

# side handles: a mounting plate and a hanging ring
for sx in (-1, 1):
    box("handle_plate", (0.006, 0.1, 0.05), (sx * (W / 2 + 0.003), 0, H - 0.09), bevel=0.002, segments=2, mat="Iron")
    torus("handle_ring", 0.045, 0.006, (sx * (W / 2 + 0.012), 0, H - 0.13), rot=(0, math.pi / 2, 0), maj=32, mi=8, mat="Iron")

# lock plate with a keyhole, and the hasp hanging from the lid
lock = box("lock_plate", (0.09, 0.008, 0.1), (0, -D / 2 - 0.004, H - 0.06), bevel=0.002, segments=2, mat="Iron")
cut(lock, [cutter((0.008, 0.03, 0.025), (0, -D / 2 - 0.004, H - 0.07))], lip_bevel=0.001)
box("hasp", (0.035, 0.006, 0.09), (0, -D / 2 - 0.011, H - 0.01), bevel=0.002, segments=2, mat="Iron")

export("TreasureChest", rotate=False)
