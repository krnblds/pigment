# Builds a cluster of wall pipes for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/pipes_cluster.py -- assets/pipes_cluster.glb
#
# Four parallel horizontal pipes of different diameters (~2.5 m run) held off
# the wall (+Y) by vertical strut channels with clamp rings and stand-offs.
# The big main bends down through an elbow into a floor flange; bolted
# flange joints, end flanges, a gate valve with handwheel and conduit
# couplings add convex edges for wear and crevices for dirt. The pipes face
# -Y. One UV set, no overlaps, everything inside 0..1.

import math
import sys

import bpy
from mathutils import Matrix, Vector

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "pipes_cluster.glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
parts = []


def finish(o, bevel, segments=3, angle=35):
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.shade_smooth()
    if bevel > 0:
        m = o.modifiers.new("bevel", "BEVEL")
        m.width = bevel
        m.segments = segments
        m.limit_method = "ANGLE"
        m.angle_limit = math.radians(angle)
        m.harden_normals = True
    o.select_set(False)
    parts.append(o)
    return o


def box(name, size, loc, bevel=0.004, segments=3, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    return finish(o, bevel, segments)


def cyl(name, r, depth, loc, rot=(0, 0, 0), bevel=0.002, segments=2, verts=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return finish(o, bevel, segments)


def apply_mods(o):
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def cutter(size, loc, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    c = bpy.context.active_object
    c.scale = size
    return c


def cut(body, cutters, lip_bevel=0.0025):
    """Boolean the cutters out of an already-bevelled body, then bevel the new lips."""
    apply_mods(body)
    parts.remove(body)
    for c in cutters:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = c
        c.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bm = body.modifiers.new("cut", "BOOLEAN")
        bm.operation = "DIFFERENCE"
        bm.object = c
        try:
            bm.solver = "EXACT"
        except TypeError:
            pass
        apply_mods(body)
        bpy.data.objects.remove(c, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = body
    body.select_set(True)
    if body.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
    body.select_set(False)
    return finish(body, lip_bevel, 2, angle=40)


def export(name):
    for o in parts:
        apply_mods(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    mz = min(v.co.z for v in obj.data.vertices)
    for v in obj.data.vertices:
        v.co.z -= mz

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.006)
    bpy.ops.object.mode_set(mode="OBJECT")

    me = obj.data
    assert len(me.uv_layers) == 1, len(me.uv_layers)
    uv = me.uv_layers[0].data
    us = [d.uv.x for d in uv]
    vs = [d.uv.y for d in uv]
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    print(f"UV bounds: u [{umin:.4f}, {umax:.4f}]  v [{vmin:.4f}, {vmax:.4f}]")
    assert umin >= 0 and vmin >= 0 and umax <= 1 and vmax <= 1, "UVs outside 0..1"

    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    print(f"{name}: {len(me.vertices)} verts, {len(me.polygons)} faces, {tris} tris, uv layers {len(me.uv_layers)}")
    print(f"origin {tuple(round(c, 4) for c in obj.location)}")
    print(f"size: {max(xs)-min(xs):.3f} x {max(ys)-min(ys):.3f} x {max(zs)-min(zs):.3f} m, min z {min(zs):.4f}")
    assert tris < 60000, tris

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_texcoords=True, export_normals=True, export_materials="NONE", export_yup=True)
    print("exported", out)




def torus(name, R, r, loc, rot=(0, 0, 0), maj=48, mi=10):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=maj, minor_segments=mi, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return finish(o, 0)


def fillet_path(pts, rad, steps=8):
    """Round the corners of a polyline with quadratic arcs (bent tube look)."""
    pts = [Vector(p) for p in pts]
    if rad <= 0 or len(pts) < 3:
        return pts
    res = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, p, b = pts[i - 1], pts[i], pts[i + 1]
        da, db = a - p, b - p
        t = min(rad, da.length / 2, db.length / 2)
        p0 = p + da.normalized() * t
        p1 = p + db.normalized() * t
        for k in range(steps + 1):
            s = k / steps
            res.append((1 - s) ** 2 * p0 + 2 * (1 - s) * s * p + s * s * p1)
    res.append(pts[-1])
    clean = [res[0]]
    for q in res[1:]:
        if (q - clean[-1]).length > 1e-5:
            clean.append(q)
    return clean


def tube(name, pts, r, fillet=0.0, cyclic=False, res=4, steps=8):
    """A round tube along a polyline: curve with bevel depth, converted to mesh."""
    cd = bpy.data.curves.new(name, "CURVE")
    cd.dimensions = "3D"
    cd.bevel_mode = "ROUND"
    cd.bevel_depth = r
    cd.bevel_resolution = res
    cd.use_fill_caps = not cyclic
    path = [Vector(p) for p in pts] if cyclic else fillet_path(pts, fillet, steps)
    sp = cd.splines.new("POLY")
    sp.points.add(len(path) - 1)
    for pt, co in zip(sp.points, path):
        pt.co = (co.x, co.y, co.z, 1.0)
    sp.use_cyclic_u = cyclic
    o = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    o = bpy.context.active_object
    o.select_set(False)
    return finish(o, 0)


XL, XR = -1.25, 1.25  # run extents
YA = (0, math.pi / 2, 0)  # cylinder / torus axis along X
wy = 0.0  # wall plane; everything sits at y < 0

# (name, radius, y centre, z centre)
P1 = (0.10, -0.17, 0.78)
P2 = (0.065, -0.13, 0.48)
P3 = (0.04, -0.10, 1.04)
P4 = (0.025, -0.07, 1.20)


def flange(x, r, y, z, bolts=8, t=0.022, along=YA):
    """A bolted flange ring around a pipe running along X at (y, z)."""
    fr = r + 0.045 if r > 0.05 else r + 0.03
    cyl("flange", fr, t, (x, y, z), rot=along, bevel=0.004, segments=2, verts=40)
    for k in range(bolts):
        a = 2 * math.pi * (k + 0.5) / bolts
        br = (r + fr) / 2 + 0.005
        cyl("flange_bolt", 0.009 if r > 0.05 else 0.006, t + 0.02, (x, y + br * math.cos(a), z + br * math.sin(a)), rot=along, bevel=0.002, verts=6)


# --- P1: main line, elbow down into a floor flange ---
r1, y1, z1 = P1
xe = 1.10  # vertical drop position
tube("main", [(XL + 0.01, y1, z1), (xe, y1, z1), (xe, y1, 0.03)], r1, fillet=0.26, res=6, steps=16)
flange(XL + 0.012, r1, y1, z1)
flange(-0.45, r1, y1, z1)
flange(-0.45 + 0.024, r1, y1, z1)
flange(0.62, r1, y1, z1)
cyl("floor_flange", r1 + 0.07, 0.03, (xe, y1, 0.015), bevel=0.006, segments=3, verts=40)
for k in range(6):
    a = 2 * math.pi * k / 6
    cyl("floor_bolt", 0.012, 0.02, (xe + (r1 + 0.045) * math.cos(a), y1 + (r1 + 0.045) * math.sin(a), 0.035), bevel=0.002, verts=6)
# flange pair on the vertical drop (axis Z)
cyl("drop_flange", r1 + 0.045, 0.022, (xe, y1, 0.32), bevel=0.004, segments=2, verts=40)
cyl("drop_flange", r1 + 0.045, 0.022, (xe, y1, 0.32 + 0.024), bevel=0.004, segments=2, verts=40)

# --- P2: straight line with a flanged joint ---
r2, y2, z2 = P2
x2e = xe - r1 - 0.09  # stops short of the main line's drop, blind-flanged
tube("line2", [(XL + 0.01, y2, z2), (x2e, y2, z2)], r2, res=5)
for x in (XL + 0.012, 0.25, 0.25 + 0.024, x2e - 0.012):
    flange(x, r2, y2, z2, bolts=6)
cyl("blind_flange", r2 + 0.045, 0.014, (x2e + 0.007, y2, z2), rot=YA, bevel=0.004, segments=2, verts=40)

# --- P3: smaller line with a gate valve and handwheel ---
r3, y3, z3 = P3
tube("line3", [(XL + 0.01, y3, z3), (XR - 0.01, y3, z3)], r3, res=4)
xv = -0.15
for x in (xv - 0.07, xv + 0.07):
    flange(x, r3, y3, z3, bolts=4, t=0.016)
box("valve_body", (0.12, 0.11, 0.11), (xv, y3, z3), bevel=0.012, segments=3)
cyl("bonnet", 0.03, 0.10, (xv, y3, z3 + 0.10), bevel=0.004, verts=20)
cyl("stem", 0.008, 0.10, (xv, y3, z3 + 0.19), bevel=0, verts=10)
torus("handwheel", 0.07, 0.008, (xv, y3, z3 + 0.22), maj=32, mi=8)
for k in range(3):
    a = k * 2 * math.pi / 3
    box("spoke", (0.07, 0.008, 0.008), (xv + 0.035 * math.cos(a), y3 + 0.035 * math.sin(a), z3 + 0.22), bevel=0.0, rot=(0, 0, a))
for x in (XL + 0.01, XR - 0.01):
    flange(x, r3, y3, z3, bolts=4, t=0.016)

# --- P4: electrical conduit with couplings ---
r4, y4, z4 = P4
tube("conduit", [(XL + 0.01, y4, z4), (XR - 0.01, y4, z4)], r4, res=3)
for x in (-0.9, -0.1, 0.7):
    cyl("coupling", r4 + 0.007, 0.05, (x, y4, z4), rot=YA, bevel=0.003, verts=20)

# --- wall struts with clamp rings and stand-offs ---
for xs in (-0.95, -0.05, 0.85):
    box("strut", (0.042, 0.042, 1.02), (xs, wy - 0.021, 0.31 + 0.51), bevel=0.004, segments=2)
    cut_slot = cutter((0.012, 0.03, 0.96), (xs, wy - 0.042, 0.82))  # open channel lip
    cut(parts[-1], [cut_slot], lip_bevel=0.0015)
    for zp in (0.31, 1.33):
        box("strut_plate", (0.10, 0.01, 0.06), (xs, wy - 0.005, zp), bevel=0.003, segments=2)
        cyl("anchor", 0.01, 0.016, (xs + 0.035, wy - 0.012, zp), rot=(math.pi / 2, 0, 0), bevel=0.002, verts=6)
    for (r, y, z) in (P1, P2, P3, P4):
        torus("clamp", r + 0.006, 0.007, (xs, y, z), rot=YA, maj=40 if r > 0.05 else 28, mi=8)
        y_back = y + r + 0.006
        box("standoff", (0.03, abs(y_back - (wy - 0.042)) + 0.01, 0.022), (xs, (y_back + wy - 0.042) / 2, z), bevel=0.003, segments=2)
        cyl("clamp_bolt", 0.006, 0.03, (xs, y, z + r + 0.016), bevel=0.0015, verts=6)

export("PipesCluster")
