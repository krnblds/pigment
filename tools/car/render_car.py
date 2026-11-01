"""Proof renders of the exported car (headless Blender 5.2, Cycles / OptiX).

    blender -b --factory-startup --python tools/car/render_car.py -- MODE [--out DIR] [--samples N] [--glb PATH]

MODE:
    studio     night studio: wet black floor, overhead area-light strips (reflection lines),
               cyan + magenta neon rim tubes. 3/4 front, side profile, 3/4 rear.
    turntable  8 views round the car in the night studio, one contact sheet
    clay       clay + wireframe sheet (4 views)
    town       the car on a street of scenes/town/cyberpunk_town.blend at night
It imports assets/car/car.glb (what Godot gets), not the build scene.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = argv[0] if argv else "studio"


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


OUT = opt("--out", os.path.join(ROOT, "docs", "agents", "car"))
SAMPLES = int(opt("--samples", "160"))
GLB = opt("--glb", os.path.join(ROOT, "assets", "car", "car.glb"))


def cycles(res=(1600, 1000)):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            for d in prefs.devices:
                d.use = d.type == kind
            sc.cycles.device = "GPU"
            break
        except Exception:
            continue
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 10
    sc.cycles.transparent_max_bounces = 16
    sc.cycles.caustics_reflective = False
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    sc.render.image_settings.file_format = "PNG"


def import_car(path=GLB, z=0.0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.data.objects if o not in before]
    for o in objs:
        if o.name.startswith("Collider"):
            o.hide_render = True
            o.hide_set(True)
    # importer: glTF +Z forward -> Blender -Y forward (the car faces -Y again)
    return objs


def emissive_mat(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    return m


def wet_floor():
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))
    fl = bpy.context.object
    fl.name = "WetFloor"
    m = bpy.data.materials.new("WetFloor")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.012, 0.012, 0.014, 1)
    b.inputs["Metallic"].default_value = 0.0
    # puddly: roughness varies between mirror-wet and damp asphalt
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = 0.6
    tex.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.45
    ramp.inputs["From Max"].default_value = 0.6
    ramp.inputs["To Min"].default_value = 0.03
    ramp.inputs["To Max"].default_value = 0.32
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], b.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = 60
    nt.links.new(n2.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    fl.data.materials.append(m)
    return fl


def strip_light(name, loc, size, rot, color, energy):
    d = bpy.data.lights.new(name, "AREA")
    d.shape = "RECTANGLE"
    d.size, d.size_y = size
    d.color = color
    d.energy = energy
    o = bpy.data.objects.new(name, d)
    o.location = loc
    o.rotation_euler = rot
    bpy.context.scene.collection.objects.link(o)
    return o


def neon_tube(name, a, b, color, strength, r=0.025):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=(b - a).length, location=(a + b) / 2)
    o = bpy.context.object
    o.name = name
    o.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
    o.data.materials.append(emissive_mat(name, color, strength))
    o.visible_camera = True
    return o


def night_studio():
    sc = bpy.context.scene
    w = bpy.data.worlds.new("NightStudio")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.004, 0.006, 0.012, 1)
    bg.inputs["Strength"].default_value = 1.0
    sc.world = w
    wet_floor()
    # overhead softbox strips: long reflection lines along the body
    for i, x in enumerate((-1.1, 0.0, 1.1)):
        l = strip_light(f"Strip{i}", (x, 0, 3.4), (0.18, 6.0), (0, 0, 0), (0.9, 0.95, 1.0), 260)
    # a big soft key from the front-left, and a warm sodium fill from the right
    strip_light("Key", (-4.5, -4.0, 2.4), (3.0, 1.0), (math.radians(65), 0, math.radians(-48)), (0.85, 0.9, 1.0), 260)
    strip_light("Sodium", (4.5, 1.5, 1.8), (1.5, 1.5), (math.radians(70), 0, math.radians(110)), (1.0, 0.55, 0.22), 160)
    # neon rim tubes behind the car (visible, reflected in the paint and the wet floor)
    neon_tube("NeonCyan", (-6, 6.5, 0.25), (6, 6.5, 0.25), (0.1, 0.85, 1.0), 40, 0.03)
    neon_tube("NeonMagenta", (-6.5, 4.5, 2.6), (-6.5, -5, 2.6), (1.0, 0.1, 0.6), 35, 0.03)
    neon_tube("NeonMagenta2", (6.5, 4.5, 0.6), (6.5, -5, 0.6), (1.0, 0.15, 0.5), 25, 0.03)
    strip_light("RimCyan", (0, 6.0, 1.0), (8.0, 0.4), (math.radians(-90), 0, 0), (0.1, 0.8, 1.0), 380)
    strip_light("RimMagenta", (-6.0, 0, 2.4), (0.4, 8.0), (0, math.radians(-75), 0), (1.0, 0.12, 0.6), 320)


def camera(name, loc, target, lens=50):
    c = bpy.data.cameras.new(name)
    c.lens = lens
    c.dof.use_dof = False
    o = bpy.data.objects.new(name, c)
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(o)
    return o


def shoot(cam, path):
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("[render_car]", path)


SHOTS = {
    "front34": ((-4.6, -5.4, 1.15), (0.0, -0.35, 0.55), 50),
    "side": ((-8.5, 0.0, 0.75), (0.0, 0.0, 0.62), 50),
    "rear34": ((4.4, 5.6, 1.25), (0.0, 0.35, 0.6), 50),
}


def sheet(paths, cols, out):
    """Combine PNGs into a contact sheet with Blender's image API."""
    ims = [bpy.data.images.load(p) for p in paths]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    big = bpy.data.images.new("sheet", cols * w, rows * h, alpha=False)
    import array
    px = array.array("f", [0.0]) * (cols * w * rows * h * 4)
    for i, im in enumerate(ims):
        src = array.array("f", [0.0]) * (w * h * 4)
        im.pixels.foreach_get(src)
        cx, cy = i % cols, rows - 1 - i // cols
        for y in range(h):
            o = ((cy * h + y) * cols * w + cx * w) * 4
            px[o:o + w * 4] = src[y * w * 4:(y + 1) * w * 4]
    big.pixels.foreach_set(px)
    big.filepath_raw = out
    big.file_format = "PNG"
    big.save()
    for p in paths:
        os.remove(p)
    print("[render_car]", out)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    if MODE == "town":
        return town()
    import_car()
    if MODE == "studio":
        cycles((1280, 768))
        night_studio()
        for nm, (loc, tgt, lens) in SHOTS.items():
            shoot(camera(nm, loc, tgt, lens), os.path.join(OUT, f"car_studio_{nm}.png"))
    elif MODE == "turntable":
        cycles((640, 400))
        night_studio()
        paths = []
        for i in range(8):
            a = math.radians(-135 + i * 45)
            loc = (8.4 * math.sin(a), -8.4 * math.cos(a), 1.9)
            p = os.path.join(OUT, f"_tt{i}.png")
            shoot(camera(f"tt{i}", loc, (0, 0, 0.55), 50), p)
            paths.append(p)
        sheet(paths, 4, os.path.join(OUT, "car_turntable.png"))
    elif MODE == "clay":
        sc = bpy.context.scene
        sc.render.engine = "BLENDER_WORKBENCH"
        sh = sc.display.shading
        sh.light = "STUDIO"
        sh.color_type = "SINGLE"
        sh.single_color = (0.75, 0.75, 0.76)
        sh.show_cavity = True
        sh.cavity_type = "BOTH"
        sc.display.render_aa = "16"
        sc.render.resolution_x, sc.render.resolution_y = (900, 560)
        sc.render.image_settings.file_format = "PNG"
        # wireframe overlay via a wireframe-modifier copy in dark grey
        for o in [o for o in sc.objects if o.type == "MESH" and not o.name.startswith("Collider")]:
            w = o.copy()
            w.data = o.data
            sc.collection.objects.link(w)
            m = w.modifiers.new("wire", "WIREFRAME")
            m.thickness = 0.0016
            m.use_replace = True
            m.use_even_offset = False
            w.color = (0.1, 0.1, 0.12, 1)
            w["wire"] = True
        sh.color_type = "OBJECT"
        for o in sc.objects:
            if o.type == "MESH" and "wire" not in o.keys():
                o.color = (0.78, 0.78, 0.8, 1)
        paths = []
        views = [((-4.6, -5.4, 1.4), (0, -0.3, 0.55)), ((4.6, 5.4, 1.5), (0, 0.3, 0.6)), ((-8.5, 0, 0.75), (0, 0, 0.62)),
                 ((-2.2, -2.6, 0.7), (0.79, -1.33, 0.33))]
        for i, (loc, tgt) in enumerate(views):
            p = os.path.join(OUT, f"_clay{i}.png")
            shoot(camera(f"c{i}", loc, tgt, 50 if i < 3 else 60), p)
            paths.append(p)
        sheet(paths, 2, os.path.join(OUT, "car_clay_wire.png"))


def town():
    blend = os.path.join(ROOT, "scenes", "town", "cyberpunk_town.blend")
    bpy.ops.wm.open_mainfile(filepath=blend)
    import_car()


if __name__ == "__main__":
    main()
