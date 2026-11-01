"""Procedural futuristic rooms for interior-mapped windows (headless Blender 5.2).

Two modes (run by tools/interiors/interiors.py):

    blender -b --factory-startup --python tools/interiors/rooms.py -- build  <out_dir> [room ...]
        builds each room, writes <out_dir>/meshes/<room>.glb (one mesh, Smart UV
        unwrapped, every furniture piece its own part) and <room>.json (the
        role of every part's bounding box, the decals to project, the lights)
        for the Pigment texturing step.

    blender -b --factory-startup --python tools/interiors/rooms.py -- render <out_dir> [room ...] [--samples N] [--res W]
        rebuilds the room, swaps its geometry for the glb textured by Pigment
        (<out_dir>/<room>/), and renders the pre-projected interior image from
        the canonical camera: <out_dir>/renders/<room>_lit.png, _off.png and
        _depth.png (16-bit, 0 = window plane .. 1 = back wall).

Room space (Blender, metres): the window plane is y = 0, the room goes into +y
to the back wall at y = D, x runs -W/2..W/2 (right as seen from outside), the
floor is z = 0 and the ceiling z = H. The canonical camera stands E metres in
front of the window (y = -E) at mid height, looking +y, with its frustum through
the front rectangle (see crates/core/src/interior.rs). glTF export maps
(x, y, z) -> (x, z, -y): the room then lies at glTF z <= 0, as Pigment's
pack_interiors expects.
"""
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

BULB_GAIN = 3.0       # bare bulbs / pendants light a whole room at night
LIT_GAIN = 2.5        # switchable lights are authored in watts, then scaled up for a night-time window
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
STORY = "assets/decals/story/"
PROPS = "assets/decals/props/"
DEC = "assets/decals/"


# ------------------------------------------------------------------ roles (Pigment fills, see interiors.py)
def paint(rgb, rough=0.7, metal=0.0, **kw):
    d = {"color": list(rgb), "rough": rough, "metal": metal}
    d.update(kw)
    return d


WOOD = paint((0.32, 0.2, 0.11), 0.55, grain=True)
DARK_WOOD = paint((0.12, 0.07, 0.04), 0.45, grain=True)
STEEL = paint((0.55, 0.56, 0.58), 0.35, 0.9)
GUNMETAL = paint((0.12, 0.13, 0.14), 0.4, 0.8)
BLACK = paint((0.02, 0.02, 0.022), 0.5)
WHITE = paint((0.75, 0.75, 0.73), 0.45)
PLASTIC_GREY = paint((0.32, 0.33, 0.34), 0.5)
CHROME = paint((0.8, 0.8, 0.82), 0.12, 1.0)
CONCRETE = paint((0.3, 0.29, 0.27), 0.9, concrete=True)
TATAMI = paint((0.42, 0.38, 0.22), 0.85, tiles=True)
CARDBOARD = paint((0.42, 0.3, 0.17), 0.9)
FABRIC = lambda rgb: paint(rgb, 0.95, fabric=True)  # noqa: E731
SKIN_DARK = paint((0.08, 0.07, 0.07), 0.8)          # people read as silhouettes
PLANT = paint((0.07, 0.2, 0.05), 0.7, leaves=True)
SOIL = paint((0.06, 0.04, 0.03), 0.95)


def glow(rgb, strength=4.0):
    """Self-lit surface (neon, LEDs, screens without an image, grow lights)."""
    return {"color": list(rgb), "rough": 0.3, "metal": 0.0, "emit": list(rgb), "strength": strength}


# ------------------------------------------------------------------ the builder
class Room:
    def __init__(self, name, W=4.0, H=3.0, D=4.5, seed=1, eye=None):
        self.name, self.W, self.H, self.D = name, W, H, D
        self.E = eye or D
        self.bm = bmesh.new()
        self.parts = []      # {min, max, role} in Blender coords
        self.decals = []     # {image, position, normal, size, emissive, tint}
        self.lights = []     # {type, loc, rot, color, power, size, state}
        self.lamps = []      # emissive light fittings: {kind, c, s, color, strength, state}
        self.rng = random.Random(seed)
        self.tags = []
        self.grade = {}

    # -- primitives (every call is one part)
    def _add(self, geom_verts, role):
        lo = Vector((min(v.co.x for v in geom_verts), min(v.co.y for v in geom_verts), min(v.co.z for v in geom_verts)))
        hi = Vector((max(v.co.x for v in geom_verts), max(v.co.y for v in geom_verts), max(v.co.z for v in geom_verts)))
        self.parts.append({"min": list(lo), "max": list(hi), "role": role})

    def box(self, c, s, role, rz=0.0, rx=0.0):
        """Axis box centred at c with size s, rotated rz (deg) about z then rx about x."""
        M = Matrix.Translation(Vector(c)) @ Matrix.Rotation(math.radians(rz), 4, "Z") @ Matrix.Rotation(math.radians(rx), 4, "X") @ Matrix.Diagonal((*s, 1.0))
        r = bmesh.ops.create_cube(self.bm, size=1.0, matrix=M)
        self._add(r["verts"], role)

    def cyl(self, c, r, h, role, seg=16, axis="Z", r2=None):
        rot = {"Z": Matrix.Identity(4), "X": Matrix.Rotation(math.radians(90), 4, "Y"), "Y": Matrix.Rotation(math.radians(90), 4, "X")}[axis]
        M = Matrix.Translation(Vector(c)) @ rot
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=h, matrix=M)
        self._add(res["verts"], role)

    def ball(self, c, r, role, scale=(1, 1, 1)):
        M = Matrix.Translation(Vector(c)) @ Matrix.Diagonal((*scale, 1.0))
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=14, v_segments=8, radius=r, matrix=M)
        self._add(res["verts"], role)

    # -- room shell: five slabs just outside the room (inner faces are the room)
    def shell(self, wall, floor, ceiling, back=None, left=None, right=None):
        W, H, D, t = self.W, self.H, self.D, 0.1
        self.box((0, D / 2, -t / 2), (W + 2 * t, D, t), floor)
        self.box((0, D / 2, H + t / 2), (W + 2 * t, D, t), ceiling)
        self.box((0, D + t / 2, H / 2), (W + 2 * t, t, H + 2 * t), back or wall)
        self.box((-W / 2 - t / 2, D / 2, H / 2), (t, D, H), left or wall)
        self.box((W / 2 + t / 2, D / 2, H / 2), (t, D, H), right or wall)

    # -- decals (projected by Pigment)
    def decal(self, image, pos, normal, size, emissive=0.0, tint=(1, 1, 1), opacity=1.0):
        self.decals.append({"image": image, "position": list(pos), "normal": list(normal), "size": list(size),
                            "emissive": emissive, "tint": list(tint), "opacity": opacity})

    def poster(self, image, wall, u, z, w, h=None, emissive=0.0):
        """A paper poster on a wall: 'back' (u = x), 'left' / 'right' (u = y)."""
        h = h or w * 1.4
        W, D = self.W, self.D
        if wall == "back":
            self.decal(image, (u, D - 0.002, z), (0, -1, 0), (w, h), emissive)
        elif wall == "left":
            self.decal(image, (-W / 2 + 0.002, u, z), (1, 0, 0), (w, h), emissive)
        else:
            self.decal(image, (W / 2 - 0.002, u, z), (-1, 0, 0), (w, h), emissive)

    def screen(self, c, w, h, normal, image=None, color=(0.4, 0.6, 1.0), strength=5.0, bezel=0.03, depth=0.04):
        """A flat screen: a dark bezel box and an emissive face (an image decal or a plain glow)."""
        n = Vector(normal)
        rz = math.degrees(math.atan2(-n.x, n.y)) if abs(n.z) < 0.5 else 0.0
        self.box(c, (w + 2 * bezel, depth, h + 2 * bezel), BLACK, rz=rz)
        face = Vector(c) + n * (depth / 2 + 0.006)
        self.box(tuple(face), (w, 0.01, h), glow(color, strength) if image is None else glow((0.02, 0.02, 0.03), 0.0), rz=rz)
        if image:
            self.decal(image, tuple(face + n * 0.006), tuple(n), (w, h), emissive=strength)

    # -- light fittings and lights
    def lamp_panel(self, c, s, color=(1.0, 0.95, 0.88), power=120.0, state="lit", strength=8.0):
        """Ceiling panel: an emissive slab (Blender material, switchable) plus an area light under it."""
        self.lamps.append({"kind": "box", "c": list(c), "s": list(s), "color": list(color), "strength": strength, "state": state})
        self.lights.append({"type": "AREA", "loc": [c[0], c[1], c[2] - s[2] / 2 - 0.01], "rot": [0, 0, 0], "color": list(color),
                            "power": power, "size": [s[0], s[1]], "state": state})

    def bulb(self, c, color=(1.0, 0.62, 0.32), power=40.0, r=0.05, state="lit", cord=True, shade=None):
        if cord:
            top = self.H
            self.cyl((c[0], c[1], (c[2] + top) / 2 + r), 0.006, top - c[2] - r, BLACK, seg=6)
        if shade:
            self.cyl((c[0], c[1], c[2] + r * 0.6), shade[0], shade[1], shade[2], seg=20, r2=shade[0] * 0.35)
        self.lamps.append({"kind": "ball", "c": list(c), "s": [r, r, r], "color": list(color), "strength": 30.0, "state": state})
        self.lights.append({"type": "POINT", "loc": list(c), "rot": [0, 0, 0], "color": list(color), "power": power, "size": [r * 2, 0], "state": state})

    def light(self, loc, color, power, kind="POINT", size=0.2, rot=(0, 0, 0), state="lit"):
        self.lights.append({"type": kind, "loc": list(loc), "rot": list(rot), "color": list(color), "power": power,
                            "size": [size, size] if not isinstance(size, (list, tuple)) else list(size), "state": state})

    def neon(self, pts, color, r=0.012, strength=6.0, light_power=8.0):
        """A neon tube along a polyline (always on), with a weak coloured light at its middle."""
        for a, b in zip(pts, pts[1:]):
            a, b = Vector(a), Vector(b)
            d = b - a
            L = d.length
            if L < 1e-4:
                continue
            q = d.normalized().to_track_quat("Z", "Y")
            M = Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4()
            res = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=8, radius1=r, radius2=r, depth=L, matrix=M)
            self._add(res["verts"], glow(color, strength))
        mid = Vector(pts[len(pts) // 2])
        if light_power:
            self.light(tuple(mid), color, light_power, state="always")

    # -- furniture
    def table(self, c, s, top=WOOD, legs=GUNMETAL, h=0.75):
        x, y = c[0], c[1]
        self.box((x, y, h - 0.02), (s[0], s[1], 0.04), top)
        for dx in (-1, 1):
            for dy in (-1, 1):
                self.box((x + dx * (s[0] / 2 - 0.05), y + dy * (s[1] / 2 - 0.05), (h - 0.04) / 2), (0.04, 0.04, h - 0.04), legs)

    def chair(self, c, rz=0.0, col=BLACK, office=False):
        x, y = c[0], c[1]
        if office:
            self.cyl((x, y, 0.22), 0.025, 0.4, CHROME, seg=8)
            self.cyl((x, y, 0.03), 0.28, 0.04, BLACK, seg=5)
            self.box((x, y, 0.47), (0.48, 0.46, 0.08), col, rz=rz)
            off = Vector((0, 0.22, 0))
            off.rotate(Matrix.Rotation(math.radians(rz), 3, "Z"))
            self.box((x + off.x, y + off.y, 0.8), (0.46, 0.06, 0.6), col, rz=rz)
            return
        self.box((x, y, 0.45), (0.42, 0.42, 0.04), col, rz=rz)
        for dx in (-1, 1):
            for dy in (-1, 1):
                self.box((x + dx * 0.18, y + dy * 0.18, 0.22), (0.03, 0.03, 0.44), GUNMETAL, rz=rz)
        off = Vector((0, 0.2, 0))
        off.rotate(Matrix.Rotation(math.radians(rz), 3, "Z"))
        self.box((x + off.x, y + off.y, 0.7), (0.42, 0.03, 0.5), col, rz=rz)

    def stool(self, c, top=paint((0.6, 0.08, 0.06), 0.4)):
        self.cyl((c[0], c[1], 0.35), 0.025, 0.7, CHROME, seg=8)
        self.cyl((c[0], c[1], 0.71), 0.17, 0.06, top, seg=16)
        self.cyl((c[0], c[1], 0.02), 0.2, 0.03, CHROME, seg=12)

    def sofa(self, c, w, rz=0.0, col=FABRIC((0.25, 0.08, 0.12)), d=0.85):
        R = Matrix.Rotation(math.radians(rz), 3, "Z")

        def at(dx, dy, z):
            v = Vector((dx, dy, 0))
            v.rotate(R)
            return (c[0] + v.x, c[1] + v.y, z)
        self.box(at(0, 0, 0.22), (w, d, 0.44), col, rz=rz)
        self.box(at(0, d / 2 - 0.1, 0.62), (w, 0.2, 0.5), col, rz=rz)
        self.box(at(-w / 2 + 0.1, 0, 0.55), (0.2, d, 0.3), col, rz=rz)
        self.box(at(w / 2 - 0.1, 0, 0.55), (0.2, d, 0.3), col, rz=rz)

    def bed(self, c, s=(1.4, 2.0), rz=0.0, sheet=FABRIC((0.55, 0.55, 0.6)), frame=DARK_WOOD, h=0.45):
        self.box((c[0], c[1], h / 2 - 0.1), (s[0], s[1], h - 0.2), frame, rz=rz)
        self.box((c[0], c[1], h - 0.05), (s[0] - 0.06, s[1] - 0.06, 0.2), sheet, rz=rz)
        R = Matrix.Rotation(math.radians(rz), 3, "Z")
        v = Vector((0, s[1] / 2 - 0.3, 0))
        v.rotate(R)
        self.box((c[0] + v.x, c[1] + v.y, h + 0.1), (s[0] * 0.7, 0.35, 0.12), WHITE, rz=rz)

    def shelf(self, c, w, h, d=0.35, n=4, col=GUNMETAL, rz=0.0, items=None):
        R = Matrix.Rotation(math.radians(rz), 3, "Z")

        def at(dx, dy, z):
            v = Vector((dx, dy, 0))
            v.rotate(R)
            return (c[0] + v.x, c[1] + v.y, z)
        for sx in (-1, 1):
            self.box(at(sx * w / 2, 0, h / 2), (0.03, d, h), col, rz=rz)
        for k in range(n):
            z = 0.1 + k * (h - 0.15) / max(1, n - 1)
            self.box(at(0, 0, z), (w, d, 0.025), col, rz=rz)
            if items and k < n - 1:
                x = -w / 2 + 0.08
                while x < w / 2 - 0.12:
                    iw = self.rng.uniform(0.08, 0.22)
                    ih = self.rng.uniform(0.1, min(0.32, (h - 0.15) / max(1, n - 1) - 0.05))
                    if x + iw > w / 2 - 0.05:
                        break
                    self.box(at(x + iw / 2, self.rng.uniform(-0.05, 0.05), z + 0.0125 + ih / 2), (iw, d * 0.7, ih), self.rng.choice(items), rz=rz)
                    x += iw + self.rng.uniform(0.01, 0.06)

    def boxes(self, c, n=6, spread=0.8, rz=0.0):
        for k in range(n):
            s = (self.rng.uniform(0.35, 0.6), self.rng.uniform(0.3, 0.5), self.rng.uniform(0.25, 0.45))
            x = c[0] + self.rng.uniform(-spread, spread)
            y = c[1] + self.rng.uniform(-spread * 0.6, spread * 0.6)
            # stack on whatever is below (crudely: by count)
            z = s[2] / 2 + (0.4 if k >= n // 2 else 0.0)
            self.box((x, y, z), s, CARDBOARD, rz=rz + self.rng.uniform(-20, 20))

    def plant(self, c, h=1.0, pot=paint((0.15, 0.15, 0.16), 0.6), r=0.18):
        self.cyl((c[0], c[1], 0.18), r, 0.36, pot, seg=12, r2=r * 0.8)
        self.cyl((c[0], c[1], 0.37), r * 0.9, 0.02, SOIL, seg=12)
        for k in range(5):
            a = k * 1.3 + self.rng.uniform(0, 0.6)
            off = Vector((math.cos(a), math.sin(a), 0)) * r * 0.6
            self.ball((c[0] + off.x, c[1] + off.y, 0.38 + h * self.rng.uniform(0.35, 0.75)), r * self.rng.uniform(0.8, 1.4), PLANT, scale=(1, 1, 1.6))

    def person(self, c, rz=0.0, pose="stand", col=FABRIC((0.06, 0.06, 0.08))):
        """A simple human figure (reads as a silhouette through a window)."""
        x, y, z0 = c[0], c[1], c[2] if len(c) > 2 else 0.0
        R = Matrix.Rotation(math.radians(rz), 3, "Z")

        def at(dx, dy, z):
            v = Vector((dx, dy, 0))
            v.rotate(R)
            return (x + v.x, y + v.y, z0 + z)
        if pose == "stand":
            for sx in (-1, 1):
                self.box(at(sx * 0.1, 0, 0.45), (0.13, 0.15, 0.9), col, rz=rz)
                self.box(at(sx * 0.26, 0, 1.15), (0.09, 0.1, 0.6), col, rz=rz)
            self.box(at(0, 0, 1.2), (0.42, 0.22, 0.62), col, rz=rz)
            self.cyl(at(0, 0, 1.55), 0.05, 0.1, SKIN_DARK, seg=8)
            self.ball(at(0, 0, 1.69), 0.11, SKIN_DARK, scale=(0.9, 1.0, 1.15))
        elif pose == "sit":
            for sx in (-1, 1):
                self.box(at(sx * 0.1, -0.2, 0.5), (0.14, 0.45, 0.14), col, rz=rz)
                self.box(at(sx * 0.1, -0.42, 0.25), (0.12, 0.12, 0.5), col, rz=rz)
                self.box(at(sx * 0.25, -0.12, 0.85), (0.09, 0.32, 0.1), col, rz=rz)
            self.box(at(0, 0.02, 0.85), (0.42, 0.22, 0.6), col, rz=rz)
            self.ball(at(0, -0.02, 1.32), 0.11, SKIN_DARK, scale=(0.9, 1.0, 1.15))
        else:  # lie on the back along +y, head at +y
            self.box(at(0, -0.45, 0.1), (0.3, 0.9, 0.16), col, rz=rz)
            self.box(at(0, 0.25, 0.13), (0.42, 0.6, 0.22), col, rz=rz)
            self.ball(at(0, 0.7, 0.16), 0.11, SKIN_DARK, scale=(0.9, 1.15, 1.0))

    def monitor(self, c, w=0.55, h=0.32, rz=0.0, image=None, color=(0.5, 0.7, 1.0), strength=4.0, stand=True):
        n = Vector((0, -1, 0))
        n.rotate(Matrix.Rotation(math.radians(rz), 3, "Z"))
        if stand:
            self.box((c[0], c[1], c[2] - h / 2 - 0.08), (0.05, 0.05, 0.16), GUNMETAL, rz=rz)
            self.box((c[0], c[1], c[2] - h / 2 - 0.165), (0.22, 0.16, 0.01), GUNMETAL, rz=rz)
        self.screen(c, w, h, tuple(n), image=image, color=color, strength=strength, bezel=0.015, depth=0.03)

    def desk_station(self, c, rz=0.0, image=None, color=(0.5, 0.75, 1.0), person=False, chair_col=BLACK, n_mon=1):
        R = Matrix.Rotation(math.radians(rz), 3, "Z")

        def at(dx, dy, z):
            v = Vector((dx, dy, 0))
            v.rotate(R)
            return (c[0] + v.x, c[1] + v.y, z)
        self.box(at(0, 0, 0.73), (1.4, 0.7, 0.04), WHITE, rz=rz)
        for sx in (-1, 1):
            self.box(at(sx * 0.66, 0, 0.36), (0.04, 0.66, 0.72), PLASTIC_GREY, rz=rz)
        for k in range(n_mon):
            dx = (k - (n_mon - 1) / 2) * 0.6
            im = image[k % len(image)] if isinstance(image, list) else image
            self.monitor(at(dx, 0.15, 1.03), rz=rz + (k - (n_mon - 1) / 2) * -12, image=im, color=color)
        self.box(at(0, -0.12, 0.76), (0.45, 0.15, 0.02), BLACK, rz=rz)
        if person:
            self.person(at(0, -0.55, 0), rz=rz, pose="sit")
        else:
            self.chair(at(0, -0.55, 0), rz=rz, office=True, col=chair_col)

    def rack(self, c, h=2.1, rz=0.0, led=(0.2, 1.0, 0.5)):
        self.box((c[0], c[1], h / 2), (0.6, 1.0, h), BLACK, rz=rz)
        n = Vector((0, -1, 0))
        n.rotate(Matrix.Rotation(math.radians(rz), 3, "Z"))
        face = Vector(c) + n * 0.505
        for k in range(10):
            z = 0.2 + k * (h - 0.35) / 9
            col = led if self.rng.random() > 0.2 else (1.0, 0.45, 0.1)
            w = self.rng.uniform(0.15, 0.45)
            self.box((face.x, face.y, z), (w, 0.01, 0.02), glow(col, 6.0), rz=rz)


# ------------------------------------------------------------------ the rooms
ROOMS = {}


def room(name, tags, W=4.0, H=3.0, D=4.5, grade=None):
    def deco(fn):
        ROOMS[name] = {"fn": fn, "tags": tags, "W": W, "H": H, "D": D, "grade": grade or {}}
        return fn
    return deco


@room("capsule_hotel", ["capsule", "upper", "warm"], D=4.0)
def capsule_hotel(r):
    r.shell(paint((0.75, 0.74, 0.7), 0.6), paint((0.2, 0.2, 0.22), 0.4), WHITE)
    W, D = r.W, r.D
    # two rows of capsule pods along the back wall, openings towards the window
    for row in range(2):
        z0 = 0.15 + row * 1.25
        for k in range(3):
            x = -1.3 + k * 1.3
            y = D - 1.05
            shell = paint((0.85, 0.84, 0.8), 0.35)
            r.box((x, y, z0 + 0.55), (1.2, 2.0, 0.08), shell)
            r.box((x, y, z0 - 0.0), (1.2, 2.0, 0.08), shell)
            r.box((x - 0.58, y, z0 + 0.28), (0.06, 2.0, 0.6), shell)
            r.box((x + 0.58, y, z0 + 0.28), (0.06, 2.0, 0.6), shell)
            r.box((x, y + 0.98, z0 + 0.28), (1.2, 0.06, 0.6), shell)
            lit = r.rng.random() < 0.75
            col = r.rng.choice([(1.0, 0.7, 0.45), (0.6, 0.8, 1.0), (1.0, 0.5, 0.8)])
            if lit:
                r.box((x, y + 0.6, z0 + 0.5), (0.9, 0.5, 0.02), glow(col, 5.0))
                r.light((x, y, z0 + 0.35), col, 15.0, state="always")
            r.box((x, y + 0.2, z0 + 0.1), (1.0, 1.6, 0.12), FABRIC((0.8, 0.8, 0.82)))
            if r.rng.random() < 0.5:   # privacy blind half down
                r.box((x, y - 0.98, z0 + 0.45), (1.1, 0.02, 0.22), FABRIC((0.15, 0.2, 0.35)))
            r.box((x + 0.45, y - 1.0, z0 + 0.5), (0.12, 0.02, 0.06), glow((0.3, 1.0, 0.5), 5.0))
    # ladder, corridor lockers
    for z in (0.3, 0.7, 1.1, 1.5):
        r.box((-1.95 + 0.1, D - 2.1, z), (0.3, 0.03, 0.03), CHROME)
    for k in range(4):
        r.box((W / 2 - 0.2, 0.5 + k * 0.42, 0.9), (0.38, 0.4, 1.8), paint((0.3, 0.32, 0.35), 0.45, 0.6))
    r.box((W / 2 - 0.4, 1.0, 1.85), (0.01, 0.4, 0.2), glow((0.2, 0.9, 1.0), 3.0))
    r.decal(PROPS + "arrow_capsules.png", (W / 2 - 0.42, 1.0, 1.85), (-1, 0, 0), (0.6, 0.2), emissive=3.0)
    r.lamp_panel((0, 1.2, r.H - 0.02), (1.2, 0.3, 0.04), (0.9, 0.95, 1.0), 60)


@room("apartment_holo", ["apartment", "upper", "screen"], D=4.5)
def apartment_holo(r):
    r.shell(paint((0.28, 0.25, 0.24), 0.8), WOOD, paint((0.5, 0.5, 0.48)), back=paint((0.18, 0.2, 0.24), 0.8))
    W, D = r.W, r.D
    # holo-TV on the left wall, sofa facing it
    r.screen((-W / 2 + 0.05, 2.4, 1.45), 1.9, 1.05, (1, 0, 0), image=STORY + "billboard_meridian.png", strength=6.0)
    r.light((-W / 2 + 0.6, 2.4, 1.45), (0.4, 0.55, 1.0), 60, kind="AREA", size=[1.6, 0.9], rot=(0, -90, 0), state="always")
    r.sofa((0.9, 2.5, 0), 2.0, rz=-90, col=FABRIC((0.3, 0.09, 0.12)))
    r.box((-0.2, 2.5, 0.2), (0.7, 1.0, 0.4), DARK_WOOD)
    r.box((-0.25, 2.3, 0.45), (0.12, 0.08, 0.1), WHITE)
    r.box((0.0, 2.7, 0.45), (0.3, 0.2, 0.06), paint((0.7, 0.1, 0.1), 0.4))
    r.shelf((1.2, D - 0.25, 0), 1.4, 1.9, items=[CARDBOARD, BLACK, paint((0.6, 0.5, 0.2)), WHITE, paint((0.1, 0.3, 0.5))])
    r.box((-1.4, D - 0.35, 0.45), (0.9, 0.6, 0.9), WHITE)                           # kitchenette
    r.box((-1.4, D - 0.35, 1.7), (0.9, 0.4, 0.6), WHITE)
    r.box((-1.4, D - 0.6, 0.92), (0.5, 0.02, 0.02), glow((1, 0.6, 0.3), 3.0))
    r.poster(STORY + "poster_unplug.png", "back", -0.3, 1.6, 0.45)
    r.poster(DEC + "poster_yume.png", "right", 1.0, 1.6, 0.5)
    r.bulb((0.4, 2.0, 2.3), (1.0, 0.6, 0.3), 25, shade=(0.18, 0.12, paint((0.8, 0.4, 0.15), 0.6)))
    r.neon([(W / 2 - 0.02, 3.5, 2.75), (W / 2 - 0.02, 0.6, 2.75)], (1.0, 0.2, 0.6), light_power=10)
    r.box((1.4, 1.0, 0.03), (1.2, 0.8, 0.02), FABRIC((0.25, 0.2, 0.3)))


@room("apartment_holo_person", ["apartment", "upper", "screen", "person"], D=4.5)
def apartment_holo_person(r):
    apartment_holo(r)
    r.person((0.4, 1.0), rz=190, pose="stand")


@room("apartment_kitchen", ["apartment", "upper", "warm"], D=4.0)
def apartment_kitchen(r):
    r.shell(paint((0.55, 0.46, 0.36), 0.8), paint((0.35, 0.3, 0.25), 0.6, tiles=True), paint((0.6, 0.58, 0.55)))
    W, D = r.W, r.D
    # counter along the back wall, fridge, rice cooker, table with two chairs
    r.box((0.3, D - 0.32, 0.45), (2.6, 0.6, 0.9), WHITE)
    r.box((0.3, D - 0.32, 0.92), (2.6, 0.62, 0.04), paint((0.15, 0.15, 0.15), 0.3))
    r.box((0.6, D - 0.3, 0.95), (0.5, 0.4, 0.02), STEEL)
    r.box((-0.5, D - 0.35, 1.0), (0.25, 0.25, 0.2), WHITE)
    r.box((0.3, D - 0.2, 1.85), (2.6, 0.35, 0.65), WHITE)
    r.box((0.3, D - 0.4, 1.5), (2.4, 0.02, 0.02), glow((1.0, 0.85, 0.6), 4.0))
    r.box((-1.55, D - 0.4, 0.95), (0.7, 0.65, 1.9), STEEL)
    r.box((-1.55, D - 0.75, 1.3), (0.15, 0.01, 0.1), glow((0.3, 0.7, 1.0), 4.0))
    r.table((0.2, 1.8, 0), (1.0, 0.8))
    r.chair((-0.4, 1.8), rz=90, col=DARK_WOOD)
    r.chair((0.8, 1.8), rz=-90, col=DARK_WOOD)
    r.box((0.1, 1.75, 0.78), (0.18, 0.18, 0.06), WHITE)
    r.box((1.5, 0.9, 0.5), (0.6, 0.4, 1.0), DARK_WOOD)
    r.poster(STORY + "poster_missing_aiko.png", "right", 2.5, 1.5, 0.35)
    r.poster(DEC + "neon_noodles_24h.png", "left", 1.2, 2.2, 0.8, 0.3)
    r.bulb((0.2, 1.8, 1.9), (1.0, 0.65, 0.35), 60, shade=(0.3, 0.18, paint((0.9, 0.85, 0.7), 0.6)))
    r.plant((1.6, D - 0.9), 0.8)


@room("dreamlink_lease", ["dreamlink", "upper", "blue", "clinic"], D=5.5, grade={"saturation": 1.1})
def dreamlink_lease(r):
    r.shell(paint((0.12, 0.14, 0.2), 0.4), paint((0.08, 0.09, 0.12), 0.2), paint((0.1, 0.11, 0.15)))
    W, D = r.W, r.D
    # rows of lease beds, sleepers wired to the ceiling, blue light
    for k, x in enumerate((-1.1, 1.1)):
        for j, y in enumerate((1.6, 3.8)):
            r.box((x, y, 0.3), (0.85, 2.0, 0.6), WHITE)
            r.box((x, y, 0.62), (0.8, 1.95, 0.06), FABRIC((0.2, 0.3, 0.5)))
            r.person((x, y, 0.62), rz=0, pose="lie", col=FABRIC((0.75, 0.78, 0.85)))
            # head rig: glowing ring + cable bundle to the ceiling
            r.cyl((x, y + 0.72, 0.85), 0.16, 0.05, glow((0.2, 0.55, 1.0), 8.0), seg=20, axis="Y")
            r.cyl((x, y + 0.72, (0.85 + r.H) / 2 + 0.05), 0.02, r.H - 0.9, BLACK, seg=6)
            r.box((x + 0.55, y + 0.7, 1.2), (0.05, 0.05, 1.2), CHROME)
            r.monitor((x + 0.55, y + 0.5, 1.6), 0.35, 0.25, rz=-90 if x > 0 else 90, color=(0.3, 0.6, 1.0), strength=5.0, stand=False)
            r.box((x, y - 1.02, 0.95), (0.7, 0.02, 0.06), glow((0.25, 0.6, 1.0), 6.0))
    r.screen((0, D - 0.05, 2.0), 1.6, 0.9, (0, -1, 0), image=STORY + "billboard_dreamlink.png", strength=6.0)
    r.neon([(-W / 2 + 0.02, 0.3, 0.05), (-W / 2 + 0.02, D - 0.1, 0.05)], (0.2, 0.5, 1.0), strength=8.0, light_power=20)
    r.neon([(W / 2 - 0.02, 0.3, 0.05), (W / 2 - 0.02, D - 0.1, 0.05)], (0.2, 0.5, 1.0), strength=8.0, light_power=20)
    r.lamp_panel((0, 2.7, r.H - 0.02), (0.4, 3.5, 0.04), (0.35, 0.55, 1.0), 120)
    r.poster(PROPS + "ad_dreamlink.png", "left", 2.7, 1.7, 0.6, 0.85, emissive=1.0)


@room("noctis_clinic", ["clinic", "upper", "violet"], D=4.5)
def noctis_clinic(r):
    r.shell(paint((0.7, 0.7, 0.74), 0.35), paint((0.6, 0.6, 0.62), 0.15, tiles=True), WHITE)
    W, D = r.W, r.D
    # reclined chair with a memory crown, waveform monitors, a cabinet of memory vials
    r.box((0.0, 2.4, 0.35), (0.7, 1.1, 0.2), CHROME)
    r.box((0.0, 2.3, 0.55), (0.65, 1.0, 0.18), FABRIC((0.35, 0.12, 0.45)))
    r.box((0.0, 3.0, 0.85), (0.65, 0.18, 0.75), FABRIC((0.35, 0.12, 0.45)), rx=-25)
    r.cyl((0.0, 2.4, 0.2), 0.12, 0.4, CHROME, seg=10)
    r.person((0.0, 2.1, 0.62), pose="lie", col=FABRIC((0.7, 0.72, 0.75)))
    r.cyl((0.0, 3.15, 1.35), 0.2, 0.12, glow((0.75, 0.3, 1.0), 8.0), seg=24)
    r.box((0.0, 3.35, 2.15), (0.08, 0.08, 1.5), STEEL)
    r.box((0.0, 3.25, 1.45), (0.3, 0.3, 0.06), STEEL)
    r.monitor((1.3, 2.9, 1.5), 0.7, 0.42, rz=-60, image=STORY + "billboard_noctis.png", strength=5.0)
    r.monitor((1.3, 2.0, 1.3), 0.5, 0.3, rz=-80, color=(0.8, 0.4, 1.0), strength=5.0)
    r.box((1.3, 2.4, 0.45), (0.5, 0.6, 0.9), WHITE)
    for k in range(4):
        for j in range(5):
            r.cyl((-1.75 + j * 0.18, D - 0.25, 1.15 + k * 0.32), 0.05, 0.2, glow(r.rng.choice([(0.8, 0.3, 1.0), (0.3, 0.8, 1.0), (1.0, 0.5, 0.2)]), 4.0), seg=10)
    r.shelf((-1.4, D - 0.22, 0), 0.95, 2.4, d=0.35, n=6, col=CHROME)
    r.lamp_panel((0, 2.3, r.H - 0.02), (1.2, 0.6, 0.04), (0.92, 0.9, 1.0), 160)
    r.poster(STORY + "plate_observed.png", "right", 3.6, 1.6, 0.4, 0.2)
    r.decal(STORY + "sign_dreams.png", (0.4, D - 0.003, 2.4), (0, -1, 0), (1.2, 0.45), emissive=3.0)


@room("meridian_office", ["office", "surveillance", "screen", "blue"], D=5.5, W=4.5)
def meridian_office(r):
    r.shell(paint((0.06, 0.07, 0.09), 0.5), paint((0.05, 0.05, 0.06), 0.3), paint((0.04, 0.04, 0.05)))
    W, D, H = r.W, r.D, r.H
    imgs = [STORY + "billboard_meridian.png", STORY + "billboard_score.png", PROPS + "holo_meridian.png", PROPS + "kiosk_score.png",
            PROPS + "parking_screen.png", PROPS + "kiosk_flagged.png", PROPS + "ped_count.png"]
    # a wall of screens on the back wall
    cols, rows = 6, 4
    sw, sh = (W - 0.4) / cols - 0.06, (H - 0.6) / rows - 0.06
    for i in range(cols):
        for j in range(rows):
            x = -W / 2 + 0.2 + (i + 0.5) * (W - 0.4) / cols
            z = 0.45 + (j + 0.5) * (H - 0.6) / rows
            img = r.rng.choice(imgs) if r.rng.random() < 0.8 else None
            r.screen((x, D - 0.06, z), sw, sh, (0, -1, 0), image=img, color=r.rng.choice([(0.3, 0.5, 1.0), (0.9, 0.2, 0.2), (0.3, 0.9, 1.0)]), strength=5.0, bezel=0.02)
    r.light((0, D - 0.8, 1.6), (0.35, 0.5, 1.0), 120, kind="AREA", size=[W - 0.4, H - 0.6], rot=(-90, 0, 0), state="always")
    # operators at a curved console row
    for k, x in enumerate((-1.4, 0.0, 1.4)):
        r.desk_station((x, 3.0, 0), rz=180, image=[STORY + "billboard_score.png", PROPS + "kiosk_flagged.png"], person=k != 1, n_mon=2)
    r.desk_station((-0.8, 1.2, 0), rz=180, image=[PROPS + "holo_meridian.png"], person=True, n_mon=2)
    r.neon([(-W / 2 + 0.02, 0.2, H - 0.05), (-W / 2 + 0.02, D - 0.1, H - 0.05)], (0.9, 0.1, 0.15), light_power=6)
    r.decal(STORY + "stencil_eye_crossed.png", (W / 2 - 0.003, 1.2, 1.7), (-1, 0, 0), (0.7, 0.7), tint=(0.15, 0.15, 0.2))


@room("hoshikawa_office", ["office", "corporate", "plants", "warm"], D=6.0, W=4.5)
def hoshikawa_office(r):
    r.shell(paint((0.62, 0.6, 0.56), 0.5), paint((0.22, 0.2, 0.18), 0.25, tiles=True), paint((0.8, 0.8, 0.78)),
            back=glow((0.02, 0.03, 0.06), 0.0))
    W, D, H = r.W, r.D, r.H
    # back wall: a city-view window (a night skyline, Pigment window grid on a dark panel)
    r.box((0, D - 0.04, H / 2), (W - 0.2, 0.02, H - 0.3), {"color": [0.01, 0.015, 0.03], "rough": 0.1, "metal": 0.0, "city": True})
    for x in (-W / 4, 0.0, W / 4):
        r.box((x, D - 0.08, H / 2), (0.06, 0.06, H), GUNMETAL)
    # desks with plants, glass partition, logo wall
    for x, y in ((-1.2, 2.2), (1.2, 2.2), (-1.2, 4.0), (1.2, 4.0)):
        r.desk_station((x, y, 0), rz=180, image=[DEC + "logo_hoshikawa_dynamics.png"] if r.rng.random() < 0.5 else None, color=(0.85, 0.9, 1.0), person=r.rng.random() < 0.3)
    for p in ((-W / 2 + 0.35, 1.0), (W / 2 - 0.35, 3.1), (-W / 2 + 0.35, 4.9), (0.0, 5.3)):
        r.plant(p, 1.3, r=0.22)
    r.box((-W / 2 + 0.9, 3.1, 0.55), (1.4, 0.02, 1.1), {"color": [0.6, 0.7, 0.72], "rough": 0.05, "metal": 0.0})
    r.decal(DEC + "logo_hoshikawa_dynamics.png", (W / 2 - 0.003, 1.6, 1.9), (-1, 0, 0), (1.2, 0.5), emissive=2.0)
    for y in (1.5, 3.1, 4.7):
        r.lamp_panel((0, y, H - 0.02), (2.6, 0.25, 0.04), (1.0, 0.92, 0.8), 140)


@room("office_cubicles", ["office", "tower", "fluorescent"], D=6.0, W=4.5)
def office_cubicles(r):
    r.shell(paint((0.55, 0.56, 0.55), 0.6), paint((0.25, 0.26, 0.28), 0.9, carpet=True), paint((0.72, 0.72, 0.7)))
    W, D, H = r.W, r.D, r.H
    for x in (-1.2, 1.2):
        for y in (1.6, 3.4, 5.1):
            r.box((x, y + 0.4, 0.6), (1.6, 0.05, 1.2), FABRIC((0.3, 0.33, 0.38)))
            r.box((x + 0.78 * (1 if x < 0 else -1), y, 0.6), (0.05, 0.8, 1.2), FABRIC((0.3, 0.33, 0.38)))
            r.desk_station((x, y, 0), rz=180, color=r.rng.choice([(0.8, 0.9, 1.0), (0.5, 0.7, 1.0)]), person=r.rng.random() < 0.2)
    for y in (1.2, 2.6, 4.0, 5.4):
        for x in (-1.2, 1.2):
            r.lamp_panel((x, y, H - 0.02), (1.2, 0.3, 0.04), (0.9, 0.97, 1.0), 70)
    r.box((W / 2 - 0.3, D - 0.4, 0.9), (0.5, 0.6, 1.8), GUNMETAL)
    r.box((W / 2 - 0.3, D - 0.72, 1.4), (0.3, 0.02, 0.3), glow((0.4, 0.9, 1.0), 4.0))
    r.poster(STORY + "billboard_jobs.png", "left", 3.0, 1.8, 1.0, 0.55)


@room("server_room", ["server", "tower", "green"], D=6.0, W=4.5)
def server_room(r):
    r.shell(paint((0.2, 0.22, 0.24), 0.6), paint((0.28, 0.3, 0.3), 0.5, tiles=True), paint((0.18, 0.18, 0.2)))
    W, D, H = r.W, r.D, r.H
    for x, rz in ((-1.3, 90), (1.3, -90)):
        for k in range(5):
            r.rack((x, 0.9 + k * 1.05, 0), h=2.1, rz=rz, led=(0.2, 1.0, 0.5) if x < 0 else (0.2, 0.7, 1.0))
    r.box((0, D / 2, H - 0.25), (0.4, D - 0.4, 0.15), GUNMETAL)
    r.box((0, D / 2, H - 0.33), (0.05, D - 0.4, 0.02), glow((0.2, 1.0, 0.6), 5.0))
    for y in (1.0, 2.6, 4.2):
        r.lamp_panel((0, y, H - 0.42), (0.3, 1.0, 0.03), (0.8, 1.0, 0.95), 40)
    r.box((0, D - 0.3, 1.0), (1.2, 0.5, 2.0), BLACK)
    r.box((0, D - 0.56, 1.5), (0.9, 0.02, 0.5), glow((0.2, 1.0, 0.5), 4.0))
    r.decal(PROPS + "stencil_noctis_bio.png", (0, D - 0.003, 2.4), (0, -1, 0), (0.6, 0.3), tint=(0.8, 0.8, 0.8))
    r.light((0, D / 2, 0.2), (0.2, 1.0, 0.6), 30, state="always")


@room("ramen_kitchen", ["shop", "ground", "food", "warm"], D=4.5)
def ramen_kitchen(r):
    r.shell(paint((0.45, 0.32, 0.2), 0.8), paint((0.18, 0.15, 0.12), 0.4, tiles=True), DARK_WOOD, back=paint((0.6, 0.6, 0.58), 0.3, tiles=True))
    W, D, H = r.W, r.D, r.H
    # counter with stools facing the window side, kitchen behind
    r.box((0, 2.2, 0.5), (W - 0.6, 0.6, 1.0), DARK_WOOD)
    r.box((0, 2.2, 1.03), (W - 0.5, 0.7, 0.05), WOOD)
    for x in (-1.3, -0.45, 0.45, 1.3):
        r.stool((x, 1.5))
        if r.rng.random() < 0.5:
            r.person((x, 1.45, 0.0), rz=0, pose="sit", col=FABRIC(r.rng.choice([(0.1, 0.1, 0.12), (0.3, 0.1, 0.1), (0.1, 0.15, 0.25)])))
        r.cyl((x, 2.2, 1.1), 0.09, 0.08, WHITE, seg=14)
    for x in (-1.2, -0.2, 0.8):
        r.cyl((x, D - 0.5, 1.05), 0.22, 0.4, STEEL, seg=18)
        r.cyl((x, D - 0.5, 0.45), 0.3, 0.9, GUNMETAL, seg=18)
    r.box((0, D - 0.5, 0.45), (W - 0.4, 0.8, 0.9), STEEL)
    r.box((0, D - 0.3, 2.2), (W - 0.4, 0.5, 0.5), STEEL)
    r.decal(PROPS + "ramen_menu.png", (-0.9, D - 0.003, 1.7), (0, -1, 0), (1.2, 0.5))
    r.decal(DEC + "neon_ramen.png", (1.0, D - 0.003, 1.75), (0, -1, 0), (1.0, 0.45), emissive=5.0)
    r.decal(PROPS + "noren_ramen.png", (0, 2.6, 2.3), (0, -1, 0), (2.4, 0.5))
    r.box((0, 2.62, 2.3), (2.6, 0.01, 0.55), FABRIC((0.6, 0.12, 0.08)))
    for x in (-1.4, 0.0, 1.4):
        r.bulb((x, 2.0, 2.1), (1.0, 0.45, 0.2), 30, r=0.12, cord=True, shade=(0.17, 0.35, paint((0.85, 0.15, 0.08), 0.6)))
    r.lamp_panel((0, D - 0.6, H - 0.02), (2.5, 0.3, 0.04), (1.0, 0.9, 0.75), 90)


@room("pachinko_parlour", ["shop", "ground", "garish"], D=5.0)
def pachinko_parlour(r):
    r.shell(paint((0.3, 0.05, 0.1), 0.5), paint((0.4, 0.1, 0.15), 0.9, carpet=True), paint((0.9, 0.75, 0.3), 0.3, 0.6))
    W, D, H = r.W, r.D, r.H
    for row, y in enumerate((1.6, 3.6)):
        for k in range(5):
            x = -1.6 + k * 0.8
            r.box((x, y + 0.25, 0.95), (0.72, 0.35, 1.9), paint((0.75, 0.7, 0.6), 0.25, 0.7))
            col = [(1.0, 0.3, 0.6), (0.3, 0.9, 1.0), (1.0, 0.8, 0.2), (0.5, 1.0, 0.3)][(k + row) % 4]
            r.box((x, y + 0.06, 1.2), (0.6, 0.02, 0.75), glow(col, 6.0))
            r.box((x, y + 0.06, 1.75), (0.6, 0.02, 0.18), glow((1.0, 0.95, 0.8), 7.0))
            r.box((x, y - 0.05, 0.75), (0.55, 0.2, 0.08), CHROME)
            r.stool((x, y - 0.45), top=paint((0.1, 0.1, 0.1), 0.5))
            if r.rng.random() < 0.35:
                r.person((x, y - 0.5, 0.0), pose="sit", col=FABRIC((0.15, 0.15, 0.2)))
    for y in (0.8, 2.6, 4.4):
        r.lamp_panel((0, y, H - 0.02), (3.4, 0.2, 0.04), (1.0, 0.85, 0.6), 80)
    r.decal(STORY + "blade_pachinko.png", (0, D - 0.003, 2.4), (0, -1, 0), (2.0, 0.6), emissive=5.0)
    r.neon([(-W / 2 + 0.03, 0.2, 2.8), (-W / 2 + 0.03, D - 0.2, 2.8)], (1.0, 0.2, 0.7), light_power=15)
    r.neon([(W / 2 - 0.03, 0.2, 2.8), (W / 2 - 0.03, D - 0.2, 2.8)], (0.2, 0.9, 1.0), light_power=15)


@room("implant_clinic", ["clinic", "ground", "shop", "green"], D=4.5)
def implant_clinic(r):
    r.shell(paint((0.5, 0.56, 0.55), 0.4), paint((0.3, 0.33, 0.33), 0.2, tiles=True), WHITE)
    W, D, H = r.W, r.D, r.H
    r.box((0.2, 2.6, 0.5), (0.75, 1.9, 0.12), paint((0.12, 0.14, 0.14), 0.4))
    r.cyl((0.2, 2.6, 0.22), 0.1, 0.44, CHROME, seg=10)
    r.person((0.2, 2.4, 0.56), pose="lie", col=FABRIC((0.15, 0.18, 0.2)))
    # robot arm over the table
    r.box((1.3, 2.6, 1.3), (0.2, 0.2, 2.6), STEEL)
    r.box((0.8, 2.6, 2.1), (1.0, 0.14, 0.14), STEEL, rz=0)
    r.box((0.35, 2.6, 1.7), (0.1, 0.1, 0.7), STEEL)
    r.cyl((0.35, 2.6, 1.3), 0.05, 0.15, glow((0.3, 1.0, 0.6), 8.0), seg=10)
    r.bulb((0.2, 2.6, 2.4), (0.85, 1.0, 0.95), 120, r=0.25, cord=False, shade=(0.4, 0.08, CHROME))
    # cabinet of implants in glowing jars
    for k in range(3):
        for j in range(6):
            r.cyl((-1.75 + j * 0.15, D - 0.2, 0.9 + k * 0.45), 0.055, 0.25, glow(r.rng.choice([(0.3, 1.0, 0.6), (0.3, 0.8, 1.0), (1.0, 0.3, 0.3)]), 5.0), seg=10)
    r.shelf((-1.38, D - 0.2, 0), 1.0, 2.2, d=0.3, n=5, col=CHROME)
    r.monitor((-1.0, 1.7, 1.4), 0.7, 0.45, rz=60, image=STORY + "sign_implant_repair.png", strength=4.0)
    r.decal(STORY + "sign_implant_repair.png", (0.5, D - 0.003, 2.3), (0, -1, 0), (1.4, 0.5), emissive=4.0)
    r.lamp_panel((-0.5, 1.2, H - 0.02), (1.0, 0.5, 0.04), (0.85, 1.0, 0.95), 100)
    r.poster(STORY + "graffiti_who_owns.png", "left", 3.2, 1.2, 0.8, 0.5)


@room("neon_bedroom", ["apartment", "upper", "pink"], D=4.0)
def neon_bedroom(r):
    r.shell(paint((0.12, 0.08, 0.16), 0.8), WOOD, paint((0.15, 0.12, 0.18)))
    W, D, H = r.W, r.D, r.H
    r.bed((0.5, D - 1.15), s=(1.6, 2.1), sheet=FABRIC((0.35, 0.1, 0.4)))
    r.decal(DEC + "neon_dennou.png", (0.5, D - 0.003, 1.8), (0, -1, 0), (1.4, 0.6), emissive=7.0)
    r.light((0.5, D - 0.4, 1.8), (1.0, 0.25, 0.75), 40, kind="AREA", size=[1.2, 0.5], rot=(-90, 0, 0), state="always")
    r.neon([(-W / 2 + 0.02, 0.4, 0.15), (-W / 2 + 0.02, D - 0.2, 0.15)], (0.6, 0.2, 1.0), light_power=10)
    r.box((-1.4, D - 0.3, 0.4), (0.7, 0.5, 0.8), DARK_WOOD)
    r.bulb((-1.4, D - 0.3, 0.95), (1.0, 0.4, 0.8), 15, r=0.08, cord=False)
    r.box((-1.2, 1.4, 0.04), (1.0, 1.2, 0.02), FABRIC((0.1, 0.05, 0.15)))
    for k in range(4):
        r.box((-1.7 + k * 0.05, 1.0, 0.3 + k * 0.05), (0.5, 0.35, 0.06), FABRIC(r.rng.choice([(0.6, 0.6, 0.6), (0.1, 0.1, 0.1), (0.4, 0.1, 0.2)])), rz=r.rng.uniform(-30, 30))
    r.poster(DEC + "poster_yume.png", "right", 2.4, 1.6, 0.5)
    r.poster(STORY + "graffiti_not_data.png", "left", 2.5, 1.7, 0.9, 0.55)
    r.screen((W / 2 - 0.05, 1.2, 1.4), 0.9, 0.5, (-1, 0, 0), image=PROPS + "holo_noctis.png", strength=4.0)


@room("evicted_room", ["empty", "upper", "dark"], D=4.5, grade={"saturation": 0.7})
def evicted_room(r):
    r.shell(paint((0.3, 0.29, 0.26), 0.9, peeling=True), CONCRETE, paint((0.35, 0.34, 0.32), 0.9))
    W, D, H = r.W, r.D, r.H
    r.boxes((-1.0, D - 1.0), n=8, spread=0.7)
    r.boxes((1.2, 1.6), n=4, spread=0.4)
    r.box((0.6, D - 0.9, 0.1), (1.0, 1.9, 0.2), FABRIC((0.4, 0.38, 0.3)), rz=8)
    r.box((-1.6, 1.0, 0.4), (0.5, 0.5, 0.8), CARDBOARD, rz=12)
    r.bulb((0.0, 2.2, 2.4), (1.0, 0.75, 0.5), 25, r=0.05)
    r.decal(STORY + "plate_property.png", (0.0, D - 0.003, 1.6), (0, -1, 0), (0.6, 0.3))
    r.decal(STORY + "graffiti_unplug.png", (W / 2 - 0.003, 2.4, 1.3), (-1, 0, 0), (1.4, 0.8), tint=(0.8, 0.8, 0.8))
    r.decal(STORY + "poster_missing_ren.png", (-W / 2 + 0.003, 2.8, 1.5), (1, 0, 0), (0.35, 0.5))
    r.light((0, 0.1, 2.0), (0.4, 0.5, 0.9), 15, kind="AREA", size=[3.0, 2.0], rot=(90, 0, 0), state="always")


@room("gym", ["gym", "upper", "fluorescent"], D=5.0)
def gym(r):
    r.shell(paint((0.3, 0.32, 0.34), 0.6), paint((0.08, 0.08, 0.09), 0.85, rubber=True), paint((0.25, 0.25, 0.27)),
            back={"color": [0.75, 0.78, 0.8], "rough": 0.03, "metal": 1.0})
    W, D, H = r.W, r.D, r.H
    for x in (-1.3, 0.0, 1.3):
        r.box((x, 1.4, 0.15), (0.75, 1.7, 0.2), BLACK)
        r.box((x, 1.4, 0.26), (0.55, 1.5, 0.02), paint((0.05, 0.05, 0.05), 0.9))
        r.box((x - 0.3, 0.75, 0.7), (0.05, 0.05, 1.1), STEEL)
        r.box((x + 0.3, 0.75, 0.7), (0.05, 0.05, 1.1), STEEL)
        r.box((x, 0.72, 1.3), (0.65, 0.1, 0.25), BLACK)
        r.box((x, 0.67, 1.32), (0.4, 0.01, 0.15), glow((0.3, 1.0, 0.7), 4.0))
        if r.rng.random() < 0.4:
            r.person((x, 1.6, 0.27), rz=180, pose="stand", col=FABRIC((0.12, 0.12, 0.14)))
    r.box((0, 3.6, 0.5), (2.4, 0.5, 0.05), STEEL)
    for k in range(8):
        r.cyl((-1.05 + k * 0.3, 3.6, 0.62), 0.08 + 0.01 * k, 0.12, BLACK, seg=14, axis="Y")
    r.box((1.6, 3.4, 1.1), (0.08, 0.08, 2.2), STEEL)
    r.box((-1.6, 3.4, 1.1), (0.08, 0.08, 2.2), STEEL)
    r.box((0, 3.4, 2.15), (3.3, 0.08, 0.08), STEEL)
    for y in (1.0, 2.5, 4.0):
        r.lamp_panel((0, y, H - 0.02), (2.8, 0.2, 0.04), (0.9, 0.97, 1.0), 90)
    r.poster(STORY + "billboard_score.png", "left", 2.8, 1.8, 1.2, 0.65, emissive=1.5)
    r.neon([(W / 2 - 0.02, 0.3, 2.6), (W / 2 - 0.02, D - 0.3, 2.6)], (0.2, 1.0, 0.6), light_power=8)


@room("karaoke_box", ["karaoke", "ground", "pink"], D=4.0)
def karaoke_box(r):
    r.shell(paint((0.1, 0.05, 0.15), 0.5), paint((0.15, 0.05, 0.2), 0.9, carpet=True), paint((0.1, 0.06, 0.14)))
    W, D, H = r.W, r.D, r.H
    r.screen((0, D - 0.06, 1.6), 2.0, 1.12, (0, -1, 0), image=STORY + "sign_karaoke.png", strength=6.0)
    r.light((0, D - 0.6, 1.6), (0.9, 0.4, 1.0), 50, kind="AREA", size=[1.8, 1.0], rot=(-90, 0, 0), state="always")
    r.sofa((-1.6, 2.0, 0), 2.6, rz=-90, col=FABRIC((0.5, 0.06, 0.25)))
    r.sofa((1.6, 2.0, 0), 2.6, rz=90, col=FABRIC((0.5, 0.06, 0.25)))
    r.table((0, 2.0, 0), (0.9, 1.6), top=paint((0.05, 0.05, 0.06), 0.1), h=0.45)
    for k in range(6):
        r.cyl((r.rng.uniform(-0.3, 0.3), r.rng.uniform(1.4, 2.6), 0.53), 0.04, 0.16, glow(r.rng.choice([(1.0, 0.7, 0.2), (0.3, 1.0, 0.8)]), 2.5), seg=10)
    r.ball((0, 2.0, H - 0.35), 0.18, CHROME)
    for k, col in enumerate([(1.0, 0.2, 0.6), (0.2, 0.6, 1.0), (0.9, 1.0, 0.2)]):
        a = k * 2.1
        r.light((math.cos(a) * 1.2, 2.0 + math.sin(a) * 1.0, 2.2), col, 25, kind="SPOT", rot=(180 + 30 * math.cos(a), 30 * math.sin(a), 0), size=0.05)
    for k in range(3):
        if r.rng.random() < 0.6:
            r.person((-1.5, 1.4 + k * 0.6, 0.0), rz=-90, pose="sit", col=FABRIC((0.2, 0.2, 0.25)))
    r.neon([(-W / 2 + 0.02, 0.1, 2.9), (-W / 2 + 0.02, D - 0.1, 2.9), (W / 2 - 0.02, D - 0.1, 2.9), (W / 2 - 0.02, 0.1, 2.9)], (1.0, 0.2, 0.8), light_power=20)


@room("hydroponics", ["hydro", "upper", "tower", "pink"], D=5.5, grade={"saturation": 1.05})
def hydroponics(r):
    r.shell(paint((0.75, 0.75, 0.75), 0.4), paint((0.2, 0.22, 0.22), 0.3), WHITE)
    W, D, H = r.W, r.D, r.H
    for x in (-1.2, 1.2):
        for k in range(4):
            z = 0.35 + k * 0.62
            r.box((x, D / 2 + 0.2, z), (1.1, D - 1.2, 0.05), STEEL)
            r.box((x, D / 2 + 0.2, z + 0.05), (1.0, D - 1.3, 0.06), paint((0.08, 0.1, 0.12), 0.3))
            for j in range(int((D - 1.4) / 0.28)):
                y = 0.75 + j * 0.28
                r.ball((x + r.rng.uniform(-0.3, 0.3), y, z + 0.17), r.rng.uniform(0.09, 0.14), PLANT, scale=(1, 1, 0.8))
                r.ball((x + r.rng.uniform(-0.3, 0.3), y + 0.1, z + 0.15), r.rng.uniform(0.07, 0.11), PLANT, scale=(1, 1, 0.8))
            r.box((x, D / 2 + 0.2, z + 0.55), (0.9, D - 1.3, 0.03), glow((1.0, 0.25, 0.85), 7.0))
        r.light((x, D / 2, 1.5), (1.0, 0.3, 0.85), 90, kind="AREA", size=[0.9, D - 1.4], rot=(0, 0, 0), state="always")
    for k in range(5):
        r.cyl((0, 0.8 + k * 1.0, 0.03), 0.04, 0.06, CHROME, seg=8)
    r.box((0, D - 0.3, 0.8), (1.0, 0.5, 1.6), STEEL)
    r.box((0, D - 0.56, 1.2), (0.6, 0.02, 0.3), glow((0.3, 1.0, 0.5), 4.0))
    r.lamp_panel((0, 1.0, H - 0.02), (1.0, 0.3, 0.04), (0.95, 1.0, 0.95), 40)


@room("konbini", ["shop", "ground", "fluorescent"], D=5.0)
def konbini(r):
    r.shell(paint((0.85, 0.85, 0.83), 0.4), paint((0.7, 0.7, 0.68), 0.15, tiles=True), WHITE)
    W, D, H = r.W, r.D, r.H
    goods = [paint(c, 0.4) for c in ((0.8, 0.1, 0.1), (0.1, 0.4, 0.8), (0.9, 0.7, 0.1), (0.2, 0.6, 0.2), (0.9, 0.9, 0.9), (0.95, 0.4, 0.1))]
    for x in (-0.7, 0.7):
        r.shelf((x, 2.8, 0), 0.5, 1.6, d=1.6, n=5, col=WHITE, rz=90, items=goods)
    for k in range(4):
        x = -1.5 + k * 1.0
        r.box((x, D - 0.4, 1.05), (0.95, 0.7, 2.1), WHITE)
        r.box((x, D - 0.76, 1.1), (0.85, 0.02, 1.7), glow((0.85, 0.95, 1.0), 3.0))
        for j in range(5):
            r.box((x + r.rng.uniform(-0.3, 0.3), D - 0.6, 0.4 + j * 0.35), (0.25, 0.15, 0.22), r.rng.choice(goods))
    r.box((1.5, 1.0, 0.5), (0.8, 1.4, 1.0), WHITE)
    r.box((1.5, 1.0, 1.15), (0.3, 0.3, 0.25), BLACK)
    r.box((1.36, 1.0, 1.2), (0.01, 0.25, 0.15), glow((0.3, 1.0, 0.6), 4.0))
    r.decal(DEC + "vending_products.png", (-W / 2 + 0.003, 1.2, 1.6), (1, 0, 0), (1.2, 0.6), emissive=0.5)
    for y in (1.0, 2.5, 4.0):
        for x in (-1.0, 1.0):
            r.lamp_panel((x, y, H - 0.02), (1.2, 0.2, 0.04), (0.95, 1.0, 1.0), 80)
    if r.rng.random() < 0.8:
        r.person((1.5, 1.5, 0), rz=180, pose="stand", col=FABRIC((0.1, 0.3, 0.5)))


@room("memory_pawn", ["shop", "ground", "screen", "violet"], D=4.5)
def memory_pawn(r):
    r.shell(paint((0.15, 0.12, 0.14), 0.6), paint((0.12, 0.1, 0.1), 0.3, tiles=True), paint((0.1, 0.09, 0.1)))
    W, D, H = r.W, r.D, r.H
    # glass display counters of memory chips, a back wall of price screens, a cage
    for x in (-1.0, 1.0):
        r.box((x, 2.2, 0.45), (1.6, 0.6, 0.9), BLACK)
        r.box((x, 2.2, 0.92), (1.6, 0.6, 0.04), {"color": [0.5, 0.6, 0.62], "rough": 0.05, "metal": 0.0})
        for j in range(8):
            r.box((x - 0.7 + j * 0.2, 2.2, 0.82), (0.08, 0.04, 0.12), glow(r.rng.choice([(0.8, 0.3, 1.0), (0.3, 0.9, 1.0)]), 4.0))
        r.box((x, 2.2, 0.75), (1.5, 0.5, 0.02), glow((0.7, 0.5, 1.0), 2.0))
    imgs = [STORY + "sign_memory_pawn.png", PROPS + "kiosk_score.png", STORY + "billboard_noctis.png", PROPS + "holo_hacked.png"]
    for k in range(4):
        r.screen((-1.5 + k * 1.0, D - 0.06, 1.9), 0.85, 0.5, (0, -1, 0), image=imgs[k], strength=5.0)
    r.box((0, D - 1.0, 1.5), (W - 0.2, 0.03, 3.0), {"color": [0.3, 0.3, 0.32], "rough": 0.4, "metal": 0.9, "mesh": True})
    if r.rng.random() < 0.7:
        r.person((0.6, D - 1.6, 0), rz=180, pose="stand", col=FABRIC((0.08, 0.08, 0.1)))
    r.bulb((-1.0, 2.2, 2.0), (0.8, 0.4, 1.0), 25, r=0.08, shade=(0.25, 0.1, BLACK))
    r.bulb((1.0, 2.2, 2.0), (0.8, 0.4, 1.0), 25, r=0.08, shade=(0.25, 0.1, BLACK))
    r.decal(STORY + "sign_memory_pawn.png", (W / 2 - 0.003, 1.6, 2.2), (-1, 0, 0), (1.4, 0.5), emissive=4.0)
    r.poster(STORY + "poster_missing_mika.png", "left", 1.4, 1.5, 0.35)


@room("unplug_hideout", ["resistance", "upper", "red"], D=4.0, grade={"contrast": 1.08})
def unplug_hideout(r):
    r.shell(paint((0.35, 0.3, 0.26), 0.9, peeling=True), CONCRETE, paint((0.3, 0.28, 0.26), 0.9))
    W, D, H = r.W, r.D, r.H
    r.table((0, 2.2, 0), (1.8, 0.9), top=WOOD)
    for k in range(5):
        r.box((r.rng.uniform(-0.7, 0.7), r.rng.uniform(1.9, 2.5), 0.76), (0.3, 0.21, 0.004), WHITE, rz=r.rng.uniform(-40, 40))
    for x in (-0.6, 0.6):
        r.box((x, 2.4, 0.95), (0.4, 0.35, 0.35), paint((0.6, 0.58, 0.5), 0.6))
        r.box((x, 2.22, 0.97), (0.3, 0.01, 0.24), glow((0.3, 1.0, 0.4), 3.0))
    r.chair((-0.3, 1.5), rz=0)
    r.person((0.5, 1.6, 0), rz=200, pose="sit", col=FABRIC((0.12, 0.1, 0.1)))
    r.poster(STORY + "poster_unplug.png", "back", -1.2, 1.7, 0.6)
    r.poster(STORY + "graffiti_unplug.png", "back", 0.6, 1.9, 1.6, 0.9)
    r.poster(STORY + "poster_missing_aiko.png", "back", 1.6, 1.4, 0.35)
    r.poster(STORY + "poster_missing_ren.png", "back", 1.6, 2.0, 0.35)
    r.poster(STORY + "graffiti_who_owns.png", "left", 2.0, 1.6, 1.2, 0.7)
    r.poster(STORY + "stencil_eye_crossed.png", "right", 2.6, 1.8, 0.6, 0.6)
    r.boxes((1.4, 3.3), n=5, spread=0.4)
    r.bulb((0, 2.2, 1.9), (1.0, 0.25, 0.15), 50, r=0.06, shade=(0.22, 0.14, GUNMETAL))
    r.light((0, 3.0, 2.6), (1.0, 0.2, 0.1), 30, state="always")


@room("bar_counter", ["shop", "ground", "warm", "bar"], D=4.5)
def bar_counter(r):
    r.shell(paint((0.12, 0.08, 0.06), 0.7), DARK_WOOD, paint((0.08, 0.06, 0.05)), back=paint((0.15, 0.1, 0.08), 0.5))
    W, D, H = r.W, r.D, r.H
    r.box((0, D - 1.3, 0.55), (W - 0.6, 0.55, 1.1), DARK_WOOD)
    r.box((0, D - 1.3, 1.12), (W - 0.5, 0.65, 0.05), paint((0.04, 0.03, 0.02), 0.15))
    r.box((0, D - 1.0, 1.05), (W - 0.6, 0.02, 0.02), glow((1.0, 0.6, 0.2), 6.0))
    for k in range(3):
        z = 1.2 + k * 0.42
        r.box((0, D - 0.15, z), (W - 0.6, 0.25, 0.03), {"color": [0.6, 0.65, 0.7], "rough": 0.05, "metal": 0.0})
        for j in range(14):
            x = -1.6 + j * 0.24 + r.rng.uniform(-0.05, 0.05)
            r.cyl((x, D - 0.15, z + 0.15), 0.04, 0.28, glow(r.rng.choice([(0.6, 0.3, 0.05), (0.2, 0.5, 0.2), (0.7, 0.6, 0.4), (0.3, 0.1, 0.4)]), 1.2), seg=10)
        r.box((0, D - 0.04, z + 0.1), (W - 0.6, 0.01, 0.02), glow((1.0, 0.55, 0.2), 6.0))
    for x in (-1.4, -0.5, 0.4, 1.3):
        r.stool((x, D - 1.9), top=paint((0.1, 0.1, 0.1), 0.5))
    r.person((-0.5, D - 1.95, 0), rz=0, pose="sit", col=FABRIC((0.25, 0.1, 0.1)))
    r.person((0.8, D - 0.7, 0), rz=180, pose="stand", col=FABRIC((0.05, 0.05, 0.05)))
    r.decal(DEC + "neon_bar.png", (-W / 2 + 0.003, 2.2, 2.0), (1, 0, 0), (1.2, 0.6), emissive=6.0)
    r.decal(DEC + "neon_open.png", (W / 2 - 0.003, 1.4, 2.0), (-1, 0, 0), (0.9, 0.45), emissive=6.0)
    for x in (-1.2, 0.0, 1.2):
        r.bulb((x, D - 1.3, 2.0), (1.0, 0.55, 0.25), 30, r=0.05, shade=(0.14, 0.2, CHROME))


ORDER = list(ROOMS)


# ------------------------------------------------------------------ Blender plumbing
def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def to_gltf(v):
    return [v[0], v[2], -v[1]]


def build(name, out):
    spec = ROOMS[name]
    r = Room(name, spec["W"], spec["H"], spec["D"], seed=sum(map(ord, name)))
    spec["fn"](r)
    clear()
    me = bpy.data.meshes.new(name)
    r.bm.to_mesh(me)
    r.bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    me.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, scale_to_bounds=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    os.makedirs(os.path.join(out, "meshes"), exist_ok=True)
    glb = os.path.join(out, "meshes", f"{name}.glb")
    bpy.ops.export_scene.gltf(filepath=glb, use_selection=True, export_format="GLB", export_yup=True,
                              export_materials="NONE", export_normals=True, export_texcoords=True, export_apply=True)
    side = {
        "name": name, "size": [r.W, r.H, r.D], "eye": r.E, "tags": spec["tags"], "grade": spec["grade"],
        # parts and decals in glTF coordinates (what Pigment sees)
        "parts": [{"min": [min(a, b) for a, b in zip(to_gltf(p["min"]), to_gltf(p["max"]))],
                   "max": [max(a, b) for a, b in zip(to_gltf(p["min"]), to_gltf(p["max"]))], "role": p["role"]} for p in r.parts],
        "decals": [dict(d, position=to_gltf(d["position"]), normal=to_gltf(d["normal"])) for d in r.decals],
        "lights": r.lights, "lamps": r.lamps,
    }
    with open(os.path.join(out, "meshes", f"{name}.json"), "w") as f:
        json.dump(side, f, indent=1)
    print(f"[rooms] built {name}: {len(r.parts)} parts, {len(r.decals)} decals, {len(r.lights)} lights")


def _emission_mat(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def _depth_override(D):
    """Emission = depth into the room (Blender y / D): the depth pass."""
    m = bpy.data.materials.new("depth_pass")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.use_clamp = True
    nt.links.new(sep.outputs["Y"], div.inputs[0])
    div.inputs[1].default_value = D
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(div.outputs[0], em.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def render(name, out, samples=128, res=768):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from blender_pigment import apply_pigment_material
    side = json.load(open(os.path.join(out, "meshes", f"{name}.json")))
    W, H, D = side["size"]
    E = side["eye"]
    clear()
    sc = bpy.context.scene
    bpy.ops.import_scene.gltf(filepath=os.path.join(out, "meshes", f"{name}.glb"))
    ob = next(o for o in sc.objects if o.type == "MESH")
    folder = os.path.join(out, name)
    apply_pigment_material(ob, folder, name)
    # light fittings (switchable) and lights
    lamp_objs, light_objs = [], []
    for k, l in enumerate(side["lamps"]):
        if l["kind"] == "box":
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=l["c"])
            o = bpy.context.active_object
            o.scale = l["s"]
        else:
            bpy.ops.mesh.primitive_uv_sphere_add(radius=l["s"][0], location=l["c"], segments=16, ring_count=8)
            o = bpy.context.active_object
        o.data.materials.append(_emission_mat(f"lamp{k}", l["color"], l["strength"]))
        o["state"] = l["state"]
        o.visible_shadow = False          # the light inside a bulb / under a panel must get out
        lamp_objs.append(o)
    for k, l in enumerate(side["lights"]):
        ld = bpy.data.lights.new(f"L{k}", l["type"])
        ld.color = l["color"]
        # lights that switch with the room carry most of the lit look
        ld.energy = l["power"] * (LIT_GAIN if l["state"] == "lit" else 1.0) * (BULB_GAIN if l["type"] == "POINT" and l["state"] == "lit" else 1.0)
        if l["type"] == "AREA":
            ld.shape = "RECTANGLE"
            ld.size, ld.size_y = l["size"][0], l["size"][1]
        elif l["type"] == "SPOT":
            ld.spot_size = math.radians(40)
            ld.shadow_soft_size = l["size"][0]
        else:
            ld.shadow_soft_size = max(0.02, l["size"][0])
        lo = bpy.data.objects.new(f"L{k}", ld)
        lo.location = l["loc"]
        # area lights point down -z by default: rot is extra (deg)
        lo.rotation_euler = [math.radians(a) for a in l["rot"]]
        lo["state"] = l["state"]
        sc.collection.objects.link(lo)
        light_objs.append(lo)
    # city glow through the window (always): a weak cool area light just outside, facing in
    ld = bpy.data.lights.new("city", "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = W, H
    ld.color = (0.45, 0.55, 1.0)
    ld.energy = 6.0
    lo = bpy.data.objects.new("city", ld)
    lo.location = (0, -0.05, H / 2)
    lo.rotation_euler = (math.radians(90), 0, 0)
    lo["state"] = "always"
    lo.visible_camera = False
    sc.collection.objects.link(lo)
    light_objs.append(lo)
    # the canonical camera
    cd = bpy.data.cameras.new("cam")
    cd.sensor_fit = "HORIZONTAL"
    cd.angle = 2 * math.atan(W / 2 / E)
    cd.clip_start = 0.05
    cam = bpy.data.objects.new("cam", cd)
    cam.location = (0, -E, H / 2)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dev
            prefs.get_devices()
            for d in prefs.devices:
                d.use = d.type == dev
            sc.cycles.device = "GPU"
            break
        except Exception:
            continue
    sc.render.resolution_x = res
    sc.render.resolution_y = int(round(res * H / W))
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in [i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["look"].enum_items_static] else "None"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    rd = os.path.join(out, "renders")
    os.makedirs(rd, exist_ok=True)
    for state in ("lit", "off"):
        for o in lamp_objs + light_objs:
            on = o["state"] == "always" or state == "lit"
            o.hide_render = not on
        sc.cycles.samples = samples
        sc.view_settings.exposure = 0.0
        sc.render.filepath = os.path.join(rd, f"{name}_{state}.png")
        bpy.ops.render.render(write_still=True)
    # depth: an emission override, raw, 16 bit
    vl = sc.view_layers[0]
    vl.material_override = _depth_override(D)
    for o in lamp_objs:
        o.hide_render = False
    sc.cycles.samples = 8
    sc.cycles.use_denoising = False
    sc.view_settings.view_transform = "Raw" if "Raw" in [i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items_static] else "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.color_mode = "BW"
    sc.render.image_settings.color_depth = "16"
    sc.render.filepath = os.path.join(rd, f"{name}_depth.png")
    bpy.ops.render.render(write_still=True)
    vl.material_override = None
    print(f"[rooms] rendered {name}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    mode, out = argv[0], argv[1]
    rest = argv[2:]
    samples, res = 128, 768
    if "--samples" in rest:
        i = rest.index("--samples")
        samples = int(rest[i + 1])
        del rest[i:i + 2]
    if "--res" in rest:
        i = rest.index("--res")
        res = int(rest[i + 1])
        del rest[i:i + 2]
    names = rest or ORDER
    for n in names:
        if n not in ROOMS:
            raise SystemExit(f"unknown room {n} (one of {', '.join(ORDER)})")
        if mode == "build":
            build(n, out)
        elif mode == "render":
            render(n, out, samples, res)
        elif mode == "list":
            print(n, ROOMS[n]["tags"])


if __name__ == "__main__":
    main()
