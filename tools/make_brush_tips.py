"""Procedural brush tips (alphas) for Pigment's brush engine.

Writes 256 x 256 grayscale PNGs to assets/brushes/ (white = paint) plus
assets/brushes/index.json. Deterministic (fixed seeds).

    python tools/make_brush_tips.py
"""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

N = 256
OUT = Path(__file__).resolve().parents[1] / "assets/brushes"
yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
u = (xx + 0.5) / N * 2 - 1
v = (yy + 0.5) / N * 2 - 1
r = np.sqrt(u * u + v * v)


def vnoise(scale, seed, octaves=4):
    rng = np.random.default_rng(seed)
    out = np.zeros((N, N), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        s = int(scale * 2 ** o)
        g = rng.random((s + 1, s + 1)).astype(np.float32)
        img = Image.fromarray((g * 255).astype(np.uint8)).resize((N, N), Image.BICUBIC)
        out += np.asarray(img, np.float32) / 255 * amp
        tot += amp
        amp *= 0.5
    return out / tot


def disc_fade(edge=0.15):
    return np.clip((1 - r) / edge, 0, 1)


def save(name, a):
    a = np.clip(a, 0, 1)
    Image.fromarray((a * 255).astype(np.uint8), "L").save(OUT / f"{name}.png", optimize=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tips = {}
    tips["round"] = ("Round, soft edge", np.clip((1 - r) / 0.35, 0, 1) ** 1.5)
    tips["square"] = ("Square, hard edge", ((np.abs(u) < 0.8) & (np.abs(v) < 0.8)).astype(np.float32))
    n = vnoise(6, 1)
    tips["chalk"] = ("Chalk: grainy disc", disc_fade(0.3) * np.clip((n - 0.35) * 3, 0, 1))
    rng = np.random.default_rng(2)
    spray = np.zeros((N, N), np.float32)
    for _ in range(900):
        a = rng.random() * math.tau
        d = abs(rng.normal(0, 0.45))
        if d > 0.95:
            continue
        x, y = int((math.cos(a) * d * 0.5 + 0.5) * N), int((math.sin(a) * d * 0.5 + 0.5) * N)
        rr = rng.integers(1, 3)
        spray[max(0, y - rr):y + rr, max(0, x - rr):x + rr] = rng.uniform(0.5, 1)
    tips["spray"] = ("Spray: airbrush dots", spray)
    img = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(3)
    d.ellipse([70, 70, 186, 186], fill=255)
    for _ in range(40):
        a = rng.random() * math.tau
        dist = rng.uniform(55, 120)
        rad = rng.uniform(3, 16) * (1 - dist / 140)
        cx, cy = 128 + math.cos(a) * dist, 128 + math.sin(a) * dist
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=255)
        if rng.random() < 0.4:
            d.line([128 + math.cos(a) * 50, 128 + math.sin(a) * 50, cx, cy], fill=255, width=max(1, int(rad * 0.6)))
    tips["splatter"] = ("Splatter: paint splash", np.asarray(img.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255)
    img = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(4)

    def crack(x, y, a, length, w, depth):
        for _ in range(int(length / 6)):
            a += rng.normal(0, 0.35)
            nx, ny = x + math.cos(a) * 6, y + math.sin(a) * 6
            d.line([x, y, nx, ny], fill=255, width=max(1, int(w)))
            x, y = nx, ny
            w *= 0.97
            if depth < 3 and rng.random() < 0.08:
                crack(x, y, a + rng.choice([-1, 1]) * rng.uniform(0.5, 1.1), length * 0.5, w * 0.7, depth + 1)

    for k in range(4):
        crack(128, 128, k * math.pi / 2 + rng.normal(0, 0.3), 120, 4, 0)
    tips["cracks"] = ("Cracks: branching fractures", np.asarray(img.filter(ImageFilter.GaussianBlur(0.7)), np.float32) / 255 * disc_fade(0.25))
    img = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(5)
    for _ in range(26):
        a = rng.normal(0.25, 0.25)
        cx, cy = rng.uniform(40, 216, 2)
        ln = rng.uniform(40, 160)
        dx, dy = math.cos(a) * ln / 2, math.sin(a) * ln / 2
        d.line([cx - dx, cy - dy, cx + dx, cy + dy], fill=int(rng.uniform(120, 255)), width=1 if rng.random() < 0.7 else 2)
    tips["scratches"] = ("Scratches: thin parallel scuffs", np.asarray(img, np.float32) / 255 * disc_fade(0.3))
    for k, (sc, seed) in enumerate([(4, 7), (10, 8)]):
        g = vnoise(sc, seed, 5)
        tips[f"grunge_{k + 1}"] = (f"Grunge stamp {k + 1}", disc_fade(0.4) * np.clip((g - 0.45) * 4, 0, 1))
    img = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(9)
    for _ in range(7):
        a = rng.random() * math.tau
        cx, cy = 128 + rng.normal(0, 40), 128 + rng.normal(0, 40)
        L, W = rng.uniform(40, 70), rng.uniform(14, 24)
        pts = []
        for t in np.linspace(0, 1, 24):
            w = math.sin(t * math.pi) * W
            pts.append((t * L - L / 2, w))
        pts += [(x, -y) for x, y in reversed(pts)]
        rot = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
        d.polygon(rot, fill=int(rng.uniform(180, 255)))
        d.line([rot[0], rot[23]], fill=60, width=1)
    tips["leaves"] = ("Leaves: a scatter of leaf shapes", np.asarray(img.filter(ImageFilter.GaussianBlur(0.6)), np.float32) / 255 * disc_fade(0.2))
    rng = np.random.default_rng(10)
    dots = np.zeros((N, N), np.float32)
    for _ in range(60):
        cx, cy = rng.uniform(-0.8, 0.8, 2)
        rr = rng.uniform(0.02, 0.09)
        dots = np.maximum(dots, np.clip((rr - np.sqrt((u - cx) ** 2 + (v - cy) ** 2)) / 0.01, 0, 1))
    tips["dots"] = ("Dots: random round specks", dots * disc_fade(0.15))
    index = []
    for name, (label, a) in tips.items():
        save(name, a)
        index.append({"id": name, "label": label, "file": f"{name}.png"})
    (OUT / "index.json").write_text(json.dumps({"tips": index}, indent=2) + "\n")
    print(f"wrote {len(index)} tips to {OUT}")


if __name__ == "__main__":
    main()
