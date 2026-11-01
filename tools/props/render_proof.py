"""Proof renders for the street props (headless Blender 5.2, Cycles).

    blender -b --factory-startup --python tools/props/render_proof.py -- lineup [--samples 48]
    blender -b --factory-startup --python tools/props/render_proof.py -- street [--samples 128] [--seed 7] [--town-textures DIR]

lineup  renders every exported glb (assets/props/<name>.glb, the Godot files) at night in a
        small studio, one tile each -> docs/agents/props/tiles/ (scratch, then
        tools/props/contact_sheet.py makes docs/agents/props/lineup.png)
street  a test crossroads dressed by tools/props/scatter.py (scatter_props on the same layout as
        scatter.demo_context) with town kit buildings and lamps: docs/agents/props/street_night.png.
        Road / building textures come from the town's Pigment exports (git-ignored):
        --town-textures, default scenes/town/textures (falls back to the main checkout's).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DOCS = os.path.join(ROOT, "docs", "agents", "props")
PROPS = os.path.join(ROOT, "assets", "props")
TEX = os.path.join(ROOT, "scenes", "props", "textures")


def opt(name, default=None):
    if name in ARGS:
        return ARGS[ARGS.index(name) + 1]
    return default


def cycles(samples, w, h):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    if "--cpu" in ARGS:
        sc.cycles.device = "CPU"
        sc.render.threads_mode = "FIXED"
        sc.render.threads = int(opt("--threads", 8))
    else:
      try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        sc.cycles.device = "GPU"
      except Exception as e:  # noqa: BLE001
        print("[render_proof] GPU setup failed, CPU:", e)
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.render.film_transparent = False


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    return new


def prop_lights(objs, scale=1.0):
    """Point / spot lights at the Light_* empties (extras imported as custom properties)."""
    out = []
    for o in objs:
        if o.type != "EMPTY" or "light" not in o.keys():
            continue
        kind = o["light"]
        ld = bpy.data.lights.new(o.name, "SPOT" if kind == "spot" else "POINT")
        ld.color = tuple(o["color"])[:3]
        ld.energy = float(o["energy"]) * scale
        ld.shadow_soft_size = 0.05
        if kind == "spot":
            ld.spot_size = math.radians(50)
        lo = bpy.data.objects.new(o.name + "_L", ld)
        bpy.context.scene.collection.objects.link(lo)
        lo.matrix_world = o.matrix_world.copy()
        out.append(lo)
    return out


def hide_colliders(objs):
    for o in objs:
        if o.name.startswith("Collider"):
            o.hide_render = True
            o.hide_viewport = True


def night_world(strength=0.05, color=(0.05, 0.07, 0.14)):
    w = bpy.data.worlds.new("Night")
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (*color, 1)
    bg.inputs[1].default_value = strength
    bpy.context.scene.world = w


def area(name, loc, rot, size, energy, color):
    ld = bpy.data.lights.new(name, "AREA")
    ld.size = size
    ld.energy = energy
    ld.color = color
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    o.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.scene.collection.objects.link(o)
    return o


# ------------------------------------------------------------------ lineup

def lineup():
    import catalog
    samples = int(opt("--samples", 48))
    only = [a for a in ARGS if a in catalog.PROPS]
    out = os.path.join(DOCS, "tiles")
    os.makedirs(out, exist_ok=True)
    for name in (only or catalog.names()):
        p = os.path.join(PROPS, f"{name}.glb")
        if not os.path.exists(p):
            continue
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cycles(samples, 512, 512)
        night_world(0.35, (0.05, 0.06, 0.1))
        objs = import_glb(p)
        hide_colliders(objs)
        meshes = [o for o in objs if o.type == "MESH" and not o.name.startswith("Collider")]
        if name == "puddle_decal":        # three alternative nodes share the origin: spread them out
            for k, o in enumerate(sorted(meshes, key=lambda o: o.name)):
                o.location.x += (k - 1) * 3.2
                o.visible_shadow = False
            bpy.context.view_layer.update()
        pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
        lo = Vector((min(v.x for v in pts), min(v.y for v in pts), min(v.z for v in pts)))
        hi = Vector((max(v.x for v in pts), max(v.y for v in pts), max(v.z for v in pts)))
        c = (lo + hi) / 2
        ext = max((hi - lo).length, 0.3)
        # floor: dark wet concrete
        bpy.ops.mesh.primitive_plane_add(size=ext * 60, location=(c.x, c.y, lo.z - 0.001))
        fl = bpy.context.object
        m = bpy.data.materials.new("floor")
        bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.025, 1)
        bsdf.inputs["Roughness"].default_value = 0.4
        fl.data.materials.append(m)
        area("key", c + Vector((-ext * 1.2, -ext * 1.5, ext * 1.4)), (50, 0, -35), ext * 1.2, 120 * ext * ext, (1.0, 0.85, 0.75))
        area("rim_c", c + Vector((ext * 1.6, ext * 0.8, ext * 0.6)), (70, 0, 120), ext, 90 * ext * ext, (0.2, 0.8, 1.0))
        area("rim_m", c + Vector((-ext * 1.6, ext * 1.0, ext * 0.5)), (70, 0, -120), ext, 90 * ext * ext, (1.0, 0.2, 0.7))
        prop_lights(objs, 0.6)
        cam_d = bpy.data.cameras.new("cam")
        cam = bpy.data.objects.new("cam", cam_d)
        bpy.context.scene.collection.objects.link(cam)
        bpy.context.scene.camera = cam
        cam_d.lens = 50
        d = Vector((-math.sin(math.radians(32)), -math.cos(math.radians(32)), 0.42)).normalized()
        dist = (ext / 2) / math.sin(cam_d.angle / 2) * 1.02
        cam.location = c + d * dist
        cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.render.filepath = os.path.join(out, f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[render_proof] tile {name}")


# ------------------------------------------------------------------ street

def town_tex_dir():
    d = opt("--town-textures")
    if d:
        return d
    local = os.path.join(ROOT, "scenes", "town", "textures")
    if os.path.isdir(os.path.join(local, "roads")):
        return local
    # a worktree: use the main checkout's generated textures (read only)
    main = os.path.normpath(os.path.join(ROOT, "..", "..", "..", "scenes", "town", "textures"))
    return main


def tiled_material(name, folder, base, tile_m):
    """A Pigment tile set on world-space (object-space) UVs."""
    import blender_pigment as BP
    bpy.ops.mesh.primitive_plane_add(size=1)
    tmp = bpy.context.object
    m = BP.apply_pigment_material(tmp, folder, base, flake=False)
    bpy.data.objects.remove(tmp)
    m.name = name
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / tile_m, 1 / tile_m, 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    for n in nt.nodes:
        if n.type == "TEX_IMAGE":
            nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    for n in nt.nodes:
        if n.type == "BSDF_PRINCIPLED" and "Emission Strength" in n.inputs:
            n.inputs["Emission Strength"].default_value = 0.0
    return m


def slab(name, x0, x1, y0, y1, z0, z1, mat):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object
    o.name = name
    o.scale = (x1 - x0, y1 - y0, z1 - z0)
    o.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(mat)
    return o


def street():
    import blender_pigment as BP
    import catalog
    import scatter
    samples = int(opt("--samples", 128))
    seed = int(opt("--seed", 7))
    tt = town_tex_dir()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    cycles(samples, 1920, 1080)
    night_world(0.9, (0.03, 0.045, 0.09))
    R, W, A = 6.0, 4.0, 60.0
    asphalt = tiled_material("Asphalt", os.path.join(tt, "roads", "asphalt"), "asphalt", 4.0)
    paving = tiled_material("Paving", os.path.join(tt, "roads", "paving"), "paving", 2.0)
    concrete = tiled_material("Concrete", os.path.join(tt, "roads", "concrete"), "concrete", 4.0)
    # road cross and four raised sidewalk blocks (Blender: x, y; Godot z = -y)
    slab("road", -A, A, -A, A, -0.25, 0.0, asphalt)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x0, x1 = sorted((sx * R, sx * A))
            y0, y1 = sorted((sy * R, sy * A))
            slab(f"walk_{sx}_{sy}", x0, x1, y0, y1, -0.2, 0.15, paving)
            cx, cy = sx * (R + 0.1), sy * (R + 0.1)
            slab(f"curb_a_{sx}_{sy}", *sorted((sx * R, sx * A)), *sorted((sy * R, sy * (R + 0.2))), -0.2, 0.16, concrete)
            slab(f"curb_b_{sx}_{sy}", *sorted((sx * R, sx * (R + 0.2))), *sorted((sy * R, sy * A)), -0.2, 0.16, concrete)
    # buildings from the town kit, fronts on the frontage lines
    kits = {}
    for k in ("building_a", "building_b", "street_lamp"):
        objs = import_glb(os.path.join(ROOT, "assets", "town", f"{k}.glb"))
        mesh = next(o for o in objs if o.type == "MESH")
        kits[k] = mesh
        if not mesh.data.materials:
            mesh.data.materials.append(bpy.data.materials.new(f"{k}_slot"))
        mesh.hide_render = True
        mesh.location = (0, 0, -100)
    variants = {"building_a": ["soba", "memory_pawn", "capsules", "implants"], "building_b": ["noodle_row", "night_market", "dream_strip", "pawn_row"]}
    mats = {}

    def bmat(kind, v):
        key = f"{kind}__{v}"
        if key not in mats:
            folder = os.path.join(tt, key)
            if not os.path.isdir(folder):
                folder = os.path.join(tt, kind)
            mats[key] = BP.apply_pigment_material(kits[kind], folder, kind, flake=False)
            mats[key].name = key
        return mats[key]

    import random
    rnd = random.Random(seed)
    for sx in (-1, 1):
        for sy in (-1, 1):
            for axis in ("x", "y"):
                along = R + W + 1.0
                while along < A - 6:
                    kind = rnd.choice(["building_a", "building_b"])
                    src = kits[kind]
                    bb = [Vector(c) for c in src.bound_box]
                    w = max(v.x for v in bb) - min(v.x for v in bb)
                    dpt = max(v.y for v in bb) - min(v.y for v in bb)
                    o = src.copy()
                    o.data = src.data
                    bpy.context.scene.collection.objects.link(o)
                    o.hide_render = False
                    o.material_slots[0].link = "OBJECT"
                    o.material_slots[0].material = bmat(kind, rnd.choice(variants[kind]))
                    # the kit faces -Y (front); turn it to face the street
                    if axis == "x":
                        front = Vector((0, -sy, 0))
                        pos = Vector((sx * (along + w / 2), sy * (R + W + dpt / 2), 0.15))
                    else:
                        front = Vector((-sx, 0, 0))
                        pos = Vector((sx * (R + W + dpt / 2), sy * (along + w / 2), 0.15))
                    yaw = math.atan2(front.x, -front.y)
                    o.rotation_euler = (0, 0, yaw)
                    cmin = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
                    cmax = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
                    off = Matrix.Rotation(yaw, 3, "Z") @ Vector(((cmin.x + cmax.x) / 2, (cmin.y + cmax.y) / 2, cmin.z))
                    o.location = pos - off
                    along += w + 0.4
    BP.apply_pigment_material(kits["street_lamp"], os.path.join(tt, "street_lamp"), "street_lamp", flake=False)
    # street lamps on the curbs, with a sodium point light each
    for sx in (-1, 1):
        for sy in (-1, 1):
            for k in range(3):
                d = R + 8 + k * 16
                for (x, y, yaw) in ((sx * d, sy * (R + 0.6), 0 if sy < 0 else math.pi), (sx * (R + 0.6), sy * d, math.pi / 2 * (1 if sx < 0 else -1))):
                    o = kits["street_lamp"].copy()
                    o.data = kits["street_lamp"].data
                    bpy.context.scene.collection.objects.link(o)
                    o.hide_render = False
                    o.location = (x, y, 0.15)
                    o.rotation_euler = (0, 0, yaw)
                    if not o.data.materials or not o.data.materials[0].name.startswith("Pigment"):
                        pass
                    ld = bpy.data.lights.new("lamp", "POINT")
                    ld.energy = 1400
                    ld.color = (1.0, 0.62, 0.32)
                    ld.shadow_soft_size = 0.2
                    lo = bpy.data.objects.new("lamp", ld)
                    bpy.context.scene.collection.objects.link(lo)
                    lo.location = (x - 0 * sx, y, 6.5)

    # scatter the props with the public API on the same layout (Godot coords: z = -blender y)
    ctx = scatter.demo_context(seed, "commercial")
    ctx["blocked"] += [{"pos": [sx * (R + 8 + k * 16), 0.15, sz * (R + 0.6)], "radius": 0.8} for sx in (-1, 1) for sz in (-1, 1) for k in range(3)]
    ctx["blocked"] += [{"pos": [sx * (R + 0.6), 0.15, sz * (R + 8 + k * 16)], "radius": 0.8} for sx in (-1, 1) for sz in (-1, 1) for k in range(3)]
    over = {"traffic_light_pole": {"density": {"default": 1.0}}, "street_name_sign": {"density": {"default": 1.0}},
            "bus_stop": {"density": {"default": 1.2}}, "cctv_pole": {"density": {"default": 1.0}}, "data_kiosk": {"density": {"default": 1.2}},
            "holo_pylon": {"density": {"default": 0.6}}, "ramen_cart": {"density": {"default": 0.8}}, "steam_vent": {"density": {"default": 0.06}}}
    rules = {n: over.get(n, {}) for n in catalog.names()}
    placements = scatter.scatter_props(ctx, rules)
    with open(os.path.join(DOCS, "street_scatter.json"), "w") as f:
        json.dump({"context": "scatter.demo_context(%d, 'commercial') + lamps blocked" % seed, "rules_override": over,
                   "summary": scatter.summary(placements), "placements": placements}, f, indent=0)
    # import each glb once, instance it per placement (with that placement's variant textures)
    protos = {}
    for pl in placements:
        name = pl["prop"]
        if name not in protos:
            objs = import_glb(os.path.join(PROPS, pl["file"]))
            hide_colliders(objs)
            root = next(o for o in objs if o.parent is None)
            protos[name] = (root, objs)
            for o in objs:
                o.hide_render = True
    mats_v = {}

    def variant_mat(name, v, base_mat):
        folder = os.path.join(TEX, f"{name}__{v}")
        if not os.path.isdir(folder):
            return base_mat
        key = (name, v)
        if key not in mats_v:
            tmp = bpy.data.objects.new("tmp", bpy.data.meshes.new("tmp"))
            mats_v[key] = BP.apply_pigment_material(tmp, folder, name, flake=False)
            mats_v[key].name = f"{name}__{v}"
        return mats_v[key]

    n = 0
    for pl in placements:
        root, objs = protos[pl["prop"]]
        x, y, z = pl["pos"]
        M = Matrix.Translation((x, -z, y)) @ Matrix.Rotation(pl["yaw"], 4, "Z") @ Matrix.Diagonal((*pl["scale"], 1))
        base = root.matrix_world.copy()
        for o in objs:
            if o.name.startswith("Collider"):
                continue
            c = o.copy()
            if o.type == "MESH":
                c.data = o.data
                if o.material_slots:
                    c.material_slots[0].link = "OBJECT"
                    c.material_slots[0].material = variant_mat(pl["prop"], pl["variant"], o.material_slots[0].material)
            bpy.context.scene.collection.objects.link(c)
            c.parent = None
            c.matrix_world = M @ base.inverted() @ o.matrix_world
            c.hide_render = False
            if o.type == "EMPTY":
                prop_lights([c], 1.0)
        n += 1
    print(f"[render_proof] placed {n} props: {scatter.summary(placements)}")
    # camera: street level on the (-x, +y) sidewalk looking at the far corner
    cam_d = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam_d.lens = float(opt("--lens", 24))
    loc = [float(v) for v in opt("--cam", "-16,-3.5,1.7").split(",")]
    tgt = [float(v) for v in opt("--target", "4,-9,2.2").split(",")]
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.render.filepath = os.path.join(DOCS, opt("--out", "street_night.png"))
    bpy.ops.render.render(write_still=True)
    print("[render_proof] street done")


if __name__ == "__main__":
    os.makedirs(DOCS, exist_ok=True)
    if "lineup" in ARGS:
        lineup()
    if "street" in ARGS:
        street()
