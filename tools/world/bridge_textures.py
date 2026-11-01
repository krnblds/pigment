"""Pigment recipes for the bridges (tools/world/bridge_kit.py): seamless sheets in metres.

    python tools/world/bridge_textures.py [--no-run] [names...]

Writes scenes/town/scripts/bridges/<name>.jsonl (and the stencils / sign images under
assets/decals/bridges/), then runs each through pigment-mcp unless --no-run (the city build's
recipe step uses --no-run; its Pigment node runs the scripts). Texture sets go to
scenes/town/textures/<name>/ (top level, so the Godot pack finds them by folder name).

Sheets (sheet x = U along the member, sheet z = V up / along the cable):

    bridge_concrete       4.8 m  weathered board-formed concrete: 2.4 x 1.2 m form panels, tie
                                 holes on a 1.2 m grid, rain streaks, leaks, efflorescence, patch
                                 repairs, spalls
    bridge_steel_white    4 m    pale grey-white painted steel (port / arch): bolted splice plate
                                 every 4 m, rust at the bolt heads bleeding down, edge wear, grime
    bridge_steel_weather  4 m    weathering steel (Kagero girders): patina, bolted splice
    bridge_steel_grey     2 m    galvanised / grey-painted secondary steel (railings, catwalks,
                                 gantry, scaffold, cross frames): rust spots, grime
    bridge_cable          1 m    HDPE stay sheathing: pale grey, helical rib, grime runs
    bridge_hoarding       6x3 m  Hoshikawa construction hoarding panel (logo, notices)
    bridge_hazard         2 m    yellow / black hazard stripes (gantry, crane base, barrier ends)
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
if not MCP.is_file():
    try:
        sys.path.insert(0, str(ROOT))
        from tools.city import paths as _paths
        MCP = Path(_paths.pigment_mcp() or MCP)
    except Exception:
        pass
SCRIPTS = ROOT / "scenes" / "town" / "scripts" / "bridges"
TEX = "scenes/town/textures"
PROJ = "scenes/town/projects/bridges"
DEC = "assets/decals/bridges"
BAR = "assets/decals/roads/bar.png"
PATCH_A = "assets/decals/roads/patch_a.png"
PATCH_B = "assets/decals/roads/patch_b.png"
ELLIPSE = "assets/decals/roads/soft_ellipse.png"
LOGO = "assets/decals/logo_hoshikawa_dynamics.png"

# tile sizes in metres (bridge_kit.py maps UVs with the same numbers)
TILE = {"bridge_concrete": 4.8, "bridge_steel_white": 4.0, "bridge_steel_weather": 4.0, "bridge_steel_grey": 2.0,
        "bridge_cable": 1.0, "bridge_hoarding": (6.0, 3.0), "bridge_hazard": 2.0}


def _g(gen, **kw):
    d = {"generator": gen}
    d.update(kw)
    return d


def _decal(image, layer, x, z, w, h, tint, values=None, height=None, channels=None):
    a = {"image": image, "layer": layer, "position": [round(x, 4), 0, round(z, 4)], "normal": [0, 1, 0], "size": [round(w, 4), round(h, 4)], "tint": tint}
    if values:
        a["values"] = values
    if height is not None:
        a["height"] = height
    if channels:
        a["channels"] = channels
    return {"tool": "project_decal", "args": a}


def _sheet(name, size, res, material, base, steps):
    """Flat tile project -> steps -> preview, export (separate maps), save."""
    size = list(size) if isinstance(size, (list, tuple)) else [size, size]
    L = [{"tool": "new_project", "args": {"tile": {"size_m": size, "name": name}, "resolution": res, "material": material}},
         {"tool": "delete_layer", "args": {"layer": "Paint"}},
         {"tool": "update_layer", "args": {"layer": "Base", "values": base}}]
    for st in steps:
        L.append(st if "tool" in st else {"tool": "add_layer", "args": st})
    tmp = (ROOT / ".citycache" / "bridges").as_posix()
    L += [{"tool": "render", "args": {"yaw": 0, "pitch": 89.9, "zoom": 1.0, "width": 600, "height": 600, "background": False, "path": f"{tmp}/{name}.png"}},
          {"tool": "export_textures", "args": {"dir": f"{TEX}/{name}", "name": name, "preset": "separate"}},
          {"tool": "save_project", "args": {"path": f"{PROJ}/{name}.pigment"}}]
    return L


# ---------------------------------------------------------------- stencils and signs
def make_decals():
    """Round tie-hole / bolt stencil, a rust run stencil and the bridge warning signs (PIL)."""
    from PIL import Image, ImageDraw, ImageFont
    d = ROOT / DEC
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    # soft-edged disc (alpha), white
    p = d / "dot.png"
    n = 64
    img = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    for y in range(n):
        for x in range(n):
            r = math.hypot(x + 0.5 - n / 2, y + 0.5 - n / 2) / (n / 2)
            a = max(0.0, min(1.0, (1.0 - r) / 0.18))
            img.putpixel((x, y), (255, 255, 255, int(255 * a)))
    img.save(p)
    out["dot"] = p
    # rust run: a narrow streak, strong at the top, fading down with a ragged edge
    p = d / "run.png"
    w, h = 32, 256
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    for y in range(h):
        f = y / (h - 1)                        # 0 = top of the image = top of the run
        width = 0.5 * (1.0 - 0.75 * f) * (0.85 + 0.15 * math.sin(y * 0.37))
        for x in range(w):
            u = abs((x + 0.5) / w - 0.5)
            a = max(0.0, min(1.0, (width * 0.5 - u) / 0.06)) * (1.0 - f) ** 1.3
            img.putpixel((x, y), (255, 255, 255, int(255 * a)))
    img.save(p)
    out["run"] = p

    # uplight wash cards (bridge_kit.py): light full at the bottom edge, fading up and to the sides
    for key, rgb in (("wash_warm", (255, 214, 168)), ("wash_cool", (196, 220, 255))):
        w, h = 64, 256
        img = Image.new("RGBA", (w, h))
        for y in range(h):
            f = 1.0 - y / (h - 1)                # image row 0 = top of the card (f = 1)
            for x in range(w):
                u = abs((x + 0.5) / w - 0.5) * 2
                a = math.exp(-3.2 * f) * max(0.0, 1.0 - u ** 2.2) * (0.25 + 0.75 * min(1.0, f * 12))
                img.putpixel((x, y), (*rgb, int(255 * min(1.0, a))))
        p = d / f"{key}.png"
        img.save(p)
        out[key] = p

    def font(sz, bold=True):
        for f in (["arialbd.ttf", "seguisb.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]):
            try:
                return ImageFont.truetype(f, sz)
            except OSError:
                continue
        return ImageFont.load_default()

    def sign(name, w, h, bg, fg, lines, band=None, tri=False):
        img = Image.new("RGBA", (w, h), bg)
        dr = ImageDraw.Draw(img)
        y0 = 0
        if band:
            bh = int(h * 0.3)
            dr.rectangle([0, 0, w, bh], fill=band[0])
            f = font(int(bh * 0.62))
            tw = dr.textlength(band[1], font=f)
            dr.text(((w - tw) / 2, bh * 0.16), band[1], font=f, fill=band[2])
            y0 = bh
        if tri:
            s = int(min(h - y0, w) * 0.55)
            cx, cy = int(w * 0.16), y0 + (h - y0) // 2
            dr.polygon([(cx, cy - s // 2), (cx - s // 2, cy + s // 2), (cx + s // 2, cy + s // 2)], fill=(250, 200, 20, 255), outline=(10, 10, 10, 255), width=8)
            f = font(int(s * 0.6))
            dr.text((cx - s * 0.08, cy - s * 0.2), "!", font=f, fill=(10, 10, 10, 255))
        x0 = int(w * 0.32) if tri else int(w * 0.06)
        avail = h - y0
        lh = avail / (len(lines) + 0.6)
        for k, (txt, rel) in enumerate(lines):
            f = font(int(lh * rel))
            tw = dr.textlength(txt, font=f)
            x = x0 if tri else (w - tw) / 2
            dr.text((x, y0 + lh * (0.3 + k)), txt, font=f, fill=fg)
        dr.rectangle([4, 4, w - 5, h - 5], outline=fg, width=6)
        p = d / f"{name}.png"
        img.save(p)
        out[name] = p
    sign("sign_works", 1024, 640, (240, 240, 236, 255), (15, 15, 15, 255),
         [("BRIDGE MAINTENANCE", 0.62), ("WORKS IN PROGRESS", 0.62), ("工事中  HOSHIKAWA INFRASTRUCTURE", 0.42)],
         band=((200, 20, 20, 255), "DANGER", (255, 255, 255, 255)))
    sign("sign_no_access", 1024, 512, (245, 245, 240, 255), (20, 20, 20, 255),
         [("NO UNAUTHORISED", 0.6), ("ACCESS", 0.6), ("立入禁止", 0.6)], tri=True)
    sign("sign_clearance", 1024, 360, (250, 200, 20, 255), (10, 10, 10, 255),
         [("INSPECTION CATWALK", 0.6), ("HARNESS REQUIRED", 0.6)])
    sign("sign_bridge_id", 1024, 300, (14, 70, 40, 255), (240, 240, 240, 255),
         [("SHINKAI BAY ROUTE  湾岸線", 0.62), ("P-12   LOAD 40 t", 0.52)])
    return {k: v.relative_to(ROOT).as_posix() for k, v in out.items()}


# ---------------------------------------------------------------- sheets
def concrete(D):
    S = 4.8
    steps = [
        {"name": "Tone", "values": {"base_color": [0.47, 0.46, 0.43]}, "opacity": 0.7, "mask": _g("grunge", amount=0.45, scale=0.5, softness=0.35, seed=101)},
        {"name": "Pour lifts", "values": {"base_color": [0.37, 0.36, 0.34]}, "opacity": 0.5, "mask": _g("grunge", amount=0.4, scale=1.6, softness=0.4, seed=103)},
        {"name": "Aggregate", "values": {"base_color": [0.55, 0.54, 0.51], "height": 0.15}, "opacity": 0.5, "mask": _g("spots", amount=0.25, scale=120.0, softness=0.05, seed=105)},
        {"name": "Pitting", "values": {"base_color": [0.22, 0.21, 0.2], "height": -0.6}, "opacity": 0.8, "mask": _g("spots", amount=0.05, scale=40.0, softness=0.05, seed=107)},
        {"kind": "paint", "name": "Form joints"},
        {"kind": "paint", "name": "Tie holes"},
        {"kind": "paint", "name": "Patch repairs"},
    ]
    dec = []
    # form panel joints: 2.4 m wide x 1.2 m tall panels (joints between, wrapping with the tile)
    for x in (-1.2, 1.2):
        dec.append(_decal(BAR, "Form joints", x, 0, 0.025, S + 0.02, [0.26, 0.25, 0.23], {"roughness": 0.95}, height=-0.6))
    for z in (-1.8, -0.6, 0.6, 1.8):
        dec.append(_decal(BAR, "Form joints", 0, z, S + 0.02, 0.02, [0.27, 0.26, 0.24], {"roughness": 0.95}, height=-0.5))
    # tie holes (cone + plug) at 0.6 m from the joints: 1.2 m grid
    for x in (-1.8, -0.6, 0.6, 1.8):
        for z in (-1.2, 0.0, 1.2, 2.4 - 0.001):
            zz = z if z < 2.39 else -2.4 + 0.001
            dec.append(_decal(D["dot"], "Tie holes", x, zz, 0.07, 0.07, [0.16, 0.155, 0.15], {"roughness": 0.9}, height=-1.0))
            dec.append(_decal(D["dot"], "Tie holes", x, zz, 0.035, 0.035, [0.36, 0.35, 0.33], {"roughness": 0.85}, height=-0.3))
    # patch repairs: newer, smoother, lighter mortar
    for (img, x, z, w, h) in ((PATCH_A, -0.9, -0.4, 0.9, 0.7), (PATCH_B, 1.4, 1.5, 0.6, 0.5), (PATCH_A, 0.5, -1.9, 0.5, 0.35)):
        dec.append(_decal(img, "Patch repairs", x, z, w, h, [0.5, 0.49, 0.465], {"roughness": 0.82}, height=0.12))
    weather = [
        {"name": "Tie hole rust", "material": "Rust", "opacity": 0.5, "mask": _g("leaks", amount=0.25, scale=6.0, softness=0.2, seed=109, drip_length=0.8)},
        {"name": "Rain streaks", "material": "Grime", "opacity": 0.85, "mask": _g("streaks", amount=0.5, scale=2.2, softness=0.2, seed=111)},
        {"name": "Leaks", "values": {"base_color": [0.18, 0.17, 0.15], "roughness": 0.7}, "opacity": 0.55, "mask": _g("leaks", amount=0.35, scale=1.5, softness=0.25, seed=113, drip_length=2.5)},
        {"name": "Efflorescence", "values": {"base_color": [0.78, 0.77, 0.72], "roughness": 0.95}, "opacity": 0.6, "mask": _g("streaks", amount=0.22, scale=3.0, softness=0.3, seed=115)},
        {"name": "Grime", "material": "Grime", "opacity": 0.3, "channels": {"height": False}, "mask": _g("grunge", amount=0.3, scale=0.7, softness=0.4, seed=117)},
    ]
    return _sheet("bridge_concrete", [S, S], 2048, "Concrete", {"base_color": [0.43, 0.42, 0.4], "roughness": 0.88}, steps + dec + weather)


def _bolted(D, paint, rough, bleed, metal=0.0):
    """Splice plate band at x = 0 (0.6 m wide, full height) with 2 x 12 bolt heads, rust at the
    heads and (bleed) rust runs below them."""
    S = 4.0
    dec = [_decal(BAR, "Splice plates", 0, 0, 0.62, S + 0.02, [c * 0.96 for c in paint], {"roughness": rough}, height=0.5)]
    for x in (-0.15, 0.15):
        for k in range(12):
            z = -S / 2 + (k + 0.5) * S / 12
            dec.append(_decal(D["dot"], "Bolts", x, z, 0.06, 0.06, [c * 0.9 for c in paint], {"roughness": rough}, height=1.0))
            dec.append(_decal(D["dot"], "Bolt rust", x, z - 0.005, 0.075, 0.075, [0.36, 0.15, 0.06], {"roughness": 0.85, "metallic": 0.1}))
            if bleed and (k * 7 + int(x * 10)) % 3 != 0:
                L = 0.18 + 0.25 * ((k * 13 + int(x * 20)) % 5) / 4
                dec.append(_decal(D["run"], "Rust runs", x, z - 0.04 - L / 2, 0.035, L, [0.4, 0.17, 0.07], {"roughness": 0.8}))
    return dec


def steel_white(D):
    paint = [0.74, 0.75, 0.74]
    steps = [
        {"name": "Paint tone", "values": {"base_color": [0.69, 0.7, 0.7]}, "opacity": 0.6, "mask": _g("grunge", amount=0.4, scale=0.6, softness=0.4, seed=201)},
        {"kind": "paint", "name": "Splice plates"},
        {"kind": "paint", "name": "Bolts"},
        {"kind": "paint", "name": "Bolt rust"},
        {"kind": "paint", "name": "Rust runs"},
    ] + _bolted(D, paint, 0.45, True) + [
        {"name": "Chipped paint", "values": {"base_color": [0.32, 0.33, 0.34], "roughness": 0.5, "metallic": 0.6}, "opacity": 0.6, "mask": _g("scratches", amount=0.035, scale=3.0, softness=0.05, seed=203)},
        {"name": "Rust spots", "material": "Rust", "opacity": 0.7, "mask": _g("spots", amount=0.018, scale=8.0, softness=0.15, seed=205)},
        {"name": "Salt grime", "material": "Grime", "opacity": 0.45, "mask": _g("streaks", amount=0.33, scale=2.5, softness=0.2, seed=207)},
        {"name": "Dust", "values": {"base_color": [0.5, 0.49, 0.46], "roughness": 0.8}, "opacity": 0.35, "channels": {"height": False}, "mask": _g("grunge", amount=0.3, scale=1.2, softness=0.4, seed=209)},
    ]
    return _sheet("bridge_steel_white", [4, 4], 2048, "Concrete", {"base_color": paint, "roughness": 0.45, "metallic": 0.0}, steps)


def steel_weather(D):
    base = [0.24, 0.1, 0.05]
    steps = [
        {"name": "Patina dark", "values": {"base_color": [0.15, 0.065, 0.035], "roughness": 0.85}, "opacity": 0.7, "mask": _g("grunge", amount=0.45, scale=0.8, softness=0.35, seed=301)},
        {"name": "Patina orange", "values": {"base_color": [0.4, 0.17, 0.06], "roughness": 0.9}, "opacity": 0.55, "mask": _g("spots", amount=0.3, scale=14.0, softness=0.3, seed=303)},
        {"kind": "paint", "name": "Splice plates"},
        {"kind": "paint", "name": "Bolts"},
        {"kind": "paint", "name": "Bolt rust"},
        {"kind": "paint", "name": "Rust runs"},
    ] + _bolted(D, base, 0.8, False) + [
        {"name": "Scale flakes", "values": {"base_color": [0.1, 0.05, 0.03], "height": 0.4, "roughness": 0.95}, "opacity": 0.6, "mask": _g("spots", amount=0.06, scale=30.0, softness=0.05, seed=305)},
        {"name": "Runoff streaks", "values": {"base_color": [0.12, 0.06, 0.035]}, "opacity": 0.5, "mask": _g("streaks", amount=0.35, scale=2.0, softness=0.25, seed=307)},
    ]
    return _sheet("bridge_steel_weather", [4, 4], 2048, "Concrete", {"base_color": base, "roughness": 0.82, "metallic": 0.15}, steps)


def steel_grey(D):
    base = [0.33, 0.35, 0.36]
    steps = [
        {"name": "Tone", "values": {"base_color": [0.28, 0.3, 0.31]}, "opacity": 0.6, "mask": _g("grunge", amount=0.4, scale=1.0, softness=0.4, seed=401)},
        {"name": "Worn to zinc", "values": {"base_color": [0.55, 0.56, 0.56], "roughness": 0.35, "metallic": 0.8}, "opacity": 0.5, "mask": _g("scratches", amount=0.05, scale=5.0, softness=0.05, seed=403)},
        {"name": "Rust", "material": "Rust", "opacity": 0.6, "mask": _g("spots", amount=0.03, scale=10.0, softness=0.15, seed=405)},
        {"name": "Grime runs", "material": "Grime", "opacity": 0.5, "mask": _g("streaks", amount=0.35, scale=4.0, softness=0.2, seed=407)},
    ]
    return _sheet("bridge_steel_grey", [2, 2], 1024, "Concrete", {"base_color": base, "roughness": 0.5, "metallic": 0.35}, steps)


def cable(D):
    base = [0.7, 0.7, 0.68]
    steps = [
        {"name": "Helical rib", "values": {"base_color": [0.64, 0.64, 0.62], "height": 0.8}, "opacity": 0.45, "mask": _g("stripes", amount=0.25, scale=6.0, softness=0.3, seed=501)},
        {"name": "UV chalking", "values": {"base_color": [0.78, 0.78, 0.76], "roughness": 0.6}, "opacity": 0.5, "mask": _g("grunge", amount=0.35, scale=2.0, softness=0.4, seed=503)},
        {"name": "Grime runs", "material": "Grime", "opacity": 0.55, "mask": _g("streaks", amount=0.3, scale=6.0, softness=0.2, seed=505)},
        {"name": "Soot", "values": {"base_color": [0.2, 0.2, 0.2], "roughness": 0.6}, "opacity": 0.35, "channels": {"height": False}, "mask": _g("grunge", amount=0.25, scale=4.0, softness=0.4, seed=507)},
    ]
    return _sheet("bridge_cable", [1, 1], 1024, "Concrete", {"base_color": base, "roughness": 0.35, "metallic": 0.0}, steps)


def hoarding(D):
    W, H = TILE["bridge_hoarding"]
    navy = [0.035, 0.05, 0.09]
    steps = [
        {"name": "Panel tone", "values": {"base_color": [0.045, 0.06, 0.1]}, "opacity": 0.6, "mask": _g("grunge", amount=0.4, scale=0.8, softness=0.4, seed=601)},
        {"kind": "paint", "name": "Panel seams"},
        {"kind": "paint", "name": "Graphics"},
    ]
    dec = [_decal(BAR, "Panel seams", x, 0, 0.03, H + 0.02, [0.02, 0.025, 0.04], {"roughness": 0.6}, height=-0.6) for x in (-1.5, 1.5)]
    dec.append(_decal(BAR, "Graphics", 0, H / 2 - 0.12, W + 0.02, 0.16, [0.75, 0.55, 0.12], {"roughness": 0.4}))       # gold top band
    dec.append(_decal(LOGO, "Graphics", -1.5, 0.35, 2.4, 0.9, [1.0, 1.0, 1.0], {"roughness": 0.4}))
    dec.append(_decal(D["sign_works"], "Graphics", 1.5, 0.1, 1.6, 1.0, [1.0, 1.0, 1.0], {"roughness": 0.5}))
    dec.append(_decal("assets/decals/story/sign_hoshikawa_security.png", "Graphics", -1.5, -0.65, 2.6, 0.34, [1.0, 1.0, 1.0], {"roughness": 0.4}))
    weather = [
        {"name": "Grime", "material": "Grime", "opacity": 0.55, "mask": _g("streaks", amount=0.3, scale=2.0, softness=0.2, seed=603)},
        {"name": "Splash", "material": "Grime", "opacity": 0.6, "mask": _g("grunge", amount=0.25, scale=1.5, softness=0.3, seed=605)},
    ]
    return _sheet("bridge_hoarding", [W, H], 2048, "Concrete", {"base_color": navy, "roughness": 0.55}, steps + dec + weather)


def hazard(D):
    steps = [
        {"name": "Stripes", "material": "Hazard yellow", "mask": _g("stripes", amount=0.5, scale=2.0, softness=0.02, seed=701)},
        {"name": "Scuffs", "values": {"base_color": [0.2, 0.2, 0.2], "roughness": 0.6, "metallic": 0.5}, "opacity": 0.7, "mask": _g("scratches", amount=0.1, scale=4.0, softness=0.05, seed=703)},
        {"name": "Grime", "material": "Grime", "opacity": 0.45, "mask": _g("streaks", amount=0.3, scale=3.0, softness=0.2, seed=705)},
    ]
    return _sheet("bridge_hazard", [2, 2], 1024, "Concrete", {"base_color": [0.03, 0.03, 0.03], "roughness": 0.6}, steps)


JOBS = {"bridge_concrete": concrete, "bridge_steel_white": steel_white, "bridge_steel_weather": steel_weather,
        "bridge_steel_grey": steel_grey, "bridge_cable": cable, "bridge_hoarding": hoarding, "bridge_hazard": hazard}


def main(argv):
    run = "--no-run" not in argv
    names = [a for a in argv if not a.startswith("--")] or list(JOBS)
    D = make_decals()
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    (ROOT / ".citycache" / "bridges").mkdir(parents=True, exist_ok=True)
    for name in names:
        L = JOBS[name](D)
        p = SCRIPTS / f"{name}.jsonl"
        p.write_text("".join(json.dumps(l) + "\n" for l in L), encoding="utf8")
        if run:
            r = subprocess.run([str(MCP), "--script", str(p)], cwd=ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"{name}: {r.stderr[-3000:]}\n{r.stdout[-2000:]}")
            print(name, "ok")
        else:
            print("wrote", p.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main(sys.argv[1:])
