"""Build the town kit's chain-link fence segment (assets/town/fence.glb).

A 3 m x 2 m security fence bay, origin at the bottom centre, panel in the XZ plane (Blender),
facing -Y (the street side).  Same interface as before: object "fence", the wire mesh is ONE
quad (the chain-link pattern is a Pigment cut-out, not geometry), posts at x = +-1.5 m.

    galvanised line posts (60 mm) on concrete footings, dome caps, 45 deg barbed-wire arms
    leaning out over the street side, three twisted barbed-wire strands with barbs, top rail
    through loop caps, bottom tension wire, tension bars and bands at the posts, wire ties
    along the posts and the rail, and a HOSHIKAWA PROPERTY plate wired to the mesh.

    blender -b --factory-startup --python tools/make_fence.py
    python tools/town_textures.py fence            # Pigment maps -> scenes/town/textures/fence/
"""
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "town", "fence.glb")
W, H = 3.0, 2.0
TAU = math.tau

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()


def tube(a, b, r, seg=8, caps=True):
    a, b = Vector(a), Vector(b)
    d = b - a
    q = d.normalized().to_track_quat("Z", "Y")
    m = Matrix.Translation(a) @ q.to_matrix().to_4x4()
    r0 = [bm.verts.new(m @ Vector((r * math.cos(TAU * k / seg), r * math.sin(TAU * k / seg), 0))) for k in range(seg)]
    r1 = [bm.verts.new(m @ Vector((r * math.cos(TAU * k / seg), r * math.sin(TAU * k / seg), d.length))) for k in range(seg)]
    for k in range(seg):
        j = (k + 1) % seg
        bm.faces.new((r0[k], r0[j], r1[j], r1[k]))
    if caps:
        bm.faces.new(list(reversed(r0)))
        bm.faces.new(r1)


def lathe(prof, loc, seg=16):
    loc = Vector(loc)
    rings = []
    for r, z in prof:
        if r <= 1e-6:
            rings.append([bm.verts.new(loc + Vector((0, 0, z)))])
        else:
            rings.append([bm.verts.new(loc + Vector((r * math.cos(TAU * k / seg), r * math.sin(TAU * k / seg), z))) for k in range(seg)])
    for a, b in zip(rings, rings[1:]):
        for k in range(seg):
            j = (k + 1) % seg
            if len(a) == 1:
                bm.faces.new((a[0], b[k], b[j]))
            elif len(b) == 1:
                bm.faces.new((a[k], a[j], b[0]))
            else:
                bm.faces.new((a[k], a[j], b[j], b[k]))
    if len(rings[0]) > 1:
        bm.faces.new(list(reversed(rings[0])))
    if len(rings[-1]) > 1:
        bm.faces.new(rings[-1])


def box(c, s):
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(Vector(c)) @ Matrix.Diagonal((*s, 1)))


# the mesh: one quad between the posts (cut-out wire in Pigment)
x0, x1, z0, z1 = -W / 2 + 0.035, W / 2 - 0.035, 0.05, H - 0.04
vs = [bm.verts.new(p) for p in ((x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1))]
bm.faces.new(vs)

for sx in (-1, 1):
    x = sx * W / 2
    lathe([(0.13, -0.02), (0.13, 0.05), (0.09, 0.09), (0.0, 0.095)], (x, 0.0, 0.0), seg=16)        # concrete footing
    tube((x, 0.04, 0.0), (x, 0.04, H + 0.02), 0.03, seg=12)                                        # line post
    lathe([(0.034, 0.0), (0.034, 0.03), (0.026, 0.055), (0.0, 0.065)], (x, 0.04, H + 0.02), seg=12)  # dome cap
    # barbed-wire arm, 45 deg out over the street side (-Y)
    a = Vector((x, 0.04, H + 0.03))
    b = a + Vector((0, -0.33, 0.33))
    tube(a, b, 0.014, seg=6)
    box((x, 0.04, H - 0.02), (0.075, 0.075, 0.07))                                                  # loop cap / arm socket
    # tension bar (flat) inside the mesh edge, four tension bands round the post
    tube((x - sx * 0.04, 0.0, 0.08), (x - sx * 0.04, 0.0, H - 0.08), 0.008, seg=4)
    for z in (0.25, 0.75, 1.25, 1.75):
        lathe([(0.036, -0.012), (0.036, 0.012)], (x, 0.04, z), seg=12)
        box((x - sx * 0.045, 0.02, z), (0.03, 0.012, 0.024))
    # wire ties along the post
    for z in (0.45, 1.0, 1.55):
        tube((x - sx * 0.036, -0.004, z), (x - sx * 0.036, 0.004, z + 0.02), 0.003, seg=4)

# top rail through the loop caps, bottom tension wire, ties along the rail
tube((-W / 2 - 0.05, 0.04, H - 0.02), (W / 2 + 0.05, 0.04, H - 0.02), 0.021, seg=10)
tube((-W / 2, 0.005, 0.07), (W / 2, 0.005, 0.07), 0.0028, seg=4)
for k in range(6):
    x = -W / 2 + 0.25 + k * (W - 0.5) / 5
    tube((x, -0.004, H - 0.05), (x + 0.01, 0.004, H + 0.002), 0.003, seg=4)

# three barbed strands along the arms: two twisted wires each, barbs every 0.15 m
for k, f in enumerate((0.3, 0.62, 0.95)):
    yc, zc = 0.04 - 0.33 * f, H + 0.03 + 0.33 * f
    n = 20
    for w2 in (0, 1):
        pts = [Vector((-W / 2 + W * i / n, yc + 0.0035 * math.cos(i * 1.6 + w2 * math.pi), zc + 0.0035 * math.sin(i * 1.6 + w2 * math.pi))) for i in range(n + 1)]
        for p, q in zip(pts, pts[1:]):
            tube(p, q, 0.0018, seg=4, caps=False)
    for i in range(19):
        x = -W / 2 + 0.15 + i * 0.15
        c = Vector((x, yc, zc))
        tube(c + Vector((-0.012, -0.012, -0.012)), c + Vector((0.012, 0.012, 0.012)), 0.0016, seg=3)
        tube(c + Vector((-0.012, 0.012, 0.012)), c + Vector((0.012, -0.012, -0.012)), 0.0016, seg=3)

# HOSHIKAWA PROPERTY plate wired to the mesh (street side)
box((0.35, -0.012, 1.42), (0.46, 0.004, 0.3))
for dx in (-0.2, 0.2):
    for dz in (-0.12, 0.12):
        tube((0.35 + dx, -0.016, 1.42 + dz), (0.35 + dx, 0.004, 1.42 + dz), 0.0025, seg=4)

me = bpy.data.meshes.new("fence")
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.calc_area() > 1e-9])
bm.to_mesh(me)
bm.free()
fence = bpy.data.objects.new("fence", me)
bpy.context.scene.collection.objects.link(fence)
bpy.context.view_layer.objects.active = fence
fence.select_set(True)
# the mesh quad must face -Y (street side) whatever recalc decided for a lone quad
q = next(p for p in me.polygons if len(p.vertices) == 4 and abs(p.normal.y) > 0.99 and p.area > 5.0)
if q.normal.y > 0:
    q.flip()
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004, scale_to_bounds=True)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.shade_flat()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.export_scene.gltf(filepath=os.path.abspath(OUT), export_format="GLB", use_selection=True, export_materials="NONE")
tris = sum(len(p.vertices) - 2 for p in me.polygons)
print("WROTE", os.path.abspath(OUT), tris, "tris")
