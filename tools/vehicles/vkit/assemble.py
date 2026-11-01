"""Turn the built parts into the shipped node layout.

UVs (one texture set per material), the `<id>_parts.json` sidecar for Pigment, the source
meshes Pigment paints, wheel / caliper nodes, the collider, the lamp empties, LOD1 and LOD2,
and `<id>_info.json`.
"""
import json
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import body as B
from . import cfg
from . import panels as P
from . import wheels as WH
from .geom import apply_mods

# groups that are hard to see get half the texel density
LOW_DENSITY = ("underbody", "underbody_metal", "suspension", "spring", "interior_carpet", "interior_dark",
               "interior_plastic", "black_metal")
HIDDEN_AT_LOD1 = ("underbody_metal", "suspension", "spring", "interior_fabric", "interior_plastic", "interior_dark",
                  "interior_leather", "interior_carpet", "screen", "black_metal", "underbody")
# LOD2 (distant traffic) keeps the shell, glass, lamps and the big trims only
HIDDEN_AT_LOD2 = HIDDEN_AT_LOD1 + ("rubber", "frit", "mirror", "chrome", "grille", "exhaust", "plate", "lens_clear",
                                   "lens_red", "lens_amber")


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def to_gltf(v):
    """Blender (x, y, z) -> glTF (x, z, -y)."""
    return [round(v[0], 4), round(v[2], 4), round(-v[1], 4)]


def select_only(obs):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]


def uv_area(me):
    uv = me.uv_layers.active.data
    a2 = 0.0
    for p in me.polygons:
        pts = [uv[li].uv for li in p.loop_indices]
        s2 = 0.0
        for k in range(len(pts)):
            x0, y0 = pts[k]
            x1, y1 = pts[(k + 1) % len(pts)]
            s2 += x0 * y1 - x1 * y0
        a2 += abs(s2) / 2
    return a2


def unwrap(ob, scale=1.0):
    """Smart-project one part, then rescale its UVs to real-world size (UV area ~ surface area),
    so packing the joined mesh gives every part the same texel density (times `scale`)."""
    select_only([ob])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    me = ob.data
    a3 = sum(p.area for p in me.polygons)
    a2 = uv_area(me)
    k = math.sqrt(a3 / a2) * scale if a2 > 1e-12 else scale
    for d in me.uv_layers.active.data:
        d.uv = d.uv * k


def components(ob):
    """Connected pieces of an object (vertex connectivity): [{center, size, triangles}] in glTF coords."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.transform(ob.matrix_world)
    bm.faces.ensure_lookup_table()
    seen = set()
    out = []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g)
            for v in g.verts:
                for h in v.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        vs = {v for g in comp for v in g.verts}
        lo = Vector((min(v.co.x for v in vs), min(v.co.y for v in vs), min(v.co.z for v in vs)))
        hi = Vector((max(v.co.x for v in vs), max(v.co.y for v in vs), max(v.co.z for v in vs)))
        c = (lo + hi) / 2
        sz = hi - lo
        out.append({"center": to_gltf(c), "size": [round(sz.x, 4), round(sz.z, 4), round(sz.y, 4)],
                    "triangles": sum(len(g.verts) - 2 for g in comp)})
    bm.free()
    return out


def join_registry(reg, name, material, groups):
    """Unwrap each part, record its pieces, join into one mesh object with a `car_group` face attribute."""
    records = []
    obs = []
    for nm, grp, ob in reg:
        ob.data.materials.clear()
        unwrap(ob, 0.5 if grp in LOW_DENSITY else 1.0)
        a = ob.data.attributes.new("car_group", "INT", "FACE")
        gi = groups.index(grp)
        for i in range(len(ob.data.polygons)):
            a.data[i].value = gi
        records.append({"name": nm, "group": grp, "pieces": components(ob)})
        obs.append(ob)
    select_only(obs)
    bpy.ops.object.join()
    out = bpy.context.view_layer.objects.active
    out.name = name
    out.data.name = name
    out.data.materials.clear()
    out.data.materials.append(material)
    for p in out.data.polygons:
        p.material_index = 0
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")
    out.data.uv_layers.active.name = "UVMap"
    # smooth shading with hard edges past 40 degrees (boxes, flanges, lens rims)
    out.data.set_sharp_from_angle(angle=math.radians(40))
    return out, records


def export_glb(path, objects, materials="PLACEHOLDER", image_format="AUTO"):
    select_only(objects)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
              export_texcoord=True, export_normals=True, export_tangents=False, export_materials=materials,
              export_extras=True, export_animations=False, export_attributes=False, export_cameras=False,
              export_lights=False)
    if materials == "EXPORT":
        kw["export_image_format"] = image_format
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        kw["export_texcoords"] = kw.pop("export_texcoord")
        bpy.ops.export_scene.gltf(**kw)


def make_collider(points):
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p)
    bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(5), verts=bm.verts[:], edges=bm.edges[:])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new("Collider")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Collider", me)
    bpy.context.scene.collection.objects.link(ob)
    ob["collider"] = "convex"
    ob["hidden"] = True
    ob.hide_render = True
    ob.display_type = "WIRE"
    return ob


def lamp_empty(name, loc, forward):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "SINGLE_ARROW"
    e.empty_display_size = 0.25
    e.location = loc
    # local +Y (= glTF local -Z, the direction a Godot SpotLight3D shines) points along the beam:
    # headlights forward (Blender -Y, glTF +Z), taillights back
    e.rotation_euler = (0, 0, math.pi if forward else 0.0)
    e["light"] = "headlight" if forward else "taillight"
    bpy.context.scene.collection.objects.link(e)
    return e


def decimated(me, name, target, symmetric=False):
    ob = bpy.data.objects.new(name, me.copy())
    bpy.context.scene.collection.objects.link(ob)
    m = ob.modifiers.new("dec", "DECIMATE")
    m.ratio = min(1.0, target / max(1, tris(ob)))
    m.use_collapse_triangulate = True
    if symmetric:
        m.use_symmetry = True
        m.symmetry_axis = "X"
    apply_mods(ob)
    return ob


def drop_groups(me, groups, names):
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.faces.layers.int.get("car_group")
    drop = {groups.index(g) for g in names if g in groups}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[lay] in drop], context="FACES")
    bm.to_mesh(me)
    bm.free()


def drop_small_pieces(me, min_size):
    """Delete connected pieces whose bounding box diagonal is under `min_size` (LOD2)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = set()
    kill = []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g)
            for v in g.verts:
                for h in v.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        vs = {v for g in comp for v in g.verts}
        lo = Vector((min(v.co.x for v in vs), min(v.co.y for v in vs), min(v.co.z for v in vs)))
        hi = Vector((max(v.co.x for v in vs), max(v.co.y for v in vs), max(v.co.z for v in vs)))
        if (hi - lo).length < min_size:
            kill += comp
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(me)
    bm.free()


def lod_collection(name, nodes):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    for o in nodes:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    coll.hide_render = True
    return coll


def wheel_lod(me_l, target, name):
    w = decimated(me_l, "tmpW", target)
    me = w.data
    me.name = f"WheelMesh_L_{name}"
    bpy.data.objects.remove(w, do_unlink=True)
    me_r = me.copy()
    me_r.name = f"WheelMesh_R_{name}"
    me_r.transform(Matrix.Rotation(math.pi, 4, "Z"))
    return me, me_r


def assemble(reg, wheel_parts, caliper, groups, src_dir):
    v = cfg.V
    pid = v.id_src
    mat_body = bpy.data.materials.new("CarBody")
    mat_wheel = bpy.data.materials.new("CarWheel")
    body, body_records = join_registry(reg, "Body", mat_body, groups)
    wheel, wheel_records = join_registry(wheel_parts + [caliper], "WheelSource", mat_wheel, groups)

    os.makedirs(src_dir, exist_ok=True)
    export_glb(os.path.join(src_dir, f"{pid}_body.glb"), [body])
    export_glb(os.path.join(src_dir, f"{pid}_wheel.glb"), [wheel])
    parts = {"format": "car-parts", "version": 1, "coords": "glTF (Y up, the car faces +Z)",
             "groups": groups, "body": body_records, "wheel": wheel_records,
             "triangles": {"body": tris(body), "wheel": tris(wheel)}}
    with open(os.path.join(src_dir, f"{pid}_parts.json"), "w") as f:
        json.dump(parts, f, indent=1)

    # split the caliper back out of the wheel source (it keeps its UVs: same texture set)
    cal_i = groups.index("caliper")
    bm = bmesh.new()
    bm.from_mesh(wheel.data)
    bm_cal = bm.copy()
    gl = bm.faces.layers.int.get("car_group")
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[gl] == cal_i], context="FACES")
    gl2 = bm_cal.faces.layers.int.get("car_group")
    bmesh.ops.delete(bm_cal, geom=[f for f in bm_cal.faces if f[gl2] != cal_i], context="FACES")
    me_wheel_l = bpy.data.meshes.new("WheelMesh_L")
    bm.to_mesh(me_wheel_l)
    me_cal_l = bpy.data.meshes.new("CaliperMesh_L")
    bm_cal.to_mesh(me_cal_l)
    bm.free()
    bm_cal.free()
    # right side: the same wheel turned 180 degrees about the up axis (sidewall text stays
    # readable), the caliper mirrored so it stays behind the axle
    me_wheel_r = me_wheel_l.copy()
    me_wheel_r.name = "WheelMesh_R"
    me_wheel_r.transform(Matrix.Rotation(math.pi, 4, "Z"))
    me_cal_r = me_cal_l.copy()
    me_cal_r.name = "CaliperMesh_R"
    me_cal_r.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    me_cal_r.flip_normals()
    dual = v.wheel.get("rear_dual")
    meshes = {("F", "L"): me_wheel_l, ("F", "R"): me_wheel_r, ("R", "L"): me_wheel_l, ("R", "R"): me_wheel_r}
    if dual:
        rl = WH.dual_copy(me_wheel_l, dual)
        rl.name = "WheelMeshRear_L"
        rr = rl.copy()
        rr.name = "WheelMeshRear_R"
        rr.transform(Matrix.Rotation(math.pi, 4, "Z"))
        meshes[("R", "L")], meshes[("R", "R")] = rl, rr
    for me in set(meshes.values()) | {me_cal_l, me_cal_r}:
        me.materials.clear()
        me.materials.append(mat_wheel)
    wheel_nodes, caliper_nodes = [], []
    for axle, an in zip(v.axles, "FR"):
        for sx, side in ((1, "L"), (-1, "R")):
            hub = (sx * v.track / 2, axle, v.wheel_r)
            w = bpy.data.objects.new(f"Wheel_{an}{side}", meshes[(an, side)])
            c = bpy.data.objects.new(f"Caliper_{an}{side}", me_cal_l if sx > 0 else me_cal_r)
            for o in (w, c):
                o.location = hub
                bpy.context.scene.collection.objects.link(o)
            wheel_nodes.append(w)
            caliper_nodes.append(c)
    bpy.data.objects.remove(wheel, do_unlink=True)

    # collider: convex hull of the body (no antenna / light-bar spikes)
    zmax = v.get("collider_zmax", 1.50)
    pts = [tuple(q.co) for q in body.data.vertices if q.co.z < zmax]
    col = make_collider(pts[::5])
    # lamp empties at the reflector / brake-lamp centres
    lp = v.lamps
    hx, hz = lp.head[:2]
    tx, tz = lp.tail[:2]
    yh = lp.head[2] if len(lp.head) > 2 else P.front_face_y(hx, hz)
    yt = lp.tail[2] if len(lp.tail) > 2 else P.rear_face_y(tx, tz)
    zh, zt = hz - v.body_drop, tz - v.body_drop
    lamps = [lamp_empty("Headlight_L", (hx, yh, zh), True), lamp_empty("Headlight_R", (-hx, yh, zh), True),
             lamp_empty("Taillight_L", (tx, yt, zt), False), lamp_empty("Taillight_R", (-tx, yt, zt), False)]

    # LOD1: no interior / under-car detail, decimated
    lod = v.get("lod", {})
    me = body.data.copy()
    drop_groups(me, groups, HIDDEN_AT_LOD1)
    lod_body = decimated(me, "Body_LOD1", lod.get("lod1_body", 8000))
    bpy.data.meshes.remove(me)
    lod_body.data.name = "Body_LOD1"
    me_wl1, me_wr1 = wheel_lod(me_wheel_l, lod.get("lod1_wheel", 480), "LOD1")
    lod1_meshes = {("F", "L"): me_wl1, ("F", "R"): me_wr1, ("R", "L"): me_wl1, ("R", "R"): me_wr1}
    if dual:
        a = WH.dual_copy(me_wl1, dual)
        b = a.copy()
        b.transform(Matrix.Rotation(math.pi, 4, "Z"))
        lod1_meshes[("R", "L")], lod1_meshes[("R", "R")] = a, b
    lod_nodes = [lod_body]
    for w in wheel_nodes:
        n = bpy.data.objects.new(w.name + "_LOD1", lod1_meshes[(w.name[-2], w.name[-1])])
        n.location = w.location
        lod_nodes.append(n)
    lod_collection("LOD1", lod_nodes)

    # LOD2 (distant traffic): shell + glass + lamps + big trims, ~1-2k triangles in total
    me = body.data.copy()
    drop_groups(me, groups, HIDDEN_AT_LOD2)
    drop_small_pieces(me, lod.get("lod2_min_piece", 0.12))
    lod2_body = decimated(me, "Body_LOD2", lod.get("lod2_body", 1300), symmetric=True)
    bpy.data.meshes.remove(me)
    lod2_body.data.name = "Body_LOD2"
    me_wl2, me_wr2 = wheel_lod(me_wheel_l, lod.get("lod2_wheel", 60), "LOD2")
    lod2_meshes = {("F", "L"): me_wl2, ("F", "R"): me_wr2, ("R", "L"): me_wl2, ("R", "R"): me_wr2}
    if dual:
        a = WH.dual_copy(me_wl2, dual)
        b = a.copy()
        b.transform(Matrix.Rotation(math.pi, 4, "Z"))
        lod2_meshes[("R", "L")], lod2_meshes[("R", "R")] = a, b
    lod2_nodes = [lod2_body]
    for w in wheel_nodes:
        n = bpy.data.objects.new(w.name + "_LOD2", lod2_meshes[(w.name[-2], w.name[-1])])
        n.location = w.location
        lod2_nodes.append(n)
    lod_collection("LOD2", lod2_nodes)

    lod0 = tris(body) + sum(tris(w) + tris(c) for w, c in zip(wheel_nodes, caliper_nodes))
    lod1 = sum(tris(o) for o in lod_nodes)
    lod2 = sum(tris(o) for o in lod2_nodes)
    xs = [q.co.x for q in body.data.vertices]
    zs = [q.co.z for q in body.data.vertices]
    ys = [q.co.y for q in body.data.vertices]
    dims = {"length": round(max(ys) - min(ys), 3), "width": round(max(xs) - min(xs), 3), "height": round(max(zs), 3)}
    dims.update(v.get("dimensions", {}))
    info = {
        "name": v.name,
        "id": v.id,
        "class": v["class"],
        "units": "metres",
        "coords": "glTF: +Y up, the car faces +Z, +X is the car's left side",
        "origin": "ground level under the centre of the body",
        "nodes": {"body": "Body", "wheels": [w.name for w in wheel_nodes], "calipers": [c.name for c in caliper_nodes],
                  "collider": "Collider", "lights": [l.name for l in lamps]},
        "wheel_radius": v.wheel_r, "wheel_width": v.wheel.width, "track": v.track,
        "wheelbase": round(B.axle_r() - B.axle_f(), 4),
        "wheel_positions": {w.name: to_gltf(w.location) for w in wheel_nodes},
        "lights": {l.name: {"position": to_gltf(l.location), "direction": [0, 0, 1] if l.name.startswith("Head") else [0, 0, -1],
                            "color": [1.0, 0.93, 0.8] if l.name.startswith("Head") else [1.0, 0.05, 0.03]} for l in lamps},
        "mass_kg": v.mass_kg,
        "center_of_mass": to_gltf(v.center_of_mass),
        "suspension_suggestion": v.suspension_suggestion,
        "dimensions": dims,
        "triangles": {"lod0": lod0, "lod0_body": tris(body), "lod0_wheel": tris(wheel_nodes[0]), "lod0_caliper": tris(caliper_nodes[0]),
                      "lod1": lod1, "lod2": lod2, "collider": tris(col)},
    }
    if dual:
        info["triangles"]["lod0_wheel_rear"] = tris(wheel_nodes[2])
        info["rear_dual_wheels"] = True
    for k, val in (v.get("info_extra") or {}).items():
        info[k] = val
    with open(os.path.join(src_dir, f"{pid}_info.json"), "w") as f:
        json.dump(info, f, indent=1)
    return info
