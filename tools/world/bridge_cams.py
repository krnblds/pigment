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


def blockers(w):
    """(x, y, radius, top z) of buildings and towers, for line-of-sight checks."""
    B = []
    for i in w["instances"]:
        a = i["asset"]
        if a.startswith(("building_", "warehouse_")):
            B.append((i["pos"][0], i["pos"][1], 8.0, i["pos"][2] + 16.0))
    for tw in w.get("towers", []):
        fw, fd = tw["footprint"]
        B.append((tw["pos"][0], tw["pos"][1], 0.5 * math.hypot(fw, fd), tw["pos"][2] + tw["height"]))
    return np.array(B)


def clear(B, a, b, pad=2.0):
    """Number of blockers the sight line a -> b passes through (in plan within the radius and
    below their top at that point)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    L2 = float(d[:2] @ d[:2])
    if L2 < 1e-6:
        return 0
    f = np.clip(((B[:, 0] - a[0]) * d[0] + (B[:, 1] - a[1]) * d[1]) / L2, 0.0, 1.0)
    px, py, pz = a[0] + d[0] * f, a[1] + d[1] * f, a[2] + d[2] * f
    hit = (np.hypot(B[:, 0] - px, B[:, 1] - py) < B[:, 2] + pad) & (pz < B[:, 3]) & (f > 0.02) & (f < 0.98)
    return int(hit.sum())


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
            wide = mid[:2] + side * sg * 470 - along * 90
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, sea + 9.0], target=[*mid[:2], 42.0], fov_y=38, sky="night", exposure=1.0, fog=0.0),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, sea + 9.0], target=[*mid[:2], 42.0], fov_y=38, sky="dusk", exposure=0.4, fog=0.0)]
            cl = c[:2] + side * sg * 55 - along * 38
            out.append(dict(name=f"{tag}_close", loc=[*cl, sea + 3.0], target=[*c[:2], py["deck"] + 6.0], fov_y=55, sky="dusk", exposure=0.6, fog=0.0))
            top = c[:2] + side * sg * 70 + along * 25
            out.append(dict(name=f"{tag}_pylon_top", loc=[*top, py["top"] - 25.0], target=[*c[:2], py["top"] - 18.0], fov_y=40, sky="dusk", exposure=0.6, fog=0.0))
        elif tag == "expressway":
            # the stretch with the clearest view: an elevated camera beside the viaduct looking along
            # it, no building in the sight lines to the target and to a point 60 m on
            B = blockers(w)
            best = None
            for pi in br["piers"][2:-2]:
                p, a = station(road, pi["s"])
                sd = np.array([-a[1], a[0]])
                for sg in (1, -1):
                    for lat in (45.0, 70.0, 95.0):
                        for back in (60.0, 100.0):
                            cam = np.array([*(p[:2] + sd * sg * lat - a * back), p[2] + 22.0])
                            tg = np.array([*(p[:2] + a * 30), p[2] - 2.0])
                            far = np.array([*(p[:2] + a * 120), p[2]])
                            near = np.array([*(p[:2] - a * 40), p[2]])
                            n_hit = clear(B, cam, tg) + clear(B, cam, far) + clear(B, cam, near)
                            score = n_hit * 1000 - lat * 0.1 + back * 0.05
                            if best is None or score < best[0]:
                                best = (score, cam, tg, pi, p, a, sg)
            _, wide, tg, pi, p, a, sg = best
            out += [dict(name=f"{tag}_night_wide", loc=list(wide), target=list(tg), fov_y=48, sky="night", exposure=0.8, fog=0.0),
                    dict(name=f"{tag}_dusk_wide", loc=list(wide), target=list(tg), fov_y=48, sky="dusk", exposure=0.4, fog=0.0)]
            sd = np.array([-a[1], a[0]])
            cl = p[:2] + sd * sg * 17 - a * 15
            g = ground(H, t, *cl)
            out.append(dict(name=f"{tag}_close", loc=[*cl, g + 1.7], target=[*(p[:2] + a * 5), pi["top"] - 0.5], fov_y=62, sky="dusk", exposure=1.2, fog=0.0))
        elif tag == "kagero":
            pi = min(br["piers"], key=lambda p: p["bottom"])
            p, a = station(road, pi["s"])
            sg = low_side(mid, 200)
            wide = mid[:2] + side * sg * 300 + along * 60
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, sea + 8.0], target=[*mid[:2], 6.0], fov_y=30, sky="night", exposure=1.0, fog=0.0),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, sea + 8.0], target=[*mid[:2], 6.0], fov_y=30, sky="dusk", exposure=0.4, fog=0.0)]
            sd = np.array([-a[1], a[0]])
            cl = p[:2] + sd * sg * 30 - a * 26
            out.append(dict(name=f"{tag}_close", loc=[*cl, sea + 2.5], target=[*(p[:2] + a * 6), pi["top"] - 1.0], fov_y=58, sky="dusk", exposure=0.6, fog=0.0))
        elif tag == "tenjin":
            rib = np.array(br["arches"][0])
            crown = rib[len(rib) // 2]
            sg = low_side(crown, 250)
            wide = crown[:2] + side * sg * 380 - along * 120
            out += [dict(name=f"{tag}_night_wide", loc=[*wide, sea + 10.0], target=[*crown[:2], 30.0], fov_y=30, sky="night", exposure=1.0, fog=0.0),
                    dict(name=f"{tag}_dusk_wide", loc=[*wide, sea + 10.0], target=[*crown[:2], 30.0], fov_y=30, sky="dusk", exposure=0.4, fog=0.0)]
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


def godot_views(w, H, t):
    """Godot proof views (game/scripts/automation.gd --bridge-shots): the Cycles water view of the
    port bridge, a view from the city shore, and a drive across the cable-stayed bridge (the car on
    the outer forward lane, from before the first pylon towards the second)."""
    roads = {r["id"]: r for r in w["roads"]}
    out = []
    br = next(b for b in w["bridges"] if b["name"].startswith("bay_expressway"))
    road = roads[f"r{br['edge']}"]
    c = {k["name"]: k for k in cams(w, H, t, {"port", "tenjin"})}
    v = dict(c["port_night_wide"])
    v["name"] = "godot_port_water"
    out.append(v)
    s0, s1 = br["s"]
    p0, a0 = station(road, s0 + 5)
    side = np.array([-a0[1], a0[0]])
    best = None
    for sg in (1, -1):
        for back in (60, 100, 140):
            for lat in (70, 110, 150):
                q = p0[:2] - a0 * back + side * sg * lat
                g = ground(H, t, *q)
                if g > 1.0 and (best is None or g < best[1]):
                    best = (q, g)
    if best:
        q, g = best
        mid, _ = station(road, (s0 + s1) / 2)
        out.append({"name": "godot_port_shore", "loc": [*q, g + 1.8], "target": [*mid[:2], 40.0], "fov_y": 50})
    lane = max((l for l in road["lanes"] if l["dir"] > 0), key=lambda l: l["offset"])
    py0 = min(br["pylons"], key=lambda p: p["s"])
    P = np.array(road["points"], dtype=float)
    seg = np.hypot(*np.diff(P[:, :2], axis=0).T)
    S = np.concatenate([[0], np.cumsum(seg)])
    k = int(np.argmin(np.hypot(P[:, 0] - py0["pos"][0], P[:, 1] - py0["pos"][1])))
    sstart = max(s0 + 2, S[k] - 40)
    p, a = station(road, sstart)
    q, _ = station(road, sstart + 10)
    nrm = np.array([-a[1], a[0]])
    loc = [*(p[:2] + nrm * lane["offset"]), p[2]]
    tgt = [*(q[:2] + nrm * lane["offset"]), q[2]]
    out.append({"name": "godot_port_drive", "kind": "drive", "loc": loc, "target": tgt, "speed": 17.0, "secs": 5.0})
    v = dict(c["tenjin_night_wide"])
    v["name"] = "godot_tenjin_water"
    out.append(v)
    for c_ in out:
        c_["loc"] = [round(float(x), 2) for x in c_["loc"]]
        c_["target"] = [round(float(x), 2) for x in c_["target"]]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=os.path.join(ROOT, "scenes", "world"))
    ap.add_argument("--out", default=os.path.join(ROOT, ".citycache", "bridge_cams.json"))
    ap.add_argument("--only", default="")
    ap.add_argument("--godot", action="store_true", help="views for the game's --bridge-shots instead")
    a = ap.parse_args()
    w, H, t = load(a.world)
    c = godot_views(w, H, t) if a.godot else cams(w, H, t, set(x for x in a.only.split(",") if x))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(c, open(a.out, "w"), indent=1)
    print(f"{len(c)} cameras -> {a.out}")
