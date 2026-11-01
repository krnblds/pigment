"""Quick Workbench clay previews of whatever is in the scene (for iterating on the model).

    import preview; preview.clay(out_dir, views=("front34", "side", ...))
"""
import math
import os

import bpy
from mathutils import Vector

VIEWS = {
    "front34": (Vector((-4.2, -5.6, 1.9)), Vector((0, -0.2, 0.6))),
    "rear34": (Vector((4.6, 5.4, 2.0)), Vector((0, 0.2, 0.6))),
    "side": (Vector((-9.0, 0, 0.75)), Vector((0, 0, 0.72))),
    "front": (Vector((0, -9.0, 0.8)), Vector((0, 0, 0.72))),
    "rear": (Vector((0, 9.0, 0.8)), Vector((0, 0, 0.72))),
    "top": (Vector((0, 0.001, 12.0)), Vector((0, 0, 0.5))),
    "low34": (Vector((-3.4, -4.0, 0.55)), Vector((0, -0.6, 0.55))),
    "wheel": (Vector((-2.6, -2.4, 0.5)), Vector((0.76, -1.33, 0.33))),
}


def clay(out_dir, views=("front34", "side", "rear34", "front", "top"), res=(1280, 720), wire=False, ortho=("side", "front", "rear", "top"), lens=50):
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "SINGLE"
    sh.single_color = (0.72, 0.72, 0.74)
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.show_shadows = False
    sh.show_object_outline = False
    sc.display.render_aa = "8"
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("W")
    if wire:
        sc.render.use_freestyle = False
    cam = bpy.data.objects.get("PreviewCam")
    if cam is None:
        cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
        sc.collection.objects.link(cam)
    sc.camera = cam
    out = []
    for v in views:
        loc, tgt = VIEWS[v] if isinstance(v, str) else v
        name = v if isinstance(v, str) else "view"
        cam.location = loc
        d = tgt - loc
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        if name in ortho:
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = 5.2 if name != "top" else 5.2
        else:
            cam.data.type = "PERSP"
            cam.data.lens = lens
        p = os.path.join(out_dir, f"{name}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        out.append(p)
    return out
