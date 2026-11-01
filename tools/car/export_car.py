"""Export the textured car for Godot (headless Blender 5.2).

    blender -b --factory-startup --python tools/car/export_car.py -- [--livery security|cab] [--size 2048]

Needs assets/car/src/car_model.blend (tools/car/build_car.py) and the Pigment
texture sets in scenes/car/textures/ (tools/car/car_textures.py). Writes:

    assets/car/car.glb        Body, Wheel_FL/FR/RL/RR, Caliper_*, Collider, Headlight_L/R, Taillight_L/R
    assets/car/car_lod1.glb   the same node names, ~10k triangles, half-size textures
    assets/car/car.json       wheel radius, track, wheelbase, mass, light positions, node list...

Contract: glTF +Y up, the car faces +Z, +X is its left. Every Wheel_* / Caliper_* node
has its origin at the hub centre, at rest. Lamp empties shine along their local -Z
(Godot SpotLight3D convention). Materials are glTF PBR with embedded textures: base
colour (+ alpha for glass), metallic-roughness, occlusion, normal, emissive
(+ KHR_materials_emissive_strength) and KHR_materials_clearcoat.
"""
import json
import os
import shutil
import sys
import tempfile

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

SRC = os.path.join(ROOT, "assets", "car", "src")
OUT = os.path.join(ROOT, "assets", "car")
TEX = os.path.join(ROOT, "scenes", "car", "textures")


def arg(name, default):
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index(name) + 1] if name in argv else default


def occlusion_group():
    """The node group Blender's glTF exporter reads occlusion from."""
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
        gn.location = (1000, -200)
        nt.links.new(ao.outputs["Color"], gn.inputs["Occlusion"])
    return mat


def resize_images(mat, size, tmp):
    """Point every texture at a copy no bigger than size x size (the glb embeds these)."""
    for n in mat.node_tree.nodes:
        if n.type != "TEX_IMAGE" or n.image is None:
            continue
        img = n.image
        src = bpy.path.abspath(img.filepath)
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


def use_material(objs, mat):
    for o in objs:
        for s in o.material_slots:
            s.link = "DATA"
        o.data.materials.clear()
        o.data.materials.append(mat)
        for s in o.material_slots:
            s.link = "DATA"


def export(path, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
                              export_texcoords=True, export_normals=True, export_tangents=True, export_materials="EXPORT",
                              export_image_format="AUTO", export_extras=True, export_animations=False,
                              export_cameras=False, export_lights=False, export_attributes=False)
    print(f"[export_car] {os.path.relpath(path, ROOT)}: {os.path.getsize(path) / 1e6:.1f} MB")


def main():
    livery = arg("--livery", "security")
    size = int(arg("--size", "2048"))
    bpy.ops.wm.open_mainfile(filepath=os.path.join(SRC, "car_model.blend"))
    import blender_pigment as BP
    sc = bpy.context.scene
    body = sc.objects["Body"]
    wheels = [o for o in sc.objects if o.name.startswith(("Wheel_", "Caliper_")) and not o.name.endswith("_LOD1")]
    body_dir = os.path.join(TEX, f"car_body__{livery}")
    wheel_dir = os.path.join(TEX, "car_wheel")
    mb = BP.apply_pigment_material(body, body_dir, "car_body", flake=False)
    mw = BP.apply_pigment_material(wheels[0], wheel_dir, "car_wheel", flake=False)
    use_material(wheels, mw)
    for m in (mb, mw):
        finish_material(m)
    for o in [body] + wheels:
        for k in ("pigment_source", "pigment_folder"):   # local absolute paths: keep them out of the glb
            if k in o.keys():
                del o[k]
    tmp = tempfile.mkdtemp(prefix="car_glb_")
    resize_images(mb, size, tmp)
    resize_images(mw, size // 2, tmp)

    lamps = [sc.objects[n] for n in ("Headlight_L", "Headlight_R", "Taillight_L", "Taillight_R")]
    col = sc.objects["Collider"]
    suffix = "" if livery == "security" else f"_{livery}"
    export(os.path.join(OUT, f"car{suffix}.glb"), [body] + wheels + [col] + lamps)

    # LOD1: swap names so the file uses the same node names as LOD0
    lod = {o.name[:-5]: o for o in sc.objects if o.name.endswith("_LOD1")}
    lod_body = lod["Body"]
    use_material([lod_body], mb)
    use_material([o for k, o in lod.items() if k.startswith("Wheel_")], mw)
    # LOD1 keeps the calipers of LOD0 (276 tris each) but drops nothing else
    for k, o in lod.items():
        sc.objects[k].name = k + "_LOD0"
        o.name = k
    resize_images(mb, size // 2, tmp)
    resize_images(mw, size // 4, tmp)
    calipers = [o for o in wheels if o.name.startswith("Caliper_")]
    export(os.path.join(OUT, f"car{suffix}_lod1.glb"), list(lod.values()) + calipers + [col] + lamps)

    info = json.load(open(os.path.join(SRC, "car_info.json")))
    info["livery"] = livery
    info["files"] = {"lod0": f"car{suffix}.glb", "lod1": f"car{suffix}_lod1.glb"}
    info["materials"] = {
        "CarBody": f"Pigment_car_body ({livery}): one material for the whole body; glass, lenses and the light bar are see-through "
                   "via base-colour alpha (alphaMode BLEND). In Godot use transparency = Alpha Depth Pre-Pass (or Alpha Hash) "
                   "on this material so the opaque paint sorts correctly.",
        "CarWheel": "Pigment_car_wheel: tyre, rim, disc and caliper",
    }
    info["textures"] = {"body": size, "wheel": size // 2, "lod1_body": size // 2}
    info["notes"] = ["Calipers are separate nodes (Caliper_XX, same origin as Wheel_XX): steer them with the wheel but don't spin them.",
                     "Collider is a convex hull (extras: collider=convex, hidden=true): use it as a ConvexPolygonShape3D and hide the mesh.",
                     "Headlight_* / Taillight_* empties: put a SpotLight3D / OmniLight3D there; their local -Z is the beam direction.",
                     "Metallic flake is not in glTF; the clearcoat is (KHR_materials_clearcoat)."]
    with open(os.path.join(OUT, f"car{suffix}.json"), "w") as f:
        json.dump(info, f, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    print("[export_car] done")


if __name__ == "__main__":
    main()
