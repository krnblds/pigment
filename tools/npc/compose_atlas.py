"""Paint each citizen's 1024 atlas from the spec build_citizens.py wrote (system Python: numpy + Pillow).

    python tools/npc/compose_atlas.py [--src .npccache/citizens] [--only id,id]

Per <id>.json it writes, next to it:
  <id>_albedo.png  RGB = colour (sRGB), A = alpha (hair / brows cut-out)
  <id>_normal.png  tangent-space normal (OpenGL convention, flat where a part has none)
  <id>_mask.png    R = roughness, G = rain response (how much the surface darkens / glosses when wet),
                   B = emission (1.0 = glowing trims)
Cells: MakeHuman textures resized into their cell and tinted (recipe "tints"); the procedural shell gets a
fabric for its kind (fleece, ripstop, satin nylon, twill, PVC, hi-vis mesh) in the recipe colour; trims are
painted from the UV triangles in the spec.
"""
import json
import math
import os
import sys
import glob
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
argv = sys.argv[1:]
SRC = argv[argv.index("--src") + 1] if "--src" in argv else os.path.join(ROOT, ".npccache", "citizens")
ONLY = set(filter(None, (argv[argv.index("--only") + 1] if "--only" in argv else "").split(",")))
S = 1024

ROUGH = {"body": 0.55, "eyes": 0.15, "brows": 0.8, "hair": 0.55, "clothes": 0.82, "shoes": 0.45, "acc": 0.5, "band": 0.25}
WET = {"body": 0.35, "eyes": 0.0, "brows": 0.3, "hair": 0.9, "clothes": 1.0, "shoes": 0.8, "acc": 0.6, "band": 0.2,
       "shell": 1.0, "skirt": 1.0, "collar": 1.0}
FABRIC = {  # kind: (roughness, pattern)
    "hoodie": (0.9, "fleece"), "jacket": (0.5, "ripstop"), "bomber": (0.38, "satin"), "coat": (0.7, "twill"),
    "raincoat": (0.16, "pvc"), "hivis": (0.62, "mesh"),
}


def srgb(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.clip(c, 0, 1), 1 / 2.4) - 0.055)


def load(p, size, mode="RGBA"):
    im = Image.open(p).convert(mode)
    return np.asarray(im.resize((size, size), Image.LANCZOS), np.float32) / 255.0


def rgb_to_hsv(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a[..., :3].max(-1)
    mn = a[..., :3].min(-1)
    d = mx - mn + 1e-8
    h = np.where(mx == r, (g - b) / d % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6.0
    s = np.where(mx > 0, (mx - mn) / (mx + 1e-8), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    out = np.zeros(h.shape + (3,), np.float32)
    for k, (a, b, c) in enumerate(((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))):
        m = i == k
        out[m] = np.stack([a[m], b[m], c[m]], -1)
    return out


def tint(rgb, t):
    h, s, v = rgb_to_hsv(rgb)
    h = (h + t.get("hue", 0.0)) % 1.0
    s = np.clip(s * t.get("sat", 1.0), 0, 1)
    v = np.clip(v * t.get("value", 1.0), 0, 1)
    return hsv_to_rgb(h, s, v)


def noise(size, scale, seed):
    rng = np.random.default_rng(seed)
    n = max(2, int(size / scale))
    small = Image.fromarray((rng.random((n, n)) * 255).astype(np.uint8))
    return np.asarray(small.resize((size, size), Image.BICUBIC), np.float32) / 255.0


def fabric(kind, colour, size, seed):
    """(rgb sRGB, roughness, height) for the shell fabric of `kind`."""
    rough, pat = FABRIC.get(kind, (0.7, "twill"))
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    base = np.ones((size, size), np.float32)
    h = np.zeros((size, size), np.float32)
    if pat == "fleece":
        h = noise(size, 1.5, seed) * 0.6 + noise(size, 10, seed + 1) * 0.4
        base = 0.9 + 0.12 * (h - 0.5)
    elif pat == "ripstop":
        g = ((x % 4) < 0.8) | ((y % 4) < 0.8)
        h = g.astype(np.float32) * 0.8 + noise(size, 2, seed) * 0.2
        base = 1.0 - 0.06 * g + 0.04 * (noise(size, 40, seed + 2) - 0.5)
    elif pat == "satin":
        q = (np.sin(y / size * math.pi * 90) > 0.9).astype(np.float32)   # quilting lines
        h = 1 - q * 0.8 + noise(size, 3, seed) * 0.05
        base = 1.0 - 0.12 * q + 0.08 * (noise(size, 60, seed + 3) - 0.5)
    elif pat == "twill":
        h = 0.5 + 0.5 * np.sin((x + y) * 2.4) * 0.6 + noise(size, 2, seed) * 0.3
        base = 0.94 + 0.08 * (h - 0.5) + 0.06 * (noise(size, 50, seed + 4) - 0.5)
    elif pat == "pvc":
        h = noise(size, 80, seed) * 0.2
        base = 1.0 + 0.05 * (noise(size, 90, seed + 5) - 0.5)
    else:  # mesh
        g = ((x % 5) < 2) & ((y % 5) < 2)
        h = g.astype(np.float32)
        base = 1.0 - 0.08 * g
    rgb = np.clip(np.asarray(srgb(colour))[None, None, :] * base[..., None], 0, 1)
    return rgb, rough, h


def height_to_normal(h, strength=2.0):
    gy, gx = np.gradient(h)
    n = np.stack([-gx * strength, gy * strength, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


CATS = {"body": 1, "shell": 2, "skirt": 3, "collar": 4}


def posmap(entries):
    """Rasterise the UV triangles: per texel bind-pose xyz (P) and part id (C)."""
    P = np.zeros((S, S, 3), np.float32)
    C = np.zeros((S, S), np.uint8)
    for e in entries:
        cid = CATS.get(e["cat"], 0)
        for t in e["tris"]:
            a = np.array(t[0:2]); b = np.array(t[2:4]); c = np.array(t[4:6])
            x0, x1 = int(max(0, math.floor(min(a[0], b[0], c[0])))), int(min(S - 1, math.ceil(max(a[0], b[0], c[0]))))
            y0, y1 = int(max(0, math.floor(min(a[1], b[1], c[1])))), int(min(S - 1, math.ceil(max(a[1], b[1], c[1]))))
            if x1 < x0 or y1 < y0:
                continue
            yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float32) + 0.5
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-9:
                continue
            l1 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / d
            l2 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / d
            l3 = 1 - l1 - l2
            e_ = -0.02
            inside = (l1 >= e_) & (l2 >= e_) & (l3 >= e_)
            if not inside.any():
                continue
            pa, pb, pc = np.array(t[6:9]), np.array(t[9:12]), np.array(t[12:15])
            pos = l1[..., None] * pa + l2[..., None] * pb + l3[..., None] * pc
            sub = P[y0:y1 + 1, x0:x1 + 1]
            sub[inside] = pos[inside]
            C[y0:y1 + 1, x0:x1 + 1][inside] = cid
    return P, C


def trim_mask(P, C, M, sh):
    """1 where the shell gets its trim colour (MPFB space: x left+, y back+, z up)."""
    x, y, z = P[..., 0], P[..., 1], P[..., 2]
    shell = (C == 2) | (C == 3) | (C == 4)
    out = np.zeros(C.shape, np.float32)
    if not shell.any():
        return out
    zmin = z[shell].min()
    kind = sh["kind"]
    front = y < 0
    wr = np.minimum(np.linalg.norm(P - M["wrist_l"], axis=-1), np.linalg.norm(P - M["wrist_r"], axis=-1))
    zs = z[(C == 3)] if (C == 3).any() else z[shell]
    hem = z < zs.min() + 0.018
    cuffs = (wr < 0.075) & (wr > 0.045) & (C == 2)
    m = hem | cuffs
    if kind != "hoodie":
        m |= (np.abs(x) < 0.004) & front & (C == 2)                      # zip
    if kind == "hivis" or (kind == "raincoat" and sh.get("trim")):
        for zz in (M["spine3"][2] - 0.08, M["pelvis"][2] + 0.12):
            m |= (np.abs(z - zz) < 0.016) & (C == 2)
    return (m & shell).astype(np.float32)


def compose(spec_path):
    sp = json.load(open(spec_path))
    cid = sp["id"]
    rc = sp["recipe"]
    tints = rc.get("tints", {})
    alb = np.zeros((S, S, 4), np.float32)
    alb[..., 3] = 1.0
    nrm = np.zeros((S, S, 3), np.float32)
    nrm[...] = (0.5, 0.5, 1.0)
    msk = np.zeros((S, S, 3), np.float32)
    msk[..., 0] = 0.8
    for k, c in enumerate(sp["cells"]):
        x, y, s = c["rect"]
        cat = c["cat"]
        sl = (slice(y, y + s), slice(x, x + s))
        if c.get("fill") is not None and cat in ("shell", "skirt", "collar"):
            rgb, rough, h = fabric(c.get("kind"), c["fill"], s, zlib.crc32(cid.encode()) % 1000 + k)
            alb[sl][..., :3] = rgb
            nrm[sl] = height_to_normal(h, 1.5)
            msk[sl][..., 0] = rough
            msk[sl][..., 1] = WET.get(cat, 1.0)
            continue
        if cat == "band":
            alb[sl][..., :3] = srgb(c["fill"])
            msk[sl] = (0.25, 0.2, 1.0)
            continue
        if c.get("albedo"):
            a = load(c["albedo"], s)
            rgb = a[..., :3]
            if cat == "clothes" and "base" in tints:
                rgb = tint(rgb, tints["base"])
            if cat == "hair" and "hair" in tints:
                rgb = tint(rgb, {"value": tints["hair"].get("value", 1.0), "sat": 0.85 if tints["hair"].get("value", 1) > 1.1 else 1.0})
                if "hair_dye" in tints:      # dyed: blend toward the neon colour at the tips (lower half of the card UVs)
                    yy = np.linspace(0, 1, s, dtype=np.float32)[:, None, None]
                    dye = np.asarray(srgb(tints["hair_dye"]))[None, None, :]
                    rgb = rgb * (1 - 0.6 * yy) + dye * rgb.mean(-1, keepdims=True) * 1.6 * 0.6 * yy
            alb[sl][..., :3] = np.clip(rgb, 0, 1)
            if cat in ("hair", "brows"):
                alb[sl][..., 3] = a[..., 3]
        else:
            alb[sl][..., :3] = 0.3
        if c.get("normal"):
            nrm[sl] = load(c["normal"], s, "RGB")
        msk[sl][..., 0] = ROUGH.get(cat, 0.7)
        msk[sl][..., 1] = WET.get(cat, 0.5)
    # trims, piping and reflective bands: rules on the bind-pose position map
    P, C = posmap(sp.get("posmaps", []))
    M = {k: np.asarray(v, np.float32) for k, v in sp.get("metrics", {}).items()}
    sh = rc.get("shell")
    if sh and sh.get("trim") and M:
        tm = trim_mask(P, C, M, sh)
        tm = np.asarray(Image.fromarray((tm * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)), np.float32)[..., None] / 255.0
        alb[..., :3] = alb[..., :3] * (1 - tm) + np.asarray(srgb(sh["trim"]))[None, None, :] * tm
        msk[..., 0] = msk[..., 0] * (1 - tm[..., 0]) + 0.3 * tm[..., 0]
        if sh.get("trim_glow", 0) > 0:
            msk[..., 2] = np.maximum(msk[..., 2], tm[..., 0])
    base = os.path.splitext(spec_path)[0]
    Image.fromarray((np.clip(alb, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(base + "_albedo.png", optimize=False)
    Image.fromarray((np.clip(nrm, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB").save(base + "_normal.png")
    Image.fromarray((np.clip(msk, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB").save(base + "_mask.png")
    return cid


def main():
    specs = sorted(glob.glob(os.path.join(SRC, "*.json")))
    n = 0
    for p in specs:
        cid = os.path.splitext(os.path.basename(p))[0]
        if ONLY and cid not in ONLY:
            continue
        compose(p)
        n += 1
    print("atlases: %d citizens in %s" % (n, SRC))


if __name__ == "__main__":
    main()
