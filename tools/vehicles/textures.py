"""Texture a fleet vehicle in Pigment (via pigment-mcp --script), with all its variants.

    python tools/vehicles/textures.py NAME [body] [wheel] [--no-run]
    python tools/vehicles/textures.py all
    PIGMENT_MCP=path/to/pigment-mcp.exe python tools/vehicles/textures.py mame

Reads assets/vehicles/<id>/src/<id>_parts.json (tools/vehicles/build.py: every named piece
with its material group and bounding box), matches Pigment's parts to those pieces, and
writes two Pigment scripts (scenes/vehicles/<id>/scripts/<id>_body.jsonl, <id>_wheel.jsonl):

  body   paint with clearcoat + flake (one paint layer per variant), two-tone accents, trims,
         chrome, rubber, glass, emissive lamps, interior, under-car; light wear on every
         variant (coat haze, scratches, edge chips, gap grime, rain streaks, road dirt), heavy
         wear for the beaten-up variant (sun fade, primer, rust, rust streaks, grime);
         liveries / plates / stickers as decals, each tagged with its variant group.
         `export_variants` writes one texture set per variant:
         scenes/vehicles/<id>/textures/<id>_body__<variant>/
  wheel  tyre with sidewall lettering, rim paint, lug nuts, rusty disc, caliper with logo,
         brake dust: scenes/vehicles/<id>/textures/<id>_wheel/

The Tsubame-4 keeps its authored recipe (hero_body_script, unchanged for `security` and
`cab`) with the fleet's extra variants added on top.
"""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet as F  # noqa: E402

MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
TMP = Path(os.environ.get("TEMP", "/tmp")) / "pig_fleet"
DEC = "assets/decals/car/"
STORY = "assets/decals/story/"


def paths(vid):
    return {"src": ROOT / "assets" / "vehicles" / vid / "src", "scripts": ROOT / "scenes" / "vehicles" / vid / "scripts",
            "projects": f"scenes/vehicles/{vid}/projects", "textures": f"scenes/vehicles/{vid}/textures",
            "docs": "docs/agents/fleet", "mesh_body": f"assets/vehicles/{vid}/src/{vid}_body.glb",
            "mesh_wheel": f"assets/vehicles/{vid}/src/{vid}_wheel.glb"}


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
            raise SystemExit(f"Pigment part {q['id']} (centre {q['center']}) matches no piece in the parts json: rebuild the model")
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
            print(f"   (skipped layer {name!r}: no parts in this vehicle)")
            return None
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


NO_HEIGHT = {"height": False}

# ------------------------------------------------------------------ materials (values)

MIDNIGHT_CANDY = {"base_color": [0.018, 0.035, 0.11], "metallic": 0.55, "roughness": 0.33, "coat": 1.0, "coat_roughness": 0.02, "flake": 0.12}
PEARL_WHITE = {"base_color": [0.86, 0.87, 0.88], "metallic": 0.15, "roughness": 0.3, "coat": 1.0, "coat_roughness": 0.02, "flake": 0.04}
TEAL_CANDY = {"base_color": [0.02, 0.17, 0.17], "metallic": 0.55, "roughness": 0.32, "coat": 1.0, "coat_roughness": 0.02, "flake": 0.12}
CREAM_PAINT = {"base_color": [0.78, 0.72, 0.58], "metallic": 0.1, "roughness": 0.34, "coat": 1.0, "coat_roughness": 0.04, "flake": 0.1}
BLACK_TRIM = {"base_color": [0.022, 0.022, 0.024], "metallic": 0.0, "roughness": 0.55}
SATIN_BLACK_METAL = {"base_color": [0.03, 0.03, 0.032], "metallic": 0.35, "roughness": 0.42}
RUBBER = {"base_color": [0.018, 0.018, 0.018], "metallic": 0.0, "roughness": 0.85}
CHROME = {"base_color": [0.86, 0.86, 0.88], "metallic": 1.0, "roughness": 0.1}
MIRROR = {"base_color": [0.92, 0.92, 0.94], "metallic": 1.0, "roughness": 0.015}
GLASS = {"base_color": [0.05, 0.065, 0.075], "roughness": 0.02, "metallic": 0.0, "opacity": 0.3, "transmission": 0.9}
LENS_CLEAR = {"base_color": [0.9, 0.92, 0.95], "roughness": 0.02, "metallic": 0.0, "opacity": 0.2, "transmission": 1.0}
LENS_RED = {"base_color": [0.7, 0.02, 0.015], "roughness": 0.05, "metallic": 0.0, "opacity": 0.6, "transmission": 0.6}
LENS_AMBER = {"base_color": [0.95, 0.42, 0.02], "roughness": 0.05, "metallic": 0.0, "opacity": 0.55, "transmission": 0.6}
UNDERSEAL = {"base_color": [0.025, 0.024, 0.023], "metallic": 0.0, "roughness": 0.9}
ROAD_DIRT = {"base_color": [0.15, 0.13, 0.11], "metallic": 0.0, "roughness": 0.88, "coat": 0.0, "flake": 0.0}
HIDDEN = {"opacity": 0.0, "transmission": 0.0}


def emit(rgb_base, rgb, strength):
    return {"base_color": rgb_base, "roughness": 0.2, "metallic": 0.0, "emissive": rgb, "emissive_strength": strength}


# ------------------------------------------------------------------ shared layer blocks


def trims_block(P):
    """Trims, hardware, under-car, interior: identical on every vehicle (the hero's values)."""
    return [
        fill("Black trim", P.group("black_trim", "grille"), BLACK_TRIM, channels=NO_HEIGHT),
        fill("Rubber", P.group("rubber"), RUBBER, channels=NO_HEIGHT),
        fill("Powder-coat black", P.group("black_metal"), SATIN_BLACK_METAL, channels=NO_HEIGHT),
        fill("Chrome", P.group("chrome"), CHROME, channels=NO_HEIGHT),
        fill("Mirror glass", P.group("mirror"), MIRROR, channels=NO_HEIGHT),
        fill("Exhaust steel", P.group("exhaust"), {"base_color": [0.55, 0.52, 0.5], "metallic": 1.0, "roughness": 0.3}, channels=NO_HEIGHT),
        fill("Exhaust heat tint", P.group("exhaust"), {"base_color": [0.32, 0.22, 0.28], "metallic": 1.0, "roughness": 0.35},
             {"generator": "gradient", "amount": 0.9, "softness": 0.2, "breakup": 0.6, "scale": 2.0}, opacity=0.6, channels=NO_HEIGHT),
        fill("Plates", P.group("plate"), {"base_color": [0.9, 0.9, 0.88], "metallic": 0.0, "roughness": 0.45}, channels=NO_HEIGHT),
        fill("Underseal", P.group("underbody"), UNDERSEAL, channels=NO_HEIGHT),
        fill("Underbody steel", P.group("underbody_metal"), {"base_color": [0.2, 0.18, 0.16], "metallic": 0.7, "roughness": 0.6}, channels=NO_HEIGHT),
        fill("Underbody rust", P.group("underbody_metal"), None, "Rust", {"generator": "grunge", "amount": 0.55, "scale": 3.0, "softness": 0.2}, opacity=0.9, channels=NO_HEIGHT),
        fill("Suspension", P.group("suspension"), {"base_color": [0.07, 0.07, 0.075], "metallic": 0.6, "roughness": 0.5}, channels=NO_HEIGHT),
        fill("Springs", P.group("spring"), {"base_color": [0.55, 0.07, 0.03], "metallic": 0.0, "roughness": 0.4, "coat": 0.6, "coat_roughness": 0.2}, channels=NO_HEIGHT),
        fill("Seat cloth", P.group("interior_fabric"), {"base_color": [0.06, 0.06, 0.068], "metallic": 0.0, "roughness": 0.92}, channels=NO_HEIGHT),
        fill("Cloth weave", P.group("interior_fabric"), {"base_color": [0.09, 0.09, 0.1], "roughness": 0.95, "height": -0.25},
             {"generator": "tiles", "variant": "square", "scale": 90.0, "mortar": 0.3, "amount": 0.5}, opacity=0.25, channels=NO_HEIGHT),
        fill("Leather", P.group("interior_leather"), {"base_color": [0.028, 0.025, 0.024], "metallic": 0.0, "roughness": 0.42}, channels=NO_HEIGHT),
        fill("Leather shine", P.group("interior_leather", "interior_fabric"), {"roughness": 0.3},
             {"generator": "edge_wear", "amount": 0.35, "softness": 0.2}, opacity=0.6, channels={"base_color": False, "metallic": False, "height": False}),
        fill("Cabin plastic", P.group("interior_plastic"), {"base_color": [0.045, 0.045, 0.05], "metallic": 0.0, "roughness": 0.62}, channels=NO_HEIGHT),
        fill("Dash vinyl", P.group("interior_dark"), {"base_color": [0.02, 0.02, 0.022], "metallic": 0.0, "roughness": 0.5}, channels=NO_HEIGHT),
        fill("Carpet", P.group("interior_carpet"), {"base_color": [0.035, 0.035, 0.037], "metallic": 0.0, "roughness": 0.97}, channels=NO_HEIGHT),
        fill("Screens", P.group("screen"), {"base_color": [0.01, 0.015, 0.02], "metallic": 0.0, "roughness": 0.08, "emissive": [0.2, 0.75, 0.8], "emissive_strength": 0.4}, channels=NO_HEIGHT),
    ]


def extra_groups_block(P, v):
    """Material groups only the fleet uses (box bodies, cargo, floors, signs, status lamps)."""
    L = []
    if P.group("cargo_frame"):
        L.append(fill("Aluminium frame", P.group("cargo_frame"), {"base_color": [0.62, 0.63, 0.64], "metallic": 1.0, "roughness": 0.36}, channels=NO_HEIGHT))
        L.append(fill("Aluminium oxide", P.group("cargo_frame"), {"base_color": [0.42, 0.42, 0.41], "roughness": 0.7, "metallic": 0.6},
                      {"generator": "grunge", "amount": 0.4, "scale": 4.0, "softness": 0.3}, opacity=0.6, channels=NO_HEIGHT))
    if P.group("cargo") and v["id"] != "kaiun":
        L.append(fill("Cardboard", P.group("cargo"), {"base_color": [0.42, 0.30, 0.17], "metallic": 0.0, "roughness": 0.9}, channels=NO_HEIGHT))
        L.append(fill("Parcel tape", P.group("cargo"), {"base_color": [0.75, 0.62, 0.38], "roughness": 0.4},
                      {"generator": "tiles", "variant": "square", "scale": 3.0, "mortar": 0.85, "amount": 0.5}, opacity=0.8, channels=NO_HEIGHT))
    if P.group("wood"):
        L.append(fill("Ply floor", P.group("wood"), {"base_color": [0.30, 0.20, 0.11], "metallic": 0.0, "roughness": 0.75}, channels=NO_HEIGHT))
    if P.group("interior_floor"):
        L.append(fill("Rubber floor", P.group("interior_floor"), {"base_color": [0.06, 0.065, 0.07], "metallic": 0.0, "roughness": 0.8}, channels=NO_HEIGHT))
    if P.group("handrail"):
        L.append(fill("Handrail", P.group("handrail"), {"base_color": [0.85, 0.65, 0.08], "metallic": 0.2, "roughness": 0.35}, channels=NO_HEIGHT))
    if P.group("rim_dark"):
        L.append(fill("Dark inserts", P.group("rim_dark"), BLACK_TRIM, channels=NO_HEIGHT))
    if P.group("emitter_cyan"):
        L.append(fill("Status lamps", P.group("emitter_cyan"), emit([0.2, 0.8, 0.95], [0.25, 0.85, 1.0], 4.0), channels=NO_HEIGHT))
    if P.group("emitter_sign"):
        L.append(fill("Roof sign", P.group("emitter_sign"), emit([0.9, 0.9, 0.95], [0.85, 0.95, 1.0], 2.5), channels=NO_HEIGHT))
    return L


def lamps_block(P):
    return [
        fill("Glass", P.group("glass"), GLASS, channels=NO_HEIGHT),
        fill("Ceramic frit", P.group("frit"), {"base_color": [0.012, 0.012, 0.013], "metallic": 0.0, "roughness": 0.18}, channels=NO_HEIGHT),
        fill("Headlamp lenses", P.group("lens_clear"), LENS_CLEAR, channels=NO_HEIGHT),
        fill("Tail lenses", P.group("lens_red"), LENS_RED, channels=NO_HEIGHT),
        fill("Indicator lenses", P.group("lens_amber"), LENS_AMBER, channels=NO_HEIGHT),
        fill("Headlamps", P.group("emitter_head"), emit([1.0, 0.97, 0.9], [1.0, 0.93, 0.8], 6.0), channels=NO_HEIGHT),
        fill("Tail lamps", P.group("emitter_tail"), emit([0.8, 0.03, 0.02], [1.0, 0.04, 0.02], 3.0), channels=NO_HEIGHT),
        fill("Indicators", P.group("emitter_amber"), emit([0.9, 0.45, 0.05], [1.0, 0.45, 0.02], 0.6), channels=NO_HEIGHT),
        fill("Reverse lamps", P.group("emitter_reverse"), emit([0.9, 0.9, 0.9], [1.0, 1.0, 1.0], 0.5), channels=NO_HEIGHT),
    ]


def light_wear_block(P, paint, exterior):
    """Every variant: a used-but-kept car."""
    return [
        fill("Coat haze", paint, {"coat_roughness": 0.22}, None, {"generator": "grunge", "amount": 0.35, "scale": 1.6, "softness": 0.3},
             opacity=0.45, channels={"base_color": False, "roughness": False, "metallic": False, "height": False}),
        fill("Fine scratches", paint, {"base_color": [0.4, 0.42, 0.45], "roughness": 0.45, "coat": 0.0},
             {"generator": "scratches", "amount": 0.12, "scale": 4.0}, opacity=0.18, channels=NO_HEIGHT),
        fill("Edge chips: primer", paint, {"base_color": [0.36, 0.37, 0.38], "metallic": 0.0, "roughness": 0.65, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.14, "softness": 0.04, "breakup": 0.75, "scale": 6.0}, channels=NO_HEIGHT),
        fill("Gap grime", exterior, {"base_color": [0.06, 0.055, 0.05], "roughness": 0.85, "coat": 0.0},
             {"generator": "dirt", "amount": 0.42, "softness": 0.2, "breakup": 0.5}, opacity=0.8, channels=NO_HEIGHT),
        fill("Rain streaks", P.group("paint", "chrome", "black_trim", "cargo"), {"base_color": [0.08, 0.075, 0.07], "roughness": 0.55, "coat_roughness": 0.3},
             {"generator": "leaks", "amount": 0.30, "scale": 3.0, "breakup": 0.65, "drip_length": 0.5, "ao_influence": 0.4, "softness": 0.15},
             opacity=0.22, channels=NO_HEIGHT),
        fill("Water spots", P.group("glass"), {"base_color": [0.2, 0.2, 0.2], "roughness": 0.25, "opacity": 0.55},
             {"generator": "spots", "amount": 0.15, "scale": 40.0, "softness": 0.1}, opacity=0.3, channels=NO_HEIGHT),
        fill("Road dirt", exterior + P.group("underbody"), ROAD_DIRT,
             {"generator": "gradient", "amount": 0.12, "softness": 0.05, "breakup": 0.55, "scale": 3.0,
              "effects": [{"generator": "grunge", "op": "multiply", "amount": 0.7, "scale": 2.5, "softness": 0.25}]},
             opacity=0.7, channels=NO_HEIGHT),
        fill("Road spray", exterior, {"base_color": [0.12, 0.11, 0.1], "roughness": 0.7, "coat_roughness": 0.4},
             {"generator": "gradient", "amount": 0.22, "softness": 0.12, "breakup": 0.7, "scale": 6.0}, opacity=0.2, channels=NO_HEIGHT),
        fill("Cabin dust", P.group("interior_dark", "interior_plastic", "interior_carpet"), {"base_color": [0.12, 0.11, 0.1], "roughness": 0.9},
             {"generator": "dirt", "amount": 0.35, "softness": 0.3}, opacity=0.4, channels=NO_HEIGHT),
    ]


def heavy_wear_block(P, paint, exterior, group):
    """The beaten-up variant: sun-faded, chipped to primer and steel, rusting from the low edges, grimy."""
    v = {"variant": group, "visible": False}
    return [
        fill("Beater: sun fade", paint, {"base_color": [0.55, 0.52, 0.47], "roughness": 0.8, "coat_roughness": 0.6},
             {"generator": "grunge", "amount": 0.55, "scale": 1.2, "softness": 0.45},
             opacity=0.55, channels=NO_HEIGHT, **v),
        fill("Beater: dull coat", paint, {"coat_roughness": 0.55, "roughness": 0.7}, None, {"generator": "grunge", "amount": 0.7, "scale": 2.0, "softness": 0.3},
             opacity=0.9, channels={"base_color": False, "metallic": False, "height": False}, **v),
        fill("Beater: chips to primer", paint, {"base_color": [0.36, 0.37, 0.38], "metallic": 0.0, "roughness": 0.7, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.42, "softness": 0.05, "breakup": 0.6, "scale": 5.0}, channels=NO_HEIGHT, **v),
        fill("Beater: chips to steel", paint, {"base_color": [0.5, 0.5, 0.52], "metallic": 1.0, "roughness": 0.4, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.25, "softness": 0.03, "breakup": 0.75, "scale": 8.0}, channels=NO_HEIGHT, **v),
        fill("Beater: dents scratches", paint, {"base_color": [0.45, 0.45, 0.46], "roughness": 0.55, "coat": 0.0},
             {"generator": "scratches", "amount": 0.45, "scale": 3.0}, opacity=0.5, channels=NO_HEIGHT, **v),
        fill("Beater: sill rust", paint + P.group("underbody_metal", "chrome"), {"coat": 0.0, "flake": 0.0}, "Rust",
             {"generator": "edge_wear", "amount": 0.7, "softness": 0.12, "breakup": 0.5, "scale": 5.0,
              "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.35, "softness": 0.08, "breakup": 0.35}]}, channels=NO_HEIGHT, **v),
        fill("Beater: rust bloom", paint, {"base_color": [0.30, 0.15, 0.07], "roughness": 0.85, "coat": 0.0, "flake": 0.0},
             {"generator": "spots", "amount": 0.45, "scale": 7.0, "softness": 0.2,
              "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.4, "softness": 0.12, "breakup": 0.4}]}, opacity=0.7, channels=NO_HEIGHT, **v),
        fill("Beater: rust streaks", paint, {"base_color": [0.26, 0.12, 0.05], "roughness": 0.8, "coat": 0.0},
             {"generator": "leaks", "amount": 0.55, "scale": 4.0, "breakup": 0.5, "drip_length": 0.8, "ao_influence": 0.5, "softness": 0.1},
             opacity=0.55, channels=NO_HEIGHT, **v),
        fill("Beater: grime", exterior, {"base_color": [0.08, 0.07, 0.06], "roughness": 0.9, "coat": 0.0},
             {"generator": "dirt", "amount": 0.65, "softness": 0.25, "breakup": 0.4}, opacity=0.9, channels=NO_HEIGHT, **v),
        fill("Beater: mud", exterior + P.group("underbody"), ROAD_DIRT,
             {"generator": "gradient", "amount": 0.35, "softness": 0.08, "breakup": 0.7, "scale": 3.0,
              "effects": [{"generator": "grunge", "op": "multiply", "amount": 0.85, "scale": 2.0, "softness": 0.2}]}, opacity=0.95, channels=NO_HEIGHT, **v),
        fill("Beater: dirty glass", P.group("glass"), {"base_color": [0.18, 0.17, 0.15], "roughness": 0.5, "opacity": 0.6},
             {"generator": "grunge", "amount": 0.5, "scale": 3.0, "softness": 0.3}, opacity=0.5, channels=NO_HEIGHT, **v),
    ]


# ------------------------------------------------------------------ geometry helpers for decals


class Frame:
    """Spec frame (Blender, before the ride-height drop) -> Pigment / glTF world."""

    def __init__(self, spec, fv):
        self.drop = spec["body_drop"]
        ws = max(w for _, w in spec["body"]["wside"])
        self.side_x = fv.get("side_x", ws + 0.01)
        self.front = spec["front"]
        self.rear = fv.get("rear_y", spec["rear"])

    def g(self, x, y, z):
        return [round(x, 4), round(z - self.drop, 4), round(-y, 4)]


def variant_decals(fr, P, vname, entries, enabled):
    grp = f"v_{vname}"
    out = []
    for i, e in enumerate(entries):
        kind, img = e[0], e[1]
        nm = f"{vname}_{i}_{Path(img).stem}"
        kw = dict(variant=grp, enabled=enabled, overlap_order=1 if "graffiti" not in img and "stencil" not in img else 2)
        if "graffiti" in img or "stencil" in img:
            kw.update(wear=0.25, fade=0.3, wear_style="grunge")
        if kind in ("side", "side_same", "left", "right"):
            y, z, w = e[2], e[3], e[4]
            sides = {"side": (1, -1), "side_same": (1, -1), "left": (1,), "right": (-1,)}[kind]
            for sx in sides:
                im = img
                if kind == "side" and sx < 0:
                    r = img[:-4] + "_r.png"
                    if (ROOT / r).exists():
                        im = r
                out.append(decal(im, fr.g(sx * fr.side_x, y, z), [sx, 0, 0], w, name=f"{nm}_{'L' if sx > 0 else 'R'}", **kw))
        elif kind == "top":
            y, z, w, rot = e[2], e[3], e[4], e[5]
            out.append(decal(img, fr.g(0.0, y, z), [0, 1, 0], w, rotation=rot, name=nm, **kw))
        elif kind == "rear":
            x, z, w = e[2], e[3], e[4]
            out.append(decal(img, fr.g(x, fr.rear, z), [0, 0, -1], w, name=nm, **kw))
        elif kind == "front":
            x, z, w = e[2], e[3], e[4]
            out.append(decal(img, fr.g(x, fr.front, z), [0, 0, 1], w, name=nm, **kw))
    return out


def plate_decals(P, vname, img, enabled):
    out = []
    for pid in P.named("plate_F", "plate_R"):
        out.append(part_decal(img, pid, fit="fill", margin=0.0, name=f"plate_{vname}_{pid}", variant=f"v_{vname}", enabled=enabled))
    return out


def variant_paint_layers(P, v, paint_parts, first):
    """Paint, accents, cargo colour and hidden parts for one variant (all tagged v_<name>)."""
    grp = f"v_{v['name']}"
    vis = dict(variant=grp, visible=first)
    L = []
    if v.get("paint"):
        L.append(fill(f"Paint: {v['name']}", paint_parts, F.PAINT[v["paint"]], channels=NO_HEIGHT, **vis))
    for k, a in enumerate(v.get("accents", [])):
        ids = [i for i in P.named(*a["parts"]) if P.m[i][1] in ("paint", "cargo")]
        if not ids:
            continue
        vals = F.PAINT[a["paint"]] if "paint" in a else a["values"]
        L.append(fill(f"Accent: {v['name']} {k}", ids, vals, channels=NO_HEIGHT, **vis))
    if v.get("cargo") and P.group("cargo"):
        L.append(fill(f"Box: {v['name']}", P.group("cargo"), v["cargo"], channels=NO_HEIGHT, **vis))
    return L


# ------------------------------------------------------------------ generic body recipe


def body_script(vid, P, spec, fv, pt):
    paint = P.group("paint")
    exterior = P.group("paint", "frit", "black_trim", "rubber", "chrome", "grille", "black_metal", "mirror", "plate", "exhaust",
                       "glass", "lens_clear", "lens_red", "lens_amber", "cargo", "cargo_frame")
    fr = Frame(spec, fv)
    variants = fv["variants"]
    L = [{"tool": "new_project", "args": {"mesh": pt["mesh_body"], "resolution": fv["res"], "material": "Matte black"}}]
    L += trims_block(P)
    L += extra_groups_block(P, spec)
    for i, v in enumerate(variants):
        L += variant_paint_layers(P, v, paint, i == 0)
    L += lamps_block(P)
    L += light_wear_block(P, paint, exterior)
    for v in variants:
        if v.get("rusty"):
            L += heavy_wear_block(P, paint, exterior, f"v_{v['name']}")
    # decals: liveries per variant, plates, badges, screens
    for i, v in enumerate(variants):
        L += variant_decals(fr, P, v["name"], v.get("decals", []), i == 0)
        if v.get("plate"):
            L += plate_decals(P, v["name"], v["plate"], i == 0)
    if fv.get("badge"):
        L.append(decal(fv["badge"], fr.g(-0.30 * fr.side_x, fr.rear, spec.get("badge_z", 0.0) or badge_z(spec)), [0, 0, -1], 0.17,
                       name="badge", overlap_order=1))
    for pid in P.named("dash_gauges"):
        L.append(part_decal(DEC + "gauges.png", pid, fit="fill", margin=0.0, emissive_strength=1.5, name="gauges"))
    for pid in P.named("nav_screen", "fare_screen", "terminal_screen"):
        L.append(part_decal(STORY + "billboard_score.png", pid, fit="fill", margin=0.0, emissive_strength=1.2, name=f"screen_{pid}"))
    for pid in P.named("roof_sign_face"):
        L.append(part_decal(STORY + "billboard_meridian.png", pid, fit="fill", margin=0.0, emissive_strength=2.0, name=f"roof_sign_{pid}"))
    return L


def badge_z(spec):
    """A height on the tail for the model badge: just under the rear glass / on the tailgate."""
    rw = spec["panels"].get("rear_window") or {}
    if rw.get("kind") == "rear":
        return rw["zb"] - 0.07
    zb = [z for y, z in spec["body"]["zbelt"]]
    return max(zb) - 0.04


def variants_def(fv):
    # one seed for every variant: the wear masks match, so maps that don't depend on the paint
    # (normal, AO, often the coat) are identical and stored once in the glb
    return [{"name": v["name"], "seed": 11, "disable": ["*"], "enable": [f"v_{v['name']}"]} for v in fv["variants"]]


def body_finish(L, vid, fv, pt, variants):
    v = {"yaw": 215, "pitch": 14, "width": 900, "height": 560, "lighting": "night", "bloom": True}
    L += [
        {"tool": "save_project", "args": {"path": f"{pt['projects']}/{vid}_body.pigment"}},
        {"tool": "export_variants", "args": {"dir": pt["textures"], "name": f"{vid}_body", "variants": variants, "preview": dict(v, dir=str(TMP / vid))}},
        {"tool": "save_project", "args": {"path": f"{pt['projects']}/{vid}_body.pigment"}},
    ]
    return L


# ------------------------------------------------------------------ wheels


def wheel_script(vid, P, fv, pt):
    tyre = P.group("tyre")
    rim = P.group("rim")
    rim_vals = F.RIMS[fv["rim"]] if fv.get("rim") else {"base_color": [0.13, 0.13, 0.14], "metallic": 0.85, "roughness": 0.3, "coat": 1.0, "coat_roughness": 0.05, "flake": 0.08}
    L = [
        {"tool": "new_project", "args": {"mesh": pt["mesh_wheel"], "resolution": fv["wheel_res"], "material": "Black rubber"}},
        fill("Tyre rubber", tyre, RUBBER, channels=NO_HEIGHT),
        fill("Tread scuff", tyre, {"base_color": [0.04, 0.04, 0.04], "roughness": 0.95},
             {"generator": "edge_wear", "amount": 0.45, "softness": 0.15, "breakup": 0.5}, opacity=0.8, channels=NO_HEIGHT),
        fill("Rim paint", rim, dict(rim_vals), channels=NO_HEIGHT),
        fill("Rim lip polish", rim, {"base_color": [0.8, 0.8, 0.82], "metallic": 1.0, "roughness": 0.15, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.3 if "steel" not in fv.get("rim", "") else 0.12, "softness": 0.04, "breakup": 0.3}, channels=NO_HEIGHT),
    ]
    if P.group("lug"):
        L.append(fill("Lug nuts", P.group("lug"), CHROME, channels=NO_HEIGHT))
    if P.group("rim_dark"):
        L.append(fill("Rim inserts", P.group("rim_dark"), {"base_color": [0.02, 0.022, 0.025], "metallic": 0.3, "roughness": 0.25, "coat": 1.0, "coat_roughness": 0.03},
                      channels=NO_HEIGHT))
    L += [
        fill("Disc steel", P.group("brake_disc"), {"base_color": [0.42, 0.41, 0.4], "metallic": 1.0, "roughness": 0.38}, channels=NO_HEIGHT),
        fill("Disc rust", P.group("brake_disc"), None, "Rust", {"generator": "grunge", "amount": 0.45, "scale": 12.0, "softness": 0.25}, opacity=0.85),
        fill("Caliper paint", P.group("caliper"), {"base_color": [0.75, 0.16, 0.03], "metallic": 0.0, "roughness": 0.35, "coat": 0.8, "coat_roughness": 0.08}
             if vid != "kago" else {"base_color": [0.1, 0.55, 0.65], "metallic": 0.0, "roughness": 0.35, "coat": 0.8, "coat_roughness": 0.08}, channels=NO_HEIGHT),
        fill("Brake dust", rim + P.group("caliper", "lug"), {"base_color": [0.1, 0.075, 0.055], "metallic": 0.0, "roughness": 0.85, "coat": 0.0},
             {"generator": "dirt", "amount": 0.5, "softness": 0.2, "breakup": 0.6}, opacity=0.8, channels=NO_HEIGHT),
        fill("Sidewall dust", tyre, {"base_color": [0.28, 0.26, 0.23], "roughness": 0.95},
             {"generator": "grunge", "amount": 0.42, "scale": 6.0, "softness": 0.3}, opacity=0.55, channels=NO_HEIGHT),
        fill("Road grime", tyre + rim, {"base_color": [0.12, 0.105, 0.09], "roughness": 0.9, "coat": 0.0},
             {"generator": "dirt", "amount": 0.4, "softness": 0.3, "breakup": 0.7}, opacity=0.6, channels=NO_HEIGHT),
    ]
    for pid in tyre[:1]:
        L.append(part_decal(fv["tyre"], pid, facing="+x", fit="contain", margin=0.0, name="sidewall",
                            values={"roughness": 0.7}, channels=["base_color", "roughness"]))
    for pid in P.group("caliper")[:1]:
        L.append(part_decal(fv.get("caliper_logo", DEC + "caliper_logo.png"), pid, facing="+x", fit="contain", margin=0.2, name="caliper_logo"))
    L += [
        {"tool": "save_project", "args": {"path": f"{pt['projects']}/{vid}_wheel.pigment"}},
        {"tool": "export_textures", "args": {"dir": f"{pt['textures']}/{vid}_wheel", "name": f"{vid}_wheel", "preset": "separate"}},
    ]
    return L


# ------------------------------------------------------------------ the hero (authored recipe + fleet variants)


def hero_body_script(P, pt, fv, spec):
    """tools/car/car_textures.py's body recipe, unchanged for `security` and `cab`, plus the
    fleet variants (civilian paints, executive, Hinode taxi, beater) as extra tagged layers."""
    BODY_DROP = 0.03

    def bl(x, y, z):
        return [round(x, 4), round(z - BODY_DROP, 4), round(-y, 4)]
    paint = P.group("paint")
    doors = P.named("door_F", "door_R")
    doors = [i for i in doors if P.m[i][1] == "paint"]
    shell = P.named("body_shell")
    hood = P.named("hood")
    exterior = P.group("paint", "frit", "black_trim", "rubber", "chrome", "grille", "black_metal", "mirror", "plate", "exhaust",
                       "glass", "lens_clear", "lens_red", "lens_amber")
    extra = [v for v in fv["variants"] if v["name"] not in ("security", "cab")]
    security_gear = P.group("lightbar_lens_red", "lightbar_lens_blue", "lightbar_center", "emitter_red", "emitter_blue") + \
        P.named("lightbar_", "push_bar", "spotlight_", "partition", "terminal")
    L = [
        {"tool": "new_project", "args": {"mesh": pt["mesh_body"], "resolution": fv["res"], "material": "Matte black"}},
    ] + trims_block(P) + [
        fill("Paint: midnight candy", paint, MIDNIGHT_CANDY, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Paint: pearl doors", doors, PEARL_WHITE, channels=NO_HEIGHT, variant="livery_hs"),
        fill("Paint: cab teal", paint, TEAL_CANDY, channels=NO_HEIGHT, variant="livery_cab", visible=False),
        fill("Paint: cab cream hood", hood, CREAM_PAINT, channels=NO_HEIGHT, variant="livery_cab", visible=False),
    ]
    for v in extra:
        L += variant_paint_layers(P, v, paint, False)
    L += [
        fill("Glass", P.group("glass"), GLASS, channels=NO_HEIGHT),
        fill("Ceramic frit", P.group("frit"), {"base_color": [0.012, 0.012, 0.013], "metallic": 0.0, "roughness": 0.18}, channels=NO_HEIGHT),
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
        fill("Cab sign LEDs", P.group("emitter_red", "emitter_blue"), {"base_color": [0.95, 0.6, 0.1], "roughness": 0.2, "metallic": 0.0, "emissive": [1.0, 0.62, 0.15], "emissive_strength": 3.0}, channels=NO_HEIGHT, variant="livery_cab", visible=False),
        fill("Cab sign lenses", P.group("lightbar_lens_red", "lightbar_lens_blue"), {"base_color": [0.95, 0.75, 0.3], "roughness": 0.08, "metallic": 0.0, "opacity": 0.55, "transmission": 0.6}, channels=NO_HEIGHT, variant="livery_cab", visible=False),
    ]
    # fleet variants: taxi signs reuse the light bar, civilians lose the security gear (fully transparent)
    for v in extra:
        grp = f"v_{v['name']}"
        if v.get("taxi_sign"):
            L.append(fill(f"Taxi sign LEDs: {v['name']}", P.group("emitter_red", "emitter_blue"), emit([0.95, 0.55, 0.1], [1.0, 0.55, 0.12], 3.0),
                          channels=NO_HEIGHT, variant=grp, visible=False))
            L.append(fill(f"Taxi sign lenses: {v['name']}", P.group("lightbar_lens_red", "lightbar_lens_blue"),
                          {"base_color": [0.95, 0.70, 0.30], "roughness": 0.08, "metallic": 0.0, "opacity": 0.55, "transmission": 0.6},
                          channels=NO_HEIGHT, variant=grp, visible=False))
        if v.get("civilian"):
            L.append(fill(f"No security gear: {v['name']}", security_gear, HIDDEN, channels={"opacity": True, "transmission": True},
                          variant=grp, visible=False))
    L += [
        fill("Coat haze", paint, {"coat_roughness": 0.22}, None, {"generator": "grunge", "amount": 0.35, "scale": 1.6, "softness": 0.3},
             opacity=0.5, channels={"base_color": False, "roughness": False, "metallic": False, "height": False}),
        fill("Fine scratches", paint, {"base_color": [0.4, 0.42, 0.45], "roughness": 0.45, "coat": 0.0},
             {"generator": "scratches", "amount": 0.15, "scale": 4.0}, opacity=0.2, channels=NO_HEIGHT),
        fill("Edge chips: primer", paint, {"base_color": [0.36, 0.37, 0.38], "metallic": 0.0, "roughness": 0.65, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.2, "softness": 0.04, "breakup": 0.7, "scale": 6.0}, channels=NO_HEIGHT),
        fill("Edge chips: bare steel", paint, {"base_color": [0.5, 0.5, 0.52], "metallic": 1.0, "roughness": 0.35, "coat": 0.0, "flake": 0.0},
             {"generator": "edge_wear", "amount": 0.1, "softness": 0.03, "breakup": 0.8, "scale": 8.0}, channels=NO_HEIGHT),
        fill("Arch rust", paint + P.group("underbody_metal"), {"coat": 0.0, "flake": 0.0}, "Rust",
             {"generator": "edge_wear", "amount": 0.45, "softness": 0.1, "breakup": 0.6, "scale": 5.0,
              "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.22, "softness": 0.06, "breakup": 0.3},
                          {"generator": "spots", "op": "multiply", "amount": 0.5, "scale": 6.0, "softness": 0.15}]}, channels=NO_HEIGHT),
        fill("Rust bloom", shell, {"base_color": [0.3, 0.16, 0.08], "roughness": 0.8, "coat": 0.0, "flake": 0.0},
             {"generator": "spots", "amount": 0.35, "scale": 9.0, "softness": 0.2,
              "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.2, "softness": 0.06, "breakup": 0.4}]}, opacity=0.45, channels=NO_HEIGHT),
        fill("Gap grime", exterior, {"base_color": [0.06, 0.055, 0.05], "roughness": 0.85, "coat": 0.0},
             {"generator": "dirt", "amount": 0.45, "softness": 0.2, "breakup": 0.5}, opacity=0.85, channels=NO_HEIGHT),
        fill("Rain streaks", P.group("paint", "chrome", "black_trim"), {"base_color": [0.08, 0.075, 0.07], "roughness": 0.55, "coat_roughness": 0.3},
             {"generator": "leaks", "amount": 0.45, "scale": 3.0, "breakup": 0.6, "drip_length": 0.6, "ao_influence": 0.3, "softness": 0.15},
             opacity=0.55, channels=NO_HEIGHT),
        fill("Water spots", P.group("glass"), {"base_color": [0.2, 0.2, 0.2], "roughness": 0.25, "opacity": 0.55},
             {"generator": "spots", "amount": 0.15, "scale": 40.0, "softness": 0.1}, opacity=0.3, channels=NO_HEIGHT),
        fill("Road dirt", exterior + P.group("underbody"), ROAD_DIRT,
             {"generator": "gradient", "amount": 0.2, "softness": 0.05, "breakup": 0.55, "scale": 3.0,
              "effects": [{"generator": "grunge", "op": "multiply", "amount": 0.75, "scale": 2.5, "softness": 0.25}]},
             opacity=0.9, channels=NO_HEIGHT),
        fill("Road spray", exterior, {"base_color": [0.12, 0.11, 0.1], "roughness": 0.7, "coat_roughness": 0.4},
             {"generator": "gradient", "amount": 0.32, "softness": 0.12, "breakup": 0.7, "scale": 6.0}, opacity=0.35, channels=NO_HEIGHT),
        fill("Cabin dust", P.group("interior_dark", "interior_plastic", "interior_carpet"), {"base_color": [0.12, 0.11, 0.1], "roughness": 0.9},
             {"generator": "dirt", "amount": 0.35, "softness": 0.3}, opacity=0.4, channels=NO_HEIGHT),
    ]
    for v in extra:
        if v.get("rusty"):
            L += heavy_wear_block(P, paint, exterior, f"v_{v['name']}")
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
        decal(STORY + "graffiti_unplug.png", bl(-0.885, 1.47, 0.70), [-1, 0, 0], 0.5, name="unplug_tag", variant="story", overlap_order=2, wear=0.35, fade=0.45, wear_style="grunge"),
        decal(STORY + "stencil_eye_crossed.png", bl(0.885, 1.50, 0.70), [1, 0, 0], 0.22, name="eye_stencil", variant="story", overlap_order=2, wear=0.2, fade=0.3),
    ]
    for pid in P.named("plate_F", "plate_R"):
        L.append(part_decal(DEC + "plate_hs.png", pid, fit="fill", margin=0.0, name=f"plate_hs_{pid}", variant="livery_hs"))
        L.append(part_decal(DEC + "plate_cab.png", pid, fit="fill", margin=0.0, name=f"plate_cab_{pid}", variant="livery_cab", enabled=False))
    for pid in P.named("dash_gauges"):
        L.append(part_decal(DEC + "gauges.png", pid, fit="fill", margin=0.0, emissive_strength=1.5, name="gauges"))
    for pid in P.named("terminal_screen"):
        L.append(part_decal(STORY + "billboard_score.png", pid, fit="fill", margin=0.0, emissive_strength=1.2, name="terminal"))
    fr = Frame(spec, fv)
    for v in extra:
        L += variant_decals(fr, P, v["name"], v.get("decals", []), False)
        if v.get("plate"):
            L += plate_decals(P, v["name"], v["plate"], False)
    return L


def hero_variants(fv):
    out = [{"name": "security", "disable": ["livery_cab"], "enable": ["livery_hs", "story"]},
           {"name": "cab", "disable": ["livery_hs"], "enable": ["livery_cab", "story"]}]
    for i, v in enumerate(fv["variants"]):
        if v["name"] in ("security", "cab"):
            continue
        en = [f"v_{v['name']}"] + (["story"] if v.get("rusty") else [])
        out.append({"name": v["name"], "seed": 31, "disable": ["livery_hs", "livery_cab", "story"] + [f"v_{w['name']}" for w in fv["variants"]
                                                                                                        if w["name"] not in ("security", "cab")],
                    "enable": en})
    return out


# ------------------------------------------------------------------ main


def load_spec(vid):
    mod = importlib.import_module(f"specs.{vid}")
    return mod.SPEC


def texture(vid, what, no_run=False):
    pt = paths(vid)
    fv = dict(F.VEHICLES[vid])
    if os.environ.get("FLEET_RES"):
        # e.g. FLEET_RES=2048 when the GPU is shared and a 4K body runs out of memory
        fv["res"] = min(fv["res"], int(os.environ["FLEET_RES"]))
    spec = load_spec(vid)
    fv["id"] = vid
    parts = json.loads((pt["src"] / f"{vid}_parts.json").read_text())
    for w in what:
        mesh = pt["mesh_body"] if w == "body" else pt["mesh_wheel"]
        P = Parts(match_parts(pigment_parts(mesh), parts[w]))
        if w == "body":
            if vid == "tsubame":
                L = body_finish(hero_body_script(P, pt, fv, spec), vid, fv, pt, hero_variants(fv))
            else:
                L = body_finish(body_script(vid, P, spec, fv, pt), vid, fv, pt, variants_def(fv))
        else:
            L = wheel_script(vid, P, fv, pt)
        L = [l for l in L if l is not None]
        path = pt["scripts"] / f"{vid}_{w}.jsonl"
        if no_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in L) + "\n", encoding="utf8")
            print("wrote", path)
            continue
        out = run(L, f"{vid}_{w}", keep=path)
        print(f"[textures] {vid} {w}: {len(L)} steps")
        for line in out.splitlines():
            if line.startswith("[export") or "warning" in line.lower():
                print("  ", line[:300])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    parts = [a for a in args if a in ("body", "wheel")] or ["body", "wheel"]
    names = [a for a in args if a not in ("body", "wheel")]
    if names == ["all"] or not names:
        from specs import FLEET
        names = FLEET
    for vid in names:
        texture(vid, parts, "--no-run" in sys.argv)


if __name__ == "__main__":
    main()
