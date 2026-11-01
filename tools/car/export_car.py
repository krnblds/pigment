"""Export the textured Tsubame-4 (headless Blender 5.2): a wrapper over tools/vehicles/export.py.

    blender -b --factory-startup --python tools/car/export_car.py
  = blender -b --factory-startup --python tools/vehicles/export.py -- tsubame

Writes assets/vehicles/tsubame/tsubame.glb, _lod1.glb, _lod2.glb, tsubame.json (all variants)
and the legacy assets/car/car.glb, car_lod1.glb, car.json (security livery, as before).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "vehicles"))
sys.argv = [sys.argv[0], "--", "tsubame"]

import export  # noqa: E402

export.main()
