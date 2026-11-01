"""Proof cameras for the four landmark bridges (Cycles), from world.json + the heightfield.

    python tools/world/bridge_cams.py [--out .citycache/bridge_cams.json] [--only port,tenjin]

Writes the `--cams` list world_render.py reads ({name, loc, target, fov_y, sky, exposure, fog}),
then render with:

    blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,render \
        --cams .citycache/bridge_cams.json --render-dir docs/agents/bridges/after --res 1280x720 --samples 96

Per bridge: a wide shot at night and at dusk from the lower (water) side, and a close-up of
the structure (pylon anchorage / pier and deck underside) at dusk.
"""
import argparse
import json
import math
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# landmark bridges by name prefix -> short tag
TAGS = {"bay_expressway": "port", "city_expressway": "expressway", "kagero_viaduct": "kagero", "tenjin_arch": "tenjin"}


def load(world_dir):
    w = json.load(open(os.path.join(world_dir, "world.json"), encoding="utf-8"))
    t = w["terrain"]
    n = t["n"]
    H = np.fromfile(os.path.join(world_dir, "heightfield.f32"), dtype="<f4").reshape(n, n)
    return w, H, t


def ground(H, t, x, y):
    c = t["cell_m"]
    ox, oy = t["origin"]
    i = int(round((y - oy) / c))
    j = int(round((x - ox) / c))
    n = H.shape[0]
    if not (0 <= i < n and 0 <= j < n):
        return 0.0
    return float(H[i, j])


def station(road, s):
    P = np.array(road["points"], dtype=float)
    seg = np.hypot(*np.diff(P[:, :2], axis=0).T)
    S = np.concatenate([[0], np.cumsum(seg)])
    p = np.array([np.interp(s, S, P[:, k]) for k in range(3)])
    q = np.array([np.interp(min(s + 2, S[-1]), S, P[:, k]) for k in range(3)])
    r = np.array([np.interp(max(s - 2, 0), S, P[:, k]) for k in range(3)])
    tt = (q - r)[:2]
    tt /= np.linalg.norm(tt)
    return p, tt


def cams(w, H, t, only=None):
    roads = {r["id"]: r for r in w["roads"]}
    out = []
    for br in w["bridges"]:
        tag = next((v for k, v in TAGS.items() if br["name"].startswith(k)), None)
        if tag is None or (only and tag not in only):
            continue
        road = roads[f"r{br['edge']}"]
        s0, s1 = br["s"]
        L = s1 - s0
        mid, along = station(road, (s0 + s1) / 2)
        side = np.array([-along[1], along[0]])
        sea = w.get("sea_level", 0.0)

        def low_side(c, d):
            a = ground(H, t, *(c[:2] + side * d))
            b = ground(H, t, *(c[:2] - side * d))
            return 1.0 if a <= b else -1.0
        if tag == "port":
            py = br["pylons"][0]
            c = np.array(py["pos"] + [py["deck"]])
            sg = low_side(mid, 300)
            wide = mid[:2] + side * sg * 420 - along * 150
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, sea + 9.0], target=[*mid[:2], 45.0], fov_y=32, sky="night", exposure=1.0, fog=0.0002),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, sea + 9.0], target=[*mid[:2], 45.0], fov_y=32, sky="dusk", exposure=0.4, fog=0.0002)]
            cl = c[:2] + side * sg * 55 - along * 38
            out.append(dict(name=f"{tag}_close", loc=[*cl, sea + 3.0], target=[*c[:2], py["deck"] + 6.0], fov_y=55, sky="dusk", exposure=0.6, fog=0.0))
            top = c[:2] + side * sg * 70 + along * 25
            out.append(dict(name=f"{tag}_pylon_top", loc=[*top, py["top"] - 25.0], target=[*c[:2], py["top"] - 18.0], fov_y=40, sky="dusk", exposure=0.6, fog=0.0))
        elif tag == "expressway":
            # a stretch over the city streets: the tallest pier
            pi = max(br["piers"], key=lambda p: p["top"] - p["bottom"] + 0.001 * p["s"])
            pi = br["piers"][len(br["piers"]) // 2]
            p, a = station(road, pi["s"])
            sd = np.array([-a[1], a[0]])
            sg = low_side(p, 60)
            wide = p[:2] + sd * sg * 70 - a * 120
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, p[2] + 14.0], target=[*(p[:2] + a * 40), p[2] - 2.0], fov_y=45, sky="night", exposure=0.6, fog=0.0006),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, p[2] + 14.0], target=[*(p[:2] + a * 40), p[2] - 2.0], fov_y=45, sky="dusk", exposure=0.4, fog=0.0006)]
            cl = p[:2] + sd * sg * 16 - a * 14
            g = ground(H, t, *cl)
            out.append(dict(name=f"{tag}_close", loc=[*cl, g + 1.7], target=[*(p[:2] + a * 4), pi["top"] - 0.5], fov_y=62, sky="dusk", exposure=0.8, fog=0.0))
        elif tag == "kagero":
            pi = min(br["piers"], key=lambda p: p["bottom"])
            p, a = station(road, pi["s"])
            sg = low_side(mid, 200)
            wide = mid[:2] + side * sg * 300 + along * 60
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, sea + 8.0], target=[*mid[:2], 6.0], fov_y=30, sky="night", exposure=1.0, fog=0.0002),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, sea + 8.0], target=[*mid[:2], 6.0], fov_y=30, sky="dusk", exposure=0.4, fog=0.0002)]
            sd = np.array([-a[1], a[0]])
            cl = p[:2] + sd * sg * 30 - a * 26
            out.append(dict(name=f"{tag}_close", loc=[*cl, sea + 2.5], target=[*(p[:2] + a * 6), pi["top"] - 1.0], fov_y=58, sky="dusk", exposure=0.6, fog=0.0))
        elif tag == "tenjin":
            rib = np.array(br["arches"][0])
            crown = rib[len(rib) // 2]
            sg = low_side(crown, 250)
            wide = crown[:2] + side * sg * 380 - along * 120
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, sea + 10.0], target=[*crown[:2], 30.0], fov_y=30, sky="night", exposure=1.0, fog=0.0002),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, sea + 10.0], target=[*crown[:2], 30.0], fov_y=30, sky="dusk", exposure=0.4, fog=0.0002)]
            # on the sidewalk at the arch springing, looking up the rib and the hangers
            spring = rib[3]
            P = np.array(road["points"], dtype=float)
            k = int(np.argmin(np.hypot(P[:, 0] - spring[0], P[:, 1] - spring[1])))
            rp = P[k]
            off = np.array(spring[:2]) - rp[:2]
            q = rp[:2] + off * 0.55 - along * 10
            out.append(dict(name=f"{tag}_close", loc=[*q, rp[2] + 1.7], target=[*crown[:2], crown[2] - 18.0], fov_y=62, sky="dusk", exposure=0.6, fog=0.0))
    for c in out:
        c["loc"] = [round(float(v), 2) for v in c["loc"]]
        c["target"] = [round(float(v), 2) for v in c["target"]]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=os.path.join(ROOT, "scenes", "world"))
    ap.add_argument("--out", default=os.path.join(ROOT, ".citycache", "bridge_cams.json"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    w, H, t = load(a.world)
    c = cams(w, H, t, set(x for x in a.only.split(",") if x))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(c, open(a.out, "w"), indent=1)
    print(f"{len(c)} cameras -> {a.out}")
