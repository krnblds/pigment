"""What each kind of node does. Every action wraps an existing pipeline script; the only
in-process work is small glue: packing one texture set for Godot, copying image materials,
and patching world_layout.json entries.
"""
import ast
import glob
import importlib.util
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from . import cache, graph as G, hashing, paths, pigscript

ROOT = paths.ROOT
LAYOUT_LOCK = threading.Lock()
WORLD_DIR = "game/assets/world"


def impl(factory, also=()):
    """Mark the run function a factory makes with a hash of the factory's source (and helpers'),
    so a node's key changes when *its* action changes, not when any other action in this file does."""
    import functools
    import hashlib
    import inspect

    def digest():
        src = inspect.getsource(factory) + "".join(inspect.getsource(f) for f in also)
        return factory.__name__ + ":" + hashlib.sha256(src.encode()).hexdigest()[:16]

    @functools.wraps(factory)
    def wrapper(*a, **k):
        fn = factory(*a, **k)
        fn.impl = digest()
        return fn
    return wrapper


def _env_params(params):
    return {"CITY_PARAMS": json.dumps(params or {})}


# ---------------------------------------------------------------- generators / tools
@impl
def run_generator(sec):
    def run(ctx):
        args = [str(a) for a in sec.get("args", [])]
        env = _env_params(sec.get("params"))
        if sec["runner"] == "blender":
            ctx.blender(sec["generator"], args, env=env)
        else:
            ctx.python(sec["generator"], args, env=env)
    return run


@impl
def run_tool(sec):
    def run(ctx):
        args = [str(a) for a in sec.get("args", [])]
        if sec.get("runner") == "blender":
            ctx.blender(sec["tool"], args)
        else:
            ctx.python(sec["tool"], args)
    return run


@impl
def run_recipe(rec):
    def run(ctx):
        r = rec["runner"]
        if r == "town_textures":
            ctx.run([paths.python(), "-m", "tools.city.recipe", "town", rec["job"]])
        elif r == "town_textures_world":
            ctx.run([paths.python(), "-m", "tools.city.recipe", "town_world", *rec.get("args", [])])
        elif r == "blender":
            ctx.blender(rec["tool"], [str(a) for a in rec.get("args", [])])
        else:
            ctx.python(rec["tool"], [str(a) for a in rec.get("args", [])])
    return run


# ---------------------------------------------------------------- Pigment
def pigment_node(nid, mid, script, pig):
    sp = ROOT / script
    sc = pigscript.scan(sp) if sp.is_file() else {"inputs": [], "outputs": pig.get("outputs", []), "variants": []}
    patches = pig.get("patch", [])
    from . import pins
    pin = pins.pinned(nid)
    if pin:     # the project saved in the Pigment app is the source (see tools/city/pins.py)
        proj = pin["project"]
        return G.Node(id=nid, kind="pigment.project", model=mid, title=f"Pigment: export pinned {Path(proj).name}",
                      tools=["tools/city/pins.py"], inputs=[proj],
                      outputs=[o for o in sc["outputs"] if o != proj], params={"pinned": proj}, pool="pigment",
                      run=_run_pigment(nid, script, [], sc, pinned=proj))
    return G.Node(id=nid, kind="pigment.script", model=mid, title=f"Pigment: {Path(script).name}",
                  tools=["tools/city/pigscript.py"],
                  inputs=[script] + sc["inputs"], outputs=sc["outputs"],
                  params={"patch": patches}, pool="pigment", run=_run_pigment(nid, script, patches, sc))


def _run_pigment_factory(nid, script, patches, scan, pinned=None):
    def run(ctx):
        mcp = paths.pigment_mcp()
        if not mcp:
            raise RuntimeError("pigment-mcp not found (build it, or set PIGMENT_MCP)")
        lines = pigscript.steps(ROOT / script)
        if pinned:
            from . import pins
            lines = pins.export_lines(lines, pinned)
            fast = lines
            ctx.note = f"pinned: exported from {pinned}"
        else:
            fast = _decal_fast_path(ctx, lines, scan)
        if fast is not None:
            lines = fast
        if patches:
            lines = pigscript.apply_patches(lines, patches)
        if patches or fast is not None:
            run_path = paths.CACHE / "scripts" / (cache._safe(nid) + ".jsonl")
            run_path.parent.mkdir(parents=True, exist_ok=True)
            run_path.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines), encoding="utf-8")
        else:
            run_path = ROOT / script
        for o in scan["outputs"]:
            if not o.endswith(".pigment"):
                (ROOT / o).mkdir(parents=True, exist_ok=True)
        ctx.run([mcp, "--script", run_path])
    return run


def _decal_fast_path(ctx, lines, scan):
    """When only decal images changed since the last full build (and `city watch --fast` asked for
    it), re-export just the variants that show those decals from the saved project: open_project +
    export_variants(only=...). The authored base folder is not refreshed, so the stamp is marked
    partial and the next plain `city build` runs the full script."""
    if not ctx.engine.fast or not ctx.prev:
        return None
    old = ctx.prev.get("detail", {}).get("inputs", {})
    now = {i: hashing.pattern_hash(i)[0] for i in ctx.node.inputs}
    changed = [i for i in now if old.get(i) != now[i]]
    if not changed or not all(i.startswith("assets/decals/") and i.endswith(".png") for i in changed):
        return None
    proj = next((s["args"]["path"] for s in lines if s.get("tool") == "save_project"), None)
    ev = next((s for s in lines if s.get("tool") == "export_variants"), None)
    if not proj or not ev or not (ROOT / proj).exists():        # a .pigment project is a folder
        return None
    stems = {Path(c).stem for c in changed}
    only = []
    for v in ev["args"].get("variants", []):
        names = [e.split("/")[-1] for e in v.get("enable", [])] + [str(x).split("/")[-1] for x in (v.get("swaps") or {}).values()]
        if stems & set(names) and v.get("name"):
            only.append(v["name"])
    if not only:
        return None
    args = {k: v for k, v in ev["args"].items() if k != "preview"}
    args["only"] = only
    ctx.note = f"fast path: decal {', '.join(sorted(stems))} -> variants {', '.join(only)} (partial)"
    ctx.partial = True
    return [{"tool": "open_project", "args": {"path": proj}}, {"tool": "export_variants", "args": args}]


# ---------------------------------------------------------------- world
def _glb_info(path):
    """(tris, aabb) of a glb: union of the POSITION accessor bounds, index count / 3."""
    import struct
    b = Path(path).read_bytes()
    n = struct.unpack_from("<I", b, 12)[0]
    j = json.loads(b[20:20 + n])
    lo, hi, tris = [1e30] * 3, [-1e30] * 3, 0
    for m in j.get("meshes", []):
        for pr in m["primitives"]:
            a = j["accessors"][pr["attributes"]["POSITION"]]
            lo = [min(x, y) for x, y in zip(lo, a["min"])]
            hi = [max(x, y) for x, y in zip(hi, a["max"])]
            if "indices" in pr:
                tris += j["accessors"][pr["indices"]]["count"] // 3
            else:
                tris += a["count"] // 3
    return tris, [[round(v, 4) for v in lo], [round(v, 4) for v in hi]]


def patch_layout(mapname, fn):
    """Read-modify-write game/assets/<map>/<map>_layout.json under a lock."""
    p = ROOT / "game" / "assets" / mapname / f"{mapname}_layout.json"
    if not p.is_file():
        return False
    with LAYOUT_LOCK:
        lay = json.loads(p.read_text(encoding="utf-8"))
        if fn(lay):
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(lay, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, p)
            return True
    return False


@impl
def run_world_mesh(kind, asset, keys):
    def run(ctx):
        out = ROOT / WORLD_DIR / "meshes"
        _, lines = ctx.blender("tools/city/blender/world_assets.py",
                               ["--kind", kind, "--asset", asset, "--keys", ",".join(keys), "--out", str(out)])
        got = {}
        for line in lines:
            if line.startswith("CITY_KEY "):
                d = json.loads(line[9:])
                got[d["key"]] = d
        missing = [k for k in keys if k not in got]
        if missing:
            raise RuntimeError(f"world_assets wrote no {missing}")

        def fix(lay):
            ch = False
            for k, d in got.items():
                m = lay.get("meshes", {}).get(k)
                if m and (m.get("tris") != d["tris"] or m.get("aabb") != d["aabb"]):
                    m["tris"], m["aabb"] = d["tris"], d["aabb"]
                    ch = True
            return ch
        if patch_layout("world", fix):
            ctx.log("world_layout.json: mesh bounds / triangles updated")
            ctx.events.append({"type": "layout", "map": "world", "keys": keys})
    return run


@impl
def run_world_build(w, overrides, shared_keys):
    def run(ctx):
        wdir = paths.CACHE / "world"
        wdir.mkdir(parents=True, exist_ok=True)
        cfg = w.get("config", "tools/world/world_config.json")
        if overrides:
            from .manifest import deep_merge
            base = json.loads((ROOT / cfg).read_text(encoding="utf-8"))
            merged = deep_merge(base, overrides)
            (wdir / "world_config.json").write_text(json.dumps(merged, indent=1), encoding="utf-8")
            cfg = str(wdir / "world_config.json")
            ctx.log("config overrides from smart models:", json.dumps(overrides)[:400])
        (wdir / "skip_keys.json").write_text(json.dumps(shared_keys), encoding="utf-8")
        report = wdir / "export_report.json"
        report.unlink(missing_ok=True)
        env = {"CITY_EXPORT_HOOK": str(ROOT / "tools/city/blender/export_hook.py"),
               "CITY_SKIP_KEYS": str(wdir / "skip_keys.json"),
               "CITY_FINGERPRINTS": str(wdir / "fingerprints.json"),
               "CITY_EXPORT_REPORT": str(report)}
        args = ["--stages", "gen,build,export", "--config", cfg]
        if w.get("seed") is not None:
            args += ["--seed", str(w["seed"])]
        t0 = time.time()
        ctx.blender("tools/world/world_driver.py", args, env=env)
        rep = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        if not rep:
            raise RuntimeError("the export hook wrote no report (see the log)")
        chunks = _chunks_of(rep.get("written", []))
        rep["chunks"] = sorted(chunks)
        report.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        ctx.note = (f"{len(rep.get('written', []))} glb(s) re-exported in {len(chunks)} chunk(s) of 256 m, "
                    f"{rep.get('unchanged', '?')} unchanged, {rep.get('shared_skipped', '?')} shared (per asset); "
                    f"export {rep.get('total_s', '?')} s, total {time.time() - t0:.0f} s")
        if rep.get("written"):
            ctx.events.append({"type": "layout", "map": "world", "keys": rep["written"][:2000]})
    return run


def _chunks_of(keys, size=256.0):
    """256 m world chunks (Godot x / z) the given mesh keys sit in, from the layout's bounds.
    Unique world pieces are exported in world space, so their bounds are their place."""
    lay = json.loads((ROOT / WORLD_DIR / "world_layout.json").read_text(encoding="utf-8"))
    out = set()
    for k in keys:
        m = lay.get("meshes", {}).get(k)
        if not m:
            if k.startswith("terrain_lod/"):
                out.add(k.split("/")[1].split("_")[0])
            continue
        (x0, _, z0), (x1, _, z1) = m["aabb"]
        out.add(f"{int((x0 + x1) / 2 // size)}_{int((z0 + z1) / 2 // size)}")
    return out


@impl
def run_world_verify():
    def run(ctx):
        ctx.blender("tools/world/world_driver.py", ["--stages", "build,verify", "--no-lights"])
        v = json.loads((ROOT / "scenes/world/verify.json").read_text(encoding="utf-8"))
        ctx.log(json.dumps(v)[:2000])
        bad = _verify_failures(v)
        if bad:
            raise RuntimeError("world verify: " + "; ".join(bad))
        ctx.note = "world verify: all checks 0"
    return run


def _verify_failures(v):
    """Counts in verify.json that should be 0 (keys with 'bad', 'over', 'above', 'floating', 'buried', 'overlap')."""
    bad = []

    def walk(d, path=""):
        if isinstance(d, dict):
            for k, x in d.items():
                walk(x, f"{path}.{k}" if path else k)
        elif isinstance(d, (int, float)) and not isinstance(d, bool):
            leaf = path.split(".")[-1].lower()
            if any(t in leaf for t in ("bad", "over_limit", "above", "floating", "buried", "overlap", "inside", "on_road",
                                       "fail")) and d > 0:
                bad.append(f"{path}={d}")
    walk(v)
    return bad


def _load_function(path, name):
    """One top-level function from a script that imports Blender modules (world_gen.py)."""
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    mod = ast.Module(body=[fn], type_ignores=[])
    ns = {}
    exec(compile(mod, str(path), "exec"), ns)
    return ns[name]


@impl
def run_road_scan():
    def run(ctx):
        clear = _load_function(ROOT / "tools/world/world_gen.py", "clear_carriageways")
        world = json.loads((ROOT / "scenes/world/world.json").read_text(encoding="utf-8"))
        n0 = len(world["instances"])
        msgs = []
        kept = clear(world, msgs.append)
        dropped = n0 - len(kept)
        ctx.log(*msgs)
        ctx.note = f"road obstacle scan: {dropped} of {n0} instances on a carriageway"
        if dropped:
            raise RuntimeError(ctx.note + " (" + "; ".join(msgs) + ")")
    return run


# ---------------------------------------------------------------- Godot
_PACK = None


def _pack_module():
    global _PACK
    if _PACK is None:
        argv = sys.argv
        sys.argv = ["pack_textures.py"]
        try:
            spec = importlib.util.spec_from_file_location("city_pack_textures", ROOT / "tools/godot/pack_textures.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            sys.argv = argv
        mod.FORCE = True
        _PACK = mod
    return _PACK


def texture_meta(src: Path, name: str) -> dict:
    """emissive_scale / opacity of a Pigment texture folder (variant.json, material.json, files)."""
    es = None
    for fn in ("variant.json", "material.json"):
        p = src / fn
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if fn == "variant.json" and "emissive_scale" in d:
                es = d["emissive_scale"]
                break
            if fn == "material.json":
                m = (d.get("materials") or {}).get(name) or {}
                if "emissive_scale" in m:
                    es = m["emissive_scale"]
    return {"emissive_scale": float(es) if es is not None else None,
            "opacity": (src / f"{name}_Opacity.png").is_file()}


@impl
def run_pack(src, folder, name, maps):
    def run(ctx):
        P = _pack_module()
        s = ROOT / src
        meta = texture_meta(s, name)
        for mp in maps:
            dst = ROOT / "game" / "assets" / mp / "textures" / folder
            ok = P.pack(str(s), name, str(dst), meta["opacity"])
            if not ok:
                raise RuntimeError(f"pack failed: {src} has no {name}_BaseColor.png")

            def fix(lay):
                ch = False
                for m in lay.get("materials", {}).values():
                    if m.get("type") == "pigment" and m.get("folder") == folder:
                        if meta["emissive_scale"] is not None and m.get("emissive_scale") != meta["emissive_scale"]:
                            m["emissive_scale"] = meta["emissive_scale"]
                            ch = True
                        if m.get("opacity") != meta["opacity"]:
                            m["opacity"] = meta["opacity"]
                            ch = True
                return ch
            if patch_layout(mp, fix):
                ctx.log(f"{mp}_layout.json: {folder} emissive / opacity updated")
                ctx.events.append({"type": "material", "map": mp, "folder": folder})
        ctx.log(f"packed {folder} -> {', '.join(maps)}")
    return run


IMAGE_ROOTS = ["scenes/town/textures/roads", "scenes/town/textures/world", "assets/decals"]


def image_sources(layout) -> dict:
    """{"images/<file>": source path} for the world's image materials (found by file name)."""
    want = {m["image"] for m in (layout.get("materials") or {}).values() if m.get("type") == "image" and m.get("image")}
    if not want:
        return {}
    index = {}
    for r in IMAGE_ROOTS:
        for p in sorted(glob.glob(str(ROOT / r / "**" / "*.png"), recursive=True)):
            index.setdefault(Path(p).name, paths.rel(p))
    return {w: index[Path(w).name] for w in sorted(want) if Path(w).name in index}


@impl
def run_images(imgs):
    def run(ctx):
        sc = hashing.stat_cache()
        n = 0
        for dst, src in imgs.items():
            d = ROOT / WORLD_DIR / dst
            if d.is_file() and sc.file_hash(d) == sc.file_hash(ROOT / src):
                continue
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / src, d)
            imp = d.with_name(d.name + ".import")
            if not imp.is_file():
                _pack_module().write_import(str(d))
            n += 1
        ctx.note = f"{n} image(s) updated"
    return run


@impl
def run_godot_import():
    def run(ctx):
        gd = paths.godot()
        if not gd:
            raise RuntimeError("Godot not found (set CITY_GODOT)")
        ctx.run([gd, "--headless", "--path", ROOT / "game", "--import"], timeout=3600)
    return run


@impl
def run_script_check(scripts):
    def run(ctx):
        mcp = paths.pigment_mcp()
        if not mcp:
            raise RuntimeError("pigment-mcp not found")
        bad = []
        for s in scripts:
            if not (ROOT / s).is_file():
                continue
            rc, tail = ctx.run([mcp, "--script", ROOT / s, "--check"], check=False)
            if rc != 0:
                bad.append(f"{s}: {' | '.join(tail[-3:])}")
        ctx.note = f"{len(scripts)} Pigment script(s) checked"
        if bad:
            raise RuntimeError("script check failed:\n" + "\n".join(bad))
    return run


@impl
def run_decal_audit():
    def run(ctx):
        p = ROOT / "tools/decal_audit.py"
        if not p.is_file():
            ctx.note = "tools/decal_audit.py not present yet: skipped"
            return
        ctx.python("tools/decal_audit.py", [])
    return run


_run_pigment = impl(_run_pigment_factory)      # the fast path is not part of the key: it never writes a full build
