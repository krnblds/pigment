"""Cycles shots of the ground at the camera spots from tools/world/ground_masks.py
(scenes/world/ground_spots.json, the same views as the game's --bench-spots),
in a saved world region, with the new terrain material or the old one.

    blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,save --region x0,y0,x1,y1
    blender -b --factory-startup scenes/world/world_preview.blend --python docs/agents/ground/cycles_shots.py -- \
        --out docs/agents/ground/cycles --spots ground_forest,ground_beach [--legacy] [--samples 96] [--res 1280x720] [--wet 0.6]

Daylight: a Nishita sky with a 35 degree sun, so the ground's forms read.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools", "world"))


def opt(k, d=None):
    return A[A.index(k) + 1] if k in A else d


import ground_material as GM  # noqa: E402
import world_meshes as WM  # noqa: E402
import world_render as WR  # noqa: E402

legacy = "--legacy" in A
mat = WM.terrain_material_legacy(ROOT) if legacy else GM.terrain_material(ROOT, wet=float(opt("--wet", 0.0)))
for ob in bpy.data.objects:
    if ob.type == "MESH" and (ob.name.startswith("Terrain_") or ob.name == "SeaFloor"):
        ob.data.materials.clear()
        ob.data.materials.append(mat)
res = tuple(int(v) for v in opt("--res", "1280x720").split("x"))
WR.setup(int(opt("--samples", 96)), res)
sc = bpy.context.scene
# daylight
w = bpy.data.worlds.get("GroundSky") or bpy.data.worlds.new("GroundSky")
w.use_nodes = True
nt = w.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputWorld")
bg = nt.nodes.new("ShaderNodeBackground")
sk = nt.nodes.new("ShaderNodeTexSky")
for t in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
    try:
        sk.sky_type = t
        break
    except TypeError:
        continue
try:
    sk.sun_elevation = math.radians(35)
    sk.sun_rotation = math.radians(150)
    sk.sun_intensity = 0.6
except AttributeError:
    pass
nt.links.new(sk.outputs[0], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.35
nt.links.new(bg.outputs[0], out.inputs["Surface"])
sc.world = w
moon = bpy.data.objects.get("Moon")
if moon:
    moon.data.energy = 3.2
    moon.data.color = (1.0, 0.95, 0.88)
    moon.rotation_euler = (math.radians(55), 0, math.radians(150 + 90))
sc.view_settings.exposure = float(opt("--exposure", -0.3))
cam = bpy.data.objects.get("GroundCam") or bpy.data.objects.new("GroundCam", bpy.data.cameras.new("GroundCam"))
if cam.name not in sc.collection.objects:
    sc.collection.objects.link(cam)
sc.camera = cam
spots = json.load(open(os.path.join(ROOT, "scenes", "world", "ground_spots.json")))
want = opt("--spots", "").split(",") if opt("--spots") else [s["name"] for s in spots]
outdir = os.path.join(ROOT, opt("--out", "docs/agents/ground/cycles"))
os.makedirs(outdir, exist_ok=True)
for s in spots:
    if s["name"] not in want:
        continue
    # side light: the sun comes in from the left of the view, so the ground's relief reads
    d = Vector(s["at"]) - Vector(s["eye"])
    yaw = math.atan2(d.y, d.x)
    if moon:
        moon.rotation_euler = (math.radians(58), 0, yaw + math.radians(100))
    cam.location = Vector(s["eye"])
    cam.rotation_euler = (Vector(s["at"]) - Vector(s["eye"])).to_track_quat("-Z", "Y").to_euler()
    cam.data.sensor_fit = "VERTICAL"
    cam.data.angle = math.radians(s.get("fov", 55.0))
    cam.data.clip_end = 20000
    sc.render.filepath = os.path.join(outdir, f"{s['name']}{'_before' if legacy else ''}.png")
    bpy.ops.render.render(write_still=True)
    print("rendered", sc.render.filepath, flush=True)
