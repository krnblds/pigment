"""Procedural tree generator: recursive branches + alpha-tested leaf cards.

Pure Python + numpy (no bpy): tools/trees/build_trees.py turns the result into
Blender meshes / glbs; tests run it in plain Python.

    from treegen import grow, build_lod
    sk = grow("zelkova", variant=1)              # deterministic skeleton per (species, variant)
    m0 = build_lod(sk, 0, cells)                 # LOD0: tubes + folded cards
    m1 = build_lod(sk, 1, cells)                 # LOD1: fewer sides, fewer bigger flat cards

Coordinates: Blender, metres, z up, the tree's root at the origin, front -Y.

Per-vertex attributes (for the Godot wind shader, tools/trees/README in NOTES):
    color.r   branch flex: 0 on the trunk, rising along branches and twigs
    color.g   phase: one random value per scaffold (its whole sub-tree and cards)
    color.b   leaf flutter: 0 at a card's stem, 1 at its tip (0 on bark)
    color.a   crown occlusion: dark inside the crown, 1 on the outside
    uv2.x     height / tree height (0..1): the main trunk bend
    uv2.y     1 on leaf cards, 0 on bark
"""
import math
import zlib

import numpy as np

from species import SPECIES, PLANTER_SHRUBS, BARK, LEAF_CELLS

UP = np.array([0.0, 0.0, 1.0])


# ------------------------------------------------------------------ small vector helpers
def _norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _rot(v, axis, ang):
    """Rodrigues rotation of v about the unit axis by ang radians."""
    c, s = math.cos(ang), math.sin(ang)
    return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1 - c)


def _perp(t):
    ref = np.array([1.0, 0.0, 0.0]) if abs(t[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    n = _norm(np.cross(t, ref))
    n = _norm(np.cross(n, t)) if abs(t[2]) > 0.95 else n
    if abs(t[2]) > 0.95:          # near vertical: a fixed compass frame (x east), so phyllotaxis reads as azimuth
        n = _norm(np.array([1.0, 0.0, 0.0]) - t * t[0])
    b = np.cross(t, n)
    return n, b


def envelope(shape, r):
    """Crown envelope (Weber & Penn shape ratio); r = 0 at the crown base, 1 at the top."""
    w = 1.0 - min(max(r, 0.0), 1.0)
    if shape == "conical":
        return 0.15 + 0.85 * w
    if shape == "spherical":
        return 0.2 + 0.8 * math.sin(math.pi * w)
    if shape == "hemispherical":
        return 0.25 + 0.75 * math.sin(0.5 * math.pi * w)
    if shape == "cylindrical":
        return 1.0
    if shape == "tapered":
        return 0.45 + 0.55 * w
    if shape == "flame":
        return w / 0.7 if w <= 0.7 else (1.0 - w) / 0.3
    if shape == "inverse":
        return 1.0 - 0.8 * w
    if shape == "tend_flame":
        return 0.5 + 0.5 * w / 0.7 if w <= 0.7 else 0.5 + 0.5 * (1.0 - w) / 0.3
    return 1.0


def seed_of(species, variant):
    return zlib.crc32(f"{species}:{variant}".encode()) & 0x7FFFFFFF


# ------------------------------------------------------------------ skeleton
class Branch:
    __slots__ = ("level", "pts", "rad", "length", "parent", "t0", "phase", "flex0", "dirs", "children", "leafy", "cum")

    def __init__(self, level, pts, rad, parent=None, t0=0.0, phase=0.0, flex0=0.0):
        self.level = level
        self.pts = np.asarray(pts, float)
        self.rad = np.asarray(rad, float)
        seg = np.linalg.norm(np.diff(self.pts, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])
        d = np.diff(self.pts, axis=0)
        d = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        self.dirs = np.vstack([d, d[-1:]])
        self.parent, self.t0, self.phase, self.flex0 = parent, t0, phase, flex0
        self.children = []
        self.leafy = False

    def at(self, t):
        """(point, direction, radius) at fraction t of the length."""
        s = min(max(t, 0.0), 1.0) * self.length
        i = int(np.searchsorted(self.cum, s, side="right") - 1)
        i = min(max(i, 0), len(self.pts) - 2)
        f = (s - self.cum[i]) / max(self.cum[i + 1] - self.cum[i], 1e-9)
        p = self.pts[i] * (1 - f) + self.pts[i + 1] * f
        r = self.rad[i] * (1 - f) + self.rad[i + 1] * f
        return p, self.dirs[i], r


class Skeleton:
    def __init__(self, species, variant, params):
        self.species, self.variant, self.p = species, variant, params
        self.branches = []
        self.height = 0.0
        self.trunk = None
        self.cards = []          # (pos, u, n, size_w, size_h, cell, flex, phase, mode, droop)
        self.wind = np.array([1.0, 0.0, 0.0])
        self.collider = None
        self.crown_c = np.zeros(3)
        self.crown_r = np.ones(3)


def _grow_branch(rng, p0, d0, length, r0, r1, seg, curve, wobble, gravity, level, wind=None, sweep=0.0, ground=True):
    n = max(2, int(math.ceil(length / seg)))
    step = length / n
    pts, d = [np.array(p0, float)], _norm(np.array(d0, float))
    bend = math.radians(curve) / n
    for i in range(n):
        k = np.cross(d, UP)
        if np.linalg.norm(k) > 1e-6 and bend != 0.0:
            d = _rot(d, _norm(k), bend)
        if wobble > 0:
            ax = _norm(np.cross(d, rng.normal(size=3)))
            d = _rot(d, ax, math.radians(rng.normal(0.0, wobble) * math.sqrt(step)))
        if gravity != 0.0:
            thin = 1.0 / (1.0 + (r0 * (1 - i / n) + r1 * i / n) / 0.06)
            d = _norm(d - UP * gravity * step * 0.12 * (0.5 + thin))
        if wind is not None and sweep:
            d = _norm(d + wind * sweep * step / max(length, 1.0) * 1.2)
        p = pts[-1] + d * step
        if ground and p[2] < 0.15 and level > 0:
            p[2] = 0.15 + (0.15 - p[2]) * 0.2
            d[2] = abs(d[2])
        pts.append(p)
    t = np.linspace(0.0, 1.0, n + 1)
    rad = r0 * (1 - t) ** 0.85 + r1 * t
    return np.array(pts), np.maximum(rad, 0.0035)


def grow(species, variant=0, overrides=None):
    """The deterministic skeleton (branches + card anchors) of one variant."""
    P = dict(SPECIES[species])
    if overrides:
        P.update(overrides)
    rng = np.random.default_rng(seed_of(species, variant))
    sk = Skeleton(species, variant, P)
    if "shrub" in P:
        return _grow_shrub(sk, P, rng)
    H = float(rng.uniform(*P["height"]))
    sk.height = H
    az = rng.uniform(0, 2 * math.pi)
    sk.wind = np.array([math.cos(az), math.sin(az), 0.0])
    T = P["trunk"]
    r0 = P["trunk_radius"] * (H / 10.0) ** 0.8
    lean = math.radians(T.get("lean", 0) * rng.uniform(0.5, 1.0))
    d0 = _norm(UP * math.cos(lean) + sk.wind * math.sin(lean))
    tl = T["length"] * H
    # finer rings near the ground for the root flare
    tp, tr = _grow_branch(rng, (0, 0, -0.35), d0, tl + 0.35, r0, r0 * T.get("tip", 0.12 if not T.get("split") else 0.7),
                          T["seg"], 0.0, T.get("wobble", 4), -T.get("upright", 0.0), 0, wind=sk.wind, sweep=T.get("sweep", 0.0), ground=False)
    if T.get("taper"):           # palms: nearly cylindrical
        t = np.linspace(0, 1, len(tr))
        tr = r0 * (1 - T["taper"] * t)
    tp = _refine_base(tp)
    tr = np.interp(np.linspace(0, 1, len(tp)), np.linspace(0, 1, len(tr)), tr) if len(tr) != len(tp) else tr
    trunk = Branch(-1, tp, tr, phase=0.0)
    sk.trunk = trunk
    sk.branches.append(trunk)
    hosts = [trunk]
    split = T.get("split")
    if split:
        hosts = []
        top, tdir, trad = trunk.at(1.0)
        nl = int(rng.integers(split["n"][0], split["n"][1] + 1))
        a0 = rng.uniform(0, 2 * math.pi)
        for k in range(nl):
            phi = a0 + 2 * math.pi * k / nl + rng.normal(0, 0.25)
            ang = math.radians(rng.uniform(*split["angle"]))
            dirv = _norm(tdir * math.cos(ang) + np.array([math.cos(phi), math.sin(phi), 0.0]) * math.sin(ang))
            L = split["length"] * (H - top[2]) / max(math.cos(ang), 0.4) * rng.uniform(0.85, 1.05)
            pts, rad = _grow_branch(rng, top - tdir * trad * 0.5, dirv, L, trad * split["radius"] * rng.uniform(0.85, 1.05),
                                    0.02, P["levels"][0]["seg"], split.get("curve", 0), 6, 0.0, 0)
            b = Branch(-1, pts, rad, parent=trunk, t0=1.0, phase=float(rng.random()), flex0=0.15)
            trunk.children.append(b)
            sk.branches.append(b)
            hosts.append(b)
    # recursive levels
    base = P["crown"]["base"] * H
    parents = hosts
    for li, lv in enumerate(P["levels"]):
        new = []
        last = li == len(P["levels"]) - 1
        maxlen = max(b.length for b in parents) if parents else 1.0
        for par in parents:
            if li == 0:
                n = lv["n"] * rng.uniform(0.85, 1.15) * (1.0 if par is trunk else 1.0 / max(1, len(hosts)) * 2.2)
            else:
                n = lv["n"] * min(1.0, max(0.25, par.length / maxlen)) * rng.uniform(0.8, 1.2)
            n = max(1, int(round(n)))
            ts = np.sort(rng.uniform(lv["start"], lv["end"], n)) if not lv.get("age_sort") else np.linspace(lv["start"], lv["end"], n)
            phi = rng.uniform(0, 2 * math.pi)
            for k, t in enumerate(ts):
                p, pd, pr = par.at(t)
                if li == 0 and par is trunk and p[2] < base - 0.3 and not lv.get("age_sort"):
                    continue
                phi += math.radians(lv["phyllo"] + rng.normal(0, 18))
                nn, bb = _perp(pd)
                a = math.radians(lv["angle"][0] + (lv["angle"][1] - lv["angle"][0]) * t + rng.normal(0, lv.get("angle_var", 0)))
                if lv.get("age_sort"):    # palm fronds: old ones (low) droop, young ones (top) stand up
                    a = math.radians(lv["angle"][0] + (lv["angle"][1] - lv["angle"][0]) * (k / max(1, n - 1)) + rng.normal(0, lv.get("angle_var", 0)))
                d = pd * math.cos(a) + (nn * math.cos(phi) + bb * math.sin(phi)) * math.sin(a)
                radial = np.array([p[0] - trunk.pts[0][0], p[1] - trunk.pts[0][1], 0.0])
                if np.linalg.norm(radial) < 0.2:
                    radial = np.array([d[0], d[1], 0.0])
                d = _norm(d + _norm(radial) * lv.get("outward", 0.0))
                if lv.get("downwind"):
                    d = _norm(d + sk.wind * lv["downwind"])
                # length
                if lv.get("abs_length"):
                    L = rng.uniform(*lv["abs_length"]) * (H / 9.5) ** 0.3
                elif li == 0:
                    rr = (p[2] - base) / max(H - base, 1e-3)
                    L = lv["length"] * H * envelope(P["crown"]["shape"], rr) * P["crown"].get("width", 1.0) ** 0.5
                    if par is not trunk:
                        L *= 0.55
                else:
                    L = lv["length"] * par.length * (1.0 - 0.45 * t)
                L *= 1.0 + rng.normal(0, lv.get("length_var", 0.1))
                if lv.get("downwind"):
                    L *= 0.75 + 0.45 * max(0.0, float(np.dot(_norm(np.array([d[0], d[1], 0.0])), sk.wind)))
                if L < 0.12:
                    continue
                rb = min(pr * lv["radius"], pr * 0.92) if not lv.get("radius_abs") else lv["radius_abs"]
                start = p - d * pr * 0.6
                pts, rad = _grow_branch(rng, start, d, L + pr * 0.6, rb, 0.004, lv["seg"], lv.get("curve", 0) * rng.uniform(0.6, 1.3),
                                        lv.get("wobble", 8), lv.get("gravity", 0.0), li + 1)
                phase = float(rng.random()) if par.level < 0 else par.phase
                flex = min(1.0, par.flex0 + (0.3 if li == 0 else 0.35) * (0.4 + 0.6 * t))
                b = Branch(li, pts, rad, parent=par, t0=float(t), phase=phase, flex0=flex)
                par.children.append(b)
                sk.branches.append(b)
                new.append(b)
                if last:
                    b.leafy = True
        parents = new
    _place_cards(sk, P, rng)
    sk.collider = _collider(sk, P)
    return sk


def _refine_base(pts):
    """Insert extra rings in the first 1.2 m of the trunk (root flare)."""
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        if a[2] < 1.2:
            n = max(1, int(math.ceil(np.linalg.norm(b - a) / 0.18)))
            for k in range(1, n + 1):
                out.append(a + (b - a) * k / n)
        else:
            out.append(b)
    return np.array(out)


def _collider(sk, P):
    _, _, r1 = sk.trunk.at(min(1.0, 1.35 / max(sk.trunk.length, 1.0)))
    top = sk.trunk.at(1.0)[0][2] if P["trunk"].get("split") else P["crown"]["base"] * sk.height
    h = float(min(max(top, 2.0), 6.0))
    return {"type": "capsule", "radius": round(float(r1) * 1.05, 3), "height": round(h, 2), "center": [0.0, 0.0, round(h / 2, 2)]}


# ------------------------------------------------------------------ leaf cards
def _cells(P):
    cs = P["leaves"]["cells"]
    names = [c[0] for c in cs]
    w = np.array([c[1] for c in cs], float)
    return names, w / w.sum()


def _place_cards(sk, P, rng):
    Lf = P["leaves"]
    names, wts = _cells(P)
    mode = Lf["mode"]
    leafy = [b for b in sk.branches if b.leafy]
    cand = []                                  # (pos, dir, flex, phase, branch t)
    if mode == "strip":
        for b in leafy:
            cand.append((b, None))
        sk.cards = [dict(mode="strip", branch=b, cell=names[0], width=Lf["size"][0] * (1 + rng.normal(0, Lf["size_var"])),
                         flex=b.flex0, phase=b.phase) for b, _ in cand]
        _crown(sk)
        return
    dense = max(0.05, Lf["spacing"] * 0.5)
    for b in leafy:
        s0 = Lf["start"] * b.length
        s = s0 + rng.uniform(0, dense)
        while s <= b.length:
            t = s / max(b.length, 1e-6)
            p, d, _ = b.at(t)
            cand.append((p, d, min(1.0, b.flex0 + 0.25 * t), b.phase, t, b))
            s += dense * rng.uniform(0.7, 1.3)
        p, d, _ = b.at(1.0)
        cand.append((p, d, min(1.0, b.flex0 + 0.25), b.phase, 1.0, b))
    budget = Lf["budget"] if mode != "tuft" else Lf["budget"] // 2
    if len(cand) > budget:
        # keep tips preferentially (they carry the outer foliage), then a random subset
        prio = np.array([c[4] for c in cand]) + rng.uniform(0, 0.9, len(cand))
        keep = np.sort(np.argsort(-prio)[:budget])
        cand = [cand[i] for i in keep]
    ctr = np.mean([c[0] for c in cand], axis=0) if cand else np.array([0, 0, sk.height * 0.6])
    for (p, d, flex, phase, t, b) in cand:
        cell = names[int(rng.choice(len(names), p=wts))]
        sc = 1.0 + rng.normal(0, Lf["size_var"])
        w, h = Lf["size"][0] * sc, Lf["size"][1] * sc
        out = np.array([p[0] - ctr[0], p[1] - ctr[1], 0.0])
        out = _norm(out) if np.linalg.norm(out) > 0.1 else _norm(np.array([d[0], d[1], 0.0]) + 1e-3)
        if mode == "hang":
            u = _norm(d * 0.65 + out * 0.25 - UP * 0.35 + rng.normal(0, 0.12, 3))
            n0 = _norm(UP * 0.8 + out * 0.4)
            rolls = [rng.normal(0, 0.35)]
        elif mode == "tuft":
            u = _norm(d * 0.6 + out * 0.2 + UP * Lf["tilt"] + rng.normal(0, 0.15, 3))
            n0 = _norm(UP * 0.4 + out * 0.6)
            r0 = rng.uniform(0, math.pi)
            rolls = [r0, r0 + math.pi / 2 + rng.normal(0, 0.2)]
        else:
            u = _norm(d * 0.55 + out * 0.45 + UP * Lf["tilt"] + rng.normal(0, 0.18, 3))
            n0 = _norm(UP * 0.75 + out * 0.45)
            rolls = [rng.normal(0, 0.45)]
        n1 = _norm(n0 - u * np.dot(n0, u))
        for roll in rolls:
            n = _rot(n1, u, roll)
            base = p - u * h * (0.08 if mode != "tuft" else 0.42)
            sk.cards.append(dict(mode=mode, pos=base, u=u, n=n, w=w, h=h, cell=cell, flex=flex, phase=phase,
                                 droop=Lf.get("droop", 0.1) * rng.uniform(0.5, 1.4), anchor=p))
    _crown(sk)


def _crown(sk):
    pts = []
    for c in sk.cards:
        if c["mode"] == "strip":
            pts.extend(list(c["branch"].pts))
        else:
            pts.append(c["pos"])
            pts.append(c["pos"] + c["u"] * c["h"])
    pts = np.array(pts) if pts else np.zeros((1, 3))
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    sk.crown_c = (lo + hi) / 2
    sk.crown_r = np.maximum((hi - lo) / 2, 0.3)


# ------------------------------------------------------------------ shrubs
def _grow_shrub(sk, P, rng):
    S = P["shrub"]
    sx, sy, sz = S["size"]
    sk.height = sz
    sk.wind = np.array([1.0, 0.0, 0.0])
    sk.trunk = Branch(-1, [(0, 0, -0.1), (0, 0, sz * 0.3)], [P["trunk_radius"], P["trunk_radius"] * 0.6])
    sk.branches.append(sk.trunk)
    for k in range(S.get("stems", 4)):
        a = rng.uniform(0, 2 * math.pi)
        d = _norm(np.array([math.cos(a) * 0.5, math.sin(a) * 0.5 * sy / sx, 1.0]))
        start = np.array([rng.uniform(-0.3, 0.3) * sx, rng.uniform(-0.3, 0.3) * sy, -0.05])
        pts, rad = _grow_branch(rng, start, d, sz * 0.75, P["trunk_radius"], 0.004, 0.15, 0, 20, 0.0, 1, ground=False)
        b = Branch(0, pts, rad, parent=sk.trunk, phase=float(rng.random()), flex0=0.4)
        sk.branches.append(b)
    Lf = P["leaves"]
    names, wts = _cells(P)
    n = Lf["budget"]
    c = np.array([0.0, 0.0, sz * (0.48 if S["shape"] == "mound" else 0.5)])
    for i in range(n):
        if S["shape"] == "box":
            # a rounded box: pick a face by area, then a point on it
            face = rng.choice(5, p=_box_face_p(sx, sy, sz))
            q = rng.uniform(-0.5, 0.5, 3) * np.array([sx, sy, sz])
            nrm = np.zeros(3)
            ax = [0, 0, 1, 1, 2][face]
            sgn = [1, -1, 1, -1, 1][face]
            q[ax] = sgn * 0.5 * [sx, sy, sz][ax]
            nrm[ax] = sgn
            q = q * 0.92
            q[2] += sz * 0.5
            nrm = _norm(nrm + rng.normal(0, 0.35, 3))
            pos = q
        else:
            v = _norm(rng.normal(size=3))
            v[2] = abs(v[2]) * 0.9 + 0.1
            v = _norm(v)
            inner = rng.random() < 0.2
            rad = np.array([sx / 2, sy / 2, sz * 0.55]) * (rng.uniform(0.45, 0.7) if inner else rng.uniform(0.85, 1.0))
            pos = c + v * rad
            pos[2] = max(pos[2], 0.08)
            nrm = _norm(v / np.array([sx, sy, sz]) + rng.normal(0, 0.3, 3))
        u = _norm(np.cross(nrm, rng.normal(size=3)))
        sc = 1.0 + rng.normal(0, Lf["size_var"])
        w, h = Lf["size"][0] * sc, Lf["size"][1] * sc
        cell = names[int(rng.choice(len(names), p=wts))]
        sk.cards.append(dict(mode="cloud", pos=pos - u * h * 0.5, u=u, n=nrm, w=w, h=h, cell=cell, flex=0.3, phase=float(rng.random()),
                             droop=0.0, anchor=pos))
    _crown(sk)
    sk.crown_c = c.copy()
    sk.crown_r = np.array([sx / 2, sy / 2, sz * 0.55])
    sk.collider = {"type": "box", "size": [sx, sy, sz], "center": [0.0, 0.0, sz / 2]}
    return sk


def _box_face_p(sx, sy, sz):
    a = np.array([sy * sz, sy * sz, sx * sz, sx * sz, sx * sy * 1.4])
    return a / a.sum()


def grow_planter(name):
    """The planter shrubs: a shrub species re-sized for the props-kit planter."""
    d = PLANTER_SHRUBS[name]
    base = SPECIES[d["base"]]
    ov = {"shrub": d["shrub"], "height": [d["shrub"]["size"][2]] * 2,
          "leaves": dict(base["leaves"], budget=d["budget"], lod1=d["lod1"])}
    return grow(d["base"], 0, ov)


# ------------------------------------------------------------------ meshing
class MeshData:
    """Triangle soup per material ("bark", "leaf"): positions, normals, uv, uv2, color, faces."""

    def __init__(self):
        self.parts = {m: {"p": [], "n": [], "uv": [], "uv2": [], "c": [], "f": []} for m in ("bark", "leaf")}

    def add(self, mat, p, n, uv, uv2, c, f):
        P = self.parts[mat]
        base = sum(len(x) for x in P["p"])
        P["p"].append(np.asarray(p, np.float32))
        P["n"].append(np.asarray(n, np.float32))
        P["uv"].append(np.asarray(uv, np.float32))
        P["uv2"].append(np.asarray(uv2, np.float32))
        P["c"].append(np.asarray(c, np.float32))
        P["f"].append(np.asarray(f, np.int64) + base)

    def arrays(self, mat):
        P = self.parts[mat]
        if not P["p"]:
            return None
        return {k: np.concatenate(v) for k, v in P.items()}

    def tris(self):
        return sum(sum(len(f) for f in P["f"]) for P in self.parts.values())


def _frames(pts):
    """Parallel-transported (normal, binormal) along a polyline."""
    d = np.diff(pts, axis=0)
    d = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    T = np.vstack([d[:1], (d[:-1] + d[1:]) / 2, d[-1:]])
    T = T / np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-9)
    N = np.zeros_like(T)
    N[0], _ = _perp(T[0])
    for i in range(1, len(T)):
        v = N[i - 1] - T[i] * np.dot(N[i - 1], T[i])
        N[i] = _norm(v) if np.linalg.norm(v) > 1e-6 else _perp(T[i])[0]
    B = np.cross(T, N)
    return T, N, B


def _tube(md, br, sides, sk, stride=1, flare=0.0, roots=0, palm=False):
    pts, rad = br.pts[::stride], br.rad[::stride]
    if stride > 1 and len(br.pts) % stride != 1:
        pts = np.vstack([pts, br.pts[-1:]])
        rad = np.append(rad, br.rad[-1])
    if len(pts) < 2:
        return
    T, N, B = _frames(pts)
    bark_w, bark_h = BARK[sk.p["bark"]]
    around = max(1, int(round(2 * math.pi * rad[0] / bark_w)))
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    th = np.linspace(0, 2 * math.pi, sides + 1)
    rng = np.random.default_rng(len(pts) * 7 + sides)
    th0 = rng.uniform(0, 2 * math.pi)
    P, Nn, UV, UV2, C, F = [], [], [], [], [], []
    H = max(sk.height, 1e-3)
    for i in range(len(pts)):
        r = rad[i]
        z = pts[i][2]
        ring_r = np.full(sides + 1, r)
        if flare > 0 and z < 1.6:
            lobes = (0.5 + 0.5 * np.cos(roots * th + th0)) ** 2.5 if roots else 0.5
            ring_r = r * (1.0 + flare * math.exp(-max(z, 0.0) / 0.38) * (0.35 + 1.5 * lobes))
        if palm:
            ring_r = ring_r * (1.0 + 0.035 * math.sin(2 * math.pi * cum[i] / 0.22))
            top = cum[i] / max(cum[-1], 1e-3)
            ring_r = ring_r * (1.0 + 0.55 * math.exp(-((1.0 - top) / 0.05) ** 2))
        for k in range(sides + 1):
            dirv = N[i] * math.cos(th[k]) + B[i] * math.sin(th[k])
            P.append(pts[i] + dirv * ring_r[k])
            Nn.append(dirv)
            UV.append((around * k / sides, cum[i] / bark_h))
            UV2.append((min(1.0, max(0.0, pts[i][2] / H)), 0.0))
            t = cum[i] / max(cum[-1], 1e-6)
            flex = 0.0 if br.level < 0 and br.parent is None else min(1.0, br.flex0 + 0.3 * t * (br.level + 1.5) / 3)
            C.append((flex, br.phase, 0.0, 1.0))
    S = sides + 1
    for i in range(len(pts) - 1):
        for k in range(sides):
            a, b, c, d = i * S + k, i * S + k + 1, (i + 1) * S + k + 1, (i + 1) * S + k
            F += [(a, b, c), (a, c, d)]
    md.add("bark", P, Nn, UV, UV2, C, F)


def _card_normals(sk, pts, n_card, mode):
    """Bend card normals towards the crown's outward direction (the crown shades as a volume)."""
    if mode == "hang":
        rad = pts - np.array([0.0, 0.0, 0.0])
        rad[:, 2] = 0.0
        rad = rad / np.maximum(np.linalg.norm(rad, axis=1, keepdims=True), 1e-6)
        out = rad * 0.8 + UP * 0.5
    else:
        out = (pts - sk.crown_c) / sk.crown_r
    out = out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-6)
    n = n_card[None, :] * 0.35 + out * 0.65
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)


def _occlusion(sk, pts):
    e = np.linalg.norm((pts - sk.crown_c) / sk.crown_r, axis=1)
    zf = np.clip((pts[:, 2] - (sk.crown_c[2] - sk.crown_r[2])) / (2 * sk.crown_r[2]), 0, 1)
    return np.clip((0.22 + 0.78 * np.clip(e, 0, 1) ** 1.6) * (0.72 + 0.28 * zf), 0.15, 1.0)


def _card(md, sk, c, rect, lod, scale=1.0):
    u, n = c["u"], c["n"]
    s = np.cross(u, n)
    w, h = c["w"] * scale, c["h"] * scale
    base = c["pos"] if scale == 1.0 else c["anchor"] - u * h * (0.08 if c["mode"] != "tuft" else 0.42)
    down = -UP * c["droop"] * h
    u0, v0, u1, v1 = rect
    if lod == 0:
        rows = [0.0, 1.0]
        cols = [-0.5, 0.0, 0.5]
    else:
        rows = [0.0, 1.0]
        cols = [-0.5, 0.5]
    fold = 0.14 * w if lod == 0 else 0.0
    P, UV, B = [], [], []
    for rw in rows:
        spine = base + u * h * rw + down * rw * rw
        for cl in cols:
            q = spine + s * w * cl - n * fold * abs(cl) * 2 * (0.6 + 0.4 * rw)
            P.append(q)
            UV.append((u0 + (u1 - u0) * (cl + 0.5), v0 + (v1 - v0) * rw))
            B.append(rw)
    P = np.array(P)
    N = _card_normals(sk, P, n, c["mode"])
    ao = _occlusion(sk, P)
    H = max(sk.height, 1e-3)
    C = [(min(1.0, c["flex"] + 0.12 * b), c["phase"], b, a) for b, a in zip(B, ao)]
    UV2 = [(min(1.0, max(0.0, p[2] / H)), 1.0) for p in P]
    nc = len(cols)
    F = []
    for i in range(len(rows) - 1):
        for k in range(nc - 1):
            a, b2, cc, d = i * nc + k, i * nc + k + 1, (i + 1) * nc + k + 1, (i + 1) * nc + k
            F += [(a, b2, cc), (a, cc, d)]
    md.add("leaf", P, N, UV, UV2, C, F)


def _strip(md, sk, c, rect, lod):
    """Palm frond: a folded strip along the rachis (the frond branch)."""
    br = c["branch"]
    stride = 1 if lod == 0 else 2
    pts = br.pts[::stride]
    if len(br.pts) % stride != 1:
        pts = np.vstack([pts, br.pts[-1:]])
    n0 = int(len(pts) * 0.12)
    pts = pts[n0:]
    if len(pts) < 2:
        return
    T, _, _ = _frames(pts)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    L = max(cum[-1], 1e-3)
    u0, v0, u1, v1 = rect
    cols = [-0.5, 0.0, 0.5] if lod == 0 else [-0.5, 0.5]
    P, UV, B = [], [], []
    for i in range(len(pts)):
        t = cum[i] / L
        side = _norm(np.cross(T[i], UP)) if abs(T[i][2]) < 0.98 else np.array([1.0, 0, 0])
        nrm = _norm(np.cross(side, T[i]))
        wd = c["width"] * math.sin(math.pi * min(1.0, 0.12 + t * 1.05)) ** 0.7 * (1.0 - 0.3 * t)
        for cl in cols:
            q = pts[i] + side * wd * cl + nrm * abs(cl) * wd * (0.45 if lod == 0 else 0.0) - UP * abs(cl) * wd * 0.15
            P.append(q)
            UV.append((u0 + (u1 - u0) * (cl + 0.5), v0 + (v1 - v0) * t))
            B.append(t)
    P = np.array(P)
    nn = np.array([0.0, 0.0, 1.0])
    N = _card_normals(sk, P, nn, "strip")
    ao = _occlusion(sk, P)
    H = max(sk.height, 1e-3)
    C = [(min(1.0, c["flex"] + 0.5 * b), c["phase"], b, a) for b, a in zip(B, ao)]
    UV2 = [(min(1.0, max(0.0, p[2] / H)), 1.0) for p in P]
    nc = len(cols)
    F = []
    for i in range(len(pts) - 1):
        for k in range(nc - 1):
            a, b2, cc, d = i * nc + k, i * nc + k + 1, (i + 1) * nc + k + 1, (i + 1) * nc + k
            F += [(a, b2, cc), (a, cc, d)]
    md.add("leaf", P, N, UV, UV2, C, F)


def default_cells():
    """Placeholder atlas rects (the whole texture) until the Pigment atlas exists."""
    return {k: (0.0, 0.0, 1.0, 1.0) for k in LEAF_CELLS}


def build_lod(sk, lod, cells=None, look=None):
    """MeshData of one LOD (0 or 1). cells: atlas name -> (u0, v0, u1, v1) with v0 at the
    card's stem (Blender UV space, v up). look: cell swaps of a species look."""
    cells = cells or default_cells()
    swap = dict(sk.p.get("looks", {}).get(look, {})) if look else {}
    md = MeshData()
    P = sk.p
    shrub = "shrub" in P
    for br in sk.branches:
        if br.level == -1 and br.parent is None:
            sides = P["trunk"]["sides"] if not shrub else 4
            if lod == 1:
                sides = max(5, sides // 2 + 1)
            _tube(md, br, sides, sk, stride=1 if lod == 0 else 2, flare=P.get("flare", 0.0), roots=P.get("roots", 0),
                  palm=sk.species == "palm")
            continue
        if br.level == -1:          # split leaders
            _tube(md, br, 8 if lod == 0 else 5, sk, stride=1 if lod == 0 else 2)
            continue
        lv = P["levels"][br.level] if not shrub else {"sides": 3}
        sides = lv["sides"]
        if sides == 0:
            continue
        if lod == 1:
            if br.level >= 1 or br.rad[0] < 0.045 or sk.species == "palm":
                continue
            sides = max(3, sides - 2)
        if lod == 0 and br.rad[0] < 0.006:
            continue
        _tube(md, br, sides, sk, stride=1 if lod == 0 else 2)
    cards = sk.cards
    if lod == 1 and P["leaves"]["mode"] != "strip":
        want = P["leaves"]["lod1"]
        rng = np.random.default_rng(seed_of(sk.species, sk.variant) + 99)
        if P["leaves"]["mode"] == "tuft":
            cards = [c for i, c in enumerate(cards) if i % 2 == 0]
        idx = np.sort(rng.choice(len(cards), size=min(want, len(cards)), replace=False))
        scale = min(2.0, math.sqrt(len(cards) / max(1, len(idx))) * 0.92)
        for i in idx:
            c = cards[i]
            _card(md, sk, c, cells[swap.get(c["cell"], c["cell"])], 1, scale)
        return md
    for c in cards:
        rect = cells[swap.get(c["cell"], c["cell"])]
        if c["mode"] == "strip":
            _strip(md, sk, c, rect, lod)
        else:
            _card(md, sk, c, rect, lod)
    return md


def stats(md):
    out = {}
    for m in ("bark", "leaf"):
        a = md.arrays(m)
        out[m] = 0 if a is None else int(len(a["f"]))
    out["total"] = out["bark"] + out["leaf"]
    return out


if __name__ == "__main__":
    import sys
    import time
    from species import variant_keys
    t0 = time.time()
    for key, sp, v, look in variant_keys():
        sk = grow_planter(key[5:]) if key[5:] in PLANTER_SHRUBS else grow(sp, v)
        s0, s1 = stats(build_lod(sk, 0, look=look)), stats(build_lod(sk, 1, look=look))
        print(f"{key:28s} h {sk.height:5.1f}  crown r {max(sk.crown_r[:2]):4.1f}  LOD0 {s0['total']:5d} (bark {s0['bark']}, leaf {s0['leaf']})  LOD1 {s1['total']:5d}  cards {len(sk.cards)}")
    print(f"{time.time() - t0:.1f} s")
