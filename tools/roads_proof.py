"""Proof renders for the open-world roads (headless Blender 5.2, Cycles).

    blender -b --factory-startup --python tools/roads_proof.py -- --out docs/agents/roads/after [--town old_blender_town.py]
        [--shots join,junction,night,top] [--samples 96] [--res 1280x720]

Builds the town with tools/blender_town.py (or --town, e.g. master's version
for the "before" images) through the layout driver's kit import, then renders:
    join      close-up at a run-to-run join (where the old 20 m street pieces met)
    junction  close-up where a run meets a junction mouth
    night     low street-level night shot
    top       orthographic top-down view of a junction and its runs (daylight)
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1]
    return default


# the layout driver's helpers, without running its main()
src = open(os.path.join(ROOT, "tools", "town_layout_driver.py"), encoding="utf-8").read()
src = src[: src.rindex("main()")]
D = {"__name__": "driver", "__file__": os.path.join(ROOT, "tools", "town_layout_driver.py")}
exec(compile(src, "town_layout_driver.py", "exec"), D)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    D["import_kit"]()
    D["apply_kit_materials"]()
    town_src = opt("--town", os.path.join(ROOT, "tools", "blender_town.py"))
    ns = {"__name__": "blender_town", "__file__": os.path.join(ROOT, "tools", "blender_town.py"), "TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT}
    exec(compile(open(town_src, encoding="utf-8").read(), town_src, "exec"), ns)
    info = ns["build"](root=ROOT)
    res = tuple(int(v) for v in opt("--res", "1280x720").split("x"))
    D["setup_render"](int(opt("--samples", "96")), res)
    out = opt("--out", os.path.join(ROOT, "docs", "agents", "roads", "after"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    want = opt("--shots", "join,junction,night,top").split(",")
    sc = bpy.context.scene
    cam = sc.camera
    runs = info["runs"]
    run = runs[1]                                      # J1 -> J2
    tile = 20.0
    n = max(1, int(round(run.length / tile)))
    sx = run.length / (n * tile)
    s_join = 2 * tile * sx                             # where old pieces 2 and 3 met

    def frame(s_cam, s_tgt, y_cam, y_tgt, h, lens, path=run):
        p, t = path.at(s_cam)
        q, u = path.at(s_tgt)
        nl, nq = Vector((-t.y, t.x)), Vector((-u.y, u.x))
        loc = (p.x + nl.x * y_cam, p.y + nl.y * y_cam, p.z + h)
        tgt = (q.x + nq.x * y_tgt, q.y + nq.y * y_tgt, q.z + 0.2)
        return loc, tgt, lens

    shots = {
        "join": frame(s_join - 6.5, s_join, -1.0, 1.5, 1.5, 28),
        "junction": frame(7.5, -1.0, 1.0, -0.5, 1.6, 26),
        "night": frame(s_join + 30.0, s_join - 6.0, -2.4, 0.5, 1.15, 22),
    }
    world = sc.world
    for name in sorted(want, key=lambda n: n != "night"):
        if name == "top":
            continue
        if name not in shots:
            continue
        night = name == "night"
        if not night:
            D["daylight"]()
        loc, tgt, lens = shots[name]
        cam.data.type = "PERSP"
        D["aim"](cam, loc, tgt, lens)
        sc.render.filepath = f"{out}_{name}.png"
        bpy.ops.render.render(write_still=True)
        print("rendered", sc.render.filepath)
    if "top" in want:
        D["daylight"]()
        j = info["junctions"]["J1"]["pos"]
        p, _ = run.at(30.0)
        cx, cy = (j[0] + p.x) / 2, (j[1] + p.y) / 2
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = 70.0
        cam.location = (cx, cy, j[2] + 120)
        cam.rotation_euler = (0, 0, 0)
        sc.render.resolution_x, sc.render.resolution_y = res[0], res[0]
        sc.render.filepath = f"{out}_top.png"
        bpy.ops.render.render(write_still=True)
        print("rendered", sc.render.filepath)


main()
