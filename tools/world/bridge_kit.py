"""Bridges as engineered structures (Blender 5.2): geometry helpers and materials.

The builders are in bridge_designs.py. This module has

    BM          bmesh builder with per-material metre UVs (scaled to each Pigment tile at the end),
                explicit outward hints (Godot culls back faces), boxes in any frame, tubes, lofts
                and sweeps along a road path
    Rail        stations along a road path (blender_town.Path): position, tangent, left normal
    materials() the bridge materials: Pigment sheets from tools/world/bridge_textures.py
                (custom props pigment_folder / pigment_name -> Godot ORM material), emissive
                lights, the uplight wash cards (image + alpha + emission)

Object naming (tools/godot/export_town.py COLLIDE, game/scripts/town_loader.gd):
    Girder_<b>          deck structure                 trimesh collision, always drawn
    Bridge_<b>_<part>   pylons, piers, arch ribs       trimesh collision, always drawn
    BridgeDetail_<b>    railings, catwalks, bearings,  no collision, drawn within 700 m
                        drains, signs, gantry, crane
    BridgeCables_<b>    stays / hangers as tubes       no collision, drawn within 450 m
    BridgeCablesFar_<b> the same as flat ribbons       no collision, drawn beyond 450 m
    BridgeWash_<b>      uplight wash cards             no collision, no shadows
"""
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

UP = Vector((0, 0, 1))

# Pigment sheets (tools/world/bridge_textures.py TILE): metres per repeat (u, v)
SHEETS = {
    "concrete": ("bridge_concrete", (4.8, 4.8), (0.43, 0.42, 0.4), 0.88, 0.0),
    "steel_white": ("bridge_steel_white", (4.0, 4.0), (0.72, 0.73, 0.72), 0.45, 0.0),
    "steel_weather": ("bridge_steel_weather", (4.0, 4.0), (0.24, 0.1, 0.05), 0.82, 0.15),
    "steel_grey": ("bridge_steel_grey", (2.0, 2.0), (0.33, 0.35, 0.36), 0.5, 0.35),
    "cable": ("bridge_cable", (1.0, 1.0), (0.7, 0.7, 0.68), 0.35, 0.0),
    "hoarding": ("bridge_hoarding", (6.0, 3.0), (0.04, 0.05, 0.09), 0.55, 0.0),
    "hazard": ("bridge_hazard", (2.0, 2.0), (0.6, 0.45, 0.05), 0.6, 0.0),
}
FLAT = {
    #               colour                 rough metal
    "rubber": ((0.025, 0.025, 0.028), 0.85, 0.0),
    "crane": ((0.85, 0.6, 0.05), 0.5, 0.1),
    "grating": ((0.12, 0.13, 0.14), 0.6, 0.6),
    "glass": ((0.06, 0.08, 0.09), 0.08, 0.2),
    "gold": ((0.75, 0.52, 0.18), 0.3, 1.0),
}
EMIT = {
    "red_light": ((1.0, 0.04, 0.02), 30.0),
    "lamp": ((1.0, 0.8, 0.55), 18.0),
    "lamp_cool": ((0.85, 0.92, 1.0), 14.0),
    "plaque": ((1.0, 0.8, 0.45), 2.5),
}
WASH = ("wash_warm", "wash_cool")      # assets/decals/bridges/<key>.png


def tile_of(key):
    return SHEETS[key][1] if key in SHEETS else (1.0, 1.0)


# ---------------------------------------------------------------- mesh builder
class BM:
    def __init__(self, keys):
        self.keys = list(keys)
        self.idx = {k: i for i, k in enumerate(self.keys)}
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.nf = 0

    def has(self, key):
        return key in self.idx

    def face(self, pts, key, uvs, out=None, smooth=False):
        """pts: Vectors, uvs in metres; out: a direction the face should face (winding is
        flipped to match), or None to keep the given order."""
        if out is not None:
            n = Vector((0, 0, 0))
            for k in range(len(pts)):
                a, c = pts[k], pts[(k + 1) % len(pts)]
                n += Vector(((a.y - c.y) * (a.z + c.z), (a.z - c.z) * (a.x + c.x), (a.x - c.x) * (a.y + c.y)))
            if n.dot(out) < 0:
                pts, uvs = pts[::-1], uvs[::-1]
        try:
            f = self.bm.faces.new([self.bm.verts.new(p) for p in pts])
        except ValueError:
            return None
        f.material_index = self.idx[key]
        f.smooth = smooth
        for lp, uv in zip(f.loops, uvs):
            lp[self.uv].uv = uv
        self.nf += 1
        return f

    def quad_planar(self, pts, key, out, ax_u=None):
        """Planar quad / polygon with UVs projected in its plane: v along the plane's up (or ax_u x n
        for flat faces), anchored at the first point's world position (so neighbours match)."""
        n = out.normalized()
        if abs(n.z) < 0.75:
            v_ax = (UP - n * n.dot(UP)).normalized()
            u_ax = v_ax.cross(n).normalized()
        else:
            u_ax = (ax_u or Vector((1, 0, 0))).copy()
            u_ax = (u_ax - n * n.dot(u_ax)).normalized()
            v_ax = n.cross(u_ax).normalized()
        uvs = [(p.dot(u_ax), p.dot(v_ax)) for p in pts]
        return self.face(pts, key, uvs, out)

    def box(self, c, X, Y, Z, size, key, faces="all"):
        """Box centred at c in the frame (X, Y, Z) (unit vectors), size (sx, sy, sz)."""
        c = Vector(c)
        X, Y, Z = Vector(X).normalized(), Vector(Y).normalized(), Vector(Z).normalized()
        hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2

        def P(a, b, d):
            return c + X * (a * hx) + Y * (b * hy) + Z * (d * hz)
        sides = {
            "+x": ([P(1, -1, -1), P(1, 1, -1), P(1, 1, 1), P(1, -1, 1)], X),
            "-x": ([P(-1, 1, -1), P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1)], -X),
            "+y": ([P(1, 1, -1), P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1)], Y),
            "-y": ([P(-1, -1, -1), P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1)], -Y),
            "+z": ([P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1)], Z),
            "-z": ([P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), P(-1, -1, -1)], -Z),
        }
        for k, (pts, o) in sides.items():
            if faces != "all" and k not in faces:
                continue
            self.quad_planar(pts, key, o, ax_u=X)

    def beam(self, a, b, w, h, key, up=None, faces="all"):
        """Rectangular member from a to b, w wide, h tall (h along `up` projected)."""
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        if L < 1e-4:
            return
        X = d / L
        up = Vector(up) if up is not None else (UP if abs(X.z) < 0.95 else Vector((1, 0, 0)))
        Z = (up - X * X.dot(up)).normalized()
        Y = Z.cross(X)
        self.box((a + b) / 2, X, Y, Z, (L, w, h), key, faces)

    def tube(self, a, b, r, key, seg=8, r2=None, caps=False, smooth=True):
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        if L < 1e-5:
            return
        q = d.normalized().to_track_quat("Z", "Y")
        M = Matrix.Translation(a) @ q.to_matrix().to_4x4()
        r2 = r if r2 is None else r2
        R0 = [M @ Vector((r * math.cos(2 * math.pi * k / seg), r * math.sin(2 * math.pi * k / seg), 0)) for k in range(seg)]
        R1 = [M @ Vector((r2 * math.cos(2 * math.pi * k / seg), r2 * math.sin(2 * math.pi * k / seg), L)) for k in range(seg)]
        circ = 2 * math.pi * max(r, r2)
        for k in range(seg):
            k2 = (k + 1) % seg
            u0, u1 = circ * k / seg, circ * (k + 1) / seg
            mid = (R0[k] + R0[k2] + R1[k] + R1[k2]) / 4
            ax = a + d.normalized() * (mid - a).dot(d.normalized())
            self.face([R0[k], R0[k2], R1[k2], R1[k]], key, [(u0, 0), (u1, 0), (u1, L), (u0, L)], mid - ax, smooth)
        if caps:
            self.face(R1, key, [(p - b).to_2d()[:] for p in R1], d)
            self.face(R0, key, [(p - a).to_2d()[:] for p in R0], -d)

    def loft(self, rings, key, cap_top=True, cap_bottom=False, smooth=False, vz=True):
        """Closed rings (lists of Vectors, same count) stacked bottom to top. UVs: u around the
        perimeter, v = world z (vz) or distance up the loft."""
        n = len(rings[0])
        cen = [sum(r, Vector()) / n for r in rings]
        acc = [0.0]
        for i in range(1, len(rings)):
            acc.append(acc[-1] + (cen[i] - cen[i - 1]).length)
        for i in range(len(rings) - 1):
            A, B = rings[i], rings[i + 1]
            u = 0.0
            for k in range(n):
                k2 = (k + 1) % n
                L = (A[k2] - A[k]).length
                va, vb = (A[k].z, B[k].z) if vz else (acc[i], acc[i + 1])
                va2, vb2 = (A[k2].z, B[k2].z) if vz else (acc[i], acc[i + 1])
                mid = (A[k] + A[k2] + B[k] + B[k2]) / 4
                cm = (cen[i] + cen[i + 1]) / 2
                self.face([A[k], A[k2], B[k2], B[k]], key, [(u, va), (u + L, va2), (u + L, vb2), (u, vb)], mid - cm, smooth)
                u += L
        if cap_top:
            r = rings[-1]
            ax = cen[-1] - cen[-2]
            self.face(list(r), key, [(p.x, p.y) for p in r], ax if ax.length > 1e-6 else UP)
        if cap_bottom:
            r = rings[0]
            ax = cen[0] - cen[1]
            self.face(list(r), key, [(p.x, p.y) for p in r], ax if ax.length > 1e-6 else -UP)

    def sweep(self, rail, prof, key, i0=0, i1=None, closed=False, out=None, smooth=False):
        """Sweep a cross-section (y lateral +left, z up, both relative to the path point) along
        rail stations i0..i1. Faces of a closed section face outwards (from the polygon's
        winding); open strips face `out` (a (y, z) direction in the section) or, without it,
        the side the winding would put outwards. UVs: u = along the path,
        v = distance across the section, signed so v grows upwards on webs."""
        i1 = rail.n - 1 if i1 is None else i1
        pts = list(prof) + ([prof[0]] if closed else [])
        acc = [0.0]
        for (y0, z0), (y1, z1) in zip(pts, pts[1:]):
            L = math.hypot(y1 - y0, z1 - z0)
            acc.append(acc[-1] + (L if abs(z1 - z0) <= abs(y1 - y0) else math.copysign(L, z1 - z0)))
        orient = _orient(prof)
        for k in range(len(pts) - 1):
            (y0, z0), (y1, z1) = pts[k], pts[k + 1]
            if out is not None:
                oy, oz = out
            else:
                oy, oz = (z1 - z0) * orient, -(y1 - y0) * orient
            for i in range(i0, i1):
                j = i + 1
                q = [rail.P(i, y0, z0), rail.P(j, y0, z0), rail.P(j, y1, z1), rail.P(i, y1, z1)]
                o = Vector((rail.nrm[i][0] * oy, rail.nrm[i][1] * oy, oz))
                ua, ub = rail.u[i], rail.u[j]
                self.face(q, key, [(ua, acc[k]), (ub, acc[k]), (ub, acc[k + 1]), (ua, acc[k + 1])], o, smooth)

    def sweep_var(self, rail, prof_fn, key, i0=0, i1=None, closed=True, smooth=False):
        """Like sweep, but the section changes per station: prof_fn(i) -> [(y, z)] (same count)."""
        i1 = rail.n - 1 if i1 is None else i1
        P0 = prof_fn(i0)
        m = len(P0) + (1 if closed else 0)
        prev = P0
        for i in range(i0, i1):
            cur = prof_fn(i + 1)
            A = list(prev) + ([prev[0]] if closed else [])
            B = list(cur) + ([cur[0]] if closed else [])
            orient = _orient(prev)
            v = 0.0
            for k in range(m - 1):
                (y0, z0), (y1, z1) = A[k], A[k + 1]
                (y2, z2), (y3, z3) = B[k], B[k + 1]
                L = math.hypot(y1 - y0, z1 - z0)
                dv = L if abs(z1 - z0) <= abs(y1 - y0) else math.copysign(L, z1 - z0)
                q = [rail.P(i, y0, z0), rail.P(i + 1, y2, z2), rail.P(i + 1, y3, z3), rail.P(i, y1, z1)]
                oy, oz = (z1 - z0) * orient, -(y1 - y0) * orient
                o = Vector((rail.nrm[i][0] * oy, rail.nrm[i][1] * oy, oz))
                ua, ub = rail.u[i], rail.u[i + 1]
                self.face(q, key, [(ua, v), (ub, v), (ub, v + dv), (ua, v + dv)], o, smooth)
                v += dv
            prev = cur

    def ribbon(self, a, b, w, side, key):
        """Flat card from a to b, w wide along `side` (far LOD of a cable)."""
        a, b = Vector(a), Vector(b)
        s = Vector(side).normalized() * (w / 2)
        L = (b - a).length
        n = (b - a).cross(s)
        self.face([a - s, a + s, b + s, b - s], key, [(0, 0), (w, 0), (w, L), (0, L)], n)

    def finish(self, name, mats):
        """mats: key -> material. UVs are divided by each material's tile (v up = up the
        Pigment sheet image, so decal text on the sheets reads upright)."""
        me = bpy.data.meshes.get(name)
        if me is not None:
            bpy.data.meshes.remove(me)
        me = bpy.data.meshes.new(name)
        tiles = [tile_of(k) for k in self.keys]
        used = sorted({f.material_index for f in self.bm.faces})
        remap = {m: i for i, m in enumerate(used)}
        for f in self.bm.faces:
            tu, tv = tiles[f.material_index]
            for lp in f.loops:
                u, v = lp[self.uv].uv
                lp[self.uv].uv = (u / tu, v / tv)
            f.material_index = remap[f.material_index]
        self.bm.to_mesh(me)
        self.bm.free()
        for m in used:                   # only the materials in use (one glb primitive each)
            me.materials.append(mats[self.keys[m]])
        me.update()
        return me


def _orient(prof):
    """+1 when the (y, z) polygon runs counter-clockwise: its outward normal of a segment
    (dy, dz) is then (dz, -dy)."""
    a = 0.0
    for (y0, z0), (y1, z1) in zip(prof, list(prof[1:]) + [prof[0]]):
        a += y0 * z1 - y1 * z0
    return 1.0 if a > 0 else -1.0


class Rail:
    """Stations along a road path between s0 and s1 (step metres). P(i, y, z): the point y to the
    left of the centreline and z above the path level (road surface = path + 0.2)."""

    def __init__(self, path, s0, s1, step=2.0, s=None):
        if s is None:
            n = max(2, int(math.ceil((s1 - s0) / step)) + 1)
            s = np.linspace(s0, s1, n)
        self.s = np.asarray(s, dtype=float)
        self.n = len(self.s)
        pos, t = path.at_many(self.s)
        self.pos = pos
        self.tan = t
        self.nrm = np.stack([-t[:, 1], t[:, 0]], 1)
        self.u = (self.s - self.s[0]).tolist()

    def P(self, i, y, z):
        p, n = self.pos[i], self.nrm[i]
        return Vector((p[0] + n[0] * y, p[1] + n[1] * y, p[2] + z))

    def frame(self, i):
        t = Vector((self.tan[i][0], self.tan[i][1], 0.0))
        n = Vector((self.nrm[i][0], self.nrm[i][1], 0.0))
        return Vector(self.pos[i]), t, n


def station_of(path, xy, s_hint=None, window=80.0):
    """Arc length of the path point nearest to xy (searching near s_hint when given)."""
    if s_hint is None:
        ss = np.linspace(0, path.length, max(2, int(path.length / 1.0) + 1))
    else:
        ss = np.linspace(max(0, s_hint - window), min(path.length, s_hint + window), 321)
    pos, _ = path.at_many(ss)
    d = np.hypot(pos[:, 0] - xy[0], pos[:, 1] - xy[1])
    k = int(np.argmin(d))
    return float(ss[k]), float(d[k])


def frame_at(path, s):
    p, t = path.at(s)
    t3 = Vector((t.x, t.y, 0.0))
    return Vector(p), t3, Vector((-t.y, t.x, 0.0))


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a))) if b != a else float(x >= a)
    return t * t * (3 - 2 * t)


def superellipse(cx, cy, z, ax, ay, X, Y, n=4.0, seg=16):
    """Ring of a rounded rectangle (superellipse exponent n) of half sizes ax (along X), ay
    (along Y) at height z: brutalist columns."""
    pts = []
    for k in range(seg):
        a = 2 * math.pi * (k + 0.5) / seg
        c, s = math.cos(a), math.sin(a)
        x = ax * math.copysign(abs(c) ** (2 / n), c)
        y = ay * math.copysign(abs(s) ** (2 / n), s)
        pts.append(Vector((cx, cy, z)) + X * x + Y * y)
    return pts


def chamfer_rect(c, X, Y, ax, ay, ch):
    """Octagonal ring: a rectangle of half sizes ax, ay with chamfered corners."""
    ch = min(ch, ax * 0.45, ay * 0.45)
    loc = [(ax, -ay + ch), (ax, ay - ch), (ax - ch, ay), (-ax + ch, ay), (-ax, ay - ch), (-ax, -ay + ch), (-ax + ch, -ay), (ax - ch, -ay)]
    return [Vector(c) + X * x + Y * y for x, y in loc]


# ---------------------------------------------------------------- materials
def _nodes(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m, nt, bsdf


def _img(nt, path, color):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(path, check_existing=True)
    if not color:
        n.image.colorspace_settings.name = "Non-Color"
    return n


def pigment_material(root, key):
    name, tile, col, rough, metal = SHEETS[key]
    mname = "Bridge_" + key
    if bpy.data.materials.get(mname):
        return bpy.data.materials[mname]
    m, nt, bsdf = _nodes(mname)
    folder = os.path.join(root, "scenes", "town", "textures", name)
    bc = os.path.join(folder, f"{name}_BaseColor.png")
    if os.path.isfile(bc):
        c = _img(nt, bc, True)
        nt.links.new(c.outputs["Color"], bsdf.inputs["Base Color"])
        for ch, sock in (("Roughness", "Roughness"), ("Metallic", "Metallic")):
            p = os.path.join(folder, f"{name}_{ch}.png")
            if os.path.isfile(p):
                nt.links.new(_img(nt, p, False).outputs["Color"], bsdf.inputs[sock])
        p = os.path.join(folder, f"{name}_Normal_OpenGL.png")
        if os.path.isfile(p):
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = 1.0
            nt.links.new(_img(nt, p, False).outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        m["pigment_folder"] = folder
        m["pigment_name"] = name
    else:
        bsdf.inputs["Base Color"].default_value = (*col, 1)
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
    return m


def flat_material(key):
    col, rough, metal = FLAT[key]
    mname = "Bridge_" + key
    if bpy.data.materials.get(mname):
        return bpy.data.materials[mname]
    m, nt, bsdf = _nodes(mname)
    bsdf.inputs["Base Color"].default_value = (*col, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return m


def emit_material(key):
    col, strength = EMIT[key]
    mname = "Bridge_" + key
    if bpy.data.materials.get(mname):
        return bpy.data.materials[mname]
    m, nt, bsdf = _nodes(mname)
    bsdf.inputs["Base Color"].default_value = (*col, 1)
    bsdf.inputs["Emission Color"].default_value = (*col, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    bsdf.inputs["Roughness"].default_value = 0.3
    return m


def wash_images(root):
    """Uplight wash card images (written by tools/world/bridge_textures.py make_decals: a soft cone
    of light, full at the bottom edge, colour baked in for Godot's image material)."""
    return {k: os.path.join(root, "assets", "decals", "bridges", f"{k}.png") for k in WASH}


def wash_material(root, key, strength=1.6):
    mname = "Bridge_" + key
    if bpy.data.materials.get(mname):
        return bpy.data.materials[mname]
    p = wash_images(root)[key]
    m, nt, bsdf = _nodes(mname)
    t = _img(nt, p, True)
    nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(t.outputs["Color"], bsdf.inputs["Emission Color"])
    nt.links.new(t.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Emission Strength"].default_value = strength
    bsdf.inputs["Roughness"].default_value = 1.0
    try:
        m.surface_render_method = "BLENDED"
    except (AttributeError, TypeError):
        pass
    return m


def sign_material(root, name, path=None, emission=0.0):
    mname = "Bridge_" + name
    if bpy.data.materials.get(mname):
        return bpy.data.materials[mname]
    p = path or os.path.join(root, "assets", "decals", "bridges", f"{name}.png")
    m, nt, bsdf = _nodes(mname)
    if os.path.isfile(p):
        t = _img(nt, p, True)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        if emission > 0:
            nt.links.new(t.outputs["Color"], bsdf.inputs["Emission Color"])
            nt.links.new(t.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Emission Strength"].default_value = emission
    bsdf.inputs["Roughness"].default_value = 0.5
    return m


def materials(root, red_light=None):
    M = {k: pigment_material(root, k) for k in SHEETS}
    M.update({k: flat_material(k) for k in FLAT})
    M.update({k: emit_material(k) for k in EMIT})
    if red_light is not None:
        M["red_light"] = red_light
    M.update({k: wash_material(root, k) for k in WASH})
    for s in ("sign_works", "sign_no_access", "sign_clearance", "sign_bridge_id"):
        M[s] = sign_material(root, s)
    M["logo"] = sign_material(root, "logo", os.path.join(root, "assets", "decals", "logo_hoshikawa_dynamics.png"), emission=1.5)
    return M


def put(coll, name, data, built=None, kind="bridges"):
    o = bpy.data.objects.new(name, data)
    coll.objects.link(o)
    if built is not None:
        built.setdefault(kind, []).append(o)
    return o
