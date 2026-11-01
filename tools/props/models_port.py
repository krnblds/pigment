"""Port kit props (the world's Minato port): ISO container, ship-to-shore gantry crane and the
yard high-mast light.  Blender axes: Z up, origin on the ground at the footprint centre.

These replace the world's procedural `container` / `crane_sts` / `light_mast` meshes
(tools/world/world_meshes.py Kit): tools/world/world_build.py uses assets/props/<key>.glb when
it exists, so the world asset keys, origins and sizes stay the same:

    container    12.19 x 2.44 x 2.59 m (ISO 40' dry van), long axis X, doors at +X, origin bottom
                 centre; stacks at 2.6 m pitch
    crane_sts    legs at x = +-14, y = +-9 (rails along X at y = +-9), boom over the water to +Y
                 (tip at y = 64), back reach to y = -28, apex ~68 m
    light_mast   30 m high mast, flood ring at 29.6 m, origin at the base centre
"""
import math

import bmesh
from mathutils import Euler, Vector

from proplib import Prop

MODELS = {}


def model(fn):
    MODELS[fn.__name__[2:]] = fn
    return fn


# ------------------------------------------------------------------ helpers

def corr_profile(length, pitch, depth, flat=0.36, slope=0.14):
    """Trapezoidal corrugation along [0, length]: [(s, d)] with d = 0 on the crests and
    `depth` in the troughs.  Starts and ends on a crest."""
    n = max(1, int(round(length / pitch)))
    p = length / n
    pts = []
    for k in range(n):
        s0 = k * p
        for f, d in ((0.0, 0.0), (flat, 0.0), (flat + slope, depth), (1.0 - slope, depth)):
            pts.append((s0 + f * p, d))
    pts.append((length, 0.0))
    return pts


def corr_sheet(P, name, group, origin, u, n, e, length, pitch, depth, back=0.006, uv_boost=1.0):
    """A corrugated sheet: crests on the plane through `origin`, corrugation profile along unit
    vector `u` for `length`, troughs `depth` along -n (n = outward normal), extruded along
    vector `e`.  Built as a flattened tube (crest/trough strip + one flat back face + the two
    end faces) so its normals orient outward; the open long edges hide under rails / frames."""
    bm = P.bm
    O, U, N, E = Vector(origin), Vector(u).normalized(), Vector(n).normalized(), Vector(e)
    prof = corr_profile(length, pitch, depth)
    loop = [O + U * s - N * d for s, d in prof]
    loop += [O + U * length - N * (depth + back), O - N * (depth + back)]
    a = [bm.verts.new(p) for p in loop]
    b = [bm.verts.new(p + E) for p in loop]
    k = len(loop)
    low = bm.faces.layers.int.get("uvlow") or bm.faces.layers.int.new("uvlow")
    for i in range(k):
        j = (i + 1) % k
        f = bm.faces.new((a[i], a[j], b[j], b[i]))
        if i >= k - 3:                 # the back face and the two ends: never seen
            f[low] = 1
    return P._end(0, name, group, None, uv_boost, smooth=False)


def slab(P, name, group, poly, origin, u, v, e, uv_boost=1.0, smooth=False):
    """Closed prism: 2D polygon [(a, b)] in the plane origin + u*a + v*b, extruded by vector e."""
    bm = P.bm
    O, U, V, E = Vector(origin), Vector(u), Vector(v), Vector(e)
    a = [bm.verts.new(O + U * x + V * y) for x, y in poly]
    b = [bm.verts.new(O + U * x + V * y + E) for x, y in poly]
    bm.faces.new(a)
    bm.faces.new(list(reversed(b)))
    k = len(poly)
    for i in range(k):
        j = (i + 1) % k
        bm.faces.new((a[j], a[i], b[i], b[j]))
    return P._end(0, name, group, None, uv_boost, smooth)


def beam(P, name, group, a, b, w, h=None, up=(0, 0, 1)):
    """Rectangular member (w x h section) from point a to point b."""
    a, b = Vector(a), Vector(b)
    h = w if h is None else h
    d = b - a
    t = d.normalized()
    upv = Vector(up)
    if abs(t.dot(upv)) > 0.95:
        upv = Vector((1, 0, 0))
    s = t.cross(upv).normalized()
    nrm = s.cross(t).normalized()
    poly = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return slab(P, name, group, poly, a, s, nrm, d)


# ------------------------------------------------------------------ ISO 40' container

@model
def m_container(P: Prop):
    L, W, H = 12.192, 2.438, 2.591
    cx, cy, cz = 0.178, 0.162, 0.118           # ISO corner casting
    hx, hy = L / 2, W / 2
    # corner castings (8), with a recess face for the oval apertures (decal)
    for sx in (-1, 1):
        for sy in (-1, 1):
            for k, z in enumerate((cz / 2, H - cz / 2)):
                P.box(f"casting_{'fd'[sx > 0]}{'rl'[sy > 0]}{k}", "paint2", (cx, cy, cz), loc=(sx * (hx - cx / 2), sy * (hy - cy / 2), z), bevel=0.008)
    # corner posts: front (closed end, -X) and the deeper door-end posts (+X)
    for sy in (-1, 1):
        P.box(f"post_front_{sy}", "paint", (0.15, 0.15, H - 2 * cz), loc=(-hx + 0.075, sy * (hy - 0.075), cz), base=True, bevel=0.006)
        P.box(f"post_door_{sy}", "paint", (0.2, 0.15, H - 2 * cz), loc=(hx - 0.1, sy * (hy - 0.075), cz), base=True, bevel=0.006)
    # side rails (top tube, bottom C-channel with its lip)
    rl = L - 2 * cx
    for sy in (-1, 1):
        P.box(f"top_rail_{sy}", "paint", (rl, 0.08, 0.11), loc=(0, sy * (hy - 0.04), H - 0.058), bevel=0.01)
        P.box(f"bottom_rail_{sy}", "paint", (rl, 0.07, 0.16), loc=(0, sy * (hy - 0.035), 0.095))
        P.box(f"bottom_lip_{sy}", "paint", (rl, 0.03, 0.03), loc=(0, sy * (hy - 0.012), 0.03))
    # front end: header, sill and a deep-corrugated end wall
    P.box("front_header", "paint", (0.12, W - 2 * cy, 0.12), loc=(-hx + 0.06, 0, H - 0.06), bevel=0.008)
    P.box("front_sill", "paint", (0.12, W - 2 * cy, 0.16), loc=(-hx + 0.06, 0, 0.095))
    corr_sheet(P, "front_wall", "paint", (-hx + 0.015, -(hy - 0.15), 0.175), (0, 1, 0), (-1, 0, 0), (0, 0, H - 0.29),
               W - 0.3, 0.33, 0.045)
    # side walls: 278 mm pitch, 36 mm deep trapezoidal corrugation between the posts
    x0, x1 = -hx + 0.15, hx - 0.2
    for sy in (-1, 1):
        o = (x0, sy * (hy - 0.012), 0.175)
        corr_sheet(P, f"side_wall_{'lr'[sy > 0]}", "paint", o, (1, 0, 0), (0, sy, 0), (0, 0, H - 0.29), x1 - x0, 0.278, 0.036)
    # roof: shallow transverse corrugation, slightly below the rails
    corr_sheet(P, "roof", "paint", (-hx + 0.13, -(hy - 0.06), H - 0.018), (1, 0, 0), (0, 0, 1), (0, W - 0.12, 0), L - 0.33, 0.46, 0.02)
    # underside: floor and cross members (black undercoat)
    P.box("floor", "iron", (L - 0.36, W - 0.14, 0.03), loc=(0, 0, 0.165), uv_boost=0.25)
    for k in range(13):
        x = -hx + 0.7 + k * (L - 1.4) / 12
        P.box(f"cross_member_{k}", "iron", (0.075, W - 0.14, 0.12), loc=(x, 0, 0.1), uv_boost=0.4)
    # ---- door end (+X)
    P.box("door_header", "paint", (0.2, W - 2 * cy, 0.24), loc=(hx - 0.1, 0, H - 0.12), bevel=0.01)
    P.box("door_sill", "paint", (0.2, W - 2 * cy, 0.15), loc=(hx - 0.1, 0, 0.095))
    dz0, dz1 = 0.17, H - 0.24
    dh = dz1 - dz0
    xo = hx - 0.004                                  # door frame face
    for side, sy in (("r", 1), ("l", -1)):
        ya, yb = 0.008, hy - 0.152                   # leaf from the centre gap to the post
        wl = yb - ya
        yc = sy * (ya + yb) / 2
        # leaf frame (top / bottom / sides) and the horizontally ribbed panel
        P.box(f"leaf_{side}_top", "paint", (0.045, wl, 0.08), loc=(xo - 0.0225, yc, dz1 - 0.04))
        P.box(f"leaf_{side}_bottom", "paint", (0.045, wl, 0.1), loc=(xo - 0.0225, yc, dz0 + 0.05))
        P.box(f"leaf_{side}_inner", "paint", (0.045, 0.07, dh - 0.18), loc=(xo - 0.0225, sy * (ya + 0.035), dz0 + 0.1), base=True)
        P.box(f"leaf_{side}_outer", "paint", (0.045, 0.07, dh - 0.18), loc=(xo - 0.0225, sy * (yb - 0.035), dz0 + 0.1), base=True)
        corr_sheet(P, f"door_{side}", "paint", (xo - 0.012, sy * (ya + 0.07) if sy < 0 else ya + 0.07, dz0 + 0.1), (0, 0, 1), (1, 0, 0),
                   (0, wl - 0.14, 0) if sy > 0 else (0, -(wl - 0.14), 0), dh - 0.18, 0.4, 0.03)
        # two lock rods per leaf, with guides, cams + keepers and a handle
        for k, f in enumerate((0.27, 0.73)):
            y = sy * (ya + wl * f)
            xr = xo + 0.032
            P.cyl(f"lock_rod_{side}{k}", "galv", 0.0135, H - 0.32, loc=(xr, y, 0.14), segs=8)
            for z in (0.55, 1.45, 2.05):
                P.box(f"rod_guide_{side}{k}_{z}", "galv", (0.05, 0.06, 0.035), loc=(xo + 0.012, y, z))
            for z, nm in ((0.12, "lo"), (H - 0.19, "hi")):
                P.box(f"cam_keeper_{side}{k}{nm}", "galv", (0.06, 0.08, 0.06), loc=(xo + 0.03, y, z))
            # handle: hub on the rod, lever towards the leaf centre, retainer catch
            hz = 1.12 + 0.06 * k
            dirn = -1 if f > 0.5 else 1
            P.box(f"handle_hub_{side}{k}", "galv", (0.05, 0.05, 0.09), loc=(xr, y, hz))
            P.sweep(f"handle_{side}{k}", "galv", [(xr, y, hz), (xr + 0.035, y + sy * dirn * 0.1, hz), (xr + 0.035, y + sy * dirn * 0.32, hz - 0.02)], 0.011, segs=6)
            P.box(f"retainer_{side}{k}", "galv", (0.04, 0.05, 0.08), loc=(xo + 0.02, y + sy * dirn * 0.34, hz - 0.02), bevel=0.005)
        # hinges on the outer edge of each leaf
        for z in (0.42, 1.0, 1.6, 2.15):
            yh = sy * (yb + 0.035)
            P.cyl(f"hinge_pin_{side}_{z}", "galv", 0.022, 0.11, loc=(xo + 0.02, yh, z - 0.055), segs=10)
            P.box(f"hinge_blade_{side}_{z}", "paint", (0.016, 0.16, 0.07), loc=(xo + 0.008, sy * (yb - 0.05), z))
    P.box("door_gasket", "rubber", (0.03, 0.016, dh), loc=(xo - 0.02, 0, dz0), base=True)
    P.box("csc_plate", "sign", (0.006, 0.26, 0.17), loc=(xo + 0.001, -0.55, 1.62), uv_boost=4.0)
    P.box("customs_plate", "sign2", (0.006, 0.2, 0.08), loc=(xo + 0.001, -0.55, 1.43), uv_boost=4.0)
    P.collider = [("box", (0, 0, H / 2), (L, W, H))]


# ------------------------------------------------------------------ ship-to-shore gantry crane

@model
def m_crane_sts(P: Prop):
    XL, YW = 14.0, 9.0                 # leg positions: x = +-14 (along the quay), y = +-9 (rail gauge 18 m)
    ZG = 43.0                          # underside of the girders
    # ---- travel gear: sill beams, equalisers, bogies, wheels, buffers
    for sy in (-1, 1):
        y = sy * YW
        P.box(f"sill_beam_{sy}", "paint", (2 * XL + 3.2, 1.7, 1.6), loc=(0, y, 2.7), bevel=0.06)
        for sx in (-1, 1):
            x = sx * XL
            P.box(f"equaliser_{sx}{sy}", "paint", (4.6, 1.1, 0.8), loc=(x, y, 1.55), bevel=0.04)
            for kb, bx in enumerate((-1.15, 1.15)):
                P.box(f"bogie_{sx}{sy}{kb}", "dark_metal", (2.0, 0.9, 0.75), loc=(x + bx, y, 0.85), bevel=0.04)
                for kw, wx in enumerate((-0.5, 0.5)):
                    P.cyl(f"wheel_{sx}{sy}{kb}{kw}", "steel", 0.36, 0.22, loc=(x + bx + wx, y, 0.36), rot=(90, 0, 0), center=True, segs=16)
            P.cyl(f"buffer_{sx}{sy}", "hazard", 0.32, 0.9, loc=(sx * (XL + 1.6), y, 2.6), rot=(0, 90 * sx, 0), segs=14)
    # ---- legs: tapered box sections (square, 45 deg turned cylinders), hazard collars
    for sy in (-1, 1):
        for sx in (-1, 1):
            P.cyl(f"leg_{sx}{sy}", "paint", 1.05, ZG - 3.5, loc=(sx * XL, sy * YW, 3.5), rot=(0, 0, 45), segs=4, r2=0.8, bevel=0.04)
            P.cyl(f"leg_collar_{sx}{sy}", "hazard", 1.13, 2.4, loc=(sx * XL, sy * YW, 3.5), rot=(0, 0, 45), segs=4, r2=1.1)
    # portal beams along X (on top of the legs) and the ties / braces between land and water legs
    for sy in (-1, 1):
        P.box(f"portal_{sy}", "paint", (2 * XL + 2.0, 1.8, 2.4), loc=(0, sy * YW, ZG - 1.2), bevel=0.05)
    for sx in (-1, 1):
        x = sx * XL
        P.box(f"portal_tie_{sx}", "paint", (1.1, 2 * YW - 1.4, 1.3), loc=(x, 0, 31.0), bevel=0.04)
        beam(P, f"brace_a_{sx}", "paint", (x, -YW + 0.6, 7.0), (x, YW - 0.6, 30.3), 0.55)
        beam(P, f"brace_b_{sx}", "paint", (x, YW - 0.6, 7.0), (x, -YW + 0.6, 30.3), 0.55)
    # ---- girders: two box girders, fixed back reach + boom tapering to the tip over the water
    yb, yt = -28.0, 64.0
    prof = [(yb, 0.0), (yt, 0.0), (yt, 1.6), (yt - 14.0, 3.0), (yb + 4.0, 3.0), (yb, 2.2)]
    for sx in (-1, 1):
        slab(P, f"girder_{sx}", "paint", prof, (sx * 2.4 - 0.65, 0, ZG), (0, 1, 0), (0, 0, 1), (1.3, 0, 0))
        P.box(f"trolley_rail_{sx}", "steel", (0.16, yt - yb - 1.0, 0.18), loc=(sx * 2.1, (yb + yt) / 2, ZG + 3.09))
        # walkways with a handrail (posts + rails as one swept line)
        xw = sx * 3.45
        P.box(f"walkway_{sx}", "grate", (0.9, yt - yb - 3.0, 0.06), loc=(xw, (yb + yt) / 2 - 1.0, ZG + 0.2))
        xr = xw + sx * 0.42
        P.sweep(f"handrail_top_{sx}", "hazard", [(xr, yb + 1.0, ZG + 1.3), (xr, yt - 3.0, ZG + 1.3)], 0.03, segs=6)
        P.sweep(f"handrail_mid_{sx}", "hazard", [(xr, yb + 1.0, ZG + 0.8), (xr, yt - 3.0, ZG + 0.8)], 0.022, segs=6)
        for k in range(19):
            P.cyl(f"rail_post_{sx}_{k}", "hazard", 0.025, 1.08, loc=(xr, yb + 1.0 + k * (yt - yb - 4.0) / 18, ZG + 0.23), segs=6)
    for k, y in enumerate(range(-26, 64, 6)):
        P.box(f"girder_tie_{k}", "paint", (3.5, 0.5, 0.45), loc=(0, y, ZG + 0.25))
    # ---- A-frame over the water-side legs, forestays to the boom, backstays to the back reach
    apex_z = 68.0
    for sx in (-1, 1):
        x = sx * 2.4
        beam(P, f"aframe_front_{sx}", "paint", (sx * 3.0, YW + 1.0, ZG + 3.0), (x, 5.0, apex_z), 0.9)
        beam(P, f"aframe_back_{sx}", "paint", (sx * 3.0, -4.0, ZG + 3.0), (x, 4.0, apex_z), 0.9)
        P.sweep(f"forestay_a_{sx}", "steel", [(x, 5.4, apex_z - 0.3), (x, 38.0, ZG + 3.0)], 0.16, segs=8)
        P.sweep(f"forestay_b_{sx}", "steel", [(x, 5.4, apex_z - 0.6), (x, 58.0, ZG + 2.4)], 0.16, segs=8)
        P.sweep(f"backstay_{sx}", "steel", [(x, 3.6, apex_z - 0.3), (x, -26.5, ZG + 2.6)], 0.2, segs=8)
    P.box("apex_head", "paint", (5.8, 2.2, 1.6), loc=(0, 4.6, apex_z + 0.2), bevel=0.06)
    P.cyl("boom_hoist_sheave", "dark_metal", 0.9, 4.2, loc=(0, 4.6, apex_z - 0.9), rot=(0, 90, 0), center=True, segs=16)
    P.cyl("beacon_apex", "beacon_red", 0.22, 0.3, loc=(0, 4.6, apex_z + 1.0), segs=10)
    P.cyl("beacon_tip", "beacon_red", 0.2, 0.3, loc=(0, yt - 0.6, ZG + 1.6), segs=10)
    P.light("Light_Beacon", (0, 4.6, apex_z + 1.3), color=(1.0, 0.05, 0.02), energy=30, range=40)
    # ---- machinery house on the back reach, with louvres, doors, the E-room and banner panels
    mz = ZG + 3.0
    P.box("machinery_house", "paint2", (11.0, 12.0, 6.0), loc=(0, -19.5, mz), base=True, bevel=0.12)
    P.box("machinery_roof", "dark_metal", (11.6, 12.6, 0.35), loc=(0, -19.5, mz + 6.0), base=True, bevel=0.06)
    P.box("e_room", "paint2", (6.0, 5.0, 3.0), loc=(0, -19.5, mz + 6.35), base=True, bevel=0.08)
    for sx in (-1, 1):
        P.box(f"house_banner_{sx}", "sign", (0.08, 10.4, 3.2), loc=(sx * 5.54, -19.5, mz + 1.6), base=True, uv_boost=6.0)
        P.box(f"louvre_{sx}", "grille", (0.06, 3.0, 1.2), loc=(sx * 5.53, -24.6, mz + 4.6), uv_boost=2.0)
    P.box("house_door", "dark_metal", (1.1, 0.08, 2.2), loc=(3.5, -13.47, mz), base=True)
    P.box("house_number", "sign2", (3.4, 0.08, 1.8), loc=(-1.8, -13.47, mz + 3.4), base=True, uv_boost=6.0)
    # ---- trolley, operator cab with glazing, hoist ropes, headblock and spreader
    ty = 30.0
    P.box("trolley", "paint2", (6.2, 5.0, 2.2), loc=(0, ty, ZG + 3.25), base=True, bevel=0.08)
    P.box("cab", "paint2", (2.6, 3.0, 2.7), loc=(-1.9, ty + 0.6, ZG - 2.9), base=True, bevel=0.1)
    P.box("cab_glass_front", "smoke_glass", (2.3, 0.06, 1.7), loc=(-1.9, ty + 2.12, ZG - 2.3), base=True)
    P.box("cab_glass_floor", "smoke_glass", (1.8, 1.6, 0.06), loc=(-1.9, ty + 1.3, ZG - 2.94), base=True)
    P.box("cab_hanger", "dark_metal", (0.6, 0.6, 2.4), loc=(-1.9, ty + 0.6, ZG - 0.2), base=True)
    for sx in (-1, 1):
        for sy in (-1, 1):
            P.cyl(f"hoist_rope_{sx}{sy}", "cable", 0.035, ZG + 3.2 - 21.0, loc=(sx * 0.9, ty + sy * 0.6, 21.0), segs=6)
    P.box("headblock", "paint2", (3.2, 2.2, 0.8), loc=(0, ty, 20.2), base=True, bevel=0.05)
    P.box("spreader", "hazard", (12.2, 2.3, 0.55), loc=(0, ty, 19.5), base=True, bevel=0.04)
    for sx in (-1, 1):
        for sy in (-1, 1):
            P.box(f"twistlock_{sx}{sy}", "dark_metal", (0.3, 0.3, 0.35), loc=(sx * 5.95, ty + sy * 1.0, 19.2), base=True)
    # boom floodlights (lit faces down)
    for k, y in enumerate((-8.0, 12.0, 26.0, 44.0, 58.0)):
        for sx in (-1, 1):
            P.box(f"flood_{k}{sx}", "dark_metal", (0.6, 0.45, 0.3), loc=(sx * 3.3, y, ZG - 0.4))
            P.box(f"flood_lens_{k}{sx}", "bulb", (0.5, 0.35, 0.04), loc=(sx * 3.3, y, ZG - 0.57))
    P.light("Light_Boom", (0, 26.0, ZG - 1.0), kind="spot", color=(1.0, 0.85, 0.65), energy=900, range=55, dir=(0, 0, -1))
    # ---- access stairs up the land-side leg (zig-zag stringer + landings) and the cable reel
    sx0, sy0 = XL + 1.6, -YW
    pts = [(sx0, sy0 - 1.2, 4.2)]
    for k in range(8):
        z0, z1 = 4.2 + k * 4.7, 4.2 + (k + 1) * 4.7
        a, b = (sy0 - 1.2, sy0 + 1.2) if k % 2 == 0 else (sy0 + 1.2, sy0 - 1.2)
        pts.append((sx0, b, z1))
        P.box(f"landing_{k}", "grate", (1.3, 1.0, 0.08), loc=(sx0, b + (0.5 if k % 2 == 0 else -0.5), z1 - 0.08), base=True)
    P.sweep("stair_stringer", "hazard", pts, 0.07, segs=6)
    P.cyl("cable_reel", "dark_metal", 2.1, 1.3, loc=(-XL - 1.0, -YW - 1.8, 3.6), rot=(90, 0, 0), center=True, segs=24)
    P.cyl("cable_reel_hub", "paint", 0.7, 1.5, loc=(-XL - 1.0, -YW - 1.8, 3.6), rot=(90, 0, 0), center=True, segs=12)
    P.collider = [("box", (0, sy * YW, 2.0), (2 * XL + 3.2, 1.8, 4.0)) for sy in (-1, 1)] + \
                 [("box", (sx * XL, sy * YW, (ZG + 3.5) / 2), (1.6, 1.6, ZG - 3.5)) for sx in (-1, 1) for sy in (-1, 1)] + \
                 [("box", (0, 18.0, ZG + 1.5), (6.0, 92.0, 3.0)), ("box", (0, -19.5, ZG + 6.0), (11.0, 12.0, 6.0))]


# ------------------------------------------------------------------ yard high mast

@model
def m_light_mast(P: Prop):
    # foundation, base plate, anchor bolts and gussets
    P.box("plinth", "concrete", (1.9, 1.9, 0.32), loc=(0, 0, 0), base=True, bevel=0.04, seg=2)
    P.cyl("base_plate", "galv", 0.58, 0.05, loc=(0, 0, 0.32), segs=24, bevel=0.01)
    for k in range(8):
        a = math.radians(22.5 + 45 * k)
        x, y = math.cos(a) * 0.48, math.sin(a) * 0.48
        P.cyl(f"anchor_{k}", "galv", 0.022, 0.13, loc=(x, y, 0.33), segs=8)
        P.cyl(f"nut_{k}", "galv", 0.045, 0.045, loc=(x, y, 0.37), segs=6)
        a2 = math.radians(45 * k)
        c, s = math.cos(a2), math.sin(a2)
        tri = [(0.36, 0.0), (0.56, 0.0), (0.36, 0.42)]
        slab(P, f"gusset_{k}", "galv", tri, (-s * 0.008, c * 0.008, 0.37), (c, s, 0), (0, 0, 1), (s * 0.016, -c * 0.016, 0))
    # hazard sleeve, three galvanised shaft sections with slip joints
    P.lathe("bumper_sleeve", "hazard", [(0.43, 0.37), (0.43, 1.6), (0.0, 1.6)], segs=16)
    secs = [(0.37, 0.39, 0.30, 11.0), (10.5, 0.315, 0.235, 21.0), (20.5, 0.245, 0.165, 29.3)]
    for k, (z0, r0, r1, z1) in enumerate(secs):
        P.cyl(f"shaft_{k}", "galv", r0, z1 - z0, loc=(0, 0, z0), r2=r1, segs=16)
        if k:
            P.cyl(f"slip_joint_{k}", "galv", r0 + 0.02, 0.18, loc=(0, 0, z0 + 0.05), segs=16)
    # access door with frame, lock and the mast plate
    P.box("door_frame", "galv", (0.34, 0.06, 0.72), loc=(0, -0.38, 2.0), base=True, bevel=0.01)
    P.box("door", "galv", (0.28, 0.05, 0.64), loc=(0, -0.41, 2.04), base=True, bevel=0.008)
    P.cyl("door_lock", "dark_metal", 0.025, 0.03, loc=(0.09, -0.435, 2.36), rot=(90, 0, 0), segs=10)
    P.box("mast_plate", "sign", (0.32, 0.01, 0.42), loc=(0, -0.375, 3.1), base=True, rot=(4, 0, 0), uv_boost=4.0)
    # base cabinet on the plinth
    P.box("cabinet", "paint", (0.55, 0.3, 0.95), loc=(0.6, 0.62, 0.32), base=True, bevel=0.02)
    P.box("cabinet_roof", "paint", (0.62, 0.38, 0.04), loc=(0.6, 0.62, 1.27), base=True, rot=(6, 0, 0), bevel=0.01)
    P.box("cabinet_label", "sign2", (0.3, 0.008, 0.18), loc=(0.6, 0.467, 0.95), base=True, uv_boost=4.0)
    P.sweep("conduit", "dark_metal", [(0.6, 0.62, 0.36), (0.6, 0.62, 0.34), (0.25, 0.2, 0.34), (0.0, 0.0, 0.34)], 0.03, segs=8)
    # head frame: lowering ring, spokes, floods, cap, lightning rod and aviation light
    zr = 29.6
    P.torus("ring_outer", "galv", 1.55, 0.06, loc=(0, 0, zr), segs=32, rsegs=6)
    P.torus("ring_inner", "galv", 0.36, 0.07, loc=(0, 0, zr), segs=16, rsegs=6)
    for k in range(8):
        a = math.radians(45 * k)
        c, s = math.cos(a), math.sin(a)
        P.sweep(f"spoke_{k}", "galv", [(c * 0.36, s * 0.36, zr), (c * 1.55, s * 1.55, zr)], 0.035, segs=5)
        # flood: yoke + housing tilted out and down; lit glass faces down / out
        ap = math.radians(45 * k + 22.5)
        ca, sa = math.cos(ap), math.sin(ap)
        rx, ry = ca * 1.55, sa * 1.55
        deg = math.degrees(ap)
        P.sweep(f"yoke_{k}", "dark_metal", [(rx, ry, zr), (rx + ca * 0.1, ry + sa * 0.1, zr - 0.22)], 0.025, segs=5)
        c0 = Vector((rx + ca * 0.25, ry + sa * 0.25, zr - 0.3))
        R = Euler((0, math.radians(-40), ap), "XYZ").to_matrix()
        P.box(f"flood_{k}", "paint", (0.62, 0.5, 0.16), loc=c0, rot=(0, -40, deg), bevel=0.02)
        P.box(f"flood_glass_{k}", "bulb", (0.54, 0.44, 0.02), loc=c0 + R @ Vector((0, 0, -0.085)), rot=(0, -40, deg))
    P.lathe("head_cap", "galv", [(0.2, 29.25), (0.42, 29.75), (0.42, 29.95), (0.12, 30.25), (0.0, 30.3)], segs=16)
    P.cyl("lightning_rod", "copper", 0.012, 1.6, loc=(0.15, 0, 30.1), segs=6)
    P.cyl("beacon", "beacon_red", 0.09, 0.16, loc=(-0.12, 0, 30.28), segs=12)
    P.light("Light_Flood", (0, 0, zr - 0.5), kind="spot", color=(1.0, 0.8, 0.55), energy=2600, range=60, dir=(0, 0, -1))
    P.light("Light_Beacon", (-0.12, 0, 30.5), color=(1.0, 0.05, 0.02), energy=6, range=12)
    P.collider = [("box", (0, 0, 0.16), (1.9, 1.9, 0.32)), ("cyl", (0, 0), 0.43, 29.6, 0.32)]
