"""Build the Pigment icon SVGs from geometry.

The mark is a matte graphite ball with one glossy orange brush stroke wrapped
round it: an unpainted model with Pigment's first stroke on it. The stroke is
real geometry on the sphere: a band of bristle strips laid along a tilted
great circle, each small patch lit (diffuse plus a clearcoat specular) for a
light from the top left, with a ragged dry-brush end where the stroke lifts.

    python tools/branding/make_svgs.py     (make_icons.py runs this first)

Writes, in assets/branding:
    pigment-icon.svg        master, used from 48 px up (and the in-app logo)
    pigment-icon-small.svg  16-32 px: fewer, wider bristles, lighter ball, stronger rim
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "branding"

PAINT = (240, 138, 60)  # design-system accent #F08A3C
LIGHT = (-0.5, 0.62, 0.6)  # towards the light, view space, y up, z to the viewer
VIEW = (0.0, 0.0, 1.0)


@dataclass
class Spec:
    name: str
    cx: float = 128.0
    cy: float = 128.0
    r: float = 108.0
    band: float = 21.0        # half-width of the stroke, degrees
    bristles: int = 11        # strips across the stroke
    a_end: float = -62.0      # where the stroke lifts off (front left), degrees along it
    ragged: float = 44.0      # how far the dry-brush ends spread, degrees
    roll: float = -16.0       # the stroke's slant across the ball
    pitch: float = -14.0      # how far its circle tips towards the viewer (arched)
    lift: float = -20.0       # the stroke sits this far below the circle's equator
    ball: tuple = ("#767B84", "#3A3D44", "#16171A")  # graphite: lit, mid, shadow
    rim: float = 0.022        # rim light width, of r
    rim_alpha: float = 0.35
    jitter: float = 0.07      # brightness spread between bristles
    seed: int = 7


def norm(v):
    m = math.sqrt(sum(c * c for c in v))
    return tuple(c / m for c in v)


L = norm(LIGHT)
H = norm(tuple(a + b for a, b in zip(L, VIEW)))


def band_point(a, b, s: Spec):
    """A point at angle `a` along the stroke and `b` across it, on the unit sphere, view space."""
    a, b = math.radians(a), math.radians(b + s.lift)
    x, y, z = math.cos(b) * math.sin(a), math.sin(b), math.cos(b) * math.cos(a)
    p = math.radians(s.pitch)  # tip the circle about x
    y, z = y * math.cos(p) - z * math.sin(p), y * math.sin(p) + z * math.cos(p)
    r = math.radians(s.roll)  # slant it about the view axis
    x, y = x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)
    return x, y, z


def scr(p, s: Spec):
    return s.cx + s.r * p[0], s.cy - s.r * p[1]


def lit(n, base, k_jit):
    d = max(0.0, sum(a * b for a, b in zip(n, L)))
    sp = max(0.0, sum(a * b for a, b in zip(n, H))) ** 24 * 0.55  # clearcoat
    k = (0.56 + 0.58 * d) * k_jit
    c = [min(255.0, ch * k + 255 * sp) for ch in base]
    return "#%02X%02X%02X" % tuple(int(v) for v in c)


def stroke(s: Spec) -> str:
    rng = random.Random(s.seed)
    polys = []
    db = 2 * s.band / s.bristles
    for i in range(s.bristles):
        b0 = -s.band + i * db
        jit = 1 + rng.uniform(-s.jitter, s.jitter)
        # each bristle stops at its own place: the dry-brush end
        edge = abs(i + 0.5 - s.bristles / 2) / (s.bristles / 2)  # 0 in the middle, 1 at the sides
        end = s.a_end + s.ragged * (0.55 * edge ** 1.5 + 0.45 * rng.random())
        a, step = end, 1.5
        while a < 110:
            a1 = min(a + step, 110)
            c = band_point((a + a1) / 2, b0 + db / 2, s)
            if c[2] > -0.05:
                quad = [band_point(a, b0, s), band_point(a1, b0, s), band_point(a1, b0 + db, s), band_point(a, b0 + db, s)]
                if a == end:  # round the tip of the bristle
                    quad = [band_point(a + step * 0.5, b0, s), band_point(a1, b0, s), band_point(a1, b0 + db, s),
                            band_point(a + step * 0.5, b0 + db, s), band_point(a, b0 + db / 2, s)]
                col = lit(c, PAINT, jit)
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (scr(p, s) for p in quad))
                polys.append((c[2], f'<polygon points="{pts}" fill="{col}" stroke="{col}" stroke-width="0.7" stroke-linejoin="round"/>'))
            a = a1
    polys.sort(key=lambda t: t[0])
    return "\n    ".join(p for _, p in polys)


def edge_shadow(s: Spec) -> str:
    """A soft shadow the paint's thickness throws on the ball, just below the stroke."""
    pts = []
    for k in range(0, 61):
        a = s.a_end + (110 - s.a_end) * k / 60
        p = band_point(a, -s.band - 1.5, s)
        if p[2] > 0:
            pts.append(scr(p, s))
    if len(pts) < 2:
        return ""
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    return f'<path d="{d}" fill="none" stroke="#000" stroke-opacity="0.3" stroke-width="{0.03 * s.r:.1f}" stroke-linecap="round"/>'


def svg(s: Spec) -> str:
    cx, cy, r = s.cx, s.cy, s.r
    lit_c, mid_c, dark_c = s.ball
    rr = r - s.rim * r / 2
    rim_a0, rim_a1 = math.radians(-15), math.radians(105)  # screen angles, y down: the lower right
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">',
           f"  <!-- Pigment {s.name}. Generated by tools/branding/make_svgs.py: edit that, not this. -->",
           "  <defs>",
           f'    <clipPath id="ball"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>',
           f'    <radialGradient id="graphite" gradientUnits="userSpaceOnUse" cx="{cx - 0.4 * r:.1f}" cy="{cy - 0.45 * r:.1f}" r="{1.5 * r:.1f}">'
           f'<stop offset="0" stop-color="{lit_c}"/><stop offset="0.45" stop-color="{mid_c}"/><stop offset="1" stop-color="{dark_c}"/></radialGradient>',
           f'    <radialGradient id="sheen" gradientUnits="userSpaceOnUse" cx="{cx - 0.42 * r:.1f}" cy="{cy - 0.5 * r:.1f}" r="{0.42 * r:.1f}">'
           '<stop offset="0" stop-color="#fff" stop-opacity="0.22"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
           "  </defs>",
           f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#graphite)"/>',
           f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#sheen)"/>',
           '  <g clip-path="url(#ball)">',
           f"    {edge_shadow(s)}",
           f"    {stroke(s)}",
           "  </g>",
           # rim light on the shadow side: keeps the dark ball off a dark taskbar
           f'  <path d="M{cx + rr * math.cos(rim_a0):.1f} {cy + rr * math.sin(rim_a0):.1f} A{r - s.rim * r / 2:.1f} {r - s.rim * r / 2:.1f} 0 0 1 {cx + rr * math.cos(rim_a1):.1f} {cy + rr * math.sin(rim_a1):.1f}" '
           f'fill="none" stroke="#C9CED6" stroke-opacity="{s.rim_alpha}" stroke-width="{s.rim * r:.1f}" stroke-linecap="round"/>',
           f'  <circle cx="{cx}" cy="{cy}" r="{r - 0.5}" fill="none" stroke="#000" stroke-opacity="0.45" stroke-width="1.5"/>',
           "</svg>\n"]
    return "\n".join(out)


SPECS = {
    "pigment-icon.svg": Spec("icon (master)"),
    "pigment-icon-small.svg": Spec("icon (16-32 px)", r=122, band=24, bristles=4, ragged=18, a_end=-58, jitter=0.05,
                                   ball=("#8C919A", "#4A4E56", "#202226"), rim=0.05, rim_alpha=0.55),
}


def main() -> None:
    for name, spec in SPECS.items():
        (OUT / name).write_text(svg(spec), encoding="utf-8", newline="\n")
    for old in ("pigment-mark.svg", "pigment-mark-small.svg"):
        (OUT / old).unlink(missing_ok=True)
    print("wrote " + ", ".join(SPECS))


if __name__ == "__main__":
    main()
