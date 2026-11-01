"""Quick Workbench clay previews of whatever is in the scene (for iterating on a model).

    from vkit import preview; preview.clay(out_dir, views=("front34", "side", ...), scale=1.0)

`scale` grows the camera distances for long vehicles (1.0 = a 4.4 m car).
"""
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
    "interior": (Vector((-1.6, -0.9, 1.25)), Vector((0.2, 0.1, 0.7))),
}


def clay(out_dir, views=("front34", "side", "rear34", "front", "top"), res=(1280, 720), ortho=("side", "front", "rear", "top"),
         lens=50, scale=1.0, zc=0.0, wheel_target=None):
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "MATERIAL"
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.show_shadows = False
    sh.show_object_outline = False
    sc.display.render_aa = "8"
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("W")
    cam = bpy.data.objects.get("PreviewCam")
    if cam is None:
        cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
        sc.collection.objects.link(cam)
    sc.camera = cam
    out = []
    for v in views:
        loc, tgt = VIEWS[v] if isinstance(v, str) else v
        name = v if isinstance(v, str) else "view"
        loc, tgt = loc.copy(), tgt.copy()
        if name == "wheel" and wheel_target is not None:
            tgt = Vector(wheel_target)
            loc = tgt + Vector((-3.36, -1.07, 0.17)) * max(1.0, scale * 0.8)
        elif name != "interior":
            loc = Vector((loc.x * scale, loc.y * scale, loc.z * (scale if name == "top" else 1.0) + zc))
            tgt = Vector((tgt.x, tgt.y * scale, tgt.z + zc))
        d = tgt - loc
        cam.location = loc
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        if name in ortho:
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = 5.2 * scale
        else:
            cam.data.type = "PERSP"
            cam.data.lens = lens
        p = os.path.join(out_dir, f"{name}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        out.append(p)
    return out
