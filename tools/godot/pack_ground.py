"""Pack the Pigment ground sets (tools/ground_textures.py) and the world ground
masks (tools/world/ground_masks.py) for Godot's terrain shader
(game/scripts/terrain.gdshader):

    images/ground/ground_albedo.png    Texture2DArray, one slice per set: sRGB base colour, A = height
    images/ground/ground_nrm.png       Texture2DArray: RG = normal xy (OpenGL), B = roughness, A = AO
    images/ground/ground_masks.png     the two mask images, as they are
    images/ground/ground_masks2.png
    images/ground/ground.json          slice order, metres per tile, average colour / roughness per
                                       slice (the far shading), mask grid

Slices sit in a 5 x 2 grid of SIZE px (default 2048); the .import files make Godot import them as
VRAM-compressed (BPTC) texture arrays with mipmaps. Slice 9 is the road concrete (city land).

    python tools/godot/pack_ground.py [--out game/assets/world] [--size 2048] [--force]
"""
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SETS = ["grass_turf", "dirt_mud", "cracked_mud", "forest_floor", "scree", "rock_cliff", "beach_sand", "cobbles", "vacant_lot", "concrete"]
TILE_M = {"rock_cliff": 4.0, "scree": 2.0, "forest_floor": 2.0, "grass_turf": 2.0, "dirt_mud": 4.0, "beach_sand": 4.0,
          "cracked_mud": 3.0, "cobbles": 2.0, "vacant_lot": 4.0, "concrete": 2.0}
GRID = (5, 2)

ARRAY_IMPORT = """[remap]

importer="2d_array_texture"
type="CompressedTexture2DArray"

[deps]

source_file="{res}"

[params]

compress/mode=2
compress/high_quality=true
compress/lossy_quality=0.7
compress/hdr_compression=1
compress/channel_pack={pack}
mipmaps/generate=true
mipmaps/limit=-1
slices/horizontal={h}
slices/vertical={v}
"""

MASK_IMPORT = """[remap]

importer="texture"
type="CompressedTexture2D"

[deps]

source_file="{res}"

[params]

compress/mode=0
compress/high_quality=false
compress/lossy_quality=0.7
compress/hdr_compression=1
compress/normal_map=2
compress/channel_pack=1
mipmaps/generate=true
mipmaps/limit=-1
roughness/mode=0
roughness/src_normal=""
process/fix_alpha_border=false
process/premult_alpha=false
process/normal_map_invert_y=false
process/hdr_as_srgb=false
process/hdr_clamp_exposure=false
process/size_limit=0
detect_3d/compress_to=0
"""


def opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else True
    return default


def res_path(p):
    rel = os.path.relpath(p, os.path.join(ROOT, "game")).replace("\\", "/")
    return "res://" + rel


def src_dir(name):
    if name == "concrete":
        return os.path.join(ROOT, "scenes", "town", "textures", "roads", "concrete")
    return os.path.join(ROOT, "scenes", "town", "textures", "world", name)


def load(path, mode, size, default=None):
    if not os.path.isfile(path):
        return default
    im = Image.open(path)
    if im.mode in ("I;16", "I"):
        im = Image.fromarray((np.asarray(im, dtype=np.float32) / 257.0).clip(0, 255).astype(np.uint8))
    im = im.convert(mode)
    if im.size[0] != size:
        im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im)


def pack(out, size=2048, force=False):
    dst = os.path.join(out, "images", "ground")
    os.makedirs(dst, exist_ok=True)
    have = [s for s in SETS if os.path.isfile(os.path.join(src_dir(s), f"{s}_BaseColor.png"))]
    if len(have) < len(SETS):
        print("ground: missing sets", sorted(set(SETS) - set(have)), "(python tools/ground_textures.py)")
        return False
    newest = max(os.path.getmtime(os.path.join(src_dir(s), f)) for s in SETS for f in os.listdir(src_dir(s)))
    alb_p, nrm_p = os.path.join(dst, "ground_albedo.png"), os.path.join(dst, "ground_nrm.png")
    meta = {"layers": SETS, "tile_m": [TILE_M[s] for s in SETS], "avg": [], "grid": GRID, "size": size}
    if force or not os.path.isfile(alb_p) or os.path.getmtime(alb_p) < newest:
        W, H = GRID[0] * size, GRID[1] * size
        alb = np.zeros((H, W, 4), np.uint8)
        nrm = np.zeros((H, W, 4), np.uint8)
        for k, s in enumerate(SETS):
            d = src_dir(s)
            f = lambda m: os.path.join(d, f"{s}_{m}.png")
            c = load(f("BaseColor"), "RGB", size)
            h = load(f("Height"), "L", size, np.full((size, size), 128, np.uint8))
            n = load(f("Normal_OpenGL"), "RGB", size, np.full((size, size, 3), 128, np.uint8))
            r = load(f("Roughness"), "L", size, np.full((size, size), 200, np.uint8))
            ao = load(f("AO"), "L", size, np.full((size, size), 255, np.uint8))
            gx, gy = k % GRID[0], k // GRID[0]
            sl = (slice(gy * size, (gy + 1) * size), slice(gx * size, (gx + 1) * size))
            alb[sl] = np.dstack([c, h])
            nrm[sl] = np.dstack([n[..., 0], n[..., 1], r, ao])
            lin = (c.astype(np.float32) / 255.0) ** 2.2
            meta["avg"].append([round(float(x), 4) for x in lin.reshape(-1, 3).mean(0)] + [round(float(r.mean()) / 255.0, 3)])
            print(f"  ground slice {k}: {s}")
        Image.fromarray(alb, "RGBA").save(alb_p, compress_level=6)
        Image.fromarray(nrm, "RGBA").save(nrm_p, compress_level=6)
        for p, pk in ((alb_p, 0), (nrm_p, 1)):
            with open(p + ".import", "w", encoding="utf-8") as fh:
                fh.write(ARRAY_IMPORT.format(res=res_path(p), h=GRID[0], v=GRID[1], pack=pk))
        json.dump(meta, open(os.path.join(dst, "ground_avg.json"), "w"), indent=1)
    else:
        meta = json.load(open(os.path.join(dst, "ground_avg.json")))
    # masks (+ their grid) and the camera spots for --bench-spots
    md = next((d for d in (os.path.join(ROOT, "scenes", "world"), out) if os.path.isfile(os.path.join(d, "ground_masks.png"))), None)
    if md is None:
        print("ground: no masks (python tools/world/ground_masks.py)")
    else:
        for fn in ("ground_masks.png", "ground_masks2.png"):
            p = os.path.join(dst, fn)
            if force or not os.path.isfile(p) or os.path.getmtime(p) < os.path.getmtime(os.path.join(md, fn)):
                shutil.copyfile(os.path.join(md, fn), p)
            if not os.path.isfile(p + ".import"):
                open(p + ".import", "w", encoding="utf-8").write(MASK_IMPORT.format(res=res_path(p)))
        meta["masks"] = json.load(open(os.path.join(md, "ground_masks.json")))
        sp = os.path.join(md, "ground_spots.json")
        if os.path.isfile(sp):
            shutil.copyfile(sp, os.path.join(out, "ground_spots.json"))
    json.dump(meta, open(os.path.join(dst, "ground.json"), "w"), indent=1)
    print(f"ground: {len(SETS)} slices ({size} px) -> {dst}")
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    out = os.path.abspath(str(opt(a, "--out", os.path.join(ROOT, "game", "assets", "world"))))
    pack(out, int(opt(a, "--size", 2048)), bool(opt(a, "--force", False)))
