"""Stand-in traffic fleet from the hero car (headless Blender 5.2), until the fleet workstream lands.

    blender -b --factory-startup --python tools/godot/make_traffic_standins.py

Needs assets/car/src/car_model.blend and the car's Pigment textures in scenes/car/textures/
(car_body__security, car_body__cab, car_wheel: tools/car/car_textures.py).  Writes, per livery,
into game/assets/traffic/standin/:

    <livery>_lod1.glb   the car's LOD1 (~10k tris, 1024 body texture): same contract as car.glb
                        (Body, Wheel_FL/FR/RL/RR, Collider, Headlight_*/Taillight_* empties)
    <livery>_lod2.glb   one merged mesh "Body" (body + wheels, decimated to ~1.5k tris, 512 px)
                        + Collider + lamp empties: for cars far away and parked cars

and game/assets/traffic/standin/index.json in the fleet index format (docs/agents/traffic/NOTES.md).
The security LOD0 stays game/assets/car/car.glb (the hero car).
"""
import json
import os
import shutil
import sys
import tempfile

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "car"))
OUT = os.path.join(ROOT, "game", "assets", "traffic", "standin")
SRC = os.path.join(ROOT, "assets", "car", "src")
TEX = os.path.join(ROOT, "scenes", "car", "textures")
LOD2_TRIS = 1500


def load_export_car():
    src = os.path.join(ROOT, "tools", "car", "export_car.py")
    ns = {"__name__": "export_car_lib", "__file__": src}
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns


def tris(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)


def one_livery(E, livery):
    bpy.ops.wm.open_mainfile(filepath=os.path.join(SRC, "car_model.blend"))
    import blender_pigment as BP
    sc = bpy.context.scene
    lod = {o.name[:-5]: o for o in sc.objects if o.name.endswith("_LOD1")}
    body = lod["Body"]
    wheels = [o for k, o in lod.items() if k.startswith("Wheel_")]
    mb = BP.apply_pigment_material(body, os.path.join(TEX, f"car_body__{livery}"), "car_body", flake=False)
    mw = BP.apply_pigment_material(wheels[0], os.path.join(TEX, "car_wheel"), "car_wheel", flake=False)
    E["use_material"](wheels, mw)
    for m in (mb, mw):
        E["finish_material"](m)
    for o in list(lod.values()):
        for k in ("pigment_source", "pigment_folder"):
            if k in o.keys():
                del o[k]
    tmp = tempfile.mkdtemp(prefix="traffic_glb_")
    lamps = [sc.objects[n] for n in ("Headlight_L", "Headlight_R", "Taillight_L", "Taillight_R")]
    col = sc.objects["Collider"]
    # LOD1 with LOD0 node names
    for k, o in lod.items():
        if k in sc.objects:
            sc.objects[k].name = k + "_LOD0"
        o.name = k
    E["resize_images"](mb, 1024, tmp)
    E["resize_images"](mw, 512, tmp)
    lod1_objs = [o for k, o in lod.items() if not k.startswith("Caliper_")]
    E["export"](os.path.join(OUT, f"{livery}_lod1.glb"), lod1_objs + [col] + lamps)
    # LOD2: body + wheels merged and decimated; wheel material slot kept (2 surfaces, 1 draw each)
    bpy.ops.object.select_all(action="DESELECT")
    copies = []
    for o in [body] + wheels:
        c = o.copy()
        c.data = o.data.copy()
        sc.collection.objects.link(c)
        copies.append(c)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.join()
    merged = bpy.context.view_layer.objects.active
    t0 = tris(merged)
    mod = merged.modifiers.new("dec", "DECIMATE")
    mod.ratio = min(1.0, LOD2_TRIS / max(1, t0))
    bpy.ops.object.modifier_apply(modifier=mod.name)
    print(f"[standins] {livery} lod2: {t0} -> {tris(merged)} tris")
    for k in ("Body",):
        if k in sc.objects:
            sc.objects[k].name = k + "_LOD1x"
    merged.name = "Body"
    E["resize_images"](mb, 512, tmp)
    E["resize_images"](mw, 256, tmp)
    E["export"](os.path.join(OUT, f"{livery}_lod2.glb"), [merged, col] + lamps)
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    E = load_export_car()
    for livery in ("security", "cab"):
        if os.path.isdir(os.path.join(TEX, f"car_body__{livery}")):
            one_livery(E, livery)
        else:
            print("[standins] no textures for", livery)
    index = {
        "format": "vehicle-index/1",
        "note": "stand-in fleet made from the hero car by tools/godot/make_traffic_standins.py; "
                "the fleet workstream's assets/vehicles/index.json replaces it (tools/godot/sync_vehicles.py)",
        "vehicles": [
            {"name": "kanzaki_tsubame_cab", "class": "sedan", "spawn_weight": 1.0,
             "spec": "res://assets/car/car.json",
             "lods": [{"file": "cab_lod1.glb", "max_distance": 40.0}, {"file": "cab_lod2.glb", "max_distance": 600.0}],
             "variants": [
                 {"name": "cab", "weight": 2.0},
                 {"name": "midnight", "weight": 1.0, "tint": [0.35, 0.4, 0.55]},
                 {"name": "rust", "weight": 1.0, "tint": [0.85, 0.45, 0.3]},
                 {"name": "jade", "weight": 1.0, "tint": [0.4, 0.8, 0.6]},
                 {"name": "violet", "weight": 1.0, "tint": [0.7, 0.45, 0.9]},
                 {"name": "graphite", "weight": 1.0, "tint": [0.5, 0.5, 0.52]}]},
            {"name": "kanzaki_tsubame_security", "class": "security", "spawn_weight": 0.0, "patrol": True,
             "spec": "res://assets/car/car.json", "lightbar": True,
             "lods": [{"file": "res://assets/car/car.glb", "max_distance": 14.0},
                      {"file": "security_lod1.glb", "max_distance": 45.0},
                      {"file": "security_lod2.glb", "max_distance": 600.0}],
             "variants": [{"name": "security", "weight": 1.0}]},
        ],
    }
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    print("[standins] done ->", OUT)


main()
