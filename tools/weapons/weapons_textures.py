"""Texture the Waker's kit in Pigment (pigment-mcp --script).

    python tools/weapons/weapons_textures.py [ids...]        (PIGMENT_MCP=path/to/pigment-mcp.exe to override)

For each weapon in assets/weapons/src/ (tools/weapons/make_weapons.py): asks Pigment for the mesh parts,
matches them to the modelled parts by bounding box, and writes scenes/weapons/scripts/<id>.jsonl:
base materials per part role (gunmetal, steel, polymer, stippled grip polymer, yellow taser polymer,
rubber, brass, cyan / amber emissive strips), a curvature / AO bake, edge wear on metal, scratches,
a Hoshikawa Security mark where there's room, grime, a proof render and a 1024 'separate' texture
export to scenes/weapons/textures/<id>/. Then: blender ... tools/weapons/export_weapons.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "weapons" / "src"
SCRIPTS = ROOT / "scenes" / "weapons" / "scripts"
TEX = ROOT / "scenes" / "weapons" / "textures"
PROOF = ROOT / "scenes" / "weapons" / "proof"
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
IDS = ["stun_baton", "taser", "service_pistol", "smg", "shotgun", "emp"]


def V(c, r=0.5, m=0.0, **kw):
    d = {"base_color": list(c), "roughness": r, "metallic": m}
    d.update(kw)
    return d


ROLES = {
    "gunmetal": V([0.085, 0.09, 0.1], 0.36, 1.0),
    "steel": V([0.42, 0.43, 0.45], 0.3, 1.0),
    "polymer": V([0.032, 0.034, 0.04], 0.58, 0.0),
    "polymer_grip": V([0.028, 0.028, 0.031], 0.82, 0.0),
    "polymer_yellow": V([0.82, 0.58, 0.05], 0.45, 0.0),
    "rubber": V([0.018, 0.018, 0.02], 0.9, 0.0),
    "rubber_dark": V([0.01, 0.01, 0.012], 0.92, 0.0),
    "brass": V([0.78, 0.56, 0.24], 0.32, 1.0),
    "glow_cyan": V([0.08, 0.25, 0.3], 0.3, 0.0, emissive=[0.35, 0.95, 1.0], emissive_strength=4.0),
    "glow_amber": V([0.3, 0.17, 0.04], 0.3, 0.0, emissive=[1.0, 0.6, 0.15], emissive_strength=4.0),
}
METAL = {"gunmetal", "steel", "brass"}


def run(lines, label):
    d = Path(os.environ.get("TEMP", "/tmp")) / "pigment_weapons" if label.startswith("_") else SCRIPTS
    d.mkdir(parents=True, exist_ok=True)
    script = d / f"{label}.jsonl"
    script.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf8")
    r = subprocess.run([str(MCP), "--script", str(script)], cwd=ROOT, capture_output=True, text=True, encoding="utf8")
    if r.returncode != 0:
        raise SystemExit(f"{label}: {r.stdout[-2500:]}\n{r.stderr[-3000:]}")
    return r.stdout


def pigment_parts(mesh, label):
    out = run([{"tool": "new_project", "args": {"mesh": mesh, "resolution": 512}}, {"tool": "list_parts", "args": {}}], f"_parts_{label}")
    s = out[out.index("[list_parts] ") + 13:]
    return json.loads(s[:s.index("\n[")] if "\n[" in s else s)


def match(pparts, records):
    """Pigment part id -> record: the record box that holds the part best (centre + size distance)."""
    out = {}
    for q in pparts:
        best = min(records, key=lambda r: sum(abs(q["center"][i] - r["center"][i]) + 0.5 * abs(q["size"][i] - r["size"][i]) for i in range(3)))
        out[q["id"]] = best
    return out


def script_for(wid):
    meta = json.loads((SRC / f"{wid}.json").read_text())
    mesh = f"assets/weapons/src/{wid}.glb"
    pp = pigment_parts(mesh, wid)
    if isinstance(pp, dict):
        pp = pp.get("parts", [])
    m = match(pp, meta["parts"])
    by_role = {}
    for pid, rec in m.items():
        by_role.setdefault(rec["role"], []).append(pid)
    L = [{"tool": "new_project", "args": {"mesh": mesh, "resolution": 1024}},
         {"tool": "bake", "args": {"curvature_radius": 0.002, "ao_distance": 0.03}}]
    for role, parts in sorted(by_role.items()):
        L.append({"tool": "add_layer", "args": {"name": role, "mask": {"parts": sorted(parts)}, "values": ROLES[role]}})
        if role == "polymer_grip":
            L.append({"tool": "add_layer", "args": {"name": "grip stipple", "mask": {"parts": sorted(parts), "generator": "grunge", "amount": 0.55, "scale": 40.0, "softness": 0.1},
                                                     "values": {"base_color": [0.05, 0.05, 0.055], "roughness": 0.95}, "opacity": 0.8, "channels": {"height": False}}})
    metal = sorted(p for r, ps in by_role.items() if r in METAL for p in ps)
    if metal:
        L.append({"tool": "add_layer", "args": {"name": "Edge wear", "mask": {"parts": metal, "generator": "edge_wear", "amount": 0.32, "softness": 0.15, "scale": 8.0, "breakup": 0.6},
                                                 "values": {"base_color": [0.62, 0.62, 0.64], "roughness": 0.28, "metallic": 1.0}, "opacity": 0.75, "channels": {"height": False}}})
        L.append({"tool": "add_layer", "args": {"name": "Scratches", "mask": {"parts": metal, "generator": "scratches", "amount": 0.15, "scale": 22.0},
                                                 "values": {"base_color": [0.5, 0.5, 0.52], "roughness": 0.25, "metallic": 1.0}, "opacity": 0.3, "channels": {"height": False}}})
    poly = sorted(p for r, ps in by_role.items() if r.startswith("polymer") for p in ps)
    if poly:
        L.append({"tool": "add_layer", "args": {"name": "Polymer scuffs", "mask": {"parts": poly, "generator": "edge_wear", "amount": 0.25, "softness": 0.3, "scale": 6.0},
                                                 "values": {"base_color": [0.12, 0.12, 0.13], "roughness": 0.7}, "opacity": 0.6, "channels": {"height": False}}})
    L.append({"tool": "add_layer", "args": {"name": "Grime", "material": "Grime", "mask": {"generator": "grunge", "amount": 0.3, "scale": 5.0, "softness": 0.4}, "opacity": 0.3}})
    PROOF.mkdir(parents=True, exist_ok=True)
    L.append({"tool": "render", "args": {"yaw": 70, "pitch": 12, "width": 640, "height": 400, "exposure": 0.2, "path": str(PROOF / f"{wid}.png")}})
    L.append({"tool": "export_textures", "args": {"dir": f"scenes/weapons/textures/{wid}", "preset": "separate", "name": wid}})
    return L


def main():
    ids = sys.argv[1:] or IDS
    for wid in ids:
        out = run(script_for(wid), wid)
        print(wid, "ok", (TEX / wid).exists())


if __name__ == "__main__":
    main()
