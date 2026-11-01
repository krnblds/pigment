"""Decals for the street props (story content: Hoshikawa, MERIDIAN, Dreamlink, Noctis, UNPLUG).

    python tools/props/make_prop_decals.py      ->  assets/decals/props/*.png

Street names, bus-stop ads, kiosk / meter / phone screens, vending fronts,
holo-pylon ads, marquee texts, stall menus and noren, stencils, stickers and
puddle shapes.  Full-colour unless noted "glyph" (white, tinted + emissive in
Pigment).  Drawn at 2x and downsampled like tools/make_decals.py.
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from make_decals import ARIAL_B, BAHN, BLACK, IMPACT, JP_BOLD, JP_REG, MONO, SS, STENCIL, canvas, font, graffiti  # noqa: E402
from make_story_decals import eye, has_cjk, noise_overlay  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "..", "assets", "decals", "props")

INK = (20, 20, 22, 255)
WHITE = (240, 242, 240, 255)
CYAN = (110, 230, 255, 255)
MER_BG = (8, 22, 40, 255)
RED = (220, 30, 45, 255)
AMBER = (255, 170, 30, 255)


def lf(txt, size, f=None):
    if has_cjk(txt):
        return font(JP_BOLD, size)
    return font(f or BAHN, size)


def fit(d, txt, max_w, max_h, f=None, start=400):
    size = int(start)
    while size > 6:
        fo = lf(txt, size, f)
        bb = d.textbbox((0, 0), txt, font=fo)
        if bb[2] - bb[0] <= max_w and bb[3] - bb[1] <= max_h:
            return fo
        size -= max(1, size // 20)
    return lf(txt, 6, f)


def save_img(img, w, h, long_side=1024):
    """Downsample the 2x canvas to the long side (keeps aspect, no crop)."""
    s = long_side / max(w, h)
    return img.convert("RGBa").resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS).convert("RGBA")


def card(w, h, bg, rows, border=None, radius=0, pad=0.06, long_side=1024, noise=8, seed=1):
    """rows: [(text, colour, weight[, font])] stacked top to bottom; weight = share of the height.
    text may be a callable(d, box) that draws itself into box (x0, y0, x1, y1)."""
    s = SS
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    if bg:
        d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=radius * s, fill=bg)
    if border:
        bw = max(2, int(min(w, h) * 0.025)) * s
        d.rounded_rectangle([bw, bw, w * s - bw, h * s - bw], radius=max(0, radius - 4) * s, outline=border, width=bw)
    px, py = w * pad * s, h * pad * s
    tot = sum(r[2] for r in rows)
    y = py
    H = h * s - 2 * py
    for r in rows:
        txt, col, wt = r[0], r[1], r[2]
        f = r[3] if len(r) > 3 else None
        rh = H * wt / tot
        box = (px, y, w * s - px, y + rh)
        if callable(txt):
            txt(d, box)
        elif txt:
            fo = fit(d, txt, box[2] - box[0], rh * 0.78, f)
            d.text(((box[0] + box[2]) / 2, y + rh / 2), txt, font=fo, fill=col, anchor="mm")
        y += rh
    img = save_img(img, w, h, long_side)
    return noise_overlay(img, seed, noise) if noise else img


def glyph(lines, w, h, f=BAHN, vertical=False, long_side=1024, gap=0.08):
    """White glyphs on transparent, filling the w x h frame (for tinted emissive)."""
    s = SS
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    if vertical:
        chars = list(lines[0])
        ch = h * s / len(chars)
        for i, c in enumerate(chars):
            fo = fit(d, c, w * s * 0.9, ch * (1 - gap), f)
            d.text((w * s / 2, ch * (i + 0.5)), c, font=fo, fill=(255, 255, 255, 255), anchor="mm")
    else:
        lh = h * s / len(lines)
        for i, ln in enumerate(lines):
            fo = fit(d, ln, w * s * 0.94, lh * (1 - gap), f)
            d.text((w * s / 2, lh * (i + 0.5)), ln, font=fo, fill=(255, 255, 255, 255), anchor="mm")
    return save_img(img, w, h, long_side)


# ------------------------------------------------------------------ icons

def eye_icon(col, crossed=False, scale=0.42):
    def draw(d, box):
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        r = min(box[2] - box[0], (box[3] - box[1]) * 1.6) * scale
        eye(d, cx, cy, r, col, max(2, int(r * 0.1)), crossed=crossed)
    return draw


def walker(d, cx, cy, hgt, col, walking=True):
    """Pictogram: walking (green) or standing (red) person."""
    u = hgt / 10
    d.ellipse([cx - u * 0.9, cy - hgt / 2, cx + u * 0.9, cy - hgt / 2 + u * 1.8], fill=col)
    w = int(u * 1.2)
    if walking:
        hip, sh = (cx, cy + u * 0.8), (cx + u * 0.3, cy - hgt / 2 + u * 2.6)
        d.line([sh, hip], fill=col, width=int(u * 1.5))
        d.line([hip, (cx + u * 2.2, cy + u * 3), (cx + u * 2.6, cy + hgt / 2)], fill=col, width=w, joint="curve")
        d.line([hip, (cx - u * 1.0, cy + u * 3.2), (cx - u * 2.6, cy + hgt / 2 - u * 0.4)], fill=col, width=w, joint="curve")
        d.line([(cx + u * 0.3, cy - u * 1.6), (cx + u * 2.2, cy + u * 0.2)], fill=col, width=w)
        d.line([(cx + u * 0.3, cy - u * 1.6), (cx - u * 1.8, cy - u * 0.2)], fill=col, width=w)
    else:
        d.rounded_rectangle([cx - u * 1.3, cy - hgt / 2 + u * 2.2, cx + u * 1.3, cy + u * 1.2], radius=u * 0.5, fill=col)
        d.line([(cx - u * 0.6, cy + u), (cx - u * 0.6, cy + hgt / 2)], fill=col, width=w)
        d.line([(cx + u * 0.6, cy + u), (cx + u * 0.6, cy + hgt / 2)], fill=col, width=w)
        d.line([(cx - u * 1.3, cy - u * 2.2), (cx - u * 1.7, cy + u * 0.8)], fill=col, width=w)
        d.line([(cx + u * 1.3, cy - u * 2.2), (cx + u * 1.7, cy + u * 0.8)], fill=col, width=w)


def ped_lens(walking):
    s = SS
    img = canvas(512, 512)
    d = ImageDraw.Draw(img)
    walker(d, 256 * s, 256 * s, 400 * s, (255, 255, 255, 255), walking)
    return save_img(img, 512, 512, 512)


def qr(d, box, seed=4):
    rnd = random.Random(seed)
    x0, y0, x1, y1 = box
    side = min(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    n = 21
    c = side / n
    ox, oy = cx - side / 2, cy - side / 2
    d.rectangle([ox, oy, ox + side, oy + side], fill=WHITE)
    for i in range(n):
        for j in range(n):
            finder = (i < 7 and j < 7) or (i >= n - 7 and j < 7) or (i < 7 and j >= n - 7)
            if finder:
                ii, jj = i % (n - 7) if i >= n - 7 else i, j % (n - 7) if j >= n - 7 else j
                on = ii in (0, 6) or jj in (0, 6) or (2 <= ii <= 4 and 2 <= jj <= 4)
            else:
                on = rnd.random() < 0.5
            if on:
                d.rectangle([ox + i * c, oy + j * c, ox + (i + 1) * c, oy + (j + 1) * c], fill=INK)


def gradient_bg(img, c0, c1):
    d = ImageDraw.Draw(img)
    H = img.height
    for y in range(H):
        t = y / H
        d.line([0, y, img.width, y], fill=tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3)) + (255,))


# ------------------------------------------------------------------ ads (portrait 0.63)

def ad(kind):
    W, H = 640, 1016
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    if kind == "noctis":
        gradient_bg(img, (40, 4, 30), (5, 0, 12))
        d.ellipse([170 * s, 140 * s, 470 * s, 440 * s], fill=(255, 210, 120, 255))
        d.ellipse([215 * s, 120 * s, 520 * s, 420 * s], fill=(40, 4, 30, 255))
        rows = [("NOCTIS", (255, 210, 120, 255), 1.3, BLACK), ("SELL A NIGHT.", WHITE, 0.6), ("KEEP THE DAY.", WHITE, 0.6),
                ("夜を売れ", (255, 90, 160, 255), 0.6), ("memories · sleep cycles · more", (200, 160, 190, 255), 0.35)]
        top = 0.5
    elif kind == "dreamlink":
        gradient_bg(img, (10, 30, 70), (80, 20, 120))
        for i in range(9):
            r = (60 + i * 34) * s
            d.ellipse([W * s / 2 - r, 300 * s - r * 0.6, W * s / 2 + r, 300 * s + r * 0.6], outline=(140, 200, 255, 120), width=3 * s)
        d.text((W * s / 2, 300 * s), "夢", font=font(JP_BOLD, 190 * s), fill=(235, 245, 255, 255), anchor="mm")
        rows = [("DREAMLINK", (150, 220, 255, 255), 1.0), ("SLEEP IS WORK.", WHITE, 0.6), ("GET PAID TO DREAM", WHITE, 0.5),
                ("a Hoshikawa company", (160, 170, 210, 255), 0.35)]
        top = 0.5
    elif kind == "meridian":
        gradient_bg(img, (6, 18, 34), (14, 50, 80))
        eye(d, W * s / 2, 290 * s, 210 * s, CYAN, 16 * s)
        rows = [("MERIDIAN", (235, 250, 255, 255), 1.0), ("CARES.", CYAN, 0.8), ("YOUR SCORE IS", WHITE, 0.45), ("YOUR FUTURE", WHITE, 0.45),
                ("612 ▲", (120, 255, 160, 255), 0.6, MONO)]
        top = 0.5
    elif kind == "security":
        gradient_bg(img, (30, 30, 34), (8, 8, 10))
        d.polygon([(W * s / 2, 110 * s), (W * s / 2 + 170 * s, 190 * s), (W * s / 2 + 140 * s, 400 * s), (W * s / 2, 480 * s),
                   (W * s / 2 - 140 * s, 400 * s), (W * s / 2 - 170 * s, 190 * s)], fill=(200, 30, 40, 255))
        d.text((W * s / 2, 300 * s), "HS", font=font(BLACK, 150 * s), fill=WHITE, anchor="mm")
        rows = [("JOIN", WHITE, 0.6), ("HOSHIKAWA", (230, 60, 60, 255), 0.8), ("SECURITY", WHITE, 0.7), ("PROTECT THE SCORE", (200, 200, 200, 255), 0.45),
                ("+40 pts on enlistment", (230, 180, 60, 255), 0.35)]
        top = 0.5
    else:  # defaced meridian ad
        img = ad("meridian")
        return img
    y0 = H * top * s
    hh = H * s - y0 - 40 * s
    tot = sum(r[2] for r in rows)
    y = y0
    for r in rows:
        rh = hh * r[2] / tot
        fo = fit(d, r[0], W * s * 0.86, rh * 0.8, r[3] if len(r) > 3 else None)
        d.text((W * s / 2, y + rh / 2), r[0], font=fo, fill=r[1], anchor="mm")
        y += rh
    return noise_overlay(save_img(img, W, H), 3, 6)


def ad_defaced():
    base = ad("meridian").copy()
    tag = graffiti("UNPLUG", BLACK, 300, (0, 240, 255, 255), (130, 80, 255, 255), (10, 0, 30, 255), (255, 240, 0, 255), seed=44, drips=10)
    tag = tag.rotate(12, expand=True)
    tw = int(base.width * 0.95)
    tag = tag.resize((tw, int(tag.height * tw / tag.width)), Image.LANCZOS)
    base.alpha_composite(tag, ((base.width - tw) // 2, int(base.height * 0.52)))
    d = ImageDraw.Draw(base)
    cx, cy, r = base.width / 2, base.height * 0.285, base.width * 0.36
    d.line([cx - r, cy + r * 0.7, cx + r, cy - r * 0.7], fill=(255, 30, 60, 255), width=int(base.width * 0.04))
    return base


# ------------------------------------------------------------------ screens

def kiosk_screen(kind):
    W, H = 680, 1040
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    if kind == "score":
        bg, fg, acc = MER_BG, CYAN, (120, 255, 160, 255)
        lines = [("MERIDIAN", fg, 0.7), (eye_icon(fg), None, 1.3), ("CITIZEN 4471-K", WHITE, 0.45), ("SCORE", (150, 190, 210, 255), 0.4),
                 ("612", acc, 1.2, MONO), ("-3 since yesterday", (255, 120, 120, 255), 0.35), ("RENT TIER C · RATIONS 2", WHITE, 0.4),
                 ("PLACE YOUR PALM ON THE SCANNER", fg, 0.35)]
    elif kind == "flagged":
        bg, fg = (40, 4, 8, 255), (255, 70, 80, 255)
        lines = [("MERIDIAN", fg, 0.7), (eye_icon(fg), None, 1.3), ("CITIZEN 2209-M", WHITE, 0.45), ("SCORE 389", fg, 0.9, MONO),
                 ("FLAGGED FOR", WHITE, 0.45), ("RE-EDUCATION", fg, 0.6), ("REPORT TO THE SECTOR OFFICE", WHITE, 0.35), ("再教育対象", fg, 0.5)]
    elif kind == "hacked":
        bg, fg = (5, 5, 5, 255), (0, 255, 160, 255)
        lines = [("MERIDIAN", (60, 90, 80, 255), 0.6), (eye_icon((255, 40, 70, 255), crossed=True), None, 1.4), ("UNPLUG", fg, 1.0, STENCIL),
                 ("THE SCORE IS A LEASH", WHITE, 0.45), ("WE ARE NOT DATA", fg, 0.45), ("抵抗せよ", WHITE, 0.5), ("> override 7G ok_", fg, 0.35, MONO)]
    else:  # dreamlink offer
        bg, fg = (20, 10, 50, 255), (190, 160, 255, 255)
        lines = [("DREAMLINK", fg, 0.7), ("夢", WHITE, 1.3), ("YOUR SCORE QUALIFIES", WHITE, 0.4), ("LEASE 4 NIGHTS", fg, 0.6),
                 ("+18 PTS", (120, 255, 160, 255), 0.9, MONO), ("sleep is work. work is worth.", (200, 190, 230, 255), 0.35), ("TOUCH TO ACCEPT", WHITE, 0.45)]
    d.rectangle([0, 0, W * s, H * s], fill=bg)
    for y in range(0, H * s, 6 * s):  # scan lines
        d.line([0, y, W * s, y], fill=(255, 255, 255, 10), width=s)
    img2 = card(W, H, None, lines, pad=0.07, noise=0)
    out = save_img(img, W, H)
    out.alpha_composite(img2)
    return out


def small_screen(lines, bg, fg, w=640, h=420, f=MONO):
    rows = [(t, fg if i else fg, wt, f) for i, (t, wt) in enumerate(lines)]
    return card(w, h, bg, rows, pad=0.08, noise=0, long_side=512)


# ------------------------------------------------------------------ vending

def vend_front(kind):
    W, H = 600, 1040
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    rnd = random.Random({"drinks": 1, "noctis": 2, "ramen": 3}[kind])
    d.rectangle([0, 0, W * s, H * s], fill=(235, 238, 240, 255) if kind != "noctis" else (16, 8, 24, 255))
    rows, cols = 4, 5
    cw, ch = W * s / cols, H * s / rows
    for r in range(rows):
        d.rectangle([0, (r + 1) * ch - 70 * s, W * s, (r + 1) * ch], fill=(30, 30, 34, 255))
        for c in range(cols):
            x0, y0 = c * cw + 14 * s, r * ch + 30 * s
            x1, y1 = (c + 1) * cw - 14 * s, (r + 1) * ch - 80 * s
            if kind == "drinks":
                col = rnd.choice([(220, 30, 40), (30, 120, 220), (250, 200, 30), (40, 170, 90), (240, 120, 30), (30, 30, 30), (200, 60, 160)])
                d.rounded_rectangle([x0, y0, x1, y1], radius=18 * s, fill=col + (255,))
                d.rectangle([x0, y0 + (y1 - y0) * 0.35, x1, y0 + (y1 - y0) * 0.6], fill=(245, 245, 245, 255))
                d.ellipse([x0 + 10 * s, y0 - 8 * s, x1 - 10 * s, y0 + 16 * s], fill=(200, 200, 205, 255))
            elif kind == "noctis":
                col = rnd.choice([(255, 80, 180), (120, 220, 255), (255, 210, 120), (170, 120, 255)])
                cx = (x0 + x1) / 2
                d.rounded_rectangle([cx - 26 * s, y0 + 10 * s, cx + 26 * s, y1], radius=24 * s, fill=col + (255,))
                d.rectangle([cx - 30 * s, y0, cx + 30 * s, y0 + 26 * s], fill=(200, 200, 210, 255))
                d.ellipse([cx - 12 * s, (y0 + y1) / 2 - 12 * s, cx + 12 * s, (y0 + y1) / 2 + 12 * s], fill=(255, 255, 255, 255))
            else:
                col = rnd.choice([(230, 40, 30), (250, 180, 20), (30, 30, 30), (240, 240, 240)])
                d.polygon([(x0, y0 + 20 * s), (x1, y0 + 20 * s), (x1 - 14 * s, y1), (x0 + 14 * s, y1)], fill=col + (255,))
                d.rectangle([x0 - 4 * s, y0, x1 + 4 * s, y0 + 24 * s], fill=(250, 250, 250, 255))
                d.text(((x0 + x1) / 2, (y0 + y1) / 2 + 10 * s), "麺", font=font(JP_BOLD, 40 * s), fill=(255, 255, 255, 255) if col != (240, 240, 240) else INK, anchor="mm")
            price = {"drinks": rnd.choice([120, 150, 160, 180]), "noctis": rnd.choice([980, 1980, 4800]), "ramen": rnd.choice([280, 320, 400])}[kind]
            d.text(((x0 + x1) / 2, (r + 1) * ch - 35 * s), f"¥{price}", font=font(MONO, 30 * s), fill=(255, 220, 80, 255), anchor="mm")
    return save_img(img, W, H)


def vend_header(kind):
    spec = {"drinks": ([("HOSHIKAWA COLD", WHITE, 1.0), ("つめた〜い", CYAN, 0.6)], (20, 90, 200, 255)),
            "noctis": ([("NOCTIS MEMORIES", (255, 200, 120, 255), 1.0), ("記憶 · one night = one dream", (255, 120, 190, 255), 0.55)], (30, 5, 25, 255)),
            "ramen": ([("RAMEN 24H", WHITE, 1.0), ("カップ麺 · no score needed", (255, 220, 120, 255), 0.55)], (190, 25, 25, 255))}[kind]
    return card(940, 170, spec[1], spec[0], pad=0.06, noise=0)


def vend_side(kind):
    W, H = 650, 1450
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    if kind == "drinks":
        gradient_bg(img, (20, 100, 220), (10, 30, 90))
        d.text((W * s / 2, H * s * 0.45), "COLD", font=font(BLACK, 230 * s), fill=WHITE, anchor="mm")
        d.text((W * s / 2, H * s * 0.62), "冷", font=font(JP_BOLD, 300 * s), fill=CYAN, anchor="mm")
    elif kind == "noctis":
        gradient_bg(img, (40, 5, 35), (5, 0, 10))
        d.text((W * s / 2, H * s * 0.4), "NOCTIS", font=fit(d, "NOCTIS", W * s * 0.9, 300 * s, BLACK), fill=(255, 200, 120, 255), anchor="mm")
        d.text((W * s / 2, H * s * 0.6), "夜", font=font(JP_BOLD, 330 * s), fill=(255, 90, 170, 255), anchor="mm")
    else:
        gradient_bg(img, (200, 30, 25), (90, 10, 10))
        d.text((W * s / 2, H * s * 0.45), "麺", font=font(JP_BOLD, 420 * s), fill=WHITE, anchor="mm")
        d.text((W * s / 2, H * s * 0.7), "24H", font=font(BLACK, 200 * s), fill=(255, 220, 80, 255), anchor="mm")
    return save_img(img, W, H)


# ------------------------------------------------------------------ holo ads (tall 0.29)

def holo(kind):
    W, H = 300, 1040
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    if kind == "dreamlink":
        col = (140, 200, 255)
        top, word, sub = "夢", "DREAMLINK", "sleep is work"
    elif kind == "noctis":
        col = (255, 120, 200)
        top, word, sub = "夜", "NOCTIS", "sell a night"
    elif kind == "meridian":
        col = (110, 230, 255)
        top, word, sub = None, "MERIDIAN", "cares"
    else:
        col = (0, 255, 150)
        top, word, sub = None, "UNPLUG", "not data"
    for y in range(0, H * s, 8 * s):
        d.line([0, y, W * s, y], fill=col + (60,), width=2 * s)
    d.rectangle([6 * s, 6 * s, W * s - 6 * s, H * s - 6 * s], outline=col + (255,), width=6 * s)
    if top:
        d.text((W * s / 2, 190 * s), top, font=font(JP_BOLD, 200 * s), fill=(255, 255, 255, 255), anchor="mm")
    else:
        eye(d, W * s / 2, 190 * s, 110 * s, col + (255,), 12 * s, crossed=(kind == "hacked"))
    # the word runs vertically, letter by letter
    n = len(word)
    y0, y1 = 360 * s, 920 * s
    ch = (y1 - y0) / n
    for i, c in enumerate(word):
        d.text((W * s / 2, y0 + ch * (i + 0.5)), c, font=font(BLACK, int(ch * 0.85)), fill=col + (255,), anchor="mm")
    d.text((W * s / 2, 975 * s), sub, font=fit(d, sub, W * s * 0.85, 50 * s), fill=(255, 255, 255, 230), anchor="mm")
    return save_img(img, W, H)


# ------------------------------------------------------------------ misc shapes

def puddle(seed, w=1200, h=900):
    rnd = random.Random(seed)
    s = 1
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    cx, cy = w / 2, h / 2
    for _ in range(14):
        rx, ry = rnd.uniform(0.12, 0.3) * w, rnd.uniform(0.12, 0.3) * h
        ox, oy = rnd.uniform(-0.2, 0.2) * w, rnd.uniform(-0.18, 0.18) * h
        d.ellipse([cx + ox - rx, cy + oy - ry, cx + ox + rx, cy + oy + ry], fill=255)
    img = img.filter(ImageFilter.GaussianBlur(28))
    img = img.point(lambda v: 0 if v < 90 else min(255, int((v - 90) * 3)))
    img = img.filter(ImageFilter.GaussianBlur(6))
    out = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    out.putalpha(img)
    return out


def noren_text():
    s = SS
    W, H = 1840, 400
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    for i, c in enumerate("ラーメン"):
        d.text(((i + 0.5) * W * s / 4, H * s * 0.55), c, font=font(JP_BOLD, 300 * s), fill=(245, 245, 240, 255), anchor="mm")
    return save_img(img, W, H)


def street(jp, en, sub, bg=(20, 110, 70, 255)):
    return card(1050, 240, bg, [(jp + "  " + en, WHITE, 1.0), (sub, (210, 230, 220, 255), 0.45)], border=WHITE, radius=18, pad=0.07, noise=6)


def decals():
    D = {}
    # street names (blades ~4.4:1, mast blade 4.25:1)
    D["street_hoshikawa_dori"] = lambda: street("星川通り", "HOSHIKAWA-DORI", "< 1-7  |  8-15 >")
    D["street_kioku_zaka"] = lambda: street("記憶坂", "KIOKU-ZAKA", "< SECTOR 7G  |  MARKET >")
    D["street_neon_yokocho"] = lambda: street("ネオン横丁", "NEON YOKOCHO", "< NIGHT MARKET  |  NO VEHICLES")
    D["street_meridian_ave"] = lambda: street("メリディアン通り", "MERIDIAN AVE", "< HOSHIKAWA HQ  |  SCORE GATE 500+", bg=(16, 50, 110, 255))
    D["street_shin_yume"] = lambda: street("新夢三丁目", "SHIN-YUME 3", "< DREAMLINK CENTRE  |  PORT >")
    D["route_plate"] = lambda: card(360, 460, (250, 200, 20, 255), [("第7区", INK, 0.8), ("SECTOR 7", INK, 0.6), ("CURFEW", RED, 0.5), ("01:00", INK, 0.7, MONO)],
                                    border=INK, radius=14, noise=10)
    D["push_button"] = lambda: card(500, 350, (240, 240, 235, 255), [("押ボタン", INK, 1.0), ("PUSH TO CROSS", INK, 0.6), ("MERIDIAN LOGS EVERY PRESS", RED, 0.35)],
                                    border=INK, radius=10, long_side=512)
    D["ped_walk"] = lambda: ped_lens(True)
    D["ped_stop"] = lambda: ped_lens(False)
    D["ped_count"] = lambda: small_screen([("12", 1.0)], (5, 5, 5, 255), (255, 140, 30, 255), w=480, h=280)
    # bus stop
    D["bus_route_flag"] = lambda: card(550, 550, (240, 240, 235, 255), [(lambda d, b: (d.ellipse([b[0] + (b[2] - b[0]) * 0.2, b[1], b[2] - (b[2] - b[0]) * 0.2, b[3]], fill=(200, 30, 40, 255)),
                                                                                             d.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), "42", font=font(BLACK, int((b[3] - b[1]) * 0.6)), fill=WHITE, anchor="mm")), None, 1.6),
                                                                         ("BUS STOP", INK, 0.5), ("星川交通 HOSHIKAWA TRANSIT", INK, 0.35)], border=INK, radius=30)
    D["bus_timetable"] = lambda: small_screen([("LINE 42 > HQ", 0.9), ("NEXT  3 MIN", 0.8), ("      9 MIN", 0.8), ("     16 MIN", 0.8),
                                               ("SCORE GATE 500+", 0.7), ("BOARDING BY FACE", 0.6)], (6, 10, 18, 255), (255, 180, 40, 255), w=540, h=800)
    for k in ("noctis", "dreamlink", "meridian", "security"):
        D[f"ad_{k}"] = (lambda kk: lambda: ad(kk))(k)
    D["ad_defaced"] = ad_defaced
    # kiosk / meter / phone screens
    for k in ("score", "flagged", "hacked", "dreamlink"):
        D[f"kiosk_{k}"] = (lambda kk: lambda: kiosk_screen(kk))(k)
    D["parking_screen"] = lambda: small_screen([("PAY BY SCORE", 0.8), ("¥400 / 30 MIN", 0.9), ("-2 PTS IF LATE", 0.6)], (8, 16, 10, 255), (120, 255, 150, 255), w=640, h=420)
    D["phone_header"] = lambda: card(740, 120, (25, 25, 30, 255), [("PUBLIC LINE 公衆回線 · ALL CALLS MONITORED", (255, 220, 120, 255), 1.0)], pad=0.08, noise=0)
    D["phone_screen"] = lambda: small_screen([("DIAL OR SAY A NAME", 0.7), ("CALL COST: 1 PT/MIN", 0.7)], (6, 14, 20, 255), CYAN, w=720, h=320)
    D["meridian_plate"] = lambda: card(600, 360, MER_BG, [(eye_icon(CYAN, scale=0.3), None, 1.2), ("MERIDIAN WATCHES", CYAN, 0.6), ("OVER SECTOR 7 · FOR YOUR SAFETY", WHITE, 0.4)],
                                       border=CYAN, radius=16)
    D["meridian_sticker"] = lambda: card(512, 512, (245, 245, 245, 255), [(eye_icon(MER_BG, scale=0.3), None, 1.3), ("MERIDIAN LINKED", MER_BG, 0.5), ("tampering lowers your score", (90, 90, 90, 255), 0.3)],
                                         border=MER_BG, radius=250, pad=0.2, long_side=512)
    D["drone_plate"] = lambda: card(1000, 500, (250, 200, 20, 255), [("HOSHIKAWA AERIAL", INK, 0.8), ("DRONE PORT 07", INK, 1.0), ("KEEP CLEAR · 離れてください", INK, 0.6)], border=INK, radius=12)
    D["drone_pad"] = lambda: card(1024, 1024, None, [(lambda d, b: (d.ellipse([b[0], b[1], b[2], b[3]], outline=(255, 255, 255, 255), width=int((b[2] - b[0]) * 0.04)),
                                                                     d.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), "07", font=font(BLACK, int((b[3] - b[1]) * 0.45)), fill=(255, 255, 255, 255), anchor="mm")), None, 1.0)],
                                  pad=0.04, noise=0)
    # vending
    for k in ("drinks", "noctis", "ramen"):
        D[f"vend_front_{k}"] = (lambda kk: lambda: vend_front(kk))(k)
        D[f"vend_header_{k}"] = (lambda kk: lambda: vend_header(kk))(k)
        D[f"vend_side_{k}"] = (lambda kk: lambda: vend_side(kk))(k)
    D["vend_flap"] = lambda: card(600, 100, None, [("取出口 · TAKE OUT", WHITE, 1.0)], pad=0.05, noise=0, long_side=512)
    D["vend_pay"] = lambda: small_screen([("TAP CARD OR FACE", 0.7), ("SCORE DISCOUNT -5%", 0.7)], (5, 10, 20, 255), CYAN, w=720, h=520)
    # holo pylon ads
    for k in ("dreamlink", "noctis", "meridian", "hacked"):
        D[f"holo_{k}"] = (lambda kk: lambda: holo(kk))(k)
    # marquee arrow texts (glyph, vertical)
    for k, txt, f in (("hotel", "HOTEL", BLACK), ("bar", "BAR", BLACK), ("pachinko", "パチンコ", JP_BOLD), ("capsules", "カプセル", JP_BOLD)):
        D[f"arrow_{k}"] = (lambda t, ff: lambda: glyph([t], 620, 1800, ff, vertical=True))(txt, f)
    # bins, boxes, crates, stencils
    D["bin_cans"] = lambda: card(680, 400, (30, 90, 180, 255), [("缶・びん", WHITE, 1.0), ("CANS · BOTTLES", WHITE, 0.6)], radius=16)
    D["bin_burnable"] = lambda: card(680, 400, (200, 40, 40, 255), [("燃えるゴミ", WHITE, 1.0), ("BURNABLE", WHITE, 0.6)], radius=16)
    D["box_fragile"] = lambda: card(800, 500, (250, 250, 245, 255), [("FRAGILE", RED, 1.0, IMPACT), ("壊れ物 ↑↑ THIS SIDE UP", INK, 0.5)], border=RED, noise=14)
    D["box_logistics"] = lambda: card(800, 500, None, [("HOSHIKAWA", INK, 0.8, BLACK), ("LOGISTICS", INK, 0.6), ("# 4471-22 / 7G", INK, 0.4, MONO)], noise=20)
    D["stencil_noctis_bio"] = lambda: card(1000, 500, None, [("NOCTIS BIOLOGICS", (235, 235, 230, 255), 0.9, STENCIL), ("KEEP COLD 4°C", (235, 235, 230, 255), 0.7, STENCIL),
                                                             ("ORGANIC MATERIAL - DO NOT OPEN", RED, 0.45, STENCIL)], noise=30, seed=5)
    D["stencil_water"] = lambda: card(1300, 600, None, [("水 WATER", (235, 235, 230, 255), 1.0, STENCIL), ("RATION ZONE 4", (235, 235, 230, 255), 0.6, STENCIL),
                                                        ("HOSHIKAWA UTILITIES", (235, 235, 230, 255), 0.45, STENCIL)], noise=30, seed=6)
    D["stencil_checkpoint"] = lambda: card(1200, 400, None, [("CHECKPOINT 9", (240, 240, 235, 255), 1.0, STENCIL), ("SCORE 500+ ONLY", (240, 240, 235, 255), 0.6, STENCIL)], noise=30, seed=7)
    D["stencil_civil"] = lambda: card(1200, 220, None, [("HOSHIKAWA CIVIL WORKS", (240, 240, 235, 255), 1.0, STENCIL)], noise=30, seed=8)
    # scooter
    D["scooter_qr"] = lambda: card(300, 660, (20, 160, 150, 255), [("HOSHIKAWA", WHITE, 0.5), ("RIDE", WHITE, 0.8, BLACK), (lambda d, b: qr(d, b), None, 1.6), ("SCAN TO RIDE", WHITE, 0.4)], radius=20, long_side=512)
    D["scooter_display"] = lambda: small_screen([("18 km/h", 1.0), ("■■■■□ 82%", 0.7)], (5, 8, 10, 255), (120, 255, 200, 255), w=600, h=440)
    D["scooter_stem"] = lambda: card(240, 1440, (20, 160, 150, 255), [("R", WHITE, 1.0, BLACK), ("I", WHITE, 1.0, BLACK), ("D", WHITE, 1.0, BLACK), ("E", WHITE, 1.0, BLACK)], long_side=512, noise=0)
    # food
    D["noren_ramen"] = noren_text
    D["ramen_menu"] = lambda: card(600, 450, (30, 22, 14, 255), [("お品書き MENU", (250, 230, 190, 255), 0.8), ("醤油 SHOYU ........ 600", WHITE, 0.6), ("味噌 MISO ........ 650", WHITE, 0.6),
                                                                 ("豚骨 TONKOTSU .... 700", WHITE, 0.6), ("NO SCORE NEEDED", (255, 120, 80, 255), 0.6)], border=(160, 120, 70, 255), radius=10, noise=16)
    D["ramen_roof_sign"] = lambda: glyph(["拉麺 RAMEN"], 900, 280, JP_BOLD)
    D["lantern_ramen"] = lambda: glyph(["拉麺"], 400, 800, JP_BOLD, vertical=True)
    D["yakitori_menu"] = lambda: card(500, 750, (25, 25, 25, 255), [("焼き鳥", WHITE, 1.0), ("YAKITORI", (255, 170, 60, 255), 0.6), ("ねぎま NEGIMA 150", WHITE, 0.45), ("つくね TSUKUNE 180", WHITE, 0.45),
                                                                     ("皮 KAWA 120", WHITE, 0.45), ("CASH · NO SCORE", (255, 90, 90, 255), 0.45)], border=(240, 240, 240, 255), radius=8, noise=20)
    D["yakitori_valance"] = lambda: card(2400, 220, None, [("焼き鳥  YAKITORI  ·  炭火焼  CHARCOAL", (250, 240, 220, 255), 1.0)], pad=0.05, noise=0)
    # small plates
    D["bench_plaque"] = lambda: card(880, 200, (40, 40, 44, 255), [("HOSHIKAWA PARKS · NO SLEEPING", (220, 200, 140, 255), 1.0)], border=(220, 200, 140, 255), radius=10, long_side=512)
    D["planter_plate"] = lambda: card(1000, 300, (30, 60, 40, 255), [("星川公園 HOSHIKAWA PARKS", WHITE, 1.0), ("littering lowers your score", (200, 230, 200, 255), 0.5)], border=WHITE, radius=10, long_side=512)
    D["ac_brand"] = lambda: card(640, 200, None, [("HOSHIKAWA CLIMATE", (60, 60, 64, 255), 1.0, BLACK)], noise=0, long_side=512)
    D["junction_tag"] = lambda: card(560, 320, (250, 200, 20, 255), [("LINE 7-G", INK, 1.0), ("DO NOT CUT", RED, 0.7)], border=INK, long_side=512)
    D["dish_logo"] = lambda: card(1000, 360, None, [("DREAMLINK", (40, 60, 120, 255), 1.0, BLACK), ("UPLINK · 夢", (40, 60, 120, 255), 0.5)], noise=0)
    # puddles
    for k in range(3):
        D[f"puddle_{'abc'[k]}"] = (lambda kk: lambda: puddle(kk + 11, *((1200, 900), (1400, 900), (1600, 650))[kk]))(k)
    return D


def main():
    os.makedirs(OUT, exist_ok=True)
    only = set(sys.argv[1:])
    D = decals()
    for k, fn in D.items():
        if only and k not in only:
            continue
        img = fn()
        img.save(os.path.join(OUT, f"{k}.png"), optimize=True)
    print(f"[make_prop_decals] {len(D) if not only else len(only)} decals -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
