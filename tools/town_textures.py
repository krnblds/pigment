"""Texture the cyberpunk town kit with Pigment (via pigment-mcp --script).

For each asset: list its parts, classify them by shape (glass, frames, AC
units, LED strips, shell, trim...), write a Pigment script that builds the
material stack with part masks and decals, run it, export textures for
Blender and save the Pigment project.

Buildings and the overhead sign are authored ONCE with every candidate
story decal recorded (see tools/make_story_decals.py for the world), then
`export_variants` writes one texture set per variant:

    scenes/town/textures/<asset>__<variant>/<asset>_BaseColor.png ...
    scenes/town/textures/<asset>__<variant>/variant.json   (emissive_scale, decals shown)

Signage follows real-world placement rules (see "story signage" below and
docs/agents/decalfix/NOTES.md): corporate (Hoshikawa / Meridian / Dreamlink /
Noctis) billboards only on framed billboard panels (rooftop, back wall,
building_c's crown); street-economy shops (memory pawn, implant repair, score
reset, capsule hotel, noodles, clinic) on the fascia / sign boxes over the
ground-floor entrances; authority plates on the enamel plates by the doors;
resistance graffiti, UNPLUG and MISSING posters on blank street-level wall.
Every decal is an exact world-space box decal on one flat surface;
tools/decal_audit.py checks every variant. Lit windows are a seeded random
subset of the glass parts per variant.

    python tools/town_textures.py [asset ...]        (all assets by default)
    PIGMENT_MCP=path/to/pigment-mcp.exe python tools/town_textures.py building_a
    PIG_TMP=dir                                       (scratch scripts and previews; default %TEMP%/pig)
    python tools/decal_audit.py                       (then audit the placements)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
OUT = ROOT / "scenes" / "town"
DECALS = "assets/decals/"
STORY = "assets/decals/story/"
ADS = "assets/decals/ads/"             # tools/make_ad_decals.py (the ad-saturated city)
TMP = Path(os.environ.get("PIG_TMP", Path.home() / "AppData" / "Local" / "Temp" / "pig"))
PREVIEWS = TMP / "town_variants"
# texture size per asset (variants multiply the textures Blender has to hold)
RES = {"building_a": 2048, "building_b": 2048, "building_c": 4096, "overhead_sign": 1024}


def run(lines, label):
    script = TMP / f"town_{label}.jsonl"
    script.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf8")
    r = subprocess.run([str(MCP), "--script", str(script)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{label}: {r.stderr[-2000:]}")
    return r.stdout


_PARTS = {}


def parts_of(asset):
    if asset in _PARTS:
        return _PARTS[asset]
    out = run([{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": 512}}, {"tool": "list_parts", "args": {}}], f"{asset}_parts")
    _PARTS[asset] = json.loads(out[out.index("[list_parts] ") + 13:])
    return _PARTS[asset]


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


def weathering(shell, ledges=None):
    """`ledges`: parts that can hold moss and standing water (default: the shell)."""
    ledges = ledges or shell
    return [
        fill("Damp patches", "Wet concrete", shell, {"generator": "grunge", "amount": 0.45, "scale": 0.7, "softness": 0.25}, opacity=0.5, channels={"height": False, "metallic": False}),
        fill("Rain streaks", "Grime", shell, {"generator": "streaks", "amount": 0.3, "scale": 2.0, "softness": 0.15}, opacity=0.5),
        # drip streaks under sills, AC units and ledges (drip bake), damp and dark
        fill("Leaks", None, shell, {"generator": "leaks", "amount": 0.55, "scale": 2.5, "breakup": 0.6, "drip_length": 3.0, "ao_influence": 0.2, "softness": 0.15},
             values={"base_color": [0.05, 0.045, 0.04], "roughness": 0.3}, opacity=0.75, channels={"height": False, "metallic": False}),
        # moss / grime build-up on ledges, sills and in crevices
        fill("Ledge moss", None, ledges, {"generator": "moss", "amount": 0.4, "scale": 3.0, "breakup": 0.7, "softness": 0.12},
             values={"base_color": [0.09, 0.12, 0.05], "roughness": 0.85}, opacity=0.85, channels={"height": False, "metallic": False}),
        # standing rain water on flat roofs, ledges and sills
        fill("Rain water", None, ledges, {"generator": "puddles", "amount": 0.35, "scale": 0.8, "softness": 0.05},
             values={"base_color": [0.03, 0.03, 0.032], "roughness": 0.02}, opacity=0.8, channels={"height": False, "metallic": False}),
        fill("Street grime", "Grime", None, {"generator": "dirt", "amount": 0.5, "softness": 0.25, "breakup": 0.5,
                                             "effects": [{"generator": "gradient", "op": "max", "amount": 0.12, "breakup": 0.5}]}, opacity=0.8),
    ]


def windows(glass):
    """See-through glass with seeded random lit subsets. All lit layers share salt 1
    with disjoint ranges, so a window is at most one colour; the variant seed
    reshuffles which windows are lit. Group "lights" can be swapped for the
    near-dark "Lit windows (few)" (an evicted building)."""
    # real glass: partly see-through, refracting, glossy (reflections)
    L = [fill("Glass", None, glass, values=GLASS, channels={"height": False})]
    # Night windows as people actually light them: mostly warm tungsten in a
    # few shades and brightnesses, some cool office fluorescents, and rarely
    # the dim blue of a Meridian feed playing to an empty room. Most stay dark.
    bands = (("Lit windows (tungsten)", 0.00, 0.14, [1.0, 0.58, 0.28], 1.5),
             ("Lit windows (soft warm)", 0.14, 0.24, [1.0, 0.72, 0.48], 1.1),
             ("Lit windows (dim lamp)", 0.24, 0.31, [0.95, 0.5, 0.22], 0.55),
             ("Lit windows (fluorescent)", 0.31, 0.36, [0.86, 0.93, 1.0], 1.2),
             ("Meridian screens", 0.36, 0.375, [0.45, 0.58, 1.0], 0.5))
    for name, a, b, col, k in bands:
        # lit windows stay solid glowing panes (opacity 1 over the glass below)
        L.append(fill(name, None, glass, values={"base_color": col, "roughness": 0.1, "metallic": 0.0, "emissive": col, "emissive_strength": k, "opacity": 1.0, "transmission": 0.0},
                      channels={"height": False}, part_subset={"from": a, "to": b, "salt": 1}, variant="lights"))
    # curtains and clutter: break up some lit panes so they aren't flat slabs of light
    L.append(fill("Curtains", None, glass, {"generator": "grunge", "amount": 0.45, "scale": 0.35, "softness": 0.3},
                  values={"base_color": [0.25, 0.16, 0.1], "roughness": 0.8, "metallic": 0.0, "emissive": [1.0, 0.55, 0.3], "emissive_strength": 0.25, "opacity": 1.0, "transmission": 0.0},
                  channels={"height": False}, part_subset={"from": 0.0, "to": 0.31, "salt": 1}, variant="lights"))
    L.append(fill("Lit windows (few)", None, glass, values={"base_color": [1.0, 0.7, 0.4], "roughness": 0.1, "metallic": 0.0, "emissive": [1.0, 0.7, 0.4], "emissive_strength": 1.6, "opacity": 1.0, "transmission": 0.0},
                  channels={"height": False}, part_subset={"from": 0.0, "to": 0.07, "salt": 2}, variant="lights_few", visible=False))
    return L


GLASS = {"base_color": [0.6, 0.7, 0.75], "roughness": 0.03, "metallic": 0.0, "opacity": 0.3, "transmission": 1.0}
# only the opacity channel: holes don't drag their colour into the wire edges
CUT_ONLY = {"base_color": False, "roughness": False, "metallic": False, "height": False, "normal": False}


def perforated(name, parts, holes_per_metre, bar):
    """Square holes in a world-aligned grid: cut the whole part out (opacity 0),
    then bring the bars back (opacity 1) through a panel-lines mask. (An
    inverted mask would also invert its part selection.)"""
    return [fill(name, "Cut-out", parts, channels=CUT_ONLY),
            fill(name + " (bars)", None, parts, {"generator": "panel_lines", "amount": bar, "scale": holes_per_metre, "softness": 0.02},
                 values={"opacity": 1.0}, channels=CUT_ONLY)]


def common(c):
    L = []
    L += windows(list(c.get("glass", [])))
    if c.get("signface"):
        L.append(fill("Sign faces", None, c["signface"], values={"base_color": [0.015, 0.015, 0.02], "roughness": 0.3, "metallic": 0.0}, channels={"height": False}))
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
        L += perforated("Grille holes", c["grille"], 30.0, 0.3)
    if c.get("wire"):
        L.append(fill("Cables", "Matte black", c["wire"]))
    if c.get("led"):
        leds = c["led"]
        L.append(fill("LED strips (cyan)", "Neon cyan", leds[0::2], values={"emissive_strength": 5.0}))
        if leds[1::2]:
            L.append(fill("LED strips (pink)", "Neon pink", leds[1::2], values={"emissive_strength": 5.0}))
    return L


def building(asset, base, shell_extra):
    parts = parts_of(asset)
    c = {}
    shells = [p for p in parts if classify(p) == "shell"]
    roof_y = max(p["center"][1] + p["size"][1] / 2 for p in shells) - 0.6
    for p in parts:
        k = classify(p)
        if k == "glass" and p["size"][1] >= 3.0:  # tall glass
            k = "signface"        # the faces of a blade sign, not a window
        if k == "trim":
            s = sorted(p["size"])
            bottom = p["center"][1] - p["size"][1] / 2
            if s[0] <= 0.08 and 0.9 <= s[1] <= 1.4 and 2.2 <= s[2] <= 2.7 and bottom < 0.6:
                k = "door"
            elif bottom >= roof_y:
                k = "roof"
        c.setdefault(k, []).append(p["id"])
    shell = c.get("shell", [])
    L = [{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": RES.get(asset, 2048), "material": base}},
         {"tool": "bake", "args": {"curvature_radius": 0.004, "curvature_strength": 0.7, "ao_distance": 0.12}}]
    L += shell_extra(shell)
    L += common(c)
    L += weathering(shell, shell + c.get("trim", []) + c.get("roof", []))
    return L, c

# ------------------------------------------------------------------ story signage
# Placement rules (docs/agents/decalfix/NOTES.md; checked by tools/decal_audit.py):
#   billboard   only on a billboard panel (a "panel" part inside its own frame)
#   ghost       a faded wall-painted ad: low opacity, heavy wear, blank wall, sparingly
#   shop        centred on the fascia / sign box over a ground-floor entrance
#   blade       on the faces of the blade sign box only
#   logo, corp  corporate signage on a crown panel, the lobby fascia or a sign box
#   plate       eye height (centre 1.4-1.9 m) on flat wall beside a door
#   poster      street level (0.8-2.2 m) on blank wall, scattered with `fit` and wear
#   graffiti    ground level up to ~3 m on blank wall, shutters or doors
# Every decal is a precise world-space box decal (position + normal + size in
# metres) on ONE flat surface, so nothing wraps over a window, ledge or corner.

# Neon colours per sign: a street reads as many shops, not one palette.
NEON = {
    "sign_memory_pawn": [1.0, 0.6, 0.15], "sign_implant_repair": [0.2, 0.9, 1.0], "sign_score_reset": [1.0, 0.2, 0.6],
    "sign_capsule_2h": [0.6, 0.35, 1.0], "sign_clinic": [0.3, 1.0, 0.4], "sign_dumplings": [1.0, 0.35, 0.12],
    "sign_jailbreak": [0.55, 1.0, 0.1], "sign_organ_credit": [1.0, 0.12, 0.15], "sign_offgrid": [0.2, 1.0, 0.8],
    "sign_charge": [1.0, 0.85, 0.2], "sign_karaoke": [1.0, 0.3, 0.85], "sign_dreams": [0.8, 0.5, 1.0],
    "sign_hoshikawa_security": [0.75, 0.9, 1.0], "sign_meridian_kiosk": [0.4, 0.9, 1.0],
    "blade_kioku": [1.0, 0.6, 0.15], "blade_gitai": [0.2, 0.9, 1.0], "blade_capsule": [0.6, 0.35, 1.0],
    "blade_soba": [1.0, 0.4, 0.1], "blade_yume": [1.0, 0.3, 0.75], "blade_pachinko": [0.4, 1.0, 0.3],
    # red-light district neon (assets/decals/ads)
    "sign_velvet_moon": [1.0, 0.25, 0.65], "sign_club_sapphire": [0.35, 0.55, 1.0], "sign_cabaret_luna": [1.0, 0.75, 0.35],
    "sign_dolls_kisaragi": [0.85, 0.75, 1.0], "sign_peep_show": [1.0, 0.15, 0.35], "sign_host_zero": [1.0, 0.82, 0.4],
    "sign_snack_yocho": [1.0, 0.45, 0.7], "sign_welcome_yoimachi": [1.0, 0.35, 0.6],
    "blade_hotel": [1.0, 0.25, 0.65], "blade_kyukei": [1.0, 0.5, 0.8], "blade_snack": [1.0, 0.45, 0.7],
    "blade_cabaret": [1.0, 0.75, 0.35], "blade_club": [0.35, 0.55, 1.0],
}

AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


def image_path(image):
    if image.startswith("logo"):
        return DECALS + image + ".png"
    if (ROOT / ADS / (image + ".png")).exists():
        return ADS + image + ".png"
    return STORY + image + ".png"


def image_aspect(image):
    """width / height of a story (or logo) decal image."""
    from PIL import Image
    with Image.open(ROOT / image_path(image)) as im:
        return im.size[0] / im.size[1]


def find_part(parts, center, size, tol=0.06):
    """The part whose bounds match `center` / `size` (metres, glTF axes): part ids
    move when the kit changes, shapes don't. Fails loudly if nothing matches."""
    d = lambda p: max(max(abs(a - b) for a, b in zip(p["center"], center)), max(abs(a - b) for a, b in zip(p["size"], size)))
    best = min(parts, key=d)
    if d(best) > tol:
        raise SystemExit(f"no part at {center} size {size} (closest: {best['id']} {best['center']} {best['size']})")
    return best["id"]


def face_of(part, facing):
    """(centre of the part's face on `facing`, normal, (width, height)) from its bounds."""
    n = AXES[facing]
    k = [abs(x) for x in n].index(1)
    if k == 1:
        raise SystemExit("signage goes on vertical faces")
    c = list(part["center"])
    c[k] += n[k] * part["size"][k] / 2
    w = part["size"][2] if k == 0 else part["size"][0]
    return c, n, (w, part["size"][1])


def fit_size(aspect, w, h, margin):
    """Largest image of `aspect` that fits w x h minus a margin all round (contain)."""
    w, h = w - 2 * margin, h - 2 * margin
    return (w, w / aspect) if w / aspect <= h else (h * aspect, h)


def on_part(kind, parts, center, size, facing, margin=0.06):
    """A slot on the face of a part found by its bounds: the image is centred and sized to fit."""
    pid = find_part(parts, center, size)
    p = next(q for q in parts if q["id"] == pid)
    c, n, (w, h) = face_of(p, facing)
    return {"kind": kind, "part": pid, "position": [round(x, 4) for x in c], "normal": list(n), "box": (w, h), "margin": margin}


def on_wall(kind, at, facing, width, **kw):
    """A slot on flat wall: centre `at` (on the wall plane), image `width` in metres."""
    return dict(kind=kind, position=list(at), normal=list(AXES[facing]), width=width, **kw)


def scatter_slot(parts_ids, region, seed, count=4, **kw):
    """Posters: scattered on blank street-level wall (`fit`: never over an opening or an edge).
    kw: `size` [min, max] m and `spacing` (min distance between centres): a dense, overlapping
    ad wall is more, smaller posters closer than their width."""
    return {"kind": "poster", "scatter": dict(parts=parts_ids, region=region, count=count, seed=seed, **kw)}


def look(kind, image):
    """Paper tears and fades, paint is grungy, enamel barely ages, neon glows."""
    if kind in ("shop", "blade", "corp") and image in NEON:            # white glyphs: tint + glow
        return dict(tint=NEON[image], emissive_strength=6.0, material="Neon pink")
    if kind == "blade" and image.startswith("banner"):                 # full-colour lit banner on a blade face
        return dict(emissive_strength=1.8, material="White plastic")
    if kind == "window":                                               # cut vinyl lettering on shop glass
        return dict(material="White plastic", opacity=0.95, fade=0.1, wear_scale=6.0, values={"opacity": 1.0, "transmission": 0.0})
    if kind == "billboard":                                            # backlit corporate ads
        return dict(emissive_strength=1.6, material="White plastic")
    if kind == "logo":
        return dict(tint=[0.85, 0.92, 1.0], emissive_strength=2.0)
    if kind == "ghost":                                                # an old painted ad, mostly gone
        return dict(material="White plastic", tint=[0.82, 0.78, 0.72], opacity=0.45, wear=0.45, fade=0.6,
                    wear_style="grunge", wear_scale=2.0, paper_rim=0.0)
    if kind == "graffiti":
        return dict(material="White plastic", opacity=0.92, fade=0.25, wear_style="grunge", wear_scale=3.0, paper_rim=0.0)
    if kind == "plate":
        return dict(material="White plastic", opacity=0.97, fade=0.15, wear_scale=6.0)
    return dict(material="White plastic", opacity=0.95, wear=0.3, fade=0.3, wear_scale=3.5)   # paper


def placement(slot, image):
    """(tool, args) for one slot and image (a list of images for a poster cluster)."""
    if "scatter" in slot:
        s = slot["scatter"]
        imgs = image if isinstance(image, list) else [image]
        a = {"images": [image_path(i) for i in imgs], "count": s["count"], "seed": s["seed"], "parts": s["parts"],
             "region": s["region"], "height": [0.8, 2.2], "size": s.get("size", [0.5, 0.62]), "rotation_jitter": 4,
             "min_spacing": s.get("spacing", 0.38), "fit": True}
        a.update(look("poster", imgs[0]))
        return "scatter_decals", a
    a = {"image": image_path(image), "position": slot["position"], "normal": slot["normal"]}
    if "box" in slot:
        w, h = fit_size(image_aspect(image), *slot["box"], slot["margin"])
    else:
        w = slot["width"]
        h = w / image_aspect(image)
    a["size"] = [round(w, 4), round(h, 4)]
    if slot.get("rotation"):
        a["rotation"] = slot["rotation"]
    a.update(look(slot["kind"], image))
    return "project_decal", a


KIND_ORDER = {"billboard": 0, "logo": 0, "corp": 0, "shop": 0, "blade": 0, "window": 0, "ghost": 1, "poster": 2, "plate": 3, "graffiti": 4}


def story(slots, variants):
    """Record every (slot, image) decal once on a "Story decals" paint layer,
    tagged "story", enabled only if the first variant uses it. Paper goes down
    before plates and graffiti (variants replay decals in record order).
    Returns the script lines and the export_variants definitions."""
    for v in variants:
        for slot in v["on"]:
            if slot not in slots:
                raise SystemExit(f"variant {v['name']}: no slot `{slot}`")
    key = lambda img: "+".join(img) if isinstance(img, list) else img
    used = {}
    for v in variants:
        for slot, img in v["on"].items():
            if img:
                used.setdefault((slot, key(img)), img)
    first = {(s, key(i)) for s, i in variants[0]["on"].items() if i}
    L = [{"tool": "add_layer", "args": {"kind": "paint", "name": "Story decals"}}]
    for (slot, k), img in sorted(used.items(), key=lambda e: KIND_ORDER[slots[e[0][0]]["kind"]]):
        tool, a = placement(slots[slot], img)
        a.update(layer="Story decals", name=f"{slot}/{k}", variant="story", enabled=(slot, k) in first)
        L.append({"tool": tool, "args": a})
    defs = []
    for v in variants:
        enable = [f"{s}/{key(i)}" for s, i in v["on"].items() if i]
        disable = ["story"]
        if v.get("lights") == "few":
            disable.append("lights")
            enable.append("lights_few")
        d = {"name": v["name"], "seed": v["seed"], "disable": disable, "enable": enable}
        if v.get("swaps"):
            d["swaps"] = v["swaps"]
        defs.append(d)
    return L, defs


def finish(L, asset, defs=None):
    T = str(TMP).replace("\\", "/")
    L += [
        {"tool": "render", "args": {"yaw": 25, "pitch": 12, "width": 640, "height": 800, "exposure": -0.3, "path": f"{T}/town_tex_{asset}_a.png"}},
        {"tool": "render", "args": {"yaw": -50, "pitch": 18, "width": 640, "height": 800, "exposure": -0.3, "path": f"{T}/town_tex_{asset}_b.png"}},
    ]
    if defs:
        P = str(PREVIEWS).replace("\\", "/")
        view = PREVIEW_VIEW.get(asset, {"yaw": 25, "pitch": 10})
        L.append({"tool": "export_variants", "args": {"dir": "scenes/town/textures", "name": asset, "preset": "separate", "variants": defs,
                                                      "preview": dict(view, width=480, height=640, exposure=-0.4, dir=P)}})
    # the authored look always gets a base folder too (fallback for tools that don't pick variants)
    L.append({"tool": "export_textures", "args": {"dir": f"scenes/town/textures/{asset}", "preset": "separate", "name": asset}})
    L.append({"tool": "save_project", "args": {"path": f"scenes/town/projects/{asset}.pigment"}})
    (OUT / "scripts").mkdir(parents=True, exist_ok=True)
    (OUT / "scripts" / f"{asset}.jsonl").write_text("\n".join(json.dumps(l) for l in L), encoding="utf8")
    out = run(L, asset)
    (TMP / f"town_{asset}.log").write_text(out, encoding="utf8")
    warn = [line for line in out.splitlines() if '"warning"' in line]
    scale = [line for line in out.splitlines() if "emissive_scale" in line]
    print(asset, "ok", scale[-1].strip() if scale else "", f"({len(warn)} texel warnings)" if warn else "")


PREVIEW_VIEW = {
    "building_a": {"yaw": 28, "pitch": 6},
    "building_b": {"yaw": 22, "pitch": 6},
    "building_c": {"yaw": 30, "pitch": 6},
    "overhead_sign": {"yaw": 90, "pitch": 4, "zoom": 1.2},
}

# ------------------------------------------------------------------ building A: narrow 6-storey walk-up

# glTF axes: front +z (wall z=5), sides x=+-4 (windows only above the ground
# floor), blank back wall z=-5 (pipes at x 0.9 / 1.12 / -3.55). Ground floor
# y 0..4.2: shop recess x -3.6..1.4 under a fascia lightbox, stair door x 2.0..3.2.


def a_slots(parts):
    shell = [find_part(parts, (0, 2.1, 0), (8, 4.2, 10))]          # ground-floor wall
    return {
        "blade_e": on_part("blade", parts, (3.708, 10.0, 5.75), (0.012, 5.88, 1.08), "+x", margin=0.05),
        "blade_w": on_part("blade", parts, (3.392, 10.0, 5.75), (0.012, 5.88, 1.08), "-x", margin=0.05),
        "shop": on_part("shop", parts, (-1.1, 3.64, 5.2), (5.3, 0.8, 0.4), "+z", margin=0.07),
        "roof": on_part("billboard", parts, (0.0, 24.1, 3.4), (6.4, 3.2, 0.08), "+z", margin=0.04),
        "back": on_part("billboard", parts, (0.4, 10.6, -5.42), (6.4, 3.2, 0.08), "-z", margin=0.04),
        # ghost sign: blank back wall above the billboard, clear of the pipes
        "ghost": on_wall("ghost", (-1.35, 15.4, -5.0), "-z", 3.5),
        # enamel plate (its own kit part) on the pier between the shop and the stair door
        "plate": on_part("plate", parts, (1.7, 1.62, 5.007), (0.46, 0.23, 0.012), "+z", margin=0.008),
        "tag_e": on_wall("graffiti", (4.0, 1.55, -1.2), "+x", 2.8, rotation=2),
        "tag_w": on_wall("graffiti", (-4.0, 1.6, -2.4), "-x", 2.6, rotation=-3),
        "posters_w": scatter_slot(shell, {"min": [-4.3, 0.0, -2.6], "max": [-3.7, 3.0, 0.6]}, seed=5),
        "posters_e": scatter_slot(shell, {"min": [3.7, 0.0, 1.2], "max": [4.3, 3.0, 4.6]}, seed=9, count=3),
        # ads (tools/make_ad_decals.py): the shop window's vinyl, a dense overlapping ad wall on the
        # blank back wall (clear of the pipes at x 0.9 / -3.55) and a second cluster on the west wall
        # vinyl on the shop glass (part at z 4.43), below the transom frame (bottom at y 1.99)
        "window": on_wall("window", (-2.0, 1.24, 4.436), "+z", 2.6),
        "ads_back": scatter_slot(shell, {"min": [-3.0, 0.0, -5.3], "max": [0.3, 3.0, -4.7]}, seed=31, count=7, size=[0.5, 0.6], spacing=0.32),
        "ads_w": scatter_slot(shell, {"min": [-4.3, 0.0, 1.0], "max": [-3.7, 3.0, 4.4]}, seed=33, count=6, size=[0.5, 0.6], spacing=0.32),
    }


def blade(img):
    return {"blade_e": img, "blade_w": img}


# ad clusters (assets/decals/ads): paper layered on paper, the resistance pasting its answers over the glamour
ADS_STREET = ["poster_ad_volt_rush", "flyer_money_today", "poster_ad_sale_now", "sticker_score_qr", "poster_ad_hoshicoin", "flyer_kidney_cash", "poster_ad_torn_sale_hostess"]
ADS_CORP = ["poster_ad_platinum_citizen", "poster_ad_meridian_lotto", "poster_ad_unplug_over_platinum", "poster_ad_hoshikawa_limbs", "poster_ad_aqua_pure", "sticker_rate_street"]
ADS_FOOD = ["poster_ad_ramen_retro", "poster_ad_pachinko_galaxy", "flyer_grand_open", "poster_ad_noctis_sleep", "flyer_rent_face", "poster_ad_volt_rush"]
ADS_LOVE = ["poster_ad_velvet_moon_rates", "sticker_hotel_heart", "sticker_call_velvet", "poster_ad_torn_layers", "poster_ad_rouge9_lips",
            "sticker_call_angel", "poster_ad_dreamlink_intimate"]
ADS_CLUB = ["poster_ad_club_sapphire", "poster_ad_host_zero", "flyer_missing_kei", "poster_ad_missing_over_hostess", "sticker_call_moon",
            "poster_ad_who_owns_dolls", "flyer_snack_bar"]
ADS_SHOW = ["poster_ad_rose_theatre", "poster_ad_cabaret_hanabi", "poster_ad_peep_show", "poster_ad_noir_satin_legs", "sticker_call_stiletto",
            "poster_ad_not_for_sale", "flyer_dream_bootleg"]

A_VARIANTS = [
    {"name": "memory_pawn", "seed": 11, "on": {**blade("blade_kioku"), "shop": "sign_memory_pawn", "roof": "billboard_noctis",
                                               "tag_e": "graffiti_who_owns", "plate": "plate_observed", "posters_w": ["poster_missing_aiko", "poster_missing_ren"],
                                               "ads_back": ADS_STREET}},
    {"name": "implants", "seed": 23, "on": {**blade("blade_gitai"), "shop": "sign_implant_repair", "roof": "billboard_ad_hoshikawa_limbs", "back": "billboard_ad_sakura_credit",
                                            "tag_w": "graffiti_not_data", "plate": "plate_loitering", "posters_w": ["poster_unplug"], "ads_back": ADS_CORP}},
    {"name": "capsules", "seed": 37, "on": {**blade("blade_capsule"), "shop": "sign_capsule_2h", "roof": "billboard_dreamlink", "back": "billboard_ad_capsule_estate",
                                            "tag_e": "graffiti_unplug", "plate": "plate_curfew", "posters_w": ["poster_missing_mika"], "ads_back": ADS_FOOD}},
    {"name": "soba", "seed": 41, "on": {**blade("blade_soba"), "shop": "sign_dumplings", "roof": "billboard_ad_ramen_kira", "ghost": "billboard_noctis",
                                        "tag_w": "graffiti_lying", "plate": "plate_observed", "posters_e": ["poster_missing_ren", "poster_unplug"], "ads_w": ADS_FOOD}},
    {"name": "dream_den", "seed": 53, "on": {**blade("blade_yume"), "shop": "sign_dreams", "roof": "billboard_jobs", "back": "billboard_dreamlink",
                                             "tag_e": "stencil_eye_crossed", "plate": "plate_curfew", "posters_w": ["poster_unplug", "poster_missing_aiko"]}},
    # evicted: the shop is gone (dark fascia), a seizure plate, an old ghost ad, everything torn
    {"name": "evicted", "seed": 67, "lights": "few", "on": {"roof": "billboard_defaced", "ghost": "billboard_jobs", "plate": "plate_property",
                                                           "tag_e": "graffiti_unplug", "tag_w": "stencil_eye_crossed",
                                                           "posters_w": ["poster_missing_mika", "poster_unplug", "poster_missing_ren"]}},
    {"name": "fixers", "seed": 79, "on": {**blade("blade_pachinko"), "shop": "sign_score_reset", "roof": "billboard_meridian", "back": "billboard_score",
                                          "tag_w": "graffiti_who_owns", "plate": "plate_loitering", "posters_e": ["poster_missing_ren"], "ads_back": ADS_STREET}},
    # the red-light district (Yoimachi): a love hotel and a hostess bar, wallpapered with their own ads
    {"name": "love_hotel", "seed": 91, "on": {"blade_e": "banner_velvet_moon", "blade_w": "blade_kyukei", "shop": "sign_velvet_moon",
                                              "roof": "billboard_ad_velvet_moon", "back": "billboard_ad_dreamlink_intimate", "window": "window_hotel_rates",
                                              "tag_e": "graffiti_who_owns", "plate": "plate_observed", "ads_back": ADS_LOVE, "ads_w": ADS_SHOW}},
    {"name": "hostess_bar", "seed": 97, "on": {"blade_e": "banner_club_sapphire", "blade_w": "blade_club", "shop": "sign_club_sapphire",
                                               "roof": "billboard_ad_dolls_kisaragi", "back": "billboard_ad_noir_satin", "window": "window_members_only",
                                               "tag_w": "graffiti_lying", "plate": "plate_curfew", "ads_back": ADS_CLUB, "ads_w": ADS_LOVE}},
]


def build_a():
    shell_extra = lambda shell: [fill("Slab joints", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.012, "scale": 0.6})]
    L, _ = building("building_a", "Concrete", shell_extra)
    S, defs = story(a_slots(parts_of("building_a")), A_VARIANTS)
    finish(L + S, "building_a", defs)

# ------------------------------------------------------------------ building B: wide 3-storey with 4 shop bays + roof billboard

# glTF axes: front +z (upper wall z=6, bays recessed to z=4.0, bay centres
# x -5.85 / -1.95 / 1.95 / 5.85, each with a fascia sign box), sides x=+-8 and
# back z=-6 blank below the band at 4.5. Stair door at the back of bay 4.


def b_slots(parts):
    shell = [find_part(parts, (0, 2.25, 0), (16, 4.5, 12))]        # ground-floor wall
    bay = lambda u: (u, 3.93, 6.123)
    return {
        "bay1": on_part("shop", parts, bay(-5.85), (3.2, 0.85, 0.25), "+z"),
        "bay2": on_part("shop", parts, bay(-1.95), (3.2, 0.85, 0.25), "+z"),
        "bay3": on_part("shop", parts, bay(1.95), (3.2, 0.85, 0.25), "+z"),
        "bay4": on_part("shop", parts, bay(5.85), (3.2, 0.85, 0.25), "+z"),
        "roof": on_part("billboard", parts, (2.2, 18.4, 3.6), (8.0, 4.0, 0.08), "+z", margin=0.04),
        # enamel plate (its own kit part) on bay 4's side wall, beside the stair door
        "plate": on_part("plate", parts, (4.157, 1.62, 4.45), (0.012, 0.23, 0.46), "+x", margin=0.008),
        "tag_e": on_wall("graffiti", (8.0, 1.6, -2.0), "+x", 3.0, rotation=-2),
        "tag_w": on_wall("graffiti", (-8.0, 1.65, -1.6), "-x", 3.0, rotation=3),
        "back": on_wall("graffiti", (-1.5, 1.7, -6.0), "-z", 3.4, rotation=1),
        "posters_w": scatter_slot(shell, {"min": [-8.3, 0.0, -1.2], "max": [-7.7, 3.0, 2.2]}, seed=7),
        "posters_e": scatter_slot(shell, {"min": [7.7, 0.0, 1.6], "max": [8.3, 3.0, 5.0]}, seed=13, count=3),
        # ads: vinyl on the two glazed bays, dense ad walls on the blank back wall (clear of the graffiti) and the east wall
        "window1": on_part("window", parts, (-6.5, 1.8, 4.03), (1.76, 1.66, 0.012), "+z", margin=0.06),
        "window2": on_part("window", parts, (-1.3, 1.8, 4.03), (1.76, 1.66, 0.012), "+z", margin=0.06),
        "ads_back": scatter_slot(shell, {"min": [0.8, 0.0, -6.3], "max": [7.0, 3.0, -5.7]}, seed=41, count=9, size=[0.5, 0.6], spacing=0.32),
        "ads_e": scatter_slot(shell, {"min": [7.7, 0.0, -5.0], "max": [8.3, 3.0, 0.8]}, seed=43, count=8, size=[0.5, 0.6], spacing=0.32),
    }


B_VARIANTS = [
    {"name": "noodle_row", "seed": 12, "on": {"bay1": "sign_dumplings", "bay2": "sign_karaoke", "bay3": "sign_charge", "bay4": "sign_offgrid",
                                              "roof": "billboard_ad_volt_rush", "tag_e": "graffiti_unplug", "posters_w": ["poster_missing_aiko"], "plate": "plate_curfew",
                                              "ads_back": ADS_FOOD}},
    {"name": "body_shop", "seed": 24, "on": {"bay1": "sign_implant_repair", "bay2": "sign_organ_credit", "bay3": "sign_clinic", "bay4": "sign_jailbreak",
                                             "roof": "billboard_noctis", "tag_w": "graffiti_lying", "posters_e": ["poster_unplug"], "plate": "plate_loitering"}},
    {"name": "dream_strip", "seed": 36, "on": {"bay1": "sign_dreams", "bay2": "sign_capsule_2h", "bay3": "sign_karaoke", "bay4": "sign_memory_pawn",
                                               "roof": "billboard_dreamlink", "tag_e": "graffiti_who_owns", "posters_w": ["poster_missing_mika", "poster_missing_ren"], "plate": "plate_observed"}},
    {"name": "score_fixers", "seed": 48, "on": {"bay1": "sign_score_reset", "bay2": "sign_jailbreak", "bay3": "sign_dumplings", "bay4": "sign_charge",
                                                "roof": "billboard_score", "tag_w": "graffiti_not_data", "back": "graffiti_unplug", "posters_e": ["poster_missing_ren"], "plate": "plate_loitering"}},
    {"name": "pawn_row", "seed": 60, "on": {"bay1": "sign_memory_pawn", "bay2": "sign_offgrid", "bay3": "sign_implant_repair", "bay4": "sign_dreams",
                                            "roof": "billboard_ad_sakura_credit", "tag_e": "stencil_eye_crossed", "posters_w": ["poster_unplug"], "plate": "plate_curfew",
                                            "ads_back": ADS_STREET, "ads_e": ADS_CORP}},
    # seized: two shops still trading, the shuttered bay dark, a seizure plate by the stairs
    {"name": "seized", "seed": 72, "lights": "few", "on": {"bay1": "sign_clinic", "bay4": "sign_organ_credit",
                                                          "roof": "billboard_defaced", "tag_e": "graffiti_unplug", "tag_w": "graffiti_who_owns", "back": "graffiti_lying",
                                                          "posters_w": ["poster_missing_aiko", "poster_missing_mika"], "plate": "plate_property"}},
    {"name": "night_market", "seed": 84, "on": {"bay1": "sign_organ_credit", "bay2": "sign_score_reset", "bay3": "sign_capsule_2h", "bay4": "sign_clinic",
                                                "roof": "billboard_ad_star_gacha", "tag_w": "stencil_eye_crossed", "posters_e": ["poster_missing_ren", "poster_missing_aiko"], "plate": "plate_observed",
                                                "ads_back": ADS_STREET}},
    # the red-light district (Yoimachi)
    {"name": "cabaret_row", "seed": 96, "on": {"bay1": "sign_cabaret_luna", "bay2": "sign_peep_show", "bay3": "sign_host_zero", "bay4": "sign_snack_yocho",
                                               "roof": "billboard_ad_cabaret_luna", "window1": "window_now_hiring", "window2": "window_hearts",
                                               "tag_w": "graffiti_who_owns", "plate": "plate_loitering", "posters_w": ADS_CLUB[:4],
                                               "ads_back": ADS_SHOW, "ads_e": ADS_LOVE}},
    {"name": "hostess_row", "seed": 108, "on": {"bay1": "sign_club_sapphire", "bay2": "sign_dolls_kisaragi", "bay3": "sign_velvet_moon", "bay4": "sign_karaoke",
                                                "roof": "billboard_ad_noir_satin", "window1": "window_members_only", "window2": "window_hotel_rates",
                                                "tag_e": "graffiti_unplug", "plate": "plate_observed", "ads_back": ADS_CLUB, "ads_e": ADS_SHOW}},
]


def build_b():
    def shell_extra(shell):
        wear = {"generator": "edge_wear", "amount": 0.5, "scale": 18.0, "breakup": 0.8, "softness": 0.05}
        return [fill("Teal paint", "Teal paint", shell),
                fill("Panel seams", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.01, "scale": 0.8}),
                fill("Chipped paint", "Steel", shell, wear, values={"height": -0.3})]
    L, _ = building("building_b", "Concrete", shell_extra)
    S, defs = story(b_slots(parts_of("building_b")), B_VARIANTS)
    finish(L + S, "building_b", defs)

# ------------------------------------------------------------------ building C: the Hoshikawa / Meridian tower

# glTF axes: front +z (wall z=7, lobby recess x -3.2..3.2 back to z 5.5), sides
# x=+-7 (lobby side windows: east z 0.75..4.25, west z -4.25..-0.75), back
# z=-7. The crown (y 31.4..35.8) carries a framed 8 x 3.6 m panel per face at +-5.3.


def c_slots(parts):
    shell = [find_part(parts, (0, 2.5, 0), (14, 5.0, 14))]         # ground-floor wall
    crown = lambda c, s, f: on_part("billboard", parts, c, s, f, margin=0.04)
    return {
        "lobby": on_part("logo", parts, (0.0, 4.985, 9.0), (6.4, 0.9, 0.2), "+z", margin=0.08),
        "band": on_part("corp", parts, (-5.1, 3.2, 7.078), (2.9, 0.5, 0.15), "+z", margin=0.05),
        "crown_n": crown((0.0, 33.55, 5.3), (8.0, 3.6, 0.08), "+z"),
        "crown_e": crown((5.3, 33.55, 0.0), (0.08, 3.6, 8.0), "+x"),
        "crown_s": crown((0.0, 33.55, -5.3), (8.0, 3.6, 0.08), "-z"),
        "crown_w": crown((-5.3, 33.55, 0.0), (0.08, 3.6, 8.0), "-x"),
        # enamel plate (its own kit part) on the lobby recess's side wall, beside the doors
        "plate": on_part("plate", parts, (3.193, 1.62, 6.35), (0.012, 0.23, 0.46), "-x", margin=0.008),
        "tag_e": on_wall("graffiti", (7.0, 1.6, -3.4), "+x", 3.0, rotation=-2),
        "tag_w": on_wall("graffiti", (-7.0, 1.6, 3.4), "-x", 3.0, rotation=2),
        "posters_w": scatter_slot(shell, {"min": [-7.3, 0.0, 1.2], "max": [-6.7, 3.0, 4.6]}, seed=17),
    }


C_VARIANTS = [
    {"name": "hoshikawa_hq", "seed": 13, "on": {"lobby": "logo_hoshikawa_dynamics", "band": "sign_hoshikawa_security", "crown_n": "billboard_meridian",
                                                "crown_e": "billboard_score", "crown_w": "billboard_jobs", "crown_s": "billboard_meridian",
                                                "plate": "plate_property", "tag_w": "stencil_eye_crossed"}},
    {"name": "meridian", "seed": 26, "on": {"lobby": "logo_hoshikawa_dynamics", "band": "sign_meridian_kiosk", "crown_n": "billboard_score",
                                            "crown_e": "billboard_meridian", "crown_w": "billboard_meridian", "crown_s": "billboard_jobs",
                                            "plate": "plate_observed", "tag_e": "graffiti_lying"}},
    {"name": "dreamlink", "seed": 39, "on": {"lobby": "logo_hoshikawa_dynamics", "band": "sign_hoshikawa_security", "crown_n": "billboard_dreamlink",
                                             "crown_e": "billboard_noctis", "crown_w": "billboard_defaced", "crown_s": "billboard_dreamlink",
                                             "plate": "plate_curfew", "tag_e": "graffiti_unplug", "tag_w": "graffiti_not_data",
                                             "posters_w": ["poster_unplug", "poster_missing_aiko"]}},
    # downtown's corporate ad crowns
    {"name": "platinum", "seed": 52, "on": {"lobby": "logo_hoshikawa_dynamics", "band": "sign_meridian_kiosk", "crown_n": "billboard_ad_meridian_platinum",
                                            "crown_e": "billboard_ad_meridian_future", "crown_s": "billboard_ad_hoshikawa_secure", "crown_w": "billboard_ad_platinum_defaced",
                                            "plate": "plate_observed", "tag_e": "graffiti_who_owns", "posters_w": ADS_CORP[:4]}},
    {"name": "showroom", "seed": 65, "on": {"lobby": "logo_hoshikawa_dynamics", "band": "sign_hoshikawa_security", "crown_n": "billboard_ad_kanzaki_hayate",
                                            "crown_e": "billboard_ad_kagerou_watch", "crown_s": "billboard_ad_hoshikawa_home", "crown_w": "billboard_ad_attention_market",
                                            "plate": "plate_property", "tag_w": "graffiti_not_data", "posters_w": ADS_STREET[:4]}},
]


def build_c():
    def shell_extra(shell):
        return [fill("Steel cladding", None, shell, values={"base_color": [0.2, 0.21, 0.23], "roughness": 0.5, "metallic": 0.7}),
                fill("Cladding seams", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.008, "scale": 0.5}),
                fill("Scratches", "Brushed steel", shell, {"generator": "scratches", "amount": 0.08, "scale": 3.0}, opacity=0.35)]
    L, _ = building("building_c", "Concrete", shell_extra)
    S, defs = story(c_slots(parts_of("building_c")), C_VARIANTS)
    finish(L + S, "building_c", defs)


# ------------------------------------------------------------------ streets and small props


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
         # rain water fills the low spots of the asphalt and the gutters along the curb
         fill("Wet rim", None, road, {"generator": "puddles", "amount": 0.5, "scale": 0.35, "breakup": 0.5, "curvature_weight": 1.5, "softness": 0.12}, values={"base_color": [0.1, 0.1, 0.105], "roughness": 0.12}, opacity=0.6, channels={"height": False, "metallic": False}),
         fill("Puddles", None, road, {"generator": "puddles", "amount": 0.33, "scale": 0.35, "breakup": 0.5, "curvature_weight": 1.5, "softness": 0.04}, values={"base_color": [0.07, 0.07, 0.075], "roughness": 0.015, "height": -0.05}),
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


def small(asset, base, extra, variants=None):
    parts = parts_of(asset)
    L = [{"tool": "new_project", "args": {"mesh": f"assets/town/{asset}.glb", "resolution": RES.get(asset, 1024), "material": base}}]
    X = extra(parts)
    L += X[0] if variants else X
    L.append(fill("Grime", "Grime", None, {"generator": "dirt", "amount": 0.5, "softness": 0.25, "effects": [{"generator": "gradient", "op": "max", "amount": 0.15}]}, opacity=0.7))
    finish(L, asset, X[1] if variants else None)


def lamp_extra(parts):
    glass = [p["id"] for p in parts if sorted(p["size"])[0] <= 0.03 and sorted(p["size"])[1] >= 0.1]
    return [fill("Lens", "LED white", glass, values={"emissive_strength": 8.0})] if glass else []


def pole_extra(parts):
    small_parts = [p["id"] for p in parts if max(p["size"]) <= 0.35]
    return [fill("Insulators", "White plastic", small_parts)]

# ------------------------------------------------------------------ overhead sign: a double-sided shop sign, 10 shops


SIGN_VARIANTS = [
    ("memory_pawn", "sign_memory_pawn", "sign_memory_pawn"),
    ("implant_repair", "sign_implant_repair", "sign_implant_repair"),
    ("score_reset", "sign_score_reset", "sign_score_reset"),
    ("capsule", "sign_capsule_2h", "sign_capsule_2h"),
    ("noodles", "sign_dumplings", "sign_dumplings"),
    ("clinic", "sign_clinic", "sign_clinic"),
    ("jailbreak", "sign_jailbreak", "sign_offgrid"),     # two shops share the sign
    ("organ_credit", "sign_organ_credit", "sign_organ_credit"),
    ("karaoke", "sign_karaoke", "sign_dreams"),
    ("charging", "sign_charge", "sign_offgrid"),         # a charging stall next to an off-grid repair shop
    # the red-light district hanging signs (assets/decals/ads)
    ("welcome", "sign_welcome_yoimachi", "sign_welcome_yoimachi"),   # the district welcome sign over the street
    ("velvet_moon", "sign_velvet_moon", "sign_velvet_moon"),
    ("peep_show", "sign_peep_show", "sign_dolls_kisaragi"),
    ("snack", "sign_snack_yocho", "sign_host_zero"),
]


def fence():
    """Chain-link (welded wire) fence: the panel is one quad, the wire is a cut-out."""
    parts = parts_of("fence")
    panel = [min(parts, key=lambda p: sorted(p["size"])[0])["id"]]  # the flat quad
    frame = [p["id"] for p in parts if p["id"] not in panel]
    L = [{"tool": "new_project", "args": {"mesh": "assets/town/fence.glb", "resolution": 4096, "material": "Brushed steel"}},
         {"tool": "bake", "args": {"curvature_radius": 0.004, "ao_distance": 0.1}},
         fill("Wire", None, panel, values={"base_color": [0.55, 0.57, 0.58], "roughness": 0.45, "metallic": 1.0}),
         *perforated("Chain-link holes", panel, 16.0, 0.14),
         fill("Posts", "Gunmetal", frame),
         fill("Rust", "Rust", None, {"generator": "spots", "amount": 0.25, "scale": 6.0}, opacity=0.7),
         fill("Grime", "Grime", None, {"generator": "gradient", "amount": 0.25, "breakup": 0.5}, opacity=0.6)]
    finish(L, "fence")


def sign_extra(parts):
    faces = sorted([p for p in parts if sorted(p["size"])[0] <= 0.03 and sorted(p["size"])[1] >= 0.8], key=lambda p: p["center"][0])
    L = [fill("Sign backing", None, [f["id"] for f in faces], values={"base_color": [0.015, 0.015, 0.02], "roughness": 0.3, "metallic": 0.0})]

    def face(p, facing):
        c, n, (w, h) = face_of(p, facing)
        return {"kind": "shop", "part": p["id"], "position": [round(x, 4) for x in c], "normal": list(n), "box": (w, h), "margin": 0.08}
    slots = {"face_w": face(faces[0], "-x"), "face_e": face(faces[-1], "+x")}
    variants = [{"name": n, "seed": 100 + 7 * k, "on": {"face_w": w, "face_e": e}} for k, (n, w, e) in enumerate(SIGN_VARIANTS)]
    S, defs = story(slots, variants)
    return L + S, defs


# ------------------------------------------------------------------ world sheets (tools/world)
# Seamless Pigment tiles for the open world (flat sheet projects, see
# docs/agents/roads/NOTES.md): terrain (rock, grass, dirt, sand), tower
# facades (8 x 8 m: 4 bays x 2 storeys, glass panes placed as box decals so
# the runtime shader knows exactly where the windows are) and corrugated
# metal for warehouses and containers. They export to
# scenes/town/textures/world/<name>/.
#     python tools/town_textures.py world            (all of them)
#     python tools/town_textures.py world:rock,sand  (some)

WORLD_TEX = "scenes/town/textures/world"
WORLD_PROJ = "scenes/town/projects/world"
BAR = "assets/decals/roads/bar.png"          # white box stencil (tools/road_textures.py)


def _sheet(name, size, res, material, base, layers, extra=()):
    L = [{"tool": "new_project", "args": {"tile": {"size_m": size, "name": name}, "resolution": res, "material": material}},
         {"tool": "delete_layer", "args": {"layer": "Paint"}},
         {"tool": "update_layer", "args": {"layer": "Base", "values": base}}]
    for a in layers:
        L.append({"tool": "add_layer", "args": a})
    L += list(extra)
    T = str(TMP).replace("\\", "/")
    L += [{"tool": "render", "args": {"yaw": 0, "pitch": 89.9, "zoom": 1.0, "width": 700, "height": 700, "background": False, "path": f"{T}/world_{name}.png"}},
          {"tool": "export_textures", "args": {"dir": f"{WORLD_TEX}/{name}", "name": name, "preset": "separate"}},
          {"tool": "save_project", "args": {"path": f"{WORLD_PROJ}/{name}.pigment"}}]
    return L


def _g(gen, **kw):
    d = {"generator": gen}
    d.update(kw)
    return d


def world_rock():
    return _sheet("rock", [4, 4], 2048, "Concrete", {"base_color": [0.21, 0.2, 0.19], "roughness": 0.85}, [
        {"name": "Strata", "values": {"base_color": [0.29, 0.27, 0.25], "height": 0.35}, "opacity": 0.8, "mask": _g("grunge", amount=0.5, scale=0.6, softness=0.2, seed=3)},
        {"name": "Boulders", "values": {"base_color": [0.33, 0.32, 0.3], "height": 0.8}, "mask": _g("grunge", amount=0.42, scale=1.1, softness=0.12, seed=5)},
        {"name": "Ledges", "values": {"base_color": [0.25, 0.24, 0.22], "height": 0.5}, "opacity": 0.8, "mask": _g("grunge", amount=0.35, scale=2.6, softness=0.06, seed=6)},
        {"name": "Fissures", "values": {"base_color": [0.06, 0.055, 0.05], "height": -1.0}, "mask": _g("scratches", amount=0.14, scale=0.8, softness=0.03, seed=7)},
        {"name": "Grain", "values": {"base_color": [0.4, 0.38, 0.35], "height": 0.15}, "opacity": 0.5, "mask": _g("spots", amount=0.25, scale=80.0, softness=0.05, seed=9)},
        {"name": "Lichen", "values": {"base_color": [0.32, 0.33, 0.2], "roughness": 0.95}, "opacity": 0.55, "mask": _g("spots", amount=0.18, scale=6.0, softness=0.2, seed=11)},
        {"name": "Moss in cracks", "values": {"base_color": [0.08, 0.12, 0.05], "roughness": 0.95}, "opacity": 0.7, "mask": _g("moss", amount=0.25, scale=1.5, breakup=0.8, seed=13)},
        {"name": "Wet", "values": {"base_color": [0.1, 0.1, 0.1], "roughness": 0.3}, "opacity": 0.35, "channels": {"height": False}, "mask": _g("puddles", amount=0.2, scale=0.8, breakup=0.6, softness=0.2, seed=15)},
    ])


def world_grass():
    return _sheet("grass", [4, 4], 2048, "Concrete", {"base_color": [0.075, 0.11, 0.04], "roughness": 0.92}, [
        {"name": "Blades light", "values": {"base_color": [0.13, 0.17, 0.06], "height": 0.3}, "opacity": 0.8, "mask": _g("scratches", amount=0.35, scale=9.0, softness=0.05, seed=21)},
        {"name": "Clumps", "values": {"base_color": [0.1, 0.15, 0.05], "height": 0.25}, "mask": _g("spots", amount=0.4, scale=14.0, softness=0.2, seed=23)},
        {"name": "Dry", "values": {"base_color": [0.2, 0.18, 0.09]}, "opacity": 0.6, "mask": _g("grunge", amount=0.3, scale=0.8, softness=0.35, seed=25)},
        {"name": "Soil", "values": {"base_color": [0.08, 0.06, 0.04], "height": -0.3}, "opacity": 0.8, "mask": _g("spots", amount=0.12, scale=5.0, softness=0.15, seed=27)},
        {"name": "Flowers", "values": {"base_color": [0.5, 0.45, 0.3]}, "opacity": 0.6, "mask": _g("spots", amount=0.02, scale=40.0, softness=0.05, seed=29)},
    ])


def world_dirt():
    return _sheet("dirt", [4, 4], 2048, "Concrete", {"base_color": [0.14, 0.1, 0.07], "roughness": 0.9}, [
        {"name": "Tone", "values": {"base_color": [0.19, 0.14, 0.1]}, "opacity": 0.7, "mask": _g("grunge", amount=0.5, scale=0.7, softness=0.3, seed=31)},
        {"name": "Pebbles", "values": {"base_color": [0.3, 0.28, 0.25], "height": 0.6, "roughness": 0.7}, "mask": _g("spots", amount=0.12, scale=28.0, softness=0.08, seed=33)},
        {"name": "Gravel", "values": {"base_color": [0.22, 0.2, 0.18], "height": 0.3}, "opacity": 0.8, "mask": _g("spots", amount=0.25, scale=90.0, softness=0.05, seed=35)},
        {"name": "Ruts", "values": {"base_color": [0.08, 0.06, 0.045], "height": -0.6}, "opacity": 0.7, "mask": _g("scratches", amount=0.08, scale=0.5, softness=0.1, seed=37)},
        {"name": "Mud", "values": {"base_color": [0.06, 0.045, 0.035], "roughness": 0.2}, "opacity": 0.5, "channels": {"height": False}, "mask": _g("puddles", amount=0.18, scale=0.7, breakup=0.6, softness=0.2, seed=39)},
    ])


def world_sand():
    return _sheet("sand", [4, 4], 2048, "Concrete", {"base_color": [0.42, 0.37, 0.28], "roughness": 0.95}, [
        {"name": "Ripples", "values": {"base_color": [0.48, 0.43, 0.33], "height": 0.4}, "opacity": 0.8, "mask": _g("stripes", amount=0.45, scale=6.0, softness=0.45, seed=41)},
        {"name": "Tone", "values": {"base_color": [0.34, 0.3, 0.23]}, "opacity": 0.6, "mask": _g("grunge", amount=0.45, scale=0.6, softness=0.35, seed=43)},
        {"name": "Grains", "values": {"base_color": [0.55, 0.5, 0.42], "height": 0.1}, "opacity": 0.5, "mask": _g("spots", amount=0.3, scale=150.0, softness=0.05, seed=45)},
        {"name": "Shells and debris", "values": {"base_color": [0.6, 0.58, 0.55], "height": 0.4}, "mask": _g("spots", amount=0.015, scale=20.0, softness=0.05, seed=47)},
        {"name": "Wet sand", "values": {"base_color": [0.2, 0.17, 0.13], "roughness": 0.35}, "opacity": 0.5, "channels": {"height": False}, "mask": _g("grunge", amount=0.3, scale=0.4, softness=0.4, seed=49)},
    ])


# facade tile: 8 x 8 m, 4 bays (2 m) x 2 storeys (4 m). Sheet x = facade U, sheet z = height.
FACADE_STYLES = {
    #                wall colour           wall rough  glass colour         glass rough  frame colour
    "glass_blue":    ([0.16, 0.2, 0.24],   0.35,       [0.05, 0.09, 0.13],  0.05,        [0.25, 0.28, 0.3]),
    "glass_dark":    ([0.05, 0.05, 0.055], 0.3,        [0.02, 0.025, 0.03], 0.04,        [0.1, 0.1, 0.11]),
    "concrete_warm": ([0.36, 0.33, 0.29],  0.85,       [0.04, 0.045, 0.05], 0.08,        [0.15, 0.14, 0.13]),
    "panel_cyan":    ([0.22, 0.24, 0.25],  0.5,        [0.03, 0.06, 0.07],  0.05,        [0.06, 0.4, 0.45]),
}
FACADE_WINDOW = {"bay_m": 2.0, "storey_m": 4.0, "curtain": (1.86, 3.4), "punched": (1.5, 2.6), "sill_m": 0.55}


def world_facade(style):
    wall, wr, glass, gr, frame = FACADE_STYLES[style]
    curtain = style.startswith("glass")
    layers = [
        {"name": "Panels", "values": {"base_color": [c * 0.85 for c in wall]}, "opacity": 0.6,
         "mask": _g("tiles", variant="square", scale=1.0, aspect=1.0, mortar=0.02, amount=0.5, softness=0.01, seed=3)},
        {"name": "Panel joints", "values": {"base_color": [c * 0.4 for c in wall], "height": -0.5}, "mask": _g("panel_lines", amount=0.03, scale=1.0, softness=0.01, seed=5)},
        {"kind": "paint", "name": "Frames"},
        {"kind": "paint", "name": "Glass"},
    ]
    dec = []
    w, h = FACADE_WINDOW["curtain"] if curtain else FACADE_WINDOW["punched"]
    for bay in range(4):
        for storey in range(2):
            cx = -4.0 + 1.0 + bay * 2.0
            cz = -4.0 + storey * 4.0 + FACADE_WINDOW["sill_m"] + h / 2
            dec.append({"tool": "project_decal", "args": {"image": BAR, "layer": "Frames", "position": [cx, 0, cz], "normal": [0, 1, 0],
                                                          "size": [w + 0.12, h + 0.12], "tint": frame, "values": {"roughness": 0.35, "metallic": 0.8}, "height": 0.3}})
            dec.append({"tool": "project_decal", "args": {"image": BAR, "layer": "Glass", "position": [cx, 0, cz], "normal": [0, 1, 0],
                                                          "size": [w, h], "tint": glass, "values": {"roughness": gr, "metallic": 0.3}, "height": -0.2}})
            if not curtain:      # mullion splitting the pane
                dec.append({"tool": "project_decal", "args": {"image": BAR, "layer": "Frames", "position": [cx, 0, cz], "normal": [0, 1, 0],
                                                              "size": [0.06, h], "tint": frame, "values": {"roughness": 0.35, "metallic": 0.8}}})
    weather = [
        {"name": "Rain streaks", "material": "Grime", "opacity": 0.45, "mask": _g("streaks", amount=0.3, scale=2.0, softness=0.15, seed=7)},
        {"name": "Grime", "material": "Grime", "opacity": 0.35, "channels": {"height": False}, "mask": _g("grunge", amount=0.35, scale=0.9, softness=0.3, seed=9)},
    ]
    L = _sheet(f"facade_{style}", [8, 8], 2048, "Concrete", {"base_color": wall, "roughness": wr}, layers)
    tail = L[-3:]
    return L[:-3] + dec + [{"tool": "add_layer", "args": a} for a in weather] + tail


def rib_stencil():
    """Soft vertical bar (alpha = rib profile) for the corrugation decals."""
    from PIL import Image
    import math as _m
    p = ROOT / "assets" / "decals" / "world" / "rib.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    w, h = 64, 16
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    for x in range(w):
        a = int(255 * (0.5 - 0.5 * _m.cos(2 * _m.pi * (x + 0.5) / w)))
        for y in range(h):
            img.putpixel((x, y), (255, 255, 255, a))
    img.save(p)
    return p.relative_to(ROOT).as_posix()


def world_corrugated():
    """Corrugated sheet metal (warehouses, containers): neutral, tinted per instance at runtime.
    Ribs every 0.2 m (soft rib decals: a cosine height profile)."""
    rib = rib_stencil()
    ribs = [{"tool": "project_decal", "args": {"image": rib, "layer": "Ribs", "position": [-2.0 + 0.1 + k * 0.2, 0, 0], "normal": [0, 1, 0],
                                               "size": [0.2, 4.2], "tint": [0.6, 0.61, 0.62], "channels": ["base_color", "height"], "height": 1.0}} for k in range(20)]
    L = _corrugated_sheet()
    i = next(k for k, l in enumerate(L) if l["tool"] == "add_layer" and l["args"].get("name") == "Paint")
    return L[:i] + ribs + L[i:]


def _corrugated_sheet():
    return _sheet("corrugated", [4, 4], 2048, "Brushed steel", {"base_color": [0.55, 0.56, 0.57], "roughness": 0.45, "metallic": 0.7}, [
        {"kind": "paint", "name": "Ribs"},
        {"name": "Paint", "values": {"base_color": [0.7, 0.7, 0.7], "roughness": 0.6, "metallic": 0.0}, "opacity": 0.85, "channels": {"height": False},
         "mask": _g("grunge", amount=0.8, scale=1.0, softness=0.2, seed=53)},
        {"name": "Rust", "material": "Rust", "opacity": 0.8, "mask": _g("spots", amount=0.2, scale=4.0, softness=0.15, seed=55)},
        {"name": "Streaks", "material": "Grime", "opacity": 0.55, "mask": _g("streaks", amount=0.3, scale=2.5, softness=0.15, seed=57)},
        {"name": "Dents", "values": {"height": -0.4}, "opacity": 0.8, "channels": {"base_color": False, "roughness": False, "metallic": False},
         "mask": _g("spots", amount=0.06, scale=3.0, softness=0.3, seed=59)},
    ])


WORLD_JOBS = {"rock": world_rock, "grass": world_grass, "dirt": world_dirt, "sand": world_sand, "corrugated": world_corrugated,
              **{f"facade_{k}": (lambda k=k: world_facade(k)) for k in FACADE_STYLES}}


def world_sheets(names=None):
    """Write scenes/town/scripts/world/<name>.jsonl and run each through pigment-mcp."""
    d = OUT / "scripts" / "world"
    d.mkdir(parents=True, exist_ok=True)
    for name in names or WORLD_JOBS:
        L = WORLD_JOBS[name]()
        (d / f"{name}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in L), encoding="utf8")
        r = subprocess.run([str(MCP), "--script", str(d / f"{name}.jsonl")], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"world {name}: {r.stderr[-2000:]}")
        print("world", name, "ok")


if __name__ == "__main__":
    TMP.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    jobs = {
        "building_a": build_a,
        "building_b": build_b,
        "building_c": build_c,
        "street_segment": lambda: street("street_segment"),
        "crossroad": lambda: street("crossroad"),
        "street_lamp": lambda: small("street_lamp", "Gunmetal", lamp_extra),
        "power_pole": lambda: small("power_pole", "Concrete", pole_extra),
        "overhead_sign": lambda: small("overhead_sign", "Gunmetal", sign_extra, variants=True),
        "fence": fence,
        "world": world_sheets,          # every world sheet (or world:<name>,<name>)
    }
    for name in sys.argv[1:] or [j for j in jobs if j != "world"]:
        if name.startswith("world:"):
            world_sheets(name[6:].split(","))
            continue
        jobs[name]()
