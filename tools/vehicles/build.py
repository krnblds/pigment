"""Build one vehicle of the fleet from its spec (headless Blender 5.2).

    blender -b --factory-startup --python tools/vehicles/build.py -- NAME [--preview DIR] [--no-export]
    blender -b --factory-startup --python tools/vehicles/build.py -- all

NAME is a module in tools/vehicles/specs/ (tsubame, ...). The spec is data (body sections,
panel layout, light designs, wheel set, part kits, interior kit) plus a few custom parts;
the kit in tools/vehicles/vkit/ turns it into geometry. Writes to the spec's `src` folder
(assets/vehicles/<id>/src/ by default):

    <id>_body.glb     the body as Pigment paints it (one mesh, parts = connected pieces)
    <id>_wheel.glb    one wheel (tyre, rim, disc, caliper), hub at the origin
    <id>_parts.json   every named piece: group, centre, size, triangles (for textures.py)
    <id>_info.json    the node contract numbers (wheel positions, lights, mass, triangles)
    <id>_model.blend  Body, Wheel_*, Caliper_*, Collider, lamp empties, LOD1 + LOD2 collections

Textures are made in Pigment (tools/vehicles/textures.py), then tools/vehicles/export.py
writes assets/vehicles/<id>/<id>.glb, <id>_lod1.glb, <id>_lod2.glb and <id>.json.
"""
import importlib
import math
import os
import sys
import time

import bpy
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from vkit import body as B  # noqa: E402
from vkit import cfg  # noqa: E402
from vkit import chassis, interior, lights, trim  # noqa: E402
from vkit import panels as P  # noqa: E402
from vkit import wheels as W  # noqa: E402

# the Tsubame-4's material groups (always listed, so its parts.json is unchanged); vehicles that
# use more groups append them (sorted list of the union)
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
EXTRA_COLOURS = {
    "rim_dark": (0.05, 0.05, 0.05), "paint_trim": (0.6, 0.6, 0.62), "cargo": (0.7, 0.7, 0.68), "cargo_frame": (0.4, 0.4, 0.42),
    "wood": (0.35, 0.22, 0.12), "emitter_sign": (0.9, 0.9, 0.95), "emitter_cyan": (0.1, 0.8, 1.0), "sign_lens": (0.85, 0.85, 0.9),
    "interior_floor": (0.15, 0.15, 0.16), "handrail": (0.8, 0.7, 0.2),
}

KITS = {
    "headlights": lights.headlights, "taillights": lights.taillights,
    "grille": trim.grille, "window_seals": trim.window_seals, "body_mouldings": trim.body_mouldings,
    "fender_flares": trim.fender_flares, "arch_lips": trim.arch_lips, "mirrors": trim.mirrors,
    "door_handles": trim.door_handles, "wipers": trim.wipers, "plates": trim.plates, "exhaust": trim.exhaust,
    "mudflaps": trim.mudflaps, "boxes": trim.boxes, "tubes": trim.tubes, "glass_frit": trim.glass_frit,
    "wheel_wells": chassis.wheel_wells, "suspension": chassis.suspension, "beam_axle": chassis.beam_axle,
    "seat": interior.seat, "seat_rows": interior.seat_rows, "shifter": interior.shifter, "steering": interior.steering,
}


def preview_material(group):
    name = f"prev_{group}"
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        c = GROUP_COLOURS.get(group) or EXTRA_COLOURS.get(group, (0.5, 0.5, 0.5))
        if group == "paint":
            c = (0.55, 0.56, 0.58)
        m.diffuse_color = (*c, 1.0)
    return m


def load_spec(name):
    mod = importlib.import_module(f"specs.{name}")
    importlib.reload(mod)
    v = cfg.use(mod.SPEC, mod)
    v.setdefault("id_src", v.id)
    v.setdefault("src", f"assets/vehicles/{v.id}/src")
    return v, mod


def run_parts(v, mod, pieces):
    reg = []
    for it in v.parts:
        if "custom" in it:
            reg += getattr(mod, it.custom)(it)
        elif it.kit == "door_cards":
            reg += interior.door_cards(pieces, it)
        elif it.kit == "headliner":
            reg += interior.headliner(pieces["body_shell"], it)
        else:
            reg += KITS[it.kit](it)
    return reg


def build_body(v, mod):
    cage = B.build_cage()
    B.subdivide(cage, v.body.get("subd", 2))
    pieces, panes = P.cut_body(cage)
    reg = []
    for nm, ob in pieces.items():
        reg.append((nm, "paint", ob))
    for nm, (ob, grp) in panes.items():
        reg.append((nm, grp, ob))
    reg += run_parts(v, mod, pieces)
    # ride height: everything was modelled `body_drop` high (arches round arch_z)
    for nm, grp, ob in reg:
        ob.data.transform(Matrix.Translation((0, 0, -v.body_drop)))
    return reg


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def build(name, preview=None, export=True):
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    v, mod = load_spec(name)
    reg = build_body(v, mod)
    wheel_parts, caliper = W.build_wheel()
    print(f"[build] {v.id}: {len(reg)} body parts in {time.time() - t0:.1f}s, body tris {sum(tris(o) for _, _, o in reg)}, "
          f"wheel tris {sum(tris(o) for _, _, o in wheel_parts) + tris(caliper[2])}")
    used = {g for _, g, _ in reg + wheel_parts + [caliper]}
    unknown = used - set(GROUP_COLOURS) - set(EXTRA_COLOURS)
    if unknown:
        raise SystemExit(f"unknown material groups {sorted(unknown)}")
    groups = sorted(set(GROUP_COLOURS) | used)
    if preview:
        from vkit import preview as PV
        for nm, grp, ob in reg + wheel_parts + [caliper]:
            ob.data.materials.clear()
            ob.data.materials.append(preview_material(grp))
        tmp = []
        for axle in v.axles:
            for sx in (1, -1):
                for (nm, grp, ob) in wheel_parts + [caliper]:
                    n = ob.copy()
                    bpy.context.scene.collection.objects.link(n)
                    n.location = (sx * v.track / 2, axle, v.wheel_r)
                    n.rotation_euler = (0, 0, 0 if sx > 0 else math.pi)
                    tmp.append(n)
        for (nm, grp, ob) in wheel_parts + [caliper]:
            ob.location.z -= 50
        length = v.rear - v.front
        PV.clay(preview, views=v.get("preview_views", ("front34", "rear34", "side", "front", "rear", "wheel", "interior")),
                scale=v.get("preview_scale", max(1.0, length / 4.44)), zc=max(0.0, (v.get("height", 1.4) - 1.4) * 0.4),
                wheel_target=(v.track / 2, B.axle_f(), v.wheel_r))
        for (nm, grp, ob) in wheel_parts + [caliper]:
            ob.location.z += 50
        for n in tmp:
            bpy.data.objects.remove(n, do_unlink=True)
    if not export:
        return None
    from vkit import assemble as A
    src = os.path.join(ROOT, v.src)
    info = A.assemble(reg, wheel_parts, caliper, groups, src)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(src, f"{v.id_src}_model.blend"), compress=True)
    print(f"[build] {v.id}: triangles {info['triangles']}")
    print(f"[build] {v.id}: done in {time.time() - t0:.1f}s")
    return info


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names = [a for a in argv if not a.startswith("--") and (argv.index(a) == 0 or argv[argv.index(a) - 1] != "--preview")]
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None
    if not names:
        raise SystemExit("usage: build.py -- NAME|all [--preview DIR] [--no-export]")
    if names == ["all"]:
        from specs import FLEET
        names = FLEET
    for n in names:
        build(n, os.path.join(preview, n) if preview and len(names) > 1 else preview, "--no-export" not in argv)


if __name__ == "__main__":
    main()
