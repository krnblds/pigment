"""Small solid builders shared by the part kits: bevelled boxes, lathes, tubes.

Every kit function returns [(name, group, obj)]; `group` is the material family the
texturing script paints (paint, black_trim, chrome, glass, lens_*, emitter_*, ...).
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from .geom import apply_mods, bm_box, bm_obj

TAU = 2 * math.pi


def obj(name, bm, smooth=True):
    return bm_obj(name, bm, smooth_shade=smooth)


def mods(ob, bevel=None, subd=0, seg=2, solid=None, weld=False):
    if bevel:
        m = ob.modifiers.new("bev", "BEVEL")
        m.width = bevel
        m.segments = seg
        m.limit_method = "ANGLE"
        m.harden_normals = False
    if solid:
        m = ob.modifiers.new("sol", "SOLIDIFY")
        m.thickness = solid
        m.offset = -1
    if subd:
        m = ob.modifiers.new("sub", "SUBSURF")
        m.levels = subd
        m.render_levels = subd
    apply_mods(ob)
    return ob


def box(name, c, s, bevel=0.0, rot=None, subd=0, seg=2):
    bm = bmesh.new()
    mat = None
    if rot is not None:
        mat = Matrix.Translation(Vector(c)) @ rot @ Matrix.Translation(-Vector(c))
    bm_box(bm, c, s, mat)
    ob = obj(name, bm, smooth=bool(subd))
    if bevel:
        bevel = min(bevel, 0.4 * min(s))   # wider bevels collapse thin boxes into degenerate faces
    if bevel or subd:
        mods(ob, bevel=bevel or None, subd=subd, seg=seg)
    return ob


def rot_x(deg):
    return Matrix.Rotation(math.radians(deg), 4, "X")


def lathe(name, profile, c, axis="Y", seg=24, sign=1, closed_ends=False):
    """Revolve [(r, a)] (radius, axial offset) around `axis` through c."""
    bm = bmesh.new()
    rings = []
    for r, a in profile:
        ring = []
        for k in range(seg):
            t = TAU * k / seg
            u, v = r * math.cos(t), r * math.sin(t)
            if axis == "Y":
                p = (c[0] + u, c[1] + sign * a, c[2] + v)
            elif axis == "X":
                p = (c[0] + sign * a, c[1] + u, c[2] + v)
            else:
                p = (c[0] + u, c[1] + v, c[2] + sign * a)
            ring.append(bm.verts.new(p))
        rings.append(ring)
    for A, Bq in zip(rings, rings[1:]):
        for k in range(seg):
            bm.faces.new((A[k], A[(k + 1) % seg], Bq[(k + 1) % seg], Bq[k]))
    if closed_ends:
        bm.faces.new(rings[0])
        bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj(name, bm)


def mirror_x(ob, name):
    n = ob.copy()
    n.data = ob.data.copy()
    n.name = name
    bpy.context.scene.collection.objects.link(n)
    n.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    n.data.flip_normals()
    return n


SIDES = ((1, "L"), (-1, "R"))
