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


# ==================================================================== posters 0.7 (street level)

@ad("poster_ad_club_sapphire")
def p_sapphire():
    a = Art("poster")
    a.vgrad((0, 0, 700, 1000), (6, 14, 50), (2, 4, 16))
    a.bokeh(21, 30, [(80, 140, 255), (160, 200, 255), (255, 255, 255)], 6, 30, (0, 0, 700, 600), alpha=(30, 110))
    a.radial(350, 420, 300, (60, 110, 255, 200), (6, 14, 50, 0))
    woman_gown(a, 0, 140, 680, (4, 6, 20), glass_col=(200, 220, 255))
    a.neon_text((350, 90), "CLUB SAPPHIRE", 64, (110, 170, 255), SERIF, radius=8)
    a.text((350, 845), "Hostesses who listen. Champagne that doesn't.", 22, (200, 215, 255, 255), SERIF_I)
    a.text((350, 895), "クラブ・サファイア  ·  ご指名承ります", 28, (150, 190, 255, 255))
    a.text((350, 950), "SET ¥12,000 / 60min · B1F · 20+", 26, W_, BAHN)
    return a.out()


@ad("poster_ad_host_zero")
def p_host():
    a = Art("poster", (10, 10, 12))
    a.radial(350, 380, 340, (220, 180, 90, 230), (10, 10, 12, 0))
    for k in range(16):
        a.line([(350, 380), (350 + 600 * math.cos(k * math.pi / 8), 380 + 600 * math.sin(k * math.pi / 8))], (240, 200, 110, 40), 14)
    man_suit(a, 0, 130, 700, (12, 10, 10), tie_col=(220, 180, 90))
    a.text((350, 70), "HOST CLUB", 44, GOLD, SERIF, spacing=8)
    a.text((350, 140), "ZERO", 90, W_, BLACK, stroke=3, stroke_fill=GOLD)
    a.rect((80, 840, 620, 990), fill=(14, 12, 10, 230))
    a.text((350, 870), "No.1  REI  ·  今月売上 ¥38,000,000", 26, GOLD)
    a.text((350, 915), "He'll tell you you're the only one.", 24, W_, SERIF_I)
    a.text((350, 960), "初回 ¥3,000 · 20歳以上", 26, (230, 220, 200, 255))
    return a.out()


@ad("poster_ad_velvet_moon_rates")
def p_velvet():
    a = Art("poster")
    a.vgrad((0, 0, 700, 1000), (60, 0, 50), (20, 0, 20))
    neon_heart(a, 350, 260, 190, (255, 50, 150), 10, 14)
    crescent(a, 350, 250, 70, (255, 220, 235), (55, 0, 45), 0.4)
    a.neon_text((350, 520), "Velvet Moon", 92, (255, 90, 180), SCRIPT_B, radius=9)
    a.text((350, 600), "HOTEL  ·  ホテル ベルベットムーン", 26, (255, 200, 230, 255))
    rows = [("ご休憩 REST", "2h  ¥3,800"), ("ご宿泊 STAY", "¥8,800"), ("フリータイム", "¥5,500"), ("THEME ROOMS", "+¥2,000")]
    for i, (k, v) in enumerate(rows):
        y = 670 + i * 62
        a.text((90, y), k, 30, W_, anchor="lm")
        a.text((610, y), v, 32, (255, 150, 210, 255), BAHN, anchor="rm")
        a.line([(90, y + 28), (610, y + 28)], (255, 120, 190, 80), 2)
    a.text((350, 960), "→ 50m · discreet entrance · 空室あり", 24, (255, 200, 230, 255))
    return a.out()


@ad("poster_ad_peep_show")
def p_peep():
    a = Art("poster", (8, 4, 6))
    a.radial(350, 420, 320, (255, 30, 80, 200), (8, 4, 6, 0))
    keyhole(a, 350, 330, 120, (8, 4, 6, 255))
    a.glow(lambda o: o.circle(350, 330, 130, outline=(255, 40, 100, 255), width=8), 14, 2)
    a.neon_text((350, 100), "PEEP", 130, (255, 40, 100), IMPACT, radius=12)
    a.neon_text((350, 700), "SHOW", 130, (255, 210, 40), IMPACT, radius=12)
    a.text((350, 820), "覗き部屋  ·  ¥100 / MINUTE", 40, W_)
    a.text((350, 880), "You look. Nobody touches. Everybody pays.", 24, (255, 170, 190, 255), SERIF_I)
    a.text((350, 940), "LIVE ON STAGE · 20+ · ALL PERFORMERS ARE ADULTS", 20, (200, 160, 170, 255), ARIAL_B)
    return glitch(a.out(), 9, 6, 0.015, 3)


@ad("poster_ad_noir_satin_legs")
def p_noir_legs():
    a = Art("poster", (232, 222, 214))
    a.rect((0, 0, 700, 1000), outline=(20, 10, 14, 255), width=20)
    legs_pair(a, 330, 260, 620, (16, 8, 12), seam=(90, 60, 70), hem_col=(16, 8, 12), heel_col=(190, 10, 50))
    a.text((350, 90), "NOIR SATIN", 70, (16, 8, 12, 255), SERIF, spacing=8)
    a.text((350, 160), "stockings · lingerie · after dark", 26, (160, 20, 60, 255), SERIF_I)
    a.text((350, 950), "大人のランジェリー  NEW SEASON", 26, (16, 8, 12, 255))
    return a.out()


@ad("poster_ad_rouge9_lips")
def p_rouge():
    a = Art("poster", (16, 4, 8))
    a.radial(350, 450, 380, (120, 0, 30, 255), (16, 4, 8, 0))
    lips(a, 350, 440, 520, (225, 10, 50), open_=0.15)
    a.text((350, 120), "ROUGE N°9", 96, W_, SERIF, spacing=6)
    a.text((350, 720), "KISS SOMEONE YOU CAN'T AFFORD.", 30, (255, 120, 150, 255), BAHN, spacing=2)
    a.text((350, 800), "ルージュ9 · 落ちない口紅", 34, W_)
    a.text((350, 930), "¥9.99 · 9 shades of want", 30, (255, 160, 180, 255), SERIF_I)
    return a.out()


@ad("poster_ad_dolls_kisaragi")
def p_dolls():
    a = Art("poster", (238, 234, 238))
    P = profile(a, 90, 160, 620, (248, 244, 246), flip=True)
    pts = chaikin(P, 2)
    a.line(pts + [pts[0]], (120, 110, 130, 255), 4)
    a.line([(340, 250), (260, 320), (250, 420)], (150, 140, 160, 255), 3)
    a.line([(260, 520), (330, 600)], (150, 140, 160, 255), 3)
    a.glow(lambda o: o.circle(200, 380, 9, fill=(80, 200, 255, 255)), 8, 2)
    a.text((350, 70), "DOLLS", 90, (60, 50, 70, 255), SERIF, spacing=16)
    a.text((350, 135), "by KISARAGI  ·  如月ドールズ", 26, (160, 80, 120, 255), SERIF_I)
    a.text((350, 850), "She remembers your name.", 36, (60, 50, 70, 255), SERIF_I)
    a.text((350, 910), "companion rental · hour · night · year", 24, (110, 100, 120, 255), BAHN)
    a.text((350, 960), "adult synthetic companions only", 18, (130, 120, 140, 255), ARIAL_B)
    return a.out()


@ad("poster_ad_rose_theatre")
def p_rose():
    a = Art("poster", (240, 220, 180))
    for k in range(24):
        t0, t1 = math.radians(k * 15), math.radians(k * 15 + 7.5)
        a.poly([(350, 520), (350 + 900 * math.cos(t0), 520 + 900 * math.sin(t0)), (350 + 900 * math.cos(t1), 520 + 900 * math.sin(t1))],
               fill=(220, 60, 50, 255) if k % 2 else (240, 200, 120, 255))
    a.circle(350, 520, 230, fill=(250, 235, 200, 255))
    # fan dancer: a gown silhouette behind two feather fans
    for cx in (220, 480):
        for k in range(9):
            t = math.radians(-170 + k * 20)
            a.line([(cx, 480), (cx + 130 * math.cos(t), 480 + 130 * math.sin(t))], (240, 120, 160, 255), 24)
    woman_gown(a, 120, 330, 460, (40, 10, 20), glass=False)
    a.rect((0, 0, 700, 150), fill=(40, 10, 20, 255))
    a.text((350, 60), "ROSE THEATRE", 66, (250, 220, 150, 255), SERIF, spacing=6)
    a.text((350, 120), "薔薇座  ·  バーレスク・レビュー", 30, (250, 200, 160, 255))
    a.rect((0, 820, 700, 1000), fill=(40, 10, 20, 255))
    a.text((350, 870), "THE FAN DANCE OF MISS YURI", 34, (250, 220, 150, 255), SERIF)
    a.text((350, 930), "3 SHOWS NIGHTLY · 大人のための夜", 26, (250, 200, 160, 255))
    return showa(a.out(), 31)


@ad("poster_ad_cabaret_hanabi")
def p_hanabi():
    a = Art("poster", (20, 24, 60))
    for (cx, cy, r, c) in ((180, 220, 150, (255, 120, 60)), (520, 160, 120, (255, 220, 80)), (480, 420, 170, (255, 80, 160))):
        for k in range(36):
            t = math.radians(k * 10)
            a.line([(cx + r * 0.2 * math.cos(t), cy + r * 0.2 * math.sin(t)), (cx + r * math.cos(t), cy + r * math.sin(t))], rgba(c), 5)
            a.circle(cx + r * math.cos(t), cy + r * math.sin(t), 6, fill=rgba(c))
    a.text((350, 620), "キャバレー", 80, (255, 230, 120, 255), MINCHO)
    a.text((350, 730), "花火", 150, (255, 90, 120, 255), MINCHO, stroke=4, stroke_fill=(255, 240, 200, 255))
    a.text((350, 850), "CABARET HANABI · SINCE 1968", 30, (255, 230, 160, 255), SERIF)
    a.text((350, 920), "ホステス大募集 · 明朗会計 · 20歳以上", 28, W_)
    return showa(a.out(), 41, (240, 220, 180), 0.18)


@ad("poster_ad_pachinko_galaxy")
def p_pachinko():
    a = Art("poster")
    a.vgrad((0, 0, 700, 1000), (20, 0, 60), (200, 0, 120))
    rnd = random.Random(3)
    for _ in range(60):
        a.circle(rnd.uniform(0, 700), rnd.uniform(0, 1000), rnd.uniform(6, 16), fill=(220, 220, 230, 255), outline=(255, 255, 255, 255), width=2)
    a.poly(star_pts(350, 330, 240, 12, 0.6), fill=(255, 230, 0, 255))
    a.text((350, 330), "777", 130, (230, 0, 60, 255), IMPACT)
    a.text((350, 640), "パチンコ", 110, W_, JP_BOLD, stroke=6, stroke_fill=(230, 0, 60, 255))
    a.text((350, 760), "GALAXY", 110, (255, 230, 0, 255), IMPACT)
    a.text((350, 880), "新台入替 · BIG WIN · 朝10時OPEN", 36, W_)
    a.text((350, 950), "your rent is in there somewhere", 24, (255, 200, 240, 255), SERIF_I)
    return a.out()


@ad("poster_ad_meridian_lotto")
def p_lotto():
    a = Art("poster", MER_BG)
    for i in range(6):
        cx, cy = 130 + (i % 3) * 220, 300 + (i // 3) * 220
        a.circle(cx, cy, 90, fill=(240, 250, 255, 255))
        a.text((cx, cy), str([7, 13, 21, 42, 55, 88][i]), 70, (8, 22, 40, 255), MONO)
    a.text((350, 100), "MERIDIAN LOTTO", 70, CYAN, BAHN)
    a.text((350, 170), "WIN +500 SCORE", 60, W_, BAHN)
    a.text((350, 760), "Every ticket raises your score*", 34, W_, SERIF_I)
    a.text((350, 830), "スコアくじ  1枚 ¥500", 44, CYAN)
    a.text((350, 940), "*by 0.1 point. losing tickets are reported as risk behaviour.", 18, (140, 170, 200, 255), ARIAL_B)
    return a.out()


@ad("poster_ad_hoshicoin")
def p_coin():
    a = Art("poster", (6, 10, 6))
    rnd = random.Random(2)
    for _ in range(300):
        a.text((rnd.uniform(0, 700), rnd.uniform(0, 1000)), rnd.choice("01¥$"), 24, (0, 255, 90, rnd.randint(40, 140)), MONO)
    a.circle(350, 330, 220, fill=(240, 190, 40, 255))
    a.circle(350, 330, 185, outline=(180, 130, 20, 255), width=10)
    a.text((350, 330), "星", 200, (180, 110, 10, 255), MINCHO)
    a.text((350, 620), "HOSHICOIN", 90, (0, 255, 90, 255), IMPACT)
    a.text((350, 720), "+10,000% GUARANTEED", 52, W_, IMPACT)
    a.text((350, 800), "絶対に儲かる！ 今すぐ参加", 40, (0, 255, 90, 255))
    a.text((350, 900), "invite 3 friends · unlock withdrawals*", 28, W_, BAHN)
    a.text((350, 950), "*withdrawals coming soon", 20, (120, 160, 120, 255), ARIAL_B)
    return glitch(a.out(), 15, 10, 0.02, 3)


@ad("poster_ad_volt_rush")
def p_volt():
    a = Art("poster", (12, 12, 12))
    a.poly([(420, 30), (170, 520), (330, 520), (220, 980), (560, 400), (390, 400), (520, 30)], fill=(255, 225, 0, 255))
    can(a, 230, 260, 240, 520, (24, 24, 24), (255, 220, 0), "VOLT RUSH", INK)
    a.text((350, 80), "VOLT RUSH", 110, W_, IMPACT, stroke=5, stroke_fill=(12, 12, 12, 255))
    a.text((350, 860), "SLEEP IS FOR THE POOR.", 50, (255, 225, 0, 255), IMPACT, stroke=3, stroke_fill=INK)
    a.text((350, 940), "眠らない、稼ぐ。", 40, W_, stroke=3, stroke_fill=INK)
    return a.out()


@ad("poster_ad_ramen_retro")
def p_ramen():
    a = Art("poster", (250, 220, 120))
    a.rect((0, 0, 700, 1000), outline=(200, 20, 30, 255), width=24)
    a.circle(350, 420, 250, fill=(200, 20, 30, 255))
    bowl(a, 350, 450, 190, (255, 250, 240), (40, 40, 40), steam=(255, 255, 255, 200))
    a.text((350, 110), "ラーメン輝", 100, (200, 20, 30, 255), MINCHO)
    a.text((350, 760), "本物の牛の味™", 64, INK, MINCHO)
    a.text((350, 840), "REAL BEEF FLAVOUR™", 50, (200, 20, 30, 255), IMPACT)
    a.text((350, 910), "(no cow was involved)", 28, INK, SERIF_I)
    return showa(a.out(), 51)


@ad("poster_ad_aqua_pure")
def p_aqua():
    a = Art("poster")
    a.vgrad((0, 0, 700, 1000), (220, 245, 255), (60, 160, 220))
    a.poly(chaikin([(350, 140), (480, 380), (500, 480), (460, 580), (350, 630), (240, 580), (200, 480), (220, 380)], 3), fill=(255, 255, 255, 220))
    a.text((350, 480), "H2O", 90, (40, 130, 200, 255), BAHN)
    a.text((350, 720), "AQUA PURE", 90, (10, 60, 110, 255), BAHN)
    a.text((350, 800), "Clean water from ¥4.99/L", 40, (10, 60, 110, 255), SERIF_I)
    a.text((350, 870), "水道水はあなたの選択です。", 34, W_)
    a.text((350, 940), "Tap water is a choice. A bad one.", 26, W_, ARIAL_B)
    return a.out()


@ad("poster_ad_platinum_citizen")
def p_platinum():
    a = Art("poster")
    a.vgrad((0, 0, 700, 1000), (40, 44, 54), (12, 14, 18))
    a.rect((110, 180, 590, 480), fill=(214, 218, 226, 255), r=26)
    eye(a, 200, 270, 50, (40, 60, 90), 7)
    a.text((560, 430), "PLATINUM", 44, (40, 44, 56, 255), BAHN, anchor="rm", spacing=5)
    a.text((350, 90), "MERIDIAN", 56, CYAN, BAHN, spacing=10)
    a.text((350, 600), "UPGRADE TO", 50, (200, 204, 214, 255), BAHN)
    a.text((350, 680), "PLATINUM", 100, W_, BAHN, spacing=6)
    a.text((350, 770), "CITIZEN", 70, (200, 204, 214, 255), BAHN, spacing=6)
    a.text((350, 870), "Be the person doors open for.", 30, (160, 210, 255, 255), SERIF_I)
    a.text((350, 940), "プラチナ市民 · 月額 ¥88,000", 30, (200, 204, 214, 255))
    return a.out()


@ad("poster_ad_hoshikawa_limbs")
def p_limbs():
    a = Art("poster", (232, 234, 238))
    cyber_arm(a, 40, 220, 560, (60, 68, 82), (230, 30, 60))
    a.text((350, 100), "義体", 120, (230, 30, 60, 255), MINCHO)
    a.text((350, 640), "UPGRADE", 100, INK, BAHN)
    a.text((350, 740), "YOURSELF.", 100, (230, 30, 60, 255), BAHN)
    a.text((350, 850), "Kinetic limbs from ¥0 down", 34, INK, BAHN)
    a.text((350, 910), "repossession may occur at any time", 22, (110, 110, 120, 255), ARIAL_B)
    a.text((350, 960), "HOSHIKAWA DYNAMICS", 26, (230, 30, 60, 255), BAHN)
    return a.out()


@ad("poster_ad_dreamlink_intimate")
def p_intimate():
    a = Art("poster")
    a.vgrad((0, 0, 700, 1000), (40, 0, 30), (120, 10, 70))
    a.bokeh(41, 40, [(255, 80, 160), (255, 170, 210), (180, 60, 255)], 6, 36, alpha=(30, 110), blur=5)
    a.radial(350, 420, 300, (255, 120, 190, 200), (90, 10, 60, 0))
    profile(a, 40, 200, 420, (24, 0, 16))
    profile(a, 330, 200, 420, (24, 0, 16), flip=True)
    a.text((350, 90), "DREAMLINK", 46, (255, 190, 220, 255), BAHN, spacing=10)
    a.text((350, 760), "Intimate", 120, W_, SCRIPT_B)
    a.text((350, 860), "whoever you want, all night", 32, (255, 200, 225, 255), SERIF_I)
    a.text((350, 920), "夢の中なら、誰とでも。 R18", 32, (255, 160, 200, 255))
    return a.out()


@ad("poster_ad_matcha_dating")
def p_matcha():
    a = Art("poster", (240, 252, 240))
    a.rect((170, 160, 530, 640), fill=(255, 255, 255, 255), outline=(200, 210, 200, 255), width=3, r=28)
    a.rect((195, 185, 505, 470), fill=(220, 225, 222, 255), r=18)
    a.ell((300, 220, 400, 330), fill=(160, 170, 165, 255))
    a.ell((250, 320, 450, 500), fill=(160, 170, 165, 255))
    a.rect((195, 470, 505, 490), fill=(255, 255, 255, 255))
    a.text((350, 550), "♥ 97% · SCORE 812", 34, (70, 160, 90, 255))
    a.text((350, 90), "MATCHA", 100, (70, 160, 90, 255), BLACK)
    a.text((350, 740), "love, rated.", 60, (40, 60, 45, 255), SERIF_I)
    a.text((350, 830), "Only see people your score can afford.", 28, (40, 60, 45, 255), BAHN)
    a.text((350, 900), "スコアで選ぶ、運命の人。 18+", 34, (70, 160, 90, 255))
    return a.out()


@ad("poster_ad_noctis_sleep")
def p_noctis():
    a = Art("poster", (10, 8, 10))
    a.rect((24, 24, 676, 976), outline=(255, 190, 40, 255), width=4)
    crescent(a, 350, 330, 190, (255, 190, 40), (10, 8, 10))
    a.text((350, 640), "NOCTIS", 110, (255, 190, 40, 255), BLACK)
    a.text((350, 740), "SELL A NIGHT. KEEP THE DAY.", 36, W_, BAHN)
    a.text((350, 810), "一晩 ¥1,500 · 即日現金", 40, (255, 190, 40, 255))
    a.text((350, 900), "you weren't using it anyway", 26, (200, 200, 200, 255), SERIF_I)
    return a.out()


@ad("poster_ad_sale_now")
def p_sale():
    a = Art("poster", (230, 20, 40))
    rnd = random.Random(77)
    for k in range(40):
        w = rnd.choice(["SALE", "NOW", "限定", "LIMITED", "-80%", "今すぐ", "LAST"])
        a.text((rnd.uniform(0, 700), rnd.uniform(0, 1000)), w, rnd.uniform(30, 90), rgba(rnd.choice([(255, 230, 0), (255, 255, 255), (20, 20, 20)])),
               IMPACT if w.isascii() else JP_BOLD)
    a.rect((40, 330, 660, 690), fill=(255, 230, 0, 255))
    a.text((350, 460), "SALE", 210, (230, 20, 40, 255), IMPACT)
    a.text((350, 630), "LIMITED · NOW · 今だけ", 50, INK, IMPACT)
    return glitch(a.out(), 21, 14, 0.04, 8)


# ---------------------------------------------------------------- the street answers back

@ad("poster_ad_torn_layers")
def p_torn():
    """A Velvet Moon poster pasted over an old MERIDIAN one, half torn away."""
    img = rip_to(p_velvet(), p_platinum(), 4, 0.55)
    return torn(noise(img, 4, 18, 40), 4, "tb", 0.02)


@ad("poster_ad_torn_sale_hostess")
def p_torn2():
    img = rip_to(p_sale(), p_sapphire(), 9, 0.6, side="l")
    return torn(img, 9, "tr", 0.025)


@ad("poster_ad_missing_over_hostess")
def p_missing_over():
    """Someone pasted a MISSING flyer over the hostess-club poster."""
    img = paste_over(p_sapphire(), f_missing(), (0.55, 0.52), 0.62, rot=-4)
    return torn(img, 12, "b", 0.02)


@ad("poster_ad_who_owns_dolls")
def p_who_owns():
    img = strike(p_dolls(), 3, (230, 20, 30, 255), 2, 0.02)
    return spray(img, "WHO OWNS YOU?", 51, (230, 20, 30, 255), (40, 0, 0, 255), at=(0.5, 0.6), width=0.95, rot=-8, f=IMPACT)


@ad("poster_ad_unplug_over_platinum")
def p_unplug_over():
    img = p_platinum()
    d = ImageDraw.Draw(img)
    w, h = img.size
    cx, cy, r = w * 0.29, h * 0.23, w * 0.13
    d.line([cx - r, cy + r * 0.8, cx + r, cy - r * 0.8], fill=(255, 30, 60, 255), width=int(w * 0.03))
    return spray(img, "UNPLUG", 61, (0, 240, 255, 255), (130, 80, 255, 255), at=(0.5, 0.7), width=0.95, rot=10)


@ad("poster_ad_not_for_sale")
def p_bodies():
    return spray(p_noir_legs(), "NOT FOR SALE", 71, (255, 240, 0, 255), (255, 60, 0, 255), at=(0.5, 0.45), width=0.9, rot=-12, f=IMPACT)


# ==================================================================== flyers (photocopied, wheat-paste)

def flyer_base():
    return Art("flyer", (250, 250, 248))


@ad("flyer_money_today")
def f_money():
    a = flyer_base()
    a.text((300, 90), "MONEY", 130, INK, IMPACT)
    a.text((300, 210), "TODAY!", 130, INK, IMPACT)
    a.text((300, 320), "即日融資 · スコア不問", 50, INK)
    a.rect((40, 380, 560, 560), outline=INK, width=6)
    a.rows((60, 395, 540, 545), [("NO SCORE CHECK", INK, 1, IMPACT), ("NO QUESTIONS", INK, 1, IMPACT), ("NO WAY OUT", INK, 0.8, SERIF_I)])
    a.text((300, 640), "☎ " + phone(11), 52, INK, MONO)
    a.text((300, 720), "ask for Mr. Kaneda · ask nicely", 30, INK, SERIF_I)
    a.text((300, 800), "collateral: anything you can live without", 24, INK, ARIAL_B)
    return torn(photocopy(a.out(), 1), 1, "tblr", 0.015)


@ad("flyer_rent_face")
def f_face():
    a = flyer_base()
    profile(a, 140, 60, 380, (40, 40, 40))
    a.text((300, 520), "YOUR FACE = AD SPACE", 54, INK, IMPACT)
    a.text((300, 600), "顔広告モデル募集  時給¥80", 44, INK)
    a.text((300, 680), "walk the arcade 6h a day · smile", 30, INK, ARIAL_B)
    a.text((300, 770), "☎ " + phone(12), 48, INK, MONO)
    return torn(photocopy(a.out(), 2, threshold=110), 2, "tb", 0.02)


@ad("flyer_kidney_cash")
def f_kidney():
    a = flyer_base()
    a.text((300, 100), "WE BUY", 110, INK, IMPACT)
    a.text((300, 230), "KIDNEYS", 130, INK, IMPACT)
    a.text((300, 340), "腎臓 高価買取", 70, INK)
    a.rows((40, 400, 560, 640), [("CASH SAME DAY", INK, 1, IMPACT), ("clean clinic · 2 hours", INK, 1, ARIAL_B), ("you have two. why?", INK, 1, SERIF_I)])
    a.text((300, 740), "☎ " + phone(13), 50, INK, MONO)
    return torn(photocopy(a.out(), 3), 3, "tblr", 0.02, holes=1)


@ad("flyer_snack_bar")
def f_snack():
    a = Art("flyer", (255, 200, 220))
    a.text((300, 110), "スナック", 110, (150, 0, 60, 255), MINCHO)
    a.text((300, 270), "夜蝶", 170, (40, 0, 30, 255), MINCHO)
    a.text((300, 400), "SNACK YOCHO", 46, (150, 0, 60, 255), SERIF)
    gloved_arm(a, 80, 780, 190, 590, (40, 0, 30), glass_col=(150, 0, 60), width=24)
    a.text((390, 540), "ママが待ってます", 36, (40, 0, 30, 255))
    a.text((390, 610), "カラオケ1曲 ¥200", 32, (40, 0, 30, 255))
    a.text((390, 680), "2F · 20歳以上", 32, (40, 0, 30, 255))
    a.text((390, 760), "☎ " + phone(14), 30, (40, 0, 30, 255), MONO)
    return showa(torn(a.out(), 14, "tb", 0.015), 14)


@ad("flyer_unplug_meeting")
def f_meeting():
    a = flyer_base()
    eye(a, 300, 230, 170, (20, 20, 20), 18, crossed=True)
    a.text((300, 470), "WHO OWNS YOU?", 70, INK, STENCIL)
    a.text((300, 560), "your sleep · your face · your name", 30, INK, ARIAL_B)
    a.text((300, 640), "誰があなたを所有している？", 40, INK)
    a.text((300, 740), "THURSDAY · BEHIND THE NOODLE BAR · 03:00", 26, INK, MONO)
    a.text((300, 800), "come without your band", 26, INK, SERIF_I)
    return torn(photocopy(a.out(), 5, threshold=140), 5, "tblr", 0.02)


@ad("flyer_grand_open")
def f_grand():
    a = Art("flyer", (255, 240, 0))
    a.text((300, 100), "GRAND", 120, (230, 0, 40, 255), IMPACT)
    a.text((300, 230), "OPEN!!", 130, (230, 0, 40, 255), IMPACT)
    a.text((300, 360), "新装開店 パチンコ銀河", 52, INK)
    a.poly(star_pts(300, 560, 150, 16, 0.7), fill=(230, 0, 40, 255))
    a.text((300, 560), "777", 90, (255, 240, 0, 255), IMPACT)
    a.text((300, 780), "朝10時 · 先着100名様にティッシュ", 34, INK)
    return torn(a.out(), 6, "tb", 0.02)


@ad("flyer_missing_kei")
def f_missing():
    a = flyer_base()
    a.text((300, 80), "MISSING", 120, INK, IMPACT)
    a.text((300, 170), "行方不明 · 探しています", 44, INK)
    a.rect((170, 220, 430, 500), fill=(130, 130, 130, 255))
    a.ell((250, 250, 350, 360), fill=(60, 60, 60, 255))
    a.ell((200, 350, 400, 560), fill=(60, 60, 60, 255))
    a.rect((170, 500, 430, 560), fill=(250, 250, 248, 255))
    a.text((300, 580), "KEI ASANO · 24", 52, INK, BAHN)
    a.text((300, 650), "last seen: Club Sapphire, B1F", 32, INK, ARIAL_B)
    a.text((300, 700), "she signed a \"hostess contract\"", 30, INK, SERIF_I)
    a.text((300, 780), "☎ " + phone(17), 44, INK, MONO)
    return torn(photocopy(a.out(), 7, threshold=120), 7, "tblr", 0.015)


@ad("flyer_dream_bootleg")
def f_bootleg():
    a = Art("flyer", (20, 0, 30))
    neon_heart(a, 300, 260, 150, (255, 60, 180), 8, 10)
    a.text((300, 260), "夢", 120, W_)
    a.text((300, 480), "BOOTLEG DREAMS", 56, (255, 80, 200, 255), IMPACT)
    a.text((300, 560), "intimate files · no logs · adults only", 30, W_, ARIAL_B)
    a.text((300, 630), "Dreamlinkより安い · 履歴なし", 36, (255, 160, 220, 255))
    a.text((300, 720), "ask at the dumpling stall", 30, W_, SERIF_I)
    return torn(glitch(a.out(), 8, 8, 0.02, 4), 8, "tb", 0.02)


# ==================================================================== stickers and call cards

def call_card(name, jp, tagline, bg, fg, seed, motif):
    a = Art("sticker", bg)
    a.rect((14, 14, 486, 686), outline=rgba(fg), width=6, r=20)
    motif(a)
    a.text((250, 400), name, 64, rgba(fg), SCRIPT_B)
    a.text((250, 470), jp, 38, rgba(fg))
    a.text((250, 530), tagline, 24, rgba(fg), SERIF_I)
    a.text((250, 610), "☎ " + phone(seed), 40, rgba(fg), MONO)
    a.text((250, 660), "24H · 20歳以上 · 出張OK", 20, rgba(fg))
    return noise(a.out(), seed, 10, 50)


@ad("sticker_call_angel")
def s_angel():
    def m(a):
        for sgn in (-1, 1):
            for k in range(5):
                a.ell((250 + sgn * (40 + k * 26) - 30, 150 + k * 18, 250 + sgn * (40 + k * 26) + 30, 250 + k * 10), fill=(255, 255, 255, 220))
        a.circle(250, 170, 40, outline=(255, 220, 120, 255), width=8)
    return call_card("Angel", "エンジェル", "a little heaven, by the hour", (255, 120, 180), (255, 255, 255), 21, m)


@ad("sticker_call_velvet")
def s_velvet():
    return call_card("Velvet", "ベルベット", "she'll call you darling", (20, 0, 14), (255, 140, 190), 22, lambda a: lips(a, 250, 210, 260, (230, 20, 60)))


@ad("sticker_call_moon")
def s_moon():
    def m(a):
        crescent(a, 250, 200, 110, (255, 230, 140), (30, 20, 70))
        rnd = random.Random(5)
        for k in range(8):
            a.poly(star_pts(rnd.uniform(40, 460), rnd.uniform(40, 320), 10), fill=(255, 230, 140, 255))
    return call_card("Moonlight", "ムーンライト", "companionship until dawn", (30, 20, 70), (255, 230, 140), 23, m)


@ad("sticker_call_stiletto")
def s_heels():
    return call_card("Stiletto", "スティレット", "dinner, dancing, discretion", (250, 240, 235), (200, 0, 40), 24,
                     lambda a: stiletto(a, 110, 90, 280, (200, 0, 40), sole=(20, 0, 0)))


@ad("sticker_score_qr")
def s_qr():
    a = Art("sticker", (255, 230, 0))
    a.text((250, 90), "FREE", 100, INK, IMPACT)
    a.text((250, 190), "SCORE +50", 70, (230, 0, 40, 255), IMPACT)
    qr(a, 110, 250, 280, 5)
    a.text((250, 600), "スキャンでスコアUP!", 38, INK)
    a.text((250, 660), "(it is not MERIDIAN)", 22, INK, SERIF_I)
    return a.out()


@ad("sticker_rate_street")
def s_rate():
    a = Art("sticker", MER_BG)
    eye(a, 250, 160, 120, CYAN, 12)
    a.text((250, 330), "RATE THIS STREET", 48, W_, BAHN)
    for k in range(5):
        a.poly(star_pts(90 + k * 80, 430, 34), fill=CYAN)
    a.text((250, 540), "あなたの評価が街を良くします", 26, CYAN)
    a.text((250, 620), "unrated streets lose lighting", 24, (150, 190, 220, 255), ARIAL_B)
    return a.out()


@ad("sticker_who_owns")
def s_who():
    a = Art("sticker", (240, 240, 230))
    eye(a, 250, 240, 180, (230, 20, 30), 22, crossed=True)
    a.text((250, 500), "WHO OWNS", 80, INK, STENCIL)
    a.text((250, 600), "YOU?", 90, (230, 20, 30, 255), STENCIL)
    return torn(noise(a.out(), 31, 30, 20), 31, "tblr", 0.03)


@ad("sticker_hotel_heart")
def s_heart():
    a = Art("sticker")
    heart(a, 250, 330, 240, fill=(255, 40, 140, 255))
    heart(a, 250, 330, 205, outline=(255, 255, 255, 255), width=6)
    a.text((250, 280), "HOTEL", 50, W_, BAHN)
    a.text((250, 350), "Velvet Moon", 56, W_, SCRIPT_B)
    a.text((250, 430), "REST ¥3,800 →", 32, W_, BAHN)
    return a.out()


# ==================================================================== bus-stop lightboxes (0.63)

def lightbox_from(poster, strip_bg, strip_fg, strip_txt):
    """A lightbox edition of a poster: the art over a lit brand strip."""
    a = Art("lightbox", strip_bg)
    art = poster()
    w = a.W * a.s
    art = art.resize((w, int(art.height * w / art.width)), Image.LANCZOS)
    a.img.alpha_composite(art, (0, 0))
    y0 = art.height / a.s
    a.rect((0, y0, a.W, a.H), fill=rgba(strip_bg))
    a.fit((30, y0 + 8, a.W - 30, a.H - 8), strip_txt, rgba(strip_fg), BAHN)
    return a.out()


@ad("lightbox_dolls")
def lb_dolls():
    return lightbox_from(p_dolls, (60, 50, 70), (240, 230, 240), "DOLLS by KISARAGI · 如月")


@ad("lightbox_velvet_moon")
def lb_velvet():
    return lightbox_from(p_velvet, (255, 40, 140), (255, 255, 255), "HOTEL VELVET MOON · 50m →")


@ad("lightbox_volt_rush")
def lb_volt():
    return lightbox_from(p_volt, (255, 225, 0), (12, 12, 12), "VOLT RUSH · 6 CANS ¥600")


@ad("lightbox_ramen_kira")
def lb_ramen():
    return lightbox_from(p_ramen, (200, 20, 30), (255, 240, 200), "RAMEN KIRA · 3 MIN · ¥90")


@ad("lightbox_platinum")
def lb_platinum():
    return lightbox_from(p_platinum, (110, 230, 255), (8, 22, 40), "MERIDIAN · UPGRADE TODAY")


@ad("lightbox_matcha")
def lb_matcha():
    return lightbox_from(p_matcha, (70, 160, 90), (255, 255, 255), "MATCHA · love, rated · 18+")


@ad("lightbox_intimate")
def lb_intimate():
    return lightbox_from(p_intimate, (255, 120, 190), (40, 0, 30), "DREAMLINK INTIMATE · R18")


@ad("lightbox_hayate")
def lb_hayate():
    a = Art("lightbox")
    a.vgrad((0, 0, 640, 1016), (10, 6, 30), (70, 10, 80))
    a.circle(320, 470, 170, fill=(255, 120, 60, 255))
    for k in range(6):
        a.rect((150, 470 + k * 26, 490, 470 + k * 26 + 8 + k * 2), fill=(70, 10, 80, 255))
    for k in range(10):
        a.line([(0, 640 + k * k * 4), (640, 640 + k * k * 4)], (255, 60, 200, 80), 2)
    coupe(a, 20, 700, 600, (150, 30, 200), (20, 10, 40), light=(220, 240, 255))
    a.text((320, 110), "KANZAKI", 90, W_, IMPACT, spacing=6)
    a.text((320, 210), "HAYATE RS", 80, (255, 150, 220, 255), IMPACT)
    a.text((320, 820), "疾風 · THE ROAD IS STILL YOURS", 34, W_)
    a.text((320, 900), "score 650+ to register", 28, (220, 200, 240, 255), SERIF_I)
    return a.out()


@ad("lightbox_breathe_plus")
def lb_breathe():
    a = Art("lightbox")
    a.vgrad((0, 0, 640, 1016), (200, 240, 250), (80, 160, 200))
    a.ell((140, 200, 500, 560), fill=(250, 252, 255, 255))
    a.ell((210, 310, 300, 400), fill=(60, 90, 110, 255))
    a.ell((340, 310, 430, 400), fill=(60, 90, 110, 255))
    a.rect((230, 440, 410, 490), fill=(40, 200, 140, 255), r=20)
    a.text((320, 465), "98%", 32, W_, BAHN)
    a.text((320, 110), "BREATHE+", 110, (20, 60, 80, 255), BAHN)
    a.text((320, 680), "Clean air,", 60, (20, 60, 80, 255), SERIF_I)
    a.text((320, 760), "by subscription.", 60, (20, 60, 80, 255), SERIF_I)
    a.text((320, 880), "¥300/day · 空気は無料ではありません", 30, W_)
    return a.out()


# ==================================================================== holo-pylon loop frames (0.29; _1 _2 _3 play as a loop)

def holo_frame(col, draw, word, sub, k):
    a = Art("holo")
    for y in range(0, 1040, 8):
        a.line([(0, y), (300, y)], rgba(col, 50 + 30 * (k % 2)), 2)
    a.rect((6, 6, 294, 1034), outline=rgba(col), width=6)
    draw(a)
    n = len(word)
    y0, y1 = 400, 920
    ch = (y1 - y0) / max(n, 1)
    for i, c in enumerate(word):
        a.text((150, y0 + ch * (i + 0.5)), c, ch * 0.85, rgba(col), BLACK)
    a.fit((15, 945, 285, 1010), sub, (255, 255, 255, 235))
    return a.out()


@ad("holo_hotel_1")
def h_hotel1():
    return holo_frame((255, 60, 170), lambda a: neon_heart(a, 150, 200, 80, (255, 60, 170), 6, 8), "HOTEL", "Velvet Moon", 1)


@ad("holo_hotel_2")
def h_hotel2():
    return holo_frame((255, 120, 200), lambda a: neon_heart(a, 150, 200, 120, (255, 120, 200), 8, 12), "¥3800", "ご休憩 2h", 2)


@ad("holo_hotel_3")
def h_hotel3():
    def d(a):
        neon_heart(a, 150, 200, 120, (255, 60, 170), 8, 12)
        crescent(a, 150, 195, 50, (255, 230, 240), (60, 10, 50), 0.4)
    return holo_frame((255, 60, 170), d, "空室あり", "VACANCY", 3)


@ad("holo_sale_1")
def h_sale1():
    return holo_frame((255, 230, 0), lambda a: a.poly(star_pts(150, 200, 120, 12, 0.65), fill=(255, 230, 0, 255)), "SALE", "セール", 1)


@ad("holo_sale_2")
def h_sale2():
    return holo_frame((255, 60, 60), lambda a: a.text((150, 200), "-90%", 90, (255, 60, 60, 255), IMPACT), "LIMITED", "限定", 2)


@ad("holo_sale_3")
def h_sale3():
    return glitch(holo_frame((0, 255, 200), lambda a: a.text((150, 200), "!!", 180, (0, 255, 200, 255), IMPACT), "NOW", "今すぐ", 3), 7, 8, 0.05, 6)


@ad("holo_dolls_1")
def h_dolls1():
    return holo_frame((200, 200, 255), lambda a: profile(a, 50, 70, 260, (200, 200, 255)), "DOLLS", "by KISARAGI", 1)


@ad("holo_dolls_2")
def h_dolls2():
    def d(a):
        profile(a, 50, 70, 260, (200, 200, 255))
        a.glow(lambda o: o.circle(195, 160, 8, fill=(80, 220, 255, 255)), 6, 2)
    return holo_frame((200, 200, 255), d, "名前", "she remembers your name", 2)


@ad("holo_dolls_3")
def h_dolls3():
    return holo_frame((255, 160, 220), lambda a: lips(a, 150, 200, 200, (255, 120, 190)), "RENT", "hour · night · year", 3)


@ad("holo_volt")
def h_volt():
    return holo_frame((255, 225, 0), lambda a: a.poly([(170, 60), (100, 220), (150, 220), (120, 340), (210, 170), (160, 170), (200, 60)],
                                                      fill=(255, 225, 0, 255)), "VOLT", "sleep is for the poor", 1)


@ad("holo_gacha")
def h_gacha():
    return holo_frame((255, 120, 220), lambda a: a.poly(star_pts(150, 200, 120), fill=(255, 220, 60, 255)), "GACHA", "★★★★★ 0.003%", 2)


# ==================================================================== kiosk screens (0.65)

def kiosk_base(bg, head, col):
    a = Art("kiosk", bg)
    a.rect((0, 0, 680, 110), fill=rgba(col))
    a.fit((30, 20, 650, 90), head, (8, 22, 40, 255))
    return a


@ad("kiosk_platinum_offer")
def k_platinum():
    a = kiosk_base(MER_BG, "MERIDIAN · CITIZEN SERVICES", CYAN)
    a.text((340, 200), "CITIZEN 0x4F2A-88", 34, (150, 190, 220, 255), MONO)
    gauge(a, 340, 420, 170, 0.55, (255, 200, 60), (255, 255, 255, 40), 26)
    a.text((340, 420), "604", 110, W_, MONO)
    a.text((340, 640), "YOU QUALIFY FOR", 44, W_, BAHN)
    a.text((340, 720), "PLATINUM", 96, (220, 225, 235, 255), BAHN, spacing=6)
    a.rect((140, 820, 540, 920), fill=CYAN, r=20)
    a.text((340, 870), "UPGRADE ¥88,000", 44, (8, 22, 40, 255), BAHN)
    a.text((340, 980), "declining will be noted", 28, (150, 190, 220, 255), SERIF_I)
    return a.out()


@ad("kiosk_loan_approved")
def k_loan():
    a = kiosk_base((255, 236, 242), "SAKURA CREDIT · INSTANT", (210, 20, 90))
    a.text((340, 260), "✓", 220, (40, 180, 90, 255))
    a.text((340, 470), "APPROVED", 110, (40, 180, 90, 255), IMPACT)
    a.text((340, 600), "¥ 500,000", 90, INK, MONO)
    a.text((340, 700), "APR 39.8% · 実質年率", 40, INK)
    a.text((340, 790), "collateral: LEFT KIDNEY", 40, (210, 20, 90, 255), BAHN)
    a.rect((140, 860, 540, 960), fill=(210, 20, 90, 255), r=20)
    a.text((340, 910), "PRESS PALM TO ACCEPT", 32, W_, BAHN)
    return a.out()


@ad("kiosk_match_found")
def k_match():
    a = kiosk_base((240, 252, 240), "MATCHA · NEARBY", (70, 160, 90))
    for i, (sc, ok) in enumerate(((812, True), (790, True), (433, False))):
        y = 160 + i * 230
        a.rect((60, y, 620, y + 200), fill=(255, 255, 255, 255), outline=(200, 210, 200, 255), width=3, r=20)
        a.circle(160, y + 100, 70, fill=(170, 180, 175, 255))
        a.text((260, y + 70), f"{sc}", 60, (70, 160, 90, 255) if ok else (210, 40, 60, 255), MONO, anchor="lm")
        a.text((260, y + 140), "♥ 40m away" if ok else "✕ hidden: below your score", 30, (60, 70, 60, 255), anchor="lm")
    a.text((340, 900), "love, rated. 18+", 50, (40, 60, 45, 255), SERIF_I)
    return a.out()


@ad("kiosk_attention_unlock")
def k_attention():
    a = kiosk_base((10, 10, 14), "ATTENTION REQUIRED", (0, 255, 200))
    eye(a, 340, 330, 180, (0, 255, 200), 14)
    a.text((340, 580), "WATCH 30 SECONDS", 56, W_, BAHN)
    a.text((340, 660), "TO UNLOCK THIS DOOR", 56, W_, BAHN)
    a.rect((90, 760, 590, 800), outline=(0, 255, 200, 255), width=4, r=10)
    a.rect((94, 764, 300, 796), fill=(0, 255, 200, 255), r=8)
    a.text((340, 880), "視線を外さないでください", 40, (0, 255, 200, 255))
    a.text((340, 960), "looking away restarts the timer", 28, (150, 160, 160, 255), SERIF_I)
    return a.out()


# ==================================================================== window vinyl (transparent)

@ad("window_hotel_rates")
def w_rates():
    a = Art("window")
    col = (255, 255, 255, 235)
    heart(a, 150, 300, 110, outline=(255, 120, 190, 255), width=8)
    a.text((620, 120), "HOTEL VELVET MOON", 70, col, BAHN, spacing=4)
    a.text((620, 250), "ご休憩 ¥3,800〜", 80, col)
    a.text((620, 380), "ご宿泊 ¥8,800〜", 80, col)
    a.text((620, 510), "24H · 空室あり", 60, (255, 160, 210, 255))
    return a.out()


@ad("window_members_only")
def w_members():
    a = Art("window")
    col = (240, 220, 160, 230)
    a.rect((40, 40, 1160, 560), outline=col, width=6)
    a.rect((60, 60, 1140, 540), outline=col, width=2)
    a.text((600, 190), "MEMBERS ONLY", 100, col, SERIF, spacing=8)
    a.text((600, 340), "会員制 · 20歳以上", 80, col)
    a.text((600, 470), "CLUB SAPPHIRE  ·  B1F", 50, col, SERIF_I)
    return a.out()


@ad("window_hearts")
def w_hearts():
    a = Art("window")
    rnd = random.Random(3)
    for _ in range(26):
        heart(a, rnd.uniform(40, 1160), rnd.uniform(40, 560), rnd.uniform(18, 60), fill=rgba(rnd.choice([(255, 80, 160), (255, 255, 255), (255, 170, 210)]), 220))
    a.text((600, 300), "LOVE", 200, (255, 255, 255, 240), SCRIPT_B)
    return a.out()


@ad("window_now_hiring")
def w_hiring():
    a = Art("window")
    col = (255, 255, 255, 235)
    a.text((600, 120), "NOW HIRING", 130, (255, 230, 0, 240), IMPACT)
    a.text((600, 280), "ホステス・キャスト募集", 80, col)
    a.text((600, 400), "日払い OK · 未経験歓迎 · 20歳以上", 56, col)
    a.text((600, 510), "your score doesn't matter here*", 44, (255, 200, 220, 230), SERIF_I)
    return a.out()


# ==================================================================== lit vertical banners (0.21: blade sign faces)

def banner(bg0, bg1, draw, word, word_col, f=MINCHO, sub=None, sub_col=W_):
    a = Art("banner")
    a.vgrad((0, 0, 300, 1400), bg0, bg1)
    a.rect((10, 10, 290, 1390), outline=rgba(word_col), width=5)
    draw(a)
    n = len(word)
    y0, y1 = 330, 1220 if sub else 1360
    ch = (y1 - y0) / n
    for i, c in enumerate(word.replace("ー", "｜")):
        a.text((150, y0 + ch * (i + 0.5)), c, min(ch * 0.86, 230), rgba(word_col), f)
    if sub:
        a.fit((20, 1250, 280, 1370), sub, rgba(sub_col), BAHN)
    return a.out()


@ad("banner_velvet_moon")
def bn_velvet():
    def d(a):
        neon_heart(a, 150, 170, 100, (255, 60, 170), 7, 10)
        crescent(a, 150, 165, 40, (255, 230, 240), (60, 0, 50), 0.4)
    return banner((60, 0, 50), (20, 0, 20), d, "ホテル", (255, 120, 200), JP_BOLD, "VELVET MOON")


@ad("banner_club_sapphire")
def bn_sapphire():
    return banner((6, 14, 50), (2, 4, 16), lambda a: woman_gown(a, 0, 20, 300, (110, 170, 255), glass_col=(220, 230, 255)),
                  "クラブ", (130, 180, 255), MINCHO, "SAPPHIRE")


@ad("banner_cabaret")
def bn_cabaret():
    return banner((80, 0, 14), (20, 0, 4), lambda a: legs_pair(a, 140, 60, 230, (255, 210, 150), hem_col=(255, 210, 150), heel_col=(255, 210, 150)),
                  "キャバレー", (255, 210, 150), MINCHO, "LUNA")


@ad("banner_sale")
def bn_sale():
    return glitch(banner((230, 20, 40), (120, 0, 20), lambda a: a.text((150, 170), "%", 220, (255, 230, 0, 255), IMPACT),
                         "大売出し", (255, 230, 0), JP_BOLD, "SALE NOW"), 4, 8, 0.03, 4)


@ad("banner_meridian")
def bn_meridian():
    return banner((14, 40, 70), (6, 18, 34), lambda a: eye(a, 150, 170, 110, CYAN, 10), "市民スコア", (120, 230, 255), JP_BOLD, "YOUR FUTURE")


# ==================================================================== neon glyph signs (white: tinted + emissive in Pigment)

NEON_SIGNS = {
    "sign_velvet_moon": (["Velvet Moon", "HOTEL"], SCRIPT_B),
    "sign_club_sapphire": (["CLUB", "SAPPHIRE"], SERIF),
    "sign_cabaret_luna": (["CABARET", "LUNA"], SERIF),
    "sign_dolls_kisaragi": (["DOLLS", "KISARAGI"], SERIF),
    "sign_peep_show": (["PEEP", "SHOW"], IMPACT),
    "sign_host_zero": (["HOST", "ZERO"], BLACK),
    "sign_snack_yocho": (["スナック", "夜蝶"], JP_BOLD),
    "sign_welcome_yoimachi": (["WELCOME", "宵町"], JP_BOLD),
}
NEON_BLADES = {
    "blade_hotel": "ホテル",
    "blade_kyukei": "ご休憩",
    "blade_snack": "スナック",
    "blade_cabaret": "キャバレー",
    "blade_club": "クラブ",
}
for _k, (_lines, _f) in NEON_SIGNS.items():
    R[_k] = (lambda l, f: lambda: neon_text(l, f, 220 if f == SCRIPT_B else 300, line_gap=0.2))(_lines, _f)
for _k, _t in NEON_BLADES.items():
    R[_k] = (lambda t: lambda: neon_text([t.replace("ー", "｜")], JP_BOLD, 480, vertical=True, line_gap=0.05))(_t)


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
