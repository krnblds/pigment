"""How every street prop breaks, for the game's destructible world (system Python, no deps).

    python tools/props/damage_table.py      ->  game/data/damage/props.json   (committed)

Reads assets/props/index.json (category, size, collider shapes, lights) and the props' source
records assets/props/src/<name>.json (pieces with groups and boxes), adds the behaviour per prop, and
writes one table that scripts/damage/destructibles.gd loads. The two town-kit meshes that aren't
props (street_lamp, power_pole) are described by hand at the bottom.

Behaviours (kind):
  snap     a pole / post: a static collider until hit; above `threshold` (impulse, N s, roughly the
           car's mass x its closing speed) it shears off at the base and falls as a rigid body.
           A lamp head goes dark with a spark burst and a flicker.
  burst    the fire hydrant: snaps like a pole, then a water jet runs from the stub.
  topple   bolted-down heavy boxes (vending machine, kiosks): a static collider until the impulse
           passes `threshold`, then they tip over; glass / screens shatter from `glass_threshold`.
  shelter  the bus stop: stays put (static collider), its glass panes shatter from `glass_threshold`.
  knock    loose things (cones, bags, bins, boxes, crates, pallets, bikes, scooters, benches,
           planters, carts, plastic barriers): no collider until a car is about to touch them, then
           a rigid body of `mass` that the car shoves away. `chunks` split it into separate bodies
           (bags, boxes in a stack).
  heavy    jersey barriers: a heavy rigid body (1.8 t) that barely moves.
  bend     guard rails: a static collider; above `threshold` the section breaks loose.
  none     out of reach (rooftop / wall props, cables, trees, decals): not destructible.

Other fields: mass (kg), material (metal / plastic / glass / wood / concrete / cardboard / bag: sounds
and particles), collider (from the index, prop space), bounds, glass ([{center, size}] panes),
head (where a lamp's light sits: sparks, flicker, the streamed light it kills), spill ("cans"),
chunks ([{center, size}] boxes: a triangle goes to the chunk its centroid falls in, else the nearest).
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "game", "data", "damage", "props.json")

# name: (kind, mass kg, threshold N s, material, extra)
RULES = {
    "traffic_light_pole": ("snap", 160, 14000, "metal", {}),
    "traffic_light_mast": ("snap", 420, 20000, "metal", {}),
    "ped_signal": ("snap", 70, 7000, "metal", {}),
    "street_name_sign": ("snap", 35, 4500, "metal", {}),
    "bollard": ("snap", 45, 8000, "metal", {}),
    "parking_meter": ("snap", 40, 4000, "metal", {}),
    "cctv_pole": ("snap", 130, 11000, "metal", {}),
    "drone_mast": ("snap", 260, 16000, "metal", {}),
    "holo_pylon": ("snap", 90, 6000, "metal", {"glass_groups": ["holo"]}),
    "fire_hydrant": ("burst", 85, 5500, "metal", {}),
    "vending_machine": ("topple", 260, 7000, "metal", {"glass_groups": ["glass"], "glass_threshold": 2500, "spill": "cans"}),
    "data_kiosk": ("topple", 300, 12000, "metal", {"glass_groups": ["screen"], "glass_threshold": 2500}),
    "phone_kiosk": ("topple", 180, 9000, "metal", {"glass_groups": ["screen", "ad"], "glass_threshold": 2000}),
    "bus_stop": ("shelter", 0, 0, "glass", {"glass_groups": ["glass"], "glass_threshold": 2500}),
    "traffic_cone": ("knock", 3.5, 0, "plastic", {}),
    "trash_bag_pile": ("knock", 7, 0, "bag", {"chunk_rule": r"^bag_(\d)"}),
    "trash_bin": ("knock", 16, 0, "plastic", {}),
    "cardboard_boxes": ("knock", 4, 0, "cardboard", {"chunk_rule": r"_([abc])(?:_\d)?$"}),
    "pallet": ("knock", 22, 0, "wood", {}),
    "crate_stack": ("knock", 14, 0, "wood", {"chunk_rule": r"(?:_([ab])(?:_\d)?$)|^(pcrate)"}),
    "bicycle": ("knock", 14, 0, "metal", {}),
    "scooter": ("knock", 75, 0, "metal", {}),
    "bench": ("knock", 55, 0, "metal", {}),
    "planter": ("knock", 260, 0, "concrete", {}),
    "ramen_cart": ("knock", 140, 0, "wood", {}),
    "skewer_stall": ("knock", 110, 0, "wood", {}),
    "crash_barrier": ("knock", 110, 0, "plastic", {}),
    "jersey_barrier": ("heavy", 1800, 0, "concrete", {}),
    "guard_rail": ("bend", 120, 18000, "metal", {}),
}
NONE = ["steam_vent", "neon_arrow_sign", "cable_bundle", "ac_unit", "satellite_dish", "water_tank",
        "puddle_decal", "street_tree", "palm_tree"]


def piece_box(p):
    return {"center": [round(x, 4) for x in p["center"]], "size": [round(x, 4) for x in p["size"]]}


def union(boxes):
    lo = [min(b["center"][i] - b["size"][i] / 2 for b in boxes) for i in range(3)]
    hi = [max(b["center"][i] + b["size"][i] / 2 for b in boxes) for i in range(3)]
    return {"center": [round((lo[i] + hi[i]) / 2, 4) for i in range(3)], "size": [round(hi[i] - lo[i], 4) for i in range(3)]}


def main():
    idx = json.load(open(os.path.join(ROOT, "assets", "props", "index.json")))
    out = {"format": "prop-damage", "version": 1,
           "doc": "tools/props/damage_table.py (behaviours in its header); keys are prop names; layout mesh keys "
                  "PROP_<name>[__<variant>] map to <name>",
           "props": {}}
    for name, e in idx["props"].items():
        if name in NONE or name not in RULES:
            out["props"][name] = {"kind": "none"}
            continue
        kind, mass, thr, mat, extra = RULES[name]
        d = {"kind": kind, "mass": mass, "material": mat, "category": e.get("category"),
             "collider": e.get("collider", {}).get("shapes", []), "bounds": e.get("bounds"), "size": e.get("size_m")}
        if thr:
            d["threshold"] = thr
        src = os.path.join(ROOT, "assets", "props", "src", f"{name}.json")
        pieces = json.load(open(src))["pieces"] if os.path.exists(src) else []
        if extra.get("glass_groups"):
            d["glass"] = [piece_box(p) for p in pieces if p["group"] in extra["glass_groups"]]
            d["glass_threshold"] = extra.get("glass_threshold", 2500)
        if extra.get("spill"):
            d["spill"] = extra["spill"]
        if extra.get("chunk_rule"):
            groups = {}
            for p in pieces:
                m = re.search(extra["chunk_rule"], p["piece"])
                if m:
                    k = next(g for g in m.groups() if g)
                    groups.setdefault(k, []).append(piece_box(p))
            d["chunks"] = [union(v) for _k, v in sorted(groups.items())]
        lights = e.get("lights") or []
        if lights and kind in ("snap", "topple", "burst"):
            top = max(lights, key=lambda l: l["pos"][1])
            d["head"] = [round(x, 3) for x in top["pos"]]
        out["props"][name] = d
    # town-kit meshes (not props): the street lamp and the wooden power pole
    out["props"]["street_lamp"] = {
        "kind": "snap", "mass": 150, "threshold": 10000, "material": "metal", "category": "kit",
        "collider": [{"type": "cylinder", "center": [0, 3.0, 0], "radius": 0.12, "height": 6.0},
                     {"type": "box", "center": [0, 5.95, 1.1], "size": [0.2, 0.18, 2.3]}],
        "bounds": {"min": [-0.21, 0.0, -0.21], "max": [0.21, 6.18, 2.33]},
        "head": [0.0, 5.8, 2.1], "loader_collision": True,
        "note": "street_lamp.glb from the town kit; its light is the world's Light_lamp at (0, 5.8, 2.1)"}
    out["props"]["power_pole"] = {
        "kind": "snap", "mass": 420, "threshold": 24000, "material": "wood", "category": "kit",
        "collider": [{"type": "cylinder", "center": [0, 4.5, 0], "radius": 0.16, "height": 9.0},
                     {"type": "box", "center": [0, 8.6, 0.0], "size": [2.6, 0.2, 0.2]}],
        "bounds": {"min": [-1.3, 0.0, -0.26], "max": [1.3, 9.1, 1.18]}, "loader_collision": True}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    kinds = {}
    for n, d in out["props"].items():
        kinds.setdefault(d["kind"], []).append(n)
    for k, v in sorted(kinds.items()):
        print(f"{k:8s} {len(v):2d}  {', '.join(sorted(v))}")
    print("->", os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
