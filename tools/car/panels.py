"""Cut the subdivided body shell into real panels.

Wheel arches, window openings (DLO), lamp and grille apertures are boolean
differences; shut lines are 4 mm thin cutters whose closed loops separate the
doors, hood, trunk lid, bumpers and fuel door into their own connected
pieces. Every piece then gets a short inward flange along its cut edges so
the gaps have depth.
"""
import math

import bmesh
import bpy
from mathutils import Vector

import body as B
from carlib import (apply_mods, bm_box, bm_cyl, bm_gap_cutter, bm_obj, bm_prism, boolean, copy_obj, cut, delete, open_cuts,
                    rounded_rect)

GAP = 0.0045


def hs(y):
    return B.half_section(y)


def z_roof(y):
    return hs(y)[B.P_ROOF][1]


def z_belt(y):
    return hs(y)[B.P_SHOULDER][1]


def z_gbase(y):
    return hs(y)[B.P_GBASE][1]


def w_roof(y):
    return hs(y)[B.P_ROOF][0]


def w_shoulder(y):
    return hs(y)[B.P_SHOULDER][0]


def frange(a, b, n):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


# ------------------------------------------------------------------ outlines (side view = (y, z))

DOOR_BOTTOM = 0.335
FD_FRONT = -0.835
B_LINE = 0.215          # front / rear door shut line below the belt
FD_FRAME_REAR = 0.185   # front door frame rear edge (B pillar starts)
RD_FRAME_FRONT = 0.250
RD_TOP_REAR = 0.80      # rear door frame top-rear corner
RD_REAR = 1.005         # rear door rear edge above the arch
ARCH_GAP = 0.035


def rail(y):
    """Door frame top line: just under the roof edge."""
    return z_roof(y) - 0.022


def dlo_top(y):
    return z_roof(y) - 0.062


def dlo_bottom(y):
    return z_gbase(y) + 0.018


def a_pillar_y0():
    """Where the rail line rises clear of the belt (front of the side glass)."""
    for y in frange(-0.84, 0.0, 200):
        if rail(y) > z_belt(y) + 0.03:
            return y
    return -0.6


def arch_pts(axle, r, z0, z1, rear_side, n=10):
    """Points on an arch circle (offset r) between heights z0 and z1 on the front (rear_side=False) or rear side."""
    out = []
    for z in frange(z0, z1, n):
        dz = z - B.WHEEL_R
        dy = math.sqrt(max(0.0, r * r - dz * dz))
        out.append((axle + dy if rear_side else axle - dy, z))
    return out


def front_door_outline():
    ya = a_pillar_y0()
    pts = [(FD_FRONT, DOOR_BOTTOM), (FD_FRONT, z_belt(FD_FRONT) - 0.005), (ya, z_belt(ya) + 0.03)]
    pts += [(y, rail(y)) for y in frange(ya + 0.05, FD_FRAME_REAR - 0.03, 14)]
    pts += [(FD_FRAME_REAR, rail(FD_FRAME_REAR) - 0.01), (FD_FRAME_REAR, z_belt(FD_FRAME_REAR) + 0.01),
            (B_LINE, z_belt(B_LINE) - 0.005), (B_LINE, DOOR_BOTTOM)]
    return pts


def rear_door_outline():
    r = B.ARCH_R + ARCH_GAP
    zb = z_belt(RD_REAR)
    arc = arch_pts(B.AXLE_R, r, DOOR_BOTTOM, 0.70, False, 9)
    pts = [(B_LINE, DOOR_BOTTOM), (B_LINE, z_belt(B_LINE) - 0.005), (RD_FRAME_FRONT, z_belt(RD_FRAME_FRONT) + 0.01),
           (RD_FRAME_FRONT, rail(RD_FRAME_FRONT) - 0.01)]
    pts += [(y, rail(y)) for y in frange(RD_FRAME_FRONT + 0.03, RD_TOP_REAR, 10)]
    pts += [(RD_REAR - 0.02, zb + 0.03), (RD_REAR, zb - 0.005), (RD_REAR, 0.72)]
    pts += list(reversed(arc))
    return pts


def front_dlo():
    ya = a_pillar_y0() + 0.03
    pts = [(ya, dlo_bottom(ya) + 0.004)]
    pts += [(y, dlo_top(y)) for y in frange(ya + 0.07, FD_FRAME_REAR - 0.055, 14)]
    pts += [(FD_FRAME_REAR - 0.04, dlo_top(FD_FRAME_REAR - 0.04) - 0.012), (FD_FRAME_REAR - 0.04, dlo_bottom(FD_FRAME_REAR))]
    return pts


def rear_dlo():
    y0 = RD_FRAME_FRONT + 0.04
    pts = [(y0, dlo_bottom(y0)), (y0, dlo_top(y0) - 0.012)]
    pts += [(y, dlo_top(y)) for y in frange(y0 + 0.04, RD_TOP_REAR - 0.07, 10)]
    pts += [(RD_REAR - 0.075, dlo_bottom(RD_REAR) + 0.01)]
    return pts


def quarter_dlo():
    """Small fixed quarter glass behind the rear door (C pillar)."""
    y0 = RD_TOP_REAR + 0.065
    y1 = 1.12
    return [(RD_REAR + 0.035, dlo_bottom(RD_REAR) + 0.012), (y0 + 0.02, dlo_top(y0 + 0.02) - 0.01), (y1, dlo_bottom(y1) + 0.02)]


def windshield_outline():
    """Top view (x, y) of the windshield opening."""
    ys = frange(-0.735, -0.035, 12)
    left = [(w_roof(y) - 0.06 - 0.03 * (1 - (y + 0.735) / 0.7), y) for y in ys]
    return [(-x, y) for x, y in left] + [(x, y) for x, y in reversed(left)]


def rear_window_outline():
    ys = frange(1.015, 1.52, 10)
    left = [(w_roof(y) - 0.065, y) for y in ys]
    return [(-x, y) for x, y in left] + [(x, y) for x, y in reversed(left)]


HOOD_FRONT = -2.125
HOOD_REAR = -0.82
TRUNK_FRONT = 1.635
TRUNK_REAR = 2.175


def hood_outline():
    ys = frange(HOOD_FRONT, HOOD_REAR, 14)
    side = [(w_shoulder(y) - 0.032, y) for y in ys]
    return [(x, y) for x, y in side] + [(-x, y) for x, y in reversed(side)]


def trunk_outline():
    ys = frange(TRUNK_FRONT, TRUNK_REAR, 8)
    side = [(w_shoulder(y) - 0.034, y) for y in ys]
    return [(x, y) for x, y in side] + [(-x, y) for x, y in reversed(side)]


# ------------------------------------------------------------------ cutters


_BVH = {}


def set_reference(shell):
    """Remember the uncut shell for ray casts (surface positions for parts)."""
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(shell.data)
    bm.transform(shell.matrix_world)
    _BVH["shell"] = BVHTree.FromBMesh(bm)
    bm.free()


def ray(origin, direction):
    hit = _BVH["shell"].ray_cast(Vector(origin), Vector(direction).normalized())
    return hit  # (location, normal, index, distance) or (None,)*4


def side_x(y, z, sx=1):
    """x of the outer body surface at (y, z) on side sx (+1 = left, -1 = right)."""
    loc, n, i, d = ray((sx * 2.0, y, z), (-sx, 0, 0))
    return (loc.x, n) if loc is not None else (sx * 0.88, Vector((sx, 0, 0)))


def top_z(x, y):
    loc, n, i, d = ray((x, y, 3.0), (0, 0, -1))
    return (loc.z, n) if loc is not None else (0.9, Vector((0, 0, 1)))


def front_face_y(x, z):
    loc, n, i, d = ray((x, -4.0, z), (0, 1, 0))
    return loc.y if loc is not None else -2.2


def rear_face_y(x, z):
    loc, n, i, d = ray((x, 4.0, z), (0, -1, 0))
    return loc.y if loc is not None else 2.24


def make_cutters():
    """Returns (solid_cutters_obj, gap_cutters_obj, window_solids {name: obj})."""
    col = bpy.context.scene.collection
    # --- solid openings
    bm = bmesh.new()
    for axle in (B.AXLE_F, B.AXLE_R):
        for sx in (-1, 1):
            bm_cyl(bm, (sx * 0.86, axle, B.WHEEL_R), B.ARCH_R, 0.62, seg=48, axis="X")
    # headlight apertures (wrap slightly round the corner) and the grille opening
    for sx in (-1, 1):
        bm_prism(bm, rounded_rect(0.385, 0.565, 0.84, 0.700, 0.018), "Y", -2.5, -2.06) if sx > 0 else \
            bm_prism(bm, rounded_rect(-0.84, 0.565, -0.385, 0.700, 0.018), "Y", -2.5, -2.06)
    bm_prism(bm, rounded_rect(-0.345, 0.575, 0.345, 0.690, 0.012), "Y", -2.5, -2.10)
    # taillight bar across the tail panel, wrapping round the corners
    bm_prism(bm, rounded_rect(-0.86, 0.765, 0.86, 0.885, 0.015), "Y", 2.10, 2.6)
    # lower air intakes in the front bumper (either side of the plate) and amber indicators
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.22, sx * 0.56))
        bm_prism(bm, rounded_rect(x0, 0.300, x1, 0.425, 0.03), "Y", -2.6, -2.05)
        x0, x1 = sorted((sx * 0.62, sx * 0.80))
        bm_prism(bm, rounded_rect(x0, 0.455, x1, 0.505, 0.012), "Y", -2.6, -2.10)
    # rear plate recess is modelled as a separate inset panel; exhaust cut-outs in the rear valance
    for sx in (-1, 1):
        bm_prism(bm, rounded_rect(sx * 0.52 - 0.09, 0.215, sx * 0.52 + 0.09, 0.285, 0.03), "Y", 2.0, 2.6)
    solids = bm_obj("CutSolids", bm, col)

    # --- shut lines
    bm = bmesh.new()
    for sx in (-1, 1):
        a0, a1 = (0.45, 1.3) if sx > 0 else (-1.3, -0.45)
        bm_gap_cutter(bm, front_door_outline(), "X", a0, a1, GAP, closed=True)
        bm_gap_cutter(bm, rear_door_outline(), "X", a0, a1, GAP, closed=True)
        # fuel filler door on the left rear quarter
        if sx > 0:
            bm_gap_cutter(bm, rounded_rect(1.55, 0.70, 1.73, 0.82, 0.03, 3), "X", 0.6, 1.3, 0.003, closed=True)
    # hood and trunk lid (top view, cut along Z)
    bm_gap_cutter(bm, hood_outline(), "Z", 0.62, 1.2, GAP, closed=True)
    bm_gap_cutter(bm, trunk_outline(), "Z", 0.80, 1.2, GAP, closed=True)
    # bumpers: a horizontal slab across the nose / tail + a vertical slab ahead of / behind the arches
    for (y0, y1, zt, yv) in ((-2.6, -1.79, 0.548, -1.79), (1.86, 2.6, 0.585, 1.86)):
        bm_box(bm, (0, (y0 + y1) / 2, zt), (2.4, y1 - y0, GAP))
        bm_box(bm, (0, yv, zt / 2 - 0.05), (2.4, GAP, zt + 0.1))
    gaps = bm_obj("CutGaps", bm, col)

    # --- number plate recesses (kept as pockets: tagged RECESS, not deleted)
    bm = bmesh.new()
    bm_prism(bm, rounded_rect(-0.185, 0.330, 0.185, 0.505, 0.012), "Y", -2.6, front_face_y(0.0, 0.42) + 0.016)
    bm_prism(bm, rounded_rect(-0.195, 0.345, 0.195, 0.525, 0.012), "Y", rear_face_y(0.0, 0.44) - 0.016, 2.6)
    recess = bm_obj("CutRecess", bm, col)

    # --- glass openings (also used to cut the glass panes out of a copy of the shell)
    wins = {}
    for sx in (-1, 1):
        a0, a1 = (0.40, 1.3) if sx > 0 else (-1.3, -0.40)
        side = "L" if sx > 0 else "R"
        for nm, pts in (("door_glass_F", front_dlo()), ("door_glass_R", rear_dlo()), ("quarter_glass", quarter_dlo())):
            bm = bmesh.new()
            bm_prism(bm, pts, "X", a0, a1)
            wins[f"{nm}_{side}"] = bm_obj(f"Win_{nm}_{side}", bm, col)
    bm = bmesh.new()
    bm_prism(bm, windshield_outline(), "Z", 0.80, 1.7)
    wins["windshield"] = bm_obj("Win_windshield", bm, col)
    bm = bmesh.new()
    bm_prism(bm, rear_window_outline(), "Z", 0.90, 1.7)
    wins["rear_window"] = bm_obj("Win_rear_window", bm, col)
    return solids, gaps, wins, recess


def flange(ob, depth=0.012, skip_glass=True):
    """Extrude every open boundary inward (against the vertex normal) so cuts have depth."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    bound = [e for e in bm.edges if e.is_boundary]
    vnorm = {}
    for e in bound:
        for v in e.verts:
            if v not in vnorm:
                n = Vector()
                for f in v.link_faces:
                    n += f.normal
                vnorm[v] = n.normalized() if n.length > 0 else Vector((0, 0, 1))
    res = bmesh.ops.extrude_edge_only(bm, edges=bound)
    newv = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
    # map new verts back to the originals via the extruded faces
    for f in [g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)]:
        pass
    for v in newv:
        src = None
        for e in v.link_edges:
            o = e.other_vert(v)
            if o in vnorm:
                src = o
                break
        if src is not None:
            v.co = src.co - vnorm[src] * depth
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def lamp_apertures():
    """Prisms for the lens patches (same shapes as the light openings)."""
    col = bpy.context.scene.collection
    out = {}
    for sx, side in ((1, "L"), (-1, "R")):
        x0, x1 = sorted((sx * 0.385, sx * 0.84))
        bm = bmesh.new()
        bm_prism(bm, rounded_rect(x0, 0.565, x1, 0.700, 0.018), "Y", -2.5, -2.06)
        out[f"headlight_lens_{side}"] = bm_obj(f"Lens_h_{side}", bm, col)
        x0, x1 = sorted((sx * 0.62, sx * 0.80))
        bm = bmesh.new()
        bm_prism(bm, rounded_rect(x0, 0.455, x1, 0.505, 0.012), "Y", -2.6, -2.10)
        out[f"indicator_lens_{side}"] = bm_obj(f"Lens_i_{side}", bm, col)
    bm = bmesh.new()
    bm_prism(bm, rounded_rect(-0.86, 0.765, 0.86, 0.885, 0.015), "Y", 2.10, 2.6)
    out["taillight_lens"] = bm_obj("Lens_t", bm, col)
    return out


PIECE_RULES = [
    # name, test(center, size)
    ("hood", lambda c, s: c.z > 0.7 and c.y < -0.9 and abs(c.x) < 0.3 and s.x > 1.2),
    ("trunk_lid", lambda c, s: c.z > 0.8 and c.y > 1.6 and abs(c.x) < 0.3 and s.x > 1.2),
    ("bumper_F", lambda c, s: c.y < -1.85 and c.z < 0.55 and s.x > 1.2),
    ("bumper_R", lambda c, s: c.y > 1.9 and c.z < 0.6 and s.x > 1.2),
    ("fuel_door", lambda c, s: c.x > 0.7 and 1.5 < c.y < 1.8 and s.y < 0.25),
    ("door_FL", lambda c, s: c.x > 0.6 and -0.9 < c.y < 0.2 and s.y > 0.8),
    ("door_FR", lambda c, s: c.x < -0.6 and -0.9 < c.y < 0.2 and s.y > 0.8),
    ("door_RL", lambda c, s: c.x > 0.6 and 0.2 < c.y < 1.1 and s.y > 0.6),
    ("door_RR", lambda c, s: c.x < -0.6 and 0.2 < c.y < 1.1 and s.y > 0.6),
]


def separate_pieces(ob):
    """Split `ob` into connected pieces and name them. Returns {name: obj}."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    seen = set()
    groups = []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack = [f]
        comp = []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g.index)
            for v in g.verts:
                for h in v.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        groups.append(comp)
    groups.sort(key=len, reverse=True)
    out = {}
    rest = []
    for gi, comp in enumerate(groups):
        bm2 = bm.copy()
        keep = set(comp)
        bmesh.ops.delete(bm2, geom=[f for f in bm2.faces if f.index not in keep], context="FACES")
        lo = Vector((min(v.co.x for v in bm2.verts), min(v.co.y for v in bm2.verts), min(v.co.z for v in bm2.verts)))
        hi = Vector((max(v.co.x for v in bm2.verts), max(v.co.y for v in bm2.verts), max(v.co.z for v in bm2.verts)))
        c, sz = (lo + hi) / 2, hi - lo
        name = None
        if gi == 0:
            name = "body_shell"
        else:
            for nm, test in PIECE_RULES:
                if nm not in out and test(c, sz):
                    name = nm
                    break
        if name is None:
            rest.append(bm2)
            continue
        out[name] = bm_obj(name, bm2)
    # stray slivers go back into the shell
    if rest:
        shell = out["body_shell"]
        bmS = bmesh.new()
        bmS.from_mesh(shell.data)
        for b in rest:
            me = bpy.data.meshes.new("tmp")
            b.to_mesh(me)
            b.free()
            bmS.from_mesh(me)
            bpy.data.meshes.remove(me)
        bmS.to_mesh(shell.data)
        bmS.free()
    bm.free()
    delete([ob])
    return out


def thicken(ob, t=0.004, inset=0.003):
    """Glass / lens pane: push in a little and give it thickness."""
    me = ob.data
    me.update()
    for v in me.vertices:
        v.co -= v.normal * inset
    m = ob.modifiers.new("solid", "SOLIDIFY")
    m.thickness = t
    m.offset = -1
    m.use_even_offset = True
    m.use_rim = True
    apply_mods(ob)
    return ob


def cut_body(shell):
    set_reference(shell)
    solids, gaps, wins, recess = make_cutters()
    lamps = lamp_apertures()
    glass_src = copy_obj(shell, "GlassSource")
    cut(shell, solids, keep=True)
    for w in wins.values():
        cut(shell, w, keep=True)
    cut(shell, recess, keep=True, tag="RECESS")
    cut(shell, gaps, keep=True)
    open_cuts(shell)
    # glass panes and lamp lenses: the shell surface inside each opening
    panes = {}
    for nm, w in list(wins.items()) + list(lamps.items()):
        p = copy_obj(glass_src, f"glass_{nm}" if nm in wins else nm)
        cut(p, w, "INTERSECT")
        p.data.materials.clear()
        thicken(p, 0.004 if nm in wins else 0.003, 0.004 if nm in wins else 0.006)
        panes[p.name] = p
    delete([solids, gaps, recess, glass_src] + list(wins.values()) + list(lamps.values()))
    shell.data.materials.clear()
    pieces = separate_pieces(shell)
    for nm, ob in pieces.items():
        flange(ob, 0.014)
    return pieces, panes
