"""Natural ground textures for the open world, authored in Pigment.

Nine seamless PBR tiles (flat sheet projects, see docs/agents/roads/NOTES.md),
built from the ground generators (docs/agents/ground/NOTES.md): Voronoi cells,
scatter (pebbles, chips, leaves, needles, twigs, shells, clover), ridged rock,
grass blades and wind ripples, stacked with height blend (small stones settle
between big ones, sand and water fill the lows, moss and lichen sit on the
tops), per-instance jitter and height gain.

| set           | tile  | what |
|---------------|-------|------|
| rock_cliff    | 4 m   | strata ledges, block-joint fractures, water stains, lichen, debris on the ledges |
| scree         | 2 m   | angular boulders, stones, gravel and fines settling between them, dust, lichen |
| forest_floor  | 2 m   | humus, pine needles, fallen leaves, twigs, cones of moss |
| grass_turf    | 2 m   | dense blades in clumps over thatch, dry tips and dry patches, clover |
| dirt_mud      | 4 m   | packed earth, clods, pebbles, tyre ruts, puddles and wet mud in the lows |
| beach_sand    | 4 m   | wind ripples, heavy minerals in the troughs, shells and fragments, damp patches |
| cracked_mud   | 3 m   | dried clay plates with curled rims, deep and fine cracks, dust |
| cobbles       | 2 m   | granite setts in running bond, polished tops, grimy and mossy joints, weeds |
| vacant_lot    | 4 m   | broken concrete slabs, gravel and soil, cracks, weeds, stains, litter |

Each exports BaseColor, Roughness, Normal (OpenGL), Height and AO (+ Metallic)
to scenes/town/textures/world/<name>/ (git-ignored) and saves
scenes/world/projects/ground/<name>.pigment. The scripts are written to
scenes/world/scripts/ground/<name>.jsonl.

    python tools/ground_textures.py                       write + run every set (4096)
    python tools/ground_textures.py scree cobbles         some of them
    python tools/ground_textures.py --res 1024 ...        quick look
    python tools/ground_textures.py --no-run              only write the scripts (city build recipe)

Height units: Pigment's height-to-normal treats a height step of 1 over 1/256
of the tile as 45 degrees, so one unit is size_m / 256 metres (1.56 cm on a
4 m tile). Relief beyond -1..1 comes from `height_gain` (the composited stack
is HDR; the exported height map clamps to -1..1).
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
TEX = "scenes/town/textures/world"
PROJ = "scenes/world/projects/ground"
SCRIPTS = ROOT / "scenes" / "world" / "scripts" / "ground"
DECALS = ROOT / "assets" / "decals" / "ground"
RES = 4096


def g(gen, **kw):
    d = {"generator": gen}
    d.update(kw)
    return d


def L(name, color=None, mask=None, **kw):
    """A fill layer. color sRGB; kw: height, roughness, metallic -> values; anything else is an add_layer arg."""
    vals = {}
    if color is not None:
        vals["base_color"] = list(color)
    for k in ("height", "roughness", "metallic"):
        if k in kw:
            vals[k] = kw.pop(k)
    a = {"name": name, "values": vals}
    if mask is not None:
        a["mask"] = mask
    a.update(kw)
    return a


def sheet(name, size, base, layers, extra=(), res=None, post=()):
    """new tile project -> base -> layers -> (decals) -> post layers -> export + save."""
    res = res or RES
    S = [{"tool": "new_project", "args": {"tile": {"size_m": [size, size], "name": name}, "resolution": res, "material": "Concrete"}},
         {"tool": "delete_layer", "args": {"layer": "Paint"}},
         {"tool": "update_layer", "args": {"layer": "Base", "values": base}}]
    S += [{"tool": "add_layer", "args": a} for a in layers]
    S += list(extra)
    S += [{"tool": "add_layer", "args": a} for a in post]
    S += [{"tool": "export_textures", "args": {"dir": f"{TEX}/{name}", "name": name, "preset": "separate"}},
          {"tool": "save_project", "args": {"path": f"{PROJ}/{name}.pigment"}}]
    return S


NO_H = {"height": False}


# ------------------------------------------------------------------ rock cliff
def rock_cliff():
    """Layered, fractured cliff rock: strata ledges along the tile's v (= up when
    projected on a cliff), block joints, water stains running down, lichen on
    the faces, debris and moss on the ledges."""
    rock = dict(scale=0.55, strata=0.75, cracks=1.1, bands=1.4, streaks=0.7, warp=0.9, crack_scale=0.8, seed=3)
    return sheet("rock_cliff", 4.0, {"base_color": [0.29, 0.275, 0.255], "roughness": 0.82, "height": 0.0}, [
        L("Rock mass", (0.34, 0.32, 0.295), g("rock", **rock), height=1.0, height_profile=True, height_gain=6.0,
          jitter={"value": 0.12, "hue": 0.015, "saturation": 0.15, "roughness": 0.06}),
        L("Fracture faces", (0.4, 0.38, 0.35), g("cells", variant="plates", scale=2.6, stretch=1.4, randomness=0.9, edge_width=0.05, edge_noise=0.8, warp=0.4, height_variation=0.8, seed=5),
          height=1.0, height_profile=True, height_gain=1.6, opacity=0.8, blend={"height": "add"}, jitter={"value": 0.15}),
        L("Grain", (0.33, 0.31, 0.29), g("rock", scale=5.0, strata=0.1, cracks=0.3, warp=0.5, streaks=0.0, crack_scale=4.0, seed=7),
          height=0.6, height_profile=True, height_gain=1.0, opacity=0.6, blend={"height": "add"}),
        L("Crystals", (0.52, 0.5, 0.47), g("scatter", variant="chip", scale=160.0, density=0.5, size=0.45, irregularity=0.8, seed=9),
          height=0.25, height_profile=True, opacity=0.55, blend={"height": "add"}, jitter={"value": 0.4}),
        L("Joints", (0.07, 0.065, 0.06), g("rock", variant="cracks", amount=0.5, softness=0.3, **rock), height=-1.0, height_gain=2.5,
          blend={"height": "add"}, roughness=0.95),
        L("Water stains", (0.12, 0.11, 0.1), g("rock", variant="streaks", amount=0.42, softness=0.12, **rock), opacity=0.55, channels=NO_H, roughness=0.6),
        L("Iron stains", (0.42, 0.25, 0.13), g("rock", variant="streaks", amount=0.25, softness=0.15, **dict(rock, seed=11)), opacity=0.35, channels=NO_H),
        L("Ledge debris", (0.36, 0.33, 0.29), g("scatter", variant="chip", scale=40.0, density=0.85, size=0.5, per_cell=2, irregularity=0.7, seed=13,
                                                 effects=[{"generator": "rock", "op": "multiply", "variant": "ledges", "amount": 0.75, "softness": 0.2, **rock}]),
          height=1.0, height_profile=True, height_gain=1.5, height_blend={"mode": "above", "contrast": 0.3}, jitter={"value": 0.3}),
        L("Ledge moss", (0.11, 0.15, 0.05), g("rock", variant="ledges", amount=0.6, softness=0.25, **rock,
                                               effects=[{"generator": "spots", "op": "multiply", "amount": 0.4, "scale": 2.5, "softness": 0.2, "breakup": 0.6, "seed": 14}]),
          channels=NO_H, roughness=0.95, opacity=0.7),
        L("Lichen grey", (0.55, 0.55, 0.5), g("spots", amount=0.12, scale=11.0, softness=0.05, breakup=0.8, seed=15),
          height_blend={"mode": "below", "offset": 2.0, "contrast": 0.8}, channels=NO_H, roughness=0.9, opacity=0.55),
        L("Lichen yellow", (0.5, 0.46, 0.2), g("spots", amount=0.05, scale=16.0, softness=0.04, breakup=0.8, seed=17),
          height_blend={"mode": "below", "offset": 2.5, "contrast": 0.8}, channels=NO_H, roughness=0.9, opacity=0.5),
        L("Weathering", (0.4, 0.38, 0.35), g("grunge", amount=0.4, scale=0.5, softness=0.35, seed=19), opacity=0.35, channels=NO_H),
        L("Warm tone", (0.38, 0.3, 0.22), g("grunge", amount=0.35, scale=0.35, softness=0.35, seed=20), opacity=0.45, channels=NO_H),
        L("Cool tone", (0.24, 0.25, 0.26), g("grunge", amount=0.3, scale=0.6, softness=0.3, seed=22), opacity=0.4, channels=NO_H),
    ])


# ------------------------------------------------------------------ scree
def scree():
    """Angular talus: boulders, then stones, gravel and fines that only show
    where they lie above what is already there (they settle in the gaps)."""
    J = {"value": 0.3, "hue": 0.02, "saturation": 0.2, "roughness": 0.08}
    above = {"mode": "above", "contrast": 0.15}
    return sheet("scree", 2.0, {"base_color": [0.3, 0.28, 0.25], "roughness": 0.9, "height": 0.0}, [
        L("Fines", (0.33, 0.31, 0.28), g("scatter", variant="chip", scale=140.0, density=0.95, size=0.55, per_cell=2, irregularity=0.6, seed=21),
          height=0.3, height_profile=True, jitter={"value": 0.35}),
        L("Boulders", (0.4, 0.385, 0.36), g("scatter", variant="chip", scale=2.5, density=0.55, size=0.62, elongation=1.3, irregularity=0.7, height_variation=0.4, seed=23),
          height=1.0, height_profile=True, height_gain=7.0, height_blend=above, jitter=J),
        L("Stones", (0.42, 0.4, 0.37), g("scatter", variant="chip", scale=8.0, density=0.75, size=0.6, per_cell=2, elongation=1.4, irregularity=0.8, seed=25),
          height=1.0, height_profile=True, height_gain=3.5, height_blend=above, jitter=J),
        L("Gravel", (0.39, 0.37, 0.345), g("scatter", variant="chip", scale=26.0, density=0.85, size=0.58, per_cell=2, elongation=1.3, irregularity=0.8, seed=27),
          height=1.0, height_profile=True, height_gain=1.6, height_blend=above, jitter=J),
        L("Grit", (0.36, 0.34, 0.31), g("scatter", variant="pebble", scale=70.0, density=0.8, size=0.5, per_cell=2, seed=29),
          height=1.0, height_profile=True, height_gain=0.8, height_blend=above, jitter={"value": 0.4}),
        L("Edges", (0.5, 0.48, 0.45), g("edge_wear", amount=0.35, scale=8.0, breakup=0.4, seed=31), opacity=0.25, channels=NO_H),
        L("Shadowed gaps", (0.12, 0.11, 0.1), height_blend={"mode": "above", "offset": 0.5, "contrast": 0.4}, channels=NO_H, roughness=0.95, opacity=0.7),
        L("Dust", (0.42, 0.38, 0.32), g("grunge", amount=0.4, scale=1.1, softness=0.3, seed=37),
          height_blend={"mode": "above", "offset": 1.4, "contrast": 0.5}, channels=NO_H, roughness=0.95, opacity=0.45),
        L("Lichen", (0.55, 0.55, 0.48), g("spots", amount=0.1, scale=9.0, softness=0.03, breakup=0.6, seed=33),
          height_blend={"mode": "below", "offset": 4.0, "contrast": 0.5}, channels=NO_H, roughness=0.9, opacity=0.7),
        L("Lichen orange", (0.6, 0.35, 0.1), g("spots", amount=0.05, scale=14.0, softness=0.03, breakup=0.6, seed=35),
          height_blend={"mode": "below", "offset": 5.0, "contrast": 0.5}, channels=NO_H, roughness=0.9, opacity=0.6),
    ])


# ------------------------------------------------------------------ forest floor
def forest_floor():
    """Under the cedars and pines: dark humus, a mat of needles, fallen leaves
    and twigs, moss cushions, damp patches."""
    above = {"mode": "above", "contrast": 0.1}
    return sheet("forest_floor", 2.0, {"base_color": [0.075, 0.055, 0.04], "roughness": 0.85, "height": 0.0}, [
        L("Humus", (0.1, 0.075, 0.055), g("scatter", variant="pebble", scale=90.0, density=0.9, size=0.5, per_cell=2, irregularity=0.8, seed=41),
          height=0.4, height_profile=True, jitter={"value": 0.4}),
        L("Soil tone", (0.13, 0.095, 0.065), g("grunge", amount=0.45, scale=0.8, softness=0.3, seed=43), opacity=0.6, channels=NO_H),
        L("Old needles", (0.2, 0.13, 0.08), g("scatter", variant="twig", scale=35.0, density=0.9, size=0.04, elongation=16.0, per_cell=3, seed=45),
          height=1.0, height_profile=True, height_gain=0.8, height_blend=above, jitter={"value": 0.35, "hue": 0.02}, roughness=0.8),
        L("Needles", (0.42, 0.24, 0.11), g("scatter", variant="twig", scale=30.0, density=0.8, size=0.045, elongation=15.0, per_cell=3, seed=47,
                                            effects=[{"generator": "grunge", "op": "multiply", "amount": 0.6, "scale": 1.2, "softness": 0.3, "seed": 48}]),
          height=1.0, height_profile=True, height_gain=1.2, height_blend=above, jitter={"value": 0.35, "hue": 0.025, "saturation": 0.25}, roughness=0.7),
        L("Moss cushions", (0.09, 0.14, 0.045), g("scatter", variant="pebble", scale=240.0, density=0.95, size=0.6, per_cell=2, seed=49,
                                                 effects=[{"generator": "spots", "op": "multiply", "amount": 0.18, "scale": 4.0, "softness": 0.08, "breakup": 0.7, "seed": 50}]),
          height=1.0, height_profile=True, height_gain=1.2, height_blend=above, jitter={"value": 0.3, "hue": 0.03}, roughness=0.95),
        L("Leaves", (0.3, 0.17, 0.08), g("scatter", variant="leaf", scale=5.0, density=0.4, size=0.38, elongation=1.7, per_cell=2, irregularity=0.5, seed=51),
          height=1.0, height_profile=True, height_gain=1.6, height_blend=above, jitter={"value": 0.3, "hue": 0.025, "saturation": 0.2, "roughness": 0.1}, roughness=0.65),
        L("Dark leaves", (0.16, 0.1, 0.06), g("scatter", variant="leaf", scale=7.0, density=0.45, size=0.36, elongation=1.6, per_cell=2, irregularity=0.5, seed=53),
          height=1.0, height_profile=True, height_gain=1.3, height_blend=above, jitter={"value": 0.3, "hue": 0.03}, roughness=0.75),
        L("Twigs", (0.2, 0.15, 0.11), g("scatter", variant="twig", scale=2.2, density=0.6, size=0.05, elongation=11.0, per_cell=2, seed=55),
          height=1.0, height_profile=True, height_gain=3.0, height_blend=above, jitter={"value": 0.3}, roughness=0.8),
        L("Cones", (0.3, 0.19, 0.1), g("scatter", variant="pebble", scale=1.3, density=0.25, size=0.12, elongation=1.5, seed=57),
          height=1.0, height_profile=True, height_gain=4.0, height_blend=above, jitter={"value": 0.25}, roughness=0.7),
        L("Damp", (0.05, 0.04, 0.03), g("grunge", amount=0.35, scale=0.6, softness=0.3, seed=59), opacity=0.45, channels=NO_H, roughness=0.45),
    ])


# ------------------------------------------------------------------ grass / turf
def grass_turf():
    """Turf seen from above: thatch under dense blades in clumps, dry tips and
    dry patches, clover."""
    blades = dict(scale=95.0, density=0.95, length=0.075, lean=0.6, clumping=0.55, width=0.0032, swirl=0.6, seed=61)
    above = {"mode": "above", "contrast": 0.08}
    dry = [{"generator": "grunge", "op": "multiply", "amount": 0.52, "scale": 1.1, "softness": 0.1, "seed": 62}]
    return sheet("grass_turf", 2.0, {"base_color": [0.07, 0.055, 0.035], "roughness": 0.9, "height": 0.0}, [
        L("Thatch", (0.3, 0.26, 0.15), g("blades", scale=70.0, density=0.9, length=0.09, lean=0.97, clumping=0.2, width=0.0025, swirl=0.3, seed=63),
          height=1.0, height_profile=True, height_gain=0.5, jitter={"value": 0.35, "hue": 0.02}, roughness=0.85),
        L("Clover", (0.1, 0.24, 0.06), g("scatter", variant="clover", scale=14.0, density=0.85, size=0.4, per_cell=2, seed=65,
                                         effects=[{"generator": "spots", "op": "multiply", "amount": 0.4, "scale": 1.6, "softness": 0.06, "breakup": 0.4, "seed": 66}]),
          height=1.0, height_profile=True, height_gain=1.8, height_blend=above, jitter={"value": 0.2, "hue": 0.02, "saturation": 0.15}, roughness=0.6),
        L("Blades", (0.12, 0.22, 0.05), g("blades", **blades), height=1.0, height_profile=True, height_gain=2.0, height_blend=above,
          jitter={"value": 0.3, "hue": 0.03, "saturation": 0.2, "roughness": 0.1}, roughness=0.6),
        L("Blades fine", (0.15, 0.25, 0.07), g("blades", **dict(blades, scale=120.0, length=0.06, width=0.0024, seed=67)), height=1.0, height_profile=True,
          height_gain=1.9, height_blend=above, jitter={"value": 0.3, "hue": 0.03, "saturation": 0.2}, roughness=0.6),
        L("Dry tips", (0.45, 0.42, 0.22), g("blades", variant="tips", level=0.8, softness=0.05, **blades), channels=NO_H, opacity=0.6, roughness=0.8),
        L("Dry patches", (0.42, 0.37, 0.2), g("blades", variant="tips", level=0.35, softness=0.15, **blades, effects=dry), channels=NO_H, opacity=0.75, roughness=0.8),
        L("Bare soil", (0.12, 0.09, 0.06), g("grunge", amount=0.12, scale=0.9, softness=0.12, seed=69),
          height_blend={"mode": "above", "offset": 0.6, "contrast": 0.3}, channels=NO_H, opacity=0.6),
    ])


# ------------------------------------------------------------------ dirt / mud
def tyre_track():
    """A curved pair of tyre ruts with chevron tread (alpha = rut depth), 1.4 x 4 m."""
    from PIL import Image
    p = DECALS / "tyre_track.png"
    DECALS.mkdir(parents=True, exist_ok=True)
    w, h = 224, 640
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        bend = 14.0 * math.sin(t * math.pi)            # a gentle curve
        fade = min(1.0, t * 6.0, (1 - t) * 6.0)
        for x in range(w):
            a = 0.0
            for c in (w * 0.22, w * 0.78):
                d = (x - c - bend) / (w * 0.13)
                if abs(d) < 1.0:
                    prof = math.cos(d * math.pi / 2) ** 1.5
                    chev = 0.5 + 0.5 * math.sin((y / h * 60.0 + abs(d) * 2.2) * math.pi * 2)
                    a = max(a, prof * (0.75 + 0.25 * chev))
            px[x, y] = (255, 255, 255, int(255 * a * fade))
    img.save(p)
    return p.relative_to(ROOT).as_posix()


def dirt_mud():
    """A muddy track: packed earth, clods and pebbles, tyre ruts crossing, water
    and wet mud in every low via height blend."""
    track = tyre_track()
    ruts = []
    for (x, z, rot) in ((-0.7, 0.4, 10.0), (1.1, -0.5, -18.0)):
        ruts.append({"tool": "project_decal", "args": {"image": track, "layer": "Ruts", "position": [x, 0, z], "normal": [0, 1, 0], "size": [1.4, 4.0],
                                                       "rotation": rot, "tint": [0.13, 0.095, 0.065], "channels": ["base_color", "height"], "height": -1.0}})
    above = {"mode": "above", "contrast": 0.12}
    return sheet("dirt_mud", 4.0, {"base_color": [0.17, 0.125, 0.085], "roughness": 0.85, "height": 0.0}, [
        L("Packed earth", (0.2, 0.15, 0.1), g("rock", scale=1.2, strata=0.0, cracks=0.2, warp=0.6, streaks=0.0, crack_scale=3.0, seed=71),
          height=1.0, height_profile=True, height_gain=1.5, jitter={"value": 0.1}),
        L("Soil tone", (0.12, 0.085, 0.06), g("grunge", amount=0.45, scale=0.7, softness=0.3, seed=73), opacity=0.6, channels=NO_H),
        L("Clods", (0.19, 0.14, 0.095), g("scatter", variant="chip", scale=18.0, density=0.6, size=0.55, per_cell=2, irregularity=0.9, seed=75),
          height=1.0, height_profile=True, height_gain=1.4, height_blend=above, jitter={"value": 0.25, "hue": 0.015}),
        L("Grit", (0.26, 0.22, 0.17), g("scatter", variant="chip", scale=80.0, density=0.6, size=0.5, per_cell=2, seed=77),
          height=1.0, height_profile=True, height_gain=0.6, height_blend=above, jitter={"value": 0.4}),
        L("Pebbles", (0.28, 0.25, 0.21), g("scatter", variant="pebble", scale=7.0, density=0.12, size=0.35, elongation=1.3, irregularity=0.5, seed=79),
          height=1.0, height_profile=True, height_gain=2.0, height_blend=above, jitter={"value": 0.3, "hue": 0.02}, roughness=0.7),
        {"kind": "paint", "name": "Ruts"},
    ], extra=ruts, post=[
        L("Wet mud", (0.07, 0.05, 0.035), height_blend={"mode": "above", "offset": 0.35, "contrast": 0.3}, channels=NO_H, roughness=0.3),
        L("Puddles", (0.05, 0.04, 0.03), height=0.05, height_blend={"mode": "above", "contrast": 0.03}, roughness=0.03,
          mask=g("grunge", amount=0.75, scale=0.5, softness=0.3, seed=81)),
        L("Dry crust", (0.3, 0.24, 0.17), g("grunge", amount=0.3, scale=1.4, softness=0.2, seed=83),
          height_blend={"mode": "below", "offset": 1.0, "contrast": 0.4}, channels=NO_H, opacity=0.6, roughness=0.95),
    ])


# ------------------------------------------------------------------ beach sand
def beach_sand():
    """Wind-rippled beach: dark heavy minerals in the troughs, shells and shell
    grit, the odd pebble and wrack, damp patches."""
    rip = dict(scale=6.5, angle=18.0, irregularity=0.75, defects=0.55, asymmetry=0.65, sharpness=0.4, seed=91)
    above = {"mode": "above", "contrast": 0.08}
    return sheet("beach_sand", 4.0, {"base_color": [0.6, 0.53, 0.41], "roughness": 0.92, "height": 0.0}, [
        L("Ripples", (0.64, 0.57, 0.45), g("ripples", **rip), height=1.0, height_profile=True, height_gain=1.6),
        L("Swell", (0.6, 0.53, 0.41), g("ripples", scale=0.6, angle=-10.0, irregularity=1.0, defects=0.8, asymmetry=0.2, seed=93),
          height=1.0, height_profile=True, height_gain=1.5, blend={"height": "add"}, channels={"base_color": False}),
        L("Grain", (0.7, 0.64, 0.53), g("scatter", variant="pebble", scale=220.0, density=0.7, size=0.5, seed=95), height=0.15, height_profile=True,
          blend={"height": "add"}, jitter={"value": 0.5, "hue": 0.04}),
        L("Heavy minerals", (0.33, 0.3, 0.27), height_blend={"mode": "above", "offset": 0.55, "contrast": 0.25}, channels=NO_H, opacity=0.55,
          mask=g("grunge", amount=0.6, scale=0.8, softness=0.3, seed=97)),
        L("Shell grit", (0.85, 0.82, 0.76), g("scatter", variant="chip", scale=30.0, density=0.25, size=0.4, seed=99), height=1.0, height_profile=True,
          height_gain=0.8, height_blend=above, jitter={"value": 0.3, "hue": 0.05, "saturation": 0.4}, roughness=0.6),
        L("Shells", (0.86, 0.8, 0.72), g("scatter", variant="shell", scale=2.4, density=0.35, size=0.35, seed=101), height=1.0, height_profile=True,
          height_gain=2.5, height_blend=above, jitter={"value": 0.25, "hue": 0.06, "saturation": 0.5}, roughness=0.45),
        L("Pebbles", (0.55, 0.52, 0.47), g("scatter", variant="pebble", scale=4.0, density=0.08, size=0.25, elongation=1.4, seed=103), height=1.0,
          height_profile=True, height_gain=3.0, height_blend=above, jitter={"value": 0.35, "hue": 0.03}, roughness=0.5),
        L("Wrack", (0.2, 0.16, 0.08), g("scatter", variant="twig", scale=1.2, density=0.15, size=0.035, elongation=14.0, seed=105), height=1.0,
          height_profile=True, height_gain=1.5, height_blend=above, roughness=0.5),
        L("Damp", (0.36, 0.31, 0.24), g("grunge", amount=0.3, scale=0.35, softness=0.35, seed=107), opacity=0.6, channels=NO_H, roughness=0.55),
    ])


# ------------------------------------------------------------------ cracked mud
def cracked_mud():
    """Dried clay: polygon plates with curled rims, deep primary cracks, fine
    secondary cracks, a dusty crust."""
    cells = dict(scale=2.6, randomness=0.95, warp=0.25, edge_noise=0.7, seed=111)
    return sheet("cracked_mud", 3.0, {"base_color": [0.12, 0.09, 0.065], "roughness": 0.9, "height": -1.0}, [
        L("Plates", (0.42, 0.36, 0.29), g("cells", variant="plates", edge_width=0.018, height_variation=0.35, **cells), height=1.0, height_profile=True,
          height_gain=3.0, jitter={"value": 0.12, "hue": 0.01}),
        L("Curled rims", (0.46, 0.4, 0.32), g("cells", variant="edges", edge_width=0.07, amount=1.0, softness=0.02, **cells), height=1.0,
          height_profile=True, height_gain=0.9, blend={"height": "add"}, opacity=0.8),
        L("Cracks", (0.1, 0.075, 0.055), g("cells", variant="edges", edge_width=0.008, amount=0.5, softness=0.25, **cells), height=-1.0, height_gain=1.0,
          roughness=0.95),
        L("Fine cracks", (0.25, 0.19, 0.14), g("cells", variant="edges", scale=9.0, edge_width=0.0025, amount=0.55, softness=0.2, randomness=0.9,
                                                edge_noise=0.9, warp=0.3, seed=113, effects=[{"generator": "grunge", "op": "multiply", "amount": 0.6, "scale": 1.5, "seed": 114}]),
          height=-0.6, blend={"height": "add"}, opacity=0.9),
        L("Pores", (0.38, 0.3, 0.22), g("scatter", variant="pebble", scale=300.0, density=0.5, size=0.4, seed=115), height=-0.2, height_profile=True,
          blend={"height": "add"}, opacity=0.5),
        L("Dust", (0.58, 0.49, 0.37), g("grunge", amount=0.35, scale=0.9, softness=0.3, seed=117),
          height_blend={"mode": "below", "offset": 2.4, "contrast": 0.6}, channels=NO_H, opacity=0.6, roughness=0.97),
        L("Damp", (0.32, 0.25, 0.18), g("grunge", amount=0.35, scale=0.5, softness=0.35, seed=119), opacity=0.5, channels=NO_H),
        L("Dark crack fill", (0.08, 0.06, 0.045), height_blend={"mode": "above", "offset": -0.3, "contrast": 0.4}, channels=NO_H),
    ])


# ------------------------------------------------------------------ cobbles
def cobbles():
    """An old-town plaza: worn granite setts in rough rows (Voronoi cells close
    to a grid, stretched), domed and polished on top, grimy joints with moss
    and weeds."""
    setts = dict(scale=5.5, stretch=1.35, randomness=0.32, warp=0.12, edge_noise=0.35, seed=121)
    return sheet("cobbles", 2.0, {"base_color": [0.2, 0.185, 0.165], "roughness": 0.9, "height": 0.0}, [
        L("Joint sand", (0.26, 0.24, 0.2), g("scatter", variant="chip", scale=180.0, density=0.9, size=0.5, per_cell=2, seed=123), height=0.5,
          height_profile=True, jitter={"value": 0.4}),
        L("Setts", (0.43, 0.41, 0.38), g("cells", variant="plates", edge_width=0.03, height_variation=0.2, amount=0.55, softness=0.06, **setts), height=1.0,
          height_profile=True, height_gain=4.0, jitter={"value": 0.35, "hue": 0.04, "saturation": 0.6, "roughness": 0.15}, roughness=0.6),
        L("Sett crowns", None, g("cells", variant="dome", height_variation=0.3, **setts), height=1.0, height_profile=True, height_gain=1.2,
          blend={"height": "add"}, channels={"base_color": False, "roughness": False}),
        L("Sett relief", None, g("rock", scale=7.0, strata=0.0, cracks=0.0, warp=0.6, streaks=0.0, seed=125), height=1.0, height_profile=True,
          height_gain=0.6, blend={"height": "add"}, channels={"base_color": False, "roughness": False}),
        L("Granite speckle dark", (0.12, 0.12, 0.13), g("scatter", variant="chip", scale=260.0, density=0.45, size=0.45, seed=127), channels=NO_H, opacity=0.6),
        L("Granite speckle light", (0.72, 0.69, 0.65), g("scatter", variant="chip", scale=300.0, density=0.3, size=0.4, seed=129), channels=NO_H, opacity=0.4),
        L("Polished tops", (0.46, 0.45, 0.43), height_blend={"mode": "below", "offset": 4.4, "contrast": 0.6}, channels=NO_H, roughness=0.32, opacity=0.5),
        L("Chipped edges", (0.5, 0.49, 0.46), g("cells", variant="edges", edge_width=0.05, amount=0.6, softness=0.2, **setts,
                                                    effects=[{"generator": "grunge", "op": "multiply", "amount": 0.4, "scale": 6.0, "softness": 0.1, "seed": 126}]),
          channels=NO_H, opacity=0.35),
        L("Joint grime", (0.07, 0.065, 0.055), height_blend={"mode": "above", "offset": 1.6, "contrast": 0.5}, channels=NO_H, roughness=0.85, opacity=0.85),
        L("Joint moss", (0.09, 0.14, 0.045), g("grunge", amount=0.3, scale=1.2, softness=0.2, seed=131),
          height_blend={"mode": "above", "offset": 0.6, "contrast": 0.3}, channels=NO_H, roughness=0.95, opacity=0.85),
        L("Weeds", (0.14, 0.24, 0.06), g("blades", scale=60.0, density=0.5, length=0.05, lean=0.5, clumping=1.0, width=0.0035, seed=133,
                                          effects=[{"generator": "spots", "op": "multiply", "amount": 0.18, "scale": 2.0, "softness": 0.05, "seed": 134}]),
          height=1.0, height_profile=True, height_gain=2.0, height_blend={"mode": "above", "offset": 0.0, "contrast": 0.3}, jitter={"value": 0.3, "hue": 0.03}),
        L("Stains", (0.12, 0.11, 0.1), g("grunge", amount=0.35, scale=0.8, softness=0.3, seed=135), opacity=0.45, channels=NO_H),
        L("Gum", (0.5, 0.48, 0.45), g("scatter", variant="pebble", scale=4.0, density=0.1, size=0.1, seed=137), opacity=0.6, channels=NO_H, roughness=0.5),
    ])


# ------------------------------------------------------------------ urban vacant lot
def vacant_lot():
    """Industrial / port gaps: an old slab broken into pieces with some missing,
    gravel and soil between, cracks, weeds in every gap, stains and litter."""
    pieces = dict(scale=2.2, randomness=1.0, warp=0.3, edge_noise=0.8, seed=141)
    above = {"mode": "above", "contrast": 0.12}
    return sheet("vacant_lot", 4.0, {"base_color": [0.2, 0.17, 0.13], "roughness": 0.9, "height": 0.0}, [
        L("Soil", (0.17, 0.135, 0.1), g("rock", scale=1.5, strata=0.0, cracks=0.0, warp=0.6, streaks=0.0, seed=143), height=1.0, height_profile=True,
          height_gain=0.8),
        L("Gravel", (0.38, 0.36, 0.33), g("scatter", variant="chip", scale=40.0, density=0.85, size=0.55, per_cell=2, irregularity=0.8, seed=145,
                                           effects=[{"generator": "grunge", "op": "multiply", "amount": 0.65, "scale": 0.8, "softness": 0.3, "seed": 146}]),
          height=1.0, height_profile=True, height_gain=1.2, height_blend=above, jitter={"value": 0.35, "hue": 0.03, "saturation": 0.3}),
        L("Slabs", (0.33, 0.32, 0.3), g("cells", variant="plates", edge_width=0.012, height_variation=0.35, **pieces,
                                          effects=[{"generator": "tiles", "variant": "square", "op": "multiply", "scale": 0.5, "aspect": 1.0, "mortar": 0.012, "softness": 0.004},
                                                   {"generator": "cells", "variant": "value", "op": "multiply", "amount": 0.7, "softness": 0.01, **pieces}]),
          height=1.0, height_profile=True, height_gain=3.0, jitter={"value": 0.1, "roughness": 0.05}, roughness=0.8),
        L("Aggregate", (0.55, 0.53, 0.5), g("scatter", variant="chip", scale=120.0, density=0.5, size=0.45, seed=147),
          height_blend={"mode": "below", "offset": 2.2, "contrast": 0.3}, height=0.12, height_profile=True, blend={"height": "add"}, jitter={"value": 0.4}, opacity=0.6),
        L("Slab cracks", (0.08, 0.075, 0.07), g("cells", variant="edges", scale=3.0, edge_width=0.005, amount=0.45, softness=0.2, randomness=1.0, edge_noise=1.0,
                                                 warp=0.4, seed=149, effects=[{"generator": "grunge", "op": "multiply", "amount": 0.55, "scale": 1.0, "seed": 150}]),
          height=-1.0, height_gain=1.5, blend={"height": "add"}, height_blend={"mode": "below", "offset": 2.0, "contrast": 0.2}),
        L("Weeds", (0.12, 0.2, 0.05), g("blades", scale=55.0, density=0.75, length=0.12, lean=0.5, clumping=1.0, width=0.004, swirl=0.4, seed=151,
                                          effects=[{"generator": "grunge", "op": "multiply", "amount": 0.45, "scale": 0.9, "softness": 0.25, "seed": 152}]),
          height=1.0, height_profile=True, height_gain=2.5, height_blend={"mode": "above", "contrast": 0.2}, jitter={"value": 0.35, "hue": 0.04, "saturation": 0.25}),
        L("Dry weeds", (0.42, 0.37, 0.2), g("blades", scale=40.0, density=0.5, length=0.14, lean=0.7, clumping=1.0, width=0.003, seed=153), height=1.0,
          height_profile=True, height_gain=2.3, height_blend={"mode": "above", "contrast": 0.2}, jitter={"value": 0.3}),
        L("Rust stains", (0.3, 0.17, 0.08), g("spots", amount=0.08, scale=1.2, softness=0.15, breakup=0.5, seed=155), opacity=0.35, channels=NO_H),
        L("Oil", (0.03, 0.03, 0.03), g("spots", amount=0.06, scale=0.6, softness=0.2, breakup=0.4, seed=157), opacity=0.7, channels=NO_H, roughness=0.3),
        L("Litter", (0.8, 0.78, 0.72), g("scatter", variant="flake", scale=3.0, density=0.18, size=0.25, elongation=1.5, irregularity=0.6, seed=159), height=1.0,
          height_profile=True, height_gain=0.8, height_blend=above, jitter={"value": 0.4, "hue": 0.5, "saturation": 0.6}, roughness=0.6),
        L("Grime", (0.1, 0.09, 0.08), g("grunge", amount=0.45, scale=0.6, softness=0.3, seed=161), opacity=0.45, channels=NO_H),
        L("Water stains", (0.2, 0.19, 0.17), g("spots", amount=0.25, scale=0.5, softness=0.3, breakup=0.6, seed=163), opacity=0.4, channels=NO_H, roughness=0.6),
    ])


SETS = {"rock_cliff": rock_cliff, "scree": scree, "forest_floor": forest_floor, "grass_turf": grass_turf, "dirt_mud": dirt_mud,
        "beach_sand": beach_sand, "cracked_mud": cracked_mud, "cobbles": cobbles, "vacant_lot": vacant_lot}
# metres per tile (for the Blender / Godot materials)
TILE_M = {"rock_cliff": 4.0, "scree": 2.0, "forest_floor": 2.0, "grass_turf": 2.0, "dirt_mud": 4.0, "beach_sand": 4.0,
          "cracked_mud": 3.0, "cobbles": 2.0, "vacant_lot": 4.0}


def write(name, res=None):
    global RES
    if res:
        RES = res
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    p = SCRIPTS / f"{name}.jsonl"
    p.write_text("".join(json.dumps(l) + "\n" for l in SETS[name]()), encoding="utf8")
    return p


def run(p):
    r = subprocess.run([str(MCP), "--script", str(p)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{p.name}: {r.stderr[-3000:]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    res = None
    if "--res" in args:
        i = args.index("--res")
        res = int(args[i + 1])
        del args[i:i + 2]
    no_run = "--no-run" in args
    names = [a for a in args if not a.startswith("--")] or list(SETS)
    for n in names:
        if n not in SETS:
            raise SystemExit(f"unknown set {n!r} (one of {', '.join(SETS)})")
        p = write(n, res)
        if not no_run:
            import time
            t0 = time.time()
            run(p)
            print(f"{n}: {time.time() - t0:.0f} s -> {TEX}/{n}")
        else:
            print(f"wrote {p.relative_to(ROOT).as_posix()}")
