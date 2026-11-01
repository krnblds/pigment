"""Interior-mapped windows: build the room library and the window maps.

Pipeline (each stage reads the previous stage's files; all output is
git-ignored under scenes/town/textures/interiors/):

    python tools/interiors/interiors.py build    [room ...]   Blender: procedural rooms -> meshes/<room>.glb + .json
    python tools/interiors/interiors.py texture  [room ...]   Pigment (MCP script): materials, grime, wear, posters,
                                                              emissive screens / neon decals -> <room>/ texture sets
                                                              (scripts: scenes/town/scripts/interiors/<room>.jsonl)
    python tools/interiors/interiors.py render   [room ...]   Blender Cycles: pre-projected lit / off / depth renders
    python tools/interiors/interiors.py pack                  Pigment pack_interiors: graded atlas strip + interiors.json
    python tools/interiors/interiors.py windows               Pigment export_window_map for building_a/b/c
    python tools/interiors/interiors.py sheet                 contact sheet of every room (docs/agents/interiors/)
    python tools/interiors/interiors.py sync                  copy atlas + window maps into game/assets/interiors/
    python tools/interiors/interiors.py all      [room ...]   everything above

    PIGMENT_MCP=path/to/pigment-mcp.exe   CITY_BLENDER=path/to/blender.exe   (as tools/city)

The room list and every room's furniture live in tools/interiors/rooms.py;
docs/agents/interiors/NOTES.md explains the format and how to add a room.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
OUT = ROOT / "scenes" / "town" / "textures" / "interiors"
SCRIPTS = ROOT / "scenes" / "town" / "scripts" / "interiors"
GAME = ROOT / "game" / "assets" / "interiors"
DOCS = ROOT / "docs" / "agents" / "interiors"
BLENDER = os.environ.get("CITY_BLENDER", r"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")
CELL = 512
KIT = ("building_a", "building_b", "building_c")


def mcp_exe():
    if os.environ.get("PIGMENT_MCP"):
        return Path(os.environ["PIGMENT_MCP"])
    for c in (ROOT / "target" / "release" / "pigment-mcp.exe", ROOT.parents[2] / "target" / "release" / "pigment-mcp.exe"):
        if c.exists():
            return c
    raise SystemExit("pigment-mcp.exe not found: cargo build --release, or set PIGMENT_MCP")


def run_script(lines, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf8")
    r = subprocess.run([str(mcp_exe()), "--script", str(path)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{path.name}: {r.stdout[-1500:]}\n{r.stderr[-2500:]}")
    return r.stdout


def blender(mode, rooms, *extra):
    cmd = [BLENDER, "-b", "--factory-startup", "--python", str(ROOT / "tools" / "interiors" / "rooms.py"), "--", mode, str(OUT), *rooms, *extra]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = "\n".join(l for l in r.stdout.splitlines() if l.startswith("[rooms]") or "Error" in l or "Traceback" in l)
    print(out)
    if r.returncode != 0 or "Traceback" in r.stdout or "Traceback" in r.stderr:
        raise SystemExit(f"blender {mode} failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")


def room_names():
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(ROOT / "tools" / "interiors" / "rooms.py"), "--", "list", str(OUT)],
                       cwd=ROOT, capture_output=True, text=True)
    names = []
    for l in r.stdout.splitlines():
        p = l.split(" ", 1)
        if len(p) == 2 and p[1].startswith("["):
            names.append(p[0])
    return names


# ------------------------------------------------------------------ Pigment texturing
def _layer(name, parts, values, gen=None, **kw):
    mask = {"parts": parts}
    if gen:
        mask.update(gen)
    a = {"name": name, "mask": mask, "values": values}
    a.update(kw)
    return {"tool": "add_layer", "args": a}


def match_parts(parts, side):
    """Pigment part id -> sidecar role: the smallest recorded box holding the part's centre."""
    boxes = side["parts"]
    out = {}
    for p in parts:
        c = p["center"]
        best, vol = None, 1e9
        for k, b in enumerate(boxes):
            if all(b["min"][i] - 2e-3 <= c[i] <= b["max"][i] + 2e-3 for i in range(3)):
                v = 1.0
                for i in range(3):
                    v *= max(1e-4, b["max"][i] - b["min"][i])
                if v < vol:
                    best, vol = k, v
        if best is not None:
            out[p["id"]] = best
    return out


def texture_script(name):
    side = json.loads((OUT / "meshes" / f"{name}.json").read_text())
    glb = (OUT / "meshes" / f"{name}.glb").relative_to(ROOT).as_posix()
    probe = run_script([{"tool": "new_project", "args": {"mesh": glb, "resolution": 512}}, {"tool": "list_parts", "args": {}}], SCRIPTS / f"_{name}_parts.jsonl")
    parts = json.loads(probe[probe.index("[list_parts] ") + 13:].split("\n[")[0])
    (SCRIPTS / f"_{name}_parts.jsonl").unlink()
    owner = match_parts(parts, side)
    # group parts by role
    groups = {}
    for pid, k in owner.items():
        role = side["parts"][k]["role"]
        key = json.dumps(role, sort_keys=True)
        groups.setdefault(key, []).append(pid)
    shell = [pid for pid, k in owner.items() if k < 5]        # floor, ceiling, back, left, right (shell() comes first)
    floor = [pid for pid, k in owner.items() if k == 0]
    walls = [pid for pid, k in owner.items() if 2 <= k < 5]
    furniture = [pid for pid, k in owner.items() if k >= 5]
    L = [{"tool": "new_project", "args": {"mesh": glb, "resolution": 2048, "material": "White plastic"}},
         {"tool": "bake", "args": {"ao_distance": 0.25, "curvature_radius": 0.005, "curvature_strength": 0.7}},
         {"tool": "delete_layer", "args": {"layer": "Paint"}}]
    seed = sum(map(ord, name))
    for i, (key, ids) in enumerate(sorted(groups.items())):
        role = json.loads(key)
        v = {"base_color": role["color"], "roughness": role["rough"], "metallic": role["metal"]}
        label = f"Role {i}"
        if role.get("emit"):
            v.update({"emissive": role["emit"], "emissive_strength": role["strength"]})
            label = f"Glow {i}"
        L.append(_layer(label, ids, v))
        c = role["color"]
        dark = [x * 0.6 for x in c]
        if role.get("grain"):
            L.append(_layer(f"{label} grain", ids, {"base_color": dark, "roughness": min(1, role["rough"] + 0.1)},
                            {"generator": "stripes", "amount": 0.45, "scale": 18.0, "softness": 0.6, "breakup": 0.8, "seed": seed + i}, opacity=0.5, channels={"height": False}))
        if role.get("tiles"):
            L.append(_layer(f"{label} grout", ids, {"base_color": [x * 0.45 for x in c], "roughness": 0.9, "height": -0.4},
                            {"generator": "tiles", "variant": "square", "scale": 3.0, "aspect": 1.0, "mortar": 0.04, "amount": 0.5, "softness": 0.02, "seed": seed + i}))
        if role.get("carpet") or role.get("fabric") or role.get("rubber"):
            L.append(_layer(f"{label} weave", ids, {"base_color": dark}, {"generator": "spots", "amount": 0.35, "scale": 120.0, "softness": 0.3, "seed": seed + i}, opacity=0.5, channels={"height": False}))
        if role.get("concrete"):
            L.append(_layer(f"{label} stains", ids, {"base_color": dark, "roughness": 0.95}, {"generator": "grunge", "amount": 0.45, "scale": 1.2, "softness": 0.3, "seed": seed + i}, opacity=0.7))
        if role.get("peeling"):
            L.append(_layer(f"{label} peeling", ids, {"base_color": [0.22, 0.2, 0.17], "roughness": 0.95, "height": -0.3},
                            {"generator": "grunge", "amount": 0.3, "scale": 2.5, "softness": 0.05, "breakup": 0.6, "seed": seed + i}))
        if role.get("leaves"):
            L.append(_layer(f"{label} veins", ids, {"base_color": [0.15, 0.32, 0.08]}, {"generator": "spots", "amount": 0.4, "scale": 30.0, "softness": 0.4, "seed": seed + i}, opacity=0.6))
        if role.get("mesh"):
            L.append({"tool": "add_layer", "args": {"name": f"{label} cut", "material": "Cut-out", "mask": {"parts": ids},
                                                     "channels": {"base_color": False, "roughness": False, "metallic": False, "height": False, "normal": False}}})
            L.append(_layer(f"{label} wires", ids, {"opacity": 1.0}, {"generator": "panel_lines", "amount": 0.25, "scale": 8.0, "softness": 0.02},
                            channels={"base_color": False, "roughness": False, "metallic": False, "height": False, "normal": False}))
        if role.get("city"):
            # a night skyline seen through the back window: lit window grid, dimmer towards the top
            L.append(_layer(f"{label} city", ids, {"base_color": [1.0, 0.8, 0.55], "emissive": [1.0, 0.75, 0.45], "emissive_strength": 3.0},
                            {"generator": "window_grid", "amount": 0.3, "scale": 6.0, "softness": 0.05, "seed": seed + i}))
            L.append(_layer(f"{label} city blue", ids, {"base_color": [0.5, 0.7, 1.0], "emissive": [0.45, 0.65, 1.0], "emissive_strength": 2.0},
                            {"generator": "window_grid", "amount": 0.12, "scale": 9.0, "softness": 0.05, "seed": seed + i + 7}))
    # wear and grime: Pigment generators driven by the AO / curvature bake
    if walls:
        L.append(_layer("Wall scuffs", walls, {"base_color": [0.1, 0.09, 0.08], "roughness": 0.9},
                        {"generator": "gradient", "amount": 0.12, "softness": 0.4, "breakup": 0.7, "seed": seed}, opacity=0.45, channels={"height": False, "metallic": False, "emissive": False}))
        L.append(_layer("Wall stains", walls, {"base_color": [0.12, 0.1, 0.08], "roughness": 0.9},
                        {"generator": "leaks", "amount": 0.35, "scale": 2.0, "breakup": 0.6, "drip_length": 2.0, "softness": 0.15, "seed": seed + 1}, opacity=0.35, channels={"height": False, "metallic": False, "emissive": False}))
    if floor:
        L.append(_layer("Floor wear", floor, {"base_color": [0.06, 0.055, 0.05], "roughness": 0.95},
                        {"generator": "grunge", "amount": 0.4, "scale": 1.5, "softness": 0.35, "seed": seed + 2}, opacity=0.5, channels={"height": False, "metallic": False, "emissive": False}))
    if furniture:
        L.append(_layer("Edge wear", furniture, {"base_color": [0.6, 0.6, 0.6], "roughness": 0.3, "metallic": 0.6},
                        {"generator": "edge_wear", "amount": 0.25, "scale": 20.0, "breakup": 0.7, "softness": 0.05, "seed": seed + 3}, opacity=0.6, channels={"height": False, "emissive": False}))
    L.append({"tool": "add_layer", "args": {"name": "Grime", "material": "Grime", "mask": {"generator": "dirt", "amount": 0.45, "softness": 0.25, "breakup": 0.5, "seed": seed + 4},
                                             "opacity": 0.6, "channels": {"emissive": False, "metallic": False}}})
    # posters, screens and neon: decals on their own paint layer
    L.append({"tool": "add_layer", "args": {"kind": "paint", "name": "Decals"}})
    for d in side["decals"]:
        a = {"image": d["image"], "layer": "Decals", "position": d["position"], "normal": d["normal"], "size": d["size"]}
        if d.get("emissive", 0) > 0:
            a["emissive_strength"] = d["emissive"]
        if d.get("tint") and d["tint"] != [1, 1, 1]:
            a["tint"] = d["tint"]
        if d.get("opacity", 1.0) < 1.0:
            a["opacity"] = d["opacity"]
        L.append({"tool": "project_decal", "args": a})
    tex = (OUT / name).relative_to(ROOT).as_posix()
    L += [{"tool": "export_textures", "args": {"dir": tex, "name": name, "preset": "separate"}},
          {"tool": "send_to_blender", "args": {"dir": tex, "name": name, "mesh": False}},
          {"tool": "save_project", "args": {"path": (OUT / "projects" / f"{name}.pigment").relative_to(ROOT).as_posix()}}]
    return L


def texture(names):
    for n in names:
        L = texture_script(n)
        out = run_script(L, SCRIPTS / f"{n}.jsonl")
        line = [l for l in out.splitlines() if l.startswith("script:")]
        print(f"[pigment] {n}: {line[0] if line else 'ok'}")


# ------------------------------------------------------------------ pack / window maps / sheet / sync
GRADE = {"contrast": 1.05, "saturation": 1.08, "lift": [0.004, 0.004, 0.008]}


def pack(names):
    rooms = []
    for n in names:
        side = json.loads((OUT / "meshes" / f"{n}.json").read_text())
        rd = (OUT / "renders").relative_to(ROOT).as_posix()
        rooms.append({"name": n, "size": side["size"][:1] + side["size"][1:2] + side["size"][2:3], "eye": side["eye"],
                      "lit": f"{rd}/{n}_lit.png", "off": f"{rd}/{n}_off.png", "depth": f"{rd}/{n}_depth.png",
                      "grade": side.get("grade") or {}, "off_grade": {"saturation": 0.85, "tint": [0.85, 0.92, 1.1]}, "tags": side["tags"]})
    a = {"dir": OUT.relative_to(ROOT).as_posix(), "name": "interiors", "cell": CELL, "grade": GRADE, "rooms": rooms}
    out = run_script([{"tool": "pack_interiors", "args": a}], SCRIPTS / "pack.jsonl")
    print("[pigment] pack_interiors:", [l for l in out.splitlines() if l.startswith("script:")][0])


def kit_glass(asset):
    import town_textures as T
    parts = T.parts_of(asset)
    ids = []
    for p in parts:
        k = T.classify(p)
        if k == "glass" and p["size"][1] < 3.0:     # tall glass is a blade sign face (town_textures.building)
            ids.append(p["id"])
    return ids


def windows():
    L = []
    for a in KIT:
        res = 2048 if a == "building_c" else 1024
        L += [{"tool": "new_project", "args": {"mesh": f"assets/town/{a}.glb", "resolution": 512}},
              {"tool": "export_window_map", "args": {"dir": (OUT / "windows").relative_to(ROOT).as_posix(), "name": a, "parts": kit_glass(a), "resolution": res, "pad": 3}}]
    out = run_script(L, SCRIPTS / "windows.jsonl")
    print("[pigment] window maps:", [l for l in out.splitlines() if l.startswith("script:")][0])


def sheet():
    from PIL import Image, ImageDraw, ImageFont
    atlas = json.loads((OUT / "interiors.json").read_text())
    img = Image.open(OUT / atlas["image"]).convert("RGBA")
    c = atlas["cell"]
    rooms = atlas["rooms"]
    cols = 6
    tw, th = 300, 225
    rows = (len(rooms) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw * 2 + 12) + 12, rows * (th + 34) + 12), (14, 14, 18))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    cols = cols // 2 * 1 or 1
    sheet = Image.new("RGB", (3 * (tw * 2 + 18) + 12, ((len(rooms) + 2) // 3) * (th + 34) + 12), (14, 14, 18))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(rooms):
        x0 = 12 + (i % 3) * (tw * 2 + 18)
        y0 = 12 + (i // 3) * (th + 34)
        w, h = r["size"][0], r["size"][1]
        for k, layer in enumerate((r["lit_layer"], r["off_layer"])):
            tile = img.crop((0, layer * c, c, (layer + 1) * c)).convert("RGB").resize((tw, int(tw * h / w)))
            sheet.paste(tile, (x0 + k * (tw + 4), y0))
        d.text((x0, y0 + th + 6), f"{r['name']}  ({', '.join(r['tags'][:3])})   lit | off", fill=(220, 220, 225), font=font)
    DOCS.mkdir(parents=True, exist_ok=True)
    sheet.save(DOCS / "rooms_contact_sheet.png", optimize=True)
    print("[sheet]", DOCS / "rooms_contact_sheet.png")


GODOT_IMPORT = """[remap]

importer="2d_array_texture"
type="CompressedTexture2DArray"

[deps]

source_file="res://assets/interiors/interiors_atlas.png"

[params]

compress/mode=2
compress/high_quality=false
compress/lossy_quality=0.7
compress/hdr_compression=1
compress/channel_pack=0
mipmaps/generate=true
mipmaps/limit=-1
slices/horizontal=1
slices/vertical={layers}
"""


def sync():
    """Copy what the game needs: the atlas (imported as a mipmapped, BC-compressed
    Texture2DArray), the room table and the kit window maps."""
    GAME.mkdir(parents=True, exist_ok=True)
    atlas = json.loads((OUT / "interiors.json").read_text())
    shutil.copyfile(OUT / atlas["image"], GAME / "interiors_atlas.png")
    shutil.copyfile(OUT / "interiors.json", GAME / "interiors.json")
    imp = GAME / "interiors_atlas.png.import"
    want = GODOT_IMPORT.format(layers=atlas["layers"])
    if not imp.exists() or "slices/vertical=%d" % atlas["layers"] not in imp.read_text():
        imp.write_text(want)
    for a in KIT:
        for suf in ("_WindowMap.png", "_panes.json"):
            src = OUT / "windows" / f"{a}{suf}"
            if src.exists():
                shutil.copyfile(src, GAME / f"{a}{suf}")
        wimp = GAME / f"{a}_WindowMap.png.import"
        if not wimp.exists():
            wimp.write_text(f"""[remap]

importer="texture"
type="CompressedTexture2D"

[deps]

source_file="res://assets/interiors/{a}_WindowMap.png"

[params]

compress/mode=0
mipmaps/generate=false
process/fix_alpha_border=false
detect_3d/compress_to=0
""")
    print("[sync]", GAME)


def main():
    args = sys.argv[1:] or ["all"]
    stage, names = args[0], args[1:]
    if stage in ("build", "texture", "render", "all") and not names:
        names = room_names()
    if stage in ("build", "all"):
        blender("build", names)
    if stage in ("texture", "all"):
        texture(names)
    if stage in ("render", "all"):
        blender("render", names)
    if stage in ("pack", "all"):
        pack(names or room_names())
    if stage in ("windows", "all"):
        windows()
    if stage in ("sheet", "all"):
        sheet()
    if stage in ("sync", "all"):
        sync()


if __name__ == "__main__":
    main()
