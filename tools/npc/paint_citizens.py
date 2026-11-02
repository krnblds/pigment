"""Pigment weathering pass on the citizens' atlases (system Python + pigment-mcp --script).

    python tools/npc/paint_citizens.py [--pigment <pigment-mcp.exe>] [--only id,id] [--jobs 2]

For every built citizen (after compose_atlas.py) it writes a Pigment MCP script,
.npccache/citizens/pigment/<id>.jsonl:
  new_project(<id>_paint.glb = LOD0 in the bind pose, 1024)  ->  bake (AO / curvature)
  -> "Atlas" fill layer: the composed atlas as an image fill (UV)
  -> "Street grime": the Grime material through a dirt generator (cavities, low on the body)
  -> "Rain splash": darker, glossier hems and shoes (bottom-up gradient with breakup)
  -> export_textures(separate) + render a check view
and runs it.  The exported BaseColor replaces the atlas colour (alpha kept) and the Roughness is
min-blended into the mask's R channel, so the Godot shader's wet response sits on top.
Without pigment-mcp the composed atlases are used as they are (the step is optional).
"""
import concurrent.futures as cf
import glob
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, ".npccache", "citizens")
OUT = os.path.join(SRC, "pigment")
argv = sys.argv[1:]


def find_pigment():
    if "--pigment" in argv:
        return argv[argv.index("--pigment") + 1]
    for p in [os.path.join(ROOT, "target", "release", "pigment-mcp.exe"),
              os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), "target", "release", "pigment-mcp.exe"),
              os.path.join(ROOT, "..", "..", "..", "target", "release", "pigment-mcp.exe")]:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def script(cid):
    d = os.path.join(OUT, cid)
    os.makedirs(d, exist_ok=True)
    a = lambda p: p.replace("\\", "/")  # noqa: E731
    lines = [
        {"tool": "new_project", "args": {"mesh": a(os.path.join(SRC, cid + "_paint.glb")), "resolution": 1024}},
        {"tool": "bake", "args": {"curvature_radius": 0.003, "ao_distance": 0.06}},
        {"tool": "add_layer", "args": {"name": "Atlas", "image": {"base_color": a(os.path.join(SRC, cid + "_albedo.png")),
                                                                    "projection": "uv", "tiling": 1}}},
        {"tool": "add_layer", "args": {"name": "Street grime", "material": "Grime",
                                       "mask": {"generator": "dirt", "amount": 0.3, "softness": 0.3, "breakup": 0.55},
                                       "opacity": 0.3}},
        {"tool": "add_layer", "args": {"name": "Rain splash", "mask": {"generator": "gradient", "amount": 0.16, "breakup": 0.6},
                                       "values": {"base_color": [0.035, 0.035, 0.04], "roughness": 0.18}, "opacity": 0.45}},
        {"tool": "export_textures", "args": {"dir": a(d), "preset": "separate", "name": cid}},
        {"tool": "render", "args": {"path": a(os.path.join(d, cid + "_check.png")), "lighting": "night_rain"}},
    ]
    p = os.path.join(OUT, cid + ".jsonl")
    with open(p, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")
    return p, d


def find_map(d, key):
    for p in glob.glob(os.path.join(d, "*.png")):
        if key.lower() in os.path.basename(p).lower():
            return p
    return None


def merge(cid, d):
    bc = find_map(d, "basecolor") or find_map(d, "base_color")
    if not bc:
        return False
    base = os.path.join(SRC, cid)
    alb = np.asarray(Image.open(base + "_albedo.png").convert("RGBA")).copy()
    col = np.asarray(Image.open(bc).convert("RGB").resize(alb.shape[1::-1], Image.LANCZOS))
    if col.mean() < 1.0:          # empty export: keep the composed atlas
        return False
    alb[..., :3] = col
    Image.fromarray(alb, "RGBA").save(base + "_albedo.png")
    rg = find_map(d, "roughness")
    if rg:
        m = np.asarray(Image.open(base + "_mask.png").convert("RGB")).copy()
        r = np.asarray(Image.open(rg).convert("L").resize(m.shape[1::-1], Image.LANCZOS))
        m[..., 0] = np.minimum(m[..., 0], r)
        Image.fromarray(m, "RGB").save(base + "_mask.png")
    return True


def one(pig, cid):
    p, d = script(cid)
    r = subprocess.run([pig, "--script", p], capture_output=True, text=True, cwd=ROOT)
    ok = r.returncode == 0 and merge(cid, d)
    return cid, ok, (r.stderr or r.stdout)[-400:] if not ok else ""


def main():
    pig = find_pigment()
    if not pig:
        print("pigment-mcp not found (cargo build --release -p pigment_engine): keeping the composed atlases")
        return
    only = set(filter(None, (argv[argv.index("--only") + 1] if "--only" in argv else "").split(",")))
    ids = sorted(os.path.basename(p)[:-len("_paint.glb")] for p in glob.glob(os.path.join(SRC, "*_paint.glb")))
    ids = [i for i in ids if not only or i in only]
    jobs = int(argv[argv.index("--jobs") + 1]) if "--jobs" in argv else 2
    n = 0
    with cf.ThreadPoolExecutor(jobs) as ex:
        for cid, ok, err in ex.map(lambda c: one(pig, c), ids):
            n += ok
            print("pigment %-12s %s %s" % (cid, "ok" if ok else "FAILED", err))
    print("pigment weathering: %d / %d citizens" % (n, len(ids)))


if __name__ == "__main__":
    main()
