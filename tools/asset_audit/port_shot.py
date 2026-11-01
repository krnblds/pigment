"""In-world proof shots of the rebuilt port kit (headless Blender 5.2, Cycles).

    blender -b --factory-startup --python tools/asset_audit/port_shot.py -- OUTDIR [--root CHECKOUT] [--region x0,y0,x1,y1]
            [--shots top,yard,quay] [--samples 64] [--res 1600x900] [--sky dusk|day|night] [--world-dir DIR]

Builds only a region of the open world (tools/world/world_build.py with world.json), so it takes a
couple of minutes, and renders fixed cameras over the Minato port yard.  --root runs the same shots
from another checkout (e.g. the main one: the "before" pictures with the old procedural port kit);
--world-dir is where world.json and the (git-ignored) heightfield.f32 / masks_urban.npy are read
(the build may re-snap and rewrite the heightfield there), default ROOT/scenes/world.
"""
import json
import math
import os
import sys

import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(str(opt("--root", os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(ROOT, "tools", "world"))

SHOTS = {
    "top": {"ortho": 700, "loc": (1485, -1285, 600), "target": None},
    "yard": {"loc": (1452, -1338, 48), "target": (1540, -1268, 0), "lens": 24},
    "quay": {"loc": (1543, -1470, 30), "target": (1508, -1285, 22), "lens": 22},
    "stack": {"loc": (1533, -1315, 3.0), "target": (1524, -1288, 4.0), "lens": 22},
    "shed": {"loc": (1514, -1189, 6), "target": (1482, -1193, 5), "lens": 22},
}


def load_tool(name, extra=None):
    src = os.path.join(ROOT, "tools", name + ".py")
    ns = {"__name__": name, "__file__": src}
    ns.update(extra or {})
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns


def main():
    outdir = ARGS[0]
    os.makedirs(outdir, exist_ok=True)
    region = [float(v) for v in str(opt("--region", "1150,-1420,1820,-1150")).split(",")]
    town = load_tool("blender_town", {"TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT})
    wdir = os.path.abspath(str(opt("--world-dir", os.path.join(ROOT, "scenes", "world"))))
    world = json.load(open(os.path.join(wdir, "world.json"), encoding="utf-8"))
    import world_build
    import world_render
    built = world_build.build(world, wdir, ROOT, town, load_tool, region=region, log=print,
                              trees=True, lights=True)
    res = tuple(int(v) for v in str(opt("--res", "1600x900")).split("x"))
    world_render.setup(int(opt("--samples", 64)), res, cpu=bool(opt("--cpu")))
    sc = bpy.context.scene
    cam = bpy.data.objects.new("PortCam", bpy.data.cameras.new("PortCam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.clip_end = 6000
    for name in str(opt("--shots", "yard,quay,stack")).split(","):
        s = SHOTS[name]
        world_render.sky("day" if name == "top" else str(opt("--sky", "dusk")))
        if s.get("ortho"):
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = s["ortho"]
            cam.location = s["loc"]
            cam.rotation_euler = (0, 0, 0)
        else:
            cam.data.type = "PERSP"
            world_render.aim(cam, s["loc"], s["target"], s["lens"])
        sc.render.filepath = os.path.join(outdir, f"port_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("[port_shot]", sc.render.filepath, flush=True)


main()
