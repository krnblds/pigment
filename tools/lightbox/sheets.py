"""Contact sheets for the Blender lightbox (plain Python + PIL; Blender's Python has no PIL).

    python tools/lightbox/sheets.py spec.json

spec.json:
    {"out": "docs/agents/lightbox/x.png",
     "rows": [[{"path": "cell.png", "label": "mame / cream"}, ...], ...],
     "cell": [480, 300],          # every cell is resized to this (optional, default: first image)
     "cols": 8,                   # pad rows to this many cells (optional)
     "bg": [0, 0, 0],             # padding colour
     "gap": 0,                    # pixels between cells
     "labels": true,              # small label in the bottom-left corner of each cell
     "title": "optional title bar text",
     "width": 1600,               # final width (keeps aspect), optional
     "max_bytes": 1500000,        # quantise / shrink until the PNG is under this
     "delete_cells": false}

lightbox_scene.py writes such a spec and calls this file with the system Python.
"""
import io
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FONT_DIR = os.path.join(ROOT, "crates", "app", "assets", "fonts")


def font(size, weight="SemiBold"):
    for name in (f"Inter-{weight}.ttf", "Inter-Regular.ttf"):
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def label_cell(im, text, size=None):
    """Small text with a soft dark pill behind it, bottom-left."""
    if not text:
        return im
    im = im.convert("RGB")
    w, h = im.size
    size = size or max(10, int(h * 0.034))
    f = font(size)
    d = ImageDraw.Draw(im, "RGBA")
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    pad = max(3, size // 3)
    tw, th = x1 - x0, y1 - y0
    bx, by = 2 * pad, h - th - 3 * pad          # text box top-left
    d.rounded_rectangle((bx - pad, by - pad, bx + tw + pad, by + th + pad), radius=pad, fill=(0, 0, 0, 110))
    d.text((bx - x0, by - y0), text, font=f, fill=(255, 255, 255, 235))
    return im


def save_small(im, out, max_bytes=1_500_000):
    """PNG under max_bytes: full colour if it fits, else a 256-colour quantised PNG (dithered),
    else shrink by 10 % steps."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    im = im.convert("RGB")
    while True:
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        if buf.tell() <= max_bytes:
            break
        q = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True)
        if buf.tell() <= max_bytes:
            break
        im = im.resize((int(im.width * 0.9), int(im.height * 0.9)), Image.LANCZOS)
    with open(out, "wb") as fh:
        fh.write(buf.getvalue())
    print(f"[sheets] {out} {im.size[0]}x{im.size[1]} {buf.tell() / 1e6:.2f} MB")
    return out


def grid(rows, out, cell=None, cols=None, bg=(0, 0, 0), gap=0, labels=True, title=None, width=None,
         max_bytes=1_500_000, delete_cells=False, label_size=None):
    first = next(c for r in rows for c in r if c)
    if cell is None:
        cell = Image.open(first["path"]).size
    cw, ch = cell
    cols = cols or max(len(r) for r in rows)
    if width:
        # scale cells to their final size first, so labels are sized in final pixels
        full = cols * cw + (cols - 1) * gap
        sc = width / full
        cw, ch, gap = round(cw * sc), round(ch * sc), round(gap * sc)
    th = 0
    if title:
        th = max(28, int(ch * 0.16))
    W = cols * cw + (cols - 1) * gap
    H = th + len(rows) * ch + (len(rows) - 1) * gap
    sheet = Image.new("RGB", (W, H), tuple(bg))
    if title:
        d = ImageDraw.Draw(sheet)
        f = font(int(th * 0.5), "SemiBold")
        lum = sum(bg) / 3
        d.text((int(th * 0.35), int(th * 0.22)), title, font=f, fill=(20, 20, 24) if lum > 128 else (240, 240, 245))
    for ri, r in enumerate(rows):
        for ci, c in enumerate(r):
            if not c:
                continue
            im = Image.open(c["path"]).convert("RGB")
            if im.size != (cw, ch):
                im = im.resize((cw, ch), Image.LANCZOS)
            if labels:
                im = label_cell(im, c.get("label", ""), label_size)
            sheet.paste(im, (ci * (cw + gap), th + ri * (ch + gap)))
    if width and width != W:
        sheet = sheet.resize((width, round(H * width / W)), Image.LANCZOS)   # rounding only
    save_small(sheet, out, max_bytes)
    if delete_cells:
        for r in rows:
            for c in r:
                if c and os.path.exists(c["path"]):
                    os.remove(c["path"])
    return out


def main():
    spec = json.load(open(sys.argv[1]))
    grid(spec["rows"], spec["out"], cell=spec.get("cell"), cols=spec.get("cols"), bg=spec.get("bg", (0, 0, 0)),
         gap=spec.get("gap", 0), labels=spec.get("labels", True), title=spec.get("title"),
         width=spec.get("width"), max_bytes=spec.get("max_bytes", 1_500_000),
         delete_cells=spec.get("delete_cells", False), label_size=spec.get("label_size"))


if __name__ == "__main__":
    main()
