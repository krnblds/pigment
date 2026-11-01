"""World ground masks for the terrain materials (Blender tools/world/world_meshes.py
terrain_material, Godot game/scripts/terrain.gdshader): two RGBA8 PNGs on the
terrain grid (world.json "terrain": n x n samples, cell_m apart, from origin),
sampled by world position, so the materials need no mesh attributes and the
masks rebuild in seconds without touching the world build.

ground_masks.png
    R  urban      flattened city land (masks_urban.npy)
    G  forest     tree canopy density (cedar / pine / broadleaf instances, blurred)
    B  scree      talus below cliffs: a cliff uphill of this point, on a moderate slope
    A  verge      dirt and mud along roads that run through natural land
ground_masks2.png
    R  lot        vacant lots: port / industrial city land away from buildings and roads
    G  hollow     wet valley bottoms and hollows (mud, puddles)
    B  old town   the old town's city land (cobbles)
    A  shore      natural shore band (beach sand, the wet line)

    python tools/world/ground_masks.py [world dir (default scenes/world)] [--out dir]
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def blur(a, metres, cell):
    return ndimage.gaussian_filter(a.astype(np.float32), max(metres / cell, 0.5), mode="nearest")


def ellipse_d(isl, X, Y):
    """Normalised distance to an island's ellipse (1 = its rim)."""
    cx, cy = isl["center"]
    rx, ry = isl["radius"] if isinstance(isl["radius"], list) else (isl["radius"], isl["radius"])
    a = math.radians(isl.get("rotation", 0.0))
    dx, dy = X - cx, Y - cy
    u = dx * math.cos(a) + dy * math.sin(a)
    v = -dx * math.sin(a) + dy * math.cos(a)
    return np.sqrt((u / rx) ** 2 + (v / ry) ** 2)


def build(world_dir):
    w = json.load(open(os.path.join(world_dir, "world.json"), encoding="utf-8"))
    T = w["terrain"]
    n, cell = T["n"], T["cell_m"]
    ox, oy = T["origin"]
    H = np.fromfile(os.path.join(world_dir, T["heightfield"]), dtype="<f4").reshape(n, n)
    up = os.path.join(world_dir, "masks_urban.npy")
    U = np.load(up).astype(np.float32) if os.path.isfile(up) else np.zeros_like(H)
    xs = ox + np.arange(n) * cell
    X, Y = np.meshgrid(xs, oy + np.arange(n) * cell)

    def to_px(x, y):
        return (x - ox) / cell, (y - oy) / cell
    sea = w.get("sea_level", 0.0)
    gy, gx = np.gradient(H, cell)
    slope = np.hypot(gx, gy)
    land = (H > sea + 0.2).astype(np.float32)
    natural = land * (1 - smooth(0.15, 0.5, U))
    # quays and built shores: no beaches or scree around the city islands' rims
    near_city = smooth(0.03, 0.15, blur(U, 80.0, cell))

    # forest: splat trees, blur to a canopy density
    F = np.zeros_like(H)
    for i in w["instances"]:
        if i.get("kind") not in ("tree", "shrub"):
            continue
        px, py = to_px(i["pos"][0], i["pos"][1])
        ix, iy = int(round(px)), int(round(py))
        if 0 <= ix < n and 0 <= iy < n:
            F[iy, ix] += 1.0 if i.get("kind") == "tree" else 0.4
    forest = np.clip(blur(F, 9.0, cell) * (2 * math.pi * (9.0 / cell) ** 2) / 1.6, 0, 1)
    forest = smooth(0.08, 0.55, forest) * natural

    # scree: cliffs (> ~30 deg) uphill of a point on a gentler slope
    steep = smooth(0.55, 0.85, slope)
    sb = blur(steep, 6.0, cell)
    gl = np.maximum(slope, 1e-4)
    reach = 14.0 / cell                      # look 14 m uphill
    cy_, cx_ = np.mgrid[0:n, 0:n].astype(np.float32)
    up_x = cx_ + gx / gl * reach
    up_y = cy_ + gy / gl * reach
    cliff_above = ndimage.map_coordinates(sb, [up_y, up_x], order=1, mode="nearest")
    scree = np.clip(cliff_above * 1.6, 0, 1) * (1 - steep) * smooth(0.12, 0.3, slope) * natural
    scree = np.maximum(scree, blur(steep, 10.0, cell) * 0.6 * (1 - steep) * natural)
    scree = np.clip(blur(scree, 3.0, cell), 0, 1) * smooth(3.0, 8.0, H) * (1 - near_city)

    # verges: roads through natural land (rasterised at 2 m, blurred)
    img = Image.new("L", (n, n), 0)
    dr = ImageDraw.Draw(img)
    for r in w["roads"]:
        pts = [to_px(p[0], p[1]) for p in r["points"]]
        if len(pts) < 2:
            continue
        width = (r.get("half_width", 5.0) + 3.5) * 2 / cell
        dr.line(pts, fill=255, width=max(1, int(round(width))))
    road = np.asarray(img, dtype=np.float32) / 255.0
    verge = np.clip(blur(road, 4.0, cell) * 1.4, 0, 1) * natural * (1 - steep)

    # vacant lots: port city land away from buildings, containers and roads
    occ = Image.new("L", (n, n), 0)
    do = ImageDraw.Draw(occ)
    for i in w["instances"]:
        if i.get("kind") not in ("building", "tower", "warehouse", "container", "crane"):
            continue
        px, py = to_px(i["pos"][0], i["pos"][1])
        r = {"tower": 16.0, "warehouse": 22.0, "building": 10.0, "container": 5.0, "crane": 8.0}[i["kind"]] / cell
        do.ellipse([px - r, py - r, px + r, py + r], fill=255)
    occ = np.maximum(np.asarray(occ, dtype=np.float32) / 255.0, np.asarray(img, dtype=np.float32) / 255.0)
    free = 1 - np.clip(blur(occ, 8.0, cell) * 1.8, 0, 1)
    port = np.zeros_like(H)
    old = np.zeros_like(H)
    for isl in w["islands"]:
        d = ellipse_d(isl, X, Y)
        if isl.get("kind") in ("port",):
            port = np.maximum(port, smooth(1.15, 0.95, d))
    for dd in w["districts"]:
        if dd["name"] == "old_town":
            mid = next((x for x in w["districts"] if x["name"] == "midtown"), None)
            if mid and mid.get("center"):
                dist = np.hypot(X - mid["center"][0], Y - mid["center"][1])
                old = smooth(mid["radius"] - 60, mid["radius"] + 60, dist)
                shinkai = next(i for i in w["islands"] if i["name"] == dd["island"])
                old = old * smooth(1.1, 0.95, ellipse_d(shinkai, X, Y))
    urban = smooth(0.2, 0.6, U)
    lot = np.clip(urban * port * smooth(0.25, 0.7, free), 0, 1)
    oldtown = urban * old

    # hollows: below the surrounding ground on natural land, near-flat
    hollow = smooth(0.3, 2.5, blur(H, 30.0, cell) - H) * natural * (1 - smooth(0.15, 0.4, slope))
    # shore: natural land within ~6 m of sea level
    shore = smooth(6.0, 1.5, H - sea) * (H > sea - 3.0) * (1 - smooth(0.2, 0.5, U)) * (1 - smooth(0.4, 0.8, slope)) * (1 - near_city)
    m1 = np.stack([urban, forest, scree, verge], -1)
    m2 = np.stack([lot, hollow, oldtown, shore], -1)
    spots = ground_spots(w, H, T, {"forest": forest, "shore": shore, "rough": np.maximum(scree, steep)})
    return [(np.clip(m, 0, 1) * 255 + 0.5).astype(np.uint8) for m in (m1, m2)], T, spots


def ground_spots(w, H, T, M):
    """Camera spots that show the ground sets (Blender coords, eye / target):
    a forest floor beside the mountain road, a beach from the shore road, a
    scree / rock slope seen from the mountain road. The game's --bench-spots
    picks them up (game/scripts/automation.gd) and writes cams.json for Cycles."""
    n, cell = T["n"], T["cell_m"]
    ox, oy = T["origin"]

    def h(x, y):
        i = int(np.clip(round((x - ox) / cell), 0, n - 1))
        j = int(np.clip(round((y - oy) / cell), 0, n - 1))
        return float(H[j, i])

    def m(key, x, y, r=12.0):
        a = M[key]
        i0, i1 = int((x - r - ox) / cell), int((x + r - ox) / cell) + 1
        j0, j1 = int((y - r - oy) / cell), int((y + r - oy) / cell) + 1
        return float(a[max(j0, 0):max(j1, 1), max(i0, 0):max(i1, 1)].mean()) if i1 > 0 and j1 > 0 else 0.0
    best = {}
    for r in w["roads"]:
        pts = r["points"]
        for k in range(2, len(pts) - 2, 3):
            x, y = pts[k][0], pts[k][1]
            tx, ty = pts[k + 1][0] - pts[k - 1][0], pts[k + 1][1] - pts[k - 1][1]
            ln = math.hypot(tx, ty) or 1.0
            sx, sy = -ty / ln, tx / ln
            deck = any(r.get("deck", [False] * len(pts))[max(0, k - 2):k + 3])
            for sgn in (1, -1):
                ax, ay = x + sx * sgn * 18, y + sy * sgn * 18
                for key, name, need in (("forest", "ground_forest", 0.6), ("shore", "ground_beach", 0.2), ("rough", "ground_slope", 0.35)):
                    v = m(key, ax, ay)
                    if name in ("ground_slope", "ground_forest") and r["class"] != "mountain":
                        continue
                    if name == "ground_beach" and not (0.3 < h(x, y) < 8.0):
                        continue
                    if deck and name != "ground_beach":
                        continue
                    if v > need and v > best.get(name, (0,))[0]:
                        best[name] = (v, x, y, pts[k][2] if len(pts[k]) > 2 else h(x, y), sx * sgn, sy * sgn)
    spots = []
    for name, (v, x, y, z, sx, sy) in sorted(best.items()):
        if name == "ground_forest":
            ex, ey = x + sx * 9, y + sy * 9
            eye, at = [ex, ey, h(ex, ey) + 1.7], [x + sx * 19, y + sy * 19, h(x + sx * 19, y + sy * 19) + 0.2]
        elif name == "ground_beach":
            ex, ey = x + sx * 2, y + sy * 2
            d = 6.0
            while d < 80 and h(x + sx * d, y + sy * d) > 0.6:
                d += 2.0
            tx, ty = x + sx * max(d - 6, 8), y + sy * max(d - 6, 8)
            eye, at = [ex, ey, max(h(ex, ey), z) + 1.8], [tx, ty, h(tx, ty)]
        else:
            eye, at = [x, y, z + 2.6], [x + sx * 45, y + sy * 45, h(x + sx * 45, y + sy * 45) + 2.0]
        spots.append({"name": name, "eye": [round(c, 2) for c in eye], "at": [round(c, 2) for c in at], "fov": 55.0, "score": round(v, 2)})
    return spots


def main():
    a = sys.argv[1:]
    out = None
    if "--out" in a:
        i = a.index("--out")
        out = a[i + 1]
        del a[i:i + 2]
    world_dir = a[0] if a else os.path.join(ROOT, "scenes", "world")
    out = out or world_dir
    (m1, m2), T, spots = build(world_dir)
    os.makedirs(out, exist_ok=True)
    for name, m in (("ground_masks.png", m1), ("ground_masks2.png", m2)):
        # row 0 of the PNG = the northmost row (iy = n - 1), so the image reads like a map
        Image.fromarray(m[::-1], "RGBA").save(os.path.join(out, name))
    meta = {"n": T["n"], "cell_m": T["cell_m"], "origin": T["origin"], "rows": "north first (image v = 1 - (y - origin_y) / (n * cell))",
            "ground_masks.png": ["urban", "forest", "scree", "verge"], "ground_masks2.png": ["lot", "hollow", "old_town", "shore"]}
    json.dump(meta, open(os.path.join(out, "ground_masks.json"), "w"), indent=1)
    json.dump(spots, open(os.path.join(out, "ground_spots.json"), "w"), indent=1)
    print(f"ground masks -> {out} ({T['n']} px, {T['cell_m']} m)")


if __name__ == "__main__":
    main()
