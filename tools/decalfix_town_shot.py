"""Cycles street-level shots of the hillside town with the current kit and texture variants
(docs/agents/decalfix proof). Headless Blender only:

    blender -b --factory-startup --python tools/decalfix_town_shot.py -- OUT_DIR [samples] [WxH] [shot,...]

Builds the town like tools/town_layout_driver.py (kit import, Pigment maps, layout) and
renders the driver's street-level cameras (yfork, tjunction, crossroads, stairs) to OUT_DIR.
Needs the textures: python tools/town_textures.py; python tools/road_textures.py --run.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def main():
    out = os.path.abspath(ARGS[0]) if ARGS else os.path.join(ROOT, "docs", "agents", "decalfix")
    samples = int(ARGS[1]) if len(ARGS) > 1 else 96
    res = tuple(int(v) for v in (ARGS[2] if len(ARGS) > 2 else "1600x900").split("x"))
    want = (ARGS[3] if len(ARGS) > 3 else "yfork,tjunction").split(",")
    src = os.path.join(ROOT, "tools", "town_layout_driver.py")
    D = {"__name__": "town_layout_driver", "__file__": src}
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), D)
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    D["import_kit"]()
    D["apply_kit_materials"]()
    town = D["load_tool"]("blender_town", {"TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT})
    info = town["build"](root=ROOT)
    D["setup_render"](samples, res)
    cam = bpy.context.scene.camera
    os.makedirs(out, exist_ok=True)
    for name, (loc, tgt, lens) in D["shots"](info).items():
        if name not in want:
            continue
        D["aim"](cam, loc, tgt, lens)
        bpy.context.scene.render.filepath = os.path.join(out, f"town_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", name)


main()
