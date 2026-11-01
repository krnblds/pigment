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
MAP_DIR_GLASS = os.path.join(OUT_DIR, "maps_glass")
MAP_DIR_COAT = os.path.join(OUT_DIR, "maps_coat")
os.makedirs(MAP_DIR_COAT, exist_ok=True)
os.makedirs(MAP_DIR, exist_ok=True)
os.makedirs(MAP_DIR_GLASS, exist_ok=True)
os.makedirs(MAP_DIR_NOEMIT, exist_ok=True)

ns = {"__name__": "blender_pigment", "__file__": os.path.join(HERE, "blender_pigment.py")}
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
# glass + cut-out set: opacity grid (holes) and transmission on half of it
for k in ("BaseColor", "Roughness"):
    src = os.path.join(MAP_DIR, f"dummy_{k}.png")
    open(os.path.join(MAP_DIR_GLASS, f"dummy_{k}.png"), "wb").write(open(src, "rb").read())
holes = (((xx * 16) % 1 > 0.25) & ((yy * 16) % 1 > 0.25)).astype(np.float32)
save_png(os.path.join(MAP_DIR_GLASS, "dummy_Opacity.png"), grey(np.where(xx < 0.5, 1.0 - holes, 0.35)), mode="BW")
save_png(os.path.join(MAP_DIR_GLASS, "dummy_Transmission.png"), grey((xx >= 0.5).astype(np.float32)), mode="BW")
# car paint set: clearcoat everywhere, rougher coat on one half, flake on the other
for k in ("BaseColor", "Roughness", "Metallic", "Normal_OpenGL"):
    src = os.path.join(MAP_DIR, f"dummy_{k}.png")
    open(os.path.join(MAP_DIR_COAT, f"dummy_{k}.png"), "wb").write(open(src, "rb").read())
save_png(os.path.join(MAP_DIR_COAT, "dummy_Coat.png"), grey(np.ones_like(xx, dtype=np.float32)), mode="BW")
save_png(os.path.join(MAP_DIR_COAT, "dummy_CoatRoughness.png"), grey(np.where(xx < 0.5, 0.03, 0.4).astype(np.float32)), mode="BW")
save_png(os.path.join(MAP_DIR_COAT, "dummy_Flake.png"), grey((xx >= 0.5).astype(np.float32) * 0.8), mode="BW")
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

# no opacity / transmission maps -> nothing wired to Alpha / Transmission
assert not any(l.to_socket.name in ("Alpha", "Transmission Weight") for l in mat2.node_tree.links)

# glass / cut-out variant: Opacity -> Alpha, Transmission -> Transmission Weight
cube3 = bpy.data.objects.new("Cube3", cube.data.copy())
bpy.context.scene.collection.objects.link(cube3)
cube3.location = (-3.5, 0, 0)
mat3 = apply_pigment_material(cube3, MAP_DIR_GLASS, "dummy")
assert has_link(mat3, "Pigment Opacity", P, "Alpha"), link_list(mat3)
assert has_link(mat3, "Pigment Transmission", P, "Transmission Weight"), link_list(mat3)
if hasattr(mat3, "surface_render_method"):
    assert mat3.surface_render_method == "DITHERED", mat3.surface_render_method
if hasattr(mat3, "use_raytrace_refraction"):
    assert mat3.use_raytrace_refraction
for n in mat3.node_tree.nodes:
    if n.label in ("Pigment Opacity", "Pigment Transmission"):
        assert n.image.colorspace_settings.name != "sRGB" or n.image.colorspace_settings.is_data, n.label
print("glass/cut-out variant OK")

# no coat maps -> nothing wired to the coat
assert not any(l.to_socket.name.startswith("Coat") for l in mat2.node_tree.links)
assert not any(l.to_socket.name.startswith("Coat") for l in mat3.node_tree.links)

# car paint: Coat -> Coat Weight, CoatRoughness -> Coat Roughness, painted
# normal -> Coat Normal, flake jitters the base normal only
cube4 = bpy.data.objects.new("Cube4", cube.data.copy())
bpy.context.scene.collection.objects.link(cube4)
cube4.location = (0, 3.5, 0)
mat4 = apply_pigment_material(cube4, MAP_DIR_COAT, "dummy")
assert has_link(mat4, "Pigment Coat", P, "Coat Weight"), link_list(mat4)
assert has_link(mat4, "Pigment CoatRoughness", P, "Coat Roughness"), link_list(mat4)
assert has_link(mat4, "ShaderNodeNormalMap", P, "Coat Normal"), link_list(mat4)
assert has_link(mat4, "Pigment Flake normal", P, "Normal"), link_list(mat4)
assert has_link(mat4, "Pigment Flake", "ShaderNodeMath", "Value"), link_list(mat4)
for n in mat4.node_tree.nodes:
    if n.label in ("Pigment Coat", "Pigment CoatRoughness", "Pigment Flake"):
        assert n.image.colorspace_settings.name != "sRGB" or n.image.colorspace_settings.is_data, n.label
# flake=False (before a glTF export): the normal map goes straight to Normal
cube5 = bpy.data.objects.new("Cube5", cube.data.copy())
bpy.context.scene.collection.objects.link(cube5)
cube5.location = (0, 7.0, 0)
mat5 = apply_pigment_material(cube5, MAP_DIR_COAT, "dummy", flake=False)
assert mat5 is mat4  # same material name, rebuilt in place
assert has_link(mat5, "ShaderNodeNormalMap", P, "Normal"), link_list(mat5)
assert not any(n.label == "Pigment Flake normal" for n in mat5.node_tree.nodes)
# glTF: the clearcoat survives as KHR_materials_clearcoat
import json
import struct
glb = os.path.join(OUT_DIR, "coat_test.glb")
for o in bpy.context.scene.objects:
    o.select_set(o.name == "Cube5")
bpy.context.view_layer.objects.active = cube5
bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True)
with open(glb, "rb") as fh:
    data = fh.read()
jlen = struct.unpack_from("<I", data, 12)[0]
gj = json.loads(data[20:20 + jlen])
assert "KHR_materials_clearcoat" in gj.get("extensionsUsed", []), gj.get("extensionsUsed")
cc = gj["materials"][0]["extensions"]["KHR_materials_clearcoat"]
print("glTF clearcoat:", cc)
assert "clearcoatTexture" in cc or cc.get("clearcoatFactor", 0) > 0, cc
print("clearcoat variant OK")
cube5.data.materials.clear()
# leave the flaked coat material on cube4 for the render
mat4 = apply_pigment_material(cube4, MAP_DIR_COAT, "dummy")

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
