"""Shared helpers for the car builder (headless Blender 5.2).

Coordinates are Blender's: metres, Z up, the car faces -Y (glTF +Z after
export), +X is the car's LEFT side.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector


# ------------------------------------------------------------------ interpolation


def pchip(keys, t):
    """Monotone cubic (Fritsch-Carlson) through [(t, v), ...] sorted by t."""
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    n = len(keys)
    xs = [k[0] for k in keys]
    ys = [k[1] for k in keys]
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * (xs[i + 1] - xs[i]) + (xs[i] - xs[i - 1])
            w2 = (xs[i + 1] - xs[i]) + 2 * (xs[i] - xs[i - 1])
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    i = max(j for j in range(n - 1) if xs[j] <= t)
    h = xs[i + 1] - xs[i]
    s = (t - xs[i]) / h
    h00 = 2 * s ** 3 - 3 * s ** 2 + 1
    h10 = s ** 3 - 2 * s ** 2 + s
    h01 = -2 * s ** 3 + 3 * s ** 2
    h11 = s ** 3 - s ** 2
    return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1]


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ objects


def coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def mesh_obj(name, verts, faces, collection=None, smooth_shade=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.validate(clean_customdata=False)
    me.update()
    ob = bpy.data.objects.new(name, me)
    (collection or bpy.context.scene.collection).objects.link(ob)
    if smooth_shade:
        for p in me.polygons:
            p.use_smooth = True
    return ob


def bm_obj(name, bm, collection=None, smooth_shade=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    (collection or bpy.context.scene.collection).objects.link(ob)
    for p in me.polygons:
        p.use_smooth = smooth_shade
    return ob


def apply_mods(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return ob


def apply_transform(ob):
    ob.data.transform(ob.matrix_basis)
    ob.matrix_basis = Matrix.Identity(4)


def delete(obs):
    for ob in list(obs):
        me = ob.data if ob.type == "MESH" else None
        bpy.data.objects.remove(ob, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)


def tag_material(name):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    return m


def set_material(ob, mat):
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    for p in ob.data.polygons:
        p.material_index = 0


def drop_faces_with_material(ob, name):
    """Delete faces whose material is `name` (cutter walls left by a boolean)."""
    mats = ob.data.materials
    bad = {i for i, m in enumerate(mats) if m is not None and m.name == name}
    if not bad:
        return ob
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    kill = [f for f in bm.faces if f.material_index in bad]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def cut(ob, cutter, op="DIFFERENCE", keep=False, tag="CUTTER"):
    """Manifold boolean that tags the cutter's faces with the CUTTER material.

    Both operands must be closed. Call `open_cuts(ob)` after the last cut to
    delete the cutter walls (or pass keep=False to do it right away)."""
    cm = tag_material(tag)
    targets = cutter.all_objects if isinstance(cutter, bpy.types.Collection) else [cutter]
    for c in targets:
        set_material(c, cm)
    if not ob.data.materials:
        set_material(ob, tag_material("SHELL"))
    bpy.context.view_layer.update()
    m = ob.modifiers.new("bool", "BOOLEAN")
    m.operation = op
    m.solver = "MANIFOLD"
    m.material_mode = "TRANSFER"
    if isinstance(cutter, bpy.types.Collection):
        m.operand_type = "COLLECTION"
        m.collection = cutter
    else:
        m.object = cutter
    apply_mods(ob)
    if not keep:
        open_cuts(ob)
    return ob


def open_cuts(ob):
    drop_faces_with_material(ob, "CUTTER")
    return ob


def boolean(ob, cutter, op="DIFFERENCE", solver="EXACT", hole_tolerant=False, self_intersect=False):
    m = ob.modifiers.new("bool", "BOOLEAN")
    m.operation = op
    m.solver = solver
    if solver == "EXACT":
        m.use_hole_tolerant = hole_tolerant
        m.use_self = self_intersect
    if isinstance(cutter, bpy.types.Collection):
        m.operand_type = "COLLECTION"
        m.collection = cutter
    else:
        m.object = cutter
    apply_mods(ob)
    return ob


def join(obs, name=None):
    obs = [o for o in obs if o is not None]
    base = obs[0]
    bm = bmesh.new()
    for o in obs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        # make every source's materials land in the right slot of the joined mesh
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    out = bpy.data.meshes.new(name or base.name)
    bm.to_mesh(out)
    bm.free()
    return out


def copy_obj(ob, name, collection=None):
    n = ob.copy()
    n.data = ob.data.copy()
    n.name = name
    (collection or bpy.context.scene.collection).objects.link(n)
    return n


# ------------------------------------------------------------------ primitives (bmesh)


def bm_box(bm, c, s, mat=None):
    """Axis box centre c, size s. Returns new verts."""
    m = Matrix.Translation(Vector(c)) @ Matrix.Diagonal((s[0], s[1], s[2], 1.0))
    r = bmesh.ops.create_cube(bm, size=1.0, matrix=m if mat is None else mat @ m)
    return r["verts"]


def bm_cyl(bm, c, r, depth, seg=24, axis="Z", r2=None, cap=True):
    rot = {"Z": Matrix.Identity(4), "X": Matrix.Rotation(math.pi / 2, 4, "Y"), "Y": Matrix.Rotation(math.pi / 2, 4, "X")}[axis]
    m = Matrix.Translation(Vector(c)) @ rot
    res = bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=depth, matrix=m)
    return res["verts"]


def bm_sphere(bm, c, r, seg=16, rings=8, scale=(1, 1, 1)):
    m = Matrix.Translation(Vector(c)) @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    return bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=rings, radius=r, matrix=m)["verts"]


def bm_tube_path(bm, pts, r, seg=8, closed=False):
    """A round tube along a 3D polyline (a sweep with parallel-transport frames)."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    rings = []
    prev_nrm = None
    for i, p in enumerate(pts):
        if closed:
            t = (pts[(i + 1) % n] - pts[i - 1]).normalized()
        else:
            a = pts[max(0, i - 1)]
            b = pts[min(n - 1, i + 1)]
            t = (b - a).normalized()
        if prev_nrm is None:
            up = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
            nrm = t.cross(up).normalized()
        else:
            nrm = (prev_nrm - t * prev_nrm.dot(t)).normalized()
        prev_nrm = nrm
        bin_ = t.cross(nrm)
        ring = []
        for k in range(seg):
            a = 2 * math.pi * k / seg
            ring.append(bm.verts.new(p + (nrm * math.cos(a) + bin_ * math.sin(a)) * r))
        rings.append(ring)
    segs = n if closed else n - 1
    for i in range(segs):
        A, B = rings[i], rings[(i + 1) % n]
        for k in range(seg):
            bm.faces.new((A[k], A[(k + 1) % seg], B[(k + 1) % seg], B[k]))
    if not closed:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    return rings


def bm_prism(bm, poly, axis, a0, a1):
    """Extrude a closed 2D polygon (in the plane normal to `axis`) from a0 to a1.

    axis "X": poly is (y, z); "Y": (x, z); "Z": (x, y). Makes a closed solid."""
    def p3(u, v, w):
        if axis == "X":
            return Vector((w, u, v))
        if axis == "Y":
            return Vector((u, w, v))
        return Vector((u, v, w))
    # orient the polygon counter-clockwise
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    if area < 0:
        poly = list(reversed(poly))
    lo = [bm.verts.new(p3(u, v, a0)) for u, v in poly]
    hi = [bm.verts.new(p3(u, v, a1)) for u, v in poly]
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.verts[0] in lo or f.verts[0] in hi])
    return lo + hi


def offset_polyline(pts, w, closed=False):
    """Offset a 2D polyline by +-w/2: returns (left, right) point lists (miter joins)."""
    n = len(pts)
    left, right = [], []
    for i in range(n):
        if closed:
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        else:
            a = pts[max(0, i - 1)]
            b = pts[i]
            c = pts[min(n - 1, i + 1)]
        d1 = Vector((b[0] - a[0], b[1] - a[1]))
        d2 = Vector((c[0] - b[0], c[1] - b[1]))
        if d1.length < 1e-9:
            d1 = d2
        if d2.length < 1e-9:
            d2 = d1
        d1.normalize()
        d2.normalize()
        n1 = Vector((-d1.y, d1.x))
        n2 = Vector((-d2.y, d2.x))
        nm = (n1 + n2)
        if nm.length < 1e-6:
            nm = n1
        nm.normalize()
        k = 1.0 / max(0.3, nm.dot(n1))
        left.append((b[0] + nm.x * w / 2 * k, b[1] + nm.y * w / 2 * k))
        right.append((b[0] - nm.x * w / 2 * k, b[1] - nm.y * w / 2 * k))
    return left, right


def bm_gap_cutter(bm, pts, axis, a0, a1, w=0.004, closed=False):
    """A thin solid along a 2D shut line, extruded along `axis` between a0 and a1."""
    L, R = offset_polyline(pts, w, closed)
    def p3(u, v, t):
        if axis == "X":
            return Vector((t, u, v))
        if axis == "Y":
            return Vector((u, t, v))
        return Vector((u, v, t))
    n = len(pts)
    VL0 = [bm.verts.new(p3(u, v, a0)) for u, v in L]
    VR0 = [bm.verts.new(p3(u, v, a0)) for u, v in R]
    VL1 = [bm.verts.new(p3(u, v, a1)) for u, v in L]
    VR1 = [bm.verts.new(p3(u, v, a1)) for u, v in R]
    segs = n if closed else n - 1
    faces = []
    for i in range(segs):
        j = (i + 1) % n
        faces.append(bm.faces.new((VL0[i], VL0[j], VR0[j], VR0[i])))
        faces.append(bm.faces.new((VL1[i], VR1[i], VR1[j], VL1[j])))
        faces.append(bm.faces.new((VL0[i], VL1[i], VL1[j], VL0[j])))
        faces.append(bm.faces.new((VR0[i], VR0[j], VR1[j], VR1[i])))
    if not closed:
        faces.append(bm.faces.new((VL0[0], VR0[0], VR1[0], VL1[0])))
        faces.append(bm.faces.new((VL0[-1], VL1[-1], VR1[-1], VR0[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


def ngon_points(cx, cy, rx, ry, n, start=0.0):
    return [(cx + rx * math.cos(start + 2 * math.pi * i / n), cy + ry * math.sin(start + 2 * math.pi * i / n)) for i in range(n)]


def rounded_rect(x0, y0, x1, y1, r, seg=4):
    pts = []
    corners = [(x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270)]
    for cx, cy, a0 in corners:
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts
