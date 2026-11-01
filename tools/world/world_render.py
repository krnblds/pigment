"""Proof shots of the world (Cycles). Cameras are derived from world.json, so
they follow the generated layout.

    aerial    dusk overview from over the bay: city, expressway, bridges, mountains
    bridge    the cable-stayed bay bridge at night from near the water
    mountain  on the switchback road, looking down at the city
    avenue    street level on a downtown avenue at night
    top       orthographic map-like view (debug), --day for flat daylight
"""
import math
import os

import bpy
import numpy as np
from mathutils import Vector


def setup(samples, res, cpu=False):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    sc.cycles.device = "CPU"
    for dev in (() if cpu else ("OPTIX", "CUDA")):
        try:
            prefs.compute_device_type = dev
            prefs.get_devices()
            if any(d.type == dev for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == dev
                sc.cycles.device = "GPU"
                break
        except TypeError:
            continue
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    sc.cycles.light_sampling_threshold = 0.01
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.compression = 90
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    sc.view_settings.exposure = 0.0
    # Thousands of instanced buildings with emissive windows: light-sampling
    # every emissive triangle would put ~10^8 triangles in the light tree.
    # Windows still glow when seen; the street is lit by the point lights.
    for m in bpy.data.materials:
        try:
            m.cycles.emission_sampling = "NONE"
        except (AttributeError, TypeError):
            pass


def sky(kind, fog=0.0):
    """kind: night | dusk | day."""
    sc = bpy.context.scene
    w = bpy.data.worlds.get("WorldSky") or bpy.data.worlds.new("WorldSky")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    moon = bpy.data.objects.get("Moon")
    if kind == "night":
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[0].color = (0.05, 0.035, 0.06, 1)       # city glow at the horizon
        ramp.color_ramp.elements[1].position = 0.75
        ramp.color_ramp.elements[1].color = (0.006, 0.008, 0.02, 1)
        nt.links.new(sep.outputs[2], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 1.0
        if moon:
            moon.data.energy = 0.08
    elif kind == "dusk":
        sk = nt.nodes.new("ShaderNodeTexSky")
        for t in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
            try:
                sk.sky_type = t
                break
            except TypeError:
                continue
        try:
            sk.sun_elevation = math.radians(-1.5)
            sk.sun_rotation = math.radians(290)
            sk.altitude = 50.0
            sk.air_density = 1.4
            sk.dust_density = 2.5
        except AttributeError:
            pass
        nt.links.new(sk.outputs[0], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.6
        if moon:
            moon.data.energy = 0.25
            moon.data.color = (1.0, 0.55, 0.4)
            moon.rotation_euler = (math.radians(89), 0, math.radians(200))
    else:
        bg.inputs["Color"].default_value = (0.5, 0.58, 0.7, 1)
        bg.inputs["Strength"].default_value = 1.0
        if moon:
            moon.data.energy = 3.0
            moon.data.color = (1, 1, 1)
            moon.rotation_euler = (math.radians(40), 0, math.radians(30))
    if fog > 0:
        vol = nt.nodes.new("ShaderNodeVolumePrincipled")
        vol.inputs["Density"].default_value = fog
        vol.inputs["Color"].default_value = (0.6, 0.62, 0.75, 1)
        nt.links.new(vol.outputs[0], out.inputs["Volume"])
    sc.world = w


def aim(cam, loc, target, lens):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    cam.data.clip_end = 20000


def shots(world, built):
    out = {}
    roads = {r["id"]: r for r in world["roads"]}
    # aerial: from over the bay south-east of the city, looking at downtown and the mountains
    out["aerial"] = {"loc": (1450, -1650, 620), "target": (-350, 250, 60), "lens": 26, "sky": "dusk", "exposure": 0.6}
    # bridge: the cable-stayed bridge's first pylon, seen from the water
    cs = [b for b in world["bridges"] if b["type"] == "cable_stayed" and b["pylons"]]
    if cs:
        b = cs[0]
        p0, p1 = Vector(b["pylons"][0]["pos"]), Vector(b["pylons"][-1]["pos"])
        mid = (p0 + p1) / 2
        along = (p1 - p0).normalized()
        side = Vector((-along.y, along.x))
        cam = mid + side * 330 - along * 260
        out["bridge"] = {"loc": (cam.x, cam.y, 9.0), "target": (mid.x, mid.y, 38.0), "lens": 24, "sky": "night", "exposure": 1.0}
    # mountain: on the summit road, ~75% of the way up, looking at the city
    mr = [r for r in world["roads"] if r["class"] == "mountain"]
    if mr:
        r = max(mr, key=lambda r: r["length"])
        pts = r["points"]
        best = None
        for k in range(len(pts) // 2, len(pts) - 5):
            p = Vector(pts[k])
            if best is None or p.z > best.z - 0 and k > len(pts) * 0.7:
                best = p
                break
        p = Vector(pts[int(len(pts) * 0.72)])
        q = Vector(pts[int(len(pts) * 0.72) + 3])
        t = (q - p).to_2d().normalized()
        side = Vector((-t.y, t.x))
        cam = p.to_2d() + side * 2.2
        out["mountain"] = {"loc": (cam.x, cam.y, p.z + 1.6), "target": (150, -250, 20), "lens": 20, "sky": "dusk", "exposure": 0.9}
    # avenue: downtown avenue at street level (the spawn road)
    sp = world.get("spawn")
    if sp:
        r = roads[sp["road"]]
        pts = r["points"]
        a, b = Vector(pts[0]), Vector(pts[-1])
        t = (b - a).to_2d().normalized()
        side = Vector((-t.y, t.x))
        p = Vector(sp["pos"]).to_2d() - t * 30 + side * 0.8
        out["avenue"] = {"loc": (p.x, p.y, sp["pos"][2] + 1.0), "target": (p.x + t.x * 100, p.y + t.y * 100, sp["pos"][2] + 9.0), "lens": 22,
                         "sky": "night", "exposure": 1.0, "fog": 0.0015}
    out["top"] = {"ortho": 4200, "loc": (0, 0, 2000), "sky": "day", "exposure": 0.0}
    return out


def render(world, built, root, opt, log):
    res = tuple(int(v) for v in str(opt("--res", "1600x900")).split("x"))
    setup(int(opt("--samples", 128)), res, cpu=bool(opt("--cpu")))
    sc = bpy.context.scene
    cam = bpy.data.objects.get("WorldCam") or bpy.data.objects.new("WorldCam", bpy.data.cameras.new("WorldCam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    outdir = os.path.join(root, str(opt("--render-dir", os.path.join("docs", "agents", "world"))))
    os.makedirs(outdir, exist_ok=True)
    want = str(opt("--shots", "aerial,bridge,mountain,avenue")).split(",")
    for name, s in shots(world, built).items():
        if name not in want:
            continue
        sky("day" if opt("--day") else s["sky"], 0.0 if opt("--day") else s.get("fog", 0.0))
        sc.view_settings.exposure = s.get("exposure", 0.0)
        if "ortho" in s:
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = s["ortho"]
            cam.location = s["loc"]
            cam.rotation_euler = (0, 0, 0)
            cam.data.clip_end = 5000
        else:
            cam.data.type = "PERSP"
            aim(cam, s["loc"], s["target"], s["lens"])
        sc.render.filepath = os.path.join(outdir, name + ".png")
        import time
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        log(f"rendered {name} in {time.time() - t0:.0f} s -> {sc.render.filepath}")
