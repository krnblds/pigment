"""Open-world generator driver (Blender 5.2, headless).

    blender -b --factory-startup --python tools/world/world_driver.py -- [options]

Stages (default: gen,build,verify):
    gen      config + seed -> scenes/world/world.json + heightfield.f32 (data only)
    build    world.json -> Blender scene (terrain chunks, roads, junctions, bridges,
             buildings, towers, port, props, water, sky)
    verify   terrain vs roads / bridges, floating props, grades, overlaps
    render   proof shots to docs/agents/world/ (--shots aerial,bridge,mountain,avenue)
    save     scenes/world/world_preview.blend (the --region part of the world)
    export   Godot: meshes as glb + world.json + town_layout.json in --export-dir

Options:
    --config tools/world/world_config.json   --seed N   --out scenes/world
    --stages gen,build,...   --region x0,y0,x1,y1 (build only this box; "preview" = config)
    --samples N   --res WxH   --shots a,b   --day (debug light)   --no-trees
"""
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


def load_tool(name, extra=None):
    src = os.path.join(ROOT, "tools", name + ".py")
    ns = {"__name__": name, "__file__": src}
    ns.update(extra or {})
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns


def log(*a):
    print("[world]", *a, flush=True)


def main():
    t0 = time.time()
    cfg_path = str(opt("--config", os.path.join(HERE, "world_config.json")))
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    if opt("--seed"):
        cfg["seed"] = int(opt("--seed"))
    cfg["_root"] = ROOT
    out = os.path.join(ROOT, str(opt("--out", os.path.join("scenes", "world"))))
    stages = str(opt("--stages", "gen,build,verify")).split(",")
    town = load_tool("blender_town", {"TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT})
    world = None
    if "gen" in stages:
        import world_gen
        world, net, hf = world_gen.generate(cfg, town, out, log)
    if world is None:
        world = json.load(open(os.path.join(out, "world.json"), encoding="utf-8"))
    region = opt("--region")
    if region == "preview":
        region = cfg["preview_region"]
    elif region:
        region = [float(v) for v in str(region).split(",")]
    built = None
    if any(s in stages for s in ("build", "verify", "render", "save", "export")):
        import world_build
        built = world_build.build(world, out, ROOT, town, load_tool, region=region, log=log,
                                  trees=not opt("--no-trees"), lights=not opt("--no-lights"))
    if "verify" in stages:
        import world_verify
        world_verify.verify(world, built, out, log)
    if "render" in stages:
        import world_render
        world_render.render(world, built, ROOT, opt, log)
    if "save" in stages:
        path = os.path.join(out, "world_preview.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
        log("saved", path)
    if "export" in stages:
        import world_export
        world_export.export(world, built, out, ROOT, str(opt("--export-dir", os.path.join(ROOT, "game", "assets", "world"))), log)
    log(f"done in {time.time() - t0:.0f} s")


main()
