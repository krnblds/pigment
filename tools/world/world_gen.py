"""World data stage: config + seed -> world.json + heightfield.

Runs inside Blender (needs mathutils and tools/blender_town.py's Junction /
catmull / Path), but creates no Blender data. See tools/world/world_driver.py.
"""
import json
import math
import os
import random
import time

import numpy as np
from mathutils import Vector

import network as NW
import placement as PL
import terrain as TR

ROAD_Z, WALK_OUT = 0.2, 3.0


def footprint(cls_cfg):
    side = cls_cfg.get("side", "curb")
    h = cls_cfg["half"]
    return h + {"curb": WALK_OUT, "jersey": 0.5, "guardrail": 1.1}[side]


# ---------------------------------------------------------------- terrain shaping


def flatten_urban(cfg, hf, masks):
    m = masks["urban"] * (1 - TR.smoothstep(0.02, 0.3, masks["mountain"]))
    lvl = TR.blur(hf.H, 60.0 / hf.cell)
    lvl = np.maximum(lvl, 2.6)
    land = hf.H > 0.3
    k = m * land
    hf.H = hf.H * (1 - k) + lvl * k
    return m


def polygon_mask(X0, Y0, cell, shape, poly):
    """Cells (iy, ix) inside a polygon [(x, y)]: returns (iy, ix) arrays."""
    P = np.array(poly)
    x0, y0 = P.min(0)
    x1, y1 = P.max(0)
    i0 = max(0, int((x0 - X0) / cell) - 1)
    i1 = min(shape[1] - 1, int((x1 - X0) / cell) + 2)
    j0 = max(0, int((y0 - Y0) / cell) - 1)
    j1 = min(shape[0] - 1, int((y1 - Y0) / cell) + 2)
    if i1 <= i0 or j1 <= j0:
        return np.array([], int), np.array([], int)
    xs = X0 + np.arange(i0, i1 + 1) * cell
    ys = Y0 + np.arange(j0, j1 + 1) * cell
    XX, YY = np.meshgrid(xs, ys)
    inside = np.zeros(XX.shape, bool)
    n = len(P)
    for k in range(n):
        ax, ay = P[k]
        bx, by = P[(k + 1) % n]
        cond = ((ay > YY) != (by > YY))
        xint = (bx - ax) * (YY - ay) / np.where(by - ay == 0, 1e-12, by - ay) + ax
        inside ^= cond & (XX < xint)
    jj, ii = np.nonzero(inside)
    return jj + j0, ii + i0


def conform_terrain(cfg, hf, net, log):
    """Cut and fill the heightfield to the roads: terrain stays under every
    road and sidewalk surface, lots sit just under sidewalk level, cut/fill
    slopes beyond. Bridge and viaduct decks only push the ground down."""
    H = hf.H
    natural = H.copy()
    cell = hf.cell
    n = hf.n
    xs, ys, zr, w, kind = [], [], [], [], []
    deck_pts = []
    for e in net.alive_edges():
        cc = net.classes[e.cls]
        L = e.path.length
        s = np.linspace(0, L, max(2, int(L / 1.5) + 1))
        pos, t = e.path.at_many(s)
        deck = np.interp(s, e.s, e.deck.astype(float)) > 0.5
        side = cc.get("side", "curb")
        fp = footprint(cc)
        for i in range(len(s)):
            if deck[i]:
                deck_pts.append((pos[i, 0], pos[i, 1], pos[i, 2] - 3.5, fp + 2.0))
                continue
            xs.append(pos[i, 0])
            ys.append(pos[i, 1])
            zr.append(pos[i, 2])
            w.append(fp)
            kind.append(0 if side == "curb" else 1)
    # junction arms
    for nd in net.alive_nodes():
        J = nd.J
        if J is None:
            continue
        for i, d in enumerate(J.dirs):
            for tt in np.arange(0, J.L[i] + 1e-6, 1.5):
                p = J.pos + d * tt
                xs.append(p.x)
                ys.append(p.y)
                zr.append(J.z)
                w.append(J.half[i] + WALK_OUT)
                kind.append(0)
    xs, ys, zr, w, kind = map(np.array, (xs, ys, zr, w, kind))
    R = 34.0
    best = np.full(n * n, np.inf)
    bz = np.zeros(n * n)
    bh = np.zeros(n * n)              # distance from the centreline minus the carriageway half
    bk = np.zeros(n * n, dtype=np.int8)
    ci = np.round((xs - hf.x0) / cell).astype(int)
    cj = np.round((ys - hf.x0) / cell).astype(int)
    rc = int(math.ceil((w.max() + R) / cell))
    half = w - np.where(kind == 0, WALK_OUT, 0.0)
    for oy in range(-rc, rc + 1):
        for ox in range(-rc, rc + 1):
            if (ox * ox + oy * oy) * cell * cell > (w.max() + R + 2) ** 2:
                continue
            ii, jj = ci + ox, cj + oy
            ok = (ii >= 0) & (ii < n) & (jj >= 0) & (jj < n)
            px = hf.x0 + ii * cell
            py = hf.x0 + jj * cell
            d = np.hypot(px - xs, py - ys)
            key = d - w
            ok &= key < R
            if not ok.any():
                continue
            idx = (jj * n + ii)[ok]
            key_ = key[ok]
            order = np.argsort(-key_)
            idx, key_ = idx[order], key_[order]
            m = key_ < best[idx]
            sel = np.nonzero(ok)[0][order][m]
            best[idx[m]] = key_[m]
            bz[idx[m]] = zr[sel]
            bh[idx[m]] = (d[sel] - half[sel])
            bk[idx[m]] = kind[sel]
    best = best.reshape(n, n)
    bz = bz.reshape(n, n)
    bh = bh.reshape(n, n)
    bk = bk.reshape(n, n)
    has = np.isfinite(best)
    margin = 2.9
    curb = bk == 0
    # road band: under asphalt +0.1, under the outer sidewalk +0.30 (curbed), -0.3 (barriers)
    band = has & (best <= margin)
    base_band = np.where(curb, np.where(bh > 1.8, 0.30, 0.10), -0.3)
    hi_base = np.where(curb, 0.30, -0.3)
    lo_base = np.where(curb, -0.3, -1.0)
    k = np.where(has, np.maximum(best - margin, 0.0), 0.0)
    z_hi = bz + hi_base + 1.0 * np.maximum(k - (3.0 if True else 0), 0.0)
    z_lo = bz + lo_base - 0.7 * k
    out = np.where(has, np.clip(natural, z_lo, z_hi), natural)
    out = np.where(band, bz + base_band, out)
    # junction / plaza polygons (corners included), dilated by a grid diagonal
    nj = 0
    for nd in net.alive_nodes():
        J = nd.J
        if J is None:
            continue
        ring = []
        for c in J.corners:
            ring += [J.pos + p for p in J.corner_line(c, WALK_OUT + 2.9)]
        jj, ii = polygon_mask(hf.x0, hf.x0, cell, (n, n), [(p.x, p.y) for p in ring])
        inner = []
        for c in J.corners:
            inner += [J.pos + p for p in J.corner_line(c, 1.8)]
        j2, i2 = polygon_mask(hf.x0, hf.x0, cell, (n, n), [(p.x, p.y) for p in inner])
        out[jj, ii] = J.z + 0.30
        out[j2, i2] = J.z + 0.10
        nj += 1
    # decks: keep the ground below the girder
    for x, y, zc, r in deck_pts:
        i0, i1 = int((x - r - hf.x0) / cell), int((x + r - hf.x0) / cell) + 1
        j0, j1 = int((y - r - hf.x0) / cell), int((y + r - hf.x0) / cell) + 1
        i0, j0 = max(i0, 0), max(j0, 0)
        sub = out[j0:j1 + 1, i0:i1 + 1]
        np.minimum(sub, zc, out=sub)
    hf.H = out
    log(f"conform: {int(band.sum())} cells under roads, {nj} junction pads, {len(deck_pts)} deck samples")


# ---------------------------------------------------------------- contours (sea walls)


def contours(F, level, x0, cell):
    """Marching squares polylines of F == level (world coords)."""
    a = F[:-1, :-1] > level
    b = F[:-1, 1:] > level
    c = F[1:, 1:] > level
    d = F[1:, :-1] > level
    code = a * 1 + b * 2 + c * 4 + d * 8
    segs = []
    jj, ii = np.nonzero((code > 0) & (code < 15))

    def P(j, i, side):
        if side == 0:     # bottom edge (j, i)-(j, i+1)
            f0, f1 = F[j, i], F[j, i + 1]
            t = (level - f0) / (f1 - f0)
            return (round(i + t, 4), float(j))
        if side == 1:     # right (j, i+1)-(j+1, i+1)
            f0, f1 = F[j, i + 1], F[j + 1, i + 1]
            t = (level - f0) / (f1 - f0)
            return (float(i + 1), round(j + t, 4))
        if side == 2:     # top (j+1, i)-(j+1, i+1)
            f0, f1 = F[j + 1, i], F[j + 1, i + 1]
            t = (level - f0) / (f1 - f0)
            return (round(i + t, 4), float(j + 1))
        f0, f1 = F[j, i], F[j + 1, i]
        t = (level - f0) / (f1 - f0)
        return (float(i), round(j + t, 4))
    table = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: [(3, 0), (1, 2)], 6: [(0, 2)], 7: [(3, 2)],
             8: [(2, 3)], 9: [(2, 0)], 10: [(0, 1), (2, 3)], 11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)]}
    for j, i in zip(jj, ii):
        for s0, s1 in table[int(code[j, i])]:
            segs.append((P(j, i, s0), P(j, i, s1)))
    # chain
    adj = {}
    for k, (p, q) in enumerate(segs):
        adj.setdefault(p, []).append(k)
        adj.setdefault(q, []).append(k)
    used = [False] * len(segs)
    lines = []
    for k in range(len(segs)):
        if used[k]:
            continue
        used[k] = True
        line = [segs[k][0], segs[k][1]]
        for direction in (0, 1):
            while True:
                end = line[-1] if direction == 0 else line[0]
                nxt = [m for m in adj.get(end, []) if not used[m]]
                if not nxt:
                    break
                m = nxt[0]
                used[m] = True
                p, q = segs[m]
                o = q if p == end else p
                if direction == 0:
                    line.append(o)
                else:
                    line.insert(0, o)
        lines.append([(x0 + x * cell, x0 + y * cell) for x, y in line])
    return lines


def _road_gaps(net, pad=2.5):
    """(xy points, clearance radius) along every road, for cutting sea walls where roads pass."""
    pts, rad = [], []
    for e in net.alive_edges():
        half = net.classes[e.cls]["half"] + pad
        for p in e.pts2d:
            pts.append((p.x, p.y))
            rad.append(half)
    return np.array(pts), np.array(rad)


def sea_walls(cfg, hf, masks, net, log):
    step = 4
    RP, RR = _road_gaps(net)
    F = hf.H[::step, ::step]
    c = hf.cell * step
    U = TR.blur(masks["urban_flat"][::step, ::step], 30.0 / c)
    walls = []
    for line in contours(F, 0.8, hf.x0, c):
        if len(line) < 6:
            continue
        P = np.array(line)
        ix = np.clip(np.round((P[:, 0] - hf.x0) / c).astype(int), 0, U.shape[1] - 1)
        iy = np.clip(np.round((P[:, 1] - hf.x0) / c).astype(int), 0, U.shape[0] - 1)
        urb = U[iy, ix] > 0.12
        # split into urban stretches
        idx = np.nonzero(urb)[0]
        if len(idx) < 4:
            continue
        # never across a road: drop wall points within a road's half width (+ pad)
        if len(RP):
            keep = np.ones(len(idx), bool)
            for k, i in enumerate(idx):
                d = np.hypot(RP[:, 0] - P[i, 0], RP[:, 1] - P[i, 1])
                if np.any(d < RR + c):
                    keep[k] = False
            idx = idx[keep]
            if len(idx) < 4:
                continue
        for r in np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1):
            if len(r) < 5:
                continue
            Q = P[r]
            for _ in range(3):
                Q[1:-1] = Q[1:-1] * 0.5 + (Q[:-2] + Q[2:]) * 0.25
            # top: the land just inland (max within 8 m), parapet 1.0 m
            tops = []
            for k in range(len(Q)):
                xs = Q[k, 0] + np.linspace(-8, 8, 5)[:, None] * 0 + np.array([[0, 6, -6, 0, 0]]).T * 0
                pts_x = Q[k, 0] + np.array([0, 6, -6, 0, 0, 4, -4, 4, -4])
                pts_y = Q[k, 1] + np.array([0, 0, 0, 6, -6, 4, 4, -4, -4])
                tops.append(float(np.max(hf.sample(pts_x, pts_y))) + 1.0)
            walls.append({"points": [[round(float(a), 2), round(float(b), 2)] for a, b in Q], "top": [round(t, 2) for t in tops], "bottom": -4.0})
    log(f"sea walls: {len(walls)} stretches, {sum(len(w['points']) for w in walls) * c:.0f} m")
    return walls


# ---------------------------------------------------------------- structures (decks, piers, pylons)


def structures(cfg, hf, natural, net, log):
    """Per edge: which samples are decks (over water or > 2.5 m above the
    natural ground), the bridge spans, piers, pylons, cables and arches."""
    bridges = []
    for e in net.alive_edges():
        t = natural.sample([p.x for p in e.pts2d], [p.y for p in e.pts2d])
        above = e.z - t
        deck = (above > 2.5) | (t < 0.4)
        # close gaps < 25 m, drop islands < 20 m
        s = e.s
        deck = close_runs(deck, s, 25.0, True)
        deck = close_runs(deck, s, 20.0, False)
        e.deck = deck
    for e in net.alive_edges():
        if not e.deck.any():
            continue
        idx = np.nonzero(e.deck)[0]
        runs = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1)
        cc = net.classes[e.cls]
        t = natural.sample([p.x for p in e.pts2d], [p.y for p in e.pts2d])
        kind = (e.link or {}).get("bridge") or ("viaduct" if (e.link or {}).get("elevated") else "girder")
        for r in runs:
            s0, s1 = float(e.s[r[0]]), float(e.s[r[-1]])
            if s1 - s0 < 15:
                continue
            br = {"name": f"{e.name or 'deck'}_{e.id}_{int(s0)}", "type": kind, "edge": e.id, "s": [round(s0, 2), round(s1, 2)],
                  "half": cc["half"] + 0.5, "piers": [], "pylons": [], "cables": [], "arches": [], "hangers": [], "depth": 2.4}
            wet = t[r] < 0.4
            # main span over the water channel
            main = None
            if wet.any() and kind in ("cable_stayed", "arch"):
                wi = r[wet]
                w0, w1 = float(e.s[wi[0]]), float(e.s[wi[-1]])
                sc = (w0 + w1) / 2
                span = min((w1 - w0) * (0.6 if kind == "cable_stayed" else 0.75), 420.0 if kind == "cable_stayed" else 230.0)
                main = (sc - span / 2, sc + span / 2)
            spacing = {"cable_stayed": 55.0, "arch": 45.0, "girder": 48.0, "viaduct": 36.0}.get(kind, 45.0)
            if kind == "girder":
                br["depth"] = 3.2
            # piers
            ss = s0 + spacing * 0.5
            while ss < s1 - spacing * 0.3:
                if main and main[0] - 5 < ss < main[1] + 5:
                    ss = main[1] + spacing
                    continue
                p, tg = e.path.at(ss)
                ok = pier_clear(net, e, p, cc["half"])
                if not ok:
                    for dd in (6, -6, 12, -12, 18, -18):
                        p2, tg2 = e.path.at(ss + dd)
                        if pier_clear(net, e, p2, cc["half"]):
                            p, tg, ok = p2, tg2, True
                            ss += dd
                            break
                if ok:
                    g = float(hf.sample([p.x], [p.y])[0])
                    br["piers"].append({"s": round(ss, 2), "pos": [round(p.x, 2), round(p.y, 2)], "dir": [round(tg.x, 4), round(tg.y, 4)],
                                        "top": round(p.z - br["depth"] - 0.2, 2), "bottom": round(min(g, 0.0) - 2.0 if g < 0.5 else g - 1.0, 2)})
                ss += spacing
            if main and kind == "cable_stayed":
                for sp in main:
                    p, tg = e.path.at(sp)
                    g = float(hf.sample([p.x], [p.y])[0])
                    top = p.z + 96.0
                    br["pylons"].append({"s": round(sp, 2), "pos": [round(p.x, 2), round(p.y, 2)], "dir": [round(tg.x, 4), round(tg.y, 4)],
                                         "deck": round(p.z, 2), "top": round(top, 2), "bottom": round(min(g, 0.0) - 3.0, 2)})
                    # fan of stays both ways, two planes at the deck edges
                    for side in (-1, 1):
                        nrm = Vector((-tg.y, tg.x)) * side
                        for k in range(1, 15):
                            for sgn in (-1, 1):
                                sd = sp + sgn * k * (span / 2 / 14.5)
                                q, _ = e.path.at(sd)
                                a = p.to_2d() + nrm * (cc["half"] + 0.9)
                                b = q.to_2d() + nrm * (cc["half"] + 0.9)
                                za = top - 4.0 - (14 - k) * 3.0
                                br["cables"].append([[round(a.x, 2), round(a.y, 2), round(za, 2)], [round(b.x, 2), round(b.y, 2), round(q.z + 0.6, 2)]])
            if main and kind == "arch":
                L = main[1] - main[0]
                rise = 0.22 * L
                for side in (-1, 1):
                    rib = []
                    for k in range(41):
                        f = k / 40
                        sd = main[0] + L * f
                        q, tg = e.path.at(sd)
                        nrm = Vector((-tg.y, tg.x)) * side
                        b = q.to_2d() + nrm * (cc["half"] + 1.2)
                        z0 = e.path.at(main[0])[0].z
                        z1 = e.path.at(main[1])[0].z
                        zb = z0 * (1 - f) + z1 * f
                        rib.append([round(b.x, 2), round(b.y, 2), round(zb + 4 * rise * f * (1 - f) + 0.5, 2)])
                    br["arches"].append(rib)
                    for k in range(2, 39, 2):
                        f = k / 40
                        q, tg = e.path.at(main[0] + L * f)
                        br["hangers"].append([rib[k], [rib[k][0], rib[k][1], round(q.z + 1.0, 2)]])
                for sp in main:
                    p, tg = e.path.at(sp)
                    g = float(hf.sample([p.x], [p.y])[0])
                    br["piers"].append({"s": round(sp, 2), "pos": [round(p.x, 2), round(p.y, 2)], "dir": [round(tg.x, 4), round(tg.y, 4)],
                                        "top": round(p.z - br["depth"] - 0.2, 2), "bottom": round(min(g, 0.0) - 2.0, 2), "heavy": True})
            bridges.append(br)
    log("structures: " + ", ".join(f"{b['type']} {b['s'][1] - b['s'][0]:.0f} m ({len(b['piers'])} piers)" for b in bridges if b['s'][1] - b['s'][0] > 120))
    return bridges


def close_runs(mask, s, length, value):
    """Flip runs of `not value` shorter than `length` (metres) to `value`."""
    m = mask.copy()
    n = len(m)
    i = 0
    while i < n:
        if m[i] != value:
            j = i
            while j < n and m[j] != value:
                j += 1
            inner = i > 0 and j < n
            if (s[min(j, n - 1)] - s[i] < length) and (inner or not value):
                m[i:j] = value
            i = j
        else:
            i += 1
    return m


def pier_clear(net, e, p, half):
    """A pier must not stand on another road or junction."""
    for f in net.alive_edges():
        if f is e:
            continue
        P = f.pts2d
        hw = net.classes[f.cls]["half"] + 4.0
        for q in P[::4]:
            if abs(q.x - p.x) < 40 and abs(q.y - p.y) < 40 and (q - p.to_2d()).length < hw + 2.0:
                f_z = f.path.at(0)[0].z
                return False
    for nd in net.alive_nodes():
        if nd.J is not None and (nd.pos - p.to_2d()).length < max(nd.J.L) + 6.0:
            return False
    return True


# ---------------------------------------------------------------- lanes / signals


def lane_graph(cfg, net):
    """Roads (centreline, lanes, speed), junction connections, signals."""
    roads = []
    for e in net.alive_edges():
        cc = net.classes[e.cls]
        L = e.path.length
        s = adaptive_stations(e.path)
        pos, t = e.path.at_many(s)
        lanes = []
        for k, ln in enumerate(cc["lanes"]):
            lanes.append({"id": k, "offset": ln["offset"], "dir": ln["dir"], "width": ln["width"], "kind": ln.get("kind", "drive")})
        deck = np.interp(s, e.s, e.deck.astype(float)) > 0.5
        roads.append({
            "id": f"r{e.id}", "class": e.cls, "name": e.name, "kind": e.kind,
            "start": {"node": f"n{e.a.id}", "arm": arm_index(e.a, e, 0)},
            "end": {"node": f"n{e.b.id}", "arm": arm_index(e.b, e, 1)},
            "length": round(L, 2), "half_width": cc["half"], "width": round(2 * footprint(cc), 2),
            "carriageway": round(2 * cc["half"], 2), "side": cc.get("side", "curb"), "median": cc.get("median", 0.0),
            "speed_kmh": cc["speed_kmh"], "one_way": all(l["dir"] > 0 for l in cc["lanes"]) or all(l["dir"] < 0 for l in cc["lanes"]),
            "lanes_per_dir": {"forward": sum(1 for l in lanes if l["dir"] > 0 and l["kind"] == "drive"),
                              "backward": sum(1 for l in lanes if l["dir"] < 0 and l["kind"] == "drive")},
            "lanes": lanes, "max_grade": round(e.grade, 4),
            "points": [[round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]) + ROAD_Z, 2)] for p in pos],
            "deck": [int(b) for b in deck],
        })
    return roads


def adaptive_stations(path, max_step=8.0, fine=0.5, max_turn=0.75, max_dslope=0.004):
    """Centreline samples for world.json: dense on curves and grade changes
    (chord error under ~2 cm), up to max_step apart on straights."""
    L = path.length
    n = max(2, int(math.ceil(L / fine)) + 1)
    s = np.linspace(0.0, L, n)
    pos, t = path.at_many(s)
    head = np.unwrap(np.arctan2(t[:, 1], t[:, 0]))
    slope = np.gradient(pos[:, 2], s) if n > 2 else np.zeros(n)
    keep = [0]
    for i in range(1, n - 1):
        k = keep[-1]
        if s[i + 1] - s[k] > max_step or abs(head[i + 1] - head[k]) > math.radians(max_turn) or abs(slope[i + 1] - slope[k]) > max_dslope:
            keep.append(i)
    keep.append(n - 1)
    return s[keep]


def arm_index(node, e, k):
    if hasattr(node, "arm_of") and (e.id, k) in node.arm_of:
        return node.arm_of[(e.id, k)]
    return None


def junctions_json(cfg, net):
    out = []
    signals = []
    for nd in net.alive_nodes():
        J = nd.J
        ends = [{"road": f"r{e.id}", "end": "start" if k == 0 else "end"} for e, k in nd.ends]
        if J is None:
            out.append({"id": f"n{nd.id}", "kind": nd.kind, "pos": [round(nd.pos.x, 2), round(nd.pos.y, 2), round(nd.z + ROAD_Z, 2)], "roads": ends,
                        "connections": straight_connections(net, nd)})
            continue
        arms = []
        for i, (e, k) in enumerate(nd.ends):
            ai = nd.arm_of[(e.id, k)]
            d = J.dirs[ai]
            arms.append({"index": ai, "angle": round(J.arms[ai] % 360, 2), "dir": [round(d.x, 4), round(d.y, 4)], "length": round(J.L[ai], 2),
                         "half_width": J.half[ai], "road": f"r{e.id}", "end": "start" if k == 0 else "end",
                         "mouth": [round(nd.pos.x + d.x * J.L[ai], 2), round(nd.pos.y + d.y * J.L[ai], 2)]})
        arms.sort(key=lambda a: a["index"])
        signal = nd.kind == "junction" and len(arms) >= 3 and any(a["half_width"] > 6 for a in arms)
        jj = {"id": f"n{nd.id}", "kind": nd.kind if nd.kind != "junction" else {2: "L", 3: "T", 4: "X"}.get(len(arms), "multi"),
              "pos": [round(nd.pos.x, 2), round(nd.pos.y, 2), round(nd.z + ROAD_Z, 2)], "z": nd.z, "geom": nd.geom, "arms": arms, "roads": ends,
              "signalised": signal, "connections": junction_connections(net, nd)}
        if signal:
            for a in arms:
                d = Vector(a["dir"])
                nrm = Vector((-d.y, d.x))
                # left-hand traffic: the approach comes in on the -nrm side; pole on its kerb corner
                p = nd.pos + d * (a["length"] - 2.5) - nrm * (a["half_width"] + 0.9)
                head = -d
                phase = "A" if min(adiff(a["angle"], arms[0]["angle"]), adiff(a["angle"], arms[0]["angle"] + 180)) < 45 else "B"
                sig = {"id": f"s{nd.id}_{a['index']}", "junction": jj["id"], "arm": a["index"], "controls": {"road": a["road"], "end": a["end"]},
                       "pos": [round(p.x, 2), round(p.y, 2), round(nd.z + 0.35, 2)], "facing": [round(head.x, 4), round(head.y, 4)],
                       "mast": round(a["half_width"] - 0.8, 2), "phase": phase,
                       "stop_line": [round(nd.pos.x + d.x * (a["length"] - 4.8), 2), round(nd.pos.y + d.y * (a["length"] - 4.8), 2)]}
                signals.append(sig)
        out.append(jj)
    return out, signals


def adiff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def lane_world(net, e, lane, at_end):
    """World point (x, y, z) and travel direction of a lane at a road end."""
    s = e.path.length if at_end else 0.0
    p, t = e.path.at(s)
    nrm = Vector((-t.y, t.x))
    q = p.to_2d() + nrm * lane["offset"]
    d = t if lane["dir"] > 0 else -t
    return Vector((q.x, q.y, p.z + ROAD_Z)), d


def junction_connections(net, nd):
    """Lane connectors: every incoming driving lane to the outgoing driving
    lanes of every other arm, matched from the kerb side (left-hand traffic:
    left turns from the left-most lane, right turns from the right-most)."""
    conns = []
    for e1, k1 in nd.ends:
        lanes1 = [l for l in net.classes[e1.cls]["lanes"] if l.get("kind", "drive") == "drive"]
        # incoming: travelling towards this node
        inc = [(i, l) for i, l in enumerate(net.classes[e1.cls]["lanes"]) if l.get("kind", "drive") == "drive" and ((l["dir"] > 0) == (k1 == 1))]
        inc.sort(key=lambda il: -abs(il[1]["offset"]))           # kerb side first
        for e2, k2 in nd.ends:
            if e2 is e1 and k2 == k1:
                continue
            out = [(i, l) for i, l in enumerate(net.classes[e2.cls]["lanes"]) if l.get("kind", "drive") == "drive" and ((l["dir"] > 0) == (k2 == 0))]
            out.sort(key=lambda il: -abs(il[1]["offset"]))
            if not inc or not out:
                continue
            p1, d1 = lane_world(net, e1, inc[0][1], k1 == 1)
            p2, d2 = lane_world(net, e2, out[0][1], k2 == 1)
            cr = d1.x * d2.y - d1.y * d2.x
            turn = "straight" if d1.dot(d2) > 0.7 else ("left" if cr > 0 else "right")
            pairs = []
            if turn == "left":
                pairs = [(inc[0], out[0])]
            elif turn == "right":
                pairs = [(inc[-1], out[-1])]
            else:
                for k in range(max(len(inc), len(out))):
                    pairs.append((inc[min(k, len(inc) - 1)], out[min(k, len(out) - 1)]))
            for (i1, l1), (i2, l2) in pairs:
                a, da = lane_world(net, e1, l1, k1 == 1)
                b, db = lane_world(net, e2, l2, k2 == 1)
                L = (b - a).length
                c1 = a + da.to_3d() * L * 0.4
                c2 = b - db.to_3d() * L * 0.4
                pts = []
                for k in range(9):
                    u = k / 8
                    q = a * (1 - u) ** 3 + c1 * 3 * u * (1 - u) ** 2 + c2 * 3 * u * u * (1 - u) + b * u ** 3
                    pts.append([round(q.x, 2), round(q.y, 2), round(q.z, 2)])
                conns.append({"from": {"road": f"r{e1.id}", "lane": i1}, "to": {"road": f"r{e2.id}", "lane": i2}, "turn": turn, "points": pts})
    return conns


def straight_connections(net, nd):
    conns = []
    if len(nd.ends) != 2:
        return conns
    (e1, k1), (e2, k2) = nd.ends
    for a, ka, b, kb in ((e1, k1, e2, k2), (e2, k2, e1, k1)):
        for i, l in enumerate(net.classes[a.cls]["lanes"]):
            if l.get("kind", "drive") != "drive" or (l["dir"] > 0) != (ka == 1):
                continue
            # same offset magnitude on the other road, same travel side
            best = None
            for j, m in enumerate(net.classes[b.cls]["lanes"]):
                if m.get("kind", "drive") != "drive" or (m["dir"] > 0) != (kb == 0):
                    continue
                if best is None or abs(abs(m["offset"]) - abs(l["offset"])) < best[0]:
                    best = (abs(abs(m["offset"]) - abs(l["offset"])), j)
            if best:
                conns.append({"from": {"road": f"r{a.id}", "lane": i}, "to": {"road": f"r{b.id}", "lane": best[1]}, "turn": "straight"})
    return conns


# ---------------------------------------------------------------- main


def generate(cfg, town, out_dir, log=print):
    t0 = time.time()
    hf, masks = TR.generate(cfg, log)
    log(f"terrain generated in {time.time() - t0:.0f} s, z {hf.H.min():.1f}..{hf.H.max():.1f}")
    masks["urban_flat"] = flatten_urban(cfg, hf, masks)
    natural_H = hf.H.copy()
    net = NW.Network(cfg, hf, town, log)
    noise = TR.Perlin(cfg["seed"])
    net.build_grids(masks, noise)
    net.build_links()
    net.build_mountain()
    net.prune()
    net.merge_straight()
    removed = 0
    for rnd in range(6):
        net.junction_heights()
        net.make_junctions()
        net.build_paths()
        net.solve_profiles()
        req, conflicts = net.crossings()
        bad = net.solve_profiles(req)
        # crossings the deck cannot clear (too close to an at-grade end): drop the road below
        kill = []
        for u, x, su in conflicts:
            zu = float(np.interp(su, u.s, u.z))
            if isinstance(x, NW.Edge):
                pts = np.array([(p.x, p.y) for p in x.pts2d])
                need = float(np.max(x.z)) + u.link.get("clearance", 7.5) - 0.4
                if zu < need:
                    kill.append(x)
            else:
                if zu < x.z + u.link.get("clearance", 7.5) - 0.4:
                    kill += [e for e, _ in x.ends if e.kind == "grid"]
        kill = [k for k in {id(k): k for k in kill}.values() if k.alive and k.kind == "grid"]
        if not kill:
            break
        for k in kill:
            net.kill(k)
        removed += len(kill)
        net.prune()
        net.merge_straight()
        for n in net.nodes:
            n.J = None
    log(f"profiles solved ({removed} grid roads removed under at-grade expressway ends); infeasible: {[(e.id, e.name, round(b, 1)) for e, b in bad]}")
    nat = TR.Heightfield(hf.size, hf.cell)
    nat.H = natural_H
    bridges = structures(cfg, hf, nat, net, log)
    net.split_transitions()
    for e in net.alive_edges():
        if not hasattr(e, "deck") or len(e.deck) != len(e.s):
            e.deck = np.interp(e.s, e.s, np.zeros(len(e.s))) > 1
            t = nat.sample([p.x for p in e.pts2d], [p.y for p in e.pts2d])
            e.deck = close_runs(close_runs((e.z - t > 2.5) | (t < 0.4), e.s, 25.0, True), e.s, 20.0, False)
    # bridges reference the pre-split edge: re-point them to the piece holding the span
    for br in bridges:
        old = next(e for e in net.edges if e.id == br["edge"])
        if not old.alive and hasattr(old, "split_into"):
            off, best = 0.0, None
            for f in old.split_into:
                a, b = max(br["s"][0], off), min(br["s"][1], off + f.path.length)
                if best is None or b - a > best[0]:
                    best = (b - a, f, off)
                off += f.path.length
            _, f, off = best
            br["edge"] = f.id
            br["s"] = [round(max(0.0, br["s"][0] - off), 2), round(min(f.path.length, br["s"][1] - off), 2)]
    conform_terrain(cfg, hf, net, log)
    walls = sea_walls(cfg, hf, masks, net, log)
    # plaza: flatten the summit
    roads = lane_graph(cfg, net)
    juncs, signals = junctions_json(cfg, net)
    place = PL.place_all(cfg, hf, net, masks, bridges, walls, log)
    PL.signal_instances(cfg, signals, juncs, place, log)
    # outputs
    os.makedirs(out_dir, exist_ok=True)
    hpath = os.path.join(out_dir, "heightfield.f32")
    hf.H.astype("<f4").tofile(hpath)
    np.save(os.path.join(out_dir, "masks_urban.npy"), masks["urban_flat"].astype(np.float16))
    chunk = cfg["chunk_m"]
    nch = int(cfg["size_m"] // chunk)
    per = int(round(chunk / hf.cell))
    chunks = []
    for cy in range(nch):
        for cx in range(nch):
            sub = hf.H[cy * per:(cy + 1) * per + 1, cx * per:(cx + 1) * per + 1]
            if sub.max() < -6.0:
                continue           # open sea: only the coarse sea floor
            chunks.append({"id": f"t{cx}_{cy}", "ix": cx, "iy": cy, "origin": [hf.x0 + cx * chunk, hf.x0 + cy * chunk],
                           "size_m": chunk, "zmin": round(float(sub.min()), 2), "zmax": round(float(sub.max()), 2),
                           "land": float((sub > 0).mean()) > 0.0})
    world = {
        "format": "pigment-world/1",
        "name": cfg["name"], "seed": cfg["seed"], "units": "metres", "up": "z",
        "coords": "Blender world space: x east, y north, z up. Godot: (x, z, -y).",
        "traffic": "left-hand",
        "size_m": cfg["size_m"], "sea_level": cfg["sea_level"],
        "terrain": {"heightfield": "heightfield.f32", "dtype": "float32 little-endian, row-major [iy][ix]", "n": hf.n, "cell_m": hf.cell,
                    "origin": [hf.x0, hf.x0], "chunk_m": chunk, "chunk_cells": per, "lod_cells_m": cfg["terrain"]["lod_cells_m"],
                    "chunks": chunks, "sea_floor_m": cfg["terrain"]["sea_floor"],
                    "materials": {"blend": "rock by slope (> 35 deg), grass / dirt by height and noise, sand below 2.5 m on natural shores"}},
        "islands": [{k: isl[k] for k in ("name", "kind", "center", "radius", "rotation")} for isl in cfg["islands"]],
        "districts": place["districts"],
        "road_classes": cfg["classes"],
        "roads": roads,
        "junctions": juncs,
        "signals": signals,
        "bridges": bridges,
        "sea_walls": walls,
        "instances": place["instances"],
        "towers": place["towers"],
        "wires": place["wires"],
        "lights": place["lights"],
        "spawn": place["spawn"],
        "metrics": {},
    }
    world["instances"] = clear_carriageways(world, log)
    world["metrics"] = metrics(world, net, hf)
    with open(os.path.join(out_dir, "world.json"), "w", encoding="utf-8") as f:
        json.dump(world, f, separators=(",", ":"))
    log(f"world.json: {os.path.getsize(os.path.join(out_dir, 'world.json')) / 1e6:.1f} MB; data stage {time.time() - t0:.0f} s")
    log("METRICS " + json.dumps(world["metrics"]))
    return world, net, hf


def _near_road(grid, pts, half, zz, x, y, z, cell, dz, extra):
    gx, gy = int(x // cell), int(y // cell)
    for ix in (gx - 1, gx, gx + 1):
        for iy in (gy - 1, gy, gy + 1):
            for k in grid.get((ix, iy), ()):
                if abs(z - zz[k]) < dz and (pts[k, 0] - x) ** 2 + (pts[k, 1] - y) ** 2 < (half[k] + extra) ** 2:
                    return True
    return False


def clear_carriageways(world, log, margin=0.5, dz=3.0):
    """Last safety pass: drop anything standing on a carriageway (between the curbs,
    within dz metres of the deck height) or inside a junction's paved box. Signals,
    lamps, poles and signs are kerbside by construction and are left alone."""
    import numpy as np
    keep_kinds = {"signal", "lamp", "pole", "sign"}
    pts, half, zz = [], [], []
    for r in world["roads"]:
        P = np.asarray(r["points"], float)
        hw = r["carriageway"] / 2 + margin
        for a, b in zip(P[:-1], P[1:]):
            n = max(1, int(np.linalg.norm(b[:2] - a[:2]) / 0.75))
            for t in np.linspace(0.0, 1.0, n, endpoint=False):
                q = a + (b - a) * t
                pts.append(q[:2]); half.append(hw); zz.append(q[2])
    pts = np.asarray(pts); half = np.asarray(half); zz = np.asarray(zz)
    jp = np.asarray([j["pos"][:2] for j in world["junctions"]]) if world["junctions"] else np.zeros((0, 2))
    jr = np.asarray([max((j.get("geom") or {}).get("halves") or [8.0]) for j in world["junctions"]])
    cell = 16.0
    grid = {}
    for k, q in enumerate(pts):
        grid.setdefault((int(q[0] // cell), int(q[1] // cell)), []).append(k)
    kept, dropped = [], {}
    pruned = 0
    for inst in world["instances"]:
        if inst.get("kind") in keep_kinds:
            kept.append(inst)
            continue
        x, y, z = inst["pos"]
        # trees spread their crowns: keep their trunks 1.2 m further back from the carriageway
        extra = 1.0 if inst.get("kind") == "tree" else 0.0
        hit = False
        gx, gy = int(x // cell), int(y // cell)
        for ix in (gx - 1, gx, gx + 1):
            for iy in (gy - 1, gy, gy + 1):
                for k in grid.get((ix, iy), ()):
                    if abs(z - zz[k]) < dz and (pts[k, 0] - x) ** 2 + (pts[k, 1] - y) ** 2 < (half[k] + extra) ** 2:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        if not hit and len(jp):
            d = np.hypot(jp[:, 0] - x, jp[:, 1] - y)
            hit = bool(np.any(d < jr))
        if hit:
            dropped[inst.get("asset")] = dropped.get(inst.get("asset"), 0) + 1
        else:
            if inst.get("kind") == "tree" and _near_road(grid, pts, half, zz, x, y, z, cell, dz, 4.0):
                # street trees are pruned narrow on the road side: a slimmer crown keeps lanes clear
                sc = inst.get("scale", [1, 1, 1])
                inst["scale"] = [round(sc[0] * 0.7, 4), round(sc[1] * 0.7, 4), sc[2]]
                pruned += 1
            kept.append(inst)
    log(f"clear_carriageways: pruned {pruned} roadside tree crowns")
    log(f"clear_carriageways: dropped {sum(dropped.values())} " + ", ".join(f"{k} {v}" for k, v in sorted(dropped.items())))
    return kept


def metrics(world, net, hf):
    roads = world["roads"]
    by = {}
    for r in roads:
        by[r["class"]] = by.get(r["class"], 0.0) + r["length"]
    inst = {}
    for i in world["instances"]:
        inst[i["asset"]] = inst.get(i["asset"], 0) + 1
    land = float((hf.H > 0).mean()) * world["size_m"] ** 2 / 1e6
    return {
        "land_km2": round(land, 2),
        "road_km": {k: round(v / 1000, 2) for k, v in sorted(by.items())},
        "road_km_total": round(sum(by.values()) / 1000, 2),
        "roads": len(roads), "junctions": sum(1 for j in world["junctions"] if j["kind"] not in ("transition",)),
        "signals": len(world["signals"]), "bridges": len([b for b in world["bridges"] if b["s"][1] - b["s"][0] > 120]),
        "decks": len(world["bridges"]),
        "max_grade_by_class": {c: round(max([r["max_grade"] for r in roads if r["class"] == c] or [0]), 4) for c in by},
        "instances": inst, "towers": len(world["towers"]), "terrain_chunks": len(world["terrain"]["chunks"]),
        "summit_m": round(float(hf.H.max()), 1),
    }
