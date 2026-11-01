"""Cut the subdivided body shell into real panels (spec block `V.panels`).

Wheel arches, window openings (DLO), lamp and grille apertures are boolean
differences; shut lines are thin cutters (`gap`, 4.5 mm) whose closed loops
separate the doors, hood, trunk / hatch, bumpers and fuel door into their own
connected pieces. Every piece then gets a rounded flange rolling under its cut
edges, so the gaps have depth, and the smooth surface's normals.

Panel layout (all Blender coordinates, the vehicle faces -Y):
    doors        [{name, kind: front|rear, ...}] per side, front to back (see door_outline)
    windows      fixed side glass [{name, y0, y1, ...}]
    windshield   {kind: top, y0, y1, inset, taper, z0, z1} or {kind: front, ...trapezoid}
    rear_window  {kind: top, ...} or {kind: rear, ...trapezoid}
    hood, trunk  {kind: top, y0, y1, inset, z0, z1, n} or {kind: rear, w, z0, z1, r, y0, y1, split}
    bumpers      [{y, z, end}]  horizontal slab + vertical cut
    fuel_door    {y0, y1, z0, z1, r, side}
    apertures    openings through the shell: [{rect: [x0, z0, x1, z1, r], a0, a1}] or {sides: [...]}
    lenses       panes cut out of the shell in lamp openings (same format, plus name / group)
    plates       {front: {w, z0, z1, r, depth, ray_z}, rear: {...}}  recessed plate pockets
"""
import math

import bmesh
import bpy
from mathutils import Vector

from . import body as B
from . import cfg
from .geom import (apply_mods, bm_box, bm_cyl, bm_gap_cutter, bm_obj, bm_prism, copy_obj, cut, delete, open_cuts,
                   rounded_rect)


def PN():
    return cfg.V.panels


def gap_w():
    return PN().get("gap", 0.0045)


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


def rail(y):
    """Door frame top line: just under the roof edge."""
    return z_roof(y) - PN().get("rail_drop", 0.022)


def dlo_top(y):
    return z_roof(y) - PN().get("dlo_top_drop", 0.062)


def dlo_bottom(y):
    return z_gbase(y) + PN().get("dlo_bottom_rise", 0.018)


def door_bottom():
    return PN().get("door_bottom", 0.335)


def a_pillar_y0():
    """Where the rail line rises clear of the belt (front of the side glass)."""
    y0, y1 = PN().get("apillar_search", (-0.84, 0.0))
    for y in frange(y0, y1, 200):
        if rail(y) > z_belt(y) + 0.03:
            return y
    return PN().get("apillar_fallback", -0.6)


def arch_pts(axle, r, z0, z1, rear_side, n=10):
    """Points on an arch circle (offset r) between heights z0 and z1 on the front (rear_side=False) or rear side."""
    out = []
    for z in frange(z0, z1, n):
        dz = z - B.arch_z()
        dy = math.sqrt(max(0.0, r * r - dz * dz))
        out.append((axle + dy if rear_side else axle - dy, z))
    return out


def door_span(d):
    """(front y, rear y) of a door below the belt."""
    if d.kind == "front":
        return d.front, d.line
    return d.line, d.rear


def front_door_outline(d):
    """A front door: straight front edge, then the A pillar and the roof rail to the frame's rear,
    down the B pillar to the belt and along the shut line `line` to the sill."""
    db = d.get("bottom", door_bottom())
    if d.get("frameless"):
        # hardtop / truck door: the shut line stays below the belt (the glass drops into the door)
        top = d.get("top_rise", 0.0)
        return [(d.front, db), (d.front, z_belt(d.front) + top - 0.005), (d.line, z_belt(d.line) + top - 0.005), (d.line, db)]
    ya = a_pillar_y0()
    fr = d.frame_rear
    pts = [(d.front, db), (d.front, z_belt(d.front) - 0.005), (ya, z_belt(ya) + 0.03)]
    pts += [(y, rail(y)) for y in frange(ya + 0.05, fr - 0.03, d.get("n", 14))]
    if d.get("frame_to_rail"):
        # the frame runs straight down the B pillar to the sill (one-piece door / van cab)
        pts += [(fr, rail(fr) - 0.01), (fr, db)]
        return pts
    pts += [(fr, rail(fr) - 0.01), (fr, z_belt(fr) + 0.01), (d.line, z_belt(d.line) - 0.005), (d.line, db)]
    return pts


def rear_door_outline(d):
    """A rear (or sliding) door from the shut line `line` back to `rear`; its frame follows the
    rail from `frame_front` to `top_rear`; the rear edge either drops to the belt (sedan: a fixed
    quarter behind) or runs down from the rail (van slider); `arch` notches round the rear arch."""
    db = d.get("bottom", door_bottom())
    zb = z_belt(d.rear)
    ff = d.frame_front
    pts = [(d.line, db), (d.line, z_belt(d.line) - 0.005), (ff, z_belt(ff) + 0.01), (ff, rail(ff) - 0.01)]
    if d.get("rear_frame", "belt") == "belt":
        pts += [(y, rail(y)) for y in frange(ff + 0.03, d.top_rear, d.get("n", 10))]
        pts += [(d.rear - 0.02, zb + 0.03), (d.rear, zb - 0.005)]
    else:
        pts += [(y, rail(y)) for y in frange(ff + 0.03, d.rear - 0.03, d.get("n", 10))]
        pts += [(d.rear, rail(d.rear) - 0.01)]
    if d.get("arch"):
        r = cfg.V.arch_r + d.get("arch_gap", 0.035)
        z1 = d.get("arch_top", 0.70)
        arc = arch_pts(B.axle_r(), r, db, z1, False, 9)
        pts += [(d.rear, z1 + 0.02)]
        pts += list(reversed(arc))
    else:
        pts += [(d.rear, db)]
    return pts


def door_outline(d):
    return front_door_outline(d) if d.kind == "front" else rear_door_outline(d)


def door_dlo(d):
    """The door's glass opening, or None for a door without glass."""
    if d.get("glass") is False:
        return None
    if d.kind == "front":
        if d.get("frameless"):
            return None
        ya = a_pillar_y0() + 0.03
        fr = d.frame_rear
        pts = [(ya, dlo_bottom(ya) + 0.004)]
        pts += [(y, dlo_top(y)) for y in frange(ya + 0.07, fr - 0.055, d.get("n", 14))]
        pts += [(fr - 0.04, dlo_top(fr - 0.04) - 0.012), (fr - 0.04, dlo_bottom(fr))]
        return pts
    y0 = d.frame_front + 0.04
    pts = [(y0, dlo_bottom(y0)), (y0, dlo_top(y0) - 0.012)]
    if d.get("rear_frame", "belt") == "belt":
        pts += [(y, dlo_top(y)) for y in frange(y0 + 0.04, d.top_rear - 0.07, d.get("n", 10))]
        pts += [(d.rear - 0.075, dlo_bottom(d.rear) + 0.01)]
    else:
        y1 = d.rear - 0.045
        pts += [(y, dlo_top(y)) for y in frange(y0 + 0.04, y1 - 0.04, d.get("n", 10))]
        pts += [(y1, dlo_top(y1) - 0.012), (y1, dlo_bottom(y1))]
    return pts


def fixed_window(w):
    """A fixed side window between y0 and y1 under the roof edge (corner radius r)."""
    y0, y1 = w.y0, w.y1
    r = w.get("r", 0.012)
    top = w.get("top_drop", 0.0)
    bot = w.get("bottom_rise", 0.0)
    pts = [(y0, dlo_bottom(y0) + bot), (y0, dlo_top(y0) - r - top)]
    pts += [(y, dlo_top(y) - top) for y in frange(y0 + 0.03, y1 - 0.03, w.get("n", 8))]
    pts += [(y1, dlo_top(y1) - r - top), (y1, dlo_bottom(y1) + bot)]
    if w.get("slant"):
        # the rear edge leans forward at the top (C pillar)
        pts[-2] = (y1 - w.slant, pts[-2][1])
    return pts


def trapezoid(zb, zt, wb, wt, r, n=4):
    """(x, z) outline: half width wb at zb, wt at zt, rounded corners."""
    pts = []
    for (x, z, a0) in ((wt - r, zt - r, 0), (-wt + r, zt - r, 90), (-wb + r, zb + r, 180), (wb - r, zb + r, 270)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((x + r * math.cos(a), z + r * math.sin(a)))
    return pts


def windshield_outline():
    """Top view (x, y) of the windshield opening."""
    w = PN().windshield
    ys = frange(w.y0, w.y1, 12)
    left = [(w_roof(y) - w.inset - w.taper * (1 - (y - w.y0) / (w.y1 - w.y0)), y) for y in ys]
    return [(-x, y) for x, y in left] + [(x, y) for x, y in reversed(left)]


def rear_window_outline():
    w = PN().rear_window
    ys = frange(w.y0, w.y1, 10)
    left = [(w_roof(y) - w.inset - w.get("taper", 0.0) * (y - w.y0) / (w.y1 - w.y0), y) for y in ys]
    return [(-x, y) for x, y in left] + [(x, y) for x, y in reversed(left)]


def lid_outline(k):
    """Top view (x, y) of a hood / trunk lid shut line."""
    ys = frange(k.y0, k.y1, k.get("n", 8))
    side = [(w_shoulder(y) - k.inset, y) for y in ys]
    return [(x, y) for x, y in side] + [(-x, y) for x, y in reversed(side)]


def hood_outline():
    return lid_outline(PN().hood)


def trunk_outline():
    return lid_outline(PN().trunk)


# ------------------------------------------------------------------ surface queries


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


def _far():
    r = cfg.V.get("ray") or {}
    return r.get("x", 2.0), r.get("z", 3.0), r.get("y", 4.0)


def side_x(y, z, sx=1):
    """x of the outer body surface at (y, z) on side sx (+1 = left, -1 = right)."""
    loc, n, i, d = ray((sx * _far()[0], y, z), (-sx, 0, 0))
    return (loc.x, n) if loc is not None else (sx * 0.88, Vector((sx, 0, 0)))


def top_z(x, y):
    loc, n, i, d = ray((x, y, _far()[1]), (0, 0, -1))
    return (loc.z, n) if loc is not None else (0.9, Vector((0, 0, 1)))


def front_face_y(x, z):
    loc, n, i, d = ray((x, -_far()[2], z), (0, 1, 0))
    return loc.y if loc is not None else cfg.V.front


def rear_face_y(x, z):
    loc, n, i, d = ray((x, _far()[2], z), (0, -1, 0))
    return loc.y if loc is not None else cfg.V.rear


# ------------------------------------------------------------------ cutters


def side_items(items):
    """Expand an aperture / lens list: {sides: [...]} entries are emitted once per side
    (sx = -1 then +1, x mirrored), plain entries once."""
    out = []
    for it in items:
        if "sides" in it:
            for sx in it.get("order", (-1, 1)):
                for a in it.sides:
                    out.append((a, sx))
        else:
            out.append((it, 0))
    return out


def rect_for(a, sx):
    x0, z0, x1, z1, r = a.rect
    if sx:
        x0, x1 = sorted((sx * x0, sx * x1))
    return rounded_rect(x0, z0, x1, z1, r, a.get("seg", 4))


def prism_item(bm, a, sx):
    ax = a.get("axis", "Y")
    if a.get("trapezoid"):
        zb, zt, wb, wt, r = a.trapezoid
        bm_prism(bm, trapezoid(zb, zt, wb, wt, r), ax, a.a0, a.a1)
    elif a.get("poly"):
        pts = [(sx * u if sx else u, v) for u, v in a.poly] if ax != "X" else a.poly
        bm_prism(bm, pts, ax, a.a0 if sx >= 0 or ax != "X" else -a.a1, a.a1 if sx >= 0 or ax != "X" else -a.a0)
    else:
        bm_prism(bm, rect_for(a, sx), ax, a.a0, a.a1)


def window_prism(w, name):
    bm = bmesh.new()
    if w.get("kind", "top") == "top":
        outline = windshield_outline() if name == "windshield" else rear_window_outline()
        bm_prism(bm, outline, "Z", w.z0, w.z1)
    else:
        bm_prism(bm, trapezoid(w.zb, w.zt, w.wb, w.wt, w.r), "Y", w.a0, w.a1)
    return bm_obj(f"Win_{name}", bm, bpy.context.scene.collection)


def lid_gap(b, k):
    """Gap cutter for a hood / trunk / hatch."""
    if k.get("kind", "top") == "top":
        bm_gap_cutter(b, lid_outline(k), "Z", k.z0, k.z1, gap_w(), closed=True)
    else:
        # a hatch / barn doors seen from behind: a closed loop on the tail face (x, z), cut along Y
        w, z0, z1, r = k.w, k.z0, k.z1, k.get("r", 0.04)
        if k.get("trapezoid"):
            pts = trapezoid(z0, z1, w, k.trapezoid, r)
        else:
            pts = rounded_rect(-w, z0, w, z1, r, 4)
        bm_gap_cutter(b, pts, "Y", k.y0, k.y1, gap_w(), closed=True)


def make_cutters():
    """Returns (solid cutters, gap cutters, window solids {name: obj}, plate recesses)."""
    v = cfg.V
    pn = PN()
    col = bpy.context.scene.collection
    # --- solid openings
    bm = bmesh.new()
    ax_x = pn.get("arch_x", 0.86)
    ax_d = pn.get("arch_depth", 0.62)
    for axle in v.axles:
        for sx in (-1, 1):
            bm_cyl(bm, (sx * ax_x, axle, B.arch_z()), v.arch_r, ax_d, seg=48, axis="X")
    for a, sx in side_items(pn.apertures):
        prism_item(bm, a, sx)
    solids = bm_obj("CutSolids", bm, col)

    # --- shut lines: every loop is its own closed solid, then they are unioned
    pieces = []

    def gap_piece(fn):
        b = bmesh.new()
        fn(b)
        pieces.append(bm_obj(f"Gap{len(pieces)}", b, col))
    gx0, gx1 = pn.get("gap_x", (0.45, 1.3))
    fd = pn.get("fuel_door")
    for sx in (-1, 1):
        a0, a1 = (gx0, gx1) if sx > 0 else (-gx1, -gx0)
        prev = None
        for i, d in enumerate(pn.doors):
            pts = door_outline(d)
            if prev is not None and d.kind == "rear" and abs(d.line - prev) < 1e-6:
                # nudge this door's copy of the shared shut line so the two loops never coincide
                pts = [(y + 0.0011 if abs(y - d.line) < 1e-6 else y, z) for y, z in pts]
            s = 0.003 * min(i, 1)
            gap_piece(lambda b, pts=pts, s=s: bm_gap_cutter(b, pts, "X", a0 + s, a1 - s, gap_w(), closed=True))
            prev = door_span(d)[1]
        if fd and sx == fd.get("side", 1):
            gap_piece(lambda b: bm_gap_cutter(b, rounded_rect(fd.y0, fd.z0, fd.y1, fd.z1, fd.get("r", 0.03), 3), "X",
                                              0.6 if sx > 0 else -1.3, 1.3 if sx > 0 else -0.6, 0.003, closed=True))
    if pn.get("hood"):
        gap_piece(lambda b: lid_gap(b, pn.hood))
    if pn.get("trunk"):
        gap_piece(lambda b: lid_gap(b, pn.trunk))
        if pn.trunk.get("split"):
            k = pn.trunk
            gap_piece(lambda b: bm_box(b, (0, (k.y0 + k.y1) / 2, (k.z0 + k.z1) / 2), (gap_w(), k.y1 - k.y0, k.z1 - k.z0 - 0.02)))
    for bp in pn.get("bumpers", []):
        y0, y1 = sorted((bp.end, bp.y))
        zt = bp.z
        gap_piece(lambda b: bm_box(b, (0, (y0 + y1) / 2, zt), (bp.get("width", 2.4), y1 - y0, gap_w())))
        gap_piece(lambda b: bm_box(b, (0, bp.y, zt / 2 - 0.05 + 0.001), (bp.get("width", 2.4) + 0.01, gap_w(), zt + 0.1)))
    for g in pn.get("extra_gaps", []):
        gap_piece(lambda b, g=g: bm_gap_cutter(b, [tuple(p) for p in g.pts], g.axis, g.a0, g.a1, g.get("w", gap_w()), closed=g.get("closed", True)))
    gaps = pieces[0]
    gaps.name = "CutGaps"
    for p in pieces[1:]:
        m = gaps.modifiers.new("u", "BOOLEAN")
        m.operation = "UNION"
        m.solver = "MANIFOLD"
        m.object = p
        apply_mods(gaps)
    delete(pieces[1:])

    # --- number plate recesses (kept as pockets: tagged RECESS, not deleted)
    bm = bmesh.new()
    pl = pn.get("plates") or {}
    if pl.get("front"):
        p = pl.front    # {w, z0, z1, r, depth, ray_z}: a pocket `depth` deep behind the front face
        bm_prism(bm, rounded_rect(-p.w, p.z0, p.w, p.z1, p.r), "Y", v.front - 0.4, front_face_y(0.0, p.ray_z) + p.depth)
    if pl.get("rear"):
        p = pl.rear
        bm_prism(bm, rounded_rect(-p.w, p.z0, p.w, p.z1, p.r), "Y", rear_face_y(0.0, p.ray_z) - p.depth, v.rear + 0.36)
    recess = bm_obj("CutRecess", bm, col) if len(bm.verts) else None
    if recess is None:
        bm.free()

    # --- glass openings (also used to cut the glass panes out of a copy of the shell)
    wins = {}
    wx0, wx1 = pn.get("win_x", (0.40, 1.3))
    for sx in (-1, 1):
        a0, a1 = (wx0, wx1) if sx > 0 else (-wx1, -wx0)
        side = "L" if sx > 0 else "R"
        for d in pn.doors:
            pts = door_dlo(d)
            if pts:
                bm = bmesh.new()
                bm_prism(bm, pts, "X", a0, a1)
                wins[f"door_glass_{d.name}_{side}"] = bm_obj(f"Win_door_glass_{d.name}_{side}", bm, col)
        for w in pn.get("windows", []):
            bm = bmesh.new()
            bm_prism(bm, fixed_window(w), "X", a0, a1)
            wins[f"{w.name}_{side}"] = bm_obj(f"Win_{w.name}_{side}", bm, col)
    if pn.get("windshield"):
        wins["windshield"] = window_prism(pn.windshield, "windshield")
    if pn.get("rear_window"):
        wins["rear_window"] = window_prism(pn.rear_window, "rear_window")
    return solids, gaps, wins, recess


def flange(ob, depth=0.012, round_r=0.0018):
    """Turn every open boundary (a shut line or opening) into a rounded edge rolling under the
    panel: a 45-degree roll-off ring (radius `round_r`) and then a flange `depth` deep, so the
    gaps read as real ~4 mm shut lines with soft edges and depth."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    bound = [e for e in bm.edges if e.is_boundary]
    info = {}
    for e in bound:
        f = e.link_faces[0]
        t = (e.verts[1].co - e.verts[0].co).normalized()
        d = f.normal.cross(t)
        if d.dot(f.calc_center_median() - e.verts[0].co) < 0:
            d = -d
        for v in e.verts:
            n, inw = info.get(v, (Vector(), Vector()))
            info[v] = (n, inw + d)
    for v in info:
        n = Vector()
        for f in v.link_faces:
            n += f.normal
        info[v] = (n.normalized() if n.length else Vector((0, 0, 1)), info[v][1].normalized() if info[v][1].length else Vector())

    def ring(edges, offset):
        res = bmesh.ops.extrude_edge_only(bm, edges=edges)
        newv = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
        newe = [g for g in res["geom"] if isinstance(g, bmesh.types.BMEdge) and g.is_boundary]
        mp = {}
        for v in newv:
            for e in v.link_edges:
                o = e.other_vert(v)
                if o in src_of:
                    mp[v] = src_of[o]
                    break
        for v, o in mp.items():
            n, inw = info[o]
            v.co = o.co + offset(n, inw)
            src_of[v] = o
        return newe
    src_of = {v: v for v in info}
    e1 = ring(bound, lambda n, inw: -n * round_r + inw * round_r * 0.6)
    ring(e1, lambda n, inw: -n * depth + inw * round_r)
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def transfer_normals(ob, ref, max_dist=0.004, min_dot=0.85):
    """Copy the smooth (uncut) surface's normals onto the matching vertices of a cut piece,
    so boolean slivers don't show in reflections. Flanges / recess walls keep their own."""
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(ref.data)
    bm.transform(ref.matrix_world)
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    me = ob.data
    me.update()
    vg = ob.vertex_groups.new(name="outer")
    for v in me.vertices:
        loc, nrm, idx, dist = tree.find_nearest(v.co)
        if loc is not None and dist < max_dist:
            if v.normal.dot(nrm) > min_dot:
                vg.add([v.index], 1.0, "REPLACE")
    bm.free()
    m = ob.modifiers.new("nrm", "DATA_TRANSFER")
    m.object = ref
    m.use_loop_data = True
    m.data_types_loops = {"CUSTOM_NORMAL"}
    m.loop_mapping = "POLYINTERP_NEAREST"
    m.vertex_group = "outer"
    apply_mods(ob)
    ob.vertex_groups.clear()
    return ob


def lamp_apertures():
    """Prisms for the lens patches (same shapes as the light openings): {name: (obj, group)}."""
    col = bpy.context.scene.collection
    out = {}
    for a, sx in side_items_lr(PN().get("lenses", [])):
        bm = bmesh.new()
        prism_item(bm, a, sx)
        nm = a.name if not sx else f"{a.name}_{'L' if sx > 0 else 'R'}"
        out[nm] = (bm_obj(f"Lens_{nm}", bm, col), a.group)
    return out


def side_items_lr(items):
    """Like side_items but left first (lens panes keep the original L, R order)."""
    out = []
    for it in items:
        if "sides" in it:
            for sx in (1, -1):
                for a in it.sides:
                    out.append((a, sx))
        else:
            out.append((it, 0))
    return out


def piece_rules():
    """[(name, test(centre, size))] for naming the separated pieces, built from the layout."""
    pn = PN()
    rules = []
    if pn.get("hood"):
        k = pn.hood
        if k.get("kind", "top") == "top":
            rules.append(("hood", lambda c, s, k=k: k.y0 < c.y < k.y1 and abs(c.x) < 0.3 and s.x > 1.2 and c.z > k.get("piece_z", 0.7)))
        else:
            rules.append(("hood", lambda c, s, k=k: c.y < k.y1 and abs(c.x) < 0.3 and s.x > 1.0 and c.z > k.z0))
    if pn.get("trunk"):
        k = pn.trunk
        nm = k.get("name", "trunk_lid")
        if k.get("kind", "top") == "top":
            rules.append((nm, lambda c, s, k=k: k.y0 < c.y < k.y1 + 0.1 and abs(c.x) < 0.3 and s.x > 1.2 and c.z > k.get("piece_z", 0.8)))
        elif k.get("split"):
            rules.append((nm + "_L", lambda c, s, k=k: c.y > k.y0 and 0.05 < c.x < k.w and c.z > k.z0 - 0.02 and s.z > 0.5 * (k.z1 - k.z0)))
            rules.append((nm + "_R", lambda c, s, k=k: c.y > k.y0 and -k.w < c.x < -0.05 and c.z > k.z0 - 0.02 and s.z > 0.5 * (k.z1 - k.z0)))
        else:
            rules.append((nm, lambda c, s, k=k: c.y > k.y0 and abs(c.x) < 0.3 and s.x > 1.0 and c.z > k.z0 - 0.02 and s.z > 0.5 * (k.z1 - k.z0)))
    bps = pn.get("bumpers", [])
    for bp in bps:
        nm = "bumper_F" if bp.y < 0 else "bumper_R"
        if bp.y < 0:
            rules.append((nm, lambda c, s, bp=bp: c.y < bp.y - 0.06 and c.z < bp.z + 0.002 and s.x > 1.2))
        else:
            rules.append((nm, lambda c, s, bp=bp: c.y > bp.y + 0.04 and c.z < bp.z + 0.048 and s.x > 1.2))
    fd = pn.get("fuel_door")
    if fd:
        rules.append(("fuel_door", lambda c, s, fd=fd: fd.get("side", 1) * c.x > 0.5 and fd.y0 - 0.05 < c.y < fd.y1 + 0.07 and s.y < 0.25))
    for d in pn.doors:
        y0, y1 = door_span(d)
        for sx, side in ((1, "L"), (-1, "R")):
            rules.append((f"door_{d.name}{side}", lambda c, s, y0=y0, y1=y1, sx=sx: sx * c.x > 0.35 and y0 - 0.07 < c.y < y1 + 0.07
                          and s.y > 0.7 * (y1 - y0)))
    # door names in the order the original builder used (all fronts, then all rears)
    order = {f"door_{d.name}{sd}": (i, j) for i, d in enumerate(pn.doors) for j, sd in enumerate("LR")}
    head = [r for r in rules if not r[0].startswith("door_")]
    doors = sorted([r for r in rules if r[0].startswith("door_")], key=lambda r: order[r[0]])
    return head + doors


def separate_pieces(ob):
    """Split `ob` into connected pieces and name them. Returns {name: obj}."""
    rules = piece_rules()
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
            for nm, test in rules:
                if nm not in out and test(c, sz):
                    name = nm
                    break
        print(f"[piece] {gi} faces={len(comp)} c=({c.x:.2f},{c.y:.2f},{c.z:.2f}) s=({sz.x:.2f},{sz.y:.2f},{sz.z:.2f}) -> {name}")
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
    missing = [nm for nm, _ in rules if nm not in out]
    if missing:
        print(f"[panels] WARNING: no piece for {missing}")
    return out


def thicken(ob, t=0.004, inset=0.003):
    """Glass / lens pane: push it in a little."""
    me = ob.data
    me.update()
    for v in me.vertices:
        v.co -= v.normal * inset
    return ob


def cut_body(shell):
    """Returns ({piece name: obj}, {pane name: (obj, group)})."""
    set_reference(shell)
    solids, gaps, wins, recess = make_cutters()
    lamps = lamp_apertures()
    glass_src = copy_obj(shell, "GlassSource")
    cut(shell, solids, keep=True)
    for w in wins.values():
        cut(shell, w, keep=True)
    if recess is not None:
        cut(shell, recess, keep=True, tag="RECESS")
    cut(shell, gaps, keep=True)
    open_cuts(shell)
    # glass panes and lamp lenses: the shell surface inside each opening
    panes = {}
    items = [(nm, w, "glass") for nm, w in wins.items()] + [(nm, w, g) for nm, (w, g) in lamps.items()]
    for nm, w, grp in items:
        p = copy_obj(glass_src, f"glass_{nm}" if nm in wins else nm)
        cut(p, w, "INTERSECT")
        p.data.materials.clear()
        thicken(p, 0.004 if nm in wins else 0.003, 0.004 if nm in wins else 0.006)
        panes[p.name] = (p, grp)
    delete([solids, gaps] + ([recess] if recess is not None else []) + list(wins.values()) + [w for w, g in lamps.values()])
    shell.data.materials.clear()
    pieces = separate_pieces(shell)
    depth = PN().get("flange_depth", 0.014)
    for nm, ob in pieces.items():
        flange(ob, depth)
    for ob in list(pieces.values()) + [p for p, g in panes.values()]:
        transfer_normals(ob, glass_src, max_dist=0.008 if ob.name in panes else 0.004)
    delete([glass_src])
    return pieces, panes
