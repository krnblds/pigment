"""World heightfield: islands, mountains, erosion, urban flattening (numpy only).

Coordinates: metres, x east, y north, z up, world centred on the origin.
The field is a regular grid: H[iy, ix] is the height at
(x0 + ix * cell, y0 + iy * cell).
"""
import math

import numpy as np


# ---------------------------------------------------------------- noise


class Perlin:
    """Seeded 2D gradient noise, vectorised over arrays, range about [-1, 1]."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.perm = np.concatenate([rng.permutation(256)] * 2).astype(np.int64)
        a = rng.random(256) * 2 * math.pi
        self.g = np.stack([np.cos(a), np.sin(a)], axis=1)

    def __call__(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        xi = np.floor(x).astype(np.int64)
        yi = np.floor(y).astype(np.int64)
        xf, yf = x - xi, y - yi
        xi &= 255
        yi &= 255
        p = self.perm

        def grad(ix, iy, dx, dy):
            g = self.g[p[p[ix] + iy] & 255]
            return g[..., 0] * dx + g[..., 1] * dy
        n00 = grad(xi, yi, xf, yf)
        n10 = grad(xi + 1, yi, xf - 1, yf)
        n01 = grad(xi, yi + 1, xf, yf - 1)
        n11 = grad(xi + 1, yi + 1, xf - 1, yf - 1)
        u = xf * xf * xf * (xf * (xf * 6 - 15) + 10)
        v = yf * yf * yf * (yf * (yf * 6 - 15) + 10)
        return 1.41 * ((n00 * (1 - u) + n10 * u) * (1 - v) + (n01 * (1 - u) + n11 * u) * v)


def fbm(noise, x, y, octaves=5, lac=2.0, gain=0.5):
    out = np.zeros_like(np.asarray(x, dtype=np.float64))
    amp, f, tot = 1.0, 1.0, 0.0
    for k in range(octaves):
        out += amp * noise(x * f + 17.3 * k, y * f - 9.1 * k)
        tot += amp
        amp *= gain
        f *= lac
    return out / tot


def ridged(noise, x, y, octaves=6, lac=2.0, gain=0.5):
    """Ridged multifractal: sharp crests, detail weighted by the octave above."""
    out = np.zeros_like(np.asarray(x, dtype=np.float64))
    amp, f, w, tot = 1.0, 1.0, 1.0, 0.0
    for k in range(octaves):
        n = 1.0 - np.abs(noise(x * f + 5.7 * k, y * f + 3.3 * k))
        n = n * n * w
        w = np.clip(n * 2.0, 0.0, 1.0)
        out += amp * n
        tot += amp
        amp *= gain
        f *= lac
    return out / tot


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def blur(a, sigma_cells):
    """Separable gaussian blur (edge clamped)."""
    if sigma_cells <= 0:
        return a
    r = int(math.ceil(sigma_cells * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_cells) ** 2)
    k /= k.sum()
    out = a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        for i, w in enumerate(k):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(i, i + out.shape[axis])
            acc += w * p[tuple(sl)]
        out = acc
    return out


def upsample2(a):
    """Bilinear x2 upsample: (n, n) -> (2n - 1, 2n - 1), corners kept."""
    n0, n1 = a.shape
    out = np.empty((2 * n0 - 1, 2 * n1 - 1), dtype=a.dtype)
    out[::2, ::2] = a
    out[1::2, ::2] = (a[:-1] + a[1:]) / 2
    out[::2, 1::2] = (a[:, :-1] + a[:, 1:]) / 2
    out[1::2, 1::2] = (a[:-1, :-1] + a[1:, :-1] + a[:-1, 1:] + a[1:, 1:]) / 4
    return out


# ---------------------------------------------------------------- erosion


def thermal_erosion(h, cell, talus_deg=34.0, iters=40, rate=0.5, mask=None):
    """Material above the talus angle slides to the lower 4-neighbours."""
    talus = math.tan(math.radians(talus_deg)) * cell
    for _ in range(iters):
        p = np.pad(h, 1, mode="edge")
        nb = [p[1:-1, 2:], p[1:-1, :-2], p[2:, 1:-1], p[:-2, 1:-1]]
        d = [h - q for q in nb]
        ex = [np.maximum(di - talus, 0.0) for di in d]
        tot = sum(ex) + 1e-9
        mx = np.maximum.reduce(ex)
        move = rate * mx * 0.5
        if mask is not None:
            move *= mask
        dh = -move
        shifts = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        for e, (sy, sx) in zip(ex, shifts):
            share = move * e / tot
            dh += np.roll(np.roll(share, sy, axis=0), sx, axis=1)
        h = h + dh
    return h


def flow_accumulation(h, iters=None):
    """D8 drainage area (in cells) by iterated routing: each cell passes
    1 + its inflow to its steepest lower neighbour."""
    n0, n1 = h.shape
    p = np.pad(h, 1, mode="edge")
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    best = np.zeros_like(h)
    rec = np.full(h.shape, -1, dtype=np.int64)
    iy, ix = np.mgrid[0:n0, 0:n1]
    for k, (dy, dx) in enumerate(offs):
        q = p[1 + dy:1 + dy + n0, 1 + dx:1 + dx + n1]
        s = (h - q) / math.hypot(dy, dx)
        better = s > best
        best = np.where(better, s, best)
        ty = np.clip(iy + dy, 0, n0 - 1)
        tx = np.clip(ix + dx, 0, n1 - 1)
        rec = np.where(better, ty * n1 + tx, rec)
    flat_rec = rec.ravel()
    has = flat_rec >= 0
    src = np.nonzero(has)[0]
    dst = flat_rec[has]
    a = np.ones(n0 * n1)
    for _ in range(iters or max(n0, n1)):
        nxt = np.ones(n0 * n1)
        np.add.at(nxt, dst, a[src])
        if np.allclose(nxt, a):
            break
        a = nxt
    return a.reshape(h.shape), best


def stream_erosion(h, cell, k=0.0025, iters=6, mask=None, sea=0.0):
    """Stream-power incision: dz = k * A^0.5 * S, carving valleys and gullies
    where drainage collects (cheap stand-in for hydraulic erosion)."""
    for _ in range(iters):
        a, s = flow_accumulation(h, iters=220)
        cut = k * np.sqrt(a * cell * cell) * np.minimum(s, 1.2) * cell * 0.5
        cut = np.minimum(cut, 6.0)
        if mask is not None:
            cut *= mask
        cut *= h > sea + 2.0
        h = h - cut
        h = blur(h, 0.6) * 0.35 + h * 0.65
    return h


# ---------------------------------------------------------------- islands


def island_shape(cfg, X, Y, noise):
    """Normalised island distance (<1 inside the coast) for one island."""
    cx, cy = cfg["center"]
    rot = math.radians(cfg.get("rotation", 0.0))
    dx, dy = X - cx, Y - cy
    u = (dx * math.cos(rot) + dy * math.sin(rot)) / cfg["radius"][0]
    v = (-dx * math.sin(rot) + dy * math.cos(rot)) / cfg["radius"][1]
    p = cfg.get("power", 2.0)
    d = (np.abs(u) ** p + np.abs(v) ** p) ** (1.0 / p)
    amp = cfg.get("coast_noise", 0.08)
    if amp:
        d = d + amp * fbm(noise, X / 420.0 + cx * 0.001, Y / 420.0, 4) + amp * 0.4 * fbm(noise, X / 90.0, Y / 90.0, 3)
    return d


def polyline_dist(X, Y, pts):
    """Distance from grid points to a polyline."""
    best = np.full(X.shape, 1e9)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        ex, ey = bx - ax, by - ay
        L2 = ex * ex + ey * ey
        t = np.clip(((X - ax) * ex + (Y - ay) * ey) / max(L2, 1e-9), 0, 1)
        d = np.hypot(X - ax - t * ex, Y - ay - t * ey)
        best = np.minimum(best, d)
    return best


class Heightfield:
    def __init__(self, size, cell):
        self.size = size
        self.cell = cell
        self.n = int(round(size / cell)) + 1
        self.x0 = -size / 2
        self.H = None

    def coords(self, cell=None):
        c = cell or self.cell
        n = int(round(self.size / c)) + 1
        xs = self.x0 + np.arange(n) * c
        return np.meshgrid(xs, xs)

    def sample(self, x, y):
        """Bilinear height at arrays of points (matches the mesh triangles
        only at vertices; use sample_tri for the exact surface)."""
        fx = (np.asarray(x) - self.x0) / self.cell
        fy = (np.asarray(y) - self.x0) / self.cell
        ix = np.clip(np.floor(fx).astype(int), 0, self.n - 2)
        iy = np.clip(np.floor(fy).astype(int), 0, self.n - 2)
        tx, ty = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
        H = self.H
        return (H[iy, ix] * (1 - tx) * (1 - ty) + H[iy, ix + 1] * tx * (1 - ty)
                + H[iy + 1, ix] * (1 - tx) * ty + H[iy + 1, ix + 1] * tx * ty)

    def sample_tri(self, x, y):
        """Height of the triangulated surface (each quad split along the
        (ix, iy)-(ix+1, iy+1) diagonal, as the terrain meshes are built)."""
        fx = (np.asarray(x) - self.x0) / self.cell
        fy = (np.asarray(y) - self.x0) / self.cell
        ix = np.clip(np.floor(fx).astype(int), 0, self.n - 2)
        iy = np.clip(np.floor(fy).astype(int), 0, self.n - 2)
        tx, ty = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
        H = self.H
        h00, h10, h01, h11 = H[iy, ix], H[iy, ix + 1], H[iy + 1, ix], H[iy + 1, ix + 1]
        lower = tx >= ty         # triangle (00, 10, 11)
        z_lo = h00 + (h10 - h00) * tx + (h11 - h10) * ty
        z_up = h00 + (h11 - h01) * tx + (h01 - h00) * ty
        return np.where(lower, z_lo, z_up)


def generate(cfg, log=print):
    """Natural terrain (before roads): returns (Heightfield, masks dict)."""
    seed = cfg["seed"]
    T = cfg["terrain"]
    size = cfg["size_m"]
    coarse = T.get("erosion_cell_m", 8.0)
    noise = Perlin(seed)
    noise2 = Perlin(seed + 101)
    hf_c = Heightfield(size, coarse)
    X, Y = hf_c.coords()
    sea_floor = T.get("sea_floor", -28.0) + 6.0 * fbm(noise2, X / 700.0, Y / 700.0, 3)
    H = sea_floor.copy()
    land_any = np.zeros_like(X)
    urban = np.zeros_like(X)
    mountain = np.zeros_like(X)
    for isl in cfg["islands"]:
        d = island_shape(isl, X, Y, noise)
        top = isl.get("height", 4.0)
        kind = isl.get("kind", "urban")
        # shoreline profile: shelf -> beach / quay -> plateau
        if isl.get("quay", False):
            shore = smoothstep(1.012, 0.995, d)            # near vertical (sea walls)
        else:
            shore = smoothstep(1.06, 0.9, d)                 # beaches and rocky shores
        h = sea_floor * (1 - shore) + top * shore
        h += (1 - smoothstep(1.25, 1.0, d)) * 0.0
        # rolling land
        roll = isl.get("roll", 2.0)
        h += roll * fbm(noise, X / 300.0 + 3.1, Y / 300.0, 4) * shore
        if kind == "hills":
            hills = isl.get("hills", 60.0)
            core = smoothstep(0.95, 0.35, d)
            h += hills * core * (0.55 + 0.45 * fbm(noise2, X / 380.0, Y / 380.0, 5)) + hills * 0.25 * core * ridged(noise, X / 260.0, Y / 260.0, 4)
        # mountains on the outskirts of this island
        for m in isl.get("mountains", []):
            dist = polyline_dist(X, Y, m["ridge"])
            w = m.get("width", 520.0)
            mm = smoothstep(w, w * 0.15, dist) * smoothstep(1.03, 0.62, d)
            warp_x = X + 90 * fbm(noise2, X / 500.0, Y / 500.0, 3)
            warp_y = Y + 90 * fbm(noise2, X / 500.0 + 7.7, Y / 500.0, 3)
            r = ridged(noise, warp_x / m.get("scale", 520.0), warp_y / m.get("scale", 520.0), 6)
            prof = smoothstep(w, 0.0, dist)
            h += m["height"] * mm * (0.55 * prof ** 1.4 + 0.55 * r * prof ** 0.8)
            mountain = np.maximum(mountain, mm)
        land = (d < 1.0).astype(float)
        H = np.maximum(H, h)
        land_any = np.maximum(land_any, land)
        if kind in ("urban", "port", "corporate"):
            urban = np.maximum(urban, smoothstep(0.98, 0.85, d))
    log(f"terrain: base field {H.shape} at {coarse} m")
    # erosion on the mountains and hills
    er = T.get("erosion", {})
    hill_mask = np.clip(smoothstep(6.0, 40.0, H), 0, 1)
    if er.get("thermal_iters", 0):
        H = thermal_erosion(H, coarse, er.get("talus_deg", 36.0), er["thermal_iters"], mask=hill_mask)
    if er.get("stream_iters", 0):
        H = stream_erosion(H, coarse, er.get("stream_k", 0.0025), er["stream_iters"], mask=hill_mask)
    if er.get("thermal_iters", 0):
        H = thermal_erosion(H, coarse, er.get("talus_deg", 36.0), max(4, er["thermal_iters"] // 4), mask=hill_mask)
    # refine to the mesh cell
    hf = Heightfield(size, T.get("cell_m", 2.0))
    while H.shape[0] < hf.n:
        H = upsample2(H)
        urban = upsample2(urban)
        mountain = upsample2(mountain)
    assert H.shape[0] == hf.n, (H.shape, hf.n)
    Xf, Yf = hf.coords()
    detail = T.get("detail_m", 0.6)
    natural = np.clip(smoothstep(1.0, 8.0, H), 0, 1) * (1 - urban)
    H = H + detail * fbm(noise2, Xf / 14.0, Yf / 14.0, 3) * natural + detail * 3 * mountain * fbm(noise, Xf / 45.0, Yf / 45.0, 4)
    hf.H = H
    return hf, {"urban": urban, "mountain": mountain}


def flatten(hf, region_mask, level_fn, strength=1.0):
    """Blend the field towards level_fn(X, Y) where region_mask (0..1)."""
    X, Y = hf.coords()
    tgt = level_fn(X, Y)
    land = hf.H > 0.3
    m = region_mask * strength * land
    hf.H = hf.H * (1 - m) + tgt * m
