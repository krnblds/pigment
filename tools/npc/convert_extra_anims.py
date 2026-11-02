"""Turn extra humanoid clips dropped into game/assets/npc/anim_extra/ into the citizens' extra library.

    python tools/npc/convert_extra_anims.py [--godot <console exe>]

Drop FBX (or glTF binary) files with ONE humanoid animation each into game/assets/npc/anim_extra/ - e.g.
Mixamo downloads ("FBX Binary", "Without Skin", 30 fps, In Place where offered).  The file name becomes
the clip name: "Smoking.fbx" -> "extra_smoking".  The walkers use clips whose names contain smok / phone /
lean / argu / sweep as idle activities outside shops and bars (npc_manager.gd); the game works without
any (it falls back to the CC0 idles).  Every humanoid naming that Godot's SkeletonProfileHumanoid can map
works: the script reads the skeleton, writes a BoneMap for its prefix ("mixamorig:", "mixamorig1_", none)
and retargets on import exactly like the citizens.

The drop folder, the staged copies (game/assets/npc/anim/extra/) and the library are all git-ignored:
third-party clips (Mixamo's terms forbid redistributing them) never end up in the repository.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_bonemaps as BM  # noqa: E402
import sync_godot as SG  # noqa: E402

ROOT = SG.ROOT
GAME = SG.GAME
DROP = os.path.join(GAME, "assets", "npc", "anim_extra")
STAGE = os.path.join(GAME, "assets", "npc", "anim", "extra")
SRC = os.path.join(STAGE, "src")


def run(godot, *args):
    return subprocess.run([godot, "--headless", "--path", GAME] + list(args), capture_output=True, text=True)


def bonemap_for(names):
    """BoneMap text for this skeleton: match the Mixamo names after whatever prefix the file uses."""
    by_suffix = {}
    for n in names:
        suf = re.split(r"[:_]", n, maxsplit=1)[-1] if re.match(r"^mixamorig\d*[:_]", n) else n
        by_suffix[suf] = n
    lines = ['[gd_resource type="BoneMap" load_steps=2 format=3]', "",
             '[sub_resource type="SkeletonProfileHumanoid" id="SkeletonProfileHumanoid_1"]', "", "[resource]",
             'profile = SubResource("SkeletonProfileHumanoid_1")']
    hit = 0
    for prof, mix in BM.MIXAMO.items():
        if mix in by_suffix:
            lines.append(f'bone_map/{prof} = &"{by_suffix[mix]}"')
            hit += 1
    # UE-mannequin named clips work too
    if hit < 10:
        for prof, ue in BM.UE.items():
            for n in names:
                if n.lower() == ue:
                    lines.append(f'bone_map/{prof} = &"{n}"')
                    hit += 1
    return "\n".join(lines) + "\n", hit


def main():
    godot = sys.argv[sys.argv.index("--godot") + 1] if "--godot" in sys.argv else os.environ.get("GODOT", SG.GODOT_DEFAULT)
    drops = sorted({os.path.normcase(p): p for p in glob.glob(os.path.join(DROP, "*.[fF][bB][xX]")) + glob.glob(os.path.join(DROP, "*.glb"))}.values())
    if not drops:
        print("no clips in", DROP, "- nothing to do (the game uses the CC0 idles)")
        return
    os.makedirs(SRC, exist_ok=True)
    staged = []
    for p in drops:
        slug = re.sub(r"[^a-z0-9_]+", "_", os.path.splitext(os.path.basename(p))[0].lower()).strip("_")
        dst = os.path.join(SRC, slug + os.path.splitext(p)[1].lower())
        SG.copy(p, dst)
        staged.append(dst)
        # pass 1: Godot's default import (to read the skeleton); a previous retarget is redone
        imp = dst + ".import"
        if os.path.exists(imp):
            old = open(imp, encoding="utf-8").read()
            if "retarget/bone_map" in old or "valid=false" in old:
                os.remove(imp)
    r = run(godot, "--import")
    r = run(godot, "-s", "res://scripts/npc/character/build_extra_anims.gd", "--", "bones")
    found = 0
    for line in r.stdout.splitlines():
        if not line.startswith("NPCBONES "):
            continue
        _, path, skel, names = line.split(" ", 3)
        names = json.loads(names)
        text, hit = bonemap_for(names)
        if hit < 10:
            print("skip %s: only %d humanoid bones recognised" % (path, hit))
            continue
        local = os.path.join(GAME, path.replace("res://", "").replace("/", os.sep))
        bm = os.path.splitext(local)[0] + "_bonemap.tres"
        with open(bm, "w", newline="\n") as f:
            f.write(text)
        sub = SG.RETARGET % {"skel": skel, "bonemap": SG.res(bm)}
        with open(local + ".import", encoding="utf-8") as f:
            imp = f.read()
        # keep Godot's own (FBX) import params, set only the skeleton's retarget sub-resource
        imp = re.sub(r"_subresources=\{.*?\n\}\n|_subresources=\{\}\n", lambda m: "_subresources=" + sub + "\n", imp, count=1, flags=re.S)
        with open(local + ".import", "w", newline="\n", encoding="utf-8") as f:
            f.write(imp)
        found += 1
    print("%d of %d clips have a humanoid skeleton" % (found, len(staged)))
    run(godot, "--import")
    r = run(godot, "-s", "res://scripts/npc/character/build_extra_anims.gd", "--", "build")
    print("\n".join(l for l in r.stdout.splitlines() if "npc extra" in l) or r.stdout[-600:])


if __name__ == "__main__":
    main()
