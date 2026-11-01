"""Build the Kanzaki Tsubame-4 "Hoshikawa Security" cruiser (headless Blender 5.2).

The car is now a spec of the parametric vehicle kit: tools/vehicles/specs/tsubame.py (its data
and the security conversion's custom parts) built by tools/vehicles/vkit/. This wrapper keeps
the old command working:

    blender -b --factory-startup --python tools/car/build_car.py -- [--preview DIR] [--no-export]
  = blender -b --factory-startup --python tools/vehicles/build.py -- tsubame [--preview DIR] [--no-export]

Writes assets/vehicles/tsubame/src/tsubame_body.glb, tsubame_wheel.glb, tsubame_parts.json,
tsubame_info.json and tsubame_model.blend (same geometry as the old assets/car/src/car_*).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "vehicles"))

import build  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None
build.build("tsubame", preview, "--no-export" not in argv)
