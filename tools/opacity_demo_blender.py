"""Headless Cycles demo of Pigment's opacity / transmission channel.

Needs the Pigment exports in scenes/town/textures/{building_a,fence}
(python tools/town_textures.py building_a fence). Renders a street-level
shot of building_a seen through a row of chain-link fences (cut-out
opacity) and a close-up of its glass windows (partly transparent,
transmissive, reflecting the neon across the street).

    blender -b --factory-startup --python tools/opacity_demo_blender.py -- [out_dir] [samples]
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = os.path.abspath(argv[0]) if argv else os.path.join(ROOT, "docs", "agents", "opacity")
SAMPLES = int(argv[1]) if len(argv) > 1 else 192
os.makedirs(OUT, exist_ok=True)

ns = {"__name__": "blender_pigment"}
exec(compile(open(os.path.join(HERE, "blender_pigment.py"), encoding="utf-8").read(), "blender_pigment.py", "exec"), ns)
apply_pigment_material = ns["apply_pigment_material"]

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene


def import_kit(asset, emission=6.0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ROOT, "assets", "town", f"{asset}.glb"))
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in new:
        o.select_set(True)
    bpy.context.view_layer.objects.active = new[0]
    if len(new) > 1:
        bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = f"KIT_{asset}"
    # drop import empties, keep the world transform
    obj.parent = None
    for o in [o for o in bpy.data.objects if o not in before and o.type == "EMPTY"]:
        bpy.data.objects.remove(o, do_unlink=True)
    apply_pigment_material(obj, os.path.join(ROOT, "scenes", "town", "textures", asset), asset, emission_strength=emission)
    return obj


def emissive_plane(name, size, loc, rot, color, strength):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    p = bpy.context.active_object
    p.name = name
    p.scale = (size[0], size[1], 1)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    p.data.materials.append(m)
    return p


building = import_kit("building_a")
fence = import_kit("fence")

# a row of fences in front of the building (kit faces -Y after glTF import)
bmin = Vector(min((building.matrix_world @ Vector(c)) for c in building.bound_box))
lo = [min((building.matrix_world @ Vector(c))[k] for c in building.bound_box) for k in range(3)]
hi = [max((building.matrix_world @ Vector(c))[k] for c in building.bound_box) for k in range(3)]
front_y = lo[1]
fence_y = front_y - 4.0
fences = [fence]
for i, x in enumerate((-6.0, -3.0, 0.0, 3.0, 6.0)):
    f = fence if i == 0 else fence.copy()
    if i:
        scene.collection.objects.link(f)
    f.location = (x, fence_y, 0.0)
    fences.append(f)

# ground: wet asphalt
bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, 0))
ground = bpy.context.active_object
gm = bpy.data.materials.new("Wet asphalt")
gm.use_nodes = True
b = next(n for n in gm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
b.inputs["Base Color"].default_value = (0.02, 0.02, 0.022, 1)
b.inputs["Roughness"].default_value = 0.12
ground.data.materials.append(gm)

# neon across the street (what the windows reflect) and a warm street light
emissive_plane("Neon sign (pink)", (6.0, 1.6), (-4.0, front_y - 16.0, 7.0), (math.radians(90), 0, 0), (1.0, 0.1, 0.55), 12.0)
emissive_plane("Neon sign (cyan)", (5.0, 1.2), (5.0, front_y - 16.0, 11.0), (math.radians(90), 0, 0), (0.1, 0.85, 1.0), 12.0)
emissive_plane("Screen wall", (14.0, 6.0), (0.0, front_y - 18.0, 18.0), (math.radians(90), 0, 0), (0.25, 0.35, 1.0), 2.0)
for loc, col, e in (((-8.0, front_y - 7.0, 6.0), (1.0, 0.65, 0.35), 2500.0), ((7.0, front_y - 9.0, 4.0), (0.5, 0.8, 1.0), 1500.0), ((0.0, front_y + 6.0, 3.0), (1.0, 0.3, 0.7), 800.0)):
    ld = bpy.data.lights.new("Lamp", "POINT")
    ld.energy = e
    ld.color = col
    ld.shadow_soft_size = 0.4
    lo_ = bpy.data.objects.new("Lamp", ld)
    lo_.location = loc
    scene.collection.objects.link(lo_)

# dim warm light inside each floor: seen only through the see-through glass
cx_, cy_ = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
for z in range(2, int(hi[2]), 3):
    ld = bpy.data.lights.new("Room", "POINT")
    ld.energy = 120.0
    ld.color = (1.0, 0.8, 0.6)
    lo_ = bpy.data.objects.new("Room", ld)
    lo_.location = (cx_, cy_, z + 0.6)
    scene.collection.objects.link(lo_)

# world: dim night sky gradient
world = bpy.data.worlds.new("Night")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.015, 0.02, 0.045, 1)
bg.inputs["Strength"].default_value = 1.0

# Cycles on the GPU (OptiX if available)
try:
    scene.render.engine = "CYCLES"
except TypeError as e:
    print("engine:", e)
prefs = bpy.context.preferences.addons["cycles"].preferences
for kind in ("OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = kind
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == kind
            scene.cycles.device = "GPU"
            break
    except TypeError:
        continue
print("cycles device:", scene.cycles.device, prefs.compute_device_type)
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.transparent_max_bounces = 32
scene.cycles.transmission_bounces = 12
scene.cycles.max_bounces = 16
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
except TypeError:
    pass
scene.view_settings.exposure = 0.6
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"


def shoot(name, loc, target, lens, res):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cam = bpy.data.objects.new(name, cd)
    scene.collection.objects.link(cam)
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = os.path.join(OUT, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print("RENDERED", scene.render.filepath)


cx = (lo[0] + hi[0]) / 2
shoot("opacity_fence_street", (cx + 1.0, fence_y - 2.6, 1.2), (cx, front_y, 4.0), 18, (1200, 750))
glass_view = ((cx - 2.5, front_y - 5.5, 5.2), (cx + 0.9, front_y, 6.6), 30, (960, 720))
shoot("_glass_after", *glass_view)

# "before": the same material with Opacity / Transmission unplugged (solid dark panes)
nt = building.active_material.node_tree
for l in [l for l in nt.links if l.to_socket.name in ("Alpha", "Transmission Weight")]:
    nt.links.remove(l)
shoot("_glass_before", *glass_view)


def side_by_side(a, b, out, gap=8):
    import numpy as np
    ia, ib = bpy.data.images.load(a), bpy.data.images.load(b)
    w, h = ia.size
    pa = np.array(ia.pixels[:], dtype=np.float32).reshape(h, w, 4)
    pb = np.array(ib.pixels[:], dtype=np.float32).reshape(h, w, 4)
    img = np.ones((h, 2 * w + gap, 4), np.float32)
    img[:, :w] = pa
    img[:, w + gap:] = pb
    o = bpy.data.images.new("before_after", 2 * w + gap, h, alpha=False)
    o.pixels.foreach_set(img.ravel())
    o.filepath_raw = out
    o.file_format = "PNG"
    o.save()
    for p in (a, b):
        os.remove(p)
    print("WROTE", out)


side_by_side(os.path.join(OUT, "_glass_before.png"), os.path.join(OUT, "_glass_after.png"), os.path.join(OUT, "opacity_glass_before_after.png"))
