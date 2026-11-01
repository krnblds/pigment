"""Advertising for the town: a city where bodies, attention, sleep and memories are for sale.

The world is the one in tools/make_story_decals.py (Hoshikawa Dynamics owns the
city, MERIDIAN scores every citizen, Dreamlink leases sleep, Noctis buys
memories, UNPLUG paints over all of it).  This adds the commercial noise of
such a city:

  * hyper-capitalist corporate ads: Hoshikawa cyberlimbs / Home / Security
    subscriptions, MERIDIAN premium citizenship tiers, Dreamlink and Noctis,
    energy drinks, synthetic ramen, watches, Kanzaki cars, loans, organ
    insurance, renting your face, selling your attention by the hour,
    subscription air and water, gacha, lotteries, pachinko, coin scams,
    fractional capsules, and SALE / LIMITED / NOW overload;
  * the red-light district's adult-entertainment advertising (suggestive,
    never explicit; every implied person is an adult and fully clothed:
    silhouettes in gowns and suits, lips, heels, gloved hands, a corset on a
    dress form, neon hearts): Hotel Velvet Moon (hourly rates), Club Sapphire
    (hostess), Host Club ZERO, Dolls by Kisaragi (companion androids),
    Dreamlink Intimate, Cabaret Luna, the Rose Theatre burlesque revue, Noir
    Satin lingerie, MATCHA dating (scored by MERIDIAN), a peep show, call cards;
  * the street answering back: defaced ads, torn layers of old posters,
    MISSING flyers pasted over the glamour.

Formats (prefix -> use; tools/decal_audit.py keys its placement rules on it):
    billboard_ad_*  2:1      billboard panels only (rooftop, back wall, crowns, towers)
    poster_ad_*     0.7      street-level paper (0.8-2.2 m), scattered and overlapping
    flyer_*         0.71     photocopied wheat-paste flyers (poster rules)
    sticker_*       0.71     call cards and stickers (poster rules)
    lightbox_*      0.63     bus-stop lightboxes (props)
    holo_*          0.29     holo-pylon loop frames (props; _1 _2 _3 are one loop)
    kiosk_*         0.65     data-kiosk screens (props)
    banner_*        0.21     lit vertical banners (blade sign faces)
    window_*        2:1      vinyl lettering for glass (transparent)
    sign_* / blade_*         neon glyphs (white, tinted + emissive in Pigment)

Styles: corporate clean, sleazy neon, retro Showa kitsch, glitch, photocopy.
Everything is drawn with PIL shapes, gradients and type (Yu Gothic, Bahnschrift,
Impact, Arial Black, Georgia, Segoe Script): no photos, no downloaded imagery.

    python tools/make_ad_decals.py [names...]          ->  assets/decals/ads/*.png
    python tools/make_ad_decals.py --sheet out.png     (contact sheet of every design)
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ads_kit import (ARIAL_B, BAHN, BLACK, COND, IMPACT, JP_BOLD, JP_REG, MINCHO, MONO, SCRIPT, SCRIPT_B, SERIF,  # noqa: E402
                     SERIF_I, STENCIL, Art, barcode, bowl, can, chaikin, coupe, corset, crescent, cyber_arm, dress_form, eye,
                     gauge, glitch, gloved_arm, heart, heart_pts, keyhole, legs_pair, lips, man_suit, mix, neon_heart, noise,
                     paste_over, photocopy, profile, qr, rgba, rip_to, showa, spray, star_pts, stiletto, strike, torn, watch,
                     woman_gown)
from make_decals import neon_text  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "decals", "ads")

W_ = (245, 245, 242, 255)
INK = (18, 18, 22, 255)
CYAN = (110, 230, 255, 255)
HOT = (255, 40, 140, 255)
GOLD = (240, 196, 110, 255)
RED = (220, 25, 45, 255)
VIOLET = (150, 80, 255, 255)
MER_BG = (8, 22, 40)

R = {}          # name -> maker


def ad(name):
    def deco(fn):
        R[name] = fn
        return fn
    return deco


def phone(seed):
    rnd = random.Random(seed)
    return f"090-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}"


def small_print(a, b, txt, col):
    a.fit(b, txt, col, ARIAL_B)


# ==================================================================== billboards 2:1 (corporate)

@ad("billboard_ad_hoshikawa_limbs")
def bb_limbs():
    a = Art("billboard")
    a.hgrad((0, 0, 1600, 800), (236, 238, 242), (200, 206, 214))
    a.radial(480, 420, 420, (255, 255, 255, 255), (220, 225, 232, 0))
    cyber_arm(a, 60, 170, 640, (70, 78, 92), (230, 30, 60))
    a.text((1200, 170), "UPGRADE", 130, INK, BAHN)
    a.text((1200, 300), "YOURSELF.", 130, (230, 30, 60, 255), BAHN)
    a.text((1180, 420), "HOSHIKAWA KINETIC LIMBS  ·  義体", 44, (60, 66, 80, 255))
    a.rect((900, 480, 1460, 482), fill=(60, 66, 80, 255))
    a.rows((900, 500, 1460, 690), [("Finance from 0% · pay with your future earnings", (40, 44, 54, 255), 1),
                                   ("Your old arm is worth ¥6,000 at any Noctis counter", (40, 44, 54, 255), 1),
                                   ("リース契約は市民スコア600以上の方に限ります", (90, 96, 110, 255), 1)])
    a.text((1540, 760), "HOSHIKAWA DYNAMICS", 30, (230, 30, 60, 255), BAHN, anchor="rb")
    return a.out()


@ad("billboard_ad_hoshikawa_home")
def bb_home():
    a = Art("billboard")
    a.vgrad((0, 0, 1600, 800), (255, 246, 232), (250, 220, 190))
    # a warm house icon with a camera eye in the window
    a.poly([(200, 380), (420, 200), (640, 380)], fill=(230, 30, 60, 255))
    a.rect((250, 380, 590, 660), fill=(255, 255, 255, 255))
    a.rect((370, 470, 470, 660), fill=(250, 200, 150, 255))
    eye(a, 420, 300, 60, (255, 255, 255), 8)
    a.text((1100, 180), "HOSHIKAWA HOME", 110, (40, 30, 30, 255), BAHN)
    a.text((1100, 320), "Your house is listening.", 74, (230, 30, 60, 255), SERIF_I)
    a.text((1100, 420), "So you never have to ask.", 54, (60, 50, 50, 255), SERIF_I)
    a.rows((760, 500, 1440, 680), [("FRIDGE · DOORS · CHILD-FREE BEDROOM MODE · MOOD LIGHTING", (90, 70, 60, 255), 1),
                                   ("家があなたを見守ります", (90, 70, 60, 255), 1.1),
                                   ("Voice data shared with MERIDIAN for your wellbeing.", (150, 120, 110, 255), 0.8)])
    return a.out()


@ad("billboard_ad_hoshikawa_secure")
def bb_secure():
    a = Art("billboard", (16, 16, 20))
    a.radial(1250, 400, 520, (120, 20, 30, 255), (16, 16, 20, 0))
    a.text((70, 140), "SAFETY IS A", 96, W_, BAHN, anchor="lm")
    a.text((70, 250), "SUBSCRIPTION.", 120, (230, 50, 60, 255), BAHN, anchor="lm")
    tiers = [("BRONZE", "¥980/mo", "patrol passes your street", (190, 120, 70)),
             ("SILVER", "¥4,800/mo", "a drone answers in 20 min", (200, 205, 215)),
             ("GOLD", "¥19,800/mo", "they arrive before you call", (240, 200, 90))]
    for i, (t, p, d, c) in enumerate(tiers):
        x = 70 + i * 370
        a.rect((x, 360, x + 340, 700), outline=rgba(c), width=5, r=18)
        a.fit((x + 20, 380, x + 320, 460), t, rgba(c), BAHN)
        a.fit((x + 20, 470, x + 320, 560), p, W_, BAHN)
        a.fit((x + 20, 590, x + 320, 640), d, (190, 190, 195, 255), ARIAL_B)
    a.poly([(1370, 330), (1500, 380), (1480, 560), (1370, 630), (1260, 560), (1240, 380)], fill=(200, 30, 40, 255))
    a.text((1370, 480), "HS", 120, W_, BLACK)
    a.text((1530, 760), "HOSHIKAWA SECURITY · unsubscribed homes are not monitored", 26, (150, 150, 155, 255), ARIAL_B, anchor="rb")
    return a.out()


@ad("billboard_ad_meridian_platinum")
def bb_platinum():
    a = Art("billboard")
    a.hgrad((0, 0, 1600, 800), (22, 24, 30), (70, 74, 84))
    for k in range(18):
        a.line([(800 + k * 60, 0), (600 + k * 60, 800)], (255, 255, 255, 10), 18)
    # the platinum card
    a.rect((110, 170, 690, 540), fill=(214, 218, 226, 255), r=30)
    a.hgrad((110, 170, 690, 200), (240, 242, 246), (190, 196, 206))
    a.rect((110, 170, 690, 540), outline=(255, 255, 255, 255), width=4, r=30)
    eye(a, 210, 280, 60, (40, 60, 90), 8)
    a.text((660, 470), "PLATINUM", 54, (40, 44, 56, 255), BAHN, anchor="rm", spacing=6)
    a.text((150, 470), "891", 80, (40, 44, 56, 255), MONO, anchor="lm")
    a.text((1160, 170), "UPGRADE TO", 80, (210, 214, 224, 255), BAHN)
    a.text((1160, 290), "PLATINUM", 150, W_, BAHN, spacing=8)
    a.text((1160, 400), "CITIZEN", 110, (210, 214, 224, 255), BAHN, spacing=8)
    a.rows((820, 470, 1500, 690), [("Priority doors · clean-air lanes · zero curfew", (220, 224, 232, 255), 1),
                                   ("Your neighbours will notice.", (160, 210, 255, 255), 1, SERIF_I),
                                   ("プラチナ市民へ  ·  月額 ¥88,000", (200, 204, 214, 255), 1)])
    a.text((1540, 770), "MERIDIAN CITIZENSHIP SERVICES", 26, (150, 160, 175, 255), BAHN, anchor="rb")
    return a.out()


@ad("billboard_ad_meridian_future")
def bb_future():
    a = Art("billboard", MER_BG)
    a.radial(400, 420, 420, (20, 70, 110, 255), (8, 22, 40, 0))
    gauge(a, 400, 430, 270, 0.78, (120, 255, 170), (255, 255, 255, 40), 34)
    a.text((400, 420), "742", 190, W_, MONO)
    a.text((400, 560), "▲ +12 TODAY", 46, (120, 255, 170, 255))
    a.text((1100, 200), "YOUR SCORE", 120, W_, BAHN)
    a.text((1100, 330), "IS YOUR FUTURE.", 104, CYAN, BAHN)
    a.text((1100, 470), "あなたのスコアが、あなたの未来です。", 44, (170, 210, 235, 255))
    a.rows((800, 540, 1420, 700), [("Rent · rations · doors · dates · jobs · love", (190, 220, 240, 255), 1),
                                   ("all calculated, all fair.", (120, 230, 255, 255), 1, SERIF_I)])
    a.text((1540, 760), "— MERIDIAN", 40, CYAN, BAHN, anchor="rb")
    return a.out()


@ad("billboard_ad_dreamlink_premium")
def bb_dreamlink_premium():
    a = Art("billboard")
    a.hgrad((0, 0, 1600, 800), (14, 10, 50), (70, 20, 110))
    a.bokeh(5, 40, [(140, 180, 255), (220, 140, 255), (255, 200, 255)], 6, 26, alpha=(30, 90))
    crescent(a, 360, 360, 220, (240, 230, 255), (30, 14, 70))
    for i in range(3):
        a.text((560 + i * 70, 180 - i * 50), "z", 70 + i * 20, (220, 200, 255, 220), SERIF_I)
    a.text((1100, 170), "DREAMLINK", 140, W_, IMPACT)
    a.text((1100, 290), "PREMIUM SLEEP", 74, (200, 170, 255, 255), BAHN, spacing=4)
    a.text((1100, 420), "9 hours. ¥120. Wake up rested*", 56, W_, BAHN)
    a.text((1100, 510), "眠っている間に、稼ごう。", 50, (230, 210, 255, 255))
    a.text((1100, 690), "*rested is not guaranteed. dreams may belong to other users.", 28, (190, 170, 220, 255), ARIAL_B)
    return a.out()


@ad("billboard_ad_dreamlink_intimate")
def bb_intimate():
    a = Art("billboard")
    a.hgrad((0, 0, 1600, 800), (40, 0, 30), (110, 10, 60))
    a.bokeh(9, 45, [(255, 80, 160), (255, 160, 200), (180, 60, 255)], 8, 40, alpha=(30, 100), blur=5)
    a.radial(420, 420, 380, (255, 110, 180, 200), (90, 10, 60, 0))
    # two adult profiles, almost touching
    profile(a, 120, 160, 520, (20, 0, 14))
    profile(a, 360, 160, 520, (20, 0, 14), flip=True)
    a.text((1110, 160), "DREAMLINK", 70, (255, 190, 220, 255), BAHN, spacing=10)
    a.text((1110, 290), "Intimate", 170, W_, SCRIPT_B)
    a.text((1110, 430), "Whoever you want. All night. Nobody has to know.", 40, (255, 210, 230, 255), SERIF_I)
    a.text((1110, 520), "夢の中なら、誰とでも。", 56, (255, 160, 200, 255))
    a.rect((1440, 610, 1540, 680), outline=(255, 160, 200, 255), width=4, r=10)
    a.text((1490, 645), "R18", 40, (255, 160, 200, 255), BAHN)
    a.text((780, 760), "Partners are licensed dream-likenesses of consenting adult performers. Your fantasy is logged for quality.", 22,
           (230, 170, 200, 255), ARIAL_B, anchor="lm")
    return a.out()


@ad("billboard_ad_noctis_firstkiss")
def bb_firstkiss():
    a = Art("billboard", (10, 8, 10))
    a.rect((50, 50, 1550, 750), outline=(255, 190, 40, 255), width=4)
    lips(a, 400, 400, 520, (200, 30, 50))
    a.text((1060, 170), "SELL YOUR", 90, W_, BAHN)
    a.text((1060, 290), "FIRST KISS", 130, (255, 190, 40, 255), BLACK)
    a.text((1060, 420), "¥2,000 · instant transfer · we keep it safe", 44, (230, 230, 230, 255), BAHN)
    a.text((1060, 500), "初恋の記憶、高価買取。", 52, (255, 190, 40, 255))
    a.text((1060, 620), "You won't miss what you can't remember.", 40, (200, 200, 200, 255), SERIF_I)
    a.text((1540, 740), "NOCTIS", 50, (255, 190, 40, 255), BLACK, anchor="rb")
    return a.out()


@ad("billboard_ad_volt_rush")
def bb_volt():
    a = Art("billboard", (12, 12, 12))
    for k in range(14):
        a.poly([(k * 140 - 200, 800), (k * 140 - 100, 800), (k * 140 + 300, 0), (k * 140 + 200, 0)], fill=(255, 220, 0, 18))
    a.poly([(620, 60), (430, 420), (560, 420), (470, 760), (760, 330), (620, 330), (720, 60)], fill=(255, 225, 0, 255))
    can(a, 160, 200, 200, 470, (20, 20, 20), (255, 220, 0), "VOLT RUSH", INK)
    a.text((1180, 150), "VOLT RUSH", 170, (255, 225, 0, 255), IMPACT)
    a.text((1180, 310), "SLEEP IS FOR THE POOR.", 76, W_, IMPACT)
    a.text((1180, 420), "400mg caffeine · 3 nootropics · 0 regrets", 46, (220, 220, 220, 255), BAHN)
    a.text((1180, 510), "眠らない街の、眠らないあなたへ。", 46, (255, 225, 0, 255))
    a.text((1180, 700), "Not for use with Dreamlink. Do not exceed 6 cans per shift.", 28, (160, 160, 160, 255), ARIAL_B)
    return a.out()


@ad("billboard_ad_ramen_kira")
def bb_ramen():
    a = Art("billboard")
    a.vgrad((0, 0, 1600, 800), (250, 200, 40), (240, 120, 20))
    a.halftone((200, 40, 20), (0, 0, 1600, 800), 22, 0.45, "v", 90)
    a.circle(420, 430, 330, fill=(255, 245, 220, 255))
    bowl(a, 420, 470, 240, (200, 20, 30), (250, 245, 235))
    a.text((1120, 140), "ラーメン輝", 120, (180, 10, 20, 255), JP_BOLD)
    a.text((1120, 270), "RAMEN KIRA", 100, INK, BLACK)
    a.text((1120, 400), "REAL BEEF FLAVOUR™", 82, W_, IMPACT, stroke=4, stroke_fill=(180, 10, 20, 255))
    a.text((1120, 500), "(contains no beef)", 44, INK, SERIF_I)
    a.text((1120, 620), "3 MINUTES · ¥90 · 1,840 kcal", 50, INK, BAHN)
    a.text((1120, 700), "合成牛エキス使用 · 味覚は個人差があります", 32, (120, 20, 20, 255))
    return a.out()


@ad("billboard_ad_kagerou_watch")
def bb_watch():
    a = Art("billboard", (6, 6, 8))
    a.radial(430, 400, 420, (60, 50, 40, 255), (6, 6, 8, 0))
    watch(a, 430, 400, 210, (210, 175, 100), (14, 14, 18), (240, 222, 170), (40, 26, 18))
    a.text((1120, 220), "KAGEROU", 130, (232, 205, 140, 255), SERIF, spacing=14)
    a.text((1120, 330), "陽炎  ·  CHRONOGRAPH", 40, (180, 160, 120, 255), spacing=6)
    a.text((1120, 470), "Time is the only luxury", 54, (235, 230, 220, 255), SERIF_I)
    a.text((1120, 540), "you cannot lease.", 54, (235, 230, 220, 255), SERIF_I)
    a.text((1120, 690), "From ¥4,800,000 · or 360 monthly payments of your future", 26, (150, 140, 120, 255), ARIAL_B)
    return a.out()


@ad("billboard_ad_kanzaki_hayate")
def bb_hayate():
    a = Art("billboard")
    a.vgrad((0, 0, 1600, 800), (10, 6, 30), (60, 10, 70))
    for k in range(12):
        y = 520 + k * k * 2.2
        a.line([(0, y), (1600, y)], (255, 60, 200, 60), 2)
    for k in range(-10, 11):
        a.line([(800 + k * 40, 520), (800 + k * 260, 800)], (255, 60, 200, 50), 2)
    a.circle(800, 470, 170, fill=(255, 120, 60, 255))
    for k in range(6):
        a.rect((600, 470 + k * 26, 1000, 470 + k * 26 + 8 + k * 2), fill=(60, 10, 70, 255))
    a.rect((0, 520, 1600, 524), fill=(255, 120, 200, 255))
    coupe(a, 520, 700, 640, (150, 30, 200), (20, 10, 40), light=(220, 240, 255))
    a.text((800, 110), "KANZAKI  HAYATE RS", 110, W_, IMPACT, spacing=4)
    a.text((800, 210), "THE ROAD IS STILL YOURS.", 52, (255, 150, 220, 255), BAHN, spacing=6)
    a.text((80, 760), "Hayate RS · 疾風 · Requires citizen score 650+ to register. Lease approved in 4 seconds.", 26, (220, 200, 240, 255), ARIAL_B, anchor="lm")
    return a.out()


@ad("billboard_ad_sakura_credit")
def bb_credit():
    a = Art("billboard", (255, 236, 242))
    for k in range(40):
        rnd = random.Random(k)
        cx, cy, r = rnd.uniform(0, 1600), rnd.uniform(0, 800), rnd.uniform(8, 22)
        for j in range(5):
            t = j * 72 + rnd.uniform(0, 72)
            a.circle(cx + r * math.cos(math.radians(t)), cy + r * math.sin(math.radians(t)), r * 0.6, fill=(255, 170, 200, 120))
    a.text((800, 130), "SAKURA CREDIT", 100, (210, 20, 90, 255), BLACK)
    a.text((800, 260), "ONE DEBT. ONE SMILE.", 110, INK, IMPACT)
    a.text((800, 380), "Consolidate every loan into one easy plan", 50, (60, 30, 40, 255), BAHN)
    a.rect((260, 450, 1340, 640), fill=(210, 20, 90, 255), r=24)
    a.text((800, 510), "APPROVED IN 4 SECONDS", 66, W_, BAHN)
    a.text((800, 590), "collateral accepted: kidneys · corneas · sleep · next of kin", 36, (255, 220, 235, 255), ARIAL_B)
    a.text((800, 720), "おまとめローン  実質年率 39.8%〜 · ご返済はスコアから自動引落", 34, (120, 40, 70, 255))
    return a.out()


@ad("billboard_ad_rent_your_face")
def bb_rent_face():
    a = Art("billboard", (245, 245, 245))
    # a face outline gridded like ad space
    profile(a, 140, 90, 640, (230, 230, 230))
    pts = chaikin(profile(Art((1600, 800)), 140, 90, 640, (0, 0, 0)), 2)
    a.line(pts + [pts[0]], INK, 6)
    for k in range(1, 6):
        a.line([(140 + k * 85, 90), (140 + k * 85, 730)], (255, 40, 120, 120), 3)
        a.line([(140, 90 + k * 110), (650, 90 + k * 110)], (255, 40, 120, 120), 3)
    a.text((440, 330), "AD", 60, (255, 40, 120, 255), BLACK)
    a.text((1130, 160), "RENT YOUR", 120, INK, BLACK)
    a.text((1130, 290), "FACE.", 170, (255, 40, 120, 255), BLACK)
    a.text((1130, 430), "Wear a brand on your cheek. ¥80/hour.", 50, INK, BAHN)
    a.text((1130, 510), "顔、貸してください。", 60, INK)
    a.text((1130, 640), "Smile bonus +¥5 · frowning voids payment", 38, (120, 120, 120, 255), ARIAL_B)
    a.text((1550, 760), "FACESPACE · a Hoshikawa Media partner", 26, (255, 40, 120, 255), BAHN, anchor="rb")
    return a.out()


@ad("billboard_ad_breathe_plus")
def bb_breathe():
    a = Art("billboard")
    a.vgrad((0, 0, 1600, 800), (190, 235, 245), (90, 170, 200))
    for k in range(30):
        rnd = random.Random(k + 70)
        x, y, r = rnd.uniform(0, 700), rnd.uniform(0, 800), rnd.uniform(10, 50)
        a.circle(x, y, r, outline=(255, 255, 255, 140), width=3)
    # a mask with a meter
    a.ell((180, 220, 560, 600), fill=(250, 252, 255, 255))
    a.ell((250, 330, 340, 420), fill=(60, 90, 110, 255))
    a.ell((400, 330, 490, 420), fill=(60, 90, 110, 255))
    a.rect((280, 470, 460, 520), fill=(40, 200, 140, 255), r=20)
    a.text((370, 495), "98%", 34, W_, BAHN)
    a.text((1120, 160), "BREATHE+", 160, (20, 60, 80, 255), BAHN)
    a.text((1120, 300), "Clean air, by subscription.", 60, (20, 60, 80, 255), SERIF_I)
    a.rows((760, 380, 1480, 640), [("BASIC  ¥300/day  ·  92% filtered", (20, 60, 80, 255), 1),
                                   ("PLUS  ¥900/day  ·  99% filtered", (20, 60, 80, 255), 1),
                                   ("Missed payment? Filters throttle gently.", (200, 40, 60, 255), 1)])
    a.text((1120, 720), "空気は無料ではありません。", 40, (20, 60, 80, 255))
    return a.out()


@ad("billboard_ad_star_gacha")
def bb_gacha():
    a = Art("billboard")
    a.hgrad((0, 0, 1600, 800), (255, 80, 180), (120, 60, 255))
    for k in range(26):
        rnd = random.Random(k + 300)
        a.poly(star_pts(rnd.uniform(0, 1600), rnd.uniform(0, 800), rnd.uniform(10, 40)), fill=(255, 255, 255, rnd.randint(60, 200)))
    a.circle(380, 400, 280, fill=(255, 255, 255, 255))
    a.poly(star_pts(380, 400, 230), fill=(255, 210, 40, 255))
    a.text((380, 410), "SSR", 110, (255, 60, 140, 255), BLACK)
    a.text((1100, 140), "★★★★★", 90, (255, 230, 60, 255))
    a.text((1100, 260), "STAR GACHA", 150, W_, BLACK, stroke=8, stroke_fill=(120, 20, 120, 255))
    a.text((1100, 400), "PULL NOW! 10 PULLS = 1 SSR GUARANTEED*", 48, W_, IMPACT)
    a.text((1100, 490), "今だけ！ 限定キャラ排出率UP!!", 54, (255, 240, 120, 255))
    a.text((1100, 600), "pay with credit, score, or a night of Dreamlink", 40, W_, BAHN)
    a.text((1100, 720), "*SSR rate 0.003%. guarantee applies to the 10,000th pull.", 26, (255, 230, 250, 255), ARIAL_B)
    return a.out()


@ad("billboard_ad_capsule_estate")
def bb_capsule():
    a = Art("billboard", (250, 248, 240))
    # a wall of capsules with one highlighted sliver
    for i in range(6):
        for j in range(4):
            x, y = 80 + i * 110, 120 + j * 150
            a.rect((x, y, x + 100, y + 130), fill=(225, 222, 212, 255), outline=(150, 145, 135, 255), width=3, r=12)
            a.ell((x + 20, y + 30, x + 80, y + 100), fill=(60, 60, 70, 255))
    a.rect((80 + 2 * 110, 120 + 1 * 150, 80 + 2 * 110 + 6, 120 + 1 * 150 + 130), fill=(230, 30, 60, 255))
    a.line([(306, 335), (420, 420)], (230, 30, 60, 255), 4)
    a.text((430, 440), "← yours", 40, (230, 30, 60, 255), SERIF_I, anchor="lm")
    a.text((1160, 170), "OWN 0.01%", 140, (230, 30, 60, 255), BAHN)
    a.text((1160, 300), "OF A CAPSULE!", 110, INK, BAHN)
    a.text((1160, 420), "Property is freedom. Now in micro-shares.", 46, (60, 60, 60, 255), SERIF_I)
    a.text((1160, 510), "夢のマイカプセル、0.01%から。", 50, INK)
    a.text((1160, 630), "¥12,000 deposit · sleeping rights 8 min/night", 40, (60, 60, 60, 255), BAHN)
    a.text((1550, 760), "HOSHIKAWA REALTY", 30, (230, 30, 60, 255), BAHN, anchor="rb")
    return a.out()


@ad("billboard_ad_sale_overload")
def bb_sale():
    a = Art("billboard", (255, 230, 0))
    rnd = random.Random(12)
    words = ["SALE", "LIMITED", "NOW", "セール", "限定", "今すぐ", "-90%", "LAST DAY", "FINAL", "BUY", "半額", "NEW"]
    cols = [(230, 20, 40), (20, 20, 20), (255, 255, 255), (0, 120, 255), (255, 0, 140)]
    for k in range(70):
        w = rnd.choice(words)
        c = rnd.choice(cols)
        a.text((rnd.uniform(0, 1600), rnd.uniform(0, 800)), w, rnd.uniform(40, 150), rgba(c), IMPACT if w.isascii() else JP_BOLD)
    a.poly(star_pts(800, 400, 380, 18, 0.78, -90), fill=(230, 20, 40, 255))
    a.text((800, 330), "SALE", 220, W_, IMPACT)
    a.text((800, 500), "EVERYTHING MUST GO · INCLUDING YOU", 40, W_, IMPACT)
    return glitch(a.out(), 3, 6, 0.02, 4)


@ad("billboard_ad_organsure")
def bb_organsure():
    a = Art("billboard", (236, 244, 246))
    a.rect((0, 0, 560, 800), fill=(20, 120, 130, 255))
    # kidney beans icons
    for k, (x, y) in enumerate(((170, 280), (390, 280))):
        a.ell((x - 90, y - 140, x + 90, y + 140), fill=(240, 120, 120, 255))
        a.ell((x - 10 if k == 0 else x - 120, y - 40, x + 120 if k == 0 else x + 10, y + 40), fill=(20, 120, 130, 255))
    a.text((280, 560), "ORGANSURE", 70, W_, BAHN)
    a.text((280, 640), "臓器保険", 60, W_)
    a.text((1080, 170), "Your kidneys are worth", 64, (20, 60, 70, 255), SERIF_I)
    a.text((1080, 280), "MORE THAN YOU.", 110, (20, 120, 130, 255), BLACK)
    a.text((1080, 420), "Insure them today. ¥1,200/month.", 54, (20, 60, 70, 255), BAHN)
    a.text((1080, 520), "Payout to the policy holder or the highest bidder.", 38, (80, 100, 110, 255), ARIAL_B)
    a.text((1080, 680), "Underwritten by NOCTIS BIOLOGICS", 32, (20, 120, 130, 255), BAHN)
    return a.out()


@ad("billboard_ad_attention_market")
def bb_attention():
    a = Art("billboard", (10, 10, 14))
    for k in range(20):
        a.circle(400, 400, 20 + k * 22, outline=(0, 255, 200, 140 - k * 6), width=3)
    eye(a, 400, 400, 200, (0, 255, 200), 14)
    a.text((1100, 160), "SELL YOUR", 100, W_, BAHN)
    a.text((1100, 280), "ATTENTION", 140, (0, 255, 200, 255), BAHN)
    a.text((1100, 400), "BY THE HOUR.", 100, W_, BAHN)
    a.text((1100, 520), "Wear the band. Watch the ads. ¥12/hour.", 46, (200, 255, 240, 255), BAHN)
    a.text((1100, 600), "あなたの視線、買い取ります。", 48, (0, 255, 200, 255))
    a.text((1100, 720), "Blinking is deducted. Looking away is theft.", 32, (140, 150, 150, 255), ARIAL_B)
    return a.out()


# ==================================================================== billboards 2:1 (red-light district)

@ad("billboard_ad_velvet_moon")
def bb_velvet():
    a = Art("billboard")
    a.vgrad((0, 0, 1600, 800), (30, 0, 26), (80, 0, 50))
    a.bokeh(14, 50, [(255, 60, 160), (255, 150, 60), (190, 60, 255)], 6, 30, alpha=(30, 110))
    crescent(a, 1340, 230, 150, (255, 210, 230), (45, 0, 35))
    neon_heart(a, 360, 400, 230, (255, 40, 140), 12, 16, 2)
    a.neon_text((360, 390), "♥", 140, (255, 120, 200))
    a.neon_text((960, 200), "HOTEL", 90, (255, 180, 220), BAHN, radius=8)
    a.neon_text((960, 340), "Velvet Moon", 150, (255, 60, 160), SCRIPT_B, radius=12)
    a.rect((680, 450, 1250, 452), fill=(255, 150, 200, 255))
    a.text((960, 510), "REST ¥3,800 / 2h   ·   STAY ¥8,800", 46, W_, BAHN)
    a.text((960, 590), "ご休憩 ¥3,800〜  ご宿泊 ¥8,800〜", 48, (255, 190, 220, 255))
    a.text((960, 680), "Discreet entrance · no cameras* · themed rooms", 34, (230, 170, 210, 255), ARIAL_B)
    a.text((1560, 770), "*MERIDIAN sees everything. we just don't.", 22, (190, 130, 170, 255), ARIAL_B, anchor="rb")
    return a.out()


@ad("billboard_ad_dolls_kisaragi")
def bb_dolls():
    a = Art("billboard")
    a.hgrad((0, 0, 1600, 800), (240, 236, 240), (205, 200, 215))
    a.radial(380, 420, 380, (255, 255, 255, 255), (230, 228, 236, 0))
    P = profile(a, 130, 120, 600, (245, 240, 242))
    pts = chaikin(P, 2)
    a.line(pts + [pts[0]], (120, 110, 130, 255), 4)
    # android seams and a glowing eye
    a.line([(330, 190), (410, 250), (420, 330)], (150, 140, 160, 255), 3)
    a.line([(250, 420), (380, 470), (420, 520)], (150, 140, 160, 255), 3)
    a.glow(lambda o: o.circle(525, 340, 10, fill=(80, 200, 255, 255)), 8, 2)
    barcode(a, 300, 620, 120, 40, 7, (120, 110, 130, 255))
    a.text((1110, 160), "DOLLS", 160, (60, 50, 70, 255), SERIF, spacing=20)
    a.text((1110, 260), "by KISARAGI", 60, (160, 80, 120, 255), SERIF_I)
    a.text((1110, 400), "She remembers your name.", 64, (60, 50, 70, 255), SERIF_I)
    a.text((1110, 480), "She never remembers anything else.", 42, (110, 100, 120, 255), SERIF_I)
    a.text((1110, 590), "Companion rental · by the hour, the night, the year", 36, (60, 50, 70, 255), BAHN)
    a.text((1110, 660), "如月ドールズ · 彼女はあなたの名前を覚えています", 34, (160, 80, 120, 255))
    a.text((1560, 770), "Adult companions only. Licensed under MERIDIAN Synthetic Persons Act.", 20, (130, 120, 140, 255), ARIAL_B, anchor="rb")
    return a.out()


@ad("billboard_ad_cabaret_luna")
def bb_cabaret():
    a = Art("billboard")
    a.vgrad((0, 0, 1600, 800), (60, 0, 10), (20, 0, 4))
    # curtains and a spotlight
    for x0, sgn in ((0, 1), (1600, -1)):
        for k in range(8):
            xx = x0 + sgn * k * 40
            a.poly([(xx, 0), (xx + sgn * 40, 0), (xx + sgn * (40 + k * 10), 800), (xx + sgn * k * 10, 800)], fill=(150 - k * 8, 0, 20, 255))
    a.poly([(560, 0), (680, 0), (900, 800), (300, 800)], fill=(255, 240, 200, 40))
    legs_pair(a, 610, 250, 520, (10, 0, 4), seam=(90, 30, 40), hem_col=(150, 0, 30), heel_col=(220, 20, 40), crossed=True)
    a.text((1120, 150), "CABARET", 120, (255, 220, 160, 255), SERIF, spacing=10)
    a.neon_text((1120, 290), "LUNA", 180, (255, 200, 120), SERIF, radius=10)
    a.text((1120, 440), "Burlesque · Jazz · Champagne", 52, W_, SERIF_I)
    a.text((1120, 520), "キャバレー・ルナ  夜ごと三回公演", 48, (255, 210, 160, 255))
    a.text((1120, 640), "SHOWS 20:00 · 22:00 · 00:00 · 20+ ONLY", 40, (255, 220, 160, 255), BAHN)
    return a.out()


@ad("billboard_ad_noir_satin")
def bb_noir():
    a = Art("billboard", (12, 10, 12))
    a.radial(420, 420, 420, (70, 20, 40, 255), (12, 10, 12, 0))
    P = dress_form(a, 420, 130, 600, (200, 170, 160), (30, 26, 28))
    corset(a, P, (20, 6, 14), (220, 60, 110))
    a.text((1120, 200), "NOIR SATIN", 140, (240, 230, 235, 255), SERIF, spacing=10)
    a.text((1120, 320), "lingerie for after hours", 56, (220, 60, 110, 255), SERIF_I)
    a.text((1120, 460), "Feel expensive. Pay monthly.", 54, (240, 230, 235, 255), SERIF_I)
    a.text((1120, 560), "ノワール・サテン  大人のランジェリー", 46, (220, 150, 180, 255))
    a.text((1120, 690), "NEW COLLECTION · HOSHIKAWA DORI 3F", 36, (200, 190, 195, 255), BAHN, spacing=4)
    return a.out()


@ad("billboard_ad_matcha_dating")
def bb_matcha():
    a = Art("billboard", (250, 250, 247))
    a.rect((0, 0, 1600, 800), fill=(240, 252, 240, 255))
    # two phone cards with scores
    for i, (sc, col, ok) in enumerate(((812, (70, 180, 90), True), (431, (220, 40, 60), False))):
        x = 120 + i * 330
        a.rect((x, 120, x + 290, 640), fill=(255, 255, 255, 255), outline=(200, 210, 200, 255), width=3, r=26)
        a.rect((x + 20, 140, x + 270, 420), fill=(220, 225, 222, 255), r=18)
        a.ell((x + 95, 180, x + 195, 290), fill=(160, 170, 165, 255))
        a.ell((x + 50, 280, x + 240, 460), fill=(160, 170, 165, 255))
        a.rect((x + 20, 420, x + 270, 440), fill=(255, 255, 255, 255))
        a.text((x + 145, 500), f"{sc}", 80, rgba(col), MONO)
        a.text((x + 145, 580), "♥ MATCH" if ok else "✕ BELOW YOU", 36, rgba(col))
    a.text((1150, 160), "MATCHA", 150, (70, 160, 90, 255), BLACK)
    a.text((1150, 280), "love, rated.", 70, (40, 60, 45, 255), SERIF_I)
    a.text((1150, 420), "Only see people your score can afford.", 46, (40, 60, 45, 255), BAHN)
    a.text((1150, 500), "スコアで選ぶ、運命の人。", 52, (70, 160, 90, 255))
    a.text((1150, 640), "Compatibility powered by MERIDIAN · 18+", 34, (90, 110, 95, 255), ARIAL_B)
    return a.out()


@ad("billboard_ad_platinum_defaced")
def bb_platinum_defaced():
    img = bb_platinum()
    img = strike(img, 5, (240, 20, 40, 255), 2, 0.025)
    return spray(img, "WHO OWNS YOU?", 21, (255, 240, 0, 255), (255, 80, 0, 255), at=(0.55, 0.62), width=0.8, rot=4, f=IMPACT)


@ad("billboard_ad_velvet_defaced")
def bb_velvet_defaced():
    img = bb_velvet()
    return spray(img, "BODIES NOT PRODUCTS", 33, (240, 240, 240, 255), (0, 240, 255, 255), at=(0.5, 0.75), width=0.92, rot=-3, f=IMPACT)


# ==================================================================== main


def contact_sheet(path, names=None, cols=10, cell=220):
    names = names or sorted(R)
    imgs = []
    for n in names:
        p = os.path.join(OUT, n + ".png")
        imgs.append((n, Image.open(p).convert("RGBA") if os.path.exists(p) else R[n]()))
    rows = (len(imgs) + cols - 1) // cols
    lab = 26
    sheet = Image.new("RGB", (cols * cell, rows * (cell + lab)), (34, 34, 38))
    d = ImageDraw.Draw(sheet)
    from make_decals import font as _f
    fo = _f(ARIAL_B, 12)
    for i, (n, im) in enumerate(imgs):
        x, y = (i % cols) * cell, (i // cols) * (cell + lab)
        # checker behind transparent designs
        bg = Image.new("RGBA", (cell - 8, cell - 8), (70, 70, 76, 255))
        im.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
        bg.alpha_composite(im, ((cell - 8 - im.width) // 2, (cell - 8 - im.height) // 2))
        sheet.paste(bg.convert("RGB"), (x + 4, y + 4))
        d.text((x + cell / 2, y + cell + lab / 2 - 2), n.replace("billboard_ad_", "bb_").replace("poster_ad_", "p_"), font=fo, fill=(220, 220, 225), anchor="mm")
    sheet.save(path)
    print("sheet", path, sheet.size, len(imgs), "designs")


def main(argv):
    if "--sheet" in argv:
        i = argv.index("--sheet")
        contact_sheet(argv[i + 1], [a for a in argv[:i] + argv[i + 2:]] or None)
        return
    os.makedirs(OUT, exist_ok=True)
    only = set(argv)
    for name, make in R.items():
        if only and name not in only and not any(name.startswith(o.rstrip("*")) for o in only if o.endswith("*")):
            continue
        img = make()
        img.save(os.path.join(OUT, name + ".png"), optimize=True)
        print(name, img.size)
    print(len(R), "designs")


if __name__ == "__main__":
    main(sys.argv[1:])
