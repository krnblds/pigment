"""Road network for the world: district grids, links (bridges, expressway),
the mountain road, junction geometry, vertical profiles, structures and the
lane graph. Pure data (numpy + mathutils); runs inside Blender because it
reuses tools/blender_town.py's Junction, catmull() and Path.
"""
import heapq
import math
import random

import numpy as np
from mathutils import Vector

import terrain as TR


def v2(p):
    return Vector((float(p[0]), float(p[1])))


def ang(v):
    return math.degrees(math.atan2(v.y, v.x)) % 360.0


def adiff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


# ---------------------------------------------------------------- graph


class Node:
    def __init__(self, nid, pos, kind="junction", grid=None):
        self.id = nid
        self.pos = v2(pos)
        self.kind = kind              # junction | transition | plaza
        self.grid = grid
        self.ends = []                # [(edge, 0 | 1)]
        self.z = 0.0
        self.reserved = False
        self.J = None                 # blender_town.Junction (or Plaza)

    def degree(self):
        return len(self.ends)


class Edge:
    def __init__(self, eid, a, b, cls, kind="grid"):
        self.id = eid
        self.a, self.b = a, b         # Node
        self.cls = cls
        self.kind = kind              # grid | link | mountain
        self.via = []                 # 2D waypoints between the arm ends
        self.name = ""
        self.link = None              # link config
        self.path = None
        self.alive = True
        self.zmin = []                # [(s0, s1, z)] clearance requirements (filled per solve)

    def other(self, n):
        return self.b if n is self.a else self.a


class Network:
    def __init__(self, cfg, hf, town, log=print):
        self.cfg = cfg
        self.hf = hf
        self.T = town                 # blender_town namespace
        self.log = log
        self.rng = random.Random(cfg["seed"])
        self.nodes = []
        self.edges = []
        self.grid_nodes = {}          # grid name -> {(i, j): Node}
        self.classes = cfg["classes"]

    # ------------------------------------------------------------ helpers
    def node(self, pos, **kw):
        n = Node(len(self.nodes), pos, **kw)
        self.nodes.append(n)
        return n

    def edge(self, a, b, cls, kind="grid"):
        e = Edge(len(self.edges), a, b, cls, kind)
        a.ends.append((e, 0))
        b.ends.append((e, 1))
        self.edges.append(e)
        return e

    def kill(self, e):
        e.alive = False
        e.a.ends = [(x, k) for x, k in e.a.ends if x is not e]
        e.b.ends = [(x, k) for x, k in e.b.ends if x is not e]

    def alive_edges(self):
        return [e for e in self.edges if e.alive]

    def alive_nodes(self):
        return [n for n in self.nodes if n.ends]

    def height(self, x, y):
        return float(self.hf.sample(np.array([x]), np.array([y]))[0])

    def island_d(self, name, x, y):
        isl = next(i for i in self.cfg["islands"] if i["name"] == name)
        return TR.island_shape(isl, np.asarray(x, float), np.asarray(y, float), self.noise)

    # ------------------------------------------------------------ grids
    def build_grids(self, masks, noise):
        self.noise = noise
        warp_noise = TR.Perlin(self.cfg["seed"] + 7)
        for g in self.cfg["grids"]:
            rot = math.radians(g["rotation"])
            ux, uy = Vector((math.cos(rot), math.sin(rot))), Vector((-math.sin(rot), math.cos(rot)))
            o = v2(g["origin"])
            sx, sy = g["spacing"]
            (x0, y0), (x1, y1) = g["extent"]
            R = int(math.ceil(max(x1 - x0, y1 - y0) / min(sx, sy))) + 2
            pts = {}
            for i in range(-R, R + 1):
                for j in range(-R, R + 1):
                    p = o + ux * (i * sx) + uy * (j * sy)
                    if not (x0 <= p.x <= x1 and y0 <= p.y <= y1):
                        continue
                    if g.get("warp", 0):
                        w = g["warp"]
                        p = p + Vector((w * float(warp_noise(p.x / 300.0, p.y / 300.0)), w * float(warp_noise(p.x / 300.0 + 31.0, p.y / 300.0))))
                    if self.ok_site(g, p, masks):
                        pts[(i, j)] = p
            nodes = {k: self.node(p, grid=g["name"]) for k, p in pts.items()}
            ae = g.get("avenue_every", [99, 99])
            ap = g.get("avenue_phase", [0, 0])
            for (i, j), n in nodes.items():
                for di, dj in ((1, 0), (0, 1)):
                    m = nodes.get((i + di, j + dj))
                    if m is None:
                        continue
                    if not self.ok_segment(g, n.pos, m.pos, masks):
                        continue
                    # an edge along x (di) lies on row j; along y on column i
                    line = j if di else i
                    every, phase = (ae[1], ap[1]) if di else (ae[0], ap[0])
                    cls = "avenue" if (line - phase) % every == 0 else "street"
                    self.edge(n, m, cls)
            self.grid_nodes[g["name"]] = nodes
            self.log(f"grid {g['name']}: {len(nodes)} nodes")
        # random drops (streets only), keeping every node reachable
        for g in self.cfg["grids"]:
            if not g.get("drop"):
                continue
            nodes = list(self.grid_nodes[g["name"]].values())
            es = sorted({e.id: e for n in nodes for e, _ in n.ends if e.cls == "street"}.values(), key=lambda e: e.id)
            self.rng.shuffle(es)
            for e in es[:int(len(es) * g["drop"])]:
                if e.a.degree() <= 2 or e.b.degree() <= 2:
                    continue
                self.kill(e)
                if not self.connected(e.a, e.b):
                    e.alive = True
                    e.a.ends.append((e, 0))
                    e.b.ends.append((e, 1))

    def ok_site(self, g, p, masks):
        d = float(self.island_d(g["island"], p.x, p.y))
        isl = next(i for i in self.cfg["islands"] if i["name"] == g["island"])
        r = min(isl["radius"])
        if d > 1.0 - g.get("coast_margin", 60) / r:
            return False
        h = self.height(p.x, p.y)
        if h < 1.0:
            return False
        if g.get("mountain_max") is not None:
            if self.mask_at(masks["mountain"], p) > g["mountain_max"]:
                return False
        return True

    def ok_segment(self, g, a, b, masks):
        L = (b - a).length
        for k in range(1, 8):
            p = a.lerp(b, k / 8)
            if not self.ok_site(g, p, masks):
                return False
        ms = g.get("max_slope")
        if ms:
            za, zb = self.height(a.x, a.y), self.height(b.x, b.y)
            if abs(za - zb) / L > ms * 1.6:
                return False
        return True

    def mask_at(self, m, p):
        hf = self.hf
        ix = int(round((p.x - hf.x0) / hf.cell))
        iy = int(round((p.y - hf.x0) / hf.cell))
        if 0 <= ix < m.shape[1] and 0 <= iy < m.shape[0]:
            return float(m[iy, ix])
        return 0.0

    def connected(self, a, b, limit=400):
        seen, todo = {a.id}, [a]
        while todo:
            n = todo.pop()
            if n is b:
                return True
            for e, _ in n.ends:
                m = e.other(n)
                if m.id not in seen:
                    seen.add(m.id)
                    todo.append(m)
            if len(seen) > limit:
                return True
        return False

    def prune(self):
        """Remove dead ends (degree 1) that are not reserved for links."""
        changed = True
        while changed:
            changed = False
            for n in self.nodes:
                if n.degree() == 1 and not n.reserved:
                    self.kill(n.ends[0][0])
                    changed = True

    # ------------------------------------------------------------ arms / links
    def arm_dirs(self, n):
        out = []
        for e, k in n.ends:
            out.append(self.arm_angle(e, k))
        return out

    def arm_angle(self, e, k):
        if getattr(e, "arm", None) and e.arm[k] is not None:
            return e.arm[k]
        n = e.a if k == 0 else e.b
        pts = [e.a.pos] + e.via + [e.b.pos]
        if k == 1:
            pts = pts[::-1]
        return ang(pts[1] - pts[0])

    def free_angle(self, n, want, sep=52.0, span=70.0):
        used = self.arm_dirs(n)
        best = None
        for k in range(-int(span), int(span) + 1, 2):
            a = (want + k) % 360
            if all(adiff(a, u) >= sep for u in used):
                if best is None or abs(k) < abs(best[1]):
                    best = (a, k)
        return None if best is None else best[0]

    def pick_end(self, spec, toward):
        """Grid node nearest spec['near'] with a free arm towards `toward`."""
        nodes = [n for n in self.grid_nodes[spec["grid"]].values() if n.ends or n.reserved]
        nodes.sort(key=lambda n: (n.pos - v2(spec["near"])).length)
        for n in nodes[:30]:
            want = ang(v2(toward) - n.pos)
            a = self.free_angle(n, want)
            if a is not None:
                return n, a
        raise RuntimeError(f"no free arm near {spec}")

    def build_links(self):
        for L in self.cfg["links"]:
            via = [v2(p) for p in L.get("via", [])]
            tgt_a = via[0] if via else v2(L["to"]["near"])
            tgt_b = via[-1] if via else v2(L["from"]["near"])
            na, aa = self.pick_end(L["from"], tgt_a)
            na.reserved = True
            nb, ab = self.pick_end(L["to"], tgt_b)
            nb.reserved = True
            e = self.edge(na, nb, L["class"], kind="link")
            e.arm = [aa, ab]
            e.via = via
            e.name = L["name"]
            e.link = L
            self.log(f"link {L['name']}: node {na.id} ({aa:.0f} deg) -> node {nb.id} ({ab:.0f} deg)")

    # ------------------------------------------------------------ mountain road
    def build_mountain(self):
        M = self.cfg.get("mountain_road")
        if not M:
            return
        summit_near = v2(M["summit_near"])
        # summit: highest point within 250 m of summit_near
        hf = self.hf
        X, Y = hf.coords()
        r = 260.0
        sel = (np.abs(X - summit_near.x) < r) & (np.abs(Y - summit_near.y) < r)
        k = np.argmax(np.where(sel, hf.H, -1e9))
        top = Vector((float(X.ravel()[k]), float(Y.ravel()[k])))
        start, aa = self.pick_end(M["from"], top)
        start.reserved = True
        a0 = start.pos + Vector((math.cos(math.radians(aa)), math.sin(math.radians(aa)))) * 60.0
        pts = self.astar_switchbacks(a0, top, M.get("grade", 0.085), M.get("cell_m", 10.0), aa)
        plaza = self.node(top, kind="plaza")
        plaza.reserved = True
        e = self.edge(start, plaza, "mountain", kind="mountain")
        # stop the road at the plaza rim: drop waypoints inside it
        R = M.get("plaza_radius", 24.0)
        pts = [p for p in pts if (p - top).length > R + 30.0]
        e.arm = [aa, ang(pts[-1] - top) if pts else ang(start.pos - top)]
        e.via = pts
        e.name = "summit_road"
        self.plaza_radius = R
        self.log(f"mountain road: {len(pts)} waypoints to the summit at {top.x:.0f},{top.y:.0f} ({self.height(top.x, top.y):.0f} m)")

    def astar_switchbacks(self, a, b, grade, cell, start_deg):
        """A* over (cell, heading) on the heightfield: 16 headings, at most
        45 degrees of turn per step (12 m radius), steps steeper than `grade`
        forbidden. Produces natural switchbacks on steep faces."""
        hf = self.hf
        x0, y0 = min(a.x, b.x) - 700, min(a.y, b.y) - 700
        x1, y1 = max(a.x, b.x) + 700, max(a.y, b.y) + 700
        nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
        xs, ys = x0 + np.arange(nx) * cell, y0 + np.arange(ny) * cell
        XX, YY = np.meshgrid(xs, ys)
        Hs = TR.blur(hf.sample(XX, YY), 30.0 / cell)          # the road averages the slope; cut / fill takes the rest
        sea = Hs < 2.0
        D = [(math.cos(2 * math.pi * k / 16), math.sin(2 * math.pi * k / 16)) for k in range(16)]
        steps = []
        for k, (dx, dy) in enumerate(D):
            # nearest lattice step in this heading (knight moves for odd headings)
            best = min(((i, j) for i in range(-2, 3) for j in range(-2, 3) if (i, j) != (0, 0)),
                       key=lambda q: math.atan2(q[1], q[0]) - math.atan2(dy, dx) if False else
                       abs(((math.atan2(q[1], q[0]) - math.atan2(dy, dx)) + math.pi) % (2 * math.pi) - math.pi) + 0.01 * math.hypot(*q))
            steps.append(best)
        si, sj = int(round((a.x - x0) / cell)), int(round((a.y - y0) / cell))
        gi, gj = int(round((b.x - x0) / cell)), int(round((b.y - y0) / cell))
        h0 = int(round(start_deg / 22.5)) % 16
        start = (si, sj, h0)
        g = {start: 0.0}
        prev = {}
        pq = [(0.0, start)]
        goal = None
        it = 0
        while pq:
            f, st = heapq.heappop(pq)
            i, j, h = st
            if math.hypot(i - gi, j - gj) * cell < 40.0:
                goal = st
                break
            it += 1
            if it > 2500000:
                break
            gc = g[st]
            for dh in (-2, -1, 0, 1, 2):
                h2 = (h + dh) % 16
                di, dj = steps[h2]
                i2, j2 = i + di, j + dj
                if not (0 <= i2 < nx and 0 <= j2 < ny) or sea[j2, i2]:
                    continue
                ln = math.hypot(di, dj) * cell
                dz = Hs[j2, i2] - Hs[j, i]
                gr = abs(dz) / ln
                # near the summit the slope may be steeper: the lookout pad is cut there
                near = max(0.0, 1.0 - math.hypot(i2 - gi, j2 - gj) * cell / 160.0)
                lim = max(0.6, grade * (2.2 + 2.0 * near))      # steeper only at a heavy cost (cut / fill)
                if gr > lim:
                    continue
                c = gc + ln * (1.0 + 0.6 * abs(dh) / 2) + 30.0 * ln * max(0.0, gr - grade) / grade + (8.0 if dz < 0 else 0.0)
                st2 = (i2, j2, h2)
                if c < g.get(st2, 1e18):
                    g[st2] = c
                    prev[st2] = st
                    # heuristic: climbing at `grade` needs at least dz / grade metres
                    hz = (Hs[gj, gi] - Hs[j2, i2]) / grade
                    heapq.heappush(pq, (c + max(math.hypot(i2 - gi, j2 - gj) * cell, hz), st2))
        if goal is None:
            self.log(f"mountain road: A* found no path within the grade ({it} expansions), using a straight line")
            return [a, b]
        out = []
        st = goal
        while st in prev:
            out.append(Vector((x0 + st[0] * cell, y0 + st[1] * cell)))
            st = prev[st]
        out.append(a)
        out.reverse()
        # thin to every other node and smooth (Chaikin) so the spline stays calm
        P = out[::2] + ([out[-1]] if len(out) % 2 == 0 else [])
        for _ in range(2):
            Q = [P[0]]
            for p, q in zip(P, P[1:]):
                Q += [p.lerp(q, 0.25), p.lerp(q, 0.75)]
            Q.append(P[-1])
            P = Q
        self.log(f"mountain road: A* {it} expansions, {len(out)} cells")
        return P[::2]

    # ------------------------------------------------------------ simplify
    def merge_straight(self):
        """Degree-2 grid nodes whose arms are ~180 deg apart are not junctions:
        merge their two edges into one run through the node."""
        for n in self.nodes:
            if n.degree() != 2 or n.reserved or n.kind != "junction":
                continue
            (e1, k1), (e2, k2) = n.ends
            if e1 is e2 or e1.kind != "grid" or e2.kind != "grid" or e1.cls != e2.cls:
                continue
            a1, a2 = self.arm_angle(e1, k1), self.arm_angle(e2, k2)
            if adiff(a1, a2) < 160:
                continue
            p = e1.other(n)
            q = e2.other(n)
            if p is q:
                continue
            pts1 = [e1.a.pos] + e1.via + [e1.b.pos]
            if k1 == 0:
                pts1 = pts1[::-1]         # p ... n
            pts2 = [e2.a.pos] + e2.via + [e2.b.pos]
            if k2 == 1:
                pts2 = pts2[::-1]         # n ... q
            arm_p = self.arm_angle(e1, 1 - k1)
            arm_q = self.arm_angle(e2, 1 - k2)
            self.kill(e1)
            self.kill(e2)
            e = self.edge(p, q, e1.cls)
            e.via = pts1[1:-1] + [n.pos] + pts2[1:-1]
            e.arm = [arm_p, arm_q]

    # ------------------------------------------------------------ junction geometry
    def make_junctions(self):
        T = self.T
        for n in self.alive_nodes():
            if n.kind == "plaza":
                n.J = Plaza(n, self, self.plaza_radius)
                continue
            if n.kind == "transition":
                continue
            arms = []
            halves = []
            for e, k in n.ends:
                arms.append(self.arm_angle(e, k))
                halves.append(self.classes[self.end_class(e, k)]["half"])
            wide = max(halves) > 6
            n.J = T["Junction"](f"J{n.id}", (n.pos.x, n.pos.y), n.z, arms, r_concave=9.0 if wide else 7.0,
                                r_convex=4.0, halves=halves, min_arm=12.0)
            n.arm_of = {(e.id, k): i for i, (e, k) in enumerate(n.ends)}

    def end_class(self, e, k):
        """Class of the road where edge e meets its node at end k (links start urban)."""
        if e.cls == "highway":
            return "highway_urban"
        if e.cls == "mountain":
            return "street"
        return e.cls

    # ------------------------------------------------------------ paths + profiles
    def build_paths(self):
        T = self.T
        for e in self.alive_edges():
            A, B = self.arm_point(e, 0), self.arm_point(e, 1)
            da, db = self.arm_vec(e, 0), self.arm_vec(e, 1)
            lead = 12.0 if e.kind == "grid" else 40.0
            ctrl = [A, A + da * lead] + list(e.via) + [B + db * lead, B]
            # drop waypoints that would fold back inside the lead-ins
            clean = [ctrl[0], ctrl[1]]
            for p in ctrl[2:-2]:
                if (p - clean[-1]).length > 8.0 and (p - ctrl[-2]).length > 8.0:
                    clean.append(p)
            clean += ctrl[-2:]
            e.pts2d = T["catmull"](clean)

    def arm_vec(self, e, k):
        a = math.radians(self.arm_angle(e, k))
        return Vector((math.cos(a), math.sin(a)))

    def arm_point(self, e, k):
        n = e.a if k == 0 else e.b
        if n.J is None:
            return n.pos.copy()
        i = n.arm_of[(e.id, k)] if hasattr(n, "arm_of") else 0
        return n.pos + n.J.dirs[i] * n.J.L[i]

    def junction_heights(self):
        """Junction levels from the (flattened) terrain, relaxed so every edge
        between two junctions can keep its grade limit."""
        for n in self.alive_nodes():
            xs = n.pos.x + np.array([0, 15, -15, 0, 0])
            ys = n.pos.y + np.array([0, 0, 0, 15, -15])
            n.z = float(np.mean(self.hf.sample(xs, ys)))
            if n.kind == "plaza":
                n.z = float(np.max(self.hf.sample(xs, ys)))
        gm = self.cfg["grade_max"]
        for _ in range(60):
            moved = 0
            for e in self.alive_edges():
                if e.kind != "grid":
                    continue
                L = max(1.0, (e.b.pos - e.a.pos).length - 30.0)
                lim = gm[e.cls] * 0.8 * L
                d = e.b.z - e.a.z
                if abs(d) > lim:
                    ex = (abs(d) - lim) / 2 * math.copysign(1, d)
                    e.a.z += ex * (0 if e.a.reserved else 1)
                    e.b.z -= ex * (0 if e.b.reserved else 1)
                    moved += 1
            if not moved:
                break

    def solve_profiles(self, extra_req=None):
        """Heights along every edge: follow the terrain where possible,
        Lipschitz-limited to the class grade (eased to flat at junctions),
        above every clearance requirement (water, roads crossed)."""
        T = self.T
        gm = self.cfg["grade_max"]
        infeasible = []
        for e in self.alive_edges():
            pts = e.pts2d
            seg = np.array([0.0] + [(q - p).length for p, q in zip(pts, pts[1:])])
            s = np.cumsum(seg)
            Ls = s[-1]
            xs = np.array([p.x for p in pts])
            ys = np.array([p.y for p in pts])
            t = self.hf.sample(xs, ys)
            g = np.full(len(s), gm["bridge"] if e.link and e.link.get("bridge") else gm[e.cls])
            if e.kind == "mountain":
                g[:] = gm["mountain"]
            ease = 16.0
            g = g * np.clip(np.minimum(s, Ls - s) / ease, 0.12, 1.0)
            if e.b.kind == "plaza":
                g = gm["mountain"] * np.clip(s / ease, 0.12, 1.0)
            req = np.full(len(s), -1e9)
            # water: deck clearance (navigation channel in the middle of each crossing)
            wet = t < 0.5
            if wet.any() and e.link:
                clr = e.link.get("clearance", 10.0)
                idx = np.nonzero(wet)[0]
                runs = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1)
                for r in runs:
                    s0, s1 = s[r[0]], s[r[-1]]
                    req[r] = np.maximum(req[r], 6.0)
                    mid = (s >= s0 + (s1 - s0) * 0.38) & (s <= s0 + (s1 - s0) * 0.62)
                    req[mid] = np.maximum(req[mid], clr)
            elif wet.any():
                req[wet] = np.maximum(req[wet], 3.0)
            for s0, s1, z in (extra_req or {}).get(e.id, []):
                m = (s >= s0) & (s <= s1)
                req[m] = np.maximum(req[m], z)
            za, zb = e.a.z, e.b.z
            z = lipschitz_fit(s, t, req, g, za, zb)
            bad = np.max(req - z)
            if bad > 0.3:
                infeasible.append((e, float(bad)))
            e.s = s
            e.z = z
            e.path = T["Path"](pts, z)
            e.grade = float(np.max(np.abs(np.diff(z)) / np.maximum(np.diff(s), 1e-6))) if len(s) > 1 else 0.0
        return infeasible

    # ------------------------------------------------------------ crossings (expressway over the grid)
    def crossings(self):
        """2D crossings between elevated links and other edges. Returns
        {edge id: [(s0, s1, z_required)]} for the links."""
        req = {}
        conflicts = []
        ups = [e for e in self.alive_edges() if e.link and e.link.get("elevated")]
        for u in ups:
            P = np.array([(p.x, p.y) for p in u.pts2d])
            for e in self.alive_edges():
                if e is u or e.a in (u.a, u.b) or e.b in (u.a, u.b):
                    continue
                Q = np.array([(p.x, p.y) for p in e.pts2d])
                hit = seg_intersections(P, Q)
                for (i, ti, j, tj) in hit:
                    su = u.s[i] + ti * (u.s[i + 1] - u.s[i])
                    se = e.s[j] + tj * (e.s[j + 1] - e.s[j])
                    ze = float(np.interp(se, e.s, e.z))
                    du = P[i + 1] - P[i]
                    de = Q[j + 1] - Q[j]
                    sin = abs(du[0] * de[1] - du[1] * de[0]) / max(1e-9, np.linalg.norm(du) * np.linalg.norm(de))
                    half = self.classes[e.cls]["half"] + 3.0 + self.classes[u.cls]["half"] * 0.5
                    w = half / max(sin, 0.3) + 6.0
                    req.setdefault(u.id, []).append((su - w, su + w, ze + u.link.get("clearance", 7.5)))
                    conflicts.append((u, e, su))
            # junctions under the deck
            for n in self.alive_nodes():
                if n in (u.a, u.b) or n.J is None:
                    continue
                d = np.hypot(P[:, 0] - n.pos.x, P[:, 1] - n.pos.y)
                k = int(np.argmin(d))
                if d[k] < max(n.J.L) + self.classes[u.cls]["half"] + 4:
                    w = max(n.J.L) + 10
                    req.setdefault(u.id, []).append((u.s[k] - w, u.s[k] + w, n.z + u.link.get("clearance", 7.5)))
                    conflicts.append((u, n, u.s[k]))
        return req, conflicts

    # ------------------------------------------------------------ transitions (urban <-> highway / mountain)
    def split_transitions(self):
        """Links and the mountain road start as a curbed urban road at their
        junctions and change to the barrier profile after `lead` metres. Split
        those edges at transition nodes (same carriageway width both sides)."""
        T = self.T
        for e in list(self.alive_edges()):
            if e.cls not in ("highway", "mountain"):
                continue
            urban = "highway_urban" if e.cls == "highway" else "street"
            lead = 45.0 if e.cls == "highway" else 35.0
            cuts = []
            if e.a.kind == "junction":
                cuts.append(lead)
            if e.b.kind == "junction" and e.cls == "highway":
                cuts.append(e.path.length - lead)
            if not cuts or e.path.length < 3 * lead:
                continue
            pieces = split_path(T, e.pts2d, e.z, cuts)
            prev_node = e.a
            segs = []
            for k, (pts, z, s) in enumerate(pieces):
                last = k == len(pieces) - 1
                nxt = e.b if last else self.node(pts[-1], kind="transition")
                if not last:
                    nxt.z = float(z[-1])
                cls = e.cls
                if (k == 0 and e.a.kind == "junction") or (last and e.b.kind == "junction" and e.cls == "highway"):
                    cls = urban
                f = Edge(len(self.edges), prev_node, nxt, cls, e.kind)
                self.edges.append(f)
                f.name, f.link = e.name, e.link
                f.pts2d, f.z, f.s = pts, z, s
                f.path = T["Path"](pts, z)
                f.grade = e.grade
                segs.append(f)
                prev_node = nxt
            # rewire ends
            for (node, k, f) in ((e.a, 0, segs[0]), (e.b, 1, segs[-1])):
                node.ends = [(f, k) if x is e else (x, kk) for x, kk in node.ends]
                if hasattr(node, "arm_of") and (e.id, k) in node.arm_of:
                    node.arm_of[(f.id, k)] = node.arm_of.pop((e.id, k))
            for f, g_ in zip(segs, segs[1:]):
                f.b.ends = [(f, 1), (g_, 0)]
            e.alive = False
            e.split_into = segs


def split_path(T, pts, z, cuts):
    """Split a sampled polyline (pts, z) at arc lengths `cuts`."""
    seg = np.array([0.0] + [(q - p).length for p, q in zip(pts, pts[1:])])
    s = np.cumsum(seg)
    out = []
    bounds = [0.0] + sorted(c for c in cuts if 0 < c < s[-1]) + [s[-1]]
    for a, b in zip(bounds, bounds[1:]):
        m = (s > a) & (s < b)
        idx = np.nonzero(m)[0]
        P, Z = [], []
        for c in (a,):
            i = int(np.clip(np.searchsorted(s, c) - 1, 0, len(s) - 2))
            f = (c - s[i]) / max(1e-9, s[i + 1] - s[i])
            P.append(pts[i].lerp(pts[i + 1], f))
            Z.append(z[i] * (1 - f) + z[i + 1] * f)
        for i in idx:
            if (pts[i] - P[-1]).length > 0.05:
                P.append(pts[i].copy())
                Z.append(z[i])
        i = int(np.clip(np.searchsorted(s, b) - 1, 0, len(s) - 2))
        f = (b - s[i]) / max(1e-9, s[i + 1] - s[i])
        q = pts[i].lerp(pts[i + 1], f)
        if (q - P[-1]).length > 0.05:
            P.append(q)
            Z.append(z[i] * (1 - f) + z[i + 1] * f)
        else:
            P[-1] = q
        S = np.cumsum([0.0] + [(q2 - p2).length for p2, q2 in zip(P, P[1:])])
        out.append((P, np.array(Z), S))
    return out


def seg_intersections(P, Q):
    """Crossings of polylines P and Q (arrays (n, 2)): [(i, ti, j, tj)]."""
    out = []
    # coarse bbox reject per 16-sample block
    B = 16
    for i0 in range(0, len(P) - 1, B):
        pa = P[i0:i0 + B + 1]
        pmin, pmax = pa.min(0) - 1, pa.max(0) + 1
        for j0 in range(0, len(Q) - 1, B):
            qa = Q[j0:j0 + B + 1]
            if (qa.max(0) < pmin).any() or (qa.min(0) > pmax).any():
                continue
            for i in range(i0, min(i0 + B, len(P) - 1)):
                a, b = P[i], P[i + 1]
                for j in range(j0, min(j0 + B, len(Q) - 1)):
                    c, d = Q[j], Q[j + 1]
                    r, sv = b - a, d - c
                    den = r[0] * sv[1] - r[1] * sv[0]
                    if abs(den) < 1e-12:
                        continue
                    t = ((c[0] - a[0]) * sv[1] - (c[1] - a[1]) * sv[0]) / den
                    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
                    if 0 <= t < 1 and 0 <= u < 1:
                        out.append((i, t, j, u))
    return out


def lipschitz_fit(s, t, req, g, za, zb, smooth_m=18.0):
    """Closest curve to the target t with slope <= g(s), z(0) = za,
    z(end) = zb and z >= req where possible. Built from Lipschitz envelopes
    (forward / backward passes), so it is O(n) and exact in the limit."""
    n = len(s)
    ds = np.diff(s)
    gs = (g[:-1] + g[1:]) / 2

    def env_up(v):          # largest g-Lipschitz function <= v
        u = v.copy()
        for i in range(1, n):
            u[i] = min(u[i], u[i - 1] + gs[i - 1] * ds[i - 1])
        for i in range(n - 2, -1, -1):
            u[i] = min(u[i], u[i + 1] + gs[i] * ds[i])
        return u

    def env_lo(v):          # smallest g-Lipschitz function >= v
        return -env_up(-v)
    # bounds: end cones and requirements
    ends = np.full(n, np.inf)
    ends[0], ends[-1] = za, zb
    upper = env_up(np.where(np.isfinite(ends), ends, 1e9))
    e2 = np.full(n, -1e9)
    e2[0], e2[-1] = za, zb
    lower = env_lo(np.maximum(e2, req))
    lower = np.minimum(lower, upper)          # infeasible requirement: the ends win
    z = (env_up(t) + env_lo(t)) / 2
    z = np.minimum(np.maximum(z, lower), upper)
    if smooth_m > 0 and n > 5:
        step = max(1e-3, float(np.median(ds)))
        k = TR.blur(z[None, :], smooth_m / step)[0] if n > 2 * smooth_m / step else z
        z = np.minimum(np.maximum(k, lower), upper)
    return z


class Plaza:
    """Summit lookout: a round asphalt plaza with one road arm, same
    interface as blender_town.Junction (pos, z, dirs, L, half, corners,
    corner_line) so town_roads.build_junction() builds it."""

    def __init__(self, node, net, R):
        e, k = node.ends[0]
        a = net.arm_angle(e, k)
        self.name = f"Lookout{node.id}"
        self.pos = node.pos.copy()
        self.z = node.z
        self.arms = [a]
        self.dirs = [Vector((math.cos(math.radians(a)), math.sin(math.radians(a))))]
        self.R = R
        self.half = [net.classes["street"]["half"]]
        self.L = [R + 8.0]
        self.corners = [{"ia": 0, "ib": 0, "theta": 360.0}]
        node.arm_of = {(e.id, k): 0}

    def corner_line(self, c, d):
        a = self.dirs[0]
        nrm = Vector((-a.y, a.x))
        h = self.half[0] + d
        r = self.R + d
        A = a * self.L[0] + nrm * h            # left side of the arm mouth
        B = a * self.L[0] - nrm * h
        # join the circle where it meets the arm's side lines
        phi = math.asin(min(0.95, h / r))
        a0 = math.atan2(a.y, a.x)
        out = [A]
        sweep = 2 * math.pi - 2 * phi
        m = 48
        for i in range(m + 1):
            th = a0 + phi + sweep * i / m
            out.append(Vector((math.cos(th), math.sin(th))) * r)
        out.append(B)
        return out
