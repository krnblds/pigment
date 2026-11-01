"""Layer folders + saved smart materials on the town kit (pigment-mcp --script).

1. Rebuild building_a's stack (from scenes/town/scripts/building_a.jsonl)
   as folders: Shell, Windows, Weathering (with a nested "Wall stains"
   folder) and Signs.
2. Save "Weathering" as scenes/town/smart/weathering.pigsmart.
3. Build building_b without its own weathering, render it, apply the smart
   material, re-target the wall-stain folder to building_b's wall parts and
   render again.

Writes scenes/town/scripts/folders_demo.jsonl and runs it. Renders go to
docs/agents/layer-folders/.

    python tools/folders_demo.py [--res 2048] [--no-run]
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "target" / "release" / "pigment-mcp.exe"
SCRIPTS = ROOT / "scenes" / "town" / "scripts"
DOCS = "docs/agents/layer-folders"
SMART = "scenes/town/smart/weathering.pigsmart"

WINDOWS = {"Dark glass", "Lit windows (warm)", "Lit windows (cyan)", "Lit windows (pink)", "Frames"}
WALL_STAINS = {"Damp patches", "Rain streaks"}
WEATHERING = {"Street grime"} | WALL_STAINS
# (opacity, mask amount) for the weathering layers
BOOST = {"Rain streaks": (0.9, 0.45), "Damp patches": (0.75, 0.55), "Street grime": (1.0, 0.6)}
# building_b's painted walls (the parts its wall weathering used)
B_WALLS = [1, 180, 181, 182]
A_WALLS = [1, 39, 40]


def load(name):
    return [json.loads(l) for l in (SCRIPTS / f"{name}.jsonl").read_text(encoding="utf8").splitlines() if l.strip()]


def layer_calls(name):
    """The add_layer / project_decal calls of a building script."""
    return [c for c in load(name) if c["tool"] in ("add_layer", "project_decal")]


def foldered(calls, walls):
    """add_layer calls with a `parent`; wall stains lose their own part masks
    (the folder above them selects the walls instead)."""
    out = []
    for c in calls:
        a = dict(c["args"])
        if c["tool"] == "project_decal":
            a["layer"] = "Signs/Neon"
            out.append({"tool": "project_decal", "args": a})
            continue
        n = a.get("name")
        if a.get("kind") == "paint":
            continue  # the Signs paint layer is made below, inside its folder
        if n in BOOST:
            # a heavier hand than the town scripts, so the weathering reads in the demo renders
            a["opacity"] = BOOST[n][0]
            a["mask"] = {**a["mask"], "amount": BOOST[n][1]}
        if n in WALL_STAINS:
            a["mask"] = {k: v for k, v in a["mask"].items() if k != "parts"}
            a["parent"] = "Weathering/Wall stains"
        elif n in WEATHERING:
            a["parent"] = "Weathering"
        elif n in WINDOWS:
            a["parent"] = "Windows"
        else:
            a["parent"] = "Shell"
        out.append({"tool": "add_layer", "args": a})
    return out


def script(res):
    view = {"yaw": 25, "pitch": 12, "width": 640, "height": 800, "exposure": -0.3}
    close = {"yaw": 25, "pitch": 4, "zoom": 2.2, "width": 640, "height": 640, "exposure": -0.3}
    s = [
        {"tool": "new_project", "args": {"mesh": "assets/town/building_a.glb", "resolution": res, "material": "Concrete"}},
        {"tool": "bake", "args": {"curvature_radius": 0.004, "curvature_strength": 0.7, "ao_distance": 0.12}},
        {"tool": "delete_layer", "args": {"layer": "Paint"}},
        {"tool": "add_layer", "args": {"kind": "folder", "name": "Shell"}},
        {"tool": "add_layer", "args": {"kind": "folder", "name": "Windows"}},
        {"tool": "add_layer", "args": {"kind": "folder", "name": "Weathering"}},
        {"tool": "add_layer", "args": {"kind": "folder", "name": "Wall stains", "parent": "Weathering", "mask": {"parts": A_WALLS}}},
        {"tool": "add_layer", "args": {"kind": "folder", "name": "Signs"}},
        {"tool": "add_layer", "args": {"kind": "paint", "name": "Neon", "parent": "Signs"}},
    ]
    a = foldered(layer_calls("building_a"), A_WALLS)
    s += [c for c in a if c["tool"] == "add_layer"]
    s += [c for c in a if c["tool"] == "project_decal"]
    s += [
        {"tool": "update_layer", "args": {"layer": "Weathering", "visible": False}},
        {"tool": "render", "args": {**view, "path": f"{DOCS}/building_a_weathering_off.png"}},
        {"tool": "update_layer", "args": {"layer": "Weathering", "visible": True}},
        {"tool": "render", "args": {**view, "path": f"{DOCS}/building_a_folders.png"}},
        {"tool": "list_layers", "args": {"tree": True}},
        {"tool": "save_smart_material", "args": {"layer": "Weathering", "path": SMART}},
        # building_b: its stack without its own weathering...
        {"tool": "new_project", "args": {"mesh": "assets/town/building_b.glb", "resolution": res, "material": "Concrete"}},
        {"tool": "bake", "args": {"curvature_radius": 0.004, "curvature_strength": 0.7, "ao_distance": 0.12}},
        {"tool": "update_layer", "args": {"layer": "Paint", "name": "Signs"}},
    ]
    for c in layer_calls("building_b"):
        a = c["args"]
        if c["tool"] == "add_layer" and (a.get("name") in WEATHERING or a.get("kind") == "paint"):
            continue
        s.append(c)
    s += [
        {"tool": "render", "args": {**view, "path": f"{DOCS}/building_b_before.png"}},
        {"tool": "render", "args": {**close, "path": f"{DOCS}/building_b_before_close.png"}},
        # ...then the saved Weathering, aimed at building_b's walls
        {"tool": "apply_smart_material", "args": {"path": SMART}},
        {"tool": "update_layer", "args": {"layer": "Weathering/Wall stains", "mask": {"parts": B_WALLS}}},
        {"tool": "render", "args": {**view, "path": f"{DOCS}/building_b_after.png"}},
        {"tool": "render", "args": {**close, "path": f"{DOCS}/building_b_after_close.png"}},
        {"tool": "list_layers", "args": {"tree": True}},
    ]
    return s


def main():
    res = int(sys.argv[sys.argv.index("--res") + 1]) if "--res" in sys.argv else 2048
    path = SCRIPTS / "folders_demo.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in script(res)) + "\n", encoding="utf8")
    print("wrote", path)
    if "--no-run" in sys.argv:
        return
    (ROOT / DOCS).mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(MCP), "--script", str(path)], cwd=ROOT, capture_output=True, text=True)
    log = ROOT / "target" / "folders_demo.log"
    log.write_text(r.stdout + r.stderr, encoding="utf8")
    if r.returncode != 0:
        raise SystemExit(r.stderr[-3000:])
    print("ok, log in", log)


if __name__ == "__main__":
    main()
