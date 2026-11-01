"""Story decals for the cyberpunk town: a city owned by corporations and run by an AI.

The world:
  * HOSHIKAWA DYNAMICS owns the city: the towers, the police (Hoshikawa
    Security), the power, the water.
  * MERIDIAN is the AI that runs it. It scores every citizen; your score
    decides your rent, your rations and whether the doors open for you.
  * DREAMLINK (a Hoshikawa brand) leases your sleep: your brain does
    compute for Meridian while you dream.
  * NOCTIS buys what poor people have left: memories, sleep cycles, organs.
  * Street level is people getting by: score-reset fixers, implant
    jailbreakers, memory pawn shops, noodle bars.
  * The resistance ("UNPLUG", the crossed-out eye) paints over the
    corporate posters, and someone is putting up MISSING posters for
    people "re-educated" by Meridian.

Neon signs are white glyphs (tinted and made emissive in Pigment);
billboards, plates, posters and graffiti are full colour.

    python tools/make_story_decals.py   ->  assets/decals/story/*.png
"""
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
from make_decals import (ARIAL_B, BAHN, BLACK, IMPACT, JP_BOLD, JP_REG, MONO, SS, STENCIL,  # noqa: E402
                         canvas, finish, font, graffiti, neon_text, neon_tube_text)

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "decals", "story")


def text_c(d, xy, txt, f, fill, anchor="mm"):
    d.text(xy, txt, font=f, fill=fill, anchor=anchor)


def wrap_lines(d, x, y, lines, f, fill, gap, anchor="la"):
    for i, ln in enumerate(lines):
        d.text((x, y + i * gap), ln, font=f, fill=fill, anchor=anchor)


def eye(d, cx, cy, r, col, width, crossed=False):
    """The Meridian eye (or the resistance's crossed-out version)."""
    s = SS
    d.ellipse([cx - r, cy - r * 0.55, cx + r, cy + r * 0.55], outline=col, width=width)
    d.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], fill=col)
    if crossed:
        d.line([cx - r * 1.1, cy + r * 0.8, cx + r * 1.1, cy - r * 0.8], fill=col, width=int(width * 1.6))
    return s


def noise_overlay(img, seed, amount=18):
    rnd = random.Random(seed)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 60):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r, g, b, a = px[x, y]
        if a:
            k = rnd.randint(-amount, amount)
            px[x, y] = (max(0, min(255, r + k)), max(0, min(255, g + k)), max(0, min(255, b + k)), a)
    return img

# ------------------------------------------------------------------ billboards (2:1)


def billboard_meridian():
    W, H = 1600, 800
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    for i in range(H):
        t = i / H
        d.line([0, i * s, W * s, i * s], fill=(int(8 + 10 * t), int(20 + 30 * t), int(40 + 40 * t), 255), width=s)
    eye(d, 360 * s, 400 * s, 230 * s, (120, 230, 255, 255), 18 * s)
    text_c(d, (1050 * s, 250 * s), "MERIDIAN", font(BAHN, 190 * s), (235, 250, 255, 255))
    text_c(d, (1050 * s, 420 * s), "IS LISTENING.", font(BAHN, 96 * s), (120, 230, 255, 255))
    text_c(d, (1050 * s, 530 * s), "MERIDIAN CARES.", font(BAHN, 96 * s), (235, 250, 255, 255))
    text_c(d, (1050 * s, 660 * s), "あなたの安全は、私たちのデータです。", font(JP_REG, 40 * s), (150, 200, 230, 255))
    text_c(d, (1050 * s, 730 * s), "A SERVICE OF HOSHIKAWA DYNAMICS", font(ARIAL_B, 26 * s), (110, 150, 180, 255))
    return finish(img, 0.0)


def billboard_score():
    W, H = 1600, 800
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * s, H * s], fill=(245, 245, 240, 255))
    d.rectangle([0, 0, W * s, 120 * s], fill=(200, 20, 40, 255))
    text_c(d, (W * s / 2, 60 * s), "CITIZEN SCORE  市民スコア", font(BAHN, 70 * s), (255, 255, 255, 255))
    text_c(d, (520 * s, 420 * s), "412", font(IMPACT, 380 * s), (20, 20, 25, 255))
    text_c(d, (520 * s, 650 * s), "▼ 38 THIS WEEK", font(BAHN, 64 * s), (200, 20, 40, 255))
    f = font(BAHN, 50 * s)
    wrap_lines(d, 940 * s, 230 * s, ["LOW SCORE?", "BETTER CHOICES", "MAKE BETTER", "CITIZENS."], f, (20, 20, 25, 255), 72 * s)
    wrap_lines(d, 940 * s, 560 * s, ["Report a neighbour: +15", "Skip a meal: +4", "Ask a question: -30"], font(ARIAL_B, 34 * s), (80, 80, 90, 255), 48 * s)
    text_c(d, (W * s - 40 * s, H * s - 40 * s), "— MERIDIAN", font(BAHN, 40 * s), (200, 20, 40, 255), "rb")
    return finish(img, 0.0)


def billboard_dreamlink():
    W, H = 1600, 800
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    for i in range(W):
        t = i / W
        d.line([i * s, 0, i * s, H * s], fill=(int(40 + 120 * t), int(10 + 10 * t), int(80 + 60 * (1 - t)), 255), width=s)
    for k in range(9):
        r = (80 + k * 55) * s
        d.ellipse([400 * s - r, 400 * s - r, 400 * s + r, 400 * s + r], outline=(255, 120, 220, 90 - k * 8), width=4 * s)
    text_c(d, (400 * s, 400 * s), "眠", font(JP_BOLD, 300 * s), (255, 240, 250, 255))
    text_c(d, (1080 * s, 230 * s), "DREAMLINK", font(IMPACT, 170 * s), (255, 240, 250, 255))
    text_c(d, (1080 * s, 380 * s), "YOUR SLEEP IS WORTH MONEY.", font(BAHN, 56 * s), (255, 200, 240, 255))
    text_c(d, (1080 * s, 470 * s), "Lease 6 hours a night. Earn 40¥.", font(ARIAL_B, 44 * s), (255, 255, 255, 255))
    text_c(d, (1080 * s, 640 * s), "*side effects: memory loss, borrowed dreams, nosebleeds", font(ARIAL_B, 24 * s), (220, 180, 220, 255))
    return finish(img, 0.0)


def billboard_noctis():
    W, H = 1600, 800
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * s, H * s], fill=(10, 10, 12, 255))
    d.rectangle([60 * s, 60 * s, W * s - 60 * s, H * s - 60 * s], outline=(255, 190, 40, 255), width=6 * s)
    text_c(d, (W * s / 2, 210 * s), "NOCTIS", font(BLACK, 200 * s), (255, 190, 40, 255))
    text_c(d, (W * s / 2, 380 * s), "WE BUY WHAT YOU DON'T NEED", font(BAHN, 64 * s), (240, 240, 240, 255))
    text_c(d, (W * s / 2, 500 * s), "MEMORIES · SLEEP CYCLES · KIDNEYS · CHILDHOOD", font(BAHN, 46 * s), (255, 190, 40, 255))
    text_c(d, (W * s / 2, 620 * s), "Instant credit. No questions. 記憶買取", font(JP_REG, 44 * s), (200, 200, 200, 255))
    return finish(img, 0.0)


def billboard_jobs():
    W, H = 1600, 800
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * s, H * s], fill=(230, 236, 240, 255))
    eye(d, 220 * s, 400 * s, 140 * s, (30, 90, 160, 255), 12 * s)
    f = font(BAHN, 78 * s)
    wrap_lines(d, 440 * s, 170 * s, ["YOUR JOB HAS BEEN", "OPTIMISED."], f, (25, 30, 40, 255), 100 * s)
    wrap_lines(d, 440 * s, 420 * s, ["Thank you for your service.", "Please return your badge."], font(BAHN, 56 * s), (30, 90, 160, 255), 74 * s)
    text_c(d, (W * s - 50 * s, H * s - 50 * s), "MERIDIAN WORKFORCE TRANSITION", font(ARIAL_B, 30 * s), (90, 100, 110, 255), "rb")
    return finish(img, 0.0)


def billboard_defaced():
    """The Meridian billboard, painted over by the resistance."""
    img = billboard_meridian()
    s = 1
    d = ImageDraw.Draw(img)
    rnd = random.Random(4)
    W, H = img.size
    red = (230, 20, 30, 255)
    for _ in range(3):
        y = rnd.uniform(0.3, 0.7) * H
        d.line([W * 0.42, y, W * 0.98, y + rnd.uniform(-40, 40)], fill=red, width=int(H * 0.03))
    f = font(BLACK, int(H * 0.2))
    d.text((W * 0.69, H * 0.82), "IS LYING", font=f, fill=red, anchor="mm", stroke_width=6 * s, stroke_fill=(10, 0, 0, 255))
    return img

# ------------------------------------------------------------------ vertical blade signs (neon glyphs)


BLADES = {
    "blade_gitai": ("義体", None),           # cyber-limbs
    "blade_kioku": ("記憶買取", None),        # memories bought
    "blade_pachinko": ("パチンコ", None),
    "blade_capsule": ("カプセル", None),
    "blade_soba": ("そば", None),
    "blade_yume": ("夢屋", None),            # dream shop
}

# ------------------------------------------------------------------ hanging / shop signs (neon glyphs, 2 lines)


SHOP_SIGNS = {
    "sign_implant_repair": (["IMPLANT", "REPAIR"], BAHN),
    "sign_jailbreak": (["JAILBREAK", "NO QUESTIONS"], BAHN),
    "sign_score_reset": (["SCORE", "RESET"], IMPACT),
    "sign_memory_pawn": (["MEMORY", "PAWN"], BAHN),
    "sign_organ_credit": (["ORGAN", "CREDIT"], IMPACT),
    "sign_capsule_2h": (["CAPSULE", "2H ¥9"], BAHN),
    "sign_clinic": (["CLINIC", "UNLICENSED"], BAHN),
    "sign_offgrid": (["OFF-GRID", "TEA"], BAHN),
    "sign_charge": (["CHARGE", "5¥/kWh"], BAHN),
    "sign_karaoke": (["KARAOKE", "カラオケ"], JP_BOLD),
    "sign_dumplings": (["DUMPLINGS", "餃子"], JP_BOLD),
    "sign_dreams": (["DREAMS", "RENTED"], IMPACT),
}

# ------------------------------------------------------------------ authority plates


def has_cjk(txt):
    return any(ord(c) > 0x2E7F for c in txt)


def line_font(txt, size):
    """Bahnschrift has no Japanese glyphs: CJK lines use Yu Gothic."""
    return font(JP_BOLD if has_cjk(txt) else BAHN, size)


def fit_size(d, lines, max_w, max_h, gap=1.18, start=200):
    """Largest font size (px) at which every line fits max_w and the block fits max_h."""
    size = start
    while size > 8:
        widest = max(d.textlength(ln, font=line_font(ln, size)) for ln in lines)
        if widest <= max_w and size * gap * len(lines) <= max_h:
            return size
        size -= 2
    return size


def plate(lines, bg, fg, w=1200, h=520, icon=None, sub=None):
    """Authority plate. The text block is sized to fill the plate (it used to
    shrink with line length alone and ended up tiny)."""
    s = SS
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w * s, h * s], radius=24 * s, fill=bg)
    d.rounded_rectangle([18 * s, 18 * s, (w - 18) * s, (h - 18) * s], radius=16 * s, outline=fg, width=8 * s)
    x0 = 70 * s
    if icon == "eye":
        eye(d, 200 * s, (h * s) / 2 - (25 * s if sub else 0), 125 * s, fg, 14 * s)
        x0 = 370 * s
    sub_h = 80 * s if sub else 0
    top, bottom = 50 * s, h * s - 50 * s - sub_h
    size = fit_size(d, lines, w * s - x0 - 70 * s, bottom - top, start=170 * s)
    gap = size * 1.18
    y0 = (top + bottom) / 2 - gap * (len(lines) - 1) / 2
    for i, ln in enumerate(lines):
        d.text((x0, y0 + i * gap), ln, font=line_font(ln, size), fill=fg, anchor="lm")
    if sub:
        sf = font(ARIAL_B, fit_size(d, [sub], w * s - x0 - 70 * s, 50 * s, start=40 * s))
        d.text((x0, h * s - 50 * s - sub_h / 2), sub, font=sf, fill=fg, anchor="lm")
    return noise_overlay(finish(img, 0.0), 7, 10)

# ------------------------------------------------------------------ street posters


def poster_missing(name, seed):
    """MISSING poster: photo, name, last-seen note and tear-off phone tabs,
    each in its own band so nothing overlaps."""
    W, H = 700, 1000
    s = SS
    rnd = random.Random(seed)
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    paper, ink, red, grey = (236, 232, 220, 255), (20, 20, 20, 255), (190, 20, 30, 255), (40, 40, 40, 255)
    d.rectangle([0, 0, W * s, H * s], fill=paper)
    text_c(d, (W * s / 2, 100 * s), "MISSING", font(IMPACT, 160 * s), ink)
    text_c(d, (W * s / 2, 200 * s), "行方不明", font(JP_BOLD, 54 * s), red)
    # photo: grey head-and-shoulders silhouette, clipped to the photo frame
    px0, py0, px1, py1 = 180 * s, 250 * s, 520 * s, 590 * s
    photo = Image.new("RGBA", ((px1 - px0), (py1 - py0)), (120, 118, 112, 255))
    pd = ImageDraw.Draw(photo)
    pw, ph = photo.size
    pd.ellipse([pw * 0.32, ph * 0.12, pw * 0.68, ph * 0.55], fill=(60, 58, 55, 255))
    pd.ellipse([pw * 0.1, ph * 0.5, pw * 0.9, ph * 1.3], fill=(60, 58, 55, 255))
    img.alpha_composite(photo, (px0, py0))
    d.rectangle([px0, py0, px1, py1], outline=(60, 58, 55, 255), width=3 * s)
    text_c(d, (W * s / 2, 645 * s), name, font(BAHN, fit_size(d, [name], 600 * s, 70 * s, start=64 * s)), ink)
    f = font(ARIAL_B, 27 * s)
    for i, ln in enumerate(["Last seen entering the", "MERIDIAN WELLNESS CENTRE", f"Score at disappearance: {rnd.randint(180, 330)}"]):
        text_c(d, (W * s / 2, (705 + i * 38) * s), ln, f, grey)
    # tear-off tabs: a dashed cut line, then vertical phone numbers
    tab_top = 830 * s
    for x in range(0, W * s, 16 * s):
        d.line([x, tab_top, x + 9 * s, tab_top], fill=(150, 150, 140, 255), width=2 * s)
    n = 8
    tw = W * s / n
    number = f"070-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}"
    tf = font(ARIAL_B, 19 * s)
    for i in range(n):
        if i:
            d.line([i * tw, tab_top, i * tw, H * s], fill=(150, 150, 140, 255), width=2 * s)
        if rnd.random() < 0.3:  # someone already took this one
            d.rectangle([i * tw + 2 * s, tab_top + 2 * s, (i + 1) * tw - 2 * s, H * s], fill=(0, 0, 0, 0))
            continue
        lab = Image.new("RGBA", (int(H * s - tab_top - 16 * s), int(tw - 10 * s)), (0, 0, 0, 0))
        ImageDraw.Draw(lab).text((lab.width / 2, lab.height / 2), number, font=tf, fill=grey, anchor="mm")
        lab = lab.rotate(90, expand=True)
        img.alpha_composite(lab, (int(i * tw + 5 * s), int(tab_top + 8 * s)))
    img = finish(img, 0.0)
    return noise_overlay(img, seed, 22)


def poster_unplug():
    W, H = 700, 1000
    s = SS
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * s, H * s], fill=(20, 20, 20, 255))
    eye(d, W * s / 2, 380 * s, 230 * s, (230, 30, 40, 255), 24 * s, crossed=True)
    text_c(d, (W * s / 2, 720 * s), "UNPLUG", font(STENCIL, 190 * s), (240, 240, 230, 255))
    text_c(d, (W * s / 2, 850 * s), "WE ARE NOT DATA", font(STENCIL, 72 * s), (230, 30, 40, 255))
    text_c(d, (W * s / 2, 940 * s), "抵抗せよ", font(JP_BOLD, 50 * s), (240, 240, 230, 255))
    return noise_overlay(finish(img, 0.0), 9, 30)


def stencil_eye():
    s = SS
    img = canvas(800, 800)
    d = ImageDraw.Draw(img)
    eye(d, 400 * s, 400 * s, 330 * s, (240, 240, 240, 255), 40 * s, crossed=True)
    img = img.filter(ImageFilter.GaussianBlur(1.5 * SS))
    return finish(img)


def decals():
    out = {
        "billboard_meridian": billboard_meridian,
        "billboard_score": billboard_score,
        "billboard_dreamlink": billboard_dreamlink,
        "billboard_noctis": billboard_noctis,
        "billboard_jobs": billboard_jobs,
        "billboard_defaced": billboard_defaced,
        "plate_observed": lambda: plate(["THIS STREET IS", "OBSERVED"], (20, 30, 45, 255), (120, 230, 255, 255), icon="eye", sub="BY MERIDIAN · FOR YOUR SAFETY"),
        "plate_curfew": lambda: plate(["CURFEW 23:00", "門限"], (250, 200, 20, 255), (20, 20, 20, 255), sub="ENFORCED BY HOSHIKAWA SECURITY"),
        "plate_loitering": lambda: plate(["LOITERING", "LOWERS YOUR", "SCORE"], (240, 240, 235, 255), (190, 20, 30, 255), h=600),
        "plate_property": lambda: plate(["PROPERTY OF", "HOSHIKAWA", "DYNAMICS"], (30, 30, 34, 255), (230, 230, 230, 255), h=600),
        "poster_missing_aiko": lambda: poster_missing("AIKO TANAKA", 1),
        "poster_missing_ren": lambda: poster_missing("REN MORIOKA", 2),
        "poster_missing_mika": lambda: poster_missing("MIKA SATO", 3),
        "poster_unplug": poster_unplug,
        "stencil_eye_crossed": stencil_eye,
        "graffiti_lying": lambda: graffiti("THE MACHINE IS LYING", BLACK, 200, (255, 40, 60, 255), (255, 150, 40, 255), (15, 5, 10, 255), (255, 255, 255, 255), seed=21, shear=-0.1, rot=3, drips=14),
        "graffiti_not_data": lambda: graffiti("WE ARE NOT DATA", IMPACT, 240, (240, 240, 240, 255), (160, 255, 220, 255), (10, 10, 10, 255), (255, 30, 120, 255), seed=8, shear=-0.2, rot=-3, drips=10),
        "graffiti_unplug": lambda: graffiti("UNPLUG", BLACK, 300, (0, 240, 255, 255), (130, 80, 255, 255), (10, 0, 30, 255), (255, 240, 0, 255), seed=31, drips=12),
        "graffiti_who_owns": lambda: graffiti("WHO OWNS YOUR DREAMS?", IMPACT, 190, (255, 220, 0, 255), (255, 90, 0, 255), (20, 10, 0, 255), (0, 0, 0, 255), seed=17, shear=-0.12, rot=2, drips=8),
    }
    for k, (txt, _) in BLADES.items():
        out[k] = (lambda t: lambda: neon_text([t], JP_BOLD, 480, vertical=True, line_gap=0.05))(txt)
    for k, (lines, f) in SHOP_SIGNS.items():
        out[k] = (lambda l, f: lambda: neon_text(l, f, 300, line_gap=0.2))(lines, f)
    out["sign_hoshikawa_security"] = lambda: neon_tube_text("HOSHIKAWA SECURITY", BAHN, 220, tube=8)
    out["sign_meridian_kiosk"] = lambda: neon_tube_text("MERIDIAN KIOSK", BAHN, 260, tube=9)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    only = set(sys.argv[1:])
    for name, make in decals().items():
        if only and name not in only:
            continue
        img = make()
        img.save(os.path.join(OUT, name + ".png"))
        print(name, img.size)


if __name__ == "__main__":
    main()
