"""Before/after demo for the weathering generators on the town kit.

Builds Pigment scripts from the committed town scripts (scenes/town/scripts):
"before" = the original stack, "after" = the same stack plus the new
generator layers. Runs them with pigment-mcp --script and renders close-ups
with the render tool into target/pg/.

    python docs/agents/generators/make_demo.py [resolution] [what ...]
    (PIGMENT_MCP overrides the binary, default target/release/pigment-mcp.exe)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
OUT = ROOT / "target" / "pg"
RES = int(sys.argv[1]) if len(sys.argv) > 1 else 2048


def load(asset):
    lines = [json.loads(l) for l in (ROOT / "scenes/town/scripts" / f"{asset}.jsonl").read_text().splitlines() if l.strip()]
    keep = [l for l in lines if l["tool"] not in ("render", "export_textures", "save_project")]
    keep[0]["args"]["resolution"] = RES
    return keep


def layer(name, parts, gen, values, opacity=1.0, channels=None, after=None):
    mask = dict(gen)
    if parts is not None:
        mask["parts"] = parts
    a = {"name": name, "mask": mask, "values": values, "opacity": opacity}
    a["channels"] = channels or {"height": False, "metallic": False}
    return {"tool": "add_layer", "args": a}


def run(lines, label):
    p = OUT / f"demo_{label}.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf8")
    r = subprocess.run([str(MCP), "--script", str(p)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{label}: {r.stderr[-3000:]}")
    print(label, "ok")


def renders(label, views):
    return [{"tool": "render", "args": dict(v, path=str(OUT / f"{label}_{k}.png").replace("\\", "/"))} for k, v in views.items()]


SHELL_A = [1, 39, 40]
BUILDING_VIEWS = {
    "ac": {"yaw": 20, "pitch": 8, "zoom": 2.6, "target": [1.0, 6.5, 5.0], "width": 640, "height": 800, "exposure": -0.3},
    "full": {"yaw": 25, "pitch": 12, "width": 640, "height": 800, "exposure": -0.3},
    "top": {"yaw": 20, "pitch": 55, "zoom": 2.2, "target": [0.0, 4.3, 3.5], "width": 800, "height": 640, "exposure": -0.3},
    "top_rough": {"yaw": 20, "pitch": 55, "zoom": 2.2, "target": [0.0, 4.3, 3.5], "width": 800, "height": 640, "view": "roughness"},
}
STREET_VIEWS = {
    "road": {"yaw": 25, "pitch": 35, "zoom": 1.5, "width": 800, "height": 640, "exposure": -0.3},
    "road_rough": {"yaw": 25, "pitch": 35, "zoom": 1.5, "width": 800, "height": 640, "view": "roughness"},
}


def parts_of_layer(lines, name):
    return next(l["args"]["mask"]["parts"] for l in lines if l["tool"] == "add_layer" and l["args"].get("name") == name)


def building_after(lines):
    ledges = SHELL_A + parts_of_layer(lines, "Trim")
    return [
        layer("Leaks", SHELL_A, {"generator": "leaks", "amount": 0.55, "scale": 2.5, "breakup": 0.6, "drip_length": 3.0, "ao_influence": 0.2, "softness": 0.15},
              {"base_color": [0.05, 0.045, 0.04], "roughness": 0.3}, 0.75),
        layer("Ledge moss", ledges, {"generator": "moss", "amount": 0.4, "scale": 3.0, "breakup": 0.7, "softness": 0.12},
              {"base_color": [0.09, 0.12, 0.05], "roughness": 0.85}, 0.85),
        layer("Rain water", ledges, {"generator": "puddles", "amount": 0.35, "scale": 0.8, "softness": 0.05},
              {"base_color": [0.03, 0.03, 0.032], "roughness": 0.02}, 0.8),
    ]


def street_after(lines):
    """Swap the grunge 'Puddles' layer for the puddles generator plus a wet rim."""
    out = []
    for l in lines:
        if l["tool"] == "add_layer" and l["args"].get("name") == "Puddles":
            road = l["args"]["mask"]["parts"]
            gen = {"generator": "puddles", "scale": 0.35, "breakup": 0.5, "curvature_weight": 1.5}
            out.append(layer("Wet rim", road, dict(gen, amount=0.5, softness=0.12), {"base_color": [0.1, 0.1, 0.105], "roughness": 0.12}, 0.6))
            out.append({"tool": "add_layer", "args": {"name": "Puddles", "mask": dict(gen, parts=road, amount=0.33, softness=0.04),
                                                      "values": {"base_color": [0.07, 0.07, 0.075], "roughness": 0.015, "height": -0.05}}})
        else:
            out.append(l)
    return out


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    what = sys.argv[2:] or ["building", "street"]
    if "building" in what:
        b = load("building_a")
        export0 = [{"tool": "export_textures", "args": {"dir": str(OUT / "building_a_tex_before").replace("\\", "/"), "preset": "separate", "name": "building_a"}}]
        run(b + renders("building_a_before", BUILDING_VIEWS) + export0, "building_a_before")
        export = [{"tool": "export_textures", "args": {"dir": str(OUT / "building_a_tex").replace("\\", "/"), "preset": "separate", "name": "building_a"}}]
        run(b + building_after(b) + renders("building_a_after", BUILDING_VIEWS) + export, "building_a_after")
    if "street" in what:
        s = load("street_segment")
        run(s + renders("street_before", STREET_VIEWS), "street_before")
        run(street_after(s) + renders("street_after", STREET_VIEWS), "street_after")
