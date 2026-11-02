"""UDIM / texture sets on town building_a: more texel density for street-level posters.

    python docs/agents/parity/udim_demo.py [resolution]

Before: the town script as is (one 4096 texture for the whole 26 m building).
After: the same script, but `new_project` moves the ground floor (below 3.6 m)
to UDIM tile 1002 with its UV islands repacked to fill the tile, giving two
texture sets (tile_1001, tile_1002) of 4096 each. Every layer / decal / bake
call runs on both sets (`texture_set: "*"`). Close-ups of the poster wall.
Writes scenes/town/scripts/parity_udim_demo.jsonl and docs/agents/parity/udim_before_after.png.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/agents/parity"
SCRIPT = ROOT / "scenes/town/scripts/parity_udim_demo.jsonl"
RES = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
SKIP = {"export_textures", "export_variants", "save_project", "render"}
SET_TOOLS = {"add_layer", "update_layer", "delete_layer", "add_smart_material", "apply_smart_material", "add_filter", "update_filter", "remove_filter", "set_anchor", "project_decal", "scatter_decals", "bake"}
CAMS = {"close": {"yaw": -90, "pitch": 4, "target": [-4.4, 1.55, -1.0], "distance": 2.6, "width": 900, "height": 700},
        "wide": {"yaw": -60, "pitch": 8, "target": [-3.0, 3.0, 0.0], "distance": 13, "width": 900, "height": 700}}


def town_calls(udim):
    out = []
    for raw in (ROOT / "scenes/town/scripts/building_a.jsonl").read_text().splitlines():
        if not raw.strip():
            continue
        c = json.loads(raw)
        if c["tool"] in SKIP:
            continue
        if c["tool"] == "new_project":
            c["args"]["resolution"] = RES
            if udim:
                c["args"]["udim_tiles"] = [{"tile": 1002, "below_y": 3.6, "margin": 0.004}]
        elif udim and c["tool"] in SET_TOOLS:
            c["args"]["texture_set"] = "*"
        out.append(c)
    return out


def main():
    lines = town_calls(False)
    for k, cam in CAMS.items():
        lines.append({"tool": "render", "args": {**cam, "path": f"target/pd/udim_before_{k}.png"}})
    lines += town_calls(True)
    lines.append({"tool": "list_texture_sets", "args": {}})
    for k, cam in CAMS.items():
        lines.append({"tool": "render", "args": {**cam, "path": f"target/pd/udim_after_{k}.png"}})
    lines.append({"tool": "export_textures", "args": {"dir": "target/pd/udim_export", "preset": "separate", "name": "building_a"}})
    SCRIPT.write_text("\n".join(json.dumps(c) for c in lines) + "\n")
    r = subprocess.run([str(ROOT / "target/release/pigment-mcp.exe"), "--script", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
    print(r.stderr[-1500:])
    r.check_returncode()
    for line in r.stdout.splitlines():
        if "density_gain" in line or "udim_tiles" in line:
            print(line.strip())
    from PIL import Image, ImageDraw
    tmp = ROOT / "target/pd"
    a, b = Image.open(tmp / "udim_before_close.png"), Image.open(tmp / "udim_after_close.png")
    wa, wb = Image.open(tmp / "udim_before_wide.png"), Image.open(tmp / "udim_after_wide.png")
    w, h = a.size
    out = Image.new("RGB", (w * 2, h * 2), "black")
    out.paste(a, (0, 0))
    out.paste(b, (w, 0))
    out.paste(wa, (0, h))
    out.paste(wb, (w, h))
    d = ImageDraw.Draw(out)
    d.text((12, 10), f"before: one {RES} texture for the whole building", fill="white")
    d.text((w + 12, 10), f"after: ground floor on UDIM 1002 (islands repacked), two {RES} texture sets", fill="white")
    d.text((12, h + 10), "same stack, wide view: before", fill="white")
    d.text((w + 12, h + 10), "after (generators, leaks, decals carry over)", fill="white")
    out = out.resize((w * 3 // 2, h * 3 // 2), Image.LANCZOS)
    out.save(OUT / "udim_before_after.png", optimize=True)
    print("wrote", OUT / "udim_before_after.png")


if __name__ == "__main__":
    main()
