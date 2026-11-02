"""Citizen recipes: who walks the streets of the rain city (pure Python, imported by build_citizens.py).

A recipe is a plain dict: MPFB phenotype, skin, hair, base clothes (MakeHuman CC0 assets), an optional
procedural outer layer ("shell": jacket / bomber / hoodie / coat / raincoat / hivis) with colours and trim,
accessories, and gameplay tags (umbrella, walk speed, idle style).  Asset names are candidate lists: the
first one MPFB can find is used (packs missing -> system assets), so the build never fails on a missing pack.

    make_recipes(seed, n) -> [recipe]   (deterministic)
    WAKERS                            -> the two Hoshikawa "Waker" player characters
"""
import random

# MPFB system skins: <age>_<race>_<sex>
AGES = ["young", "middleage", "old"]

# --- wardrobe (MakeHuman CC0 asset names; first available wins)
TOPS_M = ["elvs_crude_t-shirt_male", "namuhekam_male_polo_shirt", "toigo_basic_tucked_t-shirt", "toigo_fisherman_sweater"]
TOPS_F = ["joepal_crude_t-shirt_female", "toigo_turtleneck_halter_top", "toigo_basic_tucked_t-shirt", "toigo_fisherman_sweater",
          "toigo_camisole_top"]
PANTS = ["cortu_cargo_pants", "toigo_wool_pants", "toigo_harem_pants"]
SUITS_M = ["male_casualsuit01", "male_casualsuit02", "male_casualsuit03", "male_casualsuit04", "male_casualsuit05", "male_casualsuit06"]
SUITS_F = ["female_casualsuit01", "female_sportsuit01"]
FORMAL_M = ["male_elegantsuit01"]
FORMAL_F = ["female_elegantsuit01"]
WORK = ["male_worksuit01"]
SHOES_SMART = ["shoes04", "shoes01"]
SHOES_SNEAK = ["shoes05", "shoes06", "shoes02"]
SHOES_BOOT = ["shoes03"]
HAIR_M = ["short02", "short03", "short04", "short01"]
HAIR_F = ["bob01", "bob02", "ponytail01", "long01", "braid01", "short01"]
HAIR_ANY = ["afro01"]

# dark wet-night palette + a few neon / hi-vis accents (linear-ish sRGB 0-1)
DARKS = [(0.05, 0.055, 0.07), (0.09, 0.09, 0.1), (0.07, 0.09, 0.14), (0.12, 0.1, 0.08), (0.1, 0.12, 0.09), (0.16, 0.06, 0.07),
         (0.2, 0.19, 0.17), (0.14, 0.15, 0.17), (0.03, 0.03, 0.035)]
MIDS = [(0.35, 0.3, 0.22), (0.26, 0.3, 0.33), (0.4, 0.38, 0.35), (0.22, 0.26, 0.2), (0.34, 0.2, 0.18), (0.5, 0.45, 0.38)]
BRIGHTS = [(0.85, 0.62, 0.08), (0.05, 0.55, 0.6), (0.72, 0.1, 0.32), (0.85, 0.85, 0.82), (0.2, 0.35, 0.75), (0.9, 0.35, 0.05)]
NEON = [(0.0, 0.9, 1.0), (1.0, 0.1, 0.6), (0.6, 1.0, 0.1), (1.0, 0.55, 0.0), (0.55, 0.3, 1.0)]

# archetype -> weights and build
ARCHETYPES = {
    "salaryman": 5, "street": 6, "techwear": 5, "worker": 3, "elder": 3, "student": 4, "nightlife": 4, "courier": 2,
}


def _skin(rng, sex, agev, race):
    a = "young" if agev < 0.6 else ("middleage" if agev < 0.8 else "old")
    r = max(race, key=race.get)
    name = f"{a}_{r}_{sex}"
    if name == "young_caucasian_female" and rng.random() < 0.5:
        name = "young_caucasian_female2"
    return [name, f"young_{r}_{sex}"]


def _race(rng):
    k = rng.random()
    # a Japanese harbour city: mostly east-asian, mixed
    if k < 0.62:
        return {"asian": 0.85, "caucasian": 0.1, "african": 0.05}
    if k < 0.75:
        return {"asian": 0.45, "caucasian": 0.45, "african": 0.1}
    if k < 0.88:
        return {"asian": 0.1, "caucasian": 0.8, "african": 0.1}
    return {"asian": 0.1, "caucasian": 0.1, "african": 0.8}


def _shell(kind, rng, colour=None, trim=None, trim_glow=0.0, length=None):
    return {"kind": kind, "colour": colour or rng.choice(DARKS), "trim": trim, "trim_glow": trim_glow,
            "length": length, "sheen": {"coat": 0.35, "raincoat": 0.15, "jacket": 0.3, "bomber": 0.5}.get(kind, 0.75)}


def make_recipe(i, rng):
    sex = "female" if rng.random() < 0.48 else "male"
    arch = rng.choices(list(ARCHETYPES), list(ARCHETYPES.values()))[0]
    agev = {"elder": rng.uniform(0.84, 0.98), "student": rng.uniform(0.44, 0.52)}.get(arch, rng.uniform(0.48, 0.82))
    race = _race(rng)
    r = {
        "id": "citizen_%02d" % i, "sex": sex, "archetype": arch,
        "phenotype": {"gender": 1.0 if sex == "male" else 0.0, "age": round(agev, 3),
                      "muscle": round(rng.uniform(0.3, 0.75), 3), "weight": round(rng.uniform(0.3, 0.8 if arch != "elder" else 0.7), 3),
                      "height": round(rng.uniform(0.45, 0.78) if sex == "male" else rng.uniform(0.35, 0.65), 3), "proportions": round(rng.uniform(0.4, 0.8), 3),
                      "cupsize": round(rng.uniform(0.3, 0.6), 3), "firmness": 0.5, "race": race},
        "skin": _skin(rng, sex, agev, race),
        "hair": [], "clothes": [], "shell": None, "accessories": [], "tints": {},
        "umbrella": None, "walk_speed": round(rng.uniform(1.15, 1.5), 2), "idle": "Idle",
    }
    hair_pool = HAIR_M if sex == "male" else HAIR_F
    if rng.random() < 0.08:
        hair_pool = HAIR_ANY + hair_pool
    r["hair"] = [rng.choice(hair_pool)] + hair_pool
    if arch == "elder" and sex == "male" and rng.random() < 0.4:
        r["hair"] = ["short04", "short01"]
    tops = TOPS_M if sex == "male" else TOPS_F
    suits = SUITS_M if sex == "male" else SUITS_F
    if arch == "salaryman":
        r["clothes"] = [(FORMAL_M if sex == "male" else FORMAL_F) + suits, SHOES_SMART]
        r["shell"] = _shell("coat", rng, rng.choice(DARKS + MIDS[:3]), length=rng.uniform(0.55, 0.85))
        r["umbrella"] = rng.choice(["clear", "black", "black", None])
        r["walk_speed"] = round(rng.uniform(1.35, 1.6), 2)
    elif arch == "street":
        r["clothes"] = [suits, rng.choice([SHOES_SNEAK, SHOES_BOOT])]
        r["shell"] = _shell(rng.choice(["hoodie", "jacket", "bomber"]), rng, rng.choice(DARKS + BRIGHTS[:2]),
                            trim=rng.choice([None, rng.choice(NEON)]), trim_glow=0.6)
        r["accessories"] = ["cap"] if rng.random() < 0.35 else []
        r["umbrella"] = rng.choice([None, None, "clear", "neon"])
    elif arch == "techwear":
        r["clothes"] = [[rng.choice(tops)] + tops, PANTS[:1] + PANTS, SHOES_BOOT + SHOES_SNEAK]
        r["shell"] = _shell(rng.choice(["jacket", "coat", "hoodie"]), rng, rng.choice(DARKS[:4] + [DARKS[-1]]),
                            trim=rng.choice(NEON), trim_glow=1.0, length=rng.uniform(0.35, 0.6))
        r["accessories"] = ["mask"] if rng.random() < 0.6 else []
        r["umbrella"] = rng.choice([None, "neon", "black"])
    elif arch == "worker":
        r["clothes"] = [WORK + suits, SHOES_BOOT]
        r["shell"] = _shell("hivis", rng, rng.choice([(0.95, 0.5, 0.02), (0.75, 0.85, 0.05), (0.08, 0.1, 0.16)]),
                            trim=(0.85, 0.88, 0.9), trim_glow=0.0)
        r["accessories"] = ["cap"] if rng.random() < 0.5 else []
        r["idle"] = rng.choice(["Idle", "Idle_FoldArms"])
    elif arch == "elder":
        r["clothes"] = [[rng.choice(tops)] + tops, ["toigo_wool_pants"] + PANTS, SHOES_SMART]
        r["shell"] = _shell("coat", rng, rng.choice(MIDS + DARKS[:3]), length=rng.uniform(0.6, 0.9))
        r["accessories"] = ["hat"] if rng.random() < 0.5 else []
        r["umbrella"] = rng.choice(["black", "clear", None])
        r["walk_speed"] = round(rng.uniform(0.85, 1.1), 2)
    elif arch == "student":
        r["clothes"] = [suits, SHOES_SNEAK]
        r["shell"] = _shell(rng.choice(["bomber", "hoodie", "raincoat"]), rng, rng.choice(BRIGHTS + DARKS[:3]),
                            trim=rng.choice([None, (0.9, 0.9, 0.9)]))
        r["umbrella"] = rng.choice([None, "clear", "neon"])
        r["walk_speed"] = round(rng.uniform(1.3, 1.55), 2)
    elif arch == "nightlife":
        r["clothes"] = [[rng.choice(tops)] + tops, PANTS + suits, SHOES_BOOT + SHOES_SMART]
        r["shell"] = _shell(rng.choice(["coat", "jacket"]), rng, rng.choice([(0.25, 0.02, 0.06), (0.02, 0.02, 0.025), (0.5, 0.48, 0.5),
                                                                          (0.05, 0.12, 0.2)]),
                            trim=rng.choice([None, rng.choice(NEON)]), trim_glow=0.8, length=rng.uniform(0.45, 0.9))
        r["shell"]["sheen"] = 0.18                                            # vinyl
        r["accessories"] = ["glasses"] if rng.random() < 0.4 else []
        r["idle"] = rng.choice(["Idle", "Idle_TalkingPhone", "Idle_FoldArms"])
    else:  # courier
        r["clothes"] = [suits, SHOES_SNEAK]
        r["shell"] = _shell("raincoat", rng, rng.choice([(0.85, 0.62, 0.08), (0.05, 0.45, 0.5), (0.9, 0.35, 0.05)]),
                            trim=(0.85, 0.88, 0.9))
        r["walk_speed"] = round(rng.uniform(1.45, 1.7), 2)
    # trousers / jeans: mostly dark, some mid
    r["tints"] = {"base": {"value": round(rng.uniform(0.35, 0.8), 2), "sat": round(rng.uniform(0.3, 0.9), 2),
                           "hue": round(rng.uniform(-0.05, 0.05), 3)},
                  "hair": {"value": round(rng.uniform(0.25, 0.9) if arch != "elder" else rng.uniform(1.2, 1.7), 2)}}
    if arch in ("street", "techwear", "nightlife") and rng.random() < 0.18:
        r["tints"]["hair_dye"] = list(rng.choice(NEON))                    # dyed tips, it's the future
    return r


def make_recipes(seed=2077, n=32):
    rng = random.Random(seed)
    out = [make_recipe(i, rng) for i in range(n)]
    # make sure the crowd has both sexes, every archetype and enough umbrellas for a rainy night
    have = {r["archetype"] for r in out}
    for k, arch in enumerate(a for a in ARCHETYPES if a not in have):
        rr = random.Random(seed * 31 + k)
        while True:
            c = make_recipe(n - 1 - k, rr)
            if c["archetype"] == arch:
                out[n - 1 - k] = c
                break
    return out


WAKER_COAT = {"kind": "coat", "colour": (0.035, 0.04, 0.05), "trim": (0.1, 0.85, 1.0), "trim_glow": 0.55, "length": 0.75,
              "sheen": 0.32, "waker": True}
WAKERS = [
    {"id": "waker_m", "sex": "male", "archetype": "waker",
     "phenotype": {"gender": 1.0, "age": 0.55, "muscle": 0.65, "weight": 0.5, "height": 0.62, "proportions": 0.7,
                   "cupsize": 0.5, "firmness": 0.5, "race": {"asian": 0.8, "caucasian": 0.15, "african": 0.05}},
     "skin": ["young_asian_male"], "hair": ["short02", "short03"],
     "clothes": [["elvs_crude_t-shirt_male", "toigo_basic_tucked_t-shirt", "male_casualsuit06"], ["cortu_cargo_pants", "toigo_wool_pants"], SHOES_BOOT],
     "shell": dict(WAKER_COAT), "accessories": ["resonance_band"],
     "tints": {"base": {"value": 0.3, "sat": 0.2, "hue": 0.0}, "hair": {"value": 0.3}}, "umbrella": None, "walk_speed": 1.45, "idle": "Idle"},
    {"id": "waker_f", "sex": "female", "archetype": "waker",
     "phenotype": {"gender": 0.0, "age": 0.52, "muscle": 0.6, "weight": 0.45, "height": 0.6, "proportions": 0.7,
                   "cupsize": 0.45, "firmness": 0.5, "race": {"asian": 0.75, "caucasian": 0.2, "african": 0.05}},
     "skin": ["young_asian_female"], "hair": ["ponytail01", "bob02", "bob01"],
     "clothes": [["toigo_turtleneck_halter_top", "joepal_crude_t-shirt_female", "female_sportsuit01"], ["cortu_cargo_pants", "toigo_wool_pants"], SHOES_BOOT],
     "shell": dict(WAKER_COAT), "accessories": ["resonance_band"],
     "tints": {"base": {"value": 0.3, "sat": 0.2, "hue": 0.0}, "hair": {"value": 0.28}}, "umbrella": None, "walk_speed": 1.45, "idle": "Idle"},
]
