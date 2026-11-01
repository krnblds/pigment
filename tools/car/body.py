"""The SubD body shell of the Kanzaki Tsubame-4 (a fictional 1994 four-door sedan).

The cage is lofted from 13-point half cross-sections (mirrored) taken at
stations along the car. Every section has the same point layout, so each
point index traces one longitudinal line of the body: the sill, the rocker
crease, the shoulder (the main character line), the greenhouse base, the
roof edge... In the hood and deck regions the greenhouse points lie on the
hood / deck surface; across the windshield and rear window they climb to the
roof, which is how the three-box sedan shape comes out of a single loft.
"""
import math

import bmesh
import bpy

from carlib import lerp, mesh_obj, pchip, smooth

# ------------------------------------------------------------------ dimensions
FRONT = -2.20         # bumper face (car faces -Y)
REAR = 2.24
AXLE_F = -1.33
AXLE_R = 1.32
WHEEL_R = 0.332       # tyre radius (225/50 R16-ish)
ARCH_R = 0.368        # wheel arch opening radius: ~3.5 cm over the tyre
TRACK = 1.585         # wheel centre to wheel centre: tyre faces flush with the body sides
BODY_DROP = 0.03      # the body is modelled 3 cm high and lowered at the end (ride height)
ARCH_Z = WHEEL_R + BODY_DROP   # wheel centre height in the (unlowered) body frame

# station y values: dense where the shape turns (nose, cowl, roof ends, deck, tail)
STATIONS = [-2.20, -2.185, -2.15, -2.08, -1.95, -1.60, -1.00, -0.84, -0.77, -0.70,
            -0.55, -0.35, -0.15, -0.02, 0.06, 0.40, 0.80, 0.92, 1.00, 1.15, 1.32, 1.50,
            1.58, 1.66, 2.02, 2.14, 2.20, 2.235]

# longitudinal keys
ZTOP = [(-2.20, 0.680), (-2.15, 0.738), (-2.05, 0.762), (-1.50, 0.810), (-0.84, 0.860), (-0.77, 0.880),
        (-0.55, 0.990), (-0.35, 1.110), (-0.15, 1.250), (-0.02, 1.330), (0.06, 1.360), (0.30, 1.385),
        (0.55, 1.388), (0.80, 1.372), (0.92, 1.335), (1.00, 1.295), (1.15, 1.205), (1.32, 1.100),
        (1.50, 1.008), (1.58, 0.982), (1.66, 0.975), (2.02, 0.968), (2.14, 0.958), (2.20, 0.935), (2.235, 0.880)]
# how far the roof-edge point drops below the centre line (windshield wrap)
DROP = [(-2.20, 0.012), (-0.84, 0.03), (-0.70, 0.065), (-0.15, 0.06), (0.06, 0.05), (0.80, 0.05),
        (1.00, 0.08), (1.50, 0.06), (1.66, 0.015), (2.24, 0.012)]
# half widths
WSIDE = [(-2.20, 0.640), (-2.185, 0.720), (-2.15, 0.790), (-2.08, 0.836), (-1.95, 0.866), (-1.60, 0.884),
         (0.30, 0.892), (1.66, 0.888), (2.02, 0.872), (2.14, 0.846), (2.20, 0.806), (2.235, 0.730)]
# roof edge half width: hood/deck values are just where the crown starts
WROOF = [(-2.20, 0.52), (-0.84, 0.60), (-0.70, 0.62), (-0.02, 0.655), (0.30, 0.665), (0.92, 0.66),
         (1.50, 0.64), (1.66, 0.62), (2.24, 0.56)]
# greenhouse base inset from the shoulder
WG_IN = [(-2.20, 0.04), (-0.84, 0.045), (-0.70, 0.05), (0.06, 0.055), (0.92, 0.055), (1.50, 0.05), (1.66, 0.045), (2.24, 0.04)]
ZBELT = [(-2.20, 0.625), (-2.15, 0.690), (-2.0, 0.730), (-1.0, 0.810), (-0.70, 0.840), (0.30, 0.870),
         (1.32, 0.900), (1.66, 0.915), (2.14, 0.920), (2.235, 0.850)]
ZFLOOR = [(-2.20, 0.300), (-2.15, 0.250), (-1.95, 0.205), (-1.70, 0.180), (1.75, 0.185), (2.02, 0.215),
          (2.20, 0.285), (2.235, 0.33)]
ZROCK = [(-2.20, 0.330), (-2.0, 0.300), (2.0, 0.305), (2.235, 0.36)]
# nose / tail rake: the end sections lean (chin forward, tail top back)
RAKE = [(-2.20, 0.10), (-2.15, 0.05), (-2.08, 0.0), (2.14, 0.0), (2.20, 0.03), (2.235, 0.05)]

# point indices along the half section (0 = bottom centre ... 12 = top centre)
P_SILL, P_ROCK, P_SHOULDER, P_GBASE, P_ROOF = 2, 3, 6, 7, 9
NP = 12


def half_section(y):
    zt = pchip(ZTOP, y)
    drop = pchip(DROP, y)
    ws = pchip(WSIDE, y)
    wr = min(pchip(WROOF, y), ws - 0.06)
    zb = pchip(ZBELT, y)
    zf = pchip(ZFLOOR, y)
    zr = min(pchip(ZROCK, y), zb - 0.12)
    wsh = ws - 0.028
    wg = wsh - pchip(WG_IN, y)
    # how "cabin" this section is: 0 over the hood / deck, 1 under the roof
    cab = min(smooth(-0.86, -0.70, y), 1 - smooth(1.52, 1.66, y))
    zg = zb + lerp(0.010, 0.030, cab)
    zroof = zt - drop
    if zroof < zg + 0.02:
        zroof = zg + 0.02
    # greenhouse mid point: on the hood it sits on the hood crown, in the
    # cabin it gives the side glass a slight outward curve
    xg9 = lerp(wg, wr, 0.5) + lerp(0.0, 0.012, cab)
    zg9 = lerp(zg, zroof, 0.5) + lerp(0.006, 0.0, cab)
    pts = [
        (0.0, zf),
        (ws - 0.11, zf),
        (ws - 0.07, zf + 0.04),
        (ws - 0.034, zr),
        (ws, zr + 0.55 * (zb - zr)),
        (ws - 0.010, zb - 0.035),
        (wsh, zb),
        (wg, zg),
        (xg9, zg9),
        (wr, zroof),
        (wr * 0.55, zt - drop * 0.30),
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
    verts = []
    rings = []
    for y in STATIONS:
        hs = half_section(y)
        ring = []
        # full loop: right side bottom->top is mirrored (x<0), left side top->bottom
        loop = [(-x, z) for x, z in hs] + [(x, z) for x, z in reversed(hs[1:-1])]
        for x, z in loop:
            ring.append(len(verts))
            yy = y + (pchip(RAKE, y) * (z - 0.48) if y < 0 else -pchip(RAKE, y) * (z - 0.48))
            verts.append((x, yy, z))
        rings.append(ring)
    n = len(rings[0])
    faces = []
    for a, b in zip(rings, rings[1:]):
        for k in range(n):
            faces.append((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
    # cap both ends with a Coons-patch quad grid (4 x 8), bulged outward
    for ri, bulge in ((0, -0.035), (len(rings) - 1, 0.03)):
        faces += coons_cap(verts, rings[ri], bulge)
    ob = mesh_obj("BodyCage", verts, faces)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # creases on the character lines
    cl = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")
    nring = n

    def idx_of(ring_i, k):
        return rings[ring_i][k]
    crease_lines = {P_SHOULDER: 0.95, P_ROCK: 0.6, P_GBASE: 0.45, P_ROOF: 0.5}
    lookup = {}
    for k, w in crease_lines.items():
        for side_k in (k, nring - k):
            for ri in range(len(rings) - 1):
                lookup[frozenset((idx_of(ri, side_k), idx_of(ri + 1, side_k)))] = w
    for i in (0, len(rings) - 1):
        r = rings[i]
        for k in range(n):
            lookup[frozenset((r[k], r[(k + 1) % n]))] = 0.6
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
    m = ob.modifiers.new("subd", "SUBSURF")
    m.levels = levels
    m.render_levels = levels
    m.quality = 3
    from carlib import apply_mods
    apply_mods(ob)
    if decimate < 1.0:
        # collapse in flat-ish areas only matters for budget; boundaries are cut later
        m = ob.modifiers.new("dec", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = decimate
        m.use_symmetry = True
        m.symmetry_axis = "X"
        apply_mods(ob)
    return ob
