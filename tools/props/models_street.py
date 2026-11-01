"""Street furniture and traffic props.  Blender axes: Z up, front faces -Y."""
import math

from proplib import Prop

MODELS = {}


def model(fn):
    MODELS[fn.__name__[2:]] = fn
    return fn


# ------------------------------------------------------------------ shared bits

def signal_lens(P, name, group, x, y, z, r=0.1, node=None, facing="-y", visor=True):
    """A lens (+ visor) at (x, y, z) facing -Y (or +X)."""
    if facing == "-y":
        P.cyl(name, group, r, 0.02, loc=(x, y - 0.005, z), rot=(90, 0, 0), segs=20, node=node, uv_boost=1.5)
        P.cyl(name + "_ring", "dark_metal", r + 0.02, 0.012, loc=(x, y + 0.004, z), rot=(90, 0, 0), segs=20)
        if visor:
            arc = [(math.cos(math.radians(a)) * (r + 0.03), math.sin(math.radians(a)) * (r + 0.03)) for a in range(-10, 191, 20)]
            arc += [(math.cos(math.radians(a)) * (r + 0.018), math.sin(math.radians(a)) * (r + 0.018)) for a in range(190, -11, -20)]
            P.prism(name + "_visor", "paint", [(x + u, z + v) for u, v in arc], 0.17, loc=(0, y - 0.09, 0), smooth=True)
    else:  # +x
        P.cyl(name, group, r, 0.02, loc=(x + 0.005, y, z), rot=(0, 90, 0), segs=20, node=node, uv_boost=1.5)
        P.cyl(name + "_ring", "dark_metal", r + 0.02, 0.012, loc=(x - 0.004, y, z), rot=(0, 90, 0), segs=20)


def vehicle_head_vertical(P, tag, cx, cy, cz):
    """Housing 0.34 x 0.26 x 0.98 centred at (cx, cy, cz), lenses on its -Y face, backplate behind."""
    P.box(f"Head_{tag}_housing", "paint", (0.34, 0.26, 0.98), loc=(cx, cy, cz), bevel=0.02, seg=2)
    P.box(f"Head_{tag}_backplate", "backplate", (0.56, 0.02, 1.2), loc=(cx, cy + 0.145, cz), bevel=0.005)
    fy = cy - 0.13
    for i, (col, grp) in enumerate((("Red", "lens_red"), ("Amber", "lens_amber"), ("Green", "lens_green"))):
        z = cz + 0.3 - 0.3 * i
        node = f"Lamp_{tag}_{col}"
        signal_lens(P, node, grp, cx, fy, z, node=node)
        P.socket(node, (cx, fy - 0.02, z), "signal_lamp", dir=(0, -1, 0), color=col.lower(), head=tag)


def vehicle_head_horizontal(P, tag, cx, cy, cz):
    """Japanese-style horizontal head: green, amber, red from the left (seen from the front)."""
    P.box(f"Head_{tag}_housing", "paint", (1.02, 0.26, 0.34), loc=(cx, cy, cz), bevel=0.02, seg=2)
    P.box(f"Head_{tag}_backplate", "backplate", (1.22, 0.02, 0.5), loc=(cx, cy + 0.145, cz), bevel=0.005)
    fy = cy - 0.13
    # seen from the front (looking +Y), the viewer's left is -X
    for i, (col, grp) in enumerate((("Green", "lens_green"), ("Amber", "lens_amber"), ("Red", "lens_red"))):
        x = cx - 0.32 + 0.32 * i
        node = f"Lamp_{tag}_{col}"
        signal_lens(P, node, grp, x, fy, cz, r=0.11, node=node)
        P.socket(node, (x, fy - 0.02, cz), "signal_lamp", dir=(0, -1, 0), color=col.lower(), head=tag)


def ped_head(P, tag, cx, cy, cz, facing="-y"):
    """Pedestrian head: red standing man over green walking man, square lenses."""
    if facing == "-y":
        P.box(f"Ped_{tag}_housing", "paint", (0.32, 0.24, 0.66), loc=(cx, cy, cz), bevel=0.015, seg=2)
        for i, (col, grp) in enumerate((("Stop", "lens_stop"), ("Walk", "lens_walk"))):
            z = cz + 0.155 - 0.31 * i
            node = f"Ped_{tag}_{col}"
            P.box(node, grp, (0.25, 0.02, 0.25), loc=(cx, cy - 0.125, z), node=node, uv_boost=2.0)
            P.box(node + "_hood", "paint", (0.29, 0.1, 0.02), loc=(cx, cy - 0.17, z + 0.14))
            P.socket(node, (cx, cy - 0.14, z), "signal_lamp", dir=(0, -1, 0), color=col.lower(), head=f"Ped_{tag}")
    else:  # +x
        P.box(f"Ped_{tag}_housing", "paint", (0.24, 0.32, 0.66), loc=(cx, cy, cz), bevel=0.015, seg=2)
        for i, (col, grp) in enumerate((("Stop", "lens_stop"), ("Walk", "lens_walk"))):
            z = cz + 0.155 - 0.31 * i
            node = f"Ped_{tag}_{col}"
            P.box(node, grp, (0.02, 0.25, 0.25), loc=(cx + 0.125, cy, z), node=node, uv_boost=2.0)
            P.box(node + "_hood", "paint", (0.1, 0.29, 0.02), loc=(cx + 0.17, cy, z + 0.14))
            P.socket(node, (cx + 0.14, cy, z), "signal_lamp", dir=(1, 0, 0), color=col.lower(), head=f"Ped_{tag}")


def push_button(P, x, y, z, facing="-y"):
    if facing == "-y":
        P.box("button_box", "paint2", (0.12, 0.1, 0.2), loc=(x, y, z), bevel=0.012, seg=2)
        P.cyl("button", "steel", 0.025, 0.02, loc=(x, y - 0.05, z - 0.03), rot=(90, 0, 0), segs=16)
        P.box("button_plate", "sign", (0.1, 0.006, 0.07), loc=(x, y - 0.052, z + 0.05), uv_boost=3.0)
    else:
        P.box("button_box", "paint2", (0.1, 0.12, 0.2), loc=(x, y, z), bevel=0.012, seg=2)
        P.cyl("button", "steel", 0.025, 0.02, loc=(x + 0.05, y, z - 0.03), rot=(0, 90, 0), segs=16)
        P.box("button_plate", "sign", (0.006, 0.1, 0.07), loc=(x + 0.052, y, z + 0.05), uv_boost=3.0)


def pole_base(P, r, h=0.22):
    P.box("base_plate", "dark_metal", (r * 4.2, r * 4.2, 0.025), loc=(0, 0, 0), base=True, bevel=0.004)
    P.cyl("base_collar", "dark_metal", r * 1.7, h, loc=(0, 0, 0.025), r2=r * 1.25, segs=20, bevel=0.01)
    for i in range(4):
        a = math.radians(45 + 90 * i)
        P.cyl(f"bolt_{i}", "steel", 0.012, 0.04, loc=(math.cos(a) * r * 1.6, math.sin(a) * r * 1.6, 0.025), segs=6)


# ------------------------------------------------------------------ traffic

@model
def m_traffic_light_pole(P: Prop):
    r = 0.075
    pole_base(P, r)
    P.cyl("pole", "galv", r, 3.6, loc=(0, 0, 0.2), segs=18)
    P.cyl("pole_cap", "dark_metal", r + 0.01, 0.05, loc=(0, 0, 3.8), r2=r * 0.6, segs=18)
    # vehicle head on two bracket arms, in front of the pole
    vehicle_head_vertical(P, "A", 0.0, -0.32, 3.05)
    for z in (2.75, 3.35):
        P.box(f"head_bracket_{z}", "dark_metal", (0.06, 0.2, 0.05), loc=(0, -0.11, z), bevel=0.005)
        P.cyl(f"head_clamp_{z}", "dark_metal", r + 0.012, 0.07, loc=(0, 0, z - 0.035), segs=18)
    # pedestrian head on the +X side, facing +X (across the crossing)
    ped_head(P, "A", 0.26, 0.0, 2.25, facing="+x")
    P.box("ped_bracket", "dark_metal", (0.14, 0.05, 0.05), loc=(0.1, 0, 2.25), bevel=0.005)
    push_button(P, 0.0, -0.13, 1.1)
    P.cyl("button_clamp", "dark_metal", r + 0.012, 0.06, loc=(0, 0, 1.07), segs=18)
    # MERIDIAN sensor puck on top
    P.cyl("sensor_puck", "white_plastic", 0.09, 0.07, loc=(0, 0, 3.85), r2=0.07, segs=20, bevel=0.01)
    P.cyl("sensor_eye", "screen", 0.03, 0.012, loc=(0, -0.075, 3.89), rot=(90, 0, 0), segs=16)
    P.collider = [("cyl", (0, 0), 0.16, 3.9), ("box", (0, -0.32, 3.05), (0.6, 0.3, 1.2))]
    P.meta["signals"] = {"vehicle_heads": [{"head": "A", "facing": "+Z", "lamps": {"red": "Lamp_A_Red", "amber": "Lamp_A_Amber", "green": "Lamp_A_Green"}}],
                         "ped_heads": [{"head": "Ped_A", "facing": "+X", "lamps": {"stop": "Ped_A_Stop", "walk": "Ped_A_Walk"}}]}


@model
def m_traffic_light_mast(P: Prop):
    pole_base(P, 0.13, 0.3)
    P.cyl("pole", "galv", 0.13, 6.0, loc=(0, 0, 0.28), r2=0.1, segs=20)
    P.cyl("pole_cap", "dark_metal", 0.11, 0.08, loc=(0, 0, 6.28), r2=0.05, segs=20)
    P.box("arm_clamp", "dark_metal", (0.3, 0.3, 0.42), loc=(0, 0, 5.75), bevel=0.03, seg=2)
    # tapered arm out to +X, slight upward rise; tie rod above
    pts = [(0.12, 0, 5.75 + 0.02 * i) for i in range(1)] + [(0.12 + 6.5 * t, 0, 5.75 + 0.18 * t) for t in (0.25, 0.5, 0.75, 1.0)]
    P.sweep("arm", "galv", pts, 0.085, segs=14, radii=[0.085, 0.078, 0.07, 0.062, 0.055])
    P.sweep("tie_rod", "galv", [(0.1, 0, 6.15), (3.6, 0, 5.85)], 0.025, segs=8)
    P.cyl("arm_cap", "dark_metal", 0.06, 0.05, loc=(6.62, 0, 5.93), rot=(0, 90, 0), segs=14)
    for tag, x in (("B", 3.3), ("C", 5.7)):
        z = 5.75 + 0.18 * (x / 6.5)
        P.box(f"hanger_{tag}", "dark_metal", (0.06, 0.06, 0.32), loc=(x, 0, z - 0.2), bevel=0.005)
        vehicle_head_horizontal(P, tag, x, -0.02, z - 0.53)
    # pole-mounted head for the near lane, low on the pole
    vehicle_head_vertical(P, "A", 0.0, -0.33, 3.0)
    for z in (2.7, 3.3):
        P.box(f"head_bracket_{z}", "dark_metal", (0.06, 0.22, 0.05), loc=(0, -0.13, z), bevel=0.005)
    # street-name blade on the arm, lit
    P.box("name_blade", "sign", (1.7, 0.05, 0.4), loc=(1.6, -0.02, 5.32), bevel=0.01, uv_boost=2.0)
    P.box("name_blade_hanger", "dark_metal", (0.04, 0.04, 0.25), loc=(1.2, 0, 5.6))
    P.box("name_blade_hanger2", "dark_metal", (0.04, 0.04, 0.25), loc=(2.0, 0, 5.62))
    # MERIDIAN camera at the tip
    P.box("cam_body", "white_plastic", (0.12, 0.3, 0.12), loc=(6.45, -0.05, 5.7), bevel=0.02, seg=2)
    P.box("cam_shield", "white_plastic", (0.16, 0.36, 0.015), loc=(6.45, -0.06, 5.775))
    P.cyl("cam_lens", "cam_eye", 0.035, 0.02, loc=(6.45, -0.2, 5.7), rot=(90, 0, 0), segs=16)
    P.box("cam_mount", "dark_metal", (0.04, 0.04, 0.12), loc=(6.45, 0.0, 5.82))
    push_button(P, 0.0, -0.17, 1.1)
    P.collider = [("cyl", (0, 0), 0.25, 6.3)]
    P.meta["signals"] = {"vehicle_heads": [
        {"head": "A", "facing": "+Z", "lamps": {"red": "Lamp_A_Red", "amber": "Lamp_A_Amber", "green": "Lamp_A_Green"}},
        {"head": "B", "facing": "+Z", "lamps": {"red": "Lamp_B_Red", "amber": "Lamp_B_Amber", "green": "Lamp_B_Green"}},
        {"head": "C", "facing": "+Z", "lamps": {"red": "Lamp_C_Red", "amber": "Lamp_C_Amber", "green": "Lamp_C_Green"}}],
        "ped_heads": [], "arm": "+X, 6.6 m, heads at x = 3.3 and 5.7 m, 5.3 m up"}
    P.light("Light_Cam", (6.45, -0.22, 5.7), color=(1, 0.1, 0.1), energy=0.3, range=1.0)


@model
def m_ped_signal(P: Prop):
    r = 0.06
    pole_base(P, r)
    P.cyl("pole", "galv", r, 2.75, loc=(0, 0, 0.2), segs=16)
    P.cyl("pole_cap", "dark_metal", r + 0.01, 0.04, loc=(0, 0, 2.95), r2=r * 0.5, segs=16)
    ped_head(P, "A", 0.0, -0.2, 2.45)
    P.box("ped_bracket", "dark_metal", (0.05, 0.12, 0.05), loc=(0, -0.06, 2.45))
    # countdown screen under the head
    P.box("count_box", "paint", (0.3, 0.16, 0.2), loc=(0, -0.18, 1.98), bevel=0.012, seg=2)
    P.box("Ped_A_Count", "screen", (0.24, 0.01, 0.14), loc=(0, -0.262, 1.98), uv_boost=2.5, node="Ped_A_Count")
    push_button(P, 0.0, -0.11, 1.1)
    P.collider = [("cyl", (0, 0), 0.13, 2.95)]
    P.meta["signals"] = {"vehicle_heads": [], "ped_heads": [{"head": "Ped_A", "facing": "+Z", "lamps": {"stop": "Ped_A_Stop", "walk": "Ped_A_Walk"},
                                                            "countdown": "Ped_A_Count"}]}


@model
def m_street_name_sign(P: Prop):
    P.cyl("pole", "galv", 0.045, 3.25, loc=(0, 0, 0), segs=14)
    P.cyl("foot", "dark_metal", 0.07, 0.12, loc=(0, 0, 0), r2=0.05, segs=14)
    P.lathe("finial", "dark_metal", [(0.05, 3.25), (0.055, 3.29), (0.03, 3.33), (0.0, 3.37)], segs=14)
    # blade 1 faces front/back (-Y / +Y), blade 2 faces the sides (+X / -X)
    P.box("blade_1", "sign", (1.05, 0.03, 0.24), loc=(0.48, 0, 2.95), bevel=0.008, uv_boost=2.5)
    P.box("blade_2", "sign", (0.03, 1.05, 0.24), loc=(0, -0.48, 3.2), bevel=0.008, uv_boost=2.5)
    for z in (2.95, 3.2):
        P.cyl(f"clamp_{z}", "dark_metal", 0.055, 0.28, loc=(0, 0, z - 0.14), segs=14)
    P.box("route_plate", "sign2", (0.36, 0.02, 0.46), loc=(0, -0.055, 2.15), bevel=0.006, uv_boost=2.0)
    P.collider = [("cyl", (0, 0), 0.08, 3.37)]


@model
def m_bollard(P: Prop):
    k = P.param("height", 0.96) / 0.96          # smart-model parameter (city/models/prop/bollard.toml)
    P.lathe("body", "paint", [(0.0, 0.0), (0.105, 0.0), (0.105, 0.86 * k), (0.095, 0.91 * k), (0.065, 0.945 * k), (0.0, 0.96 * k)], segs=24)
    P.lathe("reflect_band", "reflector", [(0.108, 0.70 * k), (0.108, 0.76 * k)], segs=24)
    P.lathe("led_ring", "led", [(0.109, 0.80 * k), (0.109, 0.815 * k)], segs=24)
    P.cyl("base_ring", "dark_metal", 0.13, 0.03, loc=(0, 0, 0), segs=24)
    P.collider = [("cyl", (0, 0), 0.11, 0.96 * k)]
    P.light("Light_Ring", (0, -0.12, 0.81 * k), color=(0.1, 0.9, 1.0), energy=0.4, range=1.5)


@model
def m_guard_rail(P: Prop):
    # W-beam profile (y, z) in the post's frame: 0.31 m tall, 0.083 m deep, 3 mm sheet
    import math as m
    prof_c = []
    for i in range(25):
        t = i / 24
        z = 0.31 * t
        y = -0.0415 * (1 - m.cos(2 * m.pi * 2 * t)) * 0.5 * 2
        prof_c.append((y, z))
    th = 0.004
    poly = [(y - 0.0, z) for y, z in prof_c] + [(y - th, z) for y, z in reversed(prof_c)]
    # prism profiles are in XZ, extruded along Y: rotate 90 about Z so it runs along X
    P.prism("beam", "galv", [(p[0], p[1]) for p in poly], 4.0, loc=(0, -0.26, 0.45), rot=(0, 0, 90), smooth=True)
    for i, x in enumerate((-1.0, 1.0)):
        P.box(f"post_{i}", "galv", (0.1, 0.15, 0.98), loc=(x, 0.02, 0.0), base=True, bevel=0.004)
        P.box(f"spacer_{i}", "galv", (0.1, 0.12, 0.2), loc=(x, -0.14, 0.62), bevel=0.004)
        P.box(f"reflector_{i}", "reflector", (0.08, 0.01, 0.06), loc=(x, -0.31, 0.75), uv_boost=2.0)
        for k, z in enumerate((0.55, 0.69)):
            P.cyl(f"bolt_{i}_{k}", "steel", 0.012, 0.02, loc=(x, -0.31, z), rot=(90, 0, 0), segs=8)
    P.collider = [("box", (0, -0.15, 0.4), (4.0, 0.36, 0.8))]


@model
def m_crash_barrier(P: Prop):
    # profile in the YZ plane (as x=y, z) and run along X: 1.8 m, 0.5 m base, 0.8 m tall
    prof = [(-0.25, 0.0), (0.25, 0.0), (0.25, 0.08), (0.18, 0.12), (0.1, 0.78), (0.06, 0.8), (-0.06, 0.8), (-0.1, 0.78), (-0.18, 0.12), (-0.25, 0.08)]
    P.prism("body", "plastic", prof, 1.66, rot=(0, 0, 90), bevel=0.02)
    # interlock lugs at the ends
    for i, x in enumerate((-0.86, 0.86)):
        P.box(f"lug_{i}", "plastic", (0.12, 0.16, 0.7 if i else 0.5), loc=(x, 0, 0.05 if i else 0.2), base=True, bevel=0.015)
    for i, x in enumerate((-0.45, 0.45)):
        P.box(f"fork_slot_{i}", "dark_plastic", (0.36, 0.52, 0.07), loc=(x, 0, 0.0), base=True)
    P.cyl("fill_cap", "dark_plastic", 0.06, 0.025, loc=(-0.5, 0, 0.8), segs=16)
    P.cyl("drain_cap", "dark_plastic", 0.04, 0.02, loc=(0.6, -0.205, 0.12), rot=(90, 0, 0), segs=12)
    P.box("reflector_strip", "reflector", (1.2, 0.01, 0.06), loc=(0, -0.145, 0.62), rot=(-5, 0, 0), uv_boost=1.5)
    P.collider = [("box", (0, 0, 0.4), (1.8, 0.5, 0.8))]


@model
def m_jersey_barrier(P: Prop):
    # New Jersey profile: 0.61 base, 0.81 tall, 0.15 top (y, z), run along X 3 m
    half = [(0.305, 0.0), (0.305, 0.075), (0.2, 0.33), (0.075, 0.81)]
    prof = half + [(-x, z) for x, z in reversed(half)]
    P.prism("body", "concrete", prof, 3.0, rot=(0, 0, 90), bevel=0.01)
    for i, x in enumerate((-0.9, 0.9)):
        P.torus(f"loop_{i}", "rebar", 0.07, 0.012, loc=(x, 0, 0.81), rot=(90, 0, 90), arc=180, segs=10, rsegs=6)
    for i, x in enumerate((-1.2, 0.0, 1.2)):
        P.box(f"reflector_{i}", "reflector", (0.1, 0.01, 0.07), loc=(x, -0.165, 0.55), rot=(-14, 0, 0), uv_boost=2.0)
    P.box("drain_slot_0", "dark_metal", (0.3, 0.62, 0.08), loc=(-0.75, 0, 0.0), base=True)
    P.box("drain_slot_1", "dark_metal", (0.3, 0.62, 0.08), loc=(0.75, 0, 0.0), base=True)
    P.collider = [("box", (0, 0, 0.405), (3.0, 0.61, 0.81))]


@model
def m_traffic_cone(P: Prop):
    P.box("base", "rubber", (0.38, 0.38, 0.035), loc=(0, 0, 0), base=True, bevel=0.03, seg=2)
    prof = [(0.155, 0.035), (0.15, 0.05), (0.03, 0.7), (0.0, 0.705)]
    P.lathe("cone", "plastic", prof, segs=24)

    def rr(z):
        return 0.15 + (0.03 - 0.15) * (z - 0.05) / 0.65 + 0.003
    for i, (z0, z1) in enumerate(((0.38, 0.46), (0.53, 0.58))):
        P.lathe(f"collar_{i}", "reflector", [(rr(z0), z0), (rr(z1), z1)], segs=24)
    P.collider = [("cyl", (0, 0), 0.16, 0.7)]


@model
def m_steam_vent(P: Prop):
    P.cyl("frame", "iron", 0.42, 0.03, loc=(0, 0, 0), segs=28)
    P.cyl("cover", "iron", 0.36, 0.035, loc=(0, 0, 0.0), segs=28, bevel=0.005)
    # chimney: open tube with thickness, slight taper
    outer = [(0.21, 0.035), (0.2, 1.35), (0.205, 1.4)]
    prof = outer + [(0.18, 1.4), (0.175, 0.3), (0.0, 0.3)]
    P.lathe("stack", "plastic", [(0.0, 0.035)] + prof, segs=24)
    for i, z in enumerate((0.45, 0.85, 1.2)):
        rr = 0.21 + (0.2 - 0.21) * (z - 0.035) / 1.315 + 0.003
        P.lathe(f"band_{i}", "reflector", [(rr, z), (rr, z + 0.12)], segs=24)
    P.cyl("skirt", "rubber", 0.27, 0.06, loc=(0, 0, 0.035), r2=0.215, segs=24)
    P.socket("Socket_Steam", (0, 0, 1.42), "steam", dir=(0, 0, 1), rate="dense", note="white steam plume, drifts with wind")
    P.collider = [("cyl", (0, 0), 0.27, 1.4)]


# ------------------------------------------------------------------ street furniture

@model
def m_bus_stop(P: Prop):
    W, D, H = 4.0, 1.5, 2.55
    yb, yf = 0.62, -0.62
    P.box("plinth", "concrete", (W + 0.3, D + 0.25, 0.05), loc=(0, 0, 0), base=True, bevel=0.01)
    for i, (x, y) in enumerate(((-1.9, yb), (1.9, yb), (-1.9, yf), (1.9, yf))):
        P.box(f"post_{i}", "paint", (0.08, 0.08, H - 0.05), loc=(x, y, 0.05), base=True, bevel=0.006)
    # roof: slab tilted back, fascia, LED strip and light panel underneath
    P.box("roof", "paint", (W + 0.4, D + 0.45, 0.1), loc=(0, -0.05, H + 0.05), rot=(-3, 0, 0), bevel=0.02, seg=2)
    P.box("roof_fascia", "paint2", (W + 0.42, 0.06, 0.18), loc=(0, -0.05 - (D + 0.45) / 2, H + 0.02), bevel=0.01)
    P.box("roof_led", "led", (W + 0.2, 0.03, 0.025), loc=(0, -0.05 - (D + 0.45) / 2 + 0.06, H - 0.06))
    P.box("light_panel", "led", (W - 0.6, 0.5, 0.02), loc=(0, 0.0, H - 0.005))
    # back wall: glass with top and bottom rails
    P.box("back_glass", "glass", (3.72, 0.02, 1.9), loc=(0, yb, 0.3), base=True)
    P.box("back_rail_low", "paint", (3.75, 0.06, 0.06), loc=(0, yb, 0.27), base=True, bevel=0.005)
    P.box("back_rail_top", "paint", (3.75, 0.06, 0.06), loc=(0, yb, 2.2), base=True, bevel=0.005)
    # -X end: glass side panel; +X end: double-sided backlit ad box
    P.box("side_glass", "glass", (0.02, 1.1, 1.9), loc=(-1.9, 0.0, 0.3), base=True)
    P.box("adbox", "paint", (0.16, 1.28, 2.0), loc=(1.92, 0.0, 0.18), base=True, bevel=0.02, seg=2)
    P.box("ad_out", "ad", (0.01, 1.12, 1.78), loc=(2.005, 0.0, 0.29), base=True, uv_boost=2.6)
    P.box("ad_in", "ad", (0.01, 1.12, 1.78), loc=(1.835, 0.0, 0.29), base=True, uv_boost=2.6)
    # bench: slats on two brackets, anti-sleep dividers
    for i, y in enumerate((0.26, 0.36, 0.46)):
        P.box(f"seat_slat_{i}", "wood", (2.6, 0.085, 0.035), loc=(-0.3, y, 0.46), bevel=0.006)
    for i, x in enumerate((-1.4, 0.8)):
        P.box(f"bench_bracket_{i}", "dark_metal", (0.05, 0.36, 0.05), loc=(x, 0.38, 0.42), bevel=0.004)
        P.box(f"bench_leg_{i}", "dark_metal", (0.05, 0.05, 0.4), loc=(x, 0.52, 0.05), base=True)
    for i, x in enumerate((-0.75, 0.15)):
        P.sweep(f"divider_{i}", "steel", [(x, 0.22, 0.48), (x, 0.22, 0.66), (x, 0.42, 0.66), (x, 0.5, 0.48)], 0.015, segs=8)
    # timetable screen on the back wall, route flag on the front-left post
    P.box("timetable_box", "dark_metal", (0.62, 0.05, 0.9), loc=(-1.25, yb - 0.04, 1.05), base=True, bevel=0.01)
    P.box("timetable", "screen", (0.54, 0.01, 0.8), loc=(-1.25, yb - 0.07, 1.1), base=True, uv_boost=2.6)
    P.box("route_flag", "sign", (0.03, 0.55, 0.55), loc=(-1.9, yf - 0.33, 2.0), bevel=0.01, uv_boost=2.2)
    P.box("route_flag_arm", "dark_metal", (0.04, 0.32, 0.04), loc=(-1.9, yf - 0.06, 2.2))
    # MERIDIAN dome camera under the roof
    P.lathe("dome_cam", "white_plastic", [(0.0, H - 0.17), (0.07, H - 0.16), (0.09, H - 0.11), (0.09, H - 0.02)], loc=(1.5, -0.4, 0), segs=16)
    P.light("Light_Shelter", (0, 0, H - 0.15), color=(0.85, 0.92, 1.0), energy=60, range=6.0)
    P.light("Light_Ad", (2.3, 0, 1.2), color=(1.0, 0.6, 0.9), energy=25, range=4.0)
    P.collider = [("box", (0, yb, 1.25), (4.0, 0.12, 2.5)), ("box", (1.92, 0, 1.2), (0.2, 1.3, 2.4)),
                  ("box", (-1.9, 0, 1.25), (0.1, 1.3, 2.5)), ("box", (-0.3, 0.38, 0.25), (2.6, 0.4, 0.5))]


@model
def m_bench(P: Prop):
    L = 1.8
    # cast end frames: side profile (y, z) laid in the YZ plane
    prof = [(-0.28, 0.0), (-0.2, 0.0), (-0.12, 0.38), (0.18, 0.38), (0.22, 0.0), (0.3, 0.0), (0.26, 0.42),
            (0.3, 0.44), (0.34, 0.85), (0.28, 0.87), (0.22, 0.47), (-0.24, 0.45)]
    for i, x in enumerate((-L / 2 + 0.08, L / 2 - 0.08)):
        P.prism(f"frame_{i}", "paint", prof, 0.05, loc=(x, 0, 0), rot=(0, 0, 90), bevel=0.006)
    for i in range(4):
        P.box(f"seat_{i}", "wood", (L, 0.1, 0.035), loc=(0, -0.2 + i * 0.12, 0.47), bevel=0.007)
    for i in range(3):
        z = 0.56 + i * 0.11
        y = 0.24 + (z - 0.5) * 0.16
        P.box(f"back_{i}", "wood", (L, 0.03, 0.09), loc=(0, y + 0.02, z), rot=(-15, 0, 0), bevel=0.007)
    P.sweep("divider", "steel", [(0, -0.22, 0.49), (0, -0.22, 0.68), (0, 0.0, 0.72), (0, 0.18, 0.62)], 0.018, segs=8)
    P.box("divider_plate", "steel", (0.08, 0.12, 0.01), loc=(0, -0.15, 0.493))
    P.box("plaque", "sign", (0.22, 0.006, 0.05), loc=(0, 0.215, 0.69), rot=(-15, 0, 0), uv_boost=4.0)
    P.collider = [("box", (0, 0, 0.25), (L, 0.6, 0.5)), ("box", (0, 0.3, 0.65), (L, 0.15, 0.45))]


@model
def m_fire_hydrant(P: Prop):
    P.lathe("body", "paint", [(0.0, 0.0), (0.15, 0.0), (0.15, 0.04), (0.11, 0.06), (0.11, 0.1), (0.13, 0.12), (0.13, 0.15), (0.105, 0.17),
                              (0.1, 0.58), (0.125, 0.6), (0.125, 0.63), (0.1, 0.65), (0.0, 0.66)], segs=24)
    P.lathe("bonnet", "paint", [(0.0, 0.64), (0.1, 0.64), (0.1, 0.68), (0.07, 0.74), (0.0, 0.76)], segs=24)
    P.cyl("op_nut", "steel", 0.025, 0.05, loc=(0, 0, 0.75), segs=5)
    for i, s in enumerate((-1, 1)):
        P.cyl(f"outlet_{i}", "paint", 0.04, 0.09, loc=(s * 0.09, 0, 0.45), rot=(0, 90 * s, 0), segs=16)
        P.cyl(f"outlet_cap_{i}", "steel", 0.046, 0.03, loc=(s * 0.18, 0, 0.45), rot=(0, 90 * s, 0), segs=16, bevel=0.004)
        P.cyl(f"outlet_nut_{i}", "steel", 0.02, 0.025, loc=(s * 0.21, 0, 0.45), rot=(0, 90 * s, 0), segs=5)
    P.cyl("pumper", "paint", 0.06, 0.09, loc=(0, -0.09, 0.36), rot=(90, 0, 0), segs=18)
    P.cyl("pumper_cap", "steel", 0.068, 0.035, loc=(0, -0.18, 0.36), rot=(90, 0, 0), segs=18, bevel=0.004)
    P.cyl("pumper_nut", "steel", 0.025, 0.03, loc=(0, -0.215, 0.36), rot=(90, 0, 0), segs=5)
    for i in range(6):
        a = math.radians(30 + 60 * i)
        P.cyl(f"flange_bolt_{i}", "steel", 0.012, 0.025, loc=(math.cos(a) * 0.12, math.sin(a) * 0.12, 0.15), segs=6)
    P.collider = [("cyl", (0, 0), 0.15, 0.76)]


@model
def m_parking_meter(P: Prop):
    P.cyl("foot", "dark_metal", 0.07, 0.06, loc=(0, 0, 0), segs=16)
    P.cyl("post", "galv", 0.035, 1.02, loc=(0, 0, 0.0), segs=12)
    P.box("collar", "dark_metal", (0.12, 0.12, 0.06), loc=(0, 0, 1.0), base=True, bevel=0.01)
    P.box("head", "paint", (0.26, 0.18, 0.42), loc=(0, 0, 1.06), base=True, bevel=0.035, seg=3)
    P.box("screen_bezel", "dark_plastic", (0.2, 0.01, 0.14), loc=(0, -0.093, 1.36), uv_boost=1.0)
    P.box("screen", "screen", (0.17, 0.006, 0.11), loc=(0, -0.099, 1.36), uv_boost=3.5)
    P.box("card_slot", "dark_plastic", (0.1, 0.02, 0.025), loc=(0, -0.095, 1.24))
    P.box("keypad", "dark_plastic", (0.12, 0.012, 0.07), loc=(0, -0.095, 1.15), uv_boost=2.0)
    P.box("solar", "solar", (0.22, 0.14, 0.012), loc=(0, 0.0, 1.49), rot=(-12, 0, 0))
    P.box("sticker_plate", "sign", (0.16, 0.006, 0.06), loc=(0, 0.093, 1.32), uv_boost=4.0)
    P.collider = [("cyl", (0, 0), 0.13, 1.5)]


@model
def m_data_kiosk(P: Prop):
    W, D, H = 0.92, 0.42, 2.3
    P.box("plinth", "concrete", (W + 0.2, D + 0.2, 0.08), loc=(0, 0, 0), base=True, bevel=0.015)
    P.box("body", "paint", (W, D, H - 0.08), loc=(0, 0, 0.08), base=True, bevel=0.05, seg=3)
    P.box("screen_bezel", "dark_plastic", (0.74, 0.03, 1.12), loc=(0, -D / 2 - 0.005, 0.7), base=True, bevel=0.01)
    P.box("screen", "screen", (0.68, 0.01, 1.04), loc=(0, -D / 2 - 0.022, 0.74), base=True, uv_boost=2.4)
    P.cyl("eye_ring", "led", 0.1, 0.03, loc=(0, -D / 2 - 0.005, 2.02), rot=(90, 0, 0), segs=28)
    P.cyl("eye_lens", "cam_eye", 0.06, 0.035, loc=(0, -D / 2 - 0.0, 2.02), rot=(90, 0, 0), segs=24)
    P.box("palm_pad", "led", (0.2, 0.14, 0.02), loc=(0, -D / 2 - 0.08, 0.98), rot=(-30, 0, 0), bevel=0.005)
    P.box("palm_shelf", "dark_metal", (0.3, 0.16, 0.04), loc=(0, -D / 2 - 0.07, 0.94), rot=(-30, 0, 0), bevel=0.01)
    P.box("halo", "led", (W - 0.06, D - 0.06, 0.03), loc=(0, 0, H + 0.0), base=True)
    P.box("top_cap", "dark_metal", (W - 0.02, D - 0.02, 0.04), loc=(0, 0, H + 0.03), base=True, bevel=0.01)
    P.box("ad_back", "ad", (0.76, 0.01, 1.5), loc=(0, D / 2 + 0.003, 0.45), base=True, uv_boost=2.0)
    P.box("side_led_l", "led", (0.01, 0.03, 1.6), loc=(-W / 2 - 0.003, -0.12, 0.4), base=True)
    P.box("side_led_r", "led", (0.01, 0.03, 1.6), loc=(W / 2 + 0.003, -0.12, 0.4), base=True)
    P.box("speaker", "dark_metal", (0.4, 0.02, 0.06), loc=(0, -D / 2 - 0.004, 1.92))
    P.light("Light_Screen", (0, -0.75, 1.3), color=(0.3, 0.75, 1.0), energy=30, range=4.0)
    P.collider = [("box", (0, 0, H / 2), (W + 0.2, D + 0.2, H + 0.07))]


@model
def m_phone_kiosk(P: Prop):
    for i, x in enumerate((-0.32, 0.32)):
        P.box(f"leg_{i}", "paint", (0.06, 0.06, 1.0), loc=(x, 0.06, 0), base=True, bevel=0.005)
    P.box("back_panel", "paint", (0.78, 0.1, 1.15), loc=(0, 0.06, 0.95), base=True, bevel=0.02, seg=2)
    # hood: an arc over the phone, extruded forward
    arc_o = [(math.cos(math.radians(a)) * 0.48, 2.1 + math.sin(math.radians(a)) * 0.2) for a in range(0, 181, 15)]
    arc_i = [(math.cos(math.radians(a)) * 0.45, 2.1 + math.sin(math.radians(a)) * 0.17) for a in range(180, -1, -15)]
    P.prism("hood", "paint2", arc_o + arc_i, 0.6, loc=(0, -0.19, 0), smooth=True)
    for i, x in enumerate((-0.465, 0.465)):
        P.box(f"hood_side_{i}", "paint", (0.03, 0.6, 1.0), loc=(x, -0.19, 1.1), base=True, bevel=0.006)
    P.box("hood_led", "led", (0.7, 0.4, 0.015), loc=(0, -0.2, 2.09))
    P.box("phone_body", "steel", (0.32, 0.12, 0.5), loc=(0, -0.05, 1.12), base=True, bevel=0.02, seg=2)
    P.box("handset", "black_plastic", (0.06, 0.06, 0.24), loc=(-0.12, -0.13, 1.26), base=True, bevel=0.02, seg=2)
    P.sweep("cord", "black_plastic", [(-0.12, -0.13, 1.27), (-0.1, -0.15, 1.18), (-0.08, -0.13, 1.14), (-0.04, -0.12, 1.16)], 0.006, segs=6)
    P.box("keypad", "steel", (0.12, 0.01, 0.14), loc=(0.06, -0.115, 1.2), base=True, uv_boost=2.5)
    P.box("screen", "screen", (0.18, 0.01, 0.08), loc=(0.02, -0.115, 1.43), base=True, uv_boost=3.0)
    P.box("header", "sign", (0.74, 0.02, 0.12), loc=(0, -0.495, 2.03), base=True, uv_boost=2.5)
    P.box("ad_panel", "ad", (0.6, 0.01, 0.4), loc=(0, -0.0, 1.66), base=True, uv_boost=2.0)
    P.light("Light_Hood", (0, -0.25, 2.0), color=(0.9, 0.95, 1.0), energy=15, range=3.0)
    P.collider = [("box", (0, -0.15, 1.15), (0.96, 0.8, 2.3))]


@model
def m_cctv_pole(P: Prop):
    pole_base(P, 0.09)
    P.cyl("pole", "galv", 0.09, 5.3, loc=(0, 0, 0.2), r2=0.075, segs=16)
    P.cyl("pole_cap", "dark_metal", 0.085, 0.05, loc=(0, 0, 5.5), r2=0.03, segs=16)
    P.box("crossarm", "galv", (1.2, 0.08, 0.08), loc=(0, 0, 5.2), bevel=0.006)
    P.cyl("arm_clamp", "dark_metal", 0.1, 0.16, loc=(0, 0, 5.12), segs=16)
    cams = ((-0.55, -25), (0.55, 25), (0.0, 180))
    for i, (x, yaw) in enumerate(cams):
        ry = yaw
        c = math.cos(math.radians(yaw))
        s = math.sin(math.radians(yaw))
        # camera points along (sin yaw, -cos yaw) in the ground plane, tilted down
        dx, dy = s, -c
        bx, by, bz = x + dx * 0.1, dy * 0.1, 5.05
        P.box(f"cam_{i}_mount", "dark_metal", (0.04, 0.04, 0.12), loc=(x, 0, 5.1))
        P.box(f"cam_{i}_body", "white_plastic", (0.12, 0.32, 0.12), loc=(bx, by, bz), rot=(12, 0, ry), bevel=0.02, seg=2)
        P.box(f"cam_{i}_shield", "white_plastic", (0.16, 0.38, 0.012), loc=(bx, by, bz + 0.075), rot=(12, 0, ry))
        lx, ly = bx + dx * 0.165, by + dy * 0.165
        P.cyl(f"cam_{i}_lens", "cam_eye", 0.04, 0.02, loc=(lx, ly, bz - 0.035), rot=(102, 0, ry), segs=16)
        P.light(f"Light_Eye_{i}", (lx + dx * 0.03, ly + dy * 0.03, bz - 0.04), color=(1.0, 0.08, 0.08), energy=0.25, range=0.8)
    P.lathe("dome", "white_plastic", [(0.0, 4.68), (0.1, 4.7), (0.12, 4.78), (0.12, 4.86)], loc=(0, -0.2, 0), segs=20)
    P.lathe("dome_glass", "smoke_glass", [(0.0, 4.62), (0.06, 4.63), (0.098, 4.68), (0.0, 4.69)], loc=(0, -0.2, 0), segs=20)
    P.box("dome_arm", "dark_metal", (0.05, 0.16, 0.05), loc=(0, -0.11, 4.86))
    P.box("junction_box", "paint", (0.34, 0.2, 0.5), loc=(0, -0.17, 2.4), base=True, bevel=0.015, seg=2)
    P.box("meridian_plate", "sign", (0.3, 0.006, 0.18), loc=(0, -0.273, 2.62), base=True, uv_boost=3.0)
    P.box("box_led", "led", (0.04, 0.006, 0.02), loc=(0.12, -0.272, 2.5))
    P.box("solar", "solar", (0.7, 0.45, 0.02), loc=(0, 0.25, 5.6), rot=(25, 0, 0))
    P.box("solar_arm", "dark_metal", (0.04, 0.3, 0.04), loc=(0, 0.12, 5.48))
    P.collider = [("cyl", (0, 0), 0.16, 5.55), ("box", (0, -0.17, 2.65), (0.34, 0.22, 0.5))]


@model
def m_drone_mast(P: Prop):
    P.box("cabinet", "paint2", (0.9, 0.6, 1.3), loc=(0, 0.0, 0), base=True, bevel=0.03, seg=2)
    P.box("cabinet_door", "paint2", (0.7, 0.02, 1.0), loc=(0, -0.31, 0.15), base=True, bevel=0.005)
    P.box("cabinet_plate", "sign", (0.5, 0.006, 0.25), loc=(0, -0.323, 0.85), base=True, uv_boost=3.0)
    P.box("cabinet_stripe", "hazard", (0.92, 0.62, 0.12), loc=(0, 0, 0.0), base=True)
    P.box("cabinet_led", "led", (0.06, 0.006, 0.02), loc=(0.28, -0.322, 1.18))
    P.cyl("mast", "galv", 0.16, 6.3, loc=(0, 0, 1.3), r2=0.12, segs=18)
    P.cyl("mast_collar", "dark_metal", 0.22, 0.2, loc=(0, 0, 1.3), segs=18)
    P.sweep("conduit", "dark_metal", [(0.17, 0.0, 1.3), (0.165, 0, 4.0), (0.14, 0, 7.4)], 0.03, segs=8)
    # charging pad: hexagonal deck on brackets, two LED rings, beacon
    H = 7.6
    hexp = [(math.cos(math.radians(60 * i)) * 0.95, math.sin(math.radians(60 * i)) * 0.95) for i in range(6)]
    P.prism("pad_deck", "paint", hexp, 0.1, loc=(0, 0, H), rot=(90, 0, 0), bevel=0.02)
    P.prism("pad_rim", "hazard", [(math.cos(math.radians(60 * i)) * 0.99, math.sin(math.radians(60 * i)) * 0.99) for i in range(6)], 0.04,
            loc=(0, 0, H - 0.06), rot=(90, 0, 0))
    P.cyl("pad_ring_outer", "led", 0.7, 0.012, loc=(0, 0, H + 0.05), segs=36)
    P.cyl("pad_core", "paint", 0.62, 0.016, loc=(0, 0, H + 0.05), segs=36)
    P.cyl("pad_ring_inner", "led", 0.3, 0.022, loc=(0, 0, H + 0.05), segs=28)
    P.cyl("pad_center", "dark_metal", 0.24, 0.026, loc=(0, 0, H + 0.05), segs=28)
    for i in range(3):
        a = math.radians(30 + 120 * i)
        P.sweep(f"pad_strut_{i}", "galv", [(0, 0, H - 1.2), (math.cos(a) * 0.75, math.sin(a) * 0.75, H - 0.06)], 0.04, segs=8)
    P.cyl("beacon_base", "dark_metal", 0.06, 0.08, loc=(0.82, 0, H + 0.05), segs=14)
    P.lathe("beacon", "beacon_red", [(0.0, H + 0.13), (0.05, H + 0.13), (0.05, H + 0.2), (0.0, H + 0.24)], loc=(0.82, 0, 0), segs=14)
    # parked courier drone
    dz = H + 0.08
    P.box("drone_body", "white_plastic", (0.4, 0.5, 0.14), loc=(0, 0, dz), base=True, bevel=0.04, seg=3)
    P.box("drone_cargo", "paint", (0.32, 0.36, 0.18), loc=(0, 0, dz + 0.14), base=True, bevel=0.02, seg=2)
    P.cyl("drone_cam", "cam_eye", 0.04, 0.03, loc=(0, -0.26, dz + 0.07), rot=(90, 0, 0), segs=14)
    for i in range(4):
        a = math.radians(45 + 90 * i)
        ex, ey = math.cos(a) * 0.55, math.sin(a) * 0.55
        P.sweep(f"drone_arm_{i}", "black_plastic", [(math.cos(a) * 0.15, math.sin(a) * 0.15, dz + 0.08), (ex, ey, dz + 0.12)], 0.022, segs=8)
        P.cyl(f"drone_motor_{i}", "dark_metal", 0.04, 0.06, loc=(ex, ey, dz + 0.1), segs=14)
        P.cyl(f"drone_rotor_{i}", "black_plastic", 0.2, 0.008, loc=(ex, ey, dz + 0.165), segs=24)
        P.cyl(f"drone_led_{i}", "led", 0.012, 0.012, loc=(ex, ey, dz + 0.085), segs=8)
    P.light("Light_Beacon", (0.82, 0, H + 0.2), color=(1.0, 0.05, 0.05), energy=4, range=6.0)
    P.light("Light_Pad", (0, 0, H + 0.3), color=(0.2, 0.8, 1.0), energy=20, range=4.0)
    P.collider = [("box", (0, 0, 0.65), (0.9, 0.6, 1.3)), ("cyl", (0, 0), 0.2, H)]
