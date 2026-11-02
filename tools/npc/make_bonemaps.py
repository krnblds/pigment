"""Write the Godot BoneMap resources (SkeletonProfileHumanoid) for the skeletons the NPC pipeline meets.

    python tools/npc/make_bonemaps.py

  game/scripts/npc/character/bonemap_ue.tres      MPFB "game_engine" rig + Quaternius UAL (UE mannequin names)
  game/scripts/npc/character/bonemap_mixamo.tres  Mixamo rigs ("mixamorig:" prefix; the converter strips other prefixes)

The citizens' and the animation library's import settings point at these, so every skeleton is renamed
to the profile's bone names (Hips, Spine, LeftUpperArm, ...) under a unique "%GeneralSkeleton" and any
humanoid clip retargets onto any character.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "game", "scripts", "npc", "character")

SIDES = {"Left": "l", "Right": "r"}
UE = {"Root": "root", "Hips": "pelvis", "Spine": "spine_01", "Chest": "spine_02", "UpperChest": "spine_03",
      "Neck": "neck_01", "Head": "head"}
for S, s in SIDES.items():
    UE.update({
        f"{S}Shoulder": f"clavicle_{s}", f"{S}UpperArm": f"upperarm_{s}", f"{S}LowerArm": f"lowerarm_{s}", f"{S}Hand": f"hand_{s}",
        f"{S}UpperLeg": f"thigh_{s}", f"{S}LowerLeg": f"calf_{s}", f"{S}Foot": f"foot_{s}", f"{S}Toes": f"ball_{s}",
        f"{S}ThumbMetacarpal": f"thumb_01_{s}", f"{S}ThumbProximal": f"thumb_02_{s}", f"{S}ThumbDistal": f"thumb_03_{s}",
    })
    for g, n in (("Index", "index"), ("Middle", "middle"), ("Ring", "ring"), ("Little", "pinky")):
        UE.update({f"{S}{g}Proximal": f"{n}_01_{s}", f"{S}{g}Intermediate": f"{n}_02_{s}", f"{S}{g}Distal": f"{n}_03_{s}"})

MIXAMO = {"Hips": "Hips", "Spine": "Spine", "Chest": "Spine1", "UpperChest": "Spine2", "Neck": "Neck", "Head": "Head"}
for S in SIDES:
    MIXAMO.update({f"{S}Shoulder": f"{S}Shoulder", f"{S}UpperArm": f"{S}Arm", f"{S}LowerArm": f"{S}ForeArm", f"{S}Hand": f"{S}Hand",
                   f"{S}UpperLeg": f"{S}UpLeg", f"{S}LowerLeg": f"{S}Leg", f"{S}Foot": f"{S}Foot", f"{S}Toes": f"{S}ToeBase",
                   f"{S}ThumbMetacarpal": f"{S}HandThumb1", f"{S}ThumbProximal": f"{S}HandThumb2", f"{S}ThumbDistal": f"{S}HandThumb3"})
    for g, n in (("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Little", "Pinky")):
        MIXAMO.update({f"{S}{g}Proximal": f"{S}Hand{n}1", f"{S}{g}Intermediate": f"{S}Hand{n}2", f"{S}{g}Distal": f"{S}Hand{n}3"})


def write(name, mapping, prefix=""):
    lines = ['[gd_resource type="BoneMap" load_steps=2 format=3]', "",
             '[sub_resource type="SkeletonProfileHumanoid" id="SkeletonProfileHumanoid_1"]', "", "[resource]",
             'profile = SubResource("SkeletonProfileHumanoid_1")']
    for k, v in mapping.items():
        lines.append(f'bone_map/{k} = &"{prefix}{v}"')
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", name, len(mapping), "bones")


if __name__ == "__main__":
    ue = dict(UE)
    write("bonemap_ue.tres", ue)                          # UAL: lower-case "root"
    mp = dict(UE)
    mp["Root"] = "Root"                                    # MPFB game_engine: "Root"
    write("bonemap_mpfb.tres", mp)
    write("bonemap_mixamo.tres", MIXAMO, "mixamorig_")    # FBX import turns "mixamorig:" into "mixamorig_"
