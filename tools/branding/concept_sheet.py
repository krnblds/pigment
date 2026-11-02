"""Lay the icon concepts in assets/branding/concepts out on one comparison sheet.

    python tools/branding/concept_sheet.py

Each concept is shown large and at 48, 32 and 16 px (plain downscales: the
chosen one gets hand-tuned small versions), on dark and light backgrounds.
Writes docs/branding/concepts.png.
"""
from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "branding" / "concepts"
OUT = ROOT / "docs" / "branding" / "concepts.png"

BIG, SMALL = 192, [48, 32, 16]
PAD = 20
DARK, LIGHT = (30, 31, 34), (243, 243, 243)


def render(svg: Path, size: int) -> Image.Image:
    return Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_path=str(svg), width=size, height=size)))).convert("RGBA")


def font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def half(svg: Path, bg) -> Image.Image:
    w = PAD + BIG + PAD
    h = PAD + BIG + PAD + max(SMALL) + PAD
    im = Image.new("RGBA", (w, h), bg + (255,))
    im.alpha_composite(render(svg, BIG), (PAD, PAD))
    x = PAD
    for s in SMALL:
        im.alpha_composite(render(svg, s), (x, PAD + BIG + PAD + max(SMALL) - s))
        x += s + PAD
    return im


def main() -> None:
    svgs = sorted(SRC.glob("*.svg"))
    title_f, label_f = font(30), font(22)
    cards = []
    for svg in svgs:
        d, l = half(svg, DARK), half(svg, LIGHT)
        label_h = 44
        card = Image.new("RGBA", (d.width + l.width, d.height + label_h), (255, 255, 255, 255))
        card.alpha_composite(d, (0, label_h))
        card.alpha_composite(l, (d.width, label_h))
        letter, _, name = svg.stem.partition("-")
        ImageDraw.Draw(card).text((PAD, 10), f"{letter.upper()}  {name.replace('-', ' ')}", fill=(20, 20, 20), font=label_f)
        cards.append(card)
    cols = 2
    cw, ch = cards[0].size
    rows = (len(cards) + cols - 1) // cols
    head = 70
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * PAD, head + rows * (ch + PAD) + PAD), (210, 212, 216))
    ImageDraw.Draw(sheet).text((PAD, 20), "Pigment icon concepts: pick one (or a mix)", fill=(20, 20, 20), font=title_f)
    for i, card in enumerate(cards):
        r, c = divmod(i, cols)
        sheet.paste(card.convert("RGB"), (PAD + c * (cw + PAD), head + r * (ch + PAD)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT, optimize=True)
    print(f"{len(cards)} concepts -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
