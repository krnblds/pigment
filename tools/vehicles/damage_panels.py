"""Detachable damage panels for the LOD0 export (headless Blender, called from export.py).

The vehicle kit joins every part into one `Body` mesh. For damage in the game, LOD0 keeps the
panels that can bend, swing, break or fall off as their own nodes, each with its own pivot:

    Hood, Trunk (trunk lid / hatch / tailgate, plus a wing on it), Door_FL/FR/RL/RR (or the
    sliding Door_SL/SR), Bumper_F / Bumper_R, Mirror_L / Mirror_R, Glass_* (windshield, rear
    window, door and quarter glass), Lens_Head_L/R, Lens_Tail_L/R (or _C for a full-width lens),
    Lamp_Head_L/R, Lamp_Tail_L/R(/C) (the lamps' emitters: dark once the lens is broken)

Everything else stays in `Body`. A panel takes its small attached parts with it (handles, locks,
seals, rub strips, door cards and armrests for doors; plates and intakes for bumpers; louvres for
the hood; the wing for the trunk). Every node keeps identity rotation; its origin is the pivot:

    doors   hinge on the front edge, outer skin, vertical axis
    hood    hinge at the rear edge (by the windscreen), axis X
    trunk   lid: hinge at the front edge; hatch / tailgate: hinge at the top; axis X
    mirror  the stalk's root
    others  the centre of their bounding box

How a face finds its part: the joined Body's connected pieces are matched against the
`<id>_parts.json` records (piece centre + triangle count), which the kit wrote when it joined them.

`split(body, src_dir, vid)` separates the panels (custom normals, UVs, attributes and the material
slot are kept) and returns (objects, damage_info). `damage_info` goes into `<id>.json` as "damage":
the node list with kind, parent, pivot, hinge axis and opening sign, limits, mass, bounds and lamps.
Coordinates in the json are glTF / Godot car space (+Y up, the car faces +Z, +X is its left).
"""
import json
import math
import os
import re

import bmesh
import bpy
from mathutils import Matrix, Vector

ATTR = "dmg_panel"


def gl(v):
    """Blender (Z up, car faces -Y) -> glTF (Y up, faces +Z)."""
    return (v[0], v[2], -v[1])


def bl(v):
    return Vector((v[0], -v[2], v[1]))


def _side(x):
    return "C" if abs(x) < 0.15 else ("L" if x > 0 else "R")


def plan(records):
    """Panel plan from the part records: [{node, kind, parts: set, parent, lamps}]."""
    by = {r["name"]: r for r in records}
    names = list(by)
    cen = {n: by[n]["pieces"][0]["center"] for n in names}
    out = []
    used = set()

    def add(node, kind, parts, parent=None, **kw):
        parts = [p for p in parts if p in by and p not in used]
        if not parts:
            return None
        used.update(parts)
        d = {"node": node, "kind": kind, "parts": parts, "parent": parent}
        d.update(kw)
        out.append(d)
        return d

    # doors (+ handles, locks, seals, rub strips, cards, armrests) and their glass
    doors = sorted(n for n in names if re.fullmatch(r"door_(FL|FR|RL|RR|SL|SR)", n))
    door_nodes = {}
    for dn in doors:
        code = dn[5:]
        pos, side = code[0], code[1]
        extra = [f"handle_pocket_{code}", f"handle_{code}", f"door_card_{code}", f"armrest_{code}",
                 f"rub_strip_{pos}_{side}", f"window_seal_{pos}_{side}"]
        front = f"door_F{side}" if f"door_F{side}" in by else f"door_S{side}"
        if dn == front:
            extra.append(f"door_lock_{side}")
        door_nodes[code] = add(f"Door_{code}", "door", [dn] + extra, hinge="front")
    for code, d in door_nodes.items():
        if d:
            add(f"Glass_Door_{code}", "glass", [f"glass_door_glass_{code[0]}_{code[1]}"], parent=d["node"])
    # hood (+ louvres)
    hood = add("Hood", "hood", ["hood"] + [n for n in names if n.startswith("hood_louvre")], hinge="rear")
    # trunk lid / hatch / tailgate (+ a wing); its glass if the lid carries it
    tk = next((n for n in ("trunk_lid", "hatch", "tailgate") if n in by), None)
    trunk = None
    if tk:
        trunk = add("Trunk", "trunk", [tk] + [n for n in names if n.startswith("wing_")], hinge="front" if tk == "trunk_lid" else "top")
    # bumpers (+ whatever sits inside their bounds: plates, intakes, caps, pads)
    bumpers = []
    for nm, node in (("bumper_F", "Bumper_F"), ("bumper_R", "Bumper_R"), ("bumper_bar", "Bumper_F")):
        if nm in by and nm not in used and not any(b["node"] == node for b in bumpers):
            b = add(node, "bumper", [nm] + [n for n in names if n.startswith(("bumper_cap_", "push_bar"))])
            if b:
                bumpers.append(b)
    for b in bumpers:
        lo, hi = _bounds([by[p] for p in b["parts"]])
        inside = []
        for n in names:
            if n in used or by[n]["group"] not in ("black_trim", "chrome", "plate", "rubber", "black_metal", "grille"):
                continue
            plo, phi = _bounds([by[n]])
            if all(plo[i] >= lo[i] - 0.03 and phi[i] <= hi[i] + 0.03 for i in range(3)):
                inside.append(n)
        b["parts"] += inside
        used.update(inside)
    # mirrors (mounted on the front door when it is there)
    for side in "LR":
        parts = [f"mirror_stalk_{side}", f"mirror_housing_{side}", f"mirror_glass_{side}"]
        par = None
        fd = door_nodes.get("F" + side) or door_nodes.get("S" + side)
        if fd and f"mirror_stalk_{side}" in by:
            dlo, dhi = _bounds([by[p] for p in fd["parts"]])
            z = cen[f"mirror_stalk_{side}"][2]
            if dlo[2] - 0.05 <= z <= dhi[2] + 0.05:
                par = fd["node"]
        add(f"Mirror_{side}", "mirror", parts, parent=par)
    # the other glass panes (the rear window rides on a hatch / tailgate)
    for n in names:
        if n in used or by[n]["group"] != "glass" or not n.startswith("glass_"):
            continue
        par = None
        if trunk and n == "glass_rear_window":
            tlo, thi = _bounds([by[p] for p in trunk["parts"]])
            c = cen[n]
            if all(tlo[i] - 0.06 <= c[i] <= thi[i] + 0.06 for i in range(3)):
                par = "Trunk"
        node = "Glass_" + "".join(w.capitalize() for w in n[6:].split("_"))
        add(node, "glass", [n], parent=par)
    # lamp units: lenses (break) and emitters (go dark)
    lamp_names = ("headlight_", "indicator_F", "indicator_lens", "tail_brake", "tail_indicator", "tail_reverse",
                  "tail_core", "tail_status", "tail_center_rib", "taillight_lens")
    units = {}
    for n in names:
        if n in used or not n.startswith(lamp_names):
            continue
        g = by[n]["group"]
        if not (g.startswith("lens_") or g.startswith("emitter_")):
            continue
        c = cen[n]
        front = c[2] > 0
        unit = ("Head_" if front else "Tail_") + _side(c[0])
        units.setdefault(unit, {"lens": [], "lamp": []})["lens" if g.startswith("lens_") else "lamp"].append(n)
    for unit, d in sorted(units.items()):
        front = unit.startswith("Head")
        s = unit[-1]
        lamps = [("Headlight_" if front else "Taillight_") + x for x in ("LR" if s == "C" else s)]
        # lamps set in a hatch / tailgate ride on it; the others stay on the body (a bumper can fall off
        # without taking the headlamps along)
        parent = _container(cen[d["lens"][0] if d["lens"] else d["lamp"][0]], out, by, ("Trunk",))
        if d["lens"]:
            add("Lens_" + unit, "lens", d["lens"], parent=parent, lamps=lamps)
        if d["lamp"]:
            add("Lamp_" + unit, "lamp", d["lamp"], parent=parent, lamps=lamps)
    return out


def _container(c, panels, by, nodes):
    """The panel among `nodes` whose bounds hold point c (lamps set in a bumper or a tailgate)."""
    for p in panels:
        if p["node"] in nodes:
            lo, hi = _bounds([by[q] for q in p["parts"]])
            if all(lo[i] - 0.02 <= c[i] <= hi[i] + 0.02 for i in range(3)):
                return p["node"]
    return None


def _bounds(recs):
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for r in recs:
        for pc in r["pieces"]:
            for i in range(3):
                lo[i] = min(lo[i], pc["center"][i] - pc["size"][i] * 0.5)
                hi[i] = max(hi[i], pc["center"][i] + pc["size"][i] * 0.5)
    return lo, hi


def _components(me):
    """Connected pieces of a mesh: [(face indices, centre in glTF coords, triangles)]."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = bytearray(len(bm.faces))
    out = []
    for f in bm.faces:
        if seen[f.index]:
            continue
        stack = [f]
        seen[f.index] = 1
        comp = []
        while stack:
            g = stack.pop()
            comp.append(g)
            for v in g.verts:
                for h in v.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = 1
                        stack.append(h)
        vs = {v for g in comp for v in g.verts}
        lo = Vector((min(v.co.x for v in vs), min(v.co.y for v in vs), min(v.co.z for v in vs)))
        hi = Vector((max(v.co.x for v in vs), max(v.co.y for v in vs), max(v.co.z for v in vs)))
        out.append(([g.index for g in comp], gl((lo + hi) / 2), sum(len(g.verts) - 2 for g in comp)))
    bm.free()
    return out


def _match(comps, records):
    """Part name per component (centre within 3 mm and the same triangle count; else nearest centre
    with the same count within 2 cm)."""
    pieces = []
    for r in records:
        for pc in r["pieces"]:
            pieces.append((r["name"], pc["center"], pc["triangles"]))
    names = []
    miss = 0
    for _faces, c, t in comps:
        best, bd = None, 1e9
        for nm, pc, pt in pieces:
            if pt != t:
                continue
            d = math.dist(c, pc)
            if d < bd:
                best, bd = nm, d
        if bd > 0.02:
            best = None
            miss += 1
        names.append(best)
    return names, miss


def split(body, src_dir, vid):
    """Separate the panels out of `body` (triangulated, LOD0). Returns ([objects], damage info)."""
    records = json.load(open(os.path.join(src_dir, f"{vid}_parts.json")))["body"]
    panels = plan(records)
    comps = _components(body.data)
    names, miss = _match(comps, records)
    owner = {}
    for i, p in enumerate(panels):
        for n in p["parts"]:
            owner[n] = i + 1
    me = body.data
    a = me.attributes.get(ATTR) or me.attributes.new(ATTR, "INT", "FACE")
    vals = [0] * len(me.polygons)
    for (faces, _c, _t), nm in zip(comps, names):
        k = owner.get(nm, 0)
        for fi in faces:
            vals[fi] = k
    a.data.foreach_set("value", vals)
    print(f"[damage] {vid}: {len(comps)} pieces, {miss} unmatched, {len(panels)} panels")
    objs = []
    info = []
    for i, p in enumerate(panels):
        ob = _separate(body, i + 1)
        if ob is None:
            print(f"[damage]   {p['node']}: no faces")
            continue
        ob.name = p["node"]
        ob.data.name = p["node"]
        lo, hi = _ob_bounds(ob)
        pivot, axis, sign, limits = _pivot(p, lo, hi)
        piv_bl = bl(pivot)
        ob.data.transform(Matrix.Translation(-piv_bl))
        ob.location = piv_bl
        if ATTR in ob.data.attributes:
            ob.data.attributes.remove(ob.data.attributes[ATTR])
        objs.append(ob)
        tris = sum(len(f.vertices) - 2 for f in ob.data.polygons)
        size = [hi[j] - lo[j] for j in range(3)]
        e = {"node": p["node"], "kind": p["kind"], "parent": p["parent"],
             "pivot": [round(x, 4) for x in pivot], "aabb": [[round(x, 4) for x in lo], [round(x, 4) for x in hi]],
             "mass_kg": _mass(p["kind"], size), "triangles": tris, "parts": p["parts"]}
        if axis:
            e["hinge_axis"] = axis
            e["open_sign"] = sign
            e["limits_deg"] = limits
        if p.get("lamps"):
            e["lamps"] = p["lamps"]
        info.append(e)
    if ATTR in body.data.attributes:
        body.data.attributes.remove(body.data.attributes[ATTR])
    return objs, {
        "version": 1,
        "coords": "car space: +Y up, the car faces +Z, +X is its left; pivot = node origin",
        "panels": info,
        "notes": ["LOD0 only: LOD1 / LOD2 keep the merged Body.",
                  "kind: door | hood | trunk | bumper | mirror | glass | lens | lamp. A node with a parent moves with it "
                  "(and falls off with it).",
                  "hinge_axis + open_sign: rotating by open_sign * angle (radians, right-handed about the axis) opens "
                  "the panel; limits_deg = [0, max opening].",
                  "lens / lamp: lamps lists the Headlight_* / Taillight_* empties the unit lights; a broken lens darkens "
                  "its lamp node (emission off) and those lights."],
    }


def _separate(body, k):
    me = body.data
    a = me.attributes[ATTR]
    sel = [False] * len(me.polygons)
    vals = [0] * len(me.polygons)
    a.data.foreach_get("value", vals)
    any_sel = False
    for i, v in enumerate(vals):
        if v == k:
            sel[i] = True
            any_sel = True
    if not any_sel:
        return None
    before = set(bpy.data.objects)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    me.polygons.foreach_set("select", sel)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    new = [o for o in bpy.data.objects if o not in before]
    return new[0] if new else None


def _ob_bounds(ob):
    lo = [1e9] * 3
    hi = [-1e9] * 3
    mw = ob.matrix_world
    for v in ob.data.vertices:
        g = gl(mw @ v.co)
        for i in range(3):
            lo[i] = min(lo[i], g[i])
            hi[i] = max(hi[i], g[i])
    return lo, hi


def _pivot(p, lo, hi):
    """(pivot, hinge axis, opening sign, limits) in glTF car space."""
    c = [(lo[i] + hi[i]) * 0.5 for i in range(3)]
    k = p["kind"]
    if k == "door":
        left = c[0] > 0
        x = hi[0] if left else lo[0]
        # rotating +angle about +Y moves the rear edge towards -X: outward for a right door
        return [x, c[1], hi[2]], [0, 1, 0], (-1 if left else 1), [0, 75]
    if k == "hood":
        # about +X at the rear edge: +angle drops the front, so it opens with -angle
        return [c[0], hi[1], lo[2]], [1, 0, 0], -1, [0, 55]
    if k == "trunk":
        if p.get("hinge") == "top":
            return [c[0], hi[1], c[2]], [1, 0, 0], 1, [0, 80]
        return [c[0], hi[1], hi[2]], [1, 0, 0], 1, [0, 70]
    if k == "mirror":
        x = lo[0] if c[0] > 0 else hi[0]
        return [x, c[1], c[2]], None, 0, None
    return c, None, 0, None


def _mass(kind, size):
    area = max(size[0] * size[1], size[1] * size[2], size[0] * size[2])
    per = {"door": 18.0, "hood": 11.0, "trunk": 11.0, "bumper": 6.0, "mirror": 0.0, "glass": 10.0, "lens": 3.0, "lamp": 2.0}
    if kind == "mirror":
        return 1.2
    return round(max(0.3, area * per.get(kind, 5.0)), 2)
