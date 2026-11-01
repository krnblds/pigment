"""Tree kit textures, authored in Pigment (pigment-mcp --script).

    python tools/trees/stencils.py                 # leaf / bark shapes first
    python tools/trees/tree_textures.py            # write the scripts
    python tools/trees/tree_textures.py --run      # ...and run them (atlas ~2 min, bark ~20 s each)
    python tools/trees/tree_textures.py --run leaves bark_pine

Scripts: scenes/trees/scripts/<name>.jsonl (committed). Output (git-ignored):
scenes/trees/textures/<name>/ and scenes/trees/projects/<name>.pigment.

    leaves       decal atlas project (one cell per LEAF_CELLS entry, 4096): every cell gets
                 its colour stencil as a decal (base colour, roughness, opacity), the relief
                 stencil into height (normals), the blade stencil into transmission (the
                 translucency hint for the game), then tone variation, sun-bleached and
                 browned leaves, city dust and a wet sheen as generator-masked fills.
    bark_<sp>    seamless bark tile (tile mode, size from species.BARK): the relief as an image
                 fill into height, the colour detail as the base, furrows / ridges as fills
                 masked by the stencils (projected into the masks), lichen, moss, tone, grime.
tools/trees/build_trees.py packs the exports into assets/trees/textures/.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
from species import LEAF_CELLS, BARK  # noqa: E402

SCRIPTS = ROOT / "scenes" / "trees" / "scripts"
ST = "scenes/trees/stencils"
TEX = "scenes/trees/textures"
PROJ = "scenes/trees/projects"
MCP = Path(os.environ.get("PIGMENT_MCP", ROOT / "target" / "release" / "pigment-mcp.exe"))


def L(tool, **args):
    return {"tool": tool, "args": args}


# per cell: roughness, translucency, tone colour (yellowed / sun-bleached), dry-edge colour
LEAF_LOOK = {
    "pagoda_spray": dict(rough=0.5, trans=0.55, tone=[0.42, 0.5, 0.16], dry=[0.45, 0.38, 0.16]),
    "pagoda_spray_b": dict(rough=0.5, trans=0.55, tone=[0.4, 0.52, 0.18], dry=[0.45, 0.38, 0.16]),
    "zelkova_spray": dict(rough=0.55, trans=0.5, tone=[0.45, 0.5, 0.18], dry=[0.5, 0.36, 0.14]),
    "zelkova_spray_b": dict(rough=0.55, trans=0.5, tone=[0.4, 0.48, 0.15], dry=[0.5, 0.36, 0.14]),
    "ginkgo_spray": dict(rough=0.5, trans=0.6, tone=[0.55, 0.6, 0.2], dry=[0.6, 0.5, 0.15]),
    "ginkgo_gold": dict(rough=0.55, trans=0.65, tone=[0.95, 0.78, 0.2], dry=[0.6, 0.4, 0.1]),
    "cherry_blossom": dict(rough=0.6, trans=0.75, tone=[1.0, 0.8, 0.86], dry=[0.8, 0.62, 0.62]),
    "cherry_green": dict(rough=0.45, trans=0.5, tone=[0.36, 0.45, 0.14], dry=[0.5, 0.3, 0.12]),
    "pine_tuft": dict(rough=0.42, trans=0.25, tone=[0.2, 0.3, 0.14], dry=[0.42, 0.32, 0.15]),
    "cedar_spray": dict(rough=0.6, trans=0.3, tone=[0.3, 0.32, 0.14], dry=[0.45, 0.3, 0.15]),
    "palm_frond": dict(rough=0.4, trans=0.45, tone=[0.42, 0.45, 0.16], dry=[0.55, 0.45, 0.22]),
    "azalea": dict(rough=0.35, trans=0.4, tone=[0.25, 0.35, 0.12], dry=[0.4, 0.32, 0.12]),
    "azalea_bloom": dict(rough=0.4, trans=0.55, tone=[0.9, 0.3, 0.6], dry=[0.4, 0.32, 0.12]),
    "box_leaves": dict(rough=0.38, trans=0.35, tone=[0.25, 0.36, 0.1], dry=[0.42, 0.36, 0.14]),
}


def leaves():
    cells = list(LEAF_CELLS.items())
    s = [L("new_project", tile={"name": "leaves", "cells": [{"name": n, "size_m": sz} for n, sz in cells], "padding_px": 20, "folders": False},
           resolution=4096)]
    s.append(L("delete_layer", layer="Paint"))
    # under the transparent texels: a dark leaf green, so mip / filter edges stay green, not white
    s.append(L("update_layer", layer="Base", values={"base_color": [0.08, 0.13, 0.05], "roughness": 0.6, "metallic": 0.0, "opacity": 0.0}))
    add = lambda **a: s.append(L("add_layer", **a))
    dec = lambda **a: s.append(L("project_decal", **a))
    # one paint layer holds every cell's decals (a 4096 atlas with a layer stack per cell runs
    # out of GPU memory on a shared card); the material look is global fills over all cells
    s.append(L("add_layer", kind="paint", name="Cards"))
    for i, (n, sz) in enumerate(cells):
        lk = LEAF_LOOK[n]
        at = {"part": i, "face": "top", "anchor": [0.5, 0.5], "size": sz, "layer": "Cards"}
        dec(image=f"{ST}/leaf_{n}_color.png", **at,
            values={"roughness": lk["rough"], "metallic": 0.0, "opacity": 1.0}, channels=["base_color", "roughness", "metallic", "opacity"])
        dec(image=f"{ST}/leaf_{n}_relief.png", **at, alpha_from_luminance=True, height=0.8, channels=["height"])
        dec(image=f"{ST}/leaf_{n}_blade.png", **at, values={"transmission": lk["trans"]}, channels=["transmission"])
    # Pigment's look on top: tone variation, dry / sun-scorched patches, city dust, a wet sheen
    add(name="Tone", values={"base_color": [0.5, 0.52, 0.2]}, opacity=0.22,
        channels={"base_color": True, "roughness": False, "metallic": False, "height": False},
        mask={"generator": "grunge", "amount": 0.45, "scale": 6.0, "softness": 0.35, "seed": 300})
    add(name="Dry", values={"base_color": [0.45, 0.36, 0.15], "roughness": 0.75}, opacity=0.3,
        channels={"base_color": True, "roughness": True, "metallic": False, "height": False},
        mask={"generator": "spots", "amount": 0.1, "scale": 22.0, "softness": 0.2, "seed": 320})
    add(name="City dust", material="Grime", opacity=0.14,
        channels={"base_color": True, "roughness": True, "metallic": False, "height": False},
        mask={"generator": "grunge", "amount": 0.35, "scale": 12.0, "softness": 0.3, "seed": 340})
    add(name="Wet sheen", values={"roughness": 0.18}, opacity=0.45,
        channels={"base_color": False, "roughness": True, "metallic": False, "height": False},
        mask={"generator": "grunge", "amount": 0.4, "scale": 9.0, "softness": 0.4, "seed": 360})
    s += [
        L("render", yaw=0, pitch=89.9, zoom=1.0, width=1400, height=1400, background=False, path="target/trees/leaves_render.png"),
        L("export_textures", dir=f"{TEX}/leaves", name="leaves", preset="separate"),
        L("save_project", path=f"{PROJ}/leaves.pigment"),
    ]
    return s


# per species: base colour, furrow colour, ridge colour, roughness, moss / lichen amounts, relief strength
BARK_LOOK = {
    "pagoda": dict(base=[0.34, 0.31, 0.27], furrow=[0.08, 0.065, 0.055], ridge=[0.5, 0.48, 0.44], rough=0.88, lichen=0.22, moss=0.12, h=1.0),
    "zelkova": dict(base=[0.4, 0.39, 0.36], furrow=[0.3, 0.2, 0.13], ridge=[0.55, 0.54, 0.5], rough=0.75, lichen=0.3, moss=0.06, h=0.5),
    "ginkgo": dict(base=[0.38, 0.34, 0.29], furrow=[0.1, 0.085, 0.07], ridge=[0.52, 0.49, 0.43], rough=0.9, lichen=0.18, moss=0.1, h=1.0),
    "cherry": dict(base=[0.3, 0.19, 0.17], furrow=[0.12, 0.07, 0.06], ridge=[0.45, 0.36, 0.33], rough=0.48, lichen=0.2, moss=0.08, h=0.45),
    "pine": dict(base=[0.24, 0.22, 0.21], furrow=[0.14, 0.07, 0.045], ridge=[0.4, 0.38, 0.36], rough=0.9, lichen=0.15, moss=0.1, h=1.0),
    "cedar": dict(base=[0.44, 0.27, 0.18], furrow=[0.17, 0.1, 0.07], ridge=[0.56, 0.43, 0.33], rough=0.92, lichen=0.12, moss=0.16, h=0.8),
    "palm": dict(base=[0.42, 0.36, 0.27], furrow=[0.16, 0.12, 0.09], ridge=[0.56, 0.5, 0.4], rough=0.92, lichen=0.05, moss=0.0, h=0.9),
}


def bark(sp):
    lk = BARK_LOOK[sp]
    s = [L("new_project", tile={"size_m": BARK[sp], "name": f"bark_{sp}"}, resolution=1024)]
    s.append(L("delete_layer", layer="Paint"))
    s.append(L("update_layer", layer="Base", values={"base_color": lk["base"], "roughness": lk["rough"], "metallic": 0.0},
               image={"base_color": f"{ST}/bark_{sp}_color.png", "projection": "uv", "tiling": 1, "tint": [1.0, 1.0, 1.0]}))
    add = lambda **a: s.append(L("add_layer", **a))
    dec = lambda **a: s.append(L("project_decal", **a))
    whole = {"part": 0, "fit": "fill", "margin": 0.0}
    add(name="Relief", image={"height": f"{ST}/bark_{sp}_height.png", "projection": "uv", "tiling": 1, "height_scale": lk["h"]},
        channels={"base_color": False, "roughness": False, "metallic": False, "height": True})
    add(name="Tint", values={"base_color": lk["base"]}, opacity=1.0, blend={"base_color": "multiply"},
        channels={"base_color": True, "roughness": False, "metallic": False, "height": False})
    add(name="Furrows", values={"base_color": lk["furrow"], "roughness": 0.97}, mask="black",
        channels={"base_color": True, "roughness": True, "metallic": False, "height": False})
    dec(image=f"{ST}/bark_{sp}_cavity.png", layer="Furrows", mask=True, mask_value="white", **whole)
    add(name="Ridges", values={"base_color": lk["ridge"], "roughness": min(0.95, lk["rough"] + 0.04)}, opacity=0.7, mask="black",
        channels={"base_color": True, "roughness": True, "metallic": False, "height": False})
    dec(image=f"{ST}/bark_{sp}_ridge.png", layer="Ridges", mask=True, mask_value="white", **whole)
    add(name="Tone", values={"base_color": [x * 0.7 for x in lk["base"]]}, opacity=0.35,
        channels={"base_color": True, "roughness": False, "metallic": False, "height": False},
        mask={"generator": "grunge", "amount": 0.45, "scale": 1.5, "softness": 0.4, "seed": 11})
    if lk["lichen"]:
        add(name="Lichen", values={"base_color": [0.5, 0.55, 0.45], "roughness": 0.95, "height": 0.08}, opacity=0.45,
            mask={"generator": "spots", "amount": lk["lichen"] * 0.7, "scale": 24.0, "softness": 0.15, "seed": 21})
    if lk["moss"]:
        add(name="Moss", values={"base_color": [0.12, 0.2, 0.06], "roughness": 0.98, "height": 0.12}, opacity=0.8,
            mask={"generator": "moss", "amount": lk["moss"], "scale": 3.0, "breakup": 0.8, "seed": 31})
    add(name="Rain streaks", material="Grime", opacity=0.3, channels={"height": False, "metallic": False},
        mask={"generator": "streaks", "amount": 0.35, "scale": 2.0, "softness": 0.3, "seed": 41})
    add(name="City soot", values={"base_color": [0.06, 0.06, 0.06], "roughness": 0.9}, opacity=0.18,
        channels={"base_color": True, "roughness": True, "metallic": False, "height": False},
        mask={"generator": "grunge", "amount": 0.4, "scale": 3.5, "softness": 0.35, "seed": 51})
    s += [
        L("render", yaw=0, pitch=89.9, zoom=1.0, width=600, height=600, background=False, path=f"target/trees/bark_{sp}_render.png"),
        L("export_textures", dir=f"{TEX}/bark_{sp}", name=f"bark_{sp}", preset="separate"),
        L("save_project", path=f"{PROJ}/bark_{sp}.pigment"),
    ]
    return s


def write(name, lines):
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    p = SCRIPTS / f"{name}.jsonl"
    p.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    return p


def pack():
    """Pigment exports -> assets/trees/textures/ (committed; what Blender and Godot load):
    bark_<sp>_{albedo,normal,rough}.jpg (1024), leaves_albedo.png (RGBA 4096, alpha = cut-out),
    leaves_normal.jpg (4096), leaves_mask.jpg (2048: R roughness, G translucency), leaves_layout.json."""
    from PIL import Image
    out = ROOT / "assets" / "trees" / "textures"
    out.mkdir(parents=True, exist_ok=True)
    T = ROOT / TEX
    for sp in BARK:
        d = T / f"bark_{sp}"
        Image.open(d / f"bark_{sp}_BaseColor.png").convert("RGB").save(out / f"bark_{sp}_albedo.jpg", quality=90)
        Image.open(d / f"bark_{sp}_Normal_OpenGL.png").convert("RGB").save(out / f"bark_{sp}_normal.jpg", quality=92)
        Image.open(d / f"bark_{sp}_Roughness.png").convert("L").save(out / f"bark_{sp}_rough.jpg", quality=90)
    d = T / "leaves"
    Image.open(d / "leaves_BaseColorAlpha.png").convert("RGBA").save(out / "leaves_albedo.png", optimize=True)
    Image.open(d / "leaves_Normal_OpenGL.png").convert("RGB").save(out / "leaves_normal.jpg", quality=90)
    r = Image.open(d / "leaves_Roughness.png").convert("L").resize((2048, 2048), Image.LANCZOS)
    t = Image.open(d / "leaves_Transmission.png").convert("L").resize((2048, 2048), Image.LANCZOS)
    z = Image.new("L", (2048, 2048), 0)
    Image.merge("RGB", (r, t, z)).save(out / "leaves_mask.jpg", quality=92)
    import shutil
    shutil.copyfile(d / "leaves_layout.json", out / "leaves_layout.json")
    tot = sum(f.stat().st_size for f in out.iterdir())
    print(f"packed -> {out} ({tot / 1e6:.1f} MB)")


def main():
    scripts = {"leaves": leaves()}
    for sp in BARK:
        scripts[f"bark_{sp}"] = bark(sp)
    paths = {n: write(n, l) for n, l in scripts.items()}
    print("wrote", len(paths), "scripts ->", SCRIPTS)
    if "--run" in sys.argv:
        want = [a for a in sys.argv[1:] if not a.startswith("--")] or list(paths)
        (ROOT / "target" / "trees").mkdir(parents=True, exist_ok=True)
        for n in want:
            print(f"--- {n}", flush=True)
            r = subprocess.run([str(MCP), "--script", str(paths[n])], cwd=ROOT, capture_output=True, text=True)
            import re
            m = re.search(r"script: \d+ of \d+ steps run, (\d+) failed", r.stderr)
            if r.returncode != 0 or not m or int(m.group(1)) > 0:
                print(r.stdout[-4000:], r.stderr[-4000:])
                sys.exit(f"{n} failed")
            print("\n".join(l for l in r.stderr.splitlines() if l.startswith(("script:", "  slowest"))), flush=True)


if __name__ == "__main__":
    main()
