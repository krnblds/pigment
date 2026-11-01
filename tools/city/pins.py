"""Pins: a Pigment project edited by hand becomes the source of its texture sets.

Normally a Pigment node runs its script and *writes* the project. When you open the project
in the Pigment app (`city open <model>`) and save it, `city watch` sees a project the build
did not write and pins the node: from then on the node exports from the saved project
(open_project, export_variants, export_textures) instead of re-running the script, and the
project is one of its inputs. So hand edits flow downstream and are never overwritten by the
recipe. `city unpin <node>` goes back to the recipe (the next build re-runs the script).

    .citycache/pins/<node>.json    {"node", "project", "at"}
"""
import json
import time

from . import cache, hashing, paths

PINS = paths.CACHE / "pins"


def pin_path(nid):
    return PINS / (cache._safe(nid) + ".json")


def pinned(nid) -> dict | None:
    try:
        return json.loads(pin_path(nid).read_text(encoding="utf-8"))
    except Exception:
        return None


def pin(nid, project):
    cache.write_json(pin_path(nid), {"node": nid, "project": project, "at": time.strftime("%Y-%m-%d %H:%M:%S")})


def unpin(nid):
    pin_path(nid).unlink(missing_ok=True)


def node_for_project(g, rel_project):
    for n, nd in g.nodes.items():
        if nd.kind == "pigment.script" and (rel_project in nd.outputs or rel_project in nd.inputs):
            return n
    return None


def project_edited(node, rel_project) -> bool:
    """True when the project on disk is not the one the last build of this node wrote."""
    st = cache.read_stamp(node.id) or {}
    rec = (st.get("outputs") or {}).get(rel_project)
    if rec is None:
        return False
    return hashing.stat_cache().file_hash(paths.absp(rel_project)) != rec


def export_lines(script_lines, project):
    """The export part of a script, run on the saved project."""
    out = [{"tool": "open_project", "args": {"path": project}}]
    for s in script_lines:
        if s.get("tool") in ("export_variants", "export_textures", "send_to_blender"):
            a = {k: v for k, v in (s.get("args") or {}).items() if k != "preview"}
            out.append({"tool": s["tool"], "args": a})
    return out
