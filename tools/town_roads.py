"""Open-world roads for the town (Blender 5.2, bpy): spline road meshes with
continuous UVs, shared tileable Pigment materials, a trim sheet for curbs and
gutters, decals from a Pigment atlas, and world-space wetness.

Loaded by tools/blender_town.py (exec), which supplies the road graph, paths
and junction geometry. Textures come from scenes/town/textures/roads/ (made by
`python tools/road_textures.py --run`); without them the flat fallback
materials are used and no decals are placed.

Cross-section (distances from the curb line d, metres; road centre at -4):
    asphalt   d < -0.4   z ROAD_Z  world-space planar UVs (metres)  -> asphalt tile
    gutter    -0.4..0    z ROAD_Z  trim "Gutter" strip, U = along / 2 m
    curb face d = 0      ROAD_Z..CURB_Z, trim "Curb face"
    curb top  0..0.25    z CURB_Z  trim "Curb top"
    walk edge 0.25..0.6  z WALK_Z  trim "Walk edge"
    paving    0.6..3.0   z WALK_Z  UV (along, d - 0.6) metres         -> paving tile
    skirt     3.0        down to -1 m, concrete (world box mapped)
Runs and junction corners share it, and the along coordinate is scaled so
it is a whole number of 2 m tiles between junction mouths, so slabs, curb
joints and trim line up at every join. Asphalt is world planar on both, so a
run flows into a junction with no seam at all.
"""
import json
import math
import os
import random

import bmesh
import bpy
import numpy as np
from mathutils import Vector

ROAD_Z, WALK_Z, CURB_Z = 0.2, 0.35, 0.355
GUTTER = 0.4
CURB_W = 0.25
EDGE_W = 0.6
WALK_OUT = 3.0
ROAD_HALF = 4.0
TILE_ALONG = 2.0          # paving / trim period along the road
ASPHALT_TILE = 4.0
PAVING_TILE = 2.0
MAT_ASPHALT, MAT_TRIM, MAT_PAVING, MAT_CONCRETE = range(4)
SEED = 23


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- textures / materials


class RoadTextures:
    def __init__(self, root):
        self.dir = os.path.join(root, "scenes", "town", "textures", "roads")
        self.ok = all(os.path.isfile(os.path.join(self.dir, n, f"{n}_BaseColor.png")) for n in ("asphalt", "paving", "trim", "concrete"))
        self.atlas_ok = os.path.isfile(os.path.join(self.dir, "atlas", "atlas_BaseColorAlpha.png"))
        self.trim = {}
        self.atlas = {}
        if self.ok:
            lay = json.load(open(os.path.join(self.dir, "trim", "trim_layout.json"), encoding="utf-8"))
            self.trim = {c["name"]: c["uv_gl"] for c in lay["cells"]}
        if self.atlas_ok:
            lay = json.load(open(os.path.join(self.dir, "atlas", "atlas_layout.json"), encoding="utf-8"))
            self.atlas = {c["name"]: c for c in lay["cells"]}

    def path(self, name, m):
        return os.path.join(self.dir, name, f"{name}_{m}.png")


def _img(nt, path, color, interp="Smart", ext="REPEAT"):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(path, check_existing=True)
    if not color:
        n.image.colorspace_settings.name = "Non-Color"
    n.interpolation = interp
    n.extension = ext
    return n


def _math(nt, op, a=None, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def _mix(nt, kind, fac, a, b, blend="MIX"):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = kind
    n.blend_type = blend
    for sock, v in ((n.inputs["Factor"], fac), (n.inputs[6 if kind == "RGBA" else 2], a), (n.inputs[7 if kind == "RGBA" else 3], b)):
        if isinstance(v, (int, float)):
            sock.default_value = v
        elif isinstance(v, tuple):
            sock.default_value = v
        else:
            nt.links.new(v, sock)
    return n.outputs[2 if kind == "RGBA" else 0]


def _noise(nt, vec, scale, detail=4.0, rough=0.55):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    nt.links.new(vec, n.inputs["Vector"])
    return n.outputs["Fac"]


def _uv_scaled(nt, uv_name, scale, rot=0.0, offset=(0.0, 0.0)):
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = uv_name
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, 1.0)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rot)
    mp.inputs["Location"].default_value = (offset[0], offset[1], 0.0)
    nt.links.new(uv.outputs["UV"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def _wetness(nt, pos, height, strength=1.0):
    """World-space puddle mask: broad noise + the mesh's 'wet_bias' attribute
    (gutters, sag points of the road profile) + the texture's own low spots."""
    big = _noise(nt, pos, 0.11, 3.0, 0.5)
    fine = _noise(nt, pos, 0.9, 2.0, 0.5)
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "wet_bias"
    v = _math(nt, "ADD", big, _math(nt, "MULTIPLY", attr.outputs["Fac"], 0.32))
    v = _math(nt, "ADD", v, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", fine, 0.5), 0.08))
    v = _math(nt, "ADD", v, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", 0.5, height), 0.9))
    lo = 0.545 - 0.1 * (strength - 1.0)
    w = nt.nodes.new("ShaderNodeMapRange")
    w.inputs["From Min"].default_value = lo
    w.inputs["From Max"].default_value = lo + 0.05
    nt.links.new(v, w.inputs["Value"])
    damp = nt.nodes.new("ShaderNodeMapRange")
    damp.inputs["From Min"].default_value = lo - 0.14
    damp.inputs["From Max"].default_value = lo
    nt.links.new(v, damp.inputs["Value"])
    return w.outputs["Result"], damp.outputs["Result"]


def surface_material(name, tex, tile, uv="UVMap", tile_scale=1.0, anti_tile=True, wet=1.0, macro=0.22, bump=0.35, box=False):
    """Shared tileable surface: Pigment maps through `uv` (metres / tile_scale),
    a second rotated sample blended by world noise (breaks repetition), a
    macro tint / roughness variation from world-space noise, and puddles."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    L = nt.links.new

    def sample(vec, rot_tag):
        c = _img(nt, tex.path(tile, "BaseColor"), True)
        r = _img(nt, tex.path(tile, "Roughness"), False)
        h = _img(nt, tex.path(tile, "Height"), False)
        for n in (c, r, h):
            if box:
                n.projection = "BOX"
                n.projection_blend = 0.25
            L(vec, n.inputs["Vector"])
        return c.outputs["Color"], r.outputs["Color"], h.outputs["Color"]

    if box:
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1.0 / tile_scale,) * 3
        L(pos, mp.inputs["Vector"])
        v1 = mp.outputs["Vector"]
    else:
        v1 = _uv_scaled(nt, uv, 1.0 / tile_scale)
    col, rough, height = sample(v1, "a")
    if anti_tile and not box:
        v2 = _uv_scaled(nt, uv, 1.0 / tile_scale, rot=math.radians(37.0), offset=(0.31, 0.57))
        c2, r2, h2 = sample(v2, "b")
        f = nt.nodes.new("ShaderNodeMapRange")
        f.inputs["From Min"].default_value = 0.42
        f.inputs["From Max"].default_value = 0.58
        L(_noise(nt, pos, 0.07, 2.0), f.inputs["Value"])
        k = f.outputs["Result"]
        col = _mix(nt, "RGBA", k, col, c2)
        rough = _mix(nt, "FLOAT", k, _math(nt, "MULTIPLY", rough, 1.0), _math(nt, "MULTIPLY", r2, 1.0))
        height = _mix(nt, "FLOAT", k, _math(nt, "MULTIPLY", height, 1.0), _math(nt, "MULTIPLY", h2, 1.0))
    else:
        rough = _math(nt, "MULTIPLY", rough, 1.0)
        height = _math(nt, "MULTIPLY", height, 1.0)
    # macro variation: tone and roughness drift over tens of metres
    mv = _noise(nt, pos, 0.045, 3.0, 0.6)
    tone = nt.nodes.new("ShaderNodeMapRange")
    tone.inputs["To Min"].default_value = 1.0 - macro
    tone.inputs["To Max"].default_value = 1.0 + macro
    L(mv, tone.inputs["Value"])
    col = _mix(nt, "RGBA", 1.0, col, tone.outputs["Result"], "MULTIPLY")
    rough = _math(nt, "ADD", rough, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", mv, 0.5), 0.25), clamp=True)
    # wetness
    if wet > 0:
        wmask, damp = _wetness(nt, pos, height, wet)
        col = _mix(nt, "RGBA", _math(nt, "MULTIPLY", damp, 0.35), col, (0.0, 0.0, 0.0, 1.0))
        col = _mix(nt, "RGBA", wmask, col, _mix(nt, "RGBA", 1.0, col, (0.45, 0.45, 0.47, 1.0), "MULTIPLY"))
        rough = _mix(nt, "FLOAT", _math(nt, "MULTIPLY", damp, 0.4), rough, 0.25)
        rough = _mix(nt, "FLOAT", wmask, rough, 0.03)
        bstr = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", 1.0, wmask), bump)
    else:
        bstr = bump
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Distance"].default_value = 0.01 * tile_scale / 4.0
    if isinstance(bstr, float):
        bmp.inputs["Strength"].default_value = bstr
    else:
        L(bstr, bmp.inputs["Strength"])
    L(height, bmp.inputs["Height"])
    L(col, bsdf.inputs["Base Color"])
    L(rough, bsdf.inputs["Roughness"])
    L(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    L(bsdf.outputs[0], out.inputs[0])
    return m


def trim_material(tex):
    """The trim sheet: UVs already address the strips (U wraps every 2 m)."""
    m = surface_material("RoadTrim", tex, "trim", tile_scale=1.0, anti_tile=False, wet=0.8, macro=0.15, bump=0.4)
    nt = m.node_tree
    # the normal map carries the curb joints and chips crisply; combine with the bump
    nm = _img(nt, tex.path("trim", "Normal_OpenGL"), False)
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "UVMap"
    nt.links.new(uvn.outputs["UV"], nm.inputs["Vector"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.uv_map = "UVMap"
    nmap.inputs["Strength"].default_value = 0.8
    nt.links.new(nm.outputs["Color"], nmap.inputs["Color"])
    bmp = next(n for n in nt.nodes if n.type == "BUMP")
    nt.links.new(nmap.outputs["Normal"], bmp.inputs["Normal"])
    met = _img(nt, tex.path("trim", "Metallic"), False)
    nt.links.new(uvn.outputs["UV"], met.inputs["Vector"])
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    nt.links.new(met.outputs["Color"], bsdf.inputs["Metallic"])
    return m


def decal_atlas_material(tex):
    name = "RoadDecals"
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    L = nt.links.new
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    c = _img(nt, tex.path("atlas", "BaseColorAlpha"), True, ext="CLIP")
    r = _img(nt, tex.path("atlas", "Roughness"), False, ext="CLIP")
    h = _img(nt, tex.path("atlas", "Height"), False, ext="CLIP")
    me = _img(nt, tex.path("atlas", "Metallic"), False, ext="CLIP")
    nrm = _img(nt, tex.path("atlas", "Normal_OpenGL"), False, ext="CLIP")
    for n in (c, r, h, me, nrm):
        L(uv.outputs["UV"], n.inputs["Vector"])
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    wmask, damp = _wetness(nt, geo.outputs["Position"], h.outputs["Color"], 1.0)
    col = _mix(nt, "RGBA", wmask, c.outputs["Color"], _mix(nt, "RGBA", 1.0, c.outputs["Color"], (0.55, 0.55, 0.57, 1.0), "MULTIPLY"))
    rough = _mix(nt, "FLOAT", wmask, _math(nt, "MULTIPLY", r.outputs["Color"], 1.0), 0.03)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.uv_map = "UVMap"
    nmap.inputs["Strength"].default_value = 1.0
    L(nrm.outputs["Color"], nmap.inputs["Color"])
    L(col, bsdf.inputs["Base Color"])
    L(rough, bsdf.inputs["Roughness"])
    L(me.outputs["Color"], bsdf.inputs["Metallic"])
    L(c.outputs["Alpha"], bsdf.inputs["Alpha"])
    L(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    L(bsdf.outputs[0], out.inputs[0])
    try:
        m.surface_render_method = "BLENDED"
    except Exception:
        pass
    return m


def road_materials(tex, fallback):
    """[asphalt, trim, paving, concrete] shared by every run and junction."""
    if not tex.ok:
        return [fallback["asphalt"], fallback["curb"], fallback["walk"], fallback["concrete"]]
    return [
        surface_material("RoadAsphalt", tex, "asphalt", tile_scale=ASPHALT_TILE, wet=1.0, macro=0.25, bump=0.45),
        trim_material(tex),
        surface_material("RoadPaving", tex, "paving", tile_scale=PAVING_TILE, wet=0.6, macro=0.18, bump=0.5),
        surface_material("RoadConcrete", tex, "concrete", tile_scale=2.0, box=True, wet=0.0, macro=0.2, bump=0.3),
    ]


# ---------------------------------------------------------------- cross-section builder


class SectionBuilder:
    """Builds the curb / gutter / sidewalk strips between rails (point lists
    sampled at offsets d from the curb line) into one bmesh with UVs and a
    'wet_bias' attribute."""

    def __init__(self, tex):
        self.tex = tex
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.wet = self.bm.verts.layers.float.new("wet_bias")

    def vert(self, p, wet=0.0):
        v = self.bm.verts.new(p)
        v[self.wet] = wet
        return v

    def quad(self, vs, uvs, mat, want_up=None):
        if want_up is not None:
            # Newell normal; reverse the winding (with its UVs) to face want_up
            n = Vector((0, 0, 0))
            for k in range(len(vs)):
                a, c = vs[k].co, vs[(k + 1) % len(vs)].co
                n += Vector(((a.y - c.y) * (a.z + c.z), (a.z - c.z) * (a.x + c.x), (a.x - c.x) * (a.y + c.y)))
            if n.dot(want_up) < 0:
                vs, uvs = vs[::-1], uvs[::-1]
        try:
            f = self.bm.faces.new(vs)
        except ValueError:
            return None
        f.material_index = mat
        for lp, uv in zip(f.loops, uvs):
            lp[self.uv].uv = uv
        return f

    def trim_v(self, strip, t):
        """Blender V of fraction t (0 = road side / bottom) across a trim strip."""
        if not self.tex.trim:
            return t
        u0, v0, u1, v1 = self.tex.trim[strip]
        return v0 + (v1 - v0) * t

    def side(self, rails, along, base_z, outward, wet_gutter=0.6):
        """rails: {d: [(x, y), ...]} (same count), along: [metres] per sample,
        base_z: [z] per sample (path level), outward: [(x, y)] unit vectors
        towards the sidewalk. Builds gutter .. skirt."""
        n = len(along)
        Z = lambda i, dz: base_z[i] + dz
        P = lambda d, i, dz: Vector((rails[d][i][0], rails[d][i][1], Z(i, dz)))
        up = Vector((0, 0, 1))
        U = [a / TILE_ALONG for a in along]
        for i in range(n - 1):
            j = i + 1
            ow = Vector((outward[i][0], outward[i][1], 0.0))

            def strip(d0, z0, d1, z1, name, mat, want, w0=0.0, w1=0.0, t0=0.0, t1=1.0):
                vs = [self.vert(P(d0, i, z0), w0), self.vert(P(d0, j, z0), w0), self.vert(P(d1, j, z1), w1), self.vert(P(d1, i, z1), w1)]
                if mat == MAT_TRIM:
                    uvs = [(U[i], self.trim_v(name, t0)), (U[j], self.trim_v(name, t0)), (U[j], self.trim_v(name, t1)), (U[i], self.trim_v(name, t1))]
                else:
                    uvs = [(along[i], d0 - EDGE_W), (along[j], d0 - EDGE_W), (along[j], d1 - EDGE_W), (along[i], d1 - EDGE_W)]
                self.quad(vs, uvs, mat, want)

            strip(-GUTTER, ROAD_Z, 0.0, ROAD_Z, "Gutter", MAT_TRIM, up, wet_gutter * 0.6, wet_gutter)
            strip(0.0, ROAD_Z - 0.01, 0.0, CURB_Z, "Curb face", MAT_TRIM, -ow)
            strip(0.0, CURB_Z, CURB_W, CURB_Z, "Curb top", MAT_TRIM, up)
            strip(CURB_W, CURB_Z, CURB_W, WALK_Z - 0.005, "Curb face", MAT_TRIM, ow, t0=0.9, t1=1.0)
            strip(CURB_W, WALK_Z, EDGE_W, WALK_Z, "Walk edge", MAT_TRIM, up)
            strip(EDGE_W, WALK_Z, WALK_OUT, WALK_Z, None, MAT_PAVING, up)
            strip(WALK_OUT, WALK_Z, WALK_OUT, -1.0, None, MAT_CONCRETE, ow)

    def finish(self, name, mats):
        me = bpy.data.meshes.get(name)
        if me is not None:
            bpy.data.meshes.remove(me)
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in mats:
            me.materials.append(m)
        for p in me.polygons:
            p.use_smooth = False
        me.update()
        return me


def along_scale(length):
    """Scale arc length so a stretch holds a whole number of 2 m tiles."""
    n = max(1, round(length / TILE_ALONG))
    return n * TILE_ALONG / max(length, 1e-6)


def build_run(path, name, tex, mats):
    """A road run along `path` (blender_town.Path): asphalt across (world UVs),
    both sides' gutter / curb / sidewalk strips (along-path UVs)."""
    L = path.length
    n = max(2, int(math.ceil(L / 0.5)) + 1)
    s = np.linspace(0.0, L, n)
    pos, t = path.at_many(s)
    nrm = np.stack([-t[:, 1], t[:, 0]], axis=1)          # left
    k = along_scale(L)
    along = (s * k).tolist()
    zs = pos[:, 2].tolist()
    # sag points of the profile collect water
    sag = np.zeros(n)
    dz = np.diff(pos[:, 2])
    for i in range(1, n - 1):
        if dz[i - 1] < -1e-4 and dz[i] > 1e-4:
            sag = np.maximum(sag, np.exp(-((s - s[i]) / 7.0) ** 2))
    b = SectionBuilder(tex)
    # asphalt: rails across the carriageway
    ys = [-3.6, -2.7, -1.8, -0.9, 0.0, 0.9, 1.8, 2.7, 3.6]
    grid = []
    for y in ys:
        gut = smoothstep(2.4, 3.6, abs(y)) * 0.8
        grid.append([b.vert((pos[i, 0] + nrm[i, 0] * y, pos[i, 1] + nrm[i, 1] * y, zs[i] + ROAD_Z), min(1.0, gut + sag[i] * 0.9)) for i in range(n)])
    for a in range(len(ys) - 1):
        for i in range(n - 1):
            vs = [grid[a][i], grid[a][i + 1], grid[a + 1][i + 1], grid[a + 1][i]]
            b.quad(vs, [(v.co.x, v.co.y) for v in vs], MAT_ASPHALT, Vector((0, 0, 1)))
    for sgn in (1, -1):
        offs = [-GUTTER, 0.0, CURB_W, EDGE_W, WALK_OUT]
        rails = {d: [(pos[i, 0] + nrm[i, 0] * sgn * (ROAD_HALF + d), pos[i, 1] + nrm[i, 1] * sgn * (ROAD_HALF + d)) for i in range(n)] for d in offs}
        outward = [(nrm[i, 0] * sgn, nrm[i, 1] * sgn) for i in range(n)]
        b.side(rails, along, zs, outward)
    return b.finish(name, mats)


def build_junction(j, name, tex, mats, corner_line):
    """Junction in its local frame (object at (pos, z)). Asphalt: one polygon
    through every corner's gutter line, gridded, world-planar UVs. Corners:
    the same strips as the runs, along coordinate from 0 at each arm mouth."""
    b = SectionBuilder(tex)
    off = j.pos
    ring = []
    for c in j.corners:
        ring += corner_line(c, -GUTTER)
    clean = []
    for p in ring:
        if not clean or (p - clean[-1]).length > 1e-3:
            clean.append(p)
    if (clean[0] - clean[-1]).length < 1e-3:
        clean.pop()
    # asphalt polygon, then grid it so the wetness attribute and shading have vertices inside
    bm2 = bmesh.new()
    rv = [bm2.verts.new((p.x, p.y, ROAD_Z)) for p in clean]
    bm2.faces.new(rv)
    bmesh.ops.triangulate(bm2, faces=bm2.faces[:], quad_method="BEAUTY", ngon_method="BEAUTY")
    for _ in range(3):
        long_edges = [e for e in bm2.edges if e.calc_length() > 1.6]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm2, edges=long_edges, cuts=1, use_grid_fill=False)
        bmesh.ops.triangulate(bm2, faces=[f for f in bm2.faces if len(f.verts) > 3])
    bmesh.ops.beautify_fill(bm2, faces=bm2.faces[:], edges=bm2.edges[:])
    ring2 = [Vector((p.x, p.y)) for p in clean]

    def edge_dist(q):
        best = 1e9
        for a, c in zip(ring2, ring2[1:] + ring2[:1]):
            ab = c - a
            tt = max(0.0, min(1.0, (q - a).dot(ab) / max(ab.length_squared, 1e-9)))
            best = min(best, (a + ab * tt - q).length)
        return best

    vmap = {}
    for v in bm2.verts:
        q = v.co.to_2d()
        vmap[v] = b.vert((v.co.x, v.co.y, ROAD_Z), (1.0 - smoothstep(0.0, 1.2, edge_dist(q))) * 0.8)
    for f in bm2.faces:
        vs = [vmap[v] for v in f.verts]
        b.quad(vs, [(v.co.x + off.x, v.co.y + off.y) for v in vs], MAT_ASPHALT, Vector((0, 0, 1)))
    bm2.free()
    # corners
    for c in j.corners:
        offs = [-GUTTER, 0.0, CURB_W, EDGE_W, WALK_OUT]
        rails = {d: [(p.x, p.y) for p in corner_line(c, d)] for d in offs}
        ref = rails[EDGE_W]
        acc = [0.0]
        for p, q in zip(ref, ref[1:]):
            acc.append(acc[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
        k = along_scale(acc[-1])
        along = [a * k for a in acc]
        outward = []
        for i in range(len(ref)):
            o = Vector(rails[WALK_OUT][i]) - Vector(rails[0.0][i])
            outward.append(tuple(o.normalized()))
        b.side(rails, along, [0.0] * len(ref), outward)
    return b.finish(name, mats)


# ---------------------------------------------------------------- decals


class DecalBuilder:
    """Road decals as quads that follow the road surface, a few mm above it,
    textured from the Pigment atlas (BaseColor + alpha, roughness, normal)."""

    LAYER = {"crack": 0, "patch": 1, "oil": 2, "skid": 3, "line": 5, "arrow": 5, "zebra": 5, "stop": 5, "manhole": 7, "drain": 7}

    def __init__(self, tex):
        self.tex = tex
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.count = {}

    def cell_uv(self, cell, a, bb):
        u0, v0, u1, v1 = self.tex.atlas[cell]["uv_gl"]
        return (u0 + (u1 - u0) * a, v0 + (v1 - v0) * bb)

    def quad_grid(self, cell, kind, to_world, w, h, step=0.5):
        """to_world(x, y) -> Vector: x across (image right), y along (image up),
        both in metres from the decal centre."""
        nx = max(1, int(math.ceil(w / step)))
        ny = max(1, int(math.ceil(h / step)))
        lift = 0.006 + 0.0008 * self.LAYER.get(kind, 4)
        grid = []
        for iy in range(ny + 1):
            row = []
            for ix in range(nx + 1):
                a, bb = ix / nx, iy / ny
                p = to_world((a - 0.5) * w, (bb - 0.5) * h)
                row.append((self.bm.verts.new((p.x, p.y, p.z + lift)), (a, bb)))
            grid.append(row)
        for iy in range(ny):
            for ix in range(nx):
                q = [grid[iy][ix], grid[iy][ix + 1], grid[iy + 1][ix + 1], grid[iy + 1][ix]]
                f = self.bm.faces.new([v for v, _ in q])
                for lp, (_, ab) in zip(f.loops, q):
                    lp[self.uv].uv = self.cell_uv(cell, *ab)
        self.count[kind] = self.count.get(kind, 0) + 1

    def on_path(self, path, cell, kind, s, y, w, h, rot=0.0, flip=False):
        """Decal centred at arc length s, lateral y (left +), its image up along
        +s (or -s with flip), rotated by rot (radians) on the road plane."""
        ca, sa = math.cos(rot), math.sin(rot)
        sg = -1.0 if flip else 1.0

        def to_world(x, yy):
            # image right = -left = right of travel; up = along
            ls = (yy * ca - x * sa) * sg
            ly = (-(x * ca + yy * sa)) * sg
            p, t = path.at(min(max(s + ls, 0.0), path.length))
            n = Vector((-t.y, t.x))
            q = p.to_2d() + n * (y + ly)
            return Vector((q.x, q.y, p.z + ROAD_Z))
        self.quad_grid(cell, kind, to_world, w, h)

    def flat(self, origin, z, cell, kind, centre, fwd, w, h):
        """Decal on a flat junction: centre (2D, local), fwd = image up (2D unit)."""
        right = Vector((fwd.y, -fwd.x))

        def to_world(x, yy):
            q = origin + centre + right * x + fwd * yy
            return Vector((q.x, q.y, z + ROAD_Z))
        self.quad_grid(cell, kind, to_world, w, h)

    def finish(self, name, mat):
        me = bpy.data.meshes.get(name)
        if me is not None:
            bpy.data.meshes.remove(me)
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        me.materials.append(mat)
        return me


def scatter_run_decals(db, path, ri, rng, ends):
    """Markings and wear along one run. ends = (junction at start?, junction at end?)."""
    L = path.length
    # edge lines: 4 m pieces, random wear variant per piece (never a fixed period)
    for y in (3.3, -3.3):
        s = 0.3
        while s < L - 0.3:
            seg = min(4.0, L - 0.3 - s)
            if seg > 0.2:
                db.on_path(path, rng.choice(["edge_line_a", "edge_line_b", "edge_line_c"]), "line", s + seg / 2, y, 0.15, seg, flip=rng.random() < 0.5)
            s += seg
    # centre dashes: 3 m dash, 6 m gap
    s = 4.0
    while s < L - 4.0:
        db.on_path(path, "lane_dash", "line", s + 1.5, 0.0, 0.15, 3.0, flip=rng.random() < 0.5)
        s += 9.0
    # direction arrows in the incoming (left-hand traffic) lane before junctions
    if ends[1] and L > 30:
        db.on_path(path, rng.choice(["arrow_straight", "arrow_left"]), "arrow", L - 16.0, 1.8, 1.0, 5.0)
    if ends[0] and L > 30:
        db.on_path(path, rng.choice(["arrow_straight", "arrow_left"]), "arrow", 16.0, -1.8, 1.0, 5.0, flip=True)
    # wear: cracks, patches, oil, skids, manholes, gutter drains
    def place(kind, cells, per_m, ys, size, rot_jit=math.pi):
        n = max(0, int(round(L * per_m * rng.uniform(0.7, 1.3))))
        for _ in range(n):
            cell = rng.choice(cells)
            sz = db.tex.atlas[cell]["size_m"]
            k = rng.uniform(*size)
            s = rng.uniform(2.0, L - 2.0)
            y = rng.uniform(*ys)
            db.on_path(path, cell, kind, s, y, sz[0] * k, sz[1] * k, rot=rng.uniform(-rot_jit, rot_jit))
    place("crack", ["crack_a", "crack_b", "crack_c"], 1 / 11.0, (-2.6, 2.6), (0.8, 1.4))
    place("patch", ["patch_a", "patch_b"], 1 / 32.0, (-2.2, 2.2), (0.8, 1.3), rot_jit=0.08)
    place("oil", ["oil_a", "oil_b"], 1 / 16.0, (-2.4, 2.4), (0.7, 1.3))
    place("skid", ["skid"], 1 / 70.0, (-2.0, 2.0), (0.9, 1.2), rot_jit=0.15)
    s = rng.uniform(8, 30)
    while s < L - 6:
        db.on_path(path, "manhole", "manhole", s, rng.choice([0.0, 1.7, -1.7]), 0.9, 0.9, rot=rng.uniform(0, 6.3))
        s += rng.uniform(32, 58)
    for y in (3.82, -3.82):
        s = rng.uniform(5, 20)
        while s < L - 4:
            db.on_path(path, "drain", "drain", s, y, 0.36, 0.62, rot=(0 if y > 0 else math.pi))
            s += rng.uniform(18, 34)


def junction_decals(db, j, rng):
    """Zebra crossings and stop lines at every arm mouth, wear in the middle."""
    o = j.pos
    for i, d in enumerate(j.dirs):
        nrm = Vector((-d.y, d.x))
        t0, t1 = j.L[i] - 4.2, j.L[i] - 1.2
        for k in range(-3, 4):
            db.flat(o, j.z, "zebra_bar", "zebra", d * ((t0 + t1) / 2) + nrm * (k * 1.0), d if rng.random() < 0.5 else -d, 0.5, 3.0)
        # stop line across the incoming (left-hand traffic) lane
        db.flat(o, j.z, "stop_line", "stop", d * (j.L[i] - 4.8) + nrm * -1.75, d, 3.5, 0.4)
    r = max(3.0, min(j.L) - 6.0)
    for _ in range(rng.randint(2, 4)):
        a = rng.uniform(0, 2 * math.pi)
        c = Vector((math.cos(a), math.sin(a))) * rng.uniform(0, r)
        cell = rng.choice(["crack_a", "crack_b", "crack_c", "oil_a", "oil_b", "patch_a"])
        sz = db.tex.atlas[cell]["size_m"]
        kind = "crack" if cell.startswith("crack") else ("oil" if cell.startswith("oil") else "patch")
        f = rng.uniform(0, 2 * math.pi)
        db.flat(o, j.z, cell, kind, c, Vector((math.cos(f), math.sin(f))), sz[0], sz[1])
    if rng.random() < 0.8:
        a = rng.uniform(0, 2 * math.pi)
        db.flat(o, j.z, "manhole", "manhole", Vector((math.cos(a), math.sin(a))) * rng.uniform(0.5, 2.5), Vector((1, 0)), 0.9, 0.9)
