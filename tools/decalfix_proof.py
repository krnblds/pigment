"""Close-up renders of one texture variant (docs/agents/decalfix proof shots).

Replays an asset's town script (scenes/town/scripts/<asset>.jsonl, written by
tools/town_textures.py) with only the chosen variant's story decals switched on,
then renders Pigment close-ups aimed at world points:

    python tools/decalfix_proof.py building_a soba out_dir  name:yaw:pitch:x:y:z:distance ...
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import town_textures as T  # noqa: E402


def variant_script(asset, variant):
    lines = [json.loads(l) for l in (ROOT / "scenes" / "town" / "scripts" / f"{asset}.jsonl").read_text(encoding="utf8").splitlines() if l.strip()]
    defs = next(l["args"]["variants"] for l in lines if l["tool"] == "export_variants")
    d = next(x for x in defs if x["name"] == variant)
    on = set(d["enable"])
    out = []
    for l in lines:
        if l["tool"] in ("render", "export_variants", "export_textures", "save_project"):
            continue
        a = l["args"]
        if l["tool"] in ("project_decal", "scatter_decals") and a.get("variant") == "story":
            a = dict(a, enabled=a["name"] in on)
        if l["tool"] == "add_layer" and a.get("variant") in ("lights", "lights_few"):
            few = "lights_few" in on
            a = dict(a, visible=(a["variant"] == "lights_few") == few)
        out.append({"tool": l["tool"], "args": a})
    return out


def main(asset, variant, out_dir, shots):
    L = variant_script(asset, variant)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in shots:
        name, yaw, pitch, x, y, z, dist = s.split(":")
        L.append({"tool": "render", "args": {"yaw": float(yaw), "pitch": float(pitch), "target": [float(x), float(y), float(z)], "distance": float(dist),
                                             "width": 960, "height": 640, "exposure": float(os.environ.get("PROOF_EV", "-0.2")), "lighting": os.environ.get("PROOF_LIGHT", "night"), "bloom": True,
                                             "path": str((out_dir / f"{name}.png").resolve()).replace("\\", "/")}})
    T.TMP.mkdir(parents=True, exist_ok=True)
    T.run(L, f"proof_{asset}_{variant}")
    print("rendered", len(shots), "shots of", asset, variant)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
