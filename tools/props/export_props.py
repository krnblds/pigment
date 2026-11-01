"""Export the textured street props for Godot (headless Blender 5.2).

    blender -b --factory-startup --python tools/props/export_props.py -- [names...] [--no-index]

Needs assets/props/src/<name>.glb/.json (build_props.py) and the Pigment texture sets in
scenes/props/textures/<name>/ (props_textures.py).  Writes per prop:

    assets/props/<name>.glb        LOD0: mesh node <name> (+ separately driven nodes such as
                                   Lamp_A_Red), Collider (hidden, extras collider=box|cylinder|...),
                                   Light_* / Socket_* empties (extras: light / socket hints)
    assets/props/<name>_lod1.glb   decimated, same node names, half-size textures (bigger props)
    assets/props/src/<name>_export.json   files, triangle counts, texture sizes

then runs tools/props/write_index.py (system Python) for assets/props/index.json and the
variant texture swaps.  Contract: glTF Y-up, the prop faces +Z, origin on the ground at the
footprint centre (wall-mounted / spanning props: see index.json "mount").
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)
import catalog  # noqa: E402

SRC = os.path.join(ROOT, "assets", "props", "src")
OUT = os.path.join(ROOT, "assets", "props")
TEX = os.path.join(ROOT, "scenes", "props", "textures")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def bl(v):
    """glTF (x, y, z) -> Blender (x, -z, y)."""
    return Vector((v[0], -v[2], v[1]))


def occlusion_group():
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
        g.interface.new_socket("Thickness", in_out="INPUT", socket_type="NodeSocketFloat")
    return g


def finish_material(mat):
    nt = mat.node_tree
    ao = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image and n.image.name.lower().endswith("_ao.png")), None)
    if ao is not None:
        gn = nt.nodes.new("ShaderNodeGroup")
        gn.node_tree = occlusion_group()
        nt.links.new(ao.outputs["Color"], gn.inputs["Occlusion"])


def resize_images(mat, size, tmp):
    for n in mat.node_tree.nodes:
        if n.type != "TEX_IMAGE" or n.image is None:
            continue
        img = n.image
        src = img.get("orig_path") or bpy.path.abspath(img.filepath)
        img["orig_path"] = src
        dst = os.path.join(tmp, f"{size}_{os.path.basename(src)}")
        if not os.path.exists(dst):
            im = bpy.data.images.load(src, check_existing=False)
            if im.size[0] > size:
                im.scale(size, size)
            im.filepath_raw = dst
            im.file_format = "PNG"
            im.save()
            bpy.data.images.remove(im)
        img.filepath = dst
        img.reload()


def export(path, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
                              export_texcoords=True, export_normals=True, export_tangents=False, export_materials="EXPORT",
                              export_image_format="JPEG", export_image_quality=88, export_extras=True, export_animations=False,
                              export_cameras=False, export_lights=False, export_attributes=False)
    return os.path.getsize(path)


def collider_obj(shapes, main):
    """One hidden mesh holding every collider shape (boxes, cylinders) or a convex hull."""
    import bmesh
    bm = bmesh.new()
    kind = shapes[0]["type"] if shapes else "none"
    if kind == "none":
        return None
    if kind == "convex":
        bm.from_mesh(main.data)
        bmesh.ops.convex_hull(bm, input=bm.verts)
    else:
        for s in shapes:
            c = bl(s["center"])
            if s["type"] == "box":
                sz = s["size"]
                m = __import__("mathutils").Matrix.Translation(c) @ __import__("mathutils").Matrix.Diagonal((sz[0], sz[2], sz[1], 1))
                bmesh.ops.create_cube(bm, size=1.0, matrix=m)
            elif s["type"] == "cylinder":
                m = __import__("mathutils").Matrix.Translation(c)
                bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=s["radius"], radius2=s["radius"], depth=s["height"], matrix=m)
    me = bpy.data.meshes.new("Collider")
    bm.to_mesh(me)
    ob = bpy.data.objects.new("Collider", me)
    bpy.context.scene.collection.objects.link(ob)
    ob["collider"] = "convex" if kind == "convex" else ("compound" if len(shapes) > 1 else shapes[0]["type"])
    ob["hidden"] = True
    ob["shapes"] = json.dumps(shapes)
    return ob


def empties(data):
    out = []
    for l in data["lights"]:
        e = bpy.data.objects.new(l["name"], None)
        e.location = bl(l["pos"])
        if l.get("dir"):
            # local -Z = light direction (Godot SpotLight3D convention)
            d = bl(l["dir"]).normalized()
            e.rotation_euler = (-d).to_track_quat("Z", "Y").to_euler()
        e["light"] = l["type"]
        e["color"] = l["color"]
        e["energy"] = l["energy"]
        e["range"] = l["range"]
        bpy.context.scene.collection.objects.link(e)
        out.append(e)
    for s in data["sockets"]:
        if s["kind"] == "signal_lamp":
            continue           # the lamp nodes themselves carry these
        e = bpy.data.objects.new(s["name"], None)
        e.location = bl(s["pos"])
        e["socket"] = s["kind"]
        bpy.context.scene.collection.objects.link(e)
        out.append(e)
    return out


def export_prop(name):
    import blender_pigment as BP
    bpy.ops.wm.read_factory_settings(use_empty=True)
    info = catalog.PROPS[name]
    data = json.load(open(os.path.join(SRC, f"{name}.json")))
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, f"{name}.glb"))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:
        o.select_set(False)
    main = next((o for o in meshes if o.name == name), meshes[0])
    nodes = [o for o in meshes if o is not main]
    folder = os.path.join(TEX, name)
    if not os.path.isdir(folder):
        raise SystemExit(f"{name}: no textures in {folder} (run tools/props/props_textures.py {name})")
    mat = BP.apply_pigment_material(main, folder, name, flake=False)
    for o in nodes:
        o.data.materials.clear()
        o.data.materials.append(mat)
    finish_material(mat)
    for o in meshes:
        for k in ("pigment_source", "pigment_folder"):
            if k in o.keys():
                del o[k]
    # the puddles (all nodes): give every node its own origin at its centre
    if name == "puddle_decal":
        for o in meshes:
            c = sum((v.co for v in o.data.vertices), Vector()) / len(o.data.vertices)
            o.data.transform(__import__("mathutils").Matrix.Translation(-Vector((c.x, c.y, 0))))
            o.location = (0, 0, 0)
    col = collider_obj(data["collider"], main)
    emp = empties(data)
    tmp = tempfile.mkdtemp(prefix="props_glb_")
    size = info["embed"]
    resize_images(mat, size, tmp)
    extra = ([col] if col else []) + emp
    path0 = os.path.join(OUT, f"{name}.glb")
    b0 = export(path0, [main] + nodes + extra)
    tris0 = sum(len(p.vertices) - 2 for o in [main] + nodes for p in o.data.polygons)
    res = {"lod0": f"{name}.glb", "lod0_bytes": b0, "lod0_tris": tris0, "texture": size}
    if info.get("lod1"):
        lod = main.copy()
        lod.data = main.data.copy()
        bpy.context.scene.collection.objects.link(lod)
        mod = lod.modifiers.new("dec", "DECIMATE")
        mod.ratio = info["lod1"]
        mod.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = lod
        bpy.ops.object.select_all(action="DESELECT")
        lod.select_set(True)
        bpy.ops.object.modifier_apply(modifier="dec")
        main.name = name + "_LOD0"
        lod.name = name
        resize_images(mat, max(128, size // 2), tmp)
        path1 = os.path.join(OUT, f"{name}_lod1.glb")
        b1 = export(path1, [lod] + nodes + extra)
        res.update({"lod1": f"{name}_lod1.glb", "lod1_bytes": b1, "lod1_tris": sum(len(p.vertices) - 2 for o in [lod] + nodes for p in o.data.polygons),
                    "lod1_texture": max(128, size // 2)})
    with open(os.path.join(SRC, f"{name}_export.json"), "w") as f:
        json.dump(res, f, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[export_props] {name}: {b0 / 1e6:.2f} MB" + (f" + lod1 {res['lod1_bytes'] / 1e6:.2f} MB" if "lod1" in res else ""))


def main():
    names = [a for a in ARGS if not a.startswith("--")] or catalog.names()
    os.makedirs(OUT, exist_ok=True)
    for n in names:
        export_prop(n)
    if "--no-index" not in ARGS:
        py = shutil.which("python") or shutil.which("py")
        r = subprocess.run([py, os.path.join(HERE, "write_index.py")], cwd=ROOT)
        if r.returncode:
            print("[export_props] write_index.py failed: run it with the system Python")


if __name__ == "__main__":
    main()
