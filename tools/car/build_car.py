"""Build the Kanzaki Tsubame-4 "Hoshikawa Security" cruiser (headless Blender 5.2).

A fictional 1994 four-door sedan, converted for Hoshikawa Security: push bar,
roof light bar, A-pillar spotlight, rear partition and a dash terminal, bolt-on
overfenders. Everything is generated from code and is deterministic.

    blender -b --factory-startup --python tools/car/build_car.py -- [--preview DIR] [--no-export]

Writes (paths relative to the repo root):
    assets/car/src/car_body.glb       the body as Pigment paints it (one mesh, parts = connected pieces)
    assets/car/src/car_wheel.glb      one wheel (tyre, rim, disc, caliper), hub at the origin
    assets/car/src/car_parts.json     every named piece: group, centre, size, triangles (for car_textures.py)
    assets/car/src/car_model.blend    the assembled model (Body, Wheel_*, Caliper_*, Collider, lamp empties, LOD1)
Textures are made in Pigment (tools/car/car_textures.py); tools/car/export_car.py
then wires them in and writes assets/car/car.glb, car_lod1.glb and car.json.
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import body as B  # noqa: E402
import panels as P  # noqa: E402
import parts as PT  # noqa: E402
import wheels as W  # noqa: E402
from carlib import apply_mods, delete  # noqa: E402

SRC = os.path.join(ROOT, "assets", "car", "src")

GROUP_COLOURS = {
    "paint": (0.05, 0.08, 0.20), "black_trim": (0.02, 0.02, 0.02), "black_metal": (0.03, 0.03, 0.03),
    "chrome": (0.8, 0.8, 0.8), "rubber": (0.01, 0.01, 0.01), "glass": (0.3, 0.4, 0.45), "mirror": (0.7, 0.75, 0.8),
    "lens_clear": (0.75, 0.8, 0.85), "lens_red": (0.5, 0.02, 0.02), "lens_amber": (0.8, 0.4, 0.02),
    "emitter_head": (1.0, 0.95, 0.85), "emitter_tail": (0.9, 0.05, 0.03), "emitter_amber": (1.0, 0.5, 0.0),
    "emitter_reverse": (0.95, 0.95, 0.95), "emitter_red": (1.0, 0.05, 0.05), "emitter_blue": (0.05, 0.2, 1.0),
    "lightbar_lens_red": (0.6, 0.05, 0.05), "lightbar_lens_blue": (0.05, 0.1, 0.6), "lightbar_center": (0.9, 0.9, 0.9),
    "grille": (0.03, 0.03, 0.03), "plate": (0.9, 0.9, 0.85), "exhaust": (0.5, 0.5, 0.5),
    "underbody": (0.05, 0.05, 0.05), "underbody_metal": (0.2, 0.18, 0.16), "suspension": (0.15, 0.15, 0.15),
    "spring": (0.6, 0.1, 0.05), "interior_fabric": (0.12, 0.12, 0.13), "interior_plastic": (0.08, 0.08, 0.09),
    "interior_dark": (0.03, 0.03, 0.035), "interior_leather": (0.04, 0.03, 0.03), "interior_carpet": (0.05, 0.05, 0.05),
    "screen": (0.1, 0.4, 0.5), "tyre": (0.02, 0.02, 0.02), "rim": (0.6, 0.6, 0.62), "lug": (0.8, 0.8, 0.8),
    "brake_disc": (0.35, 0.33, 0.32), "caliper": (0.7, 0.35, 0.02), "frit": (0.01, 0.01, 0.01),
}


def preview_material(group):
    name = f"prev_{group}"
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        c = GROUP_COLOURS.get(group, (0.5, 0.5, 0.5))
        m.diffuse_color = (*c, 1.0)
    return m


def build_body():
    cage = B.build_cage()
    B.subdivide(cage, 2)
    pieces, panes = P.cut_body(cage)
    reg = []
    for nm, ob in pieces.items():
        reg.append((nm, "paint", ob))
    for nm, ob in panes.items():
        grp = "glass"
        if nm.startswith("headlight_lens"):
            grp = "lens_clear"
        elif nm.startswith("indicator_lens"):
            grp = "lens_amber"
        elif nm.startswith("taillight_lens"):
            grp = "lens_red"
        reg.append((nm, grp, ob))
    for fn in (PT.headlights, PT.taillights, PT.grille, PT.push_bar, PT.window_seals, PT.body_mouldings,
               PT.fender_flares, PT.mirrors, PT.door_handles, PT.wipers, PT.plates, PT.exhaust, PT.roof_gear,
               PT.mudflaps, PT.underbody, PT.wheel_wells, PT.suspension, PT.interior):
        reg += fn()
    reg += PT.door_cards(pieces)
    reg += PT.headliner(pieces["body_shell"])
    reg += PT.glass_frit()
    # ride height: everything was modelled BODY_DROP high (arches round ARCH_Z)
    for nm, grp, ob in reg:
        ob.data.transform(Matrix.Translation((0, 0, -B.BODY_DROP)))
    return reg


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    reg = build_body()
    wheel_parts, caliper = W.build_wheel()
    print(f"[car] built {len(reg)} body parts in {time.time() - t0:.1f}s, body tris {sum(tris(o) for _, _, o in reg)}, "
          f"wheel tris {sum(tris(o) for _, _, o in wheel_parts) + tris(caliper[2])}")
    if preview:
        import preview as PV
        for nm, grp, ob in reg + wheel_parts + [caliper]:
            ob.data.materials.clear()
            ob.data.materials.append(preview_material(grp))
        tmp = []
        for axle in (B.AXLE_F, B.AXLE_R):
            for sx in (1, -1):
                for (nm, grp, ob) in wheel_parts + [caliper]:
                    n = ob.copy()
                    bpy.context.scene.collection.objects.link(n)
                    n.location = (sx * B.TRACK / 2, axle, B.WHEEL_R)
                    n.rotation_euler = (0, 0, 0 if sx > 0 else math.pi)
                    tmp.append(n)
        for (nm, grp, ob) in wheel_parts + [caliper]:
            ob.location.z -= 50
        PV.clay(preview, views=("front34", "rear34", "side", "front", "rear", "low34", "wheel"))
        for (nm, grp, ob) in wheel_parts + [caliper]:
            ob.location.z += 50
        for n in tmp:
            bpy.data.objects.remove(n, do_unlink=True)
    if "--no-export" in argv:
        return
    import assemble as A
    info = A.assemble(reg, wheel_parts, caliper, sorted(GROUP_COLOURS), SRC)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(SRC, "car_model.blend"), compress=True)
    print(f"[car] triangles {info['triangles']}")
    print(f"[car] done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
