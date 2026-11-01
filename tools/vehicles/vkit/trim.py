"""Exterior trim kits: grille, window seals, rub strips, overfenders, mirrors, door handles,
wipers + cowl, number plates, exhaust, mudflaps, glass frit, generic box lists.

Each function takes its spec item `p` and returns [(name, group, obj)].
"""
import math

import bmesh
from mathutils import Matrix, Vector

from . import body as B
from . import cfg
from . import panels as P
from .geom import bm_box, bm_cyl, bm_tube_path, lerp
from .panels import frange
from .shapes import SIDES, box, lathe, mods, obj, rot_x


# ------------------------------------------------------------------ grille


def grille(p):
    """p: {z, w, h, back, slats: {n, z0, pitch, w, t}, bars: {n, pitch} (vertical), badge: r,
    intakes: {x, z, w, h, bars, pitch, x0}}"""
    out = []
    y0 = P.front_face_y(0.0, p.z)
    back = box("grille_back", (0, y0 + p.get("back", 0.06), p.z), (p.w, 0.02, p.h))
    out.append((back.name, "black_trim", back))
    if p.get("slats"):
        s = p.slats
        for i in range(s.n):
            z = s.z0 + i * s.pitch
            sl = box(f"grille_slat_{i}", (0, P.front_face_y(0.0, z) + 0.016, z), (s.w, 0.025, s.get("t", 0.007)), bevel=0.002)
            out.append((sl.name, "grille", sl))
    if p.get("bars"):
        s = p.bars
        for i in range(s.n):
            x = (i - (s.n - 1) / 2) * s.pitch
            bar = box(f"grille_bar_{i}", (x, P.front_face_y(x, p.z) + 0.02, p.z), (s.get("t", 0.008), 0.025, p.h - 0.02), bevel=0.002)
            out.append((bar.name, "grille", bar))
    if p.get("badge"):
        r = p.badge
        bz = p.get("badge_z", p.z)
        badge = lathe("grille_badge", [(0.0, 0.0), (r, 0.0), (r + 0.004, -0.006), (r + 0.004, -0.012)],
                      (0, P.front_face_y(0.0, bz) + p.get("badge_y", 0.004) if p.get("badge_z") else y0 + 0.004, bz), "Y", 20, sign=-1)
        out.append((badge.name, "chrome", badge))
    if p.get("intakes"):
        it = p.intakes
        for sx, side in SIDES:
            yi = P.front_face_y(sx * it.x, it.get("ray_z", it.z - 0.002))
            m = box(f"intake_mesh_{side}", (sx * it.x, yi + 0.04, it.z), (it.w, 0.012, it.h))
            out.append((m.name, "black_trim", m))
            for i in range(it.bars):
                x = sx * (it.x0 + i * it.pitch)
                s = box(f"intake_bar_{side}{i}", (x, yi + 0.025, it.z), (0.012, 0.03, it.h - 0.01))
                out.append((s.name, "black_trim", s))
    return out


# ------------------------------------------------------------------ glass trims


def _densify(pts, step, closed=True):
    dense = []
    n = len(pts)
    for i in range(n if closed else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(L / step))
        for j in range(k):
            t = j / k
            dense.append((lerp(a[0], b[0], t), lerp(a[1], b[1], t)))
    return dense


def window_seals(p):
    """Black rubber seals round the side glass (a thin tube along each opening)."""
    out = []
    pn = cfg.V.panels
    for sx, side in SIDES:
        loops = [(d.name, P.door_dlo(d)) for d in pn.doors]
        if p.get("fixed", False):
            loops += [(w.name, P.fixed_window(w)) for w in pn.get("windows", [])]
        for nm, pts in loops:
            if not pts:
                continue
            p3 = []
            for y, z in _densify(pts, 0.075):
                x, nrm = P.side_x(y, z, sx)
                p3.append((x + sx * 0.002, y, z))
            bm = bmesh.new()
            bm_tube_path(bm, p3, p.get("r", 0.0065), 5, closed=True)
            ob = obj(f"window_seal_{nm}_{side}", bm)
            out.append((ob.name, "rubber", ob))
    return out


def glass_frit(p):
    """Black ceramic frit bands round the windscreen and rear window: a strip lying on the glass
    along its border, `w` wide, with a dotted fade painted in Pigment."""
    out = []
    pn = cfg.V.panels
    w = p.get("w", 0.05)
    for nm, key in (("windscreen", "windshield"), ("rear_window", "rear_window")):
        win = pn.get(key)
        if not win or nm not in p.get("which", ("windscreen", "rear_window")):
            continue
        bm = bmesh.new()
        rings = []
        if win.get("kind", "top") == "top":
            outline = P.windshield_outline() if key == "windshield" else P.rear_window_outline()
            dense = _densify(outline, 0.06)
            cx = sum(q[0] for q in dense) / len(dense)
            cy = sum(q[1] for q in dense) / len(dense)
            for x, y in dense:
                d = Vector((cx - x, cy - y))
                d = Vector((d.x / max(abs(d.x), 1e-6), 0)) * w if abs(d.x) > 0.45 else Vector((0, d.y / max(abs(d.y), 1e-6))) * w
                ring = []
                for (px, py) in ((x, y), (x + d.x, y + d.y)):
                    zz, nrm = P.top_z(px, py)
                    ring.append(bm.verts.new((px, py, zz + 0.0015)))
                rings.append(ring)
            up = Vector((0, 0, 1))
        else:
            outline = P.trapezoid(win.zb, win.zt, win.wb, win.wt, win.r)
            dense = _densify(outline, 0.06)
            cx = sum(q[0] for q in dense) / len(dense)
            cz = sum(q[1] for q in dense) / len(dense)
            front = key == "windshield"
            for x, z in dense:
                d = Vector((cx - x, cz - z))
                d = d.normalized() * w if d.length > 1e-6 else d
                ring = []
                for (px, pz) in ((x, z), (x + d.x, z + d.y)):
                    yy = P.front_face_y(px, pz) - 0.0015 if front else P.rear_face_y(px, pz) + 0.0015
                    ring.append(bm.verts.new((px, yy, pz)))
                rings.append(ring)
            up = Vector((0, -1, 0)) if front else Vector((0, 1, 0))
        for i in range(len(rings)):
            A, Bq = rings[i], rings[(i + 1) % len(rings)]
            try:
                bm.faces.new((A[0], Bq[0], Bq[1], A[1]))
            except ValueError:
                pass
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for f in bm.faces:
            if f.normal.dot(up) < 0:
                f.normal_flip()
        ob = obj(f"frit_{nm}", bm)
        out.append((ob.name, "frit", ob))
    return out


# ------------------------------------------------------------------ side trims


def body_mouldings(p):
    """Black rub strips along the doors (90s style). p: {z, strips: [[name, y0, y1]], h, proud}"""
    out = []
    zc = p.z
    h2 = p.get("h", 0.045) / 2
    pr = p.get("proud", 0.009)
    prof = [(-h2, 0.0), (-h2, pr * 2 / 3), (-h2 + 0.0105, pr), (h2 - 0.0105, pr), (h2, pr * 2 / 3), (h2, 0.0)]
    for sx, side in SIDES:
        for nm, y0, y1 in p.strips:
            pts = []
            for y in frange(y0, y1, p.get("n", 12)):
                x, n = P.side_x(y, zc, sx)
                pts.append((x, y, zc))
            bm = bmesh.new()
            rings = []
            for x, y, z in pts:
                rings.append([bm.verts.new((x + sx * o, y, z + dz)) for dz, o in prof])
            for A, Bq in zip(rings, rings[1:]):
                for k in range(len(prof) - 1):
                    bm.faces.new((A[k], A[k + 1], Bq[k + 1], Bq[k]))
            bm.faces.new(rings[0])
            bm.faces.new(list(reversed(rings[-1])))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            ob = obj(f"rub_strip_{nm}_{side}", bm)
            out.append((ob.name, p.get("group", "black_trim"), ob))
    return out


def fender_flares(p):
    """Bolt-on overfenders round all arches, with bolts. p: {a0, a1, n, width, bolts}"""
    out = []
    a0d, a1d = p.get("a0", -8), p.get("a1", 188)
    wd = p.get("width", 0.07)
    for axle, an in zip(cfg.V.axles, "FR"):
        for sx, side in SIDES:
            R0 = cfg.V.arch_r - 0.004
            prof = [(R0, 0.0), (R0, 0.045), (R0 + 0.02, 0.052), (R0 + wd, 0.020), (R0 + wd + 0.015, 0.002)]
            angs = [lerp(math.radians(a0d), math.radians(a1d), t) for t in frange(0.0, 1.0, p.get("n", 34))]
            rings = []
            bm = bmesh.new()
            for a in angs:
                ring = []
                for r, o in prof:
                    y = axle + r * math.cos(a)
                    z = B.arch_z() + r * math.sin(a)
                    x, n = P.side_x(y, max(z, p.get("zmin", 0.30)), sx)
                    ring.append(bm.verts.new((x + sx * (o - 0.002), y, z)))
                rings.append(ring)
            for A, Bq in zip(rings, rings[1:]):
                for k in range(len(prof) - 1):
                    bm.faces.new((A[k], A[k + 1], Bq[k + 1], Bq[k]))
                bm.faces.new((A[-1], A[0], Bq[0], Bq[-1]))
            bm.faces.new(rings[0])
            bm.faces.new(list(reversed(rings[-1])))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            ob = obj(f"flare_{an}{side}", bm)
            out.append((ob.name, p.get("group", "black_trim"), ob))
            if p.get("bolts", 7):
                bm = bmesh.new()
                for t in frange(0.08, 0.92, p.get("bolts", 7)):
                    a = lerp(math.radians(a0d), math.radians(a1d), t)
                    r = R0 + 0.045
                    y = axle + r * math.cos(a)
                    z = B.arch_z() + r * math.sin(a)
                    x, n = P.side_x(y, max(z, p.get("zmin", 0.30)), sx)
                    bm_cyl(bm, (x + sx * 0.040, y, z), 0.008, 0.012, seg=6, axis="X")
                ob = obj(f"flare_bolts_{an}{side}", bm)
                out.append((ob.name, "chrome", ob))
    return out


def arch_lips(p):
    """A thin rolled lip round each arch opening, in body colour or black (no bolts)."""
    out = []
    for axle, an in zip(cfg.V.axles, "FR"):
        for sx, side in SIDES:
            R0 = cfg.V.arch_r + p.get("offset", 0.002)
            prof = [(R0 - 0.002, -0.004), (R0 + 0.006, 0.006), (R0 + p.get("width", 0.025), 0.004), (R0 + p.get("width", 0.025) + 0.006, -0.002)]
            angs = [lerp(math.radians(p.get("a0", -6)), math.radians(p.get("a1", 186)), t) for t in frange(0.0, 1.0, 30)]
            bm = bmesh.new()
            rings = []
            for a in angs:
                ring = []
                for r, o in prof:
                    y = axle + r * math.cos(a)
                    z = B.arch_z() + r * math.sin(a)
                    x, n = P.side_x(y, max(z, p.get("zmin", 0.25)), sx)
                    ring.append(bm.verts.new((x + sx * o, y, z)))
                rings.append(ring)
            for A, Bq in zip(rings, rings[1:]):
                for k in range(len(prof) - 1):
                    bm.faces.new((A[k], A[k + 1], Bq[k + 1], Bq[k]))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            ob = obj(f"arch_lip_{an}{side}", bm)
            mods(ob, solid=0.006)
            out.append((ob.name, p.get("group", "black_trim"), ob))
    return out


def mirrors(p):
    """Door mirrors on stalks. p: {y, dz, size, reach, group, arm: {...} (truck-style arm mirror)}"""
    out = []
    for sx, side in SIDES:
        y, z = p.y, P.z_belt(p.y) + p.get("dz", 0.075)
        x, n = P.side_x(y, z - 0.07, sx)
        reach = p.get("reach", 0.135)
        sw, sd, sh = p.get("size", (0.19, 0.085, 0.115))
        if p.get("arm"):
            # a tubular arm from the door / A pillar out to a tall mirror head
            bm = bmesh.new()
            a = p.arm
            bm_tube_path(bm, [(x - sx * 0.01, y + 0.02, z - a.get("drop", 0.10)), (x + sx * reach * 0.6, y + 0.03, z - a.get("drop", 0.10) * 0.5),
                              (x + sx * (reach - sw / 2 + 0.01), y + 0.02, z)], a.get("r", 0.012), 8)
            st = obj(f"mirror_stalk_{side}", bm)
            out.append((st.name, "black_metal", st))
        else:
            st = box(f"mirror_stalk_{side}", (x + sx * 0.035, y + 0.01, z - 0.045), (0.075, 0.04, 0.045), bevel=0.008)
            out.append((st.name, "black_trim", st))
        bm = bmesh.new()
        bm_box(bm, (x + sx * reach, y, z), (sw, sd, sh))
        for v in bm.verts:
            if v.co.y < y:  # front of the housing is rounder / narrower
                v.co.z = z + (v.co.z - z) * 0.85
                v.co.x = x + sx * reach + (v.co.x - (x + sx * reach)) * 0.9
        hob = obj(f"mirror_housing_{side}", bm)
        mods(hob, bevel=min(0.018, 0.3 * min(sw, sd, sh)), seg=3)
        out.append((hob.name, p.get("group", "paint"), hob))
        g = box(f"mirror_glass_{side}", (x + sx * reach, y + sd / 2 + 0.0015, z), (sw - 0.025, 0.004, sh - 0.023), bevel=0.012, seg=3)
        out.append((g.name, "mirror", g))
    return out


def door_handles(p):
    """p: {handles: [[name, y, lock]], dz, style: pull|flap}"""
    out = []
    for sx, side in SIDES:
        for nm, y, lock in p.handles:
            z = P.z_belt(y) - p.get("dz", 0.075)
            x, n = P.side_x(y, z, sx)
            pl = box(f"handle_pocket_{nm}{side}", (x - sx * 0.002, y, z), (0.008, 0.17, 0.05), bevel=0.012, seg=2)
            out.append((pl.name, "black_trim", pl))
            hb = box(f"handle_{nm}{side}", (x + sx * 0.010, y, z + 0.004), (0.016, 0.145, 0.024), bevel=0.007, seg=2)
            out.append((hb.name, p.get("group", "chrome"), hb))
            if lock:
                bm = bmesh.new()
                bm_cyl(bm, (x + sx * 0.006, y + 0.105, z + 0.004), 0.009, 0.012, seg=12, axis="X")
                lk = obj(f"door_lock_{side}", bm)
                out.append((lk.name, "chrome", lk))
    return out


def wipers(p):
    """p: {arms: [[px, length]], y, cowl: {y, ray_y, size, tilt}, lift}"""
    out = []
    lift = p.get("lift", 0.018)
    for k, (px, length) in enumerate(p.arms):
        yb = p.y
        dy = p.get("sweep_dy", 0.03)
        z0, n = P.top_z(px, yb)
        pts = []
        for t in frange(0, 1, 10):
            x = px - t * length
            y = yb + dy * t
            z, n = P.top_z(x, y)
            pts.append((x, y, z + lift))
        bm = bmesh.new()
        bm_tube_path(bm, pts, 0.006, 6)
        bm_cyl(bm, (px, yb - 0.01, z0 + 0.02), 0.018, 0.03, seg=12, axis="Z")
        arm = obj(f"wiper_arm_{k}", bm)
        out.append((arm.name, "black_metal", arm))
        bpts = []
        for t in frange(0.15, 1.0, 10):
            x = px - t * length
            y = yb + dy * t + 0.012
            z, n = P.top_z(x, y)
            bpts.append((x, y, z + lift / 2))
        bm = bmesh.new()
        bm_tube_path(bm, bpts, 0.0055, 5)
        bl = obj(f"wiper_blade_{k}", bm)
        out.append((bl.name, "rubber", bl))
    if p.get("cowl"):
        c = p.cowl
        zc, n = P.top_z(0.0, c.ray_y)
        cw = box("cowl_panel", (0, c.y, zc + 0.002), c.size, bevel=0.004, rot=rot_x(c.tilt))
        out.append((cw.name, "black_trim", cw))
    return out


def plates(p):
    """p: {front: {z, ray_z, size}, rear: {z, ray_z, size}, lamp: {z, size}}"""
    out = []
    if p.get("front"):
        f = p.front
        yf = P.front_face_y(0.0, f.ray_z) + 0.014
        pf = box("plate_F", (0, yf - 0.004, f.z), f.size, bevel=0.003)
        out.append((pf.name, "plate", pf))
    if p.get("rear"):
        r = p.rear
        yr = P.rear_face_y(0.0, r.ray_z) - 0.014
        pr = box("plate_R", (0, yr + 0.004, r.z), r.size, bevel=0.003)
        out.append((pr.name, "plate", pr))
    if p.get("lamp"):
        lp = p.lamp
        pl = box("plate_lamp", (0, P.rear_face_y(0.0, lp.get("ray_z", lp.z)) - 0.002, lp.z), lp.size, bevel=0.003)
        out.append((pl.name, "emitter_reverse", pl))
    return out


def exhaust(p):
    """p: {tips: [x...] (mirrored if dual), z, r, pipe: [pts], branch_start: {L: pt, R: pt}, branch_mid_y,
    silencer: [c, s], catalyst: [c, s], side_exit: bool}"""
    out = []
    z = p.z
    sides = [(sx, side) for sx, side in SIDES if (p.get("dual", True) or sx == p.get("side", 1))]
    for sx, side in sides:
        x = sx * p.x
        yr = P.rear_face_y(x, z)
        r = p.get("r", 0.040)
        tip = lathe(f"exhaust_tip_{side}", [(r, -0.14), (r, 0.012), (r - 0.004, 0.018), (r - 0.009, 0.012), (r - 0.009, -0.06)],
                    (x, yr, z), "Y", 20)
        out.append((tip.name, "exhaust", tip))
    bm = bmesh.new()
    bm_tube_path(bm, [tuple(q) for q in p.pipe], 0.026, 10)
    for sx, side in reversed(sides):
        st = p.branch_start[side]
        bm_tube_path(bm, [tuple(st), (sx * p.x, p.branch_mid_y, z), (sx * p.x, P.rear_face_y(sx * p.x, z) - 0.13, z)], 0.024, 10)
    pipe = obj("exhaust_pipe", bm)
    out.append((pipe.name, "underbody_metal", pipe))
    if p.get("silencer"):
        c, s = p.silencer
        sil = box("silencer", tuple(c), tuple(s), bevel=0.04, seg=3)
        out.append((sil.name, "underbody_metal", sil))
    if p.get("catalyst"):
        c, s = p.catalyst
        cat = box("catalyst", tuple(c), tuple(s), bevel=0.03, seg=3)
        out.append((cat.name, "underbody_metal", cat))
    return out


def mudflaps(p):
    """p: {zt, zb, inset, w, axles: [F, R]}"""
    out = []
    for axle, an in zip(cfg.V.axles, "FR"):
        if an not in p.get("axles", "FR"):
            continue
        for sx, side in SIDES:
            y = axle + cfg.V.arch_r + 0.012
            zt, zb = p.zt, p.get("zb", 0.12)
            x, n = P.side_x(y + 0.02, zt, sx)
            fl = box(f"mudflap_{an}{side}", (x - sx * p.get("inset", 0.12), y, (zt + zb) / 2), (p.get("w", 0.19), 0.006, zt - zb), bevel=0.002,
                     rot=Matrix.Rotation(math.radians(6), 4, "X"))
            out.append((fl.name, "rubber", fl))
    return out


def boxes(p):
    """A list of bevelled boxes: p.items = [[name, group, centre, size, bevel?, seg?, tilt?]]; `mirror` copies
    items whose name ends in _L to the right side."""
    out = []
    for it in p["items"]:
        nm, grp, c, s = it[:4]
        bev = it[4] if len(it) > 4 else 0.0
        seg = it[5] if len(it) > 5 else 2
        tilt = it[6] if len(it) > 6 else 0.0
        b = box(nm, tuple(c), tuple(s), bevel=bev, seg=seg, rot=rot_x(tilt) if tilt else None)
        out.append((nm, grp, b))
    return out


def tubes(p):
    """Tube runs: p.items = [[name, group, radius, [pts...], seg?]]"""
    out = []
    for it in p["items"]:
        nm, grp, r, pts = it[:4]
        bm = bmesh.new()
        bm_tube_path(bm, [tuple(q) for q in pts], r, it[4] if len(it) > 4 else 8)
        out.append((nm, grp, obj(nm, bm)))
    return out
