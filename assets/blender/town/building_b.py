# Town kit: building B, a wide four-storey block (16 x 12 m, 15 m) with a rooftop billboard.
#
#   blender -b --factory-startup --python assets/blender/town/building_b.py -- assets/town/building_b.glb
#
# Ground floor is a four-bay arcade: a ramen shop (shopfront, door, noren
# flaps, paper lanterns, fascia sign box), an arcade-game shop, a shuttered
# unit and a stair entrance. Three upper floors of horizontal window bands
# (one mullioned frame per band, glass split into separate panes). On the roof
# an 8 x 4 m billboard (frame and panel are separate parts) on posts with a
# catwalk and flood lamps, HVAC units, mushroom vents and a stair hut.
# Front faces -Y.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

W, D = 16.0, 12.0
GF, FH = 4.5, 3.2
ROOF = GF + 3 * FH  # 14.1
TOP = 15.0
F = Facade(W, D)

shell = raw_box((W, D, TOP), (0, 0, TOP / 2))
shell.name = "shell"
cuts = [cutter((W - 0.5, D - 0.5, 2.0), (0, 0, ROOF + 1.0))]

# --- arcade: four bays between square columns ---
BW, BH, BD = 3.4, 3.6, 2.0
bays = [-5.85, -1.95, 1.95, 5.85]
for u in bays:
    cuts.append(cutter((BW, 2 * BD, BH + 0.5), F.pos("S", u, 0, (BH - 0.5) / 2)))


def shopfront(u, name, door_right=True):
    """Frame (window, door, transom openings), two glass parts and a door at the back of a bay."""
    s = 1 if door_right else -1
    fz = BH / 2
    holes = [(-s * 0.65, 0.0, 1.7, 1.6), (s * 0.95, -0.6, 1.0, 2.8), (0.0, 1.25, 3.0, 0.5)]
    holed(f"{name}_frame", (BW - 0.012, 0.08, BH - 0.012), holes, F.pos("S", u, BD - 0.1, fz), bevel=0.01)
    box(f"{name}_glass", (1.76, 0.012, 1.66), F.pos("S", u - s * 0.65, BD - 0.03, fz), bevel=0.002)
    box(f"{name}_transom_glass", (3.06, 0.012, 0.56), F.pos("S", u, BD - 0.03, fz + 1.25), bevel=0.002)
    box(f"{name}_door", (0.98, 0.05, 2.58), F.pos("S", u + s * 0.95, BD - 0.1, 0.01 + 1.29), bevel=0.008)
    box(f"{name}_sign", (BW - 0.2, 0.25, 0.62), F.pos("S", u, -0.123, 4.05), bevel=0.02)


# ramen shop: noren flaps on a rod over the door, two paper lanterns at the bay mouth
shopfront(bays[0], "ramen")
du = bays[0] + 0.95
rod("noren_rod", F.pos("S", du - 0.55, BD - 0.18, 2.55), F.pos("S", du + 0.55, BD - 0.18, 2.55), 0.015)
for k in range(3):
    box("noren", (0.33, 0.01, 0.6), F.pos("S", du - 0.35 + k * 0.35, BD - 0.2, 2.24), bevel=0.0)
for s in (-1, 1):
    lu = bays[0] + s * 1.2
    lathe("lantern", [(0.07, 0.0), (0.2, 0.07), (0.25, 0.3), (0.2, 0.53), (0.07, 0.6)], F.pos("S", lu, 0.35, 2.85), segs=20)
    rod("lantern_cord", F.pos("S", lu, 0.35, 3.44), F.pos("S", lu, 0.35, BH + 0.03), 0.008, verts=8)
# arcade-game shop
shopfront(bays[1], "arcade", door_right=False)
# shuttered unit: full-height roll-up shutter with its housing
grooves = [(-BH / 2 + 0.15 + 0.11 * k, 0.02, 0.008) for k in range(31)]
grooved("shutter", (BW - 0.04, 0.05, BH - 0.02), grooves, F.pos("S", bays[2], BD - 0.3, BH / 2), bevel=0.006)
box("shutter_housing", (BW - 0.02, 0.3, 0.3), F.pos("S", bays[2], BD - 0.17, BH - 0.17), bevel=0.02)
# stair entrance: door, mailboxes, intercom
box("stair_door", (1.2, 0.06, 2.4), F.pos("S", bays[3] - 0.6, BD - 0.03, 1.21), bevel=0.008)
box("mailboxes", (1.0, 0.25, 0.7), F.pos("S", bays[3] + 0.9, BD - 0.128, 1.45), bevel=0.012)
box("intercom", (0.16, 0.06, 0.26), F.pos("S", bays[3] + 0.25, BD - 0.03, 1.4), bevel=0.008)
# arcade soffit light boxes
for u in bays:
    box("soffit_light", (1.6, 0.25, 0.08), F.pos("S", u, 1.0, BH - 0.038), bevel=0.01)

# --- upper floors: horizontal window bands ---
for i in range(3):
    fz = GF + i * FH
    window(F, cuts, "S", 0.0, fz + 0.9, 14.4, 1.6, mullions=5, panes=6, name="band")
    window(F, cuts, "N", 0.0, fz + 0.9, 13.0, 1.4, mullions=3, panes=3, sill=False, name="band_back")
    for side in ("E", "W"):
        window(F, cuts, side, 0.0, fz + 0.9, 10.0, 1.6, mullions=3, panes=4, name="band_side")
for side, i, u in [("S", 0, -4.0), ("S", 1, 3.5), ("S", 2, -1.0), ("S", 2, 5.5), ("E", 1, 2.0), ("W", 0, -3.0)]:
    ac_unit(F, side, u, GF + i * FH + 0.9 - 0.75, name="ac")

cut(shell, cuts)
finish(shell, 0.03, 2, angle=40)

box("band_ground", (W + 0.16, D + 0.16, 0.22), (0, 0, GF), bevel=0.02)
box("cornice", (W + 0.3, D + 0.3, 0.3), (0, 0, ROOF + 0.05), bevel=0.03, segments=3)
cap = raw_box((W + 0.1, D + 0.1, 0.12))
cap.name = "coping"
cut(cap, [cutter((W - 0.6, D - 0.6, 1.0))])
cap.location = (0, 0, TOP + 0.05)
finish(cap, 0.015)

# --- roof billboard: 8 x 4 m panel in a separate frame, on posts, facing -Y ---
bx, by, bz0 = 2.2, -3.6, ROOF + 2.3  # centre x, panel plane y, bottom of the panel
PW, PH = 8.0, 4.0
box("billboard_panel", (PW, 0.08, PH), (bx, by, bz0 + PH / 2), bevel=0.004)
holed("billboard_frame", (PW + 0.44, 0.26, PH + 0.44), [(0, 0, PW - 0.04, PH - 0.04)], (bx, by + 0.04, bz0 + PH / 2), bevel=0.02)
for k in (-1, 0, 1):
    px = bx + k * 3.2
    box("billboard_post", (0.22, 0.22, bz0 + PH + 0.1 - ROOF), (px, by + 0.27, (bz0 + PH + 0.1 + ROOF) / 2 - 0.02), bevel=0.012)
    rod("billboard_brace", (px, by + 2.6, ROOF + 0.02), (px, by + 0.36, bz0 + 1.6), 0.06, verts=10)
for z in (bz0 + 0.6, bz0 + PH - 0.6):
    box("billboard_beam", (PW + 0.2, 0.16, 0.16), (bx, by + 0.45, z), bevel=0.01)
# catwalk with a railing and flood lamps on short arms
box("catwalk", (PW + 0.4, 0.9, 0.08), (bx, by - 0.55, bz0 - 0.35), bevel=0.01)
n = 30
holes = [(-(PW + 0.4) / 2 + 0.05 + (k + 0.5) * (PW + 0.3) / n, -0.05, 0.2, 0.7) for k in range(n)]
holed("catwalk_rail", (PW + 0.4, 0.04, 0.9), holes, (bx, by - 1.0, bz0 - 0.31 + 0.45), bevel=0.008)
for k in (-1, 0, 1):
    lx = bx + k * 2.8
    rod("lamp_arm", (lx, by - 0.98, bz0 + 0.1), (lx, by - 1.6, bz0 + 0.55), 0.03, verts=10)
    box("lamp_head", (0.5, 0.22, 0.16), (lx, by - 1.72, bz0 + 0.62), bevel=0.015, rot=(math.radians(-35), 0, 0))
for s in (-1, 1):
    box("catwalk_hanger", (0.1, 0.1, 0.5), (bx + s * (PW / 2 - 0.4), by - 0.15, bz0 - 0.1), bevel=0.01)

# --- roof plant: HVAC units with fan discs, mushroom vents, duct, stair hut ---
for hx, hy in ((-4.8, 2.6), (-1.8, 3.4)):
    box("hvac", (2.0, 1.4, 1.1), (hx, hy, ROOF - 0.02 + 0.55), bevel=0.03)
    for s in (-1, 1):
        lathe("hvac_fan", [(0.42, 0.0), (0.42, 0.06), (0.3, 0.1), (0.0, 0.12)], (hx + s * 0.48, hy, ROOF + 1.1), segs=24, bevel=0.004)
for vx, vy in ((4.5, 3.8), (6.2, 1.5), (-6.4, -1.5)):
    lathe("vent", [(0.14, 0.0), (0.14, 0.8), (0.36, 0.82), (0.36, 0.9), (0.0, 1.06)], (vx, vy, ROOF - 0.02), segs=20, bevel=0.006)
rod("duct", (-4.8, 3.3, ROOF + 0.6), (-4.8, 5.3, ROOF + 0.6), 0.2, verts=16)
box("stair_hut", (2.6, 3.0, 2.6), (5.8, 3.8, ROOF - 0.02 + 1.3), bevel=0.03)
box("stair_hut_roof", (2.85, 3.25, 0.14), (5.8, 3.8, ROOF - 0.02 + 2.67), bevel=0.02)
box("hut_door", (0.9, 0.05, 2.0), (5.8, 3.8 - 1.5 - 0.02, ROOF + 1.0), bevel=0.008)

# downpipes on the back corners
for x in (-7.6, 7.6):
    cyl("downpipe", 0.07, ROOF + 0.2, (x, D / 2 + 0.1, (ROOF + 0.2) / 2 + 0.05), verts=16)

export("BuildingB", centre_xy=False, close=[("close", (-3.9, -6.0, 2.4), 4.2, (-0.5, -1.5, 0.3)), ("roof", (2.2, -3.0, ROOF + 3.0), 6.0, (1.0, 1.2, 0.5))])
