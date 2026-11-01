"""Placeholder hero car built to the car contract (Blender 5.2, headless).

    blender -b --factory-startup --python tools/godot/make_placeholder_car.py -- [out_dir]

Writes <out_dir>/car.glb + car.json (default target/placeholder_car/; pass game/assets/car to use
it in the game), the same contract as the real car (assets/car/car.glb + car.json from the car
workstream, now merged and copied in by tools/godot/sync_car.py), so swapping is drop-in:
    glTF Y-up, the car faces glTF +Z (its left is +X), ground at y = 0
    nodes  Body, Wheel_FL, Wheel_FR, Wheel_RL, Wheel_RR (origins at the hub centres),
           Collider (convex), empties Headlight_L/R, Taillight_L/R
    car.json  wheel_radius, wheel_width, track, wheelbase, mass (+ length/width/height)
In Blender terms the car faces -Y (glTF +Z = Blender -Y) and its left is +X.
"""
import json
import math
import os
import sys

import bmesh
import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = os.path.abspath(ARGS[0]) if ARGS else os.path.join(ROOT, "target", "placeholder_car")

SPEC = {"wheel_radius": 0.34, "wheel_width": 0.24, "track": 1.62, "wheelbase": 2.74, "mass": 1350.0,
        "length": 4.62, "width": 1.92, "height": 1.32, "placeholder": True}


def mat(name, col, rough=0.4, metal=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


def box_mesh(name, parts, bevel=0.0):
    """parts: [(center, size, material_index)] -> one mesh."""
    bm = bmesh.new()
    for c, s, mi in parts:
        r = bmesh.ops.create_cube(bm, size=1.0)
        vs = r["verts"]
        bmesh.ops.scale(bm, vec=s, verts=vs)
        bmesh.ops.translate(bm, vec=c, verts=vs)
        for f in {f for v in vs for f in v.link_faces}:
            f.material_index = mi
    if bevel:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=bevel, segments=2, affect="EDGES")
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    L, W, H = SPEC["length"], SPEC["width"], SPEC["height"]
    r, wb, tr, ww = SPEC["wheel_radius"], SPEC["wheelbase"], SPEC["track"], SPEC["wheel_width"]
    paint = mat("CarPaint", (0.05, 0.055, 0.07), 0.25, 0.8)
    trim = mat("CarTrim", (0.01, 0.01, 0.012), 0.5, 0.2)
    glass = mat("CarGlass", (0.02, 0.03, 0.04), 0.05, 0.0)
    head = mat("CarHeadlight", (0.9, 0.95, 1.0), 0.2, 0.0, (0.85, 0.92, 1.0), 12.0)
    tail = mat("CarTaillight", (0.6, 0.02, 0.03), 0.3, 0.0, (1.0, 0.04, 0.06), 6.0)
    neon = mat("CarNeon", (0.1, 0.6, 0.7), 0.3, 0.0, (0.1, 0.9, 1.0), 4.0)
    tyre = mat("CarTyre", (0.015, 0.015, 0.015), 0.85, 0.0)
    rim = mat("CarRim", (0.5, 0.52, 0.55), 0.25, 1.0)

    # Body: front is -Y.  Low wedge sedan from boxes.
    floor = 0.22
    parts = [
        ((0, 0, floor + 0.3), (W, L, 0.6), 0),                       # lower body
        ((0, 0.25, floor + 0.86), (W * 0.84, L * 0.5, 0.52), 2),     # cabin glass
        ((0, 0.25, floor + 1.1), (W * 0.8, L * 0.42, 0.04), 0),      # roof
        ((0, -L / 2 + 0.02, floor + 0.42), (W * 0.86, 0.06, 0.08), 3),   # headlight bar
        ((0, L / 2 - 0.02, floor + 0.5), (W * 0.9, 0.06, 0.07), 4),      # taillight bar
        ((W / 2 - 0.01, 0, floor + 0.05), (0.04, L * 0.6, 0.04), 5),     # side neon
        ((-W / 2 + 0.01, 0, floor + 0.05), (0.04, L * 0.6, 0.04), 5),
        ((0, -L / 2 + 0.06, floor + 0.15), (W * 0.9, 0.12, 0.2), 1),     # bumpers
        ((0, L / 2 - 0.06, floor + 0.15), (W * 0.9, 0.12, 0.2), 1),
        ((0, L / 2 - 0.1, floor + 0.72), (W * 0.9, 0.18, 0.05), 1),      # spoiler
    ]
    me = box_mesh("Body", parts, bevel=0.02)
    for m in (paint, trim, glass, head, tail, neon):
        me.materials.append(m)
    body = bpy.data.objects.new("Body", me)
    sc.collection.objects.link(body)

    # Wheels: axle along X, origin at hub centre
    def wheel_mesh():
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=28, radius1=r, radius2=r, depth=ww)
        for f in bm.faces:
            f.material_index = 0
        r2 = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=r * 0.62, radius2=r * 0.62, depth=ww + 0.02)
        for f in {f for v in r2["verts"] for f in v.link_faces}:
            f.material_index = 1
        bmesh.ops.rotate(bm, verts=bm.verts[:], cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y"))
        m = bpy.data.meshes.new("Wheel")
        bm.to_mesh(m)
        bm.free()
        m.materials.append(tyre)
        m.materials.append(rim)
        for p in m.polygons:
            p.use_smooth = p.material_index == 0
        return m
    wme = wheel_mesh()
    for name, x, y in (("Wheel_FL", tr / 2, -wb / 2), ("Wheel_FR", -tr / 2, -wb / 2),
                       ("Wheel_RL", tr / 2, wb / 2), ("Wheel_RR", -tr / 2, wb / 2)):
        o = bpy.data.objects.new(name, wme)
        o.location = (x, y, r)
        sc.collection.objects.link(o)

    # Collider: a convex box hull of the body (no wheels), lifted off the ground
    cme = box_mesh("Collider", [((0, 0, floor + 0.5), (W * 0.96, L * 0.98, 0.95), 0)])
    col = bpy.data.objects.new("Collider", cme)
    sc.collection.objects.link(col)

    for name, x, y, z in (("Headlight_L", W * 0.36, -L / 2 - 0.02, floor + 0.42), ("Headlight_R", -W * 0.36, -L / 2 - 0.02, floor + 0.42),
                          ("Taillight_L", W * 0.38, L / 2 + 0.02, floor + 0.5), ("Taillight_R", -W * 0.38, L / 2 + 0.02, floor + 0.5)):
        e = bpy.data.objects.new(name, None)
        e.empty_display_type = "ARROWS"
        e.empty_display_size = 0.2
        e.location = (x, y, z)
        # local -Z of the empty points along the light (front lights forward = -Y in Blender)
        e.rotation_euler = (math.radians(90 if name.startswith("Head") else -90), 0, 0)
        sc.collection.objects.link(e)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "car.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True, export_apply=True,
                              export_extras=True, export_cameras=False, export_lights=False)
    with open(os.path.join(OUT, "car.json"), "w", encoding="utf-8") as f:
        json.dump(SPEC, f, indent=1)
    print("wrote", path)


main()
