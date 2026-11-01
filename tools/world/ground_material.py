"""The open world's terrain material (Blender 5.2, Cycles / EEVEE) from the
Pigment ground sets (tools/ground_textures.py) and the world ground masks
(tools/world/ground_masks.py). game/scripts/terrain.gdshader is the Godot twin;
keep the blend rules (`weights` below) in step with it.

Blend, bottom to top (each step height-aware: a set's own height map decides
where its edge runs, so sand fills between grass tufts and scree pokes out):
    grass_turf      everywhere
    dirt_mud        patches by noise, verges along roads through natural land
    cracked_mud     dried hollows (hollow mask x broad noise)
    dirt_mud        wet hollows
    forest_floor    under the cedar / pine forests (forest mask)
    scree           below cliffs (scree mask) and on 25-30 deg slopes
    rock_cliff      slopes over ~30 deg, and the summits (> 210 m); triplanar
    beach_sand      natural shores (shore mask), with a wet line at the water
    city land       road concrete, cobbles in the old town, vacant lots in port gaps
Anti-tiling: every planar set is sampled twice (the second rotated 37 deg and
offset) and the two are mixed by world noise; macro tone and roughness drift
over tens of metres. Normal maps are applied as world-space perturbations
(UDN): planar sets in the ground plane, the rock triplanar.
"""
import math
import os

import bpy

SETS = ("grass_turf", "dirt_mud", "cracked_mud", "forest_floor", "scree", "rock_cliff", "beach_sand", "cobbles", "vacant_lot")
TILE_M = {"rock_cliff": 4.0, "scree": 2.0, "forest_floor": 2.0, "grass_turf": 2.0, "dirt_mud": 4.0, "beach_sand": 4.0,
          "cracked_mud": 3.0, "cobbles": 2.0, "vacant_lot": 4.0}
ROT = math.radians(37.0)


def tex_root(root):
    return os.path.join(root, "scenes", "town", "textures", "world")


def available(root):
    t = tex_root(root)
    return all(os.path.isfile(os.path.join(t, s, f"{s}_BaseColor.png")) for s in SETS)


def masks_path(root):
    for d in (os.path.join(root, "scenes", "world"), os.path.join(root, "game", "assets", "world")):
        p = os.path.join(d, "ground_masks.png")
        if os.path.isfile(p) and os.path.isfile(os.path.join(d, "ground_masks2.png")):
            return d
    return None


# ---------------------------------------------------------------- node helpers
class NT:
    """Small builder over a node tree."""

    def __init__(self, nt):
        self.nt = nt

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def _in(self, sock, v):
        if isinstance(v, (int, float)):
            sock.default_value = v
        elif isinstance(v, tuple):
            sock.default_value = v
        elif v is not None:
            self.link(v, sock)

    def math(self, op, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._in(n.inputs[0], a)
        if b is not None:
            self._in(n.inputs[1], b)
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self._in(n.inputs[0], a)
        if b is not None:
            self._in(n.inputs[1], b)
        if scale is not None:
            self._in(n.inputs["Scale"], scale)
        return n.outputs["Value" if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else "Vector"]

    def mix(self, f, a, b, kind="RGBA"):
        n = self.node("ShaderNodeMix", data_type=kind)
        if kind == "RGBA":
            n.blend_type = "MIX"
            ia, ib = 6, 7
        elif kind == "VECTOR":
            ia, ib = 4, 5
        else:
            ia, ib = 2, 3
        self._in(n.inputs["Factor"] if kind != "VECTOR" else n.inputs[0], f)
        self._in(n.inputs[ia], a)
        self._in(n.inputs[ib], b)
        return n.outputs[2 if kind == "RGBA" else (1 if kind == "VECTOR" else 0)]

    def smooth(self, a, b, x):
        n = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
        n.inputs["From Min"].default_value = a
        n.inputs["From Max"].default_value = b
        self._in(n.inputs["Value"], x)
        return n.outputs["Result"]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.link(v, n.inputs[0])
        return n.outputs

    def comb(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for k, v in enumerate((x, y, z)):
            self._in(n.inputs[k], v)
        return n.outputs[0]

    def noise(self, vec, scale, detail=4.0):
        n = self.node("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        self.link(vec, n.inputs["Vector"])
        return n.outputs["Fac"]

    def img(self, path, color, vec, interp="Linear"):
        n = self.node("ShaderNodeTexImage", interpolation=interp)
        n.image = bpy.data.images.load(path, check_existing=True)
        if not color:
            n.image.colorspace_settings.name = "Non-Color"
        self.link(vec, n.inputs["Vector"])
        return n

    def rot_z(self, vec, angle):
        n = self.node("ShaderNodeVectorRotate", rotation_type="Z_AXIS")
        self.link(vec, n.inputs["Vector"])
        n.inputs["Angle"].default_value = angle
        return n.outputs[0]


def _group(name):
    ng = bpy.data.node_groups.get(name)
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new(name, "ShaderNodeTree")
    return ng


def _io(ng, ins, outs):
    for n, t in ins:
        ng.interface.new_socket(n, in_out="INPUT", socket_type=t)
    for n, t in outs:
        ng.interface.new_socket(n, in_out="OUTPUT", socket_type=t)
    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    return gi, go


OUTS = [("Color", "NodeSocketColor"), ("Roughness", "NodeSocketFloat"), ("Height", "NodeSocketFloat"), ("Pert", "NodeSocketVector")]


def _maps(root, s):
    d = os.path.join(tex_root(root), s)
    return {m: os.path.join(d, f"{s}_{m}.png") for m in ("BaseColor", "Roughness", "Height", "Normal_OpenGL")}


def _sample(b, maps, uv):
    c = b.img(maps["BaseColor"], True, uv).outputs["Color"]
    r = b.img(maps["Roughness"], False, uv).outputs["Color"]
    h = b.img(maps["Height"], False, uv).outputs["Color"]
    n = b.img(maps["Normal_OpenGL"], False, uv).outputs["Color"]
    nv = b.vmath("SUBTRACT", b.vmath("SCALE", n, scale=2.0), (1.0, 1.0, 1.0))
    nx = b.sep(nv)
    return c, b.math("MULTIPLY", r, 1.0), b.math("MULTIPLY", h, 1.0), nx


def planar_group(root, s):
    """Top projection in metres, two samples (the second rotated 37 deg) mixed by K."""
    ng = _group(f"Ground_{s}")
    gi, go = _io(ng, [("Pos", "NodeSocketVector"), ("K", "NodeSocketFloat")], OUTS)
    b = NT(ng)
    maps = _maps(root, s)
    uv1 = b.vmath("SCALE", gi.outputs["Pos"], scale=1.0 / TILE_M[s])
    uv2 = b.vmath("ADD", b.rot_z(uv1, ROT), (0.31, 0.57, 0.0))
    c1, r1, h1, n1 = _sample(b, maps, uv1)
    c2, r2, h2, n2 = _sample(b, maps, uv2)
    p1 = b.comb(n1[0], n1[1], 0.0)
    p2 = b.rot_z(b.comb(n2[0], n2[1], 0.0), -ROT)
    k = gi.outputs["K"]
    b.link(b.mix(k, c1, c2), go.inputs["Color"])
    b.link(b.mix(k, r1, r2, "FLOAT"), go.inputs["Roughness"])
    b.link(b.mix(k, h1, h2, "FLOAT"), go.inputs["Height"])
    b.link(b.mix(k, p1, p2, "VECTOR"), go.inputs["Pert"])
    return ng


def triplanar_group(root, s, sharp=4.0):
    """World triplanar (u, v) = (y, z) on x-facing, (x, z) on y-facing, (x, y) on
    up-facing surfaces; the tile's v runs up cliffs. Normals as UDN perturbations."""
    ng = _group(f"Ground_{s}_tri")
    gi, go = _io(ng, [("Pos", "NodeSocketVector"), ("Normal", "NodeSocketVector")], OUTS)
    b = NT(ng)
    maps = _maps(root, s)
    P = b.sep(b.vmath("SCALE", gi.outputs["Pos"], scale=1.0 / TILE_M[s]))
    N = b.sep(gi.outputs["Normal"])
    w = [b.math("POWER", b.math("ABSOLUTE", N[i]), sharp) for i in range(3)]
    tot = b.math("ADD", b.math("ADD", w[0], w[1]), w[2])
    w = [b.math("DIVIDE", x, tot) for x in w]
    proj = [b.comb(P[1], P[2], 0.0), b.comb(P[0], P[2], 0.0), b.comb(P[0], P[1], 0.0)]
    acc = None
    for i in range(3):
        c, r, h, n = _sample(b, maps, proj[i])
        pert = [b.comb(0.0, n[0], n[1]), b.comb(n[0], 0.0, n[1]), b.comb(n[0], n[1], 0.0)][i]
        vals = (b.vmath("SCALE", c, scale=w[i]), b.math("MULTIPLY", r, w[i]), b.math("MULTIPLY", h, w[i]), b.vmath("SCALE", pert, scale=w[i]))
        if acc is None:
            acc = list(vals)
        else:
            acc = [b.vmath("ADD", acc[0], vals[0]), b.math("ADD", acc[1], vals[1]), b.math("ADD", acc[2], vals[2]), b.vmath("ADD", acc[3], vals[3])]
    for k, nm in enumerate(("Color", "Roughness", "Height", "Pert")):
        b.link(acc[k], go.inputs[nm])
    return ng


def terrain_material(root, wet=0.0):
    """WorldTerrain: the nine Pigment ground sets blended by the world masks,
    slope and height. `wet` (0..1): rain on the ground (darker, glossier,
    puddles in the lows)."""
    m = bpy.data.materials.get("WorldTerrain") or bpy.data.materials.new("WorldTerrain")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    b = NT(nt)
    out = b.node("ShaderNodeOutputMaterial")
    bsdf = b.node("ShaderNodeBsdfPrincipled")
    b.link(bsdf.outputs[0], out.inputs[0])
    m["ground_sets"] = ",".join(SETS)
    geo = b.node("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    nrm = geo.outputs["Normal"]
    P = b.sep(pos)
    z = P[2]
    nz = b.sep(nrm)[2]
    steep = b.math("SUBTRACT", 1.0, nz)
    # world masks (tools/world/ground_masks.py): uv = (pos - origin) / (n * cell)
    md = masks_path(root)
    import json
    meta = json.load(open(os.path.join(md, "ground_masks.json"))) if md else {"n": 2049, "cell_m": 2.0, "origin": [-2048.0, -2048.0]}
    span = meta["n"] * meta["cell_m"]
    off = [-meta["origin"][0] + meta["cell_m"] * 0.5, -meta["origin"][1] + meta["cell_m"] * 0.5, 0.0]
    muv = b.vmath("SCALE", b.vmath("ADD", pos, tuple(off)), scale=1.0 / span)
    if md:
        n1 = b.img(os.path.join(md, "ground_masks.png"), False, muv)
        n2 = b.img(os.path.join(md, "ground_masks2.png"), False, muv)
        for n in (n1, n2):
            n.extension = "EXTEND"
        m1 = b.node("ShaderNodeSeparateColor")
        b.link(n1.outputs["Color"], m1.inputs[0])
        m2 = b.node("ShaderNodeSeparateColor")
        b.link(n2.outputs["Color"], m2.inputs[0])
        urban, forest, scree = m1.outputs[0], m1.outputs[1], m1.outputs[2]
        verge = n1.outputs["Alpha"]
        lot, hollow, oldtown = m2.outputs[0], m2.outputs[1], m2.outputs[2]
        shore = n2.outputs["Alpha"]
        for n in (n1, n2):
            n.image.alpha_mode = "CHANNEL_PACKED"
    else:
        attr = b.node("ShaderNodeAttribute", attribute_name="urban")
        urban = attr.outputs["Fac"]
        forest = scree = verge = lot = hollow = oldtown = 0.0
        shore = b.smooth(4.0, 1.5, z)
    big = b.noise(pos, 0.012, 3.0)
    mid = b.noise(pos, 0.05, 4.0)
    fine = b.noise(pos, 0.25, 3.0)
    K = b.smooth(0.42, 0.58, b.noise(pos, 0.07, 2.0))
    S = {}
    for s in SETS:
        g = b.node("ShaderNodeGroup")
        if s == "rock_cliff":
            g.node_tree = triplanar_group(root, s)
            b.link(pos, g.inputs["Pos"])
            b.link(nrm, g.inputs["Normal"])
        else:
            g.node_tree = planar_group(root, s)
            b.link(pos, g.inputs["Pos"])
            b.link(K, g.inputs["K"])
        S[s] = (g.outputs["Color"], g.outputs["Roughness"], g.outputs["Height"], g.outputs["Pert"])
    if os.path.isfile(os.path.join(root, "scenes", "town", "textures", "roads", "concrete", "concrete_BaseColor.png")):
        # road concrete keeps its old 2 m box mapping; flat in the ground plane here
        d = os.path.join(root, "scenes", "town", "textures", "roads", "concrete")
        uv = b.vmath("SCALE", pos, scale=0.5)
        c = b.img(os.path.join(d, "concrete_BaseColor.png"), True, uv).outputs["Color"]
        r = b.img(os.path.join(d, "concrete_Roughness.png"), False, uv).outputs["Color"]
        h = b.img(os.path.join(d, "concrete_Height.png"), False, uv).outputs["Color"]
        S["concrete"] = (c, b.math("MULTIPLY", r, 1.0), b.math("MULTIPLY", h, 1.0), (0.0, 0.0, 0.0))
    else:
        S["concrete"] = ((0.2, 0.2, 0.2, 1.0), 0.85, 0.5, (0.0, 0.0, 0.0))

    def blend(f, base, s, hk=2.0):
        """Height-aware blend: the incoming set's height map moves its edge."""
        t = S[s]
        if hk:
            f = b.math("ADD", b.math("MULTIPLY", b.math("SUBTRACT", f, 0.5), 2.2), 0.5)
            f = b.math("ADD", f, b.math("MULTIPLY", b.math("SUBTRACT", t[2], base[2]), hk), clamp=True)
        return (b.mix(f, base[0], t[0]), b.mix(f, base[1], t[1], "FLOAT"), b.mix(f, base[2], t[2], "FLOAT"), b.mix(f, base[3], t[3], "VECTOR"))

    def jit(x, amt, n):
        return b.math("ADD", x, b.math("MULTIPLY", b.math("SUBTRACT", n, 0.5), amt))
    base = S["grass_turf"]
    # dirt: patches, verges along roads, wet hollows; then dried hollows crack
    hol = b.smooth(0.25, 0.5, hollow)
    dirtf = b.math("MAXIMUM", b.math("MAXIMUM", b.smooth(0.62, 0.7, mid), b.smooth(0.3, 0.6, jit(verge, 0.5, mid))),
                   b.math("MULTIPLY", hol, b.smooth(0.6, 0.5, big)))
    base = blend(dirtf, base, "dirt_mud")
    base = blend(b.math("MULTIPLY", hol, b.smooth(0.5, 0.6, big)), base, "cracked_mud")
    base = blend(b.smooth(0.3, 0.55, jit(forest, 0.35, mid)), base, "forest_floor")
    # scree below cliffs and on ~28-33 deg slopes (less of it under trees), rock over ~37 deg and on the summits
    screef = b.math("MAXIMUM", b.smooth(0.2, 0.45, jit(scree, 0.3, mid)), b.smooth(0.12, 0.17, jit(steep, 0.04, fine)))
    base = blend(b.math("MULTIPLY", screef, b.math("SUBTRACT", 1.0, b.math("MULTIPLY", forest, 0.8))), base, "scree")
    rockf = b.math("MAXIMUM", b.smooth(0.19, 0.24, jit(steep, 0.05, mid)), b.smooth(210.0, 250.0, b.math("ADD", z, b.math("MULTIPLY", big, 40.0))))
    base = blend(rockf, base, "rock_cliff", hk=1.2)
    base = blend(b.smooth(0.3, 0.55, jit(shore, 0.3, fine)), base, "beach_sand")
    # city land: road concrete, the old town's cobbles, port gaps as vacant lots
    cityf = b.smooth(0.3, 0.6, urban)
    base = blend(cityf, base, "concrete", hk=0)
    base = blend(b.math("MULTIPLY", cityf, b.smooth(0.3, 0.6, oldtown)), base, "cobbles", hk=0)
    base = blend(b.math("MULTIPLY", cityf, b.smooth(0.25, 0.5, jit(lot, 0.3, mid))), base, "vacant_lot", hk=0)
    col, rough, hgt, pert = base
    # macro tone / roughness drift (tens of metres)
    mv = b.noise(pos, 0.03, 3.0)
    tone = b.comb(b.math("ADD", 0.82, b.math("MULTIPLY", mv, 0.36)), b.math("ADD", 0.82, b.math("MULTIPLY", mv, 0.36)), b.math("ADD", 0.84, b.math("MULTIPLY", mv, 0.32)))
    col = b.vmath("MULTIPLY", base[0], tone)
    rough = b.math("ADD", rough, b.math("MULTIPLY", b.math("SUBTRACT", mv, 0.5), 0.15), clamp=True)
    # wet: below the waterline, a wet line on the shore, rain puddles in the lows
    wl = b.math("MAXIMUM", b.smooth(0.5, -0.3, z), b.math("MULTIPLY", b.smooth(1.4, 0.3, z), b.smooth(0.2, 0.5, shore)))
    rain = b.node("ShaderNodeValue")
    rain.label = "Wetness"
    rain.outputs[0].default_value = wet
    lows = b.smooth(0.46, 0.38, b.math("ADD", hgt, b.math("MULTIPLY", b.math("SUBTRACT", b.noise(pos, 0.11, 3.0), 0.5), 0.25)))
    pud = b.math("MULTIPLY", b.math("MULTIPLY", lows, rain.outputs[0]), b.math("SUBTRACT", 1.0, b.smooth(0.05, 0.15, steep)))
    damp = b.math("MAXIMUM", wl, b.math("MULTIPLY", rain.outputs[0], 0.85))
    col = b.vmath("MULTIPLY", col, b.mix(damp, (1.0, 1.0, 1.0), (0.6, 0.6, 0.6), "VECTOR"))
    col = b.vmath("MULTIPLY", col, b.mix(pud, (1.0, 1.0, 1.0), (0.5, 0.5, 0.5), "VECTOR"))
    rough = b.mix(damp, rough, b.math("MULTIPLY", rough, 0.55), "FLOAT")
    rough = b.mix(pud, rough, 0.03, "FLOAT")
    pert = b.vmath("SCALE", pert, scale=b.math("SUBTRACT", 1.0, b.math("MAXIMUM", pud, b.math("MULTIPLY", damp, 0.3))))
    # UDN normal: geometry normal + the blended perturbation
    n = b.vmath("NORMALIZE", b.vmath("ADD", nrm, b.vmath("SCALE", pert, scale=0.9)))
    b.link(col, bsdf.inputs["Base Color"])
    b.link(rough, bsdf.inputs["Roughness"])
    b.link(n, bsdf.inputs["Normal"])
    return m
