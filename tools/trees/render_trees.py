"""Proof renders of the tree kit (headless Blender 5.2, Cycles):

    blender -b --factory-startup --python tools/trees/render_trees.py -- lineup [--night] [--out FILE] [--samples N] [--keys a,b] [--lod 0|1|2]
    blender -b --factory-startup --python tools/trees/render_trees.py -- lods --keys tree_zelkova_a

lineup   every species (first shape + its looks) side by side on a paved ground, studio daylight
         or night (street lamps behind / in front of the crowns, wet ground, rain haze)
lods     one variant at LOD0 / LOD1 / LOD2 side by side
"""
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import tree_blender as TB  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


LINEUP = ["tree_pagoda_a", "tree_zelkova_a", "tree_ginkgo_a", "tree_ginkgo_a_gold", "tree_cherry_a", "tree_cherry_a_green",
          "tree_pine_a", "tree_cedar_a", "tree_palm_a", "tree_azalea_a_bloom", "tree_box_a"]


def setup(samples, w, h, night):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        sc.cycles.device = "GPU"
    except Exception as e:
        print("GPU setup:", e)
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast" if not night else "AgX - Base Contrast"
    sc.cycles.max_bounces = 6
    sc.cycles.transparent_max_bounces = 64
    w_ = bpy.data.worlds.new("W")
    sc.world = w_
    w_.use_nodes = True
    nt = w_.node_tree
    bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
    if night:
        bg.inputs["Color"].default_value = (0.012, 0.018, 0.035, 1)
        bg.inputs["Strength"].default_value = 0.6
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        try:
            sky.sky_type = "MULTIPLE_SCATTERING"
        except Exception:
            pass
        try:
            sky.sun_elevation = math.radians(38)
            sky.sun_rotation = math.radians(150)
        except Exception:
            pass
        nt.links.new(sky.outputs[0], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.22


def ground(night, size=200):
    bpy.ops.mesh.primitive_plane_add(size=size)
    g = bpy.context.object
    m = bpy.data.materials.new("Ground")
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (0.05, 0.05, 0.052, 1) if night else (0.09, 0.09, 0.085, 1)
    b.inputs["Roughness"].default_value = 0.22 if night else 0.8
    g.data.materials.append(m)
    return g


def place(key, x, y=0.0, lod=0, rz=0.0):
    me = TB.kit_mesh(ROOT, key, lod)
    if me is None:
        print("missing", key)
        return None
    o = bpy.data.objects.new(key, me)
    o.location = (x, y, 0)
    o.rotation_euler = (0, 0, rz)
    bpy.context.scene.collection.objects.link(o)
    return o


def lamp(p, energy=900, col=(1.0, 0.72, 0.42), size=0.25):
    li = bpy.data.lights.new("Lamp", "POINT")
    li.energy = energy
    li.color = col
    li.shadow_soft_size = size
    o = bpy.data.objects.new("Lamp", li)
    o.location = p
    bpy.context.scene.collection.objects.link(o)


def sun(elev=38, rot=150, strength=2.4):
    li = bpy.data.lights.new("Sun", "SUN")
    li.energy = strength
    li.angle = math.radians(1.5)
    o = bpy.data.objects.new("Sun", li)
    o.rotation_euler = (math.radians(90 - elev), 0, math.radians(rot))
    bpy.context.scene.collection.objects.link(o)


def camera(loc, look, lens=35):
    cd = bpy.data.cameras.new("Cam")
    cd.lens = lens
    cd.clip_end = 2000
    c = bpy.data.objects.new("Cam", cd)
    bpy.context.scene.collection.objects.link(c)
    c.location = loc
    d = [look[i] - loc[i] for i in range(3)]
    c.rotation_euler = (math.atan2(math.hypot(d[0], d[1]), -d[2]), 0, math.atan2(d[1], d[0]) - math.pi / 2)
    bpy.context.scene.camera = c
    return c


def lineup(keys, night, lod):
    idx = TB.load_index(ROOT)
    x = 0.0
    xs = []
    for k in keys:
        if k not in idx["variants"]:
            print("not built:", k)
            continue
        r = max(idx["variants"][k]["crown_radius"], 0.6)
        x += r * 0.85
        place(k, x, 0, lod, rz=0.4)
        xs.append((k, x))
        x += r * 0.85 + 0.8
    span = x
    hmax = max(idx["variants"][k]["height"] for k, _ in xs)
    ground(night, size=span * 4)
    cx = span / 2
    fov = 2 * math.atan(18 / 38)
    dist = span / 2 / math.tan(fov / 2) * 1.02
    camera((cx, -dist, hmax * 0.3), (cx, 0, hmax * 0.3), lens=38)
    if night:
        for k, xx in xs:
            lamp((xx - 2.2, -3.0, 6.0), 1400)
            lamp((xx + 1.5, 3.5, 5.0), 900, (0.5, 0.75, 1.0))
        # neon wash from the side
        lamp((cx, -30, 12), 30000, (1.0, 0.25, 0.6), 3.0)
    else:
        sun()


def sheet(keys, night, lod, samples, tile_w, tile_h, outdir):
    """One framed render per variant (tiles; tools/trees/contact_sheet.py composites + labels)."""
    idx = TB.load_index(ROOT)
    sc = bpy.context.scene
    ground(night, 300)
    if night:
        lamp_objs = []
    else:
        sun()
    cam = camera((0, -20, 5), (0, 0, 5), 50)
    fov = 2 * math.atan(18 / 50)
    for k in keys:
        if k not in idx["variants"]:
            continue
        v = idx["variants"][k]
        o = place(k, 0, 0, lod, 0.4)
        H, R = v["height"], v["crown_radius"]
        aspect = tile_w / tile_h
        need = max(H * 1.12, 2 * R * 1.1 / aspect)
        dist = need / 2 / math.tan(fov / 2 / aspect if aspect < 1 else fov / 2) * (1.0 if aspect < 1 else 1.0)
        dist = need / 2 / math.tan(math.atan(math.tan(fov / 2) / aspect)) if aspect < 1 else need / 2 / math.tan(fov / 2) * aspect
        me_ = o.data
        xs_ = [v_.co.x for v_ in me_.vertices]
        cxx = (min(xs_) + max(xs_)) / 2 * math.cos(0.4)
        cam.location = (cxx, -dist, H * 0.5)
        cam.rotation_euler = (math.radians(90), 0, 0)
        lights = []
        if night:
            for p_, e, c in (((-0.35 * R - 1.5, -2.0, min(6.0, H * 0.7)), 1500, (1.0, 0.72, 0.42)),
                             ((0.5 * R, 2.5, H * 0.5), 1200, (0.45, 0.75, 1.0)),
                             ((R * 2.5, -R * 2.0, H * 0.4), 9000, (1.0, 0.25, 0.65))):
                li = bpy.data.lights.new("L", "POINT")
                li.energy = e * max(1.0, H / 10) ** 1.5 * min(1.0, H / 6.0) ** 1.5
                li.color = c
                li.shadow_soft_size = 0.3
                lo = bpy.data.objects.new("L", li)
                lo.location = p_
                sc.collection.objects.link(lo)
                lights.append(lo)
        sc.render.resolution_x, sc.render.resolution_y = tile_w, tile_h
        sc.render.filepath = os.path.join(outdir, f"{k}{'_night' if night else ''}_lod{lod}.png")
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(o)
        for lo in lights:
            bpy.data.objects.remove(lo)


def main():
    mode = next((a for a in ARGS if not a.startswith("--")), "lineup")
    night = bool(opt("--night"))
    samples = int(opt("--samples", 64))
    lod = int(opt("--lod", 0))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    keys = opt("--keys")
    keys = keys.split(",") if isinstance(keys, str) else LINEUP
    if mode == "lineup":
        setup(samples, int(opt("--w", 2400)), int(opt("--h", 900)), night)
        lineup(keys, night, lod)
    elif mode == "sheet":
        setup(samples, 600, 700, night)
        sheet(keys, night, lod, samples, int(opt("--w", 600)), int(opt("--h", 700)), os.path.join(ROOT, "target", "trees", "tiles"))
        return
    elif mode == "lods":
        setup(samples, 1800, 800, night)
        idx = TB.load_index(ROOT)
        k = keys[0]
        r = idx["variants"][k]["crown_radius"]
        for i in range(3):
            place(k, i * r * 2.3, 0, i, 0.4)
        ground(night)
        camera((r * 2.3, -r * 6.5, idx["variants"][k]["height"] * 0.4), (r * 2.3, 0, idx["variants"][k]["height"] * 0.4), 40)
        sun()
    out = opt("--out", os.path.join(ROOT, "target", "trees", f"{mode}{'_night' if night else ''}.png"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sc = bpy.context.scene
    sc.render.filepath = out
    if out.lower().endswith(".jpg"):
        sc.render.image_settings.file_format = "JPEG"
        sc.render.image_settings.quality = 90
    bpy.ops.render.render(write_still=True)
    print("wrote", out)


main()
