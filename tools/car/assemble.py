"""Turn the built parts into the shipped node layout.

UVs (one texture set per material), the `parts.json` sidecar for Pigment, the
source meshes Pigment paints, wheel / caliper nodes, the collider, the lamp
empties, LOD1 and car_info.json.
"""
import json
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

import body as B
import panels as P
import wheels as W
from carlib import apply_mods

# groups that are hard to see get half the texel density
LOW_DENSITY = ("underbody", "underbody_metal", "suspension", "spring", "interior_carpet", "interior_dark",
               "interior_plastic", "black_metal")
HIDDEN_AT_LOD1 = ("underbody_metal", "suspension", "spring", "interior_fabric", "interior_plastic", "interior_dark",
                  "interior_leather", "interior_carpet", "screen", "black_metal", "underbody")


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


def decimated(me, name, target):
    ob = bpy.data.objects.new(name, me.copy())
    bpy.context.scene.collection.objects.link(ob)
    m = ob.modifiers.new("dec", "DECIMATE")
    m.ratio = min(1.0, target / max(1, tris(ob)))
    m.use_collapse_triangulate = True
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


def assemble(reg, wheel_parts, caliper, groups, src_dir):
    mat_body = bpy.data.materials.new("CarBody")
    mat_wheel = bpy.data.materials.new("CarWheel")
    body, body_records = join_registry(reg, "Body", mat_body, groups)
    wheel, wheel_records = join_registry(wheel_parts + [caliper], "WheelSource", mat_wheel, groups)

    os.makedirs(src_dir, exist_ok=True)
    export_glb(os.path.join(src_dir, "car_body.glb"), [body])
    export_glb(os.path.join(src_dir, "car_wheel.glb"), [wheel])
    parts = {"format": "car-parts", "version": 1, "coords": "glTF (Y up, the car faces +Z)",
             "groups": groups, "body": body_records, "wheel": wheel_records,
             "triangles": {"body": tris(body), "wheel": tris(wheel)}}
    with open(os.path.join(src_dir, "car_parts.json"), "w") as f:
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
    for me in (me_wheel_l, me_wheel_r, me_cal_l, me_cal_r):
        me.materials.clear()
        me.materials.append(mat_wheel)
    wheel_nodes, caliper_nodes = [], []
    for axle, an in ((B.AXLE_F, "F"), (B.AXLE_R, "R")):
        for sx, side in ((1, "L"), (-1, "R")):
            hub = (sx * B.TRACK / 2, axle, B.WHEEL_R)
            w = bpy.data.objects.new(f"Wheel_{an}{side}", me_wheel_l if sx > 0 else me_wheel_r)
            c = bpy.data.objects.new(f"Caliper_{an}{side}", me_cal_l if sx > 0 else me_cal_r)
            for o in (w, c):
                o.location = hub
                bpy.context.scene.collection.objects.link(o)
            wheel_nodes.append(w)
            caliper_nodes.append(c)
    bpy.data.objects.remove(wheel, do_unlink=True)

    # collider: convex hull of the body (no antenna / mirrors-only spikes above the light bar)
    pts = [tuple(v.co) for v in body.data.vertices if v.co.z < 1.50]
    col = make_collider(pts[::5])
    # lamp empties at the reflector / brake-lamp centres
    yh = P.front_face_y(0.6, 0.632)
    yt = P.rear_face_y(0.735, 0.825)
    zh, zt = 0.632 - B.BODY_DROP, 0.825 - B.BODY_DROP
    lamps = [lamp_empty("Headlight_L", (0.60, yh, zh), True), lamp_empty("Headlight_R", (-0.60, yh, zh), True),
             lamp_empty("Taillight_L", (0.735, yt, zt), False), lamp_empty("Taillight_R", (-0.735, yt, zt), False)]

    # LOD1: no interior / under-car detail, decimated to ~10k triangles in total
    me = body.data.copy()
    drop_groups(me, groups, HIDDEN_AT_LOD1)
    lod_body = decimated(me, "Body_LOD1", 8000)
    bpy.data.meshes.remove(me)
    lod_body.data.name = "Body_LOD1"
    wl = decimated(me_wheel_l, "tmpW", 480)
    me_wl_lod = wl.data
    me_wl_lod.name = "WheelMesh_L_LOD1"
    bpy.data.objects.remove(wl, do_unlink=True)
    me_wr_lod = me_wl_lod.copy()
    me_wr_lod.name = "WheelMesh_R_LOD1"
    me_wr_lod.transform(Matrix.Rotation(math.pi, 4, "Z"))
    lod_coll = bpy.data.collections.new("LOD1")
    bpy.context.scene.collection.children.link(lod_coll)
    lod_nodes = [lod_body]
    for w in wheel_nodes:
        n = bpy.data.objects.new(w.name + "_LOD1", me_wl_lod if w.name.endswith("L") else me_wr_lod)
        n.location = w.location
        lod_nodes.append(n)
    for o in lod_nodes:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        lod_coll.objects.link(o)
    lod_coll.hide_render = True

    lod0 = tris(body) + 4 * (tris(wheel_nodes[0]) + tris(caliper_nodes[0]))
    lod1 = sum(tris(o) for o in lod_nodes)
    info = {
        "name": "Kanzaki Tsubame-4, Hoshikawa Security cruiser",
        "units": "metres",
        "coords": "glTF: +Y up, the car faces +Z, +X is the car's left side",
        "origin": "ground level under the centre of the body",
        "nodes": {"body": "Body", "wheels": [w.name for w in wheel_nodes], "calipers": [c.name for c in caliper_nodes],
                  "collider": "Collider", "lights": [l.name for l in lamps]},
        "wheel_radius": B.WHEEL_R, "wheel_width": W.W_TYRE, "track": B.TRACK,
        "wheelbase": round(B.AXLE_R - B.AXLE_F, 4),
        "wheel_positions": {w.name: to_gltf(w.location) for w in wheel_nodes},
        "lights": {l.name: {"position": to_gltf(l.location), "direction": [0, 0, 1] if l.name.startswith("Head") else [0, 0, -1],
                            "color": [1.0, 0.93, 0.8] if l.name.startswith("Head") else [1.0, 0.05, 0.03]} for l in lamps},
        "mass_kg": 1280,
        "center_of_mass": to_gltf((0.0, -0.05, 0.48)),
        "suspension_suggestion": {"rest_length": 0.14, "travel": 0.12, "stiffness": 38.0, "max_force": 9000.0,
                                  "damping_compression": 0.9, "damping_relaxation": 1.4, "friction_slip": 2.8},
        "dimensions": {"length": round(B.REAR - B.FRONT, 3), "width_body": 1.784, "width_overfenders": 1.87,
                       "height_roof": round(1.39 - B.BODY_DROP, 3), "height_lightbar": round(max(v.co.z for v in body.data.vertices if v.co.z < 1.6), 3)},
        "triangles": {"lod0": lod0, "lod0_body": tris(body), "lod0_wheel": tris(wheel_nodes[0]), "lod0_caliper": tris(caliper_nodes[0]),
                      "lod1": lod1, "collider": tris(col)},
    }
    with open(os.path.join(src_dir, "car_info.json"), "w") as f:
        json.dump(info, f, indent=1)
    return info
