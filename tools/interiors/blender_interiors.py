"""Interior-mapped windows in Blender (Cycles / EEVEE), without OSL.

The same technique as game/scripts/interior_window.gdshader, as a node setup added to a
Pigment material (tools/blender_pigment.py / the Pigment Bridge add-on):

    from interiors.blender_interiors import add_interiors
    mat = apply_pigment_material(obj, folder, "building_a")
    add_interiors(mat, "building_a", folder)

Data (from tools/interiors/interiors.py; git-ignored under scenes/town/textures/interiors/):
    interiors_atlas.png + interiors.json          Pigment pack_interiors (pre-projected rooms, alpha = depth)
    windows/<asset>_WindowMap.png, _panes.json    Pigment export_window_map

Per material the script bakes a small float "pane table" image: for every pane its frame
(converted from glTF to Blender object axes), whether the variant lights it (Pigment's emissive
map at the pane centre, i.e. the variant's own lit-window selection and palette), its tint and a
room for each of 16 per-object buckets (Object Info > Random picks the bucket, so instances of
the same variant differ). The nodes then do, per shading point on a pane:
    pane index (window map, Closest) -> frame -> point on the pane in metres (Texture Coordinate
    Object) and the view ray (Geometry Incoming -> object space) in pane tangent space ->
    ray / box exit -> 6-step march against the atlas depth -> room colour -> Emission (x 1 - Fresnel)
    added to the BSDF, whose glass is turned into a dark glossy pane there.
"""
import json
import math
import os

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DATA = os.path.join(ROOT, "scenes", "town", "textures", "interiors")
BUCKETS = 16
ROWS = 4 + BUCKETS
STEPS = 6
SETS = {
    "apartments": {"ground": ["ramen_kitchen", "pachinko_parlour", "implant_clinic", "karaoke_box", "konbini", "memory_pawn", "bar_counter"],
                   "warm": ["apartment_holo", "apartment_kitchen", "neon_bedroom", "capsule_hotel", "evicted_room", "unplug_hideout", "apartment_holo_person"],
                   "cool": ["noctis_clinic", "gym", "hydroponics", "capsule_hotel", "dreamlink_lease", "implant_clinic"],
                   "screen": ["apartment_holo", "dreamlink_lease", "meridian_office", "apartment_holo_person"]},
    "corporate": {"ground": [], "warm": ["hoshikawa_office", "office_cubicles"], "cool": ["office_cubicles", "server_room", "meridian_office"],
                  "screen": ["meridian_office", "server_room"]},
}
GROUND_TOP = 4.2
LIT_ENERGY, OFF_ENERGY, TINT = 0.9, 0.35, 0.35


def _g2b(v):
    """glTF (y up) -> Blender (z up) object axes."""
    return (v[0], -v[2], v[1])


def _atlas(data=DATA):
    meta = json.load(open(os.path.join(data, "interiors.json")))
    name = "interiors_atlas"
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.load(os.path.join(data, meta["image"]), check_existing=True)
        img.name = name
        img.colorspace_settings.name = "sRGB"
        img.alpha_mode = "CHANNEL_PACKED"
    dims = bpy.data.images.get("interiors_dims")
    if dims is None:
        n = len(meta["rooms"])
        dims = bpy.data.images.new("interiors_dims", n, 1, alpha=True, float_buffer=True)
        dims.colorspace_settings.name = "Non-Color"
        px = []
        for r in meta["rooms"]:
            px += [r["size"][0], r["size"][1], r["size"][2], r["eye"]]
        dims.pixels[:] = px
        dims.pack()
    return meta, img, dims


def _pane_table(asset, folder, kind, data=DATA):
    """Float image ROWS x panes for one variant (see module doc)."""
    import numpy as np
    meta = json.load(open(os.path.join(data, "interiors.json")))
    index = {r["name"]: i for i, r in enumerate(meta["rooms"])}
    panes = json.load(open(os.path.join(data, "windows", f"{asset}_panes.json")))["panes"]
    em_path = next((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith("_Emissive.png")), None)
    em = None
    if em_path:
        im = bpy.data.images.load(em_path, check_existing=True)
        ew, eh = im.size
        em = np.empty(ew * eh * 4, dtype=np.float32)
        im.pixels.foreach_get(em)
        em = em.reshape(eh, ew, 4)          # row 0 = bottom (Blender), glTF v is down
    sets = SETS[kind]
    n = len(panes)
    rows = [[0.0] * (4 * n) for _ in range(ROWS)]
    for i, p in enumerate(panes):
        c, r, nr = _g2b(p["center"]), _g2b(p["right"]), _g2b(p["normal"])
        lit, tint = 0.0, (1.0, 0.62, 0.32)
        if em is not None:
            x = min(ew - 1, int(p["uv_center"][0] * ew))
            y = min(eh - 1, int((1.0 - p["uv_center"][1]) * eh))
            col = [float(v) for v in em[y, x, :3]]
            m = max(col)
            if m > 0.03:
                lit, tint = 1.0, tuple(v / m for v in col)
        rows[0][4 * i:4 * i + 4] = [*c, p["size"][0]]
        rows[1][4 * i:4 * i + 4] = [*r, p["size"][1]]
        rows[2][4 * i:4 * i + 4] = [*nr, lit]
        rows[3][4 * i:4 * i + 4] = [*tint, 1.0]
        ground = p["center"][1] < GROUND_TOP and sets["ground"]
        if ground:
            pool = sets["ground"]
        elif lit and tint[2] > tint[0] * 1.25:
            pool = sets["screen"]
        elif lit and tint[2] > tint[0] * 0.82:
            pool = sets["cool"]
        else:
            pool = sets["warm"]
        pool = [index[nm] for nm in pool if nm in index] or [0]
        for b in range(BUCKETS):
            h = (math.sin(i * 12.9898 + b * 78.233 + len(asset)) * 43758.5453) % 1.0
            rows[4 + b][4 * i:4 * i + 4] = [float(pool[int(h * len(pool)) % len(pool)]), 0.0, 0.0, 1.0]
    name = f"panes_{os.path.basename(os.path.normpath(folder))}"
    img = bpy.data.images.get(name) or bpy.data.images.new(name, n, ROWS, alpha=True, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    img.pixels[:] = [v for row in rows for v in row]
    img.pack()
    wm_name = f"{asset}_WindowMap"
    wm = bpy.data.images.get(wm_name)
    if wm is None:
        wm = bpy.data.images.load(os.path.join(data, "windows", f"{asset}_WindowMap.png"))
        wm.name = wm_name
        wm.colorspace_settings.name = "Non-Color"
    return img, wm, n


class _N:
    """Tiny node-graph helper: math on sockets or numbers."""

    def __init__(self, nt):
        self.nt, self.x = nt, -2400

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        n.location = (self.x, 0)
        self.x += 3
        return n

    def _in(self, sock, v):
        if isinstance(v, (int, float)):
            sock.default_value = v
        else:
            self.nt.links.new(v, sock)

    def m(self, op, a, b=0.0, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._in(n.inputs[0], a)
        self._in(n.inputs[1], b)
        return n.outputs[0]

    def add(self, *xs):
        s = xs[0]
        for x in xs[1:]:
            s = self.m("ADD", s, x)
        return s

    def mul(self, a, b):
        return self.m("MULTIPLY", a, b)

    def mix(self, a, b, t):      # a + (b - a) t
        return self.add(a, self.mul(self.m("SUBTRACT", b, a), t))

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.nt.links.new(v, n.inputs[0])
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb(self, x, y, z=0.0):
        n = self.node("ShaderNodeCombineXYZ")
        for s, v in zip(n.inputs, (x, y, z)):
            self._in(s, v)
        return n.outputs[0]

    def vm(self, op, a, b=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.nt.links.new(a, n.inputs[0])
        if b is not None:
            self.nt.links.new(b, n.inputs[1])
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]

    def tex(self, img, vec, interp="Closest"):
        n = self.node("ShaderNodeTexImage", interpolation=interp, extension="EXTEND")
        n.image = img
        self.nt.links.new(vec, n.inputs["Vector"])
        return n


def add_interiors(mat, asset, folder, kind=None, data=DATA):
    """Add interior-mapped windows to a Pigment material of a kit building (one material per variant folder)."""
    kind = kind or ("corporate" if asset == "building_c" else "apartments")
    meta, atlas, dims = _atlas(data)
    table, wm, n_panes = _pane_table(asset, folder, kind, data)
    nt = mat.node_tree
    bsdf = next(nd for nd in nt.nodes if nd.type == "BSDF_PRINCIPLED")
    out = next(nd for nd in nt.nodes if nd.type == "OUTPUT_MATERIAL" and nd.is_active_output)
    N = _N(nt)
    L = float(meta["layers"])
    n_rooms = float(len(meta["rooms"]))
    # pane index from the window map (Blender UVs and images are both v-up: same texel as glTF)
    uvn = N.node("ShaderNodeUVMap")
    wmt = N.tex(wm, uvn.outputs["UV"])
    idx = N.m("ROUND", N.mul(N.sep(wmt.outputs["Color"])[0], 255.0))
    mask = N.m("GREATER_THAN", idx, 0.5)
    col_u = N.m("DIVIDE", N.m("SUBTRACT", idx, 0.5), float(n_panes))

    def row(r):
        t = N.tex(table, N.comb(col_u, (r + 0.5) / ROWS))
        return t.outputs["Color"], t.outputs["Alpha"]
    c0, w = row(0)
    right, h = row(1)
    nrm, lit = row(2)
    tint, _ = row(3)
    # the per-object bucket picks this instance's room for the pane
    oi = N.node("ShaderNodeObjectInfo")
    bucket = N.m("FLOOR", N.mul(oi.outputs["Random"], BUCKETS - 0.001))
    rt = N.tex(table, N.comb(col_u, N.m("DIVIDE", N.add(bucket, 4.5), float(ROWS))))
    room = N.m("ROUND", N.sep(rt.outputs["Color"])[0])
    dt = N.tex(dims, N.comb(N.m("DIVIDE", N.add(room, 0.5), n_rooms), 0.5))
    W0, H0, D0 = N.sep(dt.outputs["Color"])
    E0 = dt.outputs["Alpha"]
    up = N.vm("CROSS_PRODUCT", nrm, right)
    # point on the pane (m) and the view ray in pane space
    tc = N.node("ShaderNodeTexCoord")
    rel = N.vm("SUBTRACT", tc.outputs["Object"], c0)
    px, py = N.vm("DOT_PRODUCT", rel, right), N.vm("DOT_PRODUCT", rel, up)
    geo = N.node("ShaderNodeNewGeometry")
    vt = N.node("ShaderNodeVectorTransform", vector_type="VECTOR", convert_from="WORLD", convert_to="OBJECT")
    nt.links.new(geo.outputs["Incoming"], vt.inputs[0])
    dir_o = N.vm("NORMALIZE", vt.outputs[0])
    vx = N.mul(N.vm("DOT_PRODUCT", dir_o, right), -1.0)
    vy = N.mul(N.vm("DOT_PRODUCT", dir_o, up), -1.0)
    vz = N.m("MINIMUM", N.mul(N.vm("DOT_PRODUCT", dir_o, nrm), -1.0), -1e-4)
    # fit the room round the pane (as the game shader), the pane on a 0.9 m sill
    s = N.m("MAXIMUM", 1.0, N.m("MAXIMUM", N.m("DIVIDE", w, N.mul(W0, 0.82)), N.m("DIVIDE", h, N.mul(H0, 0.8))))
    W, H, D, E = N.mul(W0, s), N.mul(H0, s), N.mul(D0, s), N.mul(E0, s)
    sill = N.m("MINIMUM", N.mul(s, 0.9), N.m("SUBTRACT", N.m("SUBTRACT", H, h), 0.04))
    ox = px
    oy = N.add(py, N.mul(H, -0.5), sill, N.mul(h, 0.5))
    # box exit
    sxv = N.m("SIGN", vx)
    syv = N.m("SIGN", vy)
    tx = N.m("DIVIDE", N.m("SUBTRACT", N.mul(N.mul(sxv, 0.5), W), ox), vx)
    ty = N.m("DIVIDE", N.m("SUBTRACT", N.mul(N.mul(syv, 0.5), H), oy), vy)
    tz = N.m("DIVIDE", N.mul(D, -1.0), vz)
    tmax = N.m("MAXIMUM", N.m("MINIMUM", N.m("MINIMUM", N.m("ABSOLUTE", tx), N.m("ABSOLUTE", ty)), tz), 0.0)
    layer = N.add(N.mul(room, 2.0), N.m("SUBTRACT", 1.0, lit))

    def atlas_vec(t):
        qx, qy, qz = N.add(ox, N.mul(vx, t)), N.add(oy, N.mul(vy, t)), N.mul(vz, t)
        k = N.m("DIVIDE", E, N.m("SUBTRACT", E, qz))
        u = N.add(0.5, N.m("DIVIDE", N.mul(qx, k), W))
        v = N.m("SUBTRACT", 0.5, N.m("DIVIDE", N.mul(qy, k), H))
        u = N.m("MINIMUM", N.m("MAXIMUM", u, 0.002), 0.998)
        v = N.m("MINIMUM", N.m("MAXIMUM", v, 0.002), 0.998)
        # strip layout: layer 0 at the top of the PNG; Blender images are v-up
        av = N.m("SUBTRACT", 1.0, N.m("DIVIDE", N.add(layer, v), L))
        return N.comb(u, av), qz

    t_hit, found = tmax, 0.0
    t_prev, f_prev = 0.0, -1.0
    for i in range(1, STEPS + 1):
        t = N.mul(tmax, i / STEPS)
        vec, qz = atlas_vec(t)
        a = N.tex(atlas, vec, "Linear").outputs["Alpha"]
        f = N.m("SUBTRACT", N.mul(qz, -1.0), N.mul(a, D))
        hit = N.m("GREATER_THAN", f, -1e-4)
        now = N.mul(hit, N.m("SUBTRACT", 1.0, found))
        frac = N.m("DIVIDE", f_prev, N.m("SUBTRACT", f_prev, f))
        tsec = N.mix(t_prev, t, N.m("MINIMUM", N.m("MAXIMUM", frac, 0.0), 1.0))
        t_hit = N.mix(t_hit, tsec, now)
        found = N.m("MAXIMUM", found, hit)
        t_prev, f_prev = t, f
    vec, _ = atlas_vec(t_hit)
    room_col = N.tex(atlas, vec, "Linear").outputs["Color"]
    # energy, tint, Fresnel, glass
    energy = N.mix(OFF_ENERGY, LIT_ENERGY, lit)
    tmix = N.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX")
    tmix.inputs["Factor"].default_value = 0.0
    nt.links.new(N.mul(lit, TINT), tmix.inputs["Factor"])
    tmix.inputs[6].default_value = (1, 1, 1, 1)
    nt.links.new(tint, tmix.inputs[7])
    tinted = N.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    tinted.inputs["Factor"].default_value = 1.0
    nt.links.new(room_col, tinted.inputs[6])
    nt.links.new(tmix.outputs[2], tinted.inputs[7])
    fres = N.node("ShaderNodeFresnel")
    fres.inputs["IOR"].default_value = 1.5
    strength = N.mul(N.mul(energy, mask), N.m("SUBTRACT", 1.0, fres.outputs[0]))
    em = N.node("ShaderNodeEmission")
    nt.links.new(tinted.outputs[2], em.inputs["Color"])
    nt.links.new(strength, em.inputs["Strength"])
    # the BSDF on panes: dark glossy glass, solid, no flat lit-pane emission
    def override(sock_name, value, is_color=False):
        sock = bsdf.inputs.get(sock_name)
        if sock is None:
            return
        mx = N.node("ShaderNodeMix", data_type="RGBA" if is_color else "FLOAT")
        nt.links.new(mask, mx.inputs["Factor"])
        a_in, b_in = (mx.inputs[6], mx.inputs[7]) if is_color else (mx.inputs[2], mx.inputs[3])
        if sock.is_linked:
            nt.links.new(sock.links[0].from_socket, a_in)
        else:
            a_in.default_value = sock.default_value
        b_in.default_value = value
        nt.links.new(mx.outputs[2] if is_color else mx.outputs[0], sock)
    override("Base Color", (0.01, 0.012, 0.014, 1.0), True)
    override("Roughness", 0.04)
    override("Alpha", 1.0)
    override("Transmission Weight", 0.0)
    override("Emission Color", (0.0, 0.0, 0.0, 1.0), True)
    surf = out.inputs["Surface"].links[0].from_socket
    add = N.node("ShaderNodeAddShader")
    nt.links.new(surf, add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs["Surface"])
    mat["pigment_interiors"] = asset
    return mat
