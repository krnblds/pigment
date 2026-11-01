"""Build the tree kit (headless Blender 5.2):

    blender -b --factory-startup --python tools/trees/build_trees.py [-- keys...] [--no-impostors] [--samples 24]

For every variant key (species.variant_keys(): tree_<species>_<a..>[_<look>], tree_planter_*):
    assets/trees/<key>.glb         LOD0: tubes (bark) + folded leaf cards
    assets/trees/<key>_lod1.glb    LOD1: trunk + scaffolds, about a quarter of the cards (bigger, flat)
    assets/trees/<key>_lod2.glb    LOD2: impostor, 3 crossed vertical quads + 1 horizontal (8 triangles)
    assets/trees/impostors/<key>_albedo.png / _normal.png   1024 x 256 atlases (4 views, Cycles)
    assets/trees/index.json        species, variants, files, triangle counts, LOD distances, colliders,
                                   textures, wind attribute layout
Needs assets/trees/textures/ (tools/trees/tree_textures.py --run). Deterministic: the same
species parameters and seeds give the same meshes.

glbs: Y up, the root at the origin, materials by name only (TreeBark_<sp>, TreeLeaves,
TreeImpostor_<key>), vertex colour COLOR_0 (wind / occlusion) and TEXCOORD_1 (height, card flag).
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import species as S  # noqa: E402
import treegen as TG  # noqa: E402
import tree_blender as TB  # noqa: E402

OUT = os.path.join(ROOT, "assets", "trees")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


def atlas_cells():
    p = os.path.join(OUT, "textures", "leaves_layout.json")
    if not os.path.isfile(p):
        print("no leaves_layout.json: placeholder UVs")
        return TG.default_cells()
    lay = json.load(open(p, encoding="utf-8"))
    cells = {}
    for c in lay["cells"]:
        u0, v0, u1, v1 = c["uv_gl"]           # Blender / GL convention: v0 = bottom = the card's stem
        # pull in half a texel so bilinear taps never reach the padding
        e = 0.5 / 4096
        cells[c["name"]] = (u0 + e, v0 + e, u1 - e, v1 - e)
    return cells


# ------------------------------------------------------------------ mesh
def to_mesh(name, md, sp):
    """MeshData -> bpy mesh: slot 0 bark, slot 1 leaves; custom normals, UVMap, UV2, Col."""
    P, F, N, UV, UV2, C, MI = [], [], [], [], [], [], []
    base = 0
    for slot, mat in enumerate(("bark", "leaf")):
        a = md.arrays(mat)
        if a is None:
            continue
        P.append(a["p"]); N.append(a["n"]); UV.append(a["uv"]); UV2.append(a["uv2"]); C.append(a["c"])
        F.append(a["f"] + base)
        MI.append(np.full(len(a["f"]), slot, np.int32))
        base += len(a["p"])
    P, F, N, UV, UV2, C, MI = (np.concatenate(x) for x in (P, F, N, UV, UV2, C, MI))
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(P))
    me.vertices.foreach_set("co", P.astype(np.float32).ravel())
    nl = len(F) * 3
    me.loops.add(nl)
    me.loops.foreach_set("vertex_index", F.astype(np.int32).ravel())
    me.polygons.add(len(F))
    me.polygons.foreach_set("loop_start", np.arange(0, nl, 3, dtype=np.int32))
    me.polygons.foreach_set("material_index", MI)
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    lv = F.ravel()
    uv = me.uv_layers.new(name="UVMap")
    uv.data.foreach_set("uv", UV[lv].astype(np.float32).ravel())
    uv2 = me.uv_layers.new(name="UV2")
    uv2.data.foreach_set("uv", UV2[lv].astype(np.float32).ravel())
    ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    ca.data.foreach_set("color", C.astype(np.float32).ravel())
    me.color_attributes.active_color = ca
    me.polygons.foreach_set("use_smooth", np.ones(len(F), bool))
    me.normals_split_custom_set_from_vertices([tuple(n) for n in N])
    me.materials.append(TB.bark_material(ROOT, sp))
    me.materials.append(TB.leaf_material(ROOT))
    return me


def export_glb(me, path):
    o = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(o)
    for x in bpy.context.selected_objects:
        x.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    kw = dict(filepath=path, use_selection=True, export_format="GLB", export_yup=True, export_apply=False,
              export_texcoords=True, export_normals=True, export_materials="EXPORT", export_cameras=False,
              export_lights=False, export_vertex_color="ACTIVE", export_all_vertex_colors=False)
    try:
        bpy.ops.export_scene.gltf(export_image_format="NONE", **kw)
    except TypeError:
        bpy.ops.export_scene.gltf(**kw)
    bpy.data.objects.remove(o)


# ------------------------------------------------------------------ impostors
VIEWS = [0.0, 60.0, 120.0]   # azimuths of the 3 vertical quads (deg); cell 3 = top view
CELL = 256


def bounds(me):
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    cx = float((co[:, 0].min() + co[:, 0].max()) / 2)
    cy = float((co[:, 1].min() + co[:, 1].max()) / 2)
    r = float(np.max(np.hypot(co[:, 0] - cx, co[:, 1] - cy)))
    return r, float(max(co[:, 2].max(), 0.5)), cx, cy


def flat_material(kind):
    """Emission-only overrides for the impostor passes: albedo x crown occlusion (alpha clipped),
    object-space normal encoded 0..1."""
    name = f"_imp_{kind}"
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    tp = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tp.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    leaf = kind.endswith("leaf")
    d = os.path.join(ROOT, "assets", "trees", "textures")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "Col"
    if kind.startswith("albedo"):
        if leaf:
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = TB._img(os.path.join(d, "leaves_albedo.png"))
            col, alpha = t.outputs["Color"], t.outputs["Alpha"]
        else:
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = TB._img(os.path.join(d, f"bark_{kind.split('_')[1]}_albedo.jpg"))
            col, alpha = t.outputs["Color"], None
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1.0
        nt.links.new(col, mul.inputs[6])
        nt.links.new(attr.outputs["Alpha"], mul.inputs[7])
        nt.links.new(mul.outputs[2], em.inputs["Color"])
    else:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        mad = nt.nodes.new("ShaderNodeVectorMath")
        mad.operation = "MULTIPLY_ADD"
        mad.inputs[1].default_value = (0.5, 0.5, 0.5)
        mad.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(geo.outputs["Normal"], mad.inputs[0])
        nt.links.new(mad.outputs[0], em.inputs["Color"])
        alpha = None
        if leaf:
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = TB._img(os.path.join(d, "leaves_albedo.png"))
            alpha = t.outputs["Alpha"]
    if alpha is not None:
        gt = nt.nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        gt.inputs[1].default_value = 0.42
        nt.links.new(alpha, gt.inputs[0])
        nt.links.new(gt.outputs[0], mix.inputs[0])
    else:
        mix.inputs[0].default_value = 1.0
    return m


def setup_render(samples):
    sc = bpy.context.scene
    try:
        sc.render.engine = "CYCLES"
    except TypeError:
        pass
    sc.cycles.samples = samples
    sc.cycles.use_denoising = False
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = dev
                prefs.get_devices()
                for d in prefs.devices:
                    d.use = True
                sc.cycles.device = "GPU"
                break
            except Exception:
                continue
    except Exception:
        pass
    sc.cycles.max_bounces = 0
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = CELL * 2
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    sc.render.filter_size = 1.0
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = True
    bg = next(n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Strength"].default_value = 0.0


def render_impostor(key, me, sp, tmp):
    """4 orthographic views -> albedo / normal atlases (1024 x 256, RGBA)."""
    sc = bpy.context.scene
    o = bpy.data.objects.new("_imp", me)
    sc.collection.objects.link(o)
    cam_d = bpy.data.cameras.new("_impcam")
    cam_d.type = "ORTHO"
    cam = bpy.data.objects.new("_impcam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    R, Hh, cx, cy = bounds(me)
    Sv = max(Hh, 2 * R) * 1.04
    St = 2 * R * 1.04
    orig = list(me.materials)
    atl = {}
    for kind in ("albedo", "normal"):
        me.materials[0] = flat_material(f"{kind}_{sp}_bark")
        me.materials[1] = flat_material(f"{kind}_leaf")
        ims = []
        for vi in range(4):
            if vi < 3:
                a = math.radians(VIEWS[vi])
                d = 60.0
                # the camera looks along -dir: quad k faces dir (its normal), seen from that side
                dirv = (math.sin(a), -math.cos(a))
                cam.location = (cx + dirv[0] * d, cy + dirv[1] * d, Sv / 2)
                cam.rotation_euler = (math.pi / 2, 0, a)
                cam_d.ortho_scale = Sv
            else:
                cam.location = (cx, cy, Hh + 30)
                cam.rotation_euler = (0, 0, 0)
                cam_d.ortho_scale = St
            cam_d.clip_end = 200
            p = os.path.join(tmp, f"{key}_{kind}_{vi}.png")
            sc.render.filepath = p
            bpy.ops.render.render(write_still=True)
            im = bpy.data.images.load(p)
            px = np.array(im.pixels[:], np.float32).reshape(CELL * 2, CELL * 2, 4)
            bpy.data.images.remove(im)
            px = px.reshape(CELL, 2, CELL, 2, 4).mean(axis=(1, 3))       # 2x supersampling
            ims.append(px)
        atlas = np.concatenate(ims, axis=1)                              # rows bottom-up (Blender pixels)
        # un-premultiply and bleed colour into the transparent texels (no dark halos when mipmapped)
        a = atlas[..., 3:4]
        rgb = np.where(a > 1e-4, atlas[..., :3] / np.maximum(a, 1e-4), 0)
        from_mask = a[..., 0] > 0.5
        rgb = bleed(rgb, from_mask)
        atl[kind] = np.concatenate([rgb, a], axis=2)
    for i, m in enumerate(orig):
        me.materials[i] = m
    bpy.data.objects.remove(o)
    bpy.data.objects.remove(cam)
    bpy.data.cameras.remove(cam_d)
    os.makedirs(os.path.join(OUT, "impostors"), exist_ok=True)
    for kind, px in atl.items():
        im = bpy.data.images.new(f"_{key}_{kind}", px.shape[1], px.shape[0], alpha=True)
        im.pixels.foreach_set(px.astype(np.float32).ravel())
        im.filepath_raw = os.path.join(OUT, "impostors", f"{key}_{kind}.png")
        im.file_format = "PNG"
        im.save()
        bpy.data.images.remove(im)
    return Sv, St, R, Hh, cx, cy


def bleed(rgb, mask, iters=12):
    rgb = rgb.copy()
    m = mask.copy()
    for _ in range(iters):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(m.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(rgb, dy, 0), dx, 1)
            sm = np.roll(np.roll(m, dy, 0), dx, 1)
            acc += sh * sm[..., None]
            cnt += sm
        grow = (~m) & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        m = m | grow
    if (~m).any():
        mean = rgb[mask].mean(axis=0) if mask.any() else np.array([0.1, 0.15, 0.05])
        rgb[~m] = mean
    return rgb


def impostor_mesh(key, Sv, St, Hh, cx=0.0, cy=0.0):
    """3 vertical quads (VIEWS) + 1 horizontal quad at 60 % height; UVs into the 4-cell atlas.
    Normals: the quad normals (the shader uses the baked normal atlas)."""
    me = bpy.data.meshes.new(f"{key}_lod2")
    verts, faces, uvs, nrm = [], [], [], []
    for vi, az in enumerate(VIEWS):
        a = math.radians(az)
        right = (math.cos(a), math.sin(a), 0.0)
        n = (math.sin(a), -math.cos(a), 0.0)
        h = Sv / 2
        b = len(verts)
        for (sx, sz, u, v) in ((-1, 0, 0, 0), (1, 0, 1, 0), (1, 2, 1, 1), (-1, 2, 0, 1)):
            verts.append((cx + right[0] * sx * h, cy + right[1] * sx * h, sz * h))
            uvs.append(((vi + u) / 4.0, v))
            nrm.append(n)
        faces.append((b, b + 1, b + 2, b + 3))
    h = St / 2
    z = Hh * 0.62
    b = len(verts)
    for (sx, sy, u, v) in ((-1, -1, 0, 0), (1, -1, 1, 0), (1, 1, 1, 1), (-1, 1, 0, 1)):
        verts.append((cx + sx * h, cy + sy * h, z))
        uvs.append(((3 + u) / 4.0, v))
        nrm.append((0, 0, 1))
    faces.append((b, b + 1, b + 2, b + 3))
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            uv.data[li].uv = uvs[me.loops[li].vertex_index]
    uv2 = me.uv_layers.new(name="UV2")
    for li, l in enumerate(me.loops):
        uv2.data[li].uv = (verts[l.vertex_index][2] / max(Hh, 0.1), 2.0)    # y = 2: impostor
    ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    for i, vv in enumerate(verts):
        ca.data[i].color = (0.0, 0.0, 0.0, 1.0)
    me.color_attributes.active_color = ca
    me.polygons.foreach_set("use_smooth", [False] * len(faces))
    me.normals_split_custom_set_from_vertices(nrm)
    me.materials.append(TB.impostor_material(ROOT, key))
    return me


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    cells = atlas_cells()
    keys = S.variant_keys()
    want = [a for a in ARGS if not a.startswith("--") and not a.replace(".", "").isdigit()]
    if want:
        keys = [k for k in keys if k[0] in want or k[1] in want]
    samples = int(opt("--samples", 24))
    setup_render(samples)
    tmp = os.path.join(ROOT, "target", "trees", "impostor_tmp")
    os.makedirs(tmp, exist_ok=True)
    idx_path = os.path.join(OUT, "index.json")
    idx = json.load(open(idx_path, encoding="utf-8")) if os.path.isfile(idx_path) else {"variants": {}}
    for key, sp, v, look in keys:
        t1 = time.time()
        planter = key[5:] in S.PLANTER_SHRUBS
        sk = TG.grow_planter(key[5:]) if planter else TG.grow(sp, v)
        md0, md1 = TG.build_lod(sk, 0, cells, look), TG.build_lod(sk, 1, cells, look)
        bsp = S.SPECIES[sp]["bark"]
        me0 = to_mesh(key, md0, bsp)
        me1 = to_mesh(f"{key}_lod1", md1, bsp)
        export_glb(me0, os.path.join(OUT, f"{key}.glb"))
        export_glb(me1, os.path.join(OUT, f"{key}_lod1.glb"))
        if not opt("--no-impostors"):
            Sv, St, R, Hh, cx, cy = render_impostor(key, me0, bsp, tmp)
        else:
            R, Hh, cx, cy = bounds(me0)
            Sv, St = max(Hh, 2 * R) * 1.04, 2 * R * 1.04
        me2 = impostor_mesh(key, Sv, St, Hh, cx, cy)
        export_glb(me2, os.path.join(OUT, f"{key}_lod2.glb"))
        kind = "shrub" if "shrub" in S.SPECIES[sp] else sp
        lods = S.LODS.get(kind, S.LODS["default"]) if kind in S.LODS else S.LODS["default"]
        s0, s1 = TG.stats(md0), TG.stats(md1)
        idx["variants"][key] = {
            "species": sp, "variant": v, "look": look, "planter": planter,
            "title": S.SPECIES[sp]["title"], "bark": bsp,
            "files": {"lod0": f"{key}.glb", "lod1": f"{key}_lod1.glb", "lod2": f"{key}_lod2.glb",
                      "impostor_albedo": f"impostors/{key}_albedo.png", "impostor_normal": f"impostors/{key}_normal.png"},
            "tris": {"lod0": s0["total"], "lod0_bark": s0["bark"], "lod0_leaf": s0["leaf"], "lod1": s1["total"], "lod2": 8},
            "lod_m": lods,
            "height": round(Hh, 2), "crown_radius": round(R, 2),
            "collider": sk.collider,
        }
        print(f"{key}: LOD0 {s0['total']} LOD1 {s1['total']} h {Hh:.1f} r {R:.1f}  ({time.time() - t1:.1f} s)", flush=True)
    idx.update({
        "version": 1,
        "generator": "tools/trees (treegen.py + build_trees.py), textures tools/trees/tree_textures.py (Pigment)",
        "coords": "glTF: y up, the root at the origin (the trunk goes 0.35 m below 0 into the ground)",
        "materials": {
            "bark": {"name": "TreeBark_<species>", "albedo": "textures/bark_<species>_albedo.jpg", "normal": "textures/bark_<species>_normal.jpg",
                     "roughness": "textures/bark_<species>_rough.jpg", "uv": "tiling: 1 UV unit = the species' bark tile (BARK in species.py)"},
            "leaves": {"name": "TreeLeaves", "albedo": "textures/leaves_albedo.png (alpha = cut-out)", "normal": "textures/leaves_normal.jpg",
                       "mask": "textures/leaves_mask.jpg (R roughness, G translucency)", "alpha_scissor": 0.42},
            "impostor": {"name": "TreeImpostor_<key>", "albedo": "impostors/<key>_albedo.png (rgb albedo x occlusion, a = cut-out)",
                         "normal": "impostors/<key>_normal.png (object-space normal, Blender z up, encoded 0..1)",
                         "layout": "4 cells across: views at azimuth 0, 60, 120 deg, then top"},
        },
        "attributes": {"COLOR_0.r": "branch flex", "COLOR_0.g": "phase", "COLOR_0.b": "leaf flutter (0 stem .. 1 tip)",
                       "COLOR_0.a": "crown occlusion", "TEXCOORD_1.x": "height / tree height", "TEXCOORD_1.y": "0 bark, 1 leaf card, 2 impostor"},
        "lods": S.LODS,
        "species": {k: {"title": d["title"], "role": d["role"], "bark": d["bark"], "variants": d["variants"], "looks": list(d.get("looks", {}))}
                    for k, d in S.SPECIES.items()},
    })
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)
    print(f"tree kit: {len(keys)} variants -> {OUT} ({time.time() - t0:.0f} s)")


main()
