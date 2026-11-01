"""Pack every variant's impostor strip into one shared atlas (system Python: numpy, PIL).

    python tools/trees/impostor_atlas.py          # after build_trees.py

scenes/trees/impostors/<key>_{albedo,normal}.png (build_trees.py, git-ignored; 1024 x 256, 4 views) -> impostors/atlas_{albedo,normal}.png
(4096 x 4096: 4 strips per row, 16 rows = 64 variants) and, per variant in index.json,
"impostor": {cell, size_v (vertical quad side), size_t (top quad side), height, center [x, y] (Blender)}.
Godot draws all impostors of a 256 m region with ONE MultiMesh: a unit crossed-quad mesh scaled per
instance from INSTANCE_CUSTOM (tree_kit.gd / tree_impostor.gdshader), so species never split draws.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import species as S  # noqa: E402
import treegen as TG  # noqa: E402

COLS, ROWS = 4, 16


def bounds(key, sp, v, look):
    planter = key[5:] in S.PLANTER_SHRUBS
    sk = TG.grow_planter(key[5:]) if planter else TG.grow(sp, v)
    md = TG.build_lod(sk, 0, None, look)
    P = np.concatenate([md.arrays(m)["p"] for m in ("bark", "leaf") if md.arrays(m) is not None])
    cx = float((P[:, 0].min() + P[:, 0].max()) / 2)
    cy = float((P[:, 1].min() + P[:, 1].max()) / 2)
    R = float(np.max(np.hypot(P[:, 0] - cx, P[:, 1] - cy)))
    H = float(max(P[:, 2].max(), 0.5))
    return R, H, cx, cy


def main():
    out = ROOT / "assets" / "trees"
    idx_p = out / "index.json"
    idx = json.load(open(idx_p, encoding="utf-8"))
    al = Image.new("RGBA", (4096, 4096), (0, 0, 0, 0))
    nm = Image.new("RGBA", (4096, 4096), (128, 128, 255, 0))
    cell = 0
    for key, sp, v, look in S.variant_keys():
        if key not in idx["variants"]:
            continue
        pa = ROOT / "scenes" / "trees" / "impostors" / f"{key}_albedo.png"
        pn = ROOT / "scenes" / "trees" / "impostors" / f"{key}_normal.png"
        if not pa.exists():
            continue
        R, H, cx, cy = bounds(key, sp, v, look)
        col, row = cell % COLS, cell // COLS
        x, y = col * 1024, row * 256
        al.paste(Image.open(pa).convert("RGBA").resize((1024, 256)), (x, y))
        nm.paste(Image.open(pn).convert("RGBA").resize((1024, 256)), (x, y))
        idx["variants"][key]["impostor"] = {"cell": cell, "size_v": round(max(H, 2 * R) * 1.04, 3), "size_t": round(2 * R * 1.04, 3),
                                            "height": round(H, 3), "center": [round(cx, 3), round(cy, 3)]}
        f = idx["variants"][key]["files"]
        f["impostor_albedo"], f["impostor_normal"] = "impostors/atlas_albedo.png", "impostors/atlas_normal.png"
        cell += 1
    al.save(out / "impostors" / "atlas_albedo.png", optimize=True)
    nm.save(out / "impostors" / "atlas_normal.png", optimize=True)
    idx["impostor_atlas"] = {"albedo": "impostors/atlas_albedo.png", "normal": "impostors/atlas_normal.png", "cols": COLS, "rows": ROWS,
                             "strip": "4 views (azimuth 0, 60, 120 deg, top) of 1024 / 4 px; rows top-down in the image"}
    with open(idx_p, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)
    print(f"impostor atlas: {cell} variants")


if __name__ == "__main__":
    main()
