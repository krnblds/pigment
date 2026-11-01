"""Texture the generated junction meshes with Pigment (pigment-mcp --script).

tools/blender_town.py (via town_layout_driver.py --export-junctions) writes
assets/town/junction_*.glb plus a .parts.json sidecar that names every
connected part (road, curb, walk, paint) by its glTF-space bounding box.  Here
each Pigment part from list_parts is matched to the nearest sidecar part and
the street material stack (same look as tools/town_textures.py street()) is
built on those part masks, exported to scenes/town/textures/<asset>/ and the
project saved to scenes/town/projects/<asset>.pigment.

    python tools/town_junction_textures.py [junction_j1 ...]
    (PIGMENT_MCP=path/to/pigment-mcp.exe overrides the binary)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_textures as tt  # noqa: E402

if os.environ.get("PIGMENT_MCP"):
    tt.MCP = Path(os.environ["PIGMENT_MCP"])
fill = tt.fill


def match_parts(asset):
    side = json.loads((tt.ROOT / "assets" / "town" / f"{asset}.parts.json").read_text(encoding="utf8"))["parts"]
    groups = {}
    for p in tt.parts_of(asset):
        c, s = p["center"], p["size"]
        best = min(side, key=lambda q: sum((a - b) ** 2 for a, b in zip(q["center"], c)) + sum((a - b) ** 2 for a, b in zip(q["size"], s)))
        groups.setdefault(best["kind"], []).append(p["id"])
    return groups


def junction(asset):
    g = match_parts(asset)
    road, curb, walk, paint = (g.get(k, []) for k in ("road", "curb", "walk", "paint"))
    print(asset, {k: len(v) for k, v in g.items()})
    L = [{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": 4096, "material": "Asphalt"}},
         {"tool": "bake", "args": {"curvature_radius": 0.004, "ao_distance": 0.1}},
         fill("Cracks", "Grime", road, {"generator": "scratches", "amount": 0.1, "scale": 1.2}, opacity=0.8),
         fill("Puddles", None, road, {"generator": "grunge", "amount": 0.45, "scale": 0.3, "softness": 0.04},
              values={"base_color": [0.07, 0.07, 0.075], "roughness": 0.015, "height": -0.05}),
         fill("Curbs", "Concrete", curb),
         fill("Paving", "Concrete", walk),
         fill("Paving joints", "Panel seam", walk, {"generator": "panel_lines", "amount": 0.02, "scale": 1.5}),
         fill("Paving grime", "Grime", walk + curb, {"generator": "grunge", "amount": 0.4, "scale": 1.2, "softness": 0.25}, opacity=0.6)]
    if paint:
        L += [fill("Zebra paint", "White plastic", paint, values={"roughness": 0.7}),
              fill("Worn paint", "Asphalt", paint, {"generator": "grunge", "amount": 0.3, "scale": 3.0, "softness": 0.1})]
    L.append(fill("Wet grime", "Grime", road + paint, {"generator": "grunge", "amount": 0.35, "scale": 1.5, "softness": 0.3}, opacity=0.5))
    tt.finish(L, asset)


if __name__ == "__main__":
    tt.TMP.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or sorted(p.stem for p in (tt.ROOT / "assets" / "town").glob("junction_*.glb"))
    for n in names:
        junction(n)
