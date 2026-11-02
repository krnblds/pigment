"""Synthesise the damage / destruction sounds for the game (system Python: numpy + scipy). Original,
no samples: noise, modal resonators and envelopes only.

    python tools/audio/make_damage_sounds.py   ->  game/assets/audio/damage/*.wav

Files (the names game/scripts/damage/damage_audio.gd looks for; `_<n>` are variations picked at
random; a purchased pack drops same-named files into game/assets/audio/damage_pack/ to replace them):

    metal_crunch_light_1..3   body panel dent: a slap, buckling clicks, inharmonic panel ring
    metal_crunch_heavy_1..3   big crash: low thump, several buckles, crunching noise, ring, tinkle tail
    metal_scrape              loop: metal dragged on asphalt / a wall (stick-slip grind, squeal)
    glass_shatter_1..2        break transient and a rain of high glass pings
    plastic_clatter_1..3      hollow plastic knocks and a couple of bounces (cones, bins, lenses)
    wood_knock_1..2           crates and pallets
    cardboard_thud            boxes
    bag_thump                 rubbish bags (thud + rustle)
    water_burst               a hydrant snapping open
    water_hiss                loop: the geyser's roar and spray
    pole_clang_1..2           a lamp post / pole hit: low bell-like modes, long decay
    electric_fizz_1..2        a lamp's wiring shorting: arcs, crackle, mains buzz
    can_rattle                drink cans spilling from a vending machine
"""
import os
import wave

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

RATE = 44100
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "game", "assets", "audio", "damage")
rng = np.random.default_rng(1977)


def t_axis(sec):
    return np.arange(int(sec * RATE)) / RATE


def bp(x, lo, hi, order=2):
    sos = butter(order, [lo, min(hi, RATE * 0.49)], btype="band", fs=RATE, output="sos")
    return sosfilt(sos, x)


def lp(x, hz, order=2):
    return sosfilt(butter(order, hz, btype="low", fs=RATE, output="sos"), x)


def hp(x, hz, order=2):
    return sosfilt(butter(order, hz, btype="high", fs=RATE, output="sos"), x)


def mode(sec, f, decay, amp=1.0, phase=None, start=0.0):
    """A decaying sinusoid (one resonant mode), starting at `start` s."""
    t = t_axis(sec)
    y = np.zeros_like(t)
    m = t >= start
    tt = t[m] - start
    ph = rng.uniform(0, 2 * np.pi) if phase is None else phase
    y[m] = amp * np.exp(-tt / decay) * np.sin(2 * np.pi * f * tt + ph)
    return y


def resonate(x, f, q):
    """Excite a two-pole resonator at f (Hz) with x (constant centre, vectorised via lfilter)."""
    w = 2 * np.pi * f / RATE
    r = np.exp(-w / (2 * q))
    a = [1.0, -2 * r * np.cos(w), r * r]
    return lfilter([1 - r], a, x)


def env(sec, attack, decay, shape=1.0):
    t = t_axis(sec)
    e = np.minimum(t / max(attack, 1e-4), 1.0) * np.exp(-np.maximum(t - attack, 0) / decay)
    return e ** shape


def clicks(sec, n, start, spread, width=0.0008, amp=1.0):
    """Sparse impulses (buckling / tinkle onsets)."""
    y = np.zeros(int(sec * RATE))
    for _ in range(n):
        t0 = start + abs(rng.normal(0, spread))
        i = int(t0 * RATE)
        if i >= len(y) - 10:
            continue
        w = max(2, int(width * RATE))
        y[i:i + w] += amp * rng.uniform(0.3, 1.0) * rng.choice([-1, 1]) * np.hanning(w)[: len(y[i:i + w])]
    return y


def normalise(x, peak_db=-1.5):
    x = x - np.mean(x)
    return x / (np.max(np.abs(x)) + 1e-9) * 10 ** (peak_db / 20)


def fade(x, out_s=0.05, in_s=0.002):
    n_in, n_out = int(in_s * RATE), int(out_s * RATE)
    x = x.copy()
    x[:n_in] *= np.linspace(0, 1, n_in)
    x[-n_out:] *= np.linspace(1, 0, n_out)
    return x


def loopable(x, fade_s=0.4):
    n = int(fade_s * RATE)
    head, body, tail = x[:n], x[n:-n], x[-n:]
    t = np.linspace(0, 1, n)
    return np.concatenate([tail * np.cos(t * np.pi / 2) + head * np.sin(t * np.pi / 2), body])


def save(name, x, loop=False):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".wav")
    x = normalise(x if loop else fade(x))
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype("<i2").tobytes())
    print(f"{os.path.relpath(p)}  {len(x) / RATE:.2f} s")


# ------------------------------------------------------------------ sounds
def panel_ring(sec, base, n, decay, start=0.0, amp=1.0):
    """Inharmonic plate modes (thin steel panel): partials spread like a plate's (~ k^1.6)."""
    y = np.zeros(int(sec * RATE))
    for k in range(1, n + 1):
        f = base * k ** 1.55 * rng.uniform(0.95, 1.06)
        y += mode(sec, f, decay * rng.uniform(0.5, 1.1) / k ** 0.35, amp * rng.uniform(0.4, 1.0) / k ** 0.6, start=start)
    return y


def metal_crunch_light(seed):
    sec = 0.7
    x = np.zeros(int(sec * RATE))
    noise = rng.standard_normal(len(x))
    slap = hp(noise, 300) * env(sec, 0.001, 0.025)
    x += 0.9 * slap
    buckle = clicks(sec, 6 + seed, 0.01, 0.05, amp=0.7)
    x += resonate(buckle, rng.uniform(900, 1600), 9) * 0.5 + resonate(buckle, rng.uniform(2500, 3800), 12) * 0.25
    x += panel_ring(sec, rng.uniform(170, 260), 9, 0.16, start=0.002, amp=0.45)
    x += 0.35 * bp(noise, 400, 3000) * env(sec, 0.004, 0.09)
    x += 0.5 * mode(sec, rng.uniform(70, 95), 0.08)
    return x


def metal_crunch_heavy(seed):
    sec = 1.6
    n = int(sec * RATE)
    noise = rng.standard_normal(n)
    x = 1.2 * mode(sec, rng.uniform(42, 60), 0.18) + 0.7 * mode(sec, rng.uniform(85, 110), 0.12)
    x += 1.0 * hp(noise, 150) * env(sec, 0.001, 0.05)
    # several buckles over the first 0.3 s, each a crunch of grinding noise
    for _ in range(4 + seed):
        t0 = abs(rng.normal(0.08, 0.1))
        e = np.zeros(n)
        i = int(t0 * RATE)
        d = int(rng.uniform(0.03, 0.09) * RATE)
        if i + d < n:
            e[i:i + d] = np.hanning(d) * rng.uniform(0.4, 1.0)
        x += bp(noise * e, rng.uniform(300, 700), rng.uniform(2500, 5000)) * 1.4
    crk = clicks(sec, 30, 0.02, 0.12, amp=0.6)
    x += resonate(crk, rng.uniform(1200, 2000), 10) * 0.4
    x += panel_ring(sec, rng.uniform(120, 180), 12, 0.45, start=0.01, amp=0.5)
    # tinkle tail: bits of trim and glass
    tink = clicks(sec, 22, 0.25, 0.35, width=0.0004, amp=0.25)
    for f in (3100, 4300, 5600, 7200):
        x += resonate(tink, f * rng.uniform(0.9, 1.1), 40) * 0.12
    return x


def metal_scrape():
    sec = 3.6
    n = int(sec * RATE)
    t = t_axis(sec)
    noise = rng.standard_normal(n)
    # stick-slip: grains of grinding at 25-60 Hz with a wandering rate
    rate = 38 + 12 * np.sin(2 * np.pi * 0.7 * t) + 6 * np.sin(2 * np.pi * 2.3 * t)
    ph = np.cumsum(rate) / RATE
    grains = (0.5 + 0.5 * np.sin(2 * np.pi * ph)) ** 6
    x = bp(noise, 600, 6000) * (0.35 + 0.9 * grains)
    x += 0.5 * lp(noise, 300) * (0.6 + 0.4 * grains)
    # squeal: two drifting resonances
    f1 = 1450 + 150 * np.sin(2 * np.pi * 0.4 * t)
    for f, q, a in ((1450, 30, 0.6), (2900, 40, 0.3)):
        x += resonate(noise * grains, f, q) * a
    x += 0.25 * np.sin(2 * np.pi * np.cumsum(f1) / RATE) * grains * 0.3
    return loopable(x)


def glass_shatter(seed):
    sec = 1.8
    n = int(sec * RATE)
    noise = rng.standard_normal(n)
    x = 1.3 * hp(noise, 1500) * env(sec, 0.0005, 0.03)
    x += 0.5 * bp(noise, 3000, 12000) * env(sec, 0.001, 0.18)
    # pings: many tiny shards ringing, density falling over time
    for _ in range(140 + 40 * seed):
        t0 = abs(rng.exponential(0.22)) + 0.003
        if t0 > sec - 0.1:
            continue
        f = rng.uniform(2400, 10500)
        x += mode(sec, f, rng.uniform(0.01, 0.05), rng.uniform(0.05, 0.25) * np.exp(-t0 * 1.5), start=t0)
    x += 0.3 * mode(sec, rng.uniform(800, 1100), 0.05)
    return x


def plastic_clatter(seed):
    sec = 0.8
    x = np.zeros(int(sec * RATE))
    noise = rng.standard_normal(len(x))
    hits = [0.0] + sorted(rng.uniform(0.12, 0.6, 2 + seed % 2))
    for i, t0 in enumerate(hits):
        a = 1.0 / (1 + i * 1.3)
        e = np.zeros(len(x))
        j = int(t0 * RATE)
        d = int(0.004 * RATE)
        e[j:j + d] = np.hanning(d) * a
        for f, q in ((rng.uniform(320, 480), 7), (rng.uniform(800, 1200), 9), (rng.uniform(1900, 2600), 11)):
            x += resonate(e * rng.standard_normal(len(e)), f, q) * 1.5
        x += hp(noise, 2000) * e * 0.5
    return x


def wood_knock(seed):
    sec = 0.6
    x = np.zeros(int(sec * RATE))
    noise = rng.standard_normal(len(x))
    hits = [0.0] + sorted(rng.uniform(0.08, 0.35, 1 + seed))
    for i, t0 in enumerate(hits):
        a = 1.0 / (1 + i * 1.5)
        x += mode(sec, rng.uniform(140, 210), 0.05, a, start=t0) + mode(sec, rng.uniform(420, 600), 0.03, 0.6 * a, start=t0)
        e = np.zeros(len(x))
        j = int(t0 * RATE)
        e[j:j + 120] = a
        x += bp(noise * e, 600, 3500) * 2.0
    return x


def cardboard_thud():
    sec = 0.5
    noise = rng.standard_normal(int(sec * RATE))
    x = lp(noise, 900) * env(sec, 0.002, 0.05) * 1.5 + mode(sec, 95, 0.06, 0.8)
    x += bp(noise, 1500, 5000) * env(sec, 0.01, 0.08) * 0.25
    return x


def bag_thump():
    sec = 0.6
    t = t_axis(sec)
    noise = rng.standard_normal(len(t))
    x = mode(sec, 70, 0.07, 1.0) + lp(noise, 500) * env(sec, 0.003, 0.06) * 0.9
    rustle = bp(noise, 2500, 9000) * env(sec, 0.02, 0.2) * (0.5 + 0.5 * (rng.random(len(t)) > 0.97))
    return x + rustle * 0.6


def water_burst():
    sec = 1.8
    n = int(sec * RATE)
    noise = rng.standard_normal(n)
    x = 1.2 * lp(noise, 1200) * env(sec, 0.003, 0.12)
    x += 0.6 * mode(sec, 55, 0.15)
    x += 0.8 * bp(noise, 800, 9000) * env(sec, 0.08, 1.2, 0.7)
    # gurgle: bubbles
    for _ in range(30):
        t0 = rng.uniform(0.02, 0.6)
        f = rng.uniform(300, 900)
        x += mode(sec, f, 0.015, 0.15, start=t0)
    return x


def water_hiss():
    sec = 4.0
    t = t_axis(sec)
    n = len(t)
    noise = rng.standard_normal(n)
    am = 1.0 + 0.18 * np.sin(2 * np.pi * 0.9 * t) + 0.1 * np.sin(2 * np.pi * 3.1 * t + 1.0)
    x = bp(noise, 900, 10000) * am * 0.9
    x += lp(noise, 400) * 0.6 * am
    # splatter: falling water on the road (dense random droplets)
    drops = clicks(sec, 900, 0.0, sec, width=0.0006, amp=0.4)
    x += resonate(drops, 1800, 5) * 0.4 + hp(drops, 3000) * 0.2
    return loopable(x)


def pole_clang(seed):
    sec = 3.0
    noise = rng.standard_normal(int(sec * RATE))
    x = 1.1 * hp(noise, 200) * env(sec, 0.0008, 0.02)
    x += 1.0 * mode(sec, rng.uniform(55, 70), 0.25)
    # a hollow steel pole: a few strong inharmonic bending modes, long decay
    base = rng.uniform(150, 210)
    for k, (r, dec, a) in enumerate([(1.0, 1.4, 1.0), (2.76, 1.0, 0.7), (5.4, 0.7, 0.5), (8.93, 0.45, 0.35), (13.3, 0.3, 0.25)]):
        f = base * r * rng.uniform(0.98, 1.02)
        x += mode(sec, f, dec, a)
        x += mode(sec, f * 1.006, dec, a * 0.6)        # beating partner
    return x


def electric_fizz(seed):
    sec = 1.6
    t = t_axis(sec)
    n = len(t)
    noise = rng.standard_normal(n)
    # mains buzz (50/60 Hz harmonics), gated by arcing
    f0 = 50.0 if seed == 1 else 60.0
    buzz = sum(np.sign(np.sin(2 * np.pi * f0 * k * t)) / k for k in (1, 2, 3, 5))
    gate = (lp(rng.standard_normal(n), 30) > 0.0).astype(float)
    x = 0.35 * buzz * gate * env(sec, 0.01, 0.6)
    cr = clicks(sec, 160, 0.0, 0.35, width=0.0003, amp=1.0)
    x += hp(cr, 1500) * 0.9 + resonate(cr, 3500, 6) * 0.3
    x += 0.4 * bp(noise, 3000, 12000) * gate * env(sec, 0.005, 0.3)
    pop = hp(noise, 100) * env(sec, 0.0005, 0.02)
    return x + pop * 1.2


def can_rattle():
    sec = 1.2
    x = np.zeros(int(sec * RATE))
    for _ in range(26):
        t0 = abs(rng.normal(0.25, 0.25))
        f = rng.uniform(1800, 4200)
        x += mode(sec, f, rng.uniform(0.02, 0.06), rng.uniform(0.2, 0.6), start=t0)
        x += mode(sec, f * 2.3, 0.02, 0.2, start=t0)
    return x


def main():
    for i in (1, 2, 3):
        save(f"metal_crunch_light_{i}", metal_crunch_light(i))
        save(f"metal_crunch_heavy_{i}", metal_crunch_heavy(i))
        save(f"plastic_clatter_{i}", plastic_clatter(i))
    save("metal_scrape", metal_scrape(), loop=True)
    for i in (1, 2):
        save(f"glass_shatter_{i}", glass_shatter(i))
        save(f"wood_knock_{i}", wood_knock(i))
        save(f"pole_clang_{i}", pole_clang(i))
        save(f"electric_fizz_{i}", electric_fizz(i))
    save("cardboard_thud", cardboard_thud())
    save("bag_thump", bag_thump())
    save("water_burst", water_burst())
    save("water_hiss", water_hiss(), loop=True)
    save("can_rattle", can_rattle())


if __name__ == "__main__":
    main()
