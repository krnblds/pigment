"""Render the Pigment icon as a real PBR object in Blender (Cycles).

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup \
        --python tools/branding/render_icon.py

The same design as make_svgs.py, modelled instead of drawn: a graphite ball
with one stroke of orange paint on it. The stroke is real geometry: bristle
strips laid on the sphere along a tilted great circle (the same band_point
maths as the SVG), with a thickness profile that is fullest in the middle,
ridged per bristle and thinning out to a ragged dry-brush end. The paint is
the accent colour under a glossy clearcoat; the ball is matte graphite.
A studio softbox, a rim and a kicker light it on a transparent film.

Writes assets/branding/render/pigment-icon-1024.png. make_icons.py uses it
for every size from 48 px up when it exists; 16-32 px stay on the
hand-simplified SVG.
"""
import math
import os
import random
import sys

import bpy
import bmesh
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_svgs  # noqa: E402  (shares the stroke geometry with the SVG)

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "assets", "branding", "render", "pigment-icon-1024.png")
SIZE = int(os.environ.get("PIGMENT_ICON_SIZE", "1024"))
SAMPLES = int(os.environ.get("PIGMENT_ICON_SAMPLES", "384"))

SPEC = make_svgs.SPECS["pigment-icon.svg"]
ACCENT = (0.93, 0.25, 0.03)  # #F08A3C in linear, pushed a touch to survive AgX


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


def view_to_world(p):
    """make_svgs view space (x right, y up, z to the viewer) to Blender (z up, camera on -Y)."""
    x, y, z = p
    return Vector((x, -z, y))


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def node(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def principled(nt):
    return next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")


def graphite_material():
    m = bpy.data.materials.new("Graphite")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = principled(nt)
    bsdf.inputs["Base Color"].default_value = srgb("#2B2E34")
    bsdf.inputs["Roughness"].default_value = 0.5
    bsdf.inputs["Specular IOR Level"].default_value = 0.5
    # a fine powder-coat grain in the roughness and a whisper of bump
    tex = node(nt, "ShaderNodeTexNoise", Scale=180.0, Detail=6.0)
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = 0.42
    ramp.inputs["To Max"].default_value = 0.6
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], bsdf.inputs["Roughness"])
    bump = node(nt, "ShaderNodeBump", Strength=0.04, Distance=0.002)
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def paint_material():
    m = bpy.data.materials.new("Pigment paint")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = principled(nt)
    bsdf.inputs["Base Color"].default_value = ACCENT + (1.0,)
    bsdf.inputs["Roughness"].default_value = 0.32
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.025
    bsdf.inputs["Coat IOR"].default_value = 1.5
    bsdf.inputs["Subsurface Weight"].default_value = 0.08
    bsdf.inputs["Subsurface Radius"].default_value = (0.02, 0.008, 0.004)
    # brush marks: fine streaks along the stroke (U runs along it) under the coat
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.5, 140.0, 1.0)
    nt.links.new(tc.outputs["UV"], mapping.inputs["Vector"])
    streak = node(nt, "ShaderNodeTexNoise", Scale=4.0, Detail=8.0, Roughness=0.6)
    nt.links.new(mapping.outputs["Vector"], streak.inputs["Vector"])
    bump = node(nt, "ShaderNodeBump", Strength=0.18, Distance=0.004)
    nt.links.new(streak.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    # a slightly deeper tone in the grooves
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = ACCENT + (1.0,)
    mix.inputs["B"].default_value = (0.78, 0.19, 0.02, 1.0)
    inv = nt.nodes.new("ShaderNodeMapRange")
    inv.inputs["From Min"].default_value = 0.35
    inv.inputs["From Max"].default_value = 0.6
    inv.inputs["To Min"].default_value = 0.45
    inv.inputs["To Max"].default_value = 0.0
    nt.links.new(streak.outputs["Fac"], inv.inputs["Value"])
    nt.links.new(inv.outputs["Result"], mix.inputs["Factor"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    return m


def ball():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=1.0)
    o = bpy.context.active_object
    o.name = "Ball"
    bpy.ops.object.shade_smooth()
    o.data.materials.append(graphite_material())
    return o


def stroke_mesh():
    """Bristle strips on the sphere, thick in the middle, ridged, ragged at the lifting end."""
    s = SPEC
    rng = random.Random(s.seed)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    n_across = 6        # vertices across one bristle
    a_far = 112.0       # the stroke runs on round the back
    db = 2 * s.band / s.bristles
    for i in range(s.bristles):
        edge = abs(i + 0.5 - s.bristles / 2) / (s.bristles / 2)
        end = s.a_end + s.ragged * (0.55 * edge ** 1.5 + 0.45 * rng.random())
        ridge = 0.65 + 0.35 * rng.random()  # how proud this bristle's ridge stands
        b0 = -s.band + i * db
        steps = max(8, int((a_far - end) / 0.75))
        rows = []
        for k in range(steps + 1):
            t = k / steps
            a = end + (a_far - end) * t
            # thickness: rises from the dry end, fullest across the middle bristles
            lift_in = min(1.0, (a - end) / 9.0) ** 0.6
            row = []
            for j in range(n_across + 1):
                u = j / n_across
                b = b0 + db * u
                across = math.sin(math.pi * u)  # each bristle leaves a shallow ridge
                body = 1 - (abs(b) / (s.band + 0.5)) ** 4  # the whole stroke thins at its edges
                h = 0.005 + 0.02 * body * lift_in * (0.9 + 0.1 * across * ridge)
                if a - end < 1.5:  # round the very tip of each bristle
                    w = (a - end) / 1.5
                    b = b0 + db * (0.5 + (u - 0.5) * (0.35 + 0.65 * w))
                p = view_to_world(make_svgs.band_point(a, b, s)) * (1.0 + h)
                v = bm.verts.new(p)
                row.append((v, (t, (i + u) / s.bristles)))
            rows.append(row)
        for k in range(steps):
            for j in range(n_across):
                quad = [rows[k][j], rows[k + 1][j], rows[k + 1][j + 1], rows[k][j + 1]]
                f = bm.faces.new([q[0] for q in quad])
                for loop, q in zip(f.loops, quad):
                    loop[uv_layer].uv = q[1]
    bm.normal_update()
    me = bpy.data.meshes.new("Stroke")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("Stroke", me)
    bpy.context.collection.objects.link(o)
    for p in me.polygons:
        p.use_smooth = True
    # face normals point out of the ball (winding check on one face)
    c = sum((v.co for v in me.vertices[:4]), Vector()) / 4
    if me.polygons[0].normal.dot(c) < 0:
        me.flip_normals()
    o.data.materials.append(paint_material())
    return o


def area(name, loc, size, energy, color=(1, 1, 1), size_y=None, shape="ELLIPSE"):
    d = bpy.data.lights.new(name, "AREA")
    d.energy = energy
    d.color = color
    d.shape = shape
    d.size = size
    d.size_y = size_y or size
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    o.location = loc
    direction = -Vector(loc)
    o.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return o


def scene():
    sc = bpy.context.scene
    try:
        sc.render.engine = "CYCLES"
    except TypeError as e:
        print("Cycles unavailable:", e)
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            if any(d.type == kind for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == kind
                sc.cycles.device = "GPU"
                print("Cycles device:", kind)
                break
        except TypeError:
            continue
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = SIZE
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.image_settings.color_depth = "8"
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Punchy"

    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.05, 0.055, 0.065, 1)
    bg.inputs["Strength"].default_value = 0.6
    sc.world = world

    cam_d = bpy.data.cameras.new("Cam")
    cam_d.type = "ORTHO"
    cam_d.ortho_scale = 2.0 * 128 / SPEC.r  # frame the ball as the SVG does
    cam = bpy.data.objects.new("Cam", cam_d)
    bpy.context.collection.objects.link(cam)
    cam.location = (0, -10, 0)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sc.camera = cam

    # key: a big softbox top left, its window reflected in the clearcoat
    area("Key", (-4.0, -5.0, 4.5), 4.5, 1100, (1.0, 0.97, 0.93), size_y=3.2)
    # rim: from behind on the right, so the dark ball separates from a dark taskbar
    area("Rim", (4.5, 4.0, 1.0), 2.5, 700, (0.85, 0.9, 1.0), size_y=4.0, shape="RECTANGLE")
    # kicker: low and warm from the right, grazing the stroke's far edge
    area("Kicker", (6.0, 1.0, -2.0), 3.0, 260, (1.0, 0.85, 0.7))
    # fill: big and weak from below, so the stroke's lower half keeps its colour
    area("Fill", (0.0, -2.5, -6.0), 6.0, 160, (1.0, 0.95, 0.9))


def main():
    clear()
    scene()
    ball()
    stroke_mesh()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.context.scene.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print("rendered", OUT)


main()
