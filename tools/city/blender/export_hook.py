"""Incremental world export (loaded by tools/world/world_export.py when $CITY_EXPORT_HOOK names this file).

make_writer(dest, ns, log) returns write_mesh(key, mesh, path) for export_town.export_layout():

  * keys in $CITY_SKIP_KEYS (a JSON list file) are not written: they are the shared meshes made from
    one kit / props asset, which the city build exports per asset (tools/city/blender/world_assets.py);
  * every other mesh gets a fingerprint (vertices, faces, corner normals, UVs, material names) and is
    only written when the fingerprint differs from the last export or the glb is missing. So a world
    rebuild after a local change re-exports only the chunks / pieces whose geometry changed;
  * glbs are written by tools/city/blender/glb_writer.py: Blender's glTF exporter walks the whole
    scene on every call, which made each of the 1,428 calls cost 1-2.5 s in the 38k-object world
    scene. ($CITY_EXPORT_MODE=plain keeps export_town.export_mesh.)

finish() saves the fingerprints and writes .citycache/world_export_report.json.
"""
import hashlib
import json
import os
import time

import bpy
import numpy as np

STATE = {}


def _arr(coll, attr, n, dtype, width=1):
    a = np.empty(n * width, dtype=dtype)
    if n:
        coll.foreach_get(attr, a)
    return a


def fingerprint(me) -> str:
    h = hashlib.sha256()
    nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
    h.update(np.array([nv, nl, npoly], np.int64).tobytes())
    h.update(np.round(_arr(me.vertices, "co", nv, np.float32, 3), 5).tobytes())
    h.update(_arr(me.loops, "vertex_index", nl, np.int32).tobytes())
    h.update(_arr(me.polygons, "loop_total", npoly, np.int32).tobytes())
    h.update(_arr(me.polygons, "material_index", npoly, np.int32).tobytes())
    try:
        cn = me.corner_normals
        h.update(np.round(_arr(cn, "vector", len(cn), np.float32, 3), 4).tobytes())
    except AttributeError:
        pass
    for uv in me.uv_layers:
        h.update(uv.name.encode())
        h.update(np.round(_arr(uv.data, "uv", nl, np.float32, 2), 5).tobytes())
    for ca in getattr(me, "color_attributes", []):
        h.update(ca.name.encode())
    h.update(json.dumps([m.name if m else None for m in me.materials]).encode())
    return h.hexdigest()


def _writer_module():
    import importlib.util
    here = os.environ.get("CITY_HOOK_DIR") or os.path.dirname(os.path.abspath(os.environ.get("CITY_EXPORT_HOOK", __file__)))
    spec = importlib.util.spec_from_file_location("city_glb_writer", os.path.join(here, "glb_writer.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fast_export(me, path):
    """The glb export_town.export_mesh() makes, written directly (tools/city/blender/glb_writer.py)."""
    if "glb" not in STATE:
        STATE["glb"] = _writer_module()
    STATE["glb"].write_glb(me, path)


def make_writer(dest, ns, log):
    fp_path = os.environ.get("CITY_FINGERPRINTS") or os.path.join(dest, ".fingerprints.json")
    try:
        old = json.load(open(fp_path, encoding="utf-8"))
    except Exception:
        old = {}
    skip = set()
    if os.environ.get("CITY_SKIP_KEYS"):
        try:
            skip = set(json.load(open(os.environ["CITY_SKIP_KEYS"], encoding="utf-8")))
        except Exception as e:
            log(f"city export hook: no skip list ({e})")
    mode = os.environ.get("CITY_EXPORT_MODE", "fast")
    STATE.update(fp_path=fp_path, old=old, new={}, written=[], skipped_same=0, skipped_shared=0, t0=time.time(),
                 t_fp=0.0, t_write=0.0, log=log, dest=dest)

    def write(key, me, path):
        if key in skip:
            STATE["skipped_shared"] += 1
            return
        t = time.time()
        f = fingerprint(me)
        STATE["t_fp"] += time.time() - t
        STATE["new"][key] = f
        if old.get(key) == f and os.path.isfile(path):
            STATE["skipped_same"] += 1
            return
        t = time.time()
        if mode == "plain":
            ns["export_mesh"](me, path)
        else:
            fast_export(me, path)
        STATE["t_write"] += time.time() - t
        STATE["written"].append(key)

    return write


def finish():
    S = STATE
    merged = dict(S["old"])
    merged.update(S["new"])
    os.makedirs(os.path.dirname(S["fp_path"]) or ".", exist_ok=True)
    with open(S["fp_path"], "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=0, sort_keys=True)
    rep = {"written": S["written"], "unchanged": S["skipped_same"], "shared_skipped": S["skipped_shared"],
           "fingerprint_s": round(S["t_fp"], 2), "write_s": round(S["t_write"], 2), "total_s": round(time.time() - S["t0"], 1)}
    rp = os.environ.get("CITY_EXPORT_REPORT")
    if rp:
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)
    S["log"](f"city export hook: wrote {len(S['written'])} glb(s), {S['skipped_same']} unchanged, "
             f"{S['skipped_shared']} shared (exported per asset); fingerprints {S['t_fp']:.1f} s, writing {S['t_write']:.1f} s")
