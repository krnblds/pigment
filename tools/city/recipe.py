"""Write a town Pigment script without running it (tools/town_textures.py is not modified).

    python -m tools.city.recipe town <job>          scenes/town/scripts/<job>.jsonl
    python -m tools.city.recipe town_world [names]  scenes/town/scripts/world/<name>.jsonl

tools/town_textures.py builds each script and runs it in one go. The city build splits that
in two steps: this one writes the script (the recipe in data form), and the Pigment node
runs it. So an edit to town_textures.py re-runs every *script writer* (cheap), but Pigment
runs only for the scripts whose content really changed.

It loads town_textures.py as a module and swaps its runner: the parts listing still goes to
pigment-mcp (the recipe needs the mesh's parts), the final run is skipped.
"""
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def load_town_textures():
    src = ROOT / "tools" / "town_textures.py"
    spec = importlib.util.spec_from_file_location("town_textures", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def town(job):
    T = load_town_textures()
    T.TMP.mkdir(parents=True, exist_ok=True)
    T.PREVIEWS.mkdir(parents=True, exist_ok=True)
    real_run = T.run

    def run(lines, label):
        if label.endswith("_parts"):
            return real_run(lines, label)          # list_parts: needed to write the recipe
        return ""                                   # the job itself: the city's Pigment node runs it

    T.run = run
    jobs = {
        "building_a": T.build_a, "building_b": T.build_b, "building_c": T.build_c,
        "street_segment": lambda: T.street("street_segment"), "crossroad": lambda: T.street("crossroad"),
        "street_lamp": lambda: T.small("street_lamp", "Gunmetal", T.lamp_extra),
        "power_pole": lambda: T.small("power_pole", "Concrete", T.pole_extra),
        "overhead_sign": lambda: T.small("overhead_sign", "Gunmetal", T.sign_extra, variants=True),
        "fence": T.fence,
    }
    if job not in jobs:
        raise SystemExit(f"unknown town_textures job {job!r}")
    jobs[job]()
    print(f"[recipe] wrote scenes/town/scripts/{job}.jsonl")


def town_world(names):
    T = load_town_textures()

    class _Sub(types.SimpleNamespace):
        @staticmethod
        def run(cmd, *a, **kw):
            if "--script" in [str(c) for c in cmd]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.run(cmd, *a, **kw)

    T.subprocess = _Sub()
    T.world_sheets(names or None)
    print(f"[recipe] wrote scenes/town/scripts/world/*.jsonl ({', '.join(names) or 'all'})")


if __name__ == "__main__":
    os.chdir(ROOT)
    kind, rest = sys.argv[1], sys.argv[2:]
    if kind == "town":
        town(rest[0])
    elif kind == "town_world":
        town_world(rest)
    else:
        raise SystemExit("usage: python -m tools.city.recipe town <job> | town_world [names]")
