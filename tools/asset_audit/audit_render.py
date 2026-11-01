"""Neutral-studio tiles for the asset audit (headless Blender 5.2, Cycles).

    blender -b --factory-startup --python tools/asset_audit/audit_render.py -- MANIFEST.json OUTDIR [--samples 24] [--res 420] [--cpu]

MANIFEST is a list of items (see audit_manifest.py):
    {"id": "props/bench", "group": "props", "label": "bench", "kind": "glb", "path": "...glb",
     "pigment": [folder, name]?,         # town kit: Pigment maps applied with blender_pigment
     "cam": {...}?,                      # reuse a framing (before/after at the same camera)
     "focus": [[x, y, z], [x, y, z]]?,   # frame this Blender-space box instead of the whole asset (close-ups)
     "view": [x, y, z]?}                 # camera direction from the target (default 3/4 front-left)
    {"id": "world/container", "kind": "worldkit", "key": "container", "world_json": "...", ...}

Every item is rendered alone in the same studio: mid-grey cyclorama floor, a soft key sun from
the front-left, a cool fill, a rim and a grey sky; 3/4 front view (the asset's front is Blender
-Y), framed to its bounding sphere. Colliders, LOD helpers and empties are hidden. Writes
OUTDIR/<id with / -> __>.png and OUTDIR/stats.json (triangles, size, materials, textured, camera).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        return ARGS[ARGS.index(name) + 1]
    return default


def load_tool(name, extra=None):
    src = os.path.join(ROOT, "tools", name + ".py")
    ns = {"__name__": name, "__file__": src}
    ns.update(extra or {})
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
    return ns


def setup_render(res, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    if "--cpu" in ARGS:
        sc.cycles.device = "CPU"
    else:
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            prefs.compute_device_type = "OPTIX"
            prefs.get_devices()
            for d in prefs.devices:
                d.use = True
            sc.cycles.device = "GPU"
        except Exception as e:  # noqa: BLE001
            print("[audit] GPU setup failed, CPU:", e)
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Base Contrast"


def studio():
    """World, floor and three sun lamps (scale-free, so a cone and a crane light alike)."""
    sc = bpy.context.scene
    w = bpy.data.worlds.new("AuditWorld")
    sc.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.42, 0.44, 0.47, 1)
    bg.inputs["Strength"].default_value = 0.55
    for name, rot, energy, col, ang in (("Key", (52, 0, -38), 3.6, (1.0, 0.96, 0.9), 8),
                                        ("Fill", (62, 0, 70), 0.9, (0.8, 0.88, 1.0), 25),
                                        ("Rim", (35, 0, 160), 2.2, (1.0, 1.0, 1.0), 6)):
        ld = bpy.data.lights.new(name, "SUN")
        ld.energy = energy
        ld.color = col
        ld.angle = math.radians(ang)
        o = bpy.data.objects.new(name, ld)
        o.rotation_euler = tuple(math.radians(a) for a in rot)
        sc.collection.objects.link(o)
    m = bpy.data.materials.new("AuditFloor")
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (0.2, 0.2, 0.21, 1)
    b.inputs["Roughness"].default_value = 0.85
    me = bpy.data.meshes.new("AuditFloor")
    S = 1.0
    me.from_pydata([(-S, -S, 0), (S, -S, 0), (S, S, 0), (-S, S, 0)], [], [(0, 1, 2, 3)])
    me.materials.append(m)
    floor = bpy.data.objects.new("AuditFloor", me)
    sc.collection.objects.link(floor)
    cam = bpy.data.objects.new("AuditCam", bpy.data.cameras.new("AuditCam"))
    cam.data.lens = 50
    cam.data.clip_start = 0.01
    cam.data.clip_end = 5000
    sc.collection.objects.link(cam)
    sc.camera = cam
    return floor, cam


HIDE = ("Collider", "collider", "_LOD", "Socket_", "Light_", "Headlight", "Taillight")


def clear_asset(keep):
    for o in list(bpy.data.objects):
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for d in list(coll):
            if d.users == 0:
                coll.remove(d)


def visible_meshes(objs):
    out = []
    for o in objs:
        if o.type != "MESH" or any(h in o.name for h in HIDE):
            if o.type == "MESH":
                o.hide_render = True
            continue
        if o.hide_render or o.get("hidden"):
            continue
        out.append(o)
    return out


def load_item(it, keep):
    before = set(bpy.data.objects)
    if it["kind"] == "glb":
        bpy.ops.import_scene.gltf(filepath=it["path"])
        new = [o for o in bpy.data.objects if o not in before]
        if it.get("pigment"):
            folder, name = it["pigment"]
            meshes = [o for o in new if o.type == "MESH"]
            if os.path.isfile(os.path.join(folder, name + "_BaseColor.png")):
                apply = load_tool("blender_pigment")["apply_pigment_material"]
                for o in meshes:
                    apply(o, folder, name)
        return new
    if it["kind"] == "worldkit":
        sys.path.insert(0, os.path.join(ROOT, "tools", "world"))
        import world_meshes as WM
        if "kit" not in KIT:
            town = load_tool("blender_town", {"TOWN_NO_AUTOBUILD": True, "TOWN_ROOT": ROOT})
            world = json.load(open(it["world_json"], encoding="utf-8"))
            KIT["kit"] = WM.Kit(ROOT, world, WM.kit_materials(ROOT, town))
            for m in bpy.data.materials:
                m.use_fake_user = True
        me = KIT["kit"].get(it["key"])
        me.use_fake_user = True          # the kit caches its meshes: keep them between items
        o = bpy.data.objects.new(it["key"], me)
        o.color = tuple(it.get("color", (0.4, 0.4, 0.4))) + (1.0,)
        bpy.context.scene.collection.objects.link(o)
        return [o]
    raise ValueError(it["kind"])


KIT = {}


def bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for o in objs:
        for c in o.bound_box:
            p = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def frame(cam, lo, hi, cam_in=None, view=(-1.0, -1.45, 0.75)):
    if cam_in:
        cam.location = Vector(cam_in["loc"])
        cam.rotation_euler = cam_in["rot"]
        cam.data.lens = cam_in.get("lens", 50)
        return cam_in
    c = (lo + hi) / 2
    r = (hi - lo).length / 2
    d = Vector(view).normalized()
    fov = 2 * math.atan(18.0 / cam.data.lens)
    dist = r / math.sin(fov / 2) * 0.92
    cam.location = c + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    return {"loc": list(cam.location), "rot": list(cam.rotation_euler), "lens": cam.data.lens}


def tri_count(objs):
    n = 0
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        n += len(me.loop_triangles)
        ev.to_mesh_clear()
    return n


def textured(objs):
    for o in objs:
        for s in o.material_slots:
            m = s.material
            if m and m.use_nodes and any(n.type == "TEX_IMAGE" and n.image for n in m.node_tree.nodes):
                return True
    return False


def main():
    manifest = json.load(open(ARGS[0], encoding="utf-8"))
    outdir = ARGS[1]
    os.makedirs(outdir, exist_ok=True)
    only = opt("--only")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render(int(opt("--res", 420)), int(opt("--samples", 24)))
    floor, cam = studio()
    keep = set(bpy.data.objects)
    stats_path = os.path.join(outdir, "stats.json")
    stats = json.load(open(stats_path)) if os.path.isfile(stats_path) else {}
    for it in manifest:
        if only and only not in it["id"]:
            continue
        clear_asset(keep | {o for o in bpy.data.objects if o.name.startswith("_keep")})
        try:
            new = load_item(it, keep)
        except Exception as e:  # noqa: BLE001
            print("[audit] FAILED", it["id"], e)
            continue
        vis = visible_meshes(new)
        if not vis:
            print("[audit] nothing visible", it["id"])
            continue
        bpy.context.view_layer.update()
        lo, hi = bounds(vis)
        size = hi - lo
        floor.scale = (max(size.x, size.y, size.z) * 6,) * 3
        floor.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z - 0.002)
        flo, fhi = (Vector(it["focus"][0]), Vector(it["focus"][1])) if it.get("focus") else (lo, hi)
        camd = frame(cam, flo, fhi, it.get("cam"), view=it.get("view", (-1.0, -1.45, 0.75)))
        fn = it["id"].replace("/", "__") + ".png"
        bpy.context.scene.render.filepath = os.path.join(outdir, fn)
        bpy.ops.render.render(write_still=True)
        stats[it["id"]] = {"group": it["group"], "label": it["label"], "file": fn, "tris": tri_count(vis),
                           "size": [round(v, 2) for v in size], "objects": len(vis),
                           "materials": len({s.material.name for o in vis for s in o.material_slots if s.material}),
                           "textured": textured(vis), "cam": camd, "note": it.get("note", "")}
        print("[audit]", it["id"], stats[it["id"]]["tris"], "tris", flush=True)
        json.dump(stats, open(stats_path, "w"), indent=1)


main()
