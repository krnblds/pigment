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
    t = np.asarray(t)[..., None] if np.ndim(a) == 3 else t
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
