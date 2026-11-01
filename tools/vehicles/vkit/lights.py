"""Light designs: headlamps and tail lamps built from elements (spec items `headlights`,
`taillights`). A design is data: a housing, a list of elements (chrome reflector bowls with
bulbs, projector lenses, rectangular reflectors, LED bars), a DRL strip and an indicator for
the front; lamp segments (brake / indicator / reverse, horizontal bars or vertical stacks), a
chrome back plate, divider fins, ribs and a third brake light for the rear.

The lenses that cover them are cut from the body shell (`V.panels.lenses`), so a design and
its aperture must agree on the rectangle.
"""
import bmesh

from . import panels as P
from .geom import bm_sphere
from .shapes import SIDES, box, lathe, obj, rot_x


def _reflector(out, side, sx, k, e, z, yk):
    r = e.r
    xc = e.x
    prof = [(0.012, 0.075), (r * 0.55, 0.055), (r * 0.85, 0.028), (r, 0.0), (r + 0.004, -0.004)]
    bowl = lathe(f"headlight_reflector_{side}{k}", prof, (sx * xc, yk + 0.028, z), "Y", e.get("seg", 20))
    out.append((bowl.name, "chrome", bowl))
    bm = bmesh.new()
    bm_sphere(bm, (sx * xc, yk + 0.058, z), 0.014, 8, 5)
    bulb = obj(f"headlight_bulb_{side}{k}", bm)
    out.append((bulb.name, "emitter_head", bulb))
    if e.get("projector"):
        s = r / 0.052
        sh = lathe(f"headlight_shroud_{side}", [(0.030 * s, 0.0), (0.040 * s, 0.004), (0.041 * s, 0.030), (0.034 * s, 0.034)],
                   (sx * xc, yk + 0.010, z), "Y", 20)
        out.append((sh.name, "black_trim", sh))
        bm = bmesh.new()
        bm_sphere(bm, (sx * xc, yk + 0.016, z), 0.031 * s, 16, 10, scale=(1, 0.55, 1))
        pl = obj(f"headlight_projector_{side}", bm)
        out.append((pl.name, "lens_clear", pl))
    if e.get("ring"):
        # an LED halo ring round the bowl
        rg = lathe(f"headlight_ring_{side}{k}", [(r + 0.004, -0.002), (r + 0.011, -0.002), (r + 0.011, 0.006), (r + 0.004, 0.006)],
                   (sx * xc, yk + 0.012, z), "Y", 28)
        out.append((rg.name, "emitter_head", rg))


def _rect_reflector(out, side, sx, k, e, z, yk):
    """A rectangular multi-facet reflector: a chrome back with stepped facets and a bulb."""
    w, h = e.w, e.h
    back = box(f"headlight_rect_{side}{k}", (sx * e.x, yk + 0.05, z), (w, 0.01, h), bevel=0.004)
    out.append((back.name, "chrome", back))
    nf = e.get("facets", 4)
    for i in range(nf):
        xi = sx * (e.x - w / 2 + (i + 0.5) * w / nf)
        f = box(f"headlight_facet_{side}{k}{i}", (xi, yk + 0.038, z), (w / nf - 0.006, 0.016, h - 0.012), bevel=0.005,
                rot=rot_x(0))
        out.append((f.name, "chrome", f))
    bm = bmesh.new()
    bm_sphere(bm, (sx * e.x, yk + 0.025, z), e.get("bulb", 0.014), 8, 5)
    bulb = obj(f"headlight_bulb_{side}{k}", bm)
    out.append((bulb.name, "emitter_head", bulb))


def _led_bar(out, side, sx, k, e, z, yk, group="emitter_head", prefix="headlight_led"):
    b = box(f"{prefix}_{side}{k}", (sx * e.x, yk + e.get("depth", 0.012), z), (e.w, 0.012, e.h), bevel=min(0.004, e.h * 0.3))
    out.append((b.name, e.get("group", group), b))


ELEMENTS = {"reflector": _reflector, "rect": _rect_reflector, "led": _led_bar}


def headlights(p):
    """p: {x, z, housing: {size, back, ray_z}, elements: [...], drl: {z, size, x?}, indicator: {x, z, size}}"""
    out = []
    for sx, side in SIDES:
        if p.get("housing"):
            hs = p.housing
            yb = P.front_face_y(sx * p.x, hs.get("ray_z", p.z))
            h = box(f"headlight_housing_{side}", (sx * p.x, yb + hs.back, p.z), hs.size, bevel=0.01)
            out.append((h.name, "black_trim", h))
        for k, e in enumerate(p.elements):
            z = e.get("z", p.z)
            yk = P.front_face_y(sx * e.x, z)
            ELEMENTS[e.type](out, side, sx, k, e, z, yk)
        if p.get("drl"):
            d = p.drl
            x = d.get("x", p.x)
            strip = box(f"headlight_drl_{side}", (sx * x, P.front_face_y(sx * x, d.z) + d.get("depth", 0.016), d.z), d.size)
            out.append((strip.name, "emitter_head", strip))
        if p.get("indicator"):
            d = p.indicator
            yi = P.front_face_y(sx * d.x, d.z)
            ib = box(f"indicator_F_{side}", (sx * d.x, yi + d.get("depth", 0.03), d.z), d.size, bevel=0.004)
            out.append((ib.name, "emitter_amber", ib))
    return out


def taillights(p):
    """p: {zc, housing: {w, d, h, back} (one across the tail) or {sides, x, w, d, h, back},
    segments: [{name, x, w, group, z?, h?}] per side, reflector: {x, w, h?}, fins: [x], ribs: {n, w, pitch},
    third: {y, roof_y, size, tilt, dz?}}"""
    out = []
    zc = p.zc
    hs = p.get("housing")
    if hs and not hs.get("sides"):
        yb = P.rear_face_y(0.0, zc)
        h = box("taillight_housing", (0, yb - hs.back, zc), (hs.w, hs.d, hs.h), bevel=0.01)
        out.append((h.name, "black_trim", h))
    elif hs:
        for sx, side in SIDES:
            z = hs.get("z", zc)
            yb = P.rear_face_y(sx * hs.x, z)
            h = box(f"taillight_housing_{side}", (sx * hs.x, yb - hs.back, z), (hs.w, hs.d, hs.h), bevel=0.01)
            out.append((h.name, "black_trim", h))
    segs = []
    for sx, side in SIDES:
        for s in p.segments:
            segs.append((f"{s.name}_{side}", sx * s.x, s.w, s.group, s.get("z", zc), s.get("h", 0.095), s.get("depth", 0.035)))
    for nm, xc, w, grp, z, hh, dp in segs:
        y = P.rear_face_y(xc, z)
        e = box(nm, (xc, y - dp, z), (w, 0.03, hh), bevel=0.004)
        out.append((nm, grp, e))
    if p.get("reflector") or p.get("fins"):
        for sx, side in SIDES:
            if p.get("reflector"):
                r = p.reflector
                y = P.rear_face_y(sx * r.x, r.get("z", zc))
                bp = box(f"tail_reflector_{side}", (sx * r.x, y - 0.075, r.get("z", zc)), (r.w, 0.008, r.get("h", 0.10)))
                out.append((bp.name, "chrome", bp))
            for xf in p.get("fins", []):
                fz = p.get("fin_z", zc)
                yf = P.rear_face_y(sx * xf, fz)
                fin = box(f"tail_fin_{side}_{int(xf * 1000)}", (sx * xf, yf - 0.045, fz), (0.008, 0.06, p.get("fin_h", 0.10)))
                out.append((fin.name, "black_trim", fin))
    if p.get("ribs"):
        rb = p.ribs
        for i in range(rb.n):
            z = zc - rb.get("start", 0.036) + i * rb.get("pitch", 0.024)
            y = P.rear_face_y(0.0, z)
            r = box(f"tail_center_rib_{i}", (0, y - 0.022, z), (rb.w, 0.012, 0.012), bevel=0.003)
            out.append((r.name, rb.get("group", "emitter_tail"), r))
    if p.get("third"):
        t = p.third
        z3 = P.z_roof(t.roof_y) - 0.03 + t.get("dz", 0.0)
        s3 = box("tail_third_brake", (0, t.y, z3 - 0.01), t.size, bevel=0.006, rot=rot_x(t.tilt))
        out.append((s3.name, "emitter_tail", s3))
    return out
