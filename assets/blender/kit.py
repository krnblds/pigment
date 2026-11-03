# Shared modelling helpers for the material test models (armchair, planter,
# stone_column, ...). Each model script does
#
#   sys.path.insert(0, os.path.dirname(__file__)); from kit import *
#
# then builds parts with box / cyl / torus / tube / lathe / rock and calls
# export(name). Unlike the older single-file scripts, parts carry a material
# (`mat="Leather"`): the GLB keeps one glTF material per name, so Pigment
# opens it with one texture set per material. Each material is unwrapped and
# packed into its own 0..1 square (as texture sets expect), or into its own
# UDIM tile when export(udim={...}) asks for that.

import math
import random
import sys

import bpy
from mathutils import Vector, noise

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "model.glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
parts = []

# viewport colours only (Pigment ignores them); keeps the .glb readable in Blender
SWATCH = {
    "Wood": (0.45, 0.28, 0.15), "Leather": (0.35, 0.18, 0.1), "Metal": (0.6, 0.6, 0.62),
    "Brass": (0.75, 0.6, 0.3), "Iron": (0.25, 0.25, 0.27), "Glass": (0.8, 0.9, 0.95),
    "Wax": (0.95, 0.92, 0.82), "Flame": (1.0, 0.75, 0.3), "Stone": (0.6, 0.58, 0.55), "Terracotta": (0.7, 0.38, 0.25),
    "Soil": (0.2, 0.14, 0.1), "Bark": (0.3, 0.22, 0.16), "EndGrain": (0.7, 0.55, 0.38),
    "Ceramic": (0.92, 0.92, 0.9), "Gold": (0.85, 0.68, 0.3), "Floor": (0.5, 0.35, 0.2),
    "Wall": (0.85, 0.82, 0.75), "Trim": (0.95, 0.95, 0.93), "Rock": (0.5, 0.48, 0.45),
}


def material(name):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.diffuse_color = (*SWATCH.get(name, (0.7, 0.7, 0.7)), 1.0)
    return m


def finish(o, bevel, segments=3, angle=35, mat="Main"):
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.shade_smooth()
    if bevel > 0:
        m = o.modifiers.new("bevel", "BEVEL")
        m.width = bevel
        m.segments = segments
        m.limit_method = "ANGLE"
        m.angle_limit = math.radians(angle)
        m.harden_normals = True
    o.select_set(False)
    o.data.materials.clear()
    o.data.materials.append(material(mat))
    parts.append(o)
    return o


def box(name, size, loc, bevel=0.004, segments=3, rot=(0, 0, 0), mat="Main"):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    return finish(o, bevel, segments, mat=mat)


def cyl(name, r, depth, loc, rot=(0, 0, 0), bevel=0.002, segments=2, verts=24, mat="Main"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return finish(o, bevel, segments, mat=mat)


def cone(name, r1, r2, depth, loc, rot=(0, 0, 0), bevel=0.002, segments=2, verts=24, mat="Main"):
    """Tapered cylinder: r1 at the bottom, r2 at the top."""
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return finish(o, bevel, segments, mat=mat)


def sphere(name, r, loc, scale=(1, 1, 1), segs=24, rings=12, mat="Main"):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segs, ring_count=rings, radius=r, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    return finish(o, 0, mat=mat)


def torus(name, R, r, loc, rot=(0, 0, 0), maj=48, mi=10, mat="Main"):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=maj, minor_segments=mi, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return finish(o, 0, mat=mat)


def apply_mods(o):
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def cutter(size, loc, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    c = bpy.context.active_object
    c.scale = size
    return c


def cut(body, cutters, lip_bevel=0.0025):
    """Boolean the cutters out of an already-bevelled body, then bevel the new lips."""
    apply_mods(body)
    parts.remove(body)
    mat = body.data.materials[0].name
    for c in cutters:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = c
        c.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bm = body.modifiers.new("cut", "BOOLEAN")
        bm.operation = "DIFFERENCE"
        bm.object = c
        try:
            bm.solver = "EXACT"
        except TypeError:
            pass
        apply_mods(body)
        bpy.data.objects.remove(c, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = body
    body.select_set(True)
    if body.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
    body.select_set(False)
    return finish(body, lip_bevel, 2, angle=40, mat=mat)


def fillet_path(pts, rad, steps=8):
    """Round the corners of a polyline with quadratic arcs (bent tube look)."""
    pts = [Vector(p) for p in pts]
    if rad <= 0 or len(pts) < 3:
        return pts
    res = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, p, b = pts[i - 1], pts[i], pts[i + 1]
        da, db = a - p, b - p
        t = min(rad, da.length / 2, db.length / 2)
        p0 = p + da.normalized() * t
        p1 = p + db.normalized() * t
        for k in range(steps + 1):
            s = k / steps
            res.append((1 - s) ** 2 * p0 + 2 * (1 - s) * s * p + s * s * p1)
    res.append(pts[-1])
    clean = [res[0]]
    for q in res[1:]:
        if (q - clean[-1]).length > 1e-5:
            clean.append(q)
    return clean


def tube(name, pts, r, fillet=0.0, cyclic=False, res=4, steps=8, mat="Main"):
    """A round tube along a polyline: curve with bevel depth, converted to mesh."""
    cd = bpy.data.curves.new(name, "CURVE")
    cd.dimensions = "3D"
    cd.bevel_mode = "ROUND"
    cd.bevel_depth = r
    cd.bevel_resolution = res
    cd.use_fill_caps = not cyclic
    path = [Vector(p) for p in pts] if cyclic else fillet_path(pts, fillet, steps)
    sp = cd.splines.new("POLY")
    sp.points.add(len(path) - 1)
    for pt, co in zip(sp.points, path):
        pt.co = (co.x, co.y, co.z, 1.0)
    sp.use_cyclic_u = cyclic
    o = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    o = bpy.context.active_object
    o.select_set(False)
    return finish(o, 0, mat=mat)


def band(name, pts, width, thick, side=(1, 0, 0), mat="Main"):
    """A flat strap swept along a polyline: iron bands, leather straps. The
    strap's width lies along `side` (keep the path perpendicular to it), its
    thickness along side x tangent; the ends are capped."""
    side = Vector(side).normalized()
    pts = [Vector(p) for p in pts]
    verts, faces = [], []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        n = side.cross(t).normalized()
        for sw, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(p + side * sw * width / 2 + n * sn * thick / 2)
    for i in range(len(pts) - 1):
        for k in range(4):
            a, b = i * 4 + k, i * 4 + (k + 1) % 4
            faces.append((a, b, b + 4, a + 4))
    faces.append((3, 2, 1, 0))
    last = (len(pts) - 1) * 4
    faces.append((last, last + 1, last + 2, last + 3))
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
    o.select_set(False)
    return finish(o, 0, mat=mat)


def spline(pts, steps=4):
    """Catmull-Rom through 2D points (end points kept): smooth lathe profiles."""
    pts = [Vector(p) for p in pts]
    res = []
    for i in range(len(pts) - 1):
        p0, p1, p2 = pts[max(i - 1, 0)], pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        for k in range(steps):
            t = k / steps
            res.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    res.append(pts[-1])
    return [tuple(p) for p in res]


def lathe(name, profile, loc=(0, 0, 0), segs=48, mat="Main", smooth_angle=40):
    """Revolve a (radius, z) profile around z. A profile point at radius 0 closes
    the surface there; sharp profile corners stay sharp (smooth by angle)."""
    me = bpy.data.meshes.new(name)
    verts, faces = [], []
    n = len(profile)
    for i in range(segs):
        a = 2 * math.pi * i / segs
        for r, z in profile:
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for i in range(segs):
        j = (i + 1) % segs
        for k in range(n - 1):
            faces.append((i * n + k, j * n + k, j * n + k + 1, i * n + k + 1))
    me.from_pydata(verts, [], faces)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.location = loc
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)  # weld the axis points
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
    o.select_set(False)
    o.data.materials.append(material(mat))
    parts.append(o)
    return o


def fbm(p, octaves=4):
    s, amp, f = 0.0, 0.5, 1.0
    for _ in range(octaves):
        s += amp * noise.noise(p * f)
        amp *= 0.5
        f *= 2.03
    return s


def displace(o, amount, scale, seed=0.0, octaves=4, mask=None):
    """Push vertices along their normals by fbm noise (organic surfaces).
    mask(co) -> 0..1 limits where it applies."""
    off = Vector((seed * 17.3, seed * 5.1, seed * 9.7))
    me = o.data
    for v in me.vertices:
        w = 1.0 if mask is None else mask(v.co)
        if w > 0:
            v.co += v.normal * amount * w * fbm(v.co * scale + off, octaves)
    me.update()


def rock(name, r, loc, scale=(1, 1, 1), seed=0, sub=4, rough=0.35, mat="Rock", flat_base=True, facets=7, chips=0, strata=0.0, grain=0.0):
    """A boulder: subdivided icosphere, squashed, displaced with ridged noise,
    sliced by `facets` random fracture planes (flat-ish faces with edges
    between them), with a flattened base so it sits on the ground.
    Detail (all off by default): `chips` small planes knock off corners and
    edges; `strata` (fraction of r) adds sawtooth bedding ledges on the
    sides; `grain` (fraction of r) pushes ridged noise along the normals for
    lumps, pits and small ridges. Use sub=5 or more so the detail holds."""
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=sub, radius=r, location=(0, 0, 0))
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    off = Vector((seed * 3.7, seed * 1.3, seed * 2.9))
    for v in o.data.vertices:
        d = v.co.normalized()
        big = noise.noise(d * 1.3 + off) * 0.25
        ridge = (1 - abs(noise.noise(d * 3.1 + off * 2))) * 0.12
        fine = fbm(d * 7 + off, 3) * 0.06
        v.co *= 1 + (big + ridge + fine) * rough / 0.35
    rnd = random.Random(seed)
    planes = []
    for _ in range(facets):
        d = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1) * 0.6 + 0.3)).normalized()  # mostly sides and tops
        planes.append((d, rnd.uniform(0.62, 0.85)))
    for v in o.data.vertices:
        for d, cut_at in planes:
            sd = Vector((d.x * scale[0], d.y * scale[1], d.z * scale[2])) * r
            h = v.co.dot(d)
            lim = cut_at * sd.length
            if h > lim:
                # flatten onto the plane, keep a little of the noise as surface texture
                v.co -= d * (h - lim) * 0.9
    # chips: many small fracture planes that knock corners and edges off the big facets
    for _ in range(chips):
        d = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1))).normalized()
        sd = Vector((d.x * scale[0], d.y * scale[1], d.z * scale[2])) * r
        lim = max(v.co.dot(d) for v in o.data.vertices) - rnd.uniform(0.03, 0.09) * r
        for v in o.data.vertices:
            h = v.co.dot(d)
            if h > lim:
                v.co -= d * (h - lim) * 0.95
    if strata or grain:
        o.data.update()  # normals of the cut shape
        axis = Vector((rnd.gauss(0, 0.3), rnd.gauss(0, 0.3), 1)).normalized()  # bedding, a little tilted
        for v in o.data.vertices:
            n = v.normal
            dz = 0.0
            if strata:
                # sawtooth ledges: each bed steps out, then weathers back
                s = (v.co.dot(axis) / (r * 0.22) + 0.3 * noise.noise(v.co * 2 + off)) % 1.0
                dz += strata * r * (s ** 3 - 0.25) * (1 - abs(n.dot(axis)))  # on the sides, not the tops
            if grain:
                # ridged multi-octave noise: lumps, pits and sharp little ridges
                p = v.co / r * 6 + off
                rid = sum((1 - abs(noise.noise(p * f))) ** 2 / f for f in (1, 2.3, 5.1))
                dz += grain * r * (rid - 0.9)
            v.co += n * dz
    for v in o.data.vertices:
        if flat_base and v.co.z < -r * scale[2] * 0.45:
            v.co.z = -r * scale[2] * 0.45 + (v.co.z + r * scale[2] * 0.45) * 0.1
    o.data.update()
    o.location = loc
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    return finish(o, 0, mat=mat)


def _unwrap(obj, rotate, margin=0.006):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=rotate, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def export(name, udim=None, rotate=True, ground=True, max_tris=80000, planar=None):
    """Join the parts, unwrap each material into its own 0..1 square (or its
    UDIM tile, udim={"Wall": 1002, ...}), and write the GLB to `out`.
    planar={"EndGrain": (cx, cy, half)} maps a material straight down from
    above instead: the square [cx +- half] x [cy +- half] fills 0..1 (one
    image over a cut face: rings stay round, the pith where you put it)."""
    for o in parts:
        apply_mods(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if ground:
        mz = min(v.co.z for v in obj.data.vertices)
        for v in obj.data.vertices:
            v.co.z -= mz
    # unused slots would export as empty materials
    used = {p.material_index for p in obj.data.polygons}
    for i in reversed(range(len(obj.data.materials))):
        if i not in used:
            obj.data.materials.pop(index=i)

    # one object per material: unwrap and pack each into 0..1, then rejoin
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    if len(obj.data.materials) > 1:
        bpy.ops.mesh.separate(type="MATERIAL")
    pieces = list(bpy.context.selected_objects)
    for p in pieces:
        box = (planar or {}).get(p.data.materials[0].name)
        if box:
            cx, cy, half = box
            if not p.data.uv_layers:
                p.data.uv_layers.new()
            for poly in p.data.polygons:
                for li, vi in zip(poly.loop_indices, poly.vertices):
                    co = p.matrix_world @ p.data.vertices[vi].co
                    p.data.uv_layers[0].data[li].uv = ((co.x - cx) / (2 * half) + 0.5, (co.y - cy) / (2 * half) + 0.5)
        else:
            _unwrap(p, rotate)
        tile = (udim or {}).get(p.data.materials[0].name, 1001)
        du, dv = (tile - 1001) % 10, (tile - 1001) // 10
        for d in p.data.uv_layers[0].data:
            d.uv.x += du
            d.uv.y += dv
    bpy.ops.object.select_all(action="DESELECT")
    for p in pieces:
        p.select_set(True)
    bpy.context.view_layer.objects.active = pieces[0]
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name

    me = obj.data
    assert len(me.uv_layers) == 1, len(me.uv_layers)
    mats = [m.name for m in me.materials]
    for mi, mname in enumerate(mats):
        faces = [p for p in me.polygons if p.material_index == mi]
        loops = [li for p in faces for li in p.loop_indices]
        us = [me.uv_layers[0].data[li].uv.x for li in loops]
        vs = [me.uv_layers[0].data[li].uv.y for li in loops]
        tile = (udim or {}).get(mname, 1001)
        du, dv = (tile - 1001) % 10, (tile - 1001) // 10
        print(f"  {mname}: tile {tile}, {sum(len(p.vertices) - 2 for p in faces)} tris, u [{min(us):.3f}, {max(us):.3f}] v [{min(vs):.3f}, {max(vs):.3f}]")
        assert min(us) >= du and max(us) <= du + 1 and min(vs) >= dv and max(vs) <= dv + 1, f"{mname}: UVs outside its tile"

    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    print(f"{name}: {len(me.vertices)} verts, {tris} tris, materials {mats}")
    print(f"size: {max(xs)-min(xs):.3f} x {max(ys)-min(ys):.3f} x {max(zs)-min(zs):.3f} m, min z {min(zs):.4f}")
    assert tris < max_tris, tris

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_texcoords=True, export_normals=True, export_materials="EXPORT", export_yup=True)
    print("exported", out)
