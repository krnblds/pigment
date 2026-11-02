"""Install the built citizens + animation sources into the Godot project and import them (system Python).

    python tools/npc/sync_godot.py [--no-import] [--godot <console exe>]

  .npccache/citizens/<id>.glb, <id>_{albedo,normal,mask}.png  -> game/assets/npc/citizens/
  .npccache/citizens/<id>.json (atlas specs)                   -> game/assets/npc/index.json (one manifest)
  .npccache/ual/UAL{1,2}_Standard.glb                          -> game/assets/npc/anim/ual{1,2}.glb
  game/assets/npc/anim_extra/                                  the git-ignored drop folder for extra clips
Writes the .import files (humanoid retarget onto SkeletonProfileHumanoid through
game/scripts/npc/character/bonemap_*.tres, normal-map / linear texture modes), runs
`godot --headless --import`, then builds res://assets/npc/anim/library(.lite).res.
Everything under game/assets/npc/ is git-ignored and regenerated.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME = os.path.join(ROOT, "game")
DST = os.path.join(GAME, "assets", "npc")
CACHE = os.path.join(ROOT, ".npccache")
GODOT_DEFAULT = r"C:\Users\kiera\Desktop\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64_console.exe"

RETARGET = """{
"nodes": {
"PATH:%(skel)s": {
"retarget/bone_map": Resource("%(bonemap)s"),
"retarget/bone_renamer/rename_bones": true,
"retarget/bone_renamer/unique_node/make_unique": true,
"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",
"retarget/rest_fixer/apply_node_transforms": true,
"retarget/rest_fixer/normalize_position_tracks": true,
"retarget/rest_fixer/reset_all_bone_poses_after_import": true,
"retarget/rest_fixer/retarget_method": 1,
"retarget/rest_fixer/fix_silhouette/enable": true,
"retarget/remove_tracks/except_bone_transform": true,
"retarget/remove_tracks/unimportant_positions": false,
"retarget/remove_tracks/unmapped_bones": false
}
}
}"""

SCENE_IMPORT = """[remap]

importer="scene"
importer_version=1
type="PackedScene"

[deps]

source_file="%(src)s"

[params]

nodes/root_type=""
nodes/root_name=""
nodes/apply_root_scale=true
nodes/root_scale=1.0
nodes/import_as_skeleton_bones=false
nodes/use_name_suffixes=true
nodes/use_node_type_suffixes=true
meshes/ensure_tangents=true
meshes/generate_lods=false
meshes/create_shadow_meshes=true
meshes/light_baking=0
meshes/lightmap_texel_size=0.2
meshes/force_disable_compression=false
skins/use_named_skins=true
animation/import=%(anim)s
animation/fps=30
animation/trimming=false
animation/remove_immutable_tracks=true
animation/import_rest_as_RESET=false
import_script/path=""
materials/extract=0
materials/extract_format=0
materials/extract_path=""
_subresources=%(sub)s
gltf/naming_version=2
gltf/embedded_image_handling=1
gltf/texture_map_mode=1
"""

TEX_IMPORT = """[remap]

importer="texture"
type="CompressedTexture2D"

[deps]

source_file="%(src)s"

[params]

compress/mode=2
compress/high_quality=false
compress/lossy_quality=0.7
compress/hdr_compression=1
compress/normal_map=%(normal)d
compress/channel_pack=0
mipmaps/generate=true
mipmaps/limit=-1
roughness/mode=0
roughness/src_normal=""
process/fix_alpha_border=true
process/premult_alpha=false
process/normal_map_invert_y=false
process/hdr_as_srgb=false
process/hdr_clamp_exposure=false
process/size_limit=0
detect_3d/compress_to=0
"""


def copy(a, b):
    os.makedirs(os.path.dirname(b), exist_ok=True)
    if not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b) or os.path.getsize(a) != os.path.getsize(b):
        shutil.copy2(a, b)
        return 1
    return 0


def write_import(path, text):
    """Write the .import unless it already holds the same params (keeps Godot's uid / dest lines)."""
    imp = path + ".import"
    if os.path.exists(imp):
        old = open(imp, encoding="utf-8").read()
        want = text.split("[params]", 1)[1].strip()
        have = old.split("[params]", 1)[1].strip() if "[params]" in old else ""
        if all(line in have for line in want.splitlines() if line and not line.startswith("_subresources")) and \
                ("retarget/bone_map" in have) == ("retarget/bone_map" in want):
            return 0
    with open(imp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return 1


def res(p):
    return "res://" + os.path.relpath(p, GAME).replace("\\", "/")


def main():
    src = os.path.join(CACHE, "citizens")
    specs = sorted(glob.glob(os.path.join(src, "*.json")))
    if not specs:
        sys.exit("no citizens in %s: run tools/npc/build_all.py first" % src)
    n = 0
    index = {"format": "pigment-citizens/1", "atlas": 1024, "citizens": []}
    cdir = os.path.join(DST, "citizens")
    for sp in specs:
        cid = os.path.splitext(os.path.basename(sp))[0]
        files = [cid + ".glb", cid + "_albedo.png", cid + "_normal.png", cid + "_mask.png"]
        if not all(os.path.isfile(os.path.join(src, f)) for f in files):
            print("skip", cid, "(not composed)")
            continue
        for f in files:
            n += copy(os.path.join(src, f), os.path.join(cdir, f))
        s = json.load(open(sp))
        rc = s["recipe"]
        M = s["metrics"]
        index["citizens"].append({
            "id": cid, "sex": rc["sex"], "archetype": rc["archetype"], "height": s["height"], "tris": s["tris"],
            "hips": round(M["pelvis"][2], 3), "shoulder": round(M["shoulder_l"][2], 3), "knee": round(M["knee_l"][2], 3),
            "umbrella": rc.get("umbrella"), "walk_speed": rc.get("walk_speed", 1.3), "idle": rc.get("idle", "Idle"),
            "shell": (rc.get("shell") or {}).get("kind"), "player": rc["archetype"] == "waker",
            "clothes": s["used"].get("clothes", []), "hair": s["used"].get("hair"), "skin": s["used"].get("skin"),
            "glb": "res://assets/npc/citizens/%s.glb" % cid,
            "albedo": "res://assets/npc/citizens/%s_albedo.png" % cid, "normal": "res://assets/npc/citizens/%s_normal.png" % cid,
            "mask": "res://assets/npc/citizens/%s_mask.png" % cid})
        glb = os.path.join(cdir, cid + ".glb")
        n += write_import(glb, SCENE_IMPORT % {"src": res(glb), "anim": "false",
                                               "sub": RETARGET % {"skel": "Armature/Skeleton3D", "bonemap": "res://scripts/npc/character/bonemap_mpfb.tres"}})
        for kind in ("albedo", "normal", "mask"):
            p = os.path.join(cdir, "%s_%s.png" % (cid, kind))
            n += write_import(p, TEX_IMPORT % {"src": res(p), "normal": 1 if kind == "normal" else 0})
    with open(os.path.join(DST, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    adir = os.path.join(DST, "anim")
    for k, name in (("ual1", "UAL1_Standard.glb"), ("ual2", "UAL2_Standard.glb")):
        a = os.path.join(CACHE, "ual", name)
        if not os.path.isfile(a):
            sys.exit("missing %s: python tools/npc/fetch_assets.py" % a)
        d = os.path.join(adir, k + ".glb")
        n += copy(a, d)
        n += write_import(d, SCENE_IMPORT % {"src": res(d), "anim": "true",
                                             "sub": RETARGET % {"skel": "Armature/Skeleton3D", "bonemap": "res://scripts/npc/character/bonemap_ue.tres"}})
    for lic in glob.glob(os.path.join(CACHE, "ual", "LICENSE_*.txt")):
        copy(lic, os.path.join(adir, os.path.basename(lic)))
    extra = os.path.join(DST, "anim_extra")
    os.makedirs(extra, exist_ok=True)
    with open(os.path.join(extra, "README.txt"), "w") as f:
        f.write("Drop extra humanoid clips here (FBX, e.g. downloaded from Mixamo 'Without Skin', 30 fps),\n"
                "then run: python tools/npc/convert_extra_anims.py\n"
                "This folder is git-ignored: never commit third-party clips. See docs/agents/npc/NOTES.md.\n")
    open(os.path.join(extra, ".gdignore"), "w").close()        # Godot must not import the raw drops here
    print("npc: %d citizens, %d files written to %s" % (len(index["citizens"]), n, DST))
    if "--no-import" in sys.argv:
        return
    godot = sys.argv[sys.argv.index("--godot") + 1] if "--godot" in sys.argv else os.environ.get("GODOT", GODOT_DEFAULT)
    r = subprocess.run([godot, "--headless", "--path", GAME, "--import"], capture_output=True, text=True)
    errs = [l for l in (r.stdout + r.stderr).splitlines() if "ERROR" in l and "npc" in l]
    print("godot import:", "ok" if r.returncode == 0 else "exit %d" % r.returncode, ("\n" + "\n".join(errs[:10])) if errs else "")
    r = subprocess.run([godot, "--headless", "--path", GAME, "-s", "res://scripts/npc/character/build_anim_library.gd"],
                       capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if "npc" in l) or r.stdout[-800:])
    if r.returncode != 0:
        sys.exit("animation library build failed")


if __name__ == "__main__":
    main()
