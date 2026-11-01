"""Export textured fleet vehicles for Godot (headless Blender 5.2).

    blender -b --factory-startup --python tools/vehicles/export.py -- NAME|all [--format webp|png] [--no-legacy]

Needs assets/vehicles/<id>/src/<id>_model.blend (tools/vehicles/build.py) and the Pigment
texture sets in scenes/vehicles/<id>/textures/ (tools/vehicles/textures.py). Writes:

    assets/vehicles/<id>/<id>.glb        LOD0: Body, Wheel_FL/FR/RL/RR, Caliper_*, Collider,
                                         Headlight_L/R, Taillight_L/R
    assets/vehicles/<id>/<id>_lod1.glb   the same node names, ~10k triangles, half-size textures
    assets/vehicles/<id>/<id>_lod2.glb   distant traffic: Body + wheels (+ Collider, lamps), ~1-2k
                                         triangles, 256 px textures, no calipers
    assets/vehicles/<id>/<id>.json       the contract numbers (car.json format) + variants
    assets/vehicles/index.json           every vehicle: class, LOD files, variants, spawn weights
and, for the Tsubame-4 (the hero), the legacy assets/car/car.glb, car_lod1.glb, car.json
(security livery, PNG textures, material Pigment_car_body), exactly as before.

Variants: every LOD's Body carries all of the vehicle's paint / livery materials through
glTF KHR_materials_variants (the default material is the first variant). Maps that are the
same in several variants (normal, AO, often roughness) are stored once. Textures are WebP
(EXT_texture_webp, which Godot 4 imports) unless --format png.
"""
import hashlib
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

import fleet as F  # noqa: E402

LOD_SIZES = {"lod0": (2048, 1024), "lod1": (1024, 512), "lod2": (256, 128)}


def arg(name, default):
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index(name) + 1] if name in argv else default


def enable_variants_ui():
    prefs = bpy.context.preferences.addons["io_scene_gltf2"].preferences
    if not prefs.KHR_materials_variants_ui:
        prefs.KHR_materials_variants_ui = True


def occlusion_group():
    """The node group Blender's glTF exporter reads occlusion from."""
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
        g.interface.new_socket("Thickness", in_out="INPUT", socket_type="NodeSocketFloat")
    return g


def drop_transmission(mat):
    """WebP can't hold the 1-channel transmission texture the exporter writes, and Godot ignores
    KHR_materials_transmission anyway: glass stays see-through through base-colour alpha."""
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return
    sock = bsdf.inputs.get("Transmission Weight")
    if sock is not None:
        for l in list(sock.links):
            mat.node_tree.links.remove(l)
        sock.default_value = 0.0


def triangulate(objs):
    """Triangulate the bodies (boolean cuts leave n-gons; the exporter needs triangles to compute
    tangents for the normal maps). Applied for real: a modifier would hide the mesh's
    KHR_materials_variants data from the exporter (it reads the evaluated copy)."""
    for o in objs:
        m = o.modifiers.new("tri", "TRIANGULATE")
        m.keep_custom_normals = True
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        me.validate(clean_customdata=False)
        old = o.data
        o.modifiers.clear()
        o.data = me
        me.name = old.name
        if old.users == 0:
            bpy.data.meshes.remove(old)


def triangulate_shared(objs):
    """Triangulate wheel / caliper meshes once per mesh datablock and keep them shared."""
    by_mesh = {}
    for o in objs:
        by_mesh.setdefault(o.data, []).append(o)
    for me, users in by_mesh.items():
        o = users[0]
        name = me.name
        triangulate([o])
        for u in users[1:]:
            u.data = o.data
        o.data.name = name


def finish_material(mat):
    nt = mat.node_tree
    ao = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image and n.image.name.lower().endswith("_ao.png")), None)
    if ao is not None:
        gn = nt.nodes.new("ShaderNodeGroup")
        gn.node_tree = occlusion_group()
        gn.location = (1000, -200)
        nt.links.new(ao.outputs["Color"], gn.inputs["Occlusion"])
    return mat


def file_hash(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


class Images:
    """Resized copies of the Pigment maps, one per (source content, size): identical maps in
    different variants become one image (one texture in the glb)."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.src = {}       # node image -> original file
        self.hashes = {}

    def remember(self, mat):
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None and n.image not in self.src:
                self.src[n.image] = bpy.path.abspath(n.image.filepath)

    def point(self, mats, size):
        """Point every texture of `mats` at a <= size copy; images with the same content share one datablock."""
        shared = {}
        for mat in mats:
            for n in mat.node_tree.nodes:
                if n.type != "TEX_IMAGE" or n.image is None:
                    continue
                src = self.src.get(n.image) or self.src.setdefault(n.image, bpy.path.abspath(n.image.filepath))
                h = self.hashes.get(src) or self.hashes.setdefault(src, file_hash(src))
                key = (h, size)
                if key in shared:
                    n.image = shared[key]
                    continue
                dst = os.path.join(self.tmp, f"{size}_{h[:12]}_{os.path.basename(src)}")
                if not os.path.exists(dst):
                    im = bpy.data.images.load(src, check_existing=False)
                    if im.size[0] > size:
                        im.scale(size, size)
                    im.filepath_raw = dst
                    im.file_format = "PNG"
                    im.save()
                    bpy.data.images.remove(im)
                img = n.image
                if img.users > 1 and img.filepath != dst:
                    img = img.copy()
                    n.image = img
                self.src[img] = src
                img.filepath = dst
                img.name = f"{os.path.splitext(os.path.basename(src))[0]}_{h[:6]}"
                img.reload()
                shared[key] = img


def use_material(objs, mat):
    for o in objs:
        for s in o.material_slots:
            s.link = "DATA"
        o.data.materials.clear()
        o.data.materials.append(mat)


def set_variants(mesh, mats, names):
    """KHR_materials_variants on slot 0 of `mesh`: variant i -> mats[i]."""
    sc = bpy.context.scene
    vs = sc.gltf2_KHR_materials_variants_variants
    if len(vs) != len(names):
        vs.clear()
        for i, nm in enumerate(names):
            v = vs.add()
            v.variant_idx = i          # set the index before the name (the name's update callback checks it)
            v.name = nm
    mesh.gltf2_variant_mesh_data.clear()
    for i, m in enumerate(mats):
        d = mesh.gltf2_variant_mesh_data.add()
        d.material_slot_index = 0
        d.material = m
        vv = d.variants.add()
        vv.variant.variant_idx = i


def export(path, objs, fmt="WEBP", quality=82):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
              export_texcoords=True, export_normals=True, export_tangents=True, export_materials="EXPORT",
              export_image_format=fmt, export_extras=True, export_animations=False,
              export_cameras=False, export_lights=False, export_attributes=False)
    if fmt == "WEBP":
        kw["export_image_quality"] = quality
    bpy.ops.export_scene.gltf(**kw)
    print(f"[export] {os.path.relpath(path, ROOT)}: {os.path.getsize(path) / 1e6:.1f} MB")


def lod_swap(sc, suffix):
    """Give the `<name>_<suffix>` objects the LOD0 names (so every file has the same node names);
    returns {name: lod object} and a function that undoes the swap."""
    lod = {o.name[:-len(suffix) - 1]: o for o in sc.objects if o.name.endswith("_" + suffix)}
    for k, o in lod.items():
        sc.objects[k].name = k + "_TMP0"
        o.name = k

    def undo():
        for k, o in lod.items():
            o.name = k + "_" + suffix
            sc.objects[k + "_TMP0"].name = k
    return lod, undo


def export_vehicle(vid, fmt, legacy=True):
    fv = F.VEHICLES[vid]
    src = os.path.join(ROOT, "assets", "vehicles", vid, "src")
    out = os.path.join(ROOT, "assets", "vehicles", vid)
    tex = os.path.join(ROOT, "scenes", "vehicles", vid, "textures")
    bpy.ops.wm.open_mainfile(filepath=os.path.join(src, f"{vid}_model.blend"))
    enable_variants_ui()
    import blender_pigment as BP
    sc = bpy.context.scene
    body = sc.objects["Body"]
    wheels = [o for o in sc.objects if o.name.startswith(("Wheel_", "Caliper_")) and "_LOD" not in o.name]
    names = [v["name"] for v in fv["variants"]]
    mats = []
    for vn in names:
        m = BP.apply_pigment_material(body, os.path.join(tex, f"{vid}_body__{vn}"), f"{vid}_body", flake=False)
        m.name = f"{vid}_{vn}"
        finish_material(m)
        mats.append(m)
    mw = BP.apply_pigment_material(wheels[0], os.path.join(tex, f"{vid}_wheel"), f"{vid}_wheel", flake=False)
    mw.name = f"{vid}_wheel"
    finish_material(mw)
    legacy_mats = (mats[0].copy(), mw.copy()) if vid == "tsubame" and legacy else None   # keeps transmission (PNG)
    if fmt == "WEBP":
        for m in mats + [mw]:
            drop_transmission(m)
    triangulate([o for o in sc.objects if o.type == "MESH" and o.name.startswith("Body")])
    triangulate_shared([o for o in sc.objects if o.type == "MESH" and o.name.startswith(("Wheel_", "Caliper_"))])
    use_material(wheels, mw)
    for o in [body] + wheels:
        for k in ("pigment_source", "pigment_folder"):   # local absolute paths: keep them out of the glb
            if k in o.keys():
                del o[k]
    tmp = tempfile.mkdtemp(prefix=f"{vid}_glb_")
    imgs = Images(tmp)
    for m in mats + [mw] + list(legacy_mats or ()):
        imgs.remember(m)
    lamps = [sc.objects[n] for n in ("Headlight_L", "Headlight_R", "Taillight_L", "Taillight_R")]
    col = sc.objects["Collider"]
    files = {}
    tri = json.load(open(os.path.join(src, f"{vid}_info.json")))["triangles"]

    # LOD0
    b, w = LOD_SIZES["lod0"]
    imgs.point(mats, b)
    imgs.point([mw], w)
    use_material([body], mats[0])
    set_variants(body.data, mats, names)
    files["lod0"] = f"{vid}.glb"
    export(os.path.join(out, files["lod0"]), [body] + wheels + [col] + lamps, fmt)
    calipers = [o for o in wheels if o.name.startswith("Caliper_")]
    # LOD1 / LOD2
    for suffix, key in (("LOD1", "lod1"), ("LOD2", "lod2")):
        lod, undo = lod_swap(sc, suffix)
        b, w = LOD_SIZES[key]
        imgs.point(mats, b)
        imgs.point([mw], w)
        lb = lod["Body"]
        use_material([lb], mats[0])
        set_variants(lb.data, mats, names)
        use_material([o for k, o in lod.items() if k.startswith("Wheel_")], mw)
        objs = list(lod.values()) + (calipers if key == "lod1" else []) + [col] + lamps
        files[key] = f"{vid}_{key}.glb"
        export(os.path.join(out, files[key]), objs, fmt)
        undo()

    info = json.load(open(os.path.join(src, f"{vid}_info.json")))
    info["files"] = dict(files, json=f"{vid}.json")
    info["textures"] = {"body": LOD_SIZES["lod0"][0], "wheel": LOD_SIZES["lod0"][1], "lod1_body": LOD_SIZES["lod1"][0],
                        "lod2_body": LOD_SIZES["lod2"][0], "format": fmt.lower()}
    info["materials"] = {
        "Body": f"one material per variant ({vid}_<variant>), switched through KHR_materials_variants; glass, lenses and "
                "hidden parts are see-through via base-colour alpha (alphaMode BLEND): in Godot use transparency = "
                "Alpha Depth Pre-Pass on it.",
        "Wheel": f"{vid}_wheel: tyre, rim, disc and caliper (shared by every variant)",
    }
    info["variants"] = [{"name": v["name"], "index": i, "label": v.get("label", v["name"]), "kind": v.get("kind", "civilian"),
                         "weight": v.get("weight", 1.0), "material": f"{vid}_{v['name']}"} for i, v in enumerate(fv["variants"])]
    info["default_variant"] = names[0]
    info["traffic"] = {"class": fv["class"], "spawn_weight": fv["weight"], "player": bool(fv.get("player") or vid == "tsubame")}
    info["notes"] = ["Calipers are separate nodes (Caliper_XX, same origin as Wheel_XX): steer them with the wheel but don't spin them. "
                     "LOD2 has no calipers.",
                     "Collider is a convex hull (extras: collider=convex, hidden=true): use it as a ConvexPolygonShape3D and hide the mesh.",
                     "Headlight_* / Taillight_* empties: put a SpotLight3D / OmniLight3D there; their local -Z is the beam direction.",
                     "Variants: glTF KHR_materials_variants on Body (all LODs). Godot does not apply the extension by itself: "
                     "tools/vehicles/godot/vehicle_variants.gd reads it at import and offers set_variant(root, name).",
                     "Metallic flake is not in glTF; the clearcoat is (KHR_materials_clearcoat)."]
    with open(os.path.join(out, f"{vid}.json"), "w") as f:
        json.dump(info, f, indent=1)

    if vid == "tsubame" and legacy:
        export_legacy(sc, body, wheels, calipers, col, lamps, legacy_mats[0], legacy_mats[1], imgs)
    shutil.rmtree(tmp, ignore_errors=True)
    return info


def export_legacy(sc, body, wheels, calipers, col, lamps, mat_security, mw, imgs):
    """assets/car/: the hero's old contract (security livery, PNG, no variants), unchanged."""
    out = os.path.join(ROOT, "assets", "car")
    body.data.gltf2_variant_mesh_data.clear()
    mat_security.name = "Pigment_car_body"
    mw.name = "Pigment_car_wheel"
    imgs.point([mat_security], 2048)
    imgs.point([mw], 1024)
    use_material([body], mat_security)
    use_material(wheels, mw)
    export(os.path.join(out, "car.glb"), [body] + wheels + [col] + lamps, "AUTO")
    lod, undo = lod_swap(sc, "LOD1")
    lb = lod["Body"]
    lb.data.gltf2_variant_mesh_data.clear()
    use_material([lb], mat_security)
    use_material([o for k, o in lod.items() if k.startswith("Wheel_")], mw)
    imgs.point([mat_security], 1024)
    imgs.point([mw], 512)
    export(os.path.join(out, "car_lod1.glb"), list(lod.values()) + calipers + [col] + lamps, "AUTO")
    undo()
    info = json.load(open(os.path.join(ROOT, "assets", "vehicles", "tsubame", "src", "tsubame_info.json")))
    keep = ["name", "units", "coords", "origin", "nodes", "wheel_radius", "wheel_width", "track", "wheelbase", "wheel_positions",
            "lights", "mass_kg", "center_of_mass", "suspension_suggestion", "dimensions", "triangles"]
    info = {k: info[k] for k in keep}
    info["dimensions"] = {k: v for k, v in info["dimensions"].items() if k not in ("width", "height")}
    info["triangles"].pop("lod2", None)
    info["livery"] = "security"
    info["files"] = {"lod0": "car.glb", "lod1": "car_lod1.glb"}
    info["materials"] = {
        "CarBody": "Pigment_car_body (security): one material for the whole body; glass, lenses and the light bar are see-through "
                   "via base-colour alpha (alphaMode BLEND). In Godot use transparency = Alpha Depth Pre-Pass (or Alpha Hash) "
                   "on this material so the opaque paint sorts correctly.",
        "CarWheel": "Pigment_car_wheel: tyre, rim, disc and caliper",
    }
    info["textures"] = {"body": 2048, "wheel": 1024, "lod1_body": 1024}
    info["notes"] = ["Calipers are separate nodes (Caliper_XX, same origin as Wheel_XX): steer them with the wheel but don't spin them.",
                     "Collider is a convex hull (extras: collider=convex, hidden=true): use it as a ConvexPolygonShape3D and hide the mesh.",
                     "Headlight_* / Taillight_* empties: put a SpotLight3D / OmniLight3D there; their local -Z is the beam direction.",
                     "Metallic flake is not in glTF; the clearcoat is (KHR_materials_clearcoat).",
                     "This is the legacy single-livery export; assets/vehicles/tsubame/ has the same car with all its variants and LOD2."]
    with open(os.path.join(out, "car.json"), "w") as f:
        json.dump(info, f, indent=1)


def write_index():
    from specs import FLEET
    vehicles = []
    for vid in FLEET:
        p = os.path.join(ROOT, "assets", "vehicles", vid, f"{vid}.json")
        if not os.path.exists(p):
            continue
        info = json.load(open(p))
        fv = F.VEHICLES[vid]
        e = {"id": vid, "name": info["name"], "class": fv["class"], "spawn_weight": fv["weight"],
             "player": info["traffic"]["player"],
             "files": {k: f"{vid}/{v}" for k, v in info["files"].items()},
             "triangles": {k: info["triangles"][k] for k in ("lod0", "lod1", "lod2") if k in info["triangles"]},
             "lod_distances_m": {"lod0": 0, "lod1": 25, "lod2": 70},
             "dimensions": info["dimensions"], "wheelbase": info["wheelbase"], "mass_kg": info["mass_kg"],
             "default_variant": info["default_variant"],
             "variants": [{k: v[k] for k in ("name", "index", "label", "kind", "weight")} for v in info["variants"]]}
        if vid == "tsubame":
            e["legacy"] = {"lod0": "../car/car.glb", "lod1": "../car/car_lod1.glb", "json": "../car/car.json", "variant": "security"}
        vehicles.append(e)
    total = sum(v["spawn_weight"] for v in vehicles if v["class"] != "sports" or True)
    idx = {
        "format": "vehicle-index", "version": 1,
        "coords": "glTF: +Y up, vehicles face +Z, +X is their left side; origin on the ground under the body centre",
        "contract": "every <id>.glb / _lod1 / _lod2 has Body, Wheel_FL/FR/RL/RR (origins at the hubs), Collider (convex hull, hidden), "
                    "Headlight_L/R + Taillight_L/R empties (local -Z = beam); LOD0 and LOD1 also Caliper_XX. <id>.json = car.json format.",
        "variants": "KHR_materials_variants on Body; pick by name (variants[].name) or index; weights are relative within a vehicle",
        "spawn": "pick a vehicle by spawn_weight / total_weight, then a variant by its weight; kinds: civilian, taxi, corporate, "
                 "police, street, beater",
        "total_weight": round(total, 3),
        "vehicles": vehicles,
    }
    with open(os.path.join(ROOT, "assets", "vehicles", "index.json"), "w") as f:
        json.dump(idx, f, indent=1, ensure_ascii=False)
    print("[export] assets/vehicles/index.json:", len(vehicles), "vehicles")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names = [a for a in argv if not a.startswith("--") and a not in ("webp", "png")]
    fmt = arg("--format", "webp").upper()
    if names == ["all"]:
        from specs import FLEET
        names = FLEET
    for vid in names:
        if vid == "index":
            continue
        export_vehicle(vid, "WEBP" if fmt == "WEBP" else "AUTO", "--no-legacy" not in argv)
    write_index()


if __name__ == "__main__":
    main()
