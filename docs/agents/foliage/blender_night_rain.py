"""Headless Blender: building_a and a street segment, both textured in
Pigment with their foliage (moss, weeds, ivy, crack grass, fallen leaves),
at night in the rain. Cycles, OptiX when available.

    blender -b --factory-startup --python docs/agents/foliage/blender_night_rain.py -- \
        [export root (default target/foliage)] [out.png] [samples]

Inputs come from `python tools/foliage_demo.py --run` (send_to_blender
folders: maps + mesh + <name>_foliage.glb + material.json). Foliage goes
through the Pigment Bridge add-on's foliage material (alpha clip, two-sided,
Translucency -> Translucent BSDF), via tools/blender_pigment.py.
"""
import json
import math
import os
import random
import sys

import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from blender_pigment import apply_pigment_material, import_pigment_foliage  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
src = os.path.abspath(args[0]) if args else os.path.join(ROOT, "target", "foliage")
out = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(ROOT, "docs", "agents", "foliage", "cycles_night_rain.png")
samples = int(args[2]) if len(args) > 2 else 160

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def emission_of(folder, name):
    try:
        return float(json.load(open(os.path.join(folder, "material.json")))["materials"][name].get("emissive_scale", 1.0)) * 1.6
    except Exception:
        return 4.0


def import_asset(name, loc=(0, 0, 0), rot_z=0.0):
    folder = os.path.join(src, name)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(folder, f"{name}.glb"))
    objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    for o in objs:
        apply_pigment_material(o, folder, name, emission_strength=emission_of(folder, name))
    fol = import_pigment_foliage(folder)
    print(f"{name}: {len(objs)} mesh object(s), {len(fol)} foliage object(s)")
    root = bpy.data.objects.new(f"{name}_root", None)
    scene.collection.objects.link(root)
    for o in objs + fol:
        if o.parent is None:
            o.parent = root
    root.location = loc
    root.rotation_euler = (0, 0, rot_z)
    return objs, fol


# building_a: glTF +X (its east wall, with the ivy) stays +X in Blender
import_asset("building_a")
# the street along the east wall: segment length along Blender Y, sidewalk against the wall
import_asset("street_segment", loc=(4.39 + 7.0, 0.0, 0.0), rot_z=math.radians(90))
import_asset("street_segment", loc=(4.39 + 7.0, 20.0, 0.0), rot_z=math.radians(90))
import_asset("street_segment", loc=(4.39 + 7.0, -20.0, 0.0), rot_z=math.radians(90))

# wet ground beyond the street
bpy.ops.mesh.primitive_plane_add(size=300, location=(0, 0, -0.02))
ground = bpy.context.object
m = bpy.data.materials.new("WetGround")
m.use_nodes = True
b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
b.inputs["Base Color"].default_value = (0.01, 0.01, 0.012, 1)
b.inputs["Roughness"].default_value = 0.12
ground.data.materials.append(m)

# ---- night sky (the game's night_rain HDR when present) ----
world = bpy.data.worlds.new("Night")
scene.world = world
world.use_nodes = True
nt = world.node_tree
bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
hdr = os.path.join(ROOT, "assets", "sky", "night_rain_2k.hdr")
if os.path.isfile(hdr):
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(hdr)
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.45
else:
    bg.inputs["Color"].default_value = (0.004, 0.006, 0.014, 1)


def light(kind, loc, energy, color, size=1.0, target=None, spot=None):
    d = bpy.data.lights.new(kind + "_light", kind)
    d.energy = energy
    d.color = color
    if kind == "AREA":
        d.size = size
    if kind == "SPOT" and spot:
        d.spot_size = math.radians(spot)
        d.spot_blend = 0.6
    o = bpy.data.objects.new(d.name, d)
    o.location = loc
    if target is not None:
        o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(o)
    return o


# a sodium street lamp over the far sidewalk, neon spill from across the street, a cold rim
light("SPOT", (15.5, -3.0, 6.5), 3500, (1.0, 0.62, 0.32), target=(6.0, -1.0, 0.0), spot=95)
light("SPOT", (15.5, 9.0, 6.5), 2500, (1.0, 0.62, 0.32), target=(6.0, 8.0, 0.0), spot=95)
light("AREA", (20.0, 2.0, 3.5), 1600, (1.0, 0.18, 0.55), size=4, target=(4.4, 2.0, 3.0))
light("AREA", (19.0, -8.0, 5.0), 1300, (0.15, 0.75, 1.0), size=4, target=(4.4, -2.0, 4.0))
light("AREA", (-6.0, 14.0, 22.0), 1800, (0.45, 0.55, 1.0), size=8, target=(0.0, 0.0, 20.0))
# back light through the ivy and grass (shows the translucency)
light("POINT", (5.2, 1.0, 1.2), 120, (1.0, 0.7, 0.4))

# ---- rain: thin glossy streaks in front of the camera ----
random.seed(4)
verts, faces = [], []
for i in range(26000):
    c = Vector((random.uniform(6.0, 17.5), random.uniform(-14.0, 12.0), random.uniform(0.0, 14.0)))
    L = random.uniform(0.12, 0.3)
    w = 0.0035
    d = Vector((0.06, 0.02, -1.0)).normalized() * L
    side = Vector((0.0, w, 0.0))
    k = len(verts)
    verts += [c - side, c + side, c + side + d, c - side + d]
    faces.append((k, k + 1, k + 2, k + 3))
rm = bpy.data.meshes.new("Rain")
rm.from_pydata([tuple(v) for v in verts], [], faces)
rain = bpy.data.objects.new("Rain", rm)
scene.collection.objects.link(rain)
rmat = bpy.data.materials.new("Rain")
rmat.use_nodes = True
rb = next(n for n in rmat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
rb.inputs["Base Color"].default_value = (0.8, 0.85, 0.9, 1)
rb.inputs["Roughness"].default_value = 0.05
rb.inputs["Alpha"].default_value = 0.22
tw = rb.inputs.get("Transmission Weight") or rb.inputs.get("Transmission")
if tw is not None:
    tw.default_value = 1.0
rain.data.materials.append(rmat)
rain.visible_shadow = False

# ---- camera: on the far sidewalk, looking back at the ivy wall ----
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 22
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = Vector((16.5, -10.5, 1.65))
target = Vector((4.4, 0.5, 4.6))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

scene.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = dev.type == "OPTIX"
    scene.cycles.device = "GPU"
except Exception as e:
    print("GPU setup failed:", e)
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.cycles.transparent_max_bounces = 32
scene.render.resolution_x = 1500
scene.render.resolution_y = 1000
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 0.35
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("rendered", out)
