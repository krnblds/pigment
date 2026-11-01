"""Composite render_trees.py `sheet` tiles into a labelled contact sheet (system Python, PIL).

    python tools/trees/contact_sheet.py OUT.jpg key1,key2,... [--suffix _night_lod0] [--cols 6]
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent


def main():
    out = sys.argv[1]
    keys = sys.argv[2].split(",")
    suffix = "_lod0"
    cols = 6
    for i, a in enumerate(sys.argv):
        if a == "--suffix":
            suffix = sys.argv[i + 1]
        if a == "--cols":
            cols = int(sys.argv[i + 1])
    idx = json.load(open(ROOT / "assets" / "trees" / "index.json", encoding="utf-8"))["variants"]
    tiles = []
    for k in keys:
        p = ROOT / "target" / "trees" / "tiles" / f"{k}{suffix}.png"
        if p.exists():
            tiles.append((k, Image.open(p).convert("RGB")))
    w, h = tiles[0][1].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 44)), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("arial.ttf", 20)
        f2 = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        f = f2 = ImageFont.load_default()
    for i, (k, im) in enumerate(tiles):
        x, y = (i % cols) * w, (i // cols) * (h + 44)
        sheet.paste(im, (x, y))
        v = idx.get(k, {})
        d.text((x + 8, y + h + 3), k.replace("tree_", ""), fill=(235, 235, 235), font=f)
        t = v.get("tris", {})
        d.text((x + 8, y + h + 25), f"{v.get('height', 0):.1f} m   LOD0 {t.get('lod0', 0)}  LOD1 {t.get('lod1', 0)}  LOD2 8 tris",
               fill=(160, 160, 165), font=f2)
    sheet.save(out, quality=88)
    print("sheet ->", out, sheet.size)


if __name__ == "__main__":
    main()
