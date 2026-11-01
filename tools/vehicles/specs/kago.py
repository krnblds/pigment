"""MERIDIAN Kago (2003): an autonomous robotaxi pod built by Hoshikawa Dynamics.

3.80 m x 1.80 m x 1.78 m, nearly symmetric front to back: a capsule body with a tall
wraparound glasshouse, sliding doors on both sides, full-width LED light bars instead of
headlamps, the MERIDIAN status eye on the nose, a lidar crown and corner sensor domes,
aero-covered wheels. Inside: two facing benches round a fare screen; no steering wheel.
MERIDIAN scores every passenger on the way.
"""
FRONT, REAR = -1.90, 1.90
AXLES = [-1.27, 1.27]


def sym(keys):
    """Mirror front keys [(y<=0, v)] to the back."""
    out = list(keys)
    out += [(-y, v) for y, v in reversed(keys) if y < 0]
    return out


SPEC = {
    "id": "kago",
    "name": "MERIDIAN Kago robotaxi pod",
    "class": "robotaxi",
    "role": "traffic / taxi",
    "front": FRONT, "rear": REAR, "axles": AXLES,
    "wheel_r": 0.330, "arch_r": 0.362, "track": 1.56, "body_drop": 0.02, "height": 1.80,
    "mass_kg": 1450,
    "center_of_mass": (0.0, 0.0, 0.48),
    "suspension_suggestion": {"rest_length": 0.14, "travel": 0.12, "stiffness": 40.0, "max_force": 10000.0,
                              "damping_compression": 1.0, "damping_relaxation": 1.5, "friction_slip": 2.6},
    "collider_zmax": 1.85,
    "lamps": {"head": (0.46, 0.766), "tail": (0.46, 0.766)},
    "lod": {"lod2_min_piece": 0.2, "lod1_body": 9000, "lod1_wheel": 420, "lod2_body": 750, "lod2_wheel": 48},
    "body": {
        "stations": [-1.90, -1.885, -1.85, -1.79, -1.70, -1.58, -1.45, -1.30, -1.15, -1.00, -0.85, -0.65, -0.40, 0.0,
                     0.40, 0.65, 0.85, 1.00, 1.15, 1.30, 1.45, 1.58, 1.70, 1.79, 1.85, 1.885, 1.90],
        "ztop": sym([(-1.90, 0.700), (-1.85, 0.830), (-1.76, 0.915), (-1.62, 0.990), (-1.45, 1.120), (-1.25, 1.330),
                     (-1.05, 1.540), (-0.85, 1.690), (-0.55, 1.765), (0.0, 1.785)]),
        "drop": sym([(-1.90, 0.010), (-1.60, 0.030), (-1.20, 0.060), (0.0, 0.060)]),
        "wside": sym([(-1.90, 0.700), (-1.885, 0.780), (-1.85, 0.840), (-1.76, 0.882), (-1.55, 0.898), (0.0, 0.900)]),
        "wroof": sym([(-1.90, 0.560), (-1.20, 0.700), (-0.60, 0.760), (0.0, 0.765)]),
        "wg_in": sym([(-1.90, 0.040), (-1.0, 0.055), (0.0, 0.060)]),
        "zbelt": sym([(-1.90, 0.680), (-1.80, 0.790), (-1.60, 0.850), (-1.0, 0.875), (0.0, 0.880)]),
        "zfloor": sym([(-1.90, 0.280), (-1.84, 0.220), (-1.65, 0.190), (0.0, 0.190)]),
        "zrock": sym([(-1.90, 0.310), (-1.70, 0.270), (0.0, 0.270)]),
        "rake": sym([(-1.90, 0.06), (-1.85, 0.03), (-1.79, 0.0), (0.0, 0.0)]),
        "decimate": 0.45, "cab": ((-1.72, -1.52), (1.52, 1.72)),
        "section": {"rock_min_drop": 0.12, "side_frac": 0.50, "shoulder_in": 0.020, "g9_bulge": (0.0, 0.020), "rake_pivot": 0.50,
                    "crown_x": 0.60, "crown_drop": 0.25},
        "cap_bulge": (-0.03, 0.03),
        "creases": {6: 0.7, 3: 0.55, 7: 0.35, 9: 0.40},
    },
    "panels": {
        "arch_x": 0.88, "arch_depth": 0.56, "door_bottom": 0.30,
        "rail_drop": 0.024, "dlo_top_drop": 0.065, "dlo_bottom_rise": 0.02,
        "doors": [{"name": "S", "kind": "rear", "line": -0.70, "frame_front": -0.66, "rear": 0.66, "rear_frame": "rail", "n": 14}],
        "windows": [{"name": "rear_quarter", "y0": 0.76, "y1": 1.18, "r": 0.03, "slant": 0.16, "n": 8},
                    {"name": "front_quarter", "y0": -1.02, "y1": -0.80, "r": 0.03, "n": 6}],
        "windshield": {"kind": "top", "y0": -1.585, "y1": -0.86, "inset": 0.058, "taper": 0.03, "z0": 0.88, "z1": 2.1},
        "rear_window": {"kind": "top", "y0": 0.86, "y1": 1.585, "inset": 0.058, "taper": 0.03, "z0": 0.88, "z1": 2.1},
        "hood": {"y0": -1.83, "y1": -1.62, "inset": 0.045, "z0": 0.70, "z1": 1.4, "n": 8, "piece_z": 0.75},
        "trunk": {"y0": 1.62, "y1": 1.83, "inset": 0.045, "z0": 0.70, "z1": 1.4, "n": 8, "piece_z": 0.75},
        "bumpers": [{"y": -1.70, "z": 0.520, "end": -2.4}, {"y": 1.66, "z": 0.520, "end": 2.4}],
        "apertures": [
            {"rect": [-0.68, 0.742, 0.68, 0.790, 0.020], "a0": -2.4, "a1": -1.70},   # front light bar
            {"rect": [-0.68, 0.742, 0.68, 0.790, 0.020], "a0": 1.70, "a1": 2.4},     # rear light bar
            {"rect": [-0.42, 0.560, 0.42, 0.680, 0.040], "a0": -2.4, "a1": -1.72},   # front sensor window
        ],
        "lenses": [
            {"name": "headlight_lens", "group": "lens_clear", "rect": [-0.68, 0.742, 0.68, 0.790, 0.020], "a0": -2.4, "a1": -1.70},
            {"name": "taillight_lens", "group": "lens_red", "rect": [-0.68, 0.742, 0.68, 0.790, 0.020], "a0": 1.70, "a1": 2.4},
            {"name": "sensor_glass", "group": "glass", "rect": [-0.42, 0.560, 0.42, 0.680, 0.040], "a0": -2.4, "a1": -1.72},
        ],
        "plates": {"front": {"w": 0.165, "z0": 0.360, "z1": 0.505, "r": 0.012, "depth": 0.012, "ray_z": 0.43},
                   "rear": {"w": 0.165, "z0": 0.360, "z1": 0.505, "r": 0.012, "depth": 0.012, "ray_z": 0.43}},
    },
    "wheel": {"barrel_seg": 32, "width": 0.215, "rim_r": 0.216, "lip_r": 0.224, "style": "aero", "slots": 7, "lugs": 0, "cap_r": 0.0,
              "disc_r": 0.150, "profile": "v2", "tyre_seg": 40, "dish": 0.020},
    "parts": [
        {"kit": "boxes", "items": [("lightbar_back_F", "black_trim", (0, -1.80, 0.766), (1.30, 0.04, 0.06), 0.01),
                                   ("lightbar_back_R", "black_trim", (0, 1.80, 0.766), (1.30, 0.04, 0.06), 0.01),
                                   ("sensor_back", "black_trim", (0, -1.80, 0.62), (0.82, 0.04, 0.12), 0.01)]},
        {"kit": "headlights", "x": 0.62, "z": 0.766,
         "elements": [{"type": "led", "x": 0.46, "w": 0.30, "h": 0.022, "depth": 0.02},
                      {"type": "led", "x": 0.16, "w": 0.24, "h": 0.010, "depth": 0.02, "group": "emitter_cyan"}],
         "indicator": {"x": 0.635, "z": 0.766, "size": (0.05, 0.02, 0.020), "depth": 0.02}},
        {"kit": "taillights", "zc": 0.766,
         "segments": [{"name": "tail_brake", "x": 0.46, "w": 0.30, "h": 0.024, "group": "emitter_tail", "depth": 0.02},
                      {"name": "tail_indicator", "x": 0.635, "w": 0.05, "h": 0.020, "group": "emitter_amber", "depth": 0.02},
                      {"name": "tail_status", "x": 0.16, "w": 0.24, "h": 0.010, "group": "emitter_cyan", "depth": 0.02}]},
        {"custom": "meridian_eye"},
        {"kit": "window_seals", "fixed": True, "r": 0.006},
        {"kit": "door_handles", "handles": [("S", -0.56, False)], "dz": 0.06, "group": "black_trim"},
        {"kit": "plates", "front": {"z": 0.4325, "ray_z": 0.43, "size": (0.30, 0.006, 0.135)},
         "rear": {"z": 0.4325, "ray_z": 0.43, "size": (0.30, 0.006, 0.135)}},
        {"custom": "sensors"},
        {"kit": "boxes", "items": [
            ("underbody_tray", "underbody", (0, 0.0, 0.192), (1.50, 3.20, 0.012), 0.01),
            ("battery_pack", "underbody_metal", (0, 0.0, 0.215), (1.20, 2.00, 0.05), 0.02, 3),
            ("crossmember_F", "underbody_metal", (0, AXLES[0] + 0.05, 0.24), (1.05, 0.10, 0.07), 0.012),
            ("crossmember_R", "underbody_metal", (0, AXLES[1] - 0.05, 0.24), (1.05, 0.10, 0.07), 0.012),
            ("motor_F", "underbody_metal", (0, AXLES[0], 0.32), (0.40, 0.30, 0.22), 0.04, 3),
            ("motor_R", "underbody_metal", (0, AXLES[1], 0.32), (0.40, 0.30, 0.22), 0.04, 3)]},
        {"kit": "wheel_wells", "inner": 0.55, "outer": 0.86, "hub_x": 0.72},
        {"kit": "suspension", "hub_x": 0.72, "top_x": 0.66, "top_dz": 0.34},
        # ---- cabin: two facing benches round a fare screen
        {"kit": "boxes", "items": [
            ("floor_carpet", "interior_floor", (0, 0.0, 0.215), (1.62, 2.60, 0.02)),
            ("fare_console", "interior_plastic", (0, 0.0, 0.42), (0.36, 0.30, 0.40), 0.04, 3),
            ("fare_screen", "screen", (0, -0.152, 0.58), (0.30, 0.004, 0.18), 0.01, 2, -15),
            ("fare_screen_back", "screen", (0, 0.152, 0.58), (0.30, 0.004, 0.18), 0.01, 2, 15),
            ("front_dash", "interior_plastic", (0, -1.42, 0.82), (1.60, 0.30, 0.10), 0.04, 3),
            ("rear_dash", "interior_plastic", (0, 1.42, 0.82), (1.60, 0.30, 0.10), 0.04, 3),
            ("dash_display", "screen", (0, -1.28, 0.88), (1.10, 0.004, 0.06), 0.006, 2, 30),
            ("handrail_bar", "handrail", (0, 0.0, 1.68), (1.20, 0.03, 0.03), 0.01)]},
        {"custom": "benches"},
        {"kit": "door_cards", "armrest": False, "inset": 0.07},
        {"kit": "headliner", "z_min": 1.62, "y0": -0.85, "y1": 0.85},
        {"kit": "glass_frit", "w": 0.05},
    ],
}


def meridian_eye(p):
    """The MERIDIAN status eye on the nose: a chrome-ringed lens with a cyan iris."""
    from vkit import panels as P
    from vkit.shapes import lathe
    out = []
    z = 0.93
    y = P.front_face_y(0.0, z)
    ring = lathe("meridian_eye_ring", [(0.075, 0.006), (0.090, 0.0), (0.094, -0.012), (0.082, -0.016)], (0, y, z), "Y", 32)
    out.append((ring.name, "chrome", ring))
    iris = lathe("meridian_eye_iris", [(0.0, -0.014), (0.030, -0.012), (0.075, -0.004), (0.078, 0.004)], (0, y, z), "Y", 32)
    out.append((iris.name, "emitter_cyan", iris))
    y2 = P.rear_face_y(0.0, z)
    ring = lathe("meridian_eye_ring_R", [(0.075, -0.006), (0.090, 0.0), (0.094, 0.012), (0.082, 0.016)], (0, y2, z), "Y", 32)
    out.append((ring.name, "chrome", ring))
    iris = lathe("meridian_eye_iris_R", [(0.0, 0.014), (0.030, 0.012), (0.075, 0.004), (0.078, -0.004)], (0, y2, z), "Y", 32)
    out.append((iris.name, "emitter_cyan", iris))
    return out


def sensors(p):
    """Lidar crown on the roof, a roof status sign, corner sensor domes."""
    import bmesh
    from vkit import panels as P
    from vkit.geom import bm_sphere
    from vkit.shapes import box, lathe, obj
    out = []
    z0, n = P.top_z(0.0, 0.0)
    base = lathe("lidar_base", [(0.0, 0.0), (0.20, 0.0), (0.21, 0.02), (0.16, 0.05), (0.0, 0.05)], (0, 0.0, z0 - 0.005), "Z", 32)
    out.append((base.name, "black_trim", base))
    drum = lathe("lidar_drum", [(0.0, 0.05), (0.10, 0.05), (0.10, 0.16), (0.0, 0.16)], (0, 0.0, z0 - 0.005), "Z", 32)
    out.append((drum.name, "black_metal", drum))
    win = lathe("lidar_window", [(0.103, 0.07), (0.103, 0.13)], (0, 0.0, z0 - 0.005), "Z", 32)
    out.append((win.name, "emitter_cyan", win))
    cap = lathe("lidar_cap", [(0.0, 0.185), (0.08, 0.18), (0.11, 0.16), (0.11, 0.155)], (0, 0.0, z0 - 0.005), "Z", 32)
    out.append((cap.name, "black_trim", cap))
    # roof sign (fare / status), front of the crown
    zs, n = P.top_z(0.0, -0.50)
    sg = box("roof_sign", (0, -0.50, zs + 0.07), (0.56, 0.06, 0.12), bevel=0.02, seg=3)
    out.append((sg.name, "black_trim", sg))
    for k, dy in (("F", -0.032), ("R", 0.032)):
        face = box(f"roof_sign_face_{k}", (0, -0.50 + dy, zs + 0.072), (0.50, 0.004, 0.09), bevel=0.004)
        out.append((face.name, "emitter_sign", face))
    for k, (sx, y) in enumerate(((1, -1.62), (-1, -1.62), (1, 1.62), (-1, 1.62))):
        x, nn = P.side_x(y, 0.86, sx)
        bm = bmesh.new()
        bm_sphere(bm, (x - sx * 0.01, y, 0.86), 0.045, 16, 8, scale=(1, 1, 0.8))
        d = obj(f"corner_sensor_{k}", bm)
        out.append((d.name, "black_trim", d))
    return out


def benches(p):
    """Two facing benches (the front one faces backwards)."""
    from mathutils import Matrix
    from vkit import cfg
    from vkit.interior import seat
    out = []
    rear = seat(cfg.wrap({"name": "bench_R", "x": 0.0, "y": 0.62, "z": 0.40, "w": 1.30, "back_h": 0.62, "recline": 14, "bench": True,
                          "headrest_x": [0.36], "depth": 0.48}))
    out += rear
    front = seat(cfg.wrap({"name": "bench_F", "x": 0.0, "y": 0.62, "z": 0.40, "w": 1.30, "back_h": 0.62, "recline": 14, "bench": True,
                           "headrest_x": [0.36], "depth": 0.48}))
    for nm, g, ob in front:
        ob.data.transform(Matrix.Rotation(3.14159265, 4, "Z"))
    out += front
    return out
