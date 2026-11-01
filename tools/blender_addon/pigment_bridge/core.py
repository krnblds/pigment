"""Pigment Bridge core: everything the add-on does, without any UI.

Usable on its own (no add-on registration needed), which is how
tools/blender_pigment.py uses it:

    import sys; sys.path.insert(0, r"<repo>/tools/blender_addon")
    from pigment_bridge import core
    core.link_objects([obj], r"C:/exports/barrel")          # build + assign
    core.check_reload()                                      # pick up re-exports

A Pigment texture folder holds `<name>_<Suffix>.png` maps and, since the
bridge, a `material.json` sidecar describing them (see
crates/core/src/bridge.rs). Without a sidecar the maps are recognised by
suffix for every Pigment export preset (separate, unreal, unity, godot).

State lives in ID custom properties so it survives save/load and works
without the add-on: materials carry `pigment_folder`, `pigment_name`,
`pigment_options`, `pigment_signature`, the emission driver inputs, and
objects carry `pigment_source` / `pigment_folder` / `pigment_seed`.
"""
import json
import os
import random
import shutil
import subprocess
import time

import bpy

SIDECAR = "material.json"
VARIANT_SEP = "__"

HEIGHT_MODES = ("NONE", "BUMP", "DISPLACEMENT")
DEFAULT_OPTIONS = {
    "height_mode": "BUMP",       # NONE | BUMP | DISPLACEMENT (true displacement + bump)
    "bump_distance": 0.01,       # metres for a full 0..1 height swing
    "bump_strength": 1.0,
    "displacement_scale": 0.02,  # metres for a full 0..1 height swing
    "ao_strength": 0.5,          # multiply base colour by AO (0 = off)
    "emission_mult": 1.0,        # on top of Pigment's emissive_scale
    "emission_override": 0.0,    # > 0: absolute emission strength (legacy API)
    "flake_normal": True,        # metallic flake map -> per-flake normal jitter on the base (not the coat)
    "flake_scale": 2500.0,       # flake cells per metre (object space): 2500 = 0.4 mm flakes
}

# Fallback when there is no sidecar: suffix -> (sources, colorspace), for every
# preset in crates/core/src/export.rs. Longest suffix wins.
RGB = ["red", "green", "blue"]
NRM_GL = ["normal_x", "normal_y", "normal_z"]
NRM_DX = ["normal_x", "normal_y_flipped", "normal_z"]
EMI = ["emissive_r", "emissive_g", "emissive_b"]
SUFFIXES = {
    "BaseColor": (RGB, "srgb"), "Albedo": (RGB, "srgb"), "albedo": (RGB, "srgb"),
    "Roughness": (["roughness"], "non-color"),
    "Metallic": (["metallic"], "non-color"),
    "AO": (["ao"], "non-color"), "Occlusion": (["ao"], "non-color"),
    "OcclusionRoughnessMetallic": (["ao", "roughness", "metallic"], "non-color"),
    "orm": (["ao", "roughness", "metallic"], "non-color"),
    "MetallicSmoothness": (["metallic", "metallic", "metallic", "smoothness"], "non-color"),
    "Normal_OpenGL": (NRM_GL, "non-color"), "normal": (NRM_GL, "non-color"),
    "Normal": (None, "non-color"),  # OpenGL (unity) or DirectX (unreal): decided per folder
    "Height": (["height"], "non-color"), "height": (["height"], "non-color"),
    "Emissive": (EMI, "srgb"), "Emission": (EMI, "srgb"), "emission": (EMI, "srgb"),
    "Opacity": (["opacity"], "non-color"), "Transmission": (["transmission"], "non-color"),
    "Coat": (["coat"], "non-color"), "CoatRoughness": (["coat_roughness"], "non-color"),
    "Flake": (["flake"], "non-color"),
}

# label of the image node by the channel a map carries (kept stable: scripts and
# tests look nodes up by these labels)
CHANNEL_LABEL = {"base_color": "BaseColor", "roughness": "Roughness", "metallic": "Metallic", "ao": "AO",
                 "normal": "Normal", "height": "Height", "emissive": "Emissive",
                 "opacity": "Opacity", "transmission": "Transmission",
                 "coat": "Coat", "coat_roughness": "CoatRoughness", "flake": "Flake"}
SOURCE_CHANNEL = {"red": "base_color", "green": "base_color", "blue": "base_color", "roughness": "roughness",
                  "smoothness": "roughness", "metallic": "metallic", "ao": "ao", "height": "height",
                  "normal_x": "normal", "normal_y": "normal", "normal_y_flipped": "normal", "normal_z": "normal",
                  "emissive_r": "emissive", "emissive_g": "emissive", "emissive_b": "emissive",
                  "opacity": "opacity", "transmission": "transmission",
                  "coat": "coat", "coat_roughness": "coat_roughness", "flake": "flake"}


# ------------------------------------------------------------------ discovery

def _abs(p):
    return os.path.normpath(os.path.abspath(bpy.path.abspath(p) if p.startswith("//") else p))


def read_sidecar(folder):
    path = os.path.join(folder, SIDECAR)
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc.get("materials"), dict):
            return doc
    except (OSError, ValueError):
        pass
    return None


def _scan_suffixes(folder):
    """{base: {suffix: path}} for PNGs named <base>_<known suffix>.png."""
    out = {}
    try:
        files = sorted(os.listdir(folder))
    except OSError:
        return out
    for f in files:
        if not f.lower().endswith(".png"):
            continue
        stem = f[:-4]
        best = None
        for suf in SUFFIXES:
            if stem.endswith("_" + suf) and (best is None or len(suf) > len(best)):
                best = suf
        if best:
            out.setdefault(stem[: -len(best) - 1], {})[best] = os.path.join(folder, f)
    return out


def list_materials(folder):
    """Base names of the texture sets in a folder (foliage card sets excluded,
    see `foliage_entries`)."""
    sc = read_sidecar(folder)
    names = set(sc["materials"]) if sc else set()
    foliage = set(foliage_entries(folder))
    return sorted((names | set(_scan_suffixes(folder))) - foliage)


# ------------------------------------------------------------------ foliage

def foliage_entries(folder):
    """{name: entry} of the foliage card sets exported next to the textures
    (Pigment export_foliage / send_to_blender: kind "foliage")."""
    sc = read_sidecar(folder)
    if not sc:
        return {}
    return {k: v for k, v in sc["materials"].items() if isinstance(v, dict) and v.get("kind") == "foliage"}


def build_foliage_material(folder, entry, mat=None, translucency=0.8, alpha_clip=None):
    """Foliage card material: BaseColorAlpha (colour + alpha cut-out), OpenGL
    normal map, roughness, and light through the leaves from the
    Translucency map (Translucent BSDF added to the Principled BSDF), mixed
    with Transparent by the alpha. Two-sided, alpha-clipped (Cycles reads the
    tree; EEVEE uses dithered / clip)."""
    maps = entry.get("maps", {})
    name = entry.get("name", "foliage")
    mat = mat or bpy.data.materials.get(f"PigmentFoliage_{name}") or bpy.data.materials.new(f"PigmentFoliage_{name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 200)
    trans = nodes.new("ShaderNodeBsdfTranslucent")
    trans.location = (300, -250)
    add = nodes.new("ShaderNodeAddShader")
    add.location = (550, 0)
    transp = nodes.new("ShaderNodeBsdfTransparent")
    transp.location = (550, 200)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (720, 0)

    def img(role, is_color, x, y):
        f = maps.get(role)
        if not f:
            return None
        path = os.path.join(folder, f)
        if not os.path.isfile(path):
            return None
        n = nodes.new("ShaderNodeTexImage")
        n.location = (x, y)
        n.image = load_image(path, is_color)
        n.interpolation = "Linear"
        return n

    col = img("base_color_alpha", True, -500, 300)
    if col is not None:
        col.image.alpha_mode = "STRAIGHT"
        links.new(col.outputs["Color"], sock(bsdf.inputs, "Base Color"))
        alpha_out = col.outputs["Alpha"]
        if alpha_clip:
            # hard cut-out: alpha > clip
            g = nodes.new("ShaderNodeMath")
            g.operation = "GREATER_THAN"
            g.inputs[1].default_value = float(alpha_clip)
            g.location = (-150, 450)
            links.new(alpha_out, g.inputs[0])
            alpha_out = g.outputs[0]
        links.new(alpha_out, mix.inputs[0])
    else:
        mix.inputs[0].default_value = 1.0
    rough = img("roughness", False, -500, 0)
    if rough is not None:
        links.new(rough.outputs["Color"], sock(bsdf.inputs, "Roughness"))
    nrm = img("normal", False, -500, -250)
    if nrm is not None:
        nm = nodes.new("ShaderNodeNormalMap")
        nm.location = (-150, -250)
        nm.inputs["Strength"].default_value = 0.6
        links.new(nrm.outputs["Color"], nm.inputs["Color"])
        links.new(nm.outputs["Normal"], sock(bsdf.inputs, "Normal"))
        links.new(nm.outputs["Normal"], trans.inputs["Normal"])
    tr = img("translucency", True, -500, -500)
    if tr is not None:
        k = nodes.new("ShaderNodeMixRGB") if hasattr(bpy.types, "ShaderNodeMixRGB") else None
        if k is not None:
            k.blend_type = "MULTIPLY"
            k.inputs[0].default_value = 1.0
            k.inputs[2].default_value = (translucency, translucency, translucency, 1.0)
            k.location = (-150, -500)
            links.new(tr.outputs["Color"], k.inputs[1])
            links.new(k.outputs[0], trans.inputs["Color"])
        else:
            links.new(tr.outputs["Color"], trans.inputs["Color"])
    else:
        trans.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    spec = input_socket(bsdf, "Specular IOR Level", "Specular", kind="VALUE")
    if spec is not None:
        spec.default_value = 0.35
    links.new(bsdf.outputs[0], add.inputs[0])
    links.new(trans.outputs[0], add.inputs[1])
    links.new(transp.outputs[0], mix.inputs[1])
    links.new(add.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    configure_see_through(mat, alpha=True)
    _set_attr(mat, "use_backface_culling", False)
    _set_enum(mat, "blend_method", "CLIP", "HASHED")
    mat["pigment_foliage"] = name
    mat["pigment_folder"] = folder
    return mat


def import_foliage(folder, name=None, collection=None, translucency=0.8):
    """Import the foliage card glb(s) Pigment exported into `folder` and give
    them the foliage material. Returns the new objects."""
    out = []
    for key, entry in foliage_entries(folder).items():
        if name and key != name:
            continue
        path = os.path.join(folder, entry.get("mesh", key + ".glb"))
        if not os.path.isfile(path):
            continue
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
        mat = build_foliage_material(folder, entry, translucency=translucency)
        for o in new:
            assign(o, mat)
            o["pigment_foliage"] = key
            if collection is not None and o.name not in collection.objects:
                for c in list(o.users_collection):
                    c.objects.unlink(o)
                collection.objects.link(o)
        out.extend(new)
    return out


def has_maps(folder):
    return bool(list_materials(folder))


def _pick_name(folder, names, name):
    if name:
        if name in names:
            return name
        raise FileNotFoundError(f"no Pigment texture set '{name}' in {folder} (found: {', '.join(names) or 'none'})")
    if not names:
        raise FileNotFoundError(f"no Pigment maps or {SIDECAR} in {folder}")
    if len(names) == 1:
        return names[0]
    # several sets: prefer the one named like the folder (or the asset of a variant folder)
    base = os.path.basename(os.path.normpath(folder))
    for cand in (base, base.split(VARIANT_SEP)[0]):
        if cand in names:
            return cand
    return names[0]


def discover(folder, name=None):
    """Describe the texture set `name` (or the folder's only/main one).

    Returns a dict: name, folder, maps [{path, sources, colorspace, suffix}],
    emissive_scale, has_emission, normal_convention, resolution, project, mesh,
    sidecar (path or None).
    """
    folder = _abs(folder)
    sc = read_sidecar(folder)
    scanned = _scan_suffixes(folder)
    names = sorted(set(sc["materials"] if sc else []) | set(scanned))
    name = _pick_name(folder, names, name)
    entry = (sc or {}).get("materials", {}).get(name) if sc else None
    spec = {"name": name, "folder": folder, "maps": [], "emissive_scale": 1.0, "has_emission": True,
            "normal_convention": "opengl", "resolution": None, "project": None, "mesh": None,
            "sidecar": os.path.join(folder, SIDECAR) if entry else None}
    if entry:
        spec["emissive_scale"] = float(entry.get("emissive_scale", 1.0) or 1.0)
        spec["has_emission"] = bool(entry.get("has_emission", True))
        spec["normal_convention"] = entry.get("normal_convention", "opengl")
        spec["resolution"] = entry.get("resolution")
        for k in ("project", "mesh"):
            v = entry.get(k)
            if v:
                spec[k] = v if os.path.isabs(v) else os.path.normpath(os.path.join(folder, v))
        for m in entry.get("maps", []):
            p = os.path.join(folder, m["file"])
            if os.path.isfile(p):
                spec["maps"].append({"path": p, "sources": list(m["sources"]), "colorspace": m.get("colorspace", "non-color"),
                                     "suffix": m.get("suffix", "")})
    else:
        # no sidecar: an export_variants folder still has variant.json with the
        # emission map's scale (it is normalised per variant)
        try:
            with open(os.path.join(folder, "variant.json"), encoding="utf-8") as fh:
                vj = json.load(fh)
            if vj.get("asset", name) == name and vj.get("emissive_scale"):
                spec["emissive_scale"] = float(vj["emissive_scale"])
                spec["variant_json"] = os.path.join(folder, "variant.json")
        except (OSError, ValueError, TypeError):
            pass
        found = scanned.get(name, {})
        directx = any(s in found for s in ("OcclusionRoughnessMetallic",))
        for suf, path in sorted(found.items()):
            sources, cs = SUFFIXES[suf]
            if sources is None:
                sources = NRM_DX if directx else NRM_GL
            spec["maps"].append({"path": path, "sources": list(sources), "colorspace": cs, "suffix": suf})
        if any(m["sources"] == NRM_DX for m in spec["maps"]):
            spec["normal_convention"] = "directx"
    if not spec["has_emission"]:
        spec["maps"] = [m for m in spec["maps"] if not set(m["sources"]) <= set(EMI)]
    if not spec["maps"]:
        raise FileNotFoundError(f"texture set '{name}' in {folder} has no map files")
    return spec


def channels(spec):
    out = []
    for m in spec["maps"]:
        for s in m["sources"]:
            c = SOURCE_CHANNEL.get(s)
            if c and c not in out:
                out.append(c)
    return out


# ------------------------------------------------------------------ variants

def split_variant(folder):
    """('building_a', 'red') for .../building_a__red; (basename, None) otherwise."""
    base = os.path.basename(os.path.normpath(folder))
    if VARIANT_SEP in base:
        a, v = base.split(VARIANT_SEP, 1)
        return a, v
    return base, None


def variant_folders(source):
    """All `<asset>__<variant>` folders for a source folder.

    `source` may be one variant (`.../crate__red`: its siblings are used), the
    plain asset path (`.../crate`, which need not exist: `crate__*` siblings),
    or a folder containing variant subfolders. Only folders with maps count.
    """
    source = _abs(source)
    asset, variant = split_variant(source)
    parent = os.path.dirname(source)
    cands = []
    if variant is None and os.path.isdir(source):
        cands = [os.path.join(source, d) for d in sorted(os.listdir(source)) if VARIANT_SEP in d]
    if not cands and os.path.isdir(parent):
        cands = [os.path.join(parent, d) for d in sorted(os.listdir(parent)) if d.startswith(asset + VARIANT_SEP)]
    return [c for c in cands if os.path.isdir(c) and has_maps(c)]


def pick_variant(obj_name, source, seed=0):
    """Deterministic random variant folder for an object (same name + seed -> same pick)."""
    vs = variant_folders(source)
    if not vs:
        return _abs(source)
    return random.Random(f"{seed}:{obj_name}").choice(vs)


# ------------------------------------------------------------------ projects

def is_project(path):
    return os.path.isfile(os.path.join(_abs(path), "project.json"))


def project_export_dir(project):
    """Where a linked .pigment project is exported for Blender: a sibling `<stem>_blender` folder."""
    project = _abs(project)
    stem = os.path.splitext(os.path.basename(project))[0]
    return os.path.join(os.path.dirname(project), stem + "_blender")


def find_pigment_mcp(hint=""):
    """pigment-mcp executable: explicit hint, $PIGMENT_MCP, the repo's target/release, or PATH."""
    cands = [hint, os.environ.get("PIGMENT_MCP", "")]
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.normpath(os.path.join(here, "..", "..", ".."))
    for exe in ("pigment-mcp.exe", "pigment-mcp"):
        cands.append(os.path.join(repo, "target", "release", exe))
    cands.append(shutil.which("pigment-mcp") or "")
    for c in cands:
        if c and os.path.isfile(bpy.path.abspath(c)):
            return bpy.path.abspath(c)
    return None


def export_project(project, out_dir=None, exe=None, name=None, wait=True):
    """Run `pigment-mcp --export-for-blender` for a project. Returns the export dir
    (wait=True) or the Popen (wait=False)."""
    exe = exe or find_pigment_mcp()
    if not exe:
        raise FileNotFoundError("pigment-mcp not found: set it in the add-on preferences or $PIGMENT_MCP")
    project = _abs(project)
    out_dir = out_dir or project_export_dir(project)
    args = [exe, "--export-for-blender", project, out_dir]
    if name:
        args += ["--name", name]
    if not wait:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pigment-mcp export failed: {r.stderr.strip()[-500:]}")
    return out_dir


def project_needs_export(project, out_dir=None):
    project = _abs(project)
    out_dir = out_dir or project_export_dir(project)
    side = os.path.join(out_dir, SIDECAR)
    if not os.path.isfile(side):
        return True
    return _mtime(os.path.join(project, "project.json")) > _mtime(side) + 1e-3 or any(
        _mtime(os.path.join(dp, f)) > _mtime(side) + 1e-3
        for sub in ("layers", "masks") for dp, _, fs in os.walk(os.path.join(project, sub)) for f in fs)


def resolve_source(source, exe=None):
    """A linked source -> a texture folder. Projects are exported on first use."""
    source = _abs(source)
    if is_project(source):
        out = project_export_dir(source)
        if project_needs_export(source, out):
            export_project(source, out, exe)
        return out
    return source


# ------------------------------------------------------------------ node helpers

def _colorspace_names():
    try:
        return [i.identifier for i in bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items]
    except Exception:
        return []


def set_colorspace(img, is_color):
    """Set sRGB / Non-Color, tolerating OCIO-config naming differences."""
    wanted = ("sRGB", "sRGB IEC61966-2.1", "srgb_tx") if is_color else ("Non-Color", "Raw", "Generic Data", "data")
    for name in wanted:
        try:
            img.colorspace_settings.name = name
            return name
        except TypeError:
            continue
    key = "srgb" if is_color else "non-color"
    for name in _colorspace_names():
        if key in name.lower():
            img.colorspace_settings.name = name
            return name
    if not is_color:
        img.colorspace_settings.is_data = True
    return img.colorspace_settings.name


def sock(sockets, *names):
    """Find an enabled socket by name or identifier (first match among names)."""
    for n in names:
        for s in sockets:
            if (s.name == n or s.identifier == n) and getattr(s, "enabled", True):
                return s
    for n in names:
        s = sockets.get(n)
        if s is not None:
            return s
    raise KeyError(f"socket {names} not found in {[s.identifier for s in sockets]}")


def input_socket(node, *names, kind=None):
    """An input socket by name / identifier, else the first enabled one of `kind`
    (socket type, e.g. "VALUE") whose name contains names[0]; None if absent."""
    try:
        return sock(node.inputs, *names)
    except KeyError:
        pass
    key = names[0].lower().split()[0]
    for s in node.inputs:
        if (kind is None or s.type == kind) and key in s.name.lower() and getattr(s, "enabled", True):
            return s
    return None


def _set_enum(obj, prop, *wanted):
    """Set an enum property to the first supported value; ignore if missing."""
    if not hasattr(obj, prop):
        return None
    try:
        items = [i.identifier for i in obj.bl_rna.properties[prop].enum_items]
    except (KeyError, AttributeError):
        items = []
    for w in wanted:
        if not items or w in items:
            try:
                setattr(obj, prop, w)
                return w
            except (TypeError, ValueError):
                continue
    return None


def _set_attr(obj, prop, value):
    if hasattr(obj, prop):
        try:
            setattr(obj, prop, value)
            return True
        except (TypeError, AttributeError, ValueError):
            pass
    return False


def configure_see_through(mat, alpha=True, transmission=False):
    """Material settings for cut-outs / glass (Blender 4.2+ EEVEE Next, 5.x).

    Dithered is the 5.x default render method: it handles alpha cut-outs and
    sorts correctly; refraction is on for transmissive glass (thin slab
    panes). Blender's older blend_method / shadow_method are set only where
    they still exist. Cycles reads the node tree directly.
    """
    if alpha or transmission:
        _set_enum(mat, "surface_render_method", "DITHERED")
        _set_enum(mat, "blend_method", "HASHED", "BLEND")           # pre-4.2
        _set_enum(mat, "shadow_method", "HASHED")                   # pre-4.2
        _set_attr(mat, "use_transparent_shadow", True)
        _set_attr(mat, "use_backface_culling", False)
    if transmission:
        _set_attr(mat, "use_raytrace_refraction", True)             # 4.2+
        _set_attr(mat, "use_screen_refraction", True)               # pre-4.2
        _set_enum(mat, "thickness_mode", "SLAB")                    # window panes are thin
        _set_attr(mat, "use_thickness_from_shadow", False)


def load_image(path, is_color, packed_alpha=False):
    abspath = os.path.abspath(path)
    img = bpy.data.images.load(abspath, check_existing=True)
    if os.path.exists(abspath):
        img.reload()  # pick up a fresh export over an old cached image
    set_colorspace(img, is_color)
    if packed_alpha:
        img.alpha_mode = "CHANNEL_PACKED"
    return img


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def signature(spec):
    """What the material was built from: sidecar + map files with mtimes."""
    files = {m["path"]: _mtime(m["path"]) for m in spec["maps"]}
    side = os.path.join(spec["folder"], SIDECAR)
    return {"sidecar": _mtime(side) if os.path.isfile(side) else 0.0, "files": files}


def options_of(mat):
    opts = dict(DEFAULT_OPTIONS)
    try:
        opts.update(json.loads(mat.get("pigment_options", "{}")))
    except ValueError:
        pass
    return opts


# ------------------------------------------------------------------ material build

def _emission_driver(mat, bsdf):
    """Emission Strength = override if override > 0 else emissive_scale * multiplier."""
    inp = sock(bsdf.inputs, "Emission Strength")
    try:
        inp.driver_remove("default_value")
    except TypeError:
        pass
    fc = inp.driver_add("default_value")
    d = fc.driver
    d.type = "SCRIPTED"
    for var, prop in (("s", "pigment_emissive_scale"), ("k", "pigment_emission_mult"), ("o", "pigment_emission_override")):
        v = d.variables.new()
        v.name = var
        v.type = "SINGLE_PROP"
        v.targets[0].id_type = "MATERIAL"
        v.targets[0].id = mat
        v.targets[0].data_path = f'["{prop}"]'
    d.expression = "o if o > 0 else s * k"  # a simple expression: no Python, no auto-run needed


def emission_strength(mat):
    o = float(mat.get("pigment_emission_override", 0.0))
    return o if o > 0 else float(mat.get("pigment_emissive_scale", 1.0)) * float(mat.get("pigment_emission_mult", 1.0))


def build_material(spec, mat=None, options=None, uv_map=""):
    """(Re)build a material's node tree from a discovered texture set.

    Rebuilding happens in place, so every object sharing the material updates.
    """
    opts = dict(DEFAULT_OPTIONS)
    if mat is not None:
        opts.update(options_of(mat))
    opts.update(options or {})
    if opts["height_mode"] not in HEIGHT_MODES:
        raise ValueError(f"height_mode must be one of {HEIGHT_MODES}")
    if mat is None:
        mat = bpy.data.materials.new(f"Pigment_{spec['name']}")
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    if nt.animation_data:
        nt.animation_data_clear()
    nt.nodes.clear()
    nodes, links = nt.nodes, nt.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (1000, 300)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (600, 300)
    links.new(sock(bsdf.outputs, "BSDF"), sock(out.inputs, "Surface"))
    uvn = nodes.new("ShaderNodeUVMap")
    uvn.location = (-1100, 300)
    uvn.uv_map = uv_map

    # one image node per map; gather a socket per source
    src = {}  # source name -> output socket (float or colour)
    rgb = {}  # "base_color" / "normal" / "emissive" -> colour socket when the map is exactly that triple
    order = {"base_color": 0, "ao": 1, "metallic": 2, "roughness": 3, "emissive": 4, "opacity": 5, "transmission": 6, "normal": 7, "height": 8}
    maps = sorted(spec["maps"], key=lambda m: min(order.get(SOURCE_CHANNEL.get(s, ""), 9) for s in m["sources"]))
    y = 900
    for m in maps:
        chans = [SOURCE_CHANNEL.get(s) for s in m["sources"] if SOURCE_CHANNEL.get(s)]
        if chans == ["height"] and opts["height_mode"] == "NONE":
            continue
        uniq = list(dict.fromkeys(chans))
        label = "Pigment " + (CHANNEL_LABEL[uniq[0]] if len(uniq) == 1 else (m["suffix"] or "Packed"))
        n = nodes.new("ShaderNodeTexImage")
        n.name = n.label = label
        n.image = load_image(m["path"], m["colorspace"] == "srgb", packed_alpha=len(m["sources"]) == 4)
        n.interpolation = "Linear"
        n.location = (-750, y)
        y -= 300
        links.new(sock(uvn.outputs, "UV"), sock(n.inputs, "Vector"))
        color = sock(n.outputs, "Color")
        s = m["sources"]
        if len(s) == 1:
            src.setdefault(s[0], color)
            continue
        if s[:3] == RGB:
            rgb["base_color"] = color
        elif s[:3] == NRM_GL:
            rgb["normal"] = color
        elif s[:3] == EMI:
            rgb["emissive"] = color
        sep = None
        for i, name in enumerate(s):
            if i == 3:
                src.setdefault(name, sock(n.outputs, "Alpha"))
                continue
            if name in RGB or name in EMI or name in ("normal_x", "normal_y", "normal_z") and "normal" in rgb:
                continue
            if sep is None:
                sep = nodes.new("ShaderNodeSeparateColor")
                sep.label = label + " split"
                sep.location = (-450, n.location.y)
                links.new(color, sock(sep.inputs, "Color"))
            src.setdefault(name, sep.outputs[i])

    def link(out_sock, *to):
        links.new(out_sock, sock(bsdf.inputs, *to))

    # base colour (x AO)
    if "base_color" in rgb:
        col = rgb["base_color"]
        if "ao" in src and opts["ao_strength"] > 0:
            mix = nodes.new("ShaderNodeMix")
            mix.name = mix.label = "AO Multiply"
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.clamp_result = True
            mix.location = (-150, 900)
            sock(mix.inputs, "Factor_Float", "Factor").default_value = float(opts["ao_strength"])
            links.new(col, sock(mix.inputs, "A_Color"))
            links.new(src["ao"], sock(mix.inputs, "B_Color"))
            col = sock(mix.outputs, "Result_Color")
        link(col, "Base Color")
    if "metallic" in src:
        link(src["metallic"], "Metallic")
    if "roughness" in src:
        link(src["roughness"], "Roughness")
    elif "smoothness" in src:
        inv = nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.label = "Smoothness to roughness"
        inv.inputs[0].default_value = 1.0
        inv.location = (-150, 500)
        links.new(src["smoothness"], inv.inputs[1])
        link(inv.outputs[0], "Roughness")

    # emission: colour from the map, strength driven by emissive_scale x multiplier
    mat["pigment_emissive_scale"] = float(spec.get("emissive_scale", 1.0))
    mat["pigment_emission_mult"] = float(opts["emission_mult"])
    mat["pigment_emission_override"] = float(opts["emission_override"] or 0.0)
    if "emissive" in rgb:
        link(rgb["emissive"], "Emission Color")
        sock(bsdf.inputs, "Emission Strength").default_value = emission_strength(mat)
        _emission_driver(mat, bsdf)

    # Opacity -> Alpha, Transmission -> Transmission Weight (looked up by
    # name, then by type, so a renamed socket in a later Blender still wires).
    # Opacity may come from its own map or the base colour's alpha (unreal/unity/godot).
    if "opacity" in src:
        a = input_socket(bsdf, "Alpha", kind="VALUE")
        if a is not None:
            links.new(src["opacity"], a)
    if "transmission" in src:
        t = input_socket(bsdf, "Transmission Weight", "Transmission", kind="VALUE")
        if t is not None:
            links.new(src["transmission"], t)
        ior = input_socket(bsdf, "IOR", kind="VALUE")
        if ior is not None:
            ior.default_value = 1.5
    configure_see_through(mat, alpha="opacity" in src, transmission="transmission" in src)

    # Clearcoat: image nodes straight into Coat Weight / Coat Roughness, so the
    # glTF exporter can write KHR_materials_clearcoat.
    if "coat" in src:
        cw = input_socket(bsdf, "Coat Weight", "Coat", kind="VALUE")
        if cw is not None:
            links.new(src["coat"], cw)
        cr = input_socket(bsdf, "Coat Roughness", kind="VALUE")
        if cr is not None:
            if "coat_roughness" in src:
                links.new(src["coat_roughness"], cr)
            else:
                cr.default_value = 0.03
        cior = input_socket(bsdf, "Coat IOR", kind="VALUE")
        if cior is not None:
            cior.default_value = 1.5

    # normal: OpenGL tangent space is Blender's; DirectX needs green flipped
    normal_out = None
    ncol = rgb.get("normal")
    if ncol is None and all(k in src for k in ("normal_x", "normal_y_flipped", "normal_z")):
        comb = nodes.new("ShaderNodeCombineColor")
        comb.label = "DirectX to OpenGL normal"
        comb.location = (-150, 100)
        flip = nodes.new("ShaderNodeMath")
        flip.operation = "SUBTRACT"
        flip.inputs[0].default_value = 1.0
        flip.location = (-300, 0)
        links.new(src["normal_y_flipped"], flip.inputs[1])
        links.new(src["normal_x"], comb.inputs[0])
        links.new(flip.outputs[0], comb.inputs[1])
        links.new(src["normal_z"], comb.inputs[2])
        ncol = sock(comb.outputs, "Color")
    if ncol is not None:
        nm = nodes.new("ShaderNodeNormalMap")
        nm.space = "TANGENT"
        nm.uv_map = uv_map
        nm.location = (100, 100)
        links.new(ncol, sock(nm.inputs, "Color"))
        normal_out = sock(nm.outputs, "Normal")

    # height: bump in the shader, or true displacement (plus bump for fine detail)
    if "height" in src and opts["height_mode"] != "NONE":
        if opts["height_mode"] == "BUMP":
            bump = nodes.new("ShaderNodeBump")
            bump.location = (350, -100)
            sock(bump.inputs, "Strength").default_value = float(opts["bump_strength"])
            sock(bump.inputs, "Distance").default_value = float(opts["bump_distance"])
            links.new(src["height"], sock(bump.inputs, "Height"))
            if normal_out is not None:
                links.new(normal_out, sock(bump.inputs, "Normal"))
            normal_out = sock(bump.outputs, "Normal")
            mat.displacement_method = "BUMP"
        else:
            disp = nodes.new("ShaderNodeDisplacement")
            disp.location = (600, -250)
            disp.space = "OBJECT"
            sock(disp.inputs, "Midlevel").default_value = 0.5
            sock(disp.inputs, "Scale").default_value = float(opts["displacement_scale"])
            links.new(src["height"], sock(disp.inputs, "Height"))
            links.new(sock(disp.outputs, "Displacement"), sock(out.inputs, "Displacement"))
            mat.displacement_method = "BOTH"
    else:
        mat.displacement_method = "BUMP"
    # the coat follows the painted detail (scratches, dents), never the flakes
    if normal_out is not None and "coat" in src:
        cn = input_socket(bsdf, "Coat Normal", kind="VECTOR")
        if cn is not None:
            links.new(normal_out, cn)
    if "flake" in src and opts.get("flake_normal", True):
        normal_out = _flake_normal(nodes, links, src["flake"], normal_out, float(opts.get("flake_scale", 2500.0)))
    if normal_out is not None:
        link(normal_out, "Normal")

    # remember how it was built (for reload / rebuild)
    mat["pigment_folder"] = spec["folder"]
    mat["pigment_name"] = spec["name"]
    mat["pigment_options"] = json.dumps(opts)
    mat["pigment_signature"] = json.dumps(signature(spec))
    mat["pigment_channels"] = ",".join(channels(spec))
    if spec.get("project"):
        mat["pigment_project"] = spec["project"]
    if spec.get("resolution"):
        mat["pigment_resolution"] = int(spec["resolution"])
    _seen[mat.name] = signature(spec)
    mat.update_tag()  # re-evaluate the emission driver
    return mat


def _flake_normal(nodes, links, flake, normal_in, scale):
    """Metallic flake: jitter the base normal per Voronoi cell (object space),
    by up to 0.45 x the flake map. Returns the new normal socket."""
    tc = nodes.new("ShaderNodeTexCoord")
    tc.location = (-450, -600)
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.name = vor.label = "Pigment Flake cells"
    vor.location = (-250, -600)
    sock(vor.inputs, "Scale").default_value = scale
    links.new(sock(tc.outputs, "Object"), sock(vor.inputs, "Vector"))
    # random cell colour 0..1 -> direction -1..1
    to_dir = nodes.new("ShaderNodeVectorMath")
    to_dir.operation = "MULTIPLY_ADD"
    to_dir.location = (-50, -600)
    links.new(sock(vor.outputs, "Color"), to_dir.inputs[0])
    to_dir.inputs[1].default_value = (2.0, 2.0, 2.0)
    to_dir.inputs[2].default_value = (-1.0, -1.0, -1.0)
    amt = nodes.new("ShaderNodeMath")
    amt.operation = "MULTIPLY"
    amt.location = (-50, -800)
    links.new(flake, amt.inputs[0])
    amt.inputs[1].default_value = 0.45
    jit = nodes.new("ShaderNodeVectorMath")
    jit.operation = "SCALE"
    jit.location = (150, -600)
    links.new(to_dir.outputs[0], jit.inputs[0])
    links.new(amt.outputs[0], sock(jit.inputs, "Scale"))
    base = normal_in
    if base is None:
        geo = nodes.new("ShaderNodeNewGeometry")
        geo.location = (150, -850)
        base = sock(geo.outputs, "Normal")
    add = nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    add.location = (330, -600)
    links.new(base, add.inputs[0])
    links.new(jit.outputs[0], add.inputs[1])
    nrm = nodes.new("ShaderNodeVectorMath")
    nrm.operation = "NORMALIZE"
    nrm.name = nrm.label = "Pigment Flake normal"
    nrm.location = (480, -600)
    links.new(add.outputs[0], nrm.inputs[0])
    return nrm.outputs[0]


def find_material(folder, name):
    folder = _abs(folder)
    for m in bpy.data.materials:
        if m.get("pigment_name") == name and m.get("pigment_folder") and _abs(m["pigment_folder"]) == folder:
            return m
    return None


def material_for(spec, options=None, uv_map=""):
    """The shared material for a texture set: reused if one exists, else built."""
    mat = find_material(spec["folder"], spec["name"])
    if mat is not None:
        if options:
            build_material(spec, mat, options, uv_map)
        return mat
    name = f"Pigment_{spec['name']}"
    if name in bpy.data.materials:  # same base name from another folder (e.g. variants)
        name = f"Pigment_{os.path.basename(spec['folder'])}"
    mat = bpy.data.materials.new(name)
    return build_material(spec, mat, options, uv_map)


def assign(obj, mat):
    """Replace all of obj's material slots with mat.

    Linked duplicates (mesh data shared by several objects) get object-level
    slots instead, so each instance can carry its own variant material.
    """
    me = obj.data
    if me.users > 1:
        if len(me.materials) == 0:
            me.materials.append(None)
        for slot in obj.material_slots:
            slot.link = "OBJECT"
            slot.material = mat
        return
    me.materials.clear()
    me.materials.append(mat)
    if len(me.polygons):
        me.polygons.foreach_set("material_index", [0] * len(me.polygons))
        me.update()


def add_displacement_subdivision(obj, levels=2):
    """Adaptive subdivision (Cycles) so true displacement has geometry to move."""
    mod = obj.modifiers.get("Pigment Displacement") or obj.modifiers.new("Pigment Displacement", "SUBSURF")
    mod.subdivision_type = "SIMPLE"
    mod.levels = levels
    mod.render_levels = levels
    if hasattr(mod, "use_adaptive_subdivision"):
        mod.use_adaptive_subdivision = True
    return mod


def link_objects(objects, source, name=None, options=None, variants=False, seed=0, subdivide=False, exe=None):
    """Link mesh objects to a Pigment texture folder or .pigment project.

    Objects resolving to the same texture set share one material. With
    `variants`, each object gets a random `<asset>__<variant>` folder (stable per
    object name and seed). Returns {object name: material}.
    """
    folder = resolve_source(source, exe)
    result = {}
    for obj in objects:
        if obj is None or obj.type != "MESH":
            continue
        f = pick_variant(obj.name, folder, seed) if variants else folder
        spec = discover(f, name)
        uv = obj.data.uv_layers[0].name if len(obj.data.uv_layers) else ""
        mat = material_for(spec, options, uv)
        assign(obj, mat)
        obj["pigment_source"] = _abs(source)
        obj["pigment_folder"] = spec["folder"]
        obj["pigment_variants"] = bool(variants)
        obj["pigment_seed"] = int(seed)
        if subdivide and options_of(mat)["height_mode"] == "DISPLACEMENT":
            add_displacement_subdivision(obj)
        result[obj.name] = mat
    return result


def reroll_variants(objects, seed=None):
    """Pick new random variants for objects linked with variants."""
    out = {}
    for obj in objects:
        if not obj.get("pigment_source"):
            continue
        s = int(obj.get("pigment_seed", 0)) + 1 if seed is None else seed
        mat = obj.active_material
        opts = options_of(mat) if mat is not None and mat.get("pigment_name") else None
        out.update(link_objects([obj], obj["pigment_source"], None, opts, variants=True, seed=s))
    return out


def import_mesh(spec, collection=None):
    """Import the mesh Pigment exported next to the textures (send_to_blender) and
    give it the material. Returns the new objects."""
    path = spec.get("mesh")
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"no exported mesh for '{spec['name']}' (use send_to_blender or export_mesh)")
    before = set(bpy.data.objects)
    if path.lower().endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    mat = material_for(spec)
    for o in new:
        assign(o, mat)
        o["pigment_source"] = spec["folder"]
        o["pigment_folder"] = spec["folder"]
        if collection is not None and o.name not in collection.objects:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            collection.objects.link(o)
    return new


# ------------------------------------------------------------------ live reload

_seen = {}   # material name -> signature last applied
_jobs = {}   # project path -> running export Popen
last_report = {"time": 0.0, "reloaded": [], "rebuilt": [], "exporting": []}


def pigment_materials():
    return [m for m in bpy.data.materials if m.get("pigment_folder") and m.get("pigment_name")]


def check_reload(force=False, watch_projects=False, exe=None):
    """Reload changed maps of every Pigment material. Called by the add-on's timer.

    - a map file's mtime changed -> that image is reloaded in place;
    - the sidecar changed or maps appeared/disappeared -> the material is
      rebuilt in place (keeps its options; picks up a new emissive_scale);
    - watch_projects: a linked .pigment project newer than its export is
      re-exported in the background with pigment-mcp (picked up next tick).
    Returns {"reloaded": [image names], "rebuilt": [material names], "exporting": [...]}.
    """
    reloaded, rebuilt, exporting = [], [], []
    for proj, job in list(_jobs.items()):
        if job.poll() is not None:
            del _jobs[proj]
    for mat in pigment_materials():
        folder = mat["pigment_folder"]
        if watch_projects and mat.get("pigment_project") and is_project(mat["pigment_project"]):
            proj = _abs(mat["pigment_project"])
            if proj not in _jobs and project_needs_export(proj, folder):
                try:
                    _jobs[proj] = export_project(proj, folder, exe, name=mat["pigment_name"], wait=False)
                    exporting.append(proj)
                except FileNotFoundError:
                    pass
        if any(_abs(mat.get("pigment_project", "")) == p for p in _jobs) and mat.get("pigment_project"):
            continue  # mid-export: wait for it
        try:
            spec = discover(folder, mat["pigment_name"])
        except FileNotFoundError:
            continue
        new = signature(spec)
        old = _seen.get(mat.name)
        if old is None:
            try:
                old = json.loads(mat.get("pigment_signature", "{}"))
            except ValueError:
                old = {}
        if not force and new == old:
            continue
        if force or new.get("sidecar") != old.get("sidecar") or set(new["files"]) != set(old.get("files", {})):
            uv = ""
            nm = next((n for n in mat.node_tree.nodes if n.type == "UV_MAP"), None)
            if nm is not None:
                uv = nm.uv_map
            build_material(spec, mat, None, uv)
            rebuilt.append(mat.name)
        else:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image is not None:
                    p = os.path.normpath(bpy.path.abspath(n.image.filepath))
                    if new["files"].get(p) != old.get("files", {}).get(p):
                        n.image.reload()
                        reloaded.append(n.image.name)
            mat["pigment_signature"] = json.dumps(new)
            _seen[mat.name] = new
            mat.node_tree.update_tag()
    last_report.update(time=time.time(), reloaded=reloaded, rebuilt=rebuilt, exporting=exporting)
    return {"reloaded": reloaded, "rebuilt": rebuilt, "exporting": exporting}


def forget_seen():
    """Drop the in-memory cache (on file load: the stored signatures are used)."""
    _seen.clear()


# ------------------------------------------------------------------ city build events (tools/city)
#
# `python -m tools.city build|watch` appends one JSON object per line to a queue file
# (<repo>/.citycache/blender_events.jsonl, or $CITY_BLENDER_EVENTS):
#     {"type": "texture_folder", "path": ".../scenes/town/textures/building_a__soba"}
#     {"type": "mesh", "path": ".../assets/town/building_a.glb"}
# The add-on's timer calls check_city_events(): texture folders rebuild the Pigment materials
# that use them; a mesh event re-imports the glb and swaps the mesh data of every object linked
# to it with link_city_mesh() (materials kept). Only events written after the first check are
# applied (an old queue is not replayed).

_city = {"path": None, "offset": None}


def city_queue_path():
    p = os.environ.get("CITY_BLENDER_EVENTS")
    if p:
        return p
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(os.path.dirname(here)))        # tools/blender_addon/pigment_bridge
    return os.path.join(repo, ".citycache", "blender_events.jsonl")


def _norm(p):
    return os.path.normcase(os.path.normpath(_abs(p)))


def link_city_mesh(obj, path):
    """Mark an object as built from a city glb, so mesh events replace its mesh data."""
    obj["city_source"] = os.path.normpath(_abs(path))


def replace_mesh(path):
    """Re-import `path` and give its geometry to every object linked to it. Returns the object names."""
    want = _norm(path)
    users = [o for o in bpy.data.objects if o.type == "MESH" and o.get("city_source") and _norm(o["city_source"]) == want]
    if not users or not os.path.isfile(path):
        return []
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and not o.name.startswith("Collider")]
    if not meshes:
        for o in new:
            bpy.data.objects.remove(o)
        return []
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    src = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    fresh = src.data
    done = []
    for o in users:
        old = o.data
        me = fresh.copy()
        me.name = old.name
        mats = [s.material for s in o.material_slots]
        links = [s.link for s in o.material_slots]
        o.data = me
        for i, m in enumerate(mats):
            if i < len(o.material_slots):
                o.material_slots[i].link = links[i]
                o.material_slots[i].material = m
            else:
                me.materials.append(m)
        if old.users == 0:
            bpy.data.meshes.remove(old)
        done.append(o.name)
    names = set()
    for o in new:
        try:
            names.add(o.name)
        except ReferenceError:
            pass
    for nm in names:
        ob = bpy.data.objects.get(nm)
        if ob is not None:
            bpy.data.objects.remove(ob)
    if fresh.users == 0:
        bpy.data.meshes.remove(fresh)
    return done


def reload_folder(folder):
    """Rebuild every Pigment material that reads `folder`. Returns the material names."""
    want = _norm(folder)
    out = []
    for mat in pigment_materials():
        if _norm(mat["pigment_folder"]) != want:
            continue
        try:
            spec = discover(mat["pigment_folder"], mat["pigment_name"])
        except FileNotFoundError:
            continue
        uv = ""
        nm = next((n for n in mat.node_tree.nodes if n.type == "UV_MAP"), None)
        if nm is not None:
            uv = nm.uv_map
        build_material(spec, mat, None, uv)
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                n.image.reload()
        _seen[mat.name] = signature(spec)
        out.append(mat.name)
    return out


def check_city_events(path=None):
    """Apply new city build events. Returns {"events", "materials", "objects"}."""
    path = path or city_queue_path()
    if _city["path"] != path:
        _city.update(path=path, offset=None)
    if not os.path.isfile(path):
        if _city["offset"] is None:
            _city["offset"] = 0
        return {"events": 0, "materials": [], "objects": []}
    size = os.path.getsize(path)
    if _city["offset"] is None:          # first look: start at the end
        _city["offset"] = size
        return {"events": 0, "materials": [], "objects": []}
    if size < _city["offset"]:           # truncated / recreated
        _city["offset"] = 0
    if size == _city["offset"]:
        return {"events": 0, "materials": [], "objects": []}
    with open(path, "rb") as f:
        f.seek(_city["offset"])
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return {"events": 0, "materials": [], "objects": []}
    _city["offset"] += end + 1
    mats, objs, n = [], [], 0
    for line in data[:end].decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        n += 1
        if e.get("type") == "texture_folder":
            mats += reload_folder(e["path"])
        elif e.get("type") == "mesh":
            objs += replace_mesh(e["path"])
    last_report.update(time=time.time(), city_events=n, city_materials=mats, city_objects=objs)
    return {"events": n, "materials": mats, "objects": objs}
