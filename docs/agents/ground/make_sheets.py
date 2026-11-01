"""Tile sheets for docs/agents/ground: before (the old world tiles) / after (the
Pigment ground sets) and every new set, each as flat albedo, a 2 x 2 repeat
lit at a grazing angle and a sphere at grazing light (tools/ground_preview.py).
Also stitches the Cycles and Godot shots into side-by-sides.

    python docs/agents/ground/make_sheets.py tiles
    python docs/agents/ground/make_sheets.py pairs <before dir> <after dir> <out.png> name,name,... [--labels a,b]
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ground_preview as GP  # noqa: E402

TEX = os.path.join(ROOT, "scenes", "town", "textures", "world")
OUT = os.path.join(ROOT, "docs", "agents", "ground")


def save(im, path, colors=256):
    """Palette PNG (keeps the docs images small)."""
    im.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(path, optimize=True)
    print(path, os.path.getsize(path) // 1024, "KB")


def stack(rows, gap=6):
    W = max(r.width for r in rows)
    H = sum(r.height for r in rows) + gap * (len(rows) - 1)
    out = Image.new("RGB", (W, H), (16, 16, 16))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + gap
    return out


def side(a, b, gap=10):
    out = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height)), (16, 16, 16))
    out.paste(a, (0, 0))
    out.paste(b, (a.width + gap, 0))
    return out


def tiles(size=256):
    pairs = [("rock", "rock_cliff"), ("grass", "grass_turf"), ("dirt", "dirt_mud"), ("sand", "beach_sand")]
    rows = []
    for old, new in pairs:
        a = GP.row(os.path.join(TEX, old), size, f"before: {old}")
        b = GP.row(os.path.join(TEX, new), size, f"after: {new}")
        rows.append(side(a, b))
    save(stack(rows), os.path.join(OUT, "tiles_before_after.png"))
    sets = ["rock_cliff", "scree", "forest_floor", "grass_turf", "dirt_mud", "beach_sand", "cracked_mud", "cobbles", "vacant_lot"]
    left = [GP.row(os.path.join(TEX, s), size) for s in sets[:5]]
    right = [GP.row(os.path.join(TEX, s), size) for s in sets[5:]]
    save(side(stack(left), stack(right)), os.path.join(OUT, "ground_sets.png"))


def label(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 12 + 9 * len(text), 26], fill=(0, 0, 0))
    d.text((6, 4), text, fill=(240, 240, 240), font=GP.font(17))
    return im


def pairs(bdir, adir, out, names, labels=("before", "after"), w=800):
    rows = []
    for n in names:
        ims = []
        for d, lab, suf in ((bdir, labels[0], "_before"), (adir, labels[1], "")):
            p = os.path.join(d, n + suf + ".png")
            if not os.path.isfile(p):
                p = os.path.join(d, n + ".png")
            im = Image.open(p).convert("RGB")
            im = im.resize((w, int(w * im.height / im.width)), Image.LANCZOS)
            ims.append(label(im, f"{n}: {lab}"))
        rows.append(side(*ims))
    save(stack(rows), out)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "tiles":
        tiles()
    elif a[0] == "pairs":
        labs = a[a.index("--labels") + 1].split(",") if "--labels" in a else ("before", "after")
        pairs(a[1], a[2], a[3], a[4].split(","), labs)
