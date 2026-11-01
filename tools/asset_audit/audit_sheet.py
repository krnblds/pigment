"""Contact sheets from audit_render.py tiles.

    python tools/asset_audit/audit_sheet.py TILEDIR OUT.jpg [--groups props,town] [--cols 8] [--title "..."] [--tile 240] [--mark a,b]
    python tools/asset_audit/audit_sheet.py --pairs BEFOREDIR AFTERDIR OUT.jpg --ids world/container,... [--title ...] [--tile 360]

Grid mode: one tile per asset with its name, triangle count and a textured / UNTEXTURED tag;
--mark outlines the picked weak assets in red. Pairs mode: before | after side by side per id.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def arg(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else default


def font(sz):
    for f in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        if os.path.isfile(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def save(img, out):
    q = 88
    while True:
        img.convert("RGB").save(out, quality=q, optimize=True)
        if os.path.getsize(out) < 1_450_000 or q < 50:
            break
        q -= 6
    print(out, os.path.getsize(out) // 1024, "KB")


def grid(tdir, out):
    st = json.load(open(os.path.join(tdir, "stats.json")))
    groups = arg("--groups")
    order = groups.split(",") if groups else []
    ids = [k for k in st if not groups or st[k]["group"] in order]
    ids.sort(key=lambda k: order.index(st[k]["group"]) if st[k]["group"] in order else 0)
    cols = int(arg("--cols", 8))
    T = int(arg("--tile", 240))
    mark = set((arg("--mark") or "").split(","))
    lab = 40
    rows = (len(ids) + cols - 1) // cols
    head = 44
    img = Image.new("RGB", (cols * T, head + rows * (T + lab)), (14, 15, 18))
    d = ImageDraw.Draw(img)
    d.text((10, 8), arg("--title", "Asset audit"), fill=(235, 235, 235), font=font(22))
    f1, f2 = font(14), font(11)
    for i, k in enumerate(ids):
        s = st[k]
        x, y = (i % cols) * T, head + (i // cols) * (T + lab)
        im = Image.open(os.path.join(tdir, s["file"])).convert("RGB").resize((T, T), Image.LANCZOS)
        img.paste(im, (x, y))
        if k in mark:
            d.rectangle([x + 1, y + 1, x + T - 2, y + T + lab - 2], outline=(230, 40, 40), width=4)
        d.text((x + 6, y + T + 2), s["label"][:34], fill=(240, 240, 240), font=f1)
        tag = "textured" if s["textured"] else "UNTEXTURED"
        col = (140, 170, 200) if s["textured"] else (240, 120, 90)
        d.text((x + 6, y + T + 21), f"{s['group']}  {s['tris']:,} tris  {tag}", fill=col, font=f2)
    save(img, out)


def pairs(bdir, adir, out):
    bs = json.load(open(os.path.join(bdir, "stats.json")))
    as_ = json.load(open(os.path.join(adir, "stats.json")))
    ids = arg("--ids").split(",")
    T = int(arg("--tile", 360))
    lab = 30
    head = 44
    cols = int(arg("--cols", 2))     # pairs per row
    rows = (len(ids) + cols - 1) // cols
    W = cols * (2 * T + 12)
    img = Image.new("RGB", (W, head + rows * (T + lab + 8)), (14, 15, 18))
    d = ImageDraw.Draw(img)
    d.text((10, 8), arg("--title", "Before | after"), fill=(235, 235, 235), font=font(22))
    f1 = font(14)
    for i, k in enumerate(ids):
        x0 = (i % cols) * (2 * T + 12)
        y = head + (i // cols) * (T + lab + 8)
        for j, (dd, st, tag) in enumerate(((bdir, bs, "before"), (adir, as_, "after"))):
            s = st.get(k)
            x = x0 + j * T
            if s is None:
                d.text((x + 10, y + T // 2), f"{k}: no {tag} tile", fill=(200, 80, 80), font=f1)
                continue
            im = Image.open(os.path.join(dd, s["file"])).convert("RGB").resize((T, T), Image.LANCZOS)
            img.paste(im, (x, y))
            d.text((x + 6, y + T + 4), f"{tag}: {s['label']}  {s['tris']:,} tris", fill=(240, 240, 240) if j else (170, 170, 170), font=f1)
    save(img, out)


if "--pairs" in sys.argv:
    i = sys.argv.index("--pairs")
    pairs(sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3])
else:
    grid(sys.argv[1], sys.argv[2])
