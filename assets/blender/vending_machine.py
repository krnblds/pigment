# Builds a cyberpunk-alley vending machine for Pigment and exports it as GLB.
#
#   blender -b --factory-startup --python assets/blender/vending_machine.py -- assets/vending_machine.glb
#
# Bevelled cabinet with a recessed display bay framed by a raised lip, a
# small screen inset, coin and card slots, a keypad, a deep dispenser opening
# under a hood, rows of recessed vent slots on both sides (creases for dirt),
# top cap, kick plate and feet (convex edges for wear). One UV set, no
# overlaps, everything inside 0..1.

import math
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "vending_machine.glb"

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


W, D, H = 0.90, 0.80, 1.90  # width (X), depth (Y), height (Z); the front faces -Y
FOOT = 0.03
z0 = FOOT  # cabinet bottom
CH = H - FOOT - 0.05  # cabinet height under the top cap
fy = -D / 2  # front plane

# --- cabinet with recesses cut into it ---
body = box("body", (W, D, CH), (0, 0, z0 + CH / 2), bevel=0.016, segments=4)
cuts = [
    # display bay (where the product window / screen / logo goes)
    cutter((0.58, 0.05, 1.10), (-0.09, fy, 0.62 + 0.55)),
    # small screen above the keypad
    cutter((0.17, 0.024, 0.13), (0.315, fy, 1.58)),
    # coin slot and card slot
    cutter((0.008, 0.06, 0.045), (0.36, fy, 1.30)),
    cutter((0.075, 0.06, 0.007), (0.30, fy, 1.24)),
    # coin return cup
    cutter((0.07, 0.07, 0.06), (0.315, fy, 0.42)),
    # dispenser opening: a real pocket
    cutter((0.52, 0.36, 0.24), (-0.09, fy, 0.25)),
]
# vent slot rows on both sides, low and high
for sx in (-1, 1):
    for zb in (0.16, 1.45):
        for i in range(6):
            cuts.append(cutter((0.03, 0.42, 0.014), (sx * W / 2, 0.02, zb + i * 0.04)))
# a horizontal seam around the cabinet (door line)
cut(body, cuts)

# raised lip framing the display bay
bx0, bx1, bz0, bz1 = -0.09 - 0.29, -0.09 + 0.29, 0.62, 1.72
lip = 0.03
box("bay_lip_t", (0.58 + 2 * lip, 0.02, lip), (-0.09, fy - 0.006, bz1 + lip / 2), bevel=0.006)
box("bay_lip_b", (0.58 + 2 * lip, 0.02, lip), (-0.09, fy - 0.006, bz0 - lip / 2), bevel=0.006)
box("bay_lip_l", (lip, 0.02, 1.10), (bx0 - lip / 2, fy - 0.006, (bz0 + bz1) / 2), bevel=0.006)
box("bay_lip_r", (lip, 0.02, 1.10), (bx1 + lip / 2, fy - 0.006, (bz0 + bz1) / 2), bevel=0.006)
# product shelves inside the bay (more crevices)
for z in (0.88, 1.15, 1.42):
    box("shelf", (0.56, 0.035, 0.012), (-0.09, fy + 0.018, z), bevel=0.003, segments=2)

# hood over the dispenser and a push flap hanging in the pocket
box("hood", (0.60, 0.05, 0.035), (-0.09, fy - 0.015, 0.39), bevel=0.008)
box("flap", (0.50, 0.012, 0.13), (-0.09, fy + 0.11, 0.30), bevel=0.003, segments=2, rot=(math.radians(-12), 0, 0))

# keypad: 3 x 4 raised buttons on a plate
box("keypad_plate", (0.15, 0.012, 0.19), (0.315, fy - 0.004, 1.06), bevel=0.004)
for r in range(4):
    for c in range(3):
        box("key", (0.034, 0.014, 0.03), (0.27 + c * 0.045, fy - 0.012, 1.0 - 0.0 + r * 0.04 - 0.0), bevel=0.003, segments=2)
# slot bezels
box("coin_bezel", (0.035, 0.01, 0.075), (0.36, fy - 0.003, 1.30), bevel=0.003)
# lock cylinder and door handle on the right column
cyl("lock", 0.016, 0.02, (0.33, fy - 0.006, 0.80), rot=(math.pi / 2, 0, 0), bevel=0.003, verts=24)
box("handle", (0.03, 0.04, 0.22), (0.40, fy - 0.02, 0.80), bevel=0.008)

# top cap and kick plate
box("top_cap", (W + 0.03, D + 0.03, 0.05), (0, 0, H - 0.025), bevel=0.01, segments=3)
box("kick", (W - 0.04, 0.02, 0.07), (0, fy - 0.006, z0 + 0.05), bevel=0.005)
# feet
for sx in (-1, 1):
    for sy in (-1, 1):
        cyl("foot", 0.035, FOOT + 0.01, (sx * (W / 2 - 0.07), sy * (D / 2 - 0.07), (FOOT + 0.01) / 2), bevel=0.004, verts=20)

export("VendingMachine")
