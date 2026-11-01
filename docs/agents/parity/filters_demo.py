"""Filters + anchor points on town building_a (before / after).

Writes scenes/town/scripts/parity_filters_demo.jsonl, runs it with
target/release/pigment-mcp.exe and composes docs/agents/parity/filters_before_after.png.

    python docs/agents/parity/filters_demo.py [resolution]

Before: the town script's stack. After, on top of it:
  - "Dents": a paint layer of painted dents and gouges (height only), set as
    an anchor point;
  - "Grime in dents": a dirt generator whose input is the Dents anchor's height,
    so grime gathers in the painted dents (not just the mesh's crevices);
  - "Chipped rims": edge wear reading the same anchor: bright chipped concrete
    on the dent rims;
  - the Leaks layer's mask gets warp + slope blur mask filters (organic runs);
  - a "Grade" filter layer: colour balance (cool shadows, warm highlights) and a
    noise overlay on roughness.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/agents/parity"
SCRIPT = ROOT / "scenes/town/scripts/parity_filters_demo.jsonl"
RES = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
CAM = {"yaw": 0, "pitch": 5, "target": [0, 3, 0], "distance": 12}
SKIP = {"export_textures", "export_variants", "save_project", "render"}


def main():
    lines = []
    for raw in (ROOT / "scenes/town/scripts/building_a.jsonl").read_text().splitlines():
        if not raw.strip():
            continue
        call = json.loads(raw)
        if call["tool"] in SKIP:
            continue
        if call["tool"] == "new_project":
            call["args"]["resolution"] = RES
        lines.append(call)
    tmp = ROOT / "target/pd"
    tmp.mkdir(parents=True, exist_ok=True)
    render = lambda name: {"tool": "render", "args": {**CAM, "width": 960, "height": 720, "path": f"target/pd/{name}.png"}}
    lines.append(render("filters_before"))
    # painted dents and gouges: height only, on the wall right of the shutter and between the windows
    lines.append({"tool": "add_layer", "args": {"kind": "paint", "name": "Dents", "anchor": "Dents"}})
    strokes = [
        ([[0.80, 0.42], [0.86, 0.47], [0.93, 0.45]], 26),
        ([[0.78, 0.55], [0.84, 0.53]], 34),
        ([[0.90, 0.58], [0.95, 0.62]], 20),
        ([[0.15, 0.13], [0.30, 0.16], [0.42, 0.12]], 18),
        ([[0.60, 0.10], [0.70, 0.13]], 30),
        ([[0.08, 0.50], [0.20, 0.47], [0.35, 0.52]], 14),
    ]
    for pts, size in strokes:
        lines.append({"tool": "paint_stroke", "args": {**CAM, "width": 960, "height": 720, "layer": "Dents", "points": pts, "size": size,
                                                         "hardness": 0.15, "channels": ["height"], "height": -0.7}})
    lines.append({"tool": "add_layer", "args": {"name": "Grime in dents", "index": 999, "material": "Grime", "opacity": 0.9, "channels": {"height": False, "metallic": False},
                                                "mask": {"generator": "dirt", "amount": 0.42, "softness": 0.12, "breakup": 0.25, "ao_influence": 0.0,
                                                         "input": {"anchor": "Dents", "channel": "height", "strength": 6, "radius": 10}}}})
    lines.append({"tool": "add_layer", "args": {"name": "Chipped rims", "index": 999, "material": "Concrete", "values": {"base_color": [0.62, 0.6, 0.57], "roughness": 0.95},
                                                "channels": {"height": False, "metallic": False},
                                                "mask": {"generator": "edge_wear", "amount": 0.25, "softness": 0.08, "breakup": 0.6, "scale": 40, "ao_influence": 0.0,
                                                         "input": {"anchor": "Dents", "channel": "height", "strength": 3, "radius": 5}}}})
    leaks = next((c["args"]["name"] for c in lines if c["tool"] == "add_layer" and "leak" in c["args"].get("name", "").lower()), None)
    if leaks:
        lines.append({"tool": "update_layer", "args": {"layer": leaks, "mask": {"filters": [{"kind": "warp", "radius": 6, "amount": 1.0, "scale": 3},
                                                                                         {"kind": "slope_blur", "radius": 10, "amount": 0.8, "scale": 2}]}}})
    lines.append({"tool": "add_layer", "args": {"kind": "filter", "name": "Grade", "filters": [
        {"kind": "color_balance", "shadows": [-0.08, 0.0, 0.1], "highlights": [0.08, 0.03, -0.05]},
        {"kind": "noise_overlay", "amount": 0.12, "scale": 25, "channels": ["roughness", "base_color"]}]}})
    lines.append(render("filters_after"))
    lines.append({"tool": "render", "args": {**CAM, "width": 960, "height": 720, "view": "height", "path": "target/pd/filters_after_height.png"}})
    SCRIPT.write_text("\n".join(json.dumps(c) for c in lines) + "\n")
    exe = ROOT / "target/release/pigment-mcp.exe"
    subprocess.run([str(exe), "--script", str(SCRIPT)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    from PIL import Image, ImageDraw
    a, b = Image.open(tmp / "filters_before.png"), Image.open(tmp / "filters_after.png")
    w, h = a.size
    out = Image.new("RGB", (w * 2, h), "black")
    out.paste(a, (0, 0))
    out.paste(b, (w, 0))
    d = ImageDraw.Draw(out)
    d.text((12, 10), "before: town stack", fill="white")
    d.text((w + 12, 10), "after: dents anchor -> grime + chipped rims, warped leak mask, grade filter layer", fill="white")
    out = out.resize((w * 2 * 3 // 4, h * 3 // 4), Image.LANCZOS)
    out.save(OUT / "filters_before_after.png", optimize=True)
    print("wrote", OUT / "filters_before_after.png")


if __name__ == "__main__":
    main()
