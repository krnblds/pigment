"""Headless test: Pigment exports with several texture sets in Blender.

Prerequisites (from the repo root):
  cargo build --release
  target/release/pigment-mcp --script scenes/materials/lantern.jsonl       # sets by material
  target/release/pigment-mcp --script scenes/materials/room_corner.jsonl   # sets by UDIM tile

Run (from the repo root):
  blender -b --factory-startup --python tools/test_blender_texture_sets.py

Checks that the Pigment Bridge core (tools/blender_addon/pigment_bridge):
  1. imports the whole mesh send_to_blender wrote, with a material per texture
     set on exactly the faces each set paints (by glTF material, by UDIM tile);
  2. reads every set's maps from the sidecar (they all exist; glass gets its
     opacity / transmission maps, the flame its emissive scale);
  3. re-linking a mesh that already carries the set materials keeps them, and
     linking the original multi-material .glb (assets/) matches by slot name.
"""
import os
import sys

import bpy

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "blender_addon"))
from pigment_bridge import core  # noqa: E402

TEX = os.path.join(REPO, "scenes", "materials", "textures")
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def faces_per_material(obj):
    out = {}
    for p in obj.data.polygons:
        m = obj.data.materials[p.material_index]
        out[m.name] = out.get(m.name, 0) + 1
    return out


bpy.ops.wm.read_factory_settings(use_empty=True)

# --- sets by material: the lantern (Metal, Glass, Wax, Flame) ---
spec = core.discover(os.path.join(TEX, "lantern"))
check(spec["texture_sets"] == ["lantern_Metal", "lantern_Glass", "lantern_Wax", "lantern_Flame"], f"lantern sets {spec['texture_sets']}")
objs = core.import_mesh(spec)
check(len(objs) == 1, "one object")
lantern = objs[0]
got = faces_per_material(lantern)
# the source model: one material per part, a set per material
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(REPO, "assets", "lantern.glb"))
src = next(o for o in bpy.data.objects if o not in before)
want = {f"Pigment_lantern_{k.split('.')[0]}": v for k, v in faces_per_material(src).items()}
check(got == want, f"faces per set {got} == source faces per material {want}")
for s in spec["texture_sets"]:
    sub = core.discover(spec["folder"], s)
    check(all(os.path.isfile(m["path"]) for m in sub["maps"]) and sub["maps"], f"{s}: every map file exists")
glass = bpy.data.materials["Pigment_lantern_Glass"]
labels = {n.label for n in glass.node_tree.nodes if n.type == "TEX_IMAGE"}
check({"Pigment Opacity", "Pigment Transmission"} <= labels, f"glass has opacity + transmission maps {sorted(labels)}")
check(bpy.data.materials["Pigment_lantern_Flame"].get("pigment_emissive_scale", 0) > 1.0, "flame keeps its emissive scale")

# linking the original .glb matches its slots by name
core.link_objects([src], spec["folder"])
check(faces_per_material(src) == want, "linking the source .glb assigns each slot its set")
# linking again is stable
core.link_objects([lantern], spec["folder"])
check(faces_per_material(lantern) == want, "re-linking keeps every face's set")

# --- sets by UDIM tile: the room corner (floor 1001, walls 1002, trim 1003) ---
spec = core.discover(os.path.join(TEX, "room_corner"))
room = core.import_mesh(spec)[0]
uv = room.data.uv_layers[0].data
wrong = 0
for p in room.data.polygons:
    tile = core._udim_tile(room.data, p, uv)
    if room.data.materials[p.material_index].name != f"Pigment_room_corner_tile_{tile}":
        wrong += 1
check(wrong == 0, f"every room face has its UDIM tile's set ({wrong} wrong)")
check(len(room.data.materials) == 3, "three sets on the room")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
