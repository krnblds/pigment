"""Texture the Kanzaki Tsubame-4 in Pigment: a wrapper over tools/vehicles/textures.py.

    python tools/car/car_textures.py [body] [wheel] [--no-run]
  = python tools/vehicles/textures.py tsubame [body] [wheel] [--no-run]

The hero's authored recipe lives in tools/vehicles/textures.py (hero_body_script); the
security and cab variants are unchanged, the fleet adds civilian / taxi / beater variants.
Outputs scenes/vehicles/tsubame/{scripts,projects,textures}/.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "vehicles"))

import textures  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
textures.texture("tsubame", args or ["body", "wheel"], "--no-run" in sys.argv)
