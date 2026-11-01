"""TOML for smart models: read with tomllib, write with this small, deterministic writer.

The writer handles what manifests use: tables, nested tables, strings, numbers, booleans,
arrays of scalars and arrays of inline tables. dump() then tomllib.loads() gives back an
equal dict (tested in tools/city/tests/test_manifest.py).
"""
import json
import math
import re
import tomllib

_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def loads(text: str) -> dict:
    return tomllib.loads(text)


def load(path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _key(k: str) -> str:
    return k if _BARE.match(k) else json.dumps(k, ensure_ascii=False)


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        r = repr(v)
        return r if ("." in r or "e" in r or "inf" in r) else r + ".0"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        raise TypeError("TOML has no null; drop the key instead")
    raise TypeError(f"not a TOML scalar: {type(v)}")


def _inline(v) -> str:
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_inline(x)}" for k, x in v.items() if x is not None) + " }" if v else "{}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_inline(x) for x in v) + "]"
    return _scalar(v)


def _array(v, indent="") -> str:
    items = [_inline(x) for x in v]
    one = "[" + ", ".join(items) + "]"
    if len(one) <= 100 and not any(isinstance(x, dict) for x in v):
        return one
    return "[\n" + "".join(f"{indent}  {s},\n" for s in items) + f"{indent}]"


def dumps(doc: dict, comments: dict | None = None) -> str:
    """comments: {"section": "text"} written above that [section]."""
    comments = comments or {}
    out = []

    def table(prefix, d):
        scalars = {k: v for k, v in d.items() if not isinstance(v, dict) and v is not None}
        tables = {k: v for k, v in d.items() if isinstance(v, dict)}
        if prefix:
            if out:
                out.append("")
            for line in (comments.get(prefix) or "").splitlines():
                out.append("# " + line if line else "#")
            out.append(f"[{prefix}]")
        for k, v in scalars.items():
            out.append(f"{_key(k)} = {_array(v) if isinstance(v, (list, tuple)) else _scalar(v)}")
        # small leaf tables of scalars read better inline (and must come before any [sub.table])
        nested = {}
        for k, v in tables.items():
            if not v:
                out.append(f"{_key(k)} = {{}}")
            elif prefix and all(not isinstance(x, (dict, list)) for x in v.values()) and len(_inline(v)) <= 90:
                out.append(f"{_key(k)} = {_inline(v)}")
            else:
                nested[k] = v
        for k, v in nested.items():
            table(f"{prefix}.{_key(k)}" if prefix else _key(k), v)

    top_scalars = {k: v for k, v in doc.items() if not isinstance(v, dict)}
    if top_scalars:
        table("", top_scalars)
    for k, v in doc.items():
        if isinstance(v, dict):
            table(_key(k), v)
    return "\n".join(out) + "\n"


def dump(doc: dict, path, header: str = "", comments: dict | None = None):
    text = "".join(f"# {line}\n" if line else "#\n" for line in header.splitlines()) + ("\n" if header else "")
    text += dumps(doc, comments)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
