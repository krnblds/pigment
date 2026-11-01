"""Foliage workstream proof: writes and runs the Pigment scripts.

    python tools/foliage_demo.py [--run] [--res 2048] [--out target/foliage]

1. `japan_atlas.jsonl`: a foliage atlas project with the Japanese tree
   species (pagoda tree, maple, ginkgo, cherry blossom, black pine) plus
   grass and ivy, drawn by the leaf generators; exports the atlas maps for
   Godot (albedo + backlight) and Blender, and composes
   docs/agents/foliage/atlas_sheet.png.
2. `building_a_foliage.jsonl`: building_a's town texture script (paths moved
   to the output folder), then moss and weeds in the rooftop / ledge
   crevices (scatter masked by the `Ledge moss` generator layer and the baked
   AO), ivy climbing the east wall (growth walk), viewport renders, and
   send_to_blender (textures + mesh + foliage).
3. `street_foliage.jsonl`: the street segment's town script, then grass and
   weeds in the asphalt cracks (masked by its `Cracks` layer) and in the
   paving joints; send_to_blender.

Then: docs/agents/foliage/blender_night_rain.py (Cycles) and the Godot demo
(game/scripts/foliage_demo.gd, `godot --path game -- --foliage-demo=...`).
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def town_script(name, out_dir, res):
    """The checked-in town script with its outputs moved and renders /
    variant exports dropped."""
    lines = []
    with open(os.path.join(ROOT, "scenes", "town", "scripts", f"{name}.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            t = c["tool"]
            if t in ("render", "render_turntable", "export_variants", "export_textures", "save_project"):
                continue
            if t == "new_project":
                c["args"]["resolution"] = res
            lines.append(c)
    return lines


def write(path, calls):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps(c) + "\n")
    print("wrote", rel(path))


def atlas_calls(out):
    cells = [
        {"name": "pagoda_tree", "preset": "pagoda_tree"},
        {"name": "maple", "preset": "maple"},
        {"name": "maple_autumn", "preset": "maple_autumn"},
        {"name": "ginkgo", "preset": "ginkgo"},
        {"name": "cherry_blossom", "preset": "cherry_blossom"},
        {"name": "black_pine", "preset": "black_pine"},
        {"name": "grass", "preset": "grass"},
        {"name": "ivy", "preset": "ivy"},
    ]
    a = os.path.join(out, "atlas")
    return [
        {"tool": "new_project", "args": {"resolution": 4096, "foliage_atlas": {"name": "JapanTrees", "cells": cells, "padding_px": 24}}},
        # a little wear on two cells, through their folders (generators on top of the generated leaves)
        {"tool": "add_foliage_cell", "args": {"name": "ginkgo_autumn", "preset": "ginkgo", "autumn": 0.95, "autumn_jitter": 0.2, "dry_edges": 0.15, "seed": 9}},
        {"tool": "update_foliage_cell", "args": {"cell": "pagoda_tree", "holes": 0.15, "bites": 0.25}},
        {"tool": "add_layer", "args": {"name": "Dust", "parent": "black_pine", "values": {"base_color": [0.35, 0.33, 0.28]}, "opacity": 0.35, "mask": {"generator": "grunge", "amount": 0.4, "scale": 30}, "channels": {"height": False}}},
        {"tool": "export_textures", "args": {"dir": rel(a), "preset": "godot", "name": "JapanTrees"}},
        {"tool": "export_textures", "args": {"dir": rel(a + "_blender"), "preset": "separate", "name": "JapanTrees"}},
        {"tool": "export_textures", "args": {"dir": rel(a + "_unreal"), "preset": "unreal", "name": "JapanTrees"}},
        {"tool": "save_project", "args": {"path": rel(os.path.join(out, "projects", "JapanTrees.pigment"))}},
    ]


def building_calls(out, res):
    calls = town_script("building_a", out, res)
    calls += [
        # moss tufts and patches where the moss generator is strong (ledges, sills), denser in crevices
        {"tool": "scatter_foliage", "args": {"layer": "Moss & weeds", "cells": [{"cell": "moss", "weight": 3}, {"cell": "moss_patch", "weight": 2}], "density": 30, "facing": "up", "mask": "Ledge moss", "mask_threshold": 0.45, "seed": 11, "scale": [0.8, 1.4]}},
        {"tool": "scatter_foliage", "args": {"layer": "Moss & weeds", "cells": ["moss", "moss_patch"], "density": 40, "facing": "up", "ao": [0, 0.5], "seed": 12, "scale": [0.7, 1.2]}},
        # weeds on the roof and the ledges, only in the corners (low AO)
        {"tool": "scatter_foliage", "args": {"layer": "Moss & weeds", "cells": [{"cell": "weed", "weight": 2}, {"cell": "grass", "weight": 3}], "count": 900, "facing": "up", "ao": [0, 0.62], "seed": 13, "scale": [0.6, 1.1], "align": 0.8}},
        # ivy up the east wall (x = +4.39, the street side)
        {"tool": "grow_ivy", "args": {"layer": "Ivy", "start": [[4.4, 0.1, -4.2], [4.4, 0.1, -1.6], [4.4, 0.1, 1.3], [4.4, 0.1, 4.1]], "length": 9, "branching": 1.6, "max_strands": 40, "leaf_spacing": 0.035, "leaf_scale": [1.1, 1.7], "up_bias": 0.65, "wander": 0.4, "seed": 7, "wind": 0.3}},
        # hanging plants under the balconies
        {"tool": "scatter_foliage", "args": {"layer": "Hanging plants", "cells": ["hanging_vine", "fern"], "count": 40, "facing": "down", "min_up": -1, "max_up": -0.8, "region": {"min": [-6, 2, -8], "max": [-4.3, 20, 8]}, "seed": 14, "scale": [0.8, 1.3], "mount": "hanging"}},
        {"tool": "render", "args": {"yaw": 62, "pitch": 6, "target": [4.4, 4.5, 0], "distance": 15, "width": 1200, "height": 900, "lighting": "night_rain", "exposure": 2.2, "path": rel(os.path.join(ROOT, "docs/agents/foliage/viewport_ivy_wall.png"))}},
        {"tool": "render", "args": {"yaw": -140, "pitch": 40, "target": [0, 20, 0], "distance": 13, "width": 1200, "height": 900, "lighting": "studio", "exposure": 0, "path": rel(os.path.join(ROOT, "docs/agents/foliage/viewport_roof_moss.png"))}},
        {"tool": "save_project", "args": {"path": rel(os.path.join(out, "projects", "building_a_foliage.pigment"))}},
        {"tool": "send_to_blender", "args": {"dir": rel(os.path.join(out, "building_a")), "name": "building_a"}},
    ]
    return calls


def street_calls(out, res):
    calls = town_script("street_segment", out, res)
    calls += [
        # grass and weeds in the asphalt cracks (the Cracks layer's scratches generator)
        {"tool": "scatter_foliage", "args": {"layer": "Crack grass", "cells": [{"cell": "grass", "weight": 3}, {"cell": "weed", "weight": 1}], "count": 1500, "parts": [0], "facing": "up", "mask": "Cracks", "mask_threshold": 0.6, "seed": 21, "scale": [0.45, 0.9], "align": 0.9}},
        # and along the paving joints and curbs
        {"tool": "scatter_foliage", "args": {"layer": "Crack grass", "cells": ["grass", "moss", "moss_patch"], "count": 900, "parts": [2, 4], "facing": "up", "mask": "Paving joints", "mask_threshold": 0.3, "seed": 22, "scale": [0.5, 0.9]}},
        {"tool": "scatter_foliage", "args": {"layer": "Fallen leaves", "cells": ["maple_leaf", "ginkgo_leaf", "cherry_petals"], "count": 260, "facing": "up", "seed": 23, "scale": [0.8, 1.3]}},
        {"tool": "render", "args": {"yaw": 20, "pitch": 30, "target": [3, 0, 3], "distance": 6, "width": 1200, "height": 900, "path": rel(os.path.join(ROOT, "docs/agents/foliage/viewport_street_cracks.png"))}},
        {"tool": "save_project", "args": {"path": rel(os.path.join(out, "projects", "street_foliage.pigment"))}},
        {"tool": "send_to_blender", "args": {"dir": rel(os.path.join(out, "street_segment")), "name": "street_segment"}},
    ]
    return calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--res", type=int, default=2048)
    ap.add_argument("--out", default=os.path.join(ROOT, "target", "foliage"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    scripts = {
        "japan_atlas": atlas_calls(out),
        "building_a_foliage": building_calls(out, a.res),
        "street_foliage": street_calls(out, a.res),
    }
    exe = os.environ.get("PIGMENT_MCP", os.path.join(ROOT, "target", "release", "pigment-mcp.exe" if os.name == "nt" else "pigment-mcp"))
    for name, calls in scripts.items():
        if a.only and name not in a.only.split(","):
            continue
        p = os.path.join(out, "scripts", f"{name}.jsonl")
        write(p, calls)
        if a.run:
            r = subprocess.run([exe, "--script", p], cwd=ROOT)
            if r.returncode != 0:
                sys.exit(f"{name} failed")
    if a.run and (not a.only or "japan_atlas" in a.only):
        atlas_sheet(os.path.join(out, "atlas"), os.path.join(ROOT, "docs", "agents", "foliage", "atlas_sheet.png"))


def atlas_sheet(atlas_dir, dst):
    """Atlas over a checker with cell names, plus its translucency and normal maps."""
    from PIL import Image, ImageDraw
    c = Image.open(os.path.join(atlas_dir, "JapanTrees_BaseColorAlpha.png")).convert("RGBA")
    t = Image.open(os.path.join(atlas_dir, "JapanTrees_Translucency.png")).convert("RGB")
    n = Image.open(os.path.join(atlas_dir, "JapanTrees_normal.png")).convert("RGB")
    lay = json.load(open(os.path.join(atlas_dir, "JapanTrees_layout.json"), encoding="utf-8"))
    S = 1100
    s = S / c.width
    bg = Image.new("RGBA", c.size, (0, 0, 0, 255))
    d = ImageDraw.Draw(bg)
    k = 64
    for y in range(0, c.height, k):
        for x in range(0, c.width, k):
            v = 58 if (x // k + y // k) % 2 else 70
            d.rectangle([x, y, x + k, y + k], fill=(v, v, v + 6, 255))
    bg.alpha_composite(c)
    main = bg.convert("RGB").resize((S, S), Image.LANCZOS)
    dm = ImageDraw.Draw(main)
    for cell in lay["cells"]:
        x0, y0 = cell["px"][0] * s, cell["px"][1] * s
        dm.text((x0 + 6, y0 + 4), cell["name"], fill=(235, 235, 235))
    side = S // 2
    out = Image.new("RGB", (S + side, S), (20, 20, 22))
    out.paste(main, (0, 0))
    out.paste(t.resize((side, side), Image.LANCZOS), (S, 0))
    out.paste(n.resize((side, side), Image.LANCZOS), (S, side))
    do = ImageDraw.Draw(out)
    do.text((S + 8, 6), "translucency (backlight)", fill=(240, 240, 240))
    do.text((S + 8, side + 6), "normal", fill=(240, 240, 240))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    out.save(dst, optimize=True)
    print("wrote", rel(dst))


if __name__ == "__main__":
    main()
