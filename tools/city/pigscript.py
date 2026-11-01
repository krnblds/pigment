"""Read a Pigment MCP script (.jsonl) for what it reads and writes.

A recipe's script is the recipe in data form, so the build can take its inputs (mesh,
decal images, tile sets, projects it opens) and outputs (texture folders, variant folders,
the saved project) straight from it instead of trusting a hand-written list.
"""
import json
from pathlib import Path

from . import paths

IN_KEYS = {("new_project", "mesh"), ("project_decal", "image"), ("add_layer", "image"), ("add_layer", "tile_set"),
           ("update_layer", "image"), ("open_project", "path"), ("apply_smart_material", "path"),
           ("add_layer", "path"), ("add_smart_material", "path")}


def steps(path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "//")):
            out.append(json.loads(line))
    return out


def _in_repo(p: str) -> str | None:
    if not isinstance(p, str) or not p:
        return None
    q = Path(p)
    r = paths.rel(q if q.is_absolute() else paths.ROOT / q)
    if Path(r).is_absolute() or r.startswith(("..", "target/", "docs/")):
        return None
    return r


def scan(path) -> dict:
    """{inputs, outputs, variants, decal_slots, decals, resolution, export_names}"""
    ins, outs, variants, slots, decals = set(), set(), [], {}, set()
    res = None
    for s in steps(path):
        tool, a = s.get("tool"), s.get("args", {}) or {}
        for (t, k) in IN_KEYS:
            if t == tool and k in a:
                r = _in_repo(a[k])
                if r:
                    ins.add(r)
        if tool == "new_project":
            res = a.get("resolution", res)
        if tool == "project_decal":
            img = _in_repo(a.get("image"))
            if img:
                decals.add(img)
            nm = a.get("name") or ""
            if "/" in nm:
                slot, image = nm.split("/", 1)
                slots.setdefault(slot, set()).add(image)
        if tool in ("export_textures", "send_to_blender"):
            d = _in_repo(a.get("dir"))
            if d:
                outs.add(d)
        if tool == "export_variants":
            d = _in_repo(a.get("dir"))
            names = [v["name"] for v in a.get("variants", []) if "name" in v]
            if a.get("only"):
                names = [n for n in names if n in a["only"]] or list(a["only"])
            variants += [n for n in names if n not in variants]
            if d:
                folder = a.get("folder", "{name}__{variant}")
                base = a.get("name") or "*"
                for v in names or ["*"]:
                    outs.add(f"{d}/{folder.replace('{name}', base).replace('{variant}', v)}")
        if tool in ("save_project", "save_smart_material"):
            p = _in_repo(a.get("path"))
            if p:
                outs.add(p)
    ins -= outs
    return {"inputs": sorted(ins), "outputs": sorted(outs), "variants": variants,
            "decal_slots": {k: sorted(v) for k, v in sorted(slots.items())}, "decals": sorted(decals),
            "resolution": res}


def apply_patches(lines: list[dict], patches: list[dict]) -> list[dict]:
    """Manifest [pigment] patch ops on a script:
        {match = {tool = "add_layer", name = "Concrete"}, set = {base_color = [0.5, 0.2, 0.2]}}
            -> merges `set` into the args of every step whose tool / args match
        {append = {tool = "add_layer", args = {...}}}
            -> inserts a step before the first export / save step
    """
    out = [json.loads(json.dumps(l)) for l in lines]
    for p in patches or []:
        if "match" in p:
            m = dict(p["match"])
            tool = m.pop("tool", None)
            hit = 0
            for s in out:
                a = s.get("args", {})
                if (tool is None or s.get("tool") == tool) and all(_get(a, k) == v for k, v in m.items()):
                    for k, v in (p.get("set") or {}).items():
                        _set(a, k, v)
                    s["args"] = a
                    hit += 1
            if not hit:
                raise ValueError(f"pigment patch matched no step: {p['match']}")
        if "append" in p:
            at = next((i for i, s in enumerate(out) if s.get("tool") in ("export_textures", "export_variants", "save_project")),
                      len(out))
            out.insert(at, p["append"])
    return out


def _get(d, dotted):
    for k in dotted.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set(d, dotted, v):
    ks = dotted.split(".")
    for k in ks[:-1]:
        d = d.setdefault(k, {})
    d[ks[-1]] = v
