"""Kanzaki Tsubame-4 (1994), Hoshikawa Security cruiser: the hero car.

A fictional four-door sedan, converted for Hoshikawa Security: push bar, roof light bar,
A-pillar spotlight, rear partition and a dash terminal, bolt-on overfenders. These are the
exact numbers of the original tools/car builder, so the toolkit rebuilds it unchanged.
Custom parts (the security conversion) are the functions at the bottom.
"""
import math

FRONT, REAR = -2.20, 2.24
AXLES = [-1.33, 1.32]
B_LINE = 0.215
DRIVER_X = -0.37

SPEC = {
    "id": "tsubame",
    "name": "Kanzaki Tsubame-4, Hoshikawa Security cruiser",
    "class": "sedan",
    "role": "hero / police",
    "front": FRONT, "rear": REAR, "axles": AXLES,
    "wheel_r": 0.332, "arch_r": 0.368, "track": 1.585, "body_drop": 0.03, "height": 1.39,
    "mass_kg": 1280,
    "center_of_mass": (0.0, -0.05, 0.48),
    "suspension_suggestion": {"rest_length": 0.14, "travel": 0.12, "stiffness": 38.0, "max_force": 9000.0,
                              "damping_compression": 0.9, "damping_relaxation": 1.4, "friction_slip": 2.8},
    "dimensions": {"length": 4.44, "width_body": 1.784, "width_overfenders": 1.87, "height_roof": 1.36, "height_lightbar": 1.467},
    "collider_zmax": 1.50,
    "lamps": {"head": (0.60, 0.632), "tail": (0.735, 0.825)},
    "lod": {"lod1_body": 8000, "lod1_wheel": 480, "lod2_body": 1300, "lod2_wheel": 60},
    "body": {
        "stations": [-2.20, -2.185, -2.15, -2.08, -1.95, -1.60, -1.00, -0.84, -0.77, -0.70,
                     -0.55, -0.35, -0.15, -0.02, 0.06, 0.40, 0.80, 0.92, 1.00, 1.15, 1.32, 1.50,
                     1.58, 1.66, 2.02, 2.14, 2.20, 2.235],
        "ztop": [(-2.20, 0.680), (-2.15, 0.738), (-2.05, 0.762), (-1.50, 0.810), (-0.84, 0.860), (-0.77, 0.880),
                 (-0.55, 0.990), (-0.35, 1.110), (-0.15, 1.250), (-0.02, 1.330), (0.06, 1.360), (0.30, 1.385),
                 (0.55, 1.388), (0.80, 1.372), (0.92, 1.335), (1.00, 1.295), (1.15, 1.205), (1.32, 1.100),
                 (1.50, 1.008), (1.58, 0.982), (1.66, 0.975), (2.02, 0.968), (2.14, 0.958), (2.20, 0.935), (2.235, 0.880)],
        "drop": [(-2.20, 0.012), (-0.84, 0.03), (-0.70, 0.065), (-0.15, 0.06), (0.06, 0.05), (0.80, 0.05),
                 (1.00, 0.08), (1.50, 0.06), (1.66, 0.015), (2.24, 0.012)],
        "wside": [(-2.20, 0.640), (-2.185, 0.720), (-2.15, 0.790), (-2.08, 0.836), (-1.95, 0.866), (-1.60, 0.884),
                  (0.30, 0.892), (1.66, 0.888), (2.02, 0.872), (2.14, 0.846), (2.20, 0.806), (2.235, 0.730)],
        "wroof": [(-2.20, 0.52), (-0.84, 0.60), (-0.70, 0.62), (-0.02, 0.655), (0.30, 0.665), (0.92, 0.66),
                  (1.50, 0.64), (1.66, 0.62), (2.24, 0.56)],
        "wg_in": [(-2.20, 0.04), (-0.84, 0.045), (-0.70, 0.05), (0.06, 0.055), (0.92, 0.055), (1.50, 0.05), (1.66, 0.045), (2.24, 0.04)],
        "zbelt": [(-2.20, 0.625), (-2.15, 0.690), (-2.0, 0.730), (-1.0, 0.810), (-0.70, 0.840), (0.30, 0.870),
                  (1.32, 0.900), (1.66, 0.915), (2.14, 0.920), (2.235, 0.850)],
        "zfloor": [(-2.20, 0.300), (-2.15, 0.250), (-1.95, 0.205), (-1.70, 0.180), (1.75, 0.185), (2.02, 0.215),
                   (2.20, 0.285), (2.235, 0.33)],
        "zrock": [(-2.20, 0.330), (-2.0, 0.300), (2.0, 0.305), (2.235, 0.36)],
        "rake": [(-2.20, 0.10), (-2.15, 0.05), (-2.08, 0.0), (2.14, 0.0), (2.20, 0.03), (2.235, 0.05)],
        "cab": ((-0.86, -0.70), (1.52, 1.66)),
    },
    "panels": {
        "doors": [
            {"name": "F", "kind": "front", "front": -0.835, "line": B_LINE, "frame_rear": 0.185},
            {"name": "R", "kind": "rear", "line": B_LINE, "frame_front": 0.250, "top_rear": 0.80, "rear": 1.005, "arch": True},
        ],
        "windshield": {"kind": "top", "y0": -0.735, "y1": -0.035, "inset": 0.06, "taper": 0.03, "z0": 0.80, "z1": 1.7},
        "rear_window": {"kind": "top", "y0": 1.015, "y1": 1.52, "inset": 0.065, "z0": 0.90, "z1": 1.7},
        "hood": {"y0": -2.125, "y1": -0.82, "inset": 0.032, "z0": 0.62, "z1": 1.2, "n": 14},
        "trunk": {"y0": 1.635, "y1": 2.175, "inset": 0.034, "z0": 0.80, "z1": 1.2, "n": 8},
        "bumpers": [{"y": -1.79, "z": 0.548, "end": -2.6}, {"y": 1.86, "z": 0.552, "end": 2.6}],
        "fuel_door": {"y0": 1.55, "y1": 1.73, "z0": 0.70, "z1": 0.82, "r": 0.03, "side": 1},
        "apertures": [
            {"sides": [{"rect": [0.385, 0.565, 0.84, 0.700, 0.018], "a0": -2.5, "a1": -2.06}]},       # headlamps
            {"rect": [-0.345, 0.575, 0.345, 0.690, 0.012], "a0": -2.5, "a1": -2.10},                 # grille
            {"rect": [-0.86, 0.765, 0.86, 0.885, 0.015], "a0": 2.10, "a1": 2.6},                     # tail bar
            {"sides": [{"rect": [0.22, 0.300, 0.56, 0.425, 0.03], "a0": -2.6, "a1": -2.05},           # intakes
                       {"rect": [0.62, 0.455, 0.80, 0.505, 0.012], "a0": -2.6, "a1": -2.10}]},        # indicators
            {"sides": [{"rect": [0.43, 0.215, 0.61, 0.285, 0.03], "a0": 2.0, "a1": 2.6}]},            # exhaust cut-outs
        ],
        "lenses": [
            {"sides": [{"name": "headlight_lens", "group": "lens_clear", "rect": [0.385, 0.565, 0.84, 0.700, 0.018], "a0": -2.5, "a1": -2.06},
                       {"name": "indicator_lens", "group": "lens_amber", "rect": [0.62, 0.455, 0.80, 0.505, 0.012], "a0": -2.6, "a1": -2.10}]},
            {"name": "taillight_lens", "group": "lens_red", "rect": [-0.86, 0.765, 0.86, 0.885, 0.015], "a0": 2.10, "a1": 2.6},
        ],
        "plates": {"front": {"w": 0.185, "z0": 0.330, "z1": 0.505, "r": 0.012, "depth": 0.016, "ray_z": 0.42},
                   "rear": {"w": 0.195, "z0": 0.330, "z1": 0.505, "r": 0.012, "depth": 0.016, "ray_z": 0.42}},
    },
    "wheel": {"width": 0.215, "rim_r": 0.203, "lip_r": 0.212, "style": "split6", "lugs": 5},
    "parts": [
        {"kit": "headlights", "x": 0.6, "z": 0.632,
         "housing": {"size": (0.40, 0.20, 0.13), "back": 0.15, "ray_z": 0.63},
         "elements": [{"type": "reflector", "x": 0.700, "r": 0.060}, {"type": "reflector", "x": 0.505, "r": 0.052, "projector": True}],
         "drl": {"z": 0.582, "size": (0.36, 0.012, 0.010)},
         "indicator": {"x": 0.71, "z": 0.48, "size": (0.17, 0.04, 0.045)}},
        {"kit": "taillights", "zc": 0.825, "housing": {"w": 1.54, "d": 0.16, "h": 0.11, "back": 0.12},
         "segments": [{"name": "tail_brake", "x": 0.735, "w": 0.20, "group": "emitter_tail"},
                      {"name": "tail_indicator", "x": 0.565, "w": 0.10, "group": "emitter_amber"},
                      {"name": "tail_reverse", "x": 0.445, "w": 0.10, "group": "emitter_reverse"}],
         "reflector": {"x": 0.62, "w": 0.46}, "fins": [0.835, 0.625, 0.505, 0.39],
         "ribs": {"n": 4, "w": 0.76}, "third": {"y": 1.06, "roof_y": 1.03, "size": (0.34, 0.035, 0.022), "tilt": -38}},
        {"kit": "grille", "z": 0.632, "w": 0.70, "h": 0.13, "slats": {"n": 5, "z0": 0.588, "pitch": 0.022, "w": 0.68}, "badge": 0.032,
         "intakes": {"x": 0.39, "z": 0.362, "ray_z": 0.36, "w": 0.34, "h": 0.13, "bars": 4, "x0": 0.26, "pitch": 0.085}},
        {"custom": "push_bar"},
        {"kit": "window_seals"},
        {"kit": "body_mouldings", "z": 0.505, "strips": [("F", -0.835 + 0.03, B_LINE - 0.012), ("R", B_LINE + 0.012, 0.95)]},
        {"kit": "fender_flares"},
        {"kit": "mirrors", "y": -0.66},
        {"kit": "door_handles", "handles": [("F", B_LINE - 0.17, True), ("R", 0.86, False)]},
        {"kit": "wipers", "arms": [(0.26, 0.58), (-0.20, 0.50)], "y": -0.745,
         "cowl": {"y": -0.795, "ray_y": -0.80, "size": (1.30, 0.06, 0.012), "tilt": -12}},
        {"kit": "plates", "front": {"z": 0.4175, "ray_z": 0.42, "size": (0.33, 0.006, 0.165)},
         "rear": {"z": 0.4175, "ray_z": 0.42, "size": (0.33, 0.006, 0.165)}, "lamp": {"z": 0.522, "ray_z": 0.52, "size": (0.10, 0.012, 0.012)}},
        {"kit": "exhaust", "x": 0.52, "z": 0.25,
         "pipe": [(0.0, -1.20, 0.205), (0.0, -0.20, 0.205), (0.05, 0.60, 0.205), (0.30, 1.35, 0.215), (0.45, 1.70, 0.23)],
         "branch_start": {"L": (0.45, 1.75, 0.235), "R": (0.30, 1.75, 0.235)}, "branch_mid_y": 1.98,
         "silencer": ((0.0, 1.78, 0.235), (0.80, 0.30, 0.13)), "catalyst": ((0.0, -0.55, 0.215), (0.16, 0.36, 0.09))},
        {"custom": "roof_gear"},
        {"kit": "mudflaps", "zt": 0.33},
        {"kit": "boxes", "items": [
            ("underbody_tray", "underbody", (0, 0.05, 0.184), (1.40, 3.50, 0.012), 0.01),
            ("underbody_tunnel", "underbody", (0, -0.20, 0.215), (0.22, 2.4, 0.07), 0.03, 3),
            ("fuel_tank", "underbody_metal", (0.0, 1.20, 0.215), (1.0, 0.45, 0.07), 0.03, 3),
            ("crossmember_F", "underbody_metal", (0, AXLES[0] + 0.05, 0.24), (1.05, 0.10, 0.07), 0.012),
            ("crossmember_R", "underbody_metal", (0, AXLES[1] - 0.05, 0.24), (1.05, 0.10, 0.07), 0.012)]},
        {"kit": "wheel_wells", "inner": 0.53, "outer": 0.86},
        {"kit": "suspension"},
        # ---- interior (right-hand drive)
        {"kit": "boxes", "items": [
            ("floor_carpet", "interior_carpet", (0, 0.30, 0.235), (1.58, 2.35, 0.02)),
            ("floor_tunnel", "interior_carpet", (0, 0.05, 0.235 + 0.06), (0.24, 1.70, 0.12), 0.04, 3),
            ("dash_lower", "interior_plastic", (0, -0.56, 0.68), (1.50, 0.30, 0.28), 0.03, 3),
            ("dash_top", "interior_dark", (0, -0.56 - 0.07, 0.855), (1.52, 0.42, 0.07), 0.03, 3, 8),
            ("dash_binnacle", "interior_dark", (DRIVER_X, -0.56 + 0.10, 0.905), (0.40, 0.14, 0.10), 0.035, 3),
            ("dash_gauges", "screen", (DRIVER_X, -0.56 + 0.168, 0.885), (0.34, 0.004, 0.07), 0.01),
            ("center_stack", "interior_plastic", (0, -0.56 + 0.10, 0.66), (0.26, 0.16, 0.30), 0.02),
            ("radio", "screen", (0, -0.56 + 0.183, 0.72), (0.19, 0.006, 0.055), 0.004),
            ("vent_R", "black_trim", (-0.60, -0.56 + 0.152, 0.79), (0.14, 0.006, 0.05), 0.006),
            ("vent_L", "black_trim", (0.60, -0.56 + 0.152, 0.79), (0.14, 0.006, 0.05), 0.006),
            ("center_console", "interior_plastic", (0, -0.05, 0.39), (0.22, 0.70, 0.18), 0.025, 3)]},
        {"kit": "shifter"},
        {"kit": "boxes", "items": [
            ("handbrake", "interior_dark", (0.02, 0.05, 0.50), (0.035, 0.24, 0.035), 0.012, 2, 14),
            # security terminal (MDT) on a stand in front of the console
            ("terminal_stand", "black_metal", (0.02, -0.33, 0.62), (0.03, 0.03, 0.22)),
            ("terminal", "interior_dark", (0.02, -0.30, 0.78), (0.30, 0.025, 0.20), 0.01, 2, -20),
            ("terminal_screen", "screen", (0.02, -0.285, 0.784), (0.27, 0.004, 0.17), 0.0, 2, -20)]},
        {"kit": "steering", "c": (DRIVER_X, -0.33, 0.86), "tilt": -62, "column_end": (DRIVER_X, -0.52, 0.80)},
        {"kit": "seat", "name": "seat_FR", "x": DRIVER_X, "y": 0.03, "z": 0.40},
        {"kit": "seat", "name": "seat_FL", "x": -DRIVER_X, "y": 0.03, "z": 0.40},
        {"kit": "seat", "name": "seat_rear", "x": 0.0, "y": 0.78, "z": 0.38, "w": 1.30, "back_h": 0.56, "recline": 22, "bench": True},
        {"custom": "partition"},
        {"kit": "boxes", "items": [
            ("parcel_shelf", "interior_dark", (0, 1.36, 0.93), (1.40, 0.40, 0.02), 0.0, 2, -4),
            ("rearview_mirror", "interior_dark", (0, -0.12, 1.25), (0.24, 0.03, 0.065), 0.012, 2)]},
        {"kit": "door_cards"},
        {"kit": "headliner", "z_min": 1.22, "y0": -0.25, "y1": 1.05},
        {"kit": "glass_frit"},
    ],
}


# ------------------------------------------------------------------ custom parts (the security conversion)


def push_bar(p):
    """Hoshikawa Security push bar: two uprights and a top hoop bolted through the bumper."""
    import bmesh
    from vkit import panels as P
    from vkit.geom import bm_tube_path
    from vkit.panels import frange
    from vkit.shapes import box, obj
    out = []
    yf = P.front_face_y(0.0, 0.40) - 0.095
    hoop = []
    for t in frange(0, 1, 13):
        a = math.pi * t
        x = -0.36 * math.cos(a)
        z = 0.30 + 0.30 * math.sin(a) ** 0.5
        hoop.append((x, yf - 0.012 * math.sin(a), z))
    bm = bmesh.new()
    bm_tube_path(bm, hoop, 0.024, 10)
    for sx in (-1, 1):
        bm_tube_path(bm, [(sx * 0.20, yf, 0.26), (sx * 0.20, yf, 0.585)], 0.022, 10)
        bm_tube_path(bm, [(sx * 0.20, yf, 0.35), (sx * 0.20, yf + 0.13, 0.35)], 0.018, 8)
    bm_tube_path(bm, [(-0.33, yf, 0.40), (0.33, yf, 0.40)], 0.018, 8)
    ob = obj("push_bar", bm)
    out.append((ob.name, "black_metal", ob))
    for sx, side in ((1, "L"), (-1, "R")):
        pad = box(f"push_bar_pad_{side}", (sx * 0.20, yf - 0.028, 0.47), (0.07, 0.02, 0.18), bevel=0.008)
        out.append((pad.name, "rubber", pad))
    return out


def roof_gear(p):
    """Light bar on brackets, whip antenna, comms puck, A-pillar spotlight."""
    import bmesh
    from mathutils import Vector
    from vkit import panels as P
    from vkit.geom import bm_box, bm_cyl, bm_tube_path
    from vkit.shapes import box, lathe, mods, obj
    out = []
    yb = 0.30
    zr, n = P.top_z(0.0, yb)
    zb = zr + 0.028
    for sx, side in ((1, "L"), (-1, "R")):
        x = sx * 0.56
        z0, n = P.top_z(x, yb)
        ft = box(f"lightbar_foot_{side}", (x, yb, (z0 + zb) / 2), (0.06, 0.16, zb - z0 + 0.02), bevel=0.008)
        out.append((ft.name, "black_metal", ft))
    base = box("lightbar_base", (0, yb, zb + 0.012), (1.26, 0.28, 0.024), bevel=0.01, seg=2)
    out.append((base.name, "black_trim", base))
    for sx, side, grp in ((1, "L", "lightbar_lens_red"), (-1, "R", "lightbar_lens_blue")):
        bm = bmesh.new()
        bm_box(bm, (sx * 0.34, yb, zb + 0.058), (0.52, 0.24, 0.07))
        ln = obj(f"lightbar_lens_{side}", bm)
        mods(ln, bevel=0.03, seg=4)
        out.append((ln.name, grp, ln))
        for i in range(4):
            em = box(f"lightbar_led_{side}{i}", (sx * (0.15 + i * 0.12), yb, zb + 0.05), (0.08, 0.17, 0.035))
            out.append((em.name, "emitter_red" if sx > 0 else "emitter_blue", em))
    cm = box("lightbar_center", (0, yb, zb + 0.06), (0.14, 0.24, 0.075), bevel=0.012, seg=3)
    out.append((cm.name, "lightbar_center", cm))
    zt, n = P.top_z(-0.42, 1.98)
    bm = bmesh.new()
    bm_cyl(bm, (-0.42, 1.98, zt + 0.012), 0.016, 0.024, seg=12)
    bm_tube_path(bm, [(-0.42, 1.98, zt + 0.02), (-0.42, 2.00, zt + 0.45), (-0.42, 2.04, zt + 0.86)], 0.0025, 5)
    ant = obj("antenna_whip", bm)
    out.append((ant.name, "black_metal", ant))
    zp, n = P.top_z(0.0, 0.78)
    puck = lathe("antenna_puck", [(0.0, 0.0), (0.055, 0.0), (0.05, 0.02), (0.03, 0.04), (0.0, 0.045)], (0, 0.78, zp - 0.002), "Z", 20)
    out.append((puck.name, "black_trim", puck))
    # A-pillar spotlight (driver's side, right-hand drive: -X)
    x, n = P.side_x(-0.42, P.z_belt(-0.42) + 0.08, -1)
    spot_c = Vector((x - 0.07, -0.47, P.z_belt(-0.42) + 0.12))
    bm = bmesh.new()
    bm_tube_path(bm, [(x - 0.005, -0.40, P.z_belt(-0.42) + 0.05), (x - 0.07, -0.42, P.z_belt(-0.42) + 0.08), tuple(spot_c + Vector((0, 0.04, -0.02)))], 0.010, 8)
    sb = obj("spotlight_bracket", bm)
    out.append((sb.name, "black_metal", sb))
    sp = lathe("spotlight_body", [(0.0, -0.06), (0.040, -0.06), (0.052, 0.0), (0.056, 0.03), (0.056, 0.035)], tuple(spot_c), "Y", 20, sign=-1)
    out.append((sp.name, "black_trim", sp))
    sl = lathe("spotlight_lens", [(0.0, 0.04), (0.052, 0.035)], tuple(spot_c), "Y", 20, sign=-1)
    out.append((sl.name, "emitter_head", sl))
    return out


def partition(p):
    """Security partition behind the front seats: frame + bars."""
    import bmesh
    from vkit.geom import bm_tube_path
    from vkit.panels import frange
    from vkit.shapes import obj
    bm = bmesh.new()
    yp = 0.40
    fr = [(-0.72, yp, 0.62), (-0.66, yp, 1.24), (0.66, yp, 1.24), (0.72, yp, 0.62)]
    bm_tube_path(bm, fr + [(-0.72, yp, 0.62)], 0.012, 6)
    for x in frange(-0.60, 0.60, 9):
        bm_tube_path(bm, [(x, yp, 0.63), (x, yp, 1.23)], 0.005, 5)
    for z in (0.80, 1.00):
        bm_tube_path(bm, [(-0.70, yp, z), (0.70, yp, z)], 0.005, 5)
    pt = obj("partition", bm)
    return [(pt.name, "black_metal", pt)]
