"""Product window for the vending machine: lit shelves of drink cans.

    python tools/make_vending_products.py   ->  assets/decals/vending_products.png
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 840, 1540  # matches the machine's display bay (about 0.55 : 1)
SHELVES = 4
random.seed(7)
FONT = None
for f in ("C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/msgothic.ttc", "C:/Windows/Fonts/arialbd.ttf"):
    if Path(f).exists():
        FONT = f
        break

PALETTE = [
    ((230, 40, 60), (255, 255, 255), "炭酸"),
    ((20, 120, 230), (255, 255, 255), "水"),
    ((250, 200, 30), (30, 30, 30), "茶"),
    ((40, 190, 90), (255, 255, 255), "緑"),
    ((250, 110, 20), (255, 255, 255), "橙"),
    ((240, 60, 170), (255, 255, 255), "夢"),
    ((20, 20, 24), (0, 230, 255), "電"),
    ((240, 240, 240), (220, 30, 40), "乳"),
]

img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)
# lit interior: bright at the top (the light), slightly darker lower down
for y in range(H):
    t = y / H
    c = int(235 - 40 * t)
    d.line([(0, y), (W, y)], fill=(c, c, min(255, c + 8)))

shelf_h = H // SHELVES
font_big = ImageFont.truetype(FONT, 46) if FONT else None
font_small = ImageFont.truetype(FONT, 22) if FONT else None
for s in range(SHELVES):
    top = s * shelf_h
    base = top + shelf_h - 40  # shelf surface
    n = 5
    can_w = W // n - 26
    can_h = int(shelf_h * 0.62)
    for i in range(n):
        body, ink, word = random.choice(PALETTE)
        x0 = 18 + i * (W // n)
        y0 = base - can_h
        # can body with a rim and a highlight
        d.rounded_rectangle([x0, y0, x0 + can_w, base], radius=18, fill=body)
        d.rectangle([x0 + 6, y0 - 10, x0 + can_w - 6, y0 + 4], fill=(170, 170, 175))
        d.rectangle([x0 + 10, y0 + 12, x0 + 22, base - 12], fill=tuple(min(255, c + 60) for c in body))
        if font_big:
            tw = d.textlength(word, font=font_big)
            d.text((x0 + (can_w - tw) / 2, y0 + can_h * 0.32), word, font=font_big, fill=ink)
        # price tag on the shelf edge
        price = random.choice(["¥120", "¥150", "¥160", "¥200"])
        d.rectangle([x0 + 8, base + 8, x0 + can_w - 8, base + 32], fill=(20, 20, 20))
        if font_small:
            d.text((x0 + 16, base + 8), price, font=font_small, fill=(255, 220, 60))
    # shelf lip
    d.rectangle([0, base, W, base + 6], fill=(120, 120, 128))

img = img.filter(ImageFilter.GaussianBlur(0.6))
out = Path(__file__).resolve().parent.parent / "assets" / "decals" / "vending_products.png"
img.convert("RGBA").save(out)
print("wrote", out, img.size)
