"""Generate the smart models (city/models/<kind>/<name>.toml) from the existing pipeline.

    python -m tools.city discover [--refresh]

Reads the town kit scripts, tools/town_textures.py's jobs and their committed Pigment scripts,
the props catalog and index, the fleet index, the road and world-sheet scripts, the decal
generators, the sky bakes, tools/world/world_config.json, scenes/world/world.json and the
Godot layout, and writes one manifest per asset.

Existing manifests are kept: only the fields listed in `[model] derived` (facts read from
the pipeline: counts, variants, decals, world keys...) are refreshed with --refresh. Every
other field is yours to edit.
"""
import collections
import glob
import importlib.util
import json
import os
import sys
from pathlib import Path

from . import manifest as M
from . import paths, pigscript

ROOT = paths.ROOT


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(path).parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


def _json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


class Facts:
    """Everything discovery reads once."""

    def __init__(self):
        self.world = _json(ROOT / "scenes/world/world.json", {}) or {}
        self.layout = _json(paths.WORLD_EXPORT / "world_layout.json", {}) or {}
        self.town_layout = _json(ROOT / "game/assets/town/town_layout.json", {}) or {}
        self.props_index = _json(ROOT / "assets/props/index.json", {}) or {}
        self.vehicles_index = _json(ROOT / "assets/vehicles/index.json", {}) or {}
        self.counts = collections.defaultdict(collections.Counter)
        for i in self.world.get("instances", []):
            self.counts[i["asset"]][i.get("district", "misc")] += 1
        self.variant_counts = collections.Counter((i["asset"], i.get("variant")) for i in self.world.get("instances", []))
        self.meshes = self.layout.get("meshes", {})

    def world_keys(self, prefix_exact, prefix_variants):
        return sorted(k for k in self.meshes if k == prefix_exact or k.startswith(prefix_variants))

    def placement(self, asset):
        c = self.counts.get(asset, {})
        return {"instances": sum(c.values()), "districts": dict(sorted(c.items()))}


def _policy(info, n):
    """town_loader.gd's _policy() (the perf workstream's streaming rules), predicted in Python."""
    cat, tris = info.get("cat", "other"), int(info.get("tris", 0))
    if cat in ("terrain", "water", "bridge", "wire"):
        return "single"
    if cat == "building" and tris > 3000:
        return "heavy"
    if cat in ("road", "decal", "wall", "rail", "stairs") and n == 1:
        return "merge"
    if tris <= 3000 and cat not in ("other", "sign", "lamp", "pole"):
        return "merge" if n <= 6 else "region"
    return "cell"


def game_section(F, keys, extra=None):
    g = {}
    if keys:
        info = F.meshes[keys[0]]
        n = sum(1 for i in F.layout.get("instances", []) if i["mesh"] in keys) if F.layout else 0
        g = {"category": info.get("cat", "other"), "collision": info.get("col", "none"), "tris": int(info.get("tris", 0)),
             "policy": _policy(info, n), "proxy": _policy(info, n) == "heavy", "world_keys": keys}
        vis = {"sign": 220.0, "decal": 150.0, "lamp": 260.0, "pole": 260.0, "rail": 170.0, "wire": 200.0, "footing": 260.0,
               "other": 150.0}.get(g["category"])
        if vis:
            g["visible_to_m"] = vis
    g.update(extra or {})
    return g


def pigment_section(scripts, textures_root=None, patch=None):
    scans = [pigscript.scan(ROOT / s) for s in scripts if (ROOT / s).is_file()]
    pig = {"scripts": list(scripts)}
    if textures_root:
        pig["textures"] = textures_root
    var, slots, decals, outs, ins, res = [], {}, set(), set(), set(), None
    for sc in scans:
        var += [v for v in sc["variants"] if v not in var]
        for k, v in sc["decal_slots"].items():
            slots.setdefault(k, set()).update(v)
        decals |= set(sc["decals"])
        outs |= set(sc["outputs"])
        ins |= set(sc["inputs"])
        res = res or sc["resolution"]
    if res:
        pig["resolution"] = res
    pig["variants"] = var
    pig["decals"] = sorted(decals)
    pig["decal_slots"] = {k: sorted(v) for k, v in sorted(slots.items())}
    pig["outputs"] = sorted(outs)
    pig["patch"] = patch or []
    return pig


# ---------------------------------------------------------------- kinds
KIT_KIND = {"building_a": "building", "building_b": "building", "building_c": "building", "street_segment": "road_set",
            "crossroad": "road_set", "street_lamp": "prop", "power_pole": "prop", "overhead_sign": "prop", "fence": "prop"}
KIT_TITLES = {
    "building_a": "Narrow six-storey walk-up (8 x 10 m, 21 m), ground-floor shop",
    "building_b": "Four-bay shophouse block (16 x 12 m)",
    "building_c": "Corporate tower (building_c), crown billboards",
    "street_segment": "Legacy 20 m street segment (town map)",
    "crossroad": "Legacy crossroad piece (town map; junctions are generated now)",
    "street_lamp": "Street lamp", "power_pole": "Power pole with five wires",
    "overhead_sign": "Overhead shop sign (ten shops)", "fence": "Chain-link fence panel (3 x 2 m)",
}


def kit_models(F):
    out = []
    tt = ROOT / "tools/town_textures.py"
    for asset, kind in KIT_KIND.items():
        gen = ROOT / f"assets/blender/town/{asset}.py"
        if gen.is_file():
            mesh = {"runner": "blender", "generator": f"assets/blender/town/{asset}.py", "args": [f"assets/town/{asset}.glb"],
                    "outputs": [f"assets/town/{asset}.glb"], "deps": ["assets/blender/town/_kit.py"], "params": {}}
        elif asset == "fence":
            mesh = {"runner": "blender", "generator": "tools/make_fence.py", "args": [], "outputs": ["assets/town/fence.glb"],
                    "deps": [], "params": {}}
        else:
            mesh = {"runner": "file", "source": f"assets/town/{asset}.glb", "outputs": [f"assets/town/{asset}.glb"]}
        script = f"scenes/town/scripts/{asset}.jsonl"
        keys = F.world_keys(asset, asset + "__")
        doc = {
            "model": {"name": asset, "kind": kind, "title": KIT_TITLES.get(asset, asset), "family": "town kit",
                      "derived": ["pigment.variants", "pigment.decals", "pigment.decal_slots", "pigment.outputs",
                                  "pigment.resolution", "game", "placement.instances", "placement.districts"]},
            "mesh": mesh,
            "recipe": {"runner": "town_textures", "tool": "tools/town_textures.py", "job": asset, "outputs": [script]},
            "pigment": pigment_section([script], "scenes/town/textures"),
            "game": game_section(F, keys),
            "placement": dict(F.placement(asset), source="tools/world/placement.py",
                              rules="kit frontage rows + back rows per district (world_config.json districts[].kit); "
                                    "a random Pigment variant per instance, never the same as the previous one"
                              if kind == "building" else "street furniture along roads (world_config.json props)"),
        }
        if asset in ("building_a", "building_b", "building_c", "overhead_sign"):
            doc["placement"]["variant_counts"] = dict(sorted((v, c) for (a, v), c in F.variant_counts.items() if a == asset and v))
        out.append(doc)
    return out


def prop_models(F):
    cat = _load_module(ROOT / "tools/props/catalog.py", "props_catalog")
    idx = F.props_index.get("props", {})
    out = []
    for name in cat.names():
        info = cat.PROPS[name]
        ix = idx.get(name, {})
        script = f"scenes/props/scripts/{name}.jsonl"
        lod1 = bool(info.get("lod1"))
        exp_out = [f"assets/props/{name}.glb", f"assets/props/src/{name}_export.json"] + ([f"assets/props/{name}_lod1.glb"] if lod1 else [])
        keys = F.world_keys("PROP_" + name, "PROP_" + name + "__")
        game = game_section(F, keys, {
            "collider": (ix.get("collider") or {}).get("type", "box"),
            "lod": ix.get("lod", {}), "mount": ix.get("mount", "ground"),
            "lights": [{"name": l["name"], "type": l.get("type", "omni"), "color": l.get("color"), "energy": l.get("energy"),
                        "range": l.get("range")} for l in ix.get("lights", [])],
            "alpha": (ix.get("material") or {}).get("alpha", ["OPAQUE"]),
        })
        if not keys:
            game.setdefault("category", info.get("category", "prop"))
        doc = {
            "model": {"name": name, "kind": "prop", "title": info.get("title", name), "family": "street props kit",
                      "category": info.get("category", ""), "description": info.get("desc", ""),
                      "derived": ["pigment.variants", "pigment.decals", "pigment.decal_slots", "pigment.outputs",
                                  "pigment.resolution", "game", "placement.instances", "placement.districts", "placement.scatter"]},
            "mesh": {"runner": "blender", "generator": "tools/props/build_props.py", "args": [name],
                     "outputs": [f"assets/props/src/{name}.glb", f"assets/props/src/{name}.json"],
                     "deps": ["tools/props/proplib.py", "tools/props/models_street.py", "tools/props/models_clutter.py",
                              "tools/props/catalog.py"],
                     "params": {}},
            "recipe": {"runner": "python", "tool": "tools/props/props_textures.py", "args": [name, "--no-run"],
                       "outputs": [script], "mutable": ["scenes/props/textures/variants.json"]},
            "pigment": pigment_section([script], "scenes/props/textures"),
            "export": {"runner": "blender", "tool": "tools/props/export_props.py", "args": [name, "--no-index"],
                       "outputs": exp_out, "embed": info.get("embed"), "lod1_ratio": info.get("lod1") or 0.0},
            "game": game,
            "placement": dict(F.placement(name), source="tools/props/scatter.py (rules: tools/props/catalog.py)",
                              scatter=ix.get("scatter", info.get("scatter", {}))),
        }
        out.append(doc)
    return out


def vehicle_models(F):
    out = []
    for v in F.vehicles_index.get("vehicles", []):
        vid = v["id"]
        scripts = [f"scenes/vehicles/{vid}/scripts/{vid}_body.jsonl", f"scenes/vehicles/{vid}/scripts/{vid}_wheel.jsonl"]
        src = f"assets/vehicles/{vid}/src"
        outs = [f"assets/vehicles/{vid}/{vid}.glb", f"assets/vehicles/{vid}/{vid}_lod1.glb", f"assets/vehicles/{vid}/{vid}_lod2.glb",
                f"assets/vehicles/{vid}/{vid}.json"]
        if vid == "tsubame":
            outs += ["assets/car/car.glb", "assets/car/car_lod1.glb", "assets/car/car.json"]
        out.append({
            "model": {"name": vid, "kind": "vehicle", "title": v.get("name", vid), "family": "fleet",
                      "derived": ["pigment.variants", "pigment.decals", "pigment.decal_slots", "pigment.outputs",
                                  "pigment.resolution", "game"]},
            "mesh": {"runner": "blender", "generator": "tools/vehicles/build.py", "args": [vid],
                     "outputs": [f"{src}/{vid}_body.glb", f"{src}/{vid}_wheel.glb", f"{src}/{vid}_parts.json", f"{src}/{vid}_info.json",
                                 f"{src}/{vid}_model.blend"],
                     "deps": ["tools/vehicles/vkit", f"tools/vehicles/specs/{vid}.py", "tools/vehicles/fleet.py"], "params": {}},
            "recipe": {"runner": "python", "tool": "tools/vehicles/textures.py", "args": [vid, "--no-run"], "outputs": scripts,
                       "deps": ["tools/vehicles/fleet.py"]},
            "pigment": pigment_section(scripts, f"scenes/vehicles/{vid}/textures"),
            "export": {"runner": "blender", "tool": "tools/vehicles/export.py", "args": [vid], "outputs": outs,
                       "mutable": ["assets/vehicles/index.json"]},
            "game": {"category": "vehicle", "collision": "convex", "class": v.get("class", ""),
                     "spawn_weight": v.get("spawn_weight", 0.0), "player": bool(v.get("player", False)),
                     "lod": {k: v[k] for k in ("lod_distances", "triangles") if k in v},
                     "variants": [x["name"] for x in v.get("variants", [])],
                     "lights": ["Headlight_L", "Headlight_R", "Taillight_L", "Taillight_R"]},
            "placement": {"source": "game/scripts/traffic (spawn by spawn_weight, then variant weight)"},
        })
    return out


def road_models(F):
    scripts = sorted(paths.rel(p) for p in glob.glob(str(ROOT / "scenes/town/scripts/roads/*.jsonl")))
    imgs = sorted({m["image"] for m in F.layout.get("materials", {}).values() if m.get("type") == "image" and
                   any(x in m["image"] for x in ("asphalt", "trim", "paving", "concrete", "atlas", "setts"))})
    return [{
        "model": {"name": "roads", "kind": "road_set", "title": "Open-world road materials: seamless tiles, trim sheet, decal atlas",
                  "family": "roads", "derived": ["pigment.variants", "pigment.decals", "pigment.decal_slots", "pigment.outputs",
                                                 "pigment.resolution", "game.images"]},
        "recipe": {"runner": "python", "tool": "tools/road_textures.py", "args": [],
                   "outputs": scripts + ["assets/decals/roads"]},
        "pigment": pigment_section(scripts, "scenes/town/textures/roads"),
        "game": {"category": "road", "collision": "trimesh", "images": imgs,
                 "note": "road meshes are world pieces (tools/town_roads.py build_run); these are their materials"},
        "placement": {"source": "tools/world/network.py + world_gen.py (road classes in world_config.json)"},
    }]


def tile_models(F):
    scripts = sorted(paths.rel(p) for p in glob.glob(str(ROOT / "scenes/town/scripts/world/*.jsonl")))
    imgs = sorted({m["image"] for m in F.layout.get("materials", {}).values() if m.get("type") == "image" and
                   any(x in m["image"] for x in ("facade", "grass", "rock", "dirt", "sand", "corrugated"))})
    return [{
        "model": {"name": "world_sheets", "kind": "tile_set", "title": "World sheets: terrain tiles, tower facades, corrugated metal",
                  "family": "world", "derived": ["pigment.variants", "pigment.decals", "pigment.decal_slots", "pigment.outputs",
                                                 "pigment.resolution", "game.images"]},
        "recipe": {"runner": "town_textures_world", "tool": "tools/town_textures.py", "job": "world", "outputs": scripts},
        "pigment": pigment_section(scripts, "scenes/town/textures/world"),
        "game": {"category": "material", "images": imgs},
    }]


DECAL_SETS = {
    "story": ("tools/make_story_decals.py", "assets/decals/story", "Story decals: Hoshikawa, MERIDIAN, Dreamlink, Noctis, UNPLUG"),
    "props": ("tools/props/make_prop_decals.py", "assets/decals/props", "Street-prop decals: screens, ads, stickers, menus"),
    "fleet": ("tools/vehicles/decals.py", "assets/decals/fleet", "Fleet liveries, plates, badges, tyre sidewalls"),
}


def decal_models(F, all_models):
    out = []
    for name, (gen, d, title) in DECAL_SETS.items():
        users = collections.defaultdict(list)
        for m in all_models:
            for img in m.get("pigment", {}).get("decals", []):
                if img.startswith(d + "/"):
                    users[Path(img).stem].append(f"{m['model']['kind']}/{m['model']['name']}")
        images = sorted(Path(p).stem for p in glob.glob(str(ROOT / d / "*.png")))
        game_imgs = sorted(m["image"] for m in F.layout.get("materials", {}).values()
                           if m.get("type") == "image" and Path(m["image"]).stem in images)
        out.append({
            "model": {"name": name, "kind": "decal_set", "title": title, "family": "decals",
                      "derived": ["decals.images", "decals.used_by", "game.images"]},
            "decals": {"runner": "python", "generator": gen, "args": [], "outputs": [d], "images": images,
                       "used_by": {k: sorted(v) for k, v in sorted(users.items())}},
            "game": {"category": "decal", "images": game_imgs,
                     "note": "images listed here are also used directly by world materials (tower crown billboards)"} if game_imgs else
                    {"category": "decal"},
        })
    return out


def sky_models(F):
    out = []
    for p in sorted(glob.glob(str(ROOT / "assets/sky/*_2k.hdr"))):
        preset = Path(p).name[:-len("_2k.hdr")]
        out.append({
            "model": {"name": preset, "kind": "sky", "title": f"Night sky preset {preset}", "family": "sky", "derived": []},
            "mesh": {"runner": "blender", "generator": "tools/sky/make_sky.py",
                     "args": ["--presets", preset, "--no-preview"],
                     "outputs": [f"assets/sky/{preset}_2k.hdr", f"game/sky/{preset}_2k.hdr", f"game/sky/sky_{preset}.tres"],
                     "mutable": ["game/sky/sky_presets.json", "game/sky/sky_night.tscn"], "deps": [], "params": {}},
            "game": {"category": "sky", "godot": f"game/sky/sky_{preset}.tres", "light_hints": "city_sky.gd picks the largest imported HDR"},
        })
    return out


def world_models(F):
    cfg = _json(ROOT / "tools/world/world_config.json", {})
    w = F.world
    out = [{
        "model": {"name": cfg.get("name", "world"), "kind": "world", "title": "The open world: 4 x 4 km bay, four islands",
                  "family": "world", "derived": ["world.metrics", "world.chunks"]},
        "world": {"config": "tools/world/world_config.json", "seed": int(cfg.get("seed", 2077)), "out": "scenes/world",
                  "export_dir": "game/assets/world", "chunk_m": cfg.get("chunk_m", 256),
                  "chunks": len((w.get("terrain") or {}).get("chunks", [])),
                  "metrics": {k: v for k, v in (w.get("metrics") or {}).items() if isinstance(v, (int, float, str))}},
        "config": {},
        "game": {"layout": "game/assets/world/world_layout.json", "loader": "game/scripts/town_loader.gd",
                 "policies": "cell / heavy (+ far proxies) / region / merge / single, see docs/agents/perf/NOTES.md"},
    }]
    out.append({
        "model": {"name": "shinkai_bay_terrain", "kind": "terrain", "title": "Terrain: islands, mountains, erosion",
                  "family": "world", "derived": ["terrain.islands", "terrain.chunks"]},
        "terrain": {"world": "world/" + cfg.get("name", "world"), "section": "terrain",
                    "islands": [i["name"] for i in cfg.get("islands", [])],
                    "chunks": len((w.get("terrain") or {}).get("chunks", [])),
                    "settings": cfg.get("terrain", {})},
        "config": {},
        "game": {"category": "terrain", "collision": "heightmap", "lod_cells_m": (cfg.get("terrain") or {}).get("lod_cells_m", [])},
    })
    for d in cfg.get("districts", []):
        dd = next((x for x in w.get("districts", []) if x["name"] == d["name"]), {})
        out.append({
            "model": {"name": d["name"], "kind": "district", "title": f"District {d['name']} ({d.get('style', '')})",
                      "family": "world", "derived": ["district.counts", "district.settings"]},
            "district": {"world": "world/" + cfg.get("name", "world"), "island": d.get("island", ""),
                         "settings": d, "counts": dd.get("counts", {})},
            "config": {},
        })
    return out


# ---------------------------------------------------------------- write
def discover(refresh=False, log=print) -> list[dict]:
    F = Facts()
    models = kit_models(F) + prop_models(F) + vehicle_models(F) + road_models(F) + tile_models(F) + sky_models(F) + world_models(F)
    models += decal_models(F, models)
    written = kept = updated = 0
    for doc in models:
        path = M.path_for(doc["model"]["kind"], doc["model"]["name"])
        if path.is_file():
            if not refresh:
                kept += 1
                continue
            old = M.load(path)
            doc = M.refresh(old, doc)
            M.save(doc, path)
            updated += 1
        else:
            M.save(doc, path)
            written += 1
    log(f"discover: {len(models)} models ({written} new, {updated} refreshed, {kept} kept) in {paths.rel(paths.MODELS)}")
    return models
