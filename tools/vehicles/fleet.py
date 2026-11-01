"""Fleet data shared by textures.py, export.py and render.py (plain Python, no Blender).

For every vehicle: its traffic class and spawn weight, texture resolutions, and its
Pigment variants (paint, two-tone accents, liveries as decals, plates, hidden parts, wear).
Decal positions are in the vehicle's spec frame (Blender metres, before the ride-height drop:
the vehicle faces -Y, Z up, +X = its left side); Pigment snaps them onto the surface (a ray
along the normal from 0.5 m outside), so they only need to be roughly on it.

Decal entries:
    ("side", image, y, z, width)          both sides; the right side uses <image>_r if it exists
    ("side_same", image, y, z, width)     both sides, same image (text that must read normally)
    ("left" / "right", image, y, z, width)
    ("top", image, y, z, width, rotation) roof / hood / deck, seen from above (z ~ surface height)
    ("rear", image, x, z, width) / ("front", image, x, z, width)
    ("plate", image)                      fitted to plate_F and plate_R
"""

D = "assets/decals/fleet/"
CAR = "assets/decals/car/"
STORY = "assets/decals/story/"


def paint(rgb, metallic=0.2, roughness=0.33, coat=1.0, coat_roughness=0.03, flake=0.08):
    return {"base_color": list(rgb), "metallic": metallic, "roughness": roughness, "coat": coat, "coat_roughness": coat_roughness, "flake": flake}


PAINT = {
    "pearl": paint((0.86, 0.87, 0.88), 0.15, 0.30, flake=0.04),
    "white": paint((0.80, 0.81, 0.81), 0.0, 0.40, coat=0.8, coat_roughness=0.06, flake=0.0),
    "silver": paint((0.52, 0.53, 0.55), 0.80, 0.34, flake=0.30),
    "gunmetal": paint((0.11, 0.115, 0.12), 0.75, 0.34, flake=0.25),
    "black": paint((0.012, 0.012, 0.014), 0.30, 0.30, flake=0.10),
    "maroon": paint((0.16, 0.018, 0.028), 0.50, 0.32, flake=0.15),
    "cream": paint((0.78, 0.72, 0.56), 0.0, 0.38, coat=0.9, coat_roughness=0.05, flake=0.0),
    "mint": paint((0.42, 0.68, 0.58), 0.05, 0.36, coat=0.9, coat_roughness=0.05, flake=0.0),
    "cherry": paint((0.60, 0.04, 0.045), 0.10, 0.32, flake=0.05),
    "sky": paint((0.32, 0.52, 0.72), 0.20, 0.34, flake=0.10),
    "purple_candy": paint((0.07, 0.018, 0.13), 0.60, 0.30, coat_roughness=0.02, flake=0.40),
    "lime": paint((0.72, 0.68, 0.035), 0.10, 0.32, flake=0.05),
    "racing_red": paint((0.52, 0.02, 0.02), 0.20, 0.30, flake=0.05),
    "orange": paint((0.85, 0.33, 0.04), 0.05, 0.34, flake=0.02),
    "navy": paint((0.018, 0.032, 0.085), 0.50, 0.32, flake=0.12),
    "recycle_green": paint((0.05, 0.28, 0.11), 0.10, 0.38, coat=0.8, coat_roughness=0.08, flake=0.0),
    "dreamlink": paint((0.20, 0.045, 0.30), 0.55, 0.32, flake=0.35),
    "noctis": paint((0.014, 0.014, 0.016), 0.20, 0.48, coat=0.5, coat_roughness=0.25, flake=0.02),
    "teal_candy": paint((0.02, 0.17, 0.17), 0.55, 0.32, flake=0.12),
    "midnight_candy": paint((0.018, 0.035, 0.11), 0.55, 0.33, coat_roughness=0.02, flake=0.12),
    "faded_beige": paint((0.36, 0.31, 0.22), 0.0, 0.72, coat=0.25, coat_roughness=0.45, flake=0.0),
    "faded_blue": paint((0.12, 0.20, 0.30), 0.10, 0.70, coat=0.25, coat_roughness=0.45, flake=0.0),
    "faded_red": paint((0.30, 0.06, 0.05), 0.0, 0.72, coat=0.2, coat_roughness=0.5, flake=0.0),
    "primer": paint((0.30, 0.31, 0.31), 0.0, 0.82, coat=0.0, coat_roughness=0.5, flake=0.0),
    "meridian_white": paint((0.88, 0.90, 0.91), 0.10, 0.25, coat_roughness=0.02, flake=0.03),
    "meridian_night": paint((0.02, 0.025, 0.035), 0.55, 0.28, coat_roughness=0.02, flake=0.20),
}
BLACK_RESIN = {"base_color": [0.03, 0.03, 0.032], "metallic": 0.0, "roughness": 0.62, "coat": 0.0, "flake": 0.0}
BOX_WHITE = {"base_color": [0.78, 0.79, 0.80], "metallic": 0.1, "roughness": 0.40, "coat": 0.6, "coat_roughness": 0.10, "flake": 0.0}
BOX_SILVER = {"base_color": [0.62, 0.63, 0.64], "metallic": 0.85, "roughness": 0.42, "coat": 0.0, "flake": 0.0}

# ------------------------------------------------------------------ the vehicles

VEHICLES = {
    "tsubame": {
        "class": "sedan", "weight": 1.0, "res": 4096, "wheel_res": 2048, "legacy": True,
        "tyre": CAR + "tyre_ring.png", "caliper_logo": CAR + "caliper_logo.png",
        # the hero keeps its authored Pigment recipe (textures.hero_body_script); these are added
        "variants": [
            {"name": "security", "label": "Hoshikawa Security cruiser", "kind": "police", "weight": 0.6},
            {"name": "cab", "label": "Koen Cab", "kind": "taxi", "weight": 1.2},
            {"name": "pearl", "label": "civilian, pearl white", "kind": "civilian", "weight": 1.0, "paint": "pearl",
             "plate": D + "plate_private_1.png", "civilian": True},
            {"name": "maroon", "label": "civilian, maroon metallic", "kind": "civilian", "weight": 0.8, "paint": "maroon",
             "plate": D + "plate_private_2.png", "civilian": True},
            {"name": "gunmetal", "label": "civilian, gunmetal", "kind": "civilian", "weight": 0.8, "paint": "gunmetal",
             "plate": D + "plate_private_3.png", "civilian": True},
            {"name": "exec", "label": "Hoshikawa Dynamics executive car", "kind": "corporate", "weight": 0.4, "paint": "black",
             "plate": D + "plate_corp.png", "civilian": True,
             "decals": [("side_same", D + "hd_door_exec.png", -0.33, 0.70, 0.62), ("top", D + "meridian_eye_cyan.png", 0.62, 1.39, 0.30, 0)]},
            {"name": "hinode", "label": "Hinode Taxi", "kind": "taxi", "weight": 1.0, "paint": "orange",
             "accents": [{"parts": ["hood", "trunk_lid"], "paint": "cream"}],
             "plate": D + "plate_commercial_1.png", "taxi_sign": True,
             "decals": [("side_same", D + "hinode_door.png", -0.33, 0.70, 0.78), ("side", D + "stripe_cream.png", -0.05, 0.47, 3.2),
                        ("top", D + "hinode_number.png", 0.62, 1.39, 0.55, 90), ("rear", D + "hinode_number.png", 0.0, 0.94, 0.34)]},
            {"name": "rusty", "label": "beaten-up, rust and primer", "kind": "beater", "weight": 0.6, "paint": "faded_blue",
             "accents": [{"parts": ["door_FR", "hood"], "paint": "primer"}],
             "plate": D + "plate_private_2.png", "civilian": True, "rusty": True,
             "decals": [("rear", D + "rusty_for_sale.png", -0.35, 0.95, 0.30)]},
        ],
    },
    "mame": {
        "class": "kei", "weight": 2.2, "res": 2048, "wheel_res": 1024,
        "tyre": D + "tyre_mame.png", "badge": D + "badge_mame.png", "rim": "steel_silver",
        "variants": [
            {"name": "cream", "label": "civilian, cream", "kind": "civilian", "weight": 1.2, "paint": "cream", "plate": D + "plate_kei_1.png"},
            {"name": "mint", "label": "civilian, mint", "kind": "civilian", "weight": 1.0, "paint": "mint", "plate": D + "plate_kei_2.png"},
            {"name": "cherry", "label": "civilian, cherry red", "kind": "civilian", "weight": 1.0, "paint": "cherry", "plate": D + "plate_kei_1.png"},
            {"name": "sky", "label": "civilian, sky blue", "kind": "civilian", "weight": 0.9, "paint": "sky", "plate": D + "plate_kei_2.png"},
            {"name": "silver", "label": "civilian, silver", "kind": "civilian", "weight": 1.0, "paint": "silver", "plate": D + "plate_kei_1.png"},
            {"name": "tsuru", "label": "Tsuru Express courier", "kind": "corporate", "weight": 0.8, "paint": "white",
             "plate": D + "plate_commercial_2.png",
             "decals": [("side_same", D + "tsuru_side.png", 0.05, 0.62, 1.20), ("rear", D + "tsuru_side.png", 0.0, 0.80, 0.62)]},
            {"name": "inspector", "label": "MERIDIAN score inspector", "kind": "corporate", "weight": 0.5, "paint": "meridian_white",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "values": BLACK_RESIN}],
             "plate": D + "plate_meridian.png",
             "decals": [("side_same", D + "meridian_inspector.png", 0.10, 0.63, 1.25), ("top", D + "meridian_eye_ink.png", -1.25, 0.80, 0.42, 0),
                        ("side", D + "stripe_cyan.png", 0.0, 0.40, 2.6)]},
            {"name": "rusty", "label": "beaten-up kei, rust and UNPLUG tag", "kind": "beater", "weight": 0.7, "paint": "faded_red",
             "accents": [{"parts": ["door_RL", "hatch"], "paint": "primer"}], "plate": D + "plate_kei_2.png", "rusty": True,
             "decals": [("right", STORY + "graffiti_unplug.png", 0.62, 0.66, 0.50), ("rear", D + "rusty_for_sale.png", 0.0, 1.08, 0.36)]},
        ],
    },
    "hakobi": {
        "class": "van", "weight": 1.4, "res": 2048, "wheel_res": 1024,
        "tyre": D + "tyre_hakobi.png", "badge": D + "badge_hakobi.png", "rim": "steel_white",
        "variants": [
            {"name": "white", "label": "plain white work van", "kind": "civilian", "weight": 1.2, "paint": "white",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "values": BLACK_RESIN}], "plate": D + "plate_commercial_1.png"},
            {"name": "silver", "label": "silver work van", "kind": "civilian", "weight": 0.8, "paint": "silver",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "values": BLACK_RESIN}], "plate": D + "plate_commercial_2.png"},
            {"name": "dreamlink", "label": "DREAMLINK pod delivery", "kind": "corporate", "weight": 1.0, "paint": "dreamlink",
             "plate": D + "plate_commercial_1.png",
             "decals": [("side_same", D + "dreamlink_side.png", 0.55, 1.32, 3.0), ("rear", D + "dreamlink_logo.png", 0.0, 1.02, 0.80)]},
            {"name": "noctis", "label": "NOCTIS collection van", "kind": "corporate", "weight": 0.8, "paint": "noctis",
             "plate": D + "plate_commercial_2.png",
             "decals": [("side_same", D + "noctis_side.png", 0.55, 1.32, 2.9), ("rear", D + "noctis_logo.png", 0.0, 1.02, 0.72)]},
            {"name": "tsuru", "label": "Tsuru Express parcels", "kind": "corporate", "weight": 1.0, "paint": "white",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "values": BLACK_RESIN}], "plate": D + "plate_commercial_1.png",
             "decals": [("side_same", D + "tsuru_side.png", 0.55, 1.42, 2.7), ("side", D + "band_tsuru.png", 0.10, 0.72, 4.2),
                        ("rear", D + "tsuru_side.png", 0.0, 1.02, 0.95)]},
            {"name": "facilities", "label": "Hoshikawa Dynamics facilities", "kind": "corporate", "weight": 0.6, "paint": "navy",
             "plate": D + "plate_corp.png",
             "decals": [("side_same", D + "hd_facilities.png", 0.55, 1.40, 2.6), ("side", D + "band_hoshikawa.png", 0.10, 0.72, 4.2)]},
            {"name": "ramen", "label": "Ramen Kira night stall", "kind": "street", "weight": 0.5, "paint": "cream",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "paint": "cherry"}], "plate": D + "plate_commercial_2.png",
             "decals": [("side_same", D + "ramen_side.png", 0.55, 1.35, 2.5)]},
            {"name": "rusty", "label": "beaten-up van, rust and graffiti", "kind": "beater", "weight": 0.6, "paint": "faded_beige",
             "accents": [{"parts": ["door_SR"], "paint": "primer"}, {"parts": ["bumper_F", "bumper_R"], "values": BLACK_RESIN}],
             "plate": D + "plate_commercial_2.png", "rusty": True,
             "decals": [("left", STORY + "graffiti_who_owns.png", 0.75, 1.30, 1.6), ("right", STORY + "graffiti_unplug.png", 1.20, 1.25, 1.2),
                        ("right", STORY + "stencil_eye_crossed.png", -0.40, 1.35, 0.45)]},
        ],
    },
    "hayate": {
        "class": "sports", "weight": 0.7, "res": 2048, "wheel_res": 1024, "player": True,
        "tyre": D + "tyre_hayate.png", "badge": D + "badge_hayate.png", "rim": "gold",
        "variants": [
            {"name": "purple", "label": "midnight purple candy", "kind": "civilian", "weight": 1.0, "paint": "purple_candy", "plate": D + "plate_private_3.png"},
            {"name": "red", "label": "racing red", "kind": "civilian", "weight": 1.0, "paint": "racing_red", "plate": D + "plate_private_1.png"},
            {"name": "pearl_stripes", "label": "pearl white, twin stripes", "kind": "civilian", "weight": 0.8, "paint": "pearl",
             "plate": D + "plate_private_2.png",
             "decals": [("top", D + "twin_stripes_black.png", -1.25, 0.72, 1.50, 90), ("top", D + "twin_stripes_black.png", 0.30, 1.23, 1.0, 90),
                        ("top", D + "twin_stripes_black.png", 1.88, 0.88, 0.55, 90)]},
            {"name": "lime", "label": "lime yellow", "kind": "civilian", "weight": 0.6, "paint": "lime", "plate": D + "plate_private_3.png"},
            {"name": "gunmetal", "label": "gunmetal", "kind": "civilian", "weight": 0.8, "paint": "gunmetal", "plate": D + "plate_private_1.png"},
            {"name": "racing", "label": "Kanzaki Racing #27", "kind": "street", "weight": 0.4, "paint": "pearl",
             "accents": [{"parts": ["hood"], "paint": "racing_red"}], "plate": D + "plate_private_2.png",
             "decals": [("side_same", D + "roundel_27.png", 0.02, 0.50, 0.42), ("side", D + "stripe_vermilion.png", -0.20, 0.30, 3.6),
                        ("side_same", D + "sponsor_kanzaki.png", 0.95, 0.62, 0.62), ("side_same", D + "sponsor_jailbreak.png", -1.45, 0.48, 0.42),
                        ("top", D + "racing_27.png", 0.30, 1.23, 0.42, 90)]},
            {"name": "pursuit", "label": "Hoshikawa Security pursuit", "kind": "police", "weight": 0.4, "paint": "midnight_candy",
             "accents": [{"parts": ["door_F"], "paint": "pearl"}], "plate": D + "plate_hs_2.png",
             "decals": [("side_same", D + "hs_pursuit.png", 0.0, 0.52, 0.80), ("side", CAR + "hs_flash.png", -0.05, 0.36, 3.3),
                        ("top", CAR + "hs_crest.png", -1.25, 0.72, 0.40, 0), ("top", CAR + "hs_unit_roof.png", 0.30, 1.23, 0.80, 90),
                        ("rear", CAR + "meridian_linked.png", 0.45, 0.45, 0.22)]},
            {"name": "rusty", "label": "street beater, primer and tags", "kind": "beater", "weight": 0.4, "paint": "faded_red",
             "accents": [{"parts": ["hood", "bumper_F"], "paint": "primer"}], "plate": D + "plate_private_3.png", "rusty": True,
             "decals": [("left", STORY + "graffiti_unplug.png", 0.95, 0.55, 0.55), ("right", STORY + "stencil_eye_crossed.png", 0.95, 0.58, 0.24)]},
        ],
    },
    "kaiun": {
        "class": "truck", "weight": 0.7, "res": 2048, "wheel_res": 1024, "side_x": 0.985, "rear_y": 2.86,
        "tyre": D + "tyre_kaiun.png", "badge": D + "badge_kaiun.png", "rim": "steel_white",
        "variants": [
            {"name": "white", "label": "plain white box truck", "kind": "civilian", "weight": 1.0, "paint": "white", "cargo": BOX_SILVER,
             "plate": D + "plate_commercial_1.png"},
            {"name": "logistics", "label": "Hoshikawa Dynamics logistics", "kind": "corporate", "weight": 1.0, "paint": "navy", "cargo": BOX_WHITE,
             "plate": D + "plate_corp.png",
             "decals": [("side_same", D + "hd_logistics.png", 0.78, 2.05, 3.4), ("side", D + "band_hoshikawa.png", 0.78, 1.28, 3.8)]},
            {"name": "dreamlink", "label": "DREAMLINK pod freight", "kind": "corporate", "weight": 0.8, "paint": "white", "cargo": BOX_WHITE,
             "plate": D + "plate_commercial_2.png",
             "decals": [("side_same", D + "dreamlink_side.png", 0.78, 2.0, 3.6)]},
            {"name": "noctis", "label": "NOCTIS collection truck", "kind": "corporate", "weight": 0.6, "paint": "noctis",
             "cargo": dict(PAINT["noctis"]), "plate": D + "plate_commercial_1.png",
             "decals": [("side_same", D + "noctis_side.png", 0.78, 2.0, 3.5)]},
            {"name": "recycle", "label": "Shigen Recycle", "kind": "corporate", "weight": 0.7, "paint": "recycle_green", "cargo": BOX_WHITE,
             "plate": D + "plate_commercial_2.png",
             "decals": [("side_same", D + "recycle_side.png", 0.78, 2.05, 3.3), ("side", D + "band_recycle.png", 0.78, 1.28, 3.8)]},
            {"name": "tsuru", "label": "Tsuru Express freight", "kind": "corporate", "weight": 0.8, "paint": "white", "cargo": BOX_WHITE,
             "plate": D + "plate_commercial_1.png",
             "decals": [("side_same", D + "tsuru_side.png", 0.78, 2.1, 3.4), ("side", D + "band_tsuru.png", 0.78, 1.28, 3.8)]},
            {"name": "rusty", "label": "beaten-up truck, rust and graffiti", "kind": "beater", "weight": 0.5, "paint": "faded_blue",
             "cargo": BOX_SILVER, "plate": D + "plate_commercial_2.png", "rusty": True,
             "decals": [("left", STORY + "graffiti_who_owns.png", 0.40, 1.95, 2.0), ("right", STORY + "graffiti_lying.png", 1.20, 1.90, 2.0),
                        ("right", STORY + "graffiti_unplug.png", -0.40, 2.30, 1.2)]},
        ],
    },
    "kago": {
        "class": "robotaxi", "weight": 1.2, "res": 2048, "wheel_res": 1024,
        "tyre": D + "tyre_kago.png", "badge": D + "badge_kago.png", "rim": "aero_white",
        "variants": [
            {"name": "meridian", "label": "MERIDIAN Ride, white", "kind": "taxi", "weight": 1.5, "paint": "meridian_white",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "paint": "meridian_night"}], "plate": D + "plate_meridian.png",
             "decals": [("side_same", D + "meridian_ride.png", 0.0, 0.62, 1.15), ("side", D + "stripe_cyan.png", 0.0, 0.36, 3.2)]},
            {"name": "night", "label": "MERIDIAN Ride, night black", "kind": "taxi", "weight": 1.0, "paint": "meridian_night",
             "plate": D + "plate_meridian.png",
             "decals": [("side_same", D + "meridian_ride_dark.png", 0.0, 0.62, 1.15), ("side", D + "stripe_cyan.png", 0.0, 0.36, 3.2)]},
            {"name": "dreamlink", "label": "DREAMLINK ad wrap", "kind": "taxi", "weight": 0.7, "paint": "dreamlink", "plate": D + "plate_meridian.png",
             "decals": [("side_same", D + "dreamlink_side.png", 0.0, 0.60, 1.30), ("front", D + "dreamlink_logo.png", 0.0, 0.47, 0.40)]},
            {"name": "noctis", "label": "NOCTIS ad wrap", "kind": "taxi", "weight": 0.5, "paint": "noctis", "plate": D + "plate_meridian.png",
             "decals": [("side_same", D + "noctis_side.png", 0.0, 0.60, 1.25)]},
            {"name": "patrol", "label": "Hoshikawa Security patrol pod", "kind": "police", "weight": 0.4, "paint": "midnight_candy",
             "accents": [{"parts": ["door_S"], "paint": "pearl"}], "plate": D + "plate_hs_2.png",
             "decals": [("side_same", D + "hs_patrol_pod.png", 0.0, 0.62, 0.95), ("side", CAR + "hs_flash.png", 0.0, 0.36, 3.2),
                        ("top", CAR + "hs_unit_roof.png", 0.55, 1.78, 0.70, 90)]},
            {"name": "vandalized", "label": "vandalized pod, UNPLUG tags", "kind": "beater", "weight": 0.4, "paint": "meridian_white",
             "accents": [{"parts": ["bumper_F", "bumper_R"], "paint": "meridian_night"}], "plate": D + "plate_meridian.png", "rusty": True,
             "decals": [("left", STORY + "graffiti_unplug.png", 0.0, 0.62, 1.1), ("right", STORY + "graffiti_not_data.png", 0.0, 0.62, 1.1),
                        ("front", STORY + "stencil_eye_crossed.png", 0.0, 0.95, 0.30), ("rear", STORY + "graffiti_lying.png", 0.0, 0.50, 0.9)]},
        ],
    },
}

RIMS = {
    "steel_silver": {"base_color": [0.55, 0.56, 0.58], "metallic": 0.9, "roughness": 0.38, "coat": 0.6, "coat_roughness": 0.10},
    "steel_white": {"base_color": [0.78, 0.79, 0.80], "metallic": 0.0, "roughness": 0.45, "coat": 0.5, "coat_roughness": 0.12},
    "gold": {"base_color": [0.55, 0.40, 0.14], "metallic": 1.0, "roughness": 0.28, "coat": 1.0, "coat_roughness": 0.04, "flake": 0.1},
    "aero_white": {"base_color": [0.86, 0.88, 0.89], "metallic": 0.1, "roughness": 0.30, "coat": 1.0, "coat_roughness": 0.03},
    "gunmetal": {"base_color": [0.13, 0.13, 0.14], "metallic": 0.85, "roughness": 0.3, "coat": 1.0, "coat_roughness": 0.05, "flake": 0.08},
}
