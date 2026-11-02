"""Line-up render of the built citizens (headless Blender, EEVEE): a quick look at the whole crowd.

    blender -b --factory-startup --python tools/npc/preview_citizens.py -- [--src .npccache/citizens]
            [--out docs/agents/npc/lineup.png] [--only id,id] [--lod 0|1|2] [--cols 12] [--res 1800]
"""
import bpy
import glob
import math
import os
import sys
from mathutils import Matrix

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def arg(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d


SRC = arg("--src", os.path.join(ROOT, ".npccache", "citizens"))
OUT = arg("--out", os.path.join(ROOT, ".npccache", "lineup.png"))
ONLY = set(filter(None, (arg("--only", "") or "").split(",")))
LOD = int(arg("--lod", "0"))
COLS = int(arg("--cols", "12"))
RES = int(arg("--res", "1800"))
YAW = float(arg("--yaw", "0"))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def material(cid):
    m = bpy.data.materials.new(cid)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    a = nt.nodes.new("ShaderNodeTexImage")
    a.image = bpy.data.images.load(os.path.join(SRC, cid + "_albedo.png"))
    nt.links.new(a.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(a.outputs["Alpha"], bsdf.inputs["Alpha"])
    k = nt.nodes.new("ShaderNodeTexImage")
    k.image = bpy.data.images.load(os.path.join(SRC, cid + "_mask.png"))
    k.image.colorspace_settings.name = "Non-Color"
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(k.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Roughness"])
    em = nt.nodes.new("ShaderNodeMath")
    em.operation = "GREATER_THAN"
    em.inputs[1].default_value = 0.75
    nt.links.new(sep.outputs["Blue"], em.inputs[0])
    mul = nt.nodes.new("ShaderNodeMixRGB")
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    nt.links.new(a.outputs["Color"], mul.inputs[1])
    nt.links.new(em.outputs[0], mul.inputs[2])
    nt.links.new(mul.outputs[0], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 4.0
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(os.path.join(SRC, cid + "_normal.png"))
    n.image.colorspace_settings.name = "Non-Color"
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(n.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    try:
        m.surface_render_method = "DITHERED"
    except Exception:
        pass
    return m


ids = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(SRC, "*.glb")))
ids = [i for i in ids if not ONLY or i in ONLY]
rows_total = (len(ids) + COLS - 1) // COLS
for k, cid in enumerate(ids):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, cid + ".glb"))
    new = [o for o in bpy.data.objects if o not in before]
    m = material(cid)
    roots = [o for o in new if o.parent is None]
    x = (k % COLS) * 0.9
    y = 0.0
    zrow = (rows_total - 1 - k // COLS) * 2.0
    for o in new:
        if o.type == "MESH":
            keep = o.name.startswith("LOD%d" % LOD)
            o.hide_render = not keep
            o.data.materials.clear()
            o.data.materials.append(m)
    for r in roots:
        r.matrix_world = Matrix.Rotation(math.radians(YAW), 4, "Z") @ r.matrix_world
        r.location.x += x
        r.location.y += y
        r.location.z += zrow
rows = (len(ids) + COLS - 1) // COLS
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
w = (min(COLS, len(ids)) - 1) * 0.9
cam.data.type = "ORTHO"
H = rows * 2.0
cam.data.ortho_scale = max(w + 1.2, H)
cam.location = (w / 2, -12, H / 2 - 0.1)
cam.rotation_euler = (math.radians(90), 0, 0)
sc.camera = cam
for i, (rot, e, col) in enumerate((((60, 0, 30), 3.0, (1, 0.9, 0.8)), ((70, 0, -120), 2.0, (0.4, 0.8, 1.0)), ((120, 0, 180), 1.5, (1.0, 0.3, 0.7)))):
    L = bpy.data.objects.new("sun%d" % i, bpy.data.lights.new("sun%d" % i, "SUN"))
    L.data.energy = e
    L.data.color = col
    L.rotation_euler = [math.radians(a) for a in rot]
    sc.collection.objects.link(L)
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.022, 0.03, 1)
sc.world = world
try:
    sc.render.engine = "BLENDER_EEVEE"
except TypeError:
    sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.render.resolution_x = RES
sc.render.resolution_y = int(RES * min(1.0, H / max(w + 1.2, 1)))
sc.render.film_transparent = False
sc.view_settings.view_transform = "AgX"
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("lineup:", OUT, len(ids), "citizens")
