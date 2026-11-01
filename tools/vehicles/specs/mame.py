"""Kanzaki Mame K3 (1997): a five-door kei hatchback.

3.39 m x 1.475 m, the kei-class box: a short sloping hood, a steep screen, a tall flat roof
and a near-vertical hatch. Round headlamps with chrome bezels sit in a full-width black
panel with a slatted grille; the tail lamps are vertical stacks in the D pillars. Steel
13-inch wheels with hubcaps. The city's commonest car: delivery runners, night-shift
nurses, Score-reset fixers.
"""
FRONT, REAR = -1.695, 1.695
AXLES = [-1.135, 1.195]
B_LINE = 0.175
DRIVER_X = -0.30

SPEC = {
    "id": "mame",
    "name": "Kanzaki Mame K3 kei hatchback",
    "class": "kei",
    "role": "traffic",
    "front": FRONT, "rear": REAR, "axles": AXLES,
    "wheel_r": 0.272, "arch_r": 0.305, "track": 1.29, "body_drop": 0.02, "height": 1.50,
    "mass_kg": 720,
    "center_of_mass": (0.0, -0.08, 0.50),
    "suspension_suggestion": {"rest_length": 0.13, "travel": 0.13, "stiffness": 26.0, "max_force": 5200.0,
                              "damping_compression": 0.8, "damping_relaxation": 1.2, "friction_slip": 2.4},
    "collider_zmax": 1.6,
    "lamps": {"head": (0.52, 0.665), "tail": (0.66, 0.86)},
    "lod": {"lod2_min_piece": 0.2, "lod1_body": 8500, "lod1_wheel": 400, "lod2_body": 750, "lod2_wheel": 48},
    "body": {
        "stations": [-1.695, -1.68, -1.65, -1.59, -1.48, -1.28, -1.05, -0.95, -0.88, -0.80, -0.66, -0.50, -0.34, -0.20,
                     -0.08, 0.10, 0.50, 0.90, 1.20, 1.40, 1.52, 1.60, 1.65, 1.675, 1.69],
        "ztop": [(-1.695, 0.640), (-1.65, 0.715), (-1.55, 0.752), (-1.20, 0.800), (-0.95, 0.835), (-0.88, 0.858),
                 (-0.70, 0.975), (-0.50, 1.125), (-0.30, 1.290), (-0.16, 1.405), (-0.05, 1.462), (0.20, 1.488),
                 (1.10, 1.490), (1.40, 1.478), (1.55, 1.455), (1.62, 1.425), (1.66, 1.380), (1.69, 1.300)],
        "drop": [(-1.695, 0.010), (-0.95, 0.020), (-0.80, 0.050), (-0.20, 0.045), (1.40, 0.045), (1.62, 0.030), (1.69, 0.020)],
        "wside": [(-1.695, 0.650), (-1.68, 0.695), (-1.65, 0.718), (-1.59, 0.730), (-1.48, 0.734), (-1.00, 0.737),
                  (1.40, 0.737), (1.60, 0.730), (1.66, 0.712), (1.69, 0.680)],
        "wroof": [(-1.695, 0.46), (-0.95, 0.56), (-0.70, 0.60), (-0.30, 0.640), (0.30, 0.650), (1.40, 0.650),
                  (1.62, 0.630), (1.69, 0.600)],
        "wg_in": [(-1.695, 0.030), (-0.90, 0.035), (0.0, 0.040), (1.69, 0.040)],
        "zbelt": [(-1.695, 0.600), (-1.60, 0.675), (-1.30, 0.735), (-0.95, 0.790), (-0.70, 0.810), (0.50, 0.845),
                  (1.30, 0.880), (1.60, 0.895), (1.69, 0.870)],
        "zfloor": [(-1.695, 0.290), (-1.62, 0.225), (-1.45, 0.185), (1.45, 0.185), (1.62, 0.230), (1.69, 0.290)],
        "zrock": [(-1.695, 0.330), (-1.50, 0.295), (1.50, 0.295), (1.69, 0.335)],
        "rake": [(-1.695, 0.12), (-1.65, 0.06), (-1.59, 0.0), (1.60, 0.0), (1.66, 0.05), (1.69, 0.085)],
        "decimate": 0.45, "cab": ((-0.95, -0.82), (2.4, 2.5)),
        "section": {"rock_min_drop": 0.10, "side_frac": 0.5, "shoulder_in": 0.020},
        "cap_bulge": (-0.025, 0.02),
    },
    "panels": {
        "arch_x": 0.74, "arch_depth": 0.50, "gap_x": (0.40, 1.1), "win_x": (0.38, 1.1),
        "door_bottom": 0.315,
        "apillar_search": (-0.86, 0.0),
        "doors": [
            {"name": "F", "kind": "front", "front": -0.775, "line": B_LINE, "frame_rear": 0.145},
            {"name": "R", "kind": "rear", "line": B_LINE, "frame_front": 0.205, "top_rear": 0.78, "rear": 0.965,
             "arch": True, "arch_top": 0.60, "arch_gap": 0.03},
        ],
        "windows": [{"name": "quarter_glass", "y0": 1.035, "y1": 1.43, "slant": 0.05, "r": 0.02}],
        "windshield": {"kind": "top", "y0": -0.835, "y1": -0.24, "inset": 0.055, "taper": 0.025, "z0": 0.82, "z1": 1.8},
        "rear_window": {"kind": "rear", "zb": 0.975, "zt": 1.385, "wb": 0.555, "wt": 0.53, "r": 0.06, "a0": 1.50, "a1": 2.2},
        "hood": {"y0": -1.625, "y1": -0.905, "inset": 0.030, "z0": 0.56, "z1": 1.1, "n": 12, "piece_z": 0.65},
        "trunk": {"kind": "rear", "name": "hatch", "w": 0.585, "trapezoid": 0.555, "z0": 0.505, "z1": 1.44, "r": 0.07, "y0": 1.42, "y1": 2.2},
        "bumpers": [{"y": -1.50, "z": 0.520, "end": -2.0}, {"y": 1.555, "z": 0.495, "end": 2.0}],
        "fuel_door": {"y0": 1.26, "y1": 1.40, "z0": 0.70, "z1": 0.80, "r": 0.025, "side": -1},
        "apertures": [
            {"rect": [-0.635, 0.578, 0.635, 0.748, 0.03], "a0": -2.2, "a1": -1.62},                    # lamp + grille panel
            {"sides": [{"rect": [0.50, 0.420, 0.66, 0.465, 0.012], "a0": -2.2, "a1": -1.55},          # bumper indicators
                       {"rect": [0.16, 0.300, 0.40, 0.400, 0.03], "a0": -2.2, "a1": -1.55}]},         # bumper intakes
            {"sides": [{"rect": [0.615, 0.640, 0.715, 1.010, 0.02], "a0": 1.52, "a1": 2.2}]},         # tail lamp stacks
        ],
        "lenses": [
            {"sides": [{"name": "headlight_lens", "group": "lens_clear", "rect": [0.4375, 0.5845, 0.6025, 0.7495, 0.0825], "a0": -2.2, "a1": -1.62},
                       {"name": "indicator_lens", "group": "lens_amber", "rect": [0.50, 0.420, 0.66, 0.465, 0.012], "a0": -2.2, "a1": -1.55}]},
            {"sides": [{"name": "taillight_lens", "group": "lens_red", "rect": [0.615, 0.640, 0.715, 1.010, 0.02], "a0": 1.52, "a1": 2.2}]},
        ],
        "plates": {"front": {"w": 0.165, "z0": 0.315, "z1": 0.465, "r": 0.012, "depth": 0.014, "ray_z": 0.39},
                   "rear": {"w": 0.165, "z0": 0.565, "z1": 0.715, "r": 0.012, "depth": 0.014, "ray_z": 0.64}},
    },
    "wheel": {"barrel_seg": 32, "disc_seg_per_hole": 6, "width": 0.150, "rim_r": 0.166, "lip_r": 0.174, "style": "steel", "holes": 6, "hole_r": 0.016, "lugs": 4,
              "lug_r": 0.045, "cap_r": 0.055, "disc_r": 0.115, "profile": "v2", "tyre_seg": 40, "dish": 0.030, "tread_pitch": 3},
    "parts": [
        {"kit": "boxes", "items": [("lamp_panel", "black_trim", (0, -1.625, 0.663), (1.24, 0.05, 0.165), 0.012)]},
        {"kit": "headlights", "x": 0.52, "z": 0.667,
         "elements": [{"type": "reflector", "x": 0.52, "r": 0.074, "seg": 24, "ring": True}],
         "indicator": {"x": 0.58, "z": 0.4425, "size": (0.15, 0.04, 0.038), "depth": 0.028}},
        {"custom": "lamp_bezels"},
        {"kit": "grille", "z": 0.667, "w": 0.62, "h": 0.15, "back": 0.05, "slats": {"n": 4, "z0": 0.625, "pitch": 0.028, "w": 0.60}, "badge": 0.026,
         "intakes": {"x": 0.28, "z": 0.35, "w": 0.24, "h": 0.10, "bars": 3, "x0": 0.20, "pitch": 0.08}},
        {"kit": "taillights", "zc": 0.825,
         "housing": {"sides": True, "x": 0.665, "w": 0.12, "d": 0.12, "h": 0.40, "back": 0.09, "z": 0.825},
         "segments": [{"name": "tail_brake", "x": 0.665, "w": 0.085, "h": 0.15, "z": 0.915, "group": "emitter_tail"},
                      {"name": "tail_indicator", "x": 0.665, "w": 0.085, "h": 0.085, "z": 0.79, "group": "emitter_amber"},
                      {"name": "tail_reverse", "x": 0.665, "w": 0.085, "h": 0.07, "z": 0.70, "group": "emitter_reverse"}],
         "third": {"y": 1.50, "roof_y": 1.50, "size": (0.30, 0.03, 0.024), "tilt": 0, "dz": 0.005}},
        {"kit": "window_seals", "fixed": True},
        {"kit": "body_mouldings", "z": 0.52, "h": 0.035, "proud": 0.007,
         "strips": [("F", -0.745, B_LINE - 0.012), ("R", B_LINE + 0.012, 0.86)]},
        {"kit": "arch_lips", "width": 0.022, "group": "black_trim"},
        {"kit": "mirrors", "y": -0.71, "dz": 0.06, "size": (0.15, 0.07, 0.10), "reach": 0.11, "group": "black_trim"},
        {"kit": "door_handles", "handles": [("F", B_LINE - 0.15, True), ("R", 0.80, False)], "dz": 0.07, "group": "black_trim"},
        {"kit": "wipers", "arms": [(0.20, 0.52), (-0.24, 0.46)], "y": -0.855,
         "cowl": {"y": -0.90, "ray_y": -0.905, "size": (1.12, 0.05, 0.012), "tilt": -14}},
        {"kit": "plates", "front": {"z": 0.39, "ray_z": 0.39, "size": (0.30, 0.006, 0.145)},
         "rear": {"z": 0.64, "ray_z": 0.64, "size": (0.30, 0.006, 0.145)}, "lamp": {"z": 0.735, "ray_z": 0.735, "size": (0.09, 0.012, 0.012)}},
        {"kit": "exhaust", "x": 0.42, "z": 0.25, "dual": False, "side": -1, "r": 0.026,
         "pipe": [(0.0, -1.10, 0.20), (0.0, -0.20, 0.20), (-0.10, 0.60, 0.20), (-0.30, 1.30, 0.21)],
         "branch_start": {"R": (-0.30, 1.30, 0.21)}, "branch_mid_y": 1.48,
         "silencer": ((-0.22, 1.38, 0.23), (0.42, 0.24, 0.11)), "catalyst": ((0.0, -0.70, 0.205), (0.13, 0.28, 0.08))},
        {"kit": "mudflaps", "zt": 0.30, "zb": 0.13, "inset": 0.10, "w": 0.15, "axles": "R"},
        {"kit": "boxes", "items": [
            ("underbody_tray", "underbody", (0, 0.03, 0.180), (1.20, 2.90, 0.012), 0.01),
            ("underbody_tunnel", "underbody", (0, -0.30, 0.205), (0.18, 1.6, 0.05), 0.02, 3),
            ("fuel_tank", "underbody_metal", (0.0, 0.85, 0.205), (0.80, 0.40, 0.06), 0.025, 3),
            ("crossmember_F", "underbody_metal", (0, AXLES[0] + 0.05, 0.225), (0.90, 0.09, 0.06), 0.012),
            ("crossmember_R", "underbody_metal", (0, AXLES[1] - 0.05, 0.225), (0.90, 0.09, 0.06), 0.012)]},
        {"kit": "wheel_wells", "inner": 0.44, "outer": 0.72, "hub_x": 0.58},
        {"kit": "suspension", "hub_x": 0.58, "top_x": 0.53, "top_dz": 0.32, "arm_x": 0.24, "arm_dy": 0.13, "shaft_x": 0.10,
         "spring_r": 0.050, "driven": "F"},
        # ---- interior (right-hand drive, column shift)
        {"kit": "boxes", "items": [
            ("floor_carpet", "interior_carpet", (0, 0.20, 0.225), (1.30, 2.10, 0.02)),
            ("dash_lower", "interior_plastic", (0, -0.70, 0.66), (1.30, 0.26, 0.24), 0.03, 3),
            ("dash_top", "interior_dark", (0, -0.77, 0.83), (1.32, 0.36, 0.06), 0.025, 3, 10),
            ("dash_binnacle", "interior_dark", (DRIVER_X, -0.58, 0.875), (0.32, 0.12, 0.09), 0.03, 3),
            ("dash_gauges", "screen", (DRIVER_X, -0.519, 0.858), (0.27, 0.004, 0.06), 0.01),
            ("center_stack", "interior_plastic", (0, -0.58, 0.66), (0.22, 0.12, 0.24), 0.02),
            ("radio", "screen", (0, -0.518, 0.70), (0.17, 0.006, 0.05), 0.004),
            ("vent_R", "black_trim", (-0.50, -0.548, 0.77), (0.12, 0.006, 0.045), 0.006),
            ("vent_L", "black_trim", (0.50, -0.548, 0.77), (0.12, 0.006, 0.045), 0.006),
            ("glovebox", "interior_plastic", (0.30, -0.56, 0.64), (0.40, 0.04, 0.14), 0.01),
            ("parcel_shelf", "interior_dark", (0, 1.30, 0.90), (1.20, 0.44, 0.02), 0.0, 2, -3),
            ("rearview_mirror", "interior_dark", (0, -0.22, 1.36), (0.20, 0.03, 0.055), 0.012, 2)]},
        {"kit": "steering", "c": (DRIVER_X, -0.42, 0.84), "tilt": -60, "r": 0.175, "column_end": (DRIVER_X, -0.62, 0.78)},
        {"kit": "seat", "name": "seat_FR", "x": DRIVER_X, "y": -0.02, "z": 0.40, "w": 0.46, "back_h": 0.60},
        {"kit": "seat", "name": "seat_FL", "x": -DRIVER_X, "y": -0.02, "z": 0.40, "w": 0.46, "back_h": 0.60},
        {"kit": "seat", "name": "seat_rear", "x": 0.0, "y": 0.72, "z": 0.37, "w": 1.12, "back_h": 0.55, "recline": 18, "bench": True,
         "headrest_x": [0.32]},
        {"kit": "door_cards", "armrest_z": 0.60, "ray_z": 0.62, "inset": 0.07},
        {"kit": "headliner", "z_min": 1.36, "y0": -0.30, "y1": 1.45},
        {"kit": "glass_frit", "which": ("windscreen", "rear_window"), "w": 0.04},
    ],
}


def lamp_bezels(p):
    """Chrome bezel rings round the round headlamps."""
    from vkit import panels as P
    from vkit.shapes import lathe
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        x, z = sx * 0.52, 0.667
        y = P.front_face_y(x, z)
        b = lathe(f"headlight_bezel_{side}", [(0.084, 0.012), (0.092, 0.004), (0.097, -0.006), (0.093, -0.012), (0.086, -0.008)],
                  (x, y, z), "Y", 32)
        out.append((b.name, "chrome", b))
    return out
