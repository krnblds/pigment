"""Write docs/agents/decals/building_a_story.jsonl: building_a's town material
stack (from scenes/town/scripts/building_a.jsonl, minus its renders/export)
plus the story decals and close-up renders.

    python tools/decals_demo.py . docs/agents/decals
    target/release/pigment-mcp --script docs/agents/decals/building_a_story.jsonl
"""
import json, sys, os

root = sys.argv[1]
out_dir = sys.argv[2]  # where renders go
base = [json.loads(l) for l in open(os.path.join(root, "scenes/town/scripts/building_a.jsonl")) if l.strip()]
base = [c for c in base if c["tool"] not in ("render", "export_textures", "save_project")]

S = "assets/decals/story/"
wall_cam = {"yaw": 90, "pitch": 4, "target": [4.0, 1.75, 0.0]}
door_cam = {"yaw": -12, "pitch": 3, "target": [3.2, 1.6, 5.0], "distance": 3.4}


def r(name, **kw):
    a = dict(width=1200, height=720, exposure=-0.2)
    a.update(kw)
    a["path"] = f"{out_dir}/{name}.png"
    return {"tool": "render", "args": a}


calls = list(base)
calls.append(r("before_wall", **wall_cam, distance=7.5))
calls += [
    # MISSING posters and an UNPLUG poster, scattered at street level on the
    # long blank east wall (+X), torn and sun-faded
    {"tool": "scatter_decals", "args": {
        "images": [S + "poster_missing_aiko.png", S + "poster_missing_mika.png", S + "poster_missing_ren.png", S + "poster_unplug.png"],
        "count": 8, "seed": 3, "parts": [152], "region": {"min": [3.8, 0, -5.5], "max": [4.6, 5, 5.5]},
        "height": [0.5, 3.0], "size": [0.6, 0.8], "rotation_jitter": 5, "min_spacing": 0.85,
        "wear": 0.32, "fade": 0.3, "wear_scale": 3.5, "overlap_order": 0}},
    # one more round the corner by the shop front, anchored on the body's left face
    {"tool": "project_decal", "args": {"image": S + "poster_missing_ren.png", "part": 152, "face": "left", "anchor": [0.92, 0.595], "size": 0.65, "rotation": -3, "wear": 0.4, "fade": 0.35, "wear_scale": 3.5, "wear_seed": 4, "overlap_order": 0}},
    # resistance graffiti sprayed over some of them
    {"tool": "project_decal", "args": {"image": S + "graffiti_lying.png", "position": [4.4, 1.55, 0.6], "normal": [1, 0, 0], "size": 2.8, "rotation": 4, "fade": 0.25, "wear_style": "grunge", "paper_rim": 0, "overlap_order": 1}},
    {"tool": "project_decal", "args": {"image": S + "stencil_eye_crossed.png", "position": [4.4, 1.9, -3.2], "normal": [1, 0, 0], "size": 0.55, "rotation": -8, "fade": 0.3, "wear_style": "grunge", "paper_rim": 0, "overlap_order": 1}},
    # the Meridian plate on the pillar by the door, faintly lit
    {"tool": "project_decal", "args": {"image": S + "plate_observed.png", "position": [3.76, 1.9, 5.3], "normal": [0, 0, 1], "size": 0.42, "emissive_strength": 1.5, "layer": "Decals 1"}},
    {"tool": "list_layers", "args": {}},
]
calls += [
    r("after_wall", **wall_cam, distance=7.5),
    r("after_wall_closeup", yaw=90, pitch=2, target=[4.0, 1.7, 1.2], distance=3.4),
    r("after_door_plate", **door_cam),
    r("after_plate_closeup", yaw=-6, pitch=2, target=[3.55, 1.75, 5.0], distance=1.7, width=900, height=600),
    # undo the whole scatter in one step, then redo it
    ] + [{"tool": "undo", "args": {}}] * 6 + [
    r("../../../target/decals_demo/undo_check", **wall_cam, distance=7.5, width=600, height=360),
    ] + [{"tool": "redo", "args": {}}] * 6 + [
    r("../../../target/decals_demo/redo_check", **wall_cam, distance=7.5, width=600, height=360),
]
with open(os.path.join(root, "docs/agents/decals/building_a_story.jsonl"), "w", newline="\n") as f:
    for c in calls:
        f.write(json.dumps(c) + "\n")
print(len(calls), "calls")
