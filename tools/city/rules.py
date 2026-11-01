"""Compile smart models into the build graph.

Per model (by section):
    [mesh]     mesh:<name>        generator -> mesh files                  (pool blender)
    [recipe]   recipe:<name>      script writer -> Pigment script(s)        (pool pigment: lists parts)
    [pigment]  pigment:<name>[/<script>]  pigment-mcp --script -> texture sets, project (pool pigment)
    [export]   export:<name>      textured game export (props, vehicles)   (pool blender)
    [decals]   decals:<name>      decal generator -> PNGs
    game.world_keys of kit / props assets:
               world.mesh:<name>  that asset's world glbs, without rebuilding the world (pool blender)
Global:
    world:build         world gen + build + incremental export (fingerprinted glbs)  (pool blender)
    godot.tex:<folder>  one Pigment texture set -> Godot albedo / orm / normal / emission
    godot.images:world  image materials (road tiles, world sheets, billboards) -> game/assets/world/images
    props:index         assets/props/index.json + variant swaps
    godot.sync:vehicles, godot.sync:car    copies into game/
    sky:<preset>        sky bakes
    godot.import        headless re-import (Godot only re-imports what changed)
    verify:*            gates (city verify)
"""
import json
import os
from pathlib import Path

from . import actions as A
from . import graph as G
from . import manifest as M
from . import paths

ROOT = paths.ROOT
WORLD_DIR = "game/assets/world"
TEX_ROOTS = ["scenes/town/textures", "scenes/props/textures"]


def _json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _script_node_id(name, script, n_scripts):
    stem = Path(script).stem
    return f"pigment:{name}" if n_scripts == 1 else f"pigment:{name}/{stem}"


def build_graph(models: dict | None = None) -> G.Graph:
    models = models if models is not None else M.load_all()
    g = G.Graph()
    layout = _json(paths.WORLD_EXPORT / "world_layout.json", {}) or {}
    town_layout = _json(ROOT / "game/assets/town/town_layout.json", {}) or {}
    shared_keys = {}            # world mesh key -> model id
    tools_city = []        # the action code itself is keyed per node (actions.impl), not per file

    for mid, doc in models.items():
        m = doc["model"]
        name, kind = m["name"], m["kind"]
        mesh = doc.get("mesh")
        # ---------------------------------------------------------- mesh
        if mesh and mesh.get("runner", "file") != "file":
            g.add(G.Node(id=f"sky:{name}" if kind == "sky" else f"mesh:{name}", kind="mesh." + mesh["runner"], model=mid,
                         title=f"{name}: geometry",
                         tools=[mesh["generator"]] + mesh.get("deps", []) + tools_city,
                         inputs=mesh.get("inputs", []), outputs=mesh.get("outputs", []), mutable=mesh.get("mutable", []),
                         params={"args": mesh.get("args", []), "params": mesh.get("params", {})},
                         pool="blender" if mesh["runner"] == "blender" else "cpu", run=A.run_generator(mesh)))
        # ---------------------------------------------------------- recipe (script writer)
        rec = doc.get("recipe")
        pig = doc.get("pigment") or {}
        scripts = pig.get("scripts", [])
        mesh_inputs = []
        for s in scripts:
            if (ROOT / s).is_file():
                from . import pigscript
                mesh_inputs += [i for i in pigscript.scan(ROOT / s)["inputs"] if i.endswith((".glb", ".gltf", ".obj"))]
        if rec:
            tool = rec.get("tool")
            g.add(G.Node(id=f"recipe:{name}", kind="recipe." + rec["runner"], model=mid, title=f"{name}: write Pigment script",
                         tools=[tool, "tools/city/recipe.py"] + rec.get("deps", []) + tools_city if tool else rec.get("deps", []),
                         inputs=sorted(set(mesh_inputs) | set(rec.get("inputs", []))), outputs=rec.get("outputs", []),
                         mutable=rec.get("mutable", []), params={"job": rec.get("job"), "args": rec.get("args", []), "env": rec.get("env", {})},
                         pool="pigment", run=A.run_recipe(rec)))
        # ---------------------------------------------------------- pigment runs
        for s in scripts:
            nid = _script_node_id(name, s, len(scripts))
            g.add(A.pigment_node(nid, mid, s, pig))
        # ---------------------------------------------------------- textured export
        ex = doc.get("export")
        if ex:
            ins = list(ex.get("inputs", []))
            if mesh:
                ins += [o for o in mesh.get("outputs", []) if not o.endswith(".blend")]
                ins += [o for o in mesh.get("outputs", []) if o.endswith(".blend")]
            ins += pig.get("outputs", [])
            g.add(G.Node(id=f"export:{name}", kind="export." + ex["runner"], model=mid, title=f"{name}: game export",
                         tools=[ex["tool"]] + ex.get("deps", []) + tools_city, inputs=sorted(set(ins)),
                         outputs=ex.get("outputs", []), mutable=ex.get("mutable", []), params={"args": ex.get("args", [])},
                         pool="blender", run=A.run_tool(ex)))
        # ---------------------------------------------------------- decal sets
        dec = doc.get("decals")
        if dec:
            g.add(G.Node(id=f"decals:{name}", kind="decals." + dec.get("runner", "python"), model=mid,
                         title=f"{name}: decal images", tools=[dec["generator"]] + tools_city,
                         mutable=dec.get("outputs", []), params={"args": dec.get("args", [])},
                         pool="cpu", cache=False, run=A.run_generator(dict(dec, runner=dec.get("runner", "python")))))
        # ---------------------------------------------------------- world glbs of kit / props assets
        keys = (doc.get("game") or {}).get("world_keys", [])
        if keys and kind in ("building", "prop", "road_set"):
            if (ROOT / f"assets/town/{name}.glb").is_file() and not keys[0].startswith("PROP_"):
                src, akind = f"assets/town/{name}.glb", "kit"
            elif (ROOT / f"assets/props/{name}.glb").is_file():
                src, akind = f"assets/props/{name}.glb", "prop"
            else:
                src = None
            if src:
                for k in keys:
                    shared_keys[k] = mid
                g.add(G.Node(id=f"world.mesh:{name}", kind="world.mesh", model=mid, title=f"{name}: world glbs",
                             tools=["tools/city/blender/world_assets.py", "tools/godot/export_town.py"] + tools_city,
                             inputs=[src], outputs=[f"{WORLD_DIR}/meshes/{k}.glb" for k in keys],
                             mutable=[f"{WORLD_DIR}/world_layout.json"],
                             params={"kind": akind, "asset": name, "keys": keys}, pool="blender",
                             run=A.run_world_mesh(akind, name, keys)))
        # ---------------------------------------------------------- sky (mesh runner is the bake)
    # -------------------------------------------------------------- world build
    world = next((d for d in models.values() if d["model"]["kind"] == "world"), None)
    if world:
        overrides = {}
        for d in models.values():
            if d["model"]["kind"] in ("world", "terrain") and d.get("config"):
                overrides = M.deep_merge(overrides, d["config"])
        for d in models.values():
            if d["model"]["kind"] == "district" and d.get("config"):
                overrides = M.deep_merge(overrides, {"districts": [dict(d["config"], name=d["model"]["name"])]})
        w = world["world"]
        unique = sorted(k for k in layout.get("meshes", {}) if k not in shared_keys)
        outs = ["scenes/world/world.json", "scenes/world/heightfield.f32", "scenes/world/masks_urban.npy",
                f"{WORLD_DIR}/world.json", f"{WORLD_DIR}/heightfield.f32", f"{WORLD_DIR}/terrain_lod"]
        outs += [f"{WORLD_DIR}/meshes/{k}.glb" for k in unique]
        g.add(G.Node(id="world:build", kind="world.build", model=M.model_id(world),
                     title="world: generate, build, export changed glbs",
                     tools=["tools/world/terrain.py", "tools/world/network.py", "tools/world/world_gen.py",
                            "tools/world/placement.py", "tools/world/world_build.py", "tools/world/world_meshes.py",
                            "tools/world/world_export.py", "tools/world/world_driver.py", "tools/godot/export_town.py",
                            "tools/blender_town.py", "tools/town_roads.py", "tools/town_layout_driver.py",
                            "tools/props/scatter.py", "tools/city/blender/export_hook.py",
                            "tools/city/blender/glb_writer.py"] + tools_city,
                     inputs=[w.get("config", "tools/world/world_config.json"), "assets/props/index.json::placement"],
                     outputs=outs, mutable=[f"{WORLD_DIR}/world_layout.json", f"{WORLD_DIR}/images", f"{WORLD_DIR}/masks_urban.npy"],
                     params={"seed": w.get("seed"), "config": w.get("config"), "overrides": overrides,
                             "shared_keys": sorted(shared_keys)},
                     pool="blender", run=A.run_world_build(w, overrides, sorted(shared_keys))))
        g.add(G.Node(id="verify:world", kind="verify.world", model=M.model_id(world), title="world verify (Blender)",
                     tools=["tools/world/world_verify.py"], inputs=["scenes/world/world.json"], pool="blender",
                     always=True, cache=False, run=A.run_world_verify()))
        g.add(G.Node(id="verify:roads", kind="verify.roads", model=M.model_id(world),
                     title="road obstacle scan (world.json)", tools=["tools/city/verify.py"],
                     inputs=["scenes/world/world.json", "assets/props/index.json::placement"], always=True, cache=False,
                     run=A.run_road_scan()))
    # -------------------------------------------------------------- Godot textures (one node per texture set)
    folders = {}
    for mapname, lay in (("world", layout), ("town", town_layout)):
        for mat in (lay.get("materials") or {}).values():
            if mat.get("type") == "pigment":
                folders.setdefault(mat["folder"], {"name": mat["name"], "maps": set()})["maps"].add(mapname)
    for folder, info in sorted(folders.items()):
        src = next((f"{r}/{folder}" for r in TEX_ROOTS if (ROOT / r / folder).is_dir()), f"scenes/town/textures/{folder}")
        outs = [f"game/assets/{mp}/textures/{folder}" for mp in sorted(info["maps"])]
        g.add(G.Node(id=f"godot.tex:{folder}", kind="godot.tex", model="", title=f"pack {folder} for Godot",
                     tools=["tools/godot/pack_textures.py"] + tools_city, inputs=[src], outputs=outs,
                     mutable=[f"game/assets/{mp}/{mp}_layout.json" for mp in sorted(info["maps"])],
                     params={"name": info["name"], "maps": sorted(info["maps"])}, pool="cpu",
                     run=A.run_pack(src, folder, info["name"], sorted(info["maps"]))))
    # -------------------------------------------------------------- Godot image materials
    imgs = A.image_sources(layout)
    if imgs:
        g.add(G.Node(id="godot.images:world", kind="godot.images", model="", title="world image materials",
                     tools=tools_city, inputs=sorted(set(imgs.values())),
                     outputs=[f"{WORLD_DIR}/{k}" for k in sorted(imgs)], params={"map": sorted(imgs.items())},
                     pool="cpu", run=A.run_images(imgs)))
    # -------------------------------------------------------------- props index, syncs, import
    if any(d["model"]["kind"] == "prop" and d.get("export") for d in models.values()):
        g.add(G.Node(id="props:index", kind="props.index", title="assets/props/index.json + variant swaps",
                     tools=["tools/props/write_index.py", "tools/props/catalog.py"] + tools_city,
                     inputs=["assets/props/src/*.json", "scenes/props/textures/variants.json", "scenes/props/textures/*__*"],
                     outputs=["assets/props/index.json", "assets/props/variants"], pool="cpu",
                     run=A.run_tool({"runner": "python", "tool": "tools/props/write_index.py", "args": []})))
    g.add(G.Node(id="godot.sync:vehicles", kind="godot.sync", title="vehicles + props glbs -> game/",
                 tools=["tools/godot/sync_vehicles.py"] + tools_city,
                 inputs=["assets/vehicles/index.json", "assets/vehicles/*/*.glb", "assets/vehicles/*/*.json",
                         "assets/props/*.glb", "assets/props/index.json"],
                 mutable=["game/assets/vehicles", "game/assets/props"], pool="cpu", cache=False,
                 run=A.run_tool({"runner": "python", "tool": "tools/godot/sync_vehicles.py", "args": []})))
    g.add(G.Node(id="godot.sync:car", kind="godot.sync", title="hero car -> game/assets/car",
                 tools=["tools/godot/sync_car.py"] + tools_city, inputs=["assets/car/car.glb", "assets/car/car.json"],
                 outputs=["game/assets/car/car.glb", "game/assets/car/car.json"], pool="cpu",
                 run=A.run_tool({"runner": "python", "tool": "tools/godot/sync_car.py", "args": []})))
    g.add(G.Node(id="godot.import", kind="godot.import", title="Godot headless re-import",
                 tools=tools_city, inputs=["game/assets", "game/sky"], pool="godot", cache=False, rekey=True,
                 run=A.run_godot_import()))
    # -------------------------------------------------------------- MCP script checks (gate)
    scripts = sorted({s for d in models.values() for s in (d.get("pigment") or {}).get("scripts", [])})
    g.add(G.Node(id="verify:scripts", kind="verify.scripts", title="pigment-mcp --check every Pigment script",
                 tools=tools_city, inputs=scripts, always=True, cache=False, pool="cpu", run=A.run_script_check(scripts)))
    g.add(G.Node(id="verify:decals", kind="verify.decals", title="decal audit (tools/decal_audit.py, when present)",
                 tools=tools_city, inputs=["tools/decal_audit.py"], always=True, cache=False, pool="cpu",
                 run=A.run_decal_audit()))
    for nd in g.nodes.values():
        if getattr(nd.run, "impl", None):
            nd.params["_impl"] = nd.run.impl
    return g.link()


def default_targets(g: G.Graph) -> set:
    """What `city build` with no target builds: everything except the gates."""
    return {n for n, nd in g.nodes.items() if not n.startswith("verify:")}
