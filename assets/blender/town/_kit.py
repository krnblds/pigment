# Shared helpers for the modular cyberpunk town kit (assets/blender/town/*.py).
#
# Same conventions as assets/blender/vending_machine.py: bevel modifiers with
# harden normals and an angle limit, shade smooth, modifiers applied, every
# piece joined into ONE mesh object, ONE UV map (smart project + pack), all UVs
# in 0..1, transforms applied, GLB exported without materials, +Y up.
#
# Pigment picks "parts" as connected components of the joined mesh, welding
# vertices by quantised position. So every logically different surface is
# built as its own closed piece, pieces are never merged, and touching pieces
# are kept a few millimetres apart so no two pieces share a vertex position.

import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "out.glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
parts = []

# facade sides: rotation about Z that turns a -Y facing piece to face that way
SIDE_ROT = {"S": 0.0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}


def _link(o):
    bpy.context.scene.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    return o


def finish(o, bevel, segments=2, angle=35):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if o.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    if bevel > 0:
        bpy.ops.object.shade_smooth()
    else:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
    if bevel > 0:
        m = o.modifiers.new("bevel", "BEVEL")
        m.width = bevel
        m.segments = segments
        m.limit_method = "ANGLE"
        m.angle_limit = math.radians(angle)
        m.harden_normals = True
    o.select_set(False)
    parts.append(o)
    return o


def raw_box(size, loc=(0, 0, 0), rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return o


def box(name, size, loc, bevel=0.01, segments=2, rot=(0, 0, 0), angle=35):
    o = raw_box(size, loc, rot)
    o.name = name
    return finish(o, bevel, segments, angle)


def cyl(name, r, depth, loc, rot=(0, 0, 0), bevel=0.004, segments=2, verts=20):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    return finish(o, bevel, segments)


def rod(name, a, b, r, bevel=0.0, verts=12):
    """Cylinder from point a to point b."""
    a, b = Vector(a), Vector(b)
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=d.length, location=(a + b) / 2)
    o = bpy.context.active_object
    o.name = name
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = d.normalized().to_track_quat("Z", "Y")
    return finish(o, bevel, 2)


def mesh_obj(name, bm, loc=(0, 0, 0), rot=(0, 0, 0)):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = loc
    o.rotation_euler = rot
    _link(o)
    return o


def lathe(name, prof, loc, segs=24, bevel=0.0, rot=(0, 0, 0), angle=35):
    """Surface of revolution about local Z; prof = [(radius, z), ...] bottom to top."""
    bm = bmesh.new()
    rings = []
    for r, z in prof:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs), z)) for i in range(segs)])
    for a, b in zip(rings, rings[1:]):
        if len(a) == 1 and len(b) == 1:
            continue
        for i in range(segs):
            j = (i + 1) % segs
            if len(a) == 1:
                bm.faces.new((a[0], b[i], b[j]))
            elif len(b) == 1:
                bm.faces.new((a[i], a[j], b[0]))
            else:
                bm.faces.new((a[i], a[j], b[j], b[i]))
    if len(rings[0]) > 1:
        bm.faces.new(list(reversed(rings[0])))
    if len(rings[-1]) > 1:
        bm.faces.new(rings[-1])
    o = mesh_obj(name, bm, loc, rot)
    return finish(o, bevel, 2, angle)


def prism(name, pts, z0, z1, bevel=0.0, segments=2, angle=35, loc=(0, 0, 0)):
    """Extrude a simple 2D polygon (x, y) between z0 and z1."""
    bm = bmesh.new()
    lo = [bm.verts.new((x, y, z0)) for x, y in pts]
    hi = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
    o = mesh_obj(name, bm, loc)
    return finish(o, bevel, segments, angle)


def cut(o, cutters):
    """Boolean all cutters out of o (no modifiers on o yet) in one exact pass."""
    if not cutters:
        return o
    coll = bpy.data.collections.new("cutters")
    bpy.context.scene.collection.children.link(coll)
    for c in cutters:
        for uc in list(c.users_collection):
            uc.objects.unlink(c)
        coll.objects.link(c)
    m = o.modifiers.new("cut", "BOOLEAN")
    m.operation = "DIFFERENCE"
    m.operand_type = "COLLECTION"
    m.collection = coll
    m.solver = "EXACT"
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.modifier_apply(modifier=m.name)
    for c in cutters:
        bpy.data.objects.remove(c, do_unlink=True)
    bpy.data.collections.remove(coll)
    return o


def cut_split(shell, cuts, z, gap=0.002):
    """cut(shell, cuts), returned as two pieces split at height z: (ground
    floor, upper floors). The seam hides behind the string course at z; the
    ground floor gets its own UV island so street-level decals (posters,
    graffiti) can be given more texture space with uv_boost."""
    lower = shell.copy()
    lower.data = shell.data.copy()
    lower.name = shell.name + "_ground"
    bpy.context.scene.collection.objects.link(lower)
    big = 400.0
    copies = []
    for c in cuts:
        d = c.copy()
        d.data = c.data.copy()
        bpy.context.scene.collection.objects.link(d)
        copies.append(d)
    cut(lower, copies + [cutter((big, big, big), (0, 0, z + big / 2))])
    cut(shell, cuts + [cutter((big, big, big), (0, 0, z + gap - big / 2))])
    return lower, shell


def cutter(size, loc=(0, 0, 0), rot=(0, 0, 0)):
    return raw_box(size, loc, rot)


def holed(name, size, holes, loc, rotz=0.0, bevel=0.01, segments=2, extra_cutters=()):
    """A plate in local XZ (thickness along Y) with rectangular through-holes.

    holes: [(cx, cz, w, h)] in plate-local coordinates. Built at the origin, then
    rotated about Z and moved to loc. One connected piece (frames, railings, grilles).
    """
    o = raw_box(size)
    o.name = name
    cs = [cutter((w, size[1] * 4, h), (cx, 0, cz)) for cx, cz, w, h in holes]
    cs += [cutter(s, l) for s, l in extra_cutters]
    cut(o, cs)
    o.location = loc
    o.rotation_euler = (0, 0, rotz)
    return finish(o, bevel, segments)


def grooved(name, size, grooves, loc, rotz=0.0, bevel=0.006):
    """A slab with shallow horizontal grooves on its -Y face: grooves = [(cz, h, depth)]."""
    w, d, h = size
    cs = [cutter((w + 0.2, 2 * dep, gh), (0, -d / 2, cz)) for cz, gh, dep in grooves]
    o = raw_box(size)
    o.name = name
    cut(o, cs)
    o.location = loc
    o.rotation_euler = (0, 0, rotz)
    return finish(o, bevel, 2)


class Facade:
    """Coordinates on the four outer faces of a W x D box building centred on the origin.

    u runs along the face (left to right seen from outside), d is the distance
    behind the face plane (positive = into the building), z is height.
    """

    def __init__(self, W, D):
        self.W, self.D = W, D

    def half(self, side):
        return self.D / 2 if side in "SN" else self.W / 2

    def width(self, side):
        return self.W if side in "SN" else self.D

    def pos(self, side, u, d, z):
        v = Matrix.Rotation(SIDE_ROT[side], 3, "Z") @ Vector((u, -self.half(side) + d, 0))
        return (v.x, v.y, z)

    def rot(self, side):
        return SIDE_ROT[side]


def window(F, shell_cuts, side, u, zb, w, h, mullions=1, recess=0.22, frame_bar=0.06, sill=True, glass=True, name="win", panes=None):
    """Recess in the shell, a mullioned frame, glass pane(s) behind it and a sill.

    Frame and glass are separate parts; panes splits the glass into that many parts.
    """
    r = F.rot(side)
    zc = zb + h / 2
    shell_cuts.append(cutter((w, recess * 2, h), F.pos(side, u, 0, zc), (0, 0, r)))
    fw, fh, ft = w - 0.008, h - 0.008, 0.06
    n = mullions + 1
    iw = (fw - frame_bar * (n + 1)) / n
    ih = fh - 2 * frame_bar
    holes = [(-fw / 2 + frame_bar + iw / 2 + k * (iw + frame_bar), 0, iw, ih) for k in range(n)]
    holed(f"{name}_frame", (fw, ft, fh), holes, F.pos(side, u, 0.07, zc), r, bevel=0.008)
    if glass:
        np_ = panes or 1
        gw = (w - 0.03 - 0.01 * (np_ - 1)) / np_
        for k in range(np_):
            gu = u - (w - 0.03) / 2 + gw / 2 + k * (gw + 0.01)
            box(f"{name}_glass", (gw, 0.012, h - 0.03), F.pos(side, gu, 0.16, zc), bevel=0.002, rot=(0, 0, r))
    if sill:
        box(f"{name}_sill", (w + 0.16, 0.12, 0.07), F.pos(side, u, -0.03, zb - 0.04), bevel=0.012, rot=(0, 0, r))


def ac_unit(F, side, u, z, name="ac"):
    """Wall AC unit hanging on a bracket: casing, fan grille disc, bracket (3 parts)."""
    r = F.rot(side)
    W_, D_, H_ = 0.82, 0.32, 0.56
    box(f"{name}_case", (W_, D_, H_), F.pos(side, u, -(D_ / 2 + 0.05), z + H_ / 2), bevel=0.02, segments=3, rot=(0, 0, r))
    holes = [(0, -0.17 + 0.05 * k, 0.40, 0.02) for k in range(8)]
    holed(f"{name}_grille", (0.46, 0.02, 0.46), holes, F.pos(side, u - 0.12, -(D_ + 0.05 + 0.012), z + H_ / 2), r, bevel=0.004)
    br = holed(f"{name}_bracket", (W_ - 0.1, D_ + 0.05, 0.05), [], F.pos(side, u, -(D_ + 0.05) / 2 + 0.002, z - 0.03), r, bevel=0.006)
    return br


# ---------------------------------------------------------------- export + checks


def _components(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    comp = [-1] * len(bm.faces)
    vcomp = [-1] * len(bm.verts)
    n = 0
    for f in bm.faces:
        if comp[f.index] >= 0:
            continue
        stack = [f]
        comp[f.index] = n
        while stack:
            g = stack.pop()
            for v in g.verts:
                vcomp[v.index] = n
                for h in v.link_faces:
                    if comp[h.index] < 0:
                        comp[h.index] = n
                        stack.append(h)
        n += 1
    bm.free()
    return n, vcomp


def _welded_components(me):
    """Pigment-style: weld vertices by quantised position, then count linked triangles."""
    co = [v.co.copy() for v in me.vertices]
    lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
    hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
    r = (hi - lo).length / 2
    q = 1e5 / max(r, 1e-6)
    key = {}
    wid = []
    for c in co:
        k = (round(c.x * q), round(c.y * q), round(c.z * q))
        wid.append(key.setdefault(k, len(key)))
    parent = list(range(len(key)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for p in me.polygons:
        vs = [wid[i] for i in p.vertices]
        a = find(vs[0])
        for b in vs[1:]:
            b = find(b)
            if a != b:
                parent[b] = a
    used = {find(wid[i]) for p in me.polygons for i in p.vertices}
    return len(used)


def uv_boost(o, k, facing=None):
    """Give piece o k times the texel density of the rest: signage faces that
    carry readable decals (billboard panels, sign boxes, fascias, plates).
    facing: only the faces whose normal points that way (world direction),
    e.g. a sign box's front, so its back and sides don't take texture space."""
    o["uvw"] = float(k)
    if facing is not None:
        o["uvw_dir"] = [float(x) for x in facing]
    return o


def _face_weights(o):
    k = float(o.get("uvw", 1.0))
    d = o.get("uvw_dir")
    if d is None:
        return [k] * len(o.data.polygons)
    d = Vector(d).normalized()
    return [k if p.normal.dot(d) > 0.9 else 1.0 for p in o.data.polygons]


def _boost_uvs(me):
    """Scale whole UV islands whose faces are mostly boosted (face attribute
    "uvw" > 1) about their own centre; pack_islands then lays everything out
    again with these relative sizes."""
    from bpy_extras.mesh_utils import mesh_linked_uv_islands

    a = me.attributes.get("uvw")
    if a is None:
        return
    w = [d.value for d in a.data]
    if all(abs(x - 1.0) < 1e-6 for x in w):
        return
    uv = me.uv_layers[0].data
    n = 0
    for island in mesh_linked_uv_islands(me):
        area = sum(me.polygons[i].area for i in island)
        boosted = [i for i in island if w[i] > 1.0 + 1e-6]
        if not boosted or sum(me.polygons[i].area for i in boosted) < 0.5 * area:
            continue
        k = max(w[i] for i in boosted)
        loops = [li for i in island for li in me.polygons[i].loop_indices]
        cu = sum(uv[li].uv.x for li in loops) / len(loops)
        cv = sum(uv[li].uv.y for li in loops) / len(loops)
        for li in loops:
            uv[li].uv = (cu + (uv[li].uv.x - cu) * k, cv + (uv[li].uv.y - cv) * k)
        n += 1
    print(f"UV boost: {n} islands")


def export(name, centre_xy=True, max_tris=80000, max_parts=240, close=(), view=(-1.0, -1.45, 0.75)):
    """close: extra preview shots [(suffix, centre, radius, view_dir)] in final coordinates."""
    for o in parts:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = o
        for m in list(o.modifiers):
            bpy.ops.object.modifier_apply(modifier=m.name)
        # per-face UV weight (after the bevel) survives the join as a face attribute
        a = o.data.attributes.get("uvw") or o.data.attributes.new("uvw", "FLOAT", "FACE")
        a.data.foreach_set("value", _face_weights(o))
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    me = obj.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    off = Vector(((max(xs) + min(xs)) / 2 if centre_xy else 0, (max(ys) + min(ys)) / 2 if centre_xy else 0, min(zs)))
    for v in me.vertices:
        v.co -= off

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    _boost_uvs(me)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    if "uvw" in me.attributes:
        me.attributes.remove(me.attributes["uvw"])

    assert len(me.uv_layers) == 1, len(me.uv_layers)
    uv = me.uv_layers[0].data
    us = [d.uv.x for d in uv]
    vs = [d.uv.y for d in uv]
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    print(f"UV bounds: u [{umin:.4f}, {umax:.4f}]  v [{vmin:.4f}, {vmax:.4f}]")
    assert umin >= 0 and vmin >= 0 and umax <= 1 and vmax <= 1, "UVs outside 0..1"

    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    nparts, vcomp = _components(me)
    welded = _welded_components(me)
    print(f"{name}: {len(me.vertices)} verts, {len(me.polygons)} faces, {tris} tris, uv layers {len(me.uv_layers)}")
    print(f"origin {tuple(round(c, 4) for c in obj.location)}")
    print(f"size: {max(xs)-min(xs):.3f} x {max(ys)-min(ys):.3f} x {max(zs)-min(zs):.3f} m  (x {min(xs):.3f}..{max(xs):.3f}, y {min(ys):.3f}..{max(ys):.3f}, z {min(zs):.4f}..{max(zs):.3f})")
    print(f"parts (bmesh linked faces): {nparts}   parts after position weld: {welded}   source pieces: {len(parts)}")
    print(f"STATS {name} dims={max(xs)-min(xs):.2f}x{max(ys)-min(ys):.2f}x{max(zs)-min(zs):.2f} tris={tris} parts={nparts} welded={welded} uv=[{umin:.4f},{umax:.4f}]x[{vmin:.4f},{vmax:.4f}]")
    assert tris < max_tris, tris
    assert nparts <= max_parts, nparts
    if welded != nparts:
        print("WARNING: some pieces share vertex positions and would weld together in Pigment")

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=True, export_texcoords=True, export_normals=True, export_materials="NONE", export_yup=True)
    print("exported", OUT)
    preview(obj, vcomp, nparts, view=view, close=close)
    return obj


def preview(obj, vcomp, nparts, view=(-1.0, -1.45, 0.75), res=(1000, 1000), close=()):
    """Workbench render, one colour per part, 3/4 view from the front-left."""
    name = os.path.splitext(os.path.basename(OUT))[0]
    path = os.path.join(os.environ.get("TEMP", "/tmp"), "pig", f"town_{name}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rng = random.Random(7)
    import colorsys

    cols = [colorsys.hsv_to_rgb(rng.random(), 0.25 + 0.3 * rng.random(), 0.6 + 0.35 * rng.random()) for _ in range(nparts)]
    me = obj.data
    attr = me.color_attributes.new("part", "FLOAT_COLOR", "POINT")
    for i, c in enumerate(vcomp):
        r, g, b = cols[c] if c >= 0 else (1, 0, 1)
        attr.data[i].color = (r, g, b, 1)
    me.color_attributes.active_color = attr

    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"
    except TypeError as e:
        print(e)
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "VERTEX"
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.show_object_outline = True
    sh.show_shadows = os.environ.get("PIG_SHADOWS", "1") == "1"
    sc.display.shadow_shift = 0.1
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("w")
    world.color = (0.08, 0.09, 0.11)
    sc.world = world

    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    lo = Vector((min(xs), min(ys), min(zs)))
    hi = Vector((max(xs), max(ys), max(zs)))
    c = (lo + hi) / 2
    rad = (hi - lo).length / 2
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.data.lens = 50
    cam.data.clip_end = 1000
    sc.camera = cam
    shots = [("", c, rad, view)] + [("_" + s_, Vector(c_), r_, v_) for s_, c_, r_, v_ in close]
    for suffix, cc, rr, vv in shots:
        d = Vector(vv).normalized()
        cam.location = cc + d * (rr / math.sin(cam.data.angle / 2) * 0.92)
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = path.replace(".png", suffix + ".png")
        bpy.ops.render.render(write_still=True)
        print("preview", sc.render.filepath)
