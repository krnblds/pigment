"""Blender lightbox: a Cycles studio for product shots of any glb (vehicles, props, buildings).

Headless only:

    blender -b --factory-startup --python tools/lightbox/lightbox_scene.py -- MODE [options]

MODE
    still       one image: --asset ID|PATH [--preset front34] [--look light|dark] [--livery NAME]
    liveries    contact sheet of every livery of one vehicle (--asset ID)
    fleet       livery sheet of every vehicle x every livery, the layout of
                docs/agents/fleet/fleet_variants.png (one row per vehicle, 8 cells of 480x300)
    grid        one beauty shot per asset in a grid: --assets a,b,c (default: the six vehicles)
    turntable   N frames round one asset (the asset turns, camera and lights stay) + a sheet;
                --frames 8, --anim also keyframes the turn (frames 1..N) and --blend saves the scene
    presets     one asset in every camera preset, as a sheet

Options
    --asset / --assets   vehicle id (assets/vehicles/<id>/<id>.glb), or any .glb path (props, town kit)
    --lod ""|_lod1|_lod2 vehicle LOD suffix (default LOD0)
    --preset             front34 | side | rear34 | rear | front | top | detail
    --look               light (white sweep, airy) | dark (black glossy sweep, strip lights) | both
    --livery             variant name or index (vehicles: KHR_materials_variants)
    --res WxH            image / cell size; --samples N (default 128, denoised)
    --out PATH           output png (still) or file / folder for sheets
    --labels 0|1         small labels on sheets (default 1); --width N final sheet width
    --yaw DEG            extra asset yaw for still

As a module (inside Blender):

    import sys; sys.path.insert(0, "tools/lightbox"); import lightbox_scene as LB
    LB.reset()
    a = LB.import_asset("hayate")
    st = LB.build_studio(a, look="dark")
    LB.set_livery(a, "racing")
    cam = LB.shoot_camera(a, "front34", res=(1600, 1000))
    LB.render(cam, "out.png")

Coordinates: every glb in this repo is glTF +Y up, facing +Z; Blender's importer turns that into
Z up, facing -Y. The camera always looks along +Y at the sweep; presets turn the asset, so the
seamless backdrop is behind it from every angle.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VEH = os.path.join(ROOT, "assets", "vehicles")
FLEET_ORDER = ["mame", "hayate", "tsubame", "kago", "hakobi", "kaiun"]   # fleet_variants.png row order

# asset yaw (deg, about +Z; 0 = asset faces the camera), camera elevation (deg), lens (mm), framing pad
PRESETS = {
    "front34": dict(yaw=-38.0, elev=9.0, lens=55, pad=1.10),
    "side":    dict(yaw=-90.0, elev=3.0, lens=70, pad=1.08),
    "rear34":  dict(yaw=148.0, elev=10.0, lens=55, pad=1.10),
    "rear":    dict(yaw=180.0, elev=8.0, lens=60, pad=1.12),
    "front":   dict(yaw=0.0, elev=8.0, lens=60, pad=1.12),
    "top":     dict(yaw=-90.0, elev=88.0, lens=50, pad=1.08),
    "detail":  dict(yaw=-42.0, elev=4.0, lens=90, pad=1.0, detail=True),
}


# ------------------------------------------------------------------ render setup


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    prefs = bpy.context.preferences.addons["io_scene_gltf2"].preferences
    if hasattr(prefs, "KHR_materials_variants_ui"):
        prefs.KHR_materials_variants_ui = True


def setup_render(res=(1600, 1000), samples=128):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    cp = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL"):
        try:
            cp.compute_device_type = kind
            cp.get_devices()
            dev = [d for d in cp.devices if d.type == kind]
            if not dev:
                continue
            for d in cp.devices:
                d.use = d.type == kind
            sc.cycles.device = "GPU"
            break
        except Exception:
            continue
    c = sc.cycles
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.01
    c.use_denoising = True
    try:
        c.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    c.max_bounces = 10
    c.glossy_bounces = 6
    c.transmission_bounces = 8
    c.transparent_max_bounces = 24
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.sample_clamp_indirect = 6.0
    c.blur_glossy = 0.5
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            continue
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"


# ------------------------------------------------------------------ assets


class Asset:
    def __init__(self, root, pivot, objs, vid=None, info=None, path=None):
        self.root, self.pivot, self.objs, self.vid, self.info, self.path = root, pivot, objs, vid, info, path

    @property
    def meshes(self):
        return [o for o in self.objs if o.type == "MESH" and not o.hide_render]

    def liveries(self):
        """[(index, name)] from the glb's KHR_materials_variants (or <id>.json)."""
        vs = getattr(bpy.context.scene, "gltf2_KHR_materials_variants_variants", None)
        if vs is not None and len(vs):
            return [(v.variant_idx, v.name) for v in vs]
        if self.info:
            return [(v["index"], v["name"]) for v in self.info.get("variants", [])]
        return []


def resolve(spec, lod=""):
    """'hayate' -> assets/vehicles/hayate/hayate.glb; a path is returned as is (relative to the repo)."""
    p = os.path.join(VEH, spec, f"{spec}{lod}.glb")
    if os.path.exists(p):
        return p, spec
    p = spec if os.path.isabs(spec) else os.path.join(ROOT, spec)
    if not os.path.exists(p):
        raise FileNotFoundError(spec)
    return p, None


def import_asset(spec, lod=""):
    """Import a glb under ROOT (turntable) > PIVOT (recentres) empties. The asset is centred on its
    footprint and stands on z = 0."""
    path, vid = resolve(spec, lod)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.data.objects if o not in before]
    name = vid or os.path.splitext(os.path.basename(path))[0]
    root = bpy.data.objects.new(f"LB_{name}", None)
    pivot = bpy.data.objects.new(f"LB_{name}_pivot", None)
    bpy.context.scene.collection.objects.link(root)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.parent = root
    for o in objs:
        if o.parent is None:
            o.parent = pivot
        if o.name.startswith("Collider") or (o.type == "MESH" and o.get("collider")):
            o.hide_render = True
            o.hide_set(True)
    info = None
    if vid:
        jp = os.path.join(VEH, vid, f"{vid}.json")
        if os.path.exists(jp):
            info = json.load(open(jp))
    a = Asset(root, pivot, objs, vid, info, path)
    bpy.context.view_layer.update()
    pts = points(a)
    lo, hi = pts.min(0), pts.max(0)
    pivot.location = (-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])
    bpy.context.view_layer.update()
    return a


def points(asset, local=False, max_per_obj=30000):
    """World-space vertex positions of the visible meshes (subsampled), Nx3. local=True gives them
    in the asset root's space (before the turntable yaw)."""
    out = []
    inv = asset.root.matrix_world.inverted() if local else Matrix.Identity(4)
    for o in asset.meshes:
        n = len(o.data.vertices)
        if n == 0:
            continue
        co = np.empty(n * 3, dtype=np.float32)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        if n > max_per_obj:
            co = co[:: n // max_per_obj + 1]
        m = np.array(inv @ o.matrix_world, dtype=np.float64)
        out.append(co @ m[:3, :3].T + m[:3, 3])
    return np.concatenate(out, 0)


def set_livery(asset, which):
    """Switch a vehicle livery. `which` is a variant name or index.

    Blender 5.2's glTF importer stores KHR_materials_variants as
    scene.gltf2_KHR_materials_variants_variants (names + indices) and, per mesh,
    mesh.gltf2_variant_mesh_data (slot index, material, variants that use it). We assign the
    material of every mapping that lists the wanted variant to its slot (what the importer's
    "Display Variant" button does). Fallback: a material named <id>_<variant> on Body."""
    lv = asset.liveries()
    idx = None
    if isinstance(which, int) or (isinstance(which, str) and which.isdigit()):
        idx = int(which)
    else:
        idx = next((i for i, n in lv if n == which), None)
        if idx is None:
            raise KeyError(f"{asset.vid}: no livery {which!r}; have {[n for _, n in lv]}")
    hit = False
    for o in asset.meshes + [o for o in asset.objs if o.type == "MESH"]:
        for d in getattr(o.data, "gltf2_variant_mesh_data", []):
            if any(v.variant.variant_idx == idx for v in d.variants):
                o.data.materials[d.material_slot_index] = d.material
                hit = True
    if not hit and asset.vid:
        name = dict(lv).get(idx)
        m = bpy.data.materials.get(f"{asset.vid}_{name}")
        body = next((o for o in asset.objs if o.name.startswith("Body")), None)
        if m and body:
            body.data.materials[0] = m
    return idx


# ------------------------------------------------------------------ studio

LOOKS = {
    # sweep colour / roughness / coat, world colour + strength, light gain, exposure
    "light": dict(sweep=(0.80, 0.80, 0.80), rough=0.55, coat=0.0, world=(0.95, 0.96, 1.0), world_s=0.06,
                  gain=1.0, exposure=0.0),
    "dark": dict(sweep=(0.006, 0.006, 0.007), rough=0.16, coat=0.0, world=(0.0, 0.0, 0.0), world_s=0.0,
                 gain=1.0, exposure=0.0),
}


def _mat(name, color, rough, coat=0.0, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Specular IOR Level"].default_value = spec
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.03
    return m


def cyclorama(width, front, back, radius, height, mat, nx=48, n_floor=40, n_arc=48, n_wall=24):
    """Seamless sweep: a floor from y=-front to y=back-radius, a quarter-circle cove of `radius`,
    then a wall at y=back up to `height`. Extruded along X over `width`. Smooth shaded."""
    prof = []
    y0, y1 = -front, back - radius
    for i in range(n_floor):
        t = i / n_floor
        prof.append((y0 + (y1 - y0) * (t ** 0.8), 0.0))  # denser near the cove
    for i in range(n_arc + 1):
        a = (math.pi / 2) * i / n_arc
        prof.append((y1 + radius * math.sin(a), radius - radius * math.cos(a)))
    for i in range(1, n_wall + 1):
        prof.append((back, radius + (height - radius) * i / n_wall))
    xs = [-width / 2 + width * i / nx for i in range(nx + 1)]
    verts = [(x, y, z) for (y, z) in prof for x in xs]
    faces = []
    W = len(xs)
    for j in range(len(prof) - 1):
        for i in range(W - 1):
            a = j * W + i
            faces.append((a, a + 1, a + W + 1, a + W))
    me = bpy.data.meshes.new("Cyclorama")
    me.from_pydata(verts, [], faces)
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new("Cyclorama", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def area_light(name, loc, size, aim, energy, color=(1, 1, 1), spread=180.0, camera_visible=False):
    d = bpy.data.lights.new(name, "AREA")
    d.shape = "RECTANGLE"
    d.size, d.size_y = size
    d.energy = energy
    d.color = color
    d.spread = math.radians(spread)
    o = bpy.data.objects.new(name, d)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    direction = Vector(aim) - Vector(loc)
    o.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    o.visible_camera = camera_visible
    return o


def flag(name, loc, length, height, color=(0.004, 0.004, 0.004)):
    """A black flag (negative fill): a vertical card along Y at loc, out of frame."""
    me = bpy.data.meshes.new(name)
    x, y, z = loc
    me.from_pydata([(x, y - length / 2, z), (x, y + length / 2, z), (x, y + length / 2, z + height),
                    (x, y - length / 2, z + height)], [], [(0, 1, 2, 3)])
    me.materials.append(_mat(name, color, 0.9, spec=0.0))
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    o.visible_camera = False
    return o


def exclude_from(receiver, lights):
    """Light linking: `lights` don't light (or show up in reflections on) `receiver`."""
    coll = bpy.data.collections.new(f"LB_no_{receiver.name}")
    coll.objects.link(receiver)
    try:
        co = coll.collection_objects[list(coll.objects).index(receiver)]
        co.light_linking.link_state = "EXCLUDE"
        for L in lights:
            L.light_linking.receiver_collection = coll
    except Exception as e:  # older Blender: no light linking, the lights simply also hit the sweep
        print("[lightbox] light linking unavailable:", e)


class Studio:
    def __init__(self, r, h, look):
        self.r, self.h, self.look, self.lights, self.sweep = r, h, look, [], None


def build_studio(asset_or_dims, look="light", turn_clear=True):
    """Sweep + lights + world sized to the asset. `asset_or_dims` is an Asset or (r, h): r = the
    footprint radius the asset may sweep through as it turns, h = its height."""
    if isinstance(asset_or_dims, Asset):
        p = points(asset_or_dims, local=True)
        r = float(np.sqrt(p[:, 0] ** 2 + p[:, 1] ** 2).max())
        h = float(p[:, 2].max())
    else:
        r, h = asset_or_dims
    L = LOOKS[look]
    sc = bpy.context.scene
    st = Studio(r, h, look)
    k = max(r, h * 0.8)           # light rig scale
    g = (k / 2.4) ** 2 * L["gain"]  # energy scales with area

    # world
    w = bpy.data.worlds.new(f"LB_{look}")
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (*L["world"], 1)
    bg.inputs["Strength"].default_value = L["world_s"]
    sc.world = w
    sc.view_settings.exposure = L["exposure"]

    # sweep: wall far enough behind that the asset can turn, a soft cove, very wide
    mat = _mat(f"Sweep_{look}", L["sweep"], L["rough"], L["coat"])
    back = r + max(1.2 * k, 1.5)
    st.sweep = cyclorama(width=16 * k + 10, front=10 * k + 8, back=back, radius=max(1.4 * k, 1.2),
                         height=max(6 * k, 3 * h + 2), mat=mat)

    # lights (camera at -Y looking +Y; the asset at the origin). Where a light sits decides which
    # surface shows its strip: the hood / roof mirror the high back (strip behind, above the frame),
    # the camera-side flank mirrors camera-right, the nose mirrors camera-left.
    tgt = (0, 0, h * 0.45)
    Ls = st.lights
    if look == "light":
        # big overhead softbox (contact shadow), key front-left, fill front-right, a long strip high
        # at the back for the hood / roof line, black flags left and right so the paint keeps its
        # colour and the strips read as lines instead of drowning in white
        Ls += [
            area_light("Overhead", (0, -0.1 * k, h + 1.7 * k), (2.4 * k, 1.4 * k), (0, -0.1 * k, 0), 1500 * g, spread=100),
            area_light("Key", (-2.0 * k, -1.8 * k, h + 0.8 * k), (1.6 * k, 0.8 * k), tgt, 700 * g, (1.0, 0.98, 0.95)),
            area_light("Fill", (1.9 * k, -2.2 * k, h * 0.8), (1.6 * k, 1.0 * k), tgt, 200 * g, (0.95, 0.97, 1.0)),
            area_light("HoodLine", (0, back - 0.9 * k, h + 1.3 * k), (4.5 * k, 0.22 * k), tgt, 450 * g),
            area_light("FlankLine", (2.3 * k, 0.2 * k, h * 0.75), (0.14 * k, 3.4 * k), tgt, 320 * g),
            area_light("Wash", (0, back - 2.4 * k, h + 2.6 * k), (6 * k, 1.0 * k), (0, back, h * 0.8), 700 * g, spread=90),
        ]
        flag("FlagR", (2.75 * k, 0.4 * k, 0), 3.6 * k, h * 1.6 + 0.6 * k)
        flag("FlagL", (-2.75 * k, 0.4 * k, 0), 3.6 * k, h * 1.6 + 0.6 * k)
    else:
        # car-commercial: long strip lines (hood / roof from the high back strips, flank from a long
        # strip at camera-right, nose from the key at camera-left), thin vertical rims, a soft glow
        # low on the cove behind; key, rims and flank strip skip the sweep (light linking) so the
        # black floor only mirrors the clean overhead lines
        Ls += [
            area_light("HoodLineA", (0, back - 1.0 * k, h + 1.1 * k), (4.5 * k, 0.12 * k), tgt, 520 * g),
            area_light("HoodLineB", (0, back - 0.6 * k, h + 1.8 * k), (4.5 * k, 0.12 * k), tgt, 420 * g),
            area_light("Overhead", (0, 0, h + 1.5 * k), (2.6 * k, 0.25 * k), (0, 0, 0), 260 * g, spread=80),
            area_light("Key", (-2.1 * k, -1.9 * k, h + 0.5 * k), (1.4 * k, 0.5 * k), tgt, 280 * g, (0.95, 0.97, 1.0)),
            area_light("Flank", (0, -2.8 * k, h * 0.55), (4.0 * k, 0.10 * k), (0, 0, h * 0.4), 220 * g),
            area_light("FlankLine", (2.4 * k, 0.2 * k, h * 0.7), (0.10 * k, 3.6 * k), tgt, 360 * g),
            area_light("RimL", (-2.0 * k, 1.1 * k, h * 0.85), (0.08 * k, 1.6 * k), tgt, 160 * g),
            area_light("RimR", (2.0 * k, 1.1 * k, h * 0.85), (0.08 * k, 1.6 * k), tgt, 160 * g),
            area_light("Glow", (0, back - 1.2 * k, 0.25 * k), (6 * k, 0.4 * k), (0, back + 1.0, 0.6 * k), 400 * g, spread=70),
        ]
        exclude_from(st.sweep, [o for o in Ls if o.name not in ("Overhead", "Glow")])
    return st


# ------------------------------------------------------------------ camera


def _basis(elev):
    e = math.radians(elev)
    f = np.array([0.0, math.cos(e), -math.sin(e)])
    rgt = np.array([1.0, 0.0, 0.0])
    up = np.cross(rgt, f)
    return f, rgt, up


def fit(pts, elev, lens, aspect, pad=1.1, sensor=36.0):
    """Camera position + target that frame pts (Nx3 world) exactly: looking along +Y tilted down by
    elev; the limiting pair of frustum planes touches the points (scaled by 1/pad), the other pair
    is centred. Closed form per pair: plane x/z = +-t through C  =>  C.x +- t C.z = min(t z +- x)."""
    f, rgt, up = _basis(elev)
    th = (sensor / 2) / lens        # tan half fov along the long side (sensor fit AUTO)
    tw, tv = (th, th / aspect) if aspect >= 1 else (th * aspect, th)
    tw, tv = tw / pad, tv / pad
    a, b, c = pts @ rgt, pts @ up, pts @ f
    mL, mR = (a + tw * c).min(), (tw * c - a).min()
    mB, mT = (b + tv * c).min(), (tv * c - b).min()
    cc = min((mL + mR) / (2 * tw), (mB + mT) / (2 * tv))
    ca, cb = (mL - mR) / 2, (mB - mT) / 2
    cam = rgt * ca + up * cb + f * cc
    D = float(np.median(c)) - cc
    return cam, cam + f * D, D


def make_camera(name, loc, tgt, lens, dof=None):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36
    cd.clip_start = 0.05
    cd.clip_end = 1000
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = Vector(loc)
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    if dof:
        cd.dof.use_dof = True
        cd.dof.focus_distance = (Vector(tgt) - Vector(loc)).length
        cd.dof.aperture_fstop = dof
    bpy.context.scene.camera = cam
    return cam


def turn(asset, yaw_deg):
    asset.root.rotation_euler = (0, 0, math.radians(yaw_deg))
    bpy.context.view_layer.update()


def detail_points(asset):
    """Front lower quarter (headlamp + front wheel) in root space, returned in world space."""
    p = points(asset, local=True)
    lo, hi = p.min(0), p.max(0)
    sel = (p[:, 1] < lo[1] + 0.36 * (hi[1] - lo[1])) & (p[:, 2] < lo[2] + 0.72 * (hi[2] - lo[2]))
    q = p[sel] if sel.sum() > 50 else p
    m = np.array(asset.root.matrix_world)
    return q @ m[:3, :3].T + m[:3, 3]


def shoot_camera(asset, preset="front34", res=(1600, 1000), yaw_extra=0.0, all_yaws=None, pad=None):
    """Turn the asset for the preset and frame it. all_yaws: frame the union over these yaws
    (turntables: the camera does not move between frames)."""
    P = PRESETS[preset]
    aspect = res[0] / res[1]
    if all_yaws:
        pts = []
        for y in all_yaws:
            turn(asset, y)
            pts.append(points(asset))
        pts = np.concatenate(pts, 0)
    turn(asset, P["yaw"] + yaw_extra)
    if not all_yaws:
        pts = detail_points(asset) if P.get("detail") else points(asset)
    loc, tgt, D = fit(pts, P["elev"], P["lens"], aspect, pad or P["pad"])
    return make_camera(f"Cam_{preset}", loc, tgt, P["lens"], dof=2.8 if P.get("detail") else None)


def render(cam, out):
    sc = bpy.context.scene
    sc.camera = cam
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("[lightbox]", out)
    return out


# ------------------------------------------------------------------ sheets (PIL via system python)


def system_python():
    for c in (os.environ.get("LIGHTBOX_PYTHON"), shutil.which("python"), shutil.which("python3"), shutil.which("py")):
        if c:
            return c
    raise RuntimeError("no system python with PIL for contact sheets (set LIGHTBOX_PYTHON)")


def make_sheet(rows, out, **kw):
    spec = dict(rows=rows, out=out, **kw)
    fd, sp = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(spec, fh)
    subprocess.run([system_python(), os.path.join(HERE, "sheets.py"), sp], check=True)
    os.remove(sp)
    return out


# ------------------------------------------------------------------ high-level jobs


def still(spec, out, preset="front34", look="light", livery=None, res=(1600, 1000), samples=128, lod="", yaw=0.0):
    reset()
    setup_render(res, samples)
    a = import_asset(spec, lod)
    if livery is not None:
        set_livery(a, livery)
    build_studio(a, look)
    cam = shoot_camera(a, preset, res, yaw_extra=yaw)
    return render(cam, out)


def default_livery(a):
    if a.info and a.info.get("default_variant"):
        return a.info["default_variant"]
    return None


def grid_job(specs, out, look, preset="front34", res=(960, 600), samples=128, cols=3, liveries=None,
             labels=True, width=None, lod=""):
    tmp = tempfile.mkdtemp(prefix="lightbox_")
    cells = []
    for s in specs:
        reset()
        setup_render(res, samples)
        a = import_asset(s, lod)
        lv = (liveries or {}).get(a.vid) or default_livery(a)
        if lv is not None:
            set_livery(a, lv)
        build_studio(a, look)
        cam = shoot_camera(a, preset, res)
        p = render(cam, os.path.join(tmp, f"{len(cells):02d}.png"))
        name = (a.info or {}).get("name", "") or os.path.splitext(os.path.basename(a.path))[0]
        cells.append(dict(path=p, label=name.split(",")[0] + (f"  /  {lv}" if lv else "")))
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    bg = (235, 235, 235) if look == "light" else (6, 6, 7)
    make_sheet(rows, out, cols=cols, bg=bg, gap=4 if look == "light" else 4, labels=labels, width=width,
               delete_cells=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def liveries_job(vids, out, look="dark", preset="front34", cell=(480, 300), samples=64, cols=8, labels=True,
                 width=None, lod=""):
    """One row per vehicle, one cell per livery (padded to `cols`): fleet_variants.png's layout."""
    tmp = tempfile.mkdtemp(prefix="lightbox_")
    rows = []
    for vid in vids:
        reset()
        setup_render(cell, samples)
        a = import_asset(vid, lod)
        build_studio(a, look)
        cam = shoot_camera(a, preset, cell, pad=1.06)
        row = []
        for idx, name in a.liveries():
            set_livery(a, idx)
            p = render(cam, os.path.join(tmp, f"{vid}_{idx}.png"))
            row.append(dict(path=p, label=f"{vid} / {name}"))
        rows.append(row)
    bg = (235, 235, 235) if look == "light" else (0, 0, 0)
    make_sheet(rows, out, cols=max(cols, max(len(r) for r in rows)), cell=list(cell), bg=bg, labels=labels,
               width=width, delete_cells=True, label_size=max(11, cell[1] // 20))
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def turntable_job(spec, out, look="dark", frames=8, res=(800, 500), samples=96, livery=None, anim=False,
                  blend=None, cols=4, labels=True, width=None, lod="", frames_dir=None, elev=None):
    reset()
    setup_render(res, samples)
    a = import_asset(spec, lod)
    lv = livery if livery is not None else default_livery(a)
    if lv is not None:
        set_livery(a, lv)
    build_studio(a, look)
    base = PRESETS["front34"]["yaw"]
    yaws = [base + 360.0 * i / frames for i in range(frames)]
    if elev is not None:
        PRESETS["turntable"] = dict(PRESETS["front34"], elev=elev)
    cam = shoot_camera(a, "turntable" if elev is not None else "front34", res, all_yaws=yaws, pad=1.04)
    sc = bpy.context.scene
    if anim:
        # keyframed turn, linear: frame i+1 = yaw i (renderable as an animation, or save --blend)
        sc.frame_start, sc.frame_end = 1, frames
        for i, y in enumerate(yaws):
            turn(a, y)
            a.root.keyframe_insert("rotation_euler", index=2, frame=i + 1)
        for fc in _fcurves(a.root):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    if blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(blend))
    fdir = frames_dir or tempfile.mkdtemp(prefix="lightbox_tt_")
    cells = []
    for i, y in enumerate(yaws):
        if anim:
            sc.frame_set(i + 1)
        else:
            turn(a, y)
        p = render(cam, os.path.join(fdir, f"turntable_{i + 1:03d}.png"))
        cells.append(dict(path=p, label=f"{round((y - base) % 360):d}°"))
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    bg = (235, 235, 235) if look == "light" else (6, 6, 7)
    make_sheet(rows, out, cols=cols, bg=bg, gap=4, labels=labels, width=width, delete_cells=frames_dir is None)
    if frames_dir is None:
        shutil.rmtree(fdir, ignore_errors=True)
    return out


def _fcurves(ob):
    ad = ob.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    if hasattr(act, "fcurves"):
        try:
            return list(act.fcurves)
        except Exception:
            pass
    out = []   # Blender 5 layered actions
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in strip.channelbags:
                out += list(bag.fcurves)
    return out


def presets_job(spec, out, look="light", res=(800, 500), samples=96, livery=None, labels=True, width=None, lod=""):
    tmp = tempfile.mkdtemp(prefix="lightbox_")
    cells = []
    for pr in PRESETS:
        reset()
        setup_render(res, samples)
        a = import_asset(spec, lod)
        lv = livery if livery is not None else default_livery(a)
        if lv is not None:
            set_livery(a, lv)
        build_studio(a, look)
        cam = shoot_camera(a, pr, res)
        cells.append(dict(path=render(cam, os.path.join(tmp, f"{pr}.png")), label=pr))
    rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
    bg = (235, 235, 235) if look == "light" else (6, 6, 7)
    make_sheet(rows, out, cols=4, bg=bg, gap=4, labels=labels, width=width, delete_cells=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


# ------------------------------------------------------------------ CLI


def _cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    mode = argv[0] if argv else "still"

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    def res(default):
        r = opt("--res")
        return tuple(int(v) for v in r.split("x")) if r else default

    samples = opt("--samples")
    looks = opt("--look", "light")
    looks = ["light", "dark"] if looks == "both" else [looks]
    lod = opt("--lod", "")
    labels = opt("--labels", "1") != "0"
    width = int(opt("--width")) if opt("--width") else None
    livery = opt("--livery")
    asset = opt("--asset", "tsubame")
    out_dir = os.path.join(ROOT, "docs", "agents", "lightbox")
    name = os.path.splitext(os.path.basename(asset))[0]

    for look in looks:
        def out(default):
            o = opt("--out")
            if o and len(looks) > 1:
                b, e = os.path.splitext(o)
                o = f"{b}_{look}{e}"
            return o or os.path.join(out_dir, default)

        if mode == "still":
            pr = opt("--preset", "front34")
            still(asset, out(f"{name}_{pr}_{look}.png"), pr, look, livery, res((1600, 1000)),
                  int(samples or 128), lod, float(opt("--yaw", "0")))
        elif mode == "grid":
            specs = opt("--assets", ",".join(FLEET_ORDER)).split(",")
            grid_job(specs, out(f"grid_{look}.png"), look, opt("--preset", "front34"), res((960, 600)),
                     int(samples or 128), int(opt("--cols", "3")), labels=labels, width=width, lod=lod)
        elif mode == "liveries":
            liveries_job([asset], out(f"{name}_liveries_{look}.png"), look, opt("--preset", "front34"),
                         res((480, 300)), int(samples or 64), int(opt("--cols", "4")), labels, width, lod)
        elif mode == "fleet":
            vids = opt("--assets", ",".join(FLEET_ORDER)).split(",")
            liveries_job(vids, out(f"fleet_liveries_{look}.png"), look, opt("--preset", "front34"),
                         res((480, 300)), int(samples or 64), 8, labels, width or 1600, lod)
        elif mode == "turntable":
            el = opt("--elev")
            turntable_job(asset, out(f"{name}_turntable_{look}.png"), look, int(opt("--frames", "8")),
                          res((800, 500)), int(samples or 96), livery, "--anim" in argv, opt("--blend"),
                          int(opt("--cols", "4")), labels, width, lod, opt("--frames-dir"),
                          float(el) if el else None)
        elif mode == "presets":
            presets_job(asset, out(f"{name}_presets_{look}.png"), look, res((800, 500)), int(samples or 96),
                        livery, labels, width, lod)
        else:
            raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    _cli()
