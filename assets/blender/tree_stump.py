# Builds a sawn tree stump with buttress roots diving into the ground, for Pigment.
#
#   blender -b --factory-startup --python assets/blender/tree_stump.py -- assets/tree_stump.glb
#
# Material test: a bark texture set (assets/tiles/bark_fissured triplanar:
# fissures run up the trunk and along the roots; Moss on the up-facing root
# backs, a target for grow_ivy) and an end grain texture set on the saw cut
# (assets/tiles/end_grain on a planar UV: growth rings round the pith,
# drying checks; Spots of rot, Puddles in the dished centre). A bark-thick
# rim of Bark frames the cut. Two materials: Bark, EndGrain.
#
# The ground is z = 0; the roots end below it (export with ground=False).

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from kit import export, fbm, finish  # noqa: E402
from mathutils import Vector  # noqa: E402

R = 0.3  # trunk radius at the cut
H = 0.55  # cut height (mean)
BARK = 0.022  # bark thickness, shown as a rim on the cut
SEG, RINGS = 192, 48
ROOTS = [(0.3, 1.0), (1.55, 0.8), (2.6, 1.1), (3.8, 0.75), (5.0, 0.95)]  # angle, strength


def radius(a, z):
    """Trunk radius at angle a, height z: lumpy, with vertical bark ridges,
    flaring into a lobe over each root near the ground."""
    flare = math.exp(-max(z, 0.0) / 0.26)
    lobes = 0.0
    for ra, s in ROOTS:
        d = math.atan2(math.sin(a - ra), math.cos(a - ra))
        lobes += s * math.exp(-(d / 0.4) ** 2)
    p = Vector((math.cos(a) * 1.5, math.sin(a) * 1.5, z * 3))
    ridges = 0.012 * fbm(Vector((math.cos(a) * 9, math.sin(a) * 9, z * 1.2)), 3)
    return R * (1 + 0.05 * fbm(p, 3) + ridges + flare * (0.22 + 0.85 * lobes))


def cut_z(x, y):
    """The saw cut: tilted a little, with a smooth torn hinge on one side
    (the wood that held as the tree fell)."""
    hinge = max(0.0, (x - 0.16) / 0.14) ** 1.5 * (0.035 + 0.012 * fbm(Vector((x, y, 0)) * 12, 2))
    return H + 0.03 * y / R + hinge


def mesh_object(name, verts, faces, mat, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    if smooth:
        bpy.ops.object.shade_smooth()
    o.select_set(False)
    return finish(o, 0, mat=mat)


# --- trunk: rings from just below the ground up to the cut ---
verts, faces = [], []
for k in range(RINGS + 1):
    t = (k / RINGS) ** 1.5  # rings bunch near the ground, where the flare changes fastest
    for i in range(SEG):
        a = 2 * math.pi * i / SEG
        r = radius(a, -0.03 + t * (H + 0.03))
        x, y = r * math.cos(a), r * math.sin(a)
        verts.append((x, y, -0.03 + t * (cut_z(x, y) + 0.03)))
for k in range(RINGS):
    for i in range(SEG):
        j = (i + 1) % SEG
        faces.append((k * SEG + i, k * SEG + j, (k + 1) * SEG + j, (k + 1) * SEG + i))
top = verts[RINGS * SEG:]

# bark rim on the cut: from the trunk's top edge in by the bark thickness
rim_in = []
for x, y, _ in top:
    r = math.hypot(x, y)
    s = (r - BARK) / r
    rim_in.append((x * s, y * s, cut_z(x * s, y * s) - 0.002))
base = len(verts)
verts += rim_in
for i in range(SEG):
    j = (i + 1) % SEG
    faces.append((RINGS * SEG + i, RINGS * SEG + j, base + j, base + i))
mesh_object("bark", verts, faces, "Bark")

# --- end grain: concentric rings inside the rim, fanning to the pith; the
# heartwood dished a little (rot holds water) ---
RR = 24
v2, f2 = [], []
for k in range(RR):
    s = 1 - k / RR
    for x, y, _ in rim_in:
        px, py = x * s, y * s
        v2.append((px, py, cut_z(px, py) - 0.002 - 0.016 * math.exp(-(s / 0.35) ** 2)))
c = len(v2)
v2.append((0, 0, cut_z(0, 0) - 0.018))
for k in range(RR - 1):
    for i in range(SEG):
        j = (i + 1) % SEG
        f2.append((k * SEG + i, k * SEG + j, (k + 1) * SEG + j, (k + 1) * SEG + i))
for i in range(SEG):
    f2.append(((RR - 1) * SEG + i, (RR - 1) * SEG + (i + 1) % SEG, c))
mesh_object("cut", v2, f2, "EndGrain")


# --- roots: tapered, a little flattened, arching out of each lobe and diving
# under the ground ---
def root(name, angle, reach, r0, rise, curl, n=28, segs=14):
    pts, rad = [], []
    for k in range(n + 1):
        t = k / n
        d = 0.12 + reach * t
        a = angle + curl * t * t
        z = rise * (1 - t) ** 1.8 - 0.07 * t ** 2
        pts.append(Vector((d * math.cos(a), d * math.sin(a), z)))
        rad.append(r0 * (1 - 0.85 * t) ** 0.9 + 0.006)
    vs, fs = [], []
    up = Vector((0, 0, 1))
    for k, (p, r) in enumerate(zip(pts, rad)):
        tan = (pts[min(k + 1, n)] - pts[max(k - 1, 0)]).normalized()
        side = tan.cross(up).normalized()
        nrm = side.cross(tan).normalized()
        for i in range(segs):
            th = 2 * math.pi * i / segs
            bump = 1 + 0.08 * fbm(p * 20 + Vector((th, 0, 0)), 2)
            vs.append(tuple(p + (side * math.cos(th) * r + nrm * math.sin(th) * r * 0.75) * bump))
    for k in range(n):
        for i in range(segs):
            j = (i + 1) % segs
            fs.append((k * segs + i, k * segs + j, (k + 1) * segs + j, (k + 1) * segs + i))
    # cap the buried tip
    tip = len(vs)
    vs.append(tuple(pts[-1] + (pts[-1] - pts[-2]).normalized() * rad[-1]))
    for i in range(segs):
        fs.append((n * segs + i, n * segs + (i + 1) % segs, tip))
    return mesh_object(name, vs, fs, "Bark")


for i, (a, s) in enumerate(ROOTS):
    root("root", a, 0.3 + 0.25 * s, 0.11 + 0.045 * s, 0.2 + 0.06 * s, 0.25 * (1 if i % 2 else -1))

export("TreeStump", rotate=False, ground=False, planar={"EndGrain": (0.0, 0.0, 0.35)})
