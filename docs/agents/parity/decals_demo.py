"""Decal objects on town building_a (before / after).

    python docs/agents/parity/decals_demo.py [resolution]

After the town stack, on a "Poster wall" decal layer:
  - place_decal region auto: the largest flat, window-free wall area at street
    level, filled with a 2 x 3 grid of ad posters;
  - a graffiti by the corner with the wrap (conform) projection;
  - on the street lamp's pole, the same sticker with box projection (it smears
    and fades round the curve) and wrap projection (it follows the surface);
  - non-destructive edits afterwards: one poster scaled and rotated, one
    hidden, the graffiti moved: the layer re-composites each time.
Writes scenes/town/scripts/parity_decals_demo.jsonl, parity_decals_lamp.jsonl and
docs/agents/parity/decals_before_after.png.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/agents/parity"
SCRIPT = ROOT / "scenes/town/scripts/parity_decals_demo.jsonl"
RES = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
SKIP = {"export_textures", "export_variants", "save_project", "render"}
ADS = ["assets/decals/ads/" + n for n in ["poster_ad_volt_rush.png", "poster_ad_sale_now.png", "poster_ad_hoshicoin.png", "poster_ad_ramen_retro.png", "poster_ad_pachinko_galaxy.png", "poster_ad_noctis_sleep.png"]]


def town():
    out = []
    for raw in (ROOT / "scenes/town/scripts/building_a.jsonl").read_text().splitlines():
        if raw.strip():
            c = json.loads(raw)
            if c["tool"] not in SKIP:
                if c["tool"] == "new_project":
                    c["args"]["resolution"] = RES
                out.append(c)
    return out


def run(lines, script=SCRIPT):
    script.write_text("\n".join(json.dumps(c) for c in lines) + "\n")
    r = subprocess.run([str(ROOT / "target/release/pigment-mcp.exe"), "--script", str(script)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        r.check_returncode()
    return r.stdout


def main():
    poster = {"tool": "place_decal", "args": {"images": ADS, "region": "auto", "height": [0.4, 3.4], "grid": {"rows": 2, "cols": 3, "gap": 0.12},
                                               "layer": "Poster wall", "fill": 0.92, "wear": 0.12, "fade": 0.15, "name": "ad"}}
    base = town() + [{"tool": "add_layer", "args": {"kind": "decal", "name": "Poster wall"}}, poster]
    out = run(base)
    m = re.search(r'"region":\s*\{\s*"center":\s*\[([^\]]*)\]\s*,\s*"normal":\s*\[([^\]]*)\]', out.replace("\n", " "))
    c = [float(x) for x in m.group(1).split(",")]
    n = [float(x) for x in m.group(2).split(",")]
    yaw = round(__import__("math").degrees(__import__("math").atan2(n[0], n[2])))
    wall = {"yaw": yaw, "pitch": 6, "target": c, "distance": 7.5, "width": 900, "height": 640}
    corner = {"yaw": 50, "pitch": 8, "target": [4.0, 1.8, 5.1], "distance": 4.2, "width": 900, "height": 640}
    lines = town() + [{"tool": "render", "args": {**wall, "path": "target/pd/dec_before_wall.png"}},
                      {"tool": "render", "args": {**corner, "path": "target/pd/dec_before_corner.png"}},
                      {"tool": "add_layer", "args": {"kind": "decal", "name": "Poster wall"}}, poster,
                      {"tool": "project_decal", "args": {"image": "assets/decals/story/graffiti_unplug.png", "layer": "Poster wall", "position": [4.0, 1.8, 4.9], "normal": [1, 0, 0],
                                                         "size": 1.6, "projection": "wrap", "name": "unplug_wrap", "tint": [0.1, 0.95, 1.0], "emissive_strength": 1.5}},
                      {"tool": "render", "args": {**wall, "path": "target/pd/dec_after_wall_v1.png"}},
                      # non-destructive edits: scale + rotate one, hide one, nudge the graffiti
                      {"tool": "update_decal", "args": {"decal": "ad_1", "scale": 1.15, "rotate": -6}},
                      {"tool": "update_decal", "args": {"decal": "ad_4", "enabled": False}},
                      {"tool": "update_decal", "args": {"decal": "unplug_wrap", "move": [-0.1, 0.15]}},
                      {"tool": "list_decals", "args": {}},
                      {"tool": "render", "args": {**wall, "path": "target/pd/dec_after_wall.png"}},
                      {"tool": "render", "args": {**corner, "path": "target/pd/dec_after_corner.png"}}]
    run(lines)
    # wrap vs box on a curved surface: the street lamp's pole
    lamp = [{"tool": "new_project", "args": {"mesh": "assets/town/street_lamp.glb", "resolution": RES, "material": "Gunmetal"}},
            {"tool": "add_layer", "args": {"kind": "decal", "name": "Stickers"}}]
    for y, proj in ((1.2, "box"), (2.1, "wrap")):
        lamp.append({"tool": "project_decal", "args": {"image": "assets/decals/story/poster_unplug.png", "layer": "Stickers", "position": [0.0, y, 0.4], "normal": [0, 0, 1],
                                                       "size": 0.42, "projection": proj, "name": f"sticker_{proj}"}})
    for k, yaw in ((0, 20), (1, 95)):
        lamp.append({"tool": "render", "args": {"yaw": yaw, "pitch": 4, "target": [0.0, 1.65, 0.0], "distance": 2.2, "width": 900, "height": 640, "path": f"target/pd/dec_lamp_{k}.png"}})
    run(lamp, ROOT / "scenes/town/scripts/parity_decals_lamp.jsonl")
    from PIL import Image, ImageDraw
    tmp = ROOT / "target/pd"
    names = [("dec_before_wall", "before: town stack"), ("dec_after_wall", "after: region auto 2x3 poster grid (then ad_1 scaled + rotated, ad_4 hidden)"),
             ("dec_before_corner", "before: the corner"), ("dec_after_corner", "after: a wrap-projected graffiti by the corner (stops where the pillar is separate geometry)"),
             ("dec_lamp_0", "street lamp pole: box projection (lower) vs wrap (upper)"), ("dec_lamp_1", "from the side: box smears and fades, wrap follows the curve")]
    imgs = [Image.open(tmp / f"{k}.png") for k, _ in names]
    w, h = imgs[0].size
    out_img = Image.new("RGB", (w * 2, h * 3), "black")
    d = ImageDraw.Draw(out_img)
    for k, (im, (_, label)) in enumerate(zip(imgs, names)):
        x, y = (k % 2) * w, (k // 2) * h
        out_img.paste(im, (x, y))
        d.text((x + 10, y + 8), label, fill="white")
    out_img = out_img.resize((w * 3 // 2, h * 9 // 4), Image.LANCZOS)
    out_img.save(OUT / "decals_before_after.png", optimize=True)
    print("wrote", OUT / "decals_before_after.png", "region centre", c, "normal", n)


if __name__ == "__main__":
    main()
