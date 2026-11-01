"""Ishimaru Kaiun 2t (1995): a cab-over light truck with an aluminium box body.

5.60 m long, 1.95 m wide over the box, 2.95 m tall. A flat-faced tilting cab (the loft)
with quad round headlamps in a black grille panel, chrome bumper, big arm mirrors and cab
steps; a ladder chassis with twin rear wheels; a ribbed box with a roll-up rear door, an
underrun bar carrying the tail lamps. Logistics for the whole city: Hoshikawa supply runs,
Dreamlink pod deliveries, recycling, night-market stock.
"""
FRONT, REAR = -2.85, -1.27        # the cab (lofted shell); the box and chassis run back to +2.75
AXLES = [-2.10, 0.95]
BOX = dict(y0=-1.20, y1=2.75, w=0.975, z0=1.05, z1=2.95)
DRIVER_X = -0.42

SPEC = {
    "id": "kaiun",
    "name": "Ishimaru Kaiun 2t box truck",
    "class": "truck",
    "role": "traffic / logistics",
    "front": FRONT, "rear": REAR, "axles": AXLES,
    "wheel_r": 0.368, "arch_r": 0.405, "track": 1.50, "body_drop": 0.03, "height": 2.95,
    "mass_kg": 3900,
    "center_of_mass": (0.0, -0.60, 0.95),
    "suspension_suggestion": {"rest_length": 0.18, "travel": 0.14, "stiffness": 70.0, "max_force": 30000.0,
                              "damping_compression": 1.4, "damping_relaxation": 2.0, "friction_slip": 2.2},
    "dimensions": {"length": 5.60, "width_box": 1.95, "width_cab": 1.76, "height_box": 2.95},
    "collider_zmax": 3.2,
    "lamps": {"head": (0.66, 0.765), "tail": (0.80, 0.62, 2.83)},
    "ray": {"x": 2.5, "z": 4.0, "y": 6.0},
    "lod": {"lod2_min_piece": 0.2, "lod1_body": 10000, "lod1_wheel": 420, "lod2_body": 750, "lod2_wheel": 48},
    "preview_views": ("front34", "rear34", "side", "front", "rear", "wheel"), "preview_scale": 1.35,
    "body": {
        "stations": [-2.85, -2.84, -2.82, -2.79, -2.75, -2.68, -2.60, -2.52, -2.44, -2.36, -2.28, -2.15, -1.90,
                     -1.60, -1.40, -1.32, -1.29, -1.275],
        "ztop": [(-2.85, 1.24), (-2.82, 1.30), (-2.76, 1.36), (-2.66, 1.55), (-2.56, 1.78), (-2.46, 1.96), (-2.36, 2.07),
                 (-2.25, 2.12), (-1.60, 2.14), (-1.35, 2.12), (-1.29, 2.08), (-1.275, 2.02)],
        "drop": [(-2.85, 0.02), (-2.70, 0.03), (-2.40, 0.05), (-1.27, 0.04)],
        "wside": [(-2.85, 0.800), (-2.84, 0.835), (-2.82, 0.858), (-2.78, 0.872), (-2.60, 0.878), (-1.40, 0.878),
                  (-1.30, 0.870), (-1.275, 0.850)],
        "wroof": [(-2.85, 0.70), (-2.60, 0.76), (-2.30, 0.80), (-1.275, 0.80)],
        "wg_in": [(-2.85, 0.025), (-1.275, 0.025)],
        "zbelt": [(-2.85, 1.19), (-2.80, 1.24), (-2.60, 1.27), (-1.275, 1.29)],
        "zfloor": [(-2.85, 0.42), (-2.80, 0.36), (-2.60, 0.34), (-1.40, 0.34), (-1.275, 0.40)],
        "zrock": [(-2.85, 0.46), (-1.275, 0.46)],
        "rake": [(-2.85, 0.03), (-2.80, 0.0), (-1.30, 0.0), (-1.275, 0.01)],
        "decimate": 0.45, "cab": ((-2.85, -2.78), (3.0, 3.1)),
        "section": {"rock_min_drop": 0.10, "side_frac": 0.42, "shoulder_in": 0.016, "belt_in": 0.006, "g9_bulge": (0.0, 0.006),
                    "crown_x": 0.70, "crown_drop": 0.20, "rake_pivot": 0.80, "wroof_min_inset": 0.05},
        "cap_bulge": (-0.03, 0.0),
        "creases": {6: 0.9, 3: 0.6, 7: 0.5, 9: 0.75},
    },
    "panels": {
        "arch_x": 0.87, "arch_depth": 0.56, "gap_x": (0.50, 1.3), "win_x": (0.50, 1.3),
        "door_bottom": 0.83,
        "apillar_search": (-2.82, -1.6),
        "doors": [{"name": "F", "kind": "front", "front": -2.62, "line": -1.42, "frame_rear": -1.45, "bottom": 0.83}],
        "windshield": {"kind": "top", "y0": -2.66, "y1": -2.30, "inset": 0.05, "taper": 0.01, "z0": 1.3, "z1": 3.0},
        "rear_window": {"kind": "rear", "zb": 1.62, "zt": 1.92, "wb": 0.48, "wt": 0.46, "r": 0.04, "a0": -1.35, "a1": -1.0},
        "hood": {"kind": "rear", "w": 0.60, "z0": 0.92, "z1": 1.22, "r": 0.03, "y0": -3.2, "y1": -2.74},
        "bumpers": [],
        "apertures": [
            {"rect": [-0.81, 0.66, 0.81, 0.87, 0.03], "a0": -3.3, "a1": -2.72},      # lamp + grille panel
            {"sides": [{"rect": [0.70, 0.92, 0.80, 1.10, 0.012], "a0": -3.3, "a1": -2.70}]},  # corner indicators
        ],
        "lenses": [
            {"sides": [{"name": "headlight_lens_out", "group": "lens_clear", "rect": [0.6215, 0.7265, 0.7085, 0.8135, 0.0435], "a0": -3.3, "a1": -2.72},
                       {"name": "headlight_lens_in", "group": "lens_clear", "rect": [0.4815, 0.7265, 0.5685, 0.8135, 0.0435], "a0": -3.3, "a1": -2.72},
                       {"name": "indicator_lens", "group": "lens_amber", "rect": [0.70, 0.92, 0.80, 1.10, 0.012], "a0": -3.3, "a1": -2.70}]},
        ],
        "plates": {},
    },
    "wheel": {"barrel_seg": 32, "disc_seg_per_hole": 6, "width": 0.195, "rim_r": 0.203, "lip_r": 0.211, "style": "steel", "holes": 6, "hole_r": 0.024, "lugs": 6,
              "lug_r": 0.080, "cap_r": 0.050, "disc_r": 0.150, "profile": "v2", "tyre_seg": 40, "dish": 0.085, "tread_pitch": 2,
              "tread_depth": 0.008, "rear_dual": 0.225},
    "parts": [
        {"kit": "boxes", "items": [("lamp_panel", "black_trim", (0, -2.775, 0.765), (1.60, 0.05, 0.20), 0.012)]},
        {"kit": "headlights", "x": 0.595, "z": 0.77,
         "elements": [{"type": "reflector", "x": 0.665, "r": 0.040, "seg": 20}, {"type": "reflector", "x": 0.525, "r": 0.040, "seg": 20}]},
        {"custom": "front_end"},
        {"kit": "window_seals", "fixed": True},
        {"kit": "mirrors", "y": -2.60, "dz": 0.20, "size": (0.12, 0.06, 0.30), "reach": 0.30, "group": "black_trim",
         "arm": {"drop": 0.30, "r": 0.012}},
        {"kit": "door_handles", "handles": [("F", -1.60, True)], "dz": 0.11, "group": "black_trim"},
        {"kit": "wipers", "arms": [(0.38, 0.66), (-0.30, 0.64)], "y": -2.67, "sweep_dy": 0.03,
         "cowl": {"y": -2.70, "ray_y": -2.705, "size": (1.50, 0.04, 0.014), "tilt": -40}},
        {"custom": "box_body"},
        {"custom": "chassis"},
        {"kit": "mudflaps", "zt": 0.82, "zb": 0.18, "inset": 0.12, "w": 0.30, "axles": "R"},
        {"kit": "wheel_wells", "inner": 0.52, "outer": 0.85, "hub_x": 0.75, "axles": "F"},
        {"kit": "suspension", "hub_x": 0.75, "top_dz": 0.40, "leaf": "FR", "leaf_len": 1.30, "leaves": 5},
        {"kit": "beam_axle", "hub_x": 0.75, "r": 0.055},
        # ---- cab interior (right-hand drive, three abreast)
        {"kit": "boxes", "items": [
            ("floor_carpet", "interior_carpet", (0, -2.05, 0.86), (1.60, 1.10, 0.02)),
            ("engine_hump", "interior_plastic", (0.05, -1.70, 0.98), (0.50, 0.50, 0.22), 0.06, 3),
            ("dash_lower", "interior_plastic", (0, -2.55, 1.15), (1.62, 0.22, 0.26), 0.03, 3),
            ("dash_top", "interior_dark", (0, -2.58, 1.31), (1.64, 0.26, 0.06), 0.025, 3, 14),
            ("dash_binnacle", "interior_dark", (DRIVER_X, -2.47, 1.36), (0.36, 0.12, 0.10), 0.03, 3),
            ("dash_gauges", "screen", (DRIVER_X, -2.409, 1.345), (0.30, 0.004, 0.07), 0.01),
            ("radio", "screen", (0.10, -2.439, 1.20), (0.18, 0.006, 0.05), 0.004),
            ("tacho_unit", "interior_dark", (0.40, -2.48, 1.22), (0.22, 0.10, 0.07), 0.008),
            ("cab_back_wall", "interior_plastic", (0, -1.36, 1.40), (1.66, 0.03, 1.00), 0.008),
            ("rearview_mirror", "interior_dark", (0, -2.30, 1.98), (0.20, 0.03, 0.055), 0.012, 2)]},
        {"kit": "steering", "c": (DRIVER_X, -2.36, 1.32), "tilt": -78, "r": 0.22, "column_end": (DRIVER_X, -2.55, 1.10)},
        {"kit": "seat", "name": "seat_FR", "x": DRIVER_X, "y": -1.72, "z": 1.14, "w": 0.50, "back_h": 0.62, "recline": 10},
        {"kit": "seat", "name": "seat_bench", "x": 0.30, "y": -1.72, "z": 1.12, "w": 0.90, "back_h": 0.58, "recline": 10, "bench": True,
         "headrest_x": [0.22]},
        {"kit": "door_cards", "armrest_z": 1.30, "ray_z": 1.32, "inset": 0.07},
        {"kit": "headliner", "z_min": 2.0, "y0": -2.25, "y1": -1.40},
        {"kit": "glass_frit", "which": ("windscreen",), "w": 0.05},
    ],
}


def front_end(p):
    """Grille slats between the lamps, chrome bumper with indicators and the plate, cab steps, corner lamps."""
    from vkit import panels as P
    from vkit.shapes import box, lathe
    out = []
    yf = P.front_face_y(0.0, 0.76)
    for i in range(4):
        z = 0.700 + i * 0.044
        s = box(f"grille_slat_{i}", (0, yf + 0.03, z), (0.82, 0.03, 0.012), bevel=0.003)
        out.append((s.name, "grille", s))
    badge = lathe("grille_badge", [(0.0, 0.0), (0.04, 0.0), (0.044, -0.006), (0.044, -0.012)], (0, yf + 0.006, 1.02), "Y", 20, sign=-1)
    out.append((badge.name, "chrome", badge))
    for sx, side in ((1, "L"), (-1, "R")):
        for k, x in (("out", 0.665), ("in", 0.525)):
            y = P.front_face_y(sx * x, 0.77)
            b = lathe(f"headlight_bezel_{k}_{side}", [(0.040, 0.008), (0.046, 0.002), (0.050, -0.006), (0.046, -0.010)], (sx * x, y, 0.77), "Y", 24)
            out.append((b.name, "chrome", b))
    # bumper: a chrome channel across the front with black end caps and amber lamps
    yb = P.front_face_y(0.0, 0.55) - 0.10
    bp = box("bumper_bar", (0, yb, 0.52), (1.80, 0.16, 0.22), bevel=0.02, seg=3)
    out.append((bp.name, "chrome", bp))
    for sx, side in ((1, "L"), (-1, "R")):
        cap = box(f"bumper_cap_{side}", (sx * 0.86, yb + 0.04, 0.52), (0.10, 0.20, 0.23), bevel=0.03, seg=3)
        out.append((cap.name, "black_trim", cap))
        ind = box(f"indicator_F_{side}", (sx * 0.68, yb - 0.081, 0.555), (0.14, 0.012, 0.05), bevel=0.004)
        out.append((ind.name, "emitter_amber", ind))
        x = P.side_x(-2.20, 0.95, sx)[0]
        for k, z in ((0, 0.62), (1, 0.42)):
            st = box(f"cab_step_{side}{k}", (sx * (abs(x) - 0.12), -1.56, z), (0.26, 0.26, 0.05), bevel=0.008)
            out.append((st.name, "black_metal", st))
        bracket = box(f"cab_step_bracket_{side}", (sx * (abs(x) - 0.24), -1.56, 0.56), (0.04, 0.24, 0.34), bevel=0.006)
        out.append((bracket.name, "black_metal", bracket))
    pl = box("plate_F", (0, yb - 0.084, 0.52), (0.33, 0.006, 0.165), bevel=0.003)
    out.append((pl.name, "plate", pl))
    # marker lamps on the cab roof front edge
    for i, x in enumerate((-0.25, 0.0, 0.25)):
        z, n = P.top_z(x, -2.30)
        m = box(f"roof_marker_{i}", (x, -2.32, z + 0.02), (0.08, 0.04, 0.03), bevel=0.008)
        out.append((m.name, "emitter_amber", m))
    return out


def box_body(p):
    """The aluminium box: skins (livery panels), corner posts, top / bottom rails, vertical ribs, a
    roll-up rear door with slats, rear frame, marker lamps."""
    from vkit.shapes import box
    b = BOX
    out = []
    y0, y1, w, z0, z1 = b["y0"], b["y1"], b["w"], b["z0"], b["z1"]
    L = y1 - y0
    yc = (y0 + y1) / 2
    t = 0.02
    # skins
    for sx, side in ((1, "L"), (-1, "R")):
        sk = box(f"box_side_{side}", (sx * (w - t / 2), yc, (z0 + z1) / 2 + 0.02), (t, L - 0.10, z1 - z0 - 0.16), bevel=0.003)
        out.append((sk.name, "cargo", sk))
    roof = box("box_roof", (0, yc, z1 - 0.01), (2 * w - 0.06, L - 0.06, 0.02), bevel=0.004)
    out.append((roof.name, "cargo", roof))
    front = box("box_front", (0, y0 + 0.01, (z0 + z1) / 2), (2 * w - 0.06, 0.02, z1 - z0 - 0.04), bevel=0.003)
    out.append((front.name, "cargo", front))
    floor = box("box_floor", (0, yc, z0 + 0.03), (2 * w, L, 0.06), bevel=0.01)
    out.append((floor.name, "cargo_frame", floor))
    # frame: corner posts and rails
    for sx, side in ((1, "L"), (-1, "R")):
        for k, y in (("F", y0 + 0.04), ("R", y1 - 0.04)):
            post = box(f"box_post_{k}{side}", (sx * (w - 0.03), y, (z0 + z1) / 2), (0.07, 0.08, z1 - z0), bevel=0.012, seg=2)
            out.append((post.name, "cargo_frame", post))
        for k, z in (("top", z1 - 0.05), ("bot", z0 + 0.09)):
            rail = box(f"box_rail_{k}_{side}", (sx * (w - 0.005), yc, z), (0.03, L - 0.02, 0.09 if k == "top" else 0.10), bevel=0.008)
            out.append((rail.name, "cargo_frame", rail))
        n = 9
        for i in range(1, n):
            y = y0 + L * i / n
            rib = box(f"box_rib_{side}{i}", (sx * (w + 0.006), y, (z0 + z1) / 2), (0.016, 0.05, z1 - z0 - 0.2), bevel=0.006)
            out.append((rib.name, "cargo_frame", rib))
    for k, x in (("L", w - 0.03), ("R", -w + 0.03)):
        pass
    top_front = box("box_rail_front", (0, y0 + 0.03, z1 - 0.05), (2 * w - 0.02, 0.07, 0.09), bevel=0.008)
    out.append((top_front.name, "cargo_frame", top_front))
    # rear: frame, header, roll-up door with slats and a handle, step
    hdr = box("box_header", (0, y1 - 0.03, z1 - 0.12), (2 * w - 0.08, 0.07, 0.22), bevel=0.01)
    out.append((hdr.name, "cargo_frame", hdr))
    sill = box("box_sill", (0, y1 - 0.03, z0 + 0.06), (2 * w - 0.08, 0.08, 0.12), bevel=0.01)
    out.append((sill.name, "cargo_frame", sill))
    zd0, zd1 = z0 + 0.12, z1 - 0.23
    n = 18
    for i in range(n):
        z = zd0 + (zd1 - zd0) * (i + 0.5) / n
        sl = box(f"roller_slat_{i}", (0, y1 - 0.02, z), (2 * w - 0.20, 0.025, (zd1 - zd0) / n - 0.006), bevel=0.005)
        out.append((sl.name, "cargo", sl))
    for sx, side in ((1, "L"), (-1, "R")):
        g = box(f"roller_guide_{side}", (sx * (w - 0.09), y1 - 0.025, (zd0 + zd1) / 2), (0.04, 0.04, zd1 - zd0), bevel=0.006)
        out.append((g.name, "cargo_frame", g))
    hd = box("roller_handle", (0, y1 + 0.005, zd0 + 0.10), (0.30, 0.03, 0.03), bevel=0.008)
    out.append((hd.name, "chrome", hd))
    # marker lamps along the top corners
    for sx, side in ((1, "L"), (-1, "R")):
        for k, y in (("F", y0 + 0.05), ("R", y1 - 0.05)):
            m = box(f"box_marker_{k}{side}", (sx * (w + 0.01), y, z1 - 0.10), (0.03, 0.06, 0.04), bevel=0.006)
            out.append((m.name, "emitter_amber" if k == "F" else "emitter_tail", m))
    return out


def chassis(p):
    """Ladder frame, side guards, fuel tank, battery box, exhaust, underrun bar with the tail lamps and plate."""
    import bmesh
    from vkit.geom import bm_cyl, bm_tube_path
    from vkit.shapes import box, lathe, obj
    out = []
    y1 = BOX["y1"]
    for sx, side in ((1, "L"), (-1, "R")):
        r = box(f"frame_rail_{side}", (sx * 0.42, -0.40, 0.66), (0.08, 6.0, 0.20), bevel=0.01)
        out.append((r.name, "underbody_metal", r))
    for i, y in enumerate((-2.5, -1.40, -0.30, 0.95, 1.90, 2.70)):
        c = box(f"frame_cross_{i}", (0, y, 0.66), (0.84, 0.08, 0.14), bevel=0.01)
        out.append((c.name, "underbody_metal", c))
    # longitudinal bearers under the box floor
    for k, x in enumerate((-0.80, -0.40, 0.0, 0.40, 0.80)):
        b = box(f"box_bearer_{k}", (x, (BOX["y0"] + y1) / 2, BOX["z0"] - 0.04), (0.06, y1 - BOX["y0"], 0.08), bevel=0.006)
        out.append((b.name, "cargo_frame", b))
    for k in range(10):
        y = BOX["y0"] + 0.1 + k * (y1 - BOX["y0"] - 0.2) / 9
        b = box(f"box_joist_{k}", (0, y, BOX["z0"] - 0.11), (1.90, 0.05, 0.06), bevel=0.006)
        out.append((b.name, "cargo_frame", b))
    # side guards between the axles
    for sx, side in ((1, "L"), (-1, "R")):
        for k, z in enumerate((0.55, 0.78)):
            g = box(f"side_guard_{side}{k}", (sx * 0.93, (-1.55 + 0.50) / 2, z), (0.03, 1.80, 0.09), bevel=0.01)
            out.append((g.name, "black_metal", g))
    # fuel tank (left) and battery box (right)
    bm = bmesh.new()
    bm_cyl(bm, (0.68, -0.55, 0.55), 0.20, 0.70, seg=24, axis="Y")
    t = obj("fuel_tank", bm)
    out.append((t.name, "chrome", t))
    bb = box("battery_box", (-0.70, -0.55, 0.58), (0.36, 0.55, 0.32), bevel=0.02)
    out.append((bb.name, "black_metal", bb))
    # exhaust: under the cab to a tip behind the right rear wheel
    bm = bmesh.new()
    bm_tube_path(bm, [(-0.20, -2.30, 0.50), (-0.25, -1.40, 0.48), (-0.60, -0.20, 0.48), (-0.85, 0.30, 0.45)], 0.035, 10)
    pipe = obj("exhaust_pipe", bm)
    out.append((pipe.name, "underbody_metal", pipe))
    sil = box("silencer", (-0.40, -0.95, 0.48), (0.40, 0.55, 0.22), bevel=0.05, seg=3)
    out.append((sil.name, "underbody_metal", sil))
    tip = lathe("exhaust_tip_R", [(0.042, -0.10), (0.042, 0.01), (0.036, 0.016), (0.034, -0.05)], (-0.86, 0.33, 0.45), "Y", 16)
    out.append((tip.name, "exhaust", tip))
    # rear underrun bar with lamps, reflectors and the plate
    yb = y1 + 0.06
    bar = box("underrun_bar", (0, yb, 0.62), (1.86, 0.10, 0.16), bevel=0.012)
    out.append((bar.name, "black_metal", bar))
    for sx, side in ((1, "L"), (-1, "R")):
        st = box(f"underrun_strut_{side}", (sx * 0.42, y1 - 0.10, 0.80), (0.06, 0.28, 0.30), bevel=0.01)
        out.append((st.name, "black_metal", st))
        x = sx * 0.73
        h = box(f"taillight_housing_{side}", (x, yb + 0.03, 0.62), (0.34, 0.06, 0.13), bevel=0.01)
        out.append((h.name, "black_trim", h))
        for nm, dx, grp in (("tail_brake", 0.11, "emitter_tail"), ("tail_indicator", 0.0, "emitter_amber"), ("tail_reverse", -0.11, "emitter_reverse")):
            e = box(f"{nm}_{side}", (x + sx * dx, yb + 0.062, 0.62), (0.095, 0.012, 0.09), bevel=0.004)
            out.append((e.name, grp, e))
        lens = box(f"taillight_lens_{side}", (x, yb + 0.07, 0.62), (0.33, 0.008, 0.11), bevel=0.004)
        out.append((lens.name, "lens_red", lens))
    pl = box("plate_R", (0, yb + 0.055, 0.62), (0.33, 0.006, 0.165), bevel=0.003)
    out.append((pl.name, "plate", pl))
    pll = box("plate_lamp", (0, yb + 0.05, 0.72), (0.10, 0.03, 0.02), bevel=0.004)
    out.append((pll.name, "emitter_reverse", pll))
    return out
