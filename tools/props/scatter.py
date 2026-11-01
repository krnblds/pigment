"""Scatter street props over a world layout (pure Python, no dependencies, deterministic).

    from tools.props.scatter import scatter_props        # or sys.path.insert(0, "tools/props")
    placements = scatter_props(context)                    # rules default to assets/props/index.json

All coordinates are glTF / Godot world space: metres, +Y up.  A prop's front is its +Z;
yaw (radians, about +Y) turns +Z onto the wanted front: yaw = atan2(front.x, front.z).

context = {
  "seed": 7,
  "district": "commercial",                  # default district (see catalog.DISTRICTS)
  "lines": [                                 # polylines along which props are placed
    {"slot": "curb", "points": [[x, y, z], ...], "district": "market",
     "side": 1,                              # front = side * (up x tangent) = side * (t.z, 0, -t.x)
     "toward": [x, z]},                      # ...or: front = the side facing this point (overrides side)
    {"slot": "alley_span", "points": [...], "width": 6.5},   # alley centreline + wall-to-wall width
    ...],                                    # slots: curb walk frontage facade roadside median alley alley_span
  "points": [                                # junction corners / crossing ends
    {"slot": "corner", "pos": [x, y, z], "dir": [dx, dz], "district": ...}],  # dir: from the walk into the road
  "areas": [                                 # rooftop / plaza / road polygons (y = height of the area)
    {"slot": "rooftop", "polygon": [[x, y, z], ...], "district": ...}],
  "blocked": [{"pos": [x, y, z], "radius": 1.5}],   # doors, driveways, lamps already placed...
}

rules: None (everything in the index), a list of prop names, or {name: partial rule} to
override fields of the index's scatter rules (e.g. {"bench": {"density": {"default": 3}}}).

Returns a list of placements:
  {"prop", "file", "lod1", "pos": [x, y, z], "yaw", "scale": [sx, sy, sz], "variant",
   "slot", "district", "collider", "xform": [basis x, y, z columns, origin] (12 floats, Godot)}

    python tools/props/scatter.py --demo      # scatter a synthetic crossroads, print a summary
"""
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
INDEX = os.path.join(ROOT, "assets", "props", "index.json")

LINE_SLOTS = {"curb", "walk", "frontage", "facade", "roadside", "median", "alley", "alley_span"}
POINT_SLOTS = {"corner", "crossing"}
AREA_SLOTS = {"rooftop", "plaza", "road"}


def load_index(path=INDEX):
    if os.path.exists(path):
        with open(path, encoding="utf8") as f:
            return json.load(f)
    import sys
    sys.path.insert(0, HERE)
    import catalog
    return {"props": {n: {"scatter": p["scatter"], "files": {"lod0": f"{n}.glb"}, "footprint": {"w": 1.0, "d": 1.0, "radius": 0.7},
                          "variants": [{"name": "default", "default": True}], "collider": {"type": "box"}} for n, p in catalog.PROPS.items()}}


# ------------------------------------------------------------------ geometry helpers

def _seg_lengths(pts):
    out = [0.0]
    for a, b in zip(pts, pts[1:]):
        out.append(out[-1] + math.dist((a[0], a[2]), (b[0], b[2])))
    return out


def _at(pts, cum, s):
    """Point and unit tangent (x, z) at arc length s."""
    for i in range(len(pts) - 1):
        if cum[i + 1] >= s or i == len(pts) - 2:
            a, b = pts[i], pts[i + 1]
            L = max(cum[i + 1] - cum[i], 1e-9)
            t = min(max((s - cum[i]) / L, 0.0), 1.0)
            p = [a[k] + (b[k] - a[k]) * t for k in range(3)]
            tx, tz = (b[0] - a[0]) / L, (b[2] - a[2]) / L
            return p, (tx, tz)
    return list(pts[-1]), (1.0, 0.0)


def _in_poly(x, z, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i][0], poly[i][2]
        x2, z2 = poly[(i + 1) % n][0], poly[(i + 1) % n][2]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-12) + x1:
            inside = not inside
    return inside


def _poly_area(poly):
    a = 0.0
    for i in range(len(poly)):
        x1, z1 = poly[i][0], poly[i][2]
        x2, z2 = poly[(i + 1) % len(poly)][0], poly[(i + 1) % len(poly)][2]
        a += x1 * z2 - x2 * z1
    return abs(a) / 2


def xform(pos, yaw, scale=(1, 1, 1)):
    c, s = math.cos(yaw), math.sin(yaw)
    sx, sy, sz = scale
    return [round(v, 5) for v in (c * sx, 0.0, -s * sx, 0.0, sy, 0.0, s * sz, 0.0, c * sz, pos[0], pos[1], pos[2])]


class _Grid:
    """Spatial hash of placed discs."""

    def __init__(self, cell=4.0):
        self.cell = cell
        self.d = {}

    def _k(self, x, z):
        return (int(math.floor(x / self.cell)), int(math.floor(z / self.cell)))

    def add(self, x, z, r, tag):
        self.d.setdefault(self._k(x, z), []).append((x, z, r, tag))

    def near(self, x, z, r):
        n = int(math.ceil((r + 6.0) / self.cell))
        kx, kz = self._k(x, z)
        for i in range(kx - n, kx + n + 1):
            for j in range(kz - n, kz + n + 1):
                yield from self.d.get((i, j), ())


# ------------------------------------------------------------------ main entry

def scatter_props(context, rules=None, *, index=None, seed=None, density_scale=1.0):
    idx = index or load_index()
    props = idx["props"]
    if rules is None:
        names = list(props)
        over = {}
    elif isinstance(rules, (list, tuple, set)):
        names, over = [n for n in rules if n in props], {}
    else:
        names, over = [n for n in rules if n in props], rules
    R = {}
    for n in names:
        r = dict(props[n]["scatter"])
        r.update(over.get(n, {}) if isinstance(over.get(n), dict) else {})
        R[n] = r
    rnd = random.Random(context.get("seed", 0) if seed is None else seed)
    default_d = context.get("district", "default")
    grid = _Grid()
    same = {}            # prop -> _Grid for its own spacing
    out = []
    last_variant = {}
    for b in context.get("blocked", []):
        grid.add(b["pos"][0], b["pos"][2], b.get("radius", 1.0), ("blocked", -1))
    cluster_id = [0]

    def dens(rule, district):
        d = rule.get("density", {})
        return float(d.get(district, d.get("default", 0.0))) * density_scale

    def radius(name, rule):
        fp = props[name].get("footprint", {})
        return rule.get("clearance") if rule.get("clearance") is not None else 0.8 * fp.get("radius", 0.5)

    def free(name, rule, x, z, r, cid):
        for (px, pz, pr, tag) in grid.near(x, z, r):
            if tag[1] == cid and cid >= 0:
                continue
            if math.hypot(px - x, pz - z) < r + pr:
                return False
        sp = rule.get("spacing", 0.0)
        if sp > 0 and name in same:
            for (px, pz, pr, tag) in same[name].near(x, z, sp):
                if tag[1] == cid and cid >= 0:
                    continue
                if math.hypot(px - x, pz - z) < sp:
                    return False
        return True

    def pick_variant(name):
        vs = props[name].get("variants") or [{"name": "default", "default": True}]
        if len(vs) == 1:
            return vs[0]["name"]
        choices = [v["name"] for v in vs if v["name"] != last_variant.get(name)]
        weights = [2.0 if any(v["name"] == c and v.get("default") for v in vs) else 1.0 for c in choices]
        v = rnd.choices(choices, weights)[0]
        last_variant[name] = v
        return v

    def place(name, rule, pos, yaw, slot, district, cid=-1, scale=(1, 1, 1), variant=None):
        r = radius(name, rule)
        if not free(name, rule, pos[0], pos[2], r, cid):
            return False
        grid.add(pos[0], pos[2], r, (name, cid))
        same.setdefault(name, _Grid(8.0)).add(pos[0], pos[2], 0.0, (name, cid))
        p = props[name]
        out.append({"prop": name, "file": p["files"]["lod0"], "lod1": p["files"].get("lod1"), "pos": [round(v, 4) for v in pos],
                    "yaw": round(yaw, 5), "scale": list(scale), "variant": variant or pick_variant(name), "slot": slot, "district": district,
                    "collider": p.get("collider", {}).get("type", "box"), "xform": xform(pos, yaw, scale)})
        return True

    def yaw_for(rule, front, tangent):
        f = rule.get("facing", "road")
        if f == "random":
            y = rnd.uniform(-math.pi, math.pi)
        elif f == "wall":
            y = math.atan2(-front[0], -front[1])
        elif f == "along":       # the prop's X axis along the line, front to either side
            y = math.atan2(front[0], front[1]) + (math.pi if rnd.random() < 0.5 else 0.0)
        else:
            y = math.atan2(front[0], front[1])
        return y + math.radians(rnd.uniform(-1, 1) * rule.get("yaw_jitter", 0))

    # ---------------- lines
    for li, line in enumerate(context.get("lines", [])):
        slot = line["slot"]
        pts = line["points"]
        if len(pts) < 2:
            continue
        district = line.get("district", default_d)
        cum = _seg_lengths(pts)
        L = cum[-1]
        for name in names:
            rule = R[name]
            if slot not in rule.get("slots", []):
                continue
            d = dens(rule, district)
            if d <= 0:
                continue
            fp = props[name].get("footprint", {})
            run = rule.get("run")
            tile = props[name].get("tile_length", fp.get("w", 1.0))
            step = 100.0 / d
            s = rnd.uniform(0, step)
            while s < L:
                p, (tx, tz) = _at(pts, cum, s)
                side = line.get("side", 1)
                n = (tz * side, -tx * side)
                if "toward" in line:
                    q = line["toward"]
                    if (q[0] - p[0]) * n[0] + (q[1] - p[2]) * n[1] < 0:
                        n = (-n[0], -n[1])
                cl = rule.get("cluster", [1, 1])
                count = rnd.randint(cl[0], cl[1]) if not run else rnd.randint(max(2, cl[0]), max(3, cl[1] if cl[1] > 1 else 8))
                cluster_id[0] += 1
                cid = cluster_id[0]
                gap = tile if run else rule.get("cluster_gap", fp.get("w", 1.0) + 0.25)
                yaw0 = yaw_for(rule, n, (tx, tz))
                variant = None
                for k in range(count):
                    sk = s + k * gap
                    if sk > L:
                        break
                    pk, (tkx, tkz) = _at(pts, cum, sk)
                    off = rule.get("offset", 0.0)
                    if slot == "alley_span":
                        width = line.get("width", props[name].get("span", 8.0))
                        mh = rule.get("mount_height", [5.0, 6.0])
                        pos = [pk[0], pk[1] + rnd.uniform(*mh), pk[2]]
                        yaw = math.atan2(tkx, tkz) + math.radians(rnd.uniform(-8, 8))
                        sc = (round(width / props[name].get("span", 8.0), 4), 1, 1)
                        place(name, rule, pos, yaw, slot, district, cid, scale=sc)
                        continue
                    pos = [pk[0] + n[0] * off, pk[1], pk[2] + n[1] * off]
                    if not run and rule.get("cluster_line") is None and k:
                        a = rnd.uniform(0, math.tau)
                        rr = rule.get("cluster_radius", 1.0) * math.sqrt(rnd.random())
                        pos = [p[0] + n[0] * off + math.cos(a) * rr, p[1], p[2] + n[1] * off + math.sin(a) * rr]
                    if slot == "facade":
                        mh = rule.get("mount_height", [3.0, 4.0])
                        pos[1] += rnd.uniform(*mh)
                    yaw = yaw0 if (run or rule.get("cluster_line")) else yaw_for(rule, n, (tkx, tkz))
                    if run:
                        # chain along the line: X axis along the tangent, tile centres one tile apart
                        yaw = math.atan2(n[0], n[1])
                    if variant is None or not run:
                        variant = pick_variant(name)
                    if not place(name, rule, pos, yaw, slot, district, cid, variant=variant) and run:
                        break
                s += step * rnd.uniform(0.6, 1.4) + (count - 1) * gap

    # ---------------- points
    for pt in context.get("points", []):
        slot = pt["slot"]
        district = pt.get("district", default_d)
        P = pt["pos"]
        dx, dz = pt["dir"]
        L = math.hypot(dx, dz) or 1.0
        dx, dz = dx / L, dz / L
        for name in names:
            rule = R[name]
            if slot not in rule.get("slots", []):
                continue
            if rnd.random() >= min(1.0, dens(rule, district)):
                continue
            a0, a1 = rule.get("along", [0.8, 2.0])
            for _ in range(4):
                side = rnd.choice((-1, 1))
                a = rnd.uniform(a0, a1)
                off = rule.get("offset", -0.5)
                pos = [P[0] + (-dz) * side * a + dx * off, P[1], P[2] + dx * side * a + dz * off]
                if rule.get("facing") == "random":
                    yaw = rnd.uniform(-math.pi, math.pi)
                else:
                    yaw = math.atan2(dx, dz) + math.radians(rnd.uniform(-1, 1) * rule.get("yaw_jitter", 0))
                if place(name, rule, pos, yaw, slot, district):
                    break

    # ---------------- areas
    for ar in context.get("areas", []):
        slot = ar["slot"]
        district = ar.get("district", default_d)
        poly = ar["polygon"]
        area = _poly_area(poly)
        y = sum(p[1] for p in poly) / len(poly)
        xs, zs = [p[0] for p in poly], [p[2] for p in poly]
        for name in names:
            rule = R[name]
            if slot not in rule.get("slots", []):
                continue
            n = dens(rule, district) * area / 100.0
            count = int(n) + (1 if rnd.random() < n - int(n) else 0)
            margin = props[name].get("footprint", {}).get("radius", 0.5)
            for _ in range(count):
                for _try in range(12):
                    x, z = rnd.uniform(min(xs), max(xs)), rnd.uniform(min(zs), max(zs))
                    if not _in_poly(x, z, poly):
                        continue
                    if any(not _in_poly(x + ox, z + oz, poly) for ox, oz in ((margin, 0), (-margin, 0), (0, margin), (0, -margin))):
                        continue
                    yaw = rnd.uniform(-math.pi, math.pi) if rule.get("facing", "random") in ("random", "road") else 0.0
                    lift = 0.012 if rule.get("decal") else 0.0
                    if place(name, rule, [x, y + lift, z], yaw, slot, district):
                        break
    return out


def summary(placements):
    c = {}
    for p in placements:
        c[p["prop"]] = c.get(p["prop"], 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def demo_context(seed=7, district="commercial"):
    """A 4-way crossroads, 12 m roads, 4 m sidewalks, 60 m arms, roof + plaza areas."""
    lines, points, areas = [], [], []
    R, W, A = 6.0, 4.0, 60.0
    for sx in (-1, 1):
        for sz in (-1, 1):
            # sidewalk quadrant (sx, sz): curb lines along both arms, frontage lines behind
            lines.append({"slot": "curb", "points": [[sx * (R + 1.0), 0.15, sz * R], [sx * A, 0.15, sz * R]], "toward": [sx * 30, 0], "district": district})
            lines.append({"slot": "curb", "points": [[sx * R, 0.15, sz * (R + 1.0)], [sx * R, 0.15, sz * A]], "toward": [0, sz * 30], "district": district})
            lines.append({"slot": "frontage", "points": [[sx * (R + W + 1), 0.15, sz * (R + W)], [sx * A, 0.15, sz * (R + W)]], "toward": [sx * 30, 0], "district": district})
            lines.append({"slot": "frontage", "points": [[sx * (R + W), 0.15, sz * (R + W + 1)], [sx * (R + W), 0.15, sz * A]], "toward": [0, sz * 30], "district": district})
            lines.append({"slot": "facade", "points": [[sx * (R + W + 1), 0.15, sz * (R + W)], [sx * A, 0.15, sz * (R + W)]], "toward": [sx * 30, 0], "district": district})
            lines.append({"slot": "walk", "points": [[sx * (R + 1.5), 0.15, sz * (R + 2)], [sx * A, 0.15, sz * (R + 2)]], "toward": [sx * 30, 0], "district": district})
            points.append({"slot": "corner", "pos": [sx * R, 0.15, sz * R], "dir": [-sx, -sz], "district": district})
            for k in (1, 2):
                points.append({"slot": "crossing", "pos": [sx * (R + 1.5), 0.15, sz * R] if k == 1 else [sx * R, 0.15, sz * (R + 1.5)],
                               "dir": [0, -sz] if k == 1 else [-sx, 0], "district": district})
            areas.append({"slot": "rooftop", "polygon": [[sx * 12, 14, sz * 12], [sx * 30, 14, sz * 12], [sx * 30, 14, sz * 30], [sx * 12, 14, sz * 30]],
                          "district": district})
    areas.append({"slot": "road", "polygon": [[-A, 0, -R], [A, 0, -R], [A, 0, R], [-A, 0, R]], "district": district})
    lines.append({"slot": "roadside", "points": [[-A, 0, -R + 0.3], [-R - 3, 0, -R + 0.3]], "side": -1, "district": district})
    lines.append({"slot": "alley_span", "points": [[R + W + 0.5, 0.15, 30], [R + W + 0.5, 0.15, 55]], "width": 6.0, "district": district})
    return {"seed": seed, "district": district, "lines": lines, "points": points, "areas": areas,
            "blocked": [{"pos": [sx * (R + 0.6), 0.15, sz * 20], "radius": 0.6} for sx in (-1, 1) for sz in (-1, 1)]}


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        for dist in ("downtown", "market", "slum", "luxury"):
            pl = scatter_props(demo_context(7, dist))
            print(f"{dist:10s} {len(pl):4d} props  {summary(pl)}")
        a = scatter_props(demo_context(7, "market"))
        b = scatter_props(demo_context(7, "market"))
        assert a == b, "not deterministic"
        print("deterministic: ok")
