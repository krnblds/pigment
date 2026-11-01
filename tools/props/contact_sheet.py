"""Lineup contact sheet from the Cycles tiles (render_proof.py lineup).

    python tools/props/contact_sheet.py   ->  docs/agents/props/lineup.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import catalog  # noqa: E402

DOCS = os.path.join(ROOT, "docs", "agents", "props")
ORDER = ["traffic", "signage", "street_furniture", "utility", "food", "clutter", "rooftop", "nature", "decal"]


def main():
    tiles = os.path.join(DOCS, "tiles")
    names = sorted([n for n in catalog.names() if os.path.exists(os.path.join(tiles, f"{n}.png"))],
                   key=lambda n: (ORDER.index(catalog.PROPS[n]["category"]), n))
    T, cols = 300, 8
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (T * cols, (T + 34) * rows + 60), (12, 12, 16))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 20)
    fs = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 14)
    big = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 32)
    d.text((16, 12), f"Street props kit: {len(names)} props (assets/props/*.glb rendered in Cycles, Pigment textures)", font=big, fill=(230, 230, 235))
    for i, n in enumerate(names):
        x, y = (i % cols) * T, 60 + (i // cols) * (T + 34)
        im = Image.open(os.path.join(tiles, f"{n}.png")).convert("RGB").resize((T, T), Image.LANCZOS)
        sheet.paste(im, (x, y))
        d.text((x + 8, y + T + 2), n, font=f, fill=(235, 235, 240))
        d.text((x + 8, y + T + 20), catalog.PROPS[n]["category"], font=fs, fill=(140, 200, 230))
    out = os.path.join(DOCS, "lineup.png")
    sheet.save(out, optimize=True)
    if os.path.getsize(out) > 1_500_000:
        sheet.convert("RGB").save(out.replace(".png", ".jpg"), quality=88)
        os.remove(out)
        out = out.replace(".png", ".jpg")
    print(f"[contact_sheet] {out}: {os.path.getsize(out) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
