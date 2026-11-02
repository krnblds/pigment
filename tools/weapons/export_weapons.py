"""Export the textured Waker kit for Godot (headless Blender 5.2).

    blender -b --factory-startup --python tools/weapons/export_weapons.py [-- ids...]

Needs assets/weapons/src/<id>.glb/.json (make_weapons.py) and the Pigment texture sets in
scenes/weapons/textures/<id>/ (weapons_textures.py). Writes game/assets/weapons/<id>.glb: the mesh
with its Pigment material (tools/blender_pigment.py, textures embedded, 512 px) and a "Muzzle" empty
at the barrel end. Contract: grip at the origin, barrel along -Z in Godot (game/scripts/weapons/weapon_models.gd).
"""
import json
import os
import sys
import tempfile

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "props"))
import blender_pigment as BP  # noqa: E402
from export_props import finish_material, resize_images  # noqa: E402

SRC = os.path.join(ROOT, "assets", "weapons", "src")
TEX = os.path.join(ROOT, "scenes", "weapons", "textures")
OUT = os.path.join(ROOT, "game", "assets", "weapons")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
IDS = ARGS or ["stun_baton", "taser", "service_pistol", "smg", "shotgun", "emp"]


def export_one(wid, tmp):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    meta = json.load(open(os.path.join(SRC, f"{wid}.json")))
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, f"{wid}.glb"))
    main = next(o for o in bpy.context.scene.objects if o.type == "MESH")
    main.name = wid
    folder = os.path.join(TEX, wid)
    mat = BP.apply_pigment_material(main, folder, wid, flake=False)
    finish_material(mat)
    resize_images(mat, 512, tmp)
    m = meta["muzzle_gltf"]
    mz = bpy.data.objects.new("Muzzle", None)
    bpy.context.scene.collection.objects.link(mz)
    mz.location = Vector((m[0], -m[2], m[1]))          # glTF -> Blender
    for o in bpy.context.scene.objects:
        o.select_set(o in (main, mz))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{wid}.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True)
    print(f"{wid}: {os.path.getsize(path) // 1024} KB -> {path}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for wid in IDS:
            export_one(wid, tmp)
