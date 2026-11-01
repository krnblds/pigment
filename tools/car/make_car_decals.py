"""Decals for the Kanzaki Tsubame-4 car (livery, plates, stickers, tyre lettering).

Two liveries, both from the town's story (tools/make_story_decals.py):
  * HOSHIKAWA SECURITY: the corporate police of Hoshikawa Dynamics. Midnight
    blue, a vermilion side flash, door crest, unit number on the roof (for the
    drones) and the MERIDIAN LINKED sticker: the car feeds the citizen score.
  * KOEN CAB: the same car sold at a fleet auction, now a night cab in teal
    with a cream flash.

    python tools/car/make_car_decals.py   ->  assets/decals/car/*.png
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from make_decals import ARIAL_B, BAHN, BLACK, JP_BOLD, MONO, SS, canvas, finish, font  # noqa: E402

OUT = os.path.join(HERE, "..", "..", "assets", "decals", "car")

WHITE = (244, 246, 250, 255)
VERMILION = (232, 64, 28, 255)
MIDNIGHT = (12, 22, 52, 255)
CREAM = (238, 226, 196, 255)
TEAL = (16, 92, 96, 255)
YELLOW = (250, 196, 20, 255)
BLACKC = (14, 14, 16, 255)


def save(img, name, margin=0.0):
    os.makedirs(OUT, exist_ok=True)
    finish(img, margin).save(os.path.join(OUT, name + ".png"))
    print("wrote", name)


def crest(d, cx, cy, r, col, star_col):
    """Hoshikawa crest: a shield with a star over a river (hoshi = star, kawa = river)."""
    s = r
    pts = [(cx - s, cy - s * 0.9), (cx + s, cy - s * 0.9), (cx + s, cy + s * 0.15), (cx, cy + s * 1.05), (cx - s, cy + s * 0.15)]
    d.polygon(pts, fill=col)
    inner = [(cx + (x - cx) * 0.86, cy + (y - cy) * 0.86) for x, y in pts]
    d.polygon(inner, outline=star_col, width=max(2, int(r * 0.06)))
    # star
    st = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r * (0.42 if i % 2 == 0 else 0.17)
        st.append((cx + rr * math.cos(a), cy - r * 0.18 + rr * math.sin(a)))
    d.polygon(st, fill=star_col)
    # river: three wavy lines
    for k in range(3):
        y0 = cy + r * (0.30 + k * 0.17)
        w = r * (0.75 - k * 0.18)
        line = [(cx - w + t * 2 * w / 30, y0 + math.sin(t / 30 * math.tau * 1.5) * r * 0.045) for t in range(31)]
        d.line(line, fill=star_col, width=max(2, int(r * 0.06)))


def side_flash(col, edge, name, mirror=False):
    """Long side stripe: a band that kicks up into a chevron at the front (left end = front)."""
    W, H = 2400, 300
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    band = [(0, 120 * s), (W * s, 120 * s), (W * s, 210 * s), (0, 210 * s)]
    kick = [(0, 30 * s), (420 * s, 30 * s), (300 * s, 120 * s), (0, 120 * s)]
    d.polygon(band, fill=col)
    d.polygon([(0, 120 * s), (0, 30 * s), (420 * s, 30 * s), (300 * s, 120 * s)], fill=col)
    # pin lines
    d.line([(0, 224 * s), (W * s, 224 * s)], fill=edge, width=8 * s)
    d.line([(440 * s, 16 * s), (320 * s, 106 * s), (W * s, 106 * s)], fill=edge, width=7 * s)
    # speed slashes at the front
    for i in range(4):
        x = 470 * s + i * 70 * s
        d.polygon([(x, 30 * s), (x + 34 * s, 30 * s), (x - 46 * s, 96 * s), (x - 80 * s, 96 * s)], fill=col)
    save(img, name)
    if mirror:
        # the right side of the car sees the stripe from the other direction: front on the right
        save(img.transpose(Image.FLIP_LEFT_RIGHT), name + "_r")


def hs_door_text(fg=WHITE, crest_bg=WHITE, crest_fg=MIDNIGHT, name="hs_door"):
    W, H = 1400, 380
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    crest(d, 170 * s, 180 * s, 140 * s, crest_bg, crest_fg)
    d.text((340 * s, 60 * s), "HOSHIKAWA", font=font(BAHN, 150 * s), fill=fg)
    d.text((345 * s, 215 * s), "SECURITY", font=font(BAHN, 96 * s), fill=VERMILION)
    d.text((880 * s, 228 * s), "星川警備", font=font(JP_BOLD, 80 * s), fill=fg)
    save(img, name)


def hs_hood_crest():
    W = 800
    img = canvas(W, W)
    d = ImageDraw.Draw(img)
    s = SS
    crest(d, 400 * s, 380 * s, 330 * s, WHITE, MIDNIGHT)
    save(img, "hs_crest")


def unit_number(txt, name, col, w=1200, h=520, fnt=BLACK):
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    d.text((w // 2 * SS, h // 2 * SS), txt, font=font(fnt, int(h * 0.82) * SS), fill=col, anchor="mm")
    save(img, name)


def meridian_sticker():
    W, H = 900, 300
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rounded_rectangle([0, 0, W * s, H * s], 30 * s, fill=(10, 14, 22, 255))
    d.rounded_rectangle([10 * s, 10 * s, (W - 10) * s, (H - 10) * s], 24 * s, outline=(120, 230, 255, 255), width=5 * s)
    cx, cy, r = 150 * s, 150 * s, 95 * s
    d.ellipse([cx - r, cy - r * 0.55, cx + r, cy + r * 0.55], outline=(120, 230, 255, 255), width=12 * s)
    d.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], fill=(120, 230, 255, 255))
    d.text((290 * s, 52 * s), "MERIDIAN LINKED", font=font(BAHN, 72 * s), fill=(235, 250, 255, 255))
    d.text((292 * s, 150 * s), "THIS UNIT RECORDS AND SCORES", font=font(BAHN, 36 * s), fill=(120, 230, 255, 255))
    d.text((292 * s, 200 * s), "ALL CITIZEN CONTACT  ·  市民評価", font=font(JP_BOLD, 34 * s), fill=(120, 230, 255, 255))
    save(img, "meridian_linked")


def shock_warning():
    W, H = 700, 300
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rectangle([0, 0, W * s, H * s], fill=YELLOW)
    # hazard edge
    for i in range(-2, 30):
        x = i * 50 * s
        d.polygon([(x, 0), (x + 25 * s, 0), (x - 15 * s, 40 * s), (x - 40 * s, 40 * s)], fill=BLACKC)
        d.polygon([(x, (H - 40) * s), (x + 25 * s, (H - 40) * s), (x - 15 * s, H * s), (x - 40 * s, H * s)], fill=BLACKC)
    # bolt
    bx, by = 110 * s, 150 * s
    d.polygon([(bx + 20 * s, by - 90 * s), (bx - 40 * s, by + 10 * s), (bx, by + 10 * s), (bx - 20 * s, by + 90 * s),
               (bx + 50 * s, by - 15 * s), (bx + 8 * s, by - 15 * s)], fill=BLACKC)
    d.text((195 * s, 70 * s), "DETERRENT FIELD", font=font(BAHN, 54 * s), fill=BLACKC)
    d.text((195 * s, 145 * s), "DO NOT TOUCH VEHICLE", font=font(BAHN, 40 * s), fill=BLACKC)
    d.text((200 * s, 200 * s), "接触禁止", font=font(JP_BOLD, 40 * s), fill=BLACKC)
    save(img, "shock_warning")


def plate(top, main, name, bg, fg, border):
    W, H = 660, 330
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rounded_rectangle([0, 0, W * s, H * s], 22 * s, fill=bg)
    d.rounded_rectangle([8 * s, 8 * s, (W - 8) * s, (H - 8) * s], 18 * s, outline=border, width=6 * s)
    for x in (70, W - 70):
        d.ellipse([(x - 12) * s, 30 * s, (x + 12) * s, 54 * s], fill=(150, 150, 150, 255))
    d.text((W // 2 * s, 78 * s), top, font=font(JP_BOLD, 64 * s), fill=fg, anchor="mm")
    d.text((80 * s, 225 * s), main[0], font=font(JP_BOLD, 90 * s), fill=fg, anchor="mm")
    d.text((W // 2 * s + 40 * s, 222 * s), main[1], font=font(BAHN, 170 * s), fill=fg, anchor="mm")
    save(img, name)


def cab_door():
    W, H = 1300, 380
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    # a checker block + name
    for i in range(6):
        for j in range(3):
            if (i + j) % 2 == 0:
                d.rectangle([(20 + i * 50) * s, (60 + j * 50) * s, (70 + i * 50) * s, (110 + j * 50) * s], fill=CREAM)
    d.text((350 * s, 40 * s), "KOEN CAB", font=font(BAHN, 150 * s), fill=CREAM)
    d.text((355 * s, 205 * s), "公園タクシー   24H", font=font(JP_BOLD, 76 * s), fill=CREAM)
    d.text((40 * s, 300 * s), "CALL #0451  ·  NO MERIDIAN TRACE ON CASH FARES", font=font(BAHN, 44 * s), fill=CREAM)
    save(img, "cab_door")


def tyre_ring():
    """Sidewall lettering laid round a ring (centre of the image = hub)."""
    W = 2048
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    c = W / 2
    r_text = W * 0.5 * (0.258 / 0.325)    # the raised lettering band on the sidewall (0.245..0.271 m)
    items = [("KANZAKI", 120, BLACK), ("RADIAL  RS-90", 64, BAHN), ("225/50 R16  91V", 64, BAHN),
             ("KANZAKI", 120, BLACK), ("TUBELESS  ·  M+S", 56, BAHN), ("MAX LOAD 615 kg", 52, BAHN)]
    a = 0.0
    total = len(items)
    for k, (txt, px, fn) in enumerate(items):
        f = font(fn, px)
        a0 = k / total * math.tau
        L = f.getlength(txt)
        ang = a0 - (L / r_text) / 2
        for ch in txt:
            w = f.getlength(ch)
            mid = ang + (w / 2) / r_text
            g = Image.new("RGBA", (int(px * 1.6), int(px * 1.6)), (0, 0, 0, 0))
            gd = ImageDraw.Draw(g)
            gd.text((g.width / 2, g.height / 2), ch, font=f, fill=(225, 225, 220, 255), anchor="mm")
            g = g.rotate(-math.degrees(mid), resample=Image.BICUBIC)
            x = c + r_text * math.sin(mid) - g.width / 2
            y = c - r_text * math.cos(mid) - g.height / 2
            img.alpha_composite(g, (int(x), int(y)))
            ang += w / r_text
    img = img.resize((1024, 1024), Image.LANCZOS)
    os.makedirs(OUT, exist_ok=True)
    img.save(os.path.join(OUT, "tyre_ring.png"))
    print("wrote tyre_ring")


def gauges():
    W, H = 900, 300
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rectangle([0, 0, W * s, H * s], fill=(6, 8, 10, 255))
    for cx, maxv in ((170, 8), (450, 180), (730, 4)):
        r = 120
        d.ellipse([(cx - r) * s, (150 - r) * s, (cx + r) * s, (150 + r) * s], outline=(60, 220, 210, 255), width=4 * s)
        for i in range(21):
            a = math.radians(-225 + i * 270 / 20)
            r0 = r - (22 if i % 5 == 0 else 12)
            d.line([((cx + r0 * math.cos(a)) * s, (150 + r0 * math.sin(a)) * s), ((cx + (r - 4) * math.cos(a)) * s, (150 + (r - 4) * math.sin(a)) * s)],
                   fill=(60, 220, 210, 255), width=3 * s)
        a = math.radians(-225 + 270 * 0.32)
        d.line([(cx * s, 150 * s), ((cx + (r - 30) * math.cos(a)) * s, (150 + (r - 30) * math.sin(a)) * s)], fill=(255, 90, 40, 255), width=5 * s)
    d.text((450 * s, 225 * s), "km/h", font=font(BAHN, 30 * s), fill=(60, 220, 210, 255), anchor="mm")
    save(img, "gauges")


def caliper_logo():
    img = canvas(600, 160)
    d = ImageDraw.Draw(img)
    d.text((300 * SS, 80 * SS), "KANZAKI", font=font(BLACK, 120 * SS), fill=WHITE, anchor="mm")
    save(img, "caliper_logo")


def badge():
    img = canvas(600, 200)
    d = ImageDraw.Draw(img)
    d.text((300 * SS, 70 * SS), "TSUBAME", font=font(BAHN, 110 * SS), fill=(220, 222, 226, 255), anchor="mm")
    d.text((300 * SS, 160 * SS), "4  GT-S", font=font(BAHN, 64 * SS), fill=(220, 222, 226, 255), anchor="mm")
    save(img, "badge_tsubame")


def main():
    side_flash(VERMILION, WHITE, "hs_flash", mirror=True)
    side_flash(CREAM, (20, 20, 20, 255), "cab_flash", mirror=True)
    hs_door_text()
    hs_door_text(MIDNIGHT, MIDNIGHT, WHITE, "hs_door_dark")
    hs_hood_crest()
    unit_number("217", "hs_unit", WHITE)
    unit_number("HS-217", "hs_unit_roof", WHITE, w=1600, h=440)
    unit_number("0451", "cab_number", CREAM)
    meridian_sticker()
    shock_warning()
    plate("星川 300", ("け", "2-17"), "plate_hs", (246, 246, 240, 255), (20, 90, 50, 255), (20, 90, 50, 255))
    plate("湾岸 500", ("あ", "4-51"), "plate_cab", (250, 214, 40, 255), (16, 16, 16, 255), (16, 16, 16, 255))
    cab_door()
    tyre_ring()
    gauges()
    caliper_logo()
    badge()


if __name__ == "__main__":
    main()
