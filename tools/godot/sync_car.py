"""Put the hero car into the Godot project (system Python).

    python tools/godot/sync_car.py

If the car workstream's assets/car/car.glb + car.json exist they are copied to game/assets/car/
(replacing the placeholder).  Otherwise nothing changes: game/assets/car/ keeps the placeholder
made by tools/godot/make_placeholder_car.py to the same contract.  Re-import afterwards:
    godot --headless --path game --import
"""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "assets", "car")
DST = os.path.join(ROOT, "game", "assets", "car")

if os.path.isfile(os.path.join(SRC, "car.glb")) and os.path.isfile(os.path.join(SRC, "car.json")):
    os.makedirs(DST, exist_ok=True)
    for fn in ("car.glb", "car.json"):
        shutil.copyfile(os.path.join(SRC, fn), os.path.join(DST, fn))
    # textures referenced by a .gltf (not needed for .glb) would be copied here too
    print("copied the real car from", SRC)
else:
    print("no assets/car/car.glb yet: keeping the placeholder in", DST)
