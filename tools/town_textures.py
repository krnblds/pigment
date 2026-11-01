"""Texture the cyberpunk town kit with Pigment (via pigment-mcp --script).

For each asset: list its parts, classify them by shape (glass, frames, AC
units, LED strips, shell, trim...), write a Pigment script that builds the
material stack with part masks and decals, run it, export textures for
Blender and save the Pigment project.

    python tools/town_textures.py [asset ...]
"""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "showcase" / "release" / "pigment-mcp.exe"))
OUT = ROOT / "scenes" / "town"
DECALS = "assets/decals/"
TMP = Path.home() / "AppData" / "Local" / "Temp" / "pig"


def run(lines, label):
    script = TMP / f"town_{label}.jsonl"
    script.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf8")
    r = subprocess.run([str(MCP), "--script", str(script)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{label}: {r.stderr[-2000:]}")
    return r.stdout


def parts_of(asset):
    out = run([{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": 512}}, {"tool": "list_parts", "args": {}}], f"{asset}_parts")
    return json.loads(out[out.index("[list_parts] ") + 13:])


def classify(p):
    s = sorted(p["size"])
    t = p["triangles"]
    if t <= 2 or s[1] < 0.005:
        return "wire"
    if s[0] < 0.12 and s[1] >= 3.0 and s[2] >= 6.0:
        return "panel"            # billboard faces, big flat panels
    if s[0] <= 0.015 and s[1] >= 0.25:
        return "glass"
    if s[0] <= 0.12 and s[1] <= 0.12 and s[2] >= 3.0:
        return "led"
    if 0.03 <= s[0] <= 0.09 and s[1] >= 0.8 and t >= 200:
        return "frame"
    if abs(s[0] - 0.32) < 0.03 and abs(s[2] - 0.82) < 0.05:
        return "ac"
    if abs(s[1] - 0.46) < 0.03 and t > 800:
        return "grille"
    if s[2] >= 8.0 and s[1] >= 8.0:
        return "shell"
    return "trim"


def fill(name, material=None, parts=None, gen=None, **kw):
    a = {"name": name}
    if material:
        a["material"] = material
    m = {}
    if parts is not None:
        m["parts"] = parts
    if gen:
        m.update(gen)
    if m:
        a["mask"] = m
    a.update(kw)
    return {"tool": "add_layer", "args": a}


def weathering(shell):
    return [
        fill("Damp patches", "Wet concrete", shell, {"generator": "grunge", "amount": 0.45, "scale": 0.7, "softness": 0.25}, opacity=0.5, channels={"height": False, "metallic": False}),
        fill("Rain streaks", "Grime", shell, {"generator": "streaks", "amount": 0.3, "scale": 2.0, "softness": 0.15}, opacity=0.5),
        fill("Street grime", "Grime", None, {"generator": "dirt", "amount": 0.5, "softness": 0.25, "breakup": 0.5,
                                             "effects": [{"generator": "gradient", "op": "max", "amount": 0.12, "breakup": 0.5}]}, opacity=0.8),
    ]


def windows(glass, seed):
    rng = random.Random(seed)
    rng.shuffle(glass)
    n = len(glass)
    warm, cyan, pink = glass[: int(n * 0.32)], glass[int(n * 0.32): int(n * 0.40)], glass[int(n * 0.40): int(n * 0.43)]
    L = [fill("Dark glass", None, glass, values={"base_color": [0.02, 0.025, 0.03], "roughness": 0.04, "metallic": 0.0}, channels={"height": False})]
    for name, parts, col, k in (("Lit windows (warm)", warm, [1.0, 0.72, 0.42], 2.4), ("Lit windows (cyan)", cyan, [0.35, 0.85, 1.0], 2.2), ("Lit windows (pink)", pink, [1.0, 0.3, 0.7], 2.2)):
        if parts:
            L.append(fill(name, None, parts, values={"base_color": col, "roughness": 0.1, "metallic": 0.0, "emissive": col, "emissive_strength": k}, channels={"height": False}))
    return L


def common(c, seed):
    L = []
    L += windows(list(c.get("glass", [])), seed)
    if c.get("frame"):
        L.append(fill("Frames", "Matte black", c["frame"]))
    if c.get("panel"):
        L.append(fill("Screens", None, c["panel"], values={"base_color": [0.012, 0.012, 0.015], "roughness": 0.08, "metallic": 0.0}, channels={"height": False}))
    if c.get("trim"):
        L.append(fill("Trim", "Gunmetal", c["trim"]))
    if c.get("door"):
        L.append(fill("Doors", None, c["door"], values={"base_color": [0.11, 0.12, 0.13], "roughness": 0.45, "metallic": 0.6}))
        L.append(fill("Door scuffs", "Steel", c["door"], {"generator": "edge_wear", "amount": 0.25, "scale": 20.0, "breakup": 0.7, "softness": 0.05}))
    if c.get("roof"):
        L.append(fill("Rooftop metal", None, c["roof"], values={"base_color": [0.32, 0.33, 0.34], "roughness": 0.55, "metallic": 0.8}))
        L.append(fill("Rooftop rust streaks", "Rust", c["roof"], {"generator": "streaks", "amount": 0.18, "scale": 3.0, "softness": 0.2}, opacity=0.6))
    if c.get("ac"):
        L.append(fill("AC units", "White plastic", c["ac"]))
    if c.get("grille"):
        L.append(fill("Grilles", "Dark iron", c["grille"]))
    if c.get("wire"):
        L.append(fill("Cables", "Matte black", c["wire"]))
    if c.get("led"):
        leds = c["led"]
        L.append(fill("LED strips (cyan)", "Neon cyan", leds[0::2], values={"emissive_strength": 5.0}))
        if leds[1::2]:
            L.append(fill("LED strips (pink)", "Neon pink", leds[1::2], values={"emissive_strength": 5.0}))
    return L


def building(asset, base, shell_extra, signs, seed):
    parts = parts_of(asset)
    c = {}
    shells = [p for p in parts if classify(p) == "shell"]
    roof_y = max(p["center"][1] + p["size"][1] / 2 for p in shells) - 0.6
    for p in parts:
        k = classify(p)
        if k == "trim":
            s = sorted(p["size"])
            bottom = p["center"][1] - p["size"][1] / 2
            if s[0] <= 0.08 and 0.9 <= s[1] <= 1.4 and 2.2 <= s[2] <= 2.7 and bottom < 0.6:
                k = "door"
            elif bottom >= roof_y:
                k = "roof"
        c.setdefault(k, []).append(p["id"])
    sel = lambda k: [i for i in c.get(k, []) if i < 256]
    c = {k: sel(k) for k in c}
    shell = c.get("shell", [])
    L = [{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": 4096, "material": base}},
         {"tool": "bake", "args": {"curvature_radius": 0.004, "curvature_strength": 0.7, "ao_distance": 0.12}}]
    L += shell_extra(shell)
    L += common(c, seed)
    L += weathering(shell)
    if signs:
        L.append({"tool": "add_layer", "args": {"kind": "paint", "name": "Signs"}})
        for s in signs:
            L.append({"tool": "project_decal", "args": dict(s, layer="Signs")})
    return L, c


def finish(L, asset):
    T = str(TMP).replace("\\", "/")
    L += [
        {"tool": "render", "args": {"yaw": 25, "pitch": 12, "width": 640, "height": 800, "exposure": -0.3, "path": f"{T}/town_tex_{asset}_a.png"}},
        {"tool": "render", "args": {"yaw": -50, "pitch": 18, "width": 640, "height": 800, "exposure": -0.3, "path": f"{T}/town_tex_{asset}_b.png"}},
        {"tool": "export_textures", "args": {"dir": f"scenes/town/textures/{asset}", "preset": "separate", "name": asset}},
        {"tool": "save_project", "args": {"path": f"scenes/town/projects/{asset}.pigment"}},
    ]
    (OUT / "scripts").mkdir(parents=True, exist_ok=True)
    (OUT / "scripts" / f"{asset}.jsonl").write_text("\n".join(json.dumps(l) for l in L), encoding="utf8")
    out = run(L, asset)
    scale = [line for line in out.splitlines() if "emissive_scale" in line]
    print(asset, "ok", scale[-1].strip() if scale else "")


def build_a():
    shell_extra = lambda shell: [fill("Slab joints", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.012, "scale": 0.6})]
    signs = [{"image": DECALS + "neon_dennou.png", "part": 154, "fit": "contain", "tint": [1.0, 0.25, 0.65], "emissive_strength": 6.0}]
    L, _ = building("building_a", "Concrete", shell_extra, signs, 1)
    finish(L, "building_a")


def build_b():
    def shell_extra(shell):
        wear = {"generator": "edge_wear", "amount": 0.5, "scale": 18.0, "breakup": 0.8, "softness": 0.05}
        return [fill("Teal paint", "Teal paint", shell),
                fill("Panel seams", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.01, "scale": 0.8}),
                fill("Chipped paint", "Steel", shell, wear, values={"height": -0.3})]
    signs = [{"image": DECALS + "poster_yume.png", "part": 183, "fit": "contain", "emissive_strength": 2.5},
             {"image": DECALS + "neon_noodles_24h.png", "part": 5, "fit": "contain", "tint": [1.0, 0.55, 0.1], "emissive_strength": 6.0},
             {"image": DECALS + "neon_ramen.png", "part": 18, "fit": "contain", "tint": [1.0, 0.2, 0.25], "emissive_strength": 6.0}]
    L, _ = building("building_b", "Concrete", shell_extra, signs, 2)
    finish(L, "building_b")


def build_c():
    def shell_extra(shell):
        return [fill("Steel cladding", None, shell, values={"base_color": [0.2, 0.21, 0.23], "roughness": 0.5, "metallic": 0.7}),
                fill("Cladding seams", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.008, "scale": 0.5}),
                fill("Scratches", "Brushed steel", shell, {"generator": "scratches", "amount": 0.08, "scale": 3.0}, opacity=0.35)]
    signs = [{"image": DECALS + "logo_hoshikawa_dynamics.png", "part": 0, "fit": "contain", "tint": [0.9, 0.95, 1.0], "emissive_strength": 2.0}]
    L, _ = building("building_c", "Concrete", shell_extra, signs, 3)
    finish(L, "building_c")


def street(asset):
    parts = parts_of(asset)
    road, curb, walk, iron, stripes = [], [], [], [], []
    for p in parts:
        s = sorted(p["size"])
        if s[0] <= 0.015:
            stripes.append(p["id"])
        elif s[2] <= 1.0:
            iron.append(p["id"])
        elif s[0] >= 0.19 and s[0] <= 0.21 and s[1] >= 7.9:
            road.append(p["id"])
        elif s[1] <= 0.4:
            curb.append(p["id"])
        else:
            walk.append(p["id"])
    L = [{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": 4096, "material": "Asphalt"}},
         {"tool": "bake", "args": {"curvature_radius": 0.004, "ao_distance": 0.1}},
         fill("Cracks", "Grime", road, {"generator": "scratches", "amount": 0.1, "scale": 1.2}, opacity=0.8),
         fill("Puddles", None, road, {"generator": "grunge", "amount": 0.45, "scale": 0.3, "softness": 0.04}, values={"base_color": [0.07, 0.07, 0.075], "roughness": 0.015, "height": -0.05}),
         fill("Curbs", "Concrete", curb),
         fill("Paving", "Concrete", walk),
         fill("Paving joints", "Panel seam", walk, {"generator": "panel_lines", "amount": 0.02, "scale": 1.5}),
         fill("Paving grime", "Grime", walk + curb, {"generator": "grunge", "amount": 0.4, "scale": 1.2, "softness": 0.25}, opacity=0.6),
         fill("Iron covers", "Dark iron", iron),
         fill("Cover rust", "Rust", iron, {"generator": "spots", "amount": 0.35, "scale": 8.0})]
    if stripes:
        L += [fill("Zebra paint", "White plastic", stripes, values={"roughness": 0.7}),
              fill("Worn paint", "Asphalt", stripes, {"generator": "grunge", "amount": 0.3, "scale": 3.0, "softness": 0.1})]
    L.append(fill("Wet grime", "Grime", road, {"generator": "grunge", "amount": 0.35, "scale": 1.5, "softness": 0.3}, opacity=0.5))
    finish(L, asset)


def small(asset, base, extra):
    parts = parts_of(asset)
    L = [{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": 1024, "material": base}}]
    L += extra(parts)
    L.append(fill("Grime", "Grime", None, {"generator": "dirt", "amount": 0.5, "softness": 0.25, "effects": [{"generator": "gradient", "op": "max", "amount": 0.15}]}, opacity=0.7))
    finish(L, asset)


def lamp_extra(parts):
    glass = [p["id"] for p in parts if sorted(p["size"])[0] <= 0.03 and sorted(p["size"])[1] >= 0.1]
    return [fill("Lens", "LED white", glass, values={"emissive_strength": 8.0})] if glass else []


def pole_extra(parts):
    small_parts = [p["id"] for p in parts if max(p["size"]) <= 0.35]
    return [fill("Insulators", "White plastic", small_parts)]


def sign_extra(parts):
    faces = [p for p in parts if sorted(p["size"])[0] <= 0.03 and sorted(p["size"])[1] >= 0.8]
    L = [{"tool": "add_layer", "args": {"kind": "paint", "name": "Sign faces"}}]
    for f, img, col in zip(faces, ["neon_bar.png", "neon_open.png"], [[0.2, 0.9, 1.0], [1.0, 0.25, 0.6]]):
        L.append({"tool": "project_decal", "args": {"layer": "Sign faces", "image": DECALS + img, "part": f["id"], "fit": "contain", "tint": col, "emissive_strength": 6.0}})
    return L


if __name__ == "__main__":
    TMP.mkdir(parents=True, exist_ok=True)
    jobs = {
        "building_a": build_a,
        "building_b": build_b,
        "building_c": build_c,
        "street_segment": lambda: street("street_segment"),
        "crossroad": lambda: street("crossroad"),
        "street_lamp": lambda: small("street_lamp", "Gunmetal", lamp_extra),
        "power_pole": lambda: small("power_pole", "Concrete", pole_extra),
        "overhead_sign": lambda: small("overhead_sign", "Gunmetal", sign_extra),
    }
    for name in sys.argv[1:] or jobs:
        jobs[name]()
