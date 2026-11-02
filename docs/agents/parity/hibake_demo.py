"""High-to-low bake + ID masks on the generated bevelled box pair (before / after).

    python docs/agents/parity/hibake_demo.py

Writes the pair (cargo test write_test_pair), bakes the sculpted high box onto
the 4 x 4-quads-per-face low box, then paints by ID: red lid, gold ring,
edge wear from the high mesh's curvature, grime in the high mesh's AO.
Output: docs/agents/parity/hibake_before_after.png (renders + the baked maps).
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/agents/parity"
TMP = ROOT / "target/pd"
CAM = {"yaw": 30, "pitch": 28, "zoom": 1.35, "width": 720, "height": 600}


def main():
    subprocess.run(["cargo", "test", "-p", "pigment-core", "--release", "-j", "6", "write_test_pair", "--", "--ignored"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lid = [0.6826, 0.4275, 0.95]   # hibake::id_color(1)
    ring = [0.1875, 0.75, 0.298]   # hibake::id_color(2)
    L = [
        {"tool": "new_project", "args": {"mesh": "target/pd/box_low.obj", "resolution": 2048, "material": "Teal paint"}},
        {"tool": "render", "args": {**CAM, "path": "target/pd/hb_before.png"}},
        {"tool": "bake", "args": {"high_mesh": "target/pd/box_high.obj", "dir": "target/pd/hb_maps",
                                  "maps": ["normal", "ao", "curvature", "height", "thickness", "color_id", "position", "normal_object"]}},
        {"tool": "add_layer", "args": {"name": "Lid paint", "material": "Red paint", "mask": {"id_color": {"color": lid, "tolerance": 0.08}}}},
        {"tool": "add_layer", "args": {"name": "Ring", "material": "Gold", "mask": {"id_color": {"color": ring, "tolerance": 0.08}}}},
        {"tool": "add_layer", "args": {"name": "Edge wear", "material": "Steel", "mask": {"generator": "edge_wear", "amount": 0.55, "softness": 0.08, "breakup": 0.6, "scale": 30}}},
        {"tool": "add_layer", "args": {"name": "Grime", "material": "Grime", "opacity": 0.8, "mask": {"generator": "dirt", "amount": 0.5, "softness": 0.2, "breakup": 0.4}}},
        {"tool": "render", "args": {**CAM, "path": "target/pd/hb_after.png"}},
    ]
    script = TMP / "hibake_demo.jsonl"
    script.write_text("\n".join(json.dumps(c) for c in L) + "\n")
    subprocess.run([str(ROOT / "target/release/pigment-mcp.exe"), "--script", str(script)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    from PIL import Image, ImageDraw
    a, b = Image.open(TMP / "hb_before.png"), Image.open(TMP / "hb_after.png")
    w, h = a.size
    maps = ["normal", "ao", "curvature", "height", "thickness", "color_id"]
    t = w * 2 // len(maps)
    out = Image.new("RGB", (w * 2, h + t + 22), "black")
    out.paste(a, (0, 0))
    out.paste(b, (w, 0))
    d = ImageDraw.Draw(out)
    for k, m in enumerate(maps):
        img = Image.open(TMP / "hb_maps" / f"box_low_{m}.png")
        if img.mode in ("I;16", "I"):
            img = img.point(lambda x: x / 257).convert("L")
        img = img.convert("RGB").resize((t, t), Image.LANCZOS)
        out.paste(img, (k * t, h + 22))
        d.text((k * t + 6, h + 5), m, fill="white")
    d.text((12, 10), "before: low box (4x4 quads per face), teal paint", fill="white")
    d.text((w + 12, 10), "after: baked from the sculpted high box; lid / ring masked by colour ID; wear + grime from high curvature / AO", fill="white")
    out.save(OUT / "hibake_before_after.png", optimize=True)
    print("wrote", OUT / "hibake_before_after.png")


if __name__ == "__main__":
    main()
