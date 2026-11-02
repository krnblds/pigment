"""Model the Waker's kit (headless Blender 5.2): low-poly, bevelled, UV-unwrapped source meshes for
Pigment.

    blender -b --factory-startup --python tools/weapons/make_weapons.py

Writes assets/weapons/src/<id>.glb and <id>.json (per part: name, role, glTF-space bbox centre / size,
so tools/weapons/weapons_textures.py can find Pigment's parts by box) for:

    stun_baton      Komori stun baton: rubber grip rings, steel shaft, glowing contact cap
    taser           HS-T2 taser: yellow polymer body, black cartridge, cyan contacts
    service_pistol  HS-9 service pistol: gunmetal slide, polymer frame, cyan status strip
    smg             HS-K Shrike SMG: receiver, shroud, magazine, folding stock, amber strip
    shotgun         Mukade-12 pump shotgun: receiver, barrel + tube, ribbed pump, stock
    emp             Hush EMP charge: knurled sphere, glowing band, pull ring

Contract (as game/scripts/weapons/weapon_models.gd expects): grip / hand point at the origin, barrel
along Blender +Y (glTF -Z, Godot -Z), up +Z; a "Muzzle" empty at the barrel end is added by
export_weapons.py from the json.
"""
import json
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "assets", "weapons", "src")


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


class Kit:
    def __init__(self, wid):
        self.id = wid
        self.parts = []
        self.muzzle = (0.0, 0.2, 0.05)

    def _finish(self, ob, role, bevel):
        if bevel > 0:
            m = ob.modifiers.new("bevel", "BEVEL")
            m.width = bevel
            m.segments = 2
            m.limit_method = "ANGLE"
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.modifier_apply(modifier="bevel")
        ob["role"] = role
        self.parts.append(ob)
        return ob

    def box(self, name, role, size, center, rot=(0, 0, 0), bevel=0.0015):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=center, rotation=[math.radians(a) for a in rot])
        ob = bpy.context.active_object
        ob.name = f"{self.id}_{name}"
        ob.scale = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        return self._finish(ob, role, bevel)

    def cyl(self, name, role, r, length, center, axis="Y", verts=12, bevel=0.001, r2=None):
        rot = {"X": (0, 90, 0), "Y": (90, 0, 0), "Z": (0, 0, 0)}[axis]
        if r2 is None:
            bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=length, location=center, rotation=[math.radians(a) for a in rot])
        else:
            bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r2, depth=length, location=center, rotation=[math.radians(a) for a in rot])
        ob = bpy.context.active_object
        ob.name = f"{self.id}_{name}"
        return self._finish(ob, role, bevel)

    def torus(self, name, role, R, r, center, axis="Z"):
        rot = {"X": (0, 90, 0), "Y": (90, 0, 0), "Z": (0, 0, 0)}[axis]
        bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=20, minor_segments=6, location=center, rotation=[math.radians(a) for a in rot])
        ob = bpy.context.active_object
        ob.name = f"{self.id}_{name}"
        return self._finish(ob, role, 0)

    def sphere(self, name, role, r, center, sub=2):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=sub, radius=r, location=center)
        ob = bpy.context.active_object
        ob.name = f"{self.id}_{name}"
        return self._finish(ob, role, 0)

    def save(self):
        os.makedirs(OUT, exist_ok=True)
        records = []
        for ob in self.parts:
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            # UVs: smart project per part, packed together after the join
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")
            ob.select_set(False)
            ws = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            lo = Vector((min(v.x for v in ws), min(v.y for v in ws), min(v.z for v in ws)))
            hi = Vector((max(v.x for v in ws), max(v.y for v in ws), max(v.z for v in ws)))
            c = (lo + hi) / 2
            s = hi - lo
            # Blender (x, y, z) -> glTF (x, z, -y)
            records.append({"name": ob.name, "role": ob["role"], "center": [c.x, c.z, -c.y], "size": [s.x, s.z, s.y]})
        for ob in self.parts:
            ob.select_set(True)
        bpy.context.view_layer.objects.active = self.parts[0]
        bpy.ops.object.join()
        main = bpy.context.active_object
        main.name = self.id
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.pack_islands(margin=0.01)
        bpy.ops.object.mode_set(mode="OBJECT")
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
        except Exception:
            bpy.ops.object.shade_smooth()
        tris = sum(len(p.vertices) - 2 for p in main.data.polygons)
        path = os.path.join(OUT, f"{self.id}.glb")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
                                  export_materials="NONE")
        m = self.muzzle
        with open(os.path.join(OUT, f"{self.id}.json"), "w") as f:
            json.dump({"id": self.id, "parts": records, "triangles": tris, "muzzle_gltf": [m[0], m[2], -m[1]]}, f, indent=1)
        print(f"{self.id}: {len(records)} parts, {tris} tris -> {path}")


def baton():
    k = Kit("stun_baton")
    k.cyl("grip", "rubber", 0.017, 0.2, (0, 0.0, 0), verts=14)
    for i in range(5):
        k.torus(f"ring{i}", "rubber_dark", 0.0175, 0.003, (0, -0.08 + i * 0.04, 0), axis="Y")
    k.cyl("guard", "steel", 0.022, 0.012, (0, 0.105, 0), verts=14)
    k.cyl("shaft", "steel", 0.012, 0.4, (0, 0.31, 0), verts=12)
    k.cyl("tip", "glow_cyan", 0.016, 0.04, (0, 0.53, 0), verts=14)
    k.cyl("pommel", "steel", 0.019, 0.02, (0, -0.11, 0), verts=14)
    k.box("switch", "glow_amber", (0.006, 0.02, 0.008), (0, 0.06, 0.018))
    k.muzzle = (0, 0.55, 0)
    k.save()


def grip(k, role, top=0.015, height=0.105, depth=0.046, angle=-16):
    k.box("grip", role, (0.03, depth, height), (0, -0.012, top - height / 2), rot=(angle, 0, 0), bevel=0.004)


def pistol():
    k = Kit("service_pistol")
    k.box("slide", "gunmetal", (0.032, 0.19, 0.034), (0, 0.065, 0.05), bevel=0.003)
    k.box("frame", "polymer", (0.03, 0.16, 0.024), (0, 0.058, 0.022), bevel=0.003)
    grip(k, "polymer_grip")
    k.box("guard", "polymer", (0.02, 0.05, 0.006), (0, 0.04, -0.008), bevel=0.002)
    k.box("trigger", "steel", (0.006, 0.008, 0.022), (0, 0.035, 0.005))
    k.cyl("barrel", "steel", 0.0065, 0.02, (0, 0.165, 0.052), verts=10)
    k.box("sight_f", "steel", (0.004, 0.006, 0.006), (0, 0.15, 0.07))
    k.box("sight_r", "steel", (0.014, 0.006, 0.006), (0, -0.02, 0.07))
    k.box("strip_l", "glow_cyan", (0.0015, 0.09, 0.004), (0.0165, 0.07, 0.044), bevel=0)
    k.box("strip_r", "glow_cyan", (0.0015, 0.09, 0.004), (-0.0165, 0.07, 0.044), bevel=0)
    k.box("light", "polymer", (0.026, 0.04, 0.02), (0, 0.115, 0.002), bevel=0.003)
    k.muzzle = (0, 0.175, 0.052)
    k.save()


def taser():
    k = Kit("taser")
    k.box("body", "polymer_yellow", (0.036, 0.13, 0.042), (0, 0.055, 0.045), bevel=0.005)
    k.box("cart", "polymer", (0.042, 0.05, 0.05), (0, 0.145, 0.045), bevel=0.004)
    grip(k, "polymer_grip", top=0.025)
    k.box("guard", "polymer", (0.02, 0.05, 0.006), (0, 0.045, 0.0), bevel=0.002)
    k.box("contact_l", "glow_cyan", (0.008, 0.004, 0.008), (0.01, 0.171, 0.052), bevel=0)
    k.box("contact_r", "glow_cyan", (0.008, 0.004, 0.008), (-0.01, 0.171, 0.052), bevel=0)
    k.box("laser", "polymer", (0.02, 0.04, 0.016), (0, 0.11, 0.016), bevel=0.003)
    k.box("display", "glow_cyan", (0.02, 0.012, 0.002), (0, -0.006, 0.067), bevel=0)
    k.muzzle = (0, 0.172, 0.05)
    k.save()


def smg():
    k = Kit("smg")
    k.box("receiver", "gunmetal", (0.044, 0.28, 0.058), (0, 0.08, 0.05), bevel=0.004)
    k.box("rail", "steel", (0.02, 0.2, 0.008), (0, 0.08, 0.083), bevel=0.001)
    k.cyl("shroud", "gunmetal", 0.016, 0.12, (0, 0.27, 0.055), verts=12)
    k.cyl("muzzle", "steel", 0.011, 0.04, (0, 0.35, 0.055), verts=10)
    grip(k, "polymer_grip", top=0.02, height=0.1)
    k.box("mag", "polymer", (0.026, 0.035, 0.15), (0, 0.075, -0.05), rot=(8, 0, 0), bevel=0.003)
    k.box("foregrip", "polymer_grip", (0.026, 0.035, 0.07), (0, 0.2, -0.008), bevel=0.004)
    for sx in (-1, 1):
        k.cyl(f"stock_rod{sx}", "steel", 0.0045, 0.2, (sx * 0.014, -0.15, 0.05), verts=8)
    k.box("butt", "polymer", (0.04, 0.02, 0.09), (0, -0.25, 0.035), bevel=0.004)
    k.box("strip", "glow_amber", (0.046, 0.08, 0.004), (0, 0.13, 0.072), bevel=0)
    k.box("sight", "steel", (0.016, 0.02, 0.02), (0, 0.0, 0.095), bevel=0.002)
    k.muzzle = (0, 0.37, 0.055)
    k.save()


def shotgun():
    k = Kit("shotgun")
    k.box("receiver", "gunmetal", (0.05, 0.26, 0.07), (0, 0.06, 0.05), bevel=0.004)
    k.cyl("barrel", "steel", 0.012, 0.52, (0, 0.45, 0.068), verts=12)
    k.cyl("tube", "gunmetal", 0.011, 0.42, (0, 0.4, 0.038), verts=12)
    k.cyl("pump", "polymer_grip", 0.02, 0.18, (0, 0.33, 0.042), verts=14)
    for i in range(5):
        k.torus(f"rib{i}", "polymer", 0.0205, 0.003, (0, 0.26 + i * 0.035, 0.042), axis="Y")
    grip(k, "polymer_grip", top=0.025, height=0.095)
    k.box("stock", "polymer", (0.042, 0.24, 0.06), (0, -0.17, 0.035), rot=(-6, 0, 0), bevel=0.006)
    k.box("pad", "rubber", (0.044, 0.02, 0.075), (0, -0.295, 0.025), bevel=0.004)
    k.box("bead", "glow_amber", (0.004, 0.006, 0.005), (0, 0.7, 0.083), bevel=0)
    k.box("shells", "brass", (0.036, 0.05, 0.016), (0.026, 0.05, 0.05), bevel=0.002)
    k.muzzle = (0, 0.71, 0.068)
    k.save()


def emp():
    k = Kit("emp")
    k.sphere("shell", "gunmetal", 0.045, (0, 0, 0), sub=2)
    k.torus("band", "glow_cyan", 0.046, 0.005, (0, 0, 0), axis="Z")
    k.cyl("cap", "steel", 0.012, 0.02, (0, 0, 0.048), axis="Z", verts=10)
    k.torus("ring", "steel", 0.014, 0.0025, (0, 0.0, 0.066), axis="X")
    k.muzzle = (0, 0, 0)
    k.save()


if __name__ == "__main__":
    for fn in (baton, pistol, taser, smg, shotgun, emp):
        reset()
        fn()
