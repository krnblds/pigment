"""Write assets/props/index.json and the variant texture swaps (system Python + PIL).

    python tools/props/write_index.py

Reads tools/props/catalog.py, assets/props/src/<name>.json (+ _export.json from
export_props.py), scenes/props/textures/variants.json and the Pigment variant folders.
Variant swaps go to assets/props/variants/<name>__<variant>_albedo.(jpg|png) and
_emission.jpg at the prop's embed size: put them on the prop material's albedo /
emission textures to get that variant (roughness, normals etc. are shared).
"""
import json
import os
import struct
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import catalog  # noqa: E402

SRC = os.path.join(ROOT, "assets", "props", "src")
OUT = os.path.join(ROOT, "assets", "props")
VAR = os.path.join(OUT, "variants")
TEX = os.path.join(ROOT, "scenes", "props", "textures")


def glb_json(path):
    with open(path, "rb") as f:
        f.read(12)
        ln, _ = struct.unpack("<II", f.read(8))
        return json.loads(f.read(ln))


def variant_maps(name, folder, vname, size):
    base = os.path.join(folder, f"{name}_BaseColor.png")
    if not os.path.exists(base):
        return None
    im = Image.open(base).convert("RGB")
    op = os.path.join(folder, f"{name}_Opacity.png")
    out = {}
    os.makedirs(VAR, exist_ok=True)
    if os.path.exists(op):
        im = im.convert("RGBA")
        im.putalpha(Image.open(op).convert("L"))
        im = im.resize((size, size), Image.LANCZOS)
        fn = f"{name}__{vname}_albedo.png"
        im.save(os.path.join(VAR, fn), optimize=True)
    else:
        im = im.resize((size, size), Image.LANCZOS)
        fn = f"{name}__{vname}_albedo.jpg"
        im.save(os.path.join(VAR, fn), quality=85)
    out["albedo"] = f"variants/{fn}"
    em = os.path.join(folder, f"{name}_Emissive.png")
    if os.path.exists(em):
        fn = f"{name}__{vname}_emission.jpg"
        Image.open(em).convert("RGB").resize((size, size), Image.LANCZOS).save(os.path.join(VAR, fn), quality=85)
        out["emission"] = f"variants/{fn}"
    for side in ("variant.json", "material.json"):
        p = os.path.join(folder, side)
        if os.path.exists(p):
            j = json.load(open(p))
            if "emissive_scale" in j:
                out["emissive_scale"] = j["emissive_scale"]
                break
    return out


def main():
    vinfo = json.load(open(os.path.join(TEX, "variants.json"))) if os.path.exists(os.path.join(TEX, "variants.json")) else {}
    props = {}
    total = 0
    for name, info in catalog.PROPS.items():
        sp = os.path.join(SRC, f"{name}.json")
        ep = os.path.join(SRC, f"{name}_export.json")
        if not (os.path.exists(sp) and os.path.exists(ep)):
            print(f"[write_index] skip {name}: not exported")
            continue
        src, ex = json.load(open(sp)), json.load(open(ep))
        g = glb_json(os.path.join(OUT, ex["lod0"]))
        alpha = sorted({m.get("alphaMode", "OPAQUE") for m in g.get("materials", [])})
        node_names = [n["name"] for n in g["nodes"]]
        total += ex["lod0_bytes"] + ex.get("lod1_bytes", 0)
        lo, hi = src["bounds_gl"]["min"], src["bounds_gl"]["max"]
        w, d = hi[0] - lo[0], hi[2] - lo[2]
        vi = vinfo.get(name, {})
        variants = [{"name": vi.get("default", "default"), "default": True}]
        for v in vi.get("variants", []):
            m = variant_maps(name, os.path.join(TEX, f"{name}__{v}"), v, info["embed"])
            if m:
                variants.append(dict(name=v, **m))
                total += sum(os.path.getsize(os.path.join(OUT, m[k])) for k in ("albedo", "emission") if k in m)
        mount = info.get("mount") or ("span" if info.get("span") else "ground")
        lod = {"lod0_tris": ex["lod0_tris"]}
        if "lod1" in ex:
            ext = max(src["size_m"])
            lod.update(lod1_tris=ex["lod1_tris"], lod1_from_m=round(max(20.0, ext * 9), 1))
        lod["visible_to_m"] = round(max(60.0, max(src["size_m"]) * 45), 1)
        props[name] = {
            "title": info["title"], "category": info["category"], "desc": info["desc"],
            "files": {k: ex[k] for k in ("lod0", "lod1") if k in ex},
            "lod": lod,
            "size_m": src["size_m"],
            "footprint": {"w": round(w, 3), "d": round(d, 3), "radius": round(((w / 2) ** 2 + (d / 2) ** 2) ** 0.5, 3),
                          "center": [round((lo[0] + hi[0]) / 2, 3), round((lo[2] + hi[2]) / 2, 3)]},
            "bounds": src["bounds_gl"],
            "mount": mount,
            "nodes": {"main": node_names[0] if node_names else name, "all": node_names, "driven": src["nodes"]},
            "collider": {"type": ("none" if src["collider"][0]["type"] == "none" else
                                  "convex" if src["collider"][0]["type"] == "convex" else
                                  src["collider"][0]["type"] if len(src["collider"]) == 1 else "compound"),
                         "shapes": [s for s in src["collider"] if s["type"] not in ("none", "convex")], "node": "Collider"},
            "lights": src["lights"],
            "sockets": [s for s in src["sockets"] if s["kind"] != "signal_lamp"],
            "material": {"alpha": alpha, "texture": ex["texture"], "texels_per_m": src["texels_per_m"],
                         "emissive": any("emissiveTexture" in m for m in g.get("materials", []))},
            "variants": variants,
            "scatter": info["scatter"],
        }
        for k in ("tile_length", "span"):
            if k in info:
                props[name][k] = info[k]
        if src["meta"].get("signals"):
            sig = dict(src["meta"]["signals"])
            sig["lamp_positions"] = {s["name"]: {"pos": s["pos"], "dir": s["dir"], "color": s["color"]} for s in src["sockets"] if s["kind"] == "signal_lamp"}
            sig["lit_colors"] = {"red": [1.0, 0.08, 0.04], "amber": [1.0, 0.55, 0.05], "green": [0.1, 1.0, 0.65], "walk": [0.2, 1.0, 0.55], "stop": [1.0, 0.18, 0.08]}
            sig["how_to_drive"] = ("Every lamp node shares the prop material and its emissive texels show the lit lens. To switch a lamp off, give "
                                   "that node a material override with emission disabled (or emission_energy_multiplier = 0); to switch it on, "
                                   "restore the shared material. Optional: an OmniLight3D at lamp_positions[name] tinted lit_colors[color].")
            props[name]["signals"] = sig
    index = {
        "version": 1,
        "generator": "tools/props (build_props.py -> props_textures.py -> export_props.py -> write_index.py)",
        "conventions": {
            "axes": "glTF / Godot: +Y up, metres; every prop faces +Z (its front). +X is on the right of a viewer standing in "
                    "front of the prop (e.g. the mast arm reaches out to +X). Yaw = atan2(front.x, front.z) turns +Z onto a front direction.",
            "origin": "ground: on the ground at the footprint centre. wall: on the wall plane at the mount point (the prop sticks out along +Z). "
                      "span: midpoint between the two attachment points (scale X to the gap; the cables sag below it).",
            "nodes": "First node = the main mesh (named like the prop). Driven nodes (traffic lamps) are separate meshes with the same "
                     "material. 'Collider' is a hidden mesh (extras: collider, shapes); use index collider.shapes for primitive shapes. "
                     "Light_* empties carry extras {light, color, energy (W-ish), range}; local -Z is a spot's direction. Socket_* empties "
                     "mark particle emitters (steam, smoke).",
            "materials": "One Pigment material per prop (base colour, ORM, normal, emissive with KHR_materials_emissive_strength). "
                         "alpha BLEND = glass / holo / cut-outs: in Godot use transparency Alpha Depth Pre-Pass (or Alpha Scissor for "
                         "cut-out-only props such as puddles and grilles).",
            "variants": "Swap the material's albedo (and emission) textures for variants/<prop>__<variant>_*; other maps are shared.",
            "lod": "Switch to files.lod1 beyond lod.lod1_from_m; hide beyond lod.visible_to_m (visibility_range_end).",
        },
        "districts": catalog.DISTRICTS,
        "slots": catalog.SLOTS,
        "scatter_fields": catalog.SCATTER_DOC,
        "total_bytes": total,
        "props": props,
    }
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf8") as f:
        json.dump(index, f, indent=1, ensure_ascii=False)
    print(f"[write_index] {len(props)} props, {total / 1e6:.1f} MB of glbs + variant textures")


if __name__ == "__main__":
    main()
