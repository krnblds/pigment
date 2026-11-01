"""Night sky for the rainy megacity: procedural world shader, equirect HDR bake
and a reusable Blender world setup (headless Blender 5.2, Cycles).

Bake (writes assets/sky/<preset>_2k.hdr + docs/agents/sky/<preset>_equirect.png):

    blender -b --factory-startup --python tools/sky/make_sky.py -- [options]

Options (after "--"):
    --presets a,b       subset of PRESETS (default: all)
    --res 2k|4k|8k      HDR size (2k = 2048x1024, committed; 4k / 8k are git-ignored)
    --samples N         Cycles AA samples per pixel (default 16; the sky is analytic)
    --no-preview        skip the tone-mapped PNG preview
    --check             also re-render the baked HDR through apply_sky() and report
                        the mean error against the procedural sky (orientation check)

Use from another Blender script (blender_town.py does this):

    ns = {"__name__": "make_sky"}
    exec(open("tools/sky/make_sky.py").read(), ns)
    ns["apply_sky"](bpy.context.scene, "night_rain")

Presets
    night_rain   default: a low, heavy overcast lit from below by the city: sodium
                 orange at the horizon, magenta, then blue-black overhead, a few
                 breaks with faint stars, searchlights and the MERIDIAN eye glow.
    night_moon   the same deck thinner and broken, a hazy moon behind it.
    dusk         purple-orange sunset glowing under the cloud deck.
    predawn      cold blue hour, thin broken cloud, a pale gold seam in the east.

Orientation
    The HDRs use the glTF / Godot / Pigment equirect convention: the image centre
    (u = 0.5) looks along glTF -Z = Blender +Y and u grows towards +X.  Godot's
    PanoramaSkyMaterial and Pigment's `render(hdri)` read them as they are; in
    Blender the Environment Texture needs a -90 degree Z turn (apply_sky does it).

Clouds
    Each layer is a horizontal plane at height H: the view ray is projected on it
    (p = d.xy * H / d.z), so cells shrink and crowd into the horizon like a real
    deck.  Density is domain-warped fBm, stretched along the wind, eroded by a
    finer noise and remapped with a smoothstep; a second, offset sample towards
    the brightest city glow fakes the light gradient through the cloud (lit
    undersides, darker crevices), so the deck reads as soft volume, not blobs.
    The colour is the light-pollution gradient (elevation ramp x azimuth glow)
    multiplied in; thick cloud is bright, the breaks are dark sky.
"""
import math
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or "tools/sky/make_sky.py"))
ROOT = os.path.dirname(os.path.dirname(HERE))
SKY_DIR = os.path.join(ROOT, "assets", "sky")
DOC_DIR = os.path.join(ROOT, "docs", "agents", "sky")
RES = {"1k": (1024, 512), "2k": (2048, 1024), "4k": (4096, 2048), "8k": (8192, 4096)}


def _c(r, g, b):
    return (r, g, b, 1.0)


# ---------------------------------------------------------------- presets
# Colours are linear radiance (the HDR is scene-referred).  Elevation stops are
# sin(elevation).  az_* are degrees, Blender convention (0 = +X, 90 = +Y).
PRESETS = {
    "night_rain": dict(
        label="Night rain",
        # light-pollution gradient on the cloud base, by elevation
        glow=[(0.0, _c(0.80, 0.33, 0.085)), (0.10, _c(0.58, 0.21, 0.075)), (0.26, _c(0.32, 0.095, 0.13)),
              (0.48, _c(0.14, 0.05, 0.13)), (0.75, _c(0.055, 0.03, 0.085)), (1.0, _c(0.032, 0.024, 0.06))],
        # clear sky seen through the breaks
        clear=[(0.0, _c(0.10, 0.04, 0.05)), (0.15, _c(0.010, 0.007, 0.018)), (1.0, _c(0.0016, 0.0019, 0.0045))],
        haze=_c(0.70, 0.30, 0.10), haze_height=0.07, haze_amount=0.9,
        ground=_c(0.012, 0.007, 0.006),
        downtown=dict(az=60.0, width=55.0, gain=0.9),       # brightest glow (MERIDIAN district)
        az_vary=0.35,
        layers=[  # height, scale, stretch, coverage lo/hi, opacity, brightness, warp, wind deg, seed
            dict(h=1.0, scale=0.75, stretch=1.5, lo=0.30, hi=0.62, alpha=1.0, gain=1.0, warp=0.4, wind=25, seed=1.0),
            dict(h=2.2, scale=0.45, stretch=2.4, lo=0.36, hi=0.66, alpha=0.9, gain=0.6, warp=0.5, wind=40, seed=7.0),
        ],
        breaks=dict(scale=0.22, lo=0.36, hi=0.43, amount=0.85),
        shade=1.6,
        stars=dict(density=0.020, gain=0.8),
        moon=None,
        sun=None,
        searchlights=[dict(az=48, lean=-14, width=0.9, gain=0.10, top=0.42), dict(az=71, lean=10, width=0.7, gain=0.07, top=0.36),
                      dict(az=-128, lean=6, width=0.8, gain=0.05, top=0.30)],
        eye=dict(az=75, el=24, r=0.9, gain=0.55, color=_c(0.15, 0.85, 1.0), pupil=_c(1.0, 0.08, 0.10)),
        fog=dict(color=_c(0.62, 0.42, 0.40), density=0.0045, emission=_c(0.022, 0.010, 0.008)),
        world_light=0.6,
        key=dict(az=-120, el=55, energy=0.05, color=(0.6, 0.7, 1.0)),
        exposure=1.0,
    ),
}

PRESETS["night_moon"] = dict(
    PRESETS["night_rain"],
    label="Night, hazy moon",
    layers=[
        dict(h=1.0, scale=1.5, stretch=2.8, lo=0.40, hi=0.70, alpha=0.88, gain=0.9, warp=1.0, wind=25, seed=3.0),
        dict(h=2.6, scale=0.8, stretch=4.0, lo=0.36, hi=0.66, alpha=0.55, gain=0.5, warp=1.3, wind=40, seed=9.0),
    ],
    breaks=dict(scale=0.25, lo=0.25, hi=0.45, amount=0.9),
    stars=dict(density=0.025, gain=1.0),
    moon=dict(az=-115, el=38, size=0.55, gain=60.0, color=(0.85, 0.9, 1.0), halo=0.35),
    key=dict(az=-115, el=38, energy=0.12, color=(0.65, 0.75, 1.0)),
)

PRESETS["dusk"] = dict(
    label="Dusk",
    glow=[(0.0, _c(2.2, 0.75, 0.28)), (0.05, _c(1.35, 0.42, 0.26)), (0.14, _c(0.62, 0.20, 0.30)),
          (0.30, _c(0.26, 0.10, 0.26)), (0.55, _c(0.12, 0.07, 0.17)), (1.0, _c(0.07, 0.05, 0.12))],
    clear=[(0.0, _c(0.9, 0.42, 0.25)), (0.12, _c(0.22, 0.14, 0.28)), (1.0, _c(0.045, 0.06, 0.14))],
    haze=_c(1.6, 0.70, 0.36), haze_height=0.06, haze_amount=1.0,
    ground=_c(0.10, 0.05, 0.05),
    downtown=dict(az=60.0, width=55.0, gain=0.35),
    az_vary=0.25,
    layers=[
        dict(h=1.2, scale=1.5, stretch=3.0, lo=0.36, hi=0.66, alpha=0.95, gain=1.0, warp=1.0, wind=-20, seed=2.0),
        dict(h=3.0, scale=0.8, stretch=4.5, lo=0.40, hi=0.72, alpha=0.75, gain=0.8, warp=1.2, wind=-5, seed=5.0),
    ],
    breaks=dict(scale=0.2, lo=0.28, hi=0.44, amount=0.85),
    shade=1.8,
    stars=None,
    moon=None,
    sun=dict(az=-160, el=-2.5, color=_c(3.2, 0.95, 0.35), width=0.9, horizon=6.0, under=2.6),
    searchlights=[],
    eye=dict(az=75, el=24, r=0.9, gain=0.25, color=_c(0.15, 0.85, 1.0), pupil=_c(1.0, 0.08, 0.10)),
    fog=dict(color=_c(0.80, 0.55, 0.50), density=0.0035, emission=_c(0.05, 0.025, 0.022)),
    world_light=0.8,
    key=dict(az=-160, el=4, energy=0.35, color=(1.0, 0.55, 0.35)),
    exposure=0.6,
)

PRESETS["predawn"] = dict(
    label="Pre-dawn",
    glow=[(0.0, _c(0.55, 0.30, 0.20)), (0.05, _c(0.30, 0.17, 0.17)), (0.14, _c(0.13, 0.10, 0.17)),
          (0.30, _c(0.075, 0.075, 0.14)), (0.55, _c(0.045, 0.055, 0.11)), (1.0, _c(0.03, 0.04, 0.085))],
    clear=[(0.0, _c(0.30, 0.22, 0.24)), (0.12, _c(0.07, 0.09, 0.17)), (1.0, _c(0.012, 0.022, 0.06))],
    haze=_c(0.50, 0.36, 0.34), haze_height=0.06, haze_amount=0.9,
    ground=_c(0.05, 0.04, 0.045),
    downtown=dict(az=60.0, width=55.0, gain=0.5),
    az_vary=0.25,
    layers=[
        dict(h=1.4, scale=1.3, stretch=3.5, lo=0.46, hi=0.74, alpha=0.85, gain=0.8, warp=1.1, wind=60, seed=4.0),
        dict(h=4.0, scale=0.7, stretch=5.0, lo=0.42, hi=0.72, alpha=0.6, gain=0.8, warp=1.4, wind=70, seed=8.0),
    ],
    breaks=dict(scale=0.22, lo=0.20, hi=0.50, amount=0.95),
    shade=1.4,
    stars=dict(density=0.015, gain=0.35),
    moon=None,
    sun=dict(az=20, el=-9.0, color=_c(1.1, 0.55, 0.30), width=1.3, horizon=3.0, under=1.6),
    searchlights=[],
    eye=dict(az=75, el=24, r=0.9, gain=0.3, color=_c(0.15, 0.85, 1.0), pupil=_c(1.0, 0.08, 0.10)),
    fog=dict(color=_c(0.50, 0.50, 0.58), density=0.004, emission=_c(0.016, 0.016, 0.022)),
    world_light=0.8,
    key=dict(az=20, el=6, energy=0.12, color=(0.75, 0.75, 1.0)),
    exposure=1.0,
)

DEFAULT = "night_rain"


# ---------------------------------------------------------------- node helpers
class G:
    """Tiny expression builder over a shader node tree.  Arguments are sockets
    or plain numbers / tuples (written into the input's default value)."""

    def __init__(self, nt):
        self.nt = nt
        self.x = 0

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        n.location = (self.x, 0)
        self.x += 30
        return n

    def put(self, sock, v):
        if v is None:
            return
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, sock)
        elif isinstance(v, tuple):
            n = len(sock.default_value)
            sock.default_value = (tuple(v) + (1.0,) * n)[:n]
        else:
            sock.default_value = v

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.put(n.inputs[0], a)
        self.put(n.inputs[1], b)
        self.put(n.inputs[2], c)
        return n.outputs[0]

    def add(self, a, b):
        return self.math("ADD", a, b)

    def mul(self, a, b):
        return self.math("MULTIPLY", a, b)

    def sub(self, a, b):
        return self.math("SUBTRACT", a, b)

    def vmath(self, op, a, b=None, scale=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.put(n.inputs[0], a)
        self.put(n.inputs[1], b)
        if scale is not None:
            self.put(n.inputs["Scale"], scale)
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.put(n.inputs[0], v)
        return n.outputs

    def comb(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.put(n.inputs[i], v)
        return n.outputs[0]

    def smooth(self, v, lo, hi, out_lo=0.0, out_hi=1.0):
        n = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
        self.put(n.inputs["Value"], v)
        self.put(n.inputs[1], lo)
        self.put(n.inputs[2], hi)
        self.put(n.inputs[3], out_lo)
        self.put(n.inputs[4], out_hi)
        return n.outputs["Result"]

    def noise(self, vec, scale, detail=6.0, rough=0.55, lac=2.0, dist=0.0, dims="3D", w=None, color=False):
        n = self.node("ShaderNodeTexNoise", noise_dimensions=dims, noise_type="FBM")
        self.put(n.inputs["Vector"], vec)
        self.put(n.inputs["Scale"], scale)
        self.put(n.inputs["Detail"], detail)
        self.put(n.inputs["Roughness"], rough)
        self.put(n.inputs["Lacunarity"], lac)
        self.put(n.inputs["Distortion"], dist)
        if w is not None:
            self.put(n.inputs["W"], w)
        return n.outputs["Color"] if color else n.outputs["Factor"]

    def ramp(self, fac, stops):
        n = self.node("ShaderNodeValToRGB")
        cr = n.color_ramp
        cr.interpolation = "B_SPLINE" if len(stops) > 2 else "LINEAR"
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = col
        self.put(n.inputs[0], fac)
        return n.outputs["Color"]

    def mix(self, fac, a, b, blend="MIX"):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self.put(n.inputs["Factor"], fac)
        self.put(n.inputs[6], a)
        self.put(n.inputs[7], b)
        return n.outputs[2]

    def cmul(self, a, b):
        return self.mix(1.0, a, b, "MULTIPLY")

    def cadd(self, a, b):
        return self.mix(1.0, a, b, "ADD")

    def scale_color(self, c, s):
        """colour * scalar (scalar socket or number)."""
        return self.vmath("SCALE", c, scale=s)

    def gauss(self, x, width):
        """exp(-(x / width)^2)"""
        q = self.math("DIVIDE", x, width)
        return self.math("EXPONENT", self.mul(self.mul(q, q), -1.0))


def _dir(az_deg, el_deg):
    a, e = math.radians(az_deg), math.radians(el_deg)
    return (math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))


def _angle_diff(g, az, centre_deg):
    """|az - centre| in radians, wrapped to [0, pi] (az is a socket, radians)."""
    d = g.sub(az, math.radians(centre_deg))
    s = g.math("SINE", g.mul(d, 0.5))
    return g.mul(g.math("ARCSINE", g.math("ABSOLUTE", s), clamp=False), 2.0)


# ---------------------------------------------------------------- the sky shader
def build_sky_nodes(nt, P, direction=None):
    """Build the procedural sky into node tree `nt` and return its colour
    socket (linear radiance).  `direction` is a socket with the world-space view
    direction (defaults to Texture Coordinate > Generated)."""
    g = G(nt)
    if direction is None:
        direction = g.node("ShaderNodeTexCoord").outputs["Generated"]
    D = g.vmath("NORMALIZE", direction)
    dx, dy, dz = g.sep(D)
    ez = g.math("MAXIMUM", dz, 0.0)
    az = g.math("ARCTAN2", dy, dx)

    # azimuthal light-pollution strength: rolling districts + the downtown lobe
    dt = P["downtown"]
    city = g.add(1.0, g.mul(g.sub(g.noise(g.comb(dx, dy, 0.0), 1.3, 3.0, 0.5, dims="3D"), 0.5), P["az_vary"] * 2.0))
    city = g.add(city, g.mul(g.gauss(_angle_diff(g, az, dt["az"]), math.radians(dt["width"])), dt["gain"]))
    glow = g.scale_color(g.ramp(ez, P["glow"]), city)

    # optional sun below the horizon (dusk / pre-dawn): lights the cloud base on its side
    if P.get("sun"):
        s = P["sun"]
        sdot = g.vmath("DOT_PRODUCT", D, _dir(s["az"], s["el"]))
        lobe = g.math("EXPONENT", g.mul(g.sub(sdot, 1.0), s["width"]))        # broad, ~cos lobe
        tight = g.math("EXPONENT", g.mul(g.sub(sdot, 1.0), s["horizon"] * 4))  # bright seam near the sun
        fall = g.math("EXPONENT", g.mul(ez, -s["horizon"]))                    # strongest low down
        sun_amt = g.mul(g.add(g.mul(lobe, fall), g.mul(tight, 0.6)), s["under"])
        glow = g.cadd(glow, g.scale_color(s["color"], sun_amt))

    # cloud-plane coordinates: hz never reaches 0, so the deck converges smoothly
    hz = g.add(ez, 0.035)
    px = g.math("DIVIDE", dx, hz)
    py = g.math("DIVIDE", dy, hz)
    # fade the cloud contrast into the horizon haze where the projection aliases
    near = g.smooth(ez, 0.0, 0.10)

    # level of detail: the plane projection packs ever more cloud into each
    # pixel towards the horizon; drop octaves there instead of aliasing
    lod = g.smooth(ez, 0.03, 0.45)
    detail = g.math("MULTIPLY_ADD", lod, 6.0, 1.0)

    # large-scale breaks in the deck
    b = P["breaks"]
    bn = g.noise(g.comb(px, py, 11.0), b["scale"], 3.0, 0.5)
    open_ = g.mul(g.smooth(bn, b["lo"], b["hi"], 1.0, 0.0), b["amount"])      # 1 = break

    # light direction in the cloud plane: towards the downtown glow, low on the horizon
    lx, ly = math.cos(math.radians(dt["az"])), math.sin(math.radians(dt["az"]))

    sky = g.ramp(ez, P["clear"])
    # stars, behind everything
    if P.get("stars"):
        st = P["stars"]
        vor = g.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
        g.put(vor.inputs["Vector"], D)
        g.put(vor.inputs["Scale"], 260.0)
        g.put(vor.inputs["Randomness"], 1.0)
        rnd = g.sep(vor.outputs["Color"])
        pick = g.smooth(rnd[0], 1.0 - st["density"], 1.0)                        # sparse
        size = g.smooth(vor.outputs["Distance"], 0.16, 0.0)
        twinkle = g.math("POWER", rnd[1], 3.0)
        vis = g.smooth(ez, 0.12, 0.45)
        star = g.mul(g.mul(g.mul(pick, size), g.add(0.15, twinkle)), g.mul(vis, st["gain"]))
        sky = g.cadd(sky, g.scale_color(_c(0.85, 0.9, 1.0), star))

    # moon (behind the clouds; they thin its disc and scatter a halo)
    moon_disc = moon_halo = None
    if P.get("moon"):
        m = P["moon"]
        mdot = g.vmath("DOT_PRODUCT", D, _dir(m["az"], m["el"]))
        r = math.radians(m["size"] / 2)
        moon_disc = g.smooth(mdot, math.cos(r * 1.15), math.cos(r * 0.9))
        aureole = g.math("EXPONENT", g.mul(g.sub(mdot, 1.0), 900.0))
        corona = g.math("EXPONENT", g.mul(g.sub(mdot, 1.0), 60.0))
        moon_halo = g.add(g.mul(aureole, 1.4), g.mul(corona, 0.22))
        sky = g.cadd(sky, g.scale_color(m["color"] + (1.0,), g.mul(moon_disc, m["gain"])))
        sky = g.cadd(sky, g.scale_color(m["color"] + (1.0,), g.mul(moon_halo, m["halo"] * 0.4)))

    # cloud layers, top first, each composited over what is above it
    total = 0.0
    low_dens = None
    for i, L in enumerate(sorted(P["layers"], key=lambda l: -l["h"])):
        ca, sa = math.cos(math.radians(L["wind"])), math.sin(math.radians(L["wind"]))
        # rotate into the wind frame and stretch along it
        u = g.add(g.mul(px, ca * L["h"]), g.mul(py, sa * L["h"]))
        v = g.add(g.mul(px, -sa * L["h"]), g.mul(py, ca * L["h"]))
        u = g.math("DIVIDE", u, L["stretch"])
        base = g.comb(u, v, L["seed"])
        # domain warp: low-frequency vector noise added to the coordinates
        warp = g.vmath("SUBTRACT", g.noise(base, L["scale"] * 0.35, 3.0, 0.5, color=True), (0.5, 0.5, 0.5))
        q = g.vmath("ADD", base, g.vmath("SCALE", warp, scale=L["warp"]))
        # big soft masses + a finer billow detail that fades out with distance
        big = g.noise(q, L["scale"], 2.5, 0.5, 2.0, 0.0)
        det = g.noise(q, L["scale"] * 3.2, g.mul(detail, 0.8), 0.58, 2.1, 0.0)
        n = g.add(big, g.mul(g.sub(det, 0.5), g.mul(lod, 0.5)))
        # light-gradient sample of the masses, offset towards the glow
        eps = 0.12 / L["scale"]
        q2 = g.vmath("ADD", q, (lx * eps / L["stretch"], ly * eps, 0.0))
        n2 = g.noise(q2, L["scale"], 2.5, 0.5, 2.0, 0.0)
        n2 = g.add(n2, g.mul(g.sub(det, 0.5), g.mul(lod, 0.12)))
        lit = g.math("MULTIPLY_ADD", g.sub(n, n2), P["shade"] * 3.0, 0.6)
        lit = g.math("MAXIMUM", g.math("MINIMUM", lit, 1.3), 0.15)
        dens = g.smooth(n, L["lo"], L["hi"])
        dens = g.mul(dens, g.sub(1.0, open_))
        # thicker cloud scatters more of the city light back down
        thick = g.add(0.35, g.mul(g.smooth(n, L["lo"], L["hi"] + 0.25), 0.9))
        bright = g.mul(g.mul(lit, thick), L["gain"])
        col = g.scale_color(glow, bright)
        if moon_halo is not None:            # the moon lights thin cloud around it
            col = g.cadd(col, g.scale_color(P["moon"]["color"] + (1.0,), g.mul(moon_halo, P["moon"]["halo"])))
        a = g.mul(g.mul(dens, L["alpha"]), near)
        sky = g.mix(a, sky, col)
        total = g.math("MAXIMUM", total, a) if i else a
        low_dens = dens

    # far flat stratus band near the horizon (between the haze and the deck)
    band = g.mul(g.smooth(ez, 0.16, 0.0), g.sub(1.0, near))
    sky = g.mix(g.mul(band, 0.85), sky, g.scale_color(glow, 0.8))

    # searchlights: thin beams in the hazy air under the deck
    for sl in P.get("searchlights", []):
        centre = g.add(math.radians(sl["az"]), g.mul(ez, math.radians(sl["lean"])))
        dd = g.sub(az, centre)
        dd = g.mul(g.math("ARCSINE", g.math("ABSOLUTE", g.math("SINE", g.mul(dd, 0.5)))), 2.0)
        beam = g.gauss(dd, math.radians(sl["width"]) * 0.5)
        beam = g.mul(beam, g.smooth(ez, sl["top"], 0.0))
        sky = g.cadd(sky, g.scale_color(_c(0.75, 0.82, 1.0), g.mul(beam, sl["gain"])))
        # its spot on the cloud base
        top = sl["top"]
        sp = _dir(sl["az"] + sl["lean"] * top, math.degrees(math.asin(top)))
        spot = g.math("EXPONENT", g.mul(g.sub(g.vmath("DOT_PRODUCT", D, sp), 1.0), 600.0))
        sky = g.cadd(sky, g.scale_color(_c(0.75, 0.82, 1.0), g.mul(g.mul(spot, low_dens), sl["gain"] * 0.8)))

    # MERIDIAN eye: a giant hologram's glow on the cloud base (cyan iris ring, red pupil)
    if P.get("eye"):
        e = P["eye"]
        # the eye sits on the deck at (az, el); x runs along the horizon there
        dist = 1.0 / math.tan(math.radians(e["el"]))
        ca, sa = math.cos(math.radians(e["az"])), math.sin(math.radians(e["az"]))
        rx, ry = g.sub(px, ca * dist), g.sub(py, sa * dist)
        ex = g.add(g.mul(rx, -sa), g.mul(ry, ca))           # tangential
        ey = g.add(g.mul(rx, ca), g.mul(ry, sa))            # radial
        R = e["r"]
        # almond: |ey| < 0.45 R (1 - (ex/R)^2), blurred by the cloud
        lid = g.math("MAXIMUM", g.math("MULTIPLY_ADD", g.mul(g.math("DIVIDE", ex, R), g.math("DIVIDE", ex, R)), -1.0, 1.0), 0.0)
        t = g.math("DIVIDE", g.math("ABSOLUTE", ey), g.add(g.mul(lid, 0.45 * R), 0.02))
        wash = g.mul(g.smooth(t, 1.6, 0.6), g.smooth(g.math("ABSOLUTE", ex), R, R * 0.7))
        rr = g.math("SQRT", g.add(g.mul(ex, ex), g.mul(ey, ey)))
        ring = g.gauss(g.sub(rr, R * 0.26), R * 0.08)
        pupil = g.gauss(rr, R * 0.1)
        on_cloud = g.mul(g.add(0.3, g.mul(low_dens, 0.7)), near)
        eye = g.cadd(g.scale_color(e["color"], g.add(g.mul(wash, 0.35), g.mul(ring, 0.5))),
                     g.scale_color(e["pupil"], g.mul(pupil, 0.6)))
        sky = g.cadd(sky, g.scale_color(eye, g.mul(on_cloud, e["gain"] * 0.25)))

    # horizon haze, then the dark ground below
    haze_amt = g.mul(g.math("EXPONENT", g.mul(ez, -1.0 / P["haze_height"])), P["haze_amount"])
    sky = g.mix(haze_amt, sky, g.scale_color(P["haze"], city))
    below = g.smooth(dz, 0.01, -0.09)
    sky = g.mix(below, sky, g.scale_color(P["ground"], city))
    return sky


def sky_world(name, preset):
    """A world whose background is the procedural sky (no volume)."""
    P = PRESETS[preset]
    w = bpy.data.worlds.get(name) or bpy.data.worlds.new(name)
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    col = build_sky_nodes(nt, P)
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(col, bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return w


# ---------------------------------------------------------------- render helpers
def _cycles(sc, samples):
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dev
            prefs.get_devices()
            if any(d.type == dev for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == dev
                sc.cycles.device = "GPU"
                break
        except TypeError:
            continue
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.use_denoising = False


def _pano_scene(name, w, res, samples):
    sc = bpy.data.scenes.get(name) or bpy.data.scenes.new(name)
    sc.world = w
    _cycles(sc, samples)
    cam = bpy.data.objects.get(name + "_cam")
    if cam is None:
        cd = bpy.data.cameras.new(name + "_cam")
        cam = bpy.data.objects.new(name + "_cam", cd)
        sc.collection.objects.link(cam)
    cam.data.type = "PANO"
    cam.data.panorama_type = "EQUIRECTANGULAR"
    cam.location = (0, 0, 0)
    # forward = Blender +Y -> image centre = glTF -Z (Godot / Pigment convention)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    return sc


def save_float(sc, path):
    s = sc.render.image_settings
    s.file_format = "HDR"
    s.color_mode = "RGB"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.data.images["Render Result"].save_render(path, scene=sc)


def save_preview(sc, path, exposure, width=1600):
    s = sc.render.image_settings
    s.file_format = "PNG"
    s.color_mode = "RGB"
    s.compression = 95
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    sc.view_settings.exposure = exposure
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".full.png"
    bpy.data.images["Render Result"].save_render(tmp, scene=sc)
    img = bpy.data.images.load(tmp)
    if img.size[0] > width:
        img.scale(width, width // 2)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    os.remove(tmp)


def hdr_path(preset, res="2k", folder=None):
    return os.path.join(folder or SKY_DIR, f"{preset}_{res}.hdr")


def bake(preset, res="2k", samples=16, preview=True, folder=None):
    P = PRESETS[preset]
    w = sky_world("SkyProc_" + preset, preset)
    sc = _pano_scene("SkyBake", w, RES[res], samples)
    t = time.time()
    bpy.ops.render.render(scene=sc.name)
    out = hdr_path(preset, res, folder)
    save_float(sc, out)
    print(f"sky: {preset} {res} -> {out} ({os.path.getsize(out) / 1e6:.1f} MB, {time.time() - t:.1f}s)")
    if preview:
        save_preview(sc, os.path.join(DOC_DIR, f"{preset}_equirect.png"), math.log2(P["exposure"]))
        view(preset, sc)
    return out


def view(preset, sc=None, az=None, pitch=16.0, lens=12.0, path=None):
    """A wide perspective look at the sky (what a street-level camera sees)."""
    P = PRESETS[preset]
    sc = sc or _pano_scene("SkyBake", sky_world("SkyProc_" + preset, preset), RES["2k"], 16)
    cam = sc.camera
    az = P["downtown"]["az"] if az is None else az
    old = (cam.data.type, tuple(cam.rotation_euler), sc.render.resolution_x, sc.render.resolution_y)
    cam.data.type = "PERSP"
    cam.data.lens = lens
    cam.rotation_euler = (math.radians(90 + pitch), 0, math.radians(az - 90))
    sc.render.resolution_x, sc.render.resolution_y = 1600, 800
    bpy.ops.render.render(scene=sc.name)
    save_preview(sc, path or os.path.join(DOC_DIR, f"{preset}_view.png"), math.log2(P["exposure"]))
    cam.data.type = old[0]
    cam.rotation_euler = old[1]
    sc.render.resolution_x, sc.render.resolution_y = old[2], old[3]


# ---------------------------------------------------------------- shared world setup
def apply_sky(scene, preset=DEFAULT, hdr=None, strength=None, camera_strength=1.0, fog=True,
              fog_bounds=None, key_light=True, procedural=False, res="2k"):
    """Make `scene`'s world the baked sky of `preset`.

    hdr              path to the equirect (default assets/sky/<preset>_<res>.hdr; if missing
                     the procedural shader is used directly)
    strength         world light on the scene (default: the preset's `world_light`, low so
                     street lamps and neon dominate); camera rays always see `camera_strength`
    fog              add / update the "SkyFog" volume box (a box, not a world volume: an
                     infinite world volume would swallow the sky).  fog_bounds = ((x0,y0,z0),
                     (x1,y1,z1)); default: the bounding box of the scene's meshes + 60 m
    key_light        point the "Moon" sun lamp (created if missing) at the preset's key
                     (moon / low sun) with its colour and energy
    Returns the world.
    """
    P = PRESETS[preset]
    strength = P["world_light"] if strength is None else strength
    w = bpy.data.worlds.get("Sky") or bpy.data.worlds.new("Sky")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    path = hdr or hdr_path(preset, res)
    if procedural or not os.path.isfile(path):
        if not procedural:
            print(f"sky: {path} missing, using the procedural sky (bake with tools/sky/make_sky.py)")
        col = build_sky_nodes(nt, P)
    else:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        mapping = nt.nodes.new("ShaderNodeMapping")
        # glTF-convention equirect (centre = Blender +Y) -> Blender's (centre = +X)
        mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(-90.0))
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.interpolation = "Cubic"
        img = bpy.data.images.load(os.path.abspath(path), check_existing=True)
        env.image = img
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        col = env.outputs["Color"]
    # camera rays see the sky as baked; everything else is lit at `strength`
    lp = nt.nodes.new("ShaderNodeLightPath")
    mixs = nt.nodes.new("ShaderNodeMath")
    mixs.operation = "MULTIPLY_ADD"     # is_camera * (cam - light) + light
    mixs.inputs[1].default_value = camera_strength - strength
    mixs.inputs[2].default_value = strength
    nt.links.new(lp.outputs["Is Camera Ray"], mixs.inputs[0])
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(col, bg.inputs["Color"])
    nt.links.new(mixs.outputs[0], bg.inputs["Strength"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    w["sky_preset"] = preset
    scene.world = w
    if fog:
        _fog_box(scene, P["fog"], fog_bounds)
    if key_light and P.get("key"):
        k = P["key"]
        mo = bpy.data.objects.get("Moon")
        if mo is None or mo.type != "LIGHT":
            mo = bpy.data.objects.new("Moon", bpy.data.lights.new("Moon", "SUN"))
            scene.collection.objects.link(mo)
        mo.data.energy = k["energy"]
        mo.data.color = k["color"]
        mo.data.angle = math.radians(2.0)
        # the sun lamp shines along its -Z: point it from the key direction
        from mathutils import Vector
        d = Vector(_dir(k["az"], max(k["el"], 1.0)))
        mo.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    return w


def _fog_box(scene, F, bounds=None):
    if bounds is None:
        lo = [1e9] * 3
        hi = [-1e9] * 3
        for o in scene.objects:
            if o.type != "MESH" or o.name == "SkyFog" or not o.visible_get():
                continue
            for c in o.bound_box:
                p = o.matrix_world @ __import__("mathutils").Vector(c)
                for i in range(3):
                    lo[i] = min(lo[i], p[i])
                    hi[i] = max(hi[i], p[i])
        if lo[0] > hi[0]:
            lo, hi = [-200, -200, -10], [200, 200, 150]
        m = 60.0
        bounds = ((lo[0] - m, lo[1] - m, lo[2] - 5), (hi[0] + m, hi[1] + m, max(hi[2] + 40, lo[2] + 120)))
    (x0, y0, z0), (x1, y1, z1) = bounds
    me = bpy.data.meshes.get("SkyFog") or bpy.data.meshes.new("SkyFog")
    me.clear_geometry()
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f)
    me.update()
    ob = bpy.data.objects.get("SkyFog")
    if ob is None:
        ob = bpy.data.objects.new("SkyFog", me)
        scene.collection.objects.link(ob)
    ob.display_type = "WIRE"
    ob.hide_select = True
    try:
        ob.visible_shadow = False
    except AttributeError:
        pass
    mat = bpy.data.materials.get("SkyFog") or bpy.data.materials.new("SkyFog")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = F["color"]
    vol.inputs["Emission Color"].default_value = F["emission"]
    vol.inputs["Emission Strength"].default_value = 1.0
    vol.inputs["Anisotropy"].default_value = 0.35
    # denser near the ground: density * exp(-(z - z0) / 35 m)
    tc = nt.nodes.new("ShaderNodeNewGeometry")
    sepn = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Position"], sepn.inputs[0])
    m1 = nt.nodes.new("ShaderNodeMath")
    m1.operation = "MULTIPLY_ADD"
    m1.inputs[1].default_value = -1.0 / 35.0
    m1.inputs[2].default_value = z0 / 35.0
    nt.links.new(sepn.outputs[2], m1.inputs[0])
    m2 = nt.nodes.new("ShaderNodeMath")
    m2.operation = "EXPONENT"
    nt.links.new(m1.outputs[0], m2.inputs[0])
    m3 = nt.nodes.new("ShaderNodeMath")
    m3.operation = "MULTIPLY_ADD"
    m3.inputs[1].default_value = F["density"] * 0.7
    m3.inputs[2].default_value = F["density"] * 0.3
    nt.links.new(m2.outputs[0], m3.inputs[0])
    nt.links.new(m3.outputs[0], vol.inputs["Density"])
    # emission scales with density too (glowing city haze)
    nt.links.new(m3.outputs[0], vol.inputs["Emission Strength"])
    vol.inputs["Emission Color"].default_value = tuple(c / max(F["density"], 1e-6) for c in F["emission"][:3]) + (1.0,)
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    me.materials.clear()
    me.materials.append(mat)
    return ob


# ---------------------------------------------------------------- orientation check
def check(preset, res="1k"):
    """Render the procedural sky and the baked HDR through apply_sky() with the
    same Blender camera and compare: verifies the bake/apply orientation."""
    import numpy as np
    sc = _pano_scene("SkyCheck", sky_world("SkyProc_" + preset, preset), RES[res], 4)
    cam = sc.camera
    cam.rotation_euler = (math.radians(80), 0, math.radians(37))     # arbitrary
    sc.render.image_settings.file_format = "HDR"
    a_path = os.path.join(bpy.app.tempdir, "a.hdr")
    b_path = os.path.join(bpy.app.tempdir, "b.hdr")
    bpy.ops.render.render(scene=sc.name)
    bpy.data.images["Render Result"].save_render(a_path, scene=sc)
    apply_sky(sc, preset, fog=False, key_light=False, strength=1.0)
    bpy.ops.render.render(scene=sc.name)
    bpy.data.images["Render Result"].save_render(b_path, scene=sc)
    A = np.array(bpy.data.images.load(a_path).pixels[:]).reshape(-1, 4)[:, :3]
    B = np.array(bpy.data.images.load(b_path).pixels[:]).reshape(-1, 4)[:, :3]
    err = float(np.abs(A - B).mean() / max(A.mean(), 1e-9))
    print(f"sky check {preset}: relative mean abs error {err:.4f} (mean {A.mean():.4f} vs {B.mean():.4f})")
    return err


def main(args):
    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            return args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else True
        return default
    presets = opt("--presets", ",".join(PRESETS)).split(",")
    res = opt("--res", "2k")
    samples = int(opt("--samples", 16))
    for p in presets:
        bake(p, res, samples, preview=not opt("--no-preview") and res == "2k")
    if opt("--check"):
        for p in presets:
            check(p)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
