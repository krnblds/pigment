"""Proof renders of the exported fleet (headless Blender 5.2, Cycles / OptiX).

    blender -b --factory-startup --python tools/vehicles/render.py -- MODE [--only a,b] [--samples N] [--out DIR]

MODE:
    studio    one 3/4 front shot per vehicle in the night studio (wet black floor, overhead strips,
              cyan / magenta neon), the same set-up as docs/agents/car/car_studio_front34.png
    lineup    every vehicle side by side at night on wet asphalt: sodium street lights, neon,
              headlamps on (spot lights at the Headlight_* empties)
    variants  a contact sheet: one row per vehicle, one cell per variant
    all       the three

Everything imports assets/vehicles/<id>/<id>.glb (what Godot gets) and switches variants with
the file's KHR_materials_variants mappings.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "car"))

import fleet as F  # noqa: E402
import render_car as RC  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = argv[0] if argv else "studio"


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


OUT = opt("--out", os.path.join(ROOT, "docs", "agents", "fleet"))
SAMPLES = int(opt("--samples", "160"))
RC.SAMPLES = SAMPLES
ONLY = opt("--only", "")
ORDER = ["mame", "hayate", "tsubame", "kago", "hakobi", "kaiun"]


def fleet():
    from specs import FLEET
    names = [n for n in ORDER if n in FLEET]
    if ONLY:
        names = [n for n in names if n in ONLY.split(",")]
    return names


def enable_variants_ui():
    prefs = bpy.context.preferences.addons["io_scene_gltf2"].preferences
    if not prefs.KHR_materials_variants_ui:
        prefs.KHR_materials_variants_ui = True


def import_vehicle(vid, lod="", loc=(0, 0, 0), yaw=0.0):
    """Import <id>.glb under an empty at loc / yaw; returns (root empty, objects)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ROOT, "assets", "vehicles", vid, f"{vid}{lod}.glb"))
    objs = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new(f"V_{vid}", None)
    bpy.context.scene.collection.objects.link(root)
    for o in objs:
        if o.parent is None:
            o.parent = root
        if o.name.startswith("Collider"):
            o.hide_render = True
            o.hide_set(True)
    root.location = loc
    root.rotation_euler = (0, 0, yaw)
    bpy.context.view_layer.update()
    return root, objs


def set_variant(objs, idx):
    """Show variant `idx` (KHR_materials_variants mappings stored by Blender's importer)."""
    for o in objs:
        if o.type != "MESH" or not hasattr(o.data, "gltf2_variant_mesh_data"):
            continue
        for d in o.data.gltf2_variant_mesh_data:
            if any(v.variant.variant_idx == idx for v in d.variants):
                o.data.materials[d.material_slot_index] = d.material


def bbox(objs):
    pts = []
    for o in objs:
        if o.type == "MESH" and not o.name.startswith("Collider"):
            pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def headlamp_spots(root, objs, energy=900, spread=48):
    """Real lights at the contract's lamp empties, shining along the vehicle's forward / back
    (in Godot: a SpotLight3D at the empty, whose local -Z is the beam)."""
    fwd = (root.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
    for o in objs:
        if o.type == "EMPTY" and o.name.startswith(("Headlight_", "Taillight_")):
            head = o.name.startswith("Head")
            d = bpy.data.lights.new(o.name + "_L", "SPOT")
            d.energy = energy if head else 25
            d.spot_size = math.radians(spread if head else 120)
            d.spot_blend = 0.6
            d.color = (1.0, 0.92, 0.8) if head else (1.0, 0.05, 0.03)
            d.shadow_soft_size = 0.05
            L = bpy.data.objects.new(o.name + "_L", d)
            bpy.context.scene.collection.objects.link(L)
            L.location = o.matrix_world.translation
            beam = (fwd if head else -fwd) + Vector((0, 0, -0.10 if head else 0.0))
            L.rotation_euler = beam.normalized().to_track_quat("-Z", "Y").to_euler()


def frame_camera(objs, azim=-38.0, elev=7.0, lens=50, pad=1.18, name="cam"):
    lo, hi = bbox(objs)
    c = (lo + hi) / 2
    size = hi - lo
    tgt = Vector((c.x, c.y - size.y * 0.06, lo.z + size.z * 0.42))
    r = max(size.length * 0.5, 1.2)
    fov = 2 * math.atan(18 / lens)    # 36 mm sensor
    dist = r * pad / math.tan(fov / 2) * 0.82
    a, e = math.radians(azim), math.radians(elev)
    loc = tgt + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * dist
    return RC.camera(name, tuple(loc), tuple(tgt), lens)


# ------------------------------------------------------------------ modes


def studio():
    names = fleet()
    os.makedirs(OUT, exist_ok=True)
    for vid in names:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        enable_variants_ui()
        RC.cycles((1280, 768))
        RC.night_studio()
        root, objs = import_vehicle(vid)
        cam = frame_camera(objs, azim=-40, elev=8, pad=1.28)
        RC.shoot(cam, os.path.join(OUT, f"{vid}_studio_front34.png"))


def asphalt_floor(size=80):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    fl = bpy.context.object
    fl.name = "WetAsphalt"
    m = bpy.data.materials.new("WetAsphalt")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # puddles: large noise -> wet (mirror) vs damp asphalt
    pud = nt.nodes.new("ShaderNodeTexNoise")
    pud.inputs["Scale"].default_value = 0.45
    pud.inputs["Detail"].default_value = 4
    nt.links.new(tc.outputs["Object"], pud.inputs["Vector"])
    wet = nt.nodes.new("ShaderNodeMapRange")
    wet.inputs["From Min"].default_value = 0.47
    wet.inputs["From Max"].default_value = 0.53
    nt.links.new(pud.outputs["Fac"], wet.inputs["Value"])
    # aggregate: fine noise for colour and bump
    agg = nt.nodes.new("ShaderNodeTexNoise")
    agg.inputs["Scale"].default_value = 140
    agg.inputs["Detail"].default_value = 2
    nt.links.new(tc.outputs["Object"], agg.inputs["Vector"])
    col = nt.nodes.new("ShaderNodeMix")
    col.data_type = "RGBA"
    col.inputs["A"].default_value = (0.020, 0.020, 0.022, 1)
    col.inputs["B"].default_value = (0.045, 0.044, 0.046, 1)
    nt.links.new(agg.outputs["Fac"], col.inputs["Factor"])
    dark = nt.nodes.new("ShaderNodeMix")
    dark.data_type = "RGBA"
    nt.links.new(col.outputs["Result"], dark.inputs["A"])
    dark.inputs["B"].default_value = (0.006, 0.006, 0.007, 1)
    nt.links.new(wet.outputs["Result"], dark.inputs["Factor"])
    nt.links.new(dark.outputs["Result"], b.inputs["Base Color"])
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.62
    rough.inputs["To Max"].default_value = 0.02
    nt.links.new(wet.outputs["Result"], rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], b.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bstr = nt.nodes.new("ShaderNodeMapRange")
    bstr.inputs["To Min"].default_value = 1.0
    bstr.inputs["To Max"].default_value = 0.0
    nt.links.new(wet.outputs["Result"], bstr.inputs["Value"])
    nt.links.new(bstr.outputs["Result"], bump.inputs["Strength"])
    nt.links.new(agg.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    fl.data.materials.append(m)
    # lane markings: worn white dashes
    mm = RC.emissive_mat("LaneWhite", (0.7, 0.7, 0.68), 0.0)
    pm = bpy.data.materials.new("LanePaint")
    pm.use_nodes = True
    pb = pm.node_tree.nodes["Principled BSDF"]
    pb.inputs["Base Color"].default_value = (0.55, 0.55, 0.52, 1)
    pb.inputs["Roughness"].default_value = 0.35
    for i in range(-6, 7):
        bpy.ops.mesh.primitive_plane_add(size=1, location=(i * 3.4, -3.6, 0.002))
        d = bpy.context.object
        d.scale = (1.6, 0.10, 1)
        d.data.materials.append(pm)
    return fl


def night_street():
    sc = bpy.context.scene
    w = bpy.data.worlds.new("NightStreet")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.006, 0.008, 0.016, 1)
    bg.inputs["Strength"].default_value = 1.0
    sc.world = w
    asphalt_floor()
    # sodium street lights overhead (pools of orange on the wet road)
    for i, x in enumerate((-9.0, 0.0, 9.0)):
        d = bpy.data.lights.new(f"Sodium{i}", "SPOT")
        d.energy = 2600
        d.color = (1.0, 0.62, 0.30)
        d.spot_size = math.radians(95)
        d.spot_blend = 0.8
        d.shadow_soft_size = 0.3
        o = bpy.data.objects.new(f"Sodium{i}", d)
        o.location = (x, 0.5, 6.0)
        sc.collection.objects.link(o)
        RC.neon_tube(f"LampHead{i}", (x - 0.4, 1.0, 7.05), (x + 0.4, 1.0, 7.05), (1.0, 0.6, 0.3), 30, 0.05)
    # a wall of lit billboards and signs behind the cars (the town's story decals)
    signs = [("billboard_meridian", -9.5, 4.2, 4.2), ("blade_soba", -4.6, 3.6, 1.1), ("billboard_dreamlink", 0.2, 4.6, 4.4),
             ("sign_score_reset", 4.8, 3.0, 2.4), ("billboard_noctis", 9.8, 4.4, 4.2), ("sign_memory_pawn", 14.0, 3.2, 2.2),
             ("sign_hoshikawa_security", -14.0, 3.4, 2.6)]
    for i, (img, x, z, w_) in enumerate(signs):
        path = os.path.join(ROOT, "assets", "decals", "story", img + ".png")
        if not os.path.exists(path):
            continue
        im = bpy.data.images.load(path)
        h = w_ * im.size[1] / im.size[0]
        bpy.ops.mesh.primitive_plane_add(size=1, location=(x, 8.9, z + 0.9), rotation=(math.radians(90), 0, 0))
        p = bpy.context.object
        p.scale = (w_, h, 1)
        m = bpy.data.materials.new(f"Sign{i}")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = im
        e = nt.nodes.new("ShaderNodeEmission")
        e.inputs["Strength"].default_value = 3.0
        mix = nt.nodes.new("ShaderNodeMixShader")
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(t.outputs["Color"], e.inputs["Color"])
        nt.links.new(t.outputs["Alpha"], mix.inputs["Fac"])
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(e.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], o.inputs[0])
        p.data.materials.append(m)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 9.2, 4.0), rotation=(math.radians(90), 0, 0))
    wall = bpy.context.object
    wall.scale = (70, 12, 1)
    wm = bpy.data.materials.new("Wall")
    wm.use_nodes = True
    wm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.02, 0.02, 0.025, 1)
    wall.data.materials.append(wm)
    RC.neon_tube("NeonLow", (-16, 8.6, 0.6), (16, 8.6, 0.6), (0.1, 0.85, 1.0), 25, 0.03)
    RC.neon_tube("NeonHigh", (-16, 8.6, 6.9), (16, 8.6, 6.9), (1.0, 0.1, 0.6), 20, 0.03)
    RC.strip_light("Fill", (0, -22, 6), (10, 2), (math.radians(72), 0, 0), (0.6, 0.7, 1.0), 260)
    RC.strip_light("RimMagenta", (-14, 2, 3), (0.5, 10), (0, math.radians(-75), 0), (1.0, 0.12, 0.6), 600)


LINEUP_VARIANT = {"mame": "mint", "hayate": "purple", "tsubame": "security", "kago": "meridian", "hakobi": "dreamlink", "kaiun": "logistics"}


def lineup():
    import json
    bpy.ops.wm.read_factory_settings(use_empty=True)
    enable_variants_ui()
    RC.cycles((1920, 900))
    night_street()
    names = fleet()
    widths = {}
    infos = {}
    for vid in names:
        infos[vid] = json.load(open(os.path.join(ROOT, "assets", "vehicles", vid, f"{vid}.json")))
    # a staggered row, every car turned 3/4 to the camera, small to big
    n = len(names)
    sp = 3.55
    allobjs = []
    for k, vid in enumerate(names):
        x = (k - (n - 1) / 2) * sp
        L = infos[vid]["dimensions"].get("length", 4.4)
        y = 0.9 * ((k % 2) - 0.5) + 0.25 * (L - 4.4)
        root, objs = import_vehicle(vid, loc=(x, y, 0), yaw=math.radians(-34 + 4 * (k - (n - 1) / 2)))
        vname = LINEUP_VARIANT.get(vid)
        idx = next((v["index"] for v in infos[vid]["variants"] if v["name"] == vname), 0)
        set_variant(objs, idx)
        headlamp_spots(root, objs)
        allobjs += objs
    # soft key from the front-left and a cool fill, low: reflection lines along the bodies
    RC.strip_light("Key", (-9.0, -9.0, 3.2), (6.0, 1.2), (math.radians(68), 0, math.radians(-45)), (0.85, 0.9, 1.0), 900)
    RC.strip_light("Key2", (9.0, -9.0, 2.6), (6.0, 1.0), (math.radians(70), 0, math.radians(45)), (1.0, 0.6, 0.35), 90)
    cam = RC.camera("LineupCam", (0.0, -19.0, 1.25), (0.0, 0.6, 1.15), 30)
    RC.shoot(cam, os.path.join(OUT, "fleet_lineup_night.png"))


def variants_sheet():
    import json
    names = fleet()
    os.makedirs(OUT, exist_ok=True)
    cell = (480, 300)
    rows = []
    for vid in names:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        enable_variants_ui()
        RC.cycles(cell)
        bpy.context.scene.cycles.samples = min(SAMPLES, 64)
        RC.night_studio()
        info = json.load(open(os.path.join(ROOT, "assets", "vehicles", vid, f"{vid}.json")))
        root, objs = import_vehicle(vid)
        cam = frame_camera(objs, azim=-42, elev=10, pad=1.05)
        paths = []
        for v in info["variants"]:
            set_variant(objs, v["index"])
            p = os.path.join(OUT, f"_v_{vid}_{v['index']}.png")
            RC.shoot(cam, p)
            paths.append(p)
        rows.append(paths)
    # assemble: rows of up to 8 cells, padded with black
    cols = max(len(r) for r in rows)
    from array import array
    w, h = cell
    big = bpy.data.images.new("vsheet", cols * w, len(rows) * h, alpha=False)
    px = array("f", [0.0]) * (cols * w * len(rows) * h * 4)
    for ri, r in enumerate(rows):
        for ci, p in enumerate(r):
            im = bpy.data.images.load(p)
            src = array("f", [0.0]) * (w * h * 4)
            im.pixels.foreach_get(src)
            cy = len(rows) - 1 - ri
            for y in range(h):
                o = ((cy * h + y) * cols * w + ci * w) * 4
                px[o:o + w * 4] = src[y * w * 4:(y + 1) * w * 4]
            bpy.data.images.remove(im)
            os.remove(p)
    big.pixels.foreach_set(px)
    out = os.path.join(OUT, "fleet_variants.png")
    big.filepath_raw = out
    big.file_format = "PNG"
    big.save()
    print("[render]", out)


def main():
    os.makedirs(OUT, exist_ok=True)
    if MODE in ("studio", "all"):
        studio()
    if MODE in ("lineup", "all"):
        lineup()
    if MODE in ("variants", "all"):
        variants_sheet()


if __name__ == "__main__":
    main()
