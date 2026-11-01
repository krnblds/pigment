"""Kanzaki Hayate RS (1998): a low two-door fastback coupe, the player's car.

4.38 m x 1.80 m x 1.24 m on 17-inch cross-spoke wheels. A long low hood with louvres and
slim projector lamps, a wraparound glasshouse with strong tumblehome, wide rear haunches,
a fastback glass, a short deck with a wing, and four round tail lamps in a black garnish.
Street racers love it; so do Hoshikawa Security's pursuit units.
"""
FRONT, REAR = -2.12, 2.26
AXLES = [-1.30, 1.20]
DOOR_LINE = 0.60
DRIVER_X = -0.36

SPEC = {
    "id": "hayate",
    "name": "Kanzaki Hayate RS sports coupe",
    "class": "sports",
    "role": "player / traffic",
    "front": FRONT, "rear": REAR, "axles": AXLES,
    "wheel_r": 0.322, "arch_r": 0.352, "track": 1.555, "body_drop": 0.02, "height": 1.24,
    "mass_kg": 1340,
    "center_of_mass": (0.0, 0.0, 0.42),
    "suspension_suggestion": {"rest_length": 0.12, "travel": 0.10, "stiffness": 48.0, "max_force": 10000.0,
                              "damping_compression": 1.1, "damping_relaxation": 1.7, "friction_slip": 3.2},
    "collider_zmax": 1.40,
    "lamps": {"head": (0.66, 0.53), "tail": (0.61, 0.665)},
    "lod": {"lod2_min_piece": 0.2, "lod1_body": 9000, "lod1_wheel": 480, "lod2_body": 750, "lod2_wheel": 48},
    "body": {
        "stations": [-2.12, -2.105, -2.07, -2.00, -1.88, -1.60, -1.20, -0.80, -0.60, -0.52, -0.45, -0.32, -0.18, -0.05,
                     0.08, 0.30, 0.55, 0.80, 1.05, 1.30, 1.52, 1.62, 1.72, 1.95, 2.12, 2.20, 2.245],
        "ztop": [(-2.12, 0.520), (-2.07, 0.585), (-2.00, 0.618), (-1.60, 0.682), (-1.00, 0.735), (-0.60, 0.768),
                 (-0.52, 0.790), (-0.40, 0.870), (-0.25, 0.985), (-0.10, 1.110), (0.05, 1.195), (0.25, 1.225),
                 (0.45, 1.215), (0.70, 1.165), (1.00, 1.080), (1.30, 0.990), (1.52, 0.925), (1.62, 0.905),
                 (1.80, 0.880), (2.05, 0.872), (2.15, 0.858), (2.20, 0.835), (2.245, 0.785)],
        "drop": [(-2.12, 0.010), (-0.60, 0.022), (-0.45, 0.055), (0.05, 0.060), (0.70, 0.075), (1.30, 0.060),
                 (1.62, 0.020), (2.245, 0.010)],
        "wside": [(-2.12, 0.650), (-2.105, 0.730), (-2.07, 0.800), (-2.00, 0.850), (-1.88, 0.878), (-1.50, 0.890),
                  (-0.90, 0.886), (-0.30, 0.876), (0.30, 0.882), (0.90, 0.898), (1.30, 0.905), (1.90, 0.900),
                  (2.12, 0.872), (2.20, 0.830), (2.245, 0.760)],
        "wroof": [(-2.12, 0.50), (-0.60, 0.585), (-0.45, 0.600), (0.0, 0.615), (0.40, 0.605), (0.90, 0.575),
                  (1.40, 0.530), (1.62, 0.500), (2.245, 0.470)],
        "wg_in": [(-2.12, 0.035), (-0.60, 0.050), (0.0, 0.075), (1.0, 0.085), (1.62, 0.060), (2.245, 0.040)],
        "zbelt": [(-2.12, 0.520), (-2.07, 0.578), (-1.90, 0.625), (-1.30, 0.690), (-0.60, 0.715), (0.20, 0.740),
                  (0.90, 0.765), (1.50, 0.785), (2.05, 0.790), (2.20, 0.772), (2.245, 0.725)],
        "zfloor": [(-2.12, 0.230), (-2.06, 0.175), (-1.85, 0.140), (1.90, 0.150), (2.15, 0.195), (2.245, 0.250)],
        "zrock": [(-2.12, 0.265), (-1.90, 0.240), (2.00, 0.250), (2.245, 0.290)],
        "rake": [(-2.12, 0.20), (-2.07, 0.11), (-2.00, 0.0), (2.12, 0.0), (2.20, 0.035), (2.245, 0.06)],
        "decimate": 0.45, "cab": ((-0.62, -0.46), (1.48, 1.64)),
        "section": {"rock_min_drop": 0.11, "side_frac": 0.50, "shoulder_in": 0.024, "g9_bulge": (0.0, 0.018), "rake_pivot": 0.40},
        "cap_bulge": (-0.03, 0.025),
        "creases": {6: 0.85, 3: 0.65, 7: 0.5, 9: 0.45},
    },
    "panels": {
        "arch_x": 0.88, "arch_depth": 0.56, "door_bottom": 0.27,
        "apillar_search": (-0.60, 0.3),
        "doors": [{"name": "F", "kind": "front", "front": -0.585, "line": DOOR_LINE, "frame_rear": 0.555, "n": 16}],
        "windows": [{"name": "quarter_glass", "y0": 0.635, "y1": 1.16, "slant": 0.22, "r": 0.03, "n": 8}],
        "windshield": {"kind": "top", "y0": -0.475, "y1": 0.025, "inset": 0.055, "taper": 0.03, "z0": 0.72, "z1": 1.6},
        "rear_window": {"kind": "top", "y0": 0.66, "y1": 1.50, "inset": 0.075, "taper": 0.035, "z0": 0.85, "z1": 1.6},
        "hood": {"y0": -2.02, "y1": -0.50, "inset": 0.030, "z0": 0.50, "z1": 1.2, "n": 14, "piece_z": 0.55},
        "trunk": {"y0": 1.585, "y1": 2.175, "inset": 0.040, "z0": 0.72, "z1": 1.2, "n": 8, "piece_z": 0.75},
        "bumpers": [{"y": -1.86, "z": 0.420, "end": -2.6}, {"y": 1.98, "z": 0.560, "end": 2.6}],
        "fuel_door": {"y0": 1.40, "y1": 1.54, "z0": 0.66, "z1": 0.76, "r": 0.035, "side": 1},
        "apertures": [
            {"sides": [{"rect": [0.475, 0.495, 0.845, 0.565, 0.016], "a0": -2.6, "a1": -1.98}]},          # slim headlamps
            {"rect": [-0.52, 0.235, 0.52, 0.365, 0.035], "a0": -2.6, "a1": -1.95},                       # main intake
            {"sides": [{"rect": [0.62, 0.255, 0.82, 0.335, 0.025], "a0": -2.6, "a1": -1.90},             # brake ducts
                       {"rect": [0.60, 0.410, 0.80, 0.440, 0.010], "a0": -2.6, "a1": -1.95}]},           # indicators
            {"rect": [-0.845, 0.600, 0.845, 0.730, 0.02], "a0": 2.10, "a1": 2.6},                        # tail garnish
            {"sides": [{"rect": [0.31, 0.205, 0.45, 0.275, 0.034], "a0": 2.0, "a1": 2.6}]},              # exhaust cut-outs
        ],
        "lenses": [
            {"sides": [{"name": "headlight_lens", "group": "lens_clear", "rect": [0.475, 0.495, 0.845, 0.565, 0.016], "a0": -2.6, "a1": -1.98},
                       {"name": "indicator_lens", "group": "lens_amber", "rect": [0.60, 0.410, 0.80, 0.440, 0.010], "a0": -2.6, "a1": -1.95}]},
            {"sides": [{"name": "taillight_lens_out", "group": "lens_red", "rect": [0.648, 0.607, 0.762, 0.721, 0.057], "a0": 2.10, "a1": 2.6},
                       {"name": "taillight_lens_in", "group": "lens_red", "rect": [0.455, 0.607, 0.569, 0.721, 0.057], "a0": 2.10, "a1": 2.6}]},
        ],
        "plates": {"front": {"w": 0.165, "z0": 0.255, "z1": 0.395, "r": 0.010, "depth": 0.012, "ray_z": 0.30},
                   "rear": {"w": 0.170, "z0": 0.405, "z1": 0.560, "r": 0.012, "depth": 0.016, "ray_z": 0.48}},
    },
    "wheel": {"barrel_seg": 36, "width": 0.235, "rim_r": 0.216, "lip_r": 0.226, "style": "mesh", "spokes": 10, "lugs": 5, "lug_r": 0.052,
              "cap_r": 0.036, "disc_r": 0.160, "profile": "v2", "tyre_seg": 48, "dish": 0.050, "hub_r": 0.075, "caliper_a1": 78},
    "parts": [
        {"kit": "headlights", "x": 0.66, "z": 0.53,
         "housing": {"size": (0.36, 0.09, 0.066), "back": 0.065},
         "elements": [{"type": "reflector", "x": 0.75, "r": 0.030, "seg": 20, "projector": True},
                      {"type": "reflector", "x": 0.57, "r": 0.030, "seg": 20},
                      {"type": "led", "x": 0.66, "z": 0.505, "w": 0.33, "h": 0.008, "depth": 0.014}],
         "indicator": {"x": 0.70, "z": 0.425, "size": (0.19, 0.03, 0.026), "depth": 0.024}},
        {"kit": "grille", "z": 0.30, "w": 1.02, "h": 0.12, "back": 0.07, "bars": {"n": 13, "pitch": 0.075, "t": 0.010},
         "slats": {"n": 2, "z0": 0.27, "pitch": 0.06, "w": 1.0, "t": 0.008}},
        {"kit": "boxes", "items": [("brake_duct_mesh_L", "black_trim", (0.72, -1.93, 0.295), (0.20, 0.012, 0.08)),
                                   ("brake_duct_mesh_R", "black_trim", (-0.72, -1.93, 0.295), (0.20, 0.012, 0.08)),
                                   ("tail_garnish", "black_trim", (0, 2.205, 0.665), (1.66, 0.02, 0.13), 0.006)]},
        {"kit": "taillights", "zc": 0.664,
         "segments": [{"name": "tail_brake_out", "x": 0.705, "w": 0.095, "h": 0.095, "group": "emitter_tail", "depth": 0.03},
                      {"name": "tail_brake_in", "x": 0.512, "w": 0.095, "h": 0.095, "group": "emitter_tail", "depth": 0.03},
                      {"name": "tail_reverse", "x": 0.32, "w": 0.10, "h": 0.03, "group": "emitter_reverse", "depth": 0.02},
                      {"name": "tail_indicator", "x": 0.80, "w": 0.04, "h": 0.07, "group": "emitter_amber", "depth": 0.02}],
         "third": {"y": 2.05, "roof_y": 1.95, "size": (0.30, 0.02, 0.016), "tilt": 0, "dz": 0.0}},
        {"custom": "tail_rings"},
        {"kit": "window_seals", "fixed": True, "r": 0.0055},
        {"custom": "side_skirts"},
        {"kit": "mirrors", "y": -0.43, "dz": 0.06, "size": (0.17, 0.07, 0.085), "reach": 0.12},
        {"kit": "door_handles", "handles": [("F", 0.42, True)], "dz": 0.06, "group": "black_trim"},
        {"kit": "wipers", "arms": [(0.24, 0.56), (-0.22, 0.50)], "y": -0.505, "lift": 0.014,
         "cowl": {"y": -0.53, "ray_y": -0.535, "size": (1.26, 0.05, 0.010), "tilt": -8}},
        {"kit": "plates", "front": {"z": 0.325, "ray_z": 0.30, "size": (0.30, 0.006, 0.13)},
         "rear": {"z": 0.4825, "ray_z": 0.48, "size": (0.31, 0.006, 0.145)}, "lamp": {"z": 0.58, "ray_z": 0.575, "size": (0.10, 0.012, 0.010)}},
        {"kit": "exhaust", "x": 0.38, "z": 0.24, "r": 0.042,
         "pipe": [(0.0, -1.10, 0.17), (0.0, -0.20, 0.17), (0.0, 0.70, 0.17), (0.10, 1.40, 0.19), (0.20, 1.70, 0.21)],
         "branch_start": {"L": (0.20, 1.72, 0.22), "R": (-0.20, 1.72, 0.22)}, "branch_mid_y": 1.95,
         "silencer": ((0.0, 1.78, 0.22), (0.90, 0.26, 0.12)), "catalyst": ((0.0, -0.45, 0.18), (0.16, 0.34, 0.08))},
        {"custom": "rear_wing"},
        {"custom": "hood_vents"},
        {"kit": "boxes", "items": [
            ("underbody_tray", "underbody", (0, 0.05, 0.142), (1.40, 3.40, 0.012), 0.01),
            ("underbody_tunnel", "underbody", (0, -0.15, 0.18), (0.24, 2.4, 0.07), 0.03, 3),
            ("fuel_tank", "underbody_metal", (0.0, 1.08, 0.18), (0.9, 0.40, 0.07), 0.03, 3),
            ("front_splitter", "black_trim", (0, -1.98, 0.16), (1.56, 0.20, 0.012), 0.004),
            ("rear_diffuser", "black_trim", (0, 2.10, 0.20), (1.10, 0.22, 0.015), 0.004, 2, 12),
            ("crossmember_F", "underbody_metal", (0, AXLES[0] + 0.05, 0.20), (1.05, 0.10, 0.06), 0.012),
            ("crossmember_R", "underbody_metal", (0, AXLES[1] - 0.05, 0.20), (1.05, 0.10, 0.06), 0.012)]},
        {"kit": "wheel_wells", "inner": 0.55, "outer": 0.86, "hub_x": 0.72},
        {"kit": "suspension", "hub_x": 0.72, "top_x": 0.66, "top_dz": 0.32, "arm_x": 0.32, "driven": "R"},
        # ---- interior (right-hand drive, 2+2)
        {"kit": "boxes", "items": [
            ("floor_carpet", "interior_carpet", (0, 0.20, 0.185), (1.56, 2.0, 0.02)),
            ("floor_tunnel", "interior_carpet", (0, -0.05, 0.25), (0.28, 1.70, 0.14), 0.05, 3),
            ("dash_lower", "interior_plastic", (0, -0.45, 0.58), (1.52, 0.30, 0.22), 0.03, 3),
            ("dash_top", "interior_dark", (0, -0.52, 0.72), (1.54, 0.40, 0.06), 0.03, 3, 6),
            ("dash_binnacle", "interior_dark", (DRIVER_X, -0.36, 0.765), (0.42, 0.14, 0.10), 0.04, 3),
            ("dash_gauges", "screen", (DRIVER_X, -0.29, 0.745), (0.36, 0.004, 0.07), 0.01),
            ("center_stack", "interior_plastic", (0, -0.36, 0.53), (0.28, 0.16, 0.26), 0.02),
            ("radio", "screen", (0, -0.278, 0.60), (0.19, 0.006, 0.05), 0.004),
            ("boost_gauges", "screen", (0, -0.30, 0.69), (0.24, 0.004, 0.05), 0.006),
            ("vent_R", "black_trim", (-0.62, -0.33, 0.66), (0.12, 0.006, 0.05), 0.006),
            ("vent_L", "black_trim", (0.62, -0.33, 0.66), (0.12, 0.006, 0.05), 0.006),
            ("center_console", "interior_plastic", (0, 0.05, 0.33), (0.26, 0.80, 0.16), 0.03, 3),
            ("parcel_shelf", "interior_dark", (0, 1.20, 0.76), (1.30, 0.50, 0.02), 0.0, 2, -10),
            ("rearview_mirror", "interior_dark", (0, -0.02, 1.13), (0.22, 0.03, 0.055), 0.012, 2)]},
        {"kit": "shifter", "a": (0, -0.10, 0.41), "b": (0, -0.12, 0.52), "knob": (0, -0.125, 0.535)},
        {"kit": "steering", "c": (DRIVER_X, -0.20, 0.72), "tilt": -66, "r": 0.18, "column_end": (DRIVER_X, -0.40, 0.66)},
        {"kit": "seat", "name": "seat_FR", "x": DRIVER_X, "y": 0.18, "z": 0.30, "w": 0.52, "back_h": 0.60, "recline": 22, "bolsters": True},
        {"kit": "seat", "name": "seat_FL", "x": -DRIVER_X, "y": 0.18, "z": 0.30, "w": 0.52, "back_h": 0.60, "recline": 22, "bolsters": True},
        {"kit": "seat", "name": "seat_rear", "x": 0.0, "y": 0.92, "z": 0.30, "w": 1.10, "back_h": 0.40, "recline": 30, "bench": True,
         "depth": 0.40, "headrest_x": [0.33]},
        {"kit": "door_cards", "armrest_z": 0.52, "ray_z": 0.55, "inset": 0.075},
        {"kit": "headliner", "z_min": 1.10, "y0": -0.10, "y1": 0.75},
        {"kit": "glass_frit", "w": 0.045},
    ],
}


def tail_rings(p):
    """Chrome-lipped round tail lamps: a ring and a round emitter per lamp."""
    from vkit import panels as P
    from vkit.shapes import lathe
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        for k, x in (("out", 0.705), ("in", 0.512)):
            xx = sx * x
            y = P.rear_face_y(xx, 0.664)
            ring = lathe(f"tail_ring_{k}_{side}", [(0.040, -0.006), (0.050, -0.010), (0.054, -0.030), (0.046, -0.034)], (xx, y, 0.664), "Y", 28)
            out.append((ring.name, "chrome", ring))
            core = lathe(f"tail_core_{k}_{side}", [(0.0, -0.012), (0.030, -0.014), (0.040, -0.024), (0.040, -0.040)], (xx, y, 0.664), "Y", 24)
            out.append((core.name, "emitter_tail", core))
    return out


def side_skirts(p):
    """Side skirts between the arches."""
    import bmesh
    from vkit import panels as P
    from vkit.panels import frange
    from vkit.shapes import obj
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        y0, y1 = AXLES[0] + 0.40, AXLES[1] - 0.40
        prof = [(0.0, 0.0), (0.012, 0.0), (0.020, 0.03), (0.018, 0.075), (0.0, 0.085)]
        bm = bmesh.new()
        rings = []
        for y in frange(y0, y1, 14):
            x, n = P.side_x(y, 0.27, sx)
            rings.append([bm.verts.new((x + sx * (o - 0.004), y, 0.20 + dz)) for o, dz in prof])
        for A, B in zip(rings, rings[1:]):
            for k in range(len(prof) - 1):
                bm.faces.new((A[k], A[k + 1], B[k + 1], B[k]))
        bm.faces.new(rings[0])
        bm.faces.new(list(reversed(rings[-1])))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = obj(f"side_skirt_{side}", bm)
        out.append((ob.name, "paint", ob))
    return out


def rear_wing(p):
    """A 90s wing on two swan-neck uprights over the deck lid."""
    import bmesh
    from mathutils import Matrix
    from vkit import panels as P
    from vkit.shapes import box, obj
    out = []
    y = 2.04
    zd, n = P.top_z(0.48, y)
    zt = zd + 0.11
    # aerofoil: a cambered section lofted across
    prof = [(0.0, 0.0), (0.06, 0.018), (0.16, 0.022), (0.24, 0.010), (0.26, 0.0), (0.16, 0.004), (0.06, 0.002)]
    bm = bmesh.new()
    rings = []
    for x in (-0.74, -0.70, 0.70, 0.74):
        sc = 0.92 if abs(x) > 0.72 else 1.0
        rings.append([bm.verts.new((x, y - 0.11 + u * sc, zt + v * sc + 0.03 * (u / 0.26))) for u, v in prof])
    for A, B in zip(rings, rings[1:]):
        for k in range(len(prof)):
            bm.faces.new((A[k], A[(k + 1) % len(prof)], B[(k + 1) % len(prof)], B[k]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    wing = obj("wing_blade", bm)
    out.append((wing.name, "paint", wing))
    for sx, side in ((1, "L"), (-1, "R")):
        z0, n = P.top_z(sx * 0.48, y)
        st = box(f"wing_upright_{side}", (sx * 0.48, y, (z0 + zt) / 2 + 0.01), (0.03, 0.14, zt - z0 + 0.03), bevel=0.008)
        out.append((st.name, "black_trim", st))
        ep = box(f"wing_endplate_{side}", (sx * 0.745, y + 0.02, zt + 0.02), (0.008, 0.30, 0.10), bevel=0.003)
        out.append((ep.name, "black_trim", ep))
    return out


def hood_vents(p):
    """Two louvred heat-extractor vents on the hood."""
    from vkit import panels as P
    from vkit.shapes import box, rot_x
    out = []
    for sx, side in ((1, "L"), (-1, "R")):
        x = sx * 0.34
        for i in range(5):
            y = -1.18 + i * 0.045
            z, n = P.top_z(x, y)
            lv = box(f"hood_louvre_{side}{i}", (x, y, z + 0.004), (0.26, 0.030, 0.006), bevel=0.002, rot=rot_x(-12))
            out.append((lv.name, "black_trim", lv))
    return out
