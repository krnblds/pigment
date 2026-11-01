"""Modelling kit for the street props (headless Blender 5.2, bpy + bmesh).

A prop is built into ONE bmesh. Every primitive call adds a *piece*: a closed,
disconnected surface tagged with a name and a material *group* (an int face
layer "piece").  Pigment splits a mesh into parts by connectivity, so every
piece becomes its own Pigment part, and tools/props/props_textures.py maps the
parts back to the groups with the records written here.

Axes (Blender): Z up, the prop's FRONT faces -Y (glTF +Z after the Y-up export),
origin on the ground at the footprint centre.  All sizes in metres.

    P = Prop("bench")
    P.box("seat", "wood", size=(1.8, 0.45, 0.04), loc=(0, 0, 0.45), bevel=0.006)
    P.cyl("leg", "steel", r=0.03, h=0.45, loc=(0.8, 0, 0))
    P.light("Light_Lamp", (0, 0, 2.5), color=(1, .8, .5), energy=40, range=6)
    P.collider = ("box",)
"""
import math

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

TAU = math.tau


def _mat(loc=(0, 0, 0), rot=(0, 0, 0), scale=None):
    m = Matrix.Translation(Vector(loc)) @ Euler([math.radians(a) for a in rot], "XYZ").to_matrix().to_4x4()
    if scale is not None:
        s = scale if isinstance(scale, (tuple, list)) else (scale, scale, scale)
        m = m @ Matrix.Diagonal((s[0], s[1], s[2], 1.0))
    return m


def gl(v):
    """Blender (x, y, z) -> glTF / Godot (x, z, -y)."""
    return [round(v[0], 4), round(v[2], 4), round(-v[1], 4)]


class Piece:
    __slots__ = ("id", "name", "group", "node", "uv_boost")

    def __init__(self, i, name, group, node, uv_boost):
        self.id, self.name, self.group, self.node, self.uv_boost = i, name, group, node, uv_boost


class Prop:
    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.layer = self.bm.faces.layers.int.new("piece")
        self.pieces = []
        self.lights = []      # {name, pos (blender), type, color, energy, range, dir}
        self.sockets = []     # {name, pos, dir, kind}: steam emitter, signal lamps...
        self.collider = ("box",)
        self.meta = {}        # anything extra the builder wants in the index (signals...)

    # ------------------------------------------------------------------ bookkeeping
    def _begin(self):
        # bmesh reuses freed slots (bevel kills faces), so new faces are found by their layer
        # value: 0 = not assigned yet, piece ids start at 1
        return 0

    def _end(self, n0, name, group, node=None, uv_boost=1.0, smooth=True):
        p = Piece(len(self.pieces) + 1, name, group, node, uv_boost)
        self.pieces.append(p)
        for f in self._new_faces(n0):
            f[self.layer] = p.id
            f.smooth = smooth
        return p

    def _new_faces(self, n0=0):
        return [f for f in self.bm.faces if f[self.layer] == 0]

    def _bevel(self, n0, width, segments=1):
        if width <= 0:
            return
        faces = self._new_faces(n0)
        edges = list({e for f in faces for e in f.edges})
        bmesh.ops.bevel(self.bm, geom=edges, offset=width, offset_type="OFFSET", segments=segments,
                        profile=0.5, affect="EDGES", clamp_overlap=True)

    # ------------------------------------------------------------------ primitives
    def box(self, name, group, size, loc=(0, 0, 0), rot=(0, 0, 0), bevel=0.0, seg=1, base=False, node=None, uv_boost=1.0):
        """Axis box of `size`, centred at `loc` (base=True: loc is the bottom centre)."""
        n0 = self._begin()
        loc = Vector(loc)
        if base:
            loc = loc + (_mat(rot=rot).to_3x3() @ Vector((0, 0, size[2] / 2)))
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=_mat(loc, rot, size))
        self._bevel(n0, min(bevel, min(size) * 0.45), seg)
        return self._end(n0, name, group, node, uv_boost)

    def cyl(self, name, group, r, h, loc=(0, 0, 0), rot=(0, 0, 0), segs=16, r2=None, bevel=0.0, node=None, uv_boost=1.0, center=False):
        """Cylinder / cone along local Z, base at `loc` (center=True: centred)."""
        n0 = self._begin()
        off = 0 if center else h / 2
        m = _mat(loc, rot) @ Matrix.Translation((0, 0, off))
        bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r,
                              radius2=r if r2 is None else r2, depth=h, matrix=m)
        self._bevel(n0, min(bevel, r * 0.4, h * 0.3), 1)
        return self._end(n0, name, group, node, uv_boost)

    def lathe(self, name, group, profile, loc=(0, 0, 0), rot=(0, 0, 0), segs=20, node=None, uv_boost=1.0, scale=None):
        """Surface of revolution about local Z.  profile: [(r, z), ...] bottom to top;
        r == 0 at an end closes it with a fan, otherwise the end gets an n-gon cap."""
        n0 = self._begin()
        bm = self.bm
        m = _mat(loc, rot, scale)
        rings = []
        for (r, z) in profile:
            if r <= 1e-6:
                rings.append([bm.verts.new(m @ Vector((0, 0, z)))])
            else:
                rings.append([bm.verts.new(m @ Vector((r * math.cos(TAU * i / segs), r * math.sin(TAU * i / segs), z)))
                              for i in range(segs)])
        for a, b in zip(rings, rings[1:]):
            if len(a) == 1 and len(b) == 1:
                continue
            for i in range(segs):
                j = (i + 1) % segs
                if len(a) == 1:
                    bm.faces.new((a[0], b[i], b[j]))
                elif len(b) == 1:
                    bm.faces.new((a[i], a[j], b[0]))
                else:
                    bm.faces.new((a[i], a[j], b[j], b[i]))
        if len(rings[0]) > 1:
            bm.faces.new(list(reversed(rings[0])))
        if len(rings[-1]) > 1:
            bm.faces.new(rings[-1])
        return self._end(n0, name, group, node, uv_boost)

    def sweep(self, name, group, pts, r, segs=8, closed=False, caps=True, node=None, uv_boost=1.0, radii=None):
        """Tube of radius r along a polyline (parallel-transport frames)."""
        n0 = self._begin()
        bm = self.bm
        P = [Vector(p) for p in pts]
        n = len(P)
        tans = []
        for i in range(n):
            if closed:
                t = P[(i + 1) % n] - P[i - 1]
            else:
                t = P[min(i + 1, n - 1)] - P[max(i - 1, 0)]
            tans.append(t.normalized())
        up = Vector((0, 0, 1)) if abs(tans[0].z) < 0.9 else Vector((1, 0, 0))
        nrm = tans[0].cross(up).normalized()
        rings = []
        for i in range(n):
            if i:
                axis = tans[i - 1].cross(tans[i])
                if axis.length > 1e-6:
                    ang = tans[i - 1].angle(tans[i])
                    nrm = (Matrix.Rotation(ang, 3, axis.normalized()) @ nrm).normalized()
            bn = tans[i].cross(nrm).normalized()
            rr = radii[i] if radii else r
            rings.append([bm.verts.new(P[i] + (nrm * math.cos(TAU * k / segs) + bn * math.sin(TAU * k / segs)) * rr) for k in range(segs)])
        last = n if closed else n - 1
        for i in range(last):
            a, b = rings[i], rings[(i + 1) % n]
            for k in range(segs):
                j = (k + 1) % segs
                bm.faces.new((a[k], a[j], b[j], b[k]))
        if caps and not closed:
            bm.faces.new(list(reversed(rings[0])))
            bm.faces.new(rings[-1])
        return self._end(n0, name, group, node, uv_boost)

    def prism(self, name, group, poly, depth, loc=(0, 0, 0), rot=(0, 0, 0), bevel=0.0, node=None, uv_boost=1.0, smooth=True):
        """Extrude a 2D polygon [(x, z), ...] (counter-clockwise seen from -Y) along +Y by `depth`,
        centred on Y.  Rotate it to lay the profile elsewhere."""
        n0 = self._begin()
        bm = self.bm
        m = _mat(loc, rot)
        a = [bm.verts.new(m @ Vector((x, -depth / 2, z))) for (x, z) in poly]
        b = [bm.verts.new(m @ Vector((x, depth / 2, z))) for (x, z) in poly]
        k = len(poly)
        bm.faces.new(a)
        bm.faces.new(list(reversed(b)))
        for i in range(k):
            j = (i + 1) % k
            bm.faces.new((a[j], a[i], b[i], b[j]))
        faces = self._new_faces(n0)
        bmesh.ops.recalc_face_normals(bm, faces=list(faces))
        self._bevel(n0, bevel, 1)
        return self._end(n0, name, group, node, uv_boost, smooth)

    def blob(self, name, group, r, loc=(0, 0, 0), scale=(1, 1, 1), rot=(0, 0, 0), subdiv=2, noise=0.15, seed=0, flat_bottom=None, node=None, uv_boost=1.0):
        """Lumpy ellipsoid (trash bags, foliage clumps).  flat_bottom: clamp z >= that (local)."""
        n0 = self._begin()
        bm = self.bm
        ret = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=r, matrix=Matrix())
        vs = ret["verts"]
        import random
        rnd = random.Random(seed)
        waves = [(Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))).normalized(), rnd.uniform(2, 5), rnd.uniform(0, TAU)) for _ in range(5)]
        for v in vs:
            d = v.co.normalized()
            k = 1 + noise * sum(math.sin(d.dot(w) * f + ph) for w, f, ph in waves) / len(waves) * 2
            v.co = v.co * k
            if flat_bottom is not None and v.co.z < flat_bottom:
                v.co.z = flat_bottom
        bmesh.ops.transform(bm, matrix=_mat(loc, rot, scale), verts=vs)
        return self._end(n0, name, group, node, uv_boost)

    def torus(self, name, group, R, r, loc=(0, 0, 0), rot=(0, 0, 0), segs=24, rsegs=8, arc=360.0, node=None, uv_boost=1.0):
        pts = []
        full = arc >= 359.9
        n = segs if full else segs + 1
        for i in range(n):
            a = math.radians(arc) * i / segs
            pts.append((R * math.cos(a), R * math.sin(a), 0))
        m = _mat(loc, rot)
        pts = [tuple(m @ Vector(p)) for p in pts]
        return self.sweep(name, group, pts, r, segs=rsegs, closed=full, node=node, uv_boost=uv_boost)

    def quad(self, name, group, w, h, loc=(0, 0, 0), rot=(0, 0, 0), node=None, uv_boost=1.0, two_sided=False):
        """Flat rectangle in local XY (normal +Z)."""
        n0 = self._begin()
        bm = self.bm
        m = _mat(loc, rot)
        vs = [bm.verts.new(m @ Vector(c)) for c in ((-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0))]
        bm.faces.new(vs)
        if two_sided:
            vs2 = [bm.verts.new(m @ Vector(c)) for c in ((-w / 2, -h / 2, -0.001), (-w / 2, h / 2, -0.001), (w / 2, h / 2, -0.001), (w / 2, -h / 2, -0.001))]
            bm.faces.new(vs2)
        return self._end(n0, name, group, node, uv_boost, smooth=False)

    def grid(self, name, group, w, h, nx, ny, loc=(0, 0, 0), rot=(0, 0, 0), fn=None, node=None, uv_boost=1.0):
        """Subdivided rectangle in local XY; fn(x, y) -> z displacement (cloth, tarps)."""
        n0 = self._begin()
        bm = self.bm
        m = _mat(loc, rot)
        V = [[bm.verts.new(m @ Vector((-w / 2 + w * i / nx, -h / 2 + h * j / ny, fn(-w / 2 + w * i / nx, -h / 2 + h * j / ny) if fn else 0)))
              for i in range(nx + 1)] for j in range(ny + 1)]
        for j in range(ny):
            for i in range(nx):
                bm.faces.new((V[j][i], V[j][i + 1], V[j + 1][i + 1], V[j + 1][i]))
        return self._end(n0, name, group, node, uv_boost)

    def solidify_last(self, thickness):
        """Give the last piece (an open sheet) thickness, keeping it one closed piece."""
        p = self.pieces[-1]
        faces = [f for f in self.bm.faces if f[self.layer] == p.id]
        n0 = self._begin()
        bmesh.ops.solidify(self.bm, geom=faces, thickness=thickness)
        for f in self._new_faces(n0):
            f[self.layer] = p.id
            f.smooth = True
        return p

    def ribbon(self, name, group, pts, widths, side, fold=0.0, thickness=0.006, node=None, uv_boost=1.0, cols=2):
        """A thin closed strip (leaf, frond, curtain) along a polyline.
        side: unit vector across the strip (kept perpendicular to the path); fold lifts the edges
        (V shape) along the strip normal by fold * half-width."""
        n0 = self._begin()
        bm = self.bm
        P = [Vector(p) for p in pts]
        sv = Vector(side).normalized()
        top, bot = [], []
        for i, p in enumerate(P):
            t = (P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]).normalized()
            s = (sv - t * sv.dot(t)).normalized()
            nrm = t.cross(s).normalized()
            w = widths[i] / 2
            rowt, rowb = [], []
            for k in range(cols + 1):
                u = -1 + 2 * k / cols
                q = p + s * (u * w) + nrm * (fold * abs(u) * w)
                rowt.append(bm.verts.new(q + nrm * thickness / 2))
                rowb.append(bm.verts.new(q - nrm * thickness / 2))
            top.append(rowt)
            bot.append(rowb)
        n = len(P)
        for i in range(n - 1):
            for k in range(cols):
                bm.faces.new((top[i][k], top[i][k + 1], top[i + 1][k + 1], top[i + 1][k]))
                bm.faces.new((bot[i][k], bot[i + 1][k], bot[i + 1][k + 1], bot[i][k + 1]))
            bm.faces.new((top[i][0], top[i + 1][0], bot[i + 1][0], bot[i][0]))
            bm.faces.new((top[i][cols], bot[i][cols], bot[i + 1][cols], top[i + 1][cols]))
        for i in (0, n - 1):
            for k in range(cols):
                f = (top[i][k], bot[i][k], bot[i][k + 1], top[i][k + 1])
                bm.faces.new(f if i == 0 else tuple(reversed(f)))
        return self._end(n0, name, group, node, uv_boost)

    def transform_all(self, loc=(0, 0, 0), rot=(0, 0, 0)):
        """Move / rotate everything built so far (and the hints) about the origin."""
        m = _mat(loc, rot)
        bmesh.ops.transform(self.bm, matrix=m, verts=self.bm.verts)
        for d in self.lights + self.sockets:
            d["pos"] = tuple(m @ Vector(d["pos"]))

    # ------------------------------------------------------------------ hints
    def light(self, name, pos, kind="omni", color=(1, 1, 1), energy=1.0, range=5.0, dir=None, shadow=False):
        self.lights.append({"name": name, "pos": tuple(pos), "type": kind, "color": list(color), "energy": energy,
                            "range": range, "dir": list(dir) if dir else None, "shadow": shadow})

    def socket(self, name, pos, kind, dir=None, **extra):
        d = {"name": name, "pos": tuple(pos), "kind": kind, "dir": list(dir) if dir else None}
        d.update(extra)
        self.sockets.append(d)

    # ------------------------------------------------------------------ finishing
    def _components(self):
        """Connected components (by shared vertex) -> list of (piece id, [faces])."""
        bm = self.bm
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        seen = set()
        comps = []
        for f in bm.faces:
            if f.index in seen:
                continue
            stack = [f]
            seen.add(f.index)
            comp = []
            while stack:
                g = stack.pop()
                comp.append(g)
                for v in g.verts:
                    for h in v.link_faces:
                        if h.index not in seen:
                            seen.add(h.index)
                            stack.append(h)
            comps.append((comp[0][self.layer], comp))
        return comps

    def to_object(self, collection=None, sharp_deg=35.0):
        """Weld nothing, mark sharp edges by angle, build the object with UVs (see uv_unwrap)."""
        bm = self.bm
        bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.calc_area() > 0])
        cos_t = math.cos(math.radians(sharp_deg))
        for e in bm.edges:
            if len(e.link_faces) == 2:
                a, b = e.link_faces
                e.smooth = a.normal.dot(b.normal) > cos_t and a.smooth and b.smooth
            else:
                e.smooth = False
        for f in bm.faces:
            f.smooth = True
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        ob = bpy.data.objects.new(self.name, me)
        (collection or bpy.context.scene.collection).objects.link(ob)
        return ob

    def records(self):
        """Per connected component: piece name, group, glTF-space bbox (for matching Pigment parts)."""
        out = []
        for pid, faces in self._components():
            vs = {v for f in faces for v in f.verts}
            lo = [min(v.co[i] for v in vs) for i in range(3)]
            hi = [max(v.co[i] for v in vs) for i in range(3)]
            c = gl([(lo[i] + hi[i]) / 2 for i in range(3)])
            s = [hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1]]
            p = self.pieces[pid - 1]
            out.append({"piece": p.name, "group": p.group, "node": p.node, "center": c, "size": [round(x, 4) for x in s],
                        "tris": sum(len(f.verts) - 2 for f in faces)})
        return out

    def bounds(self):
        vs = self.bm.verts
        lo = [min(v.co[i] for v in vs) for i in range(3)]
        hi = [max(v.co[i] for v in vs) for i in range(3)]
        return lo, hi


def uv_unwrap(ob, pieces, angle=55.0, margin=0.004):
    """Smart-project every piece, give all islands the same texel density, boost the
    pieces that carry text (screens, ads, signs: Piece.uv_boost), and pack into 0..1."""
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    if not ob.data.uv_layers:
        ob.data.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=0.0, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode="OBJECT")
    boost = {p.id: p.uv_boost for p in pieces if p.uv_boost != 1.0}
    if boost:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        lay = bm.faces.layers.int["piece"]
        uv = bm.loops.layers.uv.active
        for f in bm.faces:
            b = boost.get(f[lay])
            if b:
                for l in f.loops:
                    l[uv].uv = l[uv].uv * b
        bm.to_mesh(ob.data)
        bm.free()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, scale=True, margin_method="FRACTION", margin=margin, shape_method="AABB")
    bpy.ops.object.mode_set(mode="OBJECT")


def texel_density(ob, res):
    """Texels per metre at `res` (median over faces)."""
    me = ob.data
    uv = me.uv_layers.active.data
    ds = []
    for poly in me.polygons:
        if poly.area < 1e-6:
            continue
        a = 0.0
        idx = list(poly.loop_indices)
        p0 = uv[idx[0]].uv
        for i in range(1, len(idx) - 1):
            p1, p2 = uv[idx[i]].uv, uv[idx[i + 1]].uv
            a += abs((p1.x - p0.x) * (p2.y - p0.y) - (p2.x - p0.x) * (p1.y - p0.y)) / 2
        if a > 0:
            ds.append(math.sqrt(a / poly.area) * res)
    ds.sort()
    return ds[len(ds) // 2] if ds else 0.0


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
