"""Livery decals for the fleet (system Python + Pillow).

    python tools/vehicles/decals.py   ->  assets/decals/fleet/*.png

Every company is from the town's story (tools/make_story_decals.py): Hoshikawa Dynamics and
its police (Hoshikawa Security), MERIDIAN (the AI that scores citizens), DREAMLINK (sleep
leasing), NOCTIS (buys memories), and the street: taxi firms, couriers, a noodle van, a
recycler, street racers, the UNPLUG resistance. Plates follow the Japanese colour code
(white private, yellow kei, green commercial) with the city's own corporate series.
"""
import math
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "car"))
from make_decals import ARIAL_B, BAHN, BLACK, IMPACT, JP_BOLD, JP_REG, SS, canvas, finish, font  # noqa: E402

OUT = os.path.join(HERE, "..", "..", "assets", "decals", "fleet")

WHITE = (244, 246, 250, 255)
INK = (16, 16, 18, 255)
VERMILION = (232, 64, 28, 255)
NAVY = (14, 26, 60, 255)
GOLD = (214, 172, 88, 255)
CYAN = (110, 230, 255, 255)
MAGENTA = (255, 90, 210, 255)
PURPLE = (120, 40, 170, 255)
AMBER = (255, 190, 40, 255)
GREEN = (20, 120, 70, 255)
ORANGE = (250, 120, 20, 255)
CREAM = (238, 226, 196, 255)
RED = (210, 30, 40, 255)


def save(img, name, margin=0.0):
    os.makedirs(OUT, exist_ok=True)
    finish(img, margin).save(os.path.join(OUT, name + ".png"))
    print("wrote", name)


def mirrored(name):
    """The right side sees a stripe from the other direction (front on the right)."""
    im = Image.open(os.path.join(OUT, name + ".png"))
    im.transpose(Image.FLIP_LEFT_RIGHT).save(os.path.join(OUT, name + "_r.png"))


def crest(d, cx, cy, r, col, star_col):
    """Hoshikawa crest: a shield with a star over a river."""
    s = r
    pts = [(cx - s, cy - s * 0.9), (cx + s, cy - s * 0.9), (cx + s, cy + s * 0.15), (cx, cy + s * 1.05), (cx - s, cy + s * 0.15)]
    d.polygon(pts, fill=col)
    inner = [(cx + (x - cx) * 0.86, cy + (y - cy) * 0.86) for x, y in pts]
    d.polygon(inner, outline=star_col, width=max(2, int(r * 0.06)))
    st = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r * (0.42 if i % 2 == 0 else 0.17)
        st.append((cx + rr * math.cos(a), cy - r * 0.18 + rr * math.sin(a)))
    d.polygon(st, fill=star_col)
    for k in range(3):
        y0 = cy + r * (0.30 + k * 0.17)
        w = r * (0.75 - k * 0.18)
        line = [(cx - w + t * 2 * w / 30, y0 + math.sin(t / 30 * math.tau * 1.5) * r * 0.045) for t in range(31)]
        d.line(line, fill=star_col, width=max(2, int(r * 0.06)))


def eye(d, cx, cy, r, col, width, crossed=False):
    d.ellipse([cx - r, cy - r * 0.55, cx + r, cy + r * 0.55], outline=col, width=width)
    d.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], fill=col)
    if crossed:
        d.line([cx - r * 1.1, cy + r * 0.8, cx + r * 1.1, cy - r * 0.8], fill=col, width=int(width * 1.6))


def text(d, xy, txt, fnt, px, fill, anchor="la"):
    d.text((xy[0] * SS, xy[1] * SS), txt, font=font(fnt, int(px * SS)), fill=fill, anchor=anchor)


# ------------------------------------------------------------------ stripes and bands


def stripe(name, col, edge=None, W=2400, H=300, kick=True):
    """A long side stripe (left end = front) with an optional kick-up and pin line."""
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.polygon([(0, 120 * s), (W * s, 120 * s), (W * s, 210 * s), (0, 210 * s)], fill=col)
    if kick:
        d.polygon([(0, 120 * s), (0, 40 * s), (360 * s, 40 * s), (260 * s, 120 * s)], fill=col)
    if edge:
        d.line([(0, 226 * s), (W * s, 226 * s)], fill=edge, width=8 * s)
    save(img, name)
    mirrored(name)


def twin_stripes(name, col, W=1600, H=400):
    """Two racing stripes (for the hood / roof / deck, running front to back = up in the image)."""
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    for y0 in (40, 230):
        d.rectangle([0, y0 * s, W * s, (y0 + 130) * s], fill=col)
    save(img, name)


def band(name, c0, c1, W=2400, H=500, chevrons=True):
    """A broad two-colour band for vans and trucks (left = front)."""
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rectangle([0, 180 * s, W * s, 420 * s], fill=c0)
    d.rectangle([0, 420 * s, W * s, 470 * s], fill=c1)
    if chevrons:
        for i in range(5):
            x = 80 * s + i * 120 * s
            d.polygon([(x, 180 * s), (x + 70 * s, 180 * s), (x + 150 * s, 300 * s), (x + 70 * s, 420 * s), (x, 420 * s), (x + 80 * s, 300 * s)], fill=c1)
    save(img, name)
    mirrored(name)


# ------------------------------------------------------------------ companies


def dreamlink_side(name="dreamlink_side"):
    W, H = 2400, 900
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    for i in range(W):
        t = i / W
        d.line([i * s, 0, i * s, H * s], fill=(int(70 + 110 * t), int(20 + 10 * t), int(120 + 60 * (1 - t)), 255), width=s)
    for k in range(7):
        r = (90 + k * 60) * s
        d.ellipse([430 * s - r, 450 * s - r, 430 * s + r, 450 * s + r], outline=(255, 140, 230, 120 - k * 14), width=6 * s)
    text(d, (430, 450), "眠", JP_BOLD, 330, (255, 240, 250, 255), "mm")
    text(d, (1520, 300), "DREAMLINK", IMPACT, 230, (255, 240, 250, 255), "mm")
    text(d, (1520, 500), "YOUR SLEEP IS WORTH MONEY", BAHN, 76, (255, 205, 245, 255), "mm")
    text(d, (1520, 620), "POD DELIVERY  ·  睡眠リース", JP_BOLD, 64, WHITE, "mm")
    text(d, (1520, 760), "A HOSHIKAWA DYNAMICS SERVICE", ARIAL_B, 40, (230, 190, 235, 255), "mm")
    save(img, name)


def dreamlink_logo(name="dreamlink_logo"):
    W, H = 1200, 400
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.ellipse([20 * s, 40 * s, 340 * s, 360 * s], fill=(130, 40, 190, 255))
    text(d, (180, 200), "眠", JP_BOLD, 220, WHITE, "mm")
    text(d, (380, 110), "DREAMLINK", IMPACT, 150, WHITE)
    text(d, (385, 280), "SLEEP LEASING", BAHN, 56, (255, 190, 240, 255))
    save(img, name)


def noctis_side(name="noctis_side"):
    W, H = 2400, 800
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rectangle([0, 0, W * s, H * s], fill=(10, 10, 12, 255))
    d.rectangle([30 * s, 30 * s, (W - 30) * s, (H - 30) * s], outline=AMBER, width=10 * s)
    text(d, (W / 2, 240), "NOCTIS", BLACK, 290, AMBER, "mm")
    text(d, (W / 2, 450), "WE BUY WHAT YOU DON'T NEED", BAHN, 96, WHITE, "mm")
    text(d, (W / 2, 590), "MEMORIES · SLEEP CYCLES · KIDNEYS", BAHN, 70, AMBER, "mm")
    text(d, (W / 2, 700), "COLLECTION SERVICE  記憶買取  24H", JP_BOLD, 56, (200, 200, 200, 255), "mm")
    save(img, name)


def noctis_logo(name="noctis_logo"):
    W, H = 1000, 320
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rectangle([0, 0, W * s, H * s], fill=(10, 10, 12, 255))
    d.rectangle([12 * s, 12 * s, (W - 12) * s, (H - 12) * s], outline=AMBER, width=8 * s)
    text(d, (W / 2, 140), "NOCTIS", BLACK, 170, AMBER, "mm")
    text(d, (W / 2, 262), "COLLECTION", BAHN, 52, WHITE, "mm")
    save(img, name)


def hoshikawa_side(name, division, jp):
    W, H = 2000, 520
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    crest(d, 230 * s, 250 * s, 190 * s, WHITE, NAVY)
    text(d, (470, 70), "HOSHIKAWA", BAHN, 190, WHITE)
    text(d, (474, 270), "DYNAMICS", BAHN, 120, GOLD)
    text(d, (1180, 290), division, BAHN, 96, WHITE)
    text(d, (474, 420), jp, JP_BOLD, 70, WHITE)
    save(img, name)


def hoshikawa_door(name, sub, fg=WHITE, accent=GOLD):
    W, H = 1300, 380
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    crest(d, 160 * s, 180 * s, 130 * s, fg, NAVY if fg == WHITE else WHITE)
    text(d, (320, 50), "HOSHIKAWA", BAHN, 140, fg)
    text(d, (325, 205), sub, BAHN, 88, accent)
    save(img, name)


def meridian_side(name, line1, line2, dark=False):
    W, H = 2000, 600
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    col = CYAN if dark else (20, 120, 160, 255)
    fg = (235, 250, 255, 255) if dark else (14, 30, 46, 255)
    eye(d, 290 * s, 300 * s, 230 * s, col, 22 * s)
    text(d, (590, 90), "MERIDIAN", BAHN, 230, fg)
    text(d, (596, 340), line1, BAHN, 96, col)
    text(d, (598, 470), line2, JP_BOLD, 64, fg)
    save(img, name)


def meridian_eye_logo(name, col):
    W = 600
    img = canvas(W, W // 2)
    d = ImageDraw.Draw(img)
    s = SS
    eye(d, 300 * s, 150 * s, 270 * s, col, 26 * s)
    save(img, name)


def hs_patrol(name, line, sub):
    W, H = 1500, 420
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    crest(d, 190 * s, 200 * s, 160 * s, WHITE, NAVY)
    text(d, (390, 50), "HOSHIKAWA", BAHN, 160, WHITE)
    text(d, (395, 225), line, BAHN, 104, VERMILION)
    text(d, (395, 345), sub, JP_BOLD, 56, WHITE)
    save(img, name)


def taxi_door(name, title, jp, phone, col, fg):
    W, H = 1300, 400
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    # a rising sun disc + rays
    cx, cy = 150 * s, 200 * s
    for i in range(12):
        a = math.radians(i * 30)
        d.polygon([(cx, cy), (cx + 160 * s * math.cos(a - 0.08), cy + 160 * s * math.sin(a - 0.08)),
                   (cx + 160 * s * math.cos(a + 0.08), cy + 160 * s * math.sin(a + 0.08))], fill=col)
    d.ellipse([cx - 80 * s, cy - 80 * s, cx + 80 * s, cy + 80 * s], fill=fg)
    text(d, (330, 40), title, BAHN, 150, fg)
    text(d, (334, 210), jp, JP_BOLD, 80, fg)
    text(d, (334, 320), phone, BAHN, 52, fg)
    save(img, name)


def roof_number(name, txt, col, w=1000, h=420):
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    d.text((w // 2 * SS, h // 2 * SS), txt, font=font(BLACK, int(h * 0.8) * SS), fill=col, anchor="mm")
    save(img, name)


def courier_side(name="tsuru_side"):
    """TSURU EXPRESS: a red crane in a green circle, red / green lettering."""
    W, H = 2200, 700
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.ellipse([40 * s, 60 * s, 620 * s, 640 * s], fill=GREEN)
    # stylised crane: body, neck, wings
    cx, cy = 330 * s, 360 * s
    d.polygon([(cx - 200 * s, cy + 40 * s), (cx + 40 * s, cy - 60 * s), (cx + 210 * s, cy - 220 * s), (cx + 120 * s, cy - 40 * s),
               (cx + 40 * s, cy + 80 * s)], fill=WHITE)
    d.polygon([(cx - 40 * s, cy - 10 * s), (cx - 230 * s, cy - 220 * s), (cx - 80 * s, cy - 40 * s)], fill=WHITE)
    d.ellipse([cx + 180 * s, cy - 250 * s, cx + 230 * s, cy - 200 * s], fill=RED)
    text(d, (690, 110), "TSURU", IMPACT, 260, RED)
    text(d, (694, 380), "EXPRESS", BAHN, 130, GREEN)
    text(d, (700, 540), "鶴急便  ·  NIGHT PARCELS  ·  #0880", JP_BOLD, 60, INK)
    save(img, name)


def ramen_side(name="ramen_side"):
    W, H = 2000, 700
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rounded_rectangle([0, 0, W * s, H * s], 60 * s, fill=(180, 24, 30, 255))
    d.rounded_rectangle([24 * s, 24 * s, (W - 24) * s, (H - 24) * s], 46 * s, outline=CREAM, width=10 * s)
    text(d, (330, 350), "麺", JP_BOLD, 420, CREAM, "mm")
    text(d, (620, 120), "RAMEN KIRA", IMPACT, 190, CREAM)
    text(d, (624, 360), "らーめん輝  深夜営業", JP_BOLD, 96, (255, 214, 120, 255))
    text(d, (624, 510), "SHOYU · TONKOTSU · NO SCORE NEEDED", BAHN, 58, CREAM)
    save(img, name)


def recycle_side(name="recycle_side"):
    W, H = 2000, 560
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    cx, cy, r = 260 * s, 280 * s, 210 * s
    for k in range(3):
        a0 = k * 120
        d.arc([cx - r, cy - r, cx + r, cy + r], a0 + 15, a0 + 100, fill=(40, 160, 80, 255), width=44 * s)
        a = math.radians(a0 + 100)
        tx, ty = cx + r * math.cos(a), cy + r * math.sin(a)
        d.polygon([(tx + 50 * s * math.cos(a + 1.2), ty + 50 * s * math.sin(a + 1.2)), (tx - 50 * s * math.cos(a + 1.2), ty - 50 * s * math.sin(a + 1.2)),
                   (tx + 60 * s * math.cos(a + math.pi / 2 + 0.2), ty + 60 * s * math.sin(a + math.pi / 2 + 0.2))], fill=(40, 160, 80, 255))
    text(d, (540, 80), "SHIGEN", IMPACT, 220, (30, 110, 60, 255))
    text(d, (544, 330), "RECYCLE  資源回収", JP_BOLD, 110, INK)
    save(img, name)


def racing_roundel(name, num):
    W = 600
    img = canvas(W, W)
    d = ImageDraw.Draw(img)
    s = SS
    d.ellipse([10 * s, 10 * s, 590 * s, 590 * s], fill=WHITE)
    d.ellipse([10 * s, 10 * s, 590 * s, 590 * s], outline=INK, width=16 * s)
    text(d, (300, 310), num, BLACK, 330, INK, "mm")
    save(img, name)


def sponsor(name, title, sub, fg, bg=None, W=1400, H=300):
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    if bg:
        d.rectangle([0, 0, W * s, H * s], fill=bg)
    text(d, (W / 2, 120), title, IMPACT, 170, fg, "mm")
    if sub:
        text(d, (W / 2, 245), sub, BAHN, 60, fg, "mm")
    save(img, name)


def plate(name, top, kana, num, bg, fg, border):
    W, H = 660, 330
    img = canvas(W, H)
    d = ImageDraw.Draw(img)
    s = SS
    d.rounded_rectangle([0, 0, W * s, H * s], 22 * s, fill=bg)
    d.rounded_rectangle([8 * s, 8 * s, (W - 8) * s, (H - 8) * s], 18 * s, outline=border, width=6 * s)
    for x in (70, W - 70):
        d.ellipse([(x - 12) * s, 30 * s, (x + 12) * s, 54 * s], fill=(150, 150, 150, 255))
    text(d, (W // 2, 78), top, JP_BOLD, 64, fg, "mm")
    text(d, (80, 225), kana, JP_BOLD, 90, fg, "mm")
    text(d, (W // 2 + 40, 222), num, BAHN, 170, fg, "mm")
    save(img, name)


def tyre_ring(name, brand, line, size, band_frac):
    """Sidewall lettering laid round a ring (centre of the image = hub). `band_frac` = the raised
    band's radius as a fraction of the tyre radius (the decal is fitted to the tyre's diameter)."""
    W = 2048
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    c = W / 2
    r_text = W * 0.5 * band_frac
    px_big = int(120 * band_frac / 0.79)
    px_small = int(62 * band_frac / 0.79)
    items = [(brand, px_big, BLACK), (line, px_small, BAHN), (size, px_small, BAHN),
             (brand, px_big, BLACK), ("TUBELESS  ·  M+S", px_small, BAHN), ("MADE IN NEO-KAWASAKI", px_small, BAHN)]
    for k, (txt, px, fn) in enumerate(items):
        f = font(fn, px)
        a0 = k / len(items) * math.tau
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
    img.save(os.path.join(OUT, name + ".png"))
    print("wrote", name)


def badge(name, line1, line2):
    img = canvas(600, 200)
    d = ImageDraw.Draw(img)
    text(d, (300, 70), line1, BAHN, 110, (220, 222, 226, 255), "mm")
    text(d, (300, 160), line2, BAHN, 60, (220, 222, 226, 255), "mm")
    save(img, name)


def maker_logo(name, txt, col=WHITE):
    img = canvas(700, 180)
    d = ImageDraw.Draw(img)
    text(d, (350, 90), txt, BLACK, 130, col, "mm")
    save(img, name)


def main():
    # stripes / bands
    stripe("stripe_cream", CREAM, (20, 20, 20, 255))
    stripe("stripe_orange", ORANGE, WHITE)
    stripe("stripe_vermilion", VERMILION, WHITE)
    stripe("stripe_cyan", CYAN, None, kick=False)
    stripe("stripe_white", WHITE, None)
    twin_stripes("twin_stripes_white", WHITE)
    twin_stripes("twin_stripes_black", (20, 20, 22, 255))
    band("band_tsuru", RED, GREEN)
    band("band_hoshikawa", NAVY, GOLD, chevrons=False)
    band("band_recycle", (40, 150, 80, 255), WHITE)
    # companies
    dreamlink_side()
    dreamlink_logo()
    noctis_side()
    noctis_logo()
    hoshikawa_side("hd_logistics", "LOGISTICS", "星川ダイナミクス 物流")
    hoshikawa_side("hd_facilities", "FACILITIES", "星川ダイナミクス 施設管理")
    hoshikawa_door("hd_door_exec", "DYNAMICS", WHITE, GOLD)
    hoshikawa_door("hd_door_facilities", "FACILITIES", WHITE, GOLD)
    meridian_side("meridian_ride", "RIDE · RATED · SAFE", "あなたの移動を評価します", dark=False)
    meridian_side("meridian_ride_dark", "RIDE · RATED · SAFE", "あなたの移動を評価します", dark=True)
    meridian_side("meridian_inspector", "SCORE INSPECTOR", "市民スコア調査員", dark=False)
    meridian_eye_logo("meridian_eye_cyan", CYAN)
    meridian_eye_logo("meridian_eye_ink", (20, 60, 90, 255))
    hs_patrol("hs_pursuit", "PURSUIT", "星川警備 追跡班")
    hs_patrol("hs_patrol_pod", "PATROL", "星川警備 自動巡回")
    taxi_door("hinode_door", "HINODE", "日の出交通  タクシー", "CALL #1177 · CASH OK", ORANGE, INK)
    roof_number("hinode_number", "1177", INK)
    roof_number("racing_27", "27", INK)
    courier_side()
    ramen_side()
    recycle_side()
    racing_roundel("roundel_27", "27")
    sponsor("sponsor_kanzaki", "KANZAKI RACING", "TEAM NEO-KAWASAKI", WHITE)
    sponsor("sponsor_jailbreak", "JAILBREAK", "IMPLANT TUNING · NO LOGS", (255, 230, 40, 255))
    sponsor("rusty_for_sale", "売ります", "FOR SALE · NO SCORE CHECK · 080-4471", (240, 240, 240, 255), (200, 30, 30, 255), 900, 300)
    # plates
    plate("plate_private_1", "湾岸 330", "さ", "47-19", (246, 246, 240, 255), (20, 90, 50, 255), (20, 90, 50, 255))
    plate("plate_private_2", "湾岸 300", "ね", "8-03", (246, 246, 240, 255), (20, 90, 50, 255), (20, 90, 50, 255))
    plate("plate_private_3", "星川 500", "ほ", "1-22", (246, 246, 240, 255), (20, 90, 50, 255), (20, 90, 50, 255))
    plate("plate_kei_1", "湾岸 580", "え", "60-44", (250, 210, 40, 255), (20, 20, 20, 255), (20, 20, 20, 255))
    plate("plate_kei_2", "湾岸 580", "う", "3-91", (250, 210, 40, 255), (20, 20, 20, 255), (20, 20, 20, 255))
    plate("plate_commercial_1", "湾岸 400", "あ", "21-07", (24, 110, 60, 255), (246, 246, 240, 255), (246, 246, 240, 255))
    plate("plate_commercial_2", "湾岸 100", "か", "88-12", (24, 110, 60, 255), (246, 246, 240, 255), (246, 246, 240, 255))
    plate("plate_corp", "星川 800", "社", "0-01", (16, 18, 22, 255), (214, 172, 88, 255), (214, 172, 88, 255))
    plate("plate_meridian", "MERIDIAN", "自", "7-07", (240, 248, 252, 255), (20, 100, 140, 255), (20, 100, 140, 255))
    plate("plate_hs_2", "星川 300", "け", "4-02", (246, 246, 240, 255), (20, 40, 90, 255), (20, 40, 90, 255))
    # wheels and badges
    tyre_ring("tyre_mame", "KANZAKI", "ECO  KS-13", "145/80 R13  75S", 0.62)
    tyre_ring("tyre_hakobi", "ISHIMARU", "CARGO  LT-7", "195/80 R15  107L", 0.66)
    tyre_ring("tyre_hayate", "KANZAKI", "RADIAL  RS-90R", "235/45 R17  94W", 0.69)
    tyre_ring("tyre_kaiun", "ISHIMARU", "HAULER  LT-9", "205/85 R16  117L", 0.63)
    tyre_ring("tyre_kago", "MERIDIAN", "SILENT  EV-1", "215/55 R17  98V", 0.68)
    badge("badge_mame", "MAME", "K3  TURBO")
    badge("badge_hakobi", "HAKOBI", "LH-200")
    badge("badge_hayate", "HAYATE", "RS  TWIN TURBO")
    badge("badge_kaiun", "KAIUN", "2t  DIESEL")
    badge("badge_kago", "KAGO", "AUTONOMOUS")
    maker_logo("logo_ishimaru", "ISHIMARU")
    maker_logo("logo_kanzaki", "KANZAKI")


if __name__ == "__main__":
    main()
