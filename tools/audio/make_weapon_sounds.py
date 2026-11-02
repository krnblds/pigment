"""Synthesise the Waker kit / weapon / case sounds (system Python: numpy + scipy). Original, no samples:
noise, resonators, chirps and envelopes only.

    python tools/audio/make_weapon_sounds.py   ->  game/assets/audio/weapons/*.wav

Names (what game/scripts/weapons/weapon_audio.gd looks for; `_<n>` are variations; a purchased pack
drops same-named files into game/assets/audio/weapons_pack/ to replace them):

    pistol_shot_1..3     sharp crack, body thump, short room tail
    smg_shot_1..3        lighter, tighter crack (plays fast)
    shotgun_shot_1..2    big low boom, long tail
    taser_zap            electric crackle burst with a 2 kHz whine
    taser_hit            short arc snap
    baton_swing          air whoosh            baton_hit   thump + crackle
    dry_fire             a small click         reload_mag / reload_shell / reload_cell   clacks
    casing_tink_1..3     brass on stone        impact_concrete_1..3 / impact_metal_1..3 / ricochet_1..2
    body_hit             dull thud             emp_throw   whoosh + clink
    emp_arm              short beep            emp_blast   descending electric thump + crackle
    siren                loop: the Hoshikawa cruiser's two-tone sweep
    scan_pulse           soft sonar-like ping  wake_sync   loop: slow shimmering pad
    wake_chime           rising bell triad     echo_hum    loop: airy detuned hum
    dispatch_beep        two short tones       audit_drone loop: rotor buzz
"""
import os
import wave

import numpy as np
from scipy.signal import butter, sosfilt

RATE = 44100
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "game", "assets", "audio", "weapons")
rng = np.random.default_rng(4242)


def t_axis(sec):
    return np.arange(int(sec * RATE)) / RATE


def filt(x, lo=None, hi=None, order=2):
    if lo and hi:
        sos = butter(order, [lo, min(hi, RATE * 0.49)], btype="band", fs=RATE, output="sos")
    elif lo:
        sos = butter(order, lo, btype="high", fs=RATE, output="sos")
    else:
        sos = butter(order, min(hi, RATE * 0.49), btype="low", fs=RATE, output="sos")
    return sosfilt(sos, x)


def env(t, attack, decay):
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / decay)


def noise(n):
    return rng.standard_normal(n)


def save(name, x, peak=0.9):
    x = np.asarray(x, dtype=np.float64)
    m = np.max(np.abs(x)) or 1.0
    x = x / m * peak
    # 5 ms fade at the ends
    f = min(len(x) // 4, int(0.005 * RATE))
    if f > 0:
        x[:f] *= np.linspace(0, 1, f)
        x[-f:] *= np.linspace(1, 0, f)
    os.makedirs(OUT, exist_ok=True)
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def loopify(x, xf=0.25):
    n = int(xf * RATE)
    head, tail = x[:n], x[-n:]
    k = np.linspace(0, 1, n)
    body = x[n:-n].copy()
    out = np.concatenate([body, tail * (1 - k) + head * k])
    return out


def tail(sec, lo, hi, decay):
    t = t_axis(sec)
    return filt(noise(len(t)), lo, hi) * np.exp(-t / decay)


def gunshot(sec, crack_hi, body_f, body_decay, tail_decay, tail_gain):
    t = t_axis(sec)
    crack = filt(noise(len(t)), 1500, crack_hi) * env(t, 0.0003, 0.006)
    body = np.sin(2 * np.pi * body_f * t * (1 - 0.4 * t)) * env(t, 0.001, body_decay)
    thump = filt(noise(len(t)), 60, 500) * env(t, 0.001, body_decay * 1.5)
    room = tail(sec, 200, 3000, tail_decay) * tail_gain
    return crack * 1.0 + body * 0.7 + thump * 0.8 + room


def chirp(t, f0, f1):
    f = f0 + (f1 - f0) * t / t[-1]
    return np.sin(2 * np.pi * np.cumsum(f) / RATE)


def main():
    for i in range(3):
        save("pistol_shot_%d" % (i + 1), gunshot(0.6, 9000 + i * 900, 140 + i * 15, 0.03, 0.12, 0.35))
        save("smg_shot_%d" % (i + 1), gunshot(0.35, 10000, 180 + i * 20, 0.02, 0.07, 0.25), 0.8)
    for i in range(2):
        save("shotgun_shot_%d" % (i + 1), gunshot(1.1, 7000, 80 + i * 10, 0.07, 0.3, 0.55))
    # taser: crackle bursts + whine
    t = t_axis(0.45)
    crackle = filt(noise(len(t)), 2000, 12000) * (rng.random(len(t)) < 0.08) * 3.0
    whine = np.sin(2 * np.pi * 2100 * t + 3 * np.sin(2 * np.pi * 60 * t)) * 0.3
    buzz = np.sign(np.sin(2 * np.pi * 120 * t)) * 0.25
    save("taser_zap", (crackle + whine + buzz) * env(t, 0.005, 0.25))
    t = t_axis(0.18)
    save("taser_hit", filt(noise(len(t)), 1500, 9000) * env(t, 0.0005, 0.04) + np.sin(2 * np.pi * 1800 * t) * env(t, 0.001, 0.05) * 0.4)
    t = t_axis(0.35)
    save("baton_swing", filt(noise(len(t)), 300, 2500) * np.sin(np.pi * t / t[-1]) ** 2, 0.6)
    t = t_axis(0.4)
    hit = filt(noise(len(t)), 80, 600) * env(t, 0.001, 0.05) + filt(noise(len(t)), 2500, 10000) * (rng.random(len(t)) < 0.1) * env(t, 0.01, 0.12) * 2
    save("baton_hit", hit)
    t = t_axis(0.08)
    save("dry_fire", filt(noise(len(t)), 2000, 8000) * env(t, 0.0003, 0.006), 0.5)

    def clack(t0, f, sec_total, parts):
        t = t_axis(sec_total)
        x = np.zeros(len(t))
        for at, ff, g in parts:
            s = int(at * RATE)
            tt = t[: len(t) - s]
            x[s:] += (filt(noise(len(tt)), ff * 0.6, ff * 2.0) * env(tt, 0.0005, 0.015) + np.sin(2 * np.pi * ff * tt) * env(tt, 0.001, 0.03) * 0.5) * g
        return x

    save("reload_mag", clack(0, 0, 1.2, [(0.05, 1800, 0.7), (0.45, 900, 0.5), (0.8, 2200, 1.0), (0.95, 1500, 0.8)]), 0.7)
    save("reload_shell", clack(0, 0, 1.6, [(0.1 + i * 0.32, 1300 + i * 40, 0.8) for i in range(4)] + [(1.45, 700, 1.0)]), 0.7)
    cell = clack(0, 0, 1.2, [(0.1, 2500, 0.6), (0.6, 1800, 0.8)])
    s0 = int(0.7 * RATE)
    tt = t_axis((len(cell) - s0) / RATE)[: len(cell) - s0]
    cell[s0:s0 + len(tt)] += np.sin(2 * np.pi * 3200 * tt) * env(tt, 0.05, 0.2) * 0.2
    save("reload_cell", cell, 0.7)
    for i in range(3):
        t = t_axis(0.25)
        modes = sum(np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, d in [(4200 + i * 300, 0.05), (6900 + i * 200, 0.03), (9800, 0.02)])
        save("casing_tink_%d" % (i + 1), modes * env(t, 0.0003, 0.2), 0.5)
        t = t_axis(0.3)
        save("impact_concrete_%d" % (i + 1), filt(noise(len(t)), 600, 7000) * env(t, 0.0003, 0.02) + filt(noise(len(t)), 100, 1200) * env(t, 0.001, 0.05) * 0.6 + tail(0.3, 1000, 6000, 0.06) * 0.2)
        modes = sum(np.sin(2 * np.pi * f * t) * np.exp(-t / d) for f, d in [(1900 + i * 230, 0.08), (3100 + i * 170, 0.06), (5200, 0.04)])
        save("impact_metal_%d" % (i + 1), filt(noise(len(t)), 1500, 9000) * env(t, 0.0003, 0.01) + modes * 0.6)
    for i in range(2):
        t = t_axis(0.5)
        save("ricochet_%d" % (i + 1), chirp(t, 3800 - i * 400, 1700) * env(t, 0.005, 0.18) * 0.6 + filt(noise(len(t)), 2000, 8000) * env(t, 0.0003, 0.01), 0.6)
    t = t_axis(0.25)
    save("body_hit", filt(noise(len(t)), 60, 400) * env(t, 0.001, 0.04) + np.sin(2 * np.pi * 90 * t) * env(t, 0.001, 0.06), 0.8)
    t = t_axis(0.4)
    save("emp_throw", filt(noise(len(t)), 400, 3000) * np.sin(np.pi * t / t[-1]) ** 2 * 0.6 + np.sin(2 * np.pi * 2600 * t) * env(t, 0.001, 0.03) * 0.4, 0.6)
    t = t_axis(0.09)
    save("emp_arm", np.sin(2 * np.pi * 2400 * t) * env(t, 0.002, 0.05), 0.5)
    t = t_axis(1.6)
    drop = chirp(t, 900, 40) * env(t, 0.002, 0.5)
    crack = filt(noise(len(t)), 2000, 12000) * (rng.random(len(t)) < 0.04) * env(t, 0.01, 0.35) * 2.5
    thump = filt(noise(len(t)), 30, 200) * env(t, 0.002, 0.25) * 1.5
    save("emp_blast", drop + crack + thump)
    # siren: two-tone sweep (Hoshikawa cruiser), 4 s loop
    t = t_axis(4.25)
    f = 650 + 300 * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 0.5 * t))) * 1.0
    f = filt(f, hi=6)  # glide between the tones
    ph = np.cumsum(f) / RATE
    sir = np.sin(2 * np.pi * ph) + 0.35 * np.sin(4 * np.pi * ph) + 0.15 * np.sin(6 * np.pi * ph)
    save("siren", loopify(sir * 0.7), 0.6)
    t = t_axis(1.2)
    ping = sum(np.sin(2 * np.pi * f0 * t) * np.exp(-t / d) for f0, d in [(1320, 0.4), (1980, 0.25), (660, 0.5)])
    save("scan_pulse", ping * env(t, 0.004, 0.6), 0.5)
    t = t_axis(4.25)
    pad = sum(np.sin(2 * np.pi * f0 * t + 0.3 * np.sin(2 * np.pi * 0.3 * t + i)) for i, f0 in enumerate([220, 277.2, 329.6, 440.5]))
    pad *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t)
    save("wake_sync", loopify(pad), 0.4)
    t = t_axis(2.0)
    chime = sum(np.sin(2 * np.pi * f0 * t) * np.exp(-np.maximum(t - at, 0) / 0.8) * (t >= at) for f0, at in [(523.3, 0.0), (659.3, 0.12), (784.0, 0.24), (1046.5, 0.36)])
    save("wake_chime", chime, 0.5)
    t = t_axis(4.25)
    hum = sum(np.sin(2 * np.pi * f0 * t) for f0 in [110, 110.7, 165.2, 219.4]) + filt(noise(len(t)), 800, 3000) * 0.15
    save("echo_hum", loopify(hum), 0.3)
    t = t_axis(0.42)
    beep = np.sin(2 * np.pi * 1760 * t) * ((t < 0.12) | ((t > 0.2) & (t < 0.32))) + np.sin(2 * np.pi * 2349 * t) * ((t > 0.2) & (t < 0.32)) * 0.5
    save("dispatch_beep", beep, 0.4)
    t = t_axis(2.25)
    rot = np.sign(np.sin(2 * np.pi * 95 * t)) * 0.3 + filt(noise(len(t)), 150, 1200) * (0.6 + 0.4 * np.sin(2 * np.pi * 24 * t))
    save("audit_drone", loopify(rot), 0.4)
    print("wrote", len(os.listdir(OUT)), "files to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
