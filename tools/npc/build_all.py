"""Regenerate every pedestrian asset (system Python; needs Blender 5.2 with MPFB, Godot 4.7; pigment-mcp optional).

    python tools/npc/build_all.py [--jobs 3] [--no-fetch] [--no-pigment] [--blender <exe>] [--godot <console exe>]

  1. fetch_assets.py      CC0 MakeHuman packs -> MPFB user data; Quaternius UAL 1 + 2 -> .npccache/ual/
  2. build_citizens.py    32 citizens (headless Blender, --jobs processes)
  3. compose_atlas.py     the 1024 atlases (colour, normal, roughness / rain / emission masks)
  4. paint_citizens.py    Pigment weathering pass (grime, rain splash) when pigment-mcp is built
  5. sync_godot.py        -> game/assets/npc/ (+ import settings, Godot import, animation library)
  then, if you dropped extra clips into game/assets/npc/anim_extra/: python tools/npc/convert_extra_anims.py
Everything generated is git-ignored (.npccache/, game/assets/npc/).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import recipes as R  # noqa: E402

BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def py(script, *a):
    r = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(a), cwd=ROOT)
    if r.returncode != 0:
        sys.exit("%s failed" % script)


def main():
    jobs = int(arg("--jobs", "3"))
    blender = arg("--blender", os.environ.get("BLENDER", BLENDER))
    if "--no-fetch" not in sys.argv:
        py("fetch_assets.py")
    ids = [r["id"] for r in R.make_recipes()]
    logs = os.path.join(ROOT, ".npccache", "logs")
    os.makedirs(logs, exist_ok=True)
    procs = []
    for k in range(jobs):
        chunk = ids[k::jobs]
        lf = open(os.path.join(logs, "build_%d.log" % k), "w")
        procs.append((subprocess.Popen([blender, "-b", "--factory-startup", "--python", os.path.join(HERE, "build_citizens.py"),
                                        "--", "--only", ",".join(chunk)], stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT), lf))
    for p, lf in procs:
        p.wait()
        lf.close()
    built = sum(1 for k in range(jobs) for l in open(os.path.join(logs, "build_%d.log" % k)) if " done: tris" in l)
    print("citizens built: %d / %d (logs in .npccache/logs)" % (built, len(ids)))
    py("compose_atlas.py")
    if "--no-pigment" not in sys.argv:
        py("paint_citizens.py")
    extra = ["--godot", arg("--godot")] if arg("--godot") else []
    py("sync_godot.py", *extra)


if __name__ == "__main__":
    main()
