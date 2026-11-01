"""Procedural meshes and materials for the world (Blender 5.2): towers,
warehouses, containers, gantry cranes, light masts, signal poles, trees,
terrain, water, facades. Every mesh is built once per key and shared by its
instances (the export writes one glb per key).

UVs are in metres (u along the wall, v up), so the 8 x 8 m Pigment facade
and 4 x 4 m corrugated tiles map at true scale.
"""
import math
import os
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

# window layout of the Pigment facade tiles (tools/town_textures.py FACADE_WINDOW)
BAY, STOREY, SILL = 2.0, 4.0, 0.55
WIN = {"curtain": (1.86, 3.4), "punched": (1.5, 2.6)}


# ---------------------------------------------------------------- node helpers


def _nodes(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m, nt, bsdf


def _val(nt, v):
    n = nt.nodes.new("ShaderNodeValue")
    n.outputs[0].default_value = v
    return n.outputs[0]


def _math(nt, op, a, b=None, clamp=False):
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


def _mix(nt, fac, a, b, blend="MIX", kind="RGBA"):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = kind
    n.blend_type = blend
    sa, sb = (6, 7) if kind == "RGBA" else (2, 3)
    for sock, v in ((n.inputs["Factor"], fac), (n.inputs[sa], a), (n.inputs[sb], b)):
        if isinstance(v, (int, float, tuple)):
            sock.default_value = v
        else:
            nt.links.new(v, sock)
    return n.outputs[2 if kind == "RGBA" else 0]


def _img(nt, path, color, vec=None, proj=None):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(path, check_existing=True)
    if not color:
        n.image.colorspace_settings.name = "Non-Color"
    if proj:
        n.projection = "BOX"
        n.projection_blend = 0.3
    if vec is not None:
        nt.links.new(vec, n.inputs["Vector"])
    return n


def _sep(nt, vec):
    n = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(vec, n.inputs[0])
    return n.outputs


def _smooth(nt, a, b, x):
    n = nt.nodes.new("ShaderNodeMapRange")
    n.interpolation_type = "SMOOTHSTEP"
    n.inputs["From Min"].default_value = a
    n.inputs["From Max"].default_value = b
    nt.links.new(x, n.inputs["Value"])
    return n.outputs["Result"]


def _noise(nt, vec, scale, detail=4.0):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    nt.links.new(vec, n.inputs["Vector"])
    return n.outputs["Fac"]


def _scaled(nt, vec, s):
    mp = nt.nodes.new("ShaderNodeVectorMath")
    mp.operation = "SCALE"
    nt.links.new(vec, mp.inputs[0])
    mp.inputs["Scale"].default_value = s if isinstance(s, (int, float)) else 1.0
    if not isinstance(s, (int, float)):
        mp.operation = "MULTIPLY"
        mp.inputs[1].default_value = s
    return mp.outputs[0]


def tex_dir(root, name):
    d = os.path.join(root, "scenes", "town", "textures", "world", name)
    return d if os.path.isfile(os.path.join(d, f"{name}_BaseColor.png")) else None


# ---------------------------------------------------------------- terrain / water


def terrain_material(root):
    """Rock / grass / dirt / sand Pigment tiles blended by slope, height and
    noise; city lots ('urban' attribute) get the road concrete and paving."""
    m, nt, bsdf = _nodes("WorldTerrain")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    nz = _sep(nt, geo.outputs["Normal"])[2]
    z = _sep(nt, pos)[2]
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "urban"
    urban = attr.outputs["Fac"]
    have = all(tex_dir(root, n) for n in ("rock", "grass", "dirt", "sand"))
    roads = os.path.join(root, "scenes", "town", "textures", "roads")

    def tile(name, scale, box=False, d=None):
        d = d or tex_dir(root, name)
        v = _scaled(nt, pos, 1.0 / scale)
        c = _img(nt, os.path.join(d, f"{name}_BaseColor.png"), True, v, box)
        r = _img(nt, os.path.join(d, f"{name}_Roughness.png"), False, v, box)
        h = _img(nt, os.path.join(d, f"{name}_Height.png"), False, v, box)
        return c.outputs["Color"], _math(nt, "MULTIPLY", r.outputs["Color"], 1.0), _math(nt, "MULTIPLY", h.outputs["Color"], 1.0)
    if have:
        g = tile("grass", 4.0)
        g2 = tile("grass", 9.7)
        d = tile("dirt", 4.0)
        r = tile("rock", 6.0, box=True)
        s = tile("sand", 4.0)
    else:
        def flat(col, rough):
            return (col + (1.0,), rough, 0.5)
        g, g2, d, r, s = flat((0.08, 0.11, 0.04), 0.9), flat((0.1, 0.13, 0.05), 0.9), flat((0.13, 0.1, 0.07), 0.9), flat((0.2, 0.19, 0.18), 0.85), flat((0.4, 0.35, 0.27), 0.95)
    if os.path.isfile(os.path.join(roads, "concrete", "concrete_BaseColor.png")):
        u = tile("concrete", 2.0, box=True, d=os.path.join(roads, "concrete"))
    else:
        u = ((0.2, 0.2, 0.2, 1.0), 0.85, 0.5)
    big = _noise(nt, pos, 0.012, 3.0)
    mid = _noise(nt, pos, 0.05, 4.0)

    def blend(f, a, b):
        return tuple(_mix(nt, f, x, y, kind="RGBA" if k == 0 else "FLOAT") for k, (x, y) in enumerate(zip(a, b)))
    base = blend(_smooth(nt, 0.4, 0.6, big), g, g2)
    base = blend(_smooth(nt, 0.55, 0.68, mid), base, d)
    # dirt and scree under the rock, rock on slopes > ~35 deg and high up
    steep = _math(nt, "SUBTRACT", 1.0, nz)
    base = blend(_smooth(nt, 0.12, 0.2, steep), base, d)
    rockf = _math(nt, "MAXIMUM", _smooth(nt, 0.2, 0.3, _math(nt, "ADD", steep, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", mid, 0.5), 0.12))),
                  _smooth(nt, 210.0, 250.0, _math(nt, "ADD", z, _math(nt, "MULTIPLY", big, 40.0))))
    base = blend(rockf, base, r)
    # sand on low natural shores
    sandf = _math(nt, "MULTIPLY", _smooth(nt, 2.6, 1.4, _math(nt, "ADD", z, _math(nt, "MULTIPLY", mid, 0.8))), _math(nt, "SUBTRACT", 1.0, urban))
    base = blend(sandf, base, s)
    base = blend(_smooth(nt, 0.3, 0.6, urban), base, u)
    # wet below the waterline
    wet = _smooth(nt, 0.4, -0.3, z)
    col = _mix(nt, wet, base[0], _mix(nt, 1.0, base[0], (0.35, 0.38, 0.38, 1.0), "MULTIPLY"))
    rough = _mix(nt, wet, base[1], 0.15, kind="FLOAT")
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.03
    if not isinstance(base[2], float):
        nt.links.new(base[2], bump.inputs["Height"])
    nt.links.new(col, bsdf.inputs["Base Color"])
    if isinstance(rough, float):
        bsdf.inputs["Roughness"].default_value = rough
    else:
        nt.links.new(rough, bsdf.inputs["Roughness"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def water_material():
    """Bay water: dark, glossy, two scales of wind waves and long swell in the
    normal, a little absorption tint; reflections do the rest."""
    m, nt, bsdf = _nodes("WorldWater")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    bsdf.inputs["Base Color"].default_value = (0.004, 0.012, 0.016, 1)
    bsdf.inputs["Roughness"].default_value = 0.035
    bsdf.inputs["IOR"].default_value = 1.333
    bsdf.inputs["Specular IOR Level"].default_value = 0.6
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 0.012
    wave.inputs["Distortion"].default_value = 6.0
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(pos, wave.inputs["Vector"])
    n1 = _noise(nt, pos, 0.35, 6.0)
    n2 = _noise(nt, pos, 2.2, 3.0)
    h = _math(nt, "ADD", _math(nt, "MULTIPLY", wave.outputs["Fac"], 0.6), _math(nt, "ADD", n1, _math(nt, "MULTIPLY", n2, 0.25)))
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.2
    nt.links.new(h, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def terrain_chunk(name, H, x0, cell, ix0, iy0, per, step, urban=None):
    """Heightfield chunk: (per / step + 1)^2 vertices, every quad split along
    its (0,0)-(1,1) diagonal (terrain.Heightfield.sample_tri matches)."""
    sub = H[iy0:iy0 + per + 1:step, ix0:ix0 + per + 1:step]
    m = sub.shape[0]
    xs = x0 + (ix0 + np.arange(m) * step) * cell
    ys = x0 + (iy0 + np.arange(m) * step) * cell
    X, Y = np.meshgrid(xs, ys)
    V = np.stack([X.ravel(), Y.ravel(), sub.ravel()], 1).astype(np.float32)
    ii = np.arange(m * m).reshape(m, m)
    a, b, c, d = ii[:-1, :-1], ii[:-1, 1:], ii[1:, 1:], ii[1:, :-1]
    T = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V))
    me.vertices.foreach_set("co", V.ravel())
    me.loops.add(T.size)
    me.loops.foreach_set("vertex_index", T.ravel().astype(np.int32))
    me.polygons.add(len(T))
    me.polygons.foreach_set("loop_start", (np.arange(len(T)) * 3).astype(np.int32))
    me.update(calc_edges=True)
    me.polygons.foreach_set("use_smooth", np.ones(len(T), dtype=bool))
    if urban is not None:
        u = urban[iy0:iy0 + per + 1:step, ix0:ix0 + per + 1:step].astype(np.float32).ravel()
        at = me.attributes.new("urban", "FLOAT", "POINT")
        at.data.foreach_set("value", u)
    return me


# ---------------------------------------------------------------- facades / towers


def facade_material(root, style):
    """Pigment facade tile (8 x 8 m) in metre UVs + procedural night windows:
    every pane of the tile's 2 m x 4 m grid is lit or dark from a hash of its
    world cell and the object, in a few interior colours."""
    name = f"WorldFacade_{style}"
    if bpy.data.materials.get(name):
        return bpy.data.materials[name]
    m, nt, bsdf = _nodes(name)
    d = tex_dir(root, f"facade_{style}")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    # sheet z grows towards image row 0 (top), so flip v: the tile stands upright
    v8 = _scaled(nt, uv.outputs["UV"], (1.0 / 8.0, -1.0 / 8.0, 1.0))
    if d:
        n = f"facade_{style}"
        c = _img(nt, os.path.join(d, f"{n}_BaseColor.png"), True, v8)
        r = _img(nt, os.path.join(d, f"{n}_Roughness.png"), False, v8)
        mt = _img(nt, os.path.join(d, f"{n}_Metallic.png"), False, v8)
        nm = _img(nt, os.path.join(d, f"{n}_Normal_OpenGL.png"), False, v8)
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = 0.8
        nt.links.new(nm.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        nt.links.new(c.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
        nt.links.new(mt.outputs["Color"], bsdf.inputs["Metallic"])
    else:
        bsdf.inputs["Base Color"].default_value = (0.1, 0.11, 0.12, 1)
        bsdf.inputs["Roughness"].default_value = 0.3
    # window mask from the UV metres (same layout as the tile's glass decals)
    w, h = WIN["curtain"] if style.startswith("glass") else WIN["punched"]
    U = _sep(nt, uv.outputs["UV"])
    fu = _math(nt, "FRACT", _math(nt, "DIVIDE", U[0], BAY))
    fv = _math(nt, "FRACT", _math(nt, "DIVIDE", U[1], STOREY))
    inx = _math(nt, "LESS_THAN", _math(nt, "ABSOLUTE", _math(nt, "SUBTRACT", fu, 0.5)), w / BAY / 2)
    v0, v1 = SILL / STOREY, (SILL + h) / STOREY
    iny = _math(nt, "MULTIPLY", _math(nt, "GREATER_THAN", fv, v0), _math(nt, "LESS_THAN", fv, v1))
    win = _math(nt, "MULTIPLY", inx, iny)
    # per-window hash: cell indices + object random
    ci = _math(nt, "FLOOR", _math(nt, "DIVIDE", U[0], BAY))
    cj = _math(nt, "FLOOR", _math(nt, "DIVIDE", U[1], STOREY))
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(ci, comb.inputs[0])
    nt.links.new(cj, comb.inputs[1])
    nt.links.new(_math(nt, "MULTIPLY", oi.outputs["Random"], 100.0), comb.inputs[2])
    wn = nt.nodes.new("ShaderNodeTexWhiteNoise")
    wn.noise_dimensions = "3D"
    nt.links.new(comb.outputs[0], wn.inputs["Vector"])
    lit = _math(nt, "LESS_THAN", wn.outputs["Value"], 0.2 if style != "glass_dark" else 0.12)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (1.0, 0.62, 0.3, 1)
    els[1].position, els[1].color = 0.55, (1.0, 0.75, 0.5, 1)
    e3 = els.new(0.8)
    e3.color = (0.75, 0.9, 1.0, 1)
    e4 = els.new(0.94)
    e4.color = (0.35, 0.55, 1.0, 1)
    ramp.color_ramp.interpolation = "CONSTANT"
    nt.links.new(wn.outputs["Color"], ramp.inputs["Fac"]) if False else None
    sep2 = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(wn.outputs["Color"], sep2.inputs[0])
    nt.links.new(sep2.outputs[0], ramp.inputs["Fac"])
    strength = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", win, lit), _math(nt, "ADD", 0.2, _math(nt, "MULTIPLY", sep2.outputs[1], 0.9)))
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Emission Color"])
    nt.links.new(strength, bsdf.inputs["Emission Strength"])
    return m


def emissive(name, col, strength):
    m, nt, bsdf = _nodes(name)
    bsdf.inputs["Base Color"].default_value = (*col, 1)
    bsdf.inputs["Emission Color"].default_value = (*col, 1)
    bsdf.inputs["Emission Strength"].default_value = strength
    bsdf.inputs["Roughness"].default_value = 0.3
    return m


def painted(name, rough=0.45, metal=0.6, tex=None, scale=4.0):
    """Paint colour from the object's colour (per-instance variants), with an
    optional Pigment tile (corrugated) multiplied in, box-mapped in metres."""
    m, nt, bsdf = _nodes(name)
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    col = oi.outputs["Color"]
    if tex:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        v = _scaled(nt, tc.outputs["Object"], 1.0 / scale)
        n = os.path.basename(tex)
        c = _img(nt, os.path.join(tex, f"{n}_BaseColor.png"), True, v, True)
        r = _img(nt, os.path.join(tex, f"{n}_Roughness.png"), False, v, True)
        h = _img(nt, os.path.join(tex, f"{n}_Height.png"), False, v, True)
        col = _mix(nt, 1.0, col, _math(nt, "MULTIPLY", c.outputs["Color"], 1.4), "MULTIPLY")
        nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.6
        bump.inputs["Distance"].default_value = 0.02
        nt.links.new(h.outputs["Color"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        bsdf.inputs["Roughness"].default_value = rough
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Metallic"].default_value = metal
    return m


def cladding(name, tex=None, scale=4.0, colour=None, rust=0.6):
    """Corrugated sheet (the Pigment `corrugated` tile, box-mapped in metres) for big sheds:
    paint from the object colour (per-instance variants) or `colour`, weathered at the building
    scale where a 4 m tile can't: salt-faded patches, rust runs from the eaves and the
    fixings, and road grime splashed up the first metre and a half (object z)."""
    m, nt, bsdf = _nodes(name)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    ob = tc.outputs["Object"]
    if colour is None:
        col = nt.nodes.new("ShaderNodeObjectInfo").outputs["Color"]
    else:
        n = nt.nodes.new("ShaderNodeRGB")
        n.outputs[0].default_value = (*colour, 1)
        col = n.outputs[0]
    rough = _val(nt, 0.5)
    if tex:
        v = _scaled(nt, ob, 1.0 / scale)
        b = os.path.basename(tex)
        c = _img(nt, os.path.join(tex, f"{b}_BaseColor.png"), True, v, True)
        r = _img(nt, os.path.join(tex, f"{b}_Roughness.png"), False, v, True)
        h = _img(nt, os.path.join(tex, f"{b}_Height.png"), False, v, True)
        col = _mix(nt, 1.0, col, _math(nt, "MULTIPLY", c.outputs["Color"], 1.4), "MULTIPLY")
        rough = r.outputs["Color"]
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.6
        bump.inputs["Distance"].default_value = 0.02
        nt.links.new(h.outputs["Color"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    z = _sep(nt, ob)[2]
    # salt fade: big soft patches lighten and dull the paint
    fade = _smooth(nt, 0.45, 0.75, _noise(nt, _scaled(nt, ob, 0.12), 0.35, 3.0))
    col = _mix(nt, _math(nt, "MULTIPLY", fade, 0.35), col, (0.55, 0.53, 0.5, 1.0))
    # rust runs: noise stretched along z, strongest under the eaves, fading down the wall
    streak_v = _scaled(nt, ob, (1.6, 1.6, 0.08))
    streak = _smooth(nt, 0.55, 0.72, _noise(nt, streak_v, 3.0, 2.0))
    top = _smooth(nt, 1.0, 0.25, _math(nt, "DIVIDE", _math(nt, "SUBTRACT", _val(nt, 14.0), z), 14.0))
    run = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", streak, top), rust)
    col = _mix(nt, run, col, (0.22, 0.09, 0.04, 1.0))
    # road grime splashed up the walls
    grime = _math(nt, "MULTIPLY", _smooth(nt, 1.6, 0.0, z), _smooth(nt, 0.3, 0.7, _noise(nt, _scaled(nt, ob, 0.6), 2.0, 4.0)))
    col = _mix(nt, _math(nt, "MULTIPLY", grime, 0.8), col, (0.05, 0.045, 0.04, 1.0))
    nt.links.new(col, bsdf.inputs["Base Color"])
    nt.links.new(_mix(nt, _math(nt, "MAXIMUM", run, grime), rough, 0.85, kind="FLOAT") if not isinstance(rough, float) else rough,
                 bsdf.inputs["Roughness"])
    bsdf.inputs["Metallic"].default_value = 0.55
    return m


class Mesher:
    """bmesh helper: boxes and cylinders with metre UVs and material slots."""

    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")

    def quad(self, pts, mat, uvs=None):
        vs = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(vs)
        f.material_index = mat
        if uvs is None:
            # planar metre UVs: u along the first edge, v along z (or the second edge)
            a, b, d = Vector(pts[0]), Vector(pts[1]), Vector(pts[-1])
            eu = (b - a)
            ev = (d - a)
            uvs = [(0, 0), (eu.length, 0), (eu.length, ev.length), (0, ev.length)]
            o = Vector(pts[0])
            uvs = [((Vector(p) - o).dot(eu.normalized()), (Vector(p) - o).dot(ev.normalized())) for p in pts]
        for lp, uv in zip(f.loops, uvs):
            lp[self.uv].uv = uv
        return f

    def box(self, c, size, mat, rz=0.0, top=True, bottom=False, u0=0.0, mats=None):
        """Axis box centred at c (x, y, z-centre), walls with metre UVs that
        wrap around (u continues around the box), v = absolute height."""
        sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
        cs, sn = math.cos(rz), math.sin(rz)

        def P(x, y, z):
            return (c[0] + x * cs - y * sn, c[1] + x * sn + y * cs, c[2] + z)
        ring = [(-sx, -sy), (sx, -sy), (sx, sy), (-sx, sy)]
        u = u0
        z0, z1 = -sz, sz
        for k in range(4):
            (x0, y0), (x1, y1) = ring[k], ring[(k + 1) % 4]
            L = math.hypot(x1 - x0, y1 - y0)
            m = mats[k] if mats else mat
            self.quad([P(x0, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y0, z1)], m,
                      [(u, c[2] + z0), (u + L, c[2] + z0), (u + L, c[2] + z1), (u, c[2] + z1)])
            u += L
        if top:
            self.quad([P(x, y, z1) for x, y in ring], mat if mats is None else (mats[4] if len(mats) > 4 else mat))
        if bottom:
            self.quad([P(x, y, z0) for x, y in ring[::-1]], mat)

    def cyl(self, a, b, r, mat, seg=8, r2=None):
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        if L < 1e-6:
            return
        q = d.normalized().to_track_quat("Z", "Y")
        M = Matrix.Translation(a) @ q.to_matrix().to_4x4()
        r2 = r if r2 is None else r2
        ring0 = [M @ Vector((r * math.cos(2 * math.pi * k / seg), r * math.sin(2 * math.pi * k / seg), 0)) for k in range(seg)]
        ring1 = [M @ Vector((r2 * math.cos(2 * math.pi * k / seg), r2 * math.sin(2 * math.pi * k / seg), L)) for k in range(seg)]
        for k in range(seg):
            k2 = (k + 1) % seg
            u0, u1 = k * 2 * math.pi * r / seg, (k + 1) * 2 * math.pi * r / seg
            self.quad([ring0[k], ring0[k2], ring1[k2], ring1[k]], mat, [(u0, 0), (u1, 0), (u1, L), (u0, L)])

    def finish(self, name, mats):
        me = bpy.data.meshes.new(name)
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts[:], dist=1e-5)
        self.bm.to_mesh(me)
        self.bm.free()
        for mt in mats:
            me.materials.append(mt)
        return me


class Kit:
    """Procedural asset meshes by key, built on first use."""

    def __init__(self, root, world, M):
        self.root, self.world, self.M = root, world, M
        self.cache = {}
        self.towers = {t["mesh"]: t for t in world.get("towers", [])}
        self.story = os.path.join(root, "assets", "decals", "story")

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        me = None
        if key.startswith(("tower_", "landmark_")):
            me = self.tower(key, self.towers[key])
        elif key.startswith("warehouse_"):
            me = self.warehouse(key)
        elif key == "container":
            me = self.container()
        elif key == "crane_sts":
            me = self.crane()
        elif key == "light_mast":
            me = self.mast()
        elif key.startswith("signal_pole"):
            me = self.signal(key, 9.0 if key.endswith("long") else 5.0)
        elif key.startswith("tree_"):
            me = self.tree(key)
        self.cache[key] = me
        return me

    # -- towers: stacked setback tiers, crown
    def tower(self, key, spec):
        M = self.M
        b = Mesher()
        z = 0.0
        rng = random.Random(key)
        tiers = spec["tiers"]
        for k, (w, d, h) in enumerate(tiers):
            b.box((0, 0, z + h / 2), (w, d, h), 0, top=True, mats=[0, 0, 0, 0, 1])
            # a lit setback band at every tier top
            if k < len(tiers) - 1 or spec["crown"] == "halo":
                b.box((0, 0, z + h - 0.6), (w + 0.4, d + 0.4, 0.5), 2, top=False)
            z += h
        top = z
        w, d, _ = tiers[-1]
        crown = spec["crown"]
        if crown == "spire" or crown in ("hoshikawa", "meridian"):
            b.cyl((0, 0, top), (0, 0, top + (top * 0.18 if crown == "spire" else 30)), 1.6, 1, seg=10, r2=0.25)
            b.box((0, 0, top + 2), (w * 0.5, d * 0.5, 4), 1)
        if crown in ("billboard", "hoshikawa", "meridian"):
            # two billboard faces near the top (story decals), each on a real
            # billboard: a cabinet bolted to the facade and a frame round the face
            bw = min(w, d) * 0.9
            bh = bw * 0.5
            zc = top - bh / 2 - 2.0 if crown == "billboard" else top - bh / 2 - 6.0

            def billboard_cabinet(along_x, sgn, half, span):
                # along_x: the face runs along x (on a +-y facade at distance `half`)
                for c, sz in (((0, sgn * (half + 0.17), zc), (span + 0.3, 0.34, bh + 0.3)),          # cabinet
                              ((0, sgn * (half + 0.38), zc + bh / 2 + 0.07), (span + 0.3, 0.08, 0.14)),   # frame top
                              ((0, sgn * (half + 0.38), zc - bh / 2 - 0.07), (span + 0.3, 0.08, 0.14)),   # frame bottom
                              ((-(span / 2 + 0.08), sgn * (half + 0.38), zc), (0.14, 0.08, bh)),           # frame sides
                              (((span / 2 + 0.08), sgn * (half + 0.38), zc), (0.14, 0.08, bh))):
                    if along_x:
                        b.box(c, sz, 1, bottom=True)
                    else:
                        b.box((c[1], c[0], c[2]), (sz[1], sz[0], sz[2]), 1, bottom=True)
            for sgn in (1, -1):
                billboard_cabinet(True, sgn, d / 2, bw)
                y = sgn * (d / 2 + 0.35)
                pts = [(-bw / 2, y, zc - bh / 2), (bw / 2, y, zc - bh / 2), (bw / 2, y, zc + bh / 2), (-bw / 2, y, zc + bh / 2)]
                if sgn > 0:
                    pts = [pts[1], pts[0], pts[3], pts[2]]
                b.quad(pts, 3, [(0, 0), (1, 0), (1, 1), (0, 1)])
            if crown in ("hoshikawa", "meridian"):
                for sgn in (1, -1):
                    billboard_cabinet(False, sgn, w / 2, d * 0.9)
                    x = sgn * (w / 2 + 0.35)
                    bwy = d * 0.9
                    pts = [(x, -bwy / 2, zc - bh / 2), (x, bwy / 2, zc - bh / 2), (x, bwy / 2, zc + bh / 2), (x, -bwy / 2, zc + bh / 2)]
                    if sgn < 0:
                        pts = [pts[1], pts[0], pts[3], pts[2]]
                    b.quad(pts, 3, [(0, 0), (1, 0), (1, 1), (0, 1)])
        # rooftop clutter
        for _ in range(rng.randint(2, 5)):
            bx, by = rng.uniform(-w / 2 + 3, w / 2 - 3), rng.uniform(-d / 2 + 3, d / 2 - 3)
            b.box((bx, by, top + 1.2), (rng.uniform(2, 5), rng.uniform(2, 5), 2.4), 1)
        img = {"hoshikawa": "billboard_score", "meridian": "billboard_meridian"}.get(crown) or rng.choice(
            ["billboard_meridian", "billboard_dreamlink", "billboard_noctis", "billboard_jobs", "billboard_score", "billboard_defaced"])
        return b.finish(key, [M["facade_default"], M["roof"], M["band"], M["decal_fn"](os.path.join(self.story, img + ".png"))])

    def warehouse(self, key):
        """Port shed (key warehouse_<L>x<W>x<H>): long axis x, roll-up doors on both long
        sides, origin at the ground centre.  Concrete base course, corrugated cladding with
        corner flashings, a low gable roof with overhanging eaves, fascias, gutters and
        downpipes, ridge cap, roof vents and skylight strips; framed roll-up doors with slats,
        canopies, lamps and dock bumpers, personnel doors, gable louvres and a line's sign on
        both gables (story decals), and an UNPLUG tag on one wall."""
        L, W, H = [float(v) for v in key.split("_")[1].split("x")]
        M = self.M
        rng = random.Random(key)
        b = Mesher()
        CL, DOOR, LAMP, STEEL, BASE, ROOF, SKY, SIGN, TAG = range(9)
        rise = 1.6
        hw, hl = W / 2, L / 2
        b.box((0, 0, 0.55), (L + 0.12, W + 0.12, 1.1), BASE)                         # concrete base course
        b.box((0, 0, H / 2), (L, W, H), CL, top=False)
        for sx in (-1, 1):
            for sy in (-1, 1):
                b.box((sx * (hl - 0.05), sy * (hw - 0.05), H / 2 + 0.05), (0.22, 0.22, H - 0.9), STEEL, top=False)  # corner flashings
        # roof: two slopes with eaves (0.6 m along the sides, 0.4 m at the gables), soffits, fascias
        ox, oy, ft = 0.4, 0.6, 0.25
        zr = H + rise
        ze = H - (rise / hw) * oy
        for sgn in (1, -1):
            ridge = [(-hl - ox, 0, zr), (hl + ox, 0, zr)]
            eave = [(hl + ox, sgn * (hw + oy), ze), (-hl - ox, sgn * (hw + oy), ze)]
            pts = ridge + eave
            if sgn < 0:
                pts = [pts[1], pts[0], pts[3], pts[2]]
            b.quad(pts, ROOF)
            sof = [(-hl - ox, 0, zr - 0.12), (-hl - ox, sgn * (hw + oy), ze - 0.12), (hl + ox, sgn * (hw + oy), ze - 0.12), (hl + ox, 0, zr - 0.12)]
            if sgn < 0:
                sof = [sof[1], sof[0], sof[3], sof[2]]
            b.quad(sof, STEEL)
            y = sgn * (hw + oy)
            fas = [(-hl - ox, y, ze - ft), (hl + ox, y, ze - ft), (hl + ox, y, ze), (-hl - ox, y, ze)]
            if sgn > 0:
                fas = [fas[1], fas[0], fas[3], fas[2]]
            b.quad(fas, STEEL)
            # gutter along the eave and downpipes every ~12 m
            b.box((0, sgn * (hw + oy + 0.1), ze - ft - 0.08), (L + 2 * ox, 0.2, 0.16), STEEL, bottom=True)
            for k in range(max(2, int(L // 12) + 1)):
                x = -hl + 0.6 + k * (L - 1.2) / max(1, int(L // 12))
                b.cyl((x, sgn * (hw + oy + 0.1), ze - ft - 0.1), (x, sgn * (hw + 0.12), ze - ft - 0.6), 0.07, STEEL, seg=6)
                b.cyl((x, sgn * (hw + 0.12), ze - ft - 0.6), (x, sgn * (hw + 0.12), 0.25), 0.07, STEEL, seg=6)
            # skylight strips on the slope
            for k in range(int(L // 8)):
                x = -hl + 4.0 + k * 8.0
                f0, f1 = 0.36, 0.5
                p = lambda f, dx: (x + dx, sgn * hw * f, zr - rise * f + 0.03)
                sk = [p(f0, -2.8), p(f0, 2.8), p(f1, 2.8), p(f1, -2.8)]
                if sgn < 0:
                    sk = [sk[1], sk[0], sk[3], sk[2]]
                b.quad(sk, SKY)
        # gables, their rake fascias, louvres and the line's sign
        logo = rng.choice(["container_logo_rust", "container_logo_orange", "container_logo_blue", "container_logo_green"])
        for sgn in (1, -1):
            x = sgn * hl
            tri = [(x, -hw, H), (x, hw, H), (x, 0, H + rise)]
            vs = [b.bm.verts.new(p) for p in (tri if sgn > 0 else tri[::-1])]
            b.bm.faces.new(vs).material_index = CL
            xf = x + sgn * (ox + 0.01)
            for s2 in (1, -1):
                rk = [(xf, s2 * (hw + oy), ze - ft), (xf, 0, zr - ft), (xf, 0, zr), (xf, s2 * (hw + oy), ze)]
                if sgn * s2 < 0:
                    rk = [rk[1], rk[0], rk[3], rk[2]]
                b.quad(rk, STEEL)
            for s2 in (-1, 1):
                yl = s2 * W * 0.3
                lv = [(x + sgn * 0.03, yl - 0.9, H - 1.6), (x + sgn * 0.03, yl + 0.9, H - 1.6), (x + sgn * 0.03, yl + 0.9, H - 0.6), (x + sgn * 0.03, yl - 0.9, H - 0.6)]
                if sgn < 0:
                    lv = [lv[1], lv[0], lv[3], lv[2]]
                b.quad(lv, DOOR)
            sw = min(W * 0.55, 16.0)
            sh = sw * 0.38
            zc = H - 0.4 - sh / 2 - 1.8
            sg = [(x + sgn * 0.05, -sw / 2, zc - sh / 2), (x + sgn * 0.05, sw / 2, zc - sh / 2), (x + sgn * 0.05, sw / 2, zc + sh / 2), (x + sgn * 0.05, -sw / 2, zc + sh / 2)]
            if sgn < 0:
                sg = [sg[1], sg[0], sg[3], sg[2]]
            b.quad(sg, SIGN, [(0, 0), (1, 0), (1, 1), (0, 1)])       # u runs left to right seen from outside
        # ridge cap and roof vents
        b.box((0, 0, zr + 0.04), (L + 2 * ox, 0.6, 0.12), STEEL, bottom=True)
        for k in range(max(1, int(L // 14))):
            x = -hl + 7.0 + k * 14.0
            b.cyl((x, 0, zr - 0.1), (x, 0, zr + 0.8), 0.32, STEEL, seg=10)
            b.cyl((x, 0, zr + 0.8), (x, 0, zr + 1.05), 0.55, STEEL, seg=10, r2=0.08)
        # roll-up doors on the long sides: frame, slats, canopy, lamp, bumpers; personnel doors
        n = int(L // 12)
        for k in range(n):
            x = -hl + (k + 0.5) * L / n
            for sgn in (1, -1):
                y = sgn * (hw + 0.05)

                def face(x0, x1, z0, z1, yy, mat):
                    pts = [(x0, yy, z0), (x1, yy, z0), (x1, yy, z1), (x0, yy, z1)]
                    if sgn > 0:
                        pts = [pts[1], pts[0], pts[3], pts[2]]
                    b.quad(pts, mat)
                face(x - 2.2, x + 2.2, 0.0, 5.0, y, DOOR)
                for zz in (1.0, 2.0, 3.0, 4.0):
                    b.box((x, sgn * (hw + 0.08), zz), (4.4, 0.05, 0.06), STEEL, bottom=True)
                b.box((x, sgn * (hw + 0.09), 0.08), (4.4, 0.08, 0.16), STEEL, bottom=True)
                for dx in (-2.35, 2.35):
                    b.box((x + dx, sgn * (hw + 0.1), 2.6), (0.3, 0.2, 5.2), STEEL)
                b.box((x, sgn * (hw + 0.1), 5.3), (5.0, 0.2, 0.4), STEEL)
                b.box((x, sgn * (hw + 0.9), 5.9), (5.6, 1.7, 0.18), STEEL, bottom=True)
                b.box((x, sgn * (hw + 0.25), 5.75), (0.5, 0.25, 0.14), LAMP, bottom=True)
                for dx in (-1.9, 1.9):
                    b.box((x + dx, sgn * (hw + 0.15), 1.05), (0.28, 0.22, 0.45), DOOR, bottom=True)
                if k % 2 == 0:
                    px = x + 3.4
                    face(px - 0.5, px + 0.5, 0.0, 2.2, y, DOOR)
                    b.box((px, sgn * (hw + 0.4), 2.45), (1.5, 0.8, 0.08), STEEL, bottom=True)
                    b.box((px, sgn * (hw + 0.12), 2.32), (0.25, 0.12, 0.1), LAMP, bottom=True)
        # an UNPLUG tag low on one long wall
        tx = -hl + (rng.randrange(max(1, n)) + 0.5) * L / max(1, n) + 4.4         # between a door and the next
        tg = [(tx, -hw - 0.06, 1.25), (tx + 3.0, -hw - 0.06, 1.25), (tx + 3.0, -hw - 0.06, 3.0), (tx, -hw - 0.06, 3.0)]
        b.quad(tg, TAG, [(0, 0), (1, 0), (1, 1), (0, 1)])
        props_dec = os.path.join(self.root, "assets", "decals", "props")
        tag = rng.choice(["graffiti_unplug", "graffiti_who_owns", "graffiti_not_data"])
        return b.finish(key, [self.M["cladding"], self.M["door"], self.M["band_warm"], self.M["steel_dark"], self.M["plinth"], self.M["roof_sheet"],
                              self.M["skylight"], self.M["decal_fn"](os.path.join(props_dec, logo + ".png")),
                              self.M["decal_flat"](os.path.join(self.story, tag + ".png"))])

    def container(self):
        b = Mesher()
        L, W, H = 12.19, 2.44, 2.59
        b.box((0, 0, H / 2), (L, W, H), 0, bottom=True)
        b.box((L / 2 + 0.02, 0, H / 2), (0.05, W - 0.1, H - 0.1), 1, top=False)
        return b.finish("container", [self.M["corrugated"], self.M["steel_dark"]])

    def crane(self):
        """Ship-to-shore gantry crane: local +y is the sea (boom), legs on rails."""
        b = Mesher()
        span, base = 28.0, 18.0
        for x in (-span / 2, span / 2):
            for y in (-base / 2, base / 2):
                b.box((x, y, 21.0), (1.6, 1.6, 42.0), 0, top=False)
            b.box((x, 0, 1.0), (2.2, base + 4, 2.0), 0)
            b.box((x, 0, 30.0), (1.2, base, 1.2), 0)
        for y in (-base / 2, base / 2):
            b.box((0, y, 42.5), (span + 1.6, 1.6, 1.6), 0)
        b.box((0, 18.0, 44.5), (6.0, 92.0, 2.5), 0)         # boom (52 m over the water) + back reach
        b.box((0, -14.0, 47.0), (10.0, 10.0, 6.0), 1)        # machinery house
        for y in (-base / 2, base / 2):
            b.cyl((0, y, 43.0), (0, y, 62.0), 0.6, 0)        # A-frame
        b.cyl((0, base / 2, 62.0), (0, 62.0, 45.5), 0.12, 2, seg=6)
        b.cyl((0, -base / 2, 62.0), (0, -27.0, 46.0), 0.12, 2, seg=6)
        b.box((0, 30.0, 40.5), (4.0, 3.0, 3.0), 1)           # trolley / cab
        b.box((0, 0, 62.4), (0.8, 0.8, 0.8), 3)              # beacon
        return b.finish("crane_sts", [self.M["crane_paint"], self.M["steel_dark"], self.M["cable"], self.M["red_light"]])

    def mast(self):
        b = Mesher()
        b.cyl((0, 0, 0), (0, 0, 30.0), 0.45, 0, seg=10, r2=0.25)
        b.box((0, 0, 30.2), (4.0, 1.2, 0.4), 0)
        for x in (-1.4, -0.45, 0.45, 1.4):
            b.box((x, 0.0, 29.8), (0.8, 0.5, 0.3), 1, top=False, bottom=True)
        return b.finish("light_mast", [self.M["steel_dark"], self.M["mast_light"]])

    def signal(self, key, mast):
        """Signal pole: post at the origin, mast arm along +x over the lanes,
        three-aspect heads facing -y (towards the approaching traffic)."""
        b = Mesher()
        b.cyl((0, 0, 0), (0, 0, 6.6), 0.13, 0, seg=10, r2=0.1)
        b.cyl((0, 0, 6.2), (mast, 0, 6.2), 0.09, 0, seg=8)
        b.cyl((0, 0, 5.2), (mast * 0.45, 0, 6.15), 0.05, 0, seg=6)
        heads = [mast * 0.55, mast * 0.95] if mast > 6 else [mast * 0.7]
        for hx in heads + [0.3]:
            hz = 5.1 if hx > 0.5 else 3.0
            b.box((hx, 0, hz), (0.38, 0.32, 1.05), 0)
            for k, mat in enumerate((1, 2, 3)):
                zc = hz + 0.33 - k * 0.33
                pts = [(hx - 0.11, -0.17, zc - 0.11), (hx + 0.11, -0.17, zc - 0.11), (hx + 0.11, -0.17, zc + 0.11), (hx - 0.11, -0.17, zc + 0.11)]
                b.quad(pts, mat)
        b.box((mast * 0.5, -0.05, 6.7), (2.2, 0.08, 0.6), 4)  # street name plate
        return b.finish(key, [self.M["steel_dark"], self.M["sig_red"], self.M["sig_amber"], self.M["sig_green"], self.M["sign_blue"]])

    def tree(self, key):
        b = Mesher()
        if key == "tree_pine":
            b.cyl((0, 0, 0), (0, 0, 3.0), 0.25, 0, seg=6, r2=0.18)
            for k, (z0, r, h) in enumerate(((2.0, 2.6, 4.5), (4.5, 2.0, 4.0), (7.0, 1.3, 3.6))):
                b.cyl((0, 0, z0), (0, 0, z0 + h), r, 1, seg=8, r2=0.05)
        else:
            b.cyl((0, 0, 0), (0, 0, 3.2), 0.3, 0, seg=6, r2=0.2)
            bm2 = bmesh.ops.create_icosphere(b.bm, subdivisions=2, radius=2.8, matrix=Matrix.Translation((0, 0, 5.0)) @ Matrix.Diagonal((1.0, 1.0, 0.85, 1)))
            for f in {f for v in bm2["verts"] for f in v.link_faces}:
                f.material_index = 1
            rng = random.Random(3)
            for v in bm2["verts"]:
                v.co += v.co.normalized() * 0.0 + Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), rng.uniform(-0.3, 0.3)))
        return b.finish(key, [self.M["bark"], self.M["leaves"]])


def kit_materials(root, town):
    M = {}
    M["facade_default"] = facade_material(root, "glass_blue")
    for st in ("glass_blue", "glass_dark", "concrete_warm", "panel_cyan"):
        M["facade_" + st] = facade_material(root, st)
    m, nt, bsdf = _nodes("WorldRoof")
    bsdf.inputs["Base Color"].default_value = (0.09, 0.09, 0.095, 1)
    bsdf.inputs["Roughness"].default_value = 0.7
    M["roof"] = m
    M["band"] = emissive("WorldBandCyan", (0.3, 0.85, 1.0), 6.0)
    M["band_warm"] = emissive("WorldBandWarm", (1.0, 0.7, 0.4), 4.0)
    tex = tex_dir(root, "corrugated")
    M["corrugated"] = painted("WorldCorrugated", tex=tex, scale=4.0)
    M["crane_paint"] = painted("WorldCranePaint", rough=0.5, metal=0.4)
    M["cladding"] = cladding("WorldWarehouseCladding", tex=tex, scale=4.0)
    M["roof_sheet"] = cladding("WorldWarehouseRoof", tex=tex, scale=4.0, colour=(0.42, 0.43, 0.44), rust=0.9)
    m, nt, bsdf = _nodes("WorldPlinth")
    bsdf.inputs["Base Color"].default_value = (0.2, 0.195, 0.185, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    M["plinth"] = m
    m, nt, bsdf = _nodes("WorldSkylight")
    bsdf.inputs["Base Color"].default_value = (0.22, 0.27, 0.25, 1)
    bsdf.inputs["Roughness"].default_value = 0.35
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.82, 0.55, 1)
    bsdf.inputs["Emission Strength"].default_value = 0.25
    M["skylight"] = m
    M["decal_flat"] = lambda path: town["decal_material"](path, 0.0)

    m, nt, bsdf = _nodes("WorldDoor")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.05, 0.055, 1)
    bsdf.inputs["Metallic"].default_value = 0.7
    bsdf.inputs["Roughness"].default_value = 0.5
    M["door"] = m
    m, nt, bsdf = _nodes("WorldSteelDark")
    bsdf.inputs["Base Color"].default_value = (0.06, 0.065, 0.07, 1)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.45
    M["steel_dark"] = m
    M["cable"] = emissive("WorldCableLED", (0.55, 0.85, 1.0), 1.2)
    M["red_light"] = emissive("WorldAviationRed", (1.0, 0.05, 0.02), 30.0)
    M["mast_light"] = emissive("WorldMastLight", (1.0, 0.8, 0.55), 40.0)
    M["sig_red"] = emissive("WorldSignalRed", (1.0, 0.05, 0.02), 20.0)
    M["sig_amber"] = emissive("WorldSignalAmber", (1.0, 0.45, 0.02), 1.0)
    M["sig_green"] = emissive("WorldSignalGreen", (0.1, 1.0, 0.45), 1.0)
    m, nt, bsdf = _nodes("WorldSignBlue")
    bsdf.inputs["Base Color"].default_value = (0.02, 0.1, 0.35, 1)
    bsdf.inputs["Roughness"].default_value = 0.4
    M["sign_blue"] = m
    m, nt, bsdf = _nodes("WorldBark")
    bsdf.inputs["Base Color"].default_value = (0.06, 0.045, 0.035, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    M["bark"] = m
    m, nt, bsdf = _nodes("WorldLeaves")
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.025, 0.05, 0.02, 1)
    ramp.color_ramp.elements[1].color = (0.06, 0.09, 0.03, 1)
    nt.links.new(oi.outputs["Random"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    M["leaves"] = m
    M["decal_fn"] = lambda path: town["decal_material"](path, 0.7)
    return M
