"""Blender helpers for the tree kit (import in Blender 5.2; no side effects).

    import sys; sys.path.insert(0, "tools/trees")
    import tree_blender as TB
    idx = TB.load_index(root)
    me = TB.kit_mesh(root, "tree_zelkova_b")       # LOD0 mesh with the kit materials (cached)

The materials read assets/trees/textures/ (committed, packed by build_trees.py):
bark per species (tiling UVs), the leaf atlas (alpha clip, translucency, crown
occlusion from the vertex colour alpha).
"""
import json
import os

import bpy

_IDX = {}


def load_index(root):
    p = os.path.join(root, "assets", "trees", "index.json")
    if p not in _IDX:
        _IDX[p] = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None
    return _IDX[p]


def _img(path, non_color=False):
    name = os.path.basename(path)
    im = bpy.data.images.get(name)
    if im is None:
        im = bpy.data.images.load(path, check_existing=True)
    if non_color:
        try:
            im.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    return im


def _tex(nt, path, loc, non_color=False):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = _img(path, non_color)
    n.location = loc
    return n


def bark_material(root, sp):
    name = f"TreeBark_{sp}"
    m = bpy.data.materials.get(name)
    if m and m.get("tree_kit"):
        return m
    d = os.path.join(root, "assets", "trees", "textures")
    m = bpy.data.materials.new(name)
    m["tree_kit"] = True
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    alb = os.path.join(d, f"bark_{sp}_albedo.jpg")
    if os.path.isfile(alb):
        t = _tex(nt, alb, (-700, 300))
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = "Col"
        attr.location = (-700, 0)
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1.0
        mul.location = (-400, 300)
        nt.links.new(t.outputs["Color"], mul.inputs[6])
        nt.links.new(attr.outputs["Alpha"], mul.inputs[7])
        nt.links.new(mul.outputs[2], bsdf.inputs["Base Color"])
        r = _tex(nt, os.path.join(d, f"bark_{sp}_rough.jpg"), (-700, -250), True)
        nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
        nm = _tex(nt, os.path.join(d, f"bark_{sp}_normal.jpg"), (-700, -550), True)
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-400, -550)
        nmap.inputs["Strength"].default_value = 1.2
        nt.links.new(nm.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        bsdf.inputs["Base Color"].default_value = (0.12, 0.09, 0.07, 1)
    return m


def leaf_material(root, name="TreeLeaves", atlas="leaves"):
    m = bpy.data.materials.get(name)
    if m and m.get("tree_kit"):
        return m
    d = os.path.join(root, "assets", "trees", "textures")
    m = bpy.data.materials.new(name)
    m["tree_kit"] = True
    m.use_nodes = True
    try:
        m.surface_render_method = "DITHERED"
    except Exception:
        pass
    try:
        m.blend_method = "CLIP"
    except Exception:
        pass
    nt = m.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    alb_p = os.path.join(d, f"{atlas}_albedo.png")
    if not os.path.isfile(alb_p):
        bsdf.inputs["Base Color"].default_value = (0.1, 0.25, 0.06, 1)
        return m
    alb = _tex(nt, alb_p, (-900, 300))
    alb.interpolation = "Cubic"
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "Col"
    attr.location = (-900, 0)
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    mul.location = (-600, 300)
    nt.links.new(alb.outputs["Color"], mul.inputs[6])
    nt.links.new(attr.outputs["Alpha"], mul.inputs[7])
    nt.links.new(mul.outputs[2], bsdf.inputs["Base Color"])
    # alpha: hard clip (alpha-tested cards, as in the game)
    gt = nt.nodes.new("ShaderNodeMath")
    gt.operation = "GREATER_THAN"
    gt.inputs[1].default_value = 0.42
    gt.location = (-600, 50)
    nt.links.new(alb.outputs["Alpha"], gt.inputs[0])
    msk = _tex(nt, os.path.join(d, f"{atlas}_mask.jpg"), (-900, -300), True)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.location = (-600, -300)
    nt.links.new(msk.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs[0], bsdf.inputs["Roughness"])
    nm = _tex(nt, os.path.join(d, f"{atlas}_normal.jpg"), (-900, -600), True)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.location = (-600, -600)
    nt.links.new(nm.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    # translucency: leaves glow when lit from behind (street lamps through the crown)
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    tr.location = (-300, -200)
    nt.links.new(mul.outputs[2], tr.inputs["Color"])
    k = nt.nodes.new("ShaderNodeMath")
    k.operation = "MULTIPLY"
    k.inputs[1].default_value = 0.55
    k.location = (-300, -400)
    nt.links.new(sep.outputs[1], k.inputs[0])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (0, 100)
    nt.links.new(k.outputs[0], mix.inputs[0])
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    tp = nt.nodes.new("ShaderNodeBsdfTransparent")
    tp.location = (0, 300)
    cut = nt.nodes.new("ShaderNodeMixShader")
    cut.location = (200, 200)
    nt.links.new(gt.outputs[0], cut.inputs[0])
    nt.links.new(tp.outputs[0], cut.inputs[1])
    nt.links.new(mix.outputs[0], cut.inputs[2])
    nt.links.new(cut.outputs[0], out.inputs["Surface"])
    return m


def impostor_material(root, key):
    name = f"TreeImpostor_{key}"
    m = bpy.data.materials.get(name)
    if m and m.get("tree_kit"):
        return m
    m = bpy.data.materials.new(name)
    m["tree_kit"] = True
    m.use_nodes = True
    nt = m.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    p = os.path.join(root, "assets", "trees", "impostors", "atlas_albedo.png")
    cell = ((load_index(root) or {}).get("variants", {}).get(key, {}).get("impostor") or {}).get("cell")
    if os.path.isfile(p) and cell is not None:
        # the LOD2 UVs span this variant's 4-view strip: map them into the shared atlas
        col, row = cell % 4, cell // 4
        uvn = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (0.25, 1.0 / 16.0, 1.0)
        mp.inputs["Location"].default_value = (col * 0.25, 1.0 - (row + 1) / 16.0, 0.0)
        nt.links.new(uvn.outputs["UV"], mp.inputs["Vector"])
        t = _tex(nt, p, (-600, 200))
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.8
        gt = nt.nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        gt.inputs[1].default_value = 0.4
        nt.links.new(t.outputs["Alpha"], gt.inputs[0])
        tp = nt.nodes.new("ShaderNodeBsdfTransparent")
        cut = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(gt.outputs[0], cut.inputs[0])
        nt.links.new(tp.outputs[0], cut.inputs[1])
        nt.links.new(bsdf.outputs[0], cut.inputs[2])
        nt.links.new(cut.outputs[0], out.inputs["Surface"])
    return m


def dress(root, me, species, impostor=None):
    """Assign the kit materials by slot name (glbs carry the names only)."""
    for i, mat in enumerate(list(me.materials)):
        nm = mat.name if mat else ""
        if mat is not None and not mat.get("tree_kit"):
            mat.name = "_glb_" + nm          # the importer's stand-in: free the kit name
            nm = nm.split(".")[0]
        if nm.startswith("TreeBark"):
            me.materials[i] = bark_material(root, nm.split("_", 1)[1].split(".")[0] if "_" in nm else species)
        elif nm.startswith("TreeLeaves"):
            me.materials[i] = leaf_material(root)
        elif nm.startswith("TreeImpostor") and impostor:
            me.materials[i] = impostor_material(root, impostor)


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    me = None
    for o in new:
        if o.type == "MESH" and me is None:
            me = o.data
    for o in new:
        bpy.data.objects.remove(o)
    return me


def kit_mesh(root, key, lod=0):
    """The kit mesh of a variant (LOD0 by default), named exactly `key` (the world / town
    export keys meshes by data name, the Godot loader finds the variant by it)."""
    name = key if lod == 0 else f"{key}_lod{lod}"
    me = bpy.data.meshes.get(name)
    if me is not None:
        return me
    idx = load_index(root)
    if not idx or key not in idx["variants"]:
        return None
    v = idx["variants"][key]
    me = import_glb(os.path.join(root, "assets", "trees", v["files"][f"lod{lod}"]))
    if me is None:
        return None
    me.name = name
    dress(root, me, v["species"], key if lod == 2 else None)
    return me
