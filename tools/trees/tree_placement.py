"""Where the tree kit grows in the open world (used by tools/world/placement.py). Pure data.

Species by context:
    avenues      lined regularly in tree pits with cast-iron grates (tree_grate), one species
                 per avenue: downtown zelkova (keyaki), midtown ginkgo (some avenues gold),
                 old town pagoda tree, Kagero hills cherry, the corporate island palms
    streets      the props kit's `street_tree` / `palm_tree` scatter spots become a kit tree of
                 the district's species (smaller), with a grate; `planter`s get clipped shrubs
    parks        small groves on free urban land (cherry / pagoda + azalea borders) in the old
                 town, midtown and the hills: the "temple ground" spots
    nature       mountain forest: cedar clusters (thinning out towards the summits, pines on
                 the ridges); shores and low coastal land: black pine; the mid slopes mixed
                 cedar / pagoda / zelkova; black pines along the mountain road verge and a ring
                 of cherries and pines at the summit lookout
Every instance is a world.json instance {asset: tree_<species>_<shape>[_<look>], kind: "tree"}
(the grates: kind "prop"). Deterministic: own RNGs seeded from the world seed.
"""
import json
import math
import os
import random

import numpy as np
from mathutils import Vector

AVENUE_SPECIES = {"downtown": "zelkova", "midtown": "ginkgo", "old_town": "pagoda", "hillside": "cherry", "corporate": "palm"}
STREET_SPECIES = {"downtown": ["zelkova"], "midtown": ["ginkgo", "zelkova"], "old_town": ["pagoda", "cherry"],
                  "hillside": ["cherry", "pagoda"], "corporate": ["palm"], "port": ["zelkova"]}
# Fewer trees (user feedback): avenue trees roughly every 20 m, sparser groves and forest.
SPACING = {"zelkova": 20.0, "ginkgo": 18.0, "pagoda": 22.0, "cherry": 19.0, "palm": 20.0}
GROVE_GRID_M = 80.0         # was 46
NATURE_STEP_M = 15.0        # was 8.5 (about a third of the forest)


class Kit:
    def __init__(self, root):
        p = os.path.join(root, "assets", "trees", "index.json")
        self.ok = os.path.isfile(p)
        self.by = {}
        if not self.ok:
            return
        idx = json.load(open(p, encoding="utf-8"))
        for k, v in idx["variants"].items():
            if v.get("planter") or v.get("kind") == "grate":
                continue
            self.by.setdefault((v["species"], v.get("look")), []).append(k)
        for k in self.by:
            self.by[k].sort()
        self.grate = "tree_grate" in idx["variants"]

    def pick(self, rng, species, look=None, avoid=None):
        vs = self.by.get((species, look)) or self.by.get((species, None)) or []
        if not vs:
            return None
        v = rng.choice(vs)
        if v == avoid and len(vs) > 1:
            v = rng.choice([x for x in vs if x != avoid])
        return v


def _near(pts, p, r):
    for q in pts:
        if (q[0] - p.x) ** 2 + (q[1] - p.y) ** 2 < r * r:
            return True
    return False


def _grid(points, cell=8.0):
    g = {}
    for x, y in points:
        g.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
    return g


def _near_grid(g, p, r, cell=8.0):
    cx, cy = int(p.x // cell), int(p.y // cell)
    n = int(math.ceil(r / cell))
    for i in range(cx - n, cx + n + 1):
        for j in range(cy - n, cy + n + 1):
            for q in g.get((i, j), ()):
                if (q[0] - p.x) ** 2 + (q[1] - p.y) ** 2 < r * r:
                    return True
    return False


def avenue_trees(cfg, P, net, kit, H, log, rot90, edge_island, district_of, on_deck, WALK_Z):
    """Avenues lined in tree pits (both sides, regular spacing), one species per avenue."""
    rng = random.Random(cfg["seed"] * 7 + 301)
    furniture = [(i["pos"][0], i["pos"][1]) for i in P.instances if i.get("kind") in ("lamp", "pole", "signal", "mast")]
    fg = _grid(furniture)
    n = ng = 0
    for e in sorted(net.alive_edges(), key=lambda e: e.id):
        cc = net.classes[e.cls]
        if e.cls != "avenue" or cc.get("side", "curb") != "curb" or e.kind != "grid":
            continue
        isl = edge_island(cfg, net, e)
        L = e.path.length
        if L < 40:
            continue
        mid, _ = e.path.at(L / 2)
        dist = district_of(cfg, isl, mid.to_2d())
        if dist is None or dist["name"] not in AVENUE_SPECIES:
            continue
        sp = AVENUE_SPECIES[dist["name"]]
        look = "gold" if sp == "ginkgo" and rng.random() < 0.35 else ("green" if sp == "cherry" and rng.random() < 0.4 else None)
        sp_space = SPACING[sp]
        hh = cc["half"]
        last = None
        for sgn in (1, -1):
            s = 14.0 + rng.uniform(0, 3)
            while s < L - 14.0:
                if on_deck(e, s):
                    s += sp_space
                    continue
                pos, t = e.path.at(s)
                nout = rot90(t) * sgn
                p = pos.to_2d() + nout * (hh + 1.1)
                if _near_grid(fg, p, 3.2):
                    s += 2.0
                    continue
                key = kit.pick(rng, sp, look, last)
                last = key
                rz = rng.uniform(0, 2 * math.pi)
                sc = rng.uniform(0.85, 1.05) if sp != "palm" else rng.uniform(0.9, 1.1)
                z = pos.z + WALK_Z
                P.add(key, (p.x, p.y, z), rz, dist["name"], scale=(sc, sc, sc * rng.uniform(0.95, 1.05)), kind="tree", slot="avenue")
                n += 1
                if kit.grate and sp != "palm":
                    P.add("tree_grate", (p.x, p.y, z), math.atan2(-nout.x, nout.y), dist["name"], kind="prop", slot="tree_pit")
                    ng += 1
                s += sp_space * rng.uniform(0.95, 1.05)
    log(f"avenue trees: {n} in pits ({ng} grates)")
    return n


def street_swaps(cfg, P, kit, log):
    """The props kit's tree spots -> kit trees of the district's species; planters get shrubs."""
    rng = random.Random(cfg["seed"] * 7 + 302)
    out = []
    n = s_ = 0
    for i in P.instances:
        a = i["asset"]
        if a in ("street_tree", "palm_tree") and i.get("kind") == "prop":
            d = i.get("district", "midtown")
            if rng.random() < 0.55:                 # fewer trees: drop about half of the street spots
                continue
            sp = "palm" if a == "palm_tree" else rng.choice(STREET_SPECIES.get(d, ["zelkova"]))
            key = kit.pick(rng, sp)
            if key is None:
                out.append(i)
                continue
            sc = rng.uniform(0.62, 0.8) if sp != "palm" else rng.uniform(0.8, 1.0)
            x, y, z = i["pos"]
            out.append({"asset": key, "variant": None, "pos": [x, y, z], "rot": round(rng.uniform(0, 2 * math.pi), 5),
                        "scale": [round(sc, 4)] * 3, "district": d, "kind": "tree", "slot": "street"})
            if kit.grate and sp != "palm":
                out.append({"asset": "tree_grate", "variant": None, "pos": [x, y, z], "rot": i["rot"], "scale": [0.85, 0.85, 1.0],
                            "district": d, "kind": "prop", "slot": "tree_pit"})
            n += 1
            continue
        out.append(i)
        if a == "planter" and i.get("kind") == "prop":
            sh = "tree_planter_azalea" if rng.random() < 0.45 else "tree_planter_box"
            x, y, z = i["pos"]
            out.append({"asset": sh, "variant": None, "pos": [x, y, round(z + 0.93 * i["scale"][2], 3)], "rot": i["rot"],
                        "scale": i["scale"], "district": i.get("district"), "kind": "shrub", "slot": "planter"})
            s_ += 1
    P.instances[:] = out
    log(f"street trees: {n} props-kit tree spots became kit trees, {s_} planters got shrubs")


def park_groves(cfg, P, kit, hf, log, rect, district_of):
    """Small groves (cherry / pagoda, azalea borders) on free urban land: parks and temple grounds."""
    rng = random.Random(cfg["seed"] * 7 + 303)
    n = groves = 0
    want = {"old_town": 0.5, "midtown": 0.3, "hillside": 0.6}
    for isl in cfg["islands"]:
        if isl["kind"] not in ("urban", "hills"):
            continue
        cx, cy = isl["center"]
        R = max(isl["radius"]) * 1.05
        for gy in np.arange(cy - R, cy + R, GROVE_GRID_M):
            for gx in np.arange(cx - R, cx + R, GROVE_GRID_M):
                c = Vector((gx + rng.uniform(-14, 14), gy + rng.uniform(-14, 14)))
                d = district_of(cfg, isl["name"], c)
                if d is None or rng.random() > want.get(d["name"], 0.0):
                    continue
                corners = rect(c, 0.0, (-9, 9, -9, 9))
                if not P.free(corners) or not P.road_clear(corners, 1.0):
                    continue
                hi, lo = P.ground(c, 0.0, (-9, 9, -9, 9))
                if lo < 2.0 or hi - lo > 2.5:
                    continue
                P.claim(corners)
                groves += 1
                main = "cherry" if rng.random() < 0.65 else "pagoda"
                look = "green" if main == "cherry" and rng.random() < 0.3 else None
                k = int(rng.integers(3, 6)) if hasattr(rng, "integers") else rng.randint(3, 5)
                pts = []
                for j in range(k * 2):
                    if len(pts) >= k:
                        break
                    q = c + Vector((rng.uniform(-6.5, 6.5), rng.uniform(-6.5, 6.5)))
                    if any((q - p_).length < 5.5 for p_ in pts):
                        continue
                    pts.append(q)
                    z = float(hf.sample_tri(np.array([q.x]), np.array([q.y]))[0])
                    key = kit.pick(rng, main if rng.random() < 0.8 else ("pagoda" if main == "cherry" else "cherry"), look)
                    sc = rng.uniform(0.85, 1.1)
                    P.add(key, (q.x, q.y, z - 0.1), rng.uniform(0, 6.28), d["name"], scale=(sc, sc, sc), kind="tree", slot="park")
                    n += 1
                for j in range(rng.randint(2, 4)):            # azalea / box borders
                    a = rng.uniform(0, 2 * math.pi)
                    q = c + Vector((math.cos(a), math.sin(a))) * rng.uniform(6.5, 8.0)
                    z = float(hf.sample_tri(np.array([q.x]), np.array([q.y]))[0])
                    key = kit.pick(rng, "azalea", "bloom" if rng.random() < 0.5 else None) if rng.random() < 0.75 else kit.pick(rng, "box")
                    if key:
                        sc = rng.uniform(0.8, 1.2)
                        P.add(key, (q.x, q.y, z), a + math.pi / 2, d["name"], scale=(sc, sc, sc), kind="shrub", slot="park")
    log(f"parks: {groves} groves, {n} trees")


def nature_trees(cfg, P, hf, masks, kit, log, rect, Perlin, net=None, rot90=None):
    """Forests and shores on natural land by height, slope and distance to the sea."""
    rng = random.Random(cfg["seed"] * 7 + 304)
    noise = Perlin(cfg["seed"] + 55)
    noise2 = Perlin(cfg["seed"] + 77)
    step = NATURE_STEP_M
    xs = np.arange(-cfg["size_m"] / 2 + 10, cfg["size_m"] / 2 - 10, step)
    X, Y = np.meshgrid(xs, xs)
    rs = np.random.default_rng(cfg["seed"] + 11)
    X = X + rs.uniform(-3.5, 3.5, X.shape)
    Y = Y + rs.uniform(-3.5, 3.5, X.shape)
    Z = hf.sample_tri(X, Y)
    gx = (hf.sample(X + 2, Y) - hf.sample(X - 2, Y)) / 4
    gy = (hf.sample(X, Y + 2) - hf.sample(X, Y - 2)) / 4
    slope = np.hypot(gx, gy)
    U = masks["urban_flat"]
    ix = np.clip(((X - hf.x0) / hf.cell).astype(int), 0, hf.n - 1)
    iy = np.clip(((Y - hf.x0) / hf.cell).astype(int), 0, hf.n - 1)
    # distance to the sea (coarse): lowest terrain within 40 m
    low = np.minimum.reduce([hf.sample_tri(X + dx, Y + dy) for dx, dy in ((40, 0), (-40, 0), (0, 40), (0, -40), (28, 28), (-28, -28), (28, -28), (-28, 28))])
    dens = 0.5 + 0.5 * noise(X / 220.0, Y / 220.0)
    clump = 0.5 + 0.5 * noise2(X / 45.0, Y / 45.0)
    ok = (Z > 1.6) & (slope < 0.8) & (U[iy, ix] < 0.3) & (Z < 272)
    counts = {}
    for x, y, z, dn, cl, lw, sl in zip(X[ok], Y[ok], Z[ok], dens[ok], clump[ok], low[ok], slope[ok]):
        coast = lw < 0.5 and z < 9
        if z > 32:
            zone = "forest"
            keep = 0.25 + 0.75 * dn * (1.0 if z < 200 else max(0.15, 1 - (z - 200) / 80))
            keep *= 0.55 + 0.6 * cl            # clusters
        elif coast:
            zone = "shore"
            keep = 0.55 * dn + 0.15
        else:
            zone = "slope"
            keep = 0.2 + 0.55 * dn * cl
        if rng.random() > keep:
            continue
        p = Vector((float(x), float(y)))
        corners = rect(p, 0.0, (-1.6, 1.6, -1.6, 1.6))
        if not P.free(corners) or not P.road_clear(corners, 1.5):
            continue
        r = rng.random()
        if zone == "forest":
            sp = "pine" if (sl > 0.68 or z > 225 or r < 0.07) else "cedar"
        elif zone == "shore":
            sp = "pine"
        else:
            sp = "cedar" if r < 0.5 else ("pine" if r < 0.65 else ("pagoda" if r < 0.85 else "zelkova"))
        key = kit.pick(rng, sp)
        sc = rng.uniform(0.75, 1.15) * (0.8 if z > 190 else 1.0) * (0.85 if sp == "cedar" and zone != "forest" else 1.0)
        P.add(key, (p.x, p.y, float(z) - 0.15), rng.uniform(0, 6.28), "nature", scale=(sc, sc, sc * rng.uniform(0.92, 1.1)), kind="tree", slot=zone)
        counts[sp] = counts.get(sp, 0) + 1
    # black pines along the mountain road verge (outside the guard rail) and the summit lookout ring
    nv = 0
    if net is not None and rot90 is not None:
        for e in sorted(net.alive_edges(), key=lambda e: e.id):
            if e.cls != "mountain":
                continue
            hh = net.classes[e.cls]["half"]
            s = 20.0 + rng.uniform(0, 10)
            while s < e.path.length - 10:
                pos, t = e.path.at(s)
                sgn = rng.choice((1, -1))
                p = pos.to_2d() + rot90(t) * sgn * (hh + rng.uniform(4.0, 7.0))
                z = float(hf.sample_tri(np.array([p.x]), np.array([p.y]))[0])
                corners = rect(p, 0.0, (-1.2, 1.2, -1.2, 1.2))
                if abs(z - pos.z) < 4.0 and P.free(corners) and P.road_clear(corners, 1.0):
                    key = kit.pick(rng, "pine")
                    sc = rng.uniform(0.85, 1.15)
                    P.add(key, (p.x, p.y, z - 0.15), rng.uniform(0, 6.28), "nature", scale=(sc, sc, sc), kind="tree", slot="mountain_road")
                    nv += 1
                s += rng.uniform(22, 48)
        for nd in net.alive_nodes():
            if nd.kind != "plaza" or nd.J is None:
                continue
            J = nd.J
            for k in range(7):
                a = 2 * math.pi * k / 14 + rng.uniform(-0.1, 0.1)
                p = J.pos + Vector((math.cos(a), math.sin(a))) * (J.R + rng.uniform(5.0, 8.0))
                z = float(hf.sample_tri(np.array([p.x]), np.array([p.y]))[0])
                if abs(z - J.z) > 3.0:
                    continue
                sp = "cherry" if k % 2 == 0 else "pine"
                key = kit.pick(rng, sp)
                P.add(key, (p.x, p.y, z - 0.1), rng.uniform(0, 6.28), "nature", scale=(1.0, 1.0, 1.0), kind="tree", slot="lookout")
                nv += 1
    log(f"nature trees: {sum(counts.values())} ({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}), {nv} along the mountain road / lookout")
