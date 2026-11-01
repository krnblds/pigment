"""Write the audit manifest (every asset kit) for audit_render.py.

    python tools/asset_audit/audit_manifest.py OUT.json [--world-meshes DIR] [--groups props,town,world,bridges,fleet,car]

--world-meshes: an exported world (game/assets/world/meshes, git-ignored; default: this checkout's,
else the main checkout's) for the bridge parts. World procedural meshes (towers, port kit, signal
poles) are built live from tools/world/world_meshes.py with scenes/world/world.json.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def arg(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else default


def main():
    out = sys.argv[1]
    groups = arg("--groups", "props,town,world,bridges,fleet,car").split(",")
    wm = arg("--world-meshes")
    if not wm:
        wm = os.path.join(ROOT, "game", "assets", "world", "meshes")
        if not os.path.isdir(wm):
            # a worktree: <main>/.claude/worktrees/<name>
            wm = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), "game", "assets", "world", "meshes")
    items = []
    if "props" in groups:
        for p in sorted(glob.glob(os.path.join(ROOT, "assets", "props", "*.glb"))):
            n = os.path.splitext(os.path.basename(p))[0]
            if n.endswith("_lod1"):
                continue
            items.append({"id": "props/" + n, "group": "props", "label": n, "kind": "glb", "path": p})
    if "town" in groups:
        tex = os.path.join(ROOT, "scenes", "town", "textures")
        for p in sorted(glob.glob(os.path.join(ROOT, "assets", "town", "*.glb"))):
            n = os.path.splitext(os.path.basename(p))[0]
            items.append({"id": "town/" + n, "group": "town", "label": n, "kind": "glb", "path": p,
                          "pigment": [os.path.join(tex, n), n]})
    if "world" in groups:
        wj = os.path.join(ROOT, "scenes", "world", "world.json")
        world = json.load(open(wj, encoding="utf-8"))
        keys = ["container", "crane_sts", "light_mast", "warehouse_60x30x12", "signal_pole", "signal_pole_long",
                "landmark_hoshikawa_hq", "landmark_meridian_spire"]
        seen = set()
        for t in world["towers"]:
            crown = t["crown"]
            if crown not in seen and not t["mesh"].startswith("landmark"):
                seen.add(crown)
                keys.append(t["mesh"])
        cols = {"container": (0.55, 0.06, 0.04), "crane_sts": (0.55, 0.06, 0.04), "warehouse_60x30x12": (0.05, 0.35, 0.38)}
        for k in keys:
            items.append({"id": "world/" + k, "group": "world", "label": k, "kind": "worldkit", "key": k, "world_json": wj,
                          "color": cols.get(k, (0.4, 0.4, 0.4))})
    if "bridges" in groups and os.path.isdir(wm):
        for pat in ("Bridge_tenjin_arch_*.glb", "Bridge_bay_expressway_east_*.glb", "Bridge_kagero_viaduct_*.glb",
                    "Bridge_deck_206_0.glb", "Girder_deck_206_0.glb", "LookoutRail.glb", "SeaWall0.glb"):
            for p in sorted(glob.glob(os.path.join(wm, pat)))[:1]:
                n = os.path.splitext(os.path.basename(p))[0]
                items.append({"id": "bridges/" + n, "group": "bridges", "label": n, "kind": "glb", "path": p,
                              "note": "exported world glb (material names only, untextured in the file)"})
    if "fleet" in groups:
        for d in sorted(glob.glob(os.path.join(ROOT, "assets", "vehicles", "*", ""))):
            n = os.path.basename(os.path.dirname(d))
            p = os.path.join(d, n + ".glb")
            if os.path.isfile(p):
                items.append({"id": "fleet/" + n, "group": "fleet", "label": n, "kind": "glb", "path": p})
    if "car" in groups:
        items.append({"id": "car/car", "group": "car", "label": "car (hero)", "kind": "glb",
                      "path": os.path.join(ROOT, "assets", "car", "car.glb")})
    json.dump(items, open(out, "w"), indent=1)
    print(len(items), "items ->", out)


main()
