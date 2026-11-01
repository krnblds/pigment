"""Signs, clutter, food stalls, rooftop gear, nature-lite and decals.  Blender axes: Z up, front faces -Y."""
import math
import random

from proplib import Prop

MODELS = {}


def model(fn):
    MODELS[fn.__name__[2:]] = fn
    return fn


def arc_pts(cx, cz, r, a0, a1, n):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cz + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


# ------------------------------------------------------------------ signs / emissive

@model
def m_holo_pylon(P: Prop):
    W, H = 0.9, 3.0
    a = W / (2 * math.tan(math.radians(60)))      # apothem
    R = W / math.sqrt(3)                             # circumradius
    tri = [(R * math.cos(math.radians(-90 + 120 * i + 60)), R * math.sin(math.radians(-90 + 120 * i + 60))) for i in range(3)]
    big = [(x * 1.45, -y * 1.45) for x, y in tri]      # prism rot (90, 0, 0) maps profile (x, z) -> world (x, -z)
    P.prism("plinth", "dark_metal", big, 0.45, loc=(0, 0, 0.225), rot=(90, 0, 0), bevel=0.02)
    P.prism("plinth_led", "led", [(x * 1.47, -y * 1.47) for x, y in tri], 0.03, loc=(0, 0, 0.38), rot=(90, 0, 0))
    P.prism("cap", "dark_metal", [(x * 1.2, -y * 1.2) for x, y in tri], 0.16, loc=(0, 0, 0.45 + H + 0.08), rot=(90, 0, 0), bevel=0.015)
    P.prism("cap_led", "led", [(x * 1.22, -y * 1.22) for x, y in tri], 0.02, loc=(0, 0, 0.45 + H + 0.005), rot=(90, 0, 0))
    P.cyl("core", "dark_metal", 0.06, H, loc=(0, 0, 0.45), segs=12)
    for i in range(3):
        yaw = 120 * i
        nx, ny = math.sin(math.radians(yaw)) * -1, -math.cos(math.radians(yaw))
        # panel i faces (nx, ny): rotate a -Y facing panel by yaw about Z
        P.box(f"holo_{i}", "holo", (W - 0.04, 0.012, H), loc=(nx * a, ny * a, 0.45), rot=(0, 0, -yaw), base=True, uv_boost=2.2)
        P.box(f"emitter_{i}", "led", (W - 0.1, 0.05, 0.03), loc=(nx * (a + 0.02), ny * (a + 0.02), 0.46), rot=(0, 0, -yaw))
    for i, (x, y) in enumerate(tri):
        P.cyl(f"edge_{i}", "steel", 0.025, H, loc=(x, y, 0.45), segs=10)
    P.light("Light_Holo", (0, 0, 2.0), color=(0.6, 0.4, 1.0), energy=60, range=7.0)
    P.collider = [("cyl", (0, 0), 0.75, H + 0.6)]


@model
def m_neon_arrow_sign(P: Prop):
    # blade sign perpendicular to the wall (wall = the y = 0 plane, the sign sticks out to -Y)
    up = 0.35
    outline = [(-0.25, 2.4), (-1.05, 2.4), (-1.05, 0.3), (-1.22, 0.3), (-0.64, -0.25), (-0.08, 0.3), (-0.25, 0.3)]
    outline = [(u, v + up) for u, v in outline]
    P.prism("body", "paint", outline, 0.2, rot=(0, 0, 90), bevel=0.012)
    # profile x -> world y after the 90 deg turn (prism extrudes along local y -> world -x)
    for s, side in ((1, "r"), (-1, "l")):
        x = 0.1 * s + 0.012 * s
        loop = [(x, u * 1.0, v) for (u, v) in outline]
        inset = []
        for (xx, yy, zz) in loop:
            cy, cz = -0.65, 1.2 + up
            inset.append((xx, cy + (yy - cy) * 0.93, cz + (zz - cz) * 0.95))
        P.sweep(f"neon_{side}", "neon", inset + [inset[0]], 0.012, segs=6, closed=False, caps=True)
        P.box(f"panel_{side}", "sign_lit", (0.01, 0.62, 1.8), loc=(x - 0.006 * s, -0.65, 0.42 + up), base=True, uv_boost=2.4)
        # chase bulbs along the arrowhead
        head = [(-1.18, 0.33 + up), (-0.64, -0.2 + up), (-0.12, 0.33 + up)]
        k = 0
        for (u0, v0), (u1, v1) in zip(head, head[1:]):
            for t in (0.12, 0.37, 0.62, 0.87):
                P.blob(f"bulb_{side}_{k}", "bulb", 0.022, loc=(x + 0.01 * s, u0 + (u1 - u0) * t, v0 + (v1 - v0) * t), subdiv=1, noise=0.0)
                k += 1
    for i, z in enumerate((0.55 + up, 2.2 + up)):
        P.box(f"bracket_{i}", "dark_metal", (0.05, 0.28, 0.05), loc=(0, -0.13, z), bevel=0.005)
        P.box(f"wall_plate_{i}", "dark_metal", (0.16, 0.012, 0.2), loc=(0, -0.006, z), bevel=0.003)
    P.light("Light_Sign", (0, -0.65, 1.3 + up), color=(1.0, 0.3, 0.6), energy=25, range=5.0)
    P.collider = "none"


@model
def m_vending_machine(P: Prop):
    W, D, H = 1.0, 0.75, 1.85
    P.box("plinth", "dark_metal", (W - 0.04, D - 0.04, 0.08), loc=(0, 0, 0), base=True)
    P.box("body", "paint", (W, D, H - 0.08), loc=(0, 0, 0.08), base=True, bevel=0.025, seg=2)
    fy = -D / 2
    P.box("window_frame", "dark_metal", (0.66, 0.025, 1.12), loc=(-0.13, fy - 0.006, 0.55), base=True, bevel=0.008)
    P.box("products", "ad", (0.6, 0.01, 1.04), loc=(-0.13, fy - 0.012, 0.59), base=True, uv_boost=2.3)
    P.box("window_glass", "glass", (0.62, 0.008, 1.06), loc=(-0.13, fy - 0.026, 0.58), base=True)
    P.box("buttons", "led", (0.6, 0.02, 0.05), loc=(-0.13, fy - 0.012, 0.5), base=True, uv_boost=2.0)
    P.box("header", "sign_lit", (0.94, 0.02, 0.17), loc=(0, fy - 0.006, 1.66), base=True, uv_boost=2.4)
    P.box("pay_panel", "dark_plastic", (0.24, 0.03, 0.52), loc=(0.35, fy - 0.01, 0.95), base=True, bevel=0.006)
    P.box("pay_screen", "screen", (0.18, 0.01, 0.13), loc=(0.35, fy - 0.026, 1.3), base=True, uv_boost=3.0)
    P.box("card_reader", "led", (0.12, 0.012, 0.08), loc=(0.35, fy - 0.026, 1.12), base=True, uv_boost=2.0)
    P.box("coin_return", "steel", (0.1, 0.02, 0.06), loc=(0.35, fy - 0.02, 1.0), base=True)
    P.box("flap", "dark_plastic", (0.62, 0.04, 0.2), loc=(-0.05, fy - 0.01, 0.16), base=True, bevel=0.01)
    P.box("flap_label", "sign", (0.3, 0.006, 0.05), loc=(-0.05, fy - 0.032, 0.27), base=True, uv_boost=3.0)
    P.box("side_wrap", "ad2", (0.01, D - 0.1, H - 0.4), loc=(W / 2 + 0.003, 0, 0.25), base=True, uv_boost=1.4)
    P.box("vent", "dark_metal", (0.4, 0.015, 0.08), loc=(-0.13, fy - 0.005, 0.1), base=True)
    P.light("Light_Front", (0, -0.9, 1.1), color=(0.75, 0.9, 1.0), energy=25, range=3.5)
    P.collider = [("box", (0, 0, H / 2), (W, D, H))]


# ------------------------------------------------------------------ clutter

def sack(P: Prop, name, group, base, r, h, lean=(0.0, 0.0), squash=1.0, seed=0, ni=18, nj=12):
    """A tied rubbish bag: slumped, flat-bottomed sack with lumps from what's inside, pleats
    gathered into the neck, the neck twisted shut and two tie ears.  base = (x, y, z) of the
    bottom centre; lean shifts the top (metres); squash < 1 flattens bags lower in a pile."""
    import random
    from mathutils import Vector
    rnd = random.Random(seed)
    bm = P.bm
    lumps = [(rnd.randint(1, 3), rnd.uniform(0, math.tau), rnd.uniform(0.03, 0.08), rnd.uniform(1.5, 3.5), rnd.uniform(0, math.tau)) for _ in range(4)]
    ph = rnd.uniform(0, math.tau)
    hb = h * squash
    rows = []
    for j in range(nj + 1):
        t = j / nj * 0.9
        if t < 0.3:
            prof = 0.72 + 0.33 * math.sin(t / 0.3 * math.pi / 2)
        else:
            prof = 1.05 * math.sqrt(max(0.0, 1 - ((t - 0.3) / 0.68) ** 2)) + 0.08
        prof /= (squash ** 0.35)
        pleat = max(0.0, min(1.0, (t - 0.5) / 0.35))
        z = hb * (t if t > 0.02 else 0.0)
        row = []
        for i in range(ni):
            a = math.tau * i / ni
            d = 1.0 + sum(amp * math.sin(k * a + p0) * math.sin(f * t * math.pi + p1) for k, p0, amp, f, p1 in lumps)
            d += 0.09 * pleat * math.sin(9 * a + ph)
            rr = r * prof * d
            sh = (t / 0.9) ** 1.5
            row.append(bm.verts.new((base[0] + rr * math.cos(a) + lean[0] * sh, base[1] + rr * math.sin(a) * 0.93 + lean[1] * sh, base[2] + z)))
        rows.append(row)
    # twisted neck to the knot
    top = Vector((base[0] + lean[0], base[1] + lean[1], base[2] + hb * 0.9))
    for k, (f, dz) in enumerate(((0.45, 0.02), (0.24, 0.045), (0.17, 0.07), (0.21, 0.09))):
        row = []
        rr = rows[-1]
        cx = sum((v.co for v in rr), Vector()) / len(rr)
        for i in range(ni):
            a = math.tau * i / ni + 0.5 * (k + 1)
            row.append(bm.verts.new((cx.x + r * 0.42 * f * math.cos(a), cx.y + r * 0.42 * f * math.sin(a), top.z + dz)))
        rows.append(row)
    for a_, b_ in zip(rows, rows[1:]):
        for i in range(ni):
            k = (i + 1) % ni
            bm.faces.new((a_[i], a_[k], b_[k], b_[i]))
    bm.faces.new(list(reversed(rows[0])))
    bm.faces.new(rows[-1])
    P._end(0, name, group)
    # tie ears
    knot = sum((v.co for v in rows[-1]), Vector()) / ni
    for e, sgn in enumerate((-1, 1)):
        ang = rnd.uniform(-0.6, 0.6) + (0 if sgn > 0 else math.pi)
        dvec = Vector((math.cos(ang), math.sin(ang), 0))
        pts = [knot + dvec * 0.01, knot + dvec * 0.04 + Vector((0, 0, 0.022)), knot + dvec * 0.075 + Vector((0, 0, 0.008)), knot + dvec * 0.095 + Vector((0, 0, -0.025))]
        P.ribbon(f"{name}_ear{e}", group, [tuple(p) for p in pts], [0.025, 0.042, 0.036, 0.016], (-dvec.y, dvec.x, 0.3), fold=0.4, thickness=0.004, cols=2)


@model
def m_trash_bag_pile(P: Prop):
    # five tied bags slumped against each other, a burnable-day sticker and a MERIDIAN waste tag on
    # them, a crushed can, a takeaway cup and a flattened box under the pile (same footprint and collider)
    bags = [((-0.24, 0.08, 0.0), 0.3, 0.62, (0.04, 0.05), 0.85, "bag", 3),
            ((0.26, 0.12, 0.0), 0.28, 0.58, (-0.06, 0.03), 0.9, "bag_blue", 7),
            ((0.02, -0.2, 0.0), 0.25, 0.52, (0.02, -0.04), 0.95, "bag", 11),
            ((0.03, 0.1, 0.24), 0.21, 0.42, (0.05, -0.02), 1.0, "bag_white", 19),
            ((-0.42, -0.22, 0.0), 0.17, 0.36, (0.06, 0.02), 1.0, "bag", 23)]
    for i, (c, r, h, lean, sq, grp, seed) in enumerate(bags):
        sack(P, f"bag_{i}", grp, c, r, h, lean, sq, seed)
    P.box("sticker_burnable", "sign", (0.1, 0.002, 0.07), loc=(0.02, -0.455, 0.25), rot=(-8, 0, 0), uv_boost=4.0)
    P.box("waste_tag", "sign2", (0.08, 0.002, 0.11), loc=(0.29, -0.155, 0.27), rot=(-12, 0, 18), uv_boost=4.0)
    P.box("flat_box", "cardboard", (0.62, 0.42, 0.012), loc=(0.15, -0.05, 0.0), rot=(0, 0, 12), base=True)
    P.cyl("can", "steel", 0.033, 0.075, loc=(0.47, -0.24, 0.033), rot=(90, 0, 35), segs=10, r2=0.029)
    P.cyl("cup", "white_plastic", 0.042, 0.12, loc=(-0.62, 0.16, 0.042), rot=(0, 90, 20), segs=12, r2=0.032)
    P.cyl("cup_lid", "dark_plastic", 0.046, 0.012, loc=(-0.62 + 0.12 * math.cos(math.radians(20)), 0.16 + 0.12 * math.sin(math.radians(20)), 0.042),
          rot=(0, 90, 20), segs=12)
    P.collider = [("box", (0, -0.02, 0.36), (1.15, 0.85, 0.72))]


@model
def m_trash_bin(P: Prop):
    W, D, H = 0.84, 0.44, 0.98
    P.box("body", "paint", (W, D, H), loc=(0, 0, 0.04), base=True, bevel=0.035, seg=3)
    P.box("lid", "paint2", (W + 0.03, D + 0.03, 0.06), loc=(0, 0, H + 0.02), base=True, bevel=0.02, seg=2)
    for i, x in enumerate((-0.2, 0.2)):
        P.box(f"foot_{i}", "dark_plastic", (0.3, D - 0.04, 0.04), loc=(x, 0, 0), base=True)
    P.cyl("hole_cans", "hole", 0.075, 0.01, loc=(-0.2, -D / 2 - 0.002, 0.82), rot=(90, 0, 0), segs=20)
    P.box("hole_burn", "hole", (0.24, 0.01, 0.09), loc=(0.2, -D / 2 - 0.006, 0.82))
    P.box("label_cans", "sign", (0.34, 0.006, 0.2), loc=(-0.2, -D / 2 - 0.004, 0.56), uv_boost=3.0)
    P.box("label_burn", "sign2", (0.34, 0.006, 0.2), loc=(0.2, -D / 2 - 0.004, 0.56), uv_boost=3.0)
    P.box("divider", "paint2", (0.02, 0.008, 0.85), loc=(0, -D / 2 - 0.003, 0.1), base=True)
    P.collider = [("box", (0, 0, 0.53), (W + 0.03, D + 0.03, 1.06))]


@model
def m_cardboard_boxes(P: Prop):
    def cbox(tag, size, loc, yaw, flaps=False, tape=True, label=True):
        P.box(f"box_{tag}", "cardboard", size, loc=loc, rot=(0, 0, yaw), base=True, bevel=0.006)
        top = loc[2] + size[2]
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        if tape:
            P.box(f"tape_{tag}", "tape", (size[0] + 0.004, 0.05, 0.003), loc=(loc[0], loc[1], top), rot=(0, 0, yaw), base=True)
        if label:
            # label on the box's front (-Y) face
            ox, oy = s * (size[1] / 2 + 0.002), -c * (size[1] / 2 + 0.002)
            P.box(f"label_{tag}", "sign", (size[0] * 0.5, 0.004, size[2] * 0.4), loc=(loc[0] + ox, loc[1] + oy, loc[2] + size[2] * 0.3),
                  rot=(0, 0, yaw), base=True, uv_boost=2.5)
        if flaps:
            fw, fd = size[0], size[1]
            for k, (dx, dy, ln, rx, ry) in enumerate(((0, -fd / 2, fd / 2, 1, 0), (0, fd / 2, fd / 2, -1, 0))):
                P.box(f"flap_{tag}_{k}", "cardboard", (fw, ln, 0.006), loc=(loc[0] + dx, loc[1] + dy + (-ln / 2 if dy < 0 else ln / 2) * 0.7, top + 0.12),
                      rot=(35 * (1 if dy > 0 else -1), 0, yaw))
    cbox("a", (0.62, 0.46, 0.42), (-0.12, 0.05, 0.0), 0)
    cbox("b", (0.5, 0.4, 0.34), (-0.08, 0.08, 0.42), 11)
    cbox("c", (0.42, 0.36, 0.3), (0.42, -0.06, 0.0), -18, flaps=True, tape=False)
    P.collider = [("box", (0.05, 0.0, 0.38), (1.15, 0.7, 0.76))]


@model
def m_pallet(P: Prop):
    L, Wd = 1.2, 0.8
    for i, y in enumerate((-0.35, 0.0, 0.35)):
        P.box(f"bottom_{i}", "wood", (L, 0.1, 0.022), loc=(0, y, 0), base=True, bevel=0.003)
        for j, x in enumerate((-0.5, 0.0, 0.5)):
            P.box(f"block_{i}_{j}", "wood2", (0.145, 0.1, 0.078), loc=(x, y, 0.022), base=True, bevel=0.004)
    for j, x in enumerate((-0.5, 0.0, 0.5)):
        P.box(f"stringer_{j}", "wood", (0.145, Wd, 0.022), loc=(x, 0, 0.1), base=True, bevel=0.003)
    for i, y in enumerate((-0.3275, -0.165, 0.0, 0.165, 0.3275)):
        w = 0.145 if i in (0, 2, 4) else 0.1
        P.box(f"top_{i}", "wood", (L, w, 0.022), loc=(0, y, 0.122), base=True, bevel=0.003)
    P.collider = [("box", (0, 0, 0.072), (L, Wd, 0.144))]


@model
def m_crate_stack(P: Prop):
    def crate(tag, size, loc, yaw):
        w, d, h = size
        P.box(f"crate_{tag}", "wood2", (w - 0.04, d - 0.04, h - 0.02), loc=loc, rot=(0, 0, yaw), base=True, bevel=0.004)
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))

        def at(x, y, z):
            return (loc[0] + x * c - y * s, loc[1] + x * s + y * c, loc[2] + z)
        for k, z in enumerate((0.0, h - 0.07)):
            P.box(f"batten_f_{tag}_{k}", "wood", (w, 0.025, 0.07), loc=at(0, -d / 2 + 0.0125, z), rot=(0, 0, yaw), base=True, bevel=0.004)
            P.box(f"batten_b_{tag}_{k}", "wood", (w, 0.025, 0.07), loc=at(0, d / 2 - 0.0125, z), rot=(0, 0, yaw), base=True, bevel=0.004)
        for k, (x, y) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
            P.box(f"post_{tag}_{k}", "wood", (0.06, 0.06, h), loc=at(x * (w / 2 - 0.03), y * (d / 2 - 0.03), 0), rot=(0, 0, yaw), base=True, bevel=0.004)
            P.box(f"corner_{tag}_{k}", "steel", (0.07, 0.07, 0.07), loc=at(x * (w / 2 - 0.03), y * (d / 2 - 0.03), h - 0.06), rot=(0, 0, yaw), base=True)
        P.box(f"stencil_{tag}", "stencil", (w * 0.7, 0.004, h * 0.5), loc=at(0, -d / 2 + 0.017, h * 0.2), rot=(0, 0, yaw), base=True, uv_boost=2.0)
    crate("a", (1.0, 0.7, 0.62), (0, 0, 0), 0)
    crate("b", (0.8, 0.6, 0.5), (0.04, 0.02, 0.62), 7)
    # plastic crate on top: open box
    z0, cx, cy = 1.12, -0.05, 0.0
    P.box("pcrate_floor", "plastic", (0.5, 0.36, 0.02), loc=(cx, cy, z0), base=True)
    for k, (dx, dy, sx, sy) in enumerate(((0, -0.17, 0.5, 0.02), (0, 0.17, 0.5, 0.02), (-0.24, 0, 0.02, 0.36), (0.24, 0, 0.02, 0.36))):
        P.box(f"pcrate_wall_{k}", "plastic", (sx, sy, 0.26), loc=(cx + dx, cy + dy, z0), base=True, bevel=0.004)
    P.collider = [("box", (0, 0, 0.56), (1.0, 0.7, 1.12)), ("box", (cx, cy, z0 + 0.14), (0.5, 0.36, 0.28))]


@model
def m_bicycle(P: Prop):
    R = 0.34
    rear, front = (-0.52, 0, R), (0.52, 0, R)
    for tag, (x, y, z) in (("r", rear), ("f", front)):
        P.torus(f"tyre_{tag}", "rubber", R - 0.02, 0.022, loc=(x, y, z), rot=(90, 0, 0), segs=36, rsegs=8)
        P.torus(f"rim_{tag}", "steel", R - 0.045, 0.01, loc=(x, y, z), rot=(90, 0, 0), segs=36, rsegs=6)
        P.cyl(f"hub_{tag}", "steel", 0.025, 0.1, loc=(x, y - 0.05, z), rot=(-90, 0, 0), segs=10)
        for k in range(12):
            a = math.radians(30 * k + (15 if tag == "f" else 0))
            side = 0.035 if k % 2 else -0.035
            P.sweep(f"spoke_{tag}_{k}", "steel", [(x, y + side, z), (x + math.cos(a) * (R - 0.05), y, z + math.sin(a) * (R - 0.05))], 0.0018, segs=4)
        P.torus(f"fender_{tag}", "paint", R + 0.03, 0.022, loc=(x, y, z), rot=(90, -35, 0), segs=16, rsegs=4, arc=110)
    bb = (0.0, 0, 0.27)
    ht_lo, ht_hi = (0.37, 0, 0.66), (0.41, 0, 0.84)
    seat_c = (-0.14, 0, 0.84)
    P.sweep("down_tube", "paint", [ht_lo, (0.25, 0, 0.45), (0.1, 0, 0.3), bb], 0.02, segs=10)
    P.sweep("seat_tube", "paint", [bb, (-0.08, 0, 0.6), seat_c], 0.018, segs=10)
    P.sweep("chain_stay_l", "paint", [(0, 0.03, 0.27), (-0.52, 0.06, R)], 0.011, segs=6)
    P.sweep("chain_stay_r", "paint", [(0, -0.03, 0.27), (-0.52, -0.06, R)], 0.011, segs=6)
    P.sweep("seat_stay_l", "paint", [(-0.1, 0.02, 0.74), (-0.52, 0.06, R)], 0.01, segs=6)
    P.sweep("seat_stay_r", "paint", [(-0.1, -0.02, 0.74), (-0.52, -0.06, R)], 0.01, segs=6)
    P.sweep("head_tube", "paint", [ht_lo, ht_hi], 0.026, segs=10)
    P.sweep("fork_l", "paint", [(0.37, 0.04, 0.66), (0.45, 0.05, 0.5), (0.52, 0.055, R)], 0.012, segs=6)
    P.sweep("fork_r", "paint", [(0.37, -0.04, 0.66), (0.45, -0.05, 0.5), (0.52, -0.055, R)], 0.012, segs=6)
    P.sweep("stem", "steel", [ht_hi, (0.4, 0, 0.98)], 0.014, segs=8)
    P.sweep("handlebar", "steel", [(0.3, -0.29, 1.0), (0.38, -0.2, 1.0), (0.4, 0, 0.98), (0.38, 0.2, 1.0), (0.3, 0.29, 1.0)], 0.011, segs=8)
    for k, s in enumerate((-1, 1)):
        P.sweep(f"grip_{k}", "rubber", [(0.31, s * 0.27, 1.0), (0.26, s * 0.33, 1.0)], 0.016, segs=8)
    P.sweep("seat_post", "steel", [seat_c, (-0.17, 0, 0.93)], 0.012, segs=8)
    P.blob("saddle", "leather", 0.12, loc=(-0.16, 0, 0.96), scale=(1.4, 0.75, 0.35), subdiv=2, noise=0.02, seed=4)
    P.cyl("chainring", "steel", 0.1, 0.008, loc=(0, -0.05, 0.27), rot=(90, 0, 0), segs=24)
    for k, s in enumerate((-1, 1)):
        px = 0.14 * (1 if s > 0 else -1)
        P.sweep(f"crank_{k}", "steel", [(0, s * 0.06, 0.27), (px, s * 0.07, 0.27 - 0.1 * s)], 0.01, segs=6)
        P.box(f"pedal_{k}", "rubber", (0.1, 0.08, 0.025), loc=(px, s * 0.11, 0.27 - 0.1 * s))
    P.sweep("chain", "dark_metal", [(0.0, -0.05, 0.37), (-0.52, -0.05, R + 0.04), (-0.52, -0.05, R - 0.04), (0.0, -0.05, 0.17)], 0.005, segs=4)
    # front basket (wire, texture cut-out) and kickstand
    bx, bz = 0.6, 0.9
    P.box("basket_floor", "wire", (0.3, 0.34, 0.01), loc=(bx, 0, bz), base=True)
    for k, (dx, dy, sx, sy) in enumerate(((0, -0.17, 0.3, 0.01), (0, 0.17, 0.3, 0.01), (-0.15, 0, 0.01, 0.34), (0.15, 0, 0.01, 0.34))):
        P.box(f"basket_wall_{k}", "wire", (sx, sy, 0.22), loc=(bx + dx, dy, bz), base=True)
    P.sweep("basket_strut", "steel", [(0.45, 0, 0.92), (0.52, 0, R + 0.02)], 0.007, segs=6)
    P.sweep("kickstand", "steel", [(-0.08, 0.05, 0.27), (-0.18, 0.2, 0.0)], 0.01, segs=6)
    P.transform_all(rot=(4.0, 0, 0))
    P.collider = [("box", (0, 0, 0.5), (1.78, 0.62, 1.0))]


@model
def m_scooter(P: Prop):
    P.box("deck", "paint", (0.56, 0.15, 0.045), loc=(-0.04, 0, 0.085), base=True, bevel=0.015, seg=2)
    P.box("deck_grip", "rubber", (0.48, 0.13, 0.004), loc=(-0.06, 0, 0.13), base=True)
    for tag, x in (("r", -0.38), ("f", 0.4)):
        P.cyl(f"tyre_{tag}", "rubber", 0.1, 0.05, loc=(x, 0, 0.1), rot=(90, 0, 0), segs=24, center=True, bevel=0.012)
        P.cyl(f"hub_{tag}", "dark_metal", 0.06, 0.056, loc=(x, 0, 0.1), rot=(90, 0, 0), segs=16, center=True)
    P.torus("fender_r", "paint", 0.125, 0.02, loc=(-0.38, 0, 0.1), rot=(90, -40, 0), segs=12, rsegs=4, arc=100)
    P.sweep("neck", "paint", [(0.22, 0, 0.12), (0.36, 0, 0.2)], 0.025, segs=8)
    P.sweep("stem", "paint", [(0.4, 0, 0.1), (0.36, 0, 0.3), (0.3, 0, 1.05)], 0.022, segs=10)
    P.sweep("handlebar", "black_plastic", [(0.3, -0.25, 1.06), (0.3, 0.25, 1.06)], 0.014, segs=8)
    for k, s in enumerate((-1, 1)):
        P.sweep(f"grip_{k}", "rubber", [(0.3, s * 0.18, 1.06), (0.3, s * 0.27, 1.06)], 0.02, segs=8)
    P.box("display", "screen", (0.07, 0.09, 0.012), loc=(0.29, 0, 1.08), rot=(0, -35, 0), uv_boost=3.0)
    P.box("qr_plate", "sign", (0.012, 0.09, 0.2), loc=(0.335, 0, 0.62), rot=(0, -4, 0), uv_boost=3.0)
    P.box("stem_wrap", "sign2", (0.05, 0.05, 0.3), loc=(0.32, 0, 0.82), rot=(0, -4, 0), uv_boost=2.0)
    P.box("front_light", "led", (0.03, 0.05, 0.025), loc=(0.37, 0, 0.42), rot=(0, -4, 0))
    P.sweep("kickstand", "dark_metal", [(-0.1, 0.06, 0.08), (-0.2, 0.17, 0.0)], 0.008, segs=6)
    P.transform_all(rot=(6.0, 0, 0))
    P.collider = [("box", (0.0, 0.05, 0.55), (1.0, 0.55, 1.1))]


# ------------------------------------------------------------------ food

@model
def m_ramen_cart(P: Prop):
    # cart body: counter box on a 2-wheel axle; customers on the -Y side
    P.box("counter_body", "wood", (1.8, 0.8, 0.72), loc=(0, 0.05, 0.18), base=True, bevel=0.01)
    P.box("counter_top", "wood_dark", (1.95, 0.95, 0.05), loc=(0, 0.05, 0.9), base=True, bevel=0.008)
    P.box("ledge", "wood_dark", (1.95, 0.32, 0.04), loc=(0, -0.55, 0.88), base=True, bevel=0.006)
    for k, x in enumerate((-0.8, 0.8)):
        P.box(f"ledge_brace_{k}", "wood", (0.04, 0.25, 0.12), loc=(x, -0.5, 0.76), base=True)
    for k, y in enumerate((-0.42, 0.52)):
        P.torus(f"wheel_{k}", "wood_dark", 0.32, 0.03, loc=(0.35, y, 0.35), rot=(90, 0, 0), segs=24, rsegs=6)
        P.cyl(f"wheel_hub_{k}", "dark_metal", 0.06, 0.08, loc=(0.35, y, 0.35), rot=(90, 0, 0), center=True, segs=12)
        for s in range(6):
            a = math.radians(60 * s)
            P.box(f"wheel_spoke_{k}_{s}", "wood_dark", (0.6, 0.025, 0.035), loc=(0.35, y, 0.35), rot=(0, -60 * s, 0))
    P.box("axle", "dark_metal", (0.05, 1.0, 0.05), loc=(0.35, 0.05, 0.35))
    for k, y in enumerate((-0.2, 0.3)):
        P.sweep(f"handle_{k}", "wood", [(0.9, y, 0.6), (1.5, y, 0.75)], 0.025, segs=8)
    P.box("leg_stand", "wood", (0.06, 0.6, 0.18), loc=(-0.8, 0.05, 0.0), base=True)
    # roof on four posts, eaves overhanging the customers
    for k, (x, y) in enumerate(((-0.88, -0.32), (0.88, -0.32), (-0.88, 0.42), (0.88, 0.42))):
        P.box(f"post_{k}", "wood", (0.06, 0.06, 1.25), loc=(x, y, 0.95), base=True, bevel=0.005)
    P.box("roof", "wood_dark", (2.15, 1.35, 0.06), loc=(0, -0.05, 2.22), rot=(-7, 0, 0), bevel=0.01)
    P.box("roof_beam", "wood", (2.0, 0.08, 0.1), loc=(0, -0.35, 2.12), bevel=0.006)
    # noren: four cloth panels hanging from the front beam
    for k in range(4):
        x = -0.75 + 0.5 * k
        P.ribbon(f"noren_{k}", "noren", [(x, -0.4, 2.1), (x, -0.41, 1.88), (x, -0.4, 1.7)], [0.46, 0.46, 0.46], (1, 0, 0), thickness=0.008, uv_boost=1.8)
    P.box("roof_sign", "sign_lit", (0.9, 0.04, 0.28), loc=(0, 0.35, 2.42), base=True, uv_boost=2.4)
    # red paper lanterns at the front corners
    for k, x in enumerate((-1.02, 1.02)):
        z = 1.62
        P.lathe(f"lantern_{k}", "lantern", [(0.0, z), (0.1, z + 0.02), (0.16, z + 0.12), (0.17, z + 0.22), (0.16, z + 0.32), (0.1, z + 0.42), (0.0, z + 0.44)],
                loc=(x, -0.45, 0), segs=20, uv_boost=1.6)
        P.cyl(f"lantern_cap_b_{k}", "dark_metal", 0.1, 0.03, loc=(x, -0.45, z - 0.01), segs=16)
        P.cyl(f"lantern_cap_t_{k}", "dark_metal", 0.1, 0.03, loc=(x, -0.45, z + 0.43), segs=16)
        P.sweep(f"lantern_cord_{k}", "dark_metal", [(x, -0.45, z + 0.46), (x, -0.45, 2.15)], 0.005, segs=4)
        P.light(f"Light_Lantern_{k}", (x, -0.45, z + 0.22), color=(1.0, 0.25, 0.1), energy=18, range=4.0)
    # pot with steam, menu on the +X side, stools for customers
    P.cyl("pot", "steel", 0.2, 0.3, loc=(0.45, 0.15, 0.95), segs=24, bevel=0.01)
    P.cyl("pot_lid", "steel", 0.21, 0.02, loc=(0.45, 0.15, 1.25), r2=0.15, segs=24)
    P.cyl("pot2", "steel", 0.15, 0.22, loc=(-0.1, 0.2, 0.95), segs=20, bevel=0.008)
    P.box("menu", "sign", (0.02, 0.6, 0.45), loc=(0.915, 0.05, 1.0), base=True, uv_boost=2.4)
    for k, x in enumerate((-0.6, 0.0, 0.6)):
        P.cyl(f"stool_seat_{k}", "red_plastic", 0.17, 0.04, loc=(x, -0.95, 0.46), segs=20, bevel=0.01)
        P.cyl(f"stool_leg_{k}", "steel", 0.025, 0.44, loc=(x, -0.95, 0.02), segs=8)
        P.cyl(f"stool_base_{k}", "steel", 0.15, 0.02, loc=(x, -0.95, 0.0), segs=16)
    P.socket("Socket_Steam", (0.45, 0.15, 1.3), "steam", dir=(0, 0, 1), rate="light")
    P.light("Light_Counter", (0, -0.1, 2.0), color=(1.0, 0.75, 0.45), energy=30, range=4.5)
    P.collider = [("box", (0.1, 0.05, 0.5), (2.0, 1.0, 1.0)), ("box", (0, -0.05, 2.2), (2.15, 1.35, 0.2))]


@model
def m_skewer_stall(P: Prop):
    # table
    P.box("table_top", "wood", (1.8, 0.8, 0.04), loc=(0, 0.0, 0.84), base=True, bevel=0.006)
    for k, (x, y) in enumerate(((-0.85, -0.35), (0.85, -0.35), (-0.85, 0.35), (0.85, 0.35))):
        P.box(f"table_leg_{k}", "steel", (0.04, 0.04, 0.84), loc=(x, y, 0), base=True)
    P.box("shelf", "wood", (1.7, 0.7, 0.025), loc=(0, 0, 0.25), base=True)
    # charcoal grill with glowing coals and skewers
    P.box("grill", "dark_metal", (1.1, 0.34, 0.18), loc=(0.15, -0.12, 0.88), base=True, bevel=0.008)
    P.box("coals", "coal", (1.02, 0.26, 0.02), loc=(0.15, -0.12, 1.02), base=True)
    for k in range(9):
        x = -0.3 + 0.11 * k
        P.cyl(f"skewer_{k}", "bamboo", 0.004, 0.42, loc=(x, -0.3, 1.075), rot=(-90, 0, 0), segs=6)
        P.blob(f"meat_{k}", "meat", 0.03, loc=(x, -0.13, 1.075), scale=(1, 3.6, 0.9), subdiv=1, noise=0.25, seed=k)
    P.box("tray", "steel", (0.4, 0.3, 0.03), loc=(-0.6, -0.1, 0.88), base=True)
    P.cyl("sauce_pot", "red_plastic", 0.08, 0.14, loc=(-0.6, 0.2, 0.88), segs=14)
    # canopy on four poles, sagging tarp
    for k, (x, y) in enumerate(((-1.1, -0.65), (1.1, -0.65), (-1.1, 0.65), (1.1, 0.65))):
        P.cyl(f"pole_{k}", "galv", 0.022, 2.35 if y < 0 else 2.15, loc=(x, y, 0), segs=8)
        P.cyl(f"pole_foot_{k}", "dark_metal", 0.12, 0.03, loc=(x, y, 0), segs=12)

    def tarp(x, y):
        z = 2.35 - (y + 0.75) / 1.5 * 0.2
        return z - 0.1 * math.cos(x / 1.2 * math.pi / 2) * math.cos(y / 0.75 * math.pi / 2) - 2.25
    P.grid("tarp", "canvas", 2.4, 1.5, 12, 8, loc=(0, 0, 2.25), fn=tarp)
    P.solidify_last(0.008)
    P.box("valance", "canvas", (2.4, 0.01, 0.22), loc=(0, -0.76, 2.13), uv_boost=1.8)
    # string lights along the front edge
    pts = [(-1.1 + 2.2 * t / 10, -0.78, 2.1 - 0.18 * math.sin(math.pi * t / 10)) for t in range(11)]
    P.sweep("light_wire", "dark_metal", pts, 0.004, segs=4)
    for k in range(1, 10):
        x, y, z = pts[k]
        P.blob(f"bulb_{k}", "bulb", 0.03, loc=(x, y, z - 0.04), scale=(1, 1, 1.3), subdiv=1, noise=0.0)
    # menu A-frame in front, crates and a gas bottle
    P.box("menu_a", "sign", (0.5, 0.03, 0.75), loc=(-0.6, -1.0, 0.0), rot=(-10, 0, 0), base=True, uv_boost=2.4)
    P.box("menu_b", "wood", (0.5, 0.03, 0.75), loc=(-0.6, -0.84, 0.0), rot=(10, 0, 0), base=True)
    for k, x in enumerate((-0.5, 0.1)):
        P.box(f"crate_{k}", "plastic", (0.5, 0.34, 0.24), loc=(x, 0.1, 0.0), base=True, bevel=0.01)
    P.lathe("gas_bottle", "paint2", [(0.0, 0.0), (0.13, 0.0), (0.14, 0.05), (0.14, 0.45), (0.1, 0.55), (0.03, 0.58), (0.0, 0.58)], loc=(0.7, 0.15, 0.0), segs=18)
    P.cyl("gas_valve", "steel", 0.025, 0.06, loc=(0.7, 0.15, 0.58), segs=8)
    P.sweep("gas_hose", "rubber", [(0.7, 0.15, 0.62), (0.65, 0.0, 0.7), (0.5, -0.1, 0.85)], 0.008, segs=6)
    P.light("Light_Grill", (0.15, -0.12, 1.15), color=(1.0, 0.4, 0.1), energy=15, range=3.0)
    P.light("Light_String", (0, -0.85, 1.95), color=(1.0, 0.8, 0.5), energy=25, range=5.0)
    P.socket("Socket_Smoke", (0.15, -0.12, 1.1), "smoke", dir=(0, 0, 1), rate="light")
    P.collider = [("box", (0, 0, 0.45), (1.8, 0.8, 0.9)), ("box", (0, -1.0, 0.4), (0.5, 0.35, 0.8))]


# ------------------------------------------------------------------ utility / rooftop

@model
def m_cable_bundle(P: Prop):
    span, sag = 8.0, 0.7
    rnd = random.Random(5)

    def cat(x, dy, dz, s):
        return (x, dy, dz - s * (1 - (2 * x / span) ** 2))
    specs = [(0.0, 0.0, 0.016, "cable"), (0.05, -0.04, 0.012, "cable"), (-0.05, 0.03, 0.01, "cable2"), (0.02, 0.06, 0.02, "cable")]
    for k, (dy, dz, r, grp) in enumerate(specs):
        s = sag * (1 + 0.12 * k)
        pts = [cat(-span / 2 + span * i / 24, dy, dz, s) for i in range(25)]
        P.sweep(f"cable_{k}", grp, pts, r, segs=6)
    for k, x in enumerate((-2.5, -0.6, 1.8)):
        z = -sag * (1 - (2 * x / span) ** 2) - 0.02
        P.cyl(f"clamp_{k}", "dark_metal", 0.05, 0.06, loc=(x, 0.0, z), rot=(0, 90, 0), center=True, segs=10)
    for k, x in enumerate((-span / 2, span / 2)):
        P.box(f"anchor_{k}", "dark_metal", (0.04, 0.16, 0.22), loc=(x, 0, 0.0), bevel=0.004)
    jx = 1.1
    jz = -sag * (1 - (2 * jx / span) ** 2)
    P.box("junction_box", "paint", (0.24, 0.12, 0.3), loc=(jx, 0.0, jz - 0.24), bevel=0.012, seg=2)
    P.box("junction_tag", "sign", (0.14, 0.004, 0.08), loc=(jx, -0.062, jz - 0.2), uv_boost=3.0)
    P.sweep("junction_tail", "cable", [(jx, 0, jz - 0.39), (jx + 0.1, 0, jz - 0.7), (jx + 0.05, 0.02, jz - 1.1)], 0.01, segs=6)
    P.collider = "none"


@model
def m_ac_unit(P: Prop):
    # galvanised stand
    for k, y in enumerate((-0.12, 0.12)):
        P.box(f"rail_{k}", "galv", (1.0, 0.05, 0.04), loc=(0, y, 0.3), base=True)
        for j, x in enumerate((-0.45, 0.45)):
            P.box(f"leg_{k}_{j}", "galv", (0.04, 0.04, 0.3), loc=(x, y, 0.0), base=True)
            P.box(f"pad_{k}_{j}", "rubber", (0.08, 0.08, 0.02), loc=(x, y, 0.0), base=True)
    z0, W, D, H = 0.34, 0.9, 0.34, 0.66
    P.box("body", "paint", (W, D, H), loc=(0, 0, z0), base=True, bevel=0.02, seg=2)
    cx, cz = -0.1, z0 + H / 2
    P.cyl("fan_recess", "dark_metal", 0.26, 0.02, loc=(cx, -D / 2 + 0.012, cz), rot=(90, 0, 0), segs=28)
    for k in range(3):
        P.box(f"blade_{k}", "dark_plastic", (0.2, 0.01, 0.08), loc=(cx, -D / 2 + 0.006, cz), rot=(0, 120 * k, 0))
    P.cyl("grille", "grille", 0.25, 0.012, loc=(cx, -D / 2 - 0.004, cz), rot=(90, 0, 0), segs=28, uv_boost=1.6)
    P.box("fins_side", "fins", (0.012, D - 0.06, H - 0.1), loc=(-W / 2 - 0.006, 0, z0 + 0.05), base=True, uv_boost=1.5)
    P.box("service_cover", "steel", (0.16, 0.012, 0.4), loc=(0.33, -D / 2 - 0.006, z0 + 0.12), base=True, bevel=0.003)
    P.box("brand_plate", "sign", (0.16, 0.004, 0.05), loc=(-0.1, -D / 2 - 0.002, z0 + H - 0.06), uv_boost=3.0)
    for k, z in enumerate((z0 + 0.12, z0 + 0.2)):
        P.cyl(f"valve_{k}", "brass", 0.018, 0.05, loc=(0.47, 0.06, z), rot=(0, 90, 0), segs=8)
        P.sweep(f"pipe_{k}", "foam" if k == 0 else "copper", [(0.5, 0.06, z), (0.6, 0.08, z), (0.62, 0.2, z + 0.1), (0.6, 0.35, z + 0.4)], 0.02 if k == 0 else 0.008, segs=8)
    P.sweep("drain_hose", "dark_plastic", [(0.3, 0.1, z0), (0.35, 0.1, 0.15), (0.45, 0.2, 0.01)], 0.008, segs=6)
    P.collider = [("box", (0, 0, 0.5), (1.0, 0.36, 1.0))]


@model
def m_satellite_dish(P: Prop):
    for k, y in enumerate((-0.4, 0.4)):
        P.box(f"rail_{k}", "galv", (1.1, 0.06, 0.05), loc=(0, y, 0.0), base=True)
    for k, x in enumerate((-0.45, 0.45)):
        P.box(f"cross_{k}", "galv", (0.06, 0.86, 0.05), loc=(x, 0, 0.05), base=True)
    for k, (x, y) in enumerate(((-0.35, -0.4), (0.35, -0.4), (-0.35, 0.4), (0.35, 0.4))):
        P.box(f"ballast_{k}", "concrete", (0.3, 0.2, 0.06), loc=(x, y, 0.05), base=True, bevel=0.004)
    P.cyl("mast", "galv", 0.03, 1.05, loc=(0, 0.05, 0.1), segs=12)
    for k, (x, y) in enumerate(((-0.4, -0.35), (0.4, -0.35), (0.0, 0.4))):
        P.sweep(f"brace_{k}", "galv", [(x, y, 0.1), (0, 0.05, 0.75)], 0.012, segs=6)
    f = 0.42
    R = 0.6
    outer = [(r, r * r / (4 * f)) for r in [R * i / 10 for i in range(11)]]
    inner = [(r, z + 0.008) for r, z in reversed(outer)]
    dish_c = (0, -0.05, 1.12)
    P.lathe("dish", "dish", [(0.0, outer[0][1])] + outer[1:] + inner[:-1] + [(0.0, inner[-1][1])], loc=dish_c, rot=(55, 0, 0), segs=32, uv_boost=1.4)
    P.box("dish_mount", "dark_metal", (0.14, 0.1, 0.14), loc=(0, 0.04, 1.1), bevel=0.01)
    # feed arm from the dish's lower rim to the focus
    ax = (0, -math.sin(math.radians(55)), math.cos(math.radians(55)))
    focus = (dish_c[0] + ax[0] * f, dish_c[1] + ax[1] * f, dish_c[2] + ax[2] * f)
    lo_rim = (0, dish_c[1] - 0.5, dish_c[2] - 0.34)       # the lower rim after the 55 deg tilt
    P.sweep("feed_arm", "galv", [lo_rim, focus], 0.012, segs=6)
    P.box("lnb", "white_plastic", (0.06, 0.12, 0.06), loc=focus, rot=(55, 0, 0), bevel=0.01)
    P.sweep("coax", "cable", [(0.03, 0.05, 1.05), (0.06, 0.1, 0.6), (0.2, 0.3, 0.12)], 0.006, segs=6)
    P.collider = [("box", (0, 0, 0.6), (1.2, 1.0, 1.2))]


@model
def m_water_tank(P: Prop):
    legs = []
    for k in range(6):
        a = math.radians(60 * k + 30)
        x, y = math.cos(a) * 1.15, math.sin(a) * 1.15
        legs.append((x, y))
        P.box(f"leg_{k}", "steel_rust", (0.12, 0.12, 2.0), loc=(x, y, 0), rot=(0, 0, math.degrees(a)), base=True)
        P.box(f"foot_{k}", "steel_rust", (0.22, 0.22, 0.02), loc=(x, y, 0), base=True)
    for k in range(6):
        (x0, y0), (x1, y1) = legs[k], legs[(k + 1) % 6]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        ln = math.hypot(x1 - x0, y1 - y0)
        P.box(f"beam_{k}", "steel_rust", (ln + 0.1, 0.1, 0.14), loc=(mx, my, 1.86), rot=(0, 0, ang), base=True)
        if k % 2 == 0:
            P.sweep(f"brace_{k}", "steel_rust", [(x0, y0, 0.15), (x1, y1, 1.8)], 0.018, segs=6)
    P.cyl("deck", "wood_dark", 1.55, 0.08, loc=(0, 0, 2.0), segs=32)
    P.cyl("tank", "staves", 1.42, 2.6, loc=(0, 0, 2.08), r2=1.36, segs=40, uv_boost=1.0)
    for k, z in enumerate((2.3, 2.85, 3.4, 3.95, 4.45)):
        r = 1.42 + (1.36 - 1.42) * (z - 2.08) / 2.6 + 0.012
        P.torus(f"hoop_{k}", "steel_rust", r, 0.014, loc=(0, 0, z), segs=40, rsegs=5)
    P.lathe("roof", "roof_tar", [(1.5, 4.66), (1.5, 4.7), (0.12, 5.45), (0.0, 5.47)], segs=40)
    P.lathe("finial", "steel_rust", [(0.05, 5.4), (0.06, 5.55), (0.0, 5.62)], segs=10)
    P.box("hatch", "wood_dark", (0.4, 0.06, 0.3), loc=(1.0, -0.2, 4.98), rot=(0, -27, 0))
    # ladder up the +X side
    lx = 1.6
    for k, y in enumerate((-0.22, 0.22)):
        P.sweep(f"ladder_rail_{k}", "steel_rust", [(lx, y, 0.0), (lx, y, 4.55), (lx - 0.25, y, 4.8)], 0.02, segs=6)
    for k in range(15):
        z = 0.3 * (k + 1)
        P.cyl(f"rung_{k}", "steel_rust", 0.012, 0.44, loc=(lx, 0, z), rot=(90, 0, 0), center=True, segs=6)
    P.sweep("overflow", "steel_rust", [(-1.38, 0.2, 4.2), (-1.55, 0.2, 4.2), (-1.55, 0.2, 2.1), (-1.6, 0.2, 0.3)], 0.035, segs=8)
    P.box("stencil", "stencil", (1.3, 0.004, 0.6), loc=(0, -1.425, 3.0), uv_boost=1.8)
    P.collider = [("cyl", (0, 0), 1.55, 5.5)]


# ------------------------------------------------------------------ decal

@model
def m_puddle_decal(P: Prop):
    for nd, (w, h), x in (("Puddle_S", (1.2, 0.9), -2.6), ("Puddle_M", (2.2, 1.4), 0.0), ("Puddle_L", (3.2, 1.3), 3.0)):
        P.grid(nd, "water", w, h, 4, 3, loc=(x, 0, 0.012), node=nd)
    P.collider = "none"


# ------------------------------------------------------------------ nature

@model
def m_planter(P: Prop):
    L, Wd, H, t = 1.6, 0.6, 0.55, 0.07
    P.box("wall_f", "concrete", (L, t, H), loc=(0, -Wd / 2 + t / 2, 0), base=True, bevel=0.012)
    P.box("wall_b", "concrete", (L, t, H), loc=(0, Wd / 2 - t / 2, 0), base=True, bevel=0.012)
    P.box("wall_l", "concrete", (t, Wd - 2 * t, H), loc=(-L / 2 + t / 2, 0, 0), base=True, bevel=0.01)
    P.box("wall_r", "concrete", (t, Wd - 2 * t, H), loc=(L / 2 - t / 2, 0, 0), base=True, bevel=0.01)
    P.box("soil", "soil", (L - 2 * t, Wd - 2 * t, 0.05), loc=(0, 0, H - 0.1), base=True)
    for k, (x, y, r, sz) in enumerate(((-0.5, 0.0, 0.28, 0.8), (-0.05, 0.04, 0.33, 0.95), (0.42, -0.02, 0.27, 0.8), (0.2, 0.1, 0.2, 0.7))):
        P.blob(f"shrub_{k}", "leaves", r, loc=(x, y, H - 0.06 + r * sz * 0.7), scale=(1.1, 0.85, sz), subdiv=2, noise=0.2, seed=20 + k)
    P.box("plate", "sign", (0.3, 0.006, 0.09), loc=(0.45, -Wd / 2 - 0.003, 0.3), uv_boost=3.0)
    P.collider = [("box", (0, 0, H / 2), (L, Wd, H))]


@model
def m_street_tree(P: Prop):
    P.box("grate", "grate", (1.2, 1.2, 0.025), loc=(0, 0, 0), base=True, uv_boost=1.4)
    P.box("pit", "soil", (1.1, 1.1, 0.01), loc=(0, 0, -0.005), base=True)
    rnd = random.Random(3)
    trunk = [(0.0, 0.0, 0.0), (0.02, 0.01, 0.8), (0.06, -0.02, 1.6), (0.05, 0.02, 2.3), (0.02, 0.0, 2.9)]
    P.sweep("trunk", "bark", trunk, 0.12, segs=10, radii=[0.14, 0.12, 0.105, 0.09, 0.07])
    for k, (dx, dy, z0, z1) in enumerate(((0.9, 0.2, 2.1, 3.3), (-0.7, 0.6, 2.4, 3.6), (0.1, -0.9, 2.6, 3.5))):
        P.sweep(f"branch_{k}", "bark", [(0.04, 0.0, z0), (dx * 0.5, dy * 0.5, (z0 + z1) / 2 + 0.1), (dx, dy, z1)], 0.05, segs=8, radii=[0.06, 0.045, 0.025])
    clumps = [(0.0, 0.0, 3.9, 1.15), (0.85, 0.25, 3.5, 0.85), (-0.75, 0.55, 3.7, 0.85), (0.15, -0.85, 3.6, 0.8), (-0.5, -0.45, 4.3, 0.7), (0.5, 0.5, 4.4, 0.7)]
    for k, (x, y, z, r) in enumerate(clumps):
        P.blob(f"canopy_{k}", "leaves", r, loc=(x, y, z), scale=(1.0, 1.0, 0.78), subdiv=2, noise=0.18, seed=40 + k)
    for k in range(4):
        a = math.radians(45 + 90 * k)
        x, y = math.cos(a) * 0.42, math.sin(a) * 0.42
        P.sweep(f"guard_bar_{k}", "paint", [(x, y, 0.0), (x, y, 1.45)], 0.014, segs=6)
    for k, z in enumerate((0.5, 1.4)):
        P.torus(f"guard_ring_{k}", "paint", 0.42, 0.012, loc=(0, 0, z), segs=24, rsegs=5)
    P.collider = [("cyl", (0, 0), 0.45, 1.5), ("cyl", (0, 0), 0.15, 3.0, 1.5)]


@model
def m_palm_tree(P: Prop):
    n = 14
    top = (0.85, 0.15, 6.9)
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((top[0] * t * t, top[1] * t * t, top[2] * t))
    radii = [0.24 - 0.09 * (i / n) + (0.05 if i == 0 else 0) for i in range(n + 1)]
    P.sweep("trunk", "palm_bark", pts, 0.2, segs=12, radii=radii)
    P.blob("crown", "palm_crown", 0.24, loc=(top[0] + 0.03, top[1], top[2] + 0.1), scale=(1, 1, 1.25), subdiv=2, noise=0.1, seed=2)
    rnd = random.Random(8)
    for k in range(11):
        yaw = math.radians(360 * k / 11 + rnd.uniform(-10, 10))
        pitch = math.radians(rnd.uniform(15, 40))
        L = rnd.uniform(2.4, 3.0)
        d = (math.cos(yaw), math.sin(yaw))
        fp = []
        widths = []
        for i in range(9):
            s = i / 8
            h = L * s
            z = top[2] + 0.15 + math.sin(pitch) * h - 1.1 * (s ** 2) * L / 2.6
            r = math.cos(pitch) * h
            fp.append((top[0] + d[0] * (0.12 + r), top[1] + d[1] * (0.12 + r), z))
            widths.append(0.12 + 0.55 * math.sin(math.pi * min(1, s * 1.25)) * (1 - 0.6 * s))
        P.ribbon(f"frond_{k}", "frond", fp, widths, (-d[1], d[0], 0), fold=0.35, thickness=0.01, cols=4)
    for k in range(3):
        a = math.radians(120 * k + 20)
        P.blob(f"coconut_{k}", "coconut", 0.09, loc=(top[0] + math.cos(a) * 0.2, top[1] + math.sin(a) * 0.2, top[2] - 0.1), subdiv=1, noise=0.05, seed=k)
    # ground uplighter
    P.cyl("uplight", "dark_metal", 0.09, 0.08, loc=(-0.55, -0.3, 0), segs=16, bevel=0.01)
    P.cyl("uplight_lens", "led", 0.065, 0.005, loc=(-0.55, -0.3, 0.08), segs=16)
    P.light("Light_Uplight", (-0.55, -0.3, 0.1), kind="spot", color=(1.0, 0.85, 0.6), energy=80, range=9.0, dir=(0.25, 0.1, 1.0))
    P.collider = [("cyl", (0, 0), 0.3, 6.9)]
