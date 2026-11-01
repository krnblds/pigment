"""Generate the tyre loops for the game (system Python: numpy). Original, no samples.

    python tools/audio/make_tyre_sounds.py   ->  game/assets/audio/tyre_squeal.wav, tyre_wet.wav

Squeal: tread blocks stick and slip against the road, ringing the tyre carcass. That is
narrow-band (resonant) noise, not pure tones: a main resonance near 1 kHz whose pitch drifts,
a weaker one an octave up, rough flutter from the stick-slip, short rising chirps, and a bed
of broadband scrub. Wet: no squeal, a swish of water and a low rumble.
Both are 4 s seamless loops (the tail is cross-faded into the head).
"""
import os
import wave

import numpy as np

RATE = 44100
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "game", "assets", "audio")
rng = np.random.default_rng(7)


def smooth_noise(n, hz, rng):
    """Random walk band-limited to ~hz (for slow drifts and flutter)."""
    k = max(2, int(RATE / hz))
    pts = rng.uniform(-1, 1, n // k + 3)
    x = np.interp(np.arange(n) / k, np.arange(len(pts)), pts)
    return x


def resonator(x, f, q):
    """Two-pole resonant band-pass with a per-sample centre frequency f (Hz)."""
    y = np.zeros_like(x)
    y1 = y2 = 0.0
    for i in range(len(x)):
        w = 2 * np.pi * f[i] / RATE
        r = 1 - w / (2 * q)
        a1 = -2 * r * np.cos(w)
        a2 = r * r
        g = (1 - r * r) * 0.5
        v = g * x[i] - a1 * y1 - a2 * y2
        y2, y1 = y1, v
        y[i] = v
    return y


def onepole(x, hz, high=False):
    a = np.exp(-2 * np.pi * hz / RATE)
    y = np.zeros_like(x)
    s = 0.0
    for i in range(len(x)):
        s = (1 - a) * x[i] + a * s
        y[i] = s
    return x - y if high else y


def loopable(x, fade_s=0.5):
    n = int(fade_s * RATE)
    head, body, tail = x[:n], x[n:-n], x[-n:]
    t = np.linspace(0, 1, n)
    mixed = tail * np.cos(t * np.pi / 2) + head * np.sin(t * np.pi / 2)
    return np.concatenate([mixed, body, ])


def normalise(x, peak_db=-3.0):
    return x / np.max(np.abs(x)) * 10 ** (peak_db / 20)


def save(name, x):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype("<i2").tobytes())
    print(p, f"{len(x) / RATE:.2f} s")


def squeal(seconds=4.5):
    n = int(seconds * RATE)
    noise = rng.standard_normal(n)
    drift = 1 + 0.05 * smooth_noise(n, 0.8, rng) + 0.02 * smooth_noise(n, 4.0, rng)
    f1 = 980.0 * drift
    main = resonator(noise, f1, 45.0)
    upper = resonator(noise, f1 * 2.02, 60.0) * 0.35
    low = resonator(noise, f1 * 0.62, 25.0) * 0.25
    # stick-slip flutter: fast rough amplitude modulation (25-60 Hz) on a slower swell
    flutter = 0.65 + 0.35 * np.abs(smooth_noise(n, 45.0, rng))
    swell = 0.75 + 0.25 * smooth_noise(n, 1.5, rng)
    tone = (main + upper + low) * flutter * swell
    # short rising chirps (a tread block letting go)
    chirps = np.zeros(n)
    for _ in range(int(seconds * 3)):
        start = rng.integers(0, n - 4000)
        ln = rng.integers(1200, 3500)
        t = np.arange(ln) / RATE
        fr = rng.uniform(1050, 1350) * (1 + 0.25 * t / t[-1])
        env = np.sin(np.pi * np.arange(ln) / ln) ** 2
        chirps[start:start + ln] += np.sin(2 * np.pi * np.cumsum(fr) / RATE) * env * rng.uniform(0.2, 0.45)
    tone = tone / np.max(np.abs(tone))
    # broadband scrub under it (rubber dragging over aggregate)
    scrub = onepole(onepole(rng.standard_normal(n), 3500), 300, high=True)
    scrub = scrub / np.max(np.abs(scrub)) * (0.7 + 0.3 * flutter)
    x = tone * 0.8 + chirps * 0.35 + scrub * 0.18
    return normalise(loopable(x))


def wet(seconds=4.5):
    n = int(seconds * RATE)
    noise = rng.standard_normal(n)
    swish = onepole(onepole(noise, 6000), 1500, high=True)
    swish *= 0.6 + 0.4 * np.abs(smooth_noise(n, 9.0, rng))
    rumble = onepole(onepole(rng.standard_normal(n), 400), 60, high=True)
    rumble /= np.max(np.abs(rumble))
    swish /= np.max(np.abs(swish))
    x = swish * 0.7 + rumble * 0.45
    return normalise(loopable(x), -4.0)


if __name__ == "__main__":
    save("tyre_squeal.wav", squeal())
    save("tyre_wet.wav", wet())
