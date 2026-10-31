"""Generate cyberpunk decal PNGs (RGBA, transparent background) for the alley scene.

Usage:  python tools/make_decals.py [out_dir]
Default out_dir: assets/decals (relative to the repo root).

Every decal is drawn at 2x and downsampled (Lanczos) for clean anti-aliased
edges, cropped to its content plus a small margin, and scaled so the long side
is exactly 1024 px.
"""
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = "C:/Windows/Fonts"
LONG_SIDE = 1024
SS = 2  # supersampling factor for the working canvas


def font(name, size, index=0):
    """Load a font from C:/Windows/Fonts, falling back through alternatives."""
    candidates = [name] if isinstance(name, str) else list(name)
    for c in candidates:
        p = os.path.join(FONTS, c)
        if os.path.exists(p):
            return ImageFont.truetype(p, size, index=index)
    raise FileNotFoundError(f"none of {candidates} found in {FONTS}")


JP_BOLD = ("YuGothB.ttc", "meiryob.ttc", "msgothic.ttc")
JP_REG = ("YuGothM.ttc", "meiryo.ttc", "msgothic.ttc")
IMPACT = ("impact.ttf", "arialbd.ttf")
ARIAL_B = ("arialbd.ttf",)
BLACK = ("ariblk.ttf", "seguibl.ttf", "arialbd.ttf")
MONO = ("consolab.ttf", "consola.ttf")
STENCIL = ("STENCIL.TTF", "impact.ttf")
BAHN = ("bahnschrift.ttf", "arialbd.ttf")


def canvas(w, h):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def finish(img, margin=0.03):
    """Crop to alpha bbox (+margin), scale so long side == LONG_SIDE."""
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("empty decal")
    x0, y0, x1, y1 = bbox
    m = int(max(x1 - x0, y1 - y0) * margin)
    x0, y0 = max(0, x0 - m), max(0, y0 - m)
    x1, y1 = min(img.width, x1 + m), min(img.height, y1 + m)
    img = img.crop((x0, y0, x1, y1))
    w, h = img.size
    s = LONG_SIDE / max(w, h)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    # premultiply-safe downsample: resize RGBa then convert back
    return img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


def text_mask(txt, fnt, size, xy=(0, 0), anchor="la", stroke=0, spacing=0):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    if spacing:
        x, y = xy
        for ch in txt:
            d.text((x, y), ch, font=fnt, fill=255, anchor=anchor, stroke_width=stroke, stroke_fill=255)
            x += fnt.getlength(ch) + spacing
    else:
        d.text(xy, txt, font=fnt, fill=255, anchor=anchor, stroke_width=stroke, stroke_fill=255)
    return m


def fill_mask(img, mask, color):
    layer = Image.new("RGBA", img.size, color)
    img.alpha_composite(Image.composite(layer, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask))


# --------------------------------------------------------------------------- neon

NEON_CORE = (255, 255, 255, 255)


def neon_text(lines, fnt_names, px, vertical=False, line_gap=0.15, letter_gap=0):
    """Plain white glyph shapes for tinting / emissive use (no halo)."""
    f = font(fnt_names, px * SS)
    W = H = 4096
    img = canvas(W // SS, H // SS)
    d = ImageDraw.Draw(img)
    if vertical:
        # stack characters top-to-bottom, centred
        y = 100
        for ch in lines[0]:
            d.text((W / 2, y), ch, font=f, fill=NEON_CORE, anchor="mt")
            y += px * SS * (1 + line_gap)
    else:
        y = 100
        for ln in lines:
            if letter_gap:
                lw = sum(f.getlength(c) for c in ln) + letter_gap * SS * (len(ln) - 1)
                x = (W - lw) / 2
                for c in ln:
                    d.text((x, y), c, font=f, fill=NEON_CORE, anchor="lt")
                    x += f.getlength(c) + letter_gap * SS
            else:
                d.text((W / 2, y), ln, font=f, fill=NEON_CORE, anchor="mt")
            y += px * SS * (1 + line_gap)
    return finish(img)


def neon_tube_text(txt, fnt_names, px, tube=10):
    """Outline-tube style (bent-glass look): ring around each glyph."""
    f = font(fnt_names, px * SS)
    size = (int(f.getlength(txt) + 400), int(px * SS * 1.6))
    outer = text_mask(txt, f, size, (200, size[1] / 2), "lm", stroke=tube * SS)
    inner = text_mask(txt, f, size, (200, size[1] / 2), "lm")
    inner = inner.filter(ImageFilter.MinFilter(2 * tube * SS + 1))
    ring = ImageChops.subtract(outer, inner)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    fill_mask(img, ring, NEON_CORE)
    return finish(img)


# --------------------------------------------------------------------------- logo


def corp_logo():
    W, H = 1600, 520
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    cx, cy, r = 260 * s, 260 * s, 220 * s
    # hexagon mark with an inset "blade" triangle and a cut line
    import math

    hexpts = [(cx + r * math.cos(math.radians(60 * i - 90)), cy + r * math.sin(math.radians(60 * i - 90))) for i in range(6)]
    d.polygon(hexpts, fill=(230, 30, 60, 255))
    r2 = r * 0.72
    inner = [(cx + r2 * math.cos(math.radians(60 * i - 90)), cy + r2 * math.sin(math.radians(60 * i - 90))) for i in range(6)]
    d.polygon(inner, fill=(0, 0, 0, 0))
    tri = [(cx, cy - r * 0.5), (cx + r * 0.45, cy + r * 0.38), (cx - r * 0.45, cy + r * 0.38)]
    d.polygon(tri, fill=(240, 240, 240, 255))
    d.line([(cx - r * 0.9, cy + r * 0.12), (cx + r * 0.9, cy - r * 0.12)], fill=(0, 0, 0, 0), width=int(22 * s))
    # wordmark
    f1 = font(BAHN, 150 * s)
    f2 = font(BAHN, 58 * s)
    f3 = font(JP_BOLD, 64 * s)
    d.text((540 * s, 70 * s), "HOSHIKAWA", font=f1, fill=(240, 240, 240, 255))
    d.text((546 * s, 245 * s), "D Y N A M I C S", font=f2, fill=(230, 30, 60, 255))
    d.text((546 * s, 345 * s), "星川ダイナミクス株式会社", font=f3, fill=(200, 200, 200, 255))
    return finish(img)


# --------------------------------------------------------------------------- warnings


def bolt(d, x, y, h, fill):
    w = h * 0.55
    pts = [
        (x + w * 0.55, y), (x + w * 0.05, y + h * 0.55), (x + w * 0.45, y + h * 0.55),
        (x + w * 0.25, y + h), (x + w * 0.95, y + h * 0.38), (x + w * 0.55, y + h * 0.38),
        (x + w * 0.85, y),
    ]
    d.polygon(pts, fill=fill)


YELLOW = (255, 204, 0, 255)
INK = (15, 15, 15, 255)


def high_voltage():
    W, H = 1600, 900
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rounded_rectangle([0, 0, W * s - 1, H * s - 1], radius=40 * s, fill=YELLOW)
    d.rounded_rectangle([24 * s, 24 * s, (W - 24) * s, (H - 24) * s], radius=28 * s, outline=INK, width=14 * s)
    # black header band
    d.rectangle([24 * s, 24 * s, (W - 24) * s, 270 * s], fill=INK)
    d.text((W * s / 2, 150 * s), "DANGER", font=font(IMPACT, 210 * s), fill=YELLOW, anchor="mm")
    bolt(d, 90 * s, 320 * s, 500 * s, INK)
    d.text((420 * s, 330 * s), "HIGH", font=font(IMPACT, 200 * s), fill=INK)
    d.text((420 * s, 540 * s), "VOLTAGE", font=font(IMPACT, 200 * s), fill=INK)
    d.line([(60 * s, 790 * s), ((W - 60) * s, 790 * s)], fill=INK, width=6 * s)
    d.text((W * s / 2, 830 * s), "高電圧  危険  立入禁止", font=font(JP_BOLD, 66 * s), fill=INK, anchor="mm")
    return finish(img, margin=0.0)


def hazard_triangle():
    W = H = 1200
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    top, bl, br = (600 * s, 60 * s), (60 * s, 1100 * s), (1140 * s, 1100 * s)
    # rounded triangle: thick stroked polygon
    d.polygon([top, bl, br], fill=INK)
    d.line([top, bl, br, top], fill=INK, width=80 * s, joint="curve")
    for p in (top, bl, br):
        d.ellipse([p[0] - 40 * s, p[1] - 40 * s, p[0] + 40 * s, p[1] + 40 * s], fill=INK)
    inset = [(600 * s, 210 * s), (190 * s, 1030 * s), (1010 * s, 1030 * s)]
    d.polygon(inset, fill=YELLOW)
    # exclamation mark
    d.rounded_rectangle([555 * s, 420 * s, 645 * s, 800 * s], radius=40 * s, fill=INK)
    d.ellipse([550 * s, 850 * s, 650 * s, 950 * s], fill=INK)
    return finish(img)


# --------------------------------------------------------------------------- stencil


def stencil_sector():
    f = font(STENCIL, 300 * SS)
    txt = "SECTOR 7-G"
    size = (int(f.getlength(txt) + 400), int(300 * SS * 1.8))
    m = text_mask(txt, f, size, (200, size[1] / 2), "lm")
    if not os.path.exists(os.path.join(FONTS, "STENCIL.TTF")):
        # fallback: cut horizontal bridges through a heavy face
        d = ImageDraw.Draw(m)
        y = size[1] / 2
        d.rectangle([0, y - 10 * SS, size[0], y + 10 * SS], fill=0)
    # spray overspray roughness: erode/dilate noise along edges
    rnd = random.Random(7)
    noise = Image.effect_noise(size, 90).point(lambda v: 255 if v > 150 else 0)
    edge = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(5)), m.filter(ImageFilter.MinFilter(5)))
    m = ImageChops.subtract(m, ImageChops.multiply(edge, noise))
    m = m.filter(ImageFilter.GaussianBlur(1.2))
    # sparse speckle overspray
    sp = Image.new("L", size, 0)
    ds = ImageDraw.Draw(sp)
    bb = m.getbbox()
    for _ in range(1400):
        x = rnd.uniform(bb[0] - 40, bb[2] + 40)
        y = rnd.uniform(bb[1] - 40, bb[3] + 40)
        r = rnd.uniform(1, 3.5) * SS
        ds.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(60, 200))
    m = ImageChops.lighter(m, sp)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    fill_mask(img, m, (245, 245, 240, 255))
    return finish(img)


# --------------------------------------------------------------------------- barcode label

CODE39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
    "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn",
    "A": "wnnnnwnnw", "B": "nnwnnwnnw", "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn",
    "F": "nnwnwwnnn", "G": "nnnnnwwnw", "H": "wnnnnwwnn", "K": "wnnnnnnww", "X": "nwnnwnnnw",
    "-": "nwnnnnwnw", "*": "nwnnwnwnn",
}


def barcode_label():
    W, H = 1600, 760
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rounded_rectangle([0, 0, W * s - 1, H * s - 1], radius=24 * s, fill=(236, 234, 226, 255))
    d.rectangle([0, 0, W * s, 120 * s], fill=INK)
    d.text((40 * s, 60 * s), "HOSHIKAWA DYNAMICS // ASSET TAG", font=font(BAHN, 64 * s), fill=(236, 234, 226, 255), anchor="lm")
    d.text(((W - 40) * s, 60 * s), "資産管理", font=font(JP_BOLD, 60 * s), fill=YELLOW, anchor="rm")
    # Code39 barcode
    data = "*HK-7G-0451*"
    nw, ww, x = 5 * s, 13 * s, 80 * s
    y0, y1 = 170 * s, 520 * s
    for ch in data:
        pat = CODE39[ch]
        for i, c in enumerate(pat):
            w = ww if c == "w" else nw
            if i % 2 == 0:
                d.rectangle([x, y0, x + w - 1, y1], fill=INK)
            x += w
        x += nw
    bar_end = x
    mono = font(MONO, 56 * s)
    d.text(((80 * s + bar_end) / 2, 570 * s), "HK-7G-0451", font=mono, fill=INK, anchor="mm")
    # spec block on the right
    tx = bar_end + 60 * s
    small = font(MONO, 40 * s)
    for i, ln in enumerate(["S/N 0451-77A3-KX", "MFG 2087.03.14", "LOT 7G/ALLEY-B", "PWR 480V 3PH", "IP54  CLASS II"]):
        d.text((tx, 180 * s + i * 66 * s), ln, font=small, fill=INK)
    d.line([(40 * s, 640 * s), ((W - 40) * s, 640 * s)], fill=INK, width=4 * s)
    d.text((40 * s, 700 * s), "REMOVAL OF THIS TAG VOIDS WARRANTY", font=font(ARIAL_B, 42 * s), fill=INK, anchor="lm")
    d.text(((W - 40) * s, 700 * s), "無断撤去禁止", font=font(JP_BOLD, 42 * s), fill=INK, anchor="rm")
    return finish(img, margin=0.0)


# --------------------------------------------------------------------------- graffiti


def add_drips(mask, rnd, count, max_len, width):
    """Drips hang from the lower edge of the fill mask."""
    w, h = mask.size
    px = mask.load()
    d = ImageDraw.Draw(mask)
    bb = mask.getbbox()
    tries = 0
    made = 0
    while made < count and tries < count * 50:
        tries += 1
        x = rnd.randint(bb[0], bb[2] - 1)
        # find lowest filled pixel in this column
        y = None
        for yy in range(bb[3] - 1, bb[1], -1):
            if px[x, yy] > 128:
                y = yy
                break
        if y is None:
            continue
        L = rnd.uniform(0.25, 1.0) * max_len
        wd = rnd.uniform(0.5, 1.0) * width
        d.rectangle([x - wd / 2, y - wd, x + wd / 2, y + L], fill=255)
        r = wd * 0.85
        d.ellipse([x - r, y + L - r, x + r, y + L + r], fill=255)
        made += 1
    return mask


def gradient(size, c0, c1, vertical=True):
    g = Image.linear_gradient("L").resize(size) if vertical else Image.linear_gradient("L").rotate(90).resize(size)
    a = Image.new("RGBA", size, c0)
    b = Image.new("RGBA", size, c1)
    return Image.composite(b, a, g)


def graffiti(txt, fnt_names, px, col0, col1, outline, shadow, seed, shear=-0.25, rot=6, drips=9):
    rnd = random.Random(seed)
    f = font(fnt_names, px * SS)
    size = (int(f.getlength(txt) + 900), int(px * SS * 2.6))
    pos = (450, size[1] * 0.42)
    fillm = text_mask(txt, f, size, pos, "lm", stroke=6 * SS)
    # round off the letters
    fillm = fillm.filter(ImageFilter.GaussianBlur(5 * SS)).point(lambda v: 255 if v > 110 else 0)
    fillm = add_drips(fillm, rnd, drips, px * SS * 0.7, 16 * SS)
    outm = fillm.filter(ImageFilter.MaxFilter(2 * 14 * SS + 1))
    outm = outm.filter(ImageFilter.GaussianBlur(4 * SS)).point(lambda v: 255 if v > 100 else 0)
    shadowm = ImageChops.offset(outm, 18 * SS, 18 * SS)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    fill_mask(img, shadowm, shadow)
    fill_mask(img, outm, outline)
    grad = gradient(size, col0, col1)
    img.alpha_composite(Image.composite(grad, Image.new("RGBA", size, (0, 0, 0, 0)), fillm))
    # highlight streaks (white shine dashes on upper-left of letters)
    hl = ImageChops.subtract(fillm, ImageChops.offset(fillm, 10 * SS, 14 * SS))
    hl = hl.filter(ImageFilter.MinFilter(5))
    fill_mask(img, hl, (255, 255, 255, 220))
    # a few spray dots
    d = ImageDraw.Draw(img)
    bb = outm.getbbox()
    for _ in range(60):
        x = rnd.uniform(bb[0], bb[2])
        y = rnd.uniform(bb[1] - 60, bb[3] + 60)
        r = rnd.uniform(2, 7) * SS
        d.ellipse([x - r, y - r, x + r, y + r], fill=col1 if rnd.random() < 0.5 else col0)
    # dynamic slant
    w, h = img.size
    img = img.transform((w + int(abs(shear) * h), h), Image.AFFINE, (1, shear, -max(0.0, shear) * h, 0, 1, 0), Image.BICUBIC)
    img = img.rotate(rot, Image.BICUBIC, expand=True)
    return finish(img)


# --------------------------------------------------------------------------- poster


def poster():
    W, H = 720, 1024
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rectangle([0, 0, W * s, H * s], fill=(18, 14, 30, 255))
    # diagonal colour bars
    d.polygon([(0, 620 * s), (W * s, 380 * s), (W * s, 470 * s), (0, 710 * s)], fill=(255, 40, 120, 255))
    d.polygon([(0, 730 * s), (W * s, 490 * s), (W * s, 520 * s), (0, 760 * s)], fill=(0, 230, 255, 255))
    # big kanji
    d.text((W * s / 2, 380 * s), "夢", font=font(JP_BOLD, 520 * s), fill=(250, 245, 235, 255), anchor="mm")
    # side vertical text
    fj = font(JP_REG, 34 * s)
    y = 60 * s
    for ch in "未来はここにある":
        d.text((36 * s, y), ch, font=fj, fill=(0, 230, 255, 255))
        y += 40 * s
    # header strip
    d.text(((W - 30) * s, 40 * s), "NEO-SHINJUKU 2087", font=font(BAHN, 34 * s), fill=(255, 40, 120, 255), anchor="ra")
    # title + small text blocks
    d.text((40 * s, 800 * s), "DREAMLINK", font=font(IMPACT, 96 * s), fill=(250, 245, 235, 255))
    small = font(ARIAL_B, 16 * s)
    block = [
        "IMPLANT-GRADE NEURAL INTERFACE",
        "NOW SHIPPING TO ALL DISTRICTS",
        "FIRMWARE 9.4 / ZERO LATENCY",
    ]
    for i, ln in enumerate(block):
        d.text((44 * s, 922 * s + i * 24 * s), ln, font=small, fill=(200, 200, 220, 255))
    jp = font(JP_REG, 18 * s)
    for i, ln in enumerate(["夢を、直接あなたの脳へ。", "星川ダイナミクス提供"]):
        d.text(((W - 40) * s, 925 * s + i * 30 * s), ln, font=jp, fill=(200, 200, 220, 255), anchor="ra")
    # fake QR-ish block
    rnd = random.Random(3)
    qx, qy, cell = (W - 150) * s, 790 * s, 11 * s
    for i in range(10):
        for j in range(10):
            if rnd.random() < 0.5 or (i < 3 and j < 3):
                d.rectangle([qx + i * cell, qy + j * cell, qx + (i + 1) * cell - 1, qy + (j + 1) * cell - 1], fill=(250, 245, 235, 255))
    d.rectangle([0, 0, W * s - 1, H * s - 1], outline=(250, 245, 235, 255), width=6 * s)
    return finish(img, margin=0.0)


# --------------------------------------------------------------------------- main

DECALS = [
    ("neon_ramen.png", lambda: neon_text(["ラーメン"], JP_BOLD, 420)),
    ("neon_dennou.png", lambda: neon_text(["電脳"], JP_BOLD, 520, vertical=True, line_gap=0.05)),
    ("neon_noodles_24h.png", lambda: neon_tube_text("NOODLES 24H", ARIAL_B, 300, tube=9)),
    ("neon_bar.png", lambda: neon_tube_text("BAR", BAHN, 420, tube=12)),
    ("neon_open.png", lambda: neon_tube_text("OPEN", ARIAL_B, 400, tube=12)),
    ("logo_hoshikawa_dynamics.png", corp_logo),
    ("warning_high_voltage.png", high_voltage),
    ("hazard_triangle.png", hazard_triangle),
    ("stencil_sector_7g.png", stencil_sector),
    ("label_barcode_serial.png", barcode_label),
    ("graffiti_tag_kaze.png", lambda: graffiti("KAZE", BLACK, 320, (255, 230, 0, 255), (255, 60, 140, 255), (20, 10, 30, 255), (0, 220, 255, 255), seed=11)),
    ("graffiti_tag_zer0.png", lambda: graffiti("ZER0", IMPACT, 340, (60, 255, 120, 255), (0, 170, 255, 255), (255, 255, 255, 255), (40, 0, 60, 255), seed=5, shear=-0.15, rot=-4, drips=12)),
    ("poster_yume.png", poster),
]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "assets", "decals")
    os.makedirs(out, exist_ok=True)
    for name, fn in DECALS:
        img = fn()
        path = os.path.join(out, name)
        img.save(path, optimize=True)
        print(f"{name:32s} {img.width}x{img.height}")


if __name__ == "__main__":
    main()
