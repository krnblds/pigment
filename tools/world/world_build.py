"""Build the Blender scene from world.json (Blender 5.2, headless).

Everything is pieces, never one giant mesh:
    World_Terrain     one object per 256 m chunk (2 m grid), shared terrain material
    World_Water       the bay plane and a coarse sea floor
    World_Roads       one spline mesh per road (tools/town_roads.py build_run with the
                      class profile) + its decal mesh from the Pigment atlas
    World_Junctions   one mesh per junction / lookout (town_roads.build_junction) + decals
    World_Bridges     per bridge: girders, piers, pylons, cables, arches, railings
    World_SeaWalls    quay walls along urban coasts
    World_<district>  instances (kit meshes, towers, port kit, props) by district
    World_Lights      lamps, alley lights, masts, aviation lights
"""
import json
import math
import os
import random
import zlib

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import world_meshes as WM

ROAD_Z = 0.2


def coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    p = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in p.children]:
        p.children.link(c)
    return c


def put(c, name, data, loc=(0, 0, 0), rz=0.0, scale=None):
    o = bpy.data.objects.new(name, data)
    o.location = loc
    o.rotation_euler = (0, 0, rz)
    if scale is not None:
        o.scale = scale
    c.objects.link(o)
    return o


def path_from(town, pts, step=0.5):
    """blender_town.Path from world.json centreline points (z includes ROAD_Z)."""
    P = np.array(pts, dtype=float)
    seg = np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1]))
    s = np.concatenate([[0], np.cumsum(seg)])
    n = max(2, int(math.ceil(s[-1] / step)) + 1)
    ss = np.linspace(0, s[-1], n)
    x, y, z = (np.interp(ss, s, P[:, k]) for k in range(3))
    return town["Path"]([Vector((a, b)) for a, b in zip(x, y)], z - ROAD_Z)


def build(world, out, root, town, load_tool, region=None, log=print, trees=True, lights=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    drv = load_tool("town_layout_driver", {"__name__": "town_layout_driver"})
    drv["import_kit"]()
    drv["apply_kit_materials"]()
    R = load_tool("town_roads")
    RT = R["RoadTextures"](root)
    M = {
        "concrete": town["material"]("TownConcrete", town["concrete_nodes"]),
        "metal": R["metal_material"](),
        "asphalt": town["material"]("TownAsphaltFallback", town["flat_nodes"]((0.03, 0.03, 0.032), 0.6)),
        "curb": town["material"]("TownCurbFallback", town["flat_nodes"]((0.2, 0.2, 0.19), 0.85)),
        "walk": town["material"]("TownWalkFallback", town["flat_nodes"]((0.11, 0.11, 0.11), 0.8)),
        "wire": town["material"]("TownWire", town["flat_nodes"]((0.01, 0.01, 0.01), 0.5)),
    }
    road_mats = R["road_materials"](RT, {"asphalt": M["asphalt"], "curb": M["curb"], "walk": M["walk"], "concrete": M["concrete"]})
    road_mats5 = list(road_mats) + [M["metal"]]
    bridge_concrete = road_mats[3]
    KM = WM.kit_materials(root, town)
    kit = WM.Kit(root, world, KM)

    def inside(x, y, pad=0.0):
        if region is None:
            return True
        return region[0] - pad <= x <= region[2] + pad and region[1] - pad <= y <= region[3] + pad
    top = coll("World")
    C = {k: coll("World_" + k, top) for k in ("Terrain", "Water", "Roads", "Junctions", "Decals", "Bridges", "SeaWalls", "Props", "Nature", "Lights")}
    built = {"terrain": [], "roads": [], "junctions": [], "decals": [], "bridges": [], "piers": [], "walls": [], "instances": [],
             "lights": 0, "C": C, "region": region, "kit": kit, "road_mats": road_mats5, "R": R, "RT": RT}

    # ---- roads + decals
    nodes = {j["id"]: j for j in world["junctions"]}
    classes = world["road_classes"]
    roads_by_id = {}
    for r in world["roads"]:
        pts = r["points"]
        if not any(inside(p[0], p[1], 30) for p in pts[::4] + [pts[-1]]):
            continue
        path = path_from(town, pts)
        roads_by_id[r["id"]] = path
        prof = dict(classes[r["class"]])
        me = R["build_run"](path, "Road_" + r["id"], RT, road_mats5, prof)
        built["roads"].append(put(C["Roads"], "Road_" + r["id"], me))
        if RT.ok and RT.atlas_ok:
            db = R["DecalBuilder"](RT)
            ends = (nodes[r["start"]["node"]]["kind"] not in ("transition",), nodes[r["end"]["node"]]["kind"] not in ("transition",))
            R["scatter_run_decals"](db, path, 0, random.Random(zlib.crc32(r["id"].encode())), ends, profile=prof)
            built["decals"].append(put(C["Decals"], "Decals_" + r["id"], db.finish("Decals_" + r["id"], R["decal_atlas_material"](RT))))
    log(f"roads: {len(built['roads'])} runs")
    Js = {}
    for j in world["junctions"]:
        g = j.get("geom")
        if not g or not inside(j["pos"][0], j["pos"][1], 40):
            continue
        if "plaza" in g:
            import network as NW
            pz = g["plaza"]
            J = NW.Plaza(j["id"], j["pos"][:2], j["z"], pz["angle"], pz["R"], pz["half"])
        else:
            J = town["Junction"](j["id"], j["pos"][:2], j["z"], g["arms_deg"], r_concave=g["r_concave"], r_convex=g["r_convex"],
                                 halves=g["halves"], min_arm=g["min_arm"])
        Js[j["id"]] = J
        me = R["build_junction"](J, "Junction_" + j["id"], RT, road_mats, J.corner_line)
        built["junctions"].append(put(C["Junctions"], "Junction_" + j["id"], me, (J.pos.x, J.pos.y, J.z)))
        if RT.ok and RT.atlas_ok:
            db = R["DecalBuilder"](RT)
            R["junction_decals"](db, J, random.Random(zlib.crc32(j["id"].encode())), arms=[{"median": 0.0} for _ in J.dirs])
            built["decals"].append(put(C["Decals"], "JDecals_" + j["id"], db.finish("JDecals_" + j["id"], R["decal_atlas_material"](RT))))
        if "plaza" in g:
            lookout_dressing(C, J, M, built)
    log(f"junctions: {len(built['junctions'])}")

    # ---- terrain chunks
    T = world["terrain"]
    n = T["n"]
    H = np.fromfile(os.path.join(out, T["heightfield"]), dtype="<f4").reshape(n, n)
    upath = os.path.join(out, "masks_urban.npy")
    U = np.load(upath).astype(np.float32) if os.path.isfile(upath) else None
    # ---- final conform: no terrain vertex above a road / junction top surface
    bpy.context.view_layer.update()          # junction objects sit at their positions (matrix_world)
    snapped = snap_terrain(H, T, built["roads"] + built["junctions"])
    if snapped:
        H.astype("<f4").tofile(os.path.join(out, T["heightfield"]))      # keep world.json's field = what is built
    log(f"terrain snapped under road surfaces: {snapped} cells")
    tmat = WM.terrain_material(root)
    per = T["chunk_cells"]
    for ch in T["chunks"]:
        ox, oy = ch["origin"]
        if not inside(ox + T["chunk_m"] / 2, oy + T["chunk_m"] / 2, T["chunk_m"] / 2):
            continue
        me = WM.terrain_chunk("Terrain_" + ch["id"], H, T["origin"][0], T["cell_m"], ch["ix"] * per, ch["iy"] * per, per, 1, U)
        me.materials.append(tmat)
        built["terrain"].append(put(C["Terrain"], "Terrain_" + ch["id"], me))
    log(f"terrain: {len(built['terrain'])} chunks")
    # water + coarse sea floor
    wme = bpy.data.meshes.new("Water")
    S = 60000.0           # to the horizon
    wme.from_pydata([(-S, -S, 0), (S, -S, 0), (S, S, 0), (-S, S, 0)], [], [(0, 1, 2, 3)])
    wme.materials.append(WM.water_material())
    put(C["Water"], "Water", wme, (0, 0, world["sea_level"]))
    fme = WM.terrain_chunk("SeaFloor", H, T["origin"][0], T["cell_m"], 0, 0, n - 1, 32)
    fme.materials.append(tmat)
    put(C["Water"], "SeaFloor", fme, (0, 0, -0.5))

    # ---- bridges and viaducts
    for br in world["bridges"]:
        rid = f"r{br['edge']}"
        if rid not in roads_by_id:
            continue
        build_bridge(C["Bridges"], br, roads_by_id[rid], classes[next(r["class"] for r in world["roads"] if r["id"] == rid)], R, RT,
                     bridge_concrete, M, KM, built)
    log(f"bridges: {len(built['bridges'])} structures")

    # ---- sea walls
    for k, w in enumerate(world["sea_walls"]):
        if not any(inside(p[0], p[1], 20) for p in w["points"]):
            continue
        built["walls"].append(put(C["SeaWalls"], f"SeaWall{k}", sea_wall(w, H, T, bridge_concrete)))

    # ---- ground snap: street furniture, props, trees and container stacks stand on the
    # built surfaces (road / sidewalk / barrier tops, else terrain); world.json is updated
    bpy.context.view_layer.update()
    snap_instances(world, built, H, T, region, log)
    if region is None:
        import json as _json
        with open(os.path.join(out, "world.json"), "w", encoding="utf-8") as f:
            _json.dump(world, f, separators=(",", ":"))

    # ---- instances
    K = {o.name[4:]: o for o in bpy.data.collections["TownKit"].objects}
    var_mats = {}
    for a in ("building_a", "building_b", "building_c", "overhead_sign"):
        if a in K:
            for m in town["variant_materials"](root, a, K[a]):
                var_mats[m.name] = m
    props_dir = os.path.join(root, "assets", "props")
    plinth = bpy.data.meshes.get("PlinthBox")
    if plinth is None:
        plinth = bpy.data.meshes.new("PlinthBox")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(plinth)
        bm.free()
        plinth.materials.append(M["concrete"])
    dcoll = {}
    colours = {"rust": (0.42, 0.12, 0.06), "blue": (0.05, 0.16, 0.4), "white": (0.75, 0.75, 0.72), "green": (0.08, 0.3, 0.14),
               "orange": (0.8, 0.3, 0.05), "grey": (0.35, 0.36, 0.37), "teal": (0.05, 0.35, 0.38), "red": (0.55, 0.06, 0.04)}
    exts = {"building_a": (-4.39, 4.39, -6.62, 5.17), "building_b": (-8.39, 8.39, -6.39, 6.17), "building_c": (-7.39, 7.39, -9.25, 7.12)}
    n_inst = 0
    var_mesh = {}
    TB = None
    if os.path.isfile(os.path.join(root, "assets", "trees", "index.json")):
        import sys as _sys
        _sys.path.insert(0, os.path.join(root, "tools", "trees"))
        import tree_blender as TB
    for i in world["instances"]:
        x, y, z = i["pos"]
        if not inside(x, y, 10):
            continue
        a = i["asset"]
        if a.startswith("tree") and not trees:
            continue
        if a.startswith("tree_") and TB is not None and a in TB.load_index(root)["variants"]:
            data = TB.kit_mesh(root, a)          # tree kit (tools/trees): LOD0, named by its key
        elif a in K:
            data = K[a].data
        elif os.path.isfile(os.path.join(props_dir, a + ".glb")):
            data = import_prop(props_dir, a)
        else:
            data = kit.get(a)
        if data is None:
            continue
        d = i.get("district", "misc")
        if d not in dcoll:
            dcoll[d] = C["Nature"] if d == "nature" else C["Props"] if d == "roads" else coll("World_" + d, top)
        v = i.get("variant")
        # Variants are mesh copies with their material (not object-level
        # overrides): Cycles keys geometry by material, so overrides would
        # turn 4000 instanced buildings into 4000 BVHs.
        vm = None
        if v:
            mname = f"Pigment_{a}__{v}"
            if mname in var_mats:
                vm = var_mats[mname]
            elif a.startswith(("tower_", "landmark_")) and ("facade_" + v) in KM:
                vm = KM["facade_" + v]
            elif data.name.startswith("PROP_"):
                vm = prop_variant_material(props_dir, a, v, data, var_mats)
        if vm is not None:
            key = (data.name, vm.name)
            if key not in var_mesh:
                me2 = data.copy()
                me2.name = f"{data.name}__{v}"
                me2.materials[0] = vm
                var_mesh[key] = me2
            data = var_mesh[key]
        o = put(dcoll[d], a, data, (x, y, z), i["rot"], i.get("scale"))
        if v and vm is None and v in colours:
            o.color = (*colours[v], 1.0)
        if a.startswith(("tree", "container", "warehouse", "crane")) and not v and not (TB is not None and a in TB.load_index(root)["variants"]):
            o.color = (0.4, 0.4, 0.4, 1)
        dep = i.get("footing")
        if dep:
            if a in exts:
                xmin, xmax, ymin, ymax = exts[a]
                f = put(dcoll[d], "Footing", plinth, ((xmin + xmax) / 2, (ymin + ymax) / 2 + 0.6, -dep / 2 + 0.02))
                f.scale = (xmax - xmin - 0.1, ymax - ymin - 1.4, dep)
            else:
                tw = kit.towers.get(a)
                fw, fd = (tw["footprint"] if tw else [float(v_) for v_ in a.split("_")[1].split("x")[:2]])
                f = put(dcoll[d], "Footing", plinth, (0, 0, -dep / 2 + 0.02))
                f.scale = (fw - 0.2, fd - 0.2, dep)
            f.parent = o
        n_inst += 1
    built["instances"] = n_inst
    log(f"instances: {n_inst}")

    # ---- wires
    cu = bpy.data.curves.new("PowerLines", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.012
    nw = 0
    for w in world["wires"]:
        a, b = Vector(w["a"]), Vector(w["b"])
        if not inside(a.x, a.y):
            continue
        sp = cu.splines.new("POLY")
        sp.points.add(10)
        for k in range(11):
            u = k / 10
            q = a.lerp(b, u)
            sp.points[k].co = (q.x, q.y, q.z - w["sag"] * 4 * u * (1 - u), 1)
        nw += 1
    cu.materials.append(M["wire"])
    put(C["Props"], "PowerLines", cu)

    # ---- lights
    if lights:
        for L in world["lights"]:
            x, y, z = L["pos"]
            if not inside(x, y, 5):
                continue
            li = bpy.data.lights.new(L["kind"], "POINT")
            li.color = L["color"]
            li.energy = L["energy"]
            li.shadow_soft_size = 0.3 if L["kind"] != "mast" else 1.0
            put(C["Lights"], "Light_" + L["kind"], li, (x, y, z))
            built["lights"] += 1
    log(f"lights: {built['lights']}, wires: {nw}")
    night_world()
    built["junction_objs"] = Js
    built["paths"] = roads_by_id
    built["H"] = H
    return built


def import_prop(props_dir, name):
    me = bpy.data.meshes.get("PROP_" + name)
    if me is not None:
        return me
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(props_dir, name + ".glb"))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and not o.name.startswith("Collider")]
    if not meshes:
        return None
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
    me = obj.data
    me.name = "PROP_" + name
    names = set()
    for o in new:
        try:
            names.add(o.name)
        except ReferenceError:
            pass
    for nm in names:
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o)
    return me


def prop_variant_material(props_dir, name, variant, me, cache):
    """A props-kit variant (assets/props/index.json `variants`: albedo / emission swaps) as a copy
    of the prop's material, e.g. the port containers' yard colours and the cranes' paints. None
    when the prop has no such variant (the default look is used)."""
    mname = f"PROP_{name}__{variant}"
    if mname in cache:
        return cache[mname]
    idx = cache.get("_props_index")
    if idx is None:
        ip = os.path.join(props_dir, "index.json")
        idx = cache["_props_index"] = json.load(open(ip, encoding="utf8")).get("props", {}) if os.path.isfile(ip) else {}
    var = next((x for x in idx.get(name, {}).get("variants", []) if x.get("name") == variant and x.get("albedo")), None)
    if var is None or not me.materials or me.materials[0] is None or not me.materials[0].use_nodes:
        cache[mname] = None
        return None
    m = me.materials[0].copy()
    m.name = mname
    for n in m.node_tree.nodes:
        if n.type != "TEX_IMAGE" or n.image is None:
            continue
        sock = {l.to_socket.name for l in n.outputs["Color"].links}
        key = "albedo" if "Base Color" in sock else "emission" if any("Emission" in x for x in sock) else None
        if key and var.get(key):
            n.image = bpy.data.images.load(os.path.join(props_dir, var[key]), check_existing=True)
            if key == "emission":
                n.image.colorspace_settings.name = "sRGB"
    cache[mname] = m
    return m


def sea_wall(w, H, T, mat):
    """Quay wall along a contour: sea face from the bottom to a parapet 1 m
    over the quay, cap, land face."""
    P = [Vector(p) for p in w["points"]]
    bm = bmesh.new()
    rows = []
    for k, p in enumerate(P):
        a, b = P[max(0, k - 1)], P[min(len(P) - 1, k + 1)]
        t = (b - a).normalized()
        nn = Vector((-t.y, t.x))
        # which side is the sea: lower terrain
        def h(q):
            ix = int(round((q.x - T["origin"][0]) / T["cell_m"]))
            iy = int(round((q.y - T["origin"][1]) / T["cell_m"]))
            ix = min(max(ix, 0), H.shape[1] - 1)
            iy = min(max(iy, 0), H.shape[0] - 1)
            return H[iy, ix]
        sea = nn if h(p + nn * 6) < h(p - nn * 6) else -nn
        top = w["top"][k]
        o = p + sea * 0.3
        i = p - sea * 1.0
        rows.append([bm.verts.new((o.x, o.y, w["bottom"])), bm.verts.new((o.x, o.y, top)), bm.verts.new((i.x, i.y, top)), bm.verts.new((i.x, i.y, top - 2.5))])
    for r0, r1 in zip(rows, rows[1:]):
        for q in range(3):
            bm.faces.new((r0[q], r1[q], r1[q + 1], r0[q + 1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new("SeaWall")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    return me


def lookout_dressing(C, J, M, built):
    """Summit lookout: a railing on the plaza rim and a few lamps."""
    cu = bpy.data.curves.new("LookoutRail", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.035
    r = J.R + 2.9
    a0 = math.atan2(J.dirs[0].y, J.dirs[0].x)
    phi = math.asin(min(0.95, (J.half[0] + 3.0) / r)) + 0.05
    for h in (0.55, 1.05):
        sp = cu.splines.new("POLY")
        m = 60
        sp.points.add(m)
        for k in range(m + 1):
            th = a0 + phi + (2 * math.pi - 2 * phi) * k / m
            sp.points[k].co = (J.pos.x + r * math.cos(th), J.pos.y + r * math.sin(th), J.z + 0.35 + h, 1)
    cu.materials.append(M["metal"])
    put(C["Junctions"], "LookoutRail", cu)


def build_bridge(c, br, path, cls, R, RT, concrete, M, KM, built):
    """Girder under the deck, piers, pylons + stays, arch ribs + hangers,
    railings on the barriers, LED strips under the deck edges."""
    s0, s1 = br["s"]
    s0 = max(0.0, s0 - 6.0)
    s1 = min(path.length, s1 + 6.0)
    side = cls.get("side", "curb")
    w = cls["half"] + (3.0 if side == "curb" else 0.5)
    d = br.get("depth", 2.4)
    ss = np.linspace(s0, s1, max(2, int((s1 - s0) / 2.0) + 1))
    pos, t = path.at_many(ss)
    P3 = [(p[0], p[1], p[2]) for p in pos]
    nrm = [(-tt[1], tt[0]) for tt in t]
    b = R["SectionBuilder"](RT)
    prof = [(-w, -0.15), (-w, -d * 0.55), (-w * 0.55, -d), (w * 0.55, -d), (w, -d * 0.55), (w, -0.15)]
    b.extrude(P3, nrm, prof, 0, sgn=-1.0)
    # LED strips under the deck edges
    for sgn in (-1, 1):
        y = sgn * (w + 0.02)
        strip = [(y, -0.35), (y, -0.5)] if sgn > 0 else [(y, -0.5), (y, -0.35)]
        b.extrude(P3, nrm, strip, 1, sgn=1.0)
    me = b.finish(f"Girder_{br['name']}", [concrete, KM["cable"]])
    built["bridges"].append(put(c, f"Girder_{br['name']}", me))
    m = WM.Mesher()
    # railings on top of the barriers (or along the sidewalk edge)
    rail_y = (cls["half"] + 0.38) if side != "curb" else (cls["half"] + 2.9)
    rail_z = (ROAD_Z + 0.9 + 0.35) if side != "curb" else 0.35 + 1.05
    for sgn in (-1, 1):
        prev = None
        for k in range(len(ss)):
            q = Vector((pos[k][0] + nrm[k][0] * sgn * rail_y, pos[k][1] + nrm[k][1] * sgn * rail_y, pos[k][2] + rail_z))
            if prev is not None:
                m.cyl(prev, q, 0.05, 0, seg=6)
            if k % 2 == 0:
                m.cyl((q.x, q.y, q.z - (0.35 if side != "curb" else 1.05)), q, 0.04, 0, seg=6)
            prev = q
    for p in br["piers"]:
        x, y = p["pos"]
        dvec = Vector(p["dir"])
        lat = Vector((-dvec.y, dvec.x))
        heavy = p.get("heavy")
        if w > 9 or heavy:
            for sgn in (-1, 1):
                q = Vector((x, y)) + lat * sgn * w * 0.5
                m.cyl((q.x, q.y, p["bottom"]), (q.x, q.y, p["top"]), 1.9 if heavy else 1.3, 1, seg=12)
        else:
            m.cyl((x, y, p["bottom"]), (x, y, p["top"]), 1.5, 1, seg=12)
        cap = 1.6
        rz = math.atan2(dvec.y, dvec.x)
        m.box((x, y, p["top"] - cap / 2), (2.6, 2 * w * 0.95, cap), 1, rz=rz)
        built["piers"].append(p)
    for py in br["pylons"]:
        x, y = py["pos"]
        dvec = Vector(py["dir"])
        lat = Vector((-dvec.y, dvec.x))
        rz = math.atan2(dvec.y, dvec.x)
        legs = []
        for sgn in (-1, 1):
            foot = Vector((x, y)) + lat * sgn * (w + 3.5)
            head = Vector((x, y)) + lat * sgn * (w + 1.2)
            m.cyl((foot.x, foot.y, py["bottom"]), (head.x, head.y, py["top"]), 2.6, 1, seg=8, r2=1.6)
            legs.append((foot, head))
        for zf in (py["deck"] - d - 2.0, py["top"] - 12.0):
            m.box((x, y, zf), (3.0, 2 * (w + 2.6), 3.0), 1, rz=rz)
        m.box((x, y, py["top"] + 0.6), (2.0, 2.0, 1.2), 3)            # aviation light
        built["piers"].append({"pos": py["pos"], "bottom": py["bottom"], "top": py["top"], "pylon": True})
    for a, bpt in br["cables"]:
        m.cyl(a, bpt, 0.11, 2, seg=6)
    for rib in br["arches"]:
        for p0, p1 in zip(rib, rib[1:]):
            m.cyl(p0, p1, 0.9, 1, seg=8)
    for a, bpt in br["hangers"]:
        m.cyl(a, bpt, 0.08, 2, seg=6)
    if m.bm.faces:
        built["bridges"].append(put(c, f"Bridge_{br['name']}", m.finish(f"Bridge_{br['name']}", [M["metal"], concrete, KM["cable"], KM["red_light"]])))
    else:
        m.bm.free()


def night_world():
    sc = bpy.context.scene
    w = bpy.data.worlds.get("WorldNight") or bpy.data.worlds.new("WorldNight")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.012, 0.016, 0.035, 1)
    bg.inputs["Strength"].default_value = 1.0
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    sc.world = w
    moon = bpy.data.lights.get("Moon") or bpy.data.lights.new("Moon", "SUN")
    moon.energy = 0.06
    moon.color = (0.6, 0.7, 1.0)
    if "Moon" not in bpy.data.objects:
        o = bpy.data.objects.new("Moon", moon)
        sc.collection.objects.link(o)
        o.rotation_euler = (math.radians(55), 0, math.radians(35))


def snap_terrain(H, T, objs, clear=0.04):
    """Lower heightfield cells around every vertex and face centre of the road
    and junction top surfaces so the terrain stays at least `clear` below
    them (exact final pass after the data stage's cut / fill)."""
    pts = []
    for o in objs:
        me = o.data
        mw = np.array(o.matrix_world)
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        nz = np.empty(len(me.polygons) * 3)
        me.polygons.foreach_get("normal", nz)
        nz = nz.reshape(-1, 3)[:, 2]
        ce = np.empty(len(me.polygons) * 3)
        me.polygons.foreach_get("center", ce)
        ce = ce.reshape(-1, 3)
        top = nz > 0.5
        vi = np.empty(len(me.loops), dtype=np.int64)
        me.loops.foreach_get("vertex_index", vi)
        ls = np.empty(len(me.polygons), dtype=np.int64)
        me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(len(me.polygons), dtype=np.int64)
        me.polygons.foreach_get("loop_total", lt)
        sel = np.concatenate([vi[a:a + b] for a, b in zip(ls[top], lt[top])]) if top.any() else np.array([], dtype=np.int64)
        P = np.concatenate([co[np.unique(sel)], ce[top]]) if len(sel) else ce[top]
        P = P @ mw[:3, :3].T + mw[:3, 3]
        pts.append(P)
    if not pts:
        return 0
    P = np.concatenate(pts)
    c = T["cell_m"]
    x0 = T["origin"][0]
    fx = (P[:, 0] - x0) / c
    fy = (P[:, 1] - x0) / c
    ix = np.clip(np.floor(fx).astype(np.int64), 0, H.shape[1] - 2)
    iy = np.clip(np.floor(fy).astype(np.int64), 0, H.shape[0] - 2)
    before = H.copy()
    flat = H.reshape(-1)
    z = P[:, 2] - clear
    for dy in (-1, 0, 1, 2):
        for dx in (-1, 0, 1, 2):
            jj = np.clip(iy + dy, 0, H.shape[0] - 1)
            ii = np.clip(ix + dx, 0, H.shape[1] - 1)
            np.minimum.at(flat, jj * H.shape[1] + ii, z)
    return int((H != before).sum())


def snap_instances(world, built, H, T, region, log):
    from mathutils.bvhtree import BVHTree
    bv, bp = [], []
    for o in built["roads"] + built["junctions"] + built["walls"]:
        me = o.data
        mw = o.matrix_world
        base = len(bv)
        bv += [mw @ v.co for v in me.vertices]
        bp += [tuple(i + base for i in p.vertices) for p in me.polygons]
    bvh = BVHTree.FromPolygons(bv, bp) if bp else None
    import terrain as TR
    hf = TR.Heightfield(world["size_m"], T["cell_m"])
    hf.H = H

    def ground(x, y, z):
        g = float(hf.sample_tri(np.array([x]), np.array([y]))[0])
        if bvh is not None:
            h = bvh.ray_cast(Vector((x, y, z + 1.2)), Vector((0, 0, -1)), 80)
            if h[0] is not None and h[0].z > g:
                g = h[0].z
        return g
    kinds = ("prop", "lamp", "pole", "signal", "mast", "tree", "shrub")
    moved = dropped = 0
    stacks = {}
    keep = []
    for i in world["instances"]:
        x, y, z = i["pos"]
        if region and not (region[0] - 10 <= x <= region[2] + 10 and region[1] - 10 <= y <= region[3] + 10):
            keep.append(i)
            continue
        k = i.get("kind")
        if k == "container":
            stacks.setdefault((round(x, 1), round(y, 1)), []).append(i)
            keep.append(i)
            continue
        if k not in kinds or i.get("slot") == "rooftop":
            keep.append(i)
            continue
        g = ground(x, y, z)
        dz = g - z
        if k == "shrub" and i.get("slot") == "planter":     # tree kit shrubs ride on their planter's soil
            off = 0.93 * (i.get("scale") or [1, 1, 1])[2]
            dz = ground(x, y, z - off) - (z - off)
        if k == "tree":
            dz = min(dz, 0.0) if dz < -0.05 else 0.0         # never hang in the air
            dz = g - 0.2 - z if g - 0.2 < z else 0.0
        if abs(dz) > 4.0:
            dropped += 1
            continue
        if abs(dz) > 0.02:
            i["pos"][2] = round(z + dz, 3)
            moved += 1
        keep.append(i)
    for st in stacks.values():
        st.sort(key=lambda i: i["pos"][2])
        x, y, z = st[0]["pos"]
        dz = ground(x, y, z) - z
        if abs(dz) > 0.02:
            for i in st:
                i["pos"][2] = round(i["pos"][2] + dz, 3)
            moved += len(st)
    world["instances"] = keep
    log(f"ground snap: {moved} instances moved, {dropped} dropped (more than 4 m off the ground)")
