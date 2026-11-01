"""Drawing kit for the ad decals (tools/make_ad_decals.py).

Everything is PIL shapes, gradients and type: no photos, no downloaded imagery.
People appear only as stylised, fully clothed adult silhouettes (evening gowns,
suits, legs in stockings and heels below a skirt hem, lips, gloved hands, a
dress form wearing a corset).  Coordinates are in design units; `Art` scales
them by the supersampling factor and the result is downsampled on `out()`.
"""
import math
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_decals import ARIAL_B, BAHN, BLACK, IMPACT, JP_BOLD, JP_REG, MONO, SS, STENCIL, font, graffiti  # noqa: E402,F401

SERIF = ("georgiab.ttf", "timesbd.ttf", "arialbd.ttf")
SERIF_I = ("georgiaz.ttf", "georgiai.ttf", "timesbi.ttf", "arialbi.ttf")
SCRIPT = ("segoesc.ttf", "segoescb.ttf", "georgiai.ttf")
SCRIPT_B = ("segoescb.ttf", "segoesc.ttf", "georgiaz.ttf")
COND = ("bahnschrift.ttf", "arialnb.ttf", "arialbd.ttf")
MINCHO = ("yumindb.ttf", "YuMinchoDemibold.ttf", "msmincho.ttc", "YuGothB.ttc")
JP_HEAVY = ("YuGothB.ttc", "meiryob.ttc", "msgothic.ttc")

# formats: (design width, design height); `out()` scales the long side to 1024
FMT = {
    "billboard": (1600, 800),     # 2:1, rooftop / wall / crown billboards
    "poster": (700, 1000),        # street posters (wheat-paste clusters)
    "flyer": (600, 850),          # photocopied flyers
    "sticker": (500, 700),        # call cards and stickers
    "lightbox": (640, 1016),      # bus-stop lightbox (same as assets/decals/props/ad_*)
    "holo": (300, 1040),          # holo-pylon frames
    "kiosk": (680, 1040),         # data-kiosk screens
    "banner": (300, 1400),        # vertical lit banner (blade sign faces)
    "window": (1200, 600),        # vinyl window lettering (transparent)
}


def has_wide(txt):
    """Characters Bahnschrift / Arial lack (CJK, hearts, stars, phones, arrows): use Yu Gothic."""
    return any(ord(c) > 0x218F and c not in "™" for c in txt)


_FONTS = {}


def lf(txt, size, f=None):
    f = (JP_BOLD if f not in (JP_REG, MINCHO) else f) if has_wide(txt) else (f or BAHN)
    key = (f, max(4, int(size)))
    if key not in _FONTS:
        _FONTS[key] = font(*key)
    return _FONTS[key]


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def rgba(c, a=255):
    return tuple(c[:3]) + (a,)


class Art:
    """A supersampled RGBA canvas with drawing in design units."""

    def __init__(self, fmt_or_size, bg=None):
        W, H = FMT[fmt_or_size] if isinstance(fmt_or_size, str) else fmt_or_size
        self.W, self.H, self.s = W, H, SS
        self.img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        if bg is not None:
            self.rect((0, 0, W, H), fill=rgba(bg, bg[3] if len(bg) > 3 else 255))

    # ---------------------------------------------------------------- basics
    def S(self, v):
        return v * self.s

    def pts(self, pts):
        return [(x * self.s, y * self.s) for x, y in pts]

    def box(self, b):
        return [b[0] * self.s, b[1] * self.s, b[2] * self.s, b[3] * self.s]

    def rect(self, b, fill=None, outline=None, width=0, r=0):
        if r:
            self.d.rounded_rectangle(self.box(b), radius=r * self.s, fill=fill, outline=outline, width=int(width * self.s))
        else:
            self.d.rectangle(self.box(b), fill=fill, outline=outline, width=int(width * self.s))

    def ell(self, b, fill=None, outline=None, width=0):
        self.d.ellipse(self.box(b), fill=fill, outline=outline, width=int(width * self.s))

    def circle(self, cx, cy, r, fill=None, outline=None, width=0):
        self.ell((cx - r, cy - r, cx + r, cy + r), fill, outline, width)

    def poly(self, pts, fill=None, outline=None, width=0):
        self.d.polygon(self.pts(pts), fill=fill, outline=outline, width=int(width * self.s) if outline else 0)

    def line(self, pts, fill, width, joint="curve"):
        self.d.line(self.pts(pts), fill=fill, width=max(1, int(width * self.s)), joint=joint)

    def arc(self, b, a0, a1, fill, width):
        self.d.arc(self.box(b), a0, a1, fill=fill, width=max(1, int(width * self.s)))

    def text(self, xy, txt, size, fill, f=None, anchor="mm", stroke=0, stroke_fill=None, spacing=0):
        fo = lf(txt, size * self.s, f)
        x, y = xy[0] * self.s, xy[1] * self.s
        # safety net: shrink a line that would run off the canvas (keep a margin)
        m = 0.03 * self.W * self.s
        for _ in range(40):
            tw = fo.getlength(txt) + (spacing * self.s * (len(txt) - 1) if spacing else 0)
            room = {"l": self.W * self.s - m - x, "m": 2 * min(x - m, self.W * self.s - m - x), "r": x - m}[anchor[0]]
            if tw <= room or size < 6:
                break
            size *= 0.94
            fo = lf(txt, size * self.s, f)
        if spacing:
            # letter-spaced: lay the glyphs out by hand, honouring the horizontal anchor
            widths = [fo.getlength(c) for c in txt]
            total = sum(widths) + spacing * self.s * (len(txt) - 1)
            x0 = x - (total / 2 if anchor[0] == "m" else total if anchor[0] == "r" else 0)
            for c, w in zip(txt, widths):
                self.d.text((x0, y), c, font=fo, fill=fill, anchor="l" + anchor[1], stroke_width=int(stroke * self.s), stroke_fill=stroke_fill)
                x0 += w + spacing * self.s
            return
        self.d.text((x, y), txt, font=fo, fill=fill, anchor=anchor, stroke_width=int(stroke * self.s), stroke_fill=stroke_fill)

    def fit(self, b, txt, fill, f=None, anchor="mm", stroke=0, stroke_fill=None, max_size=None, spacing=0):
        """Largest size at which `txt` fits box b = (x0, y0, x1, y1); drawn anchored in the box."""
        x0, y0, x1, y1 = b
        w, h = (x1 - x0) * self.s, (y1 - y0) * self.s
        size = int(max_size * self.s) if max_size else int(h * 1.2)
        while size > 6:
            fo = lf(txt, size, f)
            bb = self.d.textbbox((0, 0), txt, font=fo, stroke_width=int(stroke * self.s))
            tw = bb[2] - bb[0] + (spacing * self.s * (len(txt) - 1) if spacing else 0)
            if tw <= w and bb[3] - bb[1] <= h:
                break
            size -= max(1, size // 24)
        ax = {"l": x0, "m": (x0 + x1) / 2, "r": x1}[anchor[0]]
        ay = {"t": y0, "m": (y0 + y1) / 2, "b": y1, "s": y1, "a": y0}[anchor[1]]
        self.text((ax, ay), txt, size / self.s, fill, f, anchor, stroke, stroke_fill, spacing)
        return size / self.s

    def rows(self, b, rows, gap=0.12):
        """Stack text rows in box b: rows = [(text, colour, weight[, font])], weight = share of the height."""
        x0, y0, x1, y1 = b
        tot = sum(r[2] for r in rows)
        y = y0
        for r in rows:
            rh = (y1 - y0) * r[2] / tot
            if r[0]:
                self.fit((x0, y + rh * gap / 2, x1, y + rh * (1 - gap / 2)), r[0], r[1], r[3] if len(r) > 3 else None)
            y += rh

    # ---------------------------------------------------------------- fills
    def vgrad(self, b, c0, c1):
        x0, y0, x1, y1 = [int(v * self.s) for v in b]
        for y in range(y0, y1):
            t = (y - y0) / max(1, y1 - y0 - 1)
            self.d.line([x0, y, x1, y], fill=rgba(mix(c0, c1, t), 255))

    def hgrad(self, b, c0, c1):
        x0, y0, x1, y1 = [int(v * self.s) for v in b]
        for x in range(x0, x1):
            t = (x - x0) / max(1, x1 - x0 - 1)
            self.d.line([x, y0, x, y1], fill=rgba(mix(c0, c1, t), 255))

    def radial(self, cx, cy, r, c_in, c_out, steps=60):
        """Radial glow from c_in (centre) to c_out (rim); c_out may be transparent (alpha 0)."""
        c_in = rgba(c_in, c_in[3] if len(c_in) > 3 else 255)
        c_out = rgba(c_out, c_out[3] if len(c_out) > 3 else 255)
        lay = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        for k in range(steps, 0, -1):
            t = k / steps
            rr = r * t * self.s
            ld.ellipse([cx * self.s - rr, cy * self.s - rr, cx * self.s + rr, cy * self.s + rr], fill=mix(c_in, c_out, t))
        self.img.alpha_composite(lay)

    def bokeh(self, seed, n, palette, rmin=10, rmax=60, box=None, alpha=(40, 120), blur=3):
        rnd = random.Random(seed)
        x0, y0, x1, y1 = box or (0, 0, self.W, self.H)
        lay = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        for _ in range(n):
            r = rnd.uniform(rmin, rmax) * self.s
            x, y = rnd.uniform(x0, x1) * self.s, rnd.uniform(y0, y1) * self.s
            c = rnd.choice(palette)
            ld.ellipse([x - r, y - r, x + r, y + r], fill=rgba(c, rnd.randint(*alpha)), outline=rgba(c, min(255, alpha[1] + 60)), width=max(1, int(r * 0.06)))
        self.img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(blur * self.s)))

    def overlay(self):
        """A blank layer the same size (draw on it, then glow() / paste())."""
        o = Art((self.W, self.H))
        return o

    def paste(self, other, opacity=1.0):
        im = other.img if isinstance(other, Art) else other
        if opacity < 1.0:
            im = im.copy()
            im.putalpha(im.getchannel("A").point(lambda a: int(a * opacity)))
        self.img.alpha_composite(im)

    def glow(self, draw, radius=10, strength=2, core=True):
        """Neon: draw(layer) on an overlay; composite its blur `strength` times, then the crisp shapes."""
        o = self.overlay()
        draw(o)
        b = o.img.filter(ImageFilter.GaussianBlur(radius * self.s))
        for _ in range(strength):
            self.img.alpha_composite(b)
        if core:
            self.img.alpha_composite(o.img)

    def neon_text(self, xy, txt, size, col, f=None, anchor="mm", radius=10, strength=2, core_col=(255, 255, 255)):
        def dr(o):
            o.text(xy, txt, size, rgba(col), f, anchor, stroke=size * 0.04, stroke_fill=rgba(col))
        self.glow(dr, radius, strength, core=True)
        self.text(xy, txt, size, rgba(mix(col, core_col, 0.6)), f, anchor)

    def scanlines(self, step=6, alpha=40, col=(0, 0, 0)):
        lay = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        for y in range(0, self.img.height, int(step * self.s)):
            ld.line([0, y, self.img.width, y], fill=rgba(col, alpha), width=max(1, int(step * self.s / 3)))
        self.img.alpha_composite(lay)

    def halftone(self, col, b=None, step=12, rmax=0.5, direction="v", alpha=255):
        """Dot screen getting bigger along `direction` (Showa print look)."""
        x0, y0, x1, y1 = b or (0, 0, self.W, self.H)
        y = y0
        while y < y1:
            x = x0
            t = (y - y0) / max(1, y1 - y0) if direction == "v" else 0
            while x < x1:
                tt = t if direction == "v" else (x - x0) / max(1, x1 - x0)
                r = step * rmax * tt
                if r > 0.4:
                    self.circle(x, y, r, fill=rgba(col, alpha))
                x += step
            y += step

    def out(self, long_side=1024):
        return save(self.img, self.W, self.H, long_side)


def save(img, w, h, long_side=1024):
    s = long_side / max(w, h)
    return img.convert("RGBa").resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS).convert("RGBA")


# ==================================================================== shapes
# Silhouettes are in a unit box (0..1 x 0..1, y down), placed with `place`.

def chaikin(pts, it=3, closed=True):
    """Corner-cutting smoothing: polygon silhouettes become curves."""
    for _ in range(it):
        out = []
        n = len(pts)
        rng = range(n) if closed else range(n - 1)
        if not closed:
            out.append(pts[0])
        for i in rng:
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            out += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
        if not closed:
            out.append(pts[-1])
        pts = out
    return pts


def place(pts, x, y, w, h, flip=False):
    return [(x + (1 - px if flip else px) * w, y + py * h) for px, py in pts]


def heart_pts(cx, cy, r, n=60):
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        hx = 16 * math.sin(t) ** 3
        hy = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        out.append((cx + hx / 17 * r, cy - hy / 17 * r))
    return out


def heart(a, cx, cy, r, fill=None, outline=None, width=0):
    p = heart_pts(cx, cy, r)
    if fill:
        a.poly(p, fill=fill)
    if outline:
        a.line(p + [p[0]], outline, width)


def neon_heart(a, cx, cy, r, col, width=8, radius=12, strength=2):
    a.glow(lambda o: heart(o, cx, cy, r, outline=rgba(col), width=width), radius, strength)
    heart(a, cx, cy, r, outline=rgba(mix(col, (255, 255, 255), 0.6)), width=width * 0.4)


def star_pts(cx, cy, r, n=5, inner=0.45, rot=-90):
    p = []
    for i in range(2 * n):
        rr = r if i % 2 == 0 else r * inner
        t = math.radians(rot + 180 * i / n)
        p.append((cx + rr * math.cos(t), cy + rr * math.sin(t)))
    return p


def lips(a, cx, cy, w, col, shine=True, open_=0.0):
    """Stylised lips (closed, or slightly parted with `open_`)."""
    h = w * 0.42
    x0, y0 = cx - w / 2, cy - h / 2
    up = [(0, .52), (.12, .36), (.28, .14), (.42, .06), (.5, .17), (.58, .06), (.72, .14), (.88, .36), (1, .52),
          (.78, .5), (.5, .55 - open_ * .1), (.22, .5)]
    lo = [(0, .52), (.22, .56 + open_ * .1), (.5, .6 + open_ * .14), (.78, .56 + open_ * .1), (1, .52),
          (.86, .74), (.68, .9), (.5, .95), (.32, .9), (.14, .74)]
    a.poly(chaikin(place(up, x0, y0, w, h), 2), fill=rgba(col))
    a.poly(chaikin(place(lo, x0, y0, w, h), 2), fill=rgba(mix(col, (0, 0, 0), 0.08)))
    a.line(place([(0.02, .52), (.22, .52), (.5, .57), (.78, .52), (.98, .52)], x0, y0, w, h), rgba(mix(col, (0, 0, 0), 0.55)), w * 0.012)
    if shine:
        a.ell((cx - w * 0.12, cy + h * 0.24, cx - w * 0.02, cy + h * 0.3), fill=(255, 255, 255, 90))
        a.ell((cx - w * 0.26, cy - h * 0.2, cx - w * 0.2, cy - h * 0.16), fill=(255, 255, 255, 60))


# woman in a long evening gown, one hand on her hip, the other raising a glass (3/4 view)
GOWN = [(.40, .165), (.60, .165), (.585, .215), (.56, .37), (.605, .47), (.63, .7), (.68, .97), (.74, 1.0),
        (.33, 1.0), (.37, .8), (.41, .6), (.425, .47), (.45, .37), (.415, .215)]


def woman_gown(a, x, y, h, col, flip=False, glass=True, hair=True, glass_col=None):
    """Stylised adult woman in a floor-length gown (silhouette), feet at (x + 0.5h, y + h)."""
    w = h
    P = lambda pts: place(pts, x, y, w, h, flip)
    fill = rgba(col)
    a.poly(chaikin(P(GOWN), 2), fill=fill)
    # head, neck, hair (a chignon and a wave over one shoulder)
    a.ell(_bb(P([(0.455, 0.035), (0.545, 0.135)])), fill=fill)
    a.poly(P([(0.48, 0.12), (0.52, 0.12), (0.525, 0.17), (0.475, 0.17)]), fill=fill)
    if hair:
        a.ell(_bb(P([(0.43, 0.02), (0.53, 0.1)])), fill=fill)
        a.ell(_bb(P([(0.415, 0.035), (0.465, 0.085)])), fill=fill)               # chignon
        a.poly(P([(0.53, 0.06), (0.56, 0.1), (0.565, 0.16), (0.545, 0.2), (0.535, 0.15)]), fill=fill)
    # arm on hip
    a.line(P([(0.595, 0.18), (0.64, 0.29), (0.595, 0.39)]), fill, h * 0.022)
    # raised arm with a glass
    a.line(P([(0.405, 0.18), (0.345, 0.27), (0.37, 0.15)]), fill, h * 0.02)
    if glass:
        gc = rgba(glass_col or col)
        a.line(P([(0.37, 0.15), (0.37, 0.11)]), gc, h * 0.004)
        a.poly(P([(0.345, 0.07), (0.395, 0.07), (0.37, 0.11)]), fill=gc)
    # a slit and a sheen line down the gown
    return P


def _bb(two):
    (x0, y0), (x1, y1) = two
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def man_suit(a, x, y, h, col, flip=False, tie_col=None):
    """Stylised adult man in a slim suit, one hand in a pocket (host club)."""
    w = h
    P = lambda pts: place(pts, x, y, w, h, flip)
    fill = rgba(col)
    a.ell(_bb(P([(0.45, 0.03), (0.55, 0.14)])), fill=fill)
    a.poly(P([(0.44, 0.06), (0.47, 0.0), (0.58, 0.01), (0.6, 0.06), (0.56, 0.05), (0.5, 0.04)]), fill=fill)   # swept hair
    a.poly(P([(0.48, 0.13), (0.52, 0.13), (0.525, 0.17), (0.475, 0.17)]), fill=fill)
    a.poly(P([(0.37, 0.18), (0.63, 0.18), (0.62, 0.3), (0.6, 0.52), (0.4, 0.52), (0.38, 0.3)]), fill=fill)   # jacket
    a.poly(P([(0.41, 0.5), (0.49, 0.5), (0.48, 0.98), (0.43, 0.98)]), fill=fill)                         # legs
    a.poly(P([(0.51, 0.5), (0.59, 0.5), (0.58, 0.98), (0.53, 0.98)]), fill=fill)
    a.poly(P([(0.41, 0.97), (0.48, 0.97), (0.48, 1.0), (0.39, 1.0)]), fill=fill)
    a.poly(P([(0.53, 0.97), (0.6, 0.97), (0.62, 1.0), (0.53, 1.0)]), fill=fill)
    a.line(P([(0.38, 0.2), (0.35, 0.36), (0.37, 0.5)]), fill, h * 0.03)                                    # arm down
    a.line(P([(0.62, 0.2), (0.66, 0.34), (0.6, 0.45)]), fill, h * 0.03)                                    # hand in pocket
    if tie_col:
        a.poly(P([(0.5, 0.18), (0.51, 0.2), (0.505, 0.33), (0.5, 0.35), (0.495, 0.33), (0.49, 0.2)]), fill=rgba(tie_col))
        a.poly(P([(0.47, 0.18), (0.5, 0.18), (0.5, 0.28)]), fill=rgba(mix(col, (255, 255, 255), 0.25)))
        a.poly(P([(0.53, 0.18), (0.5, 0.18), (0.5, 0.28)]), fill=rgba(mix(col, (255, 255, 255), 0.25)))


def leg(a, x, y, h, col, lean=0.0, seam=None, heel_col=None):
    """One leg in a stocking from the skirt hem (y) to a stiletto (y + h), toe pointing +x."""
    # centre line (fraction of h) and half widths, knee at 0.42
    c = [(0.0, 0.0), (0.02, 0.2), (0.04, 0.42), (0.02, 0.6), (0.0, 0.84)]
    wd = [0.085, 0.07, 0.042, 0.055, 0.022]
    L, R = [], []
    for (cx, cy), hw in zip(c, wd):
        px = x + (cx + lean * cy) * h
        py = y + cy * h
        L.append((px - hw * h, py))
        R.append((px + hw * h, py))
    # calf bulges to the back (-x)
    L[3] = (L[3][0] - 0.012 * h, L[3][1])
    a.poly(chaikin(L + R[::-1], 3), fill=rgba(col))
    ax, ay = x + (0.0 + lean * 0.84) * h, y + 0.84 * h
    stiletto(a, ax - 0.04 * h, ay - 0.02 * h, 0.2 * h, heel_col or col)
    if seam:
        a.line([(L[1][0] + 0.012 * h, L[1][1]), (L[3][0] + 0.01 * h, L[3][1]), (L[4][0] + 0.004 * h, L[4][1])], rgba(seam), h * 0.004)


def stiletto(a, x, y, w, col, sole=None):
    """Stiletto pump in profile, heel at the left (x), toe at x + w, ground at y + 0.8w."""
    P = lambda pts: [(x + px * w, y + py * w) for px, py in pts]
    body = [(0.05, 0.0), (0.22, 0.04), (0.38, 0.2), (0.62, 0.42), (0.86, 0.58), (1.0, 0.66), (0.98, 0.76),
            (0.62, 0.76), (0.36, 0.58), (0.12, 0.38), (0.06, 0.4), (0.02, 0.2)]
    a.poly(P(body), fill=rgba(col))
    a.poly(P([(0.04, 0.36), (0.12, 0.38), (0.1, 0.8), (0.08, 0.8)]), fill=rgba(col))       # the spike
    if sole:
        a.line(P([(0.36, 0.6), (0.62, 0.77), (0.98, 0.77)]), rgba(sole), w * 0.03)


def legs_pair(a, x, y, h, col, seam=None, heel_col=None, hem_col=None, crossed=True):
    """A pair of legs in stockings and heels below a skirt hem (centred on x)."""
    if crossed:
        # one leg straight, the other a step forward with the knee turned in
        leg(a, x - 0.07 * h, y, h, mix(col, (0, 0, 0), 0.25), lean=0.02, seam=seam, heel_col=heel_col)
        leg(a, x + 0.06 * h, y, h * 0.98, col, lean=0.1, seam=seam, heel_col=heel_col)
    else:
        leg(a, x - 0.08 * h, y, h, col, lean=0.0, seam=seam, heel_col=heel_col)
        leg(a, x + 0.08 * h, y, h, col, lean=0.05, seam=seam, heel_col=heel_col)
    if hem_col:
        # scalloped skirt hem over the thighs
        hw = 0.26 * h
        a.rect((x - hw, y - 0.12 * h, x + hw + 0.04 * h, y + 0.03 * h), fill=rgba(hem_col))
        n = 7
        for i in range(n):
            cx = x - hw + (i + 0.5) * (2 * hw + 0.04 * h) / n
            a.circle(cx, y + 0.03 * h, (2 * hw + 0.04 * h) / n / 2, fill=rgba(hem_col))


def profile(a, x, y, h, col, flip=False):
    """Head-and-shoulders profile facing +x (or -x with flip): the Dreamlink / Dolls face."""
    w = h * 0.8
    pts = [(.38, 0), (.58, .04), (.68, .16), (.7, .28), (.72, .36), (.8, .47), (.79, .5), (.72, .53), (.735, .58), (.71, .6),
           (.725, .64), (.7, .67), (.66, .72), (.66, .76), (.6, .8), (.5, .82), (.5, .88), (.56, 1.0), (.14, 1.0), (.26, .84),
           (.24, .7), (.12, .6), (.06, .42), (.08, .2), (.18, .06)]
    P = place(pts, x, y, w, h, flip)
    a.poly(chaikin(P, 2), fill=rgba(col))
    return P


def gloved_arm(a, x0, y0, x1, y1, col, glass_col=None, width=26):
    """An arm in an opera glove from (x0, y0) to the hand at (x1, y1), holding a coupe."""
    a.line([(x0, y0), ((x0 + x1) / 2 + width, (y0 + y1) / 2), (x1, y1)], rgba(col), width)
    a.circle(x1, y1, width * 0.75, fill=rgba(col))
    if glass_col:
        g = rgba(glass_col)
        a.line([(x1 + width * 0.6, y1 - width * 0.2), (x1 + width * 0.6, y1 - width * 2.4)], g, width * 0.18)
        a.poly([(x1 - width * 0.6, y1 - width * 2.4), (x1 + width * 1.8, y1 - width * 2.4), (x1 + width * 1.6, y1 - width * 3.0),
                (x1 - width * 0.4, y1 - width * 3.0)], fill=g)
        a.line([(x1 - width * 0.1, y1 + width * 0.1), (x1 + width * 1.3, y1 + width * 0.1)], g, width * 0.18)


def dress_form(a, cx, top, h, col, stand_col=(40, 40, 40)):
    """A tailor's dress form (torso on a stand): the lingerie ads dress it."""
    w = h * 0.5
    P = lambda pts: [(cx + (px - 0.5) * w, top + py * h) for px, py in pts]
    a.poly(chaikin(P([(0.3, 0.0), (0.7, 0.0), (0.98, 0.08), (0.94, 0.2), (0.86, 0.3), (0.74, 0.45), (0.88, 0.62), (0.9, 0.7),
              (0.1, 0.7), (0.12, 0.62), (0.26, 0.45), (0.14, 0.3), (0.06, 0.2), (0.02, 0.08)]), 2), fill=rgba(col))
    a.rect((cx - w * 0.04, top + 0.7 * h, cx + w * 0.04, top + 0.97 * h), fill=rgba(stand_col))
    a.poly(P([(0.2, 1.0), (0.8, 1.0), (0.54, 0.95), (0.46, 0.95)]), fill=rgba(stand_col))
    a.ell((cx - w * 0.12, top - 0.05 * h, cx + w * 0.12, top + 0.02 * h), fill=rgba(stand_col))
    return P


def corset(a, P, col, lace):
    """A corset over the dress form P (from dress_form): cups, laced bodice, straps."""
    a.poly(P([(0.16, 0.22), (0.84, 0.22), (0.76, 0.36), (0.72, 0.48), (0.82, 0.58), (0.18, 0.58), (0.28, 0.48), (0.24, 0.36)]), fill=rgba(col))
    for side in (0.32, 0.68):
        a.ell(_bb(P([(side - 0.17, 0.15), (side + 0.17, 0.29)])), fill=rgba(col))
        a.arc(_bb(P([(side - 0.17, 0.15), (side + 0.17, 0.29)])), 180, 360, rgba(lace), 3)
    a.line(P([(0.32, 0.17), (0.3, 0.02)]), rgba(lace), 3)
    a.line(P([(0.68, 0.17), (0.7, 0.02)]), rgba(lace), 3)
    for k in range(7):
        yy = 0.31 + k * 0.035
        a.line(P([(0.47, yy), (0.53, yy + 0.02)]), rgba(lace), 2)
        a.line(P([(0.53, yy), (0.47, yy + 0.02)]), rgba(lace), 2)
    # scalloped lace hem
    for k in range(10):
        x = 0.2 + k * 0.064
        a.arc(_bb(P([(x, 0.555), (x + 0.064, 0.6)])), 0, 180, rgba(lace), 3)


def cyber_arm(a, x, y, s, col, accent, flip=False):
    """A Hoshikawa cyberlimb: forearm, wrist, open hand (segments + glowing joints)."""
    f = -1 if flip else 1
    X = lambda v: x + f * v * s
    a.rect(_bb([(X(0), y + 0.3 * s), (X(0.55), y + 0.52 * s)]), fill=rgba(col), r=0.08 * s)            # forearm
    a.rect(_bb([(X(0.05), y + 0.33 * s), (X(0.5), y + 0.36 * s)]), fill=rgba(mix(col, (255, 255, 255), 0.35)))
    a.circle(X(0.6), y + 0.41 * s, 0.07 * s, fill=rgba(accent))                                          # wrist joint
    a.rect(_bb([(X(0.64), y + 0.32 * s), (X(0.85), y + 0.52 * s)]), fill=rgba(col), r=0.04 * s)          # palm
    for k, (dy, ln) in enumerate(((0.3, 0.22), (0.37, 0.27), (0.44, 0.26), (0.51, 0.21))):
        yy = y + dy * s
        a.rect(_bb([(X(0.86), yy - 0.025 * s), (X(0.86 + ln), yy + 0.025 * s)]), fill=rgba(col), r=0.02 * s)
        a.circle(X(0.86 + ln * 0.45), yy, 0.018 * s, fill=rgba(accent))
    a.line([(X(0.7), y + 0.53 * s), (X(0.82), y + 0.66 * s), (X(0.93), y + 0.68 * s)], rgba(col), 0.05 * s)  # thumb
    for k in range(4):
        a.line([(X(0.1 + k * 0.1), y + 0.52 * s), (X(0.1 + k * 0.1), y + 0.6 * s)], rgba(accent), 0.012 * s)


def watch(a, cx, cy, r, case, dial, hands, strap):
    a.rect((cx - r * 0.55, cy - r * 2.3, cx + r * 0.55, cy + r * 2.3), fill=rgba(strap), r=r * 0.2)
    a.circle(cx, cy, r * 1.08, fill=rgba(case))
    a.circle(cx, cy, r * 0.92, fill=rgba(dial))
    for k in range(12):
        t = math.radians(k * 30)
        r0, r1 = r * (0.7 if k % 3 else 0.62), r * 0.84
        a.line([(cx + r0 * math.sin(t), cy - r0 * math.cos(t)), (cx + r1 * math.sin(t), cy - r1 * math.cos(t))], rgba(hands), r * (0.05 if k % 3 else 0.08))
    a.line([(cx, cy), (cx + r * 0.42 * math.sin(math.radians(300)), cy - r * 0.42 * math.cos(math.radians(300)))], rgba(hands), r * 0.07)
    a.line([(cx, cy), (cx + r * 0.66 * math.sin(math.radians(60)), cy - r * 0.66 * math.cos(math.radians(60)))], rgba(hands), r * 0.045)
    a.circle(cx, cy, r * 0.06, fill=rgba(hands))
    a.rect((cx + r * 1.02, cy - r * 0.12, cx + r * 1.18, cy + r * 0.12), fill=rgba(case))


def coupe(a, x, y, L, body, glass, light=None):
    """A low sports coupe in side view (the Kanzaki Hayate RS): x, y = front-bottom-left of the box."""
    H = L * 0.27
    P = lambda pts: [(x + px * L, y - py * H) for px, py in pts]
    a.poly(P([(0.0, 0.2), (0.02, 0.45), (0.25, 0.55), (0.42, 0.95), (0.62, 1.0), (0.82, 0.78), (1.0, 0.7), (1.0, 0.25),
              (0.96, 0.15), (0.0, 0.15)]), fill=rgba(body))
    a.poly(P([(0.45, 0.88), (0.6, 0.93), (0.75, 0.75), (0.47, 0.72)]), fill=rgba(glass))
    for wx in (0.18, 0.8):
        a.circle(x + wx * L, y - 0.15 * H, 0.1 * L, fill=(10, 10, 12, 255))
        a.circle(x + wx * L, y - 0.15 * H, 0.06 * L, fill=rgba(mix(body, (200, 200, 210), 0.6)))
    if light:
        a.glow(lambda o: o.line(P([(0.0, 0.42), (0.1, 0.48)]), rgba(light), 0.012 * L), 6, 2)
        a.glow(lambda o: o.line(P([(0.97, 0.6), (1.0, 0.55)]), (255, 30, 40, 255), 0.012 * L), 6, 2)


def can(a, x, y, w, h, body, band, txt=None, txt_col=(255, 255, 255)):
    a.rect((x, y, x + w, y + h), fill=rgba(body), r=w * 0.12)
    a.ell((x, y - w * 0.12, x + w, y + w * 0.12), fill=rgba(mix(body, (220, 220, 230), 0.6)))
    a.rect((x, y + h * 0.35, x + w, y + h * 0.65), fill=rgba(band))
    a.rect((x + w * 0.12, y + h * 0.05, x + w * 0.22, y + h * 0.95), fill=(255, 255, 255, 50))
    if txt:
        lay = Art((int(h * 0.3) + 2, int(w) + 2))
        lay.fit((0, 0, h * 0.3, w), txt, rgba(txt_col), IMPACT)
        im = lay.img.rotate(90, expand=True)
        a.img.alpha_composite(im, (int((x + w * 0.5) * a.s - im.width / 2), int((y + h * 0.5) * a.s - im.height / 2)))


def bowl(a, cx, cy, r, col, rim, noodle=(250, 225, 150), steam=(255, 255, 255, 120)):
    a.poly([(cx - r, cy), (cx + r, cy), (cx + r * 0.7, cy + r * 0.7), (cx - r * 0.7, cy + r * 0.7)], fill=rgba(col))
    a.ell((cx - r, cy - r * 0.18, cx + r, cy + r * 0.18), fill=rgba(rim))
    a.ell((cx - r * 0.9, cy - r * 0.13, cx + r * 0.9, cy + r * 0.13), fill=rgba(noodle))
    for k in range(6):
        xx = cx - r * 0.7 + k * r * 0.28
        a.arc((xx - r * 0.12, cy - r * 0.12, xx + r * 0.12, cy + r * 0.08), 180, 360, rgba(mix(noodle, (160, 110, 40), 0.4)), r * 0.03)
    a.circle(cx + r * 0.35, cy - r * 0.02, r * 0.15, fill=(250, 250, 240, 255))      # egg
    a.circle(cx + r * 0.35, cy - r * 0.02, r * 0.07, fill=(250, 170, 30, 255))
    a.line([(cx - r * 0.2, cy - r * 0.05), (cx + r * 1.2, cy - r * 0.9)], (60, 30, 20, 255), r * 0.05)   # chopsticks
    a.line([(cx - r * 0.1, cy - r * 0.02), (cx + r * 1.3, cy - r * 0.75)], (60, 30, 20, 255), r * 0.05)
    for k in range(3):
        xx = cx - r * 0.45 + k * r * 0.45
        a.line([(xx, cy - r * 0.25), (xx + r * 0.12, cy - r * 0.55), (xx - r * 0.08, cy - r * 0.85), (xx + r * 0.06, cy - r * 1.15)], steam, r * 0.05)


def keyhole(a, cx, cy, r, fill):
    a.circle(cx, cy, r, fill=fill)
    a.poly([(cx - r * 0.45, cy + r * 0.5), (cx + r * 0.45, cy + r * 0.5), (cx + r * 0.8, cy + r * 2.4), (cx - r * 0.8, cy + r * 2.4)], fill=fill)


def crescent(a, cx, cy, r, col, bg, off=0.35):
    a.circle(cx, cy, r, fill=rgba(col))
    a.circle(cx + r * off, cy - r * off * 0.5, r * 0.9, fill=rgba(bg))


def eye(a, cx, cy, r, col, width, crossed=False):
    a.ell((cx - r, cy - r * 0.55, cx + r, cy + r * 0.55), outline=rgba(col), width=width)
    a.circle(cx, cy, r * 0.3, fill=rgba(col))
    if crossed:
        a.line([(cx - r * 1.1, cy + r * 0.8), (cx + r * 1.1, cy - r * 0.8)], rgba(col), width * 1.6)


def qr(a, x, y, size, seed, ink=(15, 15, 15, 255), paper=(250, 250, 250, 255)):
    rnd = random.Random(seed)
    n = 21
    c = size / n
    a.rect((x, y, x + size, y + size), fill=paper)
    for i in range(n):
        for j in range(n):
            finder = any(i0 <= i < i0 + 7 and j0 <= j < j0 + 7 for i0, j0 in ((0, 0), (14, 0), (0, 14)))
            if finder:
                ii, jj = i % 7 if i < 7 else (i - 14) % 7, j % 7 if j < 7 else (j - 14) % 7
                on = ii in (0, 6) or jj in (0, 6) or (2 <= ii <= 4 and 2 <= jj <= 4)
            else:
                on = rnd.random() < 0.48
            if on:
                a.rect((x + i * c, y + j * c, x + (i + 1) * c, y + (j + 1) * c), fill=ink)


def barcode(a, x, y, w, h, seed, ink=(15, 15, 15, 255)):
    rnd = random.Random(seed)
    xx = x
    while xx < x + w:
        bw = rnd.choice((1, 1, 2, 3)) * w / 90
        if rnd.random() < 0.55:
            a.rect((xx, y, xx + bw, y + h), fill=ink)
        xx += bw


def gauge(a, cx, cy, r, val, col, track=(255, 255, 255, 50), width=24):
    a.arc((cx - r, cy - r, cx + r, cy + r), 135, 405, track, width)
    a.arc((cx - r, cy - r, cx + r, cy + r), 135, 135 + 270 * val, rgba(col), width)


# ==================================================================== finishes

def to_img(x):
    return x.img if isinstance(x, Art) else x


def noise(img, seed, amount=14, density=40):
    rnd = random.Random(seed)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // density):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r, g, b, a = px[x, y]
        if a:
            k = rnd.randint(-amount, amount)
            px[x, y] = (max(0, min(255, r + k)), max(0, min(255, g + k)), max(0, min(255, b + k)), a)
    return img


def photocopy(img, seed, paper=(232, 229, 218), ink=(22, 22, 22), threshold=128, tint=None):
    """Cheap photocopy: greyscale, crushed to ink and paper, toner specks, streaks."""
    rnd = random.Random(seed)
    a = img.getchannel("A")
    g = ImageOps.autocontrast(img.convert("L"))
    g = g.point(lambda v: 255 if v > threshold else (0 if v < threshold * 0.55 else int((v - threshold * 0.55) / (threshold * 0.45) * 255)))
    out = Image.merge("RGB", [g.point(lambda v, i=i: int(ink[i] + (paper[i] - ink[i]) * v / 255)) for i in range(3)]).convert("RGBA")
    d = ImageDraw.Draw(out)
    w, h = out.size
    for _ in range(int(w * h / 2500)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.choice((1, 1, 2, 3))
        d.ellipse([x - r, y - r, x + r, y + r], fill=ink + (255,))
    for _ in range(3):
        x = rnd.randrange(w)
        d.line([x, 0, x + rnd.randint(-8, 8), h], fill=ink + (rnd.randint(20, 60),), width=rnd.randint(1, 4))
    if tint:
        out = Image.blend(out, Image.new("RGBA", out.size, tint + (255,)), 0.15)
    out.putalpha(a)
    return out


def glitch(img, seed, slices=14, shift=0.04, split=6):
    """RGB split and slice displacement (a hacked screen)."""
    rnd = random.Random(seed)
    r, g, b, a = img.split()
    r = ImageChops.offset(r, split, 0)
    b = ImageChops.offset(b, -split, 0)
    out = Image.merge("RGBA", (r, g, b, a))
    w, h = out.size
    for _ in range(slices):
        y = rnd.randrange(h)
        hh = rnd.randint(h // 120 + 1, h // 25 + 2)
        dx = int(rnd.uniform(-shift, shift) * w)
        band = out.crop((0, y, w, min(h, y + hh)))
        out.paste(ImageChops.offset(band, dx, 0), (0, y))
    return out


def torn(img, seed, edges="tb", depth=0.03, holes=0):
    """Ragged paper edges (alpha) along the given sides, plus optional torn-out holes."""
    rnd = random.Random(seed)
    w, h = img.size
    m = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(m)
    dep = depth * max(w, h)

    def rag(n):
        return [rnd.uniform(0.2, 1.0) * dep for _ in range(n)]
    if "t" in edges:
        n = 40
        r = rag(n + 1)
        d.polygon([(0, 0)] + [(w * i / n, r[i]) for i in range(n + 1)] + [(w, 0)], fill=0)
    if "b" in edges:
        n = 40
        r = rag(n + 1)
        d.polygon([(0, h)] + [(w * i / n, h - r[i]) for i in range(n + 1)] + [(w, h)], fill=0)
    if "l" in edges:
        n = 50
        r = rag(n + 1)
        d.polygon([(0, 0)] + [(r[i], h * i / n) for i in range(n + 1)] + [(0, h)], fill=0)
    if "r" in edges:
        n = 50
        r = rag(n + 1)
        d.polygon([(w, 0)] + [(w - r[i], h * i / n) for i in range(n + 1)] + [(w, h)], fill=0)
    for _ in range(holes):
        cx, cy = rnd.uniform(0.15, 0.85) * w, rnd.uniform(0.15, 0.85) * h
        rr = rnd.uniform(0.05, 0.12) * w
        pts = [(cx + rr * rnd.uniform(0.5, 1.2) * math.cos(t), cy + rr * rnd.uniform(0.5, 1.2) * math.sin(t))
               for t in [2 * math.pi * k / 14 for k in range(14)]]
        d.polygon(pts, fill=0)
    out = img.copy()
    out.putalpha(ImageChops.multiply(img.getchannel("A"), m))
    return out


def rip_to(img, under, seed, frac=0.45, side="r"):
    """Tear `img` away diagonally to reveal `under` (an older poster below): torn layers."""
    rnd = random.Random(seed)
    w, h = img.size
    under = under.resize((w, h), Image.LANCZOS) if under.size != (w, h) else under
    m = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(m)
    n = 30
    pts = []
    for i in range(n + 1):
        y = h * i / n
        x = w * (1 - frac * (0.4 + 0.9 * i / n)) + rnd.uniform(-0.03, 0.03) * w
        pts.append((x, y))
    if side == "r":
        d.polygon(pts + [(w, h), (w, 0)], fill=0)
    else:
        d.polygon([(w - x, y) for x, y in pts] + [(0, h), (0, 0)], fill=0)
    # white paper rim where the top sheet tore
    rim = m.filter(ImageFilter.MaxFilter(7))
    top = img.copy()
    top.putalpha(ImageChops.multiply(img.getchannel("A"), m))
    paper = Image.new("RGBA", (w, h), (238, 234, 222, 255))
    paper.putalpha(ImageChops.subtract(rim, m))
    out = under.copy()
    out.alpha_composite(paper)
    out.alpha_composite(top)
    return out


def spray(img, txt, seed, fill=(255, 30, 60, 255), shade=(255, 140, 40, 255), at=(0.5, 0.55), width=0.9, rot=8, f=BLACK):
    """Paint a graffiti tag (make_decals.graffiti) over an image."""
    tag = graffiti(txt, f, 240, fill, shade, (10, 0, 10, 255), (255, 255, 255, 255), seed=seed, drips=8)
    tag = tag.rotate(rot, expand=True, resample=Image.BICUBIC)
    tw = int(img.width * width)
    tag = tag.resize((tw, max(1, int(tag.height * tw / tag.width))), Image.LANCZOS)
    out = img.copy()
    out.alpha_composite(tag, (int(img.width * at[0] - tw / 2), int(img.height * at[1] - tag.height / 2)))
    return out


def strike(img, seed, col=(230, 20, 30, 255), n=3, width=0.03):
    rnd = random.Random(seed)
    out = img.copy()
    d = ImageDraw.Draw(out)
    w, h = out.size
    for _ in range(n):
        y = rnd.uniform(0.2, 0.8) * h
        d.line([w * rnd.uniform(0.0, 0.2), y, w * rnd.uniform(0.8, 1.0), y + rnd.uniform(-0.15, 0.15) * h], fill=col, width=int(width * h))
    return out


def paste_over(img, top, at, width, rot=0):
    """Paste `top` (a flyer) over img at fractional position `at`, `width` fraction of img width."""
    tw = int(img.width * width)
    t = top.resize((tw, max(1, int(top.height * tw / top.width))), Image.LANCZOS)
    if rot:
        t = t.rotate(rot, expand=True, resample=Image.BICUBIC)
    out = img.copy()
    out.alpha_composite(t, (int(img.width * at[0] - t.width / 2), int(img.height * at[1] - t.height / 2)))
    return out


def showa(img, seed, tone=(242, 226, 196), fade=0.22):
    """Retro Showa print: warm paper tone, faded inks, grain."""
    a = img.getchannel("A")
    base = Image.new("RGBA", img.size, tone + (255,))
    out = Image.blend(img.convert("RGBA"), base, fade)
    out = noise(out, seed, 18, 30)
    out.putalpha(a)
    return out
