"""Audit every decal record in every texture variant against real-world placement rules.

Reads the saved Pigment projects (scenes/town/projects/<asset>.pigment/project.json:
every recorded decal, scatters resolved to exact placements, plus the variant
definitions) or, for assets without a saved project, the generated script
(scenes/props/scripts/<prop>.jsonl). Geometry comes from the mesh itself (GLB
triangles + UVs) and Pigment's own part list (list_parts).

For every decal shown by any variant it checks:
  surface    the whole decal lies on ONE flat surface: rays cast at a 9 x 5 grid
             over the decal must hit a coplanar face at the decal's plane. A
             hole (window recess, door, bay) or an edge / corner under the decal,
             or anything in front of it (sill, ledge, band, AC unit, pipe, frame
             lip) is a violation, named after the part that was hit.
  billboard  billboard images only on a billboard panel (a vertical "panel"
             part >= 3 x 3 m inside its own frame part), except deliberate ghost
             signs (low opacity, heavy wear, no glow) on blank wall.
  kind       shop signs centred on a fascia / sign box over a ground-floor
             entrance; blade signs on a tall blade face; logos on a panel or
             fascia; plates centred 1.4-1.9 m up within 2.5 m of a door; posters
             within 0.8-2.2 m; graffiti within 0-3.2 m on wall, shutter or door.
  texels     texels across the decal's smaller side at the project resolution:
             >= 96 for readable signage (billboards, signs, blades, logos,
             plates); posters >= 20, graffiti and ghost signs >= 24 (coarse marks
             read at street distance; their fine print is not meant to).

    python tools/decal_audit.py                     (town buildings + overhead sign)
    python tools/decal_audit.py building_a props    (one asset; every prop script)
    python tools/decal_audit.py --json report.json  (also write the findings)

Exits 1 on any violation, listing each one.
"""
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import town_textures as T  # noqa: E402

TOWN = ["building_a", "building_b", "building_c", "overhead_sign"]
STORY_KINDS = ("billboard", "sign", "blade", "logo", "plate", "poster", "graffiti", "stencil")
MIN_TEXELS = {"billboard": 96, "shop": 96, "blade": 96, "logo": 96, "plate": 96, "poster": 20, "graffiti": 24, "ghost": 24}
GRID = (9, 5)


# ------------------------------------------------------------------ mesh

def load_glb(path):
    """(positions [n,3], uvs [n,2], triangles [m,3]) of every primitive, node transforms applied."""
    data = Path(path).read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    js = json.loads(data[20:20 + jlen])
    bin_ = data[20 + jlen + 8:]

    def acc(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[a["componentType"]]
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0)
        isz = np.dtype(dt).itemsize * n
        if stride and stride != isz:
            raw = np.frombuffer(bin_, np.uint8, count=stride * a["count"], offset=off).reshape(a["count"], stride)[:, :isz]
            return np.frombuffer(raw.tobytes(), dt).reshape(a["count"], n)
        return np.frombuffer(bin_, dt, count=a["count"] * n, offset=off).reshape(a["count"], n)

    P, U, I = [], [], []
    base = 0
    for node in js.get("nodes", []):
        if "mesh" not in node:
            continue
        M = np.eye(4)
        if "matrix" in node:
            M = np.array(node["matrix"]).reshape(4, 4).T
        else:
            t = node.get("translation", [0, 0, 0])
            q = node.get("rotation", [0, 0, 0, 1])
            s = node.get("scale", [1, 1, 1])
            x, y, z, w = q
            R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            M[:3, :3] = R * np.array(s)
            M[:3, 3] = t
        for prim in js["meshes"][node["mesh"]]["primitives"]:
            p = acc(prim["attributes"]["POSITION"]).astype(np.float64)
            p = p @ M[:3, :3].T + M[:3, 3]
            u = acc(prim["attributes"]["TEXCOORD_0"]).astype(np.float64) if "TEXCOORD_0" in prim["attributes"] else np.zeros((len(p), 2))
            i = acc(prim["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in prim else np.arange(len(p)).reshape(-1, 3)
            P.append(p)
            U.append(u)
            I.append(i + base)
            base += len(p)
    return np.concatenate(P), np.concatenate(U), np.concatenate(I)


class Mesh:
    def __init__(self, glb, parts):
        self.P, self.UV, self.I = load_glb(glb)
        a, b, c = (self.P[self.I[:, k]] for k in range(3))
        n = np.cross(b - a, c - a)
        self.area2 = np.linalg.norm(n, axis=1)
        self.N = n / np.maximum(self.area2, 1e-12)[:, None]
        self.A, self.B, self.C = a, b, c
        self.lo = np.minimum(np.minimum(a, b), c)
        self.hi = np.maximum(np.maximum(a, b), c)
        self.parts = parts
        self.ground = float(self.P[:, 1].min())
        self.tri_part = self._parts()
        if self.tri_part.max() + 1 != len(parts):
            raise SystemExit(f"{glb}: {self.tri_part.max() + 1} parts here vs {len(parts)} from Pigment")

    def _parts(self):
        """Pigment's parts (pigment_core::Mesh::parts): triangles join when they share a
        vertex index, or a welded edge used by exactly two triangles; ids by first appearance."""
        n = len(self.I)
        parent = np.arange(n)

        def find(x):
            r = x
            while parent[r] != r:
                r = parent[r]
            while parent[x] != r:
                parent[x], x = r, parent[x]
            return r

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        first = {}
        for t, tri in enumerate(self.I.tolist()):
            for v in tri:
                o = first.setdefault(v, t)
                if o != t:
                    union(o, t)
        lo, hi = self.P.min(0), self.P.max(0)
        c = (lo + hi) / 2
        r = float(np.linalg.norm(self.P - c, axis=1).max())
        q = 1e5 / max(r, 1e-6)
        keys = np.round(self.P.astype(np.float32).astype(np.float64) * q).astype(np.int64)
        _, weld = np.unique(keys, axis=0, return_inverse=True)
        weld = weld.reshape(-1)
        W = weld[self.I]
        edges = {}
        for t in range(n):
            for k in range(3):
                a, b = W[t, k], W[t, (k + 1) % 3]
                if a != b:
                    edges.setdefault((min(a, b), max(a, b)), []).append(t)
        for users in edges.values():
            if len(users) == 2:
                union(users[0], users[1])
        ids, out = {}, np.empty(n, np.int64)
        for t in range(n):
            out[t] = ids.setdefault(find(t), len(ids))
        return out

    def raycast(self, o, d, tmax, cand):
        """Nearest hit of rays (o [k,3], d [3]) against triangles `cand`: (t [k], tri [k]); t=inf if none."""
        A, B, C = self.A[cand], self.B[cand], self.C[cand]
        e1, e2 = B - A, C - A
        pv = np.cross(np.broadcast_to(d, e2.shape), e2)
        det = np.einsum("ij,ij->i", e1, pv)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tv = o[:, None, :] - A[None]                         # [k, m, 3]
        u = np.einsum("kmj,mj->km", tv, pv) * inv
        qv = np.cross(tv, e1[None])
        v = np.einsum("kmj,j->km", qv, d) * inv
        t = np.einsum("kmj,mj->km", qv, e2) * inv
        hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 0) & (t < tmax)
        t = np.where(hit, t, np.inf)
        j = np.argmin(t, axis=1)
        return t[np.arange(len(o)), j], cand[j]

    def part(self, pid):
        return next(p for p in self.parts if p["id"] == pid)

    def part_at(self, q, tol=0.012):
        """Smallest part whose bounds contain point q."""
        best = None
        for p in self.parts:
            c, s = np.array(p["center"]), np.array(p["size"])
            if np.all(np.abs(q - c) <= s / 2 + tol):
                v = float(np.prod(s + 0.01))
                if best is None or v < best[0]:
                    best = (v, p)
        return best[1] if best else None

    def texels(self, center, normal, right, up, w, h, res):
        """Texels across the decal (min of its two sides) from the UVs of the
        largest coplanar triangle under its centre."""
        cand = np.where((np.abs(self.N @ normal) > 0.9) & (self.area2 > 1e-8) &
                        np.all(self.lo <= center + 0.02, axis=1) & np.all(self.hi >= center - 0.02, axis=1))[0]
        best = None
        for t in cand:
            a, b, c = self.A[t], self.B[t], self.C[t]
            if abs(np.dot(center - a, self.N[t])) > 0.01:
                continue
            m = np.array([b - a, c - a]).T
            uv, *_ = np.linalg.lstsq(m, center - a, rcond=None)
            if uv.min() < -1e-4 or uv.sum() > 1 + 1e-4:
                continue
            if best is None or self.area2[t] > self.area2[best]:
                best = t
        if best is None:
            return None
        a, b, c = self.A[best], self.B[best], self.C[best]
        tri = self.I[best]
        m = np.array([b - a, c - a]).T
        uv = self.UV[tri]

        def to_uv(q):
            k, *_ = np.linalg.lstsq(m, q - a, rcond=None)
            return uv[0] + (uv[1] - uv[0]) * k[0] + (uv[2] - uv[0]) * k[1]
        su = np.linalg.norm(to_uv(center + right * w / 2) - to_uv(center - right * w / 2))
        sv = np.linalg.norm(to_uv(center + up * h / 2) - to_uv(center - up * h / 2))
        return float(min(su, sv) * res)


# ------------------------------------------------------------------ parts and shapes

def thin_axis(p):
    return int(np.argmin(p["size"]))


def is_billboard_panel(p, parts):
    """A vertical panel >= 3 x 3 m, <= 0.12 thick, inside a frame part (bounds
    0.1-0.5 m bigger on every in-plane side, sharing its plane)."""
    k = thin_axis(p)
    if k == 1 or p["size"][k] > 0.12:
        return False
    inplane = [i for i in range(3) if i != k]
    if min(p["size"][i] for i in inplane) < 3.0:
        return False
    for q in parts:
        if q is p:
            continue
        if abs(q["center"][k] - p["center"][k]) > 0.3 or q["size"][k] > 0.5:
            continue
        if all(0.1 <= q["size"][i] - p["size"][i] <= 1.0 and abs(q["center"][i] - p["center"][i]) < 0.05 for i in inplane):
            return True
    return False


def is_sign_box(p):
    """Fascia / sign box / plate: a small proud box, not a wall."""
    k = thin_axis(p)
    inplane = [p["size"][i] for i in range(3) if i != k]
    return k != 1 and p["size"][k] <= 0.5 and max(inplane) <= 8.5 and min(inplane) <= 1.5


def is_door(p):
    s = sorted(p["size"])
    bottom = p["center"][1] - p["size"][1] / 2
    return s[0] <= 0.1 and 0.8 <= s[1] <= 1.5 and 2.0 <= s[2] <= 2.8 and bottom < 0.6 and abs(p["size"][1] - s[2]) < 1e-6


def describe(p, parts):
    if p is None:
        return "nothing"
    k = T.classify(p)
    if is_door(p):
        k = "door"
    elif is_billboard_panel(p, parts):
        k = "billboard panel"
    return f"part {p['id']} ({k}, {p['size'][0]:.2f} x {p['size'][1]:.2f} x {p['size'][2]:.2f} m at {p['center'][0]:.2f}, {p['center'][1]:.2f}, {p['center'][2]:.2f})"


# ------------------------------------------------------------------ decal records

AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


def image_aspect(path):
    from PIL import Image
    with Image.open(ROOT / path) as im:
        return im.size[0] / im.size[1]


def frame(normal, rot_deg):
    """Placement::new: upright right / up axes on the surface, rotated about the normal."""
    n = np.array(normal, float)
    n /= np.linalg.norm(n)
    wu = np.array([0, 1.0, 0]) if abs(n[1]) < 0.9 else np.array([0, 0, -1.0])
    up0 = wu - n * np.dot(n, wu)
    up0 /= np.linalg.norm(up0)
    r0 = np.cross(up0, n)
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    return n, r0 * c + up0 * s, up0 * c - r0 * s


def geometry(args, parts):
    """(centre, normal, right, up, w, h) of a decal record, or a reason it can't be placed exactly."""
    image = args["image"]
    if "position" in args:
        size = args.get("size", 0.5)
        if isinstance(size, list):
            w, h = size
        else:
            w = size
            h = w / image_aspect(image)
        n, r, u = frame(args["normal"], args.get("rotation", 0.0))
        return np.array(args["position"], float), n, r, u, w, h
    if ("part" in args and args.get("facing")) or "box" in args:
        # legacy camera-aimed fits: the image fitted on a part's face or a world box's face
        # (approximated as the planar rect Pigment aims at; perspective is ignored)
        if "box" in args:
            b = args["box"]
            lo, hi = (np.array(b["min"], float), np.array(b["max"], float)) if "min" in b else                 (np.array(b["center"]) - np.abs(b["size"]) / 2, np.array(b["center"]) + np.abs(b["size"]) / 2)
            center, size = (lo + hi) / 2, hi - lo
            f = args.get("facing") or ("+" + "xyz"[int(np.argmin(size))])
        else:
            p = next((q for q in parts if q["id"] == args["part"]), None)
            if p is None:
                return f"no part {args['part']}"
            center, size, f = np.array(p["center"], float), np.array(p["size"], float), args["facing"]
        nn = AXES[f]
        k = [abs(x) for x in nn].index(1)
        c = center.copy()
        c[k] += nn[k] * size[k] / 2
        W, H = (size[0], size[2]) if k == 1 else ((size[2] if k == 0 else size[0]), size[1])
        m = args.get("margin", 0.05)
        asp = image_aspect(args["image"])
        w, h = W * (1 - 2 * m), H * (1 - 2 * m)
        if args.get("fit", "contain") == "contain":
            w, h = (w, w / asp) if w / asp <= h else (h * asp, h)
        n, r, u = frame(nn, 0)
        return c, n, r, u, w, h
    return "camera-projected (rect) decal: no exact placement to check"


def kind_of(name, args):
    stem = Path(args["image"]).stem
    ghostly = args.get("opacity", 1.0) <= 0.5 and args.get("fade", 0) >= 0.5 and not args.get("emissive_strength")
    if stem.startswith("billboard"):
        return "ghost" if (name.startswith("ghost/") or ghostly) else "billboard"
    if stem.startswith(("blade", "banner")):          # banner_*: a lit full-colour banner on a blade face
        return "blade"
    if stem.startswith("sign"):
        return "shop"
    if stem.startswith("logo"):
        return "logo"
    if stem.startswith("plate"):
        return "plate"
    if stem.startswith(("poster", "flyer", "sticker")):   # paper at street level (ads: assets/decals/ads)
        return "poster"
    if stem.startswith(("graffiti", "stencil")):
        return "graffiti"
    return "other"


def resolve(records, d):
    """Names of the records a variant shows (disable, then enable; selectors are names, groups or "*")."""
    on = {}
    for r in records:
        on[id(r)] = r["enabled"]
    def match(sel, r):
        sel = sel.lower()
        return (sel == "*" and r["group"]) or sel == r["name"].lower() or (r["group"] and sel == r["group"].lower())
    for sel in d.get("disable", []):
        for r in records:
            if match(sel, r):
                on[id(r)] = False
    for sel in d.get("enable", []):
        for r in records:
            if match(sel, r):
                on[id(r)] = True
    return [r for r in records if on[id(r)]]


def load_project(asset):
    """(mesh path, resolution, records, variant defs) from a saved project, else from the script."""
    pj = ROOT / "scenes" / "town" / "projects" / f"{asset}.pigment" / "project.json"
    if pj.exists():
        d = json.loads(pj.read_text(encoding="utf8"))
        recs = [dict(r, layer=l["name"]) for l in d["layers"] for r in (l.get("variant") or {}).get("decals", [])]
        defs = (d.get("variants") or {}).get("defs", [])
        return pj.parent / d["mesh"], d["resolution"], recs, defs
    for script in (ROOT / "scenes" / "props" / "scripts" / f"{asset}.jsonl", ROOT / "scenes" / "town" / "scripts" / f"{asset}.jsonl"):
        if script.exists():
            break
    else:
        raise SystemExit(f"{asset}: no project or script")
    lines = [json.loads(l) for l in script.read_text(encoding="utf8").splitlines() if l.strip()]
    mesh = res = None
    recs, defs = [], []
    for l in lines:
        a = l["args"]
        if l["tool"] == "new_project":
            mesh, res = ROOT / a["mesh"], a.get("resolution", 2048)
        elif l["tool"] == "project_decal" and not a.get("mask"):
            args = {k: v for k, v in a.items() if k not in ("layer", "name", "variant", "enabled")}
            recs.append({"name": a.get("name", Path(a["image"]).stem), "group": a.get("variant", ""), "enabled": a.get("enabled", True), "args": args, "layer": a.get("layer", "")})
        elif l["tool"] == "scatter_decals":
            raise SystemExit(f"{asset}: scatter in a script without a saved project (run the script first)")
        elif l["tool"] == "export_variants":
            defs = a.get("variants", [])
    return mesh, res, recs, defs


# ------------------------------------------------------------------ checks

def check_surface(mesh, c, n, r, u, w, h, curved=False):
    """Rays at a grid over the decal must all land on the host part (the part
    under its centre), on a face coplanar with the decal (`curved`: any face of
    the host that still faces the decal, for stickers wrapped on poles and
    tanks), with nothing in front. Returns (host part id, problems)."""
    gx, gy = GRID
    xs = (np.linspace(-0.5, 0.5, gx) * (w - 0.03)) if w > 0.06 else np.zeros(gx)
    ys = (np.linspace(-0.5, 0.5, gy) * (h - 0.03)) if h > 0.06 else np.zeros(gy)
    pts = np.array([c] + [c + r * x + u * y for y in ys for x in xs])
    reach = 0.6
    ends = np.concatenate([pts + n * reach, pts - n * 0.3])
    lo, hi = ends.min(0) - 0.01, ends.max(0) + 0.01
    cand = np.where(np.all(mesh.hi >= lo, axis=1) & np.all(mesh.lo <= hi, axis=1) & (mesh.area2 > 1e-10))[0]
    if len(cand) == 0:
        return None, [("off the mesh", None, pts[0])]
    t, tri = mesh.raycast(pts + n * reach, -n, reach + 0.3, cand)
    if not np.isfinite(t[0]):
        return None, [("no surface under the decal's centre", None, pts[0])]
    host = int(mesh.tri_part[tri[0]])
    bad = []
    for k in range(1, len(pts)):
        if not np.isfinite(t[k]):
            bad.append(("over an opening or past an edge", None, pts[k]))
            continue
        q = pts[k] + n * (reach - t[k])
        off = reach - t[k]                      # >0: hit in front of the decal plane
        pid = int(mesh.tri_part[tri[k]])
        facing = float(np.dot(mesh.N[tri[k]], n))
        if pid != host:
            what = "covered by" if off > 0.004 else "over a recess / opening at" if off < -0.004 else "crosses onto"
            bad.append((what, mesh.part(pid), q))
        elif curved:
            if abs(facing) < 0.2 or abs(off) > 0.15:
                bad.append(("wraps off the face of", mesh.part(pid), q))
        elif abs(off) > 0.004 or abs(facing) < 0.9:
            bad.append(("over a recess or edge of", mesh.part(pid), q))
    return host, bad


def audit_asset(asset, report):
    glb, res, recs, defs = load_project(asset)
    parts = T.parts_of(asset) if (ROOT / "assets" / "town" / f"{asset}.glb").exists() else parts_of_mesh(glb)
    mesh = Mesh(glb, parts)
    doors = [p for p in parts if is_door(p)]
    shown = {}
    for d in defs or [{"name": "(authored)", "disable": [], "enable": []}]:
        for r in resolve(recs, d):
            shown.setdefault(id(r), (r, []))[1].append(d["name"])
    if not defs:
        for r in recs:
            shown.setdefault(id(r), (r, ["(authored)"]))
    out = []
    for r, variants in shown.values():
        args, name = r["args"], r["name"]
        kind = kind_of(name, args)
        g = geometry(args, parts)
        v = []
        entry = {"asset": asset, "name": name, "image": Path(args["image"]).stem, "kind": kind, "variants": variants}
        if isinstance(g, str):
            v.append(g)
            entry.update(violations=v)
            out.append(entry)
            continue
        c, n, rr, u, w, h = g
        # snap the centre onto the surface along the normal (as Pigment does)
        cand = np.where(np.all(mesh.hi >= c - 0.6, axis=1) & np.all(mesh.lo <= c + 0.6, axis=1))[0]
        t, _ = mesh.raycast((c + n * 0.5)[None], -n, 1.0, cand) if len(cand) else (np.array([np.inf]), None)
        if np.isfinite(t[0]):
            c = c + n * 0.5 - n * t[0]
        bottom = float(c[1] - abs(u[1]) * h / 2 - abs(rr[1]) * w / 2 - mesh.ground)
        top = float(c[1] + abs(u[1]) * h / 2 + abs(rr[1]) * w / 2 - mesh.ground)
        mid = float(c[1] - mesh.ground)
        hid, problems = check_surface(mesh, c, n, rr, u, w, h, curved=asset not in TOWN)
        host = mesh.part(hid) if hid is not None else None
        entry.update(center=[round(float(x), 3) for x in c], size=[round(w, 3), round(h, 3)], host=hid,
                     band=[round(bottom, 2), round(top, 2)])
        for why, p, q in problems[:3]:
            v.append(f"{why} {describe(p, parts) if p else ''} at ({q[0]:.2f}, {q[1]:.2f}, {q[2]:.2f})".replace("  ", " "))
        story = Path(args["image"]).parent.name in ("story", "ads") or Path(args["image"]).stem.startswith("logo")
        if story and host is not None:
            if kind == "billboard" and not is_billboard_panel(host, parts):
                v.append(f"billboard image on {describe(host, parts)}, not on a framed billboard panel")
            if kind == "ghost":
                if is_sign_box(host) or is_billboard_panel(host, parts):
                    v.append("ghost sign on a sign part (ghost signs are painted on blank wall)")
                if args.get("opacity", 1) > 0.5 or args.get("fade", 0) < 0.5 or args.get("wear", 0) < 0.3 or args.get("emissive_strength"):
                    v.append("ghost sign is not faded enough (opacity <= 0.5, fade >= 0.5, wear >= 0.3, no glow)")
            if kind == "shop":
                hanging = asset == "overhead_sign"
                if not (is_sign_box(host) or (hanging and host["size"][thin_axis(host)] <= 0.05)):
                    v.append(f"shop sign on {describe(host, parts)}, not on a fascia / sign box")
                else:
                    hb = host["center"][1] - host["size"][1] / 2 - mesh.ground
                    if not hanging and not (2.0 <= hb <= 6.5):
                        v.append(f"sign box bottom at {hb:.2f} m: not over a ground-floor entrance")
                    k = thin_axis(host)
                    hc = np.array(host["center"])
                    off = [abs(float((c - hc)[i])) for i in range(3) if i != k]
                    if max(off) > 0.05:
                        v.append(f"shop sign not centred on its sign box (off by {max(off):.2f} m)")
            if kind == "blade":
                k = thin_axis(host)
                wide = max(host["size"][i] for i in range(3) if i not in (k, 1))
                if not (host["size"][1] >= 3.0 and wide <= 1.3 and host["size"][k] <= 0.35):
                    v.append(f"blade sign on {describe(host, parts)}, not on a blade sign face")
            if kind == "logo" and not (is_sign_box(host) or is_billboard_panel(host, parts)):
                v.append(f"logo on {describe(host, parts)}, not on a crown panel or fascia")
            if kind == "plate":
                if not (1.4 <= mid <= 1.9):
                    v.append(f"plate centre at {mid:.2f} m (eye height is 1.4-1.9 m)")
                dist = min((np.linalg.norm(np.maximum(np.abs(c - np.array(p["center"])) - np.array(p["size"]) / 2, 0)) for p in doors), default=99)
                if dist > 2.5:
                    v.append(f"plate {dist:.1f} m from the nearest door (must be beside one, <= 2.5 m)")
            if kind == "poster" and not (bottom >= 0.8 - 1e-3 and top <= 2.2 + 1e-3):
                v.append(f"poster spans {bottom:.2f}-{top:.2f} m (street level is 0.8-2.2 m)")
            if kind == "graffiti" and not (bottom >= 0.0 and top <= 3.2):
                v.append(f"graffiti spans {bottom:.2f}-{top:.2f} m (ground level up to ~3 m)")
            if kind in ("poster", "graffiti", "plate", "ghost") and is_billboard_panel(host, parts):
                v.append(f"{kind} on a billboard panel")
        tex = mesh.texels(c, n, rr, u, w, h, res)
        entry["texels"] = round(tex) if tex is not None else None
        need = MIN_TEXELS.get(kind) if story else None
        if need and tex is not None and tex < need:
            v.append(f"only {tex:.0f} texels across at {res}px (needs >= {need} for a {kind})")
        entry["violations"] = v
        out.append(entry)
    report.extend(out)
    return out


_MESH_PARTS = {}


def parts_of_mesh(glb):
    """list_parts for any mesh path (props)."""
    key = str(glb)
    if key not in _MESH_PARTS:
        rel = Path(glb).resolve().relative_to(ROOT).as_posix()
        o = T.run([{"tool": "new_project", "args": {"mesh": rel, "resolution": 512}}, {"tool": "list_parts", "args": {}}], "audit_parts")
        _MESH_PARTS[key] = json.loads(o[o.index("[list_parts] ") + 13:])
    return _MESH_PARTS[key]


def main(argv):
    out_json = None
    if "--json" in argv:
        i = argv.index("--json")
        out_json = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    assets = []
    for a in argv or TOWN:
        if a == "props":
            assets += sorted(p.stem for p in (ROOT / "scenes" / "props" / "scripts").glob("*.jsonl"))
        else:
            assets.append(a)
    T.TMP = Path(os.environ.get("PIG_TMP", T.TMP))
    T.TMP.mkdir(parents=True, exist_ok=True)
    report = []
    bad = 0
    for asset in assets:
        rows = audit_asset(asset, report)
        nv = sum(1 for e in rows if e["violations"])
        bad += nv
        kinds = {}
        for e in rows:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        tex = [e["texels"] for e in rows if e.get("texels") is not None]
        print(f"{asset}: {len(rows)} decals ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}); "
              f"min texels {min(tex) if tex else '-'}; {nv} with violations")
        for e in rows:
            for msg in e["violations"]:
                print(f"  VIOLATION {e['name']} [{e['kind']}] ({', '.join(e['variants'][:3])}{'...' if len(e['variants']) > 3 else ''}): {msg}")
    if out_json:
        Path(out_json).write_text(json.dumps(report, indent=1), encoding="utf8")
    print(f"\n{len(report)} decal records in {len(assets)} assets: {bad} with violations")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
