# Builds a 200 L steel oil drum for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/barrel.py -- assets/barrel.glb
#
# Cylindrical shell with a recessed lid inside a rolled top chime and a
# bottom chime (convex rims for edge wear), two rolled hoops plus small
# swaged ribs (creases for dirt), and two bung caps (2" and 3/4") on the lid.
# One UV set, no overlaps, everything inside 0..1.

import math
import sys

import bpy
from mathutils import Matrix, Vector

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "barrel.glb"

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


R, H = 0.286, 0.88  # outer radius at the hoops, height
RS = 0.279  # shell radius
SEG = 64

# --- shell with the lid recessed below the top chime ---
shell = cyl("shell", RS, H - 0.02, (0, 0, H / 2), bevel=0.006, segments=3, verts=SEG)
bpy.ops.mesh.primitive_cylinder_add(vertices=SEG, radius=RS - 0.012, depth=0.05, location=(0, 0, H - 0.01 - 0.016 + 0.025))
lid_cut = bpy.context.active_object
# a shallow dish in the bottom too, so the base is not a flat disc
bpy.ops.mesh.primitive_cylinder_add(vertices=SEG, radius=RS - 0.012, depth=0.03, location=(0, 0, 0.01 + 0.008 - 0.015))
base_cut = bpy.context.active_object
cut(shell, [lid_cut, base_cut], lip_bevel=0.002)

# rolled chimes at top and bottom
torus("top_chime", RS - 0.002, 0.009, (0, 0, H - 0.012), maj=SEG, mi=12)
torus("bottom_chime", RS - 0.002, 0.009, (0, 0, 0.012), maj=SEG, mi=12)
# two rolling hoops (raised rings) at the thirds
for z in (H * 0.335, H * 0.665):
    torus("hoop", RS, 0.011, (0, 0, z), maj=SEG, mi=12)
    # swaged ribs either side of each hoop
    for dz in (-0.05, 0.05):
        torus("rib", RS, 0.0035, (0, 0, z + dz), maj=SEG, mi=8)

# --- bung caps on the lid (lid surface sits at H - 0.026) ---
lz = H - 0.026
# 2" bung: flange ring, hex cap, raised square key
cyl("bung_flange", 0.042, 0.008, (0.165, 0, lz + 0.004), bevel=0.002, verts=32)
cyl("bung_cap", 0.033, 0.016, (0.165, 0, lz + 0.016), bevel=0.003, segments=2, verts=6)
box("bung_key", (0.024, 0.008, 0.008), (0.165, 0, lz + 0.027), bevel=0.002, segments=2)
# 3/4" vent bung
cyl("vent_flange", 0.024, 0.006, (-0.19, 0.05, lz + 0.003), bevel=0.0015, verts=24)
cyl("vent_cap", 0.017, 0.013, (-0.19, 0.05, lz + 0.0125), bevel=0.002, segments=2, verts=6)
box("vent_key", (0.014, 0.006, 0.006), (-0.19, 0.05, lz + 0.022), bevel=0.0015, segments=2)
# stamped embossed ring on the lid between the bungs
torus("lid_bead", 0.09, 0.004, (0, 0, lz), maj=48, mi=8)

export("Barrel")
