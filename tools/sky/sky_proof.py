"""Render the town under the old flat world and under the new skies (Cycles).

    blender -b --factory-startup scenes/town/cyberpunk_town.blend --python tools/sky/sky_proof.py -- \
        [--skies old,night_rain,dusk,predawn,night_moon] [--shots street,drone,aerial] \
        [--samples 96] [--res 1280x720] [--out docs/agents/sky/renders] [--sheet docs/agents/sky]

Writes <out>/town_<shot>_<sky>.png (a caption is stamped into each) and, with
--sheet DIR, DIR/town_<shot>_old_vs_new.png and DIR/town_presets.png.
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
        sheets(out, shots, skies, os.path.join(ROOT, opt("--sheet")))


def grid(paths, cols, tile_w, out_path):
    """Lay PNGs out in a grid (row-major, first at the top left) with thin gaps."""
    import numpy as np
    tiles = []
    for p in paths:
        im = bpy.data.images.load(p)
        th = int(im.size[1] * tile_w / im.size[0])
        im.scale(tile_w, th)
        tiles.append(np.array(im.pixels[:], dtype=np.float32).reshape(th, tile_w, 4)[::-1])   # top-down
        bpy.data.images.remove(im)
    g = 6
    th = tiles[0].shape[0]
    rows = (len(tiles) + cols - 1) // cols
    full = np.zeros((rows * th + (rows - 1) * g, cols * tile_w + (cols - 1) * g, 4), np.float32)
    full[..., :3] = 0.05
    full[..., 3] = 1.0
    for k, t in enumerate(tiles):
        r, c = divmod(k, cols)
        full[r * (th + g):r * (th + g) + th, c * (tile_w + g):c * (tile_w + g) + tile_w] = t
    img = bpy.data.images.new(os.path.basename(out_path), full.shape[1], full.shape[0])
    img.pixels = full[::-1].ravel()
    img.filepath_raw = out_path
    img.file_format = "PNG"
    img.save()
    print("wrote", out_path)


def sheets(out, shots, skies, dest):
    """<dest>/town_<shot>_old_vs_new.png (old above night_rain) and <dest>/town_presets.png
    (every new sky: one row each, the shots side by side)."""
    os.makedirs(dest, exist_ok=True)
    f = lambda shot, sky: os.path.join(out, f"town_{shot}_{sky}.png")
    if "old" in skies and "night_rain" in skies:
        for shot in shots:
            grid([f(shot, "old"), f(shot, "night_rain")], 1, 960, os.path.join(dest, f"town_{shot}_old_vs_new.png"))
    new = [s for s in skies if s != "old"]
    if new:
        two = [s for s in shots if s in ("street", "drone")] or shots[:2]
        grid([f(shot, sky) for sky in new for shot in two], len(two), 640, os.path.join(dest, "town_presets.png"))

main()
