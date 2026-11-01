"""Top-down map of a generated world (system Python: numpy + PIL).

    python tools/world/world_map.py [scenes/world] [--out docs/agents/world/map.png] [--px 2048]

Hillshaded terrain, water depth, roads by class (decks outlined), junctions
(signalised ones marked), bridges, building and tower footprints, port
containers, trees.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COL = {"street": (230, 230, 225), "avenue": (255, 200, 90), "highway_urban": (255, 120, 60), "highway": (255, 90, 40), "mountain": (240, 240, 140)}
FOOT = {"building_a": (8.8, 11.8), "building_b": (16.8, 12.6), "building_c": (14.8, 16.4), "container": (12.2, 2.4)}


def main():
    args = [a for a in sys.argv[1:]]
    out_dir = os.path.join(ROOT, args[0]) if args and not args[0].startswith("--") else os.path.join(ROOT, "scenes", "world")
    out = args[args.index("--out") + 1] if "--out" in args else os.path.join(out_dir, "map.png")
    px = int(args[args.index("--px") + 1]) if "--px" in args else 2048
    W = json.load(open(os.path.join(out_dir, "world.json"), encoding="utf-8"))
    T = W["terrain"]
    n = T["n"]
    H = np.fromfile(os.path.join(out_dir, T["heightfield"]), dtype="<f4").reshape(n, n)
    step = max(1, n // px)
    Hs = H[::step, ::step][::-1]
    gx = np.gradient(Hs, axis=1) / (T["cell_m"] * step)
    gy = np.gradient(Hs, axis=0) / (T["cell_m"] * step)
    shade = np.clip(0.75 + (-gx + gy) * 0.9, 0.25, 1.3)
    img = np.zeros(Hs.shape + (3,))
    sea = Hs < 0
    depth = np.clip(-Hs / 30, 0, 1)
    img[sea] = (np.array([0.10, 0.22, 0.32])[None] * (1 - depth[sea, None] * 0.6))
    l = np.clip(Hs / 280, 0, 1)
    grass = np.stack([0.32 + 0.5 * l, 0.42 + 0.35 * l, 0.26 + 0.5 * l], -1)
    img[~sea] = (grass * shade[..., None])[~sea]
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((px, px), Image.BILINEAR)
    d = ImageDraw.Draw(im)
    S = W["size_m"]
    k = px / S

    def P(x, y):
        return ((x + S / 2) * k, (S / 2 - y) * k)
    for i in W["instances"]:
        a = i["asset"]
        x, y = i["pos"][:2]
        if a.startswith("tree"):
            d.point(P(x, y), fill=(40, 80, 40))
            continue
        if a.startswith(("tower", "landmark")) or a in FOOT or a.startswith("warehouse"):
            if a in FOOT:
                w, h = FOOT[a]
            elif a.startswith("warehouse"):
                w, h = [float(v) for v in a.split("_")[1].split("x")[:2]]
            else:
                tw = next((t for t in W["towers"] if t["mesh"] == a and abs(t["pos"][0] - x) < 0.1), None)
                w, h = tw["footprint"] if tw else (30, 30)
            c, s = math.cos(i["rot"]), math.sin(i["rot"])
            pts = [P(x + u * c - v * s, y + u * s + v * c) for u, v in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
            fill = (90, 90, 100) if a.startswith("building") else (60, 70, 110) if a.startswith(("tower", "landmark")) else (150, 110, 70) if a == "container" else (120, 120, 120)
            d.polygon(pts, fill=fill)
    for r in W["roads"]:
        pts = [P(p[0], p[1]) for p in r["points"]]
        wdt = max(1, int(round(r["width"] * k)))
        if any(r["deck"]):
            d.line(pts, fill=(20, 20, 20), width=wdt + 3)
        d.line(pts, fill=COL.get(r["class"], (255, 255, 255)), width=wdt)
    for j in W["junctions"]:
        x, y = j["pos"][:2]
        c = P(x, y)
        r = 3 if j.get("signalised") else 1.5
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(255, 60, 60) if j.get("signalised") else (200, 200, 200))
    for b in W["bridges"]:
        for p in b["pylons"]:
            c = P(*p["pos"])
            d.rectangle([c[0] - 3, c[1] - 3, c[0] + 3, c[1] + 3], fill=(255, 255, 255))
    for w in W["sea_walls"]:
        d.line([P(*p) for p in w["points"]], fill=(200, 200, 210), width=2)
    if W.get("spawn"):
        c = P(*W["spawn"]["pos"][:2])
        d.ellipse([c[0] - 6, c[1] - 6, c[0] + 6, c[1] + 6], outline=(0, 255, 255), width=2)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    print("map", out)


if __name__ == "__main__":
    main()
