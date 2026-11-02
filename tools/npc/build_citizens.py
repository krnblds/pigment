"""Build the game's citizens with MPFB in headless Blender 5.2.

    blender -b --factory-startup --python tools/npc/build_citizens.py -- [--only id,id] [--out .npccache/citizens]

(--factory-startup is fine: the script enables the installed MPFB extension itself.)

Per recipe (tools/npc/recipes.py) it
  1. builds the MPFB human: phenotype, the low-poly body proxy (male1591 / female1605), "game_engine" rig
     (UE-mannequin bone names -> game/scripts/npc/character/bonemap_mpfb.tres), skin, eyes, eyebrows, hair,
     CC0 clothes; the basemesh is dropped (the proxy is the body), clothes delete-groups hide the body;
  2. adds the procedural outer layer ("shell"): the body proxy's torso/arms pushed out and smoothed into a
     jacket / bomber / hoodie / hi-vis vest / raincoat / coat, a lofted coat skirt rigged to the pelvis and
     thighs, collar or hood, and for the Wakers a temple-mounted resonance band; everything under the shell
     (body, shirts) is deleted, so nothing pokes through;
  3. lays every part into one 1024 atlas (UV cells; compose_atlas.py paints it: textures, tints, trims,
     emission / wetness / roughness masks) and merges the parts into one skinned mesh (2 surfaces:
     opaque + alpha-cut hair/brows) - LOD0 ~8-14k tris;
  4. LOD1: the same, decimated to ~2.6k tris (same skeleton);  LOD2: ~360 tris, arms down, unskinned,
     vertex colours tell the crowd shader which vertices are legs / arms (cheap walk sway);
  5. exports <out>/<id>.glb (Armature + LOD0 + LOD1 + LOD2) and <out>/<id>.json (atlas spec + metrics).
"""
import bpy
import bmesh
import json
import math
import os
import sys
import glob
import random
import time
import zlib
from mathutils import Vector, Matrix

import addon_utils

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import recipes as R  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


OUT = os.path.abspath(arg("--out", os.path.join(ROOT, ".npccache", "citizens")))
ONLY = set(filter(None, (arg("--only", "") or "").split(",")))
COUNT = int(arg("--count", "32"))
SEED = int(arg("--seed", "2077"))
ATLAS = 1024
LOD0_MAX = 14000
LOD1_TRIS = 2600
LOD2_TRIS = 360

addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
from bl_ext.user_default.mpfb.services.humanservice import HumanService  # noqa: E402
from bl_ext.user_default.mpfb.services.assetservice import AssetService  # noqa: E402
from bl_ext.user_default.mpfb.services.locationservice import LocationService  # noqa: E402

MPFB_DATA = LocationService.get_user_data()
SYS_DATA = None

TORSO = ("pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r")
ARMS = ("upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r")
HEAD = ("head", "neck_01")
LEGS_L = ("thigh_l", "calf_l", "foot_l", "ball_l")
LEGS_R = ("thigh_r", "calf_r", "foot_r", "ball_r")


def log(*a):
    print("[citizens]", *a, flush=True)


# ------------------------------------------------------------------ assets
def asset(kind, names):
    """First of `names` MPFB can find in <data>/<kind>/<name>/<name>.mhclo (or .proxy) whose header says CC0."""
    for n in names:
        if not n:
            continue
        ext = ".proxy" if kind == "proxymeshes" else ".mhclo"
        p = AssetService.find_asset_absolute_path(f"{n}/{n}{ext}", asset_subdir=kind)
        if p and os.path.isfile(p) and licence_ok(p):
            return n, p
    return None, None


def licence_ok(path):
    """Only assets whose own header declares CC0 (packs also hold AGPL / CC-BY headed items: skipped)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = "".join(l for l in f.readlines()[:12] if l.startswith("#")).lower()
    except OSError:
        return False
    return "cc0" in head and not any(k in head for k in ("agpl", "cc-by", "cc by", "-nc", "gpl"))


CREDITS = {}


def credit(path):
    """'author' line of an asset header (for docs/agents/npc/NOTES.md)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for l in f.readlines()[:12]:
                if l.lower().startswith("# author"):
                    return l.split(None, 2)[2].strip()
                if l.startswith("# ") and " - cc0" in l.lower():
                    return l[2:].lower().split(" - cc0")[0].strip().title()
    except OSError:
        pass
    return "MakeHuman team (system assets)"


def find_keyword(kind, words, exclude=()):
    """Clothes from the packs by keyword (caps, masks, glasses): CC0 only, sorted for determinism."""
    out = []
    for p in sorted(glob.glob(os.path.join(MPFB_DATA, kind, "*", "*.mhclo"))):
        n = os.path.splitext(os.path.basename(p))[0].lower()
        if any(w in n for w in words) and not any(e in n for e in exclude) and licence_ok(p):
            out.append(os.path.splitext(os.path.basename(p))[0])
    return out


# ------------------------------------------------------------------ scene
def reset():
    _TRUNK.clear()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.armatures, bpy.data.materials, bpy.data.images, bpy.data.actions):
        for d in list(coll):
            coll.remove(d)


def tris(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def bake_object(o):
    """Shape keys -> mesh, apply every modifier but the armature."""
    if o.data.shape_keys:
        o.shape_key_add(name="mix", from_mix=True)
        for k in list(o.data.shape_keys.key_blocks):
            o.shape_key_remove(k)
    for m in list(o.modifiers):
        if m.type != "ARMATURE":
            with bpy.context.temp_override(object=o, active_object=o):
                bpy.ops.object.modifier_apply(modifier=m.name)


def vweights(o):
    """Per vertex {group name: weight}."""
    names = {g.index: g.name for g in o.vertex_groups}
    return [{names[g.group]: g.weight for g in v.groups if g.group in names} for v in o.data.vertices]


def wsum(w, keys):
    return sum(w.get(k, 0.0) for k in keys)


def image_of(mat, kind):
    """Diffuse / normal image file used by an MPFB game-engine material."""
    if not mat or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            fp = bpy.path.abspath(n.image.filepath)
            low = os.path.basename(fp).lower()
            is_n = "normal" in low or (n.image.colorspace_settings.name.lower() in ("non-color", "linear") and "_n." in low)
            if (kind == "normal") == is_n and os.path.isfile(fp):
                return fp
    return None


def metrics(arm):
    b = arm.data.bones
    g = lambda n, tail=False: arm.matrix_world @ (b[n].tail_local if tail else b[n].head_local)  # noqa: E731
    return {"pelvis": g("pelvis"), "neck": g("neck_01"), "head": g("head"), "head_top": g("head", True),
            "knee_l": g("calf_l"), "knee_r": g("calf_r"), "ankle_l": g("foot_l"), "ankle_r": g("foot_r"),
            "wrist_l": g("hand_l"), "wrist_r": g("hand_r"), "shoulder_l": g("upperarm_l"), "shoulder_r": g("upperarm_r"),
            "elbow_l": g("lowerarm_l"), "elbow_r": g("lowerarm_r"), "spine3": g("spine_03"), "thigh_l": g("thigh_l"), "thigh_r": g("thigh_r")}


# ------------------------------------------------------------------ human
def build_human(rc):
    info = HumanService._create_default_human_info_dict()
    ph = dict(rc["phenotype"])
    race = ph.pop("race")
    info["phenotype"].update(ph)
    info["phenotype"]["race"] = race
    info["rig"] = "game_engine"
    proxy = "male1591" if rc["sex"] == "male" else "female1605"
    info["proxy"] = f"{proxy}/{proxy}.proxy"
    info["eyes"] = "low-poly/low-poly.mhclo"
    info["eyebrows"] = "eyebrow00%d/eyebrow00%d.mhclo" % ((zlib.crc32(rc["id"].encode()) % 9) + 1, (zlib.crc32(rc["id"].encode()) % 9) + 1)
    used = {"proxy": proxy}
    skin = None
    for s in rc["skin"]:
        p = AssetService.find_asset_absolute_path(f"{s}/{s}.mhmat", asset_subdir="skins")
        if p:
            skin = s
            break
    info["skin_mhmat"] = f"{skin}/{skin}.mhmat" if skin else ""
    used["skin"] = skin
    hat = None
    for a in rc.get("accessories", []):
        if a in ("cap", "hat"):
            hat = a
    hair_names = list(rc["hair"])
    if hat:                               # short hair under hats (no poke-through)
        hair_names = ["short02", "short04", "short01"] if rc["sex"] == "male" else ["bob02", "short01", "bob01"]
    hn, hp = asset("hair", hair_names)
    if hn:
        info["hair"] = f"{hn}/{hn}.mhclo"
    used["hair"] = hn
    used["credits"] = {}
    if hn:
        used["credits"][hn] = credit(hp)
    clothes = []
    for cands in rc["clothes"]:
        n, p = asset("clothes", cands)
        if n and n not in clothes:
            clothes.append(n)
            used["credits"][n] = credit(p)
    rng = random.Random(rc["id"])
    for a in rc.get("accessories", []):
        pool = {"cap": find_keyword("clothes", ["newsboy_cap", "cap"], ("cape", "capri", "xmas", "santa", "party", "propeller", "jester", "maga")), "hat": ["fedora01", "fedora_cocked", "aethelraed_unraed_cloche_hat"],
                "mask": find_keyword("clothes", ["mouth_protection", "face_mask", "surgical"], ("hero", "bag")),
                "glasses": find_keyword("clothes", ["glasses", "sunglass"], ("leopard", "heart", "star", "party", "3d", "doc_ock"))}.get(a)
        if pool:
            n, p = asset("clothes", [rng.choice(pool)] + pool)
            if n:
                clothes.append(n)
                used["credits"][n] = credit(p)
    info["clothes"] = [f"{c}/{c}.mhclo" for c in clothes]
    used["clothes"] = clothes
    for k in ("skin_material_type", "eyes_material_type", "clothes_material_type"):
        info[k] = "GAMEENGINE"
    info["name"] = rc["id"]
    st = HumanService.get_default_deserialization_settings()
    st["subdiv_levels"] = 0
    basemesh = HumanService.deserialize_from_dict(info, st)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    arm.name = "Armature"
    arm.data.name = "Armature"
    parts = []
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            continue
        if o == basemesh:
            continue
        nm = o.name.lower()
        if proxy in nm:
            cat = "body"
        elif "low-poly" in nm or "eye" in nm and "brow" not in nm and "glass" not in nm:
            cat = "eyes"
        elif "eyebrow" in nm:
            cat = "brows"
        elif hn and hn.lower() in nm:
            cat = "hair"
        else:
            cat = "clothes"
            for c in clothes:
                if c.lower() in nm:
                    cat = "shoes" if c.startswith("shoes") else ("acc" if any(k in c.lower() for k in ("cap", "fedora", "mask", "glass", "hat")) else "clothes")
        parts.append([o, cat, next((c for c in clothes if c.lower() in nm), hn if cat == "hair" else cat)])
    # the proxy, before its delete groups are applied, is the template for the shell
    body = next(p[0] for p in parts if p[1] == "body")
    template = body.copy()
    template.data = body.data.copy()
    template.name = "shell_template"
    bpy.context.scene.collection.objects.link(template)
    for m in list(template.modifiers):
        if m.type == "MASK":
            template.modifiers.remove(m)
    bpy.data.objects.remove(basemesh, do_unlink=True)
    for p in parts:
        bake_object(p[0])
    bake_object(template)
    return arm, parts, template, used


# ------------------------------------------------------------------ shell
SHELL_CUT = {"jacket": 0.01, "bomber": 0.05, "hoodie": -0.03, "hivis": 0.0, "raincoat": -0.05, "coat": -0.03}
SHELL_OFF = {"jacket": 0.02, "bomber": 0.03, "hoodie": 0.026, "hivis": 0.022, "raincoat": 0.028, "coat": 0.024}


def in_shell(w, co, M, kind, tight=0.0):
    """Is this body vertex covered by the shell?  tight > 0 shrinks the region (for deleting what's under)."""
    hand = sum(v for k, v in w.items() if k.startswith(("hand", "thumb", "index", "middle", "ring", "pinky")))
    head = wsum(w, ("head",)) + 0.5 * wsum(w, ("neck_01",))
    t = wsum(w, TORSO)
    a = wsum(w, ARMS)
    legs = wsum(w, LEGS_L + LEGS_R)
    if hand > 0.3 - tight * 4 or head > 0.35 - tight:
        return False
    if t + a < 0.45 + tight or legs > 0.55 - tight:
        return False
    if kind == "hivis" and a > 0.45:
        return False
    cut = M["pelvis"].z + SHELL_CUT[kind]
    if co.z < cut + tight * 0.5 or co.z > M["neck"].z + 0.02 - tight * 0.4:
        return False
    # sleeves end a little before the wrist joint
    for s in ("l", "r"):
        wr = M["wrist_" + s]
        el = M["elbow_" + s]
        if a > 0.3 and (co - wr).length < 0.035 + tight * 0.6 and (co - el).length > (wr - el).length * 0.6:
            return False
    return True


def make_shell(template, arm, M, spec):
    kind = spec["kind"]
    o = template.copy()
    o.data = template.data.copy()
    o.name = "shell"
    bpy.context.scene.collection.objects.link(o)
    W = vweights(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    keep = [in_shell(W[v.index], v.co, M, kind) for v in bm.verts]
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not all(keep[v.index] for v in f.verts)], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.normal_update()
    off = SHELL_OFF[kind]
    for v in bm.verts:
        v.co += v.normal * off
    inner = [v for v in bm.verts if not v.is_boundary]
    bmesh.ops.smooth_vert(bm, verts=inner, factor=0.6, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bmesh.ops.smooth_vert(bm, verts=inner, factor=0.4, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * 0.004
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


_TRUNK = {}


def _trunk(template):
    """The body's trunk + legs + head vertices (not the arms / hands hanging beside them)."""
    if template.name not in _TRUNK:
        W = vweights(template)
        _TRUNK[template.name] = [v.co.copy() for v, w in zip(template.data.vertices, W)
                                 if wsum(w, TORSO + LEGS_L + LEGS_R + HEAD) > 0.7]
    return _TRUNK[template.name]


def cross_section(template, z, band=0.02, side=None):
    """Convex hull of the trunk at height z."""
    pts = [(c.x, c.y) for c in _trunk(template) if abs(c.z - z) < band and (side is None or c.x * side > -0.01)]
    if len(pts) < 3:
        return None
    pts = sorted(set(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def ring(hull, cx, cy, n, grow, squash_front=0.0):
    """n points around a convex hull (ray from the centre), pushed out by grow."""
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        d = Vector((math.cos(a), math.sin(a)))
        best = 0.05
        for k in range(len(hull)):
            p, q = Vector(hull[k]), Vector(hull[(k + 1) % len(hull)])
            e = q - p
            den = d.x * e.y - d.y * e.x
            if abs(den) < 1e-9:
                continue
            o = p - Vector((cx, cy))
            t = (o.x * e.y - o.y * e.x) / den
            u = (o.x * d.y - o.y * d.x) / den
            if t > 0 and -1e-6 <= u <= 1 + 1e-6:
                best = max(best, t)
        r = best + grow
        if squash_front and d.y < 0:                       # MPFB front is -Y
            r -= squash_front * (-d.y)
        out.append((cx + d.x * r, cy + d.y * r))
    return out


def loft(name, rings_xyz, weights, uv_rect, closed=True, cap=False):
    """Quad strip mesh between rings; weights[ring][i] = {group: w}; uv in a cell sub-rect (u0, v0, u1, v1)."""
    me = bpy.data.meshes.new(name)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    bm = bmesh.new()
    nr = len(rings_xyz)
    n = len(rings_xyz[0])
    vs = [[bm.verts.new(p) for p in r] for r in rings_xyz]
    bm.verts.index_update()
    uvl = bm.loops.layers.uv.new("UVMap")
    u0, v0, u1, v1 = uv_rect
    m = n if closed else n - 1
    for j in range(nr - 1):
        for i in range(m):
            i2 = (i + 1) % n
            f = bm.faces.new((vs[j][i], vs[j][i2], vs[j + 1][i2], vs[j + 1][i]))
            for lp, (ii, jj) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uvl].uv = (u0 + (u1 - u0) * ii / m, v1 - (v1 - v0) * jj / max(1, nr - 1))
    for f in bm.faces:
        f.smooth = True
    bm.normal_update()
    # outward normals: compare with the radial direction
    c = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    flip = sum((f.calc_center_median() - c).dot(f.normal) for f in bm.faces) < 0
    if flip:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    for j, r in enumerate(weights):
        for i, w in enumerate(r):
            for g, val in w.items():
                if val <= 0:
                    continue
                vg = o.vertex_groups.get(g) or o.vertex_groups.new(name=g)
                vg.add([j * n + i], val, "REPLACE")
    return o


def make_skirt(template, M, spec, uv_rect):
    """Coat / raincoat tail: lofted rings from the waist to the hem, rigged to pelvis + thighs."""
    L = spec.get("length") or (0.42 if spec["kind"] == "raincoat" else 0.6)
    top = M["pelvis"].z + 0.03
    ank = (M["ankle_l"].z + M["ankle_r"].z) * 0.5
    hem = M["pelvis"].z - L * (M["pelvis"].z - ank)
    fs = [0.0, 0.16, 0.33, 0.5, 0.66, 0.82, 0.96, 1.0]
    n = 32
    rings, weights = [], []
    # smooth ellipses round the trunk + legs bounding box (the low-poly proxy is too sparse for hulls)
    pts = [c for c in _trunk(template)]
    ax = ay = 0.0
    cyl = None
    for j, f in enumerate(fs):
        z = top + (hem - top) * f
        band = [c for c in pts if abs(c.z - z) < 0.045] or band
        x0, x1 = min(c.x for c in band), max(c.x for c in band)
        y0, y1 = min(c.y for c in band), max(c.y for c in band)
        cx = 0.0
        cy = (y0 + y1) * 0.5 if cyl is None else cyl
        cyl = cy if cyl is None else cyl * 0.7 + (y0 + y1) * 0.15
        grow = 0.025 + 0.02 * f + 0.02 * f * f
        ax = max(ax * 0.995, max(abs(x0), abs(x1)) * 1.1 + grow)
        ay = max(ay * 0.995, (y1 - y0) * 0.5 * 1.3 + grow)
        ring_pts = [(cx + math.cos(2 * math.pi * i / n) * ax, cy + math.sin(2 * math.pi * i / n) * ay) for i in range(n)]
        rings.append([(x, y, z) for x, y in ring_pts])
        wr = []
        for x, _ in ring_pts:
            s_ = min(1.0, max(0.0, 0.5 + 0.5 * x / ax))   # 1 = left (+x), 0 = right
            legw = 0.85 * min(1.0, f * 1.4)
            wr.append({"pelvis": 1.0 - legw, "thigh_l": legw * s_, "thigh_r": legw * (1.0 - s_)})
        weights.append(wr)
    return loft("skirt", rings, weights, uv_rect)


def make_collar(template, M, spec, uv_rect):
    kind = spec["kind"]
    z0 = M["neck"].z - 0.025
    hull = cross_section(template, z0, 0.02)
    if hull is None:
        return None
    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)
    n = 18
    rings, weights = [], []
    if kind == "hoodie":       # hood down: a soft roll lying round the neck, fat at the back
        base = ring(hull, cx, cy, n, 0.012)
        m = 8
        tube = []
        for k in range(m + 1):
            a = 2 * math.pi * k / m
            tube.append((math.cos(a), math.sin(a)))
        for kk, (ca, sa) in enumerate(tube):
            row = []
            for (x, y) in base:
                d = Vector((x - cx, y - cy))
                L = d.length or 1.0
                d /= L
                back = max(0.0, d.y)                 # +Y is the back
                r = 0.016 + 0.034 * back ** 1.5
                c = Vector((x, y)) + d * r + Vector((0, 0.012 * back))
                z = z0 - 0.01 - 0.03 * back
                p3 = (c.x + d.x * r * ca, c.y + d.y * r * ca, z + r * sa * 1.1)
                row.append(p3)
            rings.append(row)
            weights.append([{"spine_03": 0.75, "neck_01": 0.25}] * n)
    else:                      # coat / raincoat: an upright collar
        for dz, grow in ((-0.015, 0.018), (0.035, 0.026), (0.075, 0.036)):
            pts = ring(hull, cx, cy, n, grow)
            rings.append([(x, y, z0 + dz) for x, y in pts])
            weights.append([{"spine_03": 0.5, "neck_01": 0.5}] * n)
    return loft("collar", rings, weights, uv_rect)


def make_band(M, head_obj_pts, uv_rect):
    """Waker resonance band: a slim arc over the left ear, emissive cyan."""
    # temple centre: left side of the head at eye height
    zc = M["head"].z + (M["head_top"].z - M["head"].z) * 0.32
    side = [p for p in head_obj_pts if abs(p.z - zc) < 0.02 and p.x > 0]
    if not side:
        return None
    xs = max(p.x for p in side) + 0.006
    yc = sum(p.y for p in side) / len(side) + 0.01
    rings, weights = [], []
    n = 6
    for j, t in enumerate([i / 9 for i in range(10)]):
        a = math.radians(-60 + 200 * t)                   # from the temple over the top of the ear to behind it
        c = Vector((xs, yc + 0.045 * math.cos(a) - 0.03, zc - 0.012 + 0.04 * math.sin(a) * 0.8))
        tang = Vector((0, -math.sin(a), math.cos(a) * 0.8)).normalized()
        nrm = Vector((1, 0, 0))
        bi = tang.cross(nrm).normalized()
        rings.append([tuple(c + (nrm * math.cos(2 * math.pi * k / n) + bi * math.sin(2 * math.pi * k / n)) * 0.0055) for k in range(n)])
        weights.append([{"head": 1.0}] * n)
    return loft("band", rings, weights, uv_rect)


# ------------------------------------------------------------------ atlas
class Atlas:
    """Buddy allocator over a power-of-two square (cells are powers of two)."""

    def __init__(self, size):
        self.free = {size: [(0, 0)]}
        self.size = size

    def alloc(self, s):
        k = s
        while k <= self.size and not self.free.get(k):
            k *= 2
        if k > self.size:
            return None
        x, y = self.free[k].pop()
        while k > s:
            k //= 2
            self.free.setdefault(k, []).extend([(x + k, y), (x, y + k), (x + k, y + k)])
        return (x, y, s)


def to_cell(o, rect, pad=3):
    x, y, s = rect
    uv = o.data.uv_layers.active or o.data.uv_layers[0]
    S = float(ATLAS)
    inner = (s - 2 * pad) / S
    for d in uv.data:
        u = min(1.0, max(0.0, d.uv[0]))
        v = min(1.0, max(0.0, d.uv[1]))
        d.uv = ((x + pad) / S + u * inner, 1.0 - ((y + pad) / S + (1.0 - v) * inner))


def _unused_face_tris_px(o, faces):
    uv = o.data.uv_layers.active or o.data.uv_layers[0]
    out = []
    for fi in faces:
        p = o.data.polygons[fi]
        pts = [(uv.data[li].uv[0] * ATLAS, (1.0 - uv.data[li].uv[1]) * ATLAS) for li in p.loop_indices]
        for k in range(1, len(pts) - 1):
            out.append([round(c, 1) for c in (*pts[0], *pts[k], *pts[k + 1])])
    return out


def delete_under(o, M, kind, tight):
    W = vweights(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    cov = [in_shell(W[v.index], v.co, M, kind, tight) for v in bm.verts]
    dead = [f for f in bm.faces if all(cov[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    return len(dead)


def decimate(o, ratio):
    if ratio >= 0.999:
        return
    m = o.modifiers.new("dec", "DECIMATE")
    m.decimate_type = "COLLAPSE"
    m.ratio = max(0.02, ratio)
    m.use_collapse_triangulate = True
    bpy.ops.object.select_all(action="DESELECT")
    with bpy.context.temp_override(object=o, active_object=o):
        bpy.ops.object.modifier_apply(modifier=m.name)


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    objs[0].name = name
    objs[0].data.name = name
    return objs[0]


def dup(o, name):
    c = o.copy()
    c.data = o.data.copy()
    c.name = name
    c.data.name = name
    bpy.context.scene.collection.objects.link(c)
    return c


def mat(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    return m


# ------------------------------------------------------------------ one citizen
def build(rc):
    t0 = time.time()
    reset()
    arm, parts, template, used = build_human(rc)
    M = metrics(arm)
    spec = {"id": rc["id"], "recipe": rc, "used": used, "cells": [], "posmaps": []}
    shell = rc.get("shell")
    extra = []
    if shell:
        sh = make_shell(template, arm, M, shell)
        extra.append([sh, "shell", "shell"])
        if shell["kind"] in ("coat", "raincoat"):
            extra.append([None, "skirt", "skirt"])
        if shell["kind"] in ("coat", "raincoat", "hoodie"):
            extra.append([None, "collar", "collar"])
        removed = 0
        for p in parts:
            if p[1] in ("body", "clothes"):
                removed += delete_under(p[0], M, shell["kind"], 0.02)
        log(rc["id"], "shell", shell["kind"], "faces hidden under it:", removed)
    if "resonance_band" in rc.get("accessories", []):
        extra.append([None, "band", "band"])
    # ---- atlas cells
    A = Atlas(ATLAS)
    order = {"body": 0, "shell": 1, "clothes": 2, "shoes": 4, "hair": 3, "acc": 5, "eyes": 7, "brows": 6, "skirt": 4, "collar": 6, "band": 8}
    size = {"body": 512, "shell": 512, "clothes": 512, "shoes": 128, "hair": 256, "acc": 128, "eyes": 64, "brows": 128,
            "skirt": 256, "collar": 128, "band": 32}
    allp = parts + extra
    nclothes = sum(1 for p in allp if p[1] == "clothes")
    if shell and nclothes >= 1:
        size["clothes"] = 256                 # mostly hidden under the shell
    if nclothes >= 2 and not shell:
        size["clothes"] = 256
    allp.sort(key=lambda p: (order[p[1]], p[2] or ""))
    rects = {}
    for p in sorted(allp, key=lambda p: -size[p[1]]):
        r = A.alloc(size[p[1]]) or A.alloc(size[p[1]] // 2) or A.alloc(size[p[1]] // 4)
        if r is None:
            raise RuntimeError("atlas full for " + rc["id"])
        rects[id(p)] = r
    # build the lofted parts now that their cells are known (they are made directly in atlas UV space)
    pad = 3
    for p in allp:
        if p[0] is not None:
            continue
        x, y, s = rects[id(p)]
        uvr = ((x + pad) / ATLAS, 1 - (y + s - pad) / ATLAS, (x + s - pad) / ATLAS, 1 - (y + pad) / ATLAS)
        if p[1] == "skirt":
            p[0] = make_skirt(template, M, shell, uvr)
        elif p[1] == "collar":
            p[0] = make_collar(template, M, shell, uvr)
        elif p[1] == "band":
            head = next(q[0] for q in parts if q[1] == "body")
            W = vweights(head)
            pts = [v.co.copy() for v, w in zip(head.data.vertices, W) if w.get("head", 0) > 0.8]
            p[0] = make_band(M, pts, uvr)
    allp = [p for p in allp if p[0] is not None]
    for p in allp:
        o, cat, name = p
        if o.parent != arm:
            o.parent = arm
        if not any(m.type == "ARMATURE" for m in o.modifiers):
            m = o.modifiers.new("Armature", "ARMATURE")
            m.object = arm
        if o.data.uv_layers.active is None or not len(o.data.uv_layers):
            o.data.uv_layers.new(name="UVMap")
        for u in o.data.uv_layers:
            u.name = "UVMap" if u == o.data.uv_layers.active else u.name
        r = rects[id(p)]
        if cat not in ("skirt", "collar", "band"):
            to_cell(o, r)
        src = o.data.materials[0] if len(o.data.materials) else None
        cell = {"part": name, "cat": cat, "rect": list(r), "albedo": image_of(src, "albedo"), "normal": image_of(src, "normal")}
        if cat in ("shell", "skirt", "collar"):
            cell.update({"fill": list(shell["colour"]), "kind": shell["kind"], "sheen": shell.get("sheen", 0.6)})
        if cat == "band":
            cell.update({"fill": [0.02, 0.03, 0.035], "emit_rgb": [0.1, 0.85, 1.0], "emit": 1.0})
        spec["cells"].append(cell)
        # position maps (bind-pose xyz per texel) for the parts compose_atlas.py paints by 3D rules:
        # shell trims / piping / reflective bands, sleepwalker temples on the body
        if cat in ("shell", "skirt", "collar") or cat == "body":
            spec["posmaps"].append({"cat": cat, "rect": list(r), "tris": pos_tris(o)})
        # one material per surface kind
        o.data.materials.clear()
        o.data.materials.append(mat("npc_cutout" if cat in ("hair", "brows") else "npc_opaque"))
    # ---- LOD0: clothes decimated if the citizen is too heavy
    total = sum(tris(p[0]) for p in allp)
    if total > LOD0_MAX:
        heavy = [p for p in allp if p[1] in ("clothes", "shoes", "acc", "hair") and tris(p[0]) > 600]
        ht = sum(tris(p[0]) for p in heavy)
        ratio = max(0.25, 1.0 - (total - LOD0_MAX) / max(1, ht))
        for p in heavy:
            decimate(p[0], ratio)
    lod0 = join([p[0] for p in allp], "LOD0")
    bpy.data.objects.remove(template, do_unlink=True)
    t_lod0 = tris(lod0)
    # ---- LOD1
    lod1 = dup(lod0, "LOD1")
    decimate(lod1, LOD1_TRIS / max(1, t_lod0))
    # ---- LOD2: arms down, static, vertex colours = sway weights
    lod2 = dup(lod0, "LOD2")
    sway = lod2_colors(lod2)
    pose_arms_down(arm)
    bpy.context.view_layer.update()
    with bpy.context.temp_override(object=lod2, active_object=lod2):
        bpy.ops.object.modifier_apply(modifier=next(m.name for m in lod2.modifiers if m.type == "ARMATURE"))
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix()
    # cutout cards collapse badly: drop brows; keep hair (silhouette)
    decimate(lod2, LOD2_TRIS / max(1, tris(lod2)))
    lod2.parent = None
    lod2.matrix_world = Matrix()
    lod2.vertex_groups.clear()
    lod2.data.materials.clear()
    lod2.data.materials.append(mat("npc_crowd"))
    del sway
    # ---- export
    os.makedirs(OUT, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in (arm, lod0, lod1, lod2):
        o.select_set(True)
    glb = os.path.join(OUT, rc["id"] + ".glb")
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True, export_animations=False, export_skins=True,
                              export_morph=False, export_apply=False, export_yup=True, export_materials="EXPORT",
                              export_image_format="NONE", export_vertex_color="ACTIVE", export_all_vertex_colors=False)
    spec["tris"] = [t_lod0, tris(lod1), tris(lod2)]
    spec["height"] = round(max(v.co.z for v in lod0.data.vertices), 3)
    spec["metrics"] = {k: [round(c, 4) for c in v] for k, v in M.items()}
    with open(os.path.join(OUT, rc["id"] + ".json"), "w") as f:
        json.dump(spec, f)
    log(rc["id"], "done: tris", spec["tris"], "height %.2f m" % spec["height"], "in %.1fs" % (time.time() - t0),
        "clothes", used["clothes"], "hair", used["hair"])
    return spec


def pos_tris(o):
    """[[px0, py0, px1, py1, px2, py2, x0, y0, z0, x1, ...]] atlas pixel coords + bind-pose positions."""
    uv = o.data.uv_layers.active or o.data.uv_layers[0]
    vs = o.data.vertices
    out = []
    for p in o.data.polygons:
        li = list(p.loop_indices)
        vi = list(p.vertices)
        for k in range(1, len(li) - 1):
            t = []
            for j in (0, k, k + 1):
                u, v = uv.data[li[j]].uv
                t += [round(u * ATLAS, 2), round((1.0 - v) * ATLAS, 2)]
            for j in (0, k, k + 1):
                t += [round(c, 4) for c in vs[vi[j]].co]
            out.append(t)
    return out


def lod2_colors(o):
    W = vweights(o)
    col = o.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    for i, w in enumerate(W):
        l = wsum(w, LEGS_L)
        r = wsum(w, LEGS_R)
        a = wsum(w, ("upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r"))
        col.data[i].color = (min(1, l), min(1, r), min(1, a), 1.0)
    o.data.color_attributes.active_color = col
    return col


def pose_arms_down(arm):
    for s in ("l", "r"):
        pb = arm.pose.bones["upperarm_" + s]
        b = pb.bone
        h = b.head_local.copy()
        d = (b.tail_local - b.head_local).normalized()
        sign = 1.0 if s == "l" else -1.0
        tgt = Vector((0.13 * sign, 0.03, -1.0)).normalized()
        q = d.rotation_difference(tgt)
        pb.matrix = Matrix.Translation(h) @ q.to_matrix().to_4x4() @ Matrix.Translation(-h) @ b.matrix_local


def main():
    recs = R.make_recipes(SEED, COUNT) + R.WAKERS
    if ONLY:
        recs = [r for r in recs if r["id"] in ONLY]
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for rc in recs:
        try:
            build(rc)
            ok += 1
        except Exception as e:  # keep going: one broken recipe must not stop the crowd
            import traceback
            traceback.print_exc()
            log(rc["id"], "FAILED", e)
    log("built %d / %d citizens into %s" % (ok, len(recs), OUT))


if __name__ == "__main__":
    main()
