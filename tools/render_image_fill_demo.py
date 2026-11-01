"""Headless Blender render of the image-fill demo: the street segment and
building_a retextured in Pigment with triplanar tiles
(scenes/town/image_fill_demo/*.jsonl), wired up with tools/blender_pigment.py.

    pigment-mcp --script scenes/town/image_fill_demo/street_segment_tiles.jsonl
    pigment-mcp --script scenes/town/image_fill_demo/building_a_tiles.jsonl
    blender -b --factory-startup --python tools/render_image_fill_demo.py -- [out.png] [samples]
"""
import math
import os
import sys

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from blender_pigment import apply_pigment_material  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else os.path.join(ROOT, "docs", "agents", "image-fills", "blender_tiles.png")
SAMPLES = int(argv[1]) if len(argv) > 1 else 128

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def import_asset(name, location, yaw=0.0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ROOT, "assets", "town", f"{name}.glb"))
    objs = [o for o in bpy.data.objects if o not in before]
    roots = [o for o in objs if o.parent is None]
    for r in roots:
        r.location = location
        r.rotation_mode = "XYZ"  # the glTF importer uses quaternions
        r.rotation_euler[2] += math.radians(yaw)
    folder = os.path.join(ROOT, "scenes", "town", "textures", f"{name}_tiles")
    for o in objs:
        if o.type == "MESH":
            apply_pigment_material(o, folder, name)
    return objs


import_asset("street_segment", (0.0, 0.0, 0.0))
# glTF +Z is Blender -Y: the far sidewalk ends at Blender y = -7. The
# building's windowed front faces glTF +Z, so turn it to face the street.
import_asset("building_a", (-4.2, -12.3, 0.0), 180.0)
import_asset("building_a", (4.2, -12.3, 0.0), 180.0)

# lighting: dusk sky, a low warm key and a cool fill
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (0.05, 0.07, 0.12, 1.0)
bg.inputs[1].default_value = 1.0

sun = bpy.data.lights.new("Sun", "SUN")
sun.energy = 3.0
sun.color = (1.0, 0.82, 0.65)
sun.angle = math.radians(2.0)
so = bpy.data.objects.new("Sun", sun)
so.rotation_euler = (math.radians(68), 0.0, math.radians(160))
scene.collection.objects.link(so)

fill = bpy.data.lights.new("Fill", "AREA")
fill.energy = 4000
fill.size = 10
fill.color = (0.55, 0.75, 1.0)
fo = bpy.data.objects.new("Fill", fill)
fo.location = (6, 10, 8)
fo.rotation_euler = (math.radians(-55), 0, math.radians(150))
scene.collection.objects.link(fo)

cam = bpy.data.cameras.new("Cam")
cam.lens = 18
co = bpy.data.objects.new("Cam", cam)
scene.collection.objects.link(co)
co.location = (9.0, 6.5, 3.2)
target = (-3.0, -12.0, 6.0)
d = [target[i] - co.location[i] for i in range(3)]
co.rotation_euler = (math.atan2(math.hypot(d[0], d[1]), -d[2]), 0.0, math.atan2(d[1], d[0]) - math.pi / 2)
scene.camera = co

r = scene.render
try:
    r.engine = "CYCLES"
except TypeError as e:
    print("engine:", e)
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = True
    scene.cycles.device = "GPU"
except Exception as e:  # CPU fallback
    print("GPU setup failed:", e)
r.resolution_x, r.resolution_y = 1280, 720
r.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 0.3
r.filepath = OUT
bpy.ops.render.render(write_still=True)
print("rendered", OUT)
