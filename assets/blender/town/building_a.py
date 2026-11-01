# Town kit: building A, a narrow six-storey tenement (8 x 10 m, 21 m).
#
#   blender -b --factory-startup --python assets/blender/town/building_a.py -- assets/town/building_a.glb
#
# Ground-floor shop (half-rolled shutter, shopfront glass, door, a fascia
# lightbox that houses the shutter roll),
# stair door with a canopy, five upper floors of recessed windows (frame,
# glass and sill are separate parts), three balconies with railings, wall AC
# units, a blank blade-sign box on the front corner (for a neon sign), a
# rooftop water tank on a stand, a stair hut and downpipes, a rooftop
# billboard (framed panel on posts, catwalk, flood lamps) and a wall-mounted
# billboard on the blank back wall (frame on brackets, gooseneck lamps).
# Front faces -Y.

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
GROUND_UV = 2.5  # ground-floor wall texel density vs the rest
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
# the shutter housing doubles as the shop's fascia: a lightbox sign the full
# width of the shopfront (the shop sign decal goes on its front face)
uv_boost(box("shop_sign", (SW + 0.3, 0.4, 0.8), F.pos("S", SU, -0.198, SH + 0.44), bevel=0.02, segments=2), 7, (0, -1, 0))
# stair door with a small canopy and an intercom
box("stair_door", (DW - 0.02, 0.06, DH - 0.02), F.pos("S", DU, 0.25, 0.01 + (DH - 0.02) / 2), bevel=0.008)
box("stair_canopy", (1.7, 0.7, 0.08), F.pos("S", DU, -0.348, DH + 0.3), bevel=0.012)
box("intercom", (0.16, 0.06, 0.26), F.pos("S", DU + 0.82, -0.028, 1.4), bevel=0.008)
# enamel notice plate on the pier between the shop and the stair door (eye height)
uv_boost(box("plate", (0.46, 0.012, 0.23), F.pos("S", 1.7, -0.007, 1.62), bevel=0.002), 24, (0, -1, 0))

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

# split at the string course: the ground floor gets denser UVs for street-level decals
ground, shell = cut_split(shell, cuts, GF)
uv_boost(finish(ground, 0.03, 2, angle=40), GROUND_UV)
finish(shell, 0.03, 2, angle=40)

# --- blade sign box on the front right corner (blank: neon goes on later) ---
sx, sy0 = W / 2 - 0.45, fy - 0.15
box("sign_box", (0.3, 1.2, 6.0), (sx, sy0 - 0.6, 10.0), bevel=0.03, segments=3)
for s in (-1, 1):
    uv_boost(box("sign_face", (0.012, 1.08, 5.88), (sx + s * 0.158, sy0 - 0.6, 10.0), bevel=0.002), 4.6, (s, 0, 0))
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

# --- rooftop billboard over the front: 6.4 x 3.2 m panel in its own frame, on posts ---
bx, by, bz0 = 0.0, -3.4, ROOF + 2.3  # centre x, panel plane y, bottom of the panel
PW, PH = 6.4, 3.2
uv_boost(box("billboard_panel", (PW, 0.08, PH), (bx, by, bz0 + PH / 2), bevel=0.004), 2, (0, -1, 0))
holed("billboard_frame", (PW + 0.44, 0.26, PH + 0.44), [(0, 0, PW - 0.04, PH - 0.04)], (bx, by + 0.04, bz0 + PH / 2), bevel=0.02)
for k in (-1, 0, 1):
    px = bx + k * 2.6
    box("billboard_post", (0.2, 0.2, bz0 + PH + 0.1 - ROOF), (px, by + 0.26, (bz0 + PH + 0.1 + ROOF) / 2 - 0.02), bevel=0.012)
    rod("billboard_brace", (px, by + 2.5, ROOF + 0.02), (px, by + 0.34, bz0 + 1.4), 0.055, verts=10)
for z in (bz0 + 0.5, bz0 + PH - 0.5):
    box("billboard_beam", (PW + 0.2, 0.14, 0.14), (bx, by + 0.43, z), bevel=0.01)
box("catwalk", (PW + 0.4, 0.8, 0.08), (bx, by - 0.5, bz0 - 0.32), bevel=0.01)
n = 24
holes = [(-(PW + 0.4) / 2 + 0.05 + (k + 0.5) * (PW + 0.3) / n, -0.05, 0.2, 0.7) for k in range(n)]
holed("catwalk_rail", (PW + 0.4, 0.04, 0.9), holes, (bx, by - 0.9, bz0 - 0.28 + 0.45), bevel=0.008)
for k in (-1, 1):
    lx = bx + k * 1.9
    rod("lamp_arm", (lx, by - 0.88, bz0 + 0.1), (lx, by - 1.4, bz0 + 0.5), 0.03, verts=10)
    box("lamp_head", (0.45, 0.2, 0.15), (lx, by - 1.5, bz0 + 0.56), bevel=0.015, rot=(math.radians(-35), 0, 0))
for s_ in (-1, 1):
    box("catwalk_hanger", (0.1, 0.1, 0.45), (bx + s_ * (PW / 2 - 0.4), by - 0.15, bz0 - 0.08), bevel=0.01)

# --- wall-mounted billboard on the blank back wall: frame on four brackets, two gooseneck lamps ---
wx, wz0, WPW, WPH = 0.4, 9.0, 6.4, 3.2      # centre x, bottom, panel size
wy = D / 2 + 0.42                            # panel plane, clear of the pipes on the wall
uv_boost(box("wall_billboard_panel", (WPW, 0.08, WPH), (wx, wy, wz0 + WPH / 2), bevel=0.004), 2, (0, 1, 0))
holed("wall_billboard_frame", (WPW + 0.4, 0.24, WPH + 0.4), [(0, 0, WPW - 0.04, WPH - 0.04)], (wx, wy - 0.03, wz0 + WPH / 2), bevel=0.02)
for bxk in (-2.3, 2.3):
    for bzk in (wz0 + 0.5, wz0 + WPH - 0.5):
        box("wall_billboard_bracket", (0.12, wy - 0.15 - D / 2 - 0.01, 0.12), (wx + bxk, (D / 2 + wy - 0.15) / 2 + 0.005, bzk), bevel=0.01)
for k in (-1, 1):
    lx = wx + k * 1.8
    rod("wall_lamp_arm", (lx, wy - 0.15, wz0 + WPH + 0.22), (lx, wy + 0.75, wz0 + WPH + 0.65), 0.025, verts=10)
    box("wall_lamp_head", (0.4, 0.18, 0.13), (lx, wy + 0.85, wz0 + WPH + 0.6), bevel=0.012, rot=(math.radians(35), 0, 0))

export("BuildingA", centre_xy=False, close=[("close", (0, -5, 3.0), 4.0, (-0.6, -1.5, 0.35)), ("back", (0.4, 5.5, 10.6), 5.0, (0.7, 1.4, 0.3))])
