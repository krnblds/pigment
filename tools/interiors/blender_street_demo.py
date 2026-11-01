"""Cycles street shot of the interior-mapped windows (headless Blender 5.2).

    blender -b --factory-startup --python tools/interiors/blender_street_demo.py -- <out.png> [samples] [--plain]

A short night street of kit buildings (building_b, building_a, building_c, building_a) with their
Pigment variant textures and add_interiors() on every glass pane; --plain renders the same view
with the plain Pigment glass for a before / after. Kit textures come from
scenes/town/textures/<asset>__<variant>/ in this checkout, else $PIGMENT_TOWN_TEX, else the main
checkout (worktrees share it).
"""
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)
from blender_pigment import apply_pigment_material  # noqa: E402
import blender_interiors  # noqa: E402


def tex_root():
    for c in (os.path.join(ROOT, "scenes", "town", "textures"), os.environ.get("PIGMENT_TOWN_TEX", ""),
              os.path.abspath(os.path.join(ROOT, "..", "..", "..", "scenes", "town", "textures"))):
        if c and os.path.isdir(os.path.join(c, "building_a__soba")):
            return c
    raise SystemExit("no kit textures (scenes/town/textures/building_a__soba): run tools/town_textures.py or set PIGMENT_TOWN_TEX")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[0] if argv else os.path.join(ROOT, "docs", "agents", "interiors", "blender_street.png")
    samples = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 128
    plain = "--plain" in argv
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    tr = tex_root()
    # buildings along +x, fronts facing -y (the camera side)
    row = [("building_b", "noodle_row", 8.4), ("building_a", "capsules", 4.4), ("building_c", "hoshikawa_hq", 7.4), ("building_a", "dream_den", 4.4)]
    x = -14.0
    for k, (asset, variant, half) in enumerate(row):
        x += half
        bpy.ops.import_scene.gltf(filepath=os.path.join(ROOT, "assets", "town", f"{asset}.glb"))
        ob = [o for o in bpy.context.selected_objects if o.type == "MESH"][0]
        ob.name = f"{asset}_{k}"
        ob.location = (x, 0.0, 0.0)
        folder = os.path.join(tr, f"{asset}__{variant}")
        mat = apply_pigment_material(ob, folder, asset)
        mat = mat.copy()
        mat.name = f"Pigment_{asset}__{variant}"
        ob.data.materials.clear()
        ob.data.materials.append(mat)
        if not plain:
            blender_interiors.add_interiors(mat, asset, folder)
        x += half + 0.4
    # wet street, a few lamps, night sky
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0, -14, 0))
    ground = bpy.context.active_object
    gm = bpy.data.materials.new("wet")
    gm.use_nodes = True
    b = gm.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.02, 0.02, 0.022, 1)
    b.inputs["Roughness"].default_value = 0.12
    ground.data.materials.append(gm)
    for i, lx in enumerate((-12, 2, 16)):
        ld = bpy.data.lights.new(f"lamp{i}", "POINT")
        ld.energy = 900
        ld.color = (1.0, 0.75, 0.5) if i != 1 else (0.6, 0.8, 1.0)
        ld.shadow_soft_size = 0.3
        lo = bpy.data.objects.new(f"lamp{i}", ld)
        lo.location = (lx, -9.0, 6.0)
        sc.collection.objects.link(lo)
    sc.world = bpy.data.worlds.new("night")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.02, 0.025, 0.05, 1)
    bg.inputs["Strength"].default_value = 0.6
    cd = bpy.data.cameras.new("cam")
    cd.lens = 24
    cam = bpy.data.objects.new("cam", cd)
    cam.location = (-14.0, -27.0, 1.7)
    sc.collection.objects.link(cam)
    target = bpy.data.objects.new("target", None)
    target.location = (5.0, 0.0, 8.0)
    sc.collection.objects.link(target)
    c = cam.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    sc.camera = cam
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dev
            prefs.get_devices()
            for d in prefs.devices:
                d.use = d.type == dev
            sc.cycles.device = "GPU"
            break
        except Exception:
            continue
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 1600, 900
    sc.view_settings.view_transform = "AgX"
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("[street] wrote", out)


main()
