"""The SubD body shell, lofted from 12-point half cross-sections (mirrored).

Every section has the same point layout, so each point index traces one
longitudinal line of the body: the sill, the rocker crease, the shoulder (the
main character line), the greenhouse base, the roof edge... Where the "cab"
factor is 0 (hood, deck, load bed) the greenhouse points lie on the hood / deck
surface; where it is 1 they climb to the roof. That is how a three-box sedan, a
one-box van or a wedge coupe all come out of one loft: only the key curves in
the spec's `body` block differ.

Spec fields (`V.body`, Blender coordinates: the vehicle faces -Y, Z up, +X = left):
    stations               section y values (dense where the shape turns)
    ztop, drop, wside, wroof, wg_in, zbelt, zfloor, zrock, rake
                           [(y, value)] keys, pchip-interpolated along y
    cab                    ((y0, y1), (y2, y3)): the cab factor rises over y0..y1, falls over y2..y3
    section                optional overrides of the section constants (SECTION below)
    cap_bulge              (front, rear) Coons-cap bulge
    creases                {point index: weight} on the character lines
"""
import math

import bmesh

from . import cfg
from .geom import lerp, mesh_obj, pchip, smooth

# point indices along the half section (0 = bottom centre ... 11 = top centre)
P_SILL, P_ROCK, P_SHOULDER, P_GBASE, P_ROOF = 2, 3, 6, 7, 9
NP = 12

SECTION = dict(
    wroof_min_inset=0.06,     # roof edge at least this far in from the body side
    rock_min_drop=0.12,       # rocker crease at least this far under the belt
    shoulder_in=0.028,        # shoulder point inset from the widest point
    gbase_rise=(0.010, 0.030),  # greenhouse base above the belt: (hood / deck, cab)
    min_glass=0.02,           # roof edge at least this far over the greenhouse base
    g9_bulge=(0.0, 0.012),    # side glass outward curve (hood / deck, cab)
    g9_rise=(0.006, 0.0),
    floor_in=0.11,            # floor corner inset
    sill_in=0.07, sill_up=0.04,
    rock_in=0.034,
    side_frac=0.55,           # the widest point between rocker and belt
    belt_in=0.010, belt_dz=0.035,
    crown_x=0.55, crown_drop=0.30,
    rake_pivot=0.48,
)


def sec(k):
    s = cfg.V.body.get("section") or {}
    return s.get(k, SECTION[k])


def axle_f():
    return cfg.V.axles[0]


def axle_r():
    return cfg.V.axles[-1]


def arch_z():
    """Wheel centre height in the (unlowered) body frame."""
    return cfg.V.wheel_r + cfg.V.body_drop


def cab_factor(y):
    (a0, a1), (b0, b1) = cfg.V.body.cab
    return min(smooth(a0, a1, y), 1 - smooth(b0, b1, y))


def half_section(y):
    b = cfg.V.body
    zt = pchip(b.ztop, y)
    drop = pchip(b.drop, y)
    ws = pchip(b.wside, y)
    wr = min(pchip(b.wroof, y), ws - sec("wroof_min_inset"))
    zb = pchip(b.zbelt, y)
    zf = pchip(b.zfloor, y)
    zr = min(pchip(b.zrock, y), zb - sec("rock_min_drop"))
    wsh = ws - sec("shoulder_in")
    wg = wsh - pchip(b.wg_in, y)
    cab = cab_factor(y)
    g0, g1 = sec("gbase_rise")
    zg = zb + lerp(g0, g1, cab)
    zroof = zt - drop
    if zroof < zg + sec("min_glass"):
        zroof = zg + sec("min_glass")
    xg9 = lerp(wg, wr, 0.5) + lerp(*sec("g9_bulge"), cab)
    zg9 = lerp(zg, zroof, 0.5) + lerp(*sec("g9_rise"), cab)
    pts = [
        (0.0, zf),
        (ws - sec("floor_in"), zf),
        (ws - sec("sill_in"), zf + sec("sill_up")),
        (ws - sec("rock_in"), zr),
        (ws, zr + sec("side_frac") * (zb - zr)),
        (ws - sec("belt_in"), zb - sec("belt_dz")),
        (wsh, zb),
        (wg, zg),
        (xg9, zg9),
        (wr, zroof),
        (wr * sec("crown_x"), zt - drop * sec("crown_drop")),
        (0.0, zt),
    ]
    return pts


def coons_cap(verts, ring, bulge):
    """Fill the end loop with a 4 x (NP-5) quad grid. Loop layout: ring[0] bottom centre,
    ring[1..NP-2] right side (x<0) bottom->top, ring[NP-1] top centre, then the left side top->bottom."""
    from mathutils import Vector
    n = NP
    m = 2 * (n - 1)
    R = [ring[k] for k in range(2, n - 2)]          # right rail, bottom->top
    L = [ring[m - k] for k in range(2, n - 2)]      # left rail
    B = [ring[2], ring[1], ring[0], ring[m - 1], ring[m - 2]]   # bottom, right->left
    T = [ring[n - 3], ring[n - 2], ring[n - 1], ring[n], ring[n + 1]]
    nu, nv = 4, n - 5
    grid = [[None] * (nv + 1) for _ in range(nu + 1)]
    for u in range(nu + 1):
        grid[u][0] = B[u]
        grid[u][nv] = T[u]
    for v in range(nv + 1):
        grid[0][v] = R[v]
        grid[nu][v] = L[v]
    P = lambda i: Vector(verts[i])
    c00, c10, c01, c11 = P(B[0]), P(B[nu]), P(T[0]), P(T[nu])
    for u in range(1, nu):
        for v in range(1, nv):
            s, t = u / nu, v / nv
            p = ((1 - t) * P(B[u]) + t * P(T[u]) + (1 - s) * P(R[v]) + s * P(L[v])
                 - ((1 - s) * (1 - t) * c00 + s * (1 - t) * c10 + (1 - s) * t * c01 + s * t * c11))
            p.y += bulge * math.sin(math.pi * s) * math.sin(math.pi * t)
            grid[u][v] = len(verts)
            verts.append(tuple(p))
    out = []
    for u in range(nu):
        for v in range(nv):
            out.append((grid[u][v], grid[u + 1][v], grid[u + 1][v + 1], grid[u][v + 1]))
    return out


def build_cage():
    """Returns the cage object (not subdivided)."""
    b = cfg.V.body
    pivot = sec("rake_pivot")
    verts = []
    rings = []
    for y in b.stations:
        hs = half_section(y)
        ring = []
        # full loop: right side bottom->top is mirrored (x<0), left side top->bottom
        loop = [(-x, z) for x, z in hs] + [(x, z) for x, z in reversed(hs[1:-1])]
        for x, z in loop:
            ring.append(len(verts))
            yy = y + (pchip(b.rake, y) * (z - pivot) if y < 0 else -pchip(b.rake, y) * (z - pivot))
            verts.append((x, yy, z))
        rings.append(ring)
    n = len(rings[0])
    faces = []
    for a, bb in zip(rings, rings[1:]):
        for k in range(n):
            faces.append((a[k], a[(k + 1) % n], bb[(k + 1) % n], bb[k]))
    # cap both ends with a Coons-patch quad grid, bulged outward
    bf, br = b.get("cap_bulge", (-0.035, 0.03))
    for ri, bulge in ((0, bf), (len(rings) - 1, br)):
        faces += coons_cap(verts, rings[ri], bulge)
    ob = mesh_obj("BodyCage", verts, faces)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # creases on the character lines
    cl = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")
    creases = b.get("creases") or {P_SHOULDER: 0.95, P_ROCK: 0.6, P_GBASE: 0.45, P_ROOF: 0.5}
    end_crease = b.get("end_crease", 0.6)
    lookup = {}
    for k, w in creases.items():
        k = int(k)
        for side_k in (k, n - k):
            for ri in range(len(rings) - 1):
                lookup[frozenset((rings[ri][side_k], rings[ri + 1][side_k]))] = w
    for i in (0, len(rings) - 1):
        r = rings[i]
        for k in range(n):
            lookup[frozenset((r[k], r[(k + 1) % n]))] = end_crease
    bm.verts.index_update()
    for e in bm.edges:
        key = frozenset((e.verts[0].index, e.verts[1].index))
        if key in lookup:
            e[cl] = lookup[key]
    bm.to_mesh(ob.data)
    bm.free()
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def subdivide(ob, levels=2, decimate=1.0):
    from .geom import apply_mods
    m = ob.modifiers.new("subd", "SUBSURF")
    m.levels = levels
    m.render_levels = levels
    m.quality = 3
    apply_mods(ob)
    if decimate < 1.0:
        m = ob.modifiers.new("dec", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = decimate
        m.use_symmetry = True
        m.symmetry_axis = "X"
        apply_mods(ob)
    return ob
