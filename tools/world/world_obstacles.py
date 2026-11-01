"""Obstacle scan on the built Blender world: is every lane drivable?

For every drive lane of every road (bridge decks and approaches included), every 2 m:
  * body rays: three short vertical rays (lane centre and +-0.7 m) from 0.35 m to 1.9 m above
    the lane surface, and two horizontal rays along the lane at 0.5 m and 1.2 m. Any hit on an
    object that isn't road surface is an obstacle (pier, abutment, barrier end, rail, prop...).
  * cover ray: straight down from 6 m; if the first thing hit above the lane surface isn't road
    (terrain, a bridge part, a wall) the lane is buried.

Run:  blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,obstacles
Writes scenes/world/obstacles.json and logs a summary grouped by object.
"""
import json
import math
import os

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROAD_HINTS = ("Road", "Run", "Junction", "JDecal", "Decal", "Deck", "deck", "Asphalt", "Marking")


def _is_road(o):
    n = o.name
    if any(h in n for h in ROAD_HINTS):
        return True
    mats = [m.name for m in o.data.materials if m] if o.type == "MESH" else []
    return any(m.startswith("Road") and m != "RoadMetal" for m in mats) and not any(
        k in n for k in ("Pier", "Pylon", "Cable", "Rail", "Barrier", "Abut", "Wall", "Arch", "Hanger"))


def _lane_samples(world, step=2.0):
    out = []
    for r in world["roads"]:
        P = [Vector(p) for p in r["points"]]
        deck = r.get("deck", [])
        for lane in r["lanes"]:
            if lane.get("kind", "drive") != "drive":
                continue
            off = float(lane["offset"])
            carry = 0.0
            for i in range(len(P) - 1):
                a, b = P[i], P[i + 1]
                seg = b - a
                L = seg.length
                if L < 1e-3:
                    continue
                t = seg / L
                side = Vector((-t.y, t.x, 0.0)).normalized()
                u = carry
                while u < L:
                    c = a + t * u + side * off
                    out.append((c, t, r["id"], r["class"], bool(deck[i]) if i < len(deck) else False))
                    u += step
                carry = u - L
    return out


def scan(world, built, out_dir, log):
    deps = bpy.context.evaluated_depsgraph_get()
    S = _lane_samples(world)
    log(f"obstacles: {len(S)} lane samples")
    # candidate objects: anything whose bounds come near a lane
    from mathutils.kdtree import KDTree
    kd = KDTree(len(S))
    for i, s in enumerate(S):
        kd.insert(s[0], i)
    kd.balance()
    road_objs, cand = [], []
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o.hide_render or not o.visible_get():
            continue
        bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
        lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
        hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
        ctr, rad = (lo + hi) / 2, (hi - lo).length / 2 + 3.0
        if not kd.find_range(ctr, rad):
            continue
        (road_objs if _is_road(o) else cand).append(o)
    log(f"obstacles: {len(cand)} candidate objects, {len(road_objs)} road objects near lanes")

    def bvh(o):
        ev = o.evaluated_get(deps)
        me = ev.to_mesh()
        verts = [v.co.copy() for v in me.vertices]
        polys = [tuple(p.vertices) for p in me.polygons]
        ev.to_mesh_clear()
        return BVHTree.FromPolygons(verts, polys) if polys else None

    trees = []
    for o in cand:
        t = bvh(o)
        if t:
            trees.append((o, t, o.matrix_world.inverted(), o.matrix_world))
    rtrees = []
    for o in road_objs:
        t = bvh(o)
        if t:
            rtrees.append((o, t, o.matrix_world.inverted(), o.matrix_world))

    def cast(items, origin, direc, dist):
        best = None
        for o, t, inv, mw in items:
            lo = inv @ origin
            ld = (inv.to_3x3() @ direc).normalized()
            hit = t.ray_cast(lo, ld, dist * (inv.to_3x3() @ direc).length)
            if hit[0] is not None:
                w = mw @ hit[0]
                d = (w - origin).length
                if d <= dist and (best is None or d < best[0]):
                    best = (d, o.name, w)
        return best

    # spatial grid of objects so each sample only tests nearby ones
    def grid(items, cell=24.0):
        g = {}
        for it in items:
            bb = [it[3] @ Vector(c) for c in it[0].bound_box]
            x0, x1 = int(min(v.x for v in bb) // cell), int(max(v.x for v in bb) // cell)
            y0, y1 = int(min(v.y for v in bb) // cell), int(max(v.y for v in bb) // cell)
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    g.setdefault((gx, gy), []).append(it)
        return g, cell

    G, cell = grid(trees)
    RG, _ = grid(rtrees)
    hits, buried, examples = {}, {}, []
    up = Vector((0, 0, 1))
    for c, t, rid, cls, deck in S:
        k = (int(c.x // cell), int(c.y // cell))
        near = G.get(k, [])
        rnear = RG.get(k, [])
        # lane surface height: the road just under the centreline
        top = cast(rnear, c + up * 4.0, -up, 8.0)
        zs = top[2].z if top else c.z
        base = Vector((c.x, c.y, zs))
        side = Vector((-t.y, t.x, 0.0))
        found = None
        for dx in (-0.7, 0.0, 0.7):
            h = cast(near, base + side * dx + up * 0.35, up, 1.55)
            if h:
                found = h
                break
        if not found:
            for zz in (0.5, 1.2):
                h = cast(near, base + up * zz - t * 1.0, t, 2.0)
                if h:
                    found = h
                    break
        if found:
            key = found[1].split(".")[0]
            hits[key] = hits.get(key, 0) + 1
            if hits[key] <= 8:
                examples.append({"road": rid, "class": cls, "deck": deck, "hit": found[1], "pos": [round(c.x, 1), round(c.y, 1), round(zs, 2)]})
        # buried: something that isn't road above the lane surface
        cov = cast(near, base + up * 4.5, -up, 4.4)   # 4.5 m road clearance
        if cov:
            key = cov[1].split(".")[0]
            buried[key] = buried.get(key, 0) + 1
            if buried[key] <= 8:
                examples.append({"road": rid, "class": cls, "deck": deck, "covered_by": cov[1], "pos": [round(c.x, 1), round(c.y, 1), round(zs, 2)]})
    res = {"samples": len(S), "obstacle_hits": dict(sorted(hits.items(), key=lambda kv: -kv[1])),
           "covered": dict(sorted(buried.items(), key=lambda kv: -kv[1])), "examples": examples}
    with open(os.path.join(out_dir, "obstacles.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    log(f"OBSTACLES samples {len(S)} hits {sum(hits.values())} covered {sum(buried.values())}")
    log("  top hits: " + ", ".join(f"{k} {v}" for k, v in list(res["obstacle_hits"].items())[:15]))
    log("  top cover: " + ", ".join(f"{k} {v}" for k, v in list(res["covered"].items())[:15]))
    return res
