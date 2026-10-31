"""Lay out a hillside cyberpunk town in the live Blender scene.

Needs the town kit already imported into the "TownKit" collection as
KIT_<asset> objects with their Pigment materials (see tools/blender_pigment.py).
Winding roads are 3D paths; the Pigment-textured street piece is arrayed and
bent along each path. Paved terrain follows the roads, flattens into terraces
beside them and rolls into hills further out. Buildings line both sides of
every road, sit on concrete footings and face the street.

    exec(open("tools/blender_town.py").read())  # inside Blender
"""
import math
import random

import bmesh
import bpy
from mathutils import Vector, kdtree

SEED = 11
STREET_HALF = 7.0          # street piece is 14 m wide (road + sidewalks)
SIDEWALK_Z = 0.35          # sidewalk top above the path
COLL = "CyberpunkTown"

# ---------------------------------------------------------------- heights

def hill(x, y):
    return 6.5 * math.sin(x / 52 + 0.4) * math.cos(y / 68) + 0.045 * y + 2.0 * math.sin((x + y) / 31)


JUNCTIONS = []


def road_height(x, y):
    h = hill(x, y)
    for jx, jy, jz in JUNCTIONS:
        d = math.hypot(x - jx, y - jy)
        if d < 32:
            t = max(0.0, (d - 12) / 20)
            t = t * t * (3 - 2 * t)
            h = jz + (h - jz) * t
    return h


def wild(x, y):
    return 4.0 * math.sin(x / 23 + 1.3) * math.sin(y / 19 + 0.2) + 2.5 * math.cos(x / 41 - y / 37)

# ---------------------------------------------------------------- paths

def catmull(points, step=1.0):
    pts = [Vector((p[0], p[1])) for p in points]
    pts = [pts[0] * 2 - pts[1]] + pts + [pts[-1] * 2 - pts[-2]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        n = max(2, int((p2 - p1).length / step))
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(pts[-2])
    # resample to even spacing
    even, acc = [out[0]], 0.0
    for a, b in zip(out, out[1:]):
        seg = (b - a).length
        while acc + seg >= step:
            r = (step - acc) / seg
            a = a + (b - a) * r
            seg = (b - a).length
            even.append(a)
            acc = 0.0
        acc += seg
    return even


class Path:
    def __init__(self, pts2d):
        self.p = [Vector((v.x, v.y, road_height(v.x, v.y))) for v in pts2d]
        self.length = (len(self.p) - 1) * 1.0

    def at(self, s):
        i = max(0, min(len(self.p) - 2, int(s)))
        f = s - i
        a, b = self.p[i], self.p[i + 1]
        pos = a.lerp(b, f)
        t = (b - a).to_2d().normalized()
        return pos, t

# ---------------------------------------------------------------- helpers

def clear(coll):
    for o in list(coll.objects):
        data = o.data
        bpy.data.objects.remove(o)
        if data is not None and data.users == 0 and isinstance(data, (bpy.types.Curve, bpy.types.Light, bpy.types.Camera)):
            if isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)


def material(name, build):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    build(nt)
    return m


def paving_nodes(nt):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Mortar Size"].default_value = 0.012
    brick.inputs["Brick Width"].default_value = 0.6
    brick.inputs["Row Height"].default_value = 0.3
    brick.inputs["Color1"].default_value = (0.09, 0.09, 0.095, 1)
    brick.inputs["Color2"].default_value = (0.055, 0.055, 0.06, 1)
    brick.inputs["Mortar"].default_value = (0.02, 0.02, 0.02, 1)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.08
    noise.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.48
    ramp.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1)
    ramp.color_ramp.elements[1].position = 0.56
    ramp.color_ramp.elements[1].color = (0.7, 0.7, 0.7, 1)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    L = nt.links.new
    L(tc.outputs["Object"], brick.inputs["Vector"])
    L(tc.outputs["Object"], noise.inputs["Vector"])
    L(noise.outputs["Fac"], ramp.inputs["Fac"])
    L(brick.outputs["Color"], bsdf.inputs["Base Color"])
    L(ramp.outputs["Color"], bsdf.inputs["Roughness"])
    L(brick.outputs["Fac"], bump.inputs["Height"])
    L(bump.outputs["Normal"], bsdf.inputs["Normal"])
    L(bsdf.outputs[0], out.inputs[0])


def concrete_nodes(nt):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 8
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1)
    ramp.color_ramp.elements[1].color = (0.16, 0.155, 0.15, 1)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.2
    bsdf.inputs["Roughness"].default_value = 0.85
    L = nt.links.new
    L(noise.outputs["Fac"], ramp.inputs["Fac"])
    L(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    L(noise.outputs["Fac"], bump.inputs["Height"])
    L(bump.outputs["Normal"], bsdf.inputs["Normal"])
    L(bsdf.outputs[0], out.inputs[0])


def dense_street(kit):
    name = "street_dense"
    if name in bpy.data.meshes:
        return bpy.data.meshes[name]
    me = kit.data.copy()
    me.name = name
    bm = bmesh.new()
    bm.from_mesh(me)
    for x in range(-9, 10):
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(x, 0, 0), plane_no=(1, 0, 0))
    bm.to_mesh(me)
    bm.free()
    return me


def rect_corners(c, rz, xmin, xmax, ymin, ymax):
    cs, sn = math.cos(rz), math.sin(rz)
    out = []
    for lx, ly in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)):
        out.append(Vector((c.x + lx * cs - ly * sn, c.y + lx * sn + ly * cs)))
    return out


def overlap(a, b):
    for poly in (a, b):
        for i in range(4):
            e = poly[(i + 1) % 4] - poly[i]
            ax = Vector((-e.y, e.x))
            pa = [ax.dot(p) for p in a]
            pb = [ax.dot(p) for p in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True

# ---------------------------------------------------------------- build

def build():
    rng = random.Random(SEED)
    sc = bpy.context.scene
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
        sc.collection.children.link(coll)
    clear(coll)
    K = {n: bpy.data.objects["KIT_" + n] for n in
         ["building_a", "building_b", "building_c", "street_segment", "crossroad", "street_lamp", "power_pole", "overhead_sign"]}

    def put(data, loc, rz=0.0, name="obj", parent=None):
        o = bpy.data.objects.new(name, data)
        o.location = loc
        o.rotation_euler = (0, 0, rz)
        coll.objects.link(o)
        if parent is not None:
            o.parent = parent
        return o

    # ---- road network: main road with two junctions, branches off both sides
    main_ctrl = [(-125, -45), (-90, -32), (-55, -8)]
    J1, J2 = Vector((-15, 4)), Vector((60, 18))
    main_ctrl_tail = [(98, 52), (112, 100), (100, 135)]
    # straighten through junctions
    pre = catmull(main_ctrl + [tuple(J1), (25, -6), tuple(J2)] + main_ctrl_tail, 4.0)

    def tangent_near(pts, j):
        i = min(range(len(pts)), key=lambda k: (pts[k] - j).length)
        a, b = pts[max(0, i - 2)], pts[min(len(pts) - 1, i + 2)]
        return (b - a).normalized()

    t1, t2 = tangent_near(pre, J1), tangent_near(pre, J2)
    ctrl = main_ctrl + [tuple(J1 - t1 * 16), tuple(J1 - t1 * 8), tuple(J1), tuple(J1 + t1 * 8), tuple(J1 + t1 * 16), (25, -6),
                        tuple(J2 - t2 * 16), tuple(J2 - t2 * 8), tuple(J2), tuple(J2 + t2 * 8), tuple(J2 + t2 * 16)] + main_ctrl_tail
    JUNCTIONS.clear()
    for j in (J1, J2):
        JUNCTIONS.append((j.x, j.y, hill(j.x, j.y)))
    main_full = catmull(ctrl)

    def side(j, t, s, far):
        n = Vector((-t.y, t.x)) * s
        return catmull([tuple(j + n * 7), tuple(j + n * 14), tuple(j + n * 24)] + far)

    branches = [
        side(J1, t1, 1, [(-25, 55), (-55, 90), (-90, 108)]),
        side(J1, t1, -1, [(-5, -40), (20, -78), (5, -120)]),
        side(J2, t2, 1, [(35, 62), (28, 105)]),
        side(J2, t2, -1, [(92, -12), (118, -48)]),
    ]

    # cut the main road around the junctions (crossroad pieces fill the gap)
    def split(pts, cuts):
        pieces, cur = [], []
        for v in pts:
            if any((v - j).length < 7.0 for j in cuts):
                if len(cur) > 3:
                    pieces.append(cur)
                cur = []
            else:
                cur.append(v)
        if len(cur) > 3:
            pieces.append(cur)
        return pieces

    main_path = Path(main_full)
    road_pieces = [Path(p) for p in split(main_full, [J1, J2])] + [Path(b) for b in branches]
    all_paths = [main_path] + [Path(b) for b in branches]

    street = dense_street(K["street_segment"])
    for i, path in enumerate(road_pieces):
        cu = bpy.data.curves.new(f"RoadPath{i}", "CURVE")
        cu.dimensions = "3D"
        cu.twist_mode = "Z_UP"
        sp = cu.splines.new("POLY")
        sp.points.add(len(path.p) - 1)
        for k, v in enumerate(path.p):
            sp.points[k].co = (v.x, v.y, v.z, 1)
        cobj = put(cu, (0, 0, 0), name=f"RoadPath{i}")
        cobj.hide_render = True
        cobj.hide_set(True)
        n = max(1, round(path.length / 20))
        sx = path.length / (n * 20)
        road = put(street, (10 * sx, 0, 0), name=f"Road{i}")
        road.scale = (sx, 1, 1)
        arr = road.modifiers.new("Array", "ARRAY")
        arr.count = n
        arr.relative_offset_displace = (1, 0, 0)
        cm = road.modifiers.new("Curve", "CURVE")
        cm.object = cobj
        cm.deform_axis = "POS_X"

    for j, t in ((J1, t1), (J2, t2)):
        z = hill(j.x, j.y)
        put(K["crossroad"].data, (j.x, j.y, z), math.atan2(t.y, t.x), name="Crossroad")

    # ---- buildings along every road
    road_pts = [v for p in all_paths for v in p.p]
    rkd = kdtree.KDTree(len(road_pts))
    for i, v in enumerate(road_pts):
        rkd.insert((v.x, v.y, 0), i)
    rkd.balance()

    def bounds(o):
        xs = [c[0] for c in o.bound_box]
        ys = [c[1] for c in o.bound_box]
        return min(xs), max(xs), min(ys), max(ys)

    kinds = {k: bounds(K[k]) for k in ("building_a", "building_b", "building_c")}
    plinth_me = bpy.data.meshes.get("PlinthBox")
    if plinth_me is None:
        plinth_me = bpy.data.meshes.new("PlinthBox")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(plinth_me)
        bm.free()
        plinth_me.materials.append(material("TownConcrete", concrete_nodes))
    placed = []
    lamp_cols = [(1.0, 0.62, 0.32), (0.4, 0.8, 1.0), (1.0, 0.35, 0.75), (1.0, 0.62, 0.32)]

    def clear_of_roads(corners, margin):
        c = sum(corners, Vector((0, 0))) / 4
        for (co, idx, d) in rkd.find_range((c.x, c.y, 0), 30):
            p = Vector((co[0], co[1]))
            # distance point->convex quad (approx by edge distances)
            inside = all((corners[(i + 1) % 4] - corners[i]).to_3d().cross((p - corners[i]).to_3d()).z >= 0 for i in range(4)) or \
                     all((corners[(i + 1) % 4] - corners[i]).to_3d().cross((p - corners[i]).to_3d()).z <= 0 for i in range(4))
            if inside:
                return False
            for i in range(4):
                a, b = corners[i], corners[(i + 1) % 4]
                ab = b - a
                t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
                if (a + ab * t - p).length < margin:
                    return False
        return True

    n_build = 0
    for path in all_paths:
        for sgn in (1, -1):
            s = 9.0
            while s < path.length - 9:
                kind = rng.choice(["building_a", "building_a", "building_b", "building_c"])
                xmin, xmax, ymin, ymax = kinds[kind]
                w = xmax - xmin
                ok = False
                for back in (0.3, 1.5, 3.0):
                    pos, t = path.at(s + w / 2)
                    nout = Vector((-t.y, t.x)) * sgn
                    rz = math.atan2(-nout.x, nout.y)
                    c = pos.to_2d() + nout * (STREET_HALF + back - ymin)
                    corners = rect_corners(c, rz, xmin, xmax, ymin, ymax)
                    if clear_of_roads(corners, STREET_HALF + 0.1) and not any(overlap(corners, q) for q in placed):
                        ok = True
                        break
                if not ok:
                    s += 3.0
                    continue
                placed.append(corners)
                z = pos.z + SIDEWALK_Z
                b = put(K[kind].data, (c.x, c.y, z), rz, name=kind)
                pl = put(plinth_me, ((xmin + xmax) / 2, (ymin + ymax) / 2, -4.0), name="Footing", parent=b)
                pl.scale = (w - 0.05, ymax - ymin - 0.05, 8.0)
                if rng.random() < 0.65:
                    put(K["overhead_sign"].data, (rng.uniform(xmin + 1.2, xmax - 1.2), ymin, rng.uniform(4.0, 7.5)), name="HangingSign", parent=b)
                n_build += 1
                s += w + rng.uniform(0.4, 1.6)

    # ---- lamps, poles, lights
    n_lamp = 0
    for path in all_paths:
        s, sgn = 6.0, 1
        while s < path.length - 6:
            pos, t = path.at(s)
            if any((pos.to_2d() - j).length < 11 for j in (J1, J2)):
                s += 4
                continue
            nout = Vector((-t.y, t.x)) * sgn
            rz = math.atan2(-nout.x, nout.y)
            p = pos.to_2d() + nout * 6.4
            put(K["street_lamp"].data, (p.x, p.y, pos.z + SIDEWALK_Z), rz, name="StreetLamp")
            d = bpy.data.lights.new("LampLight", "POINT")
            d.color = lamp_cols[n_lamp % 4]
            d.energy = 380
            d.shadow_soft_size = 0.3
            lp = pos.to_2d() + nout * 4.3
            put(d, (lp.x, lp.y, pos.z + SIDEWALK_Z + 5.8), name="LampLight")
            if n_lamp % 3 == 1:
                q = path.at(min(path.length - 1, s + 9))[0]
                pp = q.to_2d() - nout * 6.6
                put(K["power_pole"].data, (pp.x, pp.y, q.z + SIDEWALK_Z), rz + math.pi, name="PowerPole")
            n_lamp += 1
            s += 21
            sgn = -sgn

    # ---- terrain: paved, flattened beside roads, rolling hills beyond
    size, step = 320.0, 1.5
    n = int(size / step) + 1
    me = bpy.data.meshes.get("TownTerrain") or bpy.data.meshes.new("TownTerrain")
    bm = bmesh.new()
    verts = []
    for iy in range(n):
        for ix in range(n):
            x, y = -size / 2 + ix * step, -size / 2 + iy * step
            co, idx, d = rkd.find((x, y, 0))
            pz = road_pts[idx].z
            if d < 6.0:
                z = pz - 0.06
            elif d < 6.9:
                z = pz + 0.30
            elif d < 24:
                z = pz + SIDEWALK_Z - 0.01
            else:
                t = min(1.0, (d - 24) / 22)
                t = t * t * (3 - 2 * t)
                z = (pz + SIDEWALK_Z) * (1 - t) + (road_height(x, y) + wild(x, y) * min(1.0, (d - 24) / 40) + 1.0) * t
            verts.append(bm.verts.new((x, y, z)))
    for iy in range(n - 1):
        for ix in range(n - 1):
            a = iy * n + ix
            bm.faces.new((verts[a], verts[a + 1], verts[a + n + 1], verts[a + n]))
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.clear()
    me.materials.append(material("TownPaving", paving_nodes))
    put(me, (0, 0, 0), name="TownTerrain")

    # ---- night world with fog
    w = bpy.data.worlds.get("TownNight") or bpy.data.worlds.new("TownNight")
    w.use_nodes = True
    nt = w.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.012, 0.016, 0.035, 1)
    bg.inputs["Strength"].default_value = 1.0
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = 0.006
    vol.inputs["Color"].default_value = (0.55, 0.6, 0.8, 1)
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    sc.world = w

    # ---- camera on the main road, looking up the hill
    cam = bpy.data.objects.get("TownCam")
    if cam is None:
        cam = bpy.data.objects.new("TownCam", bpy.data.cameras.new("TownCam"))
    if cam.name not in coll.objects:
        coll.objects.link(cam)
    pos, t = main_path.at(40)
    look, _ = main_path.at(95)
    cam.location = (pos.x - t.y * 2.5, pos.y + t.x * 2.5, pos.z + 2.0)
    cam.rotation_euler = (look + Vector((0, 0, 6)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 24
    sc.camera = cam
    print(f"roads {len(road_pieces)}  buildings {n_build}  lamps {n_lamp}")


build()
