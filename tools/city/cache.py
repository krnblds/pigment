"""Stamps and the content-addressed cache (.citycache/, git-ignored).

    .citycache/objects/ab/<sha256>       file contents, stored once whatever their name
    .citycache/keys/<key>.json           node key -> {relpath: sha256} of what that build wrote
    .citycache/stamps/<node>.json        the node's last successful build: key, key detail,
                                         outputs, time, seconds
    .citycache/logs/<node>.log           the last run's output
    .citycache/stat.json                 (size, mtime) -> sha256 memo for hashing

A node whose key was built before (say an edit and its undo) gets its outputs copied back
from objects/ instead of running again.
"""
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import hashing, paths



def _C():
    return paths.CACHE


def _safe(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", node_id)


def stamp_path(node_id):
    return _C() / "stamps" / (_safe(node_id) + ".json")


def log_path(node_id):
    return _C() / "logs" / (_safe(node_id) + ".log")


def read_stamp(node_id) -> dict | None:
    try:
        return json.loads(stamp_path(node_id).read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def output_files(node) -> dict:
    """{relpath: sha256} of every file the node's (verified) outputs name right now."""
    sc = hashing.stat_cache()
    out = {}
    for pat in node.outputs:
        for f in hashing.expand(pat):
            out[paths.rel(f)] = sc.file_hash(f)
    return out


def outputs_intact(node, stamp) -> list[str]:
    """Problems with the outputs a stamp recorded (missing or changed on disk)."""
    bad = []
    rec = stamp.get("outputs", {})
    sc = hashing.stat_cache()
    for r, d in rec.items():
        p = paths.absp(r)
        if not p.is_file():
            bad.append(f"output missing: {r}")
        elif sc.file_hash(p) != d:
            bad.append(f"output changed on disk: {r}")
        if len(bad) >= 3:
            bad.append("...")
            break
    if not rec and node.outputs and not any(hashing.expand(p) for p in node.outputs):
        bad.append("outputs missing")
    return bad


def write_stamp(node, key, detail, outputs, seconds, note=""):
    write_json(stamp_path(node.id), {"node": node.id, "key": key, "detail": detail, "outputs": outputs,
                                     "built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(seconds, 2),
                                     "note": note})


# ---------------------------------------------------------------- content-addressed objects
def obj_path(digest: str) -> Path:
    return _C() / "objects" / digest[:2] / digest


def store(outputs: dict, key: str, node_id: str):
    """Copy outputs into objects/ (each content once) and remember them under the key."""
    for r, d in outputs.items():
        if d is None:
            continue
        o = obj_path(d)
        if not o.is_file():
            o.parent.mkdir(parents=True, exist_ok=True)
            tmp = o.with_name(o.name + ".tmp")
            shutil.copyfile(paths.absp(r), tmp)
            os.replace(tmp, o)
    write_json(_C() / "keys" / f"{key}.json", {"node": node_id, "outputs": outputs, "at": time.time()})


def lookup(key: str) -> dict | None:
    p = _C() / "keys" / f"{key}.json"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if all(obj_path(d).is_file() for d in rec["outputs"].values() if d):
        return rec
    return None


def restore(rec: dict) -> int:
    """Put a cached build's outputs back in place. Returns the number of files copied."""
    n = 0
    sc = hashing.stat_cache()
    for r, d in rec["outputs"].items():
        p = paths.absp(r)
        if p.is_file() and sc.file_hash(p) == d:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(obj_path(d), p)
        n += 1
    return n


# ---------------------------------------------------------------- housekeeping
def size_bytes() -> int:
    total = 0
    for dp, _, fns in os.walk(_C() / "objects"):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def gc(keep_per_node: int = 2) -> tuple[int, int]:
    """Drop all but the newest `keep_per_node` keys of each node, then unreferenced objects."""
    keys = {}
    for p in (_C() / "keys").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            p.unlink(missing_ok=True)
            continue
        keys.setdefault(rec["node"], []).append((rec.get("at", 0), p, rec))
    live = set()
    dropped = 0
    for node, lst in keys.items():
        lst.sort(key=lambda t: -t[0])
        stamp = read_stamp(node) or {}
        for i, (_, p, rec) in enumerate(lst):
            if i < keep_per_node or p.stem == stamp.get("key"):
                live |= set(rec["outputs"].values())
            else:
                p.unlink(missing_ok=True)
                dropped += 1
    freed = 0
    for dp, _, fns in os.walk(_C() / "objects"):
        for fn in fns:
            if fn not in live:
                fp = os.path.join(dp, fn)
                freed += os.path.getsize(fp)
                os.remove(fp)
    return dropped, freed


def clean(node_ids=None, everything=False):
    if everything:
        shutil.rmtree(_C(), ignore_errors=True)
        return
    for n in node_ids or []:
        stamp_path(n).unlink(missing_ok=True)
