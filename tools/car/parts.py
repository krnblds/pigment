"""Detail parts: lights, grille, trims, mirrors, wipers, handles, plates, exhaust,
roof gear, flares, mudflaps, underbody + suspension, wheel wells and the interior.

Every function returns [(name, group, obj)]. `group` is the material family the
texturing script uses (paint, black_trim, chrome, glass, lens_*, emitter_*, ...).
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import body as B
import panels as P
from carlib import apply_mods, bm_box, bm_cyl, bm_obj, bm_sphere, bm_tube_path, delete, lerp
from panels import frange

TAU = 2 * math.pi


def obj(name, bm, smooth=True):
    return bm_obj(name, bm, smooth_shade=smooth)


def mods(ob, bevel=None, subd=0, seg=2, solid=None, weld=False):
    if bevel:
        m = ob.modifiers.new("bev", "BEVEL")
        m.width = bevel
        m.segments = seg
        m.limit_method = "ANGLE"
        m.harden_normals = False
    if solid:
        m = ob.modifiers.new("sol", "SOLIDIFY")
        m.thickness = solid
        m.offset = -1
    if subd:
        m = ob.modifiers.new("sub", "SUBSURF")
        m.levels = subd
        m.render_levels = subd
    apply_mods(ob)
    return ob


def box(name, c, s, bevel=0.0, rot=None, subd=0, seg=2):
    bm = bmesh.new()
    mat = None
    if rot is not None:
        mat = Matrix.Translation(Vector(c)) @ rot @ Matrix.Translation(-Vector(c))
    bm_box(bm, c, s, mat)
    ob = obj(name, bm, smooth=bool(subd))
    if bevel:
        bevel = min(bevel, 0.4 * min(s))   # wider bevels collapse thin boxes into degenerate faces
    if bevel or subd:
        mods(ob, bevel=bevel or None, subd=subd, seg=seg)
    return ob


def lathe(name, profile, c, axis="Y", seg=24, sign=1, closed_ends=False):
    """Revolve [(r, a)] (radius, axial offset) around `axis` through c."""
    bm = bmesh.new()
    rings = []
    for r, a in profile:
        ring = []
        for k in range(seg):
            t = TAU * k / seg
            u, v = r * math.cos(t), r * math.sin(t)
            if axis == "Y":
                p = (c[0] + u, c[1] + sign * a, c[2] + v)
            elif axis == "X":
                p = (c[0] + sign * a, c[1] + u, c[2] + v)
            else:
                p = (c[0] + u, c[1] + v, c[2] + sign * a)
            ring.append(bm.verts.new(p))
        rings.append(ring)
    for A, Bq in zip(rings, rings[1:]):
        for k in range(seg):
            bm.faces.new((A[k], A[(k + 1) % seg], Bq[(k + 1) % seg], Bq[k]))
    if closed_ends:
        bm.faces.new(rings[0])
        bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj(name, bm)


def mirror_x(ob, name):
    n = ob.copy()
    n.data = ob.data.copy()
    n.name = name
    bpy.context.scene.collection.objects.link(n)
    n.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    n.data.flip_normals()
    return n


# ------------------------------------------------------------------ lights


def headlights():
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        yb = P.front_face_y(sx * 0.6, 0.63)
        # housing: a dark box behind the aperture
        h = box(f"headlight_housing_{side}", (sx * 0.600, yb + 0.15, 0.632), (0.40, 0.20, 0.13), bevel=0.01)
        out.append((h.name, "black_trim", h))
        # two reflector bowls per lamp (90s twin-reflector headlamp) + bulbs
        for k, (xc, r) in enumerate(((0.700, 0.060), (0.505, 0.052))):
            prof = [(0.012, 0.075), (r * 0.55, 0.055), (r * 0.85, 0.028), (r, 0.0), (r + 0.004, -0.004)]
            yk = P.front_face_y(sx * xc, 0.632)
            bowl = lathe(f"headlight_reflector_{side}{k}", prof, (sx * xc, yk + 0.028, 0.632), "Y", 20)
            out.append((bowl.name, "chrome", bowl))
            bm = bmesh.new()
            bm_sphere(bm, (sx * xc, yk + 0.058, 0.632), 0.014, 8, 5)
            bulb = obj(f"headlight_bulb_{side}{k}", bm)
            out.append((bulb.name, "emitter_head", bulb))
        # a slim LED position strip under the reflectors (a later "upgrade")
        strip = box(f"headlight_drl_{side}", (sx * 0.600, P.front_face_y(sx * 0.6, 0.582) + 0.016, 0.582), (0.36, 0.012, 0.010))
        out.append((strip.name, "emitter_head", strip))
        # amber indicator in the bumper corner
        yi = P.front_face_y(sx * 0.71, 0.48)
        ib = box(f"indicator_F_{side}", (sx * 0.71, yi + 0.03, 0.48), (0.17, 0.04, 0.045), bevel=0.004)
        out.append((ib.name, "emitter_amber", ib))
    return out


def taillights():
    out = []
    # one long housing behind the full-width aperture
    zc = 0.825
    yb = P.rear_face_y(0.0, zc)
    h = box("taillight_housing", (0, yb - 0.12, zc), (1.54, 0.16, 0.11), bevel=0.01)
    out.append((h.name, "black_trim", h))
    # segments: outer brake/tail (red), indicator (amber), reverse (white), centre reflector panel (red)
    segs = []
    for sx, side in ((1, "L"), (-1, "R")):
        segs += [(f"tail_brake_{side}", sx * 0.735, 0.20, "emitter_tail"),
                 (f"tail_indicator_{side}", sx * 0.565, 0.10, "emitter_amber"),
                 (f"tail_reverse_{side}", sx * 0.445, 0.10, "emitter_reverse")]
    for nm, xc, w, grp in segs:
        y = P.rear_face_y(xc, zc)
        e = box(nm, (xc, y - 0.035, zc), (w, 0.03, 0.095), bevel=0.004)
        out.append((nm, grp, e))
    # centre: a red reflector strip (not lit), with fine horizontal ribs
    for i in range(4):
        z = zc - 0.036 + i * 0.024
        y = P.rear_face_y(0.0, z)
        r = box(f"tail_center_rib_{i}", (0, y - 0.022, z), (0.76, 0.012, 0.012), bevel=0.003)
        out.append((r.name, "emitter_tail", r))
    # third brake light at the top of the rear window
    z3 = P.z_roof(1.03) - 0.03
    s3 = box("tail_third_brake", (0, 1.06, z3 - 0.01), (0.34, 0.035, 0.022), bevel=0.006,
             rot=Matrix.Rotation(math.radians(-38), 4, "X"))
    out.append((s3.name, "emitter_tail", s3))
    return out


# ------------------------------------------------------------------ grille, bumpers, trims


def grille():
    out = []
    y0 = P.front_face_y(0.0, 0.632)
    # a recessed black backing panel and five horizontal slats + a centre badge
    back = box("grille_back", (0, y0 + 0.06, 0.632), (0.70, 0.02, 0.13))
    out.append((back.name, "black_trim", back))
    for i in range(5):
        z = 0.588 + i * 0.022
        s = box(f"grille_slat_{i}", (0, P.front_face_y(0.0, z) + 0.016, z), (0.68, 0.025, 0.007), bevel=0.002)
        out.append((s.name, "grille", s))
    badge = lathe("grille_badge", [(0.0, 0.0), (0.032, 0.0), (0.036, -0.006), (0.036, -0.012)], (0, y0 + 0.004, 0.632), "Y", 20, sign=-1, closed_ends=False)
    out.append((badge.name, "chrome", badge))
    # lower intake meshes (honeycomb-ish slats) behind the bumper openings
    for sx, side in ((1, "L"), (-1, "R")):
        yi = P.front_face_y(sx * 0.39, 0.36)
        m = box(f"intake_mesh_{side}", (sx * 0.39, yi + 0.04, 0.362), (0.34, 0.012, 0.13))
        out.append((m.name, "black_trim", m))
        for i in range(4):
            x = sx * (0.26 + i * 0.085)
            s = box(f"intake_bar_{side}{i}", (x, yi + 0.025, 0.362), (0.012, 0.03, 0.12))
            out.append((s.name, "black_trim", s))
    return out


def push_bar():
    """Hoshikawa Security push bar: two uprights and a top hoop bolted through the bumper."""
    out = []
    yf = P.front_face_y(0.0, 0.40) - 0.095
    hoop = []
    for t in frange(0, 1, 13):
        a = math.pi * t
        x = -0.36 * math.cos(a)
        z = 0.30 + 0.30 * math.sin(a) ** 0.5
        hoop.append((x, yf - 0.012 * math.sin(a), z))
    bm = bmesh.new()
    bm_tube_path(bm, hoop, 0.024, 10)
    for sx in (-1, 1):
        bm_tube_path(bm, [(sx * 0.20, yf, 0.26), (sx * 0.20, yf, 0.585)], 0.022, 10)
        # mounts into the bumper
        bm_tube_path(bm, [(sx * 0.20, yf, 0.35), (sx * 0.20, yf + 0.13, 0.35)], 0.018, 8)
    bm_tube_path(bm, [(-0.33, yf, 0.40), (0.33, yf, 0.40)], 0.018, 8)
    ob = obj("push_bar", bm)
    out.append((ob.name, "black_metal", ob))
    # rubber pads on the uprights
    for sx, side in ((1, "L"), (-1, "R")):
        pad = box(f"push_bar_pad_{side}", (sx * 0.20, yf - 0.028, 0.47), (0.07, 0.02, 0.18), bevel=0.008)
        out.append((pad.name, "rubber", pad))
    return out


def window_seals():
    """Black rubber seals round the side glass (a thin tube along each opening)."""
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        for nm, pts in (("F", P.front_dlo()), ("R", P.rear_dlo())):
            # densify the outline and put it on the surface
            dense = []
            n = len(pts)
            for i in range(n):
                a, b = pts[i], pts[(i + 1) % n]
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                k = max(1, int(L / 0.075))
                for j in range(k):
                    t = j / k
                    dense.append((lerp(a[0], b[0], t), lerp(a[1], b[1], t)))
            p3 = []
            for y, z in dense:
                x, nrm = P.side_x(y, z, sx)
                p3.append((x + sx * 0.002, y, z))
            bm = bmesh.new()
            bm_tube_path(bm, p3, 0.0065, 5, closed=True)
            ob = obj(f"window_seal_{nm}_{side}", bm)
            out.append((ob.name, "rubber", ob))
    return out


def body_mouldings():
    """Black rub strips along the doors and the bumpers' top edges (90s style)."""
    out = []
    zc = 0.505
    for sx, side in ((1, "L"), (-1, "R")):
        for nm, y0, y1 in (("F", P.FD_FRONT + 0.03, P.B_LINE - 0.012), ("R", P.B_LINE + 0.012, 0.95)):
            pts = []
            for y in frange(y0, y1, 12):
                x, n = P.side_x(y, zc, sx)
                pts.append((x, y, zc))
            bm = bmesh.new()
            # a flat strip: 4.5 cm tall, 8 mm proud
            prof = [(-0.0225, 0.0), (-0.0225, 0.006), (-0.012, 0.009), (0.012, 0.009), (0.0225, 0.006), (0.0225, 0.0)]
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
            out.append((ob.name, "black_trim", ob))
    return out


def fender_flares():
    """Bolt-on black overfenders round all four arches, with bolts."""
    out = []
    for axle, an in ((B.AXLE_F, "F"), (B.AXLE_R, "R")):
        for sx, side in ((1, "L"), (-1, "R")):
            R0 = B.ARCH_R - 0.004
            prof = [(R0, 0.0), (R0, 0.045), (R0 + 0.02, 0.052), (R0 + 0.07, 0.020), (R0 + 0.085, 0.002)]
            # angle range: from the rocker at the front to the rocker at the back
            angs = []
            for t in frange(0.0, 1.0, 34):
                a = lerp(math.radians(-8), math.radians(188), t)
                angs.append(a)
            rings = []
            bm = bmesh.new()
            for a in angs:
                ring = []
                for r, o in prof:
                    y = axle + r * math.cos(a)
                    z = B.WHEEL_R + r * math.sin(a)
                    x, n = P.side_x(y, max(z, 0.30), sx)
                    ring.append(bm.verts.new((x + sx * (o - 0.002), y, z)))
                rings.append(ring)
            for A, Bq in zip(rings, rings[1:]):
                for k in range(len(prof) - 1):
                    bm.faces.new((A[k], A[k + 1], Bq[k + 1], Bq[k]))
                # back face (against the body) closes the part
                bm.faces.new((A[-1], A[0], Bq[0], Bq[-1]))
            bm.faces.new(rings[0])
            bm.faces.new(list(reversed(rings[-1])))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            ob = obj(f"flare_{an}{side}", bm)
            out.append((ob.name, "black_trim", ob))
            bm = bmesh.new()
            for t in frange(0.08, 0.92, 7):
                a = lerp(math.radians(-8), math.radians(188), t)
                r = R0 + 0.045
                y = axle + r * math.cos(a)
                z = B.WHEEL_R + r * math.sin(a)
                x, n = P.side_x(y, max(z, 0.30), sx)
                bm_cyl(bm, (x + sx * 0.040, y, z), 0.008, 0.012, seg=6, axis="X")
            ob = obj(f"flare_bolts_{an}{side}", bm)
            out.append((ob.name, "chrome", ob))
    return out


def mirrors():
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        y, z = -0.66, P.z_belt(-0.66) + 0.075
        x, n = P.side_x(y, z - 0.07, sx)
        # stalk
        st = box(f"mirror_stalk_{side}", (x + sx * 0.035, y + 0.01, z - 0.045), (0.075, 0.04, 0.045), bevel=0.008)
        out.append((st.name, "black_trim", st))
        # housing: a soft wedge, glass on the rear face
        bm = bmesh.new()
        bm_box(bm, (x + sx * 0.135, y, z), (0.19, 0.085, 0.115))
        for v in bm.verts:
            if v.co.y < y:  # front of the housing is rounder / narrower
                v.co.z = z + (v.co.z - z) * 0.85
                v.co.x = x + sx * 0.135 + (v.co.x - (x + sx * 0.135)) * 0.9
        hob = obj(f"mirror_housing_{side}", bm)
        mods(hob, bevel=0.018, seg=3)
        out.append((hob.name, "paint", hob))
        g = box(f"mirror_glass_{side}", (x + sx * 0.135, y + 0.044, z), (0.165, 0.004, 0.092), bevel=0.012, seg=3)
        out.append((g.name, "mirror", g))
    return out


def door_handles():
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        for nm, y in (("F", P.B_LINE - 0.17), ("R", 0.86)):
            z = P.z_belt(y) - 0.075
            x, n = P.side_x(y, z, sx)
            # recessed pocket plate + pull bar
            pl = box(f"handle_pocket_{nm}{side}", (x - sx * 0.002, y, z), (0.008, 0.17, 0.05), bevel=0.012, seg=2)
            out.append((pl.name, "black_trim", pl))
            hb = box(f"handle_{nm}{side}", (x + sx * 0.010, y, z + 0.004), (0.016, 0.145, 0.024), bevel=0.007, seg=2)
            out.append((hb.name, "chrome", hb))
            if nm == "F":
                bm = bmesh.new()
                bm_cyl(bm, (x + sx * 0.006, y + 0.105, z + 0.004), 0.009, 0.012, seg=12, axis="X")
                lk = obj(f"door_lock_{side}", bm)
                out.append((lk.name, "chrome", lk))
    return out


def wipers():
    out = []
    for k, (px, length) in enumerate(((0.26, 0.58), (-0.20, 0.50))):
        yb = -0.745
        z0, n = P.top_z(px, yb)
        pts = []
        for t in frange(0, 1, 10):
            x = px - t * length * (1 if px > 0 else 0.9) * (1 if k == 0 else 1) - (0 if k == 0 else 0)
            x = px - t * length
            y = yb + 0.03 * t
            z, n = P.top_z(x, y)
            pts.append((x, y, z + 0.018))
        bm = bmesh.new()
        bm_tube_path(bm, pts, 0.006, 6)
        # pivot cap
        bm_cyl(bm, (px, yb - 0.01, z0 + 0.02), 0.018, 0.03, seg=12, axis="Z")
        arm = obj(f"wiper_arm_{k}", bm)
        out.append((arm.name, "black_metal", arm))
        # the blade lies on the glass along the arm
        bpts = []
        for t in frange(0.15, 1.0, 10):
            x = px - t * length
            y = yb + 0.03 * t + 0.012
            z, n = P.top_z(x, y)
            bpts.append((x, y, z + 0.009))
        bm = bmesh.new()
        bm_tube_path(bm, bpts, 0.0055, 5)
        bl = obj(f"wiper_blade_{k}", bm)
        out.append((bl.name, "rubber", bl))
    # cowl vent panel between hood and windshield
    pts = []
    zc, n = P.top_z(0.0, -0.80)
    cw = box("cowl_panel", (0, -0.795, zc + 0.002), (1.30, 0.06, 0.012), bevel=0.004,
             rot=Matrix.Rotation(math.radians(-12), 4, "X"))
    out.append((cw.name, "black_trim", cw))
    return out


def plates():
    out = []
    yf = P.front_face_y(0.0, 0.42) + 0.014
    pf = box("plate_F", (0, yf - 0.004, 0.4175), (0.33, 0.006, 0.165), bevel=0.003)
    out.append((pf.name, "plate", pf))
    yr = P.rear_face_y(0.0, 0.42) - 0.014
    pr = box("plate_R", (0, yr + 0.004, 0.4175), (0.33, 0.006, 0.165), bevel=0.003)
    out.append((pr.name, "plate", pr))
    # plate lamp above the rear plate
    pl = box("plate_lamp", (0, P.rear_face_y(0.0, 0.52) - 0.002, 0.522), (0.10, 0.012, 0.012), bevel=0.003)
    out.append((pl.name, "emitter_reverse", pl))
    return out


def exhaust():
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        yr = P.rear_face_y(sx * 0.52, 0.25)
        prof = [(0.033, -0.10), (0.033, 0.02), (0.039, 0.025), (0.040, -0.10)]
        tip = lathe(f"exhaust_tip_{side}", [(0.040, -0.14), (0.040, 0.012), (0.036, 0.018), (0.031, 0.012), (0.031, -0.06)],
                    (sx * 0.52, yr, 0.25), "Y", 20)
        out.append((tip.name, "exhaust", tip))
    # the pipe run under the car, a silencer box and the cat
    bm = bmesh.new()
    path = [(0.0, -1.20, 0.205), (0.0, -0.20, 0.205), (0.05, 0.60, 0.205), (0.30, 1.35, 0.215), (0.45, 1.70, 0.23)]
    bm_tube_path(bm, path, 0.026, 10)
    for sx in (-1, 1):
        bm_tube_path(bm, [(0.45 if sx > 0 else 0.30, 1.75, 0.235), (sx * 0.52, 1.98, 0.25), (sx * 0.52, P.rear_face_y(sx * 0.52, 0.25) - 0.13, 0.25)], 0.024, 10)
    pipe = obj("exhaust_pipe", bm)
    out.append((pipe.name, "underbody_metal", pipe))
    sil = box("silencer", (0.0, 1.78, 0.235), (0.80, 0.30, 0.13), bevel=0.04, seg=3)
    out.append((sil.name, "underbody_metal", sil))
    cat = box("catalyst", (0.0, -0.55, 0.215), (0.16, 0.36, 0.09), bevel=0.03, seg=3)
    out.append((cat.name, "underbody_metal", cat))
    return out


def roof_gear():
    """Light bar on brackets, whip antenna, comms puck, A-pillar spotlight."""
    out = []
    yb = 0.30
    zr, n = P.top_z(0.0, yb)
    zb = zr + 0.028
    # feet / brackets at the roof edges
    for sx, side in ((1, "L"), (-1, "R")):
        x = sx * 0.56
        z0, n = P.top_z(x, yb)
        ft = box(f"lightbar_foot_{side}", (x, yb, (z0 + zb) / 2), (0.06, 0.16, zb - z0 + 0.02), bevel=0.008)
        out.append((ft.name, "black_metal", ft))
    base = box("lightbar_base", (0, yb, zb + 0.012), (1.26, 0.28, 0.024), bevel=0.01, seg=2)
    out.append((base.name, "black_trim", base))
    # lens domes: left red, right blue (the security livery); a centre module with a sign
    for sx, side, grp in ((1, "L", "lightbar_lens_red"), (-1, "R", "lightbar_lens_blue")):
        bm = bmesh.new()
        bm_box(bm, (sx * 0.34, yb, zb + 0.058), (0.52, 0.24, 0.07))
        ln = obj(f"lightbar_lens_{side}", bm)
        mods(ln, bevel=0.03, seg=4)
        out.append((ln.name, grp, ln))
        for i in range(4):
            em = box(f"lightbar_led_{side}{i}", (sx * (0.15 + i * 0.12), yb, zb + 0.05), (0.08, 0.17, 0.035))
            out.append((em.name, "emitter_red" if sx > 0 else "emitter_blue", em))
    cm = box("lightbar_center", (0, yb, zb + 0.06), (0.14, 0.24, 0.075), bevel=0.012, seg=3)
    out.append((cm.name, "lightbar_center", cm))
    # whip antenna on the trunk lid + base
    zt, n = P.top_z(-0.42, 1.98)
    bm = bmesh.new()
    bm_cyl(bm, (-0.42, 1.98, zt + 0.012), 0.016, 0.024, seg=12)
    bm_tube_path(bm, [(-0.42, 1.98, zt + 0.02), (-0.42, 2.00, zt + 0.45), (-0.42, 2.04, zt + 0.86)], 0.0025, 5)
    ant = obj("antenna_whip", bm)
    out.append((ant.name, "black_metal", ant))
    # comms puck on the roof
    zp, n = P.top_z(0.0, 0.78)
    puck = lathe("antenna_puck", [(0.0, 0.0), (0.055, 0.0), (0.05, 0.02), (0.03, 0.04), (0.0, 0.045)], (0, 0.78, zp - 0.002), "Z", 20)
    out.append((puck.name, "black_trim", puck))
    # A-pillar spotlight (driver's side, right-hand drive: -X)
    x, n = P.side_x(-0.42, P.z_belt(-0.42) + 0.08, -1)
    spot_c = Vector((x - 0.07, -0.47, P.z_belt(-0.42) + 0.12))
    bm = bmesh.new()
    bm_tube_path(bm, [(x - 0.005, -0.40, P.z_belt(-0.42) + 0.05), (x - 0.07, -0.42, P.z_belt(-0.42) + 0.08), tuple(spot_c + Vector((0, 0.04, -0.02)))], 0.010, 8)
    sb = obj("spotlight_bracket", bm)
    out.append((sb.name, "black_metal", sb))
    sp = lathe("spotlight_body", [(0.0, -0.06), (0.040, -0.06), (0.052, 0.0), (0.056, 0.03), (0.056, 0.035)], tuple(spot_c), "Y", 20, sign=-1)
    out.append((sp.name, "black_trim", sp))
    sl = lathe("spotlight_lens", [(0.0, 0.04), (0.052, 0.035)], tuple(spot_c), "Y", 20, sign=-1)
    out.append((sl.name, "emitter_head", sl))
    return out


def mudflaps():
    out = []
    for axle, an in ((B.AXLE_F, "F"), (B.AXLE_R, "R")):
        for sx, side in ((1, "L"), (-1, "R")):
            y = axle + B.ARCH_R + 0.012
            zt = 0.33
            x, n = P.side_x(y + 0.02, zt, sx)
            fl = box(f"mudflap_{an}{side}", (x - sx * 0.12, y, (zt + 0.12) / 2), (0.19, 0.006, zt - 0.12), bevel=0.002,
                     rot=Matrix.Rotation(math.radians(6), 4, "X"))
            out.append((fl.name, "rubber", fl))
    return out


def underbody():
    out = []
    # flat tray with a centre tunnel and a fuel tank
    tray = box("underbody_tray", (0, 0.05, 0.184), (1.40, 3.50, 0.012), bevel=0.01)
    out.append((tray.name, "underbody", tray))
    tun = box("underbody_tunnel", (0, -0.20, 0.215), (0.22, 2.4, 0.07), bevel=0.03, seg=3)
    out.append((tun.name, "underbody", tun))
    tank = box("fuel_tank", (0.0, 1.20, 0.215), (1.0, 0.45, 0.07), bevel=0.03, seg=3)
    out.append((tank.name, "underbody_metal", tank))
    # front and rear subframe crossmembers
    for y in (B.AXLE_F + 0.05, B.AXLE_R - 0.05):
        cm = box(f"crossmember_{'F' if y < 0 else 'R'}", (0, y, 0.24), (1.05, 0.10, 0.07), bevel=0.012)
        out.append((cm.name, "underbody_metal", cm))
    return out


def wheel_wells():
    """Arch liners (a closed drum behind each arch) so you can't see into the car."""
    out = []
    for axle, an in ((B.AXLE_F, "F"), (B.AXLE_R, "R")):
        for sx, side in ((1, "L"), (-1, "R")):
            r = B.ARCH_R - 0.006
            bm = bmesh.new()
            seg = 28
            a0, a1 = math.radians(-12), math.radians(192)
            inner_x, outer_x = sx * 0.53, sx * 0.86
            ringO, ringI = [], []
            for k in range(seg + 1):
                a = lerp(a0, a1, k / seg)
                y = axle + r * math.cos(a)
                z = B.WHEEL_R + r * math.sin(a)
                ringO.append(bm.verts.new((outer_x, y, z)))
                ringI.append(bm.verts.new((inner_x, y, z)))
            for k in range(seg):
                bm.faces.new((ringO[k], ringO[k + 1], ringI[k + 1], ringI[k]))
            # inner wall (half disc)
            c = bm.verts.new((inner_x, axle, B.WHEEL_R - 0.08))
            for k in range(seg):
                bm.faces.new((ringI[k], ringI[k + 1], c))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            # normals should face the wheel (into the drum)
            for f in bm.faces:
                cen = f.calc_center_median()
                to_axis = Vector((sx * 0.70, axle, B.WHEEL_R)) - cen
                if f.normal.dot(to_axis) < 0:
                    f.normal_flip()
            ob = obj(f"wheel_well_{an}{side}", bm)
            out.append((ob.name, "underbody", ob))
    return out


def suspension():
    """Visible in the arches: strut (damper + coil spring), top mount, lower arm, knuckle, driveshaft."""
    out = []
    for axle, an in ((B.AXLE_F, "F"), (B.AXLE_R, "R")):
        for sx, side in ((1, "L"), (-1, "R")):
            hub = Vector((sx * 0.64, axle, B.WHEEL_R))
            top = Vector((sx * 0.60, axle + (0.05 if an == "F" else -0.05), B.WHEEL_R + 0.36))
            bot = hub + Vector((-sx * 0.01, 0, 0.09))
            # damper body + rod
            bm = bmesh.new()
            d = (top - bot)
            mid = bot + d * 0.55
            bm_tube_path(bm, [tuple(bot), tuple(mid)], 0.026, 10)
            bm_tube_path(bm, [tuple(mid), tuple(top)], 0.010, 8)
            dm = obj(f"damper_{an}{side}", bm)
            out.append((dm.name, "suspension", dm))
            # coil spring: a helix around the upper damper
            pts = []
            turns = 5.5
            n = int(turns * 7)
            axis = d.normalized()
            u = axis.cross(Vector((0, 1, 0))).normalized()
            v = axis.cross(u)
            s0 = bot + d * 0.38
            for i in range(n + 1):
                t = i / n
                a = TAU * turns * t
                p = s0 + d * 0.55 * t + (u * math.cos(a) + v * math.sin(a)) * 0.058
                pts.append(tuple(p))
            bm = bmesh.new()
            bm_tube_path(bm, pts, 0.0075, 4)
            sp = obj(f"spring_{an}{side}", bm)
            out.append((sp.name, "spring", sp))
            # lower control arm (A-arm): two tubes to the subframe
            bm = bmesh.new()
            for dy in (-0.16, 0.16):
                bm_tube_path(bm, [tuple(hub + Vector((-sx * 0.02, 0, -0.10))), (sx * 0.30, axle + dy, B.WHEEL_R - 0.10)], 0.016, 8)
            arm = obj(f"control_arm_{an}{side}", bm)
            out.append((arm.name, "suspension", arm))
            # knuckle / hub carrier
            kn = box(f"knuckle_{an}{side}", tuple(hub + Vector((-sx * 0.02, 0, 0))), (0.04, 0.10, 0.20), bevel=0.012)
            out.append((kn.name, "suspension", kn))
            # driveshaft
            bm = bmesh.new()
            bm_tube_path(bm, [tuple(hub + Vector((-sx * 0.03, 0, 0))), (sx * 0.12, axle, B.WHEEL_R - 0.02)], 0.017, 8)
            ds = obj(f"driveshaft_{an}{side}", bm)
            out.append((ds.name, "underbody_metal", ds))
    return out


# ------------------------------------------------------------------ interior (right-hand drive)

DRIVER_X = -0.37


def seat(name, x, y, z, w=0.50, back_h=0.62, recline=16, bench=False):
    out = []
    cush = box(f"{name}_cushion", (x, y, z), (w, 0.50, 0.11), bevel=0.04, seg=3)
    out.append((cush.name, "interior_fabric", cush))
    rot = Matrix.Rotation(math.radians(-recline), 4, "X")
    bc = Vector((x, y + 0.24, z + 0.05 + back_h / 2))
    bk = box(f"{name}_back", tuple(bc), (w, 0.11, back_h), bevel=0.04, seg=3)
    # rotate about the hinge (rear of the cushion)
    hinge = Vector((x, y + 0.22, z + 0.05))
    bk.data.transform(Matrix.Translation(hinge) @ rot @ Matrix.Translation(-hinge))
    out.append((bk.name, "interior_fabric", bk))
    if not bench:
        # side bolsters on the backrest and a headrest on two posts
        hr_c = hinge + rot @ Vector((0, 0.03, back_h + 0.12))
        hr = box(f"{name}_headrest", tuple(hr_c), (0.26, 0.09, 0.16), bevel=0.035, seg=3, rot=None)
        hr.data.transform(Matrix.Translation(hr_c) @ rot @ Matrix.Translation(-hr_c))
        out.append((hr.name, "interior_fabric", hr))
        bm = bmesh.new()
        for dx in (-0.07, 0.07):
            a = hinge + rot @ Vector((dx, 0.03, back_h - 0.02))
            b = hinge + rot @ Vector((dx, 0.03, back_h + 0.06))
            bm_tube_path(bm, [tuple(a + Vector((x * 0, 0, 0))), tuple(b)], 0.006, 6)
        po = obj(f"{name}_posts", bm)
        po.data.transform(Matrix.Identity(4))
        out.append((po.name, "chrome", po))
        # seat base / runners
        rb = box(f"{name}_base", (x, y, z - 0.10), (w * 0.8, 0.42, 0.10), bevel=0.01)
        out.append((rb.name, "interior_dark", rb))
    else:
        for sx in (-1, 1):
            hr_c = hinge + rot @ Vector((sx * 0.38, 0.02, back_h + 0.08))
            hr = box(f"{name}_headrest_{'L' if sx > 0 else 'R'}", tuple(hr_c), (0.24, 0.08, 0.13), bevel=0.03, seg=3)
            hr.data.transform(Matrix.Translation(hr_c) @ rot @ Matrix.Translation(-hr_c))
            out.append((hr.name, "interior_fabric", hr))
    return out


def interior():
    out = []
    zf = 0.235
    # carpeted floor (with the tunnel hump) and the firewall
    fl = box("floor_carpet", (0, 0.30, zf), (1.58, 2.35, 0.02))
    out.append((fl.name, "interior_carpet", fl))
    hump = box("floor_tunnel", (0, 0.05, zf + 0.06), (0.24, 1.70, 0.12), bevel=0.04, seg=3)
    out.append((hump.name, "interior_carpet", hump))
    # dashboard: a main slab, a top pad running to the windshield, binnacle and glovebox
    ydb = -0.56
    dash = box("dash_lower", (0, ydb, 0.68), (1.50, 0.30, 0.28), bevel=0.03, seg=3)
    out.append((dash.name, "interior_plastic", dash))
    pad = box("dash_top", (0, ydb - 0.07, 0.855), (1.52, 0.42, 0.07), bevel=0.03, seg=3,
              rot=Matrix.Rotation(math.radians(8), 4, "X"))
    out.append((pad.name, "interior_dark", pad))
    binn = box("dash_binnacle", (DRIVER_X, ydb + 0.10, 0.905), (0.40, 0.14, 0.10), bevel=0.035, seg=3)
    out.append((binn.name, "interior_dark", binn))
    gauges = box("dash_gauges", (DRIVER_X, ydb + 0.168, 0.885), (0.34, 0.004, 0.07), bevel=0.01)
    out.append((gauges.name, "screen", gauges))
    # centre stack + radio + climate vents
    stack = box("center_stack", (0, ydb + 0.10, 0.66), (0.26, 0.16, 0.30), bevel=0.02)
    out.append((stack.name, "interior_plastic", stack))
    radio = box("radio", (0, ydb + 0.183, 0.72), (0.19, 0.006, 0.055), bevel=0.004)
    out.append((radio.name, "screen", radio))
    for sx in (-1, 1):
        v = box(f"vent_{'L' if sx > 0 else 'R'}", (sx * 0.60, ydb + 0.152, 0.79), (0.14, 0.006, 0.05), bevel=0.006)
        out.append((v.name, "black_trim", v))
    # centre console with shifter and handbrake
    con = box("center_console", (0, -0.05, 0.39), (0.22, 0.70, 0.18), bevel=0.025, seg=3)
    out.append((con.name, "interior_plastic", con))
    bm = bmesh.new()
    bm_tube_path(bm, [(0, -0.22, 0.48), (0, -0.24, 0.60)], 0.008, 8)
    bm_sphere(bm, (0, -0.245, 0.615), 0.025, 12, 8)
    sh = obj("shifter", bm)
    out.append((sh.name, "interior_dark", sh))
    hb = box("handbrake", (0.02, 0.05, 0.50), (0.035, 0.24, 0.035), bevel=0.012, rot=Matrix.Rotation(math.radians(14), 4, "X"))
    out.append((hb.name, "interior_dark", hb))
    # security terminal (MDT) on a stand in front of the console
    st = box("terminal_stand", (0.02, -0.33, 0.62), (0.03, 0.03, 0.22))
    out.append((st.name, "black_metal", st))
    tm = box("terminal", (0.02, -0.30, 0.78), (0.30, 0.025, 0.20), bevel=0.01,
             rot=Matrix.Rotation(math.radians(-20), 4, "X"))
    out.append((tm.name, "interior_dark", tm))
    scr = box("terminal_screen", (0.02, -0.285, 0.784), (0.27, 0.004, 0.17), rot=Matrix.Rotation(math.radians(-20), 4, "X"))
    out.append((scr.name, "screen", scr))
    # steering wheel (rim, 3 spokes, hub) on its column
    wc = Vector((DRIVER_X, -0.33, 0.86))
    tilt = Matrix.Rotation(math.radians(-62), 4, "X")
    bm = bmesh.new()
    rim = []
    for k in range(32):
        a = TAU * k / 32
        rim.append(tuple(wc + tilt @ Vector((0.185 * math.cos(a), 0, 0.185 * math.sin(a)))))
    bm_tube_path(bm, rim, 0.016, 8, closed=True)
    rob = obj("steering_rim", bm)
    out.append((rob.name, "interior_leather", rob))
    bm = bmesh.new()
    for a in (0, math.pi, -math.pi / 2):
        e = wc + tilt @ Vector((0.17 * math.cos(a), 0, 0.17 * math.sin(a)))
        bm_tube_path(bm, [tuple(wc), tuple(e)], 0.012, 6)
    bm_cyl(bm, tuple(wc + tilt @ Vector((0, 0.015, 0))), 0.06, 0.04, seg=16, axis="Y")
    sp = obj("steering_hub", bm)
    sp.data.transform(Matrix.Identity(4))
    out.append((sp.name, "interior_dark", sp))
    bm = bmesh.new()
    bm_tube_path(bm, [tuple(wc + tilt @ Vector((0, 0.04, 0))), (DRIVER_X, -0.52, 0.80)], 0.035, 10)
    col = obj("steering_column", bm)
    out.append((col.name, "interior_dark", col))
    # seats
    out += seat("seat_FR", DRIVER_X, 0.03, 0.40)
    out += seat("seat_FL", -DRIVER_X, 0.03, 0.40)
    out += seat("seat_rear", 0.0, 0.78, 0.38, w=1.30, back_h=0.56, recline=22, bench=True)
    # security partition behind the front seats: frame + bars
    bm = bmesh.new()
    yp = 0.40
    fr = [(-0.72, yp, 0.62), (-0.66, yp, 1.24), (0.66, yp, 1.24), (0.72, yp, 0.62)]
    bm_tube_path(bm, fr + [(-0.72, yp, 0.62)], 0.012, 6)
    for x in frange(-0.60, 0.60, 9):
        bm_tube_path(bm, [(x, yp, 0.63), (x, yp, 1.23)], 0.005, 5)
    for z in (0.80, 1.00):
        bm_tube_path(bm, [(-0.70, yp, z), (0.70, yp, z)], 0.005, 5)
    pt = obj("partition", bm)
    out.append((pt.name, "black_metal", pt))
    # rear parcel shelf with speakers
    ps = box("parcel_shelf", (0, 1.36, 0.93), (1.40, 0.40, 0.02), rot=Matrix.Rotation(math.radians(-4), 4, "X"))
    out.append((ps.name, "interior_dark", ps))
    # rear-view mirror
    rv = box("rearview_mirror", (0, -0.12, 1.25), (0.24, 0.03, 0.065), bevel=0.012, seg=2)
    out.append((rv.name, "interior_dark", rv))
    return out


def door_cards(pieces):
    """Inner door trims: the door skin below the belt, pushed inward and flipped, plus an armrest."""
    out = []
    for nm in ("door_FL", "door_FR", "door_RL", "door_RR"):
        d = pieces[nm]
        sx = 1 if nm.endswith("L") else -1
        bm = bmesh.new()
        bm.from_mesh(d.data)
        bm.normal_update()
        kill = [f for f in bm.faces if f.calc_center_median().z > P.z_belt(f.calc_center_median().y) - 0.02
                or f.calc_center_median().z < P.DOOR_BOTTOM + 0.03 or abs(f.normal.x) < 0.5]
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        for v in bm.verts:
            v.co.x -= sx * 0.075
        for f in bm.faces:
            f.normal_flip()
        ys = [v.co.y for v in bm.verts]
        card = obj(f"door_card_{nm[-2:]}", bm)
        m = card.modifiers.new("dec", "DECIMATE")
        m.ratio = 0.3
        m = card.modifiers.new("sol", "SOLIDIFY")
        m.thickness = 0.012
        apply_mods(card)
        out.append((card.name, "interior_plastic", card))
        if ys:
            y0, y1 = min(ys), max(ys)
            x, n = P.side_x((y0 + y1) / 2, 0.62, sx)
            ar = box(f"armrest_{nm[-2:]}", (x - sx * 0.125, (y0 + y1) / 2 + 0.04, 0.60), (0.06, (y1 - y0) * 0.55, 0.05), bevel=0.015)
            out.append((ar.name, "interior_leather", ar))
    return out


def headliner(shell):
    bm = bmesh.new()
    bm.from_mesh(shell.data)
    bm.normal_update()
    kill = [f for f in bm.faces if not (f.calc_center_median().z > 1.22 and -0.25 < f.calc_center_median().y < 1.05 and f.normal.z > 0.6)]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    for v in bm.verts:
        v.co.z -= 0.035
    for f in bm.faces:
        f.normal_flip()
    ob = obj("headliner", bm)
    return [(ob.name, "interior_fabric", ob)]
