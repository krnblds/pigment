"""Side-by-side before/after sheets from the renders in target/pg/ (see NOTES.md)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "target" / "pg"
DST = Path(__file__).resolve().parent

try:
    FONT = ImageFont.truetype("arial.ttf", 22)
except OSError:
    FONT = ImageFont.load_default()


def sheet(out, rows, scale=1.0, max_bytes=1_450_000):
    imgs = [[Image.open(SRC / f).convert("RGB") for f, _ in row] for row in rows]
    h = max(i.height for row in imgs for i in row)
    imgs = [[i.resize((round(i.width * h / i.height), h)) for i in row] for row in imgs]
    w = max(sum(i.width for i in row) for row in imgs)
    canvas = Image.new("RGB", (w, h * len(rows)), (20, 20, 22))
    d = ImageDraw.Draw(canvas)
    for r, (row, labels) in enumerate(zip(imgs, rows)):
        x = 0
        for img, (_, label) in zip(row, labels):
            canvas.paste(img, (x, r * h))
            d.rectangle([x + 8, r * h + 8, x + 16 + d.textlength(label, font=FONT), r * h + 40], fill=(0, 0, 0))
            d.text((x + 12, r * h + 10), label, fill=(255, 255, 255), font=FONT)
            x += img.width
    while True:
        im = canvas.resize((round(canvas.width * scale), round(canvas.height * scale)), Image.LANCZOS) if scale != 1.0 else canvas
        im.save(DST / out, optimize=True)
        if (DST / out).stat().st_size <= max_bytes:
            break
        scale *= 0.85
    print(out, im.size, (DST / out).stat().st_size)


sheet("building_leaks.png", [[("building_a_before_ac.png", "before"), ("building_a_after_ac.png", "after: leaks (drip bake)")]])
sheet("building_ledges.png", [[("building_a_before_top_rough.png", "before (roughness)"), ("building_a_after_top_rough.png", "after: rain water + leaks (roughness)")]], 0.8)
sheet("street_puddles.png", [[("street_before_road.png", "before: grunge puddles"), ("street_after_road.png", "after: puddles generator")],
                             [("street_before_road_rough.png", "before (roughness)"), ("street_after_road_rough.png", "after (roughness)")]], 0.7)
sheet("tower_windows_tiles.png", [[("tower_before_front.png", "before"), ("tower_after_front.png", "after: window grid, bricks, leaks"),
                                   ("tower_after_close.png", "close-up")]], 0.8)
sheet("blender_night.png", [[("night_before.png", "Blender, before"), ("night_after.png", "Blender, after")]], 0.75)
