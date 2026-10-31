# Town kit: building A, a narrow six-storey tenement (8 x 10 m, 21 m).
#
#   blender -b --factory-startup --python assets/blender/town/building_a.py -- assets/town/building_a.glb
#
# Ground-floor shop (half-rolled shutter, shopfront glass, door, awning),
# stair door with a canopy, five upper floors of recessed windows (frame,
# glass and sill are separate parts), three balconies with railings, wall AC
# units, a blank blade-sign box on the front corner (for a neon sign), a
# rooftop water tank on a stand, a stair hut and downpipes. Front faces -Y.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

W, D = 8.0, 10.0
GF = 4.2  # ground floor height
FH = 3.2  # upper floor height
ROOF = GF + 5 * FH  # 20.2, roof deck
TOP = 21.0  # parapet top
F = Facade(W, D)
fy = -D / 2

shell = raw_box((W, D, TOP), (0, 0, TOP / 2))
shell.name = "shell"
cuts = [cutter((W - 0.5, D - 0.5, 2.0), (0, 0, ROOF + 1.0))]  # roof deck inside a parapet

# --- ground floor: shop opening and stair door ---
SU, SW, SH, SR = -1.1, 5.0, 3.2, 0.6  # shop centre u, width, height, recess
cuts.append(cutter((SW, 2 * SR, SH + 0.5), F.pos("S", SU, 0, (SH - 0.5) / 2)))
DU, DW, DH = 2.6, 1.2, 2.4
cuts.append(cutter((DW, 0.6, DH + 0.5), F.pos("S", DU, 0, (DH - 0.5) / 2)))

# shopfront inside the recess: frame with window, door and transom openings
fw, fh = SW - 0.012, SH - 0.012
holed("shop_frame", (fw, 0.08, fh), [(-0.9, -0.2, 3.0, 1.8), (1.65, -0.6, 1.3, 2.8), (0.0, 1.2, 4.6, 0.5)],
      F.pos("S", SU, 0.5, SH / 2), bevel=0.01)
box("shop_glass", (3.06, 0.012, 1.86), F.pos("S", SU - 0.9, 0.57, SH / 2 - 0.2), bevel=0.002)
box("shop_transom_glass", (4.66, 0.012, 0.56), F.pos("S", SU, 0.57, SH / 2 + 1.2), bevel=0.002)
box("shop_door", (1.27, 0.05, 2.33), F.pos("S", SU + 1.65, 0.5, 0.01 + 2.33 / 2), bevel=0.008)
# roll-up shutter, two thirds down, in guide rails, with its housing outside
grooves = [(-0.55 + 0.1 * k, 0.018, 0.008) for k in range(12)]
grooved("shutter", (SW - 0.04, 0.04, 1.2), grooves, F.pos("S", SU, 0.3, SH - 0.61), bevel=0.006)
for s in (-1, 1):
    box("shutter_rail", (0.07, 0.1, SH - 0.02), F.pos("S", SU + s * (SW / 2 - 0.045), 0.3, SH / 2), bevel=0.008)
box("shutter_housing", (SW + 0.3, 0.4, 0.45), F.pos("S", SU, -0.198, SH + 0.25), bevel=0.03, segments=3)
# awning over the shop, tilted down to the street, hung on two tie rods
box("awning", (SW + 0.8, 1.6, 0.07), F.pos("S", SU, -0.84, 4.02), bevel=0.012, rot=(math.radians(15), 0, 0))
for s in (-1, 1):
    rod("awning_rod", F.pos("S", SU + s * 2.4, 0.03, 4.75), F.pos("S", SU + s * 2.4, -1.5, 3.86), 0.025)
# stair door with a small canopy and an intercom
box("stair_door", (DW - 0.02, 0.06, DH - 0.02), F.pos("S", DU, 0.25, 0.01 + (DH - 0.02) / 2), bevel=0.008)
box("stair_canopy", (1.7, 0.7, 0.08), F.pos("S", DU, -0.348, DH + 0.3), bevel=0.012)
box("intercom", (0.16, 0.06, 0.26), F.pos("S", DU + 0.82, -0.028, 1.4), bevel=0.008)

# string course over the ground floor and a cornice under the parapet
box("band", (W + 0.16, D + 0.16, 0.25), (0, 0, GF), bevel=0.02)
box("cornice", (W + 0.3, D + 0.3, 0.35), (0, 0, ROOF + 0.05), bevel=0.03, segments=3)
cap = raw_box((W + 0.1, D + 0.1, 0.12), (0, 0, 0))
cap.name = "coping"
cut(cap, [cutter((W - 0.6, D - 0.6, 1.0))])
cap.location = (0, 0, TOP + 0.05)
finish(cap, 0.015)

# --- upper floors ---
balconies = {(1, 0.0), (3, 0.0), (2, -2.6)}
acs = [("S", 0, 2.6), ("S", 2, 2.6), ("S", 4, -2.6), ("E", 1, -2.5), ("E", 3, 2.5), ("W", 2, 2.5)]
for i in range(5):
    fz = GF + i * FH
    for u in (-2.6, 0.0, 2.6):
        if (i, u) in balconies:
            # balcony door, slab and three railings
            window(F, cuts, "S", u, fz + 0.06, 1.2, 2.3, mullions=1, sill=False, name="balc_door")
            box("balc_slab", (2.4, 1.1, 0.16), F.pos("S", u, -0.548, fz - 0.03), bevel=0.02)
            n = 16
            holes = [(-1.18 + 0.04 + (k + 0.5) * (2.36 - 0.08) / n, 0.0, 0.075, 0.8) for k in range(n)]
            holed("balc_rail", (2.36, 0.04, 1.0), holes, F.pos("S", u, -1.08, fz + 0.055 + 0.5), bevel=0.008)
            for s in (-1, 1):
                holes = [(-0.5 + 0.04 + (k + 0.5) * 0.92 / 7, 0.0, 0.075, 0.8) for k in range(7)]
                holed("balc_rail_side", (1.0, 0.04, 1.0), holes, (u + s * 1.16, fy - 0.54, fz + 0.055 + 0.5), rotz=math.pi / 2, bevel=0.008)
        else:
            window(F, cuts, "S", u, fz + 0.9, 1.4, 1.7, mullions=1, name="win")
    for side in ("E", "W"):
        for u in (-2.5, 2.5):
            window(F, cuts, side, u, fz + 0.95, 1.0, 1.5, mullions=0, sill=False, name="side_win")
for side, i, u in acs:
    zb = GF + i * FH + (0.9 if side == "S" else 0.95)
    ac_unit(F, side, u, zb - 0.70, name="ac")

cut(shell, cuts)
finish(shell, 0.03, 2, angle=40)

# --- blade sign box on the front right corner (blank: neon goes on later) ---
sx, sy0 = W / 2 - 0.45, fy - 0.15
box("sign_box", (0.3, 1.2, 6.0), (sx, sy0 - 0.6, 10.0), bevel=0.03, segments=3)
for s in (-1, 1):
    box("sign_face", (0.012, 1.08, 5.88), (sx + s * 0.158, sy0 - 0.6, 10.0), bevel=0.002)
for z in (7.6, 10.0, 12.4):
    box("sign_bracket", (0.1, 0.18, 0.1), (sx, fy - 0.07, z), bevel=0.01)

# --- roof: water tank on a stand, stair hut, vent ---
tx, ty = -1.9, 2.4
for a in (-1, 1):
    for b in (-1, 1):
        box("tank_leg", (0.14, 0.14, 1.5), (tx + a * 0.95, ty + b * 0.95, ROOF + 0.73), bevel=0.01)
box("tank_deck", (2.5, 2.5, 0.16), (tx, ty, ROOF + 1.56), bevel=0.02)
lathe("tank", [(1.0, 0.0), (1.0, 1.75), (0.75, 2.02), (0.0, 2.18)], (tx, ty, ROOF + 1.66), segs=32, bevel=0.015)
for z in (0.45, 1.25):
    lathe("tank_hoop", [(1.035, z), (1.035, z + 0.08)], (tx, ty, ROOF + 1.66), segs=32, bevel=0.008)
cyl("tank_hatch", 0.22, 0.12, (tx + 0.25, ty, ROOF + 1.66 + 2.0), bevel=0.01, verts=20)
hx, hy = 2.1, 2.7
box("stair_hut", (2.4, 2.8, 2.5), (hx, hy, ROOF - 0.02 + 1.25), bevel=0.03)
box("stair_hut_roof", (2.65, 3.05, 0.14), (hx, hy, ROOF - 0.02 + 2.57), bevel=0.02)
box("hut_door", (0.9, 0.05, 2.0), (hx, hy - 1.4 - 0.02, ROOF + 1.0), bevel=0.008)
lathe("roof_vent", [(0.12, 0.0), (0.12, 0.7), (0.32, 0.72), (0.32, 0.8), (0.0, 0.95)], (-1.2, -2.6, ROOF - 0.02), segs=20, bevel=0.006)

# --- pipes on the back and side ---
cyl("downpipe", 0.07, ROOF + 0.2, (-3.55, D / 2 + 0.1, (ROOF + 0.2) / 2 + 0.05), verts=16)
cyl("pipe", 0.05, ROOF - 1.0, (0.9, D / 2 + 0.09, (ROOF - 1.0) / 2 + 0.5), verts=14)
cyl("pipe", 0.05, ROOF - 1.0, (1.12, D / 2 + 0.09, (ROOF - 1.0) / 2 + 0.5), verts=14)

export("BuildingA", centre_xy=False, close=[("close", (0, -5, 3.0), 4.0, (-0.6, -1.5, 0.35))])
