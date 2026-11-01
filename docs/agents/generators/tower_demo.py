"""Window grid + tiles demo on a plain tower with no modelled windows.

    blender -b --factory-startup --python docs/agents/generators/make_tower.py -- target/pg/tower.glb
    python docs/agents/generators/tower_demo.py [resolution]

Part ids (list_parts): 0 tower, 1 first-floor ledge, 2 cornice, 3..7 AC units.
Writes target/pg/tower_*.png and exports textures to target/pg/tower_tex/.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
OUT = ROOT / "target" / "pg"
RES = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
TOWER, LEDGES, ACS = [0], [1, 2], [3, 4, 5, 6, 7]
# the shop floor: everything below the 4 m ledge (ground gradient, no breakup)
SHOP = {"generator": "gradient", "amount": 0.14, "softness": 0.003, "breakup": 0.0}
WINDOWS = {"generator": "window_grid", "cell_size": 3.2, "aspect": 0.55, "frame": 0.2, "softness": 0.004, "seed": 7}


def add(name, parts, mask, values=None, material=None, **kw):
    a = {"name": name, "mask": dict(mask, parts=parts)}
    if values:
        a["values"] = values
    if material:
        a["material"] = material
    a.update(kw)
    return {"tool": "add_layer", "args": a}


def script(after):
    L = [{"tool": "new_project", "args": {"mesh": "target/pg/tower.glb", "resolution": RES, "material": "Concrete"}},
         {"tool": "bake", "args": {"curvature_radius": 0.004, "curvature_strength": 0.7, "ao_distance": 0.12}},
         add("Facade paint", TOWER, {}, {"base_color": [0.4, 0.41, 0.43], "roughness": 0.7, "metallic": 0.0}),
         add("AC units", ACS, {}, material="White plastic")]
    if after:
        L += [
            add("Brick base", TOWER, {"generator": "tiles", "variant": "bricks", "scale": 9.0, "aspect": 2.1, "mortar": 0.14, "breakup": 0.5,
                                      "effects": [dict(SHOP, op="multiply")]},
                {"base_color": [0.36, 0.15, 0.1], "roughness": 0.8, "height": 0.15}),
            add("Ledge tiles", LEDGES, {"generator": "tiles", "variant": "square", "scale": 4.0, "aspect": 1.0, "mortar": 0.06, "breakup": 0.6},
                {"base_color": [0.42, 0.42, 0.4], "roughness": 0.55, "height": 0.05}),
            add("Dark glass", TOWER, dict(WINDOWS, amount=1.0, breakup=0.0, effects=[dict(SHOP, op="subtract")]),
                {"base_color": [0.02, 0.025, 0.03], "roughness": 0.05, "metallic": 0.0}, channels={"height": False}),
            add("Lit windows (warm)", TOWER, dict(WINDOWS, amount=0.3, breakup=0.6, effects=[dict(SHOP, op="subtract")]),
                {"base_color": [1.0, 0.72, 0.42], "roughness": 0.1, "emissive": [1.0, 0.72, 0.42], "emissive_strength": 2.4}, channels={"height": False}),
            add("Lit windows (cyan)", TOWER, dict(WINDOWS, amount=0.06, seed=31, effects=[dict(SHOP, op="subtract")]),
                {"base_color": [0.35, 0.85, 1.0], "roughness": 0.1, "emissive": [0.35, 0.85, 1.0], "emissive_strength": 2.2}, channels={"height": False}),
            add("Leaks", TOWER, {"generator": "leaks", "amount": 0.55, "scale": 2.5, "breakup": 0.6, "drip_length": 3.0, "ao_influence": 0.2, "softness": 0.15},
                {"base_color": [0.05, 0.045, 0.04], "roughness": 0.3}, opacity=0.75, channels={"height": False, "metallic": False}),
            add("Ledge moss", TOWER + LEDGES, {"generator": "moss", "amount": 0.45, "scale": 3.0, "breakup": 0.7, "softness": 0.12},
                {"base_color": [0.09, 0.12, 0.05], "roughness": 0.85}, opacity=0.85, channels={"height": False, "metallic": False}),
            add("Rain water", LEDGES, {"generator": "puddles", "amount": 0.4, "scale": 0.8, "softness": 0.05},
                {"base_color": [0.03, 0.03, 0.032], "roughness": 0.02}, opacity=0.8, channels={"height": False, "metallic": False}),
        ]
    tag = "after" if after else "before"
    for k, v in {"front": {"yaw": 10, "pitch": 8, "width": 640, "height": 960, "exposure": -0.6},
                 "close": {"yaw": 25, "pitch": 12, "zoom": 2.6, "target": [0.0, 7.0, 5.0], "width": 800, "height": 800, "exposure": -0.4},
                 "ledge": {"yaw": 25, "pitch": 45, "zoom": 4.0, "target": [0.0, 4.2, 5.0], "width": 800, "height": 640, "exposure": -0.3}}.items():
        L.append({"tool": "render", "args": dict(v, path=str(OUT / f"tower_{tag}_{k}.png").replace("\\", "/"))})
    if after:
        L.append({"tool": "export_textures", "args": {"dir": str(OUT / "tower_tex").replace("\\", "/"), "preset": "separate", "name": "tower"}})
    return L


if __name__ == "__main__":
    for after in (False, True):
        p = OUT / f"tower_{'after' if after else 'before'}.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in script(after)), encoding="utf8")
        r = subprocess.run([str(MCP), "--script", str(p)], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(r.stderr[-3000:])
        print(p.name, "ok")
