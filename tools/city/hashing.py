"""Content hashing with a stat cache, and path patterns.

A *pattern* is a repo-relative POSIX path that may use glob wildcards in any segment
(`scenes/town/textures/building_a__*`). A directory stands for every file below it.
A pattern may end in `::<projection>` to hash only part of a JSON file (see PROJECTIONS):
`assets/props/index.json::placement` changes only when the placement-relevant fields do.

File hashes are SHA-256 of the content. They are remembered by (size, mtime_ns) in
.citycache/stat.json, so a no-op `city status` reads no file twice.
"""
import fnmatch
import glob
import hashlib
import json
import os
import threading
from pathlib import Path

from . import paths

SKIP_SUFFIXES = (".import", ".pyc", ".uid", ".tmp")
SKIP_DIRS = {"__pycache__", ".godot", ".git"}


class StatCache:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.dirty = False
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def file_hash(self, p: Path) -> str | None:
        try:
            st = p.stat()
        except OSError:
            return None
        key = str(p)
        sig = [st.st_size, st.st_mtime_ns]
        with self.lock:
            e = self.data.get(key)
            if e and e[0] == sig[0] and e[1] == sig[1]:
                return e[2]
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        d = h.hexdigest()
        with self.lock:
            self.data[key] = [sig[0], sig[1], d]
            self.dirty = True
        return d

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.path)
            self.dirty = False


_STAT = None


def stat_cache() -> StatCache:
    global _STAT
    if _STAT is None:
        _STAT = StatCache(paths.CACHE / "stat.json")
    return _STAT


def sha(data) -> str:
    if not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(data).hexdigest()


def split_projection(pattern: str):
    if "::" in pattern:
        a, b = pattern.split("::", 1)
        return a, b
    return pattern, None


def has_magic(s: str) -> bool:
    return any(c in s for c in "*?[")


def expand(pattern: str) -> list[Path]:
    """Every file a pattern stands for (sorted, absolute)."""
    pattern, _ = split_projection(pattern)
    base = paths.absp(pattern)
    hits = [Path(p) for p in glob.glob(str(base))] if has_magic(pattern) else ([base] if base.exists() else [])
    out = []
    for h in hits:
        if h.is_dir():
            for dp, dns, fns in os.walk(h):
                dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
                for fn in sorted(fns):
                    if not fn.endswith(SKIP_SUFFIXES):
                        out.append(Path(dp) / fn)
        elif h.is_file() and not h.name.endswith(SKIP_SUFFIXES):
            out.append(h)
    return sorted(set(out))


def pattern_hash(pattern: str) -> tuple[str, dict]:
    """(digest, {relpath: file digest}) for a pattern."""
    path, proj = split_projection(pattern)
    files = expand(path)
    sc = stat_cache()
    if proj:
        fn = PROJECTIONS[proj]
        parts = {}
        for f in files:
            try:
                parts[paths.rel(f)] = sha(fn(json.loads(f.read_text(encoding="utf-8"))))
            except Exception as e:      # unreadable -> hash the error so it is stale until fixed
                parts[paths.rel(f)] = sha(f"error {e}")
        return sha(parts), parts
    parts = {paths.rel(f): sc.file_hash(f) for f in files}
    return sha(parts), parts


# ---------------------------------------------------------------- pattern overlap (graph edges)
def _segs(p: str) -> list[str]:
    return [s for s in split_projection(p)[0].replace("\\", "/").strip("/").split("/") if s and s != "."]


def overlaps(a: str, b: str) -> bool:
    """True when two patterns can name a common file (one contains or matches the other)."""
    sa, sb = _segs(a), _segs(b)
    for x, y in zip(sa, sb):
        if x == y:
            continue
        if not (fnmatch.fnmatchcase(x, y) or fnmatch.fnmatchcase(y, x)):
            return False
    return True


# ---------------------------------------------------------------- JSON projections
def _placement(index):
    """The fields of assets/props/index.json that the world's scatter reads."""
    out = {}
    for n, p in sorted(index.get("props", {}).items()):
        e = {k: p.get(k) for k in ("scatter", "footprint", "files", "tile_length", "span", "mount")}
        e["collider"] = (p.get("collider") or {}).get("type")
        e["variants"] = [(v.get("name"), bool(v.get("default"))) for v in p.get("variants") or []]
        if (p.get("scatter") or {}).get("stack"):
            e["size_m"] = p.get("size_m")
        out[n] = e
    return out


def _vehicles_index(index):
    return index


PROJECTIONS = {"placement": _placement, "all": lambda d: d}
