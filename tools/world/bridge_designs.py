"""The four landmark bridges and the small decks as engineered structures (Blender 5.2).

Geometry follows world.json: the deck runs on the road centreline between the bridge's s range
(road profile and grades unchanged, the drivable surface is still the road run), piers stand at
their world.json positions, pylon tops at their world.json heights. What is new is everything a
real bridge has under and around that line. Designs (see docs/agents/bridges/NOTES.md):

    port        Minato Bay Bridge (cable_stayed): concrete H pylons with three cross beams and
                anchorage zones, 112 semi-harp stays in HDPE, a 4-5 m steel Warren truss deck
                with floor beams, stringers, lateral bracing, a centre inspection catwalk,
                portal approach piers. One pylon is under repair: scaffold with Hoshikawa
                hoardings and a tower crane on its pile cap.
    expressway  Shinkai Expressway (viaduct): brutalist board-formed concrete, a single-cell box
                girder with long curved cantilever wings on sculpted "tulip" hammerhead piers,
                bearings, drains, curved-top noise barriers, expansion joints every 4 spans.
    kagero      Kagero Viaduct (girder): weathering-steel plate girders, haunched over battered
                twin-column concrete portal piers, cross frames, stiffeners, an under-deck
                maintenance gantry.
    tenjin      Tenjin Arch (arch): white steel basket-handle network arch (ribs leaning in to
                a crown with the Hoshikawa plaque), inclined crossing hangers, a box tie girder,
                floor beams; slender concrete approach spans on oval columns.
    small       every other deck: concrete box girder on single tulip piers.

`option` picks one of the alternatives drawn in docs/agents/bridges/design_options.png (the
options driver builds them in clay); the default is the chosen design.
"""
import math

import numpy as np
from mathutils import Vector

import bridge_kit as K
from bridge_kit import BM, Rail, UP, chamfer_rect, frame_at, smoothstep, station_of, superellipse

ROAD_Z = 0.2
SEA = 0.0

DESIGNS = {"bay_expressway": "port", "city_expressway": "expressway", "kagero_viaduct": "kagero", "tenjin_arch": "tenjin"}
OPTIONS = {
    "port": ["H_truss", "invY_box", "A_fan"],
    "expressway": ["tulip", "portal", "split_V"],
    "kagero": ["haunched", "through_truss", "deck_arch"],
    "tenjin": ["basket", "twin_ribs", "single_lean"],
}
CHOSEN = {k: v[0] for k, v in OPTIONS.items()}


def design_of(br):
    return next((v for k, v in DESIGNS.items() if br["name"].startswith(k)), "small")


def edge_of(cls):
    side = cls.get("side", "curb")
    H = cls["half"]
    return H + 0.5 if side == "jersey" else H + 3.0 if side == "curb" else H + 1.1


class Ctx:
    """What a builder needs: the collection, materials, the heightfield sampler, bookkeeping."""

    def __init__(self, coll, M, ground, built, root, option=None, lights=True):
        self.c = coll
        self.M = M
        self.ground = ground
        self.built = built
        self.root = root
        self.option = option
        self.lights = lights

    def gfloor(self, p):
        return max(float(self.ground(p.x, p.y)), SEA)

    def emit(self, name, bm, kind="bridges"):
        if bm.nf == 0:
            bm.bm.free()
            return None
        me = bm.finish(name, self.M)
        o = K.put(self.c, name, me, self.built, kind)
        if name.startswith("BridgeWash_"):
            o.visible_shadow = False
        return o

    def pier(self, x, y, bottom, top, **kw):
        d = {"pos": [round(x, 2), round(y, 2)], "bottom": bottom, "top": top}
        d.update(kw)
        self.built.setdefault("piers", []).append(d)

    def light(self, name, pos, color, energy, kind="POINT", direction=None, spot=None):
        if not self.lights:
            return
        import bpy
        li = bpy.data.lights.new(name, kind)
        li.color = color
        li.energy = energy
        if kind == "SPOT":
            li.spot_size = spot or math.radians(40)
            li.spot_blend = 0.8
        li.shadow_soft_size = 0.3
        o = bpy.data.objects.new(name, li)
        o.location = pos
        if direction is not None:
            o.rotation_euler = Vector(direction).to_track_quat("-Z", "Y").to_euler()
        self.c.objects.link(o)
        self.built["lights"] = self.built.get("lights", 0) + 1


# ---------------------------------------------------------------- shared parts
def deck_range(br, path):
    s0, s1 = br["s"]
    return max(0.0, s0 - 6.0), min(path.length, s1 + 6.0)


def pier_frames(br, path, s0, s1):
    """Each world.json pier with its station on this road (piers beyond the road's ends, under a
    junction mouth, keep their own position and direction)."""
    out = []
    for p in br["piers"]:
        s, d = station_of(path, p["pos"])
        P, t, n = frame_at(path, min(max(s, s0), s1))
        if d > 4.0:
            t = Vector((p["dir"][0], p["dir"][1], 0)).normalized()
            n = Vector((-t.y, t.x, 0))
            P = Vector((p["pos"][0], p["pos"][1], p["top"] + br.get("depth", 2.4) + 0.2))
        else:
            P = Vector((P.x, P.y, P.z))
        out.append({"s": s, "off": d, "P": P, "t": t, "n": n, "data": p})
    return out


def smooth_min(arr, win):
    """Moving minimum then moving average (no steps in a depth profile)."""
    a = np.asarray(arr, dtype=float)
    n = len(a)
    m = np.array([a[max(0, i - win):i + win + 1].min() for i in range(n)])
    k = np.ones(2 * win + 1) / (2 * win + 1)
    pad = np.pad(m, win, mode="edge")
    return np.convolve(pad, k, mode="valid")[:n]


def clamp_depth(ctx, rail, want, width, margin=0.8, top=0.3, dmin=1.2):
    """Depth per station, clipped so the structure stays `margin` above the ground / water."""
    d = np.array(want, dtype=float)
    for i in range(rail.n):
        g = max(ctx.gfloor(rail.P(i, y, 0)) for y in (-width, 0.0, width))
        d[i] = min(d[i], rail.pos[i][2] - top - g - margin)
    d = np.maximum(d, dmin)
    return smooth_min(d, 3)


def barrier_railing(b, rail, cls, key="steel_grey", step=2.5):
    """Steel railing on the jersey barrier tops / along the sidewalk edge."""
    side = cls.get("side", "curb")
    H = cls["half"]
    if side == "jersey":
        y, z0 = H + 0.38, ROAD_Z + 0.9
        heights = (0.22, 0.42)
    elif side == "curb":
        y, z0 = H + 2.92, 0.35
        heights = (0.55, 1.1)
    else:
        return
    for sg in (-1, 1):
        for h in heights:
            b.sweep(rail, [(sg * y - 0.035, z0 + h - 0.03), (sg * y + 0.035, z0 + h - 0.03), (sg * y + 0.035, z0 + h + 0.03), (sg * y - 0.035, z0 + h + 0.03)],
                    key, closed=True)
        acc = 0.0
        for i in range(rail.n - 1):
            acc += rail.s[i + 1] - rail.s[i]
            if acc >= step:
                acc = 0.0
                P, t, n = rail.frame(i)
                c = P + n * (sg * y) + UP * (z0 + heights[-1] / 2 + 0.02)
                b.box(c, t, n, UP, (0.08, 0.08, heights[-1] + 0.06), key)


def catwalk(b, rail, y, zfn, width=1.0, i0=0, i1=None, key="grating", rail_key="steel_grey"):
    """Inspection walkway (grating, two handrails, posts every ~3 m) at height zfn(i)."""
    i1 = rail.n - 1 if i1 is None else i1
    w = width / 2
    b.sweep_var(rail, lambda i: [(y - w, zfn(i) - 0.06), (y + w, zfn(i) - 0.06), (y + w, zfn(i)), (y - w, zfn(i))], key, i0, i1)
    for sg in (-1, 1):
        yy = y + sg * (w - 0.03)
        b.sweep_var(rail, lambda i, yy=yy: [(yy - 0.025, zfn(i) + 1.05), (yy + 0.025, zfn(i) + 1.05), (yy + 0.025, zfn(i) + 1.1), (yy - 0.025, zfn(i) + 1.1)],
                    rail_key, i0, i1)
        for i in range(i0, i1 + 1, 2):
            P, t, n = rail.frame(i)
            b.box(P + n * yy + UP * (zfn(i) + 0.55), t, n, UP, (0.05, 0.05, 1.1), rail_key)


def caged_ladder(b, base, top, face_n, side_t, key="steel_grey"):
    """Service ladder with a safety cage from base to top (z), standing off a face."""
    base, top = Vector(base), Vector(top)
    h = top.z - base.z
    if h < 1.0:
        return
    for sg in (-1, 1):
        b.tube(base + side_t * (0.22 * sg), top + side_t * (0.22 * sg), 0.025, key, seg=6, smooth=False)
    n = int(h / 0.3)
    for k in range(1, n):
        z = base.z + k * 0.3
        c = Vector((base.x, base.y, z))
        b.tube(c - side_t * 0.22, c + side_t * 0.22, 0.016, key, seg=4, smooth=False)
    for k in range(int(2.4 / 0.9) + 1, int(h / 0.9)):
        z = base.z + k * 0.9
        c = Vector((base.x, base.y, z)) + face_n * 0.45
        pts = [c + side_t * (0.4 * math.cos(a)) + face_n * (0.4 * math.sin(a)) for a in np.linspace(0, math.pi, 7)]
        for p0, p1 in zip(pts, pts[1:]):
            b.tube(p0, p1, 0.015, key, seg=4, smooth=False)
    for a in np.linspace(0.15, math.pi - 0.15, 4):
        off = side_t * (0.4 * math.cos(a)) + face_n * (0.45 + 0.4 * math.sin(a))
        b.tube(base + off + UP * 2.4, top + off, 0.014, key, seg=4, smooth=False)


def sign_board(b, c, normal, w, h, key):
    """A sign plate facing `normal`, image upright."""
    n = Vector(normal).normalized()
    u = UP.cross(n).normalized()
    if u.length < 1e-6:
        u = Vector((1, 0, 0))
    c = Vector(c)
    pts = [c - u * (w / 2) - UP * (h / 2), c + u * (w / 2) - UP * (h / 2), c + u * (w / 2) + UP * (h / 2), c - u * (w / 2) + UP * (h / 2)]
    b.face(pts, key, [(0, 0), (1, 0), (1, 1), (0, 1)], n)
    b.face([p - n * 0.04 for p in pts[::-1]], "steel_grey", [(0, 0), (w, 0), (w, h), (0, h)], -n)


def wash(b, a, c, half_w, normal, key="wash_warm"):
    """Uplight wash card from a (bottom, full light) to c (top), facing `normal`."""
    a, c = Vector(a), Vector(c)
    n = Vector(normal).normalized()
    u = (c - a).cross(n).normalized() * half_w
    pts = [a - u, a + u, c + u, c - u]
    b.face(pts, key, [(0, 0), (1, 0), (1, 1), (0, 1)], n)


def expansion_joint(b, rail, i, half, key="grating"):
    P, t, n = rail.frame(i)
    b.box(P + UP * (ROAD_Z + 0.006), t, n, UP, (0.5, 2 * half, 0.012), key, faces=("+z", "+x", "-x"))


# ---------------------------------------------------------------- concrete box girder (expressway, approaches, small decks)
def box_section(E, D, web=None, wing=True):
    """Single-cell box with curved cantilever wings: a closed (y, z) section from the path level."""
    web = web if web is not None else min(5.2, E * 0.45)
    bot = max(1.2, web - 1.4)
    tip = 0.75 if E > 8 else 0.55
    right = [(E, 0.05), (E, -tip)]
    if wing:
        # curved soffit from the fascia to the web top: the brutalist sweep
        for k in range(1, 7):
            f = k / 6
            y = (E - 0.3) + (web - (E - 0.3)) * f
            z = -tip + 0.05 - (min(1.25, D * 0.5) - tip + 0.05) * (f ** 1.8)
            right.append((y, z))
    right.append((bot, -D))
    up_right = right[::-1]                       # bottom -> top on the right
    down_left = [(-y, z) for y, z in right]      # top -> bottom on the left
    return up_right + down_left


def concrete_girder(ctx, b, rail, E, D, key="concrete"):
    prof = box_section(E, D)
    b.sweep(rail, prof, key, closed=True)
    return prof


def tulip_pier(ctx, b, pf, top_z, bottom, ay_top, ax=1.4, ay=2.0, key="concrete", flare=0.5, n=3.6, wash_key="wash_warm"):
    """Sculpted single column flaring into a hammerhead under the girder."""
    P, t, nn = pf["P"], pf["t"], pf["n"]
    h = top_z - bottom
    rings = []
    levels = [0.0, 0.2, 0.4, 0.55, 0.65, 0.74, 0.82, 0.89, 0.95, 1.0]
    for f in levels:
        z = bottom + h * f
        fl = smoothstep(1.0 - flare, 1.0, f) ** 1.5
        a_y = ay + (ay_top - ay) * fl
        a_x = ax + 0.3 * fl
        rings.append(superellipse(P.x, P.y, z, a_x, a_y, t, nn, n=n, seg=24))
    b.loft(rings, key, cap_top=True)
    return P


def bearings(b, P, t, n, z, ys, size=0.9):
    for y in ys:
        c = P + n * y
        b.box(c + UP * (z + 0.06), t, n, UP, (size + 0.25, size + 0.25, 0.12), "concrete")
        b.box(c + UP * (z + 0.17), t, n, UP, (size, size, 0.1), "rubber")
        b.box(c + UP * (z + 0.24), t, n, UP, (size + 0.1, size + 0.1, 0.04), "steel_grey")


def noise_barrier(b, rail, y, i0, i1, post_step=4.0):
    """Curved-top noise barrier on the girder edge: steel posts, solid lower panels, tinted upper
    panels curving in over the carriageway."""
    for sg in (-1, 1):
        yy = sg * y
        b.sweep(rail, [(yy - 0.05, -0.6), (yy + 0.05, -0.6), (yy + 0.05, 2.4), (yy - 0.05, 2.4)], "steel_grey", i0, i1, closed=True)
        outer = [(yy, 2.4)] + [(yy - sg * (1.0 - math.cos(a)), 3.0 + math.sin(a)) for a in np.linspace(0, math.pi / 2, 7)]
        inner = [(py - sg * 0.06 * (1.0 if k < 2 else math.cos(math.pi / 2 * (k - 1) / 6)), pz - 0.06 * (0.0 if k < 2 else math.sin(math.pi / 2 * (k - 1) / 6)))
                 for k, (py, pz) in enumerate(outer)]
        b.sweep(rail, outer + inner[::-1], "glass", i0, i1, closed=True)
        acc = 0.0
        for i in range(i0, i1):
            acc += rail.s[i + 1] - rail.s[i]
            if acc >= post_step:
                acc = 0.0
                P, t, n = rail.frame(i)
                b.box(P + n * (yy + sg * 0.12) + UP * 1.45, t, n, UP, (0.22, 0.18, 4.1), "steel_grey")
                b.beam(P + n * (yy + sg * 0.12) + UP * 3.4, P + n * (yy - sg * 0.85) + UP * 4.0, 0.12, 0.12, "steel_grey")


def drain_pipe(b, rail, y, z, i0, i1, r=0.14):
    oct_ = [(y + r * math.cos(a), z + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    b.sweep(rail, oct_, "steel_grey", i0, i1, closed=True)


# ---------------------------------------------------------------- expressway (viaduct)
def expressway(ctx, br, path, cls, option="tulip"):
    s0, s1 = deck_range(br, path)
    rail = Rail(path, s0, s1, 3.0)
    E = cls["half"] + 0.9            # 11.9: wing tip outboard of the jersey (noise barrier on the edge)
    D = br.get("depth", 2.4)
    name = br["name"]
    g = BM(list(ctx.M))
    concrete_girder(ctx, g, rail, E, D)
    ctx.emit(f"Girder_{name}", g)
    det = BM(list(ctx.M))
    barrier_railing(det, rail, cls)
    i_nb0 = min(rail.n - 2, int(30 / 3.0))
    i_nb1 = max(i_nb0 + 1, rail.n - 1 - int(30 / 3.0))
    noise_barrier(det, rail, E - 0.1, i_nb0, i_nb1)
    drain_pipe(det, rail, 6.9, -0.95, 0, rail.n - 1)
    pb = BM(list(ctx.M))
    wb = BM(list(ctx.M))
    pfs = pier_frames(br, path, s0, s1)
    for k, pf in enumerate(pfs):
        p = pf["data"]
        top_z = pf["P"].z - D - 0.32
        bottom = p["bottom"]
        P, t, n = pf["P"], pf["t"], pf["n"]
        if option == "tulip":
            tulip_pier(ctx, pb, pf, top_z, bottom, 4.4)
            ctx.pier(P.x, P.y, bottom, top_z)
        elif option == "portal":
            for sg in (-1, 1):
                c = P + n * (sg * 4.6)
                rings = [chamfer_rect(Vector((c.x, c.y, z)), t, n, 0.9, 0.9, 0.25) for z in (bottom, top_z - 1.6)]
                pb.loft(rings, "concrete")
                ctx.pier(c.x, c.y, bottom, top_z)
            pb.box(P + UP * (top_z - 0.8), t, n, UP, (2.0, 12.0, 1.6), "concrete")
        else:      # split V
            for sg in (-1, 1):
                a = P + UP * bottom
                c = P + n * (sg * 3.6) + UP * top_z
                pb.beam(a, c, 1.4, 1.6, "concrete", up=t)
            ctx.pier(P.x, P.y, bottom, top_z)
        bearings(pb, P, t, n, top_z, (-3.0, 3.0))
        pb.box(P + UP * (top_z + 0.35), t, n, UP, (0.8, 1.2, 0.7), "concrete")         # seismic shear key
        # downpipe from the longitudinal drain to the ground along the column face
        if k % 2 == 0:
            a = P + n * 6.9 + t * 1.9 + UP * (P.z - 0.95)
            m = P + n * 1.2 + t * 1.75 + UP * (top_z - 0.4)
            det.tube(a, m, 0.12, "steel_grey", seg=6, smooth=False)
            det.tube(m, P + n * 1.2 + t * 1.75 + UP * (bottom + 1.0), 0.12, "steel_grey", seg=6, smooth=False)
            for zz in np.linspace(bottom + 1.5, top_z - 1.0, 3):
                det.box(P + n * 1.2 + t * 1.62 + UP * zz, t, n, UP, (0.3, 0.06, 0.06), "steel_grey")
        # uplight: lamp in the plaza at the foot of the column, wash up both faces
        if option == "tulip" and top_z - bottom > 3.0:
            for sg in (-1, 1):
                foot = P + t * (sg * 1.75) + UP * (bottom + 1.0)
                wash(wb, foot, P + t * (sg * 1.95) + UP * (top_z + 0.2), 2.2, t * sg, "wash_warm")
                det.box(P + t * (sg * 2.3) + UP * (bottom + 1.08), t, n, UP, (0.35, 0.6, 0.16), "lamp")
        # expansion joint every 4th pier
        if k % 4 == 3:
            i = int(np.argmin(np.abs(rail.s - pf["s"])))
            expansion_joint(det, rail, i, cls["half"])
            sub = Rail(path, pf["s"] - 0.06, pf["s"] + 0.06, s=[pf["s"] - 0.06, pf["s"] + 0.06])
            det.sweep(sub, [(y * 1.006, z * 1.01 + (0.005 if z > 0 else 0)) for y, z in box_section(E, D)], "rubber", closed=True)
        # inspection hatch in the soffit near every pier
        hp = P + t * 5.0 + UP * (P.z - D - 0.01)
        det.box(hp, t, n, UP, (0.9, 0.9, 0.04), "steel_grey")
    ctx.emit(f"Bridge_{name}_piers", pb)
    ctx.emit(f"BridgeDetail_{name}", det)
    ctx.emit(f"BridgeWash_{name}", wb)
    ctx.built.setdefault("bridge_depth", {})[name] = (rail.s.tolist(), [D] * rail.n)


# ---------------------------------------------------------------- small decks (hill streets, mountain road)
def small_deck(ctx, br, path, cls):
    s0, s1 = deck_range(br, path)
    rail = Rail(path, s0, s1, 2.0)
    E = edge_of(cls) + 0.1
    D = br.get("depth", 2.4)
    Dw = clamp_depth(ctx, rail, [D] * rail.n, E, margin=0.3, dmin=1.0)
    name = br["name"]
    g = BM(list(ctx.M))
    Dm = float(min(Dw))
    concrete_girder(ctx, g, rail, E, min(D, Dm))
    ctx.emit(f"Girder_{name}", g)
    det = BM(list(ctx.M))
    barrier_railing(det, rail, cls)
    pb = BM(list(ctx.M))
    for pf in pier_frames(br, path, s0, s1):
        p = pf["data"]
        top_z = pf["P"].z - min(D, Dm) - 0.32
        if top_z - p["bottom"] < 0.5:
            continue
        tulip_pier(ctx, pb, pf, top_z, p["bottom"], min(3.6, E * 0.4), ax=1.0, ay=1.3)
        bearings(pb, pf["P"], pf["t"], pf["n"], top_z, (-1.6, 1.6), 0.6)
        ctx.pier(pf["P"].x, pf["P"].y, p["bottom"], top_z)
    ctx.emit(f"Bridge_{name}_piers", pb)
    ctx.emit(f"BridgeDetail_{name}", det)
    ctx.built.setdefault("bridge_depth", {})[name] = (rail.s.tolist(), [min(D, Dm)] * rail.n)


# ---------------------------------------------------------------- Kagero viaduct (weathering steel girders)
def kagero(ctx, br, path, cls, option="haunched"):
    s0, s1 = deck_range(br, path)
    rail = Rail(path, s0, s1, 2.0)
    name = br["name"]
    E = cls["half"] + 0.9
    pfs = pier_frames(br, path, s0, s1)
    sp = np.array([pf["s"] for pf in pfs])
    hz = np.zeros(rail.n)
    for s in sp:
        hz = np.maximum(hz, np.cos(np.clip(np.abs(rail.s - s) / 15.0, 0, 1) * math.pi / 2) ** 2)
    want = 2.1 + (1.5 * hz if option == "haunched" else 0.0)
    d = clamp_depth(ctx, rail, want, E, margin=0.6, top=0.3, dmin=1.4)
    G = [-8.4, -2.8, 2.8, 8.4]
    slab = BM(list(ctx.M))
    slab.sweep(rail, [(-E, -0.3), (E, -0.3), (E, 0.05), (-E, 0.05)], "concrete", closed=True)
    for sg in (-1, 1):
        y = sg * E
        slab.sweep(rail, [(y, 0.15), (y, -0.95), (y + sg * 0.22, -0.95), (y + sg * 0.22, 0.15)] if sg > 0 else
                   [(y + sg * 0.22, 0.15), (y + sg * 0.22, -0.95), (y, -0.95), (y, 0.15)], "concrete", closed=True)
    ctx.emit(f"Girder_{name}", slab)
    st = BM(list(ctx.M))
    det = BM(list(ctx.M))
    key = "steel_weather"
    if option in ("haunched", "deck_arch"):
        for y in G:
            st.sweep_var(rail, lambda i, y=y: [(y - 0.03, -0.36), (y + 0.03, -0.36), (y + 0.03, -0.3 - d[i] + 0.06), (y - 0.03, -0.3 - d[i] + 0.06)][::-1], key)
            st.sweep(rail, [(y - 0.3, -0.36), (y + 0.3, -0.36), (y + 0.3, -0.3), (y - 0.3, -0.3)], key, closed=True)
            st.sweep_var(rail, lambda i, y=y: [(y - 0.36, -0.3 - d[i]), (y + 0.36, -0.3 - d[i]), (y + 0.36, -0.3 - d[i] + 0.06), (y - 0.36, -0.3 - d[i] + 0.06)], key)
        # stiffeners (every 2.5 m) and cross frames (every 6 m)
        acc, acf = 0.0, 0.0
        for i in range(rail.n - 1):
            ds = rail.s[i + 1] - rail.s[i]
            acc += ds
            acf += ds
            P, t, n = rail.frame(i)
            if acc >= 2.5:
                acc = 0.0
                for y in G:
                    for sg in (-1, 1):
                        det.box(P + n * (y + sg * 0.11) + UP * (-0.33 - d[i] / 2), t, n, UP, (0.025, 0.16, d[i] - 0.12), key)
            if acf >= 6.0:
                acf = 0.0
                zt, zb = -0.65, -0.3 - d[i] + 0.25
                for a, c in zip(G, G[1:]):
                    pa, pc = P + n * a, P + n * c
                    det.beam(pa + UP * zt, pc + UP * zt, 0.15, 0.15, key)
                    det.beam(pa + UP * zb, pc + UP * zb, 0.15, 0.15, key)
                    det.beam(pa + UP * zb, pc + UP * zt, 0.12, 0.12, key)
                    det.beam(pa + UP * zt, pc + UP * zb, 0.12, 0.12, key)
    if option == "through_truss":
        # two Warren trusses above the deck (clay option)
        for sg in (-1, 1):
            y = sg * (E + 0.4)
            st.sweep(rail, [(y - 0.4, -0.3), (y + 0.4, -0.3), (y + 0.4, 0.5), (y - 0.4, 0.5)], key, closed=True)
            st.sweep(rail, [(y - 0.4, 8.5), (y + 0.4, 8.5), (y + 0.4, 9.3), (y - 0.4, 9.3)], key, closed=True)
            for i in range(0, rail.n - 5, 5):
                a, c = rail.P(i, y, 0.5), rail.P(i + 5, y, 8.5)
                st.beam(a, c, 0.5, 0.5, key) if (i // 5) % 2 == 0 else st.beam(rail.P(i, y, 8.5), rail.P(i + 5, y, 0.5), 0.5, 0.5, key)
        for i in range(0, rail.n - 1, 5):
            st.beam(rail.P(i, -E, 9.0), rail.P(i, E, 9.0), 0.4, 0.4, key)
        for y in (-6.0, 0.0, 6.0):
            st.sweep(rail, [(y - 0.3, -1.6), (y + 0.3, -1.6), (y + 0.3, -0.3), (y - 0.3, -0.3)], key, closed=True)
    if option == "deck_arch":
        # an under-deck arch between the 2nd and 6th piers (clay option): spandrel columns on it
        if len(pfs) >= 6:
            a, c = pfs[1], pfs[5]
            ia = int(np.argmin(np.abs(rail.s - a["s"])))
            ic = int(np.argmin(np.abs(rail.s - c["s"])))
            for sg in (-1, 1):
                pts = []
                for k in range(25):
                    f = k / 24
                    i = int(round(ia + (ic - ia) * f))
                    zspring = SEA + 1.0
                    ztop = rail.pos[i][2] - 0.3 - d[i] - 0.5
                    pts.append(rail.P(i, sg * 6.0, 0) * 0 + Vector((rail.P(i, sg * 6.0, 0).x, rail.P(i, sg * 6.0, 0).y, zspring + (ztop - zspring) * math.sin(math.pi * f) ** 0.8)))
                for p0, p1 in zip(pts, pts[1:]):
                    st.beam(p0, p1, 1.6, 2.4, key)
    # inspection catwalk between the inner girders, drain pipe on the outer girder
    catwalk(det, rail, 0.0, lambda i: -0.3 - 2.0 - 0.2, 0.9)
    drain_pipe(det, rail, 9.4, -0.9, 0, rail.n - 1)
    barrier_railing(det, rail, cls)
    pb = BM(list(ctx.M))
    wb = BM(list(ctx.M))
    for k, pf in enumerate(pfs):
        p = pf["data"]
        P, t, n = pf["P"], pf["t"], pf["n"]
        i = int(np.argmin(np.abs(rail.s - pf["s"])))
        dd = d[i] if pf["off"] < 4.0 else 2.1
        top_z = P.z - 0.3 - dd - 0.45
        bottom = p["bottom"]
        if option == "deck_arch" and 1 < k < 5:
            bottom = max(bottom, SEA + 4.0)
        h = top_z - 2.2 - bottom
        if h < 0.5:
            continue
        # pile cap in the water
        if bottom < SEA:
            cap = [superellipse(P.x, P.y, z, 4.5, 10.5, t, n, n=5.0, seg=24) for z in (bottom, SEA + 1.6)]
            pb.loft(cap, "concrete")
            pb.loft([superellipse(P.x, P.y, z, 4.7, 10.7, t, n, n=5.0, seg=24) for z in (SEA - 0.3, SEA + 1.0)], "rubber", cap_top=False)
            cb = SEA + 1.6
        else:
            cb = bottom
        for sg in (-1, 1):
            rings = []
            for f in (0.0, 1.0):
                z = cb + (top_z - 2.2 - cb) * f
                yc = sg * (6.4 - 0.9 * f)
                c = P + n * yc
                rings.append(chamfer_rect(Vector((c.x, c.y, z)), t, n, 1.25 - 0.2 * f, 1.55 - 0.3 * f, 0.3))
            pb.loft(rings, "concrete")
            c = P + n * (sg * 6.0)
            ctx.pier(c.x, c.y, bottom, top_z)
            # uplight wash on the outer face of the column
            if top_z - cb > 6:
                wash(wb, P + n * (sg * 7.95) + UP * (cb + 0.3), P + n * (sg * 6.75) + UP * (top_z - 2.2), 1.3, n * sg, "wash_warm")
                det.box(P + n * (sg * 8.3) + UP * (cb + 0.12), t, n, UP, (0.5, 0.35, 0.2), "lamp")
        # cap beam with chamfered ends, tie beam on tall piers
        pb.box(P + UP * (top_z - 1.1), t, n, UP, (2.6, 17.6, 2.2), "concrete")
        for sg in (-1, 1):
            pb.beam(P + n * (sg * 8.8) + UP * (top_z - 0.2), P + n * (sg * 10.2) + UP * (top_z - 0.2), 2.6, 0.4, "concrete", up=UP)
        if top_z - cb > 16:
            pb.box(P + UP * (cb + (top_z - cb) * 0.5), t, n, UP, (1.6, 10.6, 1.4), "concrete")
        bearings(pb, P, t, n, top_z, G, 0.8)
        if k == len(pfs) // 2:
            caged_ladder(det, P + n * 6.4 + t * 1.45 + UP * cb, P + n * 6.4 + t * 1.45 + UP * (top_z - 0.1), t, n)
            sign_board(det, P + n * 6.4 + t * 1.32 + UP * (cb + 2.2), t, 0.9, 0.32, "sign_clearance")
        # downpipes
        a = P + n * 9.4 + t * 1.6 + UP * (P.z - 0.9)
        det.tube(a, P + n * 7.6 + t * 1.6 + UP * (top_z - 2.4), 0.11, "steel_grey", seg=6, smooth=False)
        det.tube(P + n * 7.6 + t * 1.6 + UP * (top_z - 2.4), P + n * 7.6 + t * 1.6 + UP * (cb + 0.3), 0.11, "steel_grey", seg=6, smooth=False)
    # the travelling maintenance gantry under one mid span
    if option == "haunched" and len(pfs) >= 4:
        sm = 0.5 * (pfs[3]["s"] + pfs[4]["s"]) if len(pfs) > 4 else 0.5 * (pfs[2]["s"] + pfs[3]["s"])
        gantry(ctx, det, path, sm, E, -0.3 - float(np.min(d)) - 0.9)
    ctx.emit(f"BridgeSteel_{name}", st)
    ctx.emit(f"Bridge_{name}_piers", pb)
    ctx.emit(f"BridgeDetail_{name}", det)
    ctx.emit(f"BridgeWash_{name}", wb)
    ctx.built.setdefault("bridge_depth", {})[name] = (rail.s.tolist(), (d + 0.3).tolist())


def gantry(ctx, b, path, s, E, zp):
    """Under-deck inspection gantry: hanger frames at both deck edges riding on fascia rails,
    a gridded platform across the whole width, hazard-striped ends, work lamps, signs."""
    P, t, n = frame_at(path, s)
    W = 2.6
    for sg in (-1, 1):
        y = sg * (E + 0.55)
        for dx in (-W / 2, W / 2):
            top = P + t * dx + n * y + UP * 0.5
            bot = P + t * dx + n * y + UP * zp
            b.beam(top, bot, 0.3, 0.3, "crane", up=t)
            b.box(top + UP * 0.15 - n * (sg * 0.3), t, n, UP, (0.5, 0.4, 0.3), "steel_grey")          # wheel bogie on the rail
        b.beam(P + n * y + t * (-W / 2) + UP * (zp + 1.2), P + n * y + t * (W / 2) + UP * (zp + 1.2), 0.2, 0.2, "crane")
        b.beam(P + n * y + t * (-W / 2) + UP * zp, P + n * y + t * (W / 2) + UP * 0.4, 0.15, 0.15, "crane")
        b.box(P + n * (y + sg * 0.18) + UP * (zp + 0.6), t, n, UP, (W, 0.04, 1.2), "hazard")
        sign_board(b, P + n * (y + sg * 0.22) + UP * (zp + 2.4), n * sg, 1.4, 0.5, "sign_clearance")
        # fascia rail the bogies run on
        b.box(P + n * (sg * (E + 0.3)) + UP * 0.35, t, n, UP, (40.0, 0.12, 0.12), "steel_grey")
    b.box(P + UP * (zp - 0.1), t, n, UP, (W, 2 * (E + 0.7), 0.2), "grating")
    for dx in (-W / 2 + 0.05, W / 2 - 0.05):
        b.box(P + t * dx + UP * (zp + 1.05), t, n, UP, (0.05, 2 * (E + 0.6), 0.06), "crane")
        b.box(P + t * dx + UP * (zp + 0.5), t, n, UP, (0.04, 2 * (E + 0.6), 0.04), "crane")
        for k in range(-5, 6):
            b.box(P + t * dx + n * (k * 2.3) + UP * (zp + 0.55), t, n, UP, (0.05, 0.05, 1.1), "crane")
    # truss under the platform
    for k in range(-5, 5):
        a = P + n * (k * 2.3) + UP * (zp - 0.2)
        c = P + n * ((k + 1) * 2.3) + UP * (zp - 1.3)
        for dx in (-W / 2, W / 2):
            b.beam(a + t * dx, c + t * dx, 0.12, 0.12, "crane")
    b.box(P + UP * (zp - 1.3), t, n, UP, (0.15, 2 * E, 0.15), "crane")
    for k in (-3, 0, 3):
        b.box(P + n * (k * 3.0) + UP * (zp + 2.4), t, n, UP, (0.3, 0.5, 0.2), "lamp")


# ---------------------------------------------------------------- Minato Bay Bridge (cable-stayed)
def port(ctx, br, path, cls, option="H_truss"):
    s0, s1 = deck_range(br, path)
    rail = Rail(path, s0, s1, 2.0)
    name = br["name"]
    H = cls["half"]
    E = H + 1.2               # 12.2: deck plate edge
    AY = E + 0.7              # stay anchor line
    truss = option == "H_truss"
    taper = np.array([smoothstep(s0, s0 + 50, s) * smoothstep(s1, s1 - 50, s) for s in rail.s])
    Dt = clamp_depth(ctx, rail, 2.6 + (4.6 - 2.6) * taper if truss else 3.0 + 0 * taper, E, margin=0.8, top=0.35, dmin=1.8)
    pfs = pier_frames(br, path, s0, s1)
    pyl = []
    for py in br["pylons"]:
        s, _ = station_of(path, py["pos"])
        pyl.append((s, py))
    # ---- deck
    g = BM(list(ctx.M))
    g.sweep(rail, [(-E, -0.35), (E, -0.35), (E, 0.05), (-E, 0.05)], "steel_white", closed=True)
    for sg in (-1, 1):        # edge fairings with the anchor outriggers' fascia
        y = sg * E
        prof = [(y, 0.1), (y + sg * 0.95, -0.2), (y + sg * 0.95, -0.7), (y, -1.25)]
        g.sweep(rail, prof if sg < 0 else prof[::-1], "steel_white", closed=True)
    ctx.emit(f"Girder_{name}", g)
    st = BM(list(ctx.M))
    det = BM(list(ctx.M))
    if truss:
        Y = H                     # truss planes under the barriers
        for sg in (-1, 1):
            st.sweep(rail, [(sg * Y - 0.45, -1.3), (sg * Y + 0.45, -1.3), (sg * Y + 0.45, -0.35), (sg * Y - 0.45, -0.35)], "steel_white", closed=True)
            st.sweep_var(rail, lambda i, sg=sg: [(sg * Y - 0.5, -0.35 - Dt[i]), (sg * Y + 0.5, -0.35 - Dt[i]), (sg * Y + 0.5, -0.35 - Dt[i] + 1.0), (sg * Y - 0.5, -0.35 - Dt[i] + 1.0)], "steel_white")
        for y in (-7.5, -3.5, 3.5, 7.5):
            st.sweep(rail, [(y - 0.15, -1.1), (y + 0.15, -1.1), (y + 0.15, -0.35), (y - 0.15, -0.35)], "steel_white", closed=True)
        # panels of ~10 m: verticals, Warren diagonals, floor beams, bottom laterals, sway frames
        panel = 10
        idx = list(range(0, rail.n, panel // 2))
        for j, i in enumerate(idx):
            P, t, n = rail.frame(i)
            zb = -0.35 - Dt[i] + 0.5
            for sg in (-1, 1):
                st.beam(rail.P(i, sg * Y, -1.3), rail.P(i, sg * Y, zb + 0.5), 0.55, 0.55, "steel_white", up=Vector((n.x, n.y, 0)))
                if j + 1 < len(idx):
                    i2 = idx[j + 1]
                    zb2 = -0.35 - Dt[i2] + 0.5
                    if j % 2 == 0:
                        st.beam(rail.P(i, sg * Y, -1.0), rail.P(i2, sg * Y, zb2), 0.6, 0.6, "steel_white", up=Vector((n.x, n.y, 0)))
                    else:
                        st.beam(rail.P(i, sg * Y, zb), rail.P(i2, sg * Y, -1.0), 0.6, 0.6, "steel_white", up=Vector((n.x, n.y, 0)))
            st.beam(rail.P(i, -Y, -0.95), rail.P(i, Y, -0.95), 0.5, 1.2, "steel_white")
            if j + 1 < len(idx):
                i2 = idx[j + 1]
                zb2 = -0.35 - Dt[i2] + 0.5
                det.beam(rail.P(i, -Y, zb), rail.P(i2, Y, zb2), 0.3, 0.3, "steel_white")
                det.beam(rail.P(i, Y, zb), rail.P(i2, -Y, zb2), 0.3, 0.3, "steel_white")
            if j % 2 == 0:
                det.beam(rail.P(i, -Y, zb), rail.P(i, Y, zb), 0.35, 0.35, "steel_white")
        catwalk(det, rail, 0.0, lambda i: -0.35 - Dt[i] + 0.55, 1.0)
    else:
        # streamlined steel box with fairings (option)
        st.sweep(rail, [(-9.0, -3.0), (9.0, -3.0), (E + 0.9, -1.2), (E + 0.9, -0.4), (-E - 0.9, -0.4), (-E - 0.9, -1.2)], "steel_white", closed=True)
    barrier_railing(det, rail, cls)
    for i in (1, rail.n - 2):
        expansion_joint(det, rail, i, H)
    # ---- approach piers: portal frames under the truss
    pb = BM(list(ctx.M))
    wb = BM(list(ctx.M))
    for pf in pfs:
        p = pf["data"]
        P, t, n = pf["P"], pf["t"], pf["n"]
        i = int(np.argmin(np.abs(rail.s - pf["s"])))
        dd = Dt[i] if pf["off"] < 4 else 2.4
        top_z = P.z - 0.35 - dd - 0.4
        bottom = p["bottom"]
        if top_z - bottom < 1.0:
            continue
        cb = bottom
        if bottom < SEA:
            pb.loft([superellipse(P.x, P.y, z, 4.0, 15.0, t, n, n=5, seg=24) for z in (bottom, SEA + 1.8)], "concrete")
            pb.loft([superellipse(P.x, P.y, z, 4.2, 15.2, t, n, n=5, seg=24) for z in (SEA - 0.3, SEA + 1.2)], "rubber", cap_top=False)
            cb = SEA + 1.8
        for sg in (-1, 1):
            c = P + n * (sg * 10.8)
            pb.loft([chamfer_rect(Vector((c.x, c.y, z)), t, n, a, a, 0.35) for z, a in ((cb, 1.5), (top_z - 2.4, 1.2))], "concrete")
            ctx.pier(c.x, c.y, bottom, top_z)
        pb.box(P + UP * (top_z - 1.2), t, n, UP, (3.0, 2 * 12.6, 2.4), "concrete")
        bearings(pb, P, t, n, top_z, (-H, H), 1.0)
    # ---- pylons and stays
    cab = BM(list(ctx.M))
    far = BM(list(ctx.M))
    for k, (sp, py) in enumerate(pyl):
        P, t, n = frame_at(path, sp)
        zd = P.z
        zt = py["top"]
        bottom = py["bottom"]
        i = int(np.argmin(np.abs(rail.s - sp)))
        zdeck_bot = zd - 0.35 - Dt[i]
        cap_top = SEA + 2.5
        # pile cap with fenders
        pb.loft([superellipse(P.x, P.y, z, 13.0, 25.0, t, n, n=6, seg=32) for z in (bottom, cap_top)], "concrete")
        pb.loft([superellipse(P.x, P.y, z, 13.3, 25.3, t, n, n=6, seg=32) for z in (SEA - 0.4, SEA + 1.4)], "rubber", cap_top=False)
        ctx.pier(P.x, P.y, bottom, zt, pylon=True)
        legs = pylon(ctx, pb, det, wb, P, t, n, cap_top, zd, zdeck_bot, zt, option, E)
        # stays: 14 per span side per plane
        main_dir = 1 if (k == 0) else -1
        other = pyl[1 - k][0] if len(pyl) > 1 else sp + main_dir * 300
        half_main = abs(other - sp) / 2
        back_len = (sp - (s0 + 10)) if main_dir > 0 else ((s1 - 10) - sp)
        for side in (-1, 1):
            for dirn in (1, -1):
                span_dir = dirn * main_dir
                for j in range(1, 15):
                    if dirn == 1:
                        sd = sp + span_dir * (12.0 + (j - 1) * (half_main - 16.0) / 13.0)
                    else:
                        sd = sp + span_dir * (14.0 + (j - 1) * (back_len - 16.0) / 13.0)
                    za = zt - 7.0 - (14 - j) * (2.3 if option != "A_fan" else 0.45)
                    a = legs(side, za, span_dir)
                    q, tq, nq = frame_at(path, sd)
                    b = q + nq * (side * AY) + UP * (-0.25)
                    r = 0.085 + 0.045 * j / 14
                    cab.tube(a, b, r, "cable", seg=8)
                    dvec = (b - a).normalized()
                    w_dir = (Vector((tq.x, tq.y, 0)) - dvec * dvec.dot(Vector((tq.x, tq.y, 0))))
                    far.ribbon(a, b, 0.5, w_dir if w_dir.length > 1e-4 else nq, "cable")
                    # deck anchorage: outrigger, anchor box, socket and guide pipe; damper collar
                    det.beam(q + nq * (side * E) + UP * (-0.5), q + nq * (side * (AY + 0.45)) + UP * (-0.5), 0.6, 0.8, "steel_white")
                    det.box(b + UP * (-0.45), Vector((tq.x, tq.y, 0)), nq, UP, (1.0, 0.8, 0.9), "steel_white")
                    det.tube(b, b - dvec * 2.6, r + 0.13, "steel_grey", seg=8)
                    det.tube(b - dvec * 2.6, b - dvec * 3.4, r + 0.06, "rubber", seg=8)
                    det.tube(a, a + dvec * 2.2, r + 0.16, "steel_white", seg=8)
        if k == 1 and truss:
            repair_works(ctx, det, P, t, n, cap_top, zd, zt, legs)
        if ctx.lights:
            for side in (-1, 1):
                c = legs(side, cap_top + 1, 1, centre=True)
                ctx.light("Light_uplight", (c.x + n.x * side * 3.2, c.y + n.y * side * 3.2, cap_top + 0.6), (1.0, 0.82, 0.62), 6000.0, "SPOT", UP * 1.0 - n * (side * 0.08), math.radians(30))
    ctx.emit(f"BridgeSteel_{name}", st)
    ctx.emit(f"Bridge_{name}_pylons", pb)
    ctx.emit(f"BridgeDetail_{name}", det)
    ctx.emit(f"BridgeCables_{name}", cab)
    ctx.emit(f"BridgeCablesFar_{name}", far)
    ctx.emit(f"BridgeWash_{name}", wb)
    ctx.built.setdefault("bridge_depth", {})[name] = (rail.s.tolist(), (Dt + 0.35).tolist())


def pylon(ctx, pb, det, wb, P, t, n, z0, zd, zdeck_bot, zt, option, E):
    """Concrete pylon on the pile cap. Returns legs(side, z, span_dir, centre=False) -> the point
    on the leg face (towards span_dir) at height z where a stay anchors."""
    def yc(z):              # leg centre (lateral) for the H pylon
        if z <= zd:
            return 17.6 + (16.4 - 17.6) * (z - z0) / max(1.0, zd - z0)
        return 16.4 + (15.4 - 16.4) * (z - zd) / max(1.0, zt - zd)

    def ay(z):
        f = (z - z0) / max(1.0, zt - z0)
        return 2.7 + (1.65 - 2.7) * f

    def ax(z):
        f = (z - z0) / max(1.0, zt - z0)
        return 3.7 + (2.4 - 3.7) * f

    if option == "A_fan":
        def yc(z):          # noqa: F811 (A frame: legs meet at the top)
            f = (z - z0) / max(1.0, zt - z0)
            return 17.6 * (1 - f) + 1.8 * f
    if option == "invY_box":
        zj = zd + 34.0

        def yc(z):          # noqa: F811 (inverted Y: legs join above the deck into one mast)
            if z >= zj:
                return 0.0
            return 17.6 * (zj - z) / (zj - z0)
    zs = sorted(set([z0, zd - 6, zd, zd + 20, zd + 45, zd + 70, zt - 8, zt] + ([zd + 34.0] if option == "invY_box" else [])))
    zs = [z for z in zs if z0 <= z <= zt]
    for side in (-1, 1):
        rings = []
        for z in zs:
            yy = side * yc(z)
            if option == "invY_box" and yc(z) == 0.0:
                if side < 0:
                    continue
            c = P + n * yy
            rings.append(chamfer_rect(Vector((c.x, c.y, z)), t, n, ax(z), ay(z) if not (option == "invY_box" and yc(z) == 0.0) else ay(z) * 1.6, 0.55))
        if len(rings) >= 2:
            pb.loft(rings, "concrete", cap_top=True)
    # cross beams
    if option == "H_truss":
        beams = [(zd + 50.0, 5.0, 3.8), (zt - 3.0, 6.0, 3.6)]
        low = zdeck_bot - 2.3
        if low - 1.8 > z0 + 2.0:
            beams.insert(0, (low, 3.6, 4.2))
        else:
            for sg in (-1, 1):          # deck close to the water: pedestals on the pile cap
                c = P + n * (sg * 11.0)
                pb.box(c + UP * (0.5 * (z0 + zdeck_bot - 0.3)), t, n, UP, (3.0, 2.6, zdeck_bot - 0.3 - z0), "concrete")
        for zc, depth, wid in beams:
            yy = yc(zc) - ay(zc) * 0.5
            pb.box(P + UP * zc, t, n, UP, (wid, 2 * yy, depth), "concrete")
            for sg in (-1, 1):       # haunches
                pb.beam(P + n * (sg * (yy - 3.0)) + UP * (zc - depth / 2), P + n * (sg * yy) + UP * (zc - depth / 2 - 2.2), wid, 1.2, "concrete", up=t)
        # bearings for the truss on the lower beam
        bearings(pb, P, t, n, zdeck_bot - 0.3 - 0.29, (-11.0, 11.0), 1.1)
    elif option == "A_fan":
        pb.box(P + UP * (zdeck_bot - 2.3), t, n, UP, (4.0, 2 * yc(zdeck_bot - 2.3), 3.6), "concrete")
    else:
        pb.box(P + UP * (zdeck_bot - 2.3), t, n, UP, (4.0, 2 * yc(zdeck_bot - 2.3), 3.6), "concrete")
    # anchorage zones: steel anchor boxes on the span faces of the legs
    zlo = zt - 7.0 - 13 * 2.3 - 2.0
    for side in (-1, 1):
        if option == "invY_box" and side < 0:
            continue
        for sg in (-1, 1):
            zm = 0.5 * (zlo + zt - 5.0)
            c = P + n * (side * yc(zm)) + t * (sg * (ax(zm) + 0.08)) + UP * zm
            det.box(c, t, n, UP, (0.16, ay(zm) * 1.5, zt - 5.0 - zlo), "steel_white")
        top = P + n * (side * yc(zt)) + UP * zt
        det.box(top + UP * 0.6, t, n, UP, (1.2, 1.2, 1.2), "steel_grey")
        det.box(top + UP * 1.35, t, n, UP, (0.5, 0.5, 0.3), "red_light")
        det.tube(top + UP * 1.2, top + UP * 6.0, 0.05, "steel_grey", seg=6)
        mid = P + n * (side * (yc(zd + 50) + ay(zd + 50) + 0.25)) + UP * (zd + 50 + 3.0)
        det.box(mid, t, n, UP, (0.4, 0.4, 0.4), "red_light")
        # maintenance railing around the leg head
        for a in range(8):
            th0, th1 = 2 * math.pi * a / 8, 2 * math.pi * (a + 1) / 8
            r = max(ax(zt), ay(zt)) + 0.8
            p0 = top + t * (r * math.cos(th0)) + n * (r * math.sin(th0)) + UP * 1.1
            p1 = top + t * (r * math.cos(th1)) + n * (r * math.sin(th1)) + UP * 1.1
            det.tube(p0, p1, 0.035, "steel_grey", seg=4)
        # uplight wash: outer face from the pile cap, span faces from the deck
        z1 = min(zt - 2, zd + 62)
        f0 = P + n * (side * (yc(z0 + 0.4) + ay(z0 + 0.4) + 0.12)) + UP * (z0 + 0.4)
        f1 = P + n * (side * (yc(z1) + ay(z1) + 0.12)) + UP * z1
        wash(wb, f0, f1, 2.6, n * side, "wash_warm")
        for sg in (-1, 1):
            f0 = P + n * (side * yc(zd + 1.0)) + t * (sg * (ax(zd + 1) + 0.12)) + UP * (zd + 1.0)
            f1 = P + n * (side * yc(zd + 38)) + t * (sg * (ax(zd + 38) + 0.12)) + UP * (zd + 38)
            wash(wb, f0, f1, 1.9, t * sg, "wash_warm")
        caged_ladder(det, P + n * (side * (yc(z0) - ay(z0) - 0.45)) + UP * z0, P + n * (side * (yc(zdeck_bot) - ay(zdeck_bot) - 0.45)) + UP * (zdeck_bot - 0.5), -n * side, t)
    sign_board(det, P + n * (yc(z0 + 2) + ay(z0 + 2) + 0.06) + UP * (z0 + 2.2), n, 1.6, 0.8, "sign_no_access")
    sign_board(det, P + n * (-(yc(z0 + 2) + ay(z0 + 2) + 0.06)) + UP * (z0 + 2.2), -n, 1.6, 0.47, "sign_bridge_id")

    def legs(side, z, span_dir, centre=False):
        yy = yc(z) * side
        if option == "invY_box" and yc(z) == 0.0:
            yy = side * 0.9
        c = P + n * yy + UP * z
        return c if centre else c + t * (span_dir * ax(z))
    return legs


def repair_works(ctx, b, P, t, n, z0, zd, zt, legs):
    """Pylon leg under repair: scaffold around one leg from the pile cap to above the deck,
    Hoshikawa hoardings on the lifts facing the road, and a tower crane on the pile cap."""
    side = -1
    zs_top = zd + 26.0
    c0 = legs(side, z0, 1, centre=True)
    ax, ay = 3.7 + 1.3, 2.7 + 1.3
    corners = [(-ax, -ay), (ax, -ay), (ax, ay), (-ax, ay)]
    pos = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        L = math.hypot(x1 - x0, y1 - y0)
        m = max(1, int(L / 2.4))
        for k in range(m):
            f = k / m
            pos.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))

    def W(x, y, z):
        return Vector((c0.x, c0.y, 0)) + t * x + n * y + UP * z
    for x, y in pos:
        b.tube(W(x, y, z0), W(x, y, zs_top), 0.03, "steel_grey", seg=6)
    lifts = np.arange(z0 + 2.0, zs_top + 0.1, 2.0)
    for li, z in enumerate(lifts):
        ring = [W(x, y, z) for x, y in corners]
        for p0, p1 in zip(ring, ring[1:] + ring[:1]):
            b.tube(p0, p1, 0.024, "steel_grey", seg=5)
        if li % 2 == 1:
            for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
                mid = W((x0 + x1) / 2, (y0 + y1) / 2, z + 0.03)
                d = W(x1, y1, z) - W(x0, y0, z)
                L = d.length
                inward = (Vector((c0.x, c0.y, 0)) + UP * z - mid)
                inward.z = 0
                inward.normalize()
                b.box(mid + inward * 0.5, d.normalized(), inward, UP, (L, 0.9, 0.06), "grating")
            # zig-zag bracing on the faces
            for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
                if li + 1 < len(lifts):
                    b.tube(W(x0, y0, z), W(x1, y1, lifts[li + 1]), 0.02, "steel_grey", seg=4)
    # hoardings on the two faces along the deck (seen by drivers), 2 lifts tall at deck level
    for sg in (-1, 1):
        x = sg * (ax + 0.05)
        za, zb = zd + 1.0, zd + 7.0
        p = [W(x, -ay, za), W(x, ay, za), W(x, ay, zb), W(x, -ay, zb)]
        if sg < 0:
            p = [p[1], p[0], p[3], p[2]]
        Wd = 2 * ay
        b.face(p, "hoarding", [(0, 0), (6.0 * round(Wd / 6.0 + 0.49), 0), (6.0 * round(Wd / 6.0 + 0.49), 6.0), (0, 6.0)], t * sg)
        b.face(p[::-1], "steel_grey", [(0, 0), (Wd, 0), (Wd, 6.0), (0, 6.0)], -t * sg)
    sp = [W(-1.0, side * (ay + 0.05), z0 + 1.2), W(1.0, side * (ay + 0.05), z0 + 1.2), W(1.0, side * (ay + 0.05), z0 + 2.45), W(-1.0, side * (ay + 0.05), z0 + 2.45)]
    b.face(sp, "sign_works", [(0, 0), (1, 0), (1, 1), (0, 1)], n * side)
    # tower crane on the pile cap, outboard of the leg
    m0 = Vector((c0.x, c0.y, 0)) + n * (side * 6.6) + t * (-7.5)
    tower_crane(b, m0, z0, zd + 72.0, t, n * side)


def tower_crane(b, base, z0, z1, fwd, side):
    """Lattice tower crane: mast (2 m square), slewing unit, cab, jib forward, counter-jib with
    counterweights, apex with pendants, trolley and hook. `fwd` is the jib direction."""
    fwd = Vector(fwd).normalized()
    side = Vector(side).normalized()
    a = 1.0
    C = [(-a, -a), (a, -a), (a, a), (-a, a)]

    def M(x, y, z):
        return Vector((base.x, base.y, 0)) + fwd * x + side * y + UP * z
    for x, y in C:
        b.tube(M(x, y, z0), M(x, y, z1), 0.09, "crane", seg=6)
    z = z0
    k = 0
    while z + 2.5 <= z1:
        for (x0, y0), (x1, y1) in zip(C, C[1:] + C[:1]):
            if k % 2:
                b.tube(M(x0, y0, z), M(x1, y1, z + 2.5), 0.045, "crane", seg=4)
            else:
                b.tube(M(x1, y1, z), M(x0, y0, z + 2.5), 0.045, "crane", seg=4)
            b.tube(M(x0, y0, z), M(x1, y1, z), 0.04, "crane", seg=4)
        z += 2.5
        k += 1
    b.box(M(0, 0, z0 + 0.6), fwd, side, UP, (3.2, 3.2, 1.2), "concrete")
    b.box(M(0, 0, z1 + 0.6), fwd, side, UP, (2.6, 2.6, 1.2), "crane")
    b.box(M(1.2, 1.8, z1 + 1.6), fwd, side, UP, (1.6, 1.6, 2.0), "crane")                 # cab
    b.box(M(1.95, 1.8, z1 + 1.8), fwd, side, UP, (0.05, 1.4, 1.0), "glass")
    zj = z1 + 1.4
    Lj, Lc = 55.0, 18.0
    # jib: triangular lattice
    tri = [(-0.7, 0.0), (0.7, 0.0), (0.0, 1.6)]
    for y, dz in tri:
        b.tube(M(0, y, zj + dz), M(Lj, y, zj + dz), 0.06, "crane", seg=5)
    x = 0.0
    k = 0
    while x + 2.5 <= Lj:
        for (y0, d0), (y1, d1) in zip(tri, tri[1:] + tri[:1]):
            b.tube(M(x, y0, zj + d0), M(x + 2.5, y1, zj + d1), 0.035, "crane", seg=4)
        x += 2.5
        k += 1
    # counter-jib and counterweights
    for y in (-0.8, 0.8):
        b.tube(M(0, y, zj), M(-Lc, y, zj), 0.08, "crane", seg=5)
    b.box(M(-Lc / 2, 0, zj + 0.05), fwd, side, UP, (Lc, 1.8, 0.1), "grating")
    for k in range(4):
        b.box(M(-Lc + 1.0 + k * 1.0, 0, zj - 1.0), fwd, side, UP, (0.9, 2.2, 2.2), "hazard")
    # apex and pendants
    apex = M(0, 0, zj + 9.0)
    for x, y in ((0.9, 0.9), (-0.9, 0.9), (0.9, -0.9), (-0.9, -0.9)):
        b.tube(M(x, y, zj), apex, 0.07, "crane", seg=5)
    b.tube(apex, M(Lj * 0.7, 0, zj + 1.6), 0.03, "steel_grey", seg=4)
    b.tube(apex, M(-Lc, 0, zj), 0.03, "steel_grey", seg=4)
    b.box(apex + UP * 0.3, fwd, side, UP, (0.35, 0.35, 0.3), "red_light")
    b.box(M(Lj, 0, zj + 0.3), fwd, side, UP, (0.3, 0.3, 0.3), "red_light")
    # trolley + hook block on a slack line
    tx = 31.0
    b.box(M(tx, 0, zj - 0.25), fwd, side, UP, (1.4, 1.6, 0.5), "crane")
    hz = zj - 32.0
    for y in (-0.15, 0.15):
        b.tube(M(tx, y, zj - 0.5), M(tx, y, hz + 0.6), 0.015, "steel_grey", seg=4)
    b.box(M(tx, 0, hz + 0.3), fwd, side, UP, (0.6, 0.5, 0.7), "hazard")
    b.tube(M(tx, 0, hz), M(tx, 0, hz - 0.8), 0.06, "steel_grey", seg=6)


# ---------------------------------------------------------------- Tenjin Arch (basket-handle network arch)
def tenjin(ctx, br, path, cls, option="basket"):
    s0, s1 = deck_range(br, path)
    name = br["name"]
    H = cls["half"]
    rib0 = br["arches"][0]
    sa, _ = station_of(path, rib0[0][:2])
    sb, _ = station_of(path, rib0[-1][:2])
    if sa > sb:
        sa, sb = sb, sa
    Pm, _, _ = frame_at(path, 0.5 * (sa + sb))
    rise = max(p[2] for p in rib0) - Pm.z - 1.0
    Ytie = H + 4.2            # 11.0: tie girder line, outboard of the sidewalk (walk edge H + 3.0)
    E = Ytie + 0.75
    pfs = pier_frames(br, path, s0, s1)
    heavy = [pf for pf in pfs if pf["data"].get("heavy")]
    # ---- approach spans: concrete box girder; main span: slab on floor beams between the ties
    ra0 = Rail(path, s0, sa - 1.0, 2.0) if sa - 1.0 - s0 > 4 else None
    ra1 = Rail(path, sb + 1.0, s1, 2.0) if s1 - sb - 1.0 > 4 else None
    rm = Rail(path, sa - 6.0, sb + 6.0, 2.0)
    g = BM(list(ctx.M))
    Da = br.get("depth", 2.4)
    for r in (ra0, ra1):
        if r is not None:
            concrete_girder(ctx, g, r, E, Da)
    g.sweep(rm, [(-E, -0.35), (E, -0.35), (E, 0.05), (-E, 0.05)], "concrete", closed=True)
    for sg in (-1, 1):       # walkway strip between the sidewalk and the tie
        y0, y1 = sg * (H + 3.0), sg * (Ytie - 0.6)
        g.sweep(rm, [(min(y0, y1), 0.0), (max(y0, y1), 0.0), (max(y0, y1), 0.35), (min(y0, y1), 0.35)], "concrete", closed=True)
    ctx.emit(f"Girder_{name}", g)
    st = BM(list(ctx.M))
    det = BM(list(ctx.M))
    cab = BM(list(ctx.M))
    far = BM(list(ctx.M))
    wb = BM(list(ctx.M))
    # tie girders (protrude 0.9 m above the deck: they shield the walkway)
    for sg in (-1, 1):
        y = sg * Ytie
        st.sweep(rm, [(y - 0.6, -1.9), (y + 0.6, -1.9), (y + 0.6, 0.9), (y - 0.6, 0.9)], "steel_white", closed=True)
    for i in range(0, rm.n, 3):
        st.beam(rm.P(i, -Ytie, -1.0), rm.P(i, Ytie, -1.0), 0.45, 1.3, "steel_white")
    # ---- ribs
    def rib_point(f, side):
        s = sa + (sb - sa) * f
        P, t, n = frame_at(path, s)
        h = 4 * rise * f * (1 - f)
        if option == "basket":
            y = side * (Ytie - (Ytie - 2.3) * (h / rise) ** 1.15)
        elif option == "single_lean":
            y = (Ytie + 4.0) * (1.0 - h / rise)
        else:
            y = side * Ytie
        base = P + UP * 0.9
        return base + n * y + UP * h, t, n
    sides = (0,) if option == "single_lean" else (-1, 1)
    N = 48
    ribs = {}
    for side in sides:
        pts = [rib_point(k / N, side if side else 1) for k in range(N + 1)]
        ribs[side] = [p for p, _, _ in pts]
        rings = []
        for k, (p, t, n) in enumerate(pts):
            T = (pts[min(N, k + 1)][0] - pts[max(0, k - 1)][0]).normalized()
            L = n * (side if side else 1)
            L = (L - T * T.dot(L)).normalized()
            U = T.cross(L).normalized()
            if U.z < 0:
                U = -U
            f = k / N
            taper = 1 - 0.32 * math.sin(math.pi * f)
            w, d = 1.25 * taper, 1.15 * taper
            if option == "single_lean":
                w, d = 2.0 * taper, 1.8 * taper
            rings.append([p + L * x + U * y for x, y in ((w, -d), (w, d), (-w, d), (-w, -d))])
        # loft along the rib (cap the ends at the springings)
        st.loft(rings, "steel_white", cap_top=True, cap_bottom=True, vz=False)
        # springing shoe on the tie
        p0 = pts[0][0]
        st.box(p0 + UP * -0.2, pts[0][1], pts[0][2], UP, (4.0, 2.4, 2.2), "steel_white")
        p1 = pts[-1][0]
        st.box(p1 + UP * -0.2, pts[-1][1], pts[-1][2], UP, (4.0, 2.4, 2.2), "steel_white")
    # wind bracing between the ribs, and the crown with the Hoshikawa plaque
    if len(sides) == 2:
        fs = [0.27, 0.34, 0.41, 0.59, 0.66, 0.73]
        prev = None
        for f in fs:
            k = int(round(f * N))
            a, c = ribs[-1][k], ribs[1][k]
            st.beam(a, c, 0.9, 1.0, "steel_white", up=UP)
            if prev is not None and abs(prev[0] - f) < 0.1:
                kp = prev[1]
                det.beam(ribs[-1][kp], c, 0.45, 0.45, "steel_white")
                det.beam(ribs[1][kp], a, 0.45, 0.45, "steel_white")
            prev = (f, k)
        if option == "basket":
            k0, k1 = int(N * 0.45), int(N * 0.55)
            for k in range(k0, k1):
                quad = [ribs[-1][k], ribs[1][k], ribs[1][k + 1], ribs[-1][k + 1]]
                st.face(quad, "steel_white", [(0, 0), (4, 0), (4, 4), (0, 4)], UP)
                st.face([q - UP * 0.9 for q in quad[::-1]], "steel_white", [(0, 0), (4, 0), (4, 4), (0, 4)], -UP)
            km = N // 2
            c = (ribs[-1][km] + ribs[1][km]) / 2
            Pc, tc, nc = frame_at(path, 0.5 * (sa + sb))
            for sgn in (-1, 1):
                plate_c = c + tc * (sgn * 2.2) + UP * (-0.2)
                det.box(plate_c, tc, nc, UP, (0.12, 4.4, 1.6), "gold")
                det.face([plate_c + tc * (sgn * 0.07) + nc * (-1.9 * sgn) + UP * -0.65, plate_c + tc * (sgn * 0.07) + nc * (1.9 * sgn) + UP * -0.65,
                          plate_c + tc * (sgn * 0.07) + nc * (1.9 * sgn) + UP * 0.65, plate_c + tc * (sgn * 0.07) + nc * (-1.9 * sgn) + UP * 0.65],
                         "logo", [(0, 0), (1, 0), (1, 1), (0, 1)], tc * sgn)
                det.box(c + nc * (sgn * 1.2) + UP * 1.0, tc, nc, UP, (0.4, 0.4, 0.4), "red_light")
    # hangers: network in each rib plane, crossing at +-22 m along the span
    for side in sides:
        rib = ribs[side]
        ns = int((sb - sa - 16.0) / 6.5)
        for j in range(ns + 1):
            s = sa + 8.0 + j * (sb - sa - 16.0) / max(1, ns)
            P, t, n = frame_at(path, s)
            y = (side if side else 0) * Ytie
            foot = P + n * y + UP * 0.9
            for dirn in ((-1, 1) if option != "twin_ribs" else (0,)):
                st_ = s + dirn * 22.0
                f = (st_ - sa) / (sb - sa)
                if not (0.06 < f < 0.94):
                    continue
                kf = f * N
                k0 = int(kf)
                q = rib[k0].lerp(rib[min(N, k0 + 1)], kf - k0) - UP * 1.0
                if option == "single_lean":
                    for yy in (-Ytie, Ytie):
                        cab.tube(q, P + n * yy + UP * 0.9, 0.07, "cable", seg=6)
                        far.ribbon(q, P + n * yy + UP * 0.9, 0.3, t, "cable")
                    continue
                cab.tube(foot, q, 0.075, "cable", seg=6)
                far.ribbon(foot, q, 0.32, t, "cable")
                det.tube(foot, foot + (q - foot).normalized() * 1.2, 0.16, "steel_grey", seg=6)
                det.tube(q, q + (foot - q).normalized() * 0.9, 0.14, "steel_grey", seg=6)
    # ---- railings, lamps' wash on the ribs, deck soffit glow
    for r in (ra0, ra1, rm):
        if r is not None:
            barrier_railing(det, r, cls)
    for side in sides:
        rib = ribs[side]
        for k in (6, 12, N - 12, N - 6):
            p = rib[k]
            P, t, n = frame_at(path, sa + (sb - sa) * k / N)
            a = Vector((p.x, p.y, P.z + 1.0))
            wash(wb, a + n * ((side or 1) * 0.0) - (n * (side or 1)) * 1.4, p - (n * (side or 1)) * 1.4 + UP * 6.0, 1.6, -n * (side or 1), "wash_cool")
        for k in range(4, N - 3, 8):
            P, t, n = frame_at(path, sa + (sb - sa) * k / N)
            det.box(P + n * ((side or 1) * (Ytie - 0.66)) + UP * 0.75, t, n, UP, (0.5, 0.12, 0.12), "lamp_cool")
    # ---- piers: heavy thrust piers under the rib ends, slender oval columns for the approaches
    pb = BM(list(ctx.M))
    for pf in pfs:
        p = pf["data"]
        P, t, n = pf["P"], pf["t"], pf["n"]
        in_main = sa - 8 < pf["s"] < sb + 8
        top_z = P.z - (2.0 if in_main or p.get("heavy") else Da) - 0.35
        bottom = p["bottom"]
        if top_z - bottom < 1.0:
            continue
        if p.get("heavy"):
            cb = bottom
            if bottom < SEA:
                pb.loft([superellipse(P.x, P.y, z, 7.0, 16.0, t, n, n=2.6, seg=32) for z in (bottom, SEA + 2.0)], "concrete")
                cb = SEA + 2.0
            rings = []
            for f in (0.0, 0.5, 0.85, 1.0):
                z = cb + (top_z - cb) * f
                rings.append(superellipse(P.x, P.y, z, 4.0 + 1.2 * f ** 2, 9.0 + 4.6 * f ** 2.5, t, n, n=2.4, seg=32))
            pb.loft(rings, "concrete")
            bearings(pb, P, t, n, top_z, (-Ytie, Ytie), 1.3)
            ctx.pier(P.x, P.y, bottom, top_z, heavy=True)
            for sg in (-1, 1):
                wash(wb, P + n * (sg * 9.4) + UP * (cb + 0.3), P + n * (sg * 13.4) + UP * (top_z - 0.3), 2.5, n * sg, "wash_warm")
        else:
            tulip_pier(ctx, pb, pf, top_z, bottom, 4.2, ax=1.3, ay=1.9, n=2.4)
            bearings(pb, P, t, n, top_z, (-3.0, 3.0))
            ctx.pier(P.x, P.y, bottom, top_z)
    ctx.emit(f"BridgeSteel_{name}", st)
    ctx.emit(f"Bridge_{name}_piers", pb)
    ctx.emit(f"BridgeDetail_{name}", det)
    ctx.emit(f"BridgeCables_{name}", cab)
    ctx.emit(f"BridgeCablesFar_{name}", far)
    ctx.emit(f"BridgeWash_{name}", wb)
    dep = []
    rs = np.linspace(s0, s1, max(2, int((s1 - s0) / 2) + 1))
    for s in rs:
        dep.append(2.0 if sa - 6 <= s <= sb + 6 else Da)
    ctx.built.setdefault("bridge_depth", {})[name] = (rs.tolist(), dep)


def build(ctx, br, path, cls, option=None):
    d = design_of(br)
    opt = option or CHOSEN.get(d)
    if d == "port" and br["pylons"]:
        port(ctx, br, path, cls, opt)
    elif d == "expressway":
        expressway(ctx, br, path, cls, opt)
    elif d == "kagero":
        kagero(ctx, br, path, cls, opt)
    elif d == "tenjin" and br["arches"]:
        tenjin(ctx, br, path, cls, opt)
    else:
        small_deck(ctx, br, path, cls)
