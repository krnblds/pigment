"""Bridges only, fast (Blender 5.2 headless): design option clay sheets and quick previews.

    blender -b --factory-startup --python tools/world/bridge_options.py -- --sheet
        every option of every landmark bridge in clay -> docs/agents/bridges/design_options.png
    blender -b --factory-startup --python tools/world/bridge_options.py -- --preview [--only port] [--samples 32]
        the chosen designs with their materials, on the terrain, no city -> .citycache/bridges/preview_*.png
    ... --stats     triangle counts per bridge object (no render)

The full world (city, lights, roads) is world_driver.py; this builds the terrain chunks near each
bridge, the road runs over it and the bridge, which takes seconds.
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

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


def clay(name, col, rough=0.6):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    return m


def main():
    import world_build as WB
    import world_meshes as WM
    import world_render as WR
    import bridge_cams as CAMS
    import bridge_designs as BD
    import bridge_kit as BK
    out = os.path.join(ROOT, "scenes", "world")
    world = json.load(open(os.path.join(out, "world.json"), encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    town = load_tool("blender_town", {"TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT})
    R = load_tool("town_roads")
    RT = R["RoadTextures"](ROOT)
    M = {
        "concrete": town["material"]("TownConcrete", town["concrete_nodes"]),
        "metal": R["metal_material"](),
        "asphalt": town["material"]("TownAsphaltFallback", town["flat_nodes"]((0.03, 0.03, 0.032), 0.6)),
        "curb": town["material"]("TownCurbFallback", town["flat_nodes"]((0.2, 0.2, 0.19), 0.85)),
        "walk": town["material"]("TownWalkFallback", town["flat_nodes"]((0.11, 0.11, 0.11), 0.8)),
    }
    road_mats = list(R["road_materials"](RT, {"asphalt": M["asphalt"], "curb": M["curb"], "walk": M["walk"], "concrete": M["concrete"]})) + [M["metal"]]
    T = world["terrain"]
    n = T["n"]
    H = np.fromfile(os.path.join(out, T["heightfield"]), dtype="<f4").reshape(n, n)
    w_, H_, t_ = CAMS.load(out)
    cams = {c["name"]: c for c in CAMS.cams(w_, H_, t_)}
    classes = world["road_classes"]
    roads = {r["id"]: r for r in world["roads"]}
    only = set(str(opt("--only", "")).split(",")) - {""}
    sheet = bool(opt("--sheet"))
    stats = bool(opt("--stats"))
    BMAT = BK.materials(ROOT)
    tmat = WM.terrain_material(ROOT)
    root_c = bpy.data.collections.new("Bridges")
    bpy.context.scene.collection.children.link(root_c)
    # water
    wme = bpy.data.meshes.new("Water")
    S = 60000.0
    wme.from_pydata([(-S, -S, 0), (S, -S, 0), (S, S, 0), (-S, S, 0)], [], [(0, 1, 2, 3)])
    wme.materials.append(WM.water_material())
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Water", wme))

    def ground(x, y, _o=T["origin"], _c=T["cell_m"]):
        fx, fy = (x - _o[0]) / _c, (y - _o[1]) / _c
        i0, j0 = int(math.floor(fy)), int(math.floor(fx))
        if not (0 <= i0 < n - 1 and 0 <= j0 < n - 1):
            return -26.0
        u, v = fx - j0, fy - i0
        return float(H[i0, j0] * (1 - u) * (1 - v) + H[i0, j0 + 1] * u * (1 - v) + H[i0 + 1, j0] * (1 - u) * v + H[i0 + 1, j0 + 1] * u * v)

    terrain_done = set()

    def terrain_near(x0, y0, x1, y1):
        per = T["chunk_cells"]
        for ch in T["chunks"]:
            ox, oy = ch["origin"]
            if ox > x1 or oy > y1 or ox + T["chunk_m"] < x0 or oy + T["chunk_m"] < y0 or ch["id"] in terrain_done:
                continue
            terrain_done.add(ch["id"])
            me = WM.terrain_chunk("Terrain_" + ch["id"], H, T["origin"][0], T["cell_m"], ch["ix"] * per, ch["iy"] * per, per, 2, None)
            me.materials.append(tmat)
            bpy.context.scene.collection.objects.link(bpy.data.objects.new("Terrain_" + ch["id"], me))

    sites = []
    for br in world["bridges"]:
        d = BD.design_of(br)
        if d == "small" or (only and d not in only):
            continue
        sites.append((d, br))
    built = {}
    results = {}
    for d, br in sites:
        r = roads[f"r{br['edge']}"]
        path = WB.path_from(town, r["points"])
        P = np.array(r["points"])
        terrain_near(P[:, 0].min() - 600, P[:, 1].min() - 600, P[:, 0].max() + 600, P[:, 1].max() + 600)
        me = R["build_run"](path, "Road_" + r["id"], RT, road_mats, dict(classes[r["class"]]))
        ro = bpy.data.objects.new("Road_" + r["id"], me)
        root_c.objects.link(ro)
        options = BD.OPTIONS[d] if sheet else [BD.CHOSEN[d]]
        for o in options:
            c = bpy.data.collections.new(f"{d}_{o}")
            root_c.children.link(c)
            ctx = BD.Ctx(c, BMAT, ground, built, ROOT, option=o, lights=not sheet)
            t0 = time.time()
            BD.build(ctx, br, path, classes[r["class"]], option=o)
            results[(d, o)] = (c, ro, time.time() - t0)
            print(f"[bridges] {d}/{o}: {len(c.objects)} objects in {time.time() - t0:.1f} s", flush=True)
    if stats:
        rep = {}
        for (d, o), (c, ro, dt) in results.items():
            for ob in c.objects:
                if ob.type == "MESH":
                    tri = sum(len(p.vertices) - 2 for p in ob.data.polygons)
                    rep[ob.name] = tri
                    print(f"  {ob.name:60s} {tri:8d} tris, {len(ob.data.materials)} mats")
        json.dump(rep, open(os.path.join(ROOT, ".citycache", "bridges", "tris.json"), "w"), indent=1)
        return
    res = (640, 360) if sheet else tuple(int(v) for v in str(opt("--res", "1280x720")).split("x"))
    WR.setup(int(opt("--samples", 24 if sheet else 48)), res)
    sc = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    moon = bpy.data.objects.new("Moon", bpy.data.lights.new("Moon", "SUN"))
    sc.collection.objects.link(moon)
    dd = os.path.join(ROOT, ".citycache", "bridges")
    os.makedirs(dd, exist_ok=True)
    if sheet:
        clay_m = clay("Clay", (0.72, 0.71, 0.69), 0.7)
        clay_c = clay("ClayCable", (0.85, 0.85, 0.84), 0.5)
        clay_t = clay("ClayGround", (0.25, 0.26, 0.25), 0.9)
        for ob in bpy.data.objects:
            if ob.type != "MESH" or ob.name == "Water":
                continue
            if ob.name.startswith("Terrain_"):
                ob.data.materials.clear()
                ob.data.materials.append(clay_t)
                continue
            mats = list(ob.data.materials)
            ob.data.materials.clear()
            for m in mats:
                ob.data.materials.append(clay_c if m and ("cable" in m.name) else clay_m)
            if ob.name.startswith("BridgeWash_") or ob.name.startswith("BridgeCablesFar_"):
                ob.hide_render = True
    shots = []
    for (d, o), (c, ro, dt) in results.items():
        view = {"expressway": "close", "kagero": "close"}.get(d, "dusk_wide") if sheet else "dusk_wide"
        cv = cams.get(f"{d}_{view}")
        if cv is None:
            continue
        for (d2, o2), (c2, _, _) in results.items():
            c2.hide_render = (d2, o2) != (d, o)
        WR.sky("day" if sheet else "dusk")
        if sheet:
            moon.data.energy = 3.5
            moon.rotation_euler = (math.radians(50), 0, math.radians(140))
        sc.view_settings.exposure = -0.3 if sheet else cv.get("exposure", 0.4)
        WR.aim(cam, cv["loc"], cv["target"], 24)
        cam.data.sensor_fit = "VERTICAL"
        cam.data.angle = math.radians(cv["fov_y"] + (6 if d == "expressway" else 0))
        p = os.path.join(dd, f"{'opt' if sheet else 'preview'}_{d}_{o}.png")
        sc.render.filepath = p
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"[bridges] rendered {p} in {time.time() - t0:.0f} s", flush=True)
        shots.append((d, o, p))
        if not sheet and opt("--close"):
            for nm in [k for k in cams if k.startswith(d) and "wide" not in k]:
                cv2 = cams[nm]
                WR.aim(cam, cv2["loc"], cv2["target"], 24)
                cam.data.angle = math.radians(cv2["fov_y"])
                sc.view_settings.exposure = cv2.get("exposure", 0.6)
                p2 = os.path.join(dd, f"preview_{nm}.png")
                sc.render.filepath = p2
                bpy.ops.render.render(write_still=True)
                print(f"[bridges] rendered {p2}", flush=True)
    if sheet:
        compose(shots)


TITLES = {
    "port": "Minato Bay Bridge (port, 629 m cable-stayed)",
    "expressway": "Shinkai Expressway (1.55 km viaduct)",
    "kagero": "Kagero Viaduct (hills, 398 m)",
    "tenjin": "Tenjin Arch (corporate island, 554 m)",
}
LABELS = {
    "H_truss": "A  concrete H pylons, semi-harp stays, steel Warren truss deck  (chosen)",
    "invY_box": "B  inverted-Y pylon, stays to one mast, steel box deck",
    "A_fan": "C  A-frame pylons, fan stays, steel box deck",
    "tulip": "A  brutalist box girder on sculpted tulip hammerheads  (chosen)",
    "portal": "B  twin-column portal piers",
    "split_V": "C  split V piers",
    "haunched": "A  haunched weathering-steel plate girders, portal piers  (chosen)",
    "through_truss": "B  Warren through truss",
    "deck_arch": "C  under-deck arch over the channel",
    "basket": "A  basket-handle network arch, Hoshikawa crown  (chosen)",
    "twin_ribs": "B  twin vertical ribs, vertical hangers",
    "single_lean": "C  single leaning arch (sculptural)",
}


def compose(shots):
    """The sheet is put together by plain Python (Blender has no PIL): tools/world/bridge_sheet.py."""
    import subprocess
    lst = os.path.join(ROOT, ".citycache", "bridges", "options.json")
    json.dump([{"design": d, "option": o, "path": p, "title": TITLES[d], "label": LABELS.get(o, o)} for d, o, p in shots], open(lst, "w"), indent=1)
    subprocess.run(["python", os.path.join(HERE, "bridge_sheet.py"), lst], check=False)


main()
