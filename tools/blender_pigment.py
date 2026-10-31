"""Apply Pigment's exported texture set to a Blender object (Blender 5.2, bpy).

Pigment's "separate" export preset writes, for base name N:
    N_BaseColor.png        sRGB
    N_Roughness.png        L8   (Non-Color)
    N_Metallic.png         L8   (Non-Color)
    N_AO.png               L8   (Non-Color)
    N_Normal_OpenGL.png    tangent space, OpenGL (+Y up), which Blender expects natively
    N_Height.png           L16, 0.5 = neutral (Non-Color)
    N_Emissive.png         sRGB RGB, black = no emission (optional)

Usage inside Blender:
    exec(open(r".../tools/blender_pigment.py").read())
    apply_pigment_material(bpy.data.objects["Barrel"], r"C:/exports/barrel", "barrel")
or import it as a module if tools/ is on sys.path.
"""
import os

import bpy

__all__ = ["apply_pigment_material", "PIGMENT_MAPS"]

# key -> (file suffix, is_color)
PIGMENT_MAPS = {
    "BaseColor": ("_BaseColor.png", True),
    "Roughness": ("_Roughness.png", False),
    "Metallic": ("_Metallic.png", False),
    "AO": ("_AO.png", False),
    "Normal": ("_Normal_OpenGL.png", False),
    "Height": ("_Height.png", False),
    "Emissive": ("_Emissive.png", True),
}


def _colorspace_names():
    try:
        return [i.identifier for i in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items]
    except Exception:
        return []


def _set_colorspace(img, is_color):
    """Set sRGB / Non-Color, tolerating OCIO-config naming differences."""
    wanted = ("sRGB", "sRGB IEC61966-2.1", "srgb_tx") if is_color else ("Non-Color", "Raw", "Generic Data", "data")
    for name in wanted:
        try:
            img.colorspace_settings.name = name
            return name
        except TypeError:
            continue
    avail = _colorspace_names()
    key = "srgb" if is_color else "non-color"
    for name in avail:
        if key in name.lower():
            img.colorspace_settings.name = name
            return name
    if not is_color:
        img.colorspace_settings.is_data = True
    return img.colorspace_settings.name


def _sock(sockets, *names):
    """Find a socket by name or identifier (first match among names)."""
    for n in names:
        for s in sockets:
            if s.name == n or s.identifier == n:
                if getattr(s, "enabled", True):
                    return s
    for n in names:
        s = sockets.get(n)
        if s is not None:
            return s
    raise KeyError(f"socket {names} not found in {[s.identifier for s in sockets]}")


def _load_image(path, is_color):
    abspath = os.path.abspath(path)
    img = bpy.data.images.load(abspath, check_existing=True)
    if img.filepath and os.path.exists(abspath):
        img.reload()  # pick up a fresh export over an old cached image
    _set_colorspace(img, is_color)
    return img


def apply_pigment_material(obj, folder, name, emission_strength=8.0, use_height=False, height_scale=0.01):
    """Build material "Pigment_<name>" from Pigment's exported maps and assign it to obj.

    Replaces all of obj's material slots with the new material. Returns the material.
    """
    if obj is None or obj.type != "MESH":
        raise TypeError("apply_pigment_material: obj must be a mesh object")

    paths = {k: os.path.join(folder, f"{name}{suf}") for k, (suf, _) in PIGMENT_MAPS.items()}
    have = {k: os.path.isfile(p) for k, p in paths.items()}
    if not any(have.values()):
        raise FileNotFoundError(f"no Pigment maps named '{name}_*.png' found in {folder}")

    mat_name = f"Pigment_{name}"
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    nodes, links = nt.nodes, nt.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 300)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (500, 300)
    links.new(_sock(bsdf.outputs, "BSDF"), _sock(out.inputs, "Surface"))

    # UV: first UV map on the mesh
    uv_layers = obj.data.uv_layers
    uv_name = uv_layers[0].name if len(uv_layers) else ""
    uvn = nodes.new("ShaderNodeUVMap")
    uvn.location = (-900, 300)
    uvn.uv_map = uv_name

    tex = {}
    order = ["BaseColor", "AO", "Metallic", "Roughness", "Emissive", "Normal", "Height"]
    y = 800
    for key in order:
        if not have[key]:
            continue
        if key == "Height" and not use_height:
            continue
        is_color = PIGMENT_MAPS[key][1]
        n = nodes.new("ShaderNodeTexImage")
        n.name = n.label = f"Pigment {key}"
        n.image = _load_image(paths[key], is_color)
        n.interpolation = "Linear"
        n.location = (-550, y)
        y -= 300
        links.new(_sock(uvn.outputs, "UV"), _sock(n.inputs, "Vector"))
        tex[key] = n

    # Base colour (optionally x AO)
    if "BaseColor" in tex:
        col_out = _sock(tex["BaseColor"].outputs, "Color")
        if "AO" in tex:
            mix = nodes.new("ShaderNodeMix")
            mix.name = mix.label = "AO Multiply"
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.clamp_result = True
            mix.location = (-150, 800)
            _sock(mix.inputs, "Factor_Float", "Factor").default_value = 0.5
            links.new(col_out, _sock(mix.inputs, "A_Color"))
            links.new(_sock(tex["AO"].outputs, "Color"), _sock(mix.inputs, "B_Color"))
            col_out = _sock(mix.outputs, "Result_Color")
        links.new(col_out, _sock(bsdf.inputs, "Base Color"))

    if "Metallic" in tex:
        links.new(_sock(tex["Metallic"].outputs, "Color"), _sock(bsdf.inputs, "Metallic"))
    if "Roughness" in tex:
        links.new(_sock(tex["Roughness"].outputs, "Color"), _sock(bsdf.inputs, "Roughness"))

    if "Emissive" in tex:
        links.new(_sock(tex["Emissive"].outputs, "Color"), _sock(bsdf.inputs, "Emission Color"))
        _sock(bsdf.inputs, "Emission Strength").default_value = float(emission_strength)

    normal_out = None
    if "Normal" in tex:
        nm = nodes.new("ShaderNodeNormalMap")
        nm.space = "TANGENT"
        nm.uv_map = uv_name
        nm.location = (-150, tex["Normal"].location.y)
        # OpenGL convention matches Blender: no green flip needed.
        links.new(_sock(tex["Normal"].outputs, "Color"), _sock(nm.inputs, "Color"))
        normal_out = _sock(nm.outputs, "Normal")

    if "Height" in tex:
        bump = nodes.new("ShaderNodeBump")
        bump.location = (150, tex["Height"].location.y)
        _sock(bump.inputs, "Strength").default_value = 1.0
        _sock(bump.inputs, "Distance").default_value = float(height_scale)
        links.new(_sock(tex["Height"].outputs, "Color"), _sock(bump.inputs, "Height"))
        if normal_out is not None:
            links.new(normal_out, _sock(bump.inputs, "Normal"))
        normal_out = _sock(bump.outputs, "Normal")

    if normal_out is not None:
        links.new(normal_out, _sock(bsdf.inputs, "Normal"))

    # replace all material slots with this one
    me = obj.data
    me.materials.clear()
    me.materials.append(mat)
    if len(me.polygons):
        me.polygons.foreach_set("material_index", [0] * len(me.polygons))
        me.update()
    return mat
