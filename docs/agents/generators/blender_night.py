"""Headless Blender: one Pigment-textured building at night on a wet street.

    blender -b --factory-startup --python docs/agents/generators/blender_night.py -- \
        <mesh.glb> <texture folder> <map name> <out.png> [emission strength]

Cycles (OptiX when available). The building's front (glTF +Z) faces the camera.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from blender_pigment import apply_pigment_material  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
glb, tex, name, out = args[:4]
emission = float(args[4]) if len(args) > 4 else 6.0

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---- the building ----
bpy.ops.import_scene.gltf(filepath=os.path.abspath(glb))
meshes = [o for o in scene.objects if o.type == "MESH"]
for o in meshes:
    apply_pigment_material(o, os.path.abspath(tex), name, emission_strength=emission)
lo = Vector((min((o.matrix_world @ Vector(c)).x for o in meshes for c in o.bound_box),
             min((o.matrix_world @ Vector(c)).y for o in meshes for c in o.bound_box),
             min((o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box)))
hi = Vector((max((o.matrix_world @ Vector(c)).x for o in meshes for c in o.bound_box),
             max((o.matrix_world @ Vector(c)).y for o in meshes for c in o.bound_box),
             max((o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box)))
height = hi.z - lo.z

# ---- wet street: dark, glossy, slightly bumpy so reflections smear ----
bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, lo.z - 0.01))
street = bpy.context.object
m = bpy.data.materials.new("WetStreet")
m.use_nodes = True
nt = m.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["Base Color"].default_value = (0.012, 0.012, 0.014, 1)
bsdf.inputs["Roughness"].default_value = 0.08
noise = nt.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 2.5
ramp = nt.nodes.new("ShaderNodeMapRange")
ramp.inputs["From Min"].default_value = 0.45
ramp.inputs["From Max"].default_value = 0.6
ramp.inputs["To Min"].default_value = 0.05
ramp.inputs["To Max"].default_value = 0.45
nt.links.new(noise.outputs["Fac"], ramp.inputs["Value"])
nt.links.new(ramp.outputs["Result"], bsdf.inputs["Roughness"])
street.data.materials.append(m)

# ---- night world + lights ----
world = bpy.data.worlds.new("Night")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.004, 0.006, 0.014, 1)
bg.inputs["Strength"].default_value = 1.0


def light(kind, loc, energy, color, size=1.0, rot=None):
    d = bpy.data.lights.new(kind + "_light", kind)
    d.energy = energy
    d.color = color
    if kind == "AREA":
        d.size = size
    o = bpy.data.objects.new(d.name, d)
    o.location = loc
    if rot:
        o.rotation_euler = rot
    scene.collection.objects.link(o)
    return o


light("SUN", (0, 0, 50), 0.08, (0.55, 0.65, 1.0), rot=(math.radians(50), 0, math.radians(30)))
# neon spill from signs across the street, a street lamp, and a cold rim
light("AREA", (-7, -9, 4), 900, (1.0, 0.2, 0.6), size=3, rot=(math.radians(80), 0, math.radians(-35)))
light("AREA", (8, -8, 6), 700, (0.2, 0.8, 1.0), size=3, rot=(math.radians(75), 0, math.radians(40)))
light("POINT", (2.5, -7.5, 5.5), 600, (1.0, 0.75, 0.45))
light("AREA", (6, 10, height * 0.8), 1500, (0.4, 0.5, 1.0), size=6, rot=(math.radians(-60), 0, math.radians(150)))

# ---- camera: low, looking up the front facade ----
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 24
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
center = (lo + hi) / 2
cam.location = Vector((center.x + 7.0, lo.y - 16.0, lo.z + 2.2))
target = Vector((center.x, center.y, lo.z + height * 0.42))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

# ---- render ----
scene.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = dev.type == "OPTIX"
    scene.cycles.device = "GPU"
except Exception as e:  # CPU fallback
    print("GPU setup failed:", e)
scene.cycles.samples = 128
scene.cycles.use_denoising = True
scene.render.resolution_x = 900
scene.render.resolution_y = 1200
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 0.6
scene.render.filepath = os.path.abspath(out)
bpy.ops.render.render(write_still=True)
print("rendered", out)
