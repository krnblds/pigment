"""Lay out a dense hillside cyberpunk town (East-Asian hill city) in Blender.

Needs the town kit imported into the "TownKit" collection as KIT_<asset>
objects with their Pigment materials (tools/town_layout_driver.py does that
headlessly; see tools/blender_pigment.py).

Road network
    A graph of junctions (X, T and Y) joined by winding 3D roads.  Every
    junction is generated procedurally from its arm angles: filleted curbs,
    continuous corner sidewalks and arm mouths with the road cross-section
    (asphalt, gutter, curb, walk edge, paving out to 7 m).  Runs between
    junctions are spline meshes swept along the path (tools/town_roads.py):
    asphalt has world-space planar UVs on runs and junctions alike, so they
    join without a seam; sidewalks and curbs use an along-path coordinate
    scaled to whole 2 m tiles between junction mouths, so slabs and curb
    joints line up at every join.  One shared material each for asphalt,
    paving, trim (curbs / gutters) and concrete, all seamless Pigment tiles
    from scenes/town/textures/roads/ (python tools/road_textures.py --run),
    with world-space macro variation and puddles.  Markings, zebra
    crossings, cracks, patches, oil, manholes and drains are decal quads from
    a Pigment atlas.  Junctions are flat; road grades ease in and out of them.

Terrain
    Smooth, flat terraces at sidewalk level beside every road (the "lots"),
    rolling ground further out.  Where two levels meet the ground steps and a
    retaining wall is built along the step (marching squares on the level
    field, bisected to the exact step line).  Terrain under asphalt is cut away
    and terrain under sidewalks sits just below them (ray cast against the road
    meshes), so it never pokes through and never floats.

Hillside detail
    Stairs climb along retaining walls, railings run along wall tops, alleys
    open between buildings, power lines sag between poles and story posters,
    graffiti and Meridian billboards are pasted on the (Blender-side) walls.

Buildings
    Front rows face the street; back rows fill the hillside.  Every building
    sits at the highest ground under its footprint on a concrete footing that
    reaches below the lowest ground.  Texture variants exported by Pigment to
    scenes/town/textures/<asset>__<variant>/ are picked at random per instance
    (object-level material slot); else the kit material is used.

    exec(open("tools/blender_town.py").read())          # inside Blender
    # or, with TOWN_NO_AUTOBUILD = True in the namespace: build(root=..., ...)
"""
import glob
import json
import math
import os
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector, kdtree
from mathutils.bvhtree import BVHTree

SEED = 11
COLL = "CyberpunkTown"
TILE = 20.0                # street piece length
ROAD_HALF = 4.0            # asphalt half width (curb face)
CURB_W = 0.25
WALK_W = 3.0               # curb face -> sidewalk outer edge
ROAD_Z, WALK_Z, CURB_Z = 0.2, 0.35, 0.355
LOT_DZ = WALK_Z - 0.01     # lots sit 1 cm under the sidewalk top
CORE = 8.4                 # inside this distance the road owns the ground level
BAND = 25.0                # building lots beside a road
GRID = 0.6                 # terrain resolution
HALF = 150.0               # terrain half extent
JUMP = 0.35                # level steps above this get a retaining wall
WALL_HALF = 0.95           # covers the steep grid triangles of a step
STEP = 0.5                 # path sample spacing

# ---------------------------------------------------------------- network
# name: ((x, y), z, [arm angles in degrees, outward])
NODES = {
    "J1": ((-20.0, -5.0), 0.0, [195, 15, 105, 285]),   # crossroads
    "J2": ((68.0, 12.0), 4.0, [200, 72, 350]),         # Y fork
    "J3": ((-50.0, 82.0), 4.5, [282, 102, 12]),        # T
    "J4": ((72.0, 108.0), 9.0, [266, 86, 176]),        # T
    "J5": ((-12.0, -92.0), -3.5, [100, 228, 312]),     # Y fork
}
# (from (node, arm), to (node, arm) | ((x, y), z) free end, waypoints)
EDGES = [
    (("J1", 0), ((-170.0, -38.0), -3.0), [(-72, -24), (-118, -22)]),
    (("J1", 1), ("J2", 0), [(27, 1)]),
    (("J2", 1), ("J4", 0), []),
    (("J4", 1), ((95.0, 170.0), 13.0), []),
    (("J1", 2), ("J3", 0), []),
    (("J3", 1), ((-85.0, 170.0), 11.0), []),
    (("J3", 2), ("J4", 2), [(5, 93), (30, 106)]),
    (("J2", 2), ((170.0, -14.0), 2.0), [(125, 2)]),
    (("J1", 3), ("J5", 0), []),
    (("J5", 1), ((-62.0, -170.0), -8.0), [(-40, -130)]),
    (("J5", 2), ((72.0, -170.0), -7.0), []),
]


def wild(x, y):
    return 3.2 * math.sin(x / 23 + 1.3) * math.sin(y / 19 + 0.2) + 2.2 * math.cos(x / 41 - y / 37) + 0.03 * y


def smooth01(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)

# ---------------------------------------------------------------- helpers


def v2(a):
    return Vector((a[0], a[1]))


def rot90(v):
    return Vector((-v.y, v.x))


def ang_vec(deg):
    a = math.radians(deg)
    return Vector((math.cos(a), math.sin(a)))


def catmull(points, step=STEP):
    pts = [v2(p) for p in points]
    # Hermite spline whose tangents are scaled to each segment's length: no
    # overshoot or cusps when control points are unevenly spaced.
    dirs = []
    for i in range(len(pts)):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        dirs.append((b - a).normalized())
    out = []
    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]
        seg = (p2 - p1).length
        m1, m2 = dirs[i] * seg, dirs[i + 1] * seg
        n = max(4, int(seg / (step * 0.25)))
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append(p1 * (2 * t3 - 3 * t2 + 1) + m1 * (t3 - 2 * t2 + t) + p2 * (-2 * t3 + 3 * t2) + m2 * (t3 - t2))
    out.append(pts[-1])
    even, acc = [out[0]], 0.0
    for a, b in zip(out, out[1:]):
        seg = (b - a).length
        while seg > 1e-9 and acc + seg >= step:
            r = (step - acc) / seg
            a = a + (b - a) * r
            seg = (b - a).length
            even.append(a)
            acc = 0.0
        acc += seg
    if (even[-1] - out[-1]).length > 1e-4:
        if (even[-1] - out[-1]).length < step * 0.5:
            even[-1] = out[-1]
        else:
            even.append(out[-1])
    return even


class Path:
    """Polyline sampled every STEP metres with heights."""

    def __init__(self, pts2d, z):
        self.p = [Vector((v.x, v.y, h)) for v, h in zip(pts2d, z)]
        seg = [0.0] + [(b - a).to_2d().length for a, b in zip(self.p, self.p[1:])]
        self.cum = np.cumsum(seg)
        self.length = float(self.cum[-1])
        xy = np.array([(v.x, v.y) for v in self.p])
        tan = np.zeros_like(xy)
        k = 3
        for i in range(len(xy)):
            a, b = xy[max(0, i - k)], xy[min(len(xy) - 1, i + k)]
            d = b - a
            tan[i] = d / max(1e-9, np.hypot(*d))
        self.tan = tan
        self.xyz = np.array([(v.x, v.y, v.z) for v in self.p])

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        i = int(np.searchsorted(self.cum, s, side="right") - 1)
        i = max(0, min(len(self.p) - 2, i))
        f = (s - self.cum[i]) / max(1e-9, self.cum[i + 1] - self.cum[i])
        pos = self.p[i].lerp(self.p[i + 1], f)
        t = Vector(self.tan[i] * (1 - f) + self.tan[i + 1] * f).normalized()
        return pos, t

    def at_many(self, s):
        s = np.clip(s, 0.0, self.length)
        i = np.clip(np.searchsorted(self.cum, s, side="right") - 1, 0, len(self.p) - 2)
        f = ((s - self.cum[i]) / np.maximum(1e-9, self.cum[i + 1] - self.cum[i]))[:, None]
        pos = self.xyz[i] * (1 - f) + self.xyz[i + 1] * f
        t = self.tan[i] * (1 - f) + self.tan[i + 1] * f
        t /= np.linalg.norm(t, axis=1)[:, None]
        return pos, t

    def min_radius(self):
        r = 1e9
        for i in range(4, len(self.p) - 4, 2):
            a, b = Vector(self.tan[i - 4]), Vector(self.tan[i + 4])
            ang = math.acos(max(-1.0, min(1.0, a.dot(b))))
            if ang > 1e-6:
                r = min(r, (self.cum[i + 4] - self.cum[i - 4]) / ang)
        return r


def ease_profile(L, za, zb, ease_a=True, ease_b=True, e=14.0):
    """Heights along s: flat where a junction is, constant grade in between."""
    n = max(2, int(round(L / STEP)) + 1)
    s = np.linspace(0, L, n)
    e = min(e, L / 3)
    slope = np.ones(n)
    if ease_a:
        slope = np.minimum(slope, np.clip(s / e, 0, 1))
    if ease_b:
        slope = np.minimum(slope, np.clip((L - s) / e, 0, 1))
    acc = np.concatenate([[0.0], np.cumsum((slope[1:] + slope[:-1]) * 0.5 * np.diff(s))])
    acc /= max(acc[-1], 1e-9)
    return s, za + (zb - za) * acc


def clear(coll):
    for o in list(coll.objects):
        data = o.data
        bpy.data.objects.remove(o)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
            elif isinstance(data, bpy.types.Mesh) and not data.name.startswith("KIT"):
                bpy.data.meshes.remove(data)


def material(name, build):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    build(nt)
    return m

# ---------------------------------------------------------------- materials


def paving_nodes(nt):
    """Dark stone paving on lots, rough gravel and moss further out (vertex colour 'zone')."""
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Mortar Size"].default_value = 0.012
    brick.inputs["Brick Width"].default_value = 0.6
    brick.inputs["Row Height"].default_value = 0.3
    brick.inputs["Color1"].default_value = (0.085, 0.085, 0.09, 1)
    brick.inputs["Color2"].default_value = (0.05, 0.05, 0.055, 1)
    brick.inputs["Mortar"].default_value = (0.02, 0.02, 0.02, 1)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.08
    noise.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.48
    ramp.color_ramp.elements[0].color = (0.06, 0.06, 0.06, 1)
    ramp.color_ramp.elements[1].position = 0.56
    ramp.color_ramp.elements[1].color = (0.7, 0.7, 0.7, 1)
    rough = nt.nodes.new("ShaderNodeTexNoise")
    rough.inputs["Scale"].default_value = 0.6
    rough.inputs["Detail"].default_value = 10
    gramp = nt.nodes.new("ShaderNodeValToRGB")
    gramp.color_ramp.elements[0].color = (0.02, 0.025, 0.018, 1)
    gramp.color_ramp.elements[1].color = (0.075, 0.07, 0.06, 1)
    zone = nt.nodes.new("ShaderNodeVertexColor")
    zone.layer_name = "zone"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    rmix = nt.nodes.new("ShaderNodeMix")
    rmix.data_type = "FLOAT"
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    hmix = nt.nodes.new("ShaderNodeMix")
    hmix.data_type = "FLOAT"
    L = nt.links.new
    L(tc.outputs["Object"], brick.inputs["Vector"])
    L(tc.outputs["Object"], noise.inputs["Vector"])
    L(tc.outputs["Object"], rough.inputs["Vector"])
    L(noise.outputs["Fac"], ramp.inputs["Fac"])
    L(rough.outputs["Fac"], gramp.inputs["Fac"])
    L(zone.outputs["Color"], mix.inputs["Factor"])
    L(brick.outputs["Color"], mix.inputs["A"])
    L(gramp.outputs["Color"], mix.inputs["B"])
    L(mix.outputs["Result"], bsdf.inputs["Base Color"])
    L(zone.outputs["Color"], rmix.inputs["Factor"])
    L(ramp.outputs["Color"], rmix.inputs["A"])
    rmix.inputs["B"].default_value = 0.9
    L(rmix.outputs["Result"], bsdf.inputs["Roughness"])
    L(zone.outputs["Color"], hmix.inputs["Factor"])
    L(brick.outputs["Fac"], hmix.inputs["A"])
    L(rough.outputs["Fac"], hmix.inputs["B"])
    L(hmix.outputs["Result"], bump.inputs["Height"])
    L(bump.outputs["Normal"], bsdf.inputs["Normal"])
    L(bsdf.outputs[0], out.inputs[0])


def concrete_nodes(nt, tint=(0.16, 0.155, 0.15), streaks=True):
    """Weathered concrete: formwork panel joints, rain streaks, darker damp foot."""
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 8
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.045, 0.045, 0.045, 1)
    ramp.color_ramp.elements[1].color = (*tint, 1)
    L = nt.links.new
    L(tc.outputs["Object"], noise.inputs["Vector"])
    L(noise.outputs["Fac"], ramp.inputs["Fac"])
    col = ramp.outputs["Color"]
    height = noise.outputs["Fac"]
    if streaks:
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (1.0, 1.0, 0.08)
        L(tc.outputs["Object"], mapping.inputs["Vector"])
        st = nt.nodes.new("ShaderNodeTexNoise")
        st.inputs["Scale"].default_value = 4.0
        st.inputs["Detail"].default_value = 4
        L(mapping.outputs["Vector"], st.inputs["Vector"])
        sr = nt.nodes.new("ShaderNodeValToRGB")
        sr.color_ramp.elements[0].position = 0.45
        sr.color_ramp.elements[0].color = (1, 1, 1, 1)
        sr.color_ramp.elements[1].position = 0.7
        sr.color_ramp.elements[1].color = (0.35, 0.33, 0.3, 1)
        L(st.outputs["Fac"], sr.inputs["Fac"])
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        L(col, mul.inputs["A"])
        L(sr.outputs["Color"], mul.inputs["B"])
        col = mul.outputs["Result"]
        brick = nt.nodes.new("ShaderNodeTexBrick")
        brick.inputs["Scale"].default_value = 1.0
        brick.inputs["Mortar Size"].default_value = 0.01
        brick.inputs["Brick Width"].default_value = 1.8
        brick.inputs["Row Height"].default_value = 0.9
        brick.offset = 0.0
        brick.inputs["Color1"].default_value = (1, 1, 1, 1)
        brick.inputs["Color2"].default_value = (0.92, 0.92, 0.92, 1)
        brick.inputs["Mortar"].default_value = (0.4, 0.4, 0.4, 1)
        bm = nt.nodes.new("ShaderNodeMapping")
        bm.inputs["Rotation"].default_value = (math.pi / 2, 0, 0)
        L(tc.outputs["Object"], bm.inputs["Vector"])
        L(bm.outputs["Vector"], brick.inputs["Vector"])
        mul2 = nt.nodes.new("ShaderNodeMix")
        mul2.data_type = "RGBA"
        mul2.blend_type = "MULTIPLY"
        mul2.inputs["Factor"].default_value = 1.0
        L(col, mul2.inputs["A"])
        L(brick.outputs["Color"], mul2.inputs["B"])
        col = mul2.outputs["Result"]
        hadd = nt.nodes.new("ShaderNodeMath")
        hadd.operation = "ADD"
        L(noise.outputs["Fac"], hadd.inputs[0])
        L(brick.outputs["Fac"], hadd.inputs[1])
        height = hadd.outputs[0]
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.2
    bsdf.inputs["Roughness"].default_value = 0.85
    L(col, bsdf.inputs["Base Color"])
    L(height, bump.inputs["Height"])
    L(bump.outputs["Normal"], bsdf.inputs["Normal"])
    L(bsdf.outputs[0], out.inputs[0])


def metal_nodes(nt):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.055, 0.06, 1)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.45
    nt.links.new(bsdf.outputs[0], out.inputs[0])


def flat_nodes(col, rough=0.8, metal=0.0):
    def f(nt):
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = (*col, 1)
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    return f


def decal_material(path, emission=0.0):
    name = "Decal_" + os.path.splitext(os.path.basename(path))[0] + ("_lit" if emission else "")
    m = bpy.data.materials.get(name)
    if m is not None:
        return m

    def f(nt):
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(path, check_existing=True)
        tex.extension = "CLIP"
        bsdf.inputs["Roughness"].default_value = 0.6
        L = nt.links.new
        L(tex.outputs["Color"], bsdf.inputs["Base Color"])
        L(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        if emission:
            L(tex.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = emission
        L(bsdf.outputs[0], out.inputs[0])
    m = material(name, f)
    try:
        m.blend_method = "HASHED"
    except Exception:
        pass
    return m

# ---------------------------------------------------------------- junction mesh


class Junction:
    """Procedural junction: n arms at arbitrary angles, filleted curbs,
    continuous corner sidewalks, zebra crossings.  Local frame: centre at the
    origin, z = path level (road top at ROAD_Z), same profile as the street kit."""

    def __init__(self, name, pos, z, arms, r_concave=6.0, r_convex=3.0, arc_n=14):
        self.name, self.pos, self.z = name, v2(pos), z
        self.arms = arms
        self.dirs = [ang_vec(a) for a in arms]
        self.arc_n = arc_n
        n = len(arms)
        order = sorted(range(n), key=lambda i: arms[i] % 360)
        self.corners = []
        need = [0.0] * n
        for k in range(n):
            ia, ib = order[k], order[(k + 1) % n]
            a, b = self.dirs[ia], self.dirs[ib]
            theta = (arms[ib] - arms[ia]) % 360
            c = {"ia": ia, "ib": ib, "theta": theta}
            if abs(theta - 180) >= 4:
                concave = theta < 180
                r = r_concave if concave else r_convex
                na, nb = rot90(a), -rot90(b)
                X = self._intersect(na * ROAD_HALF, a, nb * ROAD_HALF, b)
                phi = math.radians(theta if concave else 360 - theta)
                C = X + (a + b).normalized() * (r / math.sin(phi / 2))
                c.update(C=C, r=r, concave=concave)
                need[ia] = max(need[ia], C.dot(a))
                need[ib] = max(need[ib], C.dot(b))
            self.corners.append(c)
        self.L = [max(10.0, t + 5.5) for t in need]

    @staticmethod
    def _intersect(p, d, q, e):
        den = d.x * e.y - d.y * e.x
        t = ((q.x - p.x) * e.y - (q.y - p.y) * e.x) / den
        return p + d * t

    def arm_end(self, i):
        return self.pos + self.dirs[i] * self.L[i]

    def corner_line(self, c, d):
        a, b = self.dirs[c["ia"]], self.dirs[c["ib"]]
        na, nb = rot90(a), -rot90(b)
        A = a * self.L[c["ia"]] + na * (ROAD_HALF + d)
        B = b * self.L[c["ib"]] + nb * (ROAD_HALF + d)
        m = self.arc_n
        if "C" not in c:
            return [A.lerp(B, i / (m + 2)) for i in range(m + 3)]
        C = c["C"]
        rd = c["r"] - d if c["concave"] else c["r"] + d
        Ta = a * C.dot(a) + na * (ROAD_HALF + d)
        Tb = b * C.dot(b) + nb * (ROAD_HALF + d)
        a0 = math.atan2(Ta.y - C.y, Ta.x - C.x)
        a1 = math.atan2(Tb.y - C.y, Tb.x - C.x)
        sw = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        arc = [C + Vector((math.cos(a0 + sw * i / m), math.sin(a0 + sw * i / m))) * rd for i in range(m + 1)]
        return [A] + arc + [B]

# ---------------------------------------------------------------- roads


def _roads_api(root):
    """tools/town_roads.py: spline road meshes, shared materials, decals."""
    src = os.path.join(root, "tools", "town_roads.py")
    ns = {"__name__": "town_roads", "__file__": src}
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns

# ---------------------------------------------------------------- variants


def _pigment_api(root):
    src = os.path.join(root, "tools", "blender_pigment.py")
    # __file__ lets the wrapper find the Pigment Bridge core in tools/blender_addon
    ns = {"__name__": "blender_pigment", "__file__": src}
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns["apply_pigment_material"]


def variant_materials(root, asset, kit_obj):
    """Materials for scenes/town/textures/<asset>__<variant>/<asset>_*.png."""
    tex = os.path.join(root, "scenes", "town", "textures")
    folders = sorted(glob.glob(os.path.join(tex, asset + "__*")))
    folders = [f for f in folders if os.path.isfile(os.path.join(f, asset + "_BaseColor.png"))]
    if not folders:
        return []
    apply = _pigment_api(root)
    mats = []
    tmp_me = kit_obj.data.copy()
    tmp = bpy.data.objects.new("_variant_tmp", tmp_me)
    try:
        for f in folders:
            var = os.path.basename(f).split("__", 1)[1]
            want = f"Pigment_{asset}__{var}"
            base = bpy.data.materials.get(f"Pigment_{asset}")
            if base is not None:
                base.name = "_hold_" + asset           # keep the kit material
            m = apply(tmp, f, asset)
            old = bpy.data.materials.get(want)
            if old is not None and old != m:
                bpy.data.materials.remove(old)
            m.name = want
            if base is not None:
                base.name = f"Pigment_{asset}"
            mats.append(m)
    finally:
        bpy.data.objects.remove(tmp)
        bpy.data.meshes.remove(tmp_me)
    return mats


# ---------------------------------------------------------------- build


def build(root=None, export_junctions=False, quick=False):
    """Build the town into collection COLL.  Returns a dict of layout facts
    (junctions, paths, walls, stairs) for cameras and checks."""
    if root is None:
        root = globals().get("TOWN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(bpy.data.filepath or __file__)))
    rng = random.Random(SEED)
    sc = bpy.context.scene
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
        sc.collection.children.link(coll)
    clear(coll)
    K = {n: bpy.data.objects["KIT_" + n] for n in
         ["building_a", "building_b", "building_c", "street_lamp", "power_pole", "overhead_sign"]}

    def put(data, loc, rz=0.0, name="obj", parent=None):
        o = bpy.data.objects.new(name, data)
        o.location = loc
        o.rotation_euler = (0, 0, rz)
        coll.objects.link(o)
        if parent is not None:
            o.parent = parent
        return o

    M = {
        "concrete": material("TownConcrete", concrete_nodes),
        "wall": material("TownRetainingWall", lambda nt: concrete_nodes(nt, (0.2, 0.19, 0.175))),
        "metal": material("TownRailMetal", metal_nodes),
        "asphalt": material("TownAsphaltFallback", flat_nodes((0.03, 0.03, 0.032), 0.6)),
        "curb": material("TownCurbFallback", flat_nodes((0.2, 0.2, 0.19), 0.85)),
        "walk": material("TownWalkFallback", flat_nodes((0.11, 0.11, 0.11), 0.8)),
        "paint": material("TownPaintFallback", flat_nodes((0.6, 0.6, 0.58), 0.7)),
        "wire": material("TownWire", flat_nodes((0.01, 0.01, 0.01), 0.5)),
    }

    # ---- roads: shared tileable Pigment materials (scenes/town/textures/roads/)
    R = _roads_api(root)
    RT = R["RoadTextures"](root)
    M["concrete_fallback"] = M["concrete"]
    road_mats = R["road_materials"](RT, {"asphalt": M["asphalt"], "curb": M["curb"], "walk": M["walk"], "concrete": M["concrete"]})
    if RT.ok:
        M["wall"] = road_mats[3]         # Pigment concrete tile, world box mapped
    else:
        print("no road textures in scenes/town/textures/roads/ (python tools/road_textures.py --run): flat fallback materials")
    if export_junctions:
        print("--export-junctions is gone: junctions use the shared road materials now (no per-junction bake)")

    # ---- junctions
    J = {name: Junction(name, pos, z, arms) for name, (pos, z, arms) in NODES.items()}
    jinfo = {}
    road_meshes = []
    for name, j in J.items():
        me = R["build_junction"](j, "junction_" + name.lower(), RT, road_mats, j.corner_line)
        o = put(me, (j.pos.x, j.pos.y, j.z), name="Junction_" + name)
        road_meshes.append(o)
        jinfo[name] = {"pos": (j.pos.x, j.pos.y, j.z), "arms": j.arms, "L": j.L,
                       "kind": {4: "X", 3: ("T" if any(abs(c["theta"] - 180) < 4 for c in j.corners) else "Y")}.get(len(j.arms), "?")}

    # ---- edges
    runs = []
    run_ends = []
    for (na, ia), b, wps in EDGES:
        ja = J[na]
        A, da = ja.arm_end(ia), ja.dirs[ia]
        ctrl = [A, A + da * 10.0] + [v2(w) for w in wps]
        if isinstance(b[0], str):
            jb = J[b[0]]
            B, db = jb.arm_end(b[1]), jb.dirs[b[1]]
            ctrl += [B + db * 10.0, B]
            zb, ease_b = jb.z, True
        else:
            ctrl += [v2(b[0])]
            zb, ease_b = b[1], False
        pts = catmull(ctrl)
        seg = [0.0] + [(q - p).length for p, q in zip(pts, pts[1:])]
        L = float(np.sum(seg))
        s, z = ease_profile(L, ja.z, zb, True, ease_b)
        zz = np.interp(np.cumsum(seg), s, z)
        path = Path(pts, zz)
        runs.append(path)
        run_ends.append((True, isinstance(b[0], str)))
        grade = float(np.max(np.abs(np.diff(zz)) / np.maximum(1e-6, np.diff(np.cumsum(seg)))))
        print(f"junction arms {na}: {[round(x, 1) for x in ja.L]}") if False else None
        print(f"edge {na}.{ia} -> {b[0] if isinstance(b[0], str) else 'free'}: {L:.0f} m  grade {grade * 100:.1f}%  min radius {path.min_radius():.1f} m")

    for i, path in enumerate(runs):
        me = R["build_run"](path, f"RoadRun{i}", RT, road_mats)
        o = put(me, (0, 0, 0), name=f"RoadRun{i}")
        road_meshes.append(o)

    # ---- road decals from the Pigment atlas: markings, cracks, patches, oil, covers
    if RT.ok and RT.atlas_ok:
        drng = random.Random(R["SEED"])
        db = R["DecalBuilder"](RT)
        for i, path in enumerate(runs):
            R["scatter_run_decals"](db, path, i, drng, run_ends[i])
        for name, j in J.items():
            R["junction_decals"](db, j, drng)
        print("road decals", dict(sorted(db.count.items())))
        put(db.finish("RoadDecals", R["decal_atlas_material"](RT)), (0, 0, 0), name="RoadDecals")

    # ---- road samples for the level field
    class Road:
        pass
    roads = []
    for i, path in enumerate(runs):
        r = Road()
        r.id, r.pts = f"run{i}", path.xyz
        roads.append(r)
    for name, j in J.items():
        pts = []
        for i, d in enumerate(j.dirs):
            for t in np.arange(0, j.L[i] + 1e-6, STEP):
                p = j.pos + d * t
                pts.append((p.x, p.y, j.z))
        r = Road()
        r.id, r.pts = name, np.array(pts)
        roads.append(r)
    for r in roads:
        r.kd = kdtree.KDTree(len(r.pts))
        for k, p in enumerate(r.pts):
            r.kd.insert((p[0], p[1], 0.0), k)
        r.kd.balance()
    allpts = np.concatenate([r.pts for r in roads])
    akd = kdtree.KDTree(len(allpts))
    for k, p in enumerate(allpts):
        akd.insert((p[0], p[1], 0.0), k)
    akd.balance()

    # natural ground: blend of road levels plus rolling hills, on a coarse grid
    CG = 4.0
    cn = int(2 * HALF / CG) + 3
    cx0 = -HALF - CG
    nat = np.zeros((cn, cn))
    cand = [[None] * cn for _ in range(cn)]
    for iy in range(cn):
        for ix in range(cn):
            x, y = cx0 + ix * CG, cx0 + iy * CG
            num = den = 0.0
            dmin = 1e9
            cl = []
            for r in roads:
                _, k, d = r.kd.find((x, y, 0))
                dmin = min(dmin, d)
                w = 1.0 / (max(d - BAND, 0.0) + 8.0) ** 3
                num += (r.pts[k][2] + LOT_DZ) * w
                den += w
                if d < BAND + CG * 0.75 + 0.5:
                    cl.append(r)
            t = smooth01((dmin - BAND) / 45.0)
            nat[iy, ix] = num / den + (0.35 + 0.65 * t) * wild(x, y) * 1.3 + 4.0 * t * smooth01((y + 40) / 160)
            cand[iy][ix] = cl

    def nat_at(x, y):
        fx, fy = (x - cx0) / CG, (y - cx0) / CG
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        ix, iy = max(0, min(cn - 2, ix)), max(0, min(cn - 2, iy))
        tx, ty = fx - ix, fy - iy
        return (nat[iy, ix] * (1 - tx) * (1 - ty) + nat[iy, ix + 1] * tx * (1 - ty) +
                nat[iy + 1, ix] * (1 - tx) * ty + nat[iy + 1, ix + 1] * tx * ty)

    def cands_at(x, y):
        ix = int(round((x - cx0) / CG))
        iy = int(round((y - cx0) / CG))
        if 0 <= ix < cn and 0 <= iy < cn:
            return cand[iy][ix]
        return []

    def level(x, y, with_owner=False):
        """Ground level: the nearest road's lot level within BAND, else natural ground."""
        core = band = None
        for r in cands_at(x, y):
            _, k, d = r.kd.find((x, y, 0))
            z = r.pts[k][2] + LOT_DZ
            if d < CORE and (core is None or d < core[2]):
                core = (z, r.id, d)
            if d < BAND and (band is None or d < band[2]):
                band = (z, r.id, d)
        res = core or band
        if res is None:
            res = (nat_at(x, y), None, 1e9)
        return res if with_owner else res[0]

    def road_dist(x, y):
        return akd.find((x, y, 0))[2]

    # ---- terrain grid
    n = int(2 * HALF / GRID) + 1
    xs = -HALF + np.arange(n) * GRID
    Z = np.empty((n, n))
    for iy in range(n):
        y = xs[iy]
        for ix in range(n):
            Z[iy, ix] = level(xs[ix], y)
    Zlevel = Z.copy()

    # conform to the road meshes
    bpy.context.view_layer.update()
    bv, bp = [], []
    for o in road_meshes:
        mw = o.matrix_world
        base = len(bv)
        bv += [mw @ v.co for v in o.data.vertices]
        bp += [tuple(i + base for i in p.vertices) for p in o.data.polygons]
    bvh = BVHTree.FromPolygons(bv, bp)
    cut = np.zeros((n, n), dtype=bool)
    near = np.zeros((n, n), dtype=bool)
    for iy in range(n):
        y = xs[iy]
        for ix in range(n):
            x = xs[ix]
            _, k, d = akd.find((x, y, 0))
            if d > 8.0:
                continue
            near[iy, ix] = True
            zc = allpts[k][2]
            hit = bvh.ray_cast(Vector((x, y, zc + 60)), Vector((0, 0, -1)), 200)
            if hit[0] is None:
                continue
            hz = hit[0].z
            if hz < zc + 0.28 and hz > zc - 0.5:
                cut[iy, ix] = True
                Z[iy, ix] = zc - 0.3
            elif abs(hz - (zc + WALK_Z)) < 1.0:
                Z[iy, ix] = min(Z[iy, ix], hz - 0.015)

    # ---- retaining walls: marching squares on level steps
    def bisect_jump(p0, p1):
        a, b = 0.0, 1.0
        fa, fb = level(*p0.lerp(p1, a)), level(*p0.lerp(p1, b))
        for _ in range(8):
            m = (a + b) / 2
            fm = level(*p0.lerp(p1, m))
            if abs(fm - fa) > abs(fb - fm):
                b, fb = m, fm
            else:
                a, fa = m, fm
        return p0.lerp(p1, (a + b) / 2), abs(fb - fa)

    pts_of = {}

    def edge_pt(key):
        if key in pts_of:
            return pts_of[key]
        kind, ix, iy = key
        p0 = Vector((xs[ix], xs[iy]))
        p1 = Vector((xs[ix + 1], xs[iy])) if kind == "h" else Vector((xs[ix], xs[iy + 1]))
        pts_of[key] = bisect_jump(p0, p1)[0]
        return pts_of[key]

    def is_jump(z0, z1, n0, n1):
        return abs(z0 - z1) > JUMP and not (n0 and n1 and False)

    adj = {}

    def link(a, b):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    for iy in range(n - 1):
        for ix in range(n - 1):
            ks = []
            if abs(Zlevel[iy, ix] - Zlevel[iy, ix + 1]) > JUMP:
                ks.append(("h", ix, iy))
            if abs(Zlevel[iy + 1, ix] - Zlevel[iy + 1, ix + 1]) > JUMP:
                ks.append(("h", ix, iy + 1))
            if abs(Zlevel[iy, ix] - Zlevel[iy + 1, ix]) > JUMP:
                ks.append(("v", ix, iy))
            if abs(Zlevel[iy, ix + 1] - Zlevel[iy + 1, ix + 1]) > JUMP:
                ks.append(("v", ix + 1, iy))
            if len(ks) == 2:
                link(ks[0], ks[1])
            elif len(ks) > 2:
                ck = ("c", ix, iy)
                pts_of[ck] = sum((edge_pt(k) for k in ks), Vector((0, 0))) / len(ks)
                for k in ks:
                    link(k, ck)
    for k in adj:
        edge_pt(k) if k[0] != "c" else None

    polylines, seen = [], set()

    def walk(start, nxt):
        line = [start, nxt]
        seen.add((start, nxt))
        seen.add((nxt, start))
        prev, cur = start, nxt
        while len(adj[cur]) == 2:
            a = [q for q in adj[cur] if q != prev][0]
            if (cur, a) in seen:
                break
            seen.add((cur, a))
            seen.add((a, cur))
            line.append(a)
            prev, cur = cur, a
        return line

    for k in adj:
        if len(adj[k]) != 2:
            for q in adj[k]:
                if (k, q) not in seen:
                    polylines.append(walk(k, q))
    for k in adj:
        for q in adj[k]:
            if (k, q) not in seen:
                polylines.append(walk(k, q))
    walls = []
    for line in polylines:
        P = [pts_of[k].copy() for k in line]
        closed = line[0] == line[-1]
        for _ in range(3):
            Q = [p.copy() for p in P]
            for i in range(1, len(P) - 1):
                Q[i] = P[i] * 0.5 + (P[i - 1] + P[i + 1]) * 0.25
            P = Q
        length = sum((b - a).length for a, b in zip(P, P[1:]))
        if length < 1.5:
            continue
        # resample ~0.5 m
        cum = np.concatenate([[0], np.cumsum([(b - a).length for a, b in zip(P, P[1:])])])
        m = max(2, int(length / 0.5) + 1)
        ss = np.linspace(0, length, m)
        px = np.interp(ss, cum, [p.x for p in P])
        py = np.interp(ss, cum, [p.y for p in P])
        walls.append({"pts": [Vector((a, b)) for a, b in zip(px, py)], "closed": closed})

    wall_pts = []
    wall_objs = []
    for wi, w in enumerate(walls):
        P = w["pts"]
        recs = []
        for i, q in enumerate(P):
            a, b = P[max(0, i - 1)], P[min(len(P) - 1, i + 1)]
            t = (b - a).normalized()
            nn = rot90(t)
            za, zb = level(*(q + nn * 1.3)), level(*(q - nn * 1.3))
            low = -nn if za > zb else nn
            recs.append((q, t, nn, max(za, zb), min(za, zb), low))
        w["recs"] = recs
        bm = bmesh.new()
        rows = []
        for q, t, nn, hi, lo, low in recs:
            top, bot = hi + 0.15, lo - 0.6
            rows.append([bm.verts.new((*(q + nn * WALL_HALF), bot)), bm.verts.new((*(q + nn * WALL_HALF), top)),
                         bm.verts.new((*(q - nn * WALL_HALF), top)), bm.verts.new((*(q - nn * WALL_HALF), bot))])
            wall_pts.append((q, wi))
        for i in range(len(rows) - 1):
            r0, r1 = rows[i], rows[i + 1]
            for k in range(3):
                bm.faces.new((r0[k], r1[k], r1[k + 1], r0[k + 1]))
        bm.faces.new(rows[0][::-1])
        bm.faces.new(rows[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        me = bpy.data.meshes.new(f"RetainingWall{wi}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(M["wall"])
        wall_objs.append(put(me, (0, 0, 0), name=f"RetainingWall{wi}"))
    wkd = kdtree.KDTree(max(1, len(wall_pts)))
    for k, (q, wi) in enumerate(wall_pts):
        wkd.insert((q.x, q.y, 0), k)
    wkd.balance()

    # railings on wall tops (drops over 1 m)
    rail_cu = bpy.data.curves.new("WallRailings", "CURVE")
    rail_cu.dimensions = "3D"
    rail_cu.bevel_depth = 0.025
    posts = bmesh.new()
    for w in walls:
        run = []
        for rec in w["recs"] + [None]:
            if rec is not None:
                q, t, nn, hi, lo, low = rec
            if rec is None or hi - lo < 1.0:
                if len(run) >= 4:
                    for h in (1.0, 0.5):
                        sp = rail_cu.splines.new("POLY")
                        sp.points.add(len(run) - 1)
                        for k, (p, z) in enumerate(run):
                            sp.points[k].co = (p.x, p.y, z + h, 1)
                    for k in range(0, len(run), 4):
                        p, z = run[k]
                        bmesh.ops.create_cube(posts, size=1.0, matrix=Matrix.Translation((p.x, p.y, z + 0.5)) @ Matrix.Diagonal((0.05, 0.05, 1.0, 1)))
                run = []
                continue
            p = q + low * (WALL_HALF - 0.12)
            run.append((p, hi + 0.15))
    rail_cu.materials.append(M["metal"])
    put(rail_cu, (0, 0, 0), name="WallRailings")
    pme = bpy.data.meshes.new("RailPosts")
    posts.to_mesh(pme)
    posts.free()
    pme.materials.append(M["metal"])
    put(pme, (0, 0, 0), name="RailPosts")

    # ---- stairs along walls
    obstacles = []      # rotated rects (corners) buildings must avoid
    stairs = []
    stair_bm = bmesh.new()
    stair_rail = bpy.data.curves.new("StairRails", "CURVE")
    stair_rail.dimensions = "3D"
    stair_rail.bevel_depth = 0.02
    RISE, RUN, SW = 0.17, 0.3, 1.6
    last = []
    order = list(range(len(walls)))
    rng.shuffle(order)
    for wi in order:
        recs = walls[wi]["recs"]
        if len(recs) < 30:
            continue
        for i0 in range(4, len(recs) - 20, 7):
            q, t, nn, hi, lo, low = recs[i0]
            if not (1.4 < hi - lo < 8.0) or max(abs(q.x), abs(q.y)) > HALF - 30 or rng.random() > 0.35:
                continue
            if any((q - s).length < 35 for s in last):
                continue
            # walk along the wall, one step per RUN metres (recs are 0.5 m apart)
            off = WALL_HALF + SW / 2
            steps, zt, i, acc = [], lo, i0, 0.0
            ok = True
            while True:
                if i >= len(recs) - 1:
                    ok = False
                    break
                qa, ta, na_, hia, loa, lowa = recs[i]
                if (lowa - low).length > 0.5:
                    ok = False
                    break
                c = qa + lowa * off + ta * acc
                g = level(*c)
                if abs(g - lo) > 0.6 + abs(loa - lo) or road_dist(*c) < 7.6:
                    ok = False
                    break
                if any(wall_pts[k][1] != wi for _, k, _ in wkd.find_range((c.x, c.y, 0), WALL_HALF + SW / 2 + 0.2)):
                    ok = False
                    break
                zt += RISE
                steps.append((c, ta, lowa, g, min(zt, hia)))
                if zt >= hia - 0.02:
                    break
                acc += RUN
                while acc >= 0.5:
                    acc -= 0.5
                    i += 1
            if not ok or len(steps) < 6:
                continue
            for c, ta, lowa, g, top in steps:
                wv = rot90(ta)
                mat = Matrix(((ta.x, wv.x, 0, c.x), (ta.y, wv.y, 0, c.y), (0, 0, 1, (top + g - 0.4) / 2), (0, 0, 0, 1)))
                bmesh.ops.create_cube(stair_bm, size=1.0, matrix=mat @ Matrix.Diagonal((RUN + 0.02, SW, top - g + 0.4, 1)))
            # landing on the high ground beyond the last step
            c, ta, lowa, g, top = steps[-1]
            sp = stair_rail.splines.new("POLY")
            sp.points.add(len(steps) - 1)
            for k, (c2, ta2, lowa2, g2, top2) in enumerate(steps):
                p = c2 + lowa2 * (SW / 2 - 0.08)
                sp.points[k].co = (p.x, p.y, top2 + 0.95, 1)
            a, b = steps[0][0], steps[-1][0]
            mid = (a + b) / 2
            dirv = (b - a).normalized()
            half_len = (b - a).length / 2 + 2.5          # keep the stair foot and top open
            obstacles.append([mid + dirv * sx_ + rot90(dirv) * sy_ for sx_, sy_ in
                              ((-half_len, -SW / 2 - 2.5), (half_len, -SW / 2 - 2.5), (half_len, SW / 2 + 2.5), (-half_len, SW / 2 + 2.5))])
            li = bpy.data.lights.new("StairLight", "POINT")
            li.energy = 120
            li.color = (1.0, 0.7, 0.45)
            li.shadow_soft_size = 0.2
            put(li, (b.x, b.y, steps[-1][4] + 2.6), name="StairLight")
            li = bpy.data.lights.new("StairLight", "POINT")
            li.energy = 70
            li.color = rng.choice([(0.4, 0.9, 1.0), (1.0, 0.35, 0.7)])
            li.shadow_soft_size = 0.2
            foot = a + steps[0][2] * 1.5
            put(li, (foot.x, foot.y, steps[0][3] + 2.4), name="StairLight")
            stairs.append({"from": (a.x, a.y, steps[0][3]), "to": (b.x, b.y, steps[-1][4]), "steps": len(steps), "wall": wi})
            last.append(q)
    sme = bpy.data.meshes.new("Stairs")
    stair_bm.to_mesh(sme)
    stair_bm.free()
    sme.materials.append(M["concrete"])
    put(sme, (0, 0, 0), name="Stairs")
    stair_rail.materials.append(M["metal"])
    put(stair_rail, (0, 0, 0), name="StairRails")

    # ---- terrain mesh
    verts = np.stack(np.meshgrid(xs, xs), axis=-1).reshape(-1, 2)
    verts = np.concatenate([verts, Z.reshape(-1, 1)], axis=1)
    ii = np.arange(n * n).reshape(n, n)
    a, b, c, d = ii[:-1, :-1], ii[:-1, 1:], ii[1:, 1:], ii[1:, :-1]
    keep = ~(cut[:-1, :-1] | cut[:-1, 1:] | cut[1:, 1:] | cut[1:, :-1])
    quads = np.stack([a[keep], b[keep], c[keep], d[keep]], axis=1)
    me = bpy.data.meshes.get("TownTerrain")
    if me is not None:
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new("TownTerrain")
    me.from_pydata(verts.tolist(), [], quads.tolist())
    me.update()
    # zone colour: 0 = paved lots, 1 = rough hillside
    zone = me.color_attributes.new("zone", "FLOAT_COLOR", "POINT")
    zv = np.zeros((n * n, 4), dtype=np.float32)
    for iy in range(0, n):
        for ix in range(0, n):
            dd = road_dist(xs[ix], xs[iy]) if not near[iy, ix] else 0.0
            zv[iy * n + ix] = smooth01((dd - BAND - 2) / 10)
    zv[:, 3] = 1.0
    zone.data.foreach_set("color", zv.ravel())
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    me.materials.append(material("TownPaving", paving_nodes))
    put(me, (0, 0, 0), name="TownTerrain")

    # ---- buildings
    def bounds(o):
        xs_ = [c[0] for c in o.bound_box]
        ys_ = [c[1] for c in o.bound_box]
        return min(xs_), max(xs_), min(ys_), max(ys_)

    kinds = {k: bounds(K[k]) for k in ("building_a", "building_b", "building_c")}
    variants = {k: variant_materials(root, k, K[k]) for k in list(kinds) + ["overhead_sign"]}
    for k, v in variants.items():
        print(f"{k}: {len(v)} texture variants")
    plinth_me = bpy.data.meshes.get("PlinthBox")
    if plinth_me is None:
        plinth_me = bpy.data.meshes.new("PlinthBox")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(plinth_me)
        bm.free()
        plinth_me.materials.append(M["concrete"])

    def rect(cn_, rz, xmin, xmax, ymin, ymax):
        cs, sn = math.cos(rz), math.sin(rz)
        return [Vector((cn_.x + lx * cs - ly * sn, cn_.y + lx * sn + ly * cs)) for lx, ly in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax))]

    def overlap(a_, b_):
        for poly in (a_, b_):
            for i in range(4):
                e = poly[(i + 1) % 4] - poly[i]
                ax = Vector((-e.y, e.x))
                pa = [ax.dot(p) for p in a_]
                pb = [ax.dot(p) for p in b_]
                if max(pa) < min(pb) or max(pb) < min(pa):
                    return False
        return True

    placed = list(obstacles)

    def site_ok(cn_, rz, ext, road_clear=7.25, spread=3.0):
        """Footprint is clear of roads, walls and other buildings; returns
        (base z, lowest z) or None."""
        xmin, xmax, ymin, ymax = ext
        cs, sn = math.cos(rz), math.sin(rz)
        hw, hh = (xmax - xmin) / 2, (ymax - ymin) / 2
        lc = Vector(((xmin + xmax) / 2, (ymin + ymax) / 2))
        ctr = cn_ + Vector((lc.x * cs - lc.y * sn, lc.x * sn + lc.y * cs))
        rad = math.hypot(hw, hh)

        def dist_local(p):
            dx, dy = p.x - ctr.x, p.y - ctr.y
            lx, ly = dx * cs + dy * sn, -dx * sn + dy * cs
            return math.hypot(max(abs(lx) - hw, 0.0), max(abs(ly) - hh, 0.0))

        for co, k, d in akd.find_range((ctr.x, ctr.y, 0), rad + road_clear):
            if dist_local(Vector(co[:2])) < road_clear:
                return None
        for co, k, d in wkd.find_range((ctr.x, ctr.y, 0), rad + 1.3):
            if dist_local(Vector(co[:2])) < 1.3:
                return None
        corners = rect(cn_, rz, xmin, xmax, ymin, ymax)
        if any(overlap(corners, q) for q in placed):
            return None
        zs = []
        for u in np.linspace(-1, 1, 5):
            for v in np.linspace(-1, 1, 5):
                lx, ly = lc.x + u * hw, lc.y + v * hh
                zs.append(level(cn_.x + lx * cs - ly * sn, cn_.y + lx * sn + ly * cs))
        if max(zs) - min(zs) > spread:
            return None
        return max(zs), min(zs), corners

    lamp_cols = [(1.0, 0.62, 0.32), (0.4, 0.8, 1.0), (1.0, 0.35, 0.75), (1.0, 0.62, 0.32)]
    n_build = n_alley = 0

    def place_building(kind, cn_, rz, base, lowz, corners, sign=True):
        nonlocal n_build
        xmin, xmax, ymin, ymax = kinds[kind]
        placed.append(corners)
        b = put(K[kind].data, (cn_.x, cn_.y, base), rz, name=kind)
        mats = variants.get(kind)
        if mats:
            mats = mats + [m for m in K[kind].data.materials[:1] if m]     # the kit look stays in the mix
            b.material_slots[0].link = "OBJECT"
            b.material_slots[0].material = rng.choice(mats)
        depth = base - lowz + 0.8
        pl = put(plinth_me, ((xmin + xmax) / 2, (ymin + ymax) / 2 + 0.6, -depth / 2 + 0.02), name="Footing", parent=b)
        pl.scale = (xmax - xmin - 0.1, ymax - ymin - 1.4, depth)
        if sign and rng.random() < 0.65:
            sg = put(K["overhead_sign"].data, (rng.uniform(xmin + 1.2, xmax - 1.2), ymin + 1.2, rng.uniform(4.0, 7.5)), name="HangingSign", parent=b)
            if variants.get("overhead_sign"):      # one of the story signs, never the plain kit look
                sg.material_slots[0].link = "OBJECT"
                sg.material_slots[0].material = rng.choice(variants["overhead_sign"])
        n_build += 1
        return b

    # frontage: every run plus the junction arms leading into it
    def at_ext(path, s):
        """Path point, continuing straight beyond the ends (into junction arms)."""
        if s < 0:
            p, t = path.at(0)
            return p + (t * s).to_3d(), t
        if s > path.length:
            p, t = path.at(path.length)
            return p + (t * (s - path.length)).to_3d(), t
        return path.at(s)

    for path in runs:
        for sgn in (1, -1):
            s = -9.0
            while s < path.length + 4:
                site = None
                for kind in rng.sample(["building_a", "building_b", "building_c", "building_a", "building_b"], 5):
                    xmin, xmax, ymin, ymax = kinds[kind]
                    w = xmax - xmin
                    for back in (0.2, 0.9, 1.8):
                        pos, t = at_ext(path, s + w / 2)
                        nout = rot90(t) * sgn
                        rz = math.atan2(-nout.x, nout.y)
                        cn_ = pos.to_2d() + nout * (WALK_W + ROAD_HALF + back - ymin)
                        site = site_ok(cn_, rz, kinds[kind])
                        if site:
                            break
                    if site:
                        break
                if not site:
                    s += 2.0
                    continue
                place_building(kind, cn_, rz, site[0], site[1], site[2])
                gap = rng.uniform(0.3, 1.2)
                if rng.random() < 0.22:
                    gap = rng.uniform(2.6, 4.0)        # alley
                    n_alley += 1
                    am = pos.to_2d() + t * (w / 2 + gap / 2) + nout * (WALK_W + ROAD_HALF + 6.0)
                    li = bpy.data.lights.new("AlleyLight", "POINT")
                    li.energy = 45
                    li.color = rng.choice([(0.4, 0.9, 1.0), (1.0, 0.3, 0.6), (1.0, 0.65, 0.35)])
                    li.shadow_soft_size = 0.15
                    put(li, (am.x, am.y, level(am.x, am.y) + 3.2), name="AlleyLight")
                s += w + gap

    # back rows on the hillside
    for gy in np.arange(-HALF + 8, HALF - 8, 10.0):
        for gx in np.arange(-HALF + 8, HALF - 8, 10.0):
            for _ in range(3):
                p = Vector((gx + rng.uniform(-4, 4), gy + rng.uniform(-4, 4)))
                co, k, d = akd.find((p.x, p.y, 0))
                if d < 14:
                    break
                nout = (p - Vector(co[:2])).normalized()
                rz = math.atan2(-nout.x, nout.y) + rng.choice([0.0, 0.0, math.pi / 2, -math.pi / 2]) * (d > BAND + 15)
                kind = rng.choice(["building_a", "building_b", "building_c", "building_c"])
                site = site_ok(p, rz, kinds[kind], road_clear=7.6, spread=6.0)
                if site:
                    place_building(kind, p, rz, site[0], site[1], site[2], sign=rng.random() < 0.4)
                    break

    # ---- lamps, poles, wires
    n_lamp = 0
    pole_line = []
    for ri, path in enumerate(runs):
        s, sgn = 7.0, 1
        poles = []
        while s < path.length - 5:
            pos, t = path.at(s)
            nout = rot90(t) * sgn
            rz = math.atan2(-nout.x, nout.y)
            p = pos.to_2d() + nout * 6.4
            put(K["street_lamp"].data, (p.x, p.y, pos.z + WALK_Z), rz, name="StreetLamp")
            li = bpy.data.lights.new("LampLight", "POINT")
            li.color = lamp_cols[n_lamp % 4]
            li.energy = 420
            li.shadow_soft_size = 0.3
            lp = pos.to_2d() + nout * 4.3
            put(li, (lp.x, lp.y, pos.z + WALK_Z + 5.8), name="LampLight")
            n_lamp += 1
            s += 22
            sgn = -sgn
        s = 12.0
        side = 1 if ri % 2 == 0 else -1
        while s < path.length - 4:
            pos, t = path.at(s)
            nout = rot90(t) * side
            p = pos.to_2d() + nout * 6.65
            rz = math.atan2(-nout.x, nout.y) + math.pi / 2
            put(K["power_pole"].data, (p.x, p.y, pos.z + WALK_Z), rz, name="PowerPole")
            poles.append((p, pos.z + WALK_Z, nout))
            s += 31
        pole_line.append(poles)
    for name, j in J.items():
        for c in j.corners:
            if "C" not in c or not c["concave"]:
                continue
            mid = j.corner_line(c, 2.4)[len(j.corner_line(c, 2.4)) // 2]
            if (c["C"] - mid).length < 0.5:
                continue
            nout = (c["C"] - mid).normalized()
            rz = math.atan2(-nout.x, nout.y)
            wp = j.pos + mid
            put(K["street_lamp"].data, (wp.x, wp.y, j.z + WALK_Z), rz, name="StreetLamp")
            li = bpy.data.lights.new("LampLight", "POINT")
            li.color = lamp_cols[n_lamp % 4]
            li.energy = 420
            li.shadow_soft_size = 0.3
            lp = wp - nout * 2.1
            put(li, (lp.x, lp.y, j.z + WALK_Z + 5.8), name="LampLight")
            n_lamp += 1
    wires = bpy.data.curves.new("PowerLines", "CURVE")
    wires.dimensions = "3D"
    wires.bevel_depth = 0.012
    for poles in pole_line:
        for (p0, z0, n0), (p1, z1, n1) in zip(poles, poles[1:]):
            for off, h in ((-1.05, 8.55), (-0.35, 8.55), (0.35, 8.55), (1.05, 8.55), (0.0, 7.3)):
                a_ = p0 + n0 * off
                b_ = p1 + n1 * off
                sp = wires.splines.new("POLY")
                m = 12
                sp.points.add(m)
                sag = 0.5 + 0.02 * (b_ - a_).length
                for k in range(m + 1):
                    u = k / m
                    q = a_.lerp(b_, u)
                    z = (z0 + h) * (1 - u) + (z1 + h) * u - sag * 4 * u * (1 - u)
                    sp.points[k].co = (q.x, q.y, z, 1)
    wires.materials.append(M["wire"])
    put(wires, (0, 0, 0), name="PowerLines")

    # ---- story decals on the (Blender-side) retaining walls
    dec_dir = os.path.join(root, "assets", "decals", "story")
    pool = {
        "poster": (["poster_missing_aiko", "poster_missing_mika", "poster_missing_ren", "poster_unplug"], 0.75, 1.5, 0.0),
        "graffiti": (["graffiti_lying", "graffiti_not_data", "graffiti_unplug", "graffiti_who_owns", "stencil_eye_crossed"], 2.6, 1.3, 0.0),
        "plate": (["plate_curfew", "plate_loitering", "plate_observed", "plate_property"], 0.7, 1.7, 0.0),
        "billboard": (["billboard_meridian", "billboard_score", "billboard_dreamlink", "billboard_noctis", "billboard_jobs", "billboard_defaced"], 5.0, 2.4, 2.0),
    }
    n_dec = 0
    if os.path.isdir(dec_dir):
        for w in walls:
            recs = w["recs"]
            i = 3
            while i < len(recs) - 3:
                q, t, nn, hi, lo, low = recs[i]
                hgt = hi - lo
                if hgt < 1.6 or rng.random() > 0.45:
                    i += 4
                    continue
                kind = "billboard" if hgt > 5.5 and rng.random() < 0.6 else rng.choice(["poster", "poster", "graffiti", "plate"])
                names, width, zc, emit = pool[kind]
                img = os.path.join(dec_dir, rng.choice(names) + ".png")
                if not os.path.isfile(img):
                    i += 4
                    continue
                im = bpy.data.images.load(img, check_existing=True)
                aspect = im.size[1] / max(1, im.size[0])
                hw, hh = width / 2, width * aspect / 2
                span = int(math.ceil(hw / 0.5)) + 1
                if i - span < 0 or i + span >= len(recs):
                    i += 4
                    continue
                ends = [recs[i - span], recs[i + span]]
                ground = max(level(*(r[0] + r[5] * (WALL_HALF + 0.6))) for r in ends + [recs[i]])
                top = min(r[3] for r in ends + [recs[i]]) + 0.1
                cz = ground + zc if kind != "billboard" else (ground + top) / 2
                if cz - hh < ground + 0.15 or cz + hh > top - 0.1 or any((r[5] - low).length > 0.3 for r in ends):
                    i += 4
                    continue
                bm = bmesh.new()
                uvl = bm.loops.layers.uv.new("UVMap")
                rowv = []
                for k in range(-span, span + 1):
                    r = recs[i + k]
                    along = (r[0] - q).dot(t)
                    if abs(along) > hw:
                        continue
                    p = r[0] + r[5] * (WALL_HALF + 0.012)
                    rowv.append((along, bm.verts.new((p.x, p.y, cz - hh)), bm.verts.new((p.x, p.y, cz + hh))))
                if len(rowv) < 2:
                    bm.free()
                    i += 4
                    continue
                for (a0, v0, v1), (a1, w0, w1) in zip(rowv, rowv[1:]):
                    f = bm.faces.new((v0, w0, w1, v1))
                    for lp, (uu, vv) in zip(f.loops, ((a0, 0), (a1, 0), (a1, 1), (a0, 1))):
                        lp[uvl].uv = ((uu + hw) / (2 * hw), vv)
                bm.normal_update()
                face0 = list(bm.faces)[0]
                if face0.normal.to_2d().dot(low) < 0:
                    for f in bm.faces:
                        f.normal_flip()
                dme = bpy.data.meshes.new("StoryDecal")
                bm.to_mesh(dme)
                bm.free()
                dme.materials.append(decal_material(img, emit))
                put(dme, (0, 0, 0), name="StoryDecal_" + os.path.basename(img)[:-4])
                if kind == "billboard":
                    li = bpy.data.lights.new("BillboardLight", "AREA")
                    li.energy = 120
                    li.size = width * 0.7
                    li.color = (0.8, 0.9, 1.0)
                    lp = q + low * (WALL_HALF + 2.5)
                    o = put(li, (lp.x, lp.y, cz + hh + 0.6), name="BillboardLight")
                    o.rotation_euler = (Vector((*(-low), -0.6))).to_track_quat("-Z", "Y").to_euler()
                n_dec += 1
                i += span * 2 + 6

    # ---- night world with fog
    w = bpy.data.worlds.get("TownNight") or bpy.data.worlds.new("TownNight")
    w.use_nodes = True
    nt = w.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.012, 0.016, 0.035, 1)
    bg.inputs["Strength"].default_value = 1.0
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.005
    vol.inputs["Color"].default_value = (0.55, 0.6, 0.8, 1)
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    sc.world = w
    moon = bpy.data.lights.new("Moon", "SUN")
    moon.energy = 0.06
    moon.color = (0.6, 0.7, 1.0)
    mo = put(moon, (0, 0, 80), name="Moon")
    mo.rotation_euler = (math.radians(55), 0, math.radians(35))
    # ---- baked city sky + fog box (tools/sky/make_sky.py); TOWN_SKY = None keeps the flat world
    sky = globals().get("TOWN_SKY", "night_rain")
    if sky:
        src = os.path.join(root, "tools", "sky", "make_sky.py")
        if os.path.isfile(src):
            sky_ns = {"__name__": "make_sky", "__file__": src}
            exec(compile(open(src, encoding="utf-8").read(), src, "exec"), sky_ns)
            sky_ns["apply_sky"](sc, sky)

    # ---- default camera: street level, looking into the Y fork
    cam = bpy.data.objects.get("TownCam")
    if cam is None:
        cam = bpy.data.objects.new("TownCam", bpy.data.cameras.new("TownCam"))
    if cam.name not in coll.objects:
        coll.objects.link(cam)
    j2 = J["J2"]
    pos, t = runs[1].at(runs[1].length - 38)
    cam.location = (pos.x - t.y * 2.0, pos.y + t.x * 2.0, pos.z + 1.8)
    look = Vector((j2.pos.x, j2.pos.y, j2.z + 4.0))
    cam.rotation_euler = (look - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 24
    sc.camera = cam
    print(f"junctions {len(J)}  runs {len(runs)}  walls {len(walls)}  stairs {len(stairs)}  buildings {n_build}  alleys {n_alley}  lamps {n_lamp}  decals {n_dec}")
    return {"junctions": jinfo, "runs": runs, "walls": walls, "stairs": stairs, "level": level, "J": J,
            "buildings": n_build, "terrain": "TownTerrain"}


if not globals().get("TOWN_NO_AUTOBUILD"):
    build()
