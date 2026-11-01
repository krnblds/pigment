"""Under-car kits: arch liners (wheel wells) and suspension corners. The flat tray, tunnel,
tank and crossmembers are plain box lists (trim.boxes)."""
import math

import bmesh
from mathutils import Vector

from . import body as B
from . import cfg
from .geom import bm_tube_path, lerp
from .shapes import SIDES, TAU, box, obj


def wheel_wells(p):
    """Arch liners (a closed drum behind each arch) so you can't see into the body.
    p: {inner, outer, a0, a1}"""
    out = []
    for axle, an in zip(cfg.V.axles, "FR"):
        for sx, side in SIDES:
            r = cfg.V.arch_r - 0.006
            bm = bmesh.new()
            seg = 28
            a0, a1 = math.radians(p.get("a0", -12)), math.radians(p.get("a1", 192))
            inner_x, outer_x = sx * p.inner, sx * p.outer
            ringO, ringI = [], []
            for k in range(seg + 1):
                a = lerp(a0, a1, k / seg)
                y = axle + r * math.cos(a)
                z = B.arch_z() + r * math.sin(a)
                ringO.append(bm.verts.new((outer_x, y, z)))
                ringI.append(bm.verts.new((inner_x, y, z)))
            for k in range(seg):
                bm.faces.new((ringO[k], ringO[k + 1], ringI[k + 1], ringI[k]))
            c = bm.verts.new((inner_x, axle, B.arch_z() - 0.08))
            for k in range(seg):
                bm.faces.new((ringI[k], ringI[k + 1], c))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            for f in bm.faces:
                cen = f.calc_center_median()
                to_axis = Vector((sx * p.get("hub_x", 0.70), axle, B.arch_z())) - cen
                if f.normal.dot(to_axis) < 0:
                    f.normal_flip()
            ob = obj(f"wheel_well_{an}{side}", bm)
            out.append((ob.name, "underbody", ob))
    return out


def suspension(p):
    """Strut (damper + coil spring), lower A-arm, knuckle and driveshaft at every corner.
    p: {hub_x, top_x, top_dz, top_dy, arm_x, arm_dy, shaft_x, spring_r, leaf: [axles with leaf springs]}"""
    out = []
    for axle, an in zip(cfg.V.axles, "FR"):
        for sx, side in SIDES:
            hub = Vector((sx * p.get("hub_x", 0.70), axle, B.arch_z()))
            if an in p.get("leaf", ""):
                # a leaf-spring beam axle (vans, trucks): spring pack along y, U-bolts, damper
                bm = bmesh.new()
                L = p.get("leaf_len", 1.1)
                for i in range(p.get("leaves", 4)):
                    sag = 0.05 - i * 0.008
                    pts = [(sx * (p.get("hub_x", 0.70) - 0.12), axle + L / 2 * t, B.arch_z() - 0.07 - i * 0.012 + sag * (1 - t * t))
                           for t in [x / 6 - 1 for x in range(13)]]
                    bm_tube_path(bm, pts, 0.008, 4)
                lf = obj(f"leaf_spring_{an}{side}", bm)
                out.append((lf.name, "suspension", lf))
                bm = bmesh.new()
                top = hub + Vector((-sx * 0.16, 0.12, p.get("top_dz", 0.36) * 0.8))
                bm_tube_path(bm, [tuple(hub + Vector((-sx * 0.16, 0.05, -0.06))), tuple(top)], 0.022, 10)
                dm = obj(f"damper_{an}{side}", bm)
                out.append((dm.name, "suspension", dm))
                kn = box(f"knuckle_{an}{side}", tuple(hub + Vector((-sx * 0.06, 0, 0))), (0.12, 0.12, 0.12), bevel=0.02)
                out.append((kn.name, "suspension", kn))
                continue
            top = Vector((sx * p.get("top_x", 0.64), axle + (p.get("top_dy", 0.05) if an == "F" else -p.get("top_dy", 0.05)),
                          B.arch_z() + p.get("top_dz", 0.36)))
            bot = hub + Vector((-sx * 0.01, 0, 0.09))
            bm = bmesh.new()
            d = (top - bot)
            mid = bot + d * 0.55
            bm_tube_path(bm, [tuple(bot), tuple(mid)], 0.026, 10)
            bm_tube_path(bm, [tuple(mid), tuple(top)], 0.010, 8)
            dm = obj(f"damper_{an}{side}", bm)
            out.append((dm.name, "suspension", dm))
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
                q = s0 + d * 0.55 * t + (u * math.cos(a) + v * math.sin(a)) * p.get("spring_r", 0.058)
                pts.append(tuple(q))
            bm = bmesh.new()
            bm_tube_path(bm, pts, 0.0075, 4)
            sp = obj(f"spring_{an}{side}", bm)
            out.append((sp.name, "spring", sp))
            bm = bmesh.new()
            for dy in (-p.get("arm_dy", 0.16), p.get("arm_dy", 0.16)):
                bm_tube_path(bm, [tuple(hub + Vector((-sx * 0.02, 0, -0.10))), (sx * p.get("arm_x", 0.30), axle + dy, B.arch_z() - 0.10)], 0.016, 8)
            arm = obj(f"control_arm_{an}{side}", bm)
            out.append((arm.name, "suspension", arm))
            kn = box(f"knuckle_{an}{side}", tuple(hub + Vector((-sx * 0.02, 0, 0))), (0.04, 0.10, 0.20), bevel=0.012)
            out.append((kn.name, "suspension", kn))
            if an in p.get("driven", "FR"):
                bm = bmesh.new()
                bm_tube_path(bm, [tuple(hub + Vector((-sx * 0.03, 0, 0))), (sx * p.get("shaft_x", 0.12), axle, B.arch_z() - 0.02)], 0.017, 8)
                ds = obj(f"driveshaft_{an}{side}", bm)
                out.append((ds.name, "underbody_metal", ds))
    return out


def beam_axle(p):
    """A solid rear axle tube with a differential (vans, trucks, pickups)."""
    out = []
    axle = cfg.V.axles[-1] if p.get("axle", "R") == "R" else cfg.V.axles[0]
    z = B.arch_z()
    bm = bmesh.new()
    hx = p.get("hub_x", 0.70) - 0.06
    bm_tube_path(bm, [(-hx, axle, z), (hx, axle, z)], p.get("r", 0.04), 12)
    ax = obj(f"axle_beam_{p.get('axle', 'R')}", bm)
    out.append((ax.name, "underbody_metal", ax))
    from .shapes import lathe
    diff = lathe(f"differential_{p.get('axle', 'R')}", [(0.0, -0.10), (0.09, -0.08), (0.13, 0.0), (0.11, 0.08), (0.05, 0.12), (0.0, 0.12)],
                 (0.0, axle, z), "Y", 20)
    out.append((diff.name, "underbody_metal", diff))
    return out
