"""Street-level proof cameras for the ad workstream (docs/agents/ads).

Reads scenes/world/world.json and picks, per shot, the street segment with the
most ad-heavy building variants beside it, then writes cameras in the format
tools/world/world_render.py --cams reads ([{name, loc, target, fov_y}], Blender
coordinates) and the region to build around them.

    python tools/ads_proof.py [out_dir]          -> <out_dir>/cams.json, prints the --region
    blender -b --factory-startup --python tools/world/world_driver.py -- \
        --stages build,render --region <x0,y0,x1,y1> --cams <out_dir>/cams.json \
        --render-dir docs/agents/ads --samples 128 --res 1600x900
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHOTS = {
    # name: (district, variants that make the shot, camera height, look-up)
    "yoimachi_night": ("yoimachi", {"love_hotel", "hostess_bar", "cabaret_row", "hostess_row", "welcome", "velvet_moon", "peep_show", "snack"}, 1.6, 4.0),
    "downtown_corporate": ("downtown", {"platinum", "showroom"}, 1.6, 22.0),
}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("TEMP", "/tmp"), "ads_proof")
    os.makedirs(out, exist_ok=True)
    w = json.load(open(os.path.join(ROOT, "scenes", "world", "world.json"), encoding="utf-8"))
    cams, boxes = [], []
    for name, (dist, want, eye_h, up) in SHOTS.items():
        hot = [i for i in w["instances"] if i.get("district") == dist and i.get("variant") in want]
        best = None
        for r in w["roads"]:
            if r.get("class") not in ("street", "avenue"):
                continue
            pts = r["points"]
            for k in range(0, len(pts) - 1, 2):
                a, b = pts[k], pts[min(k + 6, len(pts) - 1)]
                if dist == "downtown" and math.dist(a[:2], (-120, -150)) > 260:
                    continue                      # the core, among the towers
                L = math.dist(a[:2], b[:2])
                if L < 10:
                    continue
                tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                # count the ad-heavy buildings in a 70 m cone ahead of a camera at a
                score = 0
                for i in hot:
                    dx, dy = i["pos"][0] - a[0], i["pos"][1] - a[1]
                    along = dx * tx + dy * ty
                    side = abs(-dx * ty + dy * tx)
                    if 8 < along < 70 and side < 22:
                        score += 1
                if best is None or score > best[0]:
                    best = (score, a, (tx, ty), r)
        score, a, (tx, ty), r = best
        half = 5.0 if r["class"] == "street" else 6.8
        # stand on the walk, look down the street
        sx, sy = -ty, tx
        loc = (a[0] + sx * (half + 1.2), a[1] + sy * (half + 1.2), a[2] + eye_h)
        tgt = (a[0] + tx * 60 - sx * 2, a[1] + ty * 60 - sy * 2, a[2] + up)
        cams.append({"name": name, "loc": [round(v, 2) for v in loc], "target": [round(v, 2) for v in tgt], "fov_y": 58,
                     "exposure": 0.6, "fog": 0.002})
        boxes.append((min(loc[0], tgt[0]) - 140, min(loc[1], tgt[1]) - 140, max(loc[0], tgt[0]) + 140, max(loc[1], tgt[1]) + 140))
        print(f"{name}: {score} ad-heavy buildings in view, road {r['id']}, cam {cams[-1]['loc']}")
    p = os.path.join(out, "cams.json")
    json.dump(cams, open(p, "w", encoding="utf-8"), indent=1)
    for (x0, y0, x1, y1), c in zip(boxes, cams):
        print(f"--region {x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}   ({c['name']})")
    print("cams ->", p)


if __name__ == "__main__":
    main()
