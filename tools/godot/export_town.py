"""Export the hillside town as game-ready glTF + a layout JSON for Godot (Blender 5.2, headless).

    blender -b --factory-startup --python tools/godot/export_town.py -- [--out game/assets/town] [--no-textures]
    (then, if Blender's Python could not run it: python tools/godot/pack_textures.py)

Steps
  1. Import the kit (assets/town/*.glb -> KIT_<asset>) with its Pigment materials and run
     tools/blender_town.py build() unchanged (same seed, same layout as the Cycles renders).
  2. Walk the CyberpunkTown collection.  Every object becomes an *instance* of a *mesh*:
       - objects that share mesh data (kit buildings, signs, lamps, poles, footings) share one glb,
       - everything else (terrain, road runs, junctions, walls, stairs, railings, wires, decals)
         gets its own glb.  Curves are converted to meshes.
     Meshes are written with their own local coordinates (glTF Y-up) to <out>/meshes/<key>.glb,
     with material *names* only (no images) so Godot can map surfaces to materials.
  3. <out>/town_layout.json:
       meshes     key -> {file, surfaces: [material name...], aabb (Godot space), tris}
       materials  name -> {type: pigment|image|flat, ...}   (Pigment folder, emissive_scale, opacity...)
       instances  [{mesh, remap {slot material -> override}, xf (Godot Transform3D, 12 floats:
                    basis x, y, z columns then origin), cat, col (box|cyl|trimesh|none)}]
       lights     street lamps, alley lights, stair lights, billboard lights
       roads      road centre polylines (Godot space) for spawn and reset
       spawn      {pos, dir}
  4. Texture packing (tools/godot/pack_textures.py) runs afterwards with the system Python
     (PIL + numpy): albedo(+alpha) / ORM / normal / emission at <= 2048 px.

Coordinates: Blender (x, y, z) -> Godot (x, z, -y), which is what the glTF exporter does to the
meshes, so an instance transform is C * M * C^T.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import time

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


OUT = os.path.abspath(str(opt("--out", os.path.join(ROOT, "game", "assets", "town"))))
C = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))          # Blender -> Godot axes


def gpos(v):
    return [round(v[0], 4), round(v[2], 4), round(-v[1], 4)]


def gxform(mw):
    r = C @ mw.to_3x3() @ C.transposed()
    t = C @ mw.translation
    cols = [r.col[0], r.col[1], r.col[2]]
    return [round(c[i], 5) for c in cols for i in range(3)] + [round(t[i], 4) for i in range(3)]


def load_tool(name, extra=None):
    src = os.path.join(ROOT, "tools", name + ".py")
    ns = {"__name__": name, "__file__": src}
    ns.update(extra or {})
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns


# ------------------------------------------------------------------ kit (same as town_layout_driver)
def import_kit():
    import glob
    kit = bpy.data.collections.get("TownKit") or bpy.data.collections.new("TownKit")
    if kit.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(kit)
    for path in sorted(glob.glob(os.path.join(ROOT, "assets", "town", "*.glb"))):
        asset = os.path.splitext(os.path.basename(path))[0]
        if asset.startswith("junction_"):
            continue
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        new = [o for o in bpy.data.objects if o not in before]
        meshes = [o for o in new if o.type == "MESH"]
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        if len(meshes) > 1:
            bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        for o in new:
            if o != obj and o.name in bpy.data.objects:
                bpy.data.objects.remove(o)
        obj.name = obj.data.name = "KIT_" + asset
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        kit.objects.link(obj)
    bpy.context.view_layer.layer_collection.children[kit.name].exclude = True
    apply = load_tool("blender_pigment")["apply_pigment_material"]
    tex = os.path.join(ROOT, "scenes", "town", "textures")
    for obj in kit.objects:
        asset = obj.name[4:]
        folder = os.path.join(tex, asset)
        if os.path.isfile(os.path.join(folder, asset + "_BaseColor.png")):
            apply(obj, folder, asset)
        else:
            print("no Pigment maps for", asset)


# ------------------------------------------------------------------ classification
COLLIDE = [  # (name prefix, category, collision)
    ("building_", "building", "box"),
    ("Footing", "footing", "box"),
    ("StreetLamp", "lamp", "cyl"),
    ("PowerPole", "pole", "cyl"),
    ("HangingSign", "sign", "none"),
    ("TownTerrain", "terrain", "trimesh"),
    ("RoadRun", "road", "trimesh"),
    ("Road", "road", "trimesh"),
    ("Junction", "road", "trimesh"),
    ("Curb", "road", "trimesh"),
    ("Sidewalk", "road", "trimesh"),
    ("RetainingWall", "wall", "trimesh"),
    ("StairRails", "rail", "none"),
    ("StairLight", "light", "none"),
    ("Stairs", "stairs", "trimesh"),
    ("StoryDecal", "decal", "none"),
    ("Decal", "decal", "none"),
    ("PowerLines", "wire", "none"),
    ("WallRailings", "rail", "none"),
    ("RailPosts", "rail", "none"),
    ("Fence", "fence", "box"),
    # open world (tools/world/world_export.py)
    ("Terrain_", "terrain", "trimesh"),
    ("SeaFloor", "terrain", "none"),
    ("Water", "water", "none"),
    ("Decals_", "decal", "none"),
    ("JDecals_", "decal", "none"),
    ("Girder_", "bridge", "trimesh"),
    ("Bridge_", "bridge", "trimesh"),
    ("SeaWall", "wall", "trimesh"),
    ("LookoutRail", "rail", "none"),
    ("tower_", "building", "box"),
    ("landmark_", "building", "box"),
    ("warehouse_", "building", "box"),
    ("container", "container", "box"),
    ("crane_sts", "crane", "trimesh"),
    ("light_mast", "pole", "cyl"),
    ("signal_pole", "signal", "cyl"),
    ("tree_", "tree", "cyl"),
    ("overhead_sign", "sign", "none"),
    ("street_lamp", "lamp", "cyl"),
    ("power_pole", "pole", "cyl"),
]


def classify(name, unique, diag):
    for pre, cat, col in COLLIDE:
        if name.startswith(pre):
            return cat, col
    if unique and diag > 4.0:
        return "other", "trimesh"
    return "other", "none"


def safe(s):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in s)


# ------------------------------------------------------------------ materials
def principled(mat):
    if not mat or not mat.use_nodes:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def socket_val(node, name, default):
    s = node.inputs.get(name) if node else None
    if s is None or not hasattr(s, "default_value"):
        return default
    v = s.default_value
    try:
        return [round(float(x), 4) for x in v]
    except TypeError:
        return round(float(v), 4)


def describe_material(mat, images_out):
    """Godot-side description of a Blender material."""
    if mat is None:
        return {"type": "flat", "color": [0.5, 0.5, 0.5], "roughness": 0.8, "metallic": 0.0}
    folder = mat.get("pigment_folder")
    if folder:
        folder = bpy.path.abspath(folder)
        side = {}
        for fn in ("variant.json", "material.json"):
            p = os.path.join(folder, fn)
            if os.path.isfile(p):
                try:
                    side[fn] = json.load(open(p, encoding="utf-8"))
                except Exception:
                    pass
        es = mat.get("pigment_emissive_scale", None)
        if es is None:
            es = side.get("variant.json", {}).get("emissive_scale", 1.0)
        name = mat.get("pigment_name") or os.path.basename(folder).split("__")[0]
        return {"type": "pigment", "folder": os.path.basename(os.path.normpath(folder)), "src": folder.replace("\\", "/"),
                "name": name, "emissive_scale": float(es),
                "opacity": os.path.isfile(os.path.join(folder, name + "_Opacity.png"))}
    b = principled(mat)
    d = {"type": "flat", "color": (socket_val(b, "Base Color", [0.5, 0.5, 0.5, 1]) or [0.5] * 3)[:3],
         "roughness": socket_val(b, "Roughness", 0.8), "metallic": socket_val(b, "Metallic", 0.0)}
    es = socket_val(b, "Emission Strength", 0.0)
    ec = socket_val(b, "Emission Color", [0, 0, 0, 1])
    img = None
    if mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                img = n.image
                break
    if img is not None:
        src = bpy.path.abspath(img.filepath)
        fn = safe(os.path.splitext(os.path.basename(src))[0]) + ".png"
        os.makedirs(images_out, exist_ok=True)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(images_out, fn))
        d = {"type": "image", "image": "images/" + fn, "roughness": d["roughness"], "metallic": d["metallic"],
             "emission": es if es else 0.0, "alpha": True}
    elif es and max(ec[:3]) > 0:
        d["emission"] = ec[:3]
        d["emission_strength"] = es
    d["blender_name"] = mat.name
    return d


# ------------------------------------------------------------------ export one mesh
def export_mesh(me, path):
    tmp = bpy.data.objects.new("_export_tmp", me)
    bpy.context.scene.collection.objects.link(tmp)
    for o in list(bpy.context.selected_objects):
        o.select_set(False)
    tmp.select_set(True)
    bpy.context.view_layer.objects.active = tmp
    kw = dict(filepath=path, use_selection=True, export_format="GLB", export_yup=True,
              export_apply=False, export_texcoords=True, export_normals=True,
              export_materials="EXPORT", export_cameras=False, export_lights=False)
    try:
        bpy.ops.export_scene.gltf(export_image_format="NONE", **kw)
    except TypeError:
        bpy.ops.export_scene.gltf(**kw)
    bpy.data.objects.remove(tmp)


def main():
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_kit()
    town = load_tool("blender_town", {"TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT})
    info = town["build"](root=ROOT)
    print(f"built in {time.time() - t0:.0f} s")
    coll = bpy.data.collections[town["COLL"]]
    # road centre lines and spawn
    roads = []
    try:
        for path in info.get("runs", []):
            pts = [gpos(p) for p in path.xyz[::4]]
            pts.append(gpos(path.xyz[-1]))
            roads.append(pts)
    except Exception as e:      # the roads rework may change info["runs"]
        print("no road centre lines:", e)
    juncs = [{"name": n, "pos": gpos(j["pos"])} for n, j in info.get("junctions", {}).items()]
    spawn = None
    try:
        r = info["runs"][1]
        p, t = r.at(r.length - 70)
        spawn = {"pos": gpos(p), "dir": gpos((t.x, t.y, 0.0))}
    except Exception:
        if roads:
            spawn = {"pos": roads[0][len(roads[0]) // 2], "dir": [1, 0, 0]}
    # traffic: road topology (which junction arm each run starts / ends at) + cross-section
    road_info = []
    try:
        for j in juncs:
            jd = info["junctions"][j["name"]]
            j["kind"] = jd.get("kind", "?")
            j["arms"] = [gpos((math.cos(math.radians(a)), math.sin(math.radians(a)), 0.0)) for a in jd["arms"]]
            j["arm_len"] = [round(float(x), 3) for x in jd["L"]]
        for (na, ia), b, _wps in town["EDGES"]:
            to = {"junction": b[0], "arm": b[1]} if isinstance(b[0], str) else None
            road_info.append({"from": {"junction": na, "arm": ia}, "to": to, "half_width": town["ROAD_HALF"],
                              "surface_dy": town["ROAD_Z"], "lanes_each_way": 1})
        if len(road_info) != len(roads):
            road_info = []
    except Exception as e:
        print("no road topology:", e)
        road_info = []
    export_layout(coll, OUT, roads, juncs, spawn, {"buildings": info.get("buildings")}, t0,
                  extra={"road_info": road_info, "drive_side": "left"})
    if not opt("--no-textures"):
        pack(OUT)


def export_layout(coll, OUT, roads, juncs, spawn, stats, t0=None, name="town_layout.json", extra=None):
    """Write every object of `coll` (and its children) as mesh glbs + instances
    into OUT/meshes and OUT/<name>. Shared mesh data -> one glb. Also used
    by tools/world/world_export.py for the open world."""
    t0 = t0 or time.time()
    os.makedirs(os.path.join(OUT, "meshes"), exist_ok=True)
    images_out = os.path.join(OUT, "images")
    dg = bpy.context.evaluated_depsgraph_get()

    # how many placed objects use each mesh datablock
    users = {}
    for o in coll.all_objects:
        if o.type == "MESH":
            users[o.data.name] = users.get(o.data.name, 0) + 1

    meshes, materials, instances, lights = {}, {}, [], []
    mesh_for_data = {}
    tmp_meshes = []

    def mat_entry(m):
        if m is None:
            return "_none"
        if m.name not in materials:
            materials[m.name] = describe_material(m, images_out)
        return m.name

    for o in sorted(coll.all_objects, key=lambda o: o.name):
        if o.type == "LIGHT":
            if o.data.type == "SUN":
                continue
            li = o.data
            d = {"kind": o.name.split(".")[0], "type": li.type, "pos": gpos(o.matrix_world.translation),
                 "color": [round(c, 3) for c in li.color], "energy": round(li.energy, 2)}
            if li.type in ("AREA", "SPOT"):
                fwd = o.matrix_world.to_3x3() @ Vector((0, 0, -1))
                d["dir"] = gpos(fwd)
                d["size"] = round(getattr(li, "size", 1.0), 3)
            lights.append(d)
            continue
        if o.type not in ("MESH", "CURVE"):
            continue
        base = o.name.split(".")[0]
        if o.type == "MESH" and users.get(o.data.name, 0) > 1:
            me = o.data
            key = safe(me.name.replace("KIT_", ""))
            unique = False
        else:
            ev = o.evaluated_get(dg)
            me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
            if not me.polygons:
                continue
            tmp_meshes.append(me)
            key = safe(o.name)
            unique = True
            if o.type == "CURVE":     # curve materials come from the curve datablock
                me.materials.clear()
                for m in o.data.materials:
                    me.materials.append(m)
        if key not in meshes:
            path = os.path.join(OUT, "meshes", key + ".glb")
            export_mesh(me, path)
            used = sorted({p.material_index for p in me.polygons})
            surfaces = [mat_entry(me.materials[i] if i < len(me.materials) else None) for i in used]
            lo = Vector((min(v.co.x for v in me.vertices), min(v.co.y for v in me.vertices), min(v.co.z for v in me.vertices)))
            hi = Vector((max(v.co.x for v in me.vertices), max(v.co.y for v in me.vertices), max(v.co.z for v in me.vertices)))
            g0, g1 = gpos(lo), gpos(hi)
            aabb = [[min(a, b) for a, b in zip(g0, g1)], [max(a, b) for a, b in zip(g0, g1)]]
            tris = sum(len(p.vertices) - 2 for p in me.polygons)
            cat, col = classify(base, unique, (hi - lo).length)
            meshes[key] = {"file": "meshes/" + key + ".glb", "surfaces": surfaces, "aabb": aabb, "tris": tris,
                           "cat": cat, "col": col}
        remap = {}
        if o.type == "MESH":
            for i, slot in enumerate(o.material_slots):
                if slot.link == "OBJECT" and slot.material is not None and i < len(o.data.materials):
                    orig = o.data.materials[i]
                    if orig is None or orig.name != slot.material.name:
                        remap[mat_entry(orig) if orig else "_none"] = mat_entry(slot.material)
        inst = {"mesh": key, "xf": gxform(o.matrix_world), "name": base}
        if remap:
            inst["remap"] = remap
        instances.append(inst)

    layout = {"version": 1, "coords": "godot (x, y up, z = -blender y)", "generated": time.strftime("%Y-%m-%d %H:%M"),
              "meshes": meshes, "materials": materials, "instances": instances, "lights": lights,
              "roads": roads, "junctions": juncs, "spawn": spawn, **(extra or {}),
              "stats": dict(stats, instances=len(instances), meshes=len(meshes), lights=len(lights))}
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(layout, f, separators=(",", ":"))
    for me in tmp_meshes:
        bpy.data.meshes.remove(me)
    tri_total = sum(m["tris"] * sum(1 for i in instances if i["mesh"] == k) for k, m in meshes.items())
    print(f"EXPORT meshes {len(meshes)} instances {len(instances)} lights {len(lights)} materials {len(materials)} "
          f"roads {len(roads)} tris {tri_total} -> {OUT}  ({time.time() - t0:.0f} s)")
    return layout


def pack(OUT):
    if True:
        py = shutil.which("python") or shutil.which("py")
        packer = os.path.join(HERE, "pack_textures.py")
        if py:
            print("packing textures with", py)
            subprocess.run([py, packer, "--out", OUT], check=False)
        else:
            print("no system python: run  python tools/godot/pack_textures.py")


if __name__ == "__main__":     # tools/world/world_export.py loads this file for export_layout()
    main()
