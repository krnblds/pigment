# Builds a front-load trash dumpster for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/trash_dumpster.py -- assets/trash_dumpster.glb
#
# Hollow bin with a sloped front (tapered body), vertical ribs front and back,
# a boxed top rim, two hinged lid flaps left slightly open (with stiffening
# ribs and grab lips), hollow fork-lift pockets on both sides and four swivel
# casters. Bevelled convex edges for wear, rib/rim/pocket creases for dirt.
# The front faces -Y. One UV set, no overlaps, everything inside 0..1.

import math
import sys

import bpy
from mathutils import Matrix, Vector

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "trash_dumpster.glb"

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


import bmesh  # noqa: E402


def hull(name, pts):
    """A closed convex mesh object from a point list."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    for p in pts:
        bm.verts.new(p)
    bmesh.ops.convex_hull(bm, input=bm.verts)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def prism(name, xb, xt, yfb, yft, yb, z0, z1):
    """Tapered bin volume: half widths xb/xt at bottom/top, sloped front, vertical back."""
    return hull(name, [(sx * x, y, z) for (x, yf, z) in ((xb, yfb, z0), (xt, yft, z1)) for y in (yf, yb) for sx in (-1, 1)])


zb, zt = 0.14, 1.10  # body bottom / top of the walls
XB, XT = 0.78, 0.80  # half widths
YFB, YFT, YB = -0.33, -0.55, 0.55  # front at bottom / top, back
T = 0.03  # wall thickness


def front_y(z):
    return YFB + (YFT - YFB) * (z - zb) / (zt - zb)


# --- hollow tapered body ---
body = finish(prism("body", XB, XT, YFB, YFT, YB, zb, zt), 0.02, segments=4)
zi1 = zt + 0.3
inner = prism("inner", XB - T, XT - T + (XT - XB) * 0.3 / (zt - zb), YFB + T, front_y(zi1) + T, YB - T, zb + 0.04, zi1)
cut(body, [inner], lip_bevel=0.006)

# boxed rim around the top opening
rim = box("rim", (2 * XT + 0.06, YB - YFT + 0.06, 0.07), (0, 0, zt - 0.035), bevel=0.008, segments=3)
cut(rim, [cutter((2 * XT - 0.04, YB - YFT - 0.04, 0.3), (0, 0, zt))], lip_bevel=0.004)

# vertical ribs: on the sloped front (tilted with it) and on the back
tilt = math.atan2(YFB - YFT, zt - zb)
ln = math.hypot(YFB - YFT, zt - zb) - 0.12
zm = (zb + zt - 0.07) / 2
n_out = Vector((0, -math.cos(tilt), -math.sin(tilt)))
for x in (-0.6, -0.2, 0.2, 0.6):
    c = Vector((x, front_y(zm), zm)) + n_out * 0.012
    box("rib_front", (0.07, 0.04, ln), tuple(c), bevel=0.008, rot=(tilt, 0, 0))
    box("rib_back", (0.07, 0.04, zt - zb - 0.1), (x, YB + 0.012, (zb + zt - 0.07) / 2), bevel=0.008)
# bottom skid band around the base
box("base_band_back", (2 * XB + 0.02, 0.03, 0.06), (0, YB + 0.008, zb + 0.03), bevel=0.006)

# hollow fork-lift pockets on both sides
zp = 0.62
for sx in (-1, 1):
    xs = XB + (XT - XB) * (zp - zb) / (zt - zb)
    pk = box("pocket", (0.12, 0.92, 0.17), (sx * (xs + 0.055), 0.07, zp), bevel=0.008)
    cut(pk, [cutter((0.075, 1.2, 0.12), (sx * (xs + 0.055), 0.07, zp))], lip_bevel=0.003)
    for y in (-0.25, 0.4):
        box("gusset", (0.05, 0.03, 0.1), (sx * (xs + 0.02), y, zp - 0.12), bevel=0.004)

# --- two lid flaps hinged at the back, left slightly open ---
hinge = Vector((0, YB + 0.03, zt + 0.02))
LL, LT = YB - YFT + 0.06, 0.035  # flap length (Y) and thickness


def lid_part(name, size, local, ang, bevel):
    R = Matrix.Rotation(-ang, 3, "X")
    return box(name, size, tuple(hinge + R @ Vector(local)), bevel=bevel, rot=(-ang, 0, 0))


for xc, ang in ((-0.41, math.radians(2.5)), (0.41, math.radians(6))):
    lid_part("lid", (0.80, LL, LT), (xc, -LL / 2, LT / 2), ang, 0.01)
    for dx in (-0.22, 0.0, 0.22):
        lid_part("lid_rib", (0.045, LL - 0.14, 0.022), (xc + dx, -LL / 2 + 0.02, LT + 0.011), ang, 0.007)
    lid_part("grab_lip", (0.34, 0.035, 0.05), (xc, -LL + 0.02, -0.01), ang, 0.006)
    for dx in (-0.27, 0.27):
        cyl("hinge_pin", 0.018, 0.12, (xc + dx, hinge.y, hinge.z), rot=(0, math.pi / 2, 0), bevel=0.003, verts=16)
        box("hinge_leaf", (0.1, 0.012, 0.07), (xc + dx, YB + 0.016, zt - 0.03), bevel=0.003)

# --- swivel casters ---
for x in (-0.62, 0.62):
    for y in (-0.20, 0.42):
        box("caster_plate", (0.13, 0.13, 0.012), (x, y, zb - 0.006), bevel=0.003, segments=2)
        cyl("swivel", 0.035, 0.02, (x, y, zb - 0.022), bevel=0.003, verts=20)
        for dx in (-0.033, 0.033):
            box("fork", (0.01, 0.06, 0.08), (x + dx, y, 0.078), bevel=0.003, segments=2)
        cyl("wheel", 0.06, 0.045, (x, y, 0.06), rot=(0, math.pi / 2, 0), bevel=0.008, segments=3, verts=28)
        cyl("axle", 0.012, 0.085, (x, y, 0.06), rot=(0, math.pi / 2, 0), bevel=0.002, verts=12)

export("TrashDumpster")
