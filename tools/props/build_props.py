"""Model the street props (headless Blender 5.2) -> Pigment source meshes.

    blender -b --factory-startup --python tools/props/build_props.py -- [names...] [--clay DIR]

For every prop (default: all in tools/props/catalog.py) writes
    assets/props/src/<name>.glb    untextured mesh with final UVs (Pigment's input; Y-up, faces +Z)
                                   main node <name> + one node per separately driven piece
                                   (traffic lamps: Lamp_A_Red ...)
    assets/props/src/<name>.json   pieces (name, group, node, glTF bbox per connected surface,
                                   used to map Pigment parts to material groups), lights,
                                   sockets, collider shapes, bounds, triangles, texel density

--clay DIR also renders a quick Workbench clay image per prop (for checking shapes).
Then: python tools/props/props_textures.py  and  blender ... tools/props/export_props.py
"""
import json
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import catalog  # noqa: E402
import proplib  # noqa: E402
from proplib import Prop, gl  # noqa: E402

MODELS = {}
for mod in ("models_street", "models_clutter", "models_port"):
    try:
        MODELS.update(__import__(mod).MODELS)
    except ImportError as e:
        if mod in str(e):
            print(f"[build_props] {mod} missing: {e}")
        else:
            raise

SRC = os.path.join(ROOT, "assets", "props", "src")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1]
    return default


def collider_shapes(P, lo, hi):
    """Blender-space collider spec -> glTF-space list of shapes."""
    spec = P.collider
    out = []
    if spec in ("none", "convex"):
        return [{"type": spec}]
    if spec == ("box",) or spec is None:
        c = [(lo[i] + hi[i]) / 2 for i in range(3)]
        s = [hi[i] - lo[i] for i in range(3)]
        return [{"type": "box", "center": gl(c), "size": [round(s[0], 4), round(s[2], 4), round(s[1], 4)]}]
    for sh in spec:
        if sh[0] == "box":
            c, s = sh[1], sh[2]
            out.append({"type": "box", "center": gl(c), "size": [round(s[0], 4), round(s[2], 4), round(s[1], 4)]})
        elif sh[0] == "cyl":
            (x, y), r, h = sh[1], sh[2], sh[3]
            z0 = sh[4] if len(sh) > 4 else 0.0
            out.append({"type": "cylinder", "center": gl((x, y, z0 + h / 2)), "radius": r, "height": h})
    return out


def build(name):
    proplib.clear_scene()
    P = Prop(name)
    MODELS[name](P)
    info = catalog.PROPS[name]
    recs = P.records()
    if len(recs) > 250:
        raise SystemExit(f"{name}: {len(recs)} connected surfaces; Pigment part masks stop at 256")
    lo, hi = P.bounds()
    ob = P.to_object()
    proplib.uv_unwrap(ob, P.pieces)
    tpm = proplib.texel_density(ob, info["res"])

    # split the separately driven pieces (traffic lamps...) into their own objects
    nodes = sorted({p.node for p in P.pieces if p.node})
    node_objs = []
    if nodes:
        import bmesh
        for nd in nodes:
            ids = {p.id for p in P.pieces if p.node == nd}
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(ob.data)
            lay = bm.faces.layers.int["piece"]
            n = 0
            for f in bm.faces:
                if f[lay] in ids:
                    f.select_set(True)
                    n += 1
            bm.select_flush_mode()
            bmesh.update_edit_mesh(ob.data)
            if not n:
                raise SystemExit(f"{name}: node {nd} has no faces")
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")
            new = [o for o in bpy.context.selected_objects if o is not ob][0]
            new.name = nd
            new.data.name = nd
            node_objs.append(new)

    if not len(ob.data.polygons):          # every piece is a node (puddle decals)
        bpy.data.objects.remove(ob)
        ob = node_objs[0]
    else:
        node_objs = node_objs
    # drop the helper attribute so it stays out of the glb
    for o in {ob, *node_objs}:
        for att in ("piece", "uvlow"):
            if att in o.data.attributes:
                o.data.attributes.remove(o.data.attributes[att])

    os.makedirs(SRC, exist_ok=True)
    path = os.path.join(SRC, f"{name}.glb")
    bpy.ops.object.select_all(action="DESELECT")
    allobjs = [ob] + [o for o in node_objs if o is not ob]
    for o in allobjs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
                              export_texcoords=True, export_normals=True, export_materials="NONE", export_extras=False,
                              export_animations=False, export_cameras=False, export_lights=False, export_attributes=False)
    tris = sum(len(p.vertices) - 2 for o in allobjs for p in o.data.polygons)
    data = {
        "name": name,
        "bounds_gl": {"min": gl((lo[0], hi[1], lo[2])), "max": gl((hi[0], lo[1], hi[2]))},
        "size_m": [round(hi[0] - lo[0], 3), round(hi[2] - lo[2], 3), round(hi[1] - lo[1], 3)],
        "tris": tris,
        "texels_per_m": round(tpm, 1),
        "nodes": nodes,
        "pieces": recs,
        "lights": [dict(l, pos=gl(l["pos"]), dir=gl(l["dir"]) if l["dir"] else None) for l in P.lights],
        "sockets": [dict(s, pos=gl(s["pos"]), dir=gl(s["dir"]) if s["dir"] else None) for s in P.sockets],
        "collider": collider_shapes(P, lo, hi),
        "meta": P.meta,
    }
    with open(os.path.join(SRC, f"{name}.json"), "w") as f:
        json.dump(data, f, indent=1)
    print(f"[build_props] {name}: {tris} tris, {len(recs)} surfaces, {len(P.pieces)} pieces, {tpm:.0f} texels/m at {info['res']}, "
          f"size {data['size_m']}")
    clay = opt("--clay")
    if clay:
        render_clay(clay, name, lo, hi)
    return data


def render_clay(out, name, lo, hi):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "RANDOM"
    sc.display.shading.show_cavity = True
    sc.render.resolution_x = sc.render.resolution_y = 480
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    ext = max(hi[i] - lo[i] for i in range(3))
    cam_d = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    from mathutils import Vector
    d = Vector((math.sin(math.radians(35)) * -1, -math.cos(math.radians(35)), 0.45)).normalized()
    cam.location = Vector(c) + d * ext * 2.2
    cam.rotation_euler = (Vector(c) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_d.lens = 50
    os.makedirs(out, exist_ok=True)
    sc.render.filepath = os.path.join(out, f"{name}.png")
    bpy.ops.render.render(write_still=True)


def main():
    names = [a for a in ARGS if not a.startswith("--") and (ARGS.index(a) == 0 or ARGS[ARGS.index(a) - 1] != "--clay")]
    names = names or [n for n in catalog.names() if n in MODELS]
    missing = [n for n in names if n not in MODELS]
    if missing:
        raise SystemExit(f"no model for {missing}")
    for n in names:
        build(n)
    print(f"[build_props] built {len(names)} props")


if __name__ == "__main__":
    main()
