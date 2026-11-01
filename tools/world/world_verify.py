"""World checks (run after the build): terrain vs roads, junctions and
bridge decks; floating props; road grades; overlapping buildings; deck
clearance over roads; piers on roads; counts and scene metrics.
Writes <out>/verify.json and prints VERIFY {...}."""
import json
import math
import os
import random

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import terrain as TR


def surface_points(objs, n, rng, up=0.9):
    """Random points on the up-facing faces of objects (area weighted)."""
    faces = []
    for o in objs:
        me = o.data
        mw = o.matrix_world
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        for p in me.polygons:
            if p.normal.z > up and p.area > 0.01:
                faces.append((p.area, [mw @ Vector(co[v]) for v in p.vertices], o.name))
    if not faces:
        return []
    w = np.array([f[0] for f in faces])
    idx = rng.choices(range(len(faces)), weights=w.tolist(), k=n)
    out = []
    for i in idx:
        vs = faces[i][1]
        a = [rng.random() for _ in vs]
        s = sum(a)
        out.append((sum((v * (k / s) for v, k in zip(vs, a)), Vector()), faces[i][2]))
    return out


def verify(world, built, out, log, samples=60000, seed=5):
    rng = random.Random(seed)
    T = world["terrain"]
    hf = TR.Heightfield(world["size_m"], T["cell_m"])
    hf.H = built["H"]
    res = {}
    dg = bpy.context.evaluated_depsgraph_get()
    # 1. terrain never above a road, junction, lookout or deck surface
    roads = built["roads"] + built["junctions"]
    pts = surface_points(roads, samples, rng)
    P = np.array([(p.x, p.y, p.z) for p, _ in pts])
    tz = hf.sample_tri(P[:, 0], P[:, 1])
    d = tz - P[:, 2]
    bad = d > 0.002
    res["terrain_above_road"] = {"samples": len(P), "violations": int(bad.sum()), "worst_mm": round(float(max(0.0, d.max())) * 1000, 1),
                                 "where": sorted({pts[i][1] for i in np.nonzero(bad)[0][:50]})[:10],
                                 "examples": [[round(float(P[i, 0]), 2), round(float(P[i, 1]), 2), round(float(d[i]), 3), pts[i][1]] for i in np.nonzero(bad)[0][:12]]}
    # 2. ground under bridge girders: terrain must stay below the girder (deck - depth), except within 15 m of the abutments
    gviol, gsamp = 0, 0
    roads_by = {r["id"]: r for r in world["roads"]}
    for br in world["bridges"]:
        path = built["paths"].get(f"r{br['edge']}")
        if path is None:
            continue
        s0, s1 = br["s"]
        # the built structure's depth below the path where the builder recorded it (bridge_designs.py)
        bd = built.get("bridge_depth", {}).get(br["name"])
        for s in np.linspace(s0 + 15, s1 - 15, max(2, int((s1 - s0) / 3))):
            p, t = path.at(s)
            depth = float(np.interp(s, bd[0], bd[1])) if bd else br.get("depth", 2.4)
            for y in (-1.0, 0.0, 1.0):
                q = p.to_2d() + Vector((-t.y, t.x)) * y * br["half"] * 0.9
                g = float(hf.sample_tri(np.array([q.x]), np.array([q.y]))[0])
                gsamp += 1
                if g > p.z - depth - 0.1:
                    gviol += 1
    res["terrain_through_bridges"] = {"samples": gsamp, "violations": gviol}
    # 3. floating / buried street furniture and buildings
    bv = []
    bp = []
    for o in roads + built["walls"]:
        me = o.data
        mw = o.matrix_world
        base = len(bv)
        bv += [mw @ v.co for v in me.vertices]
        bp += [tuple(i + base for i in p.vertices) for p in me.polygons]
    road_bvh = BVHTree.FromPolygons(bv, bp) if bp else None

    def ground(x, y, z):
        g = float(hf.sample_tri(np.array([x]), np.array([y]))[0])
        if road_bvh is not None:
            h = road_bvh.ray_cast(Vector((x, y, z + 0.5)), Vector((0, 0, -1)), 60)
            if h[0] is not None and h[0].z > g:
                g = h[0].z
        return g
    floating, buried = [], []
    region = built["region"]
    checked = 0
    for i in world["instances"]:
        if i.get("kind") not in ("lamp", "pole", "signal", "mast", "container", "prop") or i.get("slot") == "rooftop":
            continue
        x, y, z = i["pos"]
        if region and not (region[0] <= x <= region[2] and region[1] <= y <= region[3]):
            continue
        if i.get("kind") == "container" and z > 3.5 and i["pos"][2] - ground(x, y, z) > 2.0:
            continue                       # stacked on another container
        g = ground(x, y, z)
        checked += 1
        if z - g > 0.06:
            floating.append((i["asset"], round(z - g, 2), [round(x, 1), round(y, 1)]))
        elif g - z > 0.35:
            buried.append((i["asset"], round(g - z, 2), [round(x, 1), round(y, 1)]))
    by = {}
    for a, dz, _ in floating:
        c, m = by.get(a, (0, 0.0))
        by[a] = (c + 1, max(m, dz))
    res["props"] = {"checked": checked, "floating": len(floating), "buried": len(buried), "floating_by_asset": by,
                    "examples": (sorted(floating, key=lambda f: -f[1]) + buried)[:8]}
    # buildings: base at the highest ground under the footprint, footing below the lowest
    nb = nf = 0
    for i in world["instances"]:
        if i.get("kind") not in ("building", "tower", "warehouse"):
            continue
        x, y, z = i["pos"]
        if region and not (region[0] <= x <= region[2] and region[1] <= y <= region[3]):
            continue
        nb += 1
        g = float(hf.sample_tri(np.array([x]), np.array([y]))[0])
        if z - g > 0.05 and z - i.get("footing", 0) > g - 0.05:
            nf += 1
    res["buildings_floating"] = {"checked": nb, "floating": nf}
    # 4. grades per class (from the centrelines)
    lim = {"street": 0.12, "avenue": 0.12, "highway_urban": 0.06, "highway": 0.06, "mountain": 0.12}
    worst = {}
    over = []
    for r in world["roads"]:
        Q = np.array(r["points"])
        ds = np.hypot(np.diff(Q[:, 0]), np.diff(Q[:, 1]))
        g = np.abs(np.diff(Q[:, 2])) / np.maximum(ds, 1e-6)
        # 10 m moving window (what a car feels), not single samples
        cs = np.concatenate([[0], np.cumsum(ds)])
        zz = Q[:, 2]
        win = []
        for k in range(len(Q)):
            j = np.searchsorted(cs, cs[k] + 10.0)
            if j < len(Q):
                win.append(abs(zz[j] - zz[k]) / max(cs[j] - cs[k], 1e-6))
        gm = max(win) if win else (float(g.max()) if len(g) else 0.0)
        c = r["class"]
        on_bridge = any(r["deck"])
        key = c + ("+deck" if on_bridge else "")
        worst[key] = max(worst.get(key, 0.0), gm)
        L = 0.06 if on_bridge and c.startswith("highway") else lim[c]
        if gm > L + 1e-3:
            over.append((r["id"], c, round(gm, 4)))
    res["grades"] = {"max_by_class": {k: round(v, 4) for k, v in sorted(worst.items())}, "limits": lim, "over_limit": over[:10],
                     "n_over": len(over)}
    # 5. overlapping footprints (buildings, towers, warehouses, cranes) and footprints on roads
    import placement as PL
    tw = {t["mesh"]: t for t in world["towers"]}
    rects = []
    for i in world["instances"]:
        a = i["asset"]
        if a in PL.KIT:
            ext = PL.KIT[a]["ext"]
        elif a in tw:
            W, D = tw[a]["footprint"]
            ext = (-W / 2, W / 2, -D / 2, D / 2)
        elif a.startswith("warehouse_"):
            Lw, Ww = [float(v) for v in a.split("_")[1].split("x")[:2]]
            ext = (-Lw / 2, Lw / 2, -Ww / 2, Ww / 2)
        else:
            continue
        rects.append((PL.rect(Vector(i["pos"][:2]), i["rot"], ext), a))
    hsh = PL.Hash(48.0)
    n_ov = 0
    ex = []
    for k, (rc, a) in enumerate(rects):
        xs = [c.x for c in rc]
        ys = [c.y for c in rc]
        shrunk = [c.lerp(sum(rc, Vector((0, 0))) / 4, 0.02) for c in rc]       # 2 % tolerance for touching walls
        for (q, b) in hsh.query(min(xs), min(ys), max(xs), max(ys)):
            if PL.overlap(shrunk, q):
                n_ov += 1
                if len(ex) < 5:
                    ex.append((a, b, [round(xs[0], 1), round(ys[0], 1)]))
        hsh.add((shrunk, a), min(xs), min(ys), max(xs), max(ys))
    # footprints vs road keep-out (centre samples)
    on_road = 0
    rh = PL.Hash(16.0)
    cls = world["road_classes"]
    for r in world["roads"]:
        c = cls[r["class"]]
        w = c["half"] + (3.0 if c.get("side", "curb") == "curb" else 0.5)
        Q = r["points"]
        for a_, b_, dk in zip(Q, Q[1:], r["deck"]):
            L = math.hypot(b_[0] - a_[0], b_[1] - a_[1])
            for f in np.linspace(0, 1, max(2, int(L / 2) + 1)):
                x = a_[0] + (b_[0] - a_[0]) * f
                y = a_[1] + (b_[1] - a_[1]) * f
                rh.add((x, y, w, dk), x, y, x, y)
    for rc, a in rects:
        cn = sum(rc, Vector((0, 0))) / 4
        ux = (rc[1] - rc[0])
        uy = (rc[3] - rc[0])
        hw, hh = ux.length / 2, uy.length / 2
        ux.normalize()
        uy.normalize()
        xs = [c.x for c in rc]
        ys = [c.y for c in rc]
        for (x, y, w, dk) in rh.query(min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20):
            dx, dy = x - cn.x, y - cn.y
            lx = abs(dx * ux.x + dy * ux.y)
            ly = abs(dx * uy.x + dy * uy.y)
            if math.hypot(max(lx - hw, 0), max(ly - hh, 0)) < w - 0.05:
                on_road += 1
                break
    res["footprints"] = {"checked": len(rects), "overlaps": n_ov, "examples": ex, "on_road": on_road}
    # 6. decks over roads: clearance; piers standing on roads
    clear = []
    for r in world["roads"]:
        if not any(r["deck"]):
            continue
        Q = np.array(r["points"])
        D = np.array(r["deck"]) > 0
        for r2 in world["roads"]:
            if r2 is r or r2["start"]["node"] in (r["start"]["node"], r["end"]["node"]) or r2["end"]["node"] in (r["start"]["node"], r["end"]["node"]):
                continue
            Q2 = np.array(r2["points"])
            if Q2[:, 0].max() < Q[:, 0].min() - 20 or Q2[:, 0].min() > Q[:, 0].max() + 20 or Q2[:, 1].max() < Q[:, 1].min() - 20 or Q2[:, 1].min() > Q[:, 1].max() + 20:
                continue
            for k in np.nonzero(D)[0]:
                dd = np.hypot(Q2[:, 0] - Q[k, 0], Q2[:, 1] - Q[k, 1])
                j = int(np.argmin(dd))
                if dd[j] < cls[r2["class"]]["half"]:
                    clear.append(float(Q[k, 2] - Q2[j, 2]))
    piers_on_road = 0
    for p in built["piers"]:
        for (x, y, w, dk) in rh.query(p["pos"][0] - 20, p["pos"][1] - 20, p["pos"][0] + 20, p["pos"][1] + 20):
            # a pier may stand under its own deck, never on a road at grade
            if not dk and math.hypot(x - p["pos"][0], y - p["pos"][1]) < w - 3.0 + 1.5:
                piers_on_road += 1
                break
    res["decks"] = {"min_clearance_over_roads_m": round(min(clear), 2) if clear else None, "crossings_sampled": len(clear),
                    "piers": len(built["piers"]), "piers_on_roads": piers_on_road}
    # 7. scene metrics
    tri = 0
    inst_tri = 0
    meshes = {}
    for o in bpy.data.objects:
        if o.type != "MESH" or o.users_collection[0].name == "TownKit":
            continue
        me = o.data
        t = meshes.get(me.name)
        if t is None:
            t = sum(len(p.vertices) - 2 for p in me.polygons)
            meshes[me.name] = t
        inst_tri += t
    res["scene"] = {"objects": len(bpy.data.objects), "unique_meshes": len(meshes), "unique_tris": int(sum(meshes.values())),
                    "rendered_tris": int(inst_tri), "lights": built["lights"], "instances": built["instances"]}
    res["metrics"] = world["metrics"]
    with open(os.path.join(out, "verify.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    log("VERIFY " + json.dumps({k: v for k, v in res.items() if k != "metrics"}))
    return res
