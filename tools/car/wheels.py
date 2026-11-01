"""Wheel: tyre with tread blocks and sidewall detail, six-spoke alloy rim with lug
nuts and centre cap, vented brake disc on its hat, and a two-piston caliper.

Built at the origin (the hub centre), rotation axis X, the face of the rim
towards +X (a left-side wheel). Right-side wheels are mirrored copies.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import body as B
from carlib import apply_mods, bm_box, bm_cyl, bm_obj

TAU = 2 * math.pi
R_TYRE = B.WHEEL_R          # 0.325
W_TYRE = 0.215
R_RIM = 0.203               # 16" bead seat
R_LIP = 0.212


def revolve(bm, profile, seg, phase=0.0, radial_fn=None):
    """Revolve [(r, x)] around X. radial_fn(i_prof, k_seg) -> extra radius."""
    rings = []
    for i, (r, x) in enumerate(profile):
        ring = []
        for k in range(seg):
            a = TAU * k / seg + phase
            rr = r + (radial_fn(i, k) if radial_fn else 0.0)
            ring.append(bm.verts.new((x, rr * math.cos(a), rr * math.sin(a))))
        rings.append(ring)
    for A, Bq in zip(rings, rings[1:]):
        for k in range(seg):
            bm.faces.new((A[k], A[(k + 1) % seg], Bq[(k + 1) % seg], Bq[k]))
    return rings


def tyre():
    """Profile from the inner bead over the tread to the outer bead; tread blocks
    are radial offsets on the tread rings (alternating shoulder lugs + 2 grooves)."""
    hw = W_TYRE / 2
    prof = [
        (R_RIM + 0.004, -hw + 0.018),   # inner bead
        (R_RIM + 0.030, -hw + 0.004),
        (R_RIM + 0.070, -hw - 0.004),   # sidewall bulge
        (R_TYRE - 0.040, -hw - 0.002),
        (R_TYRE - 0.016, -hw + 0.004),  # shoulder
        (R_TYRE - 0.004, -hw + 0.018),
        (R_TYRE, -hw + 0.034),          # tread starts
        (R_TYRE, -0.052),
        (R_TYRE - 0.007, -0.048),       # groove 1
        (R_TYRE - 0.007, -0.036),
        (R_TYRE, -0.032),
        (R_TYRE, 0.032),
        (R_TYRE - 0.007, 0.036),        # groove 2
        (R_TYRE - 0.007, 0.048),
        (R_TYRE, 0.052),
        (R_TYRE, hw - 0.034),
        (R_TYRE - 0.004, hw - 0.018),
        (R_TYRE - 0.016, hw - 0.004),
        (R_TYRE - 0.040, hw + 0.002),
        (R_TYRE - 0.052, hw + 0.004),   # sidewall lettering band (raised)
        (R_TYRE - 0.056, hw + 0.006),
        (R_TYRE - 0.078, hw + 0.006),
        (R_TYRE - 0.082, hw + 0.004),
        (R_RIM + 0.070, hw + 0.004),
        (R_RIM + 0.030, hw - 0.004),    # rim protector
        (R_RIM + 0.004, hw - 0.018),
    ]
    seg = 96
    lug = {6, 7, 14, 15}            # outer tread ribs get the lateral lugs
    centre = {10, 11}

    def radial(i, k):
        # lateral grooves: every 3rd segment pair is cut 5 mm deep on the shoulder ribs,
        # offset by half a pitch on the centre rib (directional-ish pattern)
        if i in lug:
            return -0.005 if (k % 4) == 0 else 0.0
        if i in centre:
            return -0.004 if (k % 4) == 2 else 0.0
        return 0.0
    bm = bmesh.new()
    rings = revolve(bm, prof, seg, radial_fn=radial)
    # close the inside (a disc between the beads would never be seen; leave it open but cap
    # with a cylinder so the tyre is a closed, connected part)
    A, Bq = rings[0], rings[-1]
    for k in range(seg):
        bm.faces.new((Bq[k], Bq[(k + 1) % seg], A[(k + 1) % seg], A[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = bm_obj("tyre", bm)
    return ob


def rim():
    """Barrel (revolved) + face: hub disc, six spokes, outer lip; lug nuts and a centre cap."""
    hw = W_TYRE / 2
    bm = bmesh.new()
    # barrel: from the inner flange to the outer lip, then the lip face inward
    prof = [
        (R_RIM - 0.008, -hw + 0.010), (R_LIP, -hw + 0.012), (R_LIP, -hw + 0.022), (R_RIM - 0.002, -hw + 0.026),
        (R_RIM - 0.014, -0.02), (R_RIM - 0.014, 0.03), (R_RIM - 0.002, hw - 0.030),
        (R_LIP + 0.002, hw - 0.014), (R_LIP + 0.002, hw - 0.004), (R_LIP - 0.010, hw), (R_RIM - 0.020, hw - 0.006),
        (R_RIM - 0.024, hw - 0.020), (R_RIM - 0.020, -hw + 0.030), (R_RIM - 0.012, -hw + 0.012),
    ]
    rings = revolve(bm, prof, 72)
    A, Bq = rings[0], rings[-1]
    for k in range(72):
        bm.faces.new((Bq[k], Bq[(k + 1) % 72], A[(k + 1) % 72], A[k]))
    barrel = bm_obj("rim_barrel", bm)

    # face: hub disc
    bm = bmesh.new()
    xf = hw - 0.040    # the spoke face sits 4 cm in from the outer edge (some dish)
    hub_prof = [(0.0, xf + 0.012), (0.060, xf + 0.012), (0.075, xf + 0.004), (0.085, xf - 0.010), (0.080, xf - 0.040), (0.0, xf - 0.040)]
    revolve(bm, hub_prof, 36)
    hub = bm_obj("rim_hub", bm)
    # spokes: tapered, slightly concave boxes from the hub to the barrel
    bm = bmesh.new()
    for i in range(6):
        a = TAU * i / 6
        r0, r1 = 0.070, R_RIM - 0.016
        w0, w1 = 0.040, 0.026
        verts = []
        for (r, w, dx_front, dx_back) in ((r0, w0, 0.008, -0.030), (r1 * 0.55, (w0 + w1) / 2 * 1.04, 0.002, -0.026),
                                          (r1, w1, 0.010, -0.018)):
            ring = []
            for side in (-1, 1):
                for dx in (dx_back, dx_front):
                    # point in the spoke's local frame: radial r, tangential side*w/2
                    y = r * math.cos(a) - side * w / 2 * math.sin(a)
                    z = r * math.sin(a) + side * w / 2 * math.cos(a)
                    ring.append(bm.verts.new((xf + dx, y, z)))
            verts.append(ring)
        # ring order: (-1,back), (-1,front), (1,back), (1,front) -> quad loop order
        order = (0, 1, 3, 2)
        for A, Bq in zip(verts, verts[1:]):
            for k in range(4):
                a0, a1 = order[k], order[(k + 1) % 4]
                bm.faces.new((A[a0], A[a1], Bq[a1], Bq[a0]))
        bm.faces.new([verts[0][o] for o in reversed(order)])
        bm.faces.new([verts[-1][o] for o in order])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    spokes = bm_obj("rim_spokes", bm)
    m = spokes.modifiers.new("bev", "BEVEL")
    m.width = 0.004
    m.segments = 2
    apply_mods(spokes)
    # lug nuts + centre cap
    bm = bmesh.new()
    for i in range(5):
        a = TAU * i / 5 + TAU / 12
        bm_cyl(bm, (xf + 0.018, 0.050 * math.cos(a), 0.050 * math.sin(a)), 0.0105, 0.022, seg=6, axis="X")
    nuts = bm_obj("lug_nuts", bm, smooth_shade=False)
    bm = bmesh.new()
    revolve(bm, [(0.0, xf + 0.030), (0.020, xf + 0.029), (0.030, xf + 0.022), (0.033, xf + 0.012)], 24)
    cap = bm_obj("center_cap", bm)
    return [barrel, hub, spokes, nuts, cap]


def brake():
    """Vented disc (two plates and a gap ring) on a hat, and a caliper at the rear-top."""
    bm = bmesh.new()
    xd = -0.015
    prof = [(0.075, xd + 0.040), (0.090, xd + 0.040), (0.092, xd + 0.012), (0.142, xd + 0.012), (0.142, xd - 0.012),
            (0.090, xd - 0.012), (0.088, xd - 0.006)]
    rings = revolve(bm, prof, 48)
    bm.faces.new(list(reversed(rings[0])))
    disc = bm_obj("brake_disc", bm)
    # caliper: a block curved round the disc edge, behind the axle (+Y = rear), upper side
    bm = bmesh.new()
    a0, a1 = math.radians(20), math.radians(70)
    seg = 8
    inner, outer = 0.098, 0.158
    rings = []
    for k in range(seg + 1):
        a = a0 + (a1 - a0) * k / seg
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for (r, x) in ((inner, xd - 0.030), (outer, xd - 0.030), (outer, xd + 0.032), (inner, xd + 0.032)):
            ring.append(bm.verts.new((x, r * ca, r * sa)))
        rings.append(ring)
    for A, Bq in zip(rings, rings[1:]):
        for k in range(4):
            bm.faces.new((A[k], A[(k + 1) % 4], Bq[(k + 1) % 4], Bq[k]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    cal = bm_obj("caliper", bm)
    m = cal.modifiers.new("bev", "BEVEL")
    m.width = 0.006
    m.segments = 2
    apply_mods(cal)
    return disc, cal


def build_wheel():
    """Returns (rotating parts [(name, group, obj)], caliper (name, group, obj))."""
    out = [("tyre", "tyre", tyre())]
    for o in rim():
        out.append((o.name, "rim" if o.name != "lug_nuts" else "lug", o))
    disc, cal = brake()
    out.append(("brake_disc", "brake_disc", disc))
    return out, ("caliper", "caliper", cal)
