"""Export the world's *shared* mesh glbs for one source asset, without building the world
(headless Blender 5.2).

    blender -b --factory-startup --python tools/city/blender/world_assets.py -- \
        --kind kit|prop --asset building_a --keys building_a__soba,building_a__fixers --out game/assets/world/meshes

The world export (tools/world/world_export.py) writes one glb per mesh key. The keys made from
a town-kit or props-kit asset are copies of that asset's mesh with a material name:

    kit   KIT_<asset> (import_kit(): glb import, join, transforms applied), one copy per Pigment
          variant with material Pigment_<asset>__<variant>  -> <asset>__<variant>.glb
          (Pigment_<asset> for an asset used without variants -> <asset>.glb)
    prop  PROP_<name> (world_build.import_prop(): the glb's meshes except Collider, joined,
          transforms applied), its own material                 -> PROP_<name>.glb

This script rebuilds exactly those meshes the same way and writes them with the same
export_town.export_mesh(), so changing a building or a prop re-exports its few glbs in
seconds instead of rebuilding the 4 km world. It prints one JSON line per key:
    CITY_KEY {"key", "file", "tris", "aabb"}
"""
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1]
    return default


def export_town_ns():
    src = os.path.join(ROOT, "tools", "godot", "export_town.py")
    ns = {"__name__": "export_town", "__file__": src}
    argv = list(sys.argv)
    sys.argv = [a for a in argv if a != "--out"]
    try:
        exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    finally:
        sys.argv = argv
    return ns


def import_joined(path, skip_prefix=None):
    """glb -> one mesh object: join the meshes, clear parents, apply transforms (import_kit / import_prop)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and not (skip_prefix and o.name.startswith(skip_prefix))]
    if not meshes:
        raise SystemExit(f"no mesh in {path}")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    me = obj.data
    names = set()
    for o in new:
        try:
            names.add(o.name)
        except ReferenceError:
            pass
    for nm in names:
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o)
    return me


def material(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    return m


def main():
    kind, asset = opt("--kind"), opt("--asset")
    keys = [k for k in str(opt("--keys", "")).split(",") if k]
    out = os.path.abspath(opt("--out", os.path.join(ROOT, "game", "assets", "world", "meshes")))
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ns = export_town_ns()
    if kind == "kit":
        base = import_joined(os.path.join(ROOT, "assets", "town", asset + ".glb"))
        base.name = "KIT_" + asset
    elif kind == "prop":
        base = import_joined(os.path.join(ROOT, "assets", "props", asset + ".glb"), skip_prefix="Collider")
        base.name = "PROP_" + asset
    else:
        raise SystemExit("--kind kit|prop")
    for key in keys:
        if kind == "kit":
            var = key.split("__", 1)[1] if "__" in key else None
            me = base.copy()
            me.name = f"{base.name}__{var}" if var else base.name + "_x"
            mname = f"Pigment_{asset}__{var}" if var else f"Pigment_{asset}"
            if len(me.materials):
                me.materials[0] = material(mname)
            else:
                me.materials.append(material(mname))
        else:
            me = base
        path = os.path.join(out, key + ".glb")
        ns["export_mesh"](me, path)
        lo = [min(v.co[i] for v in me.vertices) for i in range(3)]
        hi = [max(v.co[i] for v in me.vertices) for i in range(3)]
        g0, g1 = ns["gpos"](lo), ns["gpos"](hi)
        aabb = [[min(a, b) for a, b in zip(g0, g1)], [max(a, b) for a, b in zip(g0, g1)]]
        tris = sum(len(p.vertices) - 2 for p in me.polygons)
        print("CITY_KEY " + json.dumps({"key": key, "file": "meshes/" + key + ".glb", "tris": tris, "aabb": aabb}), flush=True)


main()
