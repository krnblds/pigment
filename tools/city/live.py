"""Hot swap: tell a running Godot (game/scripts/live_link.gd, `--live`) and a running Blender
(the Pigment Bridge add-on) what changed.

Godot   events are appended to game/assets/.live/events.jsonl (one JSON object per line, with a
        sequence number). live_link.gd tails the file, applies each event in place and appends
        an acknowledgement {"seq", "ok", "ms", ...} to game/assets/.live/acks.jsonl.
Blender events are appended to .citycache/blender_events.jsonl; the add-on's timer reads them
        (core.check_city_events) and reloads the listed images / meshes.

Event types (Godot):
    {"type": "texture", "map": "world", "folder": "building_a__soba"}   reload a packed texture set
    {"type": "image", "map": "world", "image": "images/billboard_noctis.png"}
    {"type": "mesh", "map": "world", "key": "building_a__soba"}         reload a mesh glb everywhere it is used
    {"type": "material", "map": "world", "folder": ...}                 emissive / opacity changed (layout)
    {"type": "camera", "pos": [x, y, z], "look": [x, y, z], "fov": 60}  park a camera (proof shots)
    {"type": "screenshot", "path": "C:/.../shot.png"}
    {"type": "ping"}
"""
import json
import os
import threading
import time
from pathlib import Path

from . import paths

EVENTS = paths.LIVE / "events.jsonl"
ACKS = paths.LIVE / "acks.jsonl"
_lock = threading.Lock()


def _next_seq() -> int:
    s = 0
    if EVENTS.is_file():
        with open(EVENTS, "rb") as f:
            try:
                f.seek(-4096, os.SEEK_END)
            except OSError:
                f.seek(0)
            for line in f.read().decode("utf-8", "replace").splitlines():
                try:
                    s = max(s, int(json.loads(line).get("seq", 0)))
                except Exception:
                    pass
    return s + 1


def send(events, wait=False, timeout=60.0) -> list:
    """Append events for Godot. With wait, block until each is acknowledged; returns the acks."""
    if not events:
        return []
    paths.LIVE.mkdir(parents=True, exist_ok=True)
    with _lock:
        seq = _next_seq()
        out = []
        with open(EVENTS, "a", encoding="utf-8") as f:
            for e in events:
                e = dict(e, seq=seq, t=time.time())
                out.append(e)
                f.write(json.dumps(e) + "\n")
                seq += 1
    if not wait:
        return out
    return wait_acks([e["seq"] for e in out], timeout)


def wait_acks(seqs, timeout=60.0) -> list:
    want = set(seqs)
    got = {}
    t0 = time.time()
    while want - set(got) and time.time() - t0 < timeout:
        if ACKS.is_file():
            for line in ACKS.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    a = json.loads(line)
                except Exception:
                    continue
                if a.get("seq") in want:
                    got[a["seq"]] = a
        time.sleep(0.05)
    return [got.get(s, {"seq": s, "ok": False, "error": "timeout"}) for s in seqs]


def godot_listening() -> bool:
    """live_link.gd writes game/assets/.live/alive (its pid and a heartbeat time) while running."""
    p = paths.LIVE / "alive"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return time.time() - float(d.get("t", 0)) < 5.0
    except Exception:
        return False


# ---------------------------------------------------------------- changed files -> events
def events_for(changed_files) -> list:
    """Map changed output files (repo-relative) to hot-swap events, de-duplicated."""
    ev, seen = [], set()
    for r in changed_files:
        parts = r.split("/")
        if len(parts) >= 4 and parts[0] == "game" and parts[1] == "assets" and parts[2] in ("world", "town"):
            mp = parts[2]
            if parts[3] == "textures" and len(parts) >= 6:
                k = ("texture", mp, parts[4])
                if k not in seen:
                    seen.add(k)
                    ev.append({"type": "texture", "map": mp, "folder": parts[4]})
            elif parts[3] == "meshes" and r.endswith(".glb"):
                key = Path(r).stem
                k = ("mesh", mp, key)
                if k not in seen:
                    seen.add(k)
                    ev.append({"type": "mesh", "map": mp, "key": key})
            elif parts[3] == "images" and r.endswith(".png"):
                k = ("image", mp, parts[4])
                if k not in seen:
                    seen.add(k)
                    ev.append({"type": "image", "map": mp, "image": "images/" + parts[4]})
    return ev


def blender_events(changed_files) -> list:
    """Pigment texture folders / meshes a running Blender may have linked."""
    ev, seen = [], set()
    for r in changed_files:
        p = paths.absp(r)
        if r.startswith(("scenes/town/textures/", "scenes/props/textures/", "scenes/vehicles/")) and r.endswith(".png"):
            d = str(p.parent)
            if d not in seen:
                seen.add(d)
                ev.append({"type": "texture_folder", "path": d.replace("\\", "/")})
        elif r.endswith(".glb") and r.startswith(("assets/town/", "assets/props/", "assets/vehicles/")):
            ev.append({"type": "mesh", "path": str(p).replace("\\", "/")})
    return ev


def send_blender(events):
    if not events:
        return
    paths.BLENDER_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(paths.BLENDER_QUEUE, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(dict(e, t=time.time())) + "\n")
