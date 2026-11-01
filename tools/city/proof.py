"""Hot-swap proof: change an asset while Godot runs with --live, capture before / after from the
same camera, and time change -> rebuild -> swap acknowledged.

    python -m tools.city.proof [scenario ...] [--out docs/agents/citybuild] [--keep]

Scenarios (each edits a source, builds with hot swap, screenshots, then reverts the edit and
builds again, which restores the old outputs from the content-addressed cache):
    decal     assets/decals/story/billboard_noctis.png gets a "HOT SWAP" band: the tower-crown
              billboards (image material) swap directly; the Pigment variants that show it are
              re-exported on the fast path (watch --fast)
    recipe    city/models/building/building_b.toml gets a [pigment] patch (LED strips cyan / pink -> green / amber):
              building_b's Pigment script re-runs, its 7 variant sets are packed and swapped
    prop      city/models/prop/bollard.toml mesh param height 0.96 -> 1.6: mesh, Pigment,
              export, world glb, swap
Godot is started with a window (it renders the screenshots) and closed at the end.
Results go to <out>/proof.json and <out>/<scenario>_before_after.png.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import cache, engine as E, live, manifest as M, paths, rules

ROOT = paths.ROOT
OUT = ROOT / "docs" / "agents" / "citybuild"


def _world():
    return json.loads((ROOT / "scenes/world/world.json").read_text(encoding="utf-8"))


def gd(p):
    """Blender (x, y, z) -> Godot (x, z, -y)."""
    return [p[0], p[2], -p[1]]


def view_of_instance(asset, near=None, dist=26.0, height=9.0, look_up=7.0, side=0.0, pick=0):
    """A camera in front of the `pick`-th instance of an asset (nearest to `near`), looking at it."""
    import math
    W = _world()
    inst = [i for i in W["instances"] if i["asset"] == asset]
    if near is not None:
        inst.sort(key=lambda i: (i["pos"][0] - near[0]) ** 2 + (i["pos"][1] - near[1]) ** 2)
    i = inst[pick]
    x, y, z = i["pos"]
    r = i.get("rot", 0.0)
    fx, fy = math.sin(r), -math.cos(r)            # local -Y (the front) turned by rot
    rx, ry = -fy, fx
    cam = [x + fx * dist + rx * side, y + fy * dist + ry * side, z + height]
    look = [x, y, z + look_up]
    return {"pos": gd(cam), "look": gd(look), "fov": 60, "instance": i}


def view_of_tower_crown(name_prefix="tower_", crown="billboard"):
    """A camera looking up at a billboard tower crown near the spawn."""
    W = _world()
    sp = W["spawn"]["pos"]
    towers = [t for t in W.get("towers", []) if t.get("crown") == crown]
    towers.sort(key=lambda t: (t["pos"][0] - sp[0]) ** 2 + (t["pos"][1] - sp[1]) ** 2)
    t = towers[0]
    x, y, z = t["pos"]
    h = t["height"]
    cam = [x + 0.0, y - 75.0, z + h * 0.85]
    return {"pos": gd(cam), "look": gd([x, y, z + h * 0.92]), "fov": 50, "tower": t["id"] if "id" in t else t.get("mesh")}


# ---------------------------------------------------------------- Godot
class Godot:
    def __init__(self, args=("--live", "--no-traffic", "--no-rain")):
        exe = paths.godot()
        if not exe:
            raise SystemExit("Godot not found (CITY_GODOT)")
        self.log = open(paths.CACHE / "godot_live.log", "w", encoding="utf-8", errors="replace")
        (paths.LIVE / "alive").unlink(missing_ok=True)
        self.p = subprocess.Popen([exe, "--path", str(ROOT / "game"), "--", *args], cwd=str(ROOT),
                                  stdout=self.log, stderr=subprocess.STDOUT)
        t0 = time.time()
        while not live.godot_listening():
            if self.p.poll() is not None:
                raise SystemExit("Godot exited early (see .citycache/godot_live.log)")
            if time.time() - t0 > 180:
                raise SystemExit("Godot live link did not come up")
            time.sleep(0.5)
        # wait for the town
        while True:
            a = live.send([{"type": "ping"}], wait=True, timeout=30)[0]
            if a.get("town"):
                break
            time.sleep(1.0)
        self.startup_s = time.time() - t0

    def send(self, e, timeout=120):
        return live.send([e], wait=True, timeout=timeout)[0]

    def shot(self, path, frames=30):
        return self.send({"type": "screenshot", "path": str(path), "frames": frames}, timeout=120)

    def close(self):
        try:
            self.p.terminate()
            self.p.wait(timeout=20)
        except Exception:
            self.p.kill()
        self.log.close()


# ---------------------------------------------------------------- build + swap, timed
def build_and_swap(targets, fast=False, label=""):
    """Build `targets` (+ upstream) and hot-swap as each node finishes. Returns timings."""
    t0 = time.time()
    g = rules.build_graph(M.load_all())
    ids = g.select(targets)
    acks = []
    first = {}

    def on_done(n, r):
        ev = live.events_for(r.get("changed", []))
        ev += [e for e in r.get("events", []) if e.get("type") == "material"]
        if ev:
            a = live.send(ev, wait=True, timeout=300)
            acks.extend(a)
            first.setdefault("t", time.time() - t0)

    import io
    buf = io.StringIO()
    eng = E.Engine(g, out=buf, fast=fast, on_done=on_done, keep_going=False)
    res = eng.build(ids)
    total = time.time() - t0
    ran = {n: round(r["seconds"], 1) for n, r in res.items() if r["state"] in ("built", "restored", "failed")}
    failed = [n for n, r in res.items() if r["state"] == "failed"]
    print(buf.getvalue())
    return {"label": label, "total_s": round(total, 1), "first_swap_s": round(first.get("t", 0), 1),
            "nodes": ran, "states": {s: sum(1 for r in res.values() if r["state"] == s) for s in
                                     {r["state"] for r in res.values()}},
            "acks": len(acks), "acks_ok": sum(1 for a in acks if a.get("ok")),
            "swap_ms_max": max((a.get("ms", 0) for a in acks), default=0), "failed": failed}


def side_by_side(a, b, out, title_a="before", title_b="after", note=""):
    from PIL import Image, ImageDraw, ImageFont
    A, B = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    w = 960
    A = A.resize((w, int(A.height * w / A.width)))
    B = B.resize((w, int(B.height * w / B.width)))
    H = A.height + 34
    im = Image.new("RGB", (w * 2 + 8, H + (26 if note else 0)), (12, 12, 14))
    im.paste(A, (0, 34))
    im.paste(B, (w + 8, 34))
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("consola.ttf", 18)
    except Exception:
        f = ImageFont.load_default()
    d.text((10, 8), title_a, fill=(230, 230, 230), font=f)
    d.text((w + 18, 8), title_b, fill=(230, 230, 230), font=f)
    if note:
        d.text((10, H + 4), note, fill=(170, 170, 170), font=f)
    im.save(out, quality=88)


# ---------------------------------------------------------------- scenarios
def scenario_decal(G, out):
    src = ROOT / "assets/decals/story/billboard_noctis.png"
    backup = paths.CACHE / "proof_backup_billboard_noctis.png"
    shutil.copyfile(src, backup)
    view = view_of_tower_crown()
    G.send(dict(view, type="camera"))
    before = out / "decal_before.png"
    G.shot(before)
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(src).convert("RGBA")
    d = ImageDraw.Draw(im)
    w, h = im.size
    d.rectangle([0, int(h * 0.36), w, int(h * 0.64)], fill=(255, 210, 0, 255))
    try:
        f = ImageFont.truetype("arialbd.ttf", int(h * 0.2))
    except Exception:
        f = ImageFont.load_default()
    d.text((w * 0.08, h * 0.39), "HOT SWAP", fill=(10, 10, 10, 255), font=f)
    t_edit = time.time()
    im.save(src)
    # 1) the direct image material (tower crowns) + the Pigment variants (fast path)
    r = build_and_swap(["godot.images:world"], label="decal -> image material")
    G.shot(out / "decal_after.png")
    targets = _texture_targets_of("assets/decals/story/billboard_noctis.png")
    r2 = build_and_swap(targets, fast=True, label="decal -> Pigment variants (fast path)")
    r["edit_to_image_swap_s"] = round(r["total_s"], 1)
    r2["edit_to_variants_swap_s"] = round(time.time() - t_edit, 1)
    side_by_side(before, out / "decal_after.png", out / "decal_before_after.png", "before",
                 f"after: billboard_noctis.png edited -> swapped in {r['total_s']:.1f} s",
                 "tower crown billboards (image material), same camera, game running with --live")
    # revert: the image node restores from the cache
    shutil.copyfile(backup, src)
    rv = build_and_swap(["godot.images:world"], label="revert decal (cache restore)")
    rv2 = build_and_swap(targets, fast=True, label="revert variants")
    return {"image": r, "variants": r2, "revert": rv, "revert_variants": rv2, "camera": view}


def _texture_targets_of(rel):
    """The Godot texture nodes fed by the Pigment nodes that read `rel`."""
    g = rules.build_graph(M.load_all())
    readers = [n for n, nd in g.nodes.items() if rel in nd.inputs and nd.kind.startswith("pigment")]
    return sorted(u for u in g.downstream(readers) if u.startswith("godot.tex:"))


def _edit_manifest(path, fn):
    p = paths.MODELS / path
    old = p.read_text(encoding="utf-8")
    doc = M.load(p)
    fn(doc)
    M.save(doc, p)
    return p, old


def scenario_recipe(G, out):
    W = _world()
    view = view_of_instance("building_b", near=W["spawn"]["pos"], dist=30, height=6, look_up=8)
    G.send(dict(view, type="camera"))
    before = out / "recipe_before.png"
    G.shot(before)
    p, old = _edit_manifest("building/building_b.toml", lambda d: d["pigment"].__setitem__("patch", [
        {"match": {"tool": "add_layer", "name": "LED strips (cyan)"}, "set": {"material": "Neon green"}},
        {"match": {"tool": "add_layer", "name": "LED strips (pink)"}, "set": {"material": "Neon amber"}}]))
    r = build_and_swap(["godot.tex:building_b__*"], label="building_b recipe patch")
    G.shot(out / "recipe_after.png")
    side_by_side(before, out / "recipe_after.png", out / "recipe_before_after.png", "before",
                 f"after: building_b LED strips re-coloured by a patch in its smart model -> swapped in {r['total_s']:.0f} s",
                 "pigment.patch in city/models/building/building_b.toml; Pigment re-run, 7 variant sets packed + swapped")
    p.write_text(old, encoding="utf-8")
    rv = build_and_swap(["godot.tex:building_b__*"], label="revert recipe (cache restore)")
    return {"build": r, "revert": rv, "camera": view}


def scenario_prop(G, out):
    W = _world()
    view = view_of_instance("bollard", near=W["spawn"]["pos"], dist=6, height=1.6, look_up=0.6)
    G.send(dict(view, type="camera"))
    before = out / "prop_before.png"
    G.shot(before)
    p, old = _edit_manifest("prop/bollard.toml", lambda d: d["mesh"]["params"].__setitem__("height", 1.6))
    r = build_and_swap(["world.mesh:bollard", "godot.tex:bollard*"], label="bollard height 0.96 -> 1.6")
    G.shot(out / "prop_after.png")
    side_by_side(before, out / "prop_after.png", out / "prop_before_after.png", "before", f"after: bollard mesh param height 1.6 -> swapped in {r['total_s']:.0f} s",
                 "mesh.params in city/models/prop/bollard.toml -> build_props, Pigment, export, world glb, MultiMesh swap")
    p.write_text(old, encoding="utf-8")
    rv = build_and_swap(["world.mesh:bollard", "godot.tex:bollard*"], label="revert prop (cache restore)")
    return {"build": r, "revert": rv, "camera": view}


SCENARIOS = {"decal": scenario_decal, "recipe": scenario_recipe, "prop": scenario_prop}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else OUT
    if "--out" in sys.argv:
        args = [a for a in args if a != str(out)]
    out.mkdir(parents=True, exist_ok=True)
    names = args or list(SCENARIOS)
    res = {"at": time.strftime("%Y-%m-%d %H:%M:%S")}
    t0 = time.time()
    G = Godot()
    res["godot_startup_s"] = round(G.startup_s, 1)
    print(f"Godot up with --live in {G.startup_s:.1f} s")
    try:
        for n in names:
            print(f"\n=== scenario {n}")
            res[n] = SCENARIOS[n](G, out)
            print(json.dumps(res[n], indent=1)[:3000])
            (out / "proof.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    finally:
        G.close()
    res["total_s"] = round(time.time() - t0, 1)
    (out / "proof.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"proof done in {res['total_s']} s -> {out}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
