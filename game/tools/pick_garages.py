"""Pick road-side lots for the drive-in garages and write game/data/garages.json.

    python game/tools/pick_garages.py

Reads the Godot export of the open world (game/assets/world/world_layout.json: Godot coordinates, every
mesh with its local AABB) and world.json (road widths, districts, heightfield).  Each garage wants a lot
beside a straight, flat street or avenue in its district, away from junctions: the building (W along the
road x D deep) stands behind the sidewalk with its door facing the road, and a driveway crosses the
sidewalk.  The city is built out wall to wall, so a lot may take the place of ordinary buildings, their
footings, shop signs, alley lights and street clutter (they are listed in "remove" and skipped by the
town loader); street lamps, poles, signals, towers, warehouses, roads and bridges can't be moved, so a lot
touching one of those (or another road) is rejected, as is one where the terrain rises into the floor.
The best lot (near the district anchor, few buildings replaced) wins.
"""
import argparse
import json
import math
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(HERE)

# anchors in Godot x / z (blender x, -y)
GARAGES = [
    {"id": "yoimachi_mods", "name": "YOIMACHI MOD SHOP", "district": "yoimachi", "style": "mod",
     "anchor": [-720.0, 120.0], "radius": 280.0, "sign": "GARAGE", "sub": "MODS  //  TUNING  //  NEON",
     "accent": [1.0, 0.16, 0.62], "accent2": [0.2, 0.9, 1.0]},
    {"id": "hoshikawa_downtown", "name": "HOSHIKAWA MOTORS", "district": "downtown", "style": "dealer",
     "anchor": [-120.0, 150.0], "radius": 420.0, "sign": "GARAGE", "sub": "HOSHIKAWA MOTORS  //  DEALERSHIP",
     "accent": [0.25, 0.85, 1.0], "accent2": [0.85, 0.9, 1.0]},
    {"id": "port_chop", "name": "MINATO CHOP SHOP", "district": "port", "style": "chop",
     "anchor": [1380.0, 1000.0], "radius": 560.0, "sign": "GARAGE", "sub": "UNDERGROUND  //  NO QUESTIONS",
     "accent": [1.0, 0.5, 0.08], "accent2": [1.0, 0.15, 0.3]},
]

W = 14.0          # along the road
D = 16.0          # away from the road
SETBACK = 1.0     # gap between the sidewalk edge and the building front
DRIVE_W = 7.0     # driveway width
FIXED_CATS = {"lamp", "pole", "road", "terrain", "bridge", "bridge_detail", "bridge_wash", "bridge_far",
              "bridge_near", "crane", "wall", "rail", "water"}
SKIP_CATS = {"decal", "wire", "road", "terrain", "water"}   # roads: centre-line test; terrain: heightfield; decals: flat
FIXED_NAMES = ("tower", "landmark", "warehouse", "PROP_traffic_light_mast", "PROP_ped_signal", "PROP_light_mast",
               "street_lamp", "power_pole", "traffic_light", "bus", "Bridge", "Girder", "Lookout", "SeaWall")
GRID = 32.0


def heightfield(world_dir, t):
    n = t["n"]
    with open(os.path.join(world_dir, t["heightfield"]), "rb") as f:
        vals = struct.unpack("<%df" % (n * n), f.read())
    ox, oy = t["origin"]
    cell = t["cell_m"]

    def h(gx, gz):                     # Godot x, z -> blender x, y
        x, y = gx, -gz
        fx = (x - ox) / cell
        fy = (y - oy) / cell
        ix = max(0, min(n - 2, int(fx)))
        iy = max(0, min(n - 2, int(fy)))
        ax, ay = fx - ix, fy - iy
        a = vals[iy * n + ix] * (1 - ax) + vals[iy * n + ix + 1] * ax
        b = vals[(iy + 1) * n + ix] * (1 - ax) + vals[(iy + 1) * n + ix + 1] * ax
        return a * (1 - ay) + b * ay
    return h


def footprint(inst, info):
    """2D polygon (x, z) of the instance's AABB."""
    a = inst["xf"]
    lo, hi = info["aabb"]
    pts = []
    for x in (lo[0], hi[0]):
        for z in (lo[2], hi[2]):
            y = lo[1]
            px = a[0] * x + a[3] * y + a[6] * z + a[9]
            pz = a[2] * x + a[5] * y + a[8] * z + a[11]
            pts.append((px, pz))
    # order the 4 corners around their centre
    cx = sum(p[0] for p in pts) / 4
    cz = sum(p[1] for p in pts) / 4
    pts.sort(key=lambda p: math.atan2(p[1] - cz, p[0] - cx))
    ylo = a[1] * lo[0] + a[4] * lo[1] + a[7] * lo[2] + a[10]
    yhi = a[1] * hi[0] + a[4] * hi[1] + a[7] * hi[2] + a[10]
    return pts, min(ylo, yhi), max(ylo, yhi)


def rect_poly(c, t, n, hw, hd):
    return [(c[0] + t[0] * su * hw + n[0] * sv * hd, c[1] + t[1] * su * hw + n[1] * sv * hd)
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def overlap(p, q):
    """Separating axis test of two convex polygons."""
    for poly in (p, q):
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            ax, az = -(b[1] - a[1]), b[0] - a[0]
            if abs(ax) + abs(az) < 1e-9:
                continue
            pa = [ax * v[0] + az * v[1] for v in p]
            qa = [ax * v[0] + az * v[1] for v in q]
            if max(pa) < min(qa) or max(qa) < min(pa):
                return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world-dir", default=os.path.join(GAME, "assets", "world"))
    ap.add_argument("--out", default=os.path.join(GAME, "data", "garages.json"))
    a = ap.parse_args()
    lay = json.load(open(os.path.join(a.world_dir, "world_layout.json")))
    w = json.load(open(os.path.join(a.world_dir, "world.json")))
    hf = heightfield(a.world_dir, w["terrain"])
    meshes = lay["meshes"]
    grid = {}
    items = []
    for inst in lay["instances"]:
        info = meshes.get(inst["mesh"])
        if not info:
            continue
        cat = info.get("cat", "other")
        if cat in SKIP_CATS:
            continue
        poly, ylo, yhi = footprint(inst, info)
        xs = [p[0] for p in poly]
        zs = [p[1] for p in poly]
        if max(xs) - min(xs) > 400 or max(zs) - min(zs) > 400:
            continue                   # world-space merged meshes (terrain chunks, bridges) handled by roads / height
        fixed = cat in FIXED_CATS or inst["mesh"].startswith(FIXED_NAMES)
        it = {"mesh": inst["mesh"], "poly": poly, "fixed": fixed, "cat": cat, "ylo": ylo, "yhi": yhi,
              "o": (inst["xf"][9], inst["xf"][10], inst["xf"][11])}
        items.append(it)
        for gx in range(int(math.floor(min(xs) / GRID)), int(math.floor(max(xs) / GRID)) + 1):
            for gz in range(int(math.floor(min(zs) / GRID)), int(math.floor(max(zs) / GRID)) + 1):
                grid.setdefault((gx, gz), []).append(len(items) - 1)

    def near(poly):
        xs = [p[0] for p in poly]
        zs = [p[1] for p in poly]
        out = set()
        for gx in range(int(math.floor(min(xs) / GRID)), int(math.floor(max(xs) / GRID)) + 1):
            for gz in range(int(math.floor(min(zs) / GRID)), int(math.floor(max(zs) / GRID)) + 1):
                out.update(grid.get((gx, gz), []))
        return out

    roads = []
    for r in w["roads"]:
        pts = [(p[0], -p[1], p[2]) for p in r["points"]]          # Godot x, z, height
        roads.append((r, pts))
    lights = lay["lights"]
    out = []
    taken = []
    for g in GARAGES:
        anchor = g["anchor"]
        best = None
        rej = {}
        for r, pts in roads:
            if r["class"] not in ("street", "avenue") or r.get("side") != "curb" or any(r.get("deck", [])):
                continue
            half_total = float(r["width"]) * 0.5
            carry = float(r["carriageway"]) * 0.5
            cum = [0.0]
            for i in range(1, len(pts)):
                cum.append(cum[-1] + math.dist(pts[i][:2], pts[i - 1][:2]))
            L = cum[-1]
            last_s = -99.0
            for i in range(1, len(pts) - 1):
                if cum[i] - last_s < 3.0 or cum[i] < 30.0 or L - cum[i] < 30.0:
                    continue
                last_s = cum[i]
                p = pts[i]
                if math.dist(p[:2], anchor) > g["radius"]:
                    continue
                j0 = max(0, i - 8)
                j1 = min(len(pts) - 1, i + 8)
                while j0 > 0 and cum[i] - cum[j0] < 12.0:
                    j0 -= 1
                while j1 < len(pts) - 1 and cum[j1] - cum[i] < 12.0:
                    j1 += 1
                if abs(pts[j1][2] - pts[j0][2]) > 0.8:
                    rej["grade"] = rej.get("grade", 0) + 1
                    continue
                t0 = (pts[i][0] - pts[j0][0], pts[i][1] - pts[j0][1])
                t1 = (pts[j1][0] - pts[i][0], pts[j1][1] - pts[i][1])
                d = abs((math.atan2(t1[1], t1[0]) - math.atan2(t0[1], t0[0]) + math.pi) % (2 * math.pi) - math.pi)
                if d > 0.1:
                    rej["bend"] = rej.get("bend", 0) + 1
                    continue
                tx, tz = pts[j1][0] - pts[j0][0], pts[j1][1] - pts[j0][1]
                tl = math.hypot(tx, tz)
                t = (tx / tl, tz / tl)
                for side in (1.0, -1.0):
                    n = (-t[1] * side, t[0] * side)
                    front = half_total + SETBACK
                    c = (p[0] + n[0] * (front + D * 0.5), p[1] + n[1] * (front + D * 0.5))
                    if any(math.dist(c, q) < 80.0 for q in taken):
                        continue
                    lot = rect_poly(c, t, n, W * 0.5 + 0.6, D * 0.5 + 0.6)
                    dmid = (carry + front) * 0.5
                    dc = (p[0] + n[0] * dmid, p[1] + n[1] * dmid)
                    drive = rect_poly(dc, t, n, DRIVE_W * 0.5, (front - carry) * 0.5)
                    floor_y = p[2] + 0.15
                    remove = []
                    nbuild = 0
                    ok = True
                    for k in near(lot) | near(drive):
                        it = items[k]
                        if it["yhi"] < floor_y - 0.3 or it["ylo"] > floor_y + 12.0:
                            continue
                        hit_lot = overlap(it["poly"], lot)
                        hit_drive = overlap(it["poly"], drive)
                        if not (hit_lot or hit_drive):
                            continue
                        if it["fixed"]:
                            rej["fixed:" + it["mesh"].split("__")[0]] = rej.get("fixed:" + it["mesh"].split("__")[0], 0) + 1
                            ok = False
                            break
                        remove.append(it)
                        if it["cat"] == "building":
                            nbuild += 1
                    if not ok:
                        continue
                    # other roads (and this one beyond the lot) must stay clear of the building
                    for r2, pts2 in roads:
                        hw2 = float(r2["width"]) * 0.5 + 0.5
                        for q in pts2:
                            if abs(q[0] - c[0]) > 30 or abs(q[1] - c[1]) > 30:
                                continue
                            dx, dz = q[0] - c[0], q[1] - c[1]
                            u = abs(dx * t[0] + dz * t[1]) - W * 0.5
                            v = abs(dx * n[0] + dz * n[1]) - D * 0.5
                            if math.hypot(max(u, 0), max(v, 0)) < hw2:
                                rej["road"] = rej.get("road", 0) + 1
                                ok = False
                                break
                        if not ok:
                            break
                    if not ok:
                        continue
                    for su in (-0.5, -0.25, 0.0, 0.25, 0.5):
                        for sv in (-0.5, -0.25, 0.0, 0.25, 0.5):
                            hz = hf(c[0] + t[0] * W * su + n[0] * D * sv, c[1] + t[1] * W * su + n[1] * D * sv)
                            if hz > floor_y + 0.3 or hz < floor_y - 6.0:
                                rej["terrain"] = rej.get("terrain", 0) + 1
                                ok = False
                    if not ok:
                        continue
                    score = math.dist(p[:2], anchor) + 40.0 * nbuild
                    if best is None or score < best[0]:
                        best = (score, r["id"], p, t, n, c, floor_y, front, remove, nbuild)
        if best is None:
            print("no lot for", g["id"], rej)
            continue
        score, rid, p, t, n, c, floor_y, front, remove, nbuild = best
        taken.append(c)
        door = (-n[0], -n[1])                          # the door faces the road
        lot = rect_poly(c, t, n, W * 0.5 + 0.6, D * 0.5 + 0.6)
        rm_lights = []
        for l in lights:
            if l.get("kind") == "Light_lamp":
                continue
            lp = (l["pos"][0], l["pos"][2])
            u = abs((lp[0] - c[0]) * t[0] + (lp[1] - c[1]) * t[1])
            v = abs((lp[0] - c[0]) * n[0] + (lp[1] - c[1]) * n[1])
            if u < W * 0.5 + 2.0 and v < D * 0.5 + 2.0:
                rm_lights.append([round(l["pos"][0], 2), round(l["pos"][1], 2), round(l["pos"][2], 2)])
        e = dict(g)
        e.update({
            "road": rid,
            "pos": [round(c[0], 3), round(floor_y, 3), round(c[1], 3)],
            "yaw": round(math.atan2(door[0], door[1]), 5),       # rotation about Y that turns +Z to the door
            "size": [W, 7.5, D],
            "road_point": [round(p[0], 3), round(p[2], 3), round(p[1], 3)],
            "road_dir": [round(t[0], 4), 0.0, round(t[1], 4)],
            "door_dir": [round(door[0], 4), 0.0, round(door[1], 4)],
            "front": round(front, 2),
            "replaced_buildings": nbuild,
            "remove": [[it["mesh"], round(it["o"][0], 2), round(it["o"][1], 2), round(it["o"][2], 2)] for it in remove],
            "remove_lights": rm_lights,
        })
        out.append(e)
        print("%-20s road %-5s at (%.1f, %.2f, %.1f)  %.0f m from anchor, %d removed (%d buildings), %d lights" % (
            g["id"], rid, c[0], floor_y, c[1], math.dist(p[:2], anchor), len(remove), nbuild, len(rm_lights)))
    with open(a.out, "w") as f:
        json.dump({"format": "garages/1", "generated_by": "game/tools/pick_garages.py", "garages": out}, f, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
