"""Texture the Kanzaki Tsubame-4 cruiser in Pigment (via pigment-mcp --script).

Reads assets/car/src/car_parts.json (written by build_car.py: every named
piece with its group and bounding box), matches Pigment's parts to those
pieces (each Pigment part lies inside exactly one piece's box), and writes
two Pigment scripts:

    scenes/car/scripts/car_body.jsonl   4K body: candy clearcoat paint with flake, two
                                        liveries as variants (Hoshikawa Security / Koen Cab),
                                        edge chips, coat haze, rain streaks, road dirt from
                                        the sills, rust round the arches, chrome / black trim,
                                        tinted glass, emissive lamps, cloth / leather interior,
                                        livery + story decals
    scenes/car/scripts/car_wheel.jsonl  2K wheel: dusty tyre with sidewall lettering, painted
                                        alloy with brake dust, rusty disc, painted caliper

then runs them. Outputs:
    scenes/car/projects/car_body.pigment, car_wheel.pigment
    scenes/car/textures/car_body__security/, car_body__cab/, car_wheel/   (git-ignored)
    docs/agents/car/pigment_*.png                                           (renders)

    python tools/car/car_textures.py [body] [wheel] [--no-run]
    PIGMENT_MCP=path/to/pigment-mcp.exe python tools/car/car_textures.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
SRC = ROOT / "assets" / "car" / "src"
SCRIPTS = ROOT / "scenes" / "car" / "scripts"
PROJECTS = "scenes/car/projects"
TEXTURES = "scenes/car/textures"
DOCS = "docs/agents/car"
DEC = "assets/decals/car/"
STORY = "assets/decals/story/"
TMP = Path(os.environ.get("TEMP", "/tmp")) / "pig_car"


# ------------------------------------------------------------------ running pigment-mcp


def run(lines, label, keep=None):
    TMP.mkdir(parents=True, exist_ok=True)
    script = Path(keep) if keep else TMP / f"{label}.jsonl"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf8")
    r = subprocess.run([str(MCP), "--script", str(script)], cwd=ROOT, capture_output=True, text=True, encoding="utf8")
    if r.returncode != 0:
        raise SystemExit(f"{label}: {r.stdout[-1500:]}\n{r.stderr[-3000:]}")
    return r.stdout


def pigment_parts(mesh):
    out = run([{"tool": "new_project", "args": {"mesh": mesh, "resolution": 512}}, {"tool": "list_parts", "args": {}}], "parts")
    s = out[out.index("[list_parts] ") + 13:]
    return json.loads(s[:s.index("\n[")] if "\n[" in s else s)


def match_parts(pparts, records):
    """Pigment part id -> (piece name, group): the smallest piece whose box holds the part."""
    pieces = [(r["name"], r["group"], p) for r in records for p in r["pieces"]]

    def box(c, s, e=0.0):
        return [c[i] - s[i] / 2 - e for i in range(3)], [c[i] + s[i] / 2 + e for i in range(3)]
    out = {}
    for q in pparts:
        qlo, qhi = box(q["center"], q["size"])
        best = None
        for nm, g, p in pieces:
            lo, hi = box(p["center"], p["size"], 0.003)
            if all(lo[i] <= qlo[i] and qhi[i] <= hi[i] for i in range(3)):
                vol = 1.0
                for i in range(3):
                    vol *= max(p["size"][i], 1e-3)
                if best is None or vol < best[0]:
                    best = (vol, nm, g)
        if best is None:
            raise SystemExit(f"Pigment part {q['id']} (centre {q['center']}) matches no piece in car_parts.json: rebuild the model")
        out[q["id"]] = (best[1], best[2])
    return out


class Parts:
    def __init__(self, mapping):
        self.m = mapping

    def group(self, *groups):
        return sorted(i for i, (n, g) in self.m.items() if g in groups)

    def named(self, *prefixes):
        return sorted(i for i, (n, g) in self.m.items() if any(n.startswith(p) for p in prefixes))

    def without(self, ids, *prefixes):
        return [i for i in ids if not any(self.m[i][0].startswith(p) for p in prefixes)]


# ------------------------------------------------------------------ layer helpers


def fill(name, parts=None, values=None, *extra, **kw):
    """extra: a material preset name (str) and / or a generator mask (dict), in any order."""
    material = next((e for e in extra if isinstance(e, str)), None)
    gen = next((e for e in extra if isinstance(e, dict)), None)
    a = {"name": name}
    if material:
        a["material"] = material
    if values:
        a["values"] = values
    m = {}
    if parts is not None:
        if not parts:
            raise SystemExit(f"layer {name!r}: empty part selection")
        m["parts"] = parts
    if gen:
        m.update(gen)
    if m:
        a["mask"] = m
    a.update(kw)
    return {"tool": "add_layer", "args": a}


def decal(image, pos, normal, size, **kw):
    a = {"image": image, "position": pos, "normal": normal, "size": size}
    a.update(kw)
    return {"tool": "project_decal", "args": a}


def part_decal(image, part, **kw):
    a = {"image": image, "part": part}
    a.update(kw)
    return {"tool": "project_decal", "args": a}


def bl(x, y, z):
    """Blender car coordinates (front -Y, Z up) -> Pigment / glTF world (Y up, front +Z)."""
    return [round(x, 4), round(z, 4), round(-y, 4)]


NO_HEIGHT = {"height": False}

# ------------------------------------------------------------------ materials (values)

MIDNIGHT_CANDY = {"base_color": [0.018, 0.035, 0.11], "metallic": 0.55, "roughness": 0.33, "coat": 1.0, "coat_roughness": 0.03, "flake": 0.55}
PEARL_WHITE = {"base_color": [0.86, 0.87, 0.88], "metallic": 0.15, "roughness": 0.3, "coat": 1.0, "coat_roughness": 0.03, "flake": 0.2}
TEAL_CANDY = {"base_color": [0.02, 0.17, 0.17], "metallic": 0.55, "roughness": 0.32, "coat": 1.0, "coat_roughness": 0.03, "flake": 0.5}
CREAM_PAINT = {"base_color": [0.78, 0.72, 0.58], "metallic": 0.1, "roughness": 0.34, "coat": 1.0, "coat_roughness": 0.04, "flake": 0.1}
BLACK_TRIM = {"base_color": [0.022, 0.022, 0.024], "metallic": 0.0, "roughness": 0.55}
SATIN_BLACK_METAL = {"base_color": [0.03, 0.03, 0.032], "metallic": 0.35, "roughness": 0.42}
RUBBER = {"base_color": [0.018, 0.018, 0.018], "metallic": 0.0, "roughness": 0.85}
CHROME = {"base_color": [0.86, 0.86, 0.88], "metallic": 1.0, "roughness": 0.1}
MIRROR = {"base_color": [0.92, 0.92, 0.94], "metallic": 1.0, "roughness": 0.015}
GLASS = {"base_color": [0.05, 0.065, 0.075], "roughness": 0.02, "metallic": 0.0, "opacity": 0.42, "transmission": 0.9}
LENS_CLEAR = {"base_color": [0.9, 0.92, 0.95], "roughness": 0.02, "metallic": 0.0, "opacity": 0.2, "transmission": 1.0}
LENS_RED = {"base_color": [0.7, 0.02, 0.015], "roughness": 0.05, "metallic": 0.0, "opacity": 0.6, "transmission": 0.6}
LENS_AMBER = {"base_color": [0.95, 0.42, 0.02], "roughness": 0.05, "metallic": 0.0, "opacity": 0.55, "transmission": 0.6}
UNDERSEAL = {"base_color": [0.025, 0.024, 0.023], "metallic": 0.0, "roughness": 0.9}
ROAD_DIRT = {"base_color": [0.15, 0.13, 0.11], "metallic": 0.0, "roughness": 0.88, "coat": 0.0, "flake": 0.0}


def body_script(P):
    paint = P.group("paint")
    doors = P.named("door_F", "door_R")
    doors = [i for i in doors if P.m[i][1] == "paint"]
    shell = P.named("body_shell")
    hood = P.named("hood")
    exterior = P.group("paint", "black_trim", "rubber", "chrome", "grille", "black_metal", "mirror", "plate", "exhaust",
                       "glass", "lens_clear", "lens_red", "lens_amber")
    L = [
        {"tool": "new_project", "args": {"mesh": "assets/car/src/car_body.glb", "resolution": 4096, "material": "Matte black"}},
        # trims and hardware
        fill("Black trim", P.group("black_trim", "grille"), BLACK_TRIM, channels=NO_HEIGHT),
        fill("Rubber", P.group("rubber"), RUBBER, channels=NO_HEIGHT),
        fill("Powder-coat black", P.group("black_metal"), SATIN_BLACK_METAL, channels=NO_HEIGHT),
        fill("Chrome", P.group("chrome"), CHROME, channels=NO_HEIGHT),
        fill("Mirror glass", P.group("mirror"), MIRROR, channels=NO_HEIGHT),
        fill("Exhaust steel", P.group("exhaust"), {"base_color": [0.55, 0.52, 0.5], "metallic": 1.0, "roughness": 0.3}, channels=NO_HEIGHT),
        fill("Exhaust heat tint", P.group("exhaust"), {"base_color": [0.32, 0.22, 0.28], "metallic": 1.0, "roughness": 0.35},
             {"generator": "gradient", "amount": 0.9, "softness": 0.2, "breakup": 0.6, "scale": 2.0}, opacity=0.6, channels=NO_HEIGHT),
        fill("Plates", P.group("plate"), {"base_color": [0.9, 0.9, 0.88], "metallic": 0.0, "roughness": 0.45}, channels=NO_HEIGHT),
        # under the car and in the arches
        fill("Underseal", P.group("underbody"), UNDERSEAL, channels=NO_HEIGHT),
        fill("Underbody steel", P.group("underbody_metal"), {"base_color": [0.2, 0.18, 0.16], "metallic": 0.7, "roughness": 0.6}, channels=NO_HEIGHT),
        fill("Underbody rust", P.group("underbody_metal"), None, "Rust", {"generator": "grunge", "amount": 0.55, "scale": 3.0, "softness": 0.2}, opacity=0.9),
        fill("Suspension", P.group("suspension"), {"base_color": [0.07, 0.07, 0.075], "metallic": 0.6, "roughness": 0.5}, channels=NO_HEIGHT),
        fill("Springs", P.group("spring"), {"base_color": [0.55, 0.07, 0.03], "metallic": 0.0, "roughness": 0.4, "coat": 0.6, "coat_roughness": 0.2}, channels=NO_HEIGHT),
        # interior
        fill("Seat cloth", P.group("interior_fabric"), {"base_color": [0.06, 0.06, 0.068], "metallic": 0.0, "roughness": 0.92}, channels=NO_HEIGHT),
        fill("Cloth weave", P.group("interior_fabric"), {"base_color": [0.09, 0.09, 0.1], "roughness": 0.95, "height": -0.25},
             {"generator": "tiles", "variant": "square", "scale": 160.0, "mortar": 0.25, "amount": 0.5}, opacity=0.6),
        fill("Leather", P.group("interior_leather"), {"base_color": [0.028, 0.025, 0.024], "metallic": 0.0, "roughness": 0.42}, channels=NO_HEIGHT),
        fill("Leather shine", P.group("interior_leather", "interior_fabric"), {"roughness": 0.3},
             {"generator": "edge_wear", "amount": 0.35, "softness": 0.2}, opacity=0.6, channels={"base_color": False, "metallic": False, "height": False}),
        fill("Cabin plastic", P.group("interior_plastic"), {"base_color": [0.045, 0.045, 0.05], "metallic": 0.0, "roughness": 0.62}, channels=NO_HEIGHT),
        fill("Dash vinyl", P.group("interior_dark"), {"base_color": [0.02, 0.02, 0.022], "metallic": 0.0, "roughness": 0.5}, channels=NO_HEIGHT),
        fill("Carpet", P.group("interior_carpet"), {"base_color": [0.035, 0.035, 0.037], "metallic": 0.0, "roughness": 0.97}, channels=NO_HEIGHT),
        fill("Screens", P.group("screen"), {"base_color": [0.01, 0.015, 0.02], "metallic": 0.0, "roughness": 0.08, "emissive": [0.2, 0.75, 0.8], "emissive_strength": 0.4}, channels=NO_HEIGHT),
        # ---- livery: Hoshikawa Security (authored look) and Koen Cab (variant)
        fill("Paint: midnight candy", paint, MIDNIGHT_CANDY, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Paint: pearl doors", doors, PEARL_WHITE, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Paint: cab teal", paint, TEAL_CANDY, channels=NO_HEIGHT, variant="livery_cab", visible=False),
        fill("Paint: cab cream hood", hood, CREAM_PAINT, channels=NO_HEIGHT, variant="livery_cab", visible=False),
        # lamps
        fill("Glass", P.group("glass"), GLASS, channels=NO_HEIGHT),
        fill("Headlamp lenses", P.group("lens_clear"), LENS_CLEAR, channels=NO_HEIGHT),
        fill("Tail lenses", P.group("lens_red"), LENS_RED, channels=NO_HEIGHT),
        fill("Indicator lenses", P.group("lens_amber"), LENS_AMBER, channels=NO_HEIGHT),
        fill("Headlamps", P.group("emitter_head"), {"base_color": [1.0, 0.97, 0.9], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 0.93, 0.8], "emissive_strength": 6.0}, channels=NO_HEIGHT),
        fill("Tail lamps", P.group("emitter_tail"), {"base_color": [0.8, 0.03, 0.02], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 0.04, 0.02], "emissive_strength": 3.0}, channels=NO_HEIGHT),
        fill("Indicators", P.group("emitter_amber"), {"base_color": [0.9, 0.45, 0.05], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 0.45, 0.02], "emissive_strength": 0.6}, channels=NO_HEIGHT),
        fill("Reverse lamps", P.group("emitter_reverse"), {"base_color": [0.9, 0.9, 0.9], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 1.0, 1.0], "emissive_strength": 0.5}, channels=NO_HEIGHT),
        fill("Light bar LEDs red", P.group("emitter_red"), {"base_color": [0.9, 0.05, 0.05], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 0.03, 0.04], "emissive_strength": 7.0}, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Light bar LEDs blue", P.group("emitter_blue"), {"base_color": [0.05, 0.15, 0.9], "roughness": 0.2, "metallic": 0.0, "emissive": [0.05, 0.25, 1.0], "emissive_strength": 7.0}, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Light bar lens red", P.group("lightbar_lens_red"), {"base_color": [0.75, 0.05, 0.05], "roughness": 0.08, "metallic": 0.0, "opacity": 0.5, "transmission": 0.6}, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Light bar lens blue", P.group("lightbar_lens_blue"), {"base_color": [0.05, 0.15, 0.75], "roughness": 0.08, "metallic": 0.0, "opacity": 0.5, "transmission": 0.6}, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Light bar centre", P.group("lightbar_center"), {"base_color": [0.85, 0.86, 0.88], "roughness": 0.3, "metallic": 0.0, "emissive": [0.9, 0.95, 1.0], "emissive_strength": 1.2}, channels=NO_HEIGHT),
        # cab: the light bar is a cab sign now (amber, dim)
        fill("Cab sign LEDs", P.group("emitter_red", "emitter_blue"), {"base_color": [0.95, 0.6, 0.1], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 0.62, 0.15], "emissive_strength": 3.0}, channels=NO_HEIGHT, variant="livery_cab", visible=False),
        fill("Cab sign lenses", P.group("lightbar_lens_red", "lightbar_lens_blue"), {"base_color": [0.95, 0.75, 0.3], "roughness": 0.08, "metallic": 0.0, "opacity": 0.55, "transmission": 0.6}, channels=NO_HEIGHT, variant="livery_cab", visible=False),
    ]
    # ---- wear on the paint (both liveries)
    L += [
        fill("Coat haze", paint, {"coat_roughness": 0.22}, None, {"generator": "grunge", "amount": 0.5, "scale": 1.6, "softness": 0.3},
             opacity=0.8, channels={"base_color": False, "roughness": False, "metallic": False, "height": False}),
        fill("Fine scratches", paint, {"base_color": [0.4, 0.42, 0.45], "roughness": 0.45, "coat": 0.0},
             {"generator": "scratches", "amount": 0.25, "scale": 4.0}, opacity=0.35, channels=NO_HEIGHT),
        fill("Edge chips: primer", paint, {"base_color": [0.36, 0.37, 0.38], "metallic": 0.0, "roughness": 0.65, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.3, "softness": 0.05, "breakup": 0.7, "scale": 6.0}, channels=NO_HEIGHT),
        fill("Edge chips: bare steel", paint, {"base_color": [0.5, 0.5, 0.52], "metallic": 1.0, "roughness": 0.35, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.16, "softness": 0.03, "breakup": 0.8, "scale": 8.0}, channels=NO_HEIGHT),
        # rust: low edges (arches, sills, bumper bottoms), spotty
        fill("Arch rust", paint + P.group("underbody_metal"), {"coat": 0.0, "flake": 0.0}, "Rust",
             {"generator": "edge_wear", "amount": 0.55, "softness": 0.12, "breakup": 0.6, "scale": 5.0,
              "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.22, "softness": 0.06, "breakup": 0.3},
                          {"generator": "spots", "op": "multiply", "amount": 0.6, "scale": 6.0, "softness": 0.15}]}),
        fill("Rust bloom", shell, {"base_color": [0.3, 0.16, 0.08], "roughness": 0.8, "coat": 0.0, "flake": 0.0},
             {"generator": "spots", "amount": 0.35, "scale": 9.0, "softness": 0.2,
              "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.24, "softness": 0.08, "breakup": 0.4}]}, opacity=0.7, channels=NO_HEIGHT),
        # grime: gaps and crevices, rain streaks under the glass and trims, road dirt from the sills
        fill("Gap grime", exterior, {"base_color": [0.06, 0.055, 0.05], "roughness": 0.85, "coat": 0.0},
             {"generator": "dirt", "amount": 0.45, "softness": 0.2, "breakup": 0.5}, opacity=0.85, channels=NO_HEIGHT),
        fill("Rain streaks", P.group("paint", "glass", "chrome", "black_trim"), {"base_color": [0.08, 0.075, 0.07], "roughness": 0.55, "coat_roughness": 0.3},
             {"generator": "leaks", "amount": 0.45, "scale": 3.0, "breakup": 0.6, "drip_length": 0.6, "ao_influence": 0.3, "softness": 0.15},
             opacity=0.55, channels=NO_HEIGHT),
        fill("Water spots", P.group("glass"), {"base_color": [0.2, 0.2, 0.2], "roughness": 0.25, "opacity": 0.55},
             {"generator": "spots", "amount": 0.3, "scale": 40.0, "softness": 0.1}, opacity=0.5, channels=NO_HEIGHT),
        fill("Road dirt", exterior + P.group("underbody"), ROAD_DIRT,
             {"generator": "gradient", "amount": 0.2, "softness": 0.05, "breakup": 0.55, "scale": 3.0,
              "effects": [{"generator": "grunge", "op": "multiply", "amount": 0.75, "scale": 2.5, "softness": 0.25}]},
             opacity=0.9, channels=NO_HEIGHT),
        fill("Road spray", exterior, {"base_color": [0.12, 0.11, 0.1], "roughness": 0.7, "coat_roughness": 0.4},
             {"generator": "gradient", "amount": 0.32, "softness": 0.12, "breakup": 0.7, "scale": 6.0}, opacity=0.35, channels=NO_HEIGHT),
        fill("Cabin dust", P.group("interior_dark", "interior_plastic", "interior_carpet"), {"base_color": [0.12, 0.11, 0.1], "roughness": 0.9},
             {"generator": "dirt", "amount": 0.35, "softness": 0.3}, opacity=0.4, channels=NO_HEIGHT),
    ]
    # ---- decals (paint layers; anchored placement snaps them onto the body)
    side = []
    for sx, n, flash in ((1, [1, 0, 0], "hs_flash.png"), (-1, [-1, 0, 0], "hs_flash_r.png")):
        x = sx * 0.89
        side += [
            decal(DEC + flash, bl(x, -0.05, 0.47), n, [3.2, 0.40], name=f"hs_flash_{'L' if sx > 0 else 'R'}", variant="livery_hs", overlap_order=0),
            decal(DEC + "hs_door_dark.png", bl(x, -0.33, 0.70), n, 0.78, name=f"hs_door_{'L' if sx > 0 else 'R'}", variant="livery_hs", overlap_order=1),
            decal(DEC + "shock_warning.png", bl(x, 0.62, 0.62), n, 0.16, name=f"shock_{'L' if sx > 0 else 'R'}", variant="livery_hs", overlap_order=1, wear=0.15, fade=0.2),
            decal(DEC + ("cab_flash.png" if sx > 0 else "cab_flash_r.png"), bl(x, -0.05, 0.47), n, [3.2, 0.40], name=f"cab_flash_{'L' if sx > 0 else 'R'}", variant="livery_cab", enabled=False, overlap_order=0),
            decal(DEC + "cab_door.png", bl(x, -0.33, 0.70), n, 0.80, name=f"cab_door_{'L' if sx > 0 else 'R'}", variant="livery_cab", enabled=False, overlap_order=1),
        ]
    L += side
    L += [
        decal(DEC + "hs_crest.png", bl(0.0, -1.55, 0.83), [0, 1, 0], 0.42, name="hs_crest_hood", variant="livery_hs", overlap_order=1),
        decal(DEC + "hs_unit_roof.png", bl(0.0, 0.62, 1.39), [0, 1, 0], 0.95, rotation=90, name="hs_unit_roof", variant="livery_hs", overlap_order=1),
        decal(DEC + "hs_unit.png", bl(0.0, 1.95, 0.97), [0, 1, 0], 0.36, name="hs_unit_trunk", variant="livery_hs", overlap_order=1),
        decal(DEC + "cab_number.png", bl(0.0, 0.62, 1.39), [0, 1, 0], 0.55, name="cab_number_roof", variant="livery_cab", enabled=False, overlap_order=1),
        decal(DEC + "cab_number.png", bl(0.0, 1.95, 0.97), [0, 1, 0], 0.36, name="cab_number_trunk", variant="livery_cab", enabled=False, overlap_order=1),
        decal(DEC + "meridian_linked.png", bl(0.52, 2.205, 0.44), [0, 0, -1], 0.24, name="meridian_sticker", variant="livery_hs", overlap_order=1, fade=0.15),
        decal(DEC + "badge_tsubame.png", bl(-0.55, 2.10, 0.95), [0, 0.2, -1], 0.17, name="badge", overlap_order=1),
        # the resistance got to it: UNPLUG tag on the right rear quarter, half scrubbed off
        decal(STORY + "graffiti_unplug.png", bl(-0.885, 1.47, 0.70), [-1, 0, 0], 0.5, name="unplug_tag", variant="story", overlap_order=2, wear=0.35, fade=0.45, wear_style="grunge"),
        decal(STORY + "stencil_eye_crossed.png", bl(0.885, 1.50, 0.70), [1, 0, 0], 0.22, name="eye_stencil", variant="story", overlap_order=2, wear=0.2, fade=0.3),
    ]
    # plates, screens (part decals)
    for pid in P.named("plate_F", "plate_R"):
        L.append(part_decal(DEC + "plate_hs.png", pid, fit="fill", margin=0.0, name=f"plate_hs_{pid}", variant="livery_hs"))
        L.append(part_decal(DEC + "plate_cab.png", pid, fit="fill", margin=0.0, name=f"plate_cab_{pid}", variant="livery_cab", enabled=False))
    for pid in P.named("dash_gauges"):
        L.append(part_decal(DEC + "gauges.png", pid, fit="fill", margin=0.0, emissive_strength=1.5, name="gauges"))
    for pid in P.named("terminal_screen"):
        L.append(part_decal(STORY + "billboard_score.png", pid, fit="fill", margin=0.0, emissive_strength=1.2, name="terminal"))
    return L


def body_finish(L):
    variants = [{"name": "security", "disable": ["livery_cab"], "enable": ["livery_hs", "story"]},
                {"name": "cab", "disable": ["livery_hs"], "enable": ["livery_cab", "story"]}]
    v = {"yaw": 215, "pitch": 14, "width": 1200, "height": 760, "lighting": "night", "bloom": True, "dir": DOCS}
    L += [
        {"tool": "save_project", "args": {"path": f"{PROJECTS}/car_body.pigment"}},
        {"tool": "export_variants", "args": {"dir": TEXTURES, "name": "car_body", "variants": variants, "preview": dict(v, dir=str(TMP))}},
        {"tool": "render", "args": {"path": f"{DOCS}/pigment_body_night.png", "yaw": 215, "pitch": 12, "width": 1400, "height": 860,
                                    "lighting": "night", "bloom": True}},
        {"tool": "render", "args": {"path": f"{DOCS}/pigment_body_rear.png", "yaw": 40, "pitch": 12, "width": 1400, "height": 860,
                                    "lighting": "night", "bloom": True}},
        {"tool": "render", "args": {"path": f"{TMP}/pigment_body_coat.png", "yaw": 215, "pitch": 12, "width": 1000, "height": 640, "view": "coat"}},
        {"tool": "render_turntable", "args": {"path": f"{DOCS}/pigment_body_turntable.png", "frames": 8, "pitch": 12, "width": 420, "height": 300,
                                              "lighting": "studio", "bloom": False}},
        {"tool": "save_project", "args": {"path": f"{PROJECTS}/car_body.pigment"}},
    ]
    return L


def wheel_script(P):
    tyre = P.group("tyre")
    rim = P.group("rim")
    L = [
        {"tool": "new_project", "args": {"mesh": "assets/car/src/car_wheel.glb", "resolution": 2048, "material": "Black rubber"}},
        fill("Tyre rubber", tyre, RUBBER, channels=NO_HEIGHT),
        fill("Tread scuff", tyre, {"base_color": [0.04, 0.04, 0.04], "roughness": 0.95},
             {"generator": "edge_wear", "amount": 0.45, "softness": 0.15, "breakup": 0.5}, opacity=0.8, channels=NO_HEIGHT),
        fill("Rim paint", rim, {"base_color": [0.13, 0.13, 0.14], "metallic": 0.85, "roughness": 0.3, "coat": 1.0, "coat_roughness": 0.05, "flake": 0.3}, channels=NO_HEIGHT),
        fill("Rim lip polish", rim, {"base_color": [0.8, 0.8, 0.82], "metallic": 1.0, "roughness": 0.15, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.35, "softness": 0.04, "breakup": 0.3}, channels=NO_HEIGHT),
        fill("Lug nuts", P.group("lug"), CHROME, channels=NO_HEIGHT),
        fill("Disc steel", P.group("brake_disc"), {"base_color": [0.42, 0.41, 0.4], "metallic": 1.0, "roughness": 0.38}, channels=NO_HEIGHT),
        fill("Disc rust", P.group("brake_disc"), None, "Rust", {"generator": "grunge", "amount": 0.45, "scale": 12.0, "softness": 0.25}, opacity=0.85),
        fill("Caliper paint", P.group("caliper"), {"base_color": [0.75, 0.16, 0.03], "metallic": 0.0, "roughness": 0.35, "coat": 0.8, "coat_roughness": 0.08}, channels=NO_HEIGHT),
        # brake dust in every crevice of the rim and caliper, dusty sidewall
        fill("Brake dust", rim + P.group("caliper", "lug"), {"base_color": [0.1, 0.075, 0.055], "metallic": 0.0, "roughness": 0.85, "coat": 0.0},
             {"generator": "dirt", "amount": 0.55, "softness": 0.2, "breakup": 0.6}, opacity=0.85, channels=NO_HEIGHT),
        fill("Sidewall dust", tyre, {"base_color": [0.28, 0.26, 0.23], "roughness": 0.95},
             {"generator": "grunge", "amount": 0.42, "scale": 6.0, "softness": 0.3}, opacity=0.55, channels=NO_HEIGHT),
        fill("Road grime", tyre + rim, {"base_color": [0.12, 0.105, 0.09], "roughness": 0.9, "coat": 0.0},
             {"generator": "dirt", "amount": 0.4, "softness": 0.3, "breakup": 0.7}, opacity=0.6, channels=NO_HEIGHT),
    ]
    # sidewall lettering: the ring image fitted to the tyre's outer (+X) face = its diameter
    for pid in tyre[:1]:
        L.append(part_decal(DEC + "tyre_ring.png", pid, facing="+x", fit="contain", margin=0.0, name="sidewall",
                            values={"roughness": 0.7}, channels=["base_color", "roughness"]))
    for pid in P.group("caliper")[:1]:
        L.append(part_decal(DEC + "caliper_logo.png", pid, facing="+x", fit="contain", margin=0.2, name="caliper_logo"))
    L += [
        {"tool": "save_project", "args": {"path": f"{PROJECTS}/car_wheel.pigment"}},
        {"tool": "export_textures", "args": {"dir": f"{TEXTURES}/car_wheel", "name": "car_wheel", "preset": "separate"}},
        {"tool": "render", "args": {"path": f"{DOCS}/pigment_wheel.png", "yaw": 70, "pitch": 8, "width": 900, "height": 900, "lighting": "night", "bloom": True}},
    ]
    return L


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    what = args or ["body", "wheel"]
    parts = json.loads((SRC / "car_parts.json").read_text())
    for w in what:
        mesh = f"assets/car/src/car_{w}.glb"
        P = Parts(match_parts(pigment_parts(mesh), parts[w]))
        L = body_finish(body_script(P)) if w == "body" else wheel_script(P)
        path = SCRIPTS / f"car_{w}.jsonl"
        if "--no-run" in sys.argv:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in L) + "\n", encoding="utf8")
            print("wrote", path)
            continue
        out = run(L, f"car_{w}", keep=path)
        print(f"[car_textures] {w}: {len(L)} steps")
        for line in out.splitlines():
            if line.startswith("[export"):
                print("  ", line[:300])


if __name__ == "__main__":
    main()
