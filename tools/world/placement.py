"""Instances for the world: buildings per district (the town's frontage +
back-row placement), procedural towers, the port (warehouses, containers,
cranes, light masts), street props, signals, trees. Pure data.

Every instance is {"asset", "variant", "pos": [x, y, z], "rot": rz radians,
"scale": [sx, sy, sz], "district"} (+ "footing": depth below pos for
buildings). Assets are kit meshes (assets/town/<asset>.glb), props
(assets/props/<asset>.glb when the props kit is present) or procedural
meshes the build stage generates from their key (tower_*, warehouse_*,
container, crane_sts, signal_pole_*, light_mast, tree_*).
"""
import glob
import math
import os
import random

import numpy as np
from mathutils import Vector

ROAD_Z, WALK_Z, WALK_OUT = 0.2, 0.35, 3.0

# kit footprints (Blender space, from assets/town/*.glb: front of the building at -y)
KIT = {
    "building_a": {"ext": (-4.39, 4.39, -6.62, 5.17), "h": 24.0},
    "building_b": {"ext": (-8.39, 8.39, -6.39, 6.17), "h": 20.6},
    "building_c": {"ext": (-7.39, 7.39, -9.25, 7.12), "h": 41.9},
}
LAMP_COLS = [(1.0, 0.62, 0.32), (0.4, 0.8, 1.0), (1.0, 0.35, 0.75), (1.0, 0.62, 0.32)]
FACADES = ["glass_blue", "glass_dark", "concrete_warm", "panel_cyan"]


def rot90(v):
    return Vector((-v.y, v.x))


def variants_on_disk(root):
    tex = os.path.join(root, "scenes", "town", "textures")
    out = {}
    for a in list(KIT) + ["overhead_sign"]:
        fs = sorted(glob.glob(os.path.join(tex, a + "__*")))
        out[a] = [os.path.basename(f).split("__", 1)[1] for f in fs if os.path.isfile(os.path.join(f, a + "_BaseColor.png"))]
    return out


def props_on_disk(root):
    """Street props from the props kit (assets/props/*.glb), if merged."""
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(root, "assets", "props", "*.glb")))


class Hash:
    """Spatial hash of oriented rectangles / points."""

    def __init__(self, cell=32.0):
        self.cell = cell
        self.d = {}

    def keys(self, x0, y0, x1, y1):
        c = self.cell
        for i in range(int(math.floor(x0 / c)), int(math.floor(x1 / c)) + 1):
            for j in range(int(math.floor(y0 / c)), int(math.floor(y1 / c)) + 1):
                yield (i, j)

    def add(self, item, x0, y0, x1, y1):
        for k in self.keys(x0, y0, x1, y1):
            self.d.setdefault(k, []).append(item)

    def query(self, x0, y0, x1, y1):
        seen = set()
        for k in self.keys(x0, y0, x1, y1):
            for it in self.d.get(k, ()):
                if id(it) not in seen:
                    seen.add(id(it))
                    yield it


def rect(cn, rz, ext):
    xmin, xmax, ymin, ymax = ext
    cs, sn = math.cos(rz), math.sin(rz)
    return [Vector((cn.x + lx * cs - ly * sn, cn.y + lx * sn + ly * cs)) for lx, ly in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax))]


def overlap(a, b):
    """Separating-axis test of two convex quads (same as blender_town)."""
    for poly in (a, b):
        for i in range(4):
            e = poly[(i + 1) % 4] - poly[i]
            ax = Vector((-e.y, e.x))
            pa = [ax.dot(p) for p in a]
            pb = [ax.dot(p) for p in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


class Placer:
    def __init__(self, cfg, hf, net, rng):
        self.cfg, self.hf, self.net, self.rng = cfg, hf, net, rng
        self.rects = Hash(32.0)
        self.road = Hash(16.0)
        self.instances = []
        self.n_over = 0
        # road samples with their keep-out (footprint) radius
        for e in net.alive_edges():
            cc = net.classes[e.cls]
            side = cc.get("side", "curb")
            w = cc["half"] + (WALK_OUT if side == "curb" else 1.2)
            L = e.path.length
            s = np.linspace(0, L, max(2, int(L / 2.0) + 1))
            pos, t = e.path.at_many(s)
            for p in pos:
                self.road.add((p[0], p[1], w, p[2]), p[0] - 1, p[1] - 1, p[0] + 1, p[1] + 1)
        for nd in net.alive_nodes():
            J = nd.J
            if J is None:
                continue
            for i, d in enumerate(J.dirs):
                for tt in np.arange(0, J.L[i] + 1e-6, 2.0):
                    p = J.pos + d * tt
                    self.road.add((p.x, p.y, J.half[i] + WALK_OUT + (2.0 if tt < 6 else 0.0), J.z), p.x - 1, p.y - 1, p.x + 1, p.y + 1)
            if nd.kind == "plaza":
                for a in np.linspace(0, 2 * math.pi, 24, endpoint=False):
                    p = J.pos + Vector((math.cos(a), math.sin(a))) * J.R * 0.6
                    self.road.add((p.x, p.y, J.R * 0.4 + WALK_OUT + 2, J.z), p.x - 1, p.y - 1, p.x + 1, p.y + 1)

    def road_clear(self, corners, clear=0.25):
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        R = 32.0
        cn = sum(corners, Vector((0, 0))) / 4
        ex = (corners[1] - corners[0])
        ey = (corners[3] - corners[0])
        hw, hh = ex.length / 2, ey.length / 2
        ux, uy = ex.normalized(), ey.normalized()
        for (x, y, w, z) in self.road.query(min(xs) - R, min(ys) - R, max(xs) + R, max(ys) + R):
            dx, dy = x - cn.x, y - cn.y
            lx = abs(dx * ux.x + dy * ux.y)
            ly = abs(dx * uy.x + dy * uy.y)
            d = math.hypot(max(lx - hw, 0.0), max(ly - hh, 0.0))
            if d < w + clear:
                return False
        return True

    def free(self, corners):
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        for q in self.rects.query(min(xs), min(ys), max(xs), max(ys)):
            if overlap(corners, q):
                return False
        return True

    def ground(self, cn, rz, ext, n=5):
        xmin, xmax, ymin, ymax = ext
        cs, sn = math.cos(rz), math.sin(rz)
        u = np.linspace(xmin, xmax, n)
        v = np.linspace(ymin, ymax, n)
        U, V = np.meshgrid(u, v)
        X = cn.x + U * cs - V * sn
        Y = cn.y + U * sn + V * cs
        z = self.hf.sample_tri(X.ravel(), Y.ravel())
        return float(z.max()), float(z.min())

    def site(self, cn, rz, ext, spread=3.0, clear=0.25, min_z=1.2):
        corners = rect(cn, rz, ext)
        if not self.free(corners):
            return None
        if not self.road_clear(corners, clear):
            return None
        hi, lo = self.ground(cn, rz, ext)
        if lo < min_z or hi - lo > spread:
            return None
        return hi, lo, corners

    def claim(self, corners):
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        self.rects.add(corners, min(xs), min(ys), max(xs), max(ys))

    def add(self, asset, pos, rz, district, variant=None, scale=(1, 1, 1), **kw):
        d = {"asset": asset, "variant": variant, "pos": [round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)],
             "rot": round(rz % (2 * math.pi), 5), "scale": [round(s, 4) for s in scale], "district": district}
        d.update(kw)
        self.instances.append(d)
        return d


def district_of(cfg, isl_name, p):
    for d in cfg["districts"]:
        if d["island"] != isl_name:
            continue
        if "center" in d and (p - Vector(d["center"])).length > d["radius"]:
            continue
        return d
    return None


def edge_island(cfg, net, e):
    g = e.a.grid or e.b.grid
    if g is None:
        return None
    return next(x["island"] for x in cfg["grids"] if x["name"] == g)


def variant_weights(cfg, dist, asset):
    """Weights for an asset's texture variants in a district: the world default
    (cfg["variant_weights"]) overridden by the district's own ("variant_weights");
    variants not listed weigh 1. A district can thus be a red-light district
    (love hotels, cabarets) or ad-heavy (corporate crowns) without new meshes."""
    w = dict((cfg.get("variant_weights") or {}).get(asset, {}))
    if dist:
        w.update((dist.get("variant_weights") or {}).get(asset, {}))
    return w


def pick(rng, weights):
    ks = list(weights)
    return rng.choices(ks, [weights[k] for k in ks])[0]


def place_all(cfg, hf, net, masks, bridges, walls, log):
    root = cfg.get("_root", ".")
    rng = random.Random(cfg["seed"] * 31 + 5)
    P = Placer(cfg, hf, net, rng)
    var = variants_on_disk(root)
    last_var = {}
    # variant picks draw from their own stream: adding a variant never moves a building
    vrng = random.Random(cfg["seed"] * 31 + 7)

    def variant(asset, dist=None):
        vs = var.get(asset) or []
        if not vs:
            return None
        w = variant_weights(cfg, dist, asset)
        ws = [max(0.0, float(w.get(x, 1.0))) for x in vs]
        if sum(ws) <= 0:
            ws = [1.0] * len(vs)
        v = vrng.choices(vs, ws)[0]
        if v == last_var.get(asset) and sum(1 for x in ws if x > 0) > 1:
            rest = [(x, k) for x, k in zip(vs, ws) if x != v and k > 0]
            v = vrng.choices([x for x, _ in rest], [k for _, k in rest])[0]
        last_var[asset] = v
        return v
    towers = []
    stats = {}

    def bump(d, k, n=1):
        stats.setdefault(d, {}).setdefault(k, 0)
        stats[d][k] += n

    library = {}

    def tower_spec(district, W, D, Hgt, style):
        """A tower archetype of this district: each district has 10 (seeded),
        so towers are instances of a few shared meshes."""
        lib = library.get(district["name"])
        if lib is None:
            lib = []
            lo, hi = district.get("towers", {}).get("height", [60, 120])
            for k in range(10):
                lib.append(make_tower(rng.choice([24, 28, 32, 36, 40]), rng.choice([24, 28, 32, 36]), lo + (hi - lo) * (k + rng.random()) / 10))
                spec = lib[-1]
                if spec["crown"] == "billboard":
                    # the crown billboard's ad, from the district's list (downtown: corporate ads)
                    ads = district.get("crown_ads") or cfg.get("crown_ads") or []
                    if ads:
                        spec["ad"] = vrng.choice(ads)
                        spec["mesh"] += "_" + spec["ad"].replace("billboard_ad_", "").replace("billboard_", "")
            library[district["name"]] = lib
        return rng.choice(lib)

    def make_tower(W, D, Hgt):
        """A setback tower: 1-3 tiers shrinking upwards."""
        W, D = 4 * round(W / 4), 4 * round(D / 4)
        Hgt = 8 * round(Hgt / 8)
        tiers = []
        h_left = Hgt
        w, d = W, D
        k = rng.random()
        n = 1 if Hgt < 70 else (2 if k < 0.55 else 3)
        for t in range(n):
            th = h_left if t == n - 1 else 8 * round(h_left * rng.uniform(0.45, 0.65) / 8)
            tiers.append([w, d, th])
            h_left -= th
            w, d = max(12, w - 8), max(12, d - 8)
        crown = rng.choice(["flat", "spire", "halo", "billboard"])
        key = f"tower_{W}x{D}x{Hgt}_{'-'.join(str(t[2]) for t in tiers)}_{crown}"
        return {"mesh": key, "tiers": tiers, "height": Hgt, "crown": crown, "footprint": [W, D]}

    def place_tower(dist, cn, rz, spec, style, base, lo, corners, landmark=None):
        P.claim(corners)
        rec = dict(spec)
        rec.update({"id": f"tw{len(towers)}", "pos": [round(cn.x, 2), round(cn.y, 2), round(base, 2)], "rot": round(rz, 5),
                    "facade": style, "district": dist["name"], "landmark": landmark})
        towers.append(rec)
        P.add(spec["mesh"], (cn.x, cn.y, base), rz, dist["name"], variant=style, footing=round(base - lo + 0.8, 2), kind="tower")
        bump(dist["name"], "towers")

    # ---- landmarks (corporate island)
    for dist in cfg["districts"]:
        for lm in dist.get("landmarks", []):
            near = Vector(lm["near"])
            W, D = lm["footprint"]
            done = False
            for r in range(0, 120, 6):
                for a in np.linspace(0, 2 * math.pi, 12, endpoint=False):
                    cn = near + Vector((math.cos(a), math.sin(a))) * r
                    rz = math.radians(next(g["rotation"] for g in cfg["grids"] if g["island"] == dist["island"]))
                    ext = (-W / 2, W / 2, -D / 2, D / 2)
                    st = P.site(cn, rz, ext, spread=2.0, clear=4.0)
                    if st:
                        spec = {"mesh": f"landmark_{lm['name']}", "tiers": [[W, D, lm["height"] * 0.62], [W - 10, D - 10, lm["height"] * 0.26], [W - 20, D - 20, lm["height"] * 0.12]],
                                "height": lm["height"], "crown": lm["variant"], "footprint": [W, D]}
                        place_tower(dist, cn, rz, spec, "glass_dark" if lm["variant"] == "hoshikawa" else "panel_cyan", st[0], st[1], st[2], landmark=lm["name"])
                        done = True
                        break
                if done:
                    break
            log(f"landmark {lm['name']}: {'placed' if done else 'NO SITE'}")

    # ---- frontage along every curbed road (the town's front rows), per district
    edges = [e for e in net.alive_edges() if net.classes[e.cls].get("side", "curb") == "curb" and e.kind == "grid"]
    edges.sort(key=lambda e: -net.classes[e.cls]["half"])           # avenues first
    for e in edges:
        isl = edge_island(cfg, net, e)
        cc = net.classes[e.cls]
        H = cc["half"]
        path = e.path
        for sgn in (1, -1):
            s = 2.0
            while s < path.length - 2.0:
                pos, t = path.at(min(s, path.length))
                dist = district_of(cfg, isl, pos.to_2d())
                if dist is None or dist["style"] == "port":
                    s += 20.0
                    continue
                nout = rot90(t) * sgn
                rz = math.atan2(-nout.x, nout.y)
                placed = False
                tw = dist.get("towers", {})
                if tw.get("density", 0) > 0 and rng.random() < tw["density"]:
                    W = rng.choice([24, 28, 32, 36, 40])
                    D = rng.choice([24, 28, 32, 36])
                    Hgt = rng.uniform(*tw["height"])
                    if dist["style"] == "corporate":
                        Hgt *= 0.9
                    spec = tower_spec(dist, W, D, Hgt, None)
                    W, D = spec["footprint"]
                    for back in (1.5, 3.0):
                        p2, t2 = path.at(min(s + W / 2, path.length))
                        cn = p2.to_2d() + nout * (H + WALK_OUT + back + D / 2)
                        st = P.site(cn, rz, (-W / 2, W / 2, -D / 2, D / 2), spread=2.5, clear=1.0)
                        if st:
                            place_tower(dist, cn, rz, spec, rng.choice(FACADES), st[0], st[1], st[2])
                            s += W + rng.uniform(3.0, 8.0)
                            placed = True
                            break
                if placed:
                    continue
                site = None
                for kind in [pick(rng, dist.get("kit", {"building_a": 1})) for _ in range(4)]:
                    xmin, xmax, ymin, ymax = KIT[kind]["ext"]
                    w = xmax - xmin
                    for back in (0.2, 0.9, 1.8):
                        p2, t2 = path.at(min(s + w / 2, path.length))
                        cn = p2.to_2d() + nout * (WALK_OUT + H + back - ymin)
                        site = P.site(cn, rz, KIT[kind]["ext"], spread=dist.get("spread", 3.0))
                        if site:
                            break
                    if site:
                        break
                if not site:
                    s += 2.0
                    continue
                base, lo, corners = site
                P.claim(corners)
                inst = P.add(kind, (cn.x, cn.y, base), rz, dist["name"], variant=variant(kind, dist), footing=round(base - lo + 0.8, 2), kind="building")
                bump(dist["name"], "buildings")
                if rng.random() < (0.7 if dist["style"] != "corporate" else 0.2):
                    lx = rng.uniform(xmin + 1.2, xmax - 1.2)
                    ly = ymin + 1.2
                    cs, sn = math.cos(rz), math.sin(rz)
                    P.add("overhead_sign", (cn.x + lx * cs - ly * sn, cn.y + lx * sn + ly * cs, base + rng.uniform(4.0, 7.5)), rz, dist["name"],
                          variant=variant("overhead_sign", dist), kind="sign")
                gap = rng.uniform(0.3, 1.2) if dist["style"] in ("dense", "downtown") else rng.uniform(2.0, 9.0)
                if rng.random() < 0.22:
                    gap = rng.uniform(2.6, 4.0)              # alley
                    am = p2.to_2d() + t2 * (w / 2 + gap / 2) + nout * (WALK_OUT + H + 6.0)
                    P_light(P, am, base + 3.2, rng.choice([(0.4, 0.9, 1.0), (1.0, 0.3, 0.6), (1.0, 0.65, 0.35)]), 45, "alley")
                s += w + gap

    # ---- back rows: fill block interiors
    for dist in cfg["districts"]:
        if dist["style"] in ("port",) or dist.get("back_rows", 0) <= 0:
            continue
        isl = next(i for i in cfg["islands"] if i["name"] == dist["island"])
        cx, cy = isl["center"]
        R = max(isl["radius"]) * 1.1
        step = 13.0 if dist["style"] in ("dense", "downtown") else 17.0
        for gy in np.arange(cy - R, cy + R, step):
            for gx in np.arange(cx - R, cx + R, step):
                p = Vector((gx + rng.uniform(-4, 4), gy + rng.uniform(-4, 4)))
                d2 = district_of(cfg, dist["island"], p)
                if d2 is not dist or rng.random() > dist["back_rows"]:
                    continue
                # face the nearest road
                best = None
                for (x, y, w, z) in P.road.query(p.x - 60, p.y - 60, p.x + 60, p.y + 60):
                    dd = math.hypot(x - p.x, y - p.y) - w
                    if best is None or dd < best[0]:
                        best = (dd, x, y)
                if best is None or best[0] < 6.0:
                    continue
                nout = (p - Vector((best[1], best[2])))
                if nout.length < 1e-6:
                    continue
                nout.normalize()
                rz = math.atan2(-nout.x, nout.y) + (rng.choice([0.0, math.pi / 2, -math.pi / 2]) if best[0] > 40 else 0.0)
                tw = dist.get("towers", {})
                if tw.get("density", 0) > 0 and rng.random() < tw["density"] * 0.5:
                    W, D = rng.choice([24, 28, 32]), rng.choice([24, 28, 32])
                    spec = tower_spec(dist, W, D, rng.uniform(*tw["height"]) * 0.85, None)
                    W, D = spec["footprint"]
                    st = P.site(p, rz, (-W / 2, W / 2, -D / 2, D / 2), spread=2.5, clear=1.0)
                    if st:
                        place_tower(dist, p, rz, spec, rng.choice(FACADES), st[0], st[1], st[2])
                        continue
                kind = pick(rng, dist.get("kit", {"building_a": 1}))
                st = P.site(p, rz, KIT[kind]["ext"], spread=dist.get("spread", 3.0) * 2, clear=0.6)
                if st:
                    P.claim(st[2])
                    P.add(kind, (p.x, p.y, st[0]), rz, dist["name"], variant=variant(kind, dist), footing=round(st[0] - st[1] + 0.8, 2), kind="building")
                    bump(dist["name"], "buildings")

    # ---- the port: cranes on the quays, container yards, warehouses, light masts
    port = next((d for d in cfg["districts"] if d["style"] == "port"), None)
    if port:
        place_port(cfg, P, port, walls, rng, bump, log)

    # ---- street props: lamps, poles + wires, signals
    wires = []
    n_lamp = 0
    lamp_sp = cfg["props"]["lamp_spacing"]
    pole_sp = cfg["props"]["pole_spacing"]
    extra = [p for p in cfg["props"].get("extra", []) if p.get("asset") in set(props_on_disk(root))]
    for e in net.alive_edges():
        cc = net.classes[e.cls]
        side = cc.get("side", "curb")
        H = cc["half"]
        path = e.path
        isl = edge_island(cfg, net, e)
        sp = lamp_sp.get(e.cls, 30)
        s, sgn = 7.0 + rng.uniform(0, 6), 1
        while s < path.length - 5:
            pos, t = path.at(s)
            nout = rot90(t) * sgn
            rz = math.atan2(-nout.x, nout.y)
            if side == "curb":
                p = pos.to_2d() + nout * (H + 2.4)
                z = pos.z + WALK_Z
            elif side == "jersey":
                p = pos.to_2d() + nout * (H + 0.25)
                z = pos.z + ROAD_Z + 0.9
            else:
                p = pos.to_2d() + nout * (H + 0.95)
                z = pos.z + ROAD_Z - 0.05
            P.add("street_lamp", (p.x, p.y, z), rz, "roads", kind="lamp")
            lp = p - nout * 2.1
            P_light(P, lp, z + 5.8, LAMP_COLS[n_lamp % 4], 420 if side == "curb" else 520, "lamp")
            n_lamp += 1
            s += sp
            if side == "curb" or e.cls == "highway":
                sgn = -sgn
        ps = pole_sp.get(e.cls, 0)
        if ps:
            s = 12.0
            side_ = 1 if e.id % 2 == 0 else -1
            poles = []
            while s < path.length - 4:
                pos, t = path.at(s)
                nout = rot90(t) * side_
                off = H + 2.65 if side == "curb" else H + 1.6
                p = pos.to_2d() + nout * off
                z = pos.z + (WALK_Z if side == "curb" else ROAD_Z - 0.3)
                if not on_deck(e, s):
                    P.add("power_pole", (p.x, p.y, z), math.atan2(-nout.x, nout.y) + math.pi / 2, "roads", kind="pole")
                    poles.append((p, z, nout))
                s += ps
            for (p0, z0, n0), (p1, z1, n1) in zip(poles, poles[1:]):
                if (p1 - p0).length > ps * 1.6:
                    continue
                for off, h in ((-1.05, 8.55), (-0.35, 8.55), (0.35, 8.55), (1.05, 8.55), (0.0, 7.3)):
                    a = p0 + n0 * off
                    b = p1 + n1 * off
                    wires.append({"a": [round(a.x, 2), round(a.y, 2), round(z0 + h, 2)], "b": [round(b.x, 2), round(b.y, 2), round(z1 + h, 2)],
                                  "sag": round(0.5 + 0.02 * (b - a).length, 2)})
        # props kit hook: scatter whatever the props workstream provides
        scatter_props(P, e, extra, rng)
    log(f"props: {n_lamp} lamps, {len(wires)} wire spans, {len(extra)} extra prop kinds")

    # ---- bridge lights (pylon tops: aviation red; cable LEDs are emissive in the build)
    for br in bridges:
        for py in br["pylons"]:
            P_light(P, Vector(py["pos"]), py["top"] + 1.0, (1.0, 0.05, 0.02), 900, "aviation")

    # ---- tree kit (assets/trees): avenues lined in tree pits before the props, so props keep clear of the pits
    TK = tree_kit(root)
    if TK is not None:
        TK[0].avenue_trees(cfg, P, net, TK[1], hf, log, rot90, edge_island, district_of, on_deck, WALK_Z)

    # ---- street props kit (assets/props) along every curbed road, corners, crossings, rooftops
    scatter_street_props(cfg, P, net, towers, rng, log)
    if TK is not None:
        TK[0].street_swaps(cfg, P, TK[1], log)
        TK[0].park_groves(cfg, P, TK[1], hf, log, rect, district_of)

    # ---- trees on natural land
    place_trees(cfg, P, hf, masks, rng, log)

    # ---- spawn: on a downtown avenue
    spawn = None
    for e in sorted(net.alive_edges(), key=lambda e: e.id):
        if e.cls == "avenue" and e.kind == "grid":
            p, t = e.path.at(e.path.length / 2)
            if district_of(cfg, edge_island(cfg, net, e), p.to_2d()) and district_of(cfg, edge_island(cfg, net, e), p.to_2d())["name"] == "downtown":
                q = p.to_2d() + rot90(t) * 1.75
                spawn = {"pos": [round(q.x, 2), round(q.y, 2), round(p.z + 0.8, 2)], "dir": [round(t.x, 4), round(t.y, 4)], "road": f"r{e.id}"}
                break
    districts = []
    for d in cfg["districts"]:
        districts.append({"name": d["name"], "island": d["island"], "style": d["style"], "center": d.get("center"), "radius": d.get("radius"),
                          "counts": stats.get(d["name"], {})})
    lights = P.lights if hasattr(P, "lights") else []
    log(f"placement: {len(P.instances)} instances, {len(towers)} towers, {len(lights)} lights; " + ", ".join(f"{k}: {v}" for k, v in stats.items()))
    return {"instances": P.instances, "towers": towers, "wires": wires, "lights": lights, "spawn": spawn, "districts": districts}


def on_deck(e, s):
    return bool(np.interp(s, e.s, e.deck.astype(float)) > 0.5)


def P_light(P, p, z, col, energy, kind):
    if not hasattr(P, "lights"):
        P.lights = []
    P.lights.append({"pos": [round(p.x, 2), round(p.y, 2), round(z, 2)], "color": [round(c, 3) for c in col], "energy": energy, "kind": kind})


def scatter_props(P, e, props, rng):
    """Hook for the street-props kit: props = [{"asset", "spacing", "offset"
    (metres beyond the curb line, sidewalk side), "classes": [...],
    "side": "both" | "alternate", "jitter", "face": "road" | "along"}].
    Configure in world_config.json "props.extra"; only assets present in
    assets/props/*.glb are used."""
    cc = P.net.classes[e.cls]
    if cc.get("side", "curb") != "curb":
        return
    for pr in props:
        if e.cls not in pr.get("classes", ["street", "avenue"]):
            continue
        s = rng.uniform(3, pr["spacing"])
        sgn = 1
        while s < e.path.length - 3:
            pos, t = e.path.at(s)
            for side in ((1, -1) if pr.get("side", "both") == "both" else (sgn,)):
                nout = rot90(t) * side
                p = pos.to_2d() + nout * (cc["half"] + pr.get("offset", 1.2))
                rz = math.atan2(-nout.x, nout.y) if pr.get("face", "road") == "road" else math.atan2(t.y, t.x)
                P.add(pr["asset"], (p.x, p.y, pos.z + WALK_Z), rz, "roads", kind="prop")
            sgn = -sgn
            s += pr["spacing"] * rng.uniform(1 - pr.get("jitter", 0.2), 1 + pr.get("jitter", 0.2))


def place_port(cfg, P, dist, walls, rng, bump, log):
    isl = next(i for i in cfg["islands"] if i["name"] == dist["island"])
    rot = math.radians(next(g["rotation"] for g in cfg["grids"] if g["island"] == dist["island"]))
    C = Vector(isl["center"])
    # cranes along the quays, boom over the water
    sp = cfg["port"]["crane_spacing"]
    n_crane = 0
    for w in walls:
        pts = [Vector(p) for p in w["points"]]
        if not pts or (sum(pts, Vector((0, 0))) / len(pts) - C).length > max(isl["radius"]) * 1.4:
            continue
        acc = 0.0
        for a, b in zip(pts, pts[1:]):
            seg = (b - a).length
            while acc <= seg and seg > 1e-6:
                p = a.lerp(b, acc / seg)
                t = (b - a).normalized()
                n = rot90(t)
                if (p + n * 5 - C).length < (p - C).length:
                    n = -n                     # n points to the sea
                q = p - n * 22.0
                rz = math.atan2(n.y, n.x) - math.pi / 2          # local +y -> sea
                ext = (-14.0, 14.0, -9.0, 9.0)
                st = P.site(q, rz, ext, spread=1.5, clear=0.5, min_z=1.0)
                if st:
                    P.claim(st[2])
                    P.add("crane_sts", (q.x, q.y, st[0]), rz, dist["name"], variant=rng.choice(["red", "blue", "white"]), kind="crane")
                    n_crane += 1
                acc += sp
            acc -= seg
    # yards and warehouses on a jittered lattice in the port frame
    ux, uy = Vector((math.cos(rot), math.sin(rot))), Vector((-math.sin(rot), math.cos(rot)))
    n_cont = n_wh = 0
    R = max(isl["radius"])
    cols = ["rust", "blue", "white", "green", "orange", "grey", "teal"]
    for gy in np.arange(-R, R, 34.0):
        for gx in np.arange(-R, R, 70.0):
            c = C + ux * gx + uy * gy
            if rng.random() < cfg["port"]["warehouse_rate"]:
                L, W = rng.choice([(60, 30), (48, 26), (72, 32)])
                Hh = rng.choice([10, 12, 14])
                ext = (-L / 2, L / 2, -W / 2, W / 2)
                st = P.site(c, rot, ext, spread=1.5, clear=2.0)
                if st:
                    P.claim(st[2])
                    P.add(f"warehouse_{L}x{W}x{Hh}", (c.x, c.y, st[0]), rot, dist["name"], variant=rng.choice(["teal", "grey", "rust"]),
                          footing=round(st[0] - st[1] + 0.5, 2), kind="warehouse")
                    n_wh += 1
                    continue
            # a container block: 4 rows x 4 bays, stacked 1-4
            ext = (-27.0, 27.0, -12.0, 12.0)
            st = P.site(c, rot, ext, spread=1.0, clear=2.0)
            if not st:
                continue
            P.claim(st[2])
            for r in range(4):
                for b in range(4):
                    if rng.random() < 0.12:
                        continue
                    lx = -19.5 + b * 13.0
                    ly = -8.4 + r * 5.6
                    h = rng.choice([1, 2, 2, 3, 3, 4])
                    for k in range(h):
                        p = c + ux * lx + uy * ly
                        P.add("container", (p.x, p.y, st[0] + k * 2.6), rot + (math.pi if rng.random() < 0.5 else 0.0), dist["name"],
                              variant=rng.choice(cols), kind="container")
                        n_cont += 1
            P_light(P, c + uy * 14.0, st[0] + 30.0, (1.0, 0.75, 0.5), 2600, "mast")
            P.add("light_mast", ((c + uy * 14.0).x, (c + uy * 14.0).y, st[0]), rot, dist["name"], kind="mast")
    bump(dist["name"], "cranes", n_crane)
    bump(dist["name"], "containers", n_cont)
    bump(dist["name"], "warehouses", n_wh)
    log(f"port: {n_crane} cranes, {n_cont} containers, {n_wh} warehouses")


def tree_kit(root):
    """(tools/trees/tree_placement module, its Kit) when the tree kit is built (assets/trees/index.json)."""
    p = os.path.join(root, "tools", "trees", "tree_placement.py")
    if not os.path.isfile(p) or not os.path.isfile(os.path.join(root, "assets", "trees", "index.json")):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("tree_placement", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    kit = mod.Kit(root)
    return (mod, kit) if kit.ok else None


def place_trees(cfg, P, hf, masks, rng, log):
    """Natural land: with the tree kit, forests / shores / slopes by context (tools/trees/tree_placement.py);
    else the old conifers and broadleaf clumps: away from roads and buildings, slope < 35 deg,
    thinning out towards the summits."""
    from terrain import Perlin
    TK = tree_kit(cfg.get("_root", "."))
    if TK is not None:
        TK[0].nature_trees(cfg, P, hf, masks, TK[1], log, rect, Perlin, P.net, rot90)
        return
    noise = Perlin(cfg["seed"] + 55)
    step = 13.0
    n = 0
    xs = np.arange(-cfg["size_m"] / 2 + 10, cfg["size_m"] / 2 - 10, step)
    X, Y = np.meshgrid(xs, xs)
    X = X + np.array([[rng.uniform(-5, 5) for _ in range(X.shape[1])] for _ in range(X.shape[0])])
    Y = Y + np.array([[rng.uniform(-5, 5) for _ in range(X.shape[1])] for _ in range(X.shape[0])])
    Z = hf.sample_tri(X, Y)
    gx = (hf.sample(X + 2, Y) - hf.sample(X - 2, Y)) / 4
    gy = (hf.sample(X, Y + 2) - hf.sample(X, Y - 2)) / 4
    slope = np.hypot(gx, gy)
    U = masks["urban_flat"]
    ix = np.clip(((X - hf.x0) / hf.cell).astype(int), 0, hf.n - 1)
    iy = np.clip(((Y - hf.x0) / hf.cell).astype(int), 0, hf.n - 1)
    dens = 0.5 + 0.5 * noise(X / 260.0, Y / 260.0)
    ok = (Z > 3.0) & (slope < 0.7) & (U[iy, ix] < 0.3) & (Z < 270) & (dens > 0.35)
    for x, y, z, dn in zip(X[ok], Y[ok], Z[ok], dens[ok]):
        if rng.random() > dn:
            continue
        p = Vector((float(x), float(y)))
        r = 2.0
        corners = rect(p, 0.0, (-r, r, -r, r))
        if not P.free(corners) or not P.road_clear(corners, 1.0):
            continue
        conifer = z > 40 or rng.random() < 0.4
        sc = rng.uniform(0.7, 1.35) * (0.8 if z > 180 else 1.0)
        P.add("tree_pine" if conifer else "tree_broad", (p.x, p.y, float(z) - 0.2), rng.uniform(0, 6.28), "nature", scale=(sc, sc, sc * rng.uniform(0.9, 1.2)), kind="tree")
        n += 1
    log(f"trees: {n}")


# ---------------------------------------------------------------- street props kit (assets/props, tools/props/scatter.py)

PROP_DISTRICT = {"downtown": "downtown", "midtown": "commercial", "old_town": "market", "hillside": "residential",
                 "port": "industrial", "corporate": "luxury", "yoimachi": "market"}
SIGNAL_PROPS = ("traffic_light_pole", "traffic_light_mast", "ped_signal")


def G(x, y, z):
    """Blender (x, y, z up) -> Godot (x, y up, z = -y)."""
    return [round(x, 3), round(z, 3), round(-y, 3)]


def props_kit(root):
    """(scatter module, index) when the props kit is merged, else (None, None)."""
    p = os.path.join(root, "tools", "props", "scatter.py")
    if not os.path.isfile(p) or not os.path.isfile(os.path.join(root, "assets", "props", "index.json")):
        return None, None
    import importlib.util
    spec = importlib.util.spec_from_file_location("props_scatter", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.load_index()


def scatter_street_props(cfg, P, net, towers, rng, log, density_scale=0.8):
    """Dress every district with the props kit: builds one scatter context per
    district (curb / walk / frontage lines along both sides of every curbed
    road, junction corners and crossings, tower rooftops; lamps, poles and
    signals as blocked discs) and adds the placements as instances."""
    sc, index = props_kit(cfg.get("_root", "."))
    if sc is None:
        log("props kit not found (assets/props): street props skipped")
        return 0
    names = [n for n in index["props"] if n not in SIGNAL_PROPS]
    ctx = {}

    def C(dname):
        if dname not in ctx:
            ctx[dname] = {"seed": cfg["seed"] + len(ctx) * 101, "district": PROP_DISTRICT.get(dname, "commercial"),
                          "lines": [], "points": [], "areas": [], "blocked": []}
        return ctx[dname]
    blocked_kinds = ("lamp", "pole", "signal", "mast", "tree")
    for i in P.instances:
        if i.get("kind") in blocked_kinds:
            x, y, z = i["pos"]
            d = i.get("district")
            # roads-district street furniture blocks every context near it (cheap: add to all later)
            P.__dict__.setdefault("_blocked", []).append({"pos": G(x, y, z), "radius": 1.6 if i.get("kind") == "tree" else 1.1})
    for e in net.alive_edges():
        cc = net.classes[e.cls]
        if cc.get("side", "curb") != "curb" or e.kind != "grid":
            continue
        isl = edge_island(cfg, net, e)
        path = e.path
        L = path.length
        if L < 16:
            continue
        mid, _ = path.at(L / 2)
        dist = district_of(cfg, isl, mid.to_2d())
        if dist is None:
            continue
        c = C(dist["name"])
        H = cc["half"]
        s = np.linspace(3.0, L - 3.0, max(2, int((L - 6.0) / 4.0) + 1))
        pos, t = path.at_many(s)
        if any(np.interp(s, e.s, e.deck.astype(float)) > 0.5):
            continue
        for sgn in (1, -1):
            nrm = np.stack([-t[:, 1], t[:, 0]], 1) * sgn
            for slot, off in (("curb", H + 0.75), ("walk", H + 1.7), ("frontage", H + 2.75)):
                pts = [G(p[0] + n[0] * off, p[1] + n[1] * off, p[2] + WALK_Z) for p, n in zip(pos, nrm)]
                c["lines"].append({"slot": slot, "points": pts, "toward": [round(float(mid.x), 2), round(float(-mid.y), 2)]})
    for nd in net.alive_nodes():
        J = nd.J
        if J is None or nd.kind != "junction" or not nd.grid:
            continue
        isl = next(g["island"] for g in cfg["grids"] if g["name"] == nd.grid)
        dist = district_of(cfg, isl, nd.pos)
        if dist is None:
            continue
        c = C(dist["name"])
        for cr in J.corners:
            if "C" not in cr or not cr["concave"]:
                continue
            line = J.corner_line(cr, 1.2)
            m = J.pos + line[len(line) // 2]
            into = (J.pos - m).normalized()
            a, b = J.dirs[cr["ia"]], J.dirs[cr["ib"]]
            c["points"].append({"slot": "corner", "pos": G(m.x, m.y, J.z + WALK_Z), "dir": [round(into.x, 4), round(-into.y, 4)],
                                "curbs": [[round(a.x, 4), round(-a.y, 4)], [round(b.x, 4), round(-b.y, 4)]]})
        for k, d in enumerate(J.dirs):
            nrm = rot90(d)
            for sgn in (1, -1):
                p = J.pos + d * (J.L[k] - 2.7) + nrm * sgn * (J.half[k] + 0.8)
                into = -nrm * sgn
                c["points"].append({"slot": "crossing", "pos": G(p.x, p.y, J.z + WALK_Z), "dir": [round(into.x, 4), round(-into.y, 4)]})
    for tw in towers:
        dname = tw["district"]
        w, d_, _ = tw["tiers"][-1]
        cn = Vector(tw["pos"][:2])
        rz = tw["rot"]
        top = tw["pos"][2] + sum(t_[2] for t_ in tw["tiers"])
        poly = [G(q.x, q.y, top) for q in rect(cn, rz, (-w / 2 + 2, w / 2 - 2, -d_ / 2 + 2, d_ / 2 - 2))]
        C(dname)["areas"].append({"slot": "rooftop", "polygon": poly})
    blocked = P.__dict__.get("_blocked", [])
    n = 0
    stats = {}
    for dname, c in ctx.items():
        # only the blocked discs near this district's lines
        xs = [p[0] for l in c["lines"] for p in l["points"][::4]]
        zs = [p[2] for l in c["lines"] for p in l["points"][::4]]
        if xs:
            x0, x1, z0, z1 = min(xs) - 10, max(xs) + 10, min(zs) - 10, max(zs) + 10
            c["blocked"] = [b for b in blocked if x0 <= b["pos"][0] <= x1 and z0 <= b["pos"][2] <= z1]
        out = sc.scatter_props(c, names, density_scale=density_scale)
        dcfg = next((d for d in cfg["districts"] if d["name"] == dname), None)
        prng = random.Random(cfg["seed"] * 17 + len(dname))
        for pl in out:
            # district ad mix: re-pick the prop's variant with the district's weights (bus-stop ads, holo loops, kiosk screens)
            pw = variant_weights(cfg, dcfg, pl["prop"]) if dcfg else {}
            pv = ((index["props"].get(pl["prop"]) or {}).get("variants") or [])
            if pw and pv:
                names_v = [v["name"] for v in pv]
                ws = [max(0.0, float(pw.get(n_, 1.0))) for n_ in names_v]
                if sum(ws) > 0:
                    pl["variant"] = prng.choices(names_v, ws)[0]
            gx, gy, gz = pl["pos"]
            P.add(pl["prop"], (gx, -gz, gy), pl["yaw"], dname, variant=pl.get("variant") if pl.get("variant") != "default" else None,
                  scale=pl.get("scale", (1, 1, 1)), kind="prop", slot=pl.get("slot"), file="assets/props/" + pl["file"])
            stats[pl["prop"]] = stats.get(pl["prop"], 0) + 1
            n += 1
    log(f"street props: {n} from the props kit in {len(ctx)} districts; top: " +
        ", ".join(f"{k} {v}" for k, v in sorted(stats.items(), key=lambda kv: -kv[1])[:8]))
    return n


def signal_instances(cfg, signals, juncs, place, log):
    """Traffic lights at the signalised (avenue) junctions: a mast signal per
    approach (arm over the incoming lanes, heads facing the traffic) and a
    pedestrian signal at both ends of every crosswalk. Uses the props kit's
    traffic_light_mast / ped_signal when present, else the procedural pole."""
    have = os.path.isfile(os.path.join(cfg.get("_root", "."), "assets", "props", "traffic_light_mast.glb"))
    n = 0
    for sg in signals:
        d = Vector(sg["facing"]) * -1.0
        nrm = Vector((-d.y, d.x))
        asset = "traffic_light_mast" if have else ("signal_pole_long" if sg["mast"] > 7.0 else "signal_pole")
        rz = math.atan2(nrm.y, nrm.x) % (2 * math.pi)
        rec = {"asset": asset, "variant": None, "pos": sg["pos"], "rot": round(rz, 5), "scale": [1, 1, 1],
               "district": "roads", "kind": "signal", "signal": sg["id"]}
        if have:
            rec["file"] = "assets/props/traffic_light_mast.glb"
        place["instances"].append(rec)
        sg["prop"] = asset
        sg["heads"] = ["A", "B", "C"] if have else ["A"]
        n += 1
    nped = 0
    if have:
        for j in juncs:
            if not j.get("signalised"):
                continue
            for a in j["arms"]:
                d = Vector(a["dir"])
                nrm = Vector((-d.y, d.x))
                for sgn in (1, -1):
                    p = Vector(j["pos"][:2]) + d * (a["length"] - 2.7) + nrm * sgn * (a["half_width"] + 1.2)
                    face = -nrm * sgn                    # across the crosswalk
                    rz = math.atan2(face.x, -face.y)     # local -y (glTF +Z front) onto face
                    place["instances"].append({"asset": "ped_signal", "variant": None, "pos": [round(p.x, 2), round(p.y, 2), round(j["z"] + WALK_Z, 2)],
                                               "rot": round(rz % (2 * math.pi), 5), "scale": [1, 1, 1], "district": "roads", "kind": "signal",
                                               "file": "assets/props/ped_signal.glb", "junction": j["id"], "arm": a["index"]})
                    j.setdefault("ped_signals", []).append({"arm": a["index"], "pos": [round(p.x, 2), round(p.y, 2), round(j["z"] + WALK_Z, 2)],
                                                            "facing": [round(face.x, 4), round(face.y, 4)]})
                    nped += 1
    log(f"signals: {n} approach signals ({'props kit' if have else 'procedural'}), {nped} pedestrian signals")
