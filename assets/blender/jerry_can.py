# Builds a hard-surface 20 L jerry can for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/jerry_can.py -- assets/jerry_can.glb
#
# Bevelled body with stamped X recesses on both broad faces (concave creases
# for dirt), a welded seam flange around the perimeter, top and bottom rims,
# a three-bar handle and an angled spout with cap and clamp lever (convex
# edges for wear). One UV set, no overlaps, everything inside 0..1.

import math
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "jerry_can.glb"

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


W, D, H = 0.345, 0.165, 0.415  # body width (X), depth (Y), height (Z)

# --- body: bevelled box, then stamped X recesses cut into both broad faces ---
body = box("body", (W, D, H), (0, 0, H / 2 + 0.004), bevel=0.016, segments=5)
apply_mods(body)
parts.remove(body)

rx0, rx1, rz0, rz1 = -0.118, 0.118, 0.07, 0.37  # X spans this rectangle
ang = math.atan2(rz1 - rz0, rx1 - rx0)
diag = math.hypot(rx1 - rx0, rz1 - rz0)
zc = (rz0 + rz1) / 2 + 0.004
cutters = []
for sy in (-1, 1):
    y = sy * D / 2
    for a in (-ang, ang):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, y, zc), rotation=(0, a, 0))
        c = bpy.context.active_object
        c.scale = (diag, 0.014, 0.034)
        cutters.append(c)
    # shallow stamped frame around the X (horizontal grooves top and bottom)
    for z in (rz0 - 0.03, rz1 + 0.03):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, y, z + 0.004))
        c = bpy.context.active_object
        c.scale = (rx1 - rx0 + 0.05, 0.010, 0.016)
        cutters.append(c)
# one boolean per cutter: robust, and the overlapping cutters merge cleanly
for c in cutters:
    bpy.context.view_layer.objects.active = c
    bpy.ops.object.select_all(action="DESELECT")
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
assert len(body.data.polygons) > 200, "boolean emptied the body"
# the boolean leaves big n-gons with interpolated custom normals (visible as
# shading blotches on the flat faces): drop them, split normals at hard edges
bpy.context.view_layer.objects.active = body
body.select_set(True)
if body.data.has_custom_normals:
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
body.select_set(False)
# second, small bevel rounds the recess lips; the body's 5-segment bevel has
# face angles below the limit, so it is left alone
finish(body, 0.0025, 2, angle=40)

# --- welded seam flange around the perimeter (the two stamped halves) ---
box("seam", (W + 0.012, 0.007, H + 0.010), (0, 0, H / 2 + 0.004), bevel=0.0025, segments=2)
# rims around the bottom and top of the body
box("foot_rim", (W + 0.008, D + 0.008, 0.022), (0, 0, 0.011), bevel=0.004, segments=3)
box("top_rim", (W + 0.006, D + 0.006, 0.016), (0, 0, H - 0.006), bevel=0.004, segments=3)

# --- three-bar handle on top (bars run along X, spaced in Y) ---
hx, hl, hz = -0.045, 0.17, H + 0.004 + 0.042
for y in (-0.042, 0.0, 0.042):
    cyl("handle_bar", 0.0105, hl, (hx, y, hz), rot=(0, math.pi / 2, 0), bevel=0.003, segments=2, verts=20)
for s in (-1, 1):
    # posts welded to the top that carry the bars
    box("handle_post", (0.022, 0.118, 0.05), (hx + s * (hl / 2 - 0.018), 0, H + 0.004 + 0.022), bevel=0.005, segments=3)
# a raised plate the handle is welded onto
box("handle_plate", (hl + 0.02, 0.135, 0.008), (hx, 0, H + 0.004 + 0.003), bevel=0.003, segments=2)

# --- spout at the +X corner, tilted outward, with cap and clamp lever ---
tilt = math.radians(28)
sx, sz = 0.118, H + 0.004
ux, uz = math.sin(tilt), math.cos(tilt)  # spout axis in XZ
cyl("spout_collar", 0.034, 0.02, (sx, 0, sz + 0.004), bevel=0.003, segments=2, verts=32)
cyl("spout_neck", 0.024, 0.04, (sx + ux * 0.018, 0, sz + uz * 0.018), rot=(0, tilt, 0), bevel=0.002, verts=28)
cap_c = 0.046
cyl("spout_cap", 0.031, 0.026, (sx + ux * cap_c, 0, sz + uz * cap_c), rot=(0, tilt, 0), bevel=0.004, segments=3, verts=32)
cyl("cap_top", 0.022, 0.008, (sx + ux * (cap_c + 0.016), 0, sz + uz * (cap_c + 0.016)), rot=(0, tilt, 0), bevel=0.002, verts=28)
# clamp lever lying back over the top, hinged near the handle
box("clamp_lever", (0.085, 0.022, 0.010), (sx - 0.05, 0, sz + 0.03), bevel=0.003, segments=2, rot=(0, -math.radians(12), 0))
cyl("clamp_hinge", 0.008, 0.05, (sx - 0.085, 0, sz + 0.012), rot=(math.pi / 2, 0, 0), bevel=0.0015, verts=16)
box("hinge_block", (0.022, 0.05, 0.014), (sx - 0.085, 0, sz + 0.006), bevel=0.003, segments=2)

# --- apply modifiers, join into one mesh ---
for o in parts:
    apply_mods(o)
bpy.ops.object.select_all(action="DESELECT")
for o in parts:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
can = bpy.context.active_object
can.name = "JerryCan"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# sit exactly on the ground
mz = min(v.co.z for v in can.data.vertices)
for v in can.data.vertices:
    v.co.z -= mz

# --- one UV set: smart project, then pack with a margin ---
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
bpy.ops.uv.pack_islands(rotate=True, margin=0.006)
bpy.ops.object.mode_set(mode="OBJECT")

me = can.data
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
print(f"JerryCan: {len(me.vertices)} verts, {len(me.polygons)} faces, {tris} tris, uv layers {len(me.uv_layers)}")
loc = can.location
print(f"origin {tuple(round(c, 4) for c in loc)}")
print(f"size: {max(xs)-min(xs):.3f} x {max(ys)-min(ys):.3f} x {max(zs)-min(zs):.3f} m, min z {min(zs):.4f}")

bpy.ops.object.select_all(action="DESELECT")
can.select_set(True)
bpy.context.view_layer.objects.active = can
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_texcoords=True, export_normals=True, export_materials="NONE", export_yup=True)
print("exported", out)
