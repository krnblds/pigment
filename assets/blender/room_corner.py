# Builds the corner of a room (floor, two walls, a window and a doorway) for Pigment.
#
#   blender -b --factory-startup --python assets/blender/room_corner.py -- assets/room_corner.glb
#
# Material test at architectural scale, with UDIM tiles: the floor on 1001
# (Planks layouts, Tiles, Checker marble, carpets: real metres over 3 x 3 m),
# the walls on 1002 (wallpapers, Painted plaster, Subway tiles, Peeling
# wallpaper: plus Leaks under the window sill, Moss / Dirt in the floor
# corner) and the joinery on 1003 (skirting, architraves, window frame and
# sill, cornice: painted Trim with Edge wear and scuffs at foot height).
# Open with udim=true for one texture set per tile.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import box, cut, cutter, export  # noqa: E402

S = 3.0  # room size
WH = 2.6  # wall height
WT = 0.12  # wall thickness
BX, LY = S / 2, S / 2  # back wall at y = +BX, left wall at x = -LY

# floor slab, top at z = 0
box("floor", (S, S, 0.06), (0, 0, -0.03), bevel=0.003, segments=1, mat="Floor")

# back wall with a window; left wall with a doorway
back = box("wall_back", (S + WT, WT, WH), (-WT / 2, BX + WT / 2, WH / 2), bevel=0.004, segments=1, mat="Wall")
WX, WW, WS, WHT = 0.35, 1.1, 0.9, 1.25  # window centre x, width, sill height, height
cut(back, [cutter((WW, WT * 3, WHT), (WX, BX + WT / 2, WS + WHT / 2))], lip_bevel=0.003)
left = box("wall_left", (WT, S, WH), (-LY - WT / 2, 0, WH / 2), bevel=0.004, segments=1, mat="Wall")
DY, DW, DH = -0.55, 0.9, 2.1  # door centre y, width, height
cut(left, [cutter((WT * 3, DW, DH), (-LY - WT / 2, DY, DH / 2 - 0.01))], lip_bevel=0.003)

# --- joinery ---
SK, ST = 0.12, 0.018  # skirting height, thickness
box("skirting", (S, ST, SK), (0, BX - ST / 2, SK / 2), bevel=0.003, segments=2, mat="Trim")
# left wall skirting stops at the door architrave
y0, y1 = -LY, DY - DW / 2 - 0.07
box("skirting", (ST, y1 - y0, SK), (-LY + ST / 2, (y0 + y1) / 2, SK / 2), bevel=0.003, segments=2, mat="Trim")
y0, y1 = DY + DW / 2 + 0.07, BX - ST
box("skirting", (ST, y1 - y0, SK), (-LY + ST / 2, (y0 + y1) / 2, SK / 2), bevel=0.003, segments=2, mat="Trim")

# door architrave (inside face) and lining
AW, AT = 0.07, 0.02
for s in (-1, 1):
    box("architrave", (AT, AW, DH + AW), (-LY + AT / 2, DY + s * (DW / 2 + AW / 2), (DH + AW) / 2), bevel=0.004, segments=2, mat="Trim")
    box("lining", (WT, 0.02, DH), (-LY - WT / 2, DY + s * (DW / 2 - 0.01), DH / 2), bevel=0.002, segments=1, mat="Trim")
box("architrave", (AT, DW + 2 * AW, AW), (-LY + AT / 2, DY, DH + AW / 2), bevel=0.004, segments=2, mat="Trim")
box("lining", (WT, DW, 0.02), (-LY - WT / 2, DY, DH - 0.01), bevel=0.002, segments=1, mat="Trim")

# window: frame in the reveal, a mullion and transom, sill and architrave
FW = 0.06
for s in (-1, 1):
    box("frame", (FW, WT * 0.6, WHT), (WX + s * (WW / 2 - FW / 2), BX + WT / 2, WS + WHT / 2), bevel=0.003, segments=2, mat="Trim")
for z in (WS + FW / 2, WS + WHT - FW / 2):
    box("frame", (WW, WT * 0.6, FW), (WX, BX + WT / 2, z), bevel=0.003, segments=2, mat="Trim")
box("mullion", (0.04, WT * 0.5, WHT), (WX, BX + WT / 2, WS + WHT / 2), bevel=0.003, segments=2, mat="Trim")
box("transom", (WW, WT * 0.5, 0.04), (WX, BX + WT / 2, WS + WHT * 0.68), bevel=0.003, segments=2, mat="Trim")
box("sill", (WW + 0.16, 0.2, 0.035), (WX, BX - 0.03, WS - 0.0175), bevel=0.005, segments=3, mat="Trim")
for s in (-1, 1):
    box("architrave", (AW, AT, WHT + AW), (WX + s * (WW / 2 + AW / 2), BX - AT / 2, WS + (WHT + AW) / 2 - 0.035), bevel=0.004, segments=2, mat="Trim")
box("architrave", (WW + 2 * AW, AT, AW), (WX, BX - AT / 2, WS + WHT + AW / 2), bevel=0.004, segments=2, mat="Trim")

# cornice along the top of both walls
box("cornice", (S, 0.07, 0.07), (0, BX - 0.035, WH - 0.035), bevel=0.025, segments=4, mat="Trim")
box("cornice", (0.07, S - 0.07, 0.07), (-LY + 0.035, -0.035, WH - 0.035), bevel=0.025, segments=4, mat="Trim")

export("RoomCorner", udim={"Floor": 1001, "Wall": 1002, "Trim": 1003}, rotate=False)
