"""Open-world road textures, authored in Pigment.

    python tools/road_textures.py            # write stencils + scripts
    python tools/road_textures.py --run      # ...and run them (pigment-mcp --script)
    python tools/road_textures.py --run asphalt atlas    # only some

Writes:
    assets/decals/roads/*.png                 small shape stencils (alpha) the
                                              atlas script stamps with Pigment decals
    scenes/town/scripts/roads/<name>.jsonl    one Pigment script per texture
With --run, each script exports to scenes/town/textures/roads/<name>/ (git
ignored) and saves scenes/town/projects/roads/<name>.pigment.

Textures (all flat Pigment sheet projects, `new_project {tile: ...}`):
    asphalt   4 x 4 m seamless tile, 4096: binder, aggregate, worn binder,
              crack network + sealed cracks, damp patches
    paving    2 x 2 m seamless tile, 2048: 0.5 m concrete slabs, dark joints,
              moss in the joints, gum and stains
    setts     2 x 2 m seamless tile, 2048: granite setts in running bond
    concrete  2 x 2 m seamless tile, 2048: cast concrete, pores, hairline
              cracks, stains (retaining walls, stairs)
    trim      2 m road trim sheet, 2048: curb top, curb face, gutter, walk
              edge, kerb paint, drain grate strips (+ trim_layout.json)
    atlas     decal atlas, 4096: zebra bar, stop line, lane / edge lines,
              arrows, cracks, patches, manhole, drain grate, oil stains, tyre
              marks (+ atlas_layout.json, atlas_BaseColorAlpha.png)

The runtime side (tools/blender_town.py) uses world-space UVs on the asphalt
and paving, trim UVs on curbs and gutters, and decal quads cut from the atlas.
"""
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scenes" / "town" / "scripts" / "roads"
STENCILS = ROOT / "assets" / "decals" / "roads"
TEX = "scenes/town/textures/roads"
PROJ = "scenes/town/projects/roads"
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))


def rel(p):
    return Path(p).relative_to(ROOT).as_posix()


# ---------------------------------------------------------------- stencils


def stencils():
    """Shape masks (white, alpha = shape) for the atlas decals. Pigment adds
    every material, wear and relief; these are only outlines."""
    from PIL import Image, ImageDraw, ImageFilter
    STENCILS.mkdir(parents=True, exist_ok=True)
    out = {}

    def save(name, img):
        p = STENCILS / f"{name}.png"
        img.save(p)
        out[name] = rel(p)

    def mask_img(w, h, draw, blur=0.0):
        m = Image.new("L", (w, h), 0)
        draw(ImageDraw.Draw(m), w, h)
        if blur:
            m = m.filter(ImageFilter.GaussianBlur(blur))
        img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        img.putalpha(m)
        return img

    # soft ellipse: fades a decal's content out towards the cell border
    def ellipse(d, w, h):
        for k in range(40):
            t = k / 40
            a = int(255 * (1 - (1 - t) ** 2))
            ix, iy = w * 0.5 * (0.98 - 0.55 * t), h * 0.5 * (0.98 - 0.55 * t)
            d.ellipse([w / 2 - ix, h / 2 - iy, w / 2 + ix, h / 2 + iy], fill=a)
    save("soft_ellipse", mask_img(256, 256, ellipse, 6))

    # solid bar (joints, kerb paint blocks, skid bands)
    save("bar", mask_img(64, 64, lambda d, w, h: d.rectangle([0, 0, w, h], fill=255)))

    # straight arrow and left-turn arrow (road markings, 1 x 5 m cells)
    def arrow_straight(d, w, h):
        sw = w * 0.16
        d.rectangle([w / 2 - sw, h * 0.36, w / 2 + sw, h * 0.98], fill=255)
        d.polygon([(w * 0.06, h * 0.40), (w / 2, h * 0.02), (w * 0.94, h * 0.40)], fill=255)
    save("arrow_straight", mask_img(200, 1000, arrow_straight, 1.0))

    def arrow_left(d, w, h):
        sw = w * 0.12
        d.rectangle([w * 0.62 - sw, h * 0.42, w * 0.62 + sw, h * 0.98], fill=255)
        # curve to the left
        for k in range(60):
            a = math.pi * 0.5 * k / 59
            cx, cy = w * 0.62 - w * 0.30 * (1 - math.cos(a)), h * 0.42 - h * 0.12 * math.sin(a)
            d.ellipse([cx - sw, cy - sw, cx + sw, cy + sw], fill=255)
        tip = (w * 0.02, h * 0.30)
        d.polygon([tip, (w * 0.40, h * 0.14), (w * 0.40, h * 0.46)], fill=255)
    save("arrow_left", mask_img(240, 1000, arrow_left, 1.0))

    # manhole: disc, rim ring, raised pattern (concentric rings + spokes + text band)
    S = 512
    save("manhole_disc", mask_img(S, S, lambda d, w, h: d.ellipse([8, 8, w - 8, h - 8], fill=255), 1.0))
    save("manhole_rim", mask_img(S, S, lambda d, w, h: (d.ellipse([8, 8, w - 8, h - 8], fill=255), d.ellipse([40, 40, w - 40, h - 40], fill=0)), 1.0))

    def manhole_pat(d, w, h):
        c = w / 2
        for r in (200, 150, 100, 50):
            d.ellipse([c - r, c - r, c + r, c + r], outline=255, width=9)
        for k in range(16):
            a = 2 * math.pi * k / 16
            d.line([c + 50 * math.cos(a), c + 50 * math.sin(a), c + 200 * math.cos(a), c + 200 * math.sin(a)], fill=255, width=8)
        rnd = random.Random(4)
        for _ in range(500):          # anti-slip studs
            a, r = rnd.uniform(0, 2 * math.pi), rnd.uniform(60, 195)
            x, y = c + r * math.cos(a), c + r * math.sin(a)
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=255)
        d.ellipse([c - 18, c - 18, c + 18, c + 18], fill=0)
        d.ellipse([c - 12, c - 6, c - 4, c + 6], fill=255)    # lifting holes
        d.ellipse([c + 4, c - 6, c + 12, c + 6], fill=255)
    save("manhole_pattern", mask_img(S, S, manhole_pat, 0.6))

    # curb-side gully grate: frame + bars
    def grate_frame(d, w, h):
        d.rectangle([0, 0, w, h], fill=255)
    save("grate_frame", mask_img(300, 500, grate_frame))

    def grate_slots(d, w, h):
        for k in range(9):
            x = 34 + k * 27
            d.rounded_rectangle([x, 40, x + 14, h - 40], radius=6, fill=255)
    save("grate_slots", mask_img(300, 500, grate_slots, 0.5))

    # asphalt patches: irregular saw-cut rectangles
    def patch(seed):
        def f(d, w, h):
            rnd = random.Random(seed)
            pts = []
            for (x, y) in [(0.05, 0.06), (0.5, 0.03), (0.95, 0.07), (0.97, 0.5), (0.94, 0.95), (0.5, 0.97), (0.04, 0.93), (0.03, 0.5)]:
                pts.append((w * (x + rnd.uniform(-0.03, 0.03)), h * (y + rnd.uniform(-0.03, 0.03))))
            d.polygon(pts, fill=255)
        return f
    save("patch_a", mask_img(512, 400, patch(1), 1.5))
    save("patch_b", mask_img(300, 600, patch(2), 1.5))

    # tyre skid: two bands with breaks
    def skid(d, w, h):
        rnd = random.Random(7)
        for x0 in (0.08, 0.62):
            y = 0.0
            while y < 1.0:
                l = rnd.uniform(0.15, 0.5)
                d.rectangle([w * x0, h * y, w * (x0 + 0.30), h * min(1, y + l)], fill=255)
                y += l + rnd.uniform(0.0, 0.08)
    save("skid", mask_img(128, 1024, skid, 2.0))
    return out


# ---------------------------------------------------------------- scripts


def L(tool, **args):
    return {"tool": tool, "args": args}


def finish(name, res_render=900, extra=()):
    """Top-down renders (material + roughness), export, save."""
    return [
        L("render", yaw=0, pitch=89.9, zoom=1.0, width=res_render, height=res_render, background=False,
          path=f"target/roads/{name}_render.png"),
        *extra,
        L("export_textures", dir=f"{TEX}/{name}", name=name, preset="separate"),
        L("save_project", path=f"{PROJ}/{name}.pigment"),
    ]


def asphalt():
    s = [L("new_project", tile={"size_m": [4, 4], "name": "asphalt"}, resolution=4096, material="Asphalt")]
    s.append(L("delete_layer", layer="Paint"))
    s.append(L("update_layer", layer="Base", values={"base_color": [0.075, 0.075, 0.078], "roughness": 0.86}))
    add = lambda **a: s.append(L("add_layer", **a))
    add(name="Binder tone", values={"base_color": [0.058, 0.058, 0.062], "roughness": 0.8}, opacity=0.7,
        mask={"generator": "grunge", "amount": 0.5, "scale": 0.45, "softness": 0.35, "seed": 3})
    add(name="Aggregate fine", values={"base_color": [0.16, 0.155, 0.15], "roughness": 0.75, "height": 0.25},
        mask={"generator": "spots", "amount": 0.4, "scale": 220.0, "softness": 0.05, "seed": 5})
    add(name="Aggregate coarse", values={"base_color": [0.24, 0.235, 0.225], "roughness": 0.7, "height": 0.45},
        mask={"generator": "spots", "amount": 0.22, "scale": 110.0, "softness": 0.04, "seed": 9})
    add(name="Aggregate light", values={"base_color": [0.36, 0.35, 0.33], "roughness": 0.65, "height": 0.35},
        mask={"generator": "spots", "amount": 0.1, "scale": 160.0, "softness": 0.03, "seed": 13})
    # worn binder: aggregate exposed in tracks of lighter, rougher surface
    add(name="Worn binder", values={"base_color": [0.13, 0.128, 0.125], "roughness": 0.92}, opacity=0.55,
        channels={"height": False},
        mask={"generator": "grunge", "amount": 0.38, "scale": 0.9, "softness": 0.2, "seed": 21})
    add(name="Pores", values={"base_color": [0.03, 0.03, 0.032], "height": -0.35}, opacity=0.8,
        mask={"generator": "spots", "amount": 0.15, "scale": 300.0, "softness": 0.05, "seed": 31})
    # crack network: ridged noise lines (scratches generator, isotropic on a floor) + tar sealing
    add(name="Crack seal", values={"base_color": [0.022, 0.022, 0.024], "roughness": 0.3, "height": 0.08}, opacity=0.85,
        mask={"generator": "scratches", "amount": 0.3, "scale": 0.55, "softness": 0.07, "seed": 41})
    add(name="Cracks", values={"base_color": [0.012, 0.012, 0.012], "roughness": 0.95, "height": -1.0},
        mask={"generator": "scratches", "amount": 0.16, "scale": 0.55, "softness": 0.02, "seed": 41})
    add(name="Hairline cracks", values={"base_color": [0.02, 0.02, 0.02], "height": -0.6}, opacity=0.8,
        mask={"generator": "scratches", "amount": 0.09, "scale": 2.1, "softness": 0.015, "seed": 47})
    # damp low spots (the big puddles are a world-space shader mask in Blender)
    add(name="Damp", values={"base_color": [0.05, 0.05, 0.053], "roughness": 0.35}, opacity=0.35,
        channels={"height": False, "metallic": False},
        mask={"generator": "puddles", "amount": 0.15, "scale": 0.6, "breakup": 0.6, "softness": 0.15, "seed": 51})
    add(name="Dust", values={"base_color": [0.2, 0.19, 0.175], "roughness": 0.95}, opacity=0.25,
        channels={"height": False},
        mask={"generator": "grunge", "amount": 0.3, "scale": 2.6, "softness": 0.3, "seed": 61})
    return s + finish("asphalt")


def paving():
    s = [L("new_project", tile={"size_m": [2, 2], "name": "paving"}, resolution=2048, material="Concrete")]
    s.append(L("delete_layer", layer="Paint"))
    # the base is the joint: dark, recessed
    s.append(L("update_layer", layer="Base", values={"base_color": [0.045, 0.044, 0.04], "roughness": 0.95, "height": -0.6},
               channels={"height": True}))
    add = lambda **a: s.append(L("add_layer", **a))
    add(name="Joint moss", values={"base_color": [0.05, 0.08, 0.03], "roughness": 0.9}, opacity=0.8,
        mask={"generator": "moss", "amount": 0.35, "scale": 3.0, "breakup": 0.8, "seed": 2})
    add(name="Slabs", values={"base_color": [0.3, 0.295, 0.285], "roughness": 0.82, "height": 0.25},
        mask={"generator": "tiles", "variant": "square", "scale": 2.0, "aspect": 1.0, "mortar": 0.035, "breakup": 0.6, "softness": 0.012, "seed": 3})
    add(name="Slab tone", values={"base_color": [0.23, 0.225, 0.215], "roughness": 0.85}, opacity=0.8,
        channels={"height": False},
        mask={"generator": "tiles", "variant": "square", "scale": 2.0, "aspect": 1.0, "mortar": 0.035, "amount": 0.35, "softness": 0.012, "seed": 7})
    add(name="Slab grain", values={"base_color": [0.38, 0.37, 0.355], "height": 0.1}, opacity=0.5,
        mask={"generator": "spots", "amount": 0.25, "scale": 90.0, "softness": 0.05, "seed": 11})
    add(name="Chips", values={"base_color": [0.17, 0.165, 0.16], "height": -0.3}, opacity=0.9,
        mask={"generator": "scratches", "amount": 0.04, "scale": 2.5, "softness": 0.02, "seed": 17})
    add(name="Stains", material="Grime", opacity=0.45, channels={"height": False},
        mask={"generator": "grunge", "amount": 0.35, "scale": 1.4, "softness": 0.3, "seed": 19})
    add(name="Gum", values={"base_color": [0.16, 0.155, 0.15], "roughness": 0.5, "height": 0.15}, opacity=0.8,
        mask={"generator": "spots", "amount": 0.025, "scale": 9.0, "softness": 0.02, "seed": 23})
    return s + finish("paving")


def setts():
    s = [L("new_project", tile={"size_m": [2, 2], "name": "setts"}, resolution=2048, material="Concrete")]
    s.append(L("delete_layer", layer="Paint"))
    s.append(L("update_layer", layer="Base", values={"base_color": [0.035, 0.034, 0.032], "roughness": 0.95, "height": -0.7},
               channels={"height": True}))
    add = lambda **a: s.append(L("add_layer", **a))
    add(name="Setts", values={"base_color": [0.16, 0.16, 0.165], "roughness": 0.7, "height": 0.4},
        mask={"generator": "tiles", "variant": "bricks", "scale": 8.0, "aspect": 1.5, "mortar": 0.1, "breakup": 0.8, "softness": 0.04, "seed": 5})
    add(name="Sett tone", values={"base_color": [0.22, 0.21, 0.2]}, opacity=0.8, channels={"height": False},
        mask={"generator": "tiles", "variant": "bricks", "scale": 8.0, "aspect": 1.5, "mortar": 0.1, "amount": 0.4, "softness": 0.04, "seed": 9})
    add(name="Polish", values={"roughness": 0.35}, opacity=0.7, channels={"base_color": False, "height": False, "metallic": False},
        mask={"generator": "grunge", "amount": 0.4, "scale": 1.2, "softness": 0.3, "seed": 13})
    add(name="Grain", values={"base_color": [0.3, 0.29, 0.28], "height": 0.1}, opacity=0.6,
        mask={"generator": "spots", "amount": 0.2, "scale": 110.0, "softness": 0.05, "seed": 17})
    add(name="Grime", material="Grime", opacity=0.4, channels={"height": False},
        mask={"generator": "grunge", "amount": 0.3, "scale": 1.7, "softness": 0.3, "seed": 19})
    return s + finish("setts")


def concrete():
    s = [L("new_project", tile={"size_m": [2, 2], "name": "concrete"}, resolution=2048, material="Concrete")]
    s.append(L("delete_layer", layer="Paint"))
    s.append(L("update_layer", layer="Base", values={"base_color": [0.33, 0.325, 0.31], "roughness": 0.9}))
    add = lambda **a: s.append(L("add_layer", **a))
    add(name="Cast tone", values={"base_color": [0.26, 0.255, 0.245]}, opacity=0.7,
        mask={"generator": "grunge", "amount": 0.5, "scale": 0.8, "softness": 0.4, "seed": 3})
    add(name="Pores", values={"base_color": [0.12, 0.12, 0.115], "height": -0.5},
        mask={"generator": "spots", "amount": 0.08, "scale": 60.0, "softness": 0.04, "seed": 5})
    add(name="Aggregate", values={"base_color": [0.4, 0.39, 0.37], "height": 0.1}, opacity=0.5,
        mask={"generator": "spots", "amount": 0.2, "scale": 120.0, "softness": 0.05, "seed": 7})
    add(name="Hairline cracks", values={"base_color": [0.08, 0.08, 0.075], "height": -0.7},
        mask={"generator": "scratches", "amount": 0.04, "scale": 1.0, "softness": 0.015, "seed": 11})
    add(name="Water stains", material="Grime", opacity=0.5, channels={"height": False},
        mask={"generator": "grunge", "amount": 0.35, "scale": 1.1, "softness": 0.35, "seed": 13})
    add(name="Moss", values={"base_color": [0.06, 0.09, 0.035], "roughness": 0.95}, opacity=0.5,
        mask={"generator": "moss", "amount": 0.12, "scale": 2.0, "breakup": 0.9, "seed": 17})
    return s + finish("concrete")


TRIM_STRIPS = [("Curb top", 0.30), ("Curb face", 0.20), ("Gutter", 0.45), ("Walk edge", 0.35), ("Kerb paint", 0.20), ("Drain grate", 0.50)]


def trim(st):
    s = [L("new_project", tile={"size_m": 2.0, "name": "trim", "strips": [{"name": n, "height_m": h} for n, h in TRIM_STRIPS]},
           resolution=2048, material="Concrete")]
    s.append(L("delete_layer", layer="Paint"))
    s.append(L("update_layer", layer="Base", values={"base_color": [0.3, 0.295, 0.285], "roughness": 0.88}))
    add = lambda **a: s.append(L("add_layer", **a))
    # strip centres (world z) for decals; the sheet spans z -1..1
    z0, acc = -1.0, {}
    for n, h in TRIM_STRIPS:
        acc[n] = (z0, z0 + h)
        z0 += h
    zc = {n: (a + b) / 2 for n, (a, b) in acc.items()}

    def joints(strip, every, layer):
        x = -1.0
        while x < 1.0 - 1e-6:
            s.append(L("project_decal", image=st["bar"], layer=layer, position=[x, 0, zc[strip]], normal=[0, 1, 0],
                       size=[0.012, acc[strip][1] - acc[strip][0] + 0.01], tint=[0.05, 0.05, 0.045],
                       values={"roughness": 0.95}, height=-0.8))
            x += every

    # curb top: granite-grey precast blocks, 1 m long, polished by feet
    add(name="Curb stone", parent="Curb top", values={"base_color": [0.36, 0.355, 0.34], "roughness": 0.75})
    add(name="Grain", parent="Curb top", values={"base_color": [0.46, 0.45, 0.43], "height": 0.1}, opacity=0.6,
        mask={"generator": "spots", "amount": 0.25, "scale": 120.0, "softness": 0.05, "seed": 3})
    add(name="Polish", parent="Curb top", values={"roughness": 0.45}, opacity=0.6, channels={"base_color": False, "metallic": False},
        mask={"generator": "grunge", "amount": 0.4, "scale": 2.0, "softness": 0.3, "seed": 5})
    add(name="Chips", parent="Curb top", values={"base_color": [0.2, 0.2, 0.19], "height": -0.5},
        mask={"generator": "scratches", "amount": 0.05, "scale": 3.0, "softness": 0.02, "seed": 7})
    add(kind="paint", name="Curb joints", parent="Curb top")
    joints("Curb top", 1.0, "Curb top/Curb joints")
    # curb face: same stone, tyre scuffs and road grime
    add(name="Face stone", parent="Curb face", values={"base_color": [0.31, 0.305, 0.29], "roughness": 0.85})
    add(name="Road grime", parent="Curb face", material="Grime", opacity=0.6,
        mask={"generator": "grunge", "amount": 0.5, "scale": 2.5, "softness": 0.3, "seed": 9})
    add(name="Tyre scuffs", parent="Curb face", values={"base_color": [0.03, 0.03, 0.03], "roughness": 0.6}, opacity=0.8,
        mask={"generator": "scratches", "amount": 0.12, "scale": 2.0, "softness": 0.04, "seed": 11})
    add(kind="paint", name="Face joints", parent="Curb face")
    joints("Curb face", 1.0, "Curb face/Face joints")
    # gutter: smooth concrete channel, wet, leaf litter and moss
    add(name="Channel", parent="Gutter", values={"base_color": [0.2, 0.195, 0.185], "roughness": 0.55})
    add(name="Wet", parent="Gutter", values={"base_color": [0.08, 0.08, 0.078], "roughness": 0.08}, opacity=0.85,
        mask={"generator": "puddles", "amount": 0.5, "scale": 1.5, "breakup": 0.7, "softness": 0.12, "seed": 13})
    add(name="Silt", parent="Gutter", values={"base_color": [0.13, 0.1, 0.07], "roughness": 0.9}, opacity=0.7,
        mask={"generator": "grunge", "amount": 0.35, "scale": 3.0, "softness": 0.25, "seed": 15})
    add(name="Litter", parent="Gutter", values={"base_color": [0.18, 0.12, 0.05], "roughness": 0.8, "height": 0.3},
        mask={"generator": "spots", "amount": 0.05, "scale": 12.0, "softness": 0.02, "seed": 17})
    add(name="Moss", parent="Gutter", values={"base_color": [0.05, 0.085, 0.03], "roughness": 0.9}, opacity=0.6,
        mask={"generator": "moss", "amount": 0.18, "scale": 4.0, "breakup": 0.9, "seed": 19})
    add(kind="paint", name="Gutter joints", parent="Gutter")
    joints("Gutter", 2.0, "Gutter/Gutter joints")
    # walk edge: dark granite edging band between curb and slabs
    add(name="Edging", parent="Walk edge", values={"base_color": [0.15, 0.15, 0.155], "roughness": 0.7})
    add(name="Grain", parent="Walk edge", values={"base_color": [0.26, 0.255, 0.25], "height": 0.15}, opacity=0.7,
        mask={"generator": "spots", "amount": 0.3, "scale": 110.0, "softness": 0.05, "seed": 21})
    add(name="Grime", parent="Walk edge", material="Grime", opacity=0.4,
        mask={"generator": "grunge", "amount": 0.3, "scale": 2.0, "softness": 0.3, "seed": 23})
    add(kind="paint", name="Edge joints", parent="Walk edge")
    joints("Walk edge", 0.5, "Walk edge/Edge joints")
    # kerb paint: red / white 1 m blocks (no-parking corners), worn
    add(name="White paint", parent="Kerb paint", values={"base_color": [0.75, 0.74, 0.7], "roughness": 0.5})
    add(kind="paint", name="Red blocks", parent="Kerb paint")
    for x in (-0.5,):
        s.append(L("project_decal", image=st["bar"], layer="Kerb paint/Red blocks", position=[x, 0, zc["Kerb paint"]], normal=[0, 1, 0],
                   size=[1.0, 0.21], tint=[0.55, 0.06, 0.05], values={"roughness": 0.5}))
    add(name="Paint wear", parent="Kerb paint", values={"base_color": [0.3, 0.295, 0.285], "roughness": 0.85}, opacity=0.9,
        mask={"generator": "grunge", "amount": 0.32, "scale": 4.0, "softness": 0.08, "seed": 25})
    add(name="Grime", parent="Kerb paint", material="Grime", opacity=0.5,
        mask={"generator": "grunge", "amount": 0.4, "scale": 2.0, "softness": 0.3, "seed": 27})
    # drain grate strip: cast iron slot drain, 0.5 m sections
    add(name="Iron", parent="Drain grate", values={"base_color": [0.06, 0.06, 0.065], "roughness": 0.55, "metallic": 0.8})
    add(kind="paint", name="Slots", parent="Drain grate")
    x = -1.0 + 0.125
    while x < 1.0:
        for dz in (-0.12, 0.12):
            s.append(L("project_decal", image=st["bar"], layer="Drain grate/Slots", position=[x, 0, zc["Drain grate"] + dz], normal=[0, 1, 0],
                       size=[0.12, 0.17], tint=[0.0, 0.0, 0.0], values={"roughness": 1.0}, height=-1.0))
        x += 0.25
    add(name="Rust", parent="Drain grate", material="Rust", opacity=0.7,
        mask={"generator": "spots", "amount": 0.35, "scale": 9.0, "seed": 29})
    add(name="Wear", parent="Drain grate", values={"base_color": [0.3, 0.3, 0.31], "roughness": 0.3, "metallic": 1.0}, opacity=0.6,
        mask={"generator": "grunge", "amount": 0.25, "scale": 5.0, "softness": 0.2, "seed": 31})
    return s + finish("trim")


# atlas cells: name -> size in metres
ATLAS_CELLS = [
    ("zebra_bar", [0.5, 3.0]), ("stop_line", [4.0, 0.4]),
    ("lane_dash", [0.15, 3.0]), ("edge_line_a", [0.15, 4.0]), ("edge_line_b", [0.15, 4.0]), ("edge_line_c", [0.15, 4.0]),
    ("arrow_straight", [1.0, 5.0]), ("arrow_left", [1.2, 5.0]),
    ("crack_a", [2.4, 1.4]), ("crack_b", [1.6, 1.6]), ("crack_c", [3.0, 0.9]),
    ("patch_a", [1.8, 1.4]), ("patch_b", [1.1, 2.2]),
    ("manhole", [0.9, 0.9]), ("drain", [0.45, 0.75]),
    ("oil_a", [1.4, 1.1]), ("oil_b", [0.9, 0.8]), ("skid", [0.5, 4.0]),
]


def atlas(st):
    s = [L("new_project", tile={"name": "atlas", "cells": [{"name": n, "size_m": sz} for n, sz in ATLAS_CELLS], "padding_px": 24},
           resolution=4096, material="Asphalt")]
    s.append(L("delete_layer", layer="Paint"))
    # base colour under transparent texels: dark asphalt (keeps filtering at decal edges dark, not white)
    s.append(L("update_layer", layer="Base", values={"base_color": [0.06, 0.06, 0.062], "roughness": 0.85, "opacity": 0.0}))
    add = lambda **a: s.append(L("add_layer", **a))
    dec = lambda **a: s.append(L("project_decal", **a))
    return s, add, dec


def atlas_script(st):
    s, add, dec = atlas(st)
    index = {n: i for i, (n, _) in enumerate(ATLAS_CELLS)}
    sizes = dict(ATLAS_CELLS)

    def centre(n):
        """Decal placement at the middle of cell n (its mesh part), in metres."""
        return {"part": index[n], "face": "top", "anchor": [0.5, 0.5]}, sizes[n]

    def paint_fill(n, seed, wear=0.3):
        """Road paint covering the whole cell: white, glass beads, worn."""
        add(name="Paint", parent=n, values={"base_color": [0.78, 0.78, 0.74], "roughness": 0.45, "opacity": 1.0, "height": 0.15})
        add(name="Dirt", parent=n, material="Grime", opacity=0.45, channels={"height": False},
            mask={"generator": "grunge", "amount": 0.45, "scale": 3.0, "softness": 0.3, "seed": seed})
        add(name="Worn through", parent=n, values={"opacity": 0.0}, channels={"base_color": False, "roughness": False, "metallic": False, "opacity": True},
            mask={"generator": "grunge", "amount": wear, "scale": 5.0, "softness": 0.06, "seed": seed + 1})
        add(name="Cracked", parent=n, values={"opacity": 0.0}, channels={"base_color": False, "roughness": False, "metallic": False, "opacity": True},
            mask={"generator": "scratches", "amount": 0.08, "scale": 1.5, "softness": 0.02, "seed": seed + 2})

    def fade_edges(n, img="soft_ellipse", scale=1.0):
        """Opacity 0 outside a soft ellipse, so content never ends at the cell border."""
        c, sz = centre(n)
        add(name="Edge fade", parent=n, values={"opacity": 0.0}, channels={"base_color": False, "roughness": False, "metallic": False, "opacity": True},
            mask="white")
        dec(image=st[img], layer=f"{n}/Edge fade", mask=True, mask_value="black", **c,
            size=[sz[0] * scale, sz[1] * scale])

    # markings
    for i, n in enumerate(["zebra_bar", "stop_line", "lane_dash", "edge_line_a", "edge_line_b", "edge_line_c"]):
        paint_fill(n, 100 + i * 10, wear=0.22 + 0.06 * (i % 3))
    for i, n in enumerate(["arrow_straight", "arrow_left"]):
        c, sz = centre(n)
        add(kind="paint", name="Shape", parent=n)
        dec(image=st[n], layer=f"{n}/Shape", **c, size=sz, tint=[0.78, 0.78, 0.74],
            values={"roughness": 0.45, "opacity": 1.0}, channels=["base_color", "roughness", "opacity", "height"], height=0.15)
        add(name="Dirt", parent=n, material="Grime", opacity=0.45, channels={"height": False},
            mask={"generator": "grunge", "amount": 0.45, "scale": 3.0, "softness": 0.3, "seed": 170 + i})
        add(name="Worn through", parent=n, values={"opacity": 0.0}, channels={"base_color": False, "roughness": False, "metallic": False, "opacity": True},
            mask={"generator": "grunge", "amount": 0.3, "scale": 5.0, "softness": 0.06, "seed": 180 + i})
    # cracks: ridged networks, sealed rims, faded out at the cell edges
    for i, n in enumerate(["crack_a", "crack_b", "crack_c"]):
        add(name="Seal", parent=n, values={"base_color": [0.02, 0.02, 0.022], "roughness": 0.3, "opacity": 0.9, "height": 0.05},
            mask={"generator": "scratches", "amount": 0.24, "scale": 0.8 + 0.3 * i, "softness": 0.08, "seed": 200 + i})
        add(name="Crack", parent=n, values={"base_color": [0.01, 0.01, 0.01], "roughness": 0.95, "opacity": 1.0, "height": -1.0},
            mask={"generator": "scratches", "amount": 0.11, "scale": 0.8 + 0.3 * i, "softness": 0.02, "seed": 200 + i})
        add(name="Branches", parent=n, values={"base_color": [0.015, 0.015, 0.015], "opacity": 1.0, "height": -0.7},
            mask={"generator": "scratches", "amount": 0.06, "scale": 2.4, "softness": 0.015, "seed": 210 + i})
        fade_edges(n)
    # patches: saw-cut asphalt repairs, newer (darker, smoother) binder
    for i, n in enumerate(["patch_a", "patch_b"]):
        c, sz = centre(n)
        add(kind="paint", name="Shape", parent=n)
        dec(image=st[n], layer=f"{n}/Shape", **c, size=sz, tint=[0.045, 0.045, 0.047],
            values={"roughness": 0.7, "opacity": 1.0}, channels=["base_color", "roughness", "opacity", "height"], height=0.06)
        add(name="Aggregate", parent=n, values={"base_color": [0.12, 0.118, 0.115], "height": 0.2}, opacity=0.8,
            mask={"generator": "spots", "amount": 0.2, "scale": 60.0, "softness": 0.05, "seed": 220 + i})
        add(name="Tar rim", parent=n, values={"base_color": [0.015, 0.015, 0.016], "roughness": 0.25}, opacity=0.9,
            mask={"generator": "scratches", "amount": 0.15, "scale": 1.0, "softness": 0.05, "seed": 230 + i})
    # manhole cover: cast iron disc, raised pattern, polished studs, rust in the recesses
    c, sz = centre("manhole")
    add(kind="paint", name="Iron", parent="manhole")
    dec(image=st["manhole_disc"], layer="manhole/Iron", **c, size=sz, tint=[0.07, 0.068, 0.068],
        values={"roughness": 0.6, "metallic": 0.85, "opacity": 1.0}, channels=["base_color", "roughness", "metallic", "opacity"])
    add(name="Rust", parent="manhole", material="Rust", opacity=0.8,
        mask={"generator": "spots", "amount": 0.4, "scale": 14.0, "seed": 240})
    add(kind="paint", name="Relief", parent="manhole")
    dec(image=st["manhole_pattern"], layer="manhole/Relief", **c, size=sz, tint=[0.22, 0.22, 0.23],
        values={"roughness": 0.28, "metallic": 1.0}, channels=["base_color", "roughness", "metallic", "height"], height=0.7)
    dec(image=st["manhole_rim"], layer="manhole/Relief", **c, size=sz, tint=[0.16, 0.16, 0.165],
        values={"roughness": 0.35, "metallic": 1.0}, channels=["base_color", "roughness", "metallic", "height"], height=0.4)
    add(name="Grime", parent="manhole", material="Grime", opacity=0.45, channels={"height": False},
        mask={"generator": "grunge", "amount": 0.35, "scale": 6.0, "softness": 0.25, "seed": 241})
    # drain grate (curb-side gully)
    c, sz = centre("drain")
    add(kind="paint", name="Frame", parent="drain")
    dec(image=st["grate_frame"], layer="drain/Frame", **c, size=sz, tint=[0.08, 0.078, 0.078],
        values={"roughness": 0.55, "metallic": 0.85, "opacity": 1.0}, channels=["base_color", "roughness", "metallic", "opacity"])
    dec(image=st["grate_slots"], layer="drain/Frame", **c, size=sz, tint=[0.0, 0.0, 0.0],
        values={"roughness": 1.0, "metallic": 0.0}, channels=["base_color", "roughness", "metallic", "height"], height=-1.0)
    add(name="Rust", parent="drain", material="Rust", opacity=0.7,
        mask={"generator": "spots", "amount": 0.35, "scale": 16.0, "seed": 250})
    add(name="Silt", parent="drain", values={"base_color": [0.12, 0.09, 0.06], "roughness": 0.9}, opacity=0.5,
        mask={"generator": "grunge", "amount": 0.35, "scale": 7.0, "softness": 0.3, "seed": 251})
    # oil stains: domain-warped blots, glossy, faded at the edges
    for i, n in enumerate(["oil_a", "oil_b"]):
        add(name="Stain", parent=n, values={"base_color": [0.02, 0.02, 0.022], "roughness": 0.12, "opacity": 0.85},
            mask={"generator": "spots", "amount": 0.45, "scale": 2.2 + i, "softness": 0.12, "seed": 260 + i})
        add(name="Sheen", parent=n, values={"base_color": [0.08, 0.04, 0.12], "roughness": 0.05}, opacity=0.35, channels={"height": False},
            mask={"generator": "spots", "amount": 0.25, "scale": 4.0 + i, "softness": 0.2, "seed": 270 + i})
        add(name="Drips", parent=n, values={"base_color": [0.015, 0.015, 0.017], "roughness": 0.1, "opacity": 0.9},
            mask={"generator": "spots", "amount": 0.12, "scale": 9.0, "softness": 0.05, "seed": 280 + i})
        fade_edges(n)
    # tyre skid marks
    c, sz = centre("skid")
    add(kind="paint", name="Rubber", parent="skid")
    dec(image=st["skid"], layer="skid/Rubber", **c, size=sz, tint=[0.012, 0.012, 0.012],
        values={"roughness": 0.5, "opacity": 0.85}, channels=["base_color", "roughness", "opacity"])
    add(name="Breakup", parent="skid", values={"opacity": 0.0}, channels={"base_color": False, "roughness": False, "metallic": False, "opacity": True},
        mask={"generator": "grunge", "amount": 0.35, "scale": 4.0, "softness": 0.2, "seed": 290})
    s += [
        L("render", yaw=0, pitch=89.9, zoom=1.0, width=1200, height=1200, background=False, path="target/roads/atlas_render.png"),
        L("export_textures", dir=f"{TEX}/atlas", name="atlas", preset="separate"),
        L("save_project", path=f"{PROJ}/atlas.pigment"),
    ]
    return s


def write(name, lines):
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    p = SCRIPTS / f"{name}.jsonl"
    p.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    return p


def main():
    st = stencils()
    scripts = {
        "asphalt": asphalt(),
        "paving": paving(),
        "setts": setts(),
        "concrete": concrete(),
        "trim": trim(st),
        "atlas": atlas_script(st),
    }
    paths = {n: write(n, l) for n, l in scripts.items()}
    print("wrote", ", ".join(rel(p) for p in paths.values()))
    if "--run" in sys.argv:
        want = [a for a in sys.argv[1:] if not a.startswith("--")] or list(paths)
        (ROOT / "target" / "roads").mkdir(parents=True, exist_ok=True)
        for n in want:
            print(f"--- {n}")
            r = subprocess.run([str(MCP), "--script", str(paths[n])], cwd=ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stdout[-3000:], r.stderr[-3000:])
                sys.exit(f"{n} failed")
            print("\n".join(l for l in r.stderr.splitlines() if l.startswith(("script:", "  slowest"))))


if __name__ == "__main__":
    main()
