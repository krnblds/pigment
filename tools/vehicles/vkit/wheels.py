"""Wheel sets (spec block `V.wheel`): tyre with tread blocks and sidewall detail, a rim in
one of several designs, lug nuts and a centre cap, a vented brake disc (or drum) and a caliper.

Built at the origin (the hub centre), rotation axis X, the face of the rim towards +X (a
left-side wheel). Right-side wheels are the same mesh turned 180 degrees about the up axis.

Rim styles:
    split6   six split spokes (the Tsubame-4's RS-90)
    spokes   n straight tapered spokes (n = `spokes`)
    mesh     cross-spoke mesh: 2 x n thin spokes crossing (90s BBS-ish)
    steel    pressed steel: a dished disc with round vent holes and a hubcap ring
    aero     a flat aero cover with slots (robotaxi / bus)
    turbofan curved blades round a closed hub (sports)
"""
import math

import bmesh
from mathutils import Matrix

from . import cfg
from .geom import apply_mods, bm_cyl, bm_obj

TAU = 2 * math.pi


def W():
    return cfg.V.wheel


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
    """Profile from the inner bead over the tread to the outer bead; tread blocks are radial
    offsets on the tread rings (alternating shoulder lugs + 2 grooves)."""
    w = W()
    R_TYRE, R_RIM = cfg.V.wheel_r, w.rim_r
    hw = w.width / 2
    side = w.get("sidewall", 1.0)    # sidewall bulge scale (taller tyres bulge more)
    prof = [
        (R_RIM + 0.004, -hw + 0.018),   # inner bead
        (R_RIM + 0.030, -hw + 0.004),
        (R_TYRE - 0.040 * side, -hw - 0.004),   # sidewall bulge
        (R_TYRE - 0.016, -hw + 0.004),  # shoulder
        (R_TYRE - 0.004, -hw + 0.018),
        (R_TYRE, -hw + 0.034),          # tread starts
        (R_TYRE, -0.052 * w.width / 0.215),
        (R_TYRE - 0.007, -0.048 * w.width / 0.215),       # groove 1
        (R_TYRE - 0.007, -0.036 * w.width / 0.215),
        (R_TYRE, -0.032 * w.width / 0.215),
        (R_TYRE, 0.032 * w.width / 0.215),
        (R_TYRE - 0.007, 0.036 * w.width / 0.215),        # groove 2
        (R_TYRE - 0.007, 0.048 * w.width / 0.215),
        (R_TYRE, 0.052 * w.width / 0.215),
        (R_TYRE, hw - 0.034),
        (R_TYRE - 0.004, hw - 0.018),
        (R_TYRE - 0.016, hw - 0.004),
        (R_TYRE - 0.040 * side, hw + 0.002),
        (R_TYRE - 0.054 * side, hw + 0.006),   # sidewall lettering band (raised)
        (R_TYRE - 0.080 * side, hw + 0.006),
        (R_RIM + 0.070 * side, hw + 0.004),
        (R_RIM + 0.030, hw - 0.004),    # rim protector
        (R_RIM + 0.004, hw - 0.018),
    ]
    seg = w.get("tyre_seg", 64)
    lug = {5, 6, 13, 14}
    centre = {9, 10}
    pitch = w.get("tread_pitch", 4)
    depth = w.get("tread_depth", 0.005)

    def radial(i, k):
        if i in lug:
            return -depth if (k % pitch) == 0 else 0.0
        if i in centre:
            return -(depth - 0.001) if (k % pitch) == pitch // 2 else 0.0
        return 0.0
    bm = bmesh.new()
    rings = revolve(bm, prof, seg, radial_fn=radial)
    A, Bq = rings[0], rings[-1]
    for k in range(seg):
        bm.faces.new((Bq[k], Bq[(k + 1) % seg], A[(k + 1) % seg], A[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm_obj("tyre", bm)


def barrel():
    w = W()
    R_RIM, R_LIP = w.rim_r, w.lip_r
    hw = w.width / 2
    bm = bmesh.new()
    prof = [
        (R_RIM - 0.008, -hw + 0.010), (R_LIP, -hw + 0.012), (R_LIP, -hw + 0.022), (R_RIM - 0.002, -hw + 0.026),
        (R_RIM - 0.014, -0.02), (R_RIM - 0.014, 0.03), (R_RIM - 0.002, hw - 0.030),
        (R_LIP + 0.002, hw - 0.014), (R_LIP + 0.002, hw - 0.004), (R_LIP - 0.010, hw), (R_RIM - 0.020, hw - 0.006),
        (R_RIM - 0.024, hw - 0.020), (R_RIM - 0.020, -hw + 0.030), (R_RIM - 0.012, -hw + 0.012),
    ]
    rings = revolve(bm, prof, 48)
    A, Bq = rings[0], rings[-1]
    for k in range(48):
        bm.faces.new((Bq[k], Bq[(k + 1) % 48], A[(k + 1) % 48], A[k]))
    return bm_obj("rim_barrel", bm)


def _hub(xf, r=0.085):
    bm = bmesh.new()
    s = r / 0.085
    hub_prof = [(0.0, xf + 0.012), (0.060 * s, xf + 0.012), (0.075 * s, xf + 0.004), (0.085 * s, xf - 0.010), (0.080 * s, xf - 0.040), (0.0, xf - 0.040)]
    revolve(bm, hub_prof, 36)
    return bm_obj("rim_hub", bm)


def _spoke_bm(bm, xf, a, r0, r1, w0, w1, mid=0.55, front=(0.008, 0.002, 0.010), back=(-0.030, -0.026, -0.018), twist=0.0):
    """One tapered spoke from radius r0 to r1 at angle a (in the face plane x = xf)."""
    verts = []
    for (r, w, dx_front, dx_back, tw) in ((r0, w0, front[0], back[0], 0.0), (r1 * mid, (w0 + w1) / 2 * 1.04, front[1], back[1], twist * 0.5),
                                          (r1, w1, front[2], back[2], twist)):
        ring = []
        aa = a + tw
        for side in (-1, 1):
            for dx in (dx_back, dx_front):
                y = r * math.cos(aa) - side * w / 2 * math.sin(aa)
                z = r * math.sin(aa) + side * w / 2 * math.cos(aa)
                ring.append(bm.verts.new((xf + dx, y, z)))
        verts.append(ring)
    order = (0, 1, 3, 2)
    for A, Bq in zip(verts, verts[1:]):
        for k in range(4):
            a0, a1 = order[k], order[(k + 1) % 4]
            bm.faces.new((A[a0], A[a1], Bq[a1], Bq[a0]))
    bm.faces.new([verts[0][o] for o in reversed(order)])
    bm.faces.new([verts[-1][o] for o in order])


def rim_face():
    """The rim face for the chosen style: [objects]."""
    w = W()
    R_RIM = w.rim_r
    hw = w.width / 2
    style = w.get("style", "split6")
    xf = hw - w.get("dish", 0.040)
    out = []
    if style in ("split6", "spokes", "mesh", "turbofan"):
        out.append(_hub(xf, w.get("hub_r", 0.085)))
        bm = bmesh.new()
        r0, r1 = w.get("hub_r", 0.085) - 0.013, R_RIM - 0.016
        if style == "split6":
            for i in range(12):
                a = TAU * (i // 2) / 6 + (0.075 if i % 2 else -0.075)
                _spoke_bm(bm, xf, a, r0, r1, 0.022, 0.017)
        elif style == "spokes":
            n = w.get("spokes", 5)
            for i in range(n):
                _spoke_bm(bm, xf, TAU * i / n, r0, r1, w.get("spoke_w0", 0.040), w.get("spoke_w1", 0.030))
        elif style == "mesh":
            n = w.get("spokes", 10)
            for i in range(n):
                for tw in (-0.28, 0.28):
                    _spoke_bm(bm, xf, TAU * i / n - tw / 2, r0, r1, 0.011, 0.009, front=(0.006, 0.0, 0.006), back=(-0.016, -0.016, -0.012), twist=tw)
        elif style == "turbofan":
            n = w.get("spokes", 16)
            for i in range(n):
                _spoke_bm(bm, xf, TAU * i / n, r0, r1, 0.020, 0.032, front=(0.004, 0.002, 0.002), back=(-0.010, -0.010, -0.010), twist=0.22)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        spokes = bm_obj("rim_spokes", bm)
        m = spokes.modifiers.new("bev", "BEVEL")
        m.width = 0.004 if style != "mesh" else 0.002
        m.segments = 2
        apply_mods(spokes)
        out.append(spokes)
    elif style == "steel":
        # a pressed disc: dish profile from the hub to the barrel with a ring of round vent holes
        bm = bmesh.new()
        nh = w.get("holes", 8)
        seg = nh * 8
        prof = [(0.0, xf + 0.004), (0.085, xf + 0.004), (0.095, xf - 0.004), (0.115, xf - 0.010), (0.125, xf - 0.004),
                (R_RIM * 0.62, xf - 0.002), (R_RIM * 0.80, xf - 0.012), (R_RIM - 0.016, xf - 0.040), (R_RIM - 0.014, xf - 0.050)]
        revolve(bm, prof, seg)
        disc = bm_obj("rim_disc", bm)
        # vent holes: boolean cylinders through the flat ring
        cb = bmesh.new()
        rh = (R_RIM * 0.62 + 0.125) / 2 + 0.008
        for i in range(nh):
            a = TAU * (i + 0.5) / nh
            bm_cyl(cb, (xf, rh * math.cos(a), rh * math.sin(a)), w.get("hole_r", 0.022), 0.08, seg=16, axis="X")
        cutter = bm_obj("holes", cb)
        m = disc.modifiers.new("h", "BOOLEAN")
        m.operation = "DIFFERENCE"
        m.solver = "EXACT"
        m.object = cutter
        apply_mods(disc)
        import bpy
        bpy.data.objects.remove(cutter, do_unlink=True)
        m = disc.modifiers.new("sol", "SOLIDIFY")
        m.thickness = 0.004
        m.offset = -1
        apply_mods(disc)
        out.append(disc)
    elif style == "aero":
        bm = bmesh.new()
        prof = [(0.0, xf + 0.020), (0.07, xf + 0.018), (R_RIM * 0.75, xf + 0.010), (R_RIM - 0.010, xf - 0.004), (R_RIM - 0.004, xf - 0.020)]
        revolve(bm, prof, 64)
        disc = bm_obj("rim_cover", bm)
        m = disc.modifiers.new("sol", "SOLIDIFY")
        m.thickness = 0.006
        m.offset = -1
        apply_mods(disc)
        out.append(disc)
        # slots: dark inserts
        bm = bmesh.new()
        n = w.get("slots", 7)
        for i in range(n):
            a = TAU * i / n
            for t in range(6):
                r = 0.095 + t * (R_RIM * 0.72 - 0.095) / 5
                aa = a + t * 0.06
                bm_cyl(bm, (xf + 0.012 + 0.008 * (1 - t / 5), r * math.cos(aa), r * math.sin(aa)), 0.010, 0.006, seg=8, axis="X")
        slots = bm_obj("rim_slots", bm)
        out.append(slots)
    return out


def lugs_and_cap():
    w = W()
    hw = w.width / 2
    xf = hw - w.get("dish", 0.040)
    out = []
    n = w.get("lugs", 5)
    if n:
        bm = bmesh.new()
        lr = w.get("lug_r", 0.050)
        for i in range(n):
            a = TAU * i / n + TAU / 12
            bm_cyl(bm, (xf + 0.018, lr * math.cos(a), lr * math.sin(a)), 0.0105, 0.022, seg=6, axis="X")
        out.append(bm_obj("lug_nuts", bm, smooth_shade=False))
    cr = w.get("cap_r", 0.033)
    if cr:
        bm = bmesh.new()
        s = cr / 0.033
        revolve(bm, [(0.0, xf + 0.030), (0.020 * s, xf + 0.029), (0.030 * s, xf + 0.022), (0.033 * s, xf + 0.012)], 24)
        out.append(bm_obj("center_cap", bm))
    return out


def rim():
    return [barrel()] + rim_face() + lugs_and_cap()


def brake():
    """Vented disc (two plates and a gap ring) on a hat, and a caliper at the rear-top."""
    w = W()
    dr = w.get("disc_r", 0.142)
    bm = bmesh.new()
    xd = -0.015
    prof = [(0.075, xd + 0.040), (0.090, xd + 0.040), (0.092, xd + 0.012), (dr, xd + 0.012), (dr, xd - 0.012),
            (0.090, xd - 0.012), (0.088, xd - 0.006)]
    rings = revolve(bm, prof, 40)
    bm.faces.new(list(reversed(rings[0])))
    disc = bm_obj("brake_disc", bm)
    bm = bmesh.new()
    a0, a1 = math.radians(20), math.radians(w.get("caliper_a1", 70))
    seg = 8
    inner, outer = dr - 0.044, dr + 0.016
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
        grp = "lug" if o.name == "lug_nuts" else ("rim_dark" if o.name == "rim_slots" else "rim")
        out.append((o.name, grp, o))
    disc, cal = brake()
    out.append(("brake_disc", "brake_disc", disc))
    return out, ("caliper", "caliper", cal)


def dual_copy(me, offset):
    """For twin rear wheels: the wheel mesh plus a copy turned round (rim face inward) and moved
    `offset` towards the body (-X for a left wheel)."""
    import bmesh as _b
    bm = _b.new()
    bm.from_mesh(me)
    tmp = me.copy()
    tmp.transform(Matrix.Translation((-offset, 0, 0)) @ Matrix.Rotation(math.pi, 4, "Z"))
    bm.from_mesh(tmp)
    import bpy
    bpy.data.meshes.remove(tmp)
    out = bpy.data.meshes.new(me.name + "_dual")
    bm.to_mesh(out)
    bm.free()
    return out
