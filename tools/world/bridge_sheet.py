"""Compose the bridge design options sheet (docs/agents/bridges/design_options.png) from the clay
renders listed by bridge_options.py --sheet (.citycache/bridges/options.json)."""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def font(sz, bold=False):
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def main(lst):
    shots = json.load(open(lst))
    order = ["port", "expressway", "kagero", "tenjin"]
    rows = [d for d in order if any(s["design"] == d for s in shots)]
    W, Hh, top, head = 640, 360, 30, 34
    sheet = Image.new("RGB", (W * 3 + 40, len(rows) * (Hh + top + head) + 70), (18, 19, 22))
    dr = ImageDraw.Draw(sheet)
    dr.text((20, 18), "Bridge design options: massing in clay at the real sites (world.json deck line, grades, piers)", font=font(24, True), fill=(235, 235, 235))
    y = 70
    for d in rows:
        row = [s for s in shots if s["design"] == d]
        dr.text((20, y), row[0]["title"], font=font(22, True), fill=(240, 200, 120))
        y += head
        for k, s in enumerate(row):
            im = Image.open(s["path"]).convert("RGB").resize((W - 10, Hh - 10))
            x = 20 + k * W
            sheet.paste(im, (x, y + top))
            chosen = "chosen" in s["label"]
            dr.text((x, y + 4), s["label"], font=font(15, chosen), fill=(255, 255, 255) if chosen else (190, 190, 190))
            if chosen:
                dr.rectangle([x - 3, y + top - 3, x + W - 7, y + top + Hh - 7], outline=(240, 200, 120), width=3)
        y += Hh + top
    p = os.path.join(ROOT, "docs", "agents", "bridges", "design_options.png")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    sheet.save(p, optimize=True)
    print("sheet ->", p)


if __name__ == "__main__":
    main(sys.argv[1])
