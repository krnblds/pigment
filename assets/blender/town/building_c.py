# Town kit: building C, a megablock tower (14 x 14 m, ~36 m to the crown, mast to ~42 m).
#
#   blender -b --factory-startup --python assets/blender/town/building_c.py -- assets/town/building_c.glb
#
# Glazed lobby with an entrance canopy (its LED edge is its own part), eight
# repeated floors of ribbon windows on all four sides (one mullioned frame
# per ribbon, glass split into three panes), a proud floor-slab band per
# floor, vertical corner channels each holding a thin light strip (to become
# LED strips), wall AC units, a set-back crown with corner strips and
# framed sign panels on all four crown faces, an antenna mast and a
# dish. A corporate fascia stands on the canopy and a sign box hangs left of
# the lobby. Front faces -Y.

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import *  # noqa: E402,F403

W = D = 14.0
GF, FH, NF = 5.0, 3.2, 8
ROOF = GF + NF * FH  # 30.6
TOP = ROOF + 0.8
CW = 10.0  # crown footprint
CTOP = TOP + 4.4  # 35.8
CDECK = CTOP - 0.6
GROUND_UV = 2.5  # ground-floor wall texel density vs the rest
F = Facade(W, D)
NOTCH = 0.5  # corner channel cutter (removes a 0.25 x 0.25 m notch)

shell = raw_box((W, D, TOP), (0, 0, TOP / 2))
shell.name = "shell"
cuts = [cutter((W - 0.8, D - 0.8, 2.0), (0, 0, ROOF + 1.0))]
for sx in (-1, 1):
    for sy in (-1, 1):
        h = TOP - GF + 1.0
        cuts.append(cutter((NOTCH, NOTCH, h), (sx * W / 2, sy * D / 2, GF + 0.25 + h / 2)))

# --- lobby: glazed entrance recess with canopy ---
LW, LH, LD = 6.4, 4.0, 1.5
cuts.append(cutter((LW, 2 * LD, LH + 0.5), F.pos("S", 0, 0, (LH - 0.5) / 2)))
holes = [(-2.25, 0.25, 1.7, 3.2), (2.25, 0.25, 1.7, 3.2), (0.0, -0.9, 2.4, 2.6), (0.0, 1.225, 2.4, 1.25)]
holed("lobby_frame", (LW - 0.012, 0.1, LH - 0.012), holes, F.pos("S", 0, LD - 0.15, LH / 2), bevel=0.01)
for u in (-2.25, 2.25):
    box("lobby_glass", (1.76, 0.012, 3.26), F.pos("S", u, LD - 0.06, LH / 2 + 0.25), bevel=0.002)
box("lobby_transom_glass", (2.46, 0.012, 1.31), F.pos("S", 0, LD - 0.06, LH / 2 + 1.225), bevel=0.002)
for s in (-1, 1):
    box("lobby_door", (1.17, 0.05, 2.36), F.pos("S", s * 0.6, LD - 0.15, 0.01 + 1.18), bevel=0.008)
box("canopy", (LW + 2.0, 2.2, 0.25), F.pos("S", 0, -1.098, LH + 0.4), bevel=0.02)
box("canopy_led", (LW + 1.9, 0.05, 0.06), F.pos("S", 0, -2.23, LH + 0.4), bevel=0.0)
# corporate fascia standing on the canopy's front edge (the lobby logo goes on it)
uv_boost(box("lobby_fascia", (LW, 0.2, 0.9), F.pos("S", 0, -2.0, LH + 0.535 + 0.45), bevel=0.02), 8, (0, -1, 0))
# a wall sign box left of the lobby (security / kiosk notice)
uv_boost(box("lobby_sign", (2.9, 0.15, 0.5), F.pos("S", -5.1, -0.078, 3.2), bevel=0.015), 15, (0, -1, 0))
for u in (-2.0, 2.0):
    box("canopy_light", (0.8, 0.8, 0.04), F.pos("S", u, -1.1, LH + 0.255), bevel=0.006)
# lobby side windows and a service door
for side in ("E", "W"):
    window(F, cuts, side, -2.5, 1.0, 3.5, 2.6, mullions=1, sill=False, name="lobby_side")
# enamel notice plate on the lobby recess's side wall beside the doors (eye height)
uv_boost(box("plate", (0.012, 0.46, 0.23), (LW / 2 - 0.007, -(D / 2) + 0.65, 1.62), bevel=0.002), 26, (-1, 0, 0))
box("service_door", (1.2, 0.08, 2.3), F.pos("N", 3.0, -0.03, 1.16), bevel=0.01, rot=(0, 0, math.pi))

# --- repeated floors: ribbon windows on every side ---
for i in range(NF):
    fz = GF + i * FH
    for side in "SENW":
        window(F, cuts, side, 0.0, fz + 0.85, 12.0, 1.5, mullions=5, panes=3, sill=False, name="ribbon")
for side, i, u in [("S", 1, -4.0), ("S", 4, 3.0), ("S", 6, -1.5), ("E", 2, 1.0), ("W", 5, -3.0)]:
    ac_unit(F, side, u, GF + i * FH + 0.85 - 0.75, name="ac")

# split at the string course: the ground floor gets denser UVs for street-level decals
ground, shell = cut_split(shell, cuts, GF)
uv_boost(finish(ground, 0.03, 2, angle=40), GROUND_UV)
finish(shell, 0.03, 2, angle=40)

# proud floor-slab bands, notched at the corners so the light channels run through
corner_cuts = lambda: [cutter((NOTCH + 0.3, NOTCH + 0.3, 2.0), (sx * W / 2, sy * D / 2, 0)) for sx in (-1, 1) for sy in (-1, 1)]
for i in range(NF + 1):
    z = GF + i * FH if i < NF else ROOF + 0.05
    o = raw_box((W + 0.24, D + 0.24, 0.28 if i < NF else 0.34))
    o.name = "slab_band"
    cut(o, corner_cuts())
    o.location = (0, 0, z)
    finish(o, 0.02)
cap = raw_box((W + 0.1, D + 0.1, 0.12))
cap.name = "coping"
cut(cap, [cutter((W - 1.0, D - 1.0, 1.0))] + corner_cuts())
cap.location = (0, 0, TOP + 0.05)
finish(cap, 0.015)

# light strips in the corner channels (separate thin parts)
for sx in (-1, 1):
    for sy in (-1, 1):
        box("light_strip", (0.1, 0.1, TOP - GF - 0.3), (sx * (W / 2 - 0.15), sy * (D / 2 - 0.15), GF + 0.15 + (TOP - GF - 0.3) / 2 + 0.05), bevel=0.01)

# --- crown: set-back block with its own ribbon, corner channels and strips ---
CF = Facade(CW, CW)
crown = raw_box((CW, CW, CTOP - ROOF + 0.02), (0, 0, (CTOP + ROOF - 0.02) / 2))
crown.name = "crown"
ccuts = [cutter((CW - 0.6, CW - 0.6, 2.0), (0, 0, CDECK + 1.0))]
for sx in (-1, 1):
    for sy in (-1, 1):
        ccuts.append(cutter((NOTCH, NOTCH, 4.0), (sx * CW / 2, sy * CW / 2, TOP + 0.4 + 2.0)))
cut(crown, ccuts)
finish(crown, 0.03, 2, angle=40)
# crown sign panels: an 8 x 3.6 m framed panel on each face, on brackets 0.3 m off the wall
CPW, CPH, CPZ = 8.0, 3.6, TOP + 0.35   # panel size, bottom
for side in "SENW":
    r = CF.rot(side)
    uv_boost(box("crown_panel", (CPW, 0.08, CPH), CF.pos(side, 0, -0.3, CPZ + CPH / 2), bevel=0.004, rot=(0, 0, r)), 2,
             Matrix.Rotation(r, 3, "Z") @ Vector((0, -1, 0)))
    holed("crown_frame", (CPW + 0.4, 0.2, CPH + 0.4), [(0, 0, CPW - 0.04, CPH - 0.04)], CF.pos(side, 0, -0.27, CPZ + CPH / 2), r, bevel=0.02)
    for u in (-3.0, 0.0, 3.0):
        for z in (CPZ + 0.5, CPZ + CPH - 0.5):
            box("crown_bracket", (0.12, 0.15, 0.12), CF.pos(side, u, -0.085, z), bevel=0.01, rot=(0, 0, r))
for sx in (-1, 1):
    for sy in (-1, 1):
        box("crown_strip", (0.1, 0.1, 3.7), (sx * (CW / 2 - 0.15), sy * (CW / 2 - 0.15), TOP + 0.55 + 1.85), bevel=0.01)
cc = raw_box((CW + 0.1, CW + 0.1, 0.12))
cc.name = "crown_coping"
cut(cc, [cutter((CW - 0.8, CW - 0.8, 1.0))])
cc.location = (0, 0, CTOP + 0.05)
finish(cc, 0.015)

# --- roofs: mast, dish, terrace vents ---
mx, my = 2.2, 2.2
lathe("mast", [(0.32, 0.0), (0.32, 0.25), (0.2, 0.3), (0.09, 5.6), (0.04, 6.4), (0.0, 6.5)], (mx, my, CDECK - 0.02), segs=16, bevel=0.0)
for z, L in ((2.6, 2.0), (4.0, 1.4)):
    rod("mast_arm", (mx - L / 2, my, CDECK + z), (mx + L / 2, my, CDECK + z), 0.035, verts=8)
    for s in (-1, 1):
        rod("mast_whip", (mx + s * L / 2, my, CDECK + z - 0.6), (mx + s * L / 2, my, CDECK + z + 0.6), 0.02, verts=6)
lathe("beacon", [(0.0, 0.0), (0.09, 0.02), (0.09, 0.14), (0.0, 0.2)], (mx, my, CDECK + 6.5), segs=12)
lathe("dish", [(0.0, 0.0), (0.25, 0.02), (0.55, 0.1), (0.8, 0.25), (0.8, 0.3), (0.0, 0.08)], (-2.0, -1.5, CDECK + 1.0), segs=28,
      rot=(math.radians(-50), 0, 0))
box("dish_post", (0.15, 0.15, 1.0), (-2.0, -1.5, CDECK + 0.48), bevel=0.01)
for x, y in ((-5.6, -5.6), (5.6, -5.6), (-5.6, 5.6), (0.0, 5.7)):
    lathe("vent", [(0.14, 0.0), (0.14, 0.7), (0.34, 0.72), (0.34, 0.8), (0.0, 0.95)], (x, y, ROOF - 0.02), segs=18, bevel=0.006)
box("hvac", (2.2, 1.0, 1.0), (5.6, 0.0, ROOF - 0.02 + 0.5), bevel=0.03, rot=(0, 0, math.pi / 2))

export("BuildingC", centre_xy=False, view=(-1.0, -1.45, 0.55),
       close=[("close", (0, -7.0, 3.5), 5.5, (-0.6, -1.5, 0.3)), ("crown", (0, 0, CTOP), 9.0, (-1.0, -1.4, 0.7))])
