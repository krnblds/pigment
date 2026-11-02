"""Regenerate every Pigment icon raster from the SVG sources.

    pip install resvg-py pillow
    python tools/branding/make_icons.py

First runs make_svgs.py, which builds the SVGs from geometry, then
Reads   assets/branding/pigment-icon.svg        (master, used from 48 px up)
        assets/branding/pigment-icon-small.svg  (simplified, 16-32 px)
Writes  assets/branding/png/pigment-<N>.png     for N in 16 24 32 48 64 128 256 512 1024
        assets/branding/pigment.ico             (16 24 32 48 64 256)
        assets/branding/pigment.icns            (macOS, for a future bundle)
        docs/branding/icon_sizes.png            (contact sheet, dark and light)

Rasterising goes through resvg (a pure Rust renderer with Python wheels for
Windows, Linux and macOS), so there is no Cairo or Inkscape to install.
"""
from __future__ import annotations

import io
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw, ImageFont

import make_svgs

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "branding"
MASTER = SRC / "pigment-icon.svg"
SMALL = SRC / "pigment-icon-small.svg"

PNG_DIR = SRC / "png"
SHEET = ROOT / "docs" / "branding" / "icon_sizes.png"

SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 24, 32, 48, 64, 256]
SMALL_MAX = 32  # at and below this the simplified artwork is used

DARK_BG = (30, 31, 34)
LIGHT_BG = (243, 243, 243)


def render(svg: Path, size: int) -> Image.Image:
    data = bytes(resvg_py.svg_to_bytes(svg_path=str(svg), width=size, height=size))
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    assert img.size == (size, size), (svg, img.size)
    return img


def icon(size: int) -> Image.Image:
    return render(SMALL if size <= SMALL_MAX else MASTER, size)


def contact_sheet(imgs: dict[int, Image.Image]) -> Image.Image:
    pad, label_h, zoom = 24, 18, 8
    font = ImageFont.load_default()
    row_w = pad + sum(s + pad for s in SIZES)
    row_h = pad + max(SIZES) + label_h + pad
    # a zoomed strip of the small sizes, pixel for pixel, under each row
    zoom_sizes = [s for s in SIZES if s <= SMALL_MAX]
    zoom_h = pad + max(zoom_sizes) * zoom + label_h + pad
    sheet = Image.new("RGBA", (row_w, 2 * (row_h + zoom_h)))
    y = 0
    for bg, fg in ((DARK_BG, (200, 200, 200)), (LIGHT_BG, (60, 60, 60))):
        band = Image.new("RGBA", (row_w, row_h + zoom_h), bg + (255,))
        d = ImageDraw.Draw(band)
        x = pad
        for s in SIZES:
            band.alpha_composite(imgs[s], (x, pad + max(SIZES) - s))
            d.text((x, pad + max(SIZES) + 4), f"{s}", fill=fg, font=font)
            x += s + pad
        x = pad
        for s in zoom_sizes:
            big = imgs[s].resize((s * zoom, s * zoom), Image.Resampling.NEAREST)
            top = row_h + pad + (max(zoom_sizes) - s) * zoom
            band.alpha_composite(big, (x, top))
            d.text((x, row_h + pad + max(zoom_sizes) * zoom + 4), f"{s} px at {zoom}x", fill=fg, font=font)
            x += s * zoom + pad
        sheet.alpha_composite(band, (0, y))
        y += row_h + zoom_h
    return sheet.convert("RGB")


def main() -> None:
    make_svgs.main()
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    imgs = {s: icon(s) for s in SIZES}
    for s, img in imgs.items():
        img.save(PNG_DIR / f"pigment-{s}.png", optimize=True)

    # each ICO entry is its own hand-picked raster, not a downscale of the biggest
    largest = imgs[max(ICO_SIZES)]
    largest.save(
        SRC / "pigment.ico",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=[imgs[s] for s in ICO_SIZES if s != max(ICO_SIZES)],
    )
    imgs[1024].save(SRC / "pigment.icns", append_images=[imgs[s] for s in (16, 32, 64, 128, 256, 512)])

    contact_sheet(imgs).save(SHEET, optimize=True)

    with Image.open(SRC / "pigment.ico") as ico:
        got = sorted(ico.info.get("sizes", set()))
    assert got == [(s, s) for s in ICO_SIZES], got
    print(f"wrote {len(SIZES)} PNGs, pigment.ico {ICO_SIZES}, pigment.icns and {SHEET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
