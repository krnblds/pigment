"""Texture the street props in Pigment (pigment-mcp --script), and regenerate everything.

For each prop: reads assets/props/src/<name>.json (pieces with their material group and
glTF bbox, written by build_props.py), asks Pigment for the mesh's parts, maps every part
to its piece / group, and writes scenes/props/scripts/<name>.jsonl:

    group fills (part masks)  ->  edge wear, scratches, AO grime, ground dirt, rain streaks,
    leaks, rust, wet sheen    ->  emissive screens / lenses / LEDs / neon, glass (opacity /
    transmission), perforated grilles (cut-outs)  ->  "Story decals" paint layer (street names,
    ads, MERIDIAN stickers, UNPLUG tags, menus...)  ->  export_textures + export_variants
    (colour and ad swaps)  ->  save_project + a preview render

Outputs (textures are git-ignored, regenerate them with this script):
    scenes/props/scripts/<name>.jsonl
    scenes/props/projects/<name>.pigment
    scenes/props/textures/<name>/            authored look  (+ <name>__<variant>/ per variant)
    scenes/props/textures/variants.json      variants per prop (read by export_props.py)
    %TEMP%/pig_props/<name>.png              Pigment preview render

    python tools/props/props_textures.py [names...] [--no-run] [--jobs 2]
    PIGMENT_MCP=path/to/pigment-mcp.exe python tools/props/props_textures.py

Full regenerate (models -> textures -> glbs -> index):
    blender -b --factory-startup --python tools/props/build_props.py
    python tools/props/make_prop_decals.py
    python tools/props/props_textures.py
    blender -b --factory-startup --python tools/props/export_props.py
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import catalog  # noqa: E402

MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))
SRC = "assets/props/src"
SCRIPTS = ROOT / "scenes" / "props" / "scripts"
PROJECTS = "scenes/props/projects"
TEXTURES = "scenes/props/textures"
DEC = "assets/decals/props/"
STORY = "assets/decals/story/"
TMP = Path(os.environ.get("TEMP", "/tmp")) / "pig_props"
NO_HEIGHT = {"height": False}
ROUGH_ONLY = {"base_color": False, "metallic": False, "height": False}
CUT_ONLY = {"base_color": False, "roughness": False, "metallic": False, "height": False, "normal": False}


# ------------------------------------------------------------------ running pigment-mcp

def run(lines, label, keep=None):
    TMP.mkdir(parents=True, exist_ok=True)
    script = Path(keep) if keep else TMP / f"{label}.jsonl"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf8")
    r = subprocess.run([str(MCP), "--script", str(script)], cwd=ROOT, capture_output=True, text=True, encoding="utf8")
    if r.returncode != 0:
        raise SystemExit(f"{label}: {r.stdout[-2500:]}\n{r.stderr[-3000:]}")
    return r.stdout


def pigment_parts(mesh, label):
    out = run([{"tool": "new_project", "args": {"mesh": mesh, "resolution": 512}}, {"tool": "list_parts", "args": {}}], f"parts_{label}")
    s = out[out.index("[list_parts] ") + 13:]
    return json.loads(s[:s.index("\n[")] if "\n[" in s else s)


def match_parts(pparts, records):
    """Pigment part id -> record: exact bbox match first, then the smallest record box that
    holds the part, then the nearest centre."""
    out = {}
    for q in pparts:
        best = None
        for r in records:
            dc = sum(abs(q["center"][i] - r["center"][i]) for i in range(3))
            ds = sum(abs(q["size"][i] - r["size"][i]) for i in range(3))
            if dc + ds < 0.006 and (best is None or dc + ds < best[0]):
                best = (dc + ds, r)
        if best is None:
            for r in records:
                lo = [r["center"][i] - r["size"][i] / 2 - 0.004 for i in range(3)]
                hi = [r["center"][i] + r["size"][i] / 2 + 0.004 for i in range(3)]
                qlo = [q["center"][i] - q["size"][i] / 2 for i in range(3)]
                qhi = [q["center"][i] + q["size"][i] / 2 for i in range(3)]
                if all(lo[i] <= qlo[i] and qhi[i] <= hi[i] for i in range(3)):
                    vol = r["size"][0] * r["size"][1] * r["size"][2] + 1e-9
                    if best is None or vol < best[0]:
                        best = (vol, r)
        if best is None:
            best = (0, min(records, key=lambda r: sum((q["center"][i] - r["center"][i]) ** 2 for i in range(3))))
        out[q["id"]] = best[1]
    return out


# ------------------------------------------------------------------ materials per group

def V(c, r=0.5, m=0.0, **kw):
    d = {"base_color": list(c), "roughness": r, "metallic": m}
    d.update(kw)
    return d


def glow(c, s, base=None, r=0.3):
    return V(base or [x * 0.25 for x in c], r, 0.0, emissive=list(c), emissive_strength=s)


GROUP = {
    "dark_metal": ("Gunmetal", None),
    "galv": (None, V([0.56, 0.58, 0.59], 0.48, 0.95)),
    "steel": ("Brushed steel", None),
    "steel_rust": (None, V([0.3, 0.28, 0.26], 0.6, 0.85)),
    "iron": ("Dark iron", None),
    "rebar": ("Rust", None),
    "brass": (None, V([0.78, 0.6, 0.32], 0.35, 1.0)),
    "copper": ("Copper", None),
    "white_plastic": (None, V([0.82, 0.83, 0.82], 0.38)),
    "black_plastic": (None, V([0.025, 0.025, 0.028], 0.4)),
    "dark_plastic": (None, V([0.035, 0.036, 0.04], 0.55)),
    "red_plastic": (None, V([0.62, 0.06, 0.05], 0.4)),
    "rubber": ("Black rubber", None),
    "foam": (None, V([0.03, 0.03, 0.03], 0.92)),
    "leather": (None, V([0.07, 0.045, 0.035], 0.5)),
    "concrete": ("Concrete", None),
    "wood": (None, V([0.42, 0.28, 0.16], 0.72)),
    "wood2": (None, V([0.58, 0.45, 0.3], 0.8)),
    "wood_dark": (None, V([0.2, 0.11, 0.06], 0.45)),
    "staves": (None, V([0.36, 0.31, 0.26], 0.85)),
    "roof_tar": (None, V([0.05, 0.05, 0.05], 0.75)),
    "cardboard": (None, V([0.56, 0.41, 0.25], 0.88)),
    "tape": (None, V([0.72, 0.56, 0.32], 0.3)),
    "stencil": (None, V([0.58, 0.45, 0.3], 0.8)),
    "bag": (None, V([0.025, 0.025, 0.03], 0.22)),
    "bag_blue": (None, V([0.05, 0.14, 0.38], 0.28)),
    "bag_white": (None, V([0.7, 0.71, 0.68], 0.32, 0.0, opacity=0.92)),
    "hole": (None, V([0.004, 0.004, 0.004], 0.95)),
    "noren": (None, V([0.04, 0.06, 0.2], 0.92)),
    "canvas": (None, V([0.72, 0.1, 0.08], 0.85)),
    "bamboo": (None, V([0.74, 0.62, 0.42], 0.7)),
    "meat": (None, V([0.42, 0.17, 0.06], 0.35)),
    "cable": (None, V([0.02, 0.02, 0.022], 0.5)),
    "cable2": (None, V([0.8, 0.6, 0.05], 0.45)),
    "fins": (None, V([0.75, 0.76, 0.77], 0.4, 1.0)),
    "dish": (None, V([0.84, 0.84, 0.82], 0.5)),
    "soil": (None, V([0.11, 0.075, 0.05], 0.95)),
    "leaves": (None, V([0.1, 0.27, 0.09], 0.7)),
    "bark": (None, V([0.19, 0.13, 0.09], 0.9)),
    "palm_bark": (None, V([0.4, 0.33, 0.24], 0.85)),
    "palm_crown": (None, V([0.28, 0.24, 0.12], 0.8)),
    "frond": (None, V([0.13, 0.34, 0.1], 0.6)),
    "coconut": (None, V([0.33, 0.23, 0.1], 0.6)),
    "solar": (None, V([0.03, 0.05, 0.12], 0.12, 0.3)),
    "backplate": (None, V([0.02, 0.02, 0.022], 0.7)),
    "reflector": (None, V([0.88, 0.88, 0.85], 0.25)),
    "sign": (None, V([0.85, 0.85, 0.83], 0.45)),
    "sign2": (None, V([0.85, 0.85, 0.83], 0.45)),
    "ad2": (None, V([0.85, 0.85, 0.83], 0.35)),
    "sign_lit": (None, V([0.02, 0.02, 0.025], 0.3)),
    "glass": (None, V([0.6, 0.7, 0.74], 0.04, 0.0, opacity=0.28, transmission=1.0)),
    "smoke_glass": (None, V([0.08, 0.08, 0.09], 0.05, 0.0, opacity=0.75, transmission=0.6)),
    "grille": (None, V([0.12, 0.12, 0.13], 0.5, 0.7)),
    "grate": (None, V([0.1, 0.1, 0.1], 0.6, 0.8)),
    "wire": (None, V([0.15, 0.15, 0.16], 0.4, 0.9)),
    # emissive
    "screen": (None, glow([0.25, 0.55, 1.0], 0.6, base=[0.01, 0.015, 0.03], r=0.08)),
    "ad": (None, glow([1.0, 1.0, 1.0], 0.6, base=[0.9, 0.9, 0.9], r=0.2)),
    "led": (None, glow([0.3, 0.9, 1.0], 5.0)),
    "cam_eye": (None, glow([1.0, 0.05, 0.05], 3.0, base=[0.02, 0.0, 0.0], r=0.05)),
    "lens_red": (None, glow([1.0, 0.08, 0.04], 6.0, base=[0.35, 0.02, 0.02], r=0.08)),
    "lens_amber": (None, glow([1.0, 0.55, 0.05], 6.0, base=[0.4, 0.2, 0.02], r=0.08)),
    "lens_green": (None, glow([0.1, 1.0, 0.65], 6.0, base=[0.02, 0.3, 0.2], r=0.08)),
    "lens_stop": (None, V([0.03, 0.01, 0.01], 0.1)),
    "lens_walk": (None, V([0.01, 0.03, 0.02], 0.1)),
    "beacon_red": (None, glow([1.0, 0.05, 0.03], 8.0, base=[0.5, 0.02, 0.02], r=0.1)),
    "bulb": (None, glow([1.0, 0.82, 0.55], 6.0, base=[1.0, 0.9, 0.7], r=0.1)),
    "neon": (None, glow([1.0, 0.15, 0.6], 8.0, r=0.2)),
    "lantern": (None, glow([1.0, 0.3, 0.1], 2.2, base=[0.75, 0.07, 0.04], r=0.8)),
    "coal": (None, glow([1.0, 0.32, 0.05], 5.0, base=[0.05, 0.03, 0.02], r=0.9)),
    "holo": (None, V([0.15, 0.3, 0.6], 0.05, 0.0, opacity=0.18, emissive=[0.35, 0.6, 1.0], emissive_strength=1.2)),
    "water": (None, V([0.02, 0.022, 0.025], 0.02, 0.0)),
}
EMISSIVE = {"screen", "ad", "led", "cam_eye", "lens_red", "lens_amber", "lens_green", "beacon_red", "bulb", "neon", "lantern", "coal", "holo",
            "lens_stop", "lens_walk", "sign_lit"}
SEE_THROUGH = {"glass", "smoke_glass", "holo", "water"}
PAINTED = {"paint", "paint2", "plastic", "dish", "hazard"}
METAL_BARE = {"galv", "steel", "dark_metal", "iron", "steel_rust", "rebar", "brass", "copper", "fins", "grille", "grate", "wire"}
SOFT = {"leaves", "frond", "soil", "bag", "bag_blue", "bag_white", "noren", "canvas", "meat", "coconut", "palm_crown", "water"}

PAINTS = {
    "signal_yellow": V([0.78, 0.6, 0.06], 0.45),
    "signal_grey": V([0.33, 0.35, 0.36], 0.5, 0.3),
    "teal": V([0.06, 0.3, 0.32], 0.45),
    "hoshikawa_red": V([0.62, 0.06, 0.06], 0.42),
    "white": V([0.82, 0.82, 0.8], 0.4),
    "black": V([0.035, 0.035, 0.04], 0.55),
    "orange": V([0.9, 0.32, 0.04], 0.45),
    "hydrant_red": V([0.58, 0.05, 0.04], 0.4),
    "hydrant_yellow": V([0.85, 0.62, 0.05], 0.45),
    "green": V([0.1, 0.3, 0.16], 0.5),
    "navy": V([0.05, 0.08, 0.18], 0.45),
    "graphite": V([0.08, 0.085, 0.09], 0.35, 0.4),
    "pearl": V([0.86, 0.87, 0.88], 0.25, 0.1),
    "pink": V([0.85, 0.15, 0.45], 0.4),
    "violet": V([0.3, 0.1, 0.5], 0.4),
    "cream": V([0.86, 0.8, 0.65], 0.5),
    "hazard_yellow": V([0.93, 0.72, 0.05], 0.45),
    # port kit: container line colours (= the world's yard variants) and crane paints
    "c_rust": V([0.36, 0.085, 0.045], 0.55),
    "c_blue": V([0.04, 0.12, 0.33], 0.5),
    "c_white": V([0.74, 0.74, 0.71], 0.5),
    "c_green": V([0.07, 0.24, 0.12], 0.55),
    "c_orange": V([0.72, 0.25, 0.04], 0.5),
    "c_grey": V([0.3, 0.31, 0.32], 0.5),
    "c_teal": V([0.04, 0.27, 0.29], 0.5),
    "crane_red": V([0.6, 0.09, 0.05], 0.45),
    "crane_blue": V([0.06, 0.2, 0.5], 0.45),
    "crane_white": V([0.8, 0.8, 0.77], 0.45),
}


# ------------------------------------------------------------------ the texturer

class T:
    def __init__(self, name):
        self.name = name
        self.info = catalog.PROPS[name]
        self.src = json.load(open(ROOT / SRC / f"{name}.json"))
        self.mesh = f"{SRC}/{name}.glb"
        pp = pigment_parts(self.mesh, name)
        self.match = match_parts(pp, self.src["pieces"])
        self.groups = {}
        self.byname = {}
        for pid, r in self.match.items():
            self.groups.setdefault(r["group"], []).append(pid)
            self.byname.setdefault(r["piece"], []).append(pid)
        self.L = []
        self.variants = []
        self.default_variant = None
        h = self.src["size_m"][1]
        self.height = max(h, 0.05)
        self.ground = min(1.0, 0.45 / self.height)

    # selections
    def g(self, *groups):
        return sorted({p for gname in groups for p in self.groups.get(gname, [])})

    def p(self, *names, prefix=False):
        out = set()
        for n in names:
            for k, v in self.byname.items():
                if (k.startswith(n) if prefix else k == n):
                    out.update(v)
        if not out:
            raise SystemExit(f"{self.name}: no piece {names}")
        return sorted(out)

    def rec(self, piece):
        return next(r for r in self.src["pieces"] if r["piece"] == piece)

    def all_but(self, skip):
        return sorted(p for gname, ids in self.groups.items() if gname not in skip for p in ids)

    # layers
    def add(self, tool, **args):
        self.L.append({"tool": tool, "args": args})

    def fill(self, name, parts, material=None, values=None, gen=None, **kw):
        if parts is not None and not parts:
            return
        a = {"name": name}
        if material:
            a["material"] = material
        if values:
            a["values"] = values
        m = {}
        if parts is not None:
            m["parts"] = parts
        if gen:
            m.update(gen)
        if m:
            a["mask"] = m
        a.update(kw)
        self.L.append({"tool": "add_layer", "args": a})

    def decal(self, image, **kw):
        a = {"image": image if "/" in image else DEC + image + ".png", "layer": "Story decals"}
        a.update(kw)
        self.L.append({"tool": "project_decal", "args": a})

    def on_part(self, image, piece, facing, **kw):
        """Fit an image on a piece's face.  Vertical faces use an anchored decal (always upright,
        exact metres); up-facing ones use Pigment's part mode."""
        fit = kw.pop("fit", "contain")
        margin = kw.pop("margin", 0.05)
        if facing in ("+y", "-y"):
            for pid in self.p(piece):
                self.decal(image, part=pid, facing=facing, fit=fit, margin=margin, **kw)
            return
        r = self.rec(piece)
        c, sz = r["center"], r["size"]
        ax = {"+x": 0, "-x": 0, "+z": 2, "-z": 2}[facing]
        sgn = 1 if facing[0] == "+" else -1
        n = [0, 0, 0]
        n[ax] = sgn
        pos = list(c)
        pos[ax] += sgn * sz[ax] / 2
        w = (sz[2] if ax == 0 else sz[0]) * (1 - 2 * margin)
        h = sz[1] * (1 - 2 * margin)
        if fit == "contain":
            from PIL import Image
            path = image if "/" in image else DEC + image + ".png"
            iw, ih = Image.open(ROOT / path).size
            asp = iw / ih
            w, h = (w, w / asp) if w / asp <= h else (h * asp, h)
        kw.setdefault("depth", 0.01)
        self.at(image, pos, n, [round(w, 4), round(h, 4)], **kw)

    def at(self, image, pos, normal, size, **kw):
        self.decal(image, position=[round(x, 4) for x in pos], normal=list(normal), size=size, **kw)

    # ------------------------------------------------------------------ stacks
    def base(self, paint="signal_grey", paint2="graphite", plastic="orange", led=None, neon=None, screen=None, extra=None):
        """One fill per material group (part masks)."""
        cols = {"paint": PAINTS[paint] if isinstance(paint, str) else paint,
                "paint2": PAINTS[paint2] if isinstance(paint2, str) else paint2,
                "plastic": PAINTS[plastic] if isinstance(plastic, str) else plastic,
                "hazard": PAINTS["hazard_yellow"]}
        over = dict(extra or {})
        if led:
            over["led"] = glow(led, 5.0)
        if neon:
            over["neon"] = glow(neon, 8.0, r=0.2)
        if screen:
            over["screen"] = glow(screen, 0.6, base=[0.01, 0.015, 0.03], r=0.08)
        order = [g for g in self.groups if g not in EMISSIVE and g not in SEE_THROUGH] + \
                [g for g in self.groups if g in SEE_THROUGH] + [g for g in self.groups if g in EMISSIVE]
        for gname in order:
            ids = self.g(gname)
            if gname in over:
                self.fill(gname, ids, values=over[gname], channels=NO_HEIGHT if gname not in SEE_THROUGH else None)
            elif gname in cols:
                self.fill(gname, ids, values=cols[gname])
            elif gname in GROUP:
                mat, vals = GROUP[gname]
                self.fill(gname, ids, material=mat, values=vals)
            else:
                raise SystemExit(f"{self.name}: no material for group {gname!r}")
        if self.groups.get("hazard"):
            self.fill("Hazard stripes", self.g("hazard"), values=V([0.02, 0.02, 0.02], 0.6),
                      gen={"generator": "stripes", "amount": 0.5, "scale": 6.0, "softness": 0.02})
        for gname in ("grille", "grate", "wire"):
            if self.groups.get(gname):
                holes = {"grille": 34.0, "grate": 9.0, "wire": 22.0}[gname]
                bar = {"grille": 0.35, "grate": 0.45, "wire": 0.2}[gname]
                self.fill(f"{gname} holes", self.g(gname), material="Cut-out", channels=CUT_ONLY)
                self.fill(f"{gname} bars", self.g(gname), values={"opacity": 1.0},
                          gen={"generator": "panel_lines", "amount": bar, "scale": holes, "softness": 0.02}, channels=CUT_ONLY)
        if self.groups.get("wood") or self.groups.get("wood2") or self.groups.get("staves"):
            self.fill("Wood grain", self.g("wood", "wood2", "staves", "stencil"), values=V([0.18, 0.11, 0.06], 0.85),
                      gen={"generator": "streaks", "amount": 0.45, "scale": 14.0, "softness": 0.3, "breakup": 0.8}, opacity=0.55, channels=NO_HEIGHT)
        if self.groups.get("galv"):
            self.fill("Galvanised spangle", self.g("galv"), values=V([0.42, 0.44, 0.45], 0.62, 0.9),
                      gen={"generator": "grunge", "amount": 0.45, "scale": 9.0, "softness": 0.35}, opacity=0.5, channels=NO_HEIGHT)
        if self.groups.get("leaves") or self.groups.get("frond"):
            self.fill("Leaf variation", self.g("leaves", "frond"), values=V([0.2, 0.38, 0.08], 0.65),
                      gen={"generator": "grunge", "amount": 0.45, "scale": 2.5, "softness": 0.35}, opacity=0.7, channels=NO_HEIGHT)
            self.fill("Leaf shadow", self.g("leaves", "frond"), values=V([0.03, 0.08, 0.03], 0.8),
                      gen={"generator": "dirt", "amount": 0.55, "softness": 0.3}, opacity=0.8, channels=NO_HEIGHT)

    def weather(self, wear=0.5, leaks=False, rust=0.3, wet=0.5, ground=True):
        """Edge wear, scratches, AO grime, ground dirt, rain streaks, leaks, rust and wet sheen."""
        painted = self.g(*PAINTED)
        hard = self.all_but(EMISSIVE | SEE_THROUGH | {"water"})
        solid = self.all_but(EMISSIVE | SEE_THROUGH | SOFT)
        if painted and wear > 0:
            self.fill("Edge wear", painted, material="Steel",
                      gen={"generator": "edge_wear", "amount": 0.15 + 0.3 * wear, "softness": 0.12, "breakup": 0.6, "scale": 6.0},
                      channels=NO_HEIGHT)
            self.fill("Scratches", painted, values=V([0.5, 0.5, 0.5], 0.35, 0.6),
                      gen={"generator": "scratches", "amount": 0.1 + 0.2 * wear, "scale": 4.0}, opacity=0.35, channels=NO_HEIGHT)
        metal = self.g(*(METAL_BARE & set(self.groups)))
        if metal and rust > 0:
            self.fill("Rust", metal, material="Rust",
                      gen={"generator": "edge_wear", "amount": 0.2 + 0.35 * rust, "softness": 0.2, "breakup": 0.8, "scale": 5.0,
                           "effects": [{"generator": "spots", "op": "multiply", "amount": 0.5 + 0.3 * rust, "scale": 5.0, "softness": 0.2}]},
                      opacity=0.85, channels=NO_HEIGHT)
        if hard:
            self.fill("Grime", hard, material="Grime", gen={"generator": "dirt", "amount": 0.35 + 0.3 * wear, "softness": 0.25, "breakup": 0.5},
                      opacity=0.75, channels=NO_HEIGHT)
        if ground and hard:
            self.fill("Ground dirt", hard, material="Grime",
                      gen={"generator": "gradient", "amount": min(0.9, self.ground * (0.6 + wear)), "softness": 0.12, "breakup": 0.6, "scale": 4.0,
                           "effects": [{"generator": "grunge", "op": "multiply", "amount": 0.75, "scale": 3.0, "softness": 0.3}]},
                      opacity=0.7, channels=NO_HEIGHT)
        if solid:
            self.fill("Rain streaks", solid, material="Grime", gen={"generator": "streaks", "amount": 0.15 + 0.25 * wear, "scale": 3.0, "softness": 0.2},
                      opacity=0.4, channels=NO_HEIGHT)
        if leaks and solid:
            self.fill("Leaks", solid, values=V([0.06, 0.05, 0.045], 0.3),
                      gen={"generator": "leaks", "amount": 0.45 + 0.2 * wear, "scale": 3.0, "breakup": 0.6, "drip_length": 0.8, "ao_influence": 0.3,
                           "softness": 0.15}, opacity=0.6, channels=NO_HEIGHT)
        if wet > 0 and hard:
            self.fill("Wet sheen", hard, values={"roughness": 0.08},
                      gen={"generator": "grunge", "amount": 0.25 + 0.3 * wet, "scale": 1.8, "softness": 0.3}, opacity=0.6, channels=ROUGH_ONLY)
        glass = self.g("glass", "smoke_glass")
        if glass:
            self.fill("Glass grime", glass, values=V([0.3, 0.28, 0.25], 0.45),
                      gen={"generator": "spots", "amount": 0.35 + 0.3 * wear, "scale": 9.0, "softness": 0.2,
                           "effects": [{"generator": "gradient", "op": "max", "amount": 0.25, "softness": 0.2}]}, opacity=0.5, channels=NO_HEIGHT)

    def decals_layer(self):
        self.add("add_layer", kind="paint", name="Story decals")

    def top_grime(self, amount=0.4):
        """A thin film of grime over the decals so they sit in the world."""
        ids = self.all_but(EMISSIVE | SEE_THROUGH)
        if ids:
            self.fill("Decal grime", ids, material="Grime", gen={"generator": "grunge", "amount": amount, "scale": 4.0, "softness": 0.3},
                      opacity=0.35, channels=NO_HEIGHT)

    def colour_variants(self, group, colours, default):
        """Extra fills over `group`, hidden except in their variant."""
        for c in colours:
            self.fill(f"{group} {c}", self.g(group), values=PAINTS[c], variant="colours", visible=False)
        self.default_variant = default

    def variant(self, name, seed=0, enable=(), disable=(), swaps=None):
        v = {"name": name, "seed": seed, "enable": list(enable), "disable": list(disable)}
        if swaps:
            v["swaps"] = swaps
        self.variants.append(v)

    def script(self):
        n = self.name
        res = self.info["res"]
        lines = [{"tool": "new_project", "args": {"mesh": self.mesh, "resolution": res, "material": "Gunmetal"}}]
        lines += self.L
        lines.append({"tool": "render", "args": {"yaw": 30, "pitch": 14, "width": 720, "height": 720, "exposure": -0.3, "lighting": "night", "bloom": True,
                                                  "path": str(TMP / f"{n}.png").replace("\\", "/")}})
        lines.append({"tool": "export_textures", "args": {"dir": f"{TEXTURES}/{n}", "preset": "separate", "name": n}})
        if self.variants:
            lines.append({"tool": "export_variants", "args": {"dir": TEXTURES, "name": n, "preset": "separate", "variants": self.variants}})
        lines.append({"tool": "save_project", "args": {"path": f"{PROJECTS}/{n}.pigment"}})
        return lines


# ------------------------------------------------------------------ recipes
# Facing in glTF space: the prop's front is +z, its back -z, its right (+X in Blender) +x, up +y.

R = {}


def recipe(fn):
    R[fn.__name__[2:]] = fn
    return fn


def lamps_lit(t):
    """Walk / stop glyphs on the pedestrian lenses (lit)."""
    for piece, img, tint in (("Ped_A_Walk", "ped_walk", [0.2, 1.0, 0.55]), ("Ped_A_Stop", "ped_stop", [1.0, 0.18, 0.08])):
        if piece in t.byname:
            r = t.rec(piece)
            facing = "+x" if r["size"][0] < r["size"][2] else "+z"
            t.on_part(img, piece, facing, tint=tint, emissive_strength=6.0, margin=0.1)


@recipe
def r_traffic_light_pole(t):
    t.base(paint="signal_yellow", paint2="graphite", led=[0.3, 0.9, 1.0])
    t.weather(wear=0.45, rust=0.35, wet=0.6)
    t.decals_layer()
    lamps_lit(t)
    t.on_part("push_button", "button_plate", "+z")
    t.at("meridian_sticker", [0.0, 1.45, 0.08], [0, 0, 1], 0.1, wear=0.2)
    t.at(STORY + "stencil_eye_crossed.png", [0.0, 0.75, -0.076], [0, 0, -1], 0.13, tint=[0.95, 0.95, 0.95], fade=0.3, name="unplug_eye", variant="tags")
    t.at(STORY + "poster_missing_ren.png", [0.0, 1.7, -0.078], [0, 0, -1], 0.16, wear=0.4, fade=0.3, name="missing", variant="tags")
    t.top_grime()
    t.colour_variants("paint", ["signal_grey", "graphite"], "yellow")
    t.variant("grey", 3, enable=["paint signal_grey"])
    t.variant("black", 5, enable=["paint graphite"], disable=["tags"])


@recipe
def r_traffic_light_mast(t):
    t.base(paint="signal_yellow", paint2="graphite")
    t.weather(wear=0.4, rust=0.35, wet=0.6)
    t.decals_layer()
    names = ["street_meridian_ave", "street_hoshikawa_dori", "street_kioku_zaka"]
    for i, n in enumerate(names):
        t.on_part(n, "name_blade", "+z", name=f"blade_{n}", variant="blade", enabled=(i == 0), emissive_strength=0.6, margin=0.04)
    t.on_part("push_button", "button_plate", "+z")
    t.at("meridian_sticker", [0.0, 1.5, 0.13], [0, 0, 1], 0.12, wear=0.2)
    t.top_grime()
    t.colour_variants("paint", ["signal_grey"], "meridian_ave")
    t.variant("hoshikawa_dori", 3, disable=["blade"], enable=["blade_street_hoshikawa_dori"])
    t.variant("kioku_zaka_grey", 5, disable=["blade"], enable=["blade_street_kioku_zaka", "paint signal_grey"])


@recipe
def r_ped_signal(t):
    t.base(paint="signal_yellow", paint2="graphite", screen=[1.0, 0.55, 0.1])
    t.weather(wear=0.45, rust=0.3, wet=0.6)
    t.decals_layer()
    lamps_lit(t)
    t.on_part("ped_count", "Ped_A_Count", "+z", tint=[1.0, 0.6, 0.2], emissive_strength=4.0, margin=0.05)
    t.on_part("push_button", "button_plate", "+z")
    t.at(STORY + "graffiti_unplug.png", [0.0, 0.9, -0.062], [0, 0, -1], 0.12, fade=0.3, wear_style="grunge")
    t.top_grime()


@recipe
def r_street_name_sign(t):
    t.base(paint="green", paint2="graphite")
    t.weather(wear=0.35, rust=0.3, wet=0.5)
    t.decals_layer()
    pairs = [("street_hoshikawa_dori", "street_kioku_zaka"), ("street_neon_yokocho", "street_shin_yume"), ("street_meridian_ave", "street_hoshikawa_dori")]
    for i, (a, b) in enumerate(pairs):
        en = i == 0
        for face in ("+z", "-z"):
            t.on_part(a, "blade_1", face, name=f"b1{face}_{i}", variant="names", enabled=en, margin=0.02)
        for face in ("+x", "-x"):
            t.on_part(b, "blade_2", face, name=f"b2{face}_{i}", variant="names", enabled=en, margin=0.02)
    t.on_part("route_plate", "route_plate", "+z", margin=0.02)
    t.at(STORY + "poster_unplug.png", [0.0, 1.5, -0.047], [0, 0, -1], 0.14, wear=0.45, fade=0.3)
    t.top_grime()
    t.variant("neon_yokocho", 3, disable=["names"], enable=[f"b1+z_1", "b1-z_1", "b2+x_1", "b2-x_1"])
    t.variant("meridian_ave", 5, disable=["names"], enable=[f"b1+z_2", "b1-z_2", "b2+x_2", "b2-x_2"])


@recipe
def r_bollard(t):
    t.base(paint="graphite", paint2="graphite", led=[0.1, 0.9, 1.0])
    for c in ("hazard_yellow", "pearl"):
        t.fill(f"paint {c}", t.g("paint"), values=PAINTS[c], variant="colours", visible=False)
    t.weather(wear=0.6, rust=0.35, wet=0.6)
    t.fill("Bumper scuffs", t.g("paint"), values=V([0.55, 0.55, 0.53], 0.45, 0.7),
           gen={"generator": "scratches", "amount": 0.45, "scale": 3.0,
                "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.55, "softness": 0.25}]}, opacity=0.7, channels=NO_HEIGHT)
    t.fill("Tyre rubber", t.g("paint", "paint2"), values=V([0.02, 0.02, 0.02], 0.8),
           gen={"generator": "spots", "amount": 0.18, "scale": 6.0, "softness": 0.4,
                "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.7, "softness": 0.2}]}, opacity=0.6, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("bollard_plate", "id_plate", "+z", margin=0.04)
    t.at(DEC + "meridian_sticker.png", [0.0, 0.52, 0.107], [0, 0, 1], 0.07, wear=0.3)
    t.at(STORY + "graffiti_unplug.png", [0.0, 0.4, -0.107], [0, 0, -1], 0.18, fade=0.3, wear_style="grunge", name="tag", variant="tags", enabled=False)
    t.top_grime(0.3)
    t.default_variant = "graphite"
    t.variant("yellow", 3, enable=["paint hazard_yellow"])
    t.variant("pearl", 5, enable=["paint pearl"])
    t.variant("tagged", 7, enable=["tags"])


@recipe
def r_guard_rail(t):
    t.base()
    t.weather(wear=0.5, rust=0.55, wet=0.6, ground=True)
    t.decals_layer()
    t.at(STORY + "graffiti_who_owns.png", [0.0, 0.62, 0.3], [0, 0, 1], 1.4, fade=0.35, wear_style="grunge", name="tag", variant="tags")
    t.top_grime()
    t.variant("clean", 7, disable=["tags"])


@recipe
def r_crash_barrier(t):
    t.base(plastic="hoshikawa_red")
    t.weather(wear=0.6, rust=0.0, wet=0.6)
    t.decals_layer()
    t.at("stencil_civil", [0.0, 0.45, 0.205], [0, 0.25, 1], 1.0, tint=[0.95, 0.95, 0.95], fade=0.3)
    t.top_grime(0.5)
    t.colour_variants("plastic", ["white", "orange"], "red")
    t.variant("white", 3, enable=["plastic white"])
    t.variant("orange", 5, enable=["plastic orange"])


@recipe
def r_jersey_barrier(t):
    t.base()
    t.weather(wear=0.7, rust=0.6, wet=0.6)
    t.fill("Concrete stains", t.g("concrete"), values=V([0.38, 0.37, 0.35], 0.9),
           gen={"generator": "grunge", "amount": 0.45, "scale": 2.0, "softness": 0.3}, opacity=0.6, channels=NO_HEIGHT)
    t.fill("Hazard band", t.g("concrete"), values=PAINTS["hazard_yellow"],
           gen={"generator": "stripes", "amount": 0.5, "scale": 4.0, "softness": 0.02,
                "effects": [{"generator": "gradient", "op": "multiply", "amount": 0.18, "softness": 0.01}]}, opacity=0.9, channels=NO_HEIGHT)
    t.decals_layer()
    t.at("stencil_checkpoint", [-0.6, 0.62, 0.11], [0, 0.18, 1], 1.1, tint=[0.95, 0.95, 0.92], fade=0.35, wear=0.15)
    t.at(STORY + "graffiti_unplug.png", [0.75, 0.5, 0.16], [0, 0.3, 1], 1.0, fade=0.25, wear_style="grunge", name="unplug", variant="tags")
    t.at(STORY + "graffiti_not_data.png", [0.0, 0.5, -0.16], [0, 0.3, -1], 1.6, fade=0.3, wear_style="grunge", name="not_data", variant="tags")
    t.top_grime(0.5)
    t.variant("clean", 3, disable=["tags"])


@recipe
def r_traffic_cone(t):
    t.base(plastic="orange")
    t.weather(wear=0.6, rust=0, wet=0.5)
    t.decals_layer()
    t.top_grime(0.5)


@recipe
def r_steam_vent(t):
    t.base(plastic="orange")
    t.weather(wear=0.6, rust=0.6, wet=0.8)
    t.fill("Soot", t.g("plastic"), values=V([0.05, 0.05, 0.05], 0.9),
           gen={"generator": "streaks", "amount": 0.4, "scale": 5.0, "softness": 0.2,
                "effects": [{"generator": "grunge", "op": "multiply", "amount": 0.7, "scale": 3.0}]}, opacity=0.6, channels=NO_HEIGHT)
    t.decals_layer()
    t.at("meridian_sticker", [0.0, 0.62, 0.208], [0, 0, 1], 0.16, wear=0.3, fade=0.2)
    t.top_grime(0.5)


@recipe
def r_bus_stop(t):
    t.base(paint="graphite", paint2="hoshikawa_red", led=[0.85, 0.92, 1.0], screen=[1.0, 0.6, 0.15])
    t.weather(wear=0.45, leaks=True, rust=0.3, wet=0.6)
    t.decals_layer()
    ads = ["noctis", "dreamlink", "meridian", "security", "defaced"]
    for i, a in enumerate(ads):
        for piece, face in (("ad_out", "+x"), ("ad_in", "-x")):
            t.on_part(f"ad_{a}", piece, face, name=f"{piece}_{a}", variant="ads", enabled=(i == 0), emissive_strength=2.5, margin=0.0, fit="fill")
    t.on_part("bus_timetable", "timetable", "+z", emissive_strength=3.0, margin=0.03)
    for face in ("+z", "-z"):
        t.on_part("bus_route_flag", "route_flag", "+x" if face == "+z" else "-x", margin=0.04)
    gy = 0.6
    # UNPLUG and MISSING posters pasted on the back glass (seen from the street side), torn
    t.at(STORY + "poster_missing_aiko.png", [-0.4, 1.45, -0.6], [0, 0, 1], 0.32, wear=0.35, fade=0.25, name="poster_aiko", variant="posters")
    t.at(STORY + "poster_unplug.png", [0.3, 1.3, -0.6], [0, 0, 1], 0.32, wear=0.4, fade=0.3, name="poster_unplug", variant="posters")
    t.at(STORY + "stencil_eye_crossed.png", [-1.25, 1.95, -0.582], [0, 0, 1], 0.22, tint=[0.95, 0.95, 0.95], fade=0.3, name="eye_tag", variant="posters")
    t.at(STORY + "graffiti_unplug.png", [0.0, 0.32, -0.66], [0, 0, 1], 1.4, fade=0.3, wear_style="grunge", name="tag_back", variant="posters")
    t.at("meridian_sticker", [-1.9, 1.4, 0.66], [0, 0, 1], 0.12, wear=0.2)
    t.top_grime(0.4)
    t.colour_variants("paint", ["teal", "pearl"], "noctis")
    t.variant("dreamlink", 3, disable=["ads"], enable=["ad_out_dreamlink", "ad_in_dreamlink"])
    t.variant("meridian", 5, disable=["ads", "posters"], enable=["ad_out_meridian", "ad_in_meridian", "paint pearl"])
    t.variant("security", 7, disable=["ads"], enable=["ad_out_security", "ad_in_security", "paint teal"])
    t.variant("defaced", 9, disable=["ads"], enable=["ad_out_defaced", "ad_in_noctis"])


@recipe
def r_bench(t):
    t.base(paint="graphite")
    t.weather(wear=0.55, rust=0.35, wet=0.6)
    t.decals_layer()
    t.on_part("bench_plaque", "plaque", "-z", margin=0.02)
    t.at(STORY + "graffiti_not_data.png", [0.45, 0.68, -0.33], [0, 0.25, -1], 0.7, fade=0.35, wear_style="grunge", name="tag", variant="tags")
    t.top_grime()
    t.colour_variants("paint", ["teal", "hoshikawa_red"], "graphite")
    t.variant("teal", 3, enable=["paint teal"], disable=["tags"])
    t.variant("red", 5, enable=["paint hoshikawa_red"])


@recipe
def r_fire_hydrant(t):
    t.base(paint="hydrant_red")
    t.weather(wear=0.7, rust=0.5, wet=0.6)
    t.decals_layer()
    t.top_grime(0.5)
    t.colour_variants("paint", ["hydrant_yellow", "teal"], "red")
    t.variant("yellow", 3, enable=["paint hydrant_yellow"])
    t.variant("teal", 5, enable=["paint teal"])


@recipe
def r_parking_meter(t):
    t.base(paint="navy", screen=[0.4, 1.0, 0.5], led=[0.3, 0.9, 1.0])
    t.weather(wear=0.5, rust=0.3, wet=0.6)
    t.decals_layer()
    t.on_part("parking_screen", "screen", "+z", emissive_strength=3.0, margin=0.02, fit="fill")
    t.on_part("meridian_sticker", "sticker_plate", "-z", margin=0.0)
    t.at(STORY + "stencil_eye_crossed.png", [0.0, 1.16, 0.106], [0, 0, 1], 0.08, tint=[0.95, 0.95, 0.95], fade=0.3, name="tag", variant="tags")
    t.top_grime()
    t.colour_variants("paint", ["graphite"], "navy")
    t.variant("graphite", 3, enable=["paint graphite"], disable=["tags"])


@recipe
def r_data_kiosk(t):
    t.base(paint="pearl", paint2="graphite", led=[0.25, 0.85, 1.0], screen=[0.3, 0.7, 1.0])
    t.weather(wear=0.25, leaks=True, rust=0.2, wet=0.5)
    t.decals_layer()
    screens = ["score", "flagged", "dreamlink", "hacked"]
    for i, s in enumerate(screens):
        t.on_part(f"kiosk_{s}", "screen", "+z", name=f"screen_{s}", variant="screens", enabled=(i == 0), emissive_strength=3.2, margin=0.0, fit="fill")
    t.on_part("ad_meridian", "ad_back", "-z", name="back_meridian", variant="backs", emissive_strength=2.0, margin=0.0, fit="fill")
    t.on_part("ad_dreamlink", "ad_back", "-z", name="back_dreamlink", variant="backs", enabled=False, emissive_strength=2.0, margin=0.0, fit="fill")
    t.at(STORY + "graffiti_unplug.png", [0.0, 0.35, 0.215], [0, 0, 1], 0.8, fade=0.3, wear_style="grunge", name="tag", variant="tags", enabled=False)
    t.at(STORY + "poster_missing_mika.png", [0.32, 0.85, 0.215], [0, 0, 1], 0.22, wear=0.4, fade=0.3, name="missing", variant="tags", enabled=False)
    t.top_grime(0.3)
    t.colour_variants("led", [], "score")
    t.fill("Alarm LEDs", t.g("led"), values=glow([1.0, 0.1, 0.1], 5.0), variant="alarm", visible=False, channels=NO_HEIGHT)
    t.variant("flagged", 3, disable=["screens"], enable=["screen_flagged", "alarm"])
    t.variant("dreamlink", 5, disable=["screens", "backs"], enable=["screen_dreamlink", "back_dreamlink"])
    t.variant("hacked", 7, disable=["screens"], enable=["screen_hacked", "tags"])


@recipe
def r_phone_kiosk(t):
    t.base(paint="teal", paint2="graphite", led=[0.85, 0.92, 1.0], screen=[0.3, 0.8, 1.0])
    t.weather(wear=0.6, leaks=True, rust=0.4, wet=0.6)
    t.decals_layer()
    t.on_part("phone_header", "header", "+z", emissive_strength=1.5, margin=0.02, fit="fill")
    t.on_part("phone_screen", "screen", "+z", emissive_strength=2.5, margin=0.0, fit="fill")
    t.on_part("ad_dreamlink", "ad_panel", "+z", name="ad_dreamlink", variant="ads", emissive_strength=1.2, margin=0.02)
    t.on_part("ad_security", "ad_panel", "+z", name="ad_security", variant="ads", enabled=False, emissive_strength=1.2, margin=0.02)
    t.at(STORY + "poster_missing_aiko.png", [-0.25, 1.1, -0.0], [0, 0, 1], 0.16, wear=0.4, fade=0.3)
    t.at(STORY + "graffiti_lying.png", [0.0, 1.95, -0.01], [0, 0, -1], 0.8, fade=0.3, wear_style="grunge")
    t.top_grime(0.5)
    t.colour_variants("paint", ["hoshikawa_red", "cream"], "teal")
    t.variant("red", 3, enable=["paint hoshikawa_red"], disable=["ads"])
    t.variant("cream", 5, enable=["paint cream"], disable=["ads"])
    t.variants[0]["enable"].append("ad_security")
    t.variants[1]["enable"].append("ad_dreamlink")


@recipe
def r_cctv_pole(t):
    t.base(paint="graphite", led=[1.0, 0.1, 0.1])
    t.weather(wear=0.45, rust=0.4, wet=0.6)
    t.decals_layer()
    t.on_part("meridian_plate", "meridian_plate", "+z", emissive_strength=0.8, margin=0.02)
    t.at(STORY + "poster_unplug.png", [0.0, 1.6, 0.093], [0, 0, 1], 0.2, wear=0.4, fade=0.3, name="poster", variant="tags")
    t.at(STORY + "stencil_eye_crossed.png", [0.0, 2.25, 0.276], [0, 0, 1], 0.2, tint=[1, 0.2, 0.25], fade=0.2, name="eye", variant="tags")
    t.top_grime()
    t.variant("clean", 3, disable=["tags"])


@recipe
def r_drone_mast(t):
    t.base(paint="graphite", paint2="pearl", led=[0.2, 0.8, 1.0])
    t.weather(wear=0.4, leaks=True, rust=0.4, wet=0.6)
    t.decals_layer()
    t.on_part("drone_plate", "cabinet_plate", "+z", margin=0.02)
    t.decal(DEC + "drone_pad.png", part=t.p("pad_center")[0], facing="+y", tint=[0.95, 0.95, 0.9], margin=0.05)
    t.at("meridian_sticker", [0.3, 0.6, 0.322], [0, 0, 1], 0.12)
    t.at(STORY + "graffiti_who_owns.png", [0.0, 0.5, -0.3], [0, 0, -1], 0.85, fade=0.3, wear_style="grunge", name="tag", variant="tags")
    t.top_grime(0.4)
    t.variant("clean", 3, disable=["tags"])


@recipe
def r_holo_pylon(t):
    t.base(led=[0.6, 0.4, 1.0])
    t.weather(wear=0.3, rust=0.2, wet=0.6)
    t.decals_layer()
    sets = {"a": ["dreamlink", "noctis", "meridian"], "b": ["meridian", "meridian", "meridian"], "c": ["noctis", "hacked", "dreamlink"]}
    for si, (sname, ads) in enumerate(sets.items()):
        for i, a in enumerate(ads):
            yaw = 120 * i
            import math
            n = [-math.sin(math.radians(yaw)), 0, math.cos(math.radians(yaw))]   # glTF: blender (nx, ny) -> (nx, -ny)
            face = max((("+x", n[0]), ("-x", -n[0]), ("+z", n[2]), ("-z", -n[2])), key=lambda kv: kv[1])[0]
            t.on_part(f"holo_{a}", f"holo_{i}", face, name=f"{sname}_{i}", variant="holo", enabled=(si == 0), emissive_strength=5.0, margin=0.0, fit="fill",
                      values={"opacity": 0.85}, channels=["base_color", "roughness", "metallic", "opacity"])
    t.top_grime(0.25)
    t.variant("meridian", 3, disable=["holo"], enable=["b_0", "b_1", "b_2"])
    t.variant("hacked", 5, disable=["holo"], enable=["c_0", "c_1", "c_2"])


@recipe
def r_neon_arrow_sign(t):
    t.base(paint="graphite", neon=[1.0, 0.15, 0.6])
    t.weather(wear=0.45, leaks=True, rust=0.4, wet=0.6, ground=False)
    t.decals_layer()
    words = [("hotel", [1.0, 0.25, 0.6]), ("bar", [0.2, 0.9, 1.0]), ("pachinko", [1.0, 0.75, 0.15]), ("capsules", [0.65, 0.35, 1.0])]
    for i, (w, tint) in enumerate(words):
        for side, face in (("r", "+x"), ("l", "-x")):
            t.on_part(f"arrow_{w}", f"panel_{side}", face, name=f"{w}_{side}", variant="words", enabled=(i == 0), tint=tint, emissive_strength=7.0, margin=0.06)
    t.top_grime(0.3)
    t.fill("Neon cyan", t.g("neon"), values=glow([0.1, 0.9, 1.0], 8.0, r=0.2), variant="neon_cyan", visible=False, channels=NO_HEIGHT)
    t.fill("Neon amber", t.g("neon"), values=glow([1.0, 0.6, 0.1], 8.0, r=0.2), variant="neon_amber", visible=False, channels=NO_HEIGHT)
    t.fill("Neon violet", t.g("neon"), values=glow([0.6, 0.25, 1.0], 8.0, r=0.2), variant="neon_violet", visible=False, channels=NO_HEIGHT)
    t.variant("bar", 3, disable=["words"], enable=["bar_r", "bar_l", "neon_cyan"])
    t.variant("pachinko", 5, disable=["words"], enable=["pachinko_r", "pachinko_l", "neon_amber"])
    t.variant("capsules", 7, disable=["words"], enable=["capsules_r", "capsules_l", "neon_violet"])


@recipe
def r_vending_machine(t):
    t.base(paint="white", led=[0.9, 0.95, 1.0], screen=[0.3, 0.8, 1.0])
    t.weather(wear=0.45, leaks=True, rust=0.3, wet=0.5)
    t.decals_layer()
    kinds = ["drinks", "noctis", "ramen"]
    for i, k in enumerate(kinds):
        en = i == 0
        t.on_part(f"vend_front_{k}", "products", "+z", name=f"front_{k}", variant="vend", enabled=en, emissive_strength=1.6, margin=0.0, fit="fill")
        t.on_part(f"vend_header_{k}", "header", "+z", name=f"header_{k}", variant="vend", enabled=en, emissive_strength=3.0, margin=0.0, fit="fill")
        t.on_part(f"vend_side_{k}", "side_wrap", "+x", name=f"side_{k}", variant="vend", enabled=en, margin=0.0, fit="fill")
    t.on_part("vend_pay", "pay_screen", "+z", emissive_strength=2.5, margin=0.0, fit="fill")
    t.on_part("vend_flap", "flap_label", "+z", margin=0.02, tint=[0.9, 0.9, 0.9])
    t.at("meridian_sticker", [0.35, 0.82, 0.39], [0, 0, 1], 0.1)
    t.at(STORY + "graffiti_unplug.png", [-0.5, 0.9, -0.0], [-1, 0, 0], 0.7, fade=0.3, wear_style="grunge", name="tag", variant="tags")
    t.at(STORY + "poster_missing_ren.png", [-0.501, 1.3, 0.15], [-1, 0, 0], 0.25, wear=0.4, fade=0.3, name="missing", variant="tags")
    t.top_grime(0.35)
    t.colour_variants("paint", ["black", "hoshikawa_red"], "drinks")
    t.variant("noctis", 3, disable=["vend"], enable=["front_noctis", "header_noctis", "side_noctis", "paint black"])
    t.variant("ramen", 5, disable=["vend"], enable=["front_ramen", "header_ramen", "side_ramen", "paint hoshikawa_red"])


@recipe
def r_trash_bag_pile(t):
    bags = t.g("bag", "bag_blue", "bag_white")
    t.base()
    t.fill("Plastic crinkle", bags, values={"roughness": 0.55},
           gen={"generator": "grunge", "amount": 0.5, "scale": 12.0, "softness": 0.2}, opacity=0.8, channels=ROUGH_ONLY)
    t.fill("Stretch marks", bags, values=V([0.12, 0.12, 0.13], 0.4),
           gen={"generator": "streaks", "amount": 0.35, "scale": 9.0, "softness": 0.3, "breakup": 0.7}, opacity=0.35, channels=NO_HEIGHT)
    t.weather(wear=0.6, rust=0.3, wet=0.8)
    t.fill("Leaking juice", bags, values=V([0.09, 0.07, 0.03], 0.15),
           gen={"generator": "leaks", "amount": 0.35, "scale": 3.0, "breakup": 0.7, "drip_length": 0.5, "softness": 0.2}, opacity=0.6, channels=NO_HEIGHT)
    t.fill("Rain on bags", bags, values={"roughness": 0.05},
           gen={"generator": "spots", "amount": 0.4, "scale": 18.0, "softness": 0.1}, opacity=0.8, channels=ROUGH_ONLY)
    t.fill("Soggy cardboard", t.g("cardboard"), values=V([0.25, 0.17, 0.09], 0.6),
           gen={"generator": "grunge", "amount": 0.55, "scale": 3.0, "softness": 0.35}, opacity=0.8, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("bin_burnable", "sticker_burnable", "+z", margin=0.03)
    t.on_part("waste_tag", "waste_tag", "+z", margin=0.03)
    t.at(STORY + "stencil_eye_crossed.png", [0.28, 0.42, 0.05], [0.3, 0.2, 0.93], 0.14, tint=[0.95, 0.95, 0.95], fade=0.4, name="tag", variant="tags",
         enabled=False)
    t.top_grime(0.3)
    t.variant("tagged", 3, enable=["tags"])


@recipe
def r_trash_bin(t):
    t.base(paint="teal", paint2="graphite")
    t.weather(wear=0.55, rust=0.3, wet=0.6)
    t.fill("Spill stains", t.g("paint"), values=V([0.15, 0.12, 0.08], 0.4),
           gen={"generator": "leaks", "amount": 0.55, "scale": 4.0, "drip_length": 0.5, "softness": 0.2}, opacity=0.6, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("bin_cans", "label_cans", "+z", margin=0.02)
    t.on_part("bin_burnable", "label_burn", "+z", margin=0.02)
    t.at("meridian_sticker", [0.32, 0.88, 0.225], [0, 0, 1], 0.1, wear=0.3)
    t.at(STORY + "graffiti_not_data.png", [0.0, 0.5, -0.224], [0, 0, -1], 0.75, fade=0.3, wear_style="grunge", name="tag", variant="tags")
    t.top_grime(0.45)
    t.colour_variants("paint", ["hoshikawa_red", "graphite"], "teal")
    t.variant("red", 3, enable=["paint hoshikawa_red"])
    t.variant("graphite", 5, enable=["paint graphite"], disable=["tags"])


@recipe
def r_cardboard_boxes(t):
    t.base()
    t.fill("Water damage", t.g("cardboard"), values=V([0.32, 0.22, 0.13], 0.7),
           gen={"generator": "gradient", "amount": 0.18, "softness": 0.15, "breakup": 0.7, "scale": 6.0}, opacity=0.8, channels=NO_HEIGHT)
    t.weather(wear=0.5, rust=0, wet=0.6)
    t.decals_layer()
    for i, tag in enumerate("abc"):
        t.on_part("box_fragile" if tag != "b" else "box_logistics", f"label_{tag}", "+z", margin=0.02)
    t.at("box_logistics", [-0.12, 0.25, 0.282], [0, 0, 1], 0.35, tint=[0.2, 0.15, 0.1], fade=0.3)


@recipe
def r_pallet(t):
    t.base()
    t.weather(wear=0.6, rust=0, wet=0.6)
    t.decals_layer()
    t.at("box_logistics", [0.0, 0.06, 0.4], [0, 0, 1], 0.14, tint=[0.15, 0.1, 0.06], fade=0.3)


@recipe
def r_crate_stack(t):
    t.base(plastic="teal")
    t.weather(wear=0.6, rust=0.5, wet=0.5)
    t.decals_layer()
    t.on_part("stencil_noctis_bio", "stencil_a", "+z", tint=[0.95, 0.95, 0.9], margin=0.02)
    t.on_part("stencil_noctis_bio", "stencil_b", "+z", tint=[0.95, 0.95, 0.9], margin=0.02)
    t.at(STORY + "stencil_eye_crossed.png", [0.35, 0.3, 0.335], [0, 0, 1], 0.2, tint=[1, 0.2, 0.25], fade=0.3, name="tag", variant="tags")
    t.top_grime(0.4)
    t.colour_variants("plastic", ["hoshikawa_red", "hazard_yellow"], "teal")
    t.variant("red", 3, enable=["plastic hoshikawa_red"])
    t.variant("yellow", 5, enable=["plastic hazard_yellow"], disable=["tags"])


@recipe
def r_bicycle(t):
    t.base(paint="cream")
    t.weather(wear=0.55, rust=0.45, wet=0.5, ground=False)
    t.decals_layer()
    t.top_grime(0.3)
    t.colour_variants("paint", ["teal", "black", "pink"], "cream")
    t.variant("teal", 3, enable=["paint teal"])
    t.variant("black", 5, enable=["paint black"])
    t.variant("pink", 7, enable=["paint pink"])


@recipe
def r_scooter(t):
    t.base(paint=V([0.05, 0.55, 0.5], 0.35), screen=[0.4, 1.0, 0.8], led=[0.9, 0.95, 1.0])
    t.weather(wear=0.45, rust=0.2, wet=0.5)
    t.decals_layer()
    t.on_part("scooter_qr", "qr_plate", "+z", margin=0.02)
    t.on_part("scooter_display", "display", "+y", emissive_strength=2.5, margin=0.0)
    t.on_part("scooter_stem", "stem_wrap", "+z", margin=0.0, fit="fill")
    t.at("meridian_sticker", [-0.1, 0.125, 0.0], [0, 1, 0], 0.08)
    t.top_grime(0.3)
    t.colour_variants("paint", ["pink", "violet"], "teal")
    t.variant("pink", 3, enable=["paint pink"])
    t.variant("violet", 5, enable=["paint violet"])


@recipe
def r_ramen_cart(t):
    t.base(paint2="graphite")
    t.weather(wear=0.55, rust=0.4, wet=0.5)
    # ribs = the tiles' mortar: a dark fill, then the paper back on the cells (an inverted mask would also invert the parts)
    t.fill("Lantern ribs", t.g("lantern"), values=V([0.2, 0.02, 0.01], 0.8, emissive=[0.4, 0.08, 0.02], emissive_strength=0.6), channels=NO_HEIGHT)
    t.fill("Lantern paper", t.g("lantern"), values=GROUP["lantern"][1],
           gen={"generator": "tiles", "variant": "square", "scale": 22.0, "aspect": 30.0, "mortar": 0.15, "amount": 1.0}, channels=NO_HEIGHT)
    t.decals_layer()
    t.decal(DEC + "noren_ramen.png", box={"center": [0.0, 1.9, 0.41], "size": [1.95, 0.42, 0.1]}, facing="+z", tint=[0.95, 0.95, 0.92])
    t.on_part("ramen_roof_sign", "roof_sign", "+z", tint=[1.0, 0.85, 0.5], emissive_strength=5.0, margin=0.05)
    t.on_part("ramen_roof_sign", "roof_sign", "-z", tint=[1.0, 0.85, 0.5], emissive_strength=5.0, margin=0.05)
    t.on_part("ramen_menu", "menu", "+x", margin=0.02)
    for x in (-1.02, 1.02):
        t.decal(DEC + "lantern_ramen.png", box={"center": [x, 1.84, 0.45], "size": [0.2, 0.3, 0.4]}, facing="+z", tint=[0.08, 0.05, 0.04])
    t.at(STORY + "poster_missing_mika.png", [0.6, 0.55, 0.36], [0, 0, 1], 0.22, wear=0.45, fade=0.3)
    t.top_grime(0.5)


@recipe
def r_skewer_stall(t):
    t.base(paint2="graphite", plastic="teal")
    t.fill("Canvas stripes", t.g("canvas"), values=V([0.86, 0.84, 0.78], 0.85),
           gen={"generator": "tiles", "variant": "square", "scale": 3.4, "aspect": 0.05, "mortar": 0.5, "amount": 1.0}, channels=NO_HEIGHT)
    t.fill("Char", t.g("meat"), values=V([0.08, 0.04, 0.02], 0.6), gen={"generator": "grunge", "amount": 0.4, "scale": 30.0, "softness": 0.2},
           channels=NO_HEIGHT)
    t.fill("Ash", t.g("coal"), values=V([0.25, 0.24, 0.23], 0.95, emissive=[0, 0, 0], emissive_strength=0.0),
           gen={"generator": "grunge", "amount": 0.45, "scale": 18.0, "softness": 0.15}, channels=NO_HEIGHT)
    t.weather(wear=0.6, rust=0.5, wet=0.5)
    t.fill("Grease", t.g("dark_metal", "wood"), values=V([0.05, 0.04, 0.03], 0.25),
           gen={"generator": "dirt", "amount": 0.6, "softness": 0.25}, opacity=0.6, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("yakitori_menu", "menu_a", "+z", margin=0.02)
    t.on_part("yakitori_valance", "valance", "+z", margin=0.01, fit="fill", tint=[1, 1, 1])
    t.at(STORY + "poster_unplug.png", [0.85, 0.5, 0.36], [0, 0, 1], 0.2, wear=0.45, fade=0.3)
    t.top_grime(0.5)


@recipe
def r_cable_bundle(t):
    t.base(paint="signal_grey")
    t.weather(wear=0.5, rust=0.5, wet=0.6, ground=False)
    t.decals_layer()
    t.on_part("junction_tag", "junction_tag", "+z", margin=0.02)


@recipe
def r_ac_unit(t):
    t.base(paint="cream")
    t.weather(wear=0.5, leaks=True, rust=0.5, wet=0.6)
    t.decals_layer()
    t.on_part("ac_brand", "brand_plate", "+z", margin=0.02)
    t.at(STORY + "stencil_eye_crossed.png", [0.3, 0.75, 0.172], [0, 0, 1], 0.16, tint=[0.1, 0.1, 0.1], fade=0.3, name="tag", variant="tags")
    t.top_grime(0.5)
    t.colour_variants("paint", ["white", "graphite"], "cream")
    t.variant("white", 3, enable=["paint white"], disable=["tags"])
    t.variant("graphite", 5, enable=["paint graphite"])


@recipe
def r_satellite_dish(t):
    t.base()
    t.weather(wear=0.5, rust=0.5, wet=0.6)
    t.decals_layer()
    import math
    a = math.radians(55)
    n = [0, math.cos(a), math.sin(a)]                     # dish axis in glTF (blender (0, -sin, cos) -> (0, cos, sin))
    c = [0, 1.12 + n[1] * 0.12, 0.05 + n[2] * 0.12]
    t.at("dish_logo", c, n, 0.6, fade=0.3)
    t.top_grime(0.5)


@recipe
def r_water_tank(t):
    t.base()
    t.fill("Stave joints", t.g("staves"), values=V([0.15, 0.12, 0.1], 0.9),
           gen={"generator": "panel_lines", "amount": 0.12, "scale": 9.0, "softness": 0.05}, opacity=0.7, channels=NO_HEIGHT)
    t.weather(wear=0.7, leaks=True, rust=0.7, wet=0.6)
    t.fill("Moss", t.g("staves", "roof_tar", "wood_dark"), values=V([0.1, 0.16, 0.05], 0.9),
           gen={"generator": "moss", "amount": 0.4, "scale": 4.0, "breakup": 0.6, "ao_influence": 0.5}, opacity=0.8, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("stencil_water", "stencil", "+z", tint=[0.9, 0.9, 0.85], margin=0.02, fade=0.3)
    t.at(STORY + "graffiti_unplug.png", [0.9, 3.5, 1.05], [0.7, 0, 0.7], 1.4, fade=0.3, wear_style="grunge")
    t.top_grime(0.5)


@recipe
def r_puddle_decal(t):
    t.L.append({"tool": "add_layer", "args": {"name": "Cut-out", "material": "Cut-out", "channels": CUT_ONLY}})
    t.decals_layer()
    for nd, img in (("Puddle_S", "puddle_a"), ("Puddle_M", "puddle_b"), ("Puddle_L", "puddle_c")):
        r = t.rec(nd)
        t.decal(DEC + img + ".png", part=t.p(nd)[0], facing="+y", fit="fill", margin=0.0,
                values={"base_color": [0.02, 0.022, 0.025], "roughness": 0.02, "metallic": 0.0, "opacity": 0.92},
                channels=["base_color", "roughness", "metallic", "opacity"])
    t.fill("Silt", None, values=V([0.12, 0.1, 0.08], 0.6), gen={"generator": "grunge", "amount": 0.35, "scale": 4.0, "softness": 0.3}, opacity=0.6,
           channels=NO_HEIGHT)
    t.fill("Oil sheen", None, values=V([0.05, 0.03, 0.08], 0.05), gen={"generator": "spots", "amount": 0.2, "scale": 1.5, "softness": 0.4}, opacity=0.4,
           channels=NO_HEIGHT)


@recipe
def r_planter(t):
    t.base()
    t.weather(wear=0.4, leaks=True, rust=0, wet=0.5)
    t.fill("Moss", t.g("concrete"), values=V([0.12, 0.18, 0.06], 0.9),
           gen={"generator": "moss", "amount": 0.45, "scale": 5.0, "breakup": 0.6, "ao_influence": 0.6}, opacity=0.8, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("planter_plate", "plate", "+z", margin=0.02)
    t.at(STORY + "graffiti_who_owns.png", [-0.35, 0.3, 0.31], [0, 0, 1], 0.75, fade=0.3, wear_style="grunge", name="tag", variant="tags", enabled=False)
    t.top_grime(0.4)
    t.variant("tagged", 3, enable=["tags"])


@recipe
def r_street_tree(t):
    t.base(paint="graphite")
    t.weather(wear=0.5, rust=0.5, wet=0.5)
    t.fill("Bark moss", t.g("bark"), values=V([0.12, 0.2, 0.06], 0.9), gen={"generator": "moss", "amount": 0.45, "scale": 6.0, "breakup": 0.6},
           opacity=0.8, channels=NO_HEIGHT)
    t.decals_layer()
    t.fill("Autumn", t.g("leaves"), values=V([0.55, 0.28, 0.06], 0.7), variant="autumn", visible=False, channels=NO_HEIGHT)
    t.fill("Neon leaves", t.g("leaves"), values=V([0.25, 0.08, 0.3], 0.6), variant="neon", visible=False, channels=NO_HEIGHT)
    t.variant("autumn", 3, enable=["autumn"])
    t.variant("violet", 5, enable=["neon"])


@recipe
def r_palm_tree(t):
    t.base(led=[1.0, 0.85, 0.6])
    t.fill("Trunk rings", t.g("palm_bark"), values=V([0.2, 0.15, 0.1], 0.9), channels=NO_HEIGHT)
    t.fill("Trunk bark", t.g("palm_bark"), values=GROUP["palm_bark"][1],
           gen={"generator": "tiles", "variant": "square", "scale": 7.0, "aspect": 40.0, "mortar": 0.3, "amount": 1.0}, channels=NO_HEIGHT)
    t.weather(wear=0.3, rust=0.2, wet=0.4)
    t.fill("Frond tips", t.g("frond"), values=V([0.45, 0.4, 0.15], 0.7),
           gen={"generator": "grunge", "amount": 0.3, "scale": 3.0, "softness": 0.3}, opacity=0.6, channels=NO_HEIGHT)
    t.decals_layer()


# ------------------------------------------------------------------ port kit (tools/props/models_port.py)

CONTAINER_COLOURS = ["rust", "blue", "white", "green", "orange", "grey", "teal"]


def port_rust(t, parts, amount=0.5):
    """Painted steel that has lived at sea: salt-faded paint, rust blooms at edges and pits,
    rust runs below them."""
    t.fill("Salt fade", parts, values=V([0.55, 0.52, 0.48], 0.75),
           gen={"generator": "grunge", "amount": 0.3 + 0.2 * amount, "scale": 1.6, "softness": 0.45}, opacity=0.22, channels=NO_HEIGHT)
    t.fill("Rust bloom", parts, material="Rust",
           gen={"generator": "edge_wear", "amount": 0.25 + 0.35 * amount, "softness": 0.25, "breakup": 0.85, "scale": 7.0,
                "effects": [{"generator": "spots", "op": "multiply", "amount": 0.55 + 0.3 * amount, "scale": 6.0, "softness": 0.25}]},
           opacity=0.9, channels=NO_HEIGHT)
    t.fill("Rust pits", parts, material="Rust", gen={"generator": "spots", "amount": 0.12 + 0.2 * amount, "scale": 22.0, "softness": 0.15},
           opacity=0.8, channels=NO_HEIGHT)
    t.fill("Rust runs", parts, values=V([0.3, 0.12, 0.05], 0.7),
           gen={"generator": "leaks", "amount": 0.35 + 0.3 * amount, "scale": 4.0, "breakup": 0.7, "drip_length": 0.9, "ao_influence": 0.4,
                "softness": 0.2}, opacity=0.55, channels=NO_HEIGHT)


def crest(s0, length, pitch, s, flat=0.36):
    """Nearest crest centre of a models_port.corr_profile sheet to s: anchored decals snap to
    the face under their centre, so they must sit on a crest (a slope would tilt them 45 deg)."""
    n = max(1, int(round(length / pitch)))
    p = length / n
    k = min(n - 1, max(0, round((s - s0) / p - flat / 2)))
    return round(s0 + p * (k + flat / 2), 4)


@recipe
def r_container(t):
    t.base(paint=PAINTS["c_rust"], paint2="graphite", extra={"iron": V([0.03, 0.03, 0.03], 0.7, 0.2)})
    for c in CONTAINER_COLOURS[1:]:
        t.fill(f"paint {c}", t.g("paint"), values=PAINTS["c_" + c], variant="colours", visible=False)
    t.default_variant = "rust"
    t.weather(wear=0.75, leaks=True, rust=0.7, wet=0.4)
    port_rust(t, t.g("paint", "paint2"), 0.7)
    t.decals_layer()
    L, hz = 12.192, 1.207 + 0.01
    sx = lambda x: crest(-L / 2 + 0.15, L - 0.35, 0.278, x)                # side walls (glTF x)
    dy = lambda y: crest(0.27, 2.591 - 0.24 - 0.17 - 0.18, 0.4, y)          # door ribs (height)
    fz = lambda z: -crest(-(1.219 - 0.15), 2.438 - 0.3, 0.33, -z)           # front wall (glTF z)
    for c in CONTAINER_COLOURS:
        on = c == "rust"
        for sgn, side in ((1, "a"), (-1, "b")):
            t.at(DEC + f"container_logo_{c}.png", [sx(-0.6 * sgn), 1.42, sgn * hz], [0, 0, sgn], [6.2, 2.36], name=f"logo_{c}_{side}", variant="lines",
                 enabled=on, wear=0.35, fade=0.15, depth=0.12)
            t.at(DEC + f"container_code_{c}.png", [sx(4.75 * sgn), 2.2, sgn * hz], [0, 0, sgn], [1.55, 0.52], name=f"code_{c}_{side}", variant="lines",
                 enabled=on, wear=0.3, depth=0.12)
        t.at(DEC + f"container_code_{c}.png", [L / 2 + 0.01, dy(2.05), 0.55], [1, 0, 0], [0.84, 0.28], name=f"code_{c}_door", variant="lines", enabled=on, wear=0.3)
        t.at(DEC + f"container_code_{c}.png", [-L / 2 - 0.01, 2.2, fz(0.0)], [-1, 0, 0], [1.2, 0.4], name=f"code_{c}_front", variant="lines", enabled=on, wear=0.3)
    t.at(DEC + "container_weights.png", [L / 2 + 0.01, dy(1.1), -0.6], [1, 0, 0], [0.62, 0.37], wear=0.3)
    t.on_part("container_csc", "csc_plate", "+x", margin=0.03)
    t.on_part("container_customs", "customs_plate", "+x", margin=0.03)
    t.at(STORY + "graffiti_unplug.png", [sx(-3.6), 0.85, hz], [0, 0, 1], 1.5, fade=0.2, depth=0.12, wear_style="grunge", name="tag_unplug", variant="tags", enabled=False)
    t.at(STORY + "graffiti_not_data.png", [sx(2.0), 0.9, -hz], [0, 0, -1], 1.7, fade=0.2, depth=0.12, wear_style="grunge", name="tag_not_data", variant="tags", enabled=False)
    t.at(STORY + "poster_missing_mika.png", [L / 2 + 0.012, dy(1.5), 0.62], [1, 0, 0], 0.34, wear=0.5, fade=0.3, name="tag_poster", variant="tags", enabled=False)
    t.at(STORY + "stencil_eye_crossed.png", [-L / 2 - 0.012, 1.0, fz(-0.45)], [-1, 0, 0], 0.55, tint=[0.95, 0.95, 0.95], fade=0.3, name="tag_eye", variant="tags",
         enabled=False)
    t.top_grime(0.45)
    tags = {"blue": ["tag_unplug"], "green": ["tag_not_data", "tag_poster"], "grey": ["tag_not_data", "tag_eye"], "orange": ["tag_poster"]}
    for i, c in enumerate(CONTAINER_COLOURS[1:]):
        t.variant(c, 3 + 2 * i, disable=["lines"],
                  enable=[f"paint {c}"] + [f"{k}_{c}_{x}" for k in ("logo", "code") for x in ("a", "b")] + [f"code_{c}_door", f"code_{c}_front"] + tags.get(c, []))


@recipe
def r_crane_sts(t):
    t.base(paint=PAINTS["crane_red"], paint2="white", extra={"cable": V([0.04, 0.04, 0.045], 0.45, 0.8)})
    for c in ("blue", "white"):
        t.fill(f"paint {c}", t.g("paint"), values=PAINTS["crane_" + c], variant="colours", visible=False)
    t.default_variant = "red"
    t.weather(wear=0.55, leaks=True, rust=0.55, wet=0.4)
    port_rust(t, t.g("paint", "paint2", "hazard"), 0.45)
    t.fill("Grease", t.g("dark_metal", "steel"), values=V([0.02, 0.018, 0.015], 0.25, 0.2),
           gen={"generator": "dirt", "amount": 0.55, "softness": 0.3, "breakup": 0.6}, opacity=0.7, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("crane_banner", "house_banner_1", "+x", margin=0.02)
    t.on_part("crane_banner", "house_banner_-1", "-x", margin=0.02)
    t.on_part("crane_number", "house_number", "+z", margin=0.03)
    for sgn in (-1, 1):
        for x in (-6.0, 6.0):
            t.at(DEC + "crane_warning.png", [x, 2.75, sgn * 9.86], [0, 0, sgn], [3.6, 0.93], wear=0.35, fade=0.15)
    t.at(STORY + "graffiti_unplug.png", [14.0, 7.6, 9.76], [0, 0, 1], 1.8, fade=0.2, wear_style="grunge")
    t.at(STORY + "poster_missing_ren.png", [-14.0, 6.6, 9.76], [0, 0, 1], 0.6, wear=0.45, fade=0.3)
    cab = t.rec("cab")
    c = cab["center"]
    t.at(DEC + "meridian_sticker.png", [c[0] + 0.7, c[1] + 0.6, c[2] - cab["size"][2] / 2 - 0.01], [0, 0, -1], 0.45, wear=0.2)
    t.top_grime(0.4)
    t.variant("blue", 3, enable=["paint blue"])
    t.variant("white", 5, enable=["paint white"])


@recipe
def r_light_mast(t):
    t.base(paint="signal_grey", extra={"bulb": glow([1.0, 0.85, 0.6], 8.0, base=[1.0, 0.92, 0.75], r=0.1)})
    t.weather(wear=0.5, leaks=True, rust=0.5, wet=0.5)
    t.fill("Salt bloom", t.g("galv"), values=V([0.6, 0.6, 0.58], 0.8),
           gen={"generator": "spots", "amount": 0.35, "scale": 8.0, "softness": 0.35}, opacity=0.5, channels=NO_HEIGHT)
    t.fill("Concrete stains", t.g("concrete"), values=V([0.18, 0.12, 0.08], 0.85),
           gen={"generator": "leaks", "amount": 0.5, "scale": 3.0, "breakup": 0.6, "drip_length": 0.6, "softness": 0.2}, opacity=0.6, channels=NO_HEIGHT)
    t.decals_layer()
    t.on_part("mast_plate", "mast_plate", "+z", margin=0.03)
    t.on_part("mast_cabinet", "cabinet_label", "+z", margin=0.03)
    t.at(STORY + "poster_unplug.png", [0.375, 2.6, 0.0], [1, 0, 0], 0.42, wear=0.45, fade=0.3)
    t.at(STORY + "plate_observed.png", [-0.37, 3.4, 0.0], [-1, 0, 0], 0.4, wear=0.2)
    t.at(DEC + "meridian_sticker.png", [0.874, 0.95, -0.62], [1, 0, 0], 0.16, wear=0.25)
    t.top_grime(0.35)


# ------------------------------------------------------------------ main

def build(name, do_run=True):
    t = T(name)
    if name not in R:
        raise SystemExit(f"no recipe for {name}")
    R[name](t)
    lines = t.script()
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    path = SCRIPTS / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf8")
    info = {"variants": [v["name"] for v in t.variants], "default": t.default_variant or "default",
            "groups": {g: len(ids) for g, ids in t.groups.items()}}
    if do_run:
        run(lines, name, keep=path)
        print(f"[props_textures] {name}: {len(lines)} steps, {len(t.variants)} variants")
    return name, info


def main():
    args = sys.argv[1:]
    do_run = "--no-run" not in args
    jobs = int(args[args.index("--jobs") + 1]) if "--jobs" in args else 2
    names = [a for a in args if not a.startswith("--") and not a.isdigit()] or catalog.names()
    (ROOT / PROJECTS).mkdir(parents=True, exist_ok=True)
    out = {}
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        for name, info in ex.map(lambda n: build(n, do_run), names):
            out[name] = info
    vpath = ROOT / TEXTURES / "variants.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(vpath.read_text()) if vpath.exists() else {}
    old.update(out)
    vpath.write_text(json.dumps(old, indent=1))
    print(f"[props_textures] {len(names)} props")


if __name__ == "__main__":
    main()
