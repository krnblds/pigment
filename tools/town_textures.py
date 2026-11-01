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

Signage is zoned: corporate (Hoshikawa / Meridian / Dreamlink / Noctis)
billboards high up and all over building_c (the corporate tower);
street-economy shops (memory pawn, implant repair, score reset, capsule
hotel, noodles, clinic) at ground level; authority plates by the doors;
resistance graffiti, UNPLUG posters and MISSING posters at street level.
Lit windows are a seeded random subset of the glass parts per variant.

    python tools/town_textures.py [asset ...]        (all assets by default)
    PIGMENT_MCP=path/to/pigment-mcp.exe python tools/town_textures.py building_a
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
TMP = Path.home() / "AppData" / "Local" / "Temp" / "pig"
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

# Neon colours per sign: a street reads as many shops, not one palette.
NEON = {
    "sign_memory_pawn": [1.0, 0.6, 0.15], "sign_implant_repair": [0.2, 0.9, 1.0], "sign_score_reset": [1.0, 0.2, 0.6],
    "sign_capsule_2h": [0.6, 0.35, 1.0], "sign_clinic": [0.3, 1.0, 0.4], "sign_dumplings": [1.0, 0.35, 0.12],
    "sign_jailbreak": [0.55, 1.0, 0.1], "sign_organ_credit": [1.0, 0.12, 0.15], "sign_offgrid": [0.2, 1.0, 0.8],
    "sign_charge": [1.0, 0.85, 0.2], "sign_karaoke": [1.0, 0.3, 0.85], "sign_dreams": [0.8, 0.5, 1.0],
    "sign_hoshikawa_security": [0.75, 0.9, 1.0], "sign_meridian_kiosk": [0.4, 0.9, 1.0],
    "blade_kioku": [1.0, 0.6, 0.15], "blade_gitai": [0.2, 0.9, 1.0], "blade_capsule": [0.6, 0.35, 1.0],
    "blade_soba": [1.0, 0.4, 0.1], "blade_yume": [1.0, 0.3, 0.75], "blade_pachinko": [0.4, 1.0, 0.3],
}


def wall(axis, at, a0, a1, b0, b1):
    """A thin box on a wall: `axis` (x or z) is the wall normal at coordinate
    `at`; (a0, a1) spans the other horizontal axis, (b0, b1) the height."""
    if axis == "x":
        return {"min": [at - 0.05, b0, a0], "max": [at + 0.05, b1, a1]}
    return {"min": [a0, b0, at - 0.05], "max": [a1, b1, at + 0.05]}


def look(image, where):
    """project_decal args for a story image at a placement (part / box)."""
    a = {"image": STORY + image + ".png"}
    a.update(where)
    if image in NEON:                                   # white glyphs: tint + glow
        a.update(tint=NEON[image], emissive_strength=6.0, material="Neon pink")
    elif image.startswith("billboard"):                 # backlit corporate ads
        a.update(emissive_strength=1.6, material="White plastic")
    elif image.startswith("logo"):
        a.update(image=DECALS + image + ".png", tint=[0.85, 0.92, 1.0], emissive_strength=2.0)
    else:                                               # paper, paint, enamel
        a.update(material="White plastic", opacity=0.95)
    return a


def story(slots, variants):
    """Record every (slot, image) decal once on a "Story" paint layer, tagged
    "story", enabled only if the first variant uses it. A slot can have
    several placements (both faces of a blade sign): they share a name.
    Returns the script lines and the export_variants definitions."""
    used = {}
    for v in variants:
        for slot, img in v["on"].items():
            if img:
                used.setdefault((slot, img), True)
    first = {(s, i) for s, i in variants[0]["on"].items() if i}
    L = [{"tool": "add_layer", "args": {"kind": "paint", "name": "Story decals"}}]
    for (slot, img) in used:
        for where in slots[slot]:
            a = look(img, where)
            a.update(layer="Story decals", name=f"{slot}/{img}", variant="story", enabled=(slot, img) in first)
            L.append({"tool": "project_decal", "args": a})
    defs = []
    for v in variants:
        enable = [f"{s}/{i}" for s, i in v["on"].items() if i]
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
    scale = [line for line in out.splitlines() if "emissive_scale" in line]
    print(asset, "ok", scale[-1].strip() if scale else "")


PREVIEW_VIEW = {
    "building_a": {"yaw": 28, "pitch": 6},
    "building_b": {"yaw": 22, "pitch": 6},
    "building_c": {"yaw": 30, "pitch": 6},
    "overhead_sign": {"yaw": 90, "pitch": 4, "zoom": 1.2},
}

# ------------------------------------------------------------------ building A: narrow 6-storey walk-up

# front +z (wall at z=5), sides x=+-4, back z=-5; ground floor y 0..4.2
A_SLOTS = {
    "blade": [{"part": 154, "fit": "contain", "facing": "+x"}, {"part": 154, "fit": "contain", "facing": "-x"}],
    "shop": [{"box": wall("z", 5.0, -3.5, 1.3, 3.05, 4.15), "fit": "contain"}],
    "high": [{"box": wall("x", 4.0, -4.6, 4.6, 13.0, 17.6), "fit": "contain", "facing": "+x"}],
    "back": [{"box": wall("z", -5.0, -3.0, 3.4, 9.0, 12.2), "fit": "contain", "facing": "-z"}],
    "tag_e": [{"box": wall("x", 4.0, -4.6, 2.6, 0.5, 3.6), "fit": "contain", "facing": "+x"}],
    "plate": [{"box": wall("x", 4.0, 3.1, 4.7, 1.5, 2.3), "fit": "contain", "facing": "+x"}],
    "post_w1": [{"box": wall("x", -4.0, 3.6, 4.6, 0.9, 2.3), "fit": "contain", "facing": "-x"}],
    "post_w2": [{"box": wall("x", -4.0, 2.4, 3.4, 0.9, 2.3), "fit": "contain", "facing": "-x"}],
    "tag_w": [{"box": wall("x", -4.0, -4.6, 2.0, 0.5, 3.6), "fit": "contain", "facing": "-x"}],
}
A_VARIANTS = [
    {"name": "memory_pawn", "seed": 11, "on": {"blade": "blade_kioku", "shop": "sign_memory_pawn", "high": "billboard_noctis",
                                               "tag_e": "graffiti_who_owns", "plate": "plate_observed", "post_w1": "poster_missing_aiko", "post_w2": "poster_missing_ren"}},
    {"name": "implants", "seed": 23, "on": {"blade": "blade_gitai", "shop": "sign_implant_repair", "high": "billboard_score",
                                            "tag_w": "graffiti_not_data", "plate": "plate_loitering", "post_w1": "poster_unplug"}},
    {"name": "capsules", "seed": 37, "on": {"blade": "blade_capsule", "shop": "sign_capsule_2h", "high": "billboard_dreamlink", "back": "billboard_jobs",
                                            "tag_e": "graffiti_unplug", "plate": "plate_curfew", "post_w1": "poster_missing_mika"}},
    {"name": "soba", "seed": 41, "on": {"blade": "blade_soba", "shop": "sign_dumplings", "high": "billboard_meridian",
                                        "tag_w": "graffiti_lying", "plate": "plate_observed", "post_w2": "poster_missing_ren"}},
    {"name": "dream_den", "seed": 53, "on": {"blade": "blade_yume", "shop": "sign_dreams", "high": "billboard_jobs", "back": "billboard_dreamlink",
                                             "tag_e": "stencil_eye_crossed", "plate": "plate_curfew", "post_w1": "poster_unplug", "post_w2": "poster_missing_aiko"}},
    {"name": "evicted", "seed": 67, "lights": "few", "on": {"shop": "plate_property", "high": "billboard_defaced",
                                                           "tag_e": "graffiti_unplug", "tag_w": "stencil_eye_crossed", "post_w1": "poster_missing_mika", "post_w2": "poster_unplug"}},
    {"name": "fixers", "seed": 79, "on": {"blade": "blade_pachinko", "shop": "sign_score_reset", "high": "billboard_meridian", "back": "billboard_score",
                                          "tag_w": "graffiti_who_owns", "plate": "plate_loitering", "post_w1": "poster_missing_ren"}},
]


def build_a():
    shell_extra = lambda shell: [fill("Slab joints", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.012, "scale": 0.6})]
    L, _ = building("building_a", "Concrete", shell_extra)
    S, defs = story(A_SLOTS, A_VARIANTS)
    finish(L + S, "building_a", defs)

# ------------------------------------------------------------------ building B: wide 3-storey with 4 shop bays + roof billboard

# front +z (upper wall z=6, bays recessed to z=4.1), sides x=+-8, back z=-6; ground floor y 0..4.5
B_SLOTS = {
    "bay1": [{"part": 5, "fit": "contain", "margin": 0.08}],
    "bay2": [{"part": 18, "fit": "contain", "margin": 0.08}],
    "bay3": [{"box": wall("z", 6.0, 0.4, 3.5, 3.7, 4.4), "fit": "contain"}],
    "bay4": [{"box": wall("z", 6.0, 4.3, 7.4, 3.7, 4.4), "fit": "contain"}],
    "roof": [{"part": 183, "fit": "fill", "margin": 0.0}],
    "tag_e": [{"box": wall("x", 8.0, -5.6, 2.4, 0.5, 4.1), "fit": "contain", "facing": "+x"}],
    "plate": [{"box": wall("x", 8.0, 3.2, 5.4, 1.5, 2.5), "fit": "contain", "facing": "+x"}],
    "post_w1": [{"box": wall("x", -8.0, 4.4, 5.5, 0.9, 2.4), "fit": "contain", "facing": "-x"}],
    "post_w2": [{"box": wall("x", -8.0, 3.1, 4.2, 0.9, 2.4), "fit": "contain", "facing": "-x"}],
    "tag_w": [{"box": wall("x", -8.0, -5.6, 2.4, 0.5, 4.1), "fit": "contain", "facing": "-x"}],
    "back": [{"box": wall("z", -6.0, -7.0, 7.0, 0.5, 4.0), "fit": "contain", "facing": "-z"}],
}
B_VARIANTS = [
    {"name": "noodle_row", "seed": 12, "on": {"bay1": "sign_dumplings", "bay2": "sign_karaoke", "bay3": "sign_charge", "bay4": "sign_offgrid",
                                              "roof": "billboard_meridian", "tag_e": "graffiti_unplug", "post_w1": "poster_missing_aiko", "plate": "plate_curfew"}},
    {"name": "body_shop", "seed": 24, "on": {"bay1": "sign_implant_repair", "bay2": "sign_organ_credit", "bay3": "sign_clinic", "bay4": "sign_jailbreak",
                                             "roof": "billboard_noctis", "tag_w": "graffiti_lying", "post_w1": "poster_unplug", "plate": "plate_loitering"}},
    {"name": "dream_strip", "seed": 36, "on": {"bay1": "sign_dreams", "bay2": "sign_capsule_2h", "bay3": "sign_karaoke", "bay4": "sign_memory_pawn",
                                               "roof": "billboard_dreamlink", "tag_e": "graffiti_who_owns", "post_w1": "poster_missing_mika", "post_w2": "poster_missing_ren", "plate": "plate_observed"}},
    {"name": "score_fixers", "seed": 48, "on": {"bay1": "sign_score_reset", "bay2": "sign_jailbreak", "bay3": "sign_dumplings", "bay4": "sign_charge",
                                                "roof": "billboard_score", "tag_w": "graffiti_not_data", "back": "graffiti_unplug", "post_w2": "poster_missing_ren", "plate": "plate_loitering"}},
    {"name": "pawn_row", "seed": 60, "on": {"bay1": "sign_memory_pawn", "bay2": "sign_offgrid", "bay3": "sign_implant_repair", "bay4": "sign_dreams",
                                            "roof": "billboard_jobs", "tag_e": "stencil_eye_crossed", "post_w1": "poster_unplug", "plate": "plate_curfew"}},
    {"name": "seized", "seed": 72, "lights": "few", "on": {"bay1": "sign_clinic", "bay4": "sign_organ_credit", "bay3": "plate_property",
                                                          "roof": "billboard_defaced", "tag_e": "graffiti_unplug", "tag_w": "graffiti_who_owns", "back": "graffiti_lying",
                                                          "post_w1": "poster_missing_aiko", "post_w2": "poster_missing_mika", "plate": "plate_property"}},
    {"name": "night_market", "seed": 84, "on": {"bay1": "sign_organ_credit", "bay2": "sign_score_reset", "bay3": "sign_capsule_2h", "bay4": "sign_clinic",
                                                "roof": "billboard_meridian", "tag_w": "stencil_eye_crossed", "post_w1": "poster_missing_ren", "plate": "plate_observed"}},
]


def build_b():
    def shell_extra(shell):
        wear = {"generator": "edge_wear", "amount": 0.5, "scale": 18.0, "breakup": 0.8, "softness": 0.05}
        return [fill("Teal paint", "Teal paint", shell),
                fill("Panel seams", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.01, "scale": 0.8}),
                fill("Chipped paint", "Steel", shell, wear, values={"height": -0.3})]
    L, _ = building("building_b", "Concrete", shell_extra)
    S, defs = story(B_SLOTS, B_VARIANTS)
    finish(L + S, "building_b", defs)

# ------------------------------------------------------------------ building C: the Hoshikawa / Meridian tower

# front +z (wall z=7), sides x=+-7, back z=-7; crown (y 30.6..35.8) faces at +-5
C_SLOTS = {
    "lobby": [{"part": 0, "fit": "contain", "margin": 0.15}],
    "band": [{"box": wall("z", 7.0, -3.4, 3.4, 4.3, 4.95), "fit": "contain"}],
    "crown_n": [{"box": wall("z", 5.0, -4.7, 4.7, 31.0, 35.4), "fit": "fill", "margin": 0.02}],
    "crown_e": [{"box": wall("x", 5.0, -4.7, 4.7, 31.0, 35.4), "fit": "fill", "margin": 0.02, "facing": "+x"}],
    "crown_w": [{"box": wall("x", -5.0, -4.7, 4.7, 31.0, 35.4), "fit": "fill", "margin": 0.02, "facing": "-x"}],
    "crown_s": [{"box": wall("z", -5.0, -4.7, 4.7, 31.0, 35.4), "fit": "fill", "margin": 0.02, "facing": "-z"}],
    "plate": [{"box": wall("z", 7.0, 3.6, 5.6, 1.6, 2.6), "fit": "contain"}],
    "tag_e": [{"box": wall("x", 7.0, -6.0, 3.0, 0.5, 4.2), "fit": "contain", "facing": "+x"}],
    "tag_w": [{"box": wall("x", -7.0, -6.0, 3.0, 0.5, 4.2), "fit": "contain", "facing": "-x"}],
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
                                             "plate": "plate_curfew", "tag_e": "graffiti_unplug", "tag_w": "graffiti_not_data"}},
]


def build_c():
    def shell_extra(shell):
        return [fill("Steel cladding", None, shell, values={"base_color": [0.2, 0.21, 0.23], "roughness": 0.5, "metallic": 0.7}),
                fill("Cladding seams", "Panel seam", shell, {"generator": "panel_lines", "amount": 0.008, "scale": 0.5}),
                fill("Scratches", "Brushed steel", shell, {"generator": "scratches", "amount": 0.08, "scale": 3.0}, opacity=0.35)]
    L, _ = building("building_c", "Concrete", shell_extra)
    S, defs = story(C_SLOTS, C_VARIANTS)
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
    ("kiosk", "sign_meridian_kiosk", "sign_charge"),     # Meridian's terminal next to a charging stall
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
    slots = {"face_w": [{"part": faces[0]["id"], "fit": "contain", "margin": 0.08, "facing": "-x"}],
             "face_e": [{"part": faces[-1]["id"], "fit": "contain", "margin": 0.08, "facing": "+x"}]}
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
