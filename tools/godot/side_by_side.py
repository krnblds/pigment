"""Side-by-side comparison strips: Godot screenshots vs Cycles renders of the same camera spots.

    python tools/godot/side_by_side.py --out docs/agents/roadlook --width 640 \
        "before (game, main)=<dir>" "after (game)=<dir>" "Blender / Cycles=<dir>" -- avenue junction curb wet

Each <dir> holds spot_<name>.png (game: automation.gd --bench-spots) or <name>.png (Cycles:
tools/world/world_render.py --cams <dir>/cams.json). Writes <out>/<name>_compare.png per spot.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def main():
    a = sys.argv[1:]
    out = a[a.index("--out") + 1]
    width = int(a[a.index("--width") + 1]) if "--width" in a else 640
    cols, names = [], []
    rest = [x for i, x in enumerate(a) if x not in ("--out", "--width") and (i == 0 or a[i - 1] not in ("--out", "--width"))]
    sep = rest.index("--")
    for c in rest[:sep]:
        label, d = c.split("=", 1)
        cols.append((label, d))
    names = rest[sep + 1:]
    os.makedirs(out, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for n in names:
        tiles = []
        for label, d in cols:
            p = next((os.path.join(d, f) for f in (f"spot_{n}.png", f"{n}.png") if os.path.isfile(os.path.join(d, f))), None)
            im = Image.open(p).convert("RGB") if p else Image.new("RGB", (16, 9))
            im = im.resize((width, int(width * im.height / im.width)), Image.LANCZOS)
            ImageDraw.Draw(im).text((10, 8), f"{label} - {n}", fill=(255, 255, 120), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
            tiles.append(im)
        h = max(t.height for t in tiles)
        strip = Image.new("RGB", (sum(t.width for t in tiles) + 4 * (len(tiles) - 1), h), (20, 20, 20))
        x = 0
        for t in tiles:
            strip.paste(t, (x, 0))
            x += t.width + 4
        dst = os.path.join(out, f"{n}_compare.png")
        strip.save(dst, optimize=True)
        print(dst, os.path.getsize(dst) // 1024, "KB")


main()
