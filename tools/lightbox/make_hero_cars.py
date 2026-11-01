"""Rebuild docs/readme/hero_cars.png (the README's lead image) from its parts.

    python tools/lightbox/make_hero_cars.py [--sheet PATH] [--ui PATH] [--out PATH]

Layout (1600 x 1728, as committed in 50e408f):
    0..899     docs/readme/pigment_ui_car.png (1600 x 900, Pigment painting the cruiser)
    900..977   a 78 px caption band, #0e0f12: a white Segoe UI Bold title at y=24 and an orange
               Segoe UI subtitle at y=59, both at x=26
    978..1727  a 1600 x 750 livery sheet: one row per vehicle, 8 cells of 200 x 125
               (originally docs/agents/fleet/fleet_variants.png; now the Blender lightbox sheet
               from `lightbox_scene.py -- fleet --look dark --labels 0`)
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sheets import save_small  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
FONTS = os.path.join(ROOT, "crates", "app", "assets", "fonts")

TITLE = "6 vehicles · 47 liveries — every one painted in Pigment (clearcoat, flake, decals, wear)"
SUB = ("police & security · taxis · corporate fleets · Dreamlink / Noctis vans · racing coupé · "
       "MERIDIAN robotaxi · rusty wrecks")
BG = (14, 15, 18)
ORANGE = (240, 136, 58)
# ink extents measured on the original band: (x0, x1, top)
TITLE_BOX = (26, 1213, 24)
SUB_BOX = (26, 1025, 59)


def font_path(weight):
    """The original band is Segoe UI (Windows); Inter (the app's font, in the repo) elsewhere."""
    win = {"Bold": "segoeuib.ttf", "Regular": "segoeui.ttf"}[weight]
    p = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", win)
    return p if os.path.exists(p) else os.path.join(FONTS, f"Inter-{weight}.ttf")


def fitted(text, weight, target_w):
    """The font at the size whose ink width is closest to target_w (the original's)."""
    path = font_path(weight)
    best = None
    for size in range(14, 48):
        f = ImageFont.truetype(path, size)
        x0, _, x1, _ = f.getbbox(text)
        err = abs((x1 - x0) - target_w)
        if best is None or err < best[0]:
            best = (err, f)
    return best[1]


def draw_ink(d, text, f, box, fill):
    x0, y0, _, _ = f.getbbox(text)
    d.text((box[0] - x0, box[2] - y0), text, font=f, fill=fill)


def build(sheet, ui, out, title=TITLE, sub=SUB):
    top = Image.open(ui)
    if top.mode == "RGBA":
        base = Image.new("RGB", top.size, BG)
        base.paste(top, mask=top.split()[3])
        top = base
    top = top.convert("RGB").resize((1600, 900), Image.LANCZOS) if top.size != (1600, 900) else top.convert("RGB")
    sh = Image.open(sheet).convert("RGB")
    if sh.size != (1600, 750):
        sh = sh.resize((1600, 750), Image.LANCZOS)
    hero = Image.new("RGB", (1600, 1728), BG)
    hero.paste(top, (0, 0))
    band = Image.new("RGB", (1600, 78), BG)
    bd = ImageDraw.Draw(band)
    draw_ink(bd, title, fitted(title, "Bold", TITLE_BOX[1] - TITLE_BOX[0]), TITLE_BOX, (240, 241, 244))
    draw_ink(bd, sub, fitted(sub, "Regular", SUB_BOX[1] - SUB_BOX[0]), SUB_BOX, ORANGE)
    hero.paste(band, (0, 900))
    hero.paste(sh, (0, 978))
    return save_small(hero, out, 1_500_000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default=os.path.join(ROOT, "docs", "agents", "lightbox", "hero_liveries.png"))
    ap.add_argument("--ui", default=os.path.join(ROOT, "docs", "readme", "pigment_ui_car.png"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "readme", "hero_cars.png"))
    a = ap.parse_args()
    build(a.sheet, a.ui, a.out)


if __name__ == "__main__":
    main()
