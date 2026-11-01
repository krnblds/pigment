"""Leaf / needle / blossom card art and bark relief for the tree kit (system Python: numpy, PIL, scipy).

    python tools/trees/stencils.py [--only pine_tuft,bark_pine] [--preview]

Writes scenes/trees/stencils/ (git-ignored, deterministic):
    leaf_<cell>_color.png    sRGB colour + alpha (leaf shapes, twigs, flowers)
    leaf_<cell>_relief.png   grey height (leaf domes, midribs, round twigs), alpha = coverage
    leaf_<cell>_blade.png    white where light passes through (thin blades, petals), alpha = shape
    bark_<sp>_height.png     seamless grey relief of the bark tile (0.5 = flat)
    bark_<sp>_cavity.png     white in the furrows / fissures (alpha = mask)
    bark_<sp>_ridge.png      white on the plate / ridge tops (alpha = mask)
    bark_<sp>_color.png      seamless colour detail (lenticels, exposed under-bark, scars)
These are only shapes and relief: tools/trees/tree_textures.py turns them into
materials in Pigment (atlas cells and seamless bark tiles: colour layers,
generators, normals, roughness, translucency, grime, moss).

Card convention: the stem / twig base is at the bottom centre of the image,
the tip at the top.
"""
import colorsys
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "scenes" / "trees" / "stencils"
sys.path.insert(0, str(HERE))
from species import LEAF_CELLS, BARK  # noqa: E402

SS = 2          # supersampling


def jit(rng, rgb, h=0.02, s=0.08, v=0.12):
    hh, ss, vv = colorsys.rgb_to_hsv(*rgb)
    hh = (hh + rng.normal(0, h)) % 1.0
    ss = min(1.0, max(0.0, ss * (1 + rng.normal(0, s))))
    vv = min(1.0, max(0.0, vv * (1 + rng.normal(0, v))))
    return colorsys.hsv_to_rgb(hh, ss, vv)


def c8(rgb, a=255):
    return tuple(int(max(0, min(1, x)) * 255 + 0.5) for x in rgb) + (a,)


class Card:
    """Draws one card into colour + masks at SS x resolution."""

    def __init__(self, w, h, seed):
        self.W, self.H = w * SS, h * SS
        self.rng = np.random.default_rng(seed)
        self.col = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.blade = Image.new("L", (self.W, self.H), 0)
        self.rib = Image.new("L", (self.W, self.H), 0)
        self.twig = Image.new("L", (self.W, self.H), 0)
        self.dc = ImageDraw.Draw(self.col)
        self.db = ImageDraw.Draw(self.blade)
        self.dr = ImageDraw.Draw(self.rib)
        self.dt = ImageDraw.Draw(self.twig)

    # coordinates in 0..1 (x right, y up from the bottom) -> pixels
    def P(self, x, y):
        return (x * self.W, (1.0 - y) * self.H)

    def line(self, pts, w0, w1, rgb, twig=True, rib=False):
        """Tapered polyline (w in image fraction of width)."""
        n = len(pts)
        for i in range(n - 1):
            t = i / max(1, n - 2)
            w = (w0 * (1 - t) + w1 * t) * self.W
            a, b = self.P(*pts[i]), self.P(*pts[i + 1])
            self.dc.line([a, b], fill=c8(rgb), width=max(1, int(w)))
            r = w / 2
            self.dc.ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r], fill=c8(rgb))
            if twig:
                self.dt.line([a, b], fill=255, width=max(1, int(w)))
                self.dt.ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r], fill=255)
            if rib:
                self.dr.line([a, b], fill=255, width=max(1, int(w)))

    def poly(self, pts, rgb, blade=True, outline=None):
        q = [self.P(x, y) for x, y in pts]
        self.dc.polygon(q, fill=c8(rgb))
        if outline is not None:
            self.dc.line(q + [q[0]], fill=c8(outline), width=max(1, SS))
        if blade:
            self.db.polygon(q, fill=255)
        else:
            self.dt.polygon(q, fill=255)

    def save(self, name, out):
        size = (self.W // SS, self.H // SS)
        col = self.col.resize(size, Image.LANCZOS)
        blade = self.blade.resize(size, Image.LANCZOS)
        rib = self.rib.resize(size, Image.LANCZOS)
        twig = self.twig.resize(size, Image.LANCZOS)
        a = np.asarray(col)[..., 3].astype(np.float32) / 255
        # relief: domed blades (distance to the edge), raised midribs, round twigs
        from scipy.ndimage import distance_transform_edt, gaussian_filter
        bl = np.asarray(blade).astype(np.float32) / 255
        dist = distance_transform_edt(bl > 0.5)
        dome = np.clip(dist / max(3.0, size[0] / 160), 0, 1) ** 0.6
        tw = np.asarray(twig).astype(np.float32) / 255
        tdist = distance_transform_edt(tw > 0.5)
        tdome = np.clip(tdist / max(2.0, size[0] / 220), 0, 1) ** 0.5
        rb = gaussian_filter(np.asarray(rib).astype(np.float32) / 255, 0.8)
        h = 0.5 + 0.18 * dome * bl + 0.16 * rb * bl + 0.3 * tdome * (1 - bl * 0.6)
        h = np.clip(h, 0, 1)
        rel = np.dstack([h, h, h, a])
        Image.fromarray((rel * 255 + 0.5).astype(np.uint8), "RGBA").save(out / f"leaf_{name}_relief.png")
        trans = np.clip(bl * (1 - tw), 0, 1)
        Image.fromarray((np.dstack([trans, trans, trans, np.clip(a * trans * 1.0, 0, 1)]) * 255 + 0.5).astype(np.uint8), "RGBA").save(
            out / f"leaf_{name}_blade.png")
        col.save(out / f"leaf_{name}_color.png")
        return col


# ------------------------------------------------------------------ leaf shapes
def outline(kind, n=36, serr=0, teeth=14, rng=None):
    """Half-width profile of a leaf: list of (t along the midrib 0..1, half width 0..1)."""
    ts = np.linspace(0, 1, n)
    if kind == "ovate":
        w = np.sin(np.pi * ts ** 0.75) ** 0.85
    elif kind == "elliptic":
        w = np.sin(np.pi * ts) ** 0.75
    elif kind == "lanceolate":
        w = np.sin(np.pi * ts ** 0.8) ** 1.3
    elif kind == "obovate":
        w = np.sin(np.pi * ts ** 1.3) ** 0.8
    else:
        w = np.sin(np.pi * ts)
    w = w * (1 - ts ** 10 * 0.9)          # acuminate tip
    if serr:
        saw = (ts * teeth) % 1.0
        w = w * (1 - serr * saw * (ts > 0.12) * (ts < 0.96))
    return ts, w


def leaf(cv, base, ang, length, width, rgb, kind="ovate", serr=0.0, teeth=14, veins=5, curl=0.0, petiole=0.0, prgb=None):
    """A simple leaf at base (0..1 coords), midrib angle ang (radians, 0 = up), length / width in
    image-width fractions (aspect corrected for y)."""
    asp = cv.W / cv.H
    dx, dy = math.sin(ang), math.cos(ang)
    px, py = -dy, dx
    bx, by = base
    if petiole > 0:
        e = (bx + dx * petiole, by + dy * petiole * asp)
        cv.line([base, e], 0.006, 0.004, prgb or (0.25, 0.3, 0.1), twig=True)
        bx, by = e
    ts, w = outline(kind, serr=serr, teeth=teeth)
    left, right, mid = [], [], []
    for t, hw in zip(ts, w):
        bend = curl * t * t * length
        cx = bx + dx * t * length + px * bend
        cy = by + (dy * t * length + py * bend) * asp
        left.append((cx + px * hw * width / 2, cy + py * hw * width / 2 * asp))
        right.append((cx - px * hw * width / 2, cy - py * hw * width / 2 * asp))
        mid.append((cx, cy))
    dark = tuple(x * 0.72 for x in rgb)
    cv.poly(left + right[::-1], rgb, outline=dark)
    light = tuple(min(1, x * 1.25 + 0.03) for x in rgb)
    cv.line(mid[:-2], 0.0045, 0.0015, light, twig=False, rib=True)
    for k in range(1, veins + 1):
        t = k / (veins + 1)
        i = int(t * (len(mid) - 1))
        hw = w[i] * width / 2 * 0.85
        for s in (1, -1):
            e = (mid[i][0] + px * hw * s + dx * hw * 0.6, mid[i][1] + (py * hw * s + dy * hw * 0.6) * asp)
            cv.line([mid[i], e], 0.002, 0.001, tuple(min(1, x * 1.12) for x in rgb), twig=False, rib=True)
    return mid[-1]


def twig_path(rng, start, ang, length, steps=10, wob=0.12, asp=1.0):
    pts = [start]
    a = ang
    for i in range(steps):
        a += rng.normal(0, wob)
        x, y = pts[-1]
        pts.append((x + math.sin(a) * length / steps, y + math.cos(a) * length / steps * asp))
    return pts


def along(pts, t):
    n = len(pts) - 1
    f = t * n
    i = min(int(f), n - 1)
    u = f - i
    a, b = pts[i], pts[i + 1]
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u), math.atan2(b[0] - a[0], (b[1] - a[1]) + 1e-9)


BARK_TWIG = (0.2, 0.15, 0.1)


# ------------------------------------------------------------------ cells
def c_pagoda(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    main = twig_path(rng, (0.5, 0.0), rng.normal(0, 0.15), 0.85, 12, 0.08, asp)
    cv.line(main, 0.016, 0.005, BARK_TWIG)
    base_col = (0.2, 0.36, 0.09) if not name.endswith("_b") else (0.24, 0.4, 0.1)
    n = 9
    for k in range(n):
        t = 0.08 + 0.88 * k / (n - 1)
        p, a = along(main, t)
        side = 1 if k % 2 == 0 else -1
        ra = a + side * rng.uniform(0.5, 0.95)
        L = rng.uniform(0.34, 0.48) * (1.05 - 0.3 * t)
        rach = twig_path(rng, p, ra, L, 8, 0.06, asp)
        col = jit(rng, base_col, 0.015, 0.1, 0.12)
        cv.line(rach, 0.006, 0.0025, (0.28, 0.33, 0.12), twig=True)
        npairs = int(rng.integers(4, 7))
        for j in range(npairs):
            u = 0.18 + 0.78 * j / max(1, npairs - 1) * 0.95
            q, qa = along(rach, u)
            for s in (1, -1):
                lc = jit(rng, col, 0.01, 0.05, 0.1)
                leaf(cv, q, qa + s * rng.uniform(0.9, 1.25), rng.uniform(0.095, 0.125), rng.uniform(0.048, 0.06), lc,
                     "ovate", veins=3, curl=rng.normal(0, 0.15), petiole=0.006)
        e = rach[-1]
        leaf(cv, e, along(rach, 1.0)[1] + rng.normal(0, 0.1), 0.12, 0.058, jit(rng, col, 0.01, 0.05, 0.1), "ovate", veins=3, petiole=0.006)
    return cv


def c_zelkova(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    base_col = (0.24, 0.42, 0.1) if not name.endswith("_b") else (0.2, 0.37, 0.09)
    twigs = [twig_path(rng, (0.5, 0.0), rng.normal(0, 0.1), 0.92, 14, 0.1, asp)]
    for k in range(5):
        p, a = along(twigs[0], 0.18 + 0.15 * k)
        twigs.append(twig_path(rng, p, a + (1 if k % 2 else -1) * rng.uniform(0.5, 0.8), rng.uniform(0.3, 0.42), 8, 0.12, asp))
    for i, tw in enumerate(twigs):
        cv.line(tw, 0.012 if i == 0 else 0.007, 0.003, BARK_TWIG)
    for i, tw in enumerate(twigs):
        nl = 13 if i == 0 else 8
        for k in range(nl):
            t = 0.1 + 0.88 * k / (nl - 1)
            p, a = along(tw, t)
            s = 1 if k % 2 == 0 else -1
            sz = rng.uniform(0.15, 0.2) * (1.1 - 0.35 * t if i == 0 else 0.9)
            leaf(cv, p, a + s * rng.uniform(0.55, 0.95), sz, sz * 0.48, jit(rng, base_col, 0.012, 0.08, 0.13), "ovate",
                 serr=0.18, teeth=12, veins=6, curl=rng.normal(0, 0.25) * s, petiole=0.008)
    return cv


def fan(cv, base, ang, R, rgb, petiole):
    """Ginkgo leaf: a fan with a notch."""
    asp = cv.W / cv.H
    dx, dy = math.sin(ang), math.cos(ang)
    e = (base[0] + dx * petiole, base[1] + dy * petiole * asp)
    cv.line([base, e], 0.004, 0.003, tuple(x * 0.8 for x in rgb), twig=True)
    pts = [e]
    spread = cv.rng.uniform(0.85, 1.05)
    phis = np.linspace(-spread, spread, 40)
    notch = cv.rng.uniform(0.08, 0.2)
    for ph in phis:
        r = R * (1 - notch * math.exp(-(ph / 0.07) ** 2) + 0.035 * math.sin(ph * 31 + cv.rng.random()))
        a = ang + ph
        pts.append((e[0] + math.sin(a) * r, e[1] + math.cos(a) * r * asp))
    cv.poly(pts, rgb, outline=tuple(x * 0.75 for x in rgb))
    for ph in np.linspace(-spread * 0.85, spread * 0.85, 9):     # dichotomous veins
        a = ang + ph
        cv.line([e, (e[0] + math.sin(a) * R * 0.92, e[1] + math.cos(a) * R * 0.92 * asp)], 0.0012, 0.0008,
                tuple(min(1, x * 1.1) for x in rgb), twig=False, rib=True)


def c_ginkgo(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    gold = name.endswith("gold")
    main = twig_path(rng, (0.5, 0.0), rng.normal(0, 0.1), 0.9, 10, 0.07, asp)
    cv.line(main, 0.014, 0.005, (0.3, 0.27, 0.22))
    spurs = 11
    for k in range(spurs):
        t = 0.12 + 0.86 * k / (spurs - 1)
        p, a = along(main, t)
        s = 1 if k % 2 == 0 else -1
        sp = (p[0] + s * 0.02, p[1] + 0.01)
        cv.line([p, sp], 0.012, 0.01, (0.32, 0.28, 0.22))
        for j in range(int(rng.integers(4, 7))):
            if gold:
                col = jit(rng, rng.choice([(0.9, 0.68, 0.08), (0.95, 0.75, 0.15), (0.8, 0.55, 0.05), (0.7, 0.62, 0.12)]), 0.01, 0.06, 0.08)
            else:
                col = jit(rng, (0.33, 0.5, 0.12), 0.012, 0.08, 0.12)
            fan(cv, sp, a + s * rng.uniform(0.2, 1.3) + rng.normal(0, 0.4), rng.uniform(0.1, 0.14), col, rng.uniform(0.04, 0.08))
    return cv


def flower(cv, c, r, rgb, rng):
    asp = cv.W / cv.H
    a0 = rng.uniform(0, 2 * math.pi)
    for k in range(5):
        a = a0 + k * 2 * math.pi / 5
        pts = []
        for ph in np.linspace(-0.62, 0.62, 14):
            rr = r * (0.25 + 0.75 * math.cos(ph * 1.2)) * (1 - 0.15 * math.exp(-(ph / 0.1) ** 2))
            pts.append((c[0] + math.sin(a + ph * 0.9) * rr, c[1] + math.cos(a + ph * 0.9) * rr * asp))
        pts.append(c)
        pc = jit(rng, rgb, 0.005, 0.15, 0.04)
        cv.poly(pts, pc, outline=tuple(x * 0.9 for x in pc))
    cr = r * 0.22
    cx, cy = cv.P(*c)
    cv.dc.ellipse([cx - cr * cv.W, cy - cr * cv.W, cx + cr * cv.W, cy + cr * cv.W], fill=c8((0.85, 0.42, 0.5)))
    for k in range(9):         # stamens
        a = rng.uniform(0, 2 * math.pi)
        e = (c[0] + math.sin(a) * r * 0.45, c[1] + math.cos(a) * r * 0.45 * asp)
        cv.line([c, e], 0.0012, 0.001, (0.95, 0.85, 0.85), twig=False)
        ex, ey = cv.P(*e)
        d = 0.004 * cv.W
        cv.dc.ellipse([ex - d, ey - d, ex + d, ey + d], fill=c8((0.95, 0.8, 0.25)))


def c_cherry_blossom(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    main = twig_path(rng, (0.5, 0.0), rng.normal(0, 0.15), 0.92, 12, 0.12, asp)
    sides = [twig_path(rng, along(main, t)[0], along(main, t)[1] + s * rng.uniform(0.5, 0.9), rng.uniform(0.25, 0.35), 6, 0.15, asp)
             for t, s in ((0.2, 1), (0.32, -1), (0.45, 1), (0.58, -1), (0.7, 1), (0.8, -1))]
    for tw in [main] + sides:
        cv.line(tw, 0.016 if tw is main else 0.008, 0.004, (0.22, 0.13, 0.11))
    for tw in [main] + sides:
        nc = 9 if tw is main else 5
        for k in range(nc):
            p, a = along(tw, 0.15 + 0.85 * k / max(1, nc - 1))
            for j in range(int(rng.integers(3, 6))):     # umbel: pedicels from one point
                aa = a + rng.normal(0, 1.1)
                L = rng.uniform(0.03, 0.06)
                e = (p[0] + math.sin(aa) * L, p[1] + math.cos(aa) * L * asp)
                cv.line([p, e], 0.0025, 0.002, (0.45, 0.2, 0.22), twig=True)
                if rng.random() < 0.12:
                    cv.dc.ellipse([cv.P(*e)[0] - 6, cv.P(*e)[1] - 8, cv.P(*e)[0] + 6, cv.P(*e)[1] + 8], fill=c8((0.92, 0.55, 0.62)))
                    continue
                flower(cv, e, rng.uniform(0.045, 0.06), rng.choice([(0.99, 0.9, 0.92), (0.98, 0.84, 0.88), (1.0, 0.94, 0.95)]), rng)
            if rng.random() < 0.35:       # a few young bronze-green leaves
                leaf(cv, p, a + rng.choice([-1, 1]) * 0.8, 0.07, 0.03, jit(rng, (0.42, 0.35, 0.14)), "elliptic", serr=0.1, veins=3)
    return cv


def c_cherry_green(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    main = twig_path(rng, (0.5, 0.0), rng.normal(0, 0.12), 0.9, 12, 0.1, asp)
    cv.line(main, 0.014, 0.004, (0.22, 0.13, 0.11))
    sides = [twig_path(rng, along(main, t)[0], along(main, t)[1] + s * 0.7, 0.35, 6, 0.12, asp) for t, s in ((0.3, 1), (0.5, -1), (0.65, 1))]
    for tw in sides:
        cv.line(tw, 0.008, 0.003, (0.22, 0.13, 0.11))
        for k in range(5):
            p, a = along(tw, 0.15 + 0.2 * k)
            s = 1 if k % 2 == 0 else -1
            sz = rng.uniform(0.16, 0.2)
            leaf(cv, p, a + s * rng.uniform(0.5, 0.9), sz, sz * 0.45, jit(rng, (0.2, 0.36, 0.1), 0.012, 0.08, 0.12), "elliptic",
                 serr=0.12, teeth=20, veins=7, curl=rng.normal(0, 0.2), petiole=0.015, prgb=(0.45, 0.2, 0.15))
    for k in range(11):
        t = 0.08 + 0.9 * k / 10
        p, a = along(main, t)
        s = 1 if k % 2 == 0 else -1
        sz = rng.uniform(0.19, 0.24) * (1.05 - 0.3 * t)
        leaf(cv, p, a + s * rng.uniform(0.5, 0.95), sz, sz * 0.45, jit(rng, (0.2, 0.36, 0.1), 0.012, 0.08, 0.12), "elliptic",
             serr=0.12, teeth=20, veins=7, curl=rng.normal(0, 0.2), petiole=0.018, prgb=(0.45, 0.2, 0.15))
    return cv


def c_pine(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    main = twig_path(rng, (0.5, 0.0), rng.normal(0, 0.05), 0.62, 8, 0.05, asp)
    cv.line(main, 0.03, 0.02, (0.24, 0.2, 0.16))
    needles = []
    for k in range(380):
        t = rng.uniform(0.18, 1.0) ** 0.7
        p, a = along(main, t)
        ang = a + rng.normal(0, 1.0) * (1.2 - 0.5 * t)
        L = rng.uniform(0.26, 0.38)
        needles.append((t, p, ang, L))
    needles.sort(key=lambda x: x[0])
    for t, p, ang, L in needles:
        for s in (-0.07, 0.07):           # paired needles
            a = ang + s
            bend = rng.normal(0, 0.15)
            pts = []
            for u in np.linspace(0, 1, 6):
                aa = a + bend * u
                pts.append((p[0] + math.sin(aa) * L * u, p[1] + math.cos(aa) * L * u * asp))
            col = jit(rng, (0.11, 0.24, 0.1), 0.01, 0.1, 0.18)
            cv.line(pts, 0.0055, 0.002, col, twig=False)
            cv.db.line([cv.P(*q) for q in pts], fill=255, width=max(1, int(0.003 * cv.W)))
    # the white "candle" (new shoot) of kuromatsu
    tip, a = along(main, 1.0)
    cv.line([tip, (tip[0] + math.sin(a) * 0.04, tip[1] + 0.16 * asp)], 0.022, 0.012, (0.78, 0.74, 0.62))
    return cv


def c_cedar(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    axes = [twig_path(rng, (0.5, 0.0), rng.normal(0, 0.08), 0.94, 14, 0.06, asp)]
    for k in range(12):
        t = 0.1 + 0.075 * k
        p, a = along(axes[0], t)
        s = 1 if k % 2 == 0 else -1
        axes.append(twig_path(rng, p, a + s * rng.uniform(0.45, 0.75), rng.uniform(0.26, 0.4) * (1.1 - 0.5 * t), 8, 0.08, asp))
        for j in range(3):
            q, qa = along(axes[-1], 0.4 + 0.3 * j)
            axes.append(twig_path(rng, q, qa + rng.choice([-1, 1]) * 0.6, rng.uniform(0.06, 0.12), 4, 0.1, asp))
    for ax in axes:
        pts = ax
        for i in range(len(pts) - 1):
            for u in np.linspace(0, 1, 7, endpoint=False):
                x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u
                y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u
                a = math.atan2(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1] + 1e-9)
                for s in (1, -1, 0.3, -0.3):    # awl needles spiralling round the shoot
                    na = a + s * rng.uniform(0.5, 0.9)
                    L = rng.uniform(0.018, 0.03)
                    e = (x + math.sin(na) * L, y + math.cos(na) * L * asp)
                    col = jit(rng, (0.11, 0.23, 0.12), 0.01, 0.1, 0.18)
                    cv.line([(x, y), e], 0.007, 0.002, col, twig=False)
                    cv.db.line([cv.P(x, y), cv.P(*e)], fill=255, width=max(1, int(0.004 * cv.W)))
    return cv


def c_palm(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    asp = cv.W / cv.H
    rach = [(0.5 + 0.01 * math.sin(t * 3), t) for t in np.linspace(0, 1, 30)]
    pinnae = []
    for k in range(140):
        t = 0.08 + 0.9 * k / 139
        p = (0.5, t)
        for s in (1, -1):
            if t < 0.2:              # spines at the base
                L = 0.12 + 0.3 * (t - 0.08) / 0.12
                col = (0.55, 0.5, 0.25)
                wd = 0.012
            else:
                L = 0.46 * math.sin(math.pi * min(1, (t - 0.05) / 0.95)) ** 0.6 + 0.05
                col = jit(rng, (0.2, 0.33, 0.11) if rng.random() > 0.15 else (0.32, 0.36, 0.12), 0.01, 0.08, 0.12)
                wd = 0.035
            a = s * rng.uniform(0.55, 0.85)
            pinnae.append((p, a, L, wd, col))
    for p, a, L, wd, col in pinnae:
        leaf(cv, p, a, L, wd, col, "lanceolate", veins=0, curl=rng.normal(0, 0.08))
    cv.line(rach, 0.05, 0.008, (0.5, 0.48, 0.25))
    return cv


def c_azalea(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    bloom = name.endswith("bloom")
    for k in range(int(rng.integers(5, 8))):          # whorled leaf rosettes at shoot tips
        c = (rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.8))
        cv.line([(0.5, 0.0), c], 0.008, 0.005, (0.3, 0.2, 0.14))
        for j in range(int(rng.integers(6, 9))):
            leaf(cv, c, rng.uniform(0, 2 * math.pi), rng.uniform(0.16, 0.22), rng.uniform(0.07, 0.09),
                 jit(rng, (0.13, 0.28, 0.08), 0.01, 0.08, 0.15), "elliptic", veins=3)
        if bloom:
            for j in range(int(rng.integers(2, 4))):
                q = (c[0] + rng.normal(0, 0.05), c[1] + rng.normal(0, 0.05))
                flower(cv, q, rng.uniform(0.09, 0.12), rng.choice([(0.88, 0.12, 0.45), (0.92, 0.2, 0.52), (0.8, 0.1, 0.4)]), rng)
    return cv


def c_box(name, seed, w, h):
    cv = Card(w, h, seed)
    rng = cv.rng
    for k in range(9):
        a = rng.uniform(-0.8, 0.8)
        cv.line(twig_path(rng, (0.5 + rng.normal(0, 0.1), 0.0), a, 0.9, 6, 0.2), 0.006, 0.003, (0.3, 0.24, 0.14))
    for k in range(260):
        c = (rng.uniform(0.05, 0.95), rng.uniform(0.05, 0.95))
        if math.hypot(c[0] - 0.5, c[1] - 0.5) > 0.48:
            continue
        leaf(cv, c, rng.uniform(0, 2 * math.pi), rng.uniform(0.06, 0.085), rng.uniform(0.035, 0.05),
             jit(rng, (0.12, 0.26, 0.07), 0.012, 0.1, 0.18), "elliptic", veins=0)
    return cv


CELL_ART = {
    "pagoda_spray": c_pagoda, "pagoda_spray_b": c_pagoda,
    "zelkova_spray": c_zelkova, "zelkova_spray_b": c_zelkova,
    "ginkgo_spray": c_ginkgo, "ginkgo_gold": c_ginkgo,
    "cherry_blossom": c_cherry_blossom, "cherry_green": c_cherry_green,
    "pine_tuft": c_pine, "cedar_spray": c_cedar, "palm_frond": c_palm,
    "azalea": c_azalea, "azalea_bloom": c_azalea, "box_leaves": c_box,
}


def leaf_cells(only=None):
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    for k, (name, (wm, hm)) in enumerate(LEAF_CELLS.items()):
        if only and name not in only:
            continue
        long_px = 1024 if name != "palm_frond" else 2048
        if hm >= wm:
            h = long_px
            w = int(round(long_px * wm / hm / 8)) * 8
        else:
            w = long_px
            h = int(round(long_px * hm / wm / 8)) * 8
        cv = CELL_ART[name](name, 1000 + k * 17 if not name.endswith(("_b", "gold", "bloom", "green")) else 2000 + k * 31, w, h)
        cv.save(name, OUT)
        out[name] = OUT / f"leaf_{name}_color.png"
        print("leaf", name, w, h)
    return out


# ------------------------------------------------------------------ bark (seamless)
def fbm_periodic(n, m, rng, beta=2.0, aniso=(1.0, 1.0), lo=1.0, hi=None):
    """Periodic 1/f^beta noise via the FFT (seamless by construction). aniso stretches the
    features: (sx, sy) > 1 makes them longer along that axis."""
    fy = np.fft.fftfreq(n)[:, None] * n * aniso[1]
    fx = np.fft.rfftfreq(m)[None, :] * m * aniso[0]
    f = np.sqrt(fx ** 2 + fy ** 2)
    f[0, 0] = 1.0
    amp = 1.0 / f ** (beta / 2)
    amp[f < lo] = 0.0
    if hi:
        amp[f > hi] *= np.exp(-(f[f > hi] - hi) / hi)
    ph = rng.uniform(0, 2 * np.pi, amp.shape)
    spec = amp * np.exp(1j * ph)
    x = np.fft.irfft2(spec, s=(n, m))
    x = (x - x.mean()) / (x.std() + 1e-9)
    return x


def voronoi_periodic(n, m, pts, aspect=(1.0, 1.0)):
    """F1, F2 distances (pixels) and cell ids of periodic Voronoi seeds (pts in 0..1)."""
    from scipy.spatial import cKDTree
    P = []
    ids = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for i, (x, y) in enumerate(pts):
                P.append(((x + dx) * m / aspect[0], (y + dy) * n / aspect[1]))
                ids.append(i)
    tree = cKDTree(P)
    yy, xx = np.mgrid[0:n, 0:m]
    q = np.stack([xx.ravel() / aspect[0], yy.ravel() / aspect[1]], axis=1)
    d, idx = tree.query(q, k=2)
    ids = np.array(ids)
    return d[:, 0].reshape(n, m), d[:, 1].reshape(n, m), ids[idx[:, 0]].reshape(n, m)


def warp(img, dx, dy):
    n, m = img.shape
    yy, xx = np.mgrid[0:n, 0:m]
    from scipy.ndimage import map_coordinates
    return map_coordinates(img, [(yy + dy) % n, (xx + dx) % m], order=1, mode="wrap")


def norm01(a):
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def bark(sp, seed=7):
    """Height (0.5 flat), cavity mask, ridge mask, colour detail for one species."""
    wm, hm = BARK[sp]
    px_per_m = 1024 / max(wm, hm)
    m, n = int(round(wm * px_per_m / 8) * 8), int(round(hm * px_per_m / 8) * 8)
    rng = np.random.default_rng(seed + hash_s(sp))
    wx = fbm_periodic(n, m, rng, 2.6, (1, 1), 1, 12) * 10
    wy = fbm_periodic(n, m, rng, 2.6, (1, 1), 1, 12) * 10
    fine = fbm_periodic(n, m, rng, 1.6, (1, 1), 4)
    color = np.ones((n, m, 3), np.float32)
    if sp in ("pagoda", "ginkgo"):
        # interlacing vertical ridges: stretched noise -> ridged, warped
        k = 6 if sp == "pagoda" else 5
        base = fbm_periodic(n, m, rng, 2.0, (0.18, 7.0), 2.5, 60)
        base = warp(base, wx * 0.45, wy * 0.2)
        ridge = 1 - np.abs(np.tanh(base * 1.2))
        net = warp(fbm_periodic(n, m, rng, 2.0, (0.3, 5.0), 3, 80), wx * 0.3, wy * 0.1)
        h = 0.65 * norm01(ridge) ** 0.7 + 0.25 * norm01(net) + 0.1 * norm01(fine)
        if sp == "ginkgo":
            h = h ** 0.8      # corkier, deeper
        cav = np.clip(1 - h / 0.38, 0, 1)
        rid = np.clip((h - 0.62) / 0.3, 0, 1)
    elif sp == "pine":
        # irregular plates separated by deep fissures (vertically elongated cells)
        pts = rng.random((26, 2))
        f1, f2, ids = voronoi_periodic(n, m, pts, (1.0, 2.2))
        edge = np.clip((f2 - f1) / (m * 0.035), 0, 1)
        plates = edge ** 0.5
        flakes = norm01(fbm_periodic(n, m, rng, 1.8, (1, 1), 6))
        tone = np.random.default_rng(seed).random(len(pts))[ids]
        h = 0.72 * plates + 0.18 * flakes * plates + 0.1 * tone * plates
        cav = np.clip(1 - edge / 0.25, 0, 1)
        rid = np.clip((plates - 0.75) / 0.25, 0, 1) * (flakes > 0.5)
        color *= (0.85 + 0.3 * tone[..., None])
    elif sp == "zelkova":
        # smooth grey bark, scaly plates flaking off to an orange-brown under-bark
        pts = rng.random((90, 2))
        f1, f2, ids = voronoi_periodic(n, m, pts, (1.0, 1.6))
        edge = np.clip((f2 - f1) / (m * 0.012), 0, 1)
        peel = np.random.default_rng(seed + 1).random(len(pts))[ids] < 0.2
        h = 0.55 + 0.12 * norm01(fine) - 0.12 * (1 - edge) * peel - 0.1 * peel
        h = np.clip(h, 0, 1)
        cav = np.clip(1 - edge / 0.3, 0, 1) * peel * 0.8
        rid = (~peel).astype(np.float32) * edge
        under = np.array([0.78, 0.48, 0.28])
        color = np.where(peel[..., None], under[None, None, :] * 1.15, color)
        # lenticels: small horizontal dashes
        len_ = np.zeros((n, m), np.float32)
        for _ in range(500):
            x, y = rng.integers(0, m), rng.integers(0, n)
            l = rng.integers(3, 9)
            len_[y % n, (x + np.arange(l)) % m] = 1
        color *= (1 - 0.3 * len_[..., None])
    elif sp == "cherry":
        # smooth, glossy, horizontal lenticel bands and peeling horizontal strips
        bands = fbm_periodic(n, m, rng, 2.5, (6.0, 0.15), 1, 30)
        h = 0.55 + 0.1 * norm01(bands) + 0.06 * norm01(fine)
        len_ = np.zeros((n, m), np.float32)
        rows = rng.choice(n, 120)
        for y in rows:
            for _ in range(int(rng.integers(3, 9))):
                x = rng.integers(0, m)
                l = int(rng.integers(10, 60))
                t = int(rng.integers(2, 5))
                len_[(y + np.arange(t)[:, None]) % n, (x + np.arange(l)[None, :]) % m] = 1
        from scipy.ndimage import gaussian_filter
        len_ = gaussian_filter(len_, 0.8, mode="wrap")
        h = h + 0.18 * len_
        peel = norm01(fbm_periodic(n, m, rng, 2.2, (5.0, 0.3), 2, 40)) > 0.82
        h = np.where(peel, h + 0.08, h)
        cav = np.clip(len_ * 1.5, 0, 1)
        rid = peel.astype(np.float32)
        color *= (1 - 0.35 * len_[..., None])
        color = np.where(peel[..., None], color * np.array([1.15, 1.05, 1.0]), color)
    elif sp == "cedar":
        # long fibrous strips peeling vertically
        fib = fbm_periodic(n, m, rng, 1.6, (0.06, 12.0), 2, 120)
        fib = warp(fib, wx * 0.6, wy * 0.2)
        str_ = fbm_periodic(n, m, rng, 2.4, (0.15, 5.0), 1, 20)
        h = 0.55 * norm01(fib) + 0.35 * norm01(str_) + 0.1 * norm01(fine)
        cav = np.clip(1 - h / 0.35, 0, 1)
        rid = np.clip((h - 0.7) / 0.3, 0, 1)
        color *= (0.85 + 0.3 * norm01(str_)[..., None])
    elif sp == "palm":
        # Phoenix trunk: diamond leaf-base scars on a spiral lattice
        yy, xx = np.mgrid[0:n, 0:m]
        u = xx / m * 4
        v = yy / n * 4
        a = (u + v) % 1.0
        b = (u - v) % 1.0
        d = np.minimum.reduce([a, 1 - a, b, 1 - b])
        cush = np.clip(d / 0.5, 0, 1) ** 0.6
        h = 0.3 + 0.55 * cush + 0.15 * norm01(fine)
        cav = np.clip(1 - d / 0.07, 0, 1)
        rid = np.clip((cush - 0.7) / 0.3, 0, 1)
        fib = norm01(fbm_periodic(n, m, rng, 1.5, (1, 1), 8))
        color *= (0.8 + 0.35 * fib[..., None])
    else:
        raise ValueError(sp)
    h = np.clip(h, 0, 1)
    OUT.mkdir(parents=True, exist_ok=True)

    def save_l(a, fn, alpha=None):
        g = (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)
        if alpha is None:
            Image.fromarray(g, "L").save(OUT / fn)
        else:
            al = (np.clip(alpha, 0, 1) * 255 + 0.5).astype(np.uint8)
            Image.fromarray(np.dstack([np.full_like(g, 255)] * 3 + [al]), "RGBA").save(OUT / fn)
    save_l(h, f"bark_{sp}_height.png")
    save_l(None if False else cav, f"bark_{sp}_cavity.png", cav)
    save_l(rid, f"bark_{sp}_ridge.png", rid)
    col = (np.clip(color, 0, 1.5) / 1.5 * 255 + 0.5).astype(np.uint8)
    Image.fromarray(col, "RGB").save(OUT / f"bark_{sp}_color.png")
    print("bark", sp, m, n)


def hash_s(s):
    import zlib
    return zlib.crc32(s.encode()) & 0xFFFF


def preview():
    """A contact sheet of every leaf cell over grey (target/trees/stencils.png)."""
    ims = []
    for name in LEAF_CELLS:
        p = OUT / f"leaf_{name}_color.png"
        if p.exists():
            im = Image.open(p).convert("RGBA")
            im.thumbnail((300, 600))
            bg = Image.new("RGBA", im.size, (120, 125, 130, 255))
            bg.alpha_composite(im)
            ims.append(bg)
    for sp in BARK:
        p = OUT / f"bark_{sp}_height.png"
        if p.exists():
            im = Image.open(p).convert("RGBA")
            im.thumbnail((300, 600))
            ims.append(im)
    W = sum(i.width for i in ims[:8]) + 10 * 8
    sheet = Image.new("RGB", (max(W, 1200), 1300), (40, 40, 40))
    x = y = 0
    rowh = 0
    for im in ims:
        if x + im.width > sheet.width:
            x = 0
            y += rowh + 10
            rowh = 0
        sheet.paste(im, (x, y))
        x += im.width + 10
        rowh = max(rowh, im.height)
    os.makedirs(ROOT / "target" / "trees", exist_ok=True)
    sheet.save(ROOT / "target" / "trees" / "stencils.png")
    print("preview ->", ROOT / "target" / "trees" / "stencils.png")


def main():
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
    leaf_cells(only)
    for sp in BARK:
        if only and f"bark_{sp}" not in only:
            continue
        bark(sp)
    if "--preview" in sys.argv:
        preview()


if __name__ == "__main__":
    main()
