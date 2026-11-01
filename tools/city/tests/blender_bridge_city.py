"""Headless test of the Pigment Bridge's city event queue (never touches a running Blender).

    blender -b --factory-startup --python tools/city/tests/blender_bridge_city.py

A mesh linked to a glb with link_city_mesh() gets the new geometry when a {"type": "mesh"} event
arrives (its material stays), and a {"type": "texture_folder"} event rebuilds the Pigment
material reading that folder, picking up a changed map. Exits 1 on failure.
"""
import json
import os
import shutil
import sys
import tempfile

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "tools", "blender_addon"))
from pigment_bridge import core  # noqa: E402

tmp = tempfile.mkdtemp(prefix="city_bridge_")
queue = os.path.join(tmp, "events.jsonl")
os.environ["CITY_BLENDER_EVENTS"] = queue
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def export_glb(make, path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    make()
    o = bpy.context.active_object
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False, export_materials="NONE")
    return len(o.data.vertices)


glb = os.path.join(tmp, "asset.glb")
n_cube = export_glb(lambda: bpy.ops.mesh.primitive_cube_add(size=2.0), glb)
n_sphere = export_glb(lambda: bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12), os.path.join(tmp, "sphere.glb"))



def imported_verts(path):
    """Vertex count of a glb as Blender imports it (glTF splits vertices per normal / UV)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    n = sum(len(o.data.vertices) for o in new if o.type == "MESH")
    for o in new:
        bpy.data.objects.remove(o)
    return n


bpy.ops.wm.read_factory_settings(use_empty=True)
n_cube = imported_verts(glb)
n_sphere = imported_verts(os.path.join(tmp, "sphere.glb"))
bpy.ops.import_scene.gltf(filepath=glb)
obj = next(o for o in bpy.data.objects if o.type == "MESH")
obj.name = "CityAsset"
core.link_city_mesh(obj, glb)

# a Pigment texture folder (the street lamp's maps, copied)
src = os.path.join(ROOT, "scenes", "town", "textures", "street_lamp")
folder = os.path.join(tmp, "street_lamp")
if os.path.isdir(src):
    shutil.copytree(src, folder)
    core.link_objects([obj], folder)
    mat = obj.material_slots[0].material
    check(mat is not None and mat.get("pigment_folder"), "Pigment material linked")
else:
    mat = None
    print("SKIP texture part: scenes/town/textures/street_lamp missing")

r = core.check_city_events()
check(r["events"] == 0, "first check only finds the end of the queue")
check(len(obj.data.vertices) == n_cube, f"starts as the cube ({len(obj.data.vertices)} verts)")

# the build writes a new glb over the old one and queues the events
shutil.copyfile(os.path.join(tmp, "sphere.glb"), glb)
events = [{"type": "mesh", "path": glb}]
with open(queue, "a", encoding="utf-8") as f:
    for e in events:
        f.write(json.dumps(e) + "\n")
r = core.check_city_events()
check(r["events"] == 1 and r["objects"] == ["CityAsset"], f"mesh event applied: {r}")
check(len(obj.data.vertices) == n_sphere, f"mesh replaced by the sphere ({len(obj.data.vertices)} verts, want {n_sphere})")
if mat is not None:
    check(obj.material_slots[0].material == mat, "material kept after the mesh swap")
    # texture event: rewrite the base colour (solid red) and queue the folder
    bc = next(f for f in os.listdir(folder) if f.endswith("_BaseColor.png"))
    img = bpy.data.images.new("red", 64, 64)
    img.pixels = [1.0, 0.0, 0.0, 1.0] * (64 * 64)
    img.filepath_raw = os.path.join(folder, bc)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    with open(queue, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "texture_folder", "path": folder}) + "\n")
    r = core.check_city_events()
    check(r["events"] == 1 and mat.name in r["materials"], f"texture event rebuilt the material: {r}")
    tex = next(n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image and n.image.filepath.endswith(bc))
    px = list(tex.pixels[:4])
    check(px[0] > 0.9 and px[1] < 0.1, f"new base colour visible in Blender ({[round(x, 2) for x in px]})")
r = core.check_city_events()
check(r["events"] == 0, "no event is applied twice")

shutil.rmtree(tmp, ignore_errors=True)
print("RESULT", "FAIL" if fails else "PASS", flush=True)
sys.exit(1 if fails else 0)
