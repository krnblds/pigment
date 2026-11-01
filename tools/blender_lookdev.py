"""Render one Pigment-textured asset in headless Blender (Cycles) with the
same camera and lighting as Pigment's `render`, to compare the two.

    blender -b --factory-startup --python tools/blender_lookdev.py -- \
        --mesh assets/town/building_a.glb --maps scenes/town/textures/building_a \
        --name building_a --hdri night.hdr --out out.png \
        [--yaw 25 --pitch 12 --zoom 1 --width 640 --height 800 \
         --emission 6.0 --exposure 0 --bloom --samples 128]

The world uses the .hdr written by Pigment's `export_lighting` tool. Camera:
Pigment's orbit camera (vertical FOV 40 degrees, framed on the mesh's
bounding sphere at distance r / sin(20 deg) * 1.1 / zoom, eye at
target + (sin yaw cos pitch, sin pitch, cos yaw cos pitch) * distance in glTF
space, i.e. (x, -z, y) in Blender). `--emission` is the `emissive_scale` that
Pigment's `export_textures` reports. `--bloom` adds a compositor Glare (bloom).
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_pigment import apply_pigment_material  # noqa: E402


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--mesh", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--hdri", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--yaw", type=float, default=25.0)
    p.add_argument("--pitch", type=float, default=12.0)
    p.add_argument("--zoom", type=float, default=1.0)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=800)
    p.add_argument("--emission", type=float, default=6.0)
    p.add_argument("--exposure", type=float, default=0.0)
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--bloom", action="store_true")
    return p.parse_args(argv)


def world(hdri):
    w = bpy.data.worlds.new("Pigment lighting")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    env.image = bpy.data.images.load(os.path.abspath(hdri))
    # Pigment's equirect centre (u = 0.5) is glTF -Z = Blender +Y; Blender's
    # is +X. Same handedness, so a -90 degree turn about Z lines them up.
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(-90.0))
    nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def camera(objs, yaw, pitch, zoom, w, h):
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c = (lo + hi) * 0.5
    r = max((p - c).length for p in pts)
    fov = math.radians(40.0)
    d = r / math.sin(fov * 0.5) * 1.1 / max(zoom, 0.05)
    y, p = math.radians(yaw), math.radians(pitch)
    gl = Vector((math.sin(y) * math.cos(p), math.sin(p), math.cos(y) * math.cos(p)))
    eye = c + Vector((gl.x, -gl.z, gl.y)) * d
    cam = bpy.data.cameras.new("Pigment camera")
    cam.sensor_fit = "VERTICAL"
    cam.angle_y = fov
    cam.clip_start = d * 0.001
    cam.clip_end = d * 100
    ob = bpy.data.objects.new("Pigment camera", cam)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = eye
    ob.rotation_euler = (c - eye).to_track_quat("-Z", "Y").to_euler()
    s = bpy.context.scene
    s.camera = ob
    s.render.resolution_x, s.render.resolution_y = w, h
    s.render.resolution_percentage = 100


def bloom_compositor(scene):
    """Glare (bloom) in the compositor; the API moved between 4.x and 5.x."""
    try:
        tree = bpy.data.node_groups.new("Pigment bloom", "CompositorNodeTree")
        scene.compositing_node_group = tree
        out = tree.nodes.new("NodeGroupOutput")
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    except (AttributeError, TypeError):
        scene.use_nodes = True
        tree = scene.node_tree
        tree.nodes.clear()
        out = tree.nodes.new("CompositorNodeComposite")
    rl = tree.nodes.new("CompositorNodeRLayers")
    glare = tree.nodes.new("CompositorNodeGlare")
    for attr, val in (("glare_type", "BLOOM"), ("quality", "HIGH"), ("threshold", 0.8), ("size", 8)):
        if hasattr(glare, attr):
            try:
                setattr(glare, attr, val)
            except (TypeError, ValueError):
                pass
    for name, val in (("Type", "Bloom"), ("Quality", "High"), ("Threshold", 0.8), ("Strength", 1.0), ("Size", 0.6)):
        sock = glare.inputs.get(name)
        if sock is not None:
            try:
                sock.default_value = val
            except (TypeError, ValueError):
                pass
    tree.links.new(rl.outputs["Image"], glare.inputs["Image"])
    tree.links.new(glare.outputs["Image"], out.inputs[0])


def main():
    a = args()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(a.mesh))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:
        apply_pigment_material(o, os.path.abspath(a.maps), a.name, emission_strength=a.emission)
    world(a.hdri)
    camera(meshes, a.yaw, a.pitch, a.zoom, a.width, a.height)

    s = bpy.context.scene
    try:
        s.render.engine = "CYCLES"
    except TypeError as e:
        print("engine:", e)
    s.cycles.samples = a.samples
    s.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for dev in prefs.devices:
            dev.use = dev.type == "OPTIX"
        s.cycles.device = "GPU"
    except Exception as e:  # CPU fallback
        print("GPU setup failed:", e)
    # Pigment tone maps with Hill's fit of the ACES 1.x RRT + sRGB ODT.
    for vt in ("ACES 1.3", "ACES 2.0", "AgX", "Filmic", "Standard"):
        try:
            s.view_settings.view_transform = vt
            break
        except TypeError:
            continue
    s.view_settings.exposure = a.exposure
    print("view transform:", s.view_settings.view_transform)
    if a.bloom:
        bloom_compositor(s)
    s.render.filepath = os.path.abspath(a.out)
    s.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print("saved", s.render.filepath)


main()
