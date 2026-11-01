"""Previews of exported Pigment texture sets (numpy, no GPU): flat albedo, a
2 x 2 repeat of the tile lit at a grazing angle, and a sphere at grazing light.
Used for docs/agents/ground (the before / after tile sheet).

    python tools/ground_preview.py <set folder> [<set folder> ...] --out sheet.png [--size 384] [--labels a,b]

A set folder holds <name>_BaseColor.png, _Normal_OpenGL.png, _Roughness.png,
_AO.png (Pigment's `separate` export).
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load(folder, size=None):
    d = Path(folder)
    name = d.name

    def img(m, mode, default=None):
        p = d / f"{name}_{m}.png"
        if not p.is_file():
            return default
        im = Image.open(p)
        if size:
            im = im.resize((size, size), Image.LANCZOS)
        a = np.asarray(im.convert(mode), dtype=np.float32) / (255.0 if im.mode != "I;16" else 65535.0)
        return a
    c = img("BaseColor", "RGB")
    n = img("Normal_OpenGL", "RGB")
    s = c.shape[0]
    r = img("Roughness", "L", np.full((s, s), 0.8, np.float32))
    ao = img("AO", "L", np.ones((s, s), np.float32))
    return {"color": c ** 2.2, "normal": n * 2 - 1, "rough": r, "ao": ao}


def tonemap(x):
    x = np.clip(x, 0, None)
    x = x / (1 + x * 0.15)
    return (np.clip(x, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def shade(col, n, rough, ao, L, V=np.array([0.0, 0.0, 1.0]), sun=3.2, amb=0.12):
    """Lambert + GGX-ish spec for a directional light; n in the plane frame (z up)."""
    L = L / np.linalg.norm(L)
    H = (L + V) / np.linalg.norm(L + V)
    ndl = np.clip((n * L).sum(-1), 0, 1)
    ndh = np.clip((n * H).sum(-1), 0, 1)
    a = np.clip(rough, 0.04, 1) ** 2
    d = ndh * ndh * (a * a - 1) + 1
    spec = np.minimum((a * a) / (math.pi * d * d + 1e-6), 30.0) * 0.02 * ndl
    return col * (ndl[..., None] * sun + amb * ao[..., None]) + spec[..., None] * sun


def flat(m):
    return tonemap(m["color"] * 1.0)


def grazing(m, elev=14.0, az=35.0, rep=2):
    col = np.tile(m["color"], (rep, rep, 1))
    n = np.tile(m["normal"], (rep, rep, 1))
    n = n / np.linalg.norm(n, axis=-1, keepdims=True)
    r = np.tile(m["rough"], (rep, rep))
    ao = np.tile(m["ao"], (rep, rep))
    e, a = math.radians(elev), math.radians(az)
    L = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    return tonemap(shade(col, n, r, ao, L, sun=3.0 / max(math.sin(e) * 2.2, 0.35)))


def sphere(m, size, elev=18.0, az=-40.0, rep=2.0):
    """A sphere with the tile wrapped `rep` times around its equator (lat-long),
    lit from a low angle; the normal map perturbs the surface frame."""
    h, w = m["color"].shape[:2]
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    px = (xs + 0.5) / size * 2 - 1
    py = 1 - (ys + 0.5) / size * 2
    rr = px * px + py * py
    inside = rr < 1
    pz = np.sqrt(np.clip(1 - rr, 0, 1))
    N = np.stack([px, py, pz], -1)
    lon = np.arctan2(px, pz)
    lat = np.arcsin(np.clip(py, -1, 1))
    u = (lon / (2 * math.pi) + 0.5) * rep * 2
    v = (0.5 - lat / math.pi) * rep
    iu = ((u % 1) * w).astype(int) % w
    iv = ((v % 1) * h).astype(int) % h
    col = m["color"][iv, iu]
    tn = m["normal"][iv, iu]
    r = m["rough"][iv, iu]
    ao = m["ao"][iv, iu]
    T = np.stack([np.cos(lon), np.zeros_like(lon), -np.sin(lon)], -1)
    B = np.cross(N, T)
    n = tn[..., 0:1] * T + tn[..., 1:2] * B + tn[..., 2:3] * N
    n = n / np.linalg.norm(n, axis=-1, keepdims=True)
    e, a = math.radians(elev), math.radians(az)
    L = np.array([math.cos(e) * math.sin(a), math.sin(e), math.cos(e) * math.cos(a)])
    img = tonemap(shade(col, n, r, ao, L, sun=2.6))
    bg = np.full_like(img, 24)
    return np.where(inside[..., None], img, bg)


def font(sz):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            continue
    return ImageFont.load_default()


def row(folder, size, label=None):
    m = load(folder, size)
    tiles = [Image.fromarray(flat(m)), Image.fromarray(grazing(m)).resize((size, size), Image.LANCZOS), Image.fromarray(sphere(m, size))]
    out = Image.new("RGB", (size * 3 + 8, size + 26), (16, 16, 16))
    for k, t in enumerate(tiles):
        out.paste(t, (k * (size + 4), 26))
    ImageDraw.Draw(out).text((6, 4), label or Path(folder).name, fill=(230, 230, 230), font=font(17))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    size = 384
    out = "ground_sheet.png"
    labels = None
    if "--size" in a:
        i = a.index("--size")
        size = int(a[i + 1])
        del a[i:i + 2]
    if "--out" in a:
        i = a.index("--out")
        out = a[i + 1]
        del a[i:i + 2]
    if "--labels" in a:
        i = a.index("--labels")
        labels = a[i + 1].split(",")
        del a[i:i + 2]
    rows = [row(f, size, labels[k] if labels else None) for k, f in enumerate(a)]
    W = max(r.width for r in rows)
    sheet = Image.new("RGB", (W, sum(r.height for r in rows)), (16, 16, 16))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(out)
    print(out)
