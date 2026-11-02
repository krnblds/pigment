"""Export templates: 8-bit PNG vs EXR on the town overhead sign.

    python docs/agents/parity/templates_demo.py

Runs the town overhead_sign script, adds a stacked-dent height layer that
goes past -1, then exports with the built-in `separate` template (8-bit
emission normalised to its peak, 16-bit height clamped to -1..1) and with the
`arnold` template (linear EXR: HDR emission and raw height kept). Writes
docs/agents/parity/templates_before_after.png: emission and height, PNG
(before) vs EXR (after), shown as false colour of the stored values.
"""
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/agents/parity"
TMP = ROOT / "target/pd/tpl"


def main():
    lines = [json.loads(l) for l in (ROOT / "scenes/town/scripts/overhead_sign.jsonl").read_text().splitlines() if l.strip()]
    lines = [c for c in lines if c["tool"] not in ("export_textures", "export_variants", "save_project", "render")]
    # deep stacked dents: composited height goes well below -1 (HDR)
    lines.append({"tool": "add_layer", "args": {"name": "Deep dents", "values": {"height": -1.0}, "channels": {"height": True, "base_color": False, "roughness": False, "metallic": False},
                                                "height_gain": 3.0, "mask": {"generator": "spots", "amount": 0.25, "scale": 6.0}}})
    lines.append({"tool": "export_textures", "args": {"dir": str(TMP).replace("\\", "/"), "name": "sign", "preset": "separate"}})
    lines.append({"tool": "export_textures", "args": {"dir": str(TMP).replace("\\", "/"), "name": "sign", "template": "arnold"}})
    script = ROOT / "target/pd/templates_demo.jsonl"
    script.write_text("\n".join(json.dumps(c) for c in lines) + "\n")
    subprocess.run([str(ROOT / "target/release/pigment-mcp.exe"), "--script", str(script)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    import exr_read
    from PIL import Image, ImageDraw
    png_e = np.asarray(Image.open(TMP / "sign_Emissive.png").convert("RGB"), np.float32) / 255.0
    png_h = np.asarray(Image.open(TMP / "sign_Height.png"), np.float32) / 65535.0 * 2.0 - 1.0
    exr_e = exr_read.rgb(TMP / "sign_emission.exr")
    exr_h = exr_read.y(TMP / "sign_height.exr")

    def lum(a):
        return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722

    def false_colour(v, lo, hi):
        t = np.clip((v - lo) / (hi - lo), 0, 1)
        r = np.clip(1.5 - np.abs(t * 4 - 3), 0, 1)
        g = np.clip(1.5 - np.abs(t * 4 - 2), 0, 1)
        b = np.clip(1.5 - np.abs(t * 4 - 1), 0, 1)
        return Image.fromarray((np.stack([r, g, b], -1) * 255).astype(np.uint8))

    peak = float(lum(exr_e).max())
    hi = max(peak, 1.0)
    tiles = [
        (false_colour(lum(png_e), 0, hi), f"PNG emission: stored 0..1 (peak normalised to 1)"),
        (false_colour(lum(exr_e), 0, hi), f"EXR emission: linear HDR, peak {peak:.1f}"),
        (false_colour(png_h, -3, 1), f"PNG height: clamped {png_h.min():.2f}..{png_h.max():.2f}"),
        (false_colour(exr_h, -3, 1), f"EXR height: raw {exr_h.min():.2f}..{exr_h.max():.2f}"),
    ]
    s = 420
    out = Image.new("RGB", (s * 2, s * 2 + 40), "black")
    d = ImageDraw.Draw(out)
    for k, (img, label) in enumerate(tiles):
        x, y = (k % 2) * s, (k // 2) * (s + 20)
        out.paste(img.resize((s, s), Image.NEAREST), (x, y + 20))
        d.text((x + 6, y + 4), label, fill="white")
    out.save(OUT / "templates_before_after.png", optimize=True)
    print("emission peak", peak, "height range", exr_h.min(), exr_h.max(), "png height", png_h.min(), png_h.max())


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    main()
