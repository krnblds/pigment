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
    bands = (("Lit windows (warm)", 0.0, 0.30, [1.0, 0.72, 0.42], 2.4),
             ("Lit windows (cyan)", 0.30, 0.37, [0.35, 0.85, 1.0], 2.2),
             ("Lit windows (pink)", 0.37, 0.40, [1.0, 0.3, 0.7], 2.2),
             # the cold blue of a Meridian feed playing in an empty room
             ("Meridian screens", 0.40, 0.45, [0.3, 0.5, 1.0], 1.8))
    for name, a, b, col, k in bands:
        # lit windows stay solid glowing panes (opacity 1 over the glass below)
        L.append(fill(name, None, glass, values={"base_color": col, "roughness": 0.1, "metallic": 0.0, "emissive": col, "emissive_strength": k, "opacity": 1.0, "transmission": 0.0},
                      channels={"height": False}, part_subset={"from": a, "to": b, "salt": 1}, variant="lights"))
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
    else:
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
    }
    for name in sys.argv[1:] or jobs:
        jobs[name]()
