"""Brush engine on town building_a (before / after).

Writes scenes/town/scripts/parity_brush_demo.jsonl, runs it with
target/release/pigment-mcp.exe and composes docs/agents/parity/brush_before_after.png.

    python docs/agents/parity/brush_demo.py [resolution]

On a "Brushwork" paint layer over the town stack:
  - spray paint through a screen-space stencil (the crossed-eye UNPLUG mark);
  - part of the mark cloned onto the pillar beside it (clone tool);
  - a mirrored tag (symmetry X through the building's centre);
  - cracks (tip, random angle, painted height);
  - paint splatter on the shutter box (tip + position / size jitter);
  - scratches whose angle follows the stroke;
  - a pressure-ramped grime streak (pressure drives the size);
  - fallen leaves along the pavement edge (leaves tip, jitter).
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/agents/parity"
SCRIPT = ROOT / "scenes/town/scripts/parity_brush_demo.jsonl"
RES = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
CAM = {"yaw": 0, "pitch": 5, "target": [0, 3, 0], "distance": 12, "width": 960, "height": 720}
SKIP = {"export_textures", "export_variants", "save_project", "render"}


def stroke(points, **kw):
    return {"tool": "paint_stroke", "args": {**CAM, "layer": "Brushwork", "points": points, **kw}}


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
    render = lambda name: {"tool": "render", "args": {**CAM, "path": f"target/pd/{name}.png"}}
    lines.append(render("brush_before"))
    lines.append({"tool": "add_layer", "args": {"kind": "paint", "name": "Brushwork"}})
    pink = {"base_color": [1.0, 0.12, 0.55], "roughness": 0.6}
    # stencilled spray: many soft spray passes over the stencil
    stencil = {"image": "assets/decals/story/stencil_eye_crossed.png", "center": [0.86, 0.47], "scale": 0.3}
    for y in (0.38, 0.43, 0.48, 0.53, 0.58):
        lines.append(stroke([[0.74, y], [0.98, y]], size=90, tip="spray", spacing=0.15, values=pink, channels=["base_color", "roughness"], stencil=stencil))
    # clone part of the mark onto the pillar left of it (same UV island)
    lines.append(stroke([[0.68, 0.42], [0.69, 0.5], [0.68, 0.58]], size=70, tool="clone", clone_source=[0.8, 0.42], channels=["base_color", "roughness"]))
    # a mirrored tag: symmetry across the building's centre plane (x = 0)
    lines.append(stroke([[0.12, 0.66], [0.16, 0.6], [0.2, 0.67], [0.24, 0.61], [0.28, 0.66]], size=10, values={"base_color": [0.1, 0.9, 1.0], "roughness": 0.5},
                        channels=["base_color", "roughness"], symmetry={"x": True}, pressure=[0.4, 1.0, 0.7, 1.0, 0.5]))
    # cracks with random angles, recessed
    for p in ([0.36, 0.08], [0.82, 0.12], [0.93, 0.66], [0.05, 0.12]):
        lines.append(stroke([p], size=150, tip="cracks", jitter={"angle": 180}, seed=int(p[0] * 100), values={"base_color": [0.12, 0.11, 0.1], "height": -0.6, "roughness": 0.9},
                            channels=["base_color", "height", "roughness"], hardness=1.0))
    # splatter on the shutter box
    lines.append(stroke([[0.1, 0.4], [0.3, 0.42], [0.5, 0.39]], size=70, tip="splatter", spacing=1.2, jitter={"position": 0.6, "size": 0.6, "angle": 180},
                        values={"base_color": [0.95, 0.85, 0.1], "roughness": 0.4}, channels=["base_color", "roughness"]))
    # scratches following the stroke
    lines.append(stroke([[0.05, 0.75], [0.25, 0.73], [0.45, 0.76]], size=60, tip="scratches", follow_angle=True, spacing=0.6,
                        values={"base_color": [0.75, 0.75, 0.73], "roughness": 0.3, "metallic": 1.0}, channels=["base_color", "roughness", "metallic"]))
    # pressure-ramped grime streak down the wall
    lines.append(stroke([[0.66, 0.2], [0.665, 0.4], [0.67, 0.6], [0.672, 0.8]], size=28, pressure=[0.05, 0.4, 1.0, 0.6], flow=0.35,
                        values={"base_color": [0.05, 0.04, 0.03], "roughness": 0.9}, channels=["base_color", "roughness"]))
    # leaves along the bottom edge
    lines.append(stroke([[0.02, 0.97], [0.5, 0.98], [0.98, 0.97]], size=60, tip="leaves", spacing=0.9, jitter={"angle": 180, "position": 0.4, "size": 0.4},
                        values={"base_color": [0.45, 0.27, 0.08], "roughness": 0.8}, channels=["base_color", "roughness"]))
    lines.append(render("brush_after"))
    SCRIPT.write_text("\n".join(json.dumps(c) for c in lines) + "\n")
    subprocess.run([str(ROOT / "target/release/pigment-mcp.exe"), "--script", str(SCRIPT)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    from PIL import Image, ImageDraw
    tmp = ROOT / "target/pd"
    a, b = Image.open(tmp / "brush_before.png"), Image.open(tmp / "brush_after.png")
    w, h = a.size
    out = Image.new("RGB", (w * 2, h), "black")
    out.paste(a, (0, 0))
    out.paste(b, (w, 0))
    d = ImageDraw.Draw(out)
    d.text((12, 10), "before: town stack", fill="white")
    d.text((w + 12, 10), "after: stencil spray, clone, mirrored tag, crack / splatter / scratch / leaf tips, pressure streak", fill="white")
    out = out.resize((w * 2 * 3 // 4, h * 3 // 4), Image.LANCZOS)
    out.save(OUT / "brush_before_after.png", optimize=True)
    print("wrote", OUT / "brush_before_after.png")


if __name__ == "__main__":
    main()
