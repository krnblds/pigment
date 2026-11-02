"""Read EXR files for the demos: pigment-core's `exr_dump` test (the exr
crate) writes <file>.raw (u32 width, height, channels, then f32 samples;
channels in alphabetical order: B, G, R or Y)."""
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def _load(path):
    path = Path(path)
    raw = Path(str(path) + ".raw")
    if not raw.exists() or raw.stat().st_mtime < path.stat().st_mtime:
        env = dict(os.environ, PIGMENT_EXR_DUMP=str(path))
        subprocess.run(["cargo", "test", "-p", "pigment-core", "--release", "-j", "6", "exr_dump", "--", "--ignored"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    b = raw.read_bytes()
    w, h, c = np.frombuffer(b[:12], np.uint32)
    return np.frombuffer(b[12:], np.float32).reshape(h, w, c)


def rgb(path):
    a = _load(path)  # B, G, R (sorted names)
    return a[..., [2, 1, 0]] if a.shape[2] >= 3 else np.repeat(a, 3, axis=2)


def y(path):
    return _load(path)[..., 0]
