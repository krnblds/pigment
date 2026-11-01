"""Proof sheets for docs/agents/bridges/.

    python tools/world/bridge_sheet.py .citycache/bridges/options.json      design_options.png (bridge_options.py --sheet)
    python tools/world/bridge_sheet.py --pairs <before dir> <after dir>     <bridge>_before_after.png per bridge:
                                                                           night wide, dusk wide, close-up(s)
"""
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


def pairs(bdir, adir, W=600, H=338):
    tags = ["port", "expressway", "kagero", "tenjin"]
    for tag in tags:
        names = [n for n in sorted(os.listdir(adir)) if n.startswith(tag + "_") and n.endswith(".png")]
        order = [f"{tag}_night_wide.png", f"{tag}_dusk_wide.png"] + [n for n in names if "wide" not in n]
        order = [n for n in order if os.path.isfile(os.path.join(adir, n))]
        if not order:
            continue
        head = 40
        sheet = Image.new("RGB", (2 * W + 30, len(order) * (H + 28) + head + 10), (18, 19, 22))
        dr = ImageDraw.Draw(sheet)
        dr.text((10, 8), f"{tag}: before (left)  /  after (right), Cycles, same cameras", font=font(22, True), fill=(235, 235, 235))
        y = head
        for n in order:
            dr.text((10, y + 4), n[:-4].replace(tag + "_", ""), font=font(16), fill=(200, 200, 200))
            for k, d in enumerate((bdir, adir)):
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    sheet.paste(Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS), (10 + k * (W + 10), y + 24))
            y += H + 28
        out = os.path.join(ROOT, "docs", "agents", "bridges", f"{tag}_before_after.png")
        sheet.save(out, optimize=True)
        print(out, os.path.getsize(out) // 1024, "KB")


def godot(bdir, adir, names, out, W=600, H=338):
    """Godot screenshots (game --bridge-shots) before | after in one sheet."""
    head = 40
    sheet = Image.new("RGB", (2 * W + 30, len(names) * (H + 28) + head + 10), (18, 19, 22))
    dr = ImageDraw.Draw(sheet)
    dr.text((10, 8), "Godot (game --bridge-shots): before (left)  /  after (right)", font=font(22, True), fill=(235, 235, 235))
    y = head
    for n in names:
        dr.text((10, y + 4), n.replace("godot_", ""), font=font(16), fill=(200, 200, 200))
        for k, d in enumerate((bdir, adir)):
            pth = os.path.join(d, n + ".png")
            if os.path.isfile(pth):
                sheet.paste(Image.open(pth).convert("RGB").resize((W, H), Image.LANCZOS), (10 + k * (W + 10), y + 24))
        y += H + 28
    sheet.save(out, optimize=True)
    print(out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    if sys.argv[1] == "--godot":
        godot(sys.argv[2], sys.argv[3], sys.argv[5].split(","), sys.argv[4])
    elif sys.argv[1] == "--pairs":
        pairs(sys.argv[2], sys.argv[3])
    else:
        main(sys.argv[1])
