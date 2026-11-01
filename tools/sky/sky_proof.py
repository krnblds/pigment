"""Render the town under the old flat world and under the new skies (Cycles).

    blender -b --factory-startup scenes/town/cyberpunk_town.blend --python tools/sky/sky_proof.py -- \
        [--skies old,night_rain,dusk,predawn,night_moon] [--shots street,drone,aerial] \
        [--samples 96] [--res 1280x720] [--out docs/agents/sky]

Writes <out>/town_<shot>_<sky>.png (a caption is stamped into each) and, with
--sheet, <out>/town_<shot>_compare.png: every sky for a shot in one column.
The town textures are git-ignored: make them first (python tools/town_textures.py,
python tools/road_textures.py --run) or link scenes/town/textures to a checkout
that has them; without them the town renders untextured.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


ns = {"__name__": "make_sky", "__file__": os.path.join(HERE, "make_sky.py")}
exec(compile(open(ns["__file__"], encoding="utf-8").read(), ns["__file__"], "exec"), ns)

SHOTS = {
    # street level in the Y fork (the saved TownCam), a low drone view with the skyline, the
    # driver's overview
    "street": None,
    "drone": ((-150.0, -175.0, 34.0), (10.0, 20.0, 22.0), 20),
    "aerial": ((-40.0, -110.0, 120.0), (15.0, 25.0, 0.0), 30),
}


def setup(sc, samples, res):
    sc.render.engine = "CYCLES"
    ns["_cycles"](sc, samples)
    sc.cycles.use_denoising = True
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.max_bounces = 6
    sc.cycles.volume_bounces = 1
    sc.cycles.volume_step_rate = 4.0
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.compression = 90
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Punchy"
    sc.view_settings.exposure = 0.6
    r = sc.render
    r.use_stamp = True
    for k in dir(r):
        if k.startswith("use_stamp_") and k not in ("use_stamp_note", "use_stamp_labels"):
            try:
                setattr(r, k, False)
            except (AttributeError, TypeError):
                pass
    r.use_stamp_note = True
    r.use_stamp_labels = False
    r.stamp_font_size = 22


def main():
    sc = bpy.context.scene
    skies = opt("--skies", "old,night_rain").split(",")
    shots = opt("--shots", "street,drone").split(",")
    out = os.path.join(ROOT, opt("--out", os.path.join("docs", "agents", "sky")))
    w, h = (int(v) for v in opt("--res", "1280x720").split("x"))
    setup(sc, int(opt("--samples", 96)), (w, h))
    cam = sc.camera
    street = (tuple(cam.location), tuple(cam.rotation_euler), cam.data.lens)
    old_world = sc.world
    old_moon = None
    mo = bpy.data.objects.get("Moon")
    if mo:
        old_moon = (mo.data.energy, tuple(mo.data.color), tuple(mo.rotation_euler))
    fwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
    print("street camera azimuth", math.degrees(math.atan2(fwd.y, fwd.x)))
    for sky in skies:
        if sky == "old":
            sc.world = old_world
            fog = bpy.data.objects.get("SkyFog")
            if fog:
                fog.hide_render = True
            if mo and old_moon:
                mo.data.energy, mo.data.color, mo.rotation_euler = old_moon[0], old_moon[1], old_moon[2]
            label = "OLD: flat TownNight world + world-volume fog"
        else:
            ns["apply_sky"](sc, sky)
            bpy.data.objects["SkyFog"].hide_render = False
            label = f"NEW: {ns['PRESETS'][sky]['label']} ({sky}_2k.hdr + SkyFog)"
        for shot in shots:
            if SHOTS[shot] is None:
                cam.location, cam.rotation_euler, cam.data.lens = Vector(street[0]), street[1], street[2]
            else:
                loc, tgt, lens = SHOTS[shot]
                cam.location = loc
                cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
                cam.data.lens = lens
            sc.render.stamp_note_text = f"{label}   [{shot}]"
            path = os.path.join(out, f"town_{shot}_{sky}.png")
            sc.render.filepath = path
            bpy.ops.render.render(write_still=True)
            print("wrote", path)
    if opt("--sheet"):
        sheet(out, shots, skies)


def sheet(out, shots, skies, width=1280):
    """Stack the renders of each shot vertically (old on top) into one PNG."""
    import numpy as np
    for shot in shots:
        tiles = []
        for sky in skies:
            p = os.path.join(out, f"town_{shot}_{sky}.png")
            if not os.path.isfile(p):
                continue
            im = bpy.data.images.load(p)
            if im.size[0] != width:
                im.scale(width, int(im.size[1] * width / im.size[0]))
            a = np.array(im.pixels[:], dtype=np.float32).reshape(im.size[1], im.size[0], 4)
            tiles.append(a)
            bpy.data.images.remove(im)
        if not tiles:
            continue
        gap = np.ones((6, width, 4), np.float32)
        gap[..., :3] = 0.05
        rows = []
        for t in reversed(tiles):          # Blender images are bottom-up
            rows += [t, gap]
        full = np.concatenate(rows[:-1], axis=0)
        img = bpy.data.images.new(f"sheet_{shot}", width, full.shape[0])
        img.pixels = full.ravel()
        img.filepath_raw = os.path.join(out, f"town_{shot}_compare.png")
        img.file_format = "PNG"
        img.save()
        print("wrote", img.filepath_raw)


main()
