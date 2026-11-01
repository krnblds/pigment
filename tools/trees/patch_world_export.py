"""Patch an existing open-world Godot export with new trees / props from world.json, without the
55-minute full export (system Python, numpy only).

    python tools/trees/patch_world_export.py --world scenes/world/world.json --layout game/assets/world/world_layout.json [--out FILE]

The full export (tools/world/world_driver.py --stages build,export) remains the reference; this
rewrites only the instances that tools/trees changes: every world.json instance of kind prop / tree /
shrub (props-kit props, kit trees, tree grates, planter shrubs). Layout instances named after those
assets (and the old procedural tree_pine / tree_broad) are replaced; kit-tree mesh entries are added
(cat "tree": town_loader.gd draws them through tree_kit.gd from res://assets/trees, so no mesh glb
is needed in the world export). Buildings, roads, lamps, signals... stay as exported.
"""
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
KINDS = ("prop", "tree", "shrub")
C = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)    # Blender -> Godot


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def gxform(pos, rz, scale):
    c, s = math.cos(rz), math.sin(rz)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ np.diag(scale)
    r = C @ R @ C.T
    t = C @ np.array(pos, float)
    return [round(float(r[i, j]), 5) for j in range(3) for i in range(3)] + [round(float(t[i]), 4) for i in range(3)]


def main():
    wpath = Path(arg("--world", ROOT / "scenes" / "world" / "world.json"))
    lpath = Path(arg("--layout", ROOT / "game" / "assets" / "world" / "world_layout.json"))
    out = Path(arg("--out", lpath))
    world = json.load(open(wpath, encoding="utf-8"))
    lay = json.load(open(lpath, encoding="utf-8"))
    kit = json.load(open(ROOT / "assets" / "trees" / "index.json", encoding="utf-8"))["variants"]
    new = [i for i in world["instances"] if i.get("kind") in KINDS]
    names = {i["asset"] for i in new} | {"tree_pine", "tree_broad"}
    mesh_of = {}
    keep = []
    removed = 0
    for inst in lay["instances"]:
        nm = inst.get("name", "")
        if nm in names or nm.startswith("tree_"):
            mesh_of.setdefault(nm, inst["mesh"])
            removed += 1
            continue
        keep.append(inst)
    added = missing = 0
    for i in new:
        a = i["asset"]
        if a in kit:
            key = a
            if key not in lay["meshes"]:
                v = kit[a]
                r, h = v.get("crown_radius", 1.0), v.get("height", 1.0)
                lay["meshes"][key] = {"file": "meshes/%s.glb" % key, "surfaces": ["TreeBark", "TreeLeaves"],
                                      "aabb": [[-r, -0.35, -r], [r, h, r]], "tris": v["tris"]["lod0"], "cat": "tree", "col": "cyl"}
        else:
            key = mesh_of.get(a) or ("PROP_" + a)
            if key not in lay["meshes"]:
                missing += 1
                continue
        keep.append({"mesh": key, "xf": gxform(i["pos"], i["rot"], i.get("scale") or [1, 1, 1]), "name": a})
        added += 1
    lay["instances"] = keep
    lay.setdefault("stats", {})["instances"] = len(keep)
    lay["patched"] = "tools/trees/patch_world_export.py: props / trees / shrubs from " + wpath.name
    with open(out, "w", encoding="utf-8") as f:
        json.dump(lay, f, separators=(",", ":"))
    if out.parent != wpath.parent:
        shutil.copyfile(wpath, out.parent / "world.json")
    print(f"patched {out}: removed {removed}, added {added} ({missing} without a mesh), {len(keep)} instances")


if __name__ == "__main__":
    main()
