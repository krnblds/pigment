"""Headless test for tools/blender_pigment.py.

Run:
  "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup --python tools/test_blender_pigment.py

Creates dummy Pigment maps in %TEMP%/pig/maps, applies them to a UV-unwrapped cube,
checks the node links, and renders a tiny EEVEE frame to %TEMP%/pig/importer_test.png.
"""
import math
import os
import sys
import tempfile

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "pig")
MAP_DIR = os.path.join(OUT_DIR, "maps")
MAP_DIR_NOEMIT = os.path.join(OUT_DIR, "maps_noemit")
os.makedirs(MAP_DIR, exist_ok=True)
os.makedirs(MAP_DIR_NOEMIT, exist_ok=True)

ns = {"__name__": "blender_pigment"}
exec(compile(open(os.path.join(HERE, "blender_pigment.py"), encoding="utf-8").read(), "blender_pigment.py", "exec"), ns)
apply_pigment_material = ns["apply_pigment_material"]

print("Blender", bpy.app.version_string)

# ------------------------------------------------------------------ dummy maps
N = 64
yy, xx = np.mgrid[0:N, 0:N] / (N - 1)
checker = (((xx * 8).astype(int) + (yy * 8).astype(int)) % 2).astype(np.float32)
radial = np.clip(1 - np.hypot(xx - 0.5, yy - 0.5) * 2, 0, 1).astype(np.float32)


def save_png(path, rgb, depth="8", mode="RGB"):
    """rgb: HxWx3 float array 0..1 (row 0 = top). Saved via Blender's image writer."""
    h, w, _ = rgb.shape
    img = bpy.data.images.new("tmp_" + os.path.basename(path), w, h, alpha=True, float_buffer=(depth == "16"))
    px = np.ones((h, w, 4), np.float32)
    px[..., :3] = rgb[::-1]  # Blender pixels are bottom-up
    img.pixels.foreach_set(px.ravel())
    s = bpy.context.scene.render.image_settings
    s.file_format = "PNG"
    s.color_mode = mode
    s.color_depth = depth
    img.save_render(path)
    bpy.data.images.remove(img)


def grey(a):
    return np.repeat(a[..., None], 3, axis=2)


base = np.stack([0.15 + 0.7 * checker, 0.2 + 0.3 * checker, 0.6 - 0.4 * checker], axis=2)
normal = np.zeros((N, N, 3), np.float32)
normal[..., 0] = 0.5 + 0.2 * np.sin(xx * 12)
normal[..., 1] = 0.5
normal[..., 2] = 1.0
emiss = np.zeros((N, N, 3), np.float32)
emiss[(yy > 0.45) & (yy < 0.55)] = (1.0, 0.1, 0.6)

for d, with_emit in ((MAP_DIR, True), (MAP_DIR_NOEMIT, False)):
    save_png(os.path.join(d, "dummy_BaseColor.png"), base)
    save_png(os.path.join(d, "dummy_Roughness.png"), grey(0.3 + 0.5 * checker), mode="BW")
    save_png(os.path.join(d, "dummy_Metallic.png"), grey(checker), mode="BW")
    save_png(os.path.join(d, "dummy_AO.png"), grey(0.4 + 0.6 * radial), mode="BW")
    save_png(os.path.join(d, "dummy_Normal_OpenGL.png"), normal)
    save_png(os.path.join(d, "dummy_Height.png"), grey(0.5 + 0.3 * (radial - 0.5)), depth="16", mode="BW")
    if with_emit:
        save_png(os.path.join(d, "dummy_Emissive.png"), emiss)
print("maps:", sorted(os.listdir(MAP_DIR)))

# ------------------------------------------------------------------ scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.mesh.primitive_cube_add(size=2)
cube = bpy.context.active_object
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project()
bpy.ops.object.mode_set(mode="OBJECT")
# pre-existing slots that must be replaced
cube.data.materials.append(bpy.data.materials.new("OldA"))
cube.data.materials.append(bpy.data.materials.new("OldB"))
assert len(cube.data.uv_layers) == 1

mat = apply_pigment_material(cube, MAP_DIR, "dummy", emission_strength=8.0, use_height=True, height_scale=0.02)

# ------------------------------------------------------------------ checks


def link_list(m):
    return sorted(
        f"{l.from_node.bl_idname}[{l.from_node.label or l.from_node.name}].{l.from_socket.identifier} -> "
        f"{l.to_node.bl_idname}[{l.to_node.label or l.to_node.name}].{l.to_socket.identifier}"
        for l in m.node_tree.links
    )


def has_link(m, from_label, to_node_type, to_name):
    for l in m.node_tree.links:
        fn = l.from_node
        if (fn.label == from_label or fn.bl_idname == from_label) and l.to_node.bl_idname == to_node_type and \
                (l.to_socket.name == to_name or l.to_socket.identifier == to_name):
            return True
    return False


print("\nLinks in", mat.name)
for s in link_list(mat):
    print("  ", s)

P = "ShaderNodeBsdfPrincipled"
assert mat.name == "Pigment_dummy"
assert [m.name for m in cube.data.materials] == ["Pigment_dummy"], [m.name for m in cube.data.materials]
assert has_link(mat, "AO Multiply", P, "Base Color")
assert has_link(mat, "Pigment BaseColor", "ShaderNodeMix", "A_Color")
assert has_link(mat, "Pigment AO", "ShaderNodeMix", "B_Color")
assert has_link(mat, "Pigment Roughness", P, "Roughness")
assert has_link(mat, "Pigment Metallic", P, "Metallic")
assert has_link(mat, "Pigment Emissive", P, "Emission Color")
assert has_link(mat, "Pigment Normal", "ShaderNodeNormalMap", "Color")
assert has_link(mat, "ShaderNodeNormalMap", "ShaderNodeBump", "Normal")
assert has_link(mat, "Pigment Height", "ShaderNodeBump", "Height")
assert has_link(mat, "ShaderNodeBump", P, "Normal")
assert has_link(mat, "ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial", "Surface")
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
assert abs(bsdf.inputs["Emission Strength"].default_value - 8.0) < 1e-6
mix = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeMix")
assert mix.data_type == "RGBA" and mix.blend_type == "MULTIPLY"
nm = next(n for n in mat.node_tree.nodes if n.type == "NORMAL_MAP")
assert nm.space == "TANGENT" and nm.uv_map == cube.data.uv_layers[0].name
for n in mat.node_tree.nodes:
    if n.type == "TEX_IMAGE":
        print(f"   {n.label:20s} colorspace={n.image.colorspace_settings.name}")
        expect_color = n.label in ("Pigment BaseColor", "Pigment Emissive")
        assert (n.image.colorspace_settings.name == "sRGB") == expect_color or (
            not expect_color and n.image.colorspace_settings.is_data), n.label

# variant: no emissive file, no height -> no emission link, no bump node
cube2_mesh = cube.data.copy()
cube2 = bpy.data.objects.new("Cube2", cube2_mesh)
bpy.context.scene.collection.objects.link(cube2)
cube2.location = (3.5, 0, 0)
mat2 = apply_pigment_material(cube2, MAP_DIR_NOEMIT, "dummy", use_height=False)
# same base name -> same material name; rebuilt in place from the no-emit folder
assert not any(l.to_socket.name == "Emission Color" for l in mat2.node_tree.links)
assert not any(n.type == "BUMP" for n in mat2.node_tree.nodes)
assert has_link(mat2, "ShaderNodeNormalMap", P, "Normal")
print("\nno-emissive/no-height variant OK:", len(mat2.node_tree.links), "links")

# rebuild the full material for the render
mat = apply_pigment_material(cube, MAP_DIR, "dummy", emission_strength=8.0, use_height=True, height_scale=0.02)
cube2.data.materials.clear()
cube2.data.materials.append(mat)
print("ALL ASSERTS PASSED")

# ------------------------------------------------------------------ render
scene = bpy.context.scene
cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (5.5, -7.5, 4.5)
cam.rotation_euler = (math.radians(65), 0, math.radians(32))
scene.camera = cam
ld = bpy.data.lights.new("Sun", "SUN")
ld.energy = 3.0
lo = bpy.data.objects.new("Sun", ld)
lo.rotation_euler = (math.radians(50), 0, math.radians(30))
scene.collection.objects.link(lo)

for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        scene.render.engine = eng
        break
    except TypeError:
        continue
print("engine:", scene.render.engine)
scene.render.resolution_x = 320
scene.render.resolution_y = 200
scene.render.resolution_percentage = 100
try:
    scene.eevee.taa_render_samples = 8
except AttributeError:
    pass
s = scene.render.image_settings
s.file_format = "PNG"
s.color_mode = "RGBA"
s.color_depth = "8"
out = os.path.join(OUT_DIR, "importer_test.png")
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
assert os.path.isfile(out), out
print("RENDERED:", out)
sys.stdout.flush()
