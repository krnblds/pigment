"""Godot export of the built world (Blender 5.2, headless).

Uses tools/godot/export_town.py's export_layout(): every object of the
"World" collection becomes an instance of a mesh glb (shared mesh data ->
one glb: kit buildings, towers per archetype, containers, cranes, trees,
lamps...; unique pieces: terrain chunks, road runs, junctions, decals,
bridges, sea walls). Writes into --export-dir (default game/assets/world/):

    meshes/*.glb          one per mesh key (glTF, Y up)
    world_layout.json     the town_layout.json format the game already loads
                          (meshes, materials, instances, lights, roads, spawn)
    world.json            the data contract (lane graph, junctions, signals,
                          bridges, instances by asset, terrain chunks) - copied
    heightfield.f32       the terrain height grid (see world.json "terrain")
    terrain_lod/          terrain chunk LODs at 8 m and 32 m cells (glb)
"""
import json
import os
import shutil
import time

import bpy

import world_meshes as WM


def export(world, built, out, root, dest, log):
    t0 = time.time()
    os.makedirs(dest, exist_ok=True)
    ns = {"__name__": "export_town", "__file__": os.path.join(root, "tools", "godot", "export_town.py")}
    src = ns["__file__"]
    sys_argv_backup = list(__import__("sys").argv)
    __import__("sys").argv = [a for a in sys_argv_backup if a not in ("--out",)]
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    __import__("sys").argv = sys_argv_backup
    gpos = ns["gpos"]
    roads = [[gpos(p) for p in r["points"]] for r in world["roads"]]
    juncs = [{"name": j["id"], "pos": gpos(j["pos"])} for j in world["junctions"] if j["kind"] not in ("transition",)]
    sp = world.get("spawn")
    spawn = {"pos": gpos(sp["pos"]), "dir": gpos((sp["dir"][0], sp["dir"][1], 0.0))} if sp else None
    # lights are exported from the scene's light objects (World_Lights)
    # tools/city: $CITY_EXPORT_HOOK names a script whose make_writer() skips unchanged glbs (incremental export)
    hook = {}
    if os.environ.get("CITY_EXPORT_HOOK"):
        exec(compile(open(os.environ["CITY_EXPORT_HOOK"], encoding="utf-8").read(), os.environ["CITY_EXPORT_HOOK"], "exec"), hook)
    writer = hook["make_writer"](dest, ns, log) if hook else None
    layout = ns["export_layout"](bpy.data.collections["World"], dest, roads, juncs, spawn,
                                 {"world": world["name"], "buildings": sum(1 for i in world["instances"] if i.get("kind") == "building")},
                                 t0, name="world_layout.json", write_mesh=writer)
    # terrain LODs (8 m and 32 m cells) per chunk
    T = world["terrain"]
    H = built["H"]
    per = T["chunk_cells"]
    lod_dir = os.path.join(dest, "terrain_lod")
    os.makedirs(lod_dir, exist_ok=True)
    tmat = bpy.data.materials.get("WorldTerrain")
    n_lod = 0
    for ch in T["chunks"]:
        for cell_m in T["lod_cells_m"][1:]:
            step = int(round(cell_m / T["cell_m"]))
            me = WM.terrain_chunk(f"Terrain_{ch['id']}_lod{cell_m:g}", H, T["origin"][0], T["cell_m"], ch["ix"] * per, ch["iy"] * per, per, step)
            if tmat:
                me.materials.append(tmat)
            lod_path = os.path.join(lod_dir, f"{ch['id']}_{cell_m:g}m.glb")
            if writer:
                writer(f"terrain_lod/{ch['id']}_{cell_m:g}m", me, lod_path)
            else:
                ns["export_mesh"](me, lod_path)
            bpy.data.meshes.remove(me)
            n_lod += 1
    for fn in ("world.json", T["heightfield"], "masks_urban.npy"):
        p = os.path.join(out, fn)
        if os.path.isfile(p):
            shutil.copyfile(p, os.path.join(dest, fn))
    if hook.get("finish"):
        hook["finish"]()
    log(f"export: {len(layout['meshes'])} meshes, {len(layout['instances'])} instances, {n_lod} terrain LOD chunks -> {dest} ({time.time() - t0:.0f} s)")
    if "--pack" in __import__("sys").argv:
        ns["pack"](dest)
