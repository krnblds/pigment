# Builds a wall-bracket air-conditioner condenser for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/ac_unit.py -- assets/ac_unit.glb
#
# Bevelled cabinet with a recessed fan bay holding a hub and blades behind a
# circular grille (bezel, rings, cross bars), a recessed service panel, a
# louvred side intake, overhanging top and base pan, two L wall brackets with
# braces, and refrigerant pipe stubs with service valves leading to the wall.
# The front faces -Y, the wall is at +Y. One UV set, everything inside 0..1.

import math
import sys

import bpy
from mathutils import Matrix, Vector

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "ac_unit.glb"

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


W, D, H = 0.90, 0.40, 0.70  # cabinet width (X), depth (Y), height (Z)
z0 = 0.20  # cabinet sits on the brackets
fy = -D / 2
fx, fz, fr = -0.13, z0 + H / 2, 0.27  # fan centre and bay radius
YR = (math.pi / 2, 0, 0)  # cylinder / torus axis along Y

# --- cabinet: fan bay, service panel and side intake are cut in ---
body = box("body", (W, D, H), (0, 0, z0 + H / 2), bevel=0.014, segments=4)
bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=fr, depth=0.12, location=(fx, fy, fz), rotation=YR)
cuts = [bpy.context.active_object]
cuts.append(cutter((0.24, 0.016, 0.50), (0.30, fy, fz)))  # service panel inset
cuts.append(cutter((0.06, 0.30, 0.48), (-W / 2, 0.0, fz)))  # side louvre bay
cut(body, cuts)

# fan hub and three pitched blades inside the bay (bay floor at fy + 0.06)
cyl("hub", 0.06, 0.05, (fx, fy + 0.035, fz), rot=YR, bevel=0.006, segments=3, verts=32)
cyl("hub_cap", 0.03, 0.02, (fx, fy + 0.005, fz), rot=YR, bevel=0.004, verts=24)
for k in range(3):
    a = k * 2 * math.pi / 3 + 0.3
    d = 0.14
    box("blade", (0.2, 0.006, 0.09), (fx + d * math.cos(a), fy + 0.035, fz - d * math.sin(a)), bevel=0.002, segments=2, rot=(math.radians(25), a, 0))
# grille: bezel ring, concentric rings, cross bars
torus("bezel", fr + 0.004, 0.014, (fx, fy, fz), rot=YR, maj=64, mi=10)
for rr in (0.065, 0.13, 0.195, 0.25):
    torus("grille_ring", rr, 0.0045, (fx, fy - 0.008, fz), rot=YR, maj=48, mi=6)
cyl("bar_h", 0.006, 2 * fr, (fx, fy - 0.008, fz), rot=(0, math.pi / 2, 0), bevel=0, verts=10)
cyl("bar_v", 0.006, 2 * fr, (fx, fy - 0.008, fz), bevel=0, verts=10)
for k in range(4):
    a = k * math.pi / 2 + math.pi / 4
    cyl("bezel_screw", 0.009, 0.01, (fx + (fr + 0.02) * math.cos(a), fy - 0.004, fz + (fr + 0.02) * math.sin(a)), rot=YR, bevel=0.002, verts=12)

# service panel: plate sitting in its inset, four screws, a raised rating plate
box("service_plate", (0.22, 0.01, 0.48), (0.30, fy + 0.004, fz), bevel=0.003, segments=2)
for sx in (-1, 1):
    for sz in (-1, 1):
        cyl("screw", 0.007, 0.008, (0.30 + sx * 0.09, fy - 0.002, fz + sz * 0.21), rot=YR, bevel=0.002, verts=12)
box("rating_plate", (0.12, 0.006, 0.07), (0.30, fy - 0.003, fz + 0.12), bevel=0.002, segments=2)

# louvred side intake: angled slats in the side bay (bay floor at x = -W/2 + 0.03)
for i in range(10):
    box("louvre", (0.034, 0.29, 0.004), (-W / 2 + 0.012, 0.0, z0 + 0.15 + i * 0.045), bevel=0.0015, segments=2, rot=(0, math.radians(-35), 0))

# overhanging top and base pan
box("top", (W + 0.03, D + 0.03, 0.025), (0, 0, z0 + H + 0.0125), bevel=0.006)
box("base_pan", (W + 0.02, D + 0.02, 0.03), (0, 0, z0 + 0.015), bevel=0.006)

# --- L wall brackets with diagonal braces and wall plates ---
wy = D / 2 + 0.06  # wall plane
for x in (-0.30, 0.30):
    box("arm", (0.04, wy - fy + 0.02, 0.04), (x, (wy + fy) / 2, z0 - 0.02), bevel=0.004)
    box("leg", (0.04, 0.04, 0.22), (x, wy - 0.02, 0.11), bevel=0.004)
    y_a, z_a, y_b, z_b = wy - 0.03, 0.03, fy + 0.10, z0 - 0.04
    ln = math.hypot(y_a - y_b, z_a - z_b)
    box("brace", (0.03, ln, 0.03), (x, (y_a + y_b) / 2, (z_a + z_b) / 2), bevel=0.004, rot=(math.atan2(z_b - z_a, y_b - y_a) - math.pi, 0, 0))
    box("wall_plate", (0.11, 0.012, 0.30), (x, wy + 0.006, 0.15), bevel=0.003)
    for zb in (0.04, 0.26):
        cyl("bolt", 0.01, 0.014, (x, wy - 0.002, zb), rot=YR, bevel=0.002, verts=6)
    box("pad", (0.06, 0.08, 0.012), (x, -0.08, z0 - 0.003), bevel=0.003, segments=2)

# --- refrigerant pipe stubs: out of the +X side, bend, run back into the wall ---
box("valve_cover", (0.012, 0.16, 0.16), (W / 2 + 0.006, 0.09, z0 + 0.14), bevel=0.003)
for (pz, pr) in ((z0 + 0.17, 0.011), (z0 + 0.11, 0.008)):
    box("service_valve", (0.04, 0.045, 0.04), (W / 2 + 0.03, 0.09, pz), bevel=0.004)
    tube("line", [(W / 2 + 0.03, 0.09, pz), (W / 2 + 0.10, 0.09, pz), (W / 2 + 0.10, wy, pz)], pr, fillet=0.05, res=3, steps=10)
# insulation sleeve on the suction line
tube("insulation", [(W / 2 + 0.10, 0.15, z0 + 0.17), (W / 2 + 0.10, wy - 0.01, z0 + 0.17)], 0.02, res=4)
box("wall_sleeve", (0.10, 0.012, 0.13), (W / 2 + 0.10, wy + 0.004, z0 + 0.14), bevel=0.003)

export("AcUnit")
