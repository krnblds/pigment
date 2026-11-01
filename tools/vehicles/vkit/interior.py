"""Interior kits (right-hand drive): seats and benches, steering wheel and column, shifter,
door cards cut from the door skins, a headliner from the roof, plus whatever box lists the
spec adds (dash, centre stack, console, floor...: trim.boxes).
"""
import math

import bmesh
from mathutils import Matrix, Vector

from . import cfg
from . import panels as P
from .geom import apply_mods, bm_cyl, bm_sphere, bm_tube_path
from .shapes import TAU, box, obj, rot_x


def seat(p):
    """A bucket seat or a bench. p: {name, x, y, z, w, back_h, recline, bench, depth, headrest}"""
    name, x, y, z = p.name, p.x, p.y, p.z
    w = p.get("w", 0.50)
    back_h = p.get("back_h", 0.62)
    recline = p.get("recline", 16)
    bench = p.get("bench", False)
    dep = p.get("depth", 0.50)
    out = []
    cush = box(f"{name}_cushion", (x, y, z), (w, dep, 0.11), bevel=0.04, seg=3)
    out.append((cush.name, "interior_fabric", cush))
    rot = Matrix.Rotation(math.radians(-recline), 4, "X")
    bc = Vector((x, y + 0.24, z + 0.05 + back_h / 2))
    bk = box(f"{name}_back", tuple(bc), (w, 0.11, back_h), bevel=0.04, seg=3)
    hinge = Vector((x, y + dep / 2 - 0.03, z + 0.05))
    bk.data.transform(Matrix.Translation(hinge) @ rot @ Matrix.Translation(-hinge))
    out.append((bk.name, "interior_fabric", bk))
    if not bench:
        hr_c = hinge + rot @ Vector((0, 0.03, back_h + 0.12))
        hr = box(f"{name}_headrest", tuple(hr_c), (0.26, 0.09, 0.16), bevel=0.035, seg=3)
        hr.data.transform(Matrix.Translation(hr_c) @ rot @ Matrix.Translation(-hr_c))
        out.append((hr.name, "interior_fabric", hr))
        bm = bmesh.new()
        for dx in (-0.07, 0.07):
            a = hinge + rot @ Vector((dx, 0.03, back_h - 0.02))
            b = hinge + rot @ Vector((dx, 0.03, back_h + 0.06))
            bm_tube_path(bm, [tuple(a), tuple(b)], 0.006, 6)
        po = obj(f"{name}_posts", bm)
        out.append((po.name, "chrome", po))
        rb = box(f"{name}_base", (x, y, z - 0.10), (w * 0.8, 0.42, 0.10), bevel=0.01)
        out.append((rb.name, "interior_dark", rb))
        if p.get("bolsters"):
            for sx, sd in ((1, "L"), (-1, "R")):
                bo = box(f"{name}_bolster_{sd}", (x + sx * (w / 2 - 0.04), y + 0.24, z + 0.05 + back_h * 0.4), (0.08, 0.14, back_h * 0.7),
                         bevel=0.035, seg=3)
                bo.data.transform(Matrix.Translation(hinge) @ rot @ Matrix.Translation(-hinge))
                out.append((bo.name, "interior_fabric", bo))
    else:
        hx = p.get("headrest_x", [0.38])
        for k, hxx in enumerate(hx):
            for sx in (-1, 1):
                if hxx == 0 and sx > 0:
                    continue
                hr_c = hinge + rot @ Vector((sx * hxx, 0.02, back_h + 0.08))
                sfx = "L" if sx > 0 else "R"
                nm = f"{name}_headrest_{sfx}" if len(hx) == 1 else f"{name}_headrest_{k}{sfx}"
                hr = box(nm, tuple(hr_c), (0.24, 0.08, 0.13), bevel=0.03, seg=3)
                hr.data.transform(Matrix.Translation(hr_c) @ rot @ Matrix.Translation(-hr_c))
                out.append((hr.name, "interior_fabric", hr))
    return out


def seat_rows(p):
    """Rows of bus / pod seats. p: {name, rows: [[y, [x...]]], z, w, back_h, recline, depth}"""
    out = []
    for i, (y, xs) in enumerate(p.rows):
        for j, x in enumerate(xs):
            q = dict(p)
            q.update(name=f"{p.name}_{i}{j}", x=x, y=y, bench=True, headrest_x=[0.0])
            out += seat(cfg.wrap(q))
    return out


def shifter(p):
    bm = bmesh.new()
    a, b = p.get("a", (0, -0.22, 0.48)), p.get("b", (0, -0.24, 0.60))
    bm_tube_path(bm, [tuple(a), tuple(b)], 0.008, 8)
    bm_sphere(bm, tuple(p.get("knob", (0, -0.245, 0.615))), 0.025, 12, 8)
    sh = obj("shifter", bm)
    return [(sh.name, "interior_dark", sh)]


def steering(p):
    """p: {c: wheel centre, tilt, r, column_end}"""
    out = []
    wc = Vector(p.c)
    tilt = Matrix.Rotation(math.radians(p.get("tilt", -62)), 4, "X")
    r = p.get("r", 0.185)
    bm = bmesh.new()
    rim = []
    for k in range(32):
        a = TAU * k / 32
        rim.append(tuple(wc + tilt @ Vector((r * math.cos(a), 0, r * math.sin(a)))))
    bm_tube_path(bm, rim, 0.016, 8, closed=True)
    rob = obj("steering_rim", bm)
    out.append((rob.name, "interior_leather", rob))
    bm = bmesh.new()
    for a in (0, math.pi, -math.pi / 2):
        e = wc + tilt @ Vector(((r - 0.015) * math.cos(a), 0, (r - 0.015) * math.sin(a)))
        bm_tube_path(bm, [tuple(wc), tuple(e)], 0.012, 6)
    bm_cyl(bm, tuple(wc + tilt @ Vector((0, 0.015, 0))), 0.06, 0.04, seg=16, axis="Y")
    sp = obj("steering_hub", bm)
    out.append((sp.name, "interior_dark", sp))
    bm = bmesh.new()
    bm_tube_path(bm, [tuple(wc + tilt @ Vector((0, 0.04, 0))), tuple(p.column_end)], 0.035, 10)
    col = obj("steering_column", bm)
    out.append((col.name, "interior_dark", col))
    return out


def door_cards(pieces, p):
    """Inner door trims: the door skin below the belt, pushed inward and flipped, plus an armrest.
    p: {inset, armrest_z, ray_z}"""
    out = []
    for d in cfg.V.panels.doors:
        for side in "LR":
            nm = f"door_{d.name}{side}"
            if nm not in pieces:
                continue
            dob = pieces[nm]
            sx = 1 if side == "L" else -1
            bm = bmesh.new()
            bm.from_mesh(dob.data)
            bm.normal_update()
            db = d.get("bottom", P.door_bottom())
            kill = [f for f in bm.faces if f.calc_center_median().z > P.z_belt(f.calc_center_median().y) - 0.02
                    or f.calc_center_median().z < db + 0.03 or abs(f.normal.x) < 0.5]
            bmesh.ops.delete(bm, geom=kill, context="FACES")
            for v in bm.verts:
                v.co.x -= sx * p.get("inset", 0.075)
            for f in bm.faces:
                f.normal_flip()
            ys = [v.co.y for v in bm.verts]
            card = obj(f"door_card_{d.name}{side}", bm)
            m = card.modifiers.new("dec", "DECIMATE")
            m.ratio = 0.3
            m = card.modifiers.new("sol", "SOLIDIFY")
            m.thickness = 0.012
            apply_mods(card)
            out.append((card.name, "interior_plastic", card))
            if ys and p.get("armrest", True):
                y0, y1 = min(ys), max(ys)
                x, n = P.side_x((y0 + y1) / 2, p.get("ray_z", 0.62), sx)
                ar = box(f"armrest_{d.name}{side}", (x - sx * 0.125, (y0 + y1) / 2 + 0.04, p.get("armrest_z", 0.60)),
                         (0.06, (y1 - y0) * 0.55, 0.05), bevel=0.015)
                out.append((ar.name, "interior_leather", ar))
    return out


def headliner(shell, p):
    """The roof skin inside the cabin, dropped and flipped. p: {z_min, y0, y1, drop}"""
    bm = bmesh.new()
    bm.from_mesh(shell.data)
    bm.normal_update()
    kill = [f for f in bm.faces if not (f.calc_center_median().z > p.z_min and p.y0 < f.calc_center_median().y < p.y1
                                        and f.normal.z > 0.6)]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    for v in bm.verts:
        v.co.z -= p.get("drop", 0.035)
    for f in bm.faces:
        f.normal_flip()
    ob = obj("headliner", bm)
    return [(ob.name, "interior_fabric", ob)]
