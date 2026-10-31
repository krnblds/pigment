# Builds a wall-mounted neon sign box for Pigment and exports it as two GLBs:
# the metal frame, and the neon tubes on their own (to be made emissive).
#
#   blender -b --factory-startup --python assets/blender/neon_sign_frame.py -- assets/neon_sign_frame.glb [assets/neon_tubes.glb]
#
# Bevelled sign box with a recessed face (crease for dirt), a raised rim and
# corner bolts (convex edges for wear), a transformer box with conduit on top
# and stand-off mounting arms to wall plates at the back (+Y; the face looks
# down -Y). The tubes spell "OPEN" with an underline, bend back into the face
# at their electrode ends, and share the frame's coordinates so both files
# line up when loaded together. Each file: one mesh, one UV set inside 0..1.

import math
import sys

import bpy
from mathutils import Matrix, Vector

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "neon_sign_frame.glb"

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


def export(name, ground=True):
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
    mz = min(v.co.z for v in obj.data.vertices) if ground else 0.0
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


import os  # noqa: E402

tubes_out = sys.argv[sys.argv.index("--") + 2] if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 2 else os.path.join(os.path.dirname(out), "neon_tubes.glb")

W, D, H = 1.40, 0.15, 0.50  # sign box width (X), depth (Y), height (Z)
fy = -D / 2
face_y = fy + 0.04  # recessed face plane
wy = D / 2 + 0.10  # wall plane

# --- sign box with a recessed face ---
body = box("box", (W, D, H), (0, 0, H / 2), bevel=0.012, segments=4)
cut(body, [cutter((W - 0.10, 0.08, H - 0.10), (0, fy, H / 2))])
# raised rim strips around the opening
for z in (0.0 + 0.02, H - 0.02):
    box("rim_h", (W - 0.02, 0.012, 0.022), (0, fy - 0.004, z), bevel=0.004, segments=2)
for x in (-W / 2 + 0.02, W / 2 - 0.02):
    box("rim_v", (0.022, 0.012, H - 0.06), (x, fy - 0.004, H / 2), bevel=0.004, segments=2)
for sx in (-1, 1):
    for sz in (-1, 1):
        cyl("bolt", 0.008, 0.012, (sx * (W / 2 - 0.02), fy - 0.01, H / 2 + sz * (H / 2 - 0.02)), rot=(math.pi / 2, 0, 0), bevel=0.002, verts=6)
# tube stand-off clips on the face (little posts the tubes rest on)
for x in (-0.55, -0.3, -0.0, 0.3, 0.55):
    cyl("clip", 0.006, 0.02, (x, face_y - 0.01, 0.09), rot=(math.pi / 2, 0, 0), bevel=0.0015, verts=10)

# transformer box on top with a conduit running back to the wall
box("transformer", (0.24, 0.09, 0.07), (0.35, 0.01, H + 0.035), bevel=0.006)
box("transformer_lid", (0.25, 0.095, 0.01), (0.35, 0.01, H + 0.072), bevel=0.003, segments=2)
tube("conduit", [(0.47, 0.01, H + 0.035), (0.53, 0.01, H + 0.035), (0.53, wy, H + 0.035)], 0.012, fillet=0.04, res=3, steps=8)
box("conduit_box", (0.07, 0.03, 0.08), (0.53, wy - 0.015, H + 0.035), bevel=0.004)

# stand-off arms and wall plates at the back
for x in (-0.5, 0.5):
    for z in (0.12, 0.38):
        box("arm", (0.05, wy - D / 2 + 0.01, 0.05), (x, (wy + D / 2) / 2, z), bevel=0.005)
    box("wall_plate", (0.12, 0.012, 0.36), (x, wy + 0.006, 0.25), bevel=0.004)
    for z in (0.09, 0.41):
        cyl("wall_bolt", 0.011, 0.014, (x, wy - 0.002, z), rot=(math.pi / 2, 0, 0), bevel=0.002, verts=6)

export("NeonSignFrame")

# --- neon tubes: separate mesh, same coordinate frame (not re-grounded) ---
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
parts.clear()
out = tubes_out
TR = 0.012  # tube radius
ty = face_y - 0.023  # tube centre plane in front of the face
base, gh, hw = 0.14, 0.26, 0.10  # glyph baseline, height, half width


def stroke(pts2d, x0, fil=0.035):
    """A neon stroke from 2D glyph points; the ends dive back into the face (electrodes)."""
    p = [(x0 + u, ty, base + v) for u, v in pts2d]
    p = [(p[0][0], face_y + 0.005, p[0][2])] + p + [(p[-1][0], face_y + 0.005, p[-1][2])]
    tube("neon", p, TR, fillet=fil, res=3, steps=8)


# O: closed loop
cx = -0.45
loop = [(cx + hw * math.cos(t), ty, base + gh / 2 + gh / 2 * math.sin(t)) for t in (2 * math.pi * k / 40 for k in range(40))]
tube("neon_O", loop, TR, cyclic=True, res=3)
# P
stroke([(-hw, 0), (-hw, gh), (hw, gh), (hw, gh / 2), (-hw + 0.02, gh / 2)], -0.15, fil=0.05)
# E
stroke([(hw, gh), (-hw, gh), (-hw, 0), (hw, 0)], 0.15, fil=0.02)
stroke([(-hw + 0.03, gh / 2), (hw - 0.03, gh / 2)], 0.15)
# N
stroke([(-hw, 0), (-hw, gh), (hw, 0), (hw, gh)], 0.45, fil=0.02)
# underline
stroke([(-0.62, -0.05), (0.62, -0.05)], 0.0)

export("NeonTubes", ground=False)
