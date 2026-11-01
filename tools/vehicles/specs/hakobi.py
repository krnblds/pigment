"""Ishimaru Hakobi LH-200 (1996): a cab-over panel van.

4.69 m x 1.69 m x 1.97 m. The front wheels sit under the cab, so the doors step up over
the arches; a near-flat nose with rectangular lamps and a slatted grille, a steep raked
windscreen, slab sides with no rear glass (a panel van: the sides are the livery), a sliding
side door, a top-hinged tailgate, vertical corner tail lamps, a roof rack. The workhorse of
the night economy: Dreamlink sleep-pod couriers, Noctis collection vans, parcel runners.
"""
FRONT, REAR = -2.30, 2.39
AXLES = [-1.50, 0.85]
DRIVER_X = -0.40

SPEC = {
    "id": "hakobi",
    "name": "Ishimaru Hakobi LH-200 panel van",
    "class": "van",
    "role": "traffic / delivery",
    "front": FRONT, "rear": REAR, "axles": AXLES,
    "wheel_r": 0.318, "arch_r": 0.352, "track": 1.46, "body_drop": 0.03, "height": 1.97,
    "mass_kg": 1650,
    "center_of_mass": (0.0, -0.20, 0.70),
    "suspension_suggestion": {"rest_length": 0.16, "travel": 0.14, "stiffness": 42.0, "max_force": 12000.0,
                              "damping_compression": 1.0, "damping_relaxation": 1.6, "friction_slip": 2.3},
    "collider_zmax": 2.20,
    "lamps": {"head": (0.66, 0.83), "tail": (0.77, 0.95)},
    "ray": {"x": 2.0, "z": 3.0, "y": 4.0},
    "lod": {"lod2_min_piece": 0.2, "lod1_body": 9000, "lod1_wheel": 420, "lod2_body": 750, "lod2_wheel": 48},
    "body": {
        "stations": [-2.30, -2.29, -2.27, -2.24, -2.20, -2.13, -2.05, -1.96, -1.87, -1.78, -1.70, -1.62, -1.52, -1.35,
                     -1.00, -0.50, 0.00, 0.50, 1.00, 1.50, 2.00, 2.24, 2.32, 2.365, 2.385],
        "ztop": [(-2.30, 0.990), (-2.27, 1.040), (-2.20, 1.090), (-2.12, 1.180), (-1.96, 1.430), (-1.80, 1.680),
                 (-1.68, 1.850), (-1.58, 1.925), (-1.45, 1.955), (-1.00, 1.968), (2.20, 1.968), (2.32, 1.950),
                 (2.365, 1.915), (2.385, 1.860)],
        "drop": [(-2.30, 0.012), (-2.20, 0.020), (-1.80, 0.050), (-1.50, 0.040), (2.30, 0.035), (2.385, 0.020)],
        "wside": [(-2.30, 0.770), (-2.29, 0.805), (-2.27, 0.828), (-2.24, 0.840), (-2.10, 0.845), (2.30, 0.845),
                  (2.36, 0.835), (2.385, 0.815)],
        "wroof": [(-2.30, 0.66), (-2.12, 0.71), (-1.80, 0.755), (-1.50, 0.775), (2.30, 0.785), (2.385, 0.765)],
        "wg_in": [(-2.30, 0.020), (2.385, 0.022)],
        "zbelt": [(-2.30, 0.950), (-2.24, 1.010), (-2.10, 1.040), (-1.60, 1.060), (2.30, 1.080), (2.385, 1.060)],
        "zfloor": [(-2.30, 0.380), (-2.24, 0.320), (-2.05, 0.290), (2.20, 0.290), (2.33, 0.320), (2.385, 0.380)],
        "zrock": [(-2.30, 0.420), (-2.0, 0.400), (2.20, 0.400), (2.385, 0.430)],
        "rake": [(-2.30, 0.035), (-2.24, 0.0), (2.30, 0.0), (2.385, 0.025)],
        "decimate": 0.45, "cab": ((-2.30, -2.22), (3.4, 3.5)),
        "section": {"rock_min_drop": 0.10, "side_frac": 0.45, "shoulder_in": 0.016, "belt_in": 0.006, "g9_bulge": (0.0, 0.006),
                    "crown_x": 0.70, "crown_drop": 0.15, "rake_pivot": 0.70, "wroof_min_inset": 0.05},
        "cap_bulge": (-0.03, 0.012),
        "creases": {6: 0.9, 3: 0.6, 7: 0.5, 9: 0.75},
    },
    "panels": {
        "arch_x": 0.84, "arch_depth": 0.56, "gap_x": (0.45, 1.2), "win_x": (0.45, 1.2),
        "door_bottom": 0.43,
        "apillar_search": (-2.20, -1.3),
        "doors": [
            {"name": "F", "kind": "front", "front": -2.02, "line": -1.16, "frame_rear": -1.19, "bottom": 0.76},
            {"name": "S", "kind": "rear", "line": -1.16, "frame_front": -1.12, "rear": 0.13, "rear_frame": "rail", "glass": False,
             "bottom": 0.43},
        ],
        "windshield": {"kind": "top", "y0": -2.135, "y1": -1.665, "inset": 0.050, "taper": 0.015, "z0": 1.0, "z1": 2.5},
        "rear_window": {"kind": "rear", "zb": 1.20, "zt": 1.80, "wb": 0.585, "wt": 0.575, "r": 0.055, "a0": 2.2, "a1": 2.9},
        "trunk": {"kind": "rear", "name": "tailgate", "w": 0.655, "trapezoid": 0.645, "z0": 0.60, "z1": 1.88, "r": 0.05, "y0": 2.15, "y1": 2.9},
        "bumpers": [{"y": -2.13, "z": 0.640, "end": -2.7}, {"y": 2.27, "z": 0.585, "end": 2.8, "width": 2.0}],
        "fuel_door": {"y0": 0.36, "y1": 0.52, "z0": 0.74, "z1": 0.86, "r": 0.025, "side": -1},
        "apertures": [
            {"sides": [{"rect": [0.505, 0.745, 0.805, 0.905, 0.016], "a0": -2.7, "a1": -2.16}]},          # headlamps
            {"rect": [-0.455, 0.755, 0.455, 0.895, 0.014], "a0": -2.7, "a1": -2.18},                     # grille
            {"sides": [{"rect": [0.56, 0.495, 0.78, 0.545, 0.012], "a0": -2.7, "a1": -2.08},             # bumper indicators
                       {"rect": [0.705, 0.640, 0.825, 1.140, 0.018], "a0": 2.22, "a1": 2.8}]},           # tail lamp stacks
        ],
        "lenses": [
            {"sides": [{"name": "headlight_lens", "group": "lens_clear", "rect": [0.505, 0.745, 0.805, 0.905, 0.016], "a0": -2.7, "a1": -2.16},
                       {"name": "indicator_lens", "group": "lens_amber", "rect": [0.56, 0.495, 0.78, 0.545, 0.012], "a0": -2.7, "a1": -2.08}]},
            {"sides": [{"name": "taillight_lens", "group": "lens_red", "rect": [0.705, 0.640, 0.825, 1.140, 0.018], "a0": 2.22, "a1": 2.8}]},
        ],
        "plates": {"front": {"w": 0.170, "z0": 0.345, "z1": 0.500, "r": 0.012, "depth": 0.014, "ray_z": 0.42},
                   "rear": {"w": 0.170, "z0": 0.665, "z1": 0.820, "r": 0.012, "depth": 0.014, "ray_z": 0.74}},
    },
    "wheel": {"barrel_seg": 32, "disc_seg_per_hole": 6, "width": 0.195, "rim_r": 0.191, "lip_r": 0.199, "style": "steel", "holes": 6, "hole_r": 0.020, "lugs": 6,
              "lug_r": 0.070, "cap_r": 0.060, "disc_r": 0.135, "profile": "v2", "tyre_seg": 40, "dish": 0.045, "tread_pitch": 3,
              "tread_depth": 0.006},
    "parts": [
        {"kit": "headlights", "x": 0.655, "z": 0.825,
         "housing": {"size": (0.32, 0.16, 0.17), "back": 0.10},
         "elements": [{"type": "rect", "x": 0.655, "w": 0.27, "h": 0.13, "facets": 5, "bulb": 0.016}],
         "indicator": {"x": 0.67, "z": 0.52, "size": (0.20, 0.04, 0.040)}},
        {"kit": "grille", "z": 0.825, "w": 0.90, "h": 0.15, "back": 0.05, "slats": {"n": 5, "z0": 0.773, "pitch": 0.026, "w": 0.88, "t": 0.008},
         "badge": 0.030},
        {"kit": "taillights", "zc": 0.89,
         "housing": {"sides": True, "x": 0.765, "w": 0.13, "d": 0.12, "h": 0.52, "back": 0.09, "z": 0.89},
         "segments": [{"name": "tail_brake", "x": 0.765, "w": 0.10, "h": 0.20, "z": 1.02, "group": "emitter_tail"},
                      {"name": "tail_indicator", "x": 0.765, "w": 0.10, "h": 0.10, "z": 0.86, "group": "emitter_amber"},
                      {"name": "tail_reverse", "x": 0.765, "w": 0.10, "h": 0.09, "z": 0.745, "group": "emitter_reverse"}],
         "fins": [], "third": {"y": 2.33, "roof_y": 2.33, "size": (0.40, 0.03, 0.03), "tilt": 0, "dz": 0.0}},
        {"kit": "window_seals"},
        {"kit": "body_mouldings", "z": 0.62, "h": 0.06, "proud": 0.010,
         "strips": [("F", -2.0, -1.175), ("S", -1.145, 0.12), ("Q", 0.15, 0.46), ("T", 1.25, 2.23)]},
        {"kit": "arch_lips", "width": 0.028, "group": "black_trim"},
        {"kit": "mirrors", "y": -1.98, "dz": 0.16, "size": (0.13, 0.06, 0.24), "reach": 0.21, "group": "black_trim",
         "arm": {"drop": 0.14, "r": 0.011}},
        {"kit": "door_handles", "handles": [("F", -1.33, True), ("S", -1.04, False)], "dz": 0.09, "group": "black_trim"},
        {"kit": "wipers", "arms": [(0.30, 0.62), (-0.32, 0.60)], "y": -2.14, "sweep_dy": 0.04,
         "cowl": {"y": -2.165, "ray_y": -2.17, "size": (1.40, 0.05, 0.014), "tilt": -30}},
        {"kit": "plates", "front": {"z": 0.4225, "ray_z": 0.42, "size": (0.31, 0.006, 0.145)},
         "rear": {"z": 0.7425, "ray_z": 0.74, "size": (0.31, 0.006, 0.145)}, "lamp": {"z": 0.84, "ray_z": 0.84, "size": (0.10, 0.012, 0.012)}},
        {"kit": "exhaust", "x": 0.50, "z": 0.30, "dual": False, "side": -1, "r": 0.030,
         "pipe": [(0.15, -1.80, 0.27), (0.15, -0.50, 0.27), (-0.15, 0.40, 0.27), (-0.40, 1.50, 0.28)],
         "branch_start": {"R": (-0.40, 1.50, 0.28)}, "branch_mid_y": 2.05,
         "silencer": ((-0.30, 1.30, 0.30), (0.40, 0.45, 0.14)), "catalyst": ((0.15, -0.90, 0.28), (0.15, 0.32, 0.10))},
        {"kit": "mudflaps", "zt": 0.40, "zb": 0.15, "inset": 0.11, "w": 0.20},
        {"custom": "roof_rack"},
        {"kit": "boxes", "items": [
            ("rear_step", "black_trim", (0, 2.36, 0.40), (1.20, 0.16, 0.05), 0.01),
            ("frame_rail_L", "underbody_metal", (0.42, 0.20, 0.30), (0.08, 3.90, 0.12), 0.01),
            ("frame_rail_R", "underbody_metal", (-0.42, 0.20, 0.30), (0.08, 3.90, 0.12), 0.01),
            ("underbody_tray", "underbody", (0, -0.40, 0.29), (1.40, 2.80, 0.012), 0.01),
            ("fuel_tank", "underbody_metal", (0.10, 0.30, 0.32), (0.70, 0.55, 0.16), 0.03, 3),
            ("crossmember_F", "underbody_metal", (0, AXLES[0] + 0.12, 0.33), (1.0, 0.10, 0.08), 0.012),
            ("crossmember_R", "underbody_metal", (0, AXLES[1] + 0.35, 0.33), (1.0, 0.10, 0.08), 0.012)]},
        {"kit": "wheel_wells", "inner": 0.50, "outer": 0.82, "hub_x": 0.66},
        {"kit": "suspension", "hub_x": 0.66, "top_x": 0.60, "top_dz": 0.40, "arm_x": 0.28, "arm_dy": 0.15, "shaft_x": 0.10,
         "spring_r": 0.060, "driven": "", "leaf": "R", "leaf_len": 1.2},
        {"kit": "beam_axle", "hub_x": 0.66, "r": 0.045},
        # ---- cab interior (right-hand drive) + the cargo bay behind a bulkhead
        {"kit": "boxes", "items": [
            ("floor_carpet", "interior_carpet", (0, -1.55, 0.78), (1.50, 0.95, 0.02)),
            ("engine_hump", "interior_plastic", (0, -1.42, 0.86), (0.42, 0.62, 0.18), 0.05, 3),
            ("dash_lower", "interior_plastic", (0, -2.02, 1.02), (1.50, 0.22, 0.22), 0.03, 3),
            ("dash_top", "interior_dark", (0, -2.05, 1.16), (1.52, 0.28, 0.06), 0.025, 3, 14),
            ("dash_binnacle", "interior_dark", (DRIVER_X, -1.94, 1.20), (0.34, 0.12, 0.09), 0.03, 3),
            ("dash_gauges", "screen", (DRIVER_X, -1.879, 1.185), (0.28, 0.004, 0.06), 0.01),
            ("center_stack", "interior_plastic", (0.05, -1.93, 1.02), (0.26, 0.10, 0.20), 0.02),
            ("radio", "screen", (0.05, -1.879, 1.06), (0.18, 0.006, 0.05), 0.004),
            ("nav_unit", "interior_dark", (0.05, -1.95, 1.27), (0.20, 0.03, 0.13), 0.008, 2, -15),
            ("nav_screen", "screen", (0.05, -1.935, 1.275), (0.18, 0.004, 0.11), 0.0, 2, -15),
            ("bulkhead", "black_metal", (0, -0.98, 1.20), (1.56, 0.03, 1.40), 0.008),
            ("cargo_floor", "wood", (0, 0.65, 0.50), (1.50, 3.20, 0.03)),
            ("rearview_mirror", "interior_dark", (0, -1.72, 1.80), (0.20, 0.03, 0.055), 0.012, 2)]},
        {"kit": "steering", "c": (DRIVER_X, -1.84, 1.18), "tilt": -72, "r": 0.20, "column_end": (DRIVER_X, -2.02, 1.02)},
        {"kit": "seat", "name": "seat_FR", "x": DRIVER_X, "y": -1.48, "z": 0.98, "w": 0.48, "back_h": 0.62, "recline": 12},
        {"kit": "seat", "name": "seat_FL", "x": -DRIVER_X, "y": -1.48, "z": 0.98, "w": 0.48, "back_h": 0.62, "recline": 12},
        {"custom": "cargo_racks"},
        {"kit": "door_cards", "armrest_z": 1.18, "ray_z": 1.20, "inset": 0.07},
        {"kit": "headliner", "z_min": 1.80, "y0": -1.70, "y1": -1.0},
        {"kit": "glass_frit", "which": ("windscreen",), "w": 0.05},
    ],
}


def roof_rack(p):
    """Roof rails on feet with crossbars (ladder rack) and a rear ladder."""
    import bmesh
    from vkit import panels as P
    from vkit.geom import bm_tube_path
    from vkit.shapes import box, obj
    out = []
    bm = bmesh.new()
    y0, y1 = -1.35, 2.15
    feet = []
    for sx in (-1, 1):
        x = sx * 0.66
        zs = []
        for y in (y0, -0.20, 1.0, y1):
            z, n = P.top_z(x, y)
            zs.append(z)
            feet.append((x, y, z))
        zr = max(zs) + 0.07
        bm_tube_path(bm, [(x, y0 - 0.05, zr), (x, y1 + 0.05, zr)], 0.016, 8)
    for y in (y0, -0.55, 0.25, 1.05, 1.75, y1):
        z, n = P.top_z(0.0, y)
        bm_tube_path(bm, [(-0.66, y, z + 0.07), (0.66, y, z + 0.07)], 0.013, 8)
    rack = obj("roof_rack", bm)
    out.append((rack.name, "black_metal", rack))
    for i, (x, y, z) in enumerate(feet):
        f = box(f"roof_rack_foot_{i}", (x, y, z + 0.035), (0.05, 0.08, 0.075), bevel=0.01)
        out.append((f.name, "black_trim", f))
    # a ladder on the right side of the tailgate
    bm = bmesh.new()
    xl = -0.79
    yl = P.rear_face_y(xl, 1.2) + 0.03
    for x in (xl - 0.13, xl + 0.13):
        bm_tube_path(bm, [(x, yl - 0.03, 0.62), (x, yl, 0.70), (x, yl, 1.90), (x, yl - 0.06, 2.0)], 0.012, 8)
    for i in range(7):
        z = 0.78 + i * 0.17
        bm_tube_path(bm, [(xl - 0.13, yl, z), (xl + 0.13, yl, z)], 0.010, 6)
    lad = obj("rear_ladder", bm)
    out.append((lad.name, "black_metal", lad))
    return out


def cargo_racks(p):
    """Steel shelving down both sides of the cargo bay with parcels on it (seen through the tailgate glass)."""
    import random
    from vkit.shapes import box
    out = []
    rnd = random.Random(7)
    for sx, side in ((1, "L"), (-1, "R")):
        for k, z in enumerate((0.85, 1.25, 1.62)):
            sh = box(f"shelf_{side}{k}", (sx * 0.54, 0.55, z), (0.36, 2.6, 0.02), bevel=0.004)
            out.append((sh.name, "black_metal", sh))
            y = -0.70
            i = 0
            while y < 1.70:
                w = rnd.uniform(0.25, 0.45)
                h = rnd.uniform(0.14, 0.30)
                d = rnd.uniform(0.26, 0.38)
                if rnd.random() < 0.8:
                    b = box(f"parcel_{side}{k}{i}", (sx * (0.54 + rnd.uniform(-0.02, 0.02)), y + w / 2, z + 0.01 + h / 2), (min(d, 0.32), w, h), bevel=0.006)
                    out.append((b.name, "cargo", b))
                y += w + rnd.uniform(0.02, 0.10)
                i += 1
        for y in (-0.70, 0.55, 1.80):
            post = box(f"shelf_post_{side}{int(y * 100)}", (sx * 0.71, y, 1.15), (0.03, 0.03, 1.25))
            out.append((post.name, "black_metal", post))
    return out
