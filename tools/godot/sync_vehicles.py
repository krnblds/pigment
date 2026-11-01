"""Copy the fleet's vehicles and the props' traffic lights into the Godot project (system Python).

    python tools/godot/sync_vehicles.py [--src <repo root>]      (default: this checkout)

  assets/vehicles/index.json + <id>/<id>*.glb, <id>.json   -> game/assets/vehicles/   (src/ is skipped)
  assets/props/*.glb, index.json                           -> game/assets/props/
  tools/vehicles/godot/vehicle_variants.gd                 -> game/addons/fleet_variants/vehicle_variants.gd
       (the fleet's KHR_materials_variants import extension; game/addons/fleet_variants/plugin.gd registers
        it in the editor, so the variant paints survive the import)
All three destinations are git-ignored copies.  Re-import afterwards:
    godot --headless --path game --import
Traffic picks the fleet up automatically (res://assets/vehicles/index.json) and falls back to the
stand-in fleet (game/assets/traffic/standin/) without it.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = sys.argv[sys.argv.index("--src") + 1] if "--src" in sys.argv else ROOT
GAME = os.path.join(ROOT, "game")


def copy(a, b):
    os.makedirs(os.path.dirname(b), exist_ok=True)
    if not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b) or os.path.getsize(a) != os.path.getsize(b):
        shutil.copy2(a, b)
        return 1
    return 0


def main():
    n = 0
    veh = os.path.join(SRC, "assets", "vehicles")
    if os.path.isfile(os.path.join(veh, "index.json")):
        n += copy(os.path.join(veh, "index.json"), os.path.join(GAME, "assets", "vehicles", "index.json"))
        for vid in sorted(os.listdir(veh)):
            d = os.path.join(veh, vid)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if fn.endswith((".glb", ".json")):
                    n += copy(os.path.join(d, fn), os.path.join(GAME, "assets", "vehicles", vid, fn))
        print("vehicles: index + %d vehicle folders" % len([x for x in os.listdir(veh) if os.path.isdir(os.path.join(veh, x))]))
    else:
        print("no assets/vehicles/index.json in", SRC, "- traffic keeps the stand-in fleet")
    props = os.path.join(SRC, "assets", "props")
    if os.path.isdir(props):
        k = 0
        for fn in os.listdir(props):
            if fn.endswith(".glb") or fn == "index.json":
                n += copy(os.path.join(props, fn), os.path.join(GAME, "assets", "props", fn))
                k += 1
        print("props: %d files (traffic lights: %s)" % (k, ", ".join(f for f in os.listdir(props) if f.startswith("traffic_light")) or "none yet"))
    ext = os.path.join(SRC, "tools", "vehicles", "godot", "vehicle_variants.gd")
    if os.path.isfile(ext):
        n += copy(ext, os.path.join(GAME, "addons", "fleet_variants", "vehicle_variants.gd"))
        print("fleet variant import extension installed (game/addons/fleet_variants)")
    print("%d files copied; now: godot --headless --path game --import" % n)


main()
