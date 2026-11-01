"""Pack Pigment's "separate" exports into Godot-ready textures (system Python: PIL + numpy).

    python tools/godot/pack_textures.py [--out game/assets/town] [--size 2048] [--force]

Reads <out>/town_layout.json (written by tools/godot/export_town.py) and, for every material of
type "pigment", writes <out>/textures/<folder>/:
    albedo.png     sRGB RGB, + alpha from _Opacity.png when the material has one
    orm.png        R = AO, G = roughness, B = metallic   (Godot ORMMaterial3D)
    normal.png     OpenGL (+Y) tangent normal, which is Godot's convention
    emission.png   sRGB, only when the emissive map is not black
plus a .import file per PNG (VRAM compressed, mipmaps; normal maps flagged) so the headless
import produces GPU-compressed textures without the editor's 3D-usage detection.
Skips folders whose outputs are newer than their sources unless --force.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARGS = sys.argv[1:]


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


OUT = os.path.abspath(str(opt("--out", os.path.join(ROOT, "game", "assets", "town"))))
SIZE = int(opt("--size", 2048))
FORCE = bool(opt("--force", False))

IMPORT = """[remap]

importer="texture"
type="CompressedTexture2D"

[deps]

source_file="{res}"

[params]

compress/mode=2
compress/high_quality=false
compress/lossy_quality=0.7
compress/uastc_level=0
compress/rdo_quality_loss=0.0
compress/hdr_compression=1
compress/normal_map={normal}
compress/channel_pack=0
mipmaps/generate=true
mipmaps/limit=-1
roughness/mode=0
roughness/src_normal=""
process/channel_remap/red=0
process/channel_remap/green=1
process/channel_remap/blue=2
process/channel_remap/alpha=3
process/fix_alpha_border=true
process/premult_alpha=false
process/normal_map_invert_y=false
process/hdr_as_srgb=false
process/hdr_clamp_exposure=false
process/size_limit=0
detect_3d/compress_to=0
"""


def res_path(p):
    game = os.path.join(ROOT, "game")
    rel = os.path.relpath(p, game).replace("\\", "/")
    return "res://" + rel


def write_import(png, normal=False):
    imp = png + ".import"
    if os.path.isfile(imp):
        return
    with open(imp, "w", encoding="utf-8") as f:
        f.write(IMPORT.format(res=res_path(png), normal=1 if normal else 0))


def load(path, mode, size):
    im = Image.open(path)
    if im.mode == "I;16" or im.mode == "I":
        im = Image.fromarray((np.asarray(im, dtype=np.float32) / 257.0).clip(0, 255).astype(np.uint8))
    im = im.convert(mode)
    if im.size[0] > size:
        im = im.resize((size, size), Image.LANCZOS)
    return im


def save(im, path, normal=False):
    im.save(path, optimize=False, compress_level=6)
    write_import(path, normal)


def pack(folder_src, name, dst, has_opacity):
    os.makedirs(dst, exist_ok=True)
    src = lambda suf: os.path.join(folder_src, f"{name}_{suf}.png")
    if not os.path.isfile(src("BaseColor")):
        print("  missing", src("BaseColor"))
        return False
    newest = max(os.path.getmtime(os.path.join(folder_src, f)) for f in os.listdir(folder_src))
    marker = os.path.join(dst, "albedo.png")
    if not FORCE and os.path.isfile(marker) and os.path.getmtime(marker) > newest:
        return True
    base = load(src("BaseColor"), "RGB", SIZE)
    size = base.size
    if has_opacity and os.path.isfile(src("Opacity")):
        a = load(src("Opacity"), "L", SIZE).resize(size)
        base = base.copy()
        base.putalpha(a)
    save(base, os.path.join(dst, "albedo.png"))

    def chan(suf, default):
        p = src(suf)
        if os.path.isfile(p):
            return np.asarray(load(p, "L", SIZE).resize(size))
        return np.full((size[1], size[0]), default, np.uint8)
    orm = np.stack([chan("AO", 255), chan("Roughness", 200), chan("Metallic", 0)], axis=-1)
    save(Image.fromarray(orm, "RGB"), os.path.join(dst, "orm.png"))
    nrm = src("Normal_OpenGL")
    if os.path.isfile(nrm):
        save(load(nrm, "RGB", SIZE).resize(size), os.path.join(dst, "normal.png"), normal=True)
    em = src("Emissive")
    epath = os.path.join(dst, "emission.png")
    if os.path.isfile(em):
        e = load(em, "RGB", SIZE).resize(size)
        if np.asarray(e).max() > 3:
            save(e, epath)
        elif os.path.isfile(epath):
            os.remove(epath)
    return True


def main():
    layout_path = os.path.join(OUT, "town_layout.json")
    if not os.path.exists(layout_path):      # the open world (tools/world/world_export.py)
        layout_path = os.path.join(OUT, "world_layout.json")
    layout = json.load(open(layout_path, encoding="utf-8"))
    done = set()
    tex_root = os.path.join(OUT, "textures")
    for mname, m in layout["materials"].items():
        if m.get("type") != "pigment" or m["folder"] in done:
            continue
        done.add(m["folder"])
        src = m["src"]
        if not os.path.isdir(src):
            for sub in ("town", "props", "world"):
                cand = os.path.join(ROOT, "scenes", sub, "textures", m["folder"])
                if os.path.isdir(cand):
                    src = cand
                    break
        ok = pack(src, m["name"], os.path.join(tex_root, m["folder"]), m.get("opacity"))
        print(("packed " if ok else "FAILED ") + m["folder"])
    img_dir = os.path.join(OUT, "images")
    if os.path.isdir(img_dir):
        for fn in os.listdir(img_dir):
            if fn.endswith(".png"):
                write_import(os.path.join(img_dir, fn))
    print(f"textures: {len(done)} folders -> {tex_root}")
    no_mesh_lods(layout)


# Godot's automatic mesh LODs simplify the terrain (and long road / junction / bridge meshes)
# without knowing about the road cuts, so a coarse hillside pokes up through the carriageway.
# These are already split into chunks, so they keep full detail; other meshes keep auto LOD.
NO_LOD_CATS = {"terrain", "road", "junction", "bridge", "decal", "wall", "stairs", "seawall", "water"}


def no_mesh_lods(layout):
    n = 0
    for key, m in layout.get("meshes", {}).items():
        if m.get("cat") not in NO_LOD_CATS:
            continue
        imp = os.path.join(OUT, m["file"] + ".import")
        if not os.path.isfile(imp):
            continue
        txt = open(imp, encoding="utf-8").read()
        if "meshes/generate_lods=true" in txt:
            open(imp, "w", encoding="utf-8").write(txt.replace("meshes/generate_lods=true", "meshes/generate_lods=false"))
            n += 1
    print(f"mesh LODs off for {n} terrain / road / bridge meshes (re-import to apply)")


if __name__ == "__main__":     # tools/city imports pack() for one folder at a time
    main()
