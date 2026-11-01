"""The cracked-glass overlay for damaged windscreens (system Python: numpy + Pillow).

    python tools/damage/make_glass_crack.py [--pigment <pigment-mcp.exe>]
        ->  game/assets/damage/glass_crack.png   (512 px, white, alpha = cracks)

The fine crack web is painted in Pigment: a 1 m flat sheet with a fill layer masked by the
`cell_edges` generator (scripts/glass_crack.jsonl, run through `pigment-mcp --script`). This script
then adds the impact star: radial cracks from the centre and broken concentric rings, and fades the
web out with distance from the centre, so it reads as one stone / crash hit. Without the Pigment
binary a numpy Voronoi web stands in. The game projects it on the pane around the impact point
(game/scripts/damage/glass_crack.gdshader).
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "game", "assets", "damage", "glass_crack.png")
N = 512
rng = np.random.default_rng(23)


def pigment_web(exe):
    tmp = tempfile.mkdtemp(prefix="glass_crack_")
    script = os.path.join(tmp, "crack.jsonl")
    steps = [
        {"tool": "new_project", "args": {"resolution": 1024, "tile": {"name": "GlassCrack", "size_m": [1, 1],
                                                                      "cells": [{"name": "crack", "size_m": [1, 1]}], "padding_px": 0}}},
        {"tool": "add_layer", "args": {"name": "web", "kind": "fill", "values": {"base_color": [0.95, 0.97, 1.0], "opacity": 1.0, "roughness": 0.2},
                                       "mask": {"generator": "cell_edges", "scale": 9, "edge_width": 0.004, "seed": 7}}},
        {"tool": "export_textures", "args": {"dir": tmp.replace("\\", "/") + "/out", "preset": "godot"}},
    ]
    with open(script, "w") as f:
        f.write("\n".join(json.dumps(s) for s in steps) + "\n")
    subprocess.run([exe, "--script", script], check=True, capture_output=True)
    a = np.array(Image.open(os.path.join(tmp, "out", "DecalAtlas_BaseColorAlpha.png")).convert("RGBA").resize((N, N), Image.LANCZOS))
    web = a[..., 3].astype(np.float32)
    lo = np.percentile(web, 50)
    return np.clip((web - lo) / max(1.0, web.max() - lo), 0, 1), "pigment"


def numpy_web():
    pts = rng.uniform(0, N, (110, 2))
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    d = np.sqrt((xx[..., None] - pts[:, 0]) ** 2 + (yy[..., None] - pts[:, 1]) ** 2)
    d.sort(axis=2)
    return np.clip(1.0 - (d[..., 1] - d[..., 0]) / 2.5, 0, 1), "numpy"


def main():
    exe = sys.argv[sys.argv.index("--pigment") + 1] if "--pigment" in sys.argv else os.path.join(ROOT, "target", "release", "pigment-mcp.exe")
    try:
        web, src = pigment_web(exe) if os.path.exists(exe) else numpy_web()
    except Exception as e:  # noqa: BLE001
        print("pigment run failed, numpy web instead:", e)
        web, src = numpy_web()
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    r = np.sqrt((xx - N / 2) ** 2 + (yy - N / 2) ** 2) / (N / 2)
    web *= np.clip(1.15 - r * 1.25, 0, 1) ** 1.5
    star = Image.new("L", (N, N), 0)
    dr = ImageDraw.Draw(star)
    c = N / 2
    # radial cracks: wandering lines out from the hit
    for _ in range(17):
        ang = rng.uniform(0, 2 * np.pi)
        x, y = c, c
        length = rng.uniform(0.45, 0.98) * N / 2
        steps = 24
        for k in range(steps):
            ang += rng.normal(0, 0.09)
            nx, ny = x + np.cos(ang) * length / steps, y + np.sin(ang) * length / steps
            w = max(1, int(3.2 * (1 - k / steps)))
            dr.line([(x, y), (nx, ny)], fill=int(255 * (1 - 0.6 * k / steps)), width=w)
            x, y = nx, ny
    # broken rings
    for rad in (0.07, 0.14, 0.24, 0.36):
        rr = rad * N / 2 * rng.uniform(0.9, 1.1)
        a0 = 0.0
        while a0 < 360:
            span = rng.uniform(15, 50)
            if rng.random() < 0.7:
                dr.arc([c - rr, c - rr, c + rr, c + rr], a0, a0 + span, fill=int(255 * (1.1 - rad * 1.5)), width=2)
            a0 += span + rng.uniform(5, 25)
    # the crushed centre
    dr.ellipse([c - 9, c - 9, c + 9, c + 9], fill=230)
    starr = np.array(star.filter(ImageFilter.GaussianBlur(0.6))).astype(np.float32) / 255.0
    alpha = np.clip(np.maximum(starr, web * 0.75), 0, 1)
    img = np.zeros((N, N, 4), np.uint8)
    img[..., :3] = 240
    img[..., 3] = (alpha * 255).astype(np.uint8)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    Image.fromarray(img, "RGBA").save(OUT)
    print(f"{os.path.relpath(OUT, ROOT)} (web: {src})")


if __name__ == "__main__":
    main()
