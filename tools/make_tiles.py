"""Procedural tiling texture sets for Pigment's image fills.

Every set is seamless (all noise is built in the frequency domain or on a
torus, all layouts repeat exactly) and has four maps:

    base_color.png  sRGB
    roughness.png   grey
    height.png      16-bit grey, 0.5 = flat surface
    normal.png      tangent-space, OpenGL convention (+Y up), from the height

Sets (and the real-world size one repeat is designed for, use it as
Pigment's triplanar `tile_size`):

    concrete_slab     2 m   cast-in-place slab: formwork joints, tie holes, stains
    brick             1 m   running bond, 4 x 14 courses, recessed mortar
    paving_setts      1 m   granite setts in offset rows, domed tops, dirty joints
    corrugated_metal  1 m   galvanised sheet, 12 corrugations, rust patches
    asphalt_cracks    2 m   aggregate asphalt with a crack network and patches

    wallpapers   wallpaper_damask 1 m, wallpaper_stripes 0.5 m, wallpaper_floral 0.6 m,
                 wallpaper_art_deco 1 m, wallpaper_trellis 0.5 m
    carpets      carpet_plush 1 m, carpet_berber 0.5 m, carpet_tiles 1 m, carpet_hotel 1 m
    floors       wood_planks 1 m, parquet_herringbone 1 m, floor_checker 1.2 m,
                 floor_hex_tiles 1 m, terrazzo 1 m, marble 2 m, diamond_plate 1 m, rubber_studs 1 m
    walls        subway_tiles 0.9 m, plaster 2 m
    surfaces     wood_grain 1 m, leather 0.3 m, linen 0.1 m, denim 0.1 m, carbon_fibre 0.05 m,
                 hammered_metal 0.5 m
    nature       bark_fissured 0.6 m (triplanar, image up = world up),
                 end_grain 0.7 m (one stump cut, not a repeat: planar UV; make it at 2048)

    python tools/make_tiles.py [--size 512] [set ...]   (committed at 512; 1024+ for close-ups)  ->  assets/tiles/<set>/*.png
"""
import argparse
import os

import numpy as np
from PIL import Image

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "tiles")
SETS = {}


def tile_set(size_m):
    def reg(fn):
        SETS[fn.__name__] = (fn, size_m)
        return fn
    return reg


# ---------------------------------------------------------------- helpers

def coords(n):
    """Pixel centres in tile units 0..1, (y, x) grids."""
    v = (np.arange(n) + 0.5) / n
    return np.meshgrid(v, v, indexing="ij")


def noise(n, rng, lo, hi, beta=1.0):
    """Periodic band-limited noise, normalised to mean 0, std 1. lo/hi are
    frequencies in cycles per tile."""
    w = rng.standard_normal((n, n))
    f = np.fft.fftfreq(n) * n
    fy, fx = np.meshgrid(f, f, indexing="ij")
    r = np.sqrt(fx * fx + fy * fy)
    amp = np.where((r >= lo) & (r <= hi), 1.0 / np.maximum(r, 1.0) ** beta, 0.0)
    out = np.real(np.fft.ifft2(np.fft.fft2(w) * amp))
    return (out - out.mean()) / (out.std() + 1e-9)


def smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    t = np.asarray(t)
    if t.ndim == 2 and any(np.ndim(c) in (1, 3) for c in (a, b)):   # colours: broadcast t over rgb
        t = t[..., None]
    return a * (1 - t) + b * t


def color(rgb):
    return np.array(rgb, dtype=np.float64)


def blur(x, r):
    """Periodic box blur (radius r px), twice for a soft result."""
    for _ in range(2):
        acc = np.zeros_like(x)
        for d in range(-r, r + 1):
            acc += np.roll(x, d, axis=0)
        x = acc / (2 * r + 1)
        acc = np.zeros_like(x)
        for d in range(-r, r + 1):
            acc += np.roll(x, d, axis=1)
        x = acc / (2 * r + 1)
    return x


def cells(n, rows, cols, shift_odd=0.5, gap=0.0):
    """Running-bond grid: per pixel (row, col id, local x, local y in 0..1)."""
    y, x = coords(n)
    ry = y * rows
    row = np.floor(ry).astype(int)
    ly = ry - row
    rx = x * cols + (row % 2) * shift_odd
    col = np.floor(rx).astype(int) % cols
    lx = rx - np.floor(rx)
    return row, col, lx, ly


def edge_dist(lx, ly, ax, ay):
    """Distance to the cell border in metres-ish units (ax, ay = cell size)."""
    return np.minimum(np.minimum(lx, 1 - lx) * ax, np.minimum(ly, 1 - ly) * ay)


def per_cell(rng, ids, k=1):
    """Random values per cell id."""
    table = rng.random((ids.max() + 1, k))
    return table[ids]


def torus_voronoi(n, pts):
    """F1 and F2 distances (tile units) to points on the unit torus."""
    y, x = coords(n)
    f1 = np.full((n, n), 9.0)
    f2 = np.full((n, n), 9.0)
    for py, px in pts:
        dx = np.abs(x - px)
        dx = np.minimum(dx, 1 - dx)
        dy = np.abs(y - py)
        dy = np.minimum(dy, 1 - dy)
        d = np.sqrt(dx * dx + dy * dy)
        f2 = np.where(d < f1, f1, np.minimum(f2, d))
        f1 = np.minimum(f1, d)
    return f1, f2


def srgb(r, g, b):
    """A colour picked in sRGB 0..1, as the linear value `save` expects."""
    return np.array([r, g, b], dtype=np.float64) ** 2.2


def aniso_noise(n, rng, lo, hi, beta=1.0, stretch=8.0):
    """Periodic noise whose features are `stretch` times longer along x than y
    (wood grain, fibres). Normalised like `noise`."""
    w = rng.standard_normal((n, n))
    f = np.fft.fftfreq(n) * n
    fy, fx = np.meshgrid(f, f, indexing="ij")
    r = np.sqrt((fx * stretch) ** 2 + fy * fy)
    amp = np.where((r >= lo) & (r <= hi), 1.0 / np.maximum(r, 1.0) ** beta, 0.0)
    out = np.real(np.fft.ifft2(np.fft.fft2(w) * amp))
    return (out - out.mean()) / (out.std() + 1e-9)


def warp(a, dy, dx):
    """Sample `a` displaced by (dy, dx) pixels, wrapping."""
    n = a.shape[0]
    yy, xx = np.indices((n, n))
    return a[(yy + np.round(dy).astype(int)) % n, (xx + np.round(dx).astype(int)) % n]


def grid_voronoi(n, g, rng, jitter=1.0):
    """Jittered-grid Voronoi on the torus with g x g cells: F1, F2 (tile
    units) and the nearest cell's id (0..g*g-1)."""
    y, x = coords(n)
    gy, gx = y * g, x * g
    iy, ix = np.floor(gy).astype(int), np.floor(gx).astype(int)
    pts = rng.random((g, g, 2)) * jitter + (1 - jitter) / 2
    f1 = np.full((n, n), 9.0)
    f2 = np.full((n, n), 9.0)
    ids = np.zeros((n, n), dtype=int)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cy, cx = iy + dy, ix + dx
            p = pts[cy % g, cx % g]
            d = np.hypot(gy - cy - p[..., 0], gx - cx - p[..., 1])
            closer = d < f1
            f2 = np.where(closer, f1, np.minimum(f2, d))
            ids = np.where(closer, (cy % g) * g + cx % g, ids)
            f1 = np.minimum(f1, d)
    return f1 / g, f2 / g, ids


def wrap_d(a):
    """Signed periodic difference in tile units, -0.5..0.5."""
    return (a + 0.5) % 1.0 - 0.5


def leaf(u, v, cu, cv, angle, length, width, px):
    """Anti-aliased pointed-leaf mask centred (cu, cv), pointing along `angle`."""
    ca, sa = np.cos(angle), np.sin(angle)
    s = (u - cu) * ca + (v - cv) * sa
    t = -(u - cu) * sa + (v - cv) * ca
    half = width * np.clip(1 - (s / length) ** 2, 0, 1)
    return smooth(half - np.abs(t), -px, px) * (np.abs(s) < length)


def wood_rings(n, rng, rings, stretch=10.0):
    """Long-grain wood figure along x: (rings 0..1, pores 0..1, flecks)."""
    w = aniso_noise(n, rng, 1, 24, 1.2, stretch) * 0.035 + aniso_noise(n, rng, 1, 6, 1.0, 3.0) * 0.05
    y, _ = coords(n)
    r = (y + w) * rings
    late = smooth(np.abs((r % 1.0) - 0.5) * 2, 0.55, 0.95)          # latewood bands
    pores = smooth(aniso_noise(n, rng, 60, n // 2, 0.3, 14.0), 1.2, 2.4)
    fleck = aniso_noise(n, rng, 8, 80, 0.8, 4.0)
    return late, pores, fleck


def pile(n, rng):
    """Carpet pile: fibre tips, tufts and the shading of brushed pile."""
    fib = noise(n, rng, n // 6, n // 2, 0.0)
    tuft = noise(n, rng, 40, 120, 0.6)
    shade = noise(n, rng, 1, 5, 1.4)
    return fib, tuft, shade


def normal_from_height(h, strength):
    """OpenGL tangent normal: +x right, +y up the image."""
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5   # rows go down
    nx = -dx * strength
    ny = dy * strength
    nz = np.ones_like(h)
    l = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx / l, ny / l, nz / l], axis=-1)


def save(name, size_m, base, rough, height, bump):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    n = base.shape[0]
    b8 = (np.clip(base, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)  # linear -> ~sRGB
    Image.fromarray(b8, "RGB").save(os.path.join(d, "base_color.png"), optimize=True)
    Image.fromarray((np.clip(rough, 0, 1) * 255 + 0.5).astype(np.uint8), "L").save(os.path.join(d, "roughness.png"), optimize=True)
    h16 = (np.clip(height, 0, 1) * 65535 + 0.5).astype(np.uint16)
    Image.fromarray(h16).save(os.path.join(d, "height.png"))
    # bump: height units per pixel -> tilt; scaled so the normal matches the
    # set's physical size (height 0..1 = `bump` metres)
    px_m = size_m / n
    nrm = normal_from_height(height * bump / px_m, 1.0)
    Image.fromarray(((nrm * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8), "RGB").save(os.path.join(d, "normal.png"), optimize=True)
    print(f"{name}: {n}px, one repeat = {size_m} m -> {d}")


# ---------------------------------------------------------------- sets

@tile_set(2.0)
def concrete_slab(n, rng):
    y, x = coords(n)
    m = 2.0
    mottle = noise(n, rng, 1, 8, 1.2) * 0.6 + noise(n, rng, 8, 60, 1.0) * 0.3
    pores = noise(n, rng, 120, n // 2, 0.0)
    pits = smooth(pores, 2.3, 3.0)
    # formwork joints at the tile border (2 m panels), and a fainter mid line
    dj = np.minimum(np.minimum(x, 1 - x), np.minimum(y, 1 - y)) * m
    joint = 1 - smooth(dj, 0.004, 0.010)
    mid = 1 - smooth(np.abs(y - 0.5) * m, 0.001, 0.004)
    # tie holes on a 0.5 m grid
    hx = (x * 4) % 1 - 0.5
    hy = (y * 4) % 1 - 0.5
    hole_r = np.sqrt(hx * hx + hy * hy) * 0.5
    hole = 1 - smooth(hole_r, 0.010, 0.014)
    ring = smooth(hole_r, 0.012, 0.016) * (1 - smooth(hole_r, 0.02, 0.05))
    # leak stains below the holes and the joint
    streak = noise(n, rng, 2, 40, 0.8)
    stain = np.clip(smooth(streak, 0.3, 1.6) * (0.4 + 0.6 * smooth(noise(n, rng, 1, 4, 1.0), -0.5, 1.0)), 0, 1)

    g = 0.36 + mottle * 0.035 - pits * 0.08 - stain * 0.08 - ring * 0.04
    base = np.stack([g * 1.0, g * 0.985, g * 0.95], axis=-1)
    base = mix(base, color([0.12, 0.115, 0.11]), joint * 0.85 + hole * 0.9 + mid * 0.3)
    rough = 0.82 + mottle * 0.04 - stain * 0.15 + pits * 0.1
    rough = np.where(joint + hole > 0.5, 0.95, rough)
    h = 0.62 + mottle * 0.01 - pits * 0.04 - joint * 0.35 - hole * 0.45 - mid * 0.05
    return base, rough, h, 0.02


@tile_set(1.0)
def brick(n, rng):
    rows, cols = 14, 4
    row, col, lx, ly = cells(n, rows, cols)
    ids = row * cols + col
    bw, bh = 1.0 / cols, 1.0 / rows                      # metres
    d = edge_dist(lx, ly, bw, bh)
    mortar_w = 0.006
    chip = noise(n, rng, 20, 160, 0.7) * 0.0012
    face = smooth(d + chip, mortar_w, mortar_w + 0.004)    # 1 on the brick face
    v = per_cell(rng, ids, 4)
    tone = v[..., 0]
    hue = color([0.34, 0.11, 0.065]) * (0.7 + 0.6 * tone[..., None])
    hue = mix(hue, color([0.30, 0.17, 0.12]), (v[..., 1] > 0.8) * 0.8)        # brown clinkers
    hue = mix(hue, color([0.12, 0.06, 0.05]), (v[..., 2] > 0.93) * 0.7)       # burnt headers
    grain = noise(n, rng, 40, n // 2, 0.5)
    blot = noise(n, rng, 2, 12, 1.0)
    brick_c = hue * (1 + grain[..., None] * 0.06 + blot[..., None] * 0.05)
    soot = smooth(noise(n, rng, 1, 3, 1.5), 0.2, 2.2) * 0.6
    brick_c = brick_c * (1 - 0.45 * soot[..., None])
    mortar_c = color([0.42, 0.40, 0.37]) * (1 + noise(n, rng, 30, 200, 0.5)[..., None] * 0.08) * (1 - 0.5 * soot[..., None])
    base = mix(mortar_c, brick_c, face)
    rough = np.where(face > 0.5, 0.78 + grain * 0.04 + v[..., 3] * 0.08, 0.92)
    bulge = np.clip(d / 0.02, 0, 1) ** 0.5
    h = 0.35 + face * (0.35 + bulge * 0.06 + grain * 0.01) + (1 - face) * noise(n, rng, 60, 300, 0.3) * 0.02
    return base, rough, h, 0.02


@tile_set(1.0)
def paving_setts(n, rng):
    rows, cols = 10, 10
    row, col, lx, ly = cells(n, rows, cols)
    ids = row * cols + col
    s = 1.0 / cols
    d = edge_dist(lx, ly, s, 1.0 / rows)
    rough_edge = noise(n, rng, 30, 200, 0.6) * 0.004
    face = smooth(d + rough_edge, 0.006, 0.014)
    dome = np.clip(d / 0.045, 0, 1) ** 0.6
    v = per_cell(rng, ids, 3)
    grey = 0.22 + v[..., 0] * 0.14
    speck = noise(n, rng, 150, n // 2, 0.0)
    stone = np.stack([grey, grey * 0.98, grey * 0.97], -1) * (1 + speck[..., None] * 0.12)
    stone = mix(stone, stone * color([1.1, 0.95, 0.8]), (v[..., 1] > 0.75) * 0.6)   # pinkish granite
    polish = dome * 0.25
    joint_c = color([0.07, 0.06, 0.05]) * (1 + noise(n, rng, 10, 80, 0.8)[..., None] * 0.2)
    base = mix(joint_c, stone * (1 + polish[..., None]), face)
    rough = np.where(face > 0.5, 0.62 - dome * 0.2 + v[..., 2] * 0.1, 0.95)
    h = 0.3 + face * (0.3 + dome * 0.2) + speck * 0.004
    return base, rough, h, 0.03


@tile_set(1.0)
def corrugated_metal(n, rng):
    y, x = coords(n)
    waves = 12
    prof = 0.5 + 0.5 * np.sin(2 * np.pi * x * waves)
    # a sheet overlap seam across the middle
    seam = 1 - smooth(np.abs(y - 0.5), 0.002, 0.006)
    rivets = (1 - smooth(np.sqrt(((x * waves) % 1 - 0.75) ** 2 * (1 / waves) ** 2 + (y - 0.52) ** 2), 0.003, 0.006))
    zinc = noise(n, rng, 3, 50, 1.0)
    spangle = noise(n, rng, 60, n // 3, 0.2)
    rust_n = noise(n, rng, 2, 30, 1.1) + 0.6 * noise(n, rng, 30, 120, 0.8)
    # rust likes the bottom of each wave (water runs there) and the seam
    rust = smooth(rust_n + (1 - prof) * 0.8 + seam * 1.5, 1.2, 1.8)
    drip = smooth(noise(n, rng, 2, 60, 0.7) * 0.6 + rust_n * 0.5, 0.9, 1.6) * (1 - prof) ** 0.5
    rust = np.clip(rust + drip * 0.6, 0, 1)
    metal = 0.48 + zinc * 0.05 + spangle * 0.03
    metal_c = np.stack([metal, metal * 1.01, metal * 1.03], -1)
    rust_c = color([0.30, 0.11, 0.04]) * (0.7 + 0.6 * smooth(noise(n, rng, 20, 200, 0.5), -1, 1.5))[..., None]
    base = mix(metal_c, rust_c, rust)
    base = mix(base, color([0.1, 0.1, 0.1]), rivets * 0.8)
    rough = 0.38 + zinc * 0.05 + rust * 0.5 + spangle * 0.03
    h = 0.15 + prof * 0.7 + seam * 0.05 + rivets * 0.05 + rust * noise(n, rng, 80, 300, 0.4) * 0.01
    return base, rough, h, 0.03


@tile_set(2.0)
def asphalt_cracks(n, rng):
    y, x = coords(n)
    agg = noise(n, rng, 200, n // 2, 0.0)
    agg2 = noise(n, rng, 60, 200, 0.3)
    stones = smooth(agg, 1.0, 1.6)
    # crack network: Voronoi cell borders on the torus, warped
    pts = rng.random((26, 2))
    wy = noise(n, rng, 2, 16, 1.0) * 0.012
    wx = noise(n, rng, 2, 16, 1.0) * 0.012
    shift = (np.round(wy * n).astype(int), np.round(wx * n).astype(int))
    f1, f2 = torus_voronoi(n, pts)
    edge = f2 - f1
    yy, xx = np.indices((n, n))
    edge = edge[(yy + shift[0]) % n, (xx + shift[1]) % n]
    keep = smooth(noise(n, rng, 2, 6, 1.0), -0.6, 0.2)                 # not every border cracks
    width = 0.0012 + 0.0015 * smooth(noise(n, rng, 4, 30, 1.0), -1, 1.5)
    crack = (1 - smooth(edge, width * 0.4, width * 1.4)) * keep
    hair = (1 - smooth(np.abs(noise(n, rng, 6, 40, 1.0)), 0.0, 0.02)) * smooth(noise(n, rng, 2, 8, 1.0), 0.6, 1.2)
    crack = np.clip(crack + hair * 0.7, 0, 1)
    # darker sealed patch repairs
    patch = smooth(noise(n, rng, 1, 4, 1.3), 1.1, 1.25)
    wear = noise(n, rng, 1, 6, 1.0)
    g = 0.075 + stones * 0.05 + agg2 * 0.008 + wear * 0.008
    g = g * (1 - 0.35 * patch)
    base = np.stack([g, g, g * 1.03], -1)
    base = mix(base, color([0.02, 0.02, 0.02]), crack * 0.9)
    rough = 0.86 - stones * 0.1 - patch * 0.15 + crack * 0.1
    h = 0.6 + stones * 0.05 + agg2 * 0.01 - crack * 0.35 + patch * 0.01
    return base, rough, h, 0.01


# ------------------------------------------------------------ wallpapers
# Paper: a faint fibre texture, matte. Repeats are 0.5-1 m like real rolls.

def paper(n, rng):
    return noise(n, rng, 60, n // 2, 0.3) * 0.5 + noise(n, rng, 4, 30, 1.0) * 0.5


@tile_set(1.0)
def wallpaper_damask(n, rng):
    """Flocked damask: raised velvety motifs on a satin ground, half-drop repeat."""
    y, x = coords(n)
    cols, rows = 2, 2
    cx = x * cols
    col = np.floor(cx).astype(int)
    cy = y * rows + (col % 2) * 0.5                               # half drop
    u = (cx % 1.0) * 2 - 1
    v = (cy % 1.0) * 2 - 1
    au = np.abs(u)                                                # mirror symmetry
    px = 2.0 * cols / n
    r = np.hypot(au / 0.62, v / 0.9)
    th = np.arctan2(v, au)
    body = smooth(0.62 + 0.1 * np.cos(6 * th) - r, -px, px)          # lobed medallion
    hole = smooth(0.34 + 0.06 * np.cos(4 * th) - np.hypot(au / 0.5, v / 0.75), -px, px)
    core = smooth(0.12 - np.hypot(au, v + 0.05), -px, px)
    motif = np.clip(body - hole + core, 0, 1)
    for cu, cv, a, l, w in [(0.42, -0.62, -0.9, 0.24, 0.07), (0.5, 0.55, 0.8, 0.26, 0.08), (0.78, 0.05, 1.57, 0.2, 0.06),
                            (0.0, -0.86, 1.57, 0.12, 0.06), (0.0, 0.9, 1.57, 0.1, 0.05), (0.88, -0.78, -0.4, 0.14, 0.04)]:
        motif = np.maximum(motif, leaf(au, v, cu, cv, a, l, w, px))
    # scroll lines linking the medallions
    scroll = 1 - smooth(np.abs(au - (0.82 + 0.12 * np.sin(v * np.pi * 1.5))), 0.012, 0.02)
    motif = np.maximum(motif, scroll * (np.abs(v) > 0.35))
    fib = paper(n, rng)
    ground = srgb(0.36, 0.07, 0.1) * (1 + fib[..., None] * 0.03)
    flock = srgb(0.62, 0.18, 0.2) * (1 + noise(n, rng, n // 4, n // 2, 0.0)[..., None] * 0.08)
    base = mix(ground, flock, motif)
    rough = 0.38 + fib * 0.02 + motif * 0.5
    h = 0.48 + motif * 0.06 + fib * 0.003
    return base, rough, h, 0.0003


@tile_set(0.5)
def wallpaper_stripes(n, rng):
    """Regency stripe: sage and cream bands with a satin stripe and gold pinlines."""
    y, x = coords(n)
    u = (x * 2) % 1.0                                             # 25 cm repeat
    px = 2.0 / n
    band = lambda a, b: smooth(u - a, -px, px) * smooth(b - u, -px, px)
    wide = band(0.0, 0.42)
    satin = band(0.5, 0.62) + band(0.88, 1.0)
    pin = band(0.455, 0.465) + band(0.835, 0.845)
    fib = paper(n, rng)
    cream = srgb(0.93, 0.9, 0.8)
    sage = srgb(0.55, 0.62, 0.5)
    base = mix(cream, sage, wide)
    base = mix(base, srgb(0.86, 0.84, 0.74), satin)
    base = mix(base, srgb(0.78, 0.62, 0.3), pin)
    base = base * (1 + fib[..., None] * 0.025)
    rough = 0.75 - satin * 0.35 - pin * 0.4 + fib * 0.03
    h = 0.5 + fib * 0.01 + pin * 0.05
    return base, rough, h, 0.0005


@tile_set(0.6)
def wallpaper_floral(n, rng):
    """Scattered blossoms and leaves on a cream ground with a pin-dot."""
    y, x = coords(n)
    px = 1.0 / n
    g = 4
    base = srgb(0.94, 0.91, 0.84) * (1 + paper(n, rng)[..., None] * 0.02)
    dots = smooth(0.08 - np.hypot((x * 24) % 1 - 0.5, (y * 24) % 1 - 0.5), -0.05, 0.05)
    base = mix(base, srgb(0.8, 0.74, 0.62), dots * 0.6)
    ink = np.zeros((n, n))
    pal = [srgb(0.85, 0.42, 0.45), srgb(0.95, 0.7, 0.4), srgb(0.55, 0.45, 0.75), srgb(0.9, 0.55, 0.6)]
    leaf_c = srgb(0.35, 0.52, 0.36)
    for i in range(g):
        for j in range(g):
            pyc = (i + 0.2 + rng.random() * 0.6) / g
            pxc = (j + 0.2 + rng.random() * 0.6) / g
            s = 0.055 + rng.random() * 0.03
            rot = rng.random() * 6.28
            dy, dx = wrap_d(y - pyc), wrap_d(x - pxc)
            # two leaves first, then the flower over them
            for k in range(2):
                a = rot + 2.2 + k * 1.9
                lc = (s * 1.35 * np.cos(a), s * 1.35 * np.sin(a))
                lm = leaf(dx, dy, lc[0], lc[1], a, s * 0.9, s * 0.32, px)
                base = mix(base, leaf_c * (0.9 + 0.2 * rng.random()), lm)
                ink = np.maximum(ink, lm)
            r = np.hypot(dx, dy)
            th = np.arctan2(dy, dx) + rot
            petals = smooth(s * (0.55 + 0.45 * np.abs(np.cos(2.5 * th))) - r, -px, px)
            c = pal[rng.integers(len(pal))]
            base = mix(base, c * (1 - 0.25 * smooth(r / s, 0.2, 1.0))[..., None], petals)
            centre = smooth(s * 0.18 - r, -px, px)
            base = mix(base, srgb(0.95, 0.8, 0.35), centre)
            ink = np.maximum(ink, petals)
    rough = 0.72 - ink * 0.1
    h = 0.5 + ink * 0.04
    return base, rough, h, 0.0005


@tile_set(1.0)
def wallpaper_art_deco(n, rng):
    """Art deco fans: overlapping scallops with gold arcs and rays on deep teal."""
    y, x = coords(n)
    cols, rows = 4, 8
    R = 1.0 / rows                     # discs 2R apart in a row, rows R apart and offset by R: full cover
    best_d = np.full((n, n), 9.0)
    best_dy = np.zeros((n, n))
    best_dx = np.zeros((n, n))
    band = np.floor(y * rows).astype(int)
    for k in (0, -1):                                             # later (lower) rows win
        r_ = band + k
        shift = (r_ % 2) * 0.5
        i = np.round(x * cols - 0.5 - shift)
        cxp = (i + 0.5 + shift) / cols
        cyp = (r_ + 1) / rows
        dx = wrap_d(x - cxp)
        dy = y - cyp
        d = np.hypot(dx, dy) / R                                  # 1 at the rim
        take = (d < 1.0) & (best_d > 1.0)
        best_d = np.where(take, d, best_d)
        best_dy = np.where(take, dy, best_dy)
        best_dx = np.where(take, dx, best_dx)
    d = best_d
    th = np.arctan2(-best_dy, best_dx)                            # 0..pi over the visible top half
    px = 3.0 * rows / n
    rim = 1 - smooth(np.abs(d - 0.95), 0.0, px * 1.5)
    arc = 1 - smooth(np.abs(d - 0.6), 0.0, px)
    rays = (1 - smooth(np.abs(((th / np.pi) * 14) % 1.0 - 0.5) * 2, 0.0, 0.3)) * (d < 0.6) * (d > 0.25)
    gold = np.clip(rim + arc + rays * 0.8 + (d < 0.16), 0, 1)
    fib = paper(n, rng)
    teal = srgb(0.06, 0.26, 0.28) * (1 + fib[..., None] * 0.03)
    base = mix(teal * (0.85 + 0.15 * d[..., None]), srgb(0.85, 0.66, 0.32), gold)
    rough = 0.7 - gold * 0.45 + fib * 0.02
    h = 0.5 + gold * 0.03
    return base, rough, h, 0.0005


@tile_set(0.5)
def wallpaper_trellis(n, rng):
    """Mid-century trellis: a diamond lattice with dots at the crossings, mustard on charcoal."""
    y, x = coords(n)
    k = 5
    a = (x + y) * k
    b = (x - y) * k
    la = np.abs((a % 1.0) - 0.5)
    lb = np.abs((b % 1.0) - 0.5)
    px = k / n * 1.5
    line = 1 - smooth(np.minimum(la, lb), 0.025, 0.025 + px)
    node = 1 - smooth(np.hypot(la, lb), 0.1, 0.1 + px)
    inner = 1 - smooth(np.hypot(0.5 - la, 0.5 - lb), 0.05, 0.05 + px)
    fib = paper(n, rng)
    base = srgb(0.17, 0.18, 0.19) * (1 + fib[..., None] * 0.04)
    ink = np.clip(line + node + inner * 0.8, 0, 1)
    base = mix(base, srgb(0.86, 0.64, 0.2), ink)
    rough = 0.78 - ink * 0.15
    h = 0.5 + ink * 0.03
    return base, rough, h, 0.0005


# --------------------------------------------------------------- carpets
# Light, fairly neutral colours where it makes sense, so a layer's `tint`
# recolours them.

@tile_set(1.0)
def carpet_plush(n, rng):
    """Cut-pile plush carpet: dense fibre tips, tufts and pile shading. Neutral greige."""
    fib, tuft, shade = pile(n, rng)
    g = 0.42 + fib * 0.06 + tuft * 0.03 + shade * 0.015
    base = np.stack([g, g * 0.96, g * 0.9], -1)
    rough = 0.95 - shade * 0.02
    h = 0.5 + fib * 0.12 + tuft * 0.04
    return base, rough, h, 0.0012


@tile_set(0.5)
def carpet_berber(n, rng):
    """Berber loop pile: knobbly rows of loops in flecked oatmeal yarn."""
    y, x = coords(n)
    rows, loops = 50, 70
    ry = (y * rows) % 1.0
    row = np.floor(y * rows).astype(int)
    rx = (x * loops + (row % 2) * 0.5) % 1.0
    loop = np.sin(np.pi * ry) * (0.6 + 0.4 * np.sin(np.pi * rx))
    yarn = noise(n, rng, 80, n // 2, 0.2)
    fleck = noise(n, rng, 30, 160, 0.3)
    base = srgb(0.78, 0.72, 0.62) * (0.75 + 0.3 * loop)[..., None]
    base = mix(base, srgb(0.4, 0.34, 0.27), smooth(fleck, 1.1, 1.6))
    base = mix(base, srgb(0.95, 0.93, 0.88), smooth(-fleck, 1.3, 1.8) * 0.8)
    base = base * (1 + yarn[..., None] * 0.04)
    rough = np.full((n, n), 0.96)
    h = 0.2 + loop * 0.6 + yarn * 0.03
    return base, rough, h, 0.006


@tile_set(1.0)
def carpet_tiles(n, rng):
    """Office carpet tiles, 50 cm, laid quarter-turned: ribbed loop pile in charcoal blue."""
    y, x = coords(n)
    cy, cx = np.floor(y * 2).astype(int), np.floor(x * 2).astype(int)
    turned = (cy + cx) % 2 == 1
    ly, lx = (y * 2) % 1.0, (x * 2) % 1.0
    along = np.where(turned, lx, ly)
    rib = 0.5 + 0.5 * np.sin(2 * np.pi * along * 90)
    fib = noise(n, rng, n // 5, n // 2, 0.0)
    fleck = noise(n, rng, 40, 200, 0.3)
    tone = 1 + 0.06 * (rng.random((2, 2)) - 0.5)[cy, cx]
    base = srgb(0.2, 0.24, 0.3) * ((0.8 + 0.25 * rib) * tone)[..., None]
    base = mix(base, srgb(0.45, 0.5, 0.58), smooth(fleck, 1.2, 1.7) * 0.7)
    base = base * (1 + fib[..., None] * 0.05)
    seam = 1 - smooth(np.minimum(np.minimum(lx, 1 - lx), np.minimum(ly, 1 - ly)) * 0.5, 0.0004, 0.0015)
    base = base * (1 - 0.35 * seam[..., None])
    rough = np.full((n, n), 0.95)
    h = 0.4 + rib * 0.3 + fib * 0.05 - seam * 0.3
    return base, rough, h, 0.003


@tile_set(1.0)
def carpet_hotel(n, rng):
    """Bold hotel-corridor carpet: gold-edged red quatrefoils on navy, with small diamonds."""
    y, x = coords(n)
    k = 3
    u = ((x * k) % 1.0) * 2 - 1
    v = ((y * k) % 1.0) * 2 - 1
    px = 2.0 * k / n * 1.5
    r = np.hypot(u, v)
    th = np.arctan2(v, u)
    shape = 0.62 * (0.78 + 0.22 * np.cos(4 * th))
    fill = smooth(shape - r, -px, px)
    edge = smooth(shape - r, -px, px) * (1 - smooth(shape - r, 0.05, 0.05 + px))
    inner = smooth(0.18 - (np.abs(u) + np.abs(v)), -px, px)
    du, dv = np.abs(np.abs(u) - 1), np.abs(np.abs(v) - 1)
    diamond = smooth(0.16 - (du + dv), -px, px)
    fib, tuft, shade = pile(n, rng)
    navy = srgb(0.08, 0.1, 0.25)
    base = mix(navy, srgb(0.6, 0.08, 0.1), fill)
    base = mix(base, srgb(0.85, 0.62, 0.25), np.clip(edge + inner + diamond, 0, 1))
    base = base * (1 + fib[..., None] * 0.08 + tuft[..., None] * 0.04 + shade[..., None] * 0.03)
    rough = np.full((n, n), 0.95)
    h = 0.5 + fib * 0.1 + tuft * 0.06
    return base, rough, h, 0.003


# ---------------------------------------------------------------- floors

OAK = (srgb(0.72, 0.52, 0.32), srgb(0.5, 0.33, 0.18))          # earlywood, latewood


def wood_color(late, pores, fleck, tone, light=OAK[0], dark=OAK[1]):
    c = mix(light, dark, late * 0.8 + pores * 0.3)
    return c * (tone * (1 + fleck * 0.04))[..., None]


@tile_set(1.0)
def wood_planks(n, rng):
    """Oak floorboards, 14 cm wide, random joints, satin lacquer, eased edges."""
    y, x = coords(n)
    rows = 7
    row = np.floor(y * rows).astype(int)
    ly = (y * rows) % 1.0
    joints = np.sort(rng.random((rows, 2)), axis=1)
    j0, j1 = joints[row, 0], joints[row, 1]
    seg = ((x >= j0) & (x < j1)).astype(int)
    ids = row * 2 + seg
    v = rng.random((rows * 2, 3))[ids]
    # each board takes its own slice of a big grain field
    late, pores, fleck = wood_rings(n, rng, 38)
    off = (v[..., 0] * n).astype(int)
    yy, xx = np.indices((n, n))
    late, pores, fleck = (a[(yy + off) % n, xx] for a in (late, pores, fleck))
    base = wood_color(late, pores, fleck, 0.8 + 0.35 * v[..., 1])
    dj = np.minimum(np.abs(wrap_d(x - j0)), np.abs(wrap_d(x - j1)))
    de = np.minimum(np.minimum(ly, 1 - ly) / rows, dj)
    gap = 1 - smooth(de, 0.0006, 0.0022)
    base = mix(base, srgb(0.12, 0.08, 0.05), gap)
    rough = 0.38 + pores * 0.15 + v[..., 2] * 0.06 + gap * 0.4
    h = 0.55 + smooth(de, 0.0, 0.004) * 0.05 - pores * 0.01 - gap * 0.2
    return base, rough, h, 0.004


@tile_set(1.0)
def parquet_herringbone(n, rng):
    """Herringbone parquet: 6 x 25 cm oak slats, alternating direction."""
    L, P = 4, 16                                                  # slat length in widths; widths per tile
    y, x = coords(n)
    X, Y = x * P, y * P
    sid = np.full((n, n), -1)
    lu = np.zeros((n, n))                                         # along the slat 0..1
    lv = np.zeros((n, n))                                         # across 0..1
    horiz = np.zeros((n, n), dtype=bool)
    # slats: H(k,j) = [k+jL, k+jL+L) x [k-jL, k-jL+1), V(k,j) = [k+jL, k+jL+1) x [k-jL+1, k-jL+1+L)
    half = P // (2 * L)
    for j in range(-P, P + 1):
        k = np.floor(Y + j * L)                                   # H: row of the slat
        ax = X - k - j * L
        hit = (ax >= 0) & (ax < L) & (sid < 0)
        kk = k - np.floor_divide(j, half) * (P // 2) if half else k
        canon = ((np.mod(j, half) if half else 0) * P + np.mod(kk, P)).astype(int)
        sid = np.where(hit, canon * 2, sid)
        lu = np.where(hit, ax / L, lu)
        lv = np.where(hit, Y + j * L - k, lv)
        horiz |= hit
        k2 = np.floor(X - j * L)                                  # V: column of the slat
        ay = Y - k2 + j * L - 1
        hit = (ay >= 0) & (ay < L) & (sid < 0)
        kk = k2 - np.floor_divide(j, half) * (P // 2) if half else k2
        canon = ((np.mod(j, half) if half else 0) * P + np.mod(kk, P)).astype(int)
        sid = np.where(hit, canon * 2 + 1, sid)
        lu = np.where(hit, ay / L, lu)
        lv = np.where(hit, X - j * L - k2, lv)
    sid = np.maximum(sid, 0)
    v = rng.random((sid.max() + 1, 3))[sid]
    late_h, pores_h, fleck_h = wood_rings(n, rng, 60)
    late_v, pores_v, fleck_v = (np.ascontiguousarray(a.T) for a in wood_rings(n, rng, 60))
    off = (v[..., 0] * n).astype(int)
    yy, xx = np.indices((n, n))
    pick = lambda a, b: np.where(horiz, a[(yy + off) % n, xx], b[yy, (xx + off) % n])
    late, pores, fleck = pick(late_h, late_v), pick(pores_h, pores_v), pick(fleck_h, fleck_v)
    base = wood_color(late, pores, fleck, 0.78 + 0.4 * v[..., 1])
    w = 1.0 / P
    de = np.minimum(np.minimum(lv, 1 - lv) * w, np.minimum(lu, 1 - lu) * w * L)
    gap = 1 - smooth(de, 0.0004, 0.0016)
    base = mix(base, srgb(0.14, 0.09, 0.05), gap)
    rough = 0.32 + pores * 0.15 + v[..., 2] * 0.08 + gap * 0.4
    h = 0.55 - pores * 0.01 - gap * 0.2 + smooth(de, 0, 0.003) * 0.03
    return base, rough, h, 0.003


def marble_veins(n, rng, sharp=0.06):
    """Wavy marble veins (0..1) where turbulent noise crosses zero, plus cloudiness."""
    a = noise(n, rng, 1, 10, 1.3) + 0.35 * noise(n, rng, 10, 40, 1.0)
    dy, dx = noise(n, rng, 1, 6, 1.2) * n * 0.03, noise(n, rng, 1, 6, 1.2) * n * 0.03
    a = warp(a, dy, dx)
    veins = 1 - smooth(np.abs(a), 0.0, sharp)
    fine = 1 - smooth(np.abs(noise(n, rng, 6, 40, 1.0)), 0.0, sharp * 0.5)
    cloud = noise(n, rng, 1, 8, 1.2)
    return veins, fine, cloud


@tile_set(1.2)
def floor_checker(n, rng):
    """Black and white marble checkerboard, 30 cm tiles, polished, fine grout."""
    y, x = coords(n)
    k = 4
    cy, cx = np.floor(y * k).astype(int), np.floor(x * k).astype(int)
    white = (cy + cx) % 2 == 0
    veins, fine, cloud = marble_veins(n, rng)
    wm = srgb(0.9, 0.89, 0.86) * (1 + cloud[..., None] * 0.02)
    wm = mix(wm, srgb(0.55, 0.56, 0.58), veins * 0.7 + fine * 0.25)
    bm = srgb(0.05, 0.05, 0.055) * (1 + cloud[..., None] * 0.15)
    bm = mix(bm, srgb(0.6, 0.6, 0.58), veins * 0.5 + fine * 0.15)
    base = np.where(white[..., None], wm, bm)
    ly, lx = (y * k) % 1.0, (x * k) % 1.0
    de = np.minimum(np.minimum(lx, 1 - lx), np.minimum(ly, 1 - ly)) * 1.2 / k
    grout = 1 - smooth(de, 0.0008, 0.0016)
    base = mix(base, srgb(0.45, 0.44, 0.42), grout)
    rough = np.where(grout > 0.5, 0.85, 0.08 + veins * 0.04)
    h = 0.6 - grout * 0.3
    return base, rough, h, 0.002


@tile_set(1.0)
def floor_hex_tiles(n, rng):
    """Small white hexagon mosaic (about 4 cm) with scattered black tiles, grey grout."""
    y, x = coords(n)
    cols, R2 = 26, 15                                             # cols ~ sqrt(3) * R2 keeps the hexes regular
    w, h2 = 1.0 / cols, 1.0 / R2
    f1 = np.full((n, n), 9.0)
    f2 = np.full((n, n), 9.0)
    ids = np.zeros((n, n), dtype=int)
    for lat, (ox, oy) in enumerate([(0.0, 0.0), (0.5, 0.5)]):
        gi = np.floor(x / w - ox)
        gj = np.floor(y / h2 - oy)
        for di in (0, 1):
            for dj in (0, 1):
                i, j = gi + di, gj + dj
                d = np.hypot(wrap_d(x - (i + ox) * w), wrap_d(y - (j + oy) * h2))
                cid = ((np.mod(j, R2) * cols + np.mod(i, cols)) * 2 + lat).astype(int)
                closer = d < f1
                f2 = np.where(closer, f1, np.minimum(f2, d))
                ids = np.where(closer, cid, ids)
                f1 = np.minimum(f1, d)
    edge = (f2 - f1) * 0.5
    grout = 1 - smooth(edge, 0.0009, 0.0018)
    v = rng.random((cols * R2 * 2, 2))[ids]
    black = v[..., 0] < 0.07
    tile_c = np.where(black[..., None], srgb(0.06, 0.06, 0.065), srgb(0.9, 0.9, 0.88) * (0.97 + 0.05 * v[..., 1])[..., None])
    base = mix(tile_c, srgb(0.55, 0.54, 0.52), grout)
    rough = np.where(grout > 0.5, 0.9, 0.12 + v[..., 1] * 0.05)
    hgt = 0.6 - grout * 0.35 + smooth(edge, 0.0, 0.004) * 0.04
    return base, rough, hgt, 0.002


@tile_set(1.0)
def terrazzo(n, rng):
    """Polished terrazzo: angular marble chips of several colours in a cream cement."""
    f1, f2, ids = grid_voronoi(n, 34, rng)
    v = rng.random((34 * 34, 3))[ids]
    chip = smooth((f2 - f1) * 0.5, 0.002 + v[..., 1] * 0.004, 0.0035 + v[..., 1] * 0.004) * (v[..., 0] < 0.55)
    s1, s2, sid = grid_voronoi(n, 110, rng)
    sv = rng.random((110 * 110, 2))[sid]
    speck = (1 - smooth(s1, 0.0015, 0.0025)) * (sv[..., 0] < 0.5)
    pal = np.array([srgb(0.95, 0.94, 0.9), srgb(0.55, 0.55, 0.56), srgb(0.12, 0.12, 0.13), srgb(0.75, 0.42, 0.3), srgb(0.45, 0.55, 0.45), srgb(0.85, 0.75, 0.6)])
    cc = pal[(v[..., 2] * len(pal)).astype(int) % len(pal)]
    sc = pal[(sv[..., 1] * len(pal)).astype(int) % len(pal)]
    matrix = srgb(0.86, 0.83, 0.76) * (1 + noise(n, rng, 20, n // 2, 0.4)[..., None] * 0.03)
    base = mix(mix(matrix, sc, speck), cc, chip)
    rough = 0.16 + noise(n, rng, 2, 10, 1.0) * 0.03
    h = 0.5 + chip * 0.004
    return base, rough, h, 0.002


@tile_set(2.0)
def marble(n, rng):
    """Carrara-style white marble slab: soft grey veining and cloudiness, honed."""
    veins, fine, cloud = marble_veins(n, rng, 0.08)
    base = srgb(0.92, 0.91, 0.89) * (1 + cloud[..., None] * 0.025)
    base = mix(base, srgb(0.5, 0.52, 0.55), veins * 0.75)
    base = mix(base, srgb(0.7, 0.71, 0.72), fine * 0.4)
    rough = 0.12 + veins * 0.05 + cloud * 0.01
    h = 0.5 - veins * 0.003
    return base, rough, h, 0.001


@tile_set(1.0)
def diamond_plate(n, rng):
    """Steel tread plate: raised lozenges in alternating directions, scuffed tops."""
    y, x = coords(n)
    g = 24
    iy, ix = np.floor(y * g).astype(int), np.floor(x * g).astype(int)
    u, v = (x * g) % 1.0 - 0.5, (y * g) % 1.0 - 0.5
    flip = np.where((iy + ix) % 2 == 0, 1.0, -1.0)
    s = (u + flip * v) * 0.7071
    t = (u - flip * v) * 0.7071
    lz = np.abs(s) / 0.42 + np.abs(t) / 0.075
    px = g / n * 2
    raised = smooth(1.0 - lz, -px * 4, px * 4)
    crown = np.clip(1 - lz, 0, 1) ** 0.5
    scr = smooth(aniso_noise(n, rng, 30, n // 2, 0.4, 10.0), 1.3, 2.2)
    grime = smooth(noise(n, rng, 3, 20, 1.0), 0.8, 2.2)
    g0 = 0.52 + noise(n, rng, 4, 40, 1.0) * 0.03
    base = np.stack([g0, g0 * 1.01, g0 * 1.03], -1)
    base = base * (0.85 + raised[..., None] * (0.3 + 0.1 * crown[..., None]) + scr[..., None] * 0.12)
    base = mix(base, srgb(0.2, 0.18, 0.16), grime * (1 - raised) * 0.35)
    rough = 0.45 - raised * 0.15 - scr * 0.1 + grime * 0.25
    h = 0.3 + raised * (0.4 + crown * 0.15)
    return base, rough, h, 0.002


@tile_set(1.0)
def rubber_studs(n, rng):
    """Studded rubber flooring: round raised coins on a fine-textured dark grey sheet."""
    y, x = coords(n)
    g = 20
    u, v = (x * g) % 1.0 - 0.5, (y * g) % 1.0 - 0.5
    r = np.hypot(u, v)
    px = g / n * 1.5
    stud = smooth(0.3 - r, -px, px)
    dome = np.clip(1 - r / 0.3, 0, 1) ** 0.4
    tex = noise(n, rng, 80, n // 2, 0.2)
    g0 = 0.055 + tex * 0.004 + stud * 0.01
    base = np.stack([g0, g0, g0 * 1.05], -1)
    rough = 0.8 - stud * 0.15 + tex * 0.03
    h = 0.4 + stud * (0.25 + dome * 0.1) + tex * 0.01
    return base, rough, h, 0.003


# ----------------------------------------------------------------- walls

@tile_set(0.9)
def subway_tiles(n, rng):
    """Glossy white 7.5 x 15 cm metro tiles in running bond, bevelled edges, grey grout."""
    rows, cols = 12, 6
    row, col, lx, ly = cells(n, rows, cols)
    ids = row * cols + col
    bw, bh = 0.9 / cols, 0.9 / rows
    d = edge_dist(lx, ly, bw, bh)
    grout = 1 - smooth(d, 0.0012, 0.002)
    bevel = smooth(d, 0.0015, 0.007)
    v = per_cell(rng, ids, 2)
    wave = noise(n, rng, 2, 30, 1.0)
    tile = srgb(0.93, 0.93, 0.91) * (0.97 + 0.04 * v[..., 0])[..., None] * (1 + wave[..., None] * 0.01)
    base = mix(tile, srgb(0.6, 0.6, 0.58), grout)
    rough = np.where(grout > 0.5, 0.9, 0.06 + v[..., 1] * 0.04)
    h = 0.3 + (1 - grout) * (0.3 + bevel * 0.15) + wave * 0.003
    return base, rough, h, 0.004


@tile_set(2.0)
def plaster(n, rng):
    """Hand-trowelled plaster: soft lumps, trowel sweeps and fine sand. Off-white, tintable."""
    lump = noise(n, rng, 2, 20, 1.3)
    sweep = warp(aniso_noise(n, rng, 2, 40, 1.0, 4.0), noise(n, rng, 1, 4, 1.0) * n * 0.05, 0)
    sand = noise(n, rng, 120, n // 2, 0.0)
    g = 0.78 + lump * 0.02 + sweep * 0.015
    base = np.stack([g, g * 0.985, g * 0.96], -1) * (1 + sand[..., None] * 0.015)
    rough = 0.82 - smooth(sweep, 0.8, 2.0) * 0.2 + sand * 0.03
    h = 0.5 + lump * 0.08 + sweep * 0.05 + sand * 0.01
    return base, rough, h, 0.004


# ------------------------------------------------------- surface materials

@tile_set(1.0)
def wood_grain(n, rng):
    """A plain run of oak grain along x for furniture, doors and trim (UV or triplanar)."""
    late, pores, fleck = wood_rings(n, rng, 30)
    base = wood_color(late, pores, fleck, 1.0 + noise(n, rng, 1, 4, 1.0) * 0.05)
    rough = 0.45 + pores * 0.15 + late * 0.05
    h = 0.5 - pores * 0.02 + late * 0.005
    return base, rough, h, 0.002


@tile_set(0.3)
def leather(n, rng):
    """Pebble-grain leather: rounded grains, creases and a soft sheen. Mid tan, tintable."""
    f1, f2, ids = grid_voronoi(n, 70, rng)
    edge = (f2 - f1) * 0.5 * 70                                   # 0 at grain borders
    grain = smooth(edge, 0.0, 0.25) ** 0.6
    crease = 1 - smooth(np.abs(noise(n, rng, 2, 14, 1.2)), 0.0, 0.04)
    v = rng.random((70 * 70,))[ids]
    tone = 0.85 + noise(n, rng, 1, 8, 1.2) * 0.06 + v * 0.04
    base = srgb(0.62, 0.42, 0.26) * (tone * (0.82 + 0.18 * grain) * (1 - 0.25 * crease))[..., None]
    rough = 0.6 - grain * 0.15 + crease * 0.1
    h = 0.46 + grain * 0.1 - crease * 0.05
    return base, rough, h, 0.0008


@tile_set(0.1)
def linen(n, rng):
    """Plain-weave linen: over-under threads with slubs. Natural flax, tintable."""
    y, x = coords(n)
    T = 64
    i, j = np.floor(x * T).astype(int), np.floor(y * T).astype(int)
    lx, ly = (x * T) % 1.0, (y * T) % 1.0
    warp_up = (i + j) % 2 == 0
    prof_w = np.sin(np.pi * lx)                                   # across a warp thread
    prof_f = np.sin(np.pi * ly)
    slub_w = 1 + 0.25 * (rng.random(T) - 0.5)[i] + 0.08 * noise(n, rng, 4, 40, 1.0)
    slub_f = 1 + 0.25 * (rng.random(T) - 0.5)[j]
    top = np.where(warp_up, prof_w * slub_w, prof_f * slub_f)
    base = srgb(0.78, 0.72, 0.6) * (0.7 + 0.35 * top)[..., None]
    base = base * (1 + noise(n, rng, 30, n // 2, 0.3)[..., None] * 0.03)
    rough = np.full((n, n), 0.88)
    h = 0.3 + top * 0.5
    return base, rough, h, 0.0004


@tile_set(0.1)
def denim(n, rng):
    """3/1 twill denim: indigo warp diagonals over white weft, with a washed fade."""
    y, x = coords(n)
    T = 96
    i, j = np.floor(x * T).astype(int), np.floor(y * T).astype(int)
    lx, ly = (x * T) % 1.0, (y * T) % 1.0
    warp_up = (i + j) % 4 != 0
    top = np.where(warp_up, np.sin(np.pi * lx), np.sin(np.pi * ly))
    fade = smooth(noise(n, rng, 2, 12, 1.0), 0.0, 2.5) * 0.6
    slub = noise(n, rng, 4, 60, 0.8) * 0.06
    indigo = mix(srgb(0.12, 0.2, 0.38), srgb(0.42, 0.52, 0.66), fade * 0.6 + slub)
    weft = srgb(0.6, 0.62, 0.66)
    base = np.where(warp_up[..., None], indigo, weft) * (0.72 + 0.3 * top)[..., None]
    rough = np.full((n, n), 0.9)
    h = 0.3 + top * 0.5
    return base, rough, h, 0.0004


@tile_set(0.05)
def carbon_fibre(n, rng):
    """2x2 twill carbon fibre under clear resin: woven tows with a rounded sheen."""
    y, x = coords(n)
    T = 16
    i, j = np.floor(x * T).astype(int), np.floor(y * T).astype(int)
    lx, ly = (x * T) % 1.0, (y * T) % 1.0
    horiz = ((i + j) // 2) % 2 == 0
    across = np.where(horiz, ly, lx)
    along = np.where(horiz, lx, ly)
    sheen = np.sin(np.pi * across) ** 2
    fibres = 1 + 0.08 * np.sin(2 * np.pi * across * 18)
    g = (0.025 + 0.06 * sheen * fibres) * (1 - 0.15 * np.abs(along - 0.5))
    base = np.stack([g, g, g * 1.08], -1)
    rough = 0.18 + (1 - sheen) * 0.1
    h = 0.4 + np.sin(np.pi * across) * 0.25
    return base, rough, h, 0.0003


@tile_set(0.5)
def hammered_metal(n, rng):
    """Hand-hammered sheet: overlapping round dimples with bright facet edges. Neutral grey."""
    f1, f2, ids = grid_voronoi(n, 16, rng, 0.8)
    r = f1 * 16                                                   # 0 at a blow's centre
    dimple = -(np.clip(1 - r / 0.75, 0, 1) ** 2)
    ridge = 1 - smooth((f2 - f1) * 16, 0.0, 0.12)
    g = 0.62 + ridge * 0.06 + noise(n, rng, 4, 40, 1.0) * 0.02
    base = np.stack([g, g, g * 1.01], -1)
    rough = 0.28 + ridge * -0.08 + noise(n, rng, 30, n // 2, 0.3) * 0.02
    h = 0.6 + dimple * 0.4 + ridge * 0.03
    return base, rough, h, 0.003


@tile_set(0.6)
def bark_fissured(n, rng):
    """Fissured bark (oak, old pine): deep fissures running up the image (v)
    between rounded corky plates, the plates broken by cross-checks, their
    tops weathered grey, a few lichen patches. Triplanar on trunks and roots
    (image up = world up)."""
    # fissures follow the zero lines of a field ~5x longer vertically than across
    f = aniso_noise(n, rng, 2, 30, 1.6, 5.0).T + 0.3 * aniso_noise(n, rng, 6, 60, 1.0, 3.0).T
    fiss = 1 - smooth(np.abs(f), 0.05, 0.45)
    # here and there a horizontal check splits a plate into blocks
    cross = (1 - smooth(np.abs(aniso_noise(n, rng, 4, 40, 1.2, 4.0)), 0.0, 0.08)) * smooth(noise(n, rng, 2, 12, 1.0), 0.0, 0.8)
    plate = smooth(np.abs(f), 0.1, 1.2) ** 0.8 * (1 - 0.7 * cross)  # rounded plate tops
    fibre = aniso_noise(n, rng, 20, n // 2, 0.6, 5.0).T
    h = 0.1 + 0.75 * plate + fibre * 0.025 + noise(n, rng, 6, 40, 1.0) * 0.03
    tone = 1 + noise(n, rng, 2, 16, 1.2) * 0.12
    base = mix(srgb(0.09, 0.055, 0.035), srgb(0.27, 0.2, 0.15), smooth(h, 0.15, 0.7)) * tone[..., None]
    weather = smooth(plate, 0.55, 1.0) * smooth(noise(n, rng, 2, 10, 1.2), -0.8, 1.0)
    base = mix(base, srgb(0.45, 0.43, 0.39), weather * 0.5)
    lichen = smooth(noise(n, rng, 10, 60, 1.0), 2.0, 2.6) * smooth(plate, 0.5, 0.9)
    base = mix(base, srgb(0.56, 0.6, 0.46), lichen * 0.75)
    rough = 0.8 + fiss * 0.12 - lichen * 0.05
    return base, rough, h, 0.015


@tile_set(0.7)
def end_grain(n, rng):
    """A sawn stump / log end 0.7 m across, pith near the centre: growth rings
    (wide when young, then narrowing, good and bad years, wobbling), dark
    heartwood inside pale sapwood, radial drying checks from the rim, saw
    marks and grey weathering. Not a repeating tile: map it once over the cut
    (planar UV, tiling 1); generate it at 2048 so the rings don't alias."""
    y, x = coords(n)
    S = 0.35
    px, py = (x - 0.5) * 2 * S, (y - 0.5) * 2 * S                 # metres from the image centre
    dx, dy = px - 0.018, py + 0.012                                # the pith sits a little off centre
    r, a = np.hypot(dx, dy), np.arctan2(dy, dx)
    wob = sum(rng.normal(0, 0.012 / k) * np.cos(k * a + rng.uniform(0, 2 * np.pi)) for k in range(2, 7))
    rr = r * (1 + wob) + noise(n, rng, 3, 20, 1.2) * 0.0015
    years = 90
    w = (0.0055 * np.exp(-np.arange(years) / 40) + 0.0018) * np.exp(rng.normal(0, 0.3, years))
    edges = np.concatenate([[0.0], np.cumsum(w / w.sum() * S)])
    t = np.interp(rr, edges, np.arange(years + 1)) % 1.0
    late = smooth(t, 0.62, 0.9) * (1 - smooth(t, 0.96, 1.0))      # dark latewood closes each year
    heart = 1 - smooth(rr, S * 0.55, S * 0.75)
    light = mix(srgb(0.80, 0.64, 0.44), srgb(0.62, 0.42, 0.26), heart)
    dark = mix(srgb(0.58, 0.42, 0.27), srgb(0.40, 0.25, 0.14), heart)
    base = mix(light, dark, late * 0.85)
    # drying checks: wedges from the rim inwards, slightly curved
    checks = np.zeros((n, n))
    for _ in range(7):
        th, length, width = rng.uniform(-np.pi, np.pi), rng.uniform(0.35, 0.9) * S, rng.uniform(0.0015, 0.004)
        bend = rng.normal(0, 0.15)
        dist = np.abs(np.angle(np.exp(1j * (a - th - bend * r / S)))) * r
        wide = width * smooth(r, S - length, S)
        checks = np.maximum(checks, (1 - smooth(dist, wide * 0.3, wide + 1e-6)) * (wide > 1e-5))
    pith = 1 - smooth(r, 0.002, 0.006)
    saw = 0.5 + 0.5 * np.sin((px * np.cos(0.4) + py * np.sin(0.4) + 0.02 * np.sin(py * 40)) * 2 * np.pi / 0.006)
    grey = smooth(noise(n, rng, 3, 24, 1.4), 0.3, 1.5) * 0.25 + smooth(r, S * 0.75, S) * 0.25
    base = mix(base, srgb(0.55, 0.53, 0.5), grey)
    base = mix(base, srgb(0.08, 0.05, 0.03), checks)
    base = mix(base, srgb(0.25, 0.15, 0.08), pith)
    h = 0.6 - late * 0.03 + saw * 0.01 - checks * 0.5 - pith * 0.1 + noise(n, rng, 20, 200, 0.8) * 0.01
    rough = 0.75 + late * 0.05 + checks * 0.2 + grey * 0.1
    return base, rough, h, 0.006


def lap(h):
    """Periodic 5-point Laplacian (per pixel^2): < 0 on bumps, > 0 in hollows."""
    return np.roll(h, 1, 0) + np.roll(h, -1, 0) + np.roll(h, 1, 1) + np.roll(h, -1, 1) - 4 * h


def gblur(x, sigma):
    """Periodic Gaussian blur (sigma in px) through the FFT."""
    n = x.shape[0]
    f = np.fft.fftfreq(n)
    fy, fx = np.meshgrid(f, f, indexing="ij")
    g = np.exp(-2 * (np.pi * sigma) ** 2 * (fx * fx + fy * fy))
    if x.ndim == 3:
        return np.stack([np.real(np.fft.ifft2(np.fft.fft2(x[..., c]) * g)) for c in range(x.shape[2])], -1)
    return np.real(np.fft.ifft2(np.fft.fft2(x) * g))


# granite minerals: share, weathering rate (relative), sRGB colour, roughness
GRANITE = [
    ("quartz", 0.30, 0.12, (0.60, 0.60, 0.58), 0.42),
    ("k-feldspar", 0.35, 1.00, (0.74, 0.58, 0.50), 0.70),
    ("plagioclase", 0.23, 0.85, (0.83, 0.81, 0.75), 0.74),
    ("biotite", 0.12, 2.40, (0.07, 0.07, 0.07), 0.50),
]


def granite(n, size_m=0.4, years=1.0):
    """Weathered granite by simulation, not by look.

    The rock is a mosaic of crystals: big rounded k-feldspar phenocrysts
    (~14 mm) in a groundmass of small grains (~4.5 mm), boundaries warped. Each
    crystal's mineral sets how fast it weathers (quartz barely, feldspars
    ~8x faster, biotite mica fastest); grain boundaries are weaker still
    (granular disintegration). The surface then erodes step by step:

        dh/dt = -rate(mineral) * exposure(curvature) + D * lap(h)

    exposure > 1 on convex spots (more surface open to water and frost),
    < 1 in hollows; the diffusion term rounds every edge. Quartz ends up
    standing proud, mica leaves pits, feldspar sits between. Returns the
    height (0..1), the mineral index per pixel, the crystal boundary mask and
    the per-crystal random value, all seamless.
    """
    rng = np.random.default_rng(1234)                              # the same rock for every set built on it
    # groundmass: small grains of every mineral (~4.5 mm)
    gs = int(round(size_m / 0.0045))
    f1s, f2s, ids_s = grid_voronoi(n, gs, rng, 1.0)
    share = np.array([0.38, 0.17, 0.30, 0.15])                     # quartz, k-feldspar, plagioclase, biotite
    small_min = rng.choice(len(GRANITE), size=gs * gs, p=share / share.sum())
    small_var = rng.random(gs * gs)
    # phenocrysts: big rounded k-feldspar crystals (~14 mm) set in it
    gb = int(round(size_m / 0.014))
    f1b, _, ids_b = grid_voronoi(n, gb, rng, 0.9)
    has_ph = rng.random(gb * gb) < 0.35
    rad = 0.25 + 0.15 * rng.random(gb * gb)                        # crystal radius in cell units
    rb = f1b * gb
    in_ph = has_ph[ids_b] & (rb < rad[ids_b])
    mineral = np.where(in_ph, 1, small_min[ids_s])
    var = np.where(in_ph, rng.random(gb * gb)[ids_b], small_var[ids_s])
    edge = np.where(in_ph, 0.0, 1 - smooth((f2s - f1s) * gs, 0.0, 0.14))
    edge = np.maximum(edge, has_ph[ids_b] * (1 - smooth(np.abs(rb - rad[ids_b]), 0.0, 0.03)))
    # crystals don't grow as polygons: warp the whole mosaic a little
    wy, wx = (noise(n, rng, 8, 40, 1.0) * 2.5 * n / 1024 for _ in range(2))
    mineral, var, edge = warp(mineral, wy, wx), warp(var, wy, wx), warp(edge, wy, wx)
    rate = np.array([m[2] for m in GRANITE])[mineral] * (0.8 + 0.4 * var)
    rate = rate * (1 + 1.6 * edge)                                  # grain boundaries weather first
    rate = rate * np.exp(0.35 * noise(n, rng, 1, 6, 1.4))          # slower / faster patches of rock
    h = noise(n, rng, 20, n // 4, 0.5) * 0.01
    steps = int(180 * years)
    for _ in range(steps):
        L = lap(h)
        exposure = np.clip(1 - 0.8 * np.tanh(L / (L.std() + 1e-9)), 0.25, 1.8)
        h = h - 0.01 * rate * exposure + 0.035 * L
    lo, hi = np.percentile(h, [1.0, 99.5])                          # a few deep pits must not flatten the rest
    h = np.clip((h - lo) / (hi - lo + 1e-9), 0, 1)
    return h, mineral, edge, var


def granite_maps(n, h, mineral, edge, var):
    """Colour, roughness from the simulated surface: mineral colours, a grey
    weathering patina on what stands out, iron stains bled from the mica,
    grime settled in the pits."""
    cols = np.array([srgb(*m[3]) for m in GRANITE])
    base = cols[mineral] * (0.88 + 0.24 * var)[..., None]
    cavity = np.clip(gblur(h, 3) - h, 0, None)
    cavity = cavity / (cavity.max() + 1e-9)
    patina = 0.35 + 0.35 * smooth(h, 0.4, 0.9)
    base = mix(base, srgb(0.56, 0.55, 0.51), patina)
    mica = (mineral == 3).astype(float)
    halo = np.clip(gblur(mica, 2.5) - mica, 0, 1)                   # iron leached out round each flake
    base = mix(base, srgb(0.55, 0.36, 0.2), np.clip(halo * 1.2, 0, 0.3))
    base = mix(base, srgb(0.13, 0.11, 0.09), smooth(cavity, 0.05, 0.6) * 0.6 + edge * 0.12)
    rough = np.array([m[4] for m in GRANITE])[mineral]
    rough = mix(rough, 0.86, patina) + cavity * 0.15
    return base, np.clip(rough, 0, 1)


@tile_set(0.4)
def granite_weathered(n, rng):
    """Granite weathered by simulation (see `granite`): quartz grains proud,
    feldspar softened, mica pits, crystal boundaries etched, a grey patina on
    the exposed grains, iron stains, grime in the hollows. Triplanar on
    boulders, tile_size 0.4."""
    h, mineral, edge, var = granite(n)
    base, rough = granite_maps(n, h, mineral, edge, var)
    return base, rough, h, 0.002


def lichen_colonies(n, size_m=0.4, years=48.0, spores=34, seed=77):
    """Crustose lichen grown on the tile: a Johnson-Mehl tessellation.

    Spores land at random times t0 and each colony grows radially at its own
    rate g (crustose lichens: ~0.5-1.5 mm a year, the basis of
    lichenometry). A point is reached by colony i at a_i = t0_i + d_i / g_i
    (d on the torus, its margin made lobed by noise); the first colony to
    arrive owns it, so neighbours stop where they meet. Covered where
    a < years. Old centres die back (age > ~35 y), leaving rings; the young
    margin is the dark prothallus; the living thallus cracks into areoles.
    Returns coverage 0..1, colony id, age at each point, prothallus rim and
    areole cracks.
    """
    rng = np.random.default_rng(seed)
    y, x = coords(n)
    t0 = rng.uniform(0, years, spores)
    gr = np.clip(rng.normal(1.0, 0.25, spores), 0.4, 1.6) / 1000 / size_m   # tile units a year
    pos = rng.random((spores, 2))
    lobes = noise(n, rng, 6, 40, 1.0)
    best = np.full((n, n), np.inf)
    who = np.zeros((n, n), dtype=int)
    for i in range(spores):
        dx = np.abs(x - pos[i, 1])
        dx = np.minimum(dx, 1 - dx)
        dy = np.abs(y - pos[i, 0])
        dy = np.minimum(dy, 1 - dy)
        d = np.sqrt(dx * dx + dy * dy)
        a = t0[i] + d / gr[i] * (1 + 0.12 * lobes)
        closer = a < best
        best = np.where(closer, a, best)
        who = np.where(closer, i, who)
    age = years - best                                              # years since the colony reached this point
    # old centres crumble: the thallus breaks up into scattered fragments, not a fade
    crumbs = smooth(noise(n, rng, 40, 200, 0.6), 0.2, 0.9)
    alive = smooth(age, 0.0, 1.5) * (1 - smooth(age, 34.0, 37.0) * (1 - 0.7 * crumbs))
    rim = smooth(age, 0.0, 0.6) * (1 - smooth(age, 1.0, 2.5))      # the dark advancing margin
    f1, f2, _ = grid_voronoi(n, int(size_m / 0.0016), rng)         # ~1.6 mm areoles
    areole = 1 - smooth((f2 - f1) * size_m / 0.0016, 0.0, 0.18)
    return np.clip(alive, 0, 1), who, age, rim, areole


# crustose lichens on granite: colour (sRGB), share
LICHENS = [((0.64, 0.68, 0.36), 0.3),   # map lichen (Rhizocarpon): yellow-green, black prothallus
           ((0.76, 0.76, 0.71), 0.4),   # grey-white crust (Lecanora)
           ((0.56, 0.61, 0.52), 0.22),  # grey-green
           ((0.74, 0.49, 0.22), 0.08)]  # orange (Xanthoria), where birds perch


@tile_set(0.4)
def granite_lichen(n, rng):
    """The same weathered granite as `granite_weathered`, grown over by
    crustose lichen colonies (see `lichen_colonies`): rosettes that stop
    where they meet, dead centres, black margins, areole cracks. Use it on
    the parts of a boulder lichen likes (tops, the sheltered side) over
    granite_weathered, same triplanar tile_size 0.4, so the rock lines up."""
    h, mineral, edge, var = granite(n)
    base, rough = granite_maps(n, h, mineral, edge, var)
    cover, who, age, rim, areole = lichen_colonies(n)
    shares = np.array([s for _, s in LICHENS])
    kind = np.random.default_rng(5).choice(len(LICHENS), size=who.max() + 1, p=shares / shares.sum())[who]
    lc = np.array([srgb(*c) for c, _ in LICHENS])[kind]
    lc = lc * (0.85 + 0.25 * smooth(age, 2, 30))[..., None] * (1 - 0.35 * areole)[..., None]
    base = mix(base, lc, cover)
    base = mix(base, srgb(0.05, 0.05, 0.05), rim * 0.9)
    thallus = cover * (0.6 + 0.4 * (1 - areole))
    h2 = np.clip(h * 0.8 + thallus * 0.25, 0, 1)                    # the crust sits on the rock
    rough = mix(rough, 0.92, cover)
    return base, rough, h2, 0.002


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("sets", nargs="*")
    a = ap.parse_args()
    for name in a.sets or SETS:
        fn, size_m = SETS[name]
        rng = np.random.default_rng(a.seed + sum(map(ord, name)))
        base, rough, h, bump = fn(a.size, rng)
        save(name, size_m, base, rough, h, bump)


if __name__ == "__main__":
    main()
