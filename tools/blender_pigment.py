"""Apply Pigment's exported texture set to a Blender object (Blender 5.2, bpy).

Thin compatibility wrapper over the Pigment Bridge add-on's shared module
(tools/blender_addon/pigment_bridge/core.py), which does the real work. The
add-on itself adds a UI panel, live reload, variants and mesh import; see
docs/agents/blender-bridge/NOTES.md.

Pigment's "separate" export preset writes, for base name N:
    N_BaseColor.png        sRGB
    N_Roughness.png        L8   (Non-Color)
    N_Metallic.png         L8   (Non-Color)
    N_AO.png               L8   (Non-Color)
    N_Normal_OpenGL.png    tangent space, OpenGL (+Y up), which Blender expects natively
    N_Height.png           L16, 0.5 = neutral (Non-Color)
    N_Emissive.png         sRGB RGB, black = no emission (optional)
    N_Opacity.png          L8 alpha, 255 = solid, 0 = cut away (only when not solid)
    N_Transmission.png     L8, 255 = clear glass (only when the material has any)
    material.json          sidecar: maps, emissive_scale, normal convention, resolution, project
Other presets (unreal/unity/godot: packed ORM, DirectX normals, opacity in
the base colour's alpha...) work too.

Opacity drives the Principled BSDF's Alpha (cut-outs, partly see-through
glass) and Transmission its Transmission Weight (refracting glass). The
material is then switched to a see-through render method for EEVEE; Cycles
needs no settings (`configure_see_through`).

Usage inside Blender:
    exec(open(r".../tools/blender_pigment.py").read())
    apply_pigment_material(bpy.data.objects["Barrel"], r"C:/exports/barrel", "barrel")
or import it as a module if tools/ is on sys.path.
"""
import os
import sys

import bpy

__all__ = ["apply_pigment_material", "configure_see_through", "PIGMENT_MAPS", "pigment_core"]

# key -> (file suffix, is_color) for the "separate" preset (kept for scripts that read it)
PIGMENT_MAPS = {
    "BaseColor": ("_BaseColor.png", True),
    "Roughness": ("_Roughness.png", False),
    "Metallic": ("_Metallic.png", False),
    "AO": ("_AO.png", False),
    "Normal": ("_Normal_OpenGL.png", False),
    "Height": ("_Height.png", False),
    "Emissive": ("_Emissive.png", True),
    "Opacity": ("_Opacity.png", False),
    "Transmission": ("_Transmission.png", False),
}


def _addon_dir():
    """tools/blender_addon, found from this file, the working dir, the .blend's folder or $PIGMENT_REPO."""
    cands = []
    f = globals().get("__file__")
    if f:
        cands.append(os.path.join(os.path.dirname(os.path.abspath(f)), "blender_addon"))
    if os.environ.get("PIGMENT_REPO"):
        cands.append(os.path.join(os.environ["PIGMENT_REPO"], "tools", "blender_addon"))
    cands.append(os.path.join(os.getcwd(), "tools", "blender_addon"))
    d = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
    while d and os.path.dirname(d) != d:
        cands.append(os.path.join(d, "tools", "blender_addon"))
        d = os.path.dirname(d)
    for c in cands:
        if os.path.isfile(os.path.join(c, "pigment_bridge", "core.py")):
            return c
    return None


def _load_core():
    try:  # installed as an extension or legacy add-on
        import importlib
        for mod in list(sys.modules):
            if mod.endswith("pigment_bridge.core"):
                return sys.modules[mod]
        return importlib.import_module("pigment_bridge.core")
    except ImportError:
        pass
    d = _addon_dir()
    if d is None:
        raise ImportError("Pigment Bridge core not found: run from the repo root, set $PIGMENT_REPO, or install "
                          "tools/blender_addon/pigment_bridge as an add-on")
    if d not in sys.path:
        sys.path.insert(0, d)
    from pigment_bridge import core
    return core


pigment_core = _load_core()
configure_see_through = pigment_core.configure_see_through


def apply_pigment_material(obj, folder, name, emission_strength=None, use_height=False, height_scale=0.01):
    """Build material "Pigment_<name>" from Pigment's exported maps and assign it to obj.

    Replaces all of obj's material slots with the new material (rebuilt in place
    if it exists). `emission_strength=None` uses the exported emissive_scale
    from material.json (8.0 when there is no sidecar); a number overrides it.
    Returns the material.
    """
    core = pigment_core
    if obj is None or obj.type != "MESH":
        raise TypeError("apply_pigment_material: obj must be a mesh object")
    spec = core.discover(folder, name)
    opts = {
        "height_mode": "BUMP" if use_height else "NONE",
        "bump_distance": float(height_scale),
        "emission_override": 0.0,
    }
    if emission_strength is not None:
        opts["emission_override"] = float(emission_strength)
    elif not spec.get("sidecar") and not spec.get("variant_json"):
        opts["emission_override"] = 8.0  # legacy default for exports without material.json / variant.json
    uv = obj.data.uv_layers[0].name if len(obj.data.uv_layers) else ""
    mat_name = f"Pigment_{name}"
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    core.build_material(spec, mat, opts, uv)
    core.assign(obj, mat)
    obj["pigment_source"] = spec["folder"]
    obj["pigment_folder"] = spec["folder"]
    return mat
